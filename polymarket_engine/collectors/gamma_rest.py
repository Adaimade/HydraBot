"""Polymarket Gamma REST market discovery (public, no auth).

Yields a list of Market dataclasses suitable for CLOB WS subscription and
strike/expiry mapping. Filters BTC/ETH price-target markets ending within
the next N days.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
_VERB_RE = re.compile(r"\b(reach|above|below|hit|close|exceed|cross|over|under)\b", re.I)
_BTC_RE = re.compile(r"\b(bitcoin|btc)\b", re.I)
_ETH_RE = re.compile(r"\b(ethereum|ether|eth)\b", re.I)


@dataclass
class Market:
    market_id: str
    question: str
    underlying: str
    strike: float | None
    direction: str
    end_iso: str
    end_ts_ms: int
    yes_token_id: str
    no_token_id: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


def _parse_strike(question: str) -> float | None:
    matches = _PRICE_RE.findall(question or "")
    if not matches:
        return None
    largest = max(float(m.replace(",", "")) for m in matches)
    return largest if largest > 0 else None


def _parse_direction(question: str) -> str:
    q = (question or "").lower()
    if any(w in q for w in ("below", "under", "less than")):
        return "below"
    return "above"


def _underlying_for(question: str) -> str | None:
    if _BTC_RE.search(question or ""):
        return "BTCUSDT"
    if _ETH_RE.search(question or ""):
        return "ETHUSDT"
    return None


def _parse_clob_token_ids(raw: Any) -> tuple[str, str] | None:
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        ids = raw
    if not isinstance(ids, list) or len(ids) < 2:
        return None
    return str(ids[0]), str(ids[1])


def parse_market(m: dict[str, Any]) -> Market | None:
    q = m.get("question") or m.get("title") or ""
    if not (_VERB_RE.search(q) and _PRICE_RE.search(q)):
        return None
    underlying = _underlying_for(q)
    if underlying is None:
        return None
    strike = _parse_strike(q)
    if strike is None:
        return None

    end_iso = m.get("end_date_iso") or m.get("endDate") or m.get("end_date") or ""
    if not end_iso:
        return None
    try:
        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    end_ts_ms = int(end_dt.timestamp() * 1000)

    tokens = _parse_clob_token_ids(m.get("clobTokenIds") or m.get("clob_token_ids"))
    if not tokens:
        return None

    return Market(
        market_id=str(m.get("conditionId") or m.get("condition_id") or m.get("id") or ""),
        question=q,
        underlying=underlying,
        strike=strike,
        direction=_parse_direction(q),
        end_iso=end_iso,
        end_ts_ms=end_ts_ms,
        yes_token_id=tokens[0],
        no_token_id=tokens[1],
        raw=m,
    )


def discover(
    endpoint: str,
    max_days: int = 90,
    max_markets: int = 60,
    timeout: float = 15.0,
    page_limit: int = 500,
) -> list[Market]:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=max_days)
    out: list[Market] = []
    offset = 0
    while len(out) < max_markets:
        params = {
            "active": "true",
            "closed": "false",
            "limit": page_limit,
            "offset": offset,
        }
        try:
            r = requests.get(endpoint, params=params, timeout=timeout)
            r.raise_for_status()
            page = r.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[gamma] discovery page failed: %s", e)
            break
        if not page:
            break
        for m in page:
            parsed = parse_market(m)
            if parsed is None:
                continue
            end = datetime.fromtimestamp(parsed.end_ts_ms / 1000, tz=timezone.utc)
            if end < now or end > cutoff:
                continue
            out.append(parsed)
            if len(out) >= max_markets:
                break
        if len(page) < page_limit:
            break
        offset += page_limit
    logger.info("[gamma] discovered %d markets", len(out))
    return out


def discovery_record(markets: list[Market]) -> dict[str, Any]:
    ts_ms = int(time.time() * 1000)
    return {
        "ts_local_ms": ts_ms,
        "ts_exchange_ms": ts_ms,
        "source": "gamma",
        "event": "markets",
        "count": len(markets),
        "markets": [m.to_record() for m in markets],
    }
