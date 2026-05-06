"""HydraBot dynamic-tool entrypoint for the Polymarket anomaly engine.

Two read-only tools, both safe to call from chat:
  - pm_anomaly_status: collector heartbeat (last event ts, anomaly count)
  - pm_daily_report:   markdown report for a UTC date (default: yesterday)

Imports are intentionally light — only stdlib + pyarrow (via the report
module via parquet_rollup). Heavy collector deps (websockets, aiohttp) are
NOT imported here so the tools work even when the optional collector deps
aren't installed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_from_env
from .report.daily_report import render_markdown


def _read_heartbeat(path: Path | str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"error": "heartbeat file not found", "path": str(p)}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e), "path": str(p)}


def get_tools():
    def pm_anomaly_status() -> str:
        cfg = load_from_env()
        h = _read_heartbeat(cfg.heartbeat_path)
        return "```json\n" + json.dumps(h, indent=2, ensure_ascii=False) + "\n```"

    def pm_daily_report(date: str | None = None) -> str:
        cfg = load_from_env()
        if not date:
            date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        md, _ = render_markdown(
            date,
            cfg.jsonl_root() / "anomalies",
            cfg.data_dir.parent / "reports",
        )
        return md

    return [
        (
            "pm_anomaly_status",
            {
                "name": "pm_anomaly_status",
                "description": "Polymarket anomaly engine collector health: active markets, last event timestamps per source, anomalies-today count, realised-vol estimates.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            pm_anomaly_status,
        ),
        (
            "pm_daily_report",
            {
                "name": "pm_daily_report",
                "description": "Markdown daily report of Polymarket↔Binance latency-arb anomalies for the given UTC date (YYYY-MM-DD; default: yesterday).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "UTC date in YYYY-MM-DD format. Omit to get yesterday's report."}
                    },
                    "required": [],
                },
            },
            pm_daily_report,
        ),
    ]
