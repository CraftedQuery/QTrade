"""Conservative internal shadow fills stay worse than paper and never overwrite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from lab.contracts.enums import FillSource, Side
from lab.execution.shadow import conservative_shadow_fill
from tests.factories import make_fill, make_order

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)


def test_shadow_buy_is_worse_than_the_reference() -> None:
    order = make_order(side=Side.BUY, submitted_at=NOW)
    shadow = conservative_shadow_fill(
        order,
        reference_price=Decimal("100.00"),
        recorded_at=NOW,
        fill_id="shadow-1",
    )
    assert shadow.source is FillSource.INTERNAL_SHADOW
    assert shadow.price > Decimal("100.00")
    assert shadow.filled_at == NOW + timedelta(seconds=30)
    assert shadow.order_id == order.order_id
    assert shadow.client_order_id == order.client_order_id


def test_shadow_sell_is_worse_than_the_reference() -> None:
    order = make_order(side=Side.SELL, submitted_at=NOW)
    shadow = conservative_shadow_fill(
        order,
        reference_price=Decimal("100.00"),
        recorded_at=NOW,
        fill_id="shadow-2",
    )
    assert shadow.price < Decimal("100.00")
    assert shadow.source is FillSource.INTERNAL_SHADOW


def test_shadow_does_not_overwrite_a_broker_fill() -> None:
    broker = make_fill(price=Decimal("100.00"))
    order = make_order()
    shadow = conservative_shadow_fill(
        order,
        reference_price=Decimal("100.00"),
        recorded_at=NOW,
        fill_id="shadow-3",
        sequence=1,
    )
    assert broker.source is FillSource.BROKER_PAPER
    assert shadow.source is FillSource.INTERNAL_SHADOW
    assert broker.fill_id != shadow.fill_id
    assert broker.price != shadow.price
    assert broker.order_id == shadow.order_id
