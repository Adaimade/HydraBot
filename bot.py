#!/usr/bin/env python3
"""
Telegram bot interface for HydraBot.
"""

import asyncio
import json
import logging
import platform
import re
import sys
from pathlib import Path
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
    "⛔ 未授權 / Unauthorized\n\n"
    "你沒有使用此 Bot 的權限。\n"
    "如需授權，請聯繫 Bot 管理員。\n\n"
    "🐍 想自己部署一個？\n"
    "https://github.com/Adaimade/HydraBot"
)


# ── Wizard state keys ─────────────────────────────────────────────────────────
_WZ_NEW_NAME  = "new_agent_name"   # awaiting folder/project name
_WZ_NEW_TOKEN = "new_agent_token"  # awaiting Telegram bot token
_WZ_DEL_SEL   = "del_agent_sel"   # awaiting which agent to delete (multiple)
_WZ_DEL_CONF  = "del_agent_conf"  # awaiting yes/no confirmation
_WZ_DEL_BURY  = "del_agent_bury"  # awaiting yes/no for graveyard

GRAVEYARD_URL = "https://digital-graveyard.zeabur.app/"


class TelegramBot:
    def __init__(self, config: dict):
        self.config = config
        self.authorized_users: set[int] = set(config.get("authorized_users", []))
        self.app: Application | None = None

        # Sessions currently in the timezone setup flow
        # (awaiting a UTC+N input from the user)
        self._pending_tz: set[tuple] = set()

        # Multi-step wizard state per session
        # {session_id: {"state": str, "data": dict}}
        self._wizard: dict[tuple, dict] = {}

        # Sub-agent bot manager (disabled for sub-agent instances themselves)
        if not config.get("is_sub_agent", False):
            from sub_agent_manager import SubAgentManager
            self.sub_agents: SubAgentManager | None = SubAgentManager(
                str(Path(__file__).parent)
            )
        else:
            self.sub_agents = None

        from agent import AgentPool
        print("🧠 初始化 Agent Pool...")
        self.pool = AgentPool(config)
        print(f"✅ 已設定 {len(self.pool.model_configs)} 組模型，"
              f"已載入 {len(self.pool.tools) + 1} 個工具\n")

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

    def _save_whitelist(self):
        """Persist authorized_users back to config.json (CWD-relative)."""
        config_path = Path("config.json")
        try:
            data = json.loads(config_path.read_text(encoding="utf-8-sig"))
            data["authorized_users"] = sorted(self.authorized_users)
            config_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"⚠️ Failed to save whitelist to config.json: {e}")

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
        name       = re.sub(r'([*_`\[\]])', r'\\\1', update.effective_user.first_name or "")
        n          = len(self.pool.model_configs)
        session_id = self._session_id(update)

        agent_cmds = (
            "/new_agent — 建立獨立子代理 Bot\n"
            "/list_agents — 查看所有子代理\n"
            "/delete_agent — 刪除子代理\n"
        ) if self.sub_agents is not None else ""

        uid = update.effective_user.id
        text = (
            f"👋 你好，{name}！我是 HydraBot 🐍\n\n"
            f"運行在你的機器上，配備 **{n} 組模型** + **{len(self.pool.tools) + 4} 個工具**。\n"
            "可以執行程式碼、管理檔案、派出背景任務——還能建立新工具來擴展自己！\n\n"
            f"🪪 你的 Telegram ID: `{uid}`\n\n"
            "**一般指令**\n"
            "/start — 顯示此訊息\n"
            "/reset — 清除目前對話記錄\n"
            "/tools — 列出可用工具\n"
            "/models — 查看／切換模型\n"
            "/tasks — 查看背景任務與進度\n"
            "/notify — 查看／管理定時通知排程\n"
            "/timezone — 查看／修改時區設定\n"
            "/soul — 查看／清除 Bot 人設\n"
            "/whitelist — 管理授權用戶白名單\n"
            "/status — 系統狀態\n\n"
            + (f"**子代理 Bot 管理**\n{agent_cmds}\n" if agent_cmds else "")
            + "⏰ **定時通知**\n"
            "直接告訴我「明天早上 9 點提醒我開會」或「每天通知我查看報告」，\n"
            "我會自動排程並在時間到時推送通知。\n\n"
            "📊 **任務進度**\n"
            "背景任務執行時，可即時回報進度，\n"
            "用 /tasks 隨時查看最新狀態。\n\n"
            "直接發訊息開始對話 →"
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
        await update.message.reply_text("✅ 目前會話的對話記錄已清除")

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
                    f"❌ 請輸入數字索引，例如 `/model 1`（範圍 0–{n - 1}）",
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

    async def cmd_soul(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /soul        — 顯示目前人設（SOUL.md）
        /soul clear  — 清除人設
        """
        if not self._ok(update.effective_user.id):
            return
        from pathlib import Path
        soul_file = Path(__file__).parent / "SOUL.md"
        args = context.args

        if args and args[0].lower() == "clear":
            if soul_file.exists():
                soul_file.unlink()
                await update.message.reply_text("✅ 人設已清除（SOUL.md 已刪除）")
            else:
                await update.message.reply_text("📝 目前沒有人設可清除")
            return

        if not soul_file.exists():
            await update.message.reply_text(
                "📝 **SOUL.md 尚未設定**\n\n"
                "你可以直接告訴我你想要的人設風格，例如：\n"
                "「幫我設定人設：你是一隻傲嬌的貓娘，說話帶點嬌氣...」\n\n"
                "或手動編輯 `SOUL.md` 放在安裝目錄中。\n"
                "修改後立即生效，無需重啟。",
                parse_mode="Markdown",
            )
            return

        content = soul_file.read_text(encoding="utf-8").strip()
        if not content:
            await update.message.reply_text("📝 SOUL.md 存在但內容為空")
            return

        await self._send(update, f"📝 **目前人設 (SOUL.md)**\n\n{content}")

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
            session_label = f"群組 Topic (chat={chat_id}, thread={thread_id})"
        elif chat_id == update.effective_user.id:
            session_label = "私訊"
        else:
            session_label = f"群組 (chat={chat_id})"

        active_notifs = len(self.pool.scheduler.list_jobs(session_id=session_id))
        tz_raw = self.pool.get_timezone(session_id)
        if tz_raw is not None:
            sign   = "+" if tz_raw >= 0 else ""
            tz_str = f"UTC{sign}{tz_raw}"
        else:
            tz_str = "未設定（請用 /timezone 設定）"
        text = (
            "🖥️ **系統狀態**\n\n"
            f"Python: `{sys.version.split()[0]}`\n"
            f"平台: `{platform.system()} {platform.release()}`\n"
            f"目前會話: `{session_label}`\n"
            f"時區: `{tz_str}`\n"
            f"對話輪數: `{history_len // 2}` 輪\n"
            f"目前模型: `{m.get('name', m['model'])}` (#{idx})\n"
            f"Provider: `{m['provider']}`\n"
            f"模型組數: `{len(self.pool.model_configs)}`\n"
            f"工具總數: `{len(self.pool.tools) + 4}`\n"
            f"子代理執行中: `{running}`\n"
            f"定時排程: `{active_notifs}` 個"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /whitelist              — show authorized users
        /whitelist add <id>     — add user to whitelist
        /whitelist remove <id>  — remove user from whitelist
        """
        if not self._ok(update.effective_user.id):
            return

        args = context.args

        if not args:
            if not self.authorized_users:
                await update.message.reply_text(
                    "🔓 **白名單為空** — 目前所有人均可使用此 Bot\n\n"
                    "新增第一位授權用戶後，未授權用戶將無法使用。\n\n"
                    "新增用戶: `/whitelist add <user_id>`\n"
                    "💡 用戶可用 `/start` 查看自己的 ID，或透過 @userinfobot 取得。",
                    parse_mode="Markdown",
                )
            else:
                ids = "\n".join(f"• `{uid}`" for uid in sorted(self.authorized_users))
                await update.message.reply_text(
                    f"👥 **授權用戶白名單** ({len(self.authorized_users)} 人)\n\n"
                    f"{ids}\n\n"
                    f"新增: `/whitelist add <user_id>`\n"
                    f"移除: `/whitelist remove <user_id>`",
                    parse_mode="Markdown",
                )
            return

        sub = args[0].lower()

        if sub in ("add", "remove") and len(args) >= 2:
            try:
                uid = int(args[1])
            except ValueError:
                await update.message.reply_text(
                    "❌ 用戶 ID 必須是數字，例如 `/whitelist add 123456789`",
                    parse_mode="Markdown",
                )
                return

            if sub == "add":
                if uid in self.authorized_users:
                    await update.message.reply_text(
                        f"⚠️ 用戶 `{uid}` 已在白名單中", parse_mode="Markdown"
                    )
                    return
                self.authorized_users.add(uid)
                self._save_whitelist()
                await update.message.reply_text(
                    f"✅ 已新增用戶 `{uid}` 到白名單\n"
                    f"白名單現有 {len(self.authorized_users)} 人",
                    parse_mode="Markdown",
                )
            else:  # remove
                if uid not in self.authorized_users:
                    await update.message.reply_text(
                        f"❌ 用戶 `{uid}` 不在白名單中", parse_mode="Markdown"
                    )
                    return
                self.authorized_users.discard(uid)
                self._save_whitelist()
                if self.authorized_users:
                    await update.message.reply_text(
                        f"✅ 已從白名單移除用戶 `{uid}`\n"
                        f"白名單現有 {len(self.authorized_users)} 人",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        f"✅ 已從白名單移除用戶 `{uid}`\n\n"
                        f"⚠️ 白名單現在為空，**所有人均可使用此 Bot**。",
                        parse_mode="Markdown",
                    )
        else:
            await update.message.reply_text(
                "**白名單管理指令**\n\n"
                "`/whitelist`              — 查看當前白名單\n"
                "`/whitelist add <id>`     — 新增授權用戶\n"
                "`/whitelist remove <id>`  — 移除授權用戶\n\n"
                "💡 用戶可傳送 `/start` 查看自己的 Telegram ID，"
                "或使用 @userinfobot 取得 ID。",
                parse_mode="Markdown",
            )

    # ─────────────────────────────────────────────
    # Sub-agent bot management commands
    # ─────────────────────────────────────────────

    async def cmd_new_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/new_agent — start the sub-agent creation wizard."""
        if not self._ok(update.effective_user.id):
            return
        if self.sub_agents is None:
            await update.message.reply_text("⛔ 子代理 Bot 無法建立子代理（防止遞迴）")
            return

        session_id = self._session_id(update)
        self._wizard[session_id] = {"state": _WZ_NEW_NAME, "data": {}}
        await update.message.reply_text(
            "🤖 **建立子代理 Bot**\n\n"
            "**第一步：** 請輸入子代理的專案名稱。\n"
            "名稱將作為專案資料夾名稱，只能包含 **英文字母、數字、`-`、`_`**，"
            "且必須以字母或數字開頭。\n\n"
            "例如：`my-project`、`data_analyzer`、`reportbot`\n\n"
            "輸入 `cancel` 可隨時取消：",
            parse_mode="Markdown",
        )

    async def cmd_list_agents(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/list_agents — show all registered sub-agent bots."""
        if not self._ok(update.effective_user.id):
            return
        if self.sub_agents is None:
            await update.message.reply_text("⛔ 子代理管理功能不可用")
            return
        await self._send(update, self.sub_agents.status_text())

    async def cmd_delete_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/delete_agent [name] — start the deletion wizard."""
        if not self._ok(update.effective_user.id):
            return
        if self.sub_agents is None:
            await update.message.reply_text("⛔ 子代理管理功能不可用")
            return

        session_id = self._session_id(update)
        agents = self.sub_agents.names()

        if not agents:
            await update.message.reply_text("📋 目前沒有任何子代理 Bot 可刪除")
            return

        # If name provided as argument, skip selection step
        if context.args:
            target = context.args[0]
            if self.sub_agents.get(target) is None:
                names_list = "、".join(f"`{n}`" for n in agents)
                await update.message.reply_text(
                    f"❌ 找不到子代理 `{target}`\n\n現有：{names_list}",
                    parse_mode="Markdown",
                )
                return
            await self._start_del_confirm(update, session_id, target)
            return

        # Single agent: skip to confirm
        if len(agents) == 1:
            await self._start_del_confirm(update, session_id, agents[0])
            return

        # Multiple agents: ask which one
        self._wizard[session_id] = {"state": _WZ_DEL_SEL, "data": {}}
        names_list = "\n".join(f"• `{n}`" for n in agents)
        await update.message.reply_text(
            f"🗑️ **刪除子代理 Bot**\n\n"
            f"現有子代理：\n{names_list}\n\n"
            f"請輸入要刪除的子代理名稱，或輸入 `cancel` 取消：",
            parse_mode="Markdown",
        )

    async def _start_del_confirm(self, update: Update, session_id: tuple, name: str):
        """Enter the delete-confirmation step of the wizard."""
        info = self.sub_agents.get(name)
        created = info.get("created_at", "?") if info else "?"
        self._wizard[session_id] = {
            "state": _WZ_DEL_CONF,
            "data": {"target": name},
        }
        await update.message.reply_text(
            f"⚠️ **確認刪除**\n\n"
            f"子代理：**{name}**\n"
            f"建立時間：{created}\n\n"
            f"此操作將永久刪除 `agents/{name}/` 資料夾及所有相關資料（記憶、排程、工具等），"
            f"且**無法復原**。\n\n"
            f"輸入 `yes` 確認刪除，`no` 取消：",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────
    # Wizard state machine
    # ─────────────────────────────────────────────

    async def _handle_wizard(self, update: Update, text: str, session_id: tuple):
        """Route message to the appropriate wizard step handler."""
        wz = self._wizard.get(session_id)
        if not wz:
            return

        # Universal cancel
        if text.strip().lower() == "cancel":
            self._wizard.pop(session_id, None)
            await update.message.reply_text("✅ 已取消操作")
            return

        state = wz["state"]

        if state == _WZ_NEW_NAME:
            await self._wz_new_name(update, text, session_id, wz)
        elif state == _WZ_NEW_TOKEN:
            await self._wz_new_token(update, text, session_id, wz)
        elif state == _WZ_DEL_SEL:
            await self._wz_del_sel(update, text, session_id, wz)
        elif state == _WZ_DEL_CONF:
            await self._wz_del_conf(update, text, session_id, wz)
        elif state == _WZ_DEL_BURY:
            await self._wz_del_bury(update, text, session_id, wz)

    async def _wz_new_name(self, update, text, session_id, wz):
        """Wizard step: validate name, then ask for token."""
        from sub_agent_manager import SubAgentManager
        err = SubAgentManager.validate_name(text.strip())
        if err:
            await update.message.reply_text(
                f"❌ {err}\n\n請重新輸入，或輸入 `cancel` 取消：",
                parse_mode="Markdown",
            )
            return

        name = text.strip()
        if self.sub_agents.get(name):
            await update.message.reply_text(
                f"❌ 子代理 `{name}` 已存在，請使用其他名稱：",
                parse_mode="Markdown",
            )
            return

        wz["data"]["name"] = name
        wz["state"] = _WZ_NEW_TOKEN

        await update.message.reply_text(
            f"✅ 名稱：**{name}**\n\n"
            f"**第二步：** 請前往 [@BotFather](https://t.me/BotFather)，"
            f"建立一個新的 Bot 並取得 Token。\n\n"
            f"完成後將 Token 貼到這裡：\n"
            f"（格式：`數字:英數字串`，例如 `7654321:ABCdefGHI`）\n\n"
            f"輸入 `cancel` 可取消：",
            parse_mode="Markdown",
        )

    async def _wz_new_token(self, update, text, session_id, wz):
        """Wizard step: validate token, create the sub-agent."""
        from sub_agent_manager import SubAgentManager
        token = text.strip()
        err = SubAgentManager.validate_token(token)
        if err:
            await update.message.reply_text(
                f"❌ {err}\n\n請重新輸入，或輸入 `cancel` 取消：",
                parse_mode="Markdown",
            )
            return

        name = wz["data"]["name"]
        self._wizard.pop(session_id, None)

        await update.message.reply_text("⏳ 正在建立子代理，請稍候…")

        result = self.sub_agents.create(name, token, self.config)
        await self._send(update, result)

        if "已建立並啟動" in result:
            await update.message.reply_text(
                f"📌 **第三步：** 請將新建立的 Bot 加入此群組並給予適當權限。\n\n"
                f"加入後，子代理 **{name}** 就會開始在群組中運作，"
                f"擁有完全獨立的對話記憶、工具與排程。\n\n"
                f"使用 `/list_agents` 查看所有子代理狀態。",
                parse_mode="Markdown",
            )

    async def _wz_del_sel(self, update, text, session_id, wz):
        """Wizard step: select which agent to delete (multi-agent case)."""
        name = text.strip()
        if self.sub_agents.get(name) is None:
            agents = self.sub_agents.names()
            names_list = "\n".join(f"• `{n}`" for n in agents)
            await update.message.reply_text(
                f"❌ 找不到子代理 `{name}`\n\n現有：\n{names_list}\n\n"
                f"請重新輸入，或輸入 `cancel` 取消：",
                parse_mode="Markdown",
            )
            return
        await self._start_del_confirm(update, session_id, name)

    async def _wz_del_conf(self, update, text, session_id, wz):
        """Wizard step: yes/no confirmation before deletion."""
        answer = text.strip().lower()
        if answer not in ("yes", "no", "y", "n"):
            await update.message.reply_text(
                "請輸入 `yes` 確認刪除，或 `no` / `cancel` 取消：",
                parse_mode="Markdown",
            )
            return

        target = wz["data"]["target"]

        if answer in ("no", "n"):
            self._wizard.pop(session_id, None)
            await update.message.reply_text(f"✅ 已取消，子代理 **{target}** 保留不動。",
                                            parse_mode="Markdown")
            return

        # Confirmed deletion — ask about graveyard
        wz["state"] = _WZ_DEL_BURY
        await update.message.reply_text(
            f"🪦 **要將 {target} 送往數位墓園嗎？**\n\n"
            f"數位墓園是一個讓你為退役專案留下紀念的地方。\n"
            f"你可以在那裡為 **{target}** 留下一段告別文字。\n\n"
            f"輸入 `yes` 前往墓園（我會提供連結），`no` 直接刪除：",
            parse_mode="Markdown",
        )

    async def _wz_del_bury(self, update, text, session_id, wz):
        """Wizard step: offer graveyard link, then delete."""
        answer = text.strip().lower()
        target = wz["data"]["target"]
        self._wizard.pop(session_id, None)

        if answer in ("yes", "y"):
            await update.message.reply_text(
                f"🌿 請前往數位墓園，為 **{target}** 留下最後的記念：\n\n"
                f"{GRAVEYARD_URL}\n\n"
                f"填寫時可以提到這是一個 HydraBot 子代理專案，"
                f"記錄它完成的任務和存在的意義。",
                parse_mode="Markdown",
            )

        # Delete regardless of burial choice
        ok = self.sub_agents.delete(target)
        if ok:
            await update.message.reply_text(
                f"✅ 子代理 **{target}** 已刪除。\n"
                f"`agents/{target}/` 資料夾及所有相關資料已移除。",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"⚠️ 找不到子代理 {target}，可能已被刪除。")

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

        # ── Sub-agent wizard flow ───────────────────────────────────
        if session_id in self._wizard:
            await self._handle_wizard(update, text, session_id)
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

            url = "https://raw.githubusercontent.com/Adaimade/HydraBot/main/VERSION"
            # Run blocking network call in thread pool to avoid blocking the event loop
            response = await asyncio.to_thread(requests.get, url, timeout=3)
            response.raise_for_status()
            latest = response.text.strip()

            version_file = Path(__file__).parent / "VERSION"
            if version_file.exists():
                current = version_file.read_text().strip()
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

        # Start all registered sub-agent bots
        if self.sub_agents:
            self.sub_agents.start_all()

        # Check for updates in background (don't wait)
        asyncio.create_task(self._check_updates())

        commands = [
            BotCommand("start",        "顯示歡迎訊息"),
            BotCommand("reset",        "清除目前會話記錄"),
            BotCommand("tools",        "列出可用工具"),
            BotCommand("models",       "查看／切換模型"),
            BotCommand("tasks",        "查看背景任務進度"),
            BotCommand("notify",       "查看／管理定時通知排程"),
            BotCommand("timezone",     "查看／設定時區 (UTC+N)"),
            BotCommand("status",       "系統狀態與會話資訊"),
            BotCommand("soul",         "查看／清除 Bot 人設（SOUL.md）"),
            BotCommand("whitelist",    "管理授權用戶白名單"),
        ]
        if self.sub_agents is not None:
            commands += [
                BotCommand("new_agent",    "建立子代理 Bot"),
                BotCommand("list_agents",  "查看所有子代理 Bot"),
                BotCommand("delete_agent", "刪除子代理 Bot"),
            ]
        await app.bot.set_my_commands(commands)

    def run(self):
        app = (
            Application.builder()
            .token(self.config["telegram_token"])
            .post_init(self._post_init)
            .build()
        )

        # /model and /models both handled by cmd_models
        app.add_handler(CommandHandler("start",        self.cmd_start))
        app.add_handler(CommandHandler("reset",        self.cmd_reset))
        app.add_handler(CommandHandler("tools",        self.cmd_tools))
        app.add_handler(CommandHandler("models",       self.cmd_models))
        app.add_handler(CommandHandler("model",        self.cmd_models))
        app.add_handler(CommandHandler("tasks",        self.cmd_tasks))
        app.add_handler(CommandHandler("notify",       self.cmd_notify))
        app.add_handler(CommandHandler("timezone",     self.cmd_timezone))
        app.add_handler(CommandHandler("status",       self.cmd_status))
        app.add_handler(CommandHandler("soul",         self.cmd_soul))
        app.add_handler(CommandHandler("whitelist",    self.cmd_whitelist))
        if self.sub_agents is not None:
            app.add_handler(CommandHandler("new_agent",    self.cmd_new_agent))
            app.add_handler(CommandHandler("list_agents",  self.cmd_list_agents))
            app.add_handler(CommandHandler("delete_agent", self.cmd_delete_agent))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        import datetime
        local_tz_offset = datetime.datetime.now().astimezone().utcoffset()
        tz_seconds = int(local_tz_offset.total_seconds())
        tz_hours   = tz_seconds // 3600
        tz_sign    = "+" if tz_hours >= 0 else ""
        local_tz_str = f"UTC{tz_sign}{tz_hours}"

        if self.authorized_users:
            auth_info = f"{len(self.authorized_users)} 人（IDs: {', '.join(str(u) for u in sorted(self.authorized_users))}）"
        else:
            auth_info = "所有人（無限制）"

        print(f"🐍 HydraBot 運行中！")
        print(f"   模型    : {len(self.pool.model_configs)} 組")
        for i, m in enumerate(self.pool.model_configs):
            print(f"     [{i}] {m.get('name', m['model'])}  ({m['provider']} / {m['model']})")
        print(f"   工具    : {len(self.pool.tools) + 4} 個")
        print(f"   存取    : {auth_info}")
        print(f"   時區    : {local_tz_str}（本機系統時區）")
        print(f"   會話    : chat_id + thread_id 雙維度隔離")
        print(f"   Ctrl+C 停止\n")

        app.run_polling(drop_pending_updates=True)
