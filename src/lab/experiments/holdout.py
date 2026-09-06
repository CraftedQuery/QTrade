"""Holdout evaluation. The only module allowed to unseal the holdout.

Keep this file import-free of training orchestration. Training code must
not import this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from lab.contracts import Bar, Experiment, FeatureSnapshot, Prediction
from lab.contracts.enums import DatasetSplit, ExperimentStatus
from lab.experiments.baselines import evaluate_sleeves
from lab.experiments.config import ExperimentConfig
from lab.experiments.metrics import SleeveMetrics
from lab.universe.dated import DatedUniverse


@dataclass(frozen=True)
class HoldoutResult:
    """Metrics and predictions for the holdout split only."""

    experiment_id: str
    unsealed_at: datetime
    metrics: tuple[SleeveMetrics, ...]
    predictions: tuple[Prediction, ...]
    snapshots: tuple[FeatureSnapshot, ...]


def evaluate_holdout(
    experiment: Experiment,
    config: ExperimentConfig,
    universe: DatedUniverse,
    bars: Sequence[Bar],
    *,
    created_at: datetime,
    unsealed_at: datetime | None = None,
) -> tuple[Experiment, HoldoutResult]:
    """Unseal the holdout and score it. Returns the unsealed experiment.

    Viewing holdout numbers is a one-way event: ``holdout_unsealed_at`` is
    set here and never cleared.
    """
    stamp = unsealed_at if unsealed_at is not None else datetime.now(tz=UTC)
    unsealed = experiment.model_copy(
        update={
            "holdout_unsealed_at": stamp,
            "status": ExperimentStatus.COMPLETE,
        }
    )
    evaluation = evaluate_sleeves(
        unsealed,
        config,
        universe,
        bars,
        DatasetSplit.HOLDOUT,
        created_at=created_at,
    )
    if any(row.split is not DatasetSplit.HOLDOUT for row in evaluation.metrics):
        raise RuntimeError("holdout evaluation produced a non-holdout metric")
    result = HoldoutResult(
        experiment_id=experiment.experiment_id,
        unsealed_at=stamp,
        metrics=evaluation.metrics,
        predictions=evaluation.predictions,
        snapshots=evaluation.snapshots,
    )
    return unsealed, result


__all__ = ["HoldoutResult", "evaluate_holdout"]
