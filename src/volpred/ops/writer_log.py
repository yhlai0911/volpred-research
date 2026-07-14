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
import sys
from datetime import datetime, timezone
from pathlib import Path

from volpred.canonical_write import guard_canonical_write

from .common import project_path


def _writer_log_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "ops", "writer_log.jsonl")


def _warn_append_failure(
    exc: Exception,
    *,
    subsystem: str,
    target: str,
    record_id: str | None,
) -> None:
    try:
        print(
            "[writer_log] WARN append failed: "
            f"subsystem={subsystem!r} target={target!r} "
            f"record_id={record_id!r} error={type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    except Exception:
        return  # silent-ok: warn 輸出自身失敗（stderr 不可用），不可遞迴 warn


def append_writer_log(
    subsystem: str,
    target: str,
    record_id: str | None = None,
    *,
    result: str = "ok",
    actor: str | None = None,
    storage_dir: str = "storage",
) -> None:
    """Append a provenance entry; canonical-write enforcement remains fail-closed."""
    try:
        path = _writer_log_path(storage_dir)
    except Exception as exc:
        _warn_append_failure(
            exc, subsystem=subsystem, target=target, record_id=record_id,
        )
        return
    guard_canonical_write(path)
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor or os.environ.get("VOLPRED_ACTOR", "unknown"),
            "subsystem": subsystem,
            "target": target,
            "record_id": record_id,
            "result": result,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        # Writer log is best-effort; must never break the caller.
        _warn_append_failure(
            exc, subsystem=subsystem, target=target, record_id=record_id,
        )
