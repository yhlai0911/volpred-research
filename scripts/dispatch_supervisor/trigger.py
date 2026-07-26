"""Operations Core trigger seam for the dispatch executor.

The long-lived dispatch process owns worker concurrency and health monitoring,
but it does not own a business clock. Operations Core calls the tiny client in
this module once per minute; the Unix-socket server turns that durable clock
tick into one non-blocking ``scheduler._tick_once(background=True)`` decision.

This split keeps Operations Core as the only schedule owner while preserving
the executor's worker pool and independent hang monitor. Model-quota failures
remain worker outcomes instead of being confused with trigger-delivery errors.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import alerts, scheduler, state

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(
    os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))
) / "run"
SOCKET_PATH = RUNTIME_DIR / "dispatch-trigger.sock"
LOCK_PATH = RUNTIME_DIR / "dispatch-trigger.lock"
MAX_REQUEST_BYTES = 4096
CLIENT_TIMEOUT_SECONDS = 20.0


def _json_line(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        + "\n"
    ).encode("utf-8")


async def request_tick(
    *,
    socket_path: Path = SOCKET_PATH,
    reason: str = "operations_core_tick",
    timeout_seconds: float = CLIENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Deliver one Operations Core tick and return the executor acknowledgement."""

    async def exchange() -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        try:
            writer.write(
                _json_line(
                    {
                        "command": "tick",
                        "reason": str(reason)[:200],
                        "caller_pid": os.getpid(),
                    }
                )
            )
            await writer.drain()
            raw = await reader.readline()
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
        if not raw:
            raise RuntimeError("dispatch trigger server closed without acknowledgement")
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("dispatch trigger acknowledgement is not JSON") from exc
        if not isinstance(response, dict):
            raise RuntimeError("dispatch trigger acknowledgement must be an object")
        return response

    return await asyncio.wait_for(exchange(), timeout=timeout_seconds)


class DispatchTriggerServer:
    """Serialize schedule decisions while admitted workers run in the background."""

    def __init__(
        self,
        *,
        state_path: Path = state.STATE_PATH,
        schedules_path: Path = scheduler.SCHEDULES_PATH,
        prompt_path: Path = scheduler.DEFAULT_PROMPT_PATH,
        log_path: Path = scheduler.DEFAULT_LOG_PATH,
        repo_root: Path = ROOT,
        dry_run: bool = False,
    ) -> None:
        self._decision_lock = asyncio.Lock()
        self._state_path = state_path
        self._schedules_path = schedules_path
        self._prompt_path = prompt_path
        self._log_path = log_path
        self._repo_root = repo_root
        self._dry_run = dry_run

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        response: dict[str, Any]
        try:
            raw = await asyncio.wait_for(
                reader.readline(), timeout=CLIENT_TIMEOUT_SECONDS
            )
            if not raw or len(raw) > MAX_REQUEST_BYTES:
                raise ValueError("empty or oversized trigger request")
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get("command") != "tick":
                raise ValueError("unsupported trigger request")
            reason = str(request.get("reason") or "unspecified")[:200]
            async with self._decision_lock:
                cron_expr = scheduler.load_cron_expr(
                    schedules_path=self._schedules_path
                )
                decision = await scheduler._tick_once(
                    state_path=self._state_path,
                    cron_expr=cron_expr,
                    prompt_path=self._prompt_path,
                    log_path=self._log_path,
                    dry_run=self._dry_run,
                    repo_root=self._repo_root,
                    schedules_path=self._schedules_path,
                    background=True,
                )
            response = {
                "ok": True,
                "reason": reason,
                "decision": decision,
            }
        except Exception as exc:  # noqa: BLE001
            LOG.exception("dispatch trigger request failed: %s", exc)
            alerts.send_loop_crash(
                "trigger_request",
                traceback.format_exc(),
                state_path=self._state_path,
            )
            response = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        writer.write(_json_line(response))
        with suppress(ConnectionError):
            await writer.drain()
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def serve_forever(
    *,
    socket_path: Path = SOCKET_PATH,
    lock_path: Path = LOCK_PATH,
    state_path: Path = state.STATE_PATH,
    schedules_path: Path = scheduler.SCHEDULES_PATH,
    prompt_path: Path = scheduler.DEFAULT_PROMPT_PATH,
    log_path: Path = scheduler.DEFAULT_LOG_PATH,
    repo_root: Path = ROOT,
    dry_run: bool = False,
) -> None:
    """Serve trigger acknowledgements and refuse a second executor process."""

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another dispatch trigger server owns the lock") from exc
        socket_path.unlink(missing_ok=True)
        handler = DispatchTriggerServer(
            state_path=state_path,
            schedules_path=schedules_path,
            prompt_path=prompt_path,
            log_path=log_path,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        server = await asyncio.start_unix_server(
            handler.handle,
            path=str(socket_path),
        )
        os.chmod(socket_path, 0o600)
        LOG.info("dispatch trigger server listening path=%s", socket_path)
        try:
            async with server:
                await server.serve_forever()
        finally:
            server.close()
            await server.wait_closed()
    finally:
        socket_path.unlink(missing_ok=True)
        with suppress(OSError):
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dispatch-trigger")
    parser.add_argument("--socket", type=Path, default=SOCKET_PATH)
    parser.add_argument("--reason", default="operations_core_tick")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=CLIENT_TIMEOUT_SECONDS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        response = asyncio.run(
            request_tick(
                socket_path=args.socket,
                reason=args.reason,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return 0 if response.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
