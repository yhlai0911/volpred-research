"""Append-only writer provenance log.

Every mutation of shared JSON state (memory/*.json, reports/feed.json, ops
control plane) should emit one JSONL line to `storage/ops/writer_log.jsonl`.

This lets post-mortem analysis trace corruption (e.g. knowledge.json stray `]}`
bug, 2026-04-17) back to who wrote it and when.

Fields:
    ts          : ISO 8601 UTC
    actor       : os.environ["VOLPRED_ACTOR"] (claude | codex | system | unknown)
    subsystem   : memory | publisher | experiments | control_plane
    target      : relative file path written
    record_id   : optional identifier for the record touched
    result      : "ok" | "error: ..."
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .common import project_path


def _writer_log_path(storage_dir: str = "storage") -> Path:
    path = project_path(storage_dir, "ops", "writer_log.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_writer_log(
    subsystem: str,
    target: str,
    record_id: str | None = None,
    *,
    result: str = "ok",
    actor: str | None = None,
    storage_dir: str = "storage",
) -> None:
    """Append a single JSONL provenance entry. Never raises."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor or os.environ.get("VOLPRED_ACTOR", "unknown"),
            "subsystem": subsystem,
            "target": target,
            "record_id": record_id,
            "result": result,
        }
        path = _writer_log_path(storage_dir)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Writer log is best-effort; must never break the caller.
        pass
