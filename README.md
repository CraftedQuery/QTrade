# AI Trading Lab

A **paper-trading research laboratory** for liquid U.S. equities and ETFs.

Success is a trustworthy experiment loop, not a promised return. The lab's
product is an honest answer about whether a signal works — including the answer
"it does not."

> **Paper trading only.** Long or cash only. Deterministic risk code has final
> authority over every order. No live brokerage credentials are ever requested,
> stored, or used.

## Status — Release 0.1: repo skeleton and data contracts

The nine records the system exchanges are defined, with the research and safety
rules enforced in their types rather than left to code review. The lab does not
yet load market data, run an experiment, or connect to a broker.

See [`docs/user/02_features.md`](docs/user/02_features.md) for the status of
every planned capability, and [`CHANGELOG.md`](CHANGELOG.md) for what landed.

## Quick start

```bash
make install    # uv sync --extra dev
make check      # ruff + pytest
```

Full instructions: [`docs/user/04_getting_started.md`](docs/user/04_getting_started.md).

## What makes this different

The contracts refuse to represent the mistakes that are hardest to spot in
backtest results:

| Guard | How |
|---|---|
| Look-ahead bias | A feature snapshot whose `information_cutoff` exceeds its `as_of` raises at construction |
| Bar timing | `Bar.information_time` is the bar's *close*, so a daily bar cannot be used on its own open |
| Survivorship | Instruments carry listing and delisting dates; membership is answered as of a date, and refuses to guess |
| Holdout leakage | The holdout is declared at registration and its unsealing is timestamped |
| Unreported search | `trial_count` is a required field on every experiment |
| Revised predictions | `Prediction` has no outcome field; outcomes join later as separate records |
| Shorts and leverage | Weights are bounded to `[0, 1]` and must sum to at most 1 |
| Model overreach | `RiskDecision` has no field an LLM could write to, and a test keeps it that way |
| Live trading | `AccountMode` has exactly one member, `paper` |
| Duplicate orders | `client_order_id` is a pure function of the risk decision |
| Optimistic fills | Broker paper fills and pessimistic internal shadow fills are stored separately and never merged |

## Documentation

**Users and operators** — [`docs/user/`](docs/user/README.md)

| Document | Read it for |
|---|---|
| [Mission and goals](docs/user/01_mission_and_goals.md) | Why the lab exists and what it will not do |
| [Features](docs/user/02_features.md) | Every identified feature with its status |
| [Roadmap](docs/user/03_roadmap.md) | What ships when, and the go/no-go gate |
| [Getting started](docs/user/04_getting_started.md) | Install and run what exists today |
| [Glossary](docs/user/05_glossary.md) | Terms used in the docs and the code |

**Builders and agents**

| Document | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Binding rules for any coding agent. If anything conflicts with it, it wins |
| [`CLAUDE.md`](CLAUDE.md) | Extra pointer for Claude Code |
| [`docs/00_owner_mandate.md`](docs/00_owner_mandate.md) | Owner's hours, budget, capital, drawdown — **not yet filled in** |
| [`docs/01_solo_agent_build.md`](docs/01_solo_agent_build.md) | The 8–12 week slice an agent may build |
| [`docs/02_coding_agent_choice.md`](docs/02_coding_agent_choice.md) | Grok Bot vs. Grok Build vs. Claude Code |
| [`docs/03_data_contracts.md`](docs/03_data_contracts.md) | Reference for all nine contracts |

## Layout

```
configs/     Experiment and runtime configuration (not read until Release 0.2)
docs/        Mandate, build plan, contract reference
docs/user/   User-facing documentation
schemas/     Generated JSON Schemas — never hand-edit
src/lab/     The package
tests/       Contract, schema-drift, and repo-hygiene tests
```

## Commands

| Command | Does |
|---|---|
| `make install` | Create the venv and install with dev extras |
| `make lint` | `ruff check` and `ruff format --check` |
| `make test` | Run the test suite |
| `make schemas` | Regenerate `schemas/*.schema.json` from the models |
| `make check` | Everything CI would run |

## Contributing

1. Read [`AGENTS.md`](AGENTS.md) first. It contains the binding constraints and
   the out-of-scope list.
2. Stay inside the current slice in [`docs/01_solo_agent_build.md`](docs/01_solo_agent_build.md).
3. Prefer the smallest change that satisfies it. No drive-by refactors.
4. Ship documentation with the code — see *Documentation duty* in `AGENTS.md`.
5. Run `make check` and paste the output.

**Before you ask for a better result:** a poor outcome is a finding, not a bug.
Searching until it flips is how a research lab becomes worthless. Register an
experiment and report the trial count.

## Next up

**Release 0.2 — data and baseline.** Licensed historical bars for ~50 liquid
names, a dated universe, walk-forward splits with purge and embargo, and a
momentum baseline judged against cash, SPY, and equal weight.

Release 0.3 (paper execution and risk) is blocked until
[`docs/00_owner_mandate.md`](docs/00_owner_mandate.md) §3 is filled in — position
sizing and risk limits need the owner's real numbers, not guessed ones.
