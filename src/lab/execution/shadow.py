"""Conservative internal shadow fills. Deliberately worse than paper."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from lab.contracts import Fill, Order
from lab.contracts.enums import FillSource, Side

DEFAULT_SHADOW_SPREAD_BPS = Decimal("10")
DEFAULT_SHADOW_DELAY_SECONDS = 30


def conservative_shadow_fill(
    order: Order,
    *,
    reference_price: Decimal,
    recorded_at: datetime,
    fill_id: str,
    sequence: int = 0,
    spread_bps: Decimal = DEFAULT_SHADOW_SPREAD_BPS,
    delay_seconds: int = DEFAULT_SHADOW_DELAY_SECONDS,
) -> Fill:
    """Estimate the same order at a worse price, after a delay.

    Buys pay more than the reference; sells receive less. The record is
    ``internal_shadow`` and never replaces a broker paper fill.
    """
    slip = (reference_price * spread_bps) / Decimal("10000")
    if order.side is Side.BUY:
        price = reference_price + slip
    else:
        price = reference_price - slip
        if price <= 0:
            price = Decimal("0.01")
    filled_at = order.submitted_at + timedelta(seconds=delay_seconds)
    return Fill(
        fill_id=fill_id,
        order_id=order.order_id,
        client_order_id=order.client_order_id,
        source=FillSource.INTERNAL_SHADOW,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=price,
        fee=Decimal(0),
        filled_at=filled_at,
        recorded_at=recorded_at,
        sequence=sequence,
    )


__all__ = [
    "DEFAULT_SHADOW_DELAY_SECONDS",
    "DEFAULT_SHADOW_SPREAD_BPS",
    "conservative_shadow_fill",
]
