# K1175: Paper 2 Table 3 VT 2010-2026 Canonical Replication

## Purpose

BLOCKER D1 resolution for Paper 2 (taiwan-vt). The reproducibility audit (commit 8b43604a)  
identified that Table 3's VT Performance numbers claim a 2010-2026 period but no experiment  
JSON covered this period. K900 only covered 2019-2026 with entirely different numbers.

This experiment runs the exact K900 methodology with per-strategy periods that match  
Paper 2's Table 3 notes:
- Buy & Hold + EWMA VT: 2010–2026
- GARCH VT + GJR VT: 2020–2026  
- 8.63/VIX: 2016–2026

## Key Findings

### 1. Paper Table 3 Buy & Hold Numbers Are Arithmetically Inconsistent

The paper claims: Return=10.2%, Vol=20.8%, Sharpe=0.729.  
But 10.2 / 20.8 = 0.490 (not 0.729 at RF=0).  
**The three numbers cannot simultaneously be correct.** This is an error in the paper.

K1175 canonical (2010-2026): Return=14.48%, Vol=18.13%, Sharpe=0.799 — self-consistent.

### 2. MDD=-41.3% Requires Pre-2009 Data

yfinance 0050.TW starts 2009-01-02. The maximum drawdown since 2009 is -33.83%  
(from the 2022 rate-hiking bear market). To achieve -41.3% MDD would require data  
including the 2008 financial crisis — which is not available via yfinance for 0050.TW.

### 3. Turnover Mismatch Indicates Different Rebalancing Spec

Paper's turnover: EWMA=116%/yr, GARCH=98%/yr, GJR=102%/yr.  
K1175 (daily rebalancing): EWMA=480%/yr, GARCH=678%/yr, GJR=694%/yr.  
Monthly EWMA rebalancing: TO=142%/yr — closer but still not matching.

### 4. Sharpe Ratios Are Approximately Correct for GARCH/GJR

GARCH VT: K1175=0.950 vs paper=0.994 (4.5% diff — within tolerance)  
GJR VT: K1175=1.074 vs paper=1.108 (3.1% diff — within tolerance)

## Decision: (b) Update Paper

Option (a) "fix script" is not applicable — the data doesn't exist in yfinance to reproduce  
the paper's -41.3% MDD or the arithmetic inconsistency of B&H row.

Option (b) "update paper to canonical K1175 numbers" is required:
- Buy & Hold row: update Return, Vol, Sharpe, MDD to K1175 values
- EWMA/GARCH/GJR: update MDD and Return; confirm rebalancing frequency  
- Update abstract and Section 4 narrative text which references "0.729 to 0.796"

See `k1175_vs_paper2_table3_diff.md` for the full per-cell analysis.

## Files

| File | Description |
|------|-------------|
| `k1175.py` | Replication script (K900 methodology, 2010-2026 per-strategy periods) |
| `k1175_results.json` | Full results with per-strategy backtests and diff table |
| `k1175_vs_paper2_table3_diff.md` | Per-cell diff with root cause analysis and (a)/(b)/(c) decision |
| `run.log` | Full execution log |

## Data

- Source: yfinance (0050.TW, ^VIX) with `clean_tw50_data` split correction (same as K900)
- 0050.TW available from 2009-01-02 (yfinance limitation)
- VIX lagged: previous US trading day close (strictly < Taiwan date)
- Seed: 42

## Configuration (Identical to K900)

- EWMA λ = 0.94
- Target volatility = 10% annualized
- GARCH window = 2000 days
- Transaction cost = 0.186% round-trip
- Daily rebalancing for GARCH/EWMA; monthly for VIX strategies

## Canonical Table 3 Numbers (K1175)

| Strategy | Period | Sharpe | MDD (%) | Return (%) | Vol (%) | TO (%/yr) |
|----------|--------|--------|---------|-----------|---------|----------|
| Buy & Hold | 2010-2026 | 0.799 | -33.83 | 14.48 | 18.13 | 0 |
| EWMA VT 10% | 2010-2026 | 0.701 | -21.17 | 7.42 | 10.58 | 480 |
| GARCH VT 10% | 2020-2026 | 0.950 | -22.18 | 10.50 | 11.06 | 678 |
| GJR VT 10% | 2020-2026 | 1.074 | -22.25 | 12.19 | 11.35 | 694 |
| 8.63/VIX (monthly) | 2016-2026 | 1.137 | -13.71 | 10.72 | 9.43 | 102 |

## References

- K900: Taiwan VT Performance (2019-2026 period)
- K558: Taiwan Hybrid Leverage deep validation (2010-2026, 8.63/VIX base Sharpe=0.472)
- Moreira & Muir (2017) JF — Volatility-managed portfolios
- paper/taiwan-vt/reproducibility_audit/diff_report.md — original BLOCKER D1 description

## Status

- Experiment completed: 2026-04-17
- Decision: **(b) Update paper** — K1175 as canonical
- main.tex/body.tex: **NOT MODIFIED** (per worktree rules)
- K900 results: **NOT MODIFIED**
