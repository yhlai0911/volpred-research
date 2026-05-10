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
        if art.get("status") not in ("draft", "published", "scheduled"):
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


def _make_article_task(cand: dict, priority: int) -> dict:
    k_id = cand["k_id"]
    audiences_covered = cand.get("audiences_covered") or []
    needed_audience = "general" if "general" not in audiences_covered else "research"
    return {
        "id": f"{k_id}_article_{needed_audience}",
        "title": f"{k_id}: write {needed_audience}-audience article (auto-discovered uncovered K)",
        "description": (
            f"K {k_id} has verdict signal (score={cand.get('score')}, reasons={cand.get('reasons')}) "
            f"but no {needed_audience} article. Verdict preview: {(cand.get('verdict_preview') or '')[:280]}"
        ),
        "priority": priority,
        "status": "pending",
        "task_type": "daily_article",
        "source": "auto_discovered",
        "k_id": k_id,
        "tags": (cand.get("tags") or []) + ["auto-discovered", f"audience-{needed_audience}"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def refill(target: int, dry_run: bool = False) -> dict:
    if not CANDIDATES.exists():
        return {"ok": False, "reason": "publication_candidates.json missing", "added": 0}

    cand_data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    payload, tasks = _load_tasks()
    existing = _existing_ids(tasks)
    already_covered = _kids_with_general_article()

    # Compose ranked candidate list: top_10_uncovered first (highest signal),
    # then missing_research_top5 (prefer research over general for novelty),
    # then missing_general_top5. Then a 4th fallback tier (2026-05-07 fix):
    # all `candidates` array entries that are uncovered_for_general but score
    # too low (≤1) to make top_10 — without this fallback, ~97 K-experiments
    # silently never refill into next_tasks even though they need articles.
    # Sort fallback by score desc so least-bad-priority surface first.
    pool = []
    seen_in_pool: set[str] = set()
    for source_key in ("top_10_uncovered", "missing_research_top5", "missing_general_top5"):
        for cand in cand_data.get(source_key, []) or []:
            kid = cand.get("k_id")
            if not kid or kid in seen_in_pool:
                continue
            seen_in_pool.add(kid)
            pool.append(cand)

    # Fallback tier — score-0/1 uncovered K's from full candidates array.
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

    new_entries = []
    for cand in pool:
        if len(new_entries) >= target:
            break
        kid = cand["k_id"]
        # Skip if K-id already in next_tasks under ANY status — even completed
        # tasks shouldn't trigger duplicate article entries (they may have an
        # article task already, just not visible via covered_by).
        article_id = f"{kid}_article_general"
        if (kid in existing or article_id in existing
                or f"{kid}_article_research" in existing):
            continue
        # Belt-and-suspenders: skip if a general article already exists in
        # feed.json (publication_candidates' uncovered flag can lag).
        if kid.upper() in already_covered:
            continue
        # 3rd belt: candidates may have populated `covered_by` but stale
        # `audiences_covered=[]` (pre-2026-04-14 audience metadata gap).
        # 2026-05-11 K665 incident: candidate had covered_by=mile_b5fe2026 but
        # audiences_covered=[] because covered article was audience=null legacy.
        # Honor covered_by directly — if any milestone covers this K, skip.
        if cand.get("covered_by"):
            continue
        priority = _score_to_priority(int(cand.get("score") or 0))
        new_entries.append(_make_article_task(cand, priority))

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
