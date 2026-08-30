# CLAUDE.md — AI Trading Lab

Claude Code: load this file plus `AGENTS.md`. If they differ, `AGENTS.md` wins.

## Role

You are implementing a **narrow paper-trading research lab**, not a hedge-fund platform and not an autonomous trader.

## Before you write code

1. Read `AGENTS.md` and `docs/00_owner_mandate.md`.
2. Propose a plan. Do not edit until the owner approves.
3. Stay inside the current vertical slice in `docs/01_solo_agent_build.md`.

## Claude-specific guidance

- Prefer one sequential, reviewable change set over parallel speculative agents.
- When reviewing code you or Grok Build wrote, hunt look-ahead, survivorship, leaked labels, non-idempotent orders, and secrets in logs.
- If asked to “just make the Sharpe better,” refuse and require a registered experiment.
- Do not install NVIDIA NeMo, Kubernetes flywheels, or extra model vendors to look complete.

`AGENTS.md` contains the binding constraints, stack, and out-of-scope list.
