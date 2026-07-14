"""Pre-publish throttle gate for rhythm-controlled (discretionary reader-facing) articles.

Root cause (2026-06-30 boss email-12281): the publish_rhythm:burst alert kept
re-firing because content_quality.py was only a post-hoc patrol detector —
detection without prevention. Two reader-facing articles published 2.73 min
apart inside the same script run (mile_44ab1acc / mile_f5f4cb43) tripped the
30-min burst threshold; that day's fix relaxed the patrol's classification
(exempt digest + trending fixtures), but the source of legitimate-burst risk
remained: nothing actually stopped two *discretionary* publishes from clumping.

This module is the prevention half: a canonical-write-site gate inside
`Publisher._append_to_feed`. A publish whose `is_rhythm_controlled(item)` is
True and whose gap to the most recent rhythm-controlled feed entry is below
RHYTHM_BURST_GAP_MIN is rejected with PublishThrottleError — caller defers,
reschedules, or drops the work item. Fixtures (`digest` / `daily_update` /
`daily_recommendation`) and event-driven publishes (`trending_repost` /
`event_article`) bypass through the shared cadence policy in
`volpred.ops.release_cadence`.

Audit: every gate decision (pass / block) writes a record to
`storage/logs/dedup_decisions.jsonl` per `.claude/rules/dedup-gate-audit.md`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.ops.release_cadence import (
    NON_RHYTHM_CATEGORIES as _NON_RHYTHM_CATEGORIES,
    NON_RHYTHM_PHASES as _NON_RHYTHM_PHASES,
    RHYTHM_BURST_GAP_MIN,
    is_rhythm_controlled,
    sibling_group as _sibling_group,
)


class PublishThrottleError(Exception):
    """Raised when publishing `item` would create a rhythm burst (< RHYTHM_BURST_GAP_MIN)."""

    def __init__(
        self,
        message: str,
        *,
        previous_id: str | None,
        gap_minutes: float,
        threshold_minutes: float,
    ) -> None:
        super().__init__(message)
        self.previous_id = previous_id
        self.gap_minutes = gap_minutes
        self.threshold_minutes = threshold_minutes


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        try:
            from volpred.ops.diagnostics import warn

            warn(
                "publish_throttle_ts",
                "fromisoformat failed",
                raw=str(raw)[:60],
                err=str(exc),
            )
        except ImportError:
            pass  # silent-ok: diagnostics optional in early import contexts
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def find_most_recent_rhythm_published(
    feed: list[dict[str, Any]], *, exclude_id: str | None = None
) -> tuple[dict[str, Any], datetime] | None:
    """Newest published, rhythm-controlled feed entry (excluding `exclude_id`)."""
    candidates: list[tuple[dict[str, Any], datetime]] = []
    for entry in feed:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "published":
            continue
        if exclude_id is not None and entry.get("id") == exclude_id:
            continue
        if not is_rhythm_controlled(entry):
            continue
        ts = _parse_ts(entry.get("published_at") or entry.get("created_at"))
        if ts is None:
            continue
        candidates.append((entry, ts))
    if not candidates:
        return None
    candidates.sort(key=lambda kv: kv[1], reverse=True)
    return candidates[0]


def _log_throttle_decision(
    storage_dir: str | Path,
    *,
    decision: str,
    target_id: str | None,
    previous_id: str | None,
    gap_minutes: float | None,
    reason: str,
) -> None:
    """Append throttle decision to storage/logs/dedup_decisions.jsonl.

    Per `.claude/rules/dedup-gate-audit.md`: every gate decision (pass / block /
    warn) must leave an audit trail so a non-publish is never silent.
    Fail-safe — logging never breaks a publish.
    """
    from volpred.canonical_write import guard_canonical_write

    path = Path(storage_dir) / "logs" / "dedup_decisions.jsonl"
    guard_canonical_write(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate": "publish_throttle",
            "decision": decision,
            "target_id": target_id,
            "previous_id": previous_id,
            "gap_minutes": gap_minutes,
            "reason": reason,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        try:
            from volpred.ops.diagnostics import warn

            warn(
                "publish_throttle_log",
                "audit log write failed",
                err=str(exc),
            )
        except ImportError:
            pass  # silent-ok: diagnostics optional in early import contexts


def check_publish_throttle(
    item: dict[str, Any],
    feed: list[dict[str, Any]],
    *,
    storage_dir: str | Path,
    now: datetime | None = None,
    min_gap_min: float = RHYTHM_BURST_GAP_MIN,
) -> None:
    """Raise PublishThrottleError if publishing `item` violates the rhythm gap.

    Pass-through (no-op + audit `pass`) when:
      * `item` is not being published now (status draft / scheduled / etc.) — a
        draft is not reader-facing at ingestion; release_pool governs its release
        cadence, and *that* flip re-enters this gate as status="published". Only a
        published discretionary article can create a reader-facing burst, and this
        gate only ever compares against published entries. Throttling draft
        ingestion here double-gates and wedges draft-pool refill for up to the
        burst window (2026-07-05: a K1633 general draft was blocked 13min after a
        published article; the writer agent then burned ~700s waiting the window
        out). Missing status defaults to "published" (codebase convention, see
        publisher.py) so real publishes and existing unit tests stay fully gated.
      * item is NOT rhythm-controlled (fixture / event-driven / daily / digest)
      * feed has no recent rhythm-controlled publish to compare against
      * `item` and the previous publish share a `details.paired_sibling_group`
        (legit multi-sibling publish from a single script run, e.g. daily_update)
      * computed gap >= `min_gap_min`

    On block: logs `block` decision and raises PublishThrottleError; caller is
    expected to defer / reschedule the publish (not retry immediately).
    """
    target_id = item.get("id")
    status = str(item.get("status", "published") or "published").strip().lower()
    if status != "published":
        _log_throttle_decision(
            storage_dir,
            decision="pass",
            target_id=target_id,
            previous_id=None,
            gap_minutes=None,
            reason=f"non_published_ingestion:{status}",
        )
        return
    if not is_rhythm_controlled(item):
        _log_throttle_decision(
            storage_dir,
            decision="pass",
            target_id=target_id,
            previous_id=None,
            gap_minutes=None,
            reason="not_rhythm_controlled",
        )
        return
    found = find_most_recent_rhythm_published(feed, exclude_id=target_id)
    if found is None:
        _log_throttle_decision(
            storage_dir,
            decision="pass",
            target_id=target_id,
            previous_id=None,
            gap_minutes=None,
            reason="no_prior_rhythm_publish",
        )
        return
    prev, prev_ts = found
    new_group = _sibling_group(item)
    if new_group and new_group == _sibling_group(prev):
        _log_throttle_decision(
            storage_dir,
            decision="pass",
            target_id=target_id,
            previous_id=prev.get("id"),
            gap_minutes=None,
            reason=f"paired_sibling_group:{new_group}",
        )
        return
    now_ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gap_min = round((now_ts - prev_ts).total_seconds() / 60.0, 2)
    if gap_min >= min_gap_min:
        _log_throttle_decision(
            storage_dir,
            decision="pass",
            target_id=target_id,
            previous_id=prev.get("id"),
            gap_minutes=gap_min,
            reason="gap_above_threshold",
        )
        return
    _log_throttle_decision(
        storage_dir,
        decision="block",
        target_id=target_id,
        previous_id=prev.get("id"),
        gap_minutes=gap_min,
        reason=f"burst_gap_{gap_min}min_lt_{min_gap_min}min",
    )
    raise PublishThrottleError(
        f"publish_throttle: would create burst — gap={gap_min}min < "
        f"threshold={min_gap_min}min (new={target_id}, previous={prev.get('id')})",
        previous_id=prev.get("id"),
        gap_minutes=gap_min,
        threshold_minutes=min_gap_min,
    )
