"""Closed vocabularies used by the data contracts.

These are deliberately narrow. A value that is absent from an enum is a value
the lab cannot represent, which is the cheapest available enforcement of the
mandate: there is no ``SHORT`` side, no ``CRYPTO`` asset class, and no ``LIVE``
account mode anywhere in this module.
"""

from __future__ import annotations

from enum import StrEnum


class AccountMode(StrEnum):
    """Trading mode of an account.

    This enum has exactly one member on purpose. Live trading is not merely
    discouraged, it is unrepresentable: no valid :class:`~lab.contracts.execution.Order`
    can describe a live order.
    """

    PAPER = "paper"


class AssetClass(StrEnum):
    """Instrument categories in scope. Options, futures and crypto are absent."""

    US_EQUITY = "us_equity"
    US_ETF = "us_etf"


class BarInterval(StrEnum):
    """Supported OHLCV bar intervals."""

    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    HOUR_1 = "1hour"
    DAY_1 = "1day"


class PriceAdjustment(StrEnum):
    """How corporate actions have been applied to a bar's prices.

    Recorded explicitly because silently mixing adjusted and raw series is a
    classic source of fake backtest performance.
    """

    RAW = "raw"
    SPLIT = "split"
    SPLIT_AND_DIVIDEND = "split_and_dividend"


class Side(StrEnum):
    """Order side.

    ``SELL`` may only reduce or close an existing long position; it can never
    open a short. That invariant is enforced by the position-aware risk engine,
    not by this enum.
    """

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    """Order lifetime. Regular-session day orders only."""

    DAY = "day"


class OrderStatus(StrEnum):
    """Lifecycle state of an order."""

    PENDING_NEW = "pending_new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FillSource(StrEnum):
    """Origin of a fill record.

    Broker paper fills and conservative internal shadow fills are stored side
    by side and never merged or overwritten, so the two can always be compared.
    """

    BROKER_PAPER = "broker_paper"
    INTERNAL_SHADOW = "internal_shadow"


class RiskOutcome(StrEnum):
    """Verdict of the deterministic risk engine on a proposal."""

    APPROVED = "approved"
    REDUCED = "reduced"
    REJECTED = "rejected"


class ExperimentStatus(StrEnum):
    """Lifecycle state of a registered experiment."""

    REGISTERED = "registered"
    RUNNING = "running"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class DatasetSplit(StrEnum):
    """Which walk-forward split a prediction belongs to."""

    TRAIN = "train"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


__all__ = [
    "AccountMode",
    "AssetClass",
    "BarInterval",
    "DatasetSplit",
    "ExperimentStatus",
    "FillSource",
    "OrderStatus",
    "OrderType",
    "PriceAdjustment",
    "RiskOutcome",
    "Side",
    "TimeInForce",
]
