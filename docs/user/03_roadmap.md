# Roadmap

Releases map onto the week plan in [`../01_solo_agent_build.md`](../01_solo_agent_build.md).
Assume 10–15 focused hours per week; cut scope rather than quality if you have
less.

## Release 0.1 — Repo skeleton and data contracts ✅

*Weeks 1–2.*

The nine records the system exchanges, with the research and safety rules
enforced in their types rather than left to review.

- Python 3.12 project with pinned dependencies
- `src/`, `tests/`, `configs/`, `schemas/`, `docs/`
- Nine contracts: instrument, bar, feature snapshot, experiment, prediction,
  proposal, risk decision, order, fill
- Generated JSON Schemas with drift detection
- Secret hygiene enforced by tests
- **No** broker connection, no data ingestion, no dashboard

**Done when:** `make check` passes on a clean clone.

## Release 0.2 — Data and baseline ✅

*Weeks 3–4.*

- Dated 50-name universe with membership by date (`members_on`)
- Historical bars: committed fixture generator by default; optional Alpaca
  Market Data when paper keys are present
- Explicit information cutoff computed on every momentum snapshot
- Walk-forward splits with purge and embargo, applied in
  `lab.experiments.splits`
- Baselines: momentum vs. equal weight vs. cash vs. SPY
- One command: `make experiment-baseline`

**Done when:** the baseline runs from committed fixtures on a clean machine,
look-ahead tests pass against computed features, and holdout evaluation lives
in a separate module from training.

**Explicitly not in 0.2:** news, LLM calls, broker orders, dashboard,
regularized linear, MLflow, Parquet/DuckDB.

**Known gap:** the liquid-50 roster is a current-name list with listing dates
applied, not a point-in-time membership tape. Membership queries warn.

## Release 0.3 — Paper execution and risk ✅

*Weeks 5–6. Current release.* Risk limits stay **provisional placeholders**
(`owner_approved: false`) until [`../00_owner_mandate.md`](../00_owner_mandate.md)
§3 is completed. An unattended session refuses to start while they are
provisional. Edit `configs/risk.yaml` or `LAB_RISK_*` and restart to change a
limit; nothing mutates limits mid-session.

- Trade proposals generated from the 0.2 baseline sleeves
- Deterministic limits enforced: gross exposure, name cap, name count, daily
  loss, drawdown, stale data
- Kill switch (`LAB_KILL_SWITCH` or a flag file)
- Alpaca **paper** adapter with idempotent client order IDs; live host refused
- Reconciliation of local state against the broker after a restart
- Conservative internal shadow fills, deliberately worse than paper

**Done when:** replaying a proposal cannot create a second broker order, and a
restart reconciles cleanly.

**Explicitly not in 0.3:** news, LLM, Streamlit, Docker Compose, PostgreSQL,
Parquet/DuckDB, MLflow, regularized linear.

## Release 0.4 — News feature, narrowly ⬜

*Weeks 7–8.*

- One licensed news source already in the stack
- 50–100 event gold set, labelled by the owner
- TF-IDF / linear baseline as the control
- One LLM extractor, structured JSON only, invalid output quarantined
- Ablation: quant-only vs. quant+news on the same schedule and costs

**Done when:** the ablation is reported honestly, including a null result.

## Release 0.5 — Dashboard and unattended week ⬜

*Weeks 9–10.*

- Thin Streamlit view: positions, last decisions, reconciliation status, sleeve P&L
- Five consecutive paper sessions with no missing decision and no unreconciled state
- Backup and restore of the database volume, exercised once

**Done when:** five sessions run clean and a restore has actually been tested.

## Release 0.6 — Freeze and judge ⬜

*Weeks 11–12.*

- Code and configs frozen; no new features
- One-page report: what beat the control, what did not, trial count, known leaks
- Decision: **operate**, **revise**, or **stop**

**Done when:** the report exists and the decision is recorded.

## The go/no-go gate

At the freeze, the lab must be able to:

1. load a dated universe and bars;
2. run a reproducible baseline;
3. store predictions before outcomes;
4. submit paper orders without duplicates;
5. reconcile positions;
6. show results next to cash, benchmark, and equal weight.

If that works, there is a project. If it does not, **stop** — do not add scope
in the hope of rescuing it.

## Acceptance tests

Tracked across releases. These are the checks that keep results believable.

| # | Test | Status |
|---|---|---|
| 1 | Replaying the same proposal cannot create a second broker order | ✅ Shipped (0.3), end to end |
| 2 | Features computed at *t* cannot read prices after *t* | ✅ Shipped (0.2), computed features |
| 3 | Holdout evaluation is separate from training code | ✅ Shipped (0.2) |
| 4 | LLM outage degrades to quant-only; risk engine still runs | ⬜ 0.4 |
| 5 | `.env` is absent from git | ✅ Shipped (0.1) |
| 6 | `pytest` and a baseline experiment run on a clean machine from documented steps | ✅ Shipped (0.2) |

## Keeping this documentation true

Documentation is part of a change, not a follow-up to it. When a change alters
what the lab does, update the docs in the **same** change set:

| If you changed… | Update |
|---|---|
| A contract in `src/lab/contracts/` | `make schemas`, then [`../03_data_contracts.md`](../03_data_contracts.md) |
| What the lab can do | The status row in [`02_features.md`](02_features.md) |
| What ships when | This file |
| Install or run steps | [`04_getting_started.md`](04_getting_started.md) |
| A term a newcomer would not know | [`05_glossary.md`](05_glossary.md) |
| Scope, goals, or a non-goal | [`01_mission_and_goals.md`](01_mission_and_goals.md), and `AGENTS.md` if binding |
| Anything user-visible | `CHANGELOG.md` |

A feature is not shipped until its status row says so. The binding version of
this rule is in `AGENTS.md` under *Documentation duty*.
