# K980v2: Threshold GJR-GARCH — Correct Joint MLE (K980 Methodology Fix)

## Status: EXPLORATORY_NULL

**Date**: 2026-05-17
**Data**: SPY + ^VIX (yfinance), 2006-01-05 to 2026-04-06
**IS**: 2006-01-05 to 2018-12-31 (3,269 obs)
**OOS**: 2019-01-02 to 2026-04-06 (1,824 obs)
**Seed**: 42

---

## Motivation

K980 (Codex primary-path review 2026-05-17: FAIL) implemented a "Threshold GJR-GARCH" by fitting two **separate** GJR models on non-contiguous subset arrays (`returns_is[low_mask]`, `returns_is[high_mask]`), then evaluating with a **continuous** `h_t` recursion that assumed `h_{t-1}` was valid across regime boundaries. This is an estimation-evaluation mismatch: the model estimated ≠ the model being evaluated.

**K980v2 fixes this** by implementing true Joint MLE over the full time series:
- `h_t` is continuous and never restarted at regime switches
- At each step `t`, the regime-specific parameters update `h_t` but `h_{t-1}` is always the variance from the previous step (regardless of which regime was active)
- The log-likelihood is summed over all `t` simultaneously — a single optimization over 8 parameters

**Core research question** (same as K980): Does a Threshold GJR-GARCH with VIX-regime switching, estimated correctly via joint MLE, outperform a standard GJR-GARCH in OOS volatility forecasting?

---

## Model Specification

### Threshold GJR-GARCH (TGJR) — Joint MLE

```
h_t = omega[s_t] + alpha[s_t]*e_{t-1}^2 + gamma[s_t]*I(e_{t-1}<0)*e_{t-1}^2
      + beta[s_t]*h_{t-1}
```

Where:
- `s_t = I(VIX_{t-1} > c)` — regime at time t based on lagged VIX (no lookahead)
- `h_{t-1}` = same continuous variance state regardless of regime
- `c` = threshold searched over `{14, 16, 18, 20, 22, 24}`, selected by IS QLIKE
- Parameters: `[omega_low, alpha_low, gamma_low, beta_low, omega_high, alpha_high, gamma_high, beta_high]` (8 total)
- Estimation: Gaussian MLE, `scipy.optimize.minimize L-BFGS-B`, **20 multistart** per threshold

### Standard GJR-GARCH Baseline

Same scipy MLE framework, 20 multistart — identical estimation approach for fair comparison.

### Lookahead Prevention

- `data['VIX_lag'] = data['VIX'].shift(1)` applied **first**, before any train/test split
- IS recursion: regime at step `t` uses `vix_lag_is[t]` = VIX_{t-1}; shock uses `returns[t-1]`
- OOS recursion: same structure; first OOS step uses last IS return as `r_{t-1}`
- Both models use identical lag structure — fair comparison

---

## Results

### OOS Evaluation (2019–2026, 1,824 obs)

| Model | OOS QLIKE | OOS MSE |
|-------|-----------|---------|
| GJR (baseline) | **1.4956** | 2.717e-07 |
| TGJR (joint MLE, c=14) | 1.4750 | 2.727e-07 |
| Improvement | +1.38% | −0.37% |

TGJR improves QLIKE by 1.38% in point estimates but the improvement is **not statistically significant**.

### Diebold-Mariano Test (QLIKE loss, HAC Newey-West, max_lag=24)

| Statistic | Value |
|-----------|-------|
| DM stat (GJR vs TGJR) | 1.1047 |
| p-value | 0.2693 |
| Significant at 5%? | No |
| Winner (point estimate) | TGJR |

### Optimal Threshold: c = 14

Grid search over IS QLIKE — c=14 gives the best IS fit across all thresholds tested.

| c | IS QLIKE | Low% | High% | Low pers. | High pers. |
|---|----------|------|-------|-----------|------------|
| **14** | **1.6010** | 33.8% | 66.2% | 0.538 | 0.970 |
| 16 | 1.6013 | 48.0% | 52.0% | 0.855 | 0.969 |
| 18 | 1.6043 | 59.4% | 40.6% | 0.833 | 0.964 |
| 20 | 1.6180 | 67.9% | 32.1% | 0.926 | 0.942 |
| 22 | 1.6197 | 74.9% | 25.1% | 0.947 | 0.961 |
| 24 | 1.6237 | 80.9% | 19.1% | 0.958 | 0.995 |

### TGJR Parameters (c=14, Joint MLE)

| Parameter | Low VIX (≤14) | High VIX (>14) |
|-----------|---------------|----------------|
| omega | 1.698e-05 | 4.415e-06 |
| alpha | 1.0e-06 (lb) | 1.0e-06 (lb) |
| gamma | 0.4908 | 0.1698 |
| beta | 0.2925 | 0.8850 |
| **persistence** | **0.538** | **0.970** |

Both regimes satisfy the stationarity condition (persistence < 0.999).

The striking difference: low-VIX periods show **very low persistence (0.54)** — shocks dissipate quickly when markets are calm. High-VIX periods show near-unit-root persistence (0.97) — volatility clusters strongly during stress. The `alpha` parameter hits its lower bound in both regimes; the asymmetric `gamma` (leverage) term dominates.

### Regime-Conditional OOS QLIKE

| Regime (OOS) | N | GJR | TGJR | Improvement |
|---|---|-----|------|-------------|
| Low VIX (≤14) | 280 (15.4%) | 1.6149 | 1.5743 | +2.52% |
| High VIX (>14) | 1,544 (84.6%) | 1.4740 | 1.4570 | +1.15% |

TGJR improves in **both** regimes — the gain is larger in the low-VIX regime that was directly targeted during IS fitting.

### VaR Backtesting

| Level | Model | Violations | Rate | Expected | Kupiec p |
|-------|-------|-----------|------|----------|---------|
| 1% | GJR | 37/1824 | 2.03% | 1.00% | 0.0001 FAIL |
| 1% | TGJR | 35/1824 | 1.92% | 1.00% | 0.0005 FAIL |
| 5% | GJR | 107/1824 | 5.87% | 5.00% | 0.0981 PASS |
| 5% | TGJR | 93/1824 | 5.10% | 5.00% | 0.8471 PASS |

Both models fail Kupiec at 1% VaR — consistent with known heavy-tail behavior of equity returns. At 5%, TGJR passes comfortably (p=0.847), slightly better than GJR.

---

## Comparison to K980

| Item | K980 (FAIL) | K980v2 (this) |
|------|-------------|----------------|
| Estimation | Subset-wise (mismatch) | Joint MLE (full series) |
| GJR OOS QLIKE | 1.4989 | 1.4956 (−0.22%, consistent) |
| TGJR OOS QLIKE | 1.5032 (worse than GJR) | 1.4750 (better than GJR) |
| TGJR vs GJR | +0.29% (TGJR worse) | −1.38% (TGJR better) |
| DM p-value | 0.748 | 0.269 |
| Verdict | NULL | NULL |

K980's misspecified TGJR performed worse than GJR because the subset-estimated parameters were trained on the wrong objective (discontinuous h_t). With joint MLE, TGJR improves by 1.38% — but still not significant at conventional levels.

The NULL conclusion is **confirmed but weakened**: proper estimation reveals TGJR has a small positive signal (p=0.27), not the near-zero effect in K980 (p=0.75).

---

## Conclusion

Correct joint-MLE estimation of Threshold GJR-GARCH improves OOS QLIKE by **1.38%** relative to a standard GJR-GARCH baseline, but the DM test gives **p=0.269** — not significant at the 5% level. The result is classified as **EXPLORATORY_NULL**.

The experiment confirms that K980's NULL conclusion was not an artifact of the estimation flaw (it remains null under correct estimation), but the magnitude and direction of the effect change meaningfully: K980 estimated TGJR as 0.29% *worse* than GJR; K980v2 shows it is 1.38% *better*. The difference is economically plausible — joint MLE recovers the correct trade-off between low-VIX (fast mean-reversion, persistence=0.54) and high-VIX (persistent clustering, persistence=0.97) dynamics.

**Limitations**:
- 20 multistart per threshold — low-regime `alpha` hits lower bound (1e-6) in all c values, suggesting possible local optimum or model misspecification in the ARCH term
- Gaussian likelihood used for estimation; heavy-tail distribution (Student-t) may change results
- Single asset (SPY); cross-asset validation needed before claiming generalizability

---

## Files

| File | Description |
|------|-------------|
| `k980v2.py` | Full experiment script (joint MLE, grid search, evaluation) |
| `k980v2_results.json` | All metrics (QLIKE/MSE/DM/VaR/params) |
| `k980v2_oos_comparison.png` | OOS volatility forecasts + cumulative QLIKE diff + VIX regime |
| `k980v2_regime_parameters.png` | TGJR parameter comparison by regime |

## References

- Glosten, Jagannathan & Runkle (1993, JoF): GJR-GARCH model
- Zakoian (1994): Threshold heteroskedastic models
- Patton (2011, J Econometrics): QLIKE loss for volatility forecast comparison
- Diebold & Mariano (1995, JBES): Comparing predictive accuracy
- Hansen & Lunde (2005, J Econometrics): Forecast comparison of volatility models
