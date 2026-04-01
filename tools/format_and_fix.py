#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


def get_tools():
    def format_and_fix(cwd: str = ".", timeout: int = 180) -> str:
        workdir = Path(cwd).resolve()
        if not workdir.exists():
            return f"❌ 目錄不存在: {workdir}"

        cmds = [
            ("ruff_fix", [sys.executable, "-m", "ruff", "check", ".", "--fix"]),
            ("ruff_format", [sys.executable, "-m", "ruff", "format", "."]),
        ]

        lines = [f"📁 cwd: {workdir}"]
        ok_all = True

        for name, args in cmds:
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
                ok_all = ok_all and ok
                lines.append(f"\n[{name}] rc={r.returncode}")
                if r.stdout.strip():
                    lines.append("stdout:\n```")
                    lines.append(r.stdout[-2500:].rstrip())
                    lines.append("```")
                if r.stderr.strip():
                    lines.append("stderr:\n```")
                    lines.append(r.stderr[-2500:].rstrip())
                    lines.append("```")
            except subprocess.TimeoutExpired:
                ok_all = False
                lines.append(f"\n[{name}] timeout after {timeout}s")

        lines.insert(0, "✅ format/fix 完成" if ok_all else "❌ format/fix 部分失敗")
        return "\n".join(lines)

    return [
        (
            "format_and_fix",
            {
                "name": "format_and_fix",
                "description": "執行 ruff --fix + ruff format，協助先修風格問題。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": [],
                },
            },
            format_and_fix,
        )
    ]

