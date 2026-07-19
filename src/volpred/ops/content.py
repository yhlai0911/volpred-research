from __future__ import annotations

import fcntl
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timedelta, timezone

from scripts.article_backups import ensure_local_article_backups
from volpred.publisher.arc_dedup import (
    ARC_SIGNATURE_SCHEMA_VERSION,
    arc_signature,
    arc_signature_from_feed_item,
    find_arc_duplicates,
    is_arc_anchorless,
    is_arc_near_miss,
)
from volpred.publisher.publisher import (
    Publisher,
    _audit_general_content,
    _extract_experiment_refs,
    _run_publish_anti_ai_gate,
    has_lazypack_section,
)
from volpred.topic_clusters import classify_topic_cluster, cluster_cap

from volpred.canonical_write import guard_canonical_write
from .common import dump_json, load_json, project_path, write_ops_snapshot
from .content_quality import DIGEST_TITLE_PREFIX
from .next_tasks import normalize_task_priority, validate_task_status, write_tasks_to_handle
from scripts.supabase_sync import _delete_where, _get_article_id, _patch_where, _select_rows, delete_article, sync_article

DEFAULT_RELEASE_SETTINGS = {
    "mode": "manual",
    "interval_minutes": 1440,
    "max_articles_per_run": 1,
    "due_only": True,
    "include_drafts": False,
    "preferred_audiences": [],
    "last_released_at": None,
    "updated_at": None,
}


def _feed_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "reports", "feed.json")


def load_feed(storage_dir: str = "storage") -> list[dict]:
    return load_json(_feed_path(storage_dir), [])


def get_feed_item(pub_id: str, storage_dir: str = "storage") -> dict | None:
    for item in load_feed(storage_dir):
        if item.get("id") == pub_id:
            return item
    return None


def publish_milestone_article(
    title: str,
    description: str,
    *,
    phase: str,
    details: dict | None = None,
    tags: list[str] | None = None,
    status: str = "published",
    publish_at: str | None = None,
    audience: str | None = None,
    category: str | None = None,
    proposer: str | None = None,
    storage_dir: str = "storage",
) -> str:
    publisher = Publisher(storage_dir=storage_dir)
    return publisher.publish_milestone(
        title=title,
        description=description,
        phase=phase,
        details=details,
        tags=tags,
        status=status,
        publish_at=publish_at,
        audience=audience,
        category=category,
        proposer=proposer,
    )


def _normalize_release_settings(row: dict | None = None) -> dict:
    data = {**DEFAULT_RELEASE_SETTINGS, **(row or {})}
    mode = str(data.get("mode") or "manual").strip().lower()
    interval_minutes = data.get("interval_minutes")
    max_articles_per_run = data.get("max_articles_per_run")
    preferred_audiences = data.get("preferred_audiences") or []

    return {
        "mode": mode if mode in ("scheduled", "auto") else "manual",
        "interval_minutes": max(5, min(int(interval_minutes or 1440), 24 * 60 * 14)),
        "max_articles_per_run": max(1, min(int(max_articles_per_run or 1), 20)),
        "due_only": bool(data.get("due_only", True)),
        "include_drafts": bool(data.get("include_drafts", False)),
        "preferred_audiences": [
            str(value).strip()
            for value in preferred_audiences
            if isinstance(value, str) and value.strip()
        ],
        "last_released_at": data.get("last_released_at"),
        "updated_at": data.get("updated_at"),
    }


def _local_release_settings_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, ".release_settings.json")


def _warn_release_settings(message: str, exc: Exception) -> None:
    print(
        f"[content_release_settings] WARN {message}: "
        f"{type(exc).__name__}: {exc}"
    )


def _warn_question_link_side_effect(message: str, article_slug: str, exc: Exception) -> None:
    print(
        f"[content_question_links] WARN {message}: "
        f"article_slug={article_slug} error={type(exc).__name__}: {exc}"
    )


def _warn_release_pool(message: str, exc: Exception) -> None:
    print(f"  [release_pool] WARN {message}: {type(exc).__name__}: {exc}")


def _derived_last_released_at_from_feed(storage_dir: str = "storage") -> str | None:
    """Return the latest published_at among items released BY release_pool.

    Excludes:
    - member_qa: never goes through the release pool
    - audience=daily: daily strategy / position articles are emitted directly
      by daily_update.py at fixed cron times (08:03 CST), never enter the
      draft pool, never count as a pool release. (2026-04-25 fix: prior
      behavior treated daily publishes as pool releases, which permanently
      reset the 12h interval timer and starved real research/general drafts.)
    """
    latest_published_at: datetime | None = None
    for item in load_feed(storage_dir):
        if item.get("status") != "published":
            continue
        if str(item.get("category") or "").strip() == "member_qa":
            continue
        if str(item.get("audience") or "").strip() == "daily":
            continue
        published_at = _parse_datetime(item.get("published_at"))
        if published_at is None:
            continue
        if latest_published_at is None or published_at > latest_published_at:
            latest_published_at = published_at
    return latest_published_at.isoformat() if latest_published_at is not None else None


def get_content_release_settings(storage_dir: str = "storage") -> dict:
    """Read release settings from local JSON (no Supabase hit)."""
    local = _local_release_settings_path(storage_dir)
    data = load_json(local, None)
    if data is not None:
        settings = _normalize_release_settings(data)
    else:
        # First run or missing file: try Supabase once, then cache locally
        try:
            rows = _select_rows("content_release_settings", id="default")
            row = rows[0] if rows else None
        except Exception as exc:
            _warn_release_settings("Supabase read failed; using local defaults", exc)
            row = None
        settings = _normalize_release_settings(row)
        dump_json(local, settings)

    # Backward compatibility: if last_released_at is missing/invalid, keep the
    # legacy "first run always fires" behavior instead of deriving from feed.
    stored_last_released = settings.get("last_released_at")
    stored_last_released_at = _parse_datetime(stored_last_released)
    if stored_last_released_at is None:
        return settings

    derived_last_released = _derived_last_released_at_from_feed(storage_dir)
    derived_last_released_at = _parse_datetime(derived_last_released)
    if derived_last_released_at is None or derived_last_released_at == stored_last_released_at:
        return settings

    settings["last_released_at"] = derived_last_released_at.isoformat()
    _update_content_release_settings(
        {"last_released_at": settings["last_released_at"]},
        storage_dir=storage_dir,
    )
    return settings


def _update_content_release_settings(fields: dict, *, storage_dir: str = "storage") -> bool:
    """Update release settings in local JSON and optionally sync to Supabase.

    2026-04-20: PATCH payload narrowed to (fields | updated_at) instead of full
    current-settings merge. Prior behavior sent all 8 settings fields each cron
    fire, triggering recurring Supabase HTTP 400 when table schema lacks a
    local-only column (e.g. include_drafts). Delta PATCH reduces schema-mismatch
    surface and is semantically correct — the caller only wanted `fields` updated.
    """
    local = _local_release_settings_path(storage_dir)
    current = load_json(local, {**DEFAULT_RELEASE_SETTINGS})
    now_iso = datetime.now(timezone.utc).isoformat()
    local_payload = {**current, **fields, "updated_at": now_iso}
    dump_json(local, local_payload)
    remote_payload = {**fields, "updated_at": now_iso}
    # 2026-05-04 finding #B3.5: Supabase content_release_settings.mode CHECK
    # constraint predates the client-side 'auto' mode and only accepts
    # ('manual','scheduled'). 'auto' is semantically a scheduled fire that
    # bypasses force checks (see release_pool_by_settings L404), so map
    # 'auto'→'scheduled' on the wire. Local payload keeps 'auto' as-is so
    # release_pool_articles still bypasses the force check.
    if remote_payload.get("mode") == "auto":
        remote_payload["mode"] = "scheduled"
    try:
        return _patch_where("content_release_settings", {"id": "default"}, remote_payload)
    except Exception as exc:
        _warn_release_settings("Supabase patch failed; local settings updated only", exc)
        return False


def _parse_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        from .diagnostics import warn

        warn(
            "content_parse_datetime",
            "datetime parse failed; treating as missing",
            value=str(value)[:64],
            err=f"{type(exc).__name__}: {exc}",
        )
        return None


def _article_audience(item: dict) -> str:
    audience = item.get("audience") or (item.get("details") or {}).get("audience")
    if isinstance(audience, str) and audience.strip():
        return audience.strip()
    return "uncategorized"


def _is_reader_facing_published(item: dict) -> bool:
    """A published article that counts toward the reader-facing cadence used by
    the drought circuit-breaker.

    Reader-facing = general / research articles, plus the daily digest roundup
    (title prefix DIGEST_TITLE_PREFIX). The templated daily VIX / holdings
    bulletin (audience='daily', non-digest), member_qa and event pieces do NOT
    count: they publish on their own fixed cadence and would otherwise mask a
    genuine drought of real reader-facing content.
    """
    if not isinstance(item, dict) or item.get("status") != "published":
        return False
    if _article_audience(item) in _RELEASE_DEDUP_AUDIENCES:
        return True
    title = str(item.get("title") or "")
    return title.startswith(DIGEST_TITLE_PREFIX)


# --- Release-time anti-flood dedup gate -------------------------------------
# 2026-06-16 incident: release_pool promoted drafts with ZERO dedup vs
# already-published → 2026-06-15 dumped 5 "model-comparison / complexity-
# doesn't-win" general articles in one day on top of a 36-article corpus of the
# same theme. Neither arc_dedup (method articles, no distinctive ASSET entity)
# nor topic_cluster (spread across spy/vix/None) caught it. This gate compares a
# candidate draft's title+body bigram profile against recently-published
# general/research articles; a near-duplicate is skipped (stays draft) instead
# of flooding the live feed. Daily/event/member_qa audiences are exempt (their
# repetition is by design — e.g. the templated daily VIX bulletin).
_RELEASE_DEDUP_WINDOW_DAYS = 21
# 2026-06-23 (boss「可以發文了嗎」throughput incident): the per-draft
# `release_dedup_skipped` flag is only an anti-thrash COOLDOWN — it stops the
# release pool from re-evaluating the same near-dup draft on every single run.
# It must NOT be tied to the full 21-day dedup WINDOW: a single transient skip
# (e.g. one-off cluster pressure) then locks that draft out of release for 21
# days, and over time EVERY draft accumulates the flag → the whole pool freezes
# (observed: 46/46 drafts flagged, 0 eligible, 0 articles/day). Correctness is
# already guaranteed by the LIVE dedup gates (narrative_cluster_filtered +
# Jaccard near-dup) re-checked against current published content on every run;
# the flag is pure optimization, so a short cooldown is sufficient and safe.
_RELEASE_DEDUP_FLAG_TTL_DAYS = 2
# A cooldown flag caches a decision made by the gates BELOW. When that logic
# changes, every cached decision is stale by definition — but the TTL alone will
# not surface that: a draft blocked by a permanent condition simply gets
# re-stamped on each re-evaluation, so the cooldown never expires in practice
# (2026-07-11: 5 drafts held 5-12 days, pool released 0). Stamping the gate
# version makes a logic change self-invalidating: bump this whenever the block
# rules change and the next run re-decides from scratch instead of trusting a
# verdict the current code would no longer reach.
_RELEASE_DEDUP_GATE_VERSION = 3
_RELEASE_DEDUP_JACCARD = 0.45
_RELEASE_DEDUP_AUDIENCES = {"general", "research"}
_RELEASE_LAST_N_CLUSTER_WINDOW = 3
_RELEASE_LAST_N_CLUSTER_THRESHOLD = 2
# Drought circuit-breaker threshold (2026-06-24). A publishing gap hurts
# Mission #1 (content) / #5 (traffic) more than an occasional borderline-similar
# article — the same fail-open stance as .claude/rules/dedup-gate-audit.md
# ("寧錯放可接受重複也不要 invisible content gap"). Kept below the 5h
# publishing-freshness dead-man critical (alerts.PUBLISH_FRESHNESS_CRITICAL_HOURS)
# so the breaker self-remediates BEFORE that alert fires, with buffer.
_RELEASE_DROUGHT_HOURS = 4.0
_RELEASE_SOURCE_KEYS = {
    "data_source",
    "data_sources",
    "dataset",
    "dataset_id",
    "event_key",
    "source_ref",
    "source_refs",
    "source_url",
    "source_urls",
}
_GENERIC_RELEASE_SOURCE_VALUES = {
    "yfinance",
    "fred",
    "cboe",
    "sec",
    "bls",
    "bea",
    "federal reserve",
    "supabase",
}

_NARRATIVE_CLUSTER_PATTERNS = {
    "garch": re.compile(r"\b(ST)?GARCH\b|GJR|EGARCH|GARCH-MIDAS|MF-GJR|EWMA", re.I),
    "vix": re.compile(r"\bVIX\b|VVIX|VIX9D|恐慌指數|12/VIX", re.I),
    "vrp": re.compile(r"\bVRP\b|variance risk premium|波動率風險溢酬", re.I),
    "har": re.compile(r"\bHAR(?:-RV)?\b|heterogeneous autoregressive", re.I),
    "copula": re.compile(r"\bcopula\b|copula-based|DCC|BEKK", re.I),
    "vt": re.compile(r"波動率目標|vol(?:atility)?[\s-]?target|VT\s*(策略|參數|保險|成本)", re.I),
}


def _bigram_profile(text: str) -> set[str]:
    s = re.sub(r"[\s0-9A-Za-z，,。.：:；;？?！!（）()「」、\-—~%]+", "", text or "")
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _release_content_dup(item: dict, recent_pub: list[dict]) -> dict | None:
    """Return the most-similar recently-published article if `item` is a
    near-duplicate by title+body bigram Jaccard, else None."""
    title = str(item.get("title") or "")
    body = str(item.get("content") or item.get("description") or "")[:2000]
    prof = _bigram_profile(title + "\n" + body)
    if len(prof) < 20:  # too short to judge — don't block
        return None
    best, best_j = None, 0.0
    for other in recent_pub:
        if other.get("id") == item.get("id"):
            continue
        oprof = _bigram_profile(
            str(other.get("title") or "")
            + "\n"
            + str(other.get("content") or other.get("description") or "")[:2000]
        )
        if not oprof:
            continue
        j = len(prof & oprof) / len(prof | oprof)
        if j > best_j:
            best, best_j = other, j
    if best is not None and best_j >= _RELEASE_DEDUP_JACCARD:
        return {"id": best.get("id"), "title": best.get("title"), "jaccard": round(best_j, 3)}
    return None


def _release_max_jaccard(item: dict, recent_pub: list[dict]) -> float:
    """Max title+body bigram Jaccard of `item` vs any recently-published
    reader-facing article (0.0 when nothing comparable / too short to judge).

    Unlike `_release_content_dup` this returns the raw similarity even below the
    dedup threshold — used by the drought breaker to pick the LEAST dup-like
    blocked draft to force-release."""
    title = str(item.get("title") or "")
    body = str(item.get("content") or item.get("description") or "")[:2000]
    prof = _bigram_profile(title + "\n" + body)
    if len(prof) < 20:
        return 0.0
    best_j = 0.0
    for other in recent_pub:
        if other.get("id") == item.get("id"):
            continue
        oprof = _bigram_profile(
            str(other.get("title") or "")
            + "\n"
            + str(other.get("content") or other.get("description") or "")[:2000]
        )
        if not oprof:
            continue
        j = len(prof & oprof) / len(prof | oprof)
        if j > best_j:
            best_j = j
    return round(best_j, 3)


def _item_narrative_axis(item: dict) -> str:
    """Resolve an article's reader-facing narrative axis.

    Prefers the persisted arc_signature (so we agree with the arc gate) and
    falls back to recomputing from title+content. Fail-open to "unspecified"
    with a trace so a bad signature never silently changes dedup behaviour.
    """
    try:
        details = item.get("details")
        if isinstance(details, dict):
            sig = details.get("arc_signature")
            if (
                isinstance(sig, dict)
                and sig.get("schema_version") == ARC_SIGNATURE_SCHEMA_VERSION
            ):
                axis = sig.get("narrative_axis")
                if isinstance(axis, str) and axis:
                    return axis
        return str(
            arc_signature_from_feed_item(item).get("narrative_axis")
            or "unspecified"
        )
    except Exception as exc:  # noqa: BLE001
        from .diagnostics import warn

        warn(
            "release_dedup_axis",
            "narrative axis classification failed",
            err=str(exc),
            item_id=str(item.get("id") or ""),
        )
        return "unspecified"


def _release_axis_waives_dup(item: dict, blockers: list[dict]) -> bool:
    """Mirror arc_dedup v3: a text-similar pair on DIFFERENT narrative axes is
    not a real duplicate.

    The release gate's Jaccard / theme-flood checks are pure surface-text
    similarity and (unlike `find_arc_duplicates`) have no narrative-axis
    concept. A paper methodology-robustness note and an ETF product-myth piece
    can share SPY/VIX/momentum tokens while telling completely different reader
    stories. When BOTH the candidate and the blocker resolve to a SPECIFIED and
    DIFFERENT axis, this returns True (waive the dup → release).

    Conservative by design: if any axis is "unspecified", or any blocker shares
    the candidate's axis, returns False (no waiver — keep the original Jaccard /
    theme-flood verdict). It only ever RELAXES a near-dup; it never creates one.
    """
    cand_axis = _item_narrative_axis(item)
    if cand_axis == "unspecified":
        return False
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        block_axis = _item_narrative_axis(blocker)
        # Any unspecified or matching axis means we cannot rule out a real dup;
        # keep the conservative (original) verdict and do not waive.
        if block_axis == "unspecified" or block_axis == cand_axis:
            return False
    return True


# --- G1: member_qa publish-time duplicate gate (2026-07-19, STRIKE 2) --------
# Incident history for this class:
#   2026-03-31 (STRIKE 1) mile_530a28bc / mile_42ee876c — same member, same
#     Taiwan-economy question answered twice within 7 hours.
#   2026-07-19 (STRIKE 2) mile_d84aa7d0 (2026-07-12) / mile_0205a444
#     (2026-07-19) — member yaoxk1431's "30 年每年成長 15% / 7%" question
#     researched and published twice, one week apart.
#
# WHY THIS GATE LIVES AT PUBLISH TIME, not upstream:
# every previous fix guarded an INTENT step (ensure_member_qa_task creating a
# task, claim_question_for_research claiming a question). Those are all
# skippable — a main thread that hand-writes an article and calls
# publish-milestone directly never touches them, and that is exactly how
# STRIKE 2 happened. The published article is the only artifact the reader
# actually sees, and until now it was the ONE step with no owner. This gate is
# the last line of defence: it holds even when every upstream gate is bypassed,
# because nothing reaches a reader without passing through here.
#
# Deliberate follow-ups (先發初步、後補深入) are legitimate and must stay
# possible, so the gate has ONE legal channel: details['supersedes'] (CLI:
# --supersedes) must NAME the prior article id(s) it continues. Naming is the
# point — an unconditional bypass flag would decay into "always set it", while
# naming forces the author to look at what already exists.
_MEMBER_QA_PUBLISHED_STATUSES = {"published", "scheduled"}


class MemberQaDuplicatePublishError(ValueError):
    """Raised when a member_qa article would be the 2nd published answer to a
    question that already has one."""


class MemberQaPublishGateIndeterminate(ValueError):
    """Raised when the gate cannot establish whether a prior published answer
    exists (e.g. the local feed is unreadable).

    Fail-closed, but LOUD and distinguishable: 'we could not check' must never
    be silently rendered as 'clear'. Callers/operators see a different error
    class than a real duplicate so they can retry rather than assume a dup.
    """


def _member_qa_local_prior_answers(
    question_id: str,
    feed: list[dict],
    *,
    exclude_article_id: str | None = None,
) -> list[dict]:
    """Published/scheduled member_qa articles already bound to `question_id`."""
    hits: list[dict] = []
    for item in feed or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in _MEMBER_QA_PUBLISHED_STATUSES:
            continue
        details = item.get("details")
        qid = None
        if isinstance(details, dict):
            qid = details.get("question_id")
        qid = qid or item.get("question_id")
        if not qid or str(qid) != str(question_id):
            continue
        if exclude_article_id and str(item.get("id")) == str(exclude_article_id):
            continue
        hits.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "published_at": item.get("published_at") or item.get("created_at"),
                "source": "local_feed",
            }
        )
    return hits


def _member_qa_remote_prior_answers(question_id: str) -> tuple[list[dict], str | None]:
    """Supabase-side prior answers via question_articles → articles.

    Returns (hits, error). `error` non-None means the remote side is UNKNOWN,
    not clear. Supabase is an ENRICHMENT source here (it can see articles this
    checkout never wrote); the local feed is the authoritative mirror of
    everything this repo publishes, so a remote outage degrades coverage but
    does not stall the member_qa line — see `assert_member_qa_publish_allowed`.
    """
    try:
        links = _select_rows(
            "question_articles", select="question_id,article_id", question_id=question_id
        )
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    hits: list[dict] = []
    for link in links or []:
        article_id = link.get("article_id") if isinstance(link, dict) else None
        if not article_id:
            continue
        try:
            rows = _select_rows("articles", select="id,slug,status,title", id=article_id)
        except Exception as exc:  # noqa: BLE001
            return hits, f"{type(exc).__name__}: {exc}"
        for row in rows or []:
            if str(row.get("status") or "") not in _MEMBER_QA_PUBLISHED_STATUSES:
                continue
            hits.append(
                {
                    "id": row.get("slug") or row.get("id"),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "published_at": None,
                    "source": "supabase",
                }
            )
    return hits, None


def find_published_member_qa_articles(
    question_id: str,
    *,
    feed: list[dict] | None = None,
    storage_dir: str = "storage",
    exclude_article_id: str | None = None,
) -> dict:
    """Every already-published answer to `question_id`, plus source health.

    Result keys:
      articles          — de-duplicated prior published/scheduled answers
      local_ok          — the authoritative local feed was readable
      remote_ok         — the Supabase enrichment query succeeded
      remote_error      — why it did not (None when remote_ok)
    """
    local_ok = True
    if feed is None:
        try:
            feed = load_feed(storage_dir)
        except Exception as exc:  # noqa: BLE001
            from .diagnostics import warn

            warn("member_qa_publish_gate", "local feed unreadable", err=str(exc))
            feed, local_ok = [], False
    hits = _member_qa_local_prior_answers(
        question_id, feed or [], exclude_article_id=exclude_article_id
    )
    remote_hits, remote_error = _member_qa_remote_prior_answers(question_id)
    for hit in remote_hits:
        if exclude_article_id and str(hit.get("id")) == str(exclude_article_id):
            continue
        if any(str(h.get("id")) == str(hit.get("id")) for h in hits):
            continue
        hits.append(hit)
    return {
        "question_id": question_id,
        "articles": hits,
        "local_ok": local_ok,
        "remote_ok": remote_error is None,
        "remote_error": remote_error,
    }


def _normalize_supersedes(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", " ").split()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(p).strip() for p in value]
    else:
        parts = [str(value).strip()]
    return [p for p in parts if p]


def assert_member_qa_publish_allowed(
    question_id: str | None,
    *,
    feed: list[dict] | None = None,
    supersedes=None,
    title: str = "",
    storage_dir: str = "storage",
    exclude_article_id: str | None = None,
) -> dict:
    """Raise unless this member_qa article may become a reader-visible answer.

    Blocks when the question already has ≥1 published/scheduled answer, unless
    `supersedes` explicitly names ALL of them (the deliberate-sequel channel).
    """
    if not question_id:
        # No binding key → the gate cannot judge. Loud, stamped, and allowed:
        # blocking every legacy/unbound member_qa publish would stall the line
        # for a condition the gate itself cannot resolve. Recorded so an
        # unbound publish is auditable rather than invisible.
        from .diagnostics import warn

        warn(
            "member_qa_publish_gate",
            "member_qa publish carries no details.question_id — duplicate gate UNJUDGED",
            title=str(title)[:80],
        )
        print(
            "  ⚠️ member_qa publish has no details['question_id'] — duplicate gate "
            "could not judge this article. Set it so the publish-time gate can protect readers."
        )
        return {"blocked": False, "verdict": "unjudged_no_question_id", "articles": []}

    found = find_published_member_qa_articles(
        question_id,
        feed=feed,
        storage_dir=storage_dir,
        exclude_article_id=exclude_article_id,
    )
    if not found["local_ok"]:
        # We are blind on the authoritative source: "unknown" must not be
        # rendered as "no duplicate". Fail closed with a DISTINCT error type.
        raise MemberQaPublishGateIndeterminate(
            "member_qa_publish_gate_indeterminate: local feed unreadable, cannot "
            f"verify whether question_id={question_id} already has a published answer. "
            "Fix the feed read and retry — this is NOT a clearance."
        )

    priors = found["articles"]
    if not priors:
        if not found["remote_ok"]:
            # Local (authoritative for anything this repo published) says clear;
            # only the Supabase enrichment is down. Degrade explicitly instead of
            # stalling the whole member_qa line on an external outage.
            print(
                "  ⚠️ member_qa publish gate DEGRADED: Supabase cross-check unavailable "
                f"({found['remote_error']}); cleared on local feed only."
            )
            return {"blocked": False, "verdict": "clear_degraded", **found}
        return {"blocked": False, "verdict": "clear", **found}

    prior_ids = [str(a.get("id")) for a in priors]
    declared = set(_normalize_supersedes(supersedes))
    if declared and set(prior_ids).issubset(declared):
        print(
            f"  ↪️ member_qa sequel allowed: supersedes={sorted(declared)} "
            f"(question_id={question_id})"
        )
        return {"blocked": False, "verdict": "supersedes", **found}

    listed = "; ".join(
        f"{a.get('id')} ({a.get('status')}, {a.get('source')}) '{str(a.get('title') or '')[:40]}'"
        for a in priors
    )
    raise MemberQaDuplicatePublishError(
        "member_qa_duplicate_publish_blocked: question_id="
        f"{question_id} already has {len(priors)} published answer(s): {listed}. "
        "This is the 2026-07-19 STRIKE 2 class (a member's question answered twice). "
        "If this is a deliberate follow-up, re-run with "
        f"details['supersedes']={prior_ids!r} (CLI: --supersedes "
        f"{','.join(prior_ids)}); otherwise do not publish."
    )


def _extract_k_ids_from_item(item: dict) -> set[str]:
    refs: set[str] = set()
    details = item.get("details")
    if isinstance(details, dict):
        raw_refs = details.get("experiment_refs") or details.get("experiment_ids") or []
        if isinstance(raw_refs, str):
            raw_refs = [raw_refs]
        if isinstance(raw_refs, list):
            refs.update(str(r).upper() for r in raw_refs if re.fullmatch(r"K\d+", str(r).upper()))
    raw_tags = item.get("tags") or []
    if isinstance(raw_tags, list):
        refs.update(str(t).upper() for t in raw_tags if re.fullmatch(r"K\d+", str(t).upper()))
    return refs


def _release_source_token(raw: object) -> str | None:
    """Normalize explicit source metadata for release-time arc blocking.

    The release gate must not block merely because two articles have the same
    conclusion class or mention the same broad provider. Only precise metadata
    such as the same event key, source URL, dataset id, or non-generic data
    source string can make an arc hit a hard release block.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        if set(raw) <= {"provider"}:
            return None
        text = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    else:
        text = str(raw)
    token = re.sub(r"\s+", " ", text.strip()).lower()
    if not token or len(token) < 4:
        return None
    if token in _GENERIC_RELEASE_SOURCE_VALUES:
        return None
    return token


def _release_iter_source_values(raw: object):
    if isinstance(raw, dict):
        yield raw
        for value in raw.values():
            yield from _release_iter_source_values(value)
    elif isinstance(raw, (list, tuple, set)):
        for value in raw:
            yield from _release_iter_source_values(value)
    else:
        yield raw


def _release_data_source_tokens(item: dict) -> set[str]:
    """Return explicit data/event-source tokens suitable for hard blocking."""
    tokens: set[str] = set()
    containers = [item]
    details = item.get("details")
    if isinstance(details, dict):
        containers.append(details)

    for container in containers:
        event_key = _release_source_token(container.get("event_key"))
        if event_key:
            tokens.add(f"event_key:{event_key}")
        event_type = _release_source_token(container.get("event_type"))
        event_date = _release_source_token(container.get("event_date"))
        if event_type and event_date:
            tokens.add(f"event:{event_type}:{event_date}")
        for key in _RELEASE_SOURCE_KEYS:
            if key == "event_key":
                continue
            if key not in container:
                continue
            for value in _release_iter_source_values(container.get(key)):
                token = _release_source_token(value)
                if token:
                    tokens.add(f"{key}:{token}")
    return tokens


def _release_arc_block_reason(item: dict, blocker: dict | None, arc_dup: dict) -> str | None:
    """Return why an arc-dup is strong enough to block release, else None.

    Arc-dedup is scoped to ONE audience. Publishing a research write-up and a
    general-reader write-up of the same K is the product design, not a rehash —
    74 K-ids already carry both audiences in the live feed. Judging the general
    twin against its research sibling made "shared K" fire on every such draft,
    which is a permanent condition (the sibling stays published forever), so the
    draft could never leave the pool: the cooldown flag below was re-stamped on
    every re-evaluation and the pool released 0 articles for 30+ consecutive
    fires (2026-07-11; second occurrence of the 2026-06-23 pool-freeze).

    Within one audience the gate is unchanged — that is where a reader would
    actually see the same story twice, which is what the anti-rehash directive
    (email-12139) is about.
    """
    if blocker is not None and _article_audience(item) != _article_audience(blocker):
        return None

    shared_refs = {
        str(ref).upper()
        for ref in (arc_dup.get("shared_experiment_refs") or [])
        if str(ref).strip()
    }
    if blocker is not None:
        shared_refs |= _extract_k_ids_from_item(item) & _extract_k_ids_from_item(blocker)
    if shared_refs:
        return f"shared_experiment_refs={sorted(shared_refs)}"

    if blocker is None:
        return None
    shared_sources = _release_data_source_tokens(item) & _release_data_source_tokens(blocker)
    if shared_sources:
        return f"shared_data_sources={sorted(shared_sources)}"
    return None


def _log_release_dedup_decision(
    storage_dir: str,
    *,
    target_id: object,
    decision: str,
    reason: str,
    matched_id: object | None = None,
) -> None:
    """Append release gate decisions; logging is fail-open."""
    path = project_path(storage_dir, "logs", "dedup_decisions.jsonl")
    guard_canonical_write(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate": "release_pool_arc_dedup",
            "target_id": target_id,
            "matched_id": matched_id,
            "decision": decision,
            "reason": reason,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        _warn_release_pool("release arc-dedup audit log failed", exc)


def _narrative_cluster_from_text(text: str) -> str | None:
    for cluster, pattern in _NARRATIVE_CLUSTER_PATTERNS.items():
        if pattern.search(text or ""):
            return cluster
    return None


def _knowledge_experiment_clusters(storage_dir: str) -> dict[str, str]:
    knowledge = load_json(project_path(storage_dir, "memory", "knowledge.json"), [])
    out: dict[str, str] = {}
    if not isinstance(knowledge, list):
        return out
    for item in knowledge:
        if not isinstance(item, dict):
            continue
        text = "\n".join(
            str(v)
            for v in (
                item.get("title"),
                item.get("category"),
                item.get("content"),
                " ".join(str(t) for t in (item.get("tags") or [])) if isinstance(item.get("tags"), list) else "",
            )
            if v
        )
        cluster = _narrative_cluster_from_text(text)
        if cluster is None:
            continue
        refs: set[str] = set()
        for key in ("experiment_id", "k_id"):
            value = item.get(key)
            if isinstance(value, str) and re.fullmatch(r"K\d+", value.upper()):
                refs.add(value.upper())
        for key in ("experiment_ids", "related_experiments", "source_experiments"):
            value = item.get(key)
            if isinstance(value, list):
                refs.update(str(v).upper() for v in value if re.fullmatch(r"K\d+", str(v).upper()))
        evidence = item.get("evidence") or []
        if isinstance(evidence, list):
            for ev in evidence:
                refs.update(match.upper() for match in re.findall(r"\bK\d+\b", str(ev), flags=re.I))
        if not refs:
            refs.update(match.upper() for match in re.findall(r"\bK\d+\b", text, flags=re.I))
        for ref in refs:
            out.setdefault(ref, cluster)
    return out


def _article_series(item: dict) -> str | None:
    """Registered series this article belongs to (config/article_series.json is SoT).

    A serialized 專題 (無人載具 EP0..EP-Final, 迷思實驗室, 事件溫度計) is ONE narrative
    unit that ships as N chapters — not N articles flooding one cluster. Counting its
    episodes individually deadlocks the release pool the moment 2 of them are live:
    the cluster locks, the remaining episodes can never be released, and the pool goes
    silently to zero-releasable (boss Telegram msg 662-664, 2026-07-13; a whole series
    sat in the pool while the freshness dead-man switch fired).
    """
    try:
        from volpred.publisher.arc_dedup import _series_of
    except Exception as exc:  # noqa: BLE001
        _warn_release_pool("series registry unavailable — series unit-collapse off", exc)
        return None
    return _series_of(str(item.get("title") or ""))


def _series_release_pacing(spec: dict) -> dict | None:
    """Release-pacing policy for a registered series; None = unpaced.

    An explicit `release_pacing` object in the registry wins. Episodic series
    (`no_episode_numbers` is false) default to ordered, one-episode-per-24h pacing:
    a serialized 專題 is a multi-day arc by design, not a backlog to drain at pool
    cadence. 2026-07-14 incident: the moment the cluster-gate exemption (2bd97c1f7)
    removed the deadlock, it also removed the only brake — the 6-episode 無人載具
    series burned through in ~20 hours, EP4 before EP3.
    """
    raw = spec.get("release_pacing")
    if isinstance(raw, dict):
        if raw.get("disabled") is True:
            return None
        return {
            "min_hours_between_episodes": float(
                raw.get("min_hours_between_episodes", 24.0)
            ),
            "ordered": bool(
                raw.get("ordered", spec.get("no_episode_numbers") is False)
            ),
        }
    if spec.get("no_episode_numbers") is False:
        return {"min_hours_between_episodes": 24.0, "ordered": True}
    return None


def _item_paced_series(item: dict) -> str | None:
    """Registry key of the item's series when that series has release pacing, else None."""
    try:
        from volpred.publisher.arc_dedup import series_spec_for_title
    except Exception as exc:  # noqa: BLE001
        _warn_release_pool("series registry unavailable — series pacing off", exc)
        return None
    resolved = series_spec_for_title(str(item.get("title") or ""))
    if not resolved:
        return None
    series_key, spec = resolved
    return series_key if _series_release_pacing(spec) else None


def _series_pacing_hold(item: dict, feed: list[dict], now: datetime) -> dict | None:
    """Hold record if a registered series' pacing blocks this episode now, else None.

    Two independent holds, both derived from the registry members list (whose array
    order is the canonical episode order for episodic series):
    - min_gap: another episode of the same series published less than
      `min_hours_between_episodes` ago.
    - out_of_order: an earlier episode is still pending (draft/scheduled) in the feed.
      Members absent from the feed or deliberately retired (`unpublished`) do not block.
    """
    try:
        from volpred.publisher.arc_dedup import series_spec_for_title
    except Exception as exc:  # noqa: BLE001
        _warn_release_pool("series registry unavailable — series pacing off", exc)
        return None
    resolved = series_spec_for_title(str(item.get("title") or ""))
    if not resolved:
        return None
    series_key, spec = resolved
    pacing = _series_release_pacing(spec)
    if not pacing:
        return None
    members = [str(m) for m in (spec.get("members") or [])]
    by_id = {str(a.get("id") or ""): a for a in feed}
    base = {
        "id": item.get("id"),
        "title": item.get("title"),
        "series": series_key,
        "pacing": pacing,
    }

    latest: datetime | None = None
    for mid in members:
        member = by_id.get(mid)
        if not member or member.get("status") != "published":
            continue
        ts = _parse_datetime(member.get("published_at"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    if latest is not None:
        gap = timedelta(hours=pacing["min_hours_between_episodes"])
        next_eligible = latest + gap
        if now < next_eligible:
            return {**base, "reason": "min_gap", "next_eligible_at": next_eligible.isoformat()}

    if pacing["ordered"] and members:
        item_id = str(item.get("id") or "")
        for mid in members:
            member = by_id.get(mid)
            if member is None:
                continue  # not in feed yet — an unwritten episode must not deadlock the rest
            status = str(member.get("status") or "")
            if status in {"published", "unpublished"}:
                continue
            if mid != item_id:
                return {**base, "reason": "out_of_order", "next_in_series": mid}
            break
    return None


def _article_narrative_cluster(item: dict, k_cluster: dict[str, str]) -> str | None:
    title = str(item.get("title") or "")
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    topic_cluster = classify_topic_cluster(title, tags, "")
    if topic_cluster:
        return topic_cluster
    # Keep article-side cluster detection title/tags/ref-based. Body scanning is
    # too broad for release ordering and would preempt the stricter
    # release_theme_flood gate on generic articles that merely mention a model.
    text = "\n".join(str(v) for v in (title, " ".join(str(t) for t in tags)) if v)
    text_cluster = _narrative_cluster_from_text(text)
    if text_cluster:
        return text_cluster
    for ref in sorted(_extract_k_ids_from_item(item)):
        if ref in k_cluster:
            return k_cluster[ref]
    return None


def _recent_narrative_cluster_pressure(
    feed: list[dict],
    *,
    k_cluster: dict[str, str],
) -> dict:
    recent = sorted(
        [
            item
            for item in feed
            if item.get("status") == "published"
            and _article_audience(item) in _RELEASE_DEDUP_AUDIENCES
            and item.get("published_at")
        ],
        key=lambda item: str(item.get("published_at") or ""),
        reverse=True,
    )[:_RELEASE_LAST_N_CLUSTER_WINDOW]
    # A registered series counts ONCE toward cluster pressure, however many of its
    # episodes are in the window (see _article_series).
    clusters: list[str] = []
    seen_series: set[str] = set()
    for item in recent:
        cluster = _article_narrative_cluster(item, k_cluster)
        if not cluster:
            continue
        series = _article_series(item)
        if series:
            if series in seen_series:
                continue
            seen_series.add(series)
        clusters.append(cluster)
    counts = Counter(clusters)
    blocked = sorted(
        cluster
        for cluster, count in counts.items()
        if count >= _RELEASE_LAST_N_CLUSTER_THRESHOLD
    )
    return {
        "window": _RELEASE_LAST_N_CLUSTER_WINDOW,
        "threshold": _RELEASE_LAST_N_CLUSTER_THRESHOLD,
        "clusters": clusters,
        "counts": dict(counts),
        "blocked_clusters": blocked,
        "recent_ids": [item.get("id") for item in recent],
    }


def release_cluster_planner_state(*, storage_dir: str = "storage") -> dict:
    """What the REFILL side needs to know about the release-side cluster gate.

    2026-07-13 layer-2 rootfix (boss msg 660「從底層徹底處理」). Layer 1 stopped a
    registered series from locking itself out of release. But refill still topped the
    pool up by COUNT alone, so it could queue N article tasks that all land in one
    cluster — a pool that looks stocked and is entirely unreleasable. Refill must plan
    against the same gate release enforces, so this exposes that gate's own state
    instead of letting refill grow a second cluster heuristic (anti-stacking: the gate
    is defined here, in one place).

    `pipeline_counts` is the cluster composition of the drafts already waiting, i.e.
    what a new task would be piling onto.
    """
    feed = load_feed(storage_dir)
    k_cluster = _knowledge_experiment_clusters(storage_dir)
    pressure = _recent_narrative_cluster_pressure(feed, k_cluster=k_cluster)
    pipeline: Counter = Counter()
    for item in feed:
        if not isinstance(item, dict) or item.get("status") != "draft":
            continue
        cluster = _article_narrative_cluster(item, k_cluster)
        if cluster:
            pipeline[cluster] += 1
    return {
        "window": pressure["window"],
        "threshold": pressure["threshold"],
        "blocked_clusters": list(pressure["blocked_clusters"]),
        "recent_counts": dict(pressure["counts"]),
        "pipeline_counts": dict(pipeline),
    }


def make_narrative_cluster_classifier(*, storage_dir: str = "storage"):
    """Classify a not-yet-written article (title/tags/K-ids) into a narrative cluster.

    Same code path release uses on real feed items, so refill's idea of "what cluster
    will this article land in" cannot drift from the gate that later judges it. Loads
    the knowledge K→cluster map ONCE (knowledge.json is large) and returns a closure —
    callers classify many candidates without re-reading it.
    """
    k_cluster = _knowledge_experiment_clusters(storage_dir)

    def classify(
        title: str, tags: list | None = None, k_ids: list | None = None
    ) -> str | None:
        item = {"title": str(title or ""), "tags": list(tags or [])}
        cluster = _article_narrative_cluster(item, k_cluster)
        if cluster:
            return cluster
        for kid in sorted(str(k).upper() for k in (k_ids or [])):
            if kid in k_cluster:
                return k_cluster[kid]
        return None

    return classify


# Theme-flood gate: content-bigram catches near-COPIES, but the 2026-06-15
# incident was same-THEME-different-wording (36 "complex model doesn't beat
# simple" articles, bigram Jaccard < 0.45 between them). A theme signature +
# recency cap throttles saturated themes regardless of wording. Add a theme
# here when a topic visibly over-publishes; cap is per rolling window.
_THEME_CAP = 3
_RELEASE_AUDIT_MATERIALIZE_THRESHOLD = 3
_RELEASE_INTERNAL_TAGS = {"codex-24h-rule-reviewed"}
_SATURATED_THEMES = {
    "model_complexity": re.compile(
        r"模型.{0,12}(擂台|投票|加在一起|更聰明|花俏|更準|沒贏|沒更準|只贏|不能算真的贏|疊|複雜|淘汰)"
        r"|擂台賽|越複雜|複雜.{0,6}(不一定|沒|更強|更厲害|更準)|老方法|沒被淘汰|加更多數學|更花俏|愈花俏"
        r"|模型.{0,6}(投票|加權|ensemble|集成)|加在一起.{0,6}(打敗|贏|更強)"
    ),
    "vix_sufficiency": re.compile(r"VIX.{0,14}(就夠|夠不夠|足夠|充分|多餘|還需要|是不是最|打敗|比.{0,4}準)|只看\s*VIX"),
    "vt_strategy": re.compile(r"波動率目標|目標波動率|vol[\s-]?target|VT\s*(策略|參數|保險|成本)"),
    "fifty_fifty": re.compile(r"50/50|股(票)?加黃金|SPY.{0,6}GLD|股債(金|再平衡|配置)"),
    "overnight_gap": re.compile(r"夜盤|隔夜|overnight|跳空|盤前|盤後.{0,4}波動"),
}


def _release_theme_flood(item: dict, recent_pub: list[dict]) -> dict | None:
    """Skip if `item` belongs to a saturated theme that already has >= _THEME_CAP
    articles in the recent window."""
    text = str(item.get("title") or "") + "\n" + str(item.get("content") or item.get("description") or "")
    for name, rx in _SATURATED_THEMES.items():
        if not rx.search(text):
            continue
        cnt = sum(
            1
            for o in recent_pub
            if o.get("id") != item.get("id")
            and rx.search(str(o.get("title") or "") + "\n" + str(o.get("content") or o.get("description") or ""))
        )
        if cnt >= _THEME_CAP:
            return {"theme": name, "recent_count": cnt}
    return None


def _safe_release_task_suffix(value: str | None, *, fallback: str = "draft") -> str:
    suffix = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "").strip()).strip("_").lower()
    return (suffix or fallback)[:80]


def _build_release_audit_task_description(item: dict, audit_issues: list[str], skip_count: int) -> str:
    item_id = str(item.get("id") or "").strip() or "(missing id)"
    title = " ".join(str(item.get("title") or "(untitled)").split())
    issues = "\n".join(f"- {issue}" for issue in audit_issues)
    return (
        f"release_pool skipped draft `{item_id}` {skip_count} times because the "
        "general-audience audit failed.\n\n"
        f"Title: {title}\n\n"
        "Issues:\n"
        f"{issues}\n\n"
        "Fix the draft through the publisher/feed-publisher workflow or a source "
        "rewrite. Do not hand-edit historical feed data to bypass the audit."
    )


def _relocate_release_internal_tags(item: dict, *, now: datetime) -> list[str]:
    """Move workflow-only tags out of public tags before release audit."""
    raw_tags = item.get("tags")
    if not isinstance(raw_tags, list):
        return []

    public_tags = []
    moved = []
    for tag in raw_tags:
        tag_text = str(tag).strip()
        if tag_text in _RELEASE_INTERNAL_TAGS:
            moved.append(tag_text)
            continue
        public_tags.append(tag)

    if not moved:
        return []

    item["tags"] = public_tags
    details = item.get("details")
    if not isinstance(details, dict):
        details = {}
        item["details"] = details

    existing = details.get("release_internal_tags")
    if not isinstance(existing, list):
        existing = []
    merged = []
    for tag in [*existing, *moved]:
        tag_text = str(tag).strip()
        if tag_text and tag_text not in merged:
            merged.append(tag_text)
    details["release_internal_tags"] = merged
    details["release_internal_tags_moved_at"] = now.isoformat()
    if "codex-24h-rule-reviewed" in moved:
        details["codex_24h_rule_reviewed"] = True
    return moved


def _mark_release_audit_resolved(item: dict, *, now: datetime) -> None:
    details = item.get("details")
    if not isinstance(details, dict):
        return
    prior_issues = details.pop("release_audit_issues", None)
    if prior_issues:
        details["release_audit_resolved_issues"] = prior_issues
    if prior_issues or details.get("release_audit_task_id"):
        details["release_audit_status"] = "resolved"
        details["release_audit_resolved_at"] = now.isoformat()


def _materialize_release_audit_fix_task(
    *,
    item: dict,
    audit_issues: list[str],
    skip_count: int,
    storage_dir: str,
    now: datetime,
) -> dict:
    item_id = str(item.get("id") or "").strip()
    suffix_source = item_id or str(item.get("title") or "")
    task_id = f"platform_ops_release_audit_fix_{_safe_release_task_suffix(suffix_source)}"
    next_tasks_path = project_path(storage_dir, "next_tasks.json")
    guard_canonical_write(next_tasks_path)
    next_tasks_path.parent.mkdir(parents=True, exist_ok=True)
    if not next_tasks_path.exists():
        next_tasks_path.write_text("[]\n", encoding="utf-8")

    with next_tasks_path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json is not a list")

            prior = [
                task
                for task in tasks
                if isinstance(task, dict)
                and (
                    task.get("id") == task_id
                    or (
                        task.get("source") == "release_pool_audit_skip_materializer"
                        and str(task.get("article_id") or "") == item_id
                        and item_id
                    )
                )
            ]
            open_task = next(
                (
                    task
                    for task in prior
                    if str(task.get("status") or "") in _RELEASE_AUDIT_OPEN_STATUSES
                ),
                None,
            )

            if open_task is not None:
                # Write-once was the bug: the task was filed at its opening
                # priority and never learned it had gone on blocking. A
                # finished article sat behind the P1 queue for 20-30h while
                # its skip count climbed to 24 and nothing in the pool said
                # so. Refresh the evidence and escalate while it is open.
                refreshed = _refresh_release_audit_task(
                    open_task, item, audit_issues, skip_count
                )
                if refreshed:
                    write_tasks_to_handle(fh, tasks)
                return {
                    "created": False,
                    "reason": "task_already_exists",
                    "task_id": open_task.get("id") or task_id,
                    "refreshed": refreshed,
                    "priority": open_task.get("priority"),
                }

            if prior:
                # Every prior attempt is closed, yet the audit is still skipping
                # this article: the fix did not hold. Matching on article_id
                # alone regardless of status meant one closed task suppressed
                # re-materialization forever, leaving a still-blocked article
                # with no owner at all. File the next round under its own id.
                task_id = f"{task_id}_r{len(prior) + 1}"

            title_text = " ".join(str(item.get("title") or item_id or "untitled draft").split())
            task = {
                "id": task_id,
                "title": f"Fix release-pool audit blockers: {title_text[:80]}",
                "description": _build_release_audit_task_description(item, audit_issues, skip_count),
                "task_type": "platform_ops",
                "dispatch_lane": "agent",
                "priority": _release_audit_task_priority(skip_count),
                "status": "pending",
                "source": "release_pool_audit_skip_materializer",
                "tags": ["release_pool", "audit_skip", "platform_ops"],
                "created_at": now.isoformat(),
                "article_id": item_id,
                "release_audit_skipped_count": skip_count,
                "release_audit_issues": audit_issues,
            }
            validate_task_status(task["status"])
            normalize_task_priority(task)
            tasks.append(task)
            write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    return {"created": True, "task_id": task_id}


# A blocked draft is a finished article the readers never see, so it opens at P2
# rather than the old hardcoded P3 — but not at P1, which would let routine gate
# misses dilute the lane reserved for genuinely urgent work. It earns P1 by
# persisting: at the 240-minute release cadence, 6 skips is a full day during
# which the cadence had a slot to fill and could not fill it.
RELEASE_AUDIT_TASK_OPEN_PRIORITY = 2
RELEASE_AUDIT_TASK_URGENT_PRIORITY = 1
RELEASE_AUDIT_TASK_URGENT_SKIPS = 6

# Escalation applies only to tasks still awaiting work. A closed task must not be
# resurrected by a late audit tick; the audit would be reopening someone else's
# completed decision.
_RELEASE_AUDIT_OPEN_STATUSES = frozenset({"pending", "in_progress", "blocked"})


def _release_audit_task_priority(skip_count: int) -> int:
    """Priority for a release-blocked draft, as a function of how long it stuck."""
    try:
        skips = int(skip_count or 0)
    except (TypeError, ValueError):
        skips = 0
    if skips >= RELEASE_AUDIT_TASK_URGENT_SKIPS:
        return RELEASE_AUDIT_TASK_URGENT_PRIORITY
    return RELEASE_AUDIT_TASK_OPEN_PRIORITY


def _refresh_release_audit_task(
    task: dict,
    item: dict,
    audit_issues: list,
    skip_count: int,
) -> bool:
    """Re-state an existing blocker task's evidence and escalate if it persists.

    Returns True when the task changed, so the caller only rewrites the file
    when there is something to write. Priority moves one way only: a task the
    owner deliberately raised must not be pushed back down by a routine tick.
    """
    if str(task.get("status") or "") not in _RELEASE_AUDIT_OPEN_STATUSES:
        return False

    changed = False
    if task.get("release_audit_skipped_count") != skip_count:
        task["release_audit_skipped_count"] = skip_count
        changed = True
    if task.get("release_audit_issues") != audit_issues:
        # The blocker itself can change (a lazypack lands, anti-AI style trips
        # instead); a stale issue list sends the next fire at the wrong problem.
        task["release_audit_issues"] = audit_issues
        changed = True

    description = _build_release_audit_task_description(item, audit_issues, skip_count)
    if task.get("description") != description:
        task["description"] = description
        changed = True

    escalated = _release_audit_task_priority(skip_count)
    try:
        current = int(task.get("priority"))
    except (TypeError, ValueError):
        current = None
    if current is None or escalated < current:
        task["priority"] = escalated
        normalize_task_priority(task)
        changed = True

    return changed


def _next_release_audit_skip_count(details: dict) -> int:
    try:
        previous = int(details.get("release_audit_skipped_count") or 0)
    except (TypeError, ValueError):
        previous = 0
    return max(previous, 0) + 1


def _release_dedup_flag_active(item: dict, *, now: datetime) -> bool:
    d = item.get("details")
    if not (isinstance(d, dict) and bool(d.get("release_dedup_skipped"))):
        return False
    if d.get("release_dedup_gate_version") != _RELEASE_DEDUP_GATE_VERSION:
        return False  # verdict predates the current gate logic -> re-evaluate
    # Dedup flags expire with the dedup window. Without this TTL, a draft can
    # be permanently excluded from the release pool after a one-time skip.
    flagged_at = d.get("release_dedup_skipped_at")
    if not flagged_at:
        return False  # legacy flag w/o timestamp -> re-evaluate
    try:
        flagged_dt = datetime.fromisoformat(flagged_at)
        # Short anti-thrash cooldown, NOT the full dedup window — see
        # _RELEASE_DEDUP_FLAG_TTL_DAYS. After the cooldown the draft is
        # re-evaluated fresh by the live dedup gates each release run.
        return (now - flagged_dt) < timedelta(days=_RELEASE_DEDUP_FLAG_TTL_DAYS)
    except (ValueError, TypeError) as exc:
        from .diagnostics import warn

        warn(
            "release_pool",
            "release_dedup_skipped_at parse failed; re-evaluating draft",
            item_id=str(item.get("id") or ""),
            release_dedup_skipped_at=str(flagged_at),
            err=f"{type(exc).__name__}: {exc}",
        )
        return False


def _release_publish_throttle(
    item: dict,
    feed: list[dict],
    *,
    now: datetime,
    storage_dir: str,
    route: str,
) -> dict | None:
    """Return an audit summary when a draft-to-published transition is blocked.

    Draft ingestion intentionally bypasses the publisher throttle because it is
    not reader-facing. Every release-pool path must therefore call the gate at
    the actual status transition, including explicit ``pub_id`` releases and
    the drought override. The published copy prevents the draft-ingestion
    bypass from short-circuiting this release-time check.
    """
    from volpred.publisher.throttle import (
        PublishThrottleError,
        check_publish_throttle,
    )

    candidate = dict(item)
    candidate["status"] = "published"
    try:
        check_publish_throttle(
            candidate,
            feed,
            storage_dir=storage_dir,
            now=now,
        )
    except PublishThrottleError as exc:
        blocked = {
            "id": item.get("id"),
            "title": item.get("title"),
            "route": route,
            "previous_id": exc.previous_id,
            "gap_minutes": exc.gap_minutes,
            "threshold_minutes": exc.threshold_minutes,
        }
        print(
            f"  [release_pool] THROTTLE-SKIP {item.get('id')} — "
            f"gap={exc.gap_minutes}min < {exc.threshold_minutes}min "
            f"after {exc.previous_id}; kept unpublished."
        )
        return blocked
    return None


def _write_feed_locked(feed: list[dict], *, storage_dir: str) -> None:
    """Atomically replace feed.json; caller must hold ``publisher_feed`` lock."""
    path = _feed_path(storage_dir)
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.release-pool.tmp")
    try:
        tmp_path.write_text(
            json.dumps(feed, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        parsed = json.loads(tmp_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, list):
            raise ValueError("release-pool feed write must contain a list")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _atomic_promote_release_item(
    item: dict,
    *,
    now: datetime,
    released_at: str,
    storage_dir: str,
    route: str,
    expected_item: dict,
    require_reader_drought: bool = False,
) -> dict:
    """Fresh-read, throttle, promote and persist one feed entry under one lock.

    The lock boundary is deliberately short: remote sync, notification and live
    verification stay outside it. This closes both release-vs-release and
    release-vs-Publisher TOCTOU races without holding the canonical feed lock
    across network I/O.
    """
    from volpred.ops.shared_lock import shared_state_lock

    item_id = str(item.get("id") or "")
    with shared_state_lock("publisher_feed", storage_dir=storage_dir):
        fresh_feed = load_feed(storage_dir)
        index = next(
            (idx for idx, current in enumerate(fresh_feed) if current.get("id") == item_id),
            None,
        )
        if index is None:
            return {"outcome": "conflict", "id": item_id, "reason": "missing_from_fresh_feed"}

        current = fresh_feed[index]
        current_status = str(current.get("status") or "")
        if current_status not in {"draft", "scheduled"}:
            return {
                "outcome": "conflict",
                "id": item_id,
                "reason": f"fresh_status:{current_status or 'missing'}",
            }
        if current != expected_item:
            return {
                "outcome": "conflict",
                "id": item_id,
                "reason": "fresh_item_changed_since_selection",
            }

        if require_reader_drought:
            reader_times = [
                stamp
                for stamp in (
                    _parse_datetime(entry.get("published_at"))
                    for entry in fresh_feed
                    if _is_reader_facing_published(entry)
                )
                if stamp is not None
            ]
            newest_reader = max(reader_times) if reader_times else None
            fresh_gap_hours = (
                (now - newest_reader).total_seconds() / 3600.0
                if newest_reader is not None
                else None
            )
            if fresh_gap_hours is not None and fresh_gap_hours <= _RELEASE_DROUGHT_HOURS:
                return {
                    "outcome": "condition_cleared",
                    "id": item_id,
                    "reason": "reader_drought_resolved_before_promotion",
                    "gap_hours": round(fresh_gap_hours, 2),
                }

            override_times = [
                stamp
                for stamp in (
                    _parse_datetime((entry.get("details") or {}).get("release_drought_override_at"))
                    for entry in fresh_feed
                    if isinstance(entry.get("details"), dict)
                )
                if stamp is not None
            ]
            last_override = max(override_times) if override_times else None
            if (
                last_override is not None
                and (now - last_override).total_seconds() / 3600.0
                < _RELEASE_DROUGHT_HOURS
            ):
                return {
                    "outcome": "condition_cleared",
                    "id": item_id,
                    "reason": "fresh_drought_override_inside_anti_thrash_window",
                    "last_override_at": last_override.isoformat(),
                }

        prospective = {**current, **item}
        prospective["status"] = "published"
        prospective["published_at"] = released_at
        throttle_block = _release_publish_throttle(
            prospective,
            fresh_feed,
            now=now,
            storage_dir=storage_dir,
            route=route,
        )
        if throttle_block is not None:
            return {"outcome": "throttled", "block": throttle_block}

        fresh_feed[index] = prospective
        _write_feed_locked(fresh_feed, storage_dir=storage_dir)
        persisted = load_feed(storage_dir)
        persisted_item = next(
            (entry for entry in persisted if entry.get("id") == item_id),
            None,
        )
        if not isinstance(persisted_item, dict) or persisted_item.get("status") != "published":
            raise RuntimeError(
                f"release-pool promotion read-back failed: id={item_id} status not published"
            )
        return {"outcome": "promoted", "item": prospective}


def _atomic_patch_feed_entries(
    patches: list[dict],
    *,
    storage_dir: str,
) -> list[dict]:
    """Apply small, status-guarded feed patches without stale whole-file writes."""
    if not patches:
        return []
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock("publisher_feed", storage_dir=storage_dir):
        fresh_feed = load_feed(storage_dir)
        by_id = {
            str(entry.get("id") or ""): entry
            for entry in fresh_feed
            if isinstance(entry, dict)
        }
        changed = False
        conflicts: list[dict] = []
        for patch in patches:
            patch_id = str(patch.get("id") or "")
            target = by_id.get(patch_id)
            if target is None:
                conflicts.append(
                    {"outcome": "conflict", "id": patch_id, "reason": "missing_from_fresh_feed"}
                )
                continue
            expected_status = patch.get("expected_status")
            if expected_status is not None and target.get("status") != expected_status:
                conflicts.append(
                    {
                        "outcome": "conflict",
                        "id": patch_id,
                        "reason": f"fresh_status:{target.get('status') or 'missing'}",
                    }
                )
                continue
            expected_item = patch.get("expected_item")
            if expected_item is not None and target != expected_item:
                conflicts.append(
                    {
                        "outcome": "conflict",
                        "id": patch_id,
                        "reason": "fresh_item_changed_before_metadata_patch",
                    }
                )
                continue
            for key, value in (patch.get("fields") or {}).items():
                if (
                    key == "details"
                    and expected_item is None
                    and isinstance(target.get(key), dict)
                    and isinstance(value, dict)
                ):
                    target[key] = {**target[key], **value}
                else:
                    target[key] = value
                changed = True
        if changed:
            _write_feed_locked(fresh_feed, storage_dir=storage_dir)
        return conflicts


def _maybe_drought_release(
    *,
    blocked_items: list[dict],
    feed: list[dict],
    recent_pub: list[dict],
    now: datetime,
    released_at: str,
    publisher: Publisher,
    storage_dir: str,
    released: list[dict],
    publish_throttled: list[dict] | None = None,
    expected_items_by_id: dict[str, dict] | None = None,
) -> dict | None:
    """Force-release exactly ONE dedup-blocked draft when the feed is in a
    reader-facing drought.

    Called only when the normal release pass produced nothing. `blocked_items`
    is every content-clean reader-facing draft currently held back by dedup —
    both those live-blocked in this run's loop and those excluded at selection
    by the dedup-cooldown flag. Fail-open stance per
    .claude/rules/dedup-gate-audit.md: an invisible content gap (Mission #1/#5)
    is worse than an occasional borderline-similar article.

    Drought = the newest genuinely reader-facing published article
    (`_is_reader_facing_published`) is older than `_RELEASE_DROUGHT_HOURS`
    (or there is none at all). Anti-thrash: one override per drought event —
    skipped if the most recent `release_drought_override_at` stamp in the feed
    is still inside the threshold window. The released draft is the LEAST
    dup-like blocked one: lowest max bigram Jaccard vs recently-published
    reader-facing articles, ties broken by newest created_at.

    Note: the pool is restricted to dedup-blocked drafts (content-clean, only
    blocked for surface similarity) — audit-blocked drafts (forbidden stats
    terminology / tag-cap) are intentionally NOT eligible, so the breaker can
    never publish low-quality content to escape a drought.

    Returns an audit dict on override, else None. Appends the released summary
    to `released` so the caller's existing persist/sync/verify path handles it.
    """
    from .diagnostics import warn

    if not blocked_items:
        return None

    # 2026-06-29 (boss email-12164): never force-release a draft that is an arc-dup
    # of a CURRENTLY-PUBLISHED article — that republishes a near-verbatim rehash of
    # live content, directly contradicting the anti-rehash directive (email-12139).
    # Borderline dedup-blocked drafts (similar to recent but NOT an exact
    # published-dup) STAY eligible, so the breaker still relaxes dedup to avoid a
    # drought (email-12153: the dedup standard is not absolute) — it just won't
    # republish a live article. If excluding leaves nothing, signal drought
    # (return None) so fresh content is generated instead of a guaranteed rehash.
    _published_ids = {a.get("id") for a in feed if a.get("status") == "published"}
    non_rehash = [
        it
        for it in blocked_items
        if (it.get("details") or {}).get("release_arc_dedup_of") not in _published_ids
    ]
    if not non_rehash:
        warn(
            "release_drought",
            "all drought-eligible drafts are arc-dups of published articles; "
            "withholding rehash + signalling for fresh content (boss anti-rehash)",
            blocked_pool=len(blocked_items),
        )
        return None
    blocked_items = non_rehash

    # Gap to the newest genuinely reader-facing published article.
    reader_times = [
        t
        for t in (
            _parse_datetime(a.get("published_at"))
            for a in feed
            if _is_reader_facing_published(a)
        )
        if t is not None
    ]
    newest = max(reader_times) if reader_times else None
    gap_hours = (now - newest).total_seconds() / 3600.0 if newest is not None else None
    in_drought = gap_hours is None or gap_hours > _RELEASE_DROUGHT_HOURS
    if not in_drought:
        return None

    # Anti-thrash: at most one override per drought window.
    override_times = [
        t
        for t in (
            _parse_datetime((a.get("details") or {}).get("release_drought_override_at"))
            for a in feed
            if isinstance(a.get("details"), dict)
        )
        if t is not None
    ]
    last_override = max(override_times) if override_times else None
    if (
        last_override is not None
        and (now - last_override).total_seconds() / 3600.0 < _RELEASE_DROUGHT_HOURS
    ):
        warn(
            "release_drought",
            "drought detected but a prior override is still inside the anti-thrash window; skipping",
            gap_hours=round(gap_hours, 2) if gap_hours is not None else None,
            last_override_at=last_override.isoformat(),
        )
        return None

    # Pick the LEAST dup-like blocked draft: lowest max-Jaccard; ties -> newest
    # created_at. Two stable sorts (created_at desc, then jaccard asc) realise
    # the (jaccard asc, created_at desc) ordering.
    scored = [
        (_release_max_jaccard(it, recent_pub), str(it.get("created_at") or ""), it)
        for it in blocked_items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    scored.sort(key=lambda x: x[0])
    chosen_jaccard, _chosen_created, chosen = scored[0]

    gap_text = f"{gap_hours:.2f}h" if gap_hours is not None else "no prior reader-facing article"
    reason = (
        f"reader-facing drought ({gap_text} > {_RELEASE_DROUGHT_HOURS}h threshold); "
        f"force-released least dup-like blocked draft (max Jaccard={chosen_jaccard})"
    )

    # Build the intended override on a copy. A fresh-read drought revalidation
    # and the rhythm throttle still have to pass atomically before any stamp is
    # committed to the canonical feed.
    chosen_for_release = dict(chosen)
    details = chosen.get("details")
    details = dict(details) if isinstance(details, dict) else {}
    chosen_for_release["details"] = details
    details["release_drought_override"] = True
    details["release_drought_override_at"] = now.isoformat()
    details["release_drought_override_reason"] = reason
    # We are intentionally publishing this draft; clear the dedup COOLDOWN flag
    # so the now-published item carries a clean state (the override reason and
    # the original release_dedup_of/jaccard audit fields remain for provenance).
    details.pop("release_dedup_skipped", None)

    chosen_id = str(chosen.get("id") or "")
    expected_chosen = (expected_items_by_id or {}).get(chosen_id, deepcopy(chosen))
    promotion = _atomic_promote_release_item(
        chosen_for_release,
        now=now,
        released_at=released_at,
        storage_dir=storage_dir,
        route="drought_override",
        require_reader_drought=True,
        expected_item=expected_chosen,
    )
    if promotion["outcome"] == "throttled":
        if publish_throttled is not None:
            publish_throttled.append(promotion["block"])
        return None
    if promotion["outcome"] != "promoted":
        print(
            f"  [release_pool] DROUGHT-NOOP {chosen.get('id')} — "
            f"{promotion.get('reason')}; fresh condition no longer authorizes release."
        )
        return None

    chosen.clear()
    chosen.update(promotion["item"])
    warn(
        "release_drought",
        "forcing one release to break a reader-facing publishing drought",
        chosen_id=str(chosen.get("id") or ""),
        gap_hours=round(gap_hours, 2) if gap_hours is not None else None,
        max_jaccard=chosen_jaccard,
        blocked_pool=len(blocked_items),
    )
    print(f"  [release_pool] DROUGHT-OVERRIDE {chosen.get('id')} — {reason}; releasing.")

    article_slug = str(chosen.get("id", ""))
    # Publish finalization mirrors the normal release loop (sync → failed-sync
    # ledger → answer linked questions → notify). Kept inline (not shared) so a
    # change to the hot normal path can't silently alter this rare path.
    sync_ok = False
    try:
        sync_ok = bool(sync_article(chosen, storage_dir=publisher.reports_dir.parent))
    except Exception as exc:
        warn(
            "release_drought",
            "sync_article failed during drought override",
            article=article_slug,
            err=f"{type(exc).__name__}: {exc}",
        )
        print(f"  [release_pool] sync_article exception for {article_slug}: {exc}")
    released.append(
        {
            "id": article_slug,
            "title": chosen.get("title"),
            "status": chosen.get("status"),
            "published_at": chosen.get("published_at"),
            "supabase_synced": bool(sync_ok),
            "drought_override": True,
        }
    )
    if not sync_ok:
        failed_path = publisher.reports_dir.parent / ".failed_supabase_syncs.json"
        try:
            failed = json.loads(failed_path.read_text()) if failed_path.exists() else []
            if not isinstance(failed, list):
                raise ValueError(".failed_supabase_syncs.json must contain a list")
        except Exception as exc:
            _warn_release_pool("failed Supabase sync ledger unreadable; recreating", exc)
            failed = []
        if article_slug not in failed:
            failed.append(article_slug)
            failed_path.write_text(json.dumps(failed))
        print(
            f"  [release_pool] WARN Supabase sync failed for {article_slug} -- "
            f"recorded to .failed_supabase_syncs.json. "
            f"Run scripts/supabase_sync.py sync-article {article_slug} to retry."
        )
    _mark_questions_answered_on_publish(article_slug)
    publisher._notify_article_published(chosen, reason="release_pool_drought")

    return {
        "id": article_slug,
        "title": chosen.get("title"),
        "gap_hours": round(gap_hours, 2) if gap_hours is not None else None,
        "max_jaccard": chosen_jaccard,
        "blocked_pool_size": len(blocked_items),
        "reason": reason,
    }


def _lazypack_job_state(article_id: str, storage_dir: str = "storage") -> tuple[str, str | None]:
    """What the lazypack lane actually knows about ``article_id``.

    Returns ``(state, job_id)`` where state is one of ``missing`` (no job was
    ever queued), ``queued``/``running``/``failed``/``completed``.

    2026-07-19 deadlock (boss 20:14): the gate used to *assume* a job existed
    and print `lazypack-<id>` as the thing to go inspect. For mile_21e45133 and
    mile_47c4bc3e no such job was ever enqueued, so the message pointed at a
    file that does not exist and the draft skipped 20 release cycles with no
    one able to act on the instruction. A gate that reports a state it did not
    check is worse than one that blocks: it spends a human's attention on a
    dead end. Look before speaking.
    """
    queue_dir = Path(storage_dir) / "ops" / "compute_queue"
    if not queue_dir.exists():
        return "missing", None
    jobs: list[tuple[str, str, str]] = []
    for path in sorted(queue_dir.glob(f"lazypack-{article_id}*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            # 讀不動的 job 檔會讓這個 gate 少看到一個 job，而它的回答會被當成
            # 「已檢查過全部」——正是本函式 docstring 要避免的那種假回報。
            from .diagnostics import warn

            warn(f"lazypack job 檔讀取失敗，已略過：{path.name}: {exc}")
            continue
        # glob is a prefix match: lazypack-mile_ab must not answer for
        # lazypack-mile_abcdef. Retries are the only legal suffix.
        job_id = str(job.get("id") or path.stem)
        if job_id != f"lazypack-{article_id}" and not job_id.startswith(
            f"lazypack-{article_id}-r"
        ):
            continue
        jobs.append((str(job.get("queued_at") or ""), job_id, str(job.get("status") or "")))
    if not jobs:
        return "missing", None
    jobs.sort()
    _, job_id, status = jobs[-1]
    return (status or "unknown"), job_id


def _lazypack_plan_path(article_id: str, storage_dir: str = "storage") -> Path | None:
    """The authored, evidence-bound plan for ``article_id``, if one exists."""
    root = Path(storage_dir) / "lazypack_jobs"
    for candidate in (
        root / article_id / "plan.json",
        root / f"{article_id}_plan.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _lazypack_gate_issue(
    article_id: str, storage_dir: str = "storage", *, may_enqueue: bool = True
) -> str:
    """One honest sentence about why this article has no 懶人包圖組 yet.

    When the render was simply never queued and a plan is on disk, queue it
    here rather than reporting the gap: the gate is the one code path that
    reliably notices, and a draft that needs one command is not a finding, it
    is an omission to close. Without a plan there is nothing to queue — say so
    explicitly instead of inventing a job id.

    ``may_enqueue=False`` keeps the read-only preview caller side-effect free;
    it still reports the true state, it just does not act on it.
    """
    state, job_id = _lazypack_job_state(article_id, storage_dir)

    if state == "missing":
        plan = _lazypack_plan_path(article_id, storage_dir)
        if plan is not None and not may_enqueue:
            return (
                "missing 懶人包圖組 section; the render job was never queued "
                f"(an evidence-bound plan is ready at {plan})"
            )
        if plan is None:
            return (
                "missing 懶人包圖組 section and NO render job was ever queued "
                f"(checked {Path(storage_dir) / 'ops' / 'compute_queue'}/"
                f"lazypack-{article_id}*.json) "
                "— no evidence-bound plan on disk either; author one via the "
                "lazypack-infographic skill, then: uv run python "
                f"scripts/lazypack_async_render.py enqueue --article-id {article_id} "
                "--plan <plan.json>"
            )
        try:
            import subprocess

            proc = subprocess.run(
                [
                    "uv", "run", "python", "scripts/lazypack_async_render.py",
                    "enqueue", "--article-id", article_id, "--plan", str(plan),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                return (
                    "missing 懶人包圖組 section; the render job was never queued "
                    f"— auto-enqueued just now from {plan}. The */15 compute "
                    "worker will render it; this draft releases on the next cycle."
                )
            return (
                "missing 懶人包圖組 section; the render job was never queued and "
                f"auto-enqueue from {plan} FAILED: "
                f"{(proc.stderr or proc.stdout or '').strip()[:300]}"
            )
        except Exception as exc:  # noqa: BLE001 — reported, never raised at a gate
            return (
                "missing 懶人包圖組 section; the render job was never queued and "
                f"auto-enqueue from {plan} raised {type(exc).__name__}: {exc}"
            )

    if state in ("queued", "running"):
        return (
            f"missing 懶人包圖組 section (render {state}, job {job_id}) — "
            "waiting on the */15 compute worker, no action needed"
        )
    if state == "completed":
        return (
            f"missing 懶人包圖組 section although job {job_id} COMPLETED — the "
            "render finished but the section was not installed; inspect: uv run "
            f"python scripts/compute_queue.py show {job_id}"
        )
    return (
        f"missing 懶人包圖組 section (render {state}, job {job_id}) — inspect: "
        f"uv run python scripts/compute_queue.py show {job_id} ; re-enqueue via "
        "scripts/lazypack_async_render.py enqueue"
    )


def release_content_gate_issues(
    item: dict,
    storage_dir: str = "storage",
    *,
    record: bool = True,
) -> list[str]:
    """Return the content-quality blockers that would stop ``item`` releasing.

    2026-07-19 root-cause extraction (boss 20:14 「為什麼文章沒有照排程釋出」):
    `release_pool_articles` evaluated these three gates INLINE, while
    `preview_release_pool_by_settings` — the instrument that feeds the hourly
    alert AND `_auto_remediate_release_deadlock` — stopped at the dedup/cluster
    filters. The pool therefore reported `eligible=3` for 9 hours while the real
    release path released 0 and the deadlock detector concluded `not_deadlocked`.
    One evaluator, two callers: preview eligibility now means the same thing as
    release eligibility.

    No skip counters, no fix tasks, no feed mutation. Callers that need those side
    effects (the release loop) own them. `record=False` additionally suppresses the
    anti-AI gate's decision-ledger append and evaluates against a copy, so the
    preview path is fully read-only.
    """
    if not record:
        item = deepcopy(item)
    audience = str(item.get("audience") or "").lower()
    body_text = (
        item.get("description")
        or item.get("content")
        or item.get("summary")
        or ""
    )
    issues = list(
        _audit_general_content(
            audience,
            list(item.get("tags") or []),
            str(body_text),
        )
    )

    if audience == "general":
        try:
            # Read content-first (NOT the audit gate's description-first
            # body_text): the installed section lives in item["content"];
            # "description" is the <=200-char SEO snippet.
            _lz_text = item.get("content") or item.get("description") or ""
            if not has_lazypack_section(str(_lz_text)):
                issues.append(
                    _lazypack_gate_issue(
                        str(item.get("id") or ""), storage_dir,
                        may_enqueue=record
                    )
                )
        except Exception as exc:  # fail-open: never block release on a broken check
            _warn_release_pool("lazypack release gate check failed; fail-open", exc)

    issues.extend(
        _run_publish_anti_ai_gate(
            storage_dir,
            item,
            target_status="published",
            raise_on_block=False,
            log_decision=record,
        )
        or []
    )
    return issues


def release_pool_articles(
    *,
    pub_id: str | None = None,
    limit: int = 1,
    due_only: bool = True,
    include_drafts: bool | None = None,
    preferred_audiences: list[str] | None = None,
    update_last_released: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    feed = load_feed(storage_dir)
    expected_items_by_id = {
        str(item.get("id") or ""): deepcopy(item)
        for item in feed
        if isinstance(item, dict) and item.get("id")
    }
    now = datetime.now(timezone.utc)
    effective_include_drafts = include_drafts if include_drafts is not None else (not due_only)
    audience_priority = {
        audience: index
        for index, audience in enumerate(preferred_audiences or [])
    }

    def is_due(item: dict) -> bool:
        published_at = item.get("published_at")
        if item.get("status") == "draft":
            return effective_include_drafts
        if not due_only:
            return True
        if not isinstance(published_at, str) or not published_at.strip():
            return True
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")) <= now
        except Exception as exc:
            from .diagnostics import warn

            warn(
                "release_pool",
                "published_at parse failed; treating item as due",
                item_id=str(item.get("id") or ""),
                published_at=str(published_at),
                err=f"{type(exc).__name__}: {exc}",
            )
            return True

    # Cluster-headroom-aware release ordering (2026-06-29). The draft pool can be
    # dominated by one topic cluster (observed: 84% vix/spy), and pure FIFO release
    # keeps feeding the over-concentration that trips cluster_cap_drift (vix 6x /
    # spy 8x over cap) + arc_diversity. Prefer releasing drafts whose 30d cluster
    # count is UNDER its hard cap; over-cap drafts sort last but are NEVER blocked
    # (drought-safe — if every eligible draft is over-cap, one still releases). This
    # is a pure tiebreaker (reorder, not a lock), so it cannot recreate the
    # 2026-06-23 pool-freeze incident (that was a per-draft 21-day hard lock). Counts
    # come from the local `feed` (storage_dir-correct + deterministic for tests),
    # not recent_cluster_counts (which ignores storage_dir).
    _cluster_cutoff = now - timedelta(days=30)
    _cluster_pub_counts: dict[str, int] = {}
    for _it in feed:
        if _it.get("status") != "published":
            continue
        _ts = _parse_datetime(_it.get("published_at") or _it.get("created_at"))
        if _ts is None or _ts < _cluster_cutoff:
            continue
        _cl = classify_topic_cluster(
            _it.get("title") or "", _it.get("tags") or [], _it.get("category") or ""
        )
        _cluster_pub_counts[_cl] = _cluster_pub_counts.get(_cl, 0) + 1

    def _over_cap_rank(item: dict) -> int:
        cl = classify_topic_cluster(
            item.get("title") or "",
            item.get("tags") or [],
            item.get("category") or item.get("description") or "",
        )
        cap = cluster_cap(cl)
        return 1 if (cap and _cluster_pub_counts.get(cl, 0) >= cap) else 0

    def sort_key(item: dict) -> tuple:
        published_at = str(item.get("published_at") or "")
        created_at = str(item.get("created_at") or "")
        audience = _article_audience(item)
        preferred_rank = audience_priority.get(audience, len(audience_priority))
        status = str(item.get("status") or "")
        # Sort: audience priority → scheduled first → under-cap clusters first
        # (diversity tiebreaker) → FIFO (oldest created_at first).
        return (
            preferred_rank,
            0 if status == "scheduled" else 1,
            _over_cap_rank(item),
            created_at,
        )

    _eligible_statuses = {"scheduled", "draft"} if effective_include_drafts else {"scheduled"}
    candidates = [
        item for item in feed
        if item.get("status") in _eligible_statuses
        and is_due(item)
        and not _release_dedup_flag_active(item, now=now)
    ]
    candidates.sort(key=sort_key)
    if pub_id:
        candidates = [item for item in candidates if item.get("id") == pub_id]

    # Reader-facing drafts excluded *at selection* by the dedup-cooldown flag
    # (`_release_dedup_skipped` within its TTL). These never enter the release
    # loop, so they are not in dedup_blocked_items — but they ARE dedup-blocked
    # drafts and must still be reachable by the drought breaker, otherwise a
    # pool where every draft is cooldown-flagged (the common drought shape)
    # would leave the breaker with nothing to release. Excluded for an explicit
    # pub_id (manual single-article path).
    cooldown_blocked_items = [
        item for item in feed
        if not pub_id
        and item.get("status") in _eligible_statuses
        and is_due(item)
        and _release_dedup_flag_active(item, now=now)
        and _article_audience(item) in _RELEASE_DEDUP_AUDIENCES
    ]

    k_cluster = _knowledge_experiment_clusters(storage_dir)
    narrative_pressure = _recent_narrative_cluster_pressure(feed, k_cluster=k_cluster)
    blocked_narrative_clusters = set(narrative_pressure["blocked_clusters"])
    narrative_cluster_filtered: list[dict] = []
    if blocked_narrative_clusters and not pub_id:
        filtered_candidates: list[dict] = []
        for item in candidates:
            candidate_cluster = _article_narrative_cluster(item, k_cluster)
            candidate_series = _article_series(item)
            if candidate_series and candidate_cluster in blocked_narrative_clusters:
                # Serialized chapter of a registered series: the cluster gate exists to
                # stop the same story flooding the feed, not to strand a 專題 mid-run.
                # Same-episode reruns are still caught by the arc-dedup gate below.
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    decision="pass",
                    reason=f"registered_series_exempt_from_cluster_gate:{candidate_series}",
                )
                filtered_candidates.append(item)
                continue
            if (
                _article_audience(item) in _RELEASE_DEDUP_AUDIENCES
                and candidate_cluster in blocked_narrative_clusters
            ):
                narrative_cluster_filtered.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "cluster": candidate_cluster,
                        "last_n_counts": narrative_pressure["counts"],
                        "recent_ids": narrative_pressure["recent_ids"],
                    }
                )
                continue
            filtered_candidates.append(item)
        candidates = filtered_candidates

    # Series release pacing (2026-07-14): the cluster-gate exemption above keeps a
    # registered series from deadlocking the pool, but without pacing it drains at
    # pool cadence (無人載具 6 episodes in ~20h, EP4 before EP3, boss escalation).
    # Pacing is a hard hold at selection: held episodes never reach the release
    # loop, so the drought breaker cannot force them out either. An explicit
    # pub_id (manual single-article release) is an operator override and bypasses.
    series_pacing_held: list[dict] = []
    if not pub_id:
        unheld_candidates: list[dict] = []
        for item in candidates:
            hold = _series_pacing_hold(item, feed, now)
            if hold is not None:
                series_pacing_held.append(hold)
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    decision="hold",
                    reason=(
                        f"series_pacing:{hold['series']}:{hold['reason']}:"
                        f"{hold.get('next_eligible_at') or hold.get('next_in_series') or ''}"
                    ),
                )
                continue
            unheld_candidates.append(item)
        candidates = unheld_candidates

    target_limit = max(int(limit), 1)
    released: list[dict] = []
    audit_skipped: list[dict] = []
    audit_materialized: list[dict] = []
    dedup_skipped: list[dict] = []
    publish_throttled: list[dict] = []
    release_conflicts: list[dict] = []
    metadata_patches: list[dict] = []
    # Content-clean drafts blocked purely by the dedup gates this run — the only
    # pool the drought breaker may force-release from (audit-blocked drafts are
    # excluded so a drought can never publish low-quality content).
    dedup_blocked_items: list[dict] = []
    theme_valves: list[dict] = []
    theme_valves_used: set[str] = set()
    released_at = now.isoformat()

    # Recently-published general/research corpus for the anti-flood dedup gate.
    _dedup_cutoff = (now - timedelta(days=_RELEASE_DEDUP_WINDOW_DAYS)).isoformat()
    recent_pub_for_dedup = [
        a
        for a in feed
        if a.get("status") == "published"
        and str(a.get("published_at") or "") >= _dedup_cutoff
        and _article_audience(a) in _RELEASE_DEDUP_AUDIENCES
    ]

    # Re-audit at release time (2026-04-26 hardening): pre-d9921152 drafts
    # were built before publish_milestone gained audience-content gates, so
    # release_pool used to silently promote drafts containing K-id tags or
    # research-density forbidden terms in audience='general' bodies. Auto-fix
    # K-id pollution (lossless) and skip-with-log on hard audit failures so
    # main thread can clean them up without polluting the live feed.
    #
    # 2026-06-19 fall-through fix: do not pre-truncate to the first `limit`
    # candidates. If the oldest due drafts are correctly skipped by audit or
    # dedup gates, keep scanning the sorted pool until `target_limit` articles
    # are actually released or the pool is exhausted.
    _paced_series_released_this_run: set[str] = set()
    for item in candidates:
        if len(released) >= target_limit:
            break

        # Same-run guard for paced series: min_gap only sees *persisted*
        # published_at timestamps, so with limit > 1 an unordered paced series
        # could still ship two episodes in one run. One paced episode per run.
        if not pub_id:
            _series_key = _item_paced_series(item)
            if _series_key and _series_key in _paced_series_released_this_run:
                series_pacing_held.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "series": _series_key,
                        "reason": "same_run",
                    }
                )
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    decision="hold",
                    reason=f"series_pacing:{_series_key}:same_run",
                )
                continue

        _relocate_release_internal_tags(item, now=now)

        # Lossless auto-fix: relocate K-id tags to details.experiment_refs.
        raw_tags = item.get("tags") or []
        if isinstance(raw_tags, list):
            cleaned_tags, extracted_refs = _extract_experiment_refs(raw_tags)
            if extracted_refs:
                item["tags"] = cleaned_tags
                details = item.get("details")
                if not isinstance(details, dict):
                    details = {}
                    item["details"] = details
                merged_refs = sorted(
                    set((details.get("experiment_refs") or []) + extracted_refs)
                )
                details["experiment_refs"] = merged_refs

        # Hard audit gate for general audience: forbidden statistical
        # terminology + tag count cap. audit_strict effectively False here
        # so we don't crash the cron loop, but we DO refuse to flip status.
        audience = str(item.get("audience") or "").lower()
        # Gate evaluation lives in release_content_gate_issues() so the preview /
        # deadlock detector judge the pool by the SAME rules (2026-07-19). The
        # skip-counter + fix-task escalation below stays here — it is a release-run
        # side effect, not part of the verdict.
        audit_issues = release_content_gate_issues(item, storage_dir)
        if audit_issues:
            details = item.get("details")
            if not isinstance(details, dict):
                details = {}
                item["details"] = details
            skip_count = _next_release_audit_skip_count(details)
            details["release_audit_skipped_count"] = skip_count
            details["release_audit_skipped_at"] = now.isoformat()
            details["release_audit_issues"] = audit_issues

            materialized = None
            if skip_count >= _RELEASE_AUDIT_MATERIALIZE_THRESHOLD:
                materialized = _materialize_release_audit_fix_task(
                    item=item,
                    audit_issues=audit_issues,
                    skip_count=skip_count,
                    storage_dir=storage_dir,
                    now=now,
                )
                details["release_audit_task_id"] = materialized.get("task_id")
                details["release_audit_task_materialized_at"] = now.isoformat()
                if materialized.get("created"):
                    audit_materialized.append(
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "task_id": materialized.get("task_id"),
                            "skip_count": skip_count,
                        }
                    )

            skipped_entry = {
                "id": item.get("id"),
                "title": item.get("title"),
                "audience": audience,
                "issues": audit_issues,
                "skip_count": skip_count,
            }
            if materialized is not None:
                skipped_entry["materialized_task"] = materialized
            audit_skipped.append(skipped_entry)
            metadata_patches.append(
                {
                    "id": item.get("id"),
                    "expected_status": item.get("status"),
                    "expected_item": expected_items_by_id.get(str(item.get("id") or "")),
                    "fields": {
                        key: deepcopy(item[key])
                        for key in ("details", "tags")
                        if key in item
                    },
                }
            )
            continue

        _mark_release_audit_resolved(item, now=now)

        # Anti-flood dedup gate (2026-06-16): skip near-duplicate of a
        # recently-published general/research article — don't flood live feed.
        if _article_audience(item) in _RELEASE_DEDUP_AUDIENCES:
            # Pass the draft's experiment_refs so the arc gate can catch a
            # same-K recycle even when its conclusion class is 'descriptive'
            # and surface entities are all core (2026-06-19 K1054 ghost fix).
            _item_details = item.get("details") or {}
            _item_refs = []
            if isinstance(_item_details, dict):
                _item_refs = (
                    _item_details.get("experiment_refs")
                    or _item_details.get("experiment_ids")
                    or []
                )
            _item_title = str(item.get("title") or "")
            _item_text = str(item.get("content") or item.get("description") or "")
            arc_matches = find_arc_duplicates(
                _item_title,
                _item_text,
                recent_pub_for_dedup,
                days=_RELEASE_DEDUP_WINDOW_DAYS,
                new_refs=_item_refs,
                include_fuzzy=True,
            )
            arc_dups = [m for m in arc_matches if not is_arc_near_miss(m)]
            arc_near_misses = [m for m in arc_matches if is_arc_near_miss(m)]
            if arc_near_misses and not arc_dups:
                d = arc_near_misses[0]
                print(
                    f"  [release_pool] ARC-NEAR-MISS {item.get('id')} — "
                    f"advisory similarity to {d.get('id')}; releasing."
                )
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    matched_id=d.get("id"),
                    decision="warn",
                    reason="descriptive_fuzzy_mechanism_near_miss",
                )
                _d = item.get("details")
                if not isinstance(_d, dict):
                    _d = {}
                    item["details"] = _d
                _d["release_arc_near_miss_of"] = d.get("id")
                _d["release_arc_near_miss_at"] = now.isoformat()
            elif not arc_dups and is_arc_anchorless(
                arc_signature(_item_title, _item_text), _item_refs
            ):
                print(
                    f"  [release_pool] ARC-UNJUDGED {item.get('id')} — "
                    "signature has no distinctive entity/ref; releasing."
                )
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    matched_id=None,
                    decision="warn",
                    reason="anchorless_signature_not_clean",
                )
                _d = item.get("details")
                if not isinstance(_d, dict):
                    _d = {}
                    item["details"] = _d
                _d["release_arc_unjudged_at"] = now.isoformat()
            dup = _release_content_dup(item, recent_pub_for_dedup)
            flood = _release_theme_flood(item, recent_pub_for_dedup)

            if arc_dups:
                blocker_by_id = {
                    str(a.get("id") or ""): a
                    for a in recent_pub_for_dedup
                    if isinstance(a, dict)
                }
                blocking_arc_dups = []
                warn_arc_dups = []
                for arc_dup in arc_dups:
                    blocker = blocker_by_id.get(str(arc_dup.get("id") or ""))
                    block_reason = _release_arc_block_reason(item, blocker, arc_dup)
                    if block_reason:
                        arc_dup = {**arc_dup, "release_block_reason": block_reason}
                        blocking_arc_dups.append(arc_dup)
                        _log_release_dedup_decision(
                            storage_dir,
                            target_id=item.get("id"),
                            matched_id=arc_dup.get("id"),
                            decision="block",
                            reason=block_reason,
                        )
                    else:
                        warn_arc_dups.append(arc_dup)
                if warn_arc_dups:
                    d = warn_arc_dups[0]
                    print(
                        f"  [release_pool] ARC-WARN {item.get('id')} — "
                        f"arc-similar to {d.get('id')} ({d.get('conclusion_class')}) "
                        "but no shared K/data source; releasing."
                    )
                    _log_release_dedup_decision(
                        storage_dir,
                        target_id=item.get("id"),
                        matched_id=d.get("id"),
                        decision="warn",
                        reason="arc_similarity_without_shared_ref_or_data_source",
                    )
                    _d = item.get("details")
                    if not isinstance(_d, dict):
                        _d = {}
                        item["details"] = _d
                    _d["release_arc_warn_of"] = d.get("id")
                    _d["release_arc_warn_class"] = d.get("conclusion_class")
                    _d["release_arc_warn_reason"] = "no_shared_ref_or_data_source"
                    _d["release_arc_warn_at"] = now.isoformat()
                arc_dups = blocking_arc_dups

            # Narrative-axis waiver (2026-06-24): mirror the current arc schema
            # on the release gate's surface-text checks. The Jaccard near-dup and the
            # theme-flood gate are blind to reader-facing narrative axis: a
            # paper methodology-robustness note and an ETF product-myth piece
            # can be text-similar yet tell different reader stories. When the
            # candidate AND every relevant blocker resolve to a SPECIFIED but
            # DIFFERENT axis, waive the text-similarity verdict (release).
            # arc_dups already carries this waiver inside find_arc_duplicates,
            # so we never touch it here. Fail-open: any unspecified/matching
            # axis keeps the original verdict.
            if dup is not None:
                dup_blocker = next(
                    (a for a in recent_pub_for_dedup if a.get("id") == dup["id"]),
                    None,
                )
                if dup_blocker is not None and _release_axis_waives_dup(item, [dup_blocker]):
                    print(
                        f"  [release_pool] AXIS-WAIVE {item.get('id')} — "
                        f"near-dup of {dup['id']} (J={dup['jaccard']}) but narrative "
                        f"axis '{_item_narrative_axis(item)}' != "
                        f"'{_item_narrative_axis(dup_blocker)}'; releasing."
                    )
                    dup = None
            if flood is not None:
                flood_rx = _SATURATED_THEMES.get(flood["theme"])
                flood_blockers = (
                    [
                        a
                        for a in recent_pub_for_dedup
                        if a.get("id") != item.get("id")
                        and flood_rx.search(
                            str(a.get("title") or "")
                            + "\n"
                            + str(a.get("content") or a.get("description") or "")
                        )
                    ]
                    if flood_rx is not None
                    else []
                )
                if flood_blockers and _release_axis_waives_dup(item, flood_blockers):
                    print(
                        f"  [release_pool] AXIS-WAIVE {item.get('id')} — "
                        f"theme '{flood['theme']}' saturated but narrative axis "
                        f"'{_item_narrative_axis(item)}' differs from all "
                        f"{len(flood_blockers)} same-theme published pieces; releasing."
                    )
                    flood = None

            if (
                flood is not None
                and not arc_dups
                and dup is None
                and flood["theme"] not in theme_valves_used
            ):
                theme_valves_used.add(flood["theme"])
                _d = item.get("details")
                if not isinstance(_d, dict):
                    _d = {}
                    item["details"] = _d
                _d["release_theme_valve"] = True
                _d["release_theme_valve_theme"] = flood["theme"]
                _d["release_theme_valve_recent_count"] = flood["recent_count"]
                _d["release_theme_valve_at"] = now.isoformat()
                theme_valves.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "theme": flood["theme"],
                        "recent_count": flood["recent_count"],
                    }
                )
                print(
                    f"  [release_pool] THEME-VALVE {item.get('id')} — "
                    f"theme '{flood['theme']}' saturated "
                    f"(recent={flood['recent_count']}); releasing oldest candidate this run."
                )
                flood = None
            if arc_dups or dup is not None or flood is not None:
                # Flag so it's excluded from future candidate selection (no
                # infinite re-skip / slot block); left as draft for review, not
                # destructively unpublished.
                _d = item.get("details")
                if not isinstance(_d, dict):
                    _d = {}
                    item["details"] = _d
                _d["release_dedup_skipped"] = True
                _d["release_dedup_skipped_at"] = now.isoformat()
                _d["release_dedup_gate_version"] = _RELEASE_DEDUP_GATE_VERSION
                if dup is not None:
                    _d["release_dedup_of"] = dup["id"]
                    _d["release_dedup_jaccard"] = dup["jaccard"]
                if flood is not None:
                    _d["release_theme_flood"] = flood["theme"]
                    _d["release_theme_recent_count"] = flood["recent_count"]
                if arc_dups:
                    _d["release_arc_dedup_of"] = arc_dups[0]["id"]
                    _d["release_arc_dedup_class"] = arc_dups[0]["conclusion_class"]
                    _d["release_arc_dedup_reason"] = arc_dups[0].get("release_block_reason")
                dedup_skipped.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "arc_dup_of": arc_dups[0]["id"] if arc_dups else None,
                        "arc_conclusion_class": arc_dups[0]["conclusion_class"] if arc_dups else None,
                        "arc_block_reason": arc_dups[0].get("release_block_reason") if arc_dups else None,
                        "dup_of": dup["id"] if dup else None,
                        "jaccard": dup["jaccard"] if dup else None,
                        "theme_flood": flood["theme"] if flood else None,
                        "theme_recent_count": flood["recent_count"] if flood else None,
                    }
                )
                metadata_patches.append(
                    {
                        "id": item.get("id"),
                        "expected_status": item.get("status"),
                        "expected_item": expected_items_by_id.get(str(item.get("id") or "")),
                        "fields": {
                            key: deepcopy(item[key])
                            for key in ("details", "tags")
                            if key in item
                        },
                    }
                )
                # Eligible for drought-breaker rescue (content-clean, blocked
                # only for surface similarity / theme flood / arc overlap).
                dedup_blocked_items.append(item)
                reason = (
                    f"arc-dup of {arc_dups[0]['id']} ({arc_dups[0]['conclusion_class']}; {arc_dups[0].get('release_block_reason')})" if arc_dups
                    else f"near-dup of {dup['id']} (J={dup['jaccard']})" if dup
                    else f"theme '{flood['theme']}' saturated (recent={flood['recent_count']})"
                )
                print(f"  [release_pool] DEDUP-SKIP {item.get('id')} — {reason}; kept as draft.")
                continue

        promotion = _atomic_promote_release_item(
            item,
            now=now,
            released_at=released_at,
            storage_dir=storage_dir,
            route="explicit_pub_id" if pub_id else "release_pool",
            expected_item=expected_items_by_id.get(str(item.get("id") or "")),
        )
        if promotion["outcome"] == "throttled":
            publish_throttled.append(promotion["block"])
            continue
        if promotion["outcome"] != "promoted":
            release_conflicts.append(promotion)
            print(
                f"  [release_pool] RELEASE-NOOP {item.get('id')} — "
                f"{promotion.get('reason')}; fresh canonical state won."
            )
            continue

        item.clear()
        item.update(promotion["item"])
        _released_paced = _item_paced_series(item)
        if _released_paced:
            _paced_series_released_this_run.add(_released_paced)
        # Contentlayer pattern (2026-04-18): feed.json is canonical; no
        # mile_*.json singles to read back / rewrite. feed entry already
        # holds the full content since reconcile_content_from_singles().
        article_slug = str(item.get("id", ""))
        # K1021 incident (2026-04-30): sync_article return value used to be
        # ignored → release_pool flipped local status to 'published' while
        # Supabase silently kept 'draft'. Capture the result so we can
        # surface failures via the released dict + heartbeat alerts can
        # detect divergence (status_synced=False).
        sync_ok = False
        try:
            sync_ok = bool(sync_article(item, storage_dir=publisher.reports_dir.parent))
        except Exception as exc:
            print(f"  [release_pool] sync_article exception for {article_slug}: {exc}")
        released.append({
            "id": article_slug,
            "title": item.get("title"),
            "status": item.get("status"),
            "published_at": item.get("published_at"),
            "supabase_synced": bool(sync_ok),
        })
        if not sync_ok:
            # 2026-05-04 finding #9 修整：sync_article 失敗必寫
            # `.failed_supabase_syncs.json`，否則 alerts.py 的
            # `_parse_supabase_sync_state` 抓不到 → silent gap K1021 pattern。
            # 與 publisher.publish_milestone path 同一機制（
            # src/volpred/publisher/publisher.py:484-501）。
            failed_path = publisher.reports_dir.parent / ".failed_supabase_syncs.json"
            try:
                failed = json.loads(failed_path.read_text()) if failed_path.exists() else []
                if not isinstance(failed, list):
                    raise ValueError(".failed_supabase_syncs.json must contain a list")
            except Exception as exc:
                _warn_release_pool(
                    "failed Supabase sync ledger unreadable; recreating", exc
                )
                failed = []
            if article_slug not in failed:
                failed.append(article_slug)
                failed_path.write_text(json.dumps(failed))
            print(
                f"  [release_pool] WARN Supabase sync failed for {article_slug} -- "
                f"recorded to .failed_supabase_syncs.json. "
                f"Run scripts/supabase_sync.py sync-article {article_slug} to retry."
            )
        # Auto-mark linked questions as answered now that article is published
        _mark_questions_answered_on_publish(article_slug)
        publisher._notify_article_published(item, reason="release_pool")

    # Drought circuit-breaker: if the normal pass released nothing but
    # content-clean drafts were dedup-blocked, and the feed has drifted past the
    # reader-facing drought threshold, force-release exactly one (the least
    # dup-like). The rescue pool is BOTH the drafts live-blocked in this run's
    # loop AND the reader-facing drafts excluded at selection by the dedup
    # cooldown flag (deduped by id) — otherwise a pool where every draft is
    # cooldown-flagged would starve the breaker. Skipped for an explicit pub_id.
    drought_override: dict | None = None
    if not released and not pub_id:
        _blocked_by_id: dict[str, dict] = {}
        for _it in (*dedup_blocked_items, *cooldown_blocked_items):
            _bid = str(_it.get("id") or "")
            if _bid and _bid not in _blocked_by_id:
                _blocked_by_id[_bid] = _it
        drought_override = _maybe_drought_release(
            blocked_items=list(_blocked_by_id.values()),
            feed=feed,
            recent_pub=recent_pub_for_dedup,
            now=now,
            released_at=released_at,
            publisher=publisher,
            storage_dir=storage_dir,
            released=released,
            publish_throttled=publish_throttled,
            expected_items_by_id=expected_items_by_id,
        )

    # Persist only the audit/dedup fields touched by this run. A stale whole-feed
    # dump here used to overwrite concurrent Publisher/release-pool writes.
    released_ids = {str(entry.get("id") or "") for entry in released}
    pending_metadata_patches = [
        patch
        for patch in metadata_patches
        if str(patch.get("id") or "") not in released_ids
    ]
    release_conflicts.extend(
        _atomic_patch_feed_entries(pending_metadata_patches, storage_dir=storage_dir)
    )

    if released:
        # Local canonical promotion already committed atomically under the
        # publisher_feed lock. Network side effects deliberately happen after
        # that short critical section.
        for released_entry in released:
            article_id = released_entry.get("id")
            if article_id:
                publisher._sync_report_to_remote(str(article_id), released_entry)

        # 2026-05-19 post-publish live verify gate (Three-Strike fix):
        # release_pool was flipping status='published' without verifying the
        # public URL actually resolved. Verify each released item, stamp
        # verified_live_at on PASS, mark live_verify_failed + alert on FAIL.
        try:
            from volpred.publisher.live_verify import (
                verify_article_live,
                stamp_verified,
                emit_verify_alert,
            )

            verify_patches: list[dict] = []
            for released_entry in released:
                article_id = released_entry.get("id")
                if not article_id:
                    continue
                live_ok = verify_article_live(article_id)
                target = next(
                    (i for i in feed if i.get("id") == article_id),
                    None,
                )
                if target is not None:
                    stamp_verified(target, verified=live_ok)
                    verify_fields = {}
                    if "verified_live_at" in target:
                        verify_fields["verified_live_at"] = target["verified_live_at"]
                    if "live_verify_failed" in target:
                        verify_fields["live_verify_failed"] = target["live_verify_failed"]
                    verify_patches.append(
                        {
                            "id": article_id,
                            "expected_status": "published",
                            "fields": verify_fields,
                        }
                    )
                released_entry["verified_live"] = bool(live_ok)
                if not live_ok:
                    emit_verify_alert(
                        article_id,
                        (target or {}).get("title") if target else None,
                        storage_dir=storage_dir,
                    )

            _atomic_patch_feed_entries(verify_patches, storage_dir=storage_dir)
            for released_entry in released:
                article_id = released_entry.get("id")
                if not article_id:
                    continue
                target = next(
                    (i for i in feed if i.get("id") == article_id),
                    released_entry,
                )
                publisher._sync_report_to_remote(str(article_id), target)
        except Exception as exc:
            print(f"  [release_pool] live_verify exception: {exc}")

        if update_last_released:
            _update_content_release_settings(
                {"last_released_at": released_at},
                storage_dir=storage_dir,
            )

    return {
        "requested_id": pub_id,
        "released_count": len(released),
        "released": released,
        "audit_skipped": audit_skipped,
        "audit_materialized": audit_materialized,
        "dedup_skipped": dedup_skipped,
        "publish_throttled": publish_throttled,
        "release_conflicts": release_conflicts,
        "theme_valves": theme_valves,
        "drought_override": drought_override,
        "narrative_cluster_pressure": narrative_pressure,
        "narrative_cluster_filtered": narrative_cluster_filtered,
        "series_pacing_held": series_pacing_held,
        "due_only": due_only,
        "include_drafts": effective_include_drafts,
        "preferred_audiences": list(preferred_audiences or []),
        "limit": target_limit,
    }


def release_pool_by_settings(
    *,
    force: bool = False,
    storage_dir: str = "storage",
) -> dict:
    settings = get_content_release_settings(storage_dir=storage_dir)
    now = datetime.now(timezone.utc)
    last_released_at = _parse_datetime(settings.get("last_released_at"))
    next_release_at = None

    if last_released_at is not None:
        # Truncate last_released_at to minute precision to avoid sub-second
        # timing mismatches with cron (which fires at :00 seconds).
        last_minute = last_released_at.replace(second=0, microsecond=0)
        next_release_at = last_minute + timedelta(minutes=int(settings["interval_minutes"]))

    if not force:
        if settings["mode"] not in ("scheduled", "auto"):
            return {
                "mode": settings["mode"],
                "released_count": 0,
                "released": [],
                "skipped": True,
                "reason": "manual_mode",
                "settings": settings,
            }
        if next_release_at is not None and next_release_at > now:
            return {
                "mode": settings["mode"],
                "released_count": 0,
                "released": [],
                "skipped": True,
                "reason": "interval_not_due",
                "next_release_at": next_release_at.isoformat(),
                "settings": settings,
            }

    result = release_pool_articles(
        limit=int(settings["max_articles_per_run"]),
        due_only=bool(settings["due_only"]),
        include_drafts=bool(settings["include_drafts"]),
        preferred_audiences=list(settings["preferred_audiences"]),
        update_last_released=True,
        storage_dir=storage_dir,
    )
    refreshed_settings = (
        get_content_release_settings(storage_dir=storage_dir)
        if result.get("released_count")
        else settings
    )
    return {
        **result,
        "mode": settings["mode"],
        "force": force,
        "skipped": False,
        "settings": refreshed_settings,
    }


def preview_release_pool_by_settings(
    *,
    storage_dir: str = "storage",
) -> dict:
    settings = get_content_release_settings(storage_dir=storage_dir)
    now = datetime.now(timezone.utc)
    last_released_at = _parse_datetime(settings.get("last_released_at"))
    next_release_at = None
    if last_released_at is not None:
        last_minute = last_released_at.replace(second=0, microsecond=0)
        next_release_at = last_minute + timedelta(minutes=int(settings["interval_minutes"]))

    feed = load_feed(storage_dir)
    include_drafts = bool(settings["include_drafts"])
    due_only = bool(settings["due_only"])
    preferred_audiences = list(settings["preferred_audiences"])
    audience_priority = {
        audience: index
        for index, audience in enumerate(preferred_audiences)
    }

    def is_due(item: dict) -> bool:
        published_at = item.get("published_at")
        if item.get("status") == "draft":
            return include_drafts
        if not due_only:
            return True
        if not isinstance(published_at, str) or not published_at.strip():
            return True
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")) <= now
        except (ValueError, TypeError) as exc:
            # Local import keeps the diagnostics dependency from shifting the
            # module-level line numbers tracked by the silent-fallback baseline.
            from .diagnostics import warn

            warn(
                "content",
                "release pool: unparseable published_at; treating item as due (fail-open)",
                err=str(exc),
                item_id=item.get("id"),
                published_at=published_at,
            )
            return True

    def sort_key(item: dict) -> tuple:
        published_at = str(item.get("published_at") or "")
        created_at = str(item.get("created_at") or "")
        audience = _article_audience(item)
        preferred_rank = audience_priority.get(audience, len(audience_priority))
        status = str(item.get("status") or "")
        # Sort: scheduled first, then audience priority, then FIFO (oldest created_at first)
        return (preferred_rank, 0 if status == "scheduled" else 1, created_at)

    eligible_statuses = {"scheduled", "draft"} if include_drafts else {"scheduled"}
    pool_items = [item for item in feed if item.get("status") in {"draft", "scheduled"}]
    candidates_before_dedup = [
        item for item in pool_items if item.get("status") in eligible_statuses and is_due(item)
    ]
    dedup_flagged = [
        item for item in candidates_before_dedup if _release_dedup_flag_active(item, now=now)
    ]
    candidates = [
        item for item in candidates_before_dedup if not _release_dedup_flag_active(item, now=now)
    ]
    candidates.sort(key=sort_key)

    k_cluster = _knowledge_experiment_clusters(storage_dir)
    narrative_pressure = _recent_narrative_cluster_pressure(feed, k_cluster=k_cluster)
    blocked_narrative_clusters = set(narrative_pressure["blocked_clusters"])
    narrative_cluster_filtered: list[dict] = []
    if blocked_narrative_clusters:
        filtered_candidates: list[dict] = []
        for item in candidates:
            candidate_cluster = _article_narrative_cluster(item, k_cluster)
            candidate_series = _article_series(item)
            if candidate_series and candidate_cluster in blocked_narrative_clusters:
                # Serialized chapter of a registered series: the cluster gate exists to
                # stop the same story flooding the feed, not to strand a 專題 mid-run.
                # Same-episode reruns are still caught by the arc-dedup gate below.
                _log_release_dedup_decision(
                    storage_dir,
                    target_id=item.get("id"),
                    decision="pass",
                    reason=f"registered_series_exempt_from_cluster_gate:{candidate_series}",
                )
                filtered_candidates.append(item)
                continue
            if (
                _article_audience(item) in _RELEASE_DEDUP_AUDIENCES
                and candidate_cluster in blocked_narrative_clusters
            ):
                narrative_cluster_filtered.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "cluster": candidate_cluster,
                        "last_n_counts": narrative_pressure["counts"],
                        "recent_ids": narrative_pressure["recent_ids"],
                    }
                )
                continue
            filtered_candidates.append(item)
        candidates = filtered_candidates

    # Content-quality gates (audit / lazypack / anti-ai), evaluated with the same
    # helper the release loop uses. Before 2026-07-19 the preview stopped above and
    # reported every dedup-clean draft as `eligible`, so the hourly alert printed
    # "去重後可釋出=3" and `_auto_remediate_release_deadlock` saw eligible>0 →
    # not_deadlocked, while the real release path released 0 for 9 hours straight.
    content_gate_blocked: list[dict] = []
    releasable: list[dict] = []
    for item in candidates:
        try:
            issues = release_content_gate_issues(item, storage_dir, record=False)
        except Exception as exc:  # fail-open: a broken checker must not fake a deadlock
            _warn_release_pool("preview content gate check failed; fail-open", exc)
            issues = []
        if issues:
            details = item.get("details")
            content_gate_blocked.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "audience": _article_audience(item),
                    "issues": issues,
                    "skip_count": (
                        details.get("release_audit_skipped_count")
                        if isinstance(details, dict)
                        else None
                    ),
                }
            )
            continue
        releasable.append(item)
    candidates = releasable

    due_now = settings["mode"] in ("scheduled", "auto") and (
        next_release_at is None or next_release_at <= now
    )

    next_candidates = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "status": item.get("status"),
            "audience": _article_audience(item),
            "published_at": item.get("published_at"),
            "created_at": item.get("created_at"),
        }
        for item in candidates[: max(int(settings["max_articles_per_run"]), 1)]
    ]

    return {
        "mode": settings["mode"],
        "settings": settings,
        "due_now": due_now,
        "next_release_at": next_release_at.isoformat() if next_release_at else None,
        "pool_counts": {
            "draft": sum(1 for item in pool_items if item.get("status") == "draft"),
            "scheduled": sum(1 for item in pool_items if item.get("status") == "scheduled"),
            "eligible_before_dedup": len(candidates_before_dedup),
            "dedup_flagged": len(dedup_flagged),
            "narrative_cluster_filtered": len(narrative_cluster_filtered),
            "content_gate_blocked": len(content_gate_blocked),
            "eligible": len(candidates),
        },
        "narrative_cluster_pressure": narrative_pressure,
        "narrative_cluster_filtered": narrative_cluster_filtered,
        "content_gate_blocked": content_gate_blocked,
        "next_candidates": next_candidates,
    }


def build_platform_cycle_summary(
    *,
    storage_dir: str = "storage",
    source: str = "user",
    limit: int = 20,
    write_latest: bool = False,
) -> dict:
    from .questions import build_question_rerank_workflow

    release_preview = preview_release_pool_by_settings(storage_dir=storage_dir)
    ranking_workflow = build_question_rerank_workflow(
        source=source,
        limit=limit,
        storage_dir=storage_dir,
        write_latest=write_latest,
    )

    summary = {
        "workflow_name": "platform_cycle_summary",
        "generated_at": ranking_workflow.get("generated_at"),
        "release_preview": release_preview,
        "question_ranking": ranking_workflow,
        "suggestions": [],
    }

    if release_preview.get("due_now"):
        summary["suggestions"].append("內容池已到節奏釋出時間，可評估執行 release-pool-by-settings。")
    elif release_preview.get("mode") == "manual":
        summary["suggestions"].append("目前內容池為 manual 模式，如需自動節奏發布需先切換設定。")

    pending = (ranking_workflow.get("health") or {}).get("pending_evaluation", 0)
    if pending:
        summary["suggestions"].append(f"目前有 {pending} 題待評分會員問題，適合執行 6 小時重排流程。")

    if write_latest:
        target = write_ops_snapshot(
            "platform-cycle-summary-latest",
            summary,
            storage_dir=storage_dir,
        )
        summary["snapshot_path"] = str(target.relative_to(project_path()))

    return summary


def send_article_notification(
    pub_id: str,
    *,
    force_send: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    return publisher.send_article_notification(pub_id, force_send=force_send)


def send_daily_digest(
    *,
    target_date: str | None = None,
    force_send: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    parsed = None
    if target_date:
        parsed = datetime.fromisoformat(target_date).date()
    return publisher.send_daily_digest(target_date=parsed, force_send=force_send)


def _mark_questions_answered_on_publish(article_slug: str) -> int:
    """When an article is published, mark any linked questions as answered.

    Checks question_articles for questions linked to this article, and if
    they are in 'researching' status, marks them as 'answered'.
    Returns the number of questions marked.
    """
    try:
        article_id = _get_article_id(article_slug)
        if not article_id:
            return 0
        rows = _select_rows("question_articles", select="question_id,article_id", article_id=article_id)
        if not rows:
            return 0
        marked = 0
        now_utc = datetime.now(timezone.utc).isoformat()
        for row in rows:
            question_id = row.get("question_id")
            if not question_id:
                continue
            q_rows = _select_rows("questions", select="id,status", id=question_id)
            if q_rows and q_rows[0].get("status") == "researching":
                _patch_where("questions", {"id": question_id}, {
                    "status": "answered",
                    "answered_at": now_utc,
                    "updated_at": now_utc,
                })
                marked += 1
        return marked
    except Exception as exc:
        _warn_question_link_side_effect("mark answered failed on publish", article_slug, exc)
        return 0


def _cleanup_question_article_links(article_slug: str) -> int:
    """Remove question_articles rows that reference the given article slug.

    Returns the number of rows deleted (0 if none found or on error).
    """
    try:
        article_id = _get_article_id(article_slug)
        if not article_id:
            return 0
        rows = _select_rows("question_articles", select="question_id,article_id", article_id=article_id)
        if not rows:
            return 0
        deleted = 0
        for row in rows:
            question_id = row.get("question_id")
            if question_id and _delete_where("question_articles", {"question_id": question_id, "article_id": article_id}):
                deleted += 1
        return deleted
    except Exception as exc:
        _warn_question_link_side_effect("cleanup failed", article_slug, exc)
        return 0


def unpublish_article(pub_id: str, storage_dir: str = "storage") -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    success = publisher.unpublish(pub_id)
    # Clean up question_articles links so question pages don't reference
    # an unpublished article.
    qa_deleted = 0
    if success:
        qa_deleted = _cleanup_question_article_links(pub_id)
    return {
        "id": pub_id,
        "found": success,
        "status": "unpublished" if success else "missing",
        "question_article_links_removed": qa_deleted,
    }


def cleanup_test_post(pub_id: str, *, hard_delete: bool = False, storage_dir: str = "storage") -> dict:
    # Contentlayer pattern (2026-04-18): feed.json is the only canonical
    # source; mile_*.json singles are archived. We no longer check or
    # delete single files here.
    publisher = Publisher(storage_dir=storage_dir)
    feed = load_feed(storage_dir)
    had_feed_item = any(item.get("id") == pub_id for item in feed)

    if not had_feed_item:
        return {"id": pub_id, "found": False, "hard_delete": hard_delete}

    result = {
        "id": pub_id,
        "found": True,
        "hard_delete": hard_delete,
        "unpublished": publisher.unpublish(pub_id),
        "local_feed_removed": False,
        "supabase_deleted": False,
        "question_article_links_removed": 0,
    }

    # Always clean up question_articles links when cleaning up a post
    result["question_article_links_removed"] = _cleanup_question_article_links(pub_id)

    if not hard_delete:
        return result

    trimmed_feed = [item for item in feed if item.get("id") != pub_id]
    if len(trimmed_feed) != len(feed):
        # 2026-05-04 finding #17 修整：feed.json 寫入須與 publisher._append_to_feed
        # 同一 lock namespace 防 race
        from volpred.ops.shared_lock import shared_state_lock
        with shared_state_lock("publisher_feed", storage_dir=storage_dir):
            dump_json(_feed_path(storage_dir), trimmed_feed)
        result["local_feed_removed"] = True
        publisher._sync_feed_to_remote()  # internal use: keep remote feed in sync

    result["supabase_deleted"] = delete_article(pub_id)
    return result


def ensure_article_local_backups(
    *,
    repair: bool = False,
    include_non_published: bool = False,
    storage_dir: str = "storage",
) -> dict:
    result = ensure_local_article_backups(
        storage_dir=storage_dir,
        repair=repair,
        include_non_published=include_non_published,
    )
    write_ops_snapshot("article-backups", result, storage_dir=storage_dir)
    return result
