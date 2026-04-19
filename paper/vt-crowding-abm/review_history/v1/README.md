# Review Round v1 — vt-crowding-abm (Paper 5)

**Date**: 2026-04-18
**Triggered by**: Pre-submission formal review cycle (FRL 15p R3 submission-ready draft; `review_history/` previously empty despite prior informal reviews in `reviews/`).
**Manuscript**: `paper/vt-crowding-abm/main.tex` (current canonical; reproduce verified GREEN 33/33 on 2026-04-19; seed robustness passed)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` (main thread, Claude Opus 4.7 1M)
- `citation-verifier` (main thread, Claude Opus 4.7 1M; integrates prior R3 trail from 2026-04-05)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 3 MED / 4 MINOR; 13/13 content claims verified | ✅ acceptable (3 DOIs to add before submission) |
| Academic | 0 CRITICAL / 0 SEVERE / 4 MAJOR / 7 MED / 6 MINOR; predicted FRL R&R | ★★★★☆ (4.0/5) |

**Joint verdict**: **Revise before submitting**. The paper is substantively strong (novel fixed-liquidity ABM design, clean methodology, honest "quantify vs. discover" framing) but has structural revisions that will materially improve FRL acceptance odds. **Do not submit as-is**.

---

## Issues Summary

### CRITICAL (0) — none

No falsification, fabrication, or submission-blocking errors.

### SEVERE (0) — none

No lookahead bias, identification failure, or methodology gaps. 12/VIX rule explicitly uses $\text{VIX}_{t-1}$; seeds fixed; MC count disclosed.

### MAJOR (4) — blocking FRL competitiveness

| # | Source | Issue | Fix effort |
|---|---|---|---|
| 1 | latex-review MAJOR-1 | **Zero figures** in a tipping-point paper — FRL expects ≥1 figure visualizing the Sharpe-vs-adoption nonlinearity | ~30 min matplotlib |
| 2 | latex-review MAJOR-2 | Eq. (3) "sell pressure $\propto$..." is proportional-only + indexing ambiguity + drops the 1.5 cap | ~15 min rewrite |
| 3 | latex-review MAJOR-3 | **Literature gap**: missing Barroso & Detzel (2021), Cederburg et al. (2020), Liu-Tang-Zhou (2019) — recent papers challenging Moreira & Muir's VT gains. 13 refs is thin for 15p FRL | ~1 hr (read abstracts + 2 sentences + 3 bib entries) |
| 4 | latex-review MAJOR-4 | Four contributions include one scope disclaimer ("quantify vs. discover"). Reframe to 3 substantive contributions; elevate fixed-vs-scaled design validation | ~15 min reframe |

### MEDIUM (10 combined: 3 citation + 7 academic)

Citation (MEDIUM):
- MED-C1: Add DOI to `moreira2017` → `10.1111/jofi.12513`
- MED-C2: Add DOI to `brunnermeier2009` → `10.1093/rfs/hhn098`
- MED-C3: Add DOI to `harvey2016` → `10.1093/rfs/hhv059`

Academic (MEDIUM):
- MED-1: Abstract 254 words — trim OAT detail and "< 5%" sentence
- MED-2: Report MC SE alongside bootstrap CIs in Table 1
- MED-3: Verify narrow kurtosis CI at $\phi$=100% ([59.2, 63.4] for Kurt=61 may be over-confident; check block-bootstrap)
- MED-4: Cross-reference Table 1 footnote (a) from §3.1 text to surface flash-crash measurement artifact
- MED-5: Report $t$-statistic for 50% vs. 70% transition (currently only 10% vs. 50% reported)
- MED-6: Quantify "approximately half" in §4.6 — explicit "0.13 of 0.25 = 52%"
- MED-7: Add fire-sale literature citation (Greenwood & Thesmar 2011 or Coval & Stafford 2007) alongside B-P (2009)

### MINOR (10 combined: 4 citation + 6 academic)

Citation (MINOR):
- MIN-C1: `perchet2016` cite-key vs 2015 display — cosmetic rename
- MIN-C2: `danielsson2012` thematic fit (analytical, not ABM) — rephrase line 56 or replace
- MIN-C3: Kyle page 1315–1335 → 1315–1336 (off-by-one)
- MIN-C4: Add URL to `cole2017` industry report

Academic (MINOR):
- MIN-1: `\and VolPred Research System` in `\author{}` renders awkwardly — move to `\thanks{}`
- MIN-2: Negative number formatting consistency (math-mode vs em-dash)
- MIN-3: "Simplified Kyle (1985) model" → "Kyle-style linear price-impact rule" (more accurate)
- MIN-4: Gloss $\sigma_f$ notation at first use
- MIN-5: §5 Conclusion — replace one numerical restatement with forward-looking sentence
- MIN-6: Consider FRL author-guide on `\doublespacing` preference

---

## Action Plan for v2

**主線程必修 (HIGH priority, must do before submission)**:

1. **Add figure** — 2-panel matplotlib from existing `results/` JSON:
   - Panel (a): Sharpe vs. $\phi$ with bootstrap 95% CI band + threshold annotation
   - Panel (b): Ann. vol + excess kurtosis vs. $\phi$ (dual axes) showing phase transition
   - Save to `paper/vt-crowding-abm/figures/fig1_tipping_point.pdf`
   - `\includegraphics` into §3.1 results.
2. **Formalize Eq. (3)** — replace proportionality with explicit aggregate order flow expression (see latex-review MAJOR-2 for exact wording).
3. **Literature expansion** — add 2-sentence paragraph engaging Barroso & Detzel (2021) + Cederburg et al. (2020); add 3–4 `\bibitem` entries.
4. **Reframe contributions** (line 60) — collapse to 3 (quantitative tipping point / design validation / sensitivity); move "quantify vs. discover" into §2.3.
5. **Citation fixes (MED-C1/C2/C3)** — add 3 DOIs (5-minute edit).

**Deferred to v3 or optional**:

- All 7 academic MED items can be bundled into the same v2 pass (~1 hour additional).
- All 10 MINOR items are optional; address in final proof-reading pass.

**Prediction**: If all 4 MAJOR + 3 MED-C + ≥4 MED (academic) fixed → 4.3★/5 → FRL acceptance probability meaningfully improved. Predicted first-round reviewer verdict: R&R with minor-revisions request (not major).

---

## Files in this round

- `citation_review.md` — citation-verifier output, 13 citations verified, 0 MAJOR / 3 MED / 4 MINOR
- `latex_review.md` — latex-academic-reviewer output, 0 CRITICAL / 0 SEVERE / 4 MAJOR / 7 MED / 6 MINOR, 4.0★/5
- `README.md` — this file

**Live reference**: `paper/vt-crowding-abm/citation_check.md` (symlink/copy of `citation_review.md` for live-reference access; canonical archive is this v1 copy).

---

## Next round trigger

After 主線程完成 v2 修正 (figures + Eq.3 + literature + contributions + 3 DOIs):
- Re-run `latex-academic-reviewer` on updated main.tex → `review_history/v2/latex_review.md`
- Citation-verifier spot-check (verify 3 new Barroso/Cederburg/Liu entries + 3 DOIs) → `review_history/v2/citation_review.md`
- Write `review_history/v2/README.md` with delta vs v1
- If v2 clears all MAJORs and 4.3★+ achieved → green-light submission

**Stage recommendation**: Remain at `review` stage until v2 clears MAJORs. Do NOT promote to `ready_for_submission` yet (current draft would likely return as R&R even if labeled submission-ready).

---

## Previous review trail (context)

This `review_history/v1/` is the first formal `paper-review-cycle` round. Prior informal reviews exist in `paper/vt-crowding-abm/reviews/`:
- `reviews/citation_check.md`, `citation_check_v2.md`, `citation_check_v3.md` (dated 2026-04-05) — all citation-focused; R3 confirmed clean. Their findings are integrated into `citation_review.md` above.
- `reviews/review_v1.tex`, `review_v2.tex`, `review_v3.tex` — earlier latex reviews (2026-04-05); findings superseded by this v1 (current main.tex has evolved since then).
- `reviews/audit_step1_2.md` — step-by-step audit.

These legacy reviews are kept for historical reference but are **not** the canonical review trail going forward. `review_history/v{n}/` is canonical per `paper-review-cycle` SOP.
