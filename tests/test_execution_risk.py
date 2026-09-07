"""Deterministic risk engine: limits, kill switch, stale data, reduction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lab.config import RiskLimits
from lab.contracts.enums import RiskOutcome, Side
from lab.execution.book import BookState
from lab.execution.kill_switch import kill_switch_engaged
from lab.execution.risk import evaluate_proposal
from tests.factories import make_proposal

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
FRESH = NOW - timedelta(seconds=12)

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


def _prices() -> dict[str, Decimal]:
    return {"SPY": Decimal("503.00"), "QQQ": Decimal("430.00")}


def _book() -> BookState:
    return BookState.empty(LIMITS.starting_capital)


def test_shipped_limits_match_provisional_placeholders() -> None:
    from lab.config import DEFAULT_RISK_CONFIG_PATH, load_risk_limits

    loaded = load_risk_limits(path=DEFAULT_RISK_CONFIG_PATH, env={})
    assert loaded.starting_capital == Decimal("100000")
    assert loaded.max_position_weight == Decimal("0.05")
    assert loaded.max_gross_exposure == Decimal("0.60")
    assert loaded.max_positions == 20
    assert loaded.max_daily_loss == Decimal("0.02")
    assert loaded.max_drawdown == Decimal("0.10")
    assert loaded.max_data_staleness_seconds == Decimal("300")
    assert loaded.owner_approved is False
    assert loaded.is_provisional


def test_approved_when_within_all_limits() -> None:
    proposal = make_proposal(
        lines=[
            {
                "symbol": "SPY",
                "target_weight": Decimal("0.05"),
                "reference_price": Decimal("503.00"),
            }
        ]
    )
    decision = evaluate_proposal(
        proposal,
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert decision.outcome is RiskOutcome.APPROVED
    assert decision.approved_lines
    assert decision.approved_lines[0].symbol == "SPY"
    assert decision.approved_lines[0].side is Side.BUY
    assert decision.risk_config_hash == LIMITS.config_hash
    assert not decision.breached_limits


def test_kill_switch_rejects_and_approves_nothing() -> None:
    decision = evaluate_proposal(
        make_proposal(),
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=True,
    )
    assert decision.outcome is RiskOutcome.REJECTED
    assert decision.kill_switch_engaged
    assert decision.approved_lines == []
    assert "kill_switch" in decision.breached_limits


def test_stale_data_rejects() -> None:
    stale = NOW - timedelta(seconds=900)
    decision = evaluate_proposal(
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.05"),
                    "reference_price": Decimal("503.00"),
                }
            ]
        ),
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW,
        data_as_of=stale,
        kill_switch=False,
    )
    assert decision.outcome is RiskOutcome.REJECTED
    assert "stale_data" in decision.breached_limits
    assert decision.approved_lines == []


def test_daily_loss_halt_rejects() -> None:
    book = BookState.empty(LIMITS.starting_capital)
    book.cash = Decimal("97000")  # already 3% down vs 2% halt
    decision = evaluate_proposal(
        make_proposal(
            lines=[
                {
                    "symbol": "SPY",
                    "target_weight": Decimal("0.05"),
                    "reference_price": Decimal("503.00"),
                }
            ]
        ),
        limits=LIMITS,
        book=book,
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert decision.outcome is RiskOutcome.REJECTED
    assert "daily_loss" in decision.breached_limits


def test_name_cap_and_gross_reduce_rather_than_approve() -> None:
    """Factory proposal is 40% SPY + 20% QQQ — both above the 5% name cap."""
    decision = evaluate_proposal(
        make_proposal(),
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert decision.outcome is RiskOutcome.REDUCED
    assert "name_cap" in {check.limit_id for check in decision.checks if check.breached}
    assert decision.approved_lines
    spy = next(line for line in decision.approved_lines if line.symbol == "SPY")
    assert spy.side is Side.BUY
    # 5% of 100000 / 503 = 9.94 → 9 whole shares
    assert spy.quantity == Decimal("9")


def test_cannot_sell_into_a_short() -> None:
    book = BookState.empty(LIMITS.starting_capital)
    decision = evaluate_proposal(
        make_proposal(lines=[]),
        limits=LIMITS,
        book=book,
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert decision.outcome is RiskOutcome.APPROVED
    assert decision.approved_lines == []


def test_sells_only_reduce_an_existing_long() -> None:
    book = BookState.empty(LIMITS.starting_capital)
    book.apply_broker_fill_quantity("SPY", Decimal("20"), Decimal("503.00"), side_buy=True)
    decision = evaluate_proposal(
        make_proposal(lines=[]),
        limits=LIMITS,
        book=book,
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert decision.approved_lines
    line = decision.approved_lines[0]
    assert line.symbol == "SPY"
    assert line.side is Side.SELL
    assert line.quantity == Decimal("20")


def test_replay_uses_the_same_decision_id() -> None:
    proposal = make_proposal(
        lines=[
            {
                "symbol": "SPY",
                "target_weight": Decimal("0.05"),
                "reference_price": Decimal("503.00"),
            }
        ]
    )
    first = evaluate_proposal(
        proposal,
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW,
        data_as_of=FRESH,
        kill_switch=False,
    )
    second = evaluate_proposal(
        proposal,
        limits=LIMITS,
        book=_book(),
        prices=_prices(),
        decided_at=NOW + timedelta(seconds=1),
        data_as_of=FRESH,
        kill_switch=False,
    )
    assert first.decision_id == second.decision_id


def test_kill_switch_env_and_flag_file(tmp_path: Path) -> None:
    assert not kill_switch_engaged(env={})
    assert kill_switch_engaged(env={"LAB_KILL_SWITCH": "1"})
    flag = tmp_path / "kill_switch"
    flag.write_text("engaged\n", encoding="utf-8")
    assert kill_switch_engaged(env={}, path=flag)
    empty = tmp_path / "flag"
    empty.write_text("", encoding="utf-8")
    assert kill_switch_engaged(env={}, path=empty)
