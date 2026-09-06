"""Acceptance test #3: holdout evaluation is separate from training code."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path

from lab.contracts.enums import DatasetSplit
from lab.data.generate import generate_daily_bars
from lab.experiments.config import load_experiment_config
from lab.experiments.register import register_experiment
from lab.experiments.splits import build_walk_forward
from lab.experiments.train import run_training
from lab.universe.dated import load_universe

TRAIN_PATH = Path(__file__).resolve().parents[1] / "src" / "lab" / "experiments" / "train.py"
HOLDOUT_PATH = Path(__file__).resolve().parents[1] / "src" / "lab" / "experiments" / "holdout.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_train_module_does_not_import_holdout() -> None:
    imported = _imported_modules(TRAIN_PATH)
    assert not any("holdout" in name for name in imported)


def test_holdout_module_does_not_import_train() -> None:
    imported = _imported_modules(HOLDOUT_PATH)
    assert not any(name == "lab.experiments.train" or name.endswith(".train") for name in imported)


def test_training_result_never_includes_holdout_metrics() -> None:
    config = load_experiment_config()
    universe = load_universe(config.universe_path)
    splits = build_walk_forward(
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
    experiment = register_experiment(
        config,
        splits,
        registered_at=datetime(2026, 9, 6, tzinfo=UTC),
        git_sha="0123456789abcdef",
        experiment_id="isolation-1",
    )
    assert experiment.holdout_is_sealed
    bars = generate_daily_bars(
        [item.symbol for item in universe.instruments],
        date(2022, 6, 1),
        date(2023, 4, 1),
        seed=config.fixture_seed,
    )
    result = run_training(
        experiment,
        config,
        universe,
        bars,
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert DatasetSplit.HOLDOUT not in result.splits
    assert result.splits <= {DatasetSplit.TRAIN, DatasetSplit.VALIDATION}
    assert experiment.holdout_is_sealed
    assert all(prediction.split is not DatasetSplit.HOLDOUT for prediction in result.predictions)
