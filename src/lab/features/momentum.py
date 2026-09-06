"""21-session close-to-close momentum with an explicit information cutoff.

Acceptance test #2 lives here: a snapshot computed at ``as_of`` may only read
bars whose :attr:`~lab.contracts.market.Bar.information_time` is at or before
``as_of``. Future bars cannot change the value.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from lab.contracts import Bar, FeatureSnapshot
from lab.data.store import bars_available_at

FEATURE_SET = "momentum_v1"
FEATURE_SET_VERSION = "1.0.0"
DEFAULT_LOOKBACK = 21


def compute_momentum(
    bars: Sequence[Bar],
    *,
    symbol: str,
    as_of: datetime,
    lookback: int = DEFAULT_LOOKBACK,
    snapshot_id: str | None = None,
    computed_at: datetime | None = None,
) -> FeatureSnapshot:
    """Compute ``mom_{lookback}d`` for ``symbol`` using only known bars.

    The return is close[t] / close[t - lookback] - 1 over the last
    ``lookback + 1`` eligible closes. ``information_cutoff`` is the newest
    bar actually consumed, or ``as_of`` when no bar is eligible.

    Raises:
        ValueError: If ``lookback`` is not positive.
    """
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    eligible = bars_available_at((bar for bar in bars if bar.symbol == symbol), as_of)
    eligible.sort(key=lambda bar: bar.information_time)
    cutoff = eligible[-1].information_time if eligible else as_of
    values: dict[str, float | None] = {f"mom_{lookback}d": None}
    if len(eligible) >= lookback + 1:
        window = eligible[-(lookback + 1) :]
        start_close = float(window[0].close)
        end_close = float(window[-1].close)
        cutoff = window[-1].information_time
        if start_close > 0:
            values[f"mom_{lookback}d"] = end_close / start_close - 1.0
    if cutoff > as_of:  # pragma: no cover - defensive; filter forbids this
        raise ValueError(
            f"look-ahead: computed cutoff {cutoff.isoformat()} is after as_of {as_of.isoformat()}"
        )
    stamped = computed_at if computed_at is not None else datetime.now(tz=UTC)
    return FeatureSnapshot(
        snapshot_id=snapshot_id or f"{FEATURE_SET}:{symbol}:{as_of.isoformat()}",
        feature_set=FEATURE_SET,
        feature_set_version=FEATURE_SET_VERSION,
        symbol=symbol,
        as_of=as_of,
        information_cutoff=cutoff,
        values=values,
        computed_at=stamped,
    )


__all__ = ["DEFAULT_LOOKBACK", "FEATURE_SET", "FEATURE_SET_VERSION", "compute_momentum"]
