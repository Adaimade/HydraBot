# 🐍 HydraBot

> **Self-expanding AI Assistant via Telegram**
> An AI assistant running on your local machine. Chat with it through Telegram to execute code, manage files, spawn parallel sub-agents, and even create new tools at runtime to expand its own capabilities — just like a hydra: cut off one head and more grow back.

[![Version](https://img.shields.io/badge/version-1.2.0-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[中文文件](README.zh-TW.md)

---

## Features

| Feature | Description |
|---------|-------------|
| 🤖 **Multi-Model Support** | Configure multiple AI models simultaneously (primary + fast + backup), switchable mid-conversation |
| ⚡ **Parallel Sub-Agents** | `spawn_agent` — delegate subtasks to other models, running in parallel without blocking |
| 🔧 **Self-Expansion** | `create_tool` — the LLM can write and hot-reload new tools at runtime |
| 💻 **Local Execution** | Python / Shell code runs directly on your machine with full filesystem access |
| ⏰ **Scheduled Notifications** | Schedule one-time or recurring notifications pushed automatically to Telegram |
| 🌍 **Timezone Awareness** | First-run guide for UTC timezone setup; all notification times shown in user's local time |
| 🧠 **Persistent Memory** | `memory.json` — store arbitrary key-value data across conversations |
| 📊 **Progress Reporting** | Sub-agents can call `report_progress` in real-time during execution |
| 🏢 **Multi-Project Isolation** | Each Telegram group / Topic has completely independent conversation context |
| 🔌 **MCP Support** | Connect to MCP Servers to dynamically extend tool capabilities |

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
4. Interactively prompt for your Telegram Token and AI API Key
5. Set up the global `hydrabot` command (works from anywhere)

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

---

## Start & Manage

After installation, you can manage HydraBot using the `hydrabot` command. This works globally if you used the automatic installer, or from the installation directory for manual installs:

```bash
hydrabot start          # Start the bot
hydrabot update         # Update to latest version
hydrabot update --force # Force update even if version matches
hydrabot config         # Edit config.json
hydrabot status         # View install status and config summary
hydrabot logs [N]       # View last N lines of logs (default 50)
hydrabot help           # Show full help
```

> ℹ️ **Not working globally?** If using manual install, either navigate to the installation directory or add it to PATH. See [QUICKSTART.md](QUICKSTART.md) for detailed instructions.

---

## Configuration: config.json

Copy `config.example.json` and modify:

```json
{
  "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "authorized_users": [123456789],

  "max_tokens": 4096,
  "max_history": 50,

  "models": [
    {
      "name": "Primary Claude Sonnet",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-sonnet-4-6",
      "description": "Balanced performance, main conversation model"
    },
    {
      "name": "Fast Claude Haiku",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-haiku-3-5",
      "description": "Lightweight and fast, ideal for parallel sub-agent tasks"
    },
    {
      "name": "Gemini 2.0 Flash",
      "provider": "google",
      "api_key": "YOUR_GOOGLE_AI_KEY",
      "model": "gemini-2.0-flash",
      "description": "Google Gemini with ultra-long context"
    }
  ]
}
```

### Supported AI Providers

| Provider | `provider` value | Notes |
|----------|------------------|-------|
| Anthropic Claude | `anthropic` | Claude Sonnet / Haiku / Opus |
| OpenAI / GPT | `openai` | GPT-4o, o1, etc. |
| Google Gemini | `google` | Gemini 2.0 Flash, etc. |
| Custom OpenAI-compatible API | `openai` + `base_url` | Groq, DeepSeek, Ollama, local LLM, etc. |

### Parameters

| Parameter | Description |
|-----------|-------------|
| `telegram_token` | Bot Token obtained from BotFather |
| `authorized_users` | List of authorized Telegram user IDs (empty array = no restriction) |
| `max_tokens` | Max tokens per response (default 4096) |
| `max_history` | Number of conversation turns to retain (default 50) |

---

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message; guide timezone setup on first use |
| `/reset` | Clear conversation history for current session |
| `/tools` | List all available tools (including dynamic tools) |
| `/models` | View available models; `/models N` to switch to model N |
| `/tasks` | View background task progress |
| `/notify` | List scheduled notifications; `/notify cancel <id>` to cancel |
| `/timezone` | View current timezone; `/timezone UTC+8` to set |
| `/whitelist` | Manage the authorized users list; `/whitelist add <id>` to add, `/whitelist remove <id>` to remove |
| `/status` | Show system status (version, timezone, models, tool count, schedule count, etc.) |
| `/new_agent` | Start the wizard to create a new sub-agent Bot |
| `/list_agents` | List all registered sub-agent Bots and their status |
| `/delete_agent [name]` | Delete a sub-agent Bot (offers graveyard archival) |

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

| Format | Example | Description |
|--------|---------|-------------|
| Relative | `+30m` / `+2h` / `+1d` | N minutes / hours / days from now |
| Absolute | `2026-03-01T09:00:00` | User's local time (auto timezone conversion) |

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

Use the **`spawn_agent` tool** (called by the LLM) when one project needs multiple AI models working in parallel on different subtasks.

- Runs as background threads within the same process
- Each task can use a different AI model
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

| Scenario | Recommended |
|----------|-------------|
| Different daily topics, just need isolated chat | **Topics** |
| Large document / research project — multiple models working in parallel | **`spawn_agent`** |
| Deliver a project: build → git commit → deploy to cloud | **Sub-agent Bot** (`/new_agent`) |

**Decision rule of thumb:**
- Work is *conversational or research-based* with no dedicated git repo → **Topics**
- Work produces a *deliverable* (code, app, git repo, cloud deployment) → **Sub-agent Bot**
- Within that project, needs *parallel AI workstreams* (research + writing + review simultaneously) → **`spawn_agent`** inside the Sub-agent Bot

## Built-in Tools

| Tool | Description |
|------|-------------|
| `execute_python` | Execute Python code (variables persist across calls) |
| `execute_shell` | Execute shell commands with timeout and cwd support |
| `read_file` | Read local files with offset/limit pagination |
| `write_file` | Write or append to local files |
| `list_files` | List directory contents (supports glob patterns) |
| `install_package` | Install Python packages via `pip install` |
| `http_request` | HTTP GET / POST and other network requests |
| `read_memory` | Read persistent memory from memory.json |
| `write_memory` | Write to persistent memory |
| `create_tool` | Write and hot-reload a new tool (core of self-expansion) |
| `spawn_agent` | Spawn a named background task with selectable model (parallel execution) |
| `schedule_notification` | Create a scheduled notification |
| `list_notifications` | List all schedules for the current session |
| `cancel_notification` | Cancel a specific schedule |

---

## Self-Expansion: Creating Custom Tools

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
