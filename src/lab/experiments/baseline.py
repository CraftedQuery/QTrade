"""One-command baseline: ``python -m lab.experiments.baseline``.

Registers the experiment *before* any metric is computed, trains and
validates without touching the holdout, then evaluates the holdout in a
separate module.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from lab.config import REPO_ROOT
from lab.contracts import Bar, Experiment
from lab.contracts.enums import ExperimentStatus
from lab.data.alpaca import alpaca_keys_present, fetch_daily_bars
from lab.data.generate import generate_daily_bars
from lab.experiments.config import ExperimentConfig, load_experiment_config
from lab.experiments.holdout import HoldoutResult, evaluate_holdout
from lab.experiments.register import register_experiment
from lab.experiments.splits import WalkForwardSplits, build_walk_forward
from lab.experiments.train import TrainingResult, run_training
from lab.universe.dated import DatedUniverse, load_universe

DEFAULT_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "experiments"


def load_bars(
    source: str,
    config: ExperimentConfig,
    universe: DatedUniverse,
) -> list[Bar]:
    """Load bars from committed fixtures or optional Alpaca historical."""
    symbols = [item.symbol for item in universe.instruments]
    if source == "fixture":
        return generate_daily_bars(
            symbols,
            config.fixture_bar_start,
            config.fixture_bar_end,
            seed=config.fixture_seed,
            source=config.fixture_source,
        )
    if source == "alpaca":
        return fetch_daily_bars(symbols, config.fixture_bar_start, config.fixture_bar_end)
    raise ValueError(f"unknown bar source {source!r}")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _metrics_payload(rows: Sequence[object]) -> list[dict[str, object]]:
    return [row.as_dict() for row in rows]  # type: ignore[attr-defined]


def _format_block(title: str, result_metrics: Sequence[object]) -> str:
    lines = [title]
    for row in result_metrics:
        payload = row.as_dict()  # type: ignore[attr-defined]
        ic = payload["rank_ic"]
        ic_text = "n/a" if ic is None else f"{ic:.4f} (n={payload['rank_ic_n']})"
        lines.append(
            f"  {payload['sleeve_id']:14} split={payload['split']:10} "
            f"trial_count={payload['trial_count']}  "
            f"net={payload['total_return_net']:+.4f}  "
            f"gross={payload['total_return_gross']:+.4f}  "
            f"dd={payload['max_drawdown_net']:.4f}  "
            f"to={payload['mean_one_way_turnover']:.4f}  "
            f"rank_ic={ic_text}"
        )
    return "\n".join(lines)


def run_baseline(
    *,
    source: str = "fixture",
    output_dir: Path | None = None,
    config_path: Path | None = None,
    registered_at: datetime | None = None,
) -> dict[str, object]:
    """Register, train/validate, then evaluate holdout. Returns the report."""
    config = load_experiment_config(config_path)
    universe = load_universe(config.universe_path)
    splits: WalkForwardSplits = build_walk_forward(
        train_start=config.train_start,
        train_end=config.train_end,
        validation_start=config.validation_start,
        validation_end=config.validation_end,
        holdout_start=config.holdout_start,
        holdout_end=config.holdout_end,
        purge=config.purge,
        embargo=config.embargo,
        horizon=config.horizon,
    )
    stamp = registered_at if registered_at is not None else datetime.now(tz=UTC)
    experiment = register_experiment(config, splits, registered_at=stamp)
    if not experiment.holdout_is_sealed:
        raise RuntimeError("experiment must be sealed at registration")

    bars = load_bars(source, config, universe)
    root = output_dir if output_dir is not None else DEFAULT_ARTIFACT_DIR / experiment.experiment_id
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "experiment.json", json.loads(experiment.model_dump_json()))

    running = experiment.model_copy(update={"status": ExperimentStatus.RUNNING})
    training = run_training(running, config, universe, bars, created_at=stamp)
    _write_json(root / "training.json", {"metrics": _metrics_payload(training.metrics)})

    unsealed, holdout = evaluate_holdout(
        running, config, universe, bars, created_at=stamp, unsealed_at=stamp
    )
    _write_json(root / "holdout.json", {"metrics": _metrics_payload(holdout.metrics)})
    _write_json(root / "experiment.json", json.loads(unsealed.model_dump_json()))

    report = {
        "experiment_id": unsealed.experiment_id,
        "trial_count": unsealed.trial_count,
        "config_hash": unsealed.config_hash,
        "code_git_sha": unsealed.code_git_sha,
        "bar_source": source,
        "bar_count": len(bars),
        "universe_id": universe.universe_id,
        "universe_size": len(universe.instruments),
        "survivorship_flagged": universe.survivorship_flagged,
        "holdout_unsealed_at": unsealed.holdout_unsealed_at.isoformat()
        if unsealed.holdout_unsealed_at
        else None,
        "training": _metrics_payload(training.metrics),
        "holdout": _metrics_payload(holdout.metrics),
    }
    _write_json(root / "report.json", report)
    report["_text"] = _render(unsealed, universe, source, len(bars), training, holdout)
    report["_artifact_dir"] = str(root)
    return report


def _render(
    experiment: Experiment,
    universe: DatedUniverse,
    source: str,
    bar_count: int,
    training: TrainingResult,
    holdout: HoldoutResult,
) -> str:
    warning = (
        "SURVIVORSHIP: roster is not a point-in-time membership tape. "
        "listed_on/delisted_on are applied; failed names never on the roster are absent."
        if universe.survivorship_flagged
        else "point-in-time membership tape"
    )
    return "\n".join(
        [
            f"experiment_id: {experiment.experiment_id}",
            f"trial_count: {experiment.trial_count}",
            f"config_hash: {experiment.config_hash}",
            f"bars: {bar_count} from {source}",
            f"universe: {universe.universe_id} ({len(universe.instruments)} names)",
            f"survivorship: {warning}",
            "",
            _format_block(
                "train / validation (training code; holdout still sealed at this stage):",
                training.metrics,
            ),
            "",
            _format_block(
                f"holdout (holdout module; unsealed_at={holdout.unsealed_at.isoformat()}):",
                holdout.metrics,
            ),
            "",
            "Win rate is not a target. Compare momentum to cash, SPY, "
            "and equal weight, net of costs.",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``python -m lab.experiments.baseline``."""
    parser = argparse.ArgumentParser(description="Run the Release 0.2 baseline experiment.")
    parser.add_argument(
        "--source",
        choices=("fixture", "alpaca"),
        default="fixture",
        help="fixture (default, no secrets) or alpaca (paper keys in the environment)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Artifact directory.")
    parser.add_argument(
        "--config", type=Path, default=None, help="Override configs/experiment.yaml."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.source == "alpaca" and not alpaca_keys_present():
        print(
            "Alpaca keys are not set. Use --source fixture or export "
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (paper only).",
            file=sys.stderr,
        )
        return 2
    report = run_baseline(source=args.source, output_dir=args.output, config_path=args.config)
    print(report["_text"])
    print(f"\nwrote {report['_artifact_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
