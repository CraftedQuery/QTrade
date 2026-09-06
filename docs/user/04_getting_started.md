# Getting started

## What you can run today

Release 0.2 ships a dated 50-name universe, walk-forward splits with purge and
embargo, and a baseline experiment: momentum vs. cash vs. SPY vs. equal
weight. The default run uses committed fixtures and needs no secrets. It does
**not** place broker orders, call an LLM, or open a dashboard.

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
pass on a clean clone.

## Reproduce the baseline

```bash
make experiment-baseline
```

or:

```bash
uv run python -m lab.experiments.baseline
```

The command:

1. registers an experiment **before** any metric is computed
2. scores train and validation in `lab.experiments.train` (holdout stays sealed)
3. scores the holdout in `lab.experiments.holdout` only
4. writes JSON under `artifacts/experiments/<id>/`

Every printed number includes `trial_count`. Rank IC, turnover, drawdown, and
net-of-cost return are reported. Win rate is not. The liquid-50 roster is
**not** a point-in-time membership tape; the run prints a survivorship warning.

On this fixture seed, momentum holdout net (~+0.018) does not beat
equal-weight (~+0.023); `trial_count=1`. That is a finding, not a retune
target.

This is acceptance test #6.

## Configure

```bash
cp .env.example .env
```

`.env` is gitignored and must never be committed.

Leave the Alpaca variables empty unless you want optional licensed historical
bars. The default `--source fixture` path never reads them.

```bash
# optional, paper keys only — never required for make check or the fixture run
uv run python -m lab.experiments.baseline --source alpaca
```

When you fill keys in, use **paper** credentials only. Historical bars go to
`https://data.alpaca.markets`. There is deliberately no live trading endpoint
anywhere in this repository, and a test asserts it stays that way.

> **Never** paste keys into an agent prompt, a log, an issue, or a cloud VM.

## Changing the risk limits

The risk numbers are configuration, not code. They resolve in three layers,
each beating the one before:

```
built-in defaults  <  configs/risk.yaml  <  LAB_RISK_* environment variables
```

The baseline experiment does **not** read these limits. They exist for Release
0.3. Edit the file for a lasting change:

```yaml
# configs/risk.yaml
risk:
  max_position_weight: 0.03
  max_gross_exposure: 0.50
```

Or override for a single process:

```bash
LAB_RISK_MAX_POSITION_WEIGHT=0.03 uv run python -c "from lab.config import load_risk_limits; print(load_risk_limits())"
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
| `make experiment-baseline` | Reproduce the 0.2 baseline from committed fixtures |
| `make check` | Lint and test — everything CI would run |

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

Computed features use the same rule. `compute_momentum(..., as_of=t)` ignores
bars whose `information_time` is after `t`. See
[`../03_data_contracts.md`](../03_data_contracts.md) for all nine contracts.

## Repository layout

```
configs/     Experiment, universe, and risk configuration
docs/        Mandate, build plan, contract reference
docs/user/   This documentation
schemas/     Generated JSON Schemas — never hand-edit
src/lab/     The package (contracts, data, universe, features, experiments)
tests/       Contract, look-ahead, split, holdout-isolation, and hygiene tests
```

## Troubleshooting

**`make check` fails on `schemas/... is stale`** — you changed a contract but did
not regenerate. Run `make schemas` and commit the result.

**`ModuleNotFoundError: No module named 'lab'`** — install the project itself
(`make install`, or `pip install -e .`); `src/` is not on the path by default.

**Wrong Python version** — this project requires 3.12. `uv` reads
`.python-version` and will fetch it; a manual venv will not.

**`Alpaca keys are not set`** — you passed `--source alpaca` without paper keys.
Use the default fixture path, or export `ALPACA_API_KEY_ID` and
`ALPACA_API_SECRET_KEY`. Never commit `.env`.

## Next

- [Mission and goals](01_mission_and_goals.md) — why the lab works this way
- [Features](02_features.md) — what exists and what is planned
- [Roadmap](03_roadmap.md) — what ships when
