# 🚀 HydraBot 快速開始指南

安裝完成後，您可以使用統一的 `hydrabot` 命令在所有平台上啟動。

---

## 📋 安裝方式

### 方法 1：使用安裝腳本（推薦）

自動配置一切，包括 PATH 設置。安裝過程中會請你選擇訊息平台：

- **僅 Telegram** — 填 BotFather Token 與（選用）授權使用者 ID  
- **僅 Discord** — 填 Bot Token、（選用）授權 Snowflake ID；請在 Developer Portal 開啟 **Message Content Intent**  
- **Telegram + Discord** — 兩邊都會詢問  

未使用的平台在 `config.json` 裡對應 token 可留空。自動化部署可用環境變數覆寫，例如 `HB_PLATFORM`（`1` / `2` / `3` 或 `tg` / `dc` / `both`）、`HB_TG_TOKEN`、`HB_DC_TOKEN`、`HB_AUTH_USERS`、`HB_DC_AUTH_USERS`。

**Windows (PowerShell)：**
```powershell
irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex
```

**Linux / macOS：**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
```

### 方法 2：手動安裝

```bash
git clone https://github.com/Adaimade/HydraBot.git
cd HydraBot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# 編輯 config.json 填入您的 API 金鑰
```

**手動安裝後需要設置 PATH** (見下方)

---

## 🧪 內建品質工具與 Gate 政策

專案內 `tools/` 目錄可放置（或由 `create_tool` 建立）下列工具，用於改碼後驗證；它們使用 **目前 venv 的 Python**（`python -m ruff` 等），請在 venv 內安裝 `ruff`、`mypy`、`pytest`（若尚未安裝）。

| 工具 | 用途 |
|------|------|
| `format_and_fix` | `ruff check --fix` + `ruff format` |
| `run_validation` | `ruff` / `mypy` / `pytest`（可選步驟） |
| `quality_gate` | 最小閘門：`ruff check` + `pytest` |
| `quick_fix_then_gate` | 一鍵：fix → format → check → mypy → pytest |
| `code_task_guard` | 寫碼任務前輸出守門清單與流程約束 |

在 `config.json` 可調整（詳見 `config.example.json`）：

- **`tool_trace_stdout` / `tool_trace_to_chat`**：是否將每次工具呼叫摘要印到終端機，或額外推送到聊天（除錯用，後者較吵）。  
- **`enforce_gate_policy` / `gate_forbidden_in_qa` / `require_gate_before_done`**：執行階段對「一般問答 vs 改碼任務」的 gate 行為（預設開啟時，QA 回合不會亂跑 gate；改碼任務若未通過 gate 即宣告「完成」會被提醒）。

人設與與 code1.0 向量庫銜接的細節見根目錄 **[SOUL.md](SOUL.md)**。

---

## 🎯 啟動 HydraBot

### ✅ 最推薦：從任何地方執行

安裝腳本會自動添加 HydraBot 到 PATH，所以您可以**從任何目錄**執行：

```bash
# 任何地方都可以執行，腳本會自動找到安裝目錄
hydrabot start      # 啟動 Bot
hydrabot update     # 更新到最新版本（保留您的 config）
hydrabot config     # 編輯設定
hydrabot status     # 查看狀態
hydrabot help       # 顯示幫助
```

**工作原理：**
- 啟動器會自動偵測自己的位置
- 自動切換到安裝目錄
- 查找虛擬環境中的 Python
- 執行命令

### 備選方案：在安裝目錄中執行

如果 PATH 設置有問題，您也可以進入安裝目錄後執行：

**Windows：**
```powershell
cd C:\path\to\HydraBot
.\hydrabot.cmd start
# 或使用 PowerShell
.\hydrabot.ps1 start
# 或直接用 Python
.\venv\Scripts\python.exe main.py
```

**Linux / macOS：**
```bash
cd /path/to/HydraBot
./hydrabot start
# 或
source venv/bin/activate
python main.py
```

---

## 🔧 PATH 設置（手動安裝用戶）

### Windows

1. **PowerShell 方式：** (推薦)
```powershell
# 將 HydraBot 目錄添加到 PATH
$HydraPath = "C:\path\to\HydraBot"
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$HydraPath*") {
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        "$userPath;$HydraPath",
        "User"
    )
    # 立即在當前 PowerShell 加載新 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Host "✅ PATH 已更新。您現在可以立即使用 hydrabot 命令"
}
```

2. **GUI 方式：**
   - 打開 「編輯系統環境變數」
   - 點擊「環境變數」→「編輯 Path」
   - 添加 HydraBot 安裝目錄
   - 重啟命令行

### Linux / macOS

添加到 `~/.bashrc` 或 `~/.zshrc`：
```bash
export PATH="$HOME/.local/bin:$PATH"
# 或將完整路徑添加
export PATH="/path/to/hydrabot:$PATH"
```

然後立即加載（現在就可以使用 hydrabot）：
```bash
source ~/.bashrc  # 或 source ~/.zshrc
```

如果 hydrabot 命令無法找到，請確認您的 shell：
```bash
# 如果使用 zsh（macOS 預設）
source ~/.zshrc

# 如果使用 bash
source ~/.bashrc
```

---

## ✅ 驗證安裝

```bash
hydrabot status
```

應該顯示：
- ✓ 配置文件存在
- ✓ 虛擬環境存在
- ✓ 模型配置
- ✓ 授權用戶

---

## 📝 常見命令

| 命令 | 說明 | 使用位置 |
|------|------|---------|
| `hydrabot start` | 啟動 HydraBot Bot | 任何地方 |
| `hydrabot update` | 更新代碼（自動保留設定） | 任何地方 |
| `hydrabot update --force` | 強制更新（即使版本相同） | 任何地方 |
| `hydrabot config` | 編輯設定文件 | 任何地方 |
| `hydrabot status` | 查看安裝狀態與設定 | 任何地方 |
| `hydrabot logs [N]` | 查看最近 N 行日誌 | 任何地方 |
| `hydrabot help` | 顯示幫助 | 任何地方 |

---

## 🔄 更新 HydraBot

### 自動保留您的設定

更新時會自動備份和恢復：
- ✅ `config.json` - 您的 API 金鑰和設定
- ✅ `tools/` 目錄 - 自定義工具
- ✅ `memory.json` - 對話歷史

```bash
# 簡單更新（推薦）
hydrabot update

# 強制更新（即使版本相同）
hydrabot update --force
```

**更新過程：**
1. 檢查新版本
2. 備份用戶數據
3. 下載核心文件
4. 恢復備份的設定
5. 更新 Python 依賴

**注意：** 更新後需要重啟 Bot 以應用更改
```bash
hydrabot start
```

---

## ❓ 常見問題

### Q: 執行 `hydrabot` 時出現「未找到命令」

**A:** 說明 PATH 未正確設置。
- 確認已運行安裝腳本
- 重啟終端或執行 `source ~/.bashrc`
- 或使用完整路徑：`./hydrabot start`

### Q: 出現 `ImportError: No module named 'openai'`

**A:** 說明未在虛擬環境中運行。
- 確認使用了 `hydrabot start` 命令
- 或手動激活虛擬環境：
  ```bash
  # Linux/macOS
  source venv/bin/activate

  # Windows
  .\venv\Scripts\Activate.ps1
  ```

### Q: PowerShell 無法執行腳本

**A:** 設置執行策略：
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 🆘 需要幫助？

- 查看完整 [README](README.md) 與 [README.zh-TW.md](README.zh-TW.md)
- 人設與工具約束：[SOUL.md](SOUL.md)
- 提交 Issue: https://github.com/Adaimade/HydraBot/issues
