# K1510 | SUE → next-month realized vol | DML + IV exploratory causal scan

**Verdict: CONDITIONAL_PASS (Codex reviewed 2026-06-16)**

## Question

Does Standardized Unexpected Earnings (SUE) have a CAUSAL incremental effect
on next-month realized volatility (RV) at horizons h ∈ {1,2,3}, after
controlling for size, momentum, past RV, sector & seasonal FE, and macro
vol regime (VIX)?

Treatment endogeneity concern: earnings surprise and vol are both driven by
firm fundamentals, so OLS β on SUE is biased. We attempt to instrument with
**pre-announcement 5-day RV slope** (proxy for revision velocity in the
information available to traders just before earnings).

## Data

- **Universe**: S&P 500 top-50 by current market cap (static; see Limitation #1)
- **Period**: 2018-01 ~ 2026-03 (monthly panel)
- **Earnings**: `yfinance.Ticker.get_earnings_dates(limit=60)` — actual EPS,
  estimate EPS, Surprise(%) → 4,498 announcement rows across 50 firms
- **Prices**: yfinance daily Adj Close
- **VIX**: yfinance `^VIX` monthly close
- **Final monthly panel**: **4,739 rows × 50 firms × 98 months** (h=1)

## Variables

| | Definition | Lag discipline |
|---|---|---|
| Treatment D (SUE) | (actual_eps − est_eps) / rolling_8Q_std of prior surprises | Surprise std uses `shift(1)` → uses only t-2 and earlier; SUE valid for ≤3 months after announcement |
| Instrument Z | log(RV_5d) − log(RV_20d) measured strictly in window [d−20, d−1] before announcement | All info ≤ d−1 |
| Outcome Y | RV_{t+h} = sqrt(252 · mean(daily_log_ret²)) | `shift(-h)` from month-end m |
| Controls X | log_mcap (snapshot — caveat #1), past 60-day return, past 60-day RV, VIX level, sector FE (8 dummies), month-of-year FE (11 dummies) | Realized by end of m |

## Estimators

1. **OLS naive** — `Y ~ const + SUE + X + FE` with HC1 robust SE
2. **DML partialling-out** — 5-fold cross-fit GBM (200 trees, depth 3, lr 0.05)
   for `E[Y|X]` and `E[D|X]`, then OLS on residuals (`SEED=42`)
3. **Manual 2SLS** — First stage: `D ~ const + Z + X`; second stage:
   `Y ~ const + D_hat + X`. First-stage F-stat = (t-stat on Z)². **SE in
   second stage uses OLS HC1, NOT proper 2SLS covariance** (see Limitation #3)

## Results

### Main table (β = ATE of SUE on RV_{t+h}; HC1 SE; 95% CI)

| h | Estimator | β | SE | 95% CI | p-val | n | first-stage F | weak-IV |
|---|---|---|---|---|---|---|---|---|
| 1 | OLS | **+0.00098** | 0.00082 | [−0.00063, +0.00259] | 0.232 | 4,739 | — | — |
| 1 | DML | **+0.00092** | 0.00067 | [−0.00040, +0.00224] | 0.172 | 4,739 | — | — |
| 1 | IV  | +0.00312 | 0.02002 | [−0.03612, +0.04237] | 0.876 | 4,739 | **5.18** | TRUE |
| 2 | OLS | +0.00041 | 0.00061 | [−0.00079, +0.00161] | 0.502 | 4,698 | — | — |
| 2 | DML | +0.00057 | 0.00052 | [−0.00046, +0.00160] | 0.275 | 4,698 | — | — |
| 2 | IV  | +0.02306 | 0.02566 | [−0.02724, +0.07335] | 0.369 | 4,698 | **4.46** | TRUE |
| 3 | OLS | +0.00080 | 0.00057 | [−0.00032, +0.00192] | 0.161 | 4,648 | — | — |
| 3 | DML | +0.00086 | 0.00055 | [−0.00023, +0.00194] | 0.121 | 4,648 | — | — |
| 3 | IV  | +0.06006 | 0.03009 | [+0.00109, +0.11903] | 0.046 | 4,648 | **3.86** | TRUE |

### Hausman test (IV vs OLS difference)

| h | stat | p-val | interpretation |
|---|---|---|---|
| 1 | 0.011 | 0.915 | cannot reject OLS = IV (consistent with null & weak-IV) |
| 2 | 0.779 | 0.377 | same |
| 3 | 3.881 | 0.049 | borderline, but IV β unreliable (F<10) → no inference |

### Robustness — VIX regime (h=1)

| Sub-sample | n | OLS β | IV β | IV-F |
|---|---|---|---|---|
| VIX-high (≥ median) | 2,388 | +0.00036 | +0.00725 | 3.31 |
| VIX-low  (< median) | 2,351 | +0.00157 | −0.00320 | 0.95 |

Both regimes consistent with NULL OLS effect; IV β flips sign across regimes
under weak first-stage → not interpretable.

## Headline finding (honest)

**No detectable causal effect of SUE on next-month realized vol** in this
sample after partialling out price/size/sector/macro covariates. OLS and
DML produce point estimates of order +0.001 (~0.1 percentage points of
annualized vol per 1-σ surprise) with confidence intervals straddling zero.

**IV identification fails**: pre-announcement 5-day RV slope is a weak
instrument for SUE (first-stage F ∈ [3.3, 5.2] across horizons, all < 10).
IV point estimates are large but their CIs are wide and untrustworthy.

This is a **NULL result + identification failure**, not evidence of a
mechanism. The earlier "earnings surprise → realized vol" intuition appears
to be priced/absorbed within the announcement-month return-vol channel
already captured by `past60_rv`.

## Limitations (Codex review noted)

1. **Survivorship / look-ahead in universe**: S&P 500 top-50 is a *current*
   snapshot. Firms that delisted, merged, or fell out of top-50 are absent.
   `log_mcap` is a *current* snapshot, not historical — used only as a level
   control (does not affect within-firm time variation in SUE→RV channel),
   but introduces minor measurement error.
2. **No historical EPS estimate revisions**: yfinance only exposes the
   final pre-announcement estimate; we cannot construct a true
   analyst-revision IV (the original first-choice instrument).
3. **2SLS standard errors**: the second-stage OLS HC1 SE under-states the
   true 2SLS sampling variance (it does not propagate first-stage error).
   Given weak-IV, this is moot — IV inference is unreliable regardless.
4. **Sample period 2018-2026**: includes COVID (large vol shock) but only
   ~98 months of panel; longer history would help.
5. **Wording**: "ATE / causal" labels used in code for naming consistency
   with DML literature; given (1)-(4), all estimates here should be read as
   **associational / exploratory**, not as identified causal effects.

## What this means for the platform

- Do NOT add SUE-based vol forecasting features to production strategies
  based on this evidence.
- A stronger IV (true analyst-revision velocity from a paid data source) +
  full historical S&P 500 constituent list + ≥15 years panel could revisit;
  expected-return-vs-vol decoupling is plausible only with cleaner IV.
- The null result is itself useful: rules out a popular folk-trader claim
  that "high SUE → next-month vol spike" once you control for past RV.

## Files

- `k1510.py` — single self-contained script (fetch → estimate → save)
- `k1510_results.json` — all numbers + sample sizes + verdict
- `k1510_panel.parquet` — clean panel for downstream re-analysis
- `k1510_fig_a.png` — forest plot of OLS / DML / IV ATE at h=1 with 95% CI
- `k1510_fig_b.png` — ATE across horizons h=1,2,3 for the 3 estimators
- `references.md` — methodological references

## Reproduce

```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run python .claude/worktrees/agent-sue-dml-iv/experiments/k1510/k1510.py
```

Wall time ≈ 105 s on M2 Mac (network-bound by yfinance).
