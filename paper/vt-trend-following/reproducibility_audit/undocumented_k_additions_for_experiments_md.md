# Undocumented K — Additions for experiments.md

**Generated**: 2026-04-17  
**Agent**: nosource-rescan (worktree agent-ad65cd3d)  
**Source**: `nosource_rescan_report.md` rescan findings

These entries should be added to `paper/vt-trend-following/experiments.md` once that file is created (currently missing — see action item below).

---

## Priority 1: Create experiments.md

`paper/vt-trend-following/experiments.md` does not exist yet. It must be created to track all K experiments supporting the paper. The entries below should be the initial content plus entries for K55, K54, K898, K901, K518, K499, K568, K687, K688 already identified in `diff_report.md`.

---

## Entries to Add

### Entry 1 — paper3_fixes.json (VIX Threshold Sensitivity)

```
## paper3_fixes — VIX Threshold Sensitivity + Dual Mechanism Generalization

**File**: `paper/vt-trend-following/experiments/paper3_fixes.json`  
**Type**: Paper-folder experiment (no formal experiments/kXXX/ directory)  
**Proposed by**: Codex K77 + Gemini K76  
**Executed**: 2026-03-21  
**Assets**: SPY, QQQ, EEM, EFA, GLD  

### Contribution to Paper

**Fix 1 (main.tex Discussion, line 166)**: VIX threshold sensitivity for TSMOM loading.
Re-estimates Model 2 for SPY across VIX targets 8 to 20. TSMOM_t range: 7.98–10.91.
- VIX=8: TSMOM_t=10.9146 → paper claims 10.91 ✓
- VIX=10: TSMOM_t=10.9121
- VIX=12: TSMOM_t=10.8395
- VIX=15: TSMOM_t=10.395
- VIX=18: TSMOM_t=9.0009
- VIX=20: TSMOM_t=7.9791 → paper claims 7.98 ✓

**Fix 2 (Table 3 supplement)**: Dual mechanism cross-asset generalization.
MDD preservation: SPY=92.13%, QQQ=93.33%, EEM=90.28%, EFA=94.02%, GLD=96.56%
Note: This is a 5-asset robustness check with different asset set than Table 3 
(Table 3 uses SPY/50-50/DIA/QQQ/IWM from K898).

### Status
Confirmed source of main.tex Discussion threshold sensitivity claim.
NOT a source of Table 3 primary numbers (K898 is).
Paper3_fixes MDD preservation diverges from paper Table 3 (different assets).
```

---

### Entry 2 — K697 (VIX Predictive Power)

```
## K697 — VIX Predictive Power: Direction vs Magnitude

**Directory**: `experiments/k697/`  
**File**: `k697_results.json`  
**Title**: Is ANY Daily Alpha Possible? — Upper Bound Analysis  
**Data**: SPY daily returns + VIX, Yahoo Finance  

### Contribution to Paper

**review_v2 / Section 4.2 candidate** (currently CITED only in review_v2, NOT in main.tex body):

- `corr_vix_lag_absret = 0.5704` → paper claims r=0.570 (vol magnitude) ✓
- `corr_vix_lag_ret = 0.0417` → paper claims r=0.042 (direction) ✓

The finding (VIX strongly predicts next-day vol magnitude but not direction) directly supports 
the paper's Section 4.2 argument that VIX-based VT is a risk-scaling mechanism, not a 
directional signal.

### Status
CONFIRMED exact match. Should be cited in main.tex/body_v2.tex Section 4.2 mechanism discussion.
K697 is marked "Status: planning" in README.md but has a complete results JSON.
```

---

### Entry 3 — K687 (Reconciliation Required)

```
## K687 — Post-Correction Strategy Ranking (RECONCILIATION NEEDED)

**Directory**: `experiments/k687/`  
**File**: `k687_results.json`  
**Title**: Post-Correction Definitive Strategy Ranking  
**Data**: SPY + GLD, Yahoo Finance, full sample with lag correction  

### Relation to Paper

NOT a direct source of paper numbers. K687 evaluates VT applied to the 50/50 SPY/GLD blend 
as a whole (VT on blended portfolio), while Table 3 evaluates VT on each asset separately then 
blends (VT on individual assets). Different construction.

K687 results: BH 50/50 Sharpe=0.545 > EWMA VT Sharpe=0.525 > 12/VIX VT Sharpe=0.438  
Paper Table 3: 12/VIX VT Sharpe=0.982 > BH 50/50 Sharpe=0.865

This reconciliation gap must be acknowledged in paper body (Section 5 limitations or footnote):
"Our 50/50 results reflect VT applied per-asset (SPY VT + GLD VT), not VT applied to the 
pre-blended portfolio. The latter construction, while simpler, does not show Sharpe improvement."

### Status  
H5 reconciliation gap per review_v2. Paper does not reconcile K687 methodology difference.
```

---

### Entry 4 — K688 (Reconciliation Required)

```
## K688 — CRRA Utility with Properly Lagged Signals (RECONCILIATION NEEDED)

**Directory**: `experiments/k688/`  
**File**: `k688_results.json`  
**Title**: CRRA Utility with Properly Lagged Signals  
**Data**: SPY + GLD, Yahoo Finance  

### Relation to Paper

NOT a direct source of paper numbers. Verdict: "VT wins on utility only for moderately 
risk-averse (gamma >= 5)." EWMA VT wins at gamma>=5 for SPY+GLD blend.

The paper's Cederburg rebuttal (Section 4 / body_v2) claims VT provides value beyond alpha, 
appealing to drawdown protection. K688 uses CRRA utility on 50/50 blend (VT applied to blend) 
while paper's utility argument applies to VT per-asset. Same construction gap as K687.

K688 result that 12/VIX does NOT win at any gamma for the blend should be mentioned in the 
paper as a boundary condition: VT utility advantage requires per-asset application.

### Status
H5 reconciliation gap per review_v2. Not yet acknowledged in paper body.
```

---

### Entry 5 — K697 Additional (Autocorrelation results)

```
## K697 Additional — SPY Return Autocorrelation

**File**: `k697_results.json` (same as Entry 2 above)

Also contains SPY autocorrelation diagnostics:
- spy_acf_lag1 = −0.1047 (negative short-term autocorrelation)
- p_up_after_up = 0.5421 vs unconditional 0.5506 (minimal momentum edge)
- momentum_edge = −0.0085

These support the paper's claim that "VT's TSMOM loading does not reflect return momentum" 
(direction predictability near zero), consistent with r=0.042 for VIX direction prediction.
```

---

## Still-Missing Experiments (New K Numbers Needed)

The following experiments need to be created before submission:

| Proposed K | Content | Target Paper Section | Priority |
|---|---|---|---|
| K1179 (sector) | 11 SPDR ETFs (XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY/XLRE/XLC), Dec 1998–Mar 2026, GJR gamma vs TSMOM loading cross-sectional | Section 3.4, Online Appendix | HIGH |
| K1180 (sub-period) | 50/50 SPY/GLD across 4 sub-periods: pre-COVID (2005-2019), COVID (2020-2021), post-COVID (2022), OOS (2023-2026) | Section 3.6 body_v2.tex, Online Appendix | HIGH |
| K1181 (bootstrap MDD) | Block bootstrap for MDD retention (formula: (BH_MDD−Hedged_MDD)/(BH_MDD−VT_MDD)×100), 10,000 reps, block=252, 5 assets | body_v2.tex Table 6 | BLOCKER |
| K1182 (split-sample) | Split-sample K55: gamma from 2007-2016, TSMOM beta from 2017-2026 | body_v2.tex Section 3.3 | HIGH |

**Note on K1181**: K898's bootstrap uses `(hedged_MDD / VT_MDD × 100)` which yields >100% (K898 hedging improves MDD). Paper body_v2.tex Table 6 uses a different formula yielding 90-97%. The correct formula for the paper's Table 6 is `(BH_MDD − Hedged_MDD) / (BH_MDD − VT_MDD) × 100` where higher = more VT protection preserved after hedging. A new experiment using this correct formula is needed.

---

## Summary of experiments.md Entries Pending

| Entry | Type | Files Exist? | Action |
|-------|------|-------------|--------|
| paper3_fixes → VIX threshold sensitivity | UNDOCUMENTED_K (paper folder) | YES: paper3_fixes.json | Add to experiments.md |
| K697 → VIX predictive power | UNDOCUMENTED_K (experiments/) | YES: k697_results.json | Add to experiments.md; cite in body |
| K687 → strategy ranking reconciliation | RECONCILIATION | YES: k687_results.json | Add note + reconcile methodology gap in paper |
| K688 → CRRA utility reconciliation | RECONCILIATION | YES: k688_results.json | Add note + reconcile methodology gap in paper |
| K1179 (sector) | MISSING | NO | Create new experiment |
| K1180 (sub-period) | MISSING | NO | Create new experiment |
| K1181 (bootstrap MDD correct formula) | MISSING | NO | Create new experiment — BLOCKER for body_v2 |
| K1182 (split-sample) | MISSING | NO | Create new experiment |

---

*File is advisory only. No experiments, .tex files, or shared state were modified.*
