# Codex round-4 PRIMARY-PATH review — K1708 §14 new-caliber gate certification

You are the **deciding primary-path reviewer** for experiment K1708 (state-space vs HAR
realized-volatility forecasting). This is round 4. **You are NOT a fallback / shallow
reviewer** — do a full, adversarial read of the code and numbers. Your verdict is the gate
that decides whether this NULL result may be merged and written to the knowledge base.

Working tree under review (read-only sandbox):
`.claude/worktrees/dispatch-slot-1-457427c2-k1708/experiments/k1708/`

Read at minimum:
- `.claude/worktrees/dispatch-slot-1-457427c2-k1708/experiments/k1708/K1708_stage2_summary.json` (the triage deliverable / self-assessment)
- `.claude/worktrees/dispatch-slot-1-457427c2-k1708/experiments/k1708/K1708_results.json` (the payload; the actual numbers)
- `.claude/worktrees/dispatch-slot-1-457427c2-k1708/experiments/k1708/K1708.py` (esp. `derive_verdict`, `legacy_derive_verdict`, gate construction, the `.shift(1)` regressor alignment, and the new-caliber field computation)
- the K1708 test files in that dir (the 4 tests the summary says were "reconciled")

## The study conclusion under review
`study_conclusion = "NULL -- state-space did not beat HAR"`. Max Clark-West t vs own
restriction = 1.97, below the pre-registered t>=3.0 bar. The self-assessment claims all 4
blockers CLOSED and `anomaly_flag=false`.

## What you must independently verify (do not trust the summary's labels)

1. **Three new-caliber fields are genuine and still NULL.** Recompute / trace, at least by
   sanity-checking, `cw_vs_own_restriction_primary`, `cw_holm_family`, and
   `regime_qlike_vs_own_restriction` in `K1708_results.json`. Confirm every model's CW
   t-stat vs its OWN restriction is < 3.0, Holm rejects none at alpha 0.05, and the regime
   QLIKE sign-consistency conjunct fails. Confirm `overall_gate_verdict.label == "NULL"`
   with a coherent `why`. If any number looks internally inconsistent or the gate could be
   read as PASS, that is a FAIL — chase the anomaly, do not wave it through.

2. **All 4 blockers actually CLOSED**, checked against the real code path
   (`derive_verdict` vs `legacy_derive_verdict`), not the summary's prose:
   - BLOCKER-1 gate tightness now provable / new-caliber gate evaluated on real data.
   - BLOCKER-2 verdict recomputes registry control identity + Holm from real numbers
     (does not blindly trust payload labels; a relabelled control cannot force a pass).
   - BLOCKER-3 provenance = code sha256 pin + git-diffable before/after.
   - BLOCKER-4 the gate tests discriminate old-vs-new logic (would go red under pre-fix
     logic), not merely assert names/booleans.

3. **The 4 "reconciled" tests were strengthened, not loosened.** The summary claims each
   post-rerun test is strictly stronger / more discriminating and that no gate threshold was
   loosened and no number fabricated, and that `K1708.py` was NOT touched (to preserve the
   code_trace sha256 pin). Verify this: read the test diffs' intent — did any test get
   weakened or made to pass by assertion-gutting rather than by asserting the true
   post-rerun reality? Confirm `K1708.py` is unchanged relative to the sha pin claim.

4. **Lookahead discipline.** Confirm regressors are `.shift(1)` (row t uses info <= t-1),
   target is contemporaneous, baseline and treatment share one design matrix (identical lag
   convention), and hyperparameters use data < origin only. Any lookahead = FAIL.

## Known, disclosed caveats (do NOT treat as new defects unless you find them substantive)
- No fresh 41-min rerun was performed; the existing 2026-07-22 provenance-clean rerun
  (input data sha 50c4f615, 3552 raw rows, seed 42, quick_mode=false) is being certified.
  The gitignored input has since drifted (~3556 rows) so byte-identical reproduction is no
  longer possible, though reproducible-in-principle from the sha-pinned code + that snapshot.
- Under the WITHDRAWN legacy 1.645 bar a weak positive signal (HAR_KF_MLE t=1.97) would
  pass; it does not survive the stricter pre-registered bar. This is disclosed as
  transparency, not an anomaly.
Judge whether these caveats undermine the NULL certification. If certifying an
already-existing provenance-clean rerun (rather than re-running) is defensible, say so.

## Output contract
Write your review to the verdict file. **The first non-empty line must be exactly one of:**
- `VERDICT: PASS`
- `VERDICT: FAIL`

Then give numbered reasons tied to the four checks above (cite line numbers / field values).
PASS means: NULL is correct, all 4 blockers genuinely closed, tests strengthened not
loosened, no lookahead, provenance sound → safe to merge and record as a NULL finding.
FAIL means any check does not hold; state precisely which and why. Do not hedge to a
"conditional" — this gate is binary.
