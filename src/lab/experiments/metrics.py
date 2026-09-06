"""Required research metrics: rank IC, turnover, drawdown, net-of-cost.

Win rate is deliberately not computed. Every metric object carries the
experiment's trial count so a number cannot be reported without its search
budget.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from lab.contracts.enums import DatasetSplit


@dataclass(frozen=True)
class SleeveMetrics:
    """One sleeve's results on one split, always with ``trial_count``."""

    sleeve_id: str
    split: DatasetSplit
    trial_count: int
    n_sessions: int
    total_return_gross: float
    total_return_net: float
    max_drawdown_net: float
    mean_one_way_turnover: float
    rank_ic: float | None
    rank_ic_n: int

    def as_dict(self) -> dict[str, object]:
        """JSON-ready payload. ``trial_count`` is never omitted."""
        return {
            "sleeve_id": self.sleeve_id,
            "split": self.split.value,
            "trial_count": self.trial_count,
            "n_sessions": self.n_sessions,
            "total_return_gross": self.total_return_gross,
            "total_return_net": self.total_return_net,
            "max_drawdown_net": self.max_drawdown_net,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "rank_ic": self.rank_ic,
            "rank_ic_n": self.rank_ic_n,
        }


def compound_return(returns: Sequence[float]) -> float:
    """Compound a sequence of simple returns."""
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def max_drawdown(returns: Sequence[float]) -> float:
    """Peak-to-trough drawdown of an equity curve built from ``returns``.

    Returns a non-negative fraction (0.10 is a 10% drawdown).
    """
    peak = 1.0
    equity = 1.0
    worst = 0.0
    for item in returns:
        equity *= 1.0 + item
        if equity > peak:
            peak = equity
        if peak > 0:
            worst = max(worst, 1.0 - equity / peak)
    return worst


def mean_or_zero(values: Sequence[float]) -> float:
    """Arithmetic mean, or 0.0 when ``values`` is empty."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation, or ``None`` when undefined."""
    if len(x) != len(y) or len(x) < 3:
        return None
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    den_x = math.sqrt(sum((a - mean_x) ** 2 for a in x))
    den_y = math.sqrt(sum((b - mean_y) ** 2 for b in y))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return num / (den_x * den_y)


def _average_ranks(values: Sequence[float]) -> list[float]:
    n = len(values)
    order = sorted(range(n), key=lambda index: values[index])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rank correlation."""
    if len(x) != len(y) or len(x) < 3:
        return None
    return pearson(_average_ranks(x), _average_ranks(y))


def one_way_turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    """One-way turnover: half the L1 distance between weight vectors."""
    names = set(previous) | set(current)
    l1 = sum(abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names)
    return 0.5 * l1


def apply_cost(gross_return: float, turnover: float, one_way_cost_bps: float) -> float:
    """Subtract one-way costs charged on traded weight."""
    return gross_return - turnover * (one_way_cost_bps / 10_000.0)


__all__ = [
    "SleeveMetrics",
    "apply_cost",
    "compound_return",
    "max_drawdown",
    "mean_or_zero",
    "one_way_turnover",
    "pearson",
    "spearman",
]
