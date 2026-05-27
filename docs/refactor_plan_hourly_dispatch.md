# Refactor Plan — hourly-dispatch worker daemon

**Status**: TRIGGERED (3-strike threshold crossed). Phase = DESIGN-LOCKED, IMPLEMENTATION started (Deliverable 2/8 scaffold done 2026-05-28 01:07-01:13 台灣時間).
**Authority**: `CLAUDE.md` Three-Strike Rule (commit `a55620b4`) — "strike 3 是 LATEST 觸發點不是 ONLY 觸發點；一旦看見結構性 root cause...就立刻三層重構".
**Supersedes**: `docs/refactor_plan_cron_dispatch.md` (2026-05-14 pre-staged version, drafted for hang-class strikes only).
**Parent task**: `platform_ops_refactor_hourly_dispatch_worker_daemon` (P2, `storage/next_tasks.json`).

## 1. Strike Log (consolidated)

| # | Date | Symptom | Class | Patch applied |
|---|------|---------|-------|---------------|
| 1 | 2026-05-13 10:07 | claude -p hang past cap | hang | perl `alarm` SIGALRM + watchdog |
| 2 | 2026-05-13 15:07 | 17h orphan via shell exec semantics | hang | trap cleanup + PGID kill |
| 3 | 2026-05-20 (8/12 fires) | claude -p crashes on `low max fd` | env | `ulimit -Sn 65536` |
| 4 | 2026-05-21 02:07/03:07 | exit=142 (SIGALRM) | hang | (already covered by #1 layer) |
| 5 | 2026-05-21 09:07+ | launchd `EX_CONFIG/78` — plist `StandardOutPath` blocked by TCC under `Desktop/` | env | move logs to `~/.volpred/logs/` |
| 6 | 2026-05-25 17:07/18:07 | Anthropic API `529 Overloaded` → exit 1 single-shot | upstream | 3-attempt retry + sonnet fallback |
| 7 | 2026-05-27 ?? | auth failure in launchd env (`Not logged in / Please run /login`) — keychain partition list not unlocked for launchd-spawned process | env | auth preflight + zshrc source + hotfix `security set-generic-password-partition-list ...` |

**Pattern signal**: each new failure adds another bolt-on (alarm → watchdog → trap → ulimit → log path → retry+fallback → auth preflight). Wrapper has grown from ~30 lines to **313 lines**, each layer guarding the layer below. Same architectural root: **stateless shell wrapper + opaque headless CLI subprocess + launchd env isolation**. Continuing to patch each new failure class would add a ~9th layer for the next environmental edge case.

## 2. Three-Layer Diagnosis

### Layer 1 — Domain Logic (root model is wrong)

- **Current**: hourly cron = "spawn a fresh claude -p subprocess in launchd env, hope it completes". Treats orchestration as **stateless fire-and-forget**.
- **Wrong because**: orchestration job is inherently **stateful and supervised** — needs (a) job queue, (b) liveness check, (c) retry policy with backoff, (d) auth/env continuity across runs, (e) graceful degradation. Stateless model forces every-run re-acquisition of env (keychain, fd limits, PATH, zshrc state) → each acquisition is a new failure surface.
- **Right model**: **long-lived supervisor daemon** that owns runtime env *once* (at startup, in user session), with **internal scheduler** that enqueues hourly jobs to a worker pool — same supervisor for paper_review, daily_article, paper_body, email_reply etc.

### Layer 2 — Workflow (failure modes & observability are bolt-ons)

- **Current**: hang detection (perl alarm), orphan cleanup (trap), retry (manual while-loop), failure alerting (send-alert tail call), auth preflight — all **inside the wrapper that itself can fail**. Self-referential failure detection has bounded reliability.
- **Wrong because**: if the wrapper hangs before the watchdog spawns, no protection. If the wrapper exits non-0 before `send-alert`, no alert. Strike 5 (launchd EX_CONFIG/78) showed exactly this — script body never ran, zero log lines, zero alert; only detected by an unrelated grep.
- **Right workflow**: three independent processes — **supervisor** (owns scheduler + queue), **worker** (executes one job, exits), **health monitor** (independent failure detector, kills stuck workers). Health monitor outside worker means it survives worker freeze.

### Layer 3 — Program Architecture (wrong implementation technology)

- **Current**: `bash` + `perl -e alarm` + launchd `StartCalendarInterval` + manual subshell PGID arithmetic + `kill -0` polling. Every layer is a known shell-correctness landmine (PID reuse, signal masking inheritance, exec vs spawn semantics, TCC sandboxing of Desktop/).
- **Right tech**: **Python supervisor daemon** with `subprocess.Popen(start_new_session=True)` (clean PGID), `Popen.wait(timeout=N)` (no perl needed), `os.killpg(pid, SIGKILL)` (no shell quoting), structured logging via `logging.handlers.RotatingFileHandler`, JSON job queue with `fcntl.flock` (already in use for `next_tasks.json`). Daemon runs under **user login session** (`launchd` Aqua agent) → keychain unlocked, PATH from `~/.zshrc` once at startup, `ulimit` set once — no per-fire re-acquisition.

## 3. Replacement Architecture

```
launchd Aqua agent (RunAtLoad=true, KeepAlive=true)
  └─ supervisor.py (long-running, ~50MB resident)
       ├─ scheduler (asyncio loop): tick every 60s; if HH:07 reached AND no in-flight job, enqueue
       ├─ worker pool (size=1, hard cap): subprocess.Popen claude -p, timeout=3000s
       ├─ health monitor (asyncio task): every 30s ps-check worker liveness; SIGTERM→SIGKILL on timeout
       ├─ retry policy: ≤3 attempts (opus → 90s → opus → 90s → sonnet); 529-class transient retried, hang-class abort
       ├─ persistence: storage/ops/dispatch_state.json (last_fire_at, current_job_pid+start_time, attempt_count, last_completion)
       └─ alert sink: send-alert on (a) any worker exit ≠ 0 after retries (b) supervisor health crash + restart
```

### 3.1 Files to create

| Path | Role |
|------|------|
| `scripts/dispatch_supervisor.py` | Daemon entry point; loads `config/runtime_schedules.json` for tick spec |
| `scripts/dispatch_supervisor/scheduler.py` | Time-tick → enqueue logic |
| `scripts/dispatch_supervisor/worker.py` | `Popen` wrapper with PGID + timeout |
| `scripts/dispatch_supervisor/health.py` | Independent liveness check |
| `scripts/dispatch_supervisor/state.py` | JSON state file with `fcntl.flock` writer |
| `scripts/dispatch_supervisor/alerts.py` | `send-alert` shim with dedup |
| `scripts/tests/test_dispatch_supervisor.py` | Regression covering all 7 historical strikes |
| `~/Library/LaunchAgents/com.volpred.dispatch-supervisor.plist` | Aqua agent (RunAtLoad + KeepAlive, NOT StartCalendarInterval) |

### 3.2 Files to deprecate (`_legacy/` after migration)

| Path | Action |
|------|--------|
| `scripts/cron_hourly_dispatch.sh` | move to `scripts/_legacy/` |
| `~/.volpred/bin/cron_hourly_dispatch.sh` | delete (TCC copy of above) |
| `~/Library/LaunchAgents/com.volpred.hourly-dispatch.plist` | `launchctl unload` then delete |
| `scripts/cron_hourly_dispatch_prompt.md` | **keep** — supervisor loads same prompt the same way |
| `docs/refactor_plan_cron_dispatch.md` | **keep as historical** — superseded by this file but holds 5/13 hang-strike context |

### 3.3 Re-use, don't reinvent

Existing modules already give half the pieces:

- **Job queue pattern**: `scripts/compute_queue.py` already implements queued→running→completed/failed state machine with `result_artifact`, `claude_followup`, idempotent dispatch. Lift the state-file pattern.
- **Worker daemon pattern**: `~/Library/LaunchAgents/com.volpred.compute-worker.plist` already runs `*/15` worker; verified stable. Mirror its plist structure for the supervisor.
- **Lock semantics**: `scripts/task_pool_claim.py` uses `fcntl.LOCK_EX` on `next_tasks.json`; same pattern for `dispatch_state.json`.
- **Alert sink**: `uv run volpred ops send-alert` already supports HTML + body-md + dedup.

This is **not greenfield** — it's consolidation of patterns already in production into one place.

## 4. Migration Plan (parallel running)

| Phase | Duration | Action |
|-------|----------|--------|
| **0. Snapshot** | now | `git tag pre-supervisor-refactor` + commit current state |
| **1. Implement** | 1-2 days | Build `dispatch_supervisor.py` + tests; supervisor only LOGS what it WOULD enqueue (dry-run) |
| **2. Shadow** | 7 days | Both old shell + new supervisor (dry-run) run in parallel; diff their decisions every hour |
| **3. Cutover** | 1 day | Disable old shell (stub mode: log "would-have-spawned" but no claude exec); enable supervisor real-run |
| **4. Observation** | 14 days | Watch `hourly_dispatch.log` + `dispatch_supervisor.log` side-by-side; verify no regression on (a) job claim rate (b) email_reply latency (c) failure detection |
| **5. Deprecate** | 1 day | `launchctl unload` old LaunchAgent; `mv scripts/cron_hourly_dispatch.sh scripts/_legacy/`; delete TCC copies |
| **6. Retro** | 1 day | `docs/error_log.md` entry `**3-STRIKE TRIGGER** hourly-dispatch — refactored to supervisor daemon`; close parent task |

Total ~24-26 days end-to-end. Old shell stays callable up to phase 5 — full rollback any moment until then.

## 5. Verification Gate (must all PASS before phase 5)

| # | Test | Method |
|---|------|--------|
| 1 | Strike 1 (hang at S-state) | Spawn fake claude that sleeps 4000s; verify worker SIGKILL'd at 3000s + next tick fires on schedule |
| 2 | Strike 2 (orphan claude after parent kill) | Send supervisor SIGKILL mid-job; on auto-restart (KeepAlive=true), verify orphan worker detected via PID file + start_time, cleaned up, resumed |
| 3 | Strike 3 (fd limit) | Supervisor sets `ulimit -Sn 65536` at startup once; verify child Popen inherits |
| 4 | Strike 5 (TCC sandboxing) | Supervisor logs to `~/.volpred/logs/`; verify zero log files attempted under `Desktop/` (`lsof` audit) |
| 5 | Strike 6 (API 529) | Mock claude exit=1 with stderr containing "529"; verify retry-with-backoff fires (opus → 90s → opus → 90s → sonnet); on full failure verify proactive alert sent |
| 6 | Strike 7 (auth) | Mock claude exit with "Not logged in"; verify supervisor (a) does NOT retry (auth retry pointless) (b) sends auth alert with hotfix command (c) flags `dispatch_state.auth_blocked=true` to halt future ticks until manual unblock |
| 7 | Supervisor liveness | Kill supervisor via `pkill -9`; verify launchd `KeepAlive` respawns within 10s |
| 8 | Schedule fidelity | Over 24h shadow run, supervisor enqueue timestamps must match old shell fire timestamps within ±60s for all 24 fires |
| 9 | Idempotency | Inject duplicate hourly tick; verify only one worker spawns per HH:07 |
| 10 | Concurrent safety | Two scheduler ticks at same instant; verify `fcntl.flock` serializes state writes |

## 6. Codex Review Gate

Before phase 2 (shadow run start): submit `dispatch_supervisor.py` + tests to Codex for review. Required verdict ≥ CONDITIONAL_PASS. Strike-3 refactors must have an independent review per CLAUDE.md research-honesty extension to platform code.

## 7. Risk & Rollback

| Risk | Mitigation |
|------|-----------|
| Supervisor itself hangs / crashes loop | launchd `KeepAlive` + `ThrottleInterval=60` rate-limits respawn; external monitor (`check_alerts.py`) flags `dispatch_supervisor_dead` if no heartbeat in `storage/ops/dispatch_state.json` for >75min |
| State file corruption | `fcntl.LOCK_EX` write + atomic rename (`os.replace`); supervisor on startup validates JSON; fallback to bootstrap-from-zero if invalid |
| Migration regression in shadow phase | Both systems run in parallel — instant fallback by re-enabling old plist |
| Phase 5 (deprecate) breaks something hidden | `git tag pre-supervisor-refactor` at phase 0 = trivial revert; `_legacy/` keeps shell callable for emergency `bash scripts/_legacy/cron_hourly_dispatch.sh` invocation |

## 8. Execution Order (next sessions)

1. **2026-05-27 17:07-17:30**: write this plan + commit + leave parent task in `pending` (Deliverable 1 complete). ✅
2. **2026-05-28 01:07-01:13 hourly-01**: package scaffold `scripts/dispatch_supervisor/` (`__init__`, `state.py` full impl, `worker.py`/`scheduler.py`/`health.py`/`alerts.py`/`supervisor.py` stubs) + `scripts/tests/test_dispatch_state.py` (16 tests passing). State module persistence + lock + ring buffer + orphan cleanup verified. Supervisor entry refuses to run main loop (exit 78) until Deliverable 3. ✅
3. **2026-05-28 05:07-05:14 hourly-05**: Deliverable 3/8 DONE — `alerts.py` (5 alert fns + per-class dedup), `worker.py` (240 lines: Popen + PGID + retry ladder opus→opus→sonnet + classify auth/529/hang/hard_failure + `_kill_pgid` SIGTERM→SIGKILL), `health.py` (60 lines: `check_once` sync + `health_loop` asyncio), `scheduler.py` (110 lines: croniter + `_due_to_fire` + `_tick_once` + dry-run path), `supervisor.py` real asyncio gather. Version bumped 0.1.0-scaffold → 0.2.0-d3. 16 state tests still pass; classifier smoke 6/6; scheduler decision smoke 3/3; health no-op smoke pass. ✅
4. **+1 session**: Deliverable 4/8 — regression tests for strikes 1/2/3/5/6/7 + supervisor liveness + schedule fidelity + idempotency + concurrent safety (10 verification gates per §5)
4. **+1 session**: Codex review submission; address findings (Deliverable 6 gate)
5. **+1 session**: phase 2 shadow run start; daily diff for 7 days (Deliverable 5)
6. **+2 sessions**: phase 3 cutover + 14-day observation (Deliverable 5-6)
7. **+1 session**: phase 5 deprecate + retro entry (Deliverable 6-8)

Each step independently committable; each session ≤ 50min cap; heavy compute (none expected for this refactor — pure orchestration code) goes to `compute_queue.py` if needed.

## 9. Why this is genuinely structural, not a 9th patch

Every prior patch addressed *one new failure surface* (hang → alarm; orphan → trap; fd → ulimit; TCC → log path; API → retry; auth → preflight). The wrapper does not solve any underlying class — it just adds branches per observed failure.

A supervisor daemon **eliminates the failure class entirely**: keychain unlocked once (auth preflight obsolete), env loaded once (zshrc source obsolete), fd limit raised once (per-fire ulimit obsolete), TCC issues moot (daemon runs in user Aqua session, not launchd cron context), retry-and-fallback is a normal worker function not a wrapper concern, hang detection is a normal supervisor concern not a perl-alarm bolt-on. Strikes 1-7 all collapse into 2-3 supervisor primitives (timeout, retry policy, health check) instead of 7 distinct shell branches.

That's the test for "structural fix" vs "patch": does the change make *future* strikes-of-same-class impossible, or does it just handle the latest one? Supervisor satisfies the first; another shell branch satisfies only the second.

---

*Drafted 2026-05-27 17:07-17:30 台灣時間 by main thread under hourly-17 claim. Deliverable 1/8.*
*Updated 2026-05-28 01:07-01:13 台灣時間 by main thread under hourly-01 claim. Deliverable 2/8 — package scaffold + state module + 16-test unit suite.*
*Updated 2026-05-28 05:07-05:14 台灣時間 by main thread under hourly-05 claim. Deliverable 3/8 — alerts/worker/health/scheduler/supervisor real impl. Version 0.2.0-d3.*
