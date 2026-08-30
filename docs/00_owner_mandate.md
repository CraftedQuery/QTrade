# Owner mandate

**Status: NOT YET FILLED IN. The owner completes this file.**

This file was referenced by `AGENTS.md`, `CLAUDE.md`, and `README.md` but had
never been committed. It is created here as an empty template. No agent may
invent values for it — the numbers below constrain real risk decisions, and a
guessed number is worse than a blank one.

The **Capital and risk** numbers below are not hard-coded anywhere. They live in
`configs/risk.yaml` and can be changed without touching code — or overridden per
run with `LAB_RISK_*` environment variables. Until you fill in section 3 and set
`owner_approved: true`, the lab runs on conservative provisional placeholders and
reports its limits as provisional.

Precedence: built-in defaults < `configs/risk.yaml` < `LAB_RISK_*`.

Limits are read once at startup and never change mid-session, so every risk
decision stays recomputable from the config hash it stores.

---

## 1. Time

| Item | Value |
|---|---|
| Focused hours available per week |  |
| Weeks committed before the go/no-go decision |  |
| Preferred working pattern (e.g. weekends only) |  |

## 2. Budget

| Item | Value |
|---|---|
| Monthly budget for data and API costs |  |
| Monthly budget for compute |  |
| Hard ceiling above which work stops |  |

## 3. Capital and risk

Paper trading only. These figures size the **simulated** book and calibrate the
risk engine. They are not an instruction to deploy real money.

Each row maps to a setting in `configs/risk.yaml`. Fill these in, copy them
across, and set `owner_approved: true`.

| Item | Value | `configs/risk.yaml` key | Provisional default |
|---|---|---|---|
| Simulated starting capital |  | `starting_capital` | 100000 |
| Maximum position size, fraction of book |  | `max_position_weight` | 0.05 |
| Maximum gross exposure, fraction of book |  | `max_gross_exposure` | 0.60 |
| Maximum daily loss before halt, fraction |  | `max_daily_loss` | 0.02 |
| Maximum drawdown before stop, fraction |  | `max_drawdown` | 0.10 |
| Maximum names held at once |  | `max_positions` | 20 |
| Maximum market-data age before halt, seconds |  | `max_data_staleness_seconds` | 300 |

Values are fractions, not percentages: 2% is `0.02`.

## 4. Data sources

| Item | Value |
|---|---|
| Licensed market data provider(s) |  |
| Entitlements held (e.g. Alpaca paper, Benzinga news) |  |
| Sources explicitly **not** licensed |  |

## 5. Decision criteria

What has to be true at the Week 11–12 freeze for this project to continue?

| Item | Value |
|---|---|
| Minimum acceptable result vs. the equal-weight control |  |
| Maximum acceptable turnover |  |
| Definition of "stop" |  |

## 6. Explicitly out of scope for this owner

Confirm or amend the out-of-scope list in `AGENTS.md`:

- [ ] I confirm the out-of-scope list in `AGENTS.md` stands as written.
- [ ] Amendments (list them):

## 7. Sign-off

| Item | Value |
|---|---|
| Owner |  |
| Date |  |
| Mandate version |  |
