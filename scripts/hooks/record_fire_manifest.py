#!/usr/bin/env python3
"""Legacy PostToolUse observer for Edit/Write/NotebookEdit fire attribution.

The hook is deliberately fail-open. A missed declaration costs one shadow data
point; blocking the producer would cost the whole hourly fire. It is not the
canonical ownership gate: Issue #43 uses isolated workspace settlement for every
mutating producer, and Issue #44 forbids reviving manifest-driven Stage 3.
Daily checkup separately verifies that this diagnostic hook remains installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from volpred.ops import fire_manifest  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):  # silent-ok: shadow attribution must never block the producer
        return None
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 and proc.stdout.strip() else None


def record_payload(payload: dict, *, env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    fire_id = env.get("VOLPRED_FIRE_ID", "").strip()
    if not fire_id or payload.get("tool_name") not in EDIT_TOOLS:
        return False
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return False
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    root = _git_root(path)
    if root is None:
        fallback = env.get("VOLPRED_FIRE_REPO_ROOT", "").strip()
        root = Path(fallback).resolve() if fallback else None
    if root is None:
        return False
    op = fire_manifest.OP_WRITE if path.exists() else fire_manifest.OP_DELETE
    fire_manifest.record(root, fire_id, str(path), op=op, tool=str(payload.get("tool_name") or ""))
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        record_payload(payload)
    except Exception as exc:  # noqa: BLE001 — declaration is shadow-only
        print(f"[record_fire_manifest] declaration skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
