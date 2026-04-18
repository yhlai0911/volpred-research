# K718 Reconstruction Diff Report

Comparison: `k718_results.json` (original) vs `k718_results_reconstructed.json` (reconstructed)

Reconstruction date: 2026-04-17
Threshold: rtol=0.01, atol=1e-4

## Per-Asset Comparison

| Asset | Field | Original | Reconstructed | Diff | Match? |
|-------|-------|----------|---------------|------|--------|
| SPY | normalized_slope | -0.00028 | -0.00027 | 0.000010 | NO |
| SPY | n_shocks | 767 | 744 | 23.000000 | NO |
| SPY | paralysis | YES | YES | string | YES |
| SPY | ratio_calm | 3.16 | 3.13 | 0.0300 | YES |
| SPY | ratio_normal | 2.68 | 2.35 | 0.3300 | NO |
| SPY | ratio_high | 2.63 | 2.63 | 0.0000 | YES |
| GLD | normalized_slope | -0.00043 | -0.00043 | 0.000000 | YES |
| GLD | n_shocks | 767 | 744 | 23.000000 | NO |
| GLD | paralysis | YES | YES | string | YES |
| GLD | ratio_calm | 1.24 | 1.29 | 0.0500 | NO |
| GLD | ratio_normal | 1.22 | 1.15 | 0.0700 | NO |
| GLD | ratio_high | 1.37 | 1.37 | 0.0000 | YES |
| TLT | normalized_slope | -0.00044 | -0.00041 | 0.000030 | NO |
| TLT | n_shocks | 767 | 744 | 23.000000 | NO |
| TLT | paralysis | YES | YES | string | YES |
| TLT | ratio_calm | 1.32 | 1.46 | 0.1400 | NO |
| TLT | ratio_normal | 1.44 | 1.32 | 0.1200 | NO |
| TLT | ratio_high | 1.47 | 1.46 | 0.0100 | YES |
| 0050.TW | normalized_slope | 0.00019 | 8e-05 | 0.000110 | NO |
| 0050.TW | n_shocks | 612 | 572 | 40.000000 | NO |
| 0050.TW | paralysis | NO | NO | string | YES |
| 0050.TW | ratio_calm | 1.24 | 1.18 | 0.0600 | NO |
| 0050.TW | ratio_normal | 1.25 | 1.31 | 0.0600 | NO |
| 0050.TW | ratio_high | 1.21 | 1.14 | 0.0700 | NO |

## Summary

| Field | Original | Reconstructed | Match? |
|-------|----------|---------------|--------|
| paralysis_count | 3 | 3 | YES |
| total_assets | 4 | 4 | YES |

## Overall Status

**Reconstruction result: APPROXIMATE — see divergences above**

### Likely causes of divergence:
- SAR 3-bucket mapping may differ from 5-bucket (original may use different regime boundaries)
- 0050.TW trading calendar differences
- Newey-West computation differences (exact kernel weights)
- Data revisions in yfinance since original computation

**Paper errata risk**: Slopes -0.00028 (SPY), -0.00043 (GLD), -0.00044 (TLT), +0.00019 (0050.TW)
in Table 3 of main_v2.tex. If divergence >1%, errata may be needed.