#!/usr/bin/env python3
"""Immutable stage-0 launcher for versioned supervisor bootstraps.

This file is installed once outside the mutable checkout.  Release
materialization never replaces it.  Its sole job is to read the atomic release
pointer, verify the pointer-selected content-addressed stage-1 bootstrap, and
execute that bootstrap.  The stage-1 bootstrap then verifies and imports the
content-addressed application archive.
"""
from __future__ import annotations

import hashlib
import json
import os
import runpy
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT_ENV = "VOLPRED_DEFERRED_RELOAD_ROOT"
POINTER_NAME = "current_release.json"
BOOTSTRAPS_DIR_NAME = "bootstraps"
RELEASES_DIR_NAME = "releases"
BOOT_ATTEMPTS_DIR_NAME = "boot_attempts"
ROLLBACK_RECEIPTS_DIR_NAME = "rollback_receipts"
TERMINATION_MEMBER = "src/volpred/ops/termination.py"


def _run_root() -> Path:
    configured = os.environ.get(ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".volpred" / "run" / "dispatch-supervisor-reload"


def _private_regular(path: Path) -> None:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise RuntimeError(f"untrusted supervisor bootstrap file: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise RuntimeError(f"untrusted supervisor runtime directory: {path}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _private_directory(path.parent)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: atomic cleanup may race with replace


def _candidate_or_rollback(
    *,
    run_root: Path,
    pointer_path: Path,
    pointer: dict[str, Any],
) -> dict[str, Any]:
    if pointer.get("activation_state") != "candidate":
        return pointer
    request_id = pointer.get("request_id")
    max_attempts = pointer.get("max_boot_attempts")
    if not _is_sha256(request_id) or not isinstance(max_attempts, int):
        raise RuntimeError("candidate release activation metadata is invalid")
    attempts_dir = run_root / BOOT_ATTEMPTS_DIR_NAME
    _private_directory(attempts_dir)
    attempt_path = attempts_dir / f"{request_id}.json"
    attempts = 0
    if attempt_path.exists():
        _private_regular(attempt_path)
        prior = json.loads(attempt_path.read_text(encoding="utf-8"))
        if (
            not isinstance(prior, dict)
            or prior.get("request_id") != request_id
            or prior.get("release_sha256") != pointer.get("release_sha256")
            or not isinstance(prior.get("attempts"), int)
        ):
            raise RuntimeError("candidate boot attempt ledger is malformed")
        attempts = int(prior["attempts"])
    if attempts >= max_attempts:
        return _rollback_candidate(
            run_root=run_root,
            pointer_path=pointer_path,
            pointer=pointer,
            attempts=attempts,
            reason="candidate_exit_loop",
        )
    _atomic_json(
        attempt_path,
        {
            "schema_version": 1,
            "request_id": request_id,
            "release_sha256": pointer.get("release_sha256"),
            "attempts": attempts + 1,
        },
    )
    return pointer


def _rollback_candidate(
    *,
    run_root: Path,
    pointer_path: Path,
    pointer: dict[str, Any],
    attempts: int,
    reason: str,
) -> dict[str, Any]:
    previous = pointer.get("previous_release")
    if not isinstance(previous, dict):
        raise TypeError("candidate failed and has no last-known-good release")
    previous = dict(previous)
    previous["schema_version"] = 2
    previous["activation_state"] = "stable"
    previous.pop("previous_release", None)
    previous.pop("max_boot_attempts", None)
    previous.pop("startup_timeout_s", None)
    _atomic_json(pointer_path, previous)
    request_id = str(pointer["request_id"])
    receipt = run_root / ROLLBACK_RECEIPTS_DIR_NAME / f"{request_id}.json"
    _atomic_json(
        receipt,
        {
            "schema_version": 1,
            "request_id": request_id,
            "state": "rolled_back_failed_boot",
            "reason": reason,
            "failed_release_sha256": pointer.get("release_sha256"),
            "restored_release_sha256": previous.get("release_sha256"),
            "boot_attempts": attempts,
            "rolled_back_at": datetime.now(UTC).isoformat(),
        },
    )
    return previous


def _read_pointer(path: Path) -> dict[str, Any]:
    _private_regular(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("supervisor release pointer must be an object")
    return payload


def _load_stable_termination_owner(
    *,
    run_root: Path,
    candidate_pointer: dict[str, Any],
) -> ModuleType:
    """Load the termination owner from the verified last-known-good release."""
    stable = candidate_pointer.get("previous_release")
    if not isinstance(stable, dict):
        raise TypeError("candidate has no stable termination owner")
    release_sha = stable.get("release_sha256")
    release_commit = stable.get("release_commit")
    if not _is_sha256(release_sha) or not isinstance(release_commit, str):
        raise RuntimeError("stable termination owner identity is invalid")
    archive = Path(str(stable.get("release_archive") or ""))
    expected_parent = (run_root / RELEASES_DIR_NAME).resolve()
    if archive.parent.resolve() != expected_parent:
        raise RuntimeError("stable termination owner escaped the release root")
    if archive.name != f"{release_sha}.zip":
        raise RuntimeError("stable termination owner is not content-addressed")
    _private_regular(archive)
    if _sha256(archive) != release_sha:
        raise RuntimeError("stable termination owner release digest mismatch")

    try:
        with zipfile.ZipFile(archive) as release:
            names = release.namelist()
            if len(names) != len(set(names)):
                raise RuntimeError("stable release has duplicate members")
            manifest = json.loads(release.read("VOLPRED_RELEASE.json"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != 1
                or manifest.get("release_commit") != release_commit
                or manifest.get("entries") != sorted(
                    name for name in names if name != "VOLPRED_RELEASE.json"
                )
                or TERMINATION_MEMBER not in names
            ):
                raise RuntimeError("stable termination owner manifest is invalid")
            source = release.read(TERMINATION_MEMBER)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError(
            f"stable termination owner is unavailable: {exc}"
        ) from exc

    module_name = f"_volpred_stage0_termination_{release_sha}"
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return existing
    owner = ModuleType(module_name)
    owner.__file__ = f"{archive}!/{TERMINATION_MEMBER}"
    sys.modules[module_name] = owner
    try:
        exec(  # noqa: S102 - source belongs to a digest-verified stable release
            compile(source, owner.__file__, "exec"),
            owner.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    if not callable(getattr(owner, "arm", None)) or not callable(
        getattr(owner, "send_pid", None)
    ):
        sys.modules.pop(module_name, None)
        raise TypeError("stable release has no termination owner interface")
    return owner


def _terminate_child(
    child: subprocess.Popen[bytes],
    *,
    run_root: Path,
    candidate_pointer: dict[str, Any],
) -> None:
    if child.poll() is not None:
        return
    owner = _load_stable_termination_owner(
        run_root=run_root,
        candidate_pointer=candidate_pointer,
    )
    ledger = run_root / "termination_intents.jsonl"
    intent = owner.arm(
        target_kind="pid",
        target_id=child.pid,
        reason="candidate_startup_timeout",
        actor="dispatch-supervisor-stage0",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        ledger_path=ledger,
    )
    owner.send_pid(intent, signal.SIGTERM, ledger_path=ledger)
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        owner.send_pid(intent, signal.SIGKILL, ledger_path=ledger)
        child.wait(timeout=5)


def _supervise_candidate(
    *,
    run_root: Path,
    pointer_path: Path,
    pointer: dict[str, Any],
    bootstrap_path: Path,
) -> tuple[int | None, dict[str, Any] | None]:
    timeout_s = pointer.get("startup_timeout_s")
    if not isinstance(timeout_s, (int, float)) or not 0.05 <= timeout_s <= 600:
        raise RuntimeError("candidate startup timeout is invalid")
    child = subprocess.Popen([sys.executable, str(bootstrap_path)])
    old_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: Any) -> None:
        if child.poll() is None:
            child.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        old_handlers[signum] = signal.signal(signum, forward)
    try:
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            returncode = child.poll()
            if returncode is not None:
                return (returncode if returncode else 1), None
            current = _read_pointer(pointer_path)
            if (
                current.get("request_id") == pointer.get("request_id")
                and current.get("activation_state") == "stable"
            ):
                return child.wait(), None
            time.sleep(0.1)
        _terminate_child(
            child,
            run_root=run_root,
            candidate_pointer=pointer,
        )
        attempts_path = (
            run_root
            / BOOT_ATTEMPTS_DIR_NAME
            / f"{pointer['request_id']}.json"
        )
        attempt_payload = _read_pointer(attempts_path)
        restored = _rollback_candidate(
            run_root=run_root,
            pointer_path=pointer_path,
            pointer=pointer,
            attempts=int(attempt_payload["attempts"]),
            reason="startup_timeout",
        )
        return None, restored
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def main() -> int:
    run_root = _run_root()
    pointer_path = run_root / POINTER_NAME
    pointer = _read_pointer(pointer_path)
    pointer = _candidate_or_rollback(
        run_root=run_root,
        pointer_path=pointer_path,
        pointer=pointer,
    )
    bootstrap_path = Path(str(pointer.get("bootstrap_path") or ""))
    bootstrap_sha = pointer.get("bootstrap_sha256")
    if not _is_sha256(bootstrap_sha):
        raise RuntimeError("supervisor bootstrap digest is invalid")
    expected_parent = (run_root / BOOTSTRAPS_DIR_NAME).resolve()
    if bootstrap_path.parent.resolve() != expected_parent:
        raise RuntimeError("supervisor bootstrap escaped the versioned directory")
    if bootstrap_path.name != f"{bootstrap_sha}.py":
        raise RuntimeError("supervisor bootstrap is not content-addressed")
    _private_regular(bootstrap_path)
    observed = _sha256(bootstrap_path)
    if observed != bootstrap_sha:
        raise RuntimeError(
            f"supervisor bootstrap digest mismatch expected={bootstrap_sha} "
            f"observed={observed}"
        )
    if pointer.get("activation_state") == "candidate":
        returncode, restored = _supervise_candidate(
            run_root=run_root,
            pointer_path=pointer_path,
            pointer=pointer,
            bootstrap_path=bootstrap_path,
        )
        if returncode is not None:
            return returncode
        if restored is None:  # pragma: no cover - type narrowing
            raise RuntimeError("candidate supervisor returned no rollback release")
        pointer = restored
        bootstrap_path = Path(str(pointer.get("bootstrap_path") or ""))
        bootstrap_sha = pointer.get("bootstrap_sha256")
        if not _is_sha256(bootstrap_sha):
            raise RuntimeError("rollback bootstrap digest is invalid")
        _private_regular(bootstrap_path)
        if _sha256(bootstrap_path) != bootstrap_sha:
            raise RuntimeError("rollback bootstrap digest mismatch")
    runpy.run_path(str(bootstrap_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
