# Refactor Plan — cron_hourly_dispatch (pre-staged for three-strike trigger)

**Status**: PRE-STAGED. Not executed yet.
**Trigger**: Next hang of `cron_hourly_dispatch.sh` (strike 3 — currently at strike 2 after 2026-05-13 10:07 + 15:07 incidents).
**Authority**: CLAUDE.md `Three-Strike Rule` (committed `a55620b4`).

## Why pre-stage

Codex review 2026-05-14 (commit `d588d189` follow-up) returned **FAIL** with 3 CRITICAL source-code defects in the current shell-script approach:
1. Single-PID kill (not process group) — claude forks orphan on hang
2. No trap cleanup — launchd kill mid-flight = claude + watchdog orphan
3. Watchdog PID-reuse race

Patches applied for these 3 issues, but Codex's broader signal is structural: the shell + LaunchAgent + perl alarm + watchdog pyramid keeps adding layers because the underlying model is wrong for the job. One more hang justifies bottom-up rewrite.

## Three-Layer Diagnosis (per CLAUDE.md Three-Strike Rule)

### Layer 1 — Domain Logic
- **Wrong**: cron-style stateless fire-and-forget for a job that needs (a) supervision, (b) health check, (c) sequential completion gate.
- **Right**: Long-lived supervisor daemon with a job queue. Each job is a unit of work with timeout / retry / completion state, not a discrete shell invocation.

### Layer 2 — Workflow
- **Wrong**: hang detection / heartbeat / orphan cleanup are bolt-ons inside the dispatch script (script that itself can hang).
- **Right**: Three independent processes — supervisor (long-lived), worker pool (short-lived), health monitor (independent failure detector). Health monitor can kill a stuck worker because it's not inside the worker.

### Layer 3 — Program Architecture
- **Wrong**: Shell script orchestration. macOS `launchd` + `perl -e alarm` + bash subshell + `wait $!` + `kill -0` polling — every layer is a known shell-correctness landmine.
- **Right**: Python `supervisord`-style or systemd-style daemon (we use `launchd` plist to start the supervisor on boot, not to schedule jobs). Job queue in SQLite or JSON file with mtime locking. Workers spawn via `subprocess` with `start_new_session=True` for clean PGID semantics, `subprocess.Popen.wait(timeout=...)` for hang detection.

## Replacement Architecture

```
launchd (boot only, KeepAlive=true)
  └─ supervisor.py (long-running, ~50MB resident)
       ├─ scheduler thread: every 4h enqueue job to queue
       ├─ worker pool: 1 concurrent job, subprocess.Popen with timeout=12600
       ├─ health monitor thread: every 60s check worker liveness, force-kill PGID if frozen
       └─ persistence: storage/ops/dispatch_state.json (last_fire_at, current_job_pid, last_completion)
```

**Files to create**:
- `scripts/cron_dispatch_supervisor.py` — entry point
- `scripts/cron_dispatch_supervisor/scheduler.py`
- `scripts/cron_dispatch_supervisor/worker.py`
- `scripts/cron_dispatch_supervisor/health.py`
- `scripts/tests/test_cron_dispatch_supervisor.py` — regression covering all 3 historical hangs + 3 Codex CRITICAL

**Files to deprecate** (move to `scripts/_legacy/`):
- `scripts/cron_hourly_dispatch.sh`
- `~/.volpred/bin/cron_hourly_dispatch.sh` (TCC copy)
- `scripts/cron_hourly_dispatch_prompt.md` — keep, supervisor loads same way

**LaunchAgent plist update**:
```xml
<key>ProgramArguments</key>
<array>
    <string>/Users/yhlai0911/.local/bin/uv</string>
    <string>run</string>
    <string>python</string>
    <string>scripts/cron_dispatch_supervisor.py</string>
</array>
<key>KeepAlive</key><true/>
<key>RunAtLoad</key><true/>
<!-- Drop StartCalendarInterval — supervisor handles scheduling internally -->
```

## Verification Gate (must pass before deprecating shell)

1. **Regression test 1**: simulate 2026-05-13 10:07 hang (claude stuck in S state) → supervisor kills worker via PGID after timeout → next scheduled job fires on time.
2. **Regression test 2**: simulate 2026-05-13 15:07 hang (17h orphan) → supervisor's independent health monitor force-kills worker (not relying on worker's own SIGALRM).
3. **Regression test 3**: simulate parent supervisor SIGKILL mid-job → on restart (launchd KeepAlive), supervisor detects orphan worker via PID file, cleans up, resumes.
4. **Codex CRITICAL #1**: kill kills full process group (verified by spawning a child inside test worker, checking child dies).
5. **Codex CRITICAL #2**: trap-equivalent cleanup runs on SIGTERM (verified by sending supervisor SIGTERM and checking pgrep claude returns 0).
6. **Codex CRITICAL #3**: PID-reuse race — verify worker target identification uses (PID, start_time) tuple, not just PID.
7. **Live shadow run**: 7 days of supervisor running alongside shell (shell continues to fire, supervisor logs what it would have done) → diff for behavioral parity before cutover.

## Execution Steps (when strike 3 fires)

1. `git commit -m "snapshot: pre-supervisor-refactor working state"` — rollback point
2. Implement `scripts/cron_dispatch_supervisor.py` + module files
3. Write regression tests, get all PASS
4. Live shadow run 7 days
5. Cutover: unload old LaunchAgent, install new, move shell to `_legacy/`
6. 14-day observation; if hang recurs, the shell-script approach was not the root cause and we re-diagnose layer 1 (domain logic)
7. `error_log.md` entry: "**3-STRIKE TRIGGER** cron_hourly_dispatch.sh — refactored to supervisor daemon per docs/refactor_plan_cron_dispatch.md"
8. Commit message prefix: `refactor(3-strike): cron-dispatch supervisor daemon`

## Why NOT execute now

Three-Strike Rule fires at strike 3, not on review feedback alone. Pre-staging the plan reduces strike-3 latency from days to hours. If next 6 fires (00:07 / 04:07 / 08:07 / 12:07 / 16:07 / 20:07) all run clean, the current shell + 2-layer-defense may have actually solved the structural issue at the patch level — in which case this plan stays pre-staged indefinitely as insurance.
