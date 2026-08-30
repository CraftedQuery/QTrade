# configs/

Resolved experiment and runtime configuration.

`risk.yaml` **is** read by code, via `lab.config.load_risk_limits()`.
`base.yaml` is not yet — experiment configuration loading arrives in Release 0.2;
it exists now so the shape is agreed before any code depends on it.

## How configuration relates to research integrity

Every `Experiment` record stores a `config_hash`. That hash is taken over the
*resolved* configuration — after defaults, file values, and any overrides are
merged — so a stored result can always be traced back to the exact settings that
produced it. Two experiments with the same `config_hash` must be reproducible
from the same commit.

## Risk limits

`risk.yaml` holds the deterministic risk limits. They resolve in three layers:

```
built-in defaults  <  configs/risk.yaml  <  LAB_RISK_* environment variables
```

so a limit can be changed without touching code — edit the file, or export a
variable for a single run.

Limits are read **once at startup** and are never mutable at runtime. That is
deliberate. Every `RiskDecision` stores a `risk_config_hash` covering the numeric
limits, and a decision has to stay recomputable from it; a limit that could move
mid-session would make the audit trail meaningless. Change a limit, restart, and
the hash changes with it, so the record shows which numbers produced which
decisions.

The shipped values are conservative **placeholders**, marked
`owner_approved: false`. Replace them with the owner's numbers from
`docs/00_owner_mandate.md` §3 and set the flag. Until then the limits report
themselves as provisional, and Release 0.3 will refuse to run an unattended
session.

No model output may edit these settings, and `RiskLimits` exposes no mutation
method.

## Rules

- No secrets here. Credentials come from the environment; see `.env.example`.
- Configuration is committed, so a config change is a reviewable diff.
- Do not add a key that no code reads. An unused key is a false promise.
