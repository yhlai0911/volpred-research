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
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z
from volpred.ops import fire_manifest

def _snapshot(root: Path) -> Path:
    """Where PHASE-Z parks its fire-start baseline: inside the git dir, so no
    `.gitignore` rule is load-bearing and nobody can ever commit it."""
    return root / ".git" / phase_z._SNAPSHOT_BASENAME


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@volpred.local")
    _git(root, "config", "user.name", "phase-z-ownership-test")
    _git(root, "config", "commit.gpgsign", "false")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
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


def _recording_review(filed: list, created: bool = True):
    """Stand-in for the real review-lane filer: records what PHASE-Z handed it.

    The real one writes the canonical queue; these tests are about the split
    decision, not about next_tasks.json.
    """
    class _Review:
        def __init__(self) -> None:
            self.created = created
            self.fingerprints: list[str] = []

        def __call__(self, *, repo_root, gate_paths, hhmm):
            self.fingerprints.append(phase_z._gate_review_fingerprint(repo_root, gate_paths))
            if self.created:
                filed.append(list(gate_paths))
            return {"task_id": f"phase_z_gate_review_{self.fingerprints[-1]}",
                    "created": self.created}

    return _Review()


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
    assert alerts == [], "a skipped path is not actionable until it becomes stale/unowned residue"


def test_foreign_path_stuck_across_fires_escalates_to_critical(repo: Path) -> None:
    """One fire's leftover is a session mid-edit; the same path still foreign three
    fires later is a leak nobody is coming back for — an hourly `warn` reads as
    noise (owner directive, 2026-07-11)."""
    _write(repo, "theirs.txt", "abandoned by a dead session\n")

    levels: list[str | None] = []
    for _ in range(phase_z._FOREIGN_STREAK_CRITICAL):
        alerts: list = []
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = _fire(repo, alerts=alerts)
        assert outcome["committed"] is False
        levels.append(alerts[0][0] if alerts else None)

    assert levels[:-1] == [None] * (phase_z._FOREIGN_STREAK_CRITICAL - 1)
    assert levels[-1] == "critical", "persistence across fires must escalate"
    assert outcome["stuck"] == ["theirs.txt"]
    assert "theirs.txt" in _dirty(repo), "escalating must not mean auto-adopting"


def test_1316_receipt_active_sessions_are_skipped_without_warn_or_risk(repo: Path) -> None:
    """Exact regression shape from Telegram msg 1312: one fire landed its output
    while 29 paths belonging to concurrent sessions were already dirty.  Skipping
    those bytes was correct; presenting normal concurrent work as an owner WARN
    was not.  Live write-time declarations make the distinction mechanical."""
    receipt_paths = [
        "AGENTS.md", "docs/error_log.md",
        "docs/refactor_commit_ownership_state_machine.md",
        "scripts/check_experiment_artifacts.py", "scripts/dedupe_next_tasks.py",
        "scripts/dispatch_slot_budget.py", "scripts/dispatch_supervisor/phase_z.py",
        "scripts/fb_realchrome_post.py", "scripts/hooks/gate_edit_guard.py",
        "scripts/preserve_gate_blob.py", "scripts/reap_orphan_deliverables.py",
        "scripts/tests/test_fire_manifest.py",
        "scripts/tests/test_gate_blob_preservation.py",
        "scripts/tests/test_orphan_namespace_registry.py",
        "scripts/tests/test_phase_z_foreign_incident.py",
        "scripts/tests/test_reproduce_spec_runtime_emitter.py",
        "scripts/worktree_gc.py", "src/volpred/ops/content.py",
        "src/volpred/ops/fire_manifest.py", "src/volpred/ops/foreign_incident.py",
        "src/volpred/ops/next_tasks.py", "src/volpred/ops/task_signature.py",
        "src/volpred/publisher/publisher.py", "src/volpred/research/init.py",
        "src/volpred/research/reproduce_spec.py",
        "storage/reports/mile_e4002f4f.json", "tests/test_task_signature.py",
        "tests/test_topic_cluster_gate.py", "tests/test_worktree_gc.py",
    ]
    assert len(receipt_paths) == 29
    for slot, paths in enumerate((receipt_paths[:10], receipt_paths[10:20], receipt_paths[20:]), 1):
        fire_id = f"concurrent-slot-{slot}"
        fire_manifest.open_manifest(repo, fire_id=fire_id, actor=f"slot-{slot}")
        for rel in paths:
            _write(repo, rel, f"active output from {fire_id}\n")
            fire_manifest.record(repo, fire_id, rel)

    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "experiments/k1/result.json", "{}\n")
    alerts: list = []
    outcome = _fire(
        repo, alerts=alerts,
        commit_receipt_override={"task_id": "receipt-1316", "subject": "repro", "body": ""},
    )

    assert outcome["committed"] is True
    assert set(outcome["foreign_ownership"]["active"]) == set(receipt_paths)
    assert outcome["foreign_ownership"]["risk"] == []
    assert alerts == []
    assert set(receipt_paths) <= _dirty(repo), "concurrent sessions keep every byte"


def test_live_declared_owner_never_accumulates_foreign_incident(repo: Path) -> None:
    rel = "scripts/live_session.py"
    fire_manifest.open_manifest(repo, fire_id="live-session", actor="interactive-2")
    _write(repo, rel, "still being edited\n")
    fire_manifest.record(repo, "live-session", rel)

    alerts: list = []
    for _ in range(phase_z._FOREIGN_STREAK_CRITICAL + 2):
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = _fire(repo, alerts=alerts)

    assert outcome["foreign_ownership"]["active"] == {rel: "live-session"}
    assert outcome["foreign_ownership"]["risk"] == []
    assert alerts == []
    streak_path = repo / ".git" / phase_z._FOREIGN_STREAK_BASENAME
    streaks = json.loads(streak_path.read_text(encoding="utf-8")) if streak_path.exists() else {}
    assert rel not in streaks


def test_stale_and_unowned_paths_are_the_only_foreign_risk(repo: Path) -> None:
    now = 1_700_000_000.0
    stale = "scripts/stale_session.py"
    orphan = "scripts/no_owner.py"
    fire_manifest.open_manifest(
        repo, fire_id="dead-session", actor="slot-dead",
        now=now - fire_manifest.MAX_AGE_S - 1,
    )
    _write(repo, stale, "abandoned\n")
    fire_manifest.record(
        repo, "dead-session", stale,
        now=now - fire_manifest.MAX_AGE_S - 1,
    )
    _write(repo, orphan, "anonymous residue\n")

    # Exercise the partition directly so the clock is deterministic.
    ownership = fire_manifest.resolve_ownership(repo, {stale, orphan}, now=now)
    assert ownership["stale"] == {stale: "dead-session"}
    assert ownership["orphan"] == [orphan]
    partition = phase_z._partition_foreign_ownership(repo, [stale, orphan])
    # Production time is later than the synthetic timestamp, so both remain risk.
    assert set(partition["risk"]) == {stale, orphan}
    assert partition["active"] == {}


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
    assert alerts == [], "the restarted streak must not jump straight to an incident"
    streak_path = repo / ".git" / phase_z._FOREIGN_STREAK_BASENAME
    assert json.loads(streak_path.read_text(encoding="utf-8"))["theirs.txt"] == 1


# ── the fire's own work still lands ──────────────────────────────────────────

def test_agent_work_is_committed_when_tree_was_clean(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "experiments/k2/k2.py", "x\n")
    _write(repo, "docs/note.md", "y\n")

    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"experiments/k2/k2.py", "docs/note.md"}
    assert outcome["foreign"] == []


def test_clean_tree_resolves_prior_internal_phase_z_episodes(repo: Path) -> None:
    resolved: list[str] = []

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        test_runner=_no_tests,
        alert_fn=lambda **_kwargs: {},
        internal_resolve_fn=lambda **kwargs: resolved.append(kwargs["alert_key"]) or {
            "resolved": True
        },
    )

    assert outcome["reason"] == "clean"
    assert resolved == ["phase_z_baseline_missing", "silent_fallback_new"]


def test_successful_candidate_resolves_internal_silent_fallback_episode(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "ours.txt", "candidate bytes\n")
    resolved: list[str] = []

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        test_runner=_no_tests,
        alert_fn=lambda **_kwargs: {},
        internal_resolve_fn=lambda **kwargs: resolved.append(kwargs["alert_key"]) or {
            "resolved": True
        },
    )

    assert outcome["committed"] is True
    assert resolved == ["phase_z_baseline_missing", "silent_fallback_new"]


def test_candidate_success_does_not_resolve_foreign_dirty_python_incident(repo: Path) -> None:
    _write(repo, "foreign.py", "def broken():\n    return None\n")
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "owned.md", "safe non-Python output\n")
    resolved: list[str] = []

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        test_runner=_no_tests,
        alert_fn=lambda **_kwargs: {},
        internal_resolve_fn=lambda **kwargs: resolved.append(kwargs["alert_key"]) or {
            "resolved": True
        },
    )

    assert outcome["committed"] is True
    assert "phase_z_baseline_missing" in resolved
    assert "silent_fallback_new" not in resolved
    assert "foreign.py" in _dirty(repo)


def test_candidate_adoption_cas_rejects_concurrent_head_advance(repo: Path) -> None:
    """A commit arriving during the candidate gate wins; PHASE-Z never overwrites it."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "ours.txt", "candidate bytes\n")
    advanced = False

    def racing_runner(cmd, **kwargs):
        nonlocal advanced
        if not advanced and "update-ref" in cmd:
            advanced = True
            _git(repo, "commit", "--allow-empty", "--no-verify", "-qm", "concurrent winner")
        return subprocess.run(cmd, **kwargs)

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        runner=racing_runner,
        test_runner=_no_tests,
        alert_fn=lambda **_k: {},
    )

    assert advanced is True
    assert outcome["committed"] is False
    assert outcome["reason"] == "commit_nonzero"
    assert outcome["rolled_back"] is True
    assert _git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "concurrent winner"
    assert (repo / "ours.txt").read_text() == "candidate bytes\n"


def test_shared_index_refresh_preserves_same_path_concurrent_stage(repo: Path) -> None:
    """A same-path git add after adoption is data, not refreshable base state."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "ours.txt", "candidate bytes\n")
    staged = False

    def racing_runner(cmd, **kwargs):
        nonlocal staged
        proc = subprocess.run(cmd, **kwargs)
        if not staged and "update-ref" in cmd and proc.returncode == 0:
            staged = True
            blob = subprocess.run(
                ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                input="concurrent staged bytes\n", capture_output=True, text=True, check=True,
            ).stdout.strip()
            _git(repo, "update-index", "--add", "--cacheinfo", "100644", blob, "ours.txt")
        return proc

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        runner=racing_runner,
        test_runner=_no_tests,
        alert_fn=lambda **_k: {},
    )

    assert outcome["committed"] is True
    assert staged is True
    assert outcome["index_refresh"]["preserved"] == ["ours.txt"]
    assert _git(repo, "show", "HEAD:ours.txt").stdout == "candidate bytes\n"
    assert _git(repo, "show", ":ours.txt").stdout == "concurrent staged bytes\n"


def test_candidate_hook_reads_candidate_tree_and_side_effects_are_isolated(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "[ \"$(cat ours.txt)\" = \"candidate bytes\" ] || exit 17\n"
        "echo isolated > hook-side-effect.txt\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "ours.txt", "candidate bytes\n")
    changed_live = False

    def racing_runner(cmd, **kwargs):
        nonlocal changed_live
        if not changed_live and cmd and cmd[0] == "bash" and "trusted-pre-commit" in cmd[1]:
            changed_live = True
            _write(repo, "ours.txt", "concurrent live bytes\n")
        return subprocess.run(cmd, **kwargs)

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        runner=racing_runner,
        test_runner=_no_tests,
        alert_fn=lambda **_k: {},
    )

    assert outcome["committed"] is True
    assert changed_live is True
    assert _git(repo, "show", "HEAD:ours.txt").stdout == "candidate bytes\n"
    assert (repo / "ours.txt").read_text() == "concurrent live bytes\n"
    assert not (repo / "hook-side-effect.txt").exists()


def test_missing_immutable_hook_fails_closed(repo: Path) -> None:
    (repo / ".git" / "hooks" / "pre-commit").unlink()
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "ours.txt", "candidate bytes\n")

    outcome = _fire(repo)

    assert outcome["committed"] is False
    assert outcome["reason"] == "candidate_gate_missing"
    assert subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "HEAD:ours.txt"],
        capture_output=True, text=True, check=False,
    ).returncode != 0


def test_trusted_gate_change_is_held_back_without_blocking_the_batch(repo: Path) -> None:
    """assign_010d1a2d: one dirty gate file used to roll back the whole batch.

    The gate change must still not land automatically (a weakened gate would
    judge the next fire's commit), but everything else must reach HEAD and the
    deferred file must get a named forward path.
    """
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "scripts/audit_test_imports.py", "raise SystemExit(0)\n")
    _write(repo, "scripts/audit_silent_fallbacks.py", "raise SystemExit(0)\n")
    _write(repo, "storage/qa/silent_fallback_baseline.json", "[]\n")
    _write(repo, "experiments/k1/k1.py", "innocent bystander\n")

    filed: list[list[str]] = []
    outcome = _fire(repo, gate_review_fn=_recording_review(filed))

    assert outcome["committed"] is True
    assert "experiments/k1/k1.py" in _head_files(repo)          # collateral freed
    assert outcome["gate_deferred"] == [
        "scripts/audit_silent_fallbacks.py",
        "scripts/audit_test_imports.py",
        "storage/qa/silent_fallback_baseline.json",
    ]
    for rel in outcome["gate_deferred"]:                        # threat still held
        assert rel not in _head_files(repo)
        assert rel in _dirty(repo)
    assert filed == [outcome["gate_deferred"]]                  # forward path exists


def test_gate_only_fire_is_not_reported_as_nothing_owned(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "scripts/audit_test_imports.py", "raise SystemExit(0)\n")

    outcome = _fire(repo, gate_review_fn=_recording_review([]))

    assert outcome["committed"] is False
    assert outcome["reason"] == "gate_deferred_only"
    assert outcome["gate_deferred"] == ["scripts/audit_test_imports.py"]


def test_unchanged_gate_change_does_not_refile_or_realert_each_fire(repo: Path) -> None:
    """The deadlock's loudest symptom: the same reason, every hour, forever."""
    filed: list[list[str]] = []
    review = _recording_review(filed, created=True)

    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "scripts/audit_test_imports.py", "raise SystemExit(0)\n")
    _write(repo, "experiments/k1/first.py", "fire one\n")
    alerts_one: list = []
    first = _fire(repo, alerts=alerts_one, gate_review_fn=review)

    # second fire: gate file still dirty, untouched; review task already queued
    review.created = False
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "experiments/k1/second.py", "fire two\n")
    alerts_two: list = []
    second = _fire(repo, alerts=alerts_two, gate_review_fn=review)

    assert first["committed"] is True and second["committed"] is True
    assert "experiments/k1/second.py" in _head_files(repo)      # batch keeps flowing
    # Fire two never re-enters the split at all: the gate file was already dirty
    # at its baseline, so it is foreign to that fire and left alone. One review
    # task, one alert, then silence — not the same reason every hour.
    assert len(review.fingerprints) == 1
    assert [t for _lvl, t in alerts_two if "gate" in t] == []
    assert "scripts/audit_test_imports.py" in _dirty(repo)      # still awaiting review
    assert "scripts/audit_test_imports.py" not in _head_files(repo)


def test_gate_review_fingerprint_tracks_content(tmp_path: Path) -> None:
    rel = "scripts/audit_test_imports.py"
    (tmp_path / "scripts").mkdir()
    (tmp_path / rel).write_text("v1\n", encoding="utf-8")
    first = phase_z._gate_review_fingerprint(tmp_path, [rel])
    assert phase_z._gate_review_fingerprint(tmp_path, [rel]) == first
    (tmp_path / rel).write_text("v2\n", encoding="utf-8")
    assert phase_z._gate_review_fingerprint(tmp_path, [rel]) != first


def test_candidate_gate_blocks_test_without_its_foreign_script(repo: Path) -> None:
    """Reproduce 273b2b110: test owned by this fire, implementation pre-existing/foreign."""
    source_root = Path(phase_z.__file__).resolve().parents[2]
    for rel in ("scripts/git_hooks/pre-commit", "scripts/audit_test_imports.py"):
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / rel, dest)
    _write(repo, "src/volpred/__init__.py", "")
    _git(repo, "add", "scripts/git_hooks/pre-commit", "scripts/audit_test_imports.py",
         "src/volpred/__init__.py")
    _git(repo, "commit", "-qm", "seed canonical dependency gate")
    installed_hook = repo / ".git" / "hooks" / "pre-commit"
    shutil.copyfile(repo / "scripts" / "git_hooks" / "pre-commit", installed_hook)
    installed_hook.chmod(0o755)

    _write(repo, "scripts/reproduce_check.py", "VALUE = 1\n")  # foreign before fire
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "tests/test_reproduce.py", "from scripts import reproduce_check\n")
    before_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    before_index = _git(repo, "write-tree").stdout.strip()

    outcome = _fire(repo)

    assert outcome["committed"] is False
    assert outcome["reason"] == "nothing_to_commit"
    assert "rolled_back" not in outcome
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before_head
    assert _git(repo, "write-tree").stdout.strip() == before_index
    assert (repo / "scripts/reproduce_check.py").exists()
    assert (repo / "tests/test_reproduce.py").exists()


def test_foreign_worktree_hook_cannot_weaken_pinned_base_gate(repo: Path) -> None:
    source_root = Path(phase_z.__file__).resolve().parents[2]
    for rel in ("scripts/git_hooks/pre-commit", "scripts/audit_test_imports.py"):
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / rel, dest)
    _write(repo, "src/volpred/__init__.py", "")
    _git(repo, "add", "scripts/git_hooks/pre-commit", "scripts/audit_test_imports.py",
         "src/volpred/__init__.py")
    _git(repo, "commit", "-qm", "seed canonical dependency gate")
    installed_hook = repo / ".git" / "hooks" / "pre-commit"
    shutil.copyfile(repo / "scripts" / "git_hooks" / "pre-commit", installed_hook)
    installed_hook.chmod(0o755)

    # Foreign before the fire: old implementation executed this live copy and
    # let the partial candidate through.
    _write(repo, "scripts/git_hooks/pre-commit", "#!/bin/sh\nexit 0\n")
    _write(repo, "scripts/reproduce_check.py", "VALUE = 1\n")
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "tests/test_reproduce.py", "from scripts import reproduce_check\n")

    outcome = _fire(repo)

    assert outcome["committed"] is False
    assert outcome["reason"] == "nothing_to_commit"
    assert "rolled_back" not in outcome


def test_lazypack_outputs_are_not_broad_machine_churn() -> None:
    """Exact queue output_paths + reaper own panels; PHASE-Z must not claim a tree."""
    assert phase_z._is_machine_state(
        "storage/lazypack_jobs/mile_x/panels/1_framework.png"
    ) is False


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


def test_missing_baseline_uses_internal_p1_router_not_generic_alert(repo: Path) -> None:
    _write(repo, "someones_work.txt", "who wrote this?\n")
    generic: list[dict] = []
    internal: list[dict] = []

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        test_runner=_no_tests,
        alert_fn=lambda **kwargs: generic.append(kwargs) or {"sent": True},
        internal_alert_fn=lambda **kwargs: internal.append(kwargs) or {"sent": False},
        internal_resolve_fn=lambda **kwargs: {"resolved": False},
    )

    assert outcome["reason"] == "ownership_unknown"
    assert generic == []
    assert len(internal) == 1
    assert internal[0]["alert_key"] == "phase_z_baseline_missing"


def test_silent_fallback_gate_routes_internally_but_other_gates_do_not(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "echo '[pre-commit] BLOCKED — this commit introduces new silent fallback(s):' >&2\n"
        "echo '[silent-fallback-audit] findings=1 new=1' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "owned.py", "def f():\n    return None\n")
    generic: list[dict] = []
    internal: list[dict] = []

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="03:00",
        test_runner=_no_tests,
        alert_fn=lambda **kwargs: generic.append(kwargs) or {"sent": True},
        internal_alert_fn=lambda **kwargs: internal.append(kwargs) or {"sent": False},
        internal_resolve_fn=lambda **kwargs: {"resolved": False},
    )

    assert outcome["reason"] == "commit_nonzero"
    assert outcome["internal_alert_key"] == "silent_fallback_new"
    assert generic == []
    assert internal[0]["alert_key"] == "silent_fallback_new"
    assert phase_z._is_silent_fallback_gate_output("[pre-commit] BLOCKED — fake gate") is False
    assert phase_z._is_silent_fallback_clean_gate_output(
        "[pre-commit] silent-fallback-audit passed new=0 scope=2"
    ) is True
    assert phase_z._is_silent_fallback_clean_gate_output("exit 0 without Gate 2") is False


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

CHURN = "storage/next_tasks.json"


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


# ── the class, not the instance ──────────────────────────────────────────────
# The bug these three catch: ownership used to be a hand-written list of filenames
# holding exactly one entry (next_tasks.json). Every other daemon-written state file
# — dreaming runs, analytics snapshots, the event ledger, the token report — was
# therefore "somebody else's", and PHASE-Z alerted on it hourly while being the only
# thing that could ever have committed it. Eleven files were eight fires deep when the
# owner escalated (email-12123 / email-12124).
#
# Enumerating those eleven would have fixed the instance and left the class: the next
# daemon to write a new state file restarts the alarm on its first day. Ownership is
# derived from the namespace now, and these lock that in.


def test_a_state_file_no_rule_has_ever_heard_of_is_still_owned(repo: Path) -> None:
    """The drift gate. This path is in no list — it is owned because of where it lives.
    A daemon shipping tomorrow gets the same treatment without touching this module."""
    novel = "storage/ops/some_daemon_invented_this_today.json"
    _write(repo, novel, '{"runs": 1}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed novel state")
    _write(repo, novel, '{"runs": 2}\n')  # the daemon rewrites it between fires

    phase_z.run_pre_fire_guard(repo_root=repo)
    alerts: list = []
    outcome = _fire(repo, alerts=alerts)

    assert outcome["churn"] == [novel], "namespace ownership, not a filename lookup"
    assert outcome["foreign"] == []
    assert novel in _head_files(repo)
    assert alerts == [], "no hourly alarm for a file that has an owner"


def test_garbage_collected_state_is_committed_not_deferred_forever(repo: Path) -> None:
    """The event ledger expires its own entries. A deleted path cannot be opened, so
    the lock/parse gate raised ENOENT and filed it 'deferred — next fire will get it'.
    For a file that is never coming back, the next fire says the same thing, forever."""
    ledger = "storage/ops/event_ledger/deadbeef.json"
    _write(repo, ledger, '{"gc_after": "2026-07-01"}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed ledger")
    (repo / ledger).unlink()  # gc_event_ledger expires it

    phase_z.run_pre_fire_guard(repo_root=repo)
    alerts: list = []
    outcome = _fire(repo, alerts=alerts)

    assert outcome["churn"] == [ledger]
    assert ledger in _head_files(repo), "the deletion must land, not cycle"
    assert ledger not in _dirty(repo)
    assert alerts == []


def test_code_left_behind_is_still_foreign(repo: Path) -> None:
    """The boundary that makes adoption safe. Code carries a session owner who is
    expected to commit it with a message and a green test run — adopting it silently
    is incident #2 and #3. Widening ownership to daemon state must not widen it here."""
    _write(repo, "scripts/some_audit.py", "print('v1')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed code")
    _write(repo, "scripts/some_audit.py", "print('half-typed edit')\n")

    phase_z.run_pre_fire_guard(repo_root=repo)
    alerts: list = []
    outcome = _fire(repo, alerts=alerts)

    assert outcome.get("churn", []) == [], "code is never machine churn"
    assert outcome["foreign"] == ["scripts/some_audit.py"]
    assert "scripts/some_audit.py" in _dirty(repo), "left for its author"
