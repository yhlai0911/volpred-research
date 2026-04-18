# Paper 9: Reproducibility Audit Summary

**Paper**: Multiplicative GARCH-X with VIX: A Parsimonious Alternative to GARCH-MIDAS  
**Target Journals**: Journal of Empirical Finance / International Journal of Forecasting  
**Status**: Submitted (under review) as of 2026-04-17  
**Audit Date**: 2026-04-17  
**Auditor**: Claude Sonnet 4.6 (worktree agent-adb9418c, independent run)

---

## Submission-Readiness Verdict: **NEEDS-FIX**

Not a blocker for the *science*, but the replication package has gaps that a reviewer or editor demanding code/data could expose.

---

## Scorecard

| Metric | Value |
|--------|-------|
| Total tex numbers extracted | 155 |
| Matched (✓) | 86 (55.5%) |
| Approx (≈, within tolerance but noted) | 8 (5.2%) |
| Divergent (✗) | 7 (4.5%) |
| No-source (?) | 54 (34.8%) |
| **Sourced coverage** | **65.2%** |
| **Match rate (of sourced)** | **85.1%** |
| Reproducibility score | ~85% (matched+approx / sourced) |

---

## Core Results — SOLID

The central horse-race (Table 3: 17 models × QLIKE + DM t) is **fully reproducible** from `compute_mcs_dm.py` → `mcs_dm_results.json`. All 33 QLIKE values and DM statistics match to ≥3 decimal places. The VaR/ES backtesting (Tables 8–9, 30+ cells) and VRP correlation table (Table 10) are also fully sourced and verified.

---

## TOP 5 Most Critical Divergent Issues

### 1. FEZ DM t=3.45 — NO SOURCE (HIGH RISK)
**Location**: Table 6, Abstract, Conclusion  
**Paper claims**: FEZ: DM t=3.45 (Harvey significant)  
**Script output**: No experiment produces this. K949 FEZ uses different spec (MF-GJR log-exp) and period (2016-2025); produces t=3.84. K994 does not include FEZ.  
**Recommendation**: (c) → (a): Mark as "errata pending" and immediately run dedicated A4f on FEZ with OOS 2019-2026 to verify/correct.

### 2. STOXX50E DM t=3.64 — OOS PERIOD MISMATCH (HIGH RISK)  
**Location**: Table 6, Abstract  
**Paper claims**: EURO STOXX 50: DM t=3.64 (Harvey significant)  
**Script output**: K949 FEZ t=3.84 (but OOS 2016-2025, not 2019-2026; uses log-exp not A4f)  
**Recommendation**: (a) Run A4f on STOXX50E^1 or FEZ with exact OOS 2019-2026 period to get verifiable t-stat.

### 3. Table 11 Residual Diagnostics — ENTIRE TABLE NO-SOURCE (HIGH RISK)
**Location**: Table 11  
**Paper claims**: kurtosis 3.065→1.238 (−59.6%), skewness −0.856→−0.594 (−30.6%), JB 938.8→224.2 (−76.1%)  
**Script output**: No JSON contains these values. Only ν (degrees of freedom) is from K995.  
**Recommendation**: (a) Extend K995.py to compute and save residual diagnostics to k995_results.json. Critical for reviewer replication.

### 4. Sensitivity Table (Table 12) — NO DEDICATED SOURCE (MEDIUM RISK)
**Location**: Table 12  
**Paper claims**: 16 DM t-statistics across 4 design dimensions  
**Script output**: No sensitivity results JSON found anywhere.  
**Recommendation**: (a) Create experiments/k988_sensitivity/ with k988_sensitivity.py that sweeps refit_freq, window, and VIX variants; save results JSON.

### 5. 0050.TW DM t=1.44 — MISMATCH (MEDIUM RISK)
**Location**: Table 6  
**Paper claims**: 0050.TW DM t=1.44 (No Harvey sig.)  
**Script output**: K997 dm_t=−1.677 (not significant, direction correct); K1098 dm_t=2.68 (neither matches)  
**Recommendation**: (a) Identify canonical 0050.TW experiment settings matching paper; update either K998/K1098 or tex to be consistent.

---

## Secondary Issues (Lower Priority)

| Issue | Location | Recommendation |
|-------|----------|----------------|
| n=1,828 vs n=1,825 | Table 11 footnote | (b) Update tex footnote |
| Sensitivity baseline 3.92 vs main 4.03 | Tables 3/12 | (c) Add footnote clarifying methodology |
| GLD result attribution (K997 vs K1085) | results/README.md | (b) Update README attribution |
| VIX macro comparison DM t=4.77 | Section 5.3 | (a) Add source JSON |
| 7 two-year windows pooled t=6.535 | Section 4.3 | (a) Add source JSON |

---

## One-Click Reproducibility Assessment

**Currently reproducible**:
- All of Table 3 (17-model QLIKE + DM rankings)
- All of Table 4 (pairwise DM matrix)
- All of Table 5 (MCS results)
- All of Table 7 (local fear index)
- All of Tables 8–9 (VaR/ES backtesting)
- All of Table 10 (VRP correlations)
- Most of Table 6 (cross-asset, except FEZ/STOXX50E)

**NOT currently reproducible from clean clone**:
- Table 11 (residual diagnostics — no script saves these)
- Table 12 (sensitivity — no sensitivity results JSON)
- FEZ/STOXX50E rows of Table 6
- VIX vs macro comparison (Section 5.3)
- Seven two-year windows sub-period analysis (Section 4.3)

---

## Fix Priority Order (for journal replication package)

| Priority | Fix | Effort |
|----------|-----|--------|
| P1 | Extend K995.py to save residual diagnostics JSON | 1 hour |
| P2 | Create K988_sensitivity.py with full Table 12 | 3 hours |
| P3 | Dedicated A4f on FEZ/STOXX50E OOS 2019-2026 | 2 hours |
| P4 | Resolve 0050.TW t=1.44 vs K997/K1098 discrepancy | 1 hour |
| P5 | Add macro comparison and 7-window results to JSON | 2 hours |

Total estimated fix effort: ~9 hours of scripting.

---

## Audit Files

| File | Contents |
|------|----------|
| `main_tex_numbers.csv` | 155 extracted numbers with source mapping and status |
| `script_output.json` | Key outputs from all 10 experiments mapped to paper sections |
| `diff_report.md` | Detailed analysis of all divergent and no-source cases |
| `README.md` | This file: submission-readiness assessment |

---

## Methodological Patterns for Paper 2–7 Audits

Based on this audit, the following patterns are recommended for future paper audits:

1. **DM t dual-computation risk**: When a paper uses both experiment-level scripts (kXXX.py) and a dedicated MCS/DM script (compute_mcs_dm.py), the two may give slightly different t-statistics due to different DM implementations. Always identify which is canonical and cited in the paper.

2. **OOS period sensitivity**: Cross-asset results are particularly sensitive to OOS period boundaries. Always verify that the experiment OOS period matches the paper's stated OOS period exactly.

3. **Residual diagnostics are often untracked**: Papers frequently include residual diagnostic tables (kurtosis, skewness, JB tests) that are computed inline in scripts without being saved to results JSONs. These should be explicitly added to results JSONs.

4. **Sensitivity table sourcing**: Sensitivity/robustness tables are often computed from standalone runs that don't save results JSONs. These should be created as dedicated experiments.

5. **Cross-asset source attribution**: When a paper draws cross-asset results from multiple experiments with different OOS periods and specifications, the results/README.md table should explicitly note which experiment and OOS period corresponds to each row.

---

*Audit performed in isolated worktree agent-adb9418c. No tex files, experiment JSONs, or shared state were modified.*
