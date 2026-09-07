"""Turn 0.2 baseline sleeve weights into a :class:`Proposal`."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from lab.contracts import Bar, FeatureSnapshot, Proposal, ProposalLine
from lab.data.store import close_on, group_bars
from lab.experiments.baselines import (
    SLEEVE_CASH,
    SLEEVE_EQUAL_WEIGHT,
    SLEEVE_MOMENTUM,
    SLEEVE_SPY,
    weights_cash,
    weights_equal,
    weights_momentum,
    weights_spy,
)
from lab.experiments.config import ExperimentConfig
from lab.features.momentum import compute_momentum
from lab.universe.dated import DatedUniverse

SLEEVES = frozenset({SLEEVE_CASH, SLEEVE_EQUAL_WEIGHT, SLEEVE_MOMENTUM, SLEEVE_SPY})


def derive_proposal_id(experiment_id: str, sleeve: str, as_of: datetime) -> str:
    """Stable proposal id for one experiment, sleeve, and decision time."""
    digest = hashlib.sha256(f"{experiment_id}|{sleeve}|{as_of.isoformat()}".encode()).hexdigest()
    return f"prop-{digest[:32]}"


def proposal_from_weights(
    *,
    proposal_id: str,
    experiment_id: str,
    strategy_version: str,
    as_of: datetime,
    created_at: datetime,
    weights: Mapping[str, float | Decimal],
    prices: Mapping[str, Decimal],
) -> Proposal:
    """Build a long-or-cash proposal. Zero weights are omitted (cash)."""
    lines: list[ProposalLine] = []
    for symbol in sorted(weights):
        weight = Decimal(str(weights[symbol]))
        if weight <= 0:
            continue
        price = prices.get(symbol)
        if price is None or price <= 0:
            raise ValueError(f"missing reference price for {symbol}")
        lines.append(ProposalLine(symbol=symbol, target_weight=weight, reference_price=price))
    return Proposal(
        proposal_id=proposal_id,
        experiment_id=experiment_id,
        strategy_version=strategy_version,
        as_of=as_of,
        lines=lines,
        created_at=created_at,
    )


def sleeve_weights(
    sleeve: str,
    *,
    members: Sequence[str],
    benchmark: str,
    snapshots: Mapping[str, FeatureSnapshot] | None = None,
    lookback: int = 21,
) -> dict[str, float]:
    """Return target weights for one 0.2 sleeve."""
    if sleeve not in SLEEVES:
        raise ValueError(f"unknown sleeve {sleeve!r}")
    if sleeve == SLEEVE_CASH:
        return weights_cash(members)
    if sleeve == SLEEVE_SPY:
        return weights_spy(members, benchmark)
    if sleeve == SLEEVE_EQUAL_WEIGHT:
        return weights_equal(members)
    if snapshots is None:
        raise ValueError("momentum sleeve requires snapshots")
    return weights_momentum(snapshots, members, lookback)


def marks_at(
    bars: Sequence[Bar],
    as_of: datetime,
    symbols: Sequence[str],
) -> tuple[dict[str, Decimal], datetime | None]:
    """Latest eligible close per symbol, and the newest information time used."""
    grouped = group_bars(bars)
    prices: dict[str, Decimal] = {}
    newest: datetime | None = None
    for symbol in symbols:
        series = grouped.get(symbol, ())
        eligible = [bar for bar in series if bar.information_time <= as_of]
        close = close_on(grouped, symbol, as_of)
        if close is None:
            continue
        prices[symbol] = Decimal(str(close))
        if eligible:
            stamp = eligible[-1].information_time
            if newest is None or stamp > newest:
                newest = stamp
    return prices, newest


def proposal_from_baseline(
    *,
    sleeve: str,
    as_of: datetime,
    created_at: datetime,
    bars: Sequence[Bar],
    universe: DatedUniverse,
    config: ExperimentConfig,
    experiment_id: str,
) -> tuple[Proposal, dict[str, Decimal], datetime | None]:
    """Compute one sleeve's target book from the 0.2 baseline machinery."""
    day = as_of.date()
    members = list(universe.symbols_on(day))
    snapshots = None
    if sleeve == SLEEVE_MOMENTUM:
        grouped = group_bars(bars)
        snapshots = {
            symbol: compute_momentum(
                grouped.get(symbol, ()),
                symbol=symbol,
                as_of=as_of,
                lookback=config.lookback_sessions,
                snapshot_id=f"{experiment_id}:{sleeve}:{symbol}:{day.isoformat()}",
                computed_at=created_at,
            )
            for symbol in members
        }
    weights = sleeve_weights(
        sleeve,
        members=members,
        benchmark=universe.benchmark_symbol,
        snapshots=snapshots,
        lookback=config.lookback_sessions,
    )
    needed = sorted(set(members) | set(weights) | {universe.benchmark_symbol})
    prices, data_as_of = marks_at(bars, as_of, needed)
    proposal = proposal_from_weights(
        proposal_id=derive_proposal_id(experiment_id, sleeve, as_of),
        experiment_id=experiment_id,
        strategy_version=f"{sleeve}-{config.feature_set_version}",
        as_of=as_of,
        created_at=created_at,
        weights=weights,
        prices=prices,
    )
    return proposal, prices, data_as_of


__all__ = [
    "SLEEVES",
    "derive_proposal_id",
    "marks_at",
    "proposal_from_baseline",
    "proposal_from_weights",
    "sleeve_weights",
]
