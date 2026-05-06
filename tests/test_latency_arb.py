"""Offline tests for the latency-arb detector."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from polymarket_engine.collectors.binance_ws import RealisedVolTracker
from polymarket_engine.collectors.gamma_rest import Market
from polymarket_engine.detectors.latency_arb import (
    LatencyArbDetector,
    lognormal_prob_above,
)


def test_lognormal_at_strike_is_half():
    # With sigma=0.2 and ttm=30d, drift correction d2 = -0.5*0.2*sqrt(30/365)
    # ≈ -0.029 → Φ(d2) ≈ 0.489. Tolerance 0.02 covers this.
    p = lognormal_prob_above(S=65000, K=65000, sigma=0.2, ttm_years=30 / 365)
    assert abs(p - 0.5) < 0.02


def test_lognormal_above_strike_increases():
    p_lo = lognormal_prob_above(S=64000, K=65000, sigma=0.5, ttm_years=30 / 365)
    p_hi = lognormal_prob_above(S=66000, K=65000, sigma=0.5, ttm_years=30 / 365)
    assert p_lo < 0.5 < p_hi


def test_lognormal_zero_ttm_is_step():
    assert lognormal_prob_above(S=66000, K=65000, sigma=0.5, ttm_years=0.0) == 1.0
    assert lognormal_prob_above(S=64000, K=65000, sigma=0.5, ttm_years=0.0) == 0.0


def _market(end_ts_ms: int) -> Market:
    return Market(
        market_id="M1",
        question="Will Bitcoin reach $65,000 by date?",
        underlying="BTCUSDT",
        strike=65000.0,
        direction="above",
        end_iso="2026-06-01T00:00:00Z",
        end_ts_ms=end_ts_ms,
        yes_token_id="YES",
        no_token_id="NO",
    )


def _book_event(asset_id: str, bids, asks, ts_ms: int) -> dict:
    return {
        "ts_local_ms": ts_ms,
        "ts_exchange_ms": ts_ms,
        "source": "polymarket_clob",
        "event": "book",
        "asset_id": asset_id,
        "market": "M1",
        "side": "yes",
        "bids": bids,
        "asks": asks,
    }


def _bn_event(symbol: str, bid: float, ask: float, ts_ms: int) -> dict:
    return {
        "ts_local_ms": ts_ms,
        "ts_exchange_ms": ts_ms,
        "source": "binance_perp",
        "event": "bookTicker",
        "symbol": symbol,
        "bid": str(bid),
        "ask": str(ask),
    }


def _make_detector(threshold_bps=500, min_persist_ms=2000, cooldown_ms=15000,
                   max_pm_spread=0.10, min_ttm_hours=1.0, sigma=0.5):
    d = LatencyArbDetector(
        vol_provider=lambda s: sigma,
        threshold_bps=threshold_bps,
        min_persist_ms=min_persist_ms,
        cooldown_ms=cooldown_ms,
        max_pm_spread=max_pm_spread,
        min_ttm_hours=min_ttm_hours,
    )
    end_ts_ms = 0  # filled per test
    return d


def test_emits_anomaly_after_persistence_window():
    d = _make_detector()
    end = 1714521600000 + 30 * 86400 * 1000  # 30 days out
    d.on_market_metadata([_market(end)])

    # PM at 0.40 (yes mid), Binance well above strike → p_bn ≫ 0.40
    t = 1714521600000
    list(d.on_event(_book_event("YES", [["0.39", "100"]], [["0.41", "100"]], t)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t)))

    # First trigger event: starts the persistence timer, emits nothing yet
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.2, 80000.3, t + 100)))
    assert out == []

    # Still within persist window
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.3, 80000.4, t + 1500)))
    assert out == []

    # Beyond persist window → emit
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.4, 80000.5, t + 3000)))
    assert len(out) == 1
    a = out[0]
    assert a["source"] == "detector_latency_arb"
    assert a["market"] == "M1"
    assert a["edge_bps"] > 0  # PM lagging up
    assert a["duration_ms"] >= 2000


def test_cooldown_suppresses_repeated_emissions():
    d = _make_detector(cooldown_ms=15000)
    end = 1714521600000 + 30 * 86400 * 1000
    d.on_market_metadata([_market(end)])
    t = 1714521600000
    list(d.on_event(_book_event("YES", [["0.39", "100"]], [["0.41", "100"]], t)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.1, 80000.2, t + 100)))
    first = list(d.on_event(_bn_event("BTCUSDT", 80000.2, 80000.3, t + 3000)))
    assert len(first) == 1
    # Within cooldown → no second emit
    second = list(d.on_event(_bn_event("BTCUSDT", 80000.3, 80000.4, t + 5000)))
    assert second == []
    # After cooldown elapses → emit again
    third = list(d.on_event(_bn_event("BTCUSDT", 80000.4, 80000.5, t + 3000 + 16000)))
    assert len(third) == 1


def test_skips_when_pm_spread_is_wide():
    d = _make_detector(max_pm_spread=0.10)
    end = 1714521600000 + 30 * 86400 * 1000
    d.on_market_metadata([_market(end)])
    t = 1714521600000
    # Very wide spread: 0.30 / 0.55 → 0.25 > max
    list(d.on_event(_book_event("YES", [["0.30", "100"]], [["0.55", "100"]], t)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t)))
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.1, 80000.2, t + 5000)))
    assert out == []


def test_skips_when_ttm_below_threshold():
    d = _make_detector(min_ttm_hours=1.0)
    # Settlement 30 minutes from now → ttm < 1h
    t = 1714521600000
    end = t + 30 * 60 * 1000
    d.on_market_metadata([_market(end)])
    list(d.on_event(_book_event("YES", [["0.39", "100"]], [["0.41", "100"]], t)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t)))
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.1, 80000.2, t + 5000)))
    assert out == []


def test_skips_when_no_market_metadata():
    d = _make_detector()
    # No on_market_metadata called → asset_id won't match
    t = 1714521600000
    out = list(d.on_event(_book_event("YES", [["0.39", "100"]], [["0.41", "100"]], t)))
    out += list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t + 5000)))
    assert out == []


def test_below_threshold_does_not_emit():
    d = _make_detector(threshold_bps=10000)  # impossibly high
    end = 1714521600000 + 30 * 86400 * 1000
    d.on_market_metadata([_market(end)])
    t = 1714521600000
    list(d.on_event(_book_event("YES", [["0.49", "100"]], [["0.51", "100"]], t)))
    out = list(d.on_event(_bn_event("BTCUSDT", 65000.0, 65000.1, t + 5000)))
    assert out == []


def test_book_apply_changes_via_price_change():
    d = _make_detector()
    end = 1714521600000 + 30 * 86400 * 1000
    d.on_market_metadata([_market(end)])
    t = 1714521600000
    # Init with a snapshot
    list(d.on_event(_book_event("YES", [["0.50", "100"]], [["0.52", "100"]], t)))
    list(d.on_event(_bn_event("BTCUSDT", 65000.0, 65000.1, t)))
    # Apply a price_change that lifts the bid to 0.39 and ask to 0.41 by removing old + adding
    delta = {
        "ts_local_ms": t + 100,
        "ts_exchange_ms": t + 100,
        "source": "polymarket_clob",
        "event": "price_change",
        "asset_id": "YES",
        "market": "M1",
        "side": "yes",
        "changes": [
            {"price": "0.50", "side": "BUY", "size": "0"},
            {"price": "0.52", "side": "SELL", "size": "0"},
            {"price": "0.39", "side": "BUY", "size": "100"},
            {"price": "0.41", "side": "SELL", "size": "100"},
        ],
    }
    list(d.on_event(delta))
    list(d.on_event(_bn_event("BTCUSDT", 80000.0, 80000.1, t + 200)))
    list(d.on_event(_bn_event("BTCUSDT", 80000.1, 80000.2, t + 300)))
    out = list(d.on_event(_bn_event("BTCUSDT", 80000.2, 80000.3, t + 3000)))
    assert len(out) == 1
    assert out[0]["pm_top"]["bid"] == 0.39
    assert out[0]["pm_top"]["ask"] == 0.41


# ─── Realised vol tracker ─────────────────────────────────────


def test_realised_vol_default_when_cold():
    v = RealisedVolTracker(window_min=60, default_vol=0.55)
    assert v.sigma_annual() == 0.55
    v.push(1714521600000, 65000.0)
    assert v.sigma_annual() == 0.55


def test_realised_vol_responds_to_returns():
    v = RealisedVolTracker(window_min=60, default_vol=0.55)
    base = 1714521600000
    # Inject 200 samples with small but consistent log-returns
    price = 65000.0
    for i in range(200):
        price *= math.exp(0.0001 * (1 if i % 2 == 0 else -1))
        v.push(base + i * 1000, price)  # 1 per second
    sigma = v.sigma_annual()
    # Annualised from 1Hz sampling at sd ≈ 0.0001 → about 0.0001 * sqrt(31.5e6) ≈ 0.56
    assert 0.1 < sigma < 5.0
