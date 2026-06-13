"""Refill storage/next_tasks.json from existing research-gap signal.

Triggered by continue_task_dispatch when agentable + main_thread < threshold.
Pulls from canonical research-gap sources already maintained by the system:

1. storage/publication_candidates.json
   - top_10_uncovered: K-experiments with passing verdict but no published article
   - missing_general_top5 / missing_research_top5: audience gaps
2. (future) research_program.md backlog section

Each refill entry carries `task_type='daily_article'` (audience-driven write
task) or `task_type='experiment'` (follow-up K) and `source='auto_discovered'`
so the dispatcher's existing P1-conservative gate doesn't drag everything to
main_thread.

Hard rules:
- Skip K-ids already present in next_tasks (any status) to avoid dup
- Skip K-ids whose experiments/<id>/ already has results.json AND is in
  publication_candidates as uncovered (article task only — don't re-run
  the experiment)
- Default priority: derive from candidate score (3+ → P3; 4+ → P2; 5+ → P1)
- Write new tasks with status='pending' and `created_at` = now
- Idempotent: rerunning is safe (dup-skip prevents double-add)

Usage:
  uv run python scripts/refill_task_pool.py --dry-run
  uv run python scripts/refill_task_pool.py --apply --target 6
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
CANDIDATES = ROOT / "storage" / "publication_candidates.json"


def _load_tasks(max_retries: int = 5, sleep_s: float = 0.1) -> tuple[dict | list, list]:
    if not NEXT_TASKS.exists():
        return [], []
    last_err: Exception | None = None
    for attempt in range(max_retries):
        with NEXT_TASKS.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                last_err = exc
            else:
                if isinstance(data, dict):
                    return data, data.get("tasks", [])
                return data, data
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        if attempt < max_retries - 1:
            time.sleep(sleep_s)
    raise SystemExit(f"failed to parse {NEXT_TASKS} after {max_retries} retries: {last_err}")


def _save_tasks(payload: dict | list, tasks: list) -> None:
    if isinstance(payload, dict) and "tasks" in payload:
        payload["tasks"] = tasks
        out = payload
    else:
        out = tasks
    NEXT_TASKS.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _existing_ids(tasks: list) -> set[str]:
    ids: set[str] = set()
    for t in tasks:
        for key in ("id", "k_id", "experiment_id"):
            v = t.get(key)
            if v:
                ids.add(str(v))
    return ids


def _live_kids(tasks: list) -> set[str]:
    """K-ids whose article task is still 'live' (should not be retried).

    Live = pending / claimed / in_progress / blocked / pending_main_thread.
    Excludes terminal states (succeeded / failed / superseded / closed) — those
    are eligible for v2 retry IF feed.json still lacks the audience article.

    2026-05-29 fix: K1157 / K672 / K1151 had `_article_general` task in
    'succeeded' status but feed.json had no general-audience article →
    `_kids_with_general_article` correctly flagged them as uncovered, but the
    old `_existing_ids`-only filter blanket-skipped them, leaving the refill
    pool dry. The task receipt was unreliable; trust feed.json.
    """
    LIVE = {"pending", "claimed", "in_progress", "blocked",
            "pending_main_thread", "compute_queued",
            "decision_made_awaiting_body_rewrite"}
    kids: set[str] = set()
    for t in tasks:
        if str(t.get("status") or "").lower() not in LIVE:
            continue
        for key in ("k_id", "experiment_id"):
            v = t.get(key)
            if v:
                kids.add(str(v).upper())
        # Extract K-id from task id like 'K1157_article_general' or 'K1157_v2'.
        import re
        tid = str(t.get("id") or "")
        m = re.match(r"^(K\d{2,5}[a-z_]*)", tid)
        if m:
            kids.add(m.group(1).upper())
    return kids


# Publish-time audience gate became active in scripts/publish_draft.py at
# 2026-05-28T20:29:54Z (when platform_ops_audience_tag_audit_K1151_K672_K957
# completed). Pre-gate: publisher silently upcast general→research → article
# tasks succeeded with wrong-audience entries → refill flagged uncovered_for_general
# → v2/v3/v4 retry pollution. Post-gate: publish_draft returns code 7 on upcast,
# so retries are safe. We treat "all terminal article tasks predate this gate"
# as a release valve — those K-ids re-enter the candidate pool.
_AUDIENCE_GATE_ENABLED_AT = "2026-05-28T20:29:54+00:00"


def _kids_with_terminal_article_attempts(tasks: list) -> set[str]:
    """K-ids whose terminal article tasks include at least one post-gate failure.

    Terminal = succeeded / failed / superseded / closed.
    Used together with `_any_feed_coverage` to suppress infinite retry loops
    where (a) prior task ended terminal, (b) feed.json has K coverage under
    some non-`general` audience, (c) refill keeps re-flagging as
    uncovered_for_general → blind retry pollutes pool.

    2026-05-29 incident: K1151/K672/K957 — prior `_article_general` task
    'succeeded' but published article tagged audience=research; refill produced
    v2/v3/v4 endlessly. Proper fix was publisher audience-tagging audit
    (see platform_ops_audience_tag_audit_K1151_K672_K957) which added a
    publish-time gate in scripts/publish_draft.py. After the gate is active,
    a K whose ALL terminal article attempts predate the gate is safe to retry —
    a future failure mode (publisher would upcast again) is now caught by the
    gate (exit 7), not silently swallowed.

    2026-06-07 follow-up: pre-fix this helper kept K672/K957/K1151/K593/K1021
    audit_pending forever even though their last terminal task predated the gate,
    leaving refill pool permanently dry. Now we only block K-ids that have at
    least one post-gate terminal attempt (i.e., the gate was active and the
    retry still failed → audit_pending is the right state).
    """
    from datetime import datetime

    TERMINAL = {"succeeded", "failed", "superseded", "closed"}
    try:
        gate_ts = datetime.fromisoformat(_AUDIENCE_GATE_ENABLED_AT)
    except ValueError:
        gate_ts = None

    per_kid: dict[str, list[object]] = {}
    import re
    for t in tasks:
        if str(t.get("status") or "").lower() not in TERMINAL:
            continue
        if str(t.get("task_type") or "") != "daily_article":
            continue
        tid = str(t.get("id") or "")
        if "_article_" not in tid:
            continue
        candidate_kids: set[str] = set()
        for key in ("k_id", "experiment_id"):
            v = t.get(key)
            if v:
                candidate_kids.add(str(v).upper())
        m = re.match(r"^(K\d{2,5})_article_", tid)
        if m:
            candidate_kids.add(m.group(1).upper())
        if not candidate_kids:
            continue
        completed = t.get("completed_at")
        for kid in candidate_kids:
            per_kid.setdefault(kid, []).append(completed)

    kids: set[str] = set()
    for kid, completed_list in per_kid.items():
        if gate_ts is None:
            kids.add(kid)
            continue
        # Block only if any terminal attempt completed AT OR AFTER the gate.
        # Date-only / null / unparsable completed_at → treat as pre-gate
        # (the 2026-05-04/05 dateless entries are all pre-gate by construction).
        for c in completed_list:
            if not c or not isinstance(c, str):
                continue
            try:
                ts = datetime.fromisoformat(c)
            except ValueError:
                # date-only like "2026-05-05" → pre-gate
                continue
            if ts.tzinfo is None:
                continue  # naive timestamp — skip, treat as ambiguous (pre-gate)
            if ts >= gate_ts:
                kids.add(kid)
                break
    return kids


def _kids_with_succeeded_article_attempt(tasks: list, audience: str) -> set[str]:
    """K-ids with a succeeded article task for the given audience.

    2026-06-08 retry-v2 pollution: several K's (K676/K696/K707/K717/K904)
    already had a succeeded `*_article_general` task plus feed coverage, but
    candidate audience metadata still showed only `research`, so refill created
    `*_article_general_v2` retries. Once a general article task has succeeded
    and feed already references the K, blind auto-retry is the wrong action;
    it should be handled by a targeted audience/provenance audit instead.
    """
    import re

    want = f"_article_{audience}"
    kids: set[str] = set()
    for t in tasks:
        if str(t.get("status") or "").lower() != "succeeded":
            continue
        if str(t.get("task_type") or "") != "daily_article":
            continue
        tid = str(t.get("id") or "")
        if want not in tid:
            continue
        candidate_kids: set[str] = set()
        for key in ("k_id", "experiment_id"):
            v = t.get(key)
            if v:
                candidate_kids.add(str(v).upper())
        m = re.match(r"^(K\d{2,5})_article_", tid)
        if m:
            candidate_kids.add(m.group(1).upper())
        kids.update(candidate_kids)
    return kids


def _any_feed_coverage_kids() -> set[str]:
    """K-ids referenced by ANY feed article regardless of audience.

    Pairs with `_kids_with_terminal_article_attempts` — when a K already has
    feed coverage (even mis-tagged audience) AND a prior terminal article
    task, retry is the wrong fix; audience-tag audit is.
    """
    import re
    kids: set[str] = set()
    feed_path = ROOT / "storage" / "reports" / "feed.json"
    if not feed_path.exists():
        return kids
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception:
        return kids
    for art in feed:
        if not isinstance(art, dict):
            continue
        # 2026-05-31 fix: include "archived" — 122 archived articles carry K refs
        # and represent real historical coverage; excluding them let refill
        # auto-create v2 dups for K274/K288/K319 (audience=research+archived
        # invisible to both dedup helpers). Retracted/unpublished still excluded
        # (those are explicit "not coverage").
        if art.get("status") not in ("draft", "published", "scheduled", "archived"):
            continue
        details = art.get("details") or {}
        refs = details.get("experiment_refs") if isinstance(details, dict) else []
        if isinstance(refs, list):
            for r in refs:
                kids.add(str(r).upper())
        title = art.get("title", "") or ""
        for m in re.findall(r"\bK\d{2,5}[a-z_]*\b", title):
            kids.add(m.upper())
    return kids


def _next_retry_suffix(k_id: str, audience: str, tasks: list) -> str:
    """Pick next v2/v3/... suffix for a retry K article task id.

    Returns '' if base id `<K>_article_<audience>` not in existing, else 'v2'
    if v2 not in existing, else 'v3', etc.
    """
    base = f"{k_id}_article_{audience}"
    ids = {str(t.get("id") or "") for t in tasks}
    if base not in ids:
        return ""
    for n in range(2, 20):
        cand = f"{base}_v{n}"
        if cand not in ids:
            return f"v{n}"
    return "v20"


def _kids_with_general_article() -> set[str]:
    """Return set of K-ids that already have a non-unpublished general article.

    Without this guard, refill_task_pool reads publication_candidates' uncovered
    flag and proposes article tasks for K-ids that DO have an article — that
    flag is computed against covered_by metadata which can lag feed.json reality
    (2026-05-04 K518 incident). Belt-and-suspenders dedup.
    """
    import re
    kids: set[str] = set()
    feed_path = ROOT / "storage" / "reports" / "feed.json"
    if not feed_path.exists():
        return kids
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception:
        return kids
    for art in feed:
        if not isinstance(art, dict):
            continue
        # Pre-2026-04-14 articles have audience=None (metadata gap); treat
        # them as 'general' for dedup purposes since they were the platform's
        # default-audience tone before explicit research/general split.
        # 2026-05-11 K622/K630 incidents: dropped audience=None coverage and
        # auto-discovery re-queued already-covered Ks two days in a row.
        audience = art.get("audience")
        if audience not in (None, "", "general"):
            continue
        # 2026-05-31 fix: archived articles still represent K coverage (the
        # general-audience article was published then archived; refill must
        # not auto-recreate it). See _any_feed_coverage_kids same-date fix.
        if art.get("status") not in ("draft", "published", "scheduled", "archived"):
            continue
        details = art.get("details") or {}
        refs = details.get("experiment_refs") if isinstance(details, dict) else []
        if isinstance(refs, list):
            for r in refs:
                kids.add(str(r).upper())
        title = art.get("title", "") or ""
        for m in re.findall(r"\bK\d{2,5}[a-z_]*\b", title):
            kids.add(m.upper())
    return kids


def _score_to_priority(score: int) -> int:
    """Article-task priority cap (2026-05-04 fix).

    Original mapping (5+→P1) caused auto-discovered article tasks to fall
    into the dispatcher's P1-conservative-main-thread bucket — they
    weren't actually critical-tier (just popular K-experiments needing
    write-up). Cap at P3 so they stay agentable. P4 floor for low-score
    candidates.
    """
    if score >= 4:
        return 3
    return 4


def _has_publishable_title(cand: dict) -> bool:
    """Require a non-empty candidate title before enqueueing a reader-facing task.

    2026-05-28 K1378 incident: publication_candidates surfaced uncovered K rows
    with blank `title`, which then became generic daily_article queue entries.
    Those tasks lack a stable article angle and can easily correspond to stale or
    superseded internal robustness experiments. Refill should skip them until the
    upstream candidate metadata is repaired.
    """
    title = str(cand.get("title") or "").strip()
    return bool(title)


# 2026-06-03 K1120/K1393 incident introduced a conservative "7th belt":
# if research coverage already used a reader-friendly title, refill skipped
# the general companion entirely. 2026-06-06 saturation audit showed this was
# too aggressive: K593/K683/K1021 had legitimate dual-audience value
# (different evidence packaging / framing / tone) but were filtered out,
# leaving the candidate pool dry. We keep the helper for diagnostics, but the
# actual hard stop now lives at publish time:
#   1. audience gate blocks research-style drafts masquerading as general
#   2. duplicate gate blocks an actual (K-id, general) collision
# Refill should not pre-emptively suppress the queue.
_ACADEMIC_TITLE_RE = re.compile(
    r"K\d+|p[-\s]?value|t[-\s]?stat|QLIKE|Sharpe|Bonferroni|"
    r"bootstrap|MLE|cointegration|GARCH|Harvey|Diebold|"
    r"DM\s+test|HAR[-\s]?RV|MCS|VaR",
    re.IGNORECASE,
)


def _research_cover_is_reader_friendly(cand: dict) -> bool:
    """True if K already has audience=research article(s) whose title is
    free of academic jargon — in that case the research article already
    serves general readers and a separate general companion would (a) get
    force-upgraded by the audience gate, (b) be rejected by the duplicate
    gate. Refill should skip.
    """
    if "research" not in (cand.get("audiences_covered") or []):
        return False
    for art in cand.get("covered_by") or []:
        if not isinstance(art, dict):
            continue
        if art.get("audience") != "research":
            continue
        title = str(art.get("title") or "")
        if title and not _ACADEMIC_TITLE_RE.search(title):
            return True
    return False


def _is_retracted_or_overturned_candidate(cand: dict) -> bool:
    """Skip candidates whose canonical angle is already overturned/retracted.

    2026-05-30 K680 incident: an audience-gap fallback re-queued a
    general-audience write task for a K whose own title was
    "OVERTURNED" and whose primary existing coverage was a retraction.
    These are legitimate research-history artifacts, but they should not
    be auto-materialized into new daily_article tasks by the refill loop.
    """
    needles = ("overturned", "retracted", "撤稿", "推翻")
    haystacks = [
        str(cand.get("title") or ""),
        str(cand.get("verdict_preview") or ""),
        " ".join(str(t) for t in (cand.get("tags") or [])),
    ]
    covered_by = cand.get("covered_by") or []
    for art in covered_by:
        if not isinstance(art, dict):
            continue
        haystacks.append(str(art.get("title") or ""))
        haystacks.append(str(art.get("status") or ""))
    merged = "\n".join(haystacks).lower()
    return any(token in merged for token in needles)


def _is_invalidated_artifact_candidate(cand: dict) -> bool:
    """Skip candidates whose latest knowledge explicitly says unusable artifact."""
    haystacks = [
        str(cand.get("title") or ""),
        str(cand.get("verdict_preview") or ""),
        " ".join(str(t) for t in (cand.get("tags") or [])),
    ]
    merged = "\n".join(haystacks).lower()
    needles = (
        "codex review fail",
        "formal conclusion 不可採信",
        "formal conclusion not trustworthy",
        "artifact 作廢",
        "invalidated artifact",
        "設計錯誤作廢",
    )
    return any(token in merged for token in needles)


# 2026-06-08 K159/K181/K495/K510/K737 incident (3-strike trigger on refill bug):
# hourly-00 codex-cli refill picked 5 K's whose only difference from the existing
# research-tagged coverage was audience (research vs general). Narrative arc was
# identical (same K-id, same conclusion summary, same data); adding a "general
# companion" would have produced 5 duplicates by the publisher's narrative-arc
# rule but the refill belts didn't catch it because _kids_with_general_article
# only matched audience=None/general and audit_pending_kids required a prior
# terminal task. The 5 K's had heavy archived+published research coverage with no
# prior task → all gates whiffed.
_SATURATION_THRESHOLD = 2


def _is_research_saturated(cand: dict) -> bool:
    """True if K already has >= _SATURATION_THRESHOLD research articles in
    feed.json (published+archived combined). Adding a "general companion" in
    this state is a narrative-arc dup, not an audience gap.

    Reasoning: a K with multiple research articles has been told once + reframed
    + (often) retracted/rewritten. The user-facing story is well-trodden. The
    publisher's 3-layer dedup (candidates / grep / matrix) and narrative-arc
    rule will reject the new draft regardless; refill should not waste an agent
    slot generating it. Better to defer refill to a fresh K with no coverage.

    Saturation-aware refill is intentionally PER-K, not per-cluster — the
    7th belt (_breached_clusters) handles cluster-level over-representation.
    """
    covered_by = cand.get("covered_by") or []
    research_count = 0
    for art in covered_by:
        if not isinstance(art, dict):
            continue
        if art.get("audience") != "research":
            continue
        if art.get("status") not in ("published", "archived", "draft", "scheduled"):
            continue
        research_count += 1
    return research_count >= _SATURATION_THRESHOLD


def _make_article_task(cand: dict, priority: int, retry_suffix: str = "") -> dict:
    k_id = cand["k_id"]
    audiences_covered = cand.get("audiences_covered") or []
    needed_audience = "general" if "general" not in audiences_covered else "research"
    task_id = f"{k_id}_article_{needed_audience}"
    if retry_suffix:
        task_id = f"{task_id}_{retry_suffix}"
    title_prefix = f"{k_id}"
    retry_note = f" [retry-{retry_suffix}]" if retry_suffix else ""
    return {
        "id": task_id,
        "title": f"{title_prefix}: write {needed_audience}-audience article{retry_note} (auto-discovered uncovered K)",
        "description": (
            f"K {k_id} has verdict signal (score={cand.get('score')}, reasons={cand.get('reasons')}) "
            f"but no {needed_audience} article in feed.json. "
            f"{'Prior task terminal but feed lacks coverage — retry.' if retry_suffix else ''} "
            f"Verdict preview: {(cand.get('verdict_preview') or '')[:280]}"
        ),
        "priority": priority,
        "status": "pending",
        "task_type": "daily_article",
        "source": "auto_discovered",
        "k_id": k_id,
        "tags": (cand.get("tags") or []) + ["auto-discovered", f"audience-{needed_audience}"]
              + ([f"retry-{retry_suffix}"] if retry_suffix else []),
        "topic_cluster": cand.get("topic_cluster"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _breached_clusters() -> set[str]:
    """Clusters whose recent feed share exceeds DOMINANT_RATIO_LIMIT.
    Used to defer over-represented topics so the feed stops 故步自封 on
    VIX/SPY/vol-forecast (user 2026-06-07). Safe no-op if module unavailable."""
    try:
        src = str(ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from volpred.topic_clusters import DOMINANT_RATIO_LIMIT, recent_cluster_counts
        counts, total = recent_cluster_counts(days=30)
        if not total:
            return set()
        return {cl for cl, n in counts.items() if (n / total) > DOMINANT_RATIO_LIMIT}
    except Exception:
        return set()


def _cand_cluster(cand: dict) -> str | None:
    try:
        from volpred.topic_clusters import classify_topic_cluster
        return classify_topic_cluster(
            str(cand.get("title") or ""),
            [str(t) for t in (cand.get("tags") or [])],
        )
    except Exception:
        return None


RESEARCH_PROGRAM = ROOT / "research_program.md"

# Subsection headers under which open `- [ ]` items are NOT auto-queueable because
# they require data we don't have. Matched as substrings against the nearest
# preceding `###` header (case-insensitive). Everything else with the right shape
# is treated as immediately actionable (no new data needed).
_BLOCKED_RESEARCH_HEADER_TOKENS = ("blocked", "需 5-min", "需 5min", "需 options", "需 tick", "5-min 數據", "tick 數據")

# 2026-06-09: the fallback originally scanned ONLY `## 前沿文獻方向` (curated arXiv
# directions). K1420-K1432 burned through that curated list in ~2 days, so the
# pool kept going critical and required manual seeding. Broaden to scan ALL
# sections' open `- [ ]` items so the ~34 remaining research directions (台股財報,
# 金融股, microstructure, …) feed the pool — BUT filter out non-research lines
# that share the `- [ ]` shape: paper-workflow tooling (latex/citation/投稿/審查)
# and data-blocked items (no yfinance data). A line OR its header hitting any of
# these tokens is skipped.
_NON_RESEARCH_LINE_TOKENS = (
    "/latex", "latex-academic", "/citation", "citation-verifier", "引用驗證",
    "投稿", "校稿", "cover letter", "graphical abstract", "highlights",
    "adversarial review", "codex", "全面審查", "robustness（refit",
    "blocked", "需要 vix futures", "yfinance 無", "5-min 數據", "tick data",
    "需 options", "需 tick", "iv surface 圖像", "eta 2026", "數據累積到",
    "修正 gemini", "gemini v4", "gemini v3", "gemini 的",  # paper-review-fix items
)

_KID_IN_LINE_RE = re.compile(r"[Kk]\d{2,5}[a-z]?")


def _line_references_done_experiment(line: str) -> bool:
    """True if the line mentions a K-id that already has a completed experiment
    (experiments/k<id>/*results.json) — avoids re-queuing already-done directions
    (e.g. 'K1061: extend...' when experiments/k1061 already exists, or a follow-up
    idea anchored on a finding K whose work is done)."""
    for m in _KID_IN_LINE_RE.findall(line):
        d = ROOT / "experiments" / m.lower()
        if d.is_dir() and any(d.glob("*results*.json")):
            return True
    return False


def _is_non_research_line(line_low: str, header_low: str) -> bool:
    if any(tok in header_low for tok in _BLOCKED_RESEARCH_HEADER_TOKENS):
        return True
    if any(tok in line_low for tok in _NON_RESEARCH_LINE_TOKENS):
        return True
    return False


def _slugify_research(title: str) -> str:
    """Stable ASCII-ish slug for a research-direction title → task id suffix."""
    import re as _re
    # Keep ascii alnum; collapse the rest to underscores. Non-ascii (Chinese) is
    # dropped, so we fall back to a short hash to keep ids unique & stable.
    base = _re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()
    base = _re.sub(r"_+", "_", base)[:48].strip("_")
    if len(base) < 6:  # mostly-Chinese title → hash for stability
        import hashlib
        base = "rp_" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    return base


_ARC_FEED_CACHE: list | None = None


def _arc_covered_by_recent_article(direction_text: str, days: int = 90) -> list[dict]:
    """Return recent feed articles whose narrative arc (asset entities) already
    covers this backlog direction. Entity-overlap only (conclusion unknown at
    direction stage). See src/volpred/publisher/arc_dedup.py for the model.
    Fail-open on import/IO errors — this is a filter, not a hard dependency."""
    global _ARC_FEED_CACHE
    try:
        import sys as _sys

        src = str(ROOT / "src")
        if src not in _sys.path:
            _sys.path.insert(0, src)
        from volpred.publisher.arc_dedup import (
            _CORE_ENTITIES,
            extract_entities,
        )

        def _direction_level_overlap(new_e: set, old_e: set) -> bool:
            # 2026-06-11 calibration: at direction level (conclusion unknown)
            # the single-distinctive-entity rule produced false positives
            # (MOVE-lead-lag direction blocked by a TSMC-revenue article that
            # merely mentioned MOVE). Require >=2 shared DISTINCTIVE entities
            # to block; single-entity overlaps are logged by the caller's
            # print but no longer block. Publisher-side gate (entity+conclusion)
            # remains the hard backstop at publish time.
            distinctive = (new_e & old_e) - _CORE_ENTITIES
            return len(distinctive) >= 2

        if _ARC_FEED_CACHE is None:
            feed_path = ROOT / "storage" / "reports" / "feed.json"
            _ARC_FEED_CACHE = json.loads(feed_path.read_text(encoding="utf-8"))
        new_ents = extract_entities(direction_text)
        if not new_ents:
            return []
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        hits: list[dict] = []
        for existing in _ARC_FEED_CACHE[:300]:
            if existing.get("status") in ("unpublished", "retracted"):
                continue
            ts_raw = existing.get("published_at") or existing.get("created_at") or ""
            try:
                from dateutil.parser import parse as dtparse

                if dtparse(ts_raw).astimezone(timezone.utc) < cutoff:
                    continue
            except Exception:
                pass
            ex_text = f"{existing.get('title', '')}\n{existing.get('description') or ''}"
            ex_ents = extract_entities(ex_text)
            if _direction_level_overlap(new_ents, ex_ents):
                hits.append(
                    {
                        "id": existing.get("id", "?"),
                        "title": existing.get("title", "?"),
                        "shared_entities": sorted(new_ents & ex_ents),
                    }
                )
        return hits
    except Exception:
        return []


def _research_backlog_candidates(tasks: list, existing_ids: set[str], limit: int = 2) -> list[dict]:
    """Parse research_program.md for OPEN `- [ ]` research directions that need no
    new data, deduped against tasks already queued. Returns experiment-task dicts.

    This implements the long-commented `(future) research_program.md backlog`
    fallback (module docstring item 2). It is the durable fix for the recurring
    production_pending warn/critical: when the article candidate pool legitimately
    exhausts (all uncovered K's are research-saturated, 8th belt), the pool should
    keep flowing by queueing NEW research — more research = new findings = new
    writable articles (Mission #2 → #1), instead of going idle.

    Safety: only OPEN `- [x]`→excluded, only data-unblocked subsections, hard cap
    `limit` per refill (don't flood with unvetted research), idempotent slug-dedup.
    """
    if not RESEARCH_PROGRAM.exists():
        return []
    import re as _re
    text = RESEARCH_PROGRAM.read_text(encoding="utf-8", errors="replace")
    out: list[dict] = []
    current_header = ""
    current_h2 = ""
    # 2026-06-09: scan ALL sections (not just 前沿文獻方向) so the broader backlog
    # feeds the pool; filter non-research lines via _is_non_research_line. Skip the
    # paper-writing section (面向 H 論文 / 論文撰寫) wholesale — its `- [ ]` items are
    # paper-workflow steps, not research experiments.
    # Existing research-fallback task slugs already queued (any status) → skip.
    queued_research_slugs = {
        str(t.get("research_slug")) for t in tasks if t.get("research_slug")
    }
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## ") and not line.startswith("###"):
            current_h2 = line.lstrip("#").strip()
            current_header = ""
            continue
        if line.startswith("###"):
            current_header = line.lstrip("#").strip().lower()
            continue
        # Skip the paper-writing 面向 wholesale (paper-workflow, not research).
        if ("論文" in current_h2 or "面向 H" in current_h2 or "投稿" in current_h2):
            continue
        if not line.startswith("- [ ]"):
            continue
        # Skip non-research lines (paper tooling / data-blocked).
        if _is_non_research_line(line.lower(), current_header):
            continue
        # Skip directions anchored on an already-completed experiment K-id.
        if _line_references_done_experiment(line):
            continue
        body = line[len("- [ ]"):].strip()
        # Strip leading decoration: ★, **, ~~.
        title_raw = body
        title_raw = title_raw.replace("★", "").replace("**", "").replace("~~", "").strip()
        # Title = text up to first em-dash / 「—」 / period (drops the citation tail).
        title = _re.split(r"\s+[—–-]\s+|。", title_raw)[0].strip()
        if len(title) < 6:
            continue
        slug = _slugify_research(title)
        if slug in queued_research_slugs:
            continue
        task_id = f"research_{slug}"
        if task_id in existing_ids:
            continue
        # Loose dup-guard: if any existing task title already contains this title, skip.
        tl = title.lower()
        if any(tl and tl in str(t.get("title") or "").lower() for t in tasks):
            continue
        # Arc-level dup-guard (2026-06-10 K1449/K1091 incident): a direction whose
        # asset entities + likely-conclusion arc is already covered by a recent
        # article is a duplicate-in-the-making — stop it at the source, before an
        # experiment and an article get built on it. Conclusion is unknown at
        # direction stage, so we block on entity-arc overlap with ANY conclusion
        # class (conservative: a covered asset-pair needs a genuinely new angle,
        # which a one-line backlog item can't establish).
        # Direction-level arc dedup should compare the normalized backlog title,
        # not the entire explanatory tail after "—". The tail often contains
        # example assets / citations used to motivate the idea; feeding that
        # whole line into entity extraction over-blocks unrelated directions and
        # can drain the pool to zero.
        arc_hits = _arc_covered_by_recent_article(title)
        if arc_hits:
            print(
                f"  [refill] skip research direction (arc already covered by "
                f"{arc_hits[0]['id']} '{arc_hits[0]['title'][:40]}', shared="
                f"{arc_hits[0]['shared_entities']}): {title[:50]}"
            )
            continue
        out.append(_make_research_task(title, title_raw, current_header, slug, task_id))
        if len(out) >= limit:
            break
    return out


def _journal_discovery_dispatch_task(tasks: list, existing_ids: set[str]) -> list[dict]:
    """Tier 3 fallback: when article candidates AND research-backlog both dry,
    queue a platform_ops task to dispatch a journal-discovery agent.

    The agent runs `scripts/agent_prompts/journal_topic_scan.md` to scan top-tier
    journals (JBF/JFE/RFS/JoE/JPM/FAJ/CFA Institute) for 1-2 year hot topics and
    append 5-10 new directions to research_program.md so subsequent refills have
    fresh inventory. This breaks the dry-pool cycle when the research-program.md
    backlog saturates with succeeded slugs (e.g. 54/67 slugs = succeeded → all
    visible open items are slug-dedup'd; only new directions help).

    Idempotency: skip if any `journal_discovery_*` task is currently live
    (pending/claimed/in_progress/blocked) OR completed within the last 24h —
    avoids agent-flood when refill fires every hour with same dry state.

    Returns: empty list if dispatch task already exists / recently completed,
             else a single-element list with the new dispatch task.
    """
    from datetime import datetime, timedelta, timezone

    LIVE = {"pending", "claimed", "in_progress", "blocked", "pending_main_thread"}
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=24)
    for t in tasks:
        tid = str(t.get("id") or "")
        if not tid.startswith("journal_discovery_"):
            continue
        status = str(t.get("status") or "").lower()
        if status in LIVE:
            return []  # already pending — don't double-queue
        completed_at = t.get("completed_at") or t.get("created_at")
        if completed_at and isinstance(completed_at, str):
            try:
                ts = datetime.fromisoformat(completed_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    return []  # recent dispatch within 24h
            except ValueError:
                pass

    today = now_utc.strftime("%Y%m%d")
    task_id = f"journal_discovery_{today}"
    # Daily cap: only one journal-discovery dispatch per calendar day even if
    # task object isn't found via the LIVE/recent scan above (e.g. archived).
    if task_id in existing_ids:
        return []

    return [{
        "id": task_id,
        "title": "Journal-discovery 派工: 補 research_program.md backlog (refill pool dry fallback)",
        "description": (
            "Article candidate pool + research-backlog 都 dry "
            "(refill no_new_candidates_passing_filter). "
            "派 general-purpose agent 跑 scripts/agent_prompts/journal_topic_scan.md，"
            "從頂尖期刊（JBF/JFE/RFS/JoE/JPM/FAJ/CFA 等近 1-2 年）挖熱門主題，"
            "補 5-10 個新方向到 research_program.md 對應 section，完成後下一輪 refill 自動取用。"
            " 24h 內 idempotent；勿手動重派。"
        ),
        "priority": 2,
        "status": "pending",
        "task_type": "platform_ops",
        "source": "auto_journal_discovery_fallback",
        "tags": ["auto-journal-discovery", "research-backlog-refresh", "tier3-fallback"],
        "created_at": now_utc.isoformat(timespec="seconds"),
    }]


def _make_research_task(title: str, full_line: str, header: str, slug: str, task_id: str) -> dict:
    return {
        "id": task_id,
        "title": f"研究 backlog fallback: {title}",
        "description": (
            f"Article pool exhausted (all uncovered K research-saturated) → auto-queued "
            f"NEW research from research_program.md open backlog to keep the pipeline "
            f"flowing (Mission #2 research → #1 articles). "
            f"方向: {full_line[:300]} | 來源 section: {header}. "
            f"主線程派 experiment agent 前先讀 docs/error_log.md + 查相似 K + ≥3 篇文獻; "
            f"完成後 Codex review → knowledge.json → 可發佈排文章。"
        ),
        "priority": 3,
        "status": "pending",
        "task_type": "experiment",
        "source": "auto_research_fallback",
        "research_slug": slug,
        "tags": ["auto-research-fallback", "research-program-backlog"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def refill(target: int, dry_run: bool = False) -> dict:
    if not CANDIDATES.exists():
        return {"ok": False, "reason": "publication_candidates.json missing", "added": 0}

    cand_data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    payload, tasks = _load_tasks()
    existing = _existing_ids(tasks)
    live_kids = _live_kids(tasks)
    already_covered = _kids_with_general_article()
    # 2026-05-29 audience-mismatch retry-loop guard (see helper docstrings).
    terminal_article_kids = _kids_with_terminal_article_attempts(tasks)
    succeeded_general_kids = _kids_with_succeeded_article_attempt(tasks, "general")
    any_feed_kids = _any_feed_coverage_kids()
    audit_pending_kids = terminal_article_kids & any_feed_kids

    # Compose ranked candidate list: top_10_uncovered first (highest signal),
    # then missing_research_top5 (prefer research over general for novelty),
    # then missing_general_top5. If those shortlist slices are exhausted by
    # guards (e.g. audit_pending, already_covered), continue scanning the full
    # candidate table for audience-gap rows before falling back to low-score
    # fully-uncovered experiments.
    pool = []
    seen_in_pool: set[str] = set()
    for source_key in ("top_10_uncovered", "missing_research_top5", "missing_general_top5"):
        for cand in cand_data.get(source_key, []) or []:
            kid = cand.get("k_id")
            if not kid or kid in seen_in_pool:
                continue
            seen_in_pool.add(kid)
            pool.append(cand)

    # Fallback tier 1: full candidate table audience-gap rows beyond top5.
    # 2026-05-30 incident: top5 missing_general was fully occupied by
    # audit_pending K672/K1151/K957/K1086/K1404, leaving truly eligible
    # audience-gap candidates invisible and the refill pool dry.
    audience_gap_pool = []
    for cand in cand_data.get("candidates", []) or []:
        kid = cand.get("k_id")
        if not kid or kid in seen_in_pool:
            continue
        if int(cand.get("score") or 0) < 4:
            continue
        audiences_covered = cand.get("audiences_covered") or []
        collisions = cand.get("topic_family_collisions") or {}
        needed_audience = "general" if "general" not in audiences_covered else "research"
        if not cand.get("covered_by"):
            continue
        if "general" in audiences_covered and "research" in audiences_covered:
            continue
        if collisions.get(needed_audience):
            continue
        audience_gap_pool.append(cand)
    audience_gap_pool.sort(key=lambda c: (c.get("score") or 0), reverse=True)
    pool.extend(audience_gap_pool)

    # Fallback tier 2 — score-0/1 uncovered K's from full candidates array.
    fallback_pool = []
    for cand in cand_data.get("candidates", []) or []:
        kid = cand.get("k_id")
        if not kid or kid in seen_in_pool:
            continue
        if (cand.get("audiences_covered") or []):
            continue  # already has some audience coverage
        fallback_pool.append(cand)
    fallback_pool.sort(key=lambda c: c.get("score") or 0, reverse=True)
    pool.extend(fallback_pool)
    pool.sort(
        key=lambda c: (
            int(((c.get("topic_cluster_30d") or {}).get("count") or 0) > ((c.get("topic_cluster_30d") or {}).get("cap") or 999)),
            (c.get("topic_cluster_30d") or {}).get("count") or 0,
            -(c.get("score") or 0),
            c.get("k_id") or "",
        )
    )

    new_entries = []
    # 2026-06-07: Novelty-quota enforcement. The feed had drifted to ~39% VIX /
    # heavy SPY/vol-forecast (validate_feed_diversity FAIL) because refill only
    # picked "uncovered K" with no hard cluster gate. DEFER candidates in a
    # currently-breached dominant cluster — prefer contrarian/under-represented
    # topics first; only fall back to dominant ones if the non-dominant pool
    # can't meet target (better fewer-but-diverse than more-of-same).
    breached = _breached_clusters()
    deferred_dominant: list[dict] = []
    for cand in pool:
        if len(new_entries) >= target:
            break
        kid = cand["k_id"]
        audiences_covered = cand.get("audiences_covered") or []
        needed_audience = "general" if "general" not in audiences_covered else "research"
        if _is_invalidated_artifact_candidate(cand):
            continue
        # Skip if K has a LIVE task (pending/in_progress/blocked) — don't dup.
        # Terminal tasks (succeeded/failed/superseded) eligible for retry if
        # feed.json still lacks coverage (2026-05-29 fix; see _live_kids).
        if kid.upper() in live_kids:
            continue
        # Belt-and-suspenders: skip if a general article already exists in
        # feed.json (publication_candidates' uncovered flag can lag).
        if kid.upper() in already_covered:
            continue
        # 5th belt (2026-05-29): K had a terminal article task AND feed has
        # coverage under some audience → audience-tag mismatch (publisher bug),
        # not a missing-article case. Don't blind-retry; let
        # platform_ops_audience_tag_audit_K1151_K672_K957 (or equivalent) sort.
        if kid.upper() in audit_pending_kids:
            continue
        # 3rd belt: candidates may have populated `covered_by` but stale
        # `audiences_covered=[]` (pre-2026-04-14 audience metadata gap).
        # Legit audience-gap candidates (e.g. research exists, missing general)
        # must remain eligible; only suppress rows whose structured audience
        # coverage is missing altogether.
        if cand.get("covered_by") and not audiences_covered:
            continue
        # 4th belt: blank-title candidates are not publication-ready.
        if not _has_publishable_title(cand):
            continue
        # 6th belt: don't auto-queue reader-facing articles for candidates
        # whose own canonical status is already overturned/retracted.
        if _is_retracted_or_overturned_candidate(cand):
            continue
        # 7th belt (novelty quota): defer candidates in a breached dominant
        # cluster; fill from them last (below) only if target unmet.
        if breached and _cand_cluster(cand) in breached:
            deferred_dominant.append(cand)
            continue
        # 8th belt (2026-06-08): skip K already research-saturated. Audience-gap
        # (research-only → general) is a real signal only when the K has 1
        # research article worth a reader-facing reframe. ≥2 research articles
        # means the story has been told, reframed, possibly retracted — the
        # narrative-arc dedup will reject any new general draft.
        if _is_research_saturated(cand):
            continue
        priority = _score_to_priority(int(cand.get("score") or 0))
        # Pick retry suffix if base id already used by terminal task
        retry_suffix = _next_retry_suffix(kid, needed_audience, tasks)
        if (
            needed_audience == "general"
            and retry_suffix
            and kid.upper() in any_feed_kids
            and kid.upper() in succeeded_general_kids
        ):
            continue
        new_entries.append(_make_article_task(cand, priority, retry_suffix))

    # Fill remaining target from deferred dominant-cluster candidates only if the
    # contrarian/non-dominant pool was insufficient (avoid a dry pool).
    for cand in deferred_dominant:
        if len(new_entries) >= target:
            break
        kid = cand["k_id"]
        # 8th belt also applies to deferred dominant pool (2026-06-08).
        if _is_research_saturated(cand):
            continue
        audiences_covered = cand.get("audiences_covered") or []
        needed_audience = "general" if "general" not in audiences_covered else "research"
        priority = _score_to_priority(int(cand.get("score") or 0))
        retry_suffix = _next_retry_suffix(kid, needed_audience, tasks)
        if (
            needed_audience == "general"
            and retry_suffix
            and kid.upper() in any_feed_kids
            and kid.upper() in succeeded_general_kids
        ):
            continue
        new_entries.append(_make_article_task(cand, priority, retry_suffix))

    # Research-backlog fallback (2026-06-08 boss mandate「徹底解決 warning」):
    # when the article candidate pool is exhausted (all uncovered K's are
    # research-saturated → 8th belt drops them), keep the pool flowing by queueing
    # NEW research directions from research_program.md instead of going idle.
    fallback_reason = None
    if not new_entries:
        research_tasks = _research_backlog_candidates(
            tasks, existing, limit=max(1, min(2, target))
        )
        if research_tasks:
            new_entries.extend(research_tasks)
            fallback_reason = "research_backlog_fallback"

    # Tier-3 journal-discovery fallback (2026-06-14): when even research-backlog
    # is dry (e.g. 54/67 known directions are succeeded → slug-deduped), kick a
    # platform_ops task that dispatches a journal-discovery agent to populate
    # research_program.md from top-tier journals. 24h idempotent.
    if not new_entries:
        journal_tasks = _journal_discovery_dispatch_task(tasks, existing)
        if journal_tasks:
            new_entries.extend(journal_tasks)
            fallback_reason = "journal_discovery_dispatch"

    if not new_entries:
        return {"ok": True, "added": 0, "reason": "no_new_candidates_passing_filter"}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_add": len(new_entries),
            "preview_ids": [e["id"] for e in new_entries],
            **({"fallback": fallback_reason} if fallback_reason else {}),
        }

    tasks.extend(new_entries)
    _save_tasks(payload, tasks)
    return {
        "ok": True,
        "added": len(new_entries),
        "added_ids": [e["id"] for e in new_entries],
        **({"fallback": fallback_reason} if fallback_reason else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=4,
                        help="number of new tasks to attempt to add (default 4)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2

    result = refill(args.target, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("dry_run"):
            print(f"[refill] would add {result['would_add']} tasks: {result.get('preview_ids')}")
        elif result.get("added"):
            print(f"[refill] added {result['added']} tasks: {result['added_ids']}")
        else:
            print(f"[refill] no add — {result.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
