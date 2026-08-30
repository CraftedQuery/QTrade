"""Deterministic synthetic market data for tests.

This module lives in ``tests/`` on purpose. It is a **fixture, never a data
source** — nothing under ``src/lab/`` may import it, and a test enforces that.
Synthetic prices in a research pipeline would be indistinguishable from real
ones once stored, which is exactly the confusion this project cannot afford.

## Why the whole pipeline is tested against this

Real market data cannot prove the guarantees that matter. It has no known
correct answer, and it cannot be made to contain a deliberate future leak. A
seeded generator can: :func:`generate_bars` produces the same bytes every run,
and the edge-case knobs below construct exactly the situations the integrity
tests need to catch.

* ``delist_on`` — a symbol that stops trading mid-range, for survivorship tests.
* ``skip_sessions`` — a hole in the series, for gap handling.
* ``split`` — a raw-price discontinuity, so mixing adjusted and raw series is
  detectable.
* bars generated past a decision time — the planted future a feature pipeline
  must refuse to read.

## Simplifications

Sessions run 13:30-20:00 UTC on weekdays, with no holiday calendar and no
daylight-saving shift. Real sessions come from the data (decision D3); this
fixed schedule keeps generated data predictable, which is the point of a
fixture.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from lab.contracts import Bar, Instrument
from lab.contracts.enums import AssetClass, BarInterval, PriceAdjustment

SESSION_OPEN = timedelta(hours=13, minutes=30)
SESSION_CLOSE = timedelta(hours=20)
CENTS = Decimal("0.01")
SHARES = Decimal("1")

DEFAULT_SOURCE = "synthetic"


def trading_sessions(start: date, end: date, skip: Iterable[date] = ()) -> list[date]:
    """Weekday sessions in ``[start, end]``, minus any explicitly skipped dates.

    No holiday calendar: the generator's schedule is deliberately simple, and
    real sessions are derived from observed bars (decision D3).
    """
    skipped = set(skip)
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in skipped:
            days.append(current)
        current += timedelta(days=1)
    return days


def session_window(day: date) -> tuple[datetime, datetime]:
    """Open and close instants for one session, in UTC."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return midnight + SESSION_OPEN, midnight + SESSION_CLOSE


@dataclass(frozen=True)
class SymbolSpec:
    """How one synthetic symbol behaves.

    Attributes:
        symbol: Ticker.
        start_price: Price on the first session.
        annual_drift: Expected log return per year.
        annual_vol: Annualised volatility.
        delist_on: Last session this symbol trades. None means it never delists.
        skip_sessions: Sessions to omit, producing a gap in the series.
        split_on: Session at which a raw-price split discontinuity occurs.
        split_ratio: Divisor applied from ``split_on`` onward. 2 is a 2-for-1.
    """

    symbol: str
    start_price: Decimal = Decimal("100.00")
    annual_drift: float = 0.05
    annual_vol: float = 0.20
    delist_on: date | None = None
    skip_sessions: tuple[date, ...] = ()
    split_on: date | None = None
    split_ratio: Decimal = Decimal("2")
    asset_class: AssetClass = AssetClass.US_EQUITY
    exchange: str = "NASDAQ"
    listed_on: date | None = None

    def trades_on(self, day: date) -> bool:
        """Whether this symbol produces a bar on ``day``."""
        if self.listed_on is not None and day < self.listed_on:
            return False
        if self.delist_on is not None and day > self.delist_on:
            return False
        return day not in self.skip_sessions


@dataclass(frozen=True)
class MarketSpec:
    """A whole synthetic market: symbols, date range, and seed."""

    symbols: Sequence[SymbolSpec]
    start: date
    end: date
    seed: int = 20260830
    interval: BarInterval = BarInterval.DAY_1
    adjustment: PriceAdjustment = PriceAdjustment.RAW
    source: str = DEFAULT_SOURCE
    ingested_at: datetime = field(default_factory=lambda: datetime(2026, 8, 30, tzinfo=UTC))


def _quantize(value: Decimal, rounding: str = ROUND_HALF_UP) -> Decimal:
    return value.quantize(CENTS, rounding=rounding)


def _symbol_seed(seed: int, symbol: str) -> int:
    """Per-symbol seed, so adding a symbol never perturbs the others' data.

    Uses a stable digest rather than ``hash()``: Python randomises string
    hashing per process, so ``hash()`` would silently break determinism between
    runs while looking correct inside any single one.
    """
    digest = hashlib.sha256(symbol.encode()).digest()
    return seed ^ int.from_bytes(digest[:4], "big")


def generate_bars(spec: MarketSpec) -> list[Bar]:
    """Generate a deterministic set of bars for every symbol in ``spec``.

    The same ``MarketSpec`` always yields identical bars, and each symbol is
    seeded independently so adding one symbol leaves the others untouched.

    Every bar satisfies the :class:`~lab.contracts.market.Bar` contract by
    construction: quantisation rounds ``high`` up and ``low`` down, so rounding
    can never invert the OHLC invariants.
    """
    bars: list[Bar] = []
    for symbol_spec in spec.symbols:
        rng = random.Random(_symbol_seed(spec.seed, symbol_spec.symbol))  # noqa: S311
        sessions = [
            day
            for day in trading_sessions(spec.start, spec.end, symbol_spec.skip_sessions)
            if symbol_spec.trades_on(day)
        ]
        if not sessions:
            continue

        # Daily drift and volatility from annualised inputs, 252 sessions a year.
        drift = symbol_spec.annual_drift / 252
        vol = symbol_spec.annual_vol / (252**0.5)

        previous_close = symbol_spec.start_price
        for day in sessions:
            shock = rng.gauss(drift, vol)
            close = _quantize(previous_close * Decimal(str(1 + shock)))
            if close <= CENTS:
                close = CENTS

            if symbol_spec.split_on is not None and day >= symbol_spec.split_on:
                close = max(_quantize(close / symbol_spec.split_ratio), CENTS)

            open_gap = Decimal(str(1 + rng.gauss(0, vol / 2)))
            open_price = max(_quantize(previous_close * open_gap), CENTS)

            body_high = max(open_price, close)
            body_low = min(open_price, close)
            high = _quantize(
                body_high * Decimal(str(1 + abs(rng.gauss(0, vol / 2)))), ROUND_CEILING
            )
            low = _quantize(body_low * Decimal(str(1 - abs(rng.gauss(0, vol / 2)))), ROUND_FLOOR)
            low = max(min(low, body_low), CENTS)
            high = max(high, body_high)

            opened, closed = session_window(day)
            volume = Decimal(rng.randrange(100_000, 5_000_000)).quantize(SHARES)
            bars.append(
                Bar(
                    symbol=symbol_spec.symbol,
                    interval=spec.interval,
                    ts_start=opened,
                    ts_end=closed,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    vwap=_quantize((high + low + close) / 3),
                    trade_count=rng.randrange(1_000, 50_000),
                    adjustment=spec.adjustment,
                    source=spec.source,
                    ingested_at=spec.ingested_at,
                )
            )
            previous_close = close

    return sorted(bars, key=lambda bar: (bar.symbol, bar.ts_start))


def generate_instruments(spec: MarketSpec) -> list[Instrument]:
    """Instrument records matching the symbols in ``spec``.

    ``listed_on`` defaults to the market's start date and ``delisted_on`` follows
    each symbol's ``delist_on``, so point-in-time membership is answerable.
    """
    return [
        Instrument(
            symbol=symbol_spec.symbol,
            name=f"{symbol_spec.symbol} Test Issue",
            asset_class=symbol_spec.asset_class,
            exchange=symbol_spec.exchange,
            listed_on=symbol_spec.listed_on or spec.start,
            delisted_on=symbol_spec.delist_on,
            is_tradable=symbol_spec.delist_on is None,
            source=spec.source,
            retrieved_at=spec.ingested_at,
        )
        for symbol_spec in sorted(spec.symbols, key=lambda one: one.symbol)
    ]


def simple_market(
    symbols: Sequence[str] = ("AAA", "BBB", "CCC"),
    start: date = date(2024, 1, 1),
    end: date = date(2024, 6, 28),
    seed: int = 20260830,
) -> MarketSpec:
    """A small, well-behaved market. The default fixture for most tests."""
    return MarketSpec(
        symbols=tuple(SymbolSpec(symbol=symbol) for symbol in symbols),
        start=start,
        end=end,
        seed=seed,
    )


__all__ = [
    "DEFAULT_SOURCE",
    "SESSION_CLOSE",
    "SESSION_OPEN",
    "MarketSpec",
    "SymbolSpec",
    "generate_bars",
    "generate_instruments",
    "session_window",
    "simple_market",
    "trading_sessions",
]
