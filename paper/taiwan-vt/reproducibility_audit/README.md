# Paper 2 Reproducibility Audit Summary

**Paper**: Volatility Targeting in the Taiwan Stock Market (taiwan-vt)  
**Target Journal**: Pacific-Basin Finance Journal  
**Audit Date**: 2026-04-17  
**Auditor**: Claude Sonnet 4.6 (worktree agent-a6be0705)

---

## Audit Score

| Metric | Value |
|---|---|
| Numbers extracted from paper | 82 |
| Has any experiment source | 40 (49%) |
| Confirmed matched (✓ or ≈) | 14 (17% overall, 35% of sourced) |
| Divergent (✗) | 18 |
| No source found (?) | 42 (51%) |

**Overall coverage: 49%** (below the 80% threshold required)  
**Submission readiness: NEEDS-FIX (2 BLOCKERs)**

---

## Top 5 Divergences

| # | Issue | Severity | Section | Recommendation |
|---|---|---|---|---|
| 1 | Table 3 VT performance: paper 2010–2026, K900 covers 2019–2026 only — Sharpe/MDD completely different | BLOCKER | Sec 4, Table 3 | (a) Run new experiment for 2010–2026; or (b) update table to K900 period |
| 2 | Table 4 TZ momentum: entire Third contribution has no backing JSON | BLOCKER | Sec 5, Table 4 | (a) Create/run TZ momentum experiment, save as K experiment JSON |
| 3 | 0050.TW gamma=0.087 not reproduced (K892 gives 0.097 full-sample; 0.136 rolling) | MAJOR | Table 1, Table 2 | (a) Reconcile estimation period/config; or (b) update to 0.097 |
| 4 | VaR "8 violations (0.5%) Student-t" — K896 shows Student-t=18 violations (1.03%), CF=9 (0.51%) | MAJOR | Sec 7, Table 3 | (a) Correct distribution label or re-run restricted to 2020–2026 |
| 5 | 0050.TW stated 4,532 days — actual K892/K900 show 4,217 days (315 day discrepancy) | MAJOR | Sec 2, data | (b) Correct stated trading day count |

---

## Verified Results (Safe to Publish)

- SSVS: SPY_ret_L1 PIP = 1.000 (K461 confirmed)
- Conditional leverage Sharpe diff = +0.162 (K558 confirmed)
- Conditional leverage Harvey t = 4.79 (K558 confirmed)
- Normal VaR violations = 30 (K896 confirmed)
- TWII gamma ≈ 0.272 (K892 rolling last = 0.261, within ~4%)
- SPY gamma ≈ 0.211 (K892 rolling mean = 0.214)
- Figure 3 (overnight gap vs VIX) — K847 provides structural support (SPY correlation 0.399)

---

## Missing Experiment Sources

The following paper sections have **zero backing JSON**:

1. **All of Table 4** (Section 5 TZ strategy) — c2c/o2o Sharpe, 6-market t-stats, combinations
2. **Section 5** overnight gap conditional means (10.73bp, -8.91bp), bootstrap CI
3. **Section 6** (macro indicators) — import growth, BCI, ex-dividend effects
4. **Section 8** TSMC decomposition, VIX+Leading combo DM test, skewed-t parameters
5. **All 3 figure generation scripts** missing

---

## Files

- `main_tex_numbers.csv` — complete extraction of all 82 paper numbers with source mapping
- `script_output.json` — experiment JSON summaries and key statistics
- `diff_report.md` — detailed divergence analysis with recommendations
- `README.md` — this file

---

## Action Items Before Submission

**Blockers (must fix)**:
1. Create TZ momentum experiment covering 2012–2025 for 6 markets → new K experiment
2. Create/update VT performance experiment covering 2010–2026 → update K900 or add period

**Major (should fix)**:
3. Reconcile 0050.TW gamma (0.087 vs 0.097–0.136 from K892)
4. Fix VaR violation count attribution (Student-t vs CF)
5. Correct stated trading day counts (4,532 → 4,217 for 0050.TW)

**Medium (fix before R1 response)**:
6. Add macro indicator experiments (Section 6)
7. Add TSMC decomposition experiment
8. Create figure generation scripts citing K experiments
9. Fix 0050.TW skewness sign in Table 1 (−0.47 vs +0.47)
