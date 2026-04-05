#!/usr/bin/env python3
"""
HydraBot — 終端機互動模式（CLI）

與 AgentPool 直接對話，無需 Telegram / Discord。
輸出經 cli_render 精簡（階層、摺疊長輸出），風格對齊 Claude Code CLI。
"""

from __future__ import annotations

import asyncio
import re
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

    def _cli_approve(tool_name: str, inputs: dict) -> bool:
        """default 權限模式下，寫入工具執行前問使用者 Y/n。"""
        import json as _j
        summary = _j.dumps(inputs, ensure_ascii=False)
        if len(summary) > 200:
            summary = summary[:197] + "…"
        dim = "\033[2m" if sys.stdout.isatty() else ""
        bold = "\033[1m" if sys.stdout.isatty() else ""
        yellow = "\033[33m" if sys.stdout.isatty() else ""
        rst = "\033[0m" if sys.stdout.isatty() else ""
        print(f"\n{yellow}⚠  權限確認{rst}：{bold}{tool_name}{rst}")
        print(f"{dim}   {summary}{rst}")
        try:
            ans = input(f"   允許執行？[Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return ans in ("", "y", "yes")

    pool._cli_approval_callback = _cli_approve

    _stream_started = [False]

    def _stream_cb(chunk):
        """Streaming callback：chunk=str 印文字，chunk=None 表示結束。"""
        if chunk is None:
            if _stream_started[0]:
                print(flush=True)
            _stream_started[0] = False
            return
        if not _stream_started[0]:
            if cli_render:
                cli_render.print_assistant_header()
            _stream_started[0] = True
        print(chunk, end="", flush=True)

    pool._stream_callback = _stream_cb
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

    # 自動恢復上次會話
    if pool.load_session(CLI_SESSION_ID):
        n = len(pool.conversations.get(CLI_SESSION_ID, []))
        dim = "\033[2m" if sys.stdout.isatty() else ""
        rst = "\033[0m" if sys.stdout.isatty() else ""
        print(f"{dim}  ↻ 已自動恢復上次會話（{n} 條訊息）· /reset 可清除{rst}\n")

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
            stripped = line.strip()
            if re.match(r"^/(?:model|models)\s*$", stripped, re.I):
                print(pool.list_models_info(CLI_SESSION_ID))
                print()
                continue
            m_mod = re.match(r"^/(?:model|models)\s+(\S+)\s*$", stripped, re.I)
            if m_mod:
                arg = m_mod.group(1)
                try:
                    idx = int(arg)
                    print(pool.switch_model(CLI_SESSION_ID, idx))
                except ValueError:
                    n = len(pool.model_configs)
                    print(f"❌ 請輸入數字索引，例如 `/model 1`（範圍 0–{n - 1}）")
                print()
                continue
            if low == "/tools":
                print(pool.list_tools_info())
                continue
            if low == "/save":
                pool.save_session(CLI_SESSION_ID)
                print("✅ 會話已儲存。下次用 /resume 恢復。\n")
                continue
            if low == "/resume":
                ok = pool.load_session(CLI_SESSION_ID)
                if ok:
                    n = len(pool.conversations.get(CLI_SESSION_ID, []))
                    print(f"✅ 已恢復會話（{n} 條訊息）。\n")
                else:
                    print("ℹ️ 沒有找到已儲存的會話。\n")
                continue
            if low == "/usage":
                su = pool.get_token_usage(CLI_SESSION_ID)
                gl = pool.get_token_usage()
                print(f"\n  本次會話  ↑{su['prompt_tokens']:,} ↓{su['completion_tokens']:,} tokens · {su['api_calls']} calls")
                print(f"  全域累計  ↑{gl['prompt_tokens']:,} ↓{gl['completion_tokens']:,} tokens · {gl['api_calls']} calls\n")
                continue

            try:
                _stream_started[0] = False
                reply = pool.chat(CLI_SESSION_ID, line)
                if _stream_started[0]:
                    if cli_render:
                        cli_render.print_assistant_footer()
                elif cli_render:
                    cli_render.print_assistant_block(reply)
                else:
                    print(reply)
                # Token 統計
                su = pool.get_token_usage(CLI_SESSION_ID)
                if su.get("api_calls", 0) > 0:
                    _dim = "\033[2m" if sys.stdout.isatty() else ""
                    _rst = "\033[0m" if sys.stdout.isatty() else ""
                    _p = su["prompt_tokens"]
                    _c = su["completion_tokens"]
                    def _fmt(n: int) -> str:
                        if n >= 1_000_000:
                            return f"{n / 1_000_000:.1f}M"
                        if n >= 1_000:
                            return f"{n / 1_000:.1f}k"
                        return str(n)
                    print(f"{_dim}  [↑{_fmt(_p)} ↓{_fmt(_c)} tokens · {su['api_calls']} calls]{_rst}")
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
        "  /models      列出模型；/model N 切換（僅本終端機會話）\n"
        "  /save        儲存當前會話\n"
        "  /resume      恢復上次儲存的會話\n"
        "  /usage       查看本次會話與全域 token 用量\n"
        "  /tools    工具列表\n"
        "  /quit     結束\n"
        f"{'─' * 44}\n"
        "  設定 config.json 的 `cli_compact_ui: false` 可改回舊版工具列印。\n"
    )


def run_prompt(config: dict, prompt: str) -> None:
    """非互動模式：執行一次對話後退出（hydrabot run "..." 或 main.py --prompt "..."）。"""
    from agent import AgentPool

    pool: AgentPool = AgentPool(config)
    loop = asyncio.new_event_loop()

    def _loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_loop_runner, name="hydra-prompt-async", daemon=True).start()

    async def noop_send(session_id: tuple, text: str) -> None:
        pass

    pool._loop = loop
    pool._send_func = noop_send

    try:
        reply = pool.chat(CLI_SESSION_ID, prompt)
        print(reply)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        try:
            pool.shutdown()
        except Exception:
            pass
