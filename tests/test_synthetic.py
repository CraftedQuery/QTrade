"""The synthetic generator must be deterministic and contract-valid.

Everything downstream is tested against this fixture, so a flaw here would
quietly weaken every integrity test in the release.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lab.contracts import Bar
from lab.contracts.enums import BarInterval
from lab.store import BarStore
from tests.synthetic import (
    MarketSpec,
    SymbolSpec,
    generate_bars,
    generate_instruments,
    session_window,
    simple_market,
    trading_sessions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def digest(bars: list[Bar]) -> str:
    """A stable fingerprint of a generated series."""
    payload = "|".join(
        f"{bar.symbol}{bar.ts_start.isoformat()}{bar.open}{bar.high}{bar.low}{bar.close}{bar.volume}"
        for bar in bars
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# --- Determinism ------------------------------------------------------------


def test_same_spec_yields_identical_bars() -> None:
    assert generate_bars(simple_market()) == generate_bars(simple_market())


def test_determinism_survives_a_new_process() -> None:
    """Python randomises string hashing per process; seeding must not rely on it."""
    script = (
        "from tests.synthetic import simple_market, generate_bars;"
        "from tests.test_synthetic import digest;"
        "print(digest(generate_bars(simple_market())))"
    )
    runs = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert len(runs) == 1, f"generator is not deterministic across processes: {runs}"


def test_different_seeds_yield_different_data() -> None:
    assert digest(generate_bars(simple_market(seed=1))) != digest(
        generate_bars(simple_market(seed=2))
    )


def test_adding_a_symbol_does_not_disturb_the_others() -> None:
    """Per-symbol seeding: a fixture can grow without invalidating old expectations."""
    two = generate_bars(simple_market(symbols=("AAA", "BBB")))
    three = generate_bars(simple_market(symbols=("AAA", "BBB", "CCC")))
    assert [bar for bar in three if bar.symbol != "CCC"] == two


def test_generated_bars_are_stored_byte_identically(tmp_path: Path) -> None:
    """Determinism has to survive the store, not just the generator."""
    bars = generate_bars(simple_market())
    first, second = BarStore(tmp_path / "a"), BarStore(tmp_path / "b")
    first.write(bars)
    second.write(generate_bars(simple_market()))

    path = ("1day", "AAA", "bars.parquet")
    assert (first.root / "bars").joinpath(*path).read_bytes() == (second.root / "bars").joinpath(
        *path
    ).read_bytes()


# --- Contract validity ------------------------------------------------------


def test_every_bar_satisfies_the_ohlc_invariants() -> None:
    """Quantisation rounds high up and low down, so rounding cannot invert them."""
    for bar in generate_bars(simple_market()):
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
        assert bar.high >= bar.low
        assert bar.volume > 0
        assert bar.ts_end > bar.ts_start


def test_prices_stay_positive_under_a_long_drawdown() -> None:
    """A steep negative drift must not produce a zero or negative price."""
    spec = MarketSpec(
        symbols=(SymbolSpec("CRASH", annual_drift=-3.0, annual_vol=1.5),),
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
    )
    assert all(bar.low > 0 for bar in generate_bars(spec))


def test_information_time_is_the_session_close() -> None:
    bar = generate_bars(simple_market())[0]
    _, closed = session_window(bar.ts_start.date())
    assert bar.information_time == closed
    assert bar.information_time > bar.ts_start


# --- Sessions ---------------------------------------------------------------


def test_sessions_are_weekdays_only() -> None:
    days = trading_sessions(date(2024, 1, 1), date(2024, 1, 31))
    assert all(day.weekday() < 5 for day in days)
    assert date(2024, 1, 6) not in days  # a Saturday


def test_sessions_honour_skips() -> None:
    skipped = date(2024, 1, 10)
    assert skipped not in trading_sessions(date(2024, 1, 1), date(2024, 1, 31), skip=[skipped])


def test_bars_land_only_on_sessions() -> None:
    dates = {bar.ts_start.date() for bar in generate_bars(simple_market())}
    assert dates == set(trading_sessions(date(2024, 1, 1), date(2024, 6, 28)))


# --- Edge cases the integrity tests need ------------------------------------


def test_a_symbol_can_delist_mid_range() -> None:
    """Needed for survivorship tests in task 3."""
    delist = date(2024, 3, 15)
    spec = MarketSpec(
        symbols=(SymbolSpec("GONE", delist_on=delist), SymbolSpec("ALIVE")),
        start=date(2024, 1, 1),
        end=date(2024, 6, 28),
    )
    bars = generate_bars(spec)
    gone = [bar for bar in bars if bar.symbol == "GONE"]
    assert max(bar.ts_start.date() for bar in gone) <= delist
    assert max(bar.ts_start.date() for bar in bars if bar.symbol == "ALIVE") > delist


def test_a_symbol_can_list_partway_through() -> None:
    listed = date(2024, 3, 1)
    spec = MarketSpec(
        symbols=(SymbolSpec("NEW", listed_on=listed),),
        start=date(2024, 1, 1),
        end=date(2024, 6, 28),
    )
    assert min(bar.ts_start.date() for bar in generate_bars(spec)) >= listed


def test_a_series_can_contain_a_gap() -> None:
    hole = tuple(date(2024, 2, 5) + timedelta(days=offset) for offset in range(5))
    spec = MarketSpec(
        symbols=(SymbolSpec("GAPPY", skip_sessions=hole),),
        start=date(2024, 1, 1),
        end=date(2024, 6, 28),
    )
    present = {bar.ts_start.date() for bar in generate_bars(spec)}
    assert present.isdisjoint(hole)
    assert present


def test_a_split_produces_a_visible_raw_discontinuity() -> None:
    """So that mixing adjusted and raw series is detectable downstream."""
    split_on = date(2024, 4, 1)
    spec = MarketSpec(
        symbols=(SymbolSpec("SPLIT", split_on=split_on, split_ratio=Decimal("2")),),
        start=date(2024, 1, 1),
        end=date(2024, 6, 28),
    )
    bars = generate_bars(spec)
    before = [b.close for b in bars if b.ts_start.date() < split_on][-1]
    after = next(b.close for b in bars if b.ts_start.date() >= split_on)
    assert after < before / Decimal("1.5")


def test_bars_can_be_generated_past_a_decision_time() -> None:
    """The planted future that task 5's look-ahead test must prove is refused."""
    bars = generate_bars(simple_market())
    cutoff = bars[len(bars) // 2].ts_start
    assert [bar for bar in bars if bar.ts_start > cutoff]


# --- Instruments ------------------------------------------------------------


def test_instruments_match_the_symbols() -> None:
    spec = simple_market()
    instruments = generate_instruments(spec)
    assert [one.symbol for one in instruments] == ["AAA", "BBB", "CCC"]
    assert all(one.listed_on == spec.start for one in instruments)


def test_a_delisted_instrument_records_its_last_day() -> None:
    delist = date(2024, 3, 15)
    spec = MarketSpec(
        symbols=(SymbolSpec("GONE", delist_on=delist),),
        start=date(2024, 1, 1),
        end=date(2024, 6, 28),
    )
    instrument = generate_instruments(spec)[0]
    assert instrument.delisted_on == delist
    assert not instrument.is_tradable
    assert instrument.was_listed_on(date(2024, 2, 1))
    assert not instrument.was_listed_on(date(2024, 4, 1))


# --- It must never become a data source -------------------------------------


def test_the_lab_package_never_imports_the_generator() -> None:
    """Synthetic prices must not be able to reach a real experiment.

    Checks the actual import statements rather than the file text: lab code is
    free to *mention* synthetic data in a docstring — the runner's refusal
    message does exactly that — but must never import the generator.
    """
    offenders: list[str] = []
    for path in (REPO_ROOT / "src" / "lab").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            if any(name.split(".")[0] in {"tests", "synthetic"} for name in imported):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"lab code imports test fixtures: {offenders}"


def test_the_generator_is_not_shipped_in_the_package() -> None:
    assert not (REPO_ROOT / "src" / "lab" / "synthetic.py").exists()


@pytest.mark.parametrize("interval", [BarInterval.DAY_1, BarInterval.HOUR_1])
def test_interval_is_carried_through(interval: BarInterval) -> None:
    spec = MarketSpec(
        symbols=(SymbolSpec("AAA"),),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        interval=interval,
    )
    assert {bar.interval for bar in generate_bars(spec)} == {interval}
