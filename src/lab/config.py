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
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import Field, ValidationError, model_validator

from lab.contracts.base import LabModel, Weight

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


def _coerce_env_value(field: str, raw: str) -> Any:
    """Convert one environment string to the type its field expects."""
    if field == "owner_approved":
        lowered = raw.strip().lower()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
        raise ValueError(f"{ENV_PREFIX}{field.upper()}: expected a boolean, got {raw!r}")
    if field == "max_positions":
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(
                f"{ENV_PREFIX}{field.upper()}: expected an integer, got {raw!r}"
            ) from exc
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{ENV_PREFIX}{field.upper()}: expected a number, got {raw!r}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read the ``risk:`` block from a YAML config file."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    risk = loaded.get("risk", loaded)
    if not isinstance(risk, dict):
        raise ValueError(f"{path}: expected a mapping under 'risk'")
    unknown = set(risk) - set(RiskLimits.model_fields)
    if unknown:
        raise ValueError(f"{path}: unknown risk settings {sorted(unknown)}")
    return {key: value for key, value in risk.items() if value is not None}


def _read_env(env: Mapping[str, str]) -> dict[str, Any]:
    """Collect ``LAB_RISK_*`` overrides from the environment."""
    overrides: dict[str, Any] = {}
    for field in RiskLimits.model_fields:
        raw = env.get(f"{ENV_PREFIX}{field.upper()}")
        if raw is not None and raw.strip() != "":
            overrides[field] = _coerce_env_value(field, raw)
    return overrides


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
    config_path = DEFAULT_RISK_CONFIG_PATH if path is None else path
    resolved: dict[str, Any] = dict(PROVISIONAL_DEFAULTS)

    if config_path.is_file():
        resolved.update(_read_yaml(config_path))
    resolved.update(_read_env(os.environ if env is None else env))

    try:
        return RiskLimits(**resolved)
    except ValidationError as exc:
        raise ValueError(f"invalid risk limits: {exc}") from exc


__all__ = [
    "DEFAULT_RISK_CONFIG_PATH",
    "ENV_PREFIX",
    "PROVISIONAL_DEFAULTS",
    "REPO_ROOT",
    "RiskLimits",
    "load_risk_limits",
]
