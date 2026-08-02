# Token telemetry source coverage — Codex review receipt

- Task: `token_report_session_source_coverage_20260802`
- Commits: `236c6923b`, `53e241016`
- Reviewed at: 2026-08-02 (Asia/Taipei)
- Verdict: **PASS** (Spec + Standards)
- Closure: **`root_cause_fixed_and_verified`**

## Acceptance evidence

- Claude discovery structurally includes the main repo, registered worktrees, and
  Operations Core dispatch scratch directories; unrelated lookalike projects are
  excluded and copied message IDs are deduplicated.
- Codex telemetry uses exact `last_token_usage` when present. A present but malformed
  value warns and fails closed; legacy cumulative resets only establish a new baseline.
- Fork/replay parsing is single-pass and buffered. A later foreign `session_meta` can
  retract candidate records and model attribution; an unproven boundary discards the file.
- Modern replay identity is canonical session + cumulative tuple + exact-call tuple,
  intentionally excluding replayable timestamps.
- Daily and weekly report generation materialize telemetry once, then reuse the same
  immutable snapshot for aggregation and drilldown.

## Verification

- `uv run pytest tests/test_token_usage_report.py tests/test_ops_summaries.py -q`
  → **45 passed**.
- Ruff `F,E9` scope and `git diff --check` → **PASS**.
- Matt code-review Spec axis → **PASS**, no remaining P1/P2.
- Matt code-review Standards axis → **PASS**, no remaining finding.
- Live 2026-07-30 long Codex root session: **4,124 records**, input **13,842,025**,
  cache read **605,504,000**, output **1,206,304**; the former parser reported
  72,283,828,462 input for the same day shape.
- Regenerated 2026-07-26 weekly report: billable **269,490,831**, not the erroneous
  **131,255,129,227**. Regenerated 2026-08-01 daily report: billable **43,240,765**
  (Claude **4,474,589**, Codex **38,766,176**).

## Review findings closed

1. Project-slug discovery used the wrong underscore/hyphen encoding.
2. Fork replay boundaries and lineage-only workers were not represented safely.
3. Interleaved cumulative streams inflated historical Codex usage.
4. Timestamp-based modern identities recounted replayed exact events.
5. Candidate replay records leaked stale model attribution after later foreign metadata.
6. Provider quota, pricing, category, and reasoning scopes were previously conflated.

