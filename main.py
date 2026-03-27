#!/usr/bin/env python3
"""
HydraBot - Self-expanding AI Assistant via Telegram
"""

import json
import sys
import asyncio
from pathlib import Path


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


def load_config(*, allow_without_messengers: bool = False) -> dict:
    """allow_without_messengers: True 時不強制設定 telegram_token / discord_token（供 CLI 模式使用）。"""
    config_path = Path("config.json")

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
        config_path.write_text(json.dumps(template, indent=2, ensure_ascii=False))
        print("✅ 已建立 config.json")
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


def main():
    # Set working directory to the installation directory (where config.json is)
    # This ensures relative paths in tools work correctly
    script_dir = Path(__file__).parent
    import os
    os.chdir(script_dir)

    # Windows asyncio compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cli_mode = _wants_cli(sys.argv)
    config = load_config(allow_without_messengers=cli_mode)

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
