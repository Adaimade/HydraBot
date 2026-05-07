"""Polymarket public CLOB WebSocket collector (market channel)."""

from __future__ import annotations

import time
from typing import Any, Iterable

from .base import BaseWSCollector


def _to_ms(v: Any) -> int | None:
    if v is None:
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 10_000_000_000 else n * 1000


class PolymarketCollector(BaseWSCollector):
    name = "polymarket_clob"

    def __init__(self, url: str, asset_index: dict[str, tuple[str, str]], on_event):
        super().__init__(url, on_event)
        self._asset_index = dict(asset_index)

    def update_assets(self, asset_index: dict[str, tuple[str, str]]) -> None:
        self._asset_index = dict(asset_index)

    def _subscribe_messages(self) -> list[Any]:
        if not self._asset_index:
            return []
        return [{"type": "market", "assets_ids": list(self._asset_index.keys())}]

    def _normalise(self, payload: Any) -> Iterable[dict]:
        events = payload if isinstance(payload, list) else [payload]
        ts_local = int(time.time() * 1000)
        for raw in events:
            if not isinstance(raw, dict):
                continue
            etype = raw.get("event_type") or raw.get("type")
            if etype not in ("book", "price_change", "last_trade_price", "tick_size_change"):
                continue
            asset_id = str(raw.get("asset_id") or "")
            side_market = self._asset_index.get(asset_id)
            yes_or_no = side_market[0] if side_market else "unknown"
            market = raw.get("market") or (side_market[1] if side_market else "")
            ts_ex = _to_ms(raw.get("timestamp")) or ts_local

            base = {
                "ts_local_ms": ts_local,
                "ts_exchange_ms": ts_ex,
                "source": self.name,
                "event": etype,
                "market": market,
                "asset_id": asset_id,
                "side": yes_or_no,
            }
            if etype == "book":
                base["bids"] = raw.get("bids") or []
                base["asks"] = raw.get("asks") or []
                base["hash"] = raw.get("hash")
            elif etype == "price_change":
                base["changes"] = raw.get("changes") or raw.get("price_changes") or []
            elif etype == "last_trade_price":
                base["price"] = raw.get("price")
                base["size"] = raw.get("size")
                base["trade_side"] = raw.get("side")
                base["fee_rate_bps"] = raw.get("fee_rate_bps")
            elif etype == "tick_size_change":
                base["old_tick_size"] = raw.get("old_tick_size")
                base["new_tick_size"] = raw.get("new_tick_size")
            yield base
