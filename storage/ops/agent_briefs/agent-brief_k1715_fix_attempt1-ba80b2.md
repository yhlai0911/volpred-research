# K1715 fix (attempt 1 / re-dispatch after Codex FAIL) — earn a defensible NULL

**Model**: claude-opus-4-8 / max (per model_router experiment attempt=1, at ceiling)

## Context
Score-driven (GAS/DCS Beta-t-EGARCH) direct joint VaR+ES vs GARCH family. Codex primary-path
review returned **VERDICT: FAIL** (reviewed commit 87f2fec59). The implementation is **leak-free**
and both GARCH/GJR baselines are genuinely estimated — the failure is entirely in **reporting
honesty + convergence evidence**, not in the research design. Your job is to make the reported NULL
*defensible*, NOT to manufacture a positive result. A correctly-reported NULL is a full success.

Work IN the existing worktree `.claude/worktrees/k1715-204d556b` (branch already carries K1715).
Read the full verdict first: `storage/ops/codex_reviews/k1715_verdict.md`.

## The 4 blocking defects (fix every one; each must be verifiable in the JSON+README diff)

1. **README numbers contradict the JSON.** README.md:129 claims every Kupiec/Christoffersen CC
   result has p<0.01, but K1715_results.json:3712,3722 report GJR-t 5% p=0.01310 and p_cc=0.04126.
   README.md:11 says all four 1% violation rates are ≈1.87×, but JSON:3634-3636 gives GJR-t
   66/4164 = 1.585×. → Regenerate every human-facing number in README directly from the JSON
   (script the extraction so they cannot drift again). Report the actual per-model rates and p-values.

2. **Convergence is claimed but unproven — optimizer_success_rate=0 for all four models**
   (JSON:1240,2432,3624,4816). K1715.py:279-314 accepts any finite failed-BFGS result without
   retaining the gradient norm, optimizer message, Nelder-Mead vs BFGS objective change, or
   multistart dispersion; the boundary check covers only persistence and ν, not GJR α (α≈0 while
   boundary_rate stays 0). → Capture and PERSIST per-model convergence diagnostics: final gradient
   norm, optimizer termination message, objective-value change across the multistart set, and
   multistart parameter dispersion; extend the boundary check to GJR α. Re-run so
   optimizer_success_rate reflects reality. **If BFGS genuinely does not converge, report that
   honestly as a limitation — do NOT claim "convergence verified".** The NULL can stand on honest
   diagnostics; it cannot stand on a false convergence claim.

3. **False arch cross-check agreement.** README.md:105-107,147-155 and JSON:41 claim arch agrees to
   3-4 sig figs, but JSON:5049-5100 shows GJR ω≈9.5%, γ≈10.9%, ν≈8.8%, GARCH ω≈5.6% differences,
   and arch validates ONLY the baselines, not the GAS models. → Restate the cross-check honestly:
   report the actual discrepancies and scope the claim to "baseline sanity check, GAS not
   externally validated".

4. **Unidentified causal attribution.** README.md:11-13,160-163 and JSON:5161 attribute
   undercoverage specifically to Student-t + one-step lag rather than recursion. Shared failure
   across four models does not identify that cause without an alternative distribution/timing
   design. → Either add an identifying arm (alternative distribution OR alternative timing) OR
   restate as "shared undercoverage across all four models; the mechanism (distribution vs lag vs
   recursion) is NOT identified by this design." No human-facing overclaim.

## Deliverables
- Fixed `experiments/K1715/K1715_results.json` (re-run, honest convergence diagnostics) and
  `experiments/K1715/README.md` (every number sourced from the JSON; no overclaims).
- Keep lookahead-clean discipline (the existing .shift-based state assignment is correct — do not break it).
- Then obtain a fresh review: run the primary-path Codex review; if Codex times out, a fresh-context
  Claude code-reviewer verdict is the K1259-accepted fallback. Write `experiments/K1715/review_verdict.json`
  (verdict-template schema) bound to the new reviewed bytes with sha256, reviewer, reviewed_commit.
- Do NOT write knowledge.json (main thread does that on collection, per K1259).

## Success criterion
`experiments/K1715/K1715_results.json` regenerated with honest convergence diagnostics, README
numbers matching the JSON exactly, arch claim scoped to baselines, causal claim de-identified, and a
fresh review_verdict.json present. A defensible NULL is the target — not a positive result.
