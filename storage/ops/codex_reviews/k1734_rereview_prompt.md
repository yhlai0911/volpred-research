# K1734 — primary-path re-review, ALL FIVE dimensions (read-only)

**Do not treat this as a narrow follow-up.** Your previous verdict on this experiment stopped after
reporting a single blocking defect (the workspace was read-only, by its own account), so **four of
the five review dimensions were never covered**: lookahead, leakage, statistics, honesty beyond that
one item, and `verdict_supported`. Run all five from scratch on the corrected artifact.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-1e5922b4-k1734/experiments/K1734/`

- `k1734.py` — 52,830 bytes, sha256 `ff7e5a65702a24ab56222b5315cf6be5551a75c5c4b2eb4a9dde383ba070af39`
- `k1734_results.json`, `reproduce_spec.json`, `README.md`
- `k1734_h1_gate_fix_report.json` — the authors' account of this round's change
- your prior verdict under `storage/ops/codex_reviews/`

**Confirm that sha256 against disk before reviewing.** If it differs, stop and say so — the bytes
moved and nothing else you write is trustworthy.

**Do not modify anything, do not re-run the experiment, do not merge.** Output is the verdict file only.

## What changed this round (verify; do not assume)

The blocking defect was that H1 is a **compound** hypothesis — a static limb and a dynamic
"amplifies faster under stress" limb — but the accept gate only tested the static limb while the
prose claimed both. The authors took **route A**: they actually tested the second limb rather than
deleting the claim.

Main thread has already checked, and you should challenge if you disagree:

- **Three-way byte identity**: on-disk `k1734.py` == `results.code_trace` == `reproduce_spec.entrypoint`
  == `ff7e5a65…`, 52,830 B, from one run-time `finalize_experiment()` snapshot.
- **The new test reuses the file's existing design, unchanged**: `bootstrap_ci_paired`, seed 42,
  5,000 reps, circular block length 21, the same `_circular_indices` and `_summarize_boot` as the
  skew and semivariance legs; `VIX_STRESS = 20.0` on `vix_lag1`, `changed_for_this_fix: false`.
  The only difference from `bootstrap_ci` is joint row resampling of (return, stress flag).
- **The result is a NULL and is reported as one**: `verdicts.H1_accept` true → **false**; new fields
  `H1a_static_left_tail_accept: true` and `H1b_stress_amplification_accept: false`; the overall
  string was made limb-aware (`STATIC_LEFT_TAIL_ASYMMETRY_CONFIRMED_STRESS_AMPLIFICATION_NULL_…`)
  rather than collapsing to a blanket NULL that would have been wrong in the other direction.
  README §H1 states gap +0.050, CI [−0.165, +0.264], p 0.692, 0.46 bootstrap SD from zero.
- **BH-FDR family grew 8 → 9** with `H1_ampgap_cew` (a verdict-gating test must sit inside
  multiplicity control). New member does not reject (adj p 0.77895); all previously surviving
  members still survive; the conservative doubled-CW combination moves to **0.0451 vs 0.05** — a
  thin margin the authors recorded in README rather than omitting.

## Your job — all five dimensions

1. **Lookahead** — every signal, threshold and regime label. `vix_lag1` in particular: is the stress
   flag genuinely known at the open of day t everywhere it is used, including inside the paired
   bootstrap?
2. **Leakage** — train/test and in-sample/OOS boundaries, especially around the H3 CW comparison.
3. **Statistics** — is `bootstrap_ci_paired` correct for this null? Both ES amplification factors are
   asserted positive because each side's two ES share a sign; check that this holds rather than
   being assumed. Is the BH-FDR family the right family, and is the conservative CW doubling applied
   the way README claims?
4. **Honesty** — does any surviving prose anywhere in `k1734.py`, `README.md` or the results JSON
   still assert stress amplification, or assert anything the tests do not support? The authors kept
   the claim and tested it; verify the claim as stated now matches what was measured.
5. **`verdict_supported`** — does the new limb-aware overall string follow from the numbers, and does
   the branch logic produce a correct string for the other branches too, not just this one?

## Output contract

Write the verdict to `storage/ops/codex_reviews/k1734_rereview_verdict.md`.

**First non-empty line must be exactly `VERDICT: PASS` or `VERDICT: FAIL`.** Include a
`reviewed_sha256` block for `k1734.py`. Then report **each of the five dimensions explicitly** as
`PASS` / `BLOCKING` / `NON_BLOCKING` — a dimension you did not cover must be named as uncovered
rather than left out. Give file and line for anything you fault. If you FAIL, state each blocking
defect so it can be fixed without another round of clarification.
