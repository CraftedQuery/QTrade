"""Append-only JSONL ledger for proposals, decisions, orders, and fills."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from lab.contracts import Fill, Order, Proposal, RiskDecision
from lab.contracts.enums import FillSource, Side


class ExecutionLedger:
    """File-backed append-only store. Restart by pointing at the same directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        return self.root / f"{kind}.jsonl"

    def _append(self, kind: str, payload: str) -> None:
        path = self._path(kind)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")

    def _load(self, kind: str) -> list[str]:
        path = self._path(kind)
        if not path.is_file():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append_proposal(self, proposal: Proposal) -> None:
        """Append one proposal record."""
        self._append("proposals", proposal.model_dump_json())

    def append_decision(self, decision: RiskDecision) -> None:
        """Append one risk decision."""
        self._append("decisions", decision.model_dump_json())

    def append_order(self, order: Order) -> None:
        """Append one order."""
        self._append("orders", order.model_dump_json())

    def append_fill(self, fill: Fill) -> None:
        """Append one fill. Broker and shadow records coexist."""
        self._append("fills", fill.model_dump_json())

    def proposals(self) -> list[Proposal]:
        """Every stored proposal, in write order."""
        return [Proposal.model_validate_json(line) for line in self._load("proposals")]

    def decisions(self) -> list[RiskDecision]:
        """Every stored decision, in write order."""
        return [RiskDecision.model_validate_json(line) for line in self._load("decisions")]

    def orders(self) -> list[Order]:
        """Every stored order, in write order."""
        return [Order.model_validate_json(line) for line in self._load("orders")]

    def fills(self) -> list[Fill]:
        """Every stored fill, in write order."""
        return [Fill.model_validate_json(line) for line in self._load("fills")]

    def proposal_by_id(self, proposal_id: str) -> Proposal | None:
        """Return the first stored proposal with this id."""
        for proposal in self.proposals():
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def decision_for_proposal(self, proposal_id: str) -> RiskDecision | None:
        """Return the first stored decision for ``proposal_id``."""
        for decision in self.decisions():
            if decision.proposal_id == proposal_id:
                return decision
        return None

    def orders_for_decision(self, decision_id: str) -> list[Order]:
        """Orders that belong to ``decision_id``."""
        return [order for order in self.orders() if order.decision_id == decision_id]

    def order_by_client_id(self, client_order_id: str) -> Order | None:
        """Return the first stored order with this client order id."""
        for order in self.orders():
            if order.client_order_id == client_order_id:
                return order
        return None

    def broker_positions(self) -> dict[str, Decimal]:
        """Share counts implied by ``broker_paper`` fills only."""
        qty: dict[str, Decimal] = {}
        for fill in self.fills():
            if fill.source is not FillSource.BROKER_PAPER:
                continue
            held = qty.get(fill.symbol, Decimal(0))
            if fill.side is Side.BUY:
                held += fill.quantity
            else:
                held -= fill.quantity
            qty[fill.symbol] = held
        return {symbol: value for symbol, value in qty.items() if value != 0}


__all__ = ["ExecutionLedger"]
