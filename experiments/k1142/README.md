# K1142 — Volatility-Normalized OFI (Bypass VIX-Conditional Regime Switching)

**Status**: PARTIAL_OOS_ONLY (OOS DM t=+2.26 for vol-normalization; IS t=+1.45 not significant at |t|>2)
**Verdict relative to K1128/K1131 NULLs**: vol-normalization specification shows OOS improvement but IS fit is only marginal; Harvey (2016) |t|>3 publication threshold is NOT met. Cannot fully rescue K1128 story, but it materially reframes the signal.
**Date**: 2026-04-17
**Author**: Claude (worktree agent-a11a520c / K1142)
**Data**: TAIFEX TX 5-min bars 2017-2021 (K1124 parquet cache, 73,203 bars; 115 Lee-Mykland K=16 jumps)

## Problem and Motivation

K1128 split OFI→jump logistic by VIX tertile with IS-based cutoffs → OOS degeneracy because COVID VIX (up to 82.69) left IS VIX range (max 37.32). K1131 used a natural-cubic spline in VIX → OOS AUC fell to 0.496 (below chance) due to linear extrapolation beyond IS training knots.

Both experiments addressed the **functional form** of VIX-conditional interaction, but neither asked whether VIX is the right conditioning variable at all. K1131 derived-direction #3 proposed bypassing regime-switching entirely via **volatility normalization**:

```
z_absOFI_t = |OFI|_t / sigma_hat_t
z_sgnOFI_t = OFI_t   / sigma_hat_t
```

where `sigma_hat_t` is a strictly-past rolling realized volatility from the last 60 5-min log-returns (≈5 trading hours). This treats OFI as a **standardized signal relative to recent microstructure noise level** — a regime-free specification.

If vol-normalization works, then:
- K1128 "regime-dependent" story collapses into a simpler "vol-normalized universal signal"
- The entire regime-switching identification problem (IS/OOS VIX distribution mismatch) is sidestepped

## Method

### Three models

```
M_base         : logit P(jump_{t+1}=1) = α + β₁·jump_curr + β₂·|OFI|_t + β₃·OFI_t        (K1128 "M3" refit)
M_volnorm      : logit P(jump_{t+1}=1) = α + β₁·jump_curr + β₂·z_absOFI_t + β₃·z_sgnOFI_t
M_realvol_tert : logit P(jump_{t+1}=1) = α + β₁·jump_curr + β₂·|OFI| + β₃·OFI
                                         + β₄·mid_σ·|OFI| + β₅·hi_σ·|OFI|
                                         + β₆·mid_σ·OFI   + β₇·hi_σ·OFI
```

`M_realvol_tert` is a K1128-style tertile split but with regime proxy replaced by `sigma_hat` tertile (IS cutoffs). Sanity check: if simple regime-switching on σ works, then vol-normalization's continuous standardization isn't unique.

### Lag / lookahead discipline

- `sigma_hat_t = std(log_ret_{t-60}, ..., log_ret_{t-1})`, implemented as `log_ret.shift(1).rolling(60).std()` on cross-day-sorted series. Row t uses only rows [t-60, t-1], strictly past.
- Day session = 60 bars of 5 min; cross-day rolling is chosen (rather than per-day reset) because per-day reset would zero out all 60 bars/day → destroy the sample. Cross-day is also microstructure-faithful: overnight gap return is already a log_ret observation contributing to sigma_hat.
- Robustness: secondary spec uses `shift(12)` = 1-hour additional published delay.
- Target `jump_{t+1}` = same-day next-bar Lee-Mykland indicator (= K1128/K1131 pipeline).
- Seed 42; L-BFGS-B; L2 ridge 1e-4 on non-intercept coefficients.

### Jump detection

Identical to K1128/K1131: Lee-Mykland (2008) K=16 window bipower variation, Gumbel threshold α=0.01 → 115 jumps total.

## Results

### Sample

| | IS (2017-2019) | OOS (2020-2021) |
|---|---|---|
| N bars | 31,455 | 20,914 |
| Jumps | 81 | 33 |
| sigma_hat range | 0.00018 - 0.00272 (median 0.00058) | 0.00031 - 0.00698 (median 0.00092) |

COVID doubled median realized vol; `sigma_hat` tertile cutoffs (IS): 33% = 0.000512, 67% = 0.000662.

### IS log-likelihood

| Model | Params | NLL_IS | Δ vs base |
|---|---|---|---|
| M_base | 4 | 556.945 | — |
| M_volnorm | 4 | 553.915 | +3.03 |
| M_realvol_tert | 8 | 552.324 | +4.62 (LRT χ²=9.24, df=4, p=0.055) |

`M_volnorm` has the same parameter count as `M_base` but attains higher IS log-likelihood → the standardization is a strict **re-parameterization** improvement, not an overfit from extra df.

`M_realvol_tert`'s LRT vs base is marginal (p=0.055); regime-switching on sigma is just on the edge of significance in-sample.

### OOS metrics

| Model | OOS log-loss | OOS AUC | OOS Brier | Spearman(p̂, y) |
|---|---|---|---|---|
| M_base | 0.011709 | 0.5542 | 0.001574 | +0.0075 (p=0.281) |
| **M_volnorm** | **0.011650** | **0.5940** | 0.001574 | +0.0129 (p=0.062) |
| M_realvol_tert | 0.011558 | **0.6663** | 0.001572 | +0.0229 (p=0.001) |

`M_volnorm` beats `M_base` in OOS log-loss (0.59% relative improvement) and AUC (+0.04); `M_realvol_tert` is the strongest OOS AUC but relies on 4 extra interaction terms.

### DM-HLN tests (positive t ⇒ 2nd model has smaller loss)

| Contrast | IS t | OOS t | Verdict |
|---|---|---|---|
| **M_volnorm vs base** | **+1.454** | **+2.255** | OOS PASS @ |t|>2; IS marginal |
| M_realvol_tert vs base | +1.693 | +1.982 | both marginal, OOS just below threshold |
| M_volnorm vs M_realvol_tert | — | −1.573 | realvol_tert nominally better OOS but not significantly |

### Robustness: lag-12 (1-hour "published" delay) sigma_hat

| Metric | M_base | M_volnorm (lag12) |
|---|---|---|
| OOS AUC | 0.5542 | 0.5920 |
| OOS DM t vs base | — | **−0.278** |

When `sigma_hat` is computed with an extra 1-hour lag, the DM advantage evaporates (t=+2.26 → −0.28) despite AUC staying at 0.592. This says **the vol-normalization value comes from the most-recent ~5 hours** of microstructure noise, not from a slowly-changing 1-hour-stale regime proxy.

### Conditional P(jump | z_absOFI) — OOS deciles

See `k1142_cond_prob.png`. Empirical jump probability increases from ~0.06% in the lowest z_absOFI decile to ~0.31% in the highest decile, with the M_volnorm logistic curve tracing the empirical pattern reasonably within wide Wilson 95% CIs (small-N).

## Verdict: PARTIAL_OOS_ONLY

| Criterion | Threshold | Actual | Pass |
|---|---|---|---|
| M_volnorm vs base OOS DM t | ≥ 2 (methodological); ≥ 3 (Harvey publication) | **+2.255** | methodological YES; Harvey NO |
| M_volnorm vs base IS DM t | ≥ 2 | +1.454 | NO |
| M_volnorm OOS AUC > 0.55 | AUC > 0.55 | 0.594 | YES |
| M_realvol_tert OOS DM t | ≥ 2 | +1.982 | marginal NO |
| M_volnorm vs M_realvol_tert OOS | — | t=−1.57 (not sig) | specs indistinguishable |

**Overall: PARTIAL_OOS_ONLY.** Vol-normalization shows genuine OOS predictive improvement at the methodological-significance level (|t|>2 OOS) but does **not** clear the Harvey (2016) |t|>3 publication threshold required for a top-journal empirical finding with only 33 OOS jumps.

### `realvol_tertile_note`: **volnorm_unique**

Technically `M_realvol_tert` OOS t=+1.98 misses |t|>2 by 0.02; `M_volnorm` OOS t=+2.26 clears it. So within a strict |t|>2 boundary, vol-normalization is the "unique" spec that crosses the methodological threshold. But the two are statistically indistinguishable (DM t=−1.57 between them). Practically: **both the continuous vol-norm and the sigma-tertile specifications capture very similar regime-conditioning effects when the regime proxy is realized volatility rather than VIX.**

## Interpretation: What does K1142 say about K1128's story?

1. **The K1128 narrative can be partially restructured but not fully rescued.**
   Replacing VIX with `sigma_hat` (a strictly-past endogenous realized vol) eliminates the regime-identification problem (no more IS/OOS VIX distribution mismatch). The resulting spec shows OOS predictive improvement |t|>2. This reframes the signal from "OFI effect depends on VIX regime" to "normalized OFI is a regime-free predictor where the normalizer adapts in real time."

2. **But the improvement is small-N and below Harvey (2016) publication bar.**
   OOS DM t=2.26 with 33 jumps is consistent with "detectable but not robustly publishable." Stronger evidence would need either (a) longer OOS period, (b) US market replication (K1126), or (c) intensity-based jump measure rather than 0/1 indicator.

3. **Vol-normalization ≠ vol-regime.**
   `M_realvol_tert` (discrete sigma tertile) achieves the highest OOS AUC (0.666) but still marginal DM t (+1.98). The continuous standardization `z_OFI = OFI/σ` is cleaner theoretically and has slightly stronger OOS DM t. They are statistically equivalent (DM t=−1.57 between them), suggesting the fundamental signal is "OFI relative to recent noise" however parameterized.

4. **Signal is high-frequency-adaptive.**
   Lag-12 robustness loses the DM advantage entirely. The most-recent ~5 hours of microstructure matters; a 1-hour-stale normalizer does not help. This is consistent with OFI being a microstructure signal whose predictive content depends on contemporaneous noise level, not a slowly-drifting macro regime.

## Paper Narrative Implications

K1128/K1131/K1142 together form a **3-experiment narrative arc** for the Taiwan microstructure paper. Per the paper narrative state machine rule:

- K1128: VIX-tertile regime interaction — NULL (OOS distribution mismatch)
- K1131: VIX-spline regime interaction — NULL (OOS AUC 0.496, extrapolation pathology)
- K1142: vol-normalization bypass — PARTIAL_OOS_ONLY (OOS |t|=2.26, Harvey |t|>3 not met)

Aggregate interpretation: **For the TAIFEX OFI→jump setting, VIX is not an effective conditioning variable (regime or spline), and while vol-normalization does capture some adaptive signal, 2 OOS years with 33 jumps is insufficient to reach top-journal publication thresholds.** The right narrative for the paper body is NOT "regime-dependent OFI" but "normalized OFI with adaptive standardization shows detectable but fragile predictive content in Taiwan high-vol episodes."

**Do not change `paper body.tex` based on K1142 alone** (narrative state machine rule). Update `research_program.md` + knowledge.json, then at ≥3-experiment decision point consider narrative pivot after user confirmation.

## Limitations

- OOS jump count N=33 is extremely small. Wide CIs on AUC and DM; `M_volnorm` IS fit is sub-significant (t=1.45) and only the OOS is significant — suspicious asymmetry that may be small-N luck.
- SIGMA_WIN=60 chosen a-priori from K1131 derived-direction suggestion. Not tuned (no OOS leakage this way) but also unverified optimal.
- Cross-day rolling for `sigma_hat` includes overnight gap returns. TAIFEX day-to-day overnight gap is large; acceptable because `log_ret` in the parquet uses within-day log price differences (no gap inclusion when bar crosses midnight). Confirmed consistent with K1124's bar construction.
- Single market (TAIFEX). K1126 US ES/NQ replication still pending.
- No Codex code review performed for this worktree run (task-given instruction said "Codex review done by main thread post-merge"); numerical sanity-checked internally (LL, AUC, DM signs consistent).

## Derived Directions (3)

1. **K1143 — Intensity-based jump measure instead of 0/1 jump indicator**: replace `jump_{t+1}` binary target with Lee-Mykland L-statistic level or jump-size measure. More continuous target → less small-N issue at 33 jumps. Test whether vol-normalization predictive t-stat improves.

2. **K1144 — K1142 replication on 2008-2015 extended IS**: use IS = 2012-2019 (14 years, per user-assigned long-sample-period memory) so IS spans multiple VIX regimes. Refit `M_volnorm`. Expected: if vol-norm is truly regime-free, IS lengthening should tighten IS DM t above 2 without hurting OOS.

3. **K1145 — Vol-normalized OFI on US ES / NQ**: K1126 cross-market replication focused on raw OFI. Rerun with `z_absOFI = |OFI|/sigma_hat`. If US market also shows OOS |t|>2 → vol-normalization is universal microstructure phenomenon, candidate for top-journal submission. If US fails → Taiwan-specific anomaly.

## Files

- `k1142.py` — Main experiment (3 models + lag12 robustness + decile conditioning)
- `k1142_results.json` — Full numeric results (IS/OOS metrics, DM, Spearman, lag12, betas, Wilson CIs)
- `k1142_oos_roc.png` — OOS ROC curves for M_base / M_volnorm / M_realvol_tertile
- `k1142_cond_prob.png` — Conditional P(jump_{t+1}=1 | z_absOFI_t) by OOS decile with 95% Wilson CI
- `run.log` — Execution log
- `README.md` — this file

## References

- Lee, S.S., Mykland, P.A. (2008). "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." *Review of Financial Studies* 21(6), 2535-2563.
- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88.
- Hansen, P.R., Lunde, A. (2005). "A Forecast Comparison of Volatility Models: Does Anything Beat a GARCH(1,1)?" *Journal of Applied Econometrics* 20(7), 873-889. — vol proxy and normalization methodology.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
- Harvey, C.R. (2016). "Presidential Address: The Scientific Outlook in Financial Economics." *Journal of Finance* 72(4), 1399-1440. — |t|>3 threshold.
- K1128 / K1131 (this project): VIX regime-switching attempts that motivated K1142.
- K1124 / K1125: OFI signal construction on TAIFEX TX.
