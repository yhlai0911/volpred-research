# Academic Review Report — leverage-direction v8

**Date**: 2026-05-22  
**Reviewer**: latex-academic-reviewer agent (a9b23ba3fa451e209)  
**Rating**: 3.8 / 5 ★  
**Verdict**: NEAR_READY  

---

## V7 Fix Verification

| # | V7 Issue | Claimed Fix | v8 Status |
|---|----------|-------------|-----------|
| H-1 | 16 hardcoded Section/Table refs in body | \ref{} conversion + 6 subsection labels | ✅ FIXED (subsection refs) |
| H-2 | `Section~4.5` hardcoded in tables.tex:147 | `\ref{sec:var_compliance}` | ✅ FIXED |
| H-3 | Trinity pass rates wrong | Skewed-t 90.5%, FHS 76.2% | ✅ FIXED |
| M-1 | γ_RA ambiguity | Disambiguation footnote added | ✅ FIXED |
| M-2 | Abstract date "2017--2025" | Updated to "2017--2026" | ✅ FIXED |
| M-3 | campbell2017 DOI | Corrected | ✅ FIXED |

⚠️ **Note**: Top-level section labels (`sec:literature`, `sec:methodology`, `sec:results`, `sec:discussion`, `sec:conclusion`) NOT added — roadmap sentence at body.tex line 17 still uses hardcoded "Section 2…Section 6" — see H-1 below.

---

## Issues Found

### HIGH Severity — Blocking Submission

**H-1 (new) — body.tex line 17: Roadmap sentence uses hardcoded section numbers**

Confidence: 95

The roadmap paragraph reads:
```
The remainder of the paper is organized as follows. Section 2 reviews the literature.
Section 3 describes data and methodology. Section 4 presents empirical results.
Section 5 discusses implications and limitations. Section 6 concludes.
```

Top-level section labels are absent. The v6 H-1 fix converted subsection cross-references (sec:data, sec:vt_methodology, etc.) but did not address the roadmap sentence referencing top-level sections.

Fix:
```latex
% Add \label{} to each \section{} heading in body.tex:
\section{Literature Review}\label{sec:literature}
\section{Data and Methodology}\label{sec:data_methodology}
\section{Empirical Results}\label{sec:empirical_results}
\section{Implications and Limitations}\label{sec:implications}
\section{Conclusion}\label{sec:conclusion}

% body.tex line 17:
Section~\ref{sec:literature} reviews the literature.
Section~\ref{sec:data_methodology} describes data and methodology.
Section~\ref{sec:empirical_results} presents empirical results.
Section~\ref{sec:implications} discusses implications and limitations.
Section~\ref{sec:conclusion} concludes.
```

---

**H-2 (new, same as Citation MAJOR-1) — body.tex line 76: GJR 1993 frequency error**

Confidence: 100

```
\citet{glosten1993} established the leverage effect in U.S.\ equities using
fewer than 3,000 daily observations
```

GJR (1993) used **monthly** CRSP data (~735 monthly observations, 1926–1987). "3,000 daily observations" is factually wrong in both frequency and implied sample length.

Fix: "using approximately 735 monthly observations (CRSP 1926–1987)"

---

### MEDIUM Severity

**M-1 (new) — tables.tex line 234: "Proposition 1" vs "Empirical Regularity 1"**

Confidence: 90

Table caption: `\caption{Gamma-Mechanism Mapping: GJR $\gamma$ Predicts VT Alpha Mechanism (Proposition 1)}`

Body.tex line 457: `\textbf{Empirical Regularity 1 (Gamma-Mechanism Mapping, equity-type assets).}`

"Proposition" implies a proven theoretical statement; "Empirical Regularity" signals an observed pattern. All body text uses the correct "Empirical Regularity 1" — the table caption is the outlier.

Fix: Change to `(Empirical Regularity~1)` in tables.tex line 234.

---

**M-2 (new) — Sample period inconsistency**

Confidence: 85

Three locations still say "2017--2025":
- body.tex line 156: "daily returns for our seven assets over 2017--2025"
- tables.tex line 6 (tab:desc caption): "(2017--2025)"
- body.tex line 599: "The primary sample covers 2017--2025 (seven assets), with 2026 data serving as out-of-sample validation"

Abstract (main.tex line 39) says "over 2017--2026."

Body.tex line 599 reveals the design: 2017–2025 is primary in-sample, 2026 is OOS. This is defensible but must be stated consistently. Options:
1. Update abstract to distinguish IS vs OOS periods
2. Update lines 156 and tables.tex caption to 2017–2026 and define IS/OOS in data section

Also: BTC shows N=3285 in tab:desc vs ~2260 for other assets — unexplained (BTC trades 365 days/year). Add footnote.

---

### MINOR Severity

**Minor-1 (from v7 M-3) — tables.tex lines 125, 204: "Errata:" prefix non-standard**

Inline "Errata:" annotations should be converted to standard dagger footnote style. Journals require footnotes, not inline errata.

**Minor-2 (new) — body.tex line 249: FHS not defined on first use**

"FHS" appears without expansion. Add "Filtered Historical Simulation (FHS)" on first use.

**Minor-3 (new) — γ_HM cross-reference is forward-looking**

γ_HM first appears at line 384; disambiguation footnote at line 386 refers forward to sec:vt_alpha_nature. Adequate but creates minor reader friction. Add brief inline "(γ_{HM}, the Henriksson-Merton timing coefficient)" at first occurrence.

---

## Dimension Scores

| Dimension | Area | Score |
|-----------|------|-------|
| A | LaTeX structure | 4/5 |
| B | Abstract accuracy | 4.5/5 |
| C | Citation accuracy | 3/5 (GJR error) |
| D | Notation consistency | 4/5 |
| E | Argument logic | 4.5/5 |
| F | Table/caption consistency | 3.5/5 |
| G | Sample period consistency | 3.5/5 |
| H | Symbol disambiguation | 3.5/5 |
| I | Cross-reference integrity | 4/5 |
| J | Submission readiness | 3.5/5 |

---

## Required Fixes for v9 (Submission)

**HIGH — must fix:**
1. body.tex line 76 — GJR 1993: "3,000 daily" → "~735 monthly observations (CRSP 1926–1987)"
2. body.tex line 17 — roadmap: add 5 top-level `\label{}` + convert to `\ref{}`

**MEDIUM — should fix:**
3. tables.tex line 234 — caption: "Proposition 1" → "Empirical Regularity~1"
4. body.tex line 156 + tables.tex line 6 — reconcile 2017–2025 vs 2017–2026; add BTC N footnote

**MINOR:**
5. tables.tex lines 125, 204 — convert "Errata:" to dagger footnote style
6. body.tex line 249 — define FHS on first use

---

**Prediction**: After 6 fixes applied → 4.5★ READY for submission.

The paper's core argument (leverage direction taxonomy, complexity ceiling, VT domain orthogonality) is coherent and evidence-based. No structural revision needed.
