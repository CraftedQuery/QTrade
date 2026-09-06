"""Synthetic regular-session calendar used by fixtures and the baseline.

Bars are stamped in UTC as ``[14:30, 21:00)`` on weekdays. That is a stable
fixture convention, not a DST-accurate NYSE calendar. Features must still key
off :attr:`~lab.contracts.market.Bar.information_time` (the close), never the
open.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

SESSION_OPEN = (14, 30)
SESSION_CLOSE = (21, 0)


def weekdays(start: date, end: date) -> list[date]:
    """Return weekdays in the half-open interval ``[start, end)``."""
    if end < start:
        raise ValueError("end must not precede start")
    days: list[date] = []
    cursor = start
    while cursor < end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def session_start(day: date) -> datetime:
    """Inclusive UTC start of the synthetic regular session on ``day``."""
    hour, minute = SESSION_OPEN
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def session_end(day: date) -> datetime:
    """Exclusive UTC end of the synthetic regular session — the information time."""
    hour, minute = SESSION_CLOSE
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def as_of_close(day: date) -> datetime:
    """Decision timestamp for a close-to-close signal on ``day``."""
    return session_end(day)


__all__ = [
    "SESSION_CLOSE",
    "SESSION_OPEN",
    "as_of_close",
    "session_end",
    "session_start",
    "weekdays",
]
