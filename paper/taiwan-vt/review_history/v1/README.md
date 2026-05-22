# Review Round v1 — taiwan-vt

**Date**: 2026-05-23
**Triggered by**: First formal paper-review-cycle pass; previous reviews were manual (review_r1 through review_r4 in `reviews/`). Paper status claimed "0 HIGH / 0 MEDIUM" after May-20 fixes, but pre-submission final pass required.
**Reviewers**:
- citation-verifier (feature-dev:code-reviewer subagent)
- latex-academic-reviewer (feature-dev:code-reviewer subagent)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | CONDITIONAL_PASS — 1 MAJOR (undefined key), 2 MEDIUM, 2 MINOR | ⚠️ |
| Academic | **Major Revision Required** — 2 HIGH (new, not in R1-R4), 6 MEDIUM, 5 MINOR | 3.5★/5 |

**Paper status**: DOWNGRADED from "Minor Revision (0 HIGH)" → **Major Revision Required (2 HIGH)**. Two HIGH-severity issues were found that block reproduction gate and submission. Both issues are new findings not caught in R1-R4.

---

## Issues Summary

### HIGH severity (2) — blocking submission

1. **H1 — Three-way γ inconsistency for 0050.TW** (`body.tex` lines 52, 137, 148, 683)
   - Three distinct values in the same paper: 0.087/2.20 (Table 1 rolling-window), 0.097/3.60 (Section 3.1 narrative, K892 canonical), 0.124/2.46 (Section 8.4, K900 rolling-252d)
   - Table 2 (line 148) source comment points to `paper/taiwan-vt/data/0050_canonical.json` — **file does not exist**
   - K892 experiment confirms canonical: γ=0.097 (n=4,219 full-sample)
   - `gate_fix_v1/gamma_unification_proposal.md` confirms 0.087 is old N120 deprecated run

2. **H2 — ELITE Material (2383.TW) undisclosed in data section** (`body.tex` lines 30-39, 156)
   - Table 2 (line 156) includes 2383.TW with results sourced from `k1302_results.json`
   - Section 2.1 data description (lines 30-39) lists only 9 stocks (2330, 2317, 2454, 2882, 2886, 2891, 2412, 2885, 2881). 2383.TW absent.
   - Undisclosed data source violates PBFJ data transparency standards

### MEDIUM (6)

| ID | Location | Description |
|----|----------|-------------|
| M1 | line 659 | MDD figures (−77.3%/−48.6%) contradict K1175 canonical (−33.8%/−21.2%) |
| M2 | lines 300, 380 | Day-count: 1,549 vs 1,524 vs K900 canonical 1,512 |
| M3 | lines 593-594 | Christoffersen (1998) missing from VaR Trinity text (R4 carry-forward) |
| M4 | lines 501-574 | Section 6 EAV gives equal weight to US/Japan — PBFJ scope risk |
| M5 | line 683 | Section 8.4 K900 rolling-252d γ spec unattributed |
| M6 | lines 274, 593, 636 | VaR 0.5% violation source: GJR+CF vs GJR+Student-t mismatch (8 vs 9 violations) |

### MINOR (7 = 5 academic + 2 citation)

| ID | Location | Description |
|----|----------|-------------|
| mn1 | line 15 | "+0.124 Sharpe" conflates full-period and common-period table |
| mn2 | lines 181, 449 | Dual citation keys for Politis-Romano — citation MAJOR-1 |
| mn3 | line 166 | "9-stock average excl. 2330 & 0056" label ambiguous given H2 |
| mn4 | lines 52, 148 | Tables 1/2 same γ column under different stated methodologies |
| mn5 | lines 655-656 | VIX Step Rule thresholds (15/25) no K-number source |
| C-MINOR-1 | main_v3.tex 104,110,116,146 | `et al.` → `et~al.` in 4 bibitems |
| C-MINOR-2 | — | No DOIs in any bibitem (needed for APA 7th / PBFJ production) |

---

## Action Plan for v2

### Priority 1 — blocking (before reproduce gate)
1. **H1**: Update Table 2 (line 148) γ=0.087/t=2.20 → K892 canonical γ=0.097, verify t-stat from K892/K1302+K1302b; update Table 1 spec note; standardize Section 8.4 (line 683)
2. **H2**: Add ELITE Material (2383.TW) to Section 2.1 with sample period and data source; confirm inclusion/exclusion in "9-stock average"

### Priority 2 — same editorial pass (can do now)
3. **M1**: Update line 659 MDD to K1175 canonical (−33.8% → −21.2%)
4. **M2**: Unify day-count across lines 300 and 380 to K900 canonical (1,512)
5. **M3 / MAJOR citation fix**: Add `\citet{christoffersen1998}` in Section 7.2 + fix `\citep{politis1994stationary}` → `\citep{politis1994}` (body.tex:449)
6. **M6**: Verify K896 JSON — exact violation counts for GJR+Student-t vs GJR+Cornish-Fisher; fix text/comment
7. **Engle page**: `main_v3.tex:93` `987--1007` → `987--1008`
8. **et~al.**: Standardize 4 bibitems in main_v3.tex (lines 104, 110, 116, 146)

### Priority 3 — before submission
9. **M4**: Reframe Section 6 EAV US/Japan as benchmark comparisons; consider moving detailed tables to appendix
10. **M5**: Add K900 rolling-252d attribution to Section 8.4 γ values
11. **mn5**: Add "heuristic for illustration" caveat to VIX Step Rule thresholds

---

## Stage Assessment

Current stage: **revision_required** (downgraded from minor_revision)

Criteria for upgrade to `ready_for_submission`:
- latex ≥ 4★ + citation 0 MAJOR + ≤3 MEDIUM
- After Priority 1-2 fixes: predicted score 4.5★/5, citation 0 MAJOR → `ready_for_submission`

Reproduce gate prediction: after Priority 1-2 fixes → ~85% match rate (from ~73%). ≥95% requires K892 t-stat verification + VIXTWN ratio + TSMC VT + 0056 robustness experiments (per `gate_fix_v1`).

---

## Files in this round

- `citation_check_report.md` — citation-verifier output (CONDITIONAL_PASS)
- `academic_review_report.md` — latex-academic-reviewer output (Major Revision, 3.5★)
- `README.md` — this file

## Next round trigger

After main thread completes v2 fixes (Priority 1-2) → new formal review cycle → `review_history/v2/`

**Cross-reference**: Previous manual reviews in `paper/taiwan-vt/reviews/review_r1.md` through `review_r4.md`. R4 (2026-05-12) claimed 0 HIGH — H1/H2 are new findings from formal review tools.
