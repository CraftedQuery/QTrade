"""Acceptance test #3: holdout evaluation is isolated from training code.

The structural half of this file walks the real import graph. A separate
function in the same module would not satisfy the requirement; the point is that
training code physically cannot reach holdout data, even by accident.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lab.costs import CONSERVATIVE_V1
from lab.evaluation.holdout import (
    HoldoutAlreadyUnsealedError,
    evaluate_holdout,
)
from tests.factories import make_experiment

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = REPO_ROOT / "src" / "lab"
HOLDOUT_MODULE = "lab.evaluation.holdout"

# Anything a model fit or a strategy decision runs through.
TRAINING_MODULES = ("lab.models", "lab.features", "lab.strategies")

RETURNS = {
    "momentum": [0.02, -0.01, 0.03, 0.01],
    "equal_weight": [0.01, 0.00, 0.02, 0.01],
    "cash": [0.0, 0.0, 0.0, 0.0],
}
TURNOVERS = {
    "momentum": [Decimal("1.2")] * 4,
    "equal_weight": [Decimal("0.1")] * 4,
    "cash": [Decimal("0")] * 4,
}


# --- The structural guarantee -----------------------------------------------


def module_name(path: Path) -> str:
    relative = path.relative_to(LAB_ROOT).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(["lab", *parts])


def direct_imports(path: Path) -> set[str]:
    """Every lab module this file imports directly."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("lab"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("lab"):
            found.add(node.module)
            found.update(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if (LAB_ROOT / Path(*node.module.split(".")[1:]) / f"{alias.name}.py").exists()
            )
    return found


def import_graph() -> dict[str, set[str]]:
    return {module_name(path): direct_imports(path) for path in LAB_ROOT.rglob("*.py")}


def reachable_from(start: str, graph: dict[str, set[str]]) -> set[str]:
    """Every lab module reachable from ``start`` through any chain of imports."""
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        for target in graph.get(current, set()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


@pytest.mark.parametrize("training_module", TRAINING_MODULES)
def test_training_code_cannot_reach_the_holdout_evaluator(training_module: str) -> None:
    """Acceptance #3. Enforced on the real import graph, transitively."""
    graph = import_graph()
    assert training_module in graph, f"{training_module} not found in the package"
    reached = reachable_from(training_module, graph)
    assert HOLDOUT_MODULE not in reached, (
        f"{training_module} can reach {HOLDOUT_MODULE} through imports: "
        f"{sorted(reached & {HOLDOUT_MODULE})}"
    )


def test_the_evaluation_package_does_not_re_export_the_holdout() -> None:
    """A convenience re-export would silently pull it onto every training path."""
    import lab.evaluation

    assert "holdout" not in lab.evaluation.__all__
    assert not hasattr(lab.evaluation, "evaluate_holdout")


def test_the_import_graph_check_can_actually_fail() -> None:
    """Keeps the guarantee honest: prove the walker finds a real chain."""
    graph = import_graph()
    assert HOLDOUT_MODULE in graph
    assert "lab.evaluation.metrics" in reachable_from(HOLDOUT_MODULE, graph), (
        "the walker found no imports from the holdout module, so the isolation "
        "test above may be passing vacuously"
    )


def test_the_holdout_module_exists_on_its_own() -> None:
    assert (LAB_ROOT / "evaluation" / "holdout.py").is_file()


# --- Unsealing is recorded and happens once ---------------------------------


def test_evaluating_stamps_the_unsealing_time() -> None:
    experiment = make_experiment()
    assert experiment.holdout_is_sealed

    stamp = datetime(2026, 8, 31, tzinfo=UTC)
    result = evaluate_holdout(
        experiment, RETURNS, TURNOVERS, CONSERVATIVE_V1, 12, unsealed_at=stamp
    )

    assert result.experiment.holdout_unsealed_at == stamp
    assert not result.experiment.holdout_is_sealed


def test_the_original_record_is_not_mutated() -> None:
    """Records are frozen; unsealing returns a new one and history survives."""
    experiment = make_experiment()
    evaluate_holdout(experiment, RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)
    assert experiment.holdout_is_sealed


def test_a_second_evaluation_is_refused() -> None:
    """The second look is inevitably informed by the first."""
    unsealed = make_experiment(holdout_unsealed_at=datetime(2026, 8, 31, tzinfo=UTC))
    with pytest.raises(HoldoutAlreadyUnsealedError, match="second evaluation"):
        evaluate_holdout(unsealed, RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)


def test_re_evaluating_the_returned_experiment_is_refused() -> None:
    result = evaluate_holdout(make_experiment(), RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)
    with pytest.raises(HoldoutAlreadyUnsealedError):
        evaluate_holdout(result.experiment, RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)


# --- The result -------------------------------------------------------------


def test_every_comparator_is_summarised() -> None:
    result = evaluate_holdout(make_experiment(), RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)
    assert [s.name for s in result.summaries] == ["momentum", "equal_weight", "cash"]


def test_the_trial_count_travels_with_the_result() -> None:
    """No performance number without the search budget that produced it."""
    experiment = make_experiment(trial_count=17)
    assert evaluate_holdout(experiment, RETURNS, TURNOVERS, CONSERVATIVE_V1, 12).trial_count == 17


def test_the_comparator_table_is_not_sorted_by_performance() -> None:
    """Sorting invites reading the winner first and the controls never."""
    result = evaluate_holdout(make_experiment(), RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)
    assert [row[0] for row in result.comparator_table] == list(RETURNS)


def test_beating_a_comparator_is_measured_net_of_costs() -> None:
    result = evaluate_holdout(make_experiment(), RETURNS, TURNOVERS, CONSERVATIVE_V1, 12)
    assert result.beat("cash") is not None
    assert result.beat("nonexistent") is None


def test_high_turnover_can_lose_to_a_cheaper_comparator() -> None:
    """The whole reason costs are charged before comparing."""
    # churn earns more gross (0.32% vs 0.30% a period) but pays 10 bps a period
    # in costs against equal weight's 0.25 bp, which reverses the ranking.
    returns = {"churn": [0.0032] * 24, "equal_weight": [0.0030] * 24}
    turnovers = {"churn": [Decimal("2.0")] * 24, "equal_weight": [Decimal("0.05")] * 24}
    result = evaluate_holdout(make_experiment(), returns, turnovers, CONSERVATIVE_V1, 12)

    gross = {s.name: s.gross_return for s in result.summaries}
    assert gross["churn"] > gross["equal_weight"]
    assert result.beat("equal_weight") is False


def test_rank_ic_is_computed_when_pairs_are_supplied() -> None:
    day = datetime(2024, 1, 1, tzinfo=UTC)
    pairs = {day + timedelta(days=i): [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)] for i in range(6)}
    result = evaluate_holdout(
        make_experiment(), RETURNS, TURNOVERS, CONSERVATIVE_V1, 12, predictions_by_date=pairs
    )
    assert result.skill.per_date_mean == pytest.approx(1.0)
    assert result.skill.dates == 6
