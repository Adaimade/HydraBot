#!/usr/bin/env python3
"""
HydraBot — AgentPool
Manages multiple model clients, shared tools, and parallel sub-agent spawning.
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

        elif self.provider == "openai":
            try:
                import openai
                kwargs: dict = {"api_key": key}
                if base_url:
                    kwargs["base_url"] = base_url
                self.client = openai.OpenAI(**kwargs)
            except ImportError:
                raise ImportError("Run: pip install openai")

        else:
            raise ValueError(f"Unknown provider: '{self.provider}'. Use 'anthropic' or 'openai'.")


# ─────────────────────────────────────────────────────────────
# AgentPool — main public class
# ─────────────────────────────────────────────────────────────

class AgentPool:
    """
    Manages 3 model configurations, a shared tool registry,
    and background sub-agent task execution.

    Drop-in replacement for the old Agent class.
    """

    def __init__(self, config: dict):
        self.config = config
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_history = config.get("max_history", 50)

        # Model configs parsed from config.json
        self.model_configs: list[dict] = self._parse_models(config)

        # Lazy-init model clients  { index -> _ModelClient }
        self._clients: dict[int, _ModelClient] = {}

        # Shared tool registry  { name -> (schema, callable) }
        self.tools: dict[str, tuple] = {}

        # Conversation history  { user_id -> [messages] }
        self.conversations: dict[int, list] = {}

        # Each user's preferred primary model index (default: 0)
        self.user_model: dict[int, int] = {}

        # Sub-agent task tracking  { task_id -> info_dict }
        self.running_tasks: dict[str, dict] = {}

        # Persistent Python namespace for execute_python
        self._py_ns: dict = {"__builtins__": __builtins__}

        # Thread pool for background sub-agents (max 6 concurrent)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=6, thread_name_prefix="hydra_sub"
        )

        # Set by bot after startup:  pool._loop / pool._send_func
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_func = None   # async (user_id: int, text: str) -> None

        # Load tools
        self._load_builtin_tools()
        self._load_dynamic_tools()

    # ─────────────────────────────────────────────
    # Config parsing (supports old & new format)
    # ─────────────────────────────────────────────

    def _parse_models(self, cfg: dict) -> list[dict]:
        """Support both new `models` array and old single-model keys."""
        if "models" in cfg and cfg["models"]:
            # Filter out comment-only entries
            return [m for m in cfg["models"] if "provider" in m]

        # Backward compatibility: single model
        return [{
            "name": "默认模型",
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

    def chat(self, user_id: int, message: str) -> str:
        """Synchronous — call via loop.run_in_executor from bot."""
        model_idx = self.user_model.get(user_id, 0)
        client = self.get_client(model_idx)

        if user_id not in self.conversations:
            self.conversations[user_id] = []

        history = self.conversations[user_id]
        history.append({"role": "user", "content": message})

        # Build session tools (includes user-bound spawn_agent)
        session_tools = self._session_tools(user_id)

        try:
            if client.provider == "anthropic":
                response = self._anthropic_loop(client, list(history), session_tools, user_id)
            else:
                response = self._openai_loop(client, list(history), session_tools, user_id)
        except Exception as e:
            response = f"❌ Agent error: {e}\n```\n{traceback.format_exc()}\n```"
            print(response)

        history.append({"role": "assistant", "content": response})

        if len(history) > self.max_history:
            self.conversations[user_id] = history[-self.max_history:]

        return response

    def reset_conversation(self, user_id: int):
        self.conversations.pop(user_id, None)

    # ─────────────────────────────────────────────
    # Model management
    # ─────────────────────────────────────────────

    def switch_model(self, user_id: int, model_idx: int) -> str:
        n = len(self.model_configs)
        if not (0 <= model_idx < n):
            return f"❌ 无效索引，请输入 0–{n - 1}"
        self.user_model[user_id] = model_idx
        m = self.model_configs[model_idx]
        return (
            f"✅ 已切换到 **模型 {model_idx}**\n"
            f"名称: {m.get('name', m['model'])}\n"
            f"模型: `{m['model']}` ({m['provider']})"
        )

    def list_models_info(self, user_id: int) -> str:
        current = self.user_model.get(user_id, 0)
        lines = [f"🤖 **可用模型** ({len(self.model_configs)} 组)\n"]
        for i, m in enumerate(self.model_configs):
            tag = "▶️ 当前" if i == current else f"  `{i}` "
            lines.append(f"{tag} **{m.get('name', m['model'])}**")
            lines.append(f"      `{m['provider']}` / `{m['model']}`")
            if m.get("description"):
                lines.append(f"      {m['description']}")
            lines.append("")
        lines.append(f"切换命令: `/model 0`  `/model 1`  `/model 2`")
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Sub-agent spawning
    # ─────────────────────────────────────────────

    def spawn_sub_agent(self, user_id: int, task: str, model_index: int) -> str:
        """Spawn a background sub-agent. Returns immediately."""
        n = len(self.model_configs)
        model_index = max(0, min(model_index, n - 1))

        client = self.get_client(model_index)
        task_id = f"sub_{uuid.uuid4().hex[:6]}"

        self.running_tasks[task_id] = {
            "id": task_id,
            "task": task[:60] + ("…" if len(task) > 60 else ""),
            "model": client.name,
            "model_idx": model_index,
            "status": "running",
            "user_id": user_id,
        }

        pool = self

        def _run():
            try:
                # Sub-agents use only builtin tools (no spawn_agent → no recursion)
                sub_tools = dict(pool.tools)

                if client.provider == "anthropic":
                    result = pool._anthropic_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        user_id=None,  # sub-agent has no persistent user history
                    )
                else:
                    result = pool._openai_loop(
                        client,
                        [{"role": "user", "content": task}],
                        sub_tools,
                        user_id=None,
                    )

                pool.running_tasks[task_id]["status"] = "done"
                msg = (
                    f"🤖 **子代理完成** `{task_id}`\n"
                    f"模型: {client.name}\n\n"
                    f"{result}"
                )
            except Exception as e:
                pool.running_tasks[task_id]["status"] = "error"
                msg = (
                    f"❌ **子代理失败** `{task_id}`\n"
                    f"模型: {client.name}\n"
                    f"错误: {str(e)}"
                )

            # Deliver result to user via Telegram
            if pool._send_func and pool._loop:
                asyncio.run_coroutine_threadsafe(
                    pool._send_func(user_id, msg), pool._loop
                )

        self._executor.submit(_run)

        return (
            f"✅ 子代理已启动 `{task_id}`\n"
            f"模型: **{client.name}**\n"
            f"任务: {task[:80]}\n\n"
            f"⏳ 后台运行中，完成后自动推送结果 📨"
        )

    def list_tasks_info(self) -> str:
        if not self.running_tasks:
            return "📋 暂无子代理任务记录"
        lines = [f"📋 **子代理任务** ({len(self.running_tasks)} 条)\n"]
        for t in sorted(self.running_tasks.values(), key=lambda x: x["id"], reverse=True)[:10]:
            emoji = {"running": "⏳", "done": "✅", "error": "❌"}.get(t["status"], "❓")
            lines.append(f"{emoji} `{t['id']}` — {t['model']}")
            lines.append(f"   {t['task']}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Session tools (inject spawn_agent with bound user_id)
    # ─────────────────────────────────────────────

    def _session_tools(self, user_id: int) -> dict:
        """Shallow-copy tools and inject a user-bound spawn_agent."""
        tools = dict(self.tools)

        pool = self
        n = len(self.model_configs)
        model_desc = "\n".join(
            f"  {i}: {m.get('name', m['model'])} — {m.get('description', '')}"
            for i, m in enumerate(self.model_configs)
        )

        def spawn_agent(task: str, model_index: int = 1) -> str:
            return pool.spawn_sub_agent(user_id, task, model_index)

        tools["spawn_agent"] = ({
            "name": "spawn_agent",
            "description": (
                f"在后台启动子代理，并行处理任务，完成后自动把结果推送给用户。\n"
                f"可同时启动多个（建议不超过 3 个）。子代理不会再启动子代理。\n"
                f"可用模型 (model_index):\n{model_desc}"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "交给子代理的完整任务描述（越详细越好）",
                    },
                    "model_index": {
                        "type": "integer",
                        "description": f"使用哪个模型（0–{n - 1}，默认 1 快速模型）",
                    },
                },
                "required": ["task"],
            },
        }, spawn_agent)

        return tools

    # ─────────────────────────────────────────────
    # Agent loops
    # ─────────────────────────────────────────────

    def _get_schemas(self, tools_dict: dict) -> list:
        return [schema for schema, _ in tools_dict.values()]

    def _call_tool(self, name: str, inputs: dict, tools_dict: dict) -> Any:
        if name not in tools_dict:
            return f"❌ Tool not found: '{name}'"
        _, func = tools_dict[name]
        try:
            return func(**inputs)
        except Exception:
            return f"❌ Tool '{name}' error:\n```\n{traceback.format_exc()}\n```"

    def _anthropic_loop(self, client: _ModelClient, messages: list,
                         tools_dict: dict, user_id) -> str:
        system = self._system_prompt(user_id)
        schemas = self._get_schemas(tools_dict)

        for _ in range(30):
            resp = client.client.messages.create(
                model=client.model,
                max_tokens=client.max_tokens,
                system=system,
                tools=schemas,
                messages=messages,
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
                return "\n".join(texts) or "(无响应)"

        return "❌ 超过最大工具调用次数"

    def _openai_loop(self, client: _ModelClient, history: list,
                      tools_dict: dict, user_id) -> str:
        system = self._system_prompt(user_id)
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

        for _ in range(30):
            kwargs: dict = {
                "model": client.model,
                "messages": messages,
                "max_tokens": client.max_tokens,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            resp = client.client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"  🔧 {tc.function.name}({str(args)[:100]})")
                    result = self._call_tool(tc.function.name, args, tools_dict)
                    print(f"     → {str(result)[:100]}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })
            else:
                return msg.content or "(无响应)"

        return "❌ 超过最大工具调用次数"

    # ─────────────────────────────────────────────
    # System prompt
    # ─────────────────────────────────────────────

    def _system_prompt(self, user_id) -> str:
        tool_list = ", ".join(sorted(self.tools.keys())) + ", spawn_agent"

        if user_id is not None:
            idx = self.user_model.get(user_id, 0)
            cur = self.model_configs[idx % len(self.model_configs)]
            cur_info = f"模型 {idx}: **{cur.get('name', cur['model'])}** ({cur['provider']})"
        else:
            cur_info = "（子代理模式）"

        model_list = "\n".join(
            f"- 模型 {i}: **{m.get('name', m['model'])}** ({m['provider']}/{m['model']}) {m.get('description', '')}"
            for i, m in enumerate(self.model_configs)
        )

        return f"""你是 HydraBot，一个强大的本地 AI 助手，通过 Telegram 与用户交互，运行在用户的机器上。你像九头蛇一样能不断长出新的能力——每当用户需要新功能，你就能自己创建工具来满足需求。

## 当前使用
{cur_info}

## 可用模型池
{model_list}

## 核心能力
- **执行代码**：Python / Shell 命令
- **文件管理**：读取、写入、列出文件
- **安装包**：pip 安装 Python 包
- **网络请求**：HTTP GET/POST 等
- **扩展自身**：create_tool（热加载）、create_mcp_server、mcp_connect
- **并行子代理**：spawn_agent — 把子任务派给其他模型，后台并行运行，互不阻塞
- **持久记忆**：memory.json

## spawn_agent 使用策略
当需要同时处理多件事时，优先考虑 spawn_agent：
- 同时派出多个子代理（建议 ≤ 3 个）
- 轻量任务 → model_index=1（快速模型）
- 复杂/专业任务 → model_index=0（主力模型）或 model_index=2
- 子代理完成后结果自动推送，不需要等待
- 子代理内不要再次调用 spawn_agent（防止递归）

## 当前已加载工具
{tool_list}

## 行为准则
- 用中文回复（除非用户使用其他语言）
- 积极主动使用工具，不只给建议
- 并行任务优先考虑 spawn_agent
- 高风险操作前先确认
- 保持简洁友好"""

    # ─────────────────────────────────────────────
    # Tool management
    # ─────────────────────────────────────────────

    def _load_builtin_tools(self):
        from tools_builtin import get_builtin_tools
        for name, schema, func in get_builtin_tools(self):
            self.tools[name] = (schema, func)
        print(f"✅ {len(self.tools)} built-in tools loaded")

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
                print(f"   ⚠️  Failed to load {tool_file.name}: {e}")
        if count:
            print(f"✅ {count} dynamic tools loaded")

    def reload_tools(self):
        """Hot-reload all tools (called by create_tool)."""
        from tools_builtin import get_builtin_tools
        builtin_names = {name for name, _, _ in get_builtin_tools(self)}
        self.tools = {k: v for k, v in self.tools.items() if k in builtin_names}
        self._load_dynamic_tools()

    def list_tools_info(self) -> str:
        # +1 for spawn_agent which is injected per-session
        total = len(self.tools) + 1
        lines = [f"📦 **可用工具** ({total} 个)\n"]
        for name, (schema, _) in sorted(self.tools.items()):
            desc = schema.get("description", "").split("\n")[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"• `{name}`: {desc}")
        lines.append(f"• `spawn_agent`: 在后台启动子代理并行处理任务，完成后自动推送结果")
        return "\n".join(lines)


# Backward-compat alias (bot.py imports Agent)
Agent = AgentPool
