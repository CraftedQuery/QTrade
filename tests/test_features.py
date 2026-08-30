"""Acceptance test #2, end to end: features at t cannot read prices after t.

The contract can *express* the rule; these tests prove the pipeline *maintains*
it. The strongest form is the truncation test: deleting every future bar must
not change a single computed value.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from lab.features import (
    MOMENTUM_V1,
    BarWindow,
    FeatureDef,
    FeatureSet,
    compute_snapshot,
    compute_snapshots,
    is_complete,
)
from tests.synthetic import (
    MarketSpec,
    SymbolSpec,
    generate_bars,
    session_window,
    simple_market,
    trading_sessions,
)

START, END = date(2022, 1, 1), date(2024, 6, 28)
SPEC = simple_market(start=START, end=END)
BARS = generate_bars(SPEC)
SESSIONS = trading_sessions(START, END)


def at(day: date) -> datetime:
    """The decision instant at a session's close."""
    return session_window(day)[1]


MIDPOINT = at(SESSIONS[len(SESSIONS) // 2])


# --- The look-ahead guarantee ----------------------------------------------


def test_deleting_every_future_bar_changes_nothing() -> None:
    """Acceptance #2. If any feature peeked, these two would differ."""
    truncated = [bar for bar in BARS if bar.information_time <= MIDPOINT]
    for symbol in ("AAA", "BBB", "CCC"):
        full = compute_snapshot(symbol, BARS, MIDPOINT)
        limited = compute_snapshot(symbol, truncated, MIDPOINT)
        assert full == limited, f"{symbol}: future bars influenced the snapshot"


def test_a_planted_future_bar_is_invisible() -> None:
    """A deliberately extreme future bar must not move any value."""
    baseline = compute_snapshot("AAA", BARS, MIDPOINT)
    future_close = MIDPOINT + timedelta(days=1)
    planted = [
        *BARS,
        next(bar for bar in BARS if bar.symbol == "AAA").model_copy(
            update={
                "ts_start": future_close - timedelta(hours=7),
                "ts_end": future_close,
                "open": Decimal("9999"),
                "high": Decimal("9999"),
                "low": Decimal("9999"),
                "close": Decimal("9999"),
            }
        ),
    ]
    assert compute_snapshot("AAA", planted, MIDPOINT) == baseline


def test_cutoff_never_exceeds_the_decision_time() -> None:
    for day in SESSIONS[::13]:
        snapshot = compute_snapshot("AAA", BARS, at(day))
        if snapshot is not None:
            assert snapshot.information_cutoff <= snapshot.as_of


def test_cutoff_is_the_newest_bar_actually_read() -> None:
    """Derived, not asserted: it equals the latest visible close, exactly."""
    day = SESSIONS[400]
    snapshot = compute_snapshot("AAA", BARS, at(day))
    assert snapshot.information_cutoff == at(day)


def test_same_day_data_is_legitimate() -> None:
    """A bar closing exactly at the decision instant is knowable, not look-ahead."""
    day = SESSIONS[400]
    snapshot = compute_snapshot("AAA", BARS, at(day))
    assert snapshot.information_cutoff == snapshot.as_of


def test_a_decision_before_the_close_cannot_see_that_session() -> None:
    """Deciding mid-session must use yesterday's bar, not today's unfinished one."""
    day, previous = SESSIONS[400], SESSIONS[399]
    midday = session_window(day)[0] + timedelta(hours=1)
    snapshot = compute_snapshot("AAA", BARS, midday)
    assert snapshot.information_cutoff == at(previous)


# --- The window is the mechanism -------------------------------------------


def test_window_excludes_future_bars_entirely() -> None:
    window = BarWindow("AAA", BARS, MIDPOINT)
    visible = len(window)
    assert visible > 0
    assert visible < len([bar for bar in BARS if bar.symbol == "AAA"])


def test_window_reports_no_cutoff_until_something_is_read() -> None:
    """The cutoff is a consequence of reading, so an unread window has none."""
    window = BarWindow("AAA", BARS, MIDPOINT)
    assert window.information_cutoff is None
    window.closes(5)
    assert window.information_cutoff is not None


def test_window_cutoff_advances_with_what_was_read() -> None:
    window = BarWindow("AAA", BARS, MIDPOINT)
    window.close_at(10)
    older = window.information_cutoff
    window.close_at(0)
    assert window.information_cutoff > older


def test_window_ignores_other_symbols() -> None:
    assert len(BarWindow("AAA", BARS, MIDPOINT)) == len(
        [b for b in BARS if b.symbol == "AAA" and b.information_time <= MIDPOINT]
    )


def test_window_returns_what_exists_rather_than_padding() -> None:
    early = at(SESSIONS[3])
    window = BarWindow("AAA", BARS, early)
    assert len(window.closes(100)) == len(window)


def test_close_at_beyond_history_is_none() -> None:
    window = BarWindow("AAA", BARS, at(SESSIONS[2]))
    assert window.close_at(500) is None
    assert window.close_at(-1) is None


# --- Feature values ---------------------------------------------------------


def test_all_features_present_once_history_suffices() -> None:
    snapshot = compute_snapshot("AAA", BARS, at(SESSIONS[-1]))
    assert set(snapshot.values) == set(MOMENTUM_V1.names)
    assert is_complete(snapshot)


def test_short_history_yields_nulls_not_wrong_numbers() -> None:
    """A missing lookback must never be imputed into a fabricated signal."""
    snapshot = compute_snapshot("AAA", BARS, at(SESSIONS[25]))
    assert not is_complete(snapshot)
    assert snapshot.values["mom_21"] is not None
    assert snapshot.values["mom_252_21"] is None


def test_momentum_sign_follows_the_price_path() -> None:
    rising = MarketSpec(
        symbols=(SymbolSpec("UP", annual_drift=1.2, annual_vol=0.02),),
        start=date(2022, 1, 1),
        end=date(2024, 6, 28),
    )
    falling = MarketSpec(
        symbols=(SymbolSpec("DOWN", annual_drift=-0.9, annual_vol=0.02),),
        start=date(2022, 1, 1),
        end=date(2024, 6, 28),
    )
    end = at(SESSIONS[-1])
    assert compute_snapshot("UP", generate_bars(rising), end).values["mom_63"] > 0
    assert compute_snapshot("DOWN", generate_bars(falling), end).values["mom_63"] < 0


def test_volatility_ranks_a_calm_and_a_wild_series_correctly() -> None:
    calm = MarketSpec(
        symbols=(SymbolSpec("CALM", annual_vol=0.05),), start=date(2022, 1, 1), end=END
    )
    wild = MarketSpec(
        symbols=(SymbolSpec("WILD", annual_vol=0.80),), start=date(2022, 1, 1), end=END
    )
    end = at(SESSIONS[-1])
    assert (
        compute_snapshot("CALM", generate_bars(calm), end).values["vol_21"]
        < compute_snapshot("WILD", generate_bars(wild), end).values["vol_21"]
    )


def test_skip_month_momentum_excludes_the_recent_month() -> None:
    """12-1 momentum must differ from plain 12-month return."""
    snapshot = compute_snapshot("AAA", BARS, at(SESSIONS[-1]))

    plain = FeatureSet(
        name="plain",
        version="1.0.0",
        features=(
            FeatureDef(
                "mom_252",
                253,
                lambda w: (lambda a, b: float(a / b - 1))(w.close_at(0), w.close_at(252)),
            ),
        ),
    )
    full_year = compute_snapshot("AAA", BARS, at(SESSIONS[-1]), plain).values["mom_252"]
    assert snapshot.values["mom_252_21"] != full_year


# --- Shape ------------------------------------------------------------------


def test_no_visible_history_yields_no_snapshot() -> None:
    """With nothing read there is no honest cutoff, so there is no snapshot."""
    assert compute_snapshot("AAA", BARS, datetime(2000, 1, 1, tzinfo=UTC)) is None
    assert compute_snapshot("NOPE", BARS, MIDPOINT) is None


def test_snapshots_are_computed_per_symbol_and_sorted() -> None:
    snapshots = compute_snapshots(["CCC", "AAA", "BBB"], BARS, MIDPOINT)
    assert [s.symbol for s in snapshots] == ["AAA", "BBB", "CCC"]


def test_symbols_without_history_are_omitted_not_nulled() -> None:
    snapshots = compute_snapshots(["AAA", "MISSING"], BARS, MIDPOINT)
    assert [s.symbol for s in snapshots] == ["AAA"]


def test_computation_is_reproducible() -> None:
    assert compute_snapshot("AAA", BARS, MIDPOINT) == compute_snapshot("AAA", BARS, MIDPOINT)


def test_snapshot_records_the_feature_set_version() -> None:
    snapshot = compute_snapshot("AAA", BARS, MIDPOINT)
    assert snapshot.feature_set == "momentum_v1"
    assert snapshot.feature_set_version == "1.0.0"


@pytest.mark.parametrize("feature", MOMENTUM_V1.features, ids=lambda f: f.name)
def test_every_feature_declares_its_lookback(feature: FeatureDef) -> None:
    assert feature.lookback > 0
    assert MOMENTUM_V1.max_lookback >= feature.lookback
