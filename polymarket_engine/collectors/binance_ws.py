"""Binance USDT-margined perp combined-stream collector + realised-vol tracker."""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Iterable

from .base import BaseWSCollector


def build_combined_url(base: str, symbols: list[str]) -> str:
    streams: list[str] = []
    for s in symbols:
        sl = s.lower()
        streams += [f"{sl}@bookTicker", f"{sl}@aggTrade", f"{sl}@markPrice@1s"]
    qs = "/".join(streams)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}streams={qs}"


class BinanceCollector(BaseWSCollector):
    name = "binance_perp"

    def __init__(self, ws_url: str, symbols: list[str], on_event):
        url = build_combined_url(ws_url, symbols)
        super().__init__(url, on_event)
        self._symbols = [s.upper() for s in symbols]

    def _normalise(self, payload: Any) -> Iterable[dict]:
        if not isinstance(payload, dict):
            return
        data = payload.get("data") if "data" in payload else payload
        stream = payload.get("stream", "")
        if not isinstance(data, dict):
            return
        ts_local = int(time.time() * 1000)

        if "@bookTicker" in stream or data.get("e") == "bookTicker" or {"b", "a", "s"} <= set(data.keys()):
            ts_ex = int(data.get("E") or data.get("T") or ts_local)
            yield {
                "ts_local_ms": ts_local,
                "ts_exchange_ms": ts_ex,
                "source": self.name,
                "event": "bookTicker",
                "symbol": data.get("s"),
                "bid": data.get("b"),
                "bid_qty": data.get("B"),
                "ask": data.get("a"),
                "ask_qty": data.get("A"),
                "u": data.get("u"),
            }
        elif "@aggTrade" in stream or data.get("e") == "aggTrade":
            ts_ex = int(data.get("T") or data.get("E") or ts_local)
            yield {
                "ts_local_ms": ts_local,
                "ts_exchange_ms": ts_ex,
                "source": self.name,
                "event": "aggTrade",
                "symbol": data.get("s"),
                "price": data.get("p"),
                "qty": data.get("q"),
                "buyer_maker": bool(data.get("m")),
                "trade_id": data.get("a"),
            }
        elif "@markPrice" in stream or data.get("e") == "markPriceUpdate":
            ts_ex = int(data.get("E") or ts_local)
            yield {
                "ts_local_ms": ts_local,
                "ts_exchange_ms": ts_ex,
                "source": self.name,
                "event": "markPrice",
                "symbol": data.get("s"),
                "mark": data.get("p"),
                "index": data.get("i"),
                "funding_rate": data.get("r"),
                "next_funding_ts": data.get("T"),
            }


class RealisedVolTracker:
    """Annualised realised vol from log-returns of recent trade prices.

    Uses a sliding window (default 60 minutes) of last-prices sampled at
    each aggTrade event. sigma_annual = std(log-returns) * sqrt(N_per_year)
    where N_per_year is derived from observed sample spacing.
    """

    def __init__(self, window_min: int = 60, default_vol: float = 0.55):
        self._window_ms = window_min * 60 * 1000
        self._default = default_vol
        self._prices: deque[tuple[int, float]] = deque()

    def push(self, ts_ms: int, price: float) -> None:
        self._prices.append((ts_ms, price))
        cutoff = ts_ms - self._window_ms
        while self._prices and self._prices[0][0] < cutoff:
            self._prices.popleft()

    def sigma_annual(self) -> float:
        n = len(self._prices)
        if n < 30:
            return self._default
        rets: list[float] = []
        prev = self._prices[0][1]
        for _, p in list(self._prices)[1:]:
            if prev > 0 and p > 0:
                rets.append(math.log(p / prev))
            prev = p
        if len(rets) < 20:
            return self._default
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / max(len(rets) - 1, 1)
        sd = math.sqrt(var)
        first_ts = self._prices[0][0]
        last_ts = self._prices[-1][0]
        elapsed_sec = max((last_ts - first_ts) / 1000.0, 1.0)
        samples_per_year = (len(rets) / elapsed_sec) * 365 * 86400
        sigma = sd * math.sqrt(samples_per_year)
        if not math.isfinite(sigma) or sigma <= 0:
            return self._default
        return min(sigma, 5.0)
