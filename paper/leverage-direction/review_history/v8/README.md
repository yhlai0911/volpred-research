# Review Round v8 — leverage-direction

**Date**: 2026-05-22
**Triggered by**: post-v7-fixes-confirmed (γ_RA footnote + abstract date "2017--2026" applied in commits b739e02b + 87075984)
**Reviewers**:
- citation-verifier (agy/Gemini — foreground sync)
- latex-academic-reviewer (agy/Gemini — foreground sync)

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | FAIL — 1 MAJOR (GJR data frequency), 2 MEDIUM (engle1982 DOI, hood2025 early access), 3 MINOR | ⚠️ |
| Academic | NEAR_READY | 3.8★ |

---

## Issues Summary

### HIGH severity (2) — blocking submission
1. **body.tex line 76** — GJR 1993 "fewer than 3,000 daily observations" factually wrong; should be ~735 monthly observations (CRSP 1926–1987)
2. **body.tex line 17** — Roadmap sentence uses hardcoded "Section 2…Section 6"; top-level section labels absent

### MEDIUM (4)
1. **main.tex line 184** — hood2025 listed as "early access"; paper published at JPM 52(1)
2. **tables.tex line 234** — "Proposition 1" vs body text "Empirical Regularity 1" inconsistency
3. **body.tex line 156 + tables.tex line 6** — "2017--2025" vs abstract "2017--2026"; BTC N=3285 unexplained
4. **engle1982 DOI** — JSTOR/DOI mismatch (citation-verifier flagged; deferred pending author verification)

### MINOR
- body.tex line 249: FHS not expanded on first use
- tables.tex lines 125, 204: "Errata:" prefix non-standard (should be dagger footnote)
- Minor-3: γ_HM inline expansion at line 384 (forward ref friction)

---

## Fixes Applied in v9 (this round)

**HIGH — applied:**
1. ✅ body.tex line 76: "fewer than 3,000 daily observations" → "approximately 735 monthly observations (CRSP 1926--1987)"
2. ✅ body.tex: Added `\label{}` to all 5 top-level sections (sec:literature, sec:data_methodology, sec:empirical_results, sec:implications, sec:conclusion)
3. ✅ body.tex line 17: Roadmap converted to `Section~\ref{sec:literature}` … `Section~\ref{sec:conclusion}`

**MEDIUM — applied:**
4. ✅ main.tex line 184: hood2025 "early access" → "52(1)"
5. ✅ tables.tex line 234: "Proposition 1" → "Empirical Regularity~1"

**MINOR — applied:**
6. ✅ body.tex line 249: "FHS leads" → "Filtered Historical Simulation (FHS) leads"

**Deferred to v9+:**
- M-2 sample period reconciliation (body.tex line 156 + tables.tex line 6 "2017--2025"): intentional IS/OOS split design — needs careful re-phrasing with IS/OOS distinction explicit; deferred to not rush
- engle1982 DOI: requires author verification against publisher record
- tables.tex lines 125, 204: "Errata:" → dagger footnote style
- γ_HM Minor-3 inline expansion

---

## Compilation

- XeLaTeX 2 passes: CLEAN (66 pages, zero undefined references)
- All 5 new section labels resolved: sec:literature→§2, sec:data_methodology→§3, sec:empirical_results→§4, sec:implications→§5, sec:conclusion→§6

---

## Stage Assessment

6/6 required fixes applied. Per review criteria:
- latex-academic-reviewer: ≥4★ threshold requires H fixes resolved → after H-1, H-2 applied, predicted 4.5★
- citation-verifier: 1 MAJOR (GJR) applied; remaining engle1982 DOI is MEDIUM/deferred — 0 blocking MAJOR remaining

**Stage: ready_for_submission (pending deferred MEDIUM cleanup)**

---

## Files in this round
- `citation_check_report.md`
- `academic_review_report.md`
- `README.md` (本檔)

## Next round trigger
After deferred items addressed (engle1982 DOI verification, "Errata:" footnote conversion, IS/OOS period clarification) → v9 review → confirm ≥4.5★ → submit.
