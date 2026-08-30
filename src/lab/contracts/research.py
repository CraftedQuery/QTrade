"""Research contracts: :class:`FeatureSnapshot`, :class:`Experiment`, :class:`Prediction`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Self

from pydantic import Field, model_validator

from lab.contracts.base import Identifier, LabRecord, UtcDatetime
from lab.contracts.enums import DatasetSplit, ExperimentStatus


class FeatureSnapshot(LabRecord):
    """Feature values for one instrument at one decision time.

    The central invariant of the whole lab lives here:
    ``information_cutoff <= as_of``. ``as_of`` is the moment a decision is being
    made; ``information_cutoff`` is the timestamp of the newest input that fed
    these values. If the cutoff were allowed to exceed the decision time, the
    features would encode the future and every downstream result would be
    worthless. Constructing a violating snapshot raises.
    """

    snapshot_id: Identifier = Field(description="Unique id for this snapshot.")
    feature_set: Identifier = Field(description="Name of the feature set.")
    feature_set_version: str = Field(description="Version of the feature-set definition.")
    symbol: Identifier = Field(description="Instrument the features describe.")
    as_of: UtcDatetime = Field(description="Decision time these features are valid for.")
    information_cutoff: UtcDatetime = Field(
        description="Timestamp of the newest input used. Must not exceed as_of."
    )
    values: dict[str, float | None] = Field(
        description="Feature name to value. None marks a legitimately missing value."
    )
    computed_at: UtcDatetime = Field(description="Wall-clock time the snapshot was computed.")

    @model_validator(mode="after")
    def _check_no_lookahead(self) -> Self:
        if self.information_cutoff > self.as_of:
            raise ValueError(
                f"look-ahead: information_cutoff {self.information_cutoff.isoformat()} "
                f"is after as_of {self.as_of.isoformat()}"
            )
        return self


class Experiment(LabRecord):
    """A registered experiment.

    Registration happens *before* any result is viewed, which is why
    ``registered_at``, the split boundaries, and the purge/embargo settings are
    all required at construction. ``trial_count`` travels with the experiment so
    that no performance number can be reported without its search budget, and
    ``holdout_unsealed_at`` records the one moment the holdout was looked at.
    """

    experiment_id: Identifier = Field(description="Unique experiment id.")
    name: str = Field(description="Short human-readable name.")
    hypothesis: str = Field(
        min_length=1, description="What this experiment claims, written before results are seen."
    )
    registered_at: UtcDatetime = Field(description="Registration time. Precedes any result.")
    status: ExperimentStatus = Field(default=ExperimentStatus.REGISTERED)
    universe_id: Identifier = Field(description="Dated universe definition used.")
    feature_set: Identifier = Field(description="Feature set used.")
    feature_set_version: str = Field(description="Feature-set version used.")
    train_start: UtcDatetime = Field(description="Inclusive start of the training window.")
    train_end: UtcDatetime = Field(description="Exclusive end of the training window.")
    validation_start: UtcDatetime = Field(description="Inclusive start of validation.")
    validation_end: UtcDatetime = Field(description="Exclusive end of validation.")
    holdout_start: UtcDatetime = Field(description="Inclusive start of the sealed holdout.")
    holdout_end: UtcDatetime = Field(description="Exclusive end of the sealed holdout.")
    purge: timedelta = Field(
        description="Span dropped around split boundaries to remove overlapping labels."
    )
    embargo: timedelta = Field(description="Span after each split withheld from training.")
    cost_model_id: Identifier = Field(description="Transaction-cost model applied.")
    code_git_sha: str = Field(min_length=7, description="Commit the experiment ran from.")
    config_hash: str = Field(min_length=8, description="Hash of the resolved configuration.")
    trial_count: int = Field(
        ge=1, description="Configurations tried so far in this line of search, this one included."
    )
    parent_experiment_id: Identifier | None = Field(
        default=None, description="Predecessor, when this is a follow-up trial."
    )
    holdout_unsealed_at: UtcDatetime | None = Field(
        default=None, description="When holdout results were first viewed. None means still sealed."
    )

    @model_validator(mode="after")
    def _check_splits(self) -> Self:
        for label, start, end in (
            ("train", self.train_start, self.train_end),
            ("validation", self.validation_start, self.validation_end),
            ("holdout", self.holdout_start, self.holdout_end),
        ):
            if end <= start:
                raise ValueError(f"{label}_end must be strictly after {label}_start")
        if self.validation_start < self.train_end:
            raise ValueError("validation must not overlap train; walk-forward order is required")
        if self.holdout_start < self.validation_end:
            raise ValueError("holdout must not overlap validation; walk-forward order is required")
        if self.purge < timedelta(0) or self.embargo < timedelta(0):
            raise ValueError("purge and embargo must not be negative")
        if self.holdout_unsealed_at and self.holdout_unsealed_at < self.registered_at:
            raise ValueError("holdout cannot be unsealed before the experiment was registered")
        return self

    @property
    def holdout_is_sealed(self) -> bool:
        """Whether the holdout has never been looked at."""
        return self.holdout_unsealed_at is None


class Prediction(LabRecord):
    """One model output, stored before its outcome is known.

    There is deliberately no realised-return or correct/incorrect field. An
    outcome is a separate record joined on ``prediction_id`` later, so that a
    stored prediction can never be quietly revised once the future arrives.
    """

    prediction_id: Identifier = Field(description="Unique prediction id.")
    experiment_id: Identifier = Field(description="Experiment that produced it.")
    model_version: str = Field(description="Version of the model that produced it.")
    symbol: Identifier = Field(description="Instrument the prediction is about.")
    as_of: UtcDatetime = Field(description="Decision time the prediction was made for.")
    horizon: timedelta = Field(description="Forward span the prediction covers.")
    feature_snapshot_id: Identifier = Field(description="Snapshot the model consumed.")
    value: float = Field(description="Predicted score or expected return.")
    split: DatasetSplit = Field(description="Walk-forward split this prediction belongs to.")
    created_at: UtcDatetime = Field(description="Wall-clock time the prediction was written.")

    @model_validator(mode="after")
    def _check_horizon(self) -> Self:
        if self.horizon <= timedelta(0):
            raise ValueError("horizon must be positive")
        return self

    @property
    def target_time(self) -> datetime:
        """Time at which this prediction becomes resolvable."""
        return self.as_of + self.horizon


__all__ = ["Experiment", "FeatureSnapshot", "Prediction"]
