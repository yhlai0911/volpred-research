# K1261 Codex Code Review v2 — Primary-Path Re-Verification (FAIL)

**Review date**: 2026-04-29 (CST), task `task-moj1k5b2-lozeuq`, 2m 29s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd5a5-2953-7300-a21f-8928992489a7`
**Trigger**: K1261 closure (knowledge entry `f1d85a74`, confidence 0.85, 2026-04-27)
went through `feature-dev:code-reviewer` subagent fallback (`a0b2e10e`,
CONDITIONAL PASS, 0 CRIT / 3 MAJOR all already disclosed) because Codex CLI
was blocked at the time. Per `.claude/rules/experiments.md` hard rule
(commit `91317f09`) + `experiment_experiences` E078 (commit `59d1c096`)
— Codex restoration 2026-04-28T21:58 (commits `abc71f9f` / `b3e4ca0a`)
mandates re-review of fallback-gate closures.

**Scope**: K1261 P5 ABM non-VT ablation Phase 1 main (14,000 sims, 4 treatments
× 7 adoption × 500 MC).

---

## Verdict: **FAIL** (subagent v1 said CONDITIONAL PASS)

**Findings**: 0 CRITICAL / 0 SEVERE / 3 MAJOR / 1 MED / 0 MINOR

**Comparison vs subagent v1 `a0b2e10e`**:
- Agree: lookahead protection holds (VT vix[t-1], TF/MR returns[t-N..t-1],
  strategy returns 1-step lag); VT byte-match sanity holds; z-gate
  calibration empirically OK (re-checked 10%/50%/100% gives +1.01 / -1.22 /
  -0.58); no K1262 cross-contamination; no `NotImplementedError` on active
  14,000-sim path.
- **Disagree (subagent v1 MAJOR-1 NotImplementedError)**: subagent counted
  10 stub markers via `grep`, but all are unreachable from active treatment
  factories. Not a closure blocker.
- **Codex caught 3 NEW MAJORs** subagent missed.

---

## NEW MAJOR-1 — Threshold detector negative-baseline counterintuitive logic

`k1261_phase1_main.py:222` declares criteria as "sign-aware: |new| < |base|*0.5
if base>0", but `k1261_phase1_main.py:243` actually computes:
```python
sharpe_drop_pct = (cell['sharpe'] - base_sharpe) / abs(base_sharpe) * 100
cell['crit_a'] = sharpe_drop_pct < -50.0
```
This is **magnitude-aware in absolute terms**, not the documented sign-aware
behavior. For positive baselines it works correctly. **For negative baselines
(TF baseline ~-0.83, MR baseline ~-1.77) any "更負" Sharpe automatically
satisfies `crit_a`** — the "Sharpe dropped >50%" verdict fires when crowding
makes a bad strategy worse, regardless of whether that's a meaningful
"crowding-induced collapse" finding.

**Impact**: TF/MR critical adoption verdicts in `threshold_detection` and
downstream paper narrative may interpret negative-baseline-getting-more-negative
as "crowding triggered collapse" when it's actually "bad strategy continued
being bad in proportion to load size".

**Suggested fix**:
- Either rewrite criteria to be explicitly sign-aware (e.g. only fire crit_a
  when `base_sharpe > 0` and `cell['sharpe'] < base_sharpe * 0.5`); OR
- Recompute threshold_detection on a monotone loss/utility function
  (e.g. drawdown, expected loss); document the redefinition.

**Verified by main thread (2026-04-29)**: code at L243 confirms; L222 string
mismatched.

## NEW MAJOR-2 — `aggregate_metrics` admits NaN/Inf as valid cells

`k1261_non_vt_ablation.py:460` aggregation only excludes `None`, NOT
non-finite (`NaN` / `Inf`) values. `k1261_phase1_main.py:166` pre-flight
gate then sees `n_valid=500` for cells that are actually fully degenerate.
Threshold detector at `k1261_phase1_main.py:187` evaluates non-finite as
`False` — masking real instability as "stable".

**Concrete evidence (verified by main thread 2026-04-29)**:
```bash
jq '.treatments.MR.part1_results."30%" | {ann_return:.ann_return, ann_vol:.ann_vol, kurtosis:.kurtosis, n_valid:.n_valid}'
```
returns:
```json
{
  "ann_return": {"mean": 1.7976931348623157e+308, "median": 1.7976931348623157e+308,
                 "min": 1.7976931348623157e+308, "max": 1.7976931348623157e+308,
                 "std": null, "q5": null, "q95": null, "n_valid": 500},
  "ann_vol":   {"mean": null, "std": null, ..., "n_valid": 500},
  "kurtosis":  {"mean": null, "std": null, ..., "n_valid": 500}
}
```

`1.7976931348623157e+308` = `sys.float_info.max` — this is JSON's
representation of pre-sanitized infinity (likely Python `float('inf')`
clipped by JSON serializer). All 500 simulation runs produced
non-finite values for MR 30%, but `n_valid=500` claims the cell is fully
populated.

**Impact**: P5 paper TF/MR critical-adoption findings may include MR 30%
(and possibly other cells with similar pattern; not yet audited) as
"valid" data points. Threshold detector treats these as `False` →
systematic underestimation of where instability actually starts.

**Suggested fix**:
- Two-tier counter: `n_total` (raw count) vs `n_finite` (after `math.isfinite`
  filter); pre-flight gate uses `n_finite >= 30`.
- Diagnostic flag for cells where `n_finite < 0.8 * n_total` → mark as
  "collapsed" (separate from "valid finding").
- Re-run aggregation on existing 14,000-sim raw data (if available) OR
  re-run K1261 Phase 1 entirely with corrected aggregation.

## NEW MAJOR-3 — `vt_*` field naming for non-VT treatments

`k1261_non_vt_ablation.py:391-410` writes `vt_sharpe`, `vt_return`, `vt_vol`
fields for all treatments including TF, MR, NoiseControl. Verified in
`results.json`:
```bash
jq '.treatments.TF.part1_results."10%" | keys | map(select(test("vt_|sharpe|return"; "i")))'
# → ["ann_return", "vt_return", "vt_sharpe", "vt_vol"]
```

The `vt_sharpe` for TF treatment is the TF strategy's Sharpe, not VT
strategy's. **Provenance mislabel risk** — downstream readers may
compare `vt_sharpe` across treatments thinking it's the same strategy
when it's actually 4 different strategies' Sharpe ratios reused with the
same field name.

**Suggested fix**: Rename `vt_*` → `strategy_*` (or `pop_strategy_*`).
For VT-baseline treatment, additionally provide `vt_*` aliases or a
metadata note. Re-run aggregation OR add a `field_aliases` block to
results.json. Update `k1261_phase1_main.py:137` and any downstream
readers (paper citations, threshold logic).

## MED — NoiseControl breaks cross-treatment common-random-number pairing

`k1261_non_vt_ablation.py:262` and `:282`: NoiseControl introduces extra
RNG draws before fixed noise traders, so it shares only the seed family
with VT/TF/MR but NOT the full draw sequence. `k1261_phase1_verdict.md:102`
claims "cross-treatment seed pairing" — overstated for NoiseControl.

**Impact**: VT byte-match sanity holds (own treatment); VT-vs-TF and
VT-vs-MR pathwise comparisons within a seed are valid. **VT-vs-NoiseControl
pathwise comparisons are not exactly common-random-number** — they only
share the seed value, not the full draw path.

**Suggested fix**: Document in `k1261_phase1_verdict.md` and README that
NoiseControl shares seed family only, not common-random-number sequence.
This affects how to interpret per-seed differences in NoiseControl
comparisons.

---

## Direct answers to original review questions

- **Q1 Lookahead**: PASS. VT uses `vix_series[t-1]` (`k1261_non_vt_ablation.py:135`);
  TF reads `returns[t-N..t-1]` (`:165`); MR same (`:191`); strategy returns lag 1
  step (`:405`).
- **Q2 RNG draw order**: VT fork preserves K827v3; TF/MR add no extra
  draws. NoiseControl exception per MED above.
- **Q3 Strategy abstractions**: base class stub exists but all 4 active
  factories return concrete classes; main path doesn't hit `NotImplementedError`.
- **Q4 Sanity z-gate**: empirically valid at 10%/50%/100% adoption.
- **Q5 Provenance hidden gaps**: MAJOR-3 above.
- **Q6 K1261 vs K1262 boundary**: clean — no robustness sweep results in
  K1261 results.json.
- **Q7 MIN_PAIRS_PER_MODEL**: not applicable to ABM. Only filter is
  `aggregate_metrics` None-exclusion (MAJOR-2 above).

---

## Required next-slot follow-ups

1. **MAJOR-2 fix is most critical** (data integrity, not documentation):
   - MR 30% cell is genuinely degenerate (`ann_return=inf`, `ann_vol=NaN`)
   - Investigate root cause: which of the 500 sims produced inf? Is it
     an MR strategy clamp/divide-by-zero edge case at 30% adoption?
   - Re-run MR 30% (or all cells) with two-tier counter `n_total / n_finite`
2. **MAJOR-1 fix**: rewrite threshold criteria for negative baselines OR
   redefine on monotone loss function. Recompute `threshold_detection` table.
3. **MAJOR-3 fix**: rename `vt_*` → `strategy_*` in results.json + update
   downstream readers (`k1261_phase1_main.py`, paper P5 citations).
4. **MED fix**: document NoiseControl RNG-draw caveat in
   `k1261_phase1_verdict.md`.

## Knowledge entry retraction

Knowledge `f1d85a74` confidence **0.85 → 0.65 RETRACTED 2026-04-29** —
3 NEW MAJORs caught by primary-path Codex re-review imply K1261 closure
was premature. Same K1259 v1→v2 retraction pattern (commit `218f350c`).

Phase 1 P5 paper findings citing K1261 critical-adoption verdicts need
re-examination after MAJOR-1 + MAJOR-2 fixes — current verdict tables
may include sign-confused criteria triggers AND degenerate-cell pass-throughs.
