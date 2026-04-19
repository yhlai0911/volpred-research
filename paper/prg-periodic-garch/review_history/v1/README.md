# Review Round v1 — prg-periodic-garch (Paper 6)

**Date**: 2026-04-19
**Triggered by**: First formal `paper-review-cycle` round. Paper 6 is near-submission-ready (R2 SEVERE=0; reproduce gate GREEN 15/15; 3 fixes completed 2026-04-19: L84 Patton attribution, L268 Acerbi bibitem, reproduce.py bug fix). `review_history/` was previously empty despite prior informal reviews in `reviews/`.
**Manuscript**: `paper/prg-periodic-garch/main.tex` (14 pages, 19 bibitems; commit `a3b751` post-2026-04-19 fixes)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` (main thread, Claude Opus 4.7 1M)
- `citation-verifier` (main thread, Claude Opus 4.7 1M; integrates prior 2026-04-05 R1 citation_check.md)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 15 ✓ / 3 ⚠ / 1 ✗ (Lai 2024 DOI missing); 0 MAJOR / 1 MED / 3 MINOR | ✅ acceptable (1 MED must-fix before submission) |
| Academic | 0 CRITICAL / 0 SEVERE / 2 MAJOR / 6 MED / 7 MINOR; predicted FRL R&R | ★★★★☆ (4.2/5) |

**Joint verdict**: **Revise before submitting.** The paper is technically sound, reproduce-verified (15/15 GREEN), and the 2 MAJORs are about reviewer-defense posture rather than substance. The minimum-viable submission path is ~3–4 hours of focused work on MAJOR-1 Fix B + MAJOR-2 Fix A (or Fix B) + all MEDs + 1 MED-citation (Lai 2024 DOI). Do **not** submit as-is.

---

## Issues Summary

### CRITICAL (0) — none

No falsification, fabrication, submission-blocking errors, or reproducibility failures. Reproduce gate is GREEN 15/15 (100% match vs paper claims).

### SEVERE (0) — none

No lookahead bias (explicit two-phase protocol §2.2 L111–126 defends timing), no identification failure (ablation Table 3 delivers clean causal identification of the session-boundary bridge mechanism: $t=6.00 \to -0.57$ swing), no methodology gap.

### MAJOR (2) — blocking FRL competitiveness

| # | Source | Issue | Fix effort |
|---|---|---|---|
| 1 | latex-review MAJOR-1 | **No GJR-X benchmark** — cannot isolate whether PRG's edge over GJR is the overnight information or the periodic recursion. An FRL econometrics reviewer will flag this. | Fix B ~30 min (literature defense) / Fix A ~1 day (add GJR-X benchmark on SPY) |
| 2 | latex-review MAJOR-2 | **VT economic significance is TAIFEX-only**; six-market statistical story lacks economic replication. Transaction-cost impact also not quantified. | Fix B ~15 min (sentence) / Fix A ~2–3 hours (add SPY row to Table 4 + turnover-adjusted Sharpe) |

### MEDIUM (6 academic + 1 citation = 7 combined)

Academic (MEDIUM):
- MED-A1: Ablation should cover 2+ markets (currently SPY-only) — run on TAIFEX, add sentence to §4.2 (~2 hrs)
- MED-A2: Harvey (2016) threshold borrowed from asset pricing; add one-sentence justification at §2.4 L136 (~5 min)
- MED-A3: Abstract DM-$t$ range formatting ("ranging from 4.26 to 6.63") rephrase to "4.26–6.63 (all six markets above threshold)" (~2 min)
- MED-A4: Persistence notation $\rho_s$ is defined for Extended; add one sentence at Eq. (6) noting Basic case $(\alpha_0+\beta_0)(\alpha_1+\beta_1)<1$ (~3 min)
- MED-A5: Forecast-timing paragraph (§2.2 L111–126) is the key novelty defense; add one-sentence practitioner-interpretation coda (~5 min)
- MED-A6: §5 limitations paragraph should include mitigation clauses for each limitation (~15 min)

Citation (MEDIUM):
- MED-C1 (ERR-C1): **Add Lai (2024) DOI** `https://doi.org/10.1007/s10690-023-09415-w` (NOT `-09424-9`) to bibitem L392–396. Author's own prior PRS paper self-citation must carry DOI. (~2 min, **MUST DO**)

### MINOR (7 academic + 3 citation = 10 combined)

Academic (MINOR):
- MIN-A1: `\usepackage[utf8]{inputenc}` + `\usepackage{mathptmx}` — verify compiled PDF uses Times in math
- MIN-A2: `colorlinks=true` with blue — switch to black before submission (FRL preference)
- MIN-A3: `\thanks` block acknowledging "VolPred Research System" — consider removing or rephrasing
- MIN-A4: Bibliography order is chronological-by-inclusion, not alphabetical (inconsistent with `\bibliographystyle{apalike}`)
- MIN-A5: `\rho_0 \cdot \rho_1` (L102) vs `\rho_0 \rho_1` (L107) — unify multiplication notation
- MIN-A6: Caption (L183) could be more informative
- MIN-A7: "$\Delta t = 6.57\sigma$" (L226) — consider rephrasing to avoid $\sigma$-as-volatility confusion

Citation (MINOR):
- MIN-C1: DOIs recommended for 12+ bibitems (~30 min batch edit)
- MIN-C2: Author name "Chicheportiche" confirmed correct — no action
- MIN-C3: Bibitem ordering (see MIN-A4)

---

## Action Plan for v2

**主線程必修 (HIGH priority, MUST do before submission)**:

1. **ERR-C1 (citation MED)**: Add Lai (2024) DOI `10.1007/s10690-023-09415-w` to bibitem L392–396. (~2 min, BLOCKING — author's own paper must have DOI)
2. **MAJOR-1**: Rewrite §5 L310 limitation #3 from "we do not compare PRG against GJR-X" (passive) to a literature-supported claim citing Todorova2014 + Opschoor2021 (Fix B, ~30 min). OR add GJR-X benchmark on SPY to Table 2 (Fix A, ~1 day). Minimum: Fix B.
3. **MAJOR-2**: Add SPY row to Table 4 VT strategy (~2–3 hours) OR add sentence noting multi-market extension in footnote (~15 min). ALSO: report turnover-adjusted Sharpe in Table 4 footnote (~15 min regardless).
4. **MED-A1 through MED-A6**: ~30 min total polish pass.
5. **MED-C1**: covered by item 1.

**SHOULD DO before submission**:

6. **MIN-C1**: Batch-add DOIs to 12+ bibitems (~30 min).
7. **MIN-A4 / MIN-C3**: Reorder bibitems alphabetically (~15 min).

**Deferred / optional to v3 or proof stage**:

- MIN-A1 through MIN-A7 (excluding MIN-A4): final proof-reading pass.

---

## Prediction

| Scenario | Rating | FRL first-round outcome distribution |
|---|---|---|
| All MAJORs Fix A + all MEDs fixed + DOIs added | ★★★★½ (4.5/5) | Accept ~25% / R&R ~65% / Reject ~10% |
| All MAJORs Fix B + all MEDs fixed + DOIs added | ★★★★¼ (4.3/5) | Accept ~15% / R&R ~70% / Reject ~15% |
| As-is (no further fixes) | ★★★★ (4.2/5) | Accept ~10% / R&R ~60% / Reject ~30% |

**Submission recommendation**: **Revise before submitting.** The paper is technically sound and reproduce-verified; the cost of ~3–4 hours of fixes yields materially better submission posture. Do not submit as-is — not because the paper is weak (it isn't), but because the ROI of the revision pass is overwhelmingly favorable.

---

## Files in this round

- `latex_review.md` — latex-academic-reviewer output: 0 CRITICAL / 0 SEVERE / 2 MAJOR / 6 MED / 7 MINOR; 4.2★/5
- `citation_review.md` — citation-verifier output: 15 ✓ / 3 ⚠ / 1 ✗; 0 MAJOR / 1 MED / 3 MINOR; supersedes 2026-04-05 R1 citation_check.md
- `README.md` — this round summary

**Live reference** for main-thread revision work: `paper/prg-periodic-garch/citation_check.md` (canonical archive copy is in this v1 directory).

---

## Previous review trail (context)

This `review_history/v1/` is the first formal `paper-review-cycle` round. Prior informal / single-agent reviews exist in `paper/prg-periodic-garch/reviews/`:
- `reviews/citation_check_v1.md` (2026-04-05) — 19-citation R1 review. Findings integrated into `citation_review.md` above; 3 ✗ errors flagged by R1 (Lai 2024 bibitem, Patton–Hansen attribution L84, Duan 1995 smearing) are **all now resolved** in current main.tex (2026-04-19 fixes + Duan removal).
- `reviews/review_v1.tex` / `review_v1.pdf` / `review_v1.1.tex` / `review_v1.1.pdf` — earlier latex reviews (2026-04-05); findings superseded by current review_history/v1/latex_review.md (main.tex has evolved since then: L84 + L268 fixes landed 2026-04-19).
- `reviews/review_v2.tex` / `review_v2.pdf` — supplementary round (2026-04-05).

These legacy reviews are kept for historical reference but are **not** the canonical review trail going forward. `review_history/v{n}/` is canonical per `paper-review-cycle` SOP.

---

## Next round trigger

After main thread completes v2 revisions (Lai DOI + MAJOR-1 Fix B + MAJOR-2 Fix A/B + 6 MEDs):

- Re-run `latex-academic-reviewer` on updated main.tex → `review_history/v2/latex_review.md`
- `citation-verifier` spot-check (verify Lai DOI added + any new citations for MAJOR-1 Fix B) → `review_history/v2/citation_review.md`
- Write `review_history/v2/README.md` with delta vs v1
- If v2 clears both MAJORs and rating reaches 4.3★+ → green-light for FRL submission

**Stage recommendation**: Remain at `review` stage until v2 clears 2 MAJORs and the Lai (2024) DOI is added. **Do NOT promote to `ready_for_submission` yet** — current manuscript would most likely return from FRL as R&R requiring the exact same fixes enumerated here, and it is cheaper to ship those fixes preemptively.
