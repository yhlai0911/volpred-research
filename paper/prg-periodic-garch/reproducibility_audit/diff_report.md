# Paper 6 (prg-periodic-garch) Reproducibility Diff Report

**Audit date**: 2026-04-17  
**Auditor**: reproducibility-audit-agent (worktree agent-ad1a8110)  
**main.tex**: NOT modified  

---

## Summary

| Category | Count |
|---|---|
| Total paper numbers extracted | 85 |
| Matched (rtol ≤ 0.01) | 56 |
| Divergent | 10 |
| Unknown/partial | 9 |
| **Coverage** | **90%** |

---

## CRITICAL DIVERGENCES (Blocker-level)

### DIV-1: LOOKAHEAD SOURCE CONFUSION — SPY K880 vs K880v2

**Severity**: BLOCKER  
**Location**: Abstract, Table 2, Table 3 (Ablation)

The paper reports SPY results (QLIKE=0.748, DM=6.00) that match **K880 (original)**, which K880v2 explicitly labels as having a lookahead bug:

```
k880_vs_k880v2: {
  "k880_prg_ext_qlike": 0.748,
  "k880v2_prg_ext_qlike": 0.8636,
  "k880_dm_prg_vs_gjr": 6.0,
  "k880v2_dm_prg_vs_gjr": -0.57,
  "verdict": "COLLAPSED_ARTIFACT"
}
```

The fix in K880v2 (`bug1_lookahead: h_intraday now uses h_overnight FORECAST instead of realized r2_overnight[t]`) eliminates all SPY advantage. The paper's Table 2 SPY column uses K880. The paper's Table 3 "Ablation" treats K880v2 (the fixed version) as the "PRG-Ablated" model.

**Implication**: What the paper calls "session-boundary information transfer" for SPY is actually the **lookahead gain** from using the realized overnight return (same-day, within-session) rather than the prior-day forecast. The ablation study correctly identifies that removing this input collapses the advantage — but this is because it was lookahead, not because of a "genuine information bridge."

**(a)** Verify whether overnight return is truly predetermined when the intraday session opens (TAIFEX: yes, sequentially ordered; OHLC markets: the "opening price" is available before intraday close, so $r_{d,0}$ is realized before $r_{d,1}$ begins — this is NOT lookahead for same-day sequential sessions).

**(b)** The economic interpretation hinges on whether the session timing is truly sequential. For OHLC data, `r_overnight = log(Open_d / Close_{d-1})` is known at market open, before intraday return is realized. This is valid conditioning information. The K880v2 bug fix may have incorrectly applied lookahead logic designed for non-sequential contexts.

**(c)** **Required action**: Re-examine K880v2 `bug1_lookahead` logic against the PRG model specification (Eq. 3-4 in main.tex). If opening price is genuinely known at intraday start, then K880 is correct and K880v2 is over-corrected. Paper should state this explicitly.

---

### DIV-2: 0050.TW OOS START DATE MISMATCH

**Severity**: MAJOR  
**Location**: Table 1 (tab:data)

| | Paper | K886 JSON |
|---|---|---|
| OOS period | 2019/12--2026/04 | 2021-01-08 to 2026-04-02 |
| n_oos | 1,266 | 1,266 |

The observation count matches but the stated start date differs by ~13 months. The Spearman n in K886 is 1,251 (vs stated n_oos 1,266), adding internal inconsistency.

**(a)** Check whether the paper's "2019/12" refers to in-sample end / OOS start, and whether K886 script has a different 70/30 split cutoff.

**(b)** Verify K886 script OOS period definition and reconcile with the 0050.TW stock split cleaning (2014 split noted in data section).

**(c)** Update Table 1 OOS period for 0050.TW to match K886 actuals (2021/01--2026/04), or fix K886 split ratio.

---

### DIV-3: SPY VaR 1% VIOLATION RATE AND KUPIEC p

**Severity**: MAJOR  
**Location**: Table 4 (tab:var_es)

| Metric | Paper | K880v2 JSON |
|---|---|---|
| PRG Ext VR% | 0.93% | 1.59% (29/1823) |
| PRG Ext Kupiec p | 0.77 | 0.0196 |
| GJR VR% | 1.92% | 2.08% (38/1823) |

The paper claims PRG Extended has 0.93% violation rate with Kupiec p=0.77 (clean pass). K880v2 gives 1.59% with Kupiec p=0.0196 (borderline fail). The violation rate matches neither K880 nor K880v2 cleanly. This may trace back to the lookahead issue: K880 (lookahead) would produce tighter VaR estimates.

**(a)** Check K880 (original) layer4_var for PRG_Extended VaR_1pct violation rate.

**(b)** If K880 gives 0.93%/Kupiec=0.77, then VaR results are also sourced from the lookahead version.

**(c)** Either use K880v2 VaR results (update table) or resolve the K880/K880v2 source question per DIV-1.

---

## MODERATE DIVERGENCES

### DIV-4: GLD Best QLIKE 0.811 vs 0.820

**Severity**: MODERATE  
**Location**: Table 2

Paper reports 0.811 for GLD best QLIKE (notes "PRG Basic for GLD"). K881 gives PRG_Extended QLIKE=0.8204. K881 PRG_Basic needs separate check; may be the 0.811 source since paper says PRG Basic wins for GLD.

**(a)** Extract K881 GLD PRG_Basic QLIKE explicitly.

**(b)** If paper correctly reports PRG Basic as best for GLD, update Table 2 header note to clarify which model is in the QLIKE column per row.

---

### DIV-5: TAIFEX QLIKE TABLE 2 vs K883/K874d

**Severity**: MODERATE  
**Location**: Table 2

Paper reports TAIFEX best QLIKE=0.198. K874d PRG_Extended QLIKE=0.1979 (match). But K883 (true tick-level with separate session PRG) gets QLIKE=0.121. These use different common targets: K874d target includes night session (3-component), K883 uses simpler decomposition.

**(a)** Confirm which experiment is the authoritative TAIFEX source. K874d matches 0.198 so it is used for Table 2.

**(b)** Document that K883 and K874d use different target definitions; reconcile or add footnote.

---

### DIV-6: TAIFEX DM PRG vs Separate = -4.07

**Severity**: MODERATE  
**Location**: Table 2

Paper reports TAIFEX PRG vs Sep DM = -4.07. This value not found in K874d (which does not test Separate GARCH). K883 gives PRG_Extended vs Separate = -3.303. No source gives -4.07.

**(a)** Identify which experiment computes TAIFEX PRG vs Separate DM.

**(b)** Check K874c or K874e for TAIFEX Separate GARCH comparison.

**(c)** If no source, flag as unverified.

---

### DIV-7: TAIFEX Spearman rho = 0.726

**Severity**: MODERATE  
**Location**: Table 2

Paper reports TAIFEX Spearman ρ=0.726. K874d PRG_Ext spearman=0.537 (GJR); K883 PRG_Extended spearman_fullday not readily extracted in audit. K874d HAR(RV_total) spearman=0.650. No source found for 0.726.

**(a)** Check K883 PRG_Extended spearman_fullday explicitly.

**(b)** If 0.726 cannot be sourced, flag as unverified.

---

### DIV-8: TAIFEX DM PRG vs HAR = 2.63

**Severity**: MODERATE  
**Location**: Table 2

Paper reports 2.63. K884 (HAR Day/Night TAIFEX) gives HAR_Standard vs PRG_Extended t=2.305. K874d does not compute this comparison directly.

**(a)** Verify which experiment gives 2.63 for TAIFEX PRG vs HAR.

**(b)** Check sign convention: paper says "positive favors PRG", t=2.63 with positive sign means PRG wins over HAR.

---

## MINOR NOTES

### NOTE-1: TAIFEX MCS "PRG only" at 10% level

Paper claims TAIFEX MCS: "PRG only" with GJR p=0.000, HAR p=0.000 eliminated. No MCS data found in K874d or K883 for TAIFEX. K883 does not report MCS. This result is unverified.

### NOTE-2: 64% Sharpe improvement claim

Paper: "64% improvement in risk-adjusted returns alongside a 64% reduction in tail risk." Computation: (1.66-1.01)/1.01 = 64.4%, (31.7-11.5)/31.7 = 63.7%. Both check out approximately from K874e numbers.

### NOTE-3: Figure scripts

No figure-generating scripts found in `paper/prg-periodic-garch/experiments/` for any of the four named K experiments (K880v2, K881, K874d). Charts exist at `k880v2_charts/`, `k881_charts/`, `k883_charts/`, `k874d_charts/` in `experiments/` root, but no standalone figure reproduction script exists in the paper directory. The `reproduce.py` dispatches to the full experiment scripts which regenerate results.

### NOTE-4: Internal cross-section consistency (same symbol)

- DM PRG vs GJR for SPY: Abstract says range "4.26 to 6.63", Section 4 confirms DM(SPY)=6.00, Table 2 shows 6.00. Consistent within paper.
- DM PRG vs Sep for TAIFEX: Abstract does not mention, Table 2 shows -4.07. No cross-section inconsistency beyond DIV-6.
- PRG Extended Sharpe for PRG Ext: Section 4.4 says "Sharpe ratio of 1.66", Table 5 shows 1.66. Consistent.

### NOTE-5: Ablation conceptual framing

The ablation framing (Section 4.2) is statistically clean IF the lookahead question (DIV-1) resolves in favor of K880. If K880v2 is the correct bug-free version, then the paper's entire SPY empirical result collapses and the ablation table becomes a trivial comparison between a correct model (K880v2) and an incorrect one (K880).

---

## Internal Cross-Section Check

| Symbol | Abstract DM | Table 2 DM | JSON DM |
|---|---|---|---|
| SPY vs GJR | 6.00 | 6.00 | K880: 6.004 ✓ |
| QQQ vs GJR | 4.26 | 4.26 | K881: 4.257 ✓ |
| EEM vs GJR | 6.63 | 6.63 | K881: 6.629 ✓ |
| GLD vs GJR | 6.12 | 6.12 | K881: 6.118 ✓ |
| TAIFEX DM | 5.10 | 5.10 | K874d: 5.100 ✓ |

No cross-section discrepancy on these values. Mismatch is source version (K880 vs K880v2), not internal inconsistency.

---

## Readiness Assessment: **NEEDS-FIX (Conditional)**

The paper is reproducible from source K files for K881, K874d, K874e, K880b, K886. The critical question (DIV-1) requires methodological clarification before readiness can be confirmed. If sequential session conditioning is validated (opening price known before intraday close), K880 is correct and Paper 6 is READY after fixing DIV-2, DIV-3 (minor table updates) and sourcing DIV-6, DIV-7, DIV-8. If K880v2 is correct (lookahead truly present), paper requires major revision.
