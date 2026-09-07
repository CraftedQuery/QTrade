# Features

Every capability identified for the lab, with its current status. This is the
catalogue future releases build against.

**Status key**

| Status | Meaning |
|---|---|
| ✅ Shipped | Built, tested, and usable today |
| 🟡 Partial | Contract or scaffolding exists; behaviour does not |
| ⬜ Planned | Identified and scheduled, not started |
| 🚫 Out of scope | Deliberately excluded until the owner opens it |

---

## 1. Data foundation

| Feature | Status | Release | Notes |
|---|---|---|---|
| Instrument contract with listing/delisting dates | ✅ Shipped | 0.1 | Enables point-in-time universe membership |
| OHLCV bar contract with explicit information time | ✅ Shipped | 0.1 | `information_time` = bar close, never bar open |
| Corporate-action adjustment tracking | ✅ Shipped | 0.1 | Recorded per bar; prevents mixing adjusted and raw series |
| Data provenance on every record | ✅ Shipped | 0.1 | `source` and ingestion timestamp |
| Dated liquid U.S. universe (50 names to start) | ✅ Shipped | 0.2 | `configs/universe/liquid50.yaml`; `members_on(day)` applies listing windows. Grows toward 100–300 only once a true PIT membership tape exists |
| Licensed historical bar ingestion | ✅ Shipped | 0.2 | Default is committed synthetic fixtures. Optional Alpaca Market Data (`data.alpaca.markets`, IEX) when paper keys are present. No scraping |
| Parquet + DuckDB local store | ⬜ Planned | later | Deferred; 0.3 uses an append-only JSONL ledger for execution records |
| Survivorship warning on non-point-in-time sources | ✅ Shipped | 0.2 | `SurvivorshipWarning` on every non-PIT roster, including this liquid-50 list |

## 2. Research integrity

The reason the project exists. Most of this is enforced in types rather than in
review comments.

| Feature | Status | Release | Notes |
|---|---|---|---|
| Look-ahead guard on features (`information_cutoff <= as_of`) | ✅ Shipped | 0.1 | Violating snapshots raise at construction |
| UTC-aware timestamps enforced everywhere | ✅ Shipped | 0.1 | Naive datetimes rejected |
| Experiment registration before results | ✅ Shipped | 0.1 | `registered_at` required at construction |
| Walk-forward split ordering enforced | ✅ Shipped | 0.1 | Validation cannot overlap train; holdout cannot overlap validation |
| Purge and embargo as required fields | ✅ Shipped | 0.1 | Not optional, not a comment |
| Trial count carried with every experiment | ✅ Shipped | 0.1 | No performance number without its search budget |
| Sealed holdout with unseal timestamp | ✅ Shipped | 0.1 | `holdout_is_sealed` until first viewed |
| Predictions immutable and outcome-free | ✅ Shipped | 0.1 | Outcomes join later; predictions are never revised |
| Append-only record semantics | ✅ Shipped | 0.1 | All contracts frozen |
| Purge/embargo applied in the split generator | ✅ Shipped | 0.2 | `lab.experiments.splits.assign` drops purged and embargoed timestamps |
| Look-ahead test suite over real features | ✅ Shipped | 0.2 | Acceptance test #2, against `compute_momentum`, not only construction |
| Holdout evaluation isolated from training code | ✅ Shipped | 0.2 | Acceptance test #3: `train.py` does not import `holdout.py` |
| MLflow experiment tracking | ⬜ Planned | later | Deferred; artifacts are JSON under `artifacts/experiments/` and `artifacts/execution/` |
| Rank IC, turnover, drawdown, net-of-cost reporting | ✅ Shipped | 0.2 | Win rate is explicitly not a target. Every number carries `trial_count` |

## 3. Strategy and baselines

| Feature | Status | Release | Notes |
|---|---|---|---|
| Cash baseline | ✅ Shipped | 0.2 | 100% cash, zero return |
| Benchmark ETF baseline | ✅ Shipped | 0.2 | 100% SPY when SPY is a member that day |
| Equal-weight baseline | ✅ Shipped | 0.2 | The control every result is judged against |
| Simple momentum / risk baseline | ✅ Shipped | 0.2 | 21-session momentum, long the top half equal-weight. No risk-engine sizing |
| Regularized linear model | ⬜ Planned | later | Not in the locked 0.3 acceptance |
| One-command baseline run | ✅ Shipped | 0.2 | `make experiment-baseline`. On the committed fixture seed, holdout net is cash 0 / SPY negative / equal-weight ahead of momentum — a finding, not a retune target |
| Static or risk-balanced sleeve weights | ⬜ Planned | 0.4 | No adaptive allocator |

## 4. Risk and execution

| Feature | Status | Release | Notes |
|---|---|---|---|
| Trade proposals from the 0.2 baseline | ✅ Shipped | 0.3 | Momentum / equal-weight / SPY / cash sleeves become a `Proposal` |
| Long-or-cash-only proposals | ✅ Shipped | 0.1 | Negative weights unrepresentable |
| Leverage rejection | ✅ Shipped | 0.1 | Invested weight above 1 raises |
| Derived cash weight | ✅ Shipped | 0.1 | Cannot disagree with position weights |
| Deterministic risk decision contract | ✅ Shipped | 0.1 | Kill switch forces rejection; breached limits cannot be approved |
| Risk config hashing | ✅ Shipped | 0.1 | Every decision is recomputable |
| No model authority over risk | ✅ Shipped | 0.1 | No field exists for it; a test keeps it that way |
| Paper-only account mode | ✅ Shipped | 0.1 | One-member enum; live orders unrepresentable |
| Deterministic idempotent client order IDs | ✅ Shipped | 0.1 | Pure function of the decision |
| Broker vs. shadow fill separation | ✅ Shipped | 0.1 | Never merged, never overwritten |
| Alpaca **paper** adapter | ✅ Shipped | 0.3 | `paper-api.alpaca.markets` only; live trading host refused. Fixture path uses an in-process fake broker |
| Configurable risk limits (file + env, hashed) | ✅ Shipped | 0.1 | `configs/risk.yaml`, `LAB_RISK_*`; provisional until the mandate is completed |
| Risk limits enforced against live proposals | ✅ Shipped | 0.3 | Gross exposure, name cap, name count, daily loss, drawdown, stale data. Hard limits reject; name/gross/count reduce |
| Stale-data halt | ✅ Shipped | 0.3 | Data older than `max_data_staleness_seconds` rejects the proposal |
| Kill switch | ✅ Shipped | 0.3 | `LAB_KILL_SWITCH` or a flag file. Engaged → every decision is rejected |
| Position reconciliation after restart | ✅ Shipped | 0.3 | Local JSONL ledger vs broker. Unclean books refuse new orders |
| Conservative internal shadow fills | ✅ Shipped | 0.3 | 10 bps worse plus 30s delay. Never mutate the book; never overwrite broker fills |
| Duplicate-order failure tests | ✅ Shipped | 0.3 | Acceptance test #1, end to end |

## 5. News and text (narrow)

| Feature | Status | Release | Notes |
|---|---|---|---|
| One licensed news source | ⬜ Planned | 0.4 | Only a source already entitled in the stack |
| 50–100 event gold set, owner-labelled | ⬜ Planned | 0.4 | |
| TF-IDF / linear text baseline | ⬜ Planned | 0.4 | The control the LLM must beat |
| One structured news-event feature | ⬜ Planned | 0.4 | |
| One primary LLM extractor, structured JSON only | ⬜ Planned | 0.4 | Invalid JSON is quarantined, never retried into acceptance |
| One challenger above a materiality threshold | ⬜ Planned | 0.4 | Not a model scoreboard |
| Quant-only vs. quant+news ablation | ⬜ Planned | 0.4 | Same schedule, same costs |
| Graceful degradation to quant-only on LLM outage | ⬜ Planned | 0.4 | Acceptance test #4 |

## 6. Operations

| Feature | Status | Release | Notes |
|---|---|---|---|
| Pinned, reproducible dependencies | ✅ Shipped | 0.1 | `uv.lock` and `requirements.lock` |
| Secret hygiene enforced by tests | ✅ Shipped | 0.1 | Acceptance test #5 |
| Generated JSON Schemas with drift detection | ✅ Shipped | 0.1 | `make schemas`; stale files fail the suite |
| Lint, format, and test in one command | ✅ Shipped | 0.1 | `make check` |
| Docker Compose local run | ⬜ Planned | later | Deferred; 0.3 is a local Python command |
| PostgreSQL record store | ⬜ Planned | later | 0.3 persists execution records as append-only JSONL |
| Thin Streamlit ops dashboard | ⬜ Planned | 0.5 | Positions, last decisions, reconciliation status, sleeve P&L |
| Five-session unattended paper run | ⬜ Planned | 0.5 | No missing decision, no unreconciled state |
| Backup and restore of the database volume | ⬜ Planned | 0.5 | |
| Freeze report generated from stored experiments | ⬜ Planned | 0.6 | |

## 7. Out of scope

Excluded on purpose. Each would add surface area without improving the answer
the lab exists to produce. Reopening any of them is the owner's decision, not an
agent's.

| Excluded | 🚫 |
|---|---|
| Live trading, or any path to it | 🚫 |
| Shorts, options, futures, crypto, leverage, extended hours | 🚫 |
| An "AI CIO" or any model that places orders | 🚫 |
| Contextual bandits, reinforcement learning | 🚫 |
| Multi-provider model routers, three-lab committees | 🚫 |
| China feeds, social and app-review pipelines | 🚫 |
| Dynamic Opportunity Graph as a live trading input | 🚫 |
| Graph database | 🚫 |
| NVIDIA signal-miner loops, NeMo distillation, GPU clusters | 🚫 |
| TradingView webhooks as an order path | 🚫 |
| Website scraping for market or alternative data | 🚫 |
| Training on human overrides before the owner approves the sample size | 🚫 |
| Commercialization, vendor discovery SOWs | 🚫 |
