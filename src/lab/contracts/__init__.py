"""Data contracts for the AI Trading Lab.

These Pydantic models are the single source of truth for every record the lab
persists. The JSON Schema files in ``schemas/`` are generated from them by
``python -m lab.contracts.export`` and are checked for drift by the test suite;
edit the models here, never the generated JSON.
"""

from __future__ import annotations

from typing import Final

from lab.contracts.base import SCHEMA_VERSION, LabModel, LabRecord
from lab.contracts.execution import (
    ApprovedLine,
    Fill,
    LimitCheck,
    Order,
    Proposal,
    ProposalLine,
    RiskDecision,
    derive_client_order_id,
)
from lab.contracts.market import Bar, Instrument
from lab.contracts.research import Experiment, FeatureSnapshot, Prediction

CONTRACTS: Final[dict[str, type[LabRecord]]] = {
    "instrument": Instrument,
    "bar": Bar,
    "feature_snapshot": FeatureSnapshot,
    "experiment": Experiment,
    "prediction": Prediction,
    "proposal": Proposal,
    "risk_decision": RiskDecision,
    "order": Order,
    "fill": Fill,
}
"""The nine persisted contracts, keyed by their schema file stem.

The export CLI and the drift test both iterate this mapping, so a new contract
becomes a generated schema and a tested contract by being added here.
"""

__all__ = [
    "CONTRACTS",
    "SCHEMA_VERSION",
    "ApprovedLine",
    "Bar",
    "Experiment",
    "FeatureSnapshot",
    "Fill",
    "Instrument",
    "LabModel",
    "LabRecord",
    "LimitCheck",
    "Order",
    "Prediction",
    "Proposal",
    "ProposalLine",
    "RiskDecision",
    "derive_client_order_id",
]
