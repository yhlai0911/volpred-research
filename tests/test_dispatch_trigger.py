from __future__ import annotations

import asyncio
import inspect
import json
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
