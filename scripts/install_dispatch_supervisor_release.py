#!/usr/bin/env python3
"""Transactional old-launchd to immutable-release supervisor cutover.

The repository plist is only a template; editing it does not change launchd's
loaded job.  This installer closes that deployment gap as one bounded
transaction:

1. refuse while a worker or PHASE-Z closeout is active;
2. materialize and verify the committed immutable release/bootstrap chain;
3. seed the first stable release pointer;
4. atomically install and reload the LaunchAgent;
5. read back the new boot's exact release identity;
6. restore the previous plist, pointer, and loaded job on any failure.

Normal later releases use ``reload_dispatch_supervisor.sh --defer``.  This
script exists for the one-time legacy ProgramArguments cutover and is safe to
re-run after a verified cutover.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.dispatch_supervisor import deferred_reload, release_image, state

LABEL = "com.volpred.dispatch-supervisor"
ROOT = Path(__file__).resolve().parents[1]
PLIST_SOURCE = ROOT / "ops" / "launchd" / f"{LABEL}.plist"
PLIST_DESTINATION = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


class CutoverError(RuntimeError):
    """The immutable supervisor cutover failed and was rolled back."""


def cutover(
    *,
    repo_root: Path = ROOT,
    state_path: Path = state.STATE_PATH,
    run_root: Path | None = None,
    plist_source: Path = PLIST_SOURCE,
    plist_destination: Path = PLIST_DESTINATION,
    timeout_s: float = 120.0,
    materialize_fn: Callable[..., dict[str, str]] = release_image.materialize,
    launchctl_fn: Callable[[list[str], bool], subprocess.CompletedProcess[str]]
    | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    timeout_s = float(timeout_s)
    if not 0.1 <= timeout_s <= 600:
        raise ValueError("timeout_s must be between 0.1 and 600 seconds")
    quiesce_ttl_s = max(300, int(3 * timeout_s + 180))
    quiesce = state.begin_cutover_quiesce(
        reason="immutable_release_initial_cutover",
        ttl_s=quiesce_ttl_s,
        path=Path(state_path),
    )
    try:
        result = _cutover_quiesced(
            repo_root=repo_root,
            state_path=state_path,
            run_root=run_root,
            plist_source=plist_source,
            plist_destination=plist_destination,
            timeout_s=timeout_s,
            materialize_fn=materialize_fn,
            launchctl_fn=launchctl_fn,
            sleep_fn=sleep_fn,
            quiesce_token=str(quiesce["token"]),
            quiesce_ttl_s=quiesce_ttl_s,
        )
    finally:
        released = state.end_cutover_quiesce(
            token=str(quiesce["token"]),
            path=Path(state_path),
        )
    if not released:
        raise CutoverError("supervisor cutover quiesce ownership was lost")
    return result


def _cutover_quiesced(
    *,
    repo_root: Path,
    state_path: Path,
    run_root: Path | None,
    plist_source: Path,
    plist_destination: Path,
    timeout_s: float,
    materialize_fn: Callable[..., dict[str, str]],
    launchctl_fn: Callable[[list[str], bool], subprocess.CompletedProcess[str]]
    | None,
    sleep_fn: Callable[[float], None],
    quiesce_token: str,
    quiesce_ttl_s: int,
) -> dict[str, Any]:
    request_root = Path(run_root) if run_root else deferred_reload.default_root()
    drain_deadline = time.monotonic() + float(timeout_s)
    while True:
        state.renew_cutover_quiesce(
            token=quiesce_token,
            ttl_s=quiesce_ttl_s,
            path=Path(state_path),
        )
        drain = state.cutover_quiesce_snapshot(
            token=quiesce_token,
            path=Path(state_path),
        )
        if drain["active_count"] == 0:
            break
        if time.monotonic() >= drain_deadline:
            raise CutoverError(
                "supervisor cutover timed out waiting for active work to drain"
            )
        sleep_fn(0.25)
    before = state.read_state(Path(state_path))
    release = materialize_fn(
        repo_root=Path(repo_root),
        run_root=request_root,
    )
    request = {
        "request_id": secrets.token_hex(32),
        **release,
    }
    pointer_path = request_root / release_image.POINTER_NAME
    prior_pointer = release_image._read_pointer(pointer_path)
    runner = launchctl_fn or _launchctl
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    if prior_pointer is not None and _already_live(
        before,
        prior_pointer,
        runner=runner,
        service=service,
    ):
        return {
            "status": "already_cut_over",
            "request_id": prior_pointer["request_id"],
            "release_sha256": prior_pointer["release_sha256"],
        }
    if prior_pointer is not None:
        # A prior cutover may have installed the durable pointer and then lost
        # its caller before launchctl convergence. Resume that exact identity;
        # never mint a second pointer over ambiguous state.
        request = {
            key: value
            for key, value in prior_pointer.items()
            if key
            in {
                "request_id",
                "release_archive",
                "release_sha256",
                "release_commit",
                "bootstrap_path",
                "bootstrap_sha256",
                "stage0_path",
                "stage0_sha256",
            }
        }

    old_plist = (
        plist_destination.read_bytes() if plist_destination.exists() else None
    )
    old_mode = (
        stat.S_IMODE(plist_destination.stat().st_mode)
        if plist_destination.exists()
        else 0o644
    )
    installed = False
    launchd_touched = False
    if prior_pointer is None:
        release_image.install_initial_stable(
            run_root=request_root,
            request=request,
        )
    try:
        state.renew_cutover_quiesce(
            token=quiesce_token,
            ttl_s=quiesce_ttl_s,
            path=Path(state_path),
        )
        # This is the backward-compatible reservation barrier.  The loaded
        # pre-cutover reserve_fire cannot understand the new quiesce field, so
        # unload the old scheduler before the final state CAS.  Workers have
        # already drained; any old decision that races into a reservation is
        # now visible to the final gate and triggers legacy restoration.
        stopped = runner(["launchctl", "bootout", service], False)
        if stopped.returncode != 0 and not _service_absent(stopped.stderr or ""):
            raise CutoverError(
                f"cannot unload legacy scheduler: {(stopped.stderr or '')[:300]}"
            )
        launchd_touched = True
        still_loaded = runner(["launchctl", "print", service], False)
        if still_loaded.returncode == 0:
            raise CutoverError("legacy scheduler remained loaded after bootout")
        final_gate = state.cutover_quiesce_snapshot(
            token=quiesce_token,
            path=Path(state_path),
        )
        if final_gate["active_count"] != 0:
            raise CutoverError(
                "new work appeared after cutover quiesce was established"
            )
        state.write_planned_restart_marker(
            reason="immutable_release_initial_cutover",
            path=Path(state_path).parent / "supervisor_restart_marker.json",
        )
        _atomic_install(plist_destination, plist_source.read_bytes(), mode=0o644)
        installed = True
        bootstrap = runner(
            ["launchctl", "bootstrap", domain, str(plist_destination)],
            True,
        )
        if bootstrap.returncode != 0:
            raise CutoverError(
                f"launchctl bootstrap failed: {(bootstrap.stderr or '')[:300]}"
            )
        deadline = time.monotonic() + float(timeout_s)
        state.renew_cutover_quiesce(
            token=quiesce_token,
            ttl_s=quiesce_ttl_s,
            path=Path(state_path),
        )
        while time.monotonic() < deadline:
            state.renew_cutover_quiesce(
                token=quiesce_token,
                ttl_s=quiesce_ttl_s,
                path=Path(state_path),
            )
            observed = state.read_state(Path(state_path))
            loaded = runner(["launchctl", "print", service], False)
            stage0_loaded = (
                loaded.returncode == 0
                and str(request["stage0_path"]) in (loaded.stdout or "")
            )
            if _state_matches(observed, request) and stage0_loaded:
                receipt = {
                    "schema_version": 1,
                    "status": "completed",
                    "request_id": request["request_id"],
                    "release_sha256": request["release_sha256"],
                    "release_commit": request["release_commit"],
                    "bootstrap_sha256": request["bootstrap_sha256"],
                    "completed_at": datetime.now(UTC).isoformat(),
                    "supervisor_started_at": observed.get(
                        "supervisor_started_at"
                    ),
                }
                _write_receipt(
                    request_root / "cutover_receipts" / "latest.json",
                    receipt,
                )
                return receipt
            sleep_fn(0.25)
        raise CutoverError("new launchd job did not acknowledge its release identity")
    except Exception as exc:
        release_image.restore_pointer(
            run_root=request_root,
            previous=prior_pointer,
        )
        if installed:
            if old_plist is None:
                try:
                    plist_destination.unlink()
                except FileNotFoundError:
                    pass  # silent-ok: rollback removal is idempotent
            else:
                _atomic_install(plist_destination, old_plist, mode=old_mode)
        rollback_error = _restore_legacy_launchd(
            runner=runner,
            domain=domain,
            service=service,
            plist_destination=plist_destination,
            old_plist=old_plist,
            before=before,
            prior_pointer=prior_pointer,
            state_path=Path(state_path),
            timeout_s=float(timeout_s),
            sleep_fn=sleep_fn,
            launchd_touched=launchd_touched,
            quiesce_token=quiesce_token,
            quiesce_ttl_s=quiesce_ttl_s,
        )
        rollback_status = "rollback_failed" if rollback_error else "rolled_back"
        _write_receipt(
            request_root / "cutover_receipts" / "latest_rollback.json",
            {
                "schema_version": 1,
                "status": rollback_status,
                "request_id": request["request_id"],
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "rollback_error": rollback_error,
                "rolled_back_at": datetime.now(UTC).isoformat(),
            },
        )
        if rollback_error:
            raise CutoverError(
                f"{type(exc).__name__}: {exc}; rollback failed: {rollback_error}"
            ) from exc
        if isinstance(exc, CutoverError):
            raise
        raise CutoverError(f"cutover failed and was rolled back: {exc}") from exc


def _state_matches(
    observed: dict[str, Any],
    release: dict[str, Any],
) -> bool:
    return (
        observed.get("supervisor_release_id") == release.get("request_id")
        and observed.get("supervisor_release_sha256")
        == release.get("release_sha256")
        and observed.get("supervisor_release_commit")
        == release.get("release_commit")
        and observed.get("supervisor_bootstrap_sha256")
        == release.get("bootstrap_sha256")
    )


def _already_live(
    observed: dict[str, Any],
    release: dict[str, Any],
    *,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    service: str,
) -> bool:
    if not _state_matches(observed, release):
        return False
    heartbeat = observed.get("last_heartbeat_at")
    if not isinstance(heartbeat, str):
        return False
    try:
        age_s = (
            datetime.now(UTC) - datetime.fromisoformat(heartbeat)
        ).total_seconds()
    except (TypeError, ValueError):
        return False  # silent-ok: malformed heartbeat means not live
    if age_s < 0 or age_s > 180:
        return False
    status = runner(["launchctl", "print", service], False)
    return (
        status.returncode == 0
        and str(release.get("stage0_path") or "") in (status.stdout or "")
    )


def _restore_legacy_launchd(
    *,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    domain: str,
    service: str,
    plist_destination: Path,
    old_plist: bytes | None,
    before: dict[str, Any],
    prior_pointer: dict[str, Any] | None,
    state_path: Path,
    timeout_s: float,
    sleep_fn: Callable[[float], None],
    launchd_touched: bool,
    quiesce_token: str,
    quiesce_ttl_s: int,
) -> str | None:
    if not launchd_touched:
        return None
    try:
        state.renew_cutover_quiesce(
            token=quiesce_token,
            ttl_s=quiesce_ttl_s,
            path=state_path,
        )
    except Exception as exc:  # noqa: BLE001 - rollback must report fence loss
        return f"rollback quiesce renewal failed: {type(exc).__name__}: {exc}"[:500]
    try:
        bootout = runner(["launchctl", "bootout", service], False)
    except Exception as exc:  # noqa: BLE001 - rollback must report runner failure
        return f"rollback bootout raised {type(exc).__name__}: {exc}"[:500]
    bootout_detail = (bootout.stderr or "").lower()
    not_loaded = _service_absent(bootout_detail)
    if bootout.returncode != 0 and not not_loaded:
        return (
            f"rollback bootout rc={bootout.returncode}: "
            f"{(bootout.stderr or '')[:300]}"
        )
    if old_plist is None:
        return None
    try:
        bootstrap = runner(
            ["launchctl", "bootstrap", domain, str(plist_destination)],
            False,
        )
    except Exception as exc:  # noqa: BLE001 - rollback must report runner failure
        return f"legacy bootstrap raised {type(exc).__name__}: {exc}"[:500]
    if bootstrap.returncode != 0:
        return (
            f"legacy bootstrap rc={bootstrap.returncode}: "
            f"{(bootstrap.stderr or '')[:300]}"
        )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            state.renew_cutover_quiesce(
                token=quiesce_token,
                ttl_s=quiesce_ttl_s,
                path=state_path,
            )
        except Exception as exc:  # noqa: BLE001 - rollback must report fence loss
            return (
                "rollback quiesce renewal failed during readback: "
                f"{type(exc).__name__}: {exc}"
            )[:500]
        status = runner(["launchctl", "print", service], False)
        observed = state.read_state(state_path)
        identity_matches = (
            _state_matches(observed, prior_pointer)
            if prior_pointer is not None
            else all(
                observed.get(key) is None
                for key in (
                    "supervisor_release_id",
                    "supervisor_release_sha256",
                    "supervisor_release_commit",
                    "supervisor_bootstrap_sha256",
                )
            )
        )
        heartbeat = observed.get("last_heartbeat_at")
        restarted = (
            observed.get("supervisor_started_at")
            != before.get("supervisor_started_at")
            and isinstance(heartbeat, str)
            and heartbeat != before.get("last_heartbeat_at")
        )
        if status.returncode == 0 and identity_matches and restarted:
            return None
        sleep_fn(0.25)
    return "legacy launchd readback did not prove fresh heartbeat and identity"


def _service_absent(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in ("could not find service", "no such process", "not found")
    )


def _launchctl(
    command: list[str],
    check: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check,
        timeout=30,
    )


def _atomic_install(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
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


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_install(
        path,
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
        mode=0o600,
    )


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Install the immutable dispatch-supervisor launchd release"
    )
    parser.add_argument("--state", type=Path, default=state.STATE_PATH)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    args = parser.parse_args()
    result = cutover(state_path=args.state, timeout_s=args.timeout_s)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
