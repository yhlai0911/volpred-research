#!/usr/bin/env python3
"""Stable launchd bootstrap for an immutable dispatch-supervisor release.

This file intentionally uses only the standard library.  It executes before
any project package is imported, verifies the content-addressed release
pointer, removes the mutable repository from Python's import path, and then
loads the supervisor from the pinned archive.

The no-pointer fallback exists only for first installation/rollback.  Once a
release pointer is active, malformed or mismatched release state fails closed
instead of silently importing mutable working-tree code.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import json
import os
import runpy
import stat
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT_ENV = "VOLPRED_DEFERRED_RELOAD_ROOT"
POINTER_NAME = "current_release.json"
RELEASES_DIR_NAME = "releases"


class _PinnedReleaseLoader(importlib.abc.Loader):
    """Execute zip-pinned code while preserving canonical data-root semantics."""

    def __init__(
        self,
        *,
        delegate: Any,
        fullname: str,
        canonical_origin: str,
        archive_origin: str,
    ) -> None:
        self._delegate = delegate
        self._fullname = fullname
        self._canonical_origin = canonical_origin
        self._archive_origin = archive_origin

    def create_module(self, spec):
        creator = getattr(self._delegate, "create_module", None)
        return creator(spec) if creator is not None else None

    def exec_module(self, module: ModuleType) -> None:
        code = self._delegate.get_code(self._fullname)
        if code is None:
            raise ImportError(f"pinned release has no code for {self._fullname}")
        module.__file__ = self._canonical_origin
        module.__cached__ = None
        exec(code, module.__dict__)  # noqa: S102 - verified immutable archive

    def get_code(self, fullname: str):
        return self._delegate.get_code(fullname)

    def get_source(self, fullname: str):
        getter = getattr(self._delegate, "get_source", None)
        return getter(fullname) if getter is not None else None

    def is_package(self, fullname: str) -> bool:
        return bool(self._delegate.is_package(fullname))

    def get_data(self, path: str) -> bytes:
        canonical = str(self._canonical_origin)
        archive = self._archive_origin
        canonical_parent = str(Path(canonical).parent)
        archive_parent = archive.rsplit("/", 1)[0]
        if path == canonical:
            mapped = archive
        elif path.startswith(f"{canonical_parent}{os.sep}"):
            mapped = f"{archive_parent}/{path.removeprefix(canonical_parent + os.sep)}"
        else:
            mapped = path
        return self._delegate.get_data(mapped)


class _PinnedReleaseFinder(importlib.abc.MetaPathFinder):
    def __init__(self, *, archive: str, repo: Path) -> None:
        self._archive = archive
        self._repo = repo

    def find_spec(self, fullname: str, path=None, target=None):
        if not (fullname == "scripts" or fullname.startswith(("scripts.", "volpred"))):
            return None
        parts = fullname.split(".")
        base = (
            f"{self._archive}/src"
            if parts[0] == "volpred"
            else self._archive
        )
        parent = "/".join(parts[:-1])
        search_path = [f"{base}/{parent}" if parent else base]
        spec = importlib.machinery.PathFinder.find_spec(fullname, search_path)
        if spec is None or spec.loader is None or not spec.origin:
            return None
        archive_origin = str(spec.origin)
        canonical = self._canonical_origin(archive_origin)
        if canonical is None:
            return None
        spec.loader = _PinnedReleaseLoader(
            delegate=spec.loader,
            fullname=fullname,
            canonical_origin=str(canonical),
            archive_origin=archive_origin,
        )
        spec.origin = str(canonical)
        spec.cached = None
        return spec

    def _canonical_origin(self, origin: str) -> Path | None:
        src_prefix = f"{self._archive}/src/"
        root_prefix = f"{self._archive}/"
        if origin.startswith(src_prefix):
            return self._repo / "src" / origin.removeprefix(src_prefix)
        if origin.startswith(root_prefix):
            return self._repo / origin.removeprefix(root_prefix)
        return None


def _run_root() -> Path:
    configured = os.environ.get(ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".volpred" / "run" / "dispatch-supervisor-reload"


def _private_regular(path: Path) -> os.stat_result:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_mode & 0o077
    ):
        raise RuntimeError(f"untrusted supervisor release file: {path}")
    return details


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


def _load_pointer() -> dict[str, str] | None:
    run_root = _run_root()
    pointer_path = run_root / POINTER_NAME
    if not pointer_path.exists():
        return None
    _private_regular(pointer_path)
    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "request_id",
        "release_archive",
        "release_sha256",
        "release_commit",
        "bootstrap_path",
        "bootstrap_sha256",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise RuntimeError("supervisor release pointer is malformed")
    if payload["schema_version"] not in {1, 2}:
        raise RuntimeError("unsupported supervisor release pointer schema")
    request_id = payload["request_id"]
    release_sha = payload["release_sha256"]
    release_commit = payload["release_commit"]
    bootstrap_path = Path(str(payload["bootstrap_path"]))
    bootstrap_sha = payload["bootstrap_sha256"]
    if not _is_sha256(request_id) or not _is_sha256(release_sha):
        raise RuntimeError("supervisor release pointer identity is invalid")
    if not _is_object_id(release_commit):
        raise RuntimeError("supervisor release commit is invalid")
    if not _is_sha256(bootstrap_sha):
        raise RuntimeError("supervisor bootstrap identity is invalid")
    if Path(__file__).resolve() != bootstrap_path.resolve():
        raise RuntimeError("launchd executed an unpinned supervisor bootstrap")
    _private_regular(bootstrap_path)
    observed_bootstrap = _sha256(bootstrap_path)
    if observed_bootstrap != bootstrap_sha:
        raise RuntimeError(
            f"supervisor bootstrap digest mismatch expected={bootstrap_sha} "
            f"observed={observed_bootstrap}"
        )
    archive = Path(str(payload["release_archive"]))
    expected_parent = (run_root / RELEASES_DIR_NAME).resolve()
    if archive.parent.resolve() != expected_parent:
        raise RuntimeError("supervisor release archive escaped the release root")
    if archive.name != f"{release_sha}.zip":
        raise RuntimeError("supervisor release archive is not content-addressed")
    _private_regular(archive)
    observed = _sha256(archive)
    if observed != release_sha:
        raise RuntimeError(
            f"supervisor release digest mismatch expected={release_sha} "
            f"observed={observed}"
        )
    _verify_manifest(archive, expected_commit=release_commit)
    return {
        "request_id": request_id,
        "release_archive": str(archive),
        "release_sha256": release_sha,
        "release_commit": release_commit,
        "bootstrap_path": str(bootstrap_path),
        "bootstrap_sha256": str(bootstrap_sha),
    }


def _verify_manifest(path: Path, *, expected_commit: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise RuntimeError("supervisor release has duplicate members")
            raw = archive.read("VOLPRED_RELEASE.json")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"supervisor release manifest unavailable: {exc}") from exc
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeError("supervisor release manifest schema is invalid")
    if manifest.get("release_commit") != expected_commit:
        raise RuntimeError("supervisor release manifest commit mismatch")
    entries = manifest.get("entries")
    if (
        not isinstance(entries, list)
        or any(not isinstance(item, str) for item in entries)
        or len(entries) != len(set(entries))
        or set(names) != set(entries) | {"VOLPRED_RELEASE.json"}
    ):
        raise RuntimeError("supervisor release manifest members mismatch")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and (
            value == "test-fixture"
            or (
                len(value) in {40, 64}
                and all(character in "0123456789abcdef" for character in value)
            )
        )
    )


def _activate_import_path(release: dict[str, str]) -> None:
    archive = release["release_archive"]
    repo = Path.cwd().resolve()
    mutable_roots = {
        repo,
        (repo / "src").resolve(),
        (repo / "scripts").resolve(),
    }
    retained: list[str] = []
    for raw in sys.path:
        candidate = Path(raw or os.getcwd())
        try:
            resolved = candidate.resolve()
        except OSError:
            retained.append(raw)
            continue  # silent-ok: retain an unresolvable non-release sys.path entry
        if resolved not in mutable_roots:
            retained.append(raw)
    sys.path[:] = [archive, f"{archive}/src", *retained]
    sys.meta_path.insert(0, _PinnedReleaseFinder(archive=archive, repo=repo))
    os.environ["VOLPRED_SUPERVISOR_RELEASE_ID"] = release["request_id"]
    os.environ["VOLPRED_SUPERVISOR_RELEASE_SHA256"] = release["release_sha256"]
    os.environ["VOLPRED_SUPERVISOR_RELEASE_COMMIT"] = release["release_commit"]
    os.environ["VOLPRED_SUPERVISOR_RELEASE_ARCHIVE"] = archive
    os.environ["VOLPRED_SUPERVISOR_BOOTSTRAP_SHA256"] = release[
        "bootstrap_sha256"
    ]
    os.environ["VOLPRED_CANONICAL_REPO_ROOT"] = str(repo)
    sys.addaudithook(_deny_mutable_python_execution(repo))


def _deny_mutable_python_execution(repo: Path):
    """Reject future path-loader bypasses into the mutable checkout."""
    mutable_roots = (
        (repo / "scripts").resolve(),
        (repo / "src" / "volpred").resolve(),
    )

    def audit(event: str, args: tuple[Any, ...]) -> None:
        filename: object | None = None
        if event == "exec" and args:
            filename = getattr(args[0], "co_filename", None)
        elif event == "compile" and len(args) > 1:
            filename = args[1]
        if not isinstance(filename, (str, bytes)):
            return
        path = Path(os.fsdecode(filename))
        if not path.is_absolute():
            return
        try:
            candidate = path.resolve()
        except OSError:
            return  # silent-ok: unresolvable code origin cannot map to mutable roots
        if not any(
            _is_relative_to(candidate, mutable_root)
            for mutable_root in mutable_roots
        ):
            return
        if candidate.suffix in {".py", ".pyc"}:
            raise RuntimeError(
                f"refusing mutable Python execution in pinned release: {candidate}"
            )

    return audit


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False  # silent-ok: path-containment miss is expected
    return True


def main() -> int:
    sys.dont_write_bytecode = True
    release = _load_pointer()
    if release is None:
        print(
            "dispatch-supervisor bootstrap: no immutable release pointer; "
            "using canonical first-install fallback",
            file=sys.stderr,
        )
    else:
        _activate_import_path(release)
    runpy.run_module("scripts.dispatch_supervisor.supervisor", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
