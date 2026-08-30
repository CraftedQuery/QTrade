"""Arrow schemas and conversion between contracts and on-disk columns.

The store deliberately converts Pydantic models to Arrow **directly**, never via
pandas. pandas has no Decimal column type, so a price that passed through a
DataFrame would arrive on disk as a float64 and quietly lose precision. Prices
and quantities are stored as ``decimal128(38, 12)``, which round-trips exactly
through both Parquet and DuckDB.

A value carrying more than twelve decimal places raises on write rather than
truncating silently. That is the intended behaviour: a price the store cannot
represent exactly is a bug to surface, not to round.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum

import pyarrow as pa

from lab.contracts import Bar, Instrument
from lab.contracts.base import LabRecord

MONEY = pa.decimal128(38, 12)
"""On-disk type for every Decimal field: 26 integer digits, 12 fractional."""

TIMESTAMP = pa.timestamp("us", tz="UTC")
"""Microsecond UTC timestamps, matching Python's datetime resolution."""

BAR_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("interval", pa.string(), nullable=False),
        pa.field("ts_start", TIMESTAMP, nullable=False),
        pa.field("ts_end", TIMESTAMP, nullable=False),
        pa.field("open", MONEY, nullable=False),
        pa.field("high", MONEY, nullable=False),
        pa.field("low", MONEY, nullable=False),
        pa.field("close", MONEY, nullable=False),
        pa.field("volume", MONEY, nullable=False),
        pa.field("vwap", MONEY, nullable=True),
        pa.field("trade_count", pa.int64(), nullable=True),
        pa.field("adjustment", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("ingested_at", TIMESTAMP, nullable=False),
    ]
)

INSTRUMENT_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=True),
        pa.field("asset_class", pa.string(), nullable=False),
        pa.field("exchange", pa.string(), nullable=False),
        pa.field("currency", pa.string(), nullable=False),
        pa.field("listed_on", pa.date32(), nullable=True),
        pa.field("delisted_on", pa.date32(), nullable=True),
        pa.field("is_tradable", pa.bool_(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("retrieved_at", TIMESTAMP, nullable=False),
    ]
)

SCHEMAS: dict[type[LabRecord], pa.Schema] = {
    Bar: BAR_SCHEMA,
    Instrument: INSTRUMENT_SCHEMA,
}


def _column_value(value: object) -> object:
    """Render one field value in the form Arrow expects."""
    return value.value if isinstance(value, Enum) else value


def to_table[R: LabRecord](records: Sequence[R], schema: pa.Schema) -> pa.Table:
    """Convert contract records into an Arrow table with an explicit schema.

    Raises:
        pyarrow.ArrowInvalid: If a Decimal carries more precision than the
            on-disk type can hold. Failing loudly is deliberate.
    """
    columns: dict[str, list[object]] = {name: [] for name in schema.names}
    for record in records:
        dumped = record.model_dump()
        for name in schema.names:
            columns[name].append(_column_value(dumped[name]))
    return pa.Table.from_pydict(columns, schema=schema)


def from_table[R: LabRecord](table: pa.Table, model: type[R]) -> list[R]:
    """Convert an Arrow table back into validated contract records.

    Every row is re-validated through the contract, so anything that drifted on
    disk fails here rather than deep inside an experiment.
    """
    return [model.model_validate(row) for row in table.to_pylist()]


def sort_key_bars(bars: Iterable[Bar]) -> list[Bar]:
    """Order bars deterministically, so identical input yields identical files."""
    return sorted(bars, key=lambda bar: (bar.symbol, bar.interval.value, bar.ts_start))


def sort_key_instruments(instruments: Iterable[Instrument]) -> list[Instrument]:
    """Order instruments deterministically by symbol."""
    return sorted(instruments, key=lambda instrument: instrument.symbol)


__all__ = [
    "BAR_SCHEMA",
    "INSTRUMENT_SCHEMA",
    "MONEY",
    "SCHEMAS",
    "TIMESTAMP",
    "from_table",
    "sort_key_bars",
    "sort_key_instruments",
    "to_table",
]
