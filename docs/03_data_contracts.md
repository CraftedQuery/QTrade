# Data contracts

Reference for the nine records the lab persists. Source of truth is
`src/lab/contracts/`; the JSON Schemas in `schemas/` are generated from it.

## How the contracts fit together

```
Instrument ──┐
             ├─> FeatureSnapshot ──> Prediction ──> Proposal ──> RiskDecision ──> Order ──> Fill
Bar ─────────┘         ▲                  ▲             ▲
                       └──────────────────┴─────────────┴──  Experiment
```

Read left to right, this is one decision's life: market data becomes features,
features become a prediction, predictions become a desired portfolio, the risk
engine rules on it, an approved decision becomes a paper order, and the broker
answers with fills. `Experiment` is registered before any of it runs and ties
the research records together.

## Design rules that apply to all nine

| Rule | Why |
|---|---|
| **Frozen** — no in-place edits | Records are append-only. History that can be rewritten is not evidence. |
| **`extra="forbid"`** | A renamed or dropped field fails at the boundary instead of silently becoming `None` halfway through a backtest. |
| **UTC-aware datetimes only** | A naive timestamp is ambiguous, and ambiguity about *when* is how look-ahead bias gets in. |
| **`Decimal` for money and quantities** | Float rounding in an order path produces share counts that do not reconcile. |
| **`schema_version` on every record** | Old records stay readable after the contract moves on. |

## The records

### `Instrument` — a tradable U.S. equity or ETF

Carries `listed_on` and `delisted_on` so universe membership can be
reconstructed as of a past date. `was_listed_on(day)` returns `False` when
`listed_on` is unknown: an unknown listing date cannot support a point-in-time
claim, and refusing is safer than guessing.

> **Survivorship.** A universe built from a *current* constituent list contains
> only the companies that survived. Backtests on it look better than reality.
> yfinance's current S&P membership is not a point-in-time source; flag it
> whenever it is used.

### `Bar` — one OHLCV window

Covers the half-open interval `[ts_start, ts_end)`. The bar's contents are not
knowable until it closes, so `information_time` returns `ts_end`. **Use
`information_time`, never `ts_start`, when deciding whether a bar may feed a
feature.** Treating a daily bar as available at its open date is one of the most
common look-ahead bugs, and it is invisible in the results.

`adjustment` records how corporate actions were applied, because silently mixing
adjusted and raw series manufactures returns that never existed.

### `FeatureSnapshot` — features for one instrument at one decision time

The central invariant of the lab lives here:

```
information_cutoff <= as_of
```

`as_of` is the moment a decision is being made. `information_cutoff` is the
timestamp of the newest input that fed these values. Constructing a snapshot
that violates this **raises**. This is the contract-level half of acceptance
test #2; the computational half arrives with the feature pipeline in Weeks 3–4.

### `Experiment` — a registered experiment

Registration happens *before* any result is viewed, which is why
`registered_at`, the three split boundaries, and `purge`/`embargo` are all
required at construction. Validators enforce walk-forward order: validation may
not overlap train, holdout may not overlap validation.

Two fields exist purely to keep the research honest:

- **`trial_count`** travels with the experiment, so no performance number can be
  reported without its search budget. Twenty trials and one good Sharpe is not
  a finding.
- **`holdout_unsealed_at`** records the one moment the holdout was looked at,
  and cannot precede registration. `holdout_is_sealed` is `True` until then.

### `Prediction` — one model output, stored before its outcome exists

There is deliberately **no** realised-return, outcome, or correctness field.
An outcome is a separate record joined on `prediction_id` later, so a stored
prediction can never be quietly revised once the future arrives. A test asserts
those field names stay absent.

### `Proposal` — a desired target portfolio

Weights are typed as `Weight`, bounded to `[0, 1]`. A negative weight is a
validation error, so **a short position is not representable**. Total invested
weight above 1 is rejected as leverage.

`cash_weight` is a derived property, not a stored field, so it can never
disagree with the position weights. An empty `lines` list is a valid all-cash
proposal.

### `RiskDecision` — the deterministic risk engine's verdict

Three invariants are enforced at construction:

- kill switch engaged → outcome **must** be `rejected`;
- any breached limit → outcome **cannot** be `approved`;
- rejected → `approved_lines` **must** be empty.

`risk_config_hash` pins the exact limit configuration used, so any decision can
be recomputed and compared. It comes from `RiskLimits.config_hash` in
`lab.config`; see [`user/04_getting_started.md`](user/04_getting_started.md#changing-the-risk-limits)
for how limits are configured. There is no field through which a model could alter
limits, sizing, or the kill switch — a test asserts no such field is ever added.

### `Order` — an order sent to the paper broker

`account_mode` is typed as `AccountMode`, an enum with **exactly one member**,
`paper`. Live trading is not merely discouraged; a live order cannot be
constructed.

`client_order_id` comes from `derive_client_order_id(decision_id, symbol, side)`,
a pure SHA-256 of its inputs — no clock, no counter, no random component.
Replaying the same decision yields the same key, so the broker rejects the
duplicate rather than opening a second position. This is the contract-level half
of acceptance test #1.

> Changing `derive_client_order_id` changes every future key. Treat it as part
> of the contract, not as an implementation detail.

### `Fill` — an execution against an order

`source` is either `broker_paper` (what the paper broker actually did) or
`internal_shadow` (the lab's own, deliberately more pessimistic estimate for the
same order). Both are stored. Shadow fills never overwrite broker fills, and the
two are never summed — keeping them separate is what makes the comparison
meaningful.

## Changing a contract

1. Edit the model in `src/lab/contracts/`.
2. Run `make schemas` to regenerate `schemas/*.schema.json`.
3. Run `make check`. `tests/test_schemas_in_sync.py` fails if you skip step 2.
4. Bump `SCHEMA_VERSION` in `base.py` for a breaking change.
5. Update `docs/user/` if the change alters what the lab does — see the
   documentation duty in `AGENTS.md`.
6. Commit the model change and the regenerated schema together.

Never hand-edit a file in `schemas/`.
