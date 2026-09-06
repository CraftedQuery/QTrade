"""Deterministic synthetic daily bars for offline baseline runs.

The generator is the committed fixture: the same seed, symbols, and date range
always produce the same OHLCV. Provenance is recorded on every bar. This is
not vendor data and is not a substitute for a licensed historical feed.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from lab.contracts import Bar
from lab.contracts.enums import BarInterval, PriceAdjustment
from lab.data.calendar import session_end, session_start, weekdays

FIXTURE_INGESTED_AT = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
FIXTURE_SOURCE = "committed-fixture"


def generate_daily_bars(
    symbols: Sequence[str],
    start: date,
    end: date,
    *,
    seed: int,
    source: str = FIXTURE_SOURCE,
    ingested_at: datetime | None = None,
) -> list[Bar]:
    """Return one daily bar per weekday in ``[start, end)`` for each symbol.

    Paths are independent per symbol and fully determined by ``seed``. Prices
    stay positive and satisfy the :class:`~lab.contracts.market.Bar` OHLC
    invariants.
    """
    if not symbols:
        raise ValueError("at least one symbol is required")
    stamped = FIXTURE_INGESTED_AT if ingested_at is None else ingested_at
    days = weekdays(start, end)
    bars: list[Bar] = []
    for symbol in symbols:
        rng = random.Random(f"{seed}:{symbol}")  # noqa: S311 — fixture paths, not crypto
        price = Decimal(str(round(40 + rng.random() * 160, 2)))
        for day in days:
            ret = Decimal(str(round(rng.gauss(0.0004, 0.012), 6)))
            new_price = max(Decimal("1.00"), (price * (1 + ret)).quantize(Decimal("0.01")))
            high_bump = Decimal(str(round(abs(rng.gauss(0, 0.004)), 6)))
            low_bump = Decimal(str(round(abs(rng.gauss(0, 0.004)), 6)))
            high = max(price, new_price) * (1 + high_bump)
            low = min(price, new_price) * (1 - low_bump)
            low = max(Decimal("0.01"), low.quantize(Decimal("0.01")))
            high = high.quantize(Decimal("0.01"))
            if high < max(price, new_price):
                high = max(price, new_price)
            if low > min(price, new_price):
                low = min(price, new_price)
            volume = Decimal(1_000_000 + rng.randint(0, 750_000))
            bars.append(
                Bar(
                    symbol=symbol,
                    interval=BarInterval.DAY_1,
                    ts_start=session_start(day),
                    ts_end=session_end(day),
                    open=price,
                    high=high,
                    low=low,
                    close=new_price,
                    volume=volume,
                    adjustment=PriceAdjustment.SPLIT_AND_DIVIDEND,
                    source=source,
                    ingested_at=stamped,
                )
            )
            price = new_price
    return bars


__all__ = ["FIXTURE_INGESTED_AT", "FIXTURE_SOURCE", "generate_daily_bars"]
