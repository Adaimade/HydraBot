"""Abstract WebSocket collector with reconnect-and-resubscribe."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Callable

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class BaseWSCollector:
    name: str = "base"

    def __init__(
        self,
        url: str,
        on_event: Callable[[dict], None],
        ping_interval: int = 20,
        max_backoff_sec: int = 30,
    ):
        self._url = url
        self._on_event = on_event
        self._ping = ping_interval
        self._max_backoff = max_backoff_sec
        self._stop = asyncio.Event()
        self._connected_at: float | None = None
        self._last_msg_ts: float | None = None
        self._reconnects = 0

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=self._ping,
                    ping_timeout=self._ping * 2,
                    max_size=2 ** 24,
                ) as ws:
                    self._connected_at = time.time()
                    backoff = 1.0
                    logger.info("[%s] connected to %s", self.name, self._url)
                    await self._on_connect(ws)
                    async for raw in ws:
                        self._last_msg_ts = time.time()
                        await self._dispatch(raw)
            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                if self._stop.is_set():
                    return
                self._reconnects += 1
                logger.warning(
                    "[%s] disconnect (%s); reconnecting in %.1fs", self.name, e, backoff
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    return
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2.0, float(self._max_backoff))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[%s] unexpected error", self.name)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, float(self._max_backoff))

    async def stop(self) -> None:
        self._stop.set()

    async def _on_connect(self, ws) -> None:
        msgs = self._subscribe_messages()
        for m in msgs:
            await ws.send(json.dumps(m) if isinstance(m, dict) else m)

    def _subscribe_messages(self) -> list[Any]:
        return []

    async def _dispatch(self, raw) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        for ev in self._normalise(payload):
            try:
                self._on_event(ev)
            except Exception:
                logger.exception("[%s] handler raised", self.name)

    def _normalise(self, payload: Any) -> AsyncIterator[dict]:
        raise NotImplementedError

    def health(self) -> dict:
        return {
            "name": self.name,
            "connected_at": self._connected_at,
            "last_msg_ts": self._last_msg_ts,
            "reconnects": self._reconnects,
        }
