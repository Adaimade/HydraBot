#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd: Path, timeout: int) -> dict:
    r = subprocess.run(
        args,
        shell=False,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "cmd": " ".join(args),
        "returncode": r.returncode,
        "ok": r.returncode == 0,
        "stdout_tail": r.stdout[-2000:],
        "stderr_tail": r.stderr[-2000:],
    }


def get_tools():
    def quick_fix_then_gate(cwd: str = ".", timeout: int = 240) -> str:
        workdir = Path(cwd).resolve()
        if not workdir.exists():
            return f"❌ 目錄不存在: {workdir}"

        steps: list[tuple[str, dict]] = []
        all_ok = True

        try:
            steps.append(
                (
                    "ruff_fix",
                    _run(
                        [sys.executable, "-m", "ruff", "check", ".", "--fix"],
                        workdir,
                        timeout,
                    ),
                )
            )
            steps.append(
                (
                    "ruff_format",
                    _run(
                        [sys.executable, "-m", "ruff", "format", "."],
                        workdir,
                        timeout,
                    ),
                )
            )
            steps.append(
                (
                    "ruff_check",
                    _run(
                        [sys.executable, "-m", "ruff", "check", "."],
                        workdir,
                        timeout,
                    ),
                )
            )
            steps.append(
                (
                    "mypy",
                    _run(
                        [sys.executable, "-m", "mypy", "."],
                        workdir,
                        timeout,
                    ),
                )
            )
            steps.append(
                (
                    "pytest",
                    _run(
                        [sys.executable, "-m", "pytest", "-q"],
                        workdir,
                        timeout,
                    ),
                )
            )
        except subprocess.TimeoutExpired:
            return "❌ 執行超時，請縮小改動範圍後重試"

        failed: list[str] = []
        for name, data in steps:
            if not data["ok"]:
                failed.append(name)
                all_ok = False

        result = {
            "cwd": str(workdir),
            "passed": all_ok,
            "failed_steps": failed,
            "steps": [{"name": n, **d} for n, d in steps],
            "next_action": "可宣告完成" if all_ok else "先修正 failed_steps 再回報完成",
        }
        title = "✅ QUICK FIX + GATE PASSED" if all_ok else "❌ QUICK FIX + GATE FAILED"
        return (
            title
            + "\n```json\n"
            + json.dumps(result, ensure_ascii=False, indent=2)
            + "\n```"
        )

    return [
        (
            "quick_fix_then_gate",
            {
                "name": "quick_fix_then_gate",
                "description": "一鍵執行 fix/format/check/type/test，並回傳是否可宣告完成。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": [],
                },
            },
            quick_fix_then_gate,
        )
    ]

