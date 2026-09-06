"""Optional licensed historical bars from the Alpaca Market Data API.

Paper API keys are sufficient for this endpoint. This module never talks to a
broker order API and refuses any host other than the market-data host. Keys
are read from the environment and are never written to artifacts or logs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from lab.contracts import Bar
from lab.contracts.enums import BarInterval, PriceAdjustment

DEFAULT_DATA_BASE_URL = "https://data.alpaca.markets"
ALLOWED_DATA_HOSTS = frozenset({"data.alpaca.markets"})
LIVE_TRADING_HOST = "api.alpaca.markets"


def alpaca_keys_present(env: Mapping[str, str] | None = None) -> bool:
    """Return whether paper Alpaca keys are set in ``env`` (default: os.environ)."""
    mapping = os.environ if env is None else env
    key = mapping.get("ALPACA_API_KEY_ID", "").strip()
    secret = mapping.get("ALPACA_API_SECRET_KEY", "").strip()
    return bool(key and secret)


def _data_base_url(env: Mapping[str, str]) -> str:
    raw = env.get("ALPACA_DATA_BASE_URL", DEFAULT_DATA_BASE_URL).strip() or DEFAULT_DATA_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("Alpaca market-data URL must be https")
    host = (parsed.hostname or "").lower()
    if host == LIVE_TRADING_HOST:
        raise ValueError("refusing the live trading host; historical bars use the market-data API")
    if host not in ALLOWED_DATA_HOSTS:
        raise ValueError(f"refusing unapproved market-data host {host!r}")
    return raw.rstrip("/")


def _read_json(opener: Callable[..., Any], request: Request, timeout: float) -> dict[str, Any]:
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"Alpaca market-data request failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError("Alpaca market-data request failed") from exc
    if not isinstance(payload, dict):
        raise ValueError("Alpaca market-data response was not an object")
    return payload


def fetch_daily_bars(
    symbols: Sequence[str],
    start: date,
    end: date,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    ingested_at: datetime | None = None,
    timeout: float = 30,
) -> list[Bar]:
    """Fetch split-and-dividend-adjusted daily bars from Alpaca.

    Requires ``ALPACA_API_KEY_ID`` and ``ALPACA_API_SECRET_KEY``. Uses the IEX
    feed (available with paper keys). Does not log credentials.

    Args:
        symbols: Tickers to request.
        start: Inclusive calendar start.
        end: Exclusive calendar end, matching ``generate_daily_bars`` /
            ``weekdays`` (``[start, end)``). Converted to Alpaca's inclusive
            ``end`` before the request so the last included day is ``end - 1``.
        env: Environment mapping. Defaults to ``os.environ``.
        opener: Injectable ``urlopen`` for tests.
        ingested_at: Provenance stamp. Defaults to now (UTC).
        timeout: Per-request timeout in seconds.
    """
    if not symbols:
        raise ValueError("at least one symbol is required")
    mapping = os.environ if env is None else env
    if not alpaca_keys_present(mapping):
        raise ValueError(
            "Alpaca historical bars require ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY; "
            "leave them empty and use --source fixture for the committed offline run"
        )
    key_id = mapping["ALPACA_API_KEY_ID"].strip()
    secret = mapping["ALPACA_API_SECRET_KEY"].strip()
    base = _data_base_url(mapping)
    inclusive_end = _inclusive_alpaca_end(start, end)
    if inclusive_end is None:
        return []
    stamped = datetime.now(tz=UTC) if ingested_at is None else ingested_at
    fetch: Callable[..., Any] = opener if opener is not None else urlopen
    bars: list[Bar] = []
    page_token: str | None = None
    # Lab windows are half-open [start, end), same as the fixture generator.
    # Alpaca's `end` query param is inclusive, so send the last included day.
    alpaca_end = inclusive_end.isoformat()
    while True:
        params: dict[str, str] = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": alpaca_end,
            "adjustment": "all",
            "feed": "iex",
            "limit": "10000",
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        request = Request(  # noqa: S310 — host is allow-listed to data.alpaca.markets
            f"{base}/v2/stocks/bars?{urlencode(params)}",
            headers={
                "APCA-API-KEY-ID": key_id,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
            method="GET",
        )
        payload = _read_json(fetch, request, timeout)
        raw_bars = payload.get("bars") or {}
        if isinstance(raw_bars, dict):
            for symbol, rows in raw_bars.items():
                if not isinstance(rows, list):
                    continue
                bars.extend(_bars_from_rows(symbol, rows, stamped))
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    # Drop any extra session on or after the exclusive lab end.
    return [bar for bar in bars if bar.ts_start.date() < end]


def _inclusive_alpaca_end(start: date, end: date) -> date | None:
    """Last calendar day Alpaca should include for a lab ``[start, end)`` window.

    Returns ``None`` when the half-open range is empty so we do not request
    a day the fixture generator would omit.
    """
    if end <= start:
        return None
    return end - timedelta(days=1)


def _bars_from_rows(symbol: str, rows: list[Any], ingested_at: datetime) -> list[Bar]:
    parsed: list[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_alpaca_time(row.get("t"))
        ts_end = datetime(ts.year, ts.month, ts.day, 21, 0, tzinfo=UTC)
        ts_start = datetime(ts.year, ts.month, ts.day, 14, 30, tzinfo=UTC)
        if ts_end <= ts_start:
            continue
        parsed.append(
            Bar(
                symbol=symbol,
                interval=BarInterval.DAY_1,
                ts_start=ts_start,
                ts_end=ts_end,
                open=_dec(row.get("o")),
                high=_dec(row.get("h")),
                low=_dec(row.get("l")),
                close=_dec(row.get("c")),
                volume=_dec(row.get("v")),
                vwap=_optional_dec(row.get("vw")),
                trade_count=_optional_int(row.get("n")),
                adjustment=PriceAdjustment.SPLIT_AND_DIVIDEND,
                source="alpaca-iex",
                ingested_at=ingested_at,
            )
        )
    return parsed


def _parse_alpaca_time(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("Alpaca bar missing timestamp")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dec(raw: object) -> Decimal:
    if raw is None:
        raise ValueError("Alpaca bar missing a required numeric field")
    return Decimal(str(raw))


def _optional_dec(raw: object) -> Decimal | None:
    if raw is None:
        return None
    return Decimal(str(raw))


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    return int(raw)


__all__ = [
    "ALLOWED_DATA_HOSTS",
    "DEFAULT_DATA_BASE_URL",
    "alpaca_keys_present",
    "fetch_daily_bars",
]
