# K1192 vs Paper 3 Table 6 Diff Report

**Experiment**: K1192 — Paper 3 Table 6 Bootstrap MDD CI Formal Reproduce  
**Paper reference**: body_v2.tex, `\label{tab:mdd_bootstrap}`  
**Date**: 2026-04-17

---

## Paper Table 6 (Target)

| Asset | Point | 90% CI Lower | 90% CI Upper |
|-------|-------|-------------|-------------|
| SPY   | 93    | 86          | 97          |
| 50/50 | 96    | 90          | 99          |
| DIA   | 91    | 83          | 96          |
| QQQ   | 90    | 82          | 95          |
| IWM   | 97    | 91          | 100         |

---

## K1192 Results: 4-Definition Bootstrap CIs

**Formula (a) = Paper's stated formula** (Eq. mdd_retention_boot):  
`MDD Retention = (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100`

| Asset | Point(a) | CI(a) Lower | CI(a) Upper | Point paper | CI paper | Match? |
|-------|----------|------------|------------|-------------|----------|--------|
| SPY   | 103.7    | 93.0       | 182.3      | 93          | [86, 97] | NO     |
| 50/50 | 95.6     | 76.0       | 189.9      | 96          | [90, 99] | NO     |
| DIA   | 106.2    | 82.3       | 154.3      | 91          | [83, 96] | NO (lo match) |
| QQQ   | 109.0    | 89.0       | 210.0      | 90          | [82, 95] | NO     |
| IWM   | 102.2    | 87.4       | 184.2      | 97          | [91, 100] | NO    |

**Formula (b)**: `(MDD_VT - MDD_BH) / abs(MDD_BH) * 100` (VT MDD reduction %)

| Asset | CI(b) Lower | CI(b) Upper | Range matches [86,97]? |
|-------|------------|------------|------------------------|
| SPY   | 27.4       | 55.3       | NO — completely different scale |

**Formula (c)**: `MDD_Hedged * 100` (absolute MDD of hedged VT)

| Asset | CI(c) Lower | CI(c) Upper | Range matches [86,97]? |
|-------|------------|------------|------------------------|
| SPY   | -33.9      | -12.4      | NO — negative and different scale |

**Formula (d)**: `(MDD_BH - MDD_Hedged) / abs(MDD_BH) * 100` (hedged vs BH)

| Asset | CI(d) Lower | CI(d) Upper | Range matches [86,97]? |
|-------|------------|------------|------------------------|
| SPY   | -59.8      | -42.2      | NO — negative and different scale |

**Match summary**: 0/5 assets match on any of the 4 definitions (threshold: ±5pp on both bounds).

---

## Root Cause Analysis

### Why K898/K1192 (a) retention diverges from paper

**K898/K1192 produce point estimates 100-110% (hedgedVT MDD BETTER than VT).**  
**Paper Table 6 shows point estimates 90-97% (hedgedVT MDD WORSE than VT).**

This is a structural divergence, not a formula disagreement:

1. **Monthly vs daily rebalancing**: 
   - K898 uses daily VIX signal → smoother weight transitions → VT has more days at weight ~1.0, accumulating full drawdown
   - Paper uses monthly rebalancing → VT weight is constant within each month → slightly higher VT MDD
   - K1192 confirmed monthly rebalancing still gives point estimates >100%

2. **What does retention >100% mean**:
   - `(MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) = 103.7%`
   - Means: hedgedVT reduces MDD by MORE than VT alone (relative to BH)
   - This happens when the TSMOM hedge accidentally further reduces drawdown
   - Our TSMOM hedge beta ≈ 0.0-0.12, which slightly reduces hedged strategy MDD beyond VT

3. **Why paper gets 90-97% (hedgedVT slightly worse than VT)**:
   - Paper's hedgedVT likely has slightly higher MDD than VT
   - This implies paper's TSMOM hedge worsens MDD slightly (not improves it)
   - Could reflect different: (a) TSMOM lookback, (b) beta constraint, (c) how hedge is applied to portfolio (per-asset vs blend level)

4. **The bootstrap distribution problem**:
   - Our (a) distribution: mean ~127%, median ~115% — right-skewed, fat upper tail
   - Paper's distribution: mean ≈ 91-97%, narrow range [82-100]
   - The two distributions are structurally incompatible

### Possible explanations for the paper's [86, 97] range

**Hypothesis 1 (most likely)**: Paper computes MDD retention differently from the stated formula.  
The paper may compute: `MDD_Hedged / MDD_VT * 100` (ratio, not fraction of protection).  
- If VT MDD = -24.7%, Hedged MDD = -26.9% → ratio = 26.9/24.7 = 108.9% (too high)
- If VT MDD = -24.7%, Hedged MDD = -23.0% → ratio = 23.0/24.7 = 93% (matches!)

**Hypothesis 2**: Paper may compute MDD retention as `MDD_VT / MDD_BH * 100` (VT vs BH).
- SPY: -24.7% / -55.2% × 100 = 44.7% (too low, wrong scale)

**Hypothesis 3**: Paper uses a clipped version of retention, capping at 100%.
- If paper clips (a) at [0, 100]: mean ≈ 95%, CI lower ≈ 82%, CI upper ≈ 100% — plausible!
- With clipping, the paper's [86, 97] CI is consistent with our (a) distribution truncated at 100%

**Hypothesis 4 (most forensically sound)**: Paper's bootstrap produces retention < 100% consistently because the paper's actual TSMOM-hedged VT has higher MDD than VT (hedge worsens MDD). This may come from:
- Paper using orthogonalized TSMOM (paper-perp) in the hedge rather than raw TSMOM
- Paper using a different beta estimation (OLS without constraint, or full-sample vs rolling)
- The hedge adding back TSMOM factor returns that create momentum reversals, worsening MDD

---

## Verdict: Definition Match Status

| Definition | Description | Match [86,97]? | Notes |
|-----------|-------------|----------------|-------|
| (a) retention fraction | Paper's stated formula | DIVERGE | Upper bound 182 vs 97 |
| (b) VT MDD reduction % | Alternative | DIVERGE | Scale 27-55 vs 86-97 |
| (c) Hedged abs MDD | Alternative | DIVERGE | Negative values |
| (d) Hedged vs BH % | Alternative | DIVERGE | Negative values |

**Conclusion**: ALL 4 definitions DIVERGE. Paper Table 6 values [86, 97] CANNOT be reproduced from the stated methodology with either daily or monthly rebalancing using this implementation.

---

## Recommended Actions

### (a) Errata — Paper Table 6 Cannot Be Verified

The paper's Table 6 bootstrap values [86, 97] (and all 5 assets) cannot be reproduced with:
- The stated formula (Eq. mdd_retention_boot)
- Monthly rebalancing (paper spec)
- Daily rebalancing (K898)
- Any of the 4 alternative CI definitions

**Recommended action**: Paper should either:
1. Provide the exact code that generated Table 6, or
2. Replace Table 6 with K1192 canonical results (Definition a, monthly rebalancing), or  
3. Clarify whether retention is clipped at 100% in their bootstrap

### (b) If Clipping Hypothesis is Correct

If paper clips retention at [0, 100%]:
- SPY clipped CI: [86, 97] would match our 5th percentile ≈ 93 and a truncated 95th ≈ 97
  (Our 95th is 182, but clipped at 100 the effective 95th pct = 100... doesn't match [97])
- Still doesn't cleanly match — clipping hypothesis is partially supported but not complete

### (c) K1192 Canonical Results

For submission, K1192 definition (a) monthly rebalancing provides canonical results:

| Asset | Point | 90% CI (5th/95th) |
|-------|-------|-------------------|
| SPY   | 103.7 | [93.0, 182.3]     |
| 50/50 | 95.6  | [76.0, 189.9]     |
| DIA   | 106.2 | [82.3, 154.3]     |
| QQQ   | 109.0 | [89.0, 210.0]     |
| IWM   | 102.2 | [87.4, 184.2]     |

These results show retention generally ≥ 90% (all lower 90% CIs ≥ 76%), supporting the paper's claim that MDD retention is high — but with wider and higher CIs than stated in paper.

---

## K898 vs K1192 Key Difference

| Parameter | K898 | K1192 |
|-----------|------|-------|
| VT rebalancing | Daily VIX signal | Monthly VIX (month-end) |
| SPY BH MDD | -55.2% | -55.2% (same) |
| SPY VT MDD | -24.7% | -26.3% |
| SPY Hedged MDD | -22.5% | -25.3% |
| SPY point retention | 107% | 103.7% |
| SPY CI (a) | [95, 172] | [93, 182] |

Both implementations show retention > 100%, wider CI upper bounds than paper. The discrepancy is systematic.

---

*K1192 is diagnostic only. No paper .tex files were modified.*
