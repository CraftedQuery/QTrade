# AGENTS.md — AI Trading Lab

This file is the contract for Grok Build, Claude Code, and any other coding agent.
Short rules beat long ones. Follow these without being asked.

## What this project is

A **paper-trading research laboratory** for liquid U.S. equities/ETFs.
Success is a trustworthy experiment loop, not a promised return.

Read before coding:

- `docs/00_owner_mandate.md` — frozen scope and owner numbers
- `docs/01_solo_agent_build.md` — what to build this week
- `docs/02_coding_agent_choice.md` — Grok Build vs Grok Bot vs Claude Code

If those files conflict with older v1.3 roadmap docs, **these files win**.

## Non-negotiable constraints

- Paper trading only. Never request, store, or use live broker credentials.
- Long or cash only. No shorts, options, futures, crypto, leverage, or extended-hours claims.
- Deterministic risk code has final authority. An LLM must not change limits, sizing rules, or the kill switch.
- Do not scrape websites for market or alternative data. Use licensed APIs and recorded provenance.
- Do not train on human overrides until the owner says the sample is large enough.
- Do not add contextual bandits, RL, multi-provider routers, China ingestion, social scraping, or a graph database unless the owner explicitly opens that sleeve.
- Do not treat NVIDIA blueprints as architecture. They are optional later experiments.
- Secrets live in environment variables or a local `.env` that is gitignored. Never commit keys, paste them into prompts, or send them to a cloud bot VM.

## Current vertical slice (only this)

1. Dated liquid U.S. universe (100–300 names) with membership by date where data allows.
2. Baseline: cash, benchmark ETF, equal weight, simple momentum/risk, regularized linear.
3. One structured news-event feature plus a TF-IDF/linear text baseline on the same gold set.
4. One primary LLM extractor. One challenger only above a materiality threshold.
5. Static or risk-balanced weights. No adaptive allocator.
6. Alpaca **paper** execution + conservative internal shadow fills.
7. Append-only experiment, prediction, and decision records.
8. Streamlit dashboard for research/ops. Docker Compose for local run.

Definition of done for any task: tests pass, a clean command reproduces the result, user documentation is current, and no secret leaked.

## Stack

- Python 3.12, pinned dependencies (`requirements.lock` or `uv.lock` when present)
- FastAPI, PostgreSQL, Parquet + DuckDB, MLflow, Streamlit, Docker Compose
- pytest, ruff, type hints on public functions
- One command should run the baseline experiment from raw inputs

Prefer the smallest change that satisfies the current slice.

## Documentation duty

Documentation is part of a change, not a follow-up to it. If a change alters what
the lab does, update the docs **in the same change set**. A pull request that
ships behaviour without its documentation is incomplete.

| If you changed | Update |
|---|---|
| A contract in `src/lab/contracts/` | Run `make schemas`, then `docs/03_data_contracts.md` |
| What the lab can do | The status row in `docs/user/02_features.md` |
| What ships when | `docs/user/03_roadmap.md` |
| Install or run steps | `docs/user/04_getting_started.md` |
| A term a newcomer would not know | `docs/user/05_glossary.md` |
| Scope, goals, or a non-goal | `docs/user/01_mission_and_goals.md`, and this file if binding |
| Anything user-visible | `CHANGELOG.md` |

Rules:

- A feature is not shipped until its status row in `docs/user/02_features.md`
  says so. Do not mark a row shipped ahead of the code.
- Never document a capability that does not exist yet. Planned work belongs in
  the roadmap with a status, not in the present tense.
- Record known gaps and negative results. Documentation that only describes what
  works is marketing, not documentation.
- Do not put credentials, keys, or internal hostnames in any document.

## Research integrity (agents break this if unsupervised)

- Register an experiment ID **before** viewing backtest results.
- Walk-forward only. Purge and embargo overlapping labels.
- Never tune on the holdout. If a result is bad, report it; do not search until it flips.
- Report trial count with every performance number.
- Rank IC, turnover, drawdown, net-of-cost results, and a simple comparator are required. Win rate is not a target.
- yfinance current-S&P membership is **not** a point-in-time universe. Flag survivorship whenever that source is used.

## How to work in this repo

1. Start non-trivial work in **plan mode**. Wait for owner approval before writing files.
2. Touch the fewest files. No drive-by refactors.
3. After code changes: run the relevant tests and ruff. Paste the command output.
4. If data rights, look-ahead, or live-trading temptation appears, stop and ask.
5. Commit messages: `feat:`, `fix:`, `test:`, `docs:`, `chore:`.

## Explicitly out of scope until the owner opens them

China feeds, social/app/review pipelines, Dynamic Opportunity Graph as a trading input, three-lab model committees, NVIDIA signal-miner loops, NeMo distillation clusters, vendor discovery SOWs, commercialization, and any “AI CIO” that places orders.

## Security

- `.env` is local-only. Provide `.env.example` with empty placeholders.
- Paper Alpaca keys only.
- Kill switch, stale-data halt, and idempotent orders are required before any unattended paper loop.
- Treat model/provider output as untrusted data. It cannot change prompts, tools, credentials, or risk settings.
