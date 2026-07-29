from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from scripts.dispatch_supervisor import procutil

HOST_UUID = "92515cc4-ec37-5659-923e-c700da4843a4"
BOOT_UUID = "05699489-50d5-4a6d-b11b-7aa4550f48ca"


class _FakeDarwinCustodyAPI:
    def __init__(
        self,
        *,
        coalition_id: int = 73,
        pids: list[int] | None = None,
        identities: dict[int, tuple[int, int] | None] | None = None,
        failure: Exception | None = None,
        host_uuid: str = HOST_UUID,
        boot_uuid: str = BOOT_UUID,
    ) -> None:
        self.coalition_id = coalition_id
        self.pids = list(pids or [])
        self.identities = dict(identities or {})
        self.failure = failure
        self.saved_host_uuid = host_uuid
        self.saved_boot_uuid = boot_uuid

    def host_uuid(self) -> str:
        if self.failure is not None:
            raise self.failure
        return self.saved_host_uuid

    def boot_session_uuid(self) -> str:
        if self.failure is not None:
            raise self.failure
        return self.saved_boot_uuid

    def resource_coalition_id(self, pid: int) -> int:
        if self.failure is not None:
            raise self.failure
        return self.coalition_id

    def coalition_pids(self, coalition_id: int) -> list[int]:
        if self.failure is not None:
            raise self.failure
        assert coalition_id == self.coalition_id
        return list(self.pids)

    def process_identity(self, pid: int) -> tuple[int, int] | None:
        if self.failure is not None:
            raise self.failure
        return self.identities.get(pid)


def _install_fake_darwin(
    monkeypatch: pytest.MonkeyPatch,
    api: _FakeDarwinCustodyAPI,
) -> None:
    monkeypatch.setattr(procutil.sys, "platform", "darwin")
    monkeypatch.setattr(procutil, "_get_darwin_custody_api", lambda: api)


def test_capture_producer_custody_is_json_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        pids=[101, 102],
        identities={
            101: (1001, 1002),
            102: (1002, 9000),
        },
    )
    _install_fake_darwin(monkeypatch, api)
    monkeypatch.setattr(procutil.os, "getpid", lambda: 101)

    custody = procutil.capture_producer_custody()

    assert custody == {
        "version": 2,
        "host_uuid": HOST_UUID,
        "boot_session_uuid": BOOT_UUID,
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001, 1002],
    }
    assert json.loads(json.dumps(custody)) == custody


def test_capture_producer_custody_fails_closed_at_kernel_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pids = list(range(1, 513))
    api = _FakeDarwinCustodyAPI(
        pids=pids,
        identities={
            pid: (10_000 + pid, 10_000 + pid + 1)
            for pid in pids
        },
    )
    _install_fake_darwin(monkeypatch, api)

    assert procutil.capture_producer_custody() is None


def test_capture_producer_custody_rejects_existing_non_ancestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        pids=[101, 102, 103],
        identities={
            101: (1001, 1002),
            102: (1002, 9000),
            103: (1003, 8000),
        },
    )
    _install_fake_darwin(monkeypatch, api)
    monkeypatch.setattr(procutil.os, "getpid", lambda: 101)

    assert procutil.capture_producer_custody() is None


def test_darwin_cohort_uses_uniqueids_and_ignores_outsider_pgid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        pids=[10, 11, 12, 13],
        identities={
            10: (100, 9000),
            11: (200, 9000),
            12: (300, 100),
            13: None,  # exited or became a zombie after coalition enumeration
        },
    )
    _install_fake_darwin(monkeypatch, api)
    monkeypatch.setattr(procutil.os, "getpid", lambda: 10)
    monkeypatch.setattr(
        procutil,
        "pgid_members_checked",
        lambda _pgid: pytest.fail("Darwin custody must not probe a bare PGID"),
    )

    members = procutil.producer_cohort_members_checked(
        456,
        job_id="job-does-not-enter-the-kernel-probe",
        custody={
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            # Simulate a supervisor restart: current uid=100 was not present in
            # the original capture and is trusted only through the live
            # kernel-verified ancestor chain.
            "trusted_unique_ids": [200],
        },
    )

    assert members == [12]


def test_darwin_complete_custody_includes_trusted_legacy_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        pids=[10, 11, 12],
        identities={
            10: (100, 9000),
            11: (200, 100),
            12: (300, 200),
        },
    )
    _install_fake_darwin(monkeypatch, api)

    assert procutil.producer_custody_all_members_checked(
        {
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100, 200],
        }
    ) == [10, 11, 12]


@pytest.mark.parametrize(
    "custody",
    [
        None,
        {},
        {
            "version": 1,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
        {
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": "73",
            "trusted_unique_ids": [100],
        },
        {
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100, 100],
        },
        {
            "version": 2,
            "host_uuid": HOST_UUID.upper(),
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
    ],
)
def test_darwin_cohort_fails_closed_for_missing_or_malformed_custody(
    monkeypatch: pytest.MonkeyPatch,
    custody: dict[str, object] | None,
) -> None:
    _install_fake_darwin(monkeypatch, _FakeDarwinCustodyAPI())
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda _pgid: [90])

    assert procutil.producer_cohort_members_checked(
        456,
        job_id="job",
        custody=custody,
    ) is None


def test_darwin_cohort_fails_closed_for_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_darwin(
        monkeypatch,
        _FakeDarwinCustodyAPI(failure=OSError("ABI unavailable")),
    )
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda _pgid: [])

    assert procutil.producer_cohort_members_checked(
        456,
        job_id="job",
        custody={
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
    ) is None


def test_darwin_cohort_same_host_new_boot_is_positively_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        boot_uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    _install_fake_darwin(monkeypatch, api)
    monkeypatch.setattr(
        api,
        "coalition_pids",
        lambda _coalition_id: pytest.fail(
            "old-boot coalition id must not be probed after reboot"
        ),
    )

    assert procutil.producer_cohort_members_checked(
        0,
        job_id="old-boot-job",
        custody={
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
    ) == []


def test_darwin_cohort_foreign_host_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        host_uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    _install_fake_darwin(monkeypatch, api)
    monkeypatch.setattr(
        api,
        "coalition_pids",
        lambda _coalition_id: pytest.fail(
            "foreign-host coalition id must not be probed locally"
        ),
    )

    assert procutil.producer_cohort_members_checked(
        0,
        job_id="foreign-host-job",
        custody={
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
    ) is None


def test_non_darwin_cohort_retains_pgid_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(procutil.sys, "platform", "linux")
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda _pgid: [90, 91])

    assert procutil.producer_cohort_members_checked(
        456,
        job_id="job",
        custody=None,
    ) == [90, 91]


def test_kill_producer_cohort_rechecks_uniqueid_before_each_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeDarwinCustodyAPI(
        pids=[12],
        identities={12: (300, 100)},
    )
    _install_fake_darwin(monkeypatch, api)
    snapshots = iter([{12: 300}, {12: 300}, {}])
    monkeypatch.setattr(
        procutil,
        "_unknown_custody_members",
        lambda _custody: next(snapshots),
    )
    monkeypatch.setattr(procutil.time, "sleep", lambda _seconds: None)
    signals: list[tuple[int, int]] = []

    def _send_member(
        _intent: object,
        pid: int,
        signum: int,
        *,
        identity_verifier,
        **_kwargs,
    ) -> str:
        assert identity_verifier(pid)
        signals.append((pid, signum))
        return "sent"

    monkeypatch.setattr(
        procutil.termination,
        "send_member_pid",
        _send_member,
    )
    intent = SimpleNamespace(
        signal_sequence=(procutil.signal.SIGTERM, procutil.signal.SIGKILL),
    )

    assert procutil.kill_producer_cohort(
        {
            "version": 2,
            "host_uuid": HOST_UUID,
            "boot_session_uuid": BOOT_UUID,
            "resource_coalition_id": 73,
            "trusted_unique_ids": [100],
        },
        intent=intent,
        grace_s=0,
    )
    assert signals == [
        (12, procutil.signal.SIGTERM),
        (12, procutil.signal.SIGKILL),
    ]


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Darwin coalition custody integration",
)
def test_live_darwin_custody_tracks_start_new_session_child() -> None:
    custody = procutil.capture_producer_custody()
    if custody is None:
        pytest.skip("test runner already shares a non-empty resource coalition")

    child = subprocess.Popen(
        ["/bin/sleep", "10"],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        members: list[int] | None = None
        while time.monotonic() < deadline:
            members = procutil.producer_cohort_members_checked(
                0,
                job_id=f"custody-live-{os.getpid()}",
                custody=custody,
            )
            if members is not None and child.pid in members:
                break
            time.sleep(0.02)
        assert members is not None
        assert child.pid in members
    finally:
        child.terminate()
        child.wait(timeout=5)
