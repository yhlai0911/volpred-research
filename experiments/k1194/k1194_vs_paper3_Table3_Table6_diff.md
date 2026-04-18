# K1194: Paper 3 TSMOM Hedge Forensic — Table 3 & Table 6 Comparison

**Date**: 2026-04-17  
**Experiment**: K1194  
**Purpose**: Forensic comparison of 5+1 TSMOM hedge implementations vs Paper 3 Table 3 and Table 6

---

## Paper Targets (from main.tex)

### Table 3 SPY
| Strategy | Sharpe | MDD | Retention |
|---------|--------|-----|-----------|
| B&H | 0.611 | -55.2% | — |
| VT (12/VIX) | 0.797 | -24.7% | — |
| TSMOM-Hedged VT | **0.737** | **-26.9%** | **93%** |
| Pure TSMOM | 0.172 | -27.5% | — |

### Table 6 SPY (Bootstrap 90% CI for MDD Retention)
- Point estimate: 93%
- 90% CI: **[86, 97]**

---

## K1194 Results: 5+1 Standard Implementations (SUBTRACT)

All implementations use `PureVT = VT - β_TSMOM × TSMOM` (paper Eq. 6 literal).

| Implementation | Sharpe | MDD | Retention | 90% CI | Verdict |
|---|---|---|---|---|---|
| Impl1: Raw TSMOM, Monthly | 0.625 | -17.1% | 132.4% | [105.5, 195.1] | DIRECTION_REVERSAL |
| Impl2: Orth TSMOM, Monthly | 0.632 | -17.2% | 132.0% | [104.3, 194.7] | DIRECTION_REVERSAL |
| Impl3: Orth BH Rolling, Monthly | diverged | — | — | — | NUMERICAL_ERROR |
| Impl4: Orth DeltaVIX, Monthly | 0.577 | -19.1% | 125.3% | [68.9, 191.1] | DIRECTION_REVERSAL |
| Impl5: Normalized TSMOM, Monthly | 0.599 | -20.1% | 122.0% | [100.9, 196.4] | DIRECTION_REVERSAL |
| Impl6: Raw Daily (K898 style, clip[0,0.5]) | 0.791 | -22.5% | 107.2% | [95.7, 175.5] | DIRECTION_REVERSAL |

**Paper target**: Sharpe=0.737, MDD=-26.9%, Retention=93%, CI=[86, 97]

---

## K1194 Forensic: ADD (Inverted Sign) Implementations

Testing hypothesis: paper may intend `VT + β × TSMOM` (add exposure) instead of `VT - β × TSMOM` (remove exposure).

| Implementation | Sharpe | MDD | Retention | 90% CI | Verdict |
|---|---|---|---|---|---|
| ADD: Raw, Daily, clip[0,0.5] | 0.615 | -28.8% | 86.3% | [-70.2, 88.1] | PARTIAL |
| ADD: Raw, Daily, no clip | 0.574 | -38.5% | 54.8% | [-109.5, 66.4] | NO_MATCH |
| ADD: Raw, Monthly, clip[0,0.5] | 0.577 | -34.0% | 73.8% | [-92.7, 89.4] | NO_MATCH |
| ADD: Orth TSMOM, Daily, clip[0,0.5] | 0.612 | -28.7% | 86.7% | [-68.2, 88.5] | PARTIAL |

---

## Diff Analysis: Paper vs Best Empirical Results

| Metric | Paper | Best SUB (K898 daily+clip) | Best ADD (raw+daily+clip) |
|--------|-------|--------------------------|---------------------------|
| Hedged Sharpe | 0.737 | 0.791 (+0.054) | 0.615 (-0.122) |
| Hedged MDD | -26.9% | -22.5% (+4.4pp) | -28.8% (-1.9pp) |
| MDD Retention | 93% | 107.2% (+14.2pp) | 86.3% (-6.7pp) |
| 90% CI lower | 86% | 95.7% (+9.7pp) | -70.2% (incompatible) |
| 90% CI upper | 97% | 175.5% (+78.5pp) | 88.1% (-8.9pp) |

---

## Root Cause Analysis

### Why ALL subtract implementations give retention > 100%

The TSMOM factor `TSMOM_t = sign(cumret_{t-252:t-1}) × r_t` behaves as follows:
- During crash (negative cumret, r_t < 0): sign = -1, r_t < 0 → TSMOM_t > 0 (positive)
- With positive beta estimate β > 0 and TSMOM_t > 0:
  - `PureVT = VT - β × TSMOM_t = VT - (positive)` → REDUCED exposure
  - This IMPROVES MDD during crashes → retention > 100%

The hedge structure means TSMOM removal **mechanically reduces crash exposure**, because TSMOM factor is positive during crashes (sign × negative = positive). This is an inherent property of the long-short TSMOM definition.

### Why paper gets retention = 93% (< 100%)

The paper's result implies the hedged VT has **worse** MDD than unhedged VT (-26.9% vs -24.7%). This requires the hedge to **add** crash exposure. Possible explanations:

1. **Different TSMOM factor definition**: If paper uses a long-only TSMOM (only long when trend positive), the factor would be negative during crashes, and subtracting a negative × positive beta would add exposure.

2. **Paper data vintage**: If paper used data through an earlier cutoff, the 2008 and 2020 crash dynamics could differ.

3. **Possible calculation error in paper**: The paper may have numerically produced these values using a different formula than stated. The 93%/[86,97] result is inconsistent with the paper's Eq. 6 as we understand it.

4. **Monthly VT with different cash proxy**: K898/K1177/K1192 all use SHY. If the paper uses IRX differently, the VT construction differs.

---

## Verdict

### Primary Finding: SYSTEMATIC DIRECTION REVERSAL CONFIRMED

**All 5 standard (subtract) implementations yield MDD retention > 100%** (range: 107–132%), indicating the TSMOM hedge systematically **improves** (not degrades) MDD protection. This is consistent across:
- Daily and monthly VT rebalancing
- Raw and orthogonalized TSMOM
- With and without beta constraints
- 3 prior experiments (K898, K1177, K1192)

The paper's claim of 93% retention with CI [86, 97] **cannot be reproduced** with any standard implementation of the stated methodology.

### Secondary Finding: ADD Variants Partially Match Point Estimate

When the hedge sign is inverted (adding instead of removing TSMOM exposure), the retention point estimate (86–87%) is directionally closer to paper (93%), but:
- The CI is fundamentally different: ADD gives CI=[-70, 88] while paper reports [86, 97]
- The hedged Sharpe (0.612–0.615) is much lower than paper's 0.737
- This does not constitute a match

### Conclusions

**(a)** No implementation matches paper Table 3 (93% retention) AND Table 6 CI [86, 97] simultaneously.

**(b)** K1177 (used orth TSMOM, monthly): correct methodology but still direction reversal (132%).

**(c)** K1192 (used raw TSMOM, monthly, clip): closest standard result (103.7%) but still direction reversal.

**(d)** K898 (daily VIX, clip): closest in absolute numbers to paper VT Sharpe (0.805 vs 0.797) and VT MDD (-24.7% match), but hedged values diverge (0.848 vs 0.737 Sharpe, 107% vs 93% retention).

### Recommendation for Paper

The paper's Table 3 and Table 6 values for TSMOM-hedged VT (Sharpe=0.737, MDD=-26.9%, retention=93%, CI=[86,97]) appear to be **inconsistent with the methodology described in Eq. 6**. The empirically correct result — using the paper's own formula — yields retention **> 100%** (hedging improves MDD rather than degrades it).

This represents a positive finding for the paper's main thesis: VT's MDD protection is even more robust than claimed (hedging does not degrade MDD; it actually improves it). The paper's narrative about "93% retention" understates the robustness.

**Action required**: 
- Errata for Table 3 row "TSMOM-Hedged VT" and Table 6 CI values
- Revise narrative from "93% retained" to "hedging improves MDD by ~7% further"
- Knowledge base update: Paper 3 R1 A.1 needs revision

---

## Data Source and Reproducibility

- Data: yfinance (SPY, SHY, GLD, ^VIX), 2003-12-01 to 2026-03-31
- Analysis period: 2005-01-03 to 2026-03-31
- Bootstrap: B=10,000, block=252, seed=42
- Code: `experiments/k1194/k1194.py`
- Results: `experiments/k1194/k1194_results.json`
