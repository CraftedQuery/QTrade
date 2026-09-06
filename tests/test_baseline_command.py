"""The reproduce command runs from committed fixtures without secrets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab.contracts.enums import DatasetSplit
from lab.experiments.baseline import main, run_baseline


def test_run_baseline_from_fixtures_registers_then_unseals(tmp_path: Path) -> None:
    report = run_baseline(source="fixture", output_dir=tmp_path / "exp")
    assert report["trial_count"] == 1
    assert report["bar_source"] == "fixture"
    assert int(report["bar_count"]) > 0
    assert int(report["universe_size"]) == 50
    assert report["survivorship_flagged"] is True
    assert report["holdout_unsealed_at"]
    training_splits = {row["split"] for row in report["training"]}  # type: ignore[union-attr]
    holdout_splits = {row["split"] for row in report["holdout"]}  # type: ignore[union-attr]
    assert training_splits == {DatasetSplit.TRAIN.value, DatasetSplit.VALIDATION.value}
    assert holdout_splits == {DatasetSplit.HOLDOUT.value}
    for row in list(report["training"]) + list(report["holdout"]):  # type: ignore[operator]
        assert row["trial_count"] == 1
        assert "total_return_net" in row
        assert "max_drawdown_net" in row
        assert "mean_one_way_turnover" in row
    written = json.loads((tmp_path / "exp" / "report.json").read_text(encoding="utf-8"))
    assert written["experiment_id"] == report["experiment_id"]


def test_cli_writes_artifacts_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--source", "fixture", "--output", str(tmp_path / "cli")])
    assert code == 0
    captured = capsys.readouterr()
    assert "trial_count" in captured.out
    assert "holdout" in captured.out
    assert (tmp_path / "cli" / "experiment.json").is_file()
    assert (tmp_path / "cli" / "training.json").is_file()
    assert (tmp_path / "cli" / "holdout.json").is_file()


def test_cli_refuses_alpaca_without_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    code = main(["--source", "alpaca"])
    assert code == 2
    captured = capsys.readouterr()
    assert "Alpaca keys" in captured.err
