# Review Round v5 — leverage-direction

**Date**: 2026-05-21
**Triggered by**: v4 MEDIUM M-1 citation fix — systematic plain-text → `\citet{}/\citep{}` conversion
**Status**: COMPLETE — v5 academic + citation review run; fixes applied

---

## v3.3 Fixes Applied (Earlier This Session)

All M-1 plain-text citations converted to `\citet{}/\citep{}` commands throughout body.tex (27 entries). Main.tex `\date{}` updated to "May 2026 (v3.3)".

---

## v5 Fixes Applied (This Round, 2026-05-21)

| Fix | Files | Details |
|-----|-------|---------|
| H-1: 3 residual plain-text citations missed in v3.3 | body.tex | L112: `\citep{diebold1995}`; L585: `\citet{patton2011}`; L609: `\citet{hood2025}` |
| M-2: K-codes removed from table notes | tables.tex | K1186, K1206, K1187, K1198 removed from rendered text; substantive content preserved |

---

## Review Results

### Citation Check — CONDITIONAL_PASS

| Issue | Severity | Status |
|-------|----------|--------|
| H-1: 3 residual plain-text citations | MAJOR | RESOLVED in v5 |
| M-2: K-codes in table notes | MAJOR | RESOLVED in v5 |
| campbell2017 DOI (possible digit error `44`→`43`?) | FLAGGED | Needs manual doi.org verification |
| MED-1: Cederburg et al. 4.9% attribution | MEDIUM | OPEN — requires journal access |
| MIN-3: hood2025 "early access" | MINOR | OPEN — update to Vol 52(1), p.100 |

### Academic Review — 4.0/5★, Minor Revision

| Issue | Severity | Status |
|-------|----------|--------|
| H-2: ρ=1.000 circularity defense (missing OOS sentence) | HIGH | OPEN |
| M-1: Hardcoded Table/Section numbers (5 locations) | MEDIUM | OPEN |
| M-3: MCS citation year (hansen2005 vs. hansen2011?) | MEDIUM | OPEN |
| min-1: Internal `% H6 response:` comment at body.tex:68 | MINOR | OPEN |
| min-2: Engle (1982) ARCH citation missing | MINOR | OPEN |
| min-3: VT weight σ_hat_t annualization not stated | MINOR | OPEN |

---

## Gate for ready_for_submission

| Condition | Status |
|-----------|--------|
| Academic ≥ 4★ | ✅ PASS — 4.0/5★ |
| Citation 0 MAJOR | ⚠️ CONDITIONAL — campbell2017 DOI manual check needed |
| ≤ 1 MED remaining | ❌ FAIL — 3 open (H-2 ρ defense, M-1 refs, M-3 MCS) |

**NOT READY for submission.**

### v6 Required Fixes (P1 — blocking)

1. body.tex ~462: Add temporal-separation sentence to ρ=1.000 paragraph  
2. body.tex ~165/175/215/287: Replace hardcoded `Table N` → `\ref{}`  
3. body.tex ~146: Replace `Section 5.1` → `\ref{}`  
4. Verify MCS citation: `hansen2005` → confirm is `hansen2011`?  
5. Verify campbell2017 DOI: `104.00000044` vs `104.00000043` at doi.org  

### v6 Required Fixes (P2 — pre-submission)

- Update hood2025 bibitem: Vol 52(1), p.100, full title  
- Resolve MED-1 Cederburg 4.9% (journal access required)

---

## Files in This Round

- `citation_check_report.md`
- `academic_review_report.md`
- `README.md` (this file)

## Next Round Trigger

After main thread v6 P1 fixes → new cycle → `review_history/v6/`
