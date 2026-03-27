#!/usr/bin/env python3
"""
HydraBot — AgentPool
Manages multiple model clients, shared tools, and parallel sub-agent spawning.
Includes: scheduled notifications and real-time task progress reporting.
"""

import json
import asyncio
import importlib.util
import traceback
import threading
import concurrent.futures
import uuid
from pathlib import Path
from typing import Any

from scheduler import NotificationScheduler, parse_fire_at, REPEAT_INTERVALS
from learning import ExperienceLog, is_likely_failure


# Maximum number of tool-call iterations per agent loop turn
MAX_TOOL_CALLS = 30

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
        self._data_prefix = data_prefix or ""
        self._memory_path = (
            Path(f"{self._data_prefix}memory.json")
            if self._data_prefix
            else Path("memory.json")
        )
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

        # Shared tool registry  { name -> (schema, callable) }
        self.tools: dict[str, tuple] = {}

        # Conversation history  { session_id -> [messages] }
        # session_id = (chat_id, thread_id)  — chat_id is the TG group/private chat,
        # thread_id is the Telegram Topic ID (None for non-topic chats).
        # This lets each group / topic maintain a fully independent context.
        self.conversations: dict[tuple, list] = {}

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
        self.scheduler = NotificationScheduler(schedules_file=Path(_sched_name))

        # User timezone offsets  { session_id -> UTC offset hours (int) }
        # e.g. UTC+8 → 8,  UTC-5 → -5
        self.user_timezones: dict[tuple, int] = {}
        self._tz_file = (
            Path(f"{self._data_prefix}timezones.json")
            if self._data_prefix
            else Path("timezones.json")
        )
        self._load_timezones()

        # 學習回路：結構化長期記憶 + TF-IDF 語意檢索
        _exp_name = f"{self._data_prefix}experience_log.json"
        self.experience = ExperienceLog(log_path=Path(_exp_name))

        # Load tools
        self._load_builtin_tools()
        self._load_dynamic_tools()

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

        if session_id not in self.conversations:
            self.conversations[session_id] = []

        history = self.conversations[session_id]
        history.append({"role": "user", "content": message})

        # Build session tools (includes session-bound spawn_agent)
        session_tools = self._session_tools(session_id)

        # Let builtin tools (execute_python) know which session is active
        import tools_builtin
        tools_builtin.current_session_id[0] = session_id

        try:
            client = self.get_client(model_idx)
            if client.provider == "anthropic":
                response = self._anthropic_loop(client, list(history), session_tools, session_id)
            else:
                response = self._openai_loop(client, list(history), session_tools, session_id)
        except Exception as e:
            response = f"❌ Agent error: {e}\n```\n{traceback.format_exc()}\n```"
            print(response)

        history.append({"role": "assistant", "content": response})

        if len(history) > self.max_history:
            self.conversations[session_id] = history[-self.max_history:]

        # 失敗自動記錄：偵測到錯誤訊號時寫入經驗庫，供下次 recall 參考
        if is_likely_failure(response):
            try:
                self.experience.record_failure(
                    user_message=message,
                    bot_response=response,
                )
            except Exception:
                pass

        return response

    def reset_conversation(self, session_id: tuple):
        self.conversations.pop(session_id, None)
        self.reset_py_namespace(session_id)

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

    def _call_tool(self, name: str, inputs: dict, tools_dict: dict) -> Any:
        if name not in tools_dict:
            return f"❌ 找不到工具: '{name}'"
        _, func = tools_dict[name]
        try:
            return func(**inputs)
        except Exception:
            return f"❌ 工具 '{name}' 錯誤:\n```\n{traceback.format_exc()}\n```"

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

    def _anthropic_loop(self, client: _ModelClient, messages: list,
                         tools_dict: dict, session_id) -> str:
        system = self._system_prompt(session_id)
        schemas = self._get_schemas(tools_dict)

        for _ in range(MAX_TOOL_CALLS):
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

            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        print(f"  🔧 {block.name}({json.dumps(block.input)[:100]})")
                        result = self._call_tool(block.name, block.input, tools_dict)
                        print(f"     → {str(result)[:100]}")
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

    def _openai_loop(self, client: _ModelClient, history: list,
                      tools_dict: dict, session_id) -> str:
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
            choice = resp.choices[0]
            msg = choice.message

            # Gemini 等 OpenAI 相容 API 常在有函式呼叫時仍回傳 finish_reason="stop"，
            # 若只檢查 finish_reason=="tool_calls" 會永遠不執行工具（排程、Shell 等全部失效）。
            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        result = f"❌ 無法解析工具參數（JSON）: {raw_args[:300]}"
                        args = {}
                    else:
                        print(f"  🔧 {tc.function.name}({str(args)[:100]})")
                        result = self._call_tool(tc.function.name, args, tools_dict)
                        print(f"     → {str(result)[:100]}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })
            else:
                return msg.content or "（無回應）"

        return "❌ 超過工具呼叫次數上限"

    # ─────────────────────────────────────────────
    # System prompt
    # ─────────────────────────────────────────────

    def _load_soul(self) -> str:
        """Load SOUL.md persona file. Returns empty string if not set."""
        soul_file = Path("SOUL.md")
        if not soul_file.exists():
            return ""
        try:
            content = soul_file.read_text(encoding="utf-8").strip()
            return content
        except Exception:
            return ""

    def _system_prompt(self, session_id) -> str:
        tool_list = (
            ", ".join(sorted(self.tools.keys()))
            + ", spawn_agent, schedule_notification, list_notifications, cancel_notification"
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

        model_list = "\n".join(
            f"- 模型 {i}: **{m.get('name', m['model'])}** ({m['provider']}/{m['model']}) {m.get('description', '')}"
            for i, m in enumerate(self.model_configs)
        )

        soul = self._load_soul()
        soul_section = f"\n## 人設與個性風格（SOUL.md）\n{soul}\n" if soul else ""

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

## 定時通知使用策略（務必遵守）
- 用戶只要提到**提醒、通知、倒數、幾分鐘後叫我、每天／每週**等，**必須立刻呼叫** `schedule_notification` 建立排程。
- **禁止**只回覆「好的我會提醒你」卻不呼叫工具——沒有呼叫就不會真的排程，用戶也不會收到 Telegram 通知。
- 成功建立後，把工具回傳的排程 ID 與觸發時間**原文轉述**給用戶，並可提醒用 `/notify` 查看列表。
- when 格式: ISO 8601（用戶本地時間）或相對 `+Nm` / `+Nh` / `+Nd`（與時區無關）
- 循環: repeat="daily" / "hourly" / "weekly" 等；只提醒一次則不填 repeat
- 若用戶時區未設定，仍可用相對時間（+1m 等）排程；絕對時間建議先請用戶 `/timezone`

## 目前已載入工具
{tool_list}

## 行為準則
- 用繁體中文回覆（除非用戶使用其他語言）
- 積極主動使用工具，不只給建議
- 並行任務優先考慮 spawn_agent
- 高風險操作前先確認
- 保持簡潔友善"""

    # ─────────────────────────────────────────────
    # Tool management
    # ─────────────────────────────────────────────

    def _load_builtin_tools(self):
        from tools_builtin import get_builtin_tools
        for name, schema, func in get_builtin_tools(self):
            self.tools[name] = (schema, func)
        print(f"✅ 已載入 {len(self.tools)} 個內建工具")

    def _load_dynamic_tools(self):
        tools_dir = Path("tools")
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
        # +4 for session-bound tools injected per-session
        total = len(self.tools) + 4
        lines = [f"📦 **可用工具** ({total} 個)\n"]
        for name, (schema, _) in sorted(self.tools.items()):
            desc = schema.get("description", "").split("\n")[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"• `{name}`: {desc}")
        lines.append(f"• `spawn_agent`: 在後台啟動子代理並行處理任務，完成後自動推送結果")
        lines.append(f"• `schedule_notification`: 排程定時通知，到時自動推送給用戶")
        lines.append(f"• `list_notifications`: 列出目前會話的所有定時排程")
        lines.append(f"• `cancel_notification`: 取消一個定時排程")
        return "\n".join(lines)


    def shutdown(self):
        """Gracefully shut down: stop scheduler, drain thread pool."""
        self.scheduler.stop()
        self._executor.shutdown(wait=False)


# Backward-compat alias (bot.py imports Agent)
Agent = AgentPool
