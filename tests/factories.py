"""Valid-instance factories for every contract.

Each factory returns a minimal record that satisfies every invariant. Tests
build on these and mutate one field at a time, so a failure points at the
invariant under test rather than at unrelated setup.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from lab.contracts import (
    Bar,
    Experiment,
    FeatureSnapshot,
    Fill,
    Instrument,
    Order,
    Prediction,
    Proposal,
    RiskDecision,
    derive_client_order_id,
)
from lab.contracts.enums import (
    AssetClass,
    BarInterval,
    DatasetSplit,
    FillSource,
    OrderStatus,
    OrderType,
    PriceAdjustment,
    RiskOutcome,
    Side,
)

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)


def make_instrument(**overrides: Any) -> Instrument:
    """A listed ETF."""
    return Instrument(
        **{
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "asset_class": AssetClass.US_ETF,
            "exchange": "NYSE ARCA",
            "listed_on": date(1993, 1, 22),
            "source": "test-fixture",
            "retrieved_at": NOW,
            **overrides,
        }
    )


def make_bar(**overrides: Any) -> Bar:
    """One daily bar."""
    return Bar(
        **{
            "symbol": "SPY",
            "interval": BarInterval.DAY_1,
            "ts_start": NOW,
            "ts_end": NOW + timedelta(days=1),
            "open": Decimal("500.00"),
            "high": Decimal("505.00"),
            "low": Decimal("498.00"),
            "close": Decimal("503.00"),
            "volume": Decimal("1000000"),
            "adjustment": PriceAdjustment.SPLIT_AND_DIVIDEND,
            "source": "test-fixture",
            "ingested_at": NOW + timedelta(days=1),
            **overrides,
        }
    )


def make_feature_snapshot(**overrides: Any) -> FeatureSnapshot:
    """A snapshot whose inputs predate its decision time."""
    return FeatureSnapshot(
        **{
            "snapshot_id": "snap-1",
            "feature_set": "momentum_v1",
            "feature_set_version": "1.0.0",
            "symbol": "SPY",
            "as_of": NOW,
            "information_cutoff": NOW - timedelta(minutes=5),
            "values": {"mom_21d": 0.031, "vol_21d": 0.12, "missing_feature": None},
            "computed_at": NOW,
            **overrides,
        }
    )


def make_experiment(**overrides: Any) -> Experiment:
    """A registered, still-sealed experiment with ordered walk-forward splits."""
    return Experiment(
        **{
            "experiment_id": "exp-001",
            "name": "momentum baseline",
            "hypothesis": "12-1 momentum beats equal weight net of costs.",
            "registered_at": NOW,
            "universe_id": "liquid50_v1",
            "feature_set": "momentum_v1",
            "feature_set_version": "1.0.0",
            "train_start": datetime(2018, 1, 1, tzinfo=UTC),
            "train_end": datetime(2022, 1, 1, tzinfo=UTC),
            "validation_start": datetime(2022, 1, 1, tzinfo=UTC),
            "validation_end": datetime(2024, 1, 1, tzinfo=UTC),
            "holdout_start": datetime(2024, 1, 1, tzinfo=UTC),
            "holdout_end": datetime(2025, 1, 1, tzinfo=UTC),
            "purge": timedelta(days=21),
            "embargo": timedelta(days=5),
            "cost_model_id": "conservative_v1",
            "code_git_sha": "0123456789abcdef",
            "config_hash": "cafebabe1234",
            "trial_count": 1,
            **overrides,
        }
    )


def make_prediction(**overrides: Any) -> Prediction:
    """One prediction, stored before its outcome exists."""
    return Prediction(
        **{
            "prediction_id": "pred-1",
            "experiment_id": "exp-001",
            "model_version": "ridge-1.0.0",
            "symbol": "SPY",
            "as_of": NOW,
            "horizon": timedelta(days=21),
            "feature_snapshot_id": "snap-1",
            "value": 0.014,
            "split": DatasetSplit.VALIDATION,
            "created_at": NOW,
            **overrides,
        }
    )


def make_proposal(**overrides: Any) -> Proposal:
    """A 60% invested, 40% cash target portfolio."""
    return Proposal(
        **{
            "proposal_id": "prop-1",
            "experiment_id": "exp-001",
            "strategy_version": "1.0.0",
            "as_of": NOW,
            "lines": [
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.40"),
                    "reference_price": Decimal("503.00"),
                },
                {
                    "symbol": "QQQ",
                    "target_weight": Decimal("0.20"),
                    "reference_price": Decimal("430.00"),
                },
            ],
            "created_at": NOW,
            **overrides,
        }
    )


def make_risk_decision(**overrides: Any) -> RiskDecision:
    """An approved decision with no breached limits."""
    return RiskDecision(
        **{
            "decision_id": "dec-1",
            "proposal_id": "prop-1",
            "decided_at": NOW,
            "outcome": RiskOutcome.APPROVED,
            "risk_config_hash": "deadbeef99",
            "checks": [
                {
                    "limit_id": "gross_exposure",
                    "limit_value": Decimal("1.0"),
                    "observed_value": Decimal("0.6"),
                    "breached": False,
                }
            ],
            "approved_lines": [
                {"symbol": "SPY", "side": Side.BUY, "quantity": Decimal("10")},
            ],
            "kill_switch_engaged": False,
            "data_staleness_seconds": Decimal("12"),
            "reason": "within all limits",
            **overrides,
        }
    )


def make_order(**overrides: Any) -> Order:
    """A paper market order carrying its derived idempotency key."""
    return Order(
        **{
            "order_id": "ord-1",
            "client_order_id": derive_client_order_id("dec-1", "SPY", Side.BUY),
            "decision_id": "dec-1",
            "symbol": "SPY",
            "side": Side.BUY,
            "quantity": Decimal("10"),
            "order_type": OrderType.MARKET,
            "status": OrderStatus.ACCEPTED,
            "submitted_at": NOW,
            **overrides,
        }
    )


def make_fill(**overrides: Any) -> Fill:
    """A broker paper fill."""
    return Fill(
        **{
            "fill_id": "fill-1",
            "order_id": "ord-1",
            "client_order_id": derive_client_order_id("dec-1", "SPY", Side.BUY),
            "source": FillSource.BROKER_PAPER,
            "symbol": "SPY",
            "side": Side.BUY,
            "quantity": Decimal("10"),
            "price": Decimal("503.05"),
            "fee": Decimal("0"),
            "filled_at": NOW,
            "recorded_at": NOW,
            "sequence": 0,
            **overrides,
        }
    )


FACTORIES = {
    "instrument": make_instrument,
    "bar": make_bar,
    "feature_snapshot": make_feature_snapshot,
    "experiment": make_experiment,
    "prediction": make_prediction,
    "proposal": make_proposal,
    "risk_decision": make_risk_decision,
    "order": make_order,
    "fill": make_fill,
}
