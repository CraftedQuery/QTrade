"""Sleeve weights stay long-or-cash and the fixture generator is deterministic."""

from __future__ import annotations

from datetime import date

from lab.contracts import FeatureSnapshot
from lab.data.generate import generate_daily_bars
from lab.experiments.baselines import weights_cash, weights_equal, weights_momentum, weights_spy
from lab.features.momentum import FEATURE_SET, FEATURE_SET_VERSION
from tests.factories import NOW, make_feature_snapshot


def test_cash_is_empty_weights() -> None:
    assert weights_cash(("SPY", "AAA")) == {}


def test_spy_goes_to_cash_when_benchmark_is_not_a_member() -> None:
    assert weights_spy(("AAA",), "SPY") == {}
    assert weights_spy(("AAA", "SPY"), "SPY") == {"SPY": 1.0}


def test_equal_weight_is_long_only_and_sums_to_one() -> None:
    weights = weights_equal(("AAA", "BBB", "CCC"))
    assert all(value > 0 for value in weights.values())
    assert sum(weights.values()) == 1.0


def test_momentum_takes_top_half_and_never_shorts() -> None:
    def snap(symbol: str, value: float) -> FeatureSnapshot:
        return make_feature_snapshot(
            snapshot_id=symbol,
            symbol=symbol,
            values={"mom_21d": value},
            as_of=NOW,
            information_cutoff=NOW,
            computed_at=NOW,
            feature_set=FEATURE_SET,
            feature_set_version=FEATURE_SET_VERSION,
        )

    snapshots = {
        "AAA": snap("AAA", 0.10),
        "BBB": snap("BBB", 0.02),
        "CCC": snap("CCC", -0.05),
        "DDD": snap("DDD", 0.20),
    }
    weights = weights_momentum(snapshots, ("AAA", "BBB", "CCC", "DDD"), 21)
    assert set(weights) == {"DDD", "AAA"}
    assert all(value > 0 for value in weights.values())
    assert sum(weights.values()) == 1.0


def test_fixture_bars_are_deterministic_and_carry_provenance() -> None:
    first = generate_daily_bars(["SPY", "AAA"], date(2022, 8, 1), date(2022, 8, 10), seed=20260201)
    second = generate_daily_bars(["SPY", "AAA"], date(2022, 8, 1), date(2022, 8, 10), seed=20260201)
    assert [bar.close for bar in first] == [bar.close for bar in second]
    assert all(bar.source == "committed-fixture" for bar in first)
    assert all(bar.information_time == bar.ts_end for bar in first)
    other = generate_daily_bars(["SPY", "AAA"], date(2022, 8, 1), date(2022, 8, 10), seed=1)
    assert [bar.close for bar in other] != [bar.close for bar in first]
