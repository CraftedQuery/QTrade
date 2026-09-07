# Changelog

All notable changes to the AI Trading Lab.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions correspond to the releases in [`docs/user/03_roadmap.md`](docs/user/03_roadmap.md).

## [Unreleased]

## [0.3.0] — 2026-09-07

Paper execution and risk (Weeks 5–6). Paper only. No news, no LLM, no
dashboard. Risk numbers stay **provisional** (`owner_approved: false`).

### Added
- Trade proposals from the 0.2 baseline sleeves (`lab.execution.proposals`).
  Proposal ids are a pure function of experiment, sleeve, and `as_of`.
- Deterministic risk engine (`lab.execution.risk`) that evaluates live
  proposals against `configs/risk.yaml` / `LAB_RISK_*`: kill switch, stale
  data, daily loss, drawdown, name cap, name count, gross exposure. Hard
  limits reject; name/gross/count limits reduce. Sells cannot open a short.
  Decision ids are a pure function of proposal id and `risk_config_hash`.
- Kill switch via `LAB_KILL_SWITCH` or a flag file (`LAB_KILL_SWITCH_PATH`).
- Alpaca **paper** adapter (`lab.execution.alpaca_paper`) with idempotent
  `client_order_id`. HTTPS to `paper-api.alpaca.markets` only; the live
  trading host is refused.
- In-process fake paper broker for fixture runs and tests (no secrets).
- Append-only JSONL ledger (`data/execution/`) so a restart can rebuild
  local state and compare it to the broker.
- Restart reconciliation. An unclean book refuses new orders.
- Conservative internal shadow fills (10 bps worse, 30s delay). Shadow
  fills never mutate the book and never overwrite broker paper fills.
- One command: `make paper-session` /
  `uv run python -m lab.execution`. Default is an **attended** fixture
  session against the fake broker. `--unattended` exits 3 while limits
  are provisional.
- End-to-end acceptance test #1: replaying a proposal cannot create a
  second broker order.

### Changed
- Package version `0.3.0`.
- `.env.example` documents the kill-switch variables.

### Security
- No live trading host is used as a default or as a requested URL.
- Paper keys stay in the environment; they are not written to artifacts.
- Unattended sessions cannot run on placeholder risk numbers.

### Known gaps
- `docs/00_owner_mandate.md` §3 is still blank. Limits remain provisional.
  Change them in `configs/risk.yaml` or `LAB_RISK_*` and restart; do not
  set `owner_approved: true` until the mandate is filled in.
- Fixture sessions use the research clock (`decided_at = as_of`). Daily
  bars versus a 300-second stale halt will reject under `--clock wall`
  unless a fresher mark is supplied.
- Parquet/DuckDB, PostgreSQL, Docker Compose, MLflow, and a regularized
  linear model were left out of this slice.
- The liquid-50 roster is still not a point-in-time membership tape.

## [0.2.0] — 2026-09-06

Data and baseline (Weeks 3–4). Paper research only. No broker orders, no news,
no LLM, no dashboard.

### Added
- Dated 50-name U.S. universe (`configs/universe/liquid50.yaml`) with
  membership by date. `GEHC` lists during the sample so membership is not a
  constant 50. The roster is **not** a point-in-time membership tape;
  `SurvivorshipWarning` is raised on first query.
- Deterministic synthetic daily bars from a committed fixture seed
  (`lab.data.generate`). Offline baseline runs need no secrets.
- Optional Alpaca Market Data historical fetch (`lab.data.alpaca`) when paper
  keys are present. HTTPS to `data.alpaca.markets` only; the live trading host
  is refused. Keys are never written to artifacts.
- Walk-forward split generator (`lab.experiments.splits`) that applies purge
  and embargo computationally, aligned with the `Experiment` contract.
- Momentum feature computer (`lab.features.momentum`) that filters on
  `Bar.information_time` and stamps `information_cutoff` with the newest
  consumed bar.
- Baselines: cash, SPY, equal weight, 21-session momentum (long the top half).
  Reports rank IC, turnover, drawdown, and net-of-cost return. Every number
  carries `trial_count`. Win rate is not computed.
- Holdout evaluation isolated in `lab.experiments.holdout`. Training code does
  not import it and cannot emit holdout metrics.
- One command: `make experiment-baseline` /
  `uv run python -m lab.experiments.baseline`.
- Look-ahead tests against *computed* features (acceptance test #2).
- Holdout-isolation tests (acceptance test #3).
- Configurable deterministic risk limits (`src/lab/config.py`,
  `configs/risk.yaml`) — already on main after 0.1.0; first tagged with 0.2.
  The baseline does not read them.

### Changed
- Package version `0.2.0`.
- `.env.example` documents optional paper keys for historical bars.
  Broker order placement remains Release 0.3.

### Security
- Default baseline path reads no credentials.
- Alpaca client allow-lists the market-data host and refuses
  `api.alpaca.markets`.
- `.env` remains gitignored; fixture runs do not require it.

### Known gaps
- The liquid-50 list is a current-name roster with listing dates applied, not
  a vendor PIT membership tape.
- On the committed fixture seed, holdout net is cash 0 / SPY negative /
  equal-weight ahead of momentum (~+0.023 vs ~+0.018); trial_count=1.
  A finding, not a retune target.
- Fixtures are synthetic, not redistributed vendor bars.
- Regularized linear, MLflow, and Parquet/DuckDB were left out of this slice.
- `docs/00_owner_mandate.md` still has no owner numbers. The baseline does not
  invent them; it does not read `configs/risk.yaml`.

## [0.1.0] — 2026-08-30

Repo skeleton and data contracts (Weeks 1–2). No broker connection, no data
ingestion, no dashboard.

### Added

**Project**
- Python 3.12 project with pinned dependencies (`uv.lock`, `requirements.lock`).
- `src/` layout with the `lab` package; `tests/`, `configs/`, `schemas/`, `docs/`.
- `Makefile` with `install`, `lint`, `test`, `schemas`, and `check`.
- `.env.example` with empty placeholders for Alpaca **paper** credentials only.
- `.gitignore` covering `.env`, caches, and generated data.

**Data contracts** — nine Pydantic models in `src/lab/contracts/`, all frozen,
UTC-aware, and strict about unknown fields:
- `Instrument` with listing and delisting dates for point-in-time membership.
- `Bar` with `information_time` at bar close, not bar open.
- `FeatureSnapshot` enforcing `information_cutoff <= as_of`.
- `Experiment` with walk-forward ordering, purge, embargo, trial count, and a
  sealed holdout.
- `Prediction`, deliberately without any outcome field.
- `Proposal` with non-negative weights and derived cash weight.
- `RiskDecision` with kill-switch and breached-limit invariants.
- `Order` with a one-member `paper` account mode and a deterministic
  `client_order_id`.
- `Fill` distinguishing broker paper fills from internal shadow fills.

**Schemas**
- Generated JSON Schemas in `schemas/`, exported by
  `python -m lab.contracts.export`, with drift detection in the test suite.

**Tests** — 138 tests covering contract invariants, research-integrity rules,
schema drift, and repository hygiene.

**Documentation**
- `docs/00_owner_mandate.md` — template; awaiting the owner's numbers.
- `docs/03_data_contracts.md` — contract reference.
- `docs/user/` — mission and goals, feature catalogue, roadmap, getting started,
  glossary.
- `AGENTS.md` — added a *Documentation duty* section requiring user docs to be
  updated in the same change set as the code.

### Changed
- Moved `01_solo_agent_build.md` and `02_coding_agent_choice.md` into `docs/`,
  matching the paths every other file already referenced.
- `README.md` rewritten for the working repository.

### Security
- Paper trading only. No live endpoint appears anywhere in the repository, and a
  test asserts it stays that way.
- `.env` is gitignored; a test asserts it is untracked (acceptance test #5).
- Tests scan tracked files for secret-shaped strings.

### Known gaps
- `docs/00_owner_mandate.md` has no values yet. Risk limits and position sizing
  (Release 0.3) are blocked until §3 is filled in.
- Acceptance tests #1 and #2 hold at the contract level only; they become end to
  end in Releases 0.3 and 0.2 respectively.

[Unreleased]: https://github.com/CraftedQuery/QTrade/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/CraftedQuery/QTrade/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CraftedQuery/QTrade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CraftedQuery/QTrade/releases/tag/v0.1.0
