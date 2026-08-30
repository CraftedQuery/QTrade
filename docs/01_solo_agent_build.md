# Solo agent build (8–12 weeks)

This replaces the original 24-week multi-workstream calendar as the thing an agent is allowed to implement.

Vendor Phase 0/1 SOWs in the v1.3 package are **not** the solo plan. Do not recreate Kubernetes, NeMo, three model labs, or a seven-portfolio committee.

## Outcome

A local paper lab that can:

- load a dated universe and bars
- run a reproducible baseline
- store predictions before outcomes
- submit **paper** orders without duplicates
- reconcile positions
- show results next to cash / benchmark / equal weight

If that works, you have a project. If it does not, stop. Do not add China or a graph.

## Week plan

Assume 10–15 focused hours per week. Cut scope if you have less.

### Weeks 1–2 — repo and contracts

- Git repo from this pack + empty `src/`, `tests/`, `configs/`
- `.env.example`, `.gitignore`, pinned Python deps
- Schemas for: instrument, bar, feature snapshot, experiment, prediction, proposal, risk decision, order, fill
- No dashboard polish

**Agent prompt:** “Create the repo skeleton and schemas only. Do not connect Alpaca yet.”

### Weeks 3–4 — data and baseline

- Alpaca or other licensed historical bars for a small liquid set (start with 50 names, not 300)
- Explicit information cutoff on every feature
- Baseline experiment: momentum vs equal weight vs cash vs SPY
- Walk-forward with purge/embargo documented in code, not just comments
- One command: `make experiment-baseline` or `uv run python -m lab.experiments.baseline`

**Agent prompt:** “Implement the baseline experiment with tests for look-ahead. Do not add news or LLM calls.”

### Weeks 5–6 — paper execution and risk

- Trade proposal from the baseline
- Deterministic limits (gross exposure, name cap, daily loss, stale data)
- Alpaca paper adapter, idempotent client order IDs
- Reconcile local vs broker after restart
- Internal shadow fill that is *worse* than paper (spread + delay). Never overwrite broker paper fills.

**Agent prompt:** “Add paper execution and a kill switch. Write failure tests for duplicate orders and stale data. No live keys.”

### Weeks 7–8 — news feature, narrowly

- Ingest one licensed news source already in the stack (e.g. Alpaca/Benzinga if entitled)
- 50–100 event gold set you label yourself
- TF-IDF/linear baseline
- One LLM extractor, structured JSON only
- Ablation: quant-only vs quant+news on the same schedule and costs

**Agent prompt:** “Add one news feature and the TF-IDF control. Quarantine invalid JSON. Do not call three providers.”

### Weeks 9–10 — dashboard and unattended week

- Thin Streamlit: positions, last decisions, reconciliation status, sleeve P&L
- 5 consecutive paper sessions with no missing decision and no unreconciled state
- Backup/restore of the Postgres volume once

**Agent prompt:** “Add the ops dashboard and a session checklist. Do not redesign the data model.”

### Weeks 11–12 — freeze and judge

- Freeze code and configs. No new features.
- Write a one-page report: what beat the control, what did not, trial count, known leaks
- Decide: operate / revise / stop

**Agent prompt:** “Generate the freeze report from stored experiments. Do not retune anything.”

## What the agent must not build in this window

- Dynamic Opportunity Graph as live input
- China or social pipelines
- Bandits / RL
- TradingView webhooks as an order path
- Multi-model scoreboard
- NVIDIA formula miner closed loop
- NVIDIA distillation / NeMo / 2–6 GPU cluster
- Any UI that implies live profitability

## Acceptance tests an agent can implement

1. Replaying the same proposal cannot create a second broker order.
2. Features computed at t cannot read prices after t.
3. Holdout evaluation job is separate from training code.
4. LLM outage degrades to quant-only; risk engine still runs.
5. `.env` is absent from git.
6. `pytest` and a baseline experiment run on a clean machine from documented steps.
