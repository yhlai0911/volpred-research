# K1262 Codex Code Review v2 — Primary-Path Re-Verification (FAIL)

**Review date**: 2026-04-29 (CST), task `task-moj6wlga-gaaid4`, 3m 8s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd62e-294d-7ea1-8bbd-6e9f71ff8b97`
**Trigger**: K1262 closure (knowledge entry `f3b9edd4`, confidence 0.88, 2026-04-27)
went through subagent fallback during 4-day Codex CLI blocker (2026-04-26 to
04-28). Per `.claude/rules/experiments.md` hard rule (commit `91317f09`) +
E078 (commit `59d1c096`). 3rd primary-path re-review in 2 days; pattern
established with K1259 v1→v2 (`218f350c` retraction) and K1261 v1→v2
(`b8f1b6fa` retraction). Predicted inheritance: K1261 NEW MAJORs propagate.

**Scope**: K1262 P5 Phase 2 robustness sweep (16,800 sims = TF/MR × scaling
{1,3,5,10} × window {10,22,60} × 7 adoption × 100 MC).

---

## Verdict: **FAIL** (subagent v1 said CONDITIONAL PASS, 0 CRIT / 2 MAJOR
"disclosure gaps only" / H1+ STRONGLY SUPPORTED)

**Findings**: 0 CRITICAL / 0 SEVERE / 4 MAJOR / 1 MED / 0 MINOR

**Comparison vs subagent v1 `f3b9edd4`**: **contradicts**. All 3 K1261
NEW MAJORs propagated, plus K1262-specific calibration overstatement.

---

## MAJOR-1 (PROPAGATED from K1261 v2) — Negative-baseline threshold bug

`experiments/k1262/k1262.py:463` reuses K1261's `(cell_sharpe - base_sharpe) /
abs(base_sharpe)` formula. **23 of 24 sweep cells have negative 10% baseline
Sharpe** → "更負" automatically satisfies `crit_a` regardless of meaningful
collapse. Same logic at `:409` (`detect_threshold_p5_style`).

**Concrete impact on verdict tables**:
- `k1262_threshold_matrix.md:30` onwards: P5-style detector reports `20%`
  threshold for nearly every cell — this is artifact of the bug, not robust
  crowding finding.
- Multiple early thresholds in softer/strict tables also driven by this
  artifact.

**Suggested fix**: handle `base_sharpe <= 0` separately; stop threshold
comparison or use monotone-loss based criterion. Recompute K1262 verdict +
matrix tables after fix.

## MAJOR-2 (PROPAGATED from K1261 v2) — Aggregation NaN/Inf + invalid-cell gate

`experiments/k1262/k1262.py:337` `aggregate_metrics` filters non-finite (good
basic filter) but downstream detectors lack invalid-cell gate. Concrete
example: `experiments/k1262/k1262_results.json:9032` (MR / scaling=3 /
window=10 / 30%) has `ann_return`, `ann_vol`, `max_dd`, `kurtosis`,
`skewness`, `vt_return`, `vt_vol` ALL null + `final_price` ≈ 0 +
`_diagnostics.total_price_clamps = 100`. Despite degenerate, this cell
counted in `k1262_verdict.md:28` "12/12 MR cells reach threshold earlier
than VT".

Multiple similar degenerate cells (Codex flagged "類似退化 cell 不只一個").

**Suggested fix**: aggregation gains `n_valid_core` + `invalid_reason`; threshold/
verdict logic must skip cells where core metrics null OR n_valid below
floor OR collapse/clamp count exceeds threshold. **K1262 Phase 2 verdict
counts must be re-derived after this gate** — current 12/12 may be 8/12 or
fewer if degenerate cells properly excluded.

## MAJOR-3 (PROPAGATED from K1261 v2) — `vt_*` naming for non-VT treatments

`experiments/k1262/k1262.py:292` writes `vt_sharpe`/`vt_return`/`vt_vol` for
TF/MR strategies. Detectors at `:390`, `:430`, `:455` read these fields.
Raw JSON, threshold matrix, verdict all label TF/MR strategy performance as
"vt_*" — provenance mislabel.

**Suggested fix**: rename to `strategy_sharpe`/`strategy_return`/
`strategy_vol`. If backwards compat needed, write legacy alias but switch
detector + markdown reads to `strategy_*`. Re-emit results.json.

## MAJOR-4 (NEW, K1262-specific) — Detector calibration overstated

`experiments/k1262/k1262_verdict.md:12` and `k1262_softer_detector_table.md:23`
claim Phase 2 sweep validates H1+ via softer detector. **But softer detector
gives VT baseline threshold = 100%**, not the paper's 70% claim. Then
`k1262_softer_detector_table.md:23` says "100% in ±20% adoption acceptable
range" — mathematically false (100% is clearly outside 50-90% range that
"±20% from 70%" defines).

`k1262_verdict.md:16` then declares "Phase 2 cross-detector comparisons
valid" and `:52` "H1+ strongly supported".

**Impact**: H1+ strongly supported claim is **doubly compromised** — by
MAJOR-1 (negative-baseline artifact) AND MAJOR-4 (detector calibration
mismatch with paper). The verdict table comparing TF/MR to VT under "softer
detector" is comparing apples-to-oranges if softer detector itself
mis-calibrates the VT baseline.

**Suggested fix**:
- Either prove softer detector self-calibration (VT baseline 70%) or
  switch to a different detector that does calibrate to paper's 70%.
- Recompute Phase 2 sweep verdicts under correctly-calibrated detector.
- If neither works, classify Phase 2 as "detector mismatch / inconclusive"
  pending further calibration work.

## MED — README + verdict.md metadata stale

`experiments/k1262/README.md:3` still says "fallback review 0 CRITICAL, 2
MAJOR, disclosure gaps only" + "H1+ STRONGLY SUPPORTED". This contradicts
current state and will mislead downstream readers (knowledge / paper
narrative).

**Suggested fix**: update README + verdict.md to reflect FAIL verdict +
list 4 MAJORs pending fix. Mark closure as RETRACTED until fixes land.

## Direct answers to inheritance + Phase 2 specific questions

- **Q1 Aggregation NaN/Inf inheritance**: confirmed propagated. K1262
  k1262.py:337 has its own aggregate_metrics (similar pattern to K1261
  pre-fix). Today's K1261 commit `481a22a0` (two-tier counter) does NOT
  apply to K1262 — K1262 has its own copy that needs same fix.
- **Q2 Threshold logic inheritance**: confirmed propagated. Same code
  pattern at `:463`.
- **Q3 vt_* naming inheritance**: confirmed propagated.
- **Q4 Sweep cell collapse**: confirmed multiple degenerate cells exist.
  No invalid-cell gate.
- **Q5 Lookahead audit**: PASS. `returns[t-window:t]` at `:129`, `:151`
  is lag-safe.
- **Q6 RNG draw order**: PASS. Order preserved (VIX noise → noise trader
  → fundamental shock at `:184`, `:230`, `:246`, `:251`).
- **Q7 Soft-detector sensitivity**: FAIL — softer detector itself isn't
  calibrated to VT 70%, see MAJOR-4.
- **Q8 Verdict-vs-data byte-match**: PASS. `k1262_threshold_matrix.md`
  matches `threshold_per_cell`. The bug is in detector logic, not
  transcription.

---

## Next-slot follow-ups required

1. **MAJOR-2 K1262-aggregator fix**: port today's K1261 commit `481a22a0`
   (two-tier finite/total counter) to `experiments/k1262/k1262.py:337`.
   Plus add `invalid_reason` field + downstream gate at detector layer
   (NEW work beyond K1261 fix scope).
2. **MAJOR-1 fix**: same negative-baseline rewrite as K1261 needs.
   Codify: monotone loss-based threshold OR sign-aware comparison.
   Apply BOTH to k1261 and k1262.
3. **MAJOR-3 rename**: `vt_*` → `strategy_*` consistent across K1261, K1262,
   plus any P5 paper citations / tables.
4. **MAJOR-4 detector calibration**: verify softer detector's VT-baseline
   behavior. If 100%, decide: retreat (use harder detector) or document
   "Phase 2 inconclusive pending re-calibration".
5. **Re-run K1262**: 16,800 sims after fixes 1-3 land. ~10 min compute.
6. **Re-derive H1+ Phase 2 verdict**: post fix-1+2, count of "MR vs VT
   earlier threshold" likely changes (degenerate cells excluded). H1+
   strongly supported claim may need to retract or temper.
7. **P5 paper Phase 2 narrative impact**: depending on (6), citations and
   findings may need revision.

## Knowledge entry retraction

Knowledge `f3b9edd4` confidence **0.88 → 0.55 RETRACTED 2026-04-29** —
4 MAJORs caught by primary-path Codex re-review. K1262 closure was
premature; H1+ strongly supported claim NOT currently supportable
without MAJOR-1 + MAJOR-4 fix landing.

This is the **3rd consecutive subagent fallback closure** caught FAIL
by primary-path Codex (after K1259 v1→v2, K1261 v1→v2). E078 prediction
fully validated: same-family LLM blind spots are systematic, not occasional.
