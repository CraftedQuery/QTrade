"""Register an experiment before any result is viewed."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lab.config import REPO_ROOT
from lab.contracts import Experiment
from lab.contracts.enums import ExperimentStatus
from lab.experiments.config import ExperimentConfig
from lab.experiments.splits import WalkForwardSplits


def current_git_sha(*, repo_root: Path | None = None) -> str:
    """Return ``HEAD`` or a placeholder when git is unavailable."""
    root = REPO_ROOT if repo_root is None else repo_root
    git = shutil.which("git")
    if git is None:
        return "unknown-working-tree"
    try:
        result = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown-working-tree"
    sha = result.stdout.strip()
    if result.returncode != 0 or len(sha) < 7:
        return "unknown-working-tree"
    return sha


def register_experiment(
    config: ExperimentConfig,
    splits: WalkForwardSplits,
    *,
    registered_at: datetime | None = None,
    git_sha: str | None = None,
    experiment_id: str | None = None,
) -> Experiment:
    """Construct a sealed experiment. Call this before computing metrics.

    The holdout stays sealed. This function does not accept, compute, or
    return performance numbers.
    """
    stamp = registered_at if registered_at is not None else datetime.now(tz=UTC)
    sha = git_sha if git_sha is not None else current_git_sha()
    exp_id = experiment_id or f"{config.name}-{stamp.strftime('%Y%m%dT%H%M%SZ')}"
    return Experiment(
        experiment_id=exp_id,
        name=config.name,
        hypothesis=config.hypothesis,
        registered_at=stamp,
        status=ExperimentStatus.REGISTERED,
        universe_id=config.universe_id,
        feature_set=config.feature_set,
        feature_set_version=config.feature_set_version,
        train_start=splits.train.start,
        train_end=splits.train.end,
        validation_start=splits.validation.start,
        validation_end=splits.validation.end,
        holdout_start=splits.holdout.start,
        holdout_end=splits.holdout.end,
        purge=splits.purge,
        embargo=splits.embargo,
        cost_model_id=config.cost_model_id,
        code_git_sha=sha,
        config_hash=config.config_hash,
        trial_count=config.trial_count,
    )


__all__ = ["current_git_sha", "register_experiment"]
