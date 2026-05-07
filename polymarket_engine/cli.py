"""Standalone CLI: discover | collect | report | rollup.

Usage:
    python -m polymarket_engine.cli discover
    python -m polymarket_engine.cli collect
    python -m polymarket_engine.cli report [YYYY-MM-DD]
    python -m polymarket_engine.cli rollup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone

from .collectors.gamma_rest import discover
from .config import load_from_env
from .report.daily_report import render_markdown
from .runtime import Runtime
from .storage.parquet_rollup import rollup_all


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _cmd_discover(args) -> int:
    cfg = load_from_env()
    markets = discover(cfg.gamma_endpoint, cfg.market_filter_max_days, cfg.max_markets)
    out = [m.to_record() for m in markets]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n# {len(markets)} markets matched", file=sys.stderr)
    return 0


def _cmd_collect(args) -> int:
    cfg = load_from_env()
    rt = Runtime(cfg)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _stop(*_):
        loop.call_soon_threadsafe(rt.stop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, _stop)

    try:
        loop.run_until_complete(rt.run())
    finally:
        loop.close()
    return 0


def _cmd_report(args) -> int:
    cfg = load_from_env()
    date = args.date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    md, path = render_markdown(date, cfg.jsonl_root() / "anomalies", cfg.data_dir.parent / "reports")
    print(md)
    print(f"\n# wrote {path}", file=sys.stderr)
    return 0


def _cmd_rollup(args) -> int:
    cfg = load_from_env()
    written = rollup_all(cfg.jsonl_root(), cfg.parquet_root())
    for p in written:
        print(p)
    print(f"\n# rolled up {len(written)} files", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polymarket_engine.cli")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="list active BTC/ETH price-target markets")
    sub.add_parser("collect", help="run 24/7 collector (Ctrl-C to stop)")
    p_report = sub.add_parser("report", help="render daily anomaly markdown report")
    p_report.add_argument("date", nargs="?", help="YYYY-MM-DD (default: yesterday UTC)")
    sub.add_parser("rollup", help="convert finalised JSONL day-files to Parquet")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return {
        "discover": _cmd_discover,
        "collect": _cmd_collect,
        "report": _cmd_report,
        "rollup": _cmd_rollup,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
