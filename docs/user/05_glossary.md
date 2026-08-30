# Glossary

Terms used across the documentation and the code.

## Research integrity

**Look-ahead bias** — using information that did not exist at the moment a
decision was supposedly made. The most damaging error in backtesting because it
is invisible in the result: it simply makes performance look excellent. Guarded
here by `information_cutoff <= as_of` on every feature snapshot.

**Information cutoff** — the timestamp of the newest input that fed a feature.
Must never exceed the decision time (`as_of`).

**Survivorship bias** — building a universe from today's constituent list, so
companies that failed or were delisted are silently excluded. Backtests on such
a universe look better than reality. Guarded by `listed_on` / `delisted_on` on
every instrument.

**Point-in-time** — data that reflects what was actually known on a past date,
rather than today's revised view of it. A current S&P 500 membership list is
*not* point-in-time.

**Walk-forward** — training on a past window, testing on the window that follows,
then rolling forward. The only evaluation scheme this project accepts.

**Purge** — dropping observations near a split boundary whose labels overlap the
other split. Without it, training and test sets share information.

**Embargo** — withholding a further span of data immediately after a split, so
serial correlation cannot leak across the boundary.

**Holdout** — a data range declared at experiment registration and looked at
exactly once, at the end. Tuning on the holdout destroys its meaning. Tracked by
`holdout_unsealed_at`.

**Trial count** — how many configurations were tried in a line of search. A
Sharpe of 1.8 from the best of 200 trials is a different claim from a Sharpe of
1.8 from one. Every experiment carries it.

**Rank IC** — the rank correlation between predicted and realised returns across
the universe. A measure of ranking skill that is more robust than hit rate.

**Ablation** — running the same pipeline with and without one component to
isolate its contribution. Used for quant-only vs. quant+news.

**Control** — the simple comparator a result must beat to mean anything: cash, a
benchmark ETF, or equal weight.

## Portfolio and execution

**Long or cash only** — every position is a non-negative weight; unallocated
weight is cash. Short positions are unrepresentable in the contracts.

**Weight** — a position's share of portfolio value, in `[0, 1]`.

**Gross exposure** — total invested weight. Above 1 would be leverage, and is
rejected.

**Proposal** — a desired target portfolio produced by a strategy, before risk
review.

**Risk decision** — the deterministic risk engine's verdict on a proposal:
approved, reduced, or rejected. Final authority over every order.

**Kill switch** — an operator control that halts all trading. When engaged, every
risk decision must be a rejection.

**Risk limits** — the hard ceilings the risk engine enforces: position cap, gross
exposure cap, name count, daily loss halt, drawdown stop, data staleness. Held in
`configs/risk.yaml`, overridable with `LAB_RISK_*`, read once at startup.

**Provisional limits** — risk limits that are conservative placeholders rather
than the owner's real numbers. Flagged by `owner_approved: false`; the lab
reports its own limits as provisional until the mandate is completed.

**Config hash** — a deterministic hash of the resolved risk limits, stamped onto
every risk decision so the decision stays recomputable and you can always tell
which rules an order was checked against.

**Stale data halt** — refusing to trade on market data older than a threshold.

**Idempotency / client order ID** — a deterministic key derived from the risk
decision, so replaying the same decision produces the same key and the broker
rejects the duplicate instead of opening a second position.

**Reconciliation** — comparing the lab's view of positions against the broker's
after a restart, and resolving any difference.

**Paper trading** — simulated execution against a broker's paper endpoint. No
real money, no real orders. The only mode this project supports.

**Broker paper fill** — what the paper broker reports as the execution.

**Internal shadow fill** — the lab's own, deliberately more pessimistic estimate
of the same execution (wider spread, added delay). Stored alongside the broker
fill, never merged with it, so the optimism of paper fills stays visible.

**Slippage** — the gap between the price a decision assumed and the price
actually achieved.

**Turnover** — how much of the portfolio is traded per period. High turnover can
consume an edge through costs even when the signal is real.

## Market data

**Bar / OHLCV** — open, high, low, close and volume over a time window. In this
project a bar covers `[ts_start, ts_end)` and is only knowable at `ts_end`.

**Information time** — the earliest moment a bar may legitimately be used: its
close, never its open.

**Adjustment** — how corporate actions (splits, dividends) have been applied to a
price series. Mixing adjusted and raw series manufactures returns.

**VWAP** — volume-weighted average price over a window.

**Universe** — the set of instruments eligible for trading on a given date.

## Project

**Slice** — the current, narrow band of work an agent is permitted to build.
Working outside the slice is how a research lab becomes an unmaintainable demo.

**Contract** — one of the nine record types the system exchanges, defined as a
Pydantic model in `src/lab/contracts/` and exported as JSON Schema.

**Append-only** — records are added, never edited or deleted. History that can be
rewritten is not evidence.

**Schema drift** — the generated JSON Schemas falling out of step with the
models. Detected by `tests/test_schemas_in_sync.py`.

**Freeze** — the point at which code and configs stop changing so the project can
be judged honestly.
