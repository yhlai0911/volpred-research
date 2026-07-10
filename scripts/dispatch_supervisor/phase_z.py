"""Git hygiene around a dispatch fire — the single owner of both ends.

Two entry points, both called from `scheduler._tick_once`:

  - `run_pre_fire_guard()`  — BEFORE the worker: conflict-marker / orphaned
    AUTO_MERGE backstop (port of the legacy shell's git_conflict_guard call).
  - `run_phase_z()`         — AFTER the worker: deterministic commit of
    whatever the dispatched agent left uncommitted.

Keeping both here (rather than scattering a third git-touching module into the
scheduler) means "git hygiene around a fire" has exactly one enforcement owner
— see `.claude/rules/control-plane.md` anti-stacking.

---

PHASE-Z safety net — deterministic post-fire commit of whatever the
dispatched agent left uncommitted.

Port of the `scripts/cron_hourly_dispatch.sh` PHASE-Z block (2026-05-29) into
the supervisor runtime (Deliverable 7 cutover, 2026-07-04). The dispatch
prompt asks the agent to run its own PHASE Z (`git add -A` + commit) but that
is agent-discretion → ~90% reliable: real fires (e.g. 2026-07-04 07:26 + 14:57)
leave real work untracked. Without this wrapper-level commit, once the
supervisor becomes the real dispatcher a dirty working tree would accumulate
between fires with nobody to clean it — the exact protection the legacy shell
provided and that fired twice on cutover day.

Semantics mirror legacy EXACTLY:

  1. `git status --porcelain` — empty → clean → no-op.
  2. dirty → first untrack any *already-tracked-but-gitignored* flat runtime
     state file (`git ls-files -ci --exclude-standard` — the ONLY ls-files
     combination that lists tracked-but-ignored paths; `git check-ignore`
     reports already-tracked paths as NOT ignored by design). This prevents
     the 2026-07-01 incident where a re-tracked `storage/.release_settings.json`
     let a PHASE-Z commit silently revert the boss's cadence directive.
  3. `git add -A` (gitignore keeps state/log noise out — but only for paths
     that were never tracked, hence step 2 first).
  4. `git commit -m "ops(dispatch-supervisor HH:MM): PHASE-Z safety-net auto-commit (agent left uncommitted)"`.

Differences from legacy (deliberate, same behaviour):
  - `subprocess.run(..., timeout=...)` replaces the `perl -e 'alarm N; exec'`
    wrapper (this codebase's convention — see procutil.get_process_start_wall).
  - Runs once per REAL fire (called from scheduler._tick_once after
    worker.run_worker returns), NOT per retry attempt: committing between a
    failed attempt-1 and its attempt-2 retry would snapshot a half-finished
    state. Legacy likewise ran PHASE-Z once at the wrapper's end, after the
    whole dispatch (all retries/failover) completed.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

# git op timeouts (seconds) — mirror legacy perl-alarm ceilings (status/add=30,
# commit=60). status/ls-files/rm/add share the short ceiling; commit gets long.
_SHORT_TIMEOUT_S = 30
_COMMIT_TIMEOUT_S = 60

# Flat runtime-state files that .gitignore covers but which have drifted back
# into tracking before (stash-pop, stray `git add`, pre-gitignore commit).
# Scoped to the exact legacy list — NOT the storage/ops/{tasks,agents,...}/
# directories (large historical content; needs a deliberate cleanup pass, not
# an unattended per-fire rm --cached) and never paper/*/main.pdf (force-tracked
# exception). Kept byte-for-byte in sync with cron_hourly_dispatch.sh PHASE-Z.
_LEAKED_STATE_PATHSPECS = (
    # supervisor's OWN runtime state — gitignored (.gitignore:88). Not in the
    # legacy list (it predates the supervisor) but MOST important here: PHASE-Z
    # runs right after the supervisor mutates this file every fire, so if it
    # ever drifts back into tracking, an unattended commit of heartbeat /
    # last_fire_at / completions would follow every fire (Codex review #1).
    "storage/ops/dispatch_state.json",
    "storage/ops/dashboard_latest.json",
    "storage/ops/alert_dedup.json",
    "storage/ops/cron_last_run.json",
    "storage/ops/pending_sessions.json",
    "storage/ops/gmail_inbox_state.json",
    "storage/ops/dispatch_report_latest.json",
    "storage/ops/handoff_latest.md",
    "storage/ops/writer_log.jsonl",
    "storage/.release_settings.json",
    "storage/.supabase_sync_state.json",
    "storage/market_status.json",
    "storage/notifications/*.json",
    "storage/session_state.json",
    "storage/work_log.json.append",
)


# ── pre-fire guard ───────────────────────────────────────────────────────────
# Byte-for-byte the legacy ceiling: cron_hourly_dispatch.sh:76 wrapped the guard
# in `perl -e 'alarm 30; exec'` after 2026-07-02, when `uv` hung >6min inside
# __private_getcwd and blocked a whole dispatch slot before it began.
_GUARD_TIMEOUT_S = 30
_GUARD_SCRIPT_RELPATH = ("scripts", "git_conflict_guard.py")


def run_pre_fire_guard(
    *,
    repo_root: Path,
    runner=subprocess.run,
) -> dict:
    """Run the conflict-marker / orphaned-AUTO_MERGE guard before a fire.

    Re-wire of `scripts/git_conflict_guard.py`, orphaned by the 2026-07-04
    supervisor cutover: its only caller was `cron_hourly_dispatch.sh`, whose
    LaunchAgent is now unloaded. The risk it was built for is unchanged — the
    dispatcher and the always-on `codex_loop.sh` still write the same branch
    concurrently, so a half-finished 3-way merge can orphan `.git/AUTO_MERGE`
    and inject `<<<<<<<` markers into `feed.json` / `next_tasks.json` /
    `work_log.json`, which the live site and the dispatcher then read
    (docs/error_log.md 2026-06-28).

    Contract, preserved from the legacy call site:

      - **fail-OPEN** — a missing script, spawn error, timeout, crash, or
        non-zero exit is logged and returns; it never vetoes the fire. This
        function has no failure mode that can return "don't dispatch".
      - **idempotent** — the guard no-ops on a clean tree.
      - **subprocess, not import** — a guard crash (or a hang in `git`) can
        never take down the daemon, and the hard timeout bounds it. Mirrors
        `scheduler._run_pregate`.

    Invoked with `sys.executable` rather than the legacy `uv run python`: the
    guard is pure-stdlib, so no venv resolution is needed, and this sidesteps
    the `uv` cwd-resolution hang above entirely.

    Returns an observability dict: ``ran`` (bool — did the guard execute),
    ``reason`` (str), plus ``guard_output`` when it printed anything. Never
    raises.
    """
    repo_root = Path(repo_root)
    script = repo_root.joinpath(*_GUARD_SCRIPT_RELPATH)
    if not script.exists():
        LOG.warning("pre_fire_guard: %s missing — no conflict backstop this fire", script)
        return {"ran": False, "reason": "guard_missing"}

    try:
        proc = runner(
            [sys.executable, str(script), "--quiet"],
            capture_output=True,
            text=True,
            timeout=_GUARD_TIMEOUT_S,
            cwd=str(repo_root),
            check=False,
        )
    except subprocess.TimeoutExpired:
        LOG.warning("pre_fire_guard: timeout after %ss — fail-open, firing anyway", _GUARD_TIMEOUT_S)
        return {"ran": False, "reason": "timeout"}
    except OSError as exc:
        LOG.warning("pre_fire_guard: spawn failed (%s) — fail-open, firing anyway", exc)
        return {"ran": False, "reason": "spawn_error"}

    # `--quiet` keeps the guard silent on a clean tree, so any output means it
    # acted (or warned). Forward it: the guard's own stdout is the only record
    # of which canonical blobs it restored.
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    for line in out.splitlines():
        LOG.info("pre_fire_guard: %s", line)

    if proc.returncode != 0:
        # The guard's main() returns 0 on every path, so this is a crash. Not
        # silent (see .claude/rules/no-silent-fallback.md) — but not a veto.
        LOG.warning("pre_fire_guard: exit=%d — fail-open, firing anyway", proc.returncode)
        return {"ran": True, "reason": "nonzero_exit", "exit_code": proc.returncode}

    result = {"ran": True, "reason": "ok"}
    if out:
        result["guard_output"] = out[-500:]
    return result


def _git(
    repo_root: Path,
    *args: str,
    timeout_s: int,
    runner=subprocess.run,
) -> subprocess.CompletedProcess:
    """Run `git -C <repo> <args>` with a hard timeout. Never raises on non-zero
    exit (check=False); callers inspect returncode. Raises TimeoutExpired /
    OSError, which run_phase_z catches and turns into an observable no-op."""
    return runner(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def run_phase_z(
    *,
    repo_root: Path,
    now_hhmm: str | None = None,
    runner=subprocess.run,
) -> dict:
    """Deterministic post-fire commit. Returns an observability dict.

    Returns keys: ``committed`` (bool), ``reason`` (str), and — when it acted —
    ``untracked`` (list of leaked-ignored paths removed from the index) and
    ``commit_head`` (stdout tail of `git commit`). Never raises: a git hiccup
    must not crash the supervisor tick, but it is always logged (no silent
    fallback per .claude/rules/no-silent-fallback.md).
    """
    repo_root = Path(repo_root)
    hhmm = now_hhmm or datetime.now().strftime("%H:%M")
    try:
        status = _git(repo_root, "status", "--porcelain", timeout_s=_SHORT_TIMEOUT_S, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: git status failed (%s) — skipping safety-net this fire", exc)
        return {"committed": False, "reason": "status_error"}

    if status.returncode != 0:
        # e.g. not a git repository / index lock. Do NOT misreport as "clean"
        # (empty stdout) — that would silently skip a real safety-net when the
        # tree could actually be dirty. Observable, no-op this fire.
        LOG.warning("phase_z: git status rc=%d: %s — skipping safety-net this fire",
                    status.returncode, (status.stderr or "").strip()[:200])
        return {"committed": False, "reason": "status_error"}

    if not (status.stdout or "").strip():
        LOG.info("phase_z: working tree clean — agent committed everything")
        return {"committed": False, "reason": "clean"}

    LOG.info("phase_z: uncommitted changes after dispatch — auto-committing")
    untracked: list[str] = []
    try:
        leaked = _git(
            repo_root, "ls-files", "-ci", "--exclude-standard", "--",
            *_LEAKED_STATE_PATHSPECS, timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
        if leaked.returncode != 0:
            # ls-files probe itself failed (Codex review #3): don't blindly
            # treat as "no leaked paths". Warn — we can't untrack this fire, but
            # committing real work still matters more than the rare leaked edge.
            LOG.warning("phase_z: git ls-files rc=%d: %s — cannot untrack leaked-ignored this fire",
                        leaked.returncode, (leaked.stderr or "").strip()[:200])
        else:
            for path in (leaked.stdout or "").splitlines():
                path = path.strip()
                if not path:
                    continue
                rm = _git(repo_root, "rm", "--cached", "-q", "--", path,
                          timeout_s=_SHORT_TIMEOUT_S, runner=runner)
                if rm.returncode == 0:
                    untracked.append(path)
                else:
                    LOG.warning("phase_z: git rm --cached %s rc=%d: %s",
                                path, rm.returncode, (rm.stderr or "").strip()[:200])
            if untracked:
                LOG.info("phase_z: untracked accidentally-tracked ignored state file(s): %s", untracked)
    except (subprocess.TimeoutExpired, OSError) as exc:
        # fall through to add+commit anyway — untracking is best-effort; the
        # commit of real work must still happen. Logged, not silent.
        LOG.warning("phase_z: leaked-ignored untrack step failed (%s) — proceeding to add/commit", exc)

    try:
        add = _git(repo_root, "add", "-A", timeout_s=_SHORT_TIMEOUT_S, runner=runner)
        if add.returncode != 0:
            # Codex review #3: a failed `git add -A` means the index is in an
            # unknown/partial state — committing now could snapshot a partial
            # tree. Abort this fire's safety-net (observable, no commit).
            LOG.warning("phase_z: git add -A rc=%d: %s — aborting commit (partial-index risk)",
                        add.returncode, (add.stderr or "").strip()[:200])
            return {"committed": False, "reason": "add_error", "untracked": untracked}
        commit = _git(
            repo_root, "commit", "-m",
            f"ops(dispatch-supervisor {hhmm}): PHASE-Z safety-net auto-commit (agent left uncommitted)",
            timeout_s=_COMMIT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: git add/commit failed (%s)", exc)
        return {"committed": False, "reason": "commit_error", "untracked": untracked}

    out = ((commit.stdout or "") + (commit.stderr or "")).strip()
    if commit.returncode == 0:
        LOG.info("phase_z: committed — %s", out.splitlines()[-1] if out else "(no output)")
        return {"committed": True, "reason": "committed", "untracked": untracked, "commit_head": out[-500:]}
    # Non-zero commit: distinguish the benign "nothing to commit" (everything
    # dirty was a leaked-ignored file already rm --cached'd, or a race cleaned
    # it) from a genuine commit failure.
    if "nothing to commit" in out.lower():
        LOG.info("phase_z: nothing to commit after staging (benign)")
        return {"committed": False, "reason": "nothing_to_commit", "untracked": untracked}
    LOG.warning("phase_z: git commit rc=%d: %s", commit.returncode, out[:300])
    return {"committed": False, "reason": "commit_nonzero", "untracked": untracked}
