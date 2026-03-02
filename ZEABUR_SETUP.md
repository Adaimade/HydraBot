# 在 Zeabur 上部署 HydraBot

由於 Zeabur 終端限制粘貼功能，我們提供了環境變數方案，讓你可以快速完成安裝。

## 快速開始（使用環境變數）

### 1️⃣ 在 Zeabur 控制面板設定環境變數

進入你的 Zeabur 項目 → **環境變數** → 添加以下變數：

#### Telegram 配置
```
HB_TG_TOKEN=你的Telegram_Bot_Token
HB_AUTH_USERS=你的Telegram_ID   (可選，留空=允許所有人)
```

#### AI 模型配置（至少填一個）

**模型 0 - 主力模型（必填）**
```
HB_M0_PROVIDER=google
HB_M0_KEY=你的Google_API_Key
HB_M0_MODEL=gemini-2.0-flash
HB_M0_NAME=主力模型-Gemini
```

**模型 1 - 快速模型（可選，推薦填）**
```
HB_M1_PROVIDER=openai
HB_M1_KEY=你的OpenAI_API_Key
HB_M1_MODEL=gpt-4o
HB_M1_NAME=快速模型-GPT
```

**模型 2 - 備用模型（可選）**
```
HB_M2_PROVIDER=anthropic
HB_M2_KEY=你的Anthropic_API_Key
HB_M2_MODEL=claude-sonnet-4-5
HB_M2_NAME=備用模型-Claude
```

### Provider 選項

| Provider | 環境變數值 | API Key 格式 |
|----------|-----------|------------|
| Anthropic Claude | `anthropic` | `sk-ant-...` |
| OpenAI / GPT | `openai` | `sk-...` |
| Google Gemini | `google` | Google AI Studio API Key |
| OpenAI 相容（Groq/DeepSeek） | `openai-compatible` | 相應服務的 API Key |

### 2️⃣ 執行安裝

在 Zeabur 終端執行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
```

**不需要任何輸入** — 所有配置都會自動從環境變數讀取！

### 3️⃣ 驗證安裝

安裝完成後，執行：

```bash
hydrabot status
```

應該會顯示你的模型配置和授權用戶信息。

---

## 環境變數完整列表

| 變數名 | 說明 | 示例 |
|------|------|------|
| `HB_TG_TOKEN` | Telegram Bot Token | `123456:ABCdef...` |
| `HB_AUTH_USERS` | 授權用戶 ID（逗號分隔） | `123456789,987654321` |
| `HB_M0_PROVIDER` | 模型 0 提供商 | `google`, `openai`, `anthropic` |
| `HB_M0_KEY` | 模型 0 API Key | `AIza...` |
| `HB_M0_MODEL` | 模型 0 型號名 | `gemini-2.0-flash` |
| `HB_M0_NAME` | 模型 0 顯示名稱（可選） | `主力模型` |
| `HB_M1_PROVIDER` | 模型 1 提供商（可選） | `openai` |
| `HB_M1_KEY` | 模型 1 API Key（可選） | `sk-...` |
| `HB_M1_MODEL` | 模型 1 型號名（可選） | `gpt-4o` |
| `HB_M1_NAME` | 模型 1 顯示名稱（可選） | `快速模型` |
| `HB_M2_PROVIDER` | 模型 2 提供商（可選） | `anthropic` |
| `HB_M2_KEY` | 模型 2 API Key（可選） | `sk-ant-...` |
| `HB_M2_MODEL` | 模型 2 型號名（可選） | `claude-sonnet-4-5` |
| `HB_M2_NAME` | 模型 2 顯示名稱（可選） | `備用模型` |

---

## 如何獲取所需信息

### 📱 Telegram Bot Token
1. Telegram 搜尋 `@BotFather`
2. 發送 `/newbot`
3. 按提示創建 Bot，獲得 Token（格式：`123456:ABCdef...`）

### 👤 Telegram 用戶 ID
1. Telegram 搜尋 `@userinfobot`
2. 它會返回你的數字 ID

### 🔑 AI API Keys

**Google Gemini**
- 訪問 https://aistudio.google.com/apikey
- 創建新 API Key

**OpenAI / GPT**
- 訪問 https://platform.openai.com/api-keys
- 創建新 Secret Key（`sk-` 開頭）

**Anthropic Claude**
- 訪問 https://console.anthropic.com/
- 創建新 API Key（`sk-ant-` 開頭）

**Groq / DeepSeek**
- 各自平台獲取 API Key
- Provider 設為 `openai-compatible`

---

## 混合模式（環境變數 + 交互式）

如果你只設定了部分環境變數，腳本會自動進入**互動模式**要求填入缺失的信息：

```bash
# 例：只設定了 Telegram Token
HB_TG_TOKEN=你的Token
```

執行安裝時，會自動跳過 Token 輸入，但仍會提示輸入模型配置。

---

## 容器環境注意事項

### 虛擬環境位置
安裝後，虛擬環境在：`/root/hydrabot/venv`

### 啟動 Bot
```bash
cd /root/hydrabot
./venv/bin/python main.py
```

### 查看日誌
```bash
# 最後 20 行日誌
tail -20 /root/hydrabot/logs/bot.log
```

---

## 故障排除

### ❌ "E: Unable to locate package python3-pip"

已修復！確保你用的是最新版本的 `install.sh`。更新方式：
```bash
curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh > install.sh
chmod +x install.sh
bash install.sh
```

### ❌ "ensurepip is not available"

已修復！最新版本會自動處理容器環境中缺失的 venv 包。

### ❌ "API Key 格式不正確"

檢查：
- Anthropic: 應以 `sk-ant-` 開頭
- OpenAI: 應以 `sk-` 開頭
- Google: 應是英數字符串（通常較長）

### ❌ 安裝卡住或超時

重新執行安裝命令，或檢查 Zeabur 終端的網路連接。

---

## 下一步

安裝完成後：

1. **啟動 Bot**：
   ```bash
   hydrabot start
   ```

2. **查看狀態**：
   ```bash
   hydrabot status
   ```

3. **更新**：
   ```bash
   hydrabot update
   ```

祝你使用愉快！有問題請提交 Issue。
