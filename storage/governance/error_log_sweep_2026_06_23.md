# Error Log Pattern Sweep (governance_error_log_review_200) — 2026-06-23 13:07 台灣時間

## Scope
- Scanned: lines 1-599 of docs/error_log.md (~40 entries)
- Date range: 2026-06-22 to 2026-06-23
- Total entries: 233

## Three-Strike Patterns Identified

### Pattern A: Silent Fallback (127 instances, 68 files)
- Audit tool: scripts/audit_silent_fallbacks.py --json
- Status: 35+ batch fixed in 2026-06-22/23; 127 residual
- Structural fix done: .claude/rules/no-silent-fallback.md (this PR)
- Pending: src/volpred/ops/diagnostics.py + CI --strict gate

### Pattern B: Timestamp Parse Failures (8 occurrences)
- Sites: task_pool_claim / unblock_expired / dispatch_supervisor / refill_reader_facing_pool
- Structural fix pending: src/volpred/ops/timestamps.py with parse_iso_warn()

### Pattern C: Hook Exit-Code Masking (3 occurrences)
- Already fixed in 2026-06-23 batch
- Structural fix done: .claude/rules/hooks-exit-code.md (this PR)

## Visible-Root-Cause Patterns (< 3 but structural)

### Pattern D: Dual-Log Diagnosis (2 occurrences)
- gmail-poll + handoff_regen LaunchAgent dual-log divergence
- Fix: rules/hooks-exit-code.md includes wrapper STARTED/EXIT banner requirement
- Followup: update .claude/skills/admin-ops/references/scheduling.md with diagnosis checklist

### Pattern E: Dedup Gate Default-Block (2 occurrences)
- Arc-dedup 8-day content black hole
- Already fixed batch
- Structural fix done: .claude/rules/dedup-gate-audit.md (this PR)

## Action Items Completed This Fire
1. [DONE] .claude/rules/no-silent-fallback.md (prevent regression)
2. [DONE] .claude/rules/hooks-exit-code.md (prevent regression)
3. [DONE] .claude/rules/dedup-gate-audit.md (prevent regression)
4. [QUEUED] Followup task: build_diagnostics_module
5. [QUEUED] Followup task: build_timestamps_module
6. [QUEUED] Followup task: silent_fallback_ci_gate
7. [QUEUED] Followup task: admin_ops_dual_log_checklist

## Bar for Future
- New silent fallback in script → CI fails (once strict gate built)
- Baseline reduction: 127 → 0 over ~6 months (monthly governance task -20 each)
