"""Feature computation with a derived information cutoff.

The cutoff on every snapshot is computed from the bars the features actually
read, not supplied by the caller. See :mod:`lab.features.window`.
"""

from __future__ import annotations

from lab.features.compute import (
    MOMENTUM_V1,
    FeatureDef,
    FeatureSet,
    compute_snapshot,
    compute_snapshots,
    is_complete,
)
from lab.features.labels import Label, forward_return, label_symbols, overlaps_window
from lab.features.window import BarWindow

__all__ = [
    "MOMENTUM_V1",
    "BarWindow",
    "FeatureDef",
    "FeatureSet",
    "Label",
    "compute_snapshot",
    "compute_snapshots",
    "forward_return",
    "is_complete",
    "label_symbols",
    "overlaps_window",
]
