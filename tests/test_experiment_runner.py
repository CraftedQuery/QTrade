"""The baseline experiment: registration order, isolation, and one command."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from lab.config import ExperimentConfig, load_experiment_config
from lab.costs import CONSERVATIVE_V1
from lab.experiments.baseline import BaselineResult, format_report, main, register, run
from tests.synthetic import MarketSpec, SymbolSpec, generate_bars, generate_instruments
from tests.test_holdout import import_graph, reachable_from

REPO_ROOT = Path(__file__).resolve().parents[1]
START, END = date(2020, 1, 1), date(2024, 12, 31)
SYMS = tuple(f"SYN{i:02d}" for i in range(14))
SPEC = MarketSpec(
    symbols=tuple(
        SymbolSpec(s, annual_drift=-0.05 + 0.02 * i, annual_vol=0.18 + 0.01 * i)
        for i, s in enumerate(SYMS)
    ),
    start=START,
    end=END,
)
BARS = generate_bars(SPEC)
INSTRUMENTS = generate_instruments(SPEC)
CONFIG = load_experiment_config(env={}).model_copy(
    update={"benchmark_symbol": "SYN00", "top_n": 5, "max_names": 14}
)
STAMP = datetime(2026, 8, 31, tzinfo=UTC)


@pytest.fixture(scope="module")
def result() -> BaselineResult:
    return run(INSTRUMENTS, BARS, CONFIG, CONSERVATIVE_V1, registered_at=STAMP)


# --- Registration comes first ----------------------------------------------


def test_the_experiment_is_registered_before_results_exist(result: BaselineResult) -> None:
    """An experiment registered after its results is a description, not a hypothesis."""
    assert result.experiment.registered_at == STAMP
    assert result.experiment.hypothesis


def test_registration_needs_no_results(result: BaselineResult) -> None:
    """register() is callable with data alone, which is what makes the order real."""
    sessions = sorted({bar.ts_start.date() for bar in BARS})
    early = register(CONFIG, CONSERVATIVE_V1, sessions, "a claim", 1, STAMP)
    assert early.experiment_id == result.experiment.experiment_id
    assert early.holdout_is_sealed


def test_everything_the_result_depends_on_is_pinned(result: BaselineResult) -> None:
    experiment = result.experiment
    assert experiment.config_hash == CONFIG.config_hash
    assert experiment.code_git_sha
    assert experiment.cost_model_id == CONSERVATIVE_V1.model_id
    assert experiment.feature_set == CONFIG.feature_set


def test_the_trial_count_is_carried(result: BaselineResult) -> None:
    once = run(INSTRUMENTS, BARS, CONFIG, CONSERVATIVE_V1, trial_count=7, registered_at=STAMP)
    assert once.experiment.trial_count == 7
    assert "trial_count     : 7" in format_report(once)


def test_a_config_change_changes_the_experiment_id(result: BaselineResult) -> None:
    """Raising max_names is a different experiment, not the same one with more data."""
    wider = CONFIG.model_copy(update={"max_names": 100})
    assert wider.config_hash != CONFIG.config_hash
    other = run(INSTRUMENTS, BARS, wider, CONSERVATIVE_V1, registered_at=STAMP)
    assert other.experiment.experiment_id != result.experiment.experiment_id


# --- The holdout is never touched -------------------------------------------


def test_the_run_leaves_the_holdout_sealed(result: BaselineResult) -> None:
    assert result.experiment.holdout_is_sealed
    assert result.experiment.holdout_unsealed_at is None


def test_the_runner_cannot_reach_the_holdout_evaluator() -> None:
    """The isolation from task 11 must hold for the runner too."""
    graph = import_graph()
    assert "lab.experiments.baseline" in graph
    assert "lab.evaluation.holdout" not in reachable_from("lab.experiments.baseline", graph)


def test_every_prediction_is_a_validation_prediction(result: BaselineResult) -> None:
    assert result.predictions
    assert {p.split.value for p in result.predictions} == {"validation"}


# --- Comparators ------------------------------------------------------------


def test_all_four_comparators_run_on_the_same_path(result: BaselineResult) -> None:
    assert [s.name for s in result.summaries] == [
        "momentum",
        "equal_weight",
        "benchmark",
        "cash",
    ]


def test_the_candidate_is_first_and_controls_follow(result: BaselineResult) -> None:
    """Order is fixed so the controls cannot be skipped past."""
    assert result.summaries[0].name == "momentum"


def test_results_are_net_of_costs(result: BaselineResult) -> None:
    momentum = result.summaries[0]
    assert momentum.cost_drag > 0
    assert momentum.net_return < momentum.gross_return


def test_cash_earns_nothing(result: BaselineResult) -> None:
    """No interest-rate assumption; inventing one would flatter sitting in cash."""
    cash = next(s for s in result.summaries if s.name == "cash")
    assert cash.gross_return == 0.0
    assert cash.cost_drag == 0.0


def test_the_headline_ic_is_the_per_date_convention(result: BaselineResult) -> None:
    assert result.headline_ic == result.skill.per_date_mean


# --- Reproducibility --------------------------------------------------------


def test_two_runs_of_the_same_config_agree() -> None:
    first = run(INSTRUMENTS, BARS, CONFIG, CONSERVATIVE_V1, registered_at=STAMP)
    second = run(INSTRUMENTS, BARS, CONFIG, CONSERVATIVE_V1, registered_at=STAMP)
    assert first.experiment == second.experiment
    assert [s.net_return for s in first.summaries] == [s.net_return for s in second.summaries]
    assert first.headline_ic == second.headline_ic


def test_a_costlier_model_lowers_the_net_return() -> None:
    dear = CONSERVATIVE_V1.model_copy(update={"half_spread_bps": Decimal("50")})
    cheap_run = run(INSTRUMENTS, BARS, CONFIG, CONSERVATIVE_V1, registered_at=STAMP)
    dear_run = run(INSTRUMENTS, BARS, CONFIG, dear, registered_at=STAMP)
    assert dear_run.summaries[0].net_return < cheap_run.summaries[0].net_return


def test_too_little_history_is_refused_not_estimated() -> None:
    short = MarketSpec(symbols=(SymbolSpec("AAA"),), start=date(2024, 1, 1), end=date(2024, 3, 1))
    with pytest.raises(ValueError, match="too short"):
        run(generate_instruments(short), generate_bars(short), CONFIG, CONSERVATIVE_V1)


# --- Report -----------------------------------------------------------------


def test_the_report_states_the_trial_count_and_the_seal(result: BaselineResult) -> None:
    report = format_report(result)
    assert "trial_count" in report
    assert "SEALED" in report
    assert "never reads it" in report


def test_the_report_names_the_headline_convention(result: BaselineResult) -> None:
    report = format_report(result)
    assert "per-date, then averaged" in report
    assert "not the headline" in report


def test_the_report_says_win_rate_is_not_a_target(result: BaselineResult) -> None:
    assert "not a target" in format_report(result)


def test_the_report_shows_gross_and_net(result: BaselineResult) -> None:
    report = format_report(result)
    assert "gross" in report and "net" in report
    assert "cost drag" in report


# --- The command ------------------------------------------------------------


def test_the_command_refuses_to_invent_data(capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance #6 needs real data; until task 13 the command says so and exits."""
    code = main([])
    assert code == 1
    output = capsys.readouterr().out
    assert "No market data has been ingested" in output
    assert "task 13" in output


def test_the_makefile_exposes_one_command() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "experiment-baseline:" in makefile
    assert "python -m lab.experiments.baseline" in makefile


def test_the_runner_has_no_tuning_loop() -> None:
    """No search, no sweep, no 'pick the best fold'. A poor result is the finding."""
    source = (REPO_ROOT / "src" / "lab" / "experiments" / "baseline.py").read_text()
    tree = ast.parse(source)
    names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not names & {"grid_search", "optimize", "tune", "best_params"}


def test_experiment_config_rejects_an_impossible_top_n() -> None:
    with pytest.raises(ValueError, match="could never hold"):
        ExperimentConfig(**{**CONFIG.model_dump(), "top_n": 999, "max_names": 10})
