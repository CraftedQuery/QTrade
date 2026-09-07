"""Alpaca **paper** order adapter. Live trading hosts are refused."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lab.contracts import Fill, Order
from lab.contracts.enums import FillSource, OrderStatus, OrderType, Side, TimeInForce
from lab.data.alpaca import alpaca_keys_present

DEFAULT_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_PAPER_HOSTS = frozenset({"paper-api.alpaca.markets"})
LIVE_TRADING_HOST = "api.alpaca.markets"

_STATUS = {
    "new": OrderStatus.ACCEPTED,
    "accepted": OrderStatus.ACCEPTED,
    "pending_new": OrderStatus.PENDING_NEW,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
}


def _paper_base_url(env: Mapping[str, str]) -> str:
    raw = env.get("ALPACA_PAPER_BASE_URL", DEFAULT_PAPER_BASE_URL).strip() or DEFAULT_PAPER_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("Alpaca paper URL must be https")
    host = (parsed.hostname or "").lower()
    if host == LIVE_TRADING_HOST:
        raise ValueError("refusing the live trading host; paper orders use the paper API")
    if host not in ALLOWED_PAPER_HOSTS:
        raise ValueError(f"refusing unapproved paper host {host!r}")
    return raw.rstrip("/")


def _read_json(opener: Callable[..., Any], request: Request, timeout: float) -> dict[str, Any]:
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise exc
    except URLError as exc:
        raise ValueError("Alpaca paper request failed") from exc
    if not isinstance(payload, dict):
        raise ValueError("Alpaca paper response was not an object")
    return payload


class AlpacaPaperBroker:
    """Submit paper orders with deterministic client order ids."""

    def __init__(
        self,
        *,
        env: Mapping[str, str],
        opener: Callable[..., Any] | None = None,
        timeout: float = 30,
    ) -> None:
        if not alpaca_keys_present(env):
            raise ValueError(
                "Alpaca paper orders require ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY"
            )
        self._env = env
        self._key = env["ALPACA_API_KEY_ID"].strip()
        self._secret = env["ALPACA_API_SECRET_KEY"].strip()
        self._base = _paper_base_url(env)
        self._opener: Callable[..., Any] = opener if opener is not None else urlopen
        self._timeout = timeout
        self._cached_payload: dict[str, Any] = {}

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> Request:
        data = None if body is None else json.dumps(body).encode("utf-8")
        return Request(  # noqa: S310 — host is allow-listed to paper-api.alpaca.markets
            f"{self._base}{path}",
            data=data,
            headers={
                "APCA-API-KEY-ID": self._key,
                "APCA-API-SECRET-KEY": self._secret,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )

    def get_order_by_client_id(self, client_order_id: str) -> Order | None:
        """GET the paper order, or ``None`` when the broker has never seen it."""
        request = self._request("GET", f"/v2/orders:by_client_order_id/{client_order_id}")
        try:
            payload = _read_json(self._opener, request, self._timeout)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise ValueError(f"Alpaca paper request failed: HTTP {exc.code}") from exc
        self._cached_payload = payload
        return _order_from_alpaca(payload, fallback=None)

    def submit_order(self, order: Order) -> Order:
        """POST once. An existing client order id is returned, never duplicated."""
        existing = self.get_order_by_client_id(order.client_order_id)
        if existing is not None:
            return existing.model_copy(
                update={
                    "order_id": order.order_id,
                    "decision_id": order.decision_id,
                    "submitted_at": order.submitted_at,
                }
            )
        body = {
            "symbol": order.symbol,
            "qty": str(order.quantity),
            "side": order.side.value,
            "type": order.order_type.value,
            "time_in_force": order.time_in_force.value,
            "client_order_id": order.client_order_id,
        }
        request = self._request("POST", "/v2/orders", body)
        try:
            payload = _read_json(self._opener, request, self._timeout)
        except HTTPError as exc:
            if exc.code == 409:
                found = self.get_order_by_client_id(order.client_order_id)
                if found is not None:
                    return found.model_copy(
                        update={
                            "order_id": order.order_id,
                            "decision_id": order.decision_id,
                            "submitted_at": order.submitted_at,
                        }
                    )
            raise ValueError(f"Alpaca paper request failed: HTTP {exc.code}") from exc
        return _order_from_alpaca(payload, fallback=order)

    def positions(self) -> dict[str, Decimal]:
        """GET /v2/positions."""
        request = self._request("GET", "/v2/positions")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ValueError(f"Alpaca paper request failed: HTTP {exc.code}") from exc
        if not isinstance(payload, list):
            raise ValueError("Alpaca positions response was not a list")
        held: dict[str, Decimal] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            qty = Decimal(str(row.get("qty") or "0"))
            if symbol and qty > 0:
                held[symbol] = qty
        return held

    def fills_for_order(self, order: Order) -> list[Fill]:
        """One broker paper fill when the paper order reports a fill price."""
        latest = self.get_order_by_client_id(order.client_order_id)
        if latest is None:
            return []
        raw = self._cached_payload
        if not raw:
            return []
        filled_qty = Decimal(str(raw.get("filled_qty") or "0"))
        avg = raw.get("filled_avg_price")
        if filled_qty <= 0 or avg in {None, ""}:
            return []
        filled_at = _parse_time(raw.get("filled_at") or raw.get("updated_at"))
        return [
            Fill(
                fill_id=f"alpaca-{order.client_order_id}",
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                source=FillSource.BROKER_PAPER,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_qty,
                price=Decimal(str(avg)),
                fee=Decimal(0),
                filled_at=filled_at or order.submitted_at,
                recorded_at=datetime.now(tz=UTC),
                sequence=0,
            )
        ]


def _parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _order_from_alpaca(payload: dict[str, Any], fallback: Order | None) -> Order:
    status_raw = str(payload.get("status") or "accepted")
    status = _STATUS.get(status_raw, OrderStatus.ACCEPTED)
    raw_client = payload.get("client_order_id")
    client_id = str(raw_client or (fallback.client_order_id if fallback else ""))
    symbol = str(payload.get("symbol") or (fallback.symbol if fallback else ""))
    side = Side(str(payload.get("side") or (fallback.side.value if fallback else "buy")))
    qty = Decimal(str(payload.get("qty") or (fallback.quantity if fallback else "0")))
    submitted = _parse_time(payload.get("submitted_at"))
    if fallback is None:
        if not client_id or not symbol or qty <= 0:
            raise ValueError("Alpaca order payload missing required fields")
        return Order(
            order_id=f"ord-{client_id.removeprefix('lab-')[:32]}",
            client_order_id=client_id,
            decision_id="unknown",
            symbol=symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            status=status,
            submitted_at=submitted or datetime.now(tz=UTC),
            broker_order_id=str(payload.get("id") or "") or None,
        )
    return fallback.model_copy(
        update={
            "status": status,
            "broker_order_id": str(payload.get("id") or "") or None,
        }
    )


__all__ = [
    "ALLOWED_PAPER_HOSTS",
    "DEFAULT_PAPER_BASE_URL",
    "LIVE_TRADING_HOST",
    "AlpacaPaperBroker",
]
