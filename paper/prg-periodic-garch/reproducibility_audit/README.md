# Paper 6 Reproducibility Audit

**Paper**: Periodic Realized GARCH — Session-Boundary Information Transfers  
**Target journal**: Finance Research Letters (FRL)  
**Audit date**: 2026-04-17  
**Audit agent**: reproducibility-audit-agent (worktree agent-ad1a8110)  

---

## Audit Score

| Metric | Value |
|---|---|
| Numbers extracted | 85 |
| Matched (rtol ≤ 0.01) | 56 (66%) |
| Matched (source-correct) | ~66 if K880 validated |
| Divergent | 10 |
| Unknown/partial | 9 |
| **Coverage** | **90%** |
| **Readiness** | **NEEDS-FIX (Conditional)** |

---

## Source K Mapping

| Table/Section | Primary K | Secondary K |
|---|---|---|
| Table 1 (data summary) | K874d (TAIFEX), K880v2 (SPY), K881 (QQQ/GLD/EEM), K886 (0050.TW) | — |
| Table 2 (main results) | K880 ORIGINAL (SPY), K881, K874d, K886 | K883 (TAIFEX tick) |
| Table 3 (ablation) | K880 (full PRG), K880v2 (ablated version) | K880b (ES) |
| Table 4 (VaR/ES) | K880v2 (SPY VaR), K880b (ES), K874d (TAIFEX VaR) | K881 (multi-asset VaR) |
| Table 5 (economic) | K874e (VT strategy TAIFEX) | — |

---

## Top 5 Divergences with Recommendations

### 1. DIV-1: SPY Lookahead Source Confusion (BLOCKER)

**Paper uses K880 (labeled as having lookahead bug) for all SPY results. K880v2 (bug-fixed) is presented as the "Ablation" model.**

- Paper: SPY QLIKE=0.748, DM=6.00 → K880 matches exactly
- K880v2 gives QLIKE=0.8636, DM=-0.57 (no advantage vs GJR)
- K880v2's own metadata: `verdict: "COLLAPSED_ARTIFACT"`

**The key question**: Is using `r2_overnight[t]` (same-day overnight squared return) in `h_intraday[t]` truly lookahead? For sequential sessions (overnight closes before intraday opens), the overnight return IS available as conditioning information. For OHLC markets, `Open_d` is known before `Close_d`, so `r_overnight = log(Open_d / Close_{d-1})` is predetermined at intraday start. If this logic holds, K880 is correct and K880v2 over-removed valid conditioning.

**Action**: Verify session ordering explicitly in K880v2 script. If overnight return is genuinely predetermined at intraday start → use K880 and document; if not → major revision required.

### 2. DIV-2: 0050.TW OOS Date Mismatch (MAJOR)

Paper states 2019/12 OOS start; K886 JSON shows 2021-01-08 (~13 months later). n_oos=1,266 matches.

**Action**: Check K886 script for 70/30 split cutoff vs paper claim. Update Table 1 start date to 2021/01 or fix script.

### 3. DIV-3: SPY VaR Violation Rate 0.93% vs 1.59% (MAJOR)

Paper: VR=0.93%, Kupiec p=0.77. K880v2: VR=1.59%, Kupiec p=0.0196.

**Action**: Check K880 (original) VaR results. If lookahead version gives 0.93%/p=0.77, the VaR table also needs source clarification under DIV-1 resolution.

### 4. DIV-6: TAIFEX PRG vs Separate DM = -4.07 — no source found

Paper Table 2: TAIFEX DM PRG vs Sep = -4.07. K874d lacks Separate GARCH. K883 gives -3.30.

**Action**: Identify the experiment that computed this value. Check K874c or K874e TAIFEX. If unverifiable, must re-run or drop this comparison.

### 5. DIV-7: TAIFEX Spearman ρ = 0.726 — no source found

Paper Table 2: TAIFEX Spearman=0.726. K874d PRG_Ext=0.537, K883 not extracted. No source gives 0.726.

**Action**: Extract K883 PRG_Extended spearman_fullday. If not 0.726, identify which variant was used and re-run if needed.

---

## PRS 2024 APFM Paper Consistency Assessment

The PRG paper references Lai et al. (2024) [PRS paper] as the direct predecessor. Consistency checks:

1. **Session decomposition methodology**: Consistent. Both papers use the same `r_{d,0} = log(Open_d/Close_{d-1})` and `r_{d,1} = log(Close_d/Open_d)` definitions. The PRG simplifies by replacing Markov switching with deterministic session index.

2. **TAIFEX dataset**: Both use TAIFEX TX tick data. PRG uses 2017–2025 (8 years), extending the PRS sample. Consistent with PRS framing that motivated the paper.

3. **Harvey/Patton standards**: Consistent. Both use QLIKE with Patton's robust proxy argument and Harvey (2016) |t|>3 threshold.

4. **Session-boundary information transfer**: PRG makes an explicit claim that advances beyond PRS — PRS uses Markov switching to detect regime; PRG uses deterministic periodicity. The ablation study directly tests whether the cross-session bridge (PRG's claimed mechanism vs PRS's) adds value. If DIV-1 resolves favorably (K880 correct), the PRS→PRG progression is methodologically coherent.

5. **Potential tension**: PRS 2024 APFM covers regime-switching; PRG claims Markov switching introduces "estimation complexity." Both papers use same data source/period but different specifications. No numerical contradiction found between papers.

**Overall consistency**: CONSISTENT if DIV-1 is resolved. The PRG is a genuine methodological simplification of PRS that shares the same empirical motivation.

---

## Readiness

**NEEDS-FIX (Conditional)**

The paper is reproducible for K881, K874d, K874e, K880b, K886 with high fidelity. The blocker is DIV-1 (SPY lookahead status). If sequential session conditioning is validated:
- Fix Table 1 (DIV-2)
- Fix Table 4 VaR numbers (DIV-3)
- Source TAIFEX Separate DM and Spearman (DIV-6, DIV-7)
- Add one footnote clarifying K880 vs K880v2 distinction

If K880v2 is correct (lookahead bug real):
- All SPY results require revision
- Ablation study loses its central narrative
- Paper requires major methodological revision

**Figure scripts**: No standalone figure scripts exist in the paper directory. Figures must be regenerated from full experiment scripts. This is a minor completeness gap but not a blocking issue.

---

## Files

- `main_tex_numbers.csv`: 85 numbers extracted with source mapping and status
- `script_output.json`: Key values from all source K experiments
- `diff_report.md`: Detailed divergence analysis with (a)/(b)/(c) recommendations
- `README.md`: This file
