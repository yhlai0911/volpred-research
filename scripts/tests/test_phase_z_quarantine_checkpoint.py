"""D2: a stuck foreign path's bytes must become *retrievable*, not just visible.

Background — `docs/governance/2026-07/phase_z_ownership_external_review.md` §4 D2.
PHASE-Z guaranteed exactly one thing: it never sweeps somebody else's work into
main. It never guaranteed the work survives. A dirty working tree is not durable
preservation — those bytes can be overwritten by the next writer, reset by a
human, or deleted by a cleanup pass. 40+ paths sat there for up to 78 fires, and
"nothing has deleted them yet" was doing all the work in the phrase "safe".

So PHASE-Z now checkpoints stuck foreign bytes into an immutable ref. The four
properties below are the whole contract, and each is a way this could have been
implemented wrongly in a way that looks fine in a log:

1. the working tree is byte-for-byte unchanged (a "preservation" step that
   rewrites the file it preserves is the 2026-07-10 incident wearing a hat);
2. main's HEAD does not move (preservation must never become publication);
3. the content comes back out via ``git show <ref>:<path>`` (an object nobody
   can address is not preservation either);
4. a path a producer is actively writing is NOT checkpointed — capturing a torn
   half-file and calling it the saved state is worse than saving nothing.

These drive real git in a temp repo, in the style of tests/test_phase_z_ownership.py:
the behaviour under test is git plumbing semantics, and a fake git would agree
with any bug.
"""
from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z

THEIRS = "scripts/somebody_elses_edit.py"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    )


def _git_raw(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@volpred.local")
    _git(root, "config", "user.name", "phase-z-quarantine-test")
    _git(root, "config", "commit.gpgsign", "false")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")


def _no_tests(*_a, **_k):
    """Neutralise the post-commit test gate; it has its own suite."""
    return subprocess.CompletedProcess(args=[], returncode=5, stdout="", stderr="")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def _fire(repo: Path, alerts: list | None = None, **kw) -> dict:
    def _alert(*, level, title, body):
        if alerts is not None:
            alerts.append((level, title, body))
        return {"sent": True}

    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="03:00", test_runner=_no_tests, alert_fn=_alert, **kw
    )


def _write(root: Path, rel: str, text: str) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _fire_until_stuck(repo: Path, fires: int = phase_z._FOREIGN_STREAK_CRITICAL,
                      alerts: list | None = None) -> dict:
    """Run whole fires until the foreign path crosses the streak threshold.

    Streak state is only advanced by a real fire, so the threshold has to be
    reached the way production reaches it rather than by writing the counter file.
    """
    outcome: dict = {}
    for _ in range(fires):
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = _fire(repo, alerts=alerts)
    return outcome


def _quarantine_refs(repo: Path) -> list[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)",
               phase_z._FOREIGN_QUARANTINE_REF_PREFIX).stdout
    return [line for line in out.splitlines() if line]


# ── the contract ─────────────────────────────────────────────────────────────

def test_stuck_foreign_bytes_are_retrievable_from_an_immutable_ref(repo: Path) -> None:
    """The point of the whole change: after the working copy is gone, the bytes
    are still addressable."""
    body = "half-finished edit\nline two\n"
    _write(repo, THEIRS, body)

    outcome = _fire_until_stuck(repo)

    assert outcome["reason"] == "nothing_owned"
    quarantine = outcome["quarantine"]
    assert quarantine["reason"] == "checkpointed", quarantine
    assert quarantine["created"] is True
    assert quarantine["checkpointed"] == [THEIRS]
    ref = quarantine["ref"]
    assert ref.startswith(phase_z._FOREIGN_QUARANTINE_REF_PREFIX + "/")

    # The retrieval path a human is told to use, run verbatim.
    shown = _git(repo, "show", f"{ref}:{THEIRS}").stdout
    assert shown == body

    # And it survives the working copy being destroyed — which is the failure
    # mode "still dirty, nobody deleted it yet" was never protecting against.
    (repo / THEIRS).unlink()
    assert _git(repo, "show", f"{ref}:{THEIRS}").stdout == body


def test_checkpoint_leaves_the_working_tree_byte_for_byte_identical(repo: Path) -> None:
    """Preservation may not touch what it preserves — not the bytes, not the
    mtime-visible content, not the set of dirty paths, not the index."""
    body = b"binary-ish \x00\x01 payload\nnot utf-8 clean\xff\n"
    dest = repo / "experiments" / "k1380" / "losses_all.npy"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    rel = "experiments/k1380/losses_all.npy"

    index_before = (repo / ".git" / "index").read_bytes() if (repo / ".git" / "index").exists() else b""
    status_before = _git(repo, "status", "--porcelain", "-z", "--untracked-files=all").stdout

    outcome = _fire_until_stuck(repo)

    assert outcome["quarantine"]["reason"] == "checkpointed"
    assert dest.read_bytes() == body, "the checkpointed file's bytes must not change"
    assert _git(repo, "status", "--porcelain", "-z",
                "--untracked-files=all").stdout == status_before, \
        "the checkpoint must not stage, unstage or clean anything"
    index_after = (repo / ".git" / "index").read_bytes() if (repo / ".git" / "index").exists() else b""
    assert index_after == index_before, "the real index must not be written"
    # ...and the bytes really did make it in, unchanged, binary included.
    ref = outcome["quarantine"]["ref"]
    assert _git_raw(repo, "show", f"{ref}:{rel}").stdout == body


def test_checkpoint_does_not_move_main(repo: Path) -> None:
    """Quarantine is preservation, never publication. main must not learn about
    these bytes, and the checkpoint commit must not even be an ancestor of it."""
    _write(repo, THEIRS, "mid-edit\n")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    outcome = _fire_until_stuck(repo)

    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == head_before
    assert THEIRS not in _git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout

    checkpoint = outcome["quarantine"]["commit"]
    merge_base = _git_raw(repo, "merge-base", "--is-ancestor", checkpoint, "HEAD")
    assert merge_base.returncode != 0, \
        "a quarantine commit must never be reachable from main — it is parentless by design"


def test_a_path_a_writer_is_holding_is_not_checkpointed(repo: Path) -> None:
    """A producer holding the flock is mid-write: its bytes are a torn snapshot
    and it is coming back for them. Saving that and calling it the preserved
    state is worse than saving nothing."""
    _write(repo, THEIRS, "being written right now\n")

    alerts: list = []
    with open(repo / THEIRS, "r+", encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX)  # a producer is mid-edit
        try:
            outcome = _fire_until_stuck(repo, alerts=alerts)
        finally:
            fcntl.flock(writer.fileno(), fcntl.LOCK_UN)

    quarantine = outcome["quarantine"]
    assert quarantine["checkpointed"] == []
    assert quarantine["ref"] is None
    assert quarantine["skipped"][THEIRS] == "live_writer"
    assert quarantine["reason"] == "nothing_checkpointable"
    assert _quarantine_refs(repo) == [], "no ref may be created for a live path"
    # Still stuck, still alerted: skipping is a deferral, not a resolution.
    assert THEIRS in outcome["stuck"]


def test_the_lock_releasing_lets_the_next_fire_checkpoint_it(repo: Path) -> None:
    """The live-writer skip must not latch. This is the failure shape of
    docs/fix_56ddf72b_dirty_guard.md: a safety exclusion that never lifts."""
    _write(repo, THEIRS, "was locked\n")
    with open(repo / THEIRS, "r+", encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX)
        try:
            locked = _fire_until_stuck(repo)
        finally:
            fcntl.flock(writer.fileno(), fcntl.LOCK_UN)
    assert locked["quarantine"]["checkpointed"] == []

    phase_z.run_pre_fire_guard(repo_root=repo)
    freed = _fire(repo)

    assert freed["quarantine"]["checkpointed"] == [THEIRS]
    assert _git(repo, "show", f"{freed['quarantine']['ref']}:{THEIRS}").stdout == "was locked\n"


def test_unchanged_bytes_reuse_the_existing_ref(repo: Path) -> None:
    """The same 40 paths stuck for 78 fires must not mint 78 refs. A namespace
    nobody can read back is its own way of losing the content."""
    _write(repo, THEIRS, "unchanged across fires\n")
    first = _fire_until_stuck(repo)
    assert first["quarantine"]["created"] is True

    phase_z.run_pre_fire_guard(repo_root=repo)
    second = _fire(repo)

    assert second["quarantine"]["created"] is False
    assert second["quarantine"]["reason"] == "unchanged"
    assert second["quarantine"]["ref"] == first["quarantine"]["ref"]
    assert _quarantine_refs(repo) == [first["quarantine"]["ref"]]


def test_edited_bytes_get_their_own_checkpoint(repo: Path) -> None:
    """Dedup may not cost history: a second version of the same stuck path is a
    second thing that can be lost."""
    _write(repo, THEIRS, "version one\n")
    first = _fire_until_stuck(repo)

    _write(repo, THEIRS, "version two\n")
    phase_z.run_pre_fire_guard(repo_root=repo)
    second = _fire(repo)

    assert second["quarantine"]["created"] is True
    assert second["quarantine"]["ref"] != first["quarantine"]["ref"]
    assert _git(repo, "show", f"{first['quarantine']['ref']}:{THEIRS}").stdout == "version one\n"
    assert _git(repo, "show", f"{second['quarantine']['ref']}:{THEIRS}").stdout == "version two\n"


def test_no_quarantine_before_the_streak_threshold(repo: Path) -> None:
    """One fire's leftover is a session mid-edit, not a stuck path. Checkpointing
    every dirty file every hour would bury the real ones."""
    _write(repo, THEIRS, "mid-edit\n")
    phase_z.run_pre_fire_guard(repo_root=repo)

    outcome = _fire(repo)

    assert outcome["quarantine"]["reason"] == "no_stuck_paths"
    assert _quarantine_refs(repo) == []


def test_the_critical_alert_tells_the_reader_how_to_get_the_bytes_back(repo: Path) -> None:
    """The alert used to end at "nobody will delete them". Now it has to name the
    ref, because that is the only claim of durability that is actually true."""
    _write(repo, THEIRS, "stuck\n")
    alerts: list = []
    outcome = _fire_until_stuck(repo, alerts=alerts)

    criticals = [a for a in alerts if a[0] == "critical"]
    assert criticals, "a stuck path still pages"
    body = criticals[-1][2]
    ref = outcome["quarantine"]["ref"]
    assert ref in body
    assert "git show" in body


def test_a_deleted_path_is_skipped_rather_than_failing_the_fire(repo: Path) -> None:
    """A dirty *deletion* has no bytes to preserve (they are in HEAD already).
    It must not error, and it must not silently look like a successful save."""
    _write(repo, "tracked.txt", "content\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "add tracked")
    (repo / "tracked.txt").unlink()

    outcome = _fire_until_stuck(repo)

    quarantine = outcome["quarantine"]
    assert quarantine["skipped"]["tracked.txt"] == "not_a_regular_file"
    assert quarantine["checkpointed"] == []
    assert quarantine["reason"] == "nothing_checkpointable"
