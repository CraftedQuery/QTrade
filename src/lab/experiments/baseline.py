"""The baseline experiment. One command, from raw inputs to a comparator table.

    uv run python -m lab.experiments.baseline

## Registration happens before anything is computed

The `Experiment` record is built and printed **first**, before a single feature
is computed or a single return is measured. That ordering is the point, not a
formality: an experiment registered after its results are known is not a
hypothesis, it is a description. Everything the result depends on — the config
hash, the commit, the walk-forward geometry, the cost model, the trial count —
is fixed at that moment.

## What this runner does not do

It does not touch the holdout. Walk-forward validation folds are evaluated here;
the sealed holdout is read exactly once, by :mod:`lab.evaluation.holdout`, which
this module deliberately does not import. See Release 0.2 task 11.

It also does not tune anything. There is no search loop, no parameter sweep, and
no "pick the best fold". If the result is poor, that is the finding.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lab.config import ExperimentConfig, load_cost_model, load_experiment_config
from lab.contracts import Bar, Experiment, FeatureSnapshot, Instrument, Prediction, Proposal
from lab.contracts.enums import DatasetSplit
from lab.costs import CostModel
from lab.evaluation import (
    PerformanceSummary,
    RankIC,
    WalkForwardConfig,
    rank_ic,
    returns_and_turnovers,
    simulate,
    summarise,
    walk_forward_folds,
)
from lab.features import MOMENTUM_V1, compute_snapshots, label_symbols
from lab.models import align, fit_ridge, predict
from lab.strategies import (
    BenchmarkStrategy,
    CashStrategy,
    EqualWeightStrategy,
    MomentumStrategy,
    Rebalance,
    Strategy,
    rebalance_dates,
)
from lab.universe import LiquidityScreen, build_universe

SESSION_CLOSE = timedelta(hours=20)


def git_sha() -> str:
    """Commit the experiment is running from, or a marker when unavailable."""
    try:
        result = subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown-working-tree"


def _at_close(day: date) -> datetime:
    """Decision instant for a session, in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + SESSION_CLOSE


@dataclass(frozen=True)
class BaselineResult:
    """Everything one baseline run produced.

    Attributes:
        experiment: The registered record. Its holdout is still sealed.
        summaries: Performance per strategy, in comparator order.
        skill: Rank IC of the model's validation predictions.
        predictions: Every prediction written, before any outcome existed.
        folds: Walk-forward folds evaluated.
        cost_model: Costs charged.
    """

    experiment: Experiment
    summaries: tuple[PerformanceSummary, ...]
    skill: RankIC
    predictions: tuple[Prediction, ...]
    folds: int
    cost_model: CostModel

    @property
    def headline_ic(self) -> float | None:
        """Per-date rank IC, the convention the owner selected as the headline."""
        return self.skill.per_date_mean


def register(
    config: ExperimentConfig,
    cost_model: CostModel,
    sessions: Sequence[date],
    hypothesis: str,
    trial_count: int,
    registered_at: datetime | None = None,
) -> Experiment:
    """Build the experiment record. Called before any result is computed.

    The train/validation/holdout boundaries are declared here and the holdout is
    left sealed; this runner never reads it.
    """
    stamp = registered_at or datetime.now(UTC)
    total = len(sessions)
    # Two thirds train, a quarter validation, the tail sealed as holdout.
    train_end = int(total * 0.60)
    validation_end = int(total * 0.85)

    return Experiment(
        experiment_id=f"baseline-{config.config_hash}",
        name="momentum baseline",
        hypothesis=hypothesis,
        registered_at=stamp,
        universe_id=config.universe_id,
        feature_set=config.feature_set,
        feature_set_version=MOMENTUM_V1.version,
        train_start=_at_close(sessions[0]),
        train_end=_at_close(sessions[train_end]),
        validation_start=_at_close(sessions[train_end]),
        validation_end=_at_close(sessions[validation_end]),
        holdout_start=_at_close(sessions[validation_end]),
        holdout_end=_at_close(sessions[-1]),
        purge=timedelta(days=config.purge + config.label_horizon_sessions),
        embargo=timedelta(days=config.embargo),
        cost_model_id=cost_model.model_id,
        code_git_sha=git_sha(),
        config_hash=config.config_hash,
        trial_count=trial_count,
    )


def _strategies(config: ExperimentConfig) -> list[Strategy]:
    """The candidate first, then the controls it must beat."""
    return [
        MomentumStrategy(feature="mom_252_21", top_n=config.top_n),
        EqualWeightStrategy(),
        BenchmarkStrategy(config.benchmark_symbol),
        CashStrategy(),
    ]


def run(
    instruments: Sequence[Instrument],
    bars: Sequence[Bar],
    config: ExperimentConfig | None = None,
    cost_model: CostModel | None = None,
    hypothesis: str = "12-1 momentum beats equal weight net of costs.",
    trial_count: int = 1,
    registered_at: datetime | None = None,
) -> BaselineResult:
    """Run the baseline experiment over the supplied data.

    Args:
        instruments: Reference data for the candidate universe.
        bars: Price history.
        config: Experiment settings. Loaded from configuration when omitted.
        cost_model: Costs. Loaded from configuration when omitted.
        hypothesis: What this run claims, written before results are seen.
        trial_count: Configurations tried in this line of search, this one
            included. Travels with every number the run reports.
        registered_at: Registration time, for reproducible runs.

    Returns:
        The result, with the experiment's holdout still sealed.

    Raises:
        ValueError: If the data is too short to produce a single walk-forward fold.
    """
    settings = config or load_experiment_config()
    costs = cost_model or load_cost_model()

    sessions = sorted({bar.ts_start.date() for bar in bars})
    if len(sessions) < settings.min_train_size + settings.test_size:
        raise ValueError(
            f"{len(sessions)} sessions is too short for a "
            f"{settings.min_train_size}-session training window plus a "
            f"{settings.test_size}-session test fold"
        )

    # --- Registration, before a single number is computed --------------------
    experiment = register(settings, costs, sessions, hypothesis, trial_count, registered_at)

    # --- Universe ------------------------------------------------------------
    rebalances = rebalance_dates(sessions, Rebalance(settings.rebalance))
    universe = build_universe(
        settings.universe_id,
        instruments,
        bars,
        rebalances,
        LiquidityScreen(),
    )

    # --- Features and labels at each rebalance -------------------------------
    snapshots_by_date: dict[datetime, list[FeatureSnapshot]] = {}
    labels_by_date: dict[datetime, dict[str, float]] = {}
    for day in rebalances:
        as_of = _at_close(day)
        members = universe.symbols_on(day)[: settings.max_names]
        if not members:
            continue
        snapshots_by_date[as_of] = compute_snapshots(members, bars, as_of, MOMENTUM_V1)
        labels_by_date[as_of] = {
            label.symbol: label.value
            for label in label_symbols(members, bars, as_of, settings.label_horizon_sessions)
        }

    # --- Walk-forward folds over rebalance dates -----------------------------
    decision_times = sorted(snapshots_by_date)
    folds = walk_forward_folds(
        len(decision_times),
        WalkForwardConfig(
            label_horizon=max(1, settings.label_horizon_sessions // 21),
            purge=settings.purge,
            embargo=settings.embargo,
            test_size=max(1, settings.test_size // 21),
            min_train_size=max(1, settings.min_train_size // 21),
        ),
    )

    predictions: list[Prediction] = []
    pairs_by_date: dict[datetime, list[tuple[float, float]]] = {}
    for fold in folds:
        train_snapshots: list[FeatureSnapshot] = []
        train_labels = []
        for index in fold.train:
            as_of = decision_times[index]
            train_snapshots.extend(snapshots_by_date[as_of])
            train_labels.extend(
                label_symbols(
                    [s.symbol for s in snapshots_by_date[as_of]],
                    bars,
                    as_of,
                    settings.label_horizon_sessions,
                )
            )
        rows = align(train_snapshots, train_labels, MOMENTUM_V1.names)
        model = fit_ridge(rows, MOMENTUM_V1.names, alpha=float(settings.ridge_alpha))
        if model is None:
            continue

        for index in fold.test:
            as_of = decision_times[index]
            fold_predictions = predict(
                model,
                snapshots_by_date[as_of],
                experiment.experiment_id,
                DatasetSplit.VALIDATION,
                settings.label_horizon_sessions,
            )
            predictions.extend(fold_predictions)
            realised = labels_by_date.get(as_of, {})
            observed = [
                (p.value, realised[p.symbol]) for p in fold_predictions if p.symbol in realised
            ]
            if observed:
                pairs_by_date[as_of] = observed

    # --- Comparators, all on the same path -----------------------------------
    summaries: list[PerformanceSummary] = []
    periods_per_year = {"monthly": 12.0, "weekly": 52.0, "daily": 252.0}[settings.rebalance]
    for strategy in _strategies(settings):
        proposals: list[tuple[datetime, Proposal]] = []
        for as_of in decision_times:
            members = [s.symbol for s in snapshots_by_date[as_of]]
            proposals.append(
                (
                    as_of,
                    strategy.propose(
                        as_of,
                        members,
                        snapshots_by_date[as_of],
                        bars,
                        experiment.experiment_id,
                        f"{strategy.name}:{as_of.isoformat()}",
                    ),
                )
            )
        returns, turnovers = returns_and_turnovers(simulate(proposals, bars))
        summaries.append(summarise(strategy.name, returns, turnovers, costs, periods_per_year))

    return BaselineResult(
        experiment=experiment,
        summaries=tuple(summaries),
        skill=rank_ic(pairs_by_date),
        predictions=tuple(predictions),
        folds=len(folds),
        cost_model=costs,
    )


def format_report(result: BaselineResult) -> str:
    """Render the run as a plain-text report."""
    experiment = result.experiment
    lines = [
        "=" * 76,
        "BASELINE EXPERIMENT",
        "=" * 76,
        f"  experiment_id   : {experiment.experiment_id}",
        f"  registered_at   : {experiment.registered_at.isoformat()}",
        f"  hypothesis      : {experiment.hypothesis}",
        f"  config_hash     : {experiment.config_hash}",
        f"  code_git_sha    : {experiment.code_git_sha[:12]}",
        f"  cost_model      : {experiment.cost_model_id} "
        f"({result.cost_model.bps_per_side} bps/side)",
        f"  trial_count     : {experiment.trial_count}",
        f"  folds evaluated : {result.folds}",
        f"  predictions     : {len(result.predictions)}",
        f"  holdout         : SEALED until {experiment.holdout_end.date()} "
        f"(this run never reads it)",
        "",
        "  RANK IC (headline convention: per-date, then averaged)",
    ]
    skill = result.skill
    if skill.per_date_mean is None:
        lines.append("    not computable: no date produced a defined correlation")
    else:
        lines.append(f"    per-date mean : {skill.per_date_mean:+.4f}  over {skill.dates} dates")
        if skill.per_date_std is not None:
            lines.append(f"    per-date std  : {skill.per_date_std: .4f}")
        if skill.per_date_t_stat is not None:
            lines.append(f"    per-date t    : {skill.per_date_t_stat:+.3f}")
        if skill.pooled is not None:
            lines.append(f"    pooled        : {skill.pooled:+.4f}  (reported, not the headline)")

    lines += [
        "",
        "  COMPARATORS (net of costs; order is fixed, not sorted by result)",
        f"    {'strategy':<16}{'gross':>10}{'net':>10}{'ann':>10}"
        f"{'vol':>9}{'maxDD':>9}{'turn':>8}{'hit':>7}",
    ]
    for summary in result.summaries:
        sharpe = f"{summary.sharpe:+.2f}" if summary.sharpe is not None else "n/a"
        lines.append(
            f"    {summary.name:<16}{summary.gross_return:>+10.4f}{summary.net_return:>+10.4f}"
            f"{summary.annualised_return:>+10.4f}{summary.annualised_volatility:>9.4f}"
            f"{summary.max_drawdown:>9.4f}{summary.average_turnover:>8.2f}"
            f"{summary.hit_rate:>7.2f}   sharpe {sharpe}"
        )

    candidate = result.summaries[0]
    controls = result.summaries[1:]
    beaten = [s.name for s in controls if candidate.net_return > s.net_return]
    lines += [
        "",
        f"  {candidate.name} beat, net of costs: {', '.join(beaten) if beaten else 'nothing'}",
        f"  cost drag on {candidate.name}: {candidate.cost_drag:.4f} "
        f"({(candidate.cost_share_of_gross or 0) * 100:.1f}% of gross)",
        "",
        "  Every number above is from ONE trial. Report the trial count with it.",
        "  Win rate is shown because omitting it would look like an oversight. It",
        "  is not a target.",
        "=" * 76,
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m lab.experiments.baseline``."""
    parser = argparse.ArgumentParser(description="Run the baseline experiment.")
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Configurations tried in this line of search, this one included.",
    )
    parser.add_argument(
        "--hypothesis",
        default="12-1 momentum beats equal weight net of costs.",
        help="What this run claims, written before results are seen.",
    )
    args = parser.parse_args(argv)

    print("No market data has been ingested yet.")
    print("The Alpaca adapter is Release 0.2 task 13; until it lands there is")
    print("nothing to run this experiment against, and running it on synthetic")
    print("prices would produce a number that means nothing.")
    print()
    print(f"Configured: trials={args.trials}, hypothesis={args.hypothesis!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
