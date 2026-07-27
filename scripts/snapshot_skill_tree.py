#!/usr/bin/env python3
"""Materialize a portable, symlink-free user skill snapshot.

The source tree may intentionally expose Agent Skills through symlinks.  Generic
``cp -L`` is not safe here: it follows nested links without checking where they
lead and can copy secrets into Git.  This module walks the dereference graph
itself, accepts targets only below explicitly approved skill roots, rejects
cycles/special files/concurrent mutation, and swaps a fully built snapshot into
place only after the walk succeeds.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SnapshotError(RuntimeError):
    """The source cannot be represented as a safe portable snapshot."""


@dataclass(frozen=True)
class _ApprovedRoot:
    path: Path
    fd: int


def _read_stable_file(fd: int, display: Path) -> tuple[bytes, int]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise SnapshotError(f"skill entry changed type while reading: {display}")
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(fd)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise SnapshotError(f"skill file changed while reading: {display}")
    return b"".join(chunks), before.st_mode


def _lexical_target(parent: Path, target: str) -> Path:
    candidate = Path(target) if os.path.isabs(target) else parent / target
    return Path(os.path.normpath(os.fspath(candidate)))


def _open_approved_target(
    parent: Path,
    target: str,
    roots: tuple[_ApprovedRoot, ...],
) -> tuple[int, Path]:
    candidate = _lexical_target(parent, target)
    selected = next(
        (
            root
            for root in roots
            if candidate == root.path or candidate.is_relative_to(root.path)
        ),
        None,
    )
    if selected is None:
        raise SnapshotError(
            f"skill symlink escapes approved roots: {parent} -> {candidate}"
        )
    relative = candidate.relative_to(selected.path)
    current = os.dup(selected.fd)
    try:
        for index, component in enumerate(relative.parts):
            last = index == len(relative.parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not last:
                flags |= getattr(os, "O_DIRECTORY", 0)
            next_fd = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        return current, candidate
    except OSError as exc:
        os.close(current)
        raise SnapshotError(
            f"cannot open approved skill target {candidate}: {exc}"
        ) from exc


def _snapshot_fd(
    fd: int,
    destination: Path,
    *,
    display: Path,
    approved_roots: tuple[_ApprovedRoot, ...],
    ancestry: frozenset[tuple[int, int]],
) -> None:
    info = os.fstat(fd)
    if stat.S_ISREG(info.st_mode):
        payload, mode = _read_stable_file(fd, display)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        destination.chmod(0o755 if mode & stat.S_IXUSR else 0o644)
        return

    if not stat.S_ISDIR(info.st_mode):
        raise SnapshotError(f"refusing non-regular skill entry: {display}")

    inode = (info.st_dev, info.st_ino)
    if inode in ancestry:
        raise SnapshotError(f"skill directory cycle detected: {display}")
    destination.mkdir(parents=True, exist_ok=False)
    before = os.fstat(fd)
    names = sorted(os.listdir(fd))
    for name in names:
        if name in {".", ".."} or "/" in name:
            raise SnapshotError(f"invalid skill entry name under {display}: {name!r}")
        child_display = display / name
        try:
            child_info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError as exc:
            raise SnapshotError(f"cannot inspect skill entry {child_display}: {exc}") from exc
        if stat.S_ISLNK(child_info.st_mode):
            try:
                link_target = os.readlink(name, dir_fd=fd)
            except OSError as exc:
                raise SnapshotError(
                    f"cannot read skill symlink {child_display}: {exc}"
                ) from exc
            child_fd, target_display = _open_approved_target(
                display, link_target, approved_roots
            )
        else:
            if not (
                stat.S_ISREG(child_info.st_mode)
                or stat.S_ISDIR(child_info.st_mode)
            ):
                raise SnapshotError(
                    f"refusing non-regular skill entry: {child_display}"
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if stat.S_ISDIR(child_info.st_mode):
                flags |= getattr(os, "O_DIRECTORY", 0)
            try:
                child_fd = os.open(name, flags, dir_fd=fd)
            except OSError as exc:
                raise SnapshotError(
                    f"cannot open skill entry {child_display}: {exc}"
                ) from exc
            opened = os.fstat(child_fd)
            if (child_info.st_dev, child_info.st_ino, child_info.st_mode) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
            ):
                os.close(child_fd)
                raise SnapshotError(
                    f"skill entry changed before it could be opened: {child_display}"
                )
            target_display = child_display
        try:
            _snapshot_fd(
                child_fd,
                destination / name,
                display=target_display,
                approved_roots=approved_roots,
                ancestry=ancestry | {inode},
            )
        finally:
            os.close(child_fd)
    after_names = sorted(os.listdir(fd))
    after = os.fstat(fd)
    if names != after_names or (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
    ):
        raise SnapshotError(f"skill directory changed while snapshotting: {display}")


def _contains_symlink(root: Path) -> bool:
    if root.is_symlink():
        return True
    return root.exists() and any(path.is_symlink() for path in root.rglob("*"))


def snapshot_skill_tree(
    source: Path,
    destination: Path,
    *,
    approved_roots: list[Path],
    temp_root: Path,
) -> None:
    if source.is_symlink():
        raise SnapshotError(f"source skill root must not be a symlink: {source}")
    source = source.resolve(strict=True)
    roots_list: list[_ApprovedRoot] = []
    try:
        for root_arg in approved_roots:
            if not root_arg.exists():
                continue
            if root_arg.is_symlink():
                raise SnapshotError(
                    f"approved skill root must not be a symlink: {root_arg}"
                )
            root_path = root_arg.resolve(strict=True)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            root_fd = os.open(root_arg, flags)
            opened = os.fstat(root_fd)
            observed = root_arg.lstat()
            if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
                os.close(root_fd)
                raise SnapshotError(
                    f"approved skill root changed while opening: {root_arg}"
                )
            roots_list.append(_ApprovedRoot(root_path, root_fd))
        roots = tuple(roots_list)
        source_root = next((root for root in roots if root.path == source), None)
        if source_root is None:
            raise SnapshotError(f"source is not an approved skill root: {source}")

        temp_root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="skill-snapshot-", dir=temp_root))
        candidate = workspace / "candidate"
        previous = workspace / "previous"
        previous_valid = False
        try:
            # Never leave a previously broken symlink snapshot in the tracked tree,
            # even when the new source also fails validation.
            if (destination.exists() or destination.is_symlink()) and _contains_symlink(
                destination
            ):
                os.replace(destination, previous)

            source_fd = os.dup(source_root.fd)
            try:
                _snapshot_fd(
                    source_fd,
                    candidate,
                    display=source_root.path,
                    approved_roots=roots,
                    ancestry=frozenset(),
                )
            finally:
                os.close(source_fd)
            if _contains_symlink(candidate):
                raise SnapshotError("candidate snapshot unexpectedly contains a symlink")

            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                previous_valid = not _contains_symlink(destination)
                os.replace(destination, previous)
            try:
                os.replace(candidate, destination)
            except OSError:
                if previous_valid and previous.exists():
                    os.replace(previous, destination)
                raise
            if _contains_symlink(destination):
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink(missing_ok=True)
                if previous_valid and previous.exists():
                    os.replace(previous, destination)
                raise SnapshotError("installed snapshot contains a symlink")
        finally:
            try:
                shutil.rmtree(workspace)
            except OSError as exc:
                print(
                    f"snapshot_skill_tree: cannot remove temporary workspace "
                    f"{workspace}: {exc}",
                    file=sys.stderr,
                )
    finally:
        for root in roots_list:
            os.close(root.fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--approved-root", type=Path, action="append", required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot_skill_tree(
            args.source,
            args.destination,
            approved_roots=args.approved_root,
            temp_root=args.temp_root,
        )
    except SnapshotError as exc:
        print(f"snapshot_skill_tree: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
