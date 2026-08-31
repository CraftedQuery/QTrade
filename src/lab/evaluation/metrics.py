"""Performance and skill metrics, reported against the comparators.

## What is measured, and what is deliberately not a target

`AGENTS.md` requires rank IC, turnover, drawdown, net-of-cost results, and a
simple comparator with every performance number. All of those are here.

Hit rate is computed and reported, and it is **not a target**. A strategy can be
right most of the time and lose money, or right a third of the time and make it;
optimising a win rate optimises the wrong thing. It appears in the report so its
absence cannot be mistaken for an oversight.

Every number carries its trial count via the experiment record, so no result can
be quoted without the search budget that produced it.

## Rank IC: two conventions, both reported

The information coefficient is the rank correlation between predicted and
realised returns. There are two defensible ways to compute it across time:

* **per-date** — correlate within each rebalance date, then average. This is the
  standard convention and is honest about variation over time: it shows whether
  skill was steady or came from a handful of dates.
* **pooled** — correlate every (prediction, outcome) pair at once. Simpler, but
  it lets a few unusual dates dominate and hides time variation.

Both are computed. They can differ substantially, and a large gap is itself
information: it means the signal's skill was concentrated in time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from lab.costs import CostModel

TRADING_SESSIONS_PER_YEAR = 252


def _rank(values: Sequence[float]) -> list[float]:
    """Fractional ranks, averaging ties."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
            stop += 1
        average = (index + stop) / 2 + 1
        for position in range(index, stop + 1):
            ranks[order[position]] = average
        index = stop + 1
    return ranks


def spearman(predicted: Sequence[float], realised: Sequence[float]) -> float | None:
    """Spearman rank correlation, or None when it is undefined.

    Undefined for fewer than two pairs, or when either side is entirely tied —
    a constant series has no ranking to correlate.
    """
    if len(predicted) != len(realised):
        raise ValueError("predicted and realised must be the same length")
    if len(predicted) < 2:
        return None

    x, y = _rank(predicted), _rank(realised)
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    variance_x = sum((a - mean_x) ** 2 for a in x)
    variance_y = sum((b - mean_y) ** 2 for b in y)
    if variance_x <= 0 or variance_y <= 0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


@dataclass(frozen=True)
class RankIC:
    """Rank information coefficient under both conventions.

    Attributes:
        per_date_mean: Mean of the within-date correlations. The standard figure.
        per_date_std: Standard deviation across dates.
        per_date_t_stat: Mean divided by its standard error. Roughly, whether
            the skill is distinguishable from zero.
        dates: How many dates contributed a defined correlation.
        pooled: Correlation over all pairs at once, ignoring dates.
    """

    per_date_mean: float | None
    per_date_std: float | None
    per_date_t_stat: float | None
    dates: int
    pooled: float | None

    @property
    def concentration_gap(self) -> float | None:
        """Difference between pooled and per-date IC.

        A large gap means skill was concentrated in a few dates rather than
        being steady, which the pooled figure alone would hide.
        """
        if self.pooled is None or self.per_date_mean is None:
            return None
        return self.pooled - self.per_date_mean


def rank_ic(
    predictions_by_date: Mapping[datetime, Sequence[tuple[float, float]]],
) -> RankIC:
    """Rank IC across dates, computed both per-date and pooled.

    Args:
        predictions_by_date: For each decision time, the (predicted, realised)
            pairs observed on that date.

    Returns:
        Both conventions, with the dispersion of the per-date figure.
    """
    per_date: list[float] = []
    pooled_predicted: list[float] = []
    pooled_realised: list[float] = []

    for _, pairs in sorted(predictions_by_date.items()):
        if not pairs:
            continue
        predicted = [pair[0] for pair in pairs]
        realised = [pair[1] for pair in pairs]
        pooled_predicted.extend(predicted)
        pooled_realised.extend(realised)
        correlation = spearman(predicted, realised)
        if correlation is not None:
            per_date.append(correlation)

    mean = std = t_stat = None
    if per_date:
        mean = sum(per_date) / len(per_date)
        if len(per_date) > 1:
            variance = sum((value - mean) ** 2 for value in per_date) / (len(per_date) - 1)
            std = math.sqrt(variance)
            if std > 0:
                t_stat = mean / (std / math.sqrt(len(per_date)))

    return RankIC(
        per_date_mean=mean,
        per_date_std=std,
        per_date_t_stat=t_stat,
        dates=len(per_date),
        pooled=spearman(pooled_predicted, pooled_realised) if pooled_predicted else None,
    )


def turnover(previous: Mapping[str, Decimal], target: Mapping[str, Decimal]) -> Decimal:
    """Total absolute weight change between two portfolios.

    A full switch out of one name into another is a turnover of 2: one weight
    sold and one bought, both of which are paid for.
    """
    symbols = set(previous) | set(target)
    return sum(
        (
            abs(target.get(symbol, Decimal(0)) - previous.get(symbol, Decimal(0)))
            for symbol in symbols
        ),
        start=Decimal(0),
    )


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline, as a positive fraction."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def equity_curve(returns: Sequence[float], start: float = 1.0) -> list[float]:
    """Compounded equity from a series of period returns."""
    equity = [start]
    for value in returns:
        equity.append(equity[-1] * (1 + value))
    return equity


@dataclass(frozen=True)
class PerformanceSummary:
    """Performance of one strategy over an evaluation window.

    Every figure is net of costs unless its name says gross. ``hit_rate`` is
    reported but is explicitly not a target.
    """

    name: str
    periods: int
    periods_per_year: float
    gross_return: float
    net_return: float
    cost_drag: float
    annualised_return: float
    annualised_volatility: float
    sharpe: float | None
    max_drawdown: float
    average_turnover: float
    hit_rate: float
    equity: tuple[float, ...] = field(repr=False, default=())

    @property
    def cost_share_of_gross(self) -> float | None:
        """Fraction of the gross return consumed by costs."""
        if self.gross_return == 0:
            return None
        return self.cost_drag / abs(self.gross_return)


def summarise(
    name: str,
    period_returns: Sequence[float],
    turnovers: Sequence[Decimal],
    cost_model: CostModel,
    periods_per_year: float,
) -> PerformanceSummary:
    """Summarise one strategy's performance, net of costs.

    Args:
        name: Strategy name, for the comparator table.
        period_returns: Gross return for each holding period.
        turnovers: Turnover incurred entering each period. Same length as
            ``period_returns``.
        cost_model: Costs to charge against the turnover.
        periods_per_year: Rebalances per year, used to annualise.

    Returns:
        The summary. Gross and net are both reported, so the cost drag is visible
        rather than buried.
    """
    if len(period_returns) != len(turnovers):
        raise ValueError("period_returns and turnovers must be the same length")

    costs = [float(cost_model.cost_fraction(value)) for value in turnovers]
    net = [gross - cost for gross, cost in zip(period_returns, costs, strict=True)]

    gross_equity = equity_curve(period_returns)
    net_equity = equity_curve(net)
    gross_total = gross_equity[-1] - 1
    net_total = net_equity[-1] - 1

    periods = len(net)
    if periods and net_equity[-1] > 0:
        annualised = net_equity[-1] ** (periods_per_year / periods) - 1
    else:
        annualised = 0.0

    if periods > 1:
        mean = sum(net) / periods
        variance = sum((value - mean) ** 2 for value in net) / (periods - 1)
        volatility = math.sqrt(variance) * math.sqrt(periods_per_year)
    else:
        volatility = 0.0

    return PerformanceSummary(
        name=name,
        periods=periods,
        periods_per_year=periods_per_year,
        gross_return=gross_total,
        net_return=net_total,
        cost_drag=sum(costs),
        annualised_return=annualised,
        annualised_volatility=volatility,
        sharpe=(annualised / volatility) if volatility > 0 else None,
        max_drawdown=max_drawdown(net_equity),
        average_turnover=float(sum(turnovers) / len(turnovers)) if turnovers else 0.0,
        # Reported, never optimised. See the module docstring.
        hit_rate=(sum(1 for value in net if value > 0) / periods) if periods else 0.0,
        equity=tuple(net_equity),
    )


__all__ = [
    "TRADING_SESSIONS_PER_YEAR",
    "PerformanceSummary",
    "RankIC",
    "equity_curve",
    "max_drawdown",
    "rank_ic",
    "spearman",
    "summarise",
    "turnover",
]
