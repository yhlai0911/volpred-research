"""Finite canonical-root hygiene while producer landing moves out of PHASE-Z.

Two entry points, both called from `scheduler._tick_once`:

  - `run_pre_fire_guard()`  — BEFORE the worker: conflict-marker / orphaned
    AUTO_MERGE backstop (port of the legacy shell's git_conflict_guard call).
  - `run_phase_z()`         — AFTER a drained worker cohort: settle explicitly
    classified machine state and bounded legacy recovery only.

Issue #43 moved mutating producer output to isolated workspaces, declared output
paths, gates, and durable settlement receipts. The workspace finalizer owns that
landing transaction; this module must never infer producer authorship from timing,
a fire-start baseline, or an explanatory receipt. Issue #41 removes remaining
machine-state writes from Git, and Issue #44 physically retires this recognizer.

---

The historical implementation below remains only for the finite retirement
surface: machine-state commits and already-materialized recovery receipts.

Port of the `scripts/cron_hourly_dispatch.sh` PHASE-Z block (2026-05-29) into
the supervisor runtime (Deliverable 7 cutover, 2026-07-04). The dispatch prompt
forbids agent-side Git. A fire receipt explains why a cohort acted, but cannot
establish path ownership or cause producer bytes to land.

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

import ast
import fcntl
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.ops.foreign_incident import (
    QUARANTINE_REF_PREFIX,
    reconcile_incidents,
    settle_family_page,
    upsert_incident,
)
from volpred.ops.git_writer_lock import (
    GitWriterLockError,
    git_writer_lock,
    git_writer_subprocess_kwargs,
    require_canonical_main_checkout,
)
from volpred.ops.issue_tracker_sync import (
    pending_issue_task_ids_for_owners,
    settle_completed_task_issues,
)
from volpred.ops.machine_churn import (
    MachineChurnClassification,
    MachineChurnIdentity,
    classify_machine_churn,
    machine_churn_identity_matches,
)
from volpred.ops.next_tasks import backfill_ci_repair_commit

from .child_env import external_child_environment
from .procutil import (
    IDENTITY_DEAD,
    IDENTITY_MISMATCH,
    check_identity,
    get_process_start_wall,
)

LOG = logging.getLogger(__name__)

# git op timeouts (seconds) — mirror legacy perl-alarm ceilings (status/add=30,
# commit=60). status/ls-files/rm/add share the short ceiling; commit gets long.
_SHORT_TIMEOUT_S = 30
_COMMIT_TIMEOUT_S = 60
# Materialising a full candidate tree is proportional to the repository size,
# not to the number of paths this fire owns.  The old 30-second short ceiling
# was safe for small fixtures but repeatedly timed out on the live checkout
# after Graphify and the generated research corpus grew, leaving
# ``phase_z_pending`` occupied forever until its retry cap.  Keep all other git
# probes fail-fast; give this one bounded, explicit headroom.
_CANDIDATE_CHECKOUT_TIMEOUT_S = 180

# post-commit test gate — see run_phase_z's post-commit block. Bound the pytest
# subset so a hung / pathological test suite can never wedge the supervisor tick
# (the gate already runs inside scheduler's asyncio.to_thread, but the thread
# itself must return). 600s = the same ceiling the task brief specifies.
_TEST_GATE_TIMEOUT_S = 600
# Only these three trees carry the code whose regressions a safety-net commit can
# smuggle into main (docs/error_log.md dab3baa12: a gmail_inbox_poll rewrite went
# in via PHASE-Z with a red test nobody saw for 5 days). experiments/ and paper/
# are research artifacts, not the runtime the gate protects.
# Candidate commits are normally control data, but the explicit machine
# namespace can contain generated Python helpers. If one ever does, it needs
# the same post-commit attribution gate as source code; excluding storage/ops
# merely because the legacy timing recognizer used to own code was a coverage
# hole after Issue #44 retired that recognizer.
_GATED_CODE_PREFIXES = ("src/volpred/", "scripts/", "tests/", "storage/ops/")
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
    "storage/.failed_mirror_syncs.json",    # same, Mirror side (WS-C4)
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


def is_machine_state_path(rel: str) -> bool:
    """Return whether the temporary PHASE-Z namespace owns ``rel``.

    Public only so retirement/audit tooling can classify the exact live policy
    without copying its prefixes. Issue #41/#44 remove this seam with PHASE-Z.
    """
    return rel in _MACHINE_STATE_FILES or rel.startswith(_MACHINE_STATE_PREFIXES)


# Compatibility for the finite PHASE-Z implementation/tests during retirement.
_is_machine_state = is_machine_state_path


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
_FAILED_CLOSEOUT_RECOVERY_CAPABILITY = object()
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
    """The live ownership receipt, or None.

    A receipt that will not parse is QUARANTINED, not left in place. Leaving it
    made the module permanently unable to record ownership: every later failure's
    `_ensure_failed_closeout` saw a file it could not read and returned False, so
    no fire could ever persist a receipt again and nothing said so out loud. That
    is the same "no exit" shape as the untracked conflict below — a state only a
    human deleting a hidden `.git/` file could leave. Renaming it aside restores
    the module to a working state on the next call and keeps the bytes for
    forensics.
    """
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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.replace(quarantine)
            LOG.error("phase_z: failed-closeout receipt unreadable (%s) — quarantined to %s",
                      exc, quarantine.name)
        except OSError as move_exc:  # pragma: no cover — rename of our own file
            LOG.error("phase_z: failed-closeout receipt unreadable (%s) and cannot be "
                      "quarantined (%s) — ownership recording is wedged until removed",
                      exc, move_exc)
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
    machine = [rel for rel in owned if _is_machine_state(rel)]
    if machine:
        # Hot daemon-written state is never pinned (assign_33e4c59f): a dozen
        # writers touch these files every hour, so the fingerprint is guaranteed
        # to drift and the claim can only ever end in a "released" warn. Deferral
        # has no meaning for bytes that are stale a minute later — the churn lane
        # re-adopts these paths under the next fire's own baseline.
        LOG.info("phase_z: not pinning %d machine-state path(s) into failed closeout: %s",
                 len(machine), machine[:10])
        owned = [rel for rel in owned if not _is_machine_state(rel)]
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
    stale: set[str] = set()
    for rel in owned:
        fingerprint = _path_fingerprint(repo_root / rel)
        if fingerprint is None:
            # One unreadable path must not cost the other nine their receipt.
            # Aborting the whole write was the old behaviour and it silently
            # dropped ownership of every path in the batch.
            LOG.error("phase_z: cannot fingerprint owned path %s — excluded from receipt", rel)
            continue
        if rel in existing_entries:
            # The first rejected candidate is the authority. Re-pinning an
            # overlapping path would bless bytes edited after that failure — so
            # a drifted pin is RELEASED (the claim is dropped, the bytes are left
            # alone) rather than re-pinned or left to wedge the whole receipt.
            if fingerprint != existing_entries[rel]:
                LOG.warning("phase_z: failed-closeout path changed before a later failure — "
                            "releasing stale claim: %s", rel)
                stale.add(rel)
            continue
        entries.append({"path": rel, "fingerprint": fingerprint})
    if existing_payload is not None:
        payload = existing_payload
        if stale:
            payload["paths"] = [e for e in payload["paths"] if e["path"] not in stale]
            payload.setdefault("released", []).extend(
                {"path": rel, "reason": "repin_refused",
                 "released_at": datetime.now(timezone.utc).isoformat()}
                for rel in sorted(stale)
            )
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
    if not payload["paths"]:
        # Nothing left to claim. An empty receipt is unreadable by
        # _read_failed_closeout and would quarantine itself next call; delete it
        # so the module returns to the clean "no receipt" state.
        _clear_failed_closeout(repo_root, runner)
        return False
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

    ADVISORY ONLY — never a gate. `git log` cannot, by definition, name a path
    that no commit contains, so this question is FALSE for every untracked file
    forever, not merely "not yet". Using it as the sole discriminator between
    "resolved" and "conflict" is what produced a CRITICAL with no exit
    (error_log 2026-07-18): an untracked file that a later session edited was
    dirty (so not landed), drifted (so not unresolved) and invisible to git log
    (so never carried) — permanently. It now only decides how loudly a drifted
    pin is released, not whether the claim can be dropped.

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


def _release_closeout_claims(
    repo_root: Path, released: list[str], runner, *, reason: str
) -> bool:
    """Drop stale ownership claims from the receipt. THIS IS THE ALERT'S EXIT.

    A released path is one whose pinned bytes no longer exist in the working
    tree. The rejected fire's output is gone — overwritten by whoever edited the
    file afterwards — so there is nothing left for this receipt to recover and
    the claim is moot. Releasing commits nothing, deletes nothing and touches no
    working bytes; it only stops this module from asserting ownership over
    content it did not produce.

    Returns True when the receipt was successfully rewritten (or removed because
    it became empty). The caller alerts ONCE on the release; the next pass finds
    no claim and is silent. That one-shot shape is the hard requirement: before
    this, a drifted claim re-raised the same CRITICAL every fire and the only way
    to stop it was a human deleting `.git/volpred_phase_z_failed_closeout.json`.
    """
    if not released:
        return True
    dest = _failed_closeout_path(repo_root, runner)
    payload = _read_failed_closeout(repo_root, runner)
    if dest is None or payload is None:
        return False
    dropped = set(released)
    payload["paths"] = [e for e in payload["paths"] if e["path"] not in dropped]
    payload.setdefault("released", []).extend(
        {"path": rel, "reason": reason,
         "released_at": datetime.now(timezone.utc).isoformat()}
        for rel in sorted(dropped)
    )
    if not payload["paths"]:
        _clear_failed_closeout(repo_root, runner)
        LOG.warning("phase_z: released %d stale closeout claim(s); receipt is now empty and removed",
                    len(dropped))
        return True
    try:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(dest)
        LOG.warning("phase_z: released %d stale closeout claim(s); %d still pinned",
                    len(dropped), len(payload["paths"]))
        return True
    except OSError as exc:
        LOG.error("phase_z: cannot persist closeout release (%s) — claim will be re-evaluated "
                  "next pass", exc)
        return False


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

    Every pinned path lands in exactly one of three buckets, and all three
    terminate:

      landed      — no longer dirty, or drifted-and-carried-forward by a later
                    commit. Silent; the claim is satisfied.
      unresolved  — still dirty and still byte-identical to the pin. THIS is the
                    only bucket recovery acts on: the rejected fire's output is
                    verifiably still there, so it can be re-staged and committed
                    under the original attribution.
      released    — still dirty but the pinned bytes are gone (someone edited the
                    file after the failure). Nothing recoverable remains, so the
                    claim is dropped from the receipt, alerted ONCE at warn, and
                    never re-raised.

    HOW THIS ALERT STOPS (the property 2026-07-17's fix did not give it): the
    release rewrites the receipt in the same pass that alerts, so the condition
    is gone before the next fire evaluates it. No human action, no file deletion,
    no gate repair is required for the paging to end — the loudest this can ever
    be is one warn per drifted path per lifetime of the claim. Nothing is
    discarded by a release: the working-tree bytes are untouched and a later
    fire's own pre-fire baseline will own and commit them normally.

    The predecessor design had no such exit for untracked paths. "Did a later
    commit carry this forward?" is answered by `git log`, which never lists an
    untracked file, so an untracked + edited path was structurally incapable of
    leaving the conflict bucket — a CRITICAL every hour whose only off switch was
    deleting a file inside `.git/` by hand (error_log 2026-07-18).
    """
    repo_root = Path(repo_root)
    payload = _read_failed_closeout(repo_root, runner)
    if payload is None:
        return {"committed": False, "reason": "no_failed_closeout"}
    stale_machine = sorted(
        e["path"] for e in payload["paths"] if _is_machine_state(e["path"]))
    if stale_machine:
        # Receipts written before assign_33e4c59f may still pin hot machine
        # state. Release those claims silently: under the current invariant they
        # would never have been pinned, and warning about their inevitable drift
        # was the recurring "放棄認領" orphan alert (2026-07-20). Working bytes
        # are untouched; the churn lane owns them.
        LOG.info("phase_z: releasing %d pre-invariant machine-state claim(s) silently: %s",
                 len(stale_machine), stale_machine[:10])
        _release_closeout_claims(
            repo_root, stale_machine, runner, reason="machine_state_unpinned")
        payload = _read_failed_closeout(repo_root, runner)
        if payload is None:
            return {"committed": False, "reason": "no_failed_closeout"}
    dirty = _dirty_paths(repo_root, runner)
    if dirty is None:
        return {"committed": False, "reason": "status_error"}

    carried = _paths_carried_forward(repo_root, payload.get("created_at"), runner)
    unresolved: list[str] = []
    released: list[str] = []
    landed: list[str] = []
    for entry in payload["paths"]:
        rel = entry["path"]
        if rel not in dirty:
            landed.append(rel)
            continue
        if _path_fingerprint(repo_root / rel) != entry["fingerprint"]:
            # Drifted and dirty: the pinned bytes are gone either way. A later
            # commit having taken the path is merely evidence that the drift was
            # ordinary progress (silent); otherwise the claim is released with one
            # warn. Neither outcome can persist into the next pass.
            (landed if rel in carried else released).append(rel)
        else:
            unresolved.append(rel)

    if released:
        persisted = _release_closeout_claims(
            repo_root, released, runner, reason="drifted_uncarried")
        (alert_fn or _default_alert)(
            level="warn",
            title="PHASE-Z 放棄了已被覆寫的 failed-closeout 認領",
            body="\n".join([
                "## 發生什麼",
                "某班 fire 的產出曾被 commit gate 擋下，PHASE-Z 保留了 ownership receipt 準備下次補交。",
                "但下列路徑現在的內容已經不等於當時被擋下的 bytes —— 後來有人改過它。",
                "原本那份產出已不存在於工作區，**沒有任何東西可以補交**，所以系統放棄這幾條認領。",
                "",
                "## 有沒有東西不見",
                "沒有。PHASE-Z 沒有 commit、沒有覆蓋、沒有刪除任何檔案；現在的內容原封不動留在工作區，",
                "會由後續 fire 依它自己的 pre-fire baseline 正常收編。",
                "",
                "## 這則警報會再出現嗎",
                ("不會。認領已從 receipt 移除，下一班不會再評估到它。"
                 if persisted else
                 "**會** —— receipt 寫入失敗（磁碟問題），下一班會重新評估並再送一次。請檢查 "
                 "`.git/volpred_phase_z_failed_closeout.json` 是否可寫。"),
                "",
                "## 放棄認領的路徑",
                *[f"- {path}" for path in released],
            ]),
        )

    if not unresolved:
        # Nothing byte-identical is left to re-stage. Whatever remained was
        # landed or released, so the receipt has no further work to describe.
        _clear_failed_closeout(repo_root, runner)
        return {"committed": False, "reason": "released" if released else "already_closed",
                "landed": landed, "released": released}

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
        _recovery_capability=_FAILED_CLOSEOUT_RECOVERY_CAPABILITY,
        _closeout_authorization={
            entry["path"]: entry["fingerprint"]
            for entry in payload["paths"]
            if entry["path"] in unresolved
        },
    )
    if result.get("committed"):
        _clear_failed_closeout(repo_root, runner)
    if released:
        result = {**result, "released": released}
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
    """Record WHY this fire acted. Called via scripts/fire_receipt.py.

    Not an ownership or settlement point. Issue #43's workspace receipt decides
    producer output; this legacy receipt only upgrades a PHASE-Z machine-state or
    recovery commit message from a generated fallback to the agent's account.
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
    """Would PHASE-Z have to caption a legacy/machine-state commit itself?

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


def _streak_is_notifiable(streak: int) -> bool:
    """Re-page on a stuck foreign path at 3, 6, 12, 24, … fires — not every fire.

    This alert's exit is human (commit the file, or let reap_orphan_deliverables
    adopt it), and a path nobody ever collects would otherwise emit a CRITICAL
    once an hour forever. Same alert-fatigue class as the failed-closeout loop:
    an unbounded repeat rate trains the reader to ignore it, and the 25-hour
    incident (error_log 2026-07-17) is what that costs. Doubling backoff keeps
    the condition observable and escalating without being a metronome.
    """
    if streak < _FOREIGN_STREAK_CRITICAL:
        return False
    multiple, remainder = divmod(streak, _FOREIGN_STREAK_CRITICAL)
    return remainder == 0 and multiple & (multiple - 1) == 0  # 1, 2, 4, 8, …


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


def _classify_machine_churn(
    repo_root: Path,
    candidates: list[str],
) -> MachineChurnClassification:
    """Split declared machine-churn paths into (committable, deferred, corrupt).

    The lock/parse gates moved to ``volpred.ops.machine_churn`` on 2026-07-16 so the
    scheduled writers in ``scripts/`` could ask the same question this module asks —
    daily_update's dirty-guard was answering it with a bare dirty flag and latching
    itself shut. One implementation, two callers; see that module for the reasoning.
    """
    return classify_machine_churn(repo_root, candidates, label="phase_z")


# ── quarantine checkpoint (decision doc §4 D2) ───────────────────────────────
# "不掃進 main" and "不遺失" are two different guarantees, and this module only
# ever implemented the first. A dirty working tree is NOT preservation: those
# bytes can be overwritten by the next writer, reset by a human, or swept by a
# cleanup pass. 40+ paths sat foreign for up to 78 fires — visible, not safe.
#
# So: a path that is stuck (streak >= _FOREIGN_STREAK_CRITICAL) gets its current
# bytes copied into an immutable ref under _FOREIGN_QUARANTINE_REF_PREFIX. The
# rule the external review gave, verbatim:
#
#     不確定的內容一律自動保存，但絕不自動進 main。
#
# This is deliberately NOT an ownership decision and NOT an adoption heuristic
# (D1 forbids a fourth guess): it does not claim the bytes are anyone's, does
# not claim they are complete, and does not put them anywhere main can see. It
# only makes them *retrievable* — `git show <ref>:<path>` — after the working
# copy is gone. Whether they belong in main is still a human/D5 judgement.
#
# Everything below runs through git plumbing on a throwaway GIT_INDEX_FILE:
# no `git add`, no `git commit`, no `git stash`, no HEAD move, no index write,
# no working-tree write. The only shared mutations are object writes and one
# `update-ref` on a namespace nothing else reads, and both are serialised by
# volpred.ops.git_writer_lock like every other Git mutation in this module.
# Single owner is volpred.ops.foreign_incident: the D3 close-condition check has
# to look in exactly the namespace this writes to, and two string literals drift
# silently — a drift here reads as "preserved but not retrievable".
_FOREIGN_QUARANTINE_REF_PREFIX = QUARANTINE_REF_PREFIX
# Bound on one checkpoint. 40 stuck paths is today's reality; a runaway producer
# must not turn one fire into an unbounded plumbing loop inside the writer lease.
_QUARANTINE_MAX_PATHS = 200
_QUARANTINE_IDENTITY = {
    "GIT_AUTHOR_NAME": "volpred-phase-z",
    "GIT_AUTHOR_EMAIL": "phase-z@volpred.local",
    "GIT_COMMITTER_NAME": "volpred-phase-z",
    "GIT_COMMITTER_EMAIL": "phase-z@volpred.local",
}


def _quarantine_candidates(
    repo_root: Path, stuck: list[str],
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Split stuck paths into (checkpointable ``(mode, rel)``, skipped ``rel -> why``).

    The live-editing gate is ``_classify_machine_churn``'s ``deferred`` bucket —
    the same ``fcntl`` shared-lock probe every other writer in this repo uses. A
    producer holding the lock is mid-write, so its bytes are a torn snapshot and
    it is coming back for them anyway; checkpointing there would preserve a half
    file and claim it was the state. There is deliberately no second liveness
    notion here (see the decision doc §6: flock is the one signal this repo got
    right, and inventing a rival to it is exactly the class of bug D1 stops).
    """
    _, deferred, _ = _classify_machine_churn(repo_root, stuck)
    live = set(deferred)
    payload: list[tuple[str, str]] = []
    skipped: dict[str, str] = {}
    for rel in stuck:
        if rel in live:
            skipped[rel] = "live_writer"
            continue
        src = repo_root / rel
        try:
            if src.is_symlink() or not src.is_file():
                # A dirty *deletion* or a directory/symlink entry. Nothing to
                # preserve: the pre-deletion bytes already live in HEAD.
                skipped[rel] = "not_a_regular_file"
                continue
            mode = "100755" if os.access(src, os.X_OK) else "100644"
        except OSError as exc:  # silent-ok: 不是靜默 —— 失敗連同 errno 記進 skipped，
            skipped[rel] = f"stat_error: {exc}"  # 隨 checkpoint receipt 一起回報給呼叫端
            continue
        payload.append((mode, rel))
    return payload, skipped


def _quarantine_stuck_foreign(
    repo_root: Path,
    stuck: list[str],
    *,
    streaks: dict[str, int],
    hhmm: str,
    runner=subprocess.run,
) -> dict:
    """Checkpoint stuck foreign bytes into an immutable ref. Never fails a fire.

    Returns a receipt dict that is folded into ``run_phase_z``'s result (and the
    log line) so D3's incident/admission-control work has something mechanical to
    read. No second state file: the ref namespace itself is the durable record.
    """
    result: dict = {
        "ref": None, "created": False, "checkpointed": [], "skipped": {}, "reason": "",
    }
    if not stuck:
        result["reason"] = "no_stuck_paths"
        return result
    considered = stuck[:_QUARANTINE_MAX_PATHS]
    if len(stuck) > _QUARANTINE_MAX_PATHS:
        LOG.warning("phase_z: %d stuck paths exceed the quarantine cap — checkpointing the "
                    "%d longest-stuck this fire", len(stuck), _QUARANTINE_MAX_PATHS)
    payload, skipped = _quarantine_candidates(repo_root, considered)
    result["skipped"] = skipped
    if not payload:
        result["reason"] = "nothing_checkpointable"
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="volpred-phase-z-quarantine-") as tx:
            env = os.environ.copy()
            env["GIT_INDEX_FILE"] = str(Path(tx) / "index")  # never the real index
            env.update(_QUARANTINE_IDENTITY)
            with git_writer_lock(
                repo_root,
                actor=f"dispatch-phase-z-quarantine:{hhmm}",
                timeout_s=_COMMIT_TIMEOUT_S,
            ):
                stored: list[str] = []
                for mode, rel in payload:
                    blob = _git(
                        repo_root, "hash-object", "-w", "--no-filters", "--",
                        str(repo_root / rel),
                        timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                    )
                    if blob.returncode != 0:
                        skipped[rel] = f"hash_object_rc{blob.returncode}"
                        continue
                    sha = (blob.stdout or "").strip()
                    staged = _git(
                        repo_root, "update-index", "--add", "--cacheinfo",
                        f"{mode},{sha},{rel}",
                        timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                    )
                    if staged.returncode != 0:
                        skipped[rel] = f"update_index_rc{staged.returncode}"
                        continue
                    stored.append(rel)
                if not stored:
                    result["reason"] = "nothing_checkpointable"
                    return result

                write_tree = _git(
                    repo_root, "write-tree", timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                )
                if write_tree.returncode != 0:
                    LOG.warning("phase_z: quarantine write-tree rc=%d: %s",
                                write_tree.returncode, (write_tree.stderr or "")[-300:])
                    result["reason"] = "write_tree_error"
                    return result
                tree_sha = (write_tree.stdout or "").strip()

                # Same bytes as last fire → reuse that ref. Without this the same
                # 40 paths would mint a new ref every hour forever, and a refs
                # namespace nobody can read is a second kind of losing it.
                previous = _git(
                    repo_root, "for-each-ref", "--count=1", "--sort=-refname",
                    "--format=%(refname) %(objectname)", _FOREIGN_QUARANTINE_REF_PREFIX,
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                )
                if previous.returncode == 0 and (previous.stdout or "").strip():
                    prior_ref, _, prior_sha = (previous.stdout or "").strip().partition(" ")
                    prior_tree = _git(
                        repo_root, "rev-parse", "--verify", f"{prior_sha.strip()}^{{tree}}",
                        timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                    )
                    if prior_tree.returncode == 0 and (prior_tree.stdout or "").strip() == tree_sha:
                        result.update({"ref": prior_ref, "created": False,
                                       "checkpointed": stored, "reason": "unchanged"})
                        return result

                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                ref = f"{_FOREIGN_QUARANTINE_REF_PREFIX}/{ts}"
                body = "\n".join([
                    "Foreign paths stuck for >= "
                    f"{_FOREIGN_STREAK_CRITICAL} fires, checkpointed so the bytes survive "
                    "the working tree. NOT a claim of ownership, completeness or "
                    "readiness, and NOT reachable from main.",
                    "",
                    "Retrieve with: git show <ref>:<path>",
                    "",
                    *[f"- {rel} — {streaks.get(rel, 0)} fires" for rel in stored],
                ])
                # No parent: a quarantine checkpoint must never be an ancestor of
                # anything, so it can never be fast-forwarded into main by mistake.
                commit = _git(
                    repo_root, "commit-tree", tree_sha,
                    "-m", f"quarantine({hhmm}): {len(stored)} stuck foreign path(s)",
                    "-m", body,
                    timeout_s=_COMMIT_TIMEOUT_S, runner=runner, env=env,
                )
                if commit.returncode != 0:
                    LOG.warning("phase_z: quarantine commit-tree rc=%d: %s",
                                commit.returncode, (commit.stderr or "")[-300:])
                    result["reason"] = "commit_tree_error"
                    return result
                commit_sha = (commit.stdout or "").strip()
                # Empty old-value = "must not already exist"; a collision is a bug,
                # never a silent overwrite of somebody's only copy.
                landed = _git(
                    repo_root, "update-ref", ref, commit_sha, "",
                    timeout_s=_SHORT_TIMEOUT_S, runner=runner, env=env,
                )
                if landed.returncode != 0:
                    LOG.warning("phase_z: quarantine update-ref rc=%d: %s",
                                landed.returncode, (landed.stderr or "")[-300:])
                    result["reason"] = "update_ref_error"
                    return result
                result.update({"ref": ref, "created": True, "checkpointed": stored,
                               "commit": commit_sha, "reason": "checkpointed"})
    except GitWriterLockError as exc:
        LOG.warning("phase_z: quarantine skipped — git writer lock unavailable (%s)", exc)
        result["reason"] = "lock_unavailable"
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: quarantine checkpoint failed (%s) — working tree untouched", exc)
        result["reason"] = "error"
    return result


# ── persistent incident (decision doc §4 D3) ─────────────────────────────────

_STUCK_INCIDENT_ALERT_TITLE = "PHASE-Z 無主或過期檔案達處置門檻"


def _stuck_incident_alert_title(incident: dict) -> str:
    """Bind transport dedupe identity to one durable incident episode.

    ``send_alert`` keys its 24h ledger by level + title. A globally fixed title
    lets episode A's delivery suppress a disjoint B or a later e2 recurrence,
    after which B/e2 would incorrectly settle as delivered. The deterministic
    ``page_transport_id`` is inherited across overlapping successor rows and
    changes only for a disjoint/new-generation episode. It is therefore the
    correct transport identity; ``task_id`` remains the fallback for older rows.
    """
    task_id = str(
        incident.get("page_transport_id")
        or incident.get("task_id")
        or ""
    ).strip()
    return (
        f"{_STUCK_INCIDENT_ALERT_TITLE} [{task_id}]"
        if task_id
        else _STUCK_INCIDENT_ALERT_TITLE
    )


def _stuck_incident_alert_alias_titles(incident: dict) -> list[str]:
    """Map every merged predecessor transport id to its 24h ledger title."""
    primary = str(incident.get("page_transport_id") or "").strip()
    aliases = incident.get("page_transport_alias_ids") or []
    return [
        _stuck_incident_alert_title({"page_transport_id": transport_id})
        for transport_id in dict.fromkeys(
            str(value).strip() for value in aliases if str(value).strip()
        )
        if transport_id != primary
    ]


def _alert_accepts_dedup_alias_titles(alert_fn) -> bool:
    """Keep injected legacy test/report callbacks source compatible."""
    try:
        parameters = inspect.signature(alert_fn).parameters.values()
    except (TypeError, ValueError):  # silent-ok: opaque injected callback uses legacy 3-keyword contract
        return False
    return any(
        parameter.name == "dedup_alias_titles"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _reconcile_open_incidents(repo_root: Path, tasks_path: Path) -> dict:
    """重跑每張未關 incident 的判準：收乾淨的關掉，其餘更新降載旗標。Never fails a fire.

    降載必須能自己解除。靠人來關，等於把 forcing function 的解除端交給正是「沒有人
    會回來收」的那個人 —— 而這個 class 的全部教訓就是別再依賴那個人。
    """
    empty = {"closed": [], "deferred": []}
    if not tasks_path.exists():
        return empty
    try:
        outcome = reconcile_incidents(repo_root, tasks_path=tasks_path)
    except Exception as exc:  # noqa: BLE001 — 收單失敗不值得讓一班 fire 掛掉
        LOG.warning("phase_z: incident reconcile failed (%s) — 降載維持，下一班再試", exc)
        return empty
    for entry in outcome["closed"]:
        LOG.info("phase_z: incident %s closed — 關閉條件全綠（%d 個路徑），降載解除",
                 entry["task_id"], len(entry["verdict"]["checked"]))
    for entry in outcome["deferred"]:
        LOG.info("phase_z: incident %s 降載暫緩 — 剩餘 %d 個路徑都是活躍碼（作者仍在編輯）",
                 entry["task_id"], len(entry["verdict"]["deferred"]))
    return outcome


def _open_stuck_incident(
    repo_root: Path,
    stuck: list[str],
    *,
    streaks: dict[str, int],
    quarantine: dict,
) -> dict:
    """Create-or-update the single incident for this stuck set. Never fails a fire.

    The queue write is the mechanism that turns "78 fires of red logs" into a
    thing with an owner, a close condition and a cost (see
    ``volpred.ops.foreign_incident``). It is still not worth taking a dispatch
    fire down for: on failure this returns ``reason="error"``, which is exactly
    the case where the caller falls back to the legacy backed-off CRITICAL rather
    than going quiet.
    """
    tasks_path = repo_root / "storage" / "next_tasks.json"
    if not stuck:
        # 「這班沒有卡住的檔案」正是最該收掉既有 incident 的一班。
        _reconcile_open_incidents(repo_root, tasks_path)
        return {"fingerprint": None, "task_id": None, "created": False,
                "updated": False, "reason": "no_stuck_paths"}
    if not tasks_path.exists():
        # A checkout with no task pool has no scheduler to de-rate, so there is
        # nothing for an incident to control. PHASE-Z does not conjure the
        # canonical queue into existence — that would be a new writer creating
        # canonical state as a side effect. Say so, and let the caller page.
        LOG.warning("phase_z: no task pool at %s — cannot open a stuck-path incident; "
                    "falling back to the backed-off CRITICAL", tasks_path)
        return {"fingerprint": None, "task_id": None, "created": False,
                "updated": False, "reason": "no_queue"}
    try:
        receipt = upsert_incident(
            paths=stuck,
            streaks=streaks,
            quarantine_ref=quarantine.get("ref"),
            tasks_path=tasks_path,
        )
    except Exception as exc:  # noqa: BLE001 — a queue write must not fail a fire
        # 建單失敗不該連帶阻止既有 incident 的機械解除端。
        _reconcile_open_incidents(repo_root, tasks_path)
        LOG.warning("phase_z: stuck-path incident upsert failed (%s) — falling back "
                    "to the backed-off CRITICAL so the condition is not silent", exc)
        return {"fingerprint": None, "task_id": None, "created": False,
                "updated": False, "reason": "error", "error": str(exc)}
    # 解除端跟建立端在同一班 fire lifecycle 跑，而且必須在 upsert **之後**：
    # 先 reconcile 再建單會讓新 row 缺少首次 ``derates`` verdict；slot budget 對
    # 缺值採 fail-safe True，於是 covered live authoring 仍被錯降載一整班。
    # 這裡重跑 canonical assessor 並把結果持久化，budget 仍維持 read-only、
    # 不複製 grace 判斷，也不在派工熱路徑執行 git。
    _reconcile_open_incidents(repo_root, tasks_path)
    LOG.info("phase_z: stuck-path incident %s (%s) — task=%s, fingerprint=%s",
             receipt["reason"], "created" if receipt["created"] else "updated",
             receipt["task_id"], receipt["fingerprint"])
    return receipt


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
        never take down the daemon, and the hard timeout bounds it. This is an
        independent safety property; the old scheduler pregate was retired.

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
    probe failed), ``fire_lifecycle`` (durable generation + exact baseline when
    capture succeeded), plus ``guard_output`` when it printed anything. Never
    raises.
    """
    repo_root = Path(repo_root)

    # `git_runner` is separate from `runner`: the latter fakes the guard
    # subprocess in tests, and a fake that answers `[sys.executable, guard]`
    # cannot also answer `git status`.
    baseline = _dirty_paths(repo_root, git_runner)
    lifecycle: dict[str, object] = {}
    if baseline is None:
        # Never leave a previous fire's singleton available to a new fire that
        # failed to capture its own generation. New code will reject the
        # missing durable lifecycle; this unlink also fail-closes any
        # mixed-version closeout still reading the transitional file.
        _consume_pre_fire_snapshot(repo_root, git_runner)
        # No baseline → PHASE-Z will decline to commit and say so. Fail-open for
        # the fire itself (this function may never veto a dispatch), fail-closed
        # for the commit that follows it.
        snapshot_size = -1
    else:
        snapshot_size = len(baseline)
        lifecycle["fire_lifecycle"] = {
            "generation_id": uuid.uuid4().hex,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "pre_fire_dirty": sorted(baseline),
        }
        # Transitional fallback for a mixed-version daemon. New closeout uses
        # the lifecycle bound into dispatch_state.json, not this singleton.
        _write_pre_fire_snapshot(repo_root, baseline, git_runner)
        LOG.info("pre_fire_guard: baselined %d dirty path(s) at fire start", snapshot_size)

    script = repo_root.joinpath(*_GUARD_SCRIPT_RELPATH)
    if not script.exists():
        LOG.warning("pre_fire_guard: %s missing — no conflict backstop this fire", script)
        return {
            "ran": False, "reason": "guard_missing",
            "dirty_at_fire_start": snapshot_size, **lifecycle,
        }

    try:
        proc = runner(
            [sys.executable, str(script), "--quiet"],
            capture_output=True,
            text=True,
            timeout=_GUARD_TIMEOUT_S,
            cwd=str(repo_root),
            env=external_child_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        LOG.warning("pre_fire_guard: timeout after %ss — fail-open, firing anyway", _GUARD_TIMEOUT_S)
        return {
            "ran": False, "reason": "timeout",
            "dirty_at_fire_start": snapshot_size, **lifecycle,
        }
    except OSError as exc:
        LOG.warning("pre_fire_guard: spawn failed (%s) — fail-open, firing anyway", exc)
        return {
            "ran": False, "reason": "spawn_error",
            "dirty_at_fire_start": snapshot_size, **lifecycle,
        }

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
        return {
            "ran": True, "reason": "nonzero_exit",
            "exit_code": proc.returncode, "dirty_at_fire_start": snapshot_size,
            **lifecycle,
        }

    result = {
        "ran": True, "reason": "ok",
        "dirty_at_fire_start": snapshot_size, **lifecycle,
    }
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


def _git_bytes(
    repo_root: Path,
    *args: str,
    timeout_s: int,
    runner=subprocess.run,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Binary-output counterpart of :func:`_git` for candidate blob checks."""
    kwargs = {
        "capture_output": True,
        "text": False,
        "timeout": timeout_s,
        "check": False,
    }
    kwargs.update(git_writer_subprocess_kwargs(env))
    return runner(["git", "-C", str(repo_root), *args], **kwargs)


def _verify_machine_churn_candidate(
    repo_root: Path,
    identities: dict[str, MachineChurnIdentity],
    *,
    runner,
    env: dict[str, str],
) -> list[str]:
    """Bind classification evidence to both the worktree and candidate index.

    A pathname is not an identity: a writer can atomically replace it after the
    lock/parse gate.  The index blob must contain the exact bytes that passed
    that gate, and the worktree inode must still be the one classified.  Any
    mismatch discards the entire alternate-index transaction.
    """
    mismatches: list[str] = []
    for rel, identity in sorted(identities.items()):
        staged = _git(
            repo_root,
            "ls-files",
            "--stage",
            "-z",
            "--",
            rel,
            timeout_s=_SHORT_TIMEOUT_S,
            runner=runner,
            env=env,
        )
        if staged.returncode != 0:
            mismatches.append(rel)
            continue
        entries = _parse_stage_entries(staged.stdout or "")
        if not identity.exists:
            if entries or not machine_churn_identity_matches(repo_root, identity):
                mismatches.append(rel)
            continue
        records = entries.get(rel, ())
        if set(entries) != {rel} or len(records) != 1:
            mismatches.append(rel)
            continue
        fields = records[0].split()
        if len(fields) != 3 or fields[0] != identity.git_mode:
            mismatches.append(rel)
            continue
        blob = _git_bytes(
            repo_root,
            "cat-file",
            "blob",
            fields[1],
            timeout_s=_SHORT_TIMEOUT_S,
            runner=runner,
            env=env,
        )
        if (
            blob.returncode != 0
            or hashlib.sha256(blob.stdout or b"").hexdigest() != identity.sha256
            or not machine_churn_identity_matches(repo_root, identity)
        ):
            mismatches.append(rel)
    return mismatches


def _verify_closeout_candidate(
    repo_root: Path,
    authorization: dict[str, dict[str, object]],
    *,
    base_sha: str,
    runner,
    env: dict[str, str],
) -> list[str]:
    """Bind a legacy receipt to the exact candidate-index bytes it authorized.

    Checking only the live path after ``git add`` is insufficient: a writer can
    swap A→B while Git reads it, then restore pinned A before the live recheck.
    Validate both surfaces so the candidate cannot contain B under A's receipt.
    Old receipts did not persist mode, so tracked files inherit the pinned base
    tree mode and untracked regular files are limited to conservative 100644;
    the staged Git mode must match that fail-closed fallback.
    """
    mismatches: list[str] = []
    for rel, expected in sorted(authorization.items()):
        staged = _git(
            repo_root,
            "ls-files",
            "--stage",
            "-z",
            "--",
            rel,
            timeout_s=_SHORT_TIMEOUT_S,
            runner=runner,
            env=env,
        )
        if staged.returncode != 0:
            mismatches.append(rel)
            continue
        entries = _parse_stage_entries(staged.stdout or "")
        live = _path_fingerprint(repo_root / rel)
        if live != expected:
            mismatches.append(rel)
            continue

        kind = expected.get("kind")
        if kind == "missing":
            if entries:
                mismatches.append(rel)
            continue

        records = entries.get(rel, ())
        if set(entries) != {rel} or len(records) != 1:
            mismatches.append(rel)
            continue
        fields = records[0].split()
        if len(fields) != 3 or fields[2] != "0":
            mismatches.append(rel)
            continue
        staged_mode, blob_oid = fields[0], fields[1]
        blob = _git_bytes(
            repo_root,
            "cat-file",
            "blob",
            blob_oid,
            timeout_s=_SHORT_TIMEOUT_S,
            runner=runner,
            env=env,
        )
        if blob.returncode != 0:
            mismatches.append(rel)
            continue

        if kind == "file":
            # Pre-retirement receipts did not persist mode. They therefore
            # cannot authorize a later chmod: tracked files inherit the pinned
            # base tree's mode; an untracked regular file gets Git's conservative
            # 100644 default. An old untracked executable is left for manual
            # attribution rather than guessing that +x belonged to the receipt.
            base_entries = _base_tree_entries(
                repo_root,
                base_sha,
                [rel],
                runner=runner,
            )
            if base_entries is None:
                mismatches.append(rel)
                continue
            base_records = base_entries.get(rel, ())
            if len(base_records) > 1:
                mismatches.append(rel)
                continue
            expected_mode = (
                base_records[0].split()[0]
                if base_records
                else "100644"
            )
            if (
                staged_mode != expected_mode
                or len(blob.stdout or b"") != expected.get("size")
                or hashlib.sha256(blob.stdout or b"").hexdigest()
                != expected.get("sha256")
            ):
                mismatches.append(rel)
        elif kind == "symlink":
            if (
                staged_mode != "120000"
                or blob.stdout != os.fsencode(str(expected.get("target", "")))
            ):
                mismatches.append(rel)
        else:
            # Directories/special files were representable in old fingerprints
            # but are not safe Git blob authorizations.
            mismatches.append(rel)
    return mismatches


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


#: How long a provably-dead holder's lock must sit before anyone reclaims it.
#: Not a liveness signal — liveness is proven separately and must already say
#: "gone". This only keeps a reclaim from racing a holder that is mid-adopt.
_INDEX_LOCK_RECLAIM_MIN_AGE_S = 120.0


def _index_lock_owner_path(lock_path: Path) -> Path:
    return lock_path.with_name(lock_path.name + ".volpred-owner.json")


def _write_index_lock_owner(lock_path: Path) -> None:
    """Stamp who holds `.git/index.lock`, so a crash is later provable.

    Git's own index.lock carries no owner identity: the file's existence *is*
    the claim. That works when the holder always gets to run its cleanup, and
    this holder does not — the supervisor SIGTERMs itself on stale-code reload
    and SIGKILLs workers on custody loss, neither of which runs a `finally`.
    A leaked lock then blocks every writer in the repo with no way to tell
    "held" from "abandoned", which is exactly what stranded three commits for
    43 minutes, 80 seconds and 43 minutes again on 2026-08-04.

    Best-effort by construction: failing to write the sidecar must not fail the
    refresh. The cost of a missing sidecar is only that the lock becomes
    unreclaimable-by-us, which is the same safe state as before this existed.
    """
    try:
        _index_lock_owner_path(lock_path).write_text(
            json.dumps(
                {
                    "actor": "phase_z",
                    "pid": os.getpid(),
                    "pid_start_wall": get_process_start_wall(os.getpid()),
                    "host": os.uname().nodename,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.warning("phase_z: could not stamp index-lock owner (%s)", exc)


def _clear_index_lock_owner(lock_path: Path) -> None:
    try:
        _index_lock_owner_path(lock_path).unlink(missing_ok=True)
    except OSError:
        pass  # silent-ok: sidecar is advisory; a stale one fails closed on reclaim


def reclaim_leaked_index_lock(
    repo_root: Path,
    *,
    now: datetime | None = None,
    min_age_s: float = _INDEX_LOCK_RECLAIM_MIN_AGE_S,
) -> dict:
    """Release `.git/index.lock` only when its holder is provably gone.

    Fails closed at every step. A lock with no sidecar is never touched: that is
    either real Git mid-write or another tool, and deleting it would corrupt a
    live index update — the exact damage a naive "stale lock cleaner" does. We
    reclaim only a lock this module stamped, on this host, whose holder pid
    `procutil` reports as DEAD or REUSED (never `unverified`, which means the
    probe itself failed and proves nothing), and only after `min_age_s`.
    """
    index_lock = repo_root / ".git" / "index.lock"
    owner_path = _index_lock_owner_path(index_lock)
    if not index_lock.exists():
        return {"reclaimed": False, "reason": "no_lock"}
    if not owner_path.exists():
        return {"reclaimed": False, "reason": "not_ours"}
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"reclaimed": False, "reason": "owner_unreadable", "detail": str(exc)[:200]}
    if owner.get("host") != os.uname().nodename:
        return {"reclaimed": False, "reason": "foreign_host"}

    pid = owner.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {"reclaimed": False, "reason": "owner_pid_invalid"}
    if pid == os.getpid():
        return {"reclaimed": False, "reason": "self_held"}
    identity = check_identity(pid, owner.get("pid_start_wall"))
    if identity not in {IDENTITY_DEAD, IDENTITY_MISMATCH}:
        return {"reclaimed": False, "reason": f"holder_{identity}"}

    current = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(str(owner.get("created_at")))
    except ValueError:
        return {"reclaimed": False, "reason": "owner_timestamp_invalid"}
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_s = (current - created).total_seconds()
    if age_s < min_age_s:
        return {"reclaimed": False, "reason": "too_fresh", "age_s": age_s}

    try:
        index_lock.unlink(missing_ok=True)
        owner_path.unlink(missing_ok=True)
    except OSError as exc:
        return {"reclaimed": False, "reason": "unlink_failed", "detail": str(exc)[:200]}
    receipt = {
        "reclaimed": True,
        "holder_pid": pid,
        "holder_identity": identity,
        "age_s": round(age_s, 1),
        "reclaimed_at": current.isoformat(),
    }
    LOG.warning("phase_z: reclaimed leaked index.lock %s", receipt)
    return receipt


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
        _write_index_lock_owner(lock_path)
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
        if owns_lock:
            # Unconditional: `os.replace` consumes the lock on adopt but leaves
            # the sidecar, and a stray sidecar would later describe a lock that
            # a *different* writer owns.
            _clear_index_lock_owner(lock_path)
        if owns_lock and not adopted:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass  # silent-ok: the CRITICAL caller reports failed refresh


def _default_alert(
    *,
    level: str,
    title: str,
    body: str,
    dedup_alias_titles: list[str] | None = None,
) -> dict:
    """Ship a red-gate alert through the canonical Python send_alert API.

    Deferred import (matches alerts.py's own lazy-import convention) so phase_z
    stays stdlib-only at module load — the supervisor imports it every fire and a
    heavy `volpred.ops` import chain at that point would slow every tick. A send
    failure is logged, never raised: the alert is a notification, and a broken
    mailer must not turn a red-test observation into a crashed tick."""
    try:
        from volpred.ops.alerts import send_alert

        return send_alert(
            level,
            title,
            body,
            dedup_alias_titles=dedup_alias_titles or (),
        )
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
    timeout_s: float = _TEST_GATE_TIMEOUT_S,
) -> dict:
    """Run one side of the attribution comparison inside its disposable clone.

    ``timeout_s`` defaults to the post-commit gate's budget.  The orphan-half
    probe below runs the same machinery many times in one tick and passes a
    tighter budget so a slow suite cannot stall the supervisor.
    """
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
    env = external_child_environment(
        overrides={
            "VOLPRED_NO_EMAIL": "1",
            "VOLPRED_NO_REMOTE_WRITE": "1",
            "VOLPRED_NO_REMOTE_READ": "1",
            "VOLPRED_NO_CANONICAL_WRITE": "1",
            "VOLPRED_CI_PARITY": "0",
            "PYTHONPATH": os.pathsep.join(
                [str(clone_root), str(clone_root / "src")]
            ),
        }
    )
    try:
        proc = test_runner(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
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


# ---------------------------------------------------------------------------
# Orphan halves: an exit for dirty-at-fire-start paths that are provably the
# missing half of a commit that already landed.
#
# The ownership model knows two kinds of dirt: produced by this fire (commit)
# and dirty before this fire (never touch, only warn).  A path that is the
# *other half* of an already-landed commit falls in the second bucket and stays
# there forever — every fire re-reports it and CI stays red for good.  That is
# the same shape as the 2026-07-18 untracked-closeout incident: a class of path
# with no exit from the state machine.
#
# "Dirty before the fire" ⇒ "someone else is still typing it" is an INFERENCE.
# It has exactly one mechanically falsifiable exception, and the direction of
# the evidence is the whole safety argument:
#
#     A test that is ALREADY COMMITTED at HEAD is RED, and materialising this
#     path's working-tree bytes on top of a pristine HEAD turns that same test
#     GREEN.
#
# Third-party work in progress does not do that.  A half-written edit either
# changes nothing about an already-landed test or breaks more of it; only the
# missing half of a split commit repairs a test that HEAD already ships.
#
# Everything else about this path is fail-closed, matching every other rule in
# this file: no red test at HEAD, a clone failure, a pytest timeout, an
# unattributable outcome, or more candidates than the cap ⇒ adopt nothing and
# leave the existing warning exactly as it was.
# ---------------------------------------------------------------------------

# Cost ceiling for one tick. Each candidate costs one shared clone plus one
# pytest run of the tests that map to it, on top of the single HEAD probe.
_ORPHAN_HALF_MAX_CANDIDATES = 8
_ORPHAN_HALF_PROBE_TIMEOUT_S = 240
_ORPHAN_HALF_BUDGET_S = 900


def _is_test_path(rel: str) -> bool:
    """Paths whose bytes are the *thermometer*, never the patient.

    The evidence direction requires the failing test to come from HEAD.  If a
    working-tree test file were allowed to be materialised as a candidate, an
    in-progress edit that weakens an assertion would flip red→green and get
    itself adopted — the probe would be measuring the candidate's own relaxed
    thermometer.  Test files are therefore never candidates, only evidence.
    """
    return (
        rel.startswith(("tests/", "scripts/tests/"))
        or Path(rel).name.startswith("test_")
    )


# ---------------------------------------------------------------------------
# Split-pair guard (task assign_b802db4f, 2026-07-22)
#
# A refactor lands as two halves: a new source module and the test that imports
# it. PHASE-Z classifies paths by *when they went dirty*, never by what they mean
# to each other, so the halves routinely land on opposite sides of the ownership
# line -- the test went dirty during this fire (owned), the source was already
# dirty at fire start (foreign, excluded). The candidate index then holds a test
# whose import target is absent from it, audit-test-imports rejects it by design,
# the commit rolls back, every path stays dirty, and the next fire rebuilds the
# identical doomed candidate. Observed 2026-07-21/22: 21 foreign paths stuck for
# >=3 fires and ~13 hours of fire output rolled back, because the receipt written
# on failure pins only `owned` -- so recovery replays the same half-set forever.
#
# The exit is to spot the split before staging and defer the *test* half. We
# never pull the foreign source in: that is stealing another session's in-flight
# bytes, which is exactly what ownership classification exists to prevent.
# Deferring is cheap and strictly bounded -- only an *untracked* test whose
# missing half is itself untracked and present on disk qualifies, and a
# brand-new test carries no regression signal that HEAD did not already lack. A
# tracked test that breaks is a real break and still blocks the commit.
# ---------------------------------------------------------------------------

_AUDITED_IMPORT_ROOTS = {"volpred": "src", "scripts": "."}


def _referenced_source_paths(repo_root: Path, rel: str) -> set[str]:
    """Repo-relative source paths a test needs, by import and by path literal.

    Mirrors what ``scripts/audit_test_imports.py`` resolves: dotted modules under
    ``volpred``/``scripts`` (including ``from pkg import submodule``, where the
    submodule is the half that goes missing) plus bare ``scripts/x.py`` literals.
    A miss here costs nothing -- the guard only ever *drops* a path, so an
    unresolved dependency just degrades to today's behaviour of letting the gate
    reject the commit.
    """
    try:
        source = (repo_root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, ValueError, SyntaxError):
        return set()

    dotted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dotted.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            dotted.add(node.module)
            dotted.update(f"{node.module}.{alias.name}" for alias in node.names)

    out: set[str] = set()
    for name in dotted:
        base = _AUDITED_IMPORT_ROOTS.get(name.split(".", 1)[0])
        if base is None:
            continue
        stem = Path(base, *name.split("."))
        for cand in (stem.with_suffix(".py"), stem / "__init__.py"):
            if (repo_root / cand).is_file():
                out.add(cand.as_posix())
                break

    for literal in re.findall(r"['\"](scripts/[\w./-]+\.py)['\"]", source):
        if (repo_root / literal).is_file():
            out.add(literal)
    return out


def _split_pair_deferrals(
    repo_root: Path, to_stage: list[str], base_sha: str, *, runner
) -> dict[str, list[str]]:
    """Untracked tests in ``to_stage`` whose source half is absent from the candidate.

    Returns ``{test_rel: [missing source rel, ...]}``; empty when nothing is split.
    """
    staged = set(to_stage)
    tracked_cache: dict[str, bool] = {}

    def _tracked(rel: str) -> bool:
        if rel not in tracked_cache:
            probe = _git(
                repo_root, "cat-file", "-e", f"{base_sha}:{rel}",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            tracked_cache[rel] = probe.returncode == 0
        return tracked_cache[rel]

    deferrals: dict[str, list[str]] = {}
    for rel in to_stage:
        if not _is_test_path(rel) or _tracked(rel):
            continue
        missing = sorted(
            dep for dep in _referenced_source_paths(repo_root, rel)
            if dep not in staged and not _tracked(dep)
        )
        if missing:
            deferrals[rel] = missing
    return deferrals


def _orphan_half_candidates(repo_root: Path, foreign: list[str]) -> list[str]:
    """Foreign dirty paths eligible to be *proved* a missing half.

    Narrow on purpose (the adopted set must be a proved minimum, never "the
    whole baseline"):
      - inside the gated trees only — the same scope the post-commit gate uses;
      - never a test file (see _is_test_path);
      - must exist as a readable file now: a deletion has no bytes to
        materialise, so it can never be shown to repair anything.
    """
    candidates: list[str] = []
    for rel in sorted(foreign):
        if not rel.startswith(_GATED_CODE_PREFIXES):
            continue
        if _is_test_path(rel):
            continue
        if not (repo_root / rel).is_file():
            continue
        candidates.append(rel)
    return candidates


def _orphan_half_owner_groups(foreign_ownership: dict) -> dict[str, str]:
    """Map each risky path to the producer cohort that owns its probe budget."""
    groups: dict[str, str] = {}
    for rel, owner in (foreign_ownership.get("stale") or {}).items():
        groups[str(rel)] = f"stale:{owner}"
    for rel, owners in (foreign_ownership.get("contested") or {}).items():
        owner_key = ",".join(sorted(str(owner) for owner in owners))
        groups[str(rel)] = f"contested:{owner_key}"
    for rel in foreign_ownership.get("unowned") or []:
        groups[str(rel)] = "unowned"
    return groups


def _failure_ids_for(failure_ids: set[str], targets: list[str]) -> set[str]:
    """Failing node ids that live in ``targets``.

    Both id sources (junit ``file::class::name`` and pytest's short summary)
    start with the test file path, so the file is the leading segment.
    """
    wanted = set(targets)
    return {fid for fid in failure_ids if fid.split("::", 1)[0] in wanted}


def _materialise_candidate(repo_root: Path, clone_root: Path, rel: str) -> bool:
    """Copy one working-tree path's bytes into a disposable clone."""
    source = repo_root / rel
    destination = clone_root / rel
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    except OSError as exc:
        LOG.warning("phase_z: orphan-half probe cannot materialise %s (%s)", rel, exc)
        return False
    return True


def _adopt_orphan_halves(
    repo_root: Path,
    foreign: list[str],
    *,
    runner,
    test_runner,
    monotonic=time.monotonic,
    owner_groups: dict[str, str] | None = None,
) -> dict:
    """Prove (or fail to prove) which foreign dirty paths are missing halves.

    Returns an observability dict — never raises, never touches the live
    checkout, and never runs pytest anywhere but a disposable clone (the live
    tree's canonical state is rewritten by 24/7 daemons, so nothing observed
    there could be evidence; see _post_commit_test_gate).

    Keys: ``adopted`` (list[str], the proved minimum — may be empty),
    ``reason`` (why the pass stopped or what it concluded), ``considered``
    (candidates actually probed) and ``evidence`` (per adopted path: the node
    ids it turned green, and the test files that ran).
    """
    result: dict = {
        "adopted": [],
        "reason": "no_candidates",
        "considered": [],
        "evidence": {},
        "skipped_groups": {},
    }
    candidates = _orphan_half_candidates(repo_root, foreign)
    if not candidates:
        return result
    grouped: dict[str, list[str]] = {}
    for rel in candidates:
        group = (owner_groups or {}).get(rel, "unowned")
        grouped.setdefault(group, []).append(rel)
    skipped_groups = {
        group: paths
        for group, paths in sorted(grouped.items())
        if len(paths) > _ORPHAN_HALF_MAX_CANDIDATES
    }
    candidates = [
        rel
        for group, paths in sorted(grouped.items())
        if group not in skipped_groups
        for rel in paths
    ]
    result["skipped_groups"] = skipped_groups
    if skipped_groups:
        LOG.info(
            "phase_z: orphan-half probe skipped %d oversized owner group(s): %s",
            len(skipped_groups),
            {
                group: len(paths)
                for group, paths in skipped_groups.items()
            },
        )
    if not candidates:
        return {
            **result,
            "reason": "too_many_candidates",
            "considered": sorted(
                rel for paths in skipped_groups.values() for rel in paths
            ),
        }

    deadline = monotonic() + _ORPHAN_HALF_BUDGET_S
    try:
        # Pin the revision once. Every clone below materialises the SAME sha, so
        # a concurrent writer advancing HEAD mid-probe cannot make the "red" run
        # and the "green" run disagree about what they were comparing.
        head_probe = _git(repo_root, "rev-parse", "--verify", "HEAD",
                          timeout_s=_SHORT_TIMEOUT_S, runner=runner)
        if head_probe.returncode != 0:
            return {**result, "reason": "head_resolve_error", "considered": candidates}
        head_sha = (head_probe.stdout or "").strip()

        with tempfile.TemporaryDirectory(prefix="volpred-phase-z-orphan-") as tmp:
            temp_root = Path(tmp)
            head_root = temp_root / "head"
            cloned = _clone_revision(repo_root, head_root, head_sha, runner=runner)
            if not cloned["ok"]:
                LOG.warning("phase_z: orphan-half probe could not clone HEAD (%s)", cloned["reason"])
                return {**result, "reason": cloned["reason"], "considered": candidates}

            # Test targets are resolved against the CLONE, so every test that
            # can serve as evidence is HEAD's committed version by construction.
            plan = _resolve_test_targets(head_root, candidates)
            targets = plan["targets"]
            if not targets:
                return {**result, "reason": "no_mapped_tests", "considered": candidates}

            head = _run_clone_pytest(
                head_root, targets=targets, k_expr=plan["k_expr"],
                test_runner=test_runner, timeout_s=_ORPHAN_HALF_PROBE_TIMEOUT_S,
            )
            head_rc = head["returncode"]
            if head_rc is None:
                LOG.warning("phase_z: orphan-half probe HEAD run did not finish (%s)",
                            head.get("reason"))
                return {**result, "reason": f"head_{head.get('reason', 'error')}",
                        "considered": candidates}
            if head_rc != 1:
                # rc 0 (green), 5 (collected nothing) and 2 (collection error)
                # all mean the same thing here: no red test at HEAD to repair.
                # Constraint: this path only ever starts from a red HEAD.
                return {**result, "reason": "head_not_red", "head_returncode": head_rc,
                        "considered": candidates}
            head_ids = set(head.get("failure_ids", []))
            if not head_ids:
                # rc=1 with no attributable node id: cannot prove anything about
                # *which* test flipped, so prove nothing.
                return {**result, "reason": "head_failures_unattributable",
                        "considered": candidates}

            adopted: list[str] = []
            evidence: dict[str, dict] = {}
            considered: list[str] = []
            for index, rel in enumerate(candidates):
                if monotonic() >= deadline:
                    LOG.warning("phase_z: orphan-half probe out of budget after %d candidate(s)",
                                index)
                    result_reason = "budget_exhausted"
                    return {"adopted": adopted, "reason": result_reason,
                            "considered": considered, "evidence": evidence,
                            "unprobed": candidates[index:],
                            "skipped_groups": skipped_groups}
                own = _resolve_test_targets(head_root, [rel])["targets"]
                own_red = _failure_ids_for(head_ids, own)
                if not own_red:
                    # No test that HEAD ships and that maps to this path is red.
                    # Nothing this path's bytes could repair ⇒ not a missing half.
                    continue
                considered.append(rel)
                probe_root = temp_root / f"probe-{index}"
                probe = _clone_revision(repo_root, probe_root, head_sha, runner=runner)
                if not probe["ok"]:
                    LOG.warning("phase_z: orphan-half probe clone failed for %s (%s)",
                                rel, probe["reason"])
                    continue
                if not _materialise_candidate(repo_root, probe_root, rel):
                    continue
                after = _run_clone_pytest(
                    probe_root, targets=own, k_expr=None,
                    test_runner=test_runner, timeout_s=_ORPHAN_HALF_PROBE_TIMEOUT_S,
                )
                if after["returncode"] is None:
                    LOG.warning("phase_z: orphan-half probe for %s did not finish (%s)",
                                rel, after.get("reason"))
                    continue
                after_ids = set(after.get("failure_ids", []))
                repaired = sorted(own_red - after_ids)
                regressed = sorted(after_ids - head_ids)
                if not repaired or regressed:
                    # Either it fixed nothing (ordinary work in progress) or it
                    # broke something HEAD did not have (definitely not the
                    # missing half of a green commit). Leave it alone.
                    continue
                adopted.append(rel)
                evidence[rel] = {
                    "turned_green": repaired,
                    "ran": after.get("ran", own),
                    "returncode": after["returncode"],
                }
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: orphan-half probe aborted (%s) — adopting nothing", exc)
        return {**result, "reason": "probe_error", "detail": str(exc)[:300]}

    return {
        "adopted": adopted,
        "reason": "adopted" if adopted else "no_proof",
        "considered": considered,
        "evidence": evidence,
        "skipped_groups": skipped_groups,
    }


def _post_commit_test_gate(
    repo_root: Path,
    *,
    commit_sha: str,
    hhmm: str,
    runner,
    test_runner,
    internal_alert_fn,
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
    # No owner to-do heading here. A red test on an auto-committed change is
    # work the platform does, not a chore the owner runs (boss msg 907, 2026-07-17:
    # 「不要建議我行動 是你自己立刻去處理」). This routes through the internal
    # remediation bridge, which mints a P1 repair task and stays out of the owner's
    # inbox on the first occurrence; the fix/revert steps below are context for the
    # agent that picks that task up, not commands addressed to the owner.
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
        "## 修復線索（供接手任務）",
        "1. 隔離重現：",
        f"   uv run --extra dev python -m pytest {' '.join(targets)} -q"
        + (f" -k \"{k_expr}\"" if k_expr else ""),
        "2. " + _BASELINE_ACTION[baseline],
        "3. 失敗尾段：",
        "",
        "```",
        tail or "(no output captured)",
        "```",
    ])
    # Fingerprint = the node ids newly failing at HEAD (vs HEAD^). Distinct
    # failures stay distinct incidents in the bridge's escalation counter instead
    # of conflating every unrelated red under one coarse alert_key.
    new_failure_fp = sorted(current_ids - parent_ids) or list(code_files)
    alert_result = internal_alert_fn(
        alert_key="phase_z_test_gate_red",
        level="critical",
        title=title,
        body=body,
        observed_at=datetime.now(timezone.utc),
        fingerprint=new_failure_fp,
    )
    return {"passed": False, "reason": "new_failure", "failing_tail": tail,
            "alert": alert_result, **comparison, **base}


def _gate_review_fingerprint(repo_root: Path, gate_paths: list[str]) -> str:
    """Stable id for one *content* state of the deferred gate paths.

    Same bytes still sitting dirty next fire → same id → ``if_exists='skip'``
    turns the second queue attempt into a no-op. Edit the gate again → new id →
    a fresh review task. This is what keeps the review lane from re-filing the
    identical task every hour (the "連續 N 班同一 reason" failure mode).
    """
    digest = hashlib.sha256()
    for rel in sorted(gate_paths):
        blob = repo_root / rel
        try:
            body = blob.read_bytes()
        except OSError:
            body = b"<unreadable>"
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(body).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _default_gate_review(*, repo_root: Path, gate_paths: list[str], hhmm: str) -> dict:
    """File (idempotently) the review task that owns a deferred gate change.

    PHASE-Z deliberately does not commit changes to the very files that gate it
    (a commit N that weakens the gate would be judged by that weakened gate at
    commit N+1). Before 2026-07-20 that check rolled back the *whole* batch and
    left no exit: every fire retried, failed, alerted, and the workspace stayed
    stuck forever (assign_010d1a2d). Now the gate paths are simply held back —
    everything else commits — and this task is the forward path for them.
    """
    from volpred.ops.next_tasks import append_task_record

    fp = _gate_review_fingerprint(repo_root, gate_paths)
    task_id = f"phase_z_gate_review_{fp}"
    listing = "\n".join(f"- `{p}`" for p in gate_paths)
    record = {
        "id": task_id,
        "title": f"[gate review] PHASE-Z 保留了 {len(gate_paths)} 個 trusted-gate 檔案變更，待審查後提交",
        "description": "\n".join([
            f"PHASE-Z（fire {hhmm}）已把這班其餘變更正常提交，但**保留**下列 trusted-gate 路徑不提交：",
            "",
            listing,
            "",
            "## 為什麼保留",
            "這些檔案就是 PHASE-Z 用來審判 commit 的 gate 本身。若讓它們自動落地，"
            "下一班就會被『這班剛改過的 gate』審判 —— commit N 弱化 gate、commit N+1 被弱化的 gate 放行。"
            "candidate worktree 用 pinned base_sha 執行 hook，擋得住同一批的自我審判，擋不住這條跨 commit 的時序威脅。",
            "",
            "## 下一步（擇一，做完這張單就結案）",
            "1. 看 diff，確認變更沒有弱化檢查強度：",
            "",
            "```",
            "git diff -- " + " ".join(gate_paths),
            "```",
            "",
            "2. 認可 → 由審查者自行提交（PHASE-Z 不會代勞）：",
            "",
            "```",
            "git add " + " ".join(gate_paths),
            "git commit -m 'chore(gate): <說明這次 gate 變更做了什麼>'",
            "```",
            "",
            "3. 不認可 → 還原：",
            "",
            "```",
            "git checkout -- " + " ".join(gate_paths),
            "```",
            "",
            "檔案留在工作區、沒有遺失；在本單結案前，每班 PHASE-Z 都會照常提交其餘變更。",
        ]),
        "task_type": "platform_ops",
        "priority": 2,
        "status": "pending",
        "source": "phase_z_gate_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate_paths": list(gate_paths),
    }
    try:
        _, created = append_task_record(record, path=str(repo_root / "storage" / "next_tasks.json"))
    except Exception as exc:  # queue unwritable must not wedge the commit itself
        LOG.warning("phase_z: cannot file gate-review task (%s)", exc)
        return {"task_id": task_id, "created": False, "error": str(exc)}
    return {"task_id": task_id, "created": created}


def _observe_ownership_shadow(
    repo_root: Path,
    *,
    dirty_now: set[str],
    baseline: set[str] | None,
    fire_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> None:
    """Log what a DECLARED-ownership ledger would have said. Decides nothing.

    Stage 1 of docs/refactor_commit_ownership_state_machine.md. `owned = dirty_now
    - baseline` is an inference about a shared checkout, and every incident in
    error_log §B is that inference being wrong in one of three ways. The
    replacement is a write-time declaration (`volpred.ops.fire_manifest`), and
    this call measures the gap between the two answers on live fires *before*
    anything commits on the new one — a shadow, not a switch.

    Totally guarded on purpose: the commit path below must be bit-identical
    whether this succeeds, fails, or the module is missing entirely.
    """
    try:
        from volpred.ops import fire_manifest

        fire_manifest.observe_shadow(
            repo_root, dirty_now=dirty_now, baseline=baseline, fire_ids=fire_ids,
        )
    except Exception as exc:  # noqa: BLE001 — a shadow may never touch a decision
        LOG.debug("phase_z: ownership shadow skipped (%s)", exc)


def _partition_foreign_ownership(repo_root: Path, paths: list[str]) -> dict:
    """Separate somebody's live, declared work from residue that needs an exit.

    A fire-start baseline proves only that a path is not this fire's output.  It
    does *not* prove that the path is abandoned or risky.  The 2026-07-22 13:16
    receipt demonstrated the distinction: 29 paths owned by concurrent sessions
    were correctly skipped, then incorrectly presented to the owner as one WARN.

    Declared live ownership is write-time evidence, not another cleanup-layer
    recognizer.  Those paths remain visible in the PHASE-Z receipt, but they do
    not enter the foreign streak, orphan-half probe, quarantine, incident, or
    owner notification lanes.  Only unowned, stale, or contested residue does.

    Fail closed: an unreadable/missing ledger leaves every path in ``unowned``.
    That preserves the existing no-commit safety boundary and merely delays any
    notification until the persistent-incident threshold is reached.
    """
    ordered = sorted(set(paths))
    empty = {
        "active": {}, "stale": {}, "contested": {}, "unowned": ordered,
        "risk": ordered,
    }
    if not ordered:
        return empty
    try:
        from volpred.ops import fire_manifest

        ownership = fire_manifest.resolve_ownership(repo_root, ordered)
    except Exception as exc:  # noqa: BLE001 — attribution failure must not claim bytes
        LOG.warning("phase_z: declared foreign ownership unavailable (%s)", exc)
        return empty

    active = dict(ownership.get("foreign") or {})
    stale = dict(ownership.get("stale") or {})
    contested = dict(ownership.get("contested") or {})
    unowned = sorted(ownership.get("orphan") or [])
    risk = sorted(set(unowned) | set(stale) | set(contested))
    return {
        "active": {p: active[p] for p in sorted(active)},
        "stale": {p: stale[p] for p in sorted(stale)},
        "contested": {p: contested[p] for p in sorted(contested)},
        "unowned": unowned,
        "risk": risk,
    }


def recover_committed_closeout(
    *,
    repo_root: Path,
    commit_sha: str,
    generation_id: str,
    claim_owners: set[str] | list[str] | tuple[str, ...] | None = None,
    now_hhmm: str | None = None,
    runner=subprocess.run,
    test_runner=None,
    internal_alert_fn=None,
) -> dict:
    """Finish post-adoption work for a generation commit after a crash.

    Finding the generation trailer proves only that HEAD adoption happened.
    It does *not* prove the shared index refresh, task/issue receipts, or
    post-commit test gate ran.  This replay-safe finisher reruns those steps and
    returns terminal only after every required downstream handoff completes.
    """
    repo_root = Path(repo_root)
    hhmm = now_hhmm or datetime.now().strftime("%H:%M")
    internal_alert_fn = internal_alert_fn or _default_internal_alert
    shown = _git(
        repo_root,
        "show",
        "-s",
        "--format=%B",
        commit_sha,
        timeout_s=_SHORT_TIMEOUT_S,
        runner=runner,
    )
    expected_trailer = f"VolPred-Phase-Z-Generation: {generation_id}"
    commit_body = shown.stdout or ""
    if (
        shown.returncode != 0
        or not any(
            line.strip() == expected_trailer
            for line in commit_body.splitlines()
        )
    ):
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_identity_mismatch",
            "commit_sha": commit_sha,
        }
    owned_prefix = "VolPred-Phase-Z-Owned-Paths: "
    owned_lines = [
        line.strip()[len(owned_prefix):]
        for line in commit_body.splitlines()
        if line.strip().startswith(owned_prefix)
    ]
    try:
        owned_paths = json.loads(owned_lines[-1]) if len(owned_lines) == 1 else None
    except json.JSONDecodeError:
        owned_paths = None
    if (
        not isinstance(owned_paths, list)
        or any(not isinstance(path, str) for path in owned_paths)
    ):
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_owned_scope_missing",
            "commit_sha": commit_sha,
        }
    parent = _git(
        repo_root,
        "rev-parse",
        "--verify",
        f"{commit_sha}^",
        timeout_s=_SHORT_TIMEOUT_S,
        runner=runner,
    )
    changed = _git(
        repo_root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit_sha,
        timeout_s=_SHORT_TIMEOUT_S,
        runner=runner,
    )
    if parent.returncode != 0 or changed.returncode != 0:
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_git_probe_failed",
            "commit_sha": commit_sha,
        }
    base_sha = (parent.stdout or "").strip()
    candidate_paths = [
        line.strip()
        for line in (changed.stdout or "").splitlines()
        if line.strip()
    ]
    if not set(owned_paths) <= set(candidate_paths):
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_owned_scope_mismatch",
            "commit_sha": commit_sha,
        }
    try:
        with git_writer_lock(
            repo_root,
            actor=f"dispatch-phase-z-recovery:{hhmm}",
            timeout_s=_COMMIT_TIMEOUT_S,
        ):
            require_canonical_main_checkout(repo_root)
            refresh = _refresh_shared_index_cas(
                repo_root,
                base_sha=base_sha,
                committed_sha=commit_sha,
                candidate_paths=candidate_paths,
                runner=runner,
            )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("phase_z: committed closeout index recovery failed: %s", exc)
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_index_failed",
            "commit_sha": commit_sha,
            "detail": str(exc)[:300],
        }
    if not refresh.get("ok"):
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_index_failed",
            "commit_sha": commit_sha,
            "index_refresh": refresh,
        }

    _consume_pre_fire_snapshot(repo_root, runner)
    normalized_owners = {
        str(owner)
        for owner in (claim_owners or [])
        if str(owner).strip()
    }
    ci_repair_tasks_backfilled: list[str] = []
    issue_tasks_closed: list[dict[str, Any]] = []
    try:
        if normalized_owners and owned_paths:
            ci_repair_tasks_backfilled = backfill_ci_repair_commit(
                path=repo_root / "storage" / "next_tasks.json",
                claim_owners=normalized_owners,
                commit_sha=commit_sha,
            )
            linked_task_ids = pending_issue_task_ids_for_owners(
                path=repo_root / "storage" / "next_tasks.json",
                claim_owners=normalized_owners,
            )
            issue_tasks_closed = settle_completed_task_issues(
                path=repo_root / "storage" / "next_tasks.json",
                claim_owners=normalized_owners,
                commit_sha=commit_sha,
                commit_parent_sha=base_sha,
                completed_task_ids=linked_task_ids,
                repo_root=repo_root,
            )
            acknowledged_task_ids = {
                str(item.get("task_id") or "")
                for item in issue_tasks_closed
                if isinstance(item, dict)
            }
            if acknowledged_task_ids != set(linked_task_ids):
                return {
                    "committed": False,
                    "head_committed": True,
                    "reason": "committed_recovery_issue_readback_incomplete",
                    "commit_sha": commit_sha,
                    "index_refresh": refresh,
                    "missing_task_ids": sorted(
                        set(linked_task_ids) - acknowledged_task_ids
                    ),
                }
    except Exception as exc:  # noqa: BLE001
        LOG.warning("phase_z: committed closeout receipt recovery failed: %s", exc)
        return {
            "committed": False,
            "head_committed": True,
            "reason": "committed_recovery_receipt_failed",
            "commit_sha": commit_sha,
            "index_refresh": refresh,
            "detail": str(exc)[:300],
        }

    tests = _post_commit_test_gate(
        repo_root,
        commit_sha=commit_sha,
        hhmm=hhmm,
        runner=runner,
        test_runner=test_runner or subprocess.run,
        internal_alert_fn=internal_alert_fn,
    )
    return {
        "committed": True,
        "reason": "committed",
        "commit_sha": commit_sha,
        "receipt_recovered": True,
        "index_refresh": refresh,
        "tests": tests,
        "ci_repair_tasks_backfilled": ci_repair_tasks_backfilled,
        "issue_tasks_closed": issue_tasks_closed,
    }


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
    isolated_cohort: bool = False,
    gate_review_fn=None,
    claim_owners: set[str] | list[str] | tuple[str, ...] | None = None,
    fire_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    closeout_generation: str | None = None,
    _recovery_capability: object | None = None,
    _closeout_authorization: dict[str, dict[str, object]] | None = None,
) -> dict:
    """Deterministic post-fire commit. Returns an observability dict.

    ``isolated_cohort`` is retained temporarily as a scheduler-call compatibility
    field while Issue #44 removes the old cohort recognizer. It no longer changes
    ownership policy: Issue #43 established that every automated mutating lane is
    isolated-or-requeued, so *all* canonical non-machine residue is foreign to
    PHASE-Z regardless of a legacy token's flag. Machine-state adoption remains
    explicit by namespace and byte identity.

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
    gate_review_fn = gate_review_fn or _default_gate_review
    if internal_alert_fn is None:
        if supplied_alert_fn is None:
            internal_alert_fn = _default_internal_alert
        else:
            # Backward-compatible test seam: existing callers inject one three-
            # argument alert collector.  Production uses the dedicated router.
            def internal_alert_fn(
                *, alert_key: str, level: str, title: str, body: str,
                observed_at=None, fingerprint=None,
            ) -> dict:
                del alert_key, observed_at, fingerprint
                return supplied_alert_fn(level=level, title=title, body=body)
    if internal_resolve_fn is None:
        internal_resolve_fn = (
            _default_internal_resolve
            if supplied_alert_fn is None
            else lambda **_kwargs: {"resolved": False, "reason": "injected_alert_test_seam"}
        )
    # Self-heal our own crash debris before touching Git. If a previous tick was
    # SIGTERMed by the stale-code reloader (or SIGKILLed on custody loss) while
    # holding the shared-index lock, its `finally` never ran and every writer in
    # the repo is blocked until someone proves the holder is dead. That proof is
    # exactly what the owner sidecar exists for, so the next tick can do it
    # without a human deciding whether a lock looks old enough.
    reclaim_leaked_index_lock(repo_root)
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
    _observe_ownership_shadow(
        repo_root, dirty_now=dirty_now, baseline=baseline, fire_ids=fire_ids,
    )
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
    # A path becoming dirty during the fire proves only WHEN PHASE-Z first saw
    # it, not WHO wrote it. Split machine state first because its namespace has
    # an explicit owner; every canonical non-machine candidate is demoted below.
    newly_dirty = sorted(dirty_now - baseline)
    owned = [p for p in newly_dirty if not _is_machine_state(p)]
    newly_dirty_machine = [p for p in newly_dirty if _is_machine_state(p)]
    dirty_before = sorted(dirty_now & baseline)
    # ── Issue #44 retirement: timing no longer grants producer authorship ──
    # Issue #43 made every automated mutating lane isolated-or-requeued. Its
    # output lands through the workspace finalizer, so there is now *no* valid
    # worker path by which a non-machine file should appear dirty on canonical
    # main and need PHASE-Z to rescue it. The old ``dirty_now - baseline``
    # inference proved the opposite in live commit ee095d3e5: an interactive
    # session edited backup_user_claude.sh during an unrelated FOMC/K1731 fire,
    # and PHASE-Z swept that script into the dispatch commit. Demote canonical
    # non-machine residue for every cohort, including legacy/unisolated tokens;
    # such a token is itself an isolation breach, not authority to claim bytes.
    # Machine-state adoption remains on its explicit namespace + identity gate.
    # One compatibility exception drains a pre-retirement failed-closeout
    # receipt. Recovery reaches here only after recover_failed_closeout has
    # re-read the durable receipt and proved every unresolved path still matches
    # its recorded SHA/shape. That is explicit byte authority, not timing
    # inference. It cannot authorize a fresh cohort and disappears when the
    # finite legacy receipt set is drained.
    authorized_recovery = (
        recovery_mode
        and _recovery_capability is _FAILED_CLOSEOUT_RECOVERY_CAPABILITY
        and bool(_closeout_authorization)
    )
    closeout_authorization = (
        dict(_closeout_authorization or {})
        if authorized_recovery
        else {}
    )
    recovery_owned = [
        path
        for path in owned
        if path in closeout_authorization
        and _path_fingerprint(repo_root / path) == closeout_authorization[path]
    ]
    isolation_residue = [path for path in owned if path not in set(recovery_owned)]
    owned = recovery_owned
    if isolation_residue:
        LOG.info(
            "phase_z: isolation contract — leaving %d canonical non-machine "
            "path(s) for declared-ownership classification: %s",
            len(isolation_residue),
            isolation_residue[:10],
        )
    # The snapshot is consumed only on a SETTLED outcome (committed / clean /
    # nothing_owned / nothing_to_commit — the scheduler's terminal set). A failed
    # commit attempt (pre-commit gate block, add/reset error) keeps the baseline,
    # so the scheduler's bounded retry still knows what this fire owns instead of
    # degrading to ownership_unknown. "One snapshot, one fire" still holds: the
    # next fire's pre-fire guard overwrites it unconditionally.

    # Machine state has the same owner whether it became dirty before or during
    # this fire.  Classify both sets through the lock+parse gate.  Previously the
    # during-fire half bypassed this classifier as ``owned``; besides inventing
    # an agent attribution, that also skipped the corruption/live-writer checks.
    machine_candidates = sorted(
        set(newly_dirty_machine)
        | {p for p in dirty_before if _is_machine_state(p)}
    )
    foreign = sorted(
        set(p for p in dirty_before if not _is_machine_state(p))
        | set(isolation_residue)
    )
    foreign_ownership = _partition_foreign_ownership(repo_root, foreign)
    active_foreign = foreign_ownership["active"]
    risk_foreign = foreign_ownership["risk"]
    if active_foreign:
        LOG.info(
            "phase_z: %d skipped path(s) have live declared owner(s); "
            "excluded from risk/notification lanes: %s",
            len(active_foreign), list(active_foreign.items())[:10],
        )

    # Foreign dirt splits once more. Most of it really is another session's work
    # in progress. A subset can be MECHANICALLY PROVED to be the missing half of
    # a commit that already landed — a red test at HEAD that this path's bytes
    # turn green. Without this exit such a path is foreign forever and CI stays
    # red forever (see _adopt_orphan_halves for the full evidence argument).
    # Skipped during recovery for the same reason streaks are: a recovery pass
    # runs immediately before the real pre-fire snapshot, so probing here would
    # pay for the whole clone+pytest sweep twice in one tick for one answer.
    orphan_halves = (
        {"adopted": [], "reason": "recovery_mode", "considered": [], "evidence": {}}
        if authorized_recovery
        else _adopt_orphan_halves(
            repo_root,
            risk_foreign,
            runner=runner,
            test_runner=test_runner or subprocess.run,
            owner_groups=_orphan_half_owner_groups(foreign_ownership),
        )
    )
    adopted_halves = list(orphan_halves["adopted"])
    if adopted_halves:
        # Never silent: adoption reverses this file's default answer, so it says
        # which path it took and on whose evidence, every time.
        for rel in adopted_halves:
            LOG.warning(
                "phase_z: adopting orphan half %s — it turns committed test(s) %s green at HEAD",
                rel, ", ".join(orphan_halves["evidence"][rel]["turned_green"]),
            )
        foreign = [p for p in foreign if p not in set(adopted_halves)]
        risk_foreign = [p for p in risk_foreign if p not in set(adopted_halves)]
        foreign_ownership["risk"] = list(risk_foreign)
        foreign_ownership["unowned"] = [
            p for p in foreign_ownership["unowned"] if p not in set(adopted_halves)
        ]
    elif orphan_halves["reason"] not in {"no_candidates", "no_proof"}:
        LOG.info("phase_z: orphan-half probe adopted nothing (%s)", orphan_halves["reason"])

    # A recovery pass runs immediately before the real pre-fire snapshot. It
    # must not count the same unrelated dirty paths as another hourly shift.
    streaks = (
        {}
        if authorized_recovery
        else _bump_foreign_streaks(repo_root, runner, risk_foreign)
    )
    stuck = sorted((p for p, n in streaks.items() if n >= _FOREIGN_STREAK_CRITICAL),
                   key=lambda p: (-streaks[p], p))
    worst_streak = max(streaks.values(), default=0)

    quarantine: dict = {"ref": None, "created": False, "checkpointed": [],
                        "skipped": {}, "reason": "no_stuck_paths"}
    if stuck:
        LOG.warning("phase_z: %d foreign path(s) stuck for >=%d fires: %s",
                    len(stuck), _FOREIGN_STREAK_CRITICAL, stuck[:10])
        # Preservation is unconditional and needs nobody's approval; only the
        # question "does this belong in main" needs a human. Decision doc §4 D2.
        quarantine = _quarantine_stuck_foreign(
            repo_root, stuck, streaks=streaks, hhmm=hhmm, runner=runner,
        )
        LOG.info("phase_z: quarantine %s — ref=%s, %d path(s) checkpointed, %d skipped",
                 quarantine["reason"], quarantine["ref"],
                 len(quarantine["checkpointed"]), len(quarantine["skipped"]))

    # D3: the stuck set becomes ONE persistent incident in the canonical queue,
    # and that incident — not this alert — is what the scheduler reads. See
    # volpred.ops.foreign_incident for why a CRITICAL alone changed nothing.
    incident = _open_stuck_incident(repo_root, stuck, streaks=streaks,
                                    quarantine=quarantine)

    # Paging is now bounded by the incident, not by a retry curve: ONE page when
    # the incident opens, then silence while it stays open. `_streak_is_notifiable`
    # kept re-paging (3/6/12/24…) because a notification was the only mechanism
    # available; re-paging on top of a live incident would be a second reminder
    # channel for one condition, which is how both end up ignored. The escalation
    # that used to live in the retry curve now lives in the de-rated slot cap.
    # No incident means no de-rate and no owner, so silence would be strictly
    # worse than the old noise: fall back to the legacy backed-off CRITICAL.
    incident_failed = incident.get("reason") in {"error", "no_queue"}
    if incident.get("page_required", incident.get("created", False)) or (
        incident_failed and any(_streak_is_notifiable(streaks[p]) for p in stuck)
    ):
        alert_kwargs = {
            "level": "critical",
            # streak/count 會浮動，不能進 title。task id 則是 durable episode
            # identity：同 episode retry 共用 dedup key；disjoint/new generation
            # 不得被前一 episode 的 24h receipt 吞掉。
            "title": _stuck_incident_alert_title(incident),
            "body": "\n".join([
                f"（fire 時間: {hhmm}；{len(stuck)} 個檔案，最長已連續 {worst_streak} 班）",
                "",
                "## 發生什麼",
                f"這些未提交檔案沒有 live producer declaration，且已連續 {worst_streak} 班仍在工作區。"
                f"其中 unowned={len(foreign_ownership['unowned'])}、"
                f"stale={len(foreign_ownership['stale'])}、"
                f"contested={len(foreign_ownership['contested'])}；"
                "仍有 live owner 的路徑已在分類前排除，不在這張 incident 裡。",
                "",
                *([
                    "",
                    "## 這封信的 owner",
                    f"已開一張持久 incident：`{incident.get('task_id')}`"
                    f"（fingerprint `{incident.get('fingerprint')}`）。這封信不會再重發 —— "
                    "同一批檔案的後續班次只更新那張單。",
                    "**未關的代價是 scheduler 降載**：`scripts/dispatch_slot_budget.py` "
                    "看到未關 incident 就把每班 slot cap 壓下去，所以拖著不處理是有成本的。",
                    "關閉條件（機械可驗）：`uv run python -m volpred.ops.foreign_incident --check`。",
                ] if incident.get("task_id") else [
                    "",
                    "## 注意：incident 沒建起來",
                    "任務池寫入失敗，所以這次退回舊的退避通知行為（3/6/12/24… 班）。"
                    "scheduler 降載訊號這班不會生效 —— 先修任務池寫入。",
                ]),
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
                *([
                    "",
                    "## 已保存（可取回）",
                    f"這些 bytes 已 checkpoint 進不可變 ref `{quarantine['ref']}`"
                    f"（{len(quarantine['checkpointed'])} 個檔案）。工作區、index、main 都沒有被動到；"
                    "這只是保存，不是收養、不宣稱完成、也進不了 main。",
                    "取回：`git show " + str(quarantine["ref"]) + ":<路徑>`",
                ] if quarantine.get("ref") else []),
                *([
                    "",
                    "## 未保存（producer 正在寫）",
                    "以下路徑此刻被 writer 持有 flock，checkpoint 會存到寫到一半的內容，故略過：",
                    *[f"- {p}" for p, why in sorted(quarantine["skipped"].items())
                      if why == "live_writer"],
                ] if any(w == "live_writer" for w in quarantine["skipped"].values()) else []),
            ]),
        }
        alias_titles = _stuck_incident_alert_alias_titles(incident)
        if alias_titles and _alert_accepts_dedup_alias_titles(alert_fn):
            alert_kwargs["dedup_alias_titles"] = alias_titles
        alert_result = alert_fn(**alert_kwargs)
        page_token = str(incident.get("page_claim_token") or "")
        if page_token:
            delivered = bool(
                alert_result.get("sent")
                or (
                    alert_result.get("skipped")
                    and alert_result.get("skip_reason") == "dedup_24h"
                )
            ) if isinstance(alert_result, dict) else False
            try:
                settled = settle_family_page(
                    repo_root / "storage" / "next_tasks.json",
                    token=page_token,
                    delivered=delivered,
                )
            except Exception as exc:  # noqa: BLE001 — lease expiry retries safely
                settled = False
                LOG.warning(
                    "phase_z: family page settlement failed (%s); "
                    "lease expiry will retry",
                    exc,
                )
            if not settled:
                LOG.warning(
                    "phase_z: family page token %s was not settled; "
                    "lease expiry will retry",
                    page_token[:12],
                )
            elif not delivered:
                LOG.warning(
                    "phase_z: family page delivery not acknowledged; "
                    "lease released for retry"
                )

    # Classify machine state only after every PHASE-Z-owned control-plane
    # mutation above. Opening/updating a stuck-path incident writes the
    # canonical queue itself; capturing the queue identity before that write
    # made the later candidate fence reject PHASE-Z's own transaction as
    # external churn. Re-read status here so a queue that was clean at entry but
    # dirtied by the incident is included. A real writer racing after this
    # point is still caught by _verify_machine_churn_candidate before commit.
    refreshed_dirty = _dirty_paths(repo_root, runner)
    if refreshed_dirty is not None:
        machine_candidates = sorted(
            set(machine_candidates)
            | {p for p in refreshed_dirty if _is_machine_state(p)}
        )
    churn_classification = _classify_machine_churn(repo_root, machine_candidates)
    churn, churn_deferred, churn_corrupt = churn_classification

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

    if foreign:
        LOG.info("phase_z: leaving %d path(s) dirty — already dirty at fire start, not ours: %s",
                 len(foreign), foreign[:10])
    if churn:
        LOG.info("phase_z: adopting %d machine-churn path(s) — daemon-written, no session owner: %s",
                 len(churn), churn)
    if churn_deferred:
        LOG.info("phase_z: %d machine-churn path(s) busy/unreadable — next fire takes them: %s",
                 len(churn_deferred), churn_deferred)

    # ── trusted-gate split (assign_010d1a2d) ───────────────────────────────
    # A dirty gate file used to roll back the ENTIRE batch with no forward
    # path: every fire retried, failed, alerted, and the workspace stayed stuck
    # (24 innocent files held hostage by one). Two things were conflated —
    # "this batch must not be judged by its own gate" (real, and already
    # structurally impossible: the hook runs from a pinned base_sha) and "a
    # weakened gate must not judge the NEXT commit" (real, and what actually
    # needs handling). Split the batch: non-gate paths commit normally, gate
    # paths stay dirty and get a review task that says exactly which file and
    # exactly what to run. Deadlock gone, collateral gone, threat still held.
    gate_deferred = sorted(set(owned + churn + adopted_halves) & _TRUSTED_GATE_PATHS)
    gate_review: dict | None = None
    if gate_deferred:
        owned = [p for p in owned if p not in _TRUSTED_GATE_PATHS]
        churn = [p for p in churn if p not in _TRUSTED_GATE_PATHS]
        adopted_halves = [p for p in adopted_halves if p not in _TRUSTED_GATE_PATHS]
        try:
            gate_review = gate_review_fn(repo_root=repo_root, gate_paths=gate_deferred, hhmm=hhmm)
        except Exception as exc:
            LOG.warning("phase_z: gate-review hook raised (%s)", exc)
            gate_review = {"task_id": None, "created": False, "error": str(exc)}
        LOG.warning("phase_z: holding back %d trusted-gate path(s) for review (task=%s): %s",
                    len(gate_deferred), (gate_review or {}).get("task_id"), gate_deferred)
        # warn, not critical: the rest of the batch is landing normally and the
        # review task is the forward path. Only alert when the task is newly
        # filed — re-alerting every fire for an already-queued review is the
        # hourly-noise failure mode this redesign exists to kill.
        if (gate_review or {}).get("created"):
            alert_fn(
                level="warn",
                title=f"PHASE-Z 保留 {len(gate_deferred)} 個 gate 檔待審查（其餘已正常提交）",
                body="\n".join([
                    f"（fire 時間: {hhmm}）",
                    "",
                    "## 發生什麼",
                    "這班改到了 PHASE-Z 自己的 gate 檔。其餘變更**已照常提交**；下列 gate 檔保留在工作區，"
                    "等審查後由審查者提交 —— 避免這班改過的 gate 反過來審判下一班的 commit。",
                    "",
                    "## 檔案",
                    *[f"- {p}" for p in gate_deferred],
                    "",
                    "## 下一步",
                    "1. 看 diff：`git diff -- " + " ".join(gate_deferred) + "`",
                    "2. 認可就提交：`git add " + " ".join(gate_deferred) + " && git commit`",
                    "3. 不認可就還原：`git checkout -- " + " ".join(gate_deferred) + "`",
                    "",
                    f"追蹤任務: {(gate_review or {}).get('task_id')}",
                ]),
            )

    gate_extra = {"gate_deferred": gate_deferred, "gate_review": gate_review} if gate_deferred else {}

    if not owned and not churn and not adopted_halves and gate_deferred:
        # Everything this fire produced was a gate change: nothing left to
        # commit, but this is NOT "nothing_owned" — say so, so a run of these
        # is legible as one pending review rather than an idle fire.
        _consume_pre_fire_snapshot(repo_root, runner)
        return {"committed": False, "reason": "gate_deferred_only", "foreign": foreign,
                "orphan_halves": orphan_halves, "quarantine": quarantine,
                "incident": incident, "foreign_ownership": foreign_ownership, **gate_extra}

    if not owned and not churn and not adopted_halves:
        _consume_pre_fire_snapshot(repo_root, runner)  # settled: nothing of ours to commit
        LOG.info("phase_z: nothing this fire produced — %d foreign path(s) left alone", len(foreign))
        if not foreign:
            return {"committed": False, "reason": "nothing_owned", "foreign": [],
                    "orphan_halves": orphan_halves, "quarantine": quarantine,
                    "incident": incident,
                    "foreign_ownership": foreign_ownership,
                    **({"isolation_residue": isolation_residue} if isolation_residue else {})}
        if stuck:
            # the critical alert above already said everything this one would, louder.
            return {"committed": False, "reason": "nothing_owned",
                    "foreign": foreign, "stuck": stuck, "orphan_halves": orphan_halves,
                    "quarantine": quarantine,
                    "incident": incident,
                    "foreign_ownership": foreign_ownership,
                    **({"isolation_residue": isolation_residue} if isolation_residue else {})}
        return {"committed": False, "reason": "nothing_owned", "foreign": foreign,
                "orphan_halves": orphan_halves, "quarantine": quarantine,
                "incident": incident,
                "foreign_ownership": foreign_ownership,
                **({"isolation_residue": isolation_residue} if isolation_residue else {})}

    LOG.info("phase_z: auto-committing %d path(s) from this fire + %d machine-churn path(s)"
             " + %d proved orphan half/halves",
             len(owned), len(churn), len(adopted_halves))
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

            to_stage = [p for p in (owned + churn + adopted_halves) if p not in set(untracked)]

            # Defer test halves whose source half is not in this candidate; staging
            # them guarantees an audit-test-imports rejection and a rollback that
            # takes the rest of the fire's output down with it. See the split-pair
            # guard block above.
            split_deferred = _split_pair_deferrals(repo_root, to_stage, base_sha, runner=runner)
            if split_deferred:
                for test_rel, missing in sorted(split_deferred.items()):
                    LOG.warning(
                        "phase_z: deferring %s — source half not in candidate: %s",
                        test_rel, ", ".join(missing),
                    )
                to_stage = [p for p in to_stage if p not in split_deferred]

            # A classified deletion must never go back through ``git add -A``.
            # If that missing pathname reappears as a directory between the
            # classifier and staging, add would recursively ingest unverified
            # descendants (and write their blobs even when this alternate index
            # is later discarded). Remove exact index entries instead; this
            # operation never reads working-tree bytes.
            missing_churn = {
                path
                for path, identity in churn_classification.identities.items()
                if not identity.exists and path in to_stage
            }
            add_paths = [path for path in to_stage if path not in missing_churn]
            pathspec_file = tx_root / "paths.nul"
            try:
                pathspec_file.write_bytes(
                    b"\0".join(os.fsencode(path) for path in add_paths)
                )
            except OSError as exc:
                LOG.warning("phase_z: cannot write candidate pathspec (%s)", exc)
                return {"committed": False, "reason": "pathspec_error", "rolled_back": True}

            if add_paths:
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

            # A pre-retirement closeout receipt authorizes only its exact pinned
            # bytes. Recheck after staging: direct recovery_mode calls have no
            # capability, and a later writer racing the recovery cannot have its
            # new bytes committed under the rejected fire's attribution.
            closeout_identity_mismatches = _verify_closeout_candidate(
                repo_root,
                {
                    path: closeout_authorization[path]
                    for path in owned
                    if path in closeout_authorization
                },
                base_sha=base_sha,
                runner=runner,
                env=candidate_env,
            )
            if closeout_identity_mismatches:
                LOG.warning(
                    "phase_z: closeout identity changed before staging: %s",
                    closeout_identity_mismatches,
                )
                return {
                    "committed": False,
                    "reason": "closeout_identity_error",
                    "rolled_back": True,
                    "identity_mismatches": closeout_identity_mismatches,
                }

            for rel in sorted(missing_churn):
                remove = _git(
                    repo_root,
                    "update-index",
                    "--force-remove",
                    "--",
                    rel,
                    timeout_s=_SHORT_TIMEOUT_S,
                    runner=runner,
                    env=candidate_env,
                )
                if remove.returncode != 0:
                    LOG.warning(
                        "phase_z: candidate exact deletion %s rc=%d: %s",
                        rel,
                        remove.returncode,
                        (remove.stderr or "")[-300:],
                    )
                    return {
                        "committed": False,
                        "reason": "candidate_index_error",
                        "rolled_back": True,
                    }

            staged_churn_identities = {
                path: identity
                for path, identity in churn_classification.identities.items()
                if path in to_stage
            }
            churn_identity_mismatches = _verify_machine_churn_candidate(
                repo_root,
                staged_churn_identities,
                runner=runner,
                env=candidate_env,
            )
            if churn_identity_mismatches:
                LOG.warning(
                    "phase_z: machine-churn identity changed before staging: %s",
                    churn_identity_mismatches,
                )
                return {
                    "committed": False,
                    "reason": "candidate_churn_identity_error",
                    "rolled_back": True,
                    "identity_mismatches": churn_identity_mismatches,
                }

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
                timeout_s=_CANDIDATE_CHECKOUT_TIMEOUT_S, runner=runner, env=candidate_env,
            )
            if checkout.returncode != 0:
                return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
            git_dir_probe = _git(
                repo_root, "rev-parse", "--absolute-git-dir",
                timeout_s=_SHORT_TIMEOUT_S, runner=runner,
            )
            if git_dir_probe.returncode != 0:
                return {"committed": False, "reason": "candidate_gate_error", "rolled_back": True}
            hook_env = external_child_environment(
                candidate_env,
                overrides={
                    "GIT_DIR": (git_dir_probe.stdout or "").strip(),
                    "GIT_WORK_TREE": str(candidate_root),
                    "VOLPRED_NO_EMAIL": "1",
                    "VOLPRED_NO_REMOTE_WRITE": "1",
                    "VOLPRED_NO_REMOTE_READ": "1",
                    "VOLPRED_NO_CANONICAL_WRITE": "1",
                },
            )
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
            elif adopted_halves and not churn:
                subject = (
                    f"fix(ci {hhmm}): land proved missing half of an "
                    f"already-committed change"
                )
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
            if closeout_generation:
                body_lines.append("")
                body_lines.append(
                    "VolPred-Phase-Z-Generation: "
                    f"{str(closeout_generation).strip()}"
                )
                body_lines.append(
                    "VolPred-Phase-Z-Owned-Paths: "
                    + json.dumps(
                        sorted(owned),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            if adopted_halves:
                # The audit trail for reversing this file's default answer lives
                # in the commit itself, not only in a log line that rotates away.
                body_lines.append("")
                body_lines.append(
                    "Adopted orphan half/halves — dirty before this fire, but proved to be the "
                    "missing half of an already-landed commit (a test committed at HEAD was RED "
                    "and these bytes turn it GREEN in an isolated clone):"
                )
                for rel in adopted_halves:
                    turned = ", ".join(orphan_halves["evidence"][rel]["turned_green"])
                    body_lines.append(f"- {rel} — turns green: {turned}")
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
            return {
                "committed": False,
                "head_committed": True,
                "reason": "committed_recovery_index_failed",
                "commit_sha": committed_sha,
                "index_refresh": refresh,
                "owned": owned,
                "foreign": foreign,
                "churn": churn,
            }
        elif refresh.get("preserved"):
            LOG.info(
                "phase_z: preserved concurrent staged entries for %s",
                refresh["preserved"],
            )
        _consume_pre_fire_snapshot(repo_root, runner)  # settled: the fire's work landed
        LOG.info("phase_z: committed — %s", out.splitlines()[-1] if out else "(no output)")
        ci_repair_tasks_backfilled: list[str] = []
        issue_tasks_closed: list[dict[str, Any]] = []
        # A machine-churn-only commit is not evidence that any worker claim's
        # deliverable landed. After Issue #44 demotes all canonical non-machine
        # residue, backfilling/closing the fire's task from such a commit would
        # falsely settle work based on unrelated queue state.
        if claim_owners and owned:
            try:
                ci_repair_tasks_backfilled = backfill_ci_repair_commit(
                    path=repo_root / "storage" / "next_tasks.json",
                    claim_owners=claim_owners,
                    commit_sha=committed_sha,
                )
            except Exception as exc:  # noqa: BLE001 — commit already landed; receipt repair is retryable
                LOG.warning("phase_z: CI repair commit receipt backfill failed: %s", exc)
                return {
                    "committed": False,
                    "head_committed": True,
                    "reason": "committed_recovery_receipt_failed",
                    "commit_sha": committed_sha,
                    "index_refresh": refresh,
                    "detail": str(exc)[:300],
                }
            try:
                linked_task_ids = pending_issue_task_ids_for_owners(
                    path=repo_root / "storage" / "next_tasks.json",
                    claim_owners=claim_owners,
                )
                issue_tasks_closed = settle_completed_task_issues(
                    path=repo_root / "storage" / "next_tasks.json",
                    claim_owners=claim_owners,
                    commit_sha=committed_sha,
                    commit_parent_sha=base_sha,
                    completed_task_ids=linked_task_ids,
                    repo_root=repo_root,
                )
                acknowledged_task_ids = {
                    str(item.get("task_id") or "")
                    for item in issue_tasks_closed
                    if isinstance(item, dict)
                }
                if acknowledged_task_ids != set(linked_task_ids):
                    return {
                        "committed": False,
                        "head_committed": True,
                        "reason": (
                            "committed_recovery_issue_readback_incomplete"
                        ),
                        "commit_sha": committed_sha,
                        "index_refresh": refresh,
                        "missing_task_ids": sorted(
                            set(linked_task_ids) - acknowledged_task_ids
                        ),
                    }
            except Exception as exc:  # noqa: BLE001 — commit already landed; GitHub sync is retryable
                LOG.warning(
                    "phase_z: linked issue post-commit settlement failed: %s",
                    exc,
                )
                return {
                    "committed": False,
                    "head_committed": True,
                    "reason": "committed_recovery_receipt_failed",
                    "commit_sha": committed_sha,
                    "index_refresh": refresh,
                    "detail": str(exc)[:300],
                }
        tests = _post_commit_test_gate(
            repo_root, commit_sha=committed_sha, hhmm=hhmm, runner=runner,
            test_runner=test_runner or subprocess.run,
            internal_alert_fn=internal_alert_fn,
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
        return {"committed": True, "reason": "committed", "untracked": untracked,
                "commit_sha": committed_sha,
                "owned": owned, "foreign": foreign, "churn": churn,
                "commit_head": out[-500:], "tests": tests, "index_refresh": refresh,
                "orphan_halves": orphan_halves, "quarantine": quarantine,
                "incident": incident,
                "foreign_ownership": foreign_ownership,
                "ci_repair_tasks_backfilled": ci_repair_tasks_backfilled,
                "issue_tasks_closed": issue_tasks_closed,
                **({"isolation_residue": isolation_residue} if isolation_residue else {}),
                **gate_extra}
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
            "owned": owned, "commit_tail": out[-600:], "rolled_back": True,
            "quarantine": quarantine,
            "incident": incident}
