# NFP 2026-08-07 T-7 orphan adoption review

- Task: `assign_706482a8`
- Fixed point: `729d3c8f9a12d80e11d58df9648c1f23e2ec797d`
- Review state: working tree, pre-commit
- Reviewer model: Codex `gpt-5.6-sol`
- Review method: Matt two-axis review (independent Standards + Spec agents)
- Reviewed at: `2026-08-01T23:06:27Z`
- Verdict: **PASS** (no remaining P1/P2)

## Spec axis

PASS. The package formalizes the held orphan without deleting it: pinned raw
inputs, network-free canonical entrypoint, runtime-generated result/spec
identity, exact event/control tables, chart, preserved legacy bytes, a retired
compatibility command, regression tests, reader-facing correction and explicit
post-commit orphan-reaper acceptance criteria are all present.

The review independently checked the calendar-stage `T-7` versus trading-day
`T-7` boundary. The conditioning close is 2026-07-29 (VIX 20.66); the latest
2026-07-30 snapshot is correctly labelled trading-day T-6. Event-day descriptive
statistics are not promoted into an unsupported stability claim.

## Standards axis

PASS. The final round found no documented-standard violation or reportable
Fowler-baseline smell. Earlier rounds found and resolved two material contract
defects:

1. the conclusion correction was missing from `docs/error_log.md`; it now has a
   Class F representative line and a full five-step incident record;
2. the compatibility wrapper documentation initially called the whole wrapper
   inert even though it delegates the canonical writer. It now states the exact
   side effect: canonical outputs are rewritten, only the embedded
   `LEGACY_SOURCE_UNVERIFIED` text is inert, and the three legacy artifacts are
   read-only and hash-pinned.

The incident status remains `contained` until the locked commit, committed-tree
gates, orphan reaper and task completion receipt have all been read back.

## Artifact and methodology evidence

- Canonical entrypoint SHA-256:
  `02a1f78de18f1e4360e9b40de0d0faa2764aca3d299f5a4bea3d6ae3ac3d86eb`
- Canonical result SHA-256:
  `2ea19edac3549f1f58fbedf7ff15d8fa487ceffba6f1d5327b6ab51208e9254f`
- Preserved pre-change entrypoint:
  `gate_history/c5459512__nfp_20260807_t7.py`
- Legacy result/events/figure SHA-256:
  `7658a1610c200840f76699e62e1d38d574930f3956710647e1398b2e1991a315`,
  `be020d5230a61c6b9b56b5bd817a1cca0d2f8fb07b0560a6554ea18f716a70d3`,
  `266ca0f29518c43d3fd6bc0ef041e7c6572eb64b2e30533d0adb53c5ed54a728`.
- Focused regression suite: 172 passed.
- Strict artifact/result identity: PASS.
- Experiment integrity gates: 4/4 PASS.
- Ruff: PASS.
- Article-series registry: drift 0.
- Anti-AI gate: PASS (two non-blocking style warnings).

## Reader-facing acknowledgement

The article update used the canonical publisher gateway and recorded four
errata actions: HAC/provenance correction, series identity completion,
information-set correction and conclusion alignment. Mirror and Supabase
reported success.

`https://volpred.zeabur.app/v3/reports/mile_84e3be0a` returned HTTP 200. The live
page contains the corrected title, 2026-07-29 VIX 20.66, and the no-event-day-
control caveat; it no longer presents 2026-07-30 as the research T-7 close, no
longer infers event-day stability, and no longer ends from a VIX-17 premise.

## Remaining terminal gates

This review certifies the claim surface only. The task is not closed until an
exact-path locked commit lands, all gates pass on the committed tree,
`reproduce_check` succeeds, the orphan reaper no longer holds the namespace,
and the task-pool completion receipt is durable.
