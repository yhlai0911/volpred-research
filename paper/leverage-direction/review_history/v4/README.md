# Review Round v4 — leverage-direction

**Date**: 2026-05-21
**Triggered by**: Post-v3.1 mechanical fixes — verify all CRITICAL/SEVERE issues resolved + new-issue scan
**Reviewers**:
- `latex-academic-reviewer` (Claude Sonnet 4.6, academic_review_report.md)
- `citation-verifier` (Claude Sonnet 4.6, citation_check_report.md)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | **CONDITIONAL** — 2 SEVERE must fix, then ready | ★★★½ (3.5/5) |
| Citation | **MINOR issues** — 1 MED (Cederburg figure), 3 MINOR | ✅ safe to continue |

**Stage decision**: leverage-direction remains at **review** pending v3.2 targeted fixes.
**v3.1 fixes verified CLEAN**: t=-3.79 consistent at all 3 locations; abstract in-sample qualifier present; HIGH-2 §4.8 forward ref confirmed; k1092 removed from bibliography; §4.9 forward ref to §5.4.5 present.

---

## v3.1 Fixes — All Confirmed Clean ✅

| v3.1 Fix | Status |
|---------|--------|
| t-stat -4.71 → -3.79 (lines 12, 168, 208) | ✅ CONFIRMED |
| Abstract "(in-sample threshold calibration)" qualifier | ✅ CONFIRMED |
| §4.8 forward ref to §5.4.5 γ_HM disambiguation | ✅ CONFIRMED |
| k1092 inline footnote, bibitem removed | ✅ CONFIRMED |
| γ +0.20 vs +0.048 contradiction footnote | ✅ CONFIRMED |

---

## v3.2 Fixes Applied in This Round (2026-05-21)

| Fix | Location | Status |
|-----|---------|--------|
| S-1: "all twelve tested assets" → "all tested assets" | body.tex line 14 | ✅ FIXED |
| S-2: ρ=1.000 mechanism explanation added (3 sentences) | body.tex line 470 | ✅ FIXED |
| MED-1 (citation): Cederburg 4.9% → qualifying footnote | body.tex line 46 | ✅ FIXED |
| M-2: date updated "April 2026 (v3 errata)" → "May 2026 (v3.2)" | main.tex line 29 | ✅ FIXED |
| M-4: "Section~5.4.1" hardcoded → \ref{sec:qlike_ceiling} | body.tex line 502 | ✅ FIXED |
| MIN-1: hou2020 orphan bibitem removed | main.tex line 183 | ✅ FIXED |
| MIN-2: campbell2017 format — comma→paren, "and"→"\&", "~" spacers, DOI added | main.tex line 231 | ✅ FIXED |

---

## Issues Summary

### SEVERE — resolved in this round (v3.2)
1. **S-1 FIXED**: "all twelve tested assets" in MDD universality claim — factual mismatch (N=5 primary, N=14 extended, never N=12 for MDD). Fixed: removed erroneous "twelve" to match abstract/conclusion language.
2. **S-2 FIXED**: Spearman ρ=1.000 underexplained — potential "tautology?" JBF comment. Fixed: added 3-sentence mechanism explanation at §5.4.

### MEDIUM — remaining for v3.2 targeted fix
1. **M-1 PENDING**: ~8 bibliography entries cited as plain text (not \citet{}/\citep{}) — nelson1991, longin2001, bcbs2006/2019, xu2024, kim2019, araya2024, parkinson1980, bozovic2024, cederburg2020, demiguel2024. All have matching \bibitem entries; requires mechanical \citet{}/\citep{} replacement throughout body.tex. JBF will flag inconsistency.
2. **M-3 PENDING**: campbell2017 bibitem format fixed (MIN-2); nelson2025 \bibitem format (comma separator vs standard) — low priority.

### Minor — remaining
- **MIN-3 PENDING**: hood2025 update to final JPM publication (vol/issue/pages + DOI — requires verification against JPM website before updating).
- Internal review comments (`% v2-H1:`, `% Codex-R6-fix:` etc.) in source — purely cosmetic, strip before submission.
- Empty appendix heading at body.tex line 678 — check/fix before submission.

### Citation check
- **MED-1 PARTIALLY ADDRESSED**: Cederburg et al. (2020) "4.9% alpha" moved to footnote with qualifier "their reported specifications"; requires manual verification of exact Table/page reference before submission.
- **32/32 citation keys resolve** — zero dangling \cite{} keys.
- **k1092 CONFIRMED CLEAN** — removed from bibliography, appears only as inline footnote at body.tex:267.

---

## Action Plan for v3.2 (next round)

**主線程必修 before submission:**
1. M-1: Replace ~8 plain text citations with \citet{}/\citep{} commands throughout body.tex
2. MED-1: Verify Cederburg et al. (2020) 4.9% figure against original paper Tables 2–3; update footnote with specific table reference
3. MIN-3: Update hood2025 bibitem with final JPM 51(9) vol/issue/pages + correct DOI (verify at doi.org before changing)
4. Cosmetic: Strip internal % v2-H1 comments; fix empty appendix heading

**Gate for ready_for_submission:**
- Academic ≥ 4★ (currently 3.5★ — M-1 fix + verification → expected 4★+)
- Citation 0 MAJOR (currently 0 MAJOR ✅)
- ≤3 MED (currently 2 MED PENDING — M-1 + MED-1 verification)

**Prediction**: if M-1 + MED-1 verification complete → 4★/5, 0 MAJOR, 0 MED → **ready_for_submission**

---

## Files in This Round
- `citation_check_report.md` — full citation verification results
- `academic_review_report.md` — full academic review with SEVERE/MED/Minor breakdown
- `README.md` (this file)

## Next Round Trigger
After M-1 plain text citation fixes + MED-1 Cederburg verification → new review round v5 → if ≥4★ + 0 MAJOR → stage upgrade to ready_for_submission
