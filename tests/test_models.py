"""Ridge baseline: alignment, fitting, and prediction records."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from lab.contracts import Prediction
from lab.contracts.enums import DatasetSplit
from lab.features import MOMENTUM_V1, compute_snapshots, label_symbols
from lab.models import TrainingRow, align, fit_ridge, predict
from tests.synthetic import (
    MarketSpec,
    SymbolSpec,
    generate_bars,
    session_window,
    trading_sessions,
)

START, END = date(2020, 1, 1), date(2024, 12, 31)
SYMBOLS = tuple(f"S{i:02d}" for i in range(12))
SPEC = MarketSpec(
    symbols=tuple(
        SymbolSpec(s, annual_drift=-0.1 + 0.04 * i, annual_vol=0.15 + 0.02 * i)
        for i, s in enumerate(SYMBOLS)
    ),
    start=START,
    end=END,
)
BARS = generate_bars(SPEC)
SESSIONS = trading_sessions(START, END)
NAMES = MOMENTUM_V1.names
HORIZON = 21


def build_rows(indices: range) -> list[TrainingRow]:
    """Aligned training rows across several decision times."""
    snapshots, labels = [], []
    for index in indices:
        as_of = session_window(SESSIONS[index])[1]
        snapshots.extend(compute_snapshots(SYMBOLS, BARS, as_of, MOMENTUM_V1))
        labels.extend(label_symbols(SYMBOLS, BARS, as_of, HORIZON))
    return align(snapshots, labels, NAMES)


ROWS = build_rows(range(300, 800, 21))
LATE = session_window(SESSIONS[900])[1]
LATE_SNAPSHOTS = compute_snapshots(SYMBOLS, BARS, LATE, MOMENTUM_V1)


# --- Alignment --------------------------------------------------------------


def test_rows_align_features_to_their_own_label() -> None:
    assert ROWS
    for row in ROWS:
        assert len(row.features) == len(NAMES)
        assert row.label_known_at > row.as_of


def test_incomplete_snapshots_are_dropped_not_imputed() -> None:
    """A zero standing in for 'not enough history' is a fabricated observation."""
    early = session_window(SESSIONS[30])[1]
    snapshots = compute_snapshots(SYMBOLS, BARS, early, MOMENTUM_V1)
    labels = label_symbols(SYMBOLS, BARS, early, HORIZON)
    assert snapshots and labels
    assert align(snapshots, labels, NAMES) == []


def test_a_snapshot_without_a_label_is_dropped() -> None:
    as_of = session_window(SESSIONS[500])[1]
    snapshots = compute_snapshots(SYMBOLS, BARS, as_of, MOMENTUM_V1)
    assert align(snapshots, [], NAMES) == []


def test_alignment_matches_on_symbol_and_time() -> None:
    """A label from a different decision time must not attach to this snapshot."""
    as_of = session_window(SESSIONS[500])[1]
    other = session_window(SESSIONS[520])[1]
    snapshots = compute_snapshots(SYMBOLS, BARS, as_of, MOMENTUM_V1)
    mismatched = label_symbols(SYMBOLS, BARS, other, HORIZON)
    assert align(snapshots, mismatched, NAMES) == []


def test_rows_are_ordered_deterministically() -> None:
    assert [(r.as_of, r.symbol) for r in ROWS] == sorted((r.as_of, r.symbol) for r in ROWS)


# --- Fitting ----------------------------------------------------------------


def test_a_model_fits_and_exposes_its_coefficients() -> None:
    model = fit_ridge(ROWS, NAMES)
    assert model is not None
    assert set(model.coefficient_map) == set(NAMES)
    assert model.rows_fitted == len(ROWS)


def test_fitting_is_reproducible() -> None:
    first, second = fit_ridge(ROWS, NAMES), fit_ridge(ROWS, NAMES)
    assert first.coefficients == second.coefficients
    assert first.intercept == second.intercept


def test_too_few_rows_yields_no_model() -> None:
    """Better no model than one fitted to noise."""
    assert fit_ridge(ROWS[:5], NAMES, min_rows=30) is None
    assert fit_ridge([], NAMES) is None


def test_stronger_regularization_shrinks_coefficients() -> None:
    weak = fit_ridge(ROWS, NAMES, alpha=0.01)
    strong = fit_ridge(ROWS, NAMES, alpha=1000.0)
    assert sum(abs(c) for c in strong.coefficients) < sum(abs(c) for c in weak.coefficients)


def test_the_model_recovers_a_planted_linear_relationship() -> None:
    """If it cannot fit a signal that is definitely there, the fit is wrong."""
    stamp = datetime(2024, 1, 1, tzinfo=UTC)
    rows = [
        TrainingRow(
            symbol=f"X{i}",
            as_of=stamp,
            features=(float(i), 0.0, 0.0, 0.0),
            label=3.0 * i + 1.0,
            label_known_at=stamp + timedelta(days=21),
        )
        for i in range(60)
    ]
    model = fit_ridge(rows, NAMES, alpha=1e-6)
    assert model.coefficient_map["mom_21"] == pytest.approx(3.0, rel=1e-3)
    assert model.intercept == pytest.approx(1.0, rel=1e-2)


def test_predict_one_rejects_a_wrong_feature_count() -> None:
    model = fit_ridge(ROWS, NAMES)
    with pytest.raises(ValueError, match="expected 4 features"):
        model.predict_one([1.0, 2.0])


# --- Predictions ------------------------------------------------------------


def test_predictions_are_emitted_as_contract_records() -> None:
    model = fit_ridge(ROWS, NAMES)
    predictions = predict(model, LATE_SNAPSHOTS, "exp-1", DatasetSplit.VALIDATION, HORIZON)
    assert predictions
    assert all(isinstance(p, Prediction) for p in predictions)
    assert {p.split for p in predictions} == {DatasetSplit.VALIDATION}
    assert {p.model_version for p in predictions} == {"ridge-1.0.0"}


def test_a_prediction_carries_no_outcome() -> None:
    """Written before the future arrives; the contract has nowhere to put one."""
    model = fit_ridge(ROWS, NAMES)
    prediction = predict(model, LATE_SNAPSHOTS, "exp-1", DatasetSplit.HOLDOUT, HORIZON)[0]
    forbidden = {"realized", "realized_return", "outcome", "actual", "was_correct"}
    assert forbidden.isdisjoint(type(prediction).model_fields)


def test_a_prediction_links_back_to_its_snapshot() -> None:
    model = fit_ridge(ROWS, NAMES)
    by_id = {s.snapshot_id: s for s in LATE_SNAPSHOTS}
    for prediction in predict(model, LATE_SNAPSHOTS, "exp-1", DatasetSplit.TRAIN, HORIZON):
        assert prediction.feature_snapshot_id in by_id
        assert by_id[prediction.feature_snapshot_id].symbol == prediction.symbol


def test_incomplete_snapshots_are_not_scored() -> None:
    """A prediction must never rest on an imputed input."""
    model = fit_ridge(ROWS, NAMES)
    early = compute_snapshots(SYMBOLS, BARS, session_window(SESSIONS[30])[1], MOMENTUM_V1)
    assert predict(model, early, "exp-1", DatasetSplit.TRAIN, HORIZON) == []


def test_prediction_values_match_the_model() -> None:
    model = fit_ridge(ROWS, NAMES)
    predictions = predict(model, LATE_SNAPSHOTS, "exp-1", DatasetSplit.VALIDATION, HORIZON)
    by_symbol = {s.symbol: s for s in LATE_SNAPSHOTS}
    for prediction in predictions:
        expected = model.predict_one(
            [float(by_symbol[prediction.symbol].values[name]) for name in NAMES]
        )
        assert prediction.value == pytest.approx(expected)


def test_predictions_resolve_after_their_horizon() -> None:
    model = fit_ridge(ROWS, NAMES)
    for prediction in predict(model, LATE_SNAPSHOTS, "exp-1", DatasetSplit.TRAIN, HORIZON):
        assert prediction.target_time > prediction.as_of


def test_prediction_is_reproducible() -> None:
    model = fit_ridge(ROWS, NAMES)
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    first = predict(model, LATE_SNAPSHOTS, "e", DatasetSplit.TRAIN, HORIZON, created_at=stamp)
    second = predict(model, LATE_SNAPSHOTS, "e", DatasetSplit.TRAIN, HORIZON, created_at=stamp)
    assert first == second
