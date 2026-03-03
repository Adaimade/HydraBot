# 🚀 HydraBot 快速開始指南

安裝完成後，您可以使用統一的 `hydrabot` 命令在所有平台上啟動。

---

## 📋 安裝方式

### 方法 1：使用安裝腳本（推薦）

自動配置一切，包括 PATH 設置。

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

## 🎯 啟動 HydraBot

### 如果已設置 PATH（安裝腳本會自動設置）

```bash
# 任何地方都可以執行
hydrabot start
hydrabot config
hydrabot status
```

### 如果未設置 PATH（手動安裝）

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
    Write-Host "PATH 已更新。請重啟 PowerShell 使其生效"
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

然後執行：
```bash
source ~/.bashrc  # 或 source ~/.zshrc
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

| 命令 | 說明 |
|------|------|
| `hydrabot start` | 啟動 HydraBot Bot |
| `hydrabot config` | 編輯設定文件 |
| `hydrabot status` | 查看安裝狀態 |
| `hydrabot help` | 顯示幫助 |

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

- 查看完整 [README](README.md)
- 提交 Issue: https://github.com/Adaimade/HydraBot/issues
