from __future__ import annotations

import json
import os
import stat
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import deferred_reload, release_image

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "reload_dispatch_supervisor.sh"
BOOT = "2026-07-29T02:00:00+00:00"
NEXT_BOOT = "2026-07-29T02:05:00+00:00"
NOW = datetime(2026, 7, 29, 2, 1, tzinfo=UTC)


def _state(
    path: Path,
    *,
    boot: str = BOOT,
    jobs: list[dict] | None = None,
    pending: list[dict] | None = None,
    release: dict | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "supervisor_started_at": boot,
                "current_jobs": jobs or [],
                "current_job": (jobs or [None])[0],
                "phase_z_pending": pending or [],
                "supervisor_release_id": (
                    release.get("request_id") if release else None
                ),
                "supervisor_release_sha256": (
                    release.get("release_sha256") if release else None
                ),
                "supervisor_release_commit": (
                    release.get("release_commit") if release else None
                ),
                "supervisor_bootstrap_sha256": (
                    release.get("bootstrap_sha256") if release else None
                ),
            }
        ),
        encoding="utf-8",
    )


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "worker.py").write_text("VERSION = 1\n", encoding="utf-8")
    return root


def test_wrapper_defer_survives_caller_exit_without_background_waiter(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path, jobs=[{"job_id": "busy"}])

    result = subprocess.run(
        [
            "bash",
            str(WRAPPER),
            "--defer",
            "--reason",
            "test-parent-teardown",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "DISPATCH_STATE_PATH": str(state_path),
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(request_root),
            "VOLPRED_DEFERRED_RELOAD_TEST_SOURCE_ROOTS": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Waiter detached" not in result.stdout
    assert "immutable release request" in result.stdout
    active = json.loads((request_root / "active.json").read_text(encoding="utf-8"))
    assert active["reason"] == "test-parent-teardown"
    assert active["state"] == "requested"


def test_wrapper_default_deploy_arms_immutable_release_instead_of_direct_signal(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)

    result = subprocess.run(
        ["bash", str(WRAPPER), "--reason", "default-immutable-deploy"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "DISPATCH_STATE_PATH": str(state_path),
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(request_root),
            "VOLPRED_DEFERRED_RELOAD_TEST_SOURCE_ROOTS": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "immutable release request" in result.stdout
    assert "durable SIGTERM" not in result.stdout
    active = json.loads((request_root / "active.json").read_text(encoding="utf-8"))
    assert active["reason"] == "default-immutable-deploy"


def test_duplicate_request_coalesces_to_one_durable_identity(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)

    first = deferred_reload.arm(
        reason="same-deploy",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        requested_by_pid=101,
    )
    second = deferred_reload.arm(
        reason="same-deploy",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        requested_by_pid=202,
    )

    assert first["created"] is True
    assert second == {
        **first,
        "created": False,
        "coalesced": True,
    }
    assert len(list((request_root / "receipts").glob("*.json"))) == 0


def test_scheduler_admission_gate_observes_validated_active_request(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)

    deferred_reload.arm(
        reason="admission-drain",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )

    assert deferred_reload.active_request_pending(root=request_root) is True
    with deferred_reload.admission_gate(root=request_root) as admission_open:
        assert admission_open is False


def test_scheduler_admission_gate_fails_closed_on_malformed_request(
    tmp_path: Path,
) -> None:
    request_root = tmp_path / "reload-request"
    request_root.mkdir(mode=0o700)
    active = request_root / "active.json"
    active.write_text("{not-json", encoding="utf-8")
    active.chmod(0o600)

    with pytest.raises(
        deferred_reload.DeferredReloadError,
        match="active request is unreadable",
    ):
        deferred_reload.active_request_pending(root=request_root)

    with pytest.raises(
        deferred_reload.DeferredReloadError,
        match="active request is unreadable",
    ):
        with deferred_reload.admission_gate(root=request_root):
            pytest.fail("malformed reload state must not open admission")


@pytest.mark.parametrize(
    ("jobs", "pending"),
    [
        ([{"job_id": "worker"}], []),
        ([], [{"cohort_id": "closeout"}]),
        ([{"job_id": "worker"}], [{"cohort_id": "closeout"}]),
    ],
)
def test_request_waits_for_worker_and_closeout_drain(
    tmp_path: Path,
    jobs: list[dict],
    pending: list[dict],
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path, jobs=jobs, pending=pending)
    deferred_reload.arm(
        reason="drain-first",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    calls: list[dict] = []

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=calls.append,
    )

    assert outcome["action"] == "deferred_in_flight"
    assert outcome["active_count"] == len(jobs) + len(pending)
    assert calls == []
    assert (request_root / "active.json").is_file()


def test_canonical_source_edit_cannot_change_pinned_release_loaded_by_fresh_boot(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="exact-bytes",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    (source_root / "worker.py").write_text("VERSION = 2\n", encoding="utf-8")
    first = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: None,
    )
    _state(state_path, boot=NEXT_BOOT, release=request)
    second = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: pytest.fail("fresh boot only acknowledges"),
    )

    assert first["action"] == "reload_requested"
    assert second["action"] == "completed"
    with zipfile.ZipFile(request["release_archive"]) as archive:
        pinned = archive.read("fixture_roots/0/worker.py")
    assert pinned == b"VERSION = 1\n"
    assert (source_root / "worker.py").read_bytes() == b"VERSION = 2\n"


def test_idle_request_arms_exactly_one_reload_signal(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="one-signal",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    calls: list[dict] = []

    first = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=calls.append,
    )
    second = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=calls.append,
    )

    assert first["action"] == "reload_requested"
    assert second["action"] == "signal_already_armed"
    assert [call["request_id"] for call in calls] == [request["request_id"]]
    active = json.loads((request_root / "active.json").read_text(encoding="utf-8"))
    assert active["state"] == "signal_armed"


def test_fresh_boot_acknowledges_request_and_removes_active_pointer(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="boot-cas",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    calls: list[dict] = []
    deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=calls.append,
    )
    _state(state_path, boot=NEXT_BOOT, release=request)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=calls.append,
    )

    assert outcome["action"] == "completed"
    assert not (request_root / "active.json").exists()
    receipt_path = request_root / "receipts" / f"{request['request_id']}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["state"] == "completed"
    assert receipt["observed_supervisor_started_at"] == NEXT_BOOT
    assert receipt["source_sha256"] == request["source_sha256"]
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    pointer = json.loads(
        (request_root / "current_release.json").read_text(encoding="utf-8")
    )
    assert pointer["activation_state"] == "stable"
    assert "previous_release" not in pointer


def test_activation_crash_before_pointer_is_rebased_to_replacement_boot(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="crash-before-pointer",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    active_path = request_root / "active.json"
    active = {**request, "state": "activating"}
    active.pop("created", None)
    deferred_reload._atomic_replace_json(active_path, active)
    _state(state_path, boot=NEXT_BOOT)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: pytest.fail("recovery must not signal yet"),
    )

    assert outcome["action"] == "activation_recovered"
    recovered = json.loads(active_path.read_text(encoding="utf-8"))
    assert recovered["state"] == "requested"
    assert recovered["expected_supervisor_started_at"] == NEXT_BOOT
    assert not (request_root / "current_release.json").exists()


def test_activation_crash_after_pointer_is_acknowledged_by_candidate_boot(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="crash-after-pointer",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    active_path = request_root / "active.json"
    active = {**request, "state": "activating"}
    active.pop("created", None)
    deferred_reload._atomic_replace_json(active_path, active)
    release_image.activate(run_root=request_root, request=active)
    _state(state_path, boot=NEXT_BOOT, release=request)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: pytest.fail("candidate boot only acknowledges"),
    )

    assert outcome["action"] == "completed"
    pointer = json.loads(
        (request_root / "current_release.json").read_text(encoding="utf-8")
    )
    assert pointer["activation_state"] == "stable"


def test_crash_after_promotion_replays_terminal_cleanup_idempotently(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="crash-after-promotion",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: None,
    )
    _state(state_path, boot=NEXT_BOOT, release=request)
    release_image.promote(run_root=request_root, request=request)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: pytest.fail("promotion replay must not signal"),
    )

    assert outcome["action"] == "completed"
    assert not (request_root / "active.json").exists()
    receipt = json.loads(
        (
            request_root / "receipts" / f"{request['request_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "completed"


def test_fresh_boot_acknowledges_signal_even_after_original_wait_deadline(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="late-boot-ack",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        max_wait_s=1,
    )
    deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: None,
    )
    _state(state_path, boot=NEXT_BOOT, release=request)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW + timedelta(seconds=2),
        reload_fn=lambda _request: pytest.fail("fresh boot must only acknowledge"),
    )

    assert outcome["action"] == "completed"
    receipt = json.loads(
        (
            request_root / "receipts" / f"{request['request_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "completed"
    assert not (request_root / "active.json").exists()


def test_new_boot_without_signal_arm_is_rejected_as_stale_request(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="stale-boot",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    _state(state_path, boot=NEXT_BOOT)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        reload_fn=lambda _request: pytest.fail("stale request must not signal"),
    )

    assert outcome["action"] == "rejected_boot_drift"
    receipt = json.loads(
        (
            request_root / "receipts" / f"{request['request_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "rejected_boot_drift"


def test_expired_request_times_out_without_signalling(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path, jobs=[{"job_id": "busy"}])
    request = deferred_reload.arm(
        reason="bounded-wait",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        max_wait_s=1,
    )

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW.replace(second=2),
        reload_fn=lambda _request: pytest.fail("expired request must not signal"),
    )

    assert outcome["action"] == "timed_out"
    receipt = json.loads(
        (
            request_root / "receipts" / f"{request['request_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "timed_out"
    assert not (request_root / "active.json").exists()


def test_terminal_intent_can_be_retried_as_a_new_attempt_without_wedging(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path, jobs=[{"job_id": "busy"}])
    first = deferred_reload.arm(
        reason="retry-after-timeout",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        requested_by_pid=101,
        max_wait_s=1,
    )
    deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW + timedelta(seconds=2),
        reload_fn=lambda _request: pytest.fail("expired request must not signal"),
    )

    retry = deferred_reload.arm(
        reason="retry-after-timeout",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW + timedelta(seconds=3),
        requested_by_pid=202,
        max_wait_s=60,
    )
    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW + timedelta(seconds=3),
        reload_fn=lambda _request: pytest.fail("busy retry must keep waiting"),
    )

    assert retry["intent_id"] == first["intent_id"]
    assert retry["request_id"] != first["request_id"]
    assert outcome["action"] == "deferred_in_flight"
    assert json.loads(
        (request_root / "active.json").read_text(encoding="utf-8")
    )["request_id"] == retry["request_id"]


def test_terminal_receipt_replay_clears_active_after_crash_window(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path, jobs=[{"job_id": "busy"}])
    request = deferred_reload.arm(
        reason="terminal-crash-replay",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
        max_wait_s=1,
    )
    receipt_path = request_root / "receipts" / f"{request['request_id']}.json"
    receipt = {
        **{key: value for key, value in request.items() if key != "created"},
        "state": "timed_out",
        "terminal_at": (NOW + timedelta(seconds=2)).isoformat(),
        "observed_supervisor_started_at": BOOT,
        "observed_source_sha256": request["source_sha256"],
    }
    deferred_reload._write_once_json(receipt_path, receipt)

    outcome = deferred_reload.process(
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW + timedelta(seconds=3),
        reload_fn=lambda _request: pytest.fail("terminal replay must not signal"),
    )

    assert outcome["action"] == "timed_out"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert not (request_root / "active.json").exists()


def test_reload_failure_is_terminal_and_does_not_leave_retryable_intent(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request = deferred_reload.arm(
        reason="failed-signal",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )

    with pytest.raises(RuntimeError, match="cannot signal"):
        deferred_reload.process(
            state_path=state_path,
            root=request_root,
            source_roots=(source_root,),
            now=NOW,
            reload_fn=lambda _request: (_ for _ in ()).throw(
                RuntimeError("cannot signal")
            ),
        )

    receipt = json.loads(
        (
            request_root / "receipts" / f"{request['request_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "signal_failed"
    assert "cannot signal" in receipt["error"]
    assert not (request_root / "active.json").exists()
    assert not (request_root / "current_release.json").exists()


def test_malformed_active_request_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    request_root.mkdir(mode=0o700)
    (request_root / "receipts").mkdir(mode=0o700)
    active = request_root / "active.json"
    active.write_text('{"state":"requested"}\n', encoding="utf-8")
    active.chmod(0o600)

    with pytest.raises(deferred_reload.DeferredReloadError, match="missing fields"):
        deferred_reload.process(
            state_path=state_path,
            root=request_root,
            source_roots=(source_root,),
            now=NOW,
            reload_fn=lambda _request: pytest.fail("malformed request must not signal"),
        )


def test_missing_required_field_with_extra_field_still_fails_closed(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    request_root = tmp_path / "reload-request"
    source_root = _source(tmp_path)
    _state(state_path)
    deferred_reload.arm(
        reason="malformed-plus-extra",
        state_path=state_path,
        root=request_root,
        source_roots=(source_root,),
        now=NOW,
    )
    active_path = request_root / "active.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    del active["reason"]
    active["unexpected"] = "must-not-mask-missing"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    active_path.chmod(0o600)

    with pytest.raises(deferred_reload.DeferredReloadError, match="missing fields"):
        deferred_reload.process(
            state_path=state_path,
            root=request_root,
            source_roots=(source_root,),
            now=NOW,
            reload_fn=lambda _request: pytest.fail("malformed request must not signal"),
        )


def test_health_loop_is_the_only_runtime_waiter() -> None:
    import inspect

    from scripts.dispatch_supervisor import health

    source = inspect.getsource(health.health_loop)
    assert "deferred_reload.process" in source
    assert "nohup" not in WRAPPER.read_text(encoding="utf-8")
