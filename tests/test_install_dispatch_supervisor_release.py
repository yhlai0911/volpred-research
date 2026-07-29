from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import install_dispatch_supervisor_release as installer
from scripts.dispatch_supervisor import release_image

ROOT = Path(__file__).resolve().parents[1]


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
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(b"<plist>immutable</plist>\n")
    plist_destination = tmp_path / "LaunchAgents" / "supervisor.plist"
    plist_destination.parent.mkdir()
    plist_destination.write_bytes(b"<plist>legacy</plist>\n")
    commands: list[list[str]] = []
    loaded = True
    unload_reads_remaining = 1

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, unload_reads_remaining
        commands.append(command)
        if "bootout" in command:
            unload_reads_remaining = 1
            return subprocess.CompletedProcess(command, 0, "", "")
        if "bootstrap" in command:
            loaded = True
            pointer = json.loads(
                (
                    tmp_path / "run" / "current_release.json"
                ).read_text(encoding="utf-8")
            )
            observed = json.loads(state_path.read_text(encoding="utf-8"))
            observed.update(
                {
                    "supervisor_started_at": "2026-07-29T00:01:00+00:00",
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
                (
                    tmp_path / "run" / "current_release.json"
                ).read_text(encoding="utf-8")
            )
            stdout = pointer["stage0_path"]
        return subprocess.CompletedProcess(command, 0, stdout, "")

    result = installer.cutover(
        repo_root=ROOT,
        state_path=state_path,
        run_root=tmp_path / "run",
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
    ]
    receipt = json.loads(
        (
            tmp_path / "run" / "cutover_receipts" / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["release_sha256"] == result["release_sha256"]


def test_cutover_restores_legacy_plist_and_pointer_when_bootstrap_fails(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    original_state = state_path.read_bytes()
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(b"<plist>immutable</plist>\n")
    plist_destination = tmp_path / "LaunchAgents" / "supervisor.plist"
    plist_destination.parent.mkdir()
    legacy = b"<plist>legacy</plist>\n"
    plist_destination.write_bytes(legacy)
    commands: list[list[str]] = []
    bootstrap_calls = 0
    loaded = True

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal bootstrap_calls, loaded
        commands.append(command)
        if "bootout" in command:
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
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(installer.CutoverError, match="bootstrap failed"):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=tmp_path / "run",
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
        (
            tmp_path / "run" / "cutover_receipts" / "latest_rollback.json"
        ).read_text(encoding="utf-8")
    )
    assert rollback["status"] == "rolled_back"
    restored_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert restored_state["current_jobs"] == []
    assert restored_state["phase_z_pending"] == []
    assert restored_state["supervisor_release_id"] is None
    assert restored_state["cutover_quiesce"] is None
    assert restored_state["supervisor_started_at"] != json.loads(original_state)[
        "supervisor_started_at"
    ]
    assert [command[1] for command in commands] == [
        "bootout",
        "print",
        "bootstrap",
        "bootout",
        "bootstrap",
        "print",
    ]


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
    commands: list[list[str]] = []

    def launchctl(
        command: list[str],
        _check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            request["stage0_path"],
            "",
        )

    result = installer.cutover(
        repo_root=ROOT,
        state_path=state_path,
        run_root=run_root,
        plist_source=tmp_path / "unused-source.plist",
        plist_destination=tmp_path / "unused-destination.plist",
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


def test_cutover_quiesce_catches_work_inserted_during_materialization(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands: list[list[str]] = []
    loaded = True
    plist_destination = tmp_path / "destination.plist"
    plist_destination.write_bytes(b"<plist>legacy</plist>\n")

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
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(installer.CutoverError, match="new work appeared"):
        installer.cutover(
            repo_root=ROOT,
            state_path=state_path,
            run_root=tmp_path / "run",
            plist_source=tmp_path / "source.plist",
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
        "bootstrap",
        "print",
    ]
    assert not (tmp_path / "run" / "current_release.json").exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))[
        "cutover_quiesce"
    ] is None


def test_cutover_reports_rollback_failed_when_legacy_bootstrap_fails(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    _state(state_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    plist_source = tmp_path / "source.plist"
    plist_source.write_bytes(b"<plist>immutable</plist>\n")
    plist_destination = tmp_path / "legacy.plist"
    plist_destination.write_bytes(b"<plist>legacy</plist>\n")
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
            run_root=tmp_path / "run",
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=1,
            materialize_fn=_materializer(source),
            launchctl_fn=launchctl,
            sleep_fn=lambda _seconds: None,
        )

    rollback = json.loads(
        (
            tmp_path / "run" / "cutover_receipts" / "latest_rollback.json"
        ).read_text(encoding="utf-8")
    )
    assert rollback["status"] == "rollback_failed"
    assert "legacy bootstrap rc=1" in rollback["rollback_error"]


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
