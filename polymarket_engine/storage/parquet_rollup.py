"""Roll finalised JSONL day-files into Parquet under data/parquet/.

Idempotent: a JSONL file is only converted if its parquet output is missing
or older than the JSONL. Writes to part-0.parquet.tmp + os.replace.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _to_table(rows: list[dict]) -> pa.Table:
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    cols: dict[str, list] = {k: [] for k in keys}
    for r in rows:
        for k in keys:
            v = r.get(k)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            cols[k].append(v)
    return pa.table(cols)


def rollup_file(jsonl_path: Path, parquet_root: Path) -> Path | None:
    parts = jsonl_path.parts
    try:
        i = parts.index("raw")
    except ValueError:
        return None
    rel = parts[i + 1 : -1]
    date_iso = jsonl_path.stem
    out_dir = parquet_root.joinpath(*rel, f"dt={date_iso}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.parquet"

    if out_path.exists() and out_path.stat().st_mtime >= jsonl_path.stat().st_mtime:
        return out_path

    rows = _read_jsonl(jsonl_path)
    if not rows:
        return None
    table = _to_table(rows)
    tmp = out_dir / "part-0.parquet.tmp"
    pq.write_table(table, tmp, compression="snappy")
    tmp.replace(out_path)
    return out_path


def rollup_all(raw_root: Path, parquet_root: Path, today_iso: str | None = None) -> list[Path]:
    today = today_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    written: list[Path] = []
    if not raw_root.exists():
        return written
    for jsonl_path in raw_root.rglob("*.jsonl"):
        if jsonl_path.stem >= today:
            continue
        out = rollup_file(jsonl_path, parquet_root)
        if out is not None:
            written.append(out)
    return written
