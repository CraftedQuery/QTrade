"""Runtime configuration for the lab, including the deterministic risk limits.

The risk numbers in :class:`RiskLimits` come from the owner mandate
(``docs/00_owner_mandate.md`` §3). Until that document is filled in, the values
here are **provisional placeholders** — deliberately conservative, and marked as
such by :attr:`RiskLimits.owner_approved`.

## What "change dynamically" means here, and what it does not

Limits are resolved once at process start, from three layers:

1. conservative built-in defaults,
2. ``configs/risk.yaml`` if present,
3. ``LAB_RISK_*`` environment variables.

Later layers win. That means the numbers can be changed without touching code —
edit a file or export a variable and restart.

Limits are **not** mutable at runtime. Nothing in the lab may rewrite a limit
while a session is live, and no model output may set one. This is not an
oversight:

* every :class:`~lab.contracts.execution.RiskDecision` stores a
  ``risk_config_hash``, and a decision has to stay recomputable from it;
* a limit that can move mid-session makes the audit trail meaningless, because
  you can no longer say which rules a given order was checked against.

Change a limit, restart, and the hash changes with it — so the record shows
exactly which numbers produced which decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, Self, get_args, get_origin

import yaml
from pydantic import Field, ValidationError, model_validator

from lab.contracts.base import LabModel, Weight
from lab.costs import CostModel

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_RISK_CONFIG_PATH: Path = REPO_ROOT / "configs" / "risk.yaml"
ENV_PREFIX = "LAB_RISK_"

Fraction = Decimal
"""A proportion in (0, 1]. Expressed as a fraction, never as a percentage."""


class RiskLimits(LabModel):
    """Deterministic risk limits.

    Every field is a hard ceiling the risk engine enforces. Nothing here is
    advisory, and nothing here may be raised by anything other than an operator
    editing configuration between sessions.
    """

    starting_capital: Decimal = Field(
        gt=0, description="Simulated starting capital, in USD. Paper only."
    )
    max_position_weight: Weight = Field(
        gt=0, description="Largest share of the book any single name may take."
    )
    max_gross_exposure: Weight = Field(
        gt=0, description="Largest total invested weight. Below 1 means always hold cash."
    )
    max_positions: int = Field(ge=1, description="Most names that may be held at once.")
    max_daily_loss: Fraction = Field(
        gt=0, le=1, description="Daily loss fraction that halts trading for the session."
    )
    max_drawdown: Fraction = Field(
        gt=0, le=1, description="Peak-to-trough drawdown fraction that stops the lab."
    )
    max_data_staleness_seconds: Decimal = Field(
        gt=0, description="Age of market data beyond which the lab refuses to trade."
    )
    owner_approved: bool = Field(
        default=False,
        description=(
            "True once these numbers come from a completed owner mandate. "
            "False means they are provisional placeholders."
        ),
    )

    @model_validator(mode="after")
    def _check_coherent(self) -> Self:
        if self.max_position_weight > self.max_gross_exposure:
            raise ValueError(
                f"max_position_weight ({self.max_position_weight}) exceeds "
                f"max_gross_exposure ({self.max_gross_exposure}); one name cannot be "
                "allowed more than the whole book"
            )
        if self.max_daily_loss > self.max_drawdown:
            raise ValueError(
                f"max_daily_loss ({self.max_daily_loss}) exceeds max_drawdown "
                f"({self.max_drawdown}); a single day could never trip the drawdown stop first"
            )
        if self.max_position_weight * self.max_positions < self.max_gross_exposure:
            raise ValueError(
                f"max_positions ({self.max_positions}) at max_position_weight "
                f"({self.max_position_weight}) cannot reach max_gross_exposure "
                f"({self.max_gross_exposure}); the limits contradict each other"
            )
        return self

    @property
    def is_provisional(self) -> bool:
        """Whether these limits are placeholders rather than the owner's numbers.

        Release 0.3 should refuse to run an unattended session while this is
        ``True``: trading a book against invented limits is worse than not
        trading it.
        """
        return not self.owner_approved

    @property
    def config_hash(self) -> str:
        """Deterministic hash of the limits, for ``RiskDecision.risk_config_hash``.

        Covers the numeric limits only. ``owner_approved`` is provenance, not a
        rule, so approving an unchanged set of numbers does not change the hash
        and decisions stay comparable across that event.
        """
        limits = self.model_dump(mode="json", exclude={"owner_approved"})
        canonical = json.dumps(limits, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


PROVISIONAL_DEFAULTS: Mapping[str, Any] = {
    # Deliberately conservative. These are placeholders, not recommendations,
    # and they stay marked provisional until the owner mandate is completed.
    "starting_capital": Decimal("100000"),
    "max_position_weight": Decimal("0.05"),
    "max_gross_exposure": Decimal("0.60"),
    "max_positions": 20,
    "max_daily_loss": Decimal("0.02"),
    "max_drawdown": Decimal("0.10"),
    "max_data_staleness_seconds": Decimal("300"),
    "owner_approved": False,
}
"""Built-in defaults, used when no configuration file or variable overrides them."""

_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _scalar_type(annotation: Any) -> Any:
    """Unwrap ``Annotated[...]`` and ``X | None`` down to the underlying scalar.

    Field types in the contracts are aliases such as ``Weight`` and
    ``Identifier``, so the raw annotation is rarely the type a value must be
    coerced to.
    """
    while (args := get_args(annotation)) and get_origin(annotation) in (Annotated, UnionType):
        annotation = args[0]
    return annotation


def _coerce(field: str, raw: str, annotation: Any, prefix: str) -> Any:
    """Convert one environment string to the type its field expects."""
    label = f"{prefix}{field.upper()}"
    annotation = _scalar_type(annotation)

    if annotation is bool:
        lowered = raw.strip().lower()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
        raise ValueError(f"{label}: expected a boolean, got {raw!r}")
    if annotation is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{label}: expected an integer, got {raw!r}") from exc
    if annotation is str or (isinstance(annotation, type) and issubclass(annotation, StrEnum)):
        return raw.strip()
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{label}: expected a number, got {raw!r}") from exc


def _read_yaml(path: Path, section: str, model: type[LabModel]) -> dict[str, Any]:
    """Read one named block from a YAML config file."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    block = loaded.get(section, loaded)
    if not isinstance(block, dict):
        raise ValueError(f"{path}: expected a mapping under {section!r}")
    unknown = set(block) - set(model.model_fields)
    if unknown:
        raise ValueError(f"{path}: unknown {section} settings {sorted(unknown)}")
    return {key: value for key, value in block.items() if value is not None}


def _read_env(env: Mapping[str, str], prefix: str, model: type[LabModel]) -> dict[str, Any]:
    """Collect ``<PREFIX>*`` overrides from the environment."""
    overrides: dict[str, Any] = {}
    for field, info in model.model_fields.items():
        raw = env.get(f"{prefix}{field.upper()}")
        if raw is not None and raw.strip() != "":
            overrides[field] = _coerce(field, raw, info.annotation, prefix)
    return overrides


def _resolve[M: LabModel](
    model: type[M],
    defaults: Mapping[str, Any],
    path: Path,
    section: str,
    prefix: str,
    env: Mapping[str, str] | None,
    label: str,
) -> M:
    """Resolve settings from built-in defaults, then file, then environment.

    Every layered setting in the lab goes through here, so the precedence rule is
    stated once: later layers win, a missing file is not an error, and an unknown
    key fails loudly rather than leaving a setting silently at its default.
    """
    resolved: dict[str, Any] = dict(defaults)
    if path.is_file():
        resolved.update(_read_yaml(path, section, model))
    resolved.update(_read_env(os.environ if env is None else env, prefix, model))
    try:
        return model(**resolved)
    except ValidationError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


def load_risk_limits(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RiskLimits:
    """Resolve the risk limits from defaults, then file, then environment.

    Args:
        path: Config file to read. Defaults to ``configs/risk.yaml``; a missing
            file is not an error, the built-in defaults simply stand.
        env: Environment mapping to read ``LAB_RISK_*`` from. Defaults to
            ``os.environ``.

    Returns:
        The resolved limits.

    Raises:
        ValueError: If a value cannot be parsed, an unknown setting appears, or
            the resulting limits contradict each other.
    """
    return _resolve(
        RiskLimits,
        PROVISIONAL_DEFAULTS,
        DEFAULT_RISK_CONFIG_PATH if path is None else path,
        "risk",
        ENV_PREFIX,
        env,
        "risk limits",
    )


COST_ENV_PREFIX = "LAB_COST_"
DEFAULT_COST_CONFIG_PATH: Path = REPO_ROOT / "configs" / "costs.yaml"

COST_DEFAULTS: Mapping[str, Any] = {
    "model_id": "conservative_v1",
    "half_spread_bps": Decimal("3"),
    "slippage_bps": Decimal("2"),
    "commission_per_share": Decimal("0.005"),
    "min_commission_per_order": Decimal("0"),
}
"""Conservative defaults. See :mod:`lab.costs` for why they are not zero."""


def load_cost_model(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CostModel:
    """Resolve the transaction cost model from defaults, file, then environment.

    Costs decide whether a strategy looks viable, so they are configuration
    rather than a constant. The layering matches the risk limits:
    ``configs/costs.yaml`` beats the defaults, and ``LAB_COST_*`` beats the file.

    Raises:
        ValueError: If a value cannot be parsed, an unknown setting appears, or
            the model charges nothing for trading.
    """
    return _resolve(
        CostModel,
        COST_DEFAULTS,
        DEFAULT_COST_CONFIG_PATH if path is None else path,
        "costs",
        COST_ENV_PREFIX,
        env,
        "cost model",
    )


EXPERIMENT_ENV_PREFIX = "LAB_EXPERIMENT_"
DEFAULT_EXPERIMENT_CONFIG_PATH: Path = REPO_ROOT / "configs" / "experiment.yaml"


class ExperimentConfig(LabModel):
    """Settings for the baseline experiment.

    Everything a result depends on lives here so it can be hashed into the
    experiment record. Two runs with the same hash, on the same commit, must
    reproduce.
    """

    universe_id: str = Field(description="Universe definition identifier.")
    max_names: int = Field(
        ge=1,
        description="Largest universe size. Starts at 50; raising it changes the result.",
    )
    benchmark_symbol: str = Field(description="Single instrument the benchmark baseline holds.")
    feature_set: str = Field(description="Feature set name.")
    label_horizon_sessions: int = Field(ge=1, description="Sessions a label looks forward.")
    rebalance: str = Field(description="monthly, weekly or daily.")
    top_n: int = Field(ge=1, description="Names the momentum strategy holds.")
    ridge_alpha: Decimal = Field(gt=0, description="L2 regularization strength.")
    min_train_size: int = Field(ge=1, description="Sessions of training required per fold.")
    test_size: int = Field(ge=1, description="Sessions per test fold.")
    purge: int = Field(ge=0, description="Extra sessions purged beyond the label horizon.")
    embargo: int = Field(ge=0, description="Sessions withheld after each test fold.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.rebalance not in {"monthly", "weekly", "daily"}:
            raise ValueError(f"rebalance must be monthly, weekly or daily; got {self.rebalance!r}")
        if self.top_n > self.max_names:
            raise ValueError(
                f"top_n ({self.top_n}) exceeds max_names ({self.max_names}); the "
                "strategy could never hold that many names"
            )
        return self

    @property
    def config_hash(self) -> str:
        """Deterministic hash of the settings, stamped onto the experiment record."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


EXPERIMENT_DEFAULTS: Mapping[str, Any] = {
    "universe_id": "liquid50_v1",
    # 50 to start, per the build plan. Raising this to 100 is a config change,
    # not a code change - but it changes the result, so it changes the hash.
    "max_names": 50,
    "benchmark_symbol": "SPY",
    "feature_set": "momentum_v1",
    "label_horizon_sessions": 21,
    "rebalance": "monthly",
    "top_n": 10,
    "ridge_alpha": Decimal("1.0"),
    "min_train_size": 252,
    "test_size": 63,
    "purge": 0,
    "embargo": 5,
}
"""Baseline experiment defaults."""


def load_experiment_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ExperimentConfig:
    """Resolve the experiment configuration from defaults, file, then environment."""
    return _resolve(
        ExperimentConfig,
        EXPERIMENT_DEFAULTS,
        DEFAULT_EXPERIMENT_CONFIG_PATH if path is None else path,
        "experiment",
        EXPERIMENT_ENV_PREFIX,
        env,
        "experiment config",
    )


__all__ = [
    "COST_DEFAULTS",
    "COST_ENV_PREFIX",
    "DEFAULT_COST_CONFIG_PATH",
    "DEFAULT_EXPERIMENT_CONFIG_PATH",
    "DEFAULT_RISK_CONFIG_PATH",
    "ENV_PREFIX",
    "EXPERIMENT_DEFAULTS",
    "EXPERIMENT_ENV_PREFIX",
    "PROVISIONAL_DEFAULTS",
    "REPO_ROOT",
    "ExperimentConfig",
    "RiskLimits",
    "load_cost_model",
    "load_experiment_config",
    "load_risk_limits",
]
