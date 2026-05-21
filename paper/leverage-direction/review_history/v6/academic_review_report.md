# Academic Review Report — leverage-direction v6

**Target paper:** `paper/leverage-direction/body.tex` + `main.tex`
**Review date:** 2026-05-22
**Reviewer:** latex-academic-reviewer skill (agent ac13274460e2f4a07)
**Triggered by:** post-v5-all-fixes-verify

---

## Overall Verdict

**4.2 / 5★ — NEAR_READY (NOT READY for submission)**

The paper has excellent theoretical framing, strong empirical depth, and compelling cross-asset evidence. The core argument (leverage direction ≠ asset class, orthogonal VaR/VT domains, complexity ceiling) is well-structured and the H-2 circularity defense is now robust. However, **H-1 hardcoded cross-references are a blocking issue**: LaTeX `\ref{}` is not being used for most Section and Table numbers, creating fragility when sections reorder at copy-editing stage. Additionally, two medium issues remain: the hood2025 bibliography entry is missing its subtitle and still lists "early access", and the Engle (1982) ARCH test citation is missing at the ARCH effects mention in §3.1.

**Predicted journal response (JBF):** Accept with minor revisions — once H-1 is fixed and M-2/M-3 resolved, the paper meets JBF standards for rigor and contribution.

---

## Issues Summary

### HIGH Severity — Blocking Submission

#### H-1: Residual hardcoded Section and Table numbers (Confidence: 95)

Multiple locations in body.tex reference section and table numbers by hardcoded numerals instead of LaTeX `\ref{}` macros. This is a systematic issue: if sections reorder during copy-editing (common at JBF), all these references will silently point to wrong locations.

**Hardcoded Section refs found:**

| Line | Content | Fix |
|------|---------|-----|
| 126 | `Section~4.4 demonstrates` | `Section~\ref{sec:var_compliance}` |
| 156 | `in Section 4.2, this criterion` | `in Section~\ref{sec:leverage_direction}` |
| 158 | `(Section 4.5)` | `(Section~\ref{sec:vt_results})` |
| 158 | `(Section 4.4)` | `(Section~\ref{sec:var_compliance})` |
| 167 | `Section~4.2 for the regime-dependent` (in footnote) | `Section~\ref{sec:leverage_direction}` |
| 242 | `(Section 4.3)` | `(Section~\ref{sec:garch_comparison})` |
| 263 | `Section~4.4 therefore establishes` | `Section~\ref{sec:var_compliance}` |
| 283 | `Section 3.5,` | `Section~\ref{sec:vt_methodology}` |
| 283 | `Section~4.3:` | `Section~\ref{sec:garch_comparison}` |
| 369 | `(Section~4.3)` | `(Section~\ref{sec:garch_comparison})` |
| 441 | `Section~4.7` (in footnote) | `Section~\ref{sec:timing_tests}` |
| 568 | `Section~4.5` | `Section~\ref{sec:vt_results}` |
| 593 | `Section~3.1` | `Section~\ref{sec:data}` |

**Hardcoded Table refs found:**

| Line | Content | Fix |
|------|---------|-----|
| 225 | `Tables 2 and 3,` | `Tables~\ref{tab:gamma} and \ref{tab:qlike},` |
| 231 | `Table~3` (×2) | `Table~\ref{tab:qlike}` (×2) |
| 283 | `Table~3` | `Table~\ref{tab:qlike}` |

**Required new section labels to add (before fixing refs):**

| Subsection | Line | Label to add |
|-----------|------|-------------|
| `\subsection{Data}` | 55 | `\label{sec:data}` |
| `\subsection{Volatility Targeting}` (§3.5, methodology) | 138 | `\label{sec:vt_methodology}` |
| `\subsection{Leverage Direction Across Asset Classes}` | 161 | `\label{sec:leverage_direction}` |
| `\subsection{GARCH vs. GJR-GARCH: Forecasting Comparison}` | 211 | `\label{sec:garch_comparison}` |
| `\subsection{VaR Compliance: Distribution Choice Dominates}` | 240 | `\label{sec:var_compliance}` |
| `\subsection{Volatility Targeting Across Leverage Regimes}` | 279 | `\label{sec:vt_results}` |

---

### MEDIUM Severity

#### M-2: `hood2025` bibliography still has "early access" (Confidence: 90)

**File / Line:** `main.tex` line 181

The hood2025 entry in the bibliography:
```
Hood, B., & Raughtigan, C. (2025). Volatility targeting is trendy.
Journal of Portfolio Management, early access.
```

Two problems:
1. "early access" should be replaced with final volume/issue/page data. The paper was published 2025-09-08; final pagination should now be available.
2. Missing subtitle: full title is "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies" (confirmed by citation-verifier, see citation_check_report.md MED-2).

**Fix:** Verify final Vol/issue/pages at doi.org/10.3905/jpm.2025.1.764 and update entry.

---

#### M-3: Missing `\citep{engle1982}` ARCH test citation (Confidence: 92)

**File / Line:** `body.tex` line 66

Current text:
> "...exhibit significant ARCH effects (Engle's LM test $p < 0.001$)..."

The ARCH LM test is due to Engle (1982) and must be cited. The bibliography already contains `engle2018` (Engle & Siriwardane 2018, RFS) but NOT the original Engle (1982) ARCH paper:

> Engle, R. F. (1982). Autoregressive conditional heteroscedasticity with estimates of the variance of United Kingdom inflation. *Econometrica*, 50(4), 987–1007. https://doi.org/10.2307/1912773

**Fix (two steps):**
1. `body.tex` line 66: Change "Engle's LM test $p < 0.001$" to "Engle's \citep{engle1982} LM test $p < 0.001$"
2. `main.tex`: Add `engle1982` bibitem entry (sorted alphabetically, after `engle2006` and before `engleGhyselsSohn2013`)

---

### MINOR Severity

#### min-3: `cederburg2020` framing (from citation check)

Body.tex line 45 presents cederburg2020 as supporting VIX-scaling, but the paper's headline finding is broadly negative on VT across 103 strategies. See `citation_check_report.md` MED-1 for full details and suggested rewrite.

---

## Verified Content (Not Issues)

- **H-2 ρ=1.000 circularity defense** (line 462): Well-argued with OOS ρ=0.821 quantification. ✅
- **MCS attribution** (line 367): `\citep{hansen2011}` (Econometrica 2011) correctly cited for Model Confidence Set. ✅  
- **GJR-GARCH γ taxonomy** across 7 assets: clear, defensible, domain-restricted to equity-type. ✅
- **Orthogonality framing** (GARCH equation ≠ distributional assumption ≠ signal source): novel and well-demonstrated. ✅
- **VaR/ES domain orthogonality table** (tab:var_ortho): quantitatively compelling. ✅
- **Complexity ceiling** (sec:qlike_ceiling): 0.31% QLIKE range for GARCH family is striking and well-documented. ✅
- **DM test Harvey threshold t>3.0**: correctly applied throughout. ✅
- **han2011 / han2005 separation**: both correctly attributed (MCS vs. 330-model comparison). ✅

---

## Action Plan for v7

**Must fix (blocking):**
1. Add 6 missing section labels to body.tex (see H-1 table above)
2. Replace all 13 hardcoded Section refs + 3 hardcoded Table refs in body.tex
3. Add `\citep{engle1982}` to body.tex line 66 (M-3)
4. Add `engle1982` bibitem to main.tex (M-3)
5. Update `hood2025` bibitem: final pagination + full subtitle (M-2, confirmed by citation verifier)

**Should fix (MED, for submission quality):**
6. Reframe `cederburg2020` at body.tex line 45 (min-3/citation MED-1)

**Predicted after v7 P1+P2+P3 fixes:** 4.5/5★ READY for submission

---

## Files in This Round

- `citation_check_report.md` — 0 MAJOR, 2 MED, 4 MINOR (0 blocking, 2 requiring fix)
- `academic_review_report.md` — this file
- `README.md` — round summary (see review_history/v6/README.md)
