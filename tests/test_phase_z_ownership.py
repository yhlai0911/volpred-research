"""PHASE-Z must commit what the fire produced — and nothing else.

`git add -A` has no notion of authorship. Three incidents came out of that one
assumption (docs/error_log.md 2026-07-10): a truncated `next_tasks.json`
committed as history, a rewrite smuggled past the test gate, and an interactive
session's half-finished `merge_worktree.sh` swept into an unrelated agent's
commit. The fix is a fire-start baseline: dirty now minus dirty then.

These tests drive real git in a temp repo (same style as
tests/test_phase_z_test_gate.py) because the bug lives in git's staging
semantics, not in Python. A fake `git` would have happily agreed with the bug.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z

def _snapshot(root: Path) -> Path:
    """Where PHASE-Z parks its fire-start baseline: inside the git dir, so no
    `.gitignore` rule is load-bearing and nobody can ever commit it."""
    return root / ".git" / phase_z._SNAPSHOT_BASENAME


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@volpred.local")
    _git(root, "config", "user.name", "phase-z-ownership-test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")


def _write(root: Path, rel: str, text: str) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _head_files(root: Path) -> set[str]:
    out = _git(root, "show", "--pretty=", "--name-only", "HEAD").stdout
    return {line for line in out.splitlines() if line}


def _dirty(root: Path) -> set[str]:
    return phase_z._porcelain_paths(
        subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        ).stdout
    )


def _no_tests(*_a, **_k):
    """Neutralise the post-commit test gate — it is covered by its own suite and
    would otherwise spawn pytest recursively."""
    return subprocess.CompletedProcess(args=[], returncode=5, stdout="", stderr="")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def _fire(repo: Path, alerts: list | None = None, **kw) -> dict:
    def _alert(*, level, title, body):
        if alerts is not None:
            alerts.append((level, title))
        return {"sent": True}

    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="03:00", test_runner=_no_tests, alert_fn=_alert, **kw
    )


# ── the incident ─────────────────────────────────────────────────────────────

def test_another_writers_edit_is_not_committed(repo: Path) -> None:
    """The 2026-07-10 incident, reduced: someone is mid-edit when the fire runs."""
    _write(repo, "scripts/merge_worktree.sh", "half-finished edit\n")  # theirs, dirty BEFORE
    phase_z.run_pre_fire_guard(repo_root=repo)

    _write(repo, "experiments/k1/k1.py", "agent output\n")  # ours, during the fire
    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"experiments/k1/k1.py"}
    assert "scripts/merge_worktree.sh" in _dirty(repo), "their edit must survive uncommitted"
    assert outcome["foreign"] == ["scripts/merge_worktree.sh"]


def test_foreign_path_staged_by_another_writer_is_unstaged_not_committed(repo: Path) -> None:
    """Scoping only `git add` is not enough: a plain `git commit` writes the whole
    index, so a file the other writer had already `git add`ed would still land."""
    _write(repo, "theirs.txt", "staged by someone else\n")
    _git(repo, "add", "theirs.txt")  # in the index, before the fire
    phase_z.run_pre_fire_guard(repo_root=repo)

    _write(repo, "ours.txt", "agent output\n")
    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"ours.txt"}
    assert (repo / "theirs.txt").read_text(encoding="utf-8") == "staged by someone else\n"


def test_nothing_owned_commits_nothing_and_alerts(repo: Path) -> None:
    _write(repo, "theirs.txt", "mid-edit\n")
    phase_z.run_pre_fire_guard(repo_root=repo)

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    outcome = _fire(repo, alerts=alerts)

    assert outcome["reason"] == "nothing_owned"
    assert outcome["committed"] is False
    assert _git(repo, "rev-parse", "HEAD").stdout == before, "no commit may be created"
    assert alerts and alerts[0][0] == "warn"


def test_foreign_path_stuck_across_fires_escalates_to_critical(repo: Path) -> None:
    """One fire's leftover is a session mid-edit; the same path still foreign three
    fires later is a leak nobody is coming back for — an hourly `warn` reads as
    noise (owner directive, 2026-07-11)."""
    _write(repo, "theirs.txt", "abandoned by a dead session\n")

    levels: list[str] = []
    for _ in range(phase_z._FOREIGN_STREAK_CRITICAL):
        alerts: list = []
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = _fire(repo, alerts=alerts)
        assert outcome["committed"] is False
        levels.append(alerts[0][0])

    assert levels[:-1] == ["warn"] * (phase_z._FOREIGN_STREAK_CRITICAL - 1)
    assert levels[-1] == "critical", "persistence across fires must escalate"
    assert outcome["stuck"] == ["theirs.txt"]
    assert "theirs.txt" in _dirty(repo), "escalating must not mean auto-adopting"


def test_foreign_streak_resets_once_the_path_is_cleaned_up(repo: Path) -> None:
    """A cleared path must not carry its old streak into a future, unrelated leftover."""
    _write(repo, "theirs.txt", "mid-edit\n")
    for _ in range(2):
        phase_z.run_pre_fire_guard(repo_root=repo)
        _fire(repo)

    (repo / "theirs.txt").unlink()  # a human cleaned it up between fires
    phase_z.run_pre_fire_guard(repo_root=repo)
    _fire(repo)

    _write(repo, "theirs.txt", "a different session, later\n")
    alerts: list = []
    phase_z.run_pre_fire_guard(repo_root=repo)
    _fire(repo, alerts=alerts)
    assert alerts[0][0] == "warn", "the streak must start over, not resume at 3"


# ── the fire's own work still lands ──────────────────────────────────────────

def test_agent_work_is_committed_when_tree_was_clean(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "experiments/k2/k2.py", "x\n")
    _write(repo, "docs/note.md", "y\n")

    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"experiments/k2/k2.py", "docs/note.md"}
    assert outcome["foreign"] == []


def test_agent_deletion_is_committed(repo: Path) -> None:
    """`git add -A -- <path>` stages the removal; a naive `git add <path>` does not."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    (repo / "seed.txt").unlink()

    outcome = _fire(repo)

    assert outcome["committed"] is True
    still_in_head = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "HEAD:seed.txt"], capture_output=True,
    ).returncode == 0
    assert not still_in_head, "deletion must be recorded, not just left in the worktree"


def test_path_with_spaces_survives(repo: Path) -> None:
    """Argv-joined pathspecs and `core.quotePath` both mangle these; NUL does not."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "storage/drafts/a draft with spaces.md", "z\n")

    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"storage/drafts/a draft with spaces.md"}


def test_clean_tree_is_a_noop(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    assert _fire(repo)["reason"] == "clean"


# ── ownership unknown → decline, never guess ─────────────────────────────────

def test_missing_baseline_declines_to_commit(repo: Path) -> None:
    """No pre-fire guard ran. The old code would `git add -A` here — that is the bug."""
    _write(repo, "someones_work.txt", "who wrote this?\n")

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    outcome = _fire(repo, alerts=alerts)

    assert outcome["reason"] == "ownership_unknown"
    assert _git(repo, "rev-parse", "HEAD").stdout == before
    assert "someones_work.txt" in _dirty(repo)
    assert alerts and alerts[0][0] == "warn"


def test_stale_baseline_is_refused(repo: Path) -> None:
    """A daemon killed mid-fire leaves yesterday's baseline behind. Judging today's
    dirt against it would call another writer's files 'ours'."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    snap = _snapshot(repo)
    payload = json.loads(snap.read_text(encoding="utf-8"))
    payload["taken_at"] -= phase_z._SNAPSHOT_MAX_AGE_S + 60
    snap.write_text(json.dumps(payload), encoding="utf-8")

    _write(repo, "x.txt", "x\n")
    assert _fire(repo)["reason"] == "ownership_unknown"


def test_snapshot_is_consumed_so_the_next_fire_rebaselines(repo: Path) -> None:
    """One snapshot, one fire. A leftover baseline would let the next fire judge
    its output against a window taken before someone else started typing."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "a.txt", "a\n")
    _fire(repo)
    assert not _snapshot(repo).exists()


def test_guard_baselines_even_when_guard_script_is_absent(repo: Path) -> None:
    """The baseline must not be collateral damage of a missing guard script —
    losing it costs PHASE-Z its ability to commit at all."""
    _write(repo, "pre.txt", "dirty before\n")
    outcome = phase_z.run_pre_fire_guard(repo_root=repo)

    assert outcome["reason"] == "guard_missing"
    assert outcome["dirty_at_fire_start"] == 1
    assert _snapshot(repo).exists()


# ── porcelain parsing ────────────────────────────────────────────────────────

def test_porcelain_parses_renames_and_spaces() -> None:
    raw = "R  new name.txt\0old name.txt\0 M src/a.py\0?? untracked file.md\0"
    assert phase_z._porcelain_paths(raw) == {
        "new name.txt", "old name.txt", "src/a.py", "untracked file.md",
    }


def test_dirty_probe_distinguishes_clean_from_unknown(tmp_path: Path) -> None:
    """`None` (git failed) and `set()` (clean) must never collapse: the old code
    read an empty stdout on a failed `git status` as 'clean' and skipped."""
    assert phase_z._dirty_paths(tmp_path, subprocess.run) is None  # not a git repo
    _init_repo(tmp_path)
    assert phase_z._dirty_paths(tmp_path, subprocess.run) == set()

def test_baseline_never_dirties_the_tree(repo: Path) -> None:
    """The baseline must be invisible to `git status`. Parked in the working tree
    it would need a `.gitignore` rule to hide — and PHASE-Z would then see its own
    baseline as this fire's output and try to stage a file it just deleted."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    assert _snapshot(repo).exists()
    assert _dirty(repo) == set(), "pre-fire guard must not dirty a clean tree"


# ── machine churn: dirty before the fire, but nobody's session ────────────────
# Background daemons rewrite next_tasks.json between fires. It is dirty at almost
# every fire start, so the two-bucket model filed it under "another session is
# still typing this" and alerted on it every single hour while no session was ever
# coming back for it (email-12038, boss: "一直爆警告"). PHASE-Z owns it now — but
# only when it can prove nobody is mid-write.

CHURN = phase_z._MACHINE_CHURN_PATHS[0]  # storage/next_tasks.json


def _seed_churn(repo: Path, payload: str = '[{"id": "t1"}]\n') -> None:
    """Tracked and committed, then rewritten by a 'daemon' before the fire starts."""
    _write(repo, CHURN, '[]\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed churn")
    _write(repo, CHURN, payload)


def test_machine_churn_is_adopted_not_alerted(repo: Path) -> None:
    _seed_churn(repo)
    phase_z.run_pre_fire_guard(repo_root=repo)  # churn is dirty at fire start

    alerts: list = []
    outcome = _fire(repo, alerts=alerts)

    assert outcome["committed"] is True
    assert CHURN in _head_files(repo), "the queue's history must not stall forever"
    assert outcome["churn"] == [CHURN]
    assert outcome["foreign"] == [], "churn is not another session's work"
    assert alerts == [], "this is the hourly alert the boss told us to kill"


def test_machine_churn_commits_even_when_the_fire_produced_nothing(repo: Path) -> None:
    """The alerting case at 12:37 was exactly this: no output of its own, so the
    old code returned `nothing_owned` and left the churn dirty for the next fire
    to alert about again."""
    _seed_churn(repo)
    phase_z.run_pre_fire_guard(repo_root=repo)

    alerts: list = []
    outcome = _fire(repo, alerts=alerts)

    assert outcome["committed"] is True
    assert _head_files(repo) == {CHURN}
    assert alerts == []


def test_half_written_churn_is_never_committed(repo: Path) -> None:
    """Incident #1: a next_tasks.json truncated mid-write was committed as valid
    history. A file that does not parse is escalated, not adopted."""
    _seed_churn(repo, payload='[{"id": "t1"},')  # truncated mid-write
    phase_z.run_pre_fire_guard(repo_root=repo)

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    outcome = _fire(repo, alerts=alerts)

    assert _git(repo, "rev-parse", "HEAD").stdout == before, \
        "truncated queue must not become history"
    assert outcome.get("churn", []) == []
    assert (repo / CHURN).read_text(encoding="utf-8") == '[{"id": "t1"},', "content survives"
    assert [lvl for lvl, _ in alerts] == ["critical"]


def test_churn_held_by_a_writer_is_left_for_the_next_fire(repo: Path) -> None:
    """A writer holds fcntl LOCK_EX across its read-modify-write (task_pool_claim.py).
    Staging underneath it is how you capture a half-written file — defer instead."""
    import fcntl

    _seed_churn(repo)
    phase_z.run_pre_fire_guard(repo_root=repo)

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    with open(repo / CHURN, "r+", encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX)  # a daemon is mid-write
        try:
            outcome = _fire(repo, alerts=alerts)
        finally:
            fcntl.flock(writer.fileno(), fcntl.LOCK_UN)

    assert _git(repo, "rev-parse", "HEAD").stdout == before, "must not stage under a writer"
    assert outcome.get("churn", []) == []
    assert alerts == [], "a busy writer is normal, not an incident"
    assert CHURN in _dirty(repo), "still dirty — the next fire picks it up"
