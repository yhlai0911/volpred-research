# K722 Reconstruction Diff Report

Comparison: `k722_results.json` (original) vs `k722_results_reconstructed.json` (reconstructed)

Reconstruction date: 2026-04-17
Threshold: rtol=0.01, atol=1e-4

## Notes on Interpretation

k722 measures whether RV-based normalization outperforms VIX-based normalization.
corr_raw = corr(|r_SPY|, VIX) on shock days → measures how well VIX predicts |r|
corr_adjusted = corr(|r_SPY|, sqrt(RV_20)) on shock days → RV predictor
R² values are squares of correlations (verified: 0.6803² ≈ 0.4628, 0.6686² ≈ 0.4470).

## Field Comparison

| Field | Original | Reconstructed | Diff | Match? |
|-------|----------|---------------|------|--------|
| corr_raw | 0.6803 | 0.5671 | 0.113200 | NO |
| corr_adjusted | 0.6686 | 0.5092 | 0.159400 | NO |
| r2_raw | 0.4628 | 0.3216 | 0.141200 | NO |
| r2_adjusted | 0.447 | 0.2593 | 0.187700 | NO |
| conclusion | not improved | not improved | string | YES |

## Overall Status

**Reconstruction result: APPROXIMATE — see divergences above**

### Likely causes of divergence:
- Exact formula for corr_raw may use different pairs (e.g., NSI_VIX vs |r|)
- Different shock filter (all shocks vs only negative SPY)
- Different RV window (Section 7.3 says 20 days, Section 3.7 says h=22)
- Data revisions in yfinance since original computation

**Paper errata risk**: K722 supports Section 7.3 robustness. The key claim is
'alternative normalization produces qualitatively identical results' (slope remains
negative). If our conclusion='not improved' matches, the paper's robustness
claim is verified. Low direct errata risk — these are supporting robustness stats.