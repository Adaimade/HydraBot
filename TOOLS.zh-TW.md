# 工具參考

本文件整理**選用品質工具**、**內建工具一覽**，以及**自訂工具**的撰寫方式。安裝與整體設定請見 [README.zh-TW.md](README.zh-TW.md)、[config.example.json](config.example.json)。

[English](TOOLS.md)

---

## 品質工具（選用）

專案內建於 `tools/` 的輔助工具（亦可透過 `create_tool` 擴充）：**`format_and_fix`**、**`run_validation`**、**`quality_gate`**、**`quick_fix_then_gate`**、**`code_task_guard`**。它們以 **`python -m ruff` / `mypy` / `pytest`** 執行，請在 **HydraBot 同一個 venv** 內安裝對應套件。使用時機與敘事層約束另見根目錄 **[SOUL.md](SOUL.md)**。

| 工具 | 用途簡述 |
|------|----------|
| `format_and_fix` | 格式化／修 lint（Ruff 等） |
| `run_validation` | 依專案設定跑檢查（測試、型別等） |
| `quality_gate` | 彙總驗證 gate |
| `quick_fix_then_gate` | 快速修正後再驗證 |
| `code_task_guard` | 改碼回合的守門與約束 |

相關 `config.json` 鍵：`enforce_gate_policy`、`gate_forbidden_in_qa`、`require_gate_before_done`，以及 `tool_trace_stdout` / `tool_trace_to_chat` 等工具追蹤設定。

---

## 內建工具一覽

| 工具 | 說明 |
|------|------|
| `execute_python` | 執行 Python 程式碼（變數跨次呼叫保留） |
| `execute_shell` | 執行 Shell 指令，支援 timeout 與 cwd |
| `read_file` | 讀取本地檔案，支援 offset / limit 分頁 |
| `write_file` | 寫入或追加本地檔案 |
| `list_files` | 列出目錄內容（支援 glob pattern） |
| `grep_search` | 以正則搜尋檔案內容（優先 `rg`，後備 `grep`） |
| `find_files` | 以 glob 模式搜尋檔案／目錄名稱 |
| `install_package` | `pip install` 安裝 Python 套件 |
| `http_request` | HTTP GET / POST 等網路請求 |
| `remember` | 持久化 key-value 記憶（`set` / `get` / `list` / `delete`） |
| `list_tools` | 列出目前會話可用的所有工具 |
| `create_tool` | 撰寫並熱載入新工具（自我擴展核心） |
| `mcp_connect` | 連線 MCP 伺服器並載入工具（支援請求 timeout） |
| `mcp_disconnect` | 斷開 MCP 伺服器並卸載工具 |
| `list_mcp_servers` | 列出已連線 MCP 伺服器與狀態 |
| `create_mcp_server` | 在 `mcp_servers/` 建立 MCP 伺服器腳本（stdio JSON-RPC） |
| `edit_soul` | 讀取／更新 `SOUL.md` 人設（見 [README.zh-TW.md](README.zh-TW.md) 的 Bot 人設一節） |
| `log_experience` | 把成功/失敗/洞見記錄到 `experience_log.json` |
| `recall_experience` | 依語意檢索相似過往經驗，輔助排錯與複用解法 |
| `code1_rag_query` | 查詢選用之 **HydraBot-code1.0** 本機向量庫（需設定 `hydrabot_code1_root` 並安裝 `requirements_rag.txt`） |
| `spawn_agent` | 並行子代理；依 `task_role` 自動選層，可選 `model_index` 覆寫 |
| `run_pipeline` | 多步驟 Pipeline，每步可設 `task_role` 與依賴關係 |
| `report_progress` | 子代理執行中推送進度（不可再遞迴呼叫 `spawn_agent`） |
| `schedule_notification` | 建立定時通知排程 |
| `schedule_task` | 建立到點由模型執行任務的排程 |
| `list_notifications` | 列出當前會話的所有排程 |
| `cancel_notification` | 取消指定排程 |

實際可用工具可能因介面或子代理身分而略有差異；請以 Telegram／Discord 的 `/tools` 或會話內 `list_tools` 為準。

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

每個模組透過 `get_tools()` 回傳 `(名稱, schema, 可呼叫物件)` 的列表。檔案變更後可依流程使用 `create_tool` 熱載入，或視需求重啟。
