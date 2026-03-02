# Tasks: Unify Language to Traditional Chinese

## Group 1: main.py — 配置錯誤訊息

- [x] 將 `load_config()` 中所有簡體錯誤訊息改為繁體中文
  - `"telegram_token 未设置"` → `"telegram_token 未設定"`
  - `"模型 #{i} ({name}) 缺少 api_key"` → 繁體版本
  - `"model_api_key 未设置"` → `"model_api_key 未設定"`
  - `"❌ config.json 配置错误，请先填写："` → `"❌ config.json 設定有誤，請先填寫："`
  - `"运行 hydrabot.bat config 或直接编辑 config.json"` → 繁體版本
  - `"✅ Created config.json"` 下方的說明文字 → 繁體版本

## Group 2: bot.py — Telegram UI 字串

- [x] 統一 `cmd_status()` 中所有簡體字串為繁體
- [x] 統一 `cmd_reset()` 回應為繁體
- [x] 統一 `cmd_models()` 錯誤訊息為繁體
- [x] 統一 `cmd_start()` 歡迎訊息為繁體
- [x] 統一 `BotCommand` description 為繁體
- [x] 統一 `UNAUTHORIZED_MSG` 為繁體
- [x] 統一啟動 print 訊息為繁體

## Group 3: agent.py + tools_builtin.py — System Prompt 與工具說明

- [x] 將 `_system_prompt()` 主體文字全部改為繁體
- [x] 將 `_anthropic_loop()` / `_openai_loop()` 的錯誤回應改為繁體
- [x] 將 `list_models_info()` 的說明文字改為繁體
- [x] 將 `list_tools_info()` 的說明文字改為繁體
- [x] 將 `switch_model()` 回應改為繁體
- [x] 將 `_load_builtin_tools()` / `_load_dynamic_tools()` 的 print 訊息改為繁體
- [x] 將 `tools_builtin.py` 所有使用者可見字串（工具說明、回傳訊息、schema description）改為繁體
- [x] 將 `status_server.py` HTML 介面文字改為繁體

## Group 4: 最終驗收

- [x] 全域搜尋確認主要 .py 檔案無遺漏簡體使用者字串
- [ ] 啟動 bot 測試：`/start`、`/status`、`/models`、`/tools` 回應語言正確
- [x] 確認英文 log 輸出（`logger.*`）未被更動
