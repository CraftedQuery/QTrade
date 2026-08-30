"""Models. Currently one: a regularized linear baseline fitted per fold."""

from __future__ import annotations

from lab.models.ridge import FittedModel, TrainingRow, align, fit_ridge, predict

__all__ = ["FittedModel", "TrainingRow", "align", "fit_ridge", "predict"]
