#!/usr/bin/env python3
"""
HydraBot — 終端機互動模式（CLI）

與 AgentPool 直接對話，無需 Telegram / Discord。
輸出經 cli_render 精簡（階層、摺疊長輸出），風格對齊 Claude Code CLI。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import traceback
from typing import TYPE_CHECKING

try:
    import cli_render
except ImportError:
    cli_render = None  # type: ignore[misc, assignment]

if TYPE_CHECKING:
    from agent import AgentPool

# 固定會話鍵：與 Telegram (chat_id, thread_id) 格式一致
CLI_SESSION_ID = (0, None)


def run_cli(config: dict) -> None:
    """啟動 REPL，直到使用者輸入 /quit 或 EOF。"""
    print("🧠 初始化 Agent Pool…")
    from agent import AgentPool

    pool: AgentPool = AgentPool(config)

    loop = asyncio.new_event_loop()

    def _loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_loop_runner, name="hydra-cli-async", daemon=True).start()

    async def cli_send(session_id: tuple, text: str) -> None:
        if cli_render:
            print(cli_render.format_subagent_push(text), flush=True)
        else:
            print(f"\n[推送]\n{text}\n", flush=True)

    pool._loop = loop
    pool._send_func = cli_send
    pool.scheduler.start(
        loop,
        cli_send,
        task_runner=lambda sid, text: pool.chat(sid, text),
    )

    ws = (config.get("_hydrabot_workspace_dir") or "").strip()
    if cli_render:
        cli_render.print_banner(ws or "(與安裝目錄相同)")
    else:
        print(
            "\n══════════════════════════════════════════════════════════\n"
            "  HydraBot CLI — 終端機模式\n"
            "══════════════════════════════════════════════════════════\n"
        )

    prompt = cli_render.prompt_line() if cli_render else "HydraBot> "

    try:
        while True:
            try:
                line = input(prompt).strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\n（/quit 結束，或再按一次 Ctrl+C）")
                continue

            if not line:
                continue

            low = line.lower()
            if low in ("/quit", "/exit", "quit", "exit"):
                break
            if low in ("/help", "help", "/?"):
                _print_help()
                continue
            if low == "/reset":
                pool.reset_conversation(CLI_SESSION_ID)
                print("✅ 已清空本終端機會話與 Python 命名空間。\n")
                continue
            if low == "/models":
                print(_models_text(pool))
                continue
            if low == "/tools":
                print(pool.list_tools_info())
                continue

            try:
                reply = pool.chat(CLI_SESSION_ID, line)
                if cli_render:
                    cli_render.print_assistant_block(reply)
                else:
                    print(reply)
                print()
            except KeyboardInterrupt:
                print("\n（已中斷）\n")
            except Exception as e:
                print(f"❌ 錯誤: {e}\n```\n{traceback.format_exc()}\n```\n")

    finally:
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        try:
            pool.shutdown()
        except Exception:
            pass
        dim = "\033[2m" if sys.stdout.isatty() else ""
        rst = "\033[0m" if sys.stdout.isatty() else ""
        print(f"{dim}HydraBot CLI 已結束。{rst}")


def _print_help() -> None:
    print(
        f"\n{'─' * 44}\n"
        "  指令\n"
        f"{'─' * 44}\n"
        "  /help     說明\n"
        "  /reset    清空對話與本機 Python 命名空間\n"
        "  /models   模型池與目前索引\n"
        "  /tools    工具列表\n"
        "  /quit     結束\n"
        f"{'─' * 44}\n"
        "  設定 config.json 的 `cli_compact_ui: false` 可改回舊版工具列印。\n"
    )


def _models_text(pool: "AgentPool") -> str:
    idx = pool.user_model.get(CLI_SESSION_ID, 0)
    lines = [f"模型池（目前索引: {idx}）\n"]
    for i, m in enumerate(pool.model_configs):
        mark = "  ← 目前" if i == idx else ""
        lines.append(
            f"  [{i}] {m.get('name', m['model'])} "
            f"({m['provider']}/{m['model']}){mark}"
        )
    lines.append("\n調整請編輯 config.json 的 `models`。")
    return "\n".join(lines)
