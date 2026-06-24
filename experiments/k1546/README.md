# K1546: Term-structure of variance risk premium — VRP slope as predictor of SPY forward drawdown

**Verdict: NULL** (full-sample headline; with regime-specific MIXED caveat — see § Subsample)

## Motivation

Single-horizon VRP literature (K430, K438, K450) and VIX term-structure literature (K429) have produced mixed / null results when predicting **returns**. This experiment pivots on two axes simultaneously:

- **Target**: forward drawdown / left-tail event (not return). Drawdown is more tightly linked to investor capital preservation and may carry stronger signal than mean return.
- **Signal**: VRP **slope** across horizons (1M, 3M, 6M), not single-horizon VRP. Hypothesis: curvature of the variance-risk-premium term structure — `VRP_6M − VRP_1M` — captures fear-gauge structure that flattens / inverts ahead of tail events.

## Hypothesis

A **decreasing / negative VRP slope** (VRP_6M shrinks toward or below VRP_1M) signals near-term fear repricing and predicts larger forward drawdowns. Equivalently, lower slope → more negative `fwd_max_dd`.

## Data

- Source: yfinance (no mock data).
- Tickers: `SPY`, `^VIX`, `^VIX3M`, `^VIX6M`. (All four available, ~2008-01-02 → 2026-06-23.)
- N = 4,648 trading days.

## Method

- **VRP construction** (variance scale, per Bollerslev/Tauchen/Zhou 2009): `VRP_h = IV_h² − RV_h²` where `IV_h` is VIX/VIX3M/VIX6M (annualized %) and `RV_h` is rolling SPY return std × √252 × 100 over the appropriate lookback window (21 / 63 / 126 days).
- **Slopes**: `VRP_slope_3M_1M = VRP_3M − VRP_1M`, `VRP_slope_6M_1M = VRP_6M − VRP_1M`.
- **Benchmarks**: `IV_slope_3M_1M`, `IV_slope_6M_1M`, `VIX_level` (raw level).
- **Target**: forward N-day max drawdown over strictly `[t+1, t+N]`, N ∈ {5, 21, 63}.
- **Strict lookahead defense**: all signals are `.shift(1)` lagged before regression (signal at t uses ≤ t−1 info; forward DD strictly in `[t+1, t+N]`).
- **Tests**:
  1. Spearman rank correlation with block-bootstrap 95% CI (block=N, B=1000, seed=42).
  2. Newey-West HAC SE OLS regression `fwd_dd_N ~ const + signal`, lag = N.
  3. ROC AUC for tail event (`fwd_dd_21 ≤ −5%`) with Hanley-McNeil 95% CI.
  4. Quantile-5 portfolio: mean `fwd_dd_21` by signal-quintile; Welch t-test top vs bottom.
  5. Subsample stability: 2010-2019 vs 2020-2026.
  6. Encompassing regression: `fwd_dd_21 ~ const + VIX_level + VRP_slope_6M_1M` (HAC).

## Differentiation from prior K

- **K429** (VIX term-structure slope as return predictor → null). We test VRP-based slope (not raw IV) against drawdown (not return). VRP differs from IV by subtracting realized variance — purifying the premium.
- **K430** (single-horizon VRP IS sig OOS null for returns). We use cross-horizon **slope** and drawdown target.
- **K438** (GARCH-X + single VRP). Orthogonal: no GARCH, term-structure focused.
- **K450** (VRP + semivariance for returns). Orthogonal target (drawdown).

## Headline results (N=21, full sample 2008-2026)

| Signal | N | NW t-stat | AUC (-5% tail) | Spearman ρ | 95% CI |
|---|---|---|---|---|---|
| **VRP_slope_3M_1M** | 4,563 | **−0.44** | 0.473 | −0.030 | [−0.10, 0.04] |
| **VRP_slope_6M_1M** (headline) | 4,500 | **−0.98** | 0.447 | −0.047 | [−0.13, 0.04] |
| IV_slope_3M_1M (benchmark) | 4,635 | +5.67 | 0.646 | +0.226 | sig |
| IV_slope_6M_1M (benchmark) | 4,635 | +5.54 | 0.664 | +0.264 | sig |
| **VIX_level** (benchmark) | 4,636 | **−6.21** | 0.284 | −0.415 | dominant |

> Headline: `|t| = 0.98 < 2` and `AUC = 0.447 < 0.55`. **NULL.**

Both VRP slope variants are statistically indistinguishable from zero predictors of forward 21-day drawdown over the full sample. Raw IV slope and VIX level remain strongly significant in the **expected directions** — confirming pipeline validity (signals that should predict, do).

## Encompassing regression

`fwd_dd_21 ~ const + VIX_level + VRP_slope_6M_1M` (HAC lag=21):

| Term | Coefficient | NW t-stat |
|---|---|---|
| VIX_level | −0.00192 | **−6.43** |
| VRP_slope_6M_1M | −2.08e-6 | −0.39 |

VRP slope coefficient collapses to zero once VIX level is included. **VIX level subsumes the VRP slope signal entirely** — no incremental predictive power.

## Subsample stability (headline signal `VRP_slope_6M_1M`, target `fwd_dd_21`)

| Subsample | N | NW t-stat | Spearman ρ | Verdict |
|---|---|---|---|---|
| 2010-2019 | 2,516 | **−4.79** (p < 1e-6) | −0.065 | **sig negative** |
| 2020-2026 | 1,606 | −0.80 (p=0.43) | −0.087 | insig |

Subsample reveals a **regime-fragile** pattern: VRP slope had measurable predictive power in the post-GFC / pre-COVID regime, but the relationship collapsed in 2020-2026 (COVID shock + 2022 bear market + 2024-25 vol regime). The full-sample headline NULL is partly a consequence of regime averaging — but per K1416 / Harvey rigor, we do not retroactively rebrand this as PASS based on cherry-picked sub-window.

## Verdict & narrative

- **Full-sample**: NULL.
- **Regime-conditional**: 2010-2019 sig, 2020-2026 insig → **fragile**, not robust.
- **Methodological message**: VRP-slope adds **nothing incremental** over raw VIX level (encompassing test t = −0.39). VIX level is the dominant tail-risk signal; constructing a slope from `IV² − RV²` is computationally costly without economic payoff in this drawdown framework.
- **Honest framing**: this is a useful **null result** that pre-empts the temptation to publish "VRP term-structure predicts drawdown" — it doesn't, once you control for VIX level. Save authors from the K430 trap.

## Outputs

- `k1546.py` — full reproducible script (seed=42).
- `k1546_results.json` — all test statistics.
- `k1546_data.csv` — feature matrix (signal + target columns).
- `fig1_vrp_term_structure.png` — VRP_1M / 3M / 6M time series.
- `fig2_scatter_slope_vs_dd.png` — VRP_slope_6M_1M vs fwd 21d max DD scatter.
- `fig3_quantile_portfolio.png` — Quintile-portfolio mean fwd 21d max DD.
- `fig4_roc.png` — ROC for tail event (fwd 21d DD ≤ −5%).

## References

1. Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected stock returns and variance risk premia. *Review of Financial Studies*, 22(11), 4463-4492. — VRP variance-scale canonical construction.
2. Bekaert, G., & Hoerova, M. (2014). The VIX, the variance premium and stock market volatility. *Journal of Econometrics*, 183(2), 181-192. — VRP decomposition & multi-horizon usage.
3. Andersen, T. G., Bondarenko, O., & Gonzalez-Perez, M. T. (2015). Exploring return dynamics via corridor implied volatility. *Review of Financial Studies*, 28(10), 2902-2945. — corridor IV / SVIX framework for tail-risk signals.

## Methodology compliance

- ✅ `signal.shift(1)` applied to all signals (line ~218 in k1546.py).
- ✅ Forward DD strictly `[t+1, t+N]`, no t-inclusion.
- ✅ NW HAC SE with lag = forecast horizon N (overlapping-window correction).
- ✅ Block bootstrap CI with block = N, B = 1000, seed = 42.
- ✅ QLIKE not applicable (drawdown target, not variance forecast).
- ✅ Baseline (`VIX_level`, `IV_slope`) uses same `_lag1` shift convention.
- ✅ Real yfinance data (no mock).
- ✅ Subsample stability test reported separately from full-sample headline (no cherry-pick).
- ⚠️ Codex review **not** performed by worktree agent — main thread to schedule pre-knowledge-write Codex review per K1259 process gate.
