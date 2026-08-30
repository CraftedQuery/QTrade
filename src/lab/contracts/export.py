"""Generate ``schemas/*.schema.json`` from the Pydantic contracts.

Run with ``make schemas`` or ``python -m lab.contracts.export``. The output is
committed so that contract changes show up as a reviewable diff;
``tests/test_schemas_in_sync.py`` fails if the committed files fall behind.
"""

from __future__ import annotations

import json
from pathlib import Path

from lab.contracts import CONTRACTS
from lab.contracts.base import SCHEMA_VERSION, LabRecord

SCHEMA_DIR: Path = Path(__file__).resolve().parents[3] / "schemas"
"""Repository ``schemas/`` directory."""

SCHEMA_ID_BASE = "https://ai-trading-lab.local/schemas"


def build_schema(name: str, model: type[LabRecord]) -> dict[str, object]:
    """Return the JSON Schema document for one contract."""
    schema = model.model_json_schema(mode="serialization")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_ID_BASE}/{name}.schema.json",
        "x-contract-version": SCHEMA_VERSION,
        **schema,
    }


def render(name: str, model: type[LabRecord]) -> str:
    """Return the exact file contents for one contract's schema."""
    return json.dumps(build_schema(name, model), indent=2, sort_keys=True) + "\n"


def write_all(schema_dir: Path = SCHEMA_DIR) -> list[Path]:
    """Write every contract schema to ``schema_dir`` and return the paths."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in CONTRACTS.items():
        path = schema_dir / f"{name}.schema.json"
        path.write_text(render(name, model), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    """Entry point for ``python -m lab.contracts.export``."""
    for path in write_all():
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
