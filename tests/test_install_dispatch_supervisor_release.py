from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import install_dispatch_supervisor_release as installer
from scripts.dispatch_supervisor import release_image

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _verified_legacy_coalition(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[object]]:
    calls: dict[str, list[object]] = {"capture": [], "members": []}
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }

    def capture(anchor_pid: object) -> dict[str, object]:
        calls["capture"].append(anchor_pid)
        return dict(custody)

    def members(custody: dict[str, object] | None = None) -> list[int]:
        calls["members"].append(custody)
        return []

    monkeypatch.setattr(
        installer.procutil,
        "capture_existing_producer_custody",
        capture,
    )
    monkeypatch.setattr(
        installer.procutil,
        "producer_custody_all_members_checked",
        members,
    )
    return calls


@pytest.fixture(autouse=True)
def _isolated_custody_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[Path]]:
    calls: dict[str, list[Path]] = {"initialize": [], "reconcile": [], "read": []}

    def initialize(
        repo_root: Path,
        *,
        migration_confirmed_quiescent: bool,
    ) -> bool:
        assert migration_confirmed_quiescent is True
        calls["initialize"].append(Path(repo_root))
        return True

    def reconcile(repo_root: Path) -> dict[str, object]:
        calls["reconcile"].append(Path(repo_root))
        return {
            "ok": True,
            "pending_count": 0,
            "released": [],
            "unresolved": [],
        }

    def read(repo_root: Path) -> list[dict[str, object]]:
        calls["read"].append(Path(repo_root))
        return []

    monkeypatch.setattr(
        installer.custody_receipt,
        "initialize_producer_custody_ledger",
        initialize,
    )
    monkeypatch.setattr(
        installer.custody_receipt,
        "reconcile_pending_producer_custodies",
        reconcile,
    )
    monkeypatch.setattr(
        installer.custody_receipt,
        "read_pending_producer_custodies",
        read,
    )
    return calls


@pytest.fixture(autouse=True)
def _isolated_legacy_workspace_drain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, list[object]]:
    calls: dict[str, list[object]] = {"active": [], "record": []}
    monkeypatch.setattr(
        installer.custody_receipt,
        "RECEIPTS_RELPATH",
        tmp_path / "producer_custody_receipts.jsonl",
    )

    def active(repo_root: Path) -> list[dict[str, str]]:
        calls["active"].append(Path(repo_root))
        return [{
            "workspace": "dispatch-slot-1-deadbeef",
            "job_id": "deadbeef" * 4,
            "allocation_receipt_id": "a" * 32,
            "allocated_at": "2026-07-29T00:00:00+00:00",
            "branch": "worktree-dispatch-slot-1-deadbeef",
            "base_sha": "b" * 40,
        }]

    def record(
        repo_root: Path,
        *,
        workspace_generations: list[dict[str, str]],
        cutover_request_id: str,
        cutover_completed_at: str,
        complete_coalition_drained: bool,
        release_commit: str,
    ) -> bool:
        calls["record"].append(
            {
                "repo_root": Path(repo_root),
                "workspace_generations": list(workspace_generations),
                "cutover_request_id": cutover_request_id,
                "cutover_completed_at": cutover_completed_at,
                "complete_coalition_drained": complete_coalition_drained,
                "release_commit": release_commit,
            }
        )
        return True

    monkeypatch.setattr(
        installer.workspace_mod,
        "active_allocated_workspace_generations",
        active,
    )
    monkeypatch.setattr(
        installer.workspace_mod,
        "record_legacy_workspace_producer_drain",
        record,
    )
    return calls


def _plist(
    *,
    stage0_path: str,
    working_directory: Path,
    failover: str = "0",
) -> bytes:
    return plistlib.dumps(
        {
            "Label": installer.LABEL,
            "ProgramArguments": [
                "/opt/homebrew/bin/uv",
                "run",
                "python",
                stage0_path,
            ],
            "WorkingDirectory": str(working_directory),
            "EnvironmentVariables": {
                "VOLPRED_CODEX_FAILOVER": failover,
                "VOLPRED_WRITER_ISOLATION_REQUIRED": "1",
            },
            "RunAtLoad": True,
        },
        fmt=plistlib.FMT_XML,
        sort_keys=True,
    )


def _launchctl_dump(*, plist_payload: bytes, state_value: str = "running") -> str:
    parsed = plistlib.loads(plist_payload)
    arguments = "\n".join(f"\t\t{argument}" for argument in parsed["ProgramArguments"])
    environment = "\n".join(
        f"\t\t{key} => {value}" for key, value in parsed["EnvironmentVariables"].items()
    )
    return (
        f"state = {state_value}\n"
        f"program = {parsed['ProgramArguments'][0]}\n"
        "arguments = {\n"
        f"{arguments}\n"
        "}\n"
        f"working directory = {parsed['WorkingDirectory']}\n"
        "environment = {\n"
        f"{environment}\n"
        "}\n"
    )


def test_direct_file_entrypoint_loads_package_outside_repo_cwd(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_dispatch_supervisor_release.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "immutable" in completed.stdout.lower()


def _state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "supervisor_started_at": "2026-07-29T00:00:00+00:00",
                "supervisor_pid": 777,
                "current_jobs": [],
                "current_job": None,
                "phase_z_pending": [],
                "supervisor_release_id": None,
                "supervisor_release_sha256": None,
                "supervisor_release_commit": None,
                "supervisor_bootstrap_sha256": None,
                "cutover_quiesce": None,
            }
        ),
        encoding="utf-8",
    )


def _materializer(source: Path):
    def materialize(*, repo_root: Path, run_root: Path) -> dict[str, str]:
        return release_image.materialize(
            repo_root=repo_root,
            run_root=run_root,
            source_roots=(source,),
        )

    return materialize


def test_cutover_installs_launchd_job_and_reads_back_exact_release(
    tmp_path: Path,
    _verified_legacy_coalition: dict[str, list[object]],
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    immutable = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
    )
    legacy = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
        failover="1",
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(immutable)
    plist_destination = tmp_path / "LaunchAgents" / "supervisor.plist"
    plist_destination.parent.mkdir()
    plist_destination.write_bytes(legacy)
    commands: list[list[str]] = []
    loaded = True
    unload_reads_remaining = 1
    bootstrapped = False
    heartbeat_counter = 1

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, unload_reads_remaining, bootstrapped, heartbeat_counter
        commands.append(command)
        if "bootout" in command:
            intent = json.loads(
                (run_root / "cutover_receipts" / "in_progress.json").read_text(
                    encoding="utf-8"
                )
            )
            pointer = json.loads(
                (run_root / release_image.POINTER_NAME).read_text(encoding="utf-8")
            )
            assert intent["status"] == "mutation_armed"
            assert intent["request_id"] == pointer["request_id"]
            assert pointer["activation_state"] == "candidate"
            unload_reads_remaining = 1
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            loaded = True
            bootstrapped = True
            pointer = json.loads(
                (tmp_path / "run" / "current_release.json").read_text(encoding="utf-8")
            )
            observed = json.loads(state_path.read_text(encoding="utf-8"))
            observed.update(
                {
                    "supervisor_started_at": "2026-07-29T00:01:00+00:00",
                    "last_heartbeat_at": "2026-07-29T00:01:01+00:00",
                    "supervisor_release_id": pointer["request_id"],
                    "supervisor_release_sha256": pointer["release_sha256"],
                    "supervisor_release_commit": pointer["release_commit"],
                    "supervisor_bootstrap_sha256": pointer["bootstrap_sha256"],
                }
            )
            state_path.write_text(json.dumps(observed), encoding="utf-8")
        stdout = ""
        if "print" in command:
            if unload_reads_remaining:
                unload_reads_remaining -= 1
                if unload_reads_remaining == 0:
                    loaded = False
                return subprocess.CompletedProcess(command, 0, "still loaded", "")
            if not loaded:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    "could not find service",
                )
            pointer = json.loads(
                (tmp_path / "run" / "current_release.json").read_text(encoding="utf-8")
            )
            if bootstrapped:
                heartbeat_counter += 1
                observed = json.loads(state_path.read_text(encoding="utf-8"))
                observed["last_heartbeat_at"] = (
                    f"2026-07-29T00:01:{heartbeat_counter:02d}+00:00"
                )
                state_path.write_text(json.dumps(observed), encoding="utf-8")
            assert pointer["stage0_path"] == release["stage0_path"]
            stdout = _launchctl_dump(plist_payload=immutable)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    result = installer.cutover(
        repo_root=ROOT,
        state_path=state_path,
        run_root=run_root,
        plist_source=plist_source,
        plist_destination=plist_destination,
        timeout_s=1,
        materialize_fn=_materializer(source),
        launchctl_fn=launchctl,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "completed"
    assert plist_destination.read_bytes() == plist_source.read_bytes()
    assert [command[1] for command in commands] == [
        "bootout",
        "print",
        "print",
        "bootstrap",
        "print",
        "print",
    ]
    receipt = json.loads(
        (tmp_path / "run" / "cutover_receipts" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["release_sha256"] == result["release_sha256"]
    terminal_intent = json.loads(
        (tmp_path / "run" / "cutover_receipts" / "in_progress.json").read_text(
            encoding="utf-8"
        )
    )
    assert terminal_intent["status"] == "completed_verified"
    assert _verified_legacy_coalition["capture"] == [777]
    assert len(_verified_legacy_coalition["members"]) == 1
    assert _verified_legacy_coalition["members"][0]["trusted_unique_ids"] == [1001]


def test_cutover_restores_legacy_plist_and_pointer_when_bootstrap_fails(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    original_state = state_path.read_bytes()
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    immutable = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(immutable)
    plist_destination = tmp_path / "LaunchAgents" / "supervisor.plist"
    plist_destination.parent.mkdir()
    legacy = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
        failover="1",
    )
    plist_destination.write_bytes(legacy)
    commands: list[list[str]] = []
    bootstrap_calls = 0
    loaded = True
    rollback_bootout_observation: dict[str, object] = {}

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal bootstrap_calls, loaded
        commands.append(command)
        if "bootout" in command:
            if bootstrap_calls == 1:
                rollback_bootout_observation["pointer"] = json.loads(
                    (run_root / release_image.POINTER_NAME).read_text(encoding="utf-8")
                )
                rollback_bootout_observation["plist"] = plist_destination.read_bytes()
            loaded = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            bootstrap_calls += 1
            if bootstrap_calls == 1:
                return subprocess.CompletedProcess(command, 1, "", "bad plist")
            loaded = True
            observed = json.loads(state_path.read_text(encoding="utf-8"))
            observed.update(
                {
                    "supervisor_started_at": "2026-07-29T00:02:00+00:00",
                    "last_heartbeat_at": "2026-07-29T00:02:01+00:00",
                    "supervisor_release_id": None,
                    "supervisor_release_sha256": None,
                    "supervisor_release_commit": None,
                    "supervisor_bootstrap_sha256": None,
                }
            )
            state_path.write_text(json.dumps(observed), encoding="utf-8")
        if "print" in command and not loaded:
            return subprocess.CompletedProcess(command, 1, "", "not loaded")
        if "print" in command:
            return subprocess.CompletedProcess(
                command, 0, _launchctl_dump(plist_payload=legacy), ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(installer.CutoverError, match="bootstrap failed"):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=1,
            materialize_fn=_materializer(source),
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    assert plist_destination.read_bytes() == legacy
    assert not (tmp_path / "run" / "current_release.json").exists()
    rollback = json.loads(
        (tmp_path / "run" / "cutover_receipts" / "latest_rollback.json").read_text(
            encoding="utf-8"
        )
    )
    assert rollback["status"] == "rolled_back"
    restored_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert restored_state["current_jobs"] == []
    assert restored_state["phase_z_pending"] == []
    assert restored_state["supervisor_release_id"] is None
    assert restored_state["cutover_quiesce"] is None
    assert (
        restored_state["supervisor_started_at"]
        != json.loads(original_state)["supervisor_started_at"]
    )
    assert [command[1] for command in commands] == [
        "bootout",
        "print",
        "bootstrap",
        "bootout",
        "print",
        "bootstrap",
        "print",
    ]
    assert rollback_bootout_observation["pointer"]["activation_state"] == ("candidate")
    assert rollback_bootout_observation["plist"] == immutable


def test_idempotent_success_requires_live_stage0_launchctl_readback(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    request = {"request_id": "f" * 64, **release}
    release_image.install_initial_stable(run_root=run_root, request=request)
    observed = json.loads(state_path.read_text(encoding="utf-8"))
    observed.update(
        {
            "supervisor_release_id": request["request_id"],
            "supervisor_release_sha256": request["release_sha256"],
            "supervisor_release_commit": request["release_commit"],
            "supervisor_bootstrap_sha256": request["bootstrap_sha256"],
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        }
    )
    state_path.write_text(json.dumps(observed), encoding="utf-8")
    expected_plist = _plist(
        stage0_path=request["stage0_path"],
        working_directory=ROOT,
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(expected_plist)
    plist_destination = tmp_path / "destination.plist"
    plist_destination.write_bytes(expected_plist)
    commands: list[list[str]] = []

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            _launchctl_dump(plist_payload=expected_plist),
            "",
        )

    result = installer.cutover(
        repo_root=ROOT,
        state_path=state_path,
        run_root=run_root,
        plist_source=plist_source,
        plist_destination=plist_destination,
        timeout_s=1,
        materialize_fn=_materializer(source),
        launchctl_fn=launchctl,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "already_cut_over"
    assert commands == [
        [
            "launchctl",
            "print",
            f"gui/{installer.os.getuid()}/{installer.LABEL}",
        ]
    ]


def test_existing_cutover_upgrades_when_materialized_release_drifted(
    tmp_path: Path,
    _isolated_custody_ledger: dict[str, list[Path]],
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    worker = source / "worker.py"
    worker.write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    old_release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    old_request = {"request_id": "a" * 64, **old_release}
    release_image.install_initial_stable(
        run_root=run_root,
        request=old_request,
    )
    worker.write_text("VALUE = 2\n", encoding="utf-8")
    new_release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    assert new_release["release_sha256"] != old_release["release_sha256"]

    observed = json.loads(state_path.read_text(encoding="utf-8"))
    observed.update(
        {
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
            "supervisor_release_id": old_request["request_id"],
            "supervisor_release_sha256": old_request["release_sha256"],
            "supervisor_release_commit": old_request["release_commit"],
            "supervisor_bootstrap_sha256": old_request["bootstrap_sha256"],
        }
    )
    state_path.write_text(json.dumps(observed), encoding="utf-8")

    expected_plist = _plist(
        stage0_path=new_release["stage0_path"],
        working_directory=ROOT,
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(expected_plist)
    plist_destination = tmp_path / "installed.plist"
    plist_destination.write_bytes(expected_plist)
    commands: list[str] = []
    loaded = True
    bootstrapped = False
    heartbeat_counter = 0

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, bootstrapped, heartbeat_counter
        action = command[1]
        commands.append(action)
        if action == "bootout":
            loaded = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if action == "bootstrap":
            loaded = True
            bootstrapped = True
            pointer = json.loads(
                (run_root / release_image.POINTER_NAME).read_text(encoding="utf-8")
            )
            current = json.loads(state_path.read_text(encoding="utf-8"))
            current.update(
                {
                    "supervisor_started_at": "2026-07-29T01:00:00+00:00",
                    "last_heartbeat_at": "2026-07-29T01:00:01+00:00",
                    "supervisor_release_id": pointer["request_id"],
                    "supervisor_release_sha256": pointer["release_sha256"],
                    "supervisor_release_commit": pointer["release_commit"],
                    "supervisor_bootstrap_sha256": pointer["bootstrap_sha256"],
                }
            )
            state_path.write_text(json.dumps(current), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        if action == "print":
            if not loaded:
                return subprocess.CompletedProcess(
                    command, 1, "", "could not find service"
                )
            if bootstrapped:
                heartbeat_counter += 1
                current = json.loads(state_path.read_text(encoding="utf-8"))
                current["last_heartbeat_at"] = (
                    f"2026-07-29T01:00:{heartbeat_counter + 1:02d}+00:00"
                )
                state_path.write_text(json.dumps(current), encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                0,
                _launchctl_dump(plist_payload=expected_plist),
                "",
            )
        raise AssertionError(command)

    result = installer.cutover(
        repo_root=ROOT,
        state_path=state_path,
        run_root=run_root,
        plist_source=plist_source,
        plist_destination=plist_destination,
        timeout_s=1,
        materialize_fn=_materializer(source),
        launchctl_fn=launchctl,
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "completed"
    assert result["release_sha256"] == new_release["release_sha256"]
    assert "bootout" in commands
    pointer = json.loads(
        (run_root / release_image.POINTER_NAME).read_text(encoding="utf-8")
    )
    assert pointer["activation_state"] == "stable"
    assert pointer["release_sha256"] == new_release["release_sha256"]
    assert _isolated_custody_ledger["initialize"] == [ROOT]
    assert _isolated_custody_ledger["reconcile"] == [ROOT]


def test_invalid_failover_plist_is_rejected_before_any_mutation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(
        _plist(
            stage0_path=release["stage0_path"],
            working_directory=ROOT,
            failover="1",
        )
    )
    commands: list[list[str]] = []

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        raise AssertionError("launchctl must not run for an invalid plist")

    with pytest.raises(
        installer.CutoverError,
        match="VOLPRED_CODEX_FAILOVER=0",
    ):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=tmp_path / "destination.plist",
            timeout_s=1,
            materialize_fn=_materializer(source),
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    assert commands == []
    assert not (run_root / release_image.POINTER_NAME).exists()
    observed = json.loads(state_path.read_text(encoding="utf-8"))
    assert observed["cutover_quiesce"] is None
    assert observed["auth_blocked"] is False


def test_launchd_resource_coalition_id_is_exactly_parsed() -> None:
    status = subprocess.CompletedProcess(
        ["launchctl", "print", "gui/501/com.volpred.dispatch-supervisor"],
        0,
        """
        domain = gui/501 [100020]
        resource coalition = {
            ID = 59071
            type = resource
        }
        jetsam coalition = {
            ID = 59072
        }
        """,
        "",
    )

    assert installer._launchd_resource_coalition_id(status) == 59071


def test_plist_must_match_the_materialized_release_commit(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    fixture_release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(
        _plist(
            stage0_path=fixture_release["stage0_path"],
            working_directory=ROOT,
        )
    )

    def materialize(*, repo_root: Path, run_root: Path) -> dict[str, str]:
        release = _materializer(source)(
            repo_root=repo_root,
            run_root=run_root,
        )
        release["release_commit"] = head
        return release

    with pytest.raises(
        installer.CutoverError,
        match="differs from the immutable release commit",
    ):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=tmp_path / "destination.plist",
            timeout_s=1,
            materialize_fn=materialize,
            launchctl_fn=lambda command, check: subprocess.CompletedProcess(
                command, 0, "", ""
            ),
            sleep_fn=lambda _seconds: None,
        )

    assert not (run_root / release_image.POINTER_NAME).exists()
    observed = json.loads(state_path.read_text(encoding="utf-8"))
    assert observed["cutover_quiesce"] is None
    assert observed["auth_blocked"] is False


def test_release_is_not_ready_until_heartbeat_advances_after_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    expected_plist = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(expected_plist)
    plist_destination = tmp_path / "destination.plist"
    loaded = True
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.1
        return clock

    monkeypatch.setattr(installer.time, "monotonic", monotonic)

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded
        if "bootout" in command:
            loaded = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            loaded = True
            pointer = json.loads(
                (run_root / release_image.POINTER_NAME).read_text(encoding="utf-8")
            )
            observed = json.loads(state_path.read_text(encoding="utf-8"))
            observed.update(
                {
                    "supervisor_started_at": "2026-07-29T02:00:00+00:00",
                    "last_heartbeat_at": "2026-07-29T02:00:01+00:00",
                    "supervisor_release_id": pointer["request_id"],
                    "supervisor_release_sha256": pointer["release_sha256"],
                    "supervisor_release_commit": pointer["release_commit"],
                    "supervisor_bootstrap_sha256": pointer["bootstrap_sha256"],
                }
            )
            state_path.write_text(json.dumps(observed), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        if "print" in command and not loaded:
            return subprocess.CompletedProcess(command, 1, "", "could not find service")
        if "print" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                _launchctl_dump(plist_payload=expected_plist),
                "",
            )
        raise AssertionError(command)

    with pytest.raises(
        installer.CutoverError,
        match="post-startup heartbeat",
    ):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=1,
            materialize_fn=_materializer(source),
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    assert not (run_root / release_image.POINTER_NAME).exists()
    assert not plist_destination.exists()
    observed = json.loads(state_path.read_text(encoding="utf-8"))
    assert observed["cutover_quiesce"] is None
    assert observed["auth_blocked"] is False


def test_cutover_quiesce_catches_work_inserted_during_materialization(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    immutable = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
    )
    legacy = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
        failover="1",
    )
    commands: list[list[str]] = []
    loaded = True
    plist_destination = tmp_path / "destination.plist"
    plist_destination.write_bytes(legacy)
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(immutable)

    def materialize(*, repo_root: Path, run_root: Path) -> dict[str, str]:
        release = release_image.materialize(
            repo_root=repo_root,
            run_root=run_root,
            source_roots=(source,),
        )
        observed = json.loads(state_path.read_text(encoding="utf-8"))
        observed["current_jobs"] = [{"job_id": "raced-work", "slot_id": 1}]
        observed["current_job"] = observed["current_jobs"][0]
        state_path.write_text(json.dumps(observed), encoding="utf-8")
        return release

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded
        commands.append(command)
        if "bootout" in command:
            loaded = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            loaded = True
            observed = json.loads(state_path.read_text(encoding="utf-8"))
            observed.update(
                {
                    "supervisor_started_at": "2026-07-29T00:03:00+00:00",
                    "last_heartbeat_at": "2026-07-29T00:03:01+00:00",
                    "supervisor_release_id": None,
                    "supervisor_release_sha256": None,
                    "supervisor_release_commit": None,
                    "supervisor_bootstrap_sha256": None,
                }
            )
            state_path.write_text(json.dumps(observed), encoding="utf-8")
        if "print" in command and not loaded:
            return subprocess.CompletedProcess(command, 1, "", "not loaded")
        if "print" in command:
            return subprocess.CompletedProcess(
                command, 0, _launchctl_dump(plist_payload=legacy), ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(installer.CutoverError, match="new work appeared"):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=1,
            materialize_fn=materialize,
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    assert [command[1] for command in commands] == [
        "bootout",
        "print",
        "bootout",
        "print",
        "bootstrap",
        "print",
    ]
    assert not (tmp_path / "run" / "current_release.json").exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["cutover_quiesce"] is None


def test_cutover_reports_rollback_failed_when_legacy_bootstrap_fails(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    release = _materializer(source)(repo_root=ROOT, run_root=run_root)
    immutable = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
    )
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(immutable)
    plist_destination = tmp_path / "legacy.plist"
    legacy = _plist(
        stage0_path=release["stage0_path"],
        working_directory=ROOT,
        failover="1",
    )
    plist_destination.write_bytes(legacy)
    bootstrap_calls = 0
    loaded = True

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal bootstrap_calls, loaded
        if "bootout" in command:
            loaded = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            bootstrap_calls += 1
            detail = "new failed" if bootstrap_calls == 1 else "legacy failed"
            return subprocess.CompletedProcess(command, 1, "", detail)
        if "print" in command and not loaded:
            return subprocess.CompletedProcess(command, 1, "", "not loaded")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(
        installer.CutoverError,
        match="rollback failed: legacy bootstrap rc=1",
    ):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=1,
            materialize_fn=_materializer(source),
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    rollback = json.loads(
        (tmp_path / "run" / "cutover_receipts" / "latest_rollback.json").read_text(
            encoding="utf-8"
        )
    )
    assert rollback["status"] == "rollback_failed"
    assert "legacy bootstrap rc=1" in rollback["rollback_error"]
    retained = json.loads(state_path.read_text(encoding="utf-8"))
    assert retained["auth_blocked"] is True
    assert retained["cutover_quiesce"] is not None


def test_cutover_quiesce_mechanically_fences_new_fire_reservations(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    quiesce = installer.state.begin_cutover_quiesce(
        reason="test-fence",
        path=state_path,
    )
    assert installer.state.read_state(state_path)["auth_blocked"] is True

    with pytest.raises(RuntimeError, match="cutover quiesce"):
        installer.state.reserve_fire(
            schedule_id="hourly_dispatch",
            attempt=1,
            model="test",
            log_path=str(tmp_path / "worker.log"),
            path=state_path,
        )

    assert installer.state.end_cutover_quiesce(
        token=quiesce["token"],
        path=state_path,
    )
    assert installer.state.read_state(state_path)["auth_blocked"] is False


def test_expired_cutover_fence_restores_legacy_auth_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    installer.state.begin_cutover_quiesce(
        reason="expiry-test",
        path=state_path,
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["cutover_quiesce"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    handle = installer.state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="test",
        log_path=str(tmp_path / "worker.log"),
        path=state_path,
    )

    observed = installer.state.read_state(state_path)
    assert handle.job_id
    assert observed["cutover_quiesce"] is None
    assert observed["auth_blocked"] is False
