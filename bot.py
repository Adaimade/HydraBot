#!/usr/bin/env python3
"""
Telegram bot interface for HydraBot.
"""

import asyncio
import logging
import platform
import sys
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

MAX_MSG = 4096


class TelegramBot:
    def __init__(self, config: dict):
        self.config = config
        self.authorized_users: set[int] = set(config.get("authorized_users", []))
        self.app: Application | None = None

        from agent import AgentPool
        print("🧠 Initializing agent pool...")
        self.pool = AgentPool(config)
        print(f"✅ {len(self.pool.model_configs)} models configured, "
              f"{len(self.pool.tools) + 1} tools loaded\n")

    # ─────────────────────────────────────────────
    # Auth
    # ─────────────────────────────────────────────

    def _ok(self, user_id: int) -> bool:
        if not self.authorized_users:
            return True
        return user_id in self.authorized_users

    # ─────────────────────────────────────────────
    # Sub-agent result delivery
    # ─────────────────────────────────────────────

    async def _send_to_user(self, user_id: int, text: str):
        """Called by background sub-agents to push results."""
        if self.app is None:
            return
        chunks = self._split(text)
        for chunk in chunks:
            try:
                await self.app.bot.send_message(
                    chat_id=user_id, text=chunk, parse_mode="Markdown"
                )
            except Exception:
                try:
                    await self.app.bot.send_message(chat_id=user_id, text=chunk)
                except Exception as e:
                    print(f"⚠️ Failed to deliver sub-agent result to {user_id}: {e}")

    # ─────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            await update.message.reply_text("⛔ 未授权")
            return
        name = update.effective_user.first_name
        n = len(self.pool.model_configs)
        text = (
            f"👋 你好，{name}！我是 HydraBot 🐍\n\n"
            f"运行在你的机器上，配备 **{n} 组模型** + **{len(self.pool.tools) + 1} 个工具**。\n"
            "可以执行代码、管理文件、并行派出子代理——还能创建新工具来扩展自己！\n\n"
            "**命令**\n"
            "/start — 显示此消息\n"
            "/reset — 清除对话历史\n"
            "/tools — 列出可用工具\n"
            "/models — 查看/切换模型\n"
            "/tasks — 查看子代理任务\n"
            "/status — 系统状态\n\n"
            "直接发消息开始对话 →"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        self.pool.reset_conversation(update.effective_user.id)
        await update.message.reply_text("✅ 对话历史已清除")

    async def cmd_tools(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        await self._send(update, self.pool.list_tools_info())

    async def cmd_models(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /models      → list all models
        /model 1     → switch to model 1
        """
        if not self._ok(update.effective_user.id):
            return
        user_id = update.effective_user.id
        args = context.args

        if args:
            try:
                idx = int(args[0])
                result = self.pool.switch_model(user_id, idx)
                await update.message.reply_text(result, parse_mode="Markdown")
            except ValueError:
                n = len(self.pool.model_configs)
                await update.message.reply_text(
                    f"❌ 请输入数字索引，例如 `/model 1`（范围 0–{n - 1}）",
                    parse_mode="Markdown",
                )
        else:
            await self._send(update, self.pool.list_models_info(user_id))

    async def cmd_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        await self._send(update, self.pool.list_tasks_info())

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        user_id = update.effective_user.id
        idx = self.pool.user_model.get(user_id, 0)
        m = self.pool.model_configs[idx % len(self.pool.model_configs)]
        running = sum(
            1 for t in self.pool.running_tasks.values() if t["status"] == "running"
        )
        text = (
            "🖥️ **系统状态**\n\n"
            f"Python: `{sys.version.split()[0]}`\n"
            f"平台: `{platform.system()} {platform.release()}`\n"
            f"当前模型: `{m.get('name', m['model'])}` (模型 {idx})\n"
            f"Provider: `{m['provider']}`\n"
            f"模型组数: `{len(self.pool.model_configs)}`\n"
            f"工具总数: `{len(self.pool.tools) + 1}`\n"
            f"子代理运行中: `{running}`"
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

        typing_task = asyncio.create_task(self._keep_typing(update, context))

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, self.pool.chat, user.id, text
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
                    chat_id=update.effective_chat.id, action="typing"
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    # ─────────────────────────────────────────────
    # Message sending helpers
    # ─────────────────────────────────────────────

    async def _send(self, update: Update, text: str):
        if not text:
            return
        for i, chunk in enumerate(self._split(text)):
            if i > 0:
                await asyncio.sleep(0.3)
            await self._try_send(update, chunk)

    def _split(self, text: str) -> list[str]:
        if len(text) <= MAX_MSG:
            return [text]
        chunks, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > MAX_MSG:
                if current:
                    chunks.append(current)
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
    # Startup
    # ─────────────────────────────────────────────

    async def _post_init(self, app: Application):
        """Called once after app is built, before polling starts."""
        self.app = app

        # Wire sub-agent result delivery to this bot instance
        self.pool._loop = asyncio.get_running_loop()
        self.pool._send_func = self._send_to_user

        await app.bot.set_my_commands([
            BotCommand("start",  "显示欢迎消息"),
            BotCommand("reset",  "清除对话历史"),
            BotCommand("tools",  "列出可用工具"),
            BotCommand("models", "查看/切换模型"),
            BotCommand("tasks",  "查看子代理任务"),
            BotCommand("status", "系统状态"),
        ])

    def run(self):
        app = (
            Application.builder()
            .token(self.config["telegram_token"])
            .post_init(self._post_init)
            .build()
        )

        # /model and /models both handled by cmd_models
        app.add_handler(CommandHandler("start",  self.cmd_start))
        app.add_handler(CommandHandler("reset",  self.cmd_reset))
        app.add_handler(CommandHandler("tools",  self.cmd_tools))
        app.add_handler(CommandHandler("models", self.cmd_models))
        app.add_handler(CommandHandler("model",  self.cmd_models))
        app.add_handler(CommandHandler("tasks",  self.cmd_tasks))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        auth_info = (
            f"{len(self.authorized_users)} 个授权用户"
            if self.authorized_users else "所有人（无限制）"
        )
        print(f"🐍 HydraBot running!")
        print(f"   Models  : {len(self.pool.model_configs)} 组")
        print(f"   Tools   : {len(self.pool.tools) + 1} 个")
        print(f"   Access  : {auth_info}")
        print(f"   Ctrl+C to stop\n")

        app.run_polling(drop_pending_updates=True)
