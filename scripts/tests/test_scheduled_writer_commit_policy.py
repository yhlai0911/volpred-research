"""Single mechanical owner for scheduled-writer Git ownership policy.

The policy is intentionally a ratchet over the full executable population in
``config/runtime_schedules.json``.  Adding a cron job/daemon or a host
LaunchAgent without classifying its tracked outputs makes this suite fail.
"""
from __future__ import annotations

import copy
import json
import plistlib
import re
import subprocess
from pathlib import Path

import volpred.ops.scheduled_writer_commit as writer_commit
from scripts.dispatch_supervisor.phase_z import _is_machine_state
from volpred.config.runtime import get_frontend_path
from volpred.ops.scheduled_writer_commit import (
    commit_owned_outputs,
    dirty_paths_before_write,
    writable_output_paths,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = ROOT / "config" / "runtime_schedules.json"
POLICY_PATH = ROOT / "config" / "scheduled_writer_ownership.json"
ALLOWED_POLICIES = {
    "self_commit",
    "phase_z_machine_state",
    "no_repo_tracked_output",
    "tracked_content_invariant",
    "delegated_delivery_contract",
    "deprecated",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_process_ids(runtime: dict) -> set[str]:
    cron_jobs = (
        item
        for item in runtime["cron_jobs"]
        if item.get("status") != "retired"
        or any(
            item.get(field)
            for field in ("command", "canonical_script", "tcc_bypass_copy")
        )
    )
    processes = {
        *(item["id"] for item in runtime["system_crontab"]["items"]),
        *(item["id"] for item in cron_jobs),
        *(item["id"] for item in runtime["daemons"]),
    }
    scheduler = runtime.get("schedule_materialization") or {}
    if scheduler.get("job_id"):
        processes.add(str(scheduler["job_id"]))
    return processes


def _uncovered(runtime: dict, policy: dict) -> tuple[set[str], set[str]]:
    scheduled = _runtime_process_ids(runtime)
    classified = set(policy["jobs"])
    return scheduled - classified, classified - scheduled


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(path: Path) -> None:
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "scheduled-writer-test@example.com")
    _git(path, "config", "user.name", "Scheduled Writer Test")


def _plist_label(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return str(plistlib.load(handle)["Label"])
    except Exception:
        # Some canonical templates contain deployment comments that are not
        # valid XML comments (for example a literal ``--dry-run``).  Ownership
        # coverage still needs their declared Label; plist validity has a
        # separate deployment gate.
        text = path.read_text(encoding="utf-8")
        match = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", text)
        assert match is not None, f"cannot read LaunchAgent Label: {path}"
        return match.group(1)


def test_policy_covers_every_runtime_process_exactly_once() -> None:
    missing, stale = _uncovered(_load(RUNTIME_PATH), _load(POLICY_PATH))
    assert missing == set(), f"unclassified scheduled process(es): {sorted(missing)}"
    assert stale == set(), f"policy rows no longer present in runtime schedule: {sorted(stale)}"


def test_population_ratchet_fires_for_a_new_job() -> None:
    runtime = copy.deepcopy(_load(RUNTIME_PATH))
    runtime["system_crontab"]["items"].append({"id": "new_unclassified_writer"})
    missing, stale = _uncovered(runtime, _load(POLICY_PATH))
    assert missing == {"new_unclassified_writer"}
    assert stale == set()


def test_every_policy_row_has_an_existing_entrypoint_and_reason() -> None:
    for job_id, row in _load(POLICY_PATH)["jobs"].items():
        assert row["policy"] in ALLOWED_POLICIES, (job_id, row["policy"])
        assert str(row.get("reason") or "").strip(), f"missing exemption/ownership reason: {job_id}"
        entrypoint = ROOT / row["entrypoint"]
        assert entrypoint.is_file(), f"missing entrypoint for {job_id}: {entrypoint}"
        outputs = row.get("tracked_outputs")
        assert isinstance(outputs, list), f"tracked_outputs must be explicit for {job_id}"
        if row["policy"] == "no_repo_tracked_output":
            assert outputs == [], f"no-output policy cannot declare tracked output: {job_id}"


def test_self_commit_rows_have_guard_and_path_scoped_commit() -> None:
    for job_id, row in _load(POLICY_PATH)["jobs"].items():
        if row["policy"] != "self_commit":
            continue
        owner = ROOT / row["commit_owner"]
        text = owner.read_text(encoding="utf-8")
        # Either probe API satisfies the ratchet. `dirty_paths_before_write` is the
        # conservative union (dirty + unprobed); `probe_dirty_outputs` keeps them
        # apart so the caller can establish authorship via adoptable_churn instead
        # of latching on its own uncommitted output. Both are a real pre-write guard.
        helper_guard = (
            ("dirty_paths_before_write" in text or "probe_dirty_outputs" in text)
            and "writable_output_paths" in text
        )
        shell_guard = "git status --porcelain" in text
        helper_commit = "commit_owned_outputs" in text
        shell_commit = "git commit --only" in text and " -- " in text
        lock_cli_commit = "scripts/git_writer_lock.py" in text and " commit " in text
        assert helper_guard or shell_guard, f"no staged+unstaged pre-write guard: {job_id}"
        assert helper_commit or shell_commit or lock_cli_commit, (
            f"commit is not exact-path/--only scoped: {job_id}"
        )
        assert helper_commit or lock_cli_commit, f"commit bypasses Git writer lease: {job_id}"

    helper_text = (ROOT / "src/volpred/ops/scheduled_writer_commit.py").read_text()
    assert "with git_writer_lock(" in helper_text


def test_phase_z_exemptions_are_inside_the_declared_authorship_boundary() -> None:
    for job_id, row in _load(POLICY_PATH)["jobs"].items():
        if row["policy"] != "phase_z_machine_state":
            continue
        probes = row.get("phase_z_probe_paths") or []
        assert probes, f"machine-state exemption lacks a concrete probe: {job_id}"
        assert all(_is_machine_state(path) for path in probes), (job_id, probes)


def test_non_process_runtime_sections_are_exactly_ratcheted() -> None:
    runtime = _load(RUNTIME_PATH)
    dispositions = _load(POLICY_PATH)["metadata"]["non_process_sections"]
    assert set(dispositions) == {
        "remote_triggers.items",
        "session_crons.items",
        "event_jobs.items",
        "idle_policy",
    }
    assert set(dispositions["remote_triggers.items"]["ids"]) == {
        item["id"] for item in runtime["remote_triggers"]["items"]
    }
    session_jobs = dispositions["session_crons.items"]["jobs"]
    assert set(session_jobs) == {item["id"] for item in runtime["session_crons"]["items"]}
    assert set(dispositions["event_jobs.items"]["ids"]) == {
        item["id"] for item in runtime["event_jobs"]["items"]
    }
    for section in dispositions.values():
        if "jobs" in section:
            assert all(str(row.get("reason") or "").strip() for row in section["jobs"].values())
        else:
            assert str(section.get("reason") or "").strip()


def test_non_process_population_ratchet_fires_for_new_session_and_event() -> None:
    runtime = copy.deepcopy(_load(RUNTIME_PATH))
    runtime["session_crons"]["items"].append({"id": "new_session_writer"})
    runtime["event_jobs"]["items"].append({"id": "new_event_writer"})
    dispositions = _load(POLICY_PATH)["metadata"]["non_process_sections"]
    assert {item["id"] for item in runtime["session_crons"]["items"]} - set(
        dispositions["session_crons.items"]["jobs"]
    ) == {"new_session_writer"}
    assert {item["id"] for item in runtime["event_jobs"]["items"]} - set(
        dispositions["event_jobs.items"]["ids"]
    ) == {"new_event_writer"}


def test_declared_concrete_outputs_are_tracked_in_the_correct_git_root() -> None:
    policy = _load(POLICY_PATH)
    frontend_root = get_frontend_path()
    frontend_prefix = frontend_root.relative_to(ROOT).as_posix() + "/"

    def assert_tracked(owner_id: str, output: str) -> None:
        if any(
            token in output
            for token in (
                "dynamic ",
                "agent fire-owned",
                "dynamic task outputs",
                "dynamic remediation outputs",
                "dynamic already-authored paths",
                "dynamic article outputs",
            )
        ):
            return
        if output.startswith(frontend_prefix):
            # frontend-v2-fix 是巢狀 git repo，被主 repo .gitignore —— CI checkout 沒有它。
            # 該面向由前端 repo 自己的 gate 覆蓋，這裡只在本機有 checkout 時驗。
            if not (frontend_root / ".git").exists():
                return
            pathspec = output.removeprefix(frontend_prefix)
            matches = _git(frontend_root, "ls-files", "--", pathspec).stdout.splitlines()
        else:
            matches = _git(ROOT, "ls-files", "--", output).stdout.splitlines()
        assert matches, f"declared tracked output does not match Git: {owner_id}: {output}"

    for job_id, row in policy["jobs"].items():
        for output in row["tracked_outputs"]:
            assert_tracked(job_id, output)

    non_process = policy["metadata"]["non_process_sections"]
    for session_id, row in non_process["session_crons.items"]["jobs"].items():
        for output in row["tracked_outputs"]:
            assert_tracked(session_id, output)
    for output in non_process["event_jobs.items"]["tracked_outputs"]:
        assert_tracked("event_jobs.items", output)

    invariant = policy["jobs"]["collect_tw_data"]
    assert invariant["policy"] == "tracked_content_invariant"
    lock_path = ROOT / invariant["tracked_outputs"][0]
    assert lock_path.read_bytes() == b"", "tracked lock exemption requires byte-empty invariant"


def test_launchagent_population_is_registered_when_available() -> None:
    policy = _load(POLICY_PATH)
    registered = set(policy["launchagents"])

    canonical_labels = set()
    for plist in (ROOT / "ops" / "launchd").glob("com.volpred.*.plist"):
        canonical_labels.add(_plist_label(plist))
    assert canonical_labels <= registered

    installed_dir = Path.home() / "Library" / "LaunchAgents"
    if installed_dir.is_dir():
        installed_labels = set()
        for plist in installed_dir.glob("com.volpred.*.plist"):
            installed_labels.add(_plist_label(plist))
        assert installed_labels <= registered, (
            "host LaunchAgent missing writer disposition: "
            f"{sorted(installed_labels - registered)}"
        )

    jobs = policy["jobs"]
    for label, row in policy["launchagents"].items():
        assert row["status"] in {"active", "retired", "host_only_exception"}, label
        if "job_id" in row:
            assert row["job_id"] in jobs, (label, row["job_id"])
        else:
            # A fully retired agent may drop job_id: keeping a zombie runtime
            # spec + policy row just to satisfy this reference would be the
            # two-systems anti-pattern (WS-H2 2026-07-20, work-summary
            # retirement). The row must still document why it lingers —
            # typically "host plist not yet booted out".
            assert row["status"] in {"host_only_exception", "retired"}, label
            assert str(row.get("reason") or "").strip(), label


def test_operations_core_scheduler_is_registered_as_delegating_clock() -> None:
    policy = _load(POLICY_PATH)
    runtime = _load(RUNTIME_PATH)

    assert runtime["schedule_materialization"]["job_id"] == (
        "operations_core_scheduler"
    )
    scheduler = policy["jobs"]["operations_core_scheduler"]
    assert scheduler == {
        "entrypoint": "scripts/operations_core_scheduler.py",
        "policy": "no_repo_tracked_output",
        "tracked_outputs": [],
        "reason": (
            "Writes ignored scheduler receipt, lock, and log state only; "
            "each materialized job retains its separately registered "
            "writer policy."
        ),
    }
    assert policy["launchagents"][
        "com.volpred.operations-core-scheduler"
    ] == {
        "job_id": "operations_core_scheduler",
        "status": "active",
    }


def test_this_file_is_the_only_policy_enforcement_owner() -> None:
    owners = []
    for test_file in (ROOT / "scripts" / "tests").glob("test_*.py"):
        if "scheduled_writer_ownership.json" in test_file.read_text(encoding="utf-8"):
            owners.append(test_file.resolve())
    assert owners == [Path(__file__).resolve()]


def test_helper_skips_preexisting_staged_path_and_preserves_foreign_index(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    for name in ("owned.txt", "pre_dirty.txt", "foreign.txt"):
        (repo / name).write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")

    (repo / "pre_dirty.txt").write_text("other author\n", encoding="utf-8")
    (repo / "foreign.txt").write_text("foreign staged\n", encoding="utf-8")
    _git(repo, "add", "pre_dirty.txt", "foreign.txt")

    dirty = dirty_paths_before_write(
        repo,
        ["owned.txt", "pre_dirty.txt"],
        label="test-writer",
    )
    assert dirty == frozenset({"pre_dirty.txt"})
    writable = writable_output_paths(
        repo,
        ["owned.txt", "pre_dirty.txt"],
        dirty_before=dirty,
        label="test-writer",
    )
    assert writable == ["owned.txt"]

    (repo / "owned.txt").write_text("writer output\n", encoding="utf-8")
    committed = commit_owned_outputs(
        repo,
        ["owned.txt", "pre_dirty.txt"],
        dirty_before=dirty,
        message="scheduled exact output",
        label="test-writer",
    )
    assert committed == ["owned.txt"]
    assert _git(repo, "show", "--pretty=format:", "--name-only", "HEAD").stdout.split() == [
        "owned.txt"
    ]
    assert set(_git(repo, "diff", "--cached", "--name-only").stdout.splitlines()) == {
        "foreign.txt",
        "pre_dirty.txt",
    }
    assert _git(repo, "show", "HEAD:pre_dirty.txt").stdout == "base\n"
    assert _git(repo, "show", "HEAD:foreign.txt").stdout == "base\n"
    assert (repo / "pre_dirty.txt").read_text(encoding="utf-8") == "other author\n"


def test_helper_can_commit_a_new_declared_output_without_sweeping_other_dirt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")

    dirty = dirty_paths_before_write(repo, ["new.txt"], label="test-writer")
    assert dirty == frozenset()
    (repo / "tracked.txt").write_text("unrelated\n", encoding="utf-8")
    (repo / "new.txt").write_text("new output\n", encoding="utf-8")
    assert commit_owned_outputs(
        repo,
        ["new.txt"],
        dirty_before=dirty,
        message="add declared output",
        label="test-writer",
    ) == ["new.txt"]
    assert _git(repo, "status", "--short").stdout.splitlines() == [" M tracked.txt"]


def test_helper_refuses_canonical_checkout_on_side_or_detached_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    target = repo / "owned.txt"
    target.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    _git(repo, "commit", "-m", "base")

    _git(repo, "switch", "-c", "side")
    target.write_text("side output\n", encoding="utf-8")
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert commit_owned_outputs(
        repo, ["owned.txt"], dirty_before=(), message="must reject", label="side"
    ) == []
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before
    assert target.read_text(encoding="utf-8") == "side output\n"

    _git(repo, "switch", "main")
    _git(repo, "checkout", "--detach", "HEAD")
    target.write_text("detached output\n", encoding="utf-8")
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert commit_owned_outputs(
        repo, ["owned.txt"], dirty_before=(), message="must reject", label="detached"
    ) == []
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before
    assert target.read_text(encoding="utf-8") == "detached output\n"


def test_helper_git_probe_failure_blocks_the_write(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def fail_probe(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(writer_commit.subprocess, "run", fail_probe)
    dirty = dirty_paths_before_write(repo, ["owned.txt"], label="test-writer")
    assert dirty == frozenset({"owned.txt"})
    assert writable_output_paths(
        repo,
        ["owned.txt"],
        dirty_before=dirty,
        label="test-writer",
    ) == []


def test_helper_refuses_path_staged_after_initial_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    target = repo / "owned.txt"
    target.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    _git(repo, "commit", "-m", "base")

    dirty = dirty_paths_before_write(repo, ["owned.txt"], label="race-writer")
    assert dirty == frozenset()
    target.write_text("foreign staged\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    staged_before = _git(repo, "show", ":owned.txt").stdout
    target.write_text("scheduled output\n", encoding="utf-8")

    assert commit_owned_outputs(
        repo,
        ["owned.txt"],
        dirty_before=dirty,
        message="must not adopt race",
        label="race-writer",
    ) == []
    assert _git(repo, "show", ":owned.txt").stdout == staged_before
    assert target.read_text(encoding="utf-8") == "scheduled output\n"
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "base"


def test_helper_commit_failure_restores_only_owned_index_entry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    target = repo / "owned.txt"
    target.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    _git(repo, "commit", "-m", "base")
    target.write_text("scheduled output\n", encoding="utf-8")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    assert commit_owned_outputs(
        repo,
        ["owned.txt"],
        dirty_before=frozenset(),
        message="blocked by hook",
        label="hook-writer",
    ) == []
    assert _git(repo, "diff", "--cached", "--name-only").stdout == ""
    assert target.read_text(encoding="utf-8") == "scheduled output\n"
