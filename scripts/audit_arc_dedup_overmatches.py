#!/usr/bin/env python3
"""Audit recent arc-dedup skips for likely narrative-axis over-matches.

This is a read-only helper for the 2026-06-24 arc_dedup v3 incident. It scans
drafts that release_pool skipped as arc duplicates and reports cases where the
candidate and the blocker have different known narrative axes. Those are
dup-waiver / rewrite candidates for an interactive session to review.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import arc_signature  # noqa: E402


def _article_text(item: dict) -> str:
    return str(item.get("content") or item.get("description") or "")


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        from dateutil.parser import parse as dtparse

        parsed = dtparse(str(raw))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _signature(item: dict) -> dict:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    stored = details.get("arc_signature") if isinstance(details, dict) else None
    if isinstance(stored, dict) and stored.get("schema_version") == "arc_dedup_v3":
        return stored
    return arc_signature(str(item.get("title") or ""), _article_text(item))


def find_overmatches(
    feed: Iterable[dict],
    *,
    days: int = 30,
    now: datetime | None = None,
) -> list[dict]:
    items = [item for item in feed if isinstance(item, dict)]
    by_id = {str(item.get("id") or ""): item for item in items}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    candidates: list[dict] = []

    for item in items:
        details = item.get("details")
        if not isinstance(details, dict):
            continue
        blocker_id = str(details.get("release_arc_dedup_of") or "")
        skipped_at = _parse_dt(details.get("release_dedup_skipped_at"))
        if not blocker_id or not skipped_at or skipped_at < cutoff:
            continue
        blocker = by_id.get(blocker_id)
        if not blocker:
            continue

        cand_sig = _signature(item)
        block_sig = _signature(blocker)
        cand_axis = str(cand_sig.get("narrative_axis") or "unspecified")
        block_axis = str(block_sig.get("narrative_axis") or "unspecified")
        if "unspecified" in {cand_axis, block_axis} or cand_axis == block_axis:
            continue

        cand_entities = set(cand_sig.get("entities") or [])
        block_entities = set(block_sig.get("entities") or [])
        candidates.append(
            {
                "candidate_id": item.get("id"),
                "candidate_title": item.get("title"),
                "blocked_by_id": blocker.get("id"),
                "blocked_by_title": blocker.get("title"),
                "release_dedup_skipped_at": skipped_at.isoformat(),
                "candidate_narrative_axis": cand_axis,
                "blocked_by_narrative_axis": block_axis,
                "shared_entities": sorted(cand_entities & block_entities),
                "candidate_entities": sorted(cand_entities),
                "blocked_by_entities": sorted(block_entities),
                "candidate_mechanisms": cand_sig.get("mechanisms") or [],
                "blocked_by_mechanisms": block_sig.get("mechanisms") or [],
                "recommendation": "review_dup_waiver_or_fresh_arc_rewrite",
            }
        )
    return candidates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", type=Path, default=FEED_PATH)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        raise SystemExit(f"{args.feed} is not a list")
    candidates = find_overmatches(feed, days=args.days)
    payload = {
        "schema_version": "arc_dedup_overmatch_audit_v1",
        "days": args.days,
        "count": len(candidates),
        "candidates": candidates[: args.limit],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
