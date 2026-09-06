"""Walk-forward split generator with purge and embargo applied in code.

The :class:`~lab.contracts.research.Experiment` contract already stores purge
and embargo and refuses overlapping declared windows. This module is the
computational half: an observation whose timestamp falls in a declared window
can still be dropped so overlapping labels and post-split serial correlation
do not leak across the boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from lab.contracts import Experiment
from lab.contracts.enums import DatasetSplit


@dataclass(frozen=True)
class SplitWindow:
    """One declared walk-forward window and its usable sub-range."""

    split: DatasetSplit
    start: datetime
    end: datetime
    usable_start: datetime
    usable_end: datetime

    def contains_declared(self, as_of: datetime) -> bool:
        """Whether ``as_of`` sits in the declared ``[start, end)`` window."""
        return self.start <= as_of < self.end

    def contains_usable(self, as_of: datetime) -> bool:
        """Whether ``as_of`` sits in the purge/embargo-adjusted range."""
        return self.usable_start <= as_of < self.usable_end


@dataclass(frozen=True)
class WalkForwardSplits:
    """Train / validation / holdout windows aligned with the experiment contract."""

    train: SplitWindow
    validation: SplitWindow
    holdout: SplitWindow
    purge: timedelta
    embargo: timedelta
    horizon: timedelta

    @property
    def windows(self) -> tuple[SplitWindow, SplitWindow, SplitWindow]:
        """The three windows in walk-forward order."""
        return (self.train, self.validation, self.holdout)

    def window_for(self, split: DatasetSplit) -> SplitWindow:
        """Return the window for ``split``."""
        mapping = {
            DatasetSplit.TRAIN: self.train,
            DatasetSplit.VALIDATION: self.validation,
            DatasetSplit.HOLDOUT: self.holdout,
        }
        return mapping[split]

    def assign(self, as_of: datetime, *, horizon: timedelta | None = None) -> DatasetSplit | None:
        """Return the split for ``as_of``, or ``None`` if purged or embargoed.

        An observation is assigned only when:

        1. ``as_of`` is inside a declared window;
        2. ``as_of`` is inside that window's usable range (embargo at the
           start of validation/holdout, purge at the end of train/validation);
        3. the label interval ``[as_of, as_of + horizon)`` does not overlap
           the next declared window.
        """
        window = self._declared(as_of)
        if window is None or not window.contains_usable(as_of):
            return None
        label_horizon = self.horizon if horizon is None else horizon
        if as_of + label_horizon > window.end:
            return None
        nxt = self._next(window.split)
        if nxt is not None and as_of + label_horizon > nxt.start:
            return None
        return window.split

    def usable_times(self, as_ofs: Sequence[datetime], split: DatasetSplit) -> list[datetime]:
        """Filter ``as_ofs`` to those assigned to ``split``."""
        return [stamp for stamp in as_ofs if self.assign(stamp) is split]

    def _declared(self, as_of: datetime) -> SplitWindow | None:
        for window in self.windows:
            if window.contains_declared(as_of):
                return window
        return None

    def _next(self, split: DatasetSplit) -> SplitWindow | None:
        if split is DatasetSplit.TRAIN:
            return self.validation
        if split is DatasetSplit.VALIDATION:
            return self.holdout
        return None


def build_walk_forward(
    *,
    train_start: datetime,
    train_end: datetime,
    validation_start: datetime,
    validation_end: datetime,
    holdout_start: datetime,
    holdout_end: datetime,
    purge: timedelta,
    embargo: timedelta,
    horizon: timedelta,
) -> WalkForwardSplits:
    """Build splits whose declared windows match the experiment contract.

    Usable ranges:

    * train: ``[train_start, train_end - purge)``
    * validation: ``[validation_start + embargo, validation_end - purge)``
    * holdout: ``[holdout_start + embargo, holdout_end)``

    Embargo is the span after the previous split withheld from use. Purge is
    the span dropped at the end of a split so labels do not overlap the next
    window. ``horizon`` is applied again in :meth:`WalkForwardSplits.assign`.
    """
    if purge < timedelta(0) or embargo < timedelta(0):
        raise ValueError("purge and embargo must not be negative")
    if horizon <= timedelta(0):
        raise ValueError("horizon must be positive")
    train = SplitWindow(
        split=DatasetSplit.TRAIN,
        start=train_start,
        end=train_end,
        usable_start=train_start,
        usable_end=train_end - purge,
    )
    validation = SplitWindow(
        split=DatasetSplit.VALIDATION,
        start=validation_start,
        end=validation_end,
        usable_start=validation_start + embargo,
        usable_end=validation_end - purge,
    )
    holdout = SplitWindow(
        split=DatasetSplit.HOLDOUT,
        start=holdout_start,
        end=holdout_end,
        usable_start=holdout_start + embargo,
        usable_end=holdout_end,
    )
    for window in (train, validation, holdout):
        if window.end <= window.start:
            raise ValueError(
                f"{window.split.value}_end must be strictly after {window.split.value}_start"
            )
        if window.usable_end <= window.usable_start:
            raise ValueError(
                f"{window.split.value} usable range is empty after purge={purge} embargo={embargo}"
            )
    if validation.start < train.end:
        raise ValueError("validation must not overlap train; walk-forward order is required")
    if holdout.start < validation.end:
        raise ValueError("holdout must not overlap validation; walk-forward order is required")
    return WalkForwardSplits(
        train=train,
        validation=validation,
        holdout=holdout,
        purge=purge,
        embargo=embargo,
        horizon=horizon,
    )


def splits_from_experiment(experiment: Experiment, *, horizon: timedelta) -> WalkForwardSplits:
    """Rebuild computational splits from a registered experiment."""
    return build_walk_forward(
        train_start=experiment.train_start,
        train_end=experiment.train_end,
        validation_start=experiment.validation_start,
        validation_end=experiment.validation_end,
        holdout_start=experiment.holdout_start,
        holdout_end=experiment.holdout_end,
        purge=experiment.purge,
        embargo=experiment.embargo,
        horizon=horizon,
    )


__all__ = [
    "SplitWindow",
    "WalkForwardSplits",
    "build_walk_forward",
    "splits_from_experiment",
]
