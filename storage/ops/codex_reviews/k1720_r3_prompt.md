# K1720 — Codex round 3 review (rev3, read-only)

You reviewed rev2 and returned **FAIL**. Your round-2 verdict judged **R2, R3, R4 RESOLVED**, and
also passed **lookahead discipline**, the **rev1→rev2 numeric deltas**, and the **NULL decision
tree**. Two findings were left `NOT_RESOLVED`: **R1** and **R5**. The authors ran a bounded
remediation limited to exactly those two. This is round 3: decide whether rev3 is certifiable.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/`

- `K1720.py` (75,440 bytes, sha256 `1f614c1ad984d87b5efdc1864b143cded43bb95119e74c30751c7cc0bbb9285f`)
- `K1720_results.json` — canonical numbers
- `k1720_rev3_report.json` — the authors' own account of this round's two fixes
- `README.md`, `reproduce_spec.json`
- your round-2 verdict: `storage/ops/codex_reviews/k1720_r2_verdict.md`

**Do not modify anything, do not re-run the experiment, do not merge.** Output is the verdict file only.

## Already verified by the main thread (do not re-spend effort, but challenge if you disagree)

- **Three-way byte identity**: `reproduce_spec.entrypoint.sha256` == `K1720_results.code_trace.sha256`
  == on-disk `K1720.py` == `1f614c1a…`, 75,440 B. Recomputed from disk, not read from a summary.
- **R5 sweep**: `format_sample_scale()` (K1720.py:556) is the single run-time producer, and
  `decide_verdict()` interpolates it as `{scale}` into the rationale (K1720.py:914+). Every surviving
  `~2 years` / `~3 years` / `~500 sessions` string in `K1720.py` and `README.md` sits in ledger or
  quotation context (module docstring rev2/rev3 notes, `remediation[].codex_finding`,
  `format_sample_scale`'s own docstring, README §6/§7 explaining the defect). Current value:
  `2.90 years / 719 analysis sessions per complex`.
- **R1 rule semantics**: `LAST_BAR_START_BY_OFFICIAL_CLOSE = {(16,0):(15,30), (13,0):(11,30)}` and
  `close_observed` requires `last_bar_start == expected` for *that date's* official close from
  `exchange_calendars` XNYS 4.13.2 (XNAS agreement asserted at run time). All 7 official early closes
  in window validated with observed last bar 11:30. Both disagreement sets between the rev2 and rev3
  rules (`accepted_by_rev2_rejected_by_rev3`, `accepted_by_rev3_rejected_by_rev2`) are **empty** on
  this fixed cache, and the authors reported that explicitly rather than passing silently.
- **Sample reconciliation**: 730 calendar − 10 non-7-bar = 720 full − 0 dropped for own close
  unobserved − 1 dropped for missing prev_close (`2023-08-28`) = **719** analysis sessions. Matches
  `sample_provenance` for both QQQ and SPY.
- **Nothing moved**: `numbers_moved.full_depth_diff.numeric_leaves_changed = 0` (exact equality,
  rtol=0/atol=0, against the frozen rev2 snapshot); verdict rev2 NULL → rev3 NULL.

## Your job

### 1. R1 — adjudicate the fix, not just the outcome
Your round-2 finding was that the 11:30 whitelist was never checked against the official half-day
calendar, so a normal trading day whose feed truncates after 11:30 would still be accepted as an
observed close. Confirm in the code that:
- the calendar source is genuinely consulted per date (not a hard-coded date list masquerading as a
  calendar lookup), and the hard-coded verification table is a *cross-check* of the library, not the
  operative source;
- a session whose final bar starts 11:30 on a **16:00-close** date is now classified close-unobserved
  and actually removed from the analysis sample — trace the path, don't take the field name for it;
- the **symmetric leg** the authors added (dropping a 7-bar session whose *own* close was not
  observed at its official time, not only the prev_close side) is correctly wired into the sample
  reconciliation above;
- `2026-01-30` (2 bars, last bar 10:30, official close 16:00) is handled by the intended branch.

The empty disagreement sets mean this round changed no number. **That is the expected outcome and is
not by itself a defect** — but it does mean R1 can only be certified by reading the rule, not by
reading the deltas. Say explicitly whether you accept the rule as sound for a *future* cache.

### 2. R5 — confirm the single-producer property actually holds
Check that no prose statement of sample scale anywhere in the artifact bypasses
`format_sample_scale()`. Include the limitations block and the verdict rationale. If you find any
sample-scale claim built from a literal, that is a blocking defect.

### 3. Scope discipline — did the remediation stay inside its bounds?
The authors claim no estimator, specification, threshold, event definition, bandwidth rule,
bootstrap, multiplicity correction or decision-tree branch was modified, and that the only additions
are diagnostics (`n_fields_added = 138`, `numeric_leaves_changed = 0`, `fields_removed = []`).
Verify the field additions really are diagnostics. A silent specification change hidden among 138 new
fields is the failure mode to hunt for here.

### 4. Confirmatory recheck (do not re-litigate, but do not rubber-stamp)
Re-confirm on the rev3 bytes that (a) lookahead discipline still holds — in particular the
`.shift(1)`-lagged expanding top-decile event threshold and the prev-session close resolution, and
(b) `verdict_supported`: the NULL verdict still follows from the decision tree given the numbers now
in `K1720_results.json`.

## Output contract

Write the verdict to `storage/ops/codex_reviews/k1720_r3_verdict.md`.

**First non-empty line must be exactly `VERDICT: PASS` or `VERDICT: FAIL`.** Then, per finding
(R1, R5, scope, lookahead, verdict_supported): `RESOLVED` / `NOT_RESOLVED` / `NEW_DEFECT`, with the
file and line for anything you fault. If you FAIL, each blocking defect must be stated so it can be
fixed without a further round of clarification.
