"""Baseline strategies: the comparators every result must beat to mean anything.

A signal that beats nothing is not a finding. These four are the controls:

* **cash** — hold nothing. The floor. A strategy that cannot beat cash after
  costs has no reason to exist.
* **benchmark** — hold one ETF. What the owner could have done with no work.
* **equal weight** — hold the whole universe in equal parts. The comparator that
  usually embarrasses a signal, because most of what looks like skill is
  exposure.
* **momentum** — rank on a feature and hold the top slice. The candidate.

Every strategy emits a :class:`~lab.contracts.execution.Proposal`, so all four go
through the same risk engine and the same cost model. A comparator evaluated on a
different path is not a comparator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from lab.contracts import Bar, FeatureSnapshot, Proposal, ProposalLine
from lab.features import BarWindow

WEIGHT_PLACES = Decimal("0.000001")


def _even_weights(count: int, invested: Decimal) -> list[Decimal]:
    """Split ``invested`` into ``count`` equal weights that never exceed it.

    Rounds each weight down, so accumulated rounding leaves a little extra cash
    rather than silently manufacturing leverage the Proposal contract rejects.
    """
    if count <= 0:
        return []
    each = (invested / count).quantize(WEIGHT_PLACES, rounding=ROUND_DOWN)
    return [each] * count


class Strategy(ABC):
    """A named strategy that proposes a target portfolio at a decision time."""

    name: str
    version: str = "1.0.0"

    @abstractmethod
    def propose(
        self,
        as_of: datetime,
        universe: Sequence[str],
        snapshots: Sequence[FeatureSnapshot],
        bars: Sequence[Bar],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        """Return the target portfolio for this decision time."""

    def _proposal(
        self,
        as_of: datetime,
        lines: list[ProposalLine],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        return Proposal(
            proposal_id=proposal_id,
            experiment_id=experiment_id,
            strategy_version=self.version,
            as_of=as_of,
            lines=lines,
            created_at=as_of,
        )


def _reference_price(symbol: str, bars: Sequence[Bar], as_of: datetime) -> Decimal | None:
    """Latest close knowable at ``as_of``, via the same window features use."""
    return BarWindow(symbol, bars, as_of).close_at(0)


class CashStrategy(Strategy):
    """Hold nothing. The floor every other result is measured against."""

    name = "cash"

    def propose(
        self,
        as_of: datetime,
        universe: Sequence[str],
        snapshots: Sequence[FeatureSnapshot],
        bars: Sequence[Bar],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        return self._proposal(as_of, [], experiment_id, proposal_id)


class BenchmarkStrategy(Strategy):
    """Hold a single instrument at full invested weight."""

    name = "benchmark"

    def __init__(self, symbol: str, invested: Decimal = Decimal("1")) -> None:
        self.symbol = symbol
        self.invested = invested

    def propose(
        self,
        as_of: datetime,
        universe: Sequence[str],
        snapshots: Sequence[FeatureSnapshot],
        bars: Sequence[Bar],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        price = _reference_price(self.symbol, bars, as_of)
        lines = (
            []
            if price is None
            else [
                ProposalLine(
                    symbol=self.symbol,
                    target_weight=self.invested,
                    reference_price=price,
                )
            ]
        )
        return self._proposal(as_of, lines, experiment_id, proposal_id)


class EqualWeightStrategy(Strategy):
    """Hold every eligible name in equal parts.

    The comparator that usually embarrasses a signal: much of what looks like
    stock-picking skill turns out to be plain market exposure.
    """

    name = "equal_weight"

    def __init__(self, invested: Decimal = Decimal("1")) -> None:
        self.invested = invested

    def propose(
        self,
        as_of: datetime,
        universe: Sequence[str],
        snapshots: Sequence[FeatureSnapshot],
        bars: Sequence[Bar],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        priced = [
            (symbol, price)
            for symbol in sorted(universe)
            if (price := _reference_price(symbol, bars, as_of)) is not None
        ]
        weights = _even_weights(len(priced), self.invested)
        lines = [
            ProposalLine(symbol=symbol, target_weight=weight, reference_price=price)
            for (symbol, price), weight in zip(priced, weights, strict=True)
        ]
        return self._proposal(as_of, lines, experiment_id, proposal_id)


class MomentumStrategy(Strategy):
    """Hold the top slice of the universe by one feature, equally weighted.

    Names whose feature is missing are skipped, never treated as zero: an absent
    value means "not enough history", and ranking it against real values would
    invent a signal.
    """

    name = "momentum"

    def __init__(
        self,
        feature: str = "mom_252_21",
        top_n: int = 10,
        invested: Decimal = Decimal("1"),
    ) -> None:
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        self.feature = feature
        self.top_n = top_n
        self.invested = invested

    def propose(
        self,
        as_of: datetime,
        universe: Sequence[str],
        snapshots: Sequence[FeatureSnapshot],
        bars: Sequence[Bar],
        experiment_id: str,
        proposal_id: str,
    ) -> Proposal:
        eligible = set(universe)
        ranked = sorted(
            (
                (snapshot.symbol, value)
                for snapshot in snapshots
                if snapshot.symbol in eligible
                and (value := snapshot.values.get(self.feature)) is not None
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )[: self.top_n]

        priced = [
            (symbol, price)
            for symbol, _ in ranked
            if (price := _reference_price(symbol, bars, as_of)) is not None
        ]
        weights = _even_weights(len(priced), self.invested)
        lines = [
            ProposalLine(symbol=symbol, target_weight=weight, reference_price=price)
            for (symbol, price), weight in zip(priced, weights, strict=True)
        ]
        return self._proposal(as_of, lines, experiment_id, proposal_id)


__all__ = [
    "BenchmarkStrategy",
    "CashStrategy",
    "EqualWeightStrategy",
    "MomentumStrategy",
    "Strategy",
]
