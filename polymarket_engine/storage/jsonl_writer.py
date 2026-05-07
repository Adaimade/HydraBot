"""Daily-rotated, fsync-on-interval JSONL writer with atomic finalise.

Layout: <root>/<source>/<event>/YYYY-MM-DD.jsonl[.partial]

The active file carries a `.partial` suffix until it rotates (UTC midnight
based on each record's `ts_local_ms`) or `close()` is called, at which
point it's renamed to its final form via `os.replace` (atomic on POSIX).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _date_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


class _Handle:
    __slots__ = ("path", "final_path", "fp", "last_fsync_ms", "bytes_written")

    def __init__(self, path: Path, final_path: Path, fp):
        self.path = path
        self.final_path = final_path
        self.fp = fp
        self.last_fsync_ms = 0
        self.bytes_written = 0


class JsonlWriter:
    def __init__(
        self,
        root: Path,
        fsync_interval_sec: int = 5,
        now_fn: Callable[[], float] | None = None,
    ):
        self._root = Path(root)
        self._fsync_interval_ms = int(fsync_interval_sec * 1000)
        self._now_fn = now_fn or (lambda: time.time())
        self._handles: dict[tuple[str, str], _Handle] = {}
        self._date_for: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def _wall_ms(self) -> int:
        return int(self._now_fn() * 1000)

    def _open(self, source: str, event: str, date_iso: str) -> _Handle:
        d = self._root / source / event
        d.mkdir(parents=True, exist_ok=True)
        final_path = d / f"{date_iso}.jsonl"
        partial = d / f"{date_iso}.jsonl.partial"
        fp = open(partial, "ab", buffering=0)
        return _Handle(partial, final_path, fp)

    def _finalise(self, h: _Handle) -> None:
        try:
            os.fsync(h.fp.fileno())
        except OSError:
            pass
        h.fp.close()
        if h.path.exists():
            if h.final_path.exists():
                with h.path.open("rb") as src, h.final_path.open("ab") as dst:
                    dst.write(src.read())
                h.path.unlink()
            else:
                os.replace(h.path, h.final_path)

    def write(self, source: str, event: str, record: dict) -> None:
        ts_ms = record.get("ts_local_ms") or self._wall_ms()
        date_iso = _date_iso(ts_ms)
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

        with self._lock:
            key = (source, event)
            cur_date = self._date_for.get(key)
            h = self._handles.get(key)
            if h is None or cur_date != date_iso:
                if h is not None:
                    self._finalise(h)
                h = self._open(source, event, date_iso)
                self._handles[key] = h
                self._date_for[key] = date_iso

            h.fp.write(line)
            h.bytes_written += len(line)

            now_ms = self._wall_ms()
            if now_ms - h.last_fsync_ms >= self._fsync_interval_ms:
                try:
                    os.fsync(h.fp.fileno())
                except OSError:
                    pass
                h.last_fsync_ms = now_ms

    def flush(self) -> None:
        with self._lock:
            for h in self._handles.values():
                try:
                    os.fsync(h.fp.fileno())
                except OSError:
                    pass

    def close(self) -> None:
        with self._lock:
            for h in self._handles.values():
                self._finalise(h)
            self._handles.clear()
            self._date_for.clear()
