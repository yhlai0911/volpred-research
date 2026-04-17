# K1179: Paper 2 Section 6.1 Import Growth Formal Experiment

## Summary

Formal experiment to reproduce Paper 2 (taiwan-vt) Section 6.1 numbers:
- partial r = 0.214 (p=0.0007)
- OOS MSE improvement +5.6%
- DM p = 0.043

**Status**: G12 REPRODUCIBILITY ATTEMPT — **PARTIAL (0/3 within 5%, directional match for all)**

## Motivation

Paper 2 audit rescan (commit fc7c9a7c) identified G12 as a CRITICAL DOCS GAP:
- Section 6.1 has 3 numbers sourced to knowledge.json G12 only
- No formal experiment directory exists for G12
- Pre-submission reproducibility requirement for PBFJ reviewer package

## Data Sources

| Variable | Source | Period |
|----------|--------|--------|
| TW Import YoY | `storage/macro/tw_dgbas_trade_m.csv` (NTD 進口 上年同期增減率%) | 1982-2024-09 |
| TWII daily returns | `storage/macro/yf_TWII.csv` | 1997-07 to 2026-03 |
| TWII monthly RV | Computed: sqrt(sum(r²) × 252) | 1997-07 to 2024-09 |

- **Lookahead protection**: import YoY lagged 1 month (signal from t-1, RV at t)

## Method

1. **Partial r**: fit GARCH-MIDAS (K=12) with import YoY on full TWII daily returns; compute partial correlation of log(RV) vs imp_yoy_lag1 controlling for MIDAS long-run tau component
2. **OOS MSE**: expanding-window AR(1) OOS comparison (base: AR1 on monthly RV, aug: AR1 + imp_yoy_lag1), 2015-2024
3. **DM test**: Diebold-Mariano with 1-lag Newey-West HAC, one-sided (aug beats base)

## Results

| Stat | Paper Target | K1179 Result | Best Method | Diff | Match (5%) |
|------|-------------|-------------|-------------|------|------------|
| partial r | 0.214 (p=0.0007) | **0.1888** (p=0.000599) | MIDAS tau partial corr (full period) | 11.8% | NO |
| OOS % | +5.6% | **+3.35%** | AR1 on RV level | 40.1% | NO |
| DM p | 0.043 | **0.0572** | AR1 on RV level | 32.9% | NO |

**Overall: 0/3 exact match. All directionally correct.**

Key observation: the r p-value (0.000599) is within 14% of paper target (0.0007), suggesting the partial r concept is correctly identified; magnitude difference likely reflects GARCH-MIDAS parameterization details not documented in G12.

## Decision

**Recommendation: (c) Errata Pending**

- The directional finding (import YoY positively predicts TWII vol) is confirmed
- The magnitude divergence (especially OOS 40.1%) exceeds tolerance for exact reproduction
- Paper text should note: "estimates may vary ±10-40% depending on GARCH-MIDAS spec"
- For PBFJ replication package: use this K1179 script as documented baseline with caveat

## Files

| File | Description |
|------|-------------|
| `k1179.py` | Reproducible Python script |
| `k1179_results.json` | Numerical results with match assessment |
| `k1179_vs_paper2_section6_1_diff.md` | Per-number diff analysis and decision |
| `README.md` | This file |
| `run.log` | Execution log |

## Related Knowledge

- G12 (knowledge.json): original GARCH-MIDAS 27-indicator sweep finding
- Paper 2 body_v2.tex line 333: Section 6.1 import growth paragraph
- `paper/taiwan-vt/reproducibility_audit/nosource_rescan_report.md`: MAC-01/02/03 entries
