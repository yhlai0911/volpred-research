"""Signed, manifest-driven host migration assessment.

This module has no deploy, scheduler, credential-copy, or lease actuator.  It
captures a signed host snapshot, verifies two distinct trusted hosts, validates
formal-effect continuity evidence, and emits a signed *dry-run* remediation
plan.  Primary Authority remains a separate, fenced subsystem.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from volpred.ops.host_attestation import (
    HostAttestationError,
    TrustPolicy,
    challenge_consumption_id,
    ensure_trust_policy_current,
    persist_challenge_evidence,
    sha256_json,
    sign_mapping,
    verify_mapping,
)

SPEC_SCHEMA = "volpred.host-migration-spec.v2"
SNAPSHOT_SCHEMA = "volpred.host-migration-snapshot.v2"
CONTINUITY_SCHEMA = "volpred.host-continuity.v1"
REPORT_SCHEMA = "volpred.host-migration-parity.v2"
PLAN_SCHEMA = "volpred.host-migration-plan.v2"
ATTESTATIONS_SCHEMA = "volpred.host-attestations.v2"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")
_REFERENCE = re.compile(r"(?:receipt|manual|ssh|system-settings)://[A-Za-z0-9._:/#-]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOOL_ORIGINS = frozenset(
    {"application", "home", "homebrew", "repo", "system"}
)
_CROSS_HOST_OUTAGE_SCHEMA = "primary-authority-outage-cross-host.v4"
HOST_MIGRATION_STATE_DIR = Path.home() / ".volpred" / "host_migration"


class HostMigrationError(ValueError):
    """Raised when migration evidence is unsafe, malformed, or untrusted."""


def _raise_attestation(exc: HostAttestationError) -> None:
    raise HostMigrationError(str(exc)) from None


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostMigrationError(f"JSON input unreadable: {exc}") from None
    if not isinstance(value, dict):
        raise HostMigrationError("JSON input must be an object")
    return value


def load_spec(path: Path) -> dict[str, Any]:
    payload = load_json_object(path)
    validate_spec(payload)
    return payload


def _unique_ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise HostMigrationError(f"{field} must be a non-empty list")
    ids = [item.get("id") for item in value if isinstance(item, dict)]
    if len(ids) != len(value) or any(not isinstance(item, str) for item in ids):
        raise HostMigrationError(f"{field} entries require string ids")
    if len(ids) != len(set(ids)):
        raise HostMigrationError(f"{field} ids must be unique")
    return ids


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise HostMigrationError(f"{field} must be text")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise HostMigrationError(f"{field} must be repo-relative")
    return value


def validate_spec(spec: Mapping[str, Any]) -> None:
    if set(spec) != {
        "schema_version",
        "snapshot_max_age_seconds",
        "artifact_groups",
        "ignored_path_names",
        "tools",
        "secret_references",
        "forbidden_agentic_auth_names",
        "permissions",
        "continuity",
    }:
        raise HostMigrationError("migration spec fields must match the v2 contract")
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise HostMigrationError("unsupported migration spec schema")
    max_age = spec["snapshot_max_age_seconds"]
    if type(max_age) is not int or not 60 <= max_age <= 3600:
        raise HostMigrationError("snapshot max age must be 60-3600 seconds")
    _unique_ids(spec["artifact_groups"], "artifact_groups")
    _unique_ids(spec["tools"], "tools")
    secret_ids = set(_unique_ids(spec["secret_references"], "secret_references"))
    permission_ids = set(_unique_ids(spec["permissions"], "permissions"))

    for group in spec["artifact_groups"]:
        if set(group) != {
            "id",
            "paths",
            "required",
            "parity",
            "git_root",
            "git_paths",
            "required_json_schema",
        }:
            raise HostMigrationError(f"invalid artifact group {group.get('id')!r}")
        if type(group["required"]) is not bool:
            raise HostMigrationError("artifact required must be boolean")
        if group["parity"] not in {"sha256", "validated_json"}:
            raise HostMigrationError("unsupported artifact parity mode")
        if not isinstance(group["paths"], list) or not group["paths"]:
            raise HostMigrationError("artifact paths must be non-empty")
        for path in group["paths"]:
            _relative_path(path, field="artifact path")
        if group["parity"] == "sha256":
            _relative_path(group["git_root"], field="artifact git_root")
            if not isinstance(group["git_paths"], list) or not group["git_paths"]:
                raise HostMigrationError("sha256 artifact needs git_paths")
            for path in group["git_paths"]:
                _relative_path(path, field="artifact git path")
            if group["required_json_schema"] is not None:
                raise HostMigrationError("sha256 artifact cannot declare JSON schema")
        else:
            if group["git_root"] is not None or group["git_paths"]:
                raise HostMigrationError("validated JSON is runtime evidence, not Git")
            if not isinstance(group["required_json_schema"], str):
                raise HostMigrationError("validated JSON needs a schema")

    for tool in spec["tools"]:
        if set(tool) != {
            "id",
            "commands",
            "required",
            "parity",
            "allowed_install_origins",
            "functional_permission_id",
        }:
            raise HostMigrationError(f"invalid tool contract {tool.get('id')!r}")
        if tool["parity"] != "exact_sha256":
            raise HostMigrationError("unsupported tool parity")
        if type(tool["required"]) is not bool:
            raise HostMigrationError("tool required must be boolean")
        if not tool["commands"] or not all(
            isinstance(item, str)
            and item
            and not Path(item).is_absolute()
            and "/" not in item
            and "\\" not in item
            for item in tool["commands"]
        ):
            raise HostMigrationError("tool commands are malformed")
        origins = tool["allowed_install_origins"]
        if (
            not isinstance(origins, list)
            or not origins
            or any(item not in _TOOL_ORIGINS for item in origins)
            or len(origins) != len(set(origins))
        ):
            raise HostMigrationError("tool install origins are malformed")
        if tool["functional_permission_id"] not in permission_ids:
            raise HostMigrationError("tool functional permission is unknown")

    for secret in spec["secret_references"]:
        if set(secret) != {
            "id",
            "names",
            "locations",
            "required",
            "reauthorization_permission_id",
        }:
            raise HostMigrationError(
                f"invalid secret reference {secret.get('id')!r}"
            )
        if type(secret["required"]) is not bool:
            raise HostMigrationError("secret required must be boolean")
        if not secret["names"] or not all(
            isinstance(item, str) and _ENV_NAME.fullmatch(item)
            for item in secret["names"]
        ):
            raise HostMigrationError("secret field names are malformed")
        for location in secret["locations"]:
            _relative_path(location, field="secret location")
        if secret["reauthorization_permission_id"] not in permission_ids:
            raise HostMigrationError("secret reauthorization permission is unknown")

    forbidden = spec["forbidden_agentic_auth_names"]
    if not forbidden or not all(
        isinstance(item, str) and _ENV_NAME.fullmatch(item) for item in forbidden
    ):
        raise HostMigrationError("forbidden auth names are malformed")

    for permission in spec["permissions"]:
        if set(permission) != {"id", "required", "probe"}:
            raise HostMigrationError(
                f"invalid permission contract {permission.get('id')!r}"
            )
        if type(permission["required"]) is not bool:
            raise HostMigrationError("permission required must be boolean")
        if permission["probe"] != "signed_manual_attestation":
            raise HostMigrationError("permissions require signed attestations")

    for secret in spec["secret_references"]:
        if secret["id"] not in secret_ids:
            raise HostMigrationError("secret identity mismatch")

    continuity = spec["continuity"]
    if set(continuity) != {
        "receipt_max_age_seconds",
        "rto_seconds_max",
        "rpo_receipts_max",
        "formal_effect_count_min",
        "rollback_steps",
    }:
        raise HostMigrationError("invalid continuity contract")
    for field in (
        "receipt_max_age_seconds",
        "rto_seconds_max",
        "rpo_receipts_max",
        "formal_effect_count_min",
    ):
        if type(continuity[field]) is not int:
            raise HostMigrationError(f"continuity {field} must be an integer")
    if not 60 <= continuity["receipt_max_age_seconds"] <= 86400:
        raise HostMigrationError("continuity receipt age is out of bounds")
    if continuity["rto_seconds_max"] <= 0 or continuity["rpo_receipts_max"] != 0:
        raise HostMigrationError("continuity must require positive RTO and RPO=0")
    if continuity["formal_effect_count_min"] < 1:
        raise HostMigrationError("formal effects cannot be optional")
    if not continuity["rollback_steps"]:
        raise HostMigrationError("rollback steps are required")


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise HostMigrationError(f"{field} must be ISO-8601 text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise HostMigrationError(f"{field} is not ISO-8601") from None
    if parsed.tzinfo is None:
        raise HostMigrationError(f"{field} must include an offset")
    return parsed.astimezone(UTC)


def _fresh(
    value: Any,
    *,
    field: str,
    now: datetime,
    max_age_seconds: int,
) -> datetime:
    observed = _parse_utc(value, field=field)
    delta = (now - observed).total_seconds()
    if delta < -60:
        raise HostMigrationError(f"{field} is in the future")
    if delta > max_age_seconds:
        raise HostMigrationError(f"{field} is stale")
    return observed


def _resolved_inside(root: Path, path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise HostMigrationError(f"artifact path cannot resolve: {exc}") from None
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HostMigrationError("artifact symlink escapes the repo root") from None
    return resolved


def _normalized_file_mode(mode: int) -> str:
    return "100755" if stat.S_IMODE(mode) & 0o111 else "100644"


def _hash_path(
    root: Path,
    path: Path,
    *,
    include_bytes: bool = False,
) -> tuple[str, int, str, str, bytes | None]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise HostMigrationError(f"artifact unreadable: {exc}") from None
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        if Path(target).is_absolute() or ".." in Path(target).parts:
            raise HostMigrationError("artifact symlink target is unsafe")
        _resolved_inside(root, path)
        data = target.encode("utf-8")
        return (
            hashlib.sha256(data).hexdigest(),
            len(data),
            "symlink",
            "120000",
            data if include_bytes else None,
        )
    if not stat.S_ISREG(info.st_mode):
        raise HostMigrationError("artifact must be a regular file or safe symlink")
    digest = hashlib.sha256()
    size = 0
    captured = bytearray() if include_bytes else None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostMigrationError(f"artifact cannot be opened safely: {exc}") from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise HostMigrationError("artifact changed to a non-regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if captured is not None:
                    if size > 16 * 1024 * 1024:
                        raise HostMigrationError(
                            "validated JSON artifact exceeds 16 MiB"
                        )
                    captured.extend(chunk)
            after = os.fstat(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise HostMigrationError("artifact changed while it was captured")
    return (
        digest.hexdigest(),
        size,
        "file",
        _normalized_file_mode(after.st_mode),
        bytes(captured) if captured is not None else None,
    )


def _ignored(path: str, ignored_names: frozenset[str]) -> bool:
    return any(part in ignored_names for part in Path(path).parts)


def _iter_files(
    root: Path,
    paths: Sequence[str],
    ignored_names: frozenset[str],
) -> Iterable[tuple[str, Path]]:
    seen: set[str] = set()
    for relative in paths:
        candidate = root / relative
        if not candidate.exists() and not candidate.is_symlink():
            continue
        entries = (
            [candidate]
            if candidate.is_file() or candidate.is_symlink()
            else sorted(candidate.rglob("*"))
        )
        for entry in entries:
            rel = entry.relative_to(root).as_posix()
            if rel in seen or _ignored(rel, ignored_names):
                continue
            if not entry.is_symlink() and entry.is_dir():
                continue
            seen.add(rel)
            yield rel, entry


def _validate_cross_host_outage_receipt(value: Any) -> bool:
    required = {
        "schema_version",
        "rehearsal_id",
        "authority_key",
        "verified_at",
        "primary_host_id",
        "primary_host_fingerprint",
        "standby_host_id",
        "standby_host_fingerprint",
        "backend_sha256",
        "implementation_sha256",
        "cross_host_readiness_sha256",
        "primary_epoch",
        "standby_epoch",
        "primary_expires_at",
        "standby_acquired_at",
        "database_clock_handoff_seconds",
        "publisher_fence",
        "primary_receipt_sha256",
        "standby_receipt_sha256",
        "successful_authority_claims",
        "duplicate_authority_claims",
        "effect_requests",
        "provider_calls",
        "cross_host_verified",
    }
    if not isinstance(value, dict) or set(value) != required:
        return False
    text_fields = (
        "rehearsal_id",
        "primary_host_id",
        "primary_host_fingerprint",
        "standby_host_id",
        "standby_host_fingerprint",
    )
    if any(
        not isinstance(value[field], str) or not value[field].strip()
        for field in text_fields
    ):
        return False
    if value["primary_host_id"] == value["standby_host_id"]:
        return False
    if value["primary_host_fingerprint"] == value["standby_host_fingerprint"]:
        return False
    expected_authority_key = (
        "operations-core-outage-smoke-"
        + hashlib.sha256(value["rehearsal_id"].encode()).hexdigest()[:32]
    )
    if value["authority_key"] != expected_authority_key:
        return False
    for field in (
        "backend_sha256",
        "implementation_sha256",
        "cross_host_readiness_sha256",
        "primary_receipt_sha256",
        "standby_receipt_sha256",
    ):
        if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
            return False
    if (
        type(value["primary_epoch"]) is not int
        or value["primary_epoch"] < 1
        or type(value["standby_epoch"]) is not int
        or value["standby_epoch"] != value["primary_epoch"] + 1
    ):
        return False
    try:
        primary_expires = _parse_utc(
            value["primary_expires_at"],
            field="primary_expires_at",
        )
        standby_acquired = _parse_utc(
            value["standby_acquired_at"],
            field="standby_acquired_at",
        )
        verified = _parse_utc(value["verified_at"], field="verified_at")
        handoff = _finite_nonnegative_number(
            value["database_clock_handoff_seconds"],
            field="database_clock_handoff_seconds",
        )
    except HostMigrationError:  # silent-ok: malformed receipt means invalid
        return False
    measured = (standby_acquired - primary_expires).total_seconds()
    if measured < 0 or abs(measured - handoff) > 0.001 or verified < standby_acquired:
        return False
    publisher = value["publisher_fence"]
    if not isinstance(publisher, dict) or set(publisher) != {
        "effect_family",
        "owner",
        "generation",
        "changed_at",
    }:
        return False
    if (
        publisher["effect_family"] != "publisher.article.supabase.sync"
        or publisher["owner"] != "operations_core"
        or type(publisher["generation"]) is not int
        or publisher["generation"] < 1
    ):
        return False
    try:
        _parse_utc(publisher["changed_at"], field="publisher_fence.changed_at")
    except HostMigrationError:  # silent-ok: malformed fence time means invalid
        return False
    return (
        value["schema_version"] == _CROSS_HOST_OUTAGE_SCHEMA
        and value["successful_authority_claims"] == 2
        and value["duplicate_authority_claims"] == 0
        and value["effect_requests"] == 0
        and value["provider_calls"] == 0
        and value["cross_host_verified"] is True
    )


def _json_validation(
    data: bytes | None,
    *,
    required_schema: str,
) -> tuple[str | None, bool]:
    if data is None:
        return None, False
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        return None, False
    if not isinstance(value, dict):
        return None, False
    schema = value.get("schema_version")
    actual_schema = schema if isinstance(schema, str) else None
    if required_schema == _CROSS_HOST_OUTAGE_SCHEMA:
        return actual_schema, _validate_cross_host_outage_receipt(value)
    return actual_schema, False


def _capture_artifact_group(
    root: Path,
    group: Mapping[str, Any],
    ignored_names: frozenset[str],
) -> dict[str, Any]:
    missing = [
        relative
        for relative in group["paths"]
        if not (root / relative).exists() and not (root / relative).is_symlink()
    ]
    files: list[dict[str, Any]] = []
    schema_valid = True
    for relative, path in _iter_files(root, group["paths"], ignored_names):
        is_json = group["parity"] == "validated_json"
        digest, byte_count, kind, mode, captured = _hash_path(
            root,
            path,
            include_bytes=is_json,
        )
        actual_schema, json_valid = (
            _json_validation(
                captured,
                required_schema=group["required_json_schema"],
            )
            if is_json
            else (None, None)
        )
        if is_json and not json_valid:
            schema_valid = False
        files.append(
            {
                "path": relative,
                "kind": kind,
                "mode": mode,
                "bytes": byte_count,
                "sha256": digest,
                "json_schema": actual_schema,
                "json_valid": json_valid,
            }
        )
    valid = not missing and bool(files) and schema_valid
    return {
        "id": group["id"],
        "required": group["required"],
        "parity": group["parity"],
        "present": not missing,
        "valid": valid,
        "missing_paths": missing,
        "file_count": len(files),
        "byte_count": sum(item["bytes"] for item in files),
        "tree_sha256": sha256_json(files),
        "files": files,
    }


def _tar_group_files(
    *,
    repo_root: Path,
    group: Mapping[str, Any],
    ignored_names: frozenset[str],
    captured_head: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    git_root = (repo_root / group["git_root"]).resolve()
    try:
        git_root.relative_to(repo_root)
    except ValueError:
        raise HostMigrationError("artifact git root escapes repo") from None
    try:
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *group["git_paths"],
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        archive_result = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "archive",
                "--format=tar",
                captured_head,
                "--",
                *group["git_paths"],
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostMigrationError(f"Git identity capture failed: {exc}") from None
    if (
        status_result.returncode != 0 or archive_result.returncode != 0
    ):
        raise HostMigrationError("declared artifact Git identity is unavailable")
    prefix = "" if group["git_root"] == "." else group["git_root"].rstrip("/") + "/"
    files: list[dict[str, Any]] = []
    try:
        with tarfile.open(
            fileobj=io.BytesIO(archive_result.stdout),
            mode="r:",
        ) as archive:
            for member in sorted(
                archive.getmembers(),
                key=lambda item: item.name,
            ):
                name = member.name.removeprefix("./").rstrip("/")
                relative = prefix + name
                if not name or _ignored(relative, ignored_names) or member.isdir():
                    continue
                if member.issym():
                    target = member.linkname
                    if Path(target).is_absolute() or ".." in Path(target).parts:
                        raise HostMigrationError(
                            "Git artifact symlink target is unsafe"
                        )
                    data = target.encode("utf-8")
                    kind = "symlink"
                    mode = "120000"
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise HostMigrationError(
                            "Git archive file cannot be read"
                        )
                    data = extracted.read()
                    kind = "file"
                    mode = _normalized_file_mode(member.mode)
                else:
                    raise HostMigrationError(
                        "Git archive contains an unsupported node"
                    )
                files.append(
                    {
                        "path": relative,
                        "kind": kind,
                        "mode": mode,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "json_schema": None,
                        "json_valid": None,
                    }
                )
    except tarfile.TarError as exc:
        raise HostMigrationError(f"Git archive is malformed: {exc}") from None
    dirty_paths = sorted(
        {
            line[3:].strip().strip('"')
            for line in status_result.stdout.splitlines()
            if len(line) >= 4
        }
    )
    return files, dirty_paths


def _git_head(git_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostMigrationError(f"Git HEAD capture failed: {exc}") from None
    head = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise HostMigrationError("declared artifact Git HEAD is unavailable")
    return head


def _capture_source_control(
    *,
    root: Path,
    groups: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    ignored_names: frozenset[str],
) -> dict[str, Any]:
    artifact_index = {item["id"]: item for item in artifacts}
    group_states: list[dict[str, Any]] = []
    repositories: list[dict[str, Any]] = []
    by_root: dict[str, list[Mapping[str, Any]]] = {}
    for group in groups:
        if group["parity"] == "sha256":
            by_root.setdefault(group["git_root"], []).append(group)
    for git_root_name, repo_groups in by_root.items():
        git_root = (root / git_root_name).resolve()
        repo_states: list[dict[str, Any]] = []
        all_dirty: set[str] = set()
        try:
            captured_head = _git_head(git_root)
        except HostMigrationError:
            captured_head = None
        for group in repo_groups:
            try:
                if captured_head is None:
                    raise HostMigrationError("repository HEAD capture failed")
                head_files, dirty_paths = _tar_group_files(
                    repo_root=root,
                    group=group,
                    ignored_names=ignored_names,
                    captured_head=captured_head,
                )
                head_tree = sha256_json(head_files)
                captured_tree = artifact_index[group["id"]]["tree_sha256"]
                matches = head_tree == captured_tree
                available = True
            except HostMigrationError:
                head_tree = None
                dirty_paths = []
                matches = False
                available = False
            all_dirty.update(dirty_paths)
            state = {
                "id": group["id"],
                "git_root": git_root_name,
                "available": available,
                "head": captured_head,
                "head_tree_sha256": head_tree,
                "captured_tree_sha256": artifact_index[group["id"]]["tree_sha256"],
                "head_matches_capture": matches,
                "dirty_paths": dirty_paths,
            }
            repo_states.append(state)
            group_states.append(state)
        try:
            final_head = _git_head(git_root)
        except HostMigrationError:
            final_head = None
        stable = captured_head is not None and final_head == captured_head
        if not stable:
            for state in repo_states:
                state["head_matches_capture"] = False
        repositories.append(
            {
                "git_root": git_root_name,
                "captured_head": captured_head,
                "final_head": final_head,
                "heads": [captured_head] if captured_head else [],
                "head_stable": stable,
                "dirty_paths": sorted(all_dirty),
            }
        )
    clean = all(
        item["available"]
        and item["head_matches_capture"]
        and not item["dirty_paths"]
        for item in group_states
    ) and all(
        item["head_stable"] and len(item["heads"]) == 1
        for item in repositories
    )
    return {
        "declared_artifacts_clean_and_immutable": clean,
        "groups": group_states,
        "repositories": repositories,
    }


def _executable_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostMigrationError(f"tool executable cannot be opened: {exc}") from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise HostMigrationError("tool executable is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_mode,
        before.st_uid,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_mode,
        after.st_uid,
    ):
        raise HostMigrationError("tool executable changed while it was captured")
    return {
        "identity": identity,
        "mode": before.st_mode,
        "uid": before.st_uid,
        "sha256": digest.hexdigest(),
    }


def _resolve_command(tool: Mapping[str, Any]) -> Path | None:
    if tool["id"] == "python":
        candidate = Path(sys.executable)
        return candidate.resolve() if candidate.is_file() else None
    for command in tool["commands"]:
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved).resolve()
    return None


def _install_origin(executable: Path, *, repo_root: Path) -> str:
    home = Path.home().resolve()
    roots = (
        ("repo", repo_root.resolve()),
        ("home", home),
        ("homebrew", Path("/opt/homebrew")),
        ("application", Path("/Applications")),
        ("system", Path("/usr")),
        ("system", Path("/bin")),
        ("system", Path("/sbin")),
        ("system", Path("/Library/Apple")),
    )
    for origin, root in roots:
        try:
            executable.relative_to(root)
        except ValueError:  # silent-ok: try the next allowlisted root
            continue
        return origin
    return "other"


def _capture_tool(
    tool: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    executable = _resolve_command(tool)
    if executable is None:
        return {
            "id": tool["id"],
            "required": tool["required"],
            "parity": tool["parity"],
            "present": False,
            "ready": False,
            "executable_name": None,
            "executable_sha256": None,
            "install_origin": None,
            "owner_class": None,
        }
    try:
        captured = _executable_identity(executable)
        owner_class = (
            "root"
            if captured["uid"] == 0
            else "current_user"
            if captured["uid"] == os.getuid()
            else "other"
        )
        install_origin = _install_origin(executable, repo_root=repo_root)
        safe = (
            bool(stat.S_IMODE(captured["mode"]) & 0o111)
            and not bool(stat.S_IMODE(captured["mode"]) & 0o022)
            and owner_class in {"root", "current_user"}
            and install_origin in tool["allowed_install_origins"]
        )
        executable_sha = captured["sha256"] if safe else None
    except (OSError, HostMigrationError):
        safe = False
        executable_sha = None
        install_origin = "other"
        owner_class = "other"
    return {
        "id": tool["id"],
        "required": tool["required"],
        "parity": tool["parity"],
        "present": True,
        "ready": safe,
        "executable_name": executable.name,
        "executable_sha256": executable_sha,
        "install_origin": install_origin,
        "owner_class": owner_class,
    }


def _json_field_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            names.add(str(key))
            names.update(_json_field_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_json_field_names(nested))
    return names


def _reference_names(text: str, *, suffix: str) -> set[str]:
    if suffix.lower() == ".json":
        try:
            return _json_field_names(json.loads(text))
        except json.JSONDecodeError:
            return set()
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].removeprefix("export ").strip()
        if _ENV_NAME.fullmatch(name):
            names.add(name)
    return names


def _secret_location(root: Path, relative: str) -> tuple[dict[str, Any], set[str]]:
    path = root / relative
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return {
            "path": relative,
            "present": False,
            "private_mode": False,
            "regular_non_symlink": False,
        }, set()
    try:
        info = os.fstat(descriptor)
        safe_kind = stat.S_ISREG(info.st_mode)
        private_mode = safe_kind and not bool(stat.S_IMODE(info.st_mode) & 0o077)
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            text = handle.read() if safe_kind else ""
            after = os.fstat(handle.fileno())
    except (OSError, UnicodeError):
        safe_kind = False
        private_mode = False
        text = ""
        after = info
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    names = _reference_names(text, suffix=path.suffix) if safe_kind else set()
    if (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_mtime_ns,
    ):
        raise HostMigrationError("secret reference changed while it was inspected")
    return {
        "path": relative,
        "present": True,
        "private_mode": private_mode,
        "regular_non_symlink": safe_kind,
    }, names


def _capture_secret(
    *,
    root: Path,
    secret: Mapping[str, Any],
    environment: Mapping[str, str],
) -> tuple[dict[str, Any], set[str]]:
    found = {name for name in secret["names"] if environment.get(name)}
    observed_names = set(environment)
    locations: list[dict[str, Any]] = []
    for relative in secret["locations"]:
        state, names = _secret_location(root, relative)
        locations.append(state)
        observed_names.update(names)
        found.update(set(secret["names"]) & names)
    missing = sorted(set(secret["names"]) - found)
    unsafe = sorted(
        item["path"]
        for item in locations
        if item["present"]
        and (not item["regular_non_symlink"] or not item["private_mode"])
    )
    return {
        "id": secret["id"],
        "required": secret["required"],
        "reauthorization_permission_id": secret[
            "reauthorization_permission_id"
        ],
        "configured_names": sorted(found),
        "missing_names": missing,
        "unsafe_locations": unsafe,
        "locations": locations,
        "preflight_ready": not missing and not unsafe,
    }, observed_names


def _load_attestations(
    path: Path,
    *,
    migration_id: str,
    challenge: str,
    signer_identity: str,
    permission_ids: set[str],
    now: datetime,
    max_age_seconds: int,
) -> dict[str, dict[str, Any]]:
    payload = load_json_object(path)
    if set(payload) != {
        "schema_version",
        "migration_id",
        "challenge",
        "signer_identity",
        "observed_at",
        "attestations",
    }:
        raise HostMigrationError("attestation fields are malformed")
    if payload["schema_version"] != ATTESTATIONS_SCHEMA:
        raise HostMigrationError("unsupported attestations schema")
    if payload["migration_id"] != migration_id or payload["challenge"] != challenge:
        raise HostMigrationError("attestations are bound to another migration")
    if payload["signer_identity"] != signer_identity:
        raise HostMigrationError("attestations are bound to another host signer")
    _fresh(
        payload["observed_at"],
        field="attestations.observed_at",
        now=now,
        max_age_seconds=max_age_seconds,
    )
    items = payload["attestations"]
    if not isinstance(items, list):
        raise HostMigrationError("attestations must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "passed",
            "evidence_ref",
        }:
            raise HostMigrationError("attestation item is malformed")
        if item["id"] not in permission_ids or item["id"] in result:
            raise HostMigrationError("attestation id is unknown or duplicated")
        if type(item["passed"]) is not bool:
            raise HostMigrationError("attestation passed must be boolean")
        if (
            not isinstance(item["evidence_ref"], str)
            or not _REFERENCE.fullmatch(item["evidence_ref"])
        ):
            raise HostMigrationError("attestation evidence reference is unsafe")
        result[item["id"]] = item
    return result


def capture_host(
    *,
    spec: Mapping[str, Any],
    repo_root: Path,
    migration_id: str,
    challenge: str,
    signing_key_path: Path,
    signer_identity: str,
    signer_role: str,
    attestations_path: Path,
    environment: Mapping[str, str] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    validate_spec(spec)
    if signer_role not in {"source", "target"}:
        raise HostMigrationError("snapshot signer role must be source or target")
    if not _IDENTIFIER.fullmatch(migration_id):
        raise HostMigrationError("invalid migration id")
    if not isinstance(challenge, str) or not 32 <= len(challenge) <= 256:
        raise HostMigrationError("invalid migration challenge")
    root = repo_root.resolve()
    if not root.is_dir():
        raise HostMigrationError("repo root does not exist")
    now = (captured_at or datetime.now(UTC)).astimezone(UTC)
    permissions_by_id = _load_attestations(
        attestations_path,
        migration_id=migration_id,
        challenge=challenge,
        signer_identity=signer_identity,
        permission_ids={item["id"] for item in spec["permissions"]},
        now=now,
        max_age_seconds=spec["snapshot_max_age_seconds"],
    )
    ignored = frozenset(spec["ignored_path_names"])
    artifacts = [
        _capture_artifact_group(root, group, ignored)
        for group in spec["artifact_groups"]
    ]
    source_control = _capture_source_control(
        root=root,
        groups=spec["artifact_groups"],
        artifacts=artifacts,
        ignored_names=ignored,
    )
    tools = [
        _capture_tool(tool, repo_root=root)
        for tool in spec["tools"]
    ]
    env = environment if environment is not None else os.environ
    secret_states: list[dict[str, Any]] = []
    observed_names = set(env)
    for secret in spec["secret_references"]:
        state, names = _capture_secret(root=root, secret=secret, environment=env)
        secret_states.append(state)
        observed_names.update(names)
    forbidden_present = sorted(
        set(spec["forbidden_agentic_auth_names"]) & observed_names
    )
    permissions = [
        {
            "id": item["id"],
            "required": item["required"],
            "probe": item["probe"],
            "passed": permissions_by_id.get(
                item["id"],
                {"passed": False},
            )["passed"],
            "evidence_ref": permissions_by_id.get(
                item["id"],
                {"evidence_ref": None},
            )["evidence_ref"],
        }
        for item in spec["permissions"]
    ]
    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA,
        "migration_id": migration_id,
        "challenge": challenge,
        "captured_at": now.isoformat(),
        "spec_sha256": sha256_json(spec),
        "host": {
            "hostname": socket.gethostname(),
            "machine": platform.machine(),
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "repo_name": root.name,
        },
        "source_control": source_control,
        "artifacts": artifacts,
        "tools": tools,
        "secret_references": secret_states,
        "forbidden_agentic_auth_present": forbidden_present,
        "permissions": permissions,
    }
    payload["snapshot_sha256"] = sha256_json(payload)
    try:
        payload["attestation"] = sign_mapping(
            payload,
            private_key_path=signing_key_path,
            signer_identity=signer_identity,
            signer_role=signer_role,
        )
    except HostAttestationError as exc:
        _raise_attestation(exc)
    return payload


def _verify_digest(payload: Mapping[str, Any], digest_field: str) -> None:
    provided = payload.get(digest_field)
    unsigned = dict(payload)
    unsigned.pop("attestation", None)
    unsigned.pop(digest_field, None)
    if not isinstance(provided, str) or provided != sha256_json(unsigned):
        raise HostMigrationError(f"{digest_field} identity mismatch")


def _verify_snapshot(
    snapshot: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
    trust_policy: TrustPolicy,
    expected_role: str,
    now: datetime,
) -> Any:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise HostMigrationError("snapshot schema mismatch")
    if snapshot.get("migration_id") != trust_policy.migration_id:
        raise HostMigrationError("snapshot migration id mismatch")
    if snapshot.get("challenge") != trust_policy.challenge:
        raise HostMigrationError("snapshot challenge mismatch")
    if snapshot.get("spec_sha256") != sha256_json(spec):
        raise HostMigrationError("snapshot spec identity mismatch")
    _fresh(
        snapshot.get("captured_at"),
        field=f"{expected_role}.captured_at",
        now=now,
        max_age_seconds=spec["snapshot_max_age_seconds"],
    )
    _verify_digest(snapshot, "snapshot_sha256")
    try:
        return verify_mapping(
            snapshot,
            trust_policy=trust_policy,
            expected_role=expected_role,
        )
    except HostAttestationError as exc:
        _raise_attestation(exc)


def _exact_nonnegative_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise HostMigrationError(f"{field} must be a non-negative integer")
    return value


def _finite_nonnegative_number(value: Any, *, field: str) -> float:
    if type(value) not in {int, float}:
        raise HostMigrationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise HostMigrationError(f"{field} must be finite and non-negative")
    return result


def assess_continuity_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    trust_policy: TrustPolicy,
    source_snapshot_sha256: str,
    target_snapshot_sha256: str,
    now: datetime,
) -> dict[str, Any]:
    if receipt is None:
        return {
            "outcome": "missing",
            "promotion_eligible": False,
            "reason_codes": ["continuity_receipt_missing"],
            "rto_seconds": None,
            "rpo_receipts": None,
            "formal_effect_count": 0,
        }
    required_fields = {
        "schema_version",
        "migration_id",
        "source_snapshot_sha256",
        "target_snapshot_sha256",
        "rehearsal_id",
        "authority_key",
        "primary_epoch",
        "standby_epoch",
        "verified_at",
        "recovery_rto_seconds",
        "formal_effect_receipts_lost",
        "duplicate_authority_claims",
        "formal_effects",
        "receipt_sha256",
        "attestation",
    }
    if set(receipt) != required_fields or receipt["schema_version"] != CONTINUITY_SCHEMA:
        return {
            "outcome": "contained",
            "promotion_eligible": False,
            "reason_codes": ["formal_continuity_schema_missing"],
            "rto_seconds": None,
            "rpo_receipts": None,
            "formal_effect_count": 0,
        }
    try:
        _verify_digest(receipt, "receipt_sha256")
        verify_mapping(
            receipt,
            trust_policy=trust_policy,
            expected_role="continuity_verifier",
        )
        if receipt["migration_id"] != trust_policy.migration_id:
            raise HostMigrationError("continuity migration id mismatch")
        if (
            not isinstance(receipt["rehearsal_id"], str)
            or not _IDENTIFIER.fullmatch(receipt["rehearsal_id"])
        ):
            raise HostMigrationError("continuity rehearsal id is malformed")
        if receipt["authority_key"] != "operations-core-primary":
            raise HostMigrationError("continuity authority key is not canonical")
        if receipt["source_snapshot_sha256"] != source_snapshot_sha256:
            raise HostMigrationError("continuity source snapshot mismatch")
        if receipt["target_snapshot_sha256"] != target_snapshot_sha256:
            raise HostMigrationError("continuity target snapshot mismatch")
        _fresh(
            receipt["verified_at"],
            field="continuity.verified_at",
            now=now,
            max_age_seconds=spec["continuity"]["receipt_max_age_seconds"],
        )
        primary_epoch = _exact_nonnegative_int(
            receipt["primary_epoch"],
            field="continuity.primary_epoch",
        )
        standby_epoch = _exact_nonnegative_int(
            receipt["standby_epoch"],
            field="continuity.standby_epoch",
        )
        if primary_epoch < 1 or standby_epoch != primary_epoch + 1:
            raise HostMigrationError("continuity epochs are not exact-next")
        rto = _finite_nonnegative_number(
            receipt["recovery_rto_seconds"],
            field="continuity.recovery_rto_seconds",
        )
        rpo = _exact_nonnegative_int(
            receipt["formal_effect_receipts_lost"],
            field="continuity.formal_effect_receipts_lost",
        )
        duplicate_claims = _exact_nonnegative_int(
            receipt["duplicate_authority_claims"],
            field="continuity.duplicate_authority_claims",
        )
        effects = receipt["formal_effects"]
        if not isinstance(effects, list):
            raise HostMigrationError("continuity formal effects must be a list")
        effect_ids: set[str] = set()
        for effect in effects:
            if not isinstance(effect, dict) or set(effect) != {
                "effect_id",
                "effect_kind",
                "request_sha256",
                "terminal_receipt_sha256",
                "status",
                "duplicate_count",
            }:
                raise HostMigrationError("formal effect receipt is malformed")
            if not isinstance(effect["effect_id"], str) or not _IDENTIFIER.fullmatch(
                effect["effect_id"]
            ):
                raise HostMigrationError("formal effect id is malformed")
            if effect["effect_id"] in effect_ids:
                raise HostMigrationError("formal effect id is duplicated")
            effect_ids.add(effect["effect_id"])
            if effect["status"] != "acknowledged":
                raise HostMigrationError("formal effect is not acknowledged")
            if (
                not isinstance(effect["effect_kind"], str)
                or not _IDENTIFIER.fullmatch(effect["effect_kind"])
            ):
                raise HostMigrationError("formal effect kind is malformed")
            if not isinstance(
                effect["request_sha256"], str
            ) or not _SHA256.fullmatch(effect["request_sha256"]):
                raise HostMigrationError("formal effect request identity is malformed")
            if not isinstance(
                effect["terminal_receipt_sha256"], str
            ) or not _SHA256.fullmatch(effect["terminal_receipt_sha256"]):
                raise HostMigrationError("formal effect terminal identity is malformed")
            if _exact_nonnegative_int(
                effect["duplicate_count"],
                field="formal_effect.duplicate_count",
            ):
                raise HostMigrationError("formal effect has duplicate delivery")
    except (HostMigrationError, HostAttestationError) as exc:
        return {
            "outcome": "contained",
            "promotion_eligible": False,
            "reason_codes": [f"formal_continuity_invalid:{exc}"],
            "rto_seconds": None,
            "rpo_receipts": None,
            "formal_effect_count": 0,
        }
    reasons: list[str] = []
    if rto > spec["continuity"]["rto_seconds_max"]:
        reasons.append("rto_exceeded")
    if rpo != spec["continuity"]["rpo_receipts_max"]:
        reasons.append("rpo_receipts_lost")
    if duplicate_claims:
        reasons.append("duplicate_authority_claim")
    if len(effects) < spec["continuity"]["formal_effect_count_min"]:
        reasons.append("formal_effect_evidence_insufficient")
    return {
        "outcome": "pass" if not reasons else "contained",
        "promotion_eligible": not reasons,
        "reason_codes": reasons,
        "rto_seconds": rto,
        "rpo_receipts": rpo,
        "formal_effect_count": len(effects),
    }


def _index(items: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id"))
        if item_id in result:
            raise HostMigrationError("snapshot contains duplicate ids")
        result[item_id] = item
    return result


def _tool_matches(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    if not source.get("ready") or not target.get("ready"):
        return False
    source_sha = source.get("executable_sha256")
    target_sha = target.get("executable_sha256")
    if (
        not isinstance(source_sha, str)
        or not _SHA256.fullmatch(source_sha)
        or target_sha != source_sha
    ):
        return False
    return source.get("parity") == target.get("parity") == "exact_sha256"


def compare_hosts(
    *,
    spec: Mapping[str, Any],
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    trust_policy: TrustPolicy,
    continuity_receipt: Mapping[str, Any] | None,
    report_signing_key_path: Path,
    report_signer_identity: str,
    compared_at: datetime | None = None,
) -> dict[str, Any]:
    validate_spec(spec)
    now = (compared_at or datetime.now(UTC)).astimezone(UTC)
    try:
        ensure_trust_policy_current(trust_policy, now=now)
    except HostAttestationError as exc:
        _raise_attestation(exc)
    source_signer = _verify_snapshot(
        source,
        spec=spec,
        trust_policy=trust_policy,
        expected_role="source",
        now=now,
    )
    target_signer = _verify_snapshot(
        target,
        spec=spec,
        trust_policy=trust_policy,
        expected_role="target",
        now=now,
    )
    if (
        source_signer.identity == target_signer.identity
        or source_signer.public_key_fingerprint
        == target_signer.public_key_fingerprint
    ):
        raise HostMigrationError("source and target must be distinct trusted hosts")
    if source.get("host", {}).get("hostname") == target.get("host", {}).get("hostname"):
        raise HostMigrationError("source and target hostnames must differ")

    gaps: list[dict[str, str]] = []
    source_control = source.get("source_control", {})
    if not source_control.get("declared_artifacts_clean_and_immutable"):
        gaps.append(
            {
                "category": "source_identity",
                "id": "declared_artifacts",
                "reason": "source_not_clean_immutable_git",
            }
        )
    target_control = target.get("source_control", {})
    if not target_control.get("declared_artifacts_clean_and_immutable"):
        gaps.append(
            {
                "category": "target_identity",
                "id": "declared_artifacts",
                "reason": "target_not_clean_immutable_git",
            }
        )
    source_artifacts = _index(source["artifacts"])
    target_artifacts = _index(target["artifacts"])
    for group in spec["artifact_groups"]:
        before = source_artifacts.get(group["id"])
        after = target_artifacts.get(group["id"])
        if before is None or after is None:
            raise HostMigrationError("snapshot artifact set differs from spec")
        passed = bool(before["valid"]) and bool(after["valid"])
        if group["parity"] == "sha256":
            passed = passed and before["tree_sha256"] == after["tree_sha256"]
        if group["required"] and not passed:
            gaps.append(
                {
                    "category": "artifact",
                    "id": group["id"],
                    "reason": (
                        "missing_or_invalid"
                        if not before["valid"] or not after["valid"]
                        else "tree_sha256_mismatch"
                    ),
                }
            )

    source_tools = _index(source["tools"])
    target_tools = _index(target["tools"])
    for tool in spec["tools"]:
        if tool["required"] and not _tool_matches(
            source_tools[tool["id"]],
            target_tools[tool["id"]],
        ):
            gaps.append(
                {
                    "category": "tool",
                    "id": tool["id"],
                    "reason": "missing_untrusted_or_exact_sha_mismatch",
                }
            )

    permissions = _index(target["permissions"])
    for permission in spec["permissions"]:
        state = permissions.get(permission["id"])
        if state is None:
            raise HostMigrationError("target permissions differ from spec")
        if permission["required"] and state.get("passed") is not True:
            gaps.append(
                {
                    "category": "permission",
                    "id": permission["id"],
                    "reason": "signed_attestation_missing_or_failed",
                }
            )
    for secret in target["secret_references"]:
        if secret["required"] and not secret["preflight_ready"]:
            gaps.append(
                {
                    "category": "secret_reference",
                    "id": secret["id"],
                    "reason": "reference_presence_or_mode_invalid",
                }
            )
        permission = permissions[secret["reauthorization_permission_id"]]
        if secret["required"] and permission["passed"] is not True:
            gaps.append(
                {
                    "category": "secret_reference",
                    "id": secret["id"],
                    "reason": "target_reauthorization_unattested",
                }
            )
    if source["forbidden_agentic_auth_present"]:
        gaps.append(
            {
                "category": "auth_policy",
                "id": "zero_paid_agentic_auth",
                "reason": "source_forbidden_api_key_present",
            }
        )
    if target["forbidden_agentic_auth_present"]:
        gaps.append(
            {
                "category": "auth_policy",
                "id": "zero_paid_agentic_auth",
                "reason": "forbidden_api_key_present",
            }
        )

    continuity = assess_continuity_receipt(
        continuity_receipt,
        spec=spec,
        trust_policy=trust_policy,
        source_snapshot_sha256=source["snapshot_sha256"],
        target_snapshot_sha256=target["snapshot_sha256"],
        now=now,
    )
    if not continuity["promotion_eligible"]:
        for reason in continuity["reason_codes"]:
            gaps.append(
                {
                    "category": "continuity",
                    "id": "rpo_rto",
                    "reason": reason,
                }
            )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "migration_id": trust_policy.migration_id,
        "challenge": trust_policy.challenge,
        "compared_at": now.isoformat(),
        "spec_sha256": sha256_json(spec),
        "trust_policy_sha256": trust_policy.sha256,
        "source_snapshot_sha256": source["snapshot_sha256"],
        "target_snapshot_sha256": target["snapshot_sha256"],
        "source_signer": {
            "identity": source_signer.identity,
            "public_key_fingerprint": source_signer.public_key_fingerprint,
        },
        "target_signer": {
            "identity": target_signer.identity,
            "public_key_fingerprint": target_signer.public_key_fingerprint,
        },
        "source_host": source["host"],
        "target_host": target["host"],
        "gaps": gaps,
        "continuity": continuity,
        "parity_passed": not gaps,
        "promotion_eligible": not gaps and continuity["promotion_eligible"],
    }
    report["report_sha256"] = sha256_json(report)
    try:
        report["attestation"] = sign_mapping(
            report,
            private_key_path=report_signing_key_path,
            signer_identity=report_signer_identity,
            signer_role="verifier",
        )
        verify_mapping(
            report,
            trust_policy=trust_policy,
            expected_role="verifier",
        )
    except HostAttestationError as exc:
        _raise_attestation(exc)
    return report


def _validate_report(
    *,
    spec: Mapping[str, Any],
    report: Mapping[str, Any],
    trust_policy: TrustPolicy,
    now: datetime,
) -> None:
    if set(report) != {
        "schema_version",
        "migration_id",
        "challenge",
        "compared_at",
        "spec_sha256",
        "trust_policy_sha256",
        "source_snapshot_sha256",
        "target_snapshot_sha256",
        "source_signer",
        "target_signer",
        "source_host",
        "target_host",
        "gaps",
        "continuity",
        "parity_passed",
        "promotion_eligible",
        "report_sha256",
        "attestation",
    }:
        raise HostMigrationError("parity report fields are malformed")
    if report.get("schema_version") != REPORT_SCHEMA:
        raise HostMigrationError("parity report schema mismatch")
    if report.get("migration_id") != trust_policy.migration_id:
        raise HostMigrationError("parity report migration mismatch")
    if report.get("challenge") != trust_policy.challenge:
        raise HostMigrationError("parity report challenge mismatch")
    if report.get("spec_sha256") != sha256_json(spec):
        raise HostMigrationError("parity report spec identity mismatch")
    if report.get("trust_policy_sha256") != trust_policy.sha256:
        raise HostMigrationError("parity report trust identity mismatch")
    _fresh(
        report.get("compared_at"),
        field="report.compared_at",
        now=now,
        max_age_seconds=spec["snapshot_max_age_seconds"],
    )
    _verify_digest(report, "report_sha256")
    try:
        verify_mapping(
            report,
            trust_policy=trust_policy,
            expected_role="verifier",
        )
    except HostAttestationError as exc:
        _raise_attestation(exc)
    gaps = report.get("gaps")
    continuity = report.get("continuity")
    if not isinstance(gaps, list) or not isinstance(continuity, dict):
        raise HostMigrationError("parity report derived fields are malformed")
    derived_parity = not gaps
    derived_eligible = derived_parity and continuity.get("promotion_eligible") is True
    if report.get("parity_passed") is not derived_parity:
        raise HostMigrationError("parity report parity flag is inconsistent")
    if report.get("promotion_eligible") is not derived_eligible:
        raise HostMigrationError("parity report promotion flag is inconsistent")


def build_guided_plan(
    *,
    spec: Mapping[str, Any],
    report: Mapping[str, Any],
    trust_policy: TrustPolicy,
    plan_signing_key_path: Path,
    plan_signer_identity: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    validate_spec(spec)
    now = (created_at or datetime.now(UTC)).astimezone(UTC)
    try:
        ensure_trust_policy_current(trust_policy, now=now)
    except HostAttestationError as exc:
        _raise_attestation(exc)
    _validate_report(
        spec=spec,
        report=report,
        trust_policy=trust_policy,
        now=now,
    )
    grouped: dict[tuple[str, str], list[str]] = {}
    for gap in report["gaps"]:
        key = (gap["category"], gap["id"])
        grouped.setdefault(key, [])
        if gap["reason"] not in grouped[key]:
            grouped[key].append(gap["reason"])
    actions: list[dict[str, Any]] = []
    instructions = {
        "source_identity": (
            "settle all declared source paths at reviewed immutable Git HEADs; "
            "never deploy another session's WIP"
        ),
        "target_identity": (
            "settle all declared target paths at one reviewed immutable Git HEAD; "
            "never promote a dirty or mixed-HEAD target"
        ),
        "artifact": (
            "deploy the declared artifact group from its signed immutable source "
            "identity, then recapture"
        ),
        "tool": (
            "install the canonical exact executable identity and attach its signed "
            "functional permission receipt, then recapture"
        ),
        "permission": (
            "complete the target permission and attach a signed non-secret reference"
        ),
        "secret_reference": (
            "reauthorize on target; never copy source secrets or desktop sessions"
        ),
        "auth_policy": (
            "remove forbidden pay-as-you-go credentials and recapture"
        ),
        "continuity": (
            "run a signed formal-effect failover rehearsal bound to both snapshots"
        ),
    }
    for step, ((category, item_id), reasons) in enumerate(grouped.items(), start=1):
        actions.append(
            {
                "step": step,
                "category": category,
                "id": item_id,
                "reason_codes": reasons,
                "instruction": instructions[category],
                "mutates_target": True,
                "requires_operator_confirmation": True,
            }
        )
    actions.append(
        {
            "step": len(actions) + 1,
            "category": "verification",
            "id": "fresh_signed_recapture",
            "reason_codes": ["mandatory_after_any_change"],
            "instruction": (
                "recapture both hosts with a fresh challenge and rerun signed compare"
            ),
            "mutates_target": False,
            "requires_operator_confirmation": False,
        }
    )
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "migration_id": trust_policy.migration_id,
        "challenge": trust_policy.challenge,
        "created_at": now.isoformat(),
        "spec_sha256": sha256_json(spec),
        "trust_policy_sha256": trust_policy.sha256,
        "report_sha256": report["report_sha256"],
        "challenge_consumption_id": challenge_consumption_id(trust_policy),
        "mode": "dry_run",
        "performed_mutations": [],
        "actions": actions,
        "rollback": {
            "rto_seconds_max": spec["continuity"]["rto_seconds_max"],
            "rpo_receipts_max": spec["continuity"]["rpo_receipts_max"],
            "steps": list(spec["continuity"]["rollback_steps"]),
        },
        "promotion_eligible": report["promotion_eligible"],
        "authorizes_primary_lease": False,
    }
    plan["plan_sha256"] = sha256_json(plan)
    try:
        plan["attestation"] = sign_mapping(
            plan,
            private_key_path=plan_signing_key_path,
            signer_identity=plan_signer_identity,
            signer_role="verifier",
        )
        verify_mapping(
            plan,
            trust_policy=trust_policy,
            expected_role="verifier",
        )
        persist_challenge_evidence(
            trust_policy,
            state_dir=HOST_MIGRATION_STATE_DIR,
            purpose="guided_plan",
            evidence_sha256=plan["plan_sha256"],
            evidence=plan,
            consumed_at=now,
        )
    except HostAttestationError as exc:
        _raise_attestation(exc)
    return plan


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        try:
            info = path.lstat()
        except OSError as exc:
            raise HostMigrationError(f"output target cannot be inspected: {exc}") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise HostMigrationError("output target must be a regular non-symlink file")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:  # silent-ok: os.replace consumed the temp file
            pass
