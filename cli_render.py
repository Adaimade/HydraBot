#!/usr/bin/env python3
"""
HydraBot CLI 終端機呈現（對齊 Claude Code CLI 風格：層級、摺疊長輸出、精簡工具列）。
不依賴第三方套件；無 TTY 時自動關閉 ANSI。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import textwrap
from typing import Any, Mapping

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_CYAN = "\033[36m"
ANSI_GREEN = "\033[32m"
ANSI_MAGENTA = "\033[35m"


def supports_ansi() -> bool:
    if os.environ.get("NO_COLOR", "").strip():
        return False
    return sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    if not supports_ansi():
        return s
    return f"{code}{s}{ANSI_RESET}"


def tool_display_name(internal: str) -> str:
    return {
        "execute_shell": "Bash",
        "execute_python": "Python",
        "read_file": "Read",
        "write_file": "Write",
        "list_files": "List",
        "create_tool": "CreateTool",
        "install_package": "Pip",
        "http_request": "HTTP",
        "remember": "Memory",
        "edit_soul": "SOUL",
        "log_experience": "Experience",
        "recall_experience": "Recall",
        "code1_rag_query": "RAG",
        "spawn_agent": "SubAgent",
        "run_pipeline": "Pipeline",
        "schedule_notification": "Schedule",
        "schedule_task": "Task",
        "list_notifications": "ListNotify",
        "cancel_notification": "CancelNotify",
        "report_progress": "Progress",
        "mcp_connect": "MCP",
        "mcp_disconnect": "MCP",
        "list_mcp_servers": "MCP",
        "format_and_fix": "RuffFix",
        "run_validation": "Validate",
        "quality_gate": "Gate",
        "quick_fix_then_gate": "QuickGate",
        "code_task_guard": "Guard",
    }.get(internal, internal)


def summarize_tool_input(name: str, inp: Mapping[str, Any]) -> str:
    try:
        if name == "execute_shell":
            return str(inp.get("command") or "")[:120]
        if name == "execute_python":
            code = str(inp.get("code") or "")
            one = code.strip().splitlines()[0] if code.strip() else ""
            return (one[:100] + "…") if len(one) > 100 else one or "(code)"
        if name in ("read_file", "write_file"):
            return str(inp.get("path") or "")[:120]
        if name == "list_files":
            p = inp.get("path", ".")
            pat = inp.get("pattern", "*")
            return f"{p} [{pat}]"[:120]
        if name == "create_tool":
            return str(inp.get("tool_name") or "")[:80]
        if name == "install_package":
            return str(inp.get("package") or "")[:80]
        if name == "http_request":
            return f"{inp.get('method', 'GET')} {str(inp.get('url', ''))[:80]}"
        if name == "spawn_agent":
            return str(inp.get("task") or "")[:100]
        if name == "run_pipeline":
            return str(inp.get("description") or "")[:100]
        if name in ("schedule_notification", "schedule_task"):
            return str(inp.get("message") or inp.get("task") or "")[:80]
        if name == "code1_rag_query":
            return str(inp.get("question") or "")[:100]
        raw = json.dumps(dict(inp), ensure_ascii=False)
        return raw[:120] + ("…" if len(raw) > 120 else "")
    except Exception:
        return "…"


def _strip_outer_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:\w*)?\n([\s\S]*?)\n```\s*$", t)
    if m:
        return m.group(1)
    return text


def _display_width() -> int:
    """可讀寬度：終端欄寬減去左側樹狀前綴。"""
    try:
        cols = shutil.get_terminal_size((100, 24)).columns
    except Exception:
        cols = 100
    # 「  │ 」約占 4～6 字元
    w = cols - 8
    return max(48, min(108, w))


def _assistant_display_width() -> int:
    """助手區塊僅兩格縮排，可略寬於工具樹。"""
    try:
        cols = shutil.get_terminal_size((100, 24)).columns
    except Exception:
        cols = 100
    return max(52, min(112, cols - 4))


def _wrap_body_to_lines(body: str, width: int) -> list[str]:
    """將工具輸出拆成多行；超長單行依欄寬強制換行（避免一整塊無法閱讀）。"""
    out: list[str] = []
    for raw in body.splitlines():
        if len(raw) <= width:
            out.append(raw)
            continue
        chunks = textwrap.wrap(
            raw,
            width=width,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if chunks:
            out.extend(chunks)
        else:
            out.append(raw[: width - 1] + "…")
    return out


def _extract_exit_code(shell_output: str) -> str | None:
    m = re.search(r"返回碼:\s*(-?\d+)", shell_output)
    if m:
        return m.group(1)
    m2 = re.search(r"returncode[:\s]+(-?\d+)", shell_output, re.I)
    return m2.group(1) if m2 else None


def print_tool_start(tool_name: str, inputs: Mapping[str, Any]) -> None:
    label = tool_display_name(tool_name)
    summary = summarize_tool_input(tool_name, inputs)
    bullet = _c(ANSI_CYAN, "●")
    line = (
        f"{bullet} {_c(ANSI_BOLD, label)}"
        f"{_c(ANSI_DIM, '(')}{summary}{_c(ANSI_DIM, ')')}"
    )
    print(f"\n{line}", flush=True)


def print_tool_result(tool_name: str, result: Any) -> None:
    raw = str(result) if result is not None else ""
    body = _strip_outer_fence(raw)
    width = _display_width()
    lines = _wrap_body_to_lines(body, width)

    # 換行排版後仍可能極長：限制「顯示行數」與「顯示字元」
    max_lines = 28
    max_chars = 9000
    prefix = _c(ANSI_DIM, "  │ ")

    if tool_name == "execute_shell":
        ec = _extract_exit_code(raw)
        status = f"exit {ec}" if ec is not None else "done"
        print(f"{_c(ANSI_DIM, '  ├─ ')}{_c(ANSI_GREEN if ec == '0' else ANSI_MAGENTA, status)}{ANSI_RESET}", flush=True)

    shown: list[str] = []
    acc = 0
    truncated = False
    for line in lines:
        if len(shown) >= max_lines:
            truncated = True
            break
        take = line
        if acc + len(take) + 1 > max_chars:
            remain = max_chars - acc - 1
            if remain > 12:
                take = take[:remain] + "…"
                shown.append(take)
            truncated = True
            break
        shown.append(take)
        acc += len(take) + 1

    for line in shown:
        print(f"{prefix}{line}", flush=True)

    if truncated:
        rest_lines = len(lines) - len(shown)
        hint = " 已摺疊 · 模型仍會讀取完整輸出"
        if rest_lines > 0:
            tail = f"+ {rest_lines} 行（換行排版後）{hint}"
        else:
            tail = f"輸出過長已截斷{hint}"
        print(
            f"{_c(ANSI_DIM, '  └─ ')}"
            f"{_c(ANSI_GREEN, tail)}"
            f"{ANSI_RESET}",
            flush=True,
        )


def print_banner(workspace_hint: str = "") -> None:
    bar = "─" * 56
    title = _c(ANSI_BOLD + ANSI_CYAN, " HydraBot CLI ")
    print(f"\n{bar}")
    print(f"  {title}{ANSI_RESET}  終端機模式 · 工具輸出已精簡顯示")
    if workspace_hint:
        print(f"  {_c(ANSI_DIM, '工作區 ' + workspace_hint)}{ANSI_RESET}")
    print(f"{bar}")
    print(
        f"  {_c(ANSI_DIM, '› 輸入訊息與模型對話  ·  /help 指令說明  ·  /quit 結束')}{ANSI_RESET}\n"
    )


def print_assistant_block(text: str) -> None:
    """最終助手回覆：與工具區塊視覺分離；長行依終端寬度換行。"""
    if not text.strip():
        return
    print(_c(ANSI_DIM, "  ─ assistant ─────────────────────────────────"), flush=True)
    width = _assistant_display_width()
    prefix = "  "
    for para in text.rstrip().split("\n"):
        if not para.strip():
            print(flush=True)
            continue
        if len(para) <= width:
            print(f"{prefix}{para}", flush=True)
        else:
            for chunk in _wrap_body_to_lines(para, width):
                print(f"{prefix}{chunk}", flush=True)
    print(_c(ANSI_DIM, "  ─────────────────────────────────────────────"), flush=True)


def format_subagent_push(text: str) -> str:
    """背景子任務推送：避免粗獷的 [推送]。"""
    bar = _c(ANSI_DIM, "  ╭─ 子代理推送 ─────────────────────────────")
    end = _c(ANSI_DIM, "  ╰──────────────────────────────────────────")
    return f"\n{bar}\n{text.rstrip()}\n{end}"


def prompt_line() -> str:
    return _c(ANSI_CYAN, "› ") + ANSI_RESET if supports_ansi() else "› "

