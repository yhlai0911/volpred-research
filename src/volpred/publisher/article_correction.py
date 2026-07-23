"""Prepare a fail-loud correction and send it through the publisher gateway.

Single owner for the "fix a published article's body and/or metadata without
publishing a second article" flow. Corrections must not be applied by hand-
editing feed.json or PATCHing a projection: both skip the errata trail and the
single publisher gateway, leaving feed.json, Mirror, and Supabase drifting
apart (`.claude/rules/publishing.md`). This module owns correction validation
and errata construction only; ``Publisher.rewrite_and_sync_article`` is the
sole owner of canonical mutation and projection delivery.

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

import copy
import re
from datetime import datetime, timezone
from pathlib import Path

from volpred.publisher.publisher import Publisher


class CorrectionNotApplied(RuntimeError):
    """A requested replacement did not match its target exactly once."""


class CorrectionNotSynced(RuntimeError):
    """feed.json was corrected but one or more projections were not updated."""


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
    title_replacement: tuple[str, str] | None = None,
    description_replacement: tuple[str, str] | None = None,
    details_patch: dict | None = None,
    summary: str,
    action: str = "content_correction",
    storage_dir: str | Path = "storage",
) -> dict:
    """Correct `article_id` in place and stamp an errata record.

    content_replacements: [(old, new)] exact substrings. Each `old` must occur
        exactly once in the article body, otherwise nothing is written and
        CorrectionNotApplied is raised. Pass a long enough substring to be
        unique -- that requirement is the safety property, not an annoyance.
    title_replacement: (old, new) exact full-title replacement. The current
        title must equal `old`, otherwise nothing is written.
    description_replacement: (old, new) exact full-description replacement.
        The current card/SEO description must equal `old`, otherwise nothing
        is written.
    details_patch: shallow merge into `details`. A None value deletes the key.
    summary: human-readable reason, recorded in the errata trail.

    `published_at` is deliberately left alone: this is a correction to an
    existing article, not a republication, so it must not jump the feed order.
    Returns a report dict; raises KeyError if the article does not exist.
    """
    storage = Path(storage_dir)
    replacements = list(content_replacements or [])
    publisher = Publisher(storage_dir=str(storage))
    original = publisher.get_report(article_id)
    if original is None:
        raise KeyError(f"{article_id} not found in {publisher._feed_file}")
    art = copy.deepcopy(original)

    content = art.get("content") or ""

    # Resolve all spans against the ORIGINAL content, then apply them in a
    # single pass. Validation happens before any mutation, so a bad batch
    # cannot leave the article half-corrected.
    try:
        spans = _splice(content, replacements)
    except CorrectionNotApplied as exc:
        raise CorrectionNotApplied(f"{article_id}: {exc}") from None

    applied = [{"from": s["from"], "to": s["to"]} for s in spans]
    title_change: dict | None = None
    if title_replacement is not None:
        old_title, new_title = title_replacement
        current_title = str(art.get("title") or "")
        if current_title != old_title:
            raise CorrectionNotApplied(
                f"{article_id}: title did not exactly match {old_title!r}; "
                "nothing was written. Re-read the current article."
            )
        if old_title != new_title:
            title_change = {"from": old_title, "to": new_title}
            art["title"] = new_title

    description_change: dict | None = None
    if description_replacement is not None:
        old_description, new_description = description_replacement
        current_description = str(art.get("description") or "")
        if current_description != old_description:
            raise CorrectionNotApplied(
                f"{article_id}: description did not exactly match "
                f"{old_description!r}; nothing was written. Re-read the "
                "current article."
            )
        if old_description != new_description:
            description_change = {
                "from": old_description,
                "to": new_description,
            }
            art["description"] = new_description

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

    if (
        not applied
        and title_change is None
        and description_change is None
        and not details_changes
    ):
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
            "title_change": title_change,
            "description_change": description_change,
            "details_changes": details_changes,
        }
    )
    errata["update_history"] = hist
    art["errata"] = errata

    gateway = publisher.rewrite_and_sync_article(
        article_id,
        art,
        expected_item=original,
    )
    if not gateway["feed_written"]:
        if gateway.get("conflict"):
            raise CorrectionNotApplied(
                f"{article_id}: article changed concurrently; nothing was "
                "overwritten. Re-read it and prepare the correction again."
            )
        raise KeyError(f"{article_id} disappeared before the correction was written")
    if not gateway["ok"]:
        dead_letters = ", ".join(gateway["dead_letters"]) or "none"
        raise CorrectionNotSynced(
            f"{article_id}: canonical feed was corrected, but projection sync "
            f"failed ({dead_letters}); the gateway queued a retry."
        )

    return {
        "article_id": article_id,
        "content_replacements": applied,
        "title_change": title_change,
        "description_change": description_change,
        "details_changes": details_changes,
        "status": art.get("status"),
        "last_updated_at": art["last_updated_at"],
        "synced": (
            gateway["supabase"] == "ok"
            if gateway["supabase"] != "skipped"
            else None
        ),
        "gateway": gateway,
    }
