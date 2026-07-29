"""Immutable committed release images for the dispatch supervisor.

The live main checkout is an authoring surface.  Editors and ``apply_patch``
write working-tree bytes before the Git transaction lock is acquired, so no
lock around ``hash -> SIGTERM`` can make those bytes immutable until launchd
imports them.

A release is therefore a deterministic zip built from one Git commit (or from
explicit hermetic roots in tests), installed write-once under the private
supervisor run directory, and addressed by its SHA-256.  The launchd bootstrap
verifies that digest and imports ``scripts`` plus ``volpred`` from the archive,
while keeping the repository only as the working directory for data/config.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from volpred.ops.git_writer_lock import git_writer_lock

RUNTIME_RELEASE_ID_ENV = "VOLPRED_SUPERVISOR_RELEASE_ID"
RUNTIME_RELEASE_SHA_ENV = "VOLPRED_SUPERVISOR_RELEASE_SHA256"
RUNTIME_RELEASE_COMMIT_ENV = "VOLPRED_SUPERVISOR_RELEASE_COMMIT"
RUNTIME_RELEASE_ARCHIVE_ENV = "VOLPRED_SUPERVISOR_RELEASE_ARCHIVE"
STAGE0_PATH_ENV = "VOLPRED_SUPERVISOR_STAGE0_PATH"
POINTER_NAME = "current_release.json"
RELEASES_DIR_NAME = "releases"
BOOTSTRAPS_DIR_NAME = "bootstraps"
BOOT_ATTEMPTS_DIR_NAME = "boot_attempts"
ROLLBACK_RECEIPTS_DIR_NAME = "rollback_receipts"
MAX_CANDIDATE_BOOT_ATTEMPTS = 2
CANDIDATE_STARTUP_TIMEOUT_S = 120.0
PRODUCTION_PATHS = ("scripts", "src/volpred")
MONITORED_CLEAN_PATHS = (
    "scripts/dispatch_supervisor",
    "scripts/dispatch_supervisor_bootstrap.py",
    "src/volpred/ops",
)


class ReleaseImageError(RuntimeError):
    """A committed immutable supervisor release cannot be trusted."""


def materialize(
    *,
    repo_root: Path,
    run_root: Path,
    source_roots: Iterable[Path] | None = None,
) -> dict[str, str]:
    """Install and return one content-addressed immutable release archive."""
    repo_root = Path(repo_root).resolve()
    run_root = Path(run_root)
    releases = run_root / RELEASES_DIR_NAME
    _ensure_private_directory(run_root)
    _ensure_private_directory(releases)

    production = source_roots is None
    if production:
        commit, entries = _committed_entries(repo_root)
    else:
        commit = "test-fixture"
        entries = _explicit_entries(tuple(Path(root) for root in source_roots))
    archive_bytes = _deterministic_zip(entries, commit=commit)
    release_sha = hashlib.sha256(archive_bytes).hexdigest()
    archive = releases / f"{release_sha}.zip"
    _install_write_once(archive, archive_bytes)
    bootstrap = _install_bootstrap_chain(
        repo_root=repo_root,
        run_root=run_root,
        committed_entries=entries if production else None,
    )
    return {
        "release_archive": str(archive),
        "release_sha256": release_sha,
        "release_commit": commit,
        **bootstrap,
    }


def verify(request: dict[str, Any]) -> dict[str, str]:
    """Verify request-pinned archive identity without trusting the pointer."""
    raw_archive = request.get("release_archive")
    expected_sha = request.get("release_sha256")
    expected_commit = request.get("release_commit")
    bootstrap_path = request.get("bootstrap_path")
    bootstrap_sha = request.get("bootstrap_sha256")
    stage0_path = request.get("stage0_path")
    stage0_sha = request.get("stage0_sha256")
    if not isinstance(raw_archive, str) or not raw_archive:
        raise ReleaseImageError("release_archive is unavailable")
    if not _is_sha256(expected_sha):
        raise ReleaseImageError("release_sha256 is invalid")
    if not isinstance(expected_commit, str) or not expected_commit:
        raise ReleaseImageError("release_commit is invalid")
    if not isinstance(bootstrap_path, str) or not bootstrap_path:
        raise ReleaseImageError("bootstrap_path is invalid")
    if not _is_sha256(bootstrap_sha):
        raise ReleaseImageError("bootstrap_sha256 is invalid")
    if not isinstance(stage0_path, str) or not stage0_path:
        raise ReleaseImageError("stage0_path is invalid")
    if not _is_sha256(stage0_sha):
        raise ReleaseImageError("stage0_sha256 is invalid")
    archive = Path(raw_archive)
    _validate_private_regular(archive)
    observed_sha = _sha256_file(archive)
    if observed_sha != expected_sha:
        raise ReleaseImageError(
            f"release archive digest mismatch: expected={expected_sha} "
            f"observed={observed_sha}"
        )
    if archive.name != f"{expected_sha}.zip":
        raise ReleaseImageError("release archive path is not content-addressed")
    _verify_manifest(archive, expected_commit=expected_commit)
    bootstrap = Path(bootstrap_path)
    _validate_private_regular(bootstrap, allow_executable=True)
    observed_bootstrap_sha = _sha256_file(bootstrap)
    if observed_bootstrap_sha != bootstrap_sha:
        raise ReleaseImageError(
            f"bootstrap digest mismatch: expected={bootstrap_sha} "
            f"observed={observed_bootstrap_sha}"
        )
    stage0 = Path(stage0_path)
    _validate_private_regular(stage0, allow_executable=True)
    observed_stage0_sha = _sha256_file(stage0)
    if observed_stage0_sha != stage0_sha:
        raise ReleaseImageError(
            f"stage-0 digest mismatch: expected={stage0_sha} "
            f"observed={observed_stage0_sha}"
        )
    return {
        "release_archive": str(archive),
        "release_sha256": str(expected_sha),
        "release_commit": expected_commit,
        "bootstrap_path": str(bootstrap),
        "bootstrap_sha256": str(bootstrap_sha),
        "stage0_path": str(stage0),
        "stage0_sha256": str(stage0_sha),
    }


def activate(
    *,
    run_root: Path,
    request: dict[str, Any],
) -> tuple[Path, dict[str, Any] | None]:
    """Atomically point the stable bootstrap at one already-verified release."""
    verified = verify(request)
    path = Path(run_root) / POINTER_NAME
    previous = _read_pointer(path)
    pointer = {
        "schema_version": 2,
        "activation_state": "candidate",
        "max_boot_attempts": MAX_CANDIDATE_BOOT_ATTEMPTS,
        "startup_timeout_s": CANDIDATE_STARTUP_TIMEOUT_S,
        "request_id": request["request_id"],
        **verified,
        "previous_release": _stable_pointer(previous),
    }
    _atomic_replace_json(path, pointer)
    return path, previous


def install_initial_stable(
    *,
    run_root: Path,
    request: dict[str, Any],
) -> tuple[Path, dict[str, Any] | None]:
    """Install a first stable pointer for the old-launchd cutover transaction."""
    verified = verify(request)
    path = Path(run_root) / POINTER_NAME
    previous = _read_pointer(path)
    if previous is not None:
        return path, previous
    pointer = {
        "schema_version": 2,
        "activation_state": "stable",
        "request_id": request["request_id"],
        **verified,
    }
    _atomic_replace_json(path, pointer)
    return path, None


def promote(
    *,
    run_root: Path,
    request: dict[str, Any],
) -> None:
    """Atomically acknowledge a candidate as the last-known-good release."""
    path = Path(run_root) / POINTER_NAME
    pointer = _read_pointer(path)
    if pointer is None:
        raise ReleaseImageError("release pointer disappeared before promotion")
    verified = verify(request)
    exact_identity = {
        "request_id": request.get("request_id"),
        **verified,
    }
    if pointer.get("activation_state") == "stable" and all(
        pointer.get(key) == value for key, value in exact_identity.items()
    ):
        _remove_boot_attempt(run_root=run_root, request=request)
        return
    if pointer.get("request_id") != request.get("request_id") or (
        pointer.get("activation_state") != "candidate"
    ):
        raise ReleaseImageError("release pointer no longer names this candidate")
    _atomic_replace_json(
        path,
        {
            "schema_version": 2,
            "activation_state": "stable",
            "request_id": request["request_id"],
            **verified,
        },
    )
    _remove_boot_attempt(run_root=run_root, request=request)
    _fsync_directory(path.parent)


def _remove_boot_attempt(
    *,
    run_root: Path,
    request: dict[str, Any],
) -> None:
    attempts = (
        Path(run_root)
        / BOOT_ATTEMPTS_DIR_NAME
        / f"{request['request_id']}.json"
    )
    try:
        attempts.unlink()
    except FileNotFoundError:
        pass  # silent-ok: boot-attempt cleanup is idempotent
    _fsync_directory(Path(run_root))


def restore_pointer(*, run_root: Path, previous: dict[str, Any] | None) -> None:
    """Restore activation when the signal actuator fails synchronously."""
    path = Path(run_root) / POINTER_NAME
    if previous is not None:
        _atomic_replace_json(path, previous)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return  # silent-ok: absent pointer is already restored
    _fsync_directory(path.parent)


def runtime_release() -> dict[str, str] | None:
    release_id = os.environ.get(RUNTIME_RELEASE_ID_ENV)
    release_sha = os.environ.get(RUNTIME_RELEASE_SHA_ENV)
    release_commit = os.environ.get(RUNTIME_RELEASE_COMMIT_ENV)
    archive = os.environ.get(RUNTIME_RELEASE_ARCHIVE_ENV)
    if not any((release_id, release_sha, release_commit, archive)):
        return None
    if not all((release_id, release_sha, release_commit, archive)):
        raise ReleaseImageError("runtime release environment is incomplete")
    if not _is_sha256(release_id) or not _is_sha256(release_sha):
        raise ReleaseImageError("runtime release environment has invalid identity")
    return {
        "request_id": str(release_id),
        "release_sha256": str(release_sha),
        "release_commit": str(release_commit),
        "release_archive": str(archive),
    }


def _committed_entries(repo_root: Path) -> tuple[str, dict[str, bytes]]:
    with git_writer_lock(
        repo_root,
        actor="dispatch-supervisor.release-image",
        timeout_s=5,
    ):
        commit = _git(repo_root, "rev-parse", "HEAD").decode().strip()
        if not _is_object_id(commit):
            raise ReleaseImageError("cannot resolve committed release identity")
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *MONITORED_CLEAN_PATHS,
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if dirty.returncode != 0:
            raise ReleaseImageError("cannot inspect monitored release paths")
        if dirty.stdout.strip():
            paths = [
                line[3:].decode("utf-8", errors="replace")
                for line in dirty.stdout.splitlines()[:8]
                if len(line) >= 4
            ]
            raise ReleaseImageError(
                "refusing release while monitored source is uncommitted: "
                + ", ".join(paths)
            )
        raw_tar = _git(
            repo_root,
            "archive",
            "--format=tar",
            commit,
            "--",
            *PRODUCTION_PATHS,
        )

    entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or not member.name.endswith(".py"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ReleaseImageError(f"cannot extract release member {member.name}")
            entries[member.name] = extracted.read()
    if not entries:
        raise ReleaseImageError("committed release contained no Python source")
    entries.setdefault("scripts/__init__.py", b"")
    return commit, entries


def _explicit_entries(roots: tuple[Path, ...]) -> dict[str, bytes]:
    if not roots:
        raise ReleaseImageError("test release requires at least one source root")
    entries: dict[str, bytes] = {"scripts/__init__.py": b""}
    for index, root in enumerate(roots):
        root = root.resolve()
        candidates = root.rglob("*.py") if root.is_dir() else (root,)
        for candidate in sorted(candidates):
            details = candidate.lstat()
            if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise ReleaseImageError(f"release source is not regular: {candidate}")
            relative = (
                candidate.relative_to(root)
                if root.is_dir()
                else Path(candidate.name)
            )
            entries[f"fixture_roots/{index}/{relative.as_posix()}"] = (
                candidate.read_bytes()
            )
    if len(entries) == 1:
        raise ReleaseImageError("test release contained no Python source")
    return entries


def _install_bootstrap_chain(
    *,
    repo_root: Path,
    run_root: Path,
    committed_entries: dict[str, bytes] | None,
) -> dict[str, str]:
    if committed_entries is None:
        stage1_payload = (
            repo_root / "scripts" / "dispatch_supervisor_bootstrap.py"
        ).read_bytes()
        stage0_payload = (
            repo_root / "scripts" / "dispatch_supervisor_stage0.py"
        ).read_bytes()
        stage1_dir = run_root / BOOTSTRAPS_DIR_NAME
        stage0_path = run_root / "dispatch-supervisor-stage0.py"
    else:
        try:
            stage1_payload = committed_entries[
                "scripts/dispatch_supervisor_bootstrap.py"
            ]
            stage0_payload = committed_entries[
                "scripts/dispatch_supervisor_stage0.py"
            ]
        except KeyError as exc:
            raise ReleaseImageError(
                "committed release is missing the bootstrap chain"
            ) from exc
        configured_stage0 = os.environ.get(STAGE0_PATH_ENV)
        # Stage-0 validates this directory relative to the pointer root.  Do
        # not make it configurable independently or a valid pointer could be
        # unbootable after installation.
        stage1_dir = run_root / BOOTSTRAPS_DIR_NAME
        if configured_stage0:
            stage0_path = Path(configured_stage0).expanduser()
        elif _is_default_run_root(run_root):
            stage0_path = (
                Path.home()
                / ".volpred"
                / "bin"
                / "dispatch-supervisor-stage0.py"
            )
        else:
            stage0_path = run_root / "dispatch-supervisor-stage0.py"

    _ensure_private_directory(stage1_dir)
    stage1_sha = hashlib.sha256(stage1_payload).hexdigest()
    stage1_path = stage1_dir / f"{stage1_sha}.py"
    _install_write_once_mode(stage1_path, stage1_payload, mode=0o400)

    _ensure_private_directory(stage0_path.parent)
    stage0_sha = hashlib.sha256(stage0_payload).hexdigest()
    if stage0_path.exists():
        _validate_private_regular(stage0_path, allow_executable=True)
        if _sha256_file(stage0_path) != stage0_sha:
            raise ReleaseImageError(
                "installed immutable stage-0 differs from committed stage-0; "
                "use an explicit compatible migration"
            )
    else:
        _install_write_once_mode(stage0_path, stage0_payload, mode=0o500)
    return {
        "bootstrap_path": str(stage1_path),
        "bootstrap_sha256": stage1_sha,
        "stage0_path": str(stage0_path),
        "stage0_sha256": stage0_sha,
    }


def _is_default_run_root(run_root: Path) -> bool:
    return run_root.resolve() == (
        Path.home() / ".volpred" / "run" / "dispatch-supervisor-reload"
    ).resolve()


def _deterministic_zip(entries: dict[str, bytes], *, commit: str) -> bytes:
    output = io.BytesIO()
    manifest = json.dumps(
        {
            "schema_version": 1,
            "release_commit": commit,
            "entries": sorted(entries),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payloads = {**entries, "VOLPRED_RELEASE.json": manifest}
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, payload in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o400 << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _git(repo_root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseImageError(f"git {' '.join(args[:2])} failed: {detail[:300]}")
    return proc.stdout


def _install_write_once(path: Path, payload: bytes) -> None:
    _install_write_once_mode(path, payload, mode=0o400)


def _install_write_once_mode(path: Path, payload: bytes, *, mode: int) -> None:
    if path.exists():
        _validate_private_regular(path, allow_executable=bool(mode & 0o100))
        if _sha256_file(path) != hashlib.sha256(payload).hexdigest():
            raise ReleaseImageError(f"content-addressed release collision: {path}")
        return
    fd, tmp_name = tempfile.mkstemp(prefix=".release.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path, follow_symlinks=False)
        except FileExistsError:
            _validate_private_regular(path, allow_executable=bool(mode & 0o100))
            if _sha256_file(path) != hashlib.sha256(payload).hexdigest():
                raise ReleaseImageError(
                    f"content-addressed release collision: {path}"
                )
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: content-addressed install consumed the temp file


def _atomic_replace_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
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


def _read_pointer(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    _validate_private_regular(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseImageError(f"release pointer is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseImageError("release pointer must be a JSON object")
    return payload


def _stable_pointer(pointer: dict[str, Any] | None) -> dict[str, Any] | None:
    if pointer is None:
        return None
    if pointer.get("activation_state") == "candidate":
        previous = pointer.get("previous_release")
        return dict(previous) if isinstance(previous, dict) else None
    stable = dict(pointer)
    stable["schema_version"] = 2
    stable["activation_state"] = "stable"
    stable.pop("previous_release", None)
    stable.pop("max_boot_attempts", None)
    stable.pop("startup_timeout_s", None)
    return stable


def _verify_manifest(path: Path, *, expected_commit: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ReleaseImageError("release archive has duplicate members")
            raw_manifest = archive.read("VOLPRED_RELEASE.json")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ReleaseImageError(f"release manifest is unavailable: {exc}") from exc
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise ReleaseImageError("release manifest is malformed") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ReleaseImageError("release manifest schema is invalid")
    if manifest.get("release_commit") != expected_commit:
        raise ReleaseImageError("release manifest commit does not match pointer")
    entries = manifest.get("entries")
    if (
        not isinstance(entries, list)
        or any(not isinstance(item, str) for item in entries)
        or len(entries) != len(set(entries))
    ):
        raise ReleaseImageError("release manifest entries are invalid")
    expected_names = set(entries) | {"VOLPRED_RELEASE.json"}
    if set(names) != expected_names:
        raise ReleaseImageError("release archive members do not match manifest")


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise ReleaseImageError(f"release directory is not private: {path}")


def _validate_private_regular(
    path: Path,
    *,
    allow_executable: bool = False,
) -> None:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
        or (
            not allow_executable
            and details.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
    ):
        raise ReleaseImageError(f"release file is not private and regular: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            raise ReleaseImageError(f"release descriptor is untrusted: {path}")
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


def _is_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value)
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
