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


def load_config() -> dict:
    config_path = Path("config.json")

    if not config_path.exists():
        template = {
            "telegram_token": "YOUR_TELEGRAM_BOT_TOKEN",
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

    # Check Telegram token
    if config.get("telegram_token") in ("", "YOUR_TELEGRAM_BOT_TOKEN", None):
        errors.append("telegram_token 未設定")

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
        print("\n   執行 hydrabot.bat config 或直接編輯 config.json")
        sys.exit(1)

    return config


def main():
    # Windows asyncio compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print("🐍 HydraBot 啟動中...")

    config = load_config()

    from bot import TelegramBot
    bot = TelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()
