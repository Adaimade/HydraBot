#!/usr/bin/env python3
"""
HydraBot - Self-expanding AI Assistant via Telegram
"""

import json
import sys
import asyncio
from pathlib import Path


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
        print("✅ Created config.json")
        print("   Please fill in your credentials and run again.")
        sys.exit(0)

    config = json.loads(config_path.read_text(encoding="utf-8"))

    errors = []
    if config.get("telegram_token") in ("", "YOUR_TELEGRAM_BOT_TOKEN", None):
        errors.append("telegram_token not set")
    if config.get("model_api_key") in ("", "YOUR_MODEL_API_KEY", None):
        errors.append("model_api_key not set")

    if errors:
        print("❌ Config errors in config.json:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)

    return config


def main():
    # Windows asyncio compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print("🐍 HydraBot starting...")

    config = load_config()

    from bot import TelegramBot
    bot = TelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()
