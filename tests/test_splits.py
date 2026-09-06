"""Purge and embargo are applied computationally, not only stored on the contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lab.contracts.enums import DatasetSplit
from lab.experiments.splits import build_walk_forward
from tests.factories import make_experiment


def _splits() -> object:
    return build_walk_forward(
        train_start=datetime(2022, 8, 1, tzinfo=UTC),
        train_end=datetime(2023, 3, 1, tzinfo=UTC),
        validation_start=datetime(2023, 3, 1, tzinfo=UTC),
        validation_end=datetime(2023, 8, 1, tzinfo=UTC),
        holdout_start=datetime(2023, 8, 1, tzinfo=UTC),
        holdout_end=datetime(2024, 1, 1, tzinfo=UTC),
        purge=timedelta(days=21),
        embargo=timedelta(days=5),
        horizon=timedelta(days=21),
    )


def test_declared_windows_match_the_experiment_contract() -> None:
    splits = _splits()
    experiment = make_experiment(
        train_start=splits.train.start,
        train_end=splits.train.end,
        validation_start=splits.validation.start,
        validation_end=splits.validation.end,
        holdout_start=splits.holdout.start,
        holdout_end=splits.holdout.end,
        purge=splits.purge,
        embargo=splits.embargo,
    )
    assert experiment.train_end == splits.train.end
    assert experiment.purge == splits.purge
    assert experiment.embargo == splits.embargo


def test_purge_drops_train_observations_whose_labels_overlap_validation() -> None:
    splits = _splits()
    # Last day of the declared train window is not usable: it sits inside purge.
    last_train = splits.train.end - timedelta(seconds=1)
    assert splits.train.contains_declared(last_train)
    assert splits.assign(last_train) is None
    # A train day whose 21-day label stays inside train is kept.
    safe = datetime(2022, 12, 1, tzinfo=UTC)
    assert splits.assign(safe) is DatasetSplit.TRAIN


def test_embargo_withholds_the_first_days_of_validation_and_holdout() -> None:
    splits = _splits()
    first_val = splits.validation.start
    assert splits.validation.contains_declared(first_val)
    assert splits.assign(first_val) is None
    after_embargo = splits.validation.start + timedelta(days=5)
    assert splits.assign(after_embargo) is DatasetSplit.VALIDATION
    first_holdout = splits.holdout.start
    assert splits.assign(first_holdout) is None
    assert splits.assign(splits.holdout.start + timedelta(days=5)) is DatasetSplit.HOLDOUT


def test_label_horizon_overlapping_the_next_split_is_unassigned() -> None:
    splits = _splits()
    # 10 days before validation, a 21-day label crosses the boundary.
    crossing = splits.validation.start - timedelta(days=10)
    assert splits.train.contains_declared(crossing)
    assert splits.assign(crossing) is None


def test_empty_usable_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="usable range is empty"):
        build_walk_forward(
            train_start=datetime(2022, 1, 1, tzinfo=UTC),
            train_end=datetime(2022, 1, 10, tzinfo=UTC),
            validation_start=datetime(2022, 1, 10, tzinfo=UTC),
            validation_end=datetime(2022, 1, 12, tzinfo=UTC),
            holdout_start=datetime(2022, 1, 12, tzinfo=UTC),
            holdout_end=datetime(2022, 2, 1, tzinfo=UTC),
            purge=timedelta(days=21),
            embargo=timedelta(days=5),
            horizon=timedelta(days=21),
        )
