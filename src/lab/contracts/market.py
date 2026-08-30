"""Market data contracts: :class:`Instrument` and :class:`Bar`."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from lab.contracts.base import Identifier, LabRecord, Price, Quantity, UtcDatetime
from lab.contracts.enums import AssetClass, BarInterval, PriceAdjustment


class Instrument(LabRecord):
    """A tradable U.S. equity or ETF.

    ``listed_on`` and ``delisted_on`` exist so that universe membership can be
    reconstructed *as of a past date*. Without them a universe built from a
    current constituent list is survivorship-biased, which flatters every
    backtest that uses it.
    """

    symbol: Identifier = Field(description="Exchange ticker, e.g. 'SPY'.")
    name: str | None = Field(default=None, description="Issuer or fund name.")
    asset_class: AssetClass = Field(description="Instrument category.")
    exchange: str = Field(description="Primary listing exchange, e.g. 'NASDAQ'.")
    currency: Literal["USD"] = Field(default="USD", description="Quote currency.")
    listed_on: date | None = Field(
        default=None,
        description="First trading date, if known. Required for point-in-time universes.",
    )
    delisted_on: date | None = Field(
        default=None, description="Last trading date. None means still listed."
    )
    is_tradable: bool = Field(default=True, description="Whether the lab may trade it today.")
    source: str = Field(description="Data provider this record came from.")
    retrieved_at: UtcDatetime = Field(description="When the record was fetched.")

    @model_validator(mode="after")
    def _check_listing_window(self) -> Self:
        if self.listed_on and self.delisted_on and self.delisted_on < self.listed_on:
            raise ValueError("delisted_on must not precede listed_on")
        return self

    def was_listed_on(self, day: date) -> bool:
        """Return whether the instrument was tradable on ``day``.

        Returns ``False`` when ``listed_on`` is unknown: an unknown listing date
        cannot support a point-in-time claim, and refusing is safer than guessing.
        """
        if self.listed_on is None or day < self.listed_on:
            return False
        return self.delisted_on is None or day <= self.delisted_on


class Bar(LabRecord):
    """A single OHLCV bar over the half-open interval ``[ts_start, ts_end)``.

    The bar's contents are not knowable until ``ts_end``. Use
    :attr:`information_time`, never ``ts_start``, when deciding whether a bar may
    feed a feature computed at some decision time.
    """

    symbol: Identifier = Field(description="Instrument ticker.")
    interval: BarInterval = Field(description="Bar width.")
    ts_start: UtcDatetime = Field(description="Inclusive start of the bar window.")
    ts_end: UtcDatetime = Field(description="Exclusive end of the bar window.")
    open: Price = Field(description="First trade price in the window.")
    high: Price = Field(description="Highest trade price in the window.")
    low: Price = Field(description="Lowest trade price in the window.")
    close: Price = Field(description="Last trade price in the window.")
    volume: Quantity = Field(description="Shares traded in the window.")
    vwap: Price | None = Field(default=None, description="Volume-weighted average price.")
    trade_count: int | None = Field(default=None, ge=0, description="Number of trades.")
    adjustment: PriceAdjustment = Field(description="Corporate-action adjustment applied.")
    source: str = Field(description="Data provider this bar came from.")
    ingested_at: UtcDatetime = Field(description="When the lab stored the bar.")

    @model_validator(mode="after")
    def _check_window_and_prices(self) -> Self:
        if self.ts_end <= self.ts_start:
            raise ValueError("ts_end must be strictly after ts_start")
        if self.high < self.low:
            raise ValueError("high must not be below low")
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least the open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most the open and close")
        return self

    @property
    def information_time(self) -> datetime:
        """Earliest time this bar may legitimately be used as an input."""
        return self.ts_end


__all__ = ["Bar", "Instrument"]
