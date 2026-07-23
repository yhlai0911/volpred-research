VERDICT: FAIL

# Primary-path review — duplicate-snapshot contamination audit

Reviewer: Codex failover (`codex-failover-slot-2-2835aeeb3bca4d15a1f20a201e7c7f98`)
Reviewed branch: `wt/dispatch-slot-1-858545f9-snapaudit` at `90b4fe89e`
Reviewed artifact: `experiments/audit_dup_snapshot_20260719/audit_results.json`

## MAJOR-1 — the claimed consumer coverage is internally incomplete

`audit_results.json.status` says every consumer has a verdict, and `summary` reports 44
consumers with `conclusions_changed_by_the_contamination: 0`.  But the same file's
`needs_compute_queue` section names real snapshot readers that are absent from the 44-entry
`consumers_scanned` list and therefore have no `affected`/`unaffected` verdict.

The clearest example is `experiments/k1380/k1380.py`: the audit supplies an exact paired-run
command for it, while the script directly reads
`paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`; it is not one of the 44 verdicts.
The same contradiction applies to the listed garch-x-vix end-to-end readers `K1394`, `k1319`,
`k1382`, `k1391`, `k1392`, `k1393`, `k1396`, `k1398`, `k1497`, `k1498`, `k1585`, and `K1587`.
Each directly references an affected snapshot, but none has a per-consumer verdict in the
claimed coverage set.  The README itself admits those paired reruns did not finish.

This is not a request to run every expensive pipeline when a sound mechanism-level proof is
available.  It is a requirement that every discovered reader appear in the coverage ledger,
receive an explicit verdict with evidence, and be counted honestly.  Until then the audit can
only claim “zero conclusion changes among resolved consumers”; it cannot claim complete scope,
44 total consumers, or zero conclusion changes without qualification.

## Required remediation

1. Build one exhaustive consumer inventory for all nine snapshots and reconcile every reader
   against `consumers_scanned`; include the missing garch-x-vix readers above and any additional
   basename/directory/dynamic-path hits.
2. Give each real consumer a supported verdict.  Use code/window/dedup/frame-identity evidence
   where sufficient; enqueue paired end-to-end compute only where the conclusion cannot be
   settled without it.
3. Make `status`, summary counts, `conclusions_changed_by_the_contamination`, README prose, and
   `needs_compute_queue` agree.  Outstanding unresolved consumers must be represented as
   unresolved, not omitted from the denominator.
4. Regenerate the SHA-pinned review template and request a new primary-path review.

The paired-fixture isolation and the repaired KPPS GFEVD diagnostic are not the blocker here.
The merge is blocked solely because the central coverage/completeness claim is not yet supported.
