# configs/

Resolved experiment and runtime configuration.

| File | Read by |
|---|---|
| `risk.yaml` | `lab.config.load_risk_limits()` |
| `experiment.yaml` | `lab.experiments.config.load_experiment_config()` |
| `universe/liquid50.yaml` | `lab.universe.dated.load_universe()` |
| `base.yaml` | Not read. Pointer only. |

No secrets belong in this directory. Credentials come from the environment;
see `.env.example`.

## Experiment configuration

`experiment.yaml` is the source of truth for the Release 0.2 baseline: split
dates, purge, embargo, fixture seed, and the research cost model
(`one_way_cost_bps`). Those costs are a backtest assumption, not the
owner-mandate risk numbers in `risk.yaml`.

Every `Experiment` record stores a `config_hash` of the *resolved* experiment
settings so a stored result can be traced back to the exact file that produced
it.

## Risk limits

`risk.yaml` holds the deterministic risk limits. They resolve in three layers:

```
built-in defaults  <  configs/risk.yaml  <  LAB_RISK_* environment variables
```

Limits are read **once at startup** and are never mutable at runtime. The
shipped values are conservative **placeholders**, marked `owner_approved: false`.
Release 0.3's risk engine consumes them on every paper session. They stay
provisional until the owner mandate is completed.

## Rules

- No secrets here. Credentials come from the environment.
- Configuration is committed, so a config change is a reviewable diff.
- Do not add a key that no code reads. An unused key is a false promise.
