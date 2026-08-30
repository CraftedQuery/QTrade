"""A view of price history restricted to what was knowable at a decision time.

This is where the look-ahead guarantee stops being a contract that *can* express
the rule and becomes a pipeline that *maintains* it.

:class:`~lab.contracts.research.FeatureSnapshot` refuses a snapshot whose
``information_cutoff`` exceeds its ``as_of``. But a cutoff supplied by the caller
is decorative — the caller could pass anything. Here the cutoff is **derived**:
the window admits only bars whose ``information_time`` falls at or before the
decision time, and it records the newest bar it actually handed out. The cutoff
is a consequence of reading, not an argument to it.

A feature function therefore cannot see a future bar (the window does not contain
one) and cannot understate what it read (the window, not the function, reports
the cutoff).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from lab.contracts import Bar


class BarWindow:
    """Bars visible at ``as_of``, tracking which of them were actually read.

    Attributes:
        symbol: The instrument this window covers.
        as_of: The decision time. Nothing whose information arrived after this
            instant is present in the window at all.
    """

    def __init__(self, symbol: str, bars: Iterable[Bar], as_of: datetime) -> None:
        self.symbol = symbol
        self.as_of = as_of
        # A bar is knowable only once it closes, so the filter uses
        # information_time (the bar's end), never ts_start.
        self._bars: list[Bar] = sorted(
            (bar for bar in bars if bar.symbol == symbol and bar.information_time <= as_of),
            key=lambda bar: bar.ts_start,
        )
        self._cutoff: datetime | None = None

    def __len__(self) -> int:
        """How many bars are visible at the decision time."""
        return len(self._bars)

    @property
    def information_cutoff(self) -> datetime | None:
        """Newest information actually consumed, or None if nothing was read."""
        return self._cutoff

    def _record(self, bars: Sequence[Bar]) -> list[Bar]:
        """Note that these bars were read, advancing the derived cutoff."""
        for bar in bars:
            if self._cutoff is None or bar.information_time > self._cutoff:
                self._cutoff = bar.information_time
        return list(bars)

    def recent(self, count: int) -> list[Bar]:
        """The most recent ``count`` visible bars, oldest first.

        Returns fewer than requested when history is short; callers check the
        length rather than being handed a padded series.
        """
        if count <= 0:
            return []
        return self._record(self._bars[-count:])

    def closes(self, count: int) -> list[Decimal]:
        """Closing prices of the most recent ``count`` visible bars."""
        return [bar.close for bar in self.recent(count)]

    def close_at(self, sessions_ago: int) -> Decimal | None:
        """Close ``sessions_ago`` sessions back, or None if that far back is unavailable.

        ``sessions_ago=0`` is the most recent visible bar.
        """
        if sessions_ago < 0 or sessions_ago >= len(self._bars):
            return None
        bar = self._bars[-1 - sessions_ago]
        self._record([bar])
        return bar.close


__all__ = ["BarWindow"]
