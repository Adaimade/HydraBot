# 🐍 HydraBot

> **Self-expanding AI Assistant via Telegram**
> An AI assistant running on your local machine. Chat with it through Telegram to execute code, manage files, spawn parallel sub-agents, and even create new tools at runtime to expand its own capabilities — just like a hydra: cut off one head and more grow back.

> **透過 Telegram 操控的自我擴展 AI 助手**
> 運行在你本地機器上的 AI 助手，透過 Telegram 與之對話，能執行程式碼、管理檔案、並行派出子代理，甚至在執行時自行建立新工具來擴展自身能力——就像九頭蛇一樣，砍掉一頭會再長出更多。

[![Version](https://img.shields.io/badge/version-1.2.0-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Features / 特色功能

| Feature | Description |
|---------|-------------|
| 🤖 **Multi-Model Support** | Configure up to 3 AI models simultaneously (primary + fast + backup), switchable mid-conversation |
| ⚡ **Parallel Sub-Agents** | `spawn_agent` — delegate subtasks to other models, running in parallel without blocking |
| 🔧 **Self-Expansion** | `create_tool` — the LLM can write and hot-reload new tools at runtime |
| 💻 **Local Execution** | Python / Shell code runs directly on your machine with full filesystem access |
| ⏰ **Scheduled Notifications** | Schedule one-time or recurring notifications pushed automatically to Telegram |
| 🌍 **Timezone Awareness** | First-run guide for UTC timezone setup; all notification times shown in user's local time |
| 🧠 **Persistent Memory** | `memory.json` — store arbitrary key-value data across conversations |
| 📊 **Progress Reporting** | Sub-agents can call `report_progress` in real-time during execution |
| 🏢 **Multi-Project Isolation** | Each Telegram group / Topic has completely independent conversation context |
| 🔌 **MCP Support** | Connect to MCP Servers to dynamically extend tool capabilities |

| 功能 | 說明 |
|------|------|
| 🤖 **多模型並存** | 同時配置最多 3 組 AI 模型，主力 + 快速 + 備用，對話中可即時切換 |
| ⚡ **並行子代理** | `spawn_agent` — 把子任務派給其他模型，後台並行執行，互不阻塞 |
| 🔧 **自我擴展** | `create_tool` — LLM 可在運行時自行撰寫並熱載入新工具 |
| 💻 **本地執行** | Python / Shell 程式碼直接跑在你的機器上，可讀寫本地檔案 |
| ⏰ **定時通知** | 排程一次性或循環通知，到時自動推送到 Telegram |
| 🌍 **時區感知** | 首次使用引導設定 UTC 時區，所有通知時間皆以用戶本地時間顯示 |
| 🧠 **持久記憶** | `memory.json` — 可跨對話保存任意 key-value 資料 |
| 📊 **進度推送** | 子代理執行中可即時呼叫 `report_progress` 推送進度更新 |
| 🏢 **多專案隔離** | 每個 Telegram 群組 / Topic 擁有完全獨立的對話脈絡 |
| 🔌 **MCP 支援** | 可連接 MCP Server，動態擴充外部工具能力 |

---

## Quick Install / 快速安裝

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
```

The installer will automatically:
1. Detect and install Python 3.9+
2. Clone / download core files
3. Create a Python virtual environment and install dependencies
4. Interactively prompt for your Telegram Token and AI API Key
5. Create the global `hydrabot` command

安裝器會自動完成：
1. 檢測並安裝 Python 3.9+
2. 克隆/下載核心檔案
3. 建立 Python 虛擬環境並安裝依賴
4. 互動式填寫 Telegram Token、AI API Key
5. 建立全域 `hydrabot` 指令

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
```

### Manual Install / 手動安裝

```bash
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json to fill in credentials / 編輯 config.json 填入憑證
python main.py
```

---

## Start & Manage / 啟動與管理

```bash
hydrabot start          # Start the bot / 啟動 Bot
hydrabot update         # Update to latest version / 更新到最新版本
hydrabot update --force # Force update even if version matches / 強制更新（即使版本相同）
hydrabot config         # Edit config.json / 編輯 config.json
hydrabot status         # View install status and config summary / 查看安裝狀態與配置摘要
hydrabot logs [N]       # View last N lines of logs (default 50) / 查看最近 N 行日誌（預設 50）
hydrabot help           # Show full help / 顯示完整幫助
```

---

## Configuration: config.json / 設定檔

Copy `config.example.json` and modify:
複製 `config.example.json` 並修改：

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

### Supported AI Providers / 支援的 AI Provider

| Provider | `provider` value | Description / 說明 |
|----------|------------------|---------------------|
| Anthropic Claude | `anthropic` | Claude Sonnet / Haiku / Opus |
| OpenAI / GPT | `openai` | GPT-4o, o1, etc. |
| Google Gemini | `google` | Gemini 2.0 Flash, etc. |
| Custom OpenAI-compatible API | `openai` + `base_url` | Groq, DeepSeek, Ollama, local LLM, etc. / Groq、DeepSeek、Ollama、本地 LLM 等 |

### Parameters / 參數說明

| Parameter / 參數 | Description / 說明 |
|------------------|---------------------|
| `telegram_token` | Bot Token from BotFather / BotFather 取得的 Bot Token |
| `authorized_users` | List of authorized Telegram user IDs (empty array = no restriction) / 允許使用的 Telegram 用戶 ID 列表（空陣列 = 不限制） |
| `max_tokens` | Max tokens per response (default 4096) / 每次回覆最大 token 數（預設 4096） |
| `max_history` | Number of conversation turns to retain (default 50) / 保留的對話輪數（預設 50） |

---

## Telegram Bot Commands / Telegram Bot 指令

| Command / 指令 | Description / 說明 |
|----------------|---------------------|
| `/start` | Show welcome message; guide timezone setup on first use / 顯示歡迎訊息，首次使用時引導設定時區 |
| `/reset` | Clear conversation history for current session / 清除當前會話的對話歷史 |
| `/tools` | List all available tools (including dynamic tools) / 列出所有可用工具（含動態工具） |
| `/models` | View available models; `/models N` to switch to model N / 查看可用模型；`/models N` 切換到模型 N |
| `/tasks` | View background sub-agent tasks and live progress / 查看後台子代理任務與即時進度 |
| `/notify` | List scheduled notifications for current session; `/notify cancel <id>` to cancel / 列出當前會話的定時排程；`/notify cancel <id>` 取消 |
| `/timezone` | View current timezone; `/timezone UTC+8` to set / 查看當前時區設定；`/timezone UTC+8` 設定時區 |
| `/status` | Show system status (version, timezone, models, tool count, schedule count, etc.) / 顯示系統狀態（版本、時區、模型、工具數、排程數等） |

---

## Timezone Setup / 時區設定

On first use, HydraBot will automatically guide you through timezone configuration:
HydraBot 首次使用時會自動引導設定時區：

```
🌍 Please set your timezone / 請設定您的時區

• UTC+8  — Taiwan / Hong Kong / China / 台灣 / 香港 / 中國
• UTC+9  — Japan / Korea / 日本 / 韓國
• UTC+7  — Thailand / Vietnam / 泰國 / 越南
• UTC+0  — UK (winter) / 英國（冬令）
• UTC-5  — US Eastern (winter) / 美國東部（冬令）

Enter UTC+8, +8, or just 8 / 直接輸入 UTC+8、+8 或純數字 8 均可：
```

After setup, all scheduled notification times are displayed in the **user's local time**. Timezone data is persisted in `timezones.json` and retained after restarts.

設定後所有定時通知的時間均以**用戶本地時間**顯示。時區資料持久化存於 `timezones.json`，重啟後保留。

```
/timezone          → View current timezone / 查看目前時區
/timezone UTC+8    → Set to UTC+8 / 設定為 UTC+8
/timezone +8       → Same as above / 同上
/timezone 8        → Same as above (range -12 ~ +14) / 同上（範圍 -12 ~ +14）
```

---

## Scheduled Notifications / 定時通知

Tell the bot in natural language, or use the underlying tools directly:
直接用自然語言告訴 Bot，或使用底層工具：

**Trigger Time Formats / 觸發時間格式**

| Format / 格式 | Example / 範例 | Description / 說明 |
|---------------|----------------|---------------------|
| Relative / 相對時間 | `+30m` / `+2h` / `+1d` | N minutes / hours / days from now / N 分鐘 / 小時 / 天後 |
| Absolute / 絕對時間 | `2026-03-01T09:00:00` | User's local time (auto timezone conversion) / 用戶本地時間（自動依時區轉換） |

**Recurrence / 循環間隔**: `minutely` / `hourly` / `daily` / `weekly` / integer seconds (整數秒數)

**Example conversation / 範例對話**:
```
User: Remind me to drink water every day at 9am
Bot:  ✅ Schedule created: sched_a1b2c3d4
      Trigger: 2026-03-02 09:00:00 (UTC+8)
      Recurrence: daily

用戶: 每天早上 9 點提醒我喝水
Bot:  ✅ 排程已建立 sched_a1b2c3d4
      觸發時間: 2026-03-02 09:00:00 (UTC+8)
      重複: daily
```

---

## Built-in Tools / 內建工具一覽

| Tool / 工具 | Description / 說明 |
|-------------|---------------------|
| `execute_python` | Execute Python code (variables persist across calls) / 執行 Python 程式碼（變數跨次呼叫保留） |
| `execute_shell` | Execute shell commands with timeout and cwd support / 執行 Shell 指令，支援 timeout 與 cwd |
| `read_file` | Read local files with offset/limit pagination / 讀取本地檔案，支援 offset / limit 分頁 |
| `write_file` | Write or append to local files / 寫入或追加本地檔案 |
| `list_files` | List directory contents (supports glob patterns) / 列出目錄內容（支援 glob pattern） |
| `install_package` | Install Python packages via `pip install` / `pip install` 安裝 Python 套件 |
| `http_request` | HTTP GET / POST and other network requests / HTTP GET / POST 等網路請求 |
| `read_memory` | Read persistent memory from memory.json / 從 memory.json 讀取持久記憶 |
| `write_memory` | Write to persistent memory / 寫入持久記憶 |
| `create_tool` | Write and hot-reload a new tool (core of self-expansion) / 撰寫並熱載入新工具（自我擴展核心） |
| `spawn_agent` | Spawn a background sub-agent to execute tasks in parallel / 派出後台子代理並行執行任務 |
| `schedule_notification` | Create a scheduled notification / 建立定時通知排程 |
| `list_notifications` | List all schedules for the current session / 列出當前會話的所有排程 |
| `cancel_notification` | Cancel a specific schedule / 取消指定排程 |

---

## Self-Expansion: Creating Custom Tools / 自我擴展：建立自定義工具

The bot can create tools at runtime, or you can place them manually:
Bot 可在執行時自行建立工具，也可以手動放置：

```
HydraBot/
└── tools/
    ├── my_tool.py      ← custom tool / 自定義工具
    └── weather.py      ← another tool / 另一個工具
```

Tool format / 工具格式：

```python
# tools/hello.py
def get_tools():
    def say_hello(name: str) -> str:
        return f"Hello, {name}!"

    schema = {
        "name": "say_hello",
        "description": "Greet someone / 向某人打招呼",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The person's name / 對方名字"}
            },
            "required": ["name"]
        }
    }
    return [("say_hello", schema, say_hello)]
```

---

## Multi-Project Isolation / 多專案隔離

Each **Telegram group** or **Topic** has completely independent:
每個 **Telegram 群組** 或 **Topic（話題）** 擁有完全獨立的：

- Conversation history / 對話歷史
- Timezone settings / 時區設定
- Scheduled notifications / 定時排程
- Python execution environment / Python 執行環境

It is recommended to use different groups or Topics for different projects to completely avoid context contamination.
建議不同專案使用不同群組或 Topic，徹底避免脈絡污染。

---

## Update / 更新

```bash
hydrabot update
```

The updater downloads the latest core files without affecting user data such as `config.json`, `tools/`, and `memory.json`.
更新器會下載最新的核心檔案，不影響 `config.json`、`tools/`、`memory.json` 等用戶數據。

---

## System Requirements / 系統需求

- Python 3.9+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- API Key from at least one AI Provider / 至少一個 AI Provider 的 API Key
- Internet connection / 網路連接

---

## Security Notice / 安全說明

HydraBot executes AI-generated code on your local machine. Please note:
HydraBot 會在你的本機執行 AI 生成的程式碼。請注意：

- Can execute arbitrary Python / Shell commands / 可執行任意 Python / Shell 指令
- Can read and write to the local filesystem / 可讀寫本地檔案系統
- Can install third-party packages via pip / 可透過 pip 安裝第三方套件
- Can make outbound network requests / 可發起外部網路請求
- **It is strongly recommended to set `authorized_users` to restrict access / 強烈建議設定 `authorized_users`，限制授權用戶**

---

## License / 授權

MIT License — Forks and contributions are welcome. / 歡迎 Fork 與貢獻。
