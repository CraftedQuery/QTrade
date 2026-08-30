"""Invariants that must hold for every persisted contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from lab.contracts import CONTRACTS, SCHEMA_VERSION
from tests.factories import FACTORIES

CONTRACT_NAMES = sorted(CONTRACTS)


def test_every_contract_has_a_factory() -> None:
    """A new contract must arrive with a valid example, or these tests are hollow."""
    assert set(FACTORIES) == set(CONTRACTS)


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_factory_builds_the_registered_type(name: str) -> None:
    assert isinstance(FACTORIES[name](), CONTRACTS[name])


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_records_are_frozen(name: str) -> None:
    """Records are append-only; editing one in place must fail."""
    record = FACTORIES[name]()
    field = next(iter(type(record).model_fields))
    with pytest.raises(ValidationError):
        setattr(record, field, None)


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_unknown_fields_are_rejected(name: str) -> None:
    """Schema drift must fail loudly at the boundary, not vanish silently."""
    record = FACTORIES[name]()
    payload: dict[str, Any] = record.model_dump()
    payload["totally_unexpected_field"] = "surprise"
    with pytest.raises(ValidationError):
        CONTRACTS[name].model_validate(payload)


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_schema_version_is_stamped(name: str) -> None:
    assert FACTORIES[name]().schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_all_datetimes_are_utc_aware(name: str) -> None:
    record = FACTORIES[name]()
    for field, value in record:
        if isinstance(value, datetime):
            assert value.tzinfo is not None, f"{name}.{field} is naive"
            assert value.utcoffset().total_seconds() == 0, f"{name}.{field} is not UTC"


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_round_trips_through_json(name: str) -> None:
    """Serialisation must be lossless; the record store persists JSON."""
    record = FACTORIES[name]()
    assert CONTRACTS[name].model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_naive_datetimes_are_rejected(name: str) -> None:
    """A naive timestamp is ambiguous and is refused everywhere."""
    model = CONTRACTS[name]
    record = FACTORIES[name]()
    datetime_fields = [field for field, value in record if isinstance(value, datetime)]
    assert datetime_fields, f"{name} has no datetime field to check"
    for field in datetime_fields:
        payload = record.model_dump()
        payload[field] = payload[field].replace(tzinfo=None)
        with pytest.raises(ValidationError, match="timezone-aware"):
            model.model_validate(payload)
