"""Walk-forward split invariants.

A leak here produces a *good* result that is not real, so these are property
tests over a grid of configurations rather than spot checks on one example.
"""

from __future__ import annotations

import itertools
from datetime import date

import pytest
from pydantic import ValidationError

from lab.evaluation import WalkForwardConfig, to_dated_folds, walk_forward_folds
from tests.synthetic import trading_sessions

# A grid wide enough that an off-by-one in either direction shows up somewhere.
GRID = [
    WalkForwardConfig(
        label_horizon=horizon,
        purge=purge,
        embargo=embargo,
        test_size=test_size,
        min_train_size=train,
        expanding=expanding,
    )
    for horizon, purge, embargo, test_size, train, expanding in itertools.product(
        (1, 5, 21), (0, 3), (0, 5), (5, 21, 63), (60, 252), (True, False)
    )
]
SESSIONS = 1260  # roughly five years of daily bars


def fold_id(config: WalkForwardConfig) -> str:
    """Compact parametrize id, so a failure names the configuration that broke."""
    window = "expand" if config.expanding else "roll"
    return (
        f"h{config.label_horizon}-p{config.purge}-e{config.embargo}"
        f"-t{config.test_size}-m{config.min_train_size}-{window}"
    )


@pytest.mark.parametrize(
    "config",
    GRID,
    ids=fold_id,
)
def test_no_training_label_reaches_into_the_test_window(config: WalkForwardConfig) -> None:
    """The purge invariant.

    A training observation at *i* is not known until *i + label_horizon + purge*.
    If that lands at or after the test window starts, the row already encodes the
    test period's outcome and must have been purged.
    """
    for fold in walk_forward_folds(SESSIONS, config):
        test_start = min(fold.test)
        offenders = [i for i in fold.train if i + config.total_purge >= test_start]
        assert not offenders, (
            f"fold {fold.index}: training rows {offenders[:5]} have label windows "
            f"reaching test start {test_start}"
        )


@pytest.mark.parametrize(
    "config", GRID, ids=lambda c: f"h{c.label_horizon}e{c.embargo}t{c.test_size}"
)
def test_training_never_overlaps_the_test_window_or_its_embargo(
    config: WalkForwardConfig,
) -> None:
    """The embargo invariant, plus the obvious no-overlap requirement."""
    for fold in walk_forward_folds(SESSIONS, config):
        test_start, test_end = min(fold.test), max(fold.test)
        forbidden = set(range(test_start, test_end + 1 + config.embargo))
        assert not forbidden.intersection(fold.train), (
            f"fold {fold.index}: training overlaps the test window or its embargo"
        )


@pytest.mark.parametrize("config", GRID, ids=fold_id)
def test_folds_are_ordered_and_bounded(config: WalkForwardConfig) -> None:
    folds = walk_forward_folds(SESSIONS, config)
    for fold in folds:
        assert max(fold.train) < min(fold.test), "training must precede its test window"
        assert list(fold.test) == sorted(fold.test)
        assert list(fold.train) == sorted(fold.train)
        assert max(fold.test) < SESSIONS
        assert min(fold.train) >= 0
        assert fold.train_size >= config.min_train_size
    starts = [min(fold.test) for fold in folds]
    assert starts == sorted(starts), "folds must advance in time"


def test_a_naive_split_would_leak_where_ours_does_not() -> None:
    """Proves the purge test can actually fail.

    A test that passes because nothing is checked is worthless. Here the naive
    split — everything before the boundary, no purge — is shown to contain rows
    whose labels reach into the test window, and ours is shown not to.
    """
    config = WalkForwardConfig(label_horizon=21, test_size=63, min_train_size=252)
    fold = walk_forward_folds(SESSIONS, config)[0]
    test_start = min(fold.test)

    naive_train = range(0, test_start)
    naive_leaks = [i for i in naive_train if i + config.total_purge >= test_start]
    assert naive_leaks, "the naive split should leak; otherwise this test proves nothing"
    assert len(naive_leaks) == config.total_purge

    assert not [i for i in fold.train if i + config.total_purge >= test_start]


def test_purged_rows_are_exactly_the_label_window() -> None:
    config = WalkForwardConfig(label_horizon=21, purge=3, test_size=63, min_train_size=252)
    for fold in walk_forward_folds(SESSIONS, config):
        assert len(fold.purged) == config.total_purge
        assert max(fold.purged) == min(fold.test) - 1


# --- Window behaviour -------------------------------------------------------


def test_expanding_window_grows() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100, expanding=True)
    sizes = [fold.train_size for fold in walk_forward_folds(SESSIONS, config)]
    assert sizes == sorted(sizes)
    assert sizes[-1] > sizes[0]
    assert all(fold.train[0] == 0 for fold in walk_forward_folds(SESSIONS, config))


def test_rolling_window_stays_fixed() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100, expanding=False)
    folds = walk_forward_folds(SESSIONS, config)
    assert len({fold.train_size for fold in folds}) == 1
    assert folds[-1].train[0] > folds[0].train[0]


def test_test_windows_are_contiguous_by_default() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100)
    folds = walk_forward_folds(SESSIONS, config)
    for earlier, later in itertools.pairwise(folds):
        assert min(later.test) == max(earlier.test) + 1


def test_step_controls_fold_spacing() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100, step=42)
    folds = walk_forward_folds(SESSIONS, config)
    for earlier, later in itertools.pairwise(folds):
        assert min(later.test) - min(earlier.test) == 42


def test_test_windows_never_overlap() -> None:
    for config in GRID:
        seen: set[int] = set()
        for fold in walk_forward_folds(SESSIONS, config):
            assert seen.isdisjoint(fold.test)
            seen.update(fold.test)


# --- Purity and edges -------------------------------------------------------


def test_the_splitter_is_pure() -> None:
    config = WalkForwardConfig(label_horizon=21, embargo=5, test_size=63, min_train_size=252)
    assert walk_forward_folds(SESSIONS, config) == walk_forward_folds(SESSIONS, config)


def test_insufficient_history_yields_no_folds() -> None:
    """A legitimate answer, not an error."""
    config = WalkForwardConfig(label_horizon=21, test_size=63, min_train_size=252)
    assert walk_forward_folds(100, config) == []
    assert walk_forward_folds(0, config) == []


def test_exactly_enough_history_yields_one_fold() -> None:
    config = WalkForwardConfig(label_horizon=21, test_size=63, min_train_size=252)
    exact = config.min_train_size + config.total_purge + config.test_size
    assert len(walk_forward_folds(exact, config)) == 1
    assert walk_forward_folds(exact - 1, config) == []


def test_a_plain_time_split_is_rejected() -> None:
    """Zero horizon, zero purge and zero embargo is the leak this module exists for."""
    with pytest.raises(ValidationError, match="plain time split"):
        WalkForwardConfig(label_horizon=0, purge=0, embargo=0, test_size=21, min_train_size=100)


def test_negative_parameters_are_rejected() -> None:
    for field, value in (("label_horizon", -1), ("purge", -1), ("embargo", -1), ("test_size", 0)):
        with pytest.raises(ValidationError):
            WalkForwardConfig(
                **{"label_horizon": 5, "test_size": 21, "min_train_size": 100, field: value}
            )


def test_config_is_frozen() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100)
    with pytest.raises(ValidationError):
        config.purge = 99


# --- Dated view -------------------------------------------------------------


def test_dated_folds_map_onto_real_sessions() -> None:
    sessions = trading_sessions(date(2020, 1, 1), date(2024, 12, 31))
    config = WalkForwardConfig(label_horizon=21, embargo=5, test_size=63, min_train_size=252)
    folds = walk_forward_folds(len(sessions), config)
    dated = to_dated_folds(folds, sessions)

    assert len(dated) == len(folds)
    for fold in dated:
        assert fold.train_end < fold.test_start
        assert fold.test_start <= fold.test_end
        assert fold.purged_sessions == config.total_purge
    for earlier, later in itertools.pairwise(dated):
        assert later.test_start > earlier.test_end


def test_dated_folds_reject_a_short_calendar() -> None:
    config = WalkForwardConfig(label_horizon=5, test_size=21, min_train_size=100)
    folds = walk_forward_folds(SESSIONS, config)
    with pytest.raises(ValueError, match="only 10 sessions"):
        to_dated_folds(folds, trading_sessions(date(2024, 1, 1), date(2024, 1, 12))[:10])


def test_purge_is_counted_in_sessions_not_calendar_days() -> None:
    """21 sessions is about a month; using dates would shorten it every weekend."""
    sessions = trading_sessions(date(2020, 1, 1), date(2024, 12, 31))
    config = WalkForwardConfig(label_horizon=21, test_size=63, min_train_size=252)
    fold = to_dated_folds(walk_forward_folds(len(sessions), config), sessions)[0]
    assert (fold.test_start - fold.train_end).days > 21
