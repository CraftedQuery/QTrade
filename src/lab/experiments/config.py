"""Resolved configuration for the baseline experiment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from lab.config import REPO_ROOT

DEFAULT_EXPERIMENT_CONFIG_PATH: Path = REPO_ROOT / "configs" / "experiment.yaml"
DEFAULT_UNIVERSE_PATH: Path = REPO_ROOT / "configs" / "universe" / "liquid50.yaml"


@dataclass(frozen=True)
class ExperimentConfig:
    """Resolved, hashable settings for one baseline run."""

    name: str
    hypothesis: str
    universe_id: str
    universe_path: Path
    feature_set: str
    feature_set_version: str
    cost_model_id: str
    one_way_cost_bps: Decimal
    lookback_sessions: int
    rebalance_every_sessions: int
    horizon: timedelta
    purge: timedelta
    embargo: timedelta
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    fixture_seed: int
    fixture_bar_start: date
    fixture_bar_end: date
    fixture_source: str
    trial_count: int

    @property
    def config_hash(self) -> str:
        """Deterministic hash of the resolved experiment settings."""
        payload = {
            "name": self.name,
            "hypothesis": self.hypothesis,
            "universe_id": self.universe_id,
            "feature_set": self.feature_set,
            "feature_set_version": self.feature_set_version,
            "cost_model_id": self.cost_model_id,
            "one_way_cost_bps": str(self.one_way_cost_bps),
            "lookback_sessions": self.lookback_sessions,
            "rebalance_every_sessions": self.rebalance_every_sessions,
            "horizon_days": self.horizon.days,
            "purge_days": self.purge.days,
            "embargo_days": self.embargo.days,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(),
            "holdout_end": self.holdout_end.isoformat(),
            "fixture_seed": self.fixture_seed,
            "fixture_bar_start": self.fixture_bar_start.isoformat(),
            "fixture_bar_end": self.fixture_bar_end.isoformat(),
            "trial_count": self.trial_count,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def parse_iso_duration(value: str) -> timedelta:
    """Parse a day-only ISO-8601 duration such as ``P21D``."""
    raw = value.strip().upper()
    if raw.startswith("P") and raw.endswith("D") and "T" not in raw:
        days = int(raw[1:-1])
        return timedelta(days=days)
    raise ValueError(f"unsupported duration {value!r}; expected PnD")


def load_experiment_config(path: Path | None = None) -> ExperimentConfig:
    """Load ``configs/experiment.yaml`` (or ``path``) into a resolved config."""
    config_path = DEFAULT_EXPERIMENT_CONFIG_PATH if path is None else path
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{config_path}: expected a mapping at the top level")
    exp = _mapping(loaded, "experiment")
    walk = _mapping(loaded, "walk_forward")
    fixture = _mapping(loaded, "fixture")
    return ExperimentConfig(
        name=str(exp["name"]),
        hypothesis=str(exp["hypothesis"]).strip(),
        universe_id=str(exp["universe_id"]),
        universe_path=DEFAULT_UNIVERSE_PATH,
        feature_set=str(exp["feature_set"]),
        feature_set_version=str(exp["feature_set_version"]),
        cost_model_id=str(exp["cost_model_id"]),
        one_way_cost_bps=Decimal(str(exp["one_way_cost_bps"])),
        lookback_sessions=int(exp["lookback_sessions"]),
        rebalance_every_sessions=int(exp["rebalance_every_sessions"]),
        horizon=timedelta(days=int(exp["horizon_days"])),
        purge=parse_iso_duration(str(walk["purge"])),
        embargo=parse_iso_duration(str(walk["embargo"])),
        train_start=_as_utc_midnight(exp["train_start"]),
        train_end=_as_utc_midnight(exp["train_end"]),
        validation_start=_as_utc_midnight(exp["validation_start"]),
        validation_end=_as_utc_midnight(exp["validation_end"]),
        holdout_start=_as_utc_midnight(exp["holdout_start"]),
        holdout_end=_as_utc_midnight(exp["holdout_end"]),
        fixture_seed=int(fixture["seed"]),
        fixture_bar_start=_as_date(fixture["bar_start"]),
        fixture_bar_end=_as_date(fixture["bar_end"]),
        fixture_source=str(fixture.get("source") or "committed-fixture"),
        trial_count=int(exp["trial_count"]),
    )


def _mapping(loaded: dict[str, Any], key: str) -> dict[str, Any]:
    block = loaded.get(key)
    if not isinstance(block, dict):
        raise ValueError(f"expected a mapping under '{key}'")
    return block


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"cannot parse date from {value!r}")


def _as_utc_midnight(value: object) -> datetime:
    day = _as_date(value)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


__all__ = [
    "DEFAULT_EXPERIMENT_CONFIG_PATH",
    "DEFAULT_UNIVERSE_PATH",
    "ExperimentConfig",
    "load_experiment_config",
    "parse_iso_duration",
]
