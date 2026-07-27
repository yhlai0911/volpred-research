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
from pathlib import Path


class SnapshotError(RuntimeError):
    """The source cannot be represented as a safe portable snapshot."""


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _read_stable_file(source: Path) -> tuple[bytes, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise SnapshotError(f"cannot open regular skill file {source}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise SnapshotError(f"skill entry changed type while reading: {source}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
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
        raise SnapshotError(f"skill file changed while reading: {source}")
    return b"".join(chunks), before.st_mode


def _snapshot_node(
    source: Path,
    destination: Path,
    *,
    approved_roots: tuple[Path, ...],
    ancestry: frozenset[tuple[int, int]],
) -> None:
    try:
        info = source.lstat()
    except OSError as exc:
        raise SnapshotError(f"cannot inspect skill entry {source}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode):
        try:
            target = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SnapshotError(f"broken or cyclic skill symlink {source}: {exc}") from exc
        if not _is_within(target, approved_roots):
            raise SnapshotError(
                f"skill symlink escapes approved roots: {source} -> {target}"
            )
        _snapshot_node(
            target,
            destination,
            approved_roots=approved_roots,
            ancestry=ancestry,
        )
        return

    if stat.S_ISREG(info.st_mode):
        payload, mode = _read_stable_file(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        destination.chmod(0o755 if mode & stat.S_IXUSR else 0o644)
        return

    if not stat.S_ISDIR(info.st_mode):
        raise SnapshotError(f"refusing non-regular skill entry: {source}")

    inode = (info.st_dev, info.st_ino)
    if inode in ancestry:
        raise SnapshotError(f"skill directory cycle detected: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise SnapshotError(f"cannot open skill directory {source}: {exc}") from exc
    try:
        before = os.fstat(fd)
        names = sorted(os.listdir(fd))
        for name in names:
            if name in {".", ".."} or "/" in name:
                raise SnapshotError(f"invalid skill entry name under {source}: {name!r}")
            _snapshot_node(
                source / name,
                destination / name,
                approved_roots=approved_roots,
                ancestry=ancestry | {inode},
            )
        after_names = sorted(os.listdir(fd))
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if names != after_names or (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
    ):
        raise SnapshotError(f"skill directory changed while snapshotting: {source}")


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
    source = source.resolve(strict=True)
    # An optional approved root may not be installed on every host. Its lexical
    # canonical location is still part of the policy; individual symlink targets
    # must resolve strictly before they can be traversed.
    roots = tuple(root.resolve(strict=False) for root in approved_roots)
    if not _is_within(source, roots):
        raise SnapshotError(f"source is outside approved roots: {source}")
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

        _snapshot_node(
            source,
            candidate,
            approved_roots=roots,
            ancestry=frozenset(),
        )
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
