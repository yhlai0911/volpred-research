# K1098: A4f on 0050.TW with TAIFEX VIXTWN — Taiwan-Matched IV Pilot

[提出: Claude (Paper 10 side paper candidate), 執行: Claude]
Experiment date: 2026-04-12 · OOS 2013-01 ~ 2021-12 · Harvey |t|>3.0

---

## 1. Motivation

Paper 9 found that A4f-VIX fails Harvey threshold on 0050.TW:
- **K1077**: A4f-VIX on 0050.TW (OOS 2010-2025) DM **t = -0.49 NS**
- **K1083**: USD/TWD currency explains 83% of the US→TW gap
- **K1085** (GLD-GVZ): asset-matched IV **PASS t=+4.46**
- **K1088** (USO-OVX): asset-matched IV **PASS t=+4.48**

TAIFEX publishes **VIXTWN** (台指選擇權 30-day implied volatility) since 2006.
Does Taiwan have its own asset-matched IV that rescues 0050.TW — as GVZ
rescued gold and OVX rescued oil?

K997 tested VIXTWN briefly with short data. **K1098 is the full 15-year
Dropbox official VIXTWN pilot** (2007-2021).

## 2. Research Questions

| # | Hypothesis | Threshold |
|---|------------|-----------|
| H1 | A4f-VIXTWN on 0050.TW DM Harvey PASS | t > +3.0 vs GJR |
| H2 | VIXTWN beats VIX head-to-head | DM t > +3, QLIKE VIXTWN < VIX |
| H3 | COMBO (VIX + VIXTWN) strictly better than both | both DMs t > +3 |
| H4 | VIXTWN rescues K1083 structural currency gap | H1 PASS |

## 3. Data

| Source | What | Period | n |
|--------|------|--------|---|
| yfinance `0050.TW` + `clean_tw50_data` | daily close, 1:4 split adjusted | 2009-01 ~ 2021-12 | 3,192 |
| yfinance `^VIX` | US VIX daily close | 2007-01 ~ 2021-12 | (ffilled) |
| TAIFEX Dropbox `~/Dropbox/TAIFEXDATA/vix/VIX/新_每日收盤VIX/` | VIXTWN 30-day IV | 2007-01 ~ 2021-12 | 3,701 raw |

**VIXTWN parser**: 15 year-folders × 12 months = 180 monthly files parsed.
Handles variable column format (2/3/5/7 tab-fields across years, including
the 2007-10/11 edge case where date and code are space-fused). Produces
`k1098_vixtwn_daily.csv`.

**Alignment**: 0050.TW trading days are the master index; VIX and VIXTWN
are forward-filled to handle non-overlapping holidays (US vs TW).

## 4. Methods

### Models

| Model | τ (long-run component) | g (short-run GJR) |
|-------|------------------------|-------------------|
| GJR   | (none, standard GJR-GARCH) | ω+α·r²+γ·r²·I(r<0)+β·h |
| A4f-VIX | θ₀ + θ₁·VIX²_{t-1} | Engle (2013) multiplicative |
| **A4f-VIXTWN** | θ₀ + θ₁·VIXTWN²_{t-1} | same |
| A4f-COMBO | θ₀ + θ₁·VIX² + θ₂·VIXTWN² | same |

Engle–Ghysels–Sohn (2013) multiplicative structure: σ²_t = τ_t · g_t,
with u_{t-1} = r_{t-1}/√τ_t feeding the GJR short-run.

### Estimation

- Rolling window = 1000 days (~4 years), quarterly refit (every 63 days)
- OOS: **2013-01-02 ~ 2021-12-30 (n = 2,199 days, 35 refits)**
- L-BFGS-B with 3 starts, random seed 42
- 4 models fit in parallel per refit (~4.5 s/refit)

### Evaluation

| Metric | Purpose |
|--------|---------|
| QLIKE on r² (Patton 2011) | proxy-robust volatility loss |
| DM test + Newey-West HAC (Harvey 2016) | \|t\|>3.0 conservative significance |
| 1,000-rep stationary bootstrap | 95% CI for loss differentials |
| Spearman rank correlation with r² | distributional robustness |
| Regime analysis | VIXTWN independent info in high-spread periods |

## 5. Results

### 5.1 QLIKE (lower = better)

| Model | QLIKE | Δ vs GJR |
|-------|-------|----------|
| GJR | -8.3454 | — |
| A4f-VIX | -8.3900 | -0.53% |
| **A4f-VIXTWN** | -8.3768 | **-0.38%** |
| A4f-COMBO | -8.3909 | -0.55% |

### 5.2 DM Tests (positive t = X beats GJR)

| Comparison | DM t | p | Harvey |
|-----------|------|---|--------|
| A4f-VIX vs GJR | +2.68 | 0.0074 | **FAIL** |
| **A4f-VIXTWN vs GJR** | **+1.86** | **0.063** | **FAIL** |
| A4f-COMBO vs GJR | +2.80 | 0.0051 | **FAIL** |
| A4f-VIXTWN vs A4f-VIX | -0.99 | 0.32 | VIX slightly better |
| A4f-COMBO vs A4f-VIXTWN | +1.51 | 0.13 | NS |
| A4f-COMBO vs A4f-VIX | +0.14 | 0.89 | NS |

### 5.3 Hypothesis Verdicts

| H | Verdict | Evidence |
|---|---------|----------|
| **H1** (VIXTWN Harvey PASS) | **FAIL** | t=+1.86 < 3.0 |
| **H2** (VIXTWN beats VIX) | **FAIL** | t=-0.99, QLIKE VIX < VIXTWN |
| **H3** (COMBO strictly best) | **FAIL** | COMBO vs VIX t=+0.14; vs VIXTWN t=+1.51 |
| **H4** (Rescue K1083 gap) | **FAIL** | Structural gap not fixable via IV choice |

### 5.4 VIX vs VIXTWN Diagnostics

- **Correlation (levels)**: 0.870
- **Correlation (log-diff)**: 0.203
- **Max VIXTWN**: 60.41 on 2008-10-28 (GFC)
- **Max VIX**: 82.69 on 2020-03-16 (COVID)
- High-spread regime (VIXTWN-VIX z > +0.66, n=441): VIXTWN still does **not**
  beat VIX (DM t=-1.30)

### 5.5 θ₁ Stability (35 quarterly refits)

| Model | θ₁ median | θ₁ max | Stability |
|-------|-----------|--------|-----------|
| A4f-VIX | 2.00e-07 | 3.45e-03 | VIX loading spikes during crises |
| A4f-VIXTWN | 1.99e-07 | 9.82e-05 | VIXTWN loading more stable, smaller max |
| A4f-COMBO θ₁(VIX) | 1.56e-07 | 6.15e-03 | redistributes most weight to VIX |
| A4f-COMBO θ₂(VIXTWN) | 4.57e-08 | 3.54e-03 | secondary role |

COMBO's heavier reliance on VIX (by median loading magnitude) is consistent
with VIX providing richer crisis signal, but the COMBO fit suffers from
identification issues due to 0.87 level-correlation between VIX and VIXTWN.

## 6. Interpretation

**Core finding**: VIXTWN does **not** rescue Taiwan's asset-matched-IV gap.

This differs sharply from the commodity markets:
- GLD-GVZ: Harvey PASS t=+4.46 (K1085)
- USO-OVX: Harvey PASS t=+4.48 (K1088)
- **0050.TW-VIXTWN: FAIL t=+1.86 (K1098)**

### Why doesn't VIXTWN help?

1. **Currency dominance (K1083)**: 83% of the US→TW gap is the USD/TWD
   channel. A domestic equity IV cannot neutralize currency exposure that
   enters through the ETF's underlying basket.

2. **VIX already contains Taiwan-relevant info**: VIX and VIXTWN level-correlate
   at 0.87. VIXTWN is effectively a filtered version of VIX with minor
   idiosyncratic Taiwan risk.

3. **TSMC concentration (Paper 9 hypothesis)**: 0050.TW has ~55% TSMC weight.
   TSMC earnings-driven vol is not in VIXTWN's measurement (which uses
   TAIEX options, broader than TWSE 50).

4. **Spearman ranks agree**: VIX (0.211) > VIXTWN (0.201) — rank-order
   agreement is slightly stronger for VIX.

### Implication for Paper 10

**Paper 10 side paper "Taiwan Asset-Matched IV for Volatility Forecasting"
is NOT supported by this pilot.** The cross-market asset-matched IV result
(K1085, K1088) does not generalize to Taiwan equities.

**Instead**, Paper 10 should pursue:
- Currency-augmented A4f for 0050.TW (combine US VIX + USD/TWD realized vol)
- TSMC-concentration adjustment (weighted 50/50 TWSE index vs cap-weighted)
- Cross-Strait news index as an alternative Taiwan-specific regressor

## 7. Limitations

- **OOS 2013-2021**: misses the 2011 European crisis and the post-2022 rate
  regime. 0050.TW yfinance data begins 2009 so 1000-day warmup limits us to
  2013+ start.
- **VIXTWN data ends 2021-12**: Dropbox archive stops there; post-2021
  VIXTWN needs separate collection.
- **COMBO identifiability**: VIX/VIXTWN level-correlation 0.87 means the
  individual θ₁/θ₂ loadings are not independently interpretable. The
  performance comparison is still valid (predictions are identified even
  when parameters are not).
- **Single asset**: 0050.TW only. Cross-strait extension (TWII, 0056.TW,
  2330.TW individual stock) could reveal heterogeneity.
- **Null result does not prove uselessness**: VIXTWN may still help for
  other tasks (tail risk, option pricing) not captured by QLIKE on r².

## 8. Files

| File | Purpose |
|------|---------|
| `k1098.py` | Main experiment script (parser + model + OOS loop) |
| `k1098_results.json` | Full numeric results |
| `k1098_vixtwn_daily.csv` | Parsed VIXTWN daily series (for reuse) |
| `k1098_dm_comparison.png` | Bar chart: DM t vs GJR + QLIKE |
| `k1098_vix_vs_vixtwn.png` | Time-series overlay |
| `k1098_theta1_evolution.png` | Quarterly θ₁ loadings over refits (log scale) |

## 9. Upstream / Downstream

**Upstream**:
- K1077 (0050.TW A4f-VIX DM -0.49 NS, 2010-2025)
- K1083 (USD/TWD 83% of gap)
- K1085 (GLD-GVZ PASS)
- K1088 (USO-OVX PASS)
- K997 (VIXTWN brief)

**Downstream candidates** (derived from this null result):
- **K1099**: 0050.TW A4f with USD/TWD realized vol as the exogenous term
  (directly attacks the K1083 currency channel)
- **K1100**: Restricted TWSE-50 replica vol vs 0050.TW (isolate TSMC effect)
- **K1101**: Tests on individual large-cap TW stocks (2330.TW TSMC, 2317.TW
  Foxconn) — does VIXTWN help when TSMC is isolated?

## 10. References

1. Engle, R., Ghysels, E., & Sohn, B. (2013). Stock Market Volatility and
   Macroeconomic Fundamentals. *Review of Economics and Statistics*, 95(3),
   776–797.
2. Patton, A. J. (2011). Volatility forecast comparison using imperfect
   volatility proxies. *Journal of Econometrics*, 160(1), 246–256.
3. Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of
   prediction mean squared errors. *International Journal of Forecasting*,
   13(2), 281–291.
4. TAIFEX (2006). VIXTWN White Paper — Taiwan Volatility Index
   Specification.

## 11. Reproduction

```bash
cd /Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-ac306346
uv run python experiments/k1098/k1098.py
```

Requirements: yfinance, numpy, scipy, pandas, statsmodels, numba (optional),
matplotlib. VIXTWN data at `~/Dropbox/TAIFEXDATA/vix/VIX/新_每日收盤VIX/`.

Runtime: ~160 seconds on M1 Max.
Random seed: 42 (reproducible).
