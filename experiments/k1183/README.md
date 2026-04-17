# K1183: Paper 2 TSMC Decomposition

**Status**: COMPLETE — PARTIAL MATCH (outcome b)  
**Paper Section**: body.tex Sec 8.6 (TSMC Concentration Robustness)  
**Date**: 2026-04-17  

## Purpose

Reproduce Paper 2 TSMC decomposition claims:
- TSMC VT Sharpe = 1.121 (body.tex line ~529)
- ex-TSMC VT Sharpe range = 0.193–0.637 (body.tex line ~529)
- TSMC explains 52.5% of 0050.TW return variance (body.tex line ~533)

## Methodology

1. **TSMC Standalone VT**: EWMA VT (λ=0.94, 10% target) on 2330.TW, full sample 2012–2026
2. **ex-TSMC Portfolio**: Synthetic portfolio `r_ex = (r_0050 - w * r_tsmc) / (1 - w)`, varying w from 20% to 55%
3. **Variance decomposition**: OLS R² of 0050.TW returns on TSMC returns
4. **GJR-GARCH gamma**: Leverage effect in sub-period analysis
5. All with `signal.shift(1)` — no lookahead bias

## Key Results

| Metric | Paper | Computed | Match |
|--------|-------|----------|-------|
| TSMC VT Sharpe | 1.121 | **1.1244** | YES |
| ex-TSMC min Sharpe | 0.193 | **0.191** (w=0.52) | YES |
| ex-TSMC max Sharpe | 0.637 | **0.628** (w=0.32) | NEAR |
| TSMC variance % | 52.5% | **52.56%** | YES |

## Data

- 0050.TW (clean split): 4,217 days (2009-01-02 to 2026-03-30)
- 2330.TW TSMC: 4,467 days (2008-01-02 to 2026-03-30)
- Common observations: 4,215

## Files

- `k1183.py` — reproduction script (seed=42, no lookahead)
- `k1183_results.json` — full numerical results
- `k1183_vs_paper2_TSMC_diff.md` — detailed diff vs paper claims
- `run.log` — execution log

## Reproducibility Note

TSMC VT Sharpe 1.121 uses full available 0050.TW sample (2012-2026), NOT the 2019 OOS period used in main K900 tables. The ex-TSMC range spans TSMC weight assumptions from 32% (historical lower allocation) to 52% (current allocation).
