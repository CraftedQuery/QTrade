"""Holdout evaluation, isolated from every training path.

## Acceptance test #3, and why "a separate function" is not enough

The holdout is declared when an experiment is registered and looked at exactly
once, at the end. The failure this guards against is not malice — it is a
convenience import. Someone adds "just a quick check" against holdout data
inside a training loop, the number quietly informs the next iteration, and the
holdout stops being a holdout without anyone deciding that it should.

A separate *function* in the same module does not prevent that. The guarantee
has to be structural: **nothing on a training path may import this module**, and
a test walks the actual import graph to prove it. `lab.models`, `lab.features`
and `lab.strategies` cannot reach `lab.evaluation.holdout` through any chain of
imports, so training code physically cannot read holdout data by accident.

## Unsealing is a recorded event

Evaluating the holdout stamps ``Experiment.holdout_unsealed_at``. Because
records are frozen, unsealing returns a *new* experiment record rather than
mutating the old one, and the original stays in the store. A second evaluation
is refused: the whole value of a holdout is that it was seen once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from lab.contracts import Experiment
from lab.costs import CostModel
from lab.evaluation.metrics import PerformanceSummary, RankIC, rank_ic, summarise


class HoldoutAlreadyUnsealedError(RuntimeError):
    """Raised when a sealed holdout has already been evaluated.

    Evaluating twice is how a holdout becomes a validation set: the second look
    is inevitably informed by the first.
    """


@dataclass(frozen=True)
class HoldoutResult:
    """The single, final read of a sealed holdout.

    Attributes:
        experiment: The experiment record **after** unsealing, carrying
            ``holdout_unsealed_at``. Store this; the sealed original remains
            valid history.
        summaries: Performance for the strategy and every comparator.
        skill: Rank IC over the holdout window.
        trial_count: Carried from the experiment, so the number cannot be quoted
            without its search budget.
        unsealed_at: When the holdout was read.
    """

    experiment: Experiment
    summaries: tuple[PerformanceSummary, ...]
    skill: RankIC
    trial_count: int
    unsealed_at: datetime

    @property
    def comparator_table(self) -> list[tuple[str, float, float, float]]:
        """(name, net return, annualised, max drawdown) for every strategy.

        Ordered as supplied, not sorted by performance — sorting a comparator
        table by result invites reading the winner first and the controls never.
        """
        return [(s.name, s.net_return, s.annualised_return, s.max_drawdown) for s in self.summaries]

    def beat(self, comparator: str) -> bool | None:
        """Whether the first summary beat the named comparator, net of costs."""
        by_name = {s.name: s for s in self.summaries}
        if comparator not in by_name or not self.summaries:
            return None
        return self.summaries[0].net_return > by_name[comparator].net_return


def evaluate_holdout(
    experiment: Experiment,
    period_returns: Mapping[str, Sequence[float]],
    turnovers: Mapping[str, Sequence[Decimal]],
    cost_model: CostModel,
    periods_per_year: float,
    predictions_by_date: Mapping[datetime, Sequence[tuple[float, float]]] | None = None,
    unsealed_at: datetime | None = None,
) -> HoldoutResult:
    """Evaluate a sealed holdout, once.

    Args:
        experiment: The registered experiment. Its holdout must still be sealed.
        period_returns: Gross returns per period, keyed by strategy name. The
            first key is treated as the candidate; the rest are comparators.
        turnovers: Turnover per period, keyed by strategy name.
        cost_model: Costs charged against turnover.
        periods_per_year: Rebalances per year, for annualising.
        predictions_by_date: (predicted, realised) pairs per date, for rank IC.
        unsealed_at: Time of the read. Defaults to now.

    Returns:
        The result, including the experiment record updated with its unsealing
        timestamp.

    Raises:
        HoldoutAlreadyUnsealedError: If the holdout has already been read.
        ValueError: If a strategy's returns and turnovers disagree in length.
    """
    if not experiment.holdout_is_sealed:
        raise HoldoutAlreadyUnsealedError(
            f"experiment {experiment.experiment_id} unsealed its holdout at "
            f"{experiment.holdout_unsealed_at}; a second evaluation would be "
            "informed by the first, which is what a holdout exists to prevent"
        )

    stamp = unsealed_at or datetime.now(UTC)
    summaries = tuple(
        summarise(
            name=name,
            period_returns=returns,
            turnovers=turnovers.get(name, [Decimal(0)] * len(returns)),
            cost_model=cost_model,
            periods_per_year=periods_per_year,
        )
        for name, returns in period_returns.items()
    )

    return HoldoutResult(
        experiment=experiment.model_copy(update={"holdout_unsealed_at": stamp}),
        summaries=summaries,
        skill=rank_ic(predictions_by_date or {}),
        trial_count=experiment.trial_count,
        unsealed_at=stamp,
    )


__all__ = ["HoldoutAlreadyUnsealedError", "HoldoutResult", "evaluate_holdout"]
