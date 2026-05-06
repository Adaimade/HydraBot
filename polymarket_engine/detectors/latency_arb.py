"""Latency-arb detector — Polymarket YES vs Binance perp implied probability.

Maintains a per-market top-of-book on the Polymarket side (initialised from
`book` snapshots, mutated by `price_change` deltas) and a per-symbol top-of
-book on the Binance side. On each update, recomputes:

    p_pm = (best_bid + best_ask) / 2                         (PM YES mid)
    p_bn = lognormal_prob_above(S, K, sigma, ttm)            (model)

A divergence > `threshold_bps` that persists > `min_persist_ms` emits an
anomaly record (cooldown'd per market). Skip rules: wide PM spread,
near-expiry markets, missing top-of-book.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .base import AbstractDetector


def lognormal_prob_above(S: float, K: float, sigma: float, ttm_years: float, r: float = 0.0) -> float:
    """P(S_T > K) under GBM with drift r and vol sigma."""
    if ttm_years <= 0:
        return 1.0 if S > K else (0.5 if S == K else 0.0)
    if sigma <= 0 or S <= 0 or K <= 0:
        return 0.5
    d2 = (math.log(S / K) + (r - 0.5 * sigma * sigma) * ttm_years) / (sigma * math.sqrt(ttm_years))
    return 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))


@dataclass
class _PMBook:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_event_ts_ex: int = 0
    last_event_ts_local: int = 0

    def apply_snapshot(self, bids: list, asks: list) -> None:
        self.bids = _parse_levels(bids)
        self.asks = _parse_levels(asks)

    def apply_changes(self, changes: list) -> None:
        for c in changes:
            try:
                price = float(c.get("price"))
                size = float(c.get("size"))
            except (TypeError, ValueError):
                continue
            side = (c.get("side") or "").upper()
            book = self.bids if side == "BUY" else self.asks if side == "SELL" else None
            if book is None:
                continue
            if size <= 0:
                book.pop(price, None)
            else:
                book[price] = size

    def top(self) -> tuple[float, float] | None:
        if not self.bids or not self.asks:
            return None
        return max(self.bids), min(self.asks)


def _pair(x):
    if isinstance(x, dict):
        return x.get("price"), x.get("size")
    if isinstance(x, (list, tuple)) and len(x) >= 2:
        return x[0], x[1]
    return None, None


def _parse_levels(items: list) -> dict[float, float]:
    out: dict[float, float] = {}
    for x in items:
        p, s = _pair(x)
        if p is None or s is None:
            continue
        try:
            ps, ss = float(p), float(s)
        except (TypeError, ValueError):
            continue
        if ss > 0:
            out[ps] = ss
    return out


@dataclass
class _BNTop:
    bid: float = 0.0
    ask: float = 0.0
    last_ts_ex: int = 0
    last_ts_local: int = 0

    def mid(self) -> float | None:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return None


@dataclass
class _Market:
    market_id: str
    underlying: str
    strike: float
    direction: str
    end_ts_ms: int
    yes_token_id: str
    no_token_id: str


@dataclass
class _DivergenceState:
    started_at_ms: int = 0
    bn_threshold_ts_ex: int = 0
    last_emit_ms: int = 0
    last_sign: int = 0


class LatencyArbDetector(AbstractDetector):
    name = "latency_arb_v1"

    def __init__(
        self,
        vol_provider: Callable[[str], float],
        threshold_bps: int = 500,
        min_persist_ms: int = 2000,
        cooldown_ms: int = 15000,
        max_pm_spread: float = 0.10,
        min_ttm_hours: float = 1.0,
    ):
        self._vol = vol_provider
        self._threshold_bps = threshold_bps
        self._min_persist_ms = min_persist_ms
        self._cooldown_ms = cooldown_ms
        self._max_pm_spread = max_pm_spread
        self._min_ttm_hours = min_ttm_hours

        self._markets_by_yes_token: dict[str, _Market] = {}
        self._markets_by_id: dict[str, _Market] = {}
        self._pm_books: dict[str, _PMBook] = {}
        self._bn_tops: dict[str, _BNTop] = {}
        self._div_state: dict[str, _DivergenceState] = {}

    def on_market_metadata(self, markets) -> None:
        self._markets_by_yes_token.clear()
        self._markets_by_id.clear()
        for m in markets:
            mm = _Market(
                market_id=m.market_id,
                underlying=m.underlying,
                strike=float(m.strike),
                direction=m.direction,
                end_ts_ms=int(m.end_ts_ms),
                yes_token_id=m.yes_token_id,
                no_token_id=m.no_token_id,
            )
            self._markets_by_yes_token[m.yes_token_id] = mm
            self._markets_by_id[m.market_id] = mm
            self._pm_books.setdefault(m.yes_token_id, _PMBook())
            self._div_state.setdefault(m.market_id, _DivergenceState())

    def on_event(self, event: dict) -> Iterable[dict]:
        src = event.get("source")
        ev = event.get("event")
        if src == "polymarket_clob":
            return self._on_pm(event, ev)
        if src == "binance_perp" and ev == "bookTicker":
            return self._on_bn(event)
        return ()

    def _on_pm(self, event: dict, ev: str) -> Iterable[dict]:
        token = event.get("asset_id")
        market = self._markets_by_yes_token.get(token)
        if market is None:
            return ()
        book = self._pm_books.setdefault(token, _PMBook())
        if ev == "book":
            book.apply_snapshot(event.get("bids") or [], event.get("asks") or [])
        elif ev == "price_change":
            book.apply_changes(event.get("changes") or [])
        else:
            return ()
        book.last_event_ts_ex = int(event.get("ts_exchange_ms") or 0)
        book.last_event_ts_local = int(event.get("ts_local_ms") or 0)
        return self._evaluate(market, book.last_event_ts_local)

    def _on_bn(self, event: dict) -> Iterable[dict]:
        sym = event.get("symbol")
        if not sym:
            return ()
        try:
            bid = float(event.get("bid") or 0.0)
            ask = float(event.get("ask") or 0.0)
        except (TypeError, ValueError):
            return ()
        top = self._bn_tops.setdefault(sym, _BNTop())
        top.bid = bid
        top.ask = ask
        top.last_ts_ex = int(event.get("ts_exchange_ms") or 0)
        top.last_ts_local = int(event.get("ts_local_ms") or 0)
        out: list[dict] = []
        for m in self._markets_by_id.values():
            if m.underlying != sym:
                continue
            out.extend(self._evaluate(m, top.last_ts_local))
        return out

    def _evaluate(self, market: _Market, now_ms: int) -> list[dict]:
        book = self._pm_books.get(market.yes_token_id)
        bn = self._bn_tops.get(market.underlying)
        if book is None or bn is None:
            return []
        top = book.top()
        bn_mid = bn.mid()
        if top is None or bn_mid is None:
            return []

        pm_bid, pm_ask = top
        spread = pm_ask - pm_bid
        if spread > self._max_pm_spread or spread < 0:
            self._reset(market.market_id)
            return []

        ttm_years = max(0.0, (market.end_ts_ms - now_ms) / 1000.0 / (365.0 * 86400.0))
        if ttm_years < (self._min_ttm_hours / 8760.0):
            self._reset(market.market_id)
            return []

        sigma = self._vol(market.underlying)
        p_pm = (pm_bid + pm_ask) / 2.0
        p_bn_above = lognormal_prob_above(bn_mid, market.strike, sigma, ttm_years)
        p_bn = p_bn_above if market.direction == "above" else (1.0 - p_bn_above)

        edge = p_bn - p_pm
        edge_bps = int(round(edge * 10_000))
        sign = 1 if edge > 0 else (-1 if edge < 0 else 0)

        st = self._div_state.setdefault(market.market_id, _DivergenceState())

        if abs(edge_bps) < self._threshold_bps or sign == 0:
            st.started_at_ms = 0
            st.last_sign = 0
            return []

        if st.started_at_ms == 0 or st.last_sign != sign:
            st.started_at_ms = now_ms
            st.last_sign = sign
            st.bn_threshold_ts_ex = bn.last_ts_ex
            return []

        if now_ms - st.started_at_ms < self._min_persist_ms:
            return []

        if st.last_emit_ms and (now_ms - st.last_emit_ms) < self._cooldown_ms:
            return []

        st.last_emit_ms = now_ms

        lag_ms = book.last_event_ts_ex - st.bn_threshold_ts_ex
        direction = (
            "PM_LAGGING_UP" if (sign > 0 and lag_ms >= 0)
            else "PM_LAGGING_DOWN" if (sign < 0 and lag_ms >= 0)
            else "PM_LEADING"
        )

        return [{
            "ts_local_ms": now_ms,
            "ts_exchange_ms": now_ms,
            "source": "detector_latency_arb",
            "event": "anomaly",
            "detector": self.name,
            "market": market.market_id,
            "asset_id": market.yes_token_id,
            "yes_or_no": "yes",
            "underlying": market.underlying,
            "implied_prob_pm": round(p_pm, 6),
            "implied_prob_bn": round(p_bn, 6),
            "edge_bps": edge_bps,
            "lag_ms": lag_ms,
            "direction": direction,
            "duration_ms": now_ms - st.started_at_ms,
            "pm_top": {"bid": pm_bid, "ask": pm_ask, "mid": p_pm},
            "bn_top": {"bid": bn.bid, "ask": bn.ask, "mid": bn_mid},
            "vol_used": sigma,
            "ttm_years": round(ttm_years, 6),
            "strike": market.strike,
            "threshold_bps": self._threshold_bps,
        }]

    def _reset(self, market_id: str) -> None:
        st = self._div_state.get(market_id)
        if st is not None:
            st.started_at_ms = 0
            st.last_sign = 0
