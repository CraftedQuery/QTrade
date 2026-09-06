"""Dated universe: membership answered as of a calendar day."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from lab.contracts import Instrument
from lab.contracts.enums import AssetClass

SURVIVORSHIP_MESSAGE = (
    "SURVIVORSHIP: universe {universe_id} is not a point-in-time membership tape "
    "(source={source}). listed_on/delisted_on are applied, but the roster itself "
    "was chosen from names that are liquid today. yfinance-style current "
    "membership is not point-in-time. Do not treat this as a PIT universe."
)


class SurvivorshipWarning(UserWarning):
    """Raised when membership is queried on a non-point-in-time roster."""


class DatedUniverse:
    """A roster of instruments with listing windows.

    ``members_on`` is the only supported way to ask who was eligible on a
    past day. A roster that is not a genuine point-in-time membership tape
    always warns — applying listing dates to a current liquid list is still
    survivorship-biased.
    """

    def __init__(
        self,
        universe_id: str,
        instruments: Sequence[Instrument],
        *,
        source: str,
        point_in_time: bool,
        benchmark_symbol: str = "SPY",
        max_names: int | None = None,
    ) -> None:
        if not universe_id:
            raise ValueError("universe_id is required")
        if not instruments:
            raise ValueError("universe must contain at least one instrument")
        seen: set[str] = set()
        ordered: list[Instrument] = []
        for instrument in instruments:
            if instrument.symbol in seen:
                raise ValueError(f"duplicate symbol in universe: {instrument.symbol}")
            seen.add(instrument.symbol)
            ordered.append(instrument)
        if max_names is not None and len(ordered) > max_names:
            raise ValueError(
                f"universe {universe_id} has {len(ordered)} names; max_names={max_names}"
            )
        if benchmark_symbol not in seen:
            raise ValueError(f"benchmark {benchmark_symbol} is not in universe {universe_id}")
        self.universe_id = universe_id
        self.source = source
        self.point_in_time = point_in_time
        self.benchmark_symbol = benchmark_symbol
        self.max_names = max_names
        self.instruments = tuple(ordered)
        self._warned = False

    @property
    def survivorship_flagged(self) -> bool:
        """Whether this roster must be treated as survivorship-biased."""
        return not self.point_in_time

    def get(self, symbol: str) -> Instrument:
        """Return the instrument for ``symbol``.

        Raises:
            KeyError: If the symbol is not in the roster.
        """
        for instrument in self.instruments:
            if instrument.symbol == symbol:
                return instrument
        raise KeyError(symbol)

    def members_on(self, day: date) -> tuple[Instrument, ...]:
        """Instruments listed on ``day``, in roster order.

        Warns when the roster is not a point-in-time membership tape.
        """
        if self.survivorship_flagged and not self._warned:
            warnings.warn(
                SURVIVORSHIP_MESSAGE.format(universe_id=self.universe_id, source=self.source),
                SurvivorshipWarning,
                stacklevel=2,
            )
            self._warned = True
        return tuple(item for item in self.instruments if item.was_listed_on(day))

    def symbols_on(self, day: date) -> tuple[str, ...]:
        """Tickers listed on ``day``."""
        return tuple(item.symbol for item in self.members_on(day))


def load_universe(path: Path) -> DatedUniverse:
    """Load a dated universe from a YAML file."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or "universe" not in loaded:
        raise ValueError(f"{path}: expected a top-level 'universe' mapping")
    block = loaded["universe"]
    if not isinstance(block, dict):
        raise ValueError(f"{path}: 'universe' must be a mapping")
    retrieved_at = datetime(2026, 9, 6, tzinfo=UTC)
    source = str(block.get("source") or "committed-fixture")
    instruments = [
        _instrument_from_row(row, source=source, retrieved_at=retrieved_at)
        for row in block.get("instruments") or []
    ]
    return DatedUniverse(
        str(block["id"]),
        instruments,
        source=source,
        point_in_time=bool(block.get("point_in_time", False)),
        benchmark_symbol=str(block.get("benchmark_symbol") or "SPY"),
        max_names=block.get("max_names"),
    )


def _instrument_from_row(row: Any, *, source: str, retrieved_at: datetime) -> Instrument:
    if not isinstance(row, dict):
        raise ValueError("instrument row must be a mapping")
    listed = row.get("listed_on")
    delisted = row.get("delisted_on")
    return Instrument(
        symbol=str(row["symbol"]),
        name=row.get("name"),
        asset_class=AssetClass(row["asset_class"]),
        exchange=str(row["exchange"]),
        listed_on=_as_date(listed) if listed is not None else None,
        delisted_on=_as_date(delisted) if delisted is not None else None,
        source=source,
        retrieved_at=retrieved_at,
    )


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"cannot parse date from {value!r}")


__all__ = ["DatedUniverse", "SurvivorshipWarning", "load_universe"]
