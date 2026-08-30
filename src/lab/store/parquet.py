"""Parquet record store, queried through DuckDB.

Layout under the data root:

    bars/<interval>/<symbol>/bars.parquet
    instruments/instruments.parquet

Directory names are deliberately plain rather than Hive-style ``key=value``.
Every column, partition keys included, lives inside the file, so a read never
has to infer a type from a directory name. Hive naming would invite pyarrow and
DuckDB to synthesise partition columns that collide with the real ones.

## Write semantics

Writes are **upserts keyed by the record's natural key** — ``(symbol, interval,
ts_start)`` for a bar, ``symbol`` for an instrument — with three properties that
matter for a research store:

* **Idempotent.** Writing records that are already present touches no file at
  all. ``WriteResult.partitions_written`` is 0 and the store is byte-identical.
* **Corrections land.** A record whose contents changed replaces the stored one,
  so a provider's revised bar is not ignored.
* **Stale re-fetches do not clobber corrections.** An incoming record older than
  the stored one — by ``ingested_at`` — is refused and counted in
  ``WriteResult.ignored_stale``. Re-running yesterday's ingestion script cannot
  silently revert today's correction.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from lab.contracts import Bar, Instrument
from lab.contracts.base import LabRecord
from lab.contracts.enums import BarInterval
from lab.store.arrow import (
    BAR_SCHEMA,
    INSTRUMENT_SCHEMA,
    from_table,
    sort_key_bars,
    sort_key_instruments,
    to_table,
)

DEFAULT_DATA_DIR = Path("./data")
DATA_DIR_ENV = "LAB_DATA_DIR"


def resolve_data_root(root: Path | str | None = None) -> Path:
    """Return the data root: the argument, then ``LAB_DATA_DIR``, then ``./data``."""
    if root is not None:
        return Path(root)
    from_env = os.environ.get(DATA_DIR_ENV)
    return Path(from_env) if from_env else DEFAULT_DATA_DIR


@dataclass(frozen=True)
class WriteResult:
    """What a write actually did.

    Attributes:
        inserted: Records whose key was not previously stored.
        updated: Records that replaced a differing stored record.
        unchanged: Records identical to what was already stored.
        ignored_stale: Records refused because the stored version is newer.
        partitions_written: Files touched. Zero means the store was already
            correct and nothing was rewritten.
    """

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    ignored_stale: int = 0
    partitions_written: int = 0

    @property
    def changed(self) -> bool:
        """Whether this write altered the store."""
        return self.partitions_written > 0

    def __add__(self, other: WriteResult) -> WriteResult:
        return WriteResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            ignored_stale=self.ignored_stale + other.ignored_stale,
            partitions_written=self.partitions_written + other.partitions_written,
        )


def _ingestion_time(record: LabRecord) -> datetime:
    """The provenance timestamp a record carries, whatever it is called."""
    for field in ("ingested_at", "retrieved_at"):
        stamp = getattr(record, field, None)
        if isinstance(stamp, datetime):
            return stamp
    raise TypeError(f"{type(record).__name__} carries no ingestion timestamp")


def _merge[R: LabRecord](
    existing: dict[Any, R], incoming: Sequence[R], key: Callable[[R], Any]
) -> tuple[dict[Any, R], WriteResult]:
    """Upsert ``incoming`` into ``existing``, reporting what changed."""
    merged = dict(existing)
    inserted = updated = unchanged = ignored = 0

    for record in incoming:
        record_key = key(record)
        stored = merged.get(record_key)
        if stored is None:
            merged[record_key] = record
            inserted += 1
        elif stored == record:
            unchanged += 1
        elif _ingestion_time(record) < _ingestion_time(stored):
            ignored += 1
        else:
            merged[record_key] = record
            updated += 1

    return merged, WriteResult(
        inserted=inserted, updated=updated, unchanged=unchanged, ignored_stale=ignored
    )


class BarStore:
    """Append-and-correct store for OHLCV bars."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = resolve_data_root(root)
        self.bars_dir = self.root / "bars"

    def partition_path(self, symbol: str, interval: BarInterval) -> Path:
        """Location of one symbol's file for one interval."""
        return self.bars_dir / interval.value / symbol / "bars.parquet"

    @staticmethod
    def _key(bar: Bar) -> tuple[str, str, datetime]:
        return (bar.symbol, bar.interval.value, bar.ts_start)

    def _read_partition(self, path: Path) -> list[Bar]:
        if not path.is_file():
            return []
        return from_table(pq.read_table(path), Bar)

    def write(self, bars: Iterable[Bar]) -> WriteResult:
        """Upsert bars, one file per (interval, symbol).

        Returns:
            What changed. ``partitions_written == 0`` means every incoming bar
            was already stored and no file was touched.
        """
        by_partition: dict[tuple[str, BarInterval], list[Bar]] = {}
        for bar in bars:
            by_partition.setdefault((bar.symbol, bar.interval), []).append(bar)

        total = WriteResult()
        for (symbol, interval), incoming in by_partition.items():
            path = self.partition_path(symbol, interval)
            existing = {self._key(bar): bar for bar in self._read_partition(path)}
            merged, result = _merge(existing, incoming, self._key)

            if result.inserted or result.updated:
                path.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(to_table(sort_key_bars(merged.values()), BAR_SCHEMA), path)
                result = WriteResult(
                    inserted=result.inserted,
                    updated=result.updated,
                    unchanged=result.unchanged,
                    ignored_stale=result.ignored_stale,
                    partitions_written=1,
                )
            total += result
        return total

    def read(
        self,
        symbols: Sequence[str] | None = None,
        interval: BarInterval | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Read bars, optionally filtered.

        Args:
            symbols: Restrict to these tickers. None reads every stored symbol.
            interval: Restrict to one bar width. None reads every interval.
            start: Inclusive lower bound on ``ts_start``.
            end: Exclusive upper bound on ``ts_start``.

        Returns:
            Bars ordered by symbol then time. Empty when nothing matches.
        """
        paths = self._paths(symbols, interval)
        if not paths:
            return []

        clauses: list[str] = []
        params: list[Any] = []
        if symbols is not None:
            clauses.append(f"symbol IN ({', '.join('?' for _ in symbols)})")
            params.extend(symbols)
        if start is not None:
            clauses.append("ts_start >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts_start < ?")
            params.append(end)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM read_parquet(?)"  # noqa: S608 - clauses are built from literals
            f"{where} ORDER BY symbol, ts_start"
        )
        with duckdb.connect() as connection:
            table = connection.execute(sql, [[str(p) for p in paths], *params]).to_arrow_table()
        return from_table(table, Bar)

    def _paths(self, symbols: Sequence[str] | None, interval: BarInterval | None) -> list[Path]:
        """Existing partition files matching the requested symbols and interval."""
        if not self.bars_dir.is_dir():
            return []
        intervals = [interval] if interval is not None else list(BarInterval)
        if symbols is not None:
            candidates = [
                self.partition_path(symbol, one) for one in intervals for symbol in symbols
            ]
            return [path for path in candidates if path.is_file()]
        return sorted(
            path for one in intervals for path in self.bars_dir.glob(f"{one.value}/*/bars.parquet")
        )

    def symbols(self, interval: BarInterval | None = None) -> list[str]:
        """Every symbol with stored bars, sorted."""
        return sorted({path.parent.name for path in self._paths(None, interval)})


class InstrumentStore:
    """Append-and-correct store for instrument reference data."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = resolve_data_root(root)
        self.path = self.root / "instruments" / "instruments.parquet"

    @staticmethod
    def _key(instrument: Instrument) -> str:
        return instrument.symbol

    def write(self, instruments: Iterable[Instrument]) -> WriteResult:
        """Upsert instruments into the single reference file."""
        incoming = list(instruments)
        if not incoming:
            return WriteResult()

        existing = {self._key(one): one for one in self.read()}
        merged, result = _merge(existing, incoming, self._key)

        if result.inserted or result.updated:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                to_table(sort_key_instruments(merged.values()), INSTRUMENT_SCHEMA), self.path
            )
            return WriteResult(
                inserted=result.inserted,
                updated=result.updated,
                unchanged=result.unchanged,
                ignored_stale=result.ignored_stale,
                partitions_written=1,
            )
        return result

    def read(self, symbols: Sequence[str] | None = None) -> list[Instrument]:
        """Read instruments, optionally restricted to specific tickers."""
        if not self.path.is_file():
            return []
        sql = "SELECT * FROM read_parquet(?)"
        params: list[Any] = [str(self.path)]
        if symbols is not None:
            sql += f" WHERE symbol IN ({', '.join('?' for _ in symbols)})"
            params.extend(symbols)
        sql += " ORDER BY symbol"
        with duckdb.connect() as connection:
            table = connection.execute(sql, params).to_arrow_table()
        return from_table(table, Instrument)


__all__ = [
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR",
    "BarStore",
    "InstrumentStore",
    "WriteResult",
    "resolve_data_root",
]
