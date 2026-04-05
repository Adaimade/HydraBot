# Tools reference

This document lists **optional quality helpers**, the **built-in tool catalog**, and how to **author custom tools**. For install and configuration, see [README.md](README.md) and [config.example.json](config.example.json).

[繁體中文](TOOLS.zh-TW.md)

---

## Quality tools (optional)

Shipped under `tools/` (or add your own via `create_tool`): **`format_and_fix`**, **`run_validation`**, **`quality_gate`**, **`quick_fix_then_gate`**, **`code_task_guard`**. They invoke `python -m ruff`, `mypy`, `pytest` from the **same venv** as HydraBot — install those packages in the venv if needed. Behavior and when to run them are also summarized in [SOUL.md](SOUL.md) (Traditional Chinese).

| Tool | Role |
|------|------|
| `format_and_fix` | Format / lint fixes (Ruff, etc.) |
| `run_validation` | Run project checks (tests, typecheck as configured) |
| `quality_gate` | Aggregate validation gate |
| `quick_fix_then_gate` | Quick fix flow then re-validate |
| `code_task_guard` | Guardrails around code-change turns |

Related `config.json` keys: `enforce_gate_policy`, `gate_forbidden_in_qa`, `require_gate_before_done`, plus tool tracing via `tool_trace_stdout` / `tool_trace_to_chat`.

---

## Built-in tools

| Tool | Description |
|------|-------------|
| `execute_python` | Execute Python code (variables persist across calls) |
| `execute_shell` | Execute shell commands with timeout and cwd support |
| `read_file` | Read local files with offset/limit pagination |
| `write_file` | Write or append to local files |
| `list_files` | List directory contents (supports glob patterns) |
| `grep_search` | Regex search in files (`rg` preferred, fallback `grep`) |
| `find_files` | Find files/directories by glob pattern |
| `install_package` | Install Python packages via `pip install` |
| `http_request` | HTTP GET / POST and other network requests |
| `remember` | Persistent key-value memory (`set` / `get` / `list` / `delete`) |
| `list_tools` | List all tools currently available to the agent |
| `create_tool` | Write and hot-reload a new tool (core of self-expansion) |
| `mcp_connect` | Connect MCP server and load its tools (with request timeout) |
| `mcp_disconnect` | Disconnect MCP server and unload tools |
| `list_mcp_servers` | List connected MCP servers and status |
| `create_mcp_server` | Write an MCP server script under `mcp_servers/` (stdio JSON-RPC) |
| `edit_soul` | Read / update `SOUL.md` persona (see [README.md](README.md#bot-persona-soulmd)) |
| `log_experience` | Save structured success/failure/insight records into `experience_log.json` |
| `recall_experience` | Retrieve semantically similar past records for troubleshooting/reuse |
| `code1_rag_query` | Query optional local **HydraBot-code1.0** Chroma index (requires `hydrabot_code1_root` + `requirements_rag.txt`) |
| `spawn_agent` | Parallel sub-agents; auto-pick tier via `task_role`, optional `model_index` override |
| `run_pipeline` | Multi-step pipeline with per-step `task_role` and optional dependencies |
| `report_progress` | Sub-agents push progress updates (not for nested `spawn_agent`) |
| `schedule_notification` | Create a scheduled notification |
| `schedule_task` | Schedule an LLM task to run at trigger time |
| `list_notifications` | List all schedules for the current session |
| `cancel_notification` | Cancel a specific schedule |

Tool availability may vary by interface (e.g. sub-agent restrictions). Use `/tools` in Telegram/Discord or `list_tools` in session to see the live set.

---

## Self-expansion: creating custom tools

The bot can create tools at runtime, or you can place them manually:

```
HydraBot/
└── tools/
    ├── my_tool.py
    └── weather.py
```

Tool format:

```python
# tools/hello.py
def get_tools():
    def say_hello(name: str) -> str:
        return f"Hello, {name}!"

    schema = {
        "name": "say_hello",
        "description": "Greet someone by name",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The person's name"}
            },
            "required": ["name"]
        }
    }
    return [("say_hello", schema, say_hello)]
```

Each module exposes `get_tools()` returning a list of `(name, schema, callable)` tuples. After changes on disk, use `create_tool` or restart as appropriate for your workflow.
