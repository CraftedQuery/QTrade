"""Universe membership must be point-in-time, and the screen must not peek."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lab.universe import LiquidityScreen, Universe, build_universe
from tests.synthetic import (
    MarketSpec,
    SymbolSpec,
    generate_bars,
    generate_instruments,
    trading_sessions,
)

START, END = date(2024, 1, 1), date(2024, 6, 28)
LOOSE = LiquidityScreen(
    lookback_sessions=20,
    min_sessions=5,
    min_median_dollar_volume=Decimal("1"),
    min_price=Decimal("1"),
)


def market(*symbols: SymbolSpec, start: date = START, end: date = END) -> MarketSpec:
    return MarketSpec(symbols=symbols, start=start, end=end)


def build(spec: MarketSpec, dates: list[date] | None = None, **kwargs: object) -> Universe:
    return build_universe(
        "test_v1",
        generate_instruments(spec),
        generate_bars(spec),
        dates or trading_sessions(spec.start, spec.end),
        **kwargs,
    )


# --- Survivorship -----------------------------------------------------------


def test_a_delisted_name_leaves_the_universe() -> None:
    delist = date(2024, 3, 15)
    universe = build(
        market(SymbolSpec("GONE", delist_on=delist), SymbolSpec("ALIVE")), screen=LOOSE
    )

    assert "GONE" in universe.symbols_on(date(2024, 3, 1))
    assert "GONE" not in universe.symbols_on(date(2024, 4, 1))
    assert "ALIVE" in universe.symbols_on(date(2024, 4, 1))


def test_a_late_listing_is_absent_before_it_listed() -> None:
    universe = build(
        market(SymbolSpec("NEW", listed_on=date(2024, 4, 1)), SymbolSpec("OLD")), screen=LOOSE
    )
    assert "NEW" not in universe.symbols_on(date(2024, 2, 1))
    assert "OLD" in universe.symbols_on(date(2024, 2, 1))


def test_unknown_listing_date_marks_the_universe_biased() -> None:
    """A universe that cannot answer 'was this listed then' says so on the record."""
    spec = market(SymbolSpec("AAA"))
    instruments = [one.model_copy(update={"listed_on": None}) for one in generate_instruments(spec)]
    universe = build_universe(
        "test_v1", instruments, generate_bars(spec), trading_sessions(START, END), screen=LOOSE
    )
    assert universe.survivorship_biased


def test_known_listing_dates_are_not_flagged() -> None:
    assert not build(market(SymbolSpec("AAA")), screen=LOOSE).survivorship_biased


def test_an_instrument_without_bars_is_simply_absent() -> None:
    universe = build(market(SymbolSpec("AAA")), screen=LOOSE)
    assert "MISSING" not in universe.symbols_on(universe.dates()[-1])


# --- The screen must not read the future ------------------------------------


def test_membership_on_a_date_ignores_every_later_bar() -> None:
    """The core look-ahead guard: truncating future data must not change the past.

    If the screen peeked, a universe built on the full history would differ from
    one built only on data available at the time.
    """
    spec = market(SymbolSpec("AAA"), SymbolSpec("BBB"), SymbolSpec("CCC"))
    dates = trading_sessions(START, END)
    cutoff = dates[len(dates) // 2]
    all_bars = generate_bars(spec)
    truncated = [bar for bar in all_bars if bar.ts_start.date() <= cutoff]
    instruments = generate_instruments(spec)
    evaluated = [day for day in dates if day <= cutoff]

    with_future = build_universe("u", instruments, all_bars, evaluated, screen=LOOSE)
    without_future = build_universe("u", instruments, truncated, evaluated, screen=LOOSE)

    for day in evaluated:
        assert with_future.symbols_on(day) == without_future.symbols_on(day), (
            f"membership on {day} changed when future bars were removed"
        )


def test_a_name_qualifies_only_after_it_has_traded_enough() -> None:
    """Screening on whole-history volume would admit it from day one."""
    screen = LiquidityScreen(
        lookback_sessions=20,
        min_sessions=15,
        min_median_dollar_volume=Decimal("1"),
        min_price=Decimal("1"),
    )
    universe = build(market(SymbolSpec("AAA")), screen=screen)
    dates = universe.dates()

    assert "AAA" not in universe.symbols_on(dates[0])
    assert "AAA" not in universe.symbols_on(dates[10])
    assert "AAA" in universe.symbols_on(dates[20])


def test_the_screen_only_sees_completed_bars() -> None:
    """A bar's information_time is its close, so same-day data is legitimate."""
    spec = market(SymbolSpec("AAA"), start=date(2024, 1, 1), end=date(2024, 2, 29))
    universe = build(spec, screen=LOOSE)
    member = universe.members_by_date[universe.dates()[-1]][0]
    assert member.sessions_observed <= LOOSE.lookback_sessions


# --- Screen thresholds ------------------------------------------------------


def test_a_penny_stock_is_excluded() -> None:
    screen = LiquidityScreen(
        lookback_sessions=20,
        min_sessions=5,
        min_median_dollar_volume=Decimal("1"),
        min_price=Decimal("50"),
    )
    spec = market(SymbolSpec("CHEAP", start_price=Decimal("2.00"), annual_vol=0.01))
    assert build(spec, screen=screen).max_size == 0


def test_an_illiquid_name_is_excluded() -> None:
    screen = LiquidityScreen(
        lookback_sessions=20,
        min_sessions=5,
        min_median_dollar_volume=Decimal("1e15"),
        min_price=Decimal("1"),
    )
    assert build(market(SymbolSpec("THIN")), screen=screen).max_size == 0


def test_insufficient_history_is_excluded() -> None:
    screen = LiquidityScreen(
        lookback_sessions=200,
        min_sessions=200,
        min_median_dollar_volume=Decimal("1"),
        min_price=Decimal("1"),
    )
    assert build(market(SymbolSpec("AAA")), screen=screen).max_size == 0


def test_screen_rejects_an_unsatisfiable_window() -> None:
    with pytest.raises(ValidationError, match="could never pass"):
        LiquidityScreen(lookback_sessions=10, min_sessions=20)


def test_member_records_the_evidence() -> None:
    universe = build(market(SymbolSpec("AAA")), screen=LOOSE)
    member = universe.members_by_date[universe.dates()[-1]][0]
    assert member.symbol == "AAA"
    assert member.median_dollar_volume > 0
    assert member.last_close > 0
    assert member.sessions_observed >= LOOSE.min_sessions


# --- Shape ------------------------------------------------------------------


def test_universe_is_frozen_and_dated() -> None:
    universe = build(market(SymbolSpec("AAA")), screen=LOOSE)
    assert universe.start == min(universe.dates())
    assert universe.end == max(universe.dates())
    with pytest.raises(ValidationError):
        universe.universe_id = "other"


def test_symbols_are_sorted_and_unique() -> None:
    universe = build(market(SymbolSpec("CCC"), SymbolSpec("AAA"), SymbolSpec("BBB")), screen=LOOSE)
    symbols = universe.symbols_on(universe.dates()[-1])
    assert symbols == sorted(symbols)
    assert len(symbols) == len(set(symbols))


def test_a_date_never_evaluated_returns_empty() -> None:
    universe = build(market(SymbolSpec("AAA")), dates=[date(2024, 6, 3)], screen=LOOSE)
    assert universe.symbols_on(date(2024, 6, 4)) == []


def test_built_at_is_recorded() -> None:
    stamp = datetime(2026, 8, 30, tzinfo=UTC)
    universe = build(market(SymbolSpec("AAA")), screen=LOOSE, built_at=stamp)
    assert universe.built_at == stamp
