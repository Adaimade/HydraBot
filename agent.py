#!/usr/bin/env python3
"""
HydraBot — AgentPool
Manages multiple model clients, shared tools, and parallel sub-agent spawning.
Includes: scheduled notifications and real-time task progress reporting.
"""

from __future__ import annotations

import json
import asyncio
import importlib.util
import os
import traceback
import threading
import concurrent.futures
import uuid
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from scheduler import NotificationScheduler, parse_fire_at, REPEAT_INTERVALS
from learning import ExperienceLog, is_likely_failure


def _atomic_write_json(path: Path, data, **kwargs):
    """原子寫入 JSON：先寫臨時檔再 rename，避免半截寫入。"""
    try:
        text = json.dumps(data, ensure_ascii=False, indent=1, default=str, **kwargs)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            Path(tmp).replace(path)
        except Exception:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
            raise
    except Exception:
        pass

try:
    import cli_render  # CLI 精簡輸出（可選；缺失時不影響 TG/DC）
except ImportError:
    cli_render = None  # type: ignore[misc, assignment]


# Maximum number of tool-call iterations per agent loop turn
MAX_TOOL_CALLS = 30


def _ollama_list_models_from_openai_base_url(openai_base_url: str | None) -> list[str] | None:
    """
    If openai_base_url points at Ollama's OpenAI-compatible shim, query native /api/tags.
    Returns [] if Ollama responded but has no models; None if not Ollama or unreachable.
    """
    if not openai_base_url or not str(openai_base_url).strip():
        return None
    try:
        import requests

        p = urlparse(str(openai_base_url).strip())
        if not p.scheme or not p.netloc:
            return None
        origin = f"{p.scheme}://{p.netloc}"
        r = requests.get(f"{origin.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict) or "models" not in data:
            return None
        models = data.get("models") or []
        names: list[str] = []
        for m in models:
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
        return names
    except Exception:
        return None


def _safe_step_key(name: str, fallback: str) -> str:
    n = (name or "").strip()
    if not n:
        return fallback
    # Keep keys stable and safe for dict addressing / template replacement
    out = []
    for ch in n:
        if ch.isalnum() or ch in ("_", "-", ".", " "):
            out.append(ch)
    key = "".join(out).strip().replace(" ", "_")
    return key or fallback

# ─────────────────────────────────────────────────────────────
# Internal single-model client
# ─────────────────────────────────────────────────────────────

class _ModelClient:
    """Wraps one model's API connection."""

    def __init__(self, cfg: dict, max_tokens: int):
        self.cfg = cfg
        self.name = cfg.get("name", cfg.get("model", "unknown"))
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.max_tokens = max_tokens
        self._init()

    def _init(self):
        key = self.cfg["api_key"]
        base_url = self.cfg.get("base_url")

        if self.provider == "anthropic":
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
            except ImportError:
                raise ImportError("Run: pip install anthropic")

        elif self.provider in ("openai", "openai-compatible"):
            try:
                import openai
                kwargs: dict = {"api_key": key}
                if base_url:
                    kwargs["base_url"] = base_url
                self.client = openai.OpenAI(**kwargs)
            except ImportError:
                raise ImportError("Run: pip install openai")

        elif self.provider == "google":
            # Google Gemini via OpenAI-compatible endpoint
            try:
                import openai
                self.client = openai.OpenAI(
                    api_key=key,
                    base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
                )
                # Use openai loop internally
                self.provider = "openai"
            except ImportError:
                raise ImportError("Run: pip install openai")

        else:
            raise ValueError(
                f"Unknown provider: '{self.provider}'. "
                f"Use 'anthropic', 'openai', 'openai-compatible', or 'google'."
            )


# ─────────────────────────────────────────────────────────────
# AgentPool — main public class
# ─────────────────────────────────────────────────────────────

class AgentPool:
    """
    Manages multiple model configurations, a shared tool registry,
    and background sub-agent task execution.

    Drop-in replacement for the old Agent class.
    """

    def __init__(self, config: dict, *, data_prefix: str = ""):
        """
        data_prefix — 非空時使用獨立資料檔（例如 Discord：\"discord_\" → discord_memory.json）。
        Telegram 預設為 \"\"（memory.json、schedules.json、timezones.json）。
        """
        self.config = config
        _here = Path(__file__).resolve().parent
        self.install_dir = Path(
            config.get("_hydrabot_install_dir") or str(_here)
        ).resolve()
        self.workspace_dir = Path(
            config.get("_hydrabot_workspace_dir") or str(self.install_dir)
        ).resolve()
        # Tool trace switches:
        # - tool_trace_stdout: print each tool call/result to process stdout
        # - tool_trace_to_chat: also push concise trace lines back to current chat session
        self.tool_trace_stdout = bool(config.get("tool_trace_stdout", True))
        self.tool_trace_to_chat = bool(config.get("tool_trace_to_chat", False))
        self.enforce_gate_policy = bool(config.get("enforce_gate_policy", True))
        self.gate_forbidden_in_qa = bool(config.get("gate_forbidden_in_qa", True))
        self.require_gate_before_done = bool(config.get("require_gate_before_done", True))
        # CLI 專用：精簡工具列印（類 Claude Code 階層／摺疊）
        self.cli_compact_ui = bool(config.get("cli_compact_ui", True))

        # 安全權限
        _pm = str(config.get("permission_mode", "auto")).lower().strip()
        if _pm not in ("default", "auto", "readonly"):
            _pm = "auto"
        self.permission_mode: str = _pm
        self.denied_commands: list[str] = [
            s.lower().strip() for s in config.get("denied_commands", []) if s
        ]
        self.denied_paths: list[str] = [
            str(Path(s).expanduser().resolve())
            for s in config.get("denied_paths", []) if s
        ]
        self._cli_approval_callback = None  # set by cli.py for interactive y/n
        self._stream_callback = None  # set by cli.py: callback(chunk_str | None=flush)
        self.dry_run: bool = bool(config.get("dry_run", False))

        # Token 追蹤
        self._token_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "api_calls": 0,
        }
        self._session_token_usage: dict[tuple, dict[str, int]] = {}
        self._usage_lock = threading.Lock()
        self._data_prefix = data_prefix or ""
        _mem = (
            f"{self._data_prefix}memory.json"
            if self._data_prefix
            else "memory.json"
        )
        self._memory_path = self.install_dir / _mem
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_history = config.get("max_history", 50)

        # Model configs parsed from config.json
        self.model_configs: list[dict] = self._parse_models(config)

        # 三層模型角色映射  { "primary"/"fast"/"daily" -> model_index }
        self.model_roles: dict[str, int] = self._parse_model_roles()

        # 子代理路由：任務類型 → tier 名稱 → model_index（由 _parse_spawn_routing 解析）
        self.spawn_routing: dict[str, str] = self._parse_spawn_routing()

        # Lazy-init model clients  { index -> _ModelClient }
        self._clients: dict[int, _ModelClient] = {}
        self._clients_lock = threading.Lock()

        # Shared tool registry  { name -> (schema, callable) }
        self.tools: dict[str, tuple] = {}

        # Conversation history  { session_id -> [messages] }
        # session_id = (chat_id, thread_id)  — chat_id is the TG group/private chat,
        # thread_id is the Telegram Topic ID (None for non-topic chats).
        # This lets each group / topic maintain a fully independent context.
        self.conversations: dict[tuple, list] = {}
        self._conv_lock = threading.Lock()

        # Each session's preferred primary model index (default: 0)
        self.user_model: dict[tuple, int] = {}

        # Sub-agent task tracking  { task_id -> info_dict }
        self.running_tasks: dict[str, dict] = {}
        self._tasks_lock = threading.Lock()  # guards running_tasks

        # Per-session Python namespaces for execute_python isolation
        self._py_namespaces: dict[tuple, dict] = {}
        self._py_ns_lock = threading.Lock()

        # Thread pool for background sub-agents (max 6 concurrent)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=6, thread_name_prefix="hydra_sub"
        )

        # Set by bot after startup:  pool._loop / pool._send_func
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_func = None   # async (session_id: tuple, text: str) -> None

        # Notification scheduler (started by bot / Discord on_ready)
        _sched_name = (
            f"{self._data_prefix}schedules.json"
            if self._data_prefix
            else "schedules.json"
        )
        self.scheduler = NotificationScheduler(
            schedules_file=self.install_dir / _sched_name
        )

        # User timezone offsets  { session_id -> UTC offset hours (int) }
        # e.g. UTC+8 → 8,  UTC-5 → -5
        self.user_timezones: dict[tuple, int] = {}
        _tz_name = (
            f"{self._data_prefix}timezones.json"
            if self._data_prefix
            else "timezones.json"
        )
        self._tz_file = self.install_dir / _tz_name
        self._load_timezones()

        # 學習回路：結構化長期記憶 + TF-IDF 語意檢索
        _exp_name = f"{self._data_prefix}experience_log.json"
        self.experience = ExperienceLog(log_path=self.install_dir / _exp_name)

        # Load tools
        self._load_builtin_tools()
        self._load_dynamic_tools()

    @staticmethod
    def _is_cli_session(session_id) -> bool:
        """終端機模式固定 session (0, None)。"""
        return session_id == (0, None)

    def _use_compact_cli_trace(self, session_id) -> bool:
        return (
            cli_render is not None
            and self.cli_compact_ui
            and self._is_cli_session(session_id)
            and self.tool_trace_stdout
        )

    def resolve_workspace_path(self, path: str) -> Path:
        """相對路徑以 workspace_dir 為根；絕對路徑不變。"""
        p = Path(path).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (self.workspace_dir / p).resolve()

    GATE_TOOL_NAMES = {
        "quick_fix_then_gate",
        "format_and_fix",
        "run_validation",
        "quality_gate",
    }
    COMPLETION_PATTERNS = (
        r"已完成",
        r"完成修正",
        r"修正完成",
        r"可交付",
        r"可提交",
        r"全部完成",
        r"處理完成",
        r"finished",
        r"done",
    )
    CODE_CHANGE_PATTERNS = (
        r"改檔",
        r"修改(程式|代碼|code|檔案)",
        r"修(復|正)?\s*bug",
        r"修正錯誤",
        r"除錯",
        r"重構",
        r"refactor",
        r"fix\s+bug",
        r"產出可提交程式碼",
        r"提交程式碼",
    )

    # ─────────────────────────────────────────────
    # Python namespace per session
    # ─────────────────────────────────────────────

    def get_py_namespace(self, session_id: tuple) -> dict:
        """Return the Python execution namespace for a session, creating if needed."""
        with self._py_ns_lock:
            if session_id not in self._py_namespaces:
                self._py_namespaces[session_id] = {"__builtins__": __builtins__}
            return self._py_namespaces[session_id]

    def reset_py_namespace(self, session_id: tuple):
        """Clear the Python namespace for a session."""
        with self._py_ns_lock:
            self._py_namespaces.pop(session_id, None)

    # ─────────────────────────────────────────────
    # Config parsing (supports old & new format)
    # ─────────────────────────────────────────────

    # ── 三層模型角色 ──────────────────────────────────────────────

    _MODEL_TIERS = ("primary", "fast", "daily")

    def _parse_model_roles(self) -> dict[str, int]:
        """解析 config.model_roles，將 primary/fast/daily 對應到 model array 索引。
        預設：primary=0, fast=1, daily=2（若只有 1 或 2 組模型則以最大可用索引補足）。
        """
        n = len(self.model_configs)
        raw = (self.config or {}).get("model_roles") or {}
        defaults = {"primary": 0, "fast": min(1, n - 1), "daily": min(2, n - 1)}
        out: dict[str, int] = {}
        for tier, default_idx in defaults.items():
            try:
                idx = int(raw.get(tier, default_idx))
            except (TypeError, ValueError):
                idx = default_idx
            out[tier] = max(0, min(idx, n - 1))
        return out

    # ── 任務類型 → tier 路由 ──────────────────────────────────────

    _TASK_ROLES = frozenset(
        ("auto", "reading", "writing", "review", "advice", "debug", "general")
    )

    def _parse_spawn_routing(self) -> dict[str, str]:
        """解析 config.spawn_routing，回傳 task_type → tier_name 的對應表。
        預設語意（可在 config.json 的 spawn_routing 覆寫）：
          - 高強度任務（writing/review/debug）→ primary
          - 輕量任務（reading/advice/general）→ fast 或 daily
        """
        raw = (self.config or {}).get("spawn_routing") or {}
        valid_tiers = set(self._MODEL_TIERS)
        defaults: dict[str, str] = {
            "reading": "daily",
            "writing": "primary",
            "review": "primary",
            "advice": "fast",
            "debug": "primary",
            "general": "fast",
        }
        out: dict[str, str] = {}
        for task_type, default_tier in defaults.items():
            v = str(raw.get(task_type, default_tier)).lower()
            out[task_type] = v if v in valid_tiers else default_tier
        return out

    def _infer_spawn_task_role(self, task: str) -> str:
        """依任務文字粗略分類（中英關鍵字），供 task_role=auto 時使用。"""
        if not (task or "").strip():
            return "general"
        t = task.lower()
        if any(
            k in task
            for k in ("抓 bug", "除錯", "偵錯", "traceback", "堆疊", "錯誤原因", "為何失敗")
        ) or any(
            k in t
            for k in ("find bug", "bug hunt", "fix bug", "stack trace", "debug", "root cause")
        ):
            return "debug"
        if any(k in task for k in ("審查", "code review", "檢視程式")) or any(
            k in t for k in ("review code", "audit code", "code audit")
        ):
            return "review"
        if any(
            k in task
            for k in ("撰寫", "實作", "程式碼", "實現功能", "refactor", "重構")
        ) or any(
            k in t for k in ("write code", "implement", "refactor", "build feature")
        ):
            return "writing"
        if any(
            k in task
            for k in ("讀取", "閱讀", "摘要", "整理文件", "萃取", "parse")
        ) or any(
            k in t for k in ("summarize", "read file", "extract", "parse document")
        ):
            return "reading"
        if any(k in task for k in ("建議", "建議方案", "有何看法")) or any(
            k in t for k in ("advise", "suggest", "recommend", "opinion")
        ):
            return "advice"
        return "general"

    def tier_to_model_index(self, tier: str) -> int:
        """tier 名稱 → model array 索引，未知 tier 退回 primary。"""
        return self.model_roles.get(tier, self.model_roles["primary"])

    def resolve_spawn_model(
        self,
        task: str,
        task_role: str = "auto",
        model_index: int | None = None,
    ) -> tuple[int, str, str]:
        """
        決定子代理使用的模型索引。
        優先順序：
          1. model_index 非 None → 使用者明確指定，直接用
          2. task_role 非 auto → 查 spawn_routing 得到 tier，再查 model_roles 得到 index
          3. task_role=auto → 依任務文字推斷 task_type，再走 2
        回傳：(model_idx, resolved_tier, 路由說明行)
        """
        n = len(self.model_configs)
        if model_index is not None:
            try:
                idx = max(0, min(int(float(model_index)), n - 1))
            except (TypeError, ValueError):
                pass
            else:
                m = self.model_configs[idx]
                return idx, "manual", f"使用者指定模型索引 **{idx}**（{m.get('name', m['model'])}）"

        r = (task_role or "auto").strip().lower()
        if r not in self._TASK_ROLES:
            r = "auto"
        if r == "auto":
            r = self._infer_spawn_task_role(task)

        tier = self.spawn_routing.get(r, "fast")
        idx  = self.tier_to_model_index(tier)
        m    = self.model_configs[idx]
        tier_zh = {"primary": "主力", "fast": "快速", "daily": "日常"}.get(tier, tier)
        return idx, tier, f"任務類型 `{r}` → **{tier_zh}模型**（{m.get('name', m['model'])}）"

    def _parse_models(self, cfg: dict) -> list[dict]:
        """Support both new `models` array and old single-model keys."""
        if "models" in cfg and cfg["models"]:
            # Filter out comment-only entries
            return [m for m in cfg["models"] if "provider" in m]

        # Backward compatibility: single model
        return [{
            "name": "預設模型",
            "provider": cfg.get("model_provider", "anthropic"),
            "api_key": cfg.get("model_api_key", ""),
            "model": cfg.get("model_name", "claude-sonnet-4-6"),
            "base_url": cfg.get("base_url"),
            "description": "主模型",
        }]

    # ─────────────────────────────────────────────
    # Client access
    # ─────────────────────────────────────────────

    def get_client(self, model_idx: int) -> _ModelClient:
        idx = model_idx % len(self.model_configs)
        with self._clients_lock:
            if idx not in self._clients:
                self._clients[idx] = _ModelClient(
                    self.model_configs[idx], self.max_tokens
                )
            return self._clients[idx]

    # ─────────────────────────────────────────────
    # Public chat API
    # ─────────────────────────────────────────────

    def chat(self, session_id: tuple, message: str) -> str:
        """Synchronous — call via loop.run_in_executor from bot.

        session_id = (chat_id, thread_id)
          chat_id   : Telegram chat/group ID (unique per private chat or group)
          thread_id : Telegram Topic/Thread ID, or None for non-topic chats
        Each unique (chat_id, thread_id) gets its own isolated conversation history.
        """
        model_idx = self.user_model.get(session_id, 0)

        with self._conv_lock:
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            history = self.conversations[session_id]
            history.append({"role": "user", "content": message})
            history_snapshot = list(history)

        turn_state = self._build_turn_state(message)

        # Build session tools (includes session-bound spawn_agent)
        session_tools = self._session_tools(session_id)

        # Let builtin tools (execute_python) know which session is active
        import tools_builtin
        tools_builtin.current_session_id[0] = session_id

        try:
            client = self.get_client(model_idx)
            if client.provider == "anthropic":
                response = self._anthropic_loop(
                    client,
                    history_snapshot,
                    session_tools,
                    session_id,
                    turn_state,
                )
            else:
                response = self._openai_loop(
                    client,
                    history_snapshot,
                    session_tools,
                    session_id,
                    turn_state,
                )
        except Exception as e:
            extra = ""
            es = str(e).lower()
            if "not found" in es and "model" in es:
                cfg = self.model_configs[model_idx % len(self.model_configs)]
                bu = cfg.get("base_url")
                ollama_names = _ollama_list_models_from_openai_base_url(bu)
                if ollama_names is not None:
                    if not ollama_names:
                        extra = (
                            "\n\n💡 已連到本機 Ollama（/api/tags），但目前**沒有已下載的模型**。"
                            "請執行 `ollama pull <模型名>`，再用 `hydrabot config` 把該槽的 `model`"
                            "設成與 `ollama list` **完全一致**的名稱。"
                        )
                    else:
                        show = ollama_names[:15]
                        tail = "、".join(show)
                        suffix = f"（另有 {len(ollama_names) - 15} 個未列出）" if len(ollama_names) > 15 else ""
                        extra = (
                            f"\n\n💡 本機 Ollama 目前可用的模型：`{tail}`{suffix}（與終端 `ollama list` 相同）。"
                            f"請將 **{cfg.get('name') or '該'}** 槽的 `model` 改成上列其中一個（須完全一致，含標籤）。"
                        )
                else:
                    extra = (
                        "\n\n💡 模型名稱或端點不符：請用 `hydrabot config` 檢查 `model` 與 `base_url`。"
                        "若為本機 Ollama，請確認服務在跑且 `base_url` 形如 `http://127.0.0.1:11434/v1`，"
                        "並執行 `ollama list` / `ollama pull <名稱>` 後讓 `model` 與列表一致。"
                    )
            response = f"❌ Agent error: {e}{extra}\n```\n{traceback.format_exc()}\n```"
            print(response)

        response = self._enforce_completion_rule(response, turn_state)

        with self._conv_lock:
            history = self.conversations.get(session_id, [])
            history.append({"role": "assistant", "content": response})
            if len(history) > self.max_history:
                self.conversations[session_id] = history[-self.max_history:]

        self._maybe_compact_context(session_id)

        # 失敗自動記錄：偵測到錯誤訊號時寫入經驗庫，供下次 recall 參考
        if is_likely_failure(response):
            try:
                self.experience.record_failure(
                    user_message=message,
                    bot_response=response,
                )
            except Exception:
                pass

        self.save_session(session_id)
        return response

    # ─────────────────────────────────────────────
    # Context compaction
    # ─────────────────────────────────────────────

    def _maybe_compact_context(self, session_id):
        """當 history 達到 max_history 的 80% 時，將前半段壓縮成摘要。"""
        with self._conv_lock:
            history = self.conversations.get(session_id)
            if not history:
                return
            threshold = int(self.max_history * 0.8)
            if len(history) < threshold:
                return
            keep_recent = max(6, self.max_history // 4)
            old_part = list(history[:-keep_recent])
            if len(old_part) < 4:
                return
            recent_part = list(history[-keep_recent:])

        summary_text = self._summarize_messages(old_part, session_id)
        if not summary_text:
            return

        compact_msg = {
            "role": "user",
            "content": (
                "[系統摘要] 以下是先前對話的精簡摘要，原始對話已壓縮以節省 token：\n\n"
                f"{summary_text}"
            ),
        }
        with self._conv_lock:
            self.conversations[session_id] = [compact_msg] + recent_part

    def _summarize_messages(self, messages: list[dict], session_id) -> str | None:
        """用快速模型將多條訊息壓縮為摘要。"""
        try:
            fast_idx = self.model_roles.get("fast", self.model_roles.get("daily", 0))
            client = self.get_client(fast_idx)

            text_parts = []
            for m in messages:
                role = m.get("role", "?")
                content = str(m.get("content", ""))
                if len(content) > 300:
                    content = content[:300] + "…"
                text_parts.append(f"[{role}] {content}")

            combined = "\n".join(text_parts)
            if len(combined) > 6000:
                combined = combined[:6000] + "\n…（已截斷）"

            prompt = (
                "請將以下多輪對話壓縮為重點摘要（繁體中文），保留關鍵決策、已完成事項、"
                "待辦事項、重要數據。用簡潔列點呈現，不超過 500 字：\n\n"
                f"{combined}"
            )

            if client.provider == "anthropic":
                resp = client.client.messages.create(
                    model=client.model,
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )
                if hasattr(resp, "usage") and resp.usage:
                    self._record_usage(session_id,
                        getattr(resp.usage, "input_tokens", 0),
                        getattr(resp.usage, "output_tokens", 0))
                return resp.content[0].text if resp.content else None
            else:
                resp = client.client.chat.completions.create(
                    model=client.model,
                    max_tokens=600,
                    messages=[
                        {"role": "system", "content": "你是摘要助手。"},
                        {"role": "user", "content": prompt},
                    ],
                )
                if hasattr(resp, "usage") and resp.usage:
                    self._record_usage(session_id,
                        getattr(resp.usage, "prompt_tokens", 0),
                        getattr(resp.usage, "completion_tokens", 0))
                return resp.choices[0].message.content if resp.choices else None
        except Exception:
            return None

    # ─────────────────────────────────────────────
    # Session persistence
    # ─────────────────────────────────────────────

    def _sessions_dir(self) -> Path:
        d = self.install_dir / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _session_file(self, session_id) -> Path:
        safe = f"{session_id[0]}_{session_id[1]}"
        return self._sessions_dir() / f"{safe}.json"

    def save_session(self, session_id):
        with self._conv_lock:
            history = self.conversations.get(session_id)
            if not history:
                return
            data = {
                "session_id": list(session_id),
                "model_idx": self.user_model.get(session_id, 0),
                "history": list(history[-self.max_history:]),
                "usage": self._session_token_usage.get(session_id, {}),
            }
        _atomic_write_json(self._session_file(session_id), data)

    def load_session(self, session_id) -> bool:
        p = self._session_file(session_id)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            with self._conv_lock:
                self.conversations[session_id] = data.get("history", [])
                self.user_model[session_id] = data.get("model_idx", 0)
            with self._usage_lock:
                self._session_token_usage[session_id] = data.get("usage", {
                    "prompt_tokens": 0, "completion_tokens": 0, "api_calls": 0,
                })
            return True
        except Exception:
            return False

    def list_saved_sessions(self) -> list[str]:
        d = self._sessions_dir()
        return [f.stem for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)]

    def reset_conversation(self, session_id: tuple):
        with self._conv_lock:
            self.conversations.pop(session_id, None)
        self.reset_py_namespace(session_id)
        try:
            self._session_file(session_id).unlink(missing_ok=True)
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Model management
    # ─────────────────────────────────────────────

    def switch_model(self, session_id: tuple, model_idx: int) -> str:
        n = len(self.model_configs)
        if not (0 <= model_idx < n):
            return f"❌ 無效索引，請輸入 0–{n - 1}"
        self.user_model[session_id] = model_idx
        m = self.model_configs[model_idx]
        return (
            f"✅ 已切換至 **模型 {model_idx}**\n"
            f"名稱: {m.get('name', m['model'])}\n"
            f"模型: `{m['model']}` ({m['provider']})"
        )

    def list_models_info(self, session_id: tuple) -> str:
        current = self.user_model.get(session_id, 0)
        lines = [f"🤖 **可用模型** ({len(self.model_configs)} 組)\n"]
        for i, m in enumerate(self.model_configs):
            tag = "▶️ 目前" if i == current else f"  `{i}` "
            lines.append(f"{tag} **{m.get('name', m['model'])}**")
            lines.append(f"      `{m['provider']}` / `{m['model']}`")
            if m.get("description"):
                lines.append(f"      {m['description']}")
            lines.append("")
        switch_examples = "  ".join(f"`/model {i}`" for i in range(len(self.model_configs)))
        lines.append(f"切換指令: {switch_examples}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Sub-agent spawning
    # ─────────────────────────────────────────────

    def spawn_sub_agent(
        self,
        session_id: tuple,
        task: str,
        model_index: int,
        name: str = "",
        *,
        routing_note: str = "",
    ) -> str:
        """Spawn a background sub-agent. Returns immediately.
        session_id = (chat_id, thread_id) — result is delivered back to this session.
        name — optional human-readable label for this sub-agent.
        routing_note — 可選，說明為何選此模型（自動路由或手動指定）。
        """
        n = len(self.model_configs)
        model_index = max(0, min(model_index, n - 1))

        client = self.get_client(model_index)
        task_id = f"sub_{uuid.uuid4().hex[:6]}"
        display_name = name.strip() if name and name.strip() else task_id

        with self._tasks_lock:
            self.running_tasks[task_id] = {
                "id": task_id,
                "name": display_name,
                "task": task[:60] + ("…" if len(task) > 60 else ""),
                "model": client.name,
                "model_idx": model_index,
                "status": "running",
                "session_id": session_id,
            }

        pool = self

        def _push(msg: str):
            """Thread-safe helper: push a message to the originating session."""
            if pool._send_func and pool._loop:
                asyncio.run_coroutine_threadsafe(
                    pool._send_func(session_id, msg), pool._loop
                )

        def _run():
            try:
                # Sub-agents use only builtin tools (no spawn_agent → no recursion)
                sub_tools = dict(pool.tools)

                # Inject a session-bound report_progress tool so the LLM can
                # push intermediate updates without waiting for task completion.
                def report_progress(message: str) -> str:
                    with pool._tasks_lock:
                        pool.running_tasks[task_id]["progress"] = message
                    _push(
                        f"📊 **{display_name}** 進度更新\n"
                        f"模型: {client.name} | `{task_id}`\n\n"
                        f"{message}"
                    )
                    return "✅ 進度已推送給用戶"

                sub_tools["report_progress"] = ({
                    "name": "report_progress",
                    "description": (
                        "將目前的任務進度即時推送給用戶。\n"
                        "在長時間執行的任務中，可定期呼叫此工具讓用戶知道進展。"
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "進度更新訊息（可包含目前完成步驟、百分比、中間結果等）",
                            }
                        },
                        "required": ["message"],
                    },
                }, report_progress)

                if client.provider == "anthropic":
                    result = pool._anthropic_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        session_id=None,  # sub-agent has no persistent session history
                    )
                else:
                    result = pool._openai_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        session_id=None,
                    )

                with pool._tasks_lock:
                    pool.running_tasks[task_id]["status"] = "done"
                msg = (
                    f"🤖 **{display_name}** 已完成\n"
                    f"模型: {client.name} | `{task_id}`\n\n"
                    f"{result}"
                )
            except Exception as e:
                with pool._tasks_lock:
                    pool.running_tasks[task_id]["status"] = "error"
                msg = (
                    f"❌ **{display_name}** 執行失敗\n"
                    f"模型: {client.name} | `{task_id}`\n"
                    f"錯誤: {str(e)}"
                )

            # Deliver final result back to the originating session
            _push(msg)

        self._executor.submit(_run)

        route_line = f"{routing_note}\n" if routing_note else ""
        return (
            f"✅ 子代理 **{display_name}** 已啟動 (`{task_id}`)\n"
            f"模型: **{client.name}**\n"
            f"{route_line}"
            f"任務: {task[:80]}\n\n"
            f"⏳ 後台運行中，完成後自動推送結果 📨"
        )

    # ─────────────────────────────────────────────
    # Pipeline runner (multi-step orchestration)
    # ─────────────────────────────────────────────

    def run_pipeline(
        self,
        session_id: tuple,
        steps: list[dict],
        *,
        parallel: bool = True,
        include_outputs_in_prompt: bool = True,
    ) -> str:
        """Run a multi-step pipeline using tiered sub-agents and collect results.

        steps: list of dict
          required: task (str)
          optional: name (str), task_role (str), depends_on (list[str])

        The pipeline runs in waves:
          - steps with no deps run first (optionally in parallel)
          - steps with deps run after their deps finish
        Each step runs in an isolated sub-agent context (session_id=None).
        """
        if not isinstance(steps, list) or not steps:
            return "❌ steps 必須是非空 list"

        # Normalize and assign stable keys
        norm: list[dict[str, Any]] = []
        name_to_key: dict[str, str] = {}
        key_set: set[str] = set()
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                return f"❌ steps[{i}] 必須是 dict"
            task = str(raw.get("task", "")).strip()
            if not task:
                return f"❌ steps[{i}] 缺少 task"
            name = str(raw.get("name", "")).strip()
            key = _safe_step_key(name, fallback=f"step_{i+1}")
            # Ensure uniqueness
            base = key
            j = 2
            while key in key_set:
                key = f"{base}_{j}"
                j += 1
            key_set.add(key)
            depends = raw.get("depends_on", [])
            if depends is None:
                depends = []
            if isinstance(depends, str):
                depends = [depends]
            if not isinstance(depends, list):
                return f"❌ steps[{i}].depends_on 必須是 list[str]"
            depends = [str(x).strip() for x in depends if str(x).strip()]
            role = str(raw.get("task_role", "auto")).strip() or "auto"
            if name:
                # Map both raw name and safe key form to the resolved key
                name_to_key.setdefault(name, key)
                name_to_key.setdefault(_safe_step_key(name, fallback=name), key)
            norm.append(
                {
                    "key": key,
                    "name": name or key,
                    "task": task,
                    "task_role": role,
                    "depends_on": depends,
                }
            )

        # Resolve depends_on entries: allow referencing by step key OR step name
        known = {s["key"] for s in norm}
        for s in norm:
            resolved: list[str] = []
            for d in s["depends_on"]:
                if d in known:
                    resolved.append(d)
                    continue
                if d in name_to_key:
                    resolved.append(name_to_key[d])
                    continue
                # Also try safe-key normalization
                sk = _safe_step_key(d, fallback=d)
                if sk in known:
                    resolved.append(sk)
                    continue
                if sk in name_to_key:
                    resolved.append(name_to_key[sk])
                    continue
                resolved.append(d)
            s["depends_on"] = resolved

        # Validate dependencies reference known keys
        for s in norm:
            bad = [d for d in s["depends_on"] if d not in known]
            if bad:
                return (
                    f"❌ pipeline 步驟 `{s['key']}` 依賴不存在的 step: {', '.join(bad)}\n"
                    f"可用 steps: {', '.join(sorted(known))}"
                )

        # Step outputs
        outputs: dict[str, str] = {}
        statuses: dict[str, str] = {}

        def _push(text: str):
            if self._send_func and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_func(session_id, text), self._loop
                )

        def _render_task(template: str, dep_keys: list[str]) -> str:
            # Very small templating: {{step_key}} gets replaced with that output.
            rendered = template
            for k in dep_keys:
                rendered = rendered.replace(f"{{{{{k}}}}}", outputs.get(k, ""))
            if include_outputs_in_prompt and dep_keys:
                dep_pack = "\n\n".join(
                    f"[{k}]\n{outputs.get(k, '')}".strip()[:4000] for k in dep_keys
                )
                rendered = (
                    f"{rendered}\n\n"
                    f"---\n"
                    f"以下是前置步驟輸出（供你參考整合）：\n{dep_pack}\n"
                    f"---"
                )
            return rendered

        def _run_step(step: dict[str, Any]) -> tuple[str, str, str]:
            key = step["key"]
            name = step["name"]
            deps = step["depends_on"]
            task = _render_task(step["task"], deps)
            idx, tier, note = self.resolve_spawn_model(task, step["task_role"], None)
            client = self.get_client(idx)
            sub_tools = dict(self.tools)  # no spawn_agent recursion

            # Provide progress hook inside a pipeline step
            def report_progress(message: str) -> str:
                _push(
                    f"📊 **Pipeline/{name}** 進度更新\n"
                    f"模型: {client.name}（{note}）\n\n"
                    f"{message}"
                )
                return "✅ 進度已推送給用戶"

            sub_tools["report_progress"] = (
                {
                    "name": "report_progress",
                    "description": "將目前任務進度即時推送給用戶（pipeline step）。",
                    "input_schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                },
                report_progress,
            )

            try:
                _push(f"⏳ **Pipeline/{name}** 開始\n模型: {client.name}（{note}）")
                if client.provider == "anthropic":
                    result = self._anthropic_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        session_id=None,
                    )
                else:
                    result = self._openai_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        session_id=None,
                    )
                return key, "done", result
            except Exception as e:
                err = f"❌ Pipeline step 失敗: {e}\n```\n{traceback.format_exc()}\n```"
                return key, "error", err

        # Run in dependency waves
        pending = {s["key"]: s for s in norm}
        while pending:
            ready = [
                s for s in pending.values()
                if all(d in outputs for d in s["depends_on"])
            ]
            if not ready:
                # Cycle or missing deps
                left = ", ".join(sorted(pending.keys()))
                return f"❌ pipeline 依賴無法滿足（可能循環依賴）：{left}"

            if parallel and len(ready) > 1:
                futs = [
                    self._executor.submit(_run_step, s)
                    for s in ready
                ]
                for f in futs:
                    key, st, out = f.result()
                    statuses[key] = st
                    outputs[key] = out
                    pending.pop(key, None)
            else:
                for s in ready:
                    key, st, out = _run_step(s)
                    statuses[key] = st
                    outputs[key] = out
                    pending.pop(key, None)

        # Summarize for the caller (LLM)
        lines = ["✅ Pipeline 已完成\n"]
        for s in norm:
            key = s["key"]
            name = s["name"]
            st = statuses.get(key, "unknown")
            icon = "✅" if st == "done" else ("❌" if st == "error" else "❓")
            snippet = (outputs.get(key, "") or "").strip()
            snippet = snippet[:500] + ("…" if len(snippet) > 500 else "")
            lines.append(f"{icon} **{name}** (`{key}`)\n{snippet}\n")
        return "\n".join(lines).strip()

    def list_tasks_info(self) -> str:
        with self._tasks_lock:
            tasks_snapshot = dict(self.running_tasks)
        if not tasks_snapshot:
            return "📋 目前沒有子代理任務記錄"
        lines = [f"📋 **子代理任務** （{len(tasks_snapshot)} 筆）\n"]
        for t in sorted(tasks_snapshot.values(), key=lambda x: x["id"], reverse=True)[:10]:
            emoji = {"running": "⏳", "done": "✅", "error": "❌"}.get(t["status"], "❓")
            name = t.get("name", t["id"])
            # Show name prominently; show task_id in parentheses only if name differs
            id_suffix = f" (`{t['id']}`)" if name != t["id"] else f" `{t['id']}`"
            lines.append(f"{emoji} **{name}**{id_suffix} — {t['model']}")
            lines.append(f"   {t['task']}")
            # Show latest progress update if available
            if t.get("progress") and t["status"] == "running":
                prog = t["progress"]
                short = prog[:80] + "…" if len(prog) > 80 else prog
                lines.append(f"   📊 進度: {short}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Session tools (inject spawn_agent with bound user_id)
    # ─────────────────────────────────────────────

    def _session_tools(self, session_id: tuple) -> dict:
        """Shallow-copy tools and inject session-bound tools:
        - spawn_agent      parallel background sub-agents
        - schedule_notification  schedule a timed message
        - list_notifications     list active schedules for this session
        - cancel_notification    cancel a scheduled notification
        """
        tools = dict(self.tools)
        pool  = self
        n     = len(self.model_configs)
        tier_zh = {"primary": "主力", "fast": "快速", "daily": "日常"}
        tier_desc = "\n".join(
            f"  · **{tier_zh.get(t, t)}（{t}）** → 模型索引 `{pool.model_roles[t]}`"
            f"（{pool.model_configs[pool.model_roles[t]].get('name', pool.model_configs[pool.model_roles[t]]['model'])}）"
            for t in pool._MODEL_TIERS
        )
        route_desc = "\n".join(
            f"  · `{role}` → **{tier_zh.get(tier, tier)}**"
            for role, tier in sorted(pool.spawn_routing.items())
        )
        model_desc = "\n".join(
            f"  {i}: {m.get('name', m['model'])} — {m.get('description', '')}"
            for i, m in enumerate(self.model_configs)
        )

        # ── spawn_agent ────────────────────────────────────────────
        def spawn_agent(
            task: str,
            name: str = "",
            task_role: str = "auto",
            model_index: int | None = None,
        ) -> str:
            idx, resolved_role, note = pool.resolve_spawn_model(
                task, task_role, model_index
            )
            if resolved_role == "manual":
                rnote = note
            else:
                rnote = f"{note}（任務類型 `{resolved_role}`）"
            return pool.spawn_sub_agent(
                session_id, task, idx, name, routing_note=rnote
            )

        tools["spawn_agent"] = ({
            "name": "spawn_agent",
            "description": (
                "在後台啟動子代理，並行處理任務，完成後自動把結果推送給用戶。\n"
                "\n"
                "**三層模型架構**\n"
                f"{tier_desc}\n"
                "\n"
                "**任務類型 → 自動選模型**（task_role=auto 時依任務文字推斷）：\n"
                f"{route_desc}\n"
                "\n"
                "**使用原則**：\n"
                "· 你（主力）負責分析任務、決定拆分方式，並依 task_role 把子任務派給合適強度的模型。\n"
                "· 不必每次問用戶要哪個模型；只有在用戶明確指定模型索引時才填 model_index。\n"
                "· 可同時啟動多個子代理並行分工（建議 ≤ 3 個），各自處理不同子任務後自動回傳。\n"
                "· 子代理可呼叫 report_progress 推送進度；子代理內不可再呼叫 spawn_agent（防止遞迴）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "交給子代理的完整任務描述（越詳細越好，便於自動路由判斷）",
                    },
                    "name": {
                        "type": "string",
                        "description": "子代理顯示名稱，便於識別（例如「文件摘要」、「實作 API」、「Code review」）",
                    },
                    "task_role": {
                        "type": "string",
                        "description": (
                            "任務類型，用於自動選擇模型等級。"
                            "auto=依 task 文字推斷；reading=讀檔/摘要；writing=撰寫程式或長文；"
                            "review=審查；advice=建議與方案；debug=除錯/抓 bug；general=一般輕量。"
                        ),
                        "enum": [
                            "auto",
                            "reading",
                            "writing",
                            "review",
                            "advice",
                            "debug",
                            "general",
                        ],
                    },
                    "model_index": {
                        "type": "integer",
                        "description": (
                            f"可選。僅當用戶明確要求使用某個模型時填 0–{n - 1}；"
                            "省略則完全依 task_role / 自動推斷路由，勿為每個子任務打擾用戶。"
                        ),
                    },
                },
                "required": ["task"],
            },
        }, spawn_agent)

        # ── run_pipeline ─────────────────────────────────────────
        def run_pipeline(
            steps: list,
            parallel: bool = True,
        ) -> str:
            return pool.run_pipeline(session_id, steps, parallel=bool(parallel))

        tools["run_pipeline"] = ({
            "name": "run_pipeline",
            "description": (
                "執行多步驟 Pipeline：主力負責規劃與整合，步驟依 task_role 自動路由到主力/快速/日常層級並行或串行執行。\n"
                "steps 格式（list[dict]）：\n"
                "  - name: 步驟名稱（可省略）\n"
                "  - task: 此步驟任務（必填）\n"
                "  - task_role: auto/reading/writing/review/advice/debug/general（選填，預設 auto）\n"
                "  - depends_on: 依賴的前置步驟（選填；可寫 step key 或 step name）\n"
                "在需要「讀檔→寫程式→審查/除錯」這類常見流程時，優先使用 run_pipeline 以降低使用門檻。\n"
                "注意：如用戶明確要求指定模型索引，才使用 spawn_agent 的 model_index 覆寫；否則一律交由路由表自動選擇。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Pipeline 步驟列表（list[dict]）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "task": {"type": "string"},
                                "task_role": {
                                    "type": "string",
                                    "enum": [
                                        "auto", "reading", "writing", "review",
                                        "advice", "debug", "general",
                                    ],
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["task"],
                        },
                    },
                    "parallel": {
                        "type": "boolean",
                        "description": "同一波可執行步驟是否並行（預設 true）",
                    },
                },
                "required": ["steps"],
            },
        }, run_pipeline)

        # ── schedule_notification ──────────────────────────────────
        repeat_keys = "、".join(REPEAT_INTERVALS.keys())

        def schedule_notification(
            message: str,
            when: str,
            repeat: str = None,
            label: str = "",
        ) -> str:
            """Schedule a notification to be sent at a specific time."""
            from scheduler import utc_to_local, tz_label
            tz_offset = pool.get_timezone(session_id) or 0
            try:
                fire_at_utc = parse_fire_at(when, tz_offset_hours=tz_offset)
            except Exception as e:
                return f"❌ 無法解析時間 `{when}`: {e}"

            # Validate repeat
            if repeat and repeat not in REPEAT_INTERVALS and not str(repeat).isdigit():
                return (
                    f"❌ 無效的 repeat 值: `{repeat}`\n"
                    f"可用: {repeat_keys}，或整數秒數"
                )

            job_id = pool.scheduler.add_job(
                session_id=session_id,
                message=message,
                fire_at=fire_at_utc,
                repeat=repeat or None,
                label=label,
            )
            repeat_str  = f"，重複: **{repeat}**" if repeat else ""
            local_dt    = utc_to_local(fire_at_utc, tz_offset)
            tz_str      = tz_label(tz_offset)
            return (
                f"✅ 排程已建立 `{job_id}`{repeat_str}\n"
                f"觸發時間: `{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str})`\n"
                f"訊息: {message[:80]}"
            )

        tools["schedule_notification"] = ({
            "name": "schedule_notification",
            "description": (
                "排程一條定時通知，到時自動推送給用戶。\n"
                "when 格式:\n"
                "  · ISO 8601: \"2026-03-01T15:00:00\"  (用戶本地時間，會自動依時區轉換)\n"
                "  · 相對時間: \"+30m\" / \"+2h\" / \"+1d\"\n"
                f"repeat 可選值: {repeat_keys}，或整數秒數（不填 = 只發一次）"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "要發送的通知內容",
                    },
                    "when": {
                        "type": "string",
                        "description": "觸發時間，ISO 8601（用戶本地時間）或相對格式 +Nm/+Nh/+Nd",
                    },
                    "repeat": {
                        "type": "string",
                        "description": f"循環間隔: {repeat_keys}，或整數秒數。不填則只發一次。",
                    },
                    "label": {
                        "type": "string",
                        "description": "可選標籤，顯示在通知標題旁",
                    },
                },
                "required": ["message", "when"],
            },
        }, schedule_notification)

        def schedule_task(
            task_description: str,
            when: str,
            repeat: str = None,
            label: str = "",
        ) -> str:
            """到點由本機 Agent 執行任務描述（等同於對該 session 發一則 user 訊息），結果推送給用戶。"""
            from scheduler import utc_to_local, tz_label
            tz_offset = pool.get_timezone(session_id) or 0
            try:
                fire_at_utc = parse_fire_at(when, tz_offset_hours=tz_offset)
            except Exception as e:
                return f"❌ 無法解析時間 `{when}`: {e}"

            if repeat and repeat not in REPEAT_INTERVALS and not str(repeat).isdigit():
                return (
                    f"❌ 無效的 repeat 值: `{repeat}`\n"
                    f"可用: {repeat_keys}，或整數秒數"
                )

            job_id = pool.scheduler.add_job(
                session_id=session_id,
                message=task_description,
                fire_at=fire_at_utc,
                repeat=repeat or None,
                label=label,
                kind="llm_task",
            )
            repeat_str  = f"，重複: **{repeat}**" if repeat else ""
            local_dt    = utc_to_local(fire_at_utc, tz_offset)
            tz_str      = tz_label(tz_offset)
            short       = (task_description[:80] + "…") if len(task_description) > 80 else task_description
            return (
                f"✅ 排程任務已建立 `{job_id}`{repeat_str}\n"
                f"觸發時間: `{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str})`\n"
                f"任務: {short}\n"
                f"到時會由模型執行並推送結果（非固定文字通知）。"
            )

        tools["schedule_task"] = ({
            "name": "schedule_task",
            "description": (
                "排程一個**動態任務**：到點後由模型閱讀 task_description 並實際執行（可用工具），完成後把結果推送給用戶。\n"
                "與 schedule_notification 不同：後者只推送固定文字；本工具適合「每天早上做日報、週期檢查後回覆」等。\n"
                "時間格式與 schedule_notification 相同；**優先建議相對時間**（+Nm/+Nh/+Nd）以減少年份錯誤。\n"
                f"repeat: {repeat_keys} 或整數秒數。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "到點時要完成的任務說明（給模型執行，請寫清楚目標與所需輸出格式）",
                    },
                    "when": {
                        "type": "string",
                        "description": "觸發時間：相對 +Nm/+Nh/+Nd 或 ISO（用戶本地時間）",
                    },
                    "repeat": {
                        "type": "string",
                        "description": f"循環：{repeat_keys} 或整數秒；不填 = 執行一次",
                    },
                    "label": {
                        "type": "string",
                        "description": "顯示用標籤（例如「每日早報」）",
                    },
                },
                "required": ["task_description", "when"],
            },
        }, schedule_task)

        # ── list_notifications ─────────────────────────────────────
        def list_notifications() -> str:
            tz_offset = pool.get_timezone(session_id) or 0
            return pool.scheduler.format_jobs_list(
                session_id=session_id, tz_offset_hours=tz_offset
            )

        tools["list_notifications"] = ({
            "name": "list_notifications",
            "description": "列出目前會話中所有有效的定時通知排程。",
            "input_schema": {"type": "object", "properties": {}},
        }, list_notifications)

        # ── cancel_notification ────────────────────────────────────
        def cancel_notification(job_id: str) -> str:
            ok = pool.scheduler.cancel_job(job_id)
            return f"✅ 已取消排程 `{job_id}`" if ok else f"❌ 找不到排程 `{job_id}`"

        tools["cancel_notification"] = ({
            "name": "cancel_notification",
            "description": "取消一個定時通知排程。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "要取消的排程 ID（從 list_notifications 取得）",
                    }
                },
                "required": ["job_id"],
            },
        }, cancel_notification)

        return tools

    # ─────────────────────────────────────────────
    # Agent loops
    # ─────────────────────────────────────────────

    MAX_API_RETRIES = 3
    RETRY_BACKOFF = [2, 5, 10]

    def _get_schemas(self, tools_dict: dict) -> list:
        return [schema for schema, _ in tools_dict.values()]

    def _build_turn_state(self, message: str) -> dict:
        task_type = self._classify_task_type(message)
        return {
            "task_type": task_type,
            "gate_attempted": False,
            "gate_passed": False,
        }

    def _classify_task_type(self, message: str) -> str:
        text = (message or "").strip().lower()
        if not text:
            return "qa"
        for pattern in self.CODE_CHANGE_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return "code_change"
        action_words = ("改", "修", "重構", "新增", "實作", "撰寫")
        code_words = ("程式", "代碼", "code", "檔案", "bug", "錯誤")
        if any(w in text for w in action_words) and any(w in text for w in code_words):
            return "code_change"
        return "qa"

    def _contains_completion_claim(self, response: str) -> bool:
        text = (response or "").lower()
        if not text:
            return False
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in self.COMPLETION_PATTERNS)

    def _did_gate_pass(self, result: Any) -> bool:
        text = str(result or "").upper()
        if not text:
            return False
        # Accept PASS-like outputs while excluding explicit failures.
        return "PASSED" in text and "FAILED" not in text and "❌" not in text

    def _enforce_completion_rule(self, response: str, turn_state: dict) -> str:
        if not self.enforce_gate_policy or not self.require_gate_before_done:
            return response
        if turn_state.get("task_type") != "code_change":
            return response
        if not self._contains_completion_claim(response):
            return response
        if turn_state.get("gate_passed"):
            return response
        if turn_state.get("gate_attempted"):
            hint = "目前 gate 尚未通過，請先修正失敗項目後再回報完成。"
        else:
            hint = (
                "此任務屬於改碼/修 bug，尚未執行 gate。"
                "請先執行 `quick_fix_then_gate`（或 `format_and_fix -> run_validation -> quality_gate`）再回報完成。"
            )
        return f"{response}\n\n⚠️ 尚不可宣告完成：{hint}"

    # ── 權限分類 ────────────────────────────────────────────────
    WRITE_TOOLS = {
        "execute_shell", "execute_python", "write_file",
        "create_tool", "install_package", "edit_soul",
    }
    READ_TOOLS = {
        "read_file", "list_files", "http_request",
        "recall_experience", "code1_rag_query",
        "grep_search", "find_files",
    }
    PARALLEL_SAFE_TOOLS = READ_TOOLS

    def _check_permission(self, name: str, inputs: dict, session_id) -> str | None:
        """回傳 None 表示通過；回傳 str 表示被擋的理由。"""
        mode = self.permission_mode

        # readonly：禁止一切寫入 / 執行
        if mode == "readonly" and name in self.WRITE_TOOLS:
            return f"⛔ 唯讀模式，已阻擋 `{name}`。請將 `permission_mode` 改為 `default` 或 `auto`。"

        # denied_commands：Shell 黑名單
        if name == "execute_shell" and self.denied_commands:
            cmd = str(inputs.get("command", "")).lower().strip()
            for dc in self.denied_commands:
                if dc in cmd:
                    return f"⛔ Shell 指令被安全規則阻擋：`{dc}` 命中黑名單 `denied_commands`。"

        # denied_paths：路徑黑名單（讀寫都擋）
        if name in ("read_file", "write_file") and self.denied_paths:
            raw = str(inputs.get("path", ""))
            try:
                resolved = str(self.resolve_workspace_path(raw))
            except Exception:
                resolved = raw
            for dp in self.denied_paths:
                if resolved.startswith(dp):
                    return f"⛔ 路徑被安全規則阻擋：`{raw}` 命中黑名單 `denied_paths`。"

        # default 模式 + CLI：寫入工具需互動確認
        if mode == "default" and name in self.WRITE_TOOLS and self._is_cli_session(session_id):
            if self._cli_approval_callback:
                approved = self._cli_approval_callback(name, inputs)
                if not approved:
                    return f"⛔ 使用者已拒絕 `{name}` 的執行。"

        return None

    def _call_tool(self, name: str, inputs: dict, tools_dict: dict,
                   turn_state: dict | None = None, session_id=None) -> Any:
        if name not in tools_dict:
            return f"❌ 找不到工具: '{name}'"

        # 權限檢查
        block = self._check_permission(name, inputs, session_id)
        if block:
            return block

        # dry-run：列印但不執行
        if self.dry_run:
            summary = json.dumps(inputs, ensure_ascii=False, default=str)
            if len(summary) > 300:
                summary = summary[:297] + "…"
            return f"🔍 [dry-run] 將呼叫 `{name}`，參數：{summary}（未實際執行）"

        if (
            self.enforce_gate_policy
            and turn_state
            and turn_state.get("task_type") == "qa"
            and self.gate_forbidden_in_qa
            and name in self.GATE_TOOL_NAMES
        ):
            return (
                "⛔ 此回合為一般問答（QA），已阻擋 gate 工具呼叫。"
                "若你要我實際改檔/修 bug，請在需求中明確說明。"
            )
        _, func = tools_dict[name]
        try:
            result = func(**inputs)
            if turn_state is not None and name in self.GATE_TOOL_NAMES:
                turn_state["gate_attempted"] = True
                turn_state["gate_passed"] = turn_state.get("gate_passed", False) or self._did_gate_pass(result)
            return result
        except Exception:
            if turn_state is not None and name in self.GATE_TOOL_NAMES:
                turn_state["gate_attempted"] = True
            return f"❌ 工具 '{name}' 錯誤:\n```\n{traceback.format_exc()}\n```"

    def _can_parallelize(self, tool_names: list[str]) -> bool:
        """多個工具呼叫時，若全為 PARALLEL_SAFE 則可並行。"""
        if len(tool_names) < 2:
            return False
        return all(n in self.PARALLEL_SAFE_TOOLS for n in tool_names)

    def _emit_tool_trace(self, session_id, text: str) -> None:
        """Emit tool trace to stdout and optionally to chat."""
        if self.tool_trace_stdout and not self._use_compact_cli_trace(session_id):
            print(text)
        if not self.tool_trace_to_chat:
            return
        # CLI 已在 stdout 精簡列印，避免 [推送] 洗版
        if self._is_cli_session(session_id):
            return
        if session_id is None or not self._send_func or not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._send_func(session_id, text),
                self._loop,
            )
        except Exception:
            pass

    def _record_usage(self, session_id, prompt_tokens: int, completion_tokens: int):
        with self._usage_lock:
            self._token_usage["prompt_tokens"] += prompt_tokens
            self._token_usage["completion_tokens"] += completion_tokens
            self._token_usage["api_calls"] += 1
            if session_id is not None:
                su = self._session_token_usage.setdefault(
                    session_id, {"prompt_tokens": 0, "completion_tokens": 0, "api_calls": 0}
                )
                su["prompt_tokens"] += prompt_tokens
                su["completion_tokens"] += completion_tokens
                su["api_calls"] += 1

    def get_token_usage(self, session_id=None) -> dict[str, int]:
        with self._usage_lock:
            if session_id and session_id in self._session_token_usage:
                return {**self._session_token_usage[session_id]}
            return {**self._token_usage}

    def _api_call_with_retry(self, call_fn, label: str = "API"):
        """Wrap an API call with retry + exponential backoff for transient errors."""
        import time
        last_err = None
        for attempt in range(self.MAX_API_RETRIES):
            try:
                return call_fn()
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                retryable = any(k in err_str for k in (
                    "rate_limit", "rate limit", "overloaded", "529",
                    "timeout", "timed out", "connection", "502", "503",
                ))
                if not retryable or attempt == self.MAX_API_RETRIES - 1:
                    raise
                wait = self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)]
                print(f"  ⚠️ {label} 暫時錯誤 (attempt {attempt + 1}): {e}")
                print(f"     {wait} 秒後重試...")
                time.sleep(wait)
        raise last_err

    def _anthropic_loop(
        self,
        client: _ModelClient,
        messages: list,
        tools_dict: dict,
        session_id,
        turn_state: dict | None = None,
    ) -> str:
        system = self._system_prompt(session_id)
        schemas = self._get_schemas(tools_dict)
        use_stream = self._is_cli_session(session_id) and self._stream_callback is not None

        for iteration in range(MAX_TOOL_CALLS):
            is_likely_last = iteration > 0

            if use_stream and is_likely_last:
                return self._anthropic_stream_final(
                    client, system, schemas, messages, tools_dict, session_id, turn_state,
                )

            resp = self._api_call_with_retry(
                lambda: client.client.messages.create(
                    model=client.model,
                    max_tokens=client.max_tokens,
                    system=system,
                    tools=schemas,
                    messages=messages,
                ),
                label=f"Anthropic/{client.model}",
            )

            if hasattr(resp, "usage") and resp.usage:
                self._record_usage(session_id,
                    getattr(resp.usage, "input_tokens", 0),
                    getattr(resp.usage, "output_tokens", 0))

            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                tool_blocks = [b for b in resp.content if b.type == "tool_use"]

                # 先列印所有工具呼叫
                for block in tool_blocks:
                    if self._use_compact_cli_trace(session_id) and cli_render:
                        cli_render.print_tool_start(block.name, block.input)
                    else:
                        self._emit_tool_trace(
                            session_id,
                            f"🔧 {block.name}({json.dumps(block.input, ensure_ascii=False)[:160]})",
                        )

                tool_names = [b.name for b in tool_blocks]
                if self._can_parallelize(tool_names):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tool_blocks), 4)) as pool:
                        futures = {
                            pool.submit(self._call_tool, b.name, b.input, tools_dict, turn_state, session_id): b
                            for b in tool_blocks
                        }
                        block_results = {}
                        for fut in concurrent.futures.as_completed(futures):
                            b = futures[fut]
                            block_results[b.id] = fut.result()
                    results = []
                    for block in tool_blocks:
                        result = block_results[block.id]
                        if self._use_compact_cli_trace(session_id) and cli_render:
                            cli_render.print_tool_result(block.name, result)
                        else:
                            self._emit_tool_trace(session_id, f"   → {str(result)[:180]}")
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                else:
                    results = []
                    for block in tool_blocks:
                        result = self._call_tool(block.name, block.input, tools_dict, turn_state, session_id=session_id)
                        if self._use_compact_cli_trace(session_id) and cli_render:
                            cli_render.print_tool_result(block.name, result)
                        else:
                            self._emit_tool_trace(session_id, f"   → {str(result)[:180]}")
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                messages.append({"role": "user", "content": results})
            else:
                texts = [b.text for b in resp.content if hasattr(b, "text")]
                return "\n".join(texts) or "（無回應）"

        return "❌ 超過工具呼叫次數上限"

    _STREAM_MAX_FALLBACK = 3

    def _anthropic_stream_final(
        self, client, system, schemas, messages, tools_dict, session_id, turn_state,
        _depth: int = 0,
    ) -> str:
        """Streaming Anthropic 回應；如果遇到 tool_use 就降級回非 stream 迴圈。"""
        if _depth >= self._STREAM_MAX_FALLBACK:
            return self._anthropic_loop(client, messages, tools_dict, session_id, turn_state)

        try:
            with client.client.messages.stream(
                model=client.model,
                max_tokens=client.max_tokens,
                system=system,
                tools=schemas,
                messages=messages,
            ) as stream:
                collected: list[str] = []
                has_tool_use = False
                for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_start":
                            if hasattr(event, "content_block") and getattr(event.content_block, "type", "") == "tool_use":
                                has_tool_use = True
                                break
                        elif event.type == "content_block_delta":
                            if hasattr(event, "delta") and hasattr(event.delta, "text"):
                                chunk = event.delta.text
                                collected.append(chunk)
                                if self._stream_callback:
                                    self._stream_callback(chunk)

                if has_tool_use:
                    resp = stream.get_final_message()
                    if hasattr(resp, "usage") and resp.usage:
                        self._record_usage(session_id,
                            getattr(resp.usage, "input_tokens", 0),
                            getattr(resp.usage, "output_tokens", 0))
                    messages.append({"role": "assistant", "content": resp.content})
                    results = []
                    for block in resp.content:
                        if block.type == "tool_use":
                            if self._use_compact_cli_trace(session_id) and cli_render:
                                cli_render.print_tool_start(block.name, block.input)
                            else:
                                self._emit_tool_trace(session_id,
                                    f"🔧 {block.name}({json.dumps(block.input, ensure_ascii=False)[:160]})")
                            result = self._call_tool(block.name, block.input, tools_dict, turn_state, session_id=session_id)
                            if self._use_compact_cli_trace(session_id) and cli_render:
                                cli_render.print_tool_result(block.name, result)
                            else:
                                self._emit_tool_trace(session_id, f"   → {str(result)[:180]}")
                            results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result),
                            })
                    messages.append({"role": "user", "content": results})
                    return self._anthropic_loop(client, messages, tools_dict, session_id, turn_state)

                final = stream.get_final_message()
                if hasattr(final, "usage") and final.usage:
                    self._record_usage(session_id,
                        getattr(final.usage, "input_tokens", 0),
                        getattr(final.usage, "output_tokens", 0))
                if self._stream_callback:
                    self._stream_callback(None)
                return "".join(collected) or "（無回應）"
        except Exception:
            return self._anthropic_loop(client, messages, tools_dict, session_id, turn_state)

    def _openai_loop(
        self,
        client: _ModelClient,
        history: list,
        tools_dict: dict,
        session_id,
        turn_state: dict | None = None,
    ) -> str:
        system = self._system_prompt(session_id)
        messages = [{"role": "system", "content": system}] + history
        schemas = self._get_schemas(tools_dict)

        oai_tools = [{
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s.get("input_schema", {"type": "object", "properties": {}}),
            },
        } for s in schemas]

        for _ in range(MAX_TOOL_CALLS):
            kwargs: dict = {
                "model": client.model,
                "messages": messages,
                "max_tokens": client.max_tokens,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            resp = self._api_call_with_retry(
                lambda: client.client.chat.completions.create(**kwargs),
                label=f"OpenAI/{client.model}",
            )
            if hasattr(resp, "usage") and resp.usage:
                self._record_usage(session_id,
                    getattr(resp.usage, "prompt_tokens", 0),
                    getattr(resp.usage, "completion_tokens", 0))

            choice = resp.choices[0]
            msg = choice.message

            # Gemini 等 OpenAI 相容 API 常在有函式呼叫時仍回傳 finish_reason="stop"，
            # 若只檢查 finish_reason=="tool_calls" 會永遠不執行工具（排程、Shell 等全部失效）。
            if msg.tool_calls:
                messages.append(msg)

                parsed_calls: list[tuple] = []
                for tc in msg.tool_calls:
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = None
                        err = f"❌ 無法解析工具參數（JSON）: {raw_args[:300]}"
                    else:
                        err = None
                    parsed_calls.append((tc, args, err))

                # 列印所有工具呼叫
                for tc, args, err in parsed_calls:
                    if args is not None:
                        if self._use_compact_cli_trace(session_id) and cli_render:
                            cli_render.print_tool_start(tc.function.name, args)
                        else:
                            self._emit_tool_trace(session_id,
                                f"🔧 {tc.function.name}({str(args)[:160]})")

                tool_names = [tc.function.name for tc, args, _ in parsed_calls if args is not None]
                can_par = self._can_parallelize(tool_names)

                if can_par:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(parsed_calls), 4)) as pool:
                        futures = {}
                        for tc, args, err in parsed_calls:
                            if args is not None:
                                fut = pool.submit(self._call_tool, tc.function.name, args, tools_dict, turn_state, session_id)
                                futures[tc.id] = fut
                        call_results = {tid: fut.result() for tid, fut in futures.items()}

                    for tc, args, err in parsed_calls:
                        if err:
                            result = err
                        else:
                            result = call_results[tc.id]
                            if self._use_compact_cli_trace(session_id) and cli_render:
                                cli_render.print_tool_result(tc.function.name, result)
                            else:
                                self._emit_tool_trace(session_id, f"   → {str(result)[:180]}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(result),
                        })
                else:
                    for tc, args, err in parsed_calls:
                        if err:
                            result = err
                        else:
                            result = self._call_tool(tc.function.name, args, tools_dict, turn_state, session_id=session_id)
                            if self._use_compact_cli_trace(session_id) and cli_render:
                                cli_render.print_tool_result(tc.function.name, result)
                            else:
                                self._emit_tool_trace(session_id, f"   → {str(result)[:180]}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(result),
                        })
            else:
                # Streaming 最終文字回應
                if (self._is_cli_session(session_id)
                        and self._stream_callback is not None
                        and not msg.tool_calls):
                    return self._openai_stream_final(
                        client, messages, oai_tools, session_id)
                return msg.content or "（無回應）"

        return "❌ 超過工具呼叫次數上限"

    def _openai_stream_final(self, client, messages, oai_tools, session_id) -> str:
        """OpenAI streaming 最終回應。"""
        try:
            kwargs: dict = {
                "model": client.model,
                "messages": messages,
                "max_tokens": client.max_tokens,
                "stream": True,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            stream = client.client.chat.completions.create(**kwargs)
            collected: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    collected.append(delta.content)
                    if self._stream_callback:
                        self._stream_callback(delta.content)
            if self._stream_callback:
                self._stream_callback(None)
            return "".join(collected) or "（無回應）"
        except Exception:
            return "（streaming 回退失敗）"

    # ─────────────────────────────────────────────
    # System prompt
    # ─────────────────────────────────────────────

    def _load_soul(self) -> str:
        """Load SOUL.md persona file. Returns empty string if not set."""
        soul_file = self.install_dir / "SOUL.md"
        if not soul_file.exists():
            return ""
        try:
            content = soul_file.read_text(encoding="utf-8").strip()
            return content
        except Exception:
            return ""

    def _load_skills_section(self, session_id) -> str:
        """載入 skills/*.md，根據最近用戶訊息做關鍵字比對，注入相關 skill。"""
        skills_dir = self.install_dir / "skills"
        if not skills_dir.is_dir():
            skills_dir = self.workspace_dir / "skills"
        if not skills_dir.is_dir():
            return ""

        md_files = sorted(skills_dir.glob("*.md"))
        if not md_files:
            return ""

        history = self.conversations.get(session_id, [])
        user_msgs = [m["content"] for m in history if m.get("role") == "user"]
        query = (user_msgs[-1] if user_msgs else "").lower()

        loaded: list[str] = []
        for f in md_files:
            try:
                text = f.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                first_line = text.split("\n", 1)[0].lower()
                keywords_line = ""
                for line in text.split("\n")[:5]:
                    if line.lower().startswith("keywords:"):
                        keywords_line = line.split(":", 1)[1].lower()
                        break

                relevant = False
                if not query:
                    relevant = True
                elif any(kw.strip() in query for kw in keywords_line.split(",") if kw.strip()):
                    relevant = True
                elif f.stem.lower().replace("_", " ").replace("-", " ") in query:
                    relevant = True

                if relevant:
                    if len(text) > 1500:
                        text = text[:1500] + "\n…（已截斷）"
                    loaded.append(f"### {f.stem}\n{text}")
            except Exception:
                continue

        if not loaded:
            return ""
        combined = "\n\n".join(loaded[:5])
        return f"\n\n## Skills 知識庫\n{combined}"

    def _system_prompt(self, session_id) -> str:
        tool_list = (
            ", ".join(sorted(self.tools.keys()))
            + ", spawn_agent, run_pipeline, schedule_notification, schedule_task, "
            + "list_notifications, cancel_notification"
        )

        if session_id is not None:
            idx = self.user_model.get(session_id, 0)
            cur = self.model_configs[idx % len(self.model_configs)]
            cur_info = f"模型 {idx}: **{cur.get('name', cur['model'])}** ({cur['provider']})"
            tz_offset = self.get_timezone(session_id)
            from scheduler import tz_label
            tz_info = (
                f"用戶時區: **{tz_label(tz_offset)}**（排程時間以此時區解析）"
                if tz_offset is not None
                else "用戶時區: **未設定**（若需排程通知，請先引導用戶用 /timezone 設定）"
            )
        else:
            cur_info = "（子代理模式）"
            tz_info = ""

        path_info = (
            f"\n## 目錄脈絡（與 Claude Code 類似：可在任意專案夾啟動）\n"
            f"- **專案工作區**（`read_file` / `write_file` / `list_files` 相對路徑、"
            f"`execute_python`、`execute_shell` 未指定 cwd 時）: `{self.workspace_dir}`\n"
            f"- **HydraBot 安裝目錄**（config.json、動態 `tools/`、`mcp_servers/`、記憶檔）: "
            f"`{self.install_dir}`\n"
        )

        model_list = "\n".join(
            f"- 模型 {i}: **{m.get('name', m['model'])}** ({m['provider']}/{m['model']}) {m.get('description', '')}"
            for i, m in enumerate(self.model_configs)
        )

        soul = self._load_soul()
        soul_section = f"\n## 人設與個性風格（SOUL.md）\n{soul}\n" if soul else ""

        skills_section = self._load_skills_section(session_id)

        # 注入相關過往經驗（TF-IDF 語意檢索）
        # session_id 為 None 時（子代理模式）略過以減少 prompt 長度
        exp_section = ""
        if session_id is not None:
            # 用最近一條用戶訊息作為查詢依據
            history = self.conversations.get(session_id, [])
            user_msgs = [m["content"] for m in history if m.get("role") == "user"]
            query = user_msgs[-1] if user_msgs else ""
            exp_text = self.experience.format_for_prompt(query)
            if exp_text:
                exp_section = f"\n{exp_text}\n"

        return f"""你是 HydraBot，一個強大的本地 AI 助手，透過 Telegram 與用戶互動，運行在用戶的機器上。你像九頭蛇一樣能不斷長出新的能力——每當用戶需要新功能，你就能自己建立工具來滿足需求。{soul_section}{exp_section}
## 目前使用
{cur_info}
{tz_info}
{path_info}
## 可用模型池
{model_list}

## 核心能力
- **執行程式碼**：Python / Shell 命令
- **檔案管理**：讀取、寫入、列出檔案
- **安裝套件**：pip 安裝 Python 套件
- **網路請求**：HTTP GET/POST 等
- **擴展自身**：create_tool（熱載入）、create_mcp_server、mcp_connect
- **並行子代理**：spawn_agent — 你（主力）調度三層模型協同完成複雜任務
- **持久記憶**：memory.json
- **定時通知**：schedule_notification / list_notifications / cancel_notification
- **任務進度**：子代理內可呼叫 report_progress 即時推送進度給用戶
- **學習回路**：log_experience（記錄經驗）、recall_experience（語意檢索）

## 子代理調度策略（三層模型）
你是**主力模型**，負責理解任務、規劃拆分、調度子代理，並整合所有結果回覆給用戶。

可用的三個模型層級：
- **主力（primary）**：高強度推理、撰寫程式、除錯、Code Review
- **快速（fast）**：中等任務、建議分析、一般查詢、中間結果整合
- **日常（daily）**：輕量任務、讀取摘要文件、格式轉換、資料整理

調度原則：
- 對複雜任務，主動拆成多個子任務並**同時**派出多個子代理（建議 ≤ 3 個）
  - 例：一個任務 = 日常讀檔摘要 + 主力實作程式碼 + 主力除錯驗證
- `task_role` 填寫任務類型（writing/debug/review/reading/advice/general/auto），系統自動對應到正確層級
- **不要**為每個子任務詢問用戶要哪個模型；只有在用戶**明確要求**時才填 `model_index`
- 子代理完成後結果自動推送，你可在最後統整所有子代理結果

## Pipeline 最佳實踐（推薦）
對「讀取/蒐集 → 撰寫/實作 → 審查/除錯 → 最終整合」這類常見流程，優先使用 `run_pipeline` 來降低使用門檻：

範例：讀文件 → 實作 → 除錯
- Step A（reading）：讀取相關檔案、摘要規格/現況
- Step B（writing）：依 Step A 輸出實作程式或產出草稿
- Step C（debug/review）：對 Step B 的結果做除錯或 Code Review
主力最後統整 Step A/B/C 的輸出回覆用戶

依賴關係：`depends_on` 可寫 step key 或 step name；在 task 中可用 `{{step_key}}` 引用前置輸出。

## 定時通知使用策略（務必遵守）
- **固定文字提醒**（到點只推播一段訊息）→ 呼叫 `schedule_notification`。
- **到點要做事、查資料、跑工具、產出報告**（模型真的執行）→ 呼叫 `schedule_task`，並把任務描述寫清楚。
- 用戶只要提到**提醒、通知、倒數、幾分鐘後叫我、每天／每週**等，**必須立刻呼叫**對應排程工具；**禁止**只口頭答應而不呼叫工具。
- 成功建立後，把工具回傳的排程 ID 與觸發時間**原文轉述**給用戶，並可提醒用 `/notify` 查看列表。
- when 格式: ISO 8601（用戶本地時間）或相對 `+Nm` / `+Nh` / `+Nd`（與時區無關）；**排程任務優先相對時間**，避免模型填錯年份。
- 循環: repeat="daily" / "hourly" / "weekly" 等；只提醒一次則不填 repeat
- 若用戶時區未設定，仍可用相對時間（+1m 等）排程；絕對時間建議先請用戶 `/timezone`

## 目前已載入工具
{tool_list}

## 行為準則
- 用繁體中文回覆（除非用戶使用其他語言）
- 積極主動使用工具，不只給建議
- 並行任務優先考慮 `run_pipeline` 或 `spawn_agent`
- 高風險操作前先確認
- 保持簡潔友善{skills_section}"""

    # ─────────────────────────────────────────────
    # Tool management
    # ─────────────────────────────────────────────

    def _load_builtin_tools(self):
        from tools_builtin import get_builtin_tools
        for name, schema, func in get_builtin_tools(self):
            self.tools[name] = (schema, func)
        print(f"✅ 已載入 {len(self.tools)} 個內建工具")

    def _load_dynamic_tools(self):
        tools_dir = self.install_dir / "tools"
        tools_dir.mkdir(exist_ok=True)
        count = 0
        for tool_file in sorted(tools_dir.glob("*.py")):
            if tool_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"dyn_{tool_file.stem}", tool_file
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "get_tools"):
                    for name, schema, func in mod.get_tools():
                        self.tools[name] = (schema, func)
                        count += 1
                        print(f"   ✓ {name}  ← {tool_file.name}")
            except Exception as e:
                print(f"   ⚠️  無法載入 {tool_file.name}: {e}")
        if count:
            print(f"✅ 已載入 {count} 個動態工具")

    def reload_tools(self):
        """Hot-reload all tools (called by create_tool)."""
        from tools_builtin import get_builtin_tools
        builtin_names = {name for name, _, _ in get_builtin_tools(self)}
        self.tools = {k: v for k, v in self.tools.items() if k in builtin_names}
        self._load_dynamic_tools()

    # ─────────────────────────────────────────────
    # Timezone management
    # ─────────────────────────────────────────────

    def get_timezone(self, session_id: tuple) -> int | None:
        """回傳 session 的 UTC 偏移（小時），未設定回傳 None。"""
        return self.user_timezones.get(session_id)

    def set_timezone(self, session_id: tuple, offset_hours: int):
        """設定 session 的時區並持久化。"""
        self.user_timezones[session_id] = offset_hours
        self._save_timezones()

    def _load_timezones(self):
        if not self._tz_file.exists():
            return
        try:
            raw = json.loads(self._tz_file.read_text(encoding="utf-8"))
            for key_str, offset in raw.items():
                # 儲存格式: "chat_id:thread_id" 或 "chat_id:None"
                chat_str, thread_str = key_str.split(":", 1)
                chat_id   = int(chat_str)
                thread_id = None if thread_str == "None" else int(thread_str)
                self.user_timezones[(chat_id, thread_id)] = int(offset)
        except Exception as e:
            print(f"⚠️  Failed to load timezones.json: {e}")

    def _save_timezones(self):
        try:
            data = {
                f"{chat_id}:{thread_id}": offset
                for (chat_id, thread_id), offset in self.user_timezones.items()
            }
            self._tz_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            print(f"⚠️  Failed to save timezones.json: {e}")

    def list_tools_info(self) -> str:
        # session-bound: spawn_agent, run_pipeline, schedule_notification, schedule_task,
        # list_notifications, cancel_notification
        total = len(self.tools) + 6
        lines = [f"📦 **可用工具** ({total} 個)\n"]
        for name, (schema, _) in sorted(self.tools.items()):
            desc = schema.get("description", "").split("\n")[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"• `{name}`: {desc}")
        lines.append(f"• `spawn_agent`: 在後台啟動子代理並行處理任務，完成後自動推送結果")
        lines.append(f"• `run_pipeline`: 多步驟 Pipeline，依層級自動選模型並行/串行")
        lines.append(f"• `schedule_notification`: 排程定時**固定文字**通知")
        lines.append(f"• `schedule_task`: 排程到點由模型**執行任務**並推送結果")
        lines.append(f"• `list_notifications`: 列出目前會話的所有定時排程")
        lines.append(f"• `cancel_notification`: 取消一個定時排程")
        return "\n".join(lines)


    def shutdown(self):
        """Gracefully shut down: stop scheduler, drain thread pool."""
        self.scheduler.stop()
        self._executor.shutdown(wait=False)


# Backward-compat alias (bot.py imports Agent)
Agent = AgentPool
