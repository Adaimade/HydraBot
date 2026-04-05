# 🐍 HydraBot

> **Self-expanding local AI assistant for Telegram, Discord, and CLI**
> Build, debug, run shell/Python, schedule tasks, and spawn parallel sub-agents on your own machine.
> HydraBot can also create and hot-load new tools at runtime (`create_tool`) to expand itself.

[Version](VERSION)
[Python](https://www.python.org/)
[License](LICENSE)

[中文文件](README.zh-TW.md)

---

## Why HydraBot

- **Local-first execution**: shell, Python, files, and tools run on your machine.
- **Multi-interface**: Telegram / Discord / CLI with the same core agent.
- **Parallel work**: `spawn_agent` + `run_pipeline` for multi-step, multi-model tasks.
- **Self-expansion**: create tools dynamically at runtime (`create_tool`).
- **Production-oriented safety**: permission modes, deny-lists, dry-run, atomic writes, gate policy.

## 3-Minute Start

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
hydrabot
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
hydrabot
```

`hydrabot` without subcommand auto-selects:

- `start` when Telegram/Discord token is configured
- `cli` when messenger tokens are not configured

## Pick Your Mode

### 1) CLI-only (no Telegram/Discord needed)

```bash
hydrabot cli
hydrabot run "summarize this repo structure"
hydrabot run "preview tool behavior" --dry-run
```

### 2) Messenger bot mode (Telegram/Discord)

```bash
hydrabot start
```

### 3) Safe preview before real execution

```bash
hydrabot cli --dry-run
hydrabot run "refactor src/utils.py" --dry-run
```

---

## HydraBot vs a typical agent harness

Many projects ship a **minimal CLI loop** (tools + memory + optional MCP). HydraBot targets **daily use on real projects** with channels and scheduling baked in.


| Dimension          | Typical harness    | HydraBot                                                               |
| ------------------ | ------------------ | ---------------------------------------------------------------------- |
| **Interfaces**     | CLI only           | **Telegram, Discord, and CLI** — same agent core                       |
| **Scheduling**     | Rare or external   | **Built-in** notifications + LLM tasks (`schedule_*`)                  |
| **Multi-model**    | Often single model | **Primary / fast / daily** tiers + `spawn_routing`                     |
| **Parallel work**  | Varies             | `**spawn_agent`**, `**run_pipeline**`, read-only tool parallelization  |
| **Self-extension** | Skills / plugins   | `**create_tool`** (Python hot-reload) + **MCP**                        |
| **Safety**         | Varies             | `**permission_mode`**, deny-lists, `**--dry-run**`, atomic JSON writes |


*“Typical harness” here means lightweight CLI-oriented agent frameworks; names vary by project.*

---

## Use cases (copy-paste)

**1) Review a repo from the project folder (CLI)**

```bash
cd ~/your-project
hydrabot run "List top-level files, then summarize what this repo does in 5 bullets."
```

**2) Safe dry-run before letting the model touch files**

```bash
cd ~/your-project
hydrabot run "Refactor utils for readability" --dry-run
```

**3) Interactive coding session with session resume**

```bash
hydrabot cli
# inside CLI: /save after a long task, /resume next time, /usage for token stats
```

**4) Team channel bot (Telegram or Discord)**

```bash
hydrabot start
# Users talk in-channel; per-group/topic context stays isolated. See /timezone, /notify.
```

---

## Key Capabilities


| Capability                        | Description                                                                                                                                                                                        |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🤖 **Three-tier model roles**     | **Primary / fast / daily** map to `models` indices; set at install time; switch mid-chat with `/models`                                                                                            |
| ⚡ **Sub-agent auto-routing**      | `spawn_agent` routes by task type to the right tier; primary plans and integrates—users need not pick a model per subtask                                                                          |
| 🔧 **Self-Expansion**             | `create_tool` — the LLM can write and hot-reload new tools at runtime                                                                                                                              |
| 🖥️ **Multi-Channel Interface**   | Supports Telegram, Discord, and local CLI mode (`python main.py --cli`)                                                                                                                            |
| 💻 **Local Execution**            | Python / Shell code runs directly on your machine with full filesystem access                                                                                                                      |
| ⏰ **Scheduled Notifications**     | Schedule one-time or recurring notifications pushed automatically to Telegram                                                                                                                      |
| 🌍 **Timezone Awareness**         | First-run guide for UTC timezone setup; all notification times shown in user's local time                                                                                                          |
| 🧠 **Persistent Memory**          | `memory.json` — store arbitrary key-value data across conversations                                                                                                                                |
| 📚 **Learning Loop**              | `experience_log.json` + TF-IDF recall; auto-log failures and inject relevant past experience into prompts                                                                                          |
| 📊 **Progress Reporting**         | Sub-agents can call `report_progress` in real-time during execution                                                                                                                                |
| 🏢 **Multi-Project Isolation**    | Each Telegram group / Topic has completely independent conversation context                                                                                                                        |
| 🔌 **MCP Support**                | Connect to MCP Servers to dynamically extend tool capabilities                                                                                                                                     |
| ✅ **Quality tools & gate policy** | Optional `tools/` helpers (Ruff/mypy/pytest flows) and completion/gate rules in `config.json` — see [TOOLS.md](TOOLS.md#quality-tools-optional) |


---

## Command Cheatsheet

```bash
hydrabot start                # Start bot mode (Telegram/Discord)
hydrabot cli                  # Interactive terminal mode
hydrabot run "..."            # One-shot non-interactive prompt
hydrabot cli --dry-run        # Preview tool calls with no side effects
hydrabot run "..." --dry-run
hydrabot config               # Edit config.json
hydrabot status               # Show runtime summary
hydrabot update               # Update to latest
```

---

## Documentation Map

- **Quick start & PATH**: [QUICKSTART.md](QUICKSTART.md)
- **Traditional Chinese docs**: [README.zh-TW.md](README.zh-TW.md)
- **Tools (catalog, quality helpers, custom tools)**: [TOOLS.md](TOOLS.md)
- **Persona rules**: [SOUL.md](SOUL.md)
- **Config template**: [config.example.json](config.example.json)

---

## Quick Install

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
```

The installer will automatically:

1. Detect and install Python 3.10+
2. Clone / download core files
3. Create a Python virtual environment and install dependencies
4. Ask which messengers to enable: **Telegram only**, **Discord only**, **both**, or **terminal CLI only** (option 4 skips Telegram/Discord prompts; use `hydrabot cli` or `python3 main.py --cli`). Otherwise prompts for bot token(s) and optional allowlists (see `config.example.json` for `discord_`* keys)
5. Interactively configure your AI API keys and **primary / fast / daily** model slots (cloud or local LLM)
6. Set up the global `hydrabot` command (works from anywhere)

Non-interactive / CI installs can set `HB_PLATFORM` (`1` / `2` / `3` / `4` or `tg` / `dc` / `both` / `cli` / `terminal` / `none`) and `HB_TG_TOKEN` / `HB_DC_TOKEN` (and optional `HB_AUTH_USERS`, `HB_DC_AUTH_USERS`). Use `HB_PLATFORM=4` or `cli` to skip messenger tokens for CLI-only use.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
```

### Manual Install

For manual installation, you'll need to add the installation directory to PATH or run commands from that directory.

**Linux / macOS:**

```bash
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json to fill in credentials
./hydrabot start
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
# Edit config.json to fill in credentials
.\hydrabot.cmd start
```

> ℹ️ **PATH Setup**: After manual installation, either add the installation directory to your system PATH (so `hydrabot` works from anywhere), or always run commands from the installation directory. See [QUICKSTART.md](QUICKSTART.md) for detailed PATH setup instructions.

### Optional: Connect a local HydraBot-code1.0 vector store

If you use a sibling project such as **HydraBot-code1.0** (Chroma + Ollama RAG), install extra deps in the **same venv** and set the project root so HydraBot can call the built-in tool `**code1_rag_query`**:

```bash
pip install -r requirements_rag.txt
```

In `config.json`:

```json
"hydrabot_code1_root": "/absolute/path/to/HydraBot-code1.0"
```

Ensure that project has been indexed (`python src/ingest.py`) and Ollama is reachable.

---

## Start & Manage

After installation, you can manage HydraBot using the `hydrabot` command. This works globally if you used the automatic installer, or from the installation directory for manual installs:

```bash
hydrabot start          # Start the bot
hydrabot run "..."      # One-shot non-interactive prompt (prints answer then exits)
hydrabot cli --dry-run  # Preview tool calls without executing them
hydrabot run "..." --dry-run
hydrabot update         # Update to latest version
hydrabot update --force # Force update even if version matches
hydrabot config         # Edit config.json
hydrabot status         # View install status and config summary
hydrabot logs [N]       # View last N lines of logs (default 50)
hydrabot help           # Show full help
```

> ℹ️ **Not working globally?** If using manual install, either navigate to the installation directory or add it to PATH. See [QUICKSTART.md](QUICKSTART.md) for detailed instructions.

---

## CLI Mode

HydraBot also supports terminal chat mode (no Telegram/Discord token required):

```bash
python main.py --cli
```

You can also use `-c` or `cli`:

```bash
python main.py -c
python main.py cli
```

CLI built-in commands:

- `/help`
- `/reset`
- `/models` / `/model N`
- `/usage`
- `/save`
- `/resume`
- `/tools`
- `/quit` (or `/exit`)

**Terminal UX**: With `cli_compact_ui` (default `true` in `config.example.json`), tool runs render as compact blocks (`● Bash(…)`, tree lines, folded long output) and sub-agent pushes use a framed block—closer to Claude Code CLI. Set `cli_compact_ui: false` for the legacy trace style; `NO_COLOR=1` disables ANSI.

**Additional CLI runtime features**:

- Auto-save and auto-resume session history (`sessions/*.json`)
- Streaming output in CLI (chunk-by-chunk)
- `--dry-run` to preview all tool calls without side effects
- Read-only tool calls may run in parallel to reduce latency; write tools stay sequential for safety

---

## Configuration: config.json

Copy `config.example.json` and modify:

```json
{
  "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "authorized_users": [123456789],

  "max_tokens": 4096,
  "max_history": 50,

  "model_roles": {
    "primary": 0,
    "fast": 1,
    "daily": 2
  },
  "spawn_routing": {
    "reading": "daily",
    "writing": "primary",
    "review": "primary",
    "advice": "fast",
    "debug": "primary",
    "general": "fast"
  },

  "models": [
    {
      "name": "Primary Claude Sonnet",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-sonnet-4-6",
      "description": "Primary tier: reasoning and code-heavy work"
    },
    {
      "name": "Fast Claude Haiku",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-haiku-3-5",
      "description": "Fast tier: advice and medium subtasks"
    },
    {
      "name": "Gemini 2.0 Flash",
      "provider": "google",
      "api_key": "YOUR_GOOGLE_AI_KEY",
      "model": "gemini-2.0-flash",
      "description": "Daily tier: light summarization and formatting"
    }
  ]
}
```

### Supported AI Providers


| Provider                     | `provider` value      | Notes                                   |
| ---------------------------- | --------------------- | --------------------------------------- |
| Anthropic Claude             | `anthropic`           | Claude Sonnet / Haiku / Opus            |
| OpenAI / GPT                 | `openai`              | GPT-4o, o1, etc.                        |
| Google Gemini                | `google`              | Gemini 2.0 Flash, etc.                  |
| Custom OpenAI-compatible API | `openai` + `base_url` | Groq, DeepSeek, Ollama, local LLM, etc. |


### Parameters


| Parameter                  | Description                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| `telegram_token`           | Bot Token from BotFather (can be empty if you use Discord only)                                         |
| `discord_token`            | Discord bot token (empty if Telegram-only). Enable **Message Content Intent** in the Developer Portal   |
| `authorized_users`         | Allowed Telegram user IDs (empty = no restriction)                                                      |
| `discord_authorized_users` | Allowed Discord user snowflakes (empty = no restriction)                                                |
| `tool_trace_stdout`        | Log each tool call/result to process stdout (default `true`)                                            |
| `tool_trace_to_chat`       | Also push short trace lines to the chat session (default `false`, noisy)                                |
| `enforce_gate_policy`      | Apply runtime rules around QA vs code-change and gate tools (default `true`)                            |
| `gate_forbidden_in_qa`     | Block gate-style tools when the turn is classified as general QA (default `true`)                       |
| `require_gate_before_done` | When a code-change turn claims “done” without a passing gate, append a warning (default `true`)         |
| `permission_mode`          | Tool safety mode: `auto`, `default` (CLI write confirmation), or `readonly`                             |
| `denied_commands`          | Shell command blacklist substrings (e.g. `rm -rf /`)                                                    |
| `denied_paths`             | Path blacklist prefixes for `read_file`/`write_file`                                                    |
| `max_tokens`               | Max tokens per response (default 4096)                                                                  |
| `max_history`              | Number of conversation turns to retain (default 50)                                                     |
| `model_roles`              | Maps tiers to `models` indices: `primary`, `fast`, `daily`                                              |
| `spawn_routing`            | Maps sub-agent task types (`reading`, `writing`, `review`, `advice`, `debug`, `general`) to a tier name |


### Quality tools (optional)

Optional Ruff/mypy/pytest helpers and gate-related tools live under `tools/` and tie into `config.json`. **Full list and behavior:** [TOOLS.md](TOOLS.md#quality-tools-optional) · [SOUL.md](SOUL.md) (narrative constraints, Traditional Chinese).

### Three-tier models and sub-agent routing

- **Primary**: Main chat, planning, coding, debugging, code review.
- **Fast**: Advice, general Q&A, intermediate integration.
- **Daily**: Read/summarize files, light formatting and cleanup.

`spawn_agent` uses `task_role` (or infers from the task when `auto`) with `spawn_routing`, then resolves the real model via `model_roles`. Users do **not** need to pick a model for every subtask unless they explicitly set `model_index`. See `config.example.json` for the full schema.

**Local LLMs (Ollama, etc.)**: You can list multiple entries with the same `base_url` and different `model` names (e.g. 32B vs 7B) for primary/fast/daily. Watch VRAM and how many models Ollama keeps loaded when running parallel sub-agents.

---

## Telegram Bot Commands


| Command                | Description                                                                                        |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| `/start`               | Show welcome message; guide timezone setup on first use                                            |
| `/reset`               | Clear conversation history for current session                                                     |
| `/tools`               | List all available tools (including dynamic tools)                                                 |
| `/models`              | View available models; `/models N` to switch to model N                                            |
| `/tasks`               | View background task progress                                                                      |
| `/notify`              | List scheduled notifications; `/notify cancel <id>` to cancel                                      |
| `/timezone`            | View current timezone; `/timezone UTC+8` to set                                                    |
| `/whitelist`           | Manage the authorized users list; `/whitelist add <id>` to add, `/whitelist remove <id>` to remove |
| `/status`              | Show system status (version, timezone, models, tool count, schedule count, etc.)                   |
| `/new_agent`           | Start the wizard to create a new sub-agent Bot                                                     |
| `/list_agents`         | List all registered sub-agent Bots and their status                                                |
| `/delete_agent [name]` | Delete a sub-agent Bot (offers graveyard archival)                                                 |


---

## Timezone Setup

On first use, HydraBot will automatically guide you through timezone configuration:

```
🌍 Please set your timezone

• UTC+8  — Taiwan / Hong Kong / China
• UTC+9  — Japan / Korea
• UTC+7  — Thailand / Vietnam
• UTC+0  — UK (winter)
• UTC-5  — US Eastern (winter)

Enter UTC+8, +8, or just 8:
```

After setup, all scheduled notification times are displayed in the **user's local time**. Timezone data is persisted in `timezones.json` and retained after restarts.

```
/timezone          → View current timezone
/timezone UTC+8    → Set to UTC+8
/timezone +8       → Same as above
/timezone 8        → Same as above (range -12 ~ +14)
```

---

## Scheduled Notifications

Tell the bot in natural language, or use the underlying tools directly.

**Trigger Time Formats**


| Format   | Example                | Description                                  |
| -------- | ---------------------- | -------------------------------------------- |
| Relative | `+30m` / `+2h` / `+1d` | N minutes / hours / days from now            |
| Absolute | `2026-03-01T09:00:00`  | User's local time (auto timezone conversion) |


**Recurrence**: `minutely` / `hourly` / `daily` / `weekly` / integer seconds

**Example**:

```
User: Remind me to drink water every day at 9am
Bot:  ✅ Schedule created: sched_a1b2c3d4
      Trigger: 2026-03-02 09:00:00 (UTC+8)
      Recurrence: daily
```

---

## Isolation & Agent Architecture

HydraBot provides three levels of isolation to fit different use cases:

### 1. Topics — Conversation isolation only

Use **Telegram group Topics** when you need multiple assistants for different daily scenarios without worrying about files or git.

- Same HydraBot process, same filesystem
- Each Topic has a fully independent conversation history and memory
- Zero setup — just enable Topics in your Telegram group and start chatting
- **Best for:** daily assistance, Q&A, reminders, scheduling across different topics

```
Group with Topics enabled
├── Topic "Daily Assistant"  → isolated conversation
├── Topic "Research"         → isolated conversation
└── Topic "Schedule"         → isolated conversation
```

> ⚠️ Topics do **not** isolate the filesystem. If two Topics both run shell commands or git operations in the same directory, they can interfere with each other.

---

### 2. Sub-Agent Bot — Full process isolation

Use `/new_agent` when you need a **dedicated project workspace** with complete isolation from other projects.

- Separate HydraBot process, separate `agents/{name}/` directory, separate Telegram Bot identity
- All file I/O, git operations, memory, and tools are scoped to `agents/{name}/`
- **Best for:** software projects, codebases, anything involving git

```
/new_agent
  → Bot asks: project folder name (e.g. data-analyzer)
  → Bot asks: Telegram Bot Token (get one from @BotFather)
  → Bot creates agents/{name}/ with its own config, starts the process
  → Add the new Bot to your group — it operates independently
```

Each sub-agent gets a dedicated `agents/{name}/` folder with its own:

- `config.json` — token, model settings
- `memory.json` — persistent memory
- `timezones.json`, `schedules.json` — isolated scheduling
- `tools/` — custom tools

Because each instance runs from its own directory, there is **no git or file conflict** between agents.

```
/delete_agent [name]
  → Confirms deletion
  → Offers to visit the Digital Graveyard to leave a memorial
  → Permanently removes the process and agents/{name}/ folder
```

---

### 3. Parallel background tasks — Within a single project

Use the `**spawn_agent` tool** (called by the LLM) when one project needs multiple AI models working in parallel on different subtasks.

- Runs as background threads within the same process
- Each subtask is routed to **primary / fast / daily** by task type (`spawn_routing`), unless the user overrides `model_index`
- Results are pushed back automatically when done
- **Best for:** large document or research projects — web research, writing, and review running simultaneously

```
One sub-agent Bot (project workspace)
  └── LLM calls spawn_agent × 3
        ├── Model A: web research + data collection
        ├── Model B: document drafting
        └── Model C: fact-checking / cross-referencing
```

> ℹ️ Telegram Bots cannot send messages to or receive messages from other Bots. Parallel collaboration across models is handled within a single bot via `spawn_agent` — not by running multiple bots.

---

### Which to use?


| Scenario                                                                | Recommended                      |
| ----------------------------------------------------------------------- | -------------------------------- |
| Different daily topics, just need isolated chat                         | **Topics**                       |
| Large document / research project — multiple models working in parallel | `**spawn_agent`**                |
| Deliver a project: build → git commit → deploy to cloud                 | **Sub-agent Bot** (`/new_agent`) |


**Decision rule of thumb:**

- Work is *conversational or research-based* with no dedicated git repo → **Topics**
- Work produces a *deliverable* (code, app, git repo, cloud deployment) → **Sub-agent Bot**
- Within that project, needs *parallel AI workstreams* (research + writing + review simultaneously) → `**spawn_agent`** inside the Sub-agent Bot

## Tools reference

HydraBot exposes filesystem, shell, scheduling, MCP, memory, sub-agents, and self-expansion tools. **Full built-in catalog, optional quality helpers under `tools/`, and the custom-tool Python format:** [TOOLS.md](TOOLS.md) · [TOOLS.zh-TW.md](TOOLS.zh-TW.md).

---

## Bot Persona (SOUL.md)

You can give the bot a custom personality, tone, and behavior style by creating a `SOUL.md` file. Its content is automatically injected at the top of every conversation's system prompt — **changes take effect immediately without restarting**.

**Usage (just tell the bot in conversation):**

```
View current persona:   Ask the bot "show me the current persona"
Set a new persona:      Ask the bot "set the persona to: ...(describe the style you want)"
Clear the persona:      Ask the bot "clear the persona and restore default behavior"
```

The bot will call the `edit_soul` tool to handle these operations.

**Example SOUL.md:**

```markdown
You are a witty and humorous assistant. You speak concisely and love using metaphors
to explain complex concepts. You end every reply with a short, on-topic joke.
```

---

## Multi-Project Isolation

Each **Telegram group** or **Topic** has completely independent:

- Conversation history
- Timezone settings
- Scheduled notifications
- Python execution environment

Use different groups or Topics for different projects to avoid context contamination.

---

## Update

```bash
hydrabot update
```

Downloads the latest core files without affecting user data (`config.json`, `tools/`, `memory.json`).

---

## System Requirements

- Python 3.10+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- API Key from at least one AI Provider
- Internet connection

---

## Security Notice

HydraBot executes AI-generated code on your local machine. Please note:

- Can execute arbitrary Python / Shell commands
- Can read and write to the local filesystem
- Can install third-party packages via pip
- Can make outbound network requests
- **It is strongly recommended to set `authorized_users` to restrict access**

---

## License

MIT License — Forks and contributions are welcome.