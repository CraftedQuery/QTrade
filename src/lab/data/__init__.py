"""Market-data loading, fixture generation, and optional licensed fetch."""

from lab.data.alpaca import alpaca_keys_present, fetch_daily_bars
from lab.data.calendar import session_end, session_start, weekdays
from lab.data.generate import FIXTURE_INGESTED_AT, generate_daily_bars
from lab.data.store import bars_available_at, group_bars

__all__ = [
    "FIXTURE_INGESTED_AT",
    "alpaca_keys_present",
    "bars_available_at",
    "fetch_daily_bars",
    "generate_daily_bars",
    "group_bars",
    "session_end",
    "session_start",
    "weekdays",
]
