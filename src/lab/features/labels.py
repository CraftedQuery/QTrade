"""Forward-return labels with an explicit horizon.

Labels are the mirror image of features. A feature at *t* must not read anything
after *t*; a label at *t* must read **only** what comes after *t*. Both rules
exist for the same reason, and getting either backwards produces a result that
looks excellent and means nothing.

## The field that matters

Every label carries ``known_at``: the instant its outcome could first have been
observed, which is the information time of the bar that closes the horizon. That
is what makes purging computable. A training row is safe to use against a test
window only if its label was already known before that window opened — and the
splitter checks exactly that, in sessions.

Without ``known_at`` a label is just a number attached to a date, and the
overlap that purge exists to remove becomes invisible.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from lab.contracts import Bar


@dataclass(frozen=True)
class Label:
    """One forward return, with the timestamps that make it auditable.

    Attributes:
        symbol: Instrument the return belongs to.
        as_of: Decision time the label is attached to. The entry price is the
            close at or before this instant.
        horizon_sessions: Sessions the return spans.
        value: The forward simple return over the horizon.
        known_at: When the outcome could first have been observed. Always later
            than ``as_of``; this is the timestamp purge compares against.
        entry_close: Price the return starts from.
        exit_close: Price the return ends at.
    """

    symbol: str
    as_of: datetime
    horizon_sessions: int
    value: float
    known_at: datetime
    entry_close: float
    exit_close: float

    @property
    def spans(self) -> float:
        """Seconds between the decision and the outcome becoming observable."""
        return (self.known_at - self.as_of).total_seconds()


def _ordered(bars: Iterable[Bar], symbol: str) -> list[Bar]:
    return sorted((bar for bar in bars if bar.symbol == symbol), key=lambda bar: bar.ts_start)


def forward_return(
    symbol: str,
    bars: Iterable[Bar],
    as_of: datetime,
    horizon_sessions: int,
) -> Label | None:
    """The realised return over ``horizon_sessions`` following ``as_of``.

    The entry is the last close at or before ``as_of`` — the same bar a feature
    computed at ``as_of`` would have seen — and the exit is the close
    ``horizon_sessions`` later.

    Args:
        symbol: Instrument to label.
        bars: Price history, which must extend past the horizon.
        as_of: Decision time to attach the label to.
        horizon_sessions: Sessions the return spans. Must be positive; a
            zero-session label would be knowable at decision time, which is not
            a forecast.

    Returns:
        The label, or None when the history does not reach the end of the
        horizon. A truncated label is never estimated from a shorter span.

    Raises:
        ValueError: If ``horizon_sessions`` is not positive.
    """
    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive; a label must look forward")

    series = _ordered(bars, symbol)
    entry_index = None
    for index, bar in enumerate(series):
        if bar.information_time <= as_of:
            entry_index = index
        else:
            break
    if entry_index is None:
        return None

    exit_index = entry_index + horizon_sessions
    if exit_index >= len(series):
        return None

    entry, exit_bar = series[entry_index], series[exit_index]
    if entry.close <= 0:
        return None

    return Label(
        symbol=symbol,
        as_of=as_of,
        horizon_sessions=horizon_sessions,
        value=float(exit_bar.close / entry.close - 1),
        known_at=exit_bar.information_time,
        entry_close=float(entry.close),
        exit_close=float(exit_bar.close),
    )


def label_symbols(
    symbols: Sequence[str],
    bars: Iterable[Bar],
    as_of: datetime,
    horizon_sessions: int,
) -> list[Label]:
    """Label several instruments at one decision time.

    Symbols whose history does not reach the end of the horizon are omitted, so
    a label set never mixes full and partial spans.
    """
    materialised = list(bars)
    labels = [
        forward_return(symbol, materialised, as_of, horizon_sessions) for symbol in sorted(symbols)
    ]
    return [label for label in labels if label is not None]


def overlaps_window(label: Label, window_start: datetime) -> bool:
    """Whether this label's outcome was still unknown when ``window_start`` opened.

    True means the label reaches across the boundary and the row must be purged:
    it encodes information from inside the window it would be tested against.
    """
    return label.known_at >= window_start


__all__ = ["Label", "forward_return", "label_symbols", "overlaps_window"]
