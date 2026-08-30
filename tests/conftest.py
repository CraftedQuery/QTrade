"""pytest configuration for the contract test suite."""

from __future__ import annotations

import pytest

from tests.factories import FACTORIES


@pytest.fixture
def factories() -> dict[str, object]:
    """All contract factories, keyed by schema name."""
    return dict(FACTORIES)
