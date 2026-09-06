"""Dated universe membership and survivorship warning."""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

import pytest

from lab.universe.dated import SurvivorshipWarning, load_universe

TINY = Path(__file__).resolve().parent / "fixtures" / "universe_tiny.yaml"
LIQUID50 = Path(__file__).resolve().parents[1] / "configs" / "universe" / "liquid50.yaml"


def test_liquid50_has_fifty_names_and_spy() -> None:
    universe = load_universe(LIQUID50)
    assert universe.universe_id == "liquid50_v1"
    assert len(universe.instruments) == 50
    assert universe.benchmark_symbol == "SPY"
    assert universe.survivorship_flagged
    assert universe.get("GEHC").listed_on == date(2023, 1, 4)


def test_membership_changes_with_listing_and_delisting() -> None:
    universe = load_universe(TINY)
    with pytest.warns(SurvivorshipWarning, match="SURVIVORSHIP"):
        before = universe.symbols_on(date(2022, 9, 1))
    assert before == ("SPY", "AAA", "DED")
    after_delist = universe.symbols_on(date(2022, 9, 16))
    assert after_delist == ("SPY", "AAA")
    after_list = universe.symbols_on(date(2022, 10, 3))
    assert after_list == ("SPY", "AAA", "BBB")


def test_unknown_listing_date_is_excluded() -> None:
    universe = load_universe(TINY)
    spy = universe.get("SPY")
    mutated = spy.model_copy(update={"listed_on": None})
    assert not mutated.was_listed_on(date(2022, 9, 1))


def test_point_in_time_roster_does_not_warn() -> None:
    universe = load_universe(TINY)
    universe.point_in_time = True
    universe._warned = False
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        universe.members_on(date(2022, 9, 1))
    assert not [item for item in caught if issubclass(item.category, SurvivorshipWarning)]
