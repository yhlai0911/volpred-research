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
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from volpred.canonical_write import guard_canonical_write


class CorrectionNotApplied(RuntimeError):
    """A requested replacement did not match its target exactly once."""


class CorrectionNotSynced(RuntimeError):
    """feed.json was corrected but the Supabase projection was not updated."""


def _splice(content: str, replacements: list[tuple[str, str]]) -> list[dict]:
    """Locate every replacement in `content` and return non-overlapping spans.

    Matches are located in the ORIGINAL content only, so replacements cannot
    chain: given [("A","B"), ("B","C")] on "A B", a naive sequential
    `str.replace` yields "C B" because the second pattern eats the first
    pattern's output. Here both spans are resolved against the original and
    applied simultaneously, so the result is "B C".

    Raises CorrectionNotApplied unless every `old` matches exactly once and no
    two matches overlap.
    """
    spans: list[dict] = []
    for old, new in replacements:
        if not old:
            raise CorrectionNotApplied("empty search string")
        hits = [m.start() for m in re.finditer(re.escape(old), content)]
        if len(hits) != 1:
            raise CorrectionNotApplied(
                f"{old!r} matched {len(hits)} times, expected exactly 1. "
                "Nothing was written. Widen the substring until it is unique."
            )
        spans.append({"start": hits[0], "end": hits[0] + len(old),
                      "from": old, "to": new})

    spans.sort(key=lambda s: s["start"])
    for a, b in zip(spans, spans[1:]):
        if b["start"] < a["end"]:
            raise CorrectionNotApplied(
                f"replacements overlap in the source text: {a['from']!r} and "
                f"{b['from']!r}. Nothing was written."
            )
    return spans


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

        # Resolve all spans against the ORIGINAL content, then apply them in a
        # single pass. Validation happens before any mutation, so a bad batch
        # cannot leave the article half-corrected.
        try:
            spans = _splice(content, replacements)
        except CorrectionNotApplied as exc:
            raise CorrectionNotApplied(f"{article_id}: {exc}") from None

        applied = [{"from": s["from"], "to": s["to"]} for s in spans]
        if spans:
            out: list[str] = []
            pos = 0
            for s in spans:
                out.append(content[pos:s["start"]])
                out.append(s["to"])
                pos = s["end"]
            out.append(content[pos:])
            content = "".join(out)

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
        # Atomic: feed.json is ~15MB of canonical state. A truncated in-place
        # write (disk full, I/O error, kill) would destroy every article, and
        # the lock does not protect against that -- it only serialises writers.
        payload = json.dumps(feed, ensure_ascii=False, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            dir=str(feed_path.parent), prefix=".feed_correction_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, feed_path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

        # Sync inside the lock. Outside it, a concurrent writer could land
        # between the write and the sync, and we would upsert this stale
        # snapshot over their change. sync_article does not take this lock,
        # so this cannot deadlock.
        if sync:
            from scripts.supabase_sync import sync_article

            # sync_article signals failure by RETURNING FALSE, not by raising
            # (HTTP error, missing Supabase key). Returning that quietly would
            # leave feed.json corrected and the live page still serving the
            # wrong number -- exactly the silent-failure class this module
            # exists to end. Convert it into a loud error.
            synced = bool(sync_article(art, storage_dir=str(storage)))
            if not synced:
                raise CorrectionNotSynced(
                    f"{article_id}: feed.json was corrected but sync_article "
                    "returned False, so the live page still serves the old "
                    "content. Re-run the sync; do not treat this as success."
                )
        else:
            synced = None

    return {
        "article_id": article_id,
        "content_replacements": applied,
        "details_changes": details_changes,
        "status": art.get("status"),
        "last_updated_at": art["last_updated_at"],
        "synced": synced,
    }
