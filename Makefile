.PHONY: install lint test schemas check experiment-baseline paper-session

install:          ## Create the venv and install the project with dev extras
	uv sync --extra dev

lint:             ## Static checks
	uv run ruff check .
	uv run ruff format --check .

test:             ## Unit tests
	uv run pytest

schemas:          ## Regenerate schemas/*.schema.json from the Pydantic contracts
	uv run python -m lab.contracts.export

experiment-baseline:  ## Reproduce the Release 0.2 baseline from committed fixtures
	uv run python -m lab.experiments.baseline

paper-session:  ## Attended paper session from the 0.2 sleeve (fake broker, no secrets)
	uv run python -m lab.execution --source fixture --broker fake

check: lint test  ## Everything CI would run
