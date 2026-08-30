# Changelog

All notable changes to the AI Trading Lab.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions correspond to the releases in [`docs/user/03_roadmap.md`](docs/user/03_roadmap.md).

## [Unreleased]

### Added
- `lab.store` — Parquet record store queried through DuckDB, with `BarStore` and
  `InstrumentStore`. Prices and quantities are stored as exact decimals
  (`decimal128(38, 12)`); a value with more precision than that raises on write
  rather than truncating silently.
- Writes are upserts on the record's natural key: re-writing identical data
  touches no file at all, a corrected bar replaces the stored one, and a stale
  re-fetch (older `ingested_at`) is refused so it cannot revert a correction.
- Data dependencies: `pyarrow`, `duckdb`, `numpy`, `pandas`, `scikit-learn`.
  The last three are unused until tasks 5–10 of the Release 0.2 plan; they are
  resolved now so later tasks do not each churn the lock file.
- 32 tests covering decimal fidelity, timestamp precision, idempotency,
  corrections, filtering, and layout.
- `tests/synthetic.py` — deterministic synthetic market data. Seeded per symbol
  so adding a symbol leaves the others untouched, with knobs for the edge cases
  the integrity tests need: mid-range delisting, series gaps, raw-price splits,
  and bars past a decision time. A test asserts no `lab.*` module imports it, so
  synthetic prices cannot reach a real experiment.
- 22 tests covering determinism (including across processes), OHLC validity,
  session handling, and each edge case.
- `lab.universe` — point-in-time universe construction. Membership comes from
  each instrument's listing window, and the trailing liquidity screen reads only
  bars whose `information_time` falls at or before the evaluation date, so a name
  qualifies only once it has already traded enough. A universe whose instruments
  lack listing dates is marked `survivorship_biased` on the record.
- 17 tests, including one that builds the same universe from the full history and
  from a future-truncated history and requires past membership to be identical.
- `lab.evaluation.splits` — walk-forward folds with purge and embargo, counted in
  trading sessions rather than calendar days. Purge compares a training row's
  full label window against the test start, so a forward label cannot reach
  across the boundary. A configuration with zero horizon, purge and embargo is
  rejected as a plain time split.
- 448 split assertions across a 144-configuration grid, plus a test that proves
  the naive split does leak so the purge test cannot pass vacuously.
- `lab.features` — feature computation whose `information_cutoff` is **derived**
  from the bars actually read, via `BarWindow`, rather than supplied by the
  caller. Closes acceptance test #2 end to end. Feature set `momentum_v1`:
  21- and 63-session momentum, 12-1 skip-month momentum, and 21-session realized
  volatility. A missing lookback yields `None`, never an imputed value.
- 26 tests, including one that computes snapshots from the full history and from
  a future-truncated history and requires the records to be identical.
- `lab.features.labels` — forward-return labels carrying `known_at`, the instant
  the outcome could first have been observed. That timestamp is what makes the
  splitter's purge computable rather than notional. A horizon running past the
  available history yields nothing rather than a return over a shorter span.
- 17 tests, including one pinning that a label's entry price is the same close a
  feature computed at the same instant would have seen.

### Added (earlier in Unreleased)
- `docs/04_release_02_plan.md` — the Release 0.2 task breakdown (13 tasks across
  four phases), a status table to update as work lands, the locked decisions with
  their rationale, and per-task definitions of done.
- `schedule.rebalance` in `configs/base.yaml`: monthly (default), weekly, or daily.

### Changed
- Release 0.2 will source bars from **Alpaca**.
- MLflow moved from Release 0.2 to 0.3. The append-only experiment and prediction
  records already provide provenance and reproducibility, so a tracking service
  does not yet answer a question we have.
- Trading sessions will be derived from observed bars rather than a calendar
  library, avoiding a wrong-calendar bug class in purge and embargo.

### Added (0.1 follow-up)
- Configurable deterministic risk limits (`src/lab/config.py`, `configs/risk.yaml`).
  Limits resolve from built-in defaults, then the config file, then `LAB_RISK_*`
  environment variables, so the owner's numbers can be changed without touching
  code. Incoherent combinations are rejected at load time.
- `RiskLimits.config_hash` — a deterministic hash of the numeric limits, for
  `RiskDecision.risk_config_hash`. Approving unchanged numbers does not change
  the hash, so decisions stay comparable across that event.
- `RiskLimits.is_provisional` — the lab can tell whether it is running on the
  owner's real numbers or on placeholders.
- `LAB_RISK_*` placeholders in `.env.example`.
- 22 tests covering layering, coercion, invariants, and hashing.

### Changed
- `docs/00_owner_mandate.md` §3 now maps each row to its `configs/risk.yaml` key
  and shows the provisional default. Filling it in is no longer a hard blocker
  for Release 0.3 — the lab runs on flagged placeholders until then.
- Added `pyyaml` as a runtime dependency (needed to read `configs/risk.yaml`).

### Security
- Risk limits are read once at startup and are never mutable at runtime. A limit
  that could move mid-session would make the audit trail meaningless, and no
  model output may reach them: `RiskLimits` exposes no mutation method.

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

[Unreleased]: https://github.com/CraftedQuery/QTrade/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CraftedQuery/QTrade/releases/tag/v0.1.0
