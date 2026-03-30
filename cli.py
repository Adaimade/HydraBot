#!/usr/bin/env python3
"""
HydraBot — 終端機互動模式（CLI）

與 AgentPool 直接對話，無需 Telegram / Discord。
資料檔：memory.json、experience_log.json 等與專案目錄相同（session 固定為 CLI）。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import AgentPool

# 固定會話鍵：與 Telegram (chat_id, thread_id) 格式一致
CLI_SESSION_ID = (0, None)


def run_cli(config: dict) -> None:
    """啟動 REPL，直到使用者輸入 /quit 或 EOF。"""
    print("🧠 初始化 Agent Pool...")
    from agent import AgentPool

    pool: AgentPool = AgentPool(config)

    loop = asyncio.new_event_loop()

    def _loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_loop_runner, name="hydra-cli-async", daemon=True).start()

    async def cli_send(session_id: tuple, text: str) -> None:
        print(f"\n[推送]\n{text}\n")

    pool._loop = loop
    pool._send_func = cli_send
    pool.scheduler.start(
        loop,
        cli_send,
        task_runner=lambda sid, text: pool.chat(sid, text),
    )

    print(
        "\n"
        "══════════════════════════════════════════════════════════\n"
        "  HydraBot CLI — 終端機模式\n"
        "══════════════════════════════════════════════════════════\n"
        "  直接輸入文字即可與模型對話（繁體中文）。\n"
        "  指令：/help 說明  ·  /reset 清空本輪對話  ·  /models 模型列表\n"
        "        /tools 工具列表  ·  /quit 或 /exit 結束\n"
        "══════════════════════════════════════════════════════════\n"
    )

    try:
        while True:
            try:
                line = input("HydraBot> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\n（使用 /quit 結束，或再按一次 Ctrl+C）")
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
        print("HydraBot CLI 已結束。")


def _print_help() -> None:
    print(
        "指令說明：\n"
        "  /help     顯示此說明\n"
        "  /reset    清空對話歷史與本機 Python 執行環境\n"
        "  /models   列出模型池與目前使用的模型\n"
        "  /tools    列出可用工具\n"
        "  /quit     結束程式\n"
    )


def _models_text(pool: "AgentPool") -> str:
    idx = pool.user_model.get(CLI_SESSION_ID, 0)
    lines = [f"📋 **模型池**（目前索引: {idx}）\n"]
    for i, m in enumerate(pool.model_configs):
        mark = " ← 目前" if i == idx else ""
        lines.append(
            f"  [{i}] **{m.get('name', m['model'])}** "
            f"({m['provider']}/{m['model']}){mark}"
        )
    lines.append("\n在 config.json 的 `models` 調整列表；程式內切換可之後再加指令。")
    return "\n".join(lines)
