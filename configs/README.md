# configs/

Resolved experiment and runtime configuration.

Nothing in this directory is read by code yet. Configuration loading arrives in
Weeks 3–4 with the baseline experiment; `base.yaml` exists now so the shape is
agreed before any code depends on it.

## How configuration relates to research integrity

Every `Experiment` record stores a `config_hash`. That hash is taken over the
*resolved* configuration — after defaults, file values, and any overrides are
merged — so a stored result can always be traced back to the exact settings that
produced it. Two experiments with the same `config_hash` must be reproducible
from the same commit.

Risk limits will live in their own file (`risk.yaml`, Weeks 5–6) and are hashed
separately into `RiskDecision.risk_config_hash`. They are deterministic settings
owned by the operator. No model output may edit them.

## Rules

- No secrets here. Credentials come from the environment; see `.env.example`.
- Configuration is committed, so a config change is a reviewable diff.
- Do not add a key that no code reads. An unused key is a false promise.
