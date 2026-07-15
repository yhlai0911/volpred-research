#!/usr/bin/env python3
"""Fail-closed invariant for feed audience metadata.

For every visible entry declared ``audience='general'``, replay the canonical
publisher inference with the stored title, body, tags, and content type.  The
validator intentionally imports the publisher implementation instead of
copying its keyword table: type locks (daily bulletin / daily digest / member QA /
event), image URL normalization, title rules, and tags must make the same
decision at publish time and in CI.

Exit codes:
  0 -- feed is readable and no declared-general entry disagrees with publisher
  1 -- metadata mismatch or feed read/shape error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from volpred.publisher.publisher import _academic_keyword_hits, _infer_audience


_NON_VISIBLE_STATUSES = frozenset({"unpublished", "archived", "retracted"})


def _stored_content_type(entry: dict[str, Any]) -> str | None:
    """Mirror ``Publisher.publish_milestone`` content-type resolution."""
    details = entry.get("details")
    details_type = details.get("content_type") if isinstance(details, dict) else None
    value = details_type or entry.get("content_type") or entry.get("category")
    normalized = str(value or "").strip()
    return normalized or None


def infer_entry_audience(entry: dict[str, Any]) -> str:
    """Replay publisher audience inference for a stored feed row."""
    content = entry.get("content") or entry.get("description") or ""
    tags = entry.get("tags")
    if not isinstance(tags, list):
        tags = []
    return _infer_audience(
        str(entry.get("title") or ""),
        str(content),
        [str(tag) for tag in tags if tag is not None],
        content_type=_stored_content_type(entry),
    )


def check_entry(entry: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return ``(is_mismatch, academic_signals)`` for one stored feed row.

    This invariant is scoped to rows declared ``general`` because inference is
    an upcast/type-lock gate, not a downcast engine for explicitly research
    content.  A type-locked general row whose publisher result is ``member_qa``
    or ``event`` is also a mismatch and must be corrected to that type.
    """
    if entry.get("audience") != "general":
        return False, []
    if str(entry.get("status") or "").lower() in _NON_VISIBLE_STATUSES:
        return False, []

    inferred = infer_entry_audience(entry)
    if inferred == "general":
        return False, []

    content = entry.get("content") or entry.get("description") or ""
    tags = entry.get("tags")
    if not isinstance(tags, list):
        tags = []
    labels = _academic_keyword_hits(
        str(entry.get("title") or ""),
        str(content),
        [str(tag) for tag in tags if tag is not None],
    )
    return True, labels


def main(feed_path: str | None = None) -> int:
    """Scan a feed and return a process-style status code."""
    if feed_path is None:
        project_root = Path(__file__).resolve().parent.parent
        feed_path = str(project_root / "storage" / "reports" / "feed.json")

    path = Path(feed_path)
    if not path.exists():
        print(f"[validate_feed_audience] ERROR -- feed.json not found at {path}")
        return 1

    try:
        feed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            "[validate_feed_audience] ERROR reading feed.json: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    if not isinstance(feed, list):
        print(
            "[validate_feed_audience] ERROR -- feed.json top level must be a list, "
            f"got {type(feed).__name__}"
        )
        return 1

    mismatches: list[dict[str, Any]] = []
    for entry in feed:
        if not isinstance(entry, dict):
            print("[validate_feed_audience] ERROR -- feed contains a non-object row")
            return 1
        is_mismatch, labels = check_entry(entry)
        if is_mismatch:
            mismatches.append(
                {
                    "id": entry.get("id", "?"),
                    "title": str(entry.get("title") or "")[:80],
                    "declared_audience": entry.get("audience"),
                    "inferred_audience": infer_entry_audience(entry),
                    "status": entry.get("status"),
                    "academic_signals": labels,
                }
            )

    if mismatches:
        print(
            f"[validate_feed_audience] FAIL -- {len(mismatches)} "
            "publisher-inference mismatch(es) found:\n"
        )
        for mismatch in mismatches:
            print(f"  id={mismatch['id']}")
            print(f"    title   : {mismatch['title']}")
            print(
                "    audience: "
                f"{mismatch['declared_audience']} -> {mismatch['inferred_audience']}"
            )
            print(f"    status  : {mismatch['status']}")
            print(f"    signals : {mismatch['academic_signals']}\n")
        print(f"Total mismatches: {len(mismatches)}")
        print("Fix through the guarded audience-correction workflow; do not hand-edit feed.json.")
        return 1

    general_count = sum(1 for entry in feed if entry.get("audience") == "general")
    print(
        f"[validate_feed_audience] PASS -- {len(feed)} total entries, "
        f"{general_count} declared general, 0 mismatches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
