"""Rebalance schedules, derived from observed sessions.

Frequencies are monthly (the default), weekly, and daily — decision D4. Monthly
is the default because it is standard for momentum and keeps turnover from
consuming the edge before it can be measured; the other two exist so that
tradeoff can be *measured* rather than assumed.

Schedules are derived from the sessions actually present in the data (decision
D3), never from a calendar library. A month's rebalance is its last observed
session, so a holiday or an early close shifts the date automatically instead of
producing a rebalance on a day the market was shut.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum


class Rebalance(StrEnum):
    """Supported rebalance frequencies."""

    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"


def rebalance_dates(sessions: Sequence[date], frequency: Rebalance) -> list[date]:
    """Sessions on which the portfolio is rebalanced.

    Each period's rebalance is its **last** observed session, so the decision is
    made with that period's information complete. Trailing partial periods are
    included: the final session of the data is always a rebalance, because
    truncating it would silently drop the most recent decision.

    Args:
        sessions: Observed trading sessions, ascending.
        frequency: How often to rebalance.

    Returns:
        Rebalance dates in order. Empty when no sessions were supplied.
    """
    if not sessions:
        return []
    if frequency is Rebalance.DAILY:
        return list(sessions)

    def period(day: date) -> tuple[int, int]:
        if frequency is Rebalance.MONTHLY:
            return (day.year, day.month)
        iso = day.isocalendar()
        return (iso.year, iso.week)

    dates: list[date] = []
    for index, day in enumerate(sessions):
        is_last_of_period = index == len(sessions) - 1 or period(sessions[index + 1]) != period(day)
        if is_last_of_period:
            dates.append(day)
    return dates


__all__ = ["Rebalance", "rebalance_dates"]
