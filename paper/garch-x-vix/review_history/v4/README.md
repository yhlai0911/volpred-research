# Paper 9 (garch-x-vix) — Review History v4

**Date**: 2026-05-22
**Round**: v4 — Applying v3 CRITICAL fixes C1 + C3

---

## What Was Fixed

### C1 — COVID Robustness Table (RESOLVED)

**Status**: ✅ Applied — K1393 leave-COVID-out OOS results added to paper

**Changes made**:
- Added narrative paragraph after the 7-period 2-year window analysis (Section 5.1)
- Added Table `tab:covid_robust` showing DM tests by OOS sub-sample:

| Sub-sample | n | DM t | Harvey sig |
|-----------|---|------|-----------|
| Non-COVID (excl 2020-02-01 to 2020-06-30) | 1,721 | **4.26** | **Yes** |
| Pre-COVID (2019) | 273 | 2.52 | No (n<300) |
| COVID window (2020-02 to 06) | 104 | 1.48 | No (n<300) |
| Post-COVID (2021–2026-04) | 1,448 | 3.76 | Yes |

**Source**: `experiments/K1393/k1393_results.json`

**Key finding**: Non-COVID DM t=4.26 EXCEEDS the full-OOS primary result (t=4.03), confirming the advantage is a persistent normal-market phenomenon.

---

### C3 — Spec Genealogy / Multiple-Testing Disclosure (RESOLVED)

**Status**: ✅ Applied — Appendix A added

**Changes made**:
- Added `\appendix` section: "Specification Genealogy and Multiple-Testing Disclosure"
- Added Table `tab:spec_genealogy` documenting ex-ante design rationale for all 17 specs
- Confirmed: ALL 17 specs are ex-ante theory-driven; no data mining
- Multiple-testing footnote: Harvey (2016) |t|>3.0 ≈ Bonferroni z_{0.05/(2×16)} ≈ 2.95
- MCS (Hansen et al. 2011) reference for complementary test

---

## Remaining Open Issues from v3

### C2 — Main Claim Overstatement
**Status**: ✅ Already resolved in previous edits
- Paper uses "parsimonious alternative statistically indistinguishable from the best GARCH-MIDAS alternative" language throughout
- No "unnecessary" language found

### C4 — HAR-RV Benchmark Missing
**Status**: OPEN — acknowledged in limitations section but not added as comparison spec

### C5 — A4f free-ω vs Proposition 2 constrained-ω contradiction  
**Status**: OPEN — requires careful narrative fix in Section 5.3 (Propositions)

### Lower-priority items (C6–C17)
See `v3/consolidated_issues_v3.md` for full list.

---

## Compilation

- XeLaTeX 2 passes: CLEAN (43 pages, zero fatal errors)
- Pre-existing undefined citations: acerbi2019, corsi2009 (not from v4 changes)
- New cross-references resolved: tab:covid_robust, tab:spec_genealogy, app:spec_genealogy

---

## Stage Assessment

**Current stage**: `revision_required` (unchanged from v3)
**Next priority**: C5 (A4f free-ω vs Proposition 2 contradiction) + C4 (HAR-RV benchmark)
