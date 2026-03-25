#!/usr/bin/env python3
"""
HydraBot — Discord 介面（可與 Telegram 並行）。

Session 格式：(根頻道 id, 討論串 id | None)，與 Telegram (chat, topic) 概念對應。
資料檔預設前綴 discord_（memory / schedules / timezones），避免與 TG 混用。

啟用方式：config.json 設定 discord_token，並在 Developer Portal 開啟 Message Content Intent。
"""

from __future__ import annotations

import asyncio
import re
import threading
import discord

MAX_DISCORD = 2000

UNAUTHORIZED_DISC = (
    "⛔ 未授權使用此 Bot。\n"
    "請聯繫管理員將你的 Discord 使用者 ID 加入 config.json 的 `discord_authorized_users`。"
)


def split_discord_chunks(text: str, limit: int = MAX_DISCORD) -> list[str]:
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        step = ("\n" if cur else "") + line
        if len(cur) + len(step) > limit:
            if cur:
                chunks.append(cur)
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            cur = line
        else:
            cur += step
    if cur:
        chunks.append(cur)
    return chunks


def _discord_session_id(message: discord.Message) -> tuple:
    ch = message.channel
    if isinstance(ch, discord.Thread):
        return (ch.parent_id, ch.id)
    return (ch.id, None)


def _normalize_dc_prefix(config: dict) -> str:
    p = config.get("discord_data_prefix")
    if p is None or str(p).strip() == "":
        return "discord_"
    p = str(p).strip()
    return p if p.endswith("_") else p + "_"


class HydraDiscordClient(discord.Client):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.config = config
        self._dc_users = set(config.get("discord_authorized_users") or [])
        self._channels = set(config.get("discord_channel_ids") or [])
        self._guilds = set(config.get("discord_guild_ids") or [])
        self._allow_dm = config.get("discord_allow_dm", True)

        from agent import AgentPool

        self._prefix = _normalize_dc_prefix(config)
        self.pool = AgentPool(config, data_prefix=self._prefix)
        print(
            f"🧠 Discord Agent Pool（前綴 `{self._prefix}`）— "
            f"{len(self.pool.model_configs)} 組模型，{len(self.pool.tools) + 4} 個工具"
        )

    def _ok_user(self, user_id: int) -> bool:
        if self._dc_users:
            return user_id in self._dc_users
        return True

    def _ok_channel(self, message: discord.Message) -> bool:
        ch = message.channel
        if isinstance(ch, discord.DMChannel):
            return bool(self._allow_dm)
        if self._guilds and message.guild and message.guild.id not in self._guilds:
            return False
        # 討論串以「父頻道」ID 對照白名單
        effective_id = ch.parent_id if isinstance(ch, discord.Thread) else ch.id
        if self._channels and effective_id not in self._channels:
            return False
        return True

    async def on_ready(self):
        loop = asyncio.get_running_loop()
        self.pool._loop = loop
        self.pool._send_func = self._deliver_to_session
        self.pool.scheduler.start(loop, self.pool._send_func)
        active = sum(1 for j in self.pool.scheduler._jobs.values() if j.active)
        print(f"✅ Discord 已登入：{self.user}（伺服器數 {len(self.guilds)}）")
        print(f"   排程器作用中 job：{active}")

    async def _deliver_to_session(self, session_id: tuple, text: str):
        root_id, th_id = session_id[0], session_id[1]
        try:
            if th_id is not None:
                dest = self.get_channel(th_id) or await self.fetch_channel(th_id)
            else:
                dest = self.get_channel(root_id) or await self.fetch_channel(root_id)
        except Exception as e:
            print(f"⚠️ Discord 排程送達失敗 {session_id}: {e}")
            return
        if dest is None:
            return
        for chunk in split_discord_chunks(text):
            try:
                await dest.send(chunk)
            except Exception as e:
                print(f"⚠️ Discord send: {e}")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not self._ok_user(message.author.id):
            await message.channel.send(UNAUTHORIZED_DISC)
            return
        if not self._ok_channel(message):
            return

        content = message.content.strip()
        if self.user:
            content = re.sub(r"<@!?\d+>", "", content).strip()

        if content.startswith("!"):
            await self._handle_command(message, content[1:].strip())
            return

        session_id = _discord_session_id(message)
        await self._chat_reply(message, session_id, content)

    async def _handle_command(self, message: discord.Message, body: str):
        parts = body.split(maxsplit=1)
        cmd = (parts[0] or "").lower()
        argrest = parts[1] if len(parts) > 1 else ""
        session_id = _discord_session_id(message)

        if cmd in ("start", "help", "h"):
            await self._cmd_start(message)
        elif cmd == "reset":
            self.pool.reset_conversation(session_id)
            await message.channel.send("✅ 已清除此頻道／討論串的對話記錄。")
        elif cmd == "tools":
            await self._send_long(message.channel, self.pool.list_tools_info())
        elif cmd == "models":
            args = argrest.split()
            if args and args[0].isdigit():
                r = self.pool.switch_model(session_id, int(args[0]))
                await message.channel.send(r)
            else:
                await self._send_long(message.channel, self.pool.list_models_info(session_id))
        elif cmd == "tasks":
            await self._send_long(message.channel, self.pool.list_tasks_info())
        elif cmd == "notify":
            args = argrest.split()
            tz = self.pool.get_timezone(session_id) or 0
            if args and args[0].lower() == "cancel" and len(args) >= 2:
                ok = self.pool.scheduler.cancel_job(args[1])
                await message.channel.send("✅ 已取消" if ok else "❌ 找不到該排程")
            else:
                await self._send_long(
                    message.channel,
                    self.pool.scheduler.format_jobs_list(
                        session_id=session_id, tz_offset_hours=tz
                    ),
                )
        elif cmd == "remind":
            ra = argrest.split(maxsplit=1)
            if len(ra) < 2:
                await message.channel.send(
                    "用法：`!remind +1m 訊息` 或 `!remind 2026-03-01T09:00:00 標題`"
                )
                return
            when, msg = ra[0], ra[1]
            from scheduler import parse_fire_at, utc_to_local, tz_label

            tz_offset = self.pool.get_timezone(session_id) or 0
            try:
                fire_at = parse_fire_at(when, tz_offset_hours=tz_offset)
            except Exception as e:
                await message.channel.send(f"❌ 時間無法解析：{e}")
                return
            job_id = self.pool.scheduler.add_job(
                session_id=session_id,
                message=msg,
                fire_at=fire_at,
                repeat=None,
                label="",
            )
            loc = utc_to_local(fire_at, tz_offset)
            await message.channel.send(
                f"✅ 排程 `{job_id}`\n"
                f"觸發（{tz_label(tz_offset)}）: {loc.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        elif cmd == "timezone":
            if argrest.strip():
                tz = self._parse_tz(argrest.strip())
                if tz is None:
                    await message.channel.send("❌ 請用 UTC+8、+8 或 8（範圍 -12～14）")
                    return
                self.pool.set_timezone(session_id, tz)
                sign = "+" if tz >= 0 else ""
                await message.channel.send(f"✅ 時區已設為 UTC{sign}{tz}")
            else:
                t = self.pool.get_timezone(session_id)
                if t is None:
                    await message.channel.send("目前時區：未設定（例：`!timezone UTC+8`）")
                else:
                    sign = "+" if t >= 0 else ""
                    await message.channel.send(f"目前時區：UTC{sign}{t}")
        elif cmd == "status":
            await self._send_long(message.channel, self._status_text(message, session_id))
        else:
            await message.channel.send(
                f"未知指令 `{cmd}`。輸入 `!help`；一般對話可直接打字。"
            )

    @staticmethod
    def _parse_tz(text: str) -> int | None:
        t = text.strip().upper()
        m = re.match(r"^(?:UTC)?([+-]?\d+)$", t)
        if not m:
            return None
        n = int(m.group(1))
        return n if -12 <= n <= 14 else None

    def _status_text(self, message: discord.Message, session_id: tuple) -> str:
        idx = self.pool.user_model.get(session_id, 0)
        m = self.pool.model_configs[idx % len(self.pool.model_configs)]
        t = self.pool.get_timezone(session_id)
        if t is None:
            tzs = "未設定"
        else:
            sign = "+" if t >= 0 else ""
            tzs = f"UTC{sign}{t}"
        ch = message.channel
        if isinstance(ch, discord.Thread):
            label = f"討論串 {ch.id}（父 {ch.parent_id}）"
        else:
            label = f"頻道 {ch.id}"
        return (
            f"🖥️ **Discord / HydraBot**\n"
            f"會話: `{label}`\n"
            f"時區: `{tzs}`\n"
            f"模型: `{m.get('name', m['model'])}` (#{idx})\n"
            f"工具數: {len(self.pool.tools) + 4}\n"
            f"資料檔前綴: `{self._prefix}`"
        )

    async def _cmd_start(self, message: discord.Message):
        text = (
            "👋 **HydraBot（Discord）**\n\n"
            "每個文字頻道／討論串有獨立對話脈絡。\n\n"
            "**指令（前綴 `!`）**\n"
            "`!help` — 說明\n"
            "`!reset` — 清除此處對話\n"
            "`!tools` / `!models` / `!tasks`\n"
            "`!notify` / `!notify cancel <id>`\n"
            "`!remind +1m 文字`\n"
            "`!timezone` / `!timezone UTC+8`\n"
            "`!status`\n\n"
            "**一般聊天**：直接打字即可（也可 @ 機器人）。\n"
            "Developer Portal 請啟用 **Message Content Intent**。"
        )
        await self._send_long(message.channel, text)

    async def _chat_reply(self, message: discord.Message, session_id: tuple, text: str):
        if not text:
            return
        import tools_builtin

        loop = asyncio.get_running_loop()
        typing_task = asyncio.create_task(self._typing_loop(message.channel))
        tools_builtin.current_session_id[0] = session_id
        try:
            reply = await loop.run_in_executor(
                None, lambda: self.pool.chat(session_id, text)
            )
        except Exception as e:
            reply = f"❌ 錯誤: {e}"
        finally:
            typing_task.cancel()
        await self._send_long(message.channel, reply)

    async def _typing_loop(self, channel):
        try:
            while True:
                async with channel.typing():
                    await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def _send_long(self, channel, text: str):
        for i, chunk in enumerate(split_discord_chunks(text)):
            if i:
                await asyncio.sleep(0.25)
            await channel.send(chunk)


def run_discord_bot_thread(config: dict) -> threading.Thread:
    """在背景執行緒啟動 Discord（client.run 會阻塞該執行緒）。"""

    def worker():
        try:
            client = HydraDiscordClient(config)
            token = (config.get("discord_token") or "").strip()
            client.run(token)
        except Exception as e:
            print(f"❌ Discord Bot 錯誤: {e}")

    t = threading.Thread(target=worker, name="hydra_discord", daemon=True)
    t.start()
    return t
