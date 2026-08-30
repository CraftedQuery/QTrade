"""Execution contracts: proposal, risk decision, order and fill.

This module encodes the mandate structurally rather than by convention:

* a proposal's weights are non-negative and sum to at most 1 (long or cash only);
* a risk decision cannot approve a breached limit and cannot approve anything
  while the kill switch is engaged;
* an order's account mode has exactly one legal value, ``paper``;
* an order's ``client_order_id`` is a pure function of the decision it came
  from, so replaying a decision cannot create a second broker order;
* broker paper fills and internal shadow fills are separate, append-only
  records that are never merged.

Nothing here accepts a model-generated field. The risk engine is deterministic
and no LLM output may reach it.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from lab.contracts.base import (
    Identifier,
    LabModel,
    LabRecord,
    Price,
    Quantity,
    UtcDatetime,
    Weight,
)
from lab.contracts.enums import (
    AccountMode,
    FillSource,
    OrderStatus,
    OrderType,
    RiskOutcome,
    Side,
    TimeInForce,
)


class ProposalLine(LabModel):
    """A single desired position within a proposal."""

    symbol: Identifier = Field(description="Instrument to hold.")
    target_weight: Weight = Field(description="Desired share of portfolio value, in [0, 1].")
    reference_price: Price = Field(description="Price used to translate weight into quantity.")


class Proposal(LabRecord):
    """A desired target portfolio produced by a strategy.

    Weights are bounded below at zero by :data:`~lab.contracts.base.Weight`, so a
    short position cannot be expressed. Any weight not allocated to a line is
    cash; see :attr:`cash_weight`.
    """

    proposal_id: Identifier = Field(description="Unique proposal id.")
    experiment_id: Identifier = Field(description="Experiment that produced it.")
    strategy_version: str = Field(description="Version of the strategy code.")
    as_of: UtcDatetime = Field(description="Decision time the proposal targets.")
    lines: list[ProposalLine] = Field(description="Desired positions. May be empty (all cash).")
    created_at: UtcDatetime = Field(description="Wall-clock time the proposal was written.")

    @model_validator(mode="after")
    def _check_weights(self) -> Self:
        symbols = [line.symbol for line in self.lines]
        if len(symbols) != len(set(symbols)):
            raise ValueError("each symbol may appear at most once in a proposal")
        if self.invested_weight > Decimal(1):
            raise ValueError(
                f"target weights sum to {self.invested_weight}, above 1; leverage is not permitted"
            )
        return self

    @property
    def invested_weight(self) -> Decimal:
        """Total weight allocated to positions."""
        return sum((line.target_weight for line in self.lines), start=Decimal(0))

    @property
    def cash_weight(self) -> Decimal:
        """Residual weight held as cash. Derived, never stored, so it cannot disagree."""
        return Decimal(1) - self.invested_weight


class LimitCheck(LabModel):
    """One deterministic risk limit evaluated against a proposal."""

    limit_id: Identifier = Field(description="Limit identifier, e.g. 'gross_exposure'.")
    limit_value: Decimal = Field(description="Configured threshold.")
    observed_value: Decimal = Field(description="Value measured for this proposal.")
    breached: bool = Field(description="Whether the observed value violates the limit.")


class ApprovedLine(LabModel):
    """A position the risk engine cleared for execution, in shares."""

    symbol: Identifier = Field(description="Instrument to trade.")
    side: Side = Field(description="Buy to open or add, sell to reduce or close.")
    quantity: Quantity = Field(gt=0, description="Share count. Strictly positive.")


class RiskDecision(LabRecord):
    """The deterministic risk engine's verdict on a proposal.

    ``risk_config_hash`` pins the exact limit configuration used, so a decision
    can be recomputed and compared byte for byte. There is no field through
    which a model could alter limits, sizing, or the kill switch.
    """

    decision_id: Identifier = Field(description="Unique decision id.")
    proposal_id: Identifier = Field(description="Proposal this decision judges.")
    decided_at: UtcDatetime = Field(description="When the decision was made.")
    outcome: RiskOutcome = Field(description="Approved, reduced, or rejected.")
    risk_config_hash: str = Field(min_length=8, description="Hash of the risk limits applied.")
    checks: list[LimitCheck] = Field(description="Every limit evaluated, breached or not.")
    approved_lines: list[ApprovedLine] = Field(description="Cleared trades. Empty when rejected.")
    kill_switch_engaged: bool = Field(description="Whether the kill switch was active.")
    data_staleness_seconds: Decimal = Field(
        ge=0, description="Age of the newest market data at decision time."
    )
    reason: str = Field(description="Human-readable explanation, especially when not approved.")

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.kill_switch_engaged and self.outcome is not RiskOutcome.REJECTED:
            raise ValueError("kill switch engaged: outcome must be rejected")
        if self.outcome is RiskOutcome.REJECTED and self.approved_lines:
            raise ValueError("a rejected decision must not approve any lines")
        if self.outcome is RiskOutcome.APPROVED and any(check.breached for check in self.checks):
            raise ValueError("a breached limit cannot yield an approved outcome")
        symbols = [line.symbol for line in self.approved_lines]
        if len(symbols) != len(set(symbols)):
            raise ValueError("each symbol may appear at most once in approved_lines")
        return self

    @property
    def breached_limits(self) -> list[str]:
        """Ids of every limit that was violated."""
        return [check.limit_id for check in self.checks if check.breached]


def derive_client_order_id(decision_id: str, symbol: str, side: Side) -> str:
    """Return the deterministic idempotency key for one leg of a risk decision.

    The key is a pure function of its inputs — no clock, no counter, no random
    component — so replaying the same decision produces the same key and the
    broker rejects the duplicate instead of opening a second position. Changing
    this function changes every future key, so treat it as part of the contract.
    """
    digest = hashlib.sha256(f"{decision_id}|{symbol}|{side.value}".encode()).hexdigest()
    return f"lab-{digest[:32]}"


class Order(LabRecord):
    """An order submitted to the paper broker.

    ``account_mode`` is typed as :class:`~lab.contracts.enums.AccountMode`, which
    has one member. A live order is not expressible in this system.
    """

    order_id: Identifier = Field(description="Lab-side unique order id.")
    client_order_id: Identifier = Field(
        description="Idempotency key from derive_client_order_id. Stable across replays."
    )
    decision_id: Identifier = Field(description="Risk decision that authorised this order.")
    account_mode: AccountMode = Field(
        default=AccountMode.PAPER, description="Always 'paper'. No other value exists."
    )
    symbol: Identifier = Field(description="Instrument to trade.")
    side: Side = Field(description="Buy or sell.")
    quantity: Quantity = Field(gt=0, description="Share count. Strictly positive.")
    order_type: OrderType = Field(description="Market or limit.")
    limit_price: Price | None = Field(default=None, description="Required for limit orders only.")
    time_in_force: TimeInForce = Field(default=TimeInForce.DAY, description="Order lifetime.")
    status: OrderStatus = Field(description="Current lifecycle state.")
    submitted_at: UtcDatetime = Field(description="When the order was sent.")
    broker_order_id: str | None = Field(default=None, description="Broker's id, once accepted.")

    @model_validator(mode="after")
    def _check_limit_price(self) -> Self:
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("a limit order requires a limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("a market order must not carry a limit_price")
        return self


class Fill(LabRecord):
    """An execution against an order.

    Fills are append-only. A ``broker_paper`` fill is the record of what the
    paper broker actually did; an ``internal_shadow`` fill is the lab's own,
    deliberately more pessimistic estimate for the same order. Both are kept.
    Shadow fills never overwrite broker fills, and the two are never summed.
    """

    fill_id: Identifier = Field(description="Unique fill id.")
    order_id: Identifier = Field(description="Order this fill belongs to.")
    client_order_id: Identifier = Field(description="Idempotency key of that order.")
    source: FillSource = Field(description="Broker paper fill or internal shadow fill.")
    symbol: Identifier = Field(description="Instrument traded.")
    side: Side = Field(description="Buy or sell.")
    quantity: Quantity = Field(gt=0, description="Shares filled. Strictly positive.")
    price: Price = Field(description="Execution price per share.")
    fee: Price = Field(default=Decimal(0), description="Commissions and fees charged.")
    filled_at: UtcDatetime = Field(description="When the execution occurred.")
    recorded_at: UtcDatetime = Field(description="When the lab stored the fill.")
    sequence: int = Field(ge=0, description="Monotonic index of this fill within its order.")

    @property
    def notional(self) -> Decimal:
        """Gross traded value, before fees."""
        return self.quantity * self.price


__all__ = [
    "ApprovedLine",
    "Fill",
    "LimitCheck",
    "Order",
    "Proposal",
    "ProposalLine",
    "RiskDecision",
    "derive_client_order_id",
]
