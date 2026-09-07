"""Attended paper session; unattended refused while limits are provisional."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lab.config import RiskLimits
from lab.execution.book import BookState
from lab.execution.broker import FakePaperBroker
from lab.execution.ledger import ExecutionLedger
from lab.execution.session import PaperSession, ProvisionalLimitsError, main, run_paper_session
from tests.factories import make_proposal

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
PRICES = {"SPY": Decimal("503.00")}
PROVISIONAL = RiskLimits(
    starting_capital=Decimal("100000"),
    max_position_weight=Decimal("0.05"),
    max_gross_exposure=Decimal("0.60"),
    max_positions=20,
    max_daily_loss=Decimal("0.02"),
    max_drawdown=Decimal("0.10"),
    max_data_staleness_seconds=Decimal("300"),
    owner_approved=False,
)
APPROVED = RiskLimits(**{**PROVISIONAL.model_dump(), "owner_approved": True})


def test_unattended_session_refuses_provisional_limits(tmp_path: Path) -> None:
    with pytest.raises(ProvisionalLimitsError, match="provisional"):
        PaperSession(
            limits=PROVISIONAL,
            ledger=ExecutionLedger(tmp_path),
            broker=FakePaperBroker(marks=PRICES),
            book=BookState.empty(PROVISIONAL.starting_capital),
            unattended=True,
            kill_switch=False,
        )


def test_attended_session_runs_on_provisional_limits(tmp_path: Path) -> None:
    session = PaperSession(
        limits=PROVISIONAL,
        ledger=ExecutionLedger(tmp_path),
        broker=FakePaperBroker(marks=PRICES),
        book=BookState.empty(PROVISIONAL.starting_capital),
        unattended=False,
        kill_switch=False,
    )
    result = session.submit_proposal(
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
    assert result.decision.outcome.value in {"approved", "reduced"}
    assert result.orders
    assert any(fill.source.value == "internal_shadow" for fill in result.fills)
    assert any(fill.source.value == "broker_paper" for fill in result.fills)


def test_unattended_is_allowed_once_owner_approves(tmp_path: Path) -> None:
    session = PaperSession(
        limits=APPROVED,
        ledger=ExecutionLedger(tmp_path),
        broker=FakePaperBroker(marks=PRICES),
        book=BookState.empty(APPROVED.starting_capital),
        unattended=True,
        kill_switch=False,
    )
    assert not session.limits.is_provisional


def test_fixture_paper_session_needs_no_secrets(tmp_path: Path) -> None:
    report = run_paper_session(
        source="fixture",
        broker_name="fake",
        sleeve="momentum",
        output_dir=tmp_path / "out",
        ledger_dir=tmp_path / "ledger",
        unattended=False,
    )
    assert report["bar_source"] == "fixture"
    assert report["sleeve"] == "momentum"
    assert report["unattended"] is False
    assert report["limits_provisional"] is True
    assert (tmp_path / "out" / "proposal.json").is_file()
    assert (tmp_path / "out" / "decision.json").is_file()


def test_cli_refuses_unattended_while_provisional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--source",
            "fixture",
            "--broker",
            "fake",
            "--unattended",
            "--output",
            str(tmp_path / "out"),
            "--ledger",
            str(tmp_path / "ledger"),
        ]
    )
    assert code == 3
    captured = capsys.readouterr()
    assert "provisional" in captured.err


def test_cli_attended_fixture_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--source",
            "fixture",
            "--broker",
            "fake",
            "--output",
            str(tmp_path / "out"),
            "--ledger",
            str(tmp_path / "ledger"),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "proposal_id" in captured.out
    assert (tmp_path / "out" / "orders.json").is_file()
