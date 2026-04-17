from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import project_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(*args: str, text: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_path(),
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout if text else result.stdout.decode()


@dataclass
class RollbackPoint:
    point_id: str
    created_at: str
    branch: str
    head_sha: str
    tracked_patch_path: str
    tracked_files_path: str
    git_status_path: str
    untracked_list_path: str
    storage_archive_path: str | None
    config_archive_path: str | None
    untracked_archive_path: str | None
    restore_steps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rollback_root(storage_dir: str = "storage") -> Path:
    root = project_path(storage_dir, "ops", "rollback_points")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _archive_directory(
    source: Path,
    destination: Path,
    *,
    exclude_prefixes: list[Path] | None = None,
) -> None:
    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if exclude_prefixes:
            candidate = source.parent / tarinfo.name
            for exclude_prefix in exclude_prefixes:
                if candidate == exclude_prefix or exclude_prefix in candidate.parents:
                    return None
        return tarinfo

    with tarfile.open(destination, "w:gz") as tar:
        tar.add(source, arcname=source.name, filter=_filter)


def _archive_paths(paths: list[Path], destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as tar:
        for path in paths:
            if path.exists():
                tar.add(path, arcname=str(path.relative_to(project_path())))


def create_rollback_point(*, point_id: str | None = None, storage_dir: str = "storage") -> dict[str, Any]:
    point_id = point_id or datetime.now(timezone.utc).strftime("rollback_%Y%m%dT%H%M%SZ")
    point_dir = _rollback_root(storage_dir) / point_id
    if point_dir.exists():
        raise RuntimeError(f"Rollback point already exists: {point_id}")
    point_dir.mkdir(parents=True, exist_ok=False)

    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    head_sha = _git("rev-parse", "HEAD").strip()
    tracked_patch = subprocess.run(
        ["git", "diff", "--binary"],
        cwd=project_path(),
        check=True,
        capture_output=True,
    ).stdout
    (point_dir / "tracked.patch").write_bytes(tracked_patch)
    (point_dir / "tracked_files.txt").write_text(_git("ls-files"))
    (point_dir / "git_status.txt").write_text(_git("status", "--short"))
    (point_dir / "untracked.txt").write_text(_git("ls-files", "--others", "--exclude-standard"))

    storage_archive = point_dir / "storage.tar.gz"
    config_archive = point_dir / "config.tar.gz"
    untracked_archive = point_dir / "untracked.tar.gz"

    storage_path = project_path(storage_dir)
    rollback_root = _rollback_root(storage_dir)
    if storage_path.exists():
        _archive_directory(
            storage_path,
            storage_archive,
            exclude_prefixes=[rollback_root, storage_archive],
        )
    if project_path("config").exists():
        _archive_directory(project_path("config"), config_archive)

    untracked_paths = [
        project_path(line.strip())
        for line in (point_dir / "untracked.txt").read_text().splitlines()
        if line.strip()
    ]
    untracked_paths = [
        path
        for path in untracked_paths
        if path != rollback_root and rollback_root not in path.parents
    ]
    if untracked_paths:
        _archive_paths(untracked_paths, untracked_archive)

    manifest = RollbackPoint(
        point_id=point_id,
        created_at=_utc_now(),
        branch=branch,
        head_sha=head_sha,
        tracked_patch_path="tracked.patch",
        tracked_files_path="tracked_files.txt",
        git_status_path="git_status.txt",
        untracked_list_path="untracked.txt",
        storage_archive_path=storage_archive.name if storage_archive.exists() else None,
        config_archive_path=config_archive.name if config_archive.exists() else None,
        untracked_archive_path=untracked_archive.name if untracked_archive.exists() else None,
        restore_steps=[
            "git restore --source <head_sha> --worktree --staged .",
            "git apply tracked.patch",
            "extract storage/config archives over repo root",
            "restore baseline untracked archive and remove post-baseline untracked files",
        ],
    )
    (point_dir / "manifest.json").write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    return manifest.to_dict()


def list_rollback_points(*, storage_dir: str = "storage") -> list[dict[str, Any]]:
    root = _rollback_root(storage_dir)
    manifests: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json"), reverse=True):
        manifests.append(json.loads(manifest_path.read_text()))
    return manifests


def restore_rollback_point(
    point_id: str,
    *,
    storage_dir: str = "storage",
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    point_dir = _rollback_root(storage_dir) / point_id
    manifest_path = point_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Unknown rollback point: {point_id}")
    manifest = json.loads(manifest_path.read_text())
    if not force and _git("rev-parse", "HEAD").strip() != str(manifest["head_sha"]):
        raise RuntimeError("Current HEAD differs from rollback baseline. Re-run with force=True if intentional.")

    baseline_untracked = {
        line.strip()
        for line in (point_dir / str(manifest["untracked_list_path"])).read_text().splitlines()
        if line.strip()
    }
    current_untracked = {
        line.strip()
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line.strip()
    }
    extra_untracked = sorted(
        path
        for path in current_untracked - baseline_untracked
        if not path.startswith(f"{storage_dir}/ops/rollback_points/")
    )

    result = {
        "point_id": point_id,
        "dry_run": dry_run,
        "head_sha": manifest["head_sha"],
        "extra_untracked": extra_untracked,
    }
    if dry_run:
        return result

    subprocess.run(
        ["git", "restore", "--source", str(manifest["head_sha"]), "--worktree", "--staged", "."],
        cwd=project_path(),
        check=True,
    )

    for relative in extra_untracked:
        target = project_path(relative)
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    subprocess.run(
        ["git", "apply", str(point_dir / str(manifest["tracked_patch_path"]))],
        cwd=project_path(),
        check=True,
    )

    for archive_key in ("storage_archive_path", "config_archive_path", "untracked_archive_path"):
        archive_name = manifest.get(archive_key)
        if not archive_name:
            continue
        archive_path = point_dir / str(archive_name)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(project_path())

    restore_log = point_dir / "restore_log.json"
    restore_log.write_text(
        json.dumps(
            {
                "restored_at": _utc_now(),
                "point_id": point_id,
                "removed_untracked": extra_untracked,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result
