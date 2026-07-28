# K1715 — recertification round 3 (read-only)

**Read this framing before anything else.** The `review_verdict.json` sitting in this experiment
directory is **stale and must not be treated as a prior verdict on these bytes**. It records a
review of commit `70923136` at 2026-07-26T23:39Z and returned FAIL. The code and results were then
changed (`K1715.py` and `K1715_results.json` are both newer than that file). A round-2
recertification job was launched to review the new bytes and was **SIGKILLed before producing
anything**. So: the bytes you are about to review **have never been validly reviewed**. Treat this
as a first review, not an appeal.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/k1715-204d556b/experiments/K1715/`

- `K1715.py` — 64,544 bytes, sha256 `133c6f81bc966241f801e387af75a7fb246d2c5836affb748ab769c3e608a9a3`
- `K1715_results.json` — 498,813 bytes, sha256 `d622e1eba1cd7cb907cb73a51120747eb4af89fc0f796e3f29266947dc0dec17`
- `reproduce_spec.json` — 3,444 bytes, sha256 `6e583d5989028c686b668f35e0a739956bdf250ba3bd1946d7d5f0b5321aeb2e`
- `README.md`, `snapshot_repro_report.md`, `compare_to_archived.py`
- `comparator_closeout_report.json` — the closeout of the snapshot-reproduction gap (see below)
- `K1715_results_archived_929cb150.json` — the artifact the killed round-2 job was to review,
  sha256 `929cb150a4e2ff33883a8e5cbe47de545177f02ee5175387c73b40fb87a4f786`
- prior verdicts: `storage/ops/codex_reviews/k1715_verdict.md`,
  `k1715_attempt3_diag_honesty_verdict.md`

**Confirm the three sha256 values above against disk before you review.** If any differs, stop and
say so in the verdict — the bytes moved under you and nothing else you write is trustworthy.

**Do not modify anything, do not re-run the experiment, do not merge.** Output is the verdict file only.

## What has been closed since the stale verdict (verify, do not assume)

The snapshot-reproduction claim was previously **under-evidenced**: it compared only the 9,176 leaves
present in both the archived and the re-run documents and never accounted for the 1,636 one-sided
leaves. That gap is now closed, and the main thread has checked the arithmetic:

- 9,456 archived leaves / 10,532 new / 9,176 common → 280 archived-only, 1,356 new-only (both
  subtractions verified).
- Every one of those 1,636 one-sided leaves is classified **b (deliberate schema change)**;
  `c_vanished_reported_finding` is **0** in both directions and `category_c_pointers` is empty.
- The 280 archived-only leaves are the pre-rename `nm_to_bfgs_improve`; substituting the new name
  `guarded_polish_gain` finds all 280 present with **bit-identical values** (0 differing, 0 missing).
- `compare_to_archived.py` had a real fail-open defect: exit was `1 if flipped else 0`, computed only
  over shared pointers, so an archived reported finding that **vanished** from the re-run exited 0.
  It now also fails on `dropped_science`. The negative control is real and measured: deleting
  `/summary/verdict` from the new document moves exit 0 → 1; deleting a diagnostic leaf stays green.

**Your job is to audit this, not to accept it.** In particular: is `science()` — now shared between
the tolerance loop and the missing-leaf check — a predicate that actually captures every reported
finding, or can a real claim be classified diagnostic and slip through the exemption list?

## Your job — the substantive recertification

1. **The science itself.** Estimator, specification, lookahead discipline, inference, and whether the
   NULL conclusion follows from the numbers in `K1715_results.json`. Nothing here has been validly
   reviewed; do not economise on this section.
2. **The min-NLL / BFGS guard** introduced in `c9d75cf1d` (`accepted_method`, `accepted_nll`,
   `guarded_polish_gain`). Is the guard correct, and is its choice genuinely auditable from the
   emitted fields rather than asserted?
3. **README and `snapshot_repro_report.md` reconciliation** — every number traced to a pointer in
   `K1715_results.json`, not to prose.
4. **`reproduce_spec.json` provenance.** A prior round faulted this spec for not being a run-time
   product. Judge whether it now is, and whether its `entrypoint` and inputs are pinned to the bytes
   that actually ran.
5. **Known residuals the authors declared** (do not let them pass silently, but weigh them):
   `build_readme.py::_assert_convergence_schema()` has no test; a science pointer that is *new* in
   the re-run is reported but does not fail the gate; two upstream strings (`K1715.py:114` and the
   `reproduce_spec.json comparison.reason` generated from it) still describe the comparator's older,
   narrower exit semantics.

## Output contract

Write the verdict to `storage/ops/codex_reviews/k1715_recert3_verdict.md`.

**First non-empty line must be exactly `VERDICT: PASS` or `VERDICT: FAIL`.** Include a
`reviewed_sha256` block naming the exact bytes you read for `K1715.py`, `K1715_results.json` and
`reproduce_spec.json`. Then, per area (science, guard, reconciliation, spec provenance, comparator
closeout, residuals): `PASS` / `BLOCKING` / `NON_BLOCKING`, with file and line for anything you
fault. If you FAIL, state each blocking defect so it can be fixed without another round of
clarification.
