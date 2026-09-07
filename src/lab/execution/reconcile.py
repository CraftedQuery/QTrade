"""Compare local ledger positions to the paper broker after restart."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class QuantityMismatch:
    """A name held on both sides at different sizes."""

    symbol: str
    local_qty: Decimal
    broker_qty: Decimal


@dataclass(frozen=True)
class ReconcileReport:
    """Result of comparing local vs broker share counts."""

    local_positions: dict[str, Decimal]
    broker_positions: dict[str, Decimal]
    local_only: tuple[str, ...]
    broker_only: tuple[str, ...]
    quantity_mismatches: tuple[QuantityMismatch, ...]

    @property
    def is_clean(self) -> bool:
        """Whether both sides agree on every name and quantity."""
        return not self.local_only and not self.broker_only and not self.quantity_mismatches


def _nonzero(positions: Mapping[str, Decimal]) -> dict[str, Decimal]:
    return {symbol: qty for symbol, qty in positions.items() if qty != 0}


def reconcile(
    local: Mapping[str, Decimal],
    broker: Mapping[str, Decimal],
) -> ReconcileReport:
    """Diff two share maps. Zero quantities are treated as absent."""
    left = _nonzero(local)
    right = _nonzero(broker)
    local_only = tuple(sorted(set(left) - set(right)))
    broker_only = tuple(sorted(set(right) - set(left)))
    mismatches = tuple(
        QuantityMismatch(symbol=symbol, local_qty=left[symbol], broker_qty=right[symbol])
        for symbol in sorted(set(left) & set(right))
        if left[symbol] != right[symbol]
    )
    return ReconcileReport(
        local_positions=dict(left),
        broker_positions=dict(right),
        local_only=local_only,
        broker_only=broker_only,
        quantity_mismatches=mismatches,
    )


__all__ = ["QuantityMismatch", "ReconcileReport", "reconcile"]
