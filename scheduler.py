#!/usr/bin/env python3
"""
HydraBot — Notification Scheduler
定時通知排程器，支援一次性和循環通知。

內部時間全部使用 UTC（naive datetime）。
用戶輸入的絕對時間會依 tz_offset_hours 轉換為 UTC 後存入。
顯示時再轉回用戶本地時間。

支援格式：
  fire_at:
    · ISO 8601 datetime 字串  "2026-03-01T15:00:00"  （視為用戶本地時間）
    · 相對時間               "+30m" | "+2h" | "+1d"  （與時區無關）
  repeat:
    · None / "once"           一次性
    · "minutely"              每分鐘
    · "hourly"                每小時
    · "daily"                 每天
    · "weekly"                每週
    · 整數（秒）              自訂間隔
"""

import json
import uuid
import threading
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)

SCHEDULES_FILE = Path("schedules.json")

# repeat 關鍵字 → 秒數
REPEAT_INTERVALS: dict[str, int] = {
    "minutely": 60,
    "hourly":   3600,
    "daily":    86400,
    "weekly":   604800,
}


def utcnow() -> datetime:
    """回傳目前的 UTC 時間（naive datetime，無 tzinfo）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_fire_at(when: str, tz_offset_hours: int = 0) -> datetime:
    """
    將 `when` 字串解析為 UTC datetime。

    · 相對格式 (+Nm/+Nh/+Nd)：直接加到 utcnow()，與時區無關。
    · 絕對格式 (ISO 8601)：視為用戶本地時間，轉換為 UTC：
        UTC = local - tz_offset_hours

    Args:
        when: 時間字串
        tz_offset_hours: 用戶的 UTC 偏移（例如 UTC+8 傳入 8，UTC-5 傳入 -5）
    """
    when = when.strip()
    if when.startswith("+"):
        body = when[1:]
        if body.endswith("m"):
            return utcnow() + timedelta(minutes=int(body[:-1]))
        if body.endswith("h"):
            return utcnow() + timedelta(hours=int(body[:-1]))
        if body.endswith("d"):
            return utcnow() + timedelta(days=int(body[:-1]))
        raise ValueError(f"未知相對格式: {when}（應為 +Nm / +Nh / +Nd）")
    # 絕對時間：用戶本地 → UTC
    local_dt = datetime.fromisoformat(when)
    return local_dt - timedelta(hours=tz_offset_hours)


def utc_to_local(utc_dt: datetime, tz_offset_hours: int) -> datetime:
    """UTC datetime → 用戶本地 datetime。"""
    return utc_dt + timedelta(hours=tz_offset_hours)


def tz_label(tz_offset_hours: int) -> str:
    """將 UTC 偏移轉為顯示字串，例如 8 → 'UTC+8'，-5 → 'UTC-5'。"""
    sign = "+" if tz_offset_hours >= 0 else ""
    return f"UTC{sign}{tz_offset_hours}"


# ─────────────────────────────────────────────────────────────
# ScheduledJob data class
# ─────────────────────────────────────────────────────────────

class ScheduledJob:
    def __init__(
        self,
        job_id: str,
        session_id: tuple,
        message: str,
        fire_at: datetime,          # UTC
        repeat: Optional[Union[str, int]] = None,
        label: str = "",
        kind: str = "notify",
    ):
        self.job_id     = job_id
        self.session_id = session_id   # (chat_id, thread_id)
        self.message    = message
        self.fire_at    = fire_at      # UTC datetime，下次觸發時間
        self.repeat     = repeat       # None | str | int(seconds)
        self.label      = label
        # notify = 到點推送固定文字；llm_task = 到點以 message 為任務描述呼叫 LLM，結果再推送
        self.kind       = kind if kind in ("notify", "llm_task") else "notify"
        self.active     = True
        self.created_at = utcnow()

    # ── serialisation ──────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "job_id":     self.job_id,
            "session_id": list(self.session_id),
            "message":    self.message,
            "fire_at":    self.fire_at.isoformat(),
            "repeat":     self.repeat,
            "label":      self.label,
            "kind":       self.kind,
            "active":     self.active,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduledJob":
        sid = tuple(d["session_id"])
        job = cls(
            job_id     = d["job_id"],
            session_id = sid,
            message    = d["message"],
            fire_at    = datetime.fromisoformat(d["fire_at"]),
            repeat     = d.get("repeat"),
            label      = d.get("label", ""),
            kind       = d.get("kind", "notify"),
        )
        job.active = d.get("active", True)
        if "created_at" in d:
            job.created_at = datetime.fromisoformat(d["created_at"])
        return job

    # ── display ────────────────────────────────────────────────

    def status_line(self, tz_offset_hours: int = 0) -> str:
        """格式化一行狀態，時間顯示為用戶本地時間。"""
        local_dt   = utc_to_local(self.fire_at, tz_offset_hours)
        tz_str     = tz_label(tz_offset_hours)
        repeat_str = self.repeat if self.repeat else "一次性"
        label_str  = f"[{self.label}] " if self.label else ""
        state_icon = "✅" if self.active else "❌"
        short_msg  = self.message[:60] + ("…" if len(self.message) > 60 else "")
        kind_tag = "任務" if self.kind == "llm_task" else "通知"
        return (
            f"{state_icon} `{self.job_id}`  {label_str}[{kind_tag}]\n"
            f"   下次觸發: `{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str})`  重複: {repeat_str}\n"
            f"   內容: {short_msg}"
        )


# ─────────────────────────────────────────────────────────────
# NotificationScheduler
# ─────────────────────────────────────────────────────────────

class NotificationScheduler:
    """
    後台執行緒排程器 — 每 5 秒掃描到期通知並發送。
    所有時間以 UTC 儲存，對比也用 utcnow()。

    使用方式：
      scheduler = NotificationScheduler()       # 在 AgentPool 裡建立
      scheduler.start(loop, send_func)          # 在 bot._post_init 裡啟動

    schedules_file — 可指定路徑（例如 Discord 專用 discord_schedules.json）
    """

    def __init__(self, schedules_file: Optional[Union[str, Path]] = None):
        self._schedules_file = Path(schedules_file) if schedules_file else SCHEDULES_FILE
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock        = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_func: Optional[Callable] = None
        # (session_id, task_text) -> str  同步；排程觸發 llm_task 時呼叫
        self._task_runner: Optional[Callable[[tuple, str], str]] = None
        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_jobs()

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    def start(
        self,
        loop: asyncio.AbstractEventLoop,
        send_func: Callable,
        task_runner: Optional[Callable[[tuple, str], str]] = None,
    ):
        """啟動排程背景執行緒。在 bot._post_init 裡呼叫。"""
        self._loop      = loop
        self._send_func = send_func
        self._task_runner = task_runner
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"hydra_sched_{id(self) & 0xFFFF:x}",
        )
        self._thread.start()
        active = sum(1 for j in self._jobs.values() if j.active)
        print(f"⏰ Scheduler started — {active} active job(s)")

    def stop(self):
        self._stop_event.set()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def add_job(
        self,
        session_id: tuple,
        message: str,
        fire_at: datetime,              # must be UTC
        repeat: Optional[Union[str, int]] = None,
        label: str = "",
        kind: str = "notify",
    ) -> str:
        """新增定時通知或定時 LLM 任務，回傳 job_id。fire_at 必須是 UTC。"""
        job_id = f"sched_{uuid.uuid4().hex[:8]}"
        job    = ScheduledJob(job_id, session_id, message, fire_at, repeat, label, kind=kind)
        with self._lock:
            self._jobs[job_id] = job
        self._save_jobs()
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """取消排程，回傳是否成功。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.active = False
        self._save_jobs()
        return True

    def list_jobs(self, session_id: Optional[tuple] = None) -> list[ScheduledJob]:
        """列出所有 active 的排程（可按 session 過濾）。"""
        with self._lock:
            jobs = list(self._jobs.values())
        if session_id is not None:
            jobs = [j for j in jobs if j.session_id == session_id]
        return [j for j in jobs if j.active]

    def format_jobs_list(
        self,
        session_id: Optional[tuple] = None,
        tz_offset_hours: int = 0,
    ) -> str:
        """回傳格式化的排程列表字串，時間顯示為用戶本地時區。"""
        jobs = self.list_jobs(session_id)
        if not jobs:
            return "📭 目前沒有任何排程通知"
        tz_str = tz_label(tz_offset_hours)
        lines  = [f"⏰ **排程通知** ({len(jobs)} 個，時間顯示為 {tz_str})\n"]
        for job in sorted(jobs, key=lambda j: j.fire_at):
            lines.append(job.status_line(tz_offset_hours))
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────

    def _save_jobs(self):
        try:
            with self._lock:
                data = [j.to_dict() for j in self._jobs.values()]
            self._schedules_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save schedules: {e}")

    def _load_jobs(self):
        if not self._schedules_file.exists():
            return
        try:
            data = json.loads(self._schedules_file.read_text(encoding="utf-8"))
            for d in data:
                job = ScheduledJob.from_dict(d)
                # 過期的一次性 inactive job 不需要再載入
                if not job.active and not job.repeat:
                    continue
                self._jobs[job.job_id] = job
            logger.info(f"Loaded {len(self._jobs)} scheduled jobs from disk")
        except Exception as e:
            logger.warning(f"Failed to load schedules: {e}")

    # ─────────────────────────────────────────────
    # Scheduler loop
    # ─────────────────────────────────────────────

    def _run_loop(self):
        """每 5 秒掃描一次到期的 job 並觸發（以 UTC 對比）。"""
        while not self._stop_event.wait(timeout=5):
            now     = utcnow()
            to_fire = []
            with self._lock:
                for job in self._jobs.values():
                    if job.active and job.fire_at <= now:
                        to_fire.append(job)
            for job in to_fire:
                # Re-check active flag: the job may have been cancelled
                # between the collection above and now.
                if job.active:
                    self._fire_job(job)

    def _fire_job(self, job: ScheduledJob):
        """觸發一個通知並決定是否重新排程。"""
        label_str = f"[{job.label}] " if job.label else ""

        if job.kind == "llm_task":
            if not self._task_runner:
                logger.warning("llm_task job %s dropped: no task_runner", job.job_id)
                with self._lock:
                    job.active = False
                self._save_jobs()
                return
            if not self._send_func or not self._loop:
                logger.warning("llm_task job %s dropped: send_func/loop not wired", job.job_id)
                with self._lock:
                    job.active = False
                self._save_jobs()
                return
            try:
                result = self._task_runner(job.session_id, job.message)
                msg = f"⏰ **排程任務完成** {label_str}\n\n{result}"
            except Exception as e:
                msg = (
                    f"❌ **排程任務失敗** {label_str}\n\n"
                    f"{e}\n```\n{traceback.format_exc()}\n```"
                )
            asyncio.run_coroutine_threadsafe(
                self._send_func(job.session_id, msg),
                self._loop,
            )
        else:
            msg = f"⏰ **定時通知** {label_str}\n\n{job.message}"

            if self._send_func and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_func(job.session_id, msg),
                    self._loop,
                )

        # 更新排程或停用
        with self._lock:
            if job.repeat:
                if isinstance(job.repeat, str):
                    interval = REPEAT_INTERVALS.get(job.repeat, 86400)
                else:
                    interval = int(job.repeat)
                job.fire_at = utcnow() + timedelta(seconds=interval)
                logger.debug(f"Job {job.job_id} rescheduled → {job.fire_at} UTC")
            else:
                job.active = False
                logger.debug(f"Job {job.job_id} fired (one-shot) → inactive")

        self._save_jobs()
