"""Point-in-time universe membership with a trailing liquidity screen.

## The two ways a universe leaks the future

**Survivorship.** Building from a current constituent list silently excludes
everything that failed or was acquired. :class:`Universe` answers membership from
each instrument's listing window, and a universe whose source cannot support
point-in-time claims is marked ``survivorship_biased`` on the record itself —
not in a comment that nobody reads at analysis time.

**The liquidity screen.** This one is subtler and easier to get wrong. Screening
on average volume computed over the *whole* history selects names that turned out
to be liquid later, which is a look-ahead. The screen here uses only bars whose
:attr:`~lab.contracts.market.Bar.information_time` falls at or before the
evaluation date, so a name enters the universe only once it has *already* traded
enough to qualify.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from lab.contracts import Bar, Instrument
from lab.contracts.base import Identifier, LabModel, LabRecord, Price, UtcDatetime


class LiquidityScreen(LabModel):
    """A trailing liquidity filter.

    Every threshold is evaluated over a trailing window ending at the evaluation
    date. Nothing after that date is visible to the screen, so a name cannot
    qualify on the strength of volume it had not yet traded.
    """

    lookback_sessions: int = Field(
        default=60, ge=1, description="Sessions of history the screen looks back over."
    )
    min_sessions: int = Field(
        default=40, ge=1, description="Sessions that must actually be present in the window."
    )
    min_median_dollar_volume: Price = Field(
        default=Decimal("1000000"),
        description="Median close x volume over the window, below which a name is excluded.",
    )
    min_price: Price = Field(
        default=Decimal("5"), description="Minimum close price, excluding penny stocks."
    )

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.min_sessions > self.lookback_sessions:
            raise ValueError(
                f"min_sessions ({self.min_sessions}) exceeds lookback_sessions "
                f"({self.lookback_sessions}); the screen could never pass"
            )
        return self


class UniverseMember(LabModel):
    """One instrument's membership on one date, with the evidence for it."""

    symbol: Identifier = Field(description="Instrument ticker.")
    as_of: date = Field(description="Date this membership applies to.")
    median_dollar_volume: Decimal = Field(description="Trailing median dollar volume.")
    last_close: Price = Field(description="Most recent close at or before as_of.")
    sessions_observed: int = Field(ge=0, description="Sessions available in the window.")


class Universe(LabRecord):
    """A dated universe: which symbols were eligible on which dates.

    Attributes:
        survivorship_biased: True when the instrument data cannot support
            point-in-time membership. Recorded on the universe itself so any
            downstream result carries the warning with it.
    """

    universe_id: Identifier = Field(description="Universe definition identifier.")
    screen: LiquidityScreen = Field(description="Liquidity screen applied.")
    start: date = Field(description="First date evaluated.")
    end: date = Field(description="Last date evaluated.")
    members_by_date: dict[date, list[UniverseMember]] = Field(
        description="Eligible members for each evaluated date."
    )
    survivorship_biased: bool = Field(
        description="True when membership cannot be established point-in-time."
    )
    built_at: UtcDatetime = Field(description="When the universe was constructed.")

    def symbols_on(self, day: date) -> list[str]:
        """Tickers eligible on ``day``, sorted. Empty when the date was not evaluated."""
        return sorted(member.symbol for member in self.members_by_date.get(day, []))

    def dates(self) -> list[date]:
        """Every evaluated date, in order."""
        return sorted(self.members_by_date)

    @property
    def max_size(self) -> int:
        """Largest membership across all evaluated dates."""
        return max((len(members) for members in self.members_by_date.values()), default=0)


def _end_of_day(day: date) -> datetime:
    """The instant a date's information is complete, for cutoff comparisons."""
    return datetime.combine(day, time.max).replace(tzinfo=UTC)


def _median(values: Sequence[Decimal]) -> Decimal:
    """Median of a non-empty sequence, exact in Decimal."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _visible_bars(bars: Sequence[Bar], as_of: date) -> list[Bar]:
    """Bars whose information was complete at or before the end of ``as_of``.

    Uses ``information_time`` (the bar's close), never ``ts_start``. A daily bar
    dated ``as_of`` is legitimately visible; anything later is not.
    """
    cutoff = _end_of_day(as_of)
    return [bar for bar in bars if bar.information_time <= cutoff]


def _evaluate(
    symbol: str, bars: Sequence[Bar], as_of: date, screen: LiquidityScreen
) -> UniverseMember | None:
    """Apply the trailing screen to one symbol on one date."""
    visible = _visible_bars(bars, as_of)
    window = visible[-screen.lookback_sessions :]
    if len(window) < screen.min_sessions:
        return None

    last_close = window[-1].close
    if last_close < screen.min_price:
        return None

    dollar_volume = _median([bar.close * bar.volume for bar in window])
    if dollar_volume < screen.min_median_dollar_volume:
        return None

    return UniverseMember(
        symbol=symbol,
        as_of=as_of,
        median_dollar_volume=dollar_volume,
        last_close=last_close,
        sessions_observed=len(window),
    )


def build_universe(
    universe_id: str,
    instruments: Iterable[Instrument],
    bars: Iterable[Bar],
    evaluation_dates: Sequence[date],
    screen: LiquidityScreen | None = None,
    built_at: datetime | None = None,
) -> Universe:
    """Build a dated universe from instruments and their bars.

    A symbol is eligible on a date when it was listed on that date *and* passed
    the trailing liquidity screen using only information available by then.

    Args:
        universe_id: Identifier stored on experiments that use this universe.
        instruments: Reference data. Instruments lacking ``listed_on`` cannot
            support point-in-time membership and mark the universe biased.
        bars: Price history for the candidate symbols.
        evaluation_dates: Dates to evaluate membership on, typically rebalances.
        screen: Liquidity filter. Defaults to :class:`LiquidityScreen`.
        built_at: Construction timestamp, for the record.

    Returns:
        The universe, with ``survivorship_biased`` set when any instrument's
        listing window is unknown.
    """
    applied = screen or LiquidityScreen()
    reference = {instrument.symbol: instrument for instrument in instruments}

    by_symbol: dict[str, list[Bar]] = {}
    for bar in bars:
        by_symbol.setdefault(bar.symbol, []).append(bar)
    for series in by_symbol.values():
        series.sort(key=lambda bar: bar.ts_start)

    # An instrument with no listing date cannot answer "was this tradable then?".
    # The universe is marked rather than silently trusted.
    biased = any(instrument.listed_on is None for instrument in reference.values())

    members_by_date: dict[date, list[UniverseMember]] = {}
    for day in sorted(evaluation_dates):
        eligible: list[UniverseMember] = []
        for symbol, series in sorted(by_symbol.items()):
            instrument = reference.get(symbol)
            if instrument is None or not instrument.was_listed_on(day):
                continue
            member = _evaluate(symbol, series, day, applied)
            if member is not None:
                eligible.append(member)
        members_by_date[day] = eligible

    return Universe(
        universe_id=universe_id,
        screen=applied,
        start=min(evaluation_dates),
        end=max(evaluation_dates),
        members_by_date=members_by_date,
        survivorship_biased=biased,
        built_at=built_at or datetime.now(UTC),
    )


__all__ = ["LiquidityScreen", "Universe", "UniverseMember", "build_universe"]
