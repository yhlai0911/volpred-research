# Academic Review Report — leverage-direction v7

**Date**: 2026-05-22  
**Reviewer**: latex-academic-reviewer (automated, rigorous)  
**Verdict**: NEAR_READY  
**Rating**: 3.5 / 5 ★  

---

## V7 Fixes Verification

The v6 review identified four issues requiring correction before the paper could advance. Status of each:

| Issue | Claimed Fix | Verification Result |
|-------|-------------|---------------------|
| H-1 (blocking): 16 hardcoded Section/Table refs | Added 6 new labels (sec:data, sec:vt_methodology, sec:leverage_direction, sec:garch_comparison, sec:var_compliance, sec:vt_results) and converted refs to \ref{} | **PARTIAL** — Two hardcoded refs remain (see HIGH issues below) |
| M-2: hood2025 subtitle wrong | Updated to "Volatility targeting is trendy: How trend following explains alpha in volatility-managed strategies" | **CONFIRMED FIXED** — main.tex lines 183–184 correct |
| M-3: engle1982 missing bibitem + citation | Added Econometrica 50(4) 987–1007 bibitem and \citep{engle1982} citation | **CONFIRMED FIXED** — bibitem in main.tex lines 114–115; citation in body.tex line 67 |
| MED-1: cederburg2020 framed only positively | Reframed to lead with negative headline finding | **CONFIRMED FIXED** — body.tex line 45 now reads "whose headline finding is that VT does not systematically improve Sharpe ratios over unmanaged portfolios" |

**Summary**: 3/4 fixes fully applied. H-1 remains partially incomplete — the six new labels are present and most cross-refs have been converted, but two hardcoded references survived.

---

## Issues Found

### HIGH Severity (Blocking / Must Fix Before Submission)

**H-1 RESIDUAL — body.tex line 17: Roadmap sentence uses hardcoded section numbers**

```
The remainder of the paper is organized as follows.
Section 2 reviews the literature. Section 3 describes data and methodology.
Section 4 presents empirical results. Section 5 discusses implications and limitations.
Section 6 concludes.
```

All six section numbers must be converted to `\ref{}`. The six labels are already defined in the document; this is purely a mechanical fix. Example correction:

```latex
Section~\ref{sec:literature} reviews the literature.
Section~\ref{sec:data} describes data and methodology.
Section~\ref{sec:results} presents empirical results. ...
```

Note: `sec:literature`, `sec:results`, `sec:discussion`, `sec:conclusion` labels will need to be added if not already present (only the six new labels from v7 were confirmed; check body.tex for coverage of all six roadmap sections).

---

**H-2 — tables.tex line 147: "Section~4.5" in tab:vt table notes**

The table notes for `tab:vt` (VT strategy comparison panel) contain:

```
See Section~4.5 for the complete hybrid VT specification.
```

This is a hardcoded reference. It must be converted to `\ref{}` using the appropriate section label. The label `sec:vt_methodology` or `sec:vt_results` (whichever covers the hybrid VT subsection) should be used, or a new label `sec:hybrid_vt` added to the relevant subsection.

---

**H-3 (NEW) — var_panel contradiction between body.tex and tables.tex**

Body.tex line 249 states:

> "skewed-t and FHS share the highest Trinity pass rate at 76.2% (16/21)"

But tables.tex `tab:var_panel` (lines 113–114) shows:

| Model | Pass rate |
|-------|-----------|
| Skewed-t | 90.5% (19/21) |
| FHS | 76.2% (16/21) |
| CF-VaR | 76.2% (16/21) |
| Student-t(5) | 76.2% (16/21) |
| Normal | 57.1% (12/21) |

The claim that "skewed-t and FHS share the highest Trinity pass rate at 76.2%" directly contradicts the table, which shows Skewed-t at 90.5% — a higher figure — and FHS at 76.2%. The body text must be corrected to accurately reflect the table: Skewed-t achieves the highest pass rate at 90.5% (19/21), while FHS, CF-VaR, and Student-t(5) are tied at 76.2% (16/21). This is a factual error in the body that misrepresents the paper's own findings.

---

### MEDIUM Severity (Should Fix Before Submission)

**M-1 (NEW) — γ symbol overload: CRRA risk aversion parameter**

The paper uses γ throughout as the GJR-GARCH leverage direction parameter (the paper's central construct). However, body.tex line 495 introduces:

> "CRRA risk aversion parameter γ ≈ 4.5, well within the empirical range (γ ∈ [2, 10]; \citealt{cederburg2020})"

Using the same Greek letter γ for both the GJR-GARCH asymmetry coefficient and the CRRA risk aversion coefficient in the same paper is a symbol collision. Standard practice is to use λ, A, or ρ for CRRA risk aversion (all appear in the literature). Rename the CRRA parameter (e.g., to λ) with an explicit note on first use: "where λ ≈ 4.5 denotes the CRRA risk aversion coefficient."

---

**M-2 (NEW) — Abstract date "2017--2025" contradicts data section "January 2017 through March 2026"**

The abstract states the sample period as "2017--2025." The data section (body.tex line 58) states "January 2017 through March 2026." These are inconsistent. The data section date is presumably correct (as it is more specific). The abstract must be updated to "January 2017 through March 2026" or at minimum "2017--2026" to match. A date mismatch between abstract and data section is a basic factual inconsistency that reviewers will flag immediately.

---

**M-3 (NEW) — Errata notes embedded in tables inappropriate for journal submission**

Tables `tab:var_panel` and `tab:amplify` contain embedded errata text (visible in tables.tex). The word "Errata" and errata-style annotations are internal revision notes — they are not appropriate for journal submission copy. These should be either:
- Reconciled directly in the table (if the numbers have been corrected), or
- Removed entirely if they refer to superseded versions.

No published journal table should contain the word "Errata" in its notes. Clean up before finalizing the submission-ready PDF.

---

### MINOR Issues (Fix if Time Permits)

**MIN-1 — Rounding discrepancies between body text and Table 1 (tab:desc)**

Three values differ between body.tex prose and tables.tex descriptive statistics for SPY:

| Statistic | Body text | Table 1 |
|-----------|-----------|---------|
| Excess kurtosis | 14.61 | 14.6 |
| Skewness | -0.315 | -0.32 |
| Min daily return | -10.94% | -10.9% |

These are one-digit rounding differences. Standardize to one convention (either 2 decimal places throughout or 1 decimal in tables). The discrepancy is minor but looks inconsistent under close scrutiny.

---

**MIN-2 — Abbreviation first-use definitions**

The following abbreviations appear in the paper without confirmed explicit first-use definitions:

- **FHS** (Filtered Historical Simulation) — used in results sections
- **MCS** (Model Confidence Set) — used in results sections  
- **SSVS** (Stochastic Search Variable Selection) — appears in methodology/robustness
- **DQ test** (Dynamic Quantile test) — appears in VaR backtesting
- **VRP** (Variance Risk Premium) — appears in discussion
- **CRRA** (Constant Relative Risk Aversion) — appears in Appendix

Finance journals expect all non-universal abbreviations defined on first use. Verify each is defined in the text before its first appearance. If any of these appear only in appendices, ensure the appendix text itself provides the definition.

---

**MIN-3 — Footnote referencing another paper's table numbers**

Body.tex line 45 (cederburg2020 passage) contains a footnote referencing "Tables 2--3" — these are table numbers in the Cederburg et al. paper, not in the current paper. This is stylistically acceptable (citing specific tables in a reference is legitimate academic practice) but the footnote wording should make clear these are tables in the cited work, not the current paper, to avoid reader confusion.

---

**MIN-4 — Internal experiment reference in reproducibility footnote**

Body.tex line 170 contains a footnote referencing internal experiment K903. This is acceptable given that the paper describes a replication package. Ensure K903 is listed in the supplementary material / replication package index before submission. Journals do not require internal experiment codes to be removed, but they must be traceable in the replication package.

---

## Dimension-by-Dimension Assessment

| Dimension | Score | Notes |
|-----------|-------|-------|
| A. Argument & Logic Flow | 4/5 | Strong central thesis; leverage direction taxonomy well-motivated; H-3 contradiction weakens results section credibility |
| B. Symbol Consistency | 3/5 | γ overload (M-1) is the only significant issue; otherwise consistent notation |
| C. Equation Formatting | 4/5 | GJR-GARCH, QLIKE, VaR/ES equations correctly formatted; no broken numbering observed |
| D. Table/Figure Quality | 3/5 | H-3 contradiction, errata notes (M-3), minor rounding (MIN-1) reduce confidence |
| E. Citation Coverage | 4/5 | M-2, M-3, MED-1 all confirmed fixed; bibliography comprehensive for the topic |
| F. Cross-Reference Integrity | 3/5 | H-1 residual and H-2 mean two hardcoded refs remain; six new labels are present |
| G. Abstract/Intro Alignment | 3/5 | Date mismatch (M-2) is an immediate red flag |
| H. Statistical Rigor | 4/5 | DM test with Harvey correction, HAC standard errors, MCS, VaR backtesting all appropriate |
| I. Narrative Consistency | 3/5 | H-3 var_panel contradiction undermines the key empirical results narrative |
| J. Submission Readiness | 3/5 | Multiple blocking issues remain; not yet submission-ready |

---

## Overall Assessment

**Verdict: NEAR_READY — 3.5★**

The leverage-direction paper is substantively strong. The central thesis — that the sign of the GJR-GARCH γ parameter systematically predicts the direction of volatility-managed strategy performance — is well-motivated, methodologically sound, and supported by appropriate statistical machinery (DM tests, Harvey correction, VaR backtesting, Basel III compliance). The v7 revision successfully addressed three of the four v6 blocking issues.

However, three issues prevent submission as-is:

1. **H-3 (var_panel contradiction)** is the most serious: the body text claims skewed-t and FHS tie at 76.2%, but the table shows skewed-t at 90.5%. This is a direct factual error in the narrative of the results section — the kind that desk editors and peer reviewers will catch immediately and that signals inadequate proofreading.

2. **H-1 residual + H-2**: Two hardcoded section references remain despite the v7 fix supposedly resolving all 16. The roadmap sentence (body line 17) and the tab:vt note "Section~4.5" (tables line 147) must be converted to \ref{} before final submission.

3. **M-2 abstract date mismatch**: "2017--2025" vs "January 2017 through March 2026" is a basic consistency error that must be corrected.

The γ symbol overload (M-1) and errata notes in tables (M-3) should also be resolved before submission but are not as immediately damaging.

**Required actions before next review cycle**:
1. Fix body.tex line 17 roadmap sentence → convert all 5 section numbers to `\ref{}`
2. Fix tables.tex line 147 → convert `Section~4.5` to `\ref{<label>}`
3. Fix body.tex line 249 → correct var_panel pass rate statement to match table (Skewed-t 90.5%, not 76.2%)
4. Fix abstract date → "January 2017 through March 2026" (or "2017--2026" minimum)
5. Fix body.tex line 495 → rename CRRA γ to λ (or another non-conflicting symbol)
6. Remove errata annotations from tables.tex (tab:var_panel, tab:amplify)

After these six corrections, the paper should be in READY condition for a final pass before submission.

---

*Review generated: 2026-05-22. Files reviewed: body.tex (673 lines), main.tex (239 lines), tables.tex (253 lines). Review criteria: `.claude/skills/latex-academic-reviewer/SKILL.md` + `.claude/skills/latex-academic-reviewer/references/review-criteria.md`.*
