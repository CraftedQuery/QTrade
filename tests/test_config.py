"""Risk limit resolution: defaults, file, environment, and the invariants."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from lab.config import (
    DEFAULT_RISK_CONFIG_PATH,
    ENV_PREFIX,
    PROVISIONAL_DEFAULTS,
    RiskLimits,
    load_risk_limits,
)

VALID = {
    "starting_capital": Decimal("100000"),
    "max_position_weight": Decimal("0.05"),
    "max_gross_exposure": Decimal("0.60"),
    "max_positions": 20,
    "max_daily_loss": Decimal("0.02"),
    "max_drawdown": Decimal("0.10"),
    "max_data_staleness_seconds": Decimal("300"),
}


def limits(**overrides: object) -> RiskLimits:
    return RiskLimits(**{**VALID, **overrides})


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# --- Layering ---------------------------------------------------------------


def test_defaults_apply_when_nothing_overrides(tmp_path: Path) -> None:
    resolved = load_risk_limits(path=tmp_path / "absent.yaml", env={})
    assert resolved.max_position_weight == PROVISIONAL_DEFAULTS["max_position_weight"]
    assert resolved.max_gross_exposure == PROVISIONAL_DEFAULTS["max_gross_exposure"]


def test_missing_config_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_risk_limits(path=tmp_path / "nope.yaml", env={}).starting_capital > 0


def test_file_overrides_defaults(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "risk.yaml",
        "risk:\n  max_position_weight: 0.03\n  starting_capital: 250000\n",
    )
    resolved = load_risk_limits(path=config, env={})
    assert resolved.max_position_weight == Decimal("0.03")
    assert resolved.starting_capital == Decimal("250000")
    # Untouched settings keep their defaults.
    assert resolved.max_drawdown == PROVISIONAL_DEFAULTS["max_drawdown"]


def test_environment_overrides_file(tmp_path: Path) -> None:
    config = write_config(tmp_path / "risk.yaml", "risk:\n  max_position_weight: 0.03\n")
    resolved = load_risk_limits(path=config, env={f"{ENV_PREFIX}MAX_POSITION_WEIGHT": "0.04"})
    assert resolved.max_position_weight == Decimal("0.04")


def test_blank_environment_value_is_ignored(tmp_path: Path) -> None:
    """.env.example ships these keys empty; empty must not mean zero."""
    config = write_config(tmp_path / "risk.yaml", "risk:\n  max_position_weight: 0.03\n")
    resolved = load_risk_limits(path=config, env={f"{ENV_PREFIX}MAX_POSITION_WEIGHT": "  "})
    assert resolved.max_position_weight == Decimal("0.03")


def test_empty_config_file_falls_back_to_defaults(tmp_path: Path) -> None:
    config = write_config(tmp_path / "risk.yaml", "# nothing here\n")
    assert (
        load_risk_limits(path=config, env={}).max_positions
        == (PROVISIONAL_DEFAULTS["max_positions"])
    )


def test_unknown_setting_is_rejected(tmp_path: Path) -> None:
    """A typo must fail loudly rather than silently leaving a limit at default."""
    config = write_config(tmp_path / "risk.yaml", "risk:\n  max_postion_weight: 0.03\n")
    with pytest.raises(ValueError, match="unknown risk settings"):
        load_risk_limits(path=config, env={})


def test_unparseable_environment_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected a number"):
        load_risk_limits(env={f"{ENV_PREFIX}MAX_DRAWDOWN": "ten percent"})


def test_boolean_environment_values(tmp_path: Path) -> None:
    absent = tmp_path / "absent.yaml"
    for raw in ("true", "1", "yes", "on"):
        resolved = load_risk_limits(path=absent, env={f"{ENV_PREFIX}OWNER_APPROVED": raw})
        assert resolved.owner_approved
    for raw in ("false", "0", "no", "off"):
        resolved = load_risk_limits(path=absent, env={f"{ENV_PREFIX}OWNER_APPROVED": raw})
        assert not resolved.owner_approved
    with pytest.raises(ValueError, match="expected a boolean"):
        load_risk_limits(path=absent, env={f"{ENV_PREFIX}OWNER_APPROVED": "maybe"})


# --- Invariants -------------------------------------------------------------


def test_position_cap_cannot_exceed_gross_cap() -> None:
    with pytest.raises(ValueError, match="exceeds max_gross_exposure"):
        limits(max_position_weight=Decimal("0.70"), max_gross_exposure=Decimal("0.60"))


def test_daily_loss_cannot_exceed_drawdown_stop() -> None:
    with pytest.raises(ValueError, match="exceeds max_drawdown"):
        limits(max_daily_loss=Decimal("0.20"), max_drawdown=Decimal("0.10"))


def test_limits_must_be_mutually_reachable() -> None:
    """5 names at 5% cannot fill a 60% book; that configuration is incoherent."""
    with pytest.raises(ValueError, match="cannot reach max_gross_exposure"):
        limits(max_positions=5)


def test_negative_and_zero_limits_are_rejected() -> None:
    for field, bad in (
        ("starting_capital", Decimal("0")),
        ("max_position_weight", Decimal("0")),
        ("max_drawdown", Decimal("-0.1")),
        ("max_data_staleness_seconds", Decimal("0")),
        ("max_positions", 0),
    ):
        with pytest.raises(ValueError):
            limits(**{field: bad})


def test_loss_fractions_cannot_exceed_one() -> None:
    with pytest.raises(ValueError):
        limits(max_daily_loss=Decimal("1.5"), max_drawdown=Decimal("2"))


def test_limits_are_frozen() -> None:
    """A limit must not move mid-session; the audit trail depends on it."""
    resolved = limits()
    with pytest.raises(ValueError):
        resolved.max_position_weight = Decimal("0.99")


# --- Provenance and hashing -------------------------------------------------


def test_limits_are_provisional_until_the_owner_approves() -> None:
    assert limits().is_provisional
    assert not limits(owner_approved=True).is_provisional


def test_shipped_config_is_marked_provisional() -> None:
    """configs/risk.yaml holds placeholders until the mandate is completed."""
    assert load_risk_limits(path=DEFAULT_RISK_CONFIG_PATH, env={}).is_provisional


def test_config_hash_is_deterministic() -> None:
    assert limits().config_hash == limits().config_hash


def test_config_hash_changes_when_a_limit_changes() -> None:
    assert limits().config_hash != limits(max_position_weight=Decimal("0.04")).config_hash


def test_config_hash_ignores_approval_status() -> None:
    """Approving unchanged numbers must not break comparison across decisions."""
    assert limits(owner_approved=False).config_hash == limits(owner_approved=True).config_hash


def test_config_hash_fits_the_risk_decision_contract() -> None:
    """RiskDecision.risk_config_hash requires at least 8 characters."""
    from lab.contracts import RiskDecision
    from tests.factories import make_risk_decision

    decision = make_risk_decision(risk_config_hash=limits().config_hash)
    assert isinstance(decision, RiskDecision)
    assert len(decision.risk_config_hash) >= 8


# --- No model authority -----------------------------------------------------


def test_risk_limits_expose_no_mutation_path() -> None:
    """Nothing may raise a limit at runtime, least of all a model."""
    forbidden = {"set_limit", "update", "override", "apply_model_adjustment"}
    assert forbidden.isdisjoint(dir(RiskLimits))
