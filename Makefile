.PHONY: install lint test schemas check

install:          ## Create the venv and install the project with dev extras
	uv sync --extra dev

lint:             ## Static checks
	uv run ruff check .
	uv run ruff format --check .

test:             ## Unit tests
	uv run pytest

schemas:          ## Regenerate schemas/*.schema.json from the Pydantic contracts
	uv run python -m lab.contracts.export

check: lint test  ## Everything CI would run
