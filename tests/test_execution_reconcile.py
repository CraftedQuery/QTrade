"""Restart reconciliation of local ledger vs paper broker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lab.config import RiskLimits
from lab.execution.book import BookState
from lab.execution.broker import FakePaperBroker
from lab.execution.ledger import ExecutionLedger
from lab.execution.reconcile import reconcile
from lab.execution.session import PaperSession, UnreconciledError
from tests.factories import make_proposal

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PRICES = {"SPY": Decimal("503.00")}
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


def test_matching_books_are_clean() -> None:
    report = reconcile({"SPY": Decimal("9")}, {"SPY": Decimal("9")})
    assert report.is_clean
    assert report.local_only == ()
    assert report.broker_only == ()
    assert report.quantity_mismatches == ()


def test_mismatch_is_not_clean() -> None:
    report = reconcile({"SPY": Decimal("9")}, {"SPY": Decimal("8"), "AAPL": Decimal("1")})
    assert not report.is_clean
    assert "AAPL" in report.broker_only
    assert report.quantity_mismatches


def test_restart_reconciles_cleanly_after_a_fill(tmp_path: Path) -> None:
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
    first = PaperSession(
        limits=LIMITS,
        ledger=ExecutionLedger(tmp_path),
        broker=broker,
        book=BookState.empty(LIMITS.starting_capital),
        unattended=False,
        kill_switch=False,
    )
    first.submit_proposal(
        proposal,
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=5),
        decided_at=NOW,
    )
    restarted = PaperSession(
        limits=LIMITS,
        ledger=ExecutionLedger(tmp_path),
        broker=broker,
        book=BookState.empty(LIMITS.starting_capital),
        unattended=False,
        kill_switch=False,
    )
    report = restarted.reconcile()
    assert report.is_clean
    assert restarted.book.quantity("SPY") == broker.position_qty("SPY")


def test_unreconciled_restart_refuses_new_orders(tmp_path: Path) -> None:
    broker = FakePaperBroker(marks=PRICES)
    session = PaperSession(
        limits=LIMITS,
        ledger=ExecutionLedger(tmp_path),
        broker=broker,
        book=BookState.empty(LIMITS.starting_capital),
        unattended=False,
        kill_switch=False,
    )
    session.submit_proposal(
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.05"),
                    "reference_price": Decimal("503.00"),
                }
            ]
        ),
        prices=PRICES,
        data_as_of=NOW - timedelta(seconds=5),
        decided_at=NOW,
    )
    broker.force_position("AAPL", Decimal("3"))
    restarted = PaperSession(
        limits=LIMITS,
        ledger=ExecutionLedger(tmp_path),
        broker=broker,
        book=BookState.empty(LIMITS.starting_capital),
        unattended=False,
        kill_switch=False,
    )
    assert not restarted.reconcile().is_clean
    with pytest.raises(UnreconciledError):
        restarted.submit_proposal(
            make_proposal(proposal_id="prop-2"),
            prices=PRICES,
            data_as_of=NOW - timedelta(seconds=5),
            decided_at=NOW,
        )
