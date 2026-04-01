#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


def get_tools():
    def quality_gate(cwd: str = ".", timeout: int = 180) -> str:
        workdir = Path(cwd).resolve()
        if not workdir.exists():
            return f"❌ 目錄不存在: {workdir}"

        checks = [
            ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
            ("pytest", [sys.executable, "-m", "pytest", "-q"]),
        ]

        fail = []
        detail = []

        for name, args in checks:
            try:
                r = subprocess.run(
                    args,
                    shell=False,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                ok = r.returncode == 0
                detail.append(
                    {
                        "check": name,
                        "ok": ok,
                        "returncode": r.returncode,
                        "stderr_tail": r.stderr[-1500:],
                        "stdout_tail": r.stdout[-1500:],
                    }
                )
                if not ok:
                    fail.append(name)
            except subprocess.TimeoutExpired:
                fail.append(name)
                detail.append(
                    {
                        "check": name,
                        "ok": False,
                        "returncode": -1,
                        "stderr_tail": f"timeout after {timeout}s",
                        "stdout_tail": "",
                    }
                )

        passed = len(fail) == 0
        result = {
            "passed": passed,
            "failed_checks": fail,
            "detail": detail,
            "next_action": "可回報完成" if passed else "先修正 failed_checks 後再提交",
        }
        title = "✅ QUALITY GATE PASSED" if passed else "❌ QUALITY GATE FAILED"
        return title + "\n```json\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n```"

    return [
        (
            "quality_gate",
            {
                "name": "quality_gate",
                "description": "執行最小質量閘門（ruff + pytest），判斷是否可宣告完成。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": [],
                },
            },
            quality_gate,
        )
    ]

