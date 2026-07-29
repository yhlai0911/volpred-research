#!/usr/bin/env python3
"""Transactional old-launchd to immutable-release supervisor cutover.

The repository plist is only a template; editing it does not change launchd's
loaded job.  This installer closes that deployment gap as one bounded
transaction:

1. refuse while a worker or PHASE-Z closeout is active;
2. materialize and verify the committed immutable release/bootstrap chain;
3. arm a candidate pointer and initialize/reconcile global producer custody;
4. atomically install and reload the LaunchAgent;
5. prove the new boot's exact release/plist identity and a later heartbeat;
6. on failure, stop first and prove absence before restoring the prior boot.

The same transaction also repairs an already-cut-over host when its committed
release or installed/loaded plist drifted.  A rollback that cannot be proved
retains both the cutover fence and ``auth_blocked`` rather than reopening work.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dispatch_supervisor import (
    custody_receipt,
    deferred_reload,
    procutil,
    release_image,
    state,
)
from volpred.ops.diagnostics import warn

LABEL = "com.volpred.dispatch-supervisor"
PLIST_SOURCE = ROOT / "ops" / "launchd" / f"{LABEL}.plist"
PLIST_DESTINATION = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


class CutoverError(RuntimeError):
    """The immutable supervisor cutover failed."""

    def __init__(
        self,
        message: str,
        *,
        rollback_verified: bool = False,
    ) -> None:
        super().__init__(message)
        self.rollback_verified = bool(rollback_verified)


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
    transaction: dict[str, bool] = {
        "mutation_armed": False,
        "legacy_custody_unresolved": False,
    }
    release_fence = False
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
            transaction=transaction,
        )
        release_fence = True
    except Exception as exc:
        release_fence = not transaction["mutation_armed"] or (
            isinstance(exc, CutoverError)
            and exc.rollback_verified
            and not transaction["legacy_custody_unresolved"]
        )
        if not release_fence:
            _retain_failed_cutover_fence(
                token=str(quiesce["token"]),
                state_path=Path(state_path),
                ttl_s=quiesce_ttl_s,
            )
        raise
    finally:
        if release_fence:
            released = state.end_cutover_quiesce(
                token=str(quiesce["token"]),
                path=Path(state_path),
            )
            if not released and sys.exc_info()[0] is None:
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
    launchctl_fn: Callable[[list[str], bool], subprocess.CompletedProcess[str]] | None,
    sleep_fn: Callable[[float], None],
    quiesce_token: str,
    quiesce_ttl_s: int,
    transaction: dict[str, bool],
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
    expected_plist = _committed_plist_payload(
        repo_root=Path(repo_root),
        release_commit=str(request["release_commit"]),
        plist_source=Path(plist_source),
    )
    _validate_new_plist(expected_plist, request=request)
    pointer_path = request_root / release_image.POINTER_NAME
    prior_pointer = release_image._read_pointer(pointer_path)
    runner = launchctl_fn or _launchctl
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    if prior_pointer is not None and _already_live(
        before,
        prior_pointer,
        current_release=request,
        expected_plist=expected_plist,
        plist_destination=Path(plist_destination),
        repo_root=Path(repo_root),
        runner=runner,
        service=service,
    ):
        return {
            "status": "already_cut_over",
            "request_id": prior_pointer["request_id"],
            "release_sha256": prior_pointer["release_sha256"],
        }

    old_plist = plist_destination.read_bytes() if plist_destination.exists() else None
    old_mode = (
        stat.S_IMODE(plist_destination.stat().st_mode)
        if plist_destination.exists()
        else 0o644
    )
    legacy_pid = before.get("supervisor_pid")
    legacy_custody = procutil.capture_existing_producer_custody(legacy_pid)
    if legacy_custody is None:
        raise CutoverError(
            "legacy supervisor coalition was not a clean, verified ancestry"
        )
    mutation_receipt = request_root / "cutover_receipts" / "in_progress.json"
    try:
        # Arm durable mutation intent before changing the pointer or invoking
        # launchctl.  Any timeout after an external call is therefore treated
        # as a possibly-applied mutation and must prove rollback.
        _write_receipt(
            mutation_receipt,
            {
                "schema_version": 1,
                "status": "mutation_armed",
                "request_id": request["request_id"],
                "release_sha256": request["release_sha256"],
                "previous_request_id": (
                    prior_pointer.get("request_id")
                    if prior_pointer is not None
                    else None
                ),
                "armed_at": datetime.now(UTC).isoformat(),
            },
        )
        transaction["mutation_armed"] = True
        release_image.activate(
            run_root=request_root,
            request=request,
        )
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
        transaction["legacy_custody_unresolved"] = True
        stopped = runner(["launchctl", "bootout", service], False)
        if stopped.returncode != 0 and not _service_absent(stopped.stderr or ""):
            raise CutoverError(
                f"cannot unload legacy scheduler: {(stopped.stderr or '')[:300]}"
            )
        absence_error = _wait_service_absent(
            runner=runner,
            service=service,
            state_path=Path(state_path),
            timeout_s=min(30.0, timeout_s),
            sleep_fn=sleep_fn,
            quiesce_token=quiesce_token,
            quiesce_ttl_s=quiesce_ttl_s,
        )
        if absence_error:
            raise CutoverError(absence_error)
        legacy_members = procutil.producer_cohort_members_checked(
            0,
            job_id="legacy-cutover",
            custody=legacy_custody,
        )
        if legacy_members != []:
            raise CutoverError(
                "legacy supervisor coalition drain was not positively verified: "
                f"members={legacy_members}"
            )
        transaction["legacy_custody_unresolved"] = False
        final_gate = state.cutover_quiesce_snapshot(
            token=quiesce_token,
            path=Path(state_path),
        )
        if final_gate["active_count"] != 0:
            raise CutoverError(
                "new work appeared after cutover quiesce was established"
            )
        custody_receipt.initialize_producer_custody_ledger(
            Path(repo_root),
            migration_confirmed_quiescent=True,
        )
        custody_recovery = custody_receipt.reconcile_pending_producer_custodies(
            Path(repo_root)
        )
        if not custody_recovery.get("ok"):
            raise CutoverError(
                "global producer custody reconciliation remained unresolved"
            )
        if custody_receipt.read_pending_producer_custodies(Path(repo_root)):
            raise CutoverError("global producer custody ledger remained non-empty")
        state.write_planned_restart_marker(
            reason="immutable_release_initial_cutover",
            path=Path(state_path).parent / "supervisor_restart_marker.json",
        )
        _atomic_install(plist_destination, expected_plist, mode=0o644)
        bootstrap = runner(
            ["launchctl", "bootstrap", domain, str(plist_destination)],
            True,
        )
        if bootstrap.returncode != 0:
            raise CutoverError(
                f"launchctl bootstrap failed: {(bootstrap.stderr or '')[:300]}"
            )
        observed = _wait_new_release_ready(
            runner=runner,
            service=service,
            request=request,
            before=before,
            expected_plist=expected_plist,
            plist_destination=Path(plist_destination),
            state_path=Path(state_path),
            timeout_s=float(timeout_s),
            sleep_fn=sleep_fn,
            quiesce_token=quiesce_token,
            quiesce_ttl_s=quiesce_ttl_s,
        )
        release_image.promote(run_root=request_root, request=request)
        promoted = release_image._read_pointer(pointer_path)
        if not _pointer_names(promoted, request, activation_state="stable"):
            raise CutoverError(
                "release pointer promotion did not read back exact identity"
            )
        receipt = {
            "schema_version": 1,
            "status": "completed",
            "request_id": request["request_id"],
            "release_sha256": request["release_sha256"],
            "release_commit": request["release_commit"],
            "bootstrap_sha256": request["bootstrap_sha256"],
            "stage0_sha256": request["stage0_sha256"],
            "completed_at": datetime.now(UTC).isoformat(),
            "supervisor_started_at": observed.get("supervisor_started_at"),
            "supervisor_ready_heartbeat_at": observed.get("last_heartbeat_at"),
        }
        _write_receipt(
            request_root / "cutover_receipts" / "latest.json",
            receipt,
        )
        _write_receipt(
            mutation_receipt,
            {
                **receipt,
                "status": "completed_verified",
            },
        )
        return receipt
    except Exception as exc:
        if not transaction["mutation_armed"]:
            raise
        try:
            rollback_error = _restore_legacy_launchd(
                runner=runner,
                domain=domain,
                service=service,
                request_root=request_root,
                plist_destination=plist_destination,
                old_plist=old_plist,
                old_mode=old_mode,
                before=before,
                prior_pointer=prior_pointer,
                state_path=Path(state_path),
                timeout_s=float(timeout_s),
                sleep_fn=sleep_fn,
                quiesce_token=quiesce_token,
                quiesce_ttl_s=quiesce_ttl_s,
            )
        except Exception as rollback_exc:  # noqa: BLE001 - retain ambiguity
            rollback_error = (
                f"rollback raised {type(rollback_exc).__name__}: {rollback_exc}"
            )[:500]
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
        _write_receipt(
            mutation_receipt,
            {
                "schema_version": 1,
                "status": (
                    "rollback_ambiguous" if rollback_error else "rolled_back_verified"
                ),
                "request_id": request["request_id"],
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "rollback_error": rollback_error,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        if rollback_error:
            raise CutoverError(
                f"{type(exc).__name__}: {exc}; rollback failed: {rollback_error}",
                rollback_verified=False,
            ) from exc
        raise CutoverError(
            f"{type(exc).__name__}: {exc}; rollback verified",
            rollback_verified=True,
        ) from exc


def _state_matches(
    observed: dict[str, Any],
    release: dict[str, Any],
) -> bool:
    return (
        observed.get("supervisor_release_id") == release.get("request_id")
        and observed.get("supervisor_release_sha256") == release.get("release_sha256")
        and observed.get("supervisor_release_commit") == release.get("release_commit")
        and observed.get("supervisor_bootstrap_sha256")
        == release.get("bootstrap_sha256")
    )


def _already_live(
    observed: dict[str, Any],
    release: dict[str, Any],
    *,
    current_release: dict[str, Any],
    expected_plist: bytes,
    plist_destination: Path,
    repo_root: Path,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    service: str,
) -> bool:
    if release.get("activation_state") != "stable":
        return False
    if not _same_release(release, current_release):
        return False
    if not _state_matches(observed, release):
        return False
    heartbeat = observed.get("last_heartbeat_at")
    if not isinstance(heartbeat, str):
        return False
    try:
        age_s = (datetime.now(UTC) - datetime.fromisoformat(heartbeat)).total_seconds()
    except (TypeError, ValueError):
        return False  # silent-ok: malformed heartbeat means not live
    if age_s < 0 or age_s > 180:
        return False
    if not _has_post_startup_heartbeat(observed):
        return False
    try:
        if plist_destination.read_bytes() != expected_plist:
            return False
        if custody_receipt.read_pending_producer_custodies(repo_root):
            return False
    except (OSError, custody_receipt.CustodyReceiptError) as exc:
        warn(
            "dispatch_cutover_readback",
            "stable release custody/plist readback failed",
            reason=type(exc).__name__,
        )
        return False
    status = runner(["launchctl", "print", service], False)
    return _loaded_contract_matches(
        status,
        plist_payload=expected_plist,
        required_stage0=str(release.get("stage0_path") or ""),
    )


def _restore_legacy_launchd(
    *,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    domain: str,
    service: str,
    request_root: Path,
    plist_destination: Path,
    old_plist: bytes | None,
    old_mode: int,
    before: dict[str, Any],
    prior_pointer: dict[str, Any] | None,
    state_path: Path,
    timeout_s: float,
    sleep_fn: Callable[[float], None],
    quiesce_token: str,
    quiesce_ttl_s: int,
) -> str | None:
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
    absence_error = _wait_service_absent(
        runner=runner,
        service=service,
        state_path=state_path,
        timeout_s=timeout_s,
        sleep_fn=sleep_fn,
        quiesce_token=quiesce_token,
        quiesce_ttl_s=quiesce_ttl_s,
    )
    if absence_error:
        bootout_detail = (
            f"bootout rc={bootout.returncode}: {(bootout.stderr or '')[:200]}; "
            if bootout.returncode != 0
            else ""
        )
        return f"rollback {bootout_detail}{absence_error}"[:500]
    try:
        release_image.restore_pointer(
            run_root=request_root,
            previous=prior_pointer,
        )
        if old_plist is None:
            try:
                plist_destination.unlink()
            except FileNotFoundError:
                pass  # silent-ok: verified absence follows below
        else:
            _atomic_install(plist_destination, old_plist, mode=old_mode)
    except Exception as exc:  # noqa: BLE001 - rollback must report restore failure
        return f"rollback restore raised {type(exc).__name__}: {exc}"[:500]
    restored_pointer = release_image._read_pointer(
        request_root / release_image.POINTER_NAME
    )
    if not _pointer_restored(restored_pointer, prior_pointer):
        return "rollback pointer readback did not match previous identity"
    if old_plist is None:
        if plist_destination.exists():
            return "rollback plist absence readback failed"
        return None
    if plist_destination.read_bytes() != old_plist:
        return "rollback plist byte readback did not match previous bytes"
    try:
        _parse_plist(old_plist)
    except CutoverError as exc:
        return f"rollback legacy plist cannot be read back exactly: {exc}"[:500]
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
            observed.get("supervisor_started_at") != before.get("supervisor_started_at")
            and isinstance(heartbeat, str)
            and heartbeat != before.get("last_heartbeat_at")
        )
        if (
            _loaded_contract_matches(status, plist_payload=old_plist)
            and identity_matches
            and restarted
            and plist_destination.read_bytes() == old_plist
            and _pointer_restored(
                release_image._read_pointer(request_root / release_image.POINTER_NAME),
                prior_pointer,
            )
        ):
            return None
        sleep_fn(0.25)
    return "legacy launchd readback did not prove fresh heartbeat and identity"


def _wait_service_absent(
    *,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    service: str,
    state_path: Path,
    timeout_s: float,
    sleep_fn: Callable[[float], None],
    quiesce_token: str,
    quiesce_ttl_s: int,
) -> str | None:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        try:
            state.renew_cutover_quiesce(
                token=quiesce_token,
                ttl_s=quiesce_ttl_s,
                path=state_path,
            )
        except Exception as exc:  # noqa: BLE001 - absence proof needs its fence
            return (
                "quiesce renewal failed during launchd absence proof: "
                f"{type(exc).__name__}: {exc}"
            )[:500]
        try:
            observed = runner(["launchctl", "print", service], False)
        except Exception as exc:  # noqa: BLE001 - runner failure is ambiguous
            return (f"launchd absence probe raised {type(exc).__name__}: {exc}")[:500]
        if observed.returncode != 0:
            if _service_absent(observed.stderr or ""):
                return None
            return (
                "cannot verify launchd service absence: "
                f"{(observed.stderr or '')[:300]}"
            )
        sleep_fn(0.25)
    return "launchd service remained loaded after bootout timeout"


def _wait_new_release_ready(
    *,
    runner: Callable[[list[str], bool], subprocess.CompletedProcess[str]],
    service: str,
    request: dict[str, Any],
    before: dict[str, Any],
    expected_plist: bytes,
    plist_destination: Path,
    state_path: Path,
    timeout_s: float,
    sleep_fn: Callable[[float], None],
    quiesce_token: str,
    quiesce_ttl_s: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    first_heartbeat: str | None = None
    first_started_at: str | None = None
    while time.monotonic() < deadline:
        state.renew_cutover_quiesce(
            token=quiesce_token,
            ttl_s=quiesce_ttl_s,
            path=state_path,
        )
        observed = state.read_state(state_path)
        loaded = runner(["launchctl", "print", service], False)
        started_at = observed.get("supervisor_started_at")
        heartbeat = observed.get("last_heartbeat_at")
        exact_boot = (
            _state_matches(observed, request)
            and isinstance(started_at, str)
            and started_at != before.get("supervisor_started_at")
            and isinstance(heartbeat, str)
            and heartbeat != before.get("last_heartbeat_at")
            and plist_destination.read_bytes() == expected_plist
            and _loaded_contract_matches(
                loaded,
                plist_payload=expected_plist,
                required_stage0=str(request["stage0_path"]),
            )
        )
        if exact_boot:
            if first_started_at != started_at:
                first_started_at = started_at
                first_heartbeat = heartbeat
            elif heartbeat != first_heartbeat:
                return observed
        else:
            first_started_at = None
            first_heartbeat = None
        sleep_fn(0.25)
    raise CutoverError(
        "new launchd job did not prove post-startup heartbeat and exact "
        "release/plist identity"
    )


def _committed_plist_payload(
    *,
    repo_root: Path,
    release_commit: str,
    plist_source: Path,
) -> bytes:
    source_payload = plist_source.read_bytes()
    if release_commit == "test-fixture":
        return source_payload
    relative = Path("ops") / "launchd" / f"{LABEL}.plist"
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show",
            f"{release_commit}:{relative.as_posix()}",
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace")
        raise CutoverError(f"cannot read committed launchd plist: {detail[:300]}")
    committed = bytes(completed.stdout)
    if source_payload != committed:
        raise CutoverError(
            "launchd plist source differs from the immutable release commit"
        )
    return committed


def _validate_new_plist(
    payload: bytes,
    *,
    request: dict[str, Any],
) -> None:
    parsed = _parse_plist(payload)
    if parsed["Label"] != LABEL:
        raise CutoverError("launchd plist Label does not match supervisor")
    if str(request["stage0_path"]) not in parsed["ProgramArguments"]:
        raise CutoverError("launchd plist does not execute the materialized stage-0")
    environment = parsed["EnvironmentVariables"]
    if environment.get("VOLPRED_CODEX_FAILOVER") != "0":
        raise CutoverError("launchd plist must set VOLPRED_CODEX_FAILOVER=0")
    if environment.get("VOLPRED_WRITER_ISOLATION_REQUIRED") != "1":
        raise CutoverError("launchd plist must require writer isolation")


def _parse_plist(payload: bytes) -> dict[str, Any]:
    try:
        parsed = plistlib.loads(payload)
    except Exception as exc:
        raise CutoverError(
            f"launchd plist is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise CutoverError("launchd plist root must be a mapping")
    arguments = parsed.get("ProgramArguments")
    working_directory = parsed.get("WorkingDirectory")
    environment = parsed.get("EnvironmentVariables")
    if (
        not isinstance(parsed.get("Label"), str)
        or not isinstance(arguments, list)
        or not arguments
        or not all(isinstance(value, str) and value for value in arguments)
        or not isinstance(working_directory, str)
        or not working_directory
        or not isinstance(environment, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment.items()
        )
    ):
        raise CutoverError(
            "launchd plist lacks exact Label/ProgramArguments/"
            "WorkingDirectory/EnvironmentVariables contract"
        )
    return parsed


def _loaded_contract_matches(
    status: subprocess.CompletedProcess[str],
    *,
    plist_payload: bytes,
    required_stage0: str | None = None,
) -> bool:
    if status.returncode != 0:
        return False
    try:
        parsed = _parse_plist(plist_payload)
    except CutoverError as exc:
        warn(
            "dispatch_cutover_readback",
            "loaded launchd contract could not parse committed plist",
            reason=str(exc),
        )
        return False
    lines = {
        line.strip() for line in (status.stdout or "").splitlines() if line.strip()
    }
    if "state = running" not in lines:
        return False
    if f"working directory = {parsed['WorkingDirectory']}" not in lines:
        return False
    if not all(argument in lines for argument in parsed["ProgramArguments"]):
        return False
    if not all(
        f"{key} => {value}" in lines
        for key, value in parsed["EnvironmentVariables"].items()
    ):
        return False
    return not required_stage0 or required_stage0 in lines


def _same_release(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    return all(
        left.get(key) == right.get(key)
        for key in (
            "release_archive",
            "release_sha256",
            "release_commit",
            "bootstrap_path",
            "bootstrap_sha256",
            "stage0_path",
            "stage0_sha256",
        )
    )


def _has_post_startup_heartbeat(observed: dict[str, Any]) -> bool:
    started_at = observed.get("supervisor_started_at")
    heartbeat = observed.get("last_heartbeat_at")
    if not isinstance(started_at, str) or not isinstance(heartbeat, str):
        return False
    try:
        elapsed_s = (
            datetime.fromisoformat(heartbeat) - datetime.fromisoformat(started_at)
        ).total_seconds()
    except (TypeError, ValueError) as exc:
        warn(
            "dispatch_cutover_readback",
            "supervisor heartbeat timestamp contract is malformed",
            reason=type(exc).__name__,
        )
        return False
    # mark_supervisor_started writes these via two adjacent _now() calls.
    # Requiring a full second distinguishes a later health-loop beat from
    # that pre-recovery startup pair without depending on exact equality.
    return elapsed_s >= 1.0


def _pointer_names(
    pointer: dict[str, Any] | None,
    request: dict[str, Any],
    *,
    activation_state: str,
) -> bool:
    return (
        pointer is not None
        and pointer.get("activation_state") == activation_state
        and pointer.get("request_id") == request.get("request_id")
        and _same_release(pointer, request)
    )


def _pointer_restored(
    observed: dict[str, Any] | None,
    expected: dict[str, Any] | None,
) -> bool:
    if expected is None:
        return observed is None
    return observed == expected


def _retain_failed_cutover_fence(
    *,
    token: str,
    state_path: Path,
    ttl_s: int,
) -> None:
    # Move auth_blocked_at away from legacy_fence_at before retaining the
    # quiesce.  If its bounded token later expires, state cleanup will not
    # silently reopen admission after an ambiguous rollback.
    state.set_auth_blocked(True, path=state_path)
    try:
        state.renew_cutover_quiesce(
            token=token,
            ttl_s=ttl_s,
            path=state_path,
        )
    except (OSError, RuntimeError, ValueError):
        return  # silent-ok: auth_blocked is the durable fail-closed fallback


def _service_absent(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "could not find service",
            "no such process",
            "not found",
            "not loaded",
        )
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
