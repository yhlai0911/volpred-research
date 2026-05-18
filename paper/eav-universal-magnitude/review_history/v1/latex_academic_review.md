# LaTeX Academic Review — EAV Universal Magnitude
**Reviewer**: latex-academic-reviewer (main thread, Claude Sonnet 4.6)
**Date**: 2026-05-18
**Paper**: Earnings-Announcement Volatility Amplification: A Cross-Market Regularity with Magnitude Ordering — Taiwan, U.S., Japan
**Stage**: DRAFT (first formal review; §1–9 complete, reproduce 20/20 GREEN)
**Scope**: body.tex (965 lines), reproduce_report.json, experiments/k1145, k1147, k1150, k1109, k1113, k1148_d2, k1149

---

## 1. Claim–Evidence Numerical Audit (byte-traceable)

### 1.1 Table 1 (Main Results) — ALL VERIFIED

| Claim | JSON Source | Status |
|-------|------------|--------|
| TW θ̂ = 6.36×10⁻⁵ | k1145_results.json: main_fit_eav_window_1.theta_eav = 6.362165e-05 | MATCH |
| TW t_CB = 5.24 | k1145_results.json: cluster_bootstrap.t_stat = 5.242 | MATCH |
| TW 95% CI [4.13, 9.38]×10⁻⁵ | k1145_results.json: cluster_bootstrap.ci_95 | MATCH |
| TW placebo 13.3σ (exact 13.27) | (6.362e-5 − 1.356e-6) / 4.691e-6 = 13.273 | MATCH |
| US θ̂ = 1.91×10⁻⁴ | k1147_results.json: main_fit_eav_window_1.theta_eav = 1.909e-04 | MATCH |
| US t_CB = 4.50 | k1147_results.json: cluster_bootstrap.t_stat = 4.496 | MATCH |
| US 95% CI [1.29, 2.80]×10⁻⁴ | k1147_results.json: cluster_bootstrap.ci_95 | MATCH |
| US placebo 70.7σ | k1147_placebo_results.json: z_observed = 70.742 | MATCH |
| JP θ̂ = 1.41×10⁻⁴ | k1150_results.json: main_fit_eav_window_1.theta_eav = 1.413e-04 | MATCH |
| JP t_CB = 11.99 | k1150_results.json: cluster_bootstrap.t_stat = 11.989 | MATCH |
| JP 95% CI [1.29, 1.76]×10⁻⁴ | k1150_results.json: cluster_bootstrap.ci_95 | MATCH |
| JP placebo 38.6σ | k1150_placebo_results.json: z_observed = 38.648 | MATCH |

### 1.2 Window Robustness Numbers — ALL VERIFIED

| Claim | JSON | Status |
|-------|------|--------|
| TW w3: 3.80×10⁻⁵, t=14.25 | k1145: window_3.theta_eav=3.799e-5, t_hessian=14.247 | MATCH |
| TW w5: 1.73×10⁻⁵, t=10.12 | k1145: window_5.theta_eav=1.73e-5, t_hessian=10.117 | MATCH |
| US w3: 7.73×10⁻⁵, t=30.84 | k1147: window_3.theta_eav=7.733e-5, t_hessian=30.835 | MATCH |
| US w5: 8.29×10⁻⁵, t=32.11 | k1147: window_5.theta_eav=8.290e-5, t_hessian=32.108 | MATCH |
| JP w3: 1.10×10⁻⁴, t=30.60 | k1150: window_3.theta_eav=1.102e-4, t_hessian=30.597 | MATCH |
| JP w5: 8.12×10⁻⁵, t=33.15 | k1150: window_5.theta_eav=8.123e-5, t_hessian=33.150 | MATCH |

### 1.3 Factor Absorption (K1149) — ALL VERIFIED

| Claim | JSON | Status |
|-------|------|--------|
| US IS t=23.81 | k1149: h1_absorption.us.t_is = 23.812 | MATCH |
| TW IS t=10.62 | k1149: h1_absorption.tw.t_is = 10.619 | MATCH |
| US OOS DM = −3.31 | k1149: h1_absorption.us.oos_t = −3.311 | MATCH |
| TW OOS DM = −2.48 | k1149: h1_absorption.tw.oos_t = −2.482 | MATCH |
| US stress interaction t=5.04 | k1149: h3_interaction.us.t_stress = 5.038 | MATCH |
| TW stress interaction t=−0.39 | k1149: h3_interaction.tw.t_stress = −0.385 | MATCH |
| TW LRT p=0.010 | k1149: h3_interaction.tw.lrt_p = 0.01015 | MATCH |

### 1.4 K1113 / K1109 Heterogeneity Numbers — ALL VERIFIED

| Claim | JSON | Status |
|-------|------|--------|
| K1109 sector ANOVA F=1.31, p=0.297 | k1109: anova_sector_ftest.f_stat=1.309, p_value=0.297 | MATCH |
| BH min p=0.278 (fabless) | k1109: bh_adjusted_pvalues.sector_fabless=0.278 | MATCH |
| K1113 H1: BH min adj p=0.854, 0 survivors | k1113: hypothesis_verdict.H1_any_bh_survives.min_bh_adj=0.854 | MATCH |
| K1113 CV R²=−0.661 | k1113: primary_regression.cv.cv_r2 = −0.6611 | MATCH |
| K1113 Tier A = 0 firms | k1113: tier_classification_summary.A.n_firms = 0 | MATCH |

### 1.5 K1148_d2 OOS DM Numbers — ALL VERIFIED

| Claim | JSON | Status |
|-------|------|--------|
| US binary OOS DM t=−5.58 | k1148_d2: four_row_table[0].panel_DM_t_OOS = −5.580 | MATCH |
| US continuous OOS DM t=−5.25 | k1148_d2: four_row_table[1].panel_DM_t_OOS = −5.253 | MATCH |
| TW binary OOS t=−1.46 (NS, p=0.076) | k1148_d2: four_row_table[2].panel_DM_t_OOS = −1.462 | MATCH |

### 1.6 CRITICAL: Table 2 Dropout Row Mislabeling

**SEVERITY: MAJOR**

Body.tex Table 2 (robustness table, line ~799) labels the dropout row as "Min θ̂ (5 seeds)" and "Min Hess t (5 seeds)" but reports seed-42 values instead of the actual minimum:

| Metric | Body Claims | JSON Actual Min | JSON Seed-42 |
|--------|------------|-----------------|--------------|
| US min θ̂ | 1.94×10⁻⁴ | **1.82×10⁻⁴** | 1.94×10⁻⁴ |
| US min Hess t | 20.67 | **20.27** | 20.67 |
| JP min Hess t | 18.24 | **18.22** | 18.24 |
| TW min θ̂ | 6.21×10⁻⁵ | 6.21×10⁻⁵ | 6.21×10⁻⁵ (matches) |
| TW min Hess t | 12.17 | 12.17 | 12.17 (matches) |

The US and JP values listed as "minimum across 5 seeds" are in fact the first-seed (seed=42) values. The true minimums are lower. This is a labeling inconsistency: either the table label should be changed to "Seed-42 θ̂ / Hess t" (which then loses the intended robustness interpretation), or the values must be corrected to the true minimums (which are still far above significance thresholds, so the robustness conclusion is unaffected).

**Note**: TW values happen to match because the true TW minimum (6.21×10⁻⁵, 12.17) coincides with seed-42 values.

---

## 2. Structure and Argument Assessment

### 2.1 Overall Architecture

The paper follows a coherent logical sequence:
- §1 Introduction with main results and null-heterogeneity contribution clearly stated
- §2 Model with multiplicative GARCH-EAV specification, identification, estimation, and inference
- §3 Data (three markets)
- §4 Taiwan in-sample evidence
- §5 Cross-market extension (US + JP)
- §6 Cross-market regularity synthesis (magnitude ordering, null heterogeneity chain, factor absorption, binary vs continuous)
- §7 Robustness battery
- §8 Discussion of self-challenges
- §9 Conclusion
- Appendix A (placeholder)

This is structurally sound for a JBF/JFE-caliber paper. The logical chain from within-market null heterogeneity → market-level constant → clean cross-market comparison is explicitly articulated (§6.2, §7, §9).

### 2.2 MAJOR Issue: Table 1 Has No Dedicated Table for Placebo

The body creates Table 1 (main results with placebo z-column) and Table 2 (robustness battery). But Table 1 omits the pooled observations column for US (footnote says n=90,479 in text but not shown in table). The `Obs` column shows "90,479" for US row (line 601) — **this should be verified** but appears correct from k1147_results.json `pooled_obs = 90479`. JP Obs = 87,917 also matches. OK.

### 2.3 Reproducibility Gate

`reproduce_report.json: match_rate = 1.00, n_pass = 20/20, alert_level = green` — full gate passed. All 20 paper-location bindings verified. The reproduce.py is present and functioning.

**Missing from reproduce scope**: Summary statistics table (§3.4) is explicitly marked `[PLACEHOLDER]` with `---` dashes for Mean/Std/Skewness/Kurtosis. This table has no source bindings and is not tested by reproduce.py. This will cause the reproduce gate to fail when the table is populated.

### 2.4 MAJOR Issue: Two Unresolved PLACEHOLDER Sections

1. **§3.4 Summary Statistics Table**: cells show `---` for Mean, Std Dev, Skewness, Kurtosis. Cannot be left blank in submission.
2. **Appendix A**: Analytic-gradient verification placeholder. Referenced in main text §2.3 footnote: "Appendix A provides an analytic-gradient verification." This cross-reference to a non-existent appendix body is a hard MAJOR for reviewers.

### 2.5 Identification Argument

The exogeneity claim for EAV date (§2.2) is reasonable: earnings dates are predetermined and administratively set. However, the paper does not discuss **calendar clustering** — if many stocks share the same earnings season (especially in Taiwan's batch-disclosure regime), the pooling assumption $\theta_{\mathrm{EAV}}$ is common to all $i$ may be conflated with a market-wide calendar effect. This deserves a sentence of acknowledgment.

### 2.6 Methodological Assessment

**Strengths**:
- Cluster bootstrap (B=150, stock-level) appropriately accounts for cross-stock dependence
- Harvey (2016) |t|>3.0 threshold applied throughout
- Bonferroni correction for 3-market joint test explicitly computed
- Within-stock permutation placebo (n=60) correctly constructed (shuffle announcement dates within each stock's own time series)
- K1149 Scenario A+D correctly reported (not just A): factor absorption AND stress interaction asymmetry
- K1148_d3 selection-bias caveat explicitly acknowledged (§7.3)

**Weaknesses**:
- **§2.3**: The convergence footnote references `\citet{k1213_convergence_lesson}` — this is an internal experiment ID, not a citable academic reference. This must be replaced with a proper academic reference or reframed as internal working document.
- **§2.4**: The placebo test description says "60 replications" but does not state the random seed. For reproducibility, seed should be reported.
- **§5**: K1147 and K1150 are described as "applying the identical pooled MLE specification" — but the paper does not explicitly verify whether the VIX control (common to all three markets) introduces different lag structures or alignment issues across TW/US/JP markets. A sentence clarifying this would strengthen the methodology.

### 2.7 SEVERE Issue: International Cross-Market EAV Anchor Missing

**Body.tex lines 196–199**:
```
[CITATION NEEDED: international cross-market EAV anchor---see lit\_review.md A5;
needs NotebookLM pass before submission].
```

This `[CITATION NEEDED]` block appears in the published text of §1's "Relation to the Literature" third strand. It is explicitly flagged by the authors as missing. Without this anchor:
- The "cross-market regularities" contribution is grounded only in self-reference
- Reviewers at JBF/JFE will immediately flag the absence
- The paper cannot be submitted in this state

### 2.8 K1149 Scenario A+D: TW OOS DM −2.48 near threshold

Body §6.4 says TW OOS DM = −2.48 "pass". The paper's stated OOS DM threshold for passing is |t| > 2.0 (implied from K1149 design). However, the proximity of −2.48 to the threshold warrants an explicit footnote acknowledging that TW OOS factor absorption is marginally significant and should be interpreted with caution. Currently no such qualification appears.

### 2.9 Earnings Announcement Date Source Quality (JP)

§3.3 states JP earnings dates come from `yfinance Ticker.earnings_dates` API. This is a known-noisy source for non-US markets. Japanese fiscal year variation (quarterly vs semi-annual) is noted, but the paper does not state the proportion of JP stocks with usable announcement dates or any data-quality filtering criteria. A one-sentence data-quality statement is needed.

---

## 3. Writing Quality and Journal-Fitness Assessment

### 3.1 Strengths

- Abstract is compact and precise, containing all key quantitative results
- Introduction follows standard structure with clear separation of Main Results, Null Heterogeneity Contribution, and Relation to Literature
- The logical chain in §6.2 ("Reconciliation with Null Within-Market Heterogeneity") is well-argued and directly addresses the sample-composition confound concern
- Self-challenge discussion in §7.3 ("Hessian Wald vs cluster bootstrap" and "Multiple-spec multiplicity") demonstrates methodological sophistication
- K1148_d3 selection-bias caveat (§7.3) reflects research integrity

### 3.2 Issues

**MINOR: First-draft disclaimer in title page**
Line 46: `(First draft; not for citation)` — appropriate for internal review, must be removed before submission.

**MINOR: GitHub URL placeholder**
Line 40: `\url{[GitHub repo TBD]}` — must be replaced with actual repository URL before submission.

**MINOR: CJK font dependency**
Lines 13–15 use `\usepackage{fontspec}`, `\usepackage{xeCJK}`, `\setCJKmainfont{PingFang TC}`. These are macOS-specific fonts that will fail to compile on Linux/Windows (e.g., journal submission systems). If CJK characters are not actually needed in the English-language main text, these packages should be removed.

**MINOR: Internal experiment references as \citet{} keys**
- `\citet{k1213_convergence_lesson}` (line 322) — experiment ID, not academic citation
- `K1060` referenced in text as "Following K1060" (lines 298, 408) — should be reformatted as footnote explanation, not citation
- K1147/K1150 mentioned in timing footnote inline — acceptable as internal experiment references in footnotes

**MINOR: Abstract placebo precision**
Abstract says "13.3 (TW), 70.7 (US), and 38.6 (JP) placebo standard errors above zero." This is correct but the σ definition (within-stock permutation SE) is only explained in §2.4. Some journals expect the abstract to be self-contained; consider adding "—where σ is the cross-permutation standard deviation—" to clarify.

---

## 4. Completeness Assessment (Submission Readiness)

| Component | Status |
|-----------|--------|
| §1–9 text | Complete |
| Table 1 (main results) | Complete, verified |
| Table 2 (robustness) | Complete but has mislabeling issue |
| Summary statistics table (§3) | INCOMPLETE — all cells are `---` |
| Appendix A | INCOMPLETE — placeholder only |
| references.bib | MISSING |
| Figures | present (barplot, placebo dist in experiments) but not embedded in body.tex |
| reproduce.py 20/20 GREEN | PASS |
| Data snapshots | present in experiments/ data dirs |

---

## 5. Severity Summary

| Issue | Severity | Description |
|-------|----------|-------------|
| `[CITATION NEEDED]` international cross-market EAV in §1 | **SEVERE** | Submission blocker; missing contribution anchor |
| Table 2 dropout row mislabeled (seed-42 ≠ minimum) | **MAJOR** | Numerical inconsistency with stated methodology |
| Summary statistics table all `---` | **MAJOR** | Incomplete section; cannot submit |
| Appendix A is placeholder with forward reference in §2.3 | **MAJOR** | Cross-reference to non-existent content |
| references.bib missing | **MAJOR** | Cannot compile/submit |
| `\citet{k1213_convergence_lesson}` invalid citation key | **MAJOR** | Non-academic citation key in main text |
| TW OOS DM −2.48 near-threshold: no caveat | **MINOR** | Methodological transparency |
| JP earnings date source quality statement missing | **MINOR** | Data quality transparency |
| Calendar clustering acknowledgment missing | **MINOR** | Identification robustness |
| CJK font dependency (PingFang TC) | **MINOR** | Cross-platform compilation |
| First-draft disclaimer in title | **MINOR** | Must remove before submission |
| GitHub URL placeholder | **MINOR** | Must replace before submission |
| Placebo σ definition not in abstract | **MINOR** | Self-containedness |
| TW OOS DM in factor absorption table (§7, robustness) shows `---` for JP | **MINOR** | JP not in K1149 — correctly noted in table footnote, acceptable |

**CRITICAL**: 0
**SEVERE**: 1
**MAJOR**: 5
**MINOR**: 8

---

## 6. Top Issues Requiring Immediate Attention

1. **references.bib (MAJOR)**: The entire citation infrastructure is missing. Body.tex uses 9 distinct citation keys (`beaver1968`, `patell1976`, `patell_wolfson1979`, `ball_kothari1991`, `engel_rangel2008`, `engle2013`, `garch_x_vix_paper`, `glosten1993`, `harvey2016`). The file `references.bib` does not exist in `paper/eav-universal-magnitude/`. Additionally: (a) `engel_rangel2008` is likely a typo for `engle_rangel2008`; (b) `garch_x_vix_paper` is a placeholder key requiring a real citation; (c) `k1213_convergence_lesson` must be replaced.

2. **`[CITATION NEEDED]` in §1.3 (SEVERE)**: The third contribution strand in the Introduction (cross-market regularities) contains an in-text placeholder. This is the weakest point of the literature positioning and blocks submission.

3. **Table 2 dropout row mislabeling (MAJOR)**: The "Min θ̂ (5 seeds)" and "Min Hess t (5 seeds)" labels in Table 2 report seed-42 values for US and JP, not the actual minimum across 5 seeds. For US: min θ̂ = 1.82×10⁻⁴ (not 1.94×10⁻⁴), min Hess t = 20.27 (not 20.67). For JP: min Hess t = 18.22 (not 18.24). All values still strongly significant, so the substantive conclusion is unaffected, but the numerical claim must match the stated methodology.
