"""The invariants this project exists to protect.

Each test here corresponds to a rule in AGENTS.md or an acceptance test in
docs/01_solo_agent_build.md. If one of these starts passing for the wrong
reason, the lab's results stop being trustworthy.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from lab.contracts import (
    Order,
    Prediction,
    Proposal,
    RiskDecision,
    derive_client_order_id,
    execution,
)
from lab.contracts.enums import AccountMode, FillSource, OrderType, RiskOutcome, Side
from tests.factories import (
    NOW,
    make_bar,
    make_experiment,
    make_feature_snapshot,
    make_fill,
    make_instrument,
    make_order,
    make_prediction,
    make_proposal,
    make_risk_decision,
)

# --- Look-ahead ------------------------------------------------------------


def test_feature_snapshot_rejects_future_information() -> None:
    """Acceptance test #2: features computed at t cannot read data after t."""
    with pytest.raises(ValidationError, match="look-ahead"):
        make_feature_snapshot(information_cutoff=NOW + timedelta(seconds=1))


def test_feature_snapshot_allows_cutoff_equal_to_as_of() -> None:
    """Data timestamped exactly at the decision instant is legitimate."""
    assert make_feature_snapshot(information_cutoff=NOW).information_cutoff == NOW


def test_bar_information_time_is_its_end_not_its_start() -> None:
    """A bar is unknowable until it closes; using ts_start would leak the future."""
    bar = make_bar()
    assert bar.information_time == bar.ts_end
    assert bar.information_time > bar.ts_start


def test_bar_rejects_impossible_ohlc() -> None:
    with pytest.raises(ValidationError, match="high"):
        make_bar(high=Decimal("100.00"))
    with pytest.raises(ValidationError, match="ts_end"):
        make_bar(ts_end=make_bar().ts_start)


# --- Survivorship ----------------------------------------------------------


def test_instrument_membership_is_point_in_time() -> None:
    delisted = make_instrument(
        symbol="LEH", listed_on=date(1994, 1, 1), delisted_on=date(2008, 9, 16)
    )
    assert delisted.was_listed_on(date(2007, 6, 1))
    assert not delisted.was_listed_on(date(2009, 6, 1))
    assert not delisted.was_listed_on(date(1990, 1, 1))


def test_instrument_without_listing_date_refuses_point_in_time_claims() -> None:
    """An unknown listing date cannot support a membership claim, so it says no."""
    assert not make_instrument(listed_on=None).was_listed_on(date(2020, 1, 1))


def test_instrument_rejects_delisting_before_listing() -> None:
    with pytest.raises(ValidationError, match="delisted_on"):
        make_instrument(listed_on=date(2020, 1, 1), delisted_on=date(2019, 1, 1))


# --- Experiment discipline -------------------------------------------------


def test_experiment_splits_must_be_walk_forward() -> None:
    with pytest.raises(ValidationError, match="validation must not overlap train"):
        make_experiment(validation_start=datetime(2021, 1, 1, tzinfo=UTC))
    with pytest.raises(ValidationError, match="holdout must not overlap validation"):
        make_experiment(holdout_start=datetime(2023, 1, 1, tzinfo=UTC))


def test_experiment_requires_a_trial_count() -> None:
    """Every performance number travels with its search budget."""
    with pytest.raises(ValidationError):
        make_experiment(trial_count=0)


def test_experiment_holdout_starts_sealed() -> None:
    assert make_experiment().holdout_is_sealed
    unsealed = make_experiment(holdout_unsealed_at=NOW + timedelta(days=1))
    assert not unsealed.holdout_is_sealed


def test_holdout_cannot_be_unsealed_before_registration() -> None:
    with pytest.raises(ValidationError, match="unsealed before"):
        make_experiment(holdout_unsealed_at=NOW - timedelta(days=1))


def test_prediction_has_no_outcome_field() -> None:
    """Predictions are stored before outcomes and can never be revised in place."""
    forbidden = {"realized", "realized_return", "outcome", "actual", "was_correct", "label"}
    assert forbidden.isdisjoint(Prediction.model_fields)


def test_prediction_resolves_only_after_its_horizon() -> None:
    prediction = make_prediction()
    assert prediction.target_time == prediction.as_of + prediction.horizon


# --- Long or cash only -----------------------------------------------------


def test_proposal_rejects_negative_weight() -> None:
    """A short position is not representable."""
    with pytest.raises(ValidationError):
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("-0.10"),
                    "reference_price": Decimal("503.00"),
                }
            ]
        )


def test_proposal_rejects_leverage() -> None:
    with pytest.raises(ValidationError, match="leverage is not permitted"):
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.70"),
                    "reference_price": Decimal("503.00"),
                },
                {
                    "symbol": "QQQ",
                    "target_weight": Decimal("0.60"),
                    "reference_price": Decimal("430.00"),
                },
            ]
        )


def test_proposal_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValidationError, match="at most once"):
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.10"),
                    "reference_price": Decimal("503.00"),
                },
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.10"),
                    "reference_price": Decimal("503.00"),
                },
            ]
        )


def test_proposal_cash_weight_is_derived() -> None:
    """Cash is the residual, so it can never disagree with the position weights."""
    proposal = make_proposal()
    assert proposal.invested_weight == Decimal("0.60")
    assert proposal.cash_weight == Decimal("0.40")
    assert Proposal.model_fields.keys().isdisjoint({"cash_weight", "invested_weight"})


def test_an_all_cash_proposal_is_valid() -> None:
    assert make_proposal(lines=[]).cash_weight == Decimal(1)


# --- Deterministic risk authority ------------------------------------------


def test_kill_switch_forces_rejection() -> None:
    with pytest.raises(ValidationError, match="kill switch"):
        make_risk_decision(kill_switch_engaged=True, outcome=RiskOutcome.APPROVED)


def test_breached_limit_cannot_be_approved() -> None:
    with pytest.raises(ValidationError, match="breached limit"):
        make_risk_decision(
            checks=[
                {
                    "limit_id": "daily_loss",
                    "limit_value": Decimal("0.02"),
                    "observed_value": Decimal("0.05"),
                    "breached": True,
                }
            ]
        )


def test_rejected_decision_approves_nothing() -> None:
    with pytest.raises(ValidationError, match="must not approve"):
        make_risk_decision(outcome=RiskOutcome.REJECTED)


def test_risk_decision_exposes_breached_limits() -> None:
    decision = make_risk_decision(
        outcome=RiskOutcome.REJECTED,
        approved_lines=[],
        checks=[
            {
                "limit_id": "stale_data",
                "limit_value": Decimal("60"),
                "observed_value": Decimal("900"),
                "breached": True,
            }
        ],
    )
    assert decision.breached_limits == ["stale_data"]


def test_risk_decision_has_no_model_authored_field() -> None:
    """No LLM output may reach the risk engine, so there is nowhere to put it."""
    forbidden = {"llm_rationale", "model_override", "llm_adjustment", "agent_note"}
    assert forbidden.isdisjoint(RiskDecision.model_fields)


def test_risk_decision_pins_its_configuration() -> None:
    """A decision must be recomputable, so the limit config is hashed into it."""
    assert make_risk_decision().risk_config_hash


# --- Paper only, and idempotent ---------------------------------------------


def test_live_account_mode_does_not_exist() -> None:
    assert [mode.value for mode in AccountMode] == ["paper"]
    assert make_order().account_mode is AccountMode.PAPER
    with pytest.raises(ValidationError):
        make_order(account_mode="live")


def test_contract_source_never_names_a_live_endpoint() -> None:
    """The live trading host must not appear anywhere in the contract package."""
    package = Path(execution.__file__).parent
    for path in sorted(package.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        assert "https://api.alpaca.markets" not in source, f"live endpoint named in {path.name}"


def test_client_order_id_is_deterministic() -> None:
    """Acceptance test #1: replaying a proposal cannot create a second order."""
    first = derive_client_order_id("dec-1", "SPY", Side.BUY)
    second = derive_client_order_id("dec-1", "SPY", Side.BUY)
    assert first == second


def test_client_order_id_separates_distinct_legs() -> None:
    base = derive_client_order_id("dec-1", "SPY", Side.BUY)
    assert base != derive_client_order_id("dec-2", "SPY", Side.BUY)
    assert base != derive_client_order_id("dec-1", "QQQ", Side.BUY)
    assert base != derive_client_order_id("dec-1", "SPY", Side.SELL)


def test_replayed_decision_yields_an_identical_order_key() -> None:
    decision = make_risk_decision()
    line = decision.approved_lines[0]
    keys = {derive_client_order_id(decision.decision_id, line.symbol, line.side) for _ in range(5)}
    assert len(keys) == 1


def test_order_type_and_limit_price_must_agree() -> None:
    with pytest.raises(ValidationError, match="requires a limit_price"):
        make_order(order_type=OrderType.LIMIT)
    with pytest.raises(ValidationError, match="must not carry a limit_price"):
        make_order(order_type=OrderType.MARKET, limit_price=Decimal("500"))


def test_order_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_order(quantity=Decimal("0"))


def test_order_has_no_live_field() -> None:
    assert "is_live" not in Order.model_fields


# --- Shadow fills never overwrite broker fills ------------------------------


def test_broker_and_shadow_fills_coexist_as_separate_records() -> None:
    broker = make_fill()
    shadow = make_fill(
        fill_id="fill-2",
        source=FillSource.INTERNAL_SHADOW,
        price=Decimal("503.35"),
        sequence=1,
    )
    assert broker.source is not shadow.source
    assert broker.fill_id != shadow.fill_id
    assert broker.order_id == shadow.order_id
    assert broker != shadow


def test_fill_notional_excludes_fees() -> None:
    assert make_fill(quantity=Decimal("10"), price=Decimal("100")).notional == Decimal("1000")


def test_fill_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_fill(quantity=Decimal("0"))
