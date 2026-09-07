"""Acceptance test #1: replaying a proposal cannot create a second broker order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lab.config import RiskLimits
from lab.execution.book import BookState
from lab.execution.broker import FakePaperBroker
from lab.execution.ledger import ExecutionLedger
from lab.execution.session import PaperSession
from tests.factories import make_proposal

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PRICES = {"SPY": Decimal("503.00"), "QQQ": Decimal("430.00")}
LIMITS = RiskLimits(
    starting_capital=Decimal("100000"),
    max_position_weight=Decimal("0.05"),
    max_gross_exposure=Decimal("0.60"),
    max_positions=20,
    max_daily_loss=Decimal("0.02"),
    max_drawdown=Decimal("0.10"),
    max_data_staleness_seconds=Decimal("300"),
    owner_approved=False,
)


def _session(root: Path, broker: FakePaperBroker) -> PaperSession:
    return PaperSession(
        limits=LIMITS,
        ledger=ExecutionLedger(root),
        broker=broker,
        book=BookState.empty(LIMITS.starting_capital),
        unattended=False,
        kill_switch=False,
    )


def test_replaying_a_proposal_does_not_create_a_second_broker_order(tmp_path: Path) -> None:
    broker = FakePaperBroker(marks=PRICES)
    session = _session(tmp_path, broker)
    proposal = make_proposal(
        lines=[
            {
                "symbol": "SPY",
                "target_weight": Decimal("0.05"),
                "reference_price": Decimal("503.00"),
            }
        ]
    )
    first = session.submit_proposal(
        proposal,
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=5),
        decided_at=NOW,
    )
    second = session.submit_proposal(
        proposal,
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=4),
        decided_at=NOW + timedelta(seconds=10),
    )
    assert first.orders
    assert second.replayed
    assert [order.client_order_id for order in second.orders] == [
        order.client_order_id for order in first.orders
    ]
    assert broker.submit_calls == len(first.orders)
    assert len({order.client_order_id for order in broker.orders()}) == len(first.orders)


def test_new_session_on_the_same_ledger_is_also_idempotent(tmp_path: Path) -> None:
    broker = FakePaperBroker(marks=PRICES)
    proposal = make_proposal(
        lines=[
            {
                "symbol": "SPY",
                "target_weight": Decimal("0.05"),
                "reference_price": Decimal("503.00"),
            }
        ]
    )
    first = _session(tmp_path, broker).submit_proposal(
        proposal,
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=5),
        decided_at=NOW,
    )
    restarted = _session(tmp_path, broker).submit_proposal(
        proposal,
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=5),
        decided_at=NOW,
    )
    assert restarted.replayed
    assert broker.submit_calls == len(first.orders)
