"""Acceptance test #2 against *computed* features, not only contract construction."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from lab.contracts import Bar
from lab.contracts.enums import BarInterval, PriceAdjustment
from lab.data.calendar import as_of_close, session_end, session_start
from lab.data.generate import generate_daily_bars
from lab.features.momentum import compute_momentum


def _bar(symbol: str, day: date, close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        symbol=symbol,
        interval=BarInterval.DAY_1,
        ts_start=session_start(day),
        ts_end=session_end(day),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        adjustment=PriceAdjustment.SPLIT_AND_DIVIDEND,
        source="test-fixture",
        ingested_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_momentum_uses_information_time_not_bar_open() -> None:
    """A bar whose close is after as_of is invisible even if it has already opened."""
    day = date(2022, 8, 1)
    known = _bar("AAA", day, "10")
    as_of = known.information_time
    still_open = Bar(
        symbol="AAA",
        interval=BarInterval.DAY_1,
        ts_start=as_of,  # next session has opened
        ts_end=as_of + timedelta(hours=6, minutes=30),
        open=Decimal("999"),
        high=Decimal("999"),
        low=Decimal("999"),
        close=Decimal("999"),
        volume=Decimal("1000"),
        adjustment=PriceAdjustment.SPLIT_AND_DIVIDEND,
        source="test-fixture",
        ingested_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    snap = compute_momentum([known, still_open], symbol="AAA", as_of=as_of, lookback=1)
    assert snap.information_cutoff == known.information_time
    assert snap.information_cutoff <= snap.as_of
    assert still_open.ts_start <= as_of < still_open.information_time


def test_future_close_cannot_change_a_computed_feature() -> None:
    """Plant a 1_000_000 close after as_of; the snapshot must be unchanged."""
    days = [date(2022, 8, 1), date(2022, 8, 2), date(2022, 8, 3)]
    past = [_bar("AAA", day, str(10 + index)) for index, day in enumerate(days)]
    as_of = as_of_close(days[-1])
    leak = _bar("AAA", date(2022, 8, 4), "1000000")
    assert leak.information_time > as_of
    honest = compute_momentum(past, symbol="AAA", as_of=as_of, lookback=2)
    leaked = compute_momentum([*past, leak], symbol="AAA", as_of=as_of, lookback=2)
    assert honest.values == leaked.values
    assert honest.information_cutoff == leaked.information_cutoff == past[-1].information_time
    assert leaked.information_cutoff <= as_of
    expected = float(past[-1].close) / float(past[0].close) - 1.0
    assert leaked.values["mom_2d"] == pytest.approx(expected)


def test_cutoff_is_the_newest_consumed_bar() -> None:
    bars = generate_daily_bars(["AAA"], date(2022, 8, 1), date(2022, 9, 2), seed=1)
    as_of = as_of_close(date(2022, 8, 31))
    snap = compute_momentum(bars, symbol="AAA", as_of=as_of, lookback=21)
    used = [bar for bar in bars if bar.information_time <= as_of]
    assert snap.information_cutoff == used[-1].information_time
    assert snap.values["mom_21d"] is not None


def test_insufficient_history_is_missing_not_a_guess() -> None:
    bars = [_bar("AAA", date(2022, 8, 1), "10")]
    as_of = as_of_close(date(2022, 8, 1))
    snap = compute_momentum(bars, symbol="AAA", as_of=as_of, lookback=21)
    assert snap.values["mom_21d"] is None
    assert snap.information_cutoff <= as_of
