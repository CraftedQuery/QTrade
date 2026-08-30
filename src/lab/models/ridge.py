"""Regularized linear model, fitted per walk-forward fold.

## Why ridge, and why per fold

A linear model with L2 regularization is the honest baseline for a cross-
sectional signal: it is reproducible, its coefficients are inspectable, and it
cannot memorise the way a flexible model can. If ridge cannot extract a signal,
a more expressive model that appears to is far more likely to be fitting noise.

Fitting happens **once per fold, on that fold's training rows only**. The fold
boundaries already carry the purge and embargo from
:mod:`lab.evaluation.splits`, so a correct fit here means no training row's label
reached into the window being predicted.

## What this module refuses to do

* **No imputation.** A row with any missing feature is dropped, not filled. A
  zero standing in for "not enough history" is a fabricated observation, and it
  is indistinguishable from a real zero once it reaches the model.
* **No outcome on the prediction.** Predictions are written before outcomes
  exist; the :class:`~lab.contracts.research.Prediction` contract has nowhere to
  put one.
* **No refit on evaluation data.** The fitted model is returned, not re-tuned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from sklearn.linear_model import Ridge

from lab.contracts import FeatureSnapshot, Prediction
from lab.contracts.enums import DatasetSplit
from lab.features import Label, is_complete


@dataclass(frozen=True)
class TrainingRow:
    """One aligned (features, label) observation."""

    symbol: str
    as_of: datetime
    features: tuple[float, ...]
    label: float
    label_known_at: datetime


@dataclass(frozen=True)
class FittedModel:
    """A ridge model fitted to one fold's training rows.

    Attributes:
        feature_names: Columns, in the order the model expects them.
        coefficients: Fitted weight per feature, aligned to ``feature_names``.
        intercept: Fitted intercept.
        alpha: Regularization strength used.
        rows_fitted: Training observations the fit actually used.
        version: Model version stamped onto every prediction.
    """

    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float
    rows_fitted: int
    version: str

    def predict_one(self, features: Sequence[float]) -> float:
        """Score a single observation."""
        if len(features) != len(self.feature_names):
            raise ValueError(f"expected {len(self.feature_names)} features, got {len(features)}")
        return self.intercept + sum(
            weight * value for weight, value in zip(self.coefficients, features, strict=True)
        )

    @property
    def coefficient_map(self) -> dict[str, float]:
        """Coefficients by feature name, for inspection and reporting."""
        return dict(zip(self.feature_names, self.coefficients, strict=True))


def align(
    snapshots: Sequence[FeatureSnapshot],
    labels: Sequence[Label],
    feature_names: Sequence[str],
) -> list[TrainingRow]:
    """Join snapshots to labels on (symbol, as_of), dropping anything incomplete.

    A row survives only when the snapshot has every feature and a label exists
    for the same symbol at the same decision time. Nothing is imputed: a missing
    feature means the history was too short, and inventing a value for it would
    put a fabricated observation into training.
    """
    by_key = {(label.symbol, label.as_of): label for label in labels}
    rows: list[TrainingRow] = []
    for snapshot in snapshots:
        label = by_key.get((snapshot.symbol, snapshot.as_of))
        if label is None or not is_complete(snapshot):
            continue
        values = [snapshot.values[name] for name in feature_names]
        if any(value is None for value in values):
            continue
        rows.append(
            TrainingRow(
                symbol=snapshot.symbol,
                as_of=snapshot.as_of,
                features=tuple(float(value) for value in values),
                label=label.value,
                label_known_at=label.known_at,
            )
        )
    return sorted(rows, key=lambda row: (row.as_of, row.symbol))


def fit_ridge(
    rows: Sequence[TrainingRow],
    feature_names: Sequence[str],
    alpha: float = 1.0,
    version: str = "ridge-1.0.0",
    min_rows: int = 30,
) -> FittedModel | None:
    """Fit a ridge model to aligned training rows.

    Args:
        rows: Aligned observations, from :func:`align`.
        feature_names: Column order the model will expect.
        alpha: L2 regularization strength. Higher shrinks coefficients harder.
        version: Stamped onto every prediction this model produces.
        min_rows: Fewest observations worth fitting. Below this, None is
            returned rather than a model fitted to noise.

    Returns:
        The fitted model, or None when there were too few rows.
    """
    if len(rows) < min_rows:
        return None

    features = np.array([row.features for row in rows], dtype=float)
    targets = np.array([row.label for row in rows], dtype=float)

    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(features, targets)

    return FittedModel(
        feature_names=tuple(feature_names),
        coefficients=tuple(float(value) for value in model.coef_),
        intercept=float(model.intercept_),
        alpha=alpha,
        rows_fitted=len(rows),
        version=version,
    )


def predict(
    model: FittedModel,
    snapshots: Sequence[FeatureSnapshot],
    experiment_id: str,
    split: DatasetSplit,
    horizon_sessions: int,
    created_at: datetime | None = None,
) -> list[Prediction]:
    """Score snapshots, emitting Prediction records.

    Incomplete snapshots are skipped rather than scored from partial features,
    so a prediction never rests on an imputed input. Every record is written
    before its outcome exists; the contract has no field for one.
    """
    stamp = created_at or datetime.now(UTC)
    predictions: list[Prediction] = []
    for snapshot in snapshots:
        values = [snapshot.values.get(name) for name in model.feature_names]
        if any(value is None for value in values):
            continue
        predictions.append(
            Prediction(
                prediction_id=f"{snapshot.symbol}:{snapshot.as_of.isoformat()}:{model.version}",
                experiment_id=experiment_id,
                model_version=model.version,
                symbol=snapshot.symbol,
                as_of=snapshot.as_of,
                horizon=timedelta(days=horizon_sessions),
                feature_snapshot_id=snapshot.snapshot_id,
                value=model.predict_one([float(value) for value in values]),
                split=split,
                created_at=stamp,
            )
        )
    return predictions


__all__ = ["FittedModel", "TrainingRow", "align", "fit_ridge", "predict"]
