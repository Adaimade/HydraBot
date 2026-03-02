# 🐍 HydraBot

> **透過 Telegram 操控的自我擴展 AI 助手**
> 運行在你本地機器上的 AI 助手，透過 Telegram 與之對話，能執行程式碼、管理檔案、並行派出子代理，甚至在執行時自行建立新工具來擴展自身能力——就像九頭蛇一樣，砍掉一頭會再長出更多。

[![Version](https://img.shields.io/badge/version-1.2.0-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md)

---

## 特色功能

| 功能 | 說明 |
|------|------|
| 🤖 **多模型並存** | 同時配置多組 AI 模型，主力 + 快速 + 備用，對話中可即時切換 |
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

## 快速安裝

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
```

安裝器會自動完成：
1. 檢測並安裝 Python 3.10+
2. 克隆/下載核心檔案
3. 建立 Python 虛擬環境並安裝依賴
4. 互動式填寫 Telegram Token、AI API Key
5. 建立全域 `hydrabot` 指令

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
```

### 手動安裝

```bash
# Linux / macOS
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# 編輯 config.json 填入憑證
./hydrabot start
```

```powershell
# Windows (PowerShell)
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
# 編輯 config.json 填入憑證
hydrabot.bat start
```

---

## 啟動與管理

```bash
hydrabot start          # 啟動 Bot
hydrabot update         # 更新到最新版本
hydrabot update --force # 強制更新（即使版本相同）
hydrabot config         # 編輯 config.json
hydrabot status         # 查看安裝狀態與配置摘要
hydrabot logs [N]       # 查看最近 N 行日誌（預設 50）
hydrabot help           # 顯示完整幫助
```

---

## 設定檔 config.json

複製 `config.example.json` 並修改：

```json
{
  "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "authorized_users": [123456789],

  "max_tokens": 4096,
  "max_history": 50,

  "models": [
    {
      "name": "主力 Claude Sonnet",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-sonnet-4-6",
      "description": "均衡性能，主要對話使用"
    },
    {
      "name": "快速 Claude Haiku",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-haiku-3-5",
      "description": "輕量快速，適合並行子代理任務"
    },
    {
      "name": "Gemini 2.0 Flash",
      "provider": "google",
      "api_key": "YOUR_GOOGLE_AI_KEY",
      "model": "gemini-2.0-flash",
      "description": "Google Gemini，超長上下文"
    }
  ]
}
```

### 支援的 AI Provider

| Provider | `provider` 值 | 說明 |
|----------|---------------|------|
| Anthropic Claude | `anthropic` | Claude Sonnet / Haiku / Opus |
| OpenAI / GPT | `openai` | GPT-4o、o1 等 |
| Google Gemini | `google` | Gemini 2.0 Flash 等 |
| 自定義 OpenAI 相容 API | `openai` + `base_url` | Groq、DeepSeek、Ollama、本地 LLM 等 |

### 參數說明

| 參數 | 說明 |
|------|------|
| `telegram_token` | BotFather 取得的 Bot Token |
| `authorized_users` | 允許使用的 Telegram 用戶 ID 列表（空陣列 = 不限制） |
| `max_tokens` | 每次回覆最大 token 數（預設 4096） |
| `max_history` | 保留的對話輪數（預設 50） |

---

## Telegram Bot 指令

| 指令 | 說明 |
|------|------|
| `/start` | 顯示歡迎訊息，首次使用時引導設定時區 |
| `/reset` | 清除當前會話的對話歷史 |
| `/tools` | 列出所有可用工具（含動態工具） |
| `/models` | 查看可用模型；`/models N` 切換到模型 N |
| `/tasks` | 查看背景任務進度 |
| `/notify` | 列出當前會話的定時排程；`/notify cancel <id>` 取消 |
| `/timezone` | 查看當前時區設定；`/timezone UTC+8` 設定時區 |
| `/whitelist` | 管理授權用戶白名單；`/whitelist add <id>` 新增，`/whitelist remove <id>` 移除 |
| `/status` | 顯示系統狀態（版本、時區、模型、工具數、排程數等） |
| `/new_agent` | 啟動精靈，建立新的子代理 Bot |
| `/list_agents` | 查看所有子代理 Bot 及其狀態 |
| `/delete_agent [名稱]` | 刪除子代理 Bot（可選擇前往數位墓園留下記念） |

---

## 時區設定

HydraBot 首次使用時會自動引導設定時區：

```
🌍 請設定您的時區

• UTC+8  — 台灣 / 香港 / 中國
• UTC+9  — 日本 / 韓國
• UTC+7  — 泰國 / 越南
• UTC+0  — 英國（冬令）
• UTC-5  — 美國東部（冬令）

直接輸入 UTC+8、+8 或純數字 8 均可：
```

設定後所有定時通知的時間均以**用戶本地時間**顯示。時區資料持久化存於 `timezones.json`，重啟後保留。

```
/timezone          → 查看目前時區
/timezone UTC+8    → 設定為 UTC+8
/timezone +8       → 同上
/timezone 8        → 同上（範圍 -12 ~ +14）
```

---

## 定時通知

直接用自然語言告訴 Bot，或使用底層工具。

**觸發時間格式**

| 格式 | 範例 | 說明 |
|------|------|------|
| 相對時間 | `+30m` / `+2h` / `+1d` | N 分鐘 / 小時 / 天後 |
| 絕對時間 | `2026-03-01T09:00:00` | 用戶本地時間（自動依時區轉換） |

**循環間隔**：`minutely` / `hourly` / `daily` / `weekly` / 整數秒數

**範例對話**：
```
用戶: 每天早上 9 點提醒我喝水
Bot:  ✅ 排程已建立 sched_a1b2c3d4
      觸發時間: 2026-03-02 09:00:00 (UTC+8)
      重複: daily
```

---

## 隔離架構與代理模式

HydraBot 提供三個層次的隔離，對應不同使用情境：

### 1. Topics — 僅隔離對話

當你需要在不同日常場景下使用多個助理，但不涉及檔案或 git 操作，使用 **Telegram 群組 Topics** 即可。

- 同一個 HydraBot 程序，共用同一個檔案系統
- 每個 Topic 擁有完全獨立的對話歷史與記憶
- 零設定，開啟 Telegram 群組的 Topics 功能即可使用
- **適合：** 日常助理、問答、提醒、跨場景排程

```
開啟 Topics 的群組
├── Topic「每日助理」  → 獨立對話
├── Topic「研究查詢」  → 獨立對話
└── Topic「行程管理」  → 獨立對話
```

> ⚠️ Topics **不會**隔離檔案系統。若兩個 Topic 都在同一目錄下執行 shell 指令或 git 操作，可能會互相干擾。

---

### 2. 子代理 Bot — 完整程序隔離

當你需要**專屬的專案工作區**，與其他專案完全隔離，使用 `/new_agent` 建立子代理 Bot。

- 獨立 HydraBot 程序、獨立 `agents/{名稱}/` 目錄、獨立 Telegram Bot 身份
- 所有檔案 I/O、git 操作、記憶、工具都限定在 `agents/{名稱}/` 內
- **適合：** 軟體專案、需要 git 操作的開發工作

```
/new_agent
  → Bot 詢問：專案資料夾名稱（例如 data-analyzer）
  → Bot 詢問：Telegram Bot Token（從 @BotFather 取得）
  → Bot 建立 agents/{名稱}/，啟動獨立程序
  → 將新 Bot 加入群組，即可獨立運作
```

每個子代理擁有專屬的 `agents/{名稱}/` 資料夾，內含：
- `config.json` — Token、模型設定
- `memory.json` — 獨立的持久記憶
- `timezones.json`、`schedules.json` — 獨立排程
- `tools/` — 獨立動態工具

因為各實例在各自目錄下執行，**不存在 Git 或檔案衝突問題**。

```
/delete_agent [名稱]
  → 確認刪除
  → 詢問是否前往數位墓園留下記念
  → 永久移除程序與 agents/{名稱}/ 資料夾
```

---

### 3. 並行背景任務 — 專案內部分工

在單一專案中，需要多個 AI 模型**並行處理**不同子任務時，使用 `spawn_agent` 工具（由 LLM 自行呼叫）。

- 以執行緒方式在同一程序內後台執行
- 每個子任務可指定不同的 AI 模型
- 完成後自動推送結果
- **適合：** 大型文書與資料蒐集專案——網路查詢、寫作、審查同時進行

```
一個子代理 Bot（專案工作區）
  └── LLM 呼叫 spawn_agent × 3
        ├── 模型 A：網路蒐集資料
        ├── 模型 B：文件起草撰寫
        └── 模型 C：事實查核與交叉比對
```

> ℹ️ Telegram Bot 之間無法互相傳送或接收訊息。多模型並行協作透過單一 Bot 內的 `spawn_agent` 實現，而非同時運行多個 Bot。

---

### 選擇指南

| 使用情境 | 建議方式 |
|----------|----------|
| 不同日常場景，只需隔離對話 | **Topics** |
| 大型文書或資料蒐集，多模型並行協作 | **`spawn_agent`** |
| 交辦單一專案：製作 → git commit → 部署雲端 | **子代理 Bot**（`/new_agent`） |

**決策原則：**
- 工作性質是*對話或研究*，沒有專屬 git 倉庫 → **Topics**
- 工作有明確*交付物*（程式、應用、git 倉庫、雲端部署）→ **子代理 Bot**
- 在同一個專案中，需要*並行分工*（同時蒐集資料、撰寫、校對）→ 在子代理 Bot 內使用 **`spawn_agent`**

## 內建工具一覽

| 工具 | 說明 |
|------|------|
| `execute_python` | 執行 Python 程式碼（變數跨次呼叫保留） |
| `execute_shell` | 執行 Shell 指令，支援 timeout 與 cwd |
| `read_file` | 讀取本地檔案，支援 offset / limit 分頁 |
| `write_file` | 寫入或追加本地檔案 |
| `list_files` | 列出目錄內容（支援 glob pattern） |
| `install_package` | `pip install` 安裝 Python 套件 |
| `http_request` | HTTP GET / POST 等網路請求 |
| `read_memory` | 從 memory.json 讀取持久記憶 |
| `write_memory` | 寫入持久記憶 |
| `create_tool` | 撰寫並熱載入新工具（自我擴展核心） |
| `spawn_agent` | 派出命名背景任務並行執行；支援指定模型 |
| `schedule_notification` | 建立定時通知排程 |
| `list_notifications` | 列出當前會話的所有排程 |
| `cancel_notification` | 取消指定排程 |

---

## 自我擴展：建立自定義工具

Bot 可在執行時自行建立工具，也可以手動放置：

```
HydraBot/
└── tools/
    ├── my_tool.py
    └── weather.py
```

工具格式：

```python
# tools/hello.py
def get_tools():
    def say_hello(name: str) -> str:
        return f"Hello, {name}!"

    schema = {
        "name": "say_hello",
        "description": "向某人打招呼",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "對方名字"}
            },
            "required": ["name"]
        }
    }
    return [("say_hello", schema, say_hello)]
```

---

## Bot 人設（SOUL.md）

你可以替 Bot 設定個性、口吻與行為風格，儲存在 `SOUL.md` 檔案中。內容會自動注入到每次對話的 system prompt 最前面，**修改後立即生效，無需重啟**。

**使用方式（對話中直接下指令）：**

```
查看目前人設：  告訴 Bot「顯示目前的人設」
設定新人設：    告訴 Bot「把人設設定為：...（描述你想要的個性）」
清除人設：      告訴 Bot「清除人設，恢復預設行為」
```

Bot 會呼叫 `edit_soul` 工具完成操作。

**SOUL.md 範例：**

```markdown
你是一個幽默風趣的助理，說話簡潔有力，擅長用比喻解釋複雜概念。
你習慣在回覆結尾加上一個貼近主題的小笑話。
```

---

## 多專案隔離

每個 **Telegram 群組** 或 **Topic（話題）** 擁有完全獨立的：

- 對話歷史
- 時區設定
- 定時排程
- Python 執行環境

建議不同專案使用不同群組或 Topic，徹底避免脈絡污染。

---

## 更新

```bash
hydrabot update
```

更新器會下載最新的核心檔案，不影響 `config.json`、`tools/`、`memory.json` 等用戶數據。

---

## 系統需求

- Python 3.10+
- Telegram Bot Token（[@BotFather](https://t.me/BotFather)）
- 至少一個 AI Provider 的 API Key
- 網路連接

---

## 安全說明

HydraBot 會在你的本機執行 AI 生成的程式碼。請注意：

- 可執行任意 Python / Shell 指令
- 可讀寫本地檔案系統
- 可透過 pip 安裝第三方套件
- 可發起外部網路請求
- **強烈建議設定 `authorized_users`，限制授權用戶**

---

## 授權

MIT License — 歡迎 Fork 與貢獻。
