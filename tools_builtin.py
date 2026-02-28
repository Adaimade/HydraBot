#!/usr/bin/env python3
"""
Built-in tools for the HydraBot agent.

Every tool returns a string that will be shown to the LLM.
"""

import io
import sys
import json
import subprocess
import traceback
import threading
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import Agent


def get_builtin_tools(agent: "Agent") -> list:
    """Return [(name, schema_dict, function), ...]"""

    # ─────────────────────────────────────────────────────────────
    # execute_python
    # ─────────────────────────────────────────────────────────────

    def execute_python(code: str) -> str:
        """Run Python code; variables persist across calls per session."""
        if not hasattr(agent, "_py_ns"):
            agent._py_ns = {"__builtins__": __builtins__}

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        try:
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                exec(compile(code, "<agent>", "exec"), agent._py_ns)
        except Exception:
            return f"❌ 执行错误:\n```\n{traceback.format_exc()}\n```"

        out = buf_out.getvalue()
        err = buf_err.getvalue()
        parts = []
        if out:
            parts.append(f"```\n{out.rstrip()}\n```")
        if err:
            parts.append(f"⚠️ stderr:\n```\n{err.rstrip()}\n```")
        return "\n".join(parts) or "✅ 执行成功（无输出）"

    # ─────────────────────────────────────────────────────────────
    # execute_shell
    # ─────────────────────────────────────────────────────────────

    def execute_shell(command: str, timeout: int = 30, cwd: str = None) -> str:
        """Execute a shell command and return stdout/stderr."""
        try:
            r = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            parts = []
            if r.stdout.strip():
                parts.append(f"```\n{r.stdout.rstrip()}\n```")
            if r.stderr.strip():
                parts.append(f"stderr:\n```\n{r.stderr.rstrip()}\n```")
            parts.append(f"返回码: {r.returncode}")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return f"❌ 超时（{timeout}s）"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # read_file
    # ─────────────────────────────────────────────────────────────

    def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"❌ 文件不存在: {path}"
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            end = min(offset + limit, total)
            excerpt = "\n".join(
                f"{i + offset + 1:4d} | {l}" for i, l in enumerate(lines[offset:end])
            )
            header = f"📄 {path}  (行 {offset+1}–{end} / 共 {total} 行)\n"
            return header + f"```\n{excerpt}\n```"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # write_file
    # ─────────────────────────────────────────────────────────────

    def write_file(path: str, content: str, mode: str = "w") -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.open(mode, encoding="utf-8").write(content)
            return f"✅ 已写入 {path}（{p.stat().st_size:,} bytes）"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # list_files
    # ─────────────────────────────────────────────────────────────

    def list_files(path: str = ".", pattern: str = "*", max_items: int = 60) -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"❌ 路径不存在: {path}"
            items = sorted(p.glob(pattern))[:max_items]
            lines = [f"📁 {p.absolute()}/"]
            for item in items:
                rel = item.relative_to(p)
                if item.is_dir():
                    lines.append(f"  📁 {rel}/")
                else:
                    lines.append(f"  📄 {rel}  ({item.stat().st_size:,}B)")
            if not items:
                lines.append("  （空）")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # install_package
    # ─────────────────────────────────────────────────────────────

    def install_package(package: str) -> str:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", package, "--quiet"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return f"✅ 已安装: {package}"
            return f"❌ 安装失败:\n```\n{r.stderr[-600:]}\n```"
        except subprocess.TimeoutExpired:
            return "❌ 安装超时"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # create_tool  ← self-expansion core
    # ─────────────────────────────────────────────────────────────

    def create_tool(tool_name: str, tool_code: str) -> str:
        """Write a tool module to tools/ and hot-reload."""
        if not tool_name.replace("_", "").isalnum():
            return "❌ 工具名只能包含字母、数字、下划线"

        tools_dir = Path("tools")
        tools_dir.mkdir(exist_ok=True)
        path = tools_dir / f"{tool_name}.py"

        try:
            path.write_text(tool_code, encoding="utf-8")
        except Exception as e:
            return f"❌ 写入失败: {e}"

        # Validate by importing
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"_val_{tool_name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "get_tools"):
                path.unlink()
                return "❌ 工具文件必须包含 get_tools() 函数"
            loaded = mod.get_tools()
            names = [n for n, _, _ in loaded]
        except SyntaxError as e:
            path.unlink(missing_ok=True)
            return f"❌ 语法错误: {e}"
        except Exception:
            path.unlink(missing_ok=True)
            return f"❌ 加载失败:\n```\n{traceback.format_exc()}\n```"

        # Hot-reload
        agent.reload_tools()

        return (
            f"✅ 工具已创建: `{path}`\n"
            f"已加载工具: {', '.join(f'`{n}`' for n in names)}\n"
            f"可以立即使用！"
        )

    # ─────────────────────────────────────────────────────────────
    # list_tools
    # ─────────────────────────────────────────────────────────────

    def list_tools() -> str:
        return agent.list_tools_info()

    # ─────────────────────────────────────────────────────────────
    # http_request
    # ─────────────────────────────────────────────────────────────

    def http_request(
        url: str,
        method: str = "GET",
        headers: dict = None,
        body: str = None,
        timeout: int = 30,
    ) -> str:
        try:
            import requests as _req
        except ImportError:
            return "❌ 需要 requests: pip install requests"
        try:
            resp = _req.request(
                method=method.upper(),
                url=url,
                headers=headers or {},
                data=body.encode() if body else None,
                timeout=timeout,
            )
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                try:
                    body_text = json.dumps(resp.json(), indent=2, ensure_ascii=False)[:3000]
                except Exception:
                    body_text = resp.text[:3000]
            else:
                body_text = resp.text[:3000]
            return (
                f"Status: {resp.status_code} {resp.reason}\n"
                f"Content-Type: {ct}\n\n"
                f"```\n{body_text}\n```"
            )
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # create_mcp_server
    # ─────────────────────────────────────────────────────────────

    def create_mcp_server(server_name: str, server_code: str) -> str:
        """Write an MCP server script to mcp_servers/."""
        mcp_dir = Path("mcp_servers")
        mcp_dir.mkdir(exist_ok=True)
        path = mcp_dir / f"{server_name}.py"
        try:
            path.write_text(server_code, encoding="utf-8")
            return (
                f"✅ MCP 服务器已创建: `{path}`\n\n"
                f"启动命令: `python {path}`\n\n"
                f"连接命令（在对话中使用）:\n"
                f"用 `mcp_connect` 工具，command 参数填: `python {path}`"
            )
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # mcp_connect
    # ─────────────────────────────────────────────────────────────

    def mcp_connect(command: str, server_name: str = None) -> str:
        """Start an MCP server process and register its tools."""
        try:
            import shlex
            args = shlex.split(command)
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            return f"❌ 命令未找到: {command}"
        except Exception as e:
            return f"❌ 启动失败: {e}"

        lock = threading.Lock()
        req_counter = [0]

        def call_mcp(method: str, params: dict = None) -> dict:
            with lock:
                req_counter[0] += 1
                req = json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_counter[0],
                    "method": method,
                    "params": params or {},
                })
                proc.stdin.write(req + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("MCP server closed stdout")
                return json.loads(line)

        try:
            resp = call_mcp("tools/list")
        except Exception as e:
            proc.terminate()
            return f"❌ MCP 通信失败: {e}"

        if "error" in resp:
            proc.terminate()
            return f"❌ MCP 错误: {resp['error']}"

        tools = resp.get("result", {}).get("tools", [])
        sname = server_name or command.split()[0]

        def make_proxy(tn: str):
            def proxy(**kwargs):
                try:
                    r = call_mcp("tools/call", {"name": tn, "arguments": kwargs})
                    if "error" in r:
                        return f"❌ MCP 错误: {r['error']}"
                    content = r.get("result", {}).get("content", [])
                    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text") or str(r.get("result", ""))
                except Exception as exc:
                    return f"❌ MCP 调用失败: {exc}"
            return proxy

        for tool in tools:
            tn = tool["name"]
            schema = {
                "name": tn,
                "description": tool.get("description", f"MCP tool: {tn}"),
                "input_schema": tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
            agent.tools[tn] = (schema, make_proxy(tn))

        names = [t["name"] for t in tools]
        return (
            f"✅ 已连接 MCP 服务器: `{sname}`\n"
            f"加载了 {len(tools)} 个工具: {', '.join(f'`{n}`' for n in names)}"
        )

    # ─────────────────────────────────────────────────────────────
    # remember
    # ─────────────────────────────────────────────────────────────

    def remember(key: str, value: str = None, action: str = "set") -> str:
        """Persistent key-value memory stored in memory.json."""
        mem_file = Path("memory.json")
        try:
            memory = json.loads(mem_file.read_text(encoding="utf-8")) if mem_file.exists() else {}
        except Exception:
            memory = {}

        def save():
            mem_file.write_text(json.dumps(memory, indent=2, ensure_ascii=False))

        if action == "set":
            if value is None:
                return "❌ 需要 value 参数"
            memory[key] = value
            save()
            return f"✅ 已记住 `{key}`"

        elif action == "get":
            if key == "*":
                return ("📝 所有记忆:\n" + "\n".join(f"• `{k}`: {v}" for k, v in memory.items())) if memory else "📝 记忆为空"
            v = memory.get(key)
            return f"📝 `{key}`: {v}" if v is not None else f"❓ 未找到: `{key}`"

        elif action == "list":
            return ("📝 键列表:\n" + "\n".join(f"• `{k}`" for k in memory)) if memory else "📝 记忆为空"

        elif action == "delete":
            if key in memory:
                del memory[key]
                save()
                return f"✅ 已删除 `{key}`"
            return f"❓ 未找到: `{key}`"

        return f"❌ 未知操作: {action}（支持: set / get / list / delete）"

    # ─────────────────────────────────────────────────────────────
    # Schemas
    # ─────────────────────────────────────────────────────────────

    return [
        ("execute_python", {
            "name": "execute_python",
            "description": "执行 Python 代码并返回输出。变量在同一会话中持久化。",
            "input_schema": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}},
                "required": ["code"],
            },
        }, execute_python),

        ("execute_shell", {
            "name": "execute_shell",
            "description": "执行 Shell 命令（git、npm、系统命令等）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell 命令"},
                    "timeout":  {"type": "integer", "description": "超时秒数（默认 30）"},
                    "cwd":      {"type": "string",  "description": "工作目录（可选）"},
                },
                "required": ["command"],
            },
        }, execute_shell),

        ("read_file", {
            "name": "read_file",
            "description": "读取文件内容（支持分页）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":   {"type": "string",  "description": "文件路径"},
                    "offset": {"type": "integer", "description": "起始行（默认 0）"},
                    "limit":  {"type": "integer", "description": "读取行数（默认 200）"},
                },
                "required": ["path"],
            },
        }, read_file),

        ("write_file", {
            "name": "write_file",
            "description": "写入内容到文件（自动创建父目录）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "写入内容"},
                    "mode":    {"type": "string", "description": "'w' 覆盖（默认）或 'a' 追加", "enum": ["w", "a"]},
                },
                "required": ["path", "content"],
            },
        }, write_file),

        ("list_files", {
            "name": "list_files",
            "description": "列出目录中的文件。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string",  "description": "目录路径（默认当前目录）"},
                    "pattern":   {"type": "string",  "description": "glob 模式（默认 *）"},
                    "max_items": {"type": "integer", "description": "最多显示数量（默认 60）"},
                },
            },
        }, list_files),

        ("install_package", {
            "name": "install_package",
            "description": "用 pip 安装 Python 包。",
            "input_schema": {
                "type": "object",
                "properties": {"package": {"type": "string", "description": "包名，如 'requests' 或 'pandas==2.0.0'"}},
                "required": ["package"],
            },
        }, install_package),

        ("create_tool", {
            "name": "create_tool",
            "description": (
                "创建新工具文件（保存到 tools/ 目录并立即热加载）。\n"
                "文件必须包含 get_tools() 函数，返回 [(name, schema, func), ...] 列表。\n"
                "模板:\n"
                "```python\n"
                "def get_tools():\n"
                "    def my_func(param: str) -> str:\n"
                "        return f'结果: {param}'\n"
                "    return [('my_func', {\n"
                "        'name': 'my_func',\n"
                "        'description': '工具描述',\n"
                "        'input_schema': {\n"
                "            'type': 'object',\n"
                "            'properties': {'param': {'type': 'string'}},\n"
                "            'required': ['param']\n"
                "        }\n"
                "    }, my_func)]\n"
                "```"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "工具文件名（不含 .py）"},
                    "tool_code": {"type": "string", "description": "工具的 Python 代码"},
                },
                "required": ["tool_name", "tool_code"],
            },
        }, create_tool),

        ("list_tools", {
            "name": "list_tools",
            "description": "列出所有当前可用的工具。",
            "input_schema": {"type": "object", "properties": {}},
        }, list_tools),

        ("http_request", {
            "name": "http_request",
            "description": "发送 HTTP 请求。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url":     {"type": "string", "description": "请求 URL"},
                    "method":  {"type": "string", "description": "HTTP 方法（默认 GET）", "enum": ["GET","POST","PUT","DELETE","PATCH","HEAD"]},
                    "headers": {"type": "object", "description": "请求头（dict）"},
                    "body":    {"type": "string", "description": "请求体"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 30）"},
                },
                "required": ["url"],
            },
        }, http_request),

        ("create_mcp_server", {
            "name": "create_mcp_server",
            "description": (
                "创建 MCP（Model Context Protocol）服务器脚本，保存到 mcp_servers/ 目录。\n"
                "MCP 服务器通过 stdio 以 JSON-RPC 2.0 格式通信。\n"
                "最简模板:\n"
                "```python\n"
                "import sys, json\n"
                "def handle(req):\n"
                "    m = req.get('method')\n"
                "    if m == 'tools/list':\n"
                "        return {'result': {'tools': [{'name': 'hello', 'description': '示例', 'inputSchema': {'type':'object','properties':{'name':{'type':'string'}},'required':['name']}}]}}\n"
                "    elif m == 'tools/call':\n"
                "        args = req['params']['arguments']\n"
                "        return {'result': {'content': [{'type':'text','text':f'Hello, {args[\"name\"]}!'}]}}\n"
                "for line in sys.stdin:\n"
                "    req = json.loads(line.strip())\n"
                "    r = handle(req); r.update({'jsonrpc':'2.0','id':req.get('id')})\n"
                "    print(json.dumps(r), flush=True)\n"
                "```"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "服务器名称"},
                    "server_code": {"type": "string", "description": "服务器 Python 代码"},
                },
                "required": ["server_name", "server_code"],
            },
        }, create_mcp_server),

        ("mcp_connect", {
            "name": "mcp_connect",
            "description": "启动 MCP 服务器进程并将其工具加载到当前 agent 中。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command":     {"type": "string", "description": "启动命令，如 'python mcp_servers/myserver.py'"},
                    "server_name": {"type": "string", "description": "自定义服务器名称（可选）"},
                },
                "required": ["command"],
            },
        }, mcp_connect),

        ("remember", {
            "name": "remember",
            "description": "持久化记忆管理（存储在 memory.json）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key":    {"type": "string", "description": "键名；用 '*' 配合 get 读取全部"},
                    "value":  {"type": "string", "description": "存储值（action=set 时必填）"},
                    "action": {"type": "string", "description": "操作: set / get / list / delete", "enum": ["set","get","list","delete"]},
                },
                "required": ["key", "action"],
            },
        }, remember),
    ]
