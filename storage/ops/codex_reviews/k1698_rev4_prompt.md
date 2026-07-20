# Codex primary-path review — K1698 rev4 (round 5)

You are the primary-path reviewer. This is **round 5**.

## History

- Round 1 (rev1) **FAIL** — 7 blockers.
- Round 2 (rev2, `706587a37`) **FAIL** — 1 CRITICAL, 4 MAJOR, 1 MINOR, 2 still open.
- Round 3 (rev2b, `23975b1b0`) **FAIL** — 8 items.
- Round 4 (rev3, `0adb2db19`) **FAIL** — full text at
  `storage/ops/codex_reviews/k1698_rev3_verdict.md`. **Every round-3 item PASSed**;
  the FAIL rested entirely on two *new* documentation-evidence defects that the
  round-3 remediation itself introduced:
  - `NEW-MINOR-RUNTIME-EVIDENCE` — README attributed a `286.6s` runtime to "較空載"
    (a lighter machine load), and `k1698_rev3_remediation.json` line 103 called that
    figure a receipt, while line 117 of the same file admitted the on-disk log is a
    truncated stub. No load telemetry was ever collected.
  - `NEW-MINOR-AUDIT-RECORD` — the MAJOR-2 evidence field asserted
    `grep -c '3 天' README.md == 0`; the true count is 1.

**rev4 (`e13f83a5d`) is the remediation for exactly those two items and nothing else.**

## What rev4 changed

Two files, no code, no numbers:

1. `experiments/k1698/README.md` §runtime — deleted the `286.6s` figure and the
   "較空載" causal attribution. It now cites only the two runs that carry completion
   receipts (`370.6s` → `run_log_rev4.txt` last line; `288.8s` → `run_log_rev2.txt`
   line 281) and states that wall-clock varies between runs **without** explaining why,
   disclosing that no load telemetry was collected.
2. `experiments/k1698/k1698_rev3_remediation.json` — the MAJOR-2 `evidence` field now
   reports the true grep count (1) and identifies the hit as README line 78, the
   historical "corrected from 3 天 to 2 天" note rather than a surviving claim; the
   runtime entry's `evidence`/`after`/`note` no longer call `286.6s` a receipt; and the
   `execution_receipts` entry for `run_log_rev3.txt` now carries `elapsed_sec: null`
   with an explicit "NOT A RECEIPT" note.

`review_verdict.json` was regenerated against the new bytes and is **unfilled**
(`FILL: ...` in every verdict field) — it is yours to fill, not the author's.

## Your scope is narrow

1. Are the two round-4 findings actually fixed **in the bytes**, and sufficiently?
2. Did this remediation introduce any **new** claim–evidence gap? Apply the same
   standard that produced the round-4 FAIL: any statement of evidence must match what
   the bytes actually show, and no causal attribution may exceed the telemetry.
3. Confirm no substantive number moved relative to the round-4 artifact. The headline
   numerics should still read `t = 1.4694`, `n = 436`, `p_TOST = 0.868961`,
   `delta_min = 0.224194`, `GATE_VERDICT = H2_REJECTED`.

Do **not** re-litigate anything that PASSed in round 4 unless rev4's two edits touched
it. Do **not** carry round 4's verdict forward — review the current bytes.

## Where everything lives

Working tree (read-only for you):

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/
```

The bytes under review are frozen at
`/Users/yhlai0911/volpred-research/storage/ops/codex_reviews/k1698_rev4_freeze.txt`
(sha256, 10 files). If any file you read does not match its listed hash, **stop and say
so** — the review is invalidated.

Read, at minimum:

- `experiments/k1698/README.md` (the runtime paragraph, and line 78)
- `experiments/k1698/k1698_rev3_remediation.json`
- `experiments/k1698/run_log_rev2.txt` (line 281), `run_log_rev4.txt` (last line)
- `experiments/k1698/run_log_rev3.txt` — the truncated stub, to confirm it is still
  cited nowhere as a receipt. **Note: this file is deliberately NOT in the freeze list**
  precisely because it is not evidence for anything; read it to verify the negative.
- `experiments/k1698/k1698_rev2_results.json` (`elapsed_sec`, and the headline numerics)
- `storage/ops/codex_reviews/k1698_rev3_verdict.md` (the round-4 findings you are checking)

## Output contract

Write a verdict document with:

- a per-finding ruling for `NEW-MINOR-RUNTIME-EVIDENCE` and `NEW-MINOR-AUDIT-RECORD`
  (PASS / FAIL, each citing the bytes you checked),
- a `## Standing checks` section confirming the substantive numerics did not move,
- a `## 新問題` section (empty if none),
- and a final line of exactly `VERDICT: PASS` or `VERDICT: FAIL`.

Any surviving claim–evidence gap means FAIL. Do not soften a FAIL because the remaining
defects are small — round 4 correctly failed this experiment on two MINORs.

If and only if you reach PASS, also fill `experiments/k1698/review_verdict.json`:
`verdict`, `reviewer`, `reviewed_at`, `reviewed_commit` (`e13f83a5d`), `review_artifact`
(`storage/ops/codex_reviews/k1698_rev4_verdict.md`), and `blocking_defects: []`. Leave
`reviewed_sha256` exactly as generated. On FAIL, fill `verdict: FAIL` and list each
blocker in `blocking_defects`. The author must never self-sign this file.
