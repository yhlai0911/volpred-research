"""In-place correction of an already-published feed article.

Single owner for the "fix a published article's body and/or metadata without
publishing a second article" flow. Corrections must not be applied by hand-
editing feed.json or PATCHing Supabase: both skip the errata trail, the write
lock, and the projection sync, and both leave feed.json and Supabase drifting
apart (`.claude/rules/publishing.md`).

The design point is that a correction FAILS LOUDLY when it does not apply.
Every content replacement must match exactly once. A correction that silently
matched nothing is the same failure mode as the wrong-event-date bug this
module was written to clean up: nothing raises, nothing is NaN, and the
article keeps serving the wrong number.

Origin: 2026-07-19, correcting `mile_35eef830` after the K1442 event-date
audit found its NFP metadata pinned to a release date that never happened
(experiments/k1442/related_event_date_audit.md).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from volpred.canonical_write import guard_canonical_write


class CorrectionNotApplied(RuntimeError):
    """A requested replacement did not match its target exactly once."""


def apply_article_correction(
    article_id: str,
    *,
    content_replacements: list[tuple[str, str]] | None = None,
    details_patch: dict | None = None,
    summary: str,
    action: str = "content_correction",
    storage_dir: str | Path = "storage",
    sync: bool = True,
) -> dict:
    """Correct `article_id` in place and stamp an errata record.

    content_replacements: [(old, new)] exact substrings. Each `old` must occur
        exactly once in the article body, otherwise nothing is written and
        CorrectionNotApplied is raised. Pass a long enough substring to be
        unique -- that requirement is the safety property, not an annoyance.
    details_patch: shallow merge into `details`. A None value deletes the key.
    summary: human-readable reason, recorded in the errata trail.

    `published_at` is deliberately left alone: this is a correction to an
    existing article, not a republication, so it must not jump the feed order.
    Returns a report dict; raises KeyError if the article does not exist.
    """
    from volpred.ops.shared_lock import shared_state_lock

    storage = Path(storage_dir)
    feed_path = storage / "reports" / "feed.json"
    replacements = list(content_replacements or [])

    with shared_state_lock("publisher_feed", storage_dir=str(storage)):
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        art = next(
            (x for x in feed if isinstance(x, dict) and x.get("id") == article_id),
            None,
        )
        if art is None:
            raise KeyError(f"{article_id} not found in {feed_path}")

        content = art.get("content") or ""
        applied: list[dict] = []

        # Validate every replacement BEFORE mutating anything, so a bad batch
        # cannot leave the article half-corrected.
        for old, new in replacements:
            hits = content.count(old)
            if hits != 1:
                raise CorrectionNotApplied(
                    f"{article_id}: {old!r} matched {hits} times, expected exactly 1. "
                    "Nothing was written. Widen the substring until it is unique."
                )
        for old, new in replacements:
            content = content.replace(old, new, 1)
            applied.append({"from": old, "to": new})

        details_changes: dict = {}
        if details_patch:
            details = art.get("details")
            if not isinstance(details, dict):
                details = {}
            for key, value in details_patch.items():
                before = details.get(key)
                if value is None:
                    details.pop(key, None)
                else:
                    details[key] = value
                if before != value:
                    details_changes[key] = {"from": before, "to": value}
            art["details"] = details

        if not applied and not details_changes:
            raise CorrectionNotApplied(
                f"{article_id}: correction was a no-op (body and details already "
                "match the requested state). Refusing to stamp an empty errata."
            )

        if applied:
            art["content"] = content

        now_iso = datetime.now(timezone.utc).isoformat()
        art["last_updated_at"] = now_iso
        errata = art.get("errata") if isinstance(art.get("errata"), dict) else {}
        errata["update_at"] = now_iso
        errata["update_action"] = action
        errata["update_summary"] = summary
        hist = (
            errata.get("update_history")
            if isinstance(errata.get("update_history"), list)
            else []
        )
        hist.append(
            {
                "at": now_iso,
                "action": action,
                "summary": summary,
                "content_replacements": applied,
                "details_changes": details_changes,
            }
        )
        errata["update_history"] = hist
        art["errata"] = errata

        guard_canonical_write(feed_path)
        feed_path.write_text(
            json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    synced: bool | None = None
    if sync:
        from scripts.supabase_sync import sync_article

        # Deliberately not wrapped in try/except: an unsynced correction means
        # the live page still serves the wrong number, which is precisely the
        # state this module exists to end. Callers must see the failure.
        synced = bool(sync_article(art, storage_dir=str(storage)))

    return {
        "article_id": article_id,
        "content_replacements": applied,
        "details_changes": details_changes,
        "status": art.get("status"),
        "last_updated_at": art["last_updated_at"],
        "synced": synced,
    }
