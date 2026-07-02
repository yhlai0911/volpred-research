# Leverage-direction — Option A honest-null reframe: A-tick-2 COMPLETE (2026-07-03 ~03:xx 台灣時間)

Owner directive: email-12500 (2026-07-02) — Option A = downshift to "method diagnosis + honest null result", target IJF methods track / FRL.

## What A-tick-1 (prior fire, commit bc0630965) did
- Reframed title / abstract / highlights + all claim-bearing prose in `body_v_ijf.tex`
  to method-diagnosis + honest null.
- Title now neutral question; abstract states "The answer is largely no."; highlights all null.

## What A-tick-2 (this fire, hourly-03) did — header reconciliation + codex-verified residual removal

**Round 1 — residual over-claim in section headers + loose wording (4 edits):**
1. §5.2 header `Conditional Gains from Asymmetric Measurement` → `No Robust Out-of-Sample Superiority`
   (was a positive header over a section that concludes no significant OOS superiority).
2. L298 `the forecast-level gains of §5.2 survive` → `the apparent forecast-level gains ... survive`
   (mirror the established "apparent gains ... do not survive" framing).
3. L319 `the forecast-level gains documented above` → `the forecast-level results documented above`.
4. §6.1 header `The Complexity Ceiling: Synthesis` → `Synthesis: Three Independent Views of the Null`
   (demote branded "complexity ceiling" from headline; body keeps the honest "ceiling" metaphor).
   RETAINED intentionally (neutral / already-demoted): §5.3 header "Allocation-Level Results:
   The Measurement-to-Allocation Wedge" (wedge = the null mechanism) and §5.4 "Interpretive
   Taxonomy: Where the Ceiling Binds" (explicitly interpretive/supporting role).

**Round 2 — codex exec adversarial review (read-only) verdict NEEDS_FIX → all 5 fixed:**
1. L291 "for SPY, GJR wins significantly in both periods" → "unadjusted period-by-period DM tests
   favor GJR ... though this apparent edge does not survive the multiple-testing correction applied below".
2. L291 BTC "a significant γ is necessary for GJR to plausibly help, but not sufficient" →
   "a significant γ is not sufficient for out-of-sample superiority ...".
3. L176 (intro) "it predicts whether VT behaves as trend-following or contrarian" → "it is associated with ...".
4. L314 "predicts the 2018–2026 OOS coefficient ..., ruling out a purely mechanical artifact" →
   "remains positively associated with ..., making a purely same-sample artifact less likely,
   though the evidence remains underpowered".
5. `tables_main.tex` L44 Table 3 caption: "percentage improvement of GJR over GARCH. * denotes DM
   significance at 5%" → "percentage QLIKE difference for GJR relative to GARCH; ... Stars denote
   unadjusted 5% DM tests and do not imply Harvey-corrected selected-model superiority".

Codex explicitly did NOT flag the already-negated honest phrases (e.g. "apparent gains ... do not
survive", "rarely significantly worse", the COVID-only "earn its keep") and confirmed the front
matter / highlights are consistent with the honest-null framing.

## Verification
- `xelatex main_v_ijf.tex` × 2 passes: exit 0 / exit 0, **36 pp**, no undefined refs/citations, no LaTeX error.
- Final grep: no residual positive-wedge prose (only a reframe-documentation comment at L123 and the
  honest-null negation at L172 remain, both correct).
- Manuscript body is now fully consistent with the honest-null title / abstract / highlights.

## Remaining downstream (SEPARATE from this paper_body task — do NOT block on them here)
1. **Next gate = fresh full multi-round review** (latex-academic-reviewer + citation-verifier +
   journal-review via `codex exec`, per boss rule) of the reframed honest-null manuscript, since the
   prior IJF review FAILED on the old positive-wedge prose. Queued as follow-up task.
2. **title_page_v_ijf.tex AI-disclosure** conflicts with boss "禁 AI/LLM 提及" but journals may
   REQUIRE AI disclosure → POLICY, needs boss sign-off. NOT auto-changed.
3. **Manuscript convergence / stale-publish guard**: `papers.py` paper-update sees only the JBF-era
   `main.tex` (not `main_v_ijf.tex`); do NOT run `paper-update --paper-id leverage-direction` until a
   `do_not_publish` schema guard exists (see canonical_state_findings_20260702.md §2). Paper stays gated.

_Author: hourly-03 autonomous fire. Body reframe done + codex-verified; paper remains gated pending review + owner submission decision._
