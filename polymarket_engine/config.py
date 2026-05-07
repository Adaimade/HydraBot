"""Engine configuration loader.

Reads from HydraBot's config.json (key "polymarket_engine") with env-var fallback.
Standalone CLI works without HydraBot — pass a config dict directly or rely on defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "heartbeat_path": "data/heartbeat.json",
    "underlyings": ["BTCUSDT", "ETHUSDT"],
    "gamma_endpoint": "https://gamma-api.polymarket.com/markets",
    "clob_ws_url": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    "binance_ws_url": "wss://fstream.binance.com/stream",
    "discovery_interval_sec": 3600,
    "fsync_interval_sec": 5,
    "edge_threshold_bps": 500,
    "min_persist_ms": 2000,
    "cooldown_ms": 15000,
    "max_pm_spread": 0.10,
    "min_ttm_hours": 1.0,
    "vol_window_min": 60,
    "default_vol": {"BTCUSDT": 0.55, "ETHUSDT": 0.65},
    "report_time_utc": "00:30",
    "max_markets": 60,
    "market_keywords": ["bitcoin", "btc", "ether", "eth"],
    "market_filter_max_days": 90,
}


@dataclass
class EngineConfig:
    data_dir: Path
    heartbeat_path: Path
    underlyings: list[str]
    gamma_endpoint: str
    clob_ws_url: str
    binance_ws_url: str
    discovery_interval_sec: int
    fsync_interval_sec: int
    edge_threshold_bps: int
    min_persist_ms: int
    cooldown_ms: int
    max_pm_spread: float
    min_ttm_hours: float
    vol_window_min: int
    default_vol: dict[str, float]
    report_time_utc: str
    max_markets: int
    market_keywords: list[str]
    market_filter_max_days: int
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None = None) -> "EngineConfig":
        merged = {**DEFAULTS, **(raw or {})}
        merged["data_dir"] = Path(merged["data_dir"]).resolve()
        merged["heartbeat_path"] = Path(merged["heartbeat_path"]).resolve()
        valid = {f for f in cls.__dataclass_fields__ if f != "extra"}
        extra = {k: v for k, v in merged.items() if k not in valid}
        return cls(**{k: merged[k] for k in valid}, extra=extra)

    def jsonl_root(self) -> Path:
        return self.data_dir / "raw"

    def parquet_root(self) -> Path:
        return self.data_dir / "parquet"

    def reports_dir(self) -> Path:
        return self.data_dir.parent / "reports" if self.data_dir.name == "data" \
            else self.data_dir / "reports"


def load_from_hydrabot(agent_config: dict[str, Any] | None) -> EngineConfig:
    raw = (agent_config or {}).get("polymarket_engine") if agent_config else None
    return EngineConfig.from_dict(raw)


def load_from_path(config_path: str | Path) -> EngineConfig:
    p = Path(config_path)
    if not p.exists():
        return EngineConfig.from_dict(None)
    data = json.loads(p.read_text(encoding="utf-8"))
    return load_from_hydrabot(data)


def load_from_env() -> EngineConfig:
    path = os.environ.get("HYDRABOT_CONFIG", "config.json")
    return load_from_path(path)


def to_dict(cfg: EngineConfig) -> dict[str, Any]:
    d = asdict(cfg)
    d["data_dir"] = str(cfg.data_dir)
    d["heartbeat_path"] = str(cfg.heartbeat_path)
    return d
