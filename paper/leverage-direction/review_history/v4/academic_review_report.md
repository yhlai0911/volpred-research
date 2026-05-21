# Academic Review Report — leverage-direction v4
**Reviewer role**: latex-academic-reviewer (post-v3.1 comprehensive review)
**Date**: 2026-05-21
**Target journal**: Journal of Banking & Finance (JBF)
**Files reviewed**: `paper/leverage-direction/main.tex`, `paper/leverage-direction/body.tex`
**Review basis**: Post-v3.1 state; v3.1 mechanical fixes confirmed

---

## Overall Verdict

**CONDITIONAL — Not ready for submission without targeted fixes**

The paper has made meaningful mechanical progress in v3.1 (t-stat correction, abstract qualifier, HIGH-2 γ_HM disambiguation forward reference, K1092 bibitem removal). However, one SEVERE claim-evidence mismatch in §1 and systematic citation-command inconsistencies must be corrected before submission. No CRITICAL issues remain.

---

## Academic Score

**3.5 / 5★**

- Contribution and framing: strong (4★)
- Methodological rigor: solid (4★)
- Internal consistency and presentation: below submission standard (2.5★) due to issues below
- Referee readiness: borderline — fixable with one targeted revision pass

---

## Summary Table

| ID | Severity | Location | Issue | Status |
|----|----------|----------|-------|--------|
| S-1 | **SEVERE** | body.tex L14, §1 | "all twelve tested assets" — not substantiated (N=5 or N=14) | Must fix |
| S-2 | **SEVERE** | body.tex L470, §5.4 | Spearman ρ=1.000 acknowledged as mechanical but underexplained | Needs explicit hedge |
| H-1 | HIGH | body.tex §4.4.1, L267 | K1092 inline footnote — DCC not primary panel; ES claim still borderline | Acceptable for JBF with current hedge |
| M-1 | MEDIUM | body.tex throughout | ~9 entries cited as plain text, not `\citep{}`/`\citet{}` | Fix all before submission |
| M-2 | MEDIUM | main.tex L29 | `\date{April 2026 (v3 errata)}` — version not updated to v3.1 | Fix |
| M-3 | MEDIUM | main.tex bibliography | Campbell et al. 2017 bibitem non-standard format | Fix |
| M-4 | MEDIUM | body.tex L502 | Section 5.4.1 hardcoded number, not `\ref{}` | Fix |
| Mi-1 | Minor | body.tex throughout | Internal review comments (`% v2-H1:`, `% Codex-R6-fix:`) embedded | Clean before submission |
| Mi-2 | Minor | body.tex L678 | Practical Implementation Summary appendix — appears empty | Verify/fill |
| ✓ | RESOLVED | body.tex L12, 168, 208 | t=-3.79 consistent (3 occurrences); t=-4.71 absent | Confirmed clean |
| ✓ | RESOLVED | main.tex L39 | "(in-sample threshold calibration)" in abstract | Confirmed |
| ✓ | RESOLVED | body.tex L388 | §4.8 → §5.4.5 forward reference with explicit γ_HM disambiguation | Confirmed |
| ✓ | RESOLVED | main.tex bibliography | K1092 bibitem removed | Confirmed |

---

## 6 Focus Area Verification

### Focus 1 — t-stat consistency: t=-3.79 at ALL mentions

**RESOLVED.**

- Line 12 (§1 first contribution): `$t = -3.79$, $p < 0.001$` ✓
- Line 168 (§4.2.1 footnote): `$t=-3.79$ for the difference` ✓
- Line 208 (§4.2.4 body): `$t = -3.79$, $p < 0.001$` ✓
- t=-4.71: absent from entire body.tex ✓

All three occurrences consistent. No residual instances of the old value.

### Focus 2 — Abstract qualifier "(in-sample threshold calibration)"

**RESOLVED.**

Confirmed at main.tex line 39: `(in-sample threshold calibration)` within the abstract text. The qualifier appropriately scopes the VIX regime-split methodology.

### Focus 3 — HIGH-2 status: §4.8 forward reference to §5.4.5 for γ_HM disambiguation

**RESOLVED.**

At body.tex line 388 (§4.8, Formal Market Timing Tests):
> "...indicating no directional timing ability; see Section~\ref{sec:vt_alpha_nature} for disambiguation of all three $\gamma_{HM}$ estimates in this paper."

The disambiguation target (§5.4.4, sec:vt_alpha_nature, line 449) covers all three γ_HM estimates:
1. -0.035 (t=-0.39) — pure-VT full sample (§4.7)
2. -0.068 (t=-4.63) — pure-VT high-VIX subsample
3. -0.043 (t=-4.06) — Hybrid VT full sample

The forward reference is explicit, uses `\ref{}` (not hardcoded number), and the target section provides complete disambiguation. HIGH-2 is fully resolved.

### Focus 4 — HIGH-5 status: ES/FZ subsection acceptability for JBF given K1092 is DCC

**PARTIALLY ACCEPTABLE — borderline HIGH, not blocking.**

At body.tex line 267 (§4.4.1), K1092 is now an inline footnote:
> "K1092: Asset-matched DCC-A4f Fissler--Ziegel evaluation. VolPred Research Program internal experiment record (2026), available in the paper's replication package."

The paper explicitly hedges: "a supplementary DCC evaluation... deferred to replication package supplement." This is transparent. For JBF, the concern is that the primary ES claim rests on the DCC-based experiment rather than the primary panel GJR-GARCH framework. However:
- The hedge is explicit in text
- K1092 is presented as supplementary, not primary evidence
- The primary panel results (Tables 2–4) do not depend on K1092

**Assessment**: A demanding JBF referee may push back on this structure, but it does not constitute a fatal flaw. The current framing is acceptable if authors are prepared to defend the supplementary nature in a response letter.

### Focus 5 — Overall argument coherence

The paper's core argument — that GJR-GARCH γ captures directional volatility asymmetry, gold exhibits regime-dependent γ sign reversals, and VT strategies benefit from this — is coherent and well-supported. The narrative flows from §1 (contributions) through §4 (empirical analysis) to §5 (VT integration). The main coherence issue is the "all twelve" claim in §1 (see S-1 below), which contradicts the data used throughout the paper.

### Focus 6 — New issues introduced by v3.1

v3.1 itself introduced no new substantive issues. However, the review process uncovered two pre-existing issues that must be fixed before submission: the "all twelve" sample-size mismatch (S-1) and systematic plain-text citation usage (M-1).

---

## Issues by Severity

### SEVERE

#### S-1: "all twelve tested assets" claim not substantiated
- **Location**: body.tex line 14, §1 (second contribution bullet)
- **Verbatim**: "universal across all twelve tested assets"
- **Problem**: No analysis in the paper covers exactly twelve assets. The primary analysis uses N=5 assets; the validation/extended analysis uses N=14 assets (mentioned in the abstract: "extended to 26 assets in validation analyses", with ρ=0.83 for "the extended N=14 sample"). Neither N=5 nor N=14 equals "twelve." This is a claim-evidence mismatch that a JBF referee will immediately flag.
- **JBF referee impact**: HIGH — will be flagged as a factual error in the contribution statement; could lead to desk rejection if referee perceives the authors as careless with their own data.
- **Suggested fix**: Change "all twelve tested assets" to either "all five primary assets" or "across the extended N=14 asset validation sample" (whichever the second contribution actually refers to). Cross-check the exact count against Table 2 / validation tables.

#### S-2: Spearman ρ=1.000 under-explained
- **Location**: body.tex line 470 (§5.4)
- **Verbatim**: "Spearman $\rho = 1.000$ ($p < 0.001$) across 7 primary assets"
- **Problem**: ρ=1.000 is a perfect correlation. The paper does acknowledge at line 480 that this is "partly mechanical" (VT MDD is a direct function of volatility level, which γ also captures), but the explanation is brief. A JBF referee will scrutinize this heavily: a ρ of exactly 1.000 across 7 assets could indicate tautology rather than empirical finding. The current hedge ("partly mechanical") is insufficient.
- **JBF referee impact**: HIGH — referees at quantitative finance journals are trained to be suspicious of "too-perfect" results. Without a fuller explanation, this invites a "is this a tautology?" major comment.
- **Suggested fix**: Add 2-3 sentences explaining the exact mechanism that forces the perfect rank-ordering (e.g., is it purely because VT MDD is monotone in vol forecast error, and γ rank-orders vol forecast error?). If it is fully mechanical, acknowledge it explicitly and frame ρ=1.000 as a theoretical relationship being empirically confirmed, not as an independent empirical finding.

---

### HIGH

#### H-1: K1092 ES evidence rests on DCC, not primary panel
- **Location**: body.tex §4.4.1 (line 267), inline footnote
- **Problem**: The ES/FZ (Fissler-Ziegel) cross-asset evidence cited (K1092) uses DCC-A4f, which is a different model from the primary GJR-GARCH panel analyzed throughout the paper. The paper hedges this correctly but briefly.
- **JBF referee impact**: MEDIUM — likely to generate a "show me ES evidence for your primary GJR-GARCH model" comment from a thorough referee. Not a rejection risk on its own given the hedge.
- **Suggested fix**: Either (a) add one sentence explicitly stating "ES properties of the primary GJR-GARCH panel are reported in the replication package Table S3" (if such a table exists), or (b) add a footnote stating this is a known limitation and the DCC-based evidence is directionally consistent but not primary model evidence. The current text is acceptable for submission but authors should be ready to respond.

---

### MEDIUM

#### M-1: Systematic plain-text citations instead of `\cite{}` commands
- **Location**: body.tex throughout
- **Problem**: Approximately 9 bibliography entries are cited in the text as plain text rather than `\citep{}`/`\citet{}` LaTeX commands. Identified instances:
  - `nelson2025` — cited as plain text
  - `hou2020` — cited as plain text (or possibly missing from body entirely)
  - `longin2001` — cited as plain text
  - `bcbs2006`, `bcbs2019` — cited as plain text
  - `xu2024` — cited as plain text
  - `kim2019` — cited as plain text
  - `araya2024` — cited as plain text
  - `parkinson1980` — cited as plain text
- **JBF referee impact**: MEDIUM — while this does not affect scientific content, journal editors will flag un-linked citations. The JBF style guide expects consistent `\cite{}` usage, and missing links break cross-reference integrity checks.
- **Suggested fix**: Global search for all author-year strings in body.tex and ensure each has a corresponding `\cite{}` command. Run `\usepackage{natbib}` compilation to catch undefined citations.

#### M-2: Version date not updated in `\date{}`
- **Location**: main.tex line 29
- **Verbatim**: `\date{April 2026 (v3 errata)}`
- **Problem**: The document is now v3.1 but the date string still says "v3 errata." This is a cosmetic but visible inconsistency — a referee reviewing the PDF will see "v3 errata" which may cause confusion about the current version.
- **Suggested fix**: Change to `\date{April 2026 (v3.1)}` or simply `\date{May 2026}` if the date should be updated as well.

#### M-3: Campbell et al. 2017 bibitem non-standard formatting
- **Location**: main.tex bibliography, `campbell2017` entry
- **Verbatim**: `\bibitem[Campbell et~al., 2017]{campbell2017}` — uses a comma inside the bracket label
- **Problem**: All other bibliography entries in the file use `\bibitem[Author(Year)]{key}` format (parentheses, no comma). The Campbell entry uses `[Author, Year]` (comma). This is a formatting inconsistency that may produce incorrect citation rendering.
- **Suggested fix**: Change to `\bibitem[Campbell et~al.(2017)]{campbell2017}` to match the standard natbib author-year format used by all other entries.

#### M-4: Hardcoded section number at line 502
- **Location**: body.tex line 502
- **Problem**: A reference to §5.4.1 uses a hardcoded section number rather than `\ref{sec:...}`. If section numbering shifts during revision, this reference will silently become wrong.
- **Suggested fix**: Replace hardcoded "5.4.1" with appropriate `\ref{}` label.

---

### Minor

#### Mi-1: Internal review comments in .tex source
- **Location**: body.tex throughout
- **Problem**: Inline LaTeX comments from previous review passes (`% v2-H1:`, `% Codex-R6-fix:`, etc.) remain in the source. These are invisible in the compiled PDF but are visible in the source file. When submitting to JBF (which requires source .tex upload), these internal notes will be visible to editors and referees.
- **Suggested fix**: Global search for `% v2-`, `% Codex-`, and similar internal comment prefixes; remove or consolidate into a separate `review_notes.tex` file not included in submission.

#### Mi-2: Practical Implementation Summary appendix appears empty
- **Location**: body.tex around line 678
- **Problem**: A "Practical Implementation Summary" appendix section label exists but appears to contain no visible body content in the reviewed version.
- **Suggested fix**: Either fill with the intended content (likely a 1-page implementation checklist as described in earlier drafts) or remove the section heading if intentionally omitted. An empty section heading will confuse referees.

---

## v3.1 Fix Verification Summary

| Fix | Expected | Confirmed |
|-----|----------|-----------|
| t=-3.79 at lines 12, 168, 208 | All three match | YES ✓ |
| t=-4.71 removed | Not present | YES ✓ |
| "(in-sample threshold calibration)" in abstract | Present | YES ✓ |
| §4.8 forward reference to §5.4.5 using `\ref{}` | Present with explicit text | YES ✓ |
| §5.4.5 disambiguates all 3 γ_HM estimates | Full coverage | YES ✓ |
| K1092 as inline footnote (not bibliography) | Inline at §4.4.1 | YES ✓ |
| K1092 bibitem removed from bibliography | Absent | YES ✓ |

All v3.1 targeted fixes are correctly implemented.

---

## Pre-Submission Priority List

**Must fix before submission (SEVERE):**
1. Fix "all twelve tested assets" → correct sample count (S-1)
2. Expand ρ=1.000 explanation or reframe as theoretical confirmation (S-2)

**Should fix before submission (MEDIUM):**
3. Convert all plain-text citations to `\citep{}`/`\citet{}` (M-1)
4. Update `\date{}` to v3.1 (M-2)
5. Fix Campbell et al. bibitem format (M-3)
6. Replace hardcoded §5.4.1 with `\ref{}` (M-4)

**Clean up before submission (Minor):**
7. Remove internal review comments (Mi-1)
8. Fill or remove empty appendix (Mi-2)

---

## Recommended Next Version Designation

After fixing S-1, S-2, and M-1 through M-4: tag as **v3.2** and re-run `latex-academic-reviewer` + `citation-verifier` before marking `status=ready_for_submission`.

---

*Review completed: 2026-05-21*
*Reviewer: latex-academic-reviewer (post-v3.1 pass)*
*Next action: Address SEVERE issues S-1 and S-2; convert plain-text citations (M-1)*
