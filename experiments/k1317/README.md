# K1317: Forgetting-Factor BMA (Dynamic Model Averaging)

**Verdict**: PASS_NULL  
**Date**: 2026-05-15  
**Codex Review**: CONDITIONAL PASS (notation fixed, all core checks PASS)  
**Assets**: SPY, GLD, 0050.TW  
**OOS Period**: 2020-01-01 – 2026-04-17  

## Motivation

K1257 showed standard Bayesian Model Averaging (BMA) collapses posterior weights to a single model
(A4f_IV2/HAR-VIX for SPY; GJR-t for 0050.TW) within ~500 OOS days — a mathematically inevitable
outcome of product-of-likelihoods with non-stationary forecast precision.

K1317 tests whether forgetting-factor BMA (Dynamic Model Averaging, Raftery et al. 2010) with
δ∈{0.90, 0.95, 0.99, 1.00} can restore model diversity and improve forecast quality.
Forgetting: `log_prior = δ × log_posterior_{t-1}` (renormalized) before Bayesian update.

## Hypotheses

- **H1**: Forgetting-factor BMA (best δ) significantly outperforms standard BMA (δ=1) — Harvey |t|>3
- **H2**: Forgetting factor restores model diversity (entropy) relative to standard BMA — HAC t-test
- **H3**: Forgetting-factor BMA significantly outperforms best individual model (GJR-t) — Harvey |t|>3

## Results

| Asset    | Best δ | DM vs Standard (t) | H1   | H2   | DM vs GJR-t (t) | H3   |
|----------|--------|--------------------|------|------|-----------------|------|
| SPY      | 0.99   | +1.69              | FAIL | PASS | −3.83           | PASS |
| GLD      | 0.99   | +1.22              | FAIL | PASS | −1.82           | FAIL |
| 0050.TW  | 0.90   | −0.02              | FAIL | PASS | −0.02           | FAIL |

**H2 entropy restoration (HAC t-stat)**: SPY +20.96, GLD +24.06, 0050.TW +46.72 (all p≈0)

**Overall: H1=FAIL, H2=PASS, H3=FAIL → PASS_NULL**

## Interpretation

1. **Forgetting factor restores diversity** (H2 PASS): δ<1 prevents posterior concentration. All
   assets show highly significant entropy recovery. This confirms K1257's posterior collapse is a
   real phenomenon, not a numerical artifact.

2. **No forecast improvement over standard BMA** (H1 FAIL): Despite restored diversity, QLIKE
   improvement is small and statistically insignificant. The standard BMA's convergence to A4f_IV2
   (HAR-VIX, K1257/K1315) reflects true predictive dominance — the posterior concentration is
   Bayesian rational, not a bug.

3. **SPY exception** (H3 PASS for SPY only): Forgetting-factor BMA beats the individual GJR-t
   model for SPY (t=−3.83), but this is market-specific and doesn't generalize across assets.

4. **Consistent with VIX sufficient statistic** (K1315): Standard BMA correctly identifies HAR-VIX
   as the dominant model for SPY. Forgetting factor spreads weight across inferior models without
   improving net forecasts.

## Model Pool

GARCH_N, GJR_N, GJR_t, EGARCH_N, HAR_ABS, A4f_IV2 (IV proxy: SPY→^VIX, GLD→^GVZ, TW→^VIX)

## Files

- `k1317.py` — experiment script (seed=42, rolling IS=1250, refit every 63 days)
- `k1317_results.json` — full results per asset × delta
- `k1317_entropy_evolution.png` — entropy over time by delta
- `k1317_qlike_comparison.png` — QLIKE comparison plot

## References

- Raftery et al. (2010) "Online Prediction Under Model Uncertainty via Dynamic Model Averaging" JASA 105(490):1303-1316
- Cogley & Sargent (2005) "Drifts and Volatilities"
- Geweke & Amisano (2011) "Optimal Prediction Pools" J. Econometrics 164(1):130-141
- K1257: Standard BMA posterior collapse finding
- K1315: VIX sufficient statistic for SPY
- K1316: Cross-market IV transfer NULL result
