"""Signed, secret-free cold restore for a blank compatible VolPred host.

The bundle is built only from immutable Git objects already bound to a trusted
source snapshot.  Restore never calls a package manager, installs a schedule,
copies a secret, performs an external effect, or acquires Primary Authority.
It materializes a verified payload into a private staging directory and makes
the whole target visible with one rename.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from volpred.ops.host_attestation import (
    HostAttestationError,
    TrustPolicy,
    canonical_json_bytes,
    ensure_trust_policy_current,
    sha256_json,
    sign_mapping,
    verify_mapping,
)
from volpred.ops.host_migration import (
    HostMigrationError,
    verify_host_snapshot,
)

BUNDLE_SCHEMA = "volpred.cold-restore-bundle.v1"
RECEIPT_SCHEMA = "volpred.cold-restore-receipt.v1"
MANIFEST_NAME = "manifest.json"
PAYLOAD_PREFIX = "payload/"
RECEIPT_PATH = ".volpred/cold-restore-receipt.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MODES = frozenset({"100644", "100755", "120000"})
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024 * 1024
_MAX_FILE_BYTES = 1024 * 1024 * 1024
_MAX_FILE_COUNT = 200_000
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_SECRET_BASENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
        ".env.staging",
        "id_rsa",
        "id_ed25519",
    }
)


def _utc(value: datetime | None) -> datetime:
    if value is not None and value.tzinfo is None:
        raise HostMigrationError("cold restore timestamp must be timezone-aware")
    result = (value or datetime.now(UTC)).astimezone(UTC)
    return result


def _safe_relative(value: str, *, field: str = "bundle path") -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HostMigrationError(f"{field} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HostMigrationError(f"{field} must be a relative POSIX path")
    return path.as_posix()


def _secret_like(path: str, secret_paths: frozenset[str] = frozenset()) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    if path in secret_paths or name in _SECRET_BASENAMES or pure.parts[0] == ".volpred":
        return True
    if name.startswith(".env.") and not name.endswith(
        (".example", ".sample", ".template")
    ):
        return True
    return name.endswith((".pem", ".key")) or path == "storage/ops/telegram_state.json"


def _record(path: str, *, kind: str, mode: str, data: bytes) -> dict[str, Any]:
    return {
        "path": _safe_relative(path),
        "kind": kind,
        "mode": mode,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _normalized_mode(mode: int) -> str:
    return "100755" if stat.S_IMODE(mode) & 0o111 else "100644"


def _git_archive(
    *,
    repo_root: Path,
    git_root: str,
    git_paths: Sequence[str],
    head: str,
    ignored_names: frozenset[str],
) -> dict[str, tuple[dict[str, Any], bytes]]:
    root = repo_root.resolve()
    repository = (root / git_root).resolve()
    try:
        repository.relative_to(root)
    except ValueError:
        raise HostMigrationError("cold restore Git root escapes repo") from None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "archive",
                "--format=tar",
                head,
                "--",
                *git_paths,
            ],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostMigrationError(f"cold restore Git archive failed: {exc}") from None
    if result.returncode != 0:
        raise HostMigrationError("cold restore source commit is unavailable")

    prefix = "" if git_root == "." else git_root.rstrip("/") + "/"
    entries: dict[str, tuple[dict[str, Any], bytes]] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                name = member.name.removeprefix("./").rstrip("/")
                path = prefix + name
                if (
                    not name
                    or member.isdir()
                    or any(part in ignored_names for part in PurePosixPath(path).parts)
                ):
                    continue
                safe_path = _safe_relative(path)
                if member.issym():
                    target = _safe_symlink_target(member.linkname)
                    data = target.encode("utf-8")
                    record = _record(
                        safe_path,
                        kind="symlink",
                        mode="120000",
                        data=data,
                    )
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise HostMigrationError(
                            "cold restore Git member cannot be read"
                        )
                    data = extracted.read()
                    record = _record(
                        safe_path,
                        kind="file",
                        mode=_normalized_mode(member.mode),
                        data=data,
                    )
                else:
                    raise HostMigrationError(
                        "cold restore Git archive has unsupported node"
                    )
                existing = entries.get(safe_path)
                if existing is not None and existing != (record, data):
                    raise HostMigrationError("cold restore path identity collides")
                entries[safe_path] = (record, data)
    except tarfile.TarError as exc:
        raise HostMigrationError(
            f"cold restore Git archive is malformed: {exc}"
        ) from None
    return entries


def _safe_symlink_target(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HostMigrationError("cold restore symlink target is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HostMigrationError("cold restore symlink target is unsafe")
    return path.as_posix()


def _source_entries(
    *,
    spec: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, tuple[dict[str, Any], bytes]]:
    control = source_snapshot.get("source_control")
    if (
        not isinstance(control, dict)
        or control.get("declared_artifacts_clean_and_immutable") is not True
    ):
        raise HostMigrationError("cold restore source is not clean immutable Git")
    raw_repositories = control.get("repositories")
    raw_group_states = control.get("groups")
    raw_snapshots = source_snapshot.get("artifacts")
    if (
        not isinstance(raw_repositories, list)
        or not isinstance(raw_group_states, list)
        or not isinstance(raw_snapshots, list)
    ):
        raise HostMigrationError("cold restore source control fields are malformed")
    repositories = {
        item.get("git_root"): item
        for item in raw_repositories
        if isinstance(item, dict)
    }
    group_states = {
        item.get("id"): item for item in raw_group_states if isinstance(item, dict)
    }
    snapshots = {
        item.get("id"): item for item in raw_snapshots if isinstance(item, dict)
    }
    ignored = frozenset(spec["ignored_path_names"])
    secret_paths = frozenset(
        path for secret in spec["secret_references"] for path in secret["locations"]
    )
    combined: dict[str, tuple[dict[str, Any], bytes]] = {}
    for group in spec["artifact_groups"]:
        if group["parity"] != "sha256":
            continue
        state = group_states.get(group["id"])
        repository = repositories.get(group["git_root"])
        snapshot = snapshots.get(group["id"])
        if (
            not isinstance(state, dict)
            or state.get("available") is not True
            or state.get("head_matches_capture") is not True
            or state.get("dirty_paths") != []
            or not isinstance(repository, dict)
            or repository.get("head_stable") is not True
            or not isinstance(repository.get("captured_head"), str)
            or not isinstance(snapshot, dict)
            or snapshot.get("valid") is not True
        ):
            raise HostMigrationError(
                f"cold restore source group {group['id']} is not immutable"
            )
        entries = _git_archive(
            repo_root=repo_root,
            git_root=group["git_root"],
            git_paths=group["git_paths"],
            head=repository["captured_head"],
            ignored_names=ignored,
        )
        actual = sorted(
            (record for record, _data in entries.values()),
            key=lambda item: item["path"],
        )
        try:
            expected = sorted(
                (
                    {
                        key: item[key]
                        for key in ("path", "kind", "mode", "bytes", "sha256")
                    }
                    for item in snapshot["files"]
                ),
                key=lambda item: item["path"],
            )
        except (KeyError, TypeError):
            raise HostMigrationError(
                f"cold restore source group {group['id']} records are malformed"
            ) from None
        if actual != expected:
            raise HostMigrationError(
                f"cold restore source group {group['id']} identity mismatch"
            )
        for path, entry in entries.items():
            if _secret_like(path, secret_paths):
                raise HostMigrationError(
                    f"cold restore bundle would include secret path {path}"
                )
            existing = combined.get(path)
            if existing is not None and existing != entry:
                raise HostMigrationError("cold restore path identity collides")
            combined[path] = entry
    if not combined:
        raise HostMigrationError("cold restore payload is empty")
    if RECEIPT_PATH in combined:
        raise HostMigrationError("cold restore payload collides with receipt path")
    return combined


def _tar_info(name: str, *, mode: int, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _atomic_bundle_write(
    output_path: Path,
    *,
    manifest: Mapping[str, Any],
    entries: Mapping[str, tuple[Mapping[str, Any], bytes]],
) -> None:
    if output_path.exists() or output_path.is_symlink():
        raise HostMigrationError("cold restore bundle output already exists")
    parent = output_path.parent.resolve()
    if not parent.is_dir():
        raise HostMigrationError("cold restore bundle parent does not exist")
    descriptor, temporary = tempfile.mkstemp(
        dir=parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            with tarfile.open(
                fileobj=handle,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                manifest_bytes = canonical_json_bytes(manifest) + b"\n"
                archive.addfile(
                    _tar_info(
                        MANIFEST_NAME,
                        mode=0o644,
                        size=len(manifest_bytes),
                    ),
                    io.BytesIO(manifest_bytes),
                )
                for path in sorted(entries):
                    record, data = entries[path]
                    info = _tar_info(
                        PAYLOAD_PREFIX + path,
                        mode=0o755 if record["mode"] == "100755" else 0o644,
                        size=len(data) if record["kind"] == "file" else 0,
                    )
                    if record["kind"] == "symlink":
                        info.type = tarfile.SYMTYPE
                        info.mode = 0o777
                        info.linkname = data.decode("utf-8")
                        archive.addfile(info)
                    else:
                        archive.addfile(info, io.BytesIO(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, output_path, follow_symlinks=False)
        except FileExistsError:
            raise HostMigrationError(
                "cold restore bundle output appeared during build"
            ) from None
        os.unlink(temporary)
        _fsync_directory(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass  # silent-ok: successful no-clobber link already consumed temp


def build_cold_restore_bundle(
    *,
    spec: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    trust_policy: TrustPolicy,
    repo_root: Path,
    output_path: Path,
    signing_key_path: Path,
    signer_identity: str,
    built_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one deterministic signed tar from immutable source Git objects."""
    now = _utc(built_at)
    source_signer = verify_host_snapshot(
        spec=spec,
        snapshot=source_snapshot,
        trust_policy=trust_policy,
        expected_role="source",
        verified_at=now,
    )
    entries = _source_entries(
        spec=spec,
        source_snapshot=source_snapshot,
        repo_root=repo_root,
    )
    files = [entries[path][0] for path in sorted(entries)]
    byte_count = sum(item["bytes"] for item in files)
    if len(files) > _MAX_FILE_COUNT or byte_count > _MAX_PAYLOAD_BYTES:
        raise HostMigrationError("cold restore source payload exceeds safety bounds")
    manifest: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA,
        "migration_id": trust_policy.migration_id,
        "challenge": trust_policy.challenge,
        "built_at": now.isoformat(),
        "spec_sha256": sha256_json(spec),
        "trust_policy_sha256": trust_policy.sha256,
        "source_snapshot_sha256": source_snapshot["snapshot_sha256"],
        "source_signer": {
            "identity": source_signer.identity,
            "public_key_fingerprint": source_signer.public_key_fingerprint,
        },
        "file_count": len(files),
        "byte_count": byte_count,
        "payload_sha256": sha256_json(files),
        "files": files,
        "includes_secrets": False,
        "installs_schedules": False,
        "authorizes_primary_lease": False,
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    try:
        manifest["attestation"] = sign_mapping(
            manifest,
            private_key_path=signing_key_path,
            signer_identity=signer_identity,
            signer_role="verifier",
        )
        verify_mapping(
            manifest,
            trust_policy=trust_policy,
            expected_role="verifier",
        )
    except HostAttestationError as exc:
        raise HostMigrationError(str(exc)) from None
    _atomic_bundle_write(output_path, manifest=manifest, entries=entries)
    return manifest


def _verify_manifest(
    manifest: Any,
    *,
    trust_policy: TrustPolicy,
    now: datetime,
) -> list[dict[str, Any]]:
    required = {
        "schema_version",
        "migration_id",
        "challenge",
        "built_at",
        "spec_sha256",
        "trust_policy_sha256",
        "source_snapshot_sha256",
        "source_signer",
        "file_count",
        "byte_count",
        "payload_sha256",
        "files",
        "includes_secrets",
        "installs_schedules",
        "authorizes_primary_lease",
        "manifest_sha256",
        "attestation",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise HostMigrationError("cold restore manifest fields are malformed")
    if (
        manifest["schema_version"] != BUNDLE_SCHEMA
        or manifest["migration_id"] != trust_policy.migration_id
        or manifest["challenge"] != trust_policy.challenge
        or manifest["trust_policy_sha256"] != trust_policy.sha256
    ):
        raise HostMigrationError("cold restore manifest identity mismatch")
    source_signers = [item for item in trust_policy.signers if item.role == "source"]
    expected_source = {
        "identity": source_signers[0].identity,
        "public_key_fingerprint": source_signers[0].public_key_fingerprint,
    }
    if manifest["source_signer"] != expected_source:
        raise HostMigrationError("cold restore source signer identity mismatch")
    for field in ("spec_sha256", "source_snapshot_sha256", "payload_sha256"):
        if not isinstance(manifest[field], str) or not _SHA256.fullmatch(
            manifest[field]
        ):
            raise HostMigrationError(f"cold restore {field} is invalid")
    try:
        parsed_built_at = datetime.fromisoformat(str(manifest["built_at"]))
    except (TypeError, ValueError):
        raise HostMigrationError("cold restore built_at is invalid") from None
    if parsed_built_at.tzinfo is None:
        raise HostMigrationError("cold restore built_at must include an offset")
    built_at = parsed_built_at.astimezone(UTC)
    if (
        built_at < trust_policy.valid_from
        or built_at > now
        or built_at > trust_policy.valid_until
    ):
        raise HostMigrationError("cold restore built_at is outside trust window")
    try:
        ensure_trust_policy_current(trust_policy, now=now)
        verify_mapping(
            manifest,
            trust_policy=trust_policy,
            expected_role="verifier",
        )
    except HostAttestationError as exc:
        raise HostMigrationError(str(exc)) from None
    unsigned = dict(manifest)
    unsigned.pop("attestation")
    digest = unsigned.pop("manifest_sha256")
    if not isinstance(digest, str) or digest != sha256_json(unsigned):
        raise HostMigrationError("cold restore manifest digest mismatch")
    if (
        manifest["includes_secrets"] is not False
        or manifest["installs_schedules"] is not False
        or manifest["authorizes_primary_lease"] is not False
    ):
        raise HostMigrationError("cold restore activation flags must be false")
    files = manifest["files"]
    if not isinstance(files, list) or not files or len(files) > _MAX_FILE_COUNT:
        raise HostMigrationError("cold restore manifest files are malformed")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "kind",
            "mode",
            "bytes",
            "sha256",
        }:
            raise HostMigrationError("cold restore file record is malformed")
        path = _safe_relative(item["path"])
        if path in seen or _secret_like(path):
            raise HostMigrationError("cold restore file path is duplicated or secret")
        seen.add(path)
        if item["kind"] not in {"file", "symlink"} or item["mode"] not in _MODES:
            raise HostMigrationError("cold restore file kind or mode is invalid")
        if item["kind"] == "symlink" and item["mode"] != "120000":
            raise HostMigrationError("cold restore symlink mode is invalid")
        if item["kind"] == "file" and item["mode"] == "120000":
            raise HostMigrationError("cold restore regular file mode is invalid")
        if (
            type(item["bytes"]) is not int
            or item["bytes"] < 0
            or item["bytes"] > _MAX_FILE_BYTES
        ):
            raise HostMigrationError("cold restore file size is invalid")
        if not isinstance(item["sha256"], str) or not _SHA256.fullmatch(item["sha256"]):
            raise HostMigrationError("cold restore file digest is invalid")
        normalized.append(dict(item))
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        raise HostMigrationError("cold restore file records are not canonical")
    for path in seen:
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("."):
            if parent.as_posix() in seen:
                raise HostMigrationError(
                    "cold restore file paths have an unsafe hierarchy"
                )
            parent = parent.parent
    if (
        type(manifest["file_count"]) is not int
        or type(manifest["byte_count"]) is not int
        or manifest["file_count"] != len(normalized)
        or manifest["byte_count"] > _MAX_PAYLOAD_BYTES
        or manifest["byte_count"] != sum(item["bytes"] for item in normalized)
        or manifest["payload_sha256"] != sha256_json(normalized)
    ):
        raise HostMigrationError("cold restore payload manifest identity mismatch")
    return normalized


def _read_bundle(
    path: Path,
    *,
    trust_policy: TrustPolicy,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, tuple[dict[str, Any], bytes]], str]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostMigrationError(f"cold restore bundle unavailable: {exc}") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise HostMigrationError("cold restore bundle must be a regular file")
        if info.st_size <= 0 or info.st_size > _MAX_BUNDLE_BYTES:
            raise HostMigrationError("cold restore bundle size is out of bounds")
        initial_identity = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_mode,
            info.st_uid,
        )
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            handle.seek(0)
            try:
                with tarfile.open(fileobj=handle, mode="r:") as archive:
                    members = archive.getmembers()
                    names = [item.name for item in members]
                    if len(names) != len(set(names)):
                        raise HostMigrationError(
                            "cold restore archive has duplicate members"
                        )
                    index = {item.name: item for item in members}
                    manifest_member = index.get(MANIFEST_NAME)
                    if (
                        manifest_member is None
                        or not manifest_member.isfile()
                        or manifest_member.size > _MAX_MANIFEST_BYTES
                    ):
                        raise HostMigrationError(
                            "cold restore manifest member is invalid"
                        )
                    manifest_file = archive.extractfile(manifest_member)
                    if manifest_file is None:
                        raise HostMigrationError("cold restore manifest cannot be read")
                    try:
                        manifest = json.loads(manifest_file.read())
                    except (UnicodeError, json.JSONDecodeError):
                        raise HostMigrationError(
                            "cold restore manifest is not valid JSON"
                        ) from None
                    records = _verify_manifest(
                        manifest,
                        trust_policy=trust_policy,
                        now=now,
                    )
                    expected_names = {
                        MANIFEST_NAME,
                        *(PAYLOAD_PREFIX + item["path"] for item in records),
                    }
                    if set(names) != expected_names:
                        raise HostMigrationError(
                            "cold restore archive member set differs from manifest"
                        )
                    entries: dict[str, tuple[dict[str, Any], bytes]] = {}
                    for record in records:
                        member = index[PAYLOAD_PREFIX + record["path"]]
                        if record["kind"] == "file":
                            if not member.isfile():
                                raise HostMigrationError(
                                    "cold restore payload node kind mismatch"
                                )
                            extracted = archive.extractfile(member)
                            if extracted is None:
                                raise HostMigrationError(
                                    "cold restore payload cannot be read"
                                )
                            data = extracted.read()
                            mode = _normalized_mode(member.mode)
                        else:
                            if not member.issym():
                                raise HostMigrationError(
                                    "cold restore payload node kind mismatch"
                                )
                            data = _safe_symlink_target(member.linkname).encode("utf-8")
                            mode = "120000"
                        actual = _record(
                            record["path"],
                            kind=record["kind"],
                            mode=mode,
                            data=data,
                        )
                        if actual != record:
                            raise HostMigrationError(
                                "cold restore payload identity mismatch"
                            )
                        entries[record["path"]] = (record, data)
            except tarfile.TarError as exc:
                raise HostMigrationError(
                    f"cold restore archive is malformed: {exc}"
                ) from None
            final_info = os.fstat(handle.fileno())
            final_identity = (
                final_info.st_dev,
                final_info.st_ino,
                final_info.st_size,
                final_info.st_mtime_ns,
                final_info.st_mode,
                final_info.st_uid,
            )
            if final_identity != initial_identity:
                raise HostMigrationError(
                    "cold restore bundle changed while it was verified"
                )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return manifest, entries, digest.hexdigest()


def _write_regular(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_regular(path: Path) -> tuple[bytes, int]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostMigrationError(
            f"cold restore read-back file is unavailable: {exc}"
        ) from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_FILE_BYTES:
            raise HostMigrationError("cold restore read-back node is unsafe")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            data = handle.read()
            after = os.fstat(handle.fileno())
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_mode,
            before.st_uid,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_mode,
            after.st_uid,
        )
        if identity_before != identity_after:
            raise HostMigrationError(
                "cold restore read-back file changed during verification"
            )
        return data, before.st_mode
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    _write_regular(
        path,
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n",
        0o600,
    )
    _fsync_directory(path.parent)


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a directory without replacing any existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin":
        rename = libc.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            -2,  # AT_FDCWD
            source_bytes,
            -2,
            target_bytes,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            -100,  # AT_FDCWD
            source_bytes,
            -100,
            target_bytes,
            1,  # RENAME_NOREPLACE
        )
    else:
        raise HostMigrationError(
            "cold restore no-clobber rename is unsupported on this platform"
        )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise HostMigrationError("cold restore target appeared during staging")
    raise HostMigrationError(
        f"cold restore atomic target install failed: {os.strerror(error)}"
    )


def restore_cold_bundle(
    *,
    bundle_path: Path,
    target_root: Path,
    trust_policy: TrustPolicy,
    target_signing_key_path: Path,
    target_signer_identity: str,
    restored_at: datetime | None = None,
) -> dict[str, Any]:
    """Restore one verified bundle atomically into a path that does not exist."""
    now = _utc(restored_at)
    target = target_root.expanduser()
    if target.exists() or target.is_symlink():
        raise HostMigrationError("cold restore target root must not exist")
    parent = target.parent.resolve()
    if not parent.is_dir() or target.name in {"", ".", ".."}:
        raise HostMigrationError("cold restore target parent is invalid")
    manifest, entries, bundle_sha256 = _read_bundle(
        bundle_path,
        trust_policy=trust_policy,
        now=now,
    )
    staging = Path(
        tempfile.mkdtemp(
            dir=parent,
            prefix=f".{target.name}.cold-restore.",
        )
    )
    os.chmod(staging, 0o700)
    try:
        for path in sorted(entries):
            record, data = entries[path]
            destination = staging.joinpath(*PurePosixPath(path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if record["kind"] == "symlink":
                os.symlink(data.decode("utf-8"), destination)
            else:
                _write_regular(
                    destination,
                    data,
                    0o755 if record["mode"] == "100755" else 0o644,
                )
        restored_records = []
        for path in sorted(entries):
            expected, _data = entries[path]
            destination = staging.joinpath(*PurePosixPath(path).parts)
            if expected["kind"] == "symlink":
                data = _safe_symlink_target(os.readlink(destination)).encode("utf-8")
                actual = _record(
                    path,
                    kind="symlink",
                    mode="120000",
                    data=data,
                )
            else:
                data, mode = _read_regular(destination)
                actual = _record(
                    path,
                    kind="file",
                    mode=_normalized_mode(mode),
                    data=data,
                )
            if actual != expected:
                raise HostMigrationError("cold restore read-back identity mismatch")
            restored_records.append(actual)
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA,
            "migration_id": trust_policy.migration_id,
            "challenge": trust_policy.challenge,
            "restored_at": now.isoformat(),
            "target_host": socket.gethostname(),
            "target_root_name": target.name,
            "bundle_sha256": bundle_sha256,
            "manifest_sha256": manifest["manifest_sha256"],
            "source_snapshot_sha256": manifest["source_snapshot_sha256"],
            "file_count": len(restored_records),
            "byte_count": sum(item["bytes"] for item in restored_records),
            "restored_tree_sha256": sha256_json(restored_records),
            "receipt_path": RECEIPT_PATH,
            "copied_secrets": [],
            "installed_schedules": [],
            "performed_external_effects": [],
            "authorizes_primary_lease": False,
        }
        receipt["receipt_sha256"] = sha256_json(receipt)
        try:
            receipt["attestation"] = sign_mapping(
                receipt,
                private_key_path=target_signing_key_path,
                signer_identity=target_signer_identity,
                signer_role="target",
            )
            verify_mapping(
                receipt,
                trust_policy=trust_policy,
                expected_role="target",
            )
        except HostAttestationError as exc:
            raise HostMigrationError(str(exc)) from None
        _write_receipt(staging / RECEIPT_PATH, receipt)
        if target.exists() or target.is_symlink():
            raise HostMigrationError("cold restore target appeared during staging")
        _rename_directory_noreplace(staging, target)
        _fsync_directory(parent)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)
