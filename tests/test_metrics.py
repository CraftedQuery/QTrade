"""Metrics: rank IC under both conventions, turnover, drawdown, net of cost."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lab.costs import CONSERVATIVE_V1, FRICTIONLESS
from lab.evaluation import (
    equity_curve,
    max_drawdown,
    rank_ic,
    spearman,
    summarise,
    turnover,
)

DAY = datetime(2024, 1, 1, tzinfo=UTC)


# --- Spearman ---------------------------------------------------------------


def test_perfect_agreement_is_one() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_perfect_disagreement_is_minus_one() -> None:
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_rank_correlation_ignores_magnitude() -> None:
    """Only the ordering matters, which is the point of using ranks."""
    assert spearman([1, 2, 3], [1, 2, 1000]) == pytest.approx(1.0)


def test_ties_are_averaged() -> None:
    assert spearman([1, 1, 2], [5, 5, 9]) == pytest.approx(1.0)


def test_a_constant_series_has_no_correlation() -> None:
    """Nothing to rank means undefined, not zero."""
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_too_few_pairs_is_undefined() -> None:
    assert spearman([1], [2]) is None
    assert spearman([], []) is None


def test_spearman_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        spearman([1, 2], [1])


# --- Rank IC ----------------------------------------------------------------


def test_both_conventions_are_reported() -> None:
    by_date = {
        DAY: [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)],
        DAY + timedelta(days=1): [(1.0, 3.0), (2.0, 2.0), (3.0, 1.0)],
    }
    result = rank_ic(by_date)
    assert result.per_date_mean == pytest.approx(0.0)
    assert result.pooled is not None
    assert result.dates == 2


def test_a_concentration_gap_reveals_skill_bunched_in_time() -> None:
    """Pooled IC alone would hide that the skill came from one date."""
    flat = [(float(i), float(i % 3)) for i in range(10)]
    strong = [(float(i), float(i)) for i in range(10)]
    by_date = {DAY + timedelta(days=i): flat for i in range(9)}
    by_date[DAY + timedelta(days=9)] = strong

    result = rank_ic(by_date)
    assert result.dates == 10
    assert result.concentration_gap is not None


def test_per_date_dispersion_is_reported() -> None:
    by_date = {
        DAY + timedelta(days=i): [(1.0, 1.0), (2.0, 2.0)] if i % 2 else [(1.0, 2.0), (2.0, 1.0)]
        for i in range(8)
    }
    result = rank_ic(by_date)
    assert result.per_date_std is not None
    assert result.per_date_std > 0


def test_a_steady_signal_has_a_large_t_stat() -> None:
    by_date = {DAY + timedelta(days=i): [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)] for i in range(20)}
    result = rank_ic(by_date)
    assert result.per_date_mean == pytest.approx(1.0)
    assert result.per_date_std == pytest.approx(0.0)
    assert result.per_date_t_stat is None  # zero dispersion: t is undefined, not infinite


def test_no_data_yields_no_ic() -> None:
    empty = rank_ic({})
    assert empty.per_date_mean is None
    assert empty.pooled is None
    assert empty.dates == 0


def test_dates_with_undefined_correlation_are_skipped_not_zeroed() -> None:
    by_date = {
        DAY: [(1.0, 1.0), (1.0, 2.0)],  # constant predictions: undefined
        DAY + timedelta(days=1): [(1.0, 1.0), (2.0, 2.0)],
    }
    assert rank_ic(by_date).dates == 1


# --- Turnover ---------------------------------------------------------------


def test_a_full_switch_is_turnover_of_two() -> None:
    """One weight sold and one bought; both sides are paid for."""
    assert turnover({"A": Decimal("1")}, {"B": Decimal("1")}) == Decimal("2")


def test_holding_still_is_zero_turnover() -> None:
    book = {"A": Decimal("0.5"), "B": Decimal("0.5")}
    assert turnover(book, book) == Decimal("0")


def test_going_to_cash_is_turnover_of_one() -> None:
    assert turnover({"A": Decimal("1")}, {}) == Decimal("1")


def test_partial_rebalance_counts_both_legs() -> None:
    previous = {"A": Decimal("0.6"), "B": Decimal("0.4")}
    target = {"A": Decimal("0.4"), "B": Decimal("0.6")}
    assert turnover(previous, target) == Decimal("0.4")


# --- Drawdown and equity ----------------------------------------------------


def test_drawdown_measures_peak_to_trough() -> None:
    assert max_drawdown([100, 120, 60, 80]) == pytest.approx(0.5)


def test_a_rising_series_has_no_drawdown() -> None:
    assert max_drawdown([1, 2, 3, 4]) == 0.0


def test_empty_equity_has_no_drawdown() -> None:
    assert max_drawdown([]) == 0.0


def test_equity_compounds() -> None:
    assert equity_curve([0.1, 0.1])[-1] == pytest.approx(1.21)


# --- Summary ----------------------------------------------------------------


def test_costs_reduce_the_net_return() -> None:
    returns = [0.01] * 12
    churn = [Decimal("1.0")] * 12
    cheap = summarise("cheap", returns, [Decimal("0")] * 12, CONSERVATIVE_V1, 12)
    dear = summarise("dear", returns, churn, CONSERVATIVE_V1, 12)

    assert dear.net_return < cheap.net_return
    assert dear.cost_drag > 0
    assert dear.gross_return == pytest.approx(cheap.gross_return)


def test_gross_and_net_are_both_reported() -> None:
    """The drag must be visible, not buried in a single number."""
    summary = summarise("s", [0.02] * 12, [Decimal("0.5")] * 12, CONSERVATIVE_V1, 12)
    assert summary.gross_return > summary.net_return
    assert summary.cost_share_of_gross is not None
    assert 0 < summary.cost_share_of_gross < 1


def test_a_frictionless_run_flatters_the_result() -> None:
    """Exactly the comparison the cost model exists to make visible."""
    returns, churn = [0.005] * 24, [Decimal("1.5")] * 24
    optimistic = summarise("free", returns, churn, FRICTIONLESS, 12)
    honest = summarise("real", returns, churn, CONSERVATIVE_V1, 12)
    assert optimistic.net_return > honest.net_return


def test_sharpe_is_none_without_volatility() -> None:
    assert summarise("flat", [0.01] * 5, [Decimal("0")] * 5, CONSERVATIVE_V1, 12).sharpe is None


def test_annualisation_uses_the_rebalance_frequency() -> None:
    monthly = summarise("m", [0.01] * 12, [Decimal("0")] * 12, CONSERVATIVE_V1, 12)
    assert monthly.annualised_return == pytest.approx(1.01**12 - 1, rel=1e-6)


def test_volatility_is_annualised() -> None:
    summary = summarise("v", [0.02, -0.01] * 12, [Decimal("0")] * 24, CONSERVATIVE_V1, 12)
    assert summary.annualised_volatility > 0
    assert not math.isnan(summary.annualised_volatility)


def test_hit_rate_is_reported_but_is_not_a_target() -> None:
    """Present so its absence cannot be mistaken for an oversight."""
    summary = summarise("h", [0.01, -0.01, 0.01, 0.01], [Decimal("0")] * 4, CONSERVATIVE_V1, 12)
    assert summary.hit_rate == pytest.approx(0.75)


def test_a_high_hit_rate_can_still_lose_money() -> None:
    """Which is precisely why win rate is not optimised."""
    summary = summarise("trap", [0.01, 0.01, 0.01, -0.10], [Decimal("0")] * 4, CONSERVATIVE_V1, 12)
    assert summary.hit_rate == pytest.approx(0.75)
    assert summary.net_return < 0


def test_summarise_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        summarise("s", [0.01, 0.02], [Decimal("0")], CONSERVATIVE_V1, 12)


def test_average_turnover_is_reported() -> None:
    summary = summarise("t", [0.01] * 4, [Decimal("0.5")] * 4, CONSERVATIVE_V1, 12)
    assert summary.average_turnover == pytest.approx(0.5)
