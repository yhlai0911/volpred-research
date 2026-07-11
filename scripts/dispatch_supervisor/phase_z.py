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

Semantics (legacy, minus the `git add -A` that made it steal — see the ownership
block below and docs/error_log.md 2026-07-10):

  1. `git status --porcelain -z -uall` — empty → clean → no-op.
  2. no fire-start baseline → ownership unknown → commit NOTHING, alert. The work
     stays in the working tree; nobody's history gets rewritten.
  3. dirty → first untrack any *already-tracked-but-gitignored* flat runtime
     state file (`git ls-files -ci --exclude-standard` — the ONLY ls-files
     combination that lists tracked-but-ignored paths; `git check-ignore`
     reports already-tracked paths as NOT ignored by design). This prevents
     the 2026-07-01 incident where a re-tracked `storage/.release_settings.json`
     let a PHASE-Z commit silently revert the boss's cadence directive.
  4. unstage anything ANOTHER writer had staged (`git reset -- <foreign>`; the
     working tree is untouched, only their staging is), then
     `git add -A --pathspec-from-file` with only the paths this fire produced.
  5. `git commit -m "ops(dispatch-supervisor HH:MM): PHASE-Z safety-net auto-commit (agent left uncommitted)"`.

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
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

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
# pytest exit 5 = "no tests collected" — a keyword `-k` that matched nothing, NOT
# a failure. Classified as no_tests (observable), never as red.
_PYTEST_NO_TESTS_COLLECTED = 5

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
_MACHINE_CHURN_PATHS = ("storage/next_tasks.json",)


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

    Adopting a daemon-written file is only safe when nobody is mid-write. Two gates:

    1. the writers' own lock (``fcntl`` ``LOCK_EX`` across every read-modify-write of
       next_tasks.json — see scripts/task_pool_claim.py:87). If a shared lock cannot
       be taken without blocking, a writer holds it right now → defer to the next
       fire. This is the guard incident #1 lacked.
    2. the content parses. A canonical control file that does not parse is a real
       problem worth escalating, but committing it is how a truncated queue became
       "valid history" once already.

    Only ``.json`` candidates are parse-checked; a future non-JSON churn path still
    gets the lock gate.
    """
    committable: list[str] = []
    deferred: list[str] = []
    corrupt: list[str] = []
    for rel in candidates:
        try:
            with open(repo_root / rel, "r", encoding="utf-8") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError:
                    LOG.info("phase_z: %s is locked by a writer right now — leaving it "
                             "for the next fire", rel)
                    deferred.append(rel)
                    continue
                try:
                    if rel.endswith(".json"):
                        json.load(fh)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    LOG.warning("phase_z: %s does not parse (%s) — refusing to commit it", rel, exc)
                    corrupt.append(rel)
                    continue
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            LOG.warning("phase_z: cannot read machine-churn path %s (%s) — leaving it dirty", rel, exc)
            deferred.append(rel)
            continue
        committable.append(rel)
    return committable, deferred, corrupt


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


def _stem_present_in_tests(tests_dir: Path, stem: str) -> bool:
    """Does `stem` appear in any tests/*.py filename or body? Decides whether a
    `-k <stem>` fallback would collect anything (→ run it) or the changed module
    simply has no coverage (→ record as unmapped, do NOT pretend it passed)."""
    for path in sorted(tests_dir.glob("*.py")):
        if stem in path.name:
            return True
        try:
            if stem in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError as exc:
            LOG.warning("phase_z: could not scan %s for stem %r (%s)", path, stem, exc)
            continue
    return False


def _resolve_test_targets(repo_root: Path, code_files: list[str]) -> dict:
    """Map committed code files → a pytest run plan.

    Per changed `<tree>/…/<stem>.py`:
      - precise: `tests/test_<stem>*.py` exists → run those files by path.
      - keyword fallback: no precise file but `<stem>` appears in the tests tree
        → `pytest -k <stem>` over `tests/`.
      - unmapped: `<stem>` appears nowhere → recorded, never counted as passed.

    Run-plan invariant: a `-k` expression is only ever paired with the `tests/`
    directory, never with explicit file paths — `-k` filters whatever positional
    targets pytest collects, so mixing precise files with `-k` would silently drop
    the precise files whose node-ids don't contain the keyword. When any keyword
    fallback is in play we therefore run the whole `tests/` tree filtered by every
    involved stem (precise stems included, so their tests still run)."""
    tests_dir = repo_root / "tests"
    precise_files: set[str] = set()
    precise_stems: set[str] = set()
    keyword_stems: set[str] = set()
    unmapped: list[str] = []
    for changed in code_files:
        stem = Path(changed).stem
        if stem.startswith("__"):
            # __init__.py / dunder modules have no meaningful test-file stem.
            continue
        matches = sorted(tests_dir.glob(f"test_{stem}*.py"))
        if matches:
            precise_stems.add(stem)
            precise_files.update(str(m.relative_to(repo_root)) for m in matches)
        elif _stem_present_in_tests(tests_dir, stem):
            keyword_stems.add(stem)
        else:
            unmapped.append(changed)

    if keyword_stems:
        targets = ["tests"]
        k_expr = " or ".join(sorted(precise_stems | keyword_stems))
    else:
        targets = sorted(precise_files)
        k_expr = None
    return {"targets": targets, "k_expr": k_expr, "unmapped": unmapped}


def _post_commit_test_gate(
    repo_root: Path,
    *,
    hhmm: str,
    runner,
    test_runner,
    alert_fn,
) -> dict:
    """Run the tests a just-landed PHASE-Z commit put at risk (`docs/error_log.md`
    dab3baa12: safety-net commits bypass the normal test gate). Returns an
    observability dict; ``passed`` is True (green), False (red — alert sent, NO
    auto-revert), or None (skipped / no mapping / gate could not run). Never
    raises — the caller already committed; a gate hiccup must not undo that."""
    try:
        shown = _git(
            repo_root, "show", "--name-only", "--pretty=format:", "HEAD",
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

    plan = _resolve_test_targets(repo_root, code_files)
    targets, k_expr, unmapped = plan["targets"], plan["k_expr"], plan["unmapped"]
    if not targets:
        LOG.warning("phase_z: test-gate found NO tests for committed code %s — not treating as pass", code_files)
        return {
            "passed": None, "reason": "no_mapped_tests",
            "changed_code_files": code_files, "unmapped": unmapped,
        }

    argv = ["uv", "run", "--extra", "dev", "python", "-m", "pytest", *targets, "-q"]
    if k_expr:
        argv += ["-k", k_expr]
    LOG.info("phase_z: test-gate running %s", " ".join(argv))
    try:
        proc = test_runner(
            argv, capture_output=True, text=True,
            timeout=_TEST_GATE_TIMEOUT_S, cwd=str(repo_root), check=False,
        )
    except subprocess.TimeoutExpired:
        LOG.warning("phase_z: test-gate timed out after %ss — cannot verify commit", _TEST_GATE_TIMEOUT_S)
        return {"passed": None, "reason": "timeout", "ran": targets,
                "k_expr": k_expr, "changed_code_files": code_files, "unmapped": unmapped}
    except OSError as exc:
        LOG.warning("phase_z: test-gate runner spawn failed (%s) — cannot verify commit", exc)
        return {"passed": None, "reason": "runner_error", "ran": targets,
                "k_expr": k_expr, "changed_code_files": code_files, "unmapped": unmapped}

    rc = proc.returncode
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    base = {"ran": targets, "k_expr": k_expr, "returncode": rc,
            "changed_code_files": code_files, "unmapped": unmapped}
    if rc == 0:
        LOG.info("phase_z: test-gate green — %s", out.splitlines()[-1] if out else "(no output)")
        return {"passed": True, "reason": "green", **base}
    if rc == _PYTEST_NO_TESTS_COLLECTED:
        LOG.warning("phase_z: test-gate collected no tests (pytest exit 5) for %s — not a pass", targets)
        return {"passed": None, "reason": "no_tests_collected", **base}

    tail = out[-800:]
    LOG.warning("phase_z: test-gate RED rc=%d for %s", rc, targets)
    short_sha = ""
    try:
        rev = _git(repo_root, "rev-parse", "--short", "HEAD", timeout_s=_SHORT_TIMEOUT_S, runner=runner)
        if rev.returncode == 0:
            short_sha = (rev.stdout or "").strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: test-gate could not resolve commit sha (%s)", exc)

    title = f"PHASE-Z auto-commit 測試紅燈 {hhmm}（{short_sha or 'HEAD'}）"
    body = "\n".join([
        "## 觸發條件",
        "safety-net 自動 commit 直接進 main，補跑受影響測試後亮紅燈。",
        f"- commit: {short_sha or 'HEAD'}",
        f"- 變更程式檔: {', '.join(code_files)}",
        f"- 跑的測試: {' '.join(targets)}" + (f" -k \"{k_expr}\"" if k_expr else ""),
        f"- pytest 退出碼: {rc}",
        "",
        "## 影響",
        "PHASE-Z 不經正常測試閘門就把 agent 未提交的變更送進 main（error_log dab3baa12：",
        "一次紅燈在 main 上紅了 5 天沒人發現）。紅燈代表 main 現在有壞掉的 runtime。",
        "",
        "## 建議行動",
        "1. 本機重跑確認：",
        f"   uv run --extra dev python -m pytest {' '.join(targets)} -q"
        + (f" -k \"{k_expr}\"" if k_expr else ""),
        "2. 修掉紅燈或 revert 該 commit（gate 不自動 revert — revert 風險高於紅燈本身）。",
        "3. 失敗尾段：",
        "",
        "```",
        tail or "(no output captured)",
        "```",
    ])
    alert_result = alert_fn(level="critical", title=title, body=body)
    return {"passed": False, "reason": "red", "failing_tail": tail,
            "alert": alert_result, **base}


def run_phase_z(
    *,
    repo_root: Path,
    now_hhmm: str | None = None,
    runner=subprocess.run,
    test_runner=None,
    alert_fn=None,
    pre_fire_dirty: set[str] | list[str] | None = None,
) -> dict:
    """Deterministic post-fire commit. Returns an observability dict.

    Returns keys: ``committed`` (bool), ``reason`` (str), and — when it acted —
    ``untracked`` (list of leaked-ignored paths removed from the index),
    ``commit_head`` (stdout tail of `git commit`), and ``tests`` (the post-commit
    test-gate outcome, see below). Never raises: a git hiccup must not crash the
    supervisor tick, but it is always logged (no silent fallback per
    .claude/rules/no-silent-fallback.md).

    Post-commit test gate (this module is the enforcement owner — whoever created
    the untested commit verifies it, no separate watchdog per anti-stacking):
    after a successful commit, the files it touched under ``src/volpred/`` /
    ``scripts/`` / ``tests/`` are mapped to a pytest subset and run (bounded by
    ``_TEST_GATE_TIMEOUT_S``). Red → ``tests.passed=False`` + a critical alert,
    but NO auto-revert (revert risk > a red main). The ``tests`` dict is absent on
    the non-committing paths (clean / error) — nothing landed to verify.

    ``test_runner`` / ``alert_fn`` are injectable (same style as ``runner``) so the
    gate's own tests fake the pytest run instead of recursively spawning pytest.
    """
    repo_root = Path(repo_root)
    hhmm = now_hhmm or datetime.now().strftime("%H:%M")
    alert_fn = alert_fn or _default_alert

    dirty_now = _dirty_paths(repo_root, runner)
    if dirty_now is None:
        # e.g. not a git repository / index lock. Do NOT misreport as "clean" —
        # that would silently skip a real safety-net on a dirty tree.
        _consume_pre_fire_snapshot(repo_root, runner)
        return {"committed": False, "reason": "status_error"}

    if not dirty_now:
        LOG.info("phase_z: working tree clean — agent committed everything")
        _consume_pre_fire_snapshot(repo_root, runner)
        _bump_foreign_streaks(repo_root, runner, [])  # nothing foreign left → streaks die here
        return {"committed": False, "reason": "clean"}

    baseline = set(pre_fire_dirty) if pre_fire_dirty is not None else _read_pre_fire_snapshot(repo_root, runner)
    if baseline is None:
        # Ownership unknown. The old code committed anyway (`git add -A`), which
        # is how it swept an interactive session's half-finished edits into an
        # agent's commit. Declining leaves the work dirty and visible; committing
        # rewrites someone else's history under someone else's name.
        LOG.warning("phase_z: no fire-start baseline — declining to commit %d dirty path(s)",
                    len(dirty_now))
        alert_fn(
            level="warn",
            title=f"PHASE-Z 沒有 fire 起始基線 {hhmm} — 這班不自動 commit",
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
                f"- 未提交檔案數: {len(dirty_now)}",
                f"- 基線檔: <git-dir>/{_SNAPSHOT_BASENAME}（缺失或過期）",
            ]),
        )
        return {"committed": False, "reason": "ownership_unknown", "dirty": len(dirty_now)}

    owned = sorted(dirty_now - baseline)
    dirty_before = sorted(dirty_now & baseline)
    _consume_pre_fire_snapshot(repo_root, runner)

    # Dirty-at-fire-start splits two ways, not one. A daemon-written churn path has
    # an owner (this module); only the rest is "another session is still typing it".
    churn, churn_deferred, churn_corrupt = _classify_machine_churn(
        repo_root, [p for p in dirty_before if p in _MACHINE_CHURN_PATHS])
    foreign = [p for p in dirty_before if p not in _MACHINE_CHURN_PATHS]

    if churn_corrupt:
        alert_fn(
            level="critical",
            title=f"PHASE-Z {hhmm}: 控制檔內容壞掉，拒絕提交 — {', '.join(churn_corrupt)}",
            body="\n".join([
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

    streaks = _bump_foreign_streaks(repo_root, runner, foreign)
    stuck = sorted((p for p, n in streaks.items() if n >= _FOREIGN_STREAK_CRITICAL),
                   key=lambda p: (-streaks[p], p))
    worst_streak = max(streaks.values(), default=0)

    if stuck:
        LOG.warning("phase_z: %d foreign path(s) stuck for >=%d fires: %s",
                    len(stuck), _FOREIGN_STREAK_CRITICAL, stuck[:10])
        alert_fn(
            level="critical",
            title=f"PHASE-Z {hhmm}: {len(stuck)} 個檔案已連續 {worst_streak} 班沒人收 — 遺留變成堆積",
            body="\n".join([
                "## 發生什麼",
                f"這些未提交的檔案不是任何一班 fire 產出的，而且已經連續 {worst_streak} 班都還在工作區。"
                "單次遺留代表某個 session 正在寫；連續多班還在，代表沒有人會回來收 —— "
                "它們會一直卡在工作區，讓每一班的「誰擁有這個檔案」判斷越來越不可靠。",
                "",
                "## 現在該做什麼",
                "人工判斷後二選一：確認內容正確就 `git add <檔案> && git commit`；"
                "是廢棄的半成品就 `git checkout HEAD -- <檔案>` 丟掉。"
                "（PHASE-Z 不自動收養 —— 自動收養正是先前三次事故的成因。）",
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
        LOG.info("phase_z: nothing this fire produced — %d foreign path(s) left alone", len(foreign))
        if not foreign:
            return {"committed": False, "reason": "nothing_owned", "foreign": []}
        if stuck:
            # the critical alert above already said everything this one would, louder.
            return {"committed": False, "reason": "nothing_owned",
                    "foreign": foreign, "stuck": stuck}
        alert_fn(
            level="warn",
            title=f"PHASE-Z {hhmm}: {len(foreign)} 個檔案未提交，但不是這班產出的",
            body="\n".join([
                "## 發生什麼",
                "這班 fire 沒有留下任何自己的未提交變更，但工作區裡有別人的未提交檔案"
                "（fire 開始前就髒了）。PHASE-Z 不碰它們。",
                "",
                "## 現在該做什麼",
                "若這些是某個已結束 session 的遺留，請人工判斷後 commit 或捨棄；"
                "自動收養正是先前三次事故的成因。",
                "",
                "## 檔案",
                *[f"- {p}" for p in foreign[:30]],
                *(["- …"] if len(foreign) > 30 else []),
            ]),
        )
        return {"committed": False, "reason": "nothing_owned", "foreign": foreign}

    LOG.info("phase_z: auto-committing %d path(s) from this fire + %d machine-churn path(s)",
             len(owned), len(churn))
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

    # The commit itself stays index-based: the `git rm --cached` above only exists
    # in the index, and a pathspec commit would bypass it and leave the leaked
    # state files tracked. So the index must be made to contain exactly this
    # fire's work — which means first evicting anything ANOTHER writer staged.
    # `git reset -- <paths>` restores those index entries to HEAD and never
    # touches the working tree: their content survives, only the staging does not.
    if foreign:
        try:
            reset = _git(repo_root, "reset", "-q", "--", *foreign,
                         timeout_s=_SHORT_TIMEOUT_S, runner=runner)
        except (subprocess.TimeoutExpired, OSError) as exc:
            LOG.warning("phase_z: cannot unstage foreign paths (%s) — declining to commit", exc)
            return {"committed": False, "reason": "unstage_error", "untracked": untracked}
        if reset.returncode != 0:
            # Cannot prove the index is free of another writer's staged work.
            # Commit anyway and we are back to the bug this whole path exists for.
            LOG.warning("phase_z: git reset rc=%d: %s — declining to commit (theft risk)",
                        reset.returncode, (reset.stderr or "").strip()[:200])
            return {"committed": False, "reason": "unstage_error", "untracked": untracked}

    # A path we just `git rm --cached` is now untracked AND gitignored. The old
    # bare `git add -A` skipped ignored paths silently; naming one in a pathspec
    # makes git refuse the whole call ("paths are ignored by one of your
    # .gitignore files"), which would abort the fire's safety-net. Drop them: the
    # untracking is already staged and the commit below carries it.
    to_stage = [p for p in (owned + churn) if p not in set(untracked)]

    pathspec_file = ""
    if to_stage:
        # `--pathspec-from-file` (NUL) rather than argv: paths with spaces stay
        # intact and a fire that touched hundreds of files cannot hit ARG_MAX.
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".pathspec",
                                             delete=False) as fh:
                fh.write("\0".join(to_stage))
                pathspec_file = fh.name
        except OSError as exc:
            LOG.warning("phase_z: cannot write pathspec file (%s)", exc)
            return {"committed": False, "reason": "pathspec_error", "untracked": untracked}

    try:
        if to_stage:
            add = _git(repo_root, "add", "-A", f"--pathspec-from-file={pathspec_file}",
                       "--pathspec-file-nul", timeout_s=_SHORT_TIMEOUT_S, runner=runner)
            if add.returncode != 0:
                # Codex review #3: a failed `git add` means the index is in an
                # unknown/partial state — committing now could snapshot a partial
                # tree. Abort this fire's safety-net (observable, no commit).
                LOG.warning("phase_z: git add rc=%d: %s — aborting commit (partial-index risk)",
                            add.returncode, (add.stderr or "").strip()[:200])
                return {"committed": False, "reason": "add_error", "untracked": untracked}
        subject = (
            f"ops(dispatch-supervisor {hhmm}): PHASE-Z safety-net auto-commit (agent left uncommitted)"
            if owned else
            f"ops(dispatch-supervisor {hhmm}): PHASE-Z state churn (no agent output this fire)"
        )
        commit = _git(
            repo_root, "commit",
            "-m", subject,
            "-m", (f"Staged what this fire produced: {len(owned)} path(s), plus "
                   f"{len(churn)} daemon-written machine-churn path(s) this module owns.\n"
                   f"Left alone (dirty before the fire, another writer's): {len(foreign)} path(s)."),
            timeout_s=_COMMIT_TIMEOUT_S, runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("phase_z: git add/commit failed (%s)", exc)
        return {"committed": False, "reason": "commit_error", "untracked": untracked}
    finally:
        if pathspec_file:
            try:
                os.unlink(pathspec_file)
            except OSError:  # pragma: no cover
                pass  # silent-ok: best-effort cleanup of our own temp pathspec file

    out = ((commit.stdout or "") + (commit.stderr or "")).strip()
    if commit.returncode == 0:
        LOG.info("phase_z: committed — %s", out.splitlines()[-1] if out else "(no output)")
        tests = _post_commit_test_gate(
            repo_root, hhmm=hhmm, runner=runner,
            test_runner=test_runner or subprocess.run,
            alert_fn=alert_fn or _default_alert,
        )
        if foreign:
            alert_fn(
                level="warn",
                title=f"PHASE-Z {hhmm}: 有 {len(foreign)} 個檔案不是這班產出的，已略過",
                body="\n".join([
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
                "commit_head": out[-500:], "tests": tests}
    # Non-zero commit: distinguish the benign "nothing to commit" (everything
    # dirty was a leaked-ignored file already rm --cached'd, or a race cleaned
    # it) from a genuine commit failure.
    if "nothing to commit" in out.lower():
        LOG.info("phase_z: nothing to commit after staging (benign)")
        return {"committed": False, "reason": "nothing_to_commit", "untracked": untracked}
    LOG.warning("phase_z: git commit rc=%d: %s", commit.returncode, out[:300])
    return {"committed": False, "reason": "commit_nonzero", "untracked": untracked}
