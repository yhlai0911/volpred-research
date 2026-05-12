#!/usr/bin/env python3
"""Auto-generate K-experiment briefs from research_program.md gaps.

Closes the recurring drift where the dispatcher hits agentable=0 because
publication_candidates pool is fully covered but research_program.md still
has open research questions. Pool should NEVER be empty when the project
still has unfinished research — autonomous generation fills that gap.

Run weekly from cron OR triggered when continue_task_dispatch._maybe_refill
hits agentable=0 after both diverse_gen + article_refill exhaust.

Approach:
1. Scan research_program.md for unchecked `- [ ]` items
2. Scan for "Open Question / 待深入 / TODO" headings + immediate context
3. Generate K-experiment brief per unique research thread
4. Auto-assign next free K-id from experiments/ directory
5. Append as `task_type="experiment"`, priority 3 (sub-priority by ROI)

Usage:
    uv run python scripts/generate_research_backlog.py --dry-run
    uv run python scripts/generate_research_backlog.py --apply --max 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PROGRAM = ROOT / "research_program.md"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
EXPERIMENTS_DIR = ROOT / "experiments"

# Look for unchecked items + open question patterns
UNCHECKED_RE = re.compile(r"^[\s-]*\[ \]\s*\*?\*?(.+?)\*?\*?$", re.MULTILINE)
OPEN_QUESTION_RE = re.compile(
    r"^#{2,4}\s*(?:Open Question|待深入|TODO|Backlog|遺留).*$", re.MULTILINE | re.IGNORECASE
)


def find_next_k_id(start: int = 1300, *, existing_task_ids: set | None = None) -> int:
    """Find lowest free K-id ≥ start. Considers both experiments/ dir AND
    in-flight next_tasks.json entries to avoid collisions."""
    existing = {p.name.lower() for p in EXPERIMENTS_DIR.iterdir() if p.is_dir() and p.name.startswith(("k", "K"))}
    if existing_task_ids:
        for tid in existing_task_ids:
            tid_l = str(tid).lower()
            if tid_l.startswith("k") and tid_l[1:].split("_")[0].isdigit():
                existing.add(tid_l.split("_")[0])  # K1307_article → k1307
    n = start
    while f"k{n}" in existing:
        n += 1
    return n


def extract_unchecked_items(text: str, *, limit: int = 20) -> list[dict]:
    """Find `- [ ]` items in research_program.md. Returns up to limit."""
    items = []
    for m in UNCHECKED_RE.finditer(text):
        body = m.group(1).strip()
        if len(body) < 20 or len(body) > 500:
            continue  # filter out trivial / overly-long matches
        # Skip if already mentions a specific K-id (likely tracking an existing exp)
        if re.search(r"\bK\d{3,5}\b", body):
            continue
        # Filter out lines that are just headers / commit messages
        if any(p in body.lower() for p in ["commit", "fix", "merge", "review-cycle", "scripts/"]):
            continue
        # Filter out paper-submission checklist items (not research experiments)
        body_lower = body.lower()
        if any(p in body_lower for p in [
            "latex-academic-reviewer", "citation-verifier", "cover letter",
            "highlights", "graphical abstract", "投稿準備", "全面審查",
            "校稿", "highlights", "/paper-update", "submit",
        ]):
            continue
        # Require some signal of a real research question (model/test/data/hypothesis)
        research_signal = any(p in body_lower for p in [
            "model", "test", "garch", "bma", "har", "ev", "qr", "ols",
            "semi", "variance", "regression", "factor", "spillover", "vix",
            "regime", "decomp", "比較", "預測", "回歸", "檢定", "估計",
            "shap", "boot", "monte", "rolling", "panel",
        ])
        if not research_signal:
            continue
        items.append({"text": body, "source_line": text[:m.start()].count("\n") + 1})
        if len(items) >= limit:
            break
    return items


def already_in_next_tasks(brief_text: str, existing_tasks: list) -> bool:
    """Dedup: skip if a similar brief already exists in next_tasks.json."""
    brief_lower = brief_text.lower()
    keywords = [w for w in re.findall(r"\w{4,}", brief_lower) if len(w) > 3][:5]
    for t in existing_tasks:
        title = (t.get("title") or "").lower()
        desc = (t.get("description") or "").lower()
        combined = title + " " + desc
        # If 3+ of top 5 keywords appear, treat as duplicate
        hits = sum(1 for k in keywords if k in combined)
        if hits >= 3:
            return True
    return False


def build_experiment_brief(item: dict, k_id: int) -> dict:
    """Convert an open research item into a K-experiment brief."""
    return {
        "id": f"K{k_id}",
        "title": f"K{k_id}: {item['text'][:120]}",
        "priority": 3,
        "description": (
            f"Auto-generated from research_program.md unchecked item (line {item['source_line']}). "
            f"Original: {item['text']}\n\n"
            f"Required experiment workflow per .claude/rules/experiments.md: "
            f"(a) README.md with motivation + method + lookahead policy + success criteria, "
            f"(b) K{k_id}.py with signal.shift(1) + seed=42, "
            f"(c) K{k_id}_results.json with byte-traceable outputs. "
            f"Codex review primary path (fallback to subagent or audit if quota blocked). "
            f"Knowledge entry only after CONDITIONAL_PASS minimum."
        ),
        "status": "pending",
        "task_type": "experiment",
        "source": "research_backlog_auto",
        "tags": ["experiment", "autonomous-research"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def generate(*, dry_run: bool = False, max_new: int = 5) -> dict:
    if not RESEARCH_PROGRAM.exists():
        return {"ok": False, "reason": "research_program_missing", "added": 0}
    text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    items = extract_unchecked_items(text, limit=20)
    if not items:
        return {"ok": True, "added": 0, "reason": "no_unchecked_items"}

    with NEXT_TASKS.open("r", encoding="utf-8") as f:
        tasks = json.load(f)

    new_briefs = []
    next_k = find_next_k_id(start=1302)
    for item in items:
        if len(new_briefs) >= max_new:
            break
        if already_in_next_tasks(item["text"], tasks):
            continue
        brief = build_experiment_brief(item, next_k)
        new_briefs.append(brief)
        next_k += 1
        while f"k{next_k}" in {p.name.lower() for p in EXPERIMENTS_DIR.iterdir() if p.is_dir()}:
            next_k += 1

    if not new_briefs:
        return {"ok": True, "added": 0, "reason": "all_already_covered_or_in_progress"}

    if dry_run:
        return {
            "ok": True, "dry_run": True, "would_add": len(new_briefs),
            "preview": [{"id": b["id"], "title": b["title"][:80]} for b in new_briefs],
        }

    tasks.extend(new_briefs)
    with NEXT_TASKS.open("w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    return {"ok": True, "added": len(new_briefs), "added_ids": [b["id"] for b in new_briefs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max", type=int, default=5, help="max new briefs per run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2
    result = generate(dry_run=args.dry_run, max_new=args.max)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("dry_run"):
            print(f"[research_backlog] would add {result.get('would_add', 0)}: {result.get('preview')}")
        elif result.get("added"):
            print(f"[research_backlog] added {result['added']}: {result.get('added_ids')}")
        else:
            print(f"[research_backlog] no add — {result.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
