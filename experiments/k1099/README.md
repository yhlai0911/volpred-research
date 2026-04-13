# K1099: 0050.TW A4f with USD/TWD Realized Vol — Direct Currency Channel Attack

**Proposer / Executor**: [提出: 用戶, 執行: Claude]
**Date**: 2026-04-12
**Status**: Complete — all four hypotheses FAIL

## Problem

K1077 demonstrated that A4f with `τ = θ₀ + θ₁·VIX²_{t-1}` does not transmit
useful information to 0050.TW volatility forecasts (full OOS 2010-2025
DM t=-0.49 NS, Harvey FAIL). K1083 decomposed the Taiwan→EWT forecasting gap
and attributed ~83% to the **USD currency wrapper** (not domestic composition
or idiosyncratic equity effects). K1098 (proposed companion) asks whether
**domestic** implied vol (VIXTWN) can rescue A4f on 0050.TW; the working
hypothesis is that domestic IV cannot fix an FX-channel problem.

## Motivation

If currency *is* the root cause identified by K1083, then the regressor that
should work on 0050.TW is **FX realized volatility**, not US VIX nor domestic
VIXTWN. Paper 10 ("Currency-Denomination Mismatch in Cross-Market GARCH-MIDAS")
hinges on whether a *simple FX-vol proxy* restores transmission.

## Methodology

### Data

| Series | Source | Range | Transform |
|---|---|---|---|
| 0050.TW Close | yfinance (`0050.TW`) | 2005-07 ~ 2025-12 | `clean_tw50_data` (mandatory Yahoo 2014 split fix) |
| ^VIX Close | yfinance (`^VIX`) | same | forward-fill to TW trading days |
| TWDUSD=X Close | yfinance (`TWDUSD=X`) | same | K1083 corrupted-close repair (H+L median) → ffill |

### FX realized vol construction

- **FXVOL_RV21** (primary): `sqrt((1/21) · Σ r_fx²_{t-i} · 252) · 100` — rolling 21-day annualized vol in percent, matching VIX scale.
- **FXVOL_EWMA** (sensitivity): RiskMetrics EWMA with λ=0.94, annualized %.

### Models (all rolling W=2000, refit every 63 days; seed 42)

| Code | τ specification |
|---|---|
| GJR | Standard GJR-GARCH(1,1) |
| A4f_VIX | τ = max(θ₀ + θ₁·VIX²_{t-1}, ε); g = GJR; σ² = τ·g |
| A4f_FX | τ = max(θ₀ + θ₁·FXVOL_RV21²_{t-1}, ε); g = GJR |
| A4f_COMBO | τ = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·FXVOL_RV21²_{t-1}, ε); g = GJR |

All A4f share Engle et al. (2013) multiplicative `σ²_t = τ_t · g_t` with
`u_{t-1} = r_{t-1}/√τ_t` inside g.

### Evaluation

- QLIKE on `r²` (Patton 2011 proxy-robust loss).
- HAC DM test with Newey-West lag `⌊T^{1/3}⌋`; Harvey (2016) |t|>3.0 threshold for 2026 standards.
- Spearman rank correlation between forecast and `r²` (distribution-free).
- 1000-rep overlapping-block bootstrap for QLIKE-diff CIs.

### Decomposition dimensions

1. **Full OOS** (2010-2025, ~3,900 obs joint valid).
2. **Per window**: Early 2010-2014, Middle 2015-2019, Late 2020-2025.
3. **FX-focused crises**: Euro 2011, Taper Tantrum 2013, TWD devaluation 2015,
   COVID 2020, Bear 2022.
4. **FX regime terciles**: OOS FXVOL_RV21 bottom/middle/top tercile. Test
   whether high-FX-vol periods amplify A4f_FX's advantage over A4f_VIX.

## Hypotheses

- **H1**: A4f_FX on 0050.TW Harvey-PASS vs GJR full OOS (|t|>3).
- **H2**: A4f_FX vs A4f_VIX — FX channel more predictive than US VIX.
- **H3**: COMBO (VIX² + FXVol²) dominates both solos.
- **H4**: In the top-tercile FX-vol regime, A4f_FX strictly beats A4f_VIX.

## Expected outcomes

Two possible worlds:

| Scenario | Implication |
|---|---|
| Any of H1-H4 materially supported | **Paper 10 revival**: FX realized vol is the correct τ driver for non-US ETFs. Novel contribution: the regressor must match the *currency denomination*, not the underlying market. |
| All four FAIL | Taiwan is structurally unrescuable for A4f. Combined with K1083 (FX = 83% of gap) and K1098 (VIXTWN insufficient), this closes the case: non-US ETFs inherit an FX noise component that no τ regressor can absorb. |

## Files

- `k1099.py` — Full experiment script (data loading, A4f-single/combo estimators,
  OOS loop, pairwise DM, bootstrap, regime split, figures).
- `k1099_results.json` — All numeric results (pairwise DM, per-window, crisis,
  FX regime, refit log with θ₁/θ₂ trajectories).
- `k1099_dm_comparison.png` — Full OOS DM t vs GJR and vs A4f_VIX (4-bar chart).
- `k1099_fxvol_ts.png` — FX realized vol time series (RV_21 + EWMA, with tercile
  bands and shaded crisis periods).
- `k1099_regime_analysis.png` — Mean QLIKE by FX regime for all 4 models, with
  per-regime DM(FX vs VIX) annotations.

## References

- Engle, Ghysels, Sohn (2013). "Stock market volatility and macroeconomic
  fundamentals". *Rev. Econ. Stat.* 95(3):776-797.
- Conrad & Loch (2015). "Anticipating long-term stock market volatility".
  *J. Bus. Econ. Stat.*
- Patton (2011). "Volatility forecast comparison using imperfect volatility
  proxies". *J. Econometrics* 160:246-256.
- Harvey, Leybourne, Whitehouse (2016). "Multiple-horizon forecast equality
  testing" (Harvey 2016 t>3 threshold).
- **Internal**: K1058 (0050.TW short OOS NS), K1077 (0050.TW extended NS),
  K1083 (FX 83% of Taiwan→EWT gap), K1085 (GLD GVZ PASS — asset-matched
  regressor), K1098 (VIXTWN domestic IV test — pending/complementary).

## Results

### Diagnostic smoking gun (pre-model, 2009-2025)

| Pair | Pearson correlation |
|---|---|
| FXVOL_RV21 vs 21-day realized vol of 0050.TW | **+0.014** |
| VIX vs 21-day realized vol of 0050.TW | **+0.601** |
| FXVOL_RV21 vs VIX | −0.028 |

FX realized vol and 0050.TW realized vol are essentially uncorrelated. US VIX
carries 42× more linear information about Taiwan's realized vol than TWD/USD
FX realized vol does. Any MIDAS-style long-run component fed by FXVol² cannot
outperform GJR — the signal simply isn't there.

### Full OOS (2010-2025, n=3,913, 64 refits)

| Model | QLIKE (lower better) | Spearman(fc, r²) | DM t vs GJR |
|---|---:|---:|---:|
| GJR | −8.11478 | 0.200 | — |
| A4f_VIX | −8.10131 | 0.241 | −0.27 |
| A4f_FX | −8.10730 | 0.192 | −1.45 |
| A4f_COMBO | −8.04719 | 0.235 | −0.85 |

Pairwise DM vs A4f_VIX: FX t=+0.12 (indifferent), COMBO t=−0.97.

### Per-window

| Window | n | QL_GJR | QL_VIX | QL_FX | QL_COMBO |
|---|---:|---:|---:|---:|---:|
| Early 2010-2014 | 1237 | −8.289 | −8.130 | −8.266 | −7.974 |
| Middle 2015-2019 | 1219 | −8.448 | −8.500 | −8.434 | −8.489 |
| Late 2020-2025 | 1457 | −7.689 | −7.744 | −7.699 | −7.740 |

Middle 2015-2019 shows A4f_VIX vs A4f_FX DM t=−3.67 (Harvey-PASS, VIX strictly
dominates FX). No window where FX wins Harvey over GJR.

### FX regime analysis (OOS FXVOL_RV21 terciles: q33=4.44%, q67=7.63%)

| Regime | n | QL_GJR | QL_VIX | QL_FX | FX vs VIX DM t |
|---|---:|---:|---:|---:|---:|
| Low_FXVol | 1291 | −8.226 | −8.099 | −8.210 | +0.81 |
| Mid_FXVol | 1331 | −8.027 | −8.062 | −8.035 | −1.52 |
| **High_FXVol** | 1291 | −8.094 | **−8.144** | −8.079 | **−3.50 (Harvey-PASS, VIX>FX)** |

**H4 strictly inverted**: in the high-FX-vol tercile (the regime where
FX-channel pain should dominate), A4f_VIX is Harvey-significantly *better* than
A4f_FX. This is the regime where the FX hypothesis most strongly predicts the
opposite. Direct falsification.

### Hypothesis verdicts

| ID | Claim | Verdict | Key stat |
|---|---|---|---|
| H1 | A4f_FX Harvey-PASS vs GJR | **FAIL** | DM t=−1.45 |
| H2 | A4f_FX > A4f_VIX | **INDIFFERENT** | DM t=+0.12 |
| H3 | COMBO dominates both solos | **FAIL** | DM t=−0.97 vs VIX, −0.76 vs FX |
| H4 | High-FXVol: FX > VIX | **FAIL (reversed)** | DM t=−3.50 (VIX wins) |

### K1077 replication sanity check

| | K1077 (VIX, separate run) | K1099 (VIX, within 4-model stack) |
|---|---:|---:|
| A4f_VIX vs GJR DM t | −0.488 | −0.266 |
| QLIKE diff % | +0.332% | +0.166% |
| n OOS | 3913 | 3913 |

Close and same sign — K1077's null replicates inside K1099.

## Interpretation

Three independent converging lines of evidence close the "Taiwan A4f" file:

1. **K1077**: US VIX² doesn't transmit to 0050.TW.
2. **K1083**: 83% of the Taiwan→EWT forecasting gap is the USD currency
   wrapper (mechanical FX variance leaking into USD-denominated returns).
3. **K1099**: FX realized vol² (the supposed root cause from K1083) also
   doesn't transmit to 0050.TW, and in the high-FX-vol regime A4f_VIX is
   Harvey-significantly better than A4f_FX.

The apparent contradiction between K1083 and K1099 resolves when the two
results are read carefully:

- K1083 is about **ETF forecasting gap**: when you forecast **EWT** (USD-wrapped)
  from VIX, you gain a 2.26 DM t; removing the USD wrapper (using synthetic
  0050.TW+FX return) and using VIX captures most of that signal. That is a
  decomposition of **which return series** VIX predicts — EWT vs TWD-native.
- K1099 asks a different question: **given you are forecasting 0050.TW** (in
  TWD), does **FX²** help more than VIX²? The answer is no, because FX vol
  has ~zero correlation with 0050.TW vol. FX leaks into EWT's *return*
  process; it does not correlate with 0050.TW's *variance* process.

**Paper 10 revival verdict: DENIED.** FX realized vol is not a viable τ driver
for 0050.TW. Unless we can find a regressor that (a) is observed in Taiwan's
information set and (b) correlates meaningfully with Taiwan's own realized
vol, the A4f extension is empty on 0050.TW. US VIX is the best candidate
in-hand (ρ=+0.60) but even that doesn't produce Harvey-PASS after GJR absorbs
the auto-regressive component.

## Limitations

- FX data: Yahoo's TWDUSD=X has 2 glitches in 16 years which we repaired via
  H+L median (K1083 pattern). Tick-level FX data might behave differently.
- FXVOL_RV21 uses daily log returns; intraday TWDUSD RV could carry more
  information but isn't available on yfinance.
- EWMA(λ=0.94) sensitivity left in the data pipeline but not separately
  estimated in this run — future work can swap the primary driver to
  FXVOL_EWMA; we do not expect material change given the near-zero raw
  correlation.
- Rolling W=2000 with `start_idx=228` means the Early OOS uses a shorter
  training window (same as K1077 — the two are directly comparable).

## Downstream implications

- Paper 9 (single-market GARCH-MIDAS on SPY) stands; Taiwan is not its target.
- Paper 10 (currency-denomination framework) must be **re-scoped** away from
  "FX vol is the right τ regressor" to something like "EWT's forecastability
  is a superposition of domestic equity vol (matched by VIX) and FX vol
  (matched by FXVOL), and cannot be captured by a single shared τ".
- Future K1100+ should consider:
  - TAIEX-denominated options or VIXTWN (once cleaner data available) — K1098
  - Proxy for "global risk aversion that reaches Taiwan" beyond VIX
  - Giving up A4f on Taiwan entirely and focusing on range-based (Parkinson
    or Yang-Zhang) estimators using Taiwan's own OHLC

