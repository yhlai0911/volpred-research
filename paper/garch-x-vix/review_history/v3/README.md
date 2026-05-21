# Paper 9 (garch-x-vix) — Review History v3

**Date**: 2026-05-19
**Round**: v3 — LaTeX Academic Review + Citation Verification (integrating v2 adversarial findings)

---

## Stage Assessment

**Current stage**: `review` → recommend downgrade to `revision_required`

The paper requires substantive revisions before top-tier submission. Three SERIOUS FLAWs from v2 adversarial review are confirmed and corroborated by v3 LaTeX analysis.

---

## What Was Reviewed

| Component | Tool | Output |
|-----------|------|--------|
| LaTeX structure, equations, notation, logical flow | latex-academic-reviewer | `latex_academic_review_v3.md` |
| Bibliography entries, DOI verification, content-fidelity | citation-verifier | `citation_review_v3.md` |
| Cross-review integration + priority ranking | Consolidation | `consolidated_issues_v3.md` |

Prior round incorporated:
- v1 (2026-04-13): LaTeX + Citation review — all 10 issues resolved by 2026-04-18
- v2 (2026-05-19): Codex adversarial review — 3 SERIOUS FLAWS identified

---

## v3 New Findings Summary

### LaTeX Academic Review — Issue Counts

| Severity | Count | Key Issues |
|----------|-------|-----------|
| HIGH | 3 | (1) A4f free-ω vs Proposition 2 constrained-ω contradiction; (2) COVID 7-period claim without table; (3) QLIKE scaling across tables (subsumed in MEDIUM) |
| MEDIUM | 10 | Scaling footnote placement, equation labels, VaR pass criterion definition, Proposition 3 formal status, Table 2 Harvey label ambiguity |
| LOW | 8 | xeCJK build failure, fontspec note, GLD DM t discrepancy (3.17 vs 3.39), missing A4f in VRP table, Proposition 1 triviality |

### Citation Review — Issue Counts

| Severity | Count | Key Issues |
|----------|-------|-----------|
| MAJOR | 0 | (v1 MAJOR fixed) |
| MEDIUM | 2 | Harvey (2016) cross-sectional context misapplication; DM 1995 vs 2002 preference |
| LOW | 3 | Bollerslev scope, GW window W missing, Acerbi 2014→2019 upgrade |

---

## Relationship to v2 Adversarial SERIOUS FLAWS

| v2 SERIOUS FLAW | v3 Corroboration |
|----------------|-----------------|
| SF1: COVID dominance — no leave-COVID-out analysis | LaTeX-HIGH2: the 7-period robustness claim is stated in prose with no table. Confirmed missing. |
| SF2: MCS indistinguishability — "GARCH-MIDAS unnecessary" overstated | LaTeX review confirms the abstract and conclusion language remains overstated. Confirmed not yet fixed. |
| SF3: 17-spec horse race without spec genealogy | Citation-MEDIUM-V3-1: Harvey (2016) citation context is wrong for time-series context. Confirmed gap. |

All three SERIOUS FLAWs are confirmed unresolved in the current manuscript version.

---

## Consolidated Top-5 Priority Items

1. **[CRITICAL] COVID subperiod analysis** (C1): Run leave-COVID-out DM test; add Table A1 with pre/COVID/post-COVID breakdown. Experiment K_NEW_A.
2. **[CRITICAL] Reframe main claim** (C2): Change "GARCH-MIDAS unnecessary" → "statistically indistinguishable from best MIDAS at lower parameter cost." Abstract + conclusion + intro Finding 4.
3. **[CRITICAL] Spec genealogy + White RC/SPA** (C3): Add Appendix B documenting ex-ante vs ex-post specs; run SPA test. Experiment K_NEW_C. Add `white2000` citation.
4. **[HIGH] HAR-RV benchmark** (C4): Add HAR-RV and HAR-RV-VIX to Table 2 horse race. Experiment K_NEW_B.
5. **[HIGH] Proposition 2 structural coherence** (C5): Clarify that VRP identification applies to constrained model only; add A4f's VRP correlation to Table 3.

---

## New Experiments to Queue

| K ID | Description | Priority |
|------|-------------|---------|
| K_NEW_A | Leave-COVID-out DM test | P1 CRITICAL |
| K_NEW_B | HAR-RV + HAR-RV-VIX horse race | P1 HIGH |
| K_NEW_C | White RC / SPA on 17-spec horse race | P1 HIGH |
| K_NEW_D | COVID × refit-freq sensitivity interaction | P2 MEDIUM |
| K_NEW_E | VRP mechanical component simulation | P2 MEDIUM |

---

## File Inventory

| File | Description |
|------|-------------|
| `README.md` | This file — round summary |
| `latex_academic_review_v3.md` | Full LaTeX structure, notation, flow review |
| `citation_review_v3.md` | Full bibliography re-audit + content fidelity |
| `consolidated_issues_v3.md` | Cross-review priority-sorted master issue list |

---

## Next Steps

1. Queue K_NEW_A (leave-COVID-out) as next experiment — this is the most likely R1 reject reason
2. Reframe main claim in abstract/conclusion/intro (no experiments needed, writing only)
3. Add `white2000` to bibliography and update Harvey (2016) citation context
4. After K_NEW_A, K_NEW_B, K_NEW_C complete: reassess whether paper can move to `ready` stage
5. Run v4 review cycle after revisions are made

**Estimated time to submission-ready**: 3-5 weeks (assuming 5 new experiments + 2 weeks writing)
