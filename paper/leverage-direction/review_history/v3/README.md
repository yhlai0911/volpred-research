# Review Round v3 — leverage-direction

**Date**: 2026-05-21
**Triggered by**: Post-revision review cycle (v3 revision completed 2026-04-20, commit 07967bf7)
**Reviewers**:
- `latex-academic-reviewer` proxy (Claude, academic_review_report.md)
- `citation-verifier` proxy (Claude, citation_check_report.md)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | **NOT ready_for_submission** — 2 CRITICAL + 1 SEVERE blocking | ★★★☆☆ (3/5) |
| Citation | 1 ERROR (k1092 internal record) / 4 MINOR / 2 NEEDS_CHECK | Substantially improved |

**Stage decision**: leverage-direction remains at **review** (NOT promoted to ready_for_submission).

---

## Critical Discovery: body.tex / body_v3.tex Mismatch

**This is the most important finding of the v3 review.** `main.tex` imports `body.tex` via `\input{body}` (line 53), NOT `body_v3.tex`. The v3 revision was applied to `body_v3.tex` only. As a result:

- **HIGH Issue #1** (regime-gamma +0.20 vs +0.048 contradiction) — the fix is in `body_v3.tex` but body.tex still contains the v2 text with the raw contradiction and no explanatory footnote.
- **The corrected t-statistic** (t=-3.79 in body_v3.tex vs t=-4.71 in body.tex) also fails to appear in the compiled paper.
- The compiled paper (`main.tex + body.tex`) therefore still presents readers and referees with the v2 contradiction that was supposed to be resolved.

**Fix**: Either update `body.tex` with the changes from `body_v3.tex`, or update `main.tex` to `\input{body_v3}`. This is a 5-minute mechanical fix, but it must happen before any submission.

---

## Issues Summary

### CRITICAL (2) — must fix immediately

1. **body.tex not updated with v3 revision fixes** — `main.tex` imports `body.tex`, not `body_v3.tex`; HIGH Issue #1 (regime-gamma contradiction) remains unresolved in the compiled paper (body.tex line 208 still reads "+0.20 ... +0.048 (t=-4.71)").

2. **Internal t-statistic inconsistency** — body.tex has `t=-4.71` at lines 12, 168, and 208 for the regime difference; body_v3.tex revised this to `t=-3.79`. If the statistic was recomputed, the compiled paper cites the wrong value. The correct value must be determined and consistently applied.

### SEVERE (2) — blocking submission

3. **Abstract missing "(in-sample)" qualifier on 9/9 claim** — main.tex abstract (line 39) reads "correctly classifying all nine Diebold-Mariano comparisons in the primary sample" without an explicit in-sample qualifier. Body text has the caveat (line 237), abstract does not mirror it. This was listed in the v2 action plan but was not applied to the abstract.

4. **HM γ disambiguation footnote is downstream-only** — The clarifying footnote for the three γ_HM values (-0.035, -0.068, -0.043) appears only in §5.4.4 (body.tex line 448). Section 4.8 (line 388) introduces γ_HM = -0.035 n.s. without a forward reference to the disambiguation. A referee reading Section 4.8 will flag the inconsistency before reaching the footnote.

### MAJOR (2) — should fix before submission

5. **`k1092` internal record cited as bibliography entry** — main.tex bibitem `k1092` ("VolPred Research Program (2026). K1092: Asset-matched DCC-A4f Fissler–Ziegel evaluation. Internal experiment record...") is not a valid JBF reference. Must be moved to a footnote or converted to an SSRN deposit.

6. **ES backtest limited to DCC-GARCH cross-experiment evidence** — The new ES subsection (§4.4.1) cites K1092 (a multi-asset DCC framework experiment), not the primary seven-asset univariate panel. The text honestly flags this as a limitation, but a JBF referee will still note the ES evidence is indirect.

### MEDIUM (3) — improve before submission

7. **Abstract asset class enumeration incomplete** — "seven primary assets (equities, gold, bonds, emerging markets, cryptocurrency)" — SLV (silver) is missing; five classes listed for seven assets.

8. **hood2025 short title** — Bibliography uses "Volatility targeting is trendy." without the full subtitle. APA 7th requires full title.

9. **parkinson1980 uncited orphan** — Still in bibliography but not cited in body.tex (unchanged from v2).

### MINOR (~5)

- `campbell2017` bibitem label style mismatch (unfixed from v2)
- `nelson2025` ambiguity with `nelson1991` (two "Nelson" entries)
- `xu2024` publication status should be re-verified before final submission
- `acerbiszekely2014` missing DOI; page range should be verified
- `engle2004` possible orphan — verify usage in text

---

## v2 Issue Closure Status Table

| Issue | Description | v3 Status | Notes |
|-------|-------------|-----------|-------|
| HIGH-1 | Bear-market gold γ: +0.20 vs +0.048 same-sentence contradiction | **OPEN** | Fix in body_v3.tex only; body.tex (compiled) unchanged |
| HIGH-2 | HM γ_HM: §4.8 t=-0.39 vs §5.4.4 t=-4.06 | **PARTIAL** | Disambiguating footnote added at §5.4.4; §4.8 lacks forward reference |
| HIGH-3 | Proposition 1 statistically fragile | **CLOSED** | Renamed "Empirical Regularity 1" throughout |
| HIGH-4 | Table 3 "9/9 perfect" in-sample qualifier | **PARTIAL** | Body caveat explicit (line 237); abstract qualifier still missing |
| HIGH-5 | Missing ES backtest | **PARTIAL** | ES/FZ subsection added (§4.4.1) but with caveats; K1092 evidence is DCC, not primary panel |
| HIGH-6 | BTC allocation logic conflict | **CLOSED** | Significance-based rule (t>1.65) replaces γ>0.10; BTC correctly prescribed symmetric GARCH |
| HIGH-7 | Citation orphans and missing references | **CLOSED** | 3 orphans removed; engleGhyselsSohn2013 + pattonSheppard2015 added |

**Score**: 2 CLOSED / 2 PARTIAL / 2 OPEN / 1 PARTIAL = effectively 2.5/7 HIGH issues fully resolved in compiled paper (3 additional partial resolutions require follow-up).

---

## Citation Summary (v3 vs v2)

| Category | v2 Count | v3 Count | Change |
|----------|----------|----------|--------|
| Verified | 40 | 46 | +6 new verified |
| Minor issues | 5 | 4 | -1 (xu2024 initial fixed) |
| NEEDS_CHECK | 2 | 2 | Same (nelson2025; acerbiszekely new) |
| ERROR | 0 | 1 | +1 (k1092 internal record) |
| MAJOR | 0 | 0 | — |
| **Total bibitems** | 47 | 57 | +10 |

---

## Joint Verdict

**HOLD** — Do NOT promote to ready_for_submission.

**Reasoning**:
1. The compilation error (body.tex not updated) means the paper as currently compiled still contains the v2 regime-gamma contradiction that was the most severe CRITICAL-HIGH finding in v2. This alone blocks submission.
2. The t-statistic discrepancy (t=-4.71 in body.tex vs t=-3.79 in body_v3.tex) requires reconciliation — one value is wrong.
3. The abstract still lacks the explicit in-sample qualifier on the 9/9 claim.
4. The `k1092` bibliography entry is not JBF-acceptable.

**What needs to happen before v4 review**:
1. Sync body.tex with body_v3.tex (port all three line changes) — or change `\input{body}` to `\input{body_v3}` in main.tex
2. Confirm the correct t-statistic (-4.71 or -3.79) via K1198 reconciliation and apply consistently
3. Add "(in-sample threshold calibration)" qualifier to abstract's 9/9 clause
4. Convert `k1092` bibitem to footnote, or deposit on SSRN
5. Add forward reference to disambiguation footnote from §4.8

**Estimated time to fix**: 1–2 hours for the mechanical fixes (items 1–5 above). Once fixed, the paper would have 5/7 HIGH issues fully resolved and the remaining 2 (HIGH-2 HM footnote placement, HIGH-5 ES evidence scope) as defensible PARTIAL resolutions.

**Prediction for v4**: If the mechanical fixes above are applied cleanly, the paper should score ★★★★/5 and be ready for JBF submission with a realistic R&R outcome.

---

## Files in this round

- `citation_check_report.md` — citation-verifier proxy full output
- `academic_review_report.md` — latex-academic-reviewer proxy full output
- `README.md` — this file (summary + closure table + verdict)

## Next round trigger

- After porting body_v3.tex fixes to body.tex (or `\input{body_v3}`)
- After reconciling t-statistic (-4.71 vs -3.79) with K1198 data
- After abstract in-sample qualifier added
- Run new citation-verifier + latex-academic-reviewer → write `review_history/v4/`
- Target: 0 CRITICAL, 0 SEVERE, ≤2 MEDIUM → PROMOTE to ready_for_submission
