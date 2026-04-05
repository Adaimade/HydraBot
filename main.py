#!/usr/bin/env python3
"""
HydraBot - Self-expanding AI Assistant via Telegram
"""

from __future__ import annotations

import json
import os
import sys
import asyncio
from pathlib import Path


def _parse_workspace_argv(argv: list[str]) -> tuple[Path | None, list[str]]:
    """自 argv 移除 --workspace / -w / --workdir，回傳 (絕對路徑或 None, 新 argv)。"""
    workspace: str | None = None
    out: list[str] = [argv[0]] if argv else []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--workspace", "-w", "--workdir") and i + 1 < len(argv):
            workspace = argv[i + 1]
            i += 2
            continue
        if a.startswith("--workspace="):
            workspace = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    ws = Path(workspace).expanduser().resolve() if workspace else None
    return ws, out


# ══════════════════════════════════════════════════════════════
# Check if running in virtual environment
# ══════════════════════════════════════════════════════════════
def _check_venv():
    """Ensure running in virtual environment to access installed dependencies."""
    in_venv = sys.prefix != sys.base_prefix
    if not in_venv:
        try:
            msg = "\n[ERROR] HydraBot must run in a virtual environment!\n\nYou are using system Python which does not have dependencies installed.\n\nPlease start using one of these methods:\n\n1. (Recommended) Use hydrabot launcher:\n   $ hydrabot start\n"
            if sys.platform == "win32":
                msg += "2. Or use venv Python:\n   $ .\\venv\\Scripts\\python.exe main.py\n   or: .\\venv\\Scripts\\Activate.ps1; python main.py\n"
            else:
                msg += "2. Or use venv Python:\n   $ ./venv/bin/python main.py\n   or: source venv/bin/activate; python main.py\n"
            sys.stderr.write(msg)
        except Exception:
            pass
        sys.exit(1)


_check_venv()


def _telegram_configured(config: dict) -> bool:
    t = (config.get("telegram_token") or "").strip()
    return bool(t) and t not in ("YOUR_TELEGRAM_BOT_TOKEN",)


def _discord_configured(config: dict) -> bool:
    t = (config.get("discord_token") or "").strip()
    return bool(t) and "YOUR_DISCORD_BOT_TOKEN" not in t


def load_config(
    config_path: Path,
    *,
    allow_without_messengers: bool = False,
) -> dict:
    """allow_without_messengers: True 時不強制設定 telegram_token / discord_token（供 CLI 模式使用）。"""
    if not config_path.exists():
        template = {
            "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
            "discord_token": "",
            "model_api_key": "YOUR_MODEL_API_KEY",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "base_url": None,
            "authorized_users": [],
            "max_tokens": 4096,
            "max_history": 50,
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ 已建立 {config_path}")
        print("   請填寫您的憑證後重新執行。")
        sys.exit(0)

    # utf-8-sig handles both UTF-8 with BOM (written by Windows PowerShell)
    # and regular UTF-8 — strips the BOM transparently if present
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))

    errors = []

    if not allow_without_messengers:
        if not _telegram_configured(config) and not _discord_configured(config):
            errors.append("請至少設定有效的 telegram_token 或 discord_token（至少一項）")

    # Check model config — support both new (models array) and old (model_api_key) format
    models = config.get("models", [])
    if models:
        # New format: check all models have an api_key
        bad = [
            f"模型 #{i}（{m.get('name', '?')}）缺少 api_key"
            for i, m in enumerate(models)
            if m.get("api_key") in ("", "YOUR_MODEL_API_KEY", "YOUR_GOOGLE_AI_KEY", None)
            and "provider" in m  # skip comment-only entries
        ]
        errors.extend(bad)
    else:
        # Old format fallback
        if config.get("model_api_key") in ("", "YOUR_MODEL_API_KEY", None):
            errors.append("model_api_key 未設定")

    if errors:
        print("❌ config.json 設定有誤，請先填寫：")
        for e in errors:
            print(f"   · {e}")
        print("\n   執行 hydrabot config 或直接編輯 config.json")
        sys.exit(1)

    return config


def _wants_cli(argv: list[str]) -> bool:
    """是否啟動終端機模式：python main.py --cli 或 python main.py -c 或 python main.py cli"""
    rest = argv[1:]
    return "--cli" in rest or "-c" in rest or (len(rest) >= 1 and rest[0] == "cli")


def _extract_prompt(argv: list[str]) -> str | None:
    """取 --prompt / -p 後的參數；回傳 None 代表不是非互動模式。"""
    rest = argv[1:]
    for i, a in enumerate(rest):
        if a in ("--prompt", "-p") and i + 1 < len(rest):
            return rest[i + 1]
        if a.startswith("--prompt="):
            return a.split("=", 1)[1]
    return None


def main():
    install_dir = Path(__file__).resolve().parent

    ws_arg, argv_clean = _parse_workspace_argv(sys.argv)
    sys.argv = argv_clean

    # Windows asyncio compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cli_mode = _wants_cli(sys.argv)
    prompt_once = _extract_prompt(sys.argv)
    dry_run = "--dry-run" in sys.argv

    env_ws = (os.environ.get("HYDRABOT_WORKSPACE") or "").strip()
    if ws_arg is not None:
        workspace_dir = ws_arg
    elif env_ws:
        workspace_dir = Path(env_ws).expanduser().resolve()
    else:
        # 與 Claude Code CLI 類似：預設使用「啟動時的當前目錄」（hydrabot 啟動器會先還原呼叫時的 pwd）
        workspace_dir = Path.cwd().resolve()

    if not workspace_dir.is_dir():
        print(f"❌ 工作目錄不存在或不是目錄: {workspace_dir}")
        sys.exit(1)

    config_path = install_dir / "config.json"
    config = load_config(config_path, allow_without_messengers=(cli_mode or prompt_once is not None))
    config["_hydrabot_install_dir"] = str(install_dir)
    config["_hydrabot_workspace_dir"] = str(workspace_dir)
    if dry_run:
        config["dry_run"] = True

    os.chdir(workspace_dir)
    if workspace_dir != install_dir.resolve():
        print(f"📂 工作區（檔案／shell／Python 相對路徑）: {workspace_dir}")
        print(f"📦 HydraBot 安裝與 config: {install_dir}\n")

    if prompt_once is not None:
        from cli import run_prompt
        run_prompt(config, prompt_once)
        return

    if cli_mode:
        from cli import run_cli

        run_cli(config)
        return
    tg = _telegram_configured(config)
    dc = _discord_configured(config)

    if dc and not tg:
        try:
            import discord  # noqa: F401
        except ImportError:
            print("❌ 已設定 discord_token 但未安裝 discord.py")
            print("   請執行: pip install -r requirements.txt")
            sys.exit(1)
        print("🐍 HydraBot 啟動中（僅 Discord）...")
        from discord_bot import HydraDiscordClient

        HydraDiscordClient(config).run((config.get("discord_token") or "").strip())
        return

    if dc and tg:
        try:
            import discord  # noqa: F401
        except ImportError:
            print("❌ 已設定 discord_token 但未安裝 discord.py")
            print("   請執行: pip install -r requirements.txt")
            sys.exit(1)
        from discord_bot import run_discord_bot_thread

        print("🐍 HydraBot 啟動中（Telegram + Discord）...")
        run_discord_bot_thread(config)
    else:
        print("🐍 HydraBot 啟動中...")

    from bot import TelegramBot

    TelegramBot(config).run()


if __name__ == "__main__":
    main()
