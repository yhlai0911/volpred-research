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
    mode="block" (trending) — a high-confidence arc/K or non-recurring
    saturated theme prevents task creation. Recurring event-window theme-only
    hits remain warnings because the counter cannot distinguish event episodes.
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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from volpred.canonical_write import guard_canonical_write
from volpred.ops.diagnostics import warn as _diag_warn
from volpred.publisher.arc_dedup import (
    THEME_SATURATION_THRESHOLD,
    arc_signature,
    extract_entities,
    find_arc_duplicates,
    find_k_coverage,
    is_arc_anchorless,
    is_arc_near_miss,
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
WARN_ARC_NEAR_MISS = "warn_arc_near_miss"
WARN_K_COVERAGE = "warn_k_coverage"
# Not a hit and not a pass: the arc gate had no anchor, so it never looked.
# Never blocks (fail-open); it exists so the task row stops claiming `clean`.
UNJUDGED_THIN_SIGNATURE = "unjudged_thin_signature"
GATE_ERROR = "gate_error_fail_open"

# Only named, scheduled macro releases get the block-lane theme exemption.
# ``narrative_axis=event_window`` alone is far too broad: adding words such as
# 「財報公告前」to the known AI-capex duplicate flips that classifier and would
# turn a saturation=10 duplicate into a warning. Event-lane tasks are already
# warn-only; this allowlist exists specifically for recurring macro topics in
# the otherwise-blocking trending lane.
_RECURRING_MACRO_EVENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:FOMC|CPI|NFP|PCE|GDP|ECB|BOJ|BOE)(?![A-Za-z0-9])|"
    r"非農|消費者物價|消費者價格|個人消費支出|"
    r"(?:央行|聯準會|美聯儲).{0,8}(?:利率)?(?:決議|會議)|利率決議",
    flags=re.IGNORECASE,
)
_EVENT_WINDOW_CUE_RE = re.compile(
    r"前夕|公布前|公布後|發布前|發布後|決議前|決議後|會議前|會議後|"
    r"下一次|倒數|當日|前後|\b(?:preview|reaction|before|after)\b",
    flags=re.IGNORECASE,
)


def _is_recurring_macro_event(title: str, description: str) -> bool:
    """Recognise a titled scheduled macro episode without trusting axis precedence.

    Identity must be in the title. A description may mention CPI/FOMC merely as
    a control variable; letting that incidental text grant the exemption turns
    the known AI-capex duplicate back into a warning.
    """
    text = f"{title}\n{description}"
    return bool(
        _RECURRING_MACRO_EVENT_RE.search(title)
        and _EVENT_WINDOW_CUE_RE.search(text)
    )


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
            "blocked": self.blocked,
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
    path = os.path.join(str(storage_dir), "logs", "dedup_decisions.jsonl")
    guard_canonical_write(path)
    try:
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
    In block mode, recurring event-window theme hits are also advisory; exact
    K/arc duplicates still block before the theme gate.
    Gate errors fail OPEN but are logged — never silently.
    """
    if mode not in {"block", "warn"}:
        _diag_warn(
            "topic_dedup",
            "invalid mode; failing open",
            title=title[:80],
            mode=mode,
        )
        return TopicScreen(
            verdict=GATE_ERROR,
            blocked=False,
            reason=f"invalid dedup mode={mode!r}; gate failed open",
        )
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
        candidate_signature = arc_signature(title, description)
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
        arc_matches = find_arc_duplicates(
            title,
            description,
            feed,
            days=days,
            new_refs=new_refs,
            audience=audience,
            include_fuzzy=True,
        )
        dups = [m for m in arc_matches if not is_arc_near_miss(m)]
        near_misses = [m for m in arc_matches if is_arc_near_miss(m)]
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
            # Named macro releases such as CPI/NFP/FOMC are recurring episodes. A theme counter
            # cannot tell the July meeting from the June meeting (or a generic
            # term-structure explainer), so theme-only blocking creates a
            # permanent macro content hole. Exact K/arc duplicates above still
            # block; saturation remains a visible warning requiring manual
            # differentiation. Generic event-window wording (earnings/product
            # announcements) is NOT enough to enter this exception.
            recurring_event = _is_recurring_macro_event(
                title,
                description,
            )
            return TopicScreen(
                verdict=(
                    WARN_THEME_SATURATED
                    if warn_only or recurring_event
                    else BLOCK_THEME_SATURATED
                ),
                blocked=not warn_only and not recurring_event,
                reason=(
                    f"theme already covered by {saturation} live article(s) in "
                    f"{days}d (threshold {saturation_threshold}); closest: {ids}"
                    + (
                        "; recurring event-window macro theme is advisory, not a hard block"
                        if recurring_event
                        else ""
                    )
                ),
                matches=theme["matches"],
                theme_terms=theme["theme_terms"],
                saturation=saturation,
            )

        # Entity+mechanism overlap on an unclassifiable (descriptive) draft is
        # evidence worth showing, but the real-corpus audit found 17/21 such
        # hit records were false.  Never turn it into a content black hole;
        # surface it as a non-green, non-blocking verdict for both lanes.
        if near_misses:
            ids = ", ".join(str(d.get("id")) for d in near_misses[:3])
            return TopicScreen(
                verdict=WARN_ARC_NEAR_MISS,
                blocked=False,
                reason=(
                    f"fuzzy descriptive arc near-miss of {ids}; entity+mechanism "
                    "overlap alone is not duplicate evidence — caller must do the "
                    "3-layer dedup check"
                ),
                matches=near_misses,
                theme_terms=theme["theme_terms"],
                saturation=saturation,
            )

        # The arc gate returning no hits only means "clean" if it had something to
        # anchor on. A topic with no K-id and only core entities (US_EQUITY / VIX /
        # TW_EQUITY) is unanchorable, so `find_arc_duplicates` could not have found
        # a duplicate even if five of them were live — which is exactly what
        # happened on 2026-07-13 and again on 2026-07-14 (see `is_arc_anchorless`).
        # Saturation is an independent signal and may still have judged the topic;
        # only when it ALSO came up short do we genuinely not know.
        #
        # Fail-open per `.claude/rules/dedup-gate-audit.md`: this never blocks.
        # Blocking on "could not judge" would kill every macro/thematic topic that
        # carries no ticker — a content black hole, the exact failure that rule
        # forbids. The task is still created; it just carries an honest verdict and
        # the near misses, so the dispatching main thread does the 3-layer check
        # instead of trusting a green tick.
        if is_arc_anchorless(candidate_signature, new_refs):
            return TopicScreen(
                verdict=UNJUDGED_THIN_SIGNATURE,
                blocked=False,
                reason=(
                    "arc gate had no anchor (no distinctive entity, no experiment ref) "
                    f"— it did not look; theme saturation {saturation} < {saturation_threshold} "
                    "is the only signal that ran. Caller must do the 3-layer dedup check."
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


_CALIBRATION_BASELINE_CORPUS = 831
_CALIBRATION_CORPUS_DRIFT_RATIO = 0.25
_CALIBRATION_AI_TITLE = "AI變現挑戰：從期權波動率解析科技巨頭的資本定價分歧"
_CALIBRATION_AI_DESCRIPTION = (
    "隨著市場對 AI 變現速度的審視，高額資本支出面臨考驗。"
    "可量化角度：分析美股七巨頭的歷史 CapEx 宣告日前後，"
    "其隱含波動率（IV）與歷史波動率（HV）的溢價擴張程度。"
)
_CALIBRATION_NFP_TITLE = "下一次非農公布前：就業分歧是否先進入美元波動率？"
_CALIBRATION_NFP_DESCRIPTION = (
    "下一次 NFP 公布前，分析美元 DXY 日內已實現波動與"
    "選擇權隱含波動的定價差。"
)


def audit_topic_dedup_calibration(
    feed: list[dict],
    *,
    days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Run pinned live-corpus probes and report threshold/semantic drift.

    This is intentionally read-only and warning-only.  Synthetic unit tests pin
    mechanics; this probe catches the production failure class where the exact
    same code sees a materially different corpus and threshold margin.
    """
    plain = theme_saturation(
        _CALIBRATION_AI_TITLE, _CALIBRATION_AI_DESCRIPTION, feed, days=days
    )
    prefixed = theme_saturation(
        f"[trending_repost] {_CALIBRATION_AI_TITLE}",
        _CALIBRATION_AI_DESCRIPTION,
        feed,
        days=days,
    )
    nfp_control = theme_saturation(
        _CALIBRATION_NFP_TITLE,
        _CALIBRATION_NFP_DESCRIPTION,
        feed,
        days=days,
    )
    nfp_screen = screen_topic(
        _CALIBRATION_NFP_TITLE,
        _CALIBRATION_NFP_DESCRIPTION,
        feed=feed,
        audience="general",
        days=days,
        mode="block",
    )
    incident_screen = screen_topic(
        _CALIBRATION_AI_TITLE,
        _CALIBRATION_AI_DESCRIPTION,
        feed=feed,
        audience="general",
        days=days,
        mode="block",
    )
    corpus_size = int(plain.get("corpus_size") or 0)
    incident_saturation = int(plain.get("saturation") or 0)
    margin = incident_saturation - THEME_SATURATION_THRESHOLD

    fomc_title = "2026-07-29 FOMC 前夕：市場在為降息還是鷹派押注？"
    fomc_desc = "本次 FOMC 利率決議前，選擇權市場的定價與波動率期限結構。"
    fomc_matches = find_arc_duplicates(
        fomc_title,
        fomc_desc,
        feed,
        days=days,
        audience="general",
        include_fuzzy=True,
    )
    fomc_hard = [m for m in fomc_matches if not is_arc_near_miss(m)]
    fomc_near = [m for m in fomc_matches if is_arc_near_miss(m)]
    fomc_theme = theme_saturation(fomc_title, fomc_desc, feed, days=days)
    fomc_screen = screen_topic(
        fomc_title,
        fomc_desc,
        feed=feed,
        audience="general",
        days=days,
        mode="block",
    )

    negated = arc_signature(
        "選擇權到期日曆效應",
        "研究美股到期效應；不涉及油價、財報、Fed、VIX。",
    )
    crypto_entities = extract_entities(
        "USDT、USDC 與穩定幣脫鉤時，DeFi 流動性如何傳染"
    )
    bank_entities = extract_entities("銀行財報與存款流失")

    issues: list[str] = []
    if plain["theme_terms"] != prefixed["theme_terms"] or incident_saturation != int(
        prefixed.get("saturation") or 0
    ):
        issues.append("task prefix changed theme terms or saturation")
    if incident_saturation < THEME_SATURATION_THRESHOLD:
        issues.append(
            f"known AI-capex duplicate scored {incident_saturation} below threshold "
            f"{THEME_SATURATION_THRESHOLD}"
        )
    elif margin <= 1:
        issues.append(
            f"known AI-capex duplicate margin is only {margin} above threshold"
        )
    if (
        not incident_screen.blocked
        or incident_screen.verdict != BLOCK_THEME_SATURATED
    ):
        issues.append(
            "known AI-capex duplicate did not retain its calibrated theme block "
            f"(verdict {incident_screen.verdict}, blocked={incident_screen.blocked})"
        )
    if int(nfp_control.get("saturation") or 0) >= THEME_SATURATION_THRESHOLD:
        issues.append(
            "legitimate NFP/DXY control is theme-saturated at "
            f"{nfp_control.get('saturation')} (threshold {THEME_SATURATION_THRESHOLD})"
        )
    if nfp_screen.blocked or nfp_screen.verdict == GATE_ERROR:
        issues.append(
            "legitimate NFP/DXY control did not retain its nonblocking verdict "
            f"(verdict {nfp_screen.verdict}, blocked={nfp_screen.blocked})"
        )
    low = int(_CALIBRATION_BASELINE_CORPUS * (1 - _CALIBRATION_CORPUS_DRIFT_RATIO))
    high = int(_CALIBRATION_BASELINE_CORPUS * (1 + _CALIBRATION_CORPUS_DRIFT_RATIO))
    if not low <= corpus_size <= high:
        issues.append(
            f"90d live corpus size {corpus_size} outside calibrated range {low}-{high}"
        )
    if fomc_hard:
        issues.append(
            f"legitimate FOMC control has {len(fomc_hard)} hard arc match(es)"
        )
    if fomc_screen.blocked or fomc_screen.verdict != WARN_THEME_SATURATED:
        issues.append(
            "legitimate recurring FOMC control did not retain its calibrated warning "
            f"(verdict {fomc_screen.verdict}, blocked={fomc_screen.blocked})"
        )
    if {"FOMC", "VIX", "OIL"} & set(negated.get("entities") or []):
        issues.append("negated exclusion list leaked rejected entities into signature")
    if not {"STABLECOIN", "DEFI"} <= crypto_entities:
        issues.append("crypto entity vocabulary lost STABLECOIN or DEFI")
    if "SILVER" in bank_entities:
        issues.append("bank text was misclassified as SILVER")

    return {
        "ok": not issues,
        "issues": issues,
        "metrics": {
            "days": days,
            "corpus_size": corpus_size,
            "baseline_corpus_size": _CALIBRATION_BASELINE_CORPUS,
            "theme_threshold": THEME_SATURATION_THRESHOLD,
            "incident_saturation": incident_saturation,
            "incident_margin": margin,
            "incident_theme_terms": plain["theme_terms"],
            "incident_screen_verdict": incident_screen.verdict,
            "incident_screen_blocked": incident_screen.blocked,
            "nfp_control_saturation": int(nfp_control.get("saturation") or 0),
            "nfp_control_theme_terms": nfp_control.get("theme_terms") or [],
            "nfp_screen_verdict": nfp_screen.verdict,
            "nfp_screen_blocked": nfp_screen.blocked,
            "fomc_hard_matches": len(fomc_hard),
            "fomc_near_misses": len(fomc_near),
            "fomc_theme_saturation": int(fomc_theme.get("saturation") or 0),
            "fomc_screen_verdict": fomc_screen.verdict,
        },
    }
