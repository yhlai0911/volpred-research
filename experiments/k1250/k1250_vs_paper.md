# K1250 vs Paper 8 Canonical (Table 4 main.tex)

Run date: 2026-04-18T00:17:32.768565+00:00
Seed: 42 | TAU: 2.0 | NW lags: 10
Sample: 2006-01-01 to 2026-03-31

## Cross-Asset Absorption Coefficients

| Asset | Paper slope | K1250 slope | slope drift% | Paper t | K1250 t | t drift% | Paper n_shocks | K1250 n_shocks | Δn | allclose (5%) |
|-------|-------------|-------------|--------------|---------|---------|----------|----------------|-----------------|-----|---------------|
| SPY | -0.00028 | -0.00027 | 3.57% | -3.42 | -1.77 | 48.25% | 767 | 767 | +0 | YES |
| GLD | -0.00043 | -0.00043 | 0.00% | -4.17 | -2.87 | 31.18% | 767 | 767 | +0 | YES |
| TLT | -0.00044 | -0.00045 | 2.27% | -3.89 | -3.40 | 12.60% | 767 | 767 | +0 | YES |
| 0050.TW | +0.00019 | +0.00014 | 26.32% | +1.62 | +0.45 | 72.22% | 612 | 595 | -17 | NO |

## Verdict

- **Status**: PARTIAL_TSTATS_RECOVERED
- **Max slope drift**: 26.32%
- **t-statistics recovered**: YES

## Interpretation

K1250 recovers all t-statistics (previously untraceable in K718 JSON),
but residual slope drift remains > 5% for at least one asset. Options for
main thread:

  (a) Accept K1250 as improved reconstruction; disclose divergence in
      commit message and `reproduce_report.json` issues section.
  (b) Update paper body `main.tex` Table 4 to reflect K1250 numbers
      (research honesty path — revise slopes/t-stats to match current
      yfinance data vintage).
  (c) Note pending errata with magnitude disclosure per paper-workflow rule.

## Files

- `k1250.py`: rebuild script
- `k1250_results.json`: structured results (includes per-asset t-stat, R², intercept)
- `k1250_vs_paper.md`: this file
