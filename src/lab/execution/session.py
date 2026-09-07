"""Attended paper session: propose → risk → submit → shadow → reconcile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from lab.config import REPO_ROOT, RiskLimits, load_risk_limits
from lab.contracts import Fill, Order, Proposal, RiskDecision, derive_client_order_id
from lab.contracts.enums import FillSource, OrderStatus, OrderType, RiskOutcome
from lab.data.alpaca import alpaca_keys_present
from lab.data.calendar import as_of_close
from lab.execution.alpaca_paper import AlpacaPaperBroker
from lab.execution.book import BookState
from lab.execution.broker import FakePaperBroker, PaperBroker
from lab.execution.kill_switch import kill_switch_engaged
from lab.execution.ledger import ExecutionLedger
from lab.execution.proposals import proposal_from_baseline
from lab.execution.reconcile import ReconcileReport, reconcile
from lab.execution.risk import evaluate_proposal
from lab.execution.shadow import conservative_shadow_fill
from lab.experiments.baseline import load_bars
from lab.experiments.baselines import session_days
from lab.experiments.config import load_experiment_config
from lab.universe.dated import load_universe

DEFAULT_LEDGER_DIR = REPO_ROOT / "data" / "execution"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "execution"


class ProvisionalLimitsError(RuntimeError):
    """Unattended session refused because risk limits are still provisional."""


class UnreconciledError(RuntimeError):
    """Local ledger and broker positions disagree; no new order may be sent."""


@dataclass(frozen=True)
class SessionResult:
    """Outcome of submitting one proposal."""

    proposal: Proposal
    decision: RiskDecision
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    replayed: bool


class PaperSession:
    """One attended (or owner-approved unattended) paper execution session."""

    def __init__(
        self,
        *,
        limits: RiskLimits,
        ledger: ExecutionLedger,
        broker: PaperBroker,
        book: BookState,
        unattended: bool = False,
        kill_switch: bool = False,
    ) -> None:
        if unattended and limits.is_provisional:
            raise ProvisionalLimitsError(
                "unattended session refused while risk limits are provisional; "
                "complete docs/00_owner_mandate.md §3 and set owner_approved: true, "
                "or run an attended session"
            )
        self.limits = limits
        self.ledger = ledger
        self.broker = broker
        self.book = book
        self.unattended = unattended
        self.kill_switch = kill_switch
        self._restore_book()

    def _restore_book(self) -> None:
        for fill in self.ledger.fills():
            if fill.source is FillSource.BROKER_PAPER:
                self.book.apply_fill(fill)
        marks = {
            symbol: price
            for symbol in self.book.held_symbols
            if (price := self.book.avg_price(symbol)) is not None
        }
        if marks or not self.book.held_symbols:
            self.book.start_session(marks)

    def reconcile(self) -> ReconcileReport:
        """Compare ledger-implied positions to the broker."""
        return reconcile(self.ledger.broker_positions(), self.broker.positions())

    def submit_proposal(
        self,
        proposal: Proposal,
        *,
        prices: Mapping[str, Decimal],
        data_as_of: datetime,
        decided_at: datetime,
    ) -> SessionResult:
        """Evaluate and, if cleared, submit. Replays return the original orders."""
        marks = {symbol: Decimal(str(price)) for symbol, price in prices.items()}
        existing = self.ledger.decision_for_proposal(proposal.proposal_id)
        if existing is not None:
            orders = tuple(self.ledger.orders_for_decision(existing.decision_id))
            fills = tuple(
                fill
                for fill in self.ledger.fills()
                if fill.order_id in {order.order_id for order in orders}
            )
            return SessionResult(
                proposal=proposal,
                decision=existing,
                orders=orders,
                fills=fills,
                replayed=True,
            )
        report = self.reconcile()
        if not report.is_clean:
            raise UnreconciledError(
                "local ledger and broker disagree; refusing new orders: "
                f"local_only={report.local_only} broker_only={report.broker_only} "
                f"mismatches={len(report.quantity_mismatches)}"
            )
        if self.ledger.proposal_by_id(proposal.proposal_id) is None:
            self.ledger.append_proposal(proposal)
        decision = evaluate_proposal(
            proposal,
            limits=self.limits,
            book=self.book,
            prices=marks,
            decided_at=decided_at,
            data_as_of=data_as_of,
            kill_switch=self.kill_switch,
        )
        self.ledger.append_decision(decision)
        if decision.outcome is RiskOutcome.REJECTED:
            return SessionResult(
                proposal=proposal,
                decision=decision,
                orders=(),
                fills=(),
                replayed=False,
            )
        orders: list[Order] = []
        fills: list[Fill] = []
        for line in decision.approved_lines:
            client_id = derive_client_order_id(decision.decision_id, line.symbol, line.side)
            existing_order = self.ledger.order_by_client_id(
                client_id
            ) or self.broker.get_order_by_client_id(client_id)
            if existing_order is not None:
                orders.append(existing_order)
                continue
            pending = Order(
                order_id=f"ord-{client_id.removeprefix('lab-')[:32]}",
                client_order_id=client_id,
                decision_id=decision.decision_id,
                symbol=line.symbol,
                side=line.side,
                quantity=line.quantity,
                order_type=OrderType.MARKET,
                status=OrderStatus.PENDING_NEW,
                submitted_at=decided_at,
            )
            accepted = self.broker.submit_order(pending)
            self.ledger.append_order(accepted)
            orders.append(accepted)
            for broker_fill in self.broker.fills_for_order(accepted):
                self.ledger.append_fill(broker_fill)
                self.book.apply_fill(broker_fill)
                fills.append(broker_fill)
            reference = marks.get(line.symbol) or next(
                (item.reference_price for item in proposal.lines if item.symbol == line.symbol),
                None,
            )
            if reference is None:
                continue
            shadow = conservative_shadow_fill(
                accepted,
                reference_price=reference,
                recorded_at=decided_at,
                fill_id=f"shadow-{client_id}",
                sequence=1,
            )
            self.ledger.append_fill(shadow)
            fills.append(shadow)
        return SessionResult(
            proposal=proposal,
            decision=decision,
            orders=tuple(orders),
            fills=tuple(fills),
            replayed=False,
        )


def run_paper_session(
    *,
    source: str = "fixture",
    broker_name: str = "fake",
    sleeve: str = "momentum",
    as_of: date | None = None,
    clock: str = "as_of",
    output_dir: Path | None = None,
    ledger_dir: Path | None = None,
    unattended: bool = False,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
    registered_at: datetime | None = None,
) -> dict[str, object]:
    """Build a 0.2-sleeve proposal, evaluate risk, optionally submit paper orders."""
    limits = load_risk_limits(env=env)
    if unattended and limits.is_provisional:
        raise ProvisionalLimitsError(
            "unattended session refused while risk limits are provisional; "
            "complete docs/00_owner_mandate.md §3 and set owner_approved: true, "
            "or run an attended session"
        )
    config = load_experiment_config()
    universe = load_universe(config.universe_path)
    bars = load_bars(source, config, universe)
    days = session_days(bars)
    if not days:
        raise ValueError("no session days in bars")
    day = as_of if as_of is not None else days[-1]
    as_of_ts = as_of_close(day)
    created_at = registered_at if registered_at is not None else datetime.now(tz=UTC)
    experiment_id = f"paper-{config.config_hash}"
    proposal, prices, data_as_of = proposal_from_baseline(
        sleeve=sleeve,
        as_of=as_of_ts,
        created_at=created_at,
        bars=bars,
        universe=universe,
        config=config,
        experiment_id=experiment_id,
    )
    if data_as_of is None:
        data_as_of = as_of_ts
    decided_at = created_at if clock == "wall" else as_of_ts
    mapping = dict(os.environ if env is None else env)
    kill = kill_switch_engaged(env=mapping)
    ledger = ExecutionLedger(ledger_dir if ledger_dir is not None else DEFAULT_LEDGER_DIR)
    book = BookState.empty(limits.starting_capital)
    if broker_name == "fake":
        broker: PaperBroker = FakePaperBroker(marks=prices)
    elif broker_name == "alpaca":
        broker = AlpacaPaperBroker(env=mapping)
    else:
        raise ValueError(f"unknown broker {broker_name!r}")
    default_artifacts = DEFAULT_ARTIFACT_DIR / proposal.proposal_id
    artifacts = output_dir if output_dir is not None else default_artifacts
    artifacts.mkdir(parents=True, exist_ok=True)
    if dry_run:
        decision = evaluate_proposal(
            proposal,
            limits=limits,
            book=book,
            prices=prices,
            decided_at=decided_at,
            data_as_of=data_as_of,
            kill_switch=kill,
        )
        result = SessionResult(
            proposal=proposal, decision=decision, orders=(), fills=(), replayed=False
        )
    else:
        session = PaperSession(
            limits=limits,
            ledger=ledger,
            broker=broker,
            book=book,
            unattended=unattended,
            kill_switch=kill,
        )
        result = session.submit_proposal(
            proposal, prices=prices, data_as_of=data_as_of, decided_at=decided_at
        )
    _write_json(artifacts / "proposal.json", json.loads(result.proposal.model_dump_json()))
    _write_json(artifacts / "decision.json", json.loads(result.decision.model_dump_json()))
    _write_json(
        artifacts / "orders.json",
        [json.loads(order.model_dump_json()) for order in result.orders],
    )
    _write_json(
        artifacts / "fills.json",
        [json.loads(fill.model_dump_json()) for fill in result.fills],
    )
    report: dict[str, object] = {
        "proposal_id": result.proposal.proposal_id,
        "decision_id": result.decision.decision_id,
        "outcome": result.decision.outcome.value,
        "reason": result.decision.reason,
        "order_count": len(result.orders),
        "fill_count": len(result.fills),
        "replayed": result.replayed,
        "sleeve": sleeve,
        "bar_source": source,
        "broker": broker_name,
        "as_of": as_of_ts.isoformat(),
        "unattended": unattended,
        "limits_provisional": limits.is_provisional,
        "risk_config_hash": limits.config_hash,
        "artifact_dir": str(artifacts),
    }
    _write_json(artifacts / "report.json", report)
    report["_text"] = _render(report, result)
    return report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render(report: dict[str, object], result: SessionResult) -> str:
    return "\n".join(
        [
            f"proposal_id: {report['proposal_id']}",
            f"decision_id: {report['decision_id']}",
            f"outcome: {report['outcome']} ({result.decision.reason})",
            f"orders: {report['order_count']} replayed={report['replayed']}",
            f"sleeve: {report['sleeve']} source={report['bar_source']}",
            f"limits_provisional: {report['limits_provisional']}",
            f"wrote {report['artifact_dir']}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``python -m lab.execution``."""
    parser = argparse.ArgumentParser(description="Release 0.3 paper execution session.")
    parser.add_argument("--source", choices=("fixture", "alpaca"), default="fixture")
    parser.add_argument(
        "--sleeve",
        choices=("momentum", "equal_weight", "spy", "cash"),
        default="momentum",
    )
    parser.add_argument("--broker", choices=("fake", "alpaca"), default="fake")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--clock", choices=("as_of", "wall"), default="as_of")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="Refuse to run while risk limits are provisional.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Evaluate risk only.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.source == "alpaca" and not alpaca_keys_present():
        print(
            "Alpaca keys are not set. Use --source fixture or export "
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (paper only).",
            file=sys.stderr,
        )
        return 2
    if args.broker == "alpaca" and not alpaca_keys_present():
        print(
            "Alpaca paper keys are not set. Use --broker fake or export "
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (paper only).",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_paper_session(
            source=args.source,
            broker_name=args.broker,
            sleeve=args.sleeve,
            as_of=args.as_of,
            clock=args.clock,
            output_dir=args.output,
            ledger_dir=args.ledger,
            unattended=args.unattended,
            dry_run=args.dry_run,
        )
    except ProvisionalLimitsError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(report["_text"])
    return 0


__all__ = [
    "PaperSession",
    "ProvisionalLimitsError",
    "SessionResult",
    "UnreconciledError",
    "main",
    "run_paper_session",
]
