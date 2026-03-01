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

UNAUTHORIZED_MSG = (
    "⛔ 未授权 / Unauthorized\n\n"
    "你没有使用此 Bot 的权限。\n"
    "如需授权，请联系 Bot 管理员。\n\n"
    "🐍 想自己部署一个？\n"
    "https://github.com/Adaimade/HydraBot"
)


class TelegramBot:
    def __init__(self, config: dict):
        self.config = config
        self.authorized_users: set[int] = set(config.get("authorized_users", []))
        self.app: Application | None = None

        # Sessions currently in the timezone setup flow
        # (awaiting a UTC+N input from the user)
        self._pending_tz: set[tuple] = set()

        from agent import AgentPool
        print("🧠 Initializing agent pool...")
        self.pool = AgentPool(config)
        print(f"✅ {len(self.pool.model_configs)} models configured, "
              f"{len(self.pool.tools) + 1} tools loaded\n")

    # ─────────────────────────────────────────────
    # Session ID
    # ─────────────────────────────────────────────

    def _session_id(self, update: Update) -> tuple:
        """
        Returns (chat_id, thread_id) as the unique session key.

        chat_id   — Telegram chat ID (each private chat or group has its own)
        thread_id — Telegram Topic/Thread ID for supergroups with Topics enabled,
                    None for regular chats and non-topic messages.

        This means:
          · Private chat with bot       → one isolated context per user
          · Group without Topics        → one shared context per group
          · Group with Topics enabled   → one isolated context per Topic
        """
        chat_id = update.effective_chat.id
        thread_id = None
        if update.message and getattr(update.message, "is_topic_message", False):
            thread_id = update.message.message_thread_id
        return (chat_id, thread_id)

    # ─────────────────────────────────────────────
    # Auth
    # ─────────────────────────────────────────────

    def _ok(self, user_id: int) -> bool:
        if not self.authorized_users:
            return True
        return user_id in self.authorized_users

    # ─────────────────────────────────────────────
    # Timezone helpers
    # ─────────────────────────────────────────────

    @staticmethod
    def _parse_tz_input(text: str) -> int | None:
        """
        Parse timezone input from user.
        Accepts: "UTC+8", "UTC-5", "+8", "-5", "8", "0"
        Returns UTC offset as int, or None if invalid.
        Valid range: -12 to +14.
        """
        import re
        text = text.strip().upper()
        m = re.match(r'^(?:UTC)?([+-]?\d+)$', text)
        if m:
            offset = int(m.group(1))
            if -12 <= offset <= 14:
                return offset
        return None

    async def _send_tz_prompt(self, update: Update):
        """Send the timezone setup prompt message."""
        await update.message.reply_text(
            "🌍 **請設定您的時區**\n\n"
            "這讓我能在正確的時間發送定時通知。\n\n"
            "請輸入您的 UTC 偏移量，例如：\n"
            "• `UTC+8`  — 台灣 / 香港 / 中國\n"
            "• `UTC+9`  — 日本 / 韓國\n"
            "• `UTC+7`  — 泰國 / 越南\n"
            "• `UTC+0`  — 英國（冬令）\n"
            "• `UTC-5`  — 美國東部（冬令）\n\n"
            "直接輸入 `UTC+8`、`+8` 或純數字 `8` 均可：",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────
    # Sub-agent result delivery
    # ─────────────────────────────────────────────

    async def _send_to_user(self, session_id: tuple, text: str):
        """Called by background sub-agents to push results back to the originating session."""
        if self.app is None:
            return
        chat_id, thread_id = session_id
        chunks = self._split(text)
        for chunk in chunks:
            kwargs: dict = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            try:
                await self.app.bot.send_message(**kwargs)
            except Exception:
                try:
                    kwargs.pop("parse_mode", None)
                    await self.app.bot.send_message(**kwargs)
                except Exception as e:
                    print(f"⚠️ Failed to deliver sub-agent result to {session_id}: {e}")

    # ─────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            await update.message.reply_text(UNAUTHORIZED_MSG)
            return
        name       = update.effective_user.first_name
        n          = len(self.pool.model_configs)
        session_id = self._session_id(update)

        text = (
            f"👋 你好，{name}！我是 HydraBot 🐍\n\n"
            f"运行在你的机器上，配备 **{n} 组模型** + **{len(self.pool.tools) + 4} 个工具**。\n"
            "可以执行代码、管理文件、并行派出子代理——还能创建新工具来扩展自己！\n\n"
            "**命令**\n"
            "/start — 显示此消息\n"
            "/reset — 清除当前对话历史\n"
            "/tools — 列出可用工具\n"
            "/models — 查看/切换模型\n"
            "/tasks — 查看子代理任务与進度\n"
            "/notify — 查看/管理定時通知排程\n"
            "/timezone — 查看/修改時區設定\n"
            "/status — 系统状态\n\n"
            "⏰ **定時通知**\n"
            "直接告訴我「明天早上 9 點提醒我開會」或「每天通知我查看報告」，\n"
            "我會自動排程並在時間到時推送通知。\n\n"
            "📊 **任務進度**\n"
            "子代理執行長任務時，可即時回報進度，\n"
            "用 /tasks 隨時查看最新狀態。\n\n"
            "💡 **多专案隔离**\n"
            "每个 Telegram 群组 / Topic 拥有完全独立的对话上下文，\n"
            "不同专案请使用不同群组或 Topic，彻底避免代码混淆。\n\n"
            "直接发消息开始对话 →"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

        # First-time timezone setup: prompt if not yet configured
        if self.pool.get_timezone(session_id) is None:
            self._pending_tz.add(session_id)
            await self._send_tz_prompt(update)

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        session_id = self._session_id(update)
        self.pool.reset_conversation(session_id)
        await update.message.reply_text("✅ 当前会话的对话历史已清除")

    async def cmd_tools(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        await self._send(update, self.pool.list_tools_info())

    async def cmd_models(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /models      → list all models
        /model 1     → switch to model 1 (for this session only)
        """
        if not self._ok(update.effective_user.id):
            return
        session_id = self._session_id(update)
        args = context.args

        if args:
            try:
                idx = int(args[0])
                result = self.pool.switch_model(session_id, idx)
                await update.message.reply_text(result, parse_mode="Markdown")
            except ValueError:
                n = len(self.pool.model_configs)
                await update.message.reply_text(
                    f"❌ 请输入数字索引，例如 `/model 1`（范围 0–{n - 1}）",
                    parse_mode="Markdown",
                )
        else:
            await self._send(update, self.pool.list_models_info(session_id))

    async def cmd_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        await self._send(update, self.pool.list_tasks_info())

    async def cmd_notify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /notify             — list all scheduled notifications for this session
        /notify cancel <id> — cancel a scheduled notification
        """
        if not self._ok(update.effective_user.id):
            return
        session_id = self._session_id(update)
        args = context.args

        if args and args[0].lower() == "cancel" and len(args) >= 2:
            job_id = args[1]
            ok = self.pool.scheduler.cancel_job(job_id)
            msg = f"✅ 已取消排程 `{job_id}`" if ok else f"❌ 找不到排程 `{job_id}`"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            tz_offset = self.pool.get_timezone(session_id) or 0
            await self._send(
                update,
                self.pool.scheduler.format_jobs_list(
                    session_id=session_id, tz_offset_hours=tz_offset
                ),
            )

    async def cmd_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /timezone           — show current timezone (or prompt to set if missing)
        /timezone UTC+8     — set timezone for this session
        /timezone +8        — same
        /timezone 8         — same
        """
        if not self._ok(update.effective_user.id):
            return
        session_id = self._session_id(update)
        args = context.args

        if args:
            tz = self._parse_tz_input(" ".join(args))
            if tz is None:
                await update.message.reply_text(
                    "❌ 格式不正確\n"
                    "請使用 `UTC+8`、`+8` 或純數字 `8`（範圍 -12 ~ +14）",
                    parse_mode="Markdown",
                )
                return
            self.pool.set_timezone(session_id, tz)
            self._pending_tz.discard(session_id)
            sign = "+" if tz >= 0 else ""
            await update.message.reply_text(
                f"✅ 時區已設定為 **UTC{sign}{tz}**",
                parse_mode="Markdown",
            )
        else:
            tz = self.pool.get_timezone(session_id)
            if tz is None:
                self._pending_tz.add(session_id)
                await self._send_tz_prompt(update)
            else:
                sign = "+" if tz >= 0 else ""
                await update.message.reply_text(
                    f"🌍 目前時區: **UTC{sign}{tz}**\n"
                    f"修改: `/timezone UTC+8`",
                    parse_mode="Markdown",
                )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update.effective_user.id):
            return
        session_id = self._session_id(update)
        chat_id, thread_id = session_id
        idx = self.pool.user_model.get(session_id, 0)
        m = self.pool.model_configs[idx % len(self.pool.model_configs)]
        running = sum(
            1 for t in self.pool.running_tasks.values() if t["status"] == "running"
        )
        history_len = len(self.pool.conversations.get(session_id, []))

        # Session label
        if thread_id:
            session_label = f"群组 Topic (chat={chat_id}, thread={thread_id})"
        elif chat_id == update.effective_user.id:
            session_label = "私聊"
        else:
            session_label = f"群组 (chat={chat_id})"

        active_notifs = len(self.pool.scheduler.list_jobs(session_id=session_id))
        tz_raw = self.pool.get_timezone(session_id)
        if tz_raw is not None:
            sign   = "+" if tz_raw >= 0 else ""
            tz_str = f"UTC{sign}{tz_raw}"
        else:
            tz_str = "未設定（/timezone 設定）"
        text = (
            "🖥️ **系统状态**\n\n"
            f"Python: `{sys.version.split()[0]}`\n"
            f"平台: `{platform.system()} {platform.release()}`\n"
            f"当前会话: `{session_label}`\n"
            f"时区: `{tz_str}`\n"
            f"对话轮数: `{history_len // 2}` 轮\n"
            f"当前模型: `{m.get('name', m['model'])}` (#{idx})\n"
            f"Provider: `{m['provider']}`\n"
            f"模型组数: `{len(self.pool.model_configs)}`\n"
            f"工具总数: `{len(self.pool.tools) + 4}`\n"
            f"子代理运行中: `{running}`\n"
            f"定時排程: `{active_notifs}` 個"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    # ─────────────────────────────────────────────
    # Message handler
    # ─────────────────────────────────────────────

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._ok(user.id):
            await update.message.reply_text(UNAUTHORIZED_MSG)
            return

        text = update.message.text
        if not text:
            return

        session_id = self._session_id(update)

        # ── Timezone setup flow ────────────────────────────────────
        # If this session is awaiting a timezone input, intercept the message.
        if session_id in self._pending_tz:
            tz = self._parse_tz_input(text)
            if tz is not None:
                self.pool.set_timezone(session_id, tz)
                self._pending_tz.discard(session_id)
                sign = "+" if tz >= 0 else ""
                await update.message.reply_text(
                    f"✅ 時區已設定為 **UTC{sign}{tz}**\n\n"
                    f"現在可以開始對話了，直接發消息即可 →",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "❌ 格式不正確，請輸入如 `UTC+8`、`+8` 或 `8`：",
                    parse_mode="Markdown",
                )
            return
        # ──────────────────────────────────────────────────────────

        typing_task = asyncio.create_task(self._keep_typing(update, context))

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, self.pool.chat, session_id, text
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

    async def _check_updates(self):
        """
        Check for updates from GitHub in background.
        Compares local VERSION with remote VERSION file.
        Does not block startup; failures are silent.
        """
        try:
            import requests
            from pathlib import Path

            # Fetch latest VERSION from GitHub
            url = "https://raw.githubusercontent.com/Adaimade/HydraBot/main/VERSION"
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            latest = response.text.strip()

            # Read local version
            version_file = Path(__file__).parent / "VERSION"
            if version_file.exists():
                current = version_file.read_text().strip()

                # Compare versions
                if latest != current:
                    print(f"\n⚠️  新版本可用！({current} → {latest})")
                    print(f"   运行以下命令更新:")
                    print(f"   hydrabot update\n")
        except Exception:
            # Silently fail - don't interrupt bot startup
            pass

    async def _post_init(self, app: Application):
        """Called once after app is built, before polling starts."""
        self.app = app

        # Wire sub-agent result delivery to this bot instance
        loop = asyncio.get_running_loop()
        self.pool._loop = loop
        self.pool._send_func = self._send_to_user

        # Start the notification scheduler
        self.pool.scheduler.start(loop, self._send_to_user)

        # Check for updates in background (don't wait)
        asyncio.create_task(self._check_updates())

        await app.bot.set_my_commands([
            BotCommand("start",    "显示欢迎消息"),
            BotCommand("reset",    "清除当前会话历史"),
            BotCommand("tools",    "列出可用工具"),
            BotCommand("models",   "查看/切换模型"),
            BotCommand("tasks",    "查看子代理任务与進度"),
            BotCommand("notify",   "查看/管理定時通知排程"),
            BotCommand("timezone", "查看/設定時區 (UTC+N)"),
            BotCommand("status",   "系统状态与会话信息"),
        ])

    def run(self):
        app = (
            Application.builder()
            .token(self.config["telegram_token"])
            .post_init(self._post_init)
            .build()
        )

        # /model and /models both handled by cmd_models
        app.add_handler(CommandHandler("start",    self.cmd_start))
        app.add_handler(CommandHandler("reset",    self.cmd_reset))
        app.add_handler(CommandHandler("tools",    self.cmd_tools))
        app.add_handler(CommandHandler("models",   self.cmd_models))
        app.add_handler(CommandHandler("model",    self.cmd_models))
        app.add_handler(CommandHandler("tasks",    self.cmd_tasks))
        app.add_handler(CommandHandler("notify",   self.cmd_notify))
        app.add_handler(CommandHandler("timezone", self.cmd_timezone))
        app.add_handler(CommandHandler("status",   self.cmd_status))
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
        print(f"   Session : chat_id + thread_id 双维度隔离")
        print(f"   Ctrl+C to stop\n")

        app.run_polling(drop_pending_updates=True)
