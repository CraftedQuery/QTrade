"""Deterministic risk engine. No model output may reach this module."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from lab.config import RiskLimits
from lab.contracts import ApprovedLine, LimitCheck, Proposal, RiskDecision, derive_decision_id
from lab.contracts.enums import RiskOutcome, Side
from lab.execution.book import BookState


def _seconds_stale(decided_at: datetime, data_as_of: datetime) -> Decimal:
    delta = decided_at - data_as_of
    seconds = Decimal(str(delta.total_seconds()))
    return seconds if seconds > 0 else Decimal(0)


def _clip_weights(
    weights: Mapping[str, Decimal], limits: RiskLimits
) -> tuple[dict[str, Decimal], bool]:
    clipped: dict[str, Decimal] = {}
    reduced = False
    for symbol, weight in weights.items():
        if weight <= 0:
            continue
        if weight > limits.max_position_weight:
            clipped[symbol] = limits.max_position_weight
            reduced = True
        else:
            clipped[symbol] = weight
    if len(clipped) > limits.max_positions:
        reduced = True
        ranked = sorted(clipped.items(), key=lambda item: item[1], reverse=True)
        clipped = dict(ranked[: limits.max_positions])
    invested = sum(clipped.values(), start=Decimal(0))
    if invested > limits.max_gross_exposure:
        reduced = True
        scale = limits.max_gross_exposure / invested
        clipped = {symbol: weight * scale for symbol, weight in clipped.items()}
    return clipped, reduced


def _share_qty(weight: Decimal, equity: Decimal, price: Decimal) -> Decimal:
    if price <= 0 or weight <= 0 or equity <= 0:
        return Decimal(0)
    raw = (weight * equity) / price
    return raw.to_integral_value(rounding=ROUND_DOWN)


def _approved_lines(
    *,
    target: Mapping[str, Decimal],
    book: BookState,
    prices: Mapping[str, Decimal],
    equity: Decimal,
) -> list[ApprovedLine]:
    symbols = sorted(set(target) | set(book.held_symbols))
    lines: list[ApprovedLine] = []
    for symbol in symbols:
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        desired = _share_qty(target.get(symbol, Decimal(0)), equity, price)
        held = book.quantity(symbol)
        delta = desired - held
        if delta > 0:
            lines.append(ApprovedLine(symbol=symbol, side=Side.BUY, quantity=delta))
        elif delta < 0 and held > 0:
            sell = min(-delta, held)
            if sell > 0:
                lines.append(ApprovedLine(symbol=symbol, side=Side.SELL, quantity=sell))
    return lines


def evaluate_proposal(
    proposal: Proposal,
    *,
    limits: RiskLimits,
    book: BookState,
    prices: Mapping[str, Decimal],
    decided_at: datetime,
    data_as_of: datetime,
    kill_switch: bool,
) -> RiskDecision:
    """Judge ``proposal`` against ``limits`` and the current book.

    Hard rejects: kill switch, stale data, daily loss, drawdown.
    Reduces: name cap, name count, gross exposure. Sells never open a short.
    """
    staleness = _seconds_stale(decided_at, data_as_of)
    daily_loss = book.daily_loss_fraction(prices)
    drawdown = book.drawdown_fraction(prices)
    name_cap = max((line.target_weight for line in proposal.lines), default=Decimal(0))
    n_names = len(proposal.lines)
    gross = proposal.invested_weight

    checks = [
        LimitCheck(
            limit_id="kill_switch",
            limit_value=Decimal(0),
            observed_value=Decimal(1) if kill_switch else Decimal(0),
            breached=kill_switch,
        ),
        LimitCheck(
            limit_id="stale_data",
            limit_value=limits.max_data_staleness_seconds,
            observed_value=staleness,
            breached=staleness > limits.max_data_staleness_seconds,
        ),
        LimitCheck(
            limit_id="daily_loss",
            limit_value=limits.max_daily_loss,
            observed_value=daily_loss,
            breached=daily_loss >= limits.max_daily_loss,
        ),
        LimitCheck(
            limit_id="drawdown",
            limit_value=limits.max_drawdown,
            observed_value=drawdown,
            breached=drawdown >= limits.max_drawdown,
        ),
        LimitCheck(
            limit_id="name_cap",
            limit_value=limits.max_position_weight,
            observed_value=name_cap,
            breached=name_cap > limits.max_position_weight,
        ),
        LimitCheck(
            limit_id="max_positions",
            limit_value=Decimal(limits.max_positions),
            observed_value=Decimal(n_names),
            breached=n_names > limits.max_positions,
        ),
        LimitCheck(
            limit_id="gross_exposure",
            limit_value=limits.max_gross_exposure,
            observed_value=gross,
            breached=gross > limits.max_gross_exposure,
        ),
    ]
    hard = {"kill_switch", "stale_data", "daily_loss", "drawdown"}
    hard_breach = any(check.breached and check.limit_id in hard for check in checks)
    decision_id = derive_decision_id(proposal.proposal_id, limits.config_hash)

    if kill_switch or hard_breach:
        reasons = [check.limit_id for check in checks if check.breached and check.limit_id in hard]
        return RiskDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            decided_at=decided_at,
            outcome=RiskOutcome.REJECTED,
            risk_config_hash=limits.config_hash,
            checks=checks,
            approved_lines=[],
            kill_switch_engaged=kill_switch,
            data_staleness_seconds=staleness,
            reason="rejected: " + ", ".join(reasons),
        )

    requested = {line.symbol: line.target_weight for line in proposal.lines}
    target, reduced = _clip_weights(requested, limits)
    equity = book.marked_equity(prices)
    lines = _approved_lines(target=target, book=book, prices=prices, equity=equity)
    outcome = RiskOutcome.REDUCED if reduced else RiskOutcome.APPROVED
    reason = "reduced to fit limits" if reduced else "within all limits"
    return RiskDecision(
        decision_id=decision_id,
        proposal_id=proposal.proposal_id,
        decided_at=decided_at,
        outcome=outcome,
        risk_config_hash=limits.config_hash,
        checks=checks,
        approved_lines=lines,
        kill_switch_engaged=False,
        data_staleness_seconds=staleness,
        reason=reason,
    )


__all__ = ["evaluate_proposal"]
