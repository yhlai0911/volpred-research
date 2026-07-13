"""Generation-time topic dedup — the gate that runs BEFORE a task is created.

Enforcement owner (anti-stacking): this module is the ONE place that answers
"should we even create a task for this topic?". It is distinct from, and does
not replace:

  * publisher.publish_milestone arc block   -> "should we PUBLISH this article?"
  * scripts/check_arc_dedup.py              -> pre-WRITE CLI for a human/agent

Why it exists (2026-07-13 incident, root-caused 2026-07-14):
    refill_reader_facing_pool produced the trending task
    「AI營收不如預期？科技股選擇權偏斜率（Skew）洩天機」 — the 5th piece on the
    same narrative arc within 90 days. It sat in the pending pool for 20 hours
    until a human grep caught it. The write-step gate was already fixed, but the
    PRODUCTION step had no check at all: `_build_trending_task` and
    `build_pending_event_task` created rows without ever looking at the feed.

Policy differs from the publish gate ON PURPOSE. At publish time a false
positive is a content hole (the article is already written), so fuzzy signals
must fail open. At GENERATION time a false positive costs one swapped topic, so
the trending lane may block on a fuzzy signal. Per `.claude/rules/dedup-gate-audit.md`
this is the sanctioned asymmetry.

Per-lane modes (deliberate, see `screen_topic`):
    mode="block" (trending) — a hit prevents the task from being created.
    mode="warn"  (event)    — a hit ANNOTATES the task but never blocks it.

Why event is warn-only: event articles are a designed T-7 / T-2 / T+0 series
about one event, and every FOMC resembles the last FOMC. Feed event markers are
sparse and inconsistent (5 items carry `details.event_series_slot`; `event_key`
is null), so same-event siblings cannot be reliably excluded from the corpus. A
hard block would therefore kill the NEXT event window because the PREVIOUS one
exists — a content hole on P1 time-sensitive work, which is exactly what the
dedup-gate-audit rule forbids. Warn + annotate gives the writer agent the near
misses without ever silencing an event.

Never silent: every decision (block, warn, pass, and gate error) is appended to
storage/logs/dedup_decisions.jsonl, and blocks/warns are returned to the caller
with an explicit reason, per `.claude/rules/no-silent-fallback.md`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from volpred.ops.diagnostics import warn as _diag_warn
from volpred.publisher.arc_dedup import (
    THEME_SATURATION_THRESHOLD,
    find_arc_duplicates,
    find_k_coverage,
    theme_saturation,
)

DEFAULT_WINDOW_DAYS = 90

# Verdicts
CLEAN = "clean"
BLOCK_K_COVERAGE = "block_k_coverage"
BLOCK_ARC_DUP = "block_arc_dup"
BLOCK_THEME_SATURATED = "block_theme_saturated"
WARN_THEME_SATURATED = "warn_theme_saturated"
WARN_ARC_DUP = "warn_arc_dup"
WARN_K_COVERAGE = "warn_k_coverage"
GATE_ERROR = "gate_error_fail_open"


@dataclass
class TopicScreen:
    """Verdict for one candidate topic. `blocked` is the only thing callers act on."""

    verdict: str
    blocked: bool
    reason: str
    matches: list[dict] = field(default_factory=list)
    theme_terms: list[str] = field(default_factory=list)
    saturation: int = 0

    def as_task_field(self) -> dict[str, Any]:
        """Compact audit blob to embed in the task row so downstream can see it."""
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "saturation": self.saturation,
            "theme_terms": self.theme_terms,
            "near_misses": [
                {"id": m.get("id"), "title": m.get("title")} for m in self.matches[:5]
            ],
            "screened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def log_decision(
    storage_dir: str | os.PathLike[str],
    lane: str,
    task_id: str,
    screen: TopicScreen,
) -> None:
    """Append the decision to the shared dedup audit trail.

    Same JSONL as the publish-time gate (`storage/logs/dedup_decisions.jsonl`) so
    one audit tool sees every dedup decision the platform makes, at any stage.
    """
    try:
        path = os.path.join(str(storage_dir), "logs", "dedup_decisions.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate": "task_generation",
            "lane": lane,
            "action": screen.verdict,
            "blocked": screen.blocked,
            "target_id": task_id,
            "reason": screen.reason,
            "saturation": screen.saturation,
            "theme_terms": screen.theme_terms,
            "matched_ids": [m.get("id") for m in screen.matches[:5]],
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - logging must never break refill
        _diag_warn(
            "topic_dedup",
            "failed to append dedup decision",
            err=f"{type(exc).__name__}: {exc}",
            lane=lane,
            task_id=task_id,
        )


def screen_topic(
    title: str,
    description: str = "",
    *,
    feed: list[dict] | None,
    k_id: str | None = None,
    audience: str | None = None,
    days: int = DEFAULT_WINDOW_DAYS,
    mode: str = "block",
    saturation_threshold: int = THEME_SATURATION_THRESHOLD,
) -> TopicScreen:
    """Judge a candidate topic BEFORE a task row is built.

    Gates run in order of confidence:
      1. K coverage  (exact)  — this K already has a live article for this audience.
      2. Arc dup     (fuzzy)  — an existing article tells the same narrative arc.
      3. Theme saturation     — N live articles already crowd this theme.

    Gate 3 is what actually catches the 2026-07-13 class: the arc gate is
    entity-anchored and the incident's five siblings do not even arc-match each
    other (see arc_dedup.theme_saturation docstring for the measurement).

    `mode="warn"` downgrades every hit to a warning (used by the event lane).
    Gate errors fail OPEN but are logged — never silently.
    """
    warn_only = mode == "warn"
    if not feed:
        # No corpus is "could not look", not "clean". Say so out loud.
        screen = TopicScreen(
            verdict=GATE_ERROR,
            blocked=False,
            reason="no feed corpus available; screen could not run (fail-open)",
        )
        _diag_warn("topic_dedup", "no feed corpus; screen skipped", title=title[:80])
        return screen

    try:
        if k_id:
            coverage = find_k_coverage(k_id, feed, audience)
            if coverage:
                ids = ", ".join(str(c.get("id")) for c in coverage[:3])
                return TopicScreen(
                    verdict=WARN_K_COVERAGE if warn_only else BLOCK_K_COVERAGE,
                    blocked=not warn_only,
                    reason=(
                        f"{k_id} already has {len(coverage)} live article(s) for "
                        f"audience={audience or 'any'}: {ids}"
                    ),
                    matches=coverage,
                )

        new_refs = {k_id} if k_id else None
        dups = find_arc_duplicates(
            title, description, feed, days=days, new_refs=new_refs, audience=audience
        )
        if dups:
            ids = ", ".join(str(d.get("id")) for d in dups[:3])
            return TopicScreen(
                verdict=WARN_ARC_DUP if warn_only else BLOCK_ARC_DUP,
                blocked=not warn_only,
                reason=f"narrative-arc duplicate of {ids}",
                matches=dups,
            )

        theme = theme_saturation(title, description, feed, days=days)
        saturation = int(theme["saturation"])
        if saturation >= saturation_threshold:
            ids = ", ".join(str(m.get("id")) for m in theme["matches"][:3])
            return TopicScreen(
                verdict=WARN_THEME_SATURATED if warn_only else BLOCK_THEME_SATURATED,
                blocked=not warn_only,
                reason=(
                    f"theme already covered by {saturation} live article(s) in "
                    f"{days}d (threshold {saturation_threshold}); closest: {ids}"
                ),
                matches=theme["matches"],
                theme_terms=theme["theme_terms"],
                saturation=saturation,
            )

        return TopicScreen(
            verdict=CLEAN,
            blocked=False,
            reason=f"no K coverage, no arc dup, theme saturation {saturation} < {saturation_threshold}",
            theme_terms=theme["theme_terms"],
            saturation=saturation,
        )
    except Exception as exc:
        # Fail-open per dedup-gate-audit.md, but LOUD per no-silent-fallback.md.
        _diag_warn(
            "topic_dedup",
            "screen raised; failing open",
            err=f"{type(exc).__name__}: {exc}",
            title=title[:80],
            mode=mode,
        )
        return TopicScreen(
            verdict=GATE_ERROR,
            blocked=False,
            reason=f"gate error, failed open: {type(exc).__name__}: {exc}",
        )
