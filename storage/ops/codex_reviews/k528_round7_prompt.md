# Codex primary-path review — K528 round-7 NFP B1 gate hardening

You are the primary-path reviewer. This task lives in a worktree, FROZEN at its current
committed bytes. Review only; the sandbox is read-only. Your verdict is the merge ticket.
This task has a 3-strike flag active — a PASS must be earned, not granted.

## Claim surface (review exactly these)
- `.claude/worktrees/k528-round7-204d556b/tests/test_nfp_official_release_dates.py`
  (focus: class `TestReleaseMisbindingGateIsStructural` ~line 1189, and the detector
  helpers `_friday_bindings` ~966, `_clause_misbinds_237` ~996,
  `_release_misbinding_offenders` ~1015, `_k528_text_units` ~1028, real-file scan test ~1109)
- `.claude/worktrees/k528-round7-204d556b/experiments/k528/README.md`
- `.claude/worktrees/k528-round7-204d556b/experiments/K528/round7_gate_hardening_summary.json`

## What this is
Round-7 replaces the NFP "237-as-release-count" misbinding gate — previously a 5-phrase
literal blocklist with two blanket line-level exemptions (any "243" on the line, or any
denial token on the line, unconditionally skipped detection) — with a compositional,
proximity-aware (nearest-governor) structural detector: a Friday token offends only when
its nearest governing verb within 24 chars is a release/publication verb; session verbs
exempt; quoted mentions exempt; denial exemptions are clause-local not line-wide; Python
files are unitized via `ast` so implicitly-concatenated string literals are one unit.

The summary claims: OLD gate let 6/7 injections through (only the verbatim defect blocked);
NEW gate blocks 7/7 injections while keeping 4/4 legitimate distinction/errata lines
passing; 14 tests in the new class + 1 live-tree scan test all pass.

## Verify (be adversarial — this is the whole point of round-7)
1. **Not vacuous / not a stub**: read the actual helpers. Is the detector genuinely
   proximity/governor-based, or is it a phrase list wearing a structural costume? Could a
   trivially-rephrased injection (synonym, reordering, cross-clause denial) slip past it?
   Try to construct one in your head and check the code would catch it.
2. **Before/after honesty**: is the OLD column a faithful reconstruction of the real
   round-6 gate at base commit 5b1f154c1 (5 fixed strings + the two blanket exemptions),
   or is it the NEW gate relabeled to manufacture a contrast? This is the single most
   likely place for self-deception — scrutinize it.
3. **Tests real**: do the parametrized MUST-CATCH / MUST-PASS cases actually exercise the
   detector on the claimed strings, and does the live-tree scan test genuinely fail when an
   offending line exists and pass on the clean tree (not a no-op assertion)?
4. **N1/N2/N3 scope**: N1 (gate) hardened + regression-locked; N2 (README 237/243
   distinction) closed in-tree; N3 (article errata) is a DRAFT deliberately deferred to
   post-merge publish — confirm that deferral is real scope, not a silently-dropped claim.

## Output (plain text, last thing you write)
```
VERDICT: <PASS | CONDITIONAL_PASS | FAIL>
REVIEWED_COMMIT: <the worktree HEAD short sha you reviewed>
BLOCKING_DEFECTS: <none, or numbered list with file:line and why>
NON_BLOCKING_NOTES: <optional>
ONE_LINE: <one-sentence justification>
```
Bar: CONDITIONAL_PASS or above is mergeable. FAIL if the detector is defeatable by an
obvious rephrasing, the before/after is fabricated, or the tests don't actually test.
