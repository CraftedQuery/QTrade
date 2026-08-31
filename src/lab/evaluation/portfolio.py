"""Portfolio simulation: turning a sequence of proposals into realised returns.

## Where a backtest usually cheats

The proposal at *t* is built from information available at *t*. The return it
earns is measured from the close at *t* to the close at the next rebalance. Those
two facts have to stay separate, and the easy mistake is to let the decision see
the price that decides its own outcome.

The simulation here reads prices through
:class:`~lab.features.window.BarWindow`, the same component the features use, so
a weight can only ever be priced at a close that had already happened. A
position's return is then measured forward from that same close.

## What is charged

Turnover is the total absolute weight change between consecutive proposals, so
both sides of a switch are paid for. Cash earns nothing — the lab holds no
interest-rate assumption, and inventing one would flatter a strategy that sits
in cash.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from lab.contracts import Bar, Proposal
from lab.evaluation.metrics import turnover
from lab.features import BarWindow


@dataclass(frozen=True)
class Period:
    """One holding period between two rebalances.

    Attributes:
        start: Decision time the weights were set at.
        end: Decision time the position was unwound at.
        gross_return: Return earned over the period, before costs.
        turnover: Absolute weight change entering the period.
        held: Number of positions held.
    """

    start: datetime
    end: datetime
    gross_return: float
    turnover: Decimal
    held: int


def _closes_at(bars: Sequence[Bar], symbols: Sequence[str], as_of: datetime) -> dict[str, Decimal]:
    """Latest close knowable at ``as_of`` for each symbol, via the feature window."""
    prices: dict[str, Decimal] = {}
    for symbol in symbols:
        close = BarWindow(symbol, bars, as_of).close_at(0)
        if close is not None and close > 0:
            prices[symbol] = close
    return prices


def simulate(
    proposals: Sequence[tuple[datetime, Proposal]],
    bars: Sequence[Bar],
) -> list[Period]:
    """Simulate holding each proposal until the next rebalance.

    Args:
        proposals: (decision time, proposal) pairs in chronological order.
        bars: Price history covering the whole span.

    Returns:
        One :class:`Period` per holding interval. A run of *n* proposals yields
        *n - 1* periods: the final proposal has no subsequent rebalance at which
        to measure its outcome, and estimating one would be inventing data.

    Raises:
        ValueError: If the proposals are not in chronological order.
    """
    ordered = list(proposals)
    if any(a[0] >= b[0] for a, b in pairwise(ordered)):
        raise ValueError("proposals must be in strictly increasing time order")

    periods: list[Period] = []
    previous_weights: dict[str, Decimal] = {}

    for (start, proposal), (end, _) in pairwise(ordered):
        weights = {line.symbol: line.target_weight for line in proposal.lines}
        symbols = sorted(weights)

        entry = _closes_at(bars, symbols, start)
        exit_prices = _closes_at(bars, symbols, end)

        # A name without a price at both ends cannot be held; dropping it to cash
        # is the conservative reading, and it is what a real book would do when a
        # name stops trading.
        contribution = 0.0
        held = 0
        for symbol in symbols:
            if symbol not in entry or symbol not in exit_prices:
                continue
            change = float(exit_prices[symbol] / entry[symbol] - 1)
            contribution += float(weights[symbol]) * change
            held += 1

        periods.append(
            Period(
                start=start,
                end=end,
                gross_return=contribution,
                turnover=turnover(previous_weights, weights),
                held=held,
            )
        )
        previous_weights = weights

    return periods


def returns_and_turnovers(periods: Sequence[Period]) -> tuple[list[float], list[Decimal]]:
    """Split periods into the two series :func:`lab.evaluation.summarise` expects."""
    return (
        [period.gross_return for period in periods],
        [period.turnover for period in periods],
    )


__all__ = ["Period", "returns_and_turnovers", "simulate"]
