"""Store guarantees: exact decimals, idempotent writes, surviving provenance."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from lab.contracts import Bar
from lab.contracts.enums import BarInterval, PriceAdjustment
from lab.store import BarStore, InstrumentStore
from lab.store.parquet import DATA_DIR_ENV, DEFAULT_DATA_DIR, resolve_data_root
from tests.factories import NOW, make_bar, make_instrument


@pytest.fixture
def bar_store(tmp_path: Path) -> BarStore:
    return BarStore(tmp_path)


@pytest.fixture
def instrument_store(tmp_path: Path) -> InstrumentStore:
    return InstrumentStore(tmp_path)


def flat(price: Decimal, **overrides: object) -> Bar:
    """A bar that traded at one price all session, so OHLC stays coherent."""
    return make_bar(open=price, high=price, low=price, close=price, **overrides)


def series(symbol: str = "SPY", days: int = 5, **overrides: object) -> list[Bar]:
    """A run of consecutive daily bars."""
    return [
        make_bar(
            symbol=symbol,
            ts_start=NOW + timedelta(days=offset),
            ts_end=NOW + timedelta(days=offset + 1),
            ingested_at=NOW + timedelta(days=offset + 1),
            **overrides,
        )
        for offset in range(days)
    ]


# --- Round trip -------------------------------------------------------------


def test_bars_round_trip_unchanged(bar_store: BarStore) -> None:
    written = series(days=3)
    bar_store.write(written)
    assert bar_store.read() == written


def test_decimal_prices_survive_exactly(bar_store: BarStore) -> None:
    """The trap this store exists to avoid: a price arriving back as a float."""
    exact = Decimal("123.456789012")
    bar_store.write([flat(exact)])
    read_back = bar_store.read()[0]

    assert read_back.close == exact
    assert isinstance(read_back.close, Decimal)
    # Numeric equality is not enough on its own: assert no float ever appeared.
    assert read_back.close - exact == Decimal(0)


def test_tiny_and_large_decimals_survive(bar_store: BarStore) -> None:
    tiny, large = Decimal("0.000000000001"), Decimal("99999999.999999999999")
    bar_store.write([make_bar(low=tiny, open=tiny, close=large, high=large, volume=large)])
    read_back = bar_store.read()[0]
    assert read_back.low == tiny
    assert read_back.close == large


def test_excess_precision_raises_rather_than_truncating(bar_store: BarStore) -> None:
    """A price the store cannot hold exactly is a bug to surface, not to round."""
    with pytest.raises(pa.ArrowInvalid):
        bar_store.write([flat(Decimal("1.0000000000001"))])


def test_timestamps_keep_timezone_and_microseconds(bar_store: BarStore) -> None:
    precise = datetime(2026, 3, 2, 14, 30, 0, 123456, tzinfo=UTC)
    bar_store.write([make_bar(ts_start=precise, ts_end=precise + timedelta(days=1))])
    read_back = bar_store.read()[0]
    assert read_back.ts_start == precise
    assert read_back.ts_start.microsecond == 123456
    assert read_back.ts_start.tzinfo is not None


def test_provenance_survives(bar_store: BarStore) -> None:
    bar_store.write([make_bar(source="alpaca", ingested_at=NOW)])
    read_back = bar_store.read()[0]
    assert read_back.source == "alpaca"
    assert read_back.ingested_at == NOW


def test_optional_fields_round_trip_as_none(bar_store: BarStore) -> None:
    bar_store.write([make_bar(vwap=None, trade_count=None)])
    read_back = bar_store.read()[0]
    assert read_back.vwap is None
    assert read_back.trade_count is None


def test_enums_round_trip_as_enums(bar_store: BarStore) -> None:
    bar_store.write([make_bar(interval=BarInterval.MIN_5, adjustment=PriceAdjustment.RAW)])
    read_back = bar_store.read()[0]
    assert read_back.interval is BarInterval.MIN_5
    assert read_back.adjustment is PriceAdjustment.RAW


# --- Idempotency ------------------------------------------------------------


def test_rewriting_identical_bars_touches_nothing(bar_store: BarStore) -> None:
    bars = series(days=4)
    first = bar_store.write(bars)
    assert first.inserted == 4
    assert first.partitions_written == 1

    snapshot = bar_store.read()
    second = bar_store.write(bars)

    assert second.unchanged == 4
    assert second.inserted == 0
    assert second.updated == 0
    assert second.partitions_written == 0
    assert not second.changed
    assert bar_store.read() == snapshot


def test_rewriting_leaves_the_file_byte_identical(bar_store: BarStore) -> None:
    bars = series(days=3)
    bar_store.write(bars)
    path = bar_store.partition_path("SPY", BarInterval.DAY_1)
    before = path.read_bytes()

    bar_store.write(bars)
    assert path.read_bytes() == before


def test_overlapping_writes_do_not_duplicate(bar_store: BarStore) -> None:
    bar_store.write(series(days=5))
    bar_store.write(series(days=8))
    stored = bar_store.read()
    assert len(stored) == 8
    assert len({bar.ts_start for bar in stored}) == 8


def test_write_order_does_not_affect_result(bar_store: BarStore, tmp_path: Path) -> None:
    """Deterministic output: shuffled input must produce the same file."""
    bars = series(days=5)
    bar_store.write(bars)
    other = BarStore(tmp_path / "other")
    other.write(list(reversed(bars)))

    assert bar_store.read() == other.read()
    assert (
        bar_store.partition_path("SPY", BarInterval.DAY_1).read_bytes()
        == other.partition_path("SPY", BarInterval.DAY_1).read_bytes()
    )


# --- Corrections ------------------------------------------------------------


def test_a_correction_replaces_the_stored_bar(bar_store: BarStore) -> None:
    bar_store.write([flat(Decimal("100"), ingested_at=NOW)])
    result = bar_store.write([flat(Decimal("101"), ingested_at=NOW + timedelta(hours=1))])

    assert result.updated == 1
    assert result.inserted == 0
    assert bar_store.read()[0].close == Decimal("101")


def test_a_stale_refetch_cannot_revert_a_correction(bar_store: BarStore) -> None:
    """Re-running an old ingestion script must not undo today's correction."""
    bar_store.write([flat(Decimal("101"), ingested_at=NOW + timedelta(hours=1))])
    result = bar_store.write([flat(Decimal("100"), ingested_at=NOW)])

    assert result.ignored_stale == 1
    assert result.updated == 0
    assert result.partitions_written == 0
    assert bar_store.read()[0].close == Decimal("101")


# --- Reading ----------------------------------------------------------------


def test_empty_store_reads_empty(bar_store: BarStore) -> None:
    assert bar_store.read() == []
    assert bar_store.read(symbols=["SPY"]) == []
    assert bar_store.symbols() == []


def test_writing_nothing_is_a_no_op(bar_store: BarStore) -> None:
    result = bar_store.write([])
    assert result.partitions_written == 0
    assert bar_store.read() == []


def test_filter_by_symbol(bar_store: BarStore) -> None:
    bar_store.write(series("SPY", 3) + series("QQQ", 3))
    assert {bar.symbol for bar in bar_store.read(symbols=["SPY"])} == {"SPY"}
    assert len(bar_store.read()) == 6


def test_filter_by_date_range_is_half_open(bar_store: BarStore) -> None:
    bar_store.write(series(days=5))
    window = bar_store.read(start=NOW + timedelta(days=1), end=NOW + timedelta(days=3))
    assert [bar.ts_start for bar in window] == [NOW + timedelta(days=1), NOW + timedelta(days=2)]


def test_filter_by_interval(bar_store: BarStore) -> None:
    bar_store.write(series(days=2))
    bar_store.write(series(days=2, interval=BarInterval.MIN_5))
    assert len(bar_store.read(interval=BarInterval.DAY_1)) == 2
    assert len(bar_store.read()) == 4


def test_unknown_symbol_reads_empty_without_error(bar_store: BarStore) -> None:
    bar_store.write(series(days=2))
    assert bar_store.read(symbols=["NOPE"]) == []
    assert len(bar_store.read(symbols=["SPY", "NOPE"])) == 2


def test_results_are_ordered_by_symbol_then_time(bar_store: BarStore) -> None:
    bar_store.write(series("QQQ", 3) + series("SPY", 3))
    stored = bar_store.read()
    assert [(bar.symbol, bar.ts_start) for bar in stored] == sorted(
        (bar.symbol, bar.ts_start) for bar in stored
    )


def test_symbols_lists_what_is_stored(bar_store: BarStore) -> None:
    bar_store.write(series("SPY", 2) + series("QQQ", 2))
    assert bar_store.symbols() == ["QQQ", "SPY"]


def test_partitions_are_laid_out_by_interval_and_symbol(bar_store: BarStore) -> None:
    bar_store.write(series(days=2))
    path = bar_store.partition_path("SPY", BarInterval.DAY_1)
    assert path.is_file()
    assert path.parent.name == "SPY"
    assert path.parent.parent.name == "1day"
    # Plain directory names: Hive-style "key=value" would make pyarrow and DuckDB
    # synthesise partition columns that collide with the real ones in the file.
    assert "=" not in str(path.relative_to(bar_store.root))


# --- Instruments ------------------------------------------------------------


def test_instruments_round_trip(instrument_store: InstrumentStore) -> None:
    written = [make_instrument(), make_instrument(symbol="QQQ", name="Invesco QQQ Trust")]
    instrument_store.write(written)
    assert instrument_store.read() == sorted(written, key=lambda i: i.symbol)


def test_instrument_dates_round_trip(instrument_store: InstrumentStore) -> None:
    instrument_store.write(
        [make_instrument(symbol="LEH", listed_on=date(1994, 1, 1), delisted_on=date(2008, 9, 16))]
    )
    stored = instrument_store.read()[0]
    assert stored.listed_on == date(1994, 1, 1)
    assert stored.delisted_on == date(2008, 9, 16)
    assert not stored.was_listed_on(date(2009, 1, 1))


def test_instrument_null_dates_round_trip(instrument_store: InstrumentStore) -> None:
    instrument_store.write([make_instrument(listed_on=None, delisted_on=None, name=None)])
    stored = instrument_store.read()[0]
    assert stored.listed_on is None
    assert stored.name is None


def test_instrument_rewrite_is_idempotent(instrument_store: InstrumentStore) -> None:
    instruments = [make_instrument()]
    instrument_store.write(instruments)
    snapshot = instrument_store.read()

    result = instrument_store.write(instruments)
    assert result.unchanged == 1
    assert result.partitions_written == 0
    assert instrument_store.read() == snapshot


def test_instrument_filter_by_symbol(instrument_store: InstrumentStore) -> None:
    instrument_store.write([make_instrument(), make_instrument(symbol="QQQ")])
    assert [one.symbol for one in instrument_store.read(symbols=["QQQ"])] == ["QQQ"]


def test_empty_instrument_store_reads_empty(instrument_store: InstrumentStore) -> None:
    assert instrument_store.read() == []


# --- Data root resolution ---------------------------------------------------


def test_data_root_precedence(tmp_path: Path) -> None:
    assert resolve_data_root(tmp_path) == tmp_path
    assert resolve_data_root(None) in (DEFAULT_DATA_DIR, Path(DEFAULT_DATA_DIR))


def test_data_root_reads_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert resolve_data_root() == tmp_path
    monkeypatch.delenv(DATA_DIR_ENV)
    assert resolve_data_root() == DEFAULT_DATA_DIR


def test_explicit_root_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "env"))
    assert BarStore(tmp_path / "explicit").root == tmp_path / "explicit"
