"""Rebalance schedules and the four baseline comparators."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from lab.contracts import Proposal
from lab.features import MOMENTUM_V1, compute_snapshots
from lab.strategies import (
    BenchmarkStrategy,
    CashStrategy,
    EqualWeightStrategy,
    MomentumStrategy,
    Rebalance,
    rebalance_dates,
)
from tests.synthetic import (
    MarketSpec,
    SymbolSpec,
    generate_bars,
    session_window,
    trading_sessions,
)

START, END = date(2022, 1, 1), date(2024, 6, 28)
SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE")
SPEC = MarketSpec(
    symbols=tuple(SymbolSpec(s, annual_drift=0.02 * i) for i, s in enumerate(SYMBOLS)),
    start=START,
    end=END,
)
BARS = generate_bars(SPEC)
SESSIONS = trading_sessions(START, END)
AS_OF = session_window(SESSIONS[-1])[1]
SNAPSHOTS = compute_snapshots(SYMBOLS, BARS, AS_OF, MOMENTUM_V1)


def propose(strategy, universe=SYMBOLS) -> Proposal:  # noqa: ANN001
    return strategy.propose(AS_OF, universe, SNAPSHOTS, BARS, "exp-1", "prop-1")


# --- Schedules --------------------------------------------------------------


def test_daily_rebalances_every_session() -> None:
    assert rebalance_dates(SESSIONS, Rebalance.DAILY) == SESSIONS


def test_monthly_rebalances_once_per_month() -> None:
    dates = rebalance_dates(SESSIONS, Rebalance.MONTHLY)
    months = [(d.year, d.month) for d in dates]
    assert len(months) == len(set(months))
    assert 28 <= len(dates) <= 32  # about 30 months of data


def test_weekly_rebalances_once_per_iso_week() -> None:
    dates = rebalance_dates(SESSIONS, Rebalance.WEEKLY)
    weeks = [d.isocalendar()[:2] for d in dates]
    assert len(weeks) == len(set(weeks))
    assert len(dates) > len(rebalance_dates(SESSIONS, Rebalance.MONTHLY))


def test_frequencies_are_strictly_ordered_in_count() -> None:
    monthly = len(rebalance_dates(SESSIONS, Rebalance.MONTHLY))
    weekly = len(rebalance_dates(SESSIONS, Rebalance.WEEKLY))
    daily = len(rebalance_dates(SESSIONS, Rebalance.DAILY))
    assert monthly < weekly < daily


def test_a_rebalance_is_the_last_session_of_its_period() -> None:
    """So the decision is made with that period's information complete."""
    dates = set(rebalance_dates(SESSIONS, Rebalance.MONTHLY))
    for index, day in enumerate(SESSIONS[:-1]):
        if day in dates:
            assert SESSIONS[index + 1].month != day.month


def test_the_final_session_is_always_a_rebalance() -> None:
    """Dropping a trailing partial period would silently lose the latest decision."""
    for frequency in Rebalance:
        assert rebalance_dates(SESSIONS, frequency)[-1] == SESSIONS[-1]


def test_rebalances_land_only_on_observed_sessions() -> None:
    """Derived from data, not a calendar: a holiday cannot produce a rebalance."""
    observed = set(SESSIONS)
    for frequency in Rebalance:
        assert observed.issuperset(rebalance_dates(SESSIONS, frequency))


def test_a_missing_month_end_falls_back_to_the_last_traded_session() -> None:
    holiday_month = [d for d in SESSIONS if not (d.year == 2023 and d.month == 5 and d.day > 25)]
    dates = rebalance_dates(holiday_month, Rebalance.MONTHLY)
    may = [d for d in dates if d.year == 2023 and d.month == 5]
    assert may and may[0].day <= 25


def test_no_sessions_yields_no_rebalances() -> None:
    assert rebalance_dates([], Rebalance.MONTHLY) == []


# --- Baselines --------------------------------------------------------------


def test_cash_holds_nothing() -> None:
    proposal = propose(CashStrategy())
    assert proposal.lines == []
    assert proposal.cash_weight == Decimal(1)


def test_benchmark_holds_one_name() -> None:
    proposal = propose(BenchmarkStrategy("AAA"))
    assert [line.symbol for line in proposal.lines] == ["AAA"]
    assert proposal.invested_weight == Decimal(1)


def test_benchmark_with_no_price_holds_cash() -> None:
    assert propose(BenchmarkStrategy("NOPE")).lines == []


def test_equal_weight_holds_everything_evenly() -> None:
    proposal = propose(EqualWeightStrategy())
    assert len(proposal.lines) == len(SYMBOLS)
    assert len({line.target_weight for line in proposal.lines}) == 1


def test_momentum_holds_the_top_slice() -> None:
    proposal = propose(MomentumStrategy(top_n=2))
    assert len(proposal.lines) == 2
    ranked = sorted(
        (
            (s.symbol, s.values["mom_252_21"])
            for s in SNAPSHOTS
            if s.values["mom_252_21"] is not None
        ),
        key=lambda p: -p[1],
    )
    assert {line.symbol for line in proposal.lines} == {sym for sym, _ in ranked[:2]}


def test_momentum_skips_names_with_a_missing_feature() -> None:
    """An absent value means 'not enough history', never a rankable zero."""
    early = session_window(SESSIONS[30])[1]
    snapshots = compute_snapshots(SYMBOLS, BARS, early, MOMENTUM_V1)
    assert all(s.values["mom_252_21"] is None for s in snapshots)
    proposal = MomentumStrategy(top_n=3).propose(early, SYMBOLS, snapshots, BARS, "exp-1", "prop-1")
    assert proposal.lines == []


def test_momentum_top_n_beyond_the_universe_is_capped() -> None:
    assert len(propose(MomentumStrategy(top_n=99)).lines) <= len(SYMBOLS)


def test_momentum_rejects_a_nonsense_top_n() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        MomentumStrategy(top_n=0)


def test_a_name_outside_the_universe_is_never_held() -> None:
    proposal = propose(MomentumStrategy(top_n=5), universe=("AAA", "BBB"))
    assert {line.symbol for line in proposal.lines} <= {"AAA", "BBB"}


# --- Every strategy obeys the mandate ---------------------------------------

ALL = [
    CashStrategy(),
    BenchmarkStrategy("AAA"),
    EqualWeightStrategy(),
    MomentumStrategy(top_n=3),
]


@pytest.mark.parametrize("strategy", ALL, ids=lambda s: s.name)
def test_no_strategy_can_short_or_lever(strategy) -> None:  # noqa: ANN001
    """Long or cash only, enforced by the Proposal contract itself."""
    proposal = propose(strategy)
    assert all(line.target_weight >= 0 for line in proposal.lines)
    assert proposal.invested_weight <= Decimal(1)
    assert proposal.cash_weight >= 0


@pytest.mark.parametrize("strategy", ALL, ids=lambda s: s.name)
def test_rounding_leaves_cash_rather_than_manufacturing_leverage(strategy) -> None:  # noqa: ANN001
    proposal = propose(strategy)
    assert proposal.invested_weight <= Decimal(1)


@pytest.mark.parametrize("strategy", ALL, ids=lambda s: s.name)
def test_every_strategy_is_deterministic(strategy) -> None:  # noqa: ANN001
    assert propose(strategy).lines == propose(strategy).lines


@pytest.mark.parametrize("strategy", ALL, ids=lambda s: s.name)
def test_reference_prices_are_knowable_at_the_decision_time(strategy) -> None:  # noqa: ANN001
    """Prices come through BarWindow, so a future close cannot be quoted."""
    latest = {
        bar.symbol: bar.close
        for bar in sorted(BARS, key=lambda b: b.ts_start)
        if bar.information_time <= AS_OF
    }
    for line in propose(strategy).lines:
        assert line.reference_price == latest[line.symbol]


@pytest.mark.parametrize("strategy", ALL, ids=lambda s: s.name)
def test_every_strategy_emits_a_valid_proposal(strategy) -> None:  # noqa: ANN001
    proposal = propose(strategy)
    assert isinstance(proposal, Proposal)
    assert proposal.as_of == AS_OF
    assert isinstance(proposal.as_of, datetime)
