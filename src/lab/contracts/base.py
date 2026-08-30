"""Shared base types for every AI Trading Lab data contract.

Every contract in this package is:

* **frozen** — a persisted record is never edited in place, only superseded;
* **strict** — unknown fields raise instead of being silently dropped, so a
  schema drift shows up at the boundary rather than deep in a backtest;
* **UTC-aware** — naive datetimes are rejected, because an ambiguous timestamp
  is the cheapest way to introduce look-ahead bias;
* **versioned** — every record carries the ``schema_version`` it was written
  under, so old records stay readable after the contract moves on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"
"""Version stamped onto new records. Bump on any breaking contract change."""


def _coerce_to_utc(value: object) -> object:
    """Reject naive datetimes and normalise aware ones to UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "datetime must be timezone-aware; a naive timestamp is ambiguous "
                "and is a common source of look-ahead bias"
            )
        return value.astimezone(UTC)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_coerce_to_utc)]
"""A timezone-aware datetime, normalised to UTC."""

Price = Annotated[Decimal, Field(ge=0)]
"""A non-negative monetary amount. Decimal, never float, in an order path."""

Quantity = Annotated[Decimal, Field(ge=0)]
"""A non-negative share quantity. Fractional shares are permitted."""

Weight = Annotated[Decimal, Field(ge=0, le=1)]
"""A portfolio weight in [0, 1]. The upper bound is a sanity check; the lower
bound is the structural expression of *long or cash only* — a short position
cannot be represented."""

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
"""A non-empty opaque identifier."""


class LabModel(BaseModel):
    """Frozen, strict base for contracts and the value objects inside them."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
    )


class LabRecord(LabModel):
    """A contract that is persisted to the append-only record store."""

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Contract version this record was written under.",
    )


__all__ = [
    "SCHEMA_VERSION",
    "Identifier",
    "LabModel",
    "LabRecord",
    "Price",
    "Quantity",
    "UtcDatetime",
    "Weight",
]
