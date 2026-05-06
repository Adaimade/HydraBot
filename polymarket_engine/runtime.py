"""Asyncio orchestrator: collectors → writer → detectors → anomalies + heartbeat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .collectors.binance_ws import BinanceCollector, RealisedVolTracker
from .collectors.gamma_rest import Market, discover, discovery_record
from .collectors.polymarket_ws import PolymarketCollector
from .detectors.latency_arb import LatencyArbDetector
from .storage.jsonl_writer import JsonlWriter

logger = logging.getLogger(__name__)


class Runtime:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.writer = JsonlWriter(cfg.jsonl_root(), fsync_interval_sec=cfg.fsync_interval_sec)
        self._vols: dict[str, RealisedVolTracker] = {
            sym: RealisedVolTracker(
                window_min=cfg.vol_window_min,
                default_vol=cfg.default_vol.get(sym, 0.55),
            )
            for sym in cfg.underlyings
        }
        self.detector = LatencyArbDetector(
            vol_provider=lambda s: self._vols[s].sigma_annual() if s in self._vols else 0.55,
            threshold_bps=cfg.edge_threshold_bps,
            min_persist_ms=cfg.min_persist_ms,
            cooldown_ms=cfg.cooldown_ms,
            max_pm_spread=cfg.max_pm_spread,
            min_ttm_hours=cfg.min_ttm_hours,
        )
        self._stop = asyncio.Event()
        self._pm: PolymarketCollector | None = None
        self._bn: BinanceCollector | None = None
        self._markets: list[Market] = []
        self._counts: dict[str, int] = {}
        self._anomalies_today = 0

    def _on_event(self, event: dict) -> None:
        src = event.get("source", "?")
        ev = event.get("event", "?")
        self._counts[f"{src}/{ev}"] = self._counts.get(f"{src}/{ev}", 0) + 1
        try:
            self.writer.write(src, ev, event)
        except Exception:
            logger.exception("writer failed")

        if src == "binance_perp" and ev == "aggTrade":
            sym = event.get("symbol")
            try:
                price = float(event.get("price"))
            except (TypeError, ValueError):
                return
            if sym in self._vols:
                self._vols[sym].push(int(event.get("ts_exchange_ms") or 0), price)

        for anom in self.detector.on_event(event):
            try:
                self.writer.write("detector_latency_arb", "anomaly", anom)
                self._anomalies_today += 1
            except Exception:
                logger.exception("anomaly write failed")

    async def _discovery_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                markets = await loop.run_in_executor(
                    None,
                    discover,
                    self.cfg.gamma_endpoint,
                    self.cfg.market_filter_max_days,
                    self.cfg.max_markets,
                )
            except Exception:
                logger.exception("discovery failed")
                markets = []

            if markets:
                self._markets = markets
                self.detector.on_market_metadata(markets)
                self.writer.write("gamma", "markets", discovery_record(markets))
                asset_index = {m.yes_token_id: ("yes", m.market_id) for m in markets}
                asset_index.update({m.no_token_id: ("no", m.market_id) for m in markets})
                if self._pm is not None:
                    self._pm.update_assets(asset_index)
                logger.info("[runtime] %d markets active", len(markets))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.cfg.discovery_interval_sec)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_loop(self) -> None:
        path = self.cfg.heartbeat_path
        path.parent.mkdir(parents=True, exist_ok=True)
        while not self._stop.is_set():
            data = self.health()
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(path)
            except OSError:
                logger.exception("heartbeat write failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    def health(self) -> dict[str, Any]:
        return {
            "ts": int(time.time() * 1000),
            "active_markets": len(self._markets),
            "anomalies_today": self._anomalies_today,
            "event_counts": dict(self._counts),
            "vols": {s: round(t.sigma_annual(), 4) for s, t in self._vols.items()},
            "polymarket": self._pm.health() if self._pm else None,
            "binance": self._bn.health() if self._bn else None,
        }

    async def run(self) -> None:
        await self._bootstrap_markets()
        self._bn = BinanceCollector(self.cfg.binance_ws_url, self.cfg.underlyings, self._on_event)
        asset_index = {m.yes_token_id: ("yes", m.market_id) for m in self._markets}
        asset_index.update({m.no_token_id: ("no", m.market_id) for m in self._markets})
        self._pm = PolymarketCollector(self.cfg.clob_ws_url, asset_index, self._on_event)

        tasks = [
            asyncio.create_task(self._bn.run(), name="binance_ws"),
            asyncio.create_task(self._pm.run(), name="polymarket_ws"),
            asyncio.create_task(self._discovery_loop(), name="discovery"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self._tick_log_loop(), name="ticklog"),
        ]
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.writer.close()

    async def _tick_log_loop(self) -> None:
        last = dict(self._counts)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
            delta = {k: self._counts.get(k, 0) - last.get(k, 0) for k in set(last) | set(self._counts)}
            last = dict(self._counts)
            logger.info(
                "[runtime] +10s: %s  anomalies_today=%d",
                {k: v for k, v in delta.items() if v},
                self._anomalies_today,
            )

    async def _bootstrap_markets(self) -> None:
        loop = asyncio.get_running_loop()
        markets = await loop.run_in_executor(
            None,
            discover,
            self.cfg.gamma_endpoint,
            self.cfg.market_filter_max_days,
            self.cfg.max_markets,
        )
        self._markets = markets
        self.detector.on_market_metadata(markets)
        if markets:
            self.writer.write("gamma", "markets", discovery_record(markets))
        logger.info("[runtime] bootstrap: %d markets", len(markets))

    def stop(self) -> None:
        self._stop.set()


def read_heartbeat(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"error": "heartbeat file not found", "path": str(p)}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e), "path": str(p)}
