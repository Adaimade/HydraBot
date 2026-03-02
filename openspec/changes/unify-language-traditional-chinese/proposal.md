# Unify Language to Traditional Chinese

**Type**: Refactor
**Status**: proposed
**Date**: 2026-03-03

---

## Summary

統一 HydraBot 所有面向使用者的字串為繁體中文，程式碼內部（變數名、函式名、註解、log 輸出）保持英文。

## Motivation

目前程式碼庫中使用者可見的文字混雜了三種語言：

- **簡體中文**：`main.py` 的配置錯誤訊息（「未设置」、「配置错误」）、`agent.py` 的 system prompt（「执行代码」、「文件管理」）、`bot.py` 部分狀態訊息（「当前会话」、「工具总数」）
- **繁體中文**：`bot.py` 的 Telegram 指令提示、時區設定、子代理 wizard
- **英文**：部分 log 輸出、工具 schema 說明

此不一致造成使用者體驗零散、維護困難，且與專案的台灣/繁中使用者定位不符。

## Proposed Solution

### 規則

1. **使用者可見字串** → 繁體中文
   - Telegram 發送的所有訊息（`reply_text`、`send_message`）
   - 錯誤提示與警告（顯示給使用者的部分）
   - Bot 指令說明（`BotCommand` 的 description）
   - System prompt 中面向 LLM 的說明文字
   - `print()` 中含 emoji 的啟動訊息（使用者看得到的部分）

2. **保持英文** → 程式碼內部
   - 變數名、函式名、類別名
   - Python 程式碼註解（`# ...`）
   - `logging` 輸出（`logger.info/warning/error`）
   - `print()` 純技術 debug 輸出（不含 emoji 的純 log）
   - 工具 schema 中的 `name` 欄位

### 受影響檔案

| 檔案 | 問題 | 變更量 |
|------|------|--------|
| `main.py` | 配置錯誤訊息全為簡體 | 中 |
| `bot.py` | 混用繁簡，`cmd_status` 大量簡體 | 大 |
| `agent.py` | system prompt 全為簡體，部分 tool desc 簡體 | 大 |

## Alternatives Considered

- **全面英文化**：會讓一般使用者難以使用，排除。
- **保持現狀**：混亂的語言體驗持續累積技術債，排除。
- **繁簡自動轉換**：執行期轉換增加複雜度且不精確，排除。

## Impact

- Affected specs: user-facing strings, system prompt, tool descriptions
- Affected code:
  - `main.py`
  - `bot.py`
  - `agent.py`
