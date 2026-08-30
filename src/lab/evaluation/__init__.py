"""Evaluation machinery: walk-forward splitting, and later metrics and holdout.

Nothing in this package may import training code, and training code may not
import the holdout evaluator. See Release 0.2 task 11.
"""

from __future__ import annotations

from lab.evaluation.splits import (
    DatedFold,
    Fold,
    WalkForwardConfig,
    to_dated_folds,
    walk_forward_folds,
)

__all__ = [
    "DatedFold",
    "Fold",
    "WalkForwardConfig",
    "to_dated_folds",
    "walk_forward_folds",
]
