"""Detector interface — sync, single-threaded, called per event."""

from __future__ import annotations

from typing import Iterable


class AbstractDetector:
    name: str = "abstract"

    def on_event(self, event: dict) -> Iterable[dict]:
        return ()

    def on_market_metadata(self, markets: list) -> None:
        pass
