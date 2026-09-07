"""Trade proposals generated from the 0.2 baseline sleeves."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lab.contracts import Proposal
from lab.execution.proposals import derive_proposal_id, proposal_from_weights

AS_OF = datetime(2022, 8, 5, 21, 0, tzinfo=UTC)


def test_proposal_from_weights_is_long_or_cash() -> None:
    proposal = proposal_from_weights(
        proposal_id="prop-test",
        experiment_id="exp-001",
        strategy_version="momentum-1.0.0",
        as_of=AS_OF,
        created_at=AS_OF,
        weights={"SPY": 0.05, "AAPL": 0.05},
        prices={"SPY": Decimal("400"), "AAPL": Decimal("150")},
    )
    assert isinstance(proposal, Proposal)
    assert proposal.invested_weight == Decimal("0.10")
    assert proposal.cash_weight == Decimal("0.90")
    assert {line.symbol for line in proposal.lines} == {"SPY", "AAPL"}


def test_zero_and_missing_weights_become_cash() -> None:
    proposal = proposal_from_weights(
        proposal_id="prop-cash",
        experiment_id="exp-001",
        strategy_version="cash-1.0.0",
        as_of=AS_OF,
        created_at=AS_OF,
        weights={"SPY": 0.0},
        prices={"SPY": Decimal("400")},
    )
    assert proposal.lines == []
    assert proposal.cash_weight == Decimal(1)


def test_missing_reference_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="reference price"):
        proposal_from_weights(
            proposal_id="prop-x",
            experiment_id="exp-001",
            strategy_version="1.0.0",
            as_of=AS_OF,
            created_at=AS_OF,
            weights={"SPY": 0.05},
            prices={},
        )


def test_proposal_id_is_stable_for_the_same_sleeve_day() -> None:
    first = derive_proposal_id("exp-001", "momentum", AS_OF)
    second = derive_proposal_id("exp-001", "momentum", AS_OF)
    assert first == second
    assert first != derive_proposal_id("exp-001", "equal_weight", AS_OF)
