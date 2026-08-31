"""Evaluation machinery: walk-forward splitting, metrics, and the holdout read.

:mod:`lab.evaluation.holdout` is deliberately **not** re-exported here. Importing
this package must not pull the holdout evaluator into a training path — the
isolation required by acceptance test #3 is enforced on the real import graph, so
a convenience re-export would break it. Import it explicitly, from evaluation
code only.
"""

from __future__ import annotations

from lab.evaluation.metrics import (
    PerformanceSummary,
    RankIC,
    equity_curve,
    max_drawdown,
    rank_ic,
    spearman,
    summarise,
    turnover,
)
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
    "PerformanceSummary",
    "RankIC",
    "WalkForwardConfig",
    "equity_curve",
    "max_drawdown",
    "rank_ic",
    "spearman",
    "summarise",
    "to_dated_folds",
    "turnover",
    "walk_forward_folds",
]
