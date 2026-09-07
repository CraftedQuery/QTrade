"""Paper broker protocol and an in-process fake used by tests and fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from lab.contracts import Fill, Order
from lab.contracts.enums import FillSource, OrderStatus, Side


class PaperBroker(Protocol):
    """The only methods the session needs from a paper broker."""

    def submit_order(self, order: Order) -> Order:
        """Submit or return the existing order for ``order.client_order_id``."""

    def get_order_by_client_id(self, client_order_id: str) -> Order | None:
        """Look up a previously submitted order."""

    def positions(self) -> dict[str, Decimal]:
        """Broker view of long share counts."""

    def fills_for_order(self, order: Order) -> list[Fill]:
        """Broker paper fills for ``order``, if any."""


class FakePaperBroker:
    """In-memory paper broker. Duplicate client order ids are no-ops."""

    def __init__(self, marks: Mapping[str, Decimal] | None = None) -> None:
        self._orders: dict[str, Order] = {}
        self._fills: dict[str, Fill] = {}
        self._qty: dict[str, Decimal] = {}
        self._marks = dict(marks or {})
        self.submit_calls = 0

    def submit_order(self, order: Order) -> Order:
        """Accept a market order once per client order id."""
        existing = self._orders.get(order.client_order_id)
        if existing is not None:
            return existing
        self.submit_calls += 1
        accepted = order.model_copy(
            update={
                "status": OrderStatus.FILLED,
                "broker_order_id": f"fake-{order.client_order_id}",
            }
        )
        self._orders[order.client_order_id] = accepted
        price = self._marks.get(order.symbol, Decimal("1"))
        filled_at = accepted.submitted_at
        fill = Fill(
            fill_id=f"fake-fill-{order.client_order_id}",
            order_id=accepted.order_id,
            client_order_id=accepted.client_order_id,
            source=FillSource.BROKER_PAPER,
            symbol=accepted.symbol,
            side=accepted.side,
            quantity=accepted.quantity,
            price=price,
            fee=Decimal(0),
            filled_at=filled_at,
            recorded_at=datetime.now(tz=UTC) if filled_at.tzinfo else filled_at,
            sequence=0,
        )
        self._fills[order.client_order_id] = fill
        held = self._qty.get(order.symbol, Decimal(0))
        if order.side is Side.BUY:
            self._qty[order.symbol] = held + order.quantity
        else:
            remaining = held - order.quantity
            if remaining < 0:
                remaining = Decimal(0)
            if remaining == 0:
                self._qty.pop(order.symbol, None)
            else:
                self._qty[order.symbol] = remaining
        return accepted

    def get_order_by_client_id(self, client_order_id: str) -> Order | None:
        """Return the stored order, if any."""
        return self._orders.get(client_order_id)

    def positions(self) -> dict[str, Decimal]:
        """Current fake-broker longs."""
        return {symbol: qty for symbol, qty in self._qty.items() if qty > 0}

    def fills_for_order(self, order: Order) -> list[Fill]:
        """The single immediate fill, when present."""
        fill = self._fills.get(order.client_order_id)
        return [fill] if fill is not None else []

    def orders(self) -> list[Order]:
        """All accepted orders."""
        return list(self._orders.values())

    def position_qty(self, symbol: str) -> Decimal:
        """Shares the fake broker holds in ``symbol``."""
        return self._qty.get(symbol, Decimal(0))

    def force_position(self, symbol: str, quantity: Decimal) -> None:
        """Test helper: create a broker-only position the ledger does not know."""
        if quantity == 0:
            self._qty.pop(symbol, None)
            return
        self._qty[symbol] = quantity


__all__ = ["FakePaperBroker", "PaperBroker"]
