#!/usr/bin/env python3
"""Atomically reserve experiment K-ids.

This is the write-side guard for the 2026-06-23 K-id race incidents.  The
registry is intentionally small and append-only-ish: every caller takes an
exclusive file lock, scans legacy sources for backward compatibility, reserves
the next integer, and writes the reservation before doing experiment work.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from volpred.ops.diagnostics import warn

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "storage" / "ops" / "k_id_registry.json"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

_K_RE = re.compile(r"\bK(\d{1,6})(?:[A-Za-z_]\w*)?\b", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _topic_hash(topic: str | None) -> str | None:
    text = " ".join((topic or "").lower().split())
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _extract_k_numbers(text: str | None) -> set[int]:
    if not text:
        return set()
    out: set[int] = set()
    for match in _K_RE.finditer(str(text)):
        try:
            out.add(int(match.group(1)))
        except ValueError as exc:
            warn("kid_reserve", "k-number int parse failed", err=str(exc), token=match.group(0))
            continue
    return out


def _default_lock_path(registry_path: Path) -> Path:
    return registry_path.parent / "locks" / f"{registry_path.stem}.lock"


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # silent-ok: directory fsync is a best-effort durability improvement, not part of K-id uniqueness/correctness


def _load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "last_k_id": 0, "reservations": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"k_id registry unreadable: path={path} error={type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"k_id registry must be an object: path={path}")
    if data.get("schema_version") not in (None, 1):
        raise ValueError(f"unsupported k_id registry schema_version={data.get('schema_version')!r}")
    reservations = data.get("reservations", [])
    if not isinstance(reservations, list):
        raise ValueError(f"k_id registry reservations must be a list: path={path}")
    data.setdefault("schema_version", 1)
    data.setdefault("last_k_id", 0)
    data["reservations"] = reservations
    return data


def _registry_k_numbers(registry: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    try:
        out.add(int(registry.get("last_k_id") or 0))
    except (TypeError, ValueError) as exc:
        warn(
            "kid_reserve",
            "registry last_k_id not coercible to int; excluded from known set (collision risk)",
            err=str(exc),
            last_k_id=registry.get("last_k_id"),
        )
    for rec in registry.get("reservations", []):
        if not isinstance(rec, dict):
            continue
        for key in ("number", "k_id"):
            value = rec.get(key)
            if isinstance(value, int):
                out.add(value)
            elif isinstance(value, str):
                out.update(_extract_k_numbers(value))
    return {n for n in out if n > 0}


def _scan_experiment_dirs(root: Path) -> set[int]:
    out: set[int] = set()
    for base in (root / "experiments",):
        if not base.exists():
            continue
        try:
            children = list(base.iterdir())
        except OSError as exc:
            warn(
                "kid_reserve",
                "experiment dir scan failed; known K-ids may be undercounted (collision risk)",
                err=str(exc),
                path=str(base),
            )
            continue
        for path in children:
            if path.is_dir():
                out.update(_extract_k_numbers(path.name))
    return out


def _scan_worktree_experiment_dirs(root: Path) -> set[int]:
    out: set[int] = set()
    for worktree_base in (root / ".claude" / "worktrees", root / ".codex" / "worktrees"):
        if not worktree_base.exists():
            continue
        try:
            worktrees = list(worktree_base.iterdir())
        except OSError as exc:
            warn(
                "kid_reserve",
                "worktree base scan failed; known K-ids may be undercounted (collision risk)",
                err=str(exc),
                path=str(worktree_base),
            )
            continue
        for wt in worktrees:
            exp_dir = wt / "experiments"
            if not exp_dir.exists():
                continue
            try:
                children = list(exp_dir.iterdir())
            except OSError as exc:
                warn(
                    "kid_reserve",
                    "worktree experiment dir scan failed; known K-ids may be undercounted (collision risk)",
                    err=str(exc),
                    path=str(exp_dir),
                )
                continue
            for path in children:
                if path.is_dir():
                    out.update(_extract_k_numbers(path.name))
    return out


def _scan_next_tasks_k_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
    else:
        tasks = data
    if not isinstance(tasks, list):
        return set()

    keys = ("id", "k_id", "experiment_id", "title", "description", "predecessor")
    out: set[int] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in keys:
            out.update(_extract_k_numbers(task.get(key)))
    return out


def _scan_git_log_k_ids(root: Path, limit: int = 30) -> set[int]:
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--oneline"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return _extract_k_numbers(result.stdout)


def _known_k_numbers(
    *,
    root: Path,
    registry: dict[str, Any],
    next_tasks_path: Path,
    git_log_limit: int,
) -> set[int]:
    nums: set[int] = set()
    nums.update(_registry_k_numbers(registry))
    nums.update(_scan_experiment_dirs(root))
    nums.update(_scan_worktree_experiment_dirs(root))
    nums.update(_scan_next_tasks_k_ids(next_tasks_path))
    nums.update(_scan_git_log_k_ids(root, git_log_limit))
    return {n for n in nums if n > 0}


def reserve_k_id(
    *,
    claimed_by: str,
    topic: str | None = None,
    root: Path = ROOT,
    registry_path: Path = REGISTRY_PATH,
    next_tasks_path: Path | None = None,
    lock_path: Path | None = None,
    git_log_limit: int = 30,
    minimum: int = 1,
) -> dict[str, Any]:
    """Reserve and persist the next available K-id under an exclusive lock."""
    if not claimed_by.strip():
        raise ValueError("claimed_by is required")
    if minimum < 1:
        raise ValueError("minimum must be >= 1")
    root = Path(root)
    registry_path = Path(registry_path)
    next_tasks_path = Path(next_tasks_path) if next_tasks_path is not None else root / "storage" / "next_tasks.json"
    lock_path = Path(lock_path) if lock_path is not None else _default_lock_path(registry_path)

    with _exclusive_lock(lock_path):
        registry = _load_registry(registry_path)
        known = _known_k_numbers(
            root=root,
            registry=registry,
            next_tasks_path=next_tasks_path,
            git_log_limit=git_log_limit,
        )
        source_max = max(max(known) if known else 0, minimum - 1)
        number = source_max + 1
        record = {
            "k_id": f"K{number}",
            "number": number,
            "claimed_by": claimed_by,
            "claimed_at": _now_iso(),
            "status": "reserved",
            "topic": topic or "",
            "topic_hash": _topic_hash(topic),
            "source_max": source_max,
        }
        reservations = registry.setdefault("reservations", [])
        reservations.append(record)
        registry["last_k_id"] = max(number, int(registry.get("last_k_id") or 0))
        registry["updated_at"] = record["claimed_at"]
        _atomic_write_json(registry_path, registry)
        return record


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    reserve = sub.add_parser("reserve", help="atomically reserve the next K-id")
    reserve.add_argument("--owner", "--claimed-by", dest="claimed_by", required=True)
    reserve.add_argument("--topic", default="")
    reserve.add_argument("--root", type=Path, default=ROOT)
    reserve.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    reserve.add_argument("--next-tasks", type=Path, default=None)
    reserve.add_argument("--lock", type=Path, default=None)
    reserve.add_argument("--git-log-limit", type=int, default=30)
    reserve.add_argument("--minimum", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "reserve":
            record = reserve_k_id(
                claimed_by=args.claimed_by,
                topic=args.topic,
                root=args.root,
                registry_path=args.registry,
                next_tasks_path=args.next_tasks,
                lock_path=args.lock,
                git_log_limit=args.git_log_limit,
                minimum=args.minimum,
            )
            print(json.dumps({"ok": True, **record}, ensure_ascii=False, sort_keys=True))
            return 0
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
