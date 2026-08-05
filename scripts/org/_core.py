"""Shared primitives for the disk-persisted org layer (storage/org).

Design contract (docs/agents/ownership.md Zone D):
- The org's entire state (registry, charters, memories, inboxes, journals)
  lives in git-tracked files so that session restart / reboot / host
  migration recovers the whole organization from a checkout.
- Ephemeral receipts live in receipts/ (gitignored, rotated).
- Everything here is stdlib-only and side-effect free except explicit writes.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORG_ROOT = REPO_ROOT / "storage" / "org"

DEPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

# Paths no department may claim: Zone A (Codex-owned) and core Zone B
# (main-thread-owned) prefixes from docs/agents/ownership.md.
RESERVED_PATH_PREFIXES = (
    "src/volpred/ops/",
    "supabase/migrations/",
    "scripts/dispatch_supervisor/",
    "paper/",
    ".claude/skills/",
    "storage/org/registry.json",
    "storage/org/manager/",
)

REGISTRY_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def registry_path(root: Path) -> Path:
    return root / "registry.json"


def load_registry(root: Path) -> dict:
    path = registry_path(root)
    if not path.exists():
        raise FileNotFoundError(
            f"org registry not found at {path}; run `org_admin.py init` first"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_registry(root: Path, registry: dict) -> None:
    registry["updated_at"] = now_iso()
    atomic_write_json(registry_path(root), registry)


def bulletin_append(root: Path, actor: str, text: str) -> Path:
    """Append one decision record to the current month's bulletin (Zone C rules)."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    path = root / "bulletin" / f"{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {now_iso()} **{actor}**: {text}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return path


def write_receipt(root: Path, kind: str, payload: dict) -> Path:
    """Ephemeral spawn/skip receipt (gitignored)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / "receipts" / f"{stamp}_{kind}.json"
    payload = dict(payload)
    payload.setdefault("kind", kind)
    payload.setdefault("at", now_iso())
    atomic_write_json(path, payload)
    return path


def dept_dir(root: Path, name: str) -> Path:
    return root / "departments" / name


def validate_dept_name(name: str) -> None:
    if not DEPT_NAME_RE.match(name):
        raise ValueError(
            f"invalid department name {name!r}: must match {DEPT_NAME_RE.pattern}"
        )


def check_path_conflicts(registry: dict, new_paths: list[str], *, exclude: str | None = None) -> list[str]:
    """Return human-readable conflict descriptions (empty = OK)."""
    conflicts: list[str] = []
    for p in new_paths:
        for prefix in RESERVED_PATH_PREFIXES:
            if p.startswith(prefix) or prefix.startswith(p):
                conflicts.append(f"{p!r} overlaps reserved zone {prefix!r}")
    for dept, meta in registry.get("departments", {}).items():
        if dept == exclude or meta.get("status") == "retired":
            continue
        for existing in meta.get("owned_paths", []):
            for p in new_paths:
                if p.startswith(existing) or existing.startswith(p):
                    conflicts.append(f"{p!r} overlaps {existing!r} owned by {dept}")
    return conflicts
