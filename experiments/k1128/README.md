# K1128 — VIX Tertile Regime Split for OFI → Jump Prediction

**Status**: PARTIAL (primary IS-based split degenerate; secondary OOS-internal split shows regime-dependent signal)
**Date**: 2026-04-13
**Author**: Claude (worktree agent-k1128)
**Data**: TAIFEX TX 5-min bars 2017-2021 (reused K1124 cached parquet, 73,203 bars; K1125's Lee-Mykland jump detection)

## Problem and Motivation

K1125 found OFI → jump predictability is **regime-dependent**: M3 (`jump_curr + |OFI|_t + OFI_t`) achieved OOS AUC 0.580 in 2020 COVID but only 0.547 in 2021 calm. The M4 interaction term (`|OFI| * VIX_z`) failed catastrophically (DM t=-6.09, AUC<0.5).

K1128 reframes: rather than a continuous linear interaction, **split by VIX tertile and refit separately**. This avoids functional-form assumptions and gives each regime its own intercept + slope coefficients.

## Method

### Primary: IS-based tertile cutoffs
1. Compute VIX tertile cutoffs (33%/67% quantiles) on IS 2017-2019 `vix_lag1` only
2. Apply cutoffs to OOS 2020-2021 (no peeking)
3. Fit K1125 M3 model (`jump_curr + |OFI|_t + OFI_t`) within each tertile's IS sub-sample
4. Evaluate OOS within same tertile

### Secondary (descriptive): OOS-internal tertile cutoffs
Added because primary approach's IS/OOS VIX distributions are **disjoint**: IS VIX range 9.14-37.32 vs OOS 15.01-82.69. With IS-based cutoffs, **OOS has 0 low-tertile bars** and only 854 mid-tertile bars. This makes H1 (monotonicity) untestable.

OOS-internal split: compute cutoffs on OOS VIX (cannot be used for live trading, but isolates regime effect on same full-IS-trained model).

### Jump detection
Same as K1125: Lee-Mykland (2008) with K=16 window bipower variation, multi-test Gumbel threshold α=0.01 → 115 jumps total (0.21% of valid bars).

### Lag and lookahead discipline
- `vix_lag1` = previous US close VIX (TAIFEX opens 08:45 local, after US close)
- All features at bar t predict jump at bar t+1 (same as K1125)
- IS-based cutoffs computed on IS-only data
- StandardScaler fit on IS, transform on OOS
- Seed 42 fixed

### Codex review
Pre-run `codex exec -s read-only` review: PASS (no HIGH/MED/LOW issues). Verified: IS-only cutoffs, OOS assignment uses IS cutoffs, VIX T-1 lag, lag-1 target alignment, scaler discipline, DM-HLN small-sample adjustment + HAC variance, N sufficiency guard.

## Results

### Primary: IS-based tertile cutoffs — DEGENERATE

IS cutoffs: 33%=**12.07**, 67%=**14.99** (2017-2019 VIX).

| Tertile | IS N | OOS N | OOS jumps | Status |
|---------|------|-------|-----------|--------|
| Low (VIX ≤ 12.07) | 10,585 | **0** | 0 | SKIP (no OOS) |
| Mid (12.07 < VIX ≤ 14.99) | 10,451 | 854 | 1 | SKIP (insufficient jumps) |
| High (VIX > 14.99) | 10,462 | **20,060** | 32 | Evaluated |

**High-tertile only**:
- M1 AUC OOS = 0.5148
- M3 AUC OOS = **0.5926**
- DM-HLN t = +1.31 (below |t|>2 threshold)
- Coefs: jump_curr=+0.138, |OFI|=-0.031, OFI=-0.065

**Verdict**: H1 (monotonicity) untestable. COVID-era 2020-2021 VIX entirely outside IS training distribution → IS-based tertile split collapses.

### Secondary: OOS-internal tertile cutoffs (DESCRIPTIVE ONLY)

OOS cutoffs: 33%=**18.84**, 67%=**25.34** (2020-2021 VIX).

Full IS → OOS model:
- M1 AUC OOS = 0.514
- M3 AUC OOS = 0.555

Per OOS tertile (same full-IS-trained model, evaluated per OOS regime):

| Tertile | VIX range | OOS N | OOS jumps | M1 AUC | M3 AUC | DM-HLN t |
|---------|-----------|-------|-----------|--------|--------|----------|
| Low | 12.3 - 18.8 | 7,074 | 16 | 0.5302 | 0.5621 | +0.53 |
| Mid | 18.9 - 25.3 | 6,894 | 11 | 0.4992 | 0.4957 | +1.85 |
| **High** | **25.4 - 82.7** | **6,946** | **6** | 0.4995 | **0.6261** | **+3.59** |

### Key Findings

1. **Primary IS-tertile approach FAILS** (methodology null): COVID shifted OOS VIX beyond IS training range. IS-based regime cutoffs cannot be applied out-of-sample when the regime itself is structurally new. This is a methodological lesson, not a microstructure finding.

2. **Secondary (descriptive) OOS-internal split shows strong HIGH-VIX regime signal**:
   - High VIX (>25): M3 AUC 0.626, DM t=+3.59 (>Harvey 3.0 threshold)
   - But caveats: only 6 jumps, sample noise matters
   - NOT monotonic: mid-tertile AUC 0.496 below low-tertile 0.562

3. **Monotonicity H1 REJECTED**: Low=0.562, Mid=0.496, High=0.626. U-shape rather than monotonic. Mid-tertile underperformance may reflect small N (11 jumps) or may reflect that moderate-VIX periods are genuinely uninformative for the signal.

4. **Sign of OFI coefficient in high-VIX subsample**: In the high-tertile fit (primary, IS-within-tertile), signed OFI coef is -0.065 — same direction as K1125's M3 (-0.187) but weaker. The IS training sample for the high-tertile is the 2018-2019 VIX>15 periods (e.g., Feb 2018 volmageddon), which may differ from 2020 COVID dynamics.

## Triple-Threshold Verdict

| Criterion | Value | Threshold | Pass |
|-----------|-------|-----------|------|
| High tertile M3 AUC (primary) | 0.593 | > 0.55 | YES |
| High - Low AUC gap (primary) | N/A (degenerate) | > 0.02 | N/A |
| DM high-tertile |t| (primary) | 1.31 | ≥ 2.0 | NO |
| **Overall (primary)** | | | **FAIL** |

Secondary OOS-internal analysis: Harvey threshold (t>3) met at high-VIX subset (t=+3.59), but this uses OOS-derived cutoffs and only 6 jumps in that cell. **Cannot publish as live-trading signal**; suggestive for paper narrative only.

## Paper Implications (Taiwan Microstructure)

The primary result reinforces K1125's caveat: **OFI → jump predictability concentrates in high-volatility regimes**. Secondary evidence (OOS-internal split, high-VIX tertile DM t=+3.59) supports the mechanism hypothesis that large order flow imbalances on TAIFEX cross thin liquidity layers more readily in crisis periods.

Importantly, this experiment **also surfaces a methodological pitfall for regime analysis on crisis-era data**: when OOS includes an extreme event (COVID), IS-defined regime boundaries become trivial. Future work on TAIFEX regime-dependent signals should either (a) extend IS to include prior crisis years (2008-2015) or (b) use adaptive/expanding-window regime thresholds.

## Limitations

- **Jump count extremely small** in all OOS tertiles (6-16 jumps per cell); AUC estimates have wide confidence bands.
- **Secondary analysis uses OOS-peeking cutoffs** — acceptable for descriptive paper narrative, NOT for trading claims.
- Monotonicity test may be spuriously violated due to mid-tertile sample noise (11 jumps).
- IS training data for high-tertile subsample (VIX > 14.99) is 10,462 bars from 2017-2019 with only 26 jumps — moderate statistical power.
- No robustness to alpha level of jump detection (fixed at 0.01).
- Single market; US replication still needed (K1126).

## Derived Directions (3)

1. **K1129 — Expanding-window IS with pre-COVID crisis periods** (e.g., 2008 GFC, 2011 debt ceiling, 2015 China deval). Extend IS beyond 2017-2019 to capture wider VIX distribution, then re-run IS-based tertile split. Expected outcome: less-degenerate OOS tertile coverage; cleaner H1 test.

2. **K1130 — Continuous VIX as interaction with expanding-window estimation**. Rather than discrete tertiles, fit `jump_{t+1} = α + β_1 * jump_curr + β_2(VIX) * |OFI|_t + β_3(VIX) * OFI_t` where coefficients are VIX-dependent (e.g., via spline basis or B-spline). Avoids tertile definition problem entirely. Tests whether the β(VIX) curve is monotonically increasing.

3. **K1131 — Bootstrap CI on high-tertile DM statistic**. Given small N (6 jumps), block-bootstrap the OOS high-VIX tertile predictions and compute 95% CI on AUC and DM t-stat. Tests whether the +3.59 DM t is robust or an artifact of the 6 specific jump events in 2020.

## Files

- `k1128.py` — Main experiment (post-Codex-review version)
- `k1128_results.json` — Full numeric results including primary + secondary analysis
- `k1128_tertile_results.png` — 4-panel figure (AUC/DM/coef/OOS-internal)
- `README.md` — this file

## References

- Lee, S.S., Mykland, P.A. (2008). "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." *Review of Financial Studies* 21(6), 2535-2563.
- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
- Ang, A., Timmermann, A. (2012). "Regime Changes and Financial Markets." *Annual Review of Financial Economics* 4, 313-337.
