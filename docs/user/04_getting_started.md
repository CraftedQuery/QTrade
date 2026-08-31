# Getting started

## What you can run today

Release 0.1 ships the data contracts and the checks that guard them. It does
**not** yet load market data, run an experiment, or connect to a broker. You can
install the project, run the test suite, and regenerate the JSON Schemas.

## Requirements

- Python 3.12 (`.python-version` pins it)
- [uv](https://docs.astral.sh/uv/) — or plain pip, see below
- git

## Install

```bash
git clone <your-repo-url> ai-trading-lab
cd ai-trading-lab
make install
```

`make install` runs `uv sync --extra dev`, which creates `.venv/` and installs
the exact versions in `uv.lock`.

### Without uv

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

`requirements.lock` is exported from `uv.lock`, so both paths install the same
versions.

## Verify

```bash
make check
```

That runs `ruff check`, `ruff format --check`, and `pytest`. Everything should
pass on a clean clone. This is acceptance test #6 for the current release.

## Configure

```bash
cp .env.example .env
```

`.env` is gitignored and must never be committed.

Leave the Alpaca variables empty for now — nothing reads them until Release 0.3.
When you do fill them in, use **paper** credentials only. There is deliberately
no live endpoint anywhere in this repository, and a test asserts it stays that
way.

> **Never** paste keys into an agent prompt, a log, an issue, or a cloud VM.

## Changing costs and experiment settings

Both follow the same three-layer pattern as the risk limits:

```
built-in defaults  <  configs/<file>.yaml  <  LAB_<AREA>_* environment variables
```

| Setting | File | Environment prefix |
|---|---|---|
| Risk limits | `configs/risk.yaml` | `LAB_RISK_` |
| Transaction costs | `configs/costs.yaml` | `LAB_COST_` |
| Experiment | `configs/experiment.yaml` | `LAB_EXPERIMENT_` |

Costs are configuration rather than a constant because they decide whether a
strategy looks viable. The defaults are pessimistic on purpose, and a model with
zero spread *and* zero slippage is rejected at construction.

Experiment settings are hashed into the experiment record, so changing one is
visible:

```bash
LAB_EXPERIMENT_MAX_NAMES=100 make experiment-baseline
```

That is a **different experiment**, not the same one with more data — the config
hash changes, and so does the experiment id.

## Changing the risk limits

The risk numbers are configuration, not code. They resolve in three layers, each
beating the one before:

```
built-in defaults  <  configs/risk.yaml  <  LAB_RISK_* environment variables
```

Edit the file for a lasting change:

```yaml
# configs/risk.yaml
risk:
  max_position_weight: 0.03
  max_gross_exposure: 0.50
```

Or override for a single run:

```bash
LAB_RISK_MAX_POSITION_WEIGHT=0.03 uv run python -m lab.experiments.baseline
```

Read them from Python:

```python
from lab.config import load_risk_limits

limits = load_risk_limits()
limits.max_position_weight   # Decimal('0.05')
limits.is_provisional        # True until the owner mandate is completed
limits.config_hash           # stamped onto every RiskDecision
```

Values are fractions, not percentages: 2% is `0.02`.

Incoherent combinations are rejected at load time rather than at trade time —
a position cap above the gross cap, a daily loss limit above the drawdown stop,
or a name count that cannot reach the gross target.

> Limits are read once at startup and never change mid-session. Every risk
> decision stores a hash of the limits it was checked against, so it stays
> recomputable. Change a limit and restart; the hash changes with it.

The shipped values are conservative placeholders. Replace them with your own in
[`../00_owner_mandate.md`](../00_owner_mandate.md) §3, copy them into
`configs/risk.yaml`, and set `owner_approved: true`.

## Commands

| Command | Does |
|---|---|
| `make install` | Create the venv and install with dev extras |
| `make lint` | `ruff check` and `ruff format --check` |
| `make test` | Run the test suite |
| `make schemas` | Regenerate `schemas/*.schema.json` from the models |
| `make check` | Lint and test — everything CI would run |
| `make experiment-baseline` | Run the baseline experiment (refuses until real data is ingested) |

## Using the contracts

```python
from datetime import UTC, datetime, timedelta
from lab.contracts import FeatureSnapshot

as_of = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)

snapshot = FeatureSnapshot(
    snapshot_id="snap-1",
    feature_set="momentum_v1",
    feature_set_version="1.0.0",
    symbol="SPY",
    as_of=as_of,
    information_cutoff=as_of - timedelta(minutes=5),
    values={"mom_21d": 0.031},
    computed_at=as_of,
)
```

Push the cutoff past the decision time and construction fails:

```python
FeatureSnapshot(..., information_cutoff=as_of + timedelta(seconds=1))
# ValidationError: look-ahead: information_cutoff ... is after as_of ...
```

That is the whole idea. The contracts refuse to represent the mistakes that are
hardest to spot in results. See
[`../03_data_contracts.md`](../03_data_contracts.md) for all nine.

## Repository layout

```
configs/     Experiment and runtime configuration (not read until 0.2)
docs/        Mandate, build plan, contract reference
docs/user/   This documentation
schemas/     Generated JSON Schemas — never hand-edit
src/lab/     The package
tests/       Contract, schema-drift, and repo-hygiene tests
```

## Troubleshooting

**`make check` fails on `schemas/... is stale`** — you changed a contract but did
not regenerate. Run `make schemas` and commit the result.

**`ModuleNotFoundError: No module named 'lab'`** — install the project itself
(`make install`, or `pip install -e .`); `src/` is not on the path by default.

**Wrong Python version** — this project requires 3.12. `uv` reads
`.python-version` and will fetch it; a manual venv will not.

## Next

- [Mission and goals](01_mission_and_goals.md) — why the lab works this way
- [Features](02_features.md) — what exists and what is planned
- [Roadmap](03_roadmap.md) — what ships when
