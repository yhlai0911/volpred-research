# Error Log Governance Sweep 320 - 2026-07-06

## Trigger

`governance_error_log_review_320` was opened because `docs/error_log.md`
crossed the 320-entry bucket. The task brief required a review of the recent
20 top-level incidents, a silent-fallback audit if that cluster appeared, and
consolidation into rules / skills / lint rather than another one-off note.

Recent entries reviewed: `docs/error_log.md:5` through
`docs/error_log.md:267`, covering the first 20 `##` incidents from
2026-07-06 through 2026-07-02.

## Recent Cluster

The recent 20 incidents point to six recurring root-cause classes.

1. **No first-class source of truth for cross-session entities.**
   The article-series incident needed `config/article_series.json`; event
   reaction slots needed coverage state; paper / frontend status and schedule
   behavior repeatedly drift when a session infers state from titles,
   timestamps, old guides, or prose. The rule is now explicit in
   `.claude/rules/control-plane.md`: reusable entities need a registry or
   canonical config before content/state operations.

2. **Control-plane state writes need stronger invariants.**
   Recent failures include stale claim metadata, blocked rows used as terminal
   storage, a partial `next_tasks.json` write, detached-HEAD commits, and
   worktree merge false-negatives. These are one class: canonical state is
   being mutated without enough pre-write and post-write verification.

3. **Alert severity is still too coarse unless the condition has taxonomy.**
   Market holidays, quota windows, guard-held pushes, self-recovering 142
   hangs, and findings-only exits are not equivalent to infrastructure death.
   Conversely, outcome damage such as push backlog or publishing drought must
   alert even when the lower-level guard behaved correctly.

4. **Fail-open can be correct; unobservable fallback is still the hazard.**
   The cluster includes silent-fallback gate effects, guard-held push backlog,
   and benign skip handling. The common requirement is a stable `kind` /
   `reason` / `exit_semantics` / audit trail, not necessarily fail-closed
   behavior.

5. **Time, status, and provenance must be read from the canonical field.**
   UTC feed timestamps were misread as local time; draft `published_at` was
   mistaken for public state; service ownership for `/api/sync/*` was inferred
   from a similarly named mirror API. These are all "side evidence used as
   ground truth" failures.

6. **Publication gates must distinguish ingestion state from reader-facing
   state.** Draft ingestion, release-pool cadence, event reaction coverage, and
   arc-dedup operate at different lifecycle points. A gate written for
   `published` content should not automatically block draft ingestion or
   internal queue materialization.

## Silent Fallback Audit

Commands run during this sweep:

```bash
uv run python scripts/audit_silent_fallbacks.py --json
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
```

Results:

- Current audit findings: 64.
- Baseline findings: 64.
- New findings above baseline: 0.
- Resolved baseline findings: 0.

Top current clusters:

- `src/volpred/**`: 28 findings.
- `scripts/indicator_arena_daily.py`: 5 findings.
- `scripts/experiment_regime_switching_vt.py`: 3 findings.
- `scripts/radar_holdings_risk.py`: 3 findings.
- Most common fallback actions: `continue` 30, `return None` 16, `pass` 13.

Because strict audit showed `new=0`, this sweep did not mix a broad baseline
reduction with governance consolidation. The standing baseline-reduction SOP in
`.claude/rules/no-silent-fallback.md` remains the right path for shrinking the
64 known instances.

## Rules Updated

This sweep updated three rule files:

- `.claude/rules/control-plane.md`: added the 2026-07-06 error-log-320
  invariants for registries, status ground truth, atomic writes, claim metadata,
  detached HEAD checks, and worktree merge fail-closed behavior.
- `.claude/rules/alert.md`: added a severity-taxonomy section requiring
  calendar / benign skip / self-recovering / guard-held / outcome-damage
  separation before alert escalation.
- `.claude/rules/no-silent-fallback.md`: added governance-sweep usage rules for
  running `audit_silent_fallbacks`, fixing any new strict findings in the same
  turn, and reporting baseline status when no new finding exists.

## Verification

```bash
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
uv run python -m json.tool storage/next_tasks.json >/dev/null
```

Verification results on 2026-07-06:

- Silent fallback strict audit: `findings=64`, `baseline_findings=64`,
  `new=0`, `resolved=0`.
- `storage/next_tasks.json` remained valid JSON after task claim/start state
  changes.

