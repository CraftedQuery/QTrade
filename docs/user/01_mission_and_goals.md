# Mission and goals

## Mission

**Find out whether a disciplined, systematic research process can produce a
trading signal that survives honest evaluation — and be willing to conclude that
it cannot.**

The AI Trading Lab is a paper-trading research laboratory for liquid U.S.
equities and ETFs. Its product is not a strategy. Its product is a *trustworthy
answer* about whether a strategy works, produced by machinery that makes
self-deception difficult.

## The problem this exists to solve

Backtests are easy to make look good. Almost every way of making one look good
by accident is invisible in the result:

| Failure | What it looks like | What it actually is |
|---|---|---|
| Look-ahead bias | Excellent Sharpe | The model saw data that did not exist yet |
| Survivorship bias | Steady outperformance | The universe silently excludes companies that failed |
| Holdout leakage | Robust out-of-sample result | The holdout was consulted during tuning |
| Unreported search | One strong configuration | Two hundred were tried and one was kept |
| Ignored costs | Profitable signal | Spread and commission exceed the edge |
| Duplicate orders | Outsized position | A retry opened a second position |

None of these announce themselves. A lab that does not structurally prevent them
will eventually produce a confident, wrong answer. This project spends its
effort on prevention rather than on strategy search.

## Goals

1. **Reproducibility.** One documented command reruns any stored result from raw
   inputs, on a clean machine.
2. **Honest evaluation.** Walk-forward only, with purge and embargo. The holdout
   is declared at registration and looked at once. Every performance number is
   reported with its trial count.
3. **Auditability.** Experiments, predictions, and decisions are append-only.
   A prediction is stored before its outcome exists and is never revised.
4. **Safety.** Paper trading only. Long or cash only. Deterministic risk code has
   final authority over every order.
5. **A real comparison.** Any result is reported against cash, a benchmark ETF,
   and equal weight, net of costs. Beating nothing is not a finding.
6. **A decision.** At the end of the build window the project is judged and one
   of three things happens: operate, revise, or stop.

## What success means

Success is **a trustworthy experiment loop**, not a promised return.

The project has succeeded if, at the freeze, it can load a dated universe, run a
reproducible baseline, store predictions before outcomes, submit paper orders
without duplicates, reconcile positions after a restart, and show results
alongside cash, benchmark, and equal weight — and if the one-page report is
believable whether the answer is good or bad.

**A well-run experiment that concludes "this does not work" is a success.**
A strong Sharpe from a pipeline with a leak is a failure, even if it is never
discovered.

## Non-goals

Stated plainly so they do not creep in later:

| Not a goal | Why |
|---|---|
| Live trading | Paper only, throughout. Live brokerage credentials are never requested, stored, or used. |
| Autonomous trading | No "AI CIO." A model may propose; deterministic code disposes. |
| Beating a benchmark | The goal is knowing whether it does, not ensuring that it does. |
| A production platform | A local research lab for one operator, not multi-tenant infrastructure. |
| Breadth of models or vendors | One primary extractor, one challenger above a materiality threshold. No scoreboard. |
| Shorts, options, futures, crypto, leverage | Long or cash only, U.S. equities and ETFs. |
| A dashboard that implies profitability | Ops and research visibility only. |

## Operating principles

- **The smallest change that satisfies the current slice.** No speculative
  generality.
- **Register before you look.** An experiment ID exists before any result is
  viewed.
- **Report bad results.** If an outcome is poor, that is the finding. Searching
  until it flips is how a lab becomes worthless.
- **Deterministic code owns risk.** Model output is untrusted data. It cannot
  change prompts, tools, credentials, limits, sizing, or the kill switch.
- **Licensed data only.** No scraping. Provenance is recorded on every record.
- **Secrets stay local.** `.env` is gitignored. Keys never enter a prompt, a log,
  or a cloud VM.

## Scope boundary

The following are out of scope until the owner explicitly opens them, and an
agent may not add them to look complete: China feeds, social and app-review
pipelines, a Dynamic Opportunity Graph as a trading input, contextual bandits or
RL, multi-provider model routers, three-lab model committees, NVIDIA signal-miner
or distillation blueprints, NeMo clusters, TradingView webhooks as an order path,
and commercialization.

The binding version of this list lives in `AGENTS.md`.
