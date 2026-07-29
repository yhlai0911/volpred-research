"""Durable, caller-independent dispatch-supervisor reload requests.

``reload_dispatch_supervisor.sh --defer`` used to launch a ``nohup`` shell
poller.  ``nohup`` only ignores SIGHUP; it neither creates a new session nor
transfers lifecycle ownership.  Codex/PTY teardown can therefore terminate the
poller before the worker drains, leaving no receipt and a daemon on stale code.

The durable owner is now the already-running supervisor health loop:

1. the caller atomically arms one request bound to the exact supervisor boot
   and a content-addressed immutable release built from one Git commit;
2. health-loop processing waits for one atomic state snapshot to contain no
   ``current_jobs`` and no ``phase_z_pending``;
3. it atomically activates that release, persists ``signal_armed``, and calls
   the canonical planned-reload actuator;
4. the fresh boot acknowledges that exact request into a mode-0600 terminal
   receipt and removes the active pointer.

There is no background waiter process to orphan.  A request for another boot,
tampered release, malformed state, or an expired request fails closed and is
recorded rather than signalling a process or importing mutable source it did
not name.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import release_image, state

SCHEMA_VERSION = 1
DEFAULT_MAX_WAIT_S = 3900
ROOT_ENV = "VOLPRED_DEFERRED_RELOAD_ROOT"
REPO_ROOT = Path(__file__).resolve().parents[2]
TERMINAL_STATES = {
    "completed",
    "rolled_back_failed_boot",
    "rejected_boot_drift",
    "rejected_release_drift",
    "rejected_source_drift",
    "signal_failed",
    "timed_out",
}


class DeferredReloadError(RuntimeError):
    """A durable reload request cannot be trusted or safely processed."""


class ActiveRequestConflict(DeferredReloadError):
    """A different request already owns the single active reload slot."""


def default_root() -> Path:
    configured = os.environ.get(ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".volpred" / "run" / "dispatch-supervisor-reload"


def arm(
    *,
    reason: str,
    state_path: Path = state.STATE_PATH,
    root: Path | None = None,
    source_roots: Iterable[Path] | None = None,
    now: datetime | None = None,
    requested_by_pid: int | None = None,
    max_wait_s: int = DEFAULT_MAX_WAIT_S,
) -> dict[str, Any]:
    """Create or idempotently coalesce one exact deferred-reload request."""
    bounded_reason = " ".join(str(reason).split())
    if not bounded_reason or len(bounded_reason) > 240:
        raise ValueError("reason must contain 1..240 normalized characters")
    max_wait_s = int(max_wait_s)
    if max_wait_s < 1:
        raise ValueError("max_wait_s must be positive")
    now = _aware_now(now)
    snapshot = state.read_state(Path(state_path))
    boot = _boot_identity(snapshot)
    request_root = Path(root) if root is not None else default_root()
    test_roots = os.environ.get("VOLPRED_DEFERRED_RELOAD_TEST_SOURCE_ROOTS")
    if source_roots is None and test_roots:
        if "PYTEST_CURRENT_TEST" not in os.environ:
            raise DeferredReloadError(
                "test source roots are forbidden outside a pytest process"
            )
        source_roots = tuple(
            Path(item) for item in test_roots.split(os.pathsep) if item
        )
    release = release_image.materialize(
        repo_root=REPO_ROOT,
        run_root=request_root,
        source_roots=source_roots,
    )
    identity = release["release_sha256"]
    intent_id = hashlib.sha256(
        _canonical_json(
            {
                "schema_version": SCHEMA_VERSION,
                "reason": bounded_reason,
                "expected_supervisor_started_at": boot,
                "source_sha256": identity,
            }
        )
    ).hexdigest()
    request_id = secrets.token_hex(32)
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "intent_id": intent_id,
        "state": "requested",
        "reason": bounded_reason,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=max_wait_s)).isoformat(),
        "expected_supervisor_started_at": boot,
        "source_sha256": identity,
        "requested_by_pid": int(requested_by_pid or os.getpid()),
        **release,
    }
    with _locked_root(request_root):
        active_path = request_root / "active.json"
        existing = _read_active(active_path)
        if existing is not None:
            _validate_request(existing)
            if existing["intent_id"] == intent_id:
                return {
                    **existing,
                    "created": False,
                    "coalesced": True,
                }
            raise ActiveRequestConflict(
                "a different deferred reload request is already active: "
                f"{existing['request_id']}"
            )
        _atomic_replace_json(active_path, request)
    return {**request, "created": True}


def process(
    *,
    state_path: Path = state.STATE_PATH,
    root: Path | None = None,
    source_roots: Iterable[Path] | None = None,
    now: datetime | None = None,
    reload_fn: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Advance one request from durable intent to reload or terminal receipt."""
    now = _aware_now(now)
    request_root = Path(root) if root is not None else default_root()
    if not request_root.exists():
        return {"action": "no_request"}
    snapshot = state.read_state(Path(state_path))
    observed_boot = _boot_identity(snapshot)

    with _locked_root(request_root):
        active_path = request_root / "active.json"
        request = _read_active(active_path)
        if request is None:
            return {"action": "no_request"}
        _validate_request(request)
        replayed = _replay_terminal_if_present(request_root, request)
        if replayed is not None:
            return replayed
        request_id = str(request["request_id"])
        expected_boot = str(request["expected_supervisor_started_at"])
        expected_source = str(request["source_sha256"])
        request_state = str(request["state"])
        try:
            verified_release = release_image.verify(request)
        except release_image.ReleaseImageError as exc:
            return _terminal(
                request_root,
                request,
                state_name="rejected_release_drift",
                now=now,
                observed_boot=observed_boot,
                observed_source="unverified",
                error=f"{type(exc).__name__}: {exc}",
            )
        observed_source = verified_release["release_sha256"]

        # Once activation started, a different boot with
        # the exact requested source is the success acknowledgment.  It must
        # win over the original drain deadline: launchd startup and the first
        # health tick can legitimately occur after that deadline.
        if request_state in {"activating", "signal_armed"} and observed_boot != expected_boot:
            if _runtime_matches(snapshot, request):
                release_image.promote(run_root=request_root, request=request)
                terminal = "completed"
            elif _rollback_receipt_exists(request_root, request_id):
                terminal = "rolled_back_failed_boot"
            elif request_state == "activating":
                # The old daemon can die after the durable activating record
                # but before the pointer CAS.  Rebase the request onto the
                # replacement boot and retry; this is the only safe recovery
                # when that boot did not load the candidate.
                recovered = {
                    **request,
                    "state": "requested",
                    "expected_supervisor_started_at": observed_boot,
                    "recovered_activation_at": now.isoformat(),
                }
                _atomic_replace_json(active_path, recovered)
                return {
                    "action": "activation_recovered",
                    "request_id": request_id,
                }
            else:
                terminal = "rejected_release_drift"
            return _terminal(
                request_root,
                request,
                state_name=terminal,
                now=now,
                observed_boot=observed_boot,
                observed_source=observed_source,
            )

        if now >= _parse_time(request["expires_at"], field="expires_at"):
            return _terminal(
                request_root,
                request,
                state_name="timed_out",
                now=now,
                observed_boot=observed_boot,
                observed_source=observed_source,
            )

        if observed_boot != expected_boot:
            return _terminal(
                request_root,
                request,
                state_name="rejected_boot_drift",
                now=now,
                observed_boot=observed_boot,
                observed_source=observed_source,
            )

        if observed_source != expected_source:
            return _terminal(
                request_root,
                request,
                state_name="rejected_source_drift",
                now=now,
                observed_boot=observed_boot,
                observed_source=observed_source,
            )

        if request_state == "signal_armed":
            return {
                "action": "signal_already_armed",
                "request_id": request_id,
            }
        if request_state not in {"requested", "activating"}:
            raise DeferredReloadError(
                f"unsupported active request state: {request_state!r}"
            )

        if request_state == "requested":
            active_count = len(snapshot.get("current_jobs") or []) + len(
                snapshot.get("phase_z_pending") or []
            )
            if active_count:
                return {
                    "action": "deferred_in_flight",
                    "request_id": request_id,
                    "active_count": active_count,
                }
            activating = {
                **request,
                "state": "activating",
                "activation_started_at": now.isoformat(),
                "observed_supervisor_started_at": observed_boot,
            }
            # Persist first: if this process dies before/after the pointer CAS,
            # the replacement daemon can distinguish and recover both windows.
            _atomic_replace_json(active_path, activating)
            request = activating

        _pointer_path, previous_pointer = release_image.activate(
            run_root=request_root,
            request=request,
        )
        armed = {
            **request,
            "state": "signal_armed",
            "signal_armed_at": now.isoformat(),
        }
        _atomic_replace_json(active_path, armed)
        try:
            reload_fn(dict(armed))
        except BaseException as exc:
            release_image.restore_pointer(
                run_root=request_root,
                previous=previous_pointer,
            )
            _terminal(
                request_root,
                armed,
                state_name="signal_failed",
                now=now,
                observed_boot=observed_boot,
                observed_source=observed_source,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        return {
            "action": "reload_requested",
            "request_id": request_id,
        }


def _terminal(
    root: Path,
    request: dict[str, Any],
    *,
    state_name: str,
    now: datetime,
    observed_boot: str,
    observed_source: str,
    error: str | None = None,
) -> dict[str, Any]:
    receipt = {
        **request,
        "state": state_name,
        "terminal_at": now.isoformat(),
        "observed_supervisor_started_at": observed_boot,
        "observed_source_sha256": observed_source,
    }
    if error:
        receipt["error"] = error[:500]
    receipt_path = root / "receipts" / f"{request['request_id']}.json"
    _write_once_json(receipt_path, receipt)
    active_path = root / "active.json"
    try:
        active_path.unlink()
    except FileNotFoundError:
        pass  # silent-ok: idempotent active-request cleanup
    _fsync_directory(root)
    return {
        "action": state_name,
        "request_id": request["request_id"],
        "receipt": str(receipt_path),
    }


def _replay_terminal_if_present(
    root: Path,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Finish pointer cleanup after a crash following receipt installation."""
    receipt_path = root / "receipts" / f"{request['request_id']}.json"
    if not receipt_path.exists():
        return None
    _validate_regular_file(receipt_path)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredReloadError(f"terminal receipt is unreadable: {exc}") from exc
    if not isinstance(receipt, dict):
        raise DeferredReloadError("terminal receipt must be a JSON object")
    terminal_state = receipt.get("state")
    if terminal_state not in TERMINAL_STATES:
        raise DeferredReloadError(
            f"terminal receipt has invalid state: {terminal_state!r}"
        )
    for key, value in request.items():
        if key == "state":
            continue
        if receipt.get(key) != value:
            raise DeferredReloadError(
                f"terminal receipt collision for request field {key}: {receipt_path}"
            )
    active_path = root / "active.json"
    try:
        active_path.unlink()
    except FileNotFoundError:
        pass  # silent-ok: idempotent active-request cleanup
    _fsync_directory(root)
    return {
        "action": terminal_state,
        "request_id": request["request_id"],
        "receipt": str(receipt_path),
        "replayed": True,
    }


def _validate_request(request: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "request_id",
        "intent_id",
        "state",
        "reason",
        "requested_at",
        "expires_at",
        "expected_supervisor_started_at",
        "source_sha256",
        "requested_by_pid",
        "release_archive",
        "release_sha256",
        "release_commit",
        "bootstrap_path",
        "bootstrap_sha256",
        "stage0_path",
        "stage0_sha256",
    }
    if not required.issubset(request):
        raise DeferredReloadError(
            f"active request missing fields: {sorted(required - set(request))}"
        )
    if request.get("schema_version") != SCHEMA_VERSION:
        raise DeferredReloadError("unsupported deferred reload schema")
    request_id = request.get("request_id")
    intent_id = request.get("intent_id")
    source_sha = request.get("source_sha256")
    release_sha = request.get("release_sha256")
    if (
        not isinstance(request_id, str)
        or len(request_id) != 64
        or any(character not in "0123456789abcdef" for character in request_id)
    ):
        raise DeferredReloadError("invalid request_id")
    if (
        not isinstance(intent_id, str)
        or len(intent_id) != 64
        or any(character not in "0123456789abcdef" for character in intent_id)
    ):
        raise DeferredReloadError("invalid intent_id")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise DeferredReloadError("invalid source_sha256")
    if release_sha != source_sha:
        raise DeferredReloadError("release_sha256 must match source_sha256")
    if not isinstance(request.get("release_archive"), str):
        raise DeferredReloadError("invalid release_archive")
    if not isinstance(request.get("release_commit"), str):
        raise DeferredReloadError("invalid release_commit")
    if not isinstance(request.get("bootstrap_path"), str):
        raise DeferredReloadError("invalid bootstrap_path")
    bootstrap_sha = request.get("bootstrap_sha256")
    if not isinstance(bootstrap_sha, str) or len(bootstrap_sha) != 64:
        raise DeferredReloadError("invalid bootstrap_sha256")
    if not isinstance(request.get("stage0_path"), str):
        raise DeferredReloadError("invalid stage0_path")
    stage0_sha = request.get("stage0_sha256")
    if not isinstance(stage0_sha, str) or len(stage0_sha) != 64:
        raise DeferredReloadError("invalid stage0_sha256")
    if request.get("state") not in {"requested", "activating", "signal_armed"}:
        raise DeferredReloadError("invalid active request state")
    _parse_time(request.get("requested_at"), field="requested_at")
    _parse_time(request.get("expires_at"), field="expires_at")
    if not isinstance(request.get("expected_supervisor_started_at"), str):
        raise DeferredReloadError("invalid expected supervisor boot identity")


def _boot_identity(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("supervisor_started_at")
    if not isinstance(raw, str) or not raw.strip():
        raise DeferredReloadError("supervisor_started_at is unavailable")
    _parse_time(raw, field="supervisor_started_at")
    return raw.strip()


def _runtime_matches(snapshot: dict[str, Any], request: dict[str, Any]) -> bool:
    return (
        snapshot.get("supervisor_release_id") == request.get("request_id")
        and snapshot.get("supervisor_release_sha256")
        == request.get("release_sha256")
        and snapshot.get("supervisor_release_commit")
        == request.get("release_commit")
        and snapshot.get("supervisor_bootstrap_sha256")
        == request.get("bootstrap_sha256")
    )


def _rollback_receipt_exists(root: Path, request_id: str) -> bool:
    path = root / release_image.ROLLBACK_RECEIPTS_DIR_NAME / f"{request_id}.json"
    if not path.exists():
        return False
    _validate_regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredReloadError(f"rollback receipt is unreadable: {exc}") from exc
    return (
        isinstance(payload, dict)
        and payload.get("request_id") == request_id
        and payload.get("state") == "rolled_back_failed_boot"
    )


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current


def _parse_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise DeferredReloadError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DeferredReloadError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeferredReloadError(f"{field} must be timezone-aware")
    return parsed


def _read_active(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    _validate_regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredReloadError(f"active request is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeferredReloadError("active request must be a JSON object")
    return payload


@contextmanager
def _locked_root(root: Path) -> Iterator[None]:
    _ensure_private_directory(root)
    _ensure_private_directory(root / "receipts")
    lock_path = root / "request.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        _validate_regular_fd(fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        current = os.stat(lock_path, follow_symlinks=False)
        if current.st_ino != os.fstat(fd).st_ino:
            raise DeferredReloadError("reload request lock inode changed")
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise DeferredReloadError(
            f"reload request directory must be owner-only and non-symlink: {path}"
        )


def _validate_regular_file(path: Path) -> None:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise DeferredReloadError(
            f"reload request file must be owner-only and non-symlink: {path}"
        )


def _validate_regular_fd(fd: int) -> None:
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise DeferredReloadError("reload request lock must be owner-only")


def _atomic_replace_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise DeferredReloadError(f"refusing symlink destination: {path}")
    encoded = _canonical_json(payload) + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: atomic cleanup may race with replace
        raise


def _write_once_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        _validate_regular_file(path)
        current = json.loads(path.read_text(encoding="utf-8"))
        if current != payload:
            raise DeferredReloadError(f"terminal receipt collision: {path}")
        return
    encoded = _canonical_json(payload) + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    installed = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path, follow_symlinks=False)
            installed = True
        except FileExistsError:
            _validate_regular_file(path)
            current = json.loads(path.read_text(encoding="utf-8"))
            if current != payload:
                raise DeferredReloadError(f"terminal receipt collision: {path}")
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: write-once cleanup may race with install
        if installed:
            _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Arm a durable dispatch-supervisor deferred reload request"
    )
    parser.add_argument("command", choices=("arm",))
    parser.add_argument("--state", type=Path, default=state.STATE_PATH)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--max-wait-s", type=int, default=DEFAULT_MAX_WAIT_S)
    args = parser.parse_args()
    result = arm(
        reason=args.reason,
        state_path=args.state,
        max_wait_s=args.max_wait_s,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
