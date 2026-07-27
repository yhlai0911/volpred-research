#!/usr/bin/env python3
"""Sweep storage/next_tasks.json: pending `*_article_<audience>` tasks whose
K-id ALREADY has a feed article for that audience → mark blocked
(reason="deprecated"), so the dispatcher never offers them and no duplicate
article gets written.

Why (2026-07-01 root cause):
    refill_task_pool's `_kids_with_audience_article` guard prevents *creating*
    a duplicate article task, but only at creation time. A task can be queued
    when the K is genuinely uncovered, and the covering article gets written
    minutes later by another path (Codex daemon, parallel refill/publish). The
    already-queued task is never retracted, so continue_task_dispatch keeps
    listing it as an agentable candidate → duplicate-article dispatch.

    Concrete incident: `K1590_article_general` created 2026-07-01T11:23:07Z,
    article `mile_4518e9d8` (audience=general, refs=['K1590']) written
    2026-07-01T11:30:21Z (7 min later). The task stayed pending and was still
    offered by the dispatcher at 20:08. This is a recurring class (K1449/K1091
    dup incidents).

The coverage authority is refill_task_pool._kids_with_audience_article — the
SAME function refill uses to decide "already covered". Reusing it (rather than
reimplementing) is deliberate: the original bug was drift between two coverage
detectors, so this sweep must never introduce a third.

Usage:
    uv run python scripts/mark_covered_article_tasks.py            # dry-run
    uv run python scripts/mark_covered_article_tasks.py --apply    # write

Also importable: `sweep(apply=True) -> dict` is called by
continue_task_dispatch.build_report so every dispatch self-heals.
"""
from __future__ import annotations

import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from volpred.ops.diagnostics import warn as _diag_warn  # noqa: E402

# Reuse canonical block-writer plumbing so this sweep and mark_task_blocked.py
# share identical serialization + the single flock-based control plane. The old
# shared_state_lock("control_plane") did NOT coordinate with the flock the
# canonical writer holds on next_tasks.json, so we go through the same handle.
from mark_task_blocked import NEXT_TASKS, _decode_tasks  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import write_tasks_to_handle  # noqa: E402
# Coverage authority — the exact set refill uses to skip creating dup tasks.
from refill_task_pool import _kids_with_audience_article  # noqa: E402

FEED_PATH = ROOT / "storage" / "reports" / "feed.json"


def _split_article_task_id(task_id: str) -> tuple[str, str] | None:
    """Return (kid_upper, audience) for an `*_article_<audience>` task id, else None.

    Handles suffixed retries like `K1157_article_general_v2` and compound
    K-ids like `K1100g_d9_article_research`.
    """
    if "_article_" not in task_id:
        return None
    left, right = task_id.split("_article_", 1)
    if not left[:2].upper().startswith("K") or not any(c.isdigit() for c in left):
        return None
    right = right.lower()
    if right.startswith("general"):
        audience = "general"
    elif right.startswith("research"):
        audience = "research"
    else:
        return None
    return left.upper(), audience


def _covering_mile_ids(audience: str) -> dict[str, str]:
    """Best-effort kid_upper -> covering article id map, for the audit note only.

    Non-authoritative (coverage decisions use _kids_with_audience_article). If
    the feed can't be read we still block; the note just omits the mile id.
    """
    out: dict[str, str] = {}
    if not FEED_PATH.exists():
        return out
    try:
        feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _diag_warn(
            "mark_covered_article_tasks",
            "feed read failed while resolving covering mile ids",
            err=f"{type(exc).__name__}: {exc}",
        )
        return out
    aud = (audience or "general").lower()
    for art in feed:
        if not isinstance(art, dict):
            continue
        art_aud = art.get("audience")
        if aud == "general":
            if art_aud not in (None, "", "general"):
                continue
        elif art_aud != aud:
            continue
        if art.get("status") not in ("draft", "published", "scheduled", "archived"):
            continue
        details = art.get("details") or {}
        refs = details.get("experiment_refs") if isinstance(details, dict) else []
        if isinstance(refs, list):
            for r in refs:
                out.setdefault(str(r).upper(), str(art.get("id") or ""))
    return out


def find_covered(tasks: list) -> list[dict]:
    """Return descriptors for pending article tasks whose K is already covered."""
    covered = {
        "general": _kids_with_audience_article("general"),
        "research": _kids_with_audience_article("research"),
    }
    mile_maps: dict[str, dict[str, str]] = {}
    hits: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if (t.get("status") or "").lower() != "pending":
            continue
        if (t.get("blocked_reason") or "").strip():
            continue  # already blocked; leave it
        parsed = _split_article_task_id(str(t.get("id") or ""))
        if not parsed:
            continue
        kid, audience = parsed
        if kid not in covered[audience]:
            continue
        if audience not in mile_maps:
            mile_maps[audience] = _covering_mile_ids(audience)
        hits.append(
            {
                "task": t,
                "id": t.get("id"),
                "kid": kid,
                "audience": audience,
                "mile_id": mile_maps[audience].get(kid, ""),
            }
        )
    return hits


def sweep(apply: bool) -> dict:
    """Retire covered pending article tasks as terminal superseded rows. Idempotent."""
    guard_canonical_write(NEXT_TASKS)
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            payload, tasks = _decode_tasks(fh.read())
            hits = find_covered(tasks)
            if apply and hits:
                if isinstance(payload, dict):
                    raise ValueError(
                        "next_tasks.json root must be a list "
                        "(single-gateway 2026-07-16)"
                    )
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for h in hits:
                    t = h["task"]
                    mile = h["mile_id"]
                    note = (
                        f"{h['audience']}-audience article for {h['kid']} already in feed"
                        + (f" ({mile})" if mile else "")
                        + "; auto-retired to prevent duplicate dispatch"
                    )
                    t["status"] = "superseded"
                    t["blocked_reason"] = "deprecated"
                    t["blocked_at"] = now
                    t["blocked_note"] = note
                    t["terminalized_at"] = now
                    t["terminalized_reason"] = "deprecated"
                    t.pop("blocked_until", None)  # deprecated = terminal; no recheck
                    t.setdefault("status_history", []).append(
                        {"at": now, "from": "pending", "to": "superseded", "reason": note}
                    )
                write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return {
        "ok": True,
        "count": len(hits),
        "applied": bool(apply and hits),
        "ids": [h["id"] for h in hits],
        "details": [
            {"id": h["id"], "kid": h["kid"], "audience": h["audience"], "mile_id": h["mile_id"]}
            for h in hits
        ],
    }


def main(apply: bool) -> int:
    result = sweep(apply=apply)
    verb = "retired" if apply else "would retire"
    print(f"[covered-article-dedup] {verb} {result['count']} task(s)")
    for d in result["details"]:
        print(
            f"  - {d['id']} :: {d['kid']} {d['audience']} covered by "
            f"{d['mile_id'] or '(mile id unresolved)'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply=("--apply" in sys.argv)))
