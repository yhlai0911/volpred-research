#!/usr/bin/env python3
"""One-shot backfill for tasks with null task_type + normalize experiment_review.

Heuristics (priority order):
  1. task_type == 'experiment_review' → paper_review (CLAUDE.md 11-class normalization)
  2. Title patterns inferring type:
     - Paper {1-10} / paper_ → paper_review (small fix) / paper_body (rewrite) / paper_decision (narrative)
     - K-digits / k-digits_ → experiment
     - audit / cron / ops / dashboard / alert / sync / pipeline → platform_ops
     - FB / trending → trending_repost
     - daily article / 補 draft → daily_article
  3. Default → platform_ops (catch-all for housekeeping)

Run:
  uv run python scripts/backfill_task_types.py --dry-run
  uv run python scripts/backfill_task_types.py --apply
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

# Two-stage classifier:
#  Stage 1 — paper-related (highest priority, action-verb decides sub-type)
#  Stage 2 — non-paper (K-experiment / ops / etc)
PAPER_INDICATOR = re.compile(r"\b(paper|Paper)[\s_]?\d+\b|^paper_(crypto|garch|leverage|prg|taiwan|vix|volatility|vt|eav|bitcoin|btc)", re.I)

PAPER_BODY_VERBS = re.compile(
    r"\b(body[_ ]?rewrite|body[_ ]?integration|body_v\d|main_v\d|integration[_ ]?plan|self[_ ]?contained|full[_ ]?rewrite)\b",
    re.I,
)
PAPER_DECISION_VERBS = re.compile(
    r"\b(narrative[_ ]?(decision|state)|decision_made_awaiting|state[_ ]?machine|pivot|cross.?paper.?synthesis)\b",
    re.I,
)
# Default for Paper N tasks → paper_review (small errata / footnote / clarif / table fix / quick win etc.)

# Non-paper patterns
PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^(K|k)\d+|\bk\d+_\b", re.I), "experiment", "K-experiment id"),
    (re.compile(r"\b(negative[_ ]?result|methodology[_ ]?paper)\b", re.I), "paper_body", "neg-result methodology paper"),
    (re.compile(r"\b(audit|cron|crontab|launchagent|dashboard|sync|pipeline|hook|cleanup|backfill|monitor|ops|admin)\b", re.I), "platform_ops", "ops keyword"),
    (re.compile(r"\balert\b", re.I), "platform_ops", "alert keyword"),
    (re.compile(r"\b(FB|facebook|trending)\b"), "trending_repost", "FB/trending"),
    (re.compile(r"daily.?article|補.*draft|draft.*pool|event[_ ]?article", re.I), "daily_article", "article work"),
    (re.compile(r"\b(skill|rule|governance|workflow|delegation|process[_ ]?fix)\b", re.I), "governance", "governance/skill"),
    (re.compile(r"\bmember[_ ]?q(a|uestion)|會員問題", re.I), "member_qa", "member question"),
    (re.compile(r"\bstrategy[_ ]?(lifecycle|registry|upgrade|listing|gate)\b", re.I), "strategy_lifecycle", "strategy lifecycle"),
    (re.compile(r"\b(data[_ ]?summary|script|fetch|download|extract)\b", re.I), "platform_ops", "data/script ops"),
]
DEFAULT_TYPE = "platform_ops"


def infer(task: dict) -> tuple[str, str]:
    """Return (inferred_type, rationale)."""
    if task.get("task_type") == "experiment_review":
        return "paper_review", "normalize experiment_review→paper_review"

    title = task.get("title") or ""
    desc = task.get("description") or ""
    tid = task.get("id") or ""
    text = f"{tid}\n{title}\n{desc}"

    # Stage 1: paper-related?
    if PAPER_INDICATOR.search(text):
        if PAPER_DECISION_VERBS.search(text):
            return "paper_decision", "paper + narrative/decision verbs"
        if PAPER_BODY_VERBS.search(text):
            return "paper_body", "paper + body-rewrite verbs"
        return "paper_review", "paper + default (errata/footnote/clarif)"

    # Stage 2: non-paper patterns
    for pat, ttype, why in PATTERNS:
        if pat.search(text):
            return ttype, f"matched: {why}"

    return DEFAULT_TYPE, "default fallback"


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise SystemExit("next_tasks.json not a list")

            changes: list[dict] = []
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                current = t.get("task_type")
                # Touch null OR experiment_review
                if current is not None and current != "experiment_review":
                    continue
                new_type, why = infer(t)
                if new_type != current:
                    changes.append({
                        "id": t.get("id"),
                        "old": current,
                        "new": new_type,
                        "rationale": why,
                        "title": (t.get("title") or "")[:80],
                    })
                    if args.apply:
                        t["task_type"] = new_type
                        # Audit trail
                        t.setdefault("backfill_log", []).append({
                            "old": current,
                            "new": new_type,
                            "rationale": why,
                            "at": "2026-05-25",
                        })

            if args.apply:
                fh.seek(0); fh.truncate()
                json.dump(tasks, fh, indent=2, ensure_ascii=False)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    by_target = Counter(c["new"] for c in changes)
    print(f"=== Backfill {'APPLY' if args.apply else 'DRY-RUN'} ===")
    print(f"Total changes: {len(changes)}")
    print(f"By target type: {dict(by_target)}")
    print()
    print("Sample (first 15):")
    for c in changes[:15]:
        print(f"  {c['id'][:50]:<50} {c['old'] or 'null':<20} → {c['new']:<15}  // {c['rationale']}")
    if len(changes) > 15:
        print(f"  ... +{len(changes) - 15} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
