#!/usr/bin/env python3
"""
HydraBot — Notification Scheduler
定時通知排程器，支援一次性和循環通知。

支援格式：
  fire_at:
    · ISO 8601 datetime 字串  "2026-03-01T15:00:00"
    · 相對時間               "+30m" | "+2h" | "+1d"
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
from datetime import datetime, timedelta
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


def parse_fire_at(when: str) -> datetime:
    """
    Parse `when` string into a datetime.

    Accepted formats:
      "+Nm"  — N minutes from now
      "+Nh"  — N hours  from now
      "+Nd"  — N days   from now
      ISO 8601 — "2026-03-01T15:00:00"
    """
    when = when.strip()
    if when.startswith("+"):
        body = when[1:]
        if body.endswith("m"):
            return datetime.now() + timedelta(minutes=int(body[:-1]))
        if body.endswith("h"):
            return datetime.now() + timedelta(hours=int(body[:-1]))
        if body.endswith("d"):
            return datetime.now() + timedelta(days=int(body[:-1]))
        raise ValueError(f"未知相對格式: {when}（應為 +Nm / +Nh / +Nd）")
    return datetime.fromisoformat(when)


# ─────────────────────────────────────────────────────────────
# ScheduledJob data class
# ─────────────────────────────────────────────────────────────

class ScheduledJob:
    def __init__(
        self,
        job_id: str,
        session_id: tuple,
        message: str,
        fire_at: datetime,
        repeat: Optional[Union[str, int]] = None,
        label: str = "",
    ):
        self.job_id     = job_id
        self.session_id = session_id   # (chat_id, thread_id)
        self.message    = message
        self.fire_at    = fire_at      # next fire time
        self.repeat     = repeat       # None | str | int(seconds)
        self.label      = label
        self.active     = True
        self.created_at = datetime.now()

    # ── serialisation ──────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "job_id":     self.job_id,
            "session_id": list(self.session_id),
            "message":    self.message,
            "fire_at":    self.fire_at.isoformat(),
            "repeat":     self.repeat,
            "label":      self.label,
            "active":     self.active,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduledJob":
        # session_id stored as [chat_id, thread_id]
        sid = tuple(d["session_id"])
        job = cls(
            job_id     = d["job_id"],
            session_id = sid,
            message    = d["message"],
            fire_at    = datetime.fromisoformat(d["fire_at"]),
            repeat     = d.get("repeat"),
            label      = d.get("label", ""),
        )
        job.active = d.get("active", True)
        if "created_at" in d:
            job.created_at = datetime.fromisoformat(d["created_at"])
        return job

    # ── display ────────────────────────────────────────────────

    def status_line(self) -> str:
        repeat_str = self.repeat if self.repeat else "一次性"
        label_str  = f"[{self.label}] " if self.label else ""
        state_icon = "✅" if self.active else "❌"
        return (
            f"{state_icon} `{self.job_id}`  {label_str}\n"
            f"   下次觸發: `{self.fire_at.strftime('%Y-%m-%d %H:%M:%S')}`  重複: {repeat_str}\n"
            f"   訊息: {self.message[:60]}{'…' if len(self.message) > 60 else ''}"
        )


# ─────────────────────────────────────────────────────────────
# NotificationScheduler
# ─────────────────────────────────────────────────────────────

class NotificationScheduler:
    """
    後台執行緒排程器 — 每 5 秒掃描到期通知並發送。

    使用方式：
      scheduler = NotificationScheduler()           # 在 AgentPool 裡建立
      scheduler.start(loop, send_func)              # 在 _post_init 裡啟動
    """

    def __init__(self):
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock        = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_func: Optional[Callable] = None
        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_jobs()

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop, send_func: Callable):
        """啟動排程背景執行緒。在 bot._post_init 裡呼叫。"""
        self._loop      = loop
        self._send_func = send_func
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="hydra_scheduler"
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
        fire_at: datetime,
        repeat: Optional[Union[str, int]] = None,
        label: str = "",
    ) -> str:
        """新增定時通知，回傳 job_id。"""
        job_id = f"sched_{uuid.uuid4().hex[:8]}"
        job    = ScheduledJob(job_id, session_id, message, fire_at, repeat, label)
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

    def format_jobs_list(self, session_id: Optional[tuple] = None) -> str:
        """回傳格式化的排程列表字串，供 bot 直接傳送。"""
        jobs = self.list_jobs(session_id)
        if not jobs:
            return "📭 目前沒有任何排程通知"
        lines = [f"⏰ **排程通知** ({len(jobs)} 個)\n"]
        for job in sorted(jobs, key=lambda j: j.fire_at):
            lines.append(job.status_line())
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────

    def _save_jobs(self):
        try:
            with self._lock:
                data = [j.to_dict() for j in self._jobs.values()]
            SCHEDULES_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save schedules: {e}")

    def _load_jobs(self):
        if not SCHEDULES_FILE.exists():
            return
        try:
            data = json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
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
        """每 5 秒掃描一次到期的 job 並觸發。"""
        while not self._stop_event.wait(timeout=5):
            now     = datetime.now()
            to_fire = []
            with self._lock:
                for job in self._jobs.values():
                    if job.active and job.fire_at <= now:
                        to_fire.append(job)
            for job in to_fire:
                self._fire_job(job)

    def _fire_job(self, job: ScheduledJob):
        """觸發一個通知並決定是否重新排程。"""
        label_str = f"[{job.label}] " if job.label else ""
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
                job.fire_at = datetime.now() + timedelta(seconds=interval)
                logger.debug(f"Job {job.job_id} rescheduled → {job.fire_at}")
            else:
                job.active = False
                logger.debug(f"Job {job.job_id} fired (one-shot) → inactive")

        self._save_jobs()
