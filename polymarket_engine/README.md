# Polymarket Anomaly Engine (MVP)

A 24/7 market-microstructure collector + latency-arb detector that watches
Polymarket BTC/ETH price-target markets alongside Binance USDT-perps and
emits a daily markdown report.

## Components

- `collectors/` — Gamma REST market discovery + public CLOB WS + Binance combined-stream WS
- `storage/` — daily-rotated JSONL writer + nightly Parquet rollup
- `detectors/latency_arb.py` — only detector in MVP (lognormal mapping, divergence + persistence + cooldown)
- `report/daily_report.py` — markdown report generator (top-10, lag histogram, per-market table, leaderboard)
- `runtime.py` — asyncio orchestrator
- `cli.py` — `python -m polymarket_engine.cli {discover,collect,report,rollup}`
- `tools.py` — exposes `pm_anomaly_status` and `pm_daily_report` to HydraBot

## Process model

The collector runs as a **separate process** from the chat bot — `python -m
polymarket_engine.cli collect` under tmux/systemd. The HydraBot tools read
the heartbeat file and JSONL files from disk; no IPC. This keeps the 24/7
WebSocket from being affected by chat-bot restarts.

## Configure

Add a `polymarket_engine` block to `config.json`:

```json
"polymarket_engine": {
  "data_dir": "data",
  "heartbeat_path": "data/heartbeat.json",
  "underlyings": ["BTCUSDT", "ETHUSDT"],
  "edge_threshold_bps": 500,
  "min_persist_ms": 2000,
  "cooldown_ms": 15000,
  "max_pm_spread": 0.10,
  "min_ttm_hours": 1.0,
  "vol_window_min": 60,
  "report_time_utc": "00:30",
  "max_markets": 60
}
```

All keys are optional — defaults live in `polymarket_engine/config.py`.

## Run

```bash
# 1. discover BTC/ETH price-target markets (sanity check)
python -m polymarket_engine.cli discover

# 2. start the 24/7 collector (Ctrl-C to stop)
python -m polymarket_engine.cli collect

# 3. (next morning) render yesterday's report
python -m polymarket_engine.cli report

# 4. (nightly cron) roll yesterday's JSONL into Parquet
python -m polymarket_engine.cli rollup
```

## Auto-daily report (optional)

The MVP does not auto-register a daily scheduler job (no canonical "admin
chat" exists). To get an automatic daily report posted to your chat, use
HydraBot's existing scheduler from inside the chat:

```
/remind 00:30 daily run pm_daily_report
```

Or call the tool ad-hoc with `pm_daily_report` (defaults to yesterday's
UTC date) or `pm_daily_report date=2026-05-03`.

## Out of scope for this PR

Replay/backtest engine, scoring, additional detectors (spread anomaly,
panic flow, liquidity vacuum, mispricing), live order placement,
authenticated CLOB endpoints, Hyperliquid integration, real-time
push-on-each-anomaly. See the parent plan for the follow-up roadmap.
