#!/usr/bin/env python3
import json
from pathlib import Path


def get_tools():
    def code_task_guard(
        task: str,
        cwd: str = ".",
        require_tests: bool = True,
    ) -> str:
        workdir = Path(cwd).resolve()
        if not workdir.exists():
            return f"❌ 目錄不存在: {workdir}"

        checklist = [
            "是否對齊需求與範圍",
            "是否引用規格/驗收依據",
            "是否列出影響檔案",
            "是否包含驗證命令",
            "是否執行 quality gate",
        ]
        if require_tests:
            checklist.append("是否新增或更新測試")

        payload = {
            "task": task,
            "cwd": str(workdir),
            "must_follow": [
                "先檢索規格再改碼",
                "改碼後必跑 quick_fix_then_gate",
                "gate 未過不得宣告完成",
            ],
            "checklist": checklist,
        }
        return (
            "🧭 CODE TASK GUARD\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```"
        )

    return [
        (
            "code_task_guard",
            {
                "name": "code_task_guard",
                "description": "寫碼任務前產生守門清單，約束流程與驗證要求。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "cwd": {"type": "string"},
                        "require_tests": {"type": "boolean"},
                    },
                    "required": ["task"],
                },
            },
            code_task_guard,
        )
    ]

