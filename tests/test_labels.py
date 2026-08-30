"""Labels must look strictly forward, and must say when they became knowable."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from lab.features import BarWindow, forward_return, label_symbols, overlaps_window
from tests.synthetic import generate_bars, session_window, simple_market, trading_sessions

START, END = date(2022, 1, 1), date(2024, 6, 28)
SPEC = simple_market(start=START, end=END)
BARS = generate_bars(SPEC)
SESSIONS = trading_sessions(START, END)


def at(day: date) -> datetime:
    return session_window(day)[1]


# --- Direction --------------------------------------------------------------


def test_a_label_is_not_knowable_at_decision_time() -> None:
    """The whole point: the outcome lies in the future."""
    for index in (50, 200, 400):
        label = forward_return("AAA", BARS, at(SESSIONS[index]), 21)
        assert label.known_at > label.as_of
        assert label.spans > 0


def test_known_at_is_the_horizon_bar_close() -> None:
    index, horizon = 300, 21
    label = forward_return("AAA", BARS, at(SESSIONS[index]), horizon)
    assert label.known_at == at(SESSIONS[index + horizon])


def test_deleting_bars_before_the_decision_does_not_change_the_return() -> None:
    """A label reads forward only; earlier history is irrelevant to its value."""
    as_of = at(SESSIONS[300])
    full = forward_return("AAA", BARS, as_of, 21)
    trimmed = forward_return(
        "AAA", [b for b in BARS if b.ts_start.date() >= SESSIONS[250]], as_of, 21
    )
    assert full.value == trimmed.value
    assert full.known_at == trimmed.known_at


def test_the_entry_is_the_bar_a_feature_would_have_seen() -> None:
    """Feature and label must agree on where 'now' is, or they are misaligned."""
    as_of = at(SESSIONS[300])
    window = BarWindow("AAA", BARS, as_of)
    assert forward_return("AAA", BARS, as_of, 21).entry_close == float(window.close_at(0))


def test_a_zero_or_negative_horizon_is_rejected() -> None:
    for horizon in (0, -1, -21):
        with pytest.raises(ValueError, match="must look forward"):
            forward_return("AAA", BARS, at(SESSIONS[100]), horizon)


# --- Value ------------------------------------------------------------------


def test_the_return_matches_the_two_closes() -> None:
    label = forward_return("AAA", BARS, at(SESSIONS[300]), 21)
    assert label.value == pytest.approx(label.exit_close / label.entry_close - 1)


def test_longer_horizons_reach_further_forward() -> None:
    as_of = at(SESSIONS[300])
    short = forward_return("AAA", BARS, as_of, 5)
    long = forward_return("AAA", BARS, as_of, 63)
    assert long.known_at > short.known_at
    assert short.entry_close == long.entry_close


# --- Boundaries -------------------------------------------------------------


def test_a_horizon_past_the_history_yields_nothing() -> None:
    """Never estimated from a shorter span."""
    assert forward_return("AAA", BARS, at(SESSIONS[-2]), 21) is None
    assert forward_return("AAA", BARS, at(SESSIONS[-1]), 1) is None


def test_exactly_enough_history_yields_a_label() -> None:
    assert forward_return("AAA", BARS, at(SESSIONS[-22]), 21) is not None


def test_a_decision_before_any_history_yields_nothing() -> None:
    assert forward_return("AAA", BARS, datetime(2000, 1, 1, tzinfo=UTC), 21) is None


def test_an_unknown_symbol_yields_nothing() -> None:
    assert forward_return("NOPE", BARS, at(SESSIONS[300]), 21) is None


def test_a_mid_session_decision_uses_the_previous_close() -> None:
    day = SESSIONS[300]
    midday = session_window(day)[0] + timedelta(hours=1)
    label = forward_return("AAA", BARS, midday, 21)
    assert label.entry_close == float(
        next(b.close for b in BARS if b.symbol == "AAA" and b.ts_start.date() == SESSIONS[299])
    )


# --- Purge support ----------------------------------------------------------


def test_a_label_reaching_a_window_is_flagged_for_purging() -> None:
    """This is what makes the splitter's purge computable rather than notional."""
    as_of = at(SESSIONS[300])
    label = forward_return("AAA", BARS, as_of, 21)

    assert overlaps_window(label, at(SESSIONS[310])), "label ends after the window opens"
    assert not overlaps_window(label, at(SESSIONS[330])), "label ended before the window opened"


def test_the_overlap_boundary_is_inclusive() -> None:
    """A label known exactly at the window open still carries its information."""
    as_of = at(SESSIONS[300])
    label = forward_return("AAA", BARS, as_of, 21)
    assert overlaps_window(label, label.known_at)


# --- Batches ----------------------------------------------------------------


def test_labels_are_produced_per_symbol_and_sorted() -> None:
    labels = label_symbols(["CCC", "AAA", "BBB"], BARS, at(SESSIONS[300]), 21)
    assert [label.symbol for label in labels] == ["AAA", "BBB", "CCC"]


def test_symbols_without_a_full_horizon_are_omitted() -> None:
    """A label set must never mix full and partial spans."""
    assert label_symbols(["AAA", "BBB"], BARS, at(SESSIONS[-2]), 21) == []


def test_labelling_is_reproducible() -> None:
    as_of = at(SESSIONS[300])
    assert forward_return("AAA", BARS, as_of, 21) == forward_return("AAA", BARS, as_of, 21)
