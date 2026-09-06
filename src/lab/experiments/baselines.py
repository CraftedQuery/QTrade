"""Cash, SPY, equal-weight, and simple momentum sleeves.

Long or cash only. No shorts. Costs are a research assumption
(``one_way_cost_bps``), not an owner-mandate risk number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from lab.contracts import Bar, Experiment, FeatureSnapshot, Prediction
from lab.contracts.enums import DatasetSplit
from lab.data.calendar import as_of_close
from lab.data.store import group_bars, session_return
from lab.experiments.config import ExperimentConfig
from lab.experiments.metrics import (
    SleeveMetrics,
    apply_cost,
    compound_return,
    max_drawdown,
    mean_or_zero,
    one_way_turnover,
    spearman,
)
from lab.experiments.splits import WalkForwardSplits, splits_from_experiment
from lab.features.momentum import compute_momentum
from lab.universe.dated import DatedUniverse

SLEEVE_CASH = "cash"
SLEEVE_SPY = "spy"
SLEEVE_EQUAL_WEIGHT = "equal_weight"
SLEEVE_MOMENTUM = "momentum"
SLEEVE_IDS = (SLEEVE_CASH, SLEEVE_SPY, SLEEVE_EQUAL_WEIGHT, SLEEVE_MOMENTUM)


@dataclass(frozen=True)
class SplitEvaluation:
    """Sleeve metrics and outcome-free predictions for one split."""

    split: DatasetSplit
    metrics: tuple[SleeveMetrics, ...]
    predictions: tuple[Prediction, ...]
    snapshots: tuple[FeatureSnapshot, ...]


def session_days(bars: Sequence[Bar]) -> list[date]:
    """Sorted unique session dates present in ``bars``."""
    return sorted({bar.ts_start.date() for bar in bars})


def weights_cash(_members: Sequence[str]) -> dict[str, float]:
    """100% cash."""
    return {}


def weights_spy(members: Sequence[str], benchmark: str) -> dict[str, float]:
    """100% benchmark when it is a member, otherwise cash."""
    if benchmark in members:
        return {benchmark: 1.0}
    return {}


def weights_equal(members: Sequence[str]) -> dict[str, float]:
    """Equal weight across ``members``. Empty members => cash."""
    if not members:
        return {}
    share = 1.0 / len(members)
    return dict.fromkeys(members, share)


def weights_momentum(
    snapshots: Mapping[str, FeatureSnapshot],
    members: Sequence[str],
    lookback: int,
) -> dict[str, float]:
    """Equal-weight the top half by momentum. Missing scores are skipped."""
    key = f"mom_{lookback}d"
    scored: list[tuple[str, float]] = []
    for symbol in members:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            continue
        value = snapshot.values.get(key)
        if value is None:
            continue
        scored.append((symbol, value))
    if len(scored) < 2:
        return {}
    scored.sort(key=lambda item: item[1], reverse=True)
    take = max(1, len(scored) // 2)
    chosen = [symbol for symbol, _ in scored[:take]]
    share = 1.0 / len(chosen)
    return dict.fromkeys(chosen, share)


def _forward_close_return(
    series: Sequence[Bar],
    as_of: datetime,
    sessions: int,
) -> float | None:
    eligible = [bar for bar in series if bar.information_time <= as_of]
    later = [bar for bar in series if bar.information_time > as_of]
    if not eligible or len(later) < sessions:
        return None
    start = float(eligible[-1].close)
    end = float(later[sessions - 1].close)
    if start == 0:
        return None
    return end / start - 1.0


def evaluate_sleeves(
    experiment: Experiment,
    config: ExperimentConfig,
    universe: DatedUniverse,
    bars: Sequence[Bar],
    split: DatasetSplit,
    *,
    created_at: datetime,
) -> SplitEvaluation:
    """Score every sleeve on ``split`` only.

    Features at day *T* use bars with ``information_time <= T``. The return
    booked for that decision is the next session's close-to-close move, so
    the signal never reads the outcome bar.
    """
    splits: WalkForwardSplits = splits_from_experiment(experiment, horizon=config.horizon)
    grouped = group_bars(bars)
    days = session_days(bars)
    signal_days = [day for day in days if splits.assign(as_of_close(day)) is split]
    if not signal_days:
        empty = tuple(
            SleeveMetrics(
                sleeve_id=sleeve,
                split=split,
                trial_count=experiment.trial_count,
                n_sessions=0,
                total_return_gross=0.0,
                total_return_net=0.0,
                max_drawdown_net=0.0,
                mean_one_way_turnover=0.0,
                rank_ic=None,
                rank_ic_n=0,
            )
            for sleeve in SLEEVE_IDS
        )
        return SplitEvaluation(split=split, metrics=empty, predictions=(), snapshots=())

    day_index = {day: index for index, day in enumerate(days)}
    snapshots_by_day: dict[date, dict[str, FeatureSnapshot]] = {}
    all_snapshots: list[FeatureSnapshot] = []
    predictions: list[Prediction] = []
    ic_pairs: list[tuple[float, float]] = []

    for position, day in enumerate(signal_days):
        as_of = as_of_close(day)
        members = list(universe.symbols_on(day))
        snaps: dict[str, FeatureSnapshot] = {}
        for symbol in members:
            snap = compute_momentum(
                grouped.get(symbol, ()),
                symbol=symbol,
                as_of=as_of,
                lookback=config.lookback_sessions,
                snapshot_id=f"{experiment.experiment_id}:{split.value}:{symbol}:{day.isoformat()}",
                computed_at=created_at,
            )
            snaps[symbol] = snap
            all_snapshots.append(snap)
            score = snap.values.get(f"mom_{config.lookback_sessions}d")
            if score is None:
                continue
            predictions.append(
                Prediction(
                    prediction_id=f"{experiment.experiment_id}:{split.value}:{symbol}:{day.isoformat()}",
                    experiment_id=experiment.experiment_id,
                    model_version=f"{config.feature_set}-{config.feature_set_version}",
                    symbol=symbol,
                    as_of=as_of,
                    horizon=config.horizon,
                    feature_snapshot_id=snap.snapshot_id,
                    value=score,
                    split=split,
                    created_at=created_at,
                )
            )
            if position % config.rebalance_every_sessions == 0:
                fwd = _forward_close_return(
                    grouped.get(symbol, ()), as_of, config.lookback_sessions
                )
                if fwd is not None:
                    ic_pairs.append((score, fwd))
        snapshots_by_day[day] = snaps

    rank_ic = spearman([a for a, _ in ic_pairs], [b for _, b in ic_pairs]) if ic_pairs else None
    rank_ic_n = len(ic_pairs)

    sleeve_weights: dict[str, dict[str, float]] = {
        SLEEVE_CASH: {},
        SLEEVE_SPY: {},
        SLEEVE_EQUAL_WEIGHT: {},
        SLEEVE_MOMENTUM: {},
    }
    previous: dict[str, dict[str, float]] = {sleeve: {} for sleeve in SLEEVE_IDS}
    gross: dict[str, list[float]] = {sleeve: [] for sleeve in SLEEVE_IDS}
    net: dict[str, list[float]] = {sleeve: [] for sleeve in SLEEVE_IDS}
    turnovers: dict[str, list[float]] = {sleeve: [] for sleeve in SLEEVE_IDS}
    cost_bps = float(config.one_way_cost_bps)

    for position, day in enumerate(signal_days):
        idx = day_index[day]
        if idx + 1 >= len(days):
            break
        next_day = days[idx + 1]
        as_of = as_of_close(day)
        next_as_of = as_of_close(next_day)
        members = list(universe.symbols_on(day))
        rebalance = position % config.rebalance_every_sessions == 0
        if rebalance:
            snaps = snapshots_by_day[day]
            sleeve_weights[SLEEVE_CASH] = weights_cash(members)
            sleeve_weights[SLEEVE_SPY] = weights_spy(members, universe.benchmark_symbol)
            sleeve_weights[SLEEVE_EQUAL_WEIGHT] = weights_equal(members)
            sleeve_weights[SLEEVE_MOMENTUM] = weights_momentum(
                snaps, members, config.lookback_sessions
            )
        for sleeve in SLEEVE_IDS:
            current = sleeve_weights[sleeve]
            traded = one_way_turnover(previous[sleeve], current) if rebalance else 0.0
            asset_return = 0.0
            for symbol, weight in current.items():
                move = session_return(grouped, symbol, as_of, next_as_of)
                if move is not None:
                    asset_return += weight * move
            gross[sleeve].append(asset_return)
            net[sleeve].append(apply_cost(asset_return, traded, cost_bps))
            turnovers[sleeve].append(traded)
            previous[sleeve] = dict(current)

    metrics = []
    for sleeve in SLEEVE_IDS:
        metrics.append(
            SleeveMetrics(
                sleeve_id=sleeve,
                split=split,
                trial_count=experiment.trial_count,
                n_sessions=len(net[sleeve]),
                total_return_gross=compound_return(gross[sleeve]),
                total_return_net=compound_return(net[sleeve]),
                max_drawdown_net=max_drawdown(net[sleeve]),
                mean_one_way_turnover=mean_or_zero(turnovers[sleeve]),
                rank_ic=rank_ic if sleeve == SLEEVE_MOMENTUM else None,
                rank_ic_n=rank_ic_n if sleeve == SLEEVE_MOMENTUM else 0,
            )
        )
    return SplitEvaluation(
        split=split,
        metrics=tuple(metrics),
        predictions=tuple(predictions),
        snapshots=tuple(all_snapshots),
    )


__all__ = [
    "SLEEVE_CASH",
    "SLEEVE_EQUAL_WEIGHT",
    "SLEEVE_IDS",
    "SLEEVE_MOMENTUM",
    "SLEEVE_SPY",
    "SplitEvaluation",
    "evaluate_sleeves",
    "session_days",
    "weights_cash",
    "weights_equal",
    "weights_momentum",
    "weights_spy",
]
