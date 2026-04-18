# K716 Reconstruction Diff Report

Comparison: `k716_results.json` (original, ground truth) vs `k716_results_reconstructed.json` (reconstructed from main_v2.tex methodology)

Reconstruction date: 2026-04-17
Threshold: rtol=0.01, atol=1e-4

## SAR Table Comparison

| Regime | Field | Original | Reconstructed | Diff | Match? |
|--------|-------|----------|---------------|------|--------|
| calm (<15) | shock_days | 34 | 34 | 0 | YES |
| calm (<15) | shock_abs_r | 1.24 | 1.23 | 0.0100 | YES |
| calm (<15) | normal_abs_r | 0.39 | 0.39 | 0.0000 | YES |
| calm (<15) | ratio | 3.16 | 3.15 | 0.0100 | YES |
| normal (15-20) | shock_days | 168 | 168 | 0 | YES |
| normal (15-20) | shock_abs_r | 1.44 | 1.44 | 0.0000 | YES |
| normal (15-20) | normal_abs_r | 0.52 | 0.52 | 0.0000 | YES |
| normal (15-20) | ratio | 2.77 | 2.77 | 0.0000 | YES |
| elevated (20-25) | shock_days | 189 | 189 | 0 | YES |
| elevated (20-25) | shock_abs_r | 1.64 | 1.65 | 0.0100 | YES |
| elevated (20-25) | normal_abs_r | 0.69 | 0.69 | 0.0000 | YES |
| elevated (20-25) | ratio | 2.37 | 2.37 | 0.0000 | YES |
| high (25-30) | shock_days | 132 | 132 | 0 | YES |
| high (25-30) | shock_abs_r | 1.93 | 1.93 | 0.0000 | YES |
| high (25-30) | normal_abs_r | 0.83 | 0.83 | 0.0000 | YES |
| high (25-30) | ratio | 2.32 | 2.32 | 0.0000 | YES |
| crisis (>30) | shock_days | 244 | 244 | 0 | YES |
| crisis (>30) | shock_abs_r | 2.99 | 3.0 | 0.0100 | YES |
| crisis (>30) | normal_abs_r | 1.23 | 1.23 | 0.0000 | YES |
| crisis (>30) | ratio | 2.43 | 2.45 | 0.0200 | YES |

## Scalar Fields

| Field | Original | Reconstructed | Diff | Match? |
|-------|----------|---------------|------|--------|
| regression_raw_slope | 0.0669 | 0.0677 | 0.000800 | NO |
| regression_normalized_slope | -0.00028 | -0.00027 | 0.000010 | NO |
| conclusion | paralysis | paralysis | string | YES |

## Overall Status

**Reconstruction result: APPROXIMATE — see divergences above**

### Likely causes of divergence:
- Data range end date: original may have used slightly different end date
- Rounding in original results (stored as 2 decimal places)
- yfinance data revision since original computation
- Trading calendar differences

**Paper errata risk**: Numbers in main_v2.tex may need verification if divergence >1%