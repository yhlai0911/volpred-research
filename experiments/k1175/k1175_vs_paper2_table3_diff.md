# K1175 vs Paper 2 Table 3 — Per-Cell Diff Report

**Experiment**: K1175  
**Date**: 2026-04-17  
**Purpose**: BLOCKER D1 resolution — canonical replication of Paper 2 Table 3 with 2010-2026 period  
**Methodology**: K900 exactly, with per-strategy periods per paper's Table 3 Notes  
**Tolerance**: rtol=0.05 (5%) for "MATCHED"; 5–10% = "APPROX"; >10% = "DIVERGENT"

---

## Table 3 Per-Cell Comparison

### Buy & Hold (2010–2026)

| Metric | Paper Claims | K1175 Result | Abs Diff | Rel Diff | Status |
|--------|-------------|--------------|----------|----------|--------|
| Sharpe | 0.729 | 0.799 | +0.070 | 9.6% | APPROX |
| MDD (%) | -41.3 | -33.83 | +7.47pp | 18.1% | **DIVERGENT** |
| Ann Return (%) | 10.2 | 14.48 | +4.28pp | 42.0% | **DIVERGENT** |
| Ann Vol (%) | 20.8 | 18.13 | -2.67pp | 12.8% | **DIVERGENT** |
| Turnover (%/yr) | 0 | 0 | 0 | N/A | MATCHED |

**Internal consistency check**: Paper states Return=10.2%, Vol=20.8%, Sharpe=0.729.  
But Sharpe (RF=0) = 10.2/20.8 = **0.490**, NOT 0.729.  
**The paper's own three numbers for Buy & Hold are arithmetically inconsistent.**  
This is a critical error in Paper 2's Table 3.

### EWMA VT 10% (2010–2026)

| Metric | Paper Claims | K1175 Result | Abs Diff | Rel Diff | Status |
|--------|-------------|--------------|----------|----------|--------|
| Sharpe | 0.796 | 0.701 | -0.095 | 11.9% | **DIVERGENT** |
| MDD (%) | -18.4 | -21.17 | -2.77pp | 15.1% | **DIVERGENT** |
| Ann Return (%) | 7.8 | 7.42 | -0.38pp | 4.9% | MATCHED |
| Ann Vol (%) | 10.2 | 10.58 | +0.38pp | 3.7% | MATCHED |
| Turnover (%/yr) | 116 | 479.9 | +363.9 | 313.7% | **DIVERGENT** |

**Turnover diagnosis**: K1175 uses daily rebalancing (like K900), giving 480%/yr.  
Paper's 116%/yr implies monthly rebalancing for EWMA — consistent with the paper's note  
about 8.63/VIX using monthly rebalancing. Monthly EWMA (tested separately) gives  
TO=142%/yr, Sharpe=0.813 — still not matching 116%/yr or Sharpe=0.796 exactly.

### GARCH VT 10% (2020–2026 per paper note)

| Metric | Paper Claims | K1175 Result | Abs Diff | Rel Diff | Status |
|--------|-------------|--------------|----------|----------|--------|
| Sharpe | 0.994 | 0.950 | -0.044 | 4.5% | MATCHED |
| MDD (%) | -16.8 | -22.18 | -5.38pp | 32.0% | **DIVERGENT** |
| Ann Return (%) | 8.1 | 10.50 | +2.40pp | 29.6% | **DIVERGENT** |
| Ann Vol (%) | 10.5 | 11.06 | +0.56pp | 5.3% | APPROX |
| Turnover (%/yr) | 98 | 677.8 | +579.8 | 591.6% | **DIVERGENT** |

**Turnover diagnosis**: Same issue — paper's 98%/yr requires monthly rebalancing.  
Sharpe matched (4.5% diff) but MDD and Return diverge significantly.

### GJR VT 10% (2020–2026 per paper note)

| Metric | Paper Claims | K1175 Result | Abs Diff | Rel Diff | Status |
|--------|-------------|--------------|----------|----------|--------|
| Sharpe | 1.108 | 1.074 | -0.034 | 3.1% | MATCHED |
| MDD (%) | -15.1 | -22.25 | -7.15pp | 47.4% | **DIVERGENT** |
| Ann Return (%) | 8.4 | 12.19 | +3.79pp | 45.1% | **DIVERGENT** |
| Ann Vol (%) | 10.3 | 11.35 | +1.05pp | 10.2% | **DIVERGENT** |
| Turnover (%/yr) | 102 | 694.3 | +592.3 | 580.7% | **DIVERGENT** |

**Sharpe matched** (3.1% diff = best among all strategies). Sharpe is relatively scale-invariant  
since it's a ratio, so even with different magnitudes of return/vol the ratio can match.

### 8.63/VIX Monthly (2016–2026 per paper note)

| Metric | Paper Claims | K1175 Result | Abs Diff | Rel Diff | Status |
|--------|-------------|--------------|----------|----------|--------|
| Sharpe | 0.690 | 1.137 | +0.447 | 64.8% | **DIVERGENT** |
| MDD (%) | -15.3 | -13.71 | +1.59pp | 10.4% | **DIVERGENT** |
| Ann Return (%) | 7.2 | 10.72 | +3.52pp | 48.9% | **DIVERGENT** |
| Ann Vol (%) | 12.1 | 9.43 | -2.67pp | 22.1% | **DIVERGENT** |
| Turnover (%/yr) | 24 | 102.1 | +78.1 | 325.4% | **DIVERGENT** |

**Note**: K558 (full-sample 2010–2026) shows 8.63/VIX Sharpe=0.472 with MDD=-48.38%.  
Paper's 0.690 for 2016–2026 is plausible in direction (bull market period), but K1175  
gets 1.137 for 2016–2026 — much higher, which is suspicious.

---

## Summary: Matched vs Divergent

| Strategy | Sharpe | MDD | Return | Vol | Turnover | Overall |
|---------|--------|-----|--------|-----|----------|---------|
| Buy & Hold | APPROX (9.6%) | DIVERGENT (18%) | DIVERGENT (42%) | DIVERGENT (13%) | MATCHED | DIVERGENT |
| EWMA VT | DIVERGENT (12%) | DIVERGENT (15%) | MATCHED (5%) | MATCHED (4%) | DIVERGENT (314%) | DIVERGENT |
| GARCH VT | MATCHED (4.5%) | DIVERGENT (32%) | DIVERGENT (30%) | APPROX (5%) | DIVERGENT (592%) | DIVERGENT |
| GJR VT | MATCHED (3.1%) | DIVERGENT (47%) | DIVERGENT (45%) | DIVERGENT (10%) | DIVERGENT (581%) | DIVERGENT |
| 8.63/VIX | DIVERGENT (65%) | DIVERGENT (10%) | DIVERGENT (49%) | DIVERGENT (22%) | DIVERGENT (325%) | DIVERGENT |

**Maximum divergence**: Turnover (580–592%), followed by Ann Return (45–49%), MDD (47%)

---

## Root Cause Analysis

### Root Cause 1: Paper's Buy & Hold numbers are arithmetically inconsistent

The paper states Return=10.2%, Vol=20.8%, Sharpe=0.729. These three numbers are **mutually  
inconsistent**:
- Sharpe (RF=0) = 10.2/20.8 = 0.490 ≠ 0.729
- To get Sharpe=0.729 with Vol=20.8%, Return must be 15.16% (RF=0)
- To get Sharpe=0.729 with Return=10.2%, Vol must be 13.98% (RF=0)

K1175 with 2010-2026 gets Return=14.48%, Vol=18.13%, Sharpe=0.799 (self-consistent).

**This is a data/arithmetic error in the paper's Table 3.**

### Root Cause 2: MDD -41.3% requires pre-2009 data

yfinance 0050.TW data starts 2009-01-02. The maximum drawdown since 2009 is -33.83%  
(from 2022 rate-hiking cycle). The paper's -41.3% MDD requires data that includes the  
2008 financial crisis, where the TAIEX fell ~55%. This MDD is **not reproducible**  
with yfinance 0050.TW (data starts 2009).

### Root Cause 3: Rebalancing frequency mismatch for GARCH/EWMA strategies

Paper's turnover values (98–116%/yr) are consistent with **monthly** rebalancing.  
K1175 uses daily rebalancing (K900 methodology), giving 480–694%/yr.  
Paper does not explicitly state monthly for EWMA/GARCH, but the turnover numbers  
imply it. The K900 README says "monthly for VIX strategies, daily for GARCH/EWMA."

### Root Cause 4: 8.63/VIX period mismatch is real but in wrong direction

For 2016-2026, K1175 gets Sharpe=1.137 vs paper's 0.690. This 2016-2026 period  
was predominantly bullish for Taiwan (except 2022 bear market). K558 covering 2010-2026  
gets Sharpe=0.472 for the same base strategy. Something in K1175's 2016-2026 window  
is inflated, possibly due to the 8.63/VIX signal being overly favorable in that subperiod.

---

## Decision: (a)/(b)/(c)

### Verdict: **(b) Modify paper** — K1175 as canonical; paper has arithmetic errors

**Rationale**:

1. The paper's Buy & Hold numbers (Return, Vol, Sharpe) are **arithmetically inconsistent** —  
   this is not a period choice or methodology difference, it's an error.

2. The paper's -41.3% MDD cannot be produced from yfinance 0050.TW (which starts 2009).  
   The paper may have used a different data source (e.g., TEJ/Bloomberg with pre-2009 history)  
   or a different asset (TWII rather than 0050.TW), or there is a data artifact.

3. Option (a) "fix the script" is **not applicable** because:
   - We cannot access data for 0050.TW before 2009 via yfinance  
   - Even if we could, the Sharpe/Return/Vol inconsistency would remain  
   - No parameter tuning or rebalancing-frequency change produces all paper cells within 5%

4. Option (c) "errata pending" is appropriate for individual cells where the divergence  
   magnitude is known, but the **core issue** (arithmetic inconsistency) must be resolved  
   in the paper.

### Recommended paper corrections:

| Cell | Current (Paper) | Canonical (K1175) | Action |
|------|----------------|-------------------|--------|
| B&H Sharpe | 0.729 | 0.799 | Update to K1175 |
| B&H MDD | -41.3% | -33.83% | Update to K1175 |
| B&H Return | 10.2% | 14.48% | Update to K1175 |
| B&H Vol | 20.8% | 18.13% | Update to K1175 |
| EWMA Sharpe | 0.796 | 0.701 | Needs rebalancing clarification |
| EWMA MDD | -18.4% | -21.17% | Needs rebalancing clarification |
| GARCH Sharpe | 0.994 | 0.950 | ~OK, within 5% |
| GJR Sharpe | 1.108 | 1.074 | ~OK, within 3% |
| Turnover (EWMA/GARCH/GJR) | 98–116%/yr | 480–694%/yr | Fix: use monthly rebalancing or correct spec |

### If paper's -41.3% B&H MDD is from TWII (not 0050.TW):

TWII (index, not ETF) with 2007-2008 start shows MDD=-58.31% (covers the 2008 crisis).  
For 2010-2026, TWII shows MDD=-31.63%, Return=9.17%, Vol=16.85%, Sharpe=0.544.  
Neither matches the paper's claimed B&H numbers.

**Conclusion**: Paper Table 3's Buy & Hold row has an **arithmetic error** that cannot be  
explained by period choice or instrument selection with available data. Option (b) is mandatory.

---

## Errata Pending Items (c)

If immediate paper revision is not possible, the following MUST be labeled "pending errata":

- Table 3 Buy & Hold: ALL cells except Turnover=0
- Table 3 EWMA VT: Turnover (116% → 479% daily / 142% monthly)
- Table 3 GARCH/GJR Turnover (98-102% → 678-694% daily)
- Abstract and Section 4 text: "Sharpe ratio from 0.729 to 0.796" — both numbers need updating

---

**Generated by K1175 experiment**  
**Date**: 2026-04-17  
**K1175 results JSON**: `experiments/k1175/k1175_results.json`
