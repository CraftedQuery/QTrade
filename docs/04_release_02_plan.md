# Release 0.2 working plan — data and baseline

Weeks 3–4 of [`01_solo_agent_build.md`](01_solo_agent_build.md). This is a living
document: update the status column as tasks land, so a new session can pick up
without re-deriving anything.

**Status:** approved 2026-08-30. Not started.
**Base:** `main` at the 0.1 merge.
**Scope discipline:** no news, no LLM calls, no dashboard, no broker execution.
Those are Releases 0.4, 0.5 and 0.3 respectively.

---

## Why the tasks are ordered this way

Only one task genuinely needs a data provider: the ingestion adapter (task 13).
Everything else can be built and tested against a deterministic **synthetic** bar
generator (task 2).

That ordering is the whole point. It means:

- work is never blocked on data rights, entitlements, or an API outage;
- every integrity test runs on data whose correct answer is known by
  construction — a synthetic series can contain a deliberate future leak, and the
  test can prove the pipeline refused it;
- the real adapter arrives last as a thin, swappable piece behind the same
  interface, so swapping providers later touches one module.

Build the pipeline first. Plug the real data in at the end.

---

## Status at a glance

| # | Task | Phase | Status | Closes |
|---|---|---|---|---|
| 1 | Data dependencies + `lab/store/` Parquet + DuckDB layer | A | ⬜ Not started | |
| 2 | Deterministic synthetic bar generator | A | ⬜ Not started | |
| 3 | Dated universe with membership by date | A | ⬜ Not started | |
| 4 | Walk-forward splitter with purge and embargo | A | ⬜ Not started | |
| 5 | Feature pipeline with derived information cutoff | B | ⬜ Not started | **#2** |
| 6 | Forward-return labels with explicit horizon | B | ⬜ Not started | |
| 7 | Baseline strategies + rebalance schedules | B | ⬜ Not started | |
| 8 | Regularized linear (ridge) model | B | ⬜ Not started | |
| 9 | Cost model `conservative_v1` | C | ⬜ Not started | |
| 10 | Metrics: rank IC, turnover, drawdown, net of cost | C | ⬜ Not started | |
| 11 | Holdout evaluation isolated from training | C | ⬜ Not started | **#3** |
| 12 | Experiment runner + `make experiment-baseline` | C | ⬜ Not started | **#6** |
| 13 | Alpaca historical bar adapter, 50 liquid names | D | ⬜ Not started | |

Status values: ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked

---

## Decisions

Locked on 2026-08-30. Do not re-litigate these without a reason that has changed;
record any change here with its date.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Alpaca** for historical bars | Already in the stack and entitled. Licensed API, not scraping. Provenance recorded on every bar. |
| D2 | Add `pandas`, `numpy`, `pyarrow`, `duckdb`, `scikit-learn` | Needed for tasks 1–10. Roughly triples the dependency surface; accepted deliberately, not by drift. |
| D3 | **Derive trading sessions from observed bars.** No calendar library | Purge and embargo in trading days vs calendar days differ materially. Deriving avoids a wrong-calendar bug class and adds no dependency. Revisit if a gap turns out to matter. |
| D4 | Rebalance **monthly (default), weekly, and daily** — configurable | Monthly is standard for momentum and keeps turnover from eating the edge before it can be measured. Weekly and daily are supported so the cost/turnover tradeoff can be measured rather than assumed. |
| D5 | **Defer MLflow to Release 0.3** | The append-only `Experiment` and `Prediction` records already give provenance and reproducibility. Standing up a tracking service now adds surface without answering a question we have. |

### Still open

- **Owner mandate §3 numbers.** Nothing in 0.2 enforces risk limits, so this does
  not block here. It stops being harmless the moment Release 0.3 lands.
  `configs/risk.yaml` currently ships provisional placeholders.
- **Alpaca paper credentials.** Needed for task 13 only. Tasks 1–12 run on
  synthetic data.

---

## Tasks

### Phase A — foundations

Nothing here needs a data provider.

#### 1. Data dependencies and the store layer

Add `pandas`, `numpy`, `pyarrow`, `duckdb`, `scikit-learn` (D2). Build
`src/lab/store/` to write and read `Bar` and `Instrument` records as partitioned
Parquet, queried through DuckDB.

**Done when:** bars round-trip losslessly including `Decimal` prices; re-ingesting
the same bars twice leaves the store unchanged; provenance (`source`,
`ingested_at`) survives the round trip.

**Traps:** Parquet has no native `Decimal`-to-`float` guard. Decide the on-disk
representation explicitly and assert the round trip, or prices will silently
become floats and reconciliation will drift later.

#### 2. Deterministic synthetic bar generator

A seeded generator producing realistic OHLCV for N symbols over a date range,
living in `tests/` (test-only, never shipped as a data source).

Must be able to produce, on demand: a symbol that delists mid-range, a gap in the
series, a split, and a deliberately planted future value that the pipeline is
expected to refuse.

**Done when:** the same seed yields byte-identical bars; every OHLC invariant in
the `Bar` contract holds; the generator can construct each edge case above.

**Why it comes second:** every later task depends on it, and it is what makes the
integrity tests provable rather than merely plausible.

#### 3. Dated universe

Build a universe from instruments plus a liquidity screen. `members_on(date)`
answers membership as of a past date, on top of `Instrument.was_listed_on`.

**Done when:** a delisted name appears in the universe before its delisting date
and not after; a universe built from a non-point-in-time source is flagged as
survivorship-biased, loudly and in the record, not in a comment.

**Traps:** the liquidity screen itself is a look-ahead risk. Screening on
average volume computed over the whole history selects names that were liquid
*later*. Screen on trailing data only, as of each date.

#### 4. Walk-forward splitter with purge and embargo

A pure function: date range, label horizon, purge, embargo → ordered
`(train, test)` folds. This is the integrity centrepiece of the release.

**Done when:** property tests prove no training index falls within `purge` of any
test index; the embargo span after each test fold is excluded from subsequent
training; folds are strictly ordered in time and never overlap; the function is
pure and total (no hidden clock, no I/O).

**Traps:** the purge must be applied in terms of the *label* window, not the
feature window. A 21-day forward label observed at *t* contaminates training data
up to *t*+21, not *t*.

### Phase B — features and models

#### 5. Feature pipeline with derived information cutoff — closes acceptance #2

Compute `FeatureSnapshot` records where `information_cutoff` is **derived from the
maximum `Bar.information_time` actually consumed**, never asserted by hand.

**Done when:** a test plants a bar dated after `as_of`, runs the pipeline, and
proves that bar did not influence the output; the derived cutoff equals the true
newest input in every case; momentum and volatility features are implemented.

**Traps:** this is the difference between a contract that *can* express the
invariant and a pipeline that *maintains* it. If the cutoff is passed in as an
argument, the guarantee is decorative. It must be computed by the code that reads
the bars.

#### 6. Forward-return labels

Labels with an explicit horizon, aware of the purge from task 4.

**Done when:** a label at *t* uses only data strictly after *t*; overlapping label
windows cannot appear on both sides of a fold boundary.

#### 7. Baseline strategies and rebalance schedules

Cash, buy-and-hold SPY, equal weight, and momentum. Each emits a `Proposal` per
rebalance date. Rebalance frequency is configurable — monthly default, weekly,
daily (D4).

**Done when:** each baseline produces valid `Proposal` records at each supported
frequency; weights are long-or-cash and never exceed 1; the schedule is derived
from observed trading sessions (D3), not from a hardcoded calendar.

#### 8. Regularized linear model

Ridge, trained per fold, emitting `Prediction` records **before** outcomes exist.

**Done when:** training touches only its fold's training window; predictions carry
their `DatasetSplit`; refitting on the same fold and seed reproduces the same
predictions.

### Phase C — evaluation

#### 9. Cost model `conservative_v1`

Spread plus commission applied to turnover. Assumptions written down, not
implied.

**Done when:** net-of-cost returns differ from gross; the cost of a given turnover
is reproducible and documented; the model is pessimistic by design, and says so.

#### 10. Metrics

Rank IC, turnover, drawdown, net-of-cost cumulative return, against the cash /
SPY / equal-weight comparators.

**Done when:** every baseline reports the full set; trial count travels with every
performance number; win rate may be reported but is never presented as a target.

#### 11. Holdout isolation — closes acceptance #3

A separate `lab.experiments.evaluate_holdout` entry point.

**Done when:** a test asserts the training module does not import the holdout
evaluator, transitively; the holdout date range is unreachable from the training
path; unsealing stamps `Experiment.holdout_unsealed_at`.

**Traps:** "separate function in the same module" does not satisfy this. The
point is that running training cannot, even by accident, read holdout data.

#### 12. Experiment runner — closes acceptance #6

`make experiment-baseline` / `uv run python -m lab.experiments.baseline`.
Registers the `Experiment` **before** any result is computed, runs the folds,
stores predictions, and emits the comparator table.

**Done when:** one documented command reproduces the baseline from raw inputs on a
clean machine; the experiment record exists before any number is produced;
re-running with the same config and seed reproduces the same results and the same
`config_hash`.

### Phase D — real data

#### 13. Alpaca historical bar adapter

Fetch daily bars for ~50 liquid U.S. names through Alpaca (D1). Paper
entitlement, licensed API, provenance on every record.

**Needs:** Alpaca paper credentials in `.env`. Not required for tasks 1–12.

**Done when:** 50 names ingest with `source` and `ingested_at` recorded; ingestion
is idempotent; the adapter sits behind the same interface as the synthetic
generator, so the pipeline cannot tell them apart; if the universe source is not
point-in-time, survivorship is flagged on the record.

**Traps:** do not let the adapter become the pipeline's only test path. The
synthetic generator stays the primary test fixture — it is deterministic and can
contain planted leaks that real data cannot.

---

## Acceptance tests

| # | Test | Before 0.2 | After 0.2 |
|---|---|---|---|
| 1 | Replaying a proposal cannot create a second broker order | 🟡 Contract level | 🟡 Contract level — end to end in 0.3 |
| 2 | Features at *t* cannot read prices after *t* | 🟡 Contract level | ✅ End to end (task 5) |
| 3 | Holdout evaluation separate from training code | ⬜ | ✅ (task 11) |
| 4 | LLM outage degrades to quant-only | ⬜ | ⬜ — 0.4 |
| 5 | `.env` absent from git | ✅ | ✅ |
| 6 | `pytest` and a baseline run on a clean machine | 🟡 Tests only | ✅ (task 12) |

---

## Working agreement

- One task, one reviewable change set. No drive-by refactors.
- `make check` passes before every commit; paste the output.
- Documentation ships with the code — see *Documentation duty* in `AGENTS.md`.
  Update the status table above in the same change set as the task.
- A poor result is a finding. Register the experiment, report the trial count,
  and do not search until the number flips.
- If look-ahead, data rights, or live-trading temptation appears: stop and ask.

## Resuming a session

1. Read this file's status table and the Decisions section.
2. `git fetch origin main && git checkout -B <branch> origin/main` if the last PR
   merged.
3. `make install && make check` to confirm a clean base.
4. Pick the lowest-numbered task that is not ✅ and whose dependencies are done.
