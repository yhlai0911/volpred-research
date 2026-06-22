"""Prune old rollback snapshots under storage/ops/rollback_points/.

Keeps snapshots newer than --keep-days (default 14). Dry-run by default.

Usage:
    uv run python scripts/prune_rollback_points.py              # dry-run, keep 14 days
    uv run python scripts/prune_rollback_points.py --apply      # actually delete
    uv run python scripts/prune_rollback_points.py --keep-days 7 --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLLBACK_ROOT = Path("storage/ops/rollback_points")
# Matches trailing timestamp like ...20260415T080047Z or ..._YYYYMMDDTHHMMSSZ
TIMESTAMP_RE = re.compile(r"(\d{8}T\d{6}Z)$")


def _warn_prune(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[prune-rollback] WARN {message}: path={path} "
        f"error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def parse_timestamp(name: str) -> datetime | None:
    m = TIMESTAMP_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def dir_size_bytes(path: Path) -> int:
    total = 0
    for sub in path.rglob("*"):
        try:
            is_file = sub.is_file()
        except OSError as exc:
            _warn_prune("file type check failed; excluding from size total", sub, exc)
            continue
        if not is_file:
            continue
        try:
            total += sub.stat().st_size
        except OSError as exc:
            _warn_prune("file size stat failed; excluding from size total", sub, exc)
    return total


def human(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-days", type=int, default=14, help="Retain snapshots newer than this many days (default 14)")
    parser.add_argument("--apply", action="store_true", help="Actually delete. Default is dry-run")
    parser.add_argument("--root", default=str(ROLLBACK_ROOT))
    parser.add_argument("--preserve", action="append", default=[], help="Snapshot IDs to always keep regardless of age (repeatable)")
    args = parser.parse_args()
    preserve_ids = set(args.preserve)

    root = Path(args.root)
    if not root.exists():
        print(f"{root} does not exist — nothing to prune")
        return

    now = datetime.now(timezone.utc)
    keep_seconds = args.keep_days * 86400

    snapshots: list[tuple[Path, datetime | None, int]] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        ts = parse_timestamp(p.name)
        sz = dir_size_bytes(p)
        snapshots.append((p, ts, sz))

    to_delete: list[tuple[Path, datetime | None, int]] = []
    to_keep: list[tuple[Path, datetime | None, int]] = []
    undated: list[tuple[Path, datetime | None, int]] = []
    preserved: list[tuple[Path, datetime | None, int]] = []
    for p, ts, sz in snapshots:
        if p.name in preserve_ids:
            preserved.append((p, ts, sz))
            continue
        if ts is None:
            undated.append((p, ts, sz))
            continue
        age_sec = (now - ts).total_seconds()
        if age_sec > keep_seconds:
            to_delete.append((p, ts, sz))
        else:
            to_keep.append((p, ts, sz))

    total_before = sum(s for _, _, s in snapshots)
    total_delete = sum(s for _, _, s in to_delete)
    total_keep = sum(s for _, _, s in to_keep)
    total_undated = sum(s for _, _, s in undated)

    total_preserved = sum(s for _, _, s in preserved)

    print(f"Rollback snapshots: total={len(snapshots)}  size={human(total_before)}")
    print(f"  keep ({args.keep_days}d): {len(to_keep)}  size={human(total_keep)}")
    print(f"  preserved (explicit): {len(preserved)}  size={human(total_preserved)}")
    print(f"  undated (preserve): {len(undated)}  size={human(total_undated)}")
    print(f"  delete (> {args.keep_days}d): {len(to_delete)}  size={human(total_delete)}")

    if to_delete:
        print("\nDelete candidates:")
        for p, ts, sz in to_delete:
            age_d = (now - ts).total_seconds() / 86400 if ts else -1
            print(f"  {human(sz):>8}  age={age_d:5.1f}d  {p.name}")

    if not args.apply:
        print("\n[dry-run] pass --apply to actually delete")
        return

    if not to_delete:
        print("\nNothing to delete.")
        return

    for p, _, _ in to_delete:
        shutil.rmtree(p)
    print(f"\nDeleted {len(to_delete)} snapshots. Freed {human(total_delete)}")


if __name__ == "__main__":
    main()
