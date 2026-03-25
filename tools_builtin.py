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

# Module-level session tracker — set by AgentPool before each tool-call loop
current_session_id = [None]


def get_builtin_tools(agent: "Agent") -> list:
    """Return [(name, schema_dict, function), ...]"""

    # ─────────────────────────────────────────────────────────────
    # execute_python
    # ─────────────────────────────────────────────────────────────

    def execute_python(code: str) -> str:
        """Run Python code; variables persist across calls within the same session."""
        session = current_session_id[0]
        ns = agent.get_py_namespace(session) if session else {"__builtins__": __builtins__}

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        try:
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                exec(compile(code, "<agent>", "exec"), ns)
        except Exception:
            return f"❌ 執行錯誤:\n```\n{traceback.format_exc()}\n```"

        out = buf_out.getvalue()
        err = buf_err.getvalue()
        parts = []
        if out:
            parts.append(f"```\n{out.rstrip()}\n```")
        if err:
            parts.append(f"⚠️ stderr:\n```\n{err.rstrip()}\n```")
        return "\n".join(parts) or "✅ 執行成功（無輸出）"

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
            parts.append(f"返回碼: {r.returncode}")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return f"❌ 超時（{timeout}s）"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # read_file
    # ─────────────────────────────────────────────────────────────

    def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"❌ 檔案不存在: {path}"
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            end = min(offset + limit, total)
            excerpt = "\n".join(
                f"{i + offset + 1:4d} | {l}" for i, l in enumerate(lines[offset:end])
            )
            header = f"📄 {path}  （第 {offset+1}–{end} 行 / 共 {total} 行）\n"
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
            with p.open(mode, encoding="utf-8") as f:
                f.write(content)
            return f"✅ 已寫入 {path}（{p.stat().st_size:,} bytes）"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # list_files
    # ─────────────────────────────────────────────────────────────

    def list_files(path: str = ".", pattern: str = "*", max_items: int = 60) -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"❌ 路徑不存在: {path}"
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
                return f"✅ 已安裝: {package}"
            return f"❌ 安裝失敗:\n```\n{r.stderr[-600:]}\n```"
        except subprocess.TimeoutExpired:
            return "❌ 安裝超時"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # create_tool  ← self-expansion core
    # ─────────────────────────────────────────────────────────────

    # Names injected per-session (not in agent.tools) that must not be overwritten
    _SESSION_TOOL_NAMES = {
        "spawn_agent", "schedule_notification",
        "list_notifications", "cancel_notification", "report_progress",
    }

    def create_tool(tool_name: str, tool_code: str) -> str:
        """Write a tool module to tools/ and hot-reload."""
        if not tool_name.replace("_", "").isalnum():
            return "❌ 工具名稱只能包含字母、數字、底線（_）"

        # Prevent overwriting built-in or session-bound tools
        if tool_name in agent.tools or tool_name in _SESSION_TOOL_NAMES:
            return f"❌ 工具名 `{tool_name}` 與內建工具衝突，請換一個名稱"

        tools_dir = Path("tools")
        tools_dir.mkdir(exist_ok=True)
        path = tools_dir / f"{tool_name}.py"

        try:
            path.write_text(tool_code, encoding="utf-8")
        except Exception as e:
            return f"❌ 寫入失敗: {e}"

        # Validate by importing
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"_val_{tool_name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "get_tools"):
                path.unlink()
                return "❌ 工具檔案必須包含 get_tools() 函式"
            loaded = mod.get_tools()
            names = [n for n, _, _ in loaded]
        except SyntaxError as e:
            path.unlink(missing_ok=True)
            return f"❌ 語法錯誤: {e}"
        except Exception:
            path.unlink(missing_ok=True)
            return f"❌ 載入失敗:\n```\n{traceback.format_exc()}\n```"

        # Hot-reload
        agent.reload_tools()

        return (
            f"✅ 工具已建立: `{path}`\n"
            f"已載入工具: {', '.join(f'`{n}`' for n in names)}\n"
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
                f"✅ MCP 伺服器已建立: `{path}`\n\n"
                f"啟動命令: `python {path}`\n\n"
                f"連線命令（在對話中使用）:\n"
                f"用 `mcp_connect` 工具，command 參數填: `python {path}`"
            )
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # mcp_connect
    # ─────────────────────────────────────────────────────────────

    # Track connected MCP servers: { server_name -> {"proc": Popen, "tools": [str], "command": str} }
    if not hasattr(agent, "_mcp_servers"):
        agent._mcp_servers = {}

    def mcp_connect(command: str, server_name: str = None) -> str:
        """Start an MCP server process and register its tools."""
        sname = server_name or command.split()[0]

        # Prevent duplicate connections
        if sname in agent._mcp_servers:
            existing = agent._mcp_servers[sname]
            if existing["proc"].poll() is None:
                return f"⚠️ MCP 伺服器 `{sname}` 已連線中，工具: {', '.join(f'`{t}`' for t in existing['tools'])}"

        try:
            import shlex
            if sys.platform == "win32":
                normalized = command.replace("\\", "/")
                args = shlex.split(normalized, posix=False)
                args = [a.strip('"').strip("'") for a in args]
            else:
                args = shlex.split(command)
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except FileNotFoundError:
            return f"❌ 找不到命令: {command}"
        except Exception as e:
            return f"❌ 啟動失敗: {e}"

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
            return f"❌ MCP 通訊失敗: {e}"

        if "error" in resp:
            proc.terminate()
            return f"❌ MCP 錯誤: {resp['error']}"

        tools = resp.get("result", {}).get("tools", [])

        def make_proxy(tn: str):
            def proxy(**kwargs):
                try:
                    r = call_mcp("tools/call", {"name": tn, "arguments": kwargs})
                    if "error" in r:
                        return f"❌ MCP 錯誤: {r['error']}"
                    content = r.get("result", {}).get("content", [])
                    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text") or str(r.get("result", ""))
                except Exception as exc:
                    return f"❌ MCP 呼叫失敗: {exc}"
            return proxy

        tool_names = []
        for tool in tools:
            tn = tool["name"]
            tool_names.append(tn)
            schema = {
                "name": tn,
                "description": tool.get("description", f"MCP tool: {tn}"),
                "input_schema": tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
            agent.tools[tn] = (schema, make_proxy(tn))

        agent._mcp_servers[sname] = {
            "proc": proc,
            "tools": tool_names,
            "command": command,
        }

        return (
            f"✅ 已連線 MCP 伺服器: `{sname}`\n"
            f"已載入 {len(tools)} 個工具: {', '.join(f'`{n}`' for n in tool_names)}"
        )

    def mcp_disconnect(server_name: str) -> str:
        """Disconnect an MCP server and unregister its tools."""
        if server_name not in agent._mcp_servers:
            names = ", ".join(f"`{n}`" for n in agent._mcp_servers) or "（無）"
            return f"❌ 找不到 MCP 伺服器 `{server_name}`\n目前已連線: {names}"

        info = agent._mcp_servers.pop(server_name)
        proc = info["proc"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

        for tn in info["tools"]:
            agent.tools.pop(tn, None)

        return f"✅ 已斷開 MCP 伺服器 `{server_name}`，移除 {len(info['tools'])} 個工具"

    def list_mcp_servers() -> str:
        """List all connected MCP servers and their status."""
        if not agent._mcp_servers:
            return "📡 目前沒有已連線的 MCP 伺服器"
        lines = [f"📡 **MCP 伺服器** ({len(agent._mcp_servers)} 個)\n"]
        for name, info in agent._mcp_servers.items():
            alive = info["proc"].poll() is None
            status = "🟢 運行中" if alive else "🔴 已停止"
            tools_str = ", ".join(f"`{t}`" for t in info["tools"])
            lines.append(f"{status} **{name}**")
            lines.append(f"   命令: `{info['command']}`")
            lines.append(f"   工具: {tools_str}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # remember
    # ─────────────────────────────────────────────────────────────

    def remember(key: str, value: str = None, action: str = "set") -> str:
        """Persistent key-value memory (per AgentPool；Telegram: memory.json，Discord: discord_memory.json)。"""
        mem_file = getattr(agent, "_memory_path", None) or Path("memory.json")
        try:
            memory = json.loads(mem_file.read_text(encoding="utf-8")) if mem_file.exists() else {}
        except Exception:
            memory = {}

        def save():
            mem_file.write_text(json.dumps(memory, indent=2, ensure_ascii=False))

        if action == "set":
            if value is None:
                return "❌ 需要 value 參數"
            memory[key] = value
            save()
            return f"✅ 已記住 `{key}`"

        elif action == "get":
            if key == "*":
                return ("📝 所有記憶:\n" + "\n".join(f"• `{k}`: {v}" for k, v in memory.items())) if memory else "📝 記憶為空"
            v = memory.get(key)
            return f"📝 `{key}`: {v}" if v is not None else f"❓ 找不到: `{key}`"

        elif action == "list":
            return ("📝 鍵列表:\n" + "\n".join(f"• `{k}`" for k in memory)) if memory else "📝 記憶為空"

        elif action == "delete":
            if key in memory:
                del memory[key]
                save()
                return f"✅ 已刪除 `{key}`"
            return f"❓ 找不到: `{key}`"

        return f"❌ 未知操作: {action}（支援: set / get / list / delete）"

    # ─────────────────────────────────────────────────────────────
    # edit_soul
    # ─────────────────────────────────────────────────────────────

    def edit_soul(content: str = None, action: str = "get") -> str:
        """Read or write the bot's persona file (SOUL.md)."""
        soul_file = Path("SOUL.md")

        if action == "get":
            if not soul_file.exists():
                return "📝 SOUL.md 尚未建立（目前沒有人設）\n使用 action='set' 並提供 content 來設定人設。"
            text = soul_file.read_text(encoding="utf-8").strip()
            return f"📝 **當前人設 (SOUL.md)**\n\n{text}" if text else "📝 SOUL.md 存在但內容為空"

        elif action == "set":
            if not content:
                return "❌ 需要提供 content 參數"
            soul_file.write_text(content.strip(), encoding="utf-8")
            return "✅ 人設已更新（SOUL.md），下次對話即時生效，無需重啟"

        elif action == "clear":
            if soul_file.exists():
                soul_file.unlink()
            return "✅ 人設已清除（SOUL.md 已刪除）"

        return f"❌ 未知操作: {action}（支援: get / set / clear）"

    # ─────────────────────────────────────────────────────────────
    # Schemas
    # ─────────────────────────────────────────────────────────────

    return [
        ("execute_python", {
            "name": "execute_python",
            "description": "執行 Python 程式碼並返回輸出。變數在同一會話中持久化。",
            "input_schema": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "要執行的 Python 程式碼"}},
                "required": ["code"],
            },
        }, execute_python),

        ("execute_shell", {
            "name": "execute_shell",
            "description": (
                "執行 Shell 命令（git、npm、系統工具等）。\n"
                "Windows（cmd）沒有 pwd/ls：查目前目錄用 `cd`，列出目錄用 `dir`；"
                "macOS/Linux 可用 `pwd`、`ls`。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "完整一行 Shell 命令（例：dir、cd、git status）"},
                    "timeout":  {"type": "integer", "description": "逾時秒數（預設 30）"},
                    "cwd":      {"type": "string",  "description": "工作目錄（可選）"},
                },
                "required": ["command"],
            },
        }, execute_shell),

        ("read_file", {
            "name": "read_file",
            "description": "讀取檔案內容（支援分頁）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":   {"type": "string",  "description": "檔案路徑"},
                    "offset": {"type": "integer", "description": "起始行（預設 0）"},
                    "limit":  {"type": "integer", "description": "讀取行數（預設 200）"},
                },
                "required": ["path"],
            },
        }, read_file),

        ("write_file", {
            "name": "write_file",
            "description": "寫入內容到檔案（自動建立父目錄）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "檔案路徑"},
                    "content": {"type": "string", "description": "寫入內容"},
                    "mode":    {"type": "string", "description": "'w' 覆蓋（預設）或 'a' 附加", "enum": ["w", "a"]},
                },
                "required": ["path", "content"],
            },
        }, write_file),

        ("list_files", {
            "name": "list_files",
            "description": "列出目錄中的檔案。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string",  "description": "目錄路徑（預設目前目錄）"},
                    "pattern":   {"type": "string",  "description": "glob 模式（預設 *）"},
                    "max_items": {"type": "integer", "description": "最多顯示數量（預設 60）"},
                },
            },
        }, list_files),

        ("install_package", {
            "name": "install_package",
            "description": "用 pip 安裝 Python 套件。",
            "input_schema": {
                "type": "object",
                "properties": {"package": {"type": "string", "description": "套件名稱，如 'requests' 或 'pandas==2.0.0'"}},
                "required": ["package"],
            },
        }, install_package),

        ("create_tool", {
            "name": "create_tool",
            "description": (
                "建立新工具檔案（儲存到 tools/ 目錄並立即熱載入）。\n"
                "檔案必須包含 get_tools() 函式，返回 [(name, schema, func), ...] 列表。\n"
                "範本:\n"
                "```python\n"
                "def get_tools():\n"
                "    def my_func(param: str) -> str:\n"
                "        return f'結果: {param}'\n"
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
                    "tool_name": {"type": "string", "description": "工具檔案名稱（不含 .py）"},
                    "tool_code": {"type": "string", "description": "工具的 Python 程式碼"},
                },
                "required": ["tool_name", "tool_code"],
            },
        }, create_tool),

        ("list_tools", {
            "name": "list_tools",
            "description": "列出所有目前可用的工具。",
            "input_schema": {"type": "object", "properties": {}},
        }, list_tools),

        ("http_request", {
            "name": "http_request",
            "description": "發送 HTTP 請求。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url":     {"type": "string", "description": "請求 URL"},
                    "method":  {"type": "string", "description": "HTTP 方法（預設 GET）", "enum": ["GET","POST","PUT","DELETE","PATCH","HEAD"]},
                    "headers": {"type": "object", "description": "請求標頭（dict）"},
                    "body":    {"type": "string", "description": "請求本體"},
                    "timeout": {"type": "integer", "description": "逾時秒數（預設 30）"},
                },
                "required": ["url"],
            },
        }, http_request),

        ("create_mcp_server", {
            "name": "create_mcp_server",
            "description": (
                "建立 MCP（Model Context Protocol）伺服器腳本，儲存到 mcp_servers/ 目錄。\n"
                "MCP 伺服器透過 stdio 以 JSON-RPC 2.0 格式通訊。\n"
                "最簡範本:\n"
                "```python\n"
                "import sys, json\n"
                "def handle(req):\n"
                "    m = req.get('method')\n"
                "    if m == 'tools/list':\n"
                "        return {'result': {'tools': [{'name': 'hello', 'description': '範例', 'inputSchema': {'type':'object','properties':{'name':{'type':'string'}},'required':['name']}}]}}\n"
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
                    "server_name": {"type": "string", "description": "伺服器名稱"},
                    "server_code": {"type": "string", "description": "伺服器 Python 程式碼"},
                },
                "required": ["server_name", "server_code"],
            },
        }, create_mcp_server),

        ("mcp_connect", {
            "name": "mcp_connect",
            "description": "啟動 MCP 伺服器程序並將其工具載入到目前 agent 中。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command":     {"type": "string", "description": "啟動命令，如 'python mcp_servers/myserver.py'"},
                    "server_name": {"type": "string", "description": "自訂伺服器名稱（可選）"},
                },
                "required": ["command"],
            },
        }, mcp_connect),

        ("mcp_disconnect", {
            "name": "mcp_disconnect",
            "description": "斷開 MCP 伺服器並移除其工具。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "server_name": {"type": "string", "description": "要斷開的伺服器名稱"},
                },
                "required": ["server_name"],
            },
        }, mcp_disconnect),

        ("list_mcp_servers", {
            "name": "list_mcp_servers",
            "description": "列出所有已連線的 MCP 伺服器及其狀態。",
            "input_schema": {"type": "object", "properties": {}},
        }, list_mcp_servers),

        ("remember", {
            "name": "remember",
            "description": "持久化記憶管理（儲存於 memory.json）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key":    {"type": "string", "description": "鍵名；用 '*' 配合 get 讀取全部"},
                    "value":  {"type": "string", "description": "儲存值（action=set 時必填）"},
                    "action": {"type": "string", "description": "操作: set / get / list / delete", "enum": ["set","get","list","delete"]},
                },
                "required": ["key", "action"],
            },
        }, remember),

        ("edit_soul", {
            "name": "edit_soul",
            "description": (
                "讀取或更新 Bot 的人設檔案（SOUL.md）。\n"
                "SOUL.md 的內容會自動注入到每次對話的 system prompt 最前面，\n"
                "讓 Bot 以指定的個性、風格、語氣與用戶互動。\n"
                "修改後立即生效，無需重啟。\n"
                "action='get'   → 顯示目前人設內容\n"
                "action='set'   → 設定新的人設（覆蓋整個檔案）\n"
                "action='clear' → 清除人設，恢復預設行為"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action":  {"type": "string", "description": "操作: get / set / clear", "enum": ["get", "set", "clear"]},
                    "content": {"type": "string", "description": "人設內容（Markdown 格式，action=set 時必填）"},
                },
                "required": ["action"],
            },
        }, edit_soul),
    ]
