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
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
CANDIDATES = ROOT / "storage" / "publication_candidates.json"


def _load_tasks() -> tuple[dict | list, list]:
    if not NEXT_TASKS.exists():
        return [], []
    data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data, data.get("tasks", [])
    return data, data


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


def _kids_with_terminal_article_attempts(tasks: list) -> set[str]:
    """K-ids that already had any article task reach a terminal state.

    Terminal = succeeded / failed / superseded / closed.
    Used together with `_any_feed_coverage` to suppress infinite retry loops
    where (a) prior task ended terminal, (b) feed.json has K coverage under
    some non-`general` audience, (c) refill keeps re-flagging as
    uncovered_for_general → blind retry pollutes pool.

    2026-05-29 incident: K1151/K672/K957 — prior `_article_general` task
    'succeeded' but published article tagged audience=research; refill produced
    v2/v3/v4 endlessly. Proper fix is publisher audience-tagging audit
    (see platform_ops_audience_tag_audit_K1151_K672_K957); this guard stops
    bleeding while audit completes.
    """
    TERMINAL = {"succeeded", "failed", "superseded", "closed"}
    kids: set[str] = set()
    import re
    for t in tasks:
        if str(t.get("status") or "").lower() not in TERMINAL:
            continue
        # Only consider article tasks (auto-discovered daily_article).
        if str(t.get("task_type") or "") != "daily_article":
            continue
        tid = str(t.get("id") or "")
        if "_article_" not in tid:
            continue
        for key in ("k_id", "experiment_id"):
            v = t.get(key)
            if v:
                kids.add(str(v).upper())
        m = re.match(r"^(K\d{2,5})_article_", tid)
        if m:
            kids.add(m.group(1).upper())
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


# 2026-06-03 K1120/K1393 incident: 274 K's have audience=research coverage
# whose title is reader-friendly (no K-id / no statistical jargon). Refill
# kept auto-generating `_article_general` tasks for them; agents would write
# the general draft, audience gate in publisher.py would force-upgrade to
# research (≥2 academic keyword match), then duplicate gate would reject
# vs the existing research version. Net effect: task succeeded with zero
# content shipped + wasted hourly fire slot. Skip when research-side cover
# is already reader-friendly enough to serve general readers.
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
    for cand in pool:
        if len(new_entries) >= target:
            break
        kid = cand["k_id"]
        audiences_covered = cand.get("audiences_covered") or []
        needed_audience = "general" if "general" not in audiences_covered else "research"
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
        # 7th belt (2026-06-03 K1120/K1393): research-covered K whose
        # research article title is already reader-friendly serves general
        # readers; a general companion would dup-gate-reject. Skip.
        if needed_audience == "general" and _research_cover_is_reader_friendly(cand):
            continue
        priority = _score_to_priority(int(cand.get("score") or 0))
        # Pick retry suffix if base id already used by terminal task
        retry_suffix = _next_retry_suffix(kid, needed_audience, tasks)
        new_entries.append(_make_article_task(cand, priority, retry_suffix))

    if not new_entries:
        return {"ok": True, "added": 0, "reason": "no_new_candidates_passing_filter"}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_add": len(new_entries),
            "preview_ids": [e["id"] for e in new_entries],
        }

    tasks.extend(new_entries)
    _save_tasks(payload, tasks)
    return {
        "ok": True,
        "added": len(new_entries),
        "added_ids": [e["id"] for e in new_entries],
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
