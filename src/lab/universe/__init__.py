"""Dated universe construction: which instruments were tradable, and when.

A universe built from *today's* constituent list contains only the companies
that survived. Every backtest run on it inherits that bias and looks better than
reality. This package answers membership **as of a date**, and refuses to answer
when the data cannot support the claim.
"""

from __future__ import annotations

from lab.universe.dated import (
    LiquidityScreen,
    Universe,
    UniverseMember,
    build_universe,
)

__all__ = [
    "LiquidityScreen",
    "Universe",
    "UniverseMember",
    "build_universe",
]
