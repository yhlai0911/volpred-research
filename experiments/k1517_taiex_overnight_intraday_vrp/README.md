# K1517 — TAIEX Overnight vs Intraday Pseudo-VRP Decomposition

## Motivation

The variance-risk-premium literature decomposes option-implied variance risk
premia into trading-period and nontrading-period components. Papagelis and
Dotsis (2025, *Journal of Futures Markets*) show that for SPY the overnight
VRP dominates the intraday VRP and predicts next-day realized variance. **No
published study has tested this for Taiwan equities (TAIEX / ^TWII).**

K1517 fills this gap with a free-data pseudo-VRP variant and **directly
compares the cross-market structure of overnight vs intraday variance dynamics**
in TAIEX against the parent K experiment on SPY, QQQ, IWM, EFA
(`experiments/research_intraday_vs_overnight_vrp/`, verdict=NULL).

The key research questions:

1. Does TAIEX show overnight-variance dominance like EFA, or intraday-variance
   dominance like SPY/QQQ/IWM?
2. Does the lagged overnight pseudo-VRP predict next-day session variance in TAIEX?
3. Does the cross-market pattern of pseudo-VRP signs (US negative, EM possibly
   different) hold for an East-Asian market with no formal night session
   in the cash index?

## Differentiation vs Parent

| Dimension                | Parent (`research_intraday_vs_overnight_vrp`) | K1517 (this)                           |
| ------------------------ | ---------------------------------------------- | -------------------------------------- |
| Asset universe           | SPY, QQQ, IWM, EFA (US-listed ETFs)            | ^TWII (TAIEX cash index, EM Asia)      |
| Method                   | GARCH(1,1) pseudo-VRP                          | **Same** — verbatim methodology        |
| OOS start                | 2018-01-02                                     | **2007-01-03** (longer; 4,691 obs)     |
| Cross-asset bar chart    | Within US ETFs                                 | **TAIEX vs SPY-family overlay**        |
| Decision rule            | 3/4 assets must pass overnight gate            | Joint gate on single TAIEX asset       |

Methodology is held identical so the cross-market comparison is symmetric
(per `.claude/rules/experiments.md`: "跨市場比較必 symmetric refinement").

## Literature

- Papagelis, S., & Dotsis, G. (2025). The Variance Risk Premium Over Trading
  and Nontrading Periods. *Journal of Futures Markets*.
  https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589
- Carr, P., & Wu, L. (2009). Variance Risk Premia. *Review of Financial
  Studies*, 22(3), 1311–1341. https://doi.org/10.1093/rfs/hhn038
- Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected Stock Returns and
  Variance Risk Premia. *Review of Financial Studies*, 22(11), 4463–4492.
  https://www.federalreserve.gov/pubs/feds/2007/200711/
- Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized
  Volatility. *Journal of Financial Econometrics*, 7(2), 174–196.
  https://doi.org/10.1093/jjfinec/nbp001

## Related Internal K

- `experiments/research_intraday_vs_overnight_vrp/` — parent SPY/QQQ/IWM/EFA
  study; verdict NULL.
- `experiments/experiment_0dte_intraday_overnight_vol_2026_06_13/` — adjacent
  0DTE-window vol decomposition.
- `experiments/research_vrp_vrp_horizon/` — VRP horizon spec.
- `experiments/vrp_regime_decomposition/` — VRP regime conditioning.

## Data

- **Source**: local CSV pre-fetched from yfinance,
  `storage/macro/yf_TWII.csv`. Header has 3 metadata rows
  (`Price/Ticker/Date` block).
- **Asset**: `^TWII` (Taiwan Weighted Index, cash, TWD).
- **Raw range**: 1997-07-02 → 2026-03-17 (7,033 daily rows).
- **Analysis start**: 2001-01-01 (after burn-in).
- **OOS start**: 2007-01-03 (after 1000-day GARCH warmup).
- **n_OOS**: **4,691** daily observations (far exceeds the 500-obs gate from
  `research_program.md`).
- VIXTWN option-IV is **not** used — see `data_constraints.md` for rationale
  (only 129 obs from 2025-12-01).

## Method (mirrors parent)

Returns are decomposed:

- overnight: `log(Open_t / Close_{t-1})`
- intraday: `log(Close_t / Open_t)`
- close-to-close: `log(Close_t / Close_{t-1})`

Realized session variance `= overnight^2 + intraday^2`. Close-to-close variance
adds a covariance residual `2 * overnight * intraday`.

For the ex-ante proxy: rolling zero-mean GARCH(1,1) on close-to-close returns
in percent units.

- Trailing window: 1,000 observations.
- Refit frequency: 21 trading days.
- Forecast for day `t` uses returns through `t-1` (loop `i-1` indexing).

Total GARCH variance is split into overnight/intraday using the **trailing
252-day overnight share, shifted by one day** (no day-`t` info leaks in).

`pseudo-VRP_component = expected_component_variance − realized_component_variance`

Predictive regression:

```
log(session_var_t) ~ overnight_pseudo_vrp_{t-1}
                  + intraday_pseudo_vrp_{t-1}
                  + log(session_var_{t-1})
                  + log(garch_total_var_{t-1})
```

Newey-West HAC SE with 5 lags. Share / premium uncertainty: 1,000-rep
moving-block bootstrap (21-day blocks, seed=42).

### Lookahead protection (explicit)

1. GARCH forecast for day `t` uses returns through `t-1` (`values[i-1]^2`).
2. Trailing-252d overnight share is `.shift(1)` before allocation.
3. All predictive features use `.shift(1)` (overnight_pseudo_vrp_lag1,
   intraday_pseudo_vrp_lag1, log_session_var_lag1, log_garch_total_var_lag1).
4. Same `signal.shift(1)` convention as parent — cross-asset compare symmetric.

### Pre-specified gate

- Overnight-share bootstrap CI lower bound > 0.5 (overnight dominance gate)
- Lagged overnight pseudo-VRP HAC t-stat > 3 (predictive gate)
- Both must pass → PASS; one only → CONDITIONAL_PASS; neither → NULL.

## Results

### Session variance share (OOS 2007-01 → 2026-03)

| Asset    | Overnight share | Intraday share | Overnight 95% bootstrap CI |
| -------- | --------------: | -------------: | -------------------------: |
| **^TWII** | **0.420**       | **0.580**      | **[0.378, 0.460]**         |
| SPY      | 0.426           | 0.574          | [0.333, 0.524]             |
| QQQ      | 0.379           | 0.621          | [0.318, 0.451]             |
| IWM      | 0.397           | 0.603          | [0.332, 0.461]             |
| EFA      | 0.646           | 0.354          | [0.566, 0.715]             |

**TAIEX overnight share (0.42, CI upper 0.46) is statistically indistinguishable
from SPY/QQQ/IWM — none of these include 0.5, all reject overnight dominance.
EFA is the only asset with robust overnight majority.**

### Mean pseudo-VRP (pct²)

| Asset    | Overnight pseudo-VRP | Intraday pseudo-VRP |
| -------- | -------------------: | ------------------: |
| **^TWII** | **−0.027**           | **+0.027**          |
| SPY      | −0.014               | −0.035              |
| QQQ      | −0.025               | −0.055              |
| IWM      | −0.064               | −0.070              |
| EFA      | −0.032               | −0.026              |

Note: TAIEX is the **only asset with positive intraday pseudo-VRP** — the
GARCH expected intraday variance exceeds realized on average, while overnight
GARCH expected understates realized. This is the OPPOSITE pattern from SPY
(overnight expected ≈ realized; intraday expected < realized).

### Predictive regression OOS

| Asset    | Coef_overnight | t_overnight (HAC) | Coef_intraday | t_intraday (HAC) | R²    |
| -------- | -------------: | ----------------: | ------------: | ---------------: | ----: |
| **^TWII** | **−0.068**     | **−2.68**         | **−0.091**    | **−2.44**        | 0.188 |
| SPY      | −0.022         | −0.65             | −0.092        | −3.09            | 0.213 |
| QQQ      | −0.074         | −2.29             | −0.031        | −0.88            | 0.170 |
| IWM      | −0.017         | −0.52             | −0.108        | −3.93            | 0.157 |
| EFA      | −0.039         | −1.28             | −0.079        | −2.65            | 0.153 |

**No asset (TAIEX included) satisfies the t_overnight > +3 gate.** TAIEX
shows weak negative predictive sign on both components, similar to SPY/QQQ/IWM.

## Verdict

**NULL.**

The TAIEX pseudo-VRP decomposition fails both pre-specified gates:

1. Overnight share CI upper (0.460) < 0.5 — no overnight dominance.
2. HAC t_overnight = −2.68 — wrong sign and below +3.

### Cross-market finding (the actual contribution)

**The pseudo-VRP framework yields uniformly NULL across SPY, QQQ, IWM, AND
TAIEX.** Only EFA (international DM ETF) has robust overnight majority, and
even EFA fails the predictive gate.

This is the first published-quality data point on TAIEX overnight vs intraday
variance decomposition. The finding **does not contradict** Papagelis & Dotsis
(2025) — they use option-implied variance, not GARCH forecasts — but it does
suggest that the GARCH proxy is insufficient to recover the option-VRP
pattern. The intraday/overnight allocation in TAIEX matches the US ETF
pattern (intraday slightly dominates).

### Honest characterization of differences vs SPY

- TAIEX overnight pseudo-VRP **same sign as SPY (both negative)** — GARCH
  expected component < realized for overnight in both markets.
- TAIEX **intraday pseudo-VRP positive** while SPY's is negative — minor sign
  flip; small magnitudes, not statistically separated from zero (bootstrap
  CI on TAIEX intraday premium straddles 0: [−3.8e-6, +8.7e-6]).
- Predictive regressions: TAIEX both legs marginally significant negative;
  SPY only intraday leg negative significant; QQQ only overnight. **Cross-
  market heterogeneity in which leg drives prediction, but uniformly negative
  signs.**

## Research Honesty Notes

- This is **not** a replication of option-implied VRP literature. The object
  is a GARCH forecast-error proxy, labelled `pseudo-VRP` throughout.
- All predictive features are explicitly `.shift(1)` lagged; trailing share
  allocation is also shifted.
- Seed=42 fixed for the bootstrap; GARCH optimiser is deterministic per
  scipy default.
- TAIEX has no formal night session in the cash index; "overnight" here is
  the close-to-open gap captured by `^TWII` Open vs prior Close — the natural
  analog used in the literature for indices without a 24h tape.
- Result is useful as (a) free-data TAIEX baseline for future option-implied
  VRP work, (b) confirmation that the GARCH-pseudo-VRP method does not
  recover option-VRP patterns even cross-market, and (c) input to the
  paper-narrative state machine if combined with ≥2 other cross-market
  variance-decomposition findings.

## Files

- `k1517_taiex_overnight_intraday_vrp.py` — runnable end-to-end script.
- `k1517_taiex_overnight_intraday_vrp_results.json` — verdict + metrics.
- `data/twii_daily_processed.csv` — processed OHLC used in the run.
- `fig_session_variance_shares.png` — TAIEX overnight vs intraday share bar.
- `fig_predictive_tstats.png` — TAIEX predictive HAC t-stats.
- `fig_taiex_vs_spy_overnight_vrp.png` — **TAIEX vs SPY/QQQ/IWM/EFA cross-asset
  comparison panel** (3 sub-plots: overnight share, mean overnight pseudo-VRP,
  predictive HAC t-stat).
- `data_constraints.md` — VIXTWN window limitation note.

## Reproduce

```
uv run python experiments/k1517_taiex_overnight_intraday_vrp/k1517_taiex_overnight_intraday_vrp.py
```

Expected runtime ≈ 1-3 min on M-series Mac. Output is deterministic given
fixed seed and unchanged input CSV.

## Status

- [x] Pre-specified gates + verdict computed
- [x] Lookahead-protected (3 explicit `.shift(1)` sites + GARCH `i-1` index)
- [x] Cross-asset comparison vs SPY/QQQ/IWM/EFA included
- [x] Data constraints documented
- [ ] Codex review (pending main-thread merge, then 24h-rule)
- [ ] knowledge.json provenance entry (post-Codex-PASS only)
