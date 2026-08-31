"""Costs must be charged, and must be pessimistic by default."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from lab.costs import CONSERVATIVE_V1, FRICTIONLESS, CostModel


def test_a_free_cost_model_is_rejected() -> None:
    """Zero spread and zero slippage produces flattering results by construction."""
    with pytest.raises(ValidationError, match="flattering"):
        CostModel(
            model_id="free",
            half_spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            commission_per_share=Decimal("0"),
            min_commission_per_order=Decimal("0"),
        )


def test_the_default_charges_both_spread_and_slippage() -> None:
    assert CONSERVATIVE_V1.half_spread_bps > 0
    assert CONSERVATIVE_V1.slippage_bps > 0
    assert CONSERVATIVE_V1.bps_per_side == Decimal("5")


def test_the_default_charges_commission_despite_a_free_broker() -> None:
    """Alpaca charges nothing on equities; turnover still must not look free."""
    assert CONSERVATIVE_V1.commission_per_share > 0


def test_trading_nothing_costs_nothing() -> None:
    assert CONSERVATIVE_V1.order_cost(Decimal("0"), Decimal("0")) == 0
    assert CONSERVATIVE_V1.rebalance_cost(Decimal("0"), Decimal("100000")) == 0
    assert CONSERVATIVE_V1.rebalance_cost(Decimal("1"), Decimal("0")) == 0


def test_cost_scales_with_notional() -> None:
    small = CONSERVATIVE_V1.rebalance_cost(Decimal("0.1"), Decimal("100000"))
    large = CONSERVATIVE_V1.rebalance_cost(Decimal("1.0"), Decimal("100000"))
    assert large == pytest.approx(float(small) * 10)


def test_both_sides_of_a_switch_are_paid_for() -> None:
    """Selling one name to buy another is a turnover of 2, not 1."""
    one_side = CONSERVATIVE_V1.cost_fraction(Decimal("1"))
    both = CONSERVATIVE_V1.cost_fraction(Decimal("2"))
    assert both == one_side * 2


def test_cost_fraction_matches_the_basis_points() -> None:
    assert CONSERVATIVE_V1.cost_fraction(Decimal("1")) == Decimal("5") / Decimal("10000")


def test_commission_needs_a_price_to_infer_shares() -> None:
    without = CONSERVATIVE_V1.rebalance_cost(Decimal("1"), Decimal("100000"))
    with_price = CONSERVATIVE_V1.rebalance_cost(
        Decimal("1"), Decimal("100000"), average_price=Decimal("50")
    )
    assert with_price > without


def test_a_cheaper_share_price_means_more_shares_and_more_commission() -> None:
    expensive = CONSERVATIVE_V1.rebalance_cost(
        Decimal("1"), Decimal("100000"), average_price=Decimal("500")
    )
    cheap = CONSERVATIVE_V1.rebalance_cost(
        Decimal("1"), Decimal("100000"), average_price=Decimal("5")
    )
    assert cheap > expensive


def test_per_order_minimum_is_applied() -> None:
    model = CONSERVATIVE_V1.model_copy(update={"min_commission_per_order": Decimal("1")})
    assert model.rebalance_cost(Decimal("0.1"), Decimal("100000"), orders=10) - Decimal(
        "10"
    ) == pytest.approx(float(CONSERVATIVE_V1.rebalance_cost(Decimal("0.1"), Decimal("100000"))))


def test_order_cost_takes_the_larger_of_commission_and_minimum() -> None:
    model = CostModel(
        model_id="m",
        half_spread_bps=Decimal("0"),
        slippage_bps=Decimal("1"),
        commission_per_share=Decimal("0.01"),
        min_commission_per_order=Decimal("1"),
    )
    assert model.order_cost(Decimal("1000"), Decimal("10")) > Decimal("1")
    tiny = model.order_cost(Decimal("100"), Decimal("1"))
    assert tiny >= Decimal("1")


def test_frictionless_is_labelled_as_a_reference_not_a_setting() -> None:
    """It exists to show how much of a result costs consume, nothing else."""
    assert FRICTIONLESS.bps_per_side < CONSERVATIVE_V1.bps_per_side
    assert "reference" in FRICTIONLESS.model_id


def test_cost_model_is_frozen() -> None:
    with pytest.raises(ValidationError):
        CONSERVATIVE_V1.half_spread_bps = Decimal("0")


def test_negative_parameters_are_rejected() -> None:
    for field in ("half_spread_bps", "slippage_bps", "commission_per_share"):
        with pytest.raises(ValidationError):
            CostModel(
                **{
                    "model_id": "m",
                    "half_spread_bps": Decimal("1"),
                    "slippage_bps": Decimal("1"),
                    "commission_per_share": Decimal("0"),
                    "min_commission_per_order": Decimal("0"),
                    field: Decimal("-1"),
                }
            )


def test_higher_turnover_frequency_costs_more() -> None:
    """The drag a fast signal has to overcome, made explicit."""
    monthly = CONSERVATIVE_V1.cost_fraction(Decimal("0.4")) * 12
    daily = CONSERVATIVE_V1.cost_fraction(Decimal("0.4")) * 252
    assert daily > monthly * 20
