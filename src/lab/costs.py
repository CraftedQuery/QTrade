"""Transaction costs. Deliberately pessimistic.

## Why a cost model is an integrity control, not an accounting detail

A gross backtest is the most flattering number a research lab can produce, and
the easiest to produce by accident. Many signals that look strong gross are
consumed entirely by the cost of trading them — the faster the signal, the more
certain that is. A lab without costs will eventually report an edge that does not
survive contact with a broker.

So the default model is **conservative on purpose**. Alpaca charges no commission
on U.S. equities, and modelling zero cost would be defensible on paper and wrong
in spirit: it would hide the spread and the impact of trading, which are real
whatever the commission schedule says. If a signal only works under optimistic
costs, that is a finding about the signal.

## What is charged

For each rebalance, on the notional actually traded:

* **half spread** — crossing the bid-ask costs roughly half the quoted spread
  per side;
* **slippage** — an allowance for moving the price, above the spread;
* **commission** — per share, with a per-order minimum.

Costs are charged on *turnover*, the total absolute weight change across the
book, so both the buys and the sells of a rebalance are paid for.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from lab.contracts.base import Identifier, LabModel, Price

BPS = Decimal("10000")


class CostModel(LabModel):
    """A transaction cost model.

    Attributes:
        model_id: Identifier stored on every experiment that used this model, so
            a result can be traced back to the costs it was charged.
        half_spread_bps: Basis points paid crossing the spread, per side.
        slippage_bps: Basis points of price impact, per side, above the spread.
        commission_per_share: Commission charged per share traded.
        min_commission_per_order: Floor applied to each order's commission.
    """

    model_id: Identifier = Field(description="Cost model identifier.")
    half_spread_bps: Decimal = Field(ge=0, description="Basis points per side for the spread.")
    slippage_bps: Decimal = Field(ge=0, description="Basis points per side of price impact.")
    commission_per_share: Price = Field(description="Commission per share traded.")
    min_commission_per_order: Price = Field(description="Minimum commission per order.")

    @model_validator(mode="after")
    def _check_not_free(self) -> Self:
        if self.half_spread_bps == 0 and self.slippage_bps == 0:
            raise ValueError(
                "a cost model with no spread and no slippage charges nothing for "
                "trading, which produces flattering results; set a positive value "
                "or state explicitly why zero is correct"
            )
        return self

    @property
    def bps_per_side(self) -> Decimal:
        """Total basis points charged on each side of a trade."""
        return self.half_spread_bps + self.slippage_bps

    def order_cost(self, notional: Decimal, shares: Decimal) -> Decimal:
        """Cost of one order.

        Args:
            notional: Absolute value traded, in currency.
            shares: Absolute share count traded.

        Returns:
            Total cost: spread and slippage on the notional, plus commission.
        """
        if notional <= 0 or shares <= 0:
            return Decimal(0)
        spread = notional * self.bps_per_side / BPS
        commission = max(shares * self.commission_per_share, self.min_commission_per_order)
        return spread + commission

    def rebalance_cost(
        self,
        turnover: Decimal,
        portfolio_value: Decimal,
        orders: int = 0,
        average_price: Decimal | None = None,
    ) -> Decimal:
        """Cost of one rebalance, charged on the notional actually traded.

        Args:
            turnover: Total absolute weight change across the book. A full
                switch from one name to another is a turnover of 2 — one weight
                sold, one bought — and both sides are paid for.
            portfolio_value: Book value the weights apply to.
            orders: Number of orders, for the per-order commission minimum.
            average_price: Average share price, used to infer the share count.
                When omitted, only the basis-point charge applies.

        Returns:
            Total cost in currency.
        """
        if turnover <= 0 or portfolio_value <= 0:
            return Decimal(0)
        notional = turnover * portfolio_value
        cost = notional * self.bps_per_side / BPS
        if average_price is not None and average_price > 0:
            shares = notional / average_price
            cost += shares * self.commission_per_share
        if orders > 0:
            cost += orders * self.min_commission_per_order
        return cost

    def cost_fraction(self, turnover: Decimal) -> Decimal:
        """Basis-point cost of a rebalance as a fraction of portfolio value.

        Ignores commission, which needs a share count. Useful for comparing the
        drag of different rebalance frequencies.
        """
        return turnover * self.bps_per_side / BPS


CONSERVATIVE_V1 = CostModel(
    model_id="conservative_v1",
    # Liquid U.S. large caps quote inside a basis point or two; 3 is pessimistic
    # on purpose, and pessimistic is the correct direction to be wrong in.
    half_spread_bps=Decimal("3"),
    slippage_bps=Decimal("2"),
    # Alpaca charges no commission on equities. A small per-share charge is kept
    # so that a high-turnover strategy cannot look free.
    commission_per_share=Decimal("0.005"),
    min_commission_per_order=Decimal("0"),
)
"""The Release 0.2 default: 5 basis points per side, plus a small per-share charge."""

FRICTIONLESS = CostModel(
    model_id="frictionless_reference",
    half_spread_bps=Decimal("0.0001"),
    slippage_bps=Decimal("0"),
    commission_per_share=Decimal("0"),
    min_commission_per_order=Decimal("0"),
)
"""A near-zero model, for showing how much of a result costs consume.

Not a research setting. Reporting a number produced under this model without the
conservative number beside it is exactly the flattery the cost model exists to
prevent.
"""


__all__ = ["CONSERVATIVE_V1", "FRICTIONLESS", "CostModel"]
