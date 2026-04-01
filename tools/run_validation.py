#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


def get_tools():
    def run_validation(
        cwd: str = ".",
        run_ruff: bool = True,
        run_mypy: bool = True,
        run_pytest: bool = True,
        timeout: int = 180,
    ) -> str:
        workdir = Path(cwd).resolve()
        if not workdir.exists():
            return f"❌ 目錄不存在: {workdir}"

        steps = []
        if run_ruff:
            steps.append(("ruff", [sys.executable, "-m", "ruff", "check", "."]))
        if run_mypy:
            steps.append(("mypy", [sys.executable, "-m", "mypy", "."]))
        if run_pytest:
            steps.append(("pytest", [sys.executable, "-m", "pytest", "-q"]))

        results = []
        all_ok = True

        for name, args in steps:
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
                all_ok = all_ok and ok
                results.append(
                    {
                        "step": name,
                        "ok": ok,
                        "returncode": r.returncode,
                        "stdout": r.stdout[-4000:],
                        "stderr": r.stderr[-4000:],
                    }
                )
            except subprocess.TimeoutExpired:
                all_ok = False
                results.append(
                    {
                        "step": name,
                        "ok": False,
                        "returncode": -1,
                        "stdout": "",
                        "stderr": f"timeout after {timeout}s",
                    }
                )

        summary = {"all_ok": all_ok, "cwd": str(workdir), "results": results}
        head = "✅ 驗證全部通過" if all_ok else "❌ 驗證未通過"
        return head + "\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```"

    return [
        (
            "run_validation",
            {
                "name": "run_validation",
                "description": "在指定目錄執行 ruff/mypy/pytest，回傳結構化結果。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string", "description": "專案目錄"},
                        "run_ruff": {"type": "boolean", "description": "是否執行 ruff"},
                        "run_mypy": {"type": "boolean", "description": "是否執行 mypy"},
                        "run_pytest": {
                            "type": "boolean",
                            "description": "是否執行 pytest",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "每步逾時秒數",
                        },
                    },
                    "required": [],
                },
            },
            run_validation,
        )
    ]

