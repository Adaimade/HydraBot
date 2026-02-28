#!/usr/bin/env python3
"""
Telegram bot interface for HydraBot.
"""

import asyncio
import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

MAX_MSG = 4096  # Telegram message length limit


class TelegramBot:
    def __init__(self, config: dict):
        self.config = config
        self.authorized_users: set[int] = set(config.get("authorized_users", []))

        from agent import Agent
        print("🧠 Initializing agent...")
        self.agent = Agent(config)
        print("✅ Agent ready\n")

    # ─────────────────────────────────────────────
    # Auth
    # ─────────────────────────────────────────────

    def _ok(self, user_id: int) -> bool:
        """Return True if user is authorized."""
        if not self.authorized_users:
            return True
        return user_id in self.authorized_users

    # ─────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            await update.message.reply_text("⛔ 未授权")
            return

        name = update.effective_user.first_name
        text = (
            f"👋 你好，{name}！我是 HydraBot 🐍\n\n"
            "我运行在你的机器上，可以执行代码、管理文件、安装包，还能创建新工具来自我扩展！\n\n"
            "**命令**\n"
            "/start — 显示此消息\n"
            "/reset — 清除对话历史\n"
            "/tools — 列出可用工具\n"
            "/status — 系统状态\n\n"
            "直接发消息开始对话 →"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        self.agent.reset_conversation(update.effective_user.id)
        await update.message.reply_text("✅ 对话历史已清除")

    async def cmd_tools(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        await self._send(update, self.agent.list_tools_info())

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        import platform, sys
        text = (
            "🖥️ **系统状态**\n\n"
            f"Python: `{sys.version.split()[0]}`\n"
            f"平台: `{platform.system()} {platform.release()}`\n"
            f"Provider: `{self.agent.provider}`\n"
            f"模型: `{self.agent.model}`\n"
            f"工具数: `{len(self.agent.tools)}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    # ─────────────────────────────────────────────
    # Message handler
    # ─────────────────────────────────────────────

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._ok(user.id):
            await update.message.reply_text("⛔ 未授权")
            return

        text = update.message.text
        if not text:
            return

        # Continuous typing indicator while agent runs
        typing_task = asyncio.create_task(self._keep_typing(update, context))

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, self.agent.chat, user.id, text
            )
        except Exception as e:
            response = f"❌ 内部错误: {e}"
        finally:
            typing_task.cancel()

        await self._send(update, response)

    async def _keep_typing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            while True:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action="typing",
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    # ─────────────────────────────────────────────
    # Message sending helpers
    # ─────────────────────────────────────────────

    async def _send(self, update: Update, text: str):
        """Split and send text, respecting Telegram's 4096-char limit."""
        if not text:
            return

        chunks = self._split(text)
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(0.3)
            await self._try_send(update, chunk)

    def _split(self, text: str) -> list[str]:
        if len(text) <= MAX_MSG:
            return [text]

        chunks = []
        current = ""

        for line in text.split("\n"):
            if len(current) + len(line) + 1 > MAX_MSG:
                if current:
                    chunks.append(current)
                # If a single line exceeds limit, hard-split it
                while len(line) > MAX_MSG:
                    chunks.append(line[:MAX_MSG])
                    line = line[MAX_MSG:]
                current = line
            else:
                current = (current + "\n" + line) if current else line

        if current:
            chunks.append(current)

        return chunks

    async def _try_send(self, update: Update, text: str):
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            try:
                await update.message.reply_text(text)
            except Exception as e:
                await update.message.reply_text(f"[消息发送失败: {str(e)[:80]}]")

    # ─────────────────────────────────────────────
    # Start bot
    # ─────────────────────────────────────────────

    async def _post_init(self, app: Application):
        await app.bot.set_my_commands([
            BotCommand("start",  "显示欢迎消息"),
            BotCommand("reset",  "清除对话历史"),
            BotCommand("tools",  "列出可用工具"),
            BotCommand("status", "查看系统状态"),
        ])

    def run(self):
        app = (
            Application.builder()
            .token(self.config["telegram_token"])
            .post_init(self._post_init)
            .build()
        )

        app.add_handler(CommandHandler("start",  self.cmd_start))
        app.add_handler(CommandHandler("reset",  self.cmd_reset))
        app.add_handler(CommandHandler("tools",  self.cmd_tools))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        auth_info = f"{len(self.authorized_users)} 个授权用户" if self.authorized_users else "所有人（无限制）"
        print(f"🐍 HydraBot running!")
        print(f"   Model   : {self.config.get('model_name')} ({self.config.get('model_provider')})")
        print(f"   Access  : {auth_info}")
        print(f"   Tools   : {len(self.agent.tools)}")
        print(f"   Ctrl+C to stop\n")

        app.run_polling(drop_pending_updates=True)
