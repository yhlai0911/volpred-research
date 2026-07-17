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
the supervisor runtime (Deliverable 7 cutover, 2026-07-04). The dispatch prompt
now explicitly forbids agent-side Git; the agent leaves a fire receipt and this
owner adopts only paths attributed to that fire. Without this wrapper-level
commit, a dirty working tree would accumulate between fires with nobody to
clean it — the exact protection the legacy shell provided and that fired twice
on cutover day.

Semantics (legacy, minus the `git add -A` that made it steal — see the ownership
block below and docs/error_log.md 2026-07-10):

  1. `git status --porcelain -z -uall` — empty → clean → no-op.
  2. no fire-start baseline → ownership unknown → commit NOTHING, alert. The work
     stays in the working tree; nobody's history gets rewritten.
  3. Build a candidate from HEAD in a temporary `GIT_INDEX_FILE`; add only this
     fire's paths and remove leaked tracked runtime state there. The shared index
     is never mutated, so another session's staged work cannot be stolen or lost.
  4. Run the tracked canonical pre-commit path against that candidate index.
     Failure discards the temporary index: HEAD/index/working bytes are unchanged.
  5. Create the candidate commit object and adopt it with `git update-ref`'s
     old-HEAD CAS. A concurrent HEAD advance wins; PHASE-Z never overwrites it.
  6. Test the exact adopted OID in a disposable clone and compare rc=1 failures
     against its exact parent. Only newly failing node ids emit CRITICAL.

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

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from volpred.ops.machine_churn import classify_machine_churn
from volpred.ops.git_writer_lock import (
    GitWriterLockError,
    git_writer_lock,
    git_writer_subprocess_kwargs,
    require_canonical_main_checkout,
)

LOG = logging.getLogger(__name__)

# git op timeouts (seconds) — mirror legacy perl-alarm ceilings (status/add=30,
# commit=60). status/ls-files/rm/add share the short ceiling; commit gets long.
_SHORT_TIMEOUT_S = 30
_COMMIT_TIMEOUT_S = 60

# post-commit test gate — see run_phase_z's post-commit block. Bound the pytest
# subset so a hung / pathological test suite can never wedge the supervisor tick
# (the gate already runs inside scheduler's asyncio.to_thread, but the thread
# itself must return). 600s = the same ceiling the task brief specifies.
_TEST_GATE_TIMEOUT_S = 600
# Only these three trees carry the code whose regressions a safety-net commit can
# smuggle into main (docs/error_log.md dab3baa12: a gmail_inbox_poll rewrite went
# in via PHASE-Z with a red test nobody saw for 5 days). experiments/ and paper/
# are research artifacts, not the runtime the gate protects.
_GATED_CODE_PREFIXES = ("src/volpred/", "scripts/", "tests/")
_TRUSTED_GATE_PATHS = {
    "scripts/audit_silent_fallbacks.py",
    "scripts/audit_test_imports.py",
    "scripts/git_hooks/pre-commit",
    "storage/qa/silent_fallback_baseline.json",
}
# pytest exit 5 = "no tests collected" — a keyword `-k` that matched nothing, NOT
# a failure. Classified as no_tests (observable), never as red.
_PYTEST_NO_TESTS_COLLECTED = 5

# What the parent revision actually proved. rc=0 and rc=5 are NOT the same
# baseline: only the first is evidence of green.  Keeping them apart is the whole
# point — see _classify_parent_baseline.
_BASELINE_GREEN = "green"
_BASELINE_RED = "red"
_BASELINE_NO_COVERAGE = "no_coverage"
_BASELINE_UNUSABLE = "unusable"

# Flat runtime-state files that .gitignore covers but which have drifted back
# into tracking before (stash-pop, stray `git add`, pre-gitignore commit).
# Scoped to the exact legacy list — NOT the storage/ops/{tasks,agents,...}/
# directories (large historical content; needs a deliberate cleanup pass, not
# an unattended per-fire rm --cached) and never paper/*/main.pdf (force-tracked
# exception). This list is now the only live one: cron_hourly_dispatch.sh's copy
# is launchctl-disabled (a rollback artifact), so its set stays frozen at the
# legacy entries and new entries land here only — do NOT "fix" that drift.
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
    # Append-only machine logs / markers with no reader outside this host: the
    # dedup gate's decision trail (tailed locally per .claude/rules/dedup-gate-audit.md)
    # and gmail_inbox_poll's last-dispatch timestamp. Tracked by accident; they are
    # rewritten by daemons between fires, so every fire found them dirty and with no
    # session to attribute them to → an hourly "not this fire's files" alert
    # (email-12038, boss: "一直爆警告"). Untracked, they stop being anybody's problem.
    "storage/logs/dedup_decisions.jsonl",
    "storage/ops/.last_email_immediate_dispatch",
    # 2026-07-17 (boss msg 918). Claude Code's machine-local permission file: every
    # session that allows one new Bash command rewrites it, so every fire found it
    # dirty with no session to attribute it to — 26 consecutive fires of「沒人收」on
    # a file nobody was ever going to commit, because committing one host's
    # permission list is not a deliverable. Same shape as the two above, and the
    # authorship test is what decides it, not the .claude/ prefix: the shared half
    # (env / hooks / team permissions) lives in .claude/settings.json and stays
    # tracked. Untracked, this half stops being anybody's problem.
    ".claude/settings.local.json",
)

# Canonical control-plane state that background daemons (gmail poll, pool refill,
# telegram responder, unblock sweep) rewrite between fires. Unlike the leaked state
# above it MUST stay tracked — next_tasks.json is the pending queue, and its history
# is the audit trail for what the platform was asked to do.
#
# It has no session owner, though, and PHASE-Z's model only knows two kinds of dirty
# file: "this fire produced it" and "another session is still typing it". Churn fell
# into the second bucket, so it was skipped and alerted on every single hour while
# nobody was ever going to come back and commit it. This module is its owner.
#
# Adoption is gated, because the failure mode is real: incident #1 (docs/error_log.md
# 2026-07-10) committed a next_tasks.json truncated mid-write as if it were history.
# See _classify_machine_churn — a file being written right now is left for the next
# fire, and a file that does not parse is escalated, never committed.
#
# Ownership is derived from the NAMESPACE, not from a list of filenames (2026-07-12).
# The list used to hold exactly one entry — next_tasks.json — so every other file the
# daemons write (dreaming runs, analytics snapshots, the compute queue, the event
# ledger, the token-usage report, publication candidates) fell through to "another
# session is still typing it" and was alerted on, hour after hour, by a module that
# was in fact its only possible owner. Eleven files had been sitting there for eight
# consecutive fires when the owner escalated (email-12123 / email-12124: 「不要再有
# 這種做了以後浪費掉的狀況」).
#
# That is the class bug, and enumerating the eleven would only have fixed the
# instance: the twelfth daemon to write a twelfth state file would have started the
# same hourly alarm the day it shipped. A prefix says what is true — everything under
# these roots is machine state with a scheduled writer and no commit step of its own —
# so a new state file is owned the moment it appears.
#
# The boundary that matters is authorship, not location: code and research output
# (scripts/, src/, experiments/, paper/, docs/, .claude/, storage/memory/) is written
# by an agent who is expected to commit it with a message and a test run. Those stay
# foreign, and a stuck one is a real leak worth an alert.
_MACHINE_STATE_PREFIXES = (
    "storage/ops/",              # dispatch/queue/dreaming/event-ledger/registry state
    "storage/analytics/",        # reader metrics snapshots
    "storage/reports/token_usage/",
    "ops/claude_user_backup/",   # settings mirror written by the backup job
    # 2026-07-13 class sweep (boss msg 624). Same authorship test as the four
    # above — a scheduled writer, no commit step, no session to hand it back to —
    # but they were missing from the list, so every fire saw them as "someone
    # else's uncommitted work", left them dirty, and the streak counter escalated
    # them to a critical「3 班沒人收」alert that nobody could ever action. Machine
    # state does not have an author to go ask.
    "storage/research/",         # arxiv candidate scans
    "storage/indicator_arena/",  # indicator review ledger
    # 2026-07-16 (boss msg 806「為什麼又出現一樣的錯誤」). The queue compactor
    # (scripts/unblock_expired_blocked_tasks.py) appends terminal task records here
    # from PRE-PHASE-0 of every fire. Same authorship test as next_tasks.json — it
    # IS next_tasks.json's overflow — but the file list only named the queue itself,
    # so the archive stayed foreign and the streak counter had been re-reporting it
    # as「沒人收」for 35 consecutive fires. Nobody was ever coming: the writer is a
    # machine and the fire that runs it has no reason to think it authored anything.
    "storage/next_tasks_archive/",
)
_MACHINE_STATE_FILES = (
    "storage/.failed_supabase_syncs.json",  # shared publisher/drain retry queue
    "storage/.knowledge_index_state.json",  # scheduled index freshness ledger
    "storage/next_tasks.json",       # the pending queue
    # Append-only ledger written through scripts/append_work_log.py — by fires, and
    # at 04:35 by a cron backfilling it from commits. No single author to hand it
    # back to, which is why it too was foreign for 35 fires. Adoption is safer here
    # than for the queue: append_work_log serializes on a sidecar lock and lands the
    # file with os.replace, so a reader sees a whole old version or a whole new one.
    "storage/work_log.json",
    "storage/publication_candidates.json",
    "storage/reports/feed.json",     # scheduled-release cron writes it; only agents commit it
    "storage/paper_trading.json",    # forward-tracking recalc; never hand-edited (publishing.md)
)


def _is_machine_state(rel: str) -> bool:
    """True when `rel` is daemon-written state this module is the sole owner of."""
    return rel in _MACHINE_STATE_FILES or rel.startswith(_MACHINE_STATE_PREFIXES)


# ── ownership: what did THIS fire produce? ───────────────────────────────────
# `git add -A` has no notion of authorship. It stages whatever is dirty, and the
# main checkout has several concurrent writers (the dispatched agent, an
# interactive session landing a worktree, codex_loop, cron jobs). Three separate
# incidents came out of that one assumption (docs/error_log.md 2026-07-10):
#   1. a `next_tasks.json` truncated mid-write by a crashed command was committed
#      as valid history;
#   2. `dab3baa12` swept a gmail_inbox_poll rewrite into main past the test gate
#      — red for 5 days;
#   3. an interactive session's half-finished `merge_worktree.sh` edits were
#      committed under an unrelated agent's message.
# Same root cause each time: the safety net cannot tell "the agent left this"
# from "someone is still typing this".
#
# The fix gives it that signal. `run_pre_fire_guard` runs BEFORE the worker, so
# it snapshots the dirty set at fire start; whatever is dirty at PHASE-Z time and
# was NOT dirty then is what this fire produced. Anything else belongs to another
# writer and is left alone — surfaced as an alert, never adopted. Auto-adoption is
# precisely what produced all three incidents, and it is the same hazard the
# orphan-branch alert already refuses to automate: a non-conflicting file is
# silently plausible and therefore silently wrong.
#
# The baseline lives inside the git dir, not under `storage/ops/`. A tracked-tree
# location would need a `.gitignore` rule to stay invisible, and PHASE-Z would
# then see its own baseline as work this fire produced — staging a path it is
# about to delete. `.git/` is per-checkout, survives a daemon restart, is never
# reported by `git status`, and can never be committed by anyone. One less rule
# to drift.
_SNAPSHOT_BASENAME = "volpred_phase_z_pre_fire_dirty.json"
# A failed candidate already has stronger ownership evidence than a later
# fire-start baseline: PHASE-Z itself computed the exact owned path set. Keep
# that evidence after the bounded drain gives up, hash-pinned to the bytes that
# the rejected candidate contained, so a later pre-fire pass can close it out
# without ever adopting an unrelated dirty path.
_FAILED_CLOSEOUT_BASENAME = "volpred_phase_z_failed_closeout.json"
# A fire is bounded by the worker timeout (~50min). A snapshot older than this is
# from a fire whose PHASE-Z never ran (daemon killed mid-fire); trusting it would
# mean judging today's dirt against yesterday's baseline.
_SNAPSHOT_MAX_AGE_S = 6 * 3600


def _snapshot_path(repo_root: Path, runner) -> Path | None:
    """`<git-dir>/volpred_phase_z_pre_fire_dirty.json`, or None if git won't say.

    `--absolute-git-dir` resolves to `.git/worktrees/<name>` inside a linked
    worktree, so each checkout keeps its own baseline instead of racing over one.
    """
    try:
        proc = _git(repo_root, "rev-parse", "--absolute-git-dir",
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: cannot resolve git dir (%s)", exc)
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        LOG.warning("phase_z: cannot resolve git dir (rc=%d)", proc.returncode)
        return None
    return Path(proc.stdout.strip()) / _SNAPSHOT_BASENAME


def _porcelain_paths(raw: str) -> set[str]:
    """Parse `git status --porcelain -z -uall` into a path set.

    NUL-delimited because paths may contain spaces or quotes (`core.quotePath`
    would otherwise hand back C-escaped octal that no `git add --` would match).
    Rename/copy entries carry a second, NUL-separated original path — both sides
    matter: the delete half and the add half are one edit by one author.
    """
    parts = raw.split("\0")
    paths: set[str] = set()
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:  # "XY path" — shorter means the trailing empty field
            continue
        xy, path = entry[:2], entry[3:]
        paths.add(path)
        if ("R" in xy or "C" in xy) and i < len(parts) and parts[i]:
            paths.add(parts[i])
            i += 1
    return paths


def _dirty_paths(repo_root: Path, runner) -> set[str] | None:
    """Current dirty set, or None if git could not tell us (never an empty set —
    "clean" and "we don't know" must not collapse into the same value).

    The baseline file cannot appear here — it lives in the git dir, which
    `git status` never walks.
    """
    try:
        proc = _git(repo_root, "status", "--porcelain", "-z", "--untracked-files=all",
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: dirty-set probe failed (%s)", exc)
        return None
    if proc.returncode != 0:
        LOG.warning("phase_z: dirty-set probe rc=%d: %s",
                    proc.returncode, (proc.stderr or "").strip()[:200])
        return None
    return _porcelain_paths(proc.stdout or "")


def _write_pre_fire_snapshot(repo_root: Path, paths: set[str], runner) -> bool:
    dest = _snapshot_path(repo_root, runner)
    if dest is None:
        return False
    payload = {"taken_at": datetime.now().timestamp(), "paths": sorted(paths)}
    try:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(dest)  # atomic: PHASE-Z must never read a half-written baseline
        return True
    except OSError as exc:
        LOG.warning("phase_z: cannot persist pre-fire snapshot (%s) — PHASE-Z will "
                    "not know what it owns and will decline to commit", exc)
        return False


def _read_pre_fire_snapshot(repo_root: Path, runner, now: float | None = None) -> set[str] | None:
    """The fire-start baseline, or None when it is missing/stale/corrupt.

    None means "ownership unknown", and run_phase_z declines to commit on it.
    Fail-closed on purpose: a wrong baseline commits other people's work, while
    no commit merely leaves the work dirty and alerted — recoverable either way,
    but only one of the two rewrites someone else's history.
    """
    src = _snapshot_path(repo_root, runner)
    if src is None:
        return None
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
        taken_at = float(payload["taken_at"])
        paths = payload["paths"]
        if not isinstance(paths, list):
            raise TypeError("paths is not a list")
    except FileNotFoundError:
        LOG.warning("phase_z: no pre-fire snapshot — pre-fire guard did not run this fire")
        return None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        LOG.warning("phase_z: pre-fire snapshot unreadable (%s)", exc)
        return None

    age = (now if now is not None else datetime.now().timestamp()) - taken_at
    if age > _SNAPSHOT_MAX_AGE_S or age < 0:
        LOG.warning("phase_z: pre-fire snapshot is %.0fs old — refusing a stale baseline", age)
        return None
    return set(paths)


def _consume_pre_fire_snapshot(repo_root: Path, runner) -> None:
    """One snapshot, one fire. Leaving it behind would let the next fire judge its
    own output against a baseline taken before someone else's edits."""
    path = _snapshot_path(repo_root, runner)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover — unlink of our own file
        LOG.warning("phase_z: cannot remove pre-fire snapshot (%s)", exc)


def _failed_closeout_path(repo_root: Path, runner) -> Path | None:
    snapshot = _snapshot_path(repo_root, runner)
    return snapshot.with_name(_FAILED_CLOSEOUT_BASENAME) if snapshot is not None else None


def _path_fingerprint(path: Path) -> dict[str, object] | None:
    """Stable working-tree fingerprint, including deletions and symlinks."""
    try:
        if path.is_symlink():
            return {"kind": "symlink", "target": os.readlink(path)}
        if not path.exists():
            return {"kind": "missing"}
        if not path.is_file():
            return {"kind": "other", "mode": path.stat().st_mode}
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return {"kind": "file", "sha256": digest.hexdigest(), "size": size}
    except OSError as exc:
        LOG.warning("phase_z: cannot fingerprint closeout path %s (%s)", path, exc)
        return None


def _read_failed_closeout(repo_root: Path, runner) -> dict | None:
    path = _failed_closeout_path(repo_root, runner)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["paths"]
        if not isinstance(entries, list) or not entries:
            raise TypeError("paths must be a non-empty list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise TypeError("invalid path entry")
            rel = Path(entry["path"])
            if rel.is_absolute() or ".." in rel.parts:
                raise TypeError("closeout path escapes repo root")
            if not isinstance(entry.get("fingerprint"), dict):
                raise TypeError("invalid fingerprint entry")
        return payload
    except (OSError, ValueError, TypeError, KeyError) as exc:
        LOG.warning("phase_z: failed-closeout receipt unreadable (%s) — fail closed", exc)
        return None


def _ensure_failed_closeout(
    repo_root: Path,
    *,
    owned: list[str],
    reason: str,
    commit_tail: str,
    receipt: dict | None,
    runner,
) -> bool:
    """Persist first-failure ownership once; never re-pin later edited bytes."""
    if not owned:
        return False
    dest = _failed_closeout_path(repo_root, runner)
    if dest is None:
        return False
    existing_payload = _read_failed_closeout(repo_root, runner) if dest.exists() else None
    if dest.exists() and existing_payload is None:
        return False
    existing_entries = {
        entry["path"]: entry["fingerprint"]
        for entry in (existing_payload or {}).get("paths", [])
    }
    entries: list[dict[str, object]] = []
    for rel in owned:
        fingerprint = _path_fingerprint(repo_root / rel)
        if fingerprint is None:
            return False
        if rel in existing_entries:
            # The first rejected candidate is the authority. Re-pinning an
            # overlapping path would bless bytes edited after that failure.
            if fingerprint != existing_entries[rel]:
                LOG.error("phase_z: failed-closeout path changed before a later failure: %s", rel)
                return False
            continue
        entries.append({"path": rel, "fingerprint": fingerprint})
    if existing_payload is not None:
        payload = existing_payload
        payload["paths"].extend(entries)
        payload.setdefault("receipts", []).append(receipt)
        payload["last_failure_at"] = datetime.now(timezone.utc).isoformat()
        payload["last_reason"] = reason
        payload["last_commit_tail"] = commit_tail[-1200:]
    else:
        payload = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_failure_at": datetime.now(timezone.utc).isoformat(),
            "last_reason": reason,
            "last_commit_tail": commit_tail[-1200:],
            "receipts": [receipt],
            "paths": entries,
        }
    try:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(dest)
        LOG.warning(
            "phase_z: preserved hash-pinned failed closeout for %d total path(s)",
            len(payload["paths"]),
        )
        return True
    except OSError as exc:
        LOG.warning("phase_z: cannot persist failed-closeout receipt (%s)", exc)
        return False


def _clear_failed_closeout(repo_root: Path, runner) -> None:
    path = _failed_closeout_path(repo_root, runner)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        LOG.warning("phase_z: cannot clear failed-closeout receipt (%s)", exc)


def _paths_carried_forward(repo_root: Path, since_iso: str | None, runner) -> set[str]:
    """Paths some commit touched after the receipt was written.

    Asks git rather than keeping a list of "hot" state files. A shared ledger
    (`storage/work_log.json`, the task archive, token-usage reports) is appended
    to by every fire and cron worker, so a day-old byte-pin can never match it
    again — but that drift is the healthy path, not a hazard: the next writer
    commits the whole file, carrying the failed fire's lines along with its own.
    A hardcoded blocklist would have to name every such file and would rot the
    day someone adds the next one; "a later commit already took this path" is the
    same question answered from the history itself.

    Fails closed (empty set) when git won't say — an unanswered question must not
    read as "carried forward".
    """
    if not since_iso:
        return set()
    try:
        proc = _git(repo_root, "log", f"--since={since_iso}", "--name-only", "-z",
                    "--format=", timeout_s=_SHORT_TIMEOUT_S, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: carried-forward probe failed (%s)", exc)
        return set()
    if proc.returncode != 0:
        LOG.warning("phase_z: carried-forward probe failed (rc=%d)", proc.returncode)
        return set()
    return {path for path in (proc.stdout or "").split("\0") if path}


def recover_failed_closeout(
    *,
    repo_root: Path,
    runner=subprocess.run,
    test_runner=None,
    alert_fn=None,
) -> dict:
    """Retry a rejected fire's exact, unchanged paths before the next fire.

    This is not orphan adoption. The durable receipt was written by PHASE-Z at
    the original candidate failure and pins every path to its bytes (or deletion
    state). A mismatch on a path this recovery would still stage refuses recovery
    and leaves both bytes and receipt for human review.

    A pinned path that is no longer dirty is DONE, whatever it now holds: the
    working tree agrees with HEAD, so recovery would stage nothing for it and can
    misattribute nothing. Its bytes drifting means a later fire committed newer
    work under its own baseline — normal progress, not a hazard. Checking the
    hash before asking whether the path still needs committing is what pinned a
    finished receipt into a permanent hourly CRITICAL: 34 of 40 paths had already
    been committed by later fires and 6 hot state files (work_log.json, the task
    archive, token-usage reports) had legitimately moved on, so every fire for 25
    hours re-sent the same alert about work that was never at risk
    (error_log 2026-07-17).
    """
    repo_root = Path(repo_root)
    payload = _read_failed_closeout(repo_root, runner)
    if payload is None:
        return {"committed": False, "reason": "no_failed_closeout"}
    dirty = _dirty_paths(repo_root, runner)
    if dirty is None:
        return {"committed": False, "reason": "status_error"}

    carried = _paths_carried_forward(repo_root, payload.get("created_at"), runner)
    unresolved: list[str] = []
    conflicts: list[str] = []
    landed: list[str] = []
    for entry in payload["paths"]:
        rel = entry["path"]
        if rel not in dirty:
            landed.append(rel)
            continue
        if _path_fingerprint(repo_root / rel) != entry["fingerprint"]:
            # Drifted and dirty. If a later commit already took this path, that
            # shift carried the content forward and is now its owner; only an
            # edit no commit ever picked up is an unstaged-output conflict.
            (landed if rel in carried else conflicts).append(rel)
        else:
            unresolved.append(rel)

    if not unresolved and not conflicts:
        # Every pinned path reached HEAD. Nothing to recover, nothing to warn.
        _clear_failed_closeout(repo_root, runner)
        return {"committed": False, "reason": "already_closed", "landed": landed}
    if conflicts:
        (alert_fn or _default_alert)(
            level="critical",
            title="PHASE-Z failed-closeout 內容已變更，拒絕跨班提交",
            body="\n".join([
                "原 fire 的 ownership receipt 還在，但下列尚未提交的路徑已不再等於被 gate 擋下時的 bytes。",
                "為避免把後來 session 的修改冒充原 fire 產出，系統沒有 commit 或覆蓋任何檔案。",
                "",
                *[f"- {path}" for path in conflicts],
            ]),
        )
        return {"committed": False, "reason": "hash_mismatch", "conflicts": conflicts}

    subjects = [
        str(item.get("subject") or "").strip()
        for item in (payload.get("receipts") or [])
        if isinstance(item, dict) and str(item.get("subject") or "").strip()
    ]
    stored_receipt = {
        "subject": "recover hash-pinned PHASE-Z closeout",
        "body": "\n".join([
            "Original candidate(s) failed their commit gate; every recovered path remained byte-identical.",
            *[f"- {subject}" for subject in subjects[:20]],
        ]),
        "task_id": "",
    }
    result = run_phase_z(
        repo_root=repo_root,
        runner=runner,
        test_runner=test_runner,
        alert_fn=alert_fn,
        pre_fire_dirty=dirty - set(unresolved),
        commit_receipt_override=stored_receipt,
        recovery_mode=True,
    )
    if result.get("committed"):
        _clear_failed_closeout(repo_root, runner)
    return result


# ── fire commit receipt ──────────────────────────────────────────────────────
# The 3-strike fix (2026-07-13; docs/refactor_plan_agent_output_ownership.md).
#
# Committing is a MECHANICAL act. The fire-start baseline above already knows
# exactly which paths this fire produced — better than the agent does, which can
# only recall what it *thinks* it touched. That guess is how `git add -A` swept
# three other sessions' half-finished edits into a dispatch commit
# (docs/error_log.md 2026-07-10). So git belongs to this module, and the prompt
# stops asking the agent to run it.
#
# What the agent alone knows is WHY. That is all it is still asked for: a receipt
# carrying the commit subject/body. Moving the discretion here changes the failure
# mode from structural to cosmetic — an agent that forgets its receipt costs an
# audit-quality message, not a dirty tree, not a next-shift steal, not a lost
# experiment.
#
# Same git-dir home as the pre-fire snapshot, for the same reasons (invisible to
# `git status`, per-checkout, never committable) — see _SNAPSHOT_BASENAME.
_RECEIPT_BASENAME = "volpred_fire_commit_msg.json"
_RECEIPT_MAX_AGE_S = _SNAPSHOT_MAX_AGE_S  # a receipt goes stale exactly like a baseline
_RECEIPT_SUBJECT_MAX = 120  # git convention; longer subjects wrap badly in `git log --oneline`


def _receipt_path(repo_root: Path, runner) -> Path | None:
    """`<git-dir>/volpred_fire_commit_msg.json` — see _snapshot_path for why git-dir."""
    snap = _snapshot_path(repo_root, runner)
    return None if snap is None else snap.with_name(_RECEIPT_BASENAME)


def write_fire_receipt(
    repo_root: Path,
    *,
    subject: str,
    body: str = "",
    task_id: str = "",
    runner=subprocess.run,
) -> bool:
    """Record WHY this fire changed the tree. Called by the agent via scripts/fire_receipt.py.

    Not an enforcement point — PHASE-Z commits with or without this. It only
    upgrades the commit message from a generated fallback to the agent's own
    account of what it did.
    """
    dest = _receipt_path(repo_root, runner)
    if dest is None:
        return False
    subject = " ".join(subject.split())[:_RECEIPT_SUBJECT_MAX].strip()
    if not subject:
        LOG.warning("phase_z: refusing an empty receipt subject")
        return False
    payload = {
        "written_at": datetime.now().timestamp(),
        "subject": subject,
        "body": body.strip(),
        "task_id": task_id.strip(),
    }
    try:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dest)  # atomic: PHASE-Z must never read a half-written receipt
        return True
    except OSError as exc:
        LOG.warning("phase_z: cannot persist fire receipt (%s) — commit will use a "
                    "generated message", exc)
        return False


def _parse_fire_receipt(raw: str, now: float) -> dict | None:
    """Validate raw receipt bytes. Shared by the consuming read and the hook's peek,
    so the gate and the commit can never disagree about what counts as a receipt."""
    try:
        payload = json.loads(raw)
        subject = " ".join(str(payload["subject"]).split()).strip()
        written_at = float(payload["written_at"])
    except (ValueError, TypeError, KeyError) as exc:
        LOG.warning("phase_z: fire receipt malformed (%s) — using a generated message", exc)
        return None
    if not subject:
        LOG.warning("phase_z: fire receipt has an empty subject — using a generated message")
        return None

    age = now - written_at
    if age > _RECEIPT_MAX_AGE_S or age < 0:
        LOG.warning("phase_z: fire receipt is %.0fs old — refusing a stale message", age)
        return None
    return {
        "subject": subject[:_RECEIPT_SUBJECT_MAX],
        "body": str(payload.get("body") or "").strip(),
        "task_id": str(payload.get("task_id") or "").strip(),
    }


def _read_and_consume_fire_receipt(repo_root: Path, runner, now: float | None = None) -> dict | None:
    """Read the receipt and delete it in the same breath — one fire, one receipt.

    Read-and-consume (rather than read-now-delete-later) because run_phase_z has
    many exit paths: a receipt left behind by a clean-tree fire would caption the
    NEXT fire's commit with the previous fire's reasons. There is no exit path
    from which this can leak, by construction.
    """
    src = _receipt_path(repo_root, runner)
    if src is None:
        return None
    try:
        raw = src.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None  # silent-ok: no receipt is the documented fallback path, not an error
    except OSError as exc:
        LOG.warning("phase_z: fire receipt unreadable (%s)", exc)
        return None
    finally:
        try:
            src.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover — unlink of our own file
            LOG.warning("phase_z: cannot remove fire receipt (%s)", exc)

    return _parse_fire_receipt(raw, now if now is not None else datetime.now().timestamp())


def fire_output_needs_receipt(
    repo_root: Path, runner=subprocess.run, now: float | None = None,
) -> dict:
    """Would PHASE-Z have to caption this fire's commit itself?

    The Stop-hook gate (`scripts/hooks/enforce_fire_receipt.py`) asks this the moment
    the agent tries to end its turn — while it is still alive to write the receipt.
    Asking at commit time was too late, which is why 70% of dispatch commits carried
    a generated message (boss, 2026-07-16 Telegram msg 886) and the resulting warn
    became hourly noise instead of a signal.

    STRICTLY read-only: it must not consume the receipt or the snapshot. Both belong
    to run_phase_z, which runs after the agent exits; eating either here would blind
    the real commit. Callers get a verdict, never a side effect.
    """
    reply = {"needs_receipt": False, "owned": [], "reason": ""}
    dest = _receipt_path(repo_root, runner)
    if dest is None:
        reply["reason"] = "not_a_git_repo"
        return reply

    snap = _snapshot_path(repo_root, runner)
    if snap is None or not snap.exists():
        # No fire-start baseline → not a dispatch fire (or the guard never ran).
        # Ownership is unknowable, and PHASE-Z declines to commit without a
        # baseline anyway, so there is nothing a receipt could caption.
        reply["reason"] = "not_a_fire"
        return reply

    try:
        if dest.exists() and _parse_fire_receipt(
            dest.read_text(encoding="utf-8"),
            now if now is not None else datetime.now().timestamp(),
        ):
            reply["reason"] = "receipt_present"
            return reply
    except OSError as exc:
        LOG.warning("phase_z: receipt peek failed (%s) — letting the fire end", exc)
        reply["reason"] = "receipt_unreadable"
        return reply

    dirty_now = _dirty_paths(repo_root, runner)
    if dirty_now is None:
        reply["reason"] = "status_error"  # fail open: never trap an agent on a probe error
        return reply
    if not dirty_now:
        reply["reason"] = "clean"
        return reply

    baseline = _read_pre_fire_snapshot(repo_root, runner)
    if baseline is None:
        reply["reason"] = "no_baseline"
        return reply

    # Same arithmetic as run_phase_z's `owned` — one definition, two callers.
    # Machine churn is excluded: a daemon-written path is this module's own
    # bookkeeping, not an agent decision, and has no "why" to account for.
    owned = sorted(p for p in (dirty_now - baseline) if not _is_machine_state(p))
    if not owned:
        reply["reason"] = "nothing_owned"
        return reply
    reply["needs_receipt"] = True
    reply["owned"] = owned
    reply["reason"] = "needs_receipt"
    return reply


def _generated_subject(owned: list[str]) -> str:
    """A degraded WHAT, derived from the diff, for a fire that left no receipt.

    Never as good as the agent's own account — the diff shows what moved, never why.
    But 「本班產出未附說明」 told the reader nothing at all, which is what made the
    audit gap feel like a system fault in `git log` (boss, msg 886).
    """
    groups: dict[str, int] = {}
    for path in owned:
        parts = path.split("/")
        key = "/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] if parts else path)
        groups[key] = groups.get(key, 0) + 1
    top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    shown = "、".join(f"{name}({count})" for name, count in top)
    if len(groups) > len(top):
        shown += f" 等 {len(groups)} 處"
    return f"自動摘要（agent 未留 receipt）: 動到 {shown}"


# ── foreign paths that never clear ───────────────────────────────────────────
# One fire finding a foreign path means a session is mid-edit; harmless. The same
# path still foreign fire after fire means nobody is coming back for it, and a
# `warn` that repeats hourly reads as noise instead of a leak. Owner directive
# (2026-07-11): escalate on persistence. The count lives next to the pre-fire
# snapshot in the git dir — same reasons (invisible to `git status`, per-checkout,
# never committable).
_FOREIGN_STREAK_BASENAME = "volpred_phase_z_foreign_streak.json"
_FOREIGN_STREAK_CRITICAL = 3  # consecutive fires before warn → critical


def _bump_foreign_streaks(repo_root: Path, runner, foreign: list[str]) -> dict[str, int]:
    """Consecutive-fire count per still-foreign path; paths that cleared drop out."""
    snapshot = _snapshot_path(repo_root, runner)
    if snapshot is None:
        return {p: 1 for p in foreign}
    dest = snapshot.with_name(_FOREIGN_STREAK_BASENAME)
    prev: dict[str, int] = {}
    try:
        if dest.exists():
            raw = json.loads(dest.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                prev = {k: int(v) for k, v in raw.items()
                        if isinstance(k, str) and isinstance(v, int)}
    except (OSError, ValueError, TypeError) as exc:
        LOG.warning("phase_z: cannot read foreign-streak state (%s) — restarting counts", exc)
    current = {p: prev.get(p, 0) + 1 for p in foreign}
    try:
        if current:
            tmp = dest.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(dest)
        else:
            dest.unlink(missing_ok=True)
    except OSError as exc:
        LOG.warning("phase_z: cannot persist foreign-streak state (%s) — counts reset next fire", exc)
    return current


def _classify_machine_churn(repo_root: Path, candidates: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split declared machine-churn paths into (committable, deferred, corrupt).

    The lock/parse gates moved to ``volpred.ops.machine_churn`` on 2026-07-16 so the
    scheduled writers in ``scripts/`` could ask the same question this module asks —
    daily_update's dirty-guard was answering it with a bare dirty flag and latching
    itself shut. One implementation, two callers; see that module for the reasoning.
    """
    return classify_machine_churn(repo_root, candidates, label="phase_z")


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
    git_runner=subprocess.run,
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

    Also snapshots the dirty set at fire start — see the ownership block above.
    That happens FIRST, before the guard repairs anything: the guard's own
    restorations are this fire's output and must be committable, and a snapshot
    taken after them would strand the repaired files as permanently "foreign".
    The snapshot is taken on every path out of this function (a missing guard
    script must not also cost PHASE-Z its baseline).

    Returns an observability dict: ``ran`` (bool — did the guard execute),
    ``reason`` (str), ``dirty_at_fire_start`` (int — baseline size, -1 if the
    probe failed), plus ``guard_output`` when it printed anything. Never raises.
    """
    repo_root = Path(repo_root)

    # `git_runner` is separate from `runner`: the latter fakes the guard
    # subprocess in tests, and a fake that answers `[sys.executable, guard]`
    # cannot also answer `git status`.
    baseline = _dirty_paths(repo_root, git_runner)
    if baseline is None or not _write_pre_fire_snapshot(repo_root, baseline, git_runner):
        # No baseline → PHASE-Z will decline to commit and say so. Fail-open for
        # the fire itself (this function may never veto a dispatch), fail-closed
        # for the commit that follows it.
        snapshot_size = -1
    else:
        snapshot_size = len(baseline)
        LOG.info("pre_fire_guard: baselined %d dirty path(s) at fire start", snapshot_size)

    script = repo_root.joinpath(*_GUARD_SCRIPT_RELPATH)
    if not script.exists():
        LOG.warning("pre_fire_guard: %s missing — no conflict backstop this fire", script)
        return {"ran": False, "reason": "guard_missing", "dirty_at_fire_start": snapshot_size}

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
        return {"ran": False, "reason": "timeout", "dirty_at_fire_start": snapshot_size}
    except OSError as exc:
        LOG.warning("pre_fire_guard: spawn failed (%s) — fail-open, firing anyway", exc)
        return {"ran": False, "reason": "spawn_error", "dirty_at_fire_start": snapshot_size}

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
        return {"ran": True, "reason": "nonzero_exit", "exit_code": proc.returncode,
                "dirty_at_fire_start": snapshot_size}

    result = {"ran": True, "reason": "ok", "dirty_at_fire_start": snapshot_size}
    if out:
        result["guard_output"] = out[-500:]
    return result


def _git(
    repo_root: Path,
    *args: str,
    timeout_s: int,
    runner=subprocess.run,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run `git -C <repo> <args>` with a hard timeout. Never raises on non-zero
    exit (check=False); callers inspect returncode. Raises TimeoutExpired /
    OSError, which run_phase_z catches and turns into an observable no-op."""
    kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_s,
        "check": False,
    }
    kwargs.update(git_writer_subprocess_kwargs(env))
    return runner(["git", "-C", str(repo_root), *args], **kwargs)


def _parse_stage_entries(raw: str, *, tree: bool = False) -> dict[str, tuple[str, ...]]:
    """Parse NUL-delimited ``ls-files --stage`` / ``ls-tree`` output by path."""
    entries: dict[str, list[str]] = {}
    for record in (raw or "").split("\0"):
        if not record or "\t" not in record:
            continue
        meta, path = record.split("\t", 1)
        fields = meta.split()
        if tree:
            if len(fields) < 3:
                continue
            normalized = f"{fields[0]} {fields[2]} 0"
        else:
            if len(fields) < 3:
                continue
            normalized = f"{fields[0]} {fields[1]} {fields[2]}"
        entries.setdefault(path, []).append(normalized)
    return {path: tuple(sorted(values)) for path, values in entries.items()}


def _shared_index_entries(
    repo_root: Path,
    paths: list[str],
    *,
    runner,
    env: dict[str, str] | None = None,
) -> dict[str, tuple[str, ...]] | None:
    if not paths:
        return {}
    try:
        proc = _git(
            repo_root, "ls-files", "--stage", "-z", "--", *paths,
            timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: ls-files --stage failed (%s) — baseline unavailable, fail closed", exc)
        return None
    if proc.returncode != 0:
        return None
    parsed = _parse_stage_entries(proc.stdout or "")
    return {path: parsed.get(path, ()) for path in paths}


def _base_tree_entries(
    repo_root: Path,
    base_sha: str,
    paths: list[str],
    *,
    runner,
) -> dict[str, tuple[str, ...]] | None:
    if not paths:
        return {}
    try:
        proc = _git(
            repo_root, "ls-tree", "-r", "-z", base_sha, "--", *paths,
            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: ls-tree %s failed (%s) — base entries unavailable, fail closed", base_sha[:8], exc)
        return None
    if proc.returncode != 0:
        return None
    parsed = _parse_stage_entries(proc.stdout or "", tree=True)
    return {path: parsed.get(path, ()) for path in paths}


def _refresh_shared_index_cas(
    repo_root: Path,
    *,
    base_sha: str,
    committed_sha: str,
    candidate_paths: list[str],
    runner,
) -> dict:
    """Refresh only candidate paths whose shared-index entry still equals base.

    ``.git/index.lock`` is the Git-wide exclusion primitive.  We copy the current
    index into that lock, compare each candidate path to the pinned base tree,
    update only unchanged entries, then atomically adopt the lock.  A concurrent
    ``git add`` either lands before the lock and is preserved by the comparison,
    or observes the lock and cannot race between compare and replace.
    """
    try:
        probe = _git(
            repo_root, "rev-parse", "--git-path", "index",
            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "reason": "index_path_error", "detail": str(exc)[:300]}
    if probe.returncode != 0 or not (probe.stdout or "").strip():
        return {"ok": False, "reason": "index_path_error", "detail": (probe.stderr or "")[-300:]}
    index_path = Path((probe.stdout or "").strip())
    if not index_path.is_absolute():
        index_path = repo_root / index_path
    lock_path = index_path.with_name(index_path.name + ".lock")

    fd: int | None = None
    adopted = False
    owns_lock = False
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        owns_lock = True
        with os.fdopen(fd, "wb") as handle:
            fd = None
            with index_path.open("rb") as source:
                shutil.copyfileobj(source, handle)

        locked_env = os.environ.copy()
        locked_env["GIT_INDEX_FILE"] = str(lock_path)
        current = _shared_index_entries(
            repo_root, candidate_paths, runner=runner, env=locked_env,
        )
        base = _base_tree_entries(repo_root, base_sha, candidate_paths, runner=runner)
        if current is None or base is None:
            return {"ok": False, "reason": "index_compare_error"}
        refreshable = [path for path in candidate_paths if current[path] == base[path]]
        preserved = [path for path in candidate_paths if current[path] != base[path]]
        if not refreshable:
            return {"ok": True, "refreshed": [], "preserved": preserved}

        reset = _git(
            repo_root, "reset", "-q", committed_sha, "--", *refreshable,
            timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=locked_env,
        )
        if reset.returncode != 0:
            return {"ok": False, "reason": "index_refresh_error", "detail": (reset.stderr or "")[-300:]}
        os.replace(lock_path, index_path)
        adopted = True
        return {"ok": True, "refreshed": refreshable, "preserved": preserved}
    except FileExistsError:
        return {"ok": False, "reason": "index_busy"}
    except OSError as exc:
        return {"ok": False, "reason": "index_refresh_error", "detail": str(exc)[:300]}
    finally:
        if fd is not None:
            os.close(fd)
        if owns_lock and not adopted:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass  # silent-ok: the CRITICAL caller reports failed refresh


def _default_alert(*, level: str, title: str, body: str) -> dict:
    """Ship a red-gate alert through the canonical Python send_alert API.

    Deferred import (matches alerts.py's own lazy-import convention) so phase_z
    stays stdlib-only at module load — the supervisor imports it every fire and a
    heavy `volpred.ops` import chain at that point would slow every tick. A send
    failure is logged, never raised: the alert is a notification, and a broken
    mailer must not turn a red-test observation into a crashed tick."""
    try:
        from volpred.ops.alerts import send_alert

        return send_alert(level, title, body)
    except Exception as exc:  # noqa: BLE001 — notification path, never fatal
        LOG.warning("phase_z: test-gate alert send failed (%s)", exc)
        return {"sent": False, "error": str(exc)[:200]}


def _coerce_observed_at(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        LOG.warning("phase_z: invalid internal alert observed_at=%r (%s)", value, exc)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_internal_alert(
    *,
    alert_key: str,
    level: str,
    title: str,
    body: str,
    observed_at=None,
    fingerprint=None,
) -> dict:
    """Route a mechanically repairable PHASE-Z signal to P1 work first."""

    try:
        from volpred.ops.alerts import route_internal_remediable_alert

        return route_internal_remediable_alert(
            alert_key=alert_key,
            level=level,
            title=title,
            body=body,
            now=_coerce_observed_at(observed_at),
            fingerprint=fingerprint,
        )
    except Exception as exc:  # noqa: BLE001 — routing failure is observable, tick remains alive
        LOG.warning("phase_z: internal alert routing failed (%s)", exc)
        return {"sent": False, "error": str(exc)[:200]}


def _default_internal_resolve(*, alert_key: str, storage_dir: str, observed_at=None) -> dict:
    """Close a prior PHASE-Z internal incident after the detector recovers."""

    try:
        from volpred.ops.alerts import resolve_internal_remediable_alert

        return resolve_internal_remediable_alert(
            alert_key=alert_key,
            storage_dir=storage_dir,
            now=_coerce_observed_at(observed_at),
        )
    except Exception as exc:  # noqa: BLE001 — observable housekeeping, tick remains alive
        LOG.warning("phase_z: internal alert resolution failed (%s)", exc)
        return {"resolved": False, "error": str(exc)[:200]}


def _is_silent_fallback_gate_output(output: str) -> bool:
    """True only for Gate 2's explicit NEW-silent-fallback verdict."""

    normalized = " ".join(str(output or "").lower().split())
    return (
        "introduces new silent fallback" in normalized
        and "silent-fallback-audit" in normalized
        and re.search(r"\bnew=[1-9][0-9]*\b", normalized) is not None
    )


def _is_silent_fallback_clean_gate_output(output: str) -> bool:
    """True only when trusted Gate 2 emitted its explicit clean receipt."""

    normalized = " ".join(str(output or "").lower().split())
    return "silent-fallback-audit passed new=0 scope=" in normalized


_SILENT_FALLBACK_NEW_RE = re.compile(r"\bNEW\s+(\S+:\d+)\b")


def _silent_fallback_fingerprints(output: str) -> list[str]:
    """`file:line` identity of each NEW silent fallback the gate flagged.

    audit_silent_fallbacks.py prints ``NEW <path>:<line> except ...`` per finding.
    A disjoint fingerprint set means a *different* file tripped the coarse
    ``silent_fallback_new`` key — a distinct incident, not a failed repair — so
    the escalation counter must not conflate them (2026-07-15 false escalation).
    """

    return sorted({m.group(1) for m in _SILENT_FALLBACK_NEW_RE.finditer(str(output or ""))})


def _test_files_referencing_stem(tests_dir: Path, stem: str) -> list[Path]:
    """Test files whose filename or source references ``stem``.

    Pytest ``-k`` matches node metadata, not source bodies.  Returning concrete
    files avoids the old false mapping where an import in a generically named
    test file made us run ``-k stem`` and collect zero tests.
    """
    matches: list[Path] = []
    for path in sorted(tests_dir.rglob("*.py")):
        if stem in path.name:
            matches.append(path)
            continue
        try:
            if stem in path.read_text(encoding="utf-8", errors="ignore"):
                matches.append(path)
        except OSError as exc:
            LOG.warning("phase_z: could not scan %s for stem %r (%s)", path, stem, exc)
            continue
    return matches


def _resolve_test_targets(repo_root: Path, code_files: list[str]) -> dict:
    """Map committed code files → a pytest run plan.

    Per changed `<tree>/…/<stem>.py`:
      - precise: `tests/test_<stem>*.py` exists → run those files by path.
      - source-reference fallback: no precise filename but `<stem>` appears in
        test source → run those concrete files (never misuse ``-k`` as grep).
      - unmapped: `<stem>` appears nowhere → recorded, never counted as passed.

    The returned plan always uses concrete files.  This is intentionally wider
    than a keyword filter, but cannot silently collect zero due to a generic test
    function name."""
    test_roots = [p for p in (repo_root / "tests", repo_root / "scripts" / "tests") if p.is_dir()]
    precise_files: set[str] = set()
    unmapped: list[str] = []
    for changed in code_files:
        changed_path = repo_root / changed
        if (
            changed_path.is_file()
            and (changed.startswith("tests/") or changed.startswith("scripts/tests/"))
            and changed_path.name.startswith("test_")
        ):
            precise_files.add(changed)
            continue
        stem = Path(changed).stem
        if stem.startswith("__"):
            # __init__.py / dunder modules have no meaningful test-file stem.
            continue
        matches = sorted(
            match
            for tests_dir in test_roots
            for match in tests_dir.rglob(f"test_{stem}*.py")
        )
        if matches:
            precise_files.update(str(m.relative_to(repo_root)) for m in matches)
        else:
            referenced = sorted(
                match
                for tests_dir in test_roots
                for match in _test_files_referencing_stem(tests_dir, stem)
            )
            if referenced:
                precise_files.update(str(m.relative_to(repo_root)) for m in referenced)
            else:
                unmapped.append(changed)

    return {"targets": sorted(precise_files), "k_expr": None, "unmapped": unmapped}


_PYTEST_FAILURE_RE = re.compile(r"^(?:FAILED|ERROR)\s+([^\s]+)", re.MULTILINE)


def _pytest_failure_ids(output: str) -> set[str]:
    """Stable node ids from pytest's short summary (best effort for fake runners)."""
    return set(_PYTEST_FAILURE_RE.findall(output or ""))


def _junit_failure_ids(path: Path) -> set[str]:
    """Machine-readable failing testcase identities; malformed/missing XML falls back to stdout."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return set()
    failures: set[str] = set()
    for case in root.iter("testcase"):
        if not any(child.tag.rsplit("}", 1)[-1] in {"failure", "error"} for child in case):
            continue
        file_name = case.attrib.get("file", "")
        class_name = case.attrib.get("classname", "")
        test_name = case.attrib.get("name", "")
        failures.add("::".join(part for part in (file_name, class_name, test_name) if part))
    return failures


def _clone_revision(repo_root: Path, destination: Path, revision: str, *, runner) -> dict:
    """Materialise one revision in a disposable clone; never run in the live checkout."""
    try:
        clone = runner(
            ["git", "clone", "--quiet", "--shared", "--no-checkout", str(repo_root), str(destination)],
            capture_output=True,
            text=True,
            timeout=_SHORT_TIMEOUT_S,
            check=False,
        )
        if clone.returncode != 0:
            return {"ok": False, "reason": "clone_error", "detail": (clone.stderr or "")[-400:]}
        checkout = _git(
            destination, "checkout", "--quiet", "--detach", revision,
            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "clone_timeout"}
    except OSError as exc:
        return {"ok": False, "reason": "clone_error", "detail": str(exc)[:400]}
    if checkout.returncode != 0:
        return {"ok": False, "reason": "checkout_error", "detail": (checkout.stderr or "")[-400:]}
    return {"ok": True}


def _run_clone_pytest(
    clone_root: Path,
    *,
    targets: list[str],
    k_expr: str | None,
    test_runner,
) -> dict:
    """Run one side of the attribution comparison inside its disposable clone."""
    existing_targets = [target for target in targets if (clone_root / target).exists()]
    if not existing_targets:
        return {"returncode": _PYTEST_NO_TESTS_COLLECTED, "output": "", "ran": []}
    junit_path = clone_root.parent / f"{clone_root.name}-pytest.xml"
    argv = [
        "uv", "run", "--extra", "dev", "python", "-m", "pytest",
        *existing_targets, "-q", f"--junitxml={junit_path}", "-o", "junit_family=legacy",
    ]
    if k_expr:
        argv += ["-k", k_expr]
    env = os.environ.copy()
    env.update({
        "VOLPRED_NO_EMAIL": "1",
        "VOLPRED_NO_REMOTE_WRITE": "1",
        "VOLPRED_NO_REMOTE_READ": "1",
        "VOLPRED_NO_CANONICAL_WRITE": "1",
        "VOLPRED_CI_PARITY": "0",
        "PYTHONPATH": os.pathsep.join([str(clone_root), str(clone_root / "src")]),
    })
    try:
        proc = test_runner(
            argv,
            capture_output=True,
            text=True,
            timeout=_TEST_GATE_TIMEOUT_S,
            cwd=str(clone_root),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": None, "reason": "timeout", "output": "", "ran": existing_targets}
    except OSError as exc:
        return {
            "returncode": None,
            "reason": "runner_error",
            "output": str(exc),
            "ran": existing_targets,
        }
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    failure_ids = _junit_failure_ids(junit_path) or _pytest_failure_ids(output)
    return {
        "returncode": proc.returncode,
        "output": output,
        "failure_ids": sorted(failure_ids),
        "ran": existing_targets,
    }


def _classify_parent_baseline(parent_rc: int | None, parent_ran: list[str]) -> str:
    """What the parent revision actually proved — the gate's evidence baseline.

    Single owner for a distinction the gate used to lose: rc=0 means the parent
    ran these tests and they passed; rc=5 means it ran *nothing* (the test file
    or the -k case did not exist yet), which is the absence of evidence, not
    evidence of green.  Both classes still attribute a red HEAD to the commit —
    the commit did land the failure — but they license different prose and
    different advice, so the call is made once, here, instead of being implied
    by an `in (0, 1, 5)` membership test and then narrated as "HEAD^ 綠".
    """
    if parent_rc == _PYTEST_NO_TESTS_COLLECTED:
        return _BASELINE_NO_COVERAGE
    if parent_rc == 0:
        return _BASELINE_GREEN if parent_ran else _BASELINE_NO_COVERAGE
    if parent_rc == 1:
        return _BASELINE_RED
    return _BASELINE_UNUSABLE


# Prose is derived from the baseline class, never hardcoded: the 2026-07-17
# report claimed "HEAD^ 綠" on a parent that had run zero tests (parent rc=5).
_BASELINE_PROSE = {
    _BASELINE_GREEN: "HEAD^ 跑同一組測試為綠，HEAD 新增紅燈。",
    _BASELINE_RED: "HEAD^ 已有紅燈，但 HEAD 新增了 HEAD^ 沒有的失敗 node。",
    _BASELINE_NO_COVERAGE: (
        "HEAD^ 沒有跑到任何測試（測試檔／case 在 HEAD^ 尚不存在）——"
        "這**不是**「HEAD^ 綠」，對照組沒有提供任何證據；紅燈仍由本 commit 帶進 main。"
    ),
}

# What the isolated comparison is entitled to claim. A no-coverage parent rules
# out daemon race and collection error (both sides ran in disposable clones), but
# it cannot rule out a defect older than the commit — only a green parent can.
_BASELINE_IMPACT = {
    _BASELINE_GREEN: "隔離對照已排除 live daemon race、collection error 與既有紅燈；此失敗可歸因本 commit。",
    _BASELINE_RED: "隔離對照已排除 live daemon race 與 collection error；新增的失敗 node 可歸因本 commit。",
    _BASELINE_NO_COVERAGE: (
        "隔離對照已排除 live daemon race 與 collection error，紅燈確實由本 commit 帶進 main；"
        "但 HEAD^ 無覆蓋 → **無法排除缺陷本身早於本 commit**（測試新、缺陷不一定新）。"
    ),
}

_BASELINE_ACTION = {
    _BASELINE_GREEN: "修掉紅燈或 revert 該 commit（gate 不自動 revert — revert 風險高於紅燈本身）。",
    _BASELINE_RED: "修掉新增的失敗 node；HEAD^ 既有的紅燈是另一件事，不要混在同一次修復裡。",
    _BASELINE_NO_COVERAGE: (
        "這是該測試第一次存在，先判斷方向再動手：是「本 commit 的程式壞了」，"
        "還是「新測試揭露了既有的潛在缺陷」？後者 revert 只會把 bug 藏回去（2026-07-17 "
        "shared_lock 檔名長度即為此類：地雷早就在，測試只是第一個踩到的）。"
    ),
}


def _post_commit_test_gate(
    repo_root: Path,
    *,
    commit_sha: str,
    hhmm: str,
    runner,
    test_runner,
    alert_fn,
) -> dict:
    """Test an exact commit in a disposable clone and compare its exact parent.

    The live checkout is deliberately never a pytest cwd: its canonical state is
    rewritten by 24/7 daemons, so collection/fingerprint noise there cannot be
    evidence about this commit.  Only a failure newly introduced relative to the
    parent emits CRITICAL; collection errors and pre-existing failures remain
    observable but un-attributed.

    The parent's own outcome is classified (_classify_parent_baseline) before any
    of it is reported: a parent that ran zero tests is not a green parent, and
    the alert must not say so.
    """
    try:
        shown = _git(
            repo_root, "show", "--name-only", "--pretty=format:", commit_sha,
            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: test-gate `git show` failed (%s) — cannot resolve changed files", exc)
        return {"passed": None, "reason": "changed_files_error"}
    if shown.returncode != 0:
        LOG.warning("phase_z: test-gate `git show` rc=%d: %s",
                    shown.returncode, (shown.stderr or "").strip()[:200])
        return {"passed": None, "reason": "changed_files_error"}

    changed = [line.strip() for line in (shown.stdout or "").splitlines() if line.strip()]
    code_files = [
        f for f in changed
        if f.endswith(".py") and f.startswith(_GATED_CODE_PREFIXES)
    ]
    if not code_files:
        LOG.info("phase_z: test-gate skipped — commit touched no gated .py (changed=%d)", len(changed))
        return {"passed": None, "reason": "skipped_non_code", "changed_code_files": []}

    try:
        parent = _git(
            repo_root, "rev-parse", "--verify", f"{commit_sha}^",
            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: test-gate parent probe failed (%s)", exc)
        return {"passed": None, "reason": "attribution_error", "ran": []}
    if parent.returncode != 0:
        return {"passed": None, "reason": "attribution_error", "ran": []}

    with tempfile.TemporaryDirectory(prefix="volpred-phase-z-test-") as tmp:
        temp_root = Path(tmp)
        head_root = temp_root / "head"
        base_root = temp_root / "parent"
        cloned = _clone_revision(repo_root, head_root, commit_sha, runner=runner)
        if not cloned["ok"]:
            return {"passed": None, **cloned, "ran": []}
        plan = _resolve_test_targets(head_root, code_files)
        targets, k_expr, unmapped = plan["targets"], plan["k_expr"], plan["unmapped"]
        if not targets:
            LOG.warning("phase_z: test-gate found NO tests for committed code %s — not treating as pass", code_files)
            return {
                "passed": None, "reason": "no_mapped_tests",
                "changed_code_files": code_files, "unmapped": unmapped,
            }
        current = _run_clone_pytest(
            head_root, targets=targets, k_expr=k_expr, test_runner=test_runner,
        )

        rc = current["returncode"]
        out = current.get("output", "")
        base = {
            "ran": current.get("ran", targets),
            "k_expr": k_expr,
            "returncode": rc,
            "tested_sha": commit_sha,
            "changed_code_files": code_files,
            "unmapped": unmapped,
            "isolated": True,
        }
        if rc is None:
            return {"passed": None, "reason": current["reason"], **base}
        if rc == 0:
            LOG.info("phase_z: isolated test-gate green — %s", out.splitlines()[-1] if out else "(no output)")
            return {"passed": True, "reason": "green", **base}
        if rc == _PYTEST_NO_TESTS_COLLECTED:
            return {"passed": None, "reason": "no_tests_collected", **base}
        if rc == 2:
            LOG.warning("phase_z: isolated test-gate collection error; not attributing it to HEAD")
            return {"passed": None, "reason": "collection_error", "failing_tail": out[-800:], **base}
        if rc != 1:
            LOG.warning("phase_z: isolated test-gate infrastructure rc=%d; not attributing it to HEAD", rc)
            return {"passed": None, "reason": "gate_error", "failing_tail": out[-800:], **base}

        cloned_parent = _clone_revision(repo_root, base_root, f"{commit_sha}^", runner=runner)
        if not cloned_parent["ok"]:
            return {"passed": None, "reason": "attribution_error", **cloned_parent, **base}
        previous = _run_clone_pytest(
            base_root, targets=targets, k_expr=k_expr, test_runner=test_runner,
        )

    parent_rc = previous["returncode"]
    parent_ran = previous.get("ran", [])
    parent_ids = set(previous.get("failure_ids", []))
    current_ids = set(current.get("failure_ids", []))
    baseline = _classify_parent_baseline(parent_rc, parent_ran)
    comparison = {
        "parent_returncode": parent_rc,
        "parent_baseline": baseline,
        "parent_ran": parent_ran,
        "failure_ids": sorted(current_ids),
        "parent_failure_ids": sorted(parent_ids),
    }
    if baseline == _BASELINE_RED and (not current_ids or not (current_ids - parent_ids)):
        LOG.warning("phase_z: isolated test-gate failure was already red at HEAD^")
        return {"passed": False, "reason": "pre_existing_failure", "failing_tail": out[-800:],
                **comparison, **base}
    if baseline == _BASELINE_UNUSABLE:
        LOG.warning("phase_z: parent comparison rc=%s is not attributable", parent_rc)
        return {"passed": None, "reason": "attribution_error", "failing_tail": out[-800:],
                **comparison, **base}

    # HEAD is red and HEAD^ was green/no-tests, or HEAD has at least one new
    # failing node id.  This is the only non-zero class attributable to HEAD.
    rc = int(rc)
    if rc == 0:
        raise AssertionError("unreachable")
    tail = out[-800:]
    LOG.warning("phase_z: test-gate NEW failure rc=%d for %s (parent baseline=%s)",
                rc, targets, baseline)
    short_sha = commit_sha[:12]

    # title 不帶 hhmm：時間戳會讓每次 fire 的 dedup key 都不同，24h 去重形同虛設
    # （2026-07-13 老闆被同一 warn 每 64 秒轟炸的根因）。時間放 body。
    title = f"PHASE-Z auto-commit 測試紅燈（{short_sha or 'HEAD'}）"
    body = "\n".join([
        "## 觸發條件",
        "safety-net 自動 commit 在隔離 clone 補跑受影響測試；" + _BASELINE_PROSE[baseline],
        f"- fire 時間: {hhmm}",
        f"- commit: {short_sha or 'HEAD'}",
        f"- 變更程式檔: {', '.join(code_files)}",
        f"- 跑的測試: {' '.join(targets)}" + (f" -k \"{k_expr}\"" if k_expr else ""),
        f"- pytest 退出碼: {rc}（HEAD） / {parent_rc}（HEAD^，baseline={baseline}）",
        "",
        "## 影響",
        _BASELINE_IMPACT[baseline],
        "",
        "## 建議行動",
        "1. 本機重跑確認：",
        f"   uv run --extra dev python -m pytest {' '.join(targets)} -q"
        + (f" -k \"{k_expr}\"" if k_expr else ""),
        "2. " + _BASELINE_ACTION[baseline],
        "3. 失敗尾段：",
        "",
        "```",
        tail or "(no output captured)",
        "```",
    ])
    alert_result = alert_fn(level="critical", title=title, body=body)
    return {"passed": False, "reason": "new_failure", "failing_tail": tail,
            "alert": alert_result, **comparison, **base}


def run_phase_z(
    *,
    repo_root: Path,
    now_hhmm: str | None = None,
    runner=subprocess.run,
    test_runner=None,
    alert_fn=None,
    internal_alert_fn=None,
    internal_resolve_fn=None,
    pre_fire_dirty: set[str] | list[str] | None = None,
    commit_receipt_override: dict | None = None,
    recovery_mode: bool = False,
) -> dict:
    """Deterministic post-fire commit. Returns an observability dict.

    Returns keys: ``committed`` (bool), ``reason`` (str), and — when it acted —
    ``untracked`` (list of leaked-ignored paths removed from the index),
    ``commit_head`` (stdout tail of `git commit`), and ``tests`` (the post-commit
    test-gate outcome, see below). Never raises: a git hiccup must not crash the
    supervisor tick, but it is always logged (no silent fallback per
    .claude/rules/no-silent-fallback.md).

    Post-commit test gate (single enforcement owner): after a successful commit,
    its exact OID is tested in a disposable clone, never the daemon-written live
    checkout. Collection errors are classified separately; an rc=1 is compared
    with the exact parent OID. Only newly failing node ids emit CRITICAL. The
    ``tests`` dict is absent on non-committing paths — nothing landed to verify.

    ``test_runner`` / ``alert_fn`` / ``internal_alert_fn`` /
    ``internal_resolve_fn`` are injectable (same style as ``runner``) so the
    gate's own tests fake notifications and pytest instead of recursively
    spawning either production path.
    """
    repo_root = Path(repo_root)
    hhmm = now_hhmm or datetime.now().strftime("%H:%M")
    supplied_alert_fn = alert_fn
    alert_fn = alert_fn or _default_alert
    if internal_alert_fn is None:
        if supplied_alert_fn is None:
            internal_alert_fn = _default_internal_alert
        else:
            # Backward-compatible test seam: existing callers inject one three-
            # argument alert collector.  Production uses the dedicated router.
            def internal_alert_fn(
                *, alert_key: str, level: str, title: str, body: str, observed_at=None
            ) -> dict:
                del alert_key, observed_at
                return supplied_alert_fn(level=level, title=title, body=body)
    if internal_resolve_fn is None:
        internal_resolve_fn = (
            _default_internal_resolve
            if supplied_alert_fn is None
            else lambda **_kwargs: {"resolved": False, "reason": "injected_alert_test_seam"}
        )
    # Read-and-consume up front: every exit path below is now incapable of leaving
    # a receipt behind to caption the next fire's commit. See the receipt block above.
    consumed_receipt = _read_and_consume_fire_receipt(repo_root, runner)
    receipt = commit_receipt_override or consumed_receipt

    dirty_now = _dirty_paths(repo_root, runner)
    if dirty_now is None:
        # e.g. not a git repository / index lock. Do NOT misreport as "clean" —
        # that would silently skip a real safety-net on a dirty tree. The snapshot
        # is NOT consumed here: a transient probe failure retries next tick, and
        # destroying the baseline turns that retry into ownership_unknown forever
        # (2026-07-13: 12+ identical 「沒有基線」 warns in 14 minutes).
        return {"committed": False, "reason": "status_error"}

    if not dirty_now:
        LOG.info("phase_z: working tree clean — agent committed everything")
        clean_observed_at = datetime.now(timezone.utc)
        internal_resolve_fn(
            alert_key="phase_z_baseline_missing",
            storage_dir=str(repo_root / "storage"),
            observed_at=clean_observed_at,
        )
        internal_resolve_fn(
            alert_key="silent_fallback_new",
            storage_dir=str(repo_root / "storage"),
            observed_at=clean_observed_at,
        )
        _consume_pre_fire_snapshot(repo_root, runner)
        _bump_foreign_streaks(repo_root, runner, [])  # nothing foreign left → streaks die here
        return {"committed": False, "reason": "clean"}

    baseline_observed_at = datetime.now(timezone.utc)
    baseline = set(pre_fire_dirty) if pre_fire_dirty is not None else _read_pre_fire_snapshot(repo_root, runner)
    if baseline is None:
        # Ownership unknown. The old code committed anyway (`git add -A`), which
        # is how it swept an interactive session's half-finished edits into an
        # agent's commit. Declining leaves the work dirty and visible; committing
        # rewrites someone else's history under someone else's name.
        LOG.warning("phase_z: no fire-start baseline — declining to commit %d dirty path(s)",
                    len(dirty_now))
        internal_alert_fn(
            alert_key="phase_z_baseline_missing",
            observed_at=baseline_observed_at,
            level="warn",
            title="PHASE-Z 沒有 fire 起始基線 — 這班不自動 commit",
            body="\n".join([
                "## 發生什麼",
                f"PHASE-Z 看到 {len(dirty_now)} 個未提交檔案，但拿不到「這班 fire 開始時工作區長怎樣」"
                "的基線，所以無法分辨哪些是這班 agent 產出的、哪些是別人正在編輯的。",
                "",
                "## 為何不直接 commit",
                "以前它會 `git add -A` 全收。那樣做過三次事故：收走截斷的 next_tasks.json、"
                "繞過測試閘門送進 main、以及把別人正在編輯的檔案 commit 進不相干的訊息裡。",
                "",
                "## 現在該做什麼",
                "檔案仍在工作區、沒有遺失。確認是誰的工作後由該作者 commit。",
                f"- fire 時間: {hhmm}",
                f"- 未提交檔案數: {len(dirty_now)}",
                f"- 基線檔: <git-dir>/{_SNAPSHOT_BASENAME}（缺失或過期）",
            ]),
        )
        return {"committed": False, "reason": "ownership_unknown", "dirty": len(dirty_now)}

    internal_resolve_fn(
        alert_key="phase_z_baseline_missing",
        storage_dir=str(repo_root / "storage"),
        observed_at=datetime.now(timezone.utc),
    )
    owned = sorted(dirty_now - baseline)
    dirty_before = sorted(dirty_now & baseline)
    # The snapshot is consumed only on a SETTLED outcome (committed / clean /
    # nothing_owned / nothing_to_commit — the scheduler's terminal set). A failed
    # commit attempt (pre-commit gate block, add/reset error) keeps the baseline,
    # so the scheduler's bounded retry still knows what this fire owns instead of
    # degrading to ownership_unknown. "One snapshot, one fire" still holds: the
    # next fire's pre-fire guard overwrites it unconditionally.

    # Dirty-at-fire-start splits two ways, not one. A daemon-written churn path has
    # an owner (this module); only the rest is "another session is still typing it".
    churn, churn_deferred, churn_corrupt = _classify_machine_churn(
        repo_root, [p for p in dirty_before if _is_machine_state(p)])
    foreign = [p for p in dirty_before if not _is_machine_state(p)]

    if churn_corrupt:
        alert_fn(
            level="critical",
            title=f"PHASE-Z 控制檔內容壞掉，拒絕提交 — {', '.join(churn_corrupt)}",
            body="\n".join([
                f"（fire 時間: {hhmm}）",
                "",
                "## 發生什麼",
                "任務池等控制檔的內容無法解析（可能是某次寫入被中斷截斷）。PHASE-Z 沒有把它 commit "
                "進歷史 —— 曾經有一次截斷的任務池被當成正常歷史提交，這道閘門就是為了擋那件事。",
                "",
                "## 現在該做什麼",
                "檔案還在工作區、沒被覆蓋。從上一個 commit 取回可用版本："
                "`git checkout HEAD -- <檔案>`，確認寫入端為何中斷。",
                "",
                "## 檔案",
                *[f"- {p}" for p in churn_corrupt],
            ]),
        )

    # A recovery pass runs immediately before the real pre-fire snapshot. It
    # must not count the same unrelated dirty paths as another hourly shift.
    streaks = {} if recovery_mode else _bump_foreign_streaks(repo_root, runner, foreign)
    stuck = sorted((p for p, n in streaks.items() if n >= _FOREIGN_STREAK_CRITICAL),
                   key=lambda p: (-streaks[p], p))
    worst_streak = max(streaks.values(), default=0)

    if stuck:
        LOG.warning("phase_z: %d foreign path(s) stuck for >=%d fires: %s",
                    len(stuck), _FOREIGN_STREAK_CRITICAL, stuck[:10])
        alert_fn(
            level="critical",
            # streak 每班 +1、count 會浮動 — 進 title 就等於每班一個新 dedup key，
            # 同一批卡住檔案會變成連環 critical。細節全放 body。
            title="PHASE-Z 有檔案連續多班沒人收 — 遺留變成堆積",
            body="\n".join([
                f"（fire 時間: {hhmm}；{len(stuck)} 個檔案，最長已連續 {worst_streak} 班）",
                "",
                "## 發生什麼",
                f"這些未提交的檔案不是任何一班 fire 產出的，而且已經連續 {worst_streak} 班都還在工作區。"
                "單次遺留代表某個 session 正在寫；連續多班還在，代表沒有人會回來收 —— "
                "它們會一直卡在工作區，讓每一班的「誰擁有這個檔案」判斷越來越不可靠。",
                "",
                "## 現在該做什麼",
                "**沒有任何檔案會被丟棄。** 成品（草稿 / 實驗產出）由 "
                "`uv run python scripts/reap_orphan_deliverables.py --apply` 走正規入池路徑自動收編 —— "
                "每小時 check_alerts 會自己跑一次，通常不必手動介入。",
                "剩下這些是它認不出來源的檔案：確認內容正確就由作者 commit。"
                "PHASE-Z 本身不自動收養（盲目收養正是先前三次事故的成因），但**不收養不等於丟棄** —— "
                "檔案留在工作區，沒有人會刪它。",
                "",
                "## 卡住的檔案（連續班數）",
                *[f"- {p} — {streaks[p]} 班" for p in stuck[:30]],
                *(["- …"] if len(stuck) > 30 else []),
            ]),
        )

    if foreign:
        LOG.info("phase_z: leaving %d path(s) dirty — already dirty at fire start, not ours: %s",
                 len(foreign), foreign[:10])
    if churn:
        LOG.info("phase_z: adopting %d machine-churn path(s) — daemon-written, no session owner: %s",
                 len(churn), churn)
    if churn_deferred:
        LOG.info("phase_z: %d machine-churn path(s) busy/unreadable — next fire takes them: %s",
                 len(churn_deferred), churn_deferred)

    if not owned and not churn:
        _consume_pre_fire_snapshot(repo_root, runner)  # settled: nothing of ours to commit
        LOG.info("phase_z: nothing this fire produced — %d foreign path(s) left alone", len(foreign))
        if not foreign:
            return {"committed": False, "reason": "nothing_owned", "foreign": []}
        if stuck:
            # the critical alert above already said everything this one would, louder.
            return {"committed": False, "reason": "nothing_owned",
                    "foreign": foreign, "stuck": stuck}
        alert_fn(
            level="warn",
            title="PHASE-Z 有檔案未提交，但不是這班產出的",
            body="\n".join([
                f"（fire 時間: {hhmm}；{len(foreign)} 個檔案）",
                "",
                "## 發生什麼",
                "這班 fire 沒有留下任何自己的未提交變更，但工作區裡有別人的未提交檔案"
                "（fire 開始前就髒了）。PHASE-Z 不碰它們。",
                "",
                "## 現在該做什麼",
                "多半不用做什麼：成品（草稿 / 實驗產出）由 `reap_orphan_deliverables` 每小時自動收編入池；"
                "其餘檔案留在工作區等作者 commit。PHASE-Z 不自動收養（那是三次事故的成因），"
                "但**不收養不等於丟棄** —— 沒有任何流程會刪掉它們。",
                "",
                "## 檔案",
                *[f"- {p}" for p in foreign[:30]],
                *(["- …"] if len(foreign) > 30 else []),
            ]),
        )
        return {"committed": False, "reason": "nothing_owned", "foreign": foreign}

    LOG.info("phase_z: auto-committing %d path(s) from this fire + %d machine-churn path(s)",
             len(owned), len(churn))
    # Build the commit in an alternate index.  The real index may contain another
    # session's carefully staged work; mutating it and attempting to reset after a
    # hook failure is not a transaction.  A temporary GIT_INDEX_FILE gives PHASE-Z
    # an isolated candidate: every failure discards the file, so HEAD, the real
    # index, and all working bytes remain byte-for-byte untouched.
    untracked: list[str] = []
    candidate_paths: list[str] = []
    refresh: dict | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="volpred-phase-z-index-") as tx:
            tx_root = Path(tx)
            candidate_env = os.environ.copy()
            candidate_env["GIT_INDEX_FILE"] = str(tx_root / "index")

            base = _git(
                repo_root, "rev-parse", "--verify", "HEAD",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            if base.returncode != 0:
                return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}
            base_sha = (base.stdout or "").strip()

            read_tree = _git(
                repo_root, "read-tree", base_sha, timeout_s=_SHORT_TIMEOUT_S,
                runner=runner, env=candidate_env,
            )
            if read_tree.returncode != 0:
                LOG.warning("phase_z: cannot initialise candidate index: %s", (read_tree.stderr or "")[-300:])
                return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}

            leaked = _git(
                repo_root, "ls-files", "-ci", "--exclude-standard", "--",
                *_LEAKED_STATE_PATHSPECS, timeout_s=_SHORT_TIMEOUT_S,
                runner=runner, env=candidate_env,
            )
            if leaked.returncode != 0:
                LOG.warning("phase_z: candidate leaked-state probe rc=%d: %s",
                            leaked.returncode, (leaked.stderr or "")[-300:])
                return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}
            for path in filter(None, ((leaked.stdout or "").splitlines())):
                rm = _git(
                    repo_root, "rm", "--cached", "-q", "--", path,
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=candidate_env,
                )
                if rm.returncode != 0:
                    LOG.warning("phase_z: candidate git rm --cached %s rc=%d", path, rm.returncode)
                    return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}
                untracked.append(path)

            to_stage = [p for p in (owned + churn) if p not in set(untracked)]
            pathspec_file = tx_root / "paths.nul"
            try:
                pathspec_file.write_bytes(b"\0".join(os.fsencode(path) for path in to_stage))
            except OSError as exc:
                LOG.warning("phase_z: cannot write candidate pathspec (%s)", exc)
                return {"committed": False, "reason": "pathspec_error", "rolled_back": True}

            if to_stage:
                add = _git(
                    repo_root, "add", "-A", f"--pathspec-from-file={pathspec_file}",
                    "--pathspec-file-nul", timeout_s=_SHORT_TIMEOUT_S,
                    runner=runner, env=candidate_env,
                )
                if add.returncode != 0:
                    LOG.warning("phase_z: candidate git add rc=%d: %s",
                                add.returncode, (add.stderr or "")[-300:])
                    return {"committed": False, "reason": "add_error", "untracked": untracked,
                            "rolled_back": True}

            staged = _git(
                repo_root, "diff", "--cached", "--name-only", "-z", base_sha,
                timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=candidate_env,
            )
            if staged.returncode != 0:
                return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}
            candidate_paths = sorted(filter(None, (staged.stdout or "").split("\0")))
            allowed_paths = set(to_stage) | set(untracked)
            unexpected = sorted(set(candidate_paths) - allowed_paths)
            if unexpected:
                LOG.error("phase_z: candidate index contains non-owned paths: %s", unexpected)
                return {"committed": False, "reason": "candidate_scope_error", "rolled_back": True,
                        "unexpected": unexpected}
            if not candidate_paths:
                _consume_pre_fire_snapshot(repo_root, runner)
                return {"committed": False, "reason": "nothing_to_commit", "untracked": untracked}

            tree_before = _git(
                repo_root, "write-tree", timeout_s=_SHORT_TIMEOUT_S,
                runner=runner, env=candidate_env,
            )
            if tree_before.returncode != 0:
                return {"committed": False, "reason": "candidate_index_error", "rolled_back": True}

            gate_changes = sorted(set(candidate_paths) & _TRUSTED_GATE_PATHS)
            if gate_changes:
                LOG.error("phase_z: candidate attempted to modify its own trusted gate: %s", gate_changes)
                return {
                    "committed": False,
                    "reason": "candidate_gate_self_modification",
                    "rolled_back": True,
                    "gate_changes": gate_changes,
                }

            # Run an immutable hook (pinned base_sha, or an installed fixture
            # hook when the base has no canonical gate) against a materialized
            # candidate worktree.  Neither hook code nor cwd comes from the live
            # checkout, so hook side effects are confined to this temp tree.
            hook_probe = _git(
                repo_root, "rev-parse", "--git-path", "hooks/pre-commit",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            if hook_probe.returncode != 0:
                return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
            installed_hook = Path((hook_probe.stdout or "").strip())
            if not installed_hook.is_absolute():
                installed_hook = repo_root / installed_hook
            trusted_hook = tx_root / "trusted-pre-commit"
            trusted_auditor = tx_root / "trusted-audit-test-imports.py"
            base_hook = _git(
                repo_root, "show", f"{base_sha}:scripts/git_hooks/pre-commit",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            if base_hook.returncode == 0:
                base_auditor = _git(
                    repo_root, "show", f"{base_sha}:scripts/audit_test_imports.py",
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner,
                )
                if base_auditor.returncode != 0:
                    return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
                trusted_hook.write_text(base_hook.stdout or "", encoding="utf-8")
                trusted_auditor.write_text(base_auditor.stdout or "", encoding="utf-8")
            elif installed_hook.is_file() and os.access(installed_hook, os.X_OK):
                # Hermetic repositories may supply a deliberately tiny fixture
                # hook. Copy it now so a concurrent rewrite cannot change what
                # this transaction executes.
                shutil.copyfile(installed_hook, trusted_hook)
            else:
                LOG.error("phase_z: no immutable pre-commit hook available")
                return {"committed": False, "reason": "candidate_gate_missing", "rolled_back": True}
            trusted_hook.chmod(0o700)

            candidate_root = tx_root / "candidate"
            candidate_root.mkdir()
            checkout = _git(
                repo_root, "checkout-index", "--all", f"--prefix={candidate_root}{os.sep}",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=candidate_env,
            )
            if checkout.returncode != 0:
                return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
            git_dir_probe = _git(
                repo_root, "rev-parse", "--absolute-git-dir",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            if git_dir_probe.returncode != 0:
                return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
            hook_env = candidate_env.copy()
            hook_env.update({
                "GIT_DIR": (git_dir_probe.stdout or "").strip(),
                "GIT_WORK_TREE": str(candidate_root),
                "VOLPRED_NO_EMAIL": "1",
                "VOLPRED_NO_REMOTE_WRITE": "1",
                "VOLPRED_NO_REMOTE_READ": "1",
                "VOLPRED_NO_CANONICAL_WRITE": "1",
            })
            if trusted_auditor.is_file():
                hook_env["VOLPRED_TRUSTED_TEST_IMPORT_AUDITOR"] = str(trusted_auditor)
            hook_observed_at = datetime.now(timezone.utc)
            hook = runner(
                ["bash", str(trusted_hook)], cwd=str(candidate_root), env=hook_env,
                capture_output=True, text=True, timeout=_COMMIT_TIMEOUT_S, check=False,
            )
            hook_out = ((hook.stdout or "") + (hook.stderr or "")).strip()
            if hook.returncode != 0:
                LOG.warning("phase_z: candidate pre-commit blocked; alternate index discarded: %s",
                            hook_out[-400:])
                silent_fallback_blocked = _is_silent_fallback_gate_output(hook_out)
                alert_payload = {
                    "level": "warn",
                    "title": "PHASE-Z candidate 被 pre-commit 擋下（未進 main）",
                    "body": (
                        "候選 commit 已完整回滾；hook side effects 隔離於 disposable candidate。\n\n"
                        + (hook_out[-1200:] or "(hook returned non-zero without output)")
                    ),
                }
                if silent_fallback_blocked:
                    internal_alert_fn(
                        alert_key="silent_fallback_new",
                        observed_at=hook_observed_at,
                        fingerprint=_silent_fallback_fingerprints(hook_out),
                        **alert_payload,
                    )
                else:
                    alert_fn(**alert_payload)
                _ensure_failed_closeout(
                    repo_root,
                    owned=owned,
                    reason="commit_nonzero",
                    commit_tail=hook_out,
                    receipt=receipt,
                    runner=runner,
                )
                return {"committed": False, "reason": "commit_nonzero", "untracked": untracked,
                        "owned": owned,
                        "commit_tail": hook_out[-600:], "rolled_back": True,
                        "internal_alert_observed_at": hook_observed_at.isoformat(),
                        "internal_alert_key": (
                            "silent_fallback_new" if silent_fallback_blocked else None
                        )}

            # Gate 2 audits only candidate-owned Python paths; a foreign dirty
            # Python file can be the rejected candidate from an earlier cohort
            # and is absent from this alternate index.  Resolve only when the
            # successful gate covered all dirty Python state (or none remains).
            no_dirty_python = not any(path.endswith(".py") for path in dirty_now)
            clean_gate_receipt = _is_silent_fallback_clean_gate_output(hook_out)
            if no_dirty_python or (
                clean_gate_receipt
                and not any(path.endswith(".py") for path in dirty_before)
            ):
                internal_resolve_fn(
                    alert_key="silent_fallback_new",
                    storage_dir=str(repo_root / "storage"),
                    observed_at=datetime.now(timezone.utc),
                )
            tree_after = _git(
                repo_root, "write-tree", timeout_s=_SHORT_TIMEOUT_S,
                runner=runner, env=candidate_env,
            )
            if tree_after.returncode != 0 or tree_after.stdout.strip() != tree_before.stdout.strip():
                LOG.error("phase_z: pre-commit mutated candidate index; discarding transaction")
                return {"committed": False, "reason": "candidate_gate_mutation", "untracked": untracked,
                        "rolled_back": True}

            if owned and receipt:
                subject = f"dispatch({hhmm}): {receipt['subject']}"
            elif owned:
                subject = f"dispatch({hhmm}): {_generated_subject(owned)}"
            else:
                subject = f"ops(dispatch-supervisor {hhmm}): PHASE-Z state churn (no agent output this fire)"
            body_lines = []
            if receipt:
                if receipt["task_id"]:
                    body_lines.append(f"task: {receipt['task_id']}")
                if receipt["body"]:
                    body_lines.append(receipt["body"])
                if body_lines:
                    body_lines.append("")
            body_lines.append(
                f"Staged what this fire produced: {len(owned)} path(s), plus "
                f"{len(churn)} daemon-written machine-churn path(s) this module owns.\n"
                f"Left alone (dirty before the fire, another writer's): {len(foreign)} path(s)."
            )
            commit_object = _git(
                repo_root, "commit-tree", tree_after.stdout.strip(), "-p", base_sha,
                "-m", subject, "-m", "\n".join(body_lines),
                timeout_s=_COMMIT_TIMEOUT_S, runner=runner, env=candidate_env,
            )
            if commit_object.returncode != 0:
                commit = commit_object
                committed_sha = ""
            else:
                committed_sha = (commit_object.stdout or "").strip()
                try:
                    # Candidate construction is isolated in GIT_INDEX_FILE and
                    # may run concurrently.  Serialise the one shared mutation:
                    # HEAD adoption plus the matching shared-index refresh.
                    # Keeping both under one lease prevents another writer from
                    # observing the new HEAD with a stale index in between.
                    with git_writer_lock(
                        repo_root,
                        actor=f"dispatch-phase-z:{hhmm}",
                        timeout_s=_COMMIT_TIMEOUT_S,
                    ):
                        require_canonical_main_checkout(repo_root)
                        adopted = _git(
                            repo_root, "update-ref", "refs/heads/main", committed_sha, base_sha,
                            timeout_s=_SHORT_TIMEOUT_S, runner=runner,
                        )
                        if adopted.returncode == 0:
                            refresh = _refresh_shared_index_cas(
                                repo_root,
                                base_sha=base_sha,
                                committed_sha=committed_sha,
                                candidate_paths=candidate_paths,
                                runner=runner,
                            )
                except GitWriterLockError as exc:
                    adopted = subprocess.CompletedProcess(
                        args=["git", "update-ref", "refs/heads/main", committed_sha, base_sha],
                        returncode=75,
                        stdout="",
                        stderr=f"git writer transaction lock unavailable: {exc}",
                    )
                if adopted.returncode == 0:
                    commit = subprocess.CompletedProcess(
                        args=adopted.args,
                        returncode=0,
                        stdout=f"[{committed_sha[:12]}] {subject}",
                        stderr="",
                    )
                else:
                    # Another writer advanced HEAD after the candidate was built.
                    # update-ref's old-value CAS rejects adoption; the dangling
                    # commit object is harmless and the candidate index is deleted.
                    commit = subprocess.CompletedProcess(
                        args=adopted.args,
                        returncode=adopted.returncode,
                        stdout="",
                        stderr=("HEAD moved while PHASE-Z candidate was running; CAS adoption rejected.\n"
                                + (adopted.stderr or "")),
                    )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: candidate transaction failed (%s); alternate index discarded", exc)
        return {"committed": False, "reason": "commit_error", "untracked": untracked,
                "rolled_back": True}

    out = ((commit.stdout or "") + (commit.stderr or "")).strip()
    if commit.returncode == 0:
        if refresh is None:
            refresh = {"ok": False, "reason": "index_refresh_not_run"}
        if not refresh.get("ok"):
            detail = f"{refresh.get('reason')}: {refresh.get('detail', '')}".strip()
            alert_fn(
                level="critical",
                title="PHASE-Z commit 已落地但共享 index 未完成 refresh",
                body=("commit 本身完整，working bytes 未遺失；共享 index CAS 未完成。"
                      "請先確認沒有其他 git writer，再人工 refresh。\n\n" + detail),
            )
        elif refresh.get("preserved"):
            LOG.info(
                "phase_z: preserved concurrent staged entries for %s",
                refresh["preserved"],
            )
        _consume_pre_fire_snapshot(repo_root, runner)  # settled: the fire's work landed
        LOG.info("phase_z: committed — %s", out.splitlines()[-1] if out else "(no output)")
        tests = _post_commit_test_gate(
            repo_root, commit_sha=committed_sha, hhmm=hhmm, runner=runner,
            test_runner=test_runner or subprocess.run,
            alert_fn=alert_fn or _default_alert,
        )
        if owned and not receipt:
            # Not a rescue alert — the work IS committed. This flags a commit that
            # landed in main history with a generated message instead of an account
            # of why, i.e. an audit-trail gap.
            #
            # This used to claim "rare by design: the only way here is an agent that
            # produced output and skipped one CLI call". The skip WAS the only way in,
            # but it was never rare: 186 of 266 dispatch commits over 14 days (~70% of
            # fires with output) landed here, so the warn became hourly noise and the
            # boss read it as the system misfiring (msg 886, 2026-07-16). A step that
            # every agent must remember, with nothing checking, is not a rare failure —
            # it is the default path. The Stop-hook gate
            # (`scripts/hooks/enforce_fire_receipt.py`, via fire_output_needs_receipt)
            # now asks for the receipt while the agent is still alive; reaching this
            # warn means the gate was bypassed or failed open, which IS rare.
            alert_fn(
                level="warn",
                title="PHASE-Z 產出已 commit，但 agent 沒交代原因",
                body="\n".join([
                    f"（fire 時間: {hhmm}；{len(owned)} 個檔案）",
                    "",
                    "## 發生什麼",
                    f"這班 fire 產出了 {len(owned)} 個檔案，PHASE-Z 已照常 commit（**工作沒有遺失**）。",
                    "但 agent 沒有在收尾時留下 commit 說明（fire receipt），所以 subject 是從 diff",
                    "自動生成的 —— 看得出**動到哪些檔**，看不出**為什麼**。",
                    "",
                    "## 現在該做什麼",
                    "通常不用處理。若這筆 commit 之後要追溯，直接看 diff。",
                    "但這則 warn 現在應該很少見：Stop hook 會在 agent 結束前擋一次要 receipt。",
                    "若又開始每小時出現 → 表示 gate 破了，查 `scripts/hooks/enforce_fire_receipt.py`",
                    "是否 fail-open（它設計上任何錯誤都放行）、或 user-level Stop hook 是否被移除。",
                    "",
                    "## 正確做法（給 agent）",
                    "`uv run python scripts/fire_receipt.py --task-id <id> --subject '<一句話 what | why>'`",
                ]),
            )
        if foreign and not recovery_mode:
            alert_fn(
                level="warn",
                title="PHASE-Z 有檔案不是這班產出的，已略過",
                body="\n".join([
                    f"（fire 時間: {hhmm}；{len(foreign)} 個檔案）",
                    "",
                    "## 發生什麼",
                    f"這班 fire 的 {len(owned)} 個檔案已自動 commit。另外 {len(foreign)} 個檔案"
                    "在 fire 開始前就已經是未提交狀態 —— 那是別的 session 正在做的事，PHASE-Z 沒有動它們。",
                    "",
                    "## 現在該做什麼",
                    "通常不需要處理（該 session 會自己 commit）。若它已經結束，請人工確認後再 commit。",
                    "",
                    "## 略過的檔案",
                    *[f"- {p}" for p in foreign[:30]],
                    *(["- …"] if len(foreign) > 30 else []),
                ]),
            )
        return {"committed": True, "reason": "committed", "untracked": untracked,
                "owned": owned, "foreign": foreign, "churn": churn,
                "commit_head": out[-500:], "tests": tests, "index_refresh": refresh}
    # Non-zero commit: distinguish the benign "nothing to commit" (everything
    # dirty was a leaked-ignored file already rm --cached'd, or a race cleaned
    # it) from a genuine commit failure.
    if "nothing to commit" in out.lower():
        _consume_pre_fire_snapshot(repo_root, runner)  # settled: benign no-op
        LOG.info("phase_z: nothing to commit after staging (benign)")
        return {"committed": False, "reason": "nothing_to_commit", "untracked": untracked}
    # Snapshot kept: the scheduler retries with ownership intact, then gives up
    # loudly. `commit_tail` feeds its give-up alert — a pre-commit gate block is
    # the one actionable fact (2026-07-13: the boss got 12 "no baseline" warns
    # and zero mention of the silent-fallback gate that actually blocked it).
    LOG.warning("phase_z: git commit rc=%d: %s", commit.returncode, out[:300])
    _ensure_failed_closeout(
        repo_root,
        owned=owned,
        reason="commit_nonzero",
        commit_tail=out,
        receipt=receipt,
        runner=runner,
    )
    return {"committed": False, "reason": "commit_nonzero", "untracked": untracked,
            "owned": owned, "commit_tail": out[-600:], "rolled_back": True}
