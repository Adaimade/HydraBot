"""Daily anomaly report generator (markdown)."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path


_LAG_BINS = [
    ("(-inf, -2s]",   float("-inf"), -2000),
    ("(-2s, -500ms]", -2000,         -500),
    ("(-500, -100]",  -500,          -100),
    ("(-100, 100)",   -100,          100),
    ("[100, 500)",    100,           500),
    ("[500, 2000]",   500,           2000),
    ("[2000, +inf)",  2000,          float("inf")),
]


def _read_anomalies(path: Path) -> list[dict]:
    if not path.exists():
        return []
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


def _bar(count: int, max_count: int, width: int = 30) -> str:
    if max_count <= 0:
        return ""
    return "█" * max(1 if count > 0 else 0, int(round(count / max_count * width)))


def _histogram(rows: list[dict]) -> str:
    counts = [0] * len(_LAG_BINS)
    for r in rows:
        lag = r.get("lag_ms")
        if lag is None:
            continue
        for i, (_, lo, hi) in enumerate(_LAG_BINS):
            if lo <= lag < hi or (i == len(_LAG_BINS) - 1 and lag >= lo):
                counts[i] += 1
                break
    max_c = max(counts) if counts else 0
    lines = ["```", f"{'lag bin':<18}  {'n':>4}  bar"]
    for (label, _, _), c in zip(_LAG_BINS, counts):
        lines.append(f"{label:<18}  {c:>4}  {_bar(c, max_c)}")
    lines.append("```")
    return "\n".join(lines)


def _per_market(rows: list[dict]) -> list[dict]:
    by_m: dict[str, list[dict]] = {}
    for r in rows:
        by_m.setdefault(r.get("market", ""), []).append(r)
    out = []
    for mid, rs in by_m.items():
        edges = [abs(int(r.get("edge_bps", 0))) for r in rs]
        lags = [int(r.get("lag_ms", 0)) for r in rs if r.get("lag_ms") is not None]
        durations = [int(r.get("duration_ms", 0)) for r in rs]
        out.append({
            "market": mid,
            "underlying": rs[0].get("underlying", ""),
            "strike": rs[0].get("strike"),
            "count": len(rs),
            "mean_edge_bps": round(sum(edges) / len(edges)) if edges else 0,
            "median_lag_ms": int(statistics.median(lags)) if lags else 0,
            "max_duration_ms": max(durations) if durations else 0,
            "score": round((sum(edges) / len(edges) if edges else 0) * len(rs)),
        })
    return out


def _md_table(headers: list[str], rows: list[list]) -> str:
    sep = "|".join(["---"] * len(headers))
    body = ["| " + " | ".join(headers) + " |", f"|{sep}|"]
    for r in rows:
        body.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(body)


def render_markdown(
    date_iso: str,
    anomalies_root: str | Path,
    out_dir: str | Path,
) -> tuple[str, Path | None]:
    root = Path(anomalies_root)
    src = root / f"{date_iso}.jsonl"
    if not src.exists():
        src = root / f"{date_iso}.jsonl.partial"
    rows = _read_anomalies(src)

    parts: list[str] = []
    parts.append(f"# Polymarket Anomaly Report — {date_iso}\n")
    parts.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n")
    parts.append(f"\n**Total anomalies:** {len(rows)}\n")

    if not rows:
        parts.append("\n_No anomalies recorded for this date._\n")
        md = "".join(parts)
        out = Path(out_dir) / f"{date_iso}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        return md, out

    top10 = sorted(rows, key=lambda r: abs(int(r.get("edge_bps", 0))), reverse=True)[:10]
    parts.append("\n## Top 10 by edge\n\n")
    parts.append(_md_table(
        ["edge_bps", "lag_ms", "underlying", "strike", "p_pm", "p_bn", "market"],
        [[
            r.get("edge_bps"),
            r.get("lag_ms"),
            r.get("underlying"),
            r.get("strike"),
            r.get("implied_prob_pm"),
            r.get("implied_prob_bn"),
            (r.get("market") or "")[:14],
        ] for r in top10],
    ))
    parts.append("\n\n## Lag histogram\n\n")
    parts.append(_histogram(rows))

    pm = _per_market(rows)
    pm.sort(key=lambda r: r["score"], reverse=True)
    parts.append("\n\n## Per-market summary\n\n")
    parts.append(_md_table(
        ["market", "underlying", "strike", "n", "mean_|edge|_bps", "median_lag_ms", "max_dur_ms"],
        [[
            (r["market"] or "")[:14],
            r["underlying"],
            r["strike"],
            r["count"],
            r["mean_edge_bps"],
            r["median_lag_ms"],
            r["max_duration_ms"],
        ] for r in pm[:25]],
    ))
    parts.append("\n\n## High-EV leaderboard (mean_|edge|_bps × count)\n\n")
    parts.append(_md_table(
        ["rank", "score", "market", "underlying", "strike", "n"],
        [[
            i + 1,
            r["score"],
            (r["market"] or "")[:14],
            r["underlying"],
            r["strike"],
            r["count"],
        ] for i, r in enumerate(pm[:10])],
    ))

    md = "".join(parts) + "\n"
    out = Path(out_dir) / f"{date_iso}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return md, out


def yesterday_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
