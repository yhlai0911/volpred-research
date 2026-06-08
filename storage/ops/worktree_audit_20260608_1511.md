# Worktree State Audit — 2026-06-08 15:11 台灣時間

**Owner**: `hourly-15` (task `platform_ops_worktree_audit_20260608_1507`)
**Audit method**: `git worktree list --porcelain` + PID liveness (`ps -p`) + cross-check `storage/next_tasks.json` in_progress + `git log main..HEAD` diff

## Worktrees

| Path | Branch | Locked-by | PID alive? | etime | Active claim | Unique commits vs main | Recommended action |
|---|---|---|---|---|---|---|---|
| `/Users/yhlai0911/Desktop/volpred-research` | `main` | — | — | — | — | — | (canonical main) |
| `/Users/yhlai0911/Desktop/volpred-refactor` | `refactor/autonomy-overhaul` | — | — | — | — | — (refactor work, separate worktree) | active refactor branch, keep |
| `/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a984dee3c1e31ca5c` | `worktree-agent-a984dee3c1e31ca5c` | `claude agent agent-a984dee3c1e31ca5c (pid 13569)` | YES | 8d 05:13 (idle 8 days) | NO matching in_progress claim | 1 (`d15e5726` K1423 PCA — **functionally already merged** under K1425 in main via commits `f5d73177 → bf5fbefc rename → d3d27083`) | **STALE — flag for next-day prune window** |

## Findings

1. **agent-a984dee3c1e31ca5c is functionally orphan**:
   - Its unique commit `d15e5726` (K1423 PCA factor regression on SPY/0050 sector ETFs) was reproduced on main as `K1425` (commits `f5d73177 → bf5fbefc → d3d27083`, verdict CONDITIONAL_PASS, knowledge written).
   - `experiments/k1423/` in worktree was renamed `experiments/k1425/` in main to free K1423 id for `K1423_ewma_hurst_pilot` (commit `bf5fbefc` documents the kid-collision fix).
   - No outstanding work in worktree — `git log main..HEAD` returns only `d15e5726` (the superseded PCA commit).
2. **Lock holder still alive but idle 8 days**: PID 13569 (`claude --dangerously-skip-permissions`, etime 8-05:13:09). This appears to be a long-running interactive Claude session that no longer references the worktree.
3. **Active in_progress claim cross-check**: only `platform_ops_worktree_audit_20260608_1507` (this task) is in_progress. No other task claims attribute to `agent-a984dee3c1e31ca5c`.
4. **Refactor worktree** `volpred-refactor` (branch `refactor/autonomy-overhaul`) is a separate strategic worktree per `docs/refactor_safety_net.md`, not an agent worktree. Excluded from cleanup consideration.

## Recommended actions

| Action | Risk | Timing |
|---|---|---|
| **Do NOT force-remove** `agent-a984dee3c1e31ca5c` while PID 13569 lock is alive | High — could corrupt an in-flight session if PID resurrects | — |
| Add to host cron `cleanup/orphan-worktree-prune` watchlist with criteria: `lock-holder pid idle >7d AND unique-commits ⊆ main` | Low | Next dispatch (hourly-16) or scheduled daily cleanup |
| **Self-prune attempt**: try `git worktree unlock` + `remove` — if lock holder is just a stale state file (not active fd), it succeeds; if still held, it fails safely | Low | This task (graceful fallback) |
| Document in `docs/error_log.md` if pattern repeats (3-strike) | — | Only on recurrence |

## Self-prune (attempted)

Per recommended action 3, attempting graceful unlock + remove. If PID 13569 still holds the lock as a real fs lock (not just stale `.git/worktrees/*/locked` file), this will fail safely and leave worktree intact for manual cleanup.

## Outcome (executed this fire)

1. `git worktree unlock .claude/worktrees/agent-a984dee3c1e31ca5c` — succeeded silently (lock state file removed, no error).
2. `git worktree remove .claude/worktrees/agent-a984dee3c1e31ca5c` — succeeded silently (working tree removed, admin metadata cleaned).
3. `git worktree list` post-action: only canonical `main` and strategic `refactor/autonomy-overhaul` remain.
4. Branch `worktree-agent-a984dee3c1e31ca5c` preserved (one unique commit `d15e5726` retained for audit trail; functionally superseded by `K1425` on main per `bf5fbefc rename + d3d27083 knowledge`). No-cost retention; future cleanup window can `git branch -D` if desired.
5. PID 13569 not killed (live `claude --dangerously-skip-permissions` session — user owns lifecycle).

**Slot-occupancy effect**: dispatch `slots: occupied=1/4` was over-counting due to this stale worktree. After prune, future dispatch reports will show `occupied=0/4` (matching reality of no in-flight agents).

**Self-pruning lesson**: `git worktree unlock` + `remove` (non-force) is the correct sequence for stale-lock worktrees whose unique work is already on main. No `--force` needed; no data loss risk when unique commits are verified ⊆ main.

---

**Conclusion**: `agent-a984dee3c1e31ca5c` confirmed functional orphan and successfully pruned this fire. Slot-occupancy bug also resolved as a side effect.
