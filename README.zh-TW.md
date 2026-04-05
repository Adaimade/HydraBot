# 🐍 HydraBot

> **支援 Telegram / Discord / CLI 的自我擴展 AI 助手**
> 運行在你本地機器上的 AI 助手，透過 Telegram、Discord 或 CLI 與之對話，能執行程式碼、管理檔案、並行派出子代理，甚至在執行時自行建立新工具來擴展自身能力——就像九頭蛇一樣，砍掉一頭會再長出更多。

[![Version](https://img.shields.io/badge/version-1.2.0-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md)

---

## 為什麼選 HydraBot

- **本地優先**：Shell、Python、檔案與工具都在你的機器上執行。
- **多介面**：Telegram / Discord / CLI 共用同一套 agent 核心。
- **並行工作**：`spawn_agent` + `run_pipeline` 處理多步驟、多模型任務。
- **自我擴展**：執行期動態建立工具（`create_tool`）。
- **偏生產的安全**：權限模式、黑名單、`--dry-run`、JSON 原子寫入、gate 政策。

## 三分鐘上手

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

未帶子指令的 `hydrabot` 會自動選擇：
- 已設定 Telegram/Discord token 時 → `start`
- 未設定即時通 token 時 → `cli`

## 選擇你的模式

### 1) 僅 CLI（不需 Telegram/Discord）

```bash
hydrabot cli
hydrabot run "summarize this repo structure"
hydrabot run "preview tool behavior" --dry-run
```

### 2) 即時通 Bot（Telegram/Discord）

```bash
hydrabot start
```

### 3) 實際執行前先安全預覽

```bash
hydrabot cli --dry-run
hydrabot run "refactor src/utils.py" --dry-run
```

---

## HydraBot vs 典型 Agent Harness

許多專案提供的是**精簡 CLI 迴圈**（工具 + 記憶體 + 選用 MCP）。HydraBot 面向**真實專案上的日常使用**，把通道與排程內建進產品形態。

| 面向 | 典型 harness | HydraBot |
|------|--------------|----------|
| **介面** | 多半僅 CLI | **Telegram、Discord、CLI** — 同一核心 |
| **排程** | 少有或需外掛 | **內建**通知與 LLM 任務（`schedule_*`） |
| **多模型** | 常為單一模型 | **主力 / 快速 / 日常** 分層 + `spawn_routing` |
| **並行** | 視專案而定 | **`spawn_agent`**、**`run_pipeline`**、唯讀工具並行 |
| **自我擴展** | Skills / 外掛 | **`create_tool`**（Python 熱載入）+ **MCP** |
| **安全** | 視專案而定 | **`permission_mode`**、黑名單、**`--dry-run`**、JSON 原子寫入 |

*此處「典型 harness」指輕量、以 CLI 為主的 agent 框架；各專案命名不同。*

---

## 使用情境（可直接複製）

**1) 在專案目錄下快速檢視程式庫（CLI）**

```bash
cd ~/your-project
hydrabot run "列出頂層檔案，然後用 5 個要點說明這個 repo 在做什麼。"
```

**2) 讓模型動檔前先 dry-run**

```bash
cd ~/your-project
hydrabot run "重構 utils 提升可讀性" --dry-run
```

**3) 互動寫程式並可還原長會話**

```bash
hydrabot cli
# CLI 內：長任務後 `/save`，下次 `/resume`，`/usage` 查看 token 統計
```

**4) 團隊頻道 Bot（Telegram 或 Discord）**

```bash
hydrabot start
# 成員在頻道內對話；群組／Topic 脈絡各自隔離。見 /timezone、/notify。
```

---

## 特色功能

| 功能 | 說明 |
|------|------|
| 🤖 **三層模型角色** | **主力 / 快速 / 日常** 對應 `models` 索引；安裝時依序設定，對話中可 `/models` 切換 |
| ⚡ **子代理自動調度** | `spawn_agent` 依任務類型路由到對應層級；主力負責規劃與整合，無需用戶逐個選模型 |
| 🔧 **自我擴展** | `create_tool` — LLM 可在運行時自行撰寫並熱載入新工具 |
| 🖥️ **多通道介面** | 支援 Telegram、Discord 與本地 CLI 模式（`python main.py --cli`） |
| 💻 **本地執行** | Python / Shell 程式碼直接跑在你的機器上，可讀寫本地檔案 |
| ⏰ **定時通知** | 排程一次性或循環通知，到時自動推送到 Telegram |
| 🌍 **時區感知** | 首次使用引導設定 UTC 時區，所有通知時間皆以用戶本地時間顯示 |
| 🧠 **持久記憶** | `memory.json` — 可跨對話保存任意 key-value 資料 |
| 📚 **學習回路** | `experience_log.json` + TF-IDF 檢索；自動記錄失敗並在回應前注入相關經驗 |
| 📊 **進度推送** | 子代理執行中可即時呼叫 `report_progress` 推送進度更新 |
| 🏢 **多專案隔離** | 每個 Telegram 群組 / Topic 擁有完全獨立的對話脈絡 |
| 🔌 **MCP 支援** | 可連接 MCP Server，動態擴充外部工具能力 |
| ✅ **品質工具與 Gate 政策** | 可選的 `tools/` 輔助（Ruff／mypy／pytest 流程）與 `config.json` 守門設定 — 詳見 [TOOLS.zh-TW.md](TOOLS.zh-TW.md) |

---

## 指令速查

```bash
hydrabot start                # Bot 模式（Telegram/Discord）
hydrabot cli                  # 互動終端機
hydrabot run "..."            # 單次非互動提示
hydrabot cli --dry-run        # 預覽工具呼叫，無副作用
hydrabot run "..." --dry-run
hydrabot config               # 編輯 config.json
hydrabot status               # 執行期摘要
hydrabot update               # 更新到最新版
```

---

## 文件導覽

- **快速上手與 PATH**：[QUICKSTART.md](QUICKSTART.md)
- **英文說明**：[README.md](README.md)
- **工具參考（內建一覽、品質工具、自訂工具）**：[TOOLS.zh-TW.md](TOOLS.zh-TW.md) · [TOOLS.md](TOOLS.md)
- **人格規則**：[SOUL.md](SOUL.md)
- **設定範本**：[config.example.json](config.example.json)

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
4. 選擇訊息平台：**僅 Telegram**、**僅 Discord**、**兩者並行**，或 **僅終端機 CLI**（選 4 時不問 Telegram／Discord；之後用 `hydrabot cli` 或 `python3 main.py --cli`）。若選即時通，會再依選擇詢問 Token 與（選用）授權名單（Discord 需在 Developer Portal 開啟 **Message Content Intent**；詳見 `config.example.json` 的 `discord_*` 欄位）
5. 互動式填寫 AI API Key，並依序設定**主力 / 快速 / 日常**三組模型（可含本地 LLM）
6. 設定全域 `hydrabot` 指令（可從任何地方使用）

非互動／CI 部署可設定環境變數：`HB_PLATFORM`（`1`／`2`／`3`／`4` 或 `tg`／`dc`／`both`／`cli`／`terminal`／`none`）、`HB_TG_TOKEN`、`HB_DC_TOKEN`，以及選用的 `HB_AUTH_USERS`、`HB_DC_AUTH_USERS`。僅 CLI 時設 `HB_PLATFORM=4`（或 `cli`）即可略過即時通 token。

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
```

### 手動安裝

對於手動安裝，您需要將安裝目錄添加到 PATH，或者從安裝目錄中執行命令。

**Linux / macOS：**
```bash
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# 編輯 config.json 填入憑證
./hydrabot start
```

**Windows (PowerShell)：**
```powershell
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
# 編輯 config.json 填入憑證
.\hydrabot.cmd start
```

> ℹ️ **PATH 設置**：手動安裝後，請將安裝目錄添加到系統 PATH（這樣 `hydrabot` 可以從任何地方使用），或者一律從安裝目錄中執行命令。詳見 [QUICKSTART.md](QUICKSTART.md) 的 PATH 設置說明。

### 連接 HydraBot-code1.0 本地向量庫（選用）

若你另有 **HydraBot-code1.0** 等本地 RAG 專案（Chroma + Ollama），可在 **同一個 venv** 內安裝額外依賴並設定路徑，讓 HydraBot 透過內建工具 `code1_rag_query` 查詢該向量庫：

```bash
pip install -r requirements_rag.txt
```

在 `config.json` 加入（請改成你本機的絕對路徑）：

```json
"hydrabot_code1_root": "/Users/you/GitHub/HydraBot-code1.0"
```

並確認該專案已執行過索引（`python src/ingest.py`）、Ollama 可連線。對話中模型可呼叫 `code1_rag_query` 取得依庫作答。

---

## 啟動與管理

安裝完成後，您可以使用 `hydrabot` 指令管理 HydraBot。此指令在自動安裝器中可全域使用，手動安裝則需從安裝目錄執行或添加到 PATH：

```bash
hydrabot start          # 啟動 Bot
hydrabot run "..."      # 單次非互動執行（印出結果後退出）
hydrabot cli --dry-run  # 僅預覽工具呼叫，不實際執行
hydrabot run "..." --dry-run
hydrabot update         # 更新到最新版本
hydrabot update --force # 強制更新（即使版本相同）
hydrabot config         # 編輯 config.json
hydrabot status         # 查看安裝狀態與配置摘要
hydrabot logs [N]       # 查看最近 N 行日誌（預設 50）
hydrabot help           # 顯示完整幫助
```

> ℹ️ **指令無法執行？** 如使用手動安裝，請進入安裝目錄後執行，或將安裝目錄添加到 PATH。詳見 [QUICKSTART.md](QUICKSTART.md) 的說明。

---

## CLI 模式

HydraBot 支援終端機互動模式（不需要 Telegram/Discord Token）：

```bash
python main.py --cli
```

也可使用 `-c` 或 `cli`：

```bash
python main.py -c
python main.py cli
```

CLI 內建指令：
- `/help`
- `/reset`
- `/models` / `/model N`
- `/usage`
- `/save`
- `/resume`
- `/tools`
- `/quit`（或 `/exit`）

**終端機介面**：預設啟用精簡輸出（`cli_compact_ui`，見 `config.example.json`）— 工具列以 `● Bash(…)` 階層顯示、長輸出摺疊、子代理推送以邊框區隔，體驗對齊 Claude Code CLI 類型。`cli_compact_ui: false` 可還原舊版；`NO_COLOR=1` 關閉 ANSI。

**CLI 執行期功能補充**：
- 會話自動儲存與自動恢復（`sessions/*.json`）
- CLI 串流輸出（逐 chunk 顯示）
- `--dry-run` 預覽工具呼叫（零副作用）
- 唯讀類工具可能並行執行以降低延遲；寫入類工具維持循序以確保安全

---

## 設定檔 config.json

複製 `config.example.json` 並修改：

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
      "name": "主力 Claude Sonnet",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-sonnet-4-6",
      "description": "主力模型，高強度推理與程式任務"
    },
    {
      "name": "快速 Claude Haiku",
      "provider": "anthropic",
      "api_key": "sk-ant-...",
      "model": "claude-haiku-3-5",
      "description": "快速模型，建議與中量並行子任務"
    },
    {
      "name": "Gemini 2.0 Flash",
      "provider": "google",
      "api_key": "YOUR_GOOGLE_AI_KEY",
      "model": "gemini-2.0-flash",
      "description": "日常模型，輕量摘要與資料整理"
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
| `telegram_token` | BotFather 取得的 Bot Token（若僅使用 Discord 可留空） |
| `discord_token` | Discord Bot Token（若僅使用 Telegram 可留空）；須開啟 Message Content Intent |
| `authorized_users` | 允許使用的 Telegram 用戶 ID 列表（空陣列 = 不限制） |
| `discord_authorized_users` | 允許使用的 Discord 使用者 Snowflake 列表（空陣列 = 不限制） |
| `tool_trace_stdout` | 是否將每次工具呼叫摘要印到進程 stdout（預設 `true`） |
| `tool_trace_to_chat` | 是否額外將摘要推送到聊天視窗（預設 `false`，較吵，適合除錯） |
| `enforce_gate_policy` | 是否啟用「QA／改碼」與 gate 相關的執行階段規則（預設 `true`） |
| `gate_forbidden_in_qa` | 一般問答回合是否阻擋 gate 類工具（預設 `true`） |
| `require_gate_before_done` | 改碼任務若未通過 gate 卻宣告「完成」，是否在回覆後附加提醒（預設 `true`） |
| `permission_mode` | 工具安全模式：`auto`、`default`（CLI 寫入前確認）、`readonly` |
| `denied_commands` | Shell 指令黑名單（子字串比對，例如 `rm -rf /`） |
| `denied_paths` | `read_file` / `write_file` 的路徑黑名單前綴 |
| `max_tokens` | 每次回覆最大 token 數（預設 4096） |
| `max_history` | 保留的對話輪數（預設 50） |
| `model_roles` | 三層角色對應 `models` 陣列索引：`primary`（主力）、`fast`（快速）、`daily`（日常） |
| `spawn_routing` | 子代理任務類型 → 使用哪一層：`reading` / `writing` / `review` / `advice` / `debug` / `general` 對應 `primary` / `fast` / `daily` |

### 品質工具（選用）

與 Ruff／mypy／pytest 及 gate 相關的選用工具位於 `tools/`，並與 `config.json` 連動。**完整列表與說明：** [TOOLS.zh-TW.md](TOOLS.zh-TW.md) · 敘事層約束見 **[SOUL.md](SOUL.md)**。

### 三層模型與子代理路由

- **主力（primary）**：主對話、任務規劃、撰寫程式、除錯、Code Review 等高強度子任務。
- **快速（fast）**：建議、一般查詢、中間整合等中量子任務。
- **日常（daily）**：讀檔摘要、格式轉換、輕量整理。

`spawn_agent` 會依 `task_role`（或 `auto` 時依任務文字）對照 `spawn_routing`，再經 `model_roles` 選出實際模型。**無需**每次詢問用戶要哪個模型；僅在用戶明確指定時才傳入 `model_index`。完整鍵值請見 `config.example.json`。

**本地 LLM（Ollama 等）**：可在 `models` 中配置多筆相同 `base_url`、不同 `model` 名稱（例如 32B / 7B），分別對應主力／快速／日常；並行子代理時請留意本機 VRAM 與 Ollama 載入策略。

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
- 每個子任務依 **任務類型** 自動對應到主力／快速／日常其中一層（可在 `spawn_routing` 調整）
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

## 工具參考

HydraBot 提供檔案系統、Shell、排程、MCP、記憶體、子代理與自我擴展等工具。**內建完整清單、`tools/` 下選用品質工具，以及自訂工具的 Python 格式：** [TOOLS.zh-TW.md](TOOLS.zh-TW.md) · [TOOLS.md](TOOLS.md)。

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
