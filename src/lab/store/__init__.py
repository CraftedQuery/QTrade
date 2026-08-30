"""Local record store: Parquet files on disk, queried through DuckDB.

Prices and quantities are stored as exact decimals. The store converts contracts
to Arrow directly rather than through pandas, so a Decimal cannot be silently
downgraded to a float on its way to disk; see :mod:`lab.store.arrow`.
"""

from __future__ import annotations

from lab.store.arrow import BAR_SCHEMA, INSTRUMENT_SCHEMA, MONEY, from_table, to_table
from lab.store.parquet import (
    DATA_DIR_ENV,
    DEFAULT_DATA_DIR,
    BarStore,
    InstrumentStore,
    WriteResult,
    resolve_data_root,
)

__all__ = [
    "BAR_SCHEMA",
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR",
    "INSTRUMENT_SCHEMA",
    "MONEY",
    "BarStore",
    "InstrumentStore",
    "WriteResult",
    "from_table",
    "resolve_data_root",
    "to_table",
]
