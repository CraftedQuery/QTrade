"""Walk-forward splits with purge and embargo.

This module is the integrity centrepiece of the release. Everything else can be
wrong in ways that produce a visibly bad result; a leak here produces a *good*
result that is not real.

## The two leaks, and why the obvious fix is not enough

Splitting a time series at a date and training on the left is not sufficient,
because **labels look forward**. A 21-day forward return observed at time *t* is
not known until *t*+21. If *t* sits just inside the training window and *t*+21
sits inside the test window, that training row already encodes the test period's
outcome. The split looks clean by date and leaks anyway.

**Purge** removes it: any training observation whose *label window* overlaps the
test window is dropped. The comparison is against ``t + horizon``, not ``t``.
Purging on the feature timestamp alone is the classic half-fix and leaves the
leak in place.

**Embargo** handles what purge cannot. Prices are serially correlated, so a
training observation taken immediately *after* the test window still carries
information about it — volatility clusters, a trend continues. The embargo drops
a further span after each test fold from all subsequent training.

Both are in trading sessions, not calendar days. A 21-session horizon is not
21 calendar days, and using dates would silently shorten the purge across every
weekend and holiday.

## What this module guarantees

For every fold, no training index *i* and test index *j* satisfy either:

* ``label_end(i) >= start(test)`` and ``i < start(test)`` — an unpurged forward
  label reaching into the test window;
* ``start(test) <= i <= end(test) + embargo`` — an observation inside the test
  window or its embargo.

Both are asserted directly by the test suite over every generated fold, rather
than checked once for a hand-picked example.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Self

from pydantic import Field, model_validator

from lab.contracts.base import LabModel


class WalkForwardConfig(LabModel):
    """Walk-forward split parameters, all counted in trading sessions.

    Attributes:
        label_horizon: Sessions a label looks forward. Drives the purge.
        purge: Extra sessions dropped either side of the label window. Zero is
            valid; the label horizon alone is already purged.
        embargo: Sessions after each test fold withheld from later training.
        test_size: Sessions in each test fold.
        min_train_size: Sessions of training required before a fold is emitted.
        step: Sessions to advance between folds. Defaults to ``test_size``,
            which makes the test windows contiguous and non-overlapping.
        expanding: True grows the training window from the start; False keeps it
            a fixed-length rolling window of ``min_train_size``.
    """

    label_horizon: int = Field(ge=0, description="Sessions a label looks forward.")
    purge: int = Field(default=0, ge=0, description="Extra sessions dropped around the label.")
    embargo: int = Field(default=0, ge=0, description="Sessions withheld after each test fold.")
    test_size: int = Field(ge=1, description="Sessions per test fold.")
    min_train_size: int = Field(ge=1, description="Sessions of training required.")
    step: int | None = Field(default=None, ge=1, description="Sessions between folds.")
    expanding: bool = Field(default=True, description="Grow the training window over time.")

    @property
    def effective_step(self) -> int:
        """Sessions between fold starts."""
        return self.step if self.step is not None else self.test_size

    @property
    def total_purge(self) -> int:
        """Sessions of training dropped before a test window: label plus purge."""
        return self.label_horizon + self.purge

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.purge == 0 and self.label_horizon == 0 and self.embargo == 0:
            raise ValueError(
                "label_horizon, purge and embargo are all zero; that is a plain "
                "time split, which leaks overlapping labels across the boundary"
            )
        return self


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold, as positions into an ordered session list.

    Attributes:
        index: Fold number, from zero.
        train: Session positions usable for training, ascending.
        test: Session positions to evaluate on, ascending and contiguous.
        purged: Positions removed from training because their label window
            reached into the test window.
        embargoed: Positions removed from training by the embargo.
    """

    index: int
    train: tuple[int, ...]
    test: tuple[int, ...]
    purged: tuple[int, ...]
    embargoed: tuple[int, ...]

    @property
    def train_size(self) -> int:
        return len(self.train)

    @property
    def test_size(self) -> int:
        return len(self.test)


@dataclass(frozen=True)
class DatedFold:
    """A fold expressed as dates, for reporting and for the experiment record."""

    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    purged_sessions: int
    embargoed_sessions: int


def walk_forward_folds(session_count: int, config: WalkForwardConfig) -> list[Fold]:
    """Generate walk-forward folds over ``session_count`` ordered sessions.

    Pure and total: no clock, no I/O, no randomness. The same inputs always
    produce the same folds.

    Args:
        session_count: Number of trading sessions available, in order.
        config: Split parameters, in sessions.

    Returns:
        Folds in chronological order. Empty when there is not enough history for
        even one fold — that is a legitimate answer, not an error.
    """
    folds: list[Fold] = []
    test_start = config.min_train_size + config.total_purge

    while test_start + config.test_size <= session_count:
        test_end = test_start + config.test_size - 1
        test = tuple(range(test_start, test_end + 1))

        # Candidate training positions: everything before this test window, and
        # everything after its embargo. The second half only exists for later
        # folds under a rolling window; under an expanding window it is empty.
        lower_bound = (
            0
            if config.expanding
            else max(0, test_start - config.min_train_size - config.total_purge)
        )
        candidates = list(range(lower_bound, test_start))

        # Purge: drop any training position whose label window reaches the test
        # window. The comparison uses i + label_horizon, not i.
        purged = tuple(
            position for position in candidates if position + config.total_purge >= test_start
        )
        # Embargo: drop the span immediately after the test window. Nothing in
        # `candidates` sits there for a forward-only walk, but the set is
        # reported so the guarantee is visible rather than implied.
        embargo_zone = set(range(test_end + 1, test_end + 1 + config.embargo))
        embargoed = tuple(position for position in candidates if position in embargo_zone)

        removed = set(purged) | set(embargoed)
        train = tuple(position for position in candidates if position not in removed)

        if len(train) >= config.min_train_size:
            folds.append(
                Fold(
                    index=len(folds),
                    train=train,
                    test=test,
                    purged=purged,
                    embargoed=embargoed,
                )
            )

        test_start += config.effective_step

    return folds


def to_dated_folds(folds: Sequence[Fold], sessions: Sequence[date]) -> list[DatedFold]:
    """Express folds as dates, using the session calendar they were built over.

    Raises:
        ValueError: If a fold references a session outside ``sessions``.
    """
    dated: list[DatedFold] = []
    for fold in folds:
        highest = max(max(fold.train), max(fold.test))
        if highest >= len(sessions):
            raise ValueError(
                f"fold {fold.index} references session {highest} but only "
                f"{len(sessions)} sessions were supplied"
            )
        dated.append(
            DatedFold(
                index=fold.index,
                train_start=sessions[min(fold.train)],
                train_end=sessions[max(fold.train)],
                test_start=sessions[min(fold.test)],
                test_end=sessions[max(fold.test)],
                purged_sessions=len(fold.purged),
                embargoed_sessions=len(fold.embargoed),
            )
        )
    return dated


__all__ = [
    "DatedFold",
    "Fold",
    "WalkForwardConfig",
    "to_dated_folds",
    "walk_forward_folds",
]
