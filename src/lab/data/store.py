"""In-memory helpers for bars. No Parquet/DuckDB in this release."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from lab.contracts import Bar


def group_bars(bars: Sequence[Bar]) -> dict[str, list[Bar]]:
    """Group bars by symbol, each list sorted by ``information_time``."""
    grouped: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(bar)
    return {symbol: sorted(items, key=lambda item: item.information_time) for symbol, items in grouped.items()}


def bars_available_at(bars: Iterable[Bar], as_of: datetime) -> list[Bar]:
    """Return bars whose information time is at or before ``as_of``.

    This is the only filter a feature computer may use to decide whether a
    bar may be an input. ``ts_start`` is deliberately not consulted.
    """
    return [bar for bar in bars if bar.information_time <= as_of]


def close_on(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    symbol: str,
    as_of: datetime,
) -> float | None:
    """Latest close for ``symbol`` with ``information_time <= as_of``."""
    series = bars_by_symbol.get(symbol, ())
    eligible = [bar for bar in series if bar.information_time <= as_of]
    if not eligible:
        return None
    return float(eligible[-1].close)


def session_return(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    symbol: str,
    previous_as_of: datetime,
    as_of: datetime,
) -> float | None:
    """Close-to-close return between two information times, or ``None``."""
    start = close_on(bars_by_symbol, symbol, previous_as_of)
    end = close_on(bars_by_symbol, symbol, as_of)
    if start is None or end is None or start == 0:
        return None
    return end / start - 1.0


__all__ = ["bars_available_at", "close_on", "group_bars", "session_return"]
