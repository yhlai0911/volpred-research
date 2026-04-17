# K717 Reconstruction Diff Report

Comparison: `k717_results.json` (original) vs `k717_results_reconstructed.json` (reconstructed)

## IMPORTANT STRUCTURAL NOTE

k717_results.json contains a **multi-strategy VT scorecard** (14 strategies including
slow_vt, risk_parity, taiwan_spy_momentum, etc.) rather than the NSI regression
described in Section 3 of main_v2.tex. This suggests K717 was a strategy comparison
experiment used for Section 6 (Economic Implications / VT Strategy Design), not the
NSI regression (which is produced in K716).

The reconstruction covers only 4 core strategies from the original 14. Full reconstruction
of all 14 strategies (taiwan_spy_momentum, tz_tw_jp_5050, vix_cond_leverage, etc.) would
require additional data sources and strategy specifications beyond what main_v2.tex provides.

**Reconstruction status: APPROXIMATE — partial strategy coverage**

## Strategy Coverage

| Strategy | In Original | In Reconstructed | Notes |
|----------|-------------|------------------|-------|
| adaptive_tier | YES | NO | Missing — needs full strategy spec |
| fear_dca | YES | NO | Missing — needs full strategy spec |
| global_vt_tz | YES | NO | Missing — needs full strategy spec |
| piecewise_conservative | YES | NO | Missing — needs full strategy spec |
| recommended_5050 | YES | YES | Reconstructed |
| risk_parity | YES | YES | Reconstructed |
| simple_12vix | YES | YES | Reconstructed |
| slow_vt | YES | YES | Reconstructed |
| taiwan_8.63vix | YES | NO | Missing — needs full strategy spec |
| taiwan_hybrid_leverage | YES | NO | Missing — needs full strategy spec |
| taiwan_spy_momentum | YES | NO | Missing — needs full strategy spec |
| tz_tw_jp_5050 | YES | NO | Missing — needs full strategy spec |
| vix_cond_leverage | YES | NO | Missing — needs full strategy spec |
| vix_leading_guard | YES | NO | Missing — needs full strategy spec |

## Metric Comparison (Available Strategies)

| Strategy | Metric | Original | Reconstructed | Diff |
|----------|--------|----------|---------------|------|
| recommended_5050 | cagr | 13.7 | 12.6 | 1.1 |
| recommended_5050 | sharpe | 1.87 | 1.44 | 0.43 |
| recommended_5050 | mdd | -7.8 | -8.1 | 0.3 |
| recommended_5050 | n_days | 809 | 873 | 64 |
| risk_parity | cagr | 21.6 | 15.1 | 6.5 |
| risk_parity | sharpe | 2.04 | 1.52 | 0.52 |
| risk_parity | mdd | -12.0 | -9.9 | 2.1 |
| risk_parity | n_days | 809 | 875 | 66 |
| simple_12vix | cagr | 9.6 | 10.0 | 0.4 |
| simple_12vix | sharpe | 1.16 | 1.05 | 0.11 |
| simple_12vix | mdd | -11.3 | -11.8 | 0.5 |
| simple_12vix | n_days | 809 | 873 | 64 |
| slow_vt | cagr | 10.0 | 10.0 | 0.0 |
| slow_vt | sharpe | 1.17 | 1.05 | 0.12 |
| slow_vt | mdd | -11.1 | -11.8 | 0.7 |
| slow_vt | n_days | 809 | 873 | 64 |

## Overall Status

**Reconstruction result: APPROXIMATE**

- Only 4 of 14 strategies reconstructed in this script
- Strategies with Taiwan data (0050.TW) or specialized overlays (vix_cond_leverage,
  taiwan_hybrid_leverage, piecewise_conservative, adaptive_tier) require full spec
- Metric values may diverge due to exact date range differences
- Paper risk: K717 strategies appear in Section 6 as supporting evidence only;
  core claims (SAR, NSI regression) are in K716/K718/K721. Low errata risk.