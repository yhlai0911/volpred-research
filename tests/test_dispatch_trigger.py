from __future__ import annotations

import asyncio
import inspect
import json
import os
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import supervisor, trigger


def _short_socket_path() -> Path:
    # macOS limits AF_UNIX paths to roughly 104 bytes; pytest's tmp_path is
    # intentionally descriptive and can exceed that before the filename.
    return Path("/tmp") / f"vpd-trigger-{uuid.uuid4().hex[:12]}.sock"


async def _wait_for_socket(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"trigger socket was not created: {path}")


def test_trigger_round_trip_runs_background_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    lock_path = tmp_path / "dispatch.lock"
    state_path = tmp_path / "state.json"
    schedules_path = tmp_path / "schedules.json"
    schedules_path.write_text("{}", encoding="utf-8")
    calls: list[dict] = []

    monkeypatch.setattr(
        trigger.scheduler,
        "load_cron_expr",
        lambda **_kwargs: "7 * * * *",
    )

    async def fake_tick(**kwargs):
        calls.append(kwargs)
        return {"action": "launched", "job_id": "job-1"}

    monkeypatch.setattr(trigger.scheduler, "_tick_once", fake_tick)

    async def run() -> dict:
        server = asyncio.create_task(
            trigger.serve_forever(
                socket_path=socket_path,
                lock_path=lock_path,
                state_path=state_path,
                schedules_path=schedules_path,
                prompt_path=tmp_path / "prompt.md",
                log_path=tmp_path / "worker.log",
                repo_root=tmp_path,
            )
        )
        try:
            await _wait_for_socket(socket_path)
            return await trigger.request_tick(
                socket_path=socket_path,
                reason="test-tick",
            )
        finally:
            server.cancel()
            with suppress(asyncio.CancelledError):
                await server

    response = asyncio.run(run())

    assert response == {
        "ok": True,
        "reason": "test-tick",
        "decision": {"action": "launched", "job_id": "job-1"},
    }
    assert len(calls) == 1
    assert calls[0]["background"] is True
    assert calls[0]["cron_expr"] == "7 * * * *"
    assert not socket_path.exists()


def test_trigger_reconciles_completed_tick_after_ack_is_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    lock_path = tmp_path / "dispatch.lock"
    request_id = "req-accepted-no-ack"
    schedules_path = tmp_path / "schedules.json"
    schedules_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        trigger.scheduler,
        "load_cron_expr",
        lambda **_kwargs: "7 * * * *",
    )

    async def fake_tick(**_kwargs):
        # The socket deadline expires while the production server owns the
        # request. It must persist completion before attempting the late ack.
        await asyncio.sleep(0.05)
        return {"action": "launched", "job_id": "job-late-ack"}

    monkeypatch.setattr(trigger.scheduler, "_tick_once", fake_tick)

    async def run() -> dict:
        server = asyncio.create_task(
            trigger.serve_forever(
                socket_path=socket_path,
                lock_path=lock_path,
                state_path=tmp_path / "state.json",
                schedules_path=schedules_path,
                prompt_path=tmp_path / "prompt.md",
                log_path=tmp_path / "worker.log",
                repo_root=tmp_path,
            )
        )
        try:
            await _wait_for_socket(socket_path)
            return await trigger.request_tick(
                socket_path=socket_path,
                reason="operations_core_tick",
                request_id=request_id,
                timeout_seconds=0.01,
                reconciliation_timeout_seconds=0.2,
            )
        finally:
            server.cancel()
            with suppress(asyncio.CancelledError):
                await server

    response = asyncio.run(run())

    assert response["ok"] is True
    assert response["decision"]["job_id"] == "job-late-ack"
    assert response["transport_reconciliation"] == {
        "request_id": request_id,
        "source": "durable_receipt",
    }


def test_trigger_timeout_without_completed_receipt_remains_failure(
    tmp_path: Path,
) -> None:
    socket_path = _short_socket_path()

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await reader.readline()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    async def run() -> None:
        server = await asyncio.start_unix_server(handle, path=str(socket_path))
        try:
            with pytest.raises(asyncio.TimeoutError):
                await trigger.request_tick(
                    socket_path=socket_path,
                    reason="operations_core_tick",
                    request_id="req-never-completed",
                    timeout_seconds=0.01,
                    reconciliation_timeout_seconds=0.03,
                )
        finally:
            server.close()
            await server.wait_closed()
            socket_path.unlink(missing_ok=True)

    asyncio.run(run())


def test_trigger_reconciles_completed_tick_when_server_closes_without_ack() -> None:
    socket_path = _short_socket_path()
    request_id = "req-closed-no-ack"

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request = json.loads(await reader.readline())
        trigger._write_request_receipt(
            trigger._request_receipt_path(socket_path, request_id),
            {
                "request_id": request_id,
                "request_fingerprint": trigger._request_fingerprint(
                    request_id, "operations_core_tick"
                ),
                "status": "completed",
                "response": {
                    "ok": True,
                    "reason": request["reason"],
                    "decision": {"action": "skip", "reason": "not_due"},
                },
            },
        )
        writer.close()
        await writer.wait_closed()

    async def run() -> dict:
        server = await asyncio.start_unix_server(handle, path=str(socket_path))
        try:
            return await trigger.request_tick(
                socket_path=socket_path,
                request_id=request_id,
                timeout_seconds=0.2,
                reconciliation_timeout_seconds=0.1,
            )
        finally:
            server.close()
            await server.wait_closed()
            socket_path.unlink(missing_ok=True)

    response = asyncio.run(run())

    assert response["ok"] is True
    assert response["decision"]["reason"] == "not_due"
    assert response["transport_reconciliation"]["source"] == "durable_receipt"


def test_trigger_reconciles_connection_reset_after_request_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    request_id = "req-reset-no-ack"
    trigger._write_request_receipt(
        trigger._request_receipt_path(socket_path, request_id),
        {
            "request_id": request_id,
            "request_fingerprint": trigger._request_fingerprint(
                request_id, "operations_core_tick"
            ),
            "status": "completed",
            "response": {
                "ok": True,
                "decision": {"action": "skip", "reason": "not_due"},
            },
        },
    )

    class ResetReader:
        async def readline(self):
            raise ConnectionResetError("peer reset after processing")

    class DeliveredWriter:
        def write(self, _payload):
            return None

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def fake_open(_path):
        return ResetReader(), DeliveredWriter()

    monkeypatch.setattr(asyncio, "open_unix_connection", fake_open)

    response = asyncio.run(
        trigger.request_tick(
            socket_path=socket_path,
            request_id=request_id,
            timeout_seconds=0.1,
            reconciliation_timeout_seconds=0.1,
        )
    )

    assert response["ok"] is True
    assert response["transport_reconciliation"]["source"] == "durable_receipt"


def test_duplicate_request_id_replays_completed_result_without_second_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    lock_path = tmp_path / "dispatch.lock"
    schedules_path = tmp_path / "schedules.json"
    schedules_path.write_text("{}", encoding="utf-8")
    calls = 0

    monkeypatch.setattr(
        trigger.scheduler,
        "load_cron_expr",
        lambda **_kwargs: "7 * * * *",
    )

    async def fake_tick(**_kwargs):
        nonlocal calls
        calls += 1
        return {"action": "launched", "job_id": "job-once"}

    monkeypatch.setattr(trigger.scheduler, "_tick_once", fake_tick)
    monkeypatch.setattr(trigger.alerts, "send_loop_crash", lambda *_a, **_k: True)

    async def run() -> tuple[dict, dict, dict]:
        server = asyncio.create_task(
            trigger.serve_forever(
                socket_path=socket_path,
                lock_path=lock_path,
                state_path=tmp_path / "state.json",
                schedules_path=schedules_path,
                repo_root=tmp_path,
            )
        )
        try:
            await _wait_for_socket(socket_path)
            first = await trigger.request_tick(
                socket_path=socket_path,
                request_id="req-idempotent",
            )
            second = await trigger.request_tick(
                socket_path=socket_path,
                request_id="req-idempotent",
            )
            mismatched = await trigger.request_tick(
                socket_path=socket_path,
                request_id="req-idempotent",
                reason="different-payload",
            )
            return first, second, mismatched
        finally:
            server.cancel()
            with suppress(asyncio.CancelledError):
                await server

    first, second, mismatched = asyncio.run(run())

    assert calls == 1
    assert first["decision"]["job_id"] == "job-once"
    assert second["decision"]["job_id"] == "job-once"
    assert second["transport_reconciliation"]["source"] == "server_completed_receipt"
    assert mismatched["ok"] is False
    assert "different payload" in mismatched["error"]


def test_corrupt_receipt_fails_closed_without_redelivering_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    lock_path = tmp_path / "dispatch.lock"
    request_id = "req-corrupt-receipt"
    receipt_path = trigger._request_receipt_path(socket_path, request_id)
    trigger._ensure_receipt_directory(receipt_path.parent)
    receipt_path.write_text("{truncated", encoding="utf-8")
    calls = 0

    async def fake_tick(**_kwargs):
        nonlocal calls
        calls += 1
        return {"action": "launched"}

    monkeypatch.setattr(trigger.scheduler, "_tick_once", fake_tick)
    monkeypatch.setattr(trigger.alerts, "send_loop_crash", lambda *_a, **_k: True)

    async def run() -> dict:
        server = asyncio.create_task(
            trigger.serve_forever(
                socket_path=socket_path,
                lock_path=lock_path,
                state_path=tmp_path / "state.json",
                schedules_path=tmp_path / "schedules.json",
                repo_root=tmp_path,
            )
        )
        try:
            await _wait_for_socket(socket_path)
            return await trigger.request_tick(
                socket_path=socket_path,
                request_id=request_id,
            )
        finally:
            server.cancel()
            with suppress(asyncio.CancelledError):
                await server

    response = asyncio.run(run())

    assert response["ok"] is False
    assert "TriggerReceiptInvalid" in response["error"]
    assert calls == 0


def test_new_receipt_directory_fsyncs_parent_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_dir = tmp_path / "new-receipts"
    opened: list[Path] = []
    fsynced: list[int] = []
    closed: list[int] = []

    monkeypatch.setattr(
        os,
        "open",
        lambda path, _flags: opened.append(Path(path)) or 73,
    )
    monkeypatch.setattr(os, "fsync", fsynced.append)
    monkeypatch.setattr(os, "close", closed.append)

    trigger._ensure_receipt_directory(receipt_dir)
    trigger._ensure_receipt_directory(receipt_dir)

    assert opened == [tmp_path]
    assert fsynced == [73]
    assert closed == [73]


def test_receipt_pruning_is_bounded_and_preserves_recent_evidence(
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    old = receipt_dir / "old.json"
    recent = receipt_dir / "recent.json"
    old.write_text("{}\n", encoding="utf-8")
    recent.write_text("{}\n", encoding="utf-8")
    os.utime(old, (100.0, 100.0))
    os.utime(recent, (190.0, 190.0))

    trigger._prune_request_receipts(
        receipt_dir,
        now=200.0,
        retention_seconds=50.0,
    )

    assert not old.exists()
    assert recent.exists()


def test_trigger_rejects_unsupported_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = _short_socket_path()
    lock_path = tmp_path / "dispatch.lock"
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        trigger.alerts,
        "send_loop_crash",
        lambda component, tb, **_kwargs: alerts.append((component, tb)) or True,
    )

    async def run() -> dict:
        server = asyncio.create_task(
            trigger.serve_forever(
                socket_path=socket_path,
                lock_path=lock_path,
                state_path=tmp_path / "state.json",
                schedules_path=tmp_path / "schedules.json",
                repo_root=tmp_path,
            )
        )
        try:
            await _wait_for_socket(socket_path)
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(b'{"command":"wrong"}\n')
            await writer.drain()
            response = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            return response
        finally:
            server.cancel()
            with suppress(asyncio.CancelledError):
                await server

    response = asyncio.run(run())

    assert response["ok"] is False
    assert "unsupported trigger request" in response["error"]
    assert alerts and alerts[0][0] == "trigger_request"


def test_trigger_client_reports_missing_executor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = trigger.main(
        [
            "--socket",
            str(tmp_path / "missing.sock"),
            "--timeout-seconds",
            "0.1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert output["ok"] is False


def test_live_supervisor_has_no_independent_schedule_loop() -> None:
    source = inspect.getsource(supervisor._run_async)

    assert "trigger.serve_forever" in source
    assert "health.health_loop" in source
    assert "scheduler.scheduler_loop" not in source
