"""Replay engine — reads recorded JSONL/Parquet day-files and re-feeds them
to detectors with virtual-time pacing. TODO Phase 2.

The MVP only persists raw + anomalies; replay/scoring/backtest will land in a
follow-up PR. This stub exists so the import path is stable.
"""

__all__: list[str] = []
