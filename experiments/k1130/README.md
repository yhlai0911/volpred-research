# K1130 - Extended IS 2012-2019 for K1128 OFI-jump regime test

**Status**: NULL (Scenario D — INVALIDATED structural). Extended IS **does NOT** rescue K1128.
**Date**: 2026-04-17
**Author**: Claude (main-thread)
**Data**: TAIFEX TX 5-min bars 2012-2021 (rebuilt cache 146,944 bars / 2,455 days; Lee-Mykland K=16 detected 270 jumps global)

## Problem and Motivation

K1128 used IS 2017-2019 (VIX 9-37) VIX-tertile cutoffs, applied to OOS 2020-2021 (COVID, VIX 15-82). The IS cutoffs (33%=12.07, 67%=14.99) produced degenerate OOS coverage: low=0 / mid=854 / high=20,060 — regime design collapsed.

K1131 (spline rescue) returned NULL: OOS DM t=-3.94 (spline worse than tertile). Verdict: **problem is structural** (OOS VIX disjoint from IS).

`docs/error_log.md` 2026-04-13 lesson listed three candidate fixes. K1131 tested fix #3 (spline) — failed. K1130 tests **fix #1: extend IS to include prior VIX spikes**.

TAIFEX tick data starts 2012 (CLAUDE.md), so no 2008 GFC. Extended IS = **2012-2019** (8 years) covers 2015 China devaluation (VIX ~40) and 2018 Feb volpocalypse (VIX ~50).

## Method

- **IS extended**: 2012-01-01 .. 2019-12-31 (84,295 bars, 238 jumps)
- **IS K1128 reference**: 2017-01-01 .. 2019-12-31 (31,498 bars, 78 jumps)
- **OOS**: 2020-01-01 .. 2021-12-31 (20,914 bars, 30 jumps)
- **VIX**: yfinance `^VIX` daily, T-1 lag (Taiwan prev-US-close convention)
- **TAIFEX**: TX futures, T-1 rolling active contract (K1124 Codex-fix)
- **Day session**: 08:45:00 .. 13:44:59 (DAY_END=134459, K1124 audit fix)
- **Jump detection**: Lee-Mykland (2008) with rolling BV K=16, Gumbel threshold α=0.01 (threshold=5.252)
- **Tertile cutoffs**: recomputed on extended IS (not reused from K1128)
- **Features (M3)**: `jump_curr`, `|OFI|_t`, `OFI_t` (K1128 spec)
- **Baseline (no-regime)**: single logistic fit on extended IS
- **Regime model**: per-tertile logistic fit; OOS predictions stitched back by regime; fallback to base for tertiles with < 5 jumps
- **DM-HLN** on OOS log-loss; positive t means p2 (second arg) has higher LL (wins)
- **LRT** chi² on IS NLL difference

### Gemini review (Codex blocked by usage limit)

Verified: extended IS uses `list(range(2012, 2020))`, VIX lag-1 via `shift(1)` then merge, T-1 active contract, cutoffs computed on extended IS only, DM sign convention correct, LRT df correct. No HIGH/MED bugs. One LOW flagged (Gumbel threshold uses full sample's n_valid — minor, does not change direction). Added `.bfill()` after `.ffill()` for VIX safety.

## Results

### VIX tertile cutoffs

| IS sample | VIX min | mean | std | max | 33% cutoff | 67% cutoff |
|---|---|---|---|---|---|---|
| K1128 (2017-2019) | 9.14 | 14.34 | 4.19 | 37.32 | 12.07 | 14.99 |
| **K1130 Extended (2012-2019)** | **9.14** | **15.18** | **3.80** | **40.74** | **13.15** | **15.91** |
| OOS (2020-2021) | 12.32 | — | — | 82.69 | — | — |

Extended IS max VIX = 40.74 (2015 China deval, Aug 2015) — still far below COVID max = 82.69.

### OOS regime coverage (H4)

| Regime | K1128 cutoffs | Extended cutoffs |
|---|---|---|
| Low (VIX ≤ c33) | 0.00% | 1.63% |
| Mid (c33 < VIX ≤ c67) | 4.08% | 6.76% |
| High (VIX > c67) | **95.92%** | **91.61%** |

**H4 FAIL**: min coverage = 1.63% (extended), still < 10%. OOS VIX almost entirely above extended IS's 67th percentile (15.91). The fix **slightly reduces** the "high" concentration (95.92% → 91.61%) but does not meaningfully distribute OOS across tertiles.

### Per-tertile fit (extended IS)

Low and mid tertiles have < 5 OOS jumps — SKIPPED. Only high tertile fits both IS and OOS:

| Tertile | IS N | IS jumps | OOS N | OOS jumps | M1 OOS AUC | M3 OOS AUC | DM M3 vs M1 |
|---|---|---|---|---|---|---|---|
| Low | 28,291 | 91 | 341 | 1 | SKIP | SKIP | — |
| Mid | 27,969 | 69 | 1,413 | 3 | SKIP | SKIP | — |
| High | 28,035 | 78 | 19,160 | 26 | 0.519 | 0.561 | **+3.49** |

High-tertile M3 vs M1 DM t = +3.49 (within-tertile signal exists at magnitude-OFI in high VIX), but this is a within-regime M1-vs-M3 test, not the regime-switching test.

### H1 — LRT extended regime vs no-regime base (IS)

| Model | NLL_IS | LRT chi² | df | p |
|---|---|---|---|---|
| Extended base | 1623.26 | — | — | — |
| **Extended regime** | **1622.21** | **2.10** | 1 | **0.147** |
| K1128 base | 538.56 | — | — | — |
| K1128 regime | 537.47 | 2.16 | 1 | 0.141 |

**H1 FAIL**: Extended LRT chi² = 2.10 is *slightly less than* K1128's chi² = 2.16 (both df=1 because 2/3 tertiles SKIPPED → only high tertile contributes 4 params vs base's 4). Both p > 0.05 — **no statistically significant regime effect**, whether IS is 3y or 8y.

Note on df: per-tertile regime adds 4 params per *fitted* tertile. Because mid/low have < 5 jumps and fall back to base, only 1 tertile contributed extra params → df_LRT = 4-4 = 0, floored to 1 by code. So the effective comparison is "high-tertile M3 vs pooled base M3 on same high-tertile IS obs" — that's the only real free param difference.

### H2 — OOS DM regime vs base (extended)

- Regime OOS log-loss = 0.01093 (stitched: M3_high for 91.6%, base for 8.4%)
- Base OOS log-loss = 0.01100
- **DM t = +0.839** (p two-sided ≈ 0.40). **H2 FAIL**.

### H3 — OOS DM extended regime vs K1128 regime

- Extended regime OOS LL > K1128 regime OOS LL? **DM t = −0.533**. Extended is *worse* than K1128 by a hair (both dominated by the same high-tertile M3 anyway). **H3 FAIL**.

### H4 — OOS coverage ≥ 10% in each tertile

Min = 1.63% (extended low). **H4 FAIL**.

## Verdict: Scenario D

| Hypothesis | Threshold | Actual | Pass |
|---|---|---|---|
| H1 (LRT ext > K1128 AND p<0.05) | p<0.05 + larger chi² | chi²_ext=2.10, p=0.147 (smaller than K1128=2.16) | FAIL |
| H2 (OOS DM ext regime vs base, t≥+2) | Harvey joint | t=+0.839 | FAIL |
| H3 (OOS DM ext vs K1128, t≥+2) | Harvey joint | t=−0.533 | FAIL |
| H4 (min OOS coverage ≥ 10%) | coverage | 1.63% | FAIL |

**Overall: Scenario D — INVALIDATED (structural).**

## Interpretation: error_log 2026-04-13 fix #1 implication

**Fix #1 (extend IS to include prior crises) is EMPIRICALLY INVALIDATED.** Going from 3-year IS (max VIX=37) to 8-year IS (max VIX=41) did not recover regime-switching predictive power in the COVID OOS:

1. **Coverage barely improved**: min tertile coverage 0% → 1.63% (still << 10%). COVID VIX regime (mean ~28, median ~22, max 83) lies above even the extended IS 67th percentile (15.91). The 2015 and 2018 vol spikes were too brief and too modest to meaningfully shift the upper tail of an 8-year quantile.
2. **Regime signal did not emerge**: H1 LRT chi² basically identical (2.10 vs 2.16). More IS data does not create a regime effect if one doesn't exist.
3. **OOS improvement is zero**: H2 t=+0.84 (noise), H3 t=−0.53 (slightly worse than K1128).

Combined with K1131's NULL (spline fix #3 also failed), **two of three error_log fixes are now invalidated**. The only remaining untested options are #2 expanding-window adaptive quantile and #4 rolling quantile — but given the structural issue (OOS VIX regime is genuinely unprecedented in the TAIFEX-available window 2012-2021), rolling/expanding quantiles will likely converge to the same problem: COVID VIX remains in the tail of any historical window that doesn't include post-2020 data, and once COVID is included, IS is contaminated.

**The real message for K1128**:
- K1128's regime-switching narrative (high-VIX = OFI predicts jumps) is **not supported as a predictive framework**. The appearance of a signal in K1128's high tertile OOS (original AUC=0.598, DM t≈+3.59 in OOS-internal analysis) was driven by 26-29 jumps total. Even with extended IS providing 78 IS jumps in the high-tertile fit, OOS M3 AUC=0.561 and within-tertile M3 vs M1 DM=+3.49 show that **the OFI→jump signal itself survives** — but **it does not require a regime model**. K1130's single pooled base model on extended IS (AUC=0.560) is essentially equivalent to the regime-stitched model (AUC=0.561).
- **Recommended revision of K1128 narrative**: "OFI (|OFI| in particular) has weak predictive power for TAIFEX jumps during high-VIX episodes, but VIX-regime-switching is neither necessary nor statistically justified. A pooled GARCH-X / HAR-X style model using |OFI| as a continuous covariate is the correct specification."
- **error_log 2026-04-13 fixes #1 and #3 should both be downgraded** to "not empirically validated in this setting".

## Limitations

- TAIFEX tick data starts 2012; cannot use 2008 GFC to truly bracket COVID VIX range (would need VIX > 60 in IS to extrapolate reliably).
- OOS jumps = 30 total across 2 years; any per-tertile split in OOS is underpowered.
- Jump rate 0.25% is very low — even 2-year 20k-bar OOS gives ~50 jumps, fractured across 3 tertiles.
- Single-market (TAIFEX). US-market OFI-jump replication (K1126) remains pending.
- Gemini-reviewed only (Codex usage limit hit during this experiment).

## Derived Directions

1. **K1132 — Pooled base GARCH-X / HAR-X with |OFI|**: abandon regime-switching entirely. Refit K1128 M3 as a single pooled spec on extended IS 2012-2019, evaluate with triple threshold (DM|t|>3, QLIKE>5%, sub-period stability). If pooled wins → clean publishable positive result without regime baggage.
2. **K1133 — Extended-OOS through 2025**: the 2020-2021 OOS is underpowered (30 jumps). Extending OOS to 2020-2025 (~120 jumps) would give enough power to ask whether any VIX-dependent structure emerges on a larger post-COVID sample that spans quiet → vol-spike multiple times.
3. **K1134 — Non-VIX regime indicator**: replace VIX with TAIEX-native implied-vol / realized-vol ratio (since US VIX is a coarse proxy for TAIFEX regimes). If a regime effect exists, it may align with Taiwan-native vol rather than US.

## Files

- `k1130.py` — main experiment
- `k1130_results.json` — full numeric results
- `_cache_bars_2012-01-01_2021-12-31.parquet` — rebuilt TAIFEX bar cache (146,944 bars)
- `is_extended_vs_original.png` — IS VIX distribution + cutoffs (K1128 vs extended)
- `oos_regime_coverage.png` — OOS tertile coverage bar chart (K1128 vs extended)
- `run.log` — execution log
- `README.md` — this file

## References

- Lee, S.S., Mykland, P.A. (2008). "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." *Review of Financial Studies* 21(6), 2535-2563.
- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
- K1128 (this project): VIX-tertile regime split — the experiment this one tries to fix.
- K1131 (this project): Natural cubic spline rescue — NULL; motivated K1130.
- `docs/error_log.md` 2026-04-13 entry: IS-regime degeneracy on COVID data — the motivating lesson.
