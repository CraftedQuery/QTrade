.PHONY: install lint test schemas experiment-baseline check

install:          ## Create the venv and install the project with dev extras
	uv sync --extra dev

lint:             ## Static checks
	uv run ruff check .
	uv run ruff format --check .

test:             ## Unit tests
	uv run pytest

schemas:          ## Regenerate schemas/*.schema.json from the Pydantic contracts
	uv run python -m lab.contracts.export

experiment-baseline:  ## Run the baseline experiment end to end
	uv run python -m lab.experiments.baseline

check: lint test  ## Everything CI would run
