# Primary-path review — duplicate-snapshot contamination audit

You are the merge gate for an experiment that wants to enter `main`. It is an **audit**, not a
model: its deliverable is a set of verdicts about which past experiments read a contaminated
data snapshot, and whether any published or under-review number moved as a result. A wrong
"unaffected" here means a bad number stays live on the site or in a paper, so treat every
`unaffected` verdict as a claim that must be evidenced, not as a default.

**Where**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-858545f9-snapaudit`
(a linked worktree, branch `wt/dispatch-slot-1-858545f9-snapaudit`). The experiment is
`experiments/audit_dup_snapshot_20260719/`. Read the frozen bytes as they are; your sandbox is
read-only by design.

**Task**: `assign_7f508612`. Start from `README.md`, then `audit_results.json`.

## Background you need

`scripts/refresh_paper_snapshots.py` downloaded outside its per-file lock and appended using a
stale `old_last`, so concurrent refreshes appended the same block twice — exactly 10 duplicate
rows dated 2026-05-04..2026-05-15, in all 9 live paper snapshots. The audit window is
2026-05-20 to 2026-07-17.

The audit's method is a paired dirty-vs-clean fixture comparison (`build_fixtures.sh`), on the
argument that re-running against the live CSV would conflate the duplication with unrelated
data extension and revision. Judge that argument.

## What to check

1. **Coverage** — `consumers_scanned` claims 44. Is the consumer set actually complete? Grep the
   repo yourself for readers of the 9 snapshot paths; do not take the file's own list on faith.
   A consumer missed here is a silent survivor of the contamination.
2. **Every verdict carries evidence** — `affected` and `unaffected` alike. An `unaffected` with
   no cited mechanism or no paired rerun is an assumption wearing a verdict's clothes.
3. **The paired-fixture argument** — is dirty-vs-clean genuinely the right isolation, and is
   `fixtures/clean` really the same bytes minus the 10 dup rows and nothing else?
4. **`conclusions_changed_by_the_contamination: 0`** — does the evidence support zero, or does
   it only support "zero among what was measured"? `needs_compute_queue` lists 6 unfinished
   items and `partition_status` admits the garch-x-vix end-to-end reruns did not finish. Does
   the summary overclaim relative to that?
5. **`reached_a_reader`** — one published article (`mile_02c71e74`) and one knowledge.json entry
   (`k1705_reviewed_20260716`). Is the remediation scope right, and is anything else live that
   should have been listed?
6. **`false_positives_disproved: 15`** — spot-check the disproofs. A false "this consumer was
   never affected" is the same failure as a missed consumer.
7. **`partition_cfc_va/dy_diag_param.py`** (rewritten 2026-07-19, after the original run): the
   original read BTC net/to/from off a Cholesky FEVD and the repo's fevd-ordering ratchet
   rejected it — its own output showed net_btc = +4.93 under {BTC,SPY,VIX} vs -8.43 under
   {VIX,SPY,BTC}. Direction now comes from `experiments/k1025/k1025_v3.generalized_fevd` (KPPS,
   reused not re-implemented), with Cholesky retained as a non-directional control. Verify: the
   GFEVD reuse is correct and correctly applied; the row-normalisation and TO/FROM/NET
   orientation match Diebold-Yilmaz (row = receives, column = transmits); GFEVD really is
   ordering-invariant in the logs; and `dy_clean.log` being byte-identical to `dy_dirty.log`
   genuinely supports the consumer verdict rather than merely indicating both passes read the
   same file.

## Output

Write a review to the output file with, at the top, a single line:

    VERDICT: PASS

or

    VERDICT: FAIL

PASS means: merge this into `main` as-is. FAIL means it must not merge — say precisely what
must change. Use MAJOR / MINOR labels for findings. If the audit is sound but overclaims in its
`summary`/`status` prose, that is a MAJOR finding worth a FAIL, because the summary is what the
next reader will act on.

Do not soften a FAIL to keep the pipeline moving; a rubber-stamp here is worth less than no
review, and this gate exists because K1709 merged over a FAIL and turned CI red four times.
