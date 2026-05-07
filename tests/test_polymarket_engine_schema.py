"""Offline tests for the JSONL writer + collector normalisers."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from polymarket_engine.collectors.binance_ws import BinanceCollector, build_combined_url
from polymarket_engine.collectors.gamma_rest import parse_market
from polymarket_engine.collectors.polymarket_ws import PolymarketCollector, _to_ms
from polymarket_engine.storage.jsonl_writer import JsonlWriter


# ─── JsonlWriter ──────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_writer_creates_partition_per_source_event(tmp_path):
    w = JsonlWriter(tmp_path)
    w.write("polymarket_clob", "book", {"ts_local_ms": 1714521600000, "x": 1})
    w.write("binance_perp", "bookTicker", {"ts_local_ms": 1714521600000, "y": 2})
    w.close()

    pm_files = list((tmp_path / "polymarket_clob" / "book").glob("*.jsonl"))
    bn_files = list((tmp_path / "binance_perp" / "bookTicker").glob("*.jsonl"))
    assert len(pm_files) == 1
    assert len(bn_files) == 1
    assert pm_files[0].name == "2024-05-01.jsonl"
    assert _read_jsonl(pm_files[0])[0]["x"] == 1


def test_writer_rotates_across_utc_midnight(tmp_path):
    w = JsonlWriter(tmp_path)
    before_midnight = 1714521599000
    after_midnight = 1714521600000
    w.write("s", "e", {"ts_local_ms": before_midnight, "n": 1})
    w.write("s", "e", {"ts_local_ms": after_midnight, "n": 2})
    w.close()

    files = sorted((tmp_path / "s" / "e").glob("*.jsonl"))
    assert [f.name for f in files] == ["2024-04-30.jsonl", "2024-05-01.jsonl"]
    assert _read_jsonl(files[0])[0]["n"] == 1
    assert _read_jsonl(files[1])[0]["n"] == 2


def test_writer_renames_partial_to_final_on_close(tmp_path):
    w = JsonlWriter(tmp_path)
    w.write("s", "e", {"ts_local_ms": 1714521600000, "n": 1})
    partial = tmp_path / "s" / "e" / "2024-05-01.jsonl.partial"
    assert partial.exists()
    w.close()
    assert not partial.exists()
    assert (tmp_path / "s" / "e" / "2024-05-01.jsonl").exists()


def test_writer_fsync_throttled(tmp_path):
    fake_now = [1000.0]
    w = JsonlWriter(tmp_path, fsync_interval_sec=5, now_fn=lambda: fake_now[0])
    with mock.patch("polymarket_engine.storage.jsonl_writer.os.fsync") as fsync:
        w.write("s", "e", {"ts_local_ms": int(fake_now[0] * 1000), "n": 1})
        fake_now[0] += 1.0
        w.write("s", "e", {"ts_local_ms": int(fake_now[0] * 1000), "n": 2})
        fake_now[0] += 1.0
        w.write("s", "e", {"ts_local_ms": int(fake_now[0] * 1000), "n": 3})
        within = fsync.call_count
        fake_now[0] += 10.0
        w.write("s", "e", {"ts_local_ms": int(fake_now[0] * 1000), "n": 4})
        after_threshold = fsync.call_count
    w.close()
    assert within <= 1
    assert after_threshold > within


# ─── Polymarket WS normaliser ─────────────────────────────────


def _pm_collector():
    asset_index = {"71": ("yes", "M1"), "99": ("no", "M1")}
    return PolymarketCollector("wss://x", asset_index, on_event=lambda e: None)


def test_pm_book_event_normalisation():
    c = _pm_collector()
    payload = {
        "event_type": "book",
        "asset_id": "71",
        "market": "M1",
        "timestamp": "1714521600123",
        "bids": [{"price": "0.42", "size": "1500"}],
        "asks": [{"price": "0.43", "size": "800"}],
        "hash": "abc",
    }
    out = list(c._normalise(payload))
    assert len(out) == 1
    e = out[0]
    assert e["source"] == "polymarket_clob"
    assert e["event"] == "book"
    assert e["asset_id"] == "71"
    assert e["side"] == "yes"
    assert e["market"] == "M1"
    assert e["bids"] == payload["bids"]
    assert e["ts_exchange_ms"] == 1714521600123
    assert "ts_local_ms" in e


def test_pm_price_change_normalisation():
    c = _pm_collector()
    payload = {
        "event_type": "price_change",
        "asset_id": "99",
        "market": "M1",
        "timestamp": 1714521600,
        "changes": [{"price": "0.50", "side": "BUY", "size": "100"}],
    }
    e = list(c._normalise(payload))[0]
    assert e["event"] == "price_change"
    assert e["side"] == "no"
    assert e["changes"][0]["price"] == "0.50"
    assert e["ts_exchange_ms"] == 1714521600 * 1000


def test_pm_unknown_asset_marked_unknown():
    c = _pm_collector()
    payload = {"event_type": "book", "asset_id": "ZZZ", "bids": [], "asks": []}
    e = list(c._normalise(payload))[0]
    assert e["side"] == "unknown"


def test_pm_list_payload_handled():
    c = _pm_collector()
    payload = [
        {"event_type": "book", "asset_id": "71", "bids": [], "asks": []},
        {"event_type": "last_trade_price", "asset_id": "71", "price": "0.42", "size": "10", "side": "BUY"},
    ]
    events = list(c._normalise(payload))
    assert len(events) == 2
    assert events[1]["price"] == "0.42"


def test_to_ms_seconds_vs_millis():
    assert _to_ms(1714521600) == 1714521600000
    assert _to_ms(1714521600123) == 1714521600123
    assert _to_ms(None) is None
    assert _to_ms("1714521600123") == 1714521600123


# ─── Binance WS normaliser ────────────────────────────────────


def test_binance_book_ticker_normalisation():
    c = BinanceCollector("wss://fstream.binance.com/stream", ["BTCUSDT"], on_event=lambda e: None)
    payload = {
        "stream": "btcusdt@bookTicker",
        "data": {
            "e": "bookTicker",
            "u": 12345,
            "s": "BTCUSDT",
            "b": "63421.10",
            "B": "1.234",
            "a": "63421.20",
            "A": "0.987",
            "T": 1714521600100,
            "E": 1714521600110,
        },
    }
    e = list(c._normalise(payload))[0]
    assert e["source"] == "binance_perp"
    assert e["event"] == "bookTicker"
    assert e["symbol"] == "BTCUSDT"
    assert e["bid"] == "63421.10"
    assert e["ask"] == "63421.20"
    assert e["ts_exchange_ms"] == 1714521600110


def test_binance_agg_trade_normalisation():
    c = BinanceCollector("wss://x", ["BTCUSDT"], on_event=lambda e: None)
    payload = {
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "s": "BTCUSDT", "p": "63420.5", "q": "0.05", "m": False, "T": 1714521600200, "a": 9},
    }
    e = list(c._normalise(payload))[0]
    assert e["event"] == "aggTrade"
    assert e["price"] == "63420.5"
    assert e["buyer_maker"] is False
    assert e["ts_exchange_ms"] == 1714521600200


def test_binance_mark_price_normalisation():
    c = BinanceCollector("wss://x", ["BTCUSDT"], on_event=lambda e: None)
    payload = {
        "stream": "btcusdt@markPrice@1s",
        "data": {"e": "markPriceUpdate", "s": "BTCUSDT", "p": "63420.5", "i": "63419.8", "r": "0.0001", "T": 1714521700000, "E": 1714521600000},
    }
    e = list(c._normalise(payload))[0]
    assert e["event"] == "markPrice"
    assert e["mark"] == "63420.5"
    assert e["funding_rate"] == "0.0001"


def test_combined_url_builder():
    url = build_combined_url("wss://fstream.binance.com/stream", ["BTCUSDT", "ETHUSDT"])
    for s in ("btcusdt@bookTicker", "btcusdt@aggTrade", "btcusdt@markPrice@1s",
              "ethusdt@bookTicker", "ethusdt@aggTrade", "ethusdt@markPrice@1s"):
        assert s in url


# ─── Gamma market parsing ─────────────────────────────────────


def test_gamma_parse_btc_above_strike():
    raw = {
        "id": "abc",
        "conditionId": "0xabc",
        "question": "Will Bitcoin reach $100,000 by May 9, 2026?",
        "end_date_iso": "2026-05-09T23:59:00Z",
        "clobTokenIds": json.dumps(["71321", "99845"]),
    }
    m = parse_market(raw)
    assert m is not None
    assert m.underlying == "BTCUSDT"
    assert m.strike == 100000.0
    assert m.direction == "above"
    assert m.yes_token_id == "71321"
    assert m.no_token_id == "99845"


def test_gamma_parse_eth_below_strike():
    raw = {
        "conditionId": "0xeth",
        "question": "Will Ethereum close below $2,500 on June 1, 2026?",
        "end_date_iso": "2026-06-01T23:59:00Z",
        "clobTokenIds": ["a", "b"],
    }
    m = parse_market(raw)
    assert m is not None
    assert m.underlying == "ETHUSDT"
    assert m.direction == "below"
    assert m.strike == 2500.0


def test_gamma_skips_non_price_market():
    raw = {
        "conditionId": "0x1",
        "question": "Will Donald Trump win the 2024 election?",
        "end_date_iso": "2026-11-04T23:59:00Z",
        "clobTokenIds": ["a", "b"],
    }
    assert parse_market(raw) is None


def test_gamma_skips_market_without_strike():
    raw = {
        "conditionId": "0x2",
        "question": "Will Bitcoin reach a new ATH this year?",
        "end_date_iso": "2026-12-31T23:59:00Z",
        "clobTokenIds": ["a", "b"],
    }
    assert parse_market(raw) is None


def test_gamma_skips_market_without_clob_tokens():
    raw = {
        "conditionId": "0x3",
        "question": "Will Bitcoin reach $100,000 by May 9, 2026?",
        "end_date_iso": "2026-05-09T23:59:00Z",
        "clobTokenIds": "",
    }
    assert parse_market(raw) is None
