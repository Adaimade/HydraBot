#!/usr/bin/env python3
"""
HydraBot — Core AI agent with tool-calling loop.
Supports Anthropic and OpenAI-compatible APIs.
"""

import json
import importlib.util
import traceback
from pathlib import Path
from typing import Any, TYPE_CHECKING


class Agent:
    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("model_provider", "anthropic")
        self.model = config.get("model_name", "claude-sonnet-4-6")
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_history = config.get("max_history", 50)

        # user_id -> list of messages
        self.conversations: dict[int, list] = {}

        # name -> (schema_dict, callable)
        self.tools: dict[str, tuple] = {}

        self._init_client()
        self._load_builtin_tools()
        self._load_dynamic_tools()

    # ─────────────────────────────────────────────
    # Init
    # ─────────────────────────────────────────────

    def _init_client(self):
        base_url = self.config.get("base_url")

        if self.provider == "anthropic":
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.config["model_api_key"])
            except ImportError:
                raise ImportError("Run: pip install anthropic")

        elif self.provider == "openai":
            try:
                import openai
                kwargs = {"api_key": self.config["model_api_key"]}
                if base_url:
                    kwargs["base_url"] = base_url
                self.client = openai.OpenAI(**kwargs)
            except ImportError:
                raise ImportError("Run: pip install openai")

        else:
            raise ValueError(
                f"Unknown provider: '{self.provider}'. Use 'anthropic' or 'openai'."
            )

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
                    f"dyn_tool_{tool_file.stem}", tool_file
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "get_tools"):
                    for name, schema, func in module.get_tools():
                        self.tools[name] = (schema, func)
                        count += 1
                        print(f"   ✓ {name}  ← {tool_file.name}")
            except Exception as e:
                print(f"   ⚠️  Failed to load {tool_file.name}: {e}")

        if count:
            print(f"✅ {count} dynamic tools loaded")

    def reload_tools(self):
        """Reload all tools (called after create_tool)."""
        from tools_builtin import get_builtin_tools
        builtin_names = {name for name, _, _ in get_builtin_tools(self)}
        # Remove dynamic tools, keep builtins
        self.tools = {k: v for k, v in self.tools.items() if k in builtin_names}
        self._load_dynamic_tools()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def chat(self, user_id: int, message: str) -> str:
        """Synchronous chat — call via asyncio.to_thread from bot."""
        if user_id not in self.conversations:
            self.conversations[user_id] = []

        history = self.conversations[user_id]
        history.append({"role": "user", "content": message})

        try:
            if self.provider == "anthropic":
                response = self._anthropic_loop(list(history))
            else:
                response = self._openai_loop(list(history))
        except Exception as e:
            response = f"❌ Agent error: {str(e)}\n```\n{traceback.format_exc()}\n```"
            print(response)

        history.append({"role": "assistant", "content": response})

        # Trim old history
        if len(history) > self.max_history:
            self.conversations[user_id] = history[-self.max_history:]

        return response

    def reset_conversation(self, user_id: int):
        self.conversations.pop(user_id, None)

    def list_tools_info(self) -> str:
        lines = [f"📦 **可用工具** ({len(self.tools)} 个)\n"]
        for name, (schema, _) in sorted(self.tools.items()):
            desc = schema.get("description", "").split("\n")[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"• `{name}`: {desc}")
        return "\n".join(lines)

    def get_tool_schemas(self) -> list:
        return [schema for schema, _ in self.tools.values()]

    # ─────────────────────────────────────────────
    # Anthropic loop
    # ─────────────────────────────────────────────

    def _anthropic_loop(self, messages: list) -> str:
        system = self._system_prompt()
        tools = self.get_tool_schemas()

        for _ in range(30):  # max iterations
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                # Add assistant turn
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"  🔧 {block.name}({json.dumps(block.input)[:120]})")
                        result = self._call_tool(block.name, block.input)
                        print(f"     → {str(result)[:120]}")
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })

                messages.append({"role": "user", "content": results})

            else:
                # end_turn — collect text blocks
                texts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(texts) or "(无响应)"

        return "❌ 超过最大工具调用次数"

    # ─────────────────────────────────────────────
    # OpenAI loop
    # ─────────────────────────────────────────────

    def _openai_loop(self, history: list) -> str:
        system_msg = {"role": "system", "content": self._system_prompt()}
        messages = [system_msg] + history

        # Convert to OpenAI tool format
        oai_tools = []
        for schema in self.get_tool_schemas():
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": schema.get("input_schema", {
                        "type": "object", "properties": {}
                    }),
                },
            })

        for _ in range(30):
            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"  🔧 {tc.function.name}({str(args)[:120]})")
                    result = self._call_tool(tc.function.name, args)
                    print(f"     → {str(result)[:120]}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })
            else:
                return msg.content or "(无响应)"

        return "❌ 超过最大工具调用次数"

    # ─────────────────────────────────────────────
    # Tool execution
    # ─────────────────────────────────────────────

    def _call_tool(self, name: str, inputs: dict) -> Any:
        if name not in self.tools:
            return f"❌ Tool not found: '{name}'"
        _, func = self.tools[name]
        try:
            return func(**inputs)
        except Exception:
            return f"❌ Tool '{name}' raised an error:\n```\n{traceback.format_exc()}\n```"

    # ─────────────────────────────────────────────
    # System prompt
    # ─────────────────────────────────────────────

    def _system_prompt(self) -> str:
        tool_list = ", ".join(sorted(self.tools.keys()))
        return f"""你是 HydraBot，一个强大的本地 AI 助手，通过 Telegram 与用户交互，运行在用户的机器上。你像九头蛇一样能不断长出新的能力——每当用户需要新功能，你就能自己创建工具来满足需求。

## 核心能力
你可以直接操作用户的机器：
- **执行代码**：Python / Shell 命令
- **文件管理**：读取、写入、列出文件
- **安装包**：通过 pip 安装 Python 包
- **网络请求**：HTTP GET/POST 等
- **扩展自身**：创建新工具（自动加载）、创建 MCP 服务器、连接 MCP 服务器
- **持久记忆**：存储重要信息到 memory.json

## 自我扩展方法
当用户需要新功能时，你可以：
1. 用 `install_package` 安装所需依赖
2. 用 `create_tool` 创建新工具文件（自动热加载，无需重启）
3. 用 `create_mcp_server` 创建 MCP 服务器
4. 用 `mcp_connect` 连接并加载 MCP 服务器的工具

## 新工具文件格式（tools/ 目录）
```python
def get_tools():
    def my_func(param: str) -> str:
        return f"结果: {{param}}"

    return [("my_func", {{
        "name": "my_func",
        "description": "工具描述",
        "input_schema": {{
            "type": "object",
            "properties": {{"param": {{"type": "string", "description": "参数说明"}}}},
            "required": ["param"]
        }}
    }}, my_func)]
```

## 当前已加载工具
{tool_list}

## 行为准则
- 用中文回复（除非用户使用其他语言）
- 积极主动地使用工具完成任务，而不仅仅给建议
- 高风险操作前先确认
- 保持简洁友好"""
