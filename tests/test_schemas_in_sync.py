"""The committed JSON Schemas must match the Pydantic models.

The models are the source of truth. These files are generated so that contract
changes appear as a reviewable diff and so non-Python consumers can validate lab
records. If this test fails, run ``make schemas`` and commit the result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab.contracts import CONTRACTS
from lab.contracts.export import SCHEMA_DIR, render

CONTRACT_NAMES = sorted(CONTRACTS)


def test_schema_dir_is_inside_the_repo() -> None:
    assert SCHEMA_DIR.name == "schemas"
    assert (SCHEMA_DIR.parent / "pyproject.toml").exists()


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_schema_file_exists(name: str) -> None:
    assert (SCHEMA_DIR / f"{name}.schema.json").is_file()


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_schema_matches_model(name: str) -> None:
    committed = (SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
    assert committed == render(name, CONTRACTS[name]), (
        f"schemas/{name}.schema.json is stale; run `make schemas` and commit the result"
    )


def test_no_orphan_schema_files() -> None:
    """A schema whose model was removed would otherwise linger unnoticed."""
    on_disk = {path.name.removesuffix(".schema.json") for path in SCHEMA_DIR.glob("*.schema.json")}
    assert on_disk == set(CONTRACTS)


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_schema_is_valid_json_with_an_id(name: str) -> None:
    document = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert document["$id"].endswith(f"/{name}.schema.json")
    assert document["$schema"].startswith("https://json-schema.org/")
    assert document["additionalProperties"] is False


def test_generated_files_are_not_hand_edited(tmp_path: Path) -> None:
    """Regenerating into a clean directory reproduces the committed bytes exactly."""
    from lab.contracts.export import write_all

    for path in write_all(tmp_path):
        name = path.name.removesuffix(".schema.json")
        assert path.read_text(encoding="utf-8") == (SCHEMA_DIR / f"{name}.schema.json").read_text(
            encoding="utf-8"
        )
