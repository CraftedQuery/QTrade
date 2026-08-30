# schemas/

**Generated files. Do not hand-edit.**

JSON Schema (draft 2020-12) for each of the nine persisted contracts. They exist
so that contract changes appear as a reviewable diff and so non-Python consumers
can validate lab records.

The source of truth is the Pydantic models in `src/lab/contracts/`.

## Regenerating

```bash
make schemas          # or: uv run python -m lab.contracts.export
```

`tests/test_schemas_in_sync.py` regenerates every schema in memory and fails if
a committed file differs, so a stale schema cannot reach `main`.

## Files

| File | Contract |
|---|---|
| `instrument.schema.json` | A tradable U.S. equity or ETF, with listing dates |
| `bar.schema.json` | One OHLCV window |
| `feature_snapshot.schema.json` | Features for one instrument at one decision time |
| `experiment.schema.json` | A registered experiment |
| `prediction.schema.json` | One model output, stored before its outcome |
| `proposal.schema.json` | A desired target portfolio |
| `risk_decision.schema.json` | The risk engine's verdict on a proposal |
| `order.schema.json` | An order sent to the paper broker |
| `fill.schema.json` | An execution against an order |

See [`../docs/03_data_contracts.md`](../docs/03_data_contracts.md) for what each
one means and which invariants it enforces.

## Note on validation strength

JSON Schema captures field names, types, requiredness, enum members, and numeric
bounds. It does **not** capture the cross-field invariants — `information_cutoff
<= as_of`, the kill-switch rule, walk-forward split ordering, OHLC consistency.
Those live in the Pydantic validators. Validating a record against the JSON
Schema alone is necessary but not sufficient; use the models where you can.
