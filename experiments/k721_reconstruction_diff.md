# K721 Reconstruction Diff Report

Comparison: `k721_results.json` (original) vs `k721_results_reconstructed.json` (reconstructed)

Reconstruction date: 2026-04-17
Threshold: rtol=0.01, atol=1e-4

## Shock Type Comparison

| Type | Field | Original | Reconstructed | Diff | Match? |
|------|-------|----------|---------------|------|--------|
| risk-off | low_vix_impact | 1.46 | 1.47 | 0.0100 | YES |
| risk-off | high_vix_impact | 2.5 | 2.5 | 0.0000 | YES |
| risk-off | low_vix_norm | 0.083 | 0.083 | 0.0000 | YES |
| risk-off | high_vix_norm | 0.076 | 0.076 | 0.0000 | YES |
| risk-off | paralysis | YES | YES | string | YES |
| risk-off | n_low | 38 | 38 | 0.0000 | YES |
| risk-off | n_high | 144 | 148 | 4.0000 | NO |
| rate-shock | low_vix_impact | 1.5 | 1.51 | 0.0100 | YES |
| rate-shock | high_vix_impact | 1.93 | 1.78 | 0.1500 | NO |
| rate-shock | low_vix_norm | 0.085 | 0.086 | 0.0010 | NO |
| rate-shock | high_vix_norm | 0.066 | 0.06 | 0.0060 | NO |
| rate-shock | paralysis | YES | YES | string | YES |
| rate-shock | n_low | 23 | 23 | 0.0000 | YES |
| rate-shock | n_high | 56 | 64 | 8.0000 | NO |
| geopolitical | low_vix_impact | 1.28 | 1.28 | 0.0000 | YES |
| geopolitical | high_vix_impact | 2.48 | 2.51 | 0.0300 | NO |
| geopolitical | low_vix_norm | 0.073 | 0.073 | 0.0000 | YES |
| geopolitical | high_vix_norm | 0.076 | 0.076 | 0.0000 | YES |
| geopolitical | paralysis | NO | NO | string | YES |
| geopolitical | n_low | 29 | 29 | 0.0000 | YES |
| geopolitical | n_high | 117 | 121 | 4.0000 | NO |

## Overall Status

**Reconstruction result: APPROXIMATE — see divergences above**

### Likely causes of divergence:
- VIX threshold for 'high VIX' may differ (original may use 25 or 30)
- VIX threshold for 'low VIX' may differ (original may use <15 or <20)
- GLD threshold for geopolitical may differ from exactly 0.5%
- Data revisions in yfinance since original computation

**Paper errata risk**: Table tab:shock_types reports:
  Rate shocks: N=127, absorption=+0.019, t=2.87
  Risk-off: N=203, absorption=+0.007, t=1.94
  Geopolitical: N=89, absorption=-0.003, t=-0.68
  If paralysis direction (YES/NO) matches, paper conclusion holds.
  If NSI values diverge >5%, absorption coefficients may need errata.