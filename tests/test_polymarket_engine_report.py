"""Offline tests for daily report rendering + Parquet rollup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from polymarket_engine.report.daily_report import render_markdown
from polymarket_engine.storage.parquet_rollup import rollup_all


def _write_anomalies(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_report_empty_day(tmp_path):
    md, out = render_markdown("2026-05-01", tmp_path / "anomalies", tmp_path / "reports")
    assert "No anomalies" in md
    assert out is not None and out.exists()


def test_report_renders_top10_and_histogram(tmp_path):
    rows = [
        {
            "market": f"M{i % 3}",
            "underlying": "BTCUSDT",
            "strike": 65000,
            "edge_bps": 600 + i * 10,
            "lag_ms": (-1500 if i % 2 else 800),
            "duration_ms": 3000 + i * 100,
            "implied_prob_pm": 0.40,
            "implied_prob_bn": 0.55,
        }
        for i in range(15)
    ]
    _write_anomalies(tmp_path / "anomalies" / "2026-05-01.jsonl", rows)
    md, out = render_markdown("2026-05-01", tmp_path / "anomalies", tmp_path / "reports")
    assert "Top 10" in md
    assert "Lag histogram" in md
    assert "Per-market summary" in md
    assert "leaderboard" in md.lower()
    # Histogram bins must show counts
    assert "(-2s, -500ms]" in md
    assert out is not None and out.exists()


def test_report_uses_partial_when_final_missing(tmp_path):
    _write_anomalies(
        tmp_path / "anomalies" / "2026-05-01.jsonl.partial",
        [{"market": "M1", "underlying": "BTCUSDT", "strike": 65000, "edge_bps": 700, "lag_ms": -300, "duration_ms": 2000, "implied_prob_pm": 0.4, "implied_prob_bn": 0.5}],
    )
    md, _ = render_markdown("2026-05-01", tmp_path / "anomalies", tmp_path / "reports")
    assert "Total anomalies:** 1" in md


# ─── Parquet rollup ───────────────────────────────────────────


def test_rollup_converts_finalised_jsonl(tmp_path):
    raw = tmp_path / "raw" / "binance_perp" / "bookTicker"
    raw.mkdir(parents=True)
    f = raw / "2024-05-01.jsonl"
    f.write_text(
        json.dumps({"ts_local_ms": 1714521600000, "symbol": "BTCUSDT", "bid": "63421.10", "ask": "63421.20"}) + "\n"
        + json.dumps({"ts_local_ms": 1714521600100, "symbol": "BTCUSDT", "bid": "63421.20", "ask": "63421.30"}) + "\n",
        encoding="utf-8",
    )
    written = rollup_all(tmp_path / "raw", tmp_path / "parquet", today_iso="2026-05-06")
    assert len(written) == 1
    pq_path = written[0]
    assert pq_path.exists()
    table = pq.read_table(pq_path)
    assert table.num_rows == 2
    assert "bid" in table.column_names


def test_rollup_skips_today(tmp_path):
    raw = tmp_path / "raw" / "src" / "ev"
    raw.mkdir(parents=True)
    today = "2026-05-06"
    (raw / f"{today}.jsonl").write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
    written = rollup_all(tmp_path / "raw", tmp_path / "parquet", today_iso=today)
    assert written == []


def test_rollup_idempotent(tmp_path):
    raw = tmp_path / "raw" / "src" / "ev"
    raw.mkdir(parents=True)
    (raw / "2024-05-01.jsonl").write_text(json.dumps({"x": 1, "ts_local_ms": 1714521600000}) + "\n", encoding="utf-8")
    w1 = rollup_all(tmp_path / "raw", tmp_path / "parquet", today_iso="2026-05-06")
    w2 = rollup_all(tmp_path / "raw", tmp_path / "parquet", today_iso="2026-05-06")
    assert len(w1) == 1
    assert w1 == w2
