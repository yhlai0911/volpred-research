# K1131 — Continuous VIX-dependent β via Natural Cubic Spline

**Status**: NULL (spline does NOT rescue K1128; tertile remains equal-or-better in OOS)
**Date**: 2026-04-17
**Author**: Claude (worktree agent-k1131)
**Data**: TAIFEX TX 5-min bars 2017-2021 (K1124 parquet cache, 73,203 bars; 115 jumps via Lee-Mykland K=16)

## Problem and Motivation

K1128 used VIX tertile discrete cutoffs computed on IS (2017-2019). Applied to OOS (2020-2021, COVID VIX up to 82), the IS quantile cutoffs (33%=12.07, 67%=14.99) produced degenerate coverage: **low=0 / mid=854 / high=20,060** OOS bars. Almost everything collapsed to the "high" tertile, voiding the regime-switching design.

`docs/error_log.md` 2026-04-13 lesson #4 proposed: replace discrete tertile with **continuous VIX-dependent β via spline**. K1131 implements this fix and tests whether it restores regime-switching predictive value out-of-sample.

## Method

### Model spec

Baseline (K1128 M3, refit here as `M_base`):
```
logit P(jump_{t+1}=1) = α + β_1·jump_curr + β_2·|OFI|_t + β_3·OFI_t
```

K1128 discrete tertile (`M_tertile`):
```
logit P(...) = base + β_{mid}·mid·|OFI| + β_{high}·high·|OFI|
                    + γ_{mid}·mid·OFI  + γ_{high}·high·OFI
```

K1131 continuous spline (`M_spline`):
```
logit P(...) = base + [Σ_k θ_abs_k·B_k(VIX_{t-1})]·|OFI|_t
                    + [Σ_k θ_sgn_k·B_k(VIX_{t-1})]·OFI_t
```

- `B_k(·)`: natural cubic spline basis (Hastie, Tibshirani, Friedman 2009 eq. 5.4-5.5) with K=4 internal knots at IS VIX 20/40/60/80 percentile (11.05 / 12.50 / 14.25 / 17.30)
- Basis df = K-1 = 3 per interaction (1 linear + 2 cubic), total 6 VIX-interaction columns
- **Natural constraint**: function is linear beyond boundary knots → safe extrapolation to COVID VIX=82
- VIX centered at IS median (13.11) for numerical stability
- MLE via L-BFGS-B with L2 ridge 1e-4 (no penalty on intercept)
- Delta-method 95% CI for f(VIX)

### Lag and lookahead discipline (inherited from K1128/K1124)

- **VIX T-1**: `vix_df['vix'].shift(1)` — previous US close (TAIFEX opens next morning)
- **OFI** from K1124 cache with `DAY_END=13:44:59` and T-1 rolling active contract (Codex-fixed)
- IS-only knots & tertile cutoffs — no peeking at OOS
- `seed=42` fixed

### Codex/Gemini review

Codex usage-limit-blocked; **Gemini review** (`gemini -p`) identified:
- **MED**: Earlier draft used `x^2 * scale` as last basis col, violating natural-spline boundary linearity → **FIXED** to true natural cubic (linear beyond boundary knots)
- **LOW**: basis centering at median; OFI feature scale; VIX edge-case ffill — acceptable

## Results

### OOS sample

| | IS (2017-2019) | OOS (2020-2021) |
|---|---|---|
| N bars | 31,498 | 20,914 |
| Jumps | 81 | 33 |
| VIX range | 9.14 — 37.32 | 12.32 — 82.69 |

### IS log-likelihood + H1 (global LRT)

| Model | Params | NLL_IS | LRT vs base | df | p |
|---|---|---|---|---|---|
| M_base | 4 | 557.056 | — | — | — |
| M_tertile | 8 | 554.861 | 4.39 | 4 | 0.356 |
| **M_spline** | **10** | **553.032** | **8.05** | **6** | **0.235** |

**H1 FAIL**: spline's χ²(6)=8.05, p=0.235 — no statistically-significant global VIX dependence of β in-sample.

### H2 (OOS DM-HLN)

| Contrast | DM t | mean_d |
|---|---|---|
| **spline vs tertile** | **-3.937** | -7.58e-04 |
| spline vs base | -3.934 | -7.72e-04 |
| tertile vs base | -0.416 | -1.45e-05 |

**H2 FAIL**: spline is **significantly WORSE** than tertile in OOS log-loss (t=-3.94). Both tertile and spline are indistinguishable from the no-VIX baseline for OOS predictive power.

### OOS log-loss + AUC

| Model | OOS log-loss | OOS AUC |
|---|---|---|
| base | 0.01171 | 0.5543 |
| tertile | 0.01172 | 0.5559 |
| **spline** | **0.01248** | **0.4965** |

Spline OOS AUC is **below chance** (0.50), confirming pathological overfit in IS tail.

### H3 (economic significance)

Spline OOS mean |OFI|-contribution to log-odds = +0.202. Non-zero but driven by the extrapolation into VIX range 25-83 where `f_abs(VIX)` is very large (up to +20.43 in high VIX). Tertile's equivalent contribution mean = +0.089, with much smaller dispersion.

The spline's larger contribution magnitude comes from amplifying IS tail estimates; it does not translate to OOS accuracy.

### H4 (shape sensibility)

`f_abs(VIX)` shape = **U-shape_or_single_turn**.
- f_abs range: [-0.58, +20.43] — explodes at high VIX
- f_sgn range: [-1.99, +6.52]
- At OOS VIX Q25/Q50/Q75 = 17.8/22.0/27.6: f_abs = -0.07 / +1.29 / +3.03

H4 technically passes (shape isn't "very_wiggly"), but the extreme magnitude at OOS-high VIX is a red flag — natural-spline linear extrapolation, when fit on IS data whose max is 37, linearly extends to VIX=82 without regularization, producing inflated coefficients.

### OOS VIX coverage: tertile vs spline

| Regime | K1128 tertile OOS bars | Spline coverage |
|---|---|---|
| Low (VIX ≤ 12.07) | 0 | continuous |
| Mid (12.07-14.99) | 854 | continuous |
| High (>14.99) | 20,060 | continuous |

Spline does cover all 20,914 OOS bars with a nonzero f(VIX)·|OFI| term (no discrete degeneracy). But **covering ≠ predicting**: the coverage comes from IS-linear extrapolation without predictive benefit.

## Verdict: NULL

| Hypothesis | Threshold | Actual | Pass |
|---|---|---|---|
| H1 global LRT spline vs base | p < 0.05 | p = 0.235 | FAIL |
| H2 OOS DM-HLN spline vs tertile | t ≥ 2 | t = -3.94 | FAIL (reverse) |
| H3 OOS contrib nontrivial | |mean| > 1e-4 | +0.202 | PASS (but wrong direction) |
| H4 f(VIX) shape sensible | monotone/U-shape | U-shape but inflated | PASS (marginal) |

**Overall VERDICT: NULL.**

## Interpretation

1. **The spline is not a robust fix for K1128's regime degeneracy on COVID-era data.** Although it removes the discrete cutoff boundary problem, it introduces a new pathology: natural-cubic linear extrapolation from an IS training range (max VIX=37) to an OOS extreme (max VIX=82) produces inflated coefficient estimates with no predictive accuracy — in fact OOS AUC drops to 0.496 (below chance).

2. **Real message about K1128**: the K1128 primary "IS-based tertile FAILED because OOS VIX left IS range" narrative is **structurally correct, not just a technicality of cutoffs**. Neither discrete nor smooth VIX-dependent interactions extrapolate reliably to 2020 COVID. **The OFI → jump predictability itself is regime-limited, and crossing into an unprecedented VIX regime breaks the estimated relationship regardless of functional form.**

3. **error_log 2026-04-13 fix #3 should be downgraded**: the recommendation "continuous VIX-dependent β via spline" as a fix for IS-regime-degeneracy is **not empirically validated** in this TAIFEX-OFI-jump setting. The other proposed fixes (#1 extend IS to include prior crises 2008/2011/2015; #2 expanding-window adaptive quantile; #4 rolling quantile) remain unverified and more promising.

4. **K1128's secondary OOS-internal analysis** (descriptive-only, high-VIX M3 AUC=0.626, DM t=+3.59) is confirmed as an overfit artifact of 6 jumps; K1131 non-replication via a different functional form supports this.

## Limitations

- OOS jump count extremely small (N=33). Any inference over VIX bins has wide CI.
- Natural cubic spline still extrapolates linearly beyond knot_4=17.3; alternative: add a far-right knot at e.g. 50 (but no IS data to train it).
- L2 ridge 1e-4 is light; stronger regularization (or smoothing-spline penalty λ·∫f''²dx) was not tested here. Codex-review was blocked by usage limit so Gemini-reviewed only.
- VIX as sole regime indicator. Jointly with VIX3M or NFCI may do better (but adds many params on 33-jump OOS).
- Single-market (TAIFEX only). US-market replication (K1126) still pending.

## Derived Directions (3)

1. **K1132 — Extended-IS spline**: append 2008 GFC + 2011 debt-ceiling + 2015 China-deval VIX years to IS so the training range overlaps COVID. Refit spline. If f(VIX) curve becomes smooth AND OOS improves → extension solves extrapolation. (error_log 2026-04-13 fix #1)

2. **K1133 — Rolling/expanding-window spline**: refit spline monthly on an expanding window so recent VIX adaptations enter coefficient estimation in real-time. Test whether OOS predictive power recovers. (error_log 2026-04-13 fix #2, #4)

3. **K1134 — Non-OFI volatility-scaling**: abandon regime-switching interaction; instead divide |OFI| by contemporaneous short-window realized σ (volatility normalization). Tests whether OFI's predictive signal is about "microstructure shock relative to noise" rather than VIX-dependent regime.

## Files

- `k1131.py` — Main experiment (post-Gemini-review revision; natural cubic spline with boundary linearity)
- `k1131_results.json` — Full numeric results
- `spline_beta_vs_vix.png` — f_abs(VIX) and f_sgn(VIX) curves with 95% CI, tertile step function overlaid
- `tertile_vs_spline_comparison.png` — OOS log-loss + AUC + |OFI|-contribution distributions
- `run.log` — Execution log
- `README.md` — this file

## References

- Lee, S.S., Mykland, P.A. (2008). "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." *Review of Financial Studies* 21(6), 2535-2563.
- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88.
- Hastie, T., Tibshirani, R., Friedman, J. (2009). *The Elements of Statistical Learning*, 2nd ed., §5.2 Natural Cubic Splines.
- Ruppert, D., Wand, M.P., Carroll, R.J. (2003). *Semiparametric Regression.*
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
- K1128 (this project): VIX tertile regime split — the experiment this one fixes.
- error_log.md 2026-04-13 entry: IS-regime degeneracy on COVID data — the motivating lesson.
