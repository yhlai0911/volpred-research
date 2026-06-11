"""Indicator Arena one-way sync: local storage -> Supabase projection."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .registry import load_registry


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "storage"
UpsertFn = Callable[[str, list[dict[str, Any]]], bool]


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _iter_jsonl_rows(dir_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not dir_path.exists():
        return rows
    for path in sorted(dir_path.glob("*.jsonl")):
        rows.extend(_load_jsonl_rows(path))
    return rows


def build_registry_rows(storage_dir: str | Path = DEFAULT_STORAGE_DIR) -> list[dict[str, Any]]:
    storage_path = Path(storage_dir)
    registry_path = storage_path / "indicator_arena" / "registry.json"
    return [asdict(spec) for spec in load_registry(registry_path)]


def build_signal_rows(storage_dir: str | Path = DEFAULT_STORAGE_DIR) -> list[dict[str, Any]]:
    storage_path = Path(storage_dir)
    rows = _iter_jsonl_rows(storage_path / "indicator_arena" / "signals")
    out: list[dict[str, Any]] = []
    for row in rows:
        expires_at = row.get("expires_at")
        published_at = row.get("published_at") or row.get("emitted_at")
        resolve_after = row.get("resolve_after") or expires_at
        target_date = row.get("target_date")
        if target_date is None and isinstance(expires_at, str) and len(expires_at) >= 10:
            target_date = expires_at[:10]
        out.append(
            {
                "signal_id": row["signal_id"],
                "indicator_id": row["indicator_id"],
                "published_at": published_at,
                "target_date": target_date,
                "resolve_after": resolve_after,
                "indicator_value": row.get("indicator_value"),
                "prediction": row.get("prediction", {}),
                "inputs_snapshot": row.get("inputs_snapshot", {}),
                "code_version": row.get("code_version"),
                "as_of_ts": row.get("as_of_ts"),
                "emitted_at": row.get("emitted_at"),
                "expires_at": expires_at,
                "data_hash": row.get("data_hash"),
                "late": bool(row.get("late", False)),
            }
        )
    return out


def build_review_rows(storage_dir: str | Path = DEFAULT_STORAGE_DIR) -> list[dict[str, Any]]:
    storage_path = Path(storage_dir)
    rows = _iter_jsonl_rows(storage_path / "indicator_arena" / "reviews")
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "review_id": row["review_id"],
                "signal_id": row["signal_id"],
                "indicator_id": row.get("indicator_id"),
                "reviewed_at": row["reviewed_at"],
                "realized": row.get("realized", {}),
                "hit": row.get("hit"),
                "econ_value_bps": row.get("econ_value_bps"),
                "data_source_asof": row.get("data_source_asof"),
                "correction_of": row.get("correction_of"),
                "league": row.get("league"),
            }
        )
    return out


def _default_upsert(table: str, rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return True
    from scripts.supabase_sync import _post

    return _post(table, rows)


def sync_indicator_arena(
    storage_dir: str | Path = DEFAULT_STORAGE_DIR,
    *,
    dry_run: bool = False,
    upsert_fn: UpsertFn | None = None,
) -> dict[str, Any]:
    registry_rows = build_registry_rows(storage_dir)
    signal_rows = build_signal_rows(storage_dir)
    review_rows = build_review_rows(storage_dir)

    summary = {
        "indicator_registry": len(registry_rows),
        "daily_signals": len(signal_rows),
        "outcome_reviews": len(review_rows),
        "dry_run": dry_run,
        "ok": True,
    }
    if dry_run:
        return {
            **summary,
            "preview": {
                "indicator_registry": registry_rows[:2],
                "daily_signals": signal_rows[:2],
                "outcome_reviews": review_rows[:2],
            },
        }

    writer = upsert_fn or _default_upsert
    ok_registry = writer("indicator_registry", registry_rows)
    ok_signals = writer("daily_signals", signal_rows)
    ok_reviews = writer("outcome_reviews", review_rows)
    summary["ok"] = bool(ok_registry and ok_signals and ok_reviews)
    summary["table_ok"] = {
        "indicator_registry": bool(ok_registry),
        "daily_signals": bool(ok_signals),
        "outcome_reviews": bool(ok_reviews),
    }
    return summary
