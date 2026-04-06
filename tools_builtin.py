#!/usr/bin/env python3
"""
Built-in tools for the HydraBot agent.

Every tool returns a string that will be shown to the LLM.
"""

import io
import os
import sys
import json
import shutil
import time
import queue
import subprocess
import traceback
import threading
from collections import deque
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent import Agent

# Module-level session tracker — set by AgentPool before each tool-call loop
current_session_id = [None]


def _install_dir(agent: "Agent") -> Path:
    return Path(getattr(agent, "install_dir", Path.cwd())).resolve()


def _workspace_dir(agent: "Agent") -> Path:
    return Path(getattr(agent, "workspace_dir", _install_dir(agent))).resolve()


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
            shell_cwd = cwd if cwd is not None else str(_workspace_dir(agent))
            r = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=shell_cwd,
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
            p = agent.resolve_workspace_path(path)
            if not p.exists():
                return f"❌ 檔案不存在: {path}"
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            end = min(offset + limit, total)
            excerpt = "\n".join(
                f"{i + offset + 1:4d} | {l}" for i, l in enumerate(lines[offset:end])
            )
            header = f"📄 {p}  （第 {offset+1}–{end} 行 / 共 {total} 行）\n"
            return header + f"```\n{excerpt}\n```"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # write_file
    # ─────────────────────────────────────────────────────────────

    def write_file(path: str, content: str, mode: str = "w") -> str:
        try:
            p = agent.resolve_workspace_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open(mode, encoding="utf-8") as f:
                f.write(content)
            size = p.stat().st_size
            # 以寫入內容前幾行做驗證摘要（避免模型宣稱已寫入卻無法對齊工具回傳）
            lines = content.splitlines()
            preview = lines[:8]
            excerpt = "\n".join(
                f"{i + 1:4d} | {(line[:220] + '…') if len(line) > 220 else line}"
                for i, line in enumerate(preview)
            ) or "  （空檔或僅空白）"
            return (
                f"✅ 已寫入 {p}（{size:,} bytes）\n"
                f"📎 寫入驗證（內容前 {len(preview)} 行預覽）：\n```\n{excerpt}\n```"
            )
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # list_files
    # ─────────────────────────────────────────────────────────────

    def list_files(
        path: str = ".",
        pattern: str = "*",
        max_items: int = 60,
        name: Optional[str] = None,
    ) -> str:
        """列出目錄內容。`name` 為 `pattern` 的別名，與 `find_files` 命名對齊，避免模型誤傳參。"""
        try:
            eff_pattern = pattern
            if name is not None and str(name).strip() != "":
                eff_pattern = name
            p = agent.resolve_workspace_path(path)
            if not p.exists():
                return f"❌ 路徑不存在: {path}"
            items = sorted(p.glob(eff_pattern))[:max_items]
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
    # grep_search — 程式碼搜尋（ripgrep / grep）
    # ─────────────────────────────────────────────────────────────

    def grep_search(
        pattern: str,
        path: str = ".",
        include: str = "",
        ignore_case: bool = False,
        max_results: int = 50,
    ) -> str:
        """Search file contents using regex pattern (like ripgrep). Returns matching lines with file paths and line numbers."""
        try:
            base = agent.resolve_workspace_path(path)
            if not base.exists():
                return f"❌ 路徑不存在: {path}"

            rg = shutil.which("rg")
            if rg:
                cmd = [rg, "--line-number", "--no-heading", "--color=never",
                       "--max-count=5", f"--max-filesize=1M"]
                if ignore_case:
                    cmd.append("-i")
                if include:
                    cmd.extend(["--glob", include])
                cmd.extend([
                    "--glob", "!.git",
                    "--glob", "!node_modules",
                    "--glob", "!__pycache__",
                    "--glob", "!*.pyc",
                    "--glob", "!venv",
                ])
                cmd.append(pattern)
                cmd.append(str(base))
            else:
                cmd = ["grep", "-rn", "--color=never"]
                if ignore_case:
                    cmd.append("-i")
                if include:
                    cmd.extend(["--include", include])
                cmd.extend([
                    "--exclude-dir=.git",
                    "--exclude-dir=node_modules",
                    "--exclude-dir=__pycache__",
                    "--exclude-dir=venv",
                ])
                cmd.append(pattern)
                cmd.append(str(base))

            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, cwd=str(base),
            )
            lines = r.stdout.strip().splitlines()
            if not lines:
                return f"🔍 未找到符合 `{pattern}` 的結果"

            total = len(lines)
            shown = lines[:max_results]
            try:
                display = []
                for line in shown:
                    display.append(line.replace(str(base) + "/", ""))
                result = "\n".join(display)
            except Exception:
                result = "\n".join(shown)

            header = f"🔍 找到 {total} 筆結果"
            if total > max_results:
                header += f"（顯示前 {max_results} 筆）"
            return f"{header}\n```\n{result}\n```"
        except subprocess.TimeoutExpired:
            return "❌ 搜尋超時（15s）"
        except Exception as e:
            return f"❌ {e}"

    # ─────────────────────────────────────────────────────────────
    # find_files — 檔名搜尋
    # ─────────────────────────────────────────────────────────────

    def find_files(
        name: str,
        path: str = ".",
        file_type: str = "all",
        max_results: int = 40,
    ) -> str:
        """Find files/directories by name pattern (glob). file_type: 'file', 'dir', or 'all'."""
        try:
            base = agent.resolve_workspace_path(path)
            if not base.exists():
                return f"❌ 路徑不存在: {path}"

            skip = {".git", "node_modules", "__pycache__", "venv", ".venv", ".tox"}
            matches = []

            def _walk(d: Path, depth: int = 0):
                if depth > 8 or len(matches) >= max_results:
                    return
                try:
                    entries = sorted(d.iterdir())
                except PermissionError:
                    return
                for item in entries:
                    if item.name in skip:
                        continue
                    if len(matches) >= max_results:
                        return
                    import fnmatch
                    if fnmatch.fnmatch(item.name, name):
                        if file_type == "file" and not item.is_file():
                            pass
                        elif file_type == "dir" and not item.is_dir():
                            pass
                        else:
                            try:
                                rel = item.relative_to(base)
                            except ValueError:
                                rel = item
                            tag = "📁" if item.is_dir() else "📄"
                            sz = f"  ({item.stat().st_size:,}B)" if item.is_file() else "/"
                            matches.append(f"  {tag} {rel}{sz}")
                    if item.is_dir():
                        _walk(item, depth + 1)

            _walk(base)

            if not matches:
                return f"🔍 未找到符合 `{name}` 的檔案"
            header = f"🔍 找到 {len(matches)} 個結果"
            return header + "\n" + "\n".join(matches)
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
        "spawn_agent",
        "run_pipeline",
        "schedule_notification",
        "schedule_task",
        "list_notifications",
        "cancel_notification",
        "report_progress",
    }

    def create_tool(tool_name: str, tool_code: str) -> str:
        """Write a tool module to tools/ and hot-reload."""
        if not tool_name.replace("_", "").isalnum():
            return "❌ 工具名稱只能包含字母、數字、底線（_）"

        # Prevent overwriting built-in or session-bound tools
        if tool_name in agent.tools or tool_name in _SESSION_TOOL_NAMES:
            return f"❌ 工具名 `{tool_name}` 與內建工具衝突，請換一個名稱"

        tools_dir = _install_dir(agent) / "tools"
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
        mcp_dir = _install_dir(agent) / "mcp_servers"
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

    def mcp_connect(command: str, server_name: str = None, timeout_sec: int = 12) -> str:
        """Start an MCP server process and register its tools."""
        sname = server_name or command.split()[0]
        timeout_sec = max(1, int(timeout_sec))

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

        stop_event = threading.Event()
        lock = threading.Lock()
        req_counter = [0]
        resp_queue: "queue.Queue[dict]" = queue.Queue()
        stderr_tail = deque(maxlen=80)

        def _stderr_hint() -> str:
            if not stderr_tail:
                return ""
            tail = "\n".join(list(stderr_tail)[-6:])
            return f"\n最近 stderr:\n```\n{tail}\n```"

        def _stop_process() -> None:
            stop_event.set()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass

        def _pump_stdout() -> None:
            while not stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    resp_queue.put(payload)

        def _pump_stderr() -> None:
            while not stop_event.is_set():
                line = proc.stderr.readline()
                if not line:
                    break
                stderr_tail.append(line.rstrip())

        threading.Thread(target=_pump_stdout, name=f"mcp-{sname}-stdout", daemon=True).start()
        threading.Thread(target=_pump_stderr, name=f"mcp-{sname}-stderr", daemon=True).start()

        def call_mcp(method: str, params: dict = None) -> dict:
            with lock:
                req_counter[0] += 1
                req_id = req_counter[0]
                req = json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": method,
                    "params": params or {},
                })
                proc.stdin.write(req + "\n")
                proc.stdin.flush()
                deadline = time.time() + max(1, int(timeout_sec))
                while time.time() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f"MCP server exited (code={proc.returncode}){_stderr_hint()}")
                    wait = max(0.05, deadline - time.time())
                    try:
                        resp = resp_queue.get(timeout=min(0.5, wait))
                    except queue.Empty:
                        continue
                    if resp.get("id") == req_id:
                        return resp
                raise TimeoutError(f"MCP `{method}` timeout after {timeout_sec}s{_stderr_hint()}")

        try:
            resp = call_mcp("tools/list")
        except Exception as e:
            _stop_process()
            return f"❌ MCP 通訊失敗: {e}"

        if "error" in resp:
            _stop_process()
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
            "timeout_sec": timeout_sec,
            "stop_event": stop_event,
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
        stop_event = info.get("stop_event")
        if stop_event is not None:
            stop_event.set()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass

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
            lines.append(f"   timeout: `{info.get('timeout_sec', 12)}s`")
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
            import tempfile
            text = json.dumps(memory, indent=2, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(dir=str(mem_file.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                Path(tmp).replace(mem_file)
            except Exception:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except Exception:
                    pass
                raise

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
        soul_file = _install_dir(agent) / "SOUL.md"

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
    # log_experience / recall_experience
    # ─────────────────────────────────────────────────────────────

    def log_experience(
        entry_type: str = "success",
        context: str = "",
        task: str = "",
        outcome: str = "",
        correction: str = "",
        tags: str = "",
        rating: int = 0,
    ) -> str:
        """記錄一筆結構化經驗到長期記憶庫（experience_log.json）。

        entry_type: success / failure / insight
        context   : 當時的背景（用戶說了什麼、環境狀況）
        task      : 執行的任務摘要
        outcome   : 結果（成功內容 or 錯誤訊息）
        correction: 如果是失敗，填寫修正策略；成功可留空
        tags      : 逗號分隔的標籤，例如 "python,排程,錯誤"
        rating    : -1（差）/ 0（普通）/ 1（好）
        """
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        entry_id = agent.experience.add(
            entry_type = entry_type,
            context    = context,
            task       = task,
            outcome    = outcome,
            correction = correction,
            tags       = tag_list,
            rating     = int(rating),
        )
        stats = agent.experience.count()
        return (
            f"✅ 已記錄 [{entry_type}] 經驗 `{entry_id}`\n"
            f"   任務: {task[:60]}\n"
            f"📚 目前經驗庫：共 {stats['total']} 條"
            f"（成功 {stats.get('success', 0)} / "
            f"失敗 {stats.get('failure', 0)} / "
            f"洞見 {stats.get('insight', 0)}）"
        )

    def recall_experience(query: str = "", top_k: int = 5, list_recent: bool = False) -> str:
        """從長期記憶庫語意檢索相關過往經驗。

        query      : 搜尋關鍵字或描述，留空則列出最近記錄
        top_k      : 最多回傳幾條（預設 5）
        list_recent: 若為 true，改為列出最近 top_k 條（忽略 query）
        """
        from learning import TOP_K
        k = max(1, min(int(top_k), 20))

        if list_recent or not query.strip():
            return agent.experience.format_list(n=k)

        hits = agent.experience.recall(query, top_k=k)
        if not hits:
            return f"🔍 找不到與「{query}」相關的經驗"

        lines = [f"🔍 **相關經驗** — 查詢: {query}\n"]
        for i, entry in enumerate(hits, 1):
            icon = {"success": "✅", "failure": "⚠️", "insight": "💡"}.get(
                entry.entry_type, "📝"
            )
            lines.append(
                f"{i}. {icon} `{entry.entry_id}`  [{entry.entry_type}]  {entry.timestamp[:10]}\n"
                f"   任務: {entry.task[:100]}\n"
                f"   結果: {entry.outcome[:100]}"
                + (f"\n   修正: {entry.correction[:100]}" if entry.correction and entry.correction != "（待補充修正策略）" else "")
            )
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # code1_rag_query — HydraBot-code1.0 本地 Chroma + Ollama RAG
    # ─────────────────────────────────────────────────────────────

    def code1_rag_query(question: str) -> str:
        """查詢本機 HydraBot-code1.0 專案的向量庫（需 config 或環境變數指定路徑）。"""
        cfg = agent.config or {}
        root = (cfg.get("hydrabot_code1_root") or "").strip()
        if not root:
            root = os.environ.get("HYDRABOT_RAG_ROOT", "").strip()
        if not root:
            return (
                "❌ 未設定本地 RAG 專案路徑。\n"
                "請在 config.json 設定 `hydrabot_code1_root` 為 HydraBot-code1.0 專案**根目錄**絕對路徑，\n"
                "或設定環境變數 `HYDRABOT_RAG_ROOT`。\n"
                "並在虛擬環境內安裝：`pip install -r requirements_rag.txt`（本倉庫）。"
            )
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            return f"❌ 路徑不存在: {root_path}"
        rag_py = root_path / "src" / "rag_core.py"
        if not rag_py.is_file():
            return f"❌ 找不到 {rag_py}（請確認為 HydraBot-code1.0 專案根目錄）"

        os.environ["HYDRABOT_RAG_ROOT"] = str(root_path)
        src = str(root_path / "src")
        if src not in sys.path:
            sys.path.insert(0, src)

        try:
            for mod_name in ("config", "rag_core"):
                if mod_name in sys.modules:
                    m = sys.modules[mod_name]
                    mf = getattr(m, "__file__", None)
                    if mf and not str(Path(mf).resolve()).startswith(str(root_path)):
                        del sys.modules[mod_name]

            from rag_core import query_rag

            r = query_rag(question)
            lines = [f"📚 **code1.0 本地 RAG**\n\n{r.answer}"]
            if r.sources:
                lines.append("\n**來源**")
                for i, s in enumerate(r.sources, 1):
                    lines.append(f"{i}. {s}")
            return "\n".join(lines)
        except Exception:
            return (
                "❌ RAG 查詢失敗。請確認：\n"
                "· 已 `pip install -r requirements_rag.txt`\n"
                "· Ollama 可連線，且已 `ollama pull` 所需模型\n"
                "· 已在 code1.0 專案執行 `python src/ingest.py`\n\n"
                f"```\n{traceback.format_exc()}\n```"
            )

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
                "未指定 cwd 時，預設在**專案工作區**（與 read_file 相對路徑根目錄相同）。\n"
                "Windows（cmd）沒有 pwd/ls：查目前目錄用 `cd`，列出目錄用 `dir`；"
                "macOS/Linux 可用 `pwd`、`ls`。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "完整一行 Shell 命令（例：dir、cd、git status）"},
                    "timeout":  {"type": "integer", "description": "逾時秒數（預設 30）"},
                    "cwd":      {"type": "string",  "description": "工作目錄（可選；省略則使用專案工作區）"},
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
            "description": (
                "列出目錄中的檔案／子目錄（不遞迴）。"
                "篩檔名請用 `pattern` 或 `name`（兩者擇一；`name` 與 find_files 參數名一致）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string",  "description": "目錄路徑（預設目前目錄）"},
                    "pattern":   {"type": "string",  "description": "glob 模式（預設 *）；與 `name` 擇一即可"},
                    "name":      {"type": "string",  "description": "與 `pattern` 相同用途之別名（篩檔名時可只用此參數）"},
                    "max_items": {"type": "integer", "description": "最多顯示數量（預設 60）"},
                },
            },
        }, list_files),

        ("grep_search", {
            "name": "grep_search",
            "description": (
                "在專案中搜尋檔案內容（正則表達式）。使用 ripgrep 或 grep，返回匹配行與檔案位置。"
                "適合搜尋函式定義、變數引用、錯誤訊息等。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern":     {"type": "string",  "description": "搜尋的正則表達式"},
                    "path":        {"type": "string",  "description": "搜尋起始路徑（預設目前目錄）"},
                    "include":     {"type": "string",  "description": "限定檔案 glob，如 '*.py' 或 '*.ts'"},
                    "ignore_case": {"type": "boolean", "description": "是否忽略大小寫（預設 false）"},
                    "max_results": {"type": "integer", "description": "最多顯示幾筆（預設 50）"},
                },
                "required": ["pattern"],
            },
        }, grep_search),

        ("find_files", {
            "name": "find_files",
            "description": (
                "依檔名模式搜尋檔案或目錄（glob 比對）。"
                "適合找特定檔案，如 '*.py'、'Dockerfile'、'test_*.js'。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string",  "description": "檔名 glob 模式，如 '*.py' 或 'config.*'"},
                    "path":        {"type": "string",  "description": "搜尋起始路徑（預設目前目錄）"},
                    "file_type":   {"type": "string",  "description": "'file'、'dir' 或 'all'（預設 all）",
                                    "enum": ["file", "dir", "all"]},
                    "max_results": {"type": "integer", "description": "最多顯示數量（預設 40）"},
                },
                "required": ["name"],
            },
        }, find_files),

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
                    "timeout_sec": {"type": "integer", "description": "MCP 請求 timeout 秒數（預設 12）"},
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

        ("log_experience", {
            "name": "log_experience",
            "description": (
                "記錄一筆結構化經驗到長期記憶庫（experience_log.json）。\n"
                "在完成任務後、遇到錯誤後、或獲得重要洞見時主動呼叫，讓 HydraBot 越用越聰明。\n"
                "每次任務成功或失敗後，建議主動呼叫此工具記錄。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "entry_type": {
                        "type": "string",
                        "description": "經驗類型",
                        "enum": ["success", "failure", "insight"],
                    },
                    "context": {
                        "type": "string",
                        "description": "當時的背景：用戶的要求、環境狀況（最多 1000 字）",
                    },
                    "task": {
                        "type": "string",
                        "description": "執行的任務摘要（最多 500 字）",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "結果：成功的具體內容 or 失敗的錯誤訊息（最多 800 字）",
                    },
                    "correction": {
                        "type": "string",
                        "description": "若為失敗，填寫修正策略或下次應如何處理；成功可留空",
                    },
                    "tags": {
                        "type": "string",
                        "description": "逗號分隔的標籤，例如 \"python,排程,api\"",
                    },
                    "rating": {
                        "type": "integer",
                        "description": "評分：-1（差）/ 0（普通）/ 1（好）",
                        "enum": [-1, 0, 1],
                    },
                },
                "required": ["entry_type", "task", "outcome"],
            },
        }, log_experience),

        ("recall_experience", {
            "name": "recall_experience",
            "description": (
                "從長期記憶庫語意檢索與當前任務相關的過往經驗。\n"
                "遇到困難任務、不確定最佳做法、或要排查問題時，先查詢此工具以避免重複錯誤。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜尋關鍵字或描述，例如「排程通知失敗」或「爬蟲 Python」",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多回傳幾條記錄（預設 5，最大 20）",
                    },
                    "list_recent": {
                        "type": "boolean",
                        "description": "若為 true，改為列出最近 top_k 條（忽略 query）",
                    },
                },
                "required": [],
            },
        }, recall_experience),

        ("code1_rag_query", {
            "name": "code1_rag_query",
            "description": (
                "查詢本機 **HydraBot-code1.0** 專案的 Chroma 向量庫（Ollama + RAG）。\n"
                "用於對照專案規格、驗收條件、架構原則等「已索引」文件。\n"
                "使用前需於 config.json 設定 `hydrabot_code1_root` 並安裝依賴（requirements_rag.txt）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "要以向量庫回答的問題（自然語言）",
                    },
                },
                "required": ["question"],
            },
        }, code1_rag_query),
    ]
