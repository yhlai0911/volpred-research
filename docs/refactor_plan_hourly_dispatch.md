# Refactor Plan — hourly-dispatch worker daemon

**Status**: TRIGGERED (3-strike threshold crossed). Phase = DESIGN-LOCKED, IMPLEMENTATION started (Deliverable 4/8 tests+CLI done 2026-05-28 07:12 台灣時間).
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
| 8 | 2026-06-15 10:57 (+ 2026-06-14 15:57; 44 historical) | exit=142 SIGALRM recurrence — refactor STALLED at Deliverable 4/8 since 2026-05-28 (~18 days), so the structural fix never shipped → hang class still live | hang | Phase A only: `alerts.py` severity calibration (lone 142→warn) — symptom noise止血, NOT the fix |

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
4. **2026-05-28 07:12 hourly-07**: Deliverable 4/8 DONE — add `tests/test_dispatch_supervisor.py` covering worker retry/auth/hang, scheduler skip/dry-run/fire, health kill/silent-death, RLIMIT regression, and `scripts.dispatch_supervisor.cli` (`status`, `unblock-auth`, `health-check`). Version bumped 0.2.0-d3 → 0.3.0-d4. ✅
5. **+1 session**: Codex review submission; address findings (Deliverable 6 gate)
6. **+1 session**: phase 2 shadow run start; daily diff for 7 days (Deliverable 5)
7. **+2 sessions**: phase 3 cutover + 14-day observation (Deliverable 5-6)
8. **+1 session**: phase 5 deprecate + retro entry (Deliverable 6-8)

Each step independently committable; each session ≤ 50min cap; heavy compute (none expected for this refactor — pure orchestration code) goes to `compute_queue.py` if needed.

## 9. Why this is genuinely structural, not a 9th patch

Every prior patch addressed *one new failure surface* (hang → alarm; orphan → trap; fd → ulimit; TCC → log path; API → retry; auth → preflight). The wrapper does not solve any underlying class — it just adds branches per observed failure.

A supervisor daemon **eliminates the failure class entirely**: keychain unlocked once (auth preflight obsolete), env loaded once (zshrc source obsolete), fd limit raised once (per-fire ulimit obsolete), TCC issues moot (daemon runs in user Aqua session, not launchd cron context), retry-and-fallback is a normal worker function not a wrapper concern, hang detection is a normal supervisor concern not a perl-alarm bolt-on. Strikes 1-7 all collapse into 2-3 supervisor primitives (timeout, retry policy, health check) instead of 7 distinct shell branches.

That's the test for "structural fix" vs "patch": does the change make *future* strikes-of-same-class impossible, or does it just handle the latest one? Supervisor satisfies the first; another shell branch satisfies only the second.

---

*Drafted 2026-05-27 17:07-17:30 台灣時間 by main thread under hourly-17 claim. Deliverable 1/8.*
*Updated 2026-05-28 01:07-01:13 台灣時間 by main thread under hourly-01 claim. Deliverable 2/8 — package scaffold + state module + 16-test unit suite.*
*Updated 2026-05-28 05:07-05:14 台灣時間 by main thread under hourly-05 claim. Deliverable 3/8 — alerts/worker/health/scheduler/supervisor real impl. Version 0.2.0-d3.*
*Updated 2026-05-28 07:12 台灣時間 by Codex hourly tick. Deliverable 4/8 — regression tests + ops CLI. Version 0.3.0-d4.*

---

## 10. 2026-06-15 復發 + 停滯診斷（email-11745：用戶要求「徹底從底層了解並解決」）

**核心發現：結構解法已設計+半完成，但停了 18 天。** 這份 plan 的 supervisor daemon（§3-8）在 2026-05-28 做到 Deliverable 4/8（`scripts/dispatch_supervisor/` + `tests/test_dispatch_supervisor.py`），之後**卡在 Deliverable 5（Codex review）前未推進**。期間 hourly_dispatch 繼續用舊 shell+perl-alarm 路徑 → exit=142 hang 自然持續復發（2026-06-14、06-15…）。

**所以「徹底解決」不是再診斷或再設計（都已完成），是把停滯的 refactor 推完。**

### 本次（2026-06-15）實際做的 — Phase A 症狀層
- `src/volpred/ops/alerts.py` `host_cron_fail` severity 校準：單次自我恢復的 142 → `warn`；≥2 連續失敗 或 非-142 失敗 → `critical`。
- 新增 helper `_trailing_authoritative_exit_codes` / `_trailing_consecutive_failures`；body 加 severity 說明 + 指回本 plan。
- 回歸測試 `tests/test_alerts.py::test_host_cron_fail_severity_calibration`（4 cases）。
- **這只是止住 CRITICAL email noise，不是 fix**。hang class 仍 live，直到 supervisor 上線。

### 復跑 supervisor refactor 的剩餘步驟（Deliverable 5-8，§8）
5. Codex review `scripts/dispatch_supervisor/*`（需 ≥ CONDITIONAL_PASS）— **下一步**
6. Phase 2 shadow run 7 天（新舊並行 dry-run diff）
7. Phase 3 cutover + 14 天觀察
8. Phase 5 deprecate 舊 shell + retro 寫 error_log

**Phase C（cutover）高 blast radius（替換核心 runtime）— 動前需用戶確認。** review + shadow（5-6）是可逆、低風險，可自主先推。

*Updated 2026-06-15 台灣時間 by interactive main thread (email-11745 reply). Strike 8 logged; Phase A severity calibration shipped; refactor un-stalled — next action Deliverable 5 Codex review.*

### Deliverable 5 — Codex review 結果：**FAIL**（2026-06-15）

Review 抓到 7 個真 bug（**這就是它停 18 天的真因：本來就還沒 review-ready**）。進 shadow run（Deliverable 6）前**全部必修**：

1. **🔴 致命 — signal exit 分類**：worker timeout `_kill_pgid()` 後 `Popen.wait()` 回負號（-15/-9），但 `HANG_EXIT_CODES={137,142,143}`（worker.py:48）不含負號 → 被分類成 hard_failure 然後 **retry**（worker.py:251-260），**直接破壞 hang-abort 承諾**。修：把 `-SIGTERM/-SIGKILL/137/143/142/timeout sentinel` 全歸 hang；`TimeoutExpired` 後強制 category=hang。
2. **PID-reuse 身分**：state 只存 pid/pgid + supervisor-generated started_at（state.py:152-160），health 只 `os.kill(pid,0)`（health.py:31-41）。修：persist OS process start_time，killpg 前驗 pid+start_time（plan §5 #2）。
3. **restart orphan cleanup**：`mark_supervisor_started()` 直接清 current_job（state.py:120-128），沒偵測/清 orphan。修：驗身分 → 殺舊 PGID → record completion → resume。
4. **state 非 atomic**：seek/truncate/dump/fsync（state.py:94-98）無 `os.replace()`（違 §7）。修：temp file + fsync + os.replace under LOCK_EX。
5. **fire claim 非 atomic**：scheduler 讀 snapshot 判 current_job is None（scheduler.py:145-151）後才 spawn，begin_fire 在 spawn 之後（worker.py:151-157）→ 兩 tick 可 double-spawn orphan（違 §5 #9/#10）。修：spawn 前 lock 內 reserve/claim。
6. **schedule 讀錯欄位**：`load_cron_expr()` 只讀 `cron`（scheduler.py:65-68），canonical 是 `schedule`（runtime_schedules.json:937）→ source drift；且 last_fire_at 空值會補跑上個 fire（fidelity 風險）。修：讀 `schedule`、明確決定是否允許 startup catch-up。
7. **broad except 吞例外**：scheduler/health loop 只 log 不 alert（scheduler.py:132-134/health.py:109-111）；supervisor crash 無 alert（supervisor.py:83-88）。修：加 escalation alert + 對應測試（負號 exit / PID reuse / concurrent tick / atomic write / schedule field）。

**狀態**：Deliverable 5 = review done(FAIL)。下一步 = 修這 7 項 → 重 review → 過了才 Deliverable 6 shadow。Phase A 已止 alert noise，**平台無立即風險**，可從容做。**email-11745 task 留 in_progress，close email 等 supervisor 上線。**

*Updated 2026-06-15 台灣時間 — Codex review FAIL with 7 must-fix; logged for next scoped fix session.*

### Deliverable 5 修整進度（hourly-12 fire，2026-06-15 12:07 台灣時間）

**完成 fix #1 + #6 / 7**（剩 5 個給後續 fires；每 fire 5-7 個 50min cap 內收 1-2 個）：

- **#1 致命 — signal exit 分類**（`scripts/dispatch_supervisor/worker.py`）：
  - 新增 `TIMEOUT_KILLED_SENTINEL = -1000` — `_run_one_attempt` 在 `subprocess.TimeoutExpired` 路徑無條件回此值（不再依賴從 `_kill_pgid` 後的 `proc.wait()` 解讀），`_classify` 認 sentinel 直接回 `hang`
  - 新增 `_normalize_signal_exit()` — 正常 wait() 收到負號（外部 SIGTERM/SIGKILL）統一 +128+signum 落入 `HANG_EXIT_CODES = {137, 142, 143}`
  - hang 分支寫 state 前把 sentinel 轉成 137（canonical SIGKILL），external observers 不會看到 `-1000`
  - **結果**：watchdog timeout 或外部 signal kill 都正確走 `killed_timeout` 路徑、無 retry、發 hang alert
- **#6 trivial — schedule 欄位 source drift**（`scripts/dispatch_supervisor/scheduler.py`）：
  - `load_cron_expr` 先讀 `schedule`（canonical），再讀 `cron`（legacy），再 fallback
  - 修正 `config/runtime_schedules.json` 的 `volpred-hourly-dispatch.cron = null` 但 `.schedule = "7 * * * *"` 的情況：ops 改 `schedule` supervisor 真會接到
- **Regression tests**（`tests/test_dispatch_supervisor.py` 新增 7 test）：
  - `test_classify_normalizes_negative_signal_codes` — -15/-9/-14 → 143/137/142、全 `hang`
  - `test_classify_timeout_sentinel_is_hang` — sentinel 路徑 hang
  - `test_worker_timeout_path_short_circuits_retry` — TimeoutExpired → 1 attempt + 1 hang alert + result.exit_code=137（非 -1000）
  - `test_worker_signal_killed_outside_timeout_also_classified_as_hang` — 外部 SIGTERM 走 normalize 路徑、無 retry
  - `test_load_cron_expr_reads_schedule_field_first` — canonical `schedule` 欄位讀對
  - `test_load_cron_expr_falls_back_to_legacy_cron_field` — legacy `cron` 還在
  - `test_load_cron_expr_returns_fallback_when_both_fields_empty` — defensive
- **pytest**: 18/18 PASS（11 既有 + 7 新加 regression）

**剩餘 5 個 must-fix（後續 hourly fires 推進）**：#2 PID-reuse 身分 / #3 restart orphan cleanup / #4 state 非 atomic / #5 fire claim 非 atomic / #7 broad except 吞例外。

**檔案改動**：
- `scripts/dispatch_supervisor/worker.py` — sentinel + normalize + sanitise hang exit code
- `scripts/dispatch_supervisor/scheduler.py` — schedule field priority
- `tests/test_dispatch_supervisor.py` — 7 regression tests

*Updated 2026-06-15 12:25 台灣時間 by hourly-12 fire — Deliverable 5 fix #1 + #6 / 7 landed (致命 + trivial); 5 remaining for future fires.*
