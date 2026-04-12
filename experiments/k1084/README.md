# K1084: Realized Skewness and Kurtosis — Higher-Order Moments for Volatility Prediction

**Status**: PRELIMINARY (60-day 5-min sample, OOS n=30)
**Date**: 2026-04-12
**Prior experiments**: K1057 (jumps NULL), K1063 (semi-variance PASS), K1065 (overnight/intraday)
**Random seed**: 42

---

## 1. Problem Description & Motivation

K1063 showed that decomposing RV into upside (RV+) and downside (RV-) semi-variances
captures a meaningful asymmetry (t ≈ 3.10). But semi-variance only uses the sign of
intraday returns, not their full distributional shape. This experiment asks whether
**higher-order realized moments** — realized skewness (RSk) and realized kurtosis (RKt)
— carry additional predictive content beyond what HAR-RV and HAR-semi-variance already
extract.

### Why it matters

- If higher moments add signal → Paper 9 (HAR-A4f extension) should upgrade from
  semi-variance to HAR-SK-KT with Cornish-Fisher VaR.
- If they are NULL → semi-variance (K1063) already captures all the asymmetry /
  tail-shape signal that is predictable at the daily horizon, and Paper 9 should stay
  with HAR-SV.

### Research questions

| # | Hypothesis | Evaluation |
|---|-----------|------------|
| H1 | RSk has incremental predictive power for RV_{t+1} controlling for HAR-RV | DM test HAR-RSk vs HAR-RV, Harvey \|t\|>3.0 |
| H2 | RKt predicts tail risk (improves VaR via Cornish-Fisher) | Kupiec (1995) LR test at 5% and 1% |
| H3 | HAR-Full (RV+RSk+RKt+SJ) beats HAR-RV | DM test HAR-Full vs HAR-RV |
| H4 | Higher-moment effects are regime-dependent (Low vs High VIX) | Sub-sample QLIKE + regime DM |

---

## 2. Method

### Data
- **5-min SPY**: `data/intraday/SPY_5min_YYYY-MM-DD.csv`, 60 files, 2026-01-14 → 2026-04-10.
- **Daily SPY / ^VIX**: yfinance (for leverage diagnostics, regime split, VaR target).

### Moment definitions (ACJV 2015 standardisation)

For each day t with N 5-min returns {r_i}:

```
RV_t  = Σ r_i²
RSk_t = √N · Σ r_i³ / RV_t^{1.5}          (BM null mean = 0)
RKt_t = N   · Σ r_i⁴ / RV_t²              (BM null mean = 3)
SJ_t  = RV+_t − RV−_t                      (BNKS 2010 / PS 2015)
```

### Models compared (target: RV_{t+1})

| Model | Features |
|-------|----------|
| HAR-RV (baseline) | RV_d, RV_w, RV_m |
| HAR-RSk | + RSk_{t−1} |
| HAR-RKt | + RKt_{t−1} |
| HAR-SJ | + SJ_{t−1} |
| HAR-Full | + RSk + RKt + SJ |
| GJR-GARCH | w=2000 rolling refit, daily r² target |
| A4f-VIX² | VIX²_{t−1} / 252 |

OLS expanding window, INIT_WINDOW=30 → OOS n=30 days. QLIKE loss (Patton 2011),
DM test with Newey-West HAC, Harvey (2016) \|t\|>3.0 threshold.

### VaR methods

At α ∈ {5%, 1%} with σ² = HAR-RV forecast:
- Normal: z_α · σ
- Student-t (df=5 fixed): scale-corrected
- Cornish-Fisher (RKt + RSk adjusted): 4th-order expansion with winsorised lag
  predictors

Kupiec LR unconditional coverage test, pass = p > 0.05.

---

## 3. Results

### 3.1 Descriptive

| Moment | Mean | Std | BM null | t-stat | p |
|--------|------|-----|---------|--------|---|
| RV | 7.55e-05 | — | — | — | — |
| RSk | +0.059 | 0.74 | 0 | +0.61 | 0.542 |
| RKt | +4.49 | 1.73 | 3 | +6.69 | **<0.001** |
| SJ | — | — | — | — | — |

- **Excess kurtosis confirmed**: mean RKt = 4.49 (vs BM null 3), strongly significant.
- **No mean asymmetry**: RSk mean is not significantly different from 0.
- **Negative serial correlation in RSk** (ACF(1) = −0.462) — sign flips day-to-day.
- **Leverage detected**: corr(r_t, RSk_{t+1}) = −0.136 (weak).

### 3.2 HAR variants OOS (n=30)

| Model | QLIKE | MSE | DM vs HAR-RV | Harvey sig? |
|-------|-------|-----|--------------|-------------|
| HAR-RV | **−8.5973** | 1.07e-09 | — | — |
| HAR-RSk | **−8.6214** | 8.87e-10 | t=−1.78, p=0.086 | No (weak) |
| HAR-RKt | −8.5805 | 1.00e-09 | t=+0.67, p=0.507 | No |
| HAR-SJ | −8.6116 | 8.87e-10 | t=−0.83, p=0.413 | No |
| HAR-Full | −8.5758 | 9.15e-10 | t=+0.53, p=0.600 | No |
| GJR-GARCH | −8.5042 | — | — | — |
| A4f-VIX² | −8.0742 | — | — | — |

**Best model: HAR-RSk** (QLIKE = −8.6214, 0.28% better than HAR-RV).
However, **no model crosses Harvey \|t\|>3.0**, so all improvements are within noise.

### 3.3 Full-sample coefficients (interpretation only)

Most notable: **HAR-SJ** shows SJ_d coefficient = −0.78 with **t = −3.10** — consistent
with K1063's finding that downside half-variance dominates. But when pooled with RSk
and RKt in HAR-Full, individual coefficients become insignificant (t=−0.59 for SJ),
suggesting collinearity among higher-moment regressors in this short sample.

### 3.4 VaR backtest

| α | Method | Viol / N | Rate | Kupiec p | Pass? |
|---|--------|----------|------|----------|-------|
| 5% | Normal | 6/30 | 20.0% | 0.004 | **FAIL** |
| 5% | Student-t df=5 | 6/30 | 20.0% | 0.004 | **FAIL** |
| 5% | Cornish-Fisher | 5/30 | 16.7% | 0.019 | **FAIL** |
| 1% | Normal | 1/30 | 3.3% | 0.311 | PASS |
| 1% | Student-t df=5 | 0/30 | 0.0% | 1.000 | PASS |
| 1% | Cornish-Fisher | 1/30 | 3.3% | 0.311 | PASS |

- **5% VaR: all methods fail Kupiec** — HAR-RV σ² forecast systematically under-estimates
  variance during the 2026-Q1 OOS period (market was volatile, realized violations 17-20%
  vs target 5%).
- **1% VaR: all methods pass**, but sample n=30 is too small for strong inference.
- **Cornish-Fisher does NOT materially improve** over Normal in this sample — the
  RKt-based tail adjustment helps marginally at 5% (6→5 violations) but still fails.

### 3.5 Regime analysis (VIX median split = 24.74)

| Model | Low-VIX QLIKE | High-VIX QLIKE |
|-------|---------------|----------------|
| HAR-RV | −8.7188 | −8.4758 |
| HAR-RSk | **−8.7644** | −8.4784 |
| HAR-RKt | −8.6794 | −8.4817 |
| HAR-Full | −8.6652 | **−8.4864** |

- **Low-VIX**: HAR-RSk wins (RSk helps when markets are calm).
- **High-VIX**: HAR-Full slightly wins (all higher moments help when volatile) — but
  none of the regime differences cross Harvey threshold.

---

## 4. Verdict & Conclusions

| Hypothesis | Result |
|-----------|--------|
| H1 — RSk beats HAR | **NULL** (t=−1.78, not Harvey-significant) |
| H2 — RKt predicts tail (Cornish-Fisher VaR) | **NULL** at 5% (all fail Kupiec); PASS at 1% but no improvement over Normal |
| H3 — HAR-Full beats HAR-RV | **NULL** (t=+0.53, worse than baseline) |
| H4 — Regime-dependent effects | Suggestive (low-VIX favours RSk, high-VIX favours Full) but not significant |

### Main take-aways

1. **Higher moments do NOT add Harvey-significant predictive power** for RV_{t+1} in
   this 60-day sample.
2. **Semi-variance (K1063) already captures the asymmetry signal** — HAR-SJ's full-sample
   SJ coefficient has t=−3.10, consistent with K1063. When RSk/RKt are added on top of SJ,
   the new regressors do not contribute.
3. **Cornish-Fisher VaR provides modest tail-shape correction** but does not fix the
   systematic under-estimation of 5% VaR in the 2026-Q1 volatile period. The problem is
   the HAR-RV point-estimate σ² forecast, not the quantile method.
4. **Paper 9 recommendation**: retain the HAR-semi-variance specification from K1063.
   Do not upgrade to HAR-Full higher-moment specification until a longer sample confirms
   the signal.

---

## 5. Limitations

- **PRELIMINARY** sample: 60 5-min days, OOS n=30. Harvey \|t\|>3.0 requires ~40+ OOS
  observations for stable inference even with strong effects.
- **5-min noise**: RSk / RKt are highly sensitive to microstructure noise. A longer
  sample with tick-level data (or pre-averaging estimators like MedRV) may reveal signal
  currently hidden by noise.
- **Fixed df in Student-t VaR** (df=5): no estimation, just a conservative benchmark.
- **BM null interpretation**: mean(RKt)=4.49 significantly > 3 → evidence of jumps or
  fat-tailed intraday innovations, but this does not imply predictability of future
  kurtosis.
- **Regime n=15 each**: too small for formal inference. Treat regime signs as
  directional only.
- **One asset (SPY)**: should be replicated on 0050.TW when Taiwan 5-min data has
  sufficient coverage (K1085+).

---

## 6. Next Steps

1. **K1085 (TW extension)**: repeat on 0050.TW 5-min once data has ≥ 60 days. Taiwan
   often shows different kurtosis dynamics than US.
2. **K1086 (longer sample)**: re-run K1084 when US 5-min backfill extends to ≥ 252 days
   (one year). Harvey threshold inference will be meaningful.
3. **K1087 (MedRV / BV robustness)**: repeat with bipower / MedRV jump-robust estimators
   to see if results are driven by jump contamination.
4. **K1088 (pre-averaged estimators)**: use Jacod-Li-Mykland pre-averaging (e.g. 10-min
   subsample) to reduce microstructure noise in RSk/RKt.
5. **Paper 9 decision**: stick with HAR-SV (from K1063) unless K1086 overturns this
   verdict.

---

## 7. Files

| File | Purpose |
|------|---------|
| `k1084.py` | Full experiment script (deterministic, seed=42) |
| `k1084_results.json` | Machine-readable results + full summary |
| `k1084_moments_ts.png` | RV, RSk, RKt time-series plot |
| `k1084_moments_scatter.png` | Scatter: RV vs RSk, \|RSk\|, RKt |
| `k1084_har_extended.png` | HAR variants QLIKE bar chart |
| `k1084_var_tail.png` | Actual returns vs Normal / Cornish-Fisher VaR |
| `k1084_regime_analysis.png` | Low-VIX vs High-VIX QLIKE by model |
| `README.md` | This document |

---

## 8. References

- Amaya, D., Christoffersen, P., Jacobs, K., & Vasquez, A. (2015). "Does realized
  skewness predict the cross-section of equity returns?" *Journal of Financial
  Economics* 118(1), 135–167.
- Barndorff-Nielsen, O. E., Kinnebrock, S., & Shephard, N. (2010). "Measuring downside
  risk-realised semivariance." In *Volatility and Time Series Econometrics* (Festschrift
  for R. Engle).
- Corsi, F. (2009). "A simple approximate long-memory model of realized volatility."
  *Journal of Financial Econometrics* 7(2), 174–196.
- Harvey, C. R. (2016). "…and the cross-section of expected returns." *Review of
  Financial Studies* 29(1), 5–68.
- Neuberger, A. (2012). "Realized skewness." *Review of Financial Studies* 25(11),
  3424–3455.
- Patton, A. J. (2011). "Volatility forecast comparison using imperfect volatility
  proxies." *Journal of Econometrics* 160(1), 246–256.
- Patton, A. J., & Sheppard, K. (2015). "Good volatility, bad volatility: Signed jumps
  and the persistence of volatility." *Review of Economics and Statistics* 97(3),
  683–697.

---

*K1084 verdict: NULL for higher moments, but confirms K1063's semi-variance /
signed-jump finding. Paper 9 stays with HAR-SV.*
