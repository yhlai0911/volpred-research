# K1262b Codex Code Review v2 — Primary-Path Re-Verification (FAIL)

**Review date**: 2026-04-29 (CST), task `task-mojah650-m0h9ls`, 3m 24s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd689-b1cb-7be0-a7b7-1e9e8fbcd0b1`
**Trigger**: K1262b closure (knowledge entry `81ebfe54`, confidence 0.85, 2026-04-27)
went through subagent fallback during 4-day Codex CLI blocker. Per
`.claude/rules/experiments.md` hard rule + E078 systematic re-review plan.

**Scope**: K1262b P5 OAT λ/γ sensitivity sweep (5 cells × 4 treatments × 4
adoption × 200 MC = 16,000 sims).

**4th consecutive P5-family closure subjected to primary-path Codex review.
Pattern of subagent fallback FAIL does not break.**

---

## Verdict: **FAIL** (subagent v1 said CONDITIONAL PASS, "fully rebutted knife-edge")

**Findings**: 0 CRITICAL / 0 SEVERE / 4 MAJOR / 1 MED / 1 MINOR

**Comparison vs subagent v1 `81ebfe54`**: **contradicts**. K1261 NEW MAJORs
propagate; K1262 inheritance issues replicated; PLUS K1262b-specific
overclaim problem.

---

## MAJOR-1 (PROPAGATED) — Negative-baseline threshold turns failure into "support"

`experiments/k1262b/k1262b.py:467` reuses `(new-base) / abs(base) * 100`
formula. `:852` hard-codes `ALREADY_CROWDED_THRESH = -0.5` and treats `null`
as H1+ support. Verdict at `k1262b_verdict.md:11, :25` reclassifies
`cell3_lambda_high / MR / null` as support — that's a detector failure
being labeled as evidence.

**Suggested fix**: when baseline Sharpe at detector anchor is non-positive,
mark detector as uninformative for that cell; do NOT count it as evidence
for `TF/MR ≤ VT`.

## MAJOR-2 (PROPAGATED) — Aggregation/stability replicated

`experiments/k1262b/k1262b.py:429` has its own copy of `aggregate_metrics`
(NOT imported). Same failure mode: keeps every finite value, reports
`n_valid=200` even when process is repeatedly hitting price floor.

**Concrete evidence** (Codex flagged with line numbers):
- `k1262b_results.json:3582` `cell3_lambda_high / MR / 30%`: absurd
  annualized means
- `:3654`: final_price ≈ 0.0101 (effectively at the 0.01 floor)
- `:3661`: **21,812 price clamps** while keeping all 200 runs "valid"
- Same pattern at lines 3404, 3489, 3746, 3831

**Suggested fix**: treat floor-hit/collapse paths as separate failure
regime, block from ordinary robustness evidence. Apply two-tier counter
fix consistent with K1261 commit 481a22a0.

## MAJOR-3 (PROPAGATED) — `vt_*` field naming for non-VT treatments

`experiments/k1262b/k1262b.py:388` writes `vt_sharpe`/`vt_return`/`vt_vol`
for VT_baseline AND for TF/MR using `strategy_weight_history`, AND for
non-VT treatment comparisons. Same `vt_*` semantics drift.

## MAJOR-4 (NEW, K1262b-specific) — Robustness claim materially overstated

`README.md:3, :17` and `k1262b_verdict.md:13, :43` claim K1262b "fully
rebutted knife-edge critique" / "confirmed robust". **NOT supportable**
because:
- One cell rescued by negative-baseline detector bug (MAJOR-1)
- Multiple TF/MR cells in floor-hit collapse regime (MAJOR-2)

**Suggested fix**: retract robustness claim; current state is at best
"inconclusive pending sign-aware detector repair + collapse-aware
aggregation".

## MED — K827v3 byte-match calibration NOT preserved

`experiments/k1262b/k1262b.py:48` comments baseline cell "NOT seed-equal
to K1262". `:532` adds `lambda_idx/gamma_idx` offsets to every run.
Baseline 70% match is fresh deterministic replication, not byte-match
continuation. If calibration is meant to inherit K827v3/K1262 exactly,
keep baseline cell on original seed path and branch perturbation cells
separately.

## MINOR — README sim count internal inconsistency

`README.md:42` says 3 adoption levels / 12,000 sims; code and results
use 4 adoption levels / 16,000 sims; `:106` repeats the 12,000 figure.

---

## Pattern observation: 4 consecutive same-family FAIL

| K | Subagent v1 verdict | Codex v2 verdict | Inheritance |
|---|---|---|---|
| K1259 | PASS-with-caveats / 3 MAJOR | FAIL / 2 NEW MAJOR | Audit method blind spots |
| K1261 | CONDITIONAL PASS | FAIL / 3 NEW MAJOR | Negative-baseline + NaN/Inf + vt_* |
| K1262 | CONDITIONAL PASS | FAIL / 4 MAJOR | All 3 K1261 MAJORs + calibration overclaim |
| K1262b | CONDITIONAL PASS | FAIL / 4 MAJOR + 1 MED + 1 MINOR | All 3 + robustness overclaim |

Hit rate: 4/4 = 100% subagent fallback closures missed substantive issues
that primary-path Codex caught. E078 "Cross-model review NOT optional"
is no longer a hypothesis; it's the verified pattern.

**P5 paper Phase 2 narrative collapse**:
- K1261 H1+ Phase 1 critical-adoption: bugged threshold + degenerate cells
- K1262 H1+ Phase 2 sweep: bugged threshold (23/24 cells negative baseline)
  + degenerate cells + softer-detector calibration mismatch
- K1262b "knife-edge fully rebutted": one OAT cell rescued by bug + multiple
  collapse-regime cells

All 3 P5-supporting K-experiments now FAIL primary-path verification.
"H1+ STRONGLY SUPPORTED" claim cannot be sustained without major fixes.

---

## Knowledge entry retraction

Knowledge `81ebfe54` confidence **0.85 → 0.55 RETRACTED 2026-04-29**.

## Pending fixes (subsequent slots)

1. **MAJOR-1 fix coordinated across K1261/K1262/K1262b**: rewrite negative-
   baseline threshold logic. Apply uniformly.
2. **MAJOR-2 fix in K1262b**: port two-tier counter to `k1262b.py:429`
   (similar to K1261 commit 481a22a0). Plus add invalid-cell gate at
   detector layer (also pending for K1262).
3. **MAJOR-3 rename across K1261/K1262/K1262b**: `vt_*` → `strategy_*` +
   downstream readers + P5 paper citations.
4. **MAJOR-4 retract**: README.md + verdict.md update to reflect
   inconclusive-pending-fix state.
5. **Re-run K1262b 16,000 sims** after fixes 1-3 land; re-derive OAT
   robustness verdict.
6. **MED**: fix K827v3 byte-match for baseline cell (or document
   non-byte-match status explicitly).
7. **MINOR**: README sim count consistency.
8. **P5 paper stage decision** (separate slot): with all 3 supporting
   K-experiments retracted, evaluate whether `ready_for_submission` stage
   downgrade to `review` is warranted pending fix completion.
