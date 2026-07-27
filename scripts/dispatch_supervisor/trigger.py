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
import hashlib
import json
import logging
import os
import sys
import time
import traceback
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from volpred.ops.diagnostics import warn

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
RECONCILIATION_TIMEOUT_SECONDS = 35.0
RECEIPT_RETENTION_SECONDS = 2 * 24 * 60 * 60
RECEIPT_PRUNE_EVERY_REQUESTS = 1440


class TriggerAcknowledgementUnavailable(RuntimeError):
    """The request may have completed, but its socket acknowledgement was lost."""


class TriggerReceiptInvalid(RuntimeError):
    """A durable receipt exists but cannot safely authorize replay or execution."""


def _json_line(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        + "\n"
    ).encode("utf-8")


def _request_receipt_path(socket_path: Path, request_id: str) -> Path:
    """Return a traversal-safe durable receipt path for one transport request."""

    identity = f"{socket_path.absolute()}\0{request_id}".encode()
    digest = hashlib.sha256(identity).hexdigest()
    return socket_path.parent / "dispatch-trigger-receipts" / f"{digest}.json"


def _request_fingerprint(request_id: str, reason: str) -> str:
    payload = _json_line(
        {
            "command": "tick",
            "reason": str(reason)[:200],
            "request_id": request_id,
        }
    )
    return hashlib.sha256(payload).hexdigest()


def _ensure_receipt_directory(directory: Path) -> None:
    """Create the receipt directory with a parent durability barrier."""

    created = not directory.exists()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if created:
        parent_fd = os.open(directory.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def _write_request_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Durably replace one trigger receipt before exposing its socket result."""

    _ensure_receipt_directory(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n"
    ).encode("utf-8")
    try:
        with temp.open("xb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def _read_request_receipt(
    path: Path,
    request_id: str,
    request_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:  # silent-ok: canonical first-admission state
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TriggerReceiptInvalid(
            f"trigger receipt is unreadable or malformed: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise TriggerReceiptInvalid("trigger receipt root must be an object")
    if payload.get("request_id") != request_id:
        raise TriggerReceiptInvalid("trigger receipt request_id mismatch")
    if (
        request_fingerprint is not None
        and payload.get("request_fingerprint") != request_fingerprint
    ):
        raise TriggerReceiptInvalid("trigger receipt request fingerprint mismatch")
    return payload


def _prune_request_receipts(
    directory: Path,
    *,
    now: float | None = None,
    retention_seconds: float = RECEIPT_RETENTION_SECONDS,
) -> None:
    """Bound the exactly-once replay window without making delivery depend on GC."""

    cutoff = (time.time() if now is None else now) - retention_seconds
    try:
        paths = list(directory.glob("*.json"))
    except OSError as exc:
        warn(
            "dispatch_trigger_receipts",
            "receipt retention scan failed; delivery remains authoritative",
            path=str(directory),
            error=f"{type(exc).__name__}: {exc}",
        )
        return
    for path in paths:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError as exc:
            warn(
                "dispatch_trigger_receipts",
                "one stale receipt could not be pruned",
                path=str(path),
                error=f"{type(exc).__name__}: {exc}",
            )
            continue


async def _reconcile_completed_request(
    *,
    receipt_path: Path,
    request_id: str,
    request_fingerprint: str,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout_seconds)
    while True:
        receipt = _read_request_receipt(
            receipt_path,
            request_id,
            request_fingerprint,
        )
        if receipt is not None and receipt.get("status") == "completed":
            response = receipt.get("response")
            if isinstance(response, dict):
                reconciled = dict(response)
                reconciled["transport_reconciliation"] = {
                    "request_id": request_id,
                    "source": "durable_receipt",
                }
                return reconciled
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(0.05, remaining))


async def request_tick(
    *,
    socket_path: Path = SOCKET_PATH,
    reason: str = "operations_core_tick",
    request_id: str | None = None,
    timeout_seconds: float = CLIENT_TIMEOUT_SECONDS,
    reconciliation_timeout_seconds: float = RECONCILIATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Deliver one Operations Core tick and return its durable acknowledgement.

    The socket acknowledgement is only a transport optimization. The server
    commits the response receipt before writing to the socket, so a client-side
    timeout can distinguish an accepted tick from true non-delivery.
    """

    request_id = request_id or uuid.uuid4().hex
    receipt_path = _request_receipt_path(socket_path, request_id)
    request_fingerprint = _request_fingerprint(request_id, reason)
    connected = False

    async def exchange() -> dict[str, Any]:
        nonlocal connected
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        connected = True
        try:
            writer.write(
                _json_line(
                    {
                        "command": "tick",
                        "reason": str(reason)[:200],
                        "caller_pid": os.getpid(),
                        "request_id": request_id,
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
            raise TriggerAcknowledgementUnavailable(
                "dispatch trigger server closed without acknowledgement"
            )
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TriggerAcknowledgementUnavailable(
                "dispatch trigger acknowledgement is not JSON"
            ) from exc
        if not isinstance(response, dict):
            raise TriggerAcknowledgementUnavailable(
                "dispatch trigger acknowledgement must be an object"
            )
        return response

    try:
        response = await asyncio.wait_for(exchange(), timeout=timeout_seconds)
    except (
        TimeoutError,
        TriggerAcknowledgementUnavailable,
        ConnectionError,
        OSError,
    ):
        # A connect failure proves the request was never handed to this server.
        # Once connected, reset/EOF/timeout is ambiguous and must consult the
        # durable request receipt before classifying the tick as failed.
        if not connected:
            raise
        reconciled = await _reconcile_completed_request(
            receipt_path=receipt_path,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            timeout_seconds=reconciliation_timeout_seconds,
        )
        if reconciled is None:
            raise
        return reconciled
    else:
        # Keep the completed receipt for the bounded exactly-once replay window.
        # A caller retrying the same request id must receive the original result,
        # never execute a second tick.
        return response


class DispatchTriggerServer:
    """Serialize schedule decisions while admitted workers run in the background."""

    def __init__(
        self,
        *,
        socket_path: Path = SOCKET_PATH,
        state_path: Path = state.STATE_PATH,
        schedules_path: Path = scheduler.SCHEDULES_PATH,
        prompt_path: Path = scheduler.DEFAULT_PROMPT_PATH,
        log_path: Path = scheduler.DEFAULT_LOG_PATH,
        repo_root: Path = ROOT,
        dry_run: bool = False,
    ) -> None:
        self._decision_lock = asyncio.Lock()
        self._socket_path = socket_path
        self._state_path = state_path
        self._schedules_path = schedules_path
        self._prompt_path = prompt_path
        self._log_path = log_path
        self._repo_root = repo_root
        self._dry_run = dry_run
        self._requests_since_prune = 0

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
            request_id = str(request.get("request_id") or "")
            if not request_id or len(request_id) > 200:
                raise ValueError("missing or oversized trigger request_id")
            receipt_path = _request_receipt_path(self._socket_path, request_id)
            request_fingerprint = _request_fingerprint(request_id, reason)
            async with self._decision_lock:
                existing = _read_request_receipt(receipt_path, request_id)
                if (
                    existing is not None
                    and existing.get("request_fingerprint") != request_fingerprint
                ):
                    raise RuntimeError(
                        "trigger request_id was reused with a different payload"
                    )
                if existing is not None and existing.get("status") == "completed":
                    stored_response = existing.get("response")
                    if not isinstance(stored_response, dict):
                        raise RuntimeError(
                            "completed trigger receipt has no object response"
                        )
                    response = dict(stored_response)
                    response["transport_reconciliation"] = {
                        "request_id": request_id,
                        "source": "server_completed_receipt",
                    }
                elif existing is not None:
                    # A prior executor died after durable admission but before
                    # completion. Re-executing would violate exactly-once; the
                    # unresolved receipt is explicit operator evidence.
                    raise RuntimeError(
                        "trigger request was admitted without a completed receipt"
                    )
                else:
                    _write_request_receipt(
                        receipt_path,
                        {
                            "request_id": request_id,
                            "request_fingerprint": request_fingerprint,
                            "status": "accepted",
                            "caller_pid": request.get("caller_pid"),
                            "reason": reason,
                        },
                    )
                    try:
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
                    except Exception as exc:
                        LOG.exception("dispatch trigger request failed")
                        alerts.send_loop_crash(
                            "trigger_request",
                            traceback.format_exc(),
                            state_path=self._state_path,
                        )
                        response = {
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    _write_request_receipt(
                        receipt_path,
                        {
                            "request_id": request_id,
                            "request_fingerprint": request_fingerprint,
                            "status": "completed",
                            "response": response,
                        },
                    )
        except Exception as exc:
            LOG.exception("dispatch trigger request failed")
            alerts.send_loop_crash(
                "trigger_request",
                traceback.format_exc(),
                state_path=self._state_path,
            )
            response = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        self._requests_since_prune += 1
        if self._requests_since_prune >= RECEIPT_PRUNE_EVERY_REQUESTS:
            self._requests_since_prune = 0
            _prune_request_receipts(
                self._socket_path.parent / "dispatch-trigger-receipts"
            )
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
    receipt_directory = socket_path.parent / "dispatch-trigger-receipts"
    _ensure_receipt_directory(receipt_directory)
    _prune_request_receipts(receipt_directory)
    lock_handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another dispatch trigger server owns the lock") from exc
        socket_path.unlink(missing_ok=True)
        handler = DispatchTriggerServer(
            socket_path=socket_path,
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
    parser.add_argument(
        "--reconciliation-timeout-seconds",
        type=float,
        default=RECONCILIATION_TIMEOUT_SECONDS,
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
                reconciliation_timeout_seconds=args.reconciliation_timeout_seconds,
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
