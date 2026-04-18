# K1192: Paper 3 Table 6 Bootstrap MDD CI — Formal Reproduce

**Date**: 2026-04-17  
**Status**: COMPLETE — ALL 4 DEFINITIONS DIVERGE  
**Blocker**: Table 6 [86, 97] CANNOT be reproduced  

---

## Motivation

Paper 3 (vt-trend-following) body_v2.tex Table 6 (`tab:mdd_bootstrap`) reports:
- SPY: point=93%, 90% CI=[86, 97]
- 50/50: 96%, CI=[90, 99]
- DIA: 91%, CI=[83, 96]
- QQQ: 90%, CI=[82, 95]
- IWM: 97%, CI=[91, 100]

K898 (the prior bootstrap experiment) reports SPY CI=[95, 172] — completely different.
The nosource_rescan_report.md identified this as a BLOCKER: "STILL_NO_SOURCE."

This experiment provides formal forensic investigation with monthly rebalancing (paper spec) and 4 alternative CI definitions to identify which interpretation matches the paper.

---

## Methodology

- **VT rule**: `w_t = min(12/VIX_{month_end_t}, 1)`, monthly rebalancing, lagged 1 month
  - *Key difference from K898*: K898 used daily VIX signal; paper specifies monthly rebalancing
- **TSMOM hedge**: rolling 252-day regression, beta constrained [0, 0.5], lagged 1 day
- **Bootstrap**: block bootstrap, B=10,000, block_size=252, seed=42
- **CI**: 90% percentile (5th and 95th percentile of bootstrap distribution)
- **Period**: 2005-01-03 to 2026-03-31
- **Assets**: SPY, 50/50 SPY/GLD, DIA, QQQ, IWM
- **Cash proxy**: SHY

### 4 CI Definitions Tested

- **(a)** Retention fraction (paper's Eq. mdd_retention_boot):  
  `(MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100`
  
- **(b)** VT MDD reduction vs BH:  
  `(MDD_VT - MDD_BH) / abs(MDD_BH) * 100`
  
- **(c)** Absolute MDD of hedged VT:  
  `MDD_Hedged * 100`
  
- **(d)** Hedged VT improvement vs BH:  
  `(MDD_BH - MDD_Hedged) / abs(MDD_BH) * 100`

---

## Results

### Point Estimates

| Asset | BH MDD | VT MDD | Hedged MDD | Retention(a) |
|-------|--------|--------|------------|-------------|
| SPY   | -55.2% | -26.3% | -25.3%     | 103.7%      |
| 50/50 | -32.5% | -16.8% | -17.5%     | 95.6%       |
| DIA   | -51.9% | -26.8% | -25.2%     | 106.2%      |
| QQQ   | -53.4% | -28.5% | -26.2%     | 109.0%      |
| IWM   | -58.6% | -31.0% | -30.3%     | 102.2%      |

Point estimates for 4 of 5 assets exceed 100% (hedgedVT MDD is BETTER than VT MDD).

### 90% CI Results — Definition (a): Paper Formula

| Asset | Paper CI | K1192 CI(a) | Diff lo | Diff hi | Match? |
|-------|----------|------------|---------|---------|--------|
| SPY   | [86, 97] | [93, 182]  | +7      | +85     | NO     |
| 50/50 | [90, 99] | [76, 190]  | -14     | +91     | NO     |
| DIA   | [83, 96] | [82, 154]  | -1      | +58     | NO(lo ok) |
| QQQ   | [82, 95] | [89, 210]  | +7      | +115    | NO     |
| IWM   | [91,100] | [87, 184]  | -4      | +84     | NO     |

None of the 4 definitions match paper. Match count: 0/5 on any definition.

---

## Key Finding: Structural Divergence

**Root cause**: In our implementation, hedgedVT MDD is systematically BETTER than VT MDD (retention > 100%), causing right-skewed bootstrap distributions with very wide upper CI bounds. The paper's values (point 90-97%, CI [82-100]) imply hedgedVT MDD is slightly WORSE than VT MDD.

Possible explanations:
1. **Paper uses orthogonalized TSMOM** (paper-perp, not raw TSMOM) in the hedge construction — changes the hedge direction/magnitude
2. **Paper clips retention at 100%** before taking percentiles — would narrow upper CI
3. **Paper uses full-sample OLS beta** (not rolling) for hedge — different beta regime path
4. **Paper's TSMOM computation differs** (e.g., different signal scaling or cash allocation)

The divergence is systematic (affects all 5 assets consistently) not random.

---

## Recommendations

### (a) Paper Errata — HIGH PRIORITY

Table 6 cannot be reproduced with the methodology stated in the paper:
- The stated formula (Eq. mdd_retention_boot) with monthly rebalancing gives CI [93, 182] for SPY, not [86, 97]
- All 5 assets diverge systematically

**Before journal submission** (JPM/FAJ), the paper must either:
1. Provide/document the exact code generating Table 6, or
2. Update Table 6 with K1192 canonical results (definition a, monthly rebalancing), or
3. Clarify whether retention was clipped or computed with orthogonalized TSMOM hedge

### (b) K1192 as Canonical Replacement

K1192 definition (a) with monthly rebalancing is methodologically sound per the paper's stated formula. The canonical results (retention > 100% for most assets, wide upper CI) actually support a STRONGER claim: hedgedVT does not meaningfully worsen MDD vs VT, and sometimes improves it.

**Revised paper claim**: "MDD retention is at least 76% (50/50 5th pct CI), with most assets showing retention exceeding 100%, confirming that TSMOM hedging does not destroy VT's drawdown protection."

### (c) Additional Investigation Needed

To resolve the forensic question, need:
- Original code that generated paper Table 6 (if available in older experiment branches)
- Test with orthogonalized TSMOM in the hedge (vs current raw TSMOM)
- Test with full-sample beta (vs rolling beta)

---

## Files

- `k1192.py` — Main experiment script
- `k1192_results.json` — Full bootstrap results, 4 definitions, all 5 assets
- `k1192_vs_paper3_table6_diff.md` — Detailed diff report with forensic analysis
- `run.log` — Execution log

---

## Experimental Setup

- **Data source**: yfinance
- **Period**: 2005-01-03 to 2026-03-31 (paper period)
- **Seed**: 42
- **Bootstrap reps**: 10,000
- **Block size**: 252 days (1 year)
- **CI level**: 90%
- **Lookahead bias**: None (VT uses prior month-end VIX; TSMOM uses prior 252-day cum return shifted 1 day; hedge beta lagged 1 day)
