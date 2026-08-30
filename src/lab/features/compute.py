"""Feature definitions and snapshot computation.

Every feature reads through a :class:`~lab.features.window.BarWindow`, so it can
only see bars that had closed by the decision time, and the snapshot's
``information_cutoff`` is whatever the window says was actually read.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from lab.contracts import Bar, FeatureSnapshot
from lab.features.window import BarWindow


@dataclass(frozen=True)
class FeatureDef:
    """One named feature and the history it needs.

    Attributes:
        name: Column name in the snapshot.
        lookback: Sessions of history required. A window with fewer visible
            bars yields ``None`` for this feature rather than a wrong number.
        compute: Function from window to value, or None when unavailable.
    """

    name: str
    lookback: int
    compute: Callable[[BarWindow], float | None]


@dataclass(frozen=True)
class FeatureSet:
    """A named, versioned collection of features."""

    name: str
    version: str
    features: tuple[FeatureDef, ...]

    @property
    def max_lookback(self) -> int:
        """Longest history any feature in the set needs."""
        return max((feature.lookback for feature in self.features), default=0)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(feature.name for feature in self.features)


def _simple_return(window: BarWindow, sessions: int) -> float | None:
    """Return over ``sessions``, from the close that far back to the latest close."""
    latest = window.close_at(0)
    earlier = window.close_at(sessions)
    if latest is None or earlier is None or earlier <= 0:
        return None
    return float(latest / earlier - 1)


def _skip_month_momentum(window: BarWindow, long: int, skip: int) -> float | None:
    """Classic 12-1 momentum: total return, excluding the most recent month.

    The recent month is dropped because short-horizon reversal tends to cancel
    the longer-horizon momentum effect.
    """
    recent = window.close_at(skip)
    earlier = window.close_at(long)
    if recent is None or earlier is None or earlier <= 0:
        return None
    return float(recent / earlier - 1)


def _realized_volatility(window: BarWindow, sessions: int) -> float | None:
    """Annualised standard deviation of daily log returns over ``sessions``."""
    closes = window.closes(sessions + 1)
    if len(closes) < sessions + 1:
        return None
    returns = [
        math.log(float(later / earlier))
        for earlier, later in pairwise(closes)
        if earlier > 0 and later > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


MOMENTUM_V1 = FeatureSet(
    name="momentum_v1",
    version="1.0.0",
    features=(
        FeatureDef("mom_21", 22, lambda w: _simple_return(w, 21)),
        FeatureDef("mom_63", 64, lambda w: _simple_return(w, 63)),
        FeatureDef("mom_252_21", 253, lambda w: _skip_month_momentum(w, 252, 21)),
        FeatureDef("vol_21", 22, lambda w: _realized_volatility(w, 21)),
    ),
)
"""The Release 0.2 baseline feature set: three momentum horizons and one risk measure."""


def compute_snapshot(
    symbol: str,
    bars: Iterable[Bar],
    as_of: datetime,
    feature_set: FeatureSet = MOMENTUM_V1,
    snapshot_id: str | None = None,
    computed_at: datetime | None = None,
) -> FeatureSnapshot | None:
    """Compute one instrument's features at one decision time.

    The window admits only bars that had closed by ``as_of``, and the snapshot's
    ``information_cutoff`` is derived from what the features actually read. A bar
    dated after ``as_of`` cannot influence the result, because it is not in the
    window at all.

    Args:
        symbol: Instrument to compute for.
        bars: Price history. May contain bars after ``as_of``; they are excluded.
        as_of: Decision time the features are valid for.
        feature_set: Which features to compute.
        snapshot_id: Identifier. Defaults to symbol, set and timestamp.
        computed_at: Wall-clock time of computation.

    Returns:
        The snapshot, or None when no bar was visible at ``as_of`` — with nothing
        read there is no honest cutoff to record.
    """
    window = BarWindow(symbol, bars, as_of)
    values = {feature.name: feature.compute(window) for feature in feature_set.features}

    cutoff = window.information_cutoff
    if cutoff is None:
        return None

    return FeatureSnapshot(
        snapshot_id=snapshot_id or f"{symbol}:{feature_set.name}:{as_of.isoformat()}",
        feature_set=feature_set.name,
        feature_set_version=feature_set.version,
        symbol=symbol,
        as_of=as_of,
        information_cutoff=cutoff,
        values=values,
        computed_at=computed_at or as_of,
    )


def compute_snapshots(
    symbols: Sequence[str],
    bars: Iterable[Bar],
    as_of: datetime,
    feature_set: FeatureSet = MOMENTUM_V1,
    computed_at: datetime | None = None,
) -> list[FeatureSnapshot]:
    """Compute snapshots for several instruments at one decision time.

    Symbols with no visible history are omitted rather than represented by a
    snapshot full of nulls.
    """
    materialised = list(bars)
    snapshots = [
        compute_snapshot(symbol, materialised, as_of, feature_set, computed_at=computed_at)
        for symbol in sorted(symbols)
    ]
    return [snapshot for snapshot in snapshots if snapshot is not None]


def is_complete(snapshot: FeatureSnapshot) -> bool:
    """Whether every feature in the snapshot has a value.

    Incomplete snapshots are legitimate early in a series, when the longest
    lookback has not yet been satisfied. Models should skip them rather than
    impute, so that a short history never becomes a fabricated signal.
    """
    return all(value is not None for value in snapshot.values.values())


__all__ = [
    "MOMENTUM_V1",
    "FeatureDef",
    "FeatureSet",
    "compute_snapshot",
    "compute_snapshots",
    "is_complete",
]
