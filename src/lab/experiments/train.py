"""Training and validation evaluation.

This module must not import :mod:`lab.experiments.holdout` and must not
score the holdout. Acceptance test #3 is the import-graph and result-shape
checks in ``tests/test_holdout_isolation.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from lab.contracts import Bar, Experiment, FeatureSnapshot, Prediction
from lab.contracts.enums import DatasetSplit
from lab.experiments.baselines import SplitEvaluation, evaluate_sleeves
from lab.experiments.config import ExperimentConfig
from lab.experiments.metrics import SleeveMetrics
from lab.universe.dated import DatedUniverse

_TRAINABLE = (DatasetSplit.TRAIN, DatasetSplit.VALIDATION)


@dataclass(frozen=True)
class TrainingResult:
    """Metrics and predictions for train and validation only."""

    experiment_id: str
    metrics: tuple[SleeveMetrics, ...]
    predictions: tuple[Prediction, ...]
    snapshots: tuple[FeatureSnapshot, ...]

    @property
    def splits(self) -> frozenset[DatasetSplit]:
        """Splits present in the metrics. Never includes holdout."""
        return frozenset(item.split for item in self.metrics)


def run_training(
    experiment: Experiment,
    config: ExperimentConfig,
    universe: DatedUniverse,
    bars: Sequence[Bar],
    *,
    created_at: datetime,
) -> TrainingResult:
    """Evaluate cash / SPY / equal-weight / momentum on train and validation.

    Does not unseal the holdout and does not compute holdout metrics.
    """
    evaluations: list[SplitEvaluation] = []
    for split in _TRAINABLE:
        evaluations.append(
            evaluate_sleeves(
                experiment,
                config,
                universe,
                bars,
                split,
                created_at=created_at,
            )
        )
    metrics = tuple(item for evaluation in evaluations for item in evaluation.metrics)
    if any(row.split is DatasetSplit.HOLDOUT for row in metrics):
        raise RuntimeError("training code produced holdout metrics")
    predictions = tuple(item for evaluation in evaluations for item in evaluation.predictions)
    snapshots = tuple(item for evaluation in evaluations for item in evaluation.snapshots)
    return TrainingResult(
        experiment_id=experiment.experiment_id,
        metrics=metrics,
        predictions=predictions,
        snapshots=snapshots,
    )


__all__ = ["TrainingResult", "run_training"]
