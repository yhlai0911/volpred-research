# LaTeX Academic Review — Paper 9 (garch-x-vix) v3

**Manuscript**: `paper/garch-x-vix/main.tex`
**Date**: 2026-05-19
**Reviewer**: Claude (latex-academic-reviewer skill)
**Scope**: Full LaTeX/typesetting audit, equation consistency, notation, logical flow, structure

---

## Summary

| Category | HIGH | MEDIUM | LOW |
|----------|------|--------|-----|
| LaTeX / Typesetting | 0 | 3 | 4 |
| Equation / Notation consistency | 1 | 4 | 2 |
| Structural / Logical flow | 2 | 3 | 2 |
| **TOTAL** | **3** | **10** | **8** |

**Overall**: The manuscript is typeset competently. The most pressing issues are (1) a structural contradiction between the economic narrative in the discussion section (Propositions 1-3) and the best-performing model being A4f (free-omega), which loosens the structural identification underpinning those propositions; (2) the QLIKE footnote reveals a unit-scaling difference across tables without full acknowledgment; and (3) equation-label numbering contains a gap that may confuse readers.

---

## HIGH Issues

### HIGH-1. Structural contradiction: Proposition 2 (constrained) vs. recommended model (A4f, free)

**Location**: Section 6 (Discussion), Proposition 2 + abstract/conclusion

**Issue**: Proposition 2 derives the VRP auto-correction interpretation via the constrained model (`E[g_t] = 1`), where `θ_1-ratio = 0.78` implies a 21.9% VRP discount. However, the paper's recommended model throughout is A4f (free ω_g), which has `θ_1-ratio = 1.96` and `E[g_t] = 0.48`. The proposition statement and the surrounding prose do not clearly flag that the structural VRP identification only applies to the constrained model.

The abstract states: "We show that the g_t component contemporaneously tracks the variance risk premium (Spearman ρ ≈ 0.80)" without specifying which model variant. The conclusion (line 856) again refers to "g_t … tracking VRP dynamics at ρ ≈ 0.80" while the recommended model is A4f.

The v2 adversarial review (Challenge 5 — Source Decomposition Coherence) identified this as a SIGNIFICANT CONCERN; the LaTeX review now confirms it is structurally embedded in the manuscript's formal propositions.

**Required fix**:
- Add a clear note to Proposition 2 or its proof sketch that the `θ_1` VRP interpretation applies to the constrained model (A4, not A4f).
- In the discussion, explicitly acknowledge that A4f's additional `ω_g` degree of freedom "redistributes" the VRP correction across two channels (`θ_1` and `E[g_t]`), with effective ratio 0.94 (still close to the constrained 0.78).
- Either (a) align Table 3 VRP correlation figures with the recommended A4f model, or (b) explicitly footnote that Table 3 uses A3f/A2n/A4n (all constrained-ish) specifically because they cleanly satisfy Proposition 2, while A4f is recommended for forecasting.

---

### HIGH-2. Missing sub-period analysis creates a logical gap in the robustness section

**Location**: Section 5.1 (Sensitivity to Estimation Settings), Table 5

**Issue**: Table 5 reports sub-period DM tests (2019-2020, 2021-2022, 2023-2026) with a footnote noting "DM test lacks power with n ≈ 500 observations." The paragraph below Table 5 (lines 714-716) pivots to a separate "extended sub-period analysis using seven non-overlapping two-year windows spanning 2013-2026" that is not shown in any table. This unnamed analysis provides the key COVID-robustness claim ("removing [COVID] leaves 4.8-6.8% improvements"), but the evidence is presented entirely in prose with no table reference.

At top-tier journals (JEF, JoF), presenting central robustness claims without a corresponding table or appendix figure is problematic. A referee will ask: "Where is this 7-period analysis?" The v2 adversarial review (Challenge 4 — COVID dominance) rated this a SERIOUS FLAW; the prose acknowledgment without a table does not satisfactorily resolve it.

**Required fix**: Either (a) add the 7-period two-year window DM table to Section 5 or Appendix, or (b) restructure the sub-period discussion to present pre-COVID / COVID / post-COVID figures in the existing Table 5 format.

---

## MEDIUM Issues

### MEDIUM-1. QLIKE scaling inconsistency across tables requires more prominent disclosure

**Location**: Footnote to Table 2 (main results), line 295 footnote

**Issue**: The paper acknowledges (correctly via an existing footnote at line 295) that QLIKE values differ in magnitude between the main SPY table (~-8.3) and cross-asset tables (~1.4-1.6) due to variance scaling. However, this disclaimer is placed in a footnote to the evaluation methodology section, far from the cross-asset table (Table 4). A reader comparing Table 2 and Table 4 values without careful footnote reading will be confused. In addition, the disclaimer says "Rankings within each table are internally consistent" but does not explicitly warn that cross-table QLIKE level comparisons are invalid.

**Fix**: Move a condensed version of this disclaimer to Table 4's footnote. Add explicit text: "QLIKE levels are not comparable across Table 2 and Tables 4-6 due to different return scaling conventions. All comparisons are within-table."

---

### MEDIUM-2. Equation label gap: no \label{eq:...} between eq:u_lagged (Eq. 5) and eq:loglik (Eq. 10)

**Location**: Section 3.1–3.3

**Issue**: The GARCH-MIDAS tau equation is labeled `eq:midas_tau` (Eq. 6) and `eq:beta_weights` (Eq. 7). The log-likelihood is `eq:loglik` (Eq. 9 by count). But the parameter estimation paragraph at line 266 refers to "parameter vector" without a new equation label, and the constraint `ω_g = 1 - α - γ/2 - β` is stated twice (lines 187 and 261) without a shared label — the first instance is part of a list, the second is inline prose. Readers cannot cross-reference without re-reading.

**Fix**: Add `\label{eq:omega_constraint}` to the first formal statement and use `\eqref{eq:omega_constraint}` on the second occurrence at line 261.

---

### MEDIUM-3. VaR/ES equations lack explicit notation for the "pass" criterion

**Location**: Section 3.2.4 (VaR and ES Backtesting), last sentence before Section 4

**Issue**: Line 323 states "A model 'passes' at level α if all three VaR tests (UC, CC, DQ) have p > 0.05." This threshold (p > 0.05) is used consistently throughout, but is stated only once in this informal sentence. The scorecard tables (Tables 7-8) use "Pass/Fail" without reference back to this definition. A formal definition environment or at minimum a repeated inline reference ("passes by the criterion of Section 3.2.4") in the results section would improve rigor.

**Fix**: Either define a `criterion` environment or add "(by the criterion of Section~\ref{sec:evaluation})" when "Pass" is first used in Tables 7-8 captions.

---

### MEDIUM-4. Proposition 3 is stated in non-standard econometric language

**Location**: Section 6, Proposition 3

**Issue**: Proposition 3 reads: "The dynamic factor g_t reflects time-varying departures of realized variance from the VRP-corrected implied level. The GARCH autoregressive structure smooths the noisy daily ratio r_t^2/τ_t, extracting its persistent VRP component." This is an economic observation, not a mathematical proposition — it has no formal statement of conditions (measurability, stationarity), no proof, and no formal statement of what is claimed. For a top-tier econometrics journal, calling this a "Proposition" without proof is unusual; it will attract referee criticism.

**Fix**: Rename to "Remark 3" or "Observation 3" (which does not require proof), or add a formal conditional statement ("Under Assumptions A1-A3, Corr(g_t, VRP_t) > Corr(r_t^2/τ_t, VRP_t) in expectation") and provide at least a sketch proof.

---

### MEDIUM-5. Table 2 (main results) caption says "QLIKE rankings" but column header says "DM t vs GJR"

**Location**: Table 2 caption and column header

**Issue**: The table caption is "Out-of-sample specification comparison: QLIKE rankings." However, the table contains both QLIKE values and DM test statistics — the DM column is arguably equally important. The caption is accurate but undersells the content. More critically, Table 2's fourth column is "Harvey sig." which refers to whether |t| > 3.0, but the footnote says "DM t is the Diebold-Mariano test statistic against GJR-GARCH (B0); positive values indicate the model is better." A reader may initially confuse "Harvey sig." with the Harvey et al. (2016) multiple-testing framework (which applies to cross-sectional factor studies, not time-series forecast comparisons).

**Fix**: Change caption to "Out-of-sample QLIKE rankings and Diebold-Mariano test results." Add a footnote clarification: "Harvey significance here denotes |t| > 3.0 following the conservative threshold recommended by Harvey et al. (2016) for multiple comparisons, adapted to time-series forecast horse races."

---

## LOW Issues

### LOW-1. `\usepackage{xeCJK}` and `\setCJKmainfont{PingFang TC}` present in submission draft

**Location**: Lines 14-15 (preamble)

**Issue**: The manuscript uses `xeCJK` and sets `PingFang TC` as the CJK font. This is non-standard for an English-language journal submission and will cause compilation failure on referees' systems without PingFang TC installed. The paper body contains no Chinese text.

**Fix**: Remove `\usepackage{xeCJK}` and `\setCJKmainfont{PingFang TC}` from the submission draft. If Chinese-language versions are needed internally, maintain a separate build.

---

### LOW-2. `\usepackage{fontspec}` without XeLaTeX note

**Location**: Line 13 (preamble)

**Issue**: `fontspec` requires XeLaTeX or LuaLaTeX; standard pdfLaTeX will fail. No build instruction mentions this requirement. Many journals' submission systems use pdfLaTeX by default.

**Fix**: Either (a) remove `fontspec` (only needed for CJK, which can be removed per LOW-1), or (b) add a build comment at top of file: `% Compile with: xelatex main.tex`.

---

### LOW-3. `\date{April 2026}` hardcoded

**Location**: Line 43

**Issue**: For a paper currently in submission cycle, a hardcoded month is acceptable but risks becoming stale (the paper was drafted in April 2026, and further revision may move to May-June 2026 or later).

**Fix**: Minor: change to `\date{\today}` or remove `\date{}` to suppress if working draft.

---

### LOW-4. `\newcommand{\bm}[1]{\boldsymbol{#1}}` shadows existing `bm` package

**Location**: Line 35

**Issue**: The command `\bm` is already defined by the `bm` package (if loaded) with better Unicode/font support. The current definition redefines `\bm` as a simple alias for `\boldsymbol`. The paper does not load the `bm` package, so there is no conflict, but any future editor adding `\usepackage{bm}` would get an error. The usage `\bm{\psi}` (line 266) should use the standard `\boldsymbol{\psi}` or load `\usepackage{bm}` and remove the custom `\newcommand`.

**Fix**: Remove `\newcommand{\bm}` and instead use `\usepackage{bm}` in the preamble; `\bm{\psi}` will then automatically use the `bm` package's superior bold math implementation.

---

### LOW-5. Table 3 (VRP correlation) uses A3f as top entry, not A4f

**Location**: Table 3, first row

**Issue**: The recommended model throughout the paper is A4f, but Table 3 shows the highest VRP correlation is for A3f (τ_{t-1}, free ω), ρ = 0.819. A4f's correlation is not explicitly listed. If A4f has a different VRP correlation (lower, because free ω changes the level of g_t), this should be prominently reported for model consistency. The current presentation may give an inflated impression of the A4f model's structural interpretability.

**Fix**: Add A4f's VRP correlation as the first row (or a separate panel), with a note if it differs from A3f.

---

### LOW-6. `\label{tab:local_fear}` vs `\ref{tab:local_fear}` — Table 5 numbering issue

**Location**: Table 5 (local fear experiments)

**Issue**: The cross-reference at line 543 reads "Table~\ref{tab:local_fear} examines whether asset-specific fear indices..." but Table 4 (cross-asset) and Table 5 (local fear) both appear in rapid succession in Section 4. Depending on how LaTeX counts float positions, the reader may see Tables 4 and 5 in unexpected order relative to their first reference. This is a float ordering issue (using `[H]` placement with `\usepackage{float}`) — with forced `[H]` placement on all tables, this should compile correctly, but should be tested.

**Fix**: Confirm `[H]` placement is consistent; verify cross-references resolve correctly after `xelatex` compile.

---

### LOW-7. Abstract claims "DM t = 3.39" for GLD but Table 4 body uses "t = 3.17" for GLD (GVZ)

**Location**: Abstract (line 51) vs. Table 4 (line 524)

**Issue**: Abstract says "GLD with GVZ (t = 3.39)" at first mention, then "GLD with GVZ ($t = 3.17$)" at the second mention — actually line 51 reads "GLD with GVZ ($t = 3.17$)" but line 83 says "$t = 3.39$" for "GLD with GVZ (DM $t = 3.39$)". This inconsistency appears to be: Table 4 reports t = 3.17 for GVZ-only, and the "dual" GLD+GVZ result is t = 3.39 (Table 5). The abstract's first reference ($t = 3.17$) matches Table 4, but the introduction's third contribution (line 83) reports $t = 3.39$ (the dual model) without flagging the difference.

**Fix**: Verify whether the abstract/intro claim is meant to cite the GVZ-only result (3.17) or the dual result (3.39). If the dual model, update the abstract's main mention to 3.39. If GVZ-only, update line 83 to 3.17. Add clarifying text.

---

### LOW-8. Proposition 1 proof sketch is incomplete

**Location**: Section 6, Proposition 1

**Issue**: Proposition 1 states: "the unconditional variance satisfies E[σ_t^2] = E[τ_t]·E[g_t] + Cov(τ_t, g_t)." This is simply the definition of E[XY] = E[X]E[Y] + Cov(X,Y) applied to σ_t^2 = τ_t × g_t, so it holds identically without any assumptions. The proposition adds no content beyond the algebraic identity and does not need assumptions. Calling it a "Proposition" with "This identity is exact, not an approximation" implies there is something non-trivial to prove.

The claim following it — "Corr(τ_t, g_t) ≈ 0.49" — is actually the economically interesting empirical result (crisis channel: high VIX → high τ_t → large shocks → higher g_t). This empirical result should be a separate statement or table entry.

**Fix**: Either drop Proposition 1 as trivial, or reframe as "Empirical Result 1: Corr(τ_t, g_t) = 0.49 (estimated) and the approximate simplification E[σ_t^2] ≈ E[τ_t] introduces a Y% error," making the empirical finding the content.

---

## Format and Structure Observations (not issues per se)

1. **Two-level table structure is appropriate** for a 17-model horse race — no changes needed to Table 2's layout.
2. **Section ordering** (Model → Data → Results → Robustness → Discussion → Conclusion) is logical and follows journal conventions for empirical finance papers.
3. **Double spacing** and A4 format are appropriate for submission. No issues.
4. **Bibliography** (thebibliography environment with manual entries) is acceptable but a .bib file would reduce maintenance errors — suggest for future revision cycles.
5. **`natbib` usage**: `\citet{...}` and `\citep{...}` are used correctly and consistently throughout the text. No citation command errors found.
6. **Table footnote style**: `\begin{tablenotes} \footnotesize \item ... \end{tablenotes}` from `threeparttable` is used consistently and correctly.

---

## Priority Fix List

| Priority | Issue | Action |
|----------|-------|--------|
| HIGH | HIGH-1: A4f free-ω vs Proposition 2 constrained-ω contradiction | Add clarifying note to Proposition 2; align VRP discussion with A4f model |
| HIGH | HIGH-2: 7-period COVID analysis without table | Add Table A1 in appendix or restructure existing Table 5 |
| MEDIUM | MEDIUM-1: QLIKE scaling disclaimer far from cross-asset table | Add note to Table 4 footnote |
| MEDIUM | MEDIUM-4: Proposition 3 lacks formal status | Rename to Remark 3 |
| MEDIUM | MEDIUM-5: "Harvey sig." column label ambiguous | Add footnote clarification |
| LOW | LOW-1: xeCJK/PingFang TC breaks external compilation | Remove from submission draft |
| LOW | LOW-7: GLD DM t inconsistency (3.17 vs 3.39) across abstract/intro | Verify and align |
| LOW | LOW-5: Table 3 does not show A4f VRP correlation | Add A4f row to Table 3 |
