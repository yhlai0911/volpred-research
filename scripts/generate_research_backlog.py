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
import fcntl
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PROGRAM = ROOT / "research_program.md"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
EXPERIMENTS_DIR = ROOT / "experiments"
JOURNAL_DISCOVERY_LIVE_STATUSES = {"pending", "claimed", "in_progress", "blocked", "pending_main_thread"}
JOURNAL_DISCOVERY_COOLDOWN_HOURS = 6

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
    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]\n", encoding="utf-8")
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            fh.truncate()
            json.dump(out, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _existing_ids(tasks: list) -> set[str]:
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in ("id", "k_id", "experiment_id"):
            value = task.get(key)
            if value:
                ids.add(str(value))
    return ids


def extract_unchecked_items(text: str, *, limit: int = 500) -> list[dict]:
    """Find `- [ ]` items in research_program.md. Returns up to limit.

    Default raised 20→500 (2026-06-14): the prior 20 cap silently truncated
    new journal-discovery batches (research_program.md has 100+ unchecked
    items); items appended at end of file never reached dedup → refill returned
    `all_already_covered_or_in_progress` even when 15 fresh directions existed.
    """
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
            "校稿", "/paper-update", "submit",
            # Paper-fix / review-correction items (not new research experiments)
            "修正 review", "review_v", "gemini 審查",
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


def already_in_next_tasks(item: dict, existing_tasks: list) -> bool:
    """Dedup: skip if this research_program.md item already has a task.

    Primary check is exact source-line match — research_program.md line
    number is a stable identity that survives CJK-heavy text where keyword
    overlap is unreliable (Chinese chars rarely yield \\w{4,} tokens, so the
    old keyword heuristic let the same line re-materialize every daily run).
    Keyword overlap is kept only as a secondary fallback for Latin briefs.
    """
    brief_text = item["text"]
    src_line = item.get("source_line")
    for t in existing_tasks:
        if t.get("source") != "research_backlog_auto":
            continue
        # Exact source-line match (preferred — stable across runs)
        if src_line is not None and t.get("source_line") == src_line:
            return True
        # Legacy tasks predate the source_line field — fall back to parsing
        # it out of the auto-generated description.
        if src_line is not None:
            m = re.search(r"unchecked item \(line (\d+)\)", t.get("description") or "")
            if m and int(m.group(1)) == src_line:
                return True
    # Secondary keyword fallback (Latin-heavy briefs only).
    # 2026-06-14 fix: limit scope to research-type tasks. Prior version looped
    # over ALL tasks including paper_review/article/rewrite, where generic words
    # like "skew", "regime", "factor", "drawdown" trivially hit ≥3 → false-positive
    # dedup of fresh journal-discovery directions. Restricting to experiments
    # (+ research_backlog_auto source) keeps real research dedup while
    # letting new directions through.
    brief_lower = brief_text.lower()
    keywords = [w for w in re.findall(r"[a-z]{4,}", brief_lower)][:5]
    if len(keywords) >= 3:
        for t in existing_tasks:
            if t.get("task_type") != "experiment" and t.get("source") != "research_backlog_auto":
                continue
            combined = ((t.get("title") or "") + " " + (t.get("description") or "")).lower()
            if sum(1 for k in keywords if k in combined) >= 3:
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
        "dispatch_lane": "agent",
        "source": "research_backlog_auto",
        "source_line": item["source_line"],
        "tags": ["experiment", "autonomous-research"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _journal_discovery_dispatch_task(
    tasks: list,
    existing_ids: set[str],
    *,
    now_utc: datetime | None = None,
) -> list[dict]:
    """Queue one journal-discovery task when research_program.md is saturated."""
    from datetime import timedelta

    now_utc = now_utc or datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=JOURNAL_DISCOVERY_COOLDOWN_HOURS)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "")
        if not task_id.startswith("journal_discovery_"):
            continue
        status = str(task.get("status") or "").lower()
        if status in JOURNAL_DISCOVERY_LIVE_STATUSES:
            return []
        completed_at = task.get("completed_at") or task.get("created_at")
        if isinstance(completed_at, str) and completed_at:
            try:
                ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    return []
            except ValueError:
                pass

    bucket = now_utc.hour // JOURNAL_DISCOVERY_COOLDOWN_HOURS
    task_id = f"journal_discovery_{now_utc.strftime('%Y%m%d')}_{bucket}"
    if task_id in existing_ids:
        return []

    return [
        {
            "id": task_id,
            "title": "Journal-discovery 派工: 補 research_program.md backlog (research_backlog all-covered fallback)",
            "description": (
                "generate_research_backlog.py found no unqueued research_program.md "
                "directions because all visible items are already covered or in progress. "
                "派 general-purpose agent 跑 scripts/agent_prompts/journal_topic_scan.md，"
                "從頂尖期刊（JBF/JFE/RFS/JoE/JPM/FAJ/CFA 等近 1-2 年）挖熱門主題，"
                "補 5-10 個新方向到 research_program.md 對應 section，完成後下一輪 "
                "research_backlog/refill 自動取用。6h idempotent；勿手動重派。"
            ),
            "priority": 2,
            "status": "pending",
            "task_type": "platform_ops",
            "dispatch_lane": "agent",
            "source": "auto_journal_discovery_fallback",
            "tags": ["auto-journal-discovery", "research-backlog-refresh", "all-covered-fallback"],
            "created_at": now_utc.isoformat(timespec="seconds"),
        }
    ]


def _journal_fallback_result(
    *,
    payload: dict | list,
    tasks: list,
    dry_run: bool,
    reason: str,
) -> dict:
    journal_tasks = _journal_discovery_dispatch_task(tasks, _existing_ids(tasks))
    if not journal_tasks:
        return {
            "ok": True,
            "added": 0,
            "reason": reason,
            "journal_discovery": "skipped_recent_or_live",
        }
    preview = [{"id": task["id"], "title": task["title"][:80]} for task in journal_tasks]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_add": len(journal_tasks),
            "fallback_reason": "journal_discovery_dispatch",
            "reason": reason,
            "preview": preview,
        }
    tasks.extend(journal_tasks)
    _save_tasks(payload, tasks)
    return {
        "ok": True,
        "added": len(journal_tasks),
        "added_ids": [task["id"] for task in journal_tasks],
        "fallback_reason": "journal_discovery_dispatch",
        "reason": reason,
    }


def generate(*, dry_run: bool = False, max_new: int = 5) -> dict:
    if not RESEARCH_PROGRAM.exists():
        return {"ok": False, "reason": "research_program_missing", "added": 0}
    text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    payload, tasks = _load_tasks()
    items = extract_unchecked_items(text, limit=500)
    if not items:
        return _journal_fallback_result(
            payload=payload,
            tasks=tasks,
            dry_run=dry_run,
            reason="no_unchecked_items",
        )

    # K-id assignment must avoid collisions with in-flight next_tasks.json
    # entries, not just experiments/ dirs — otherwise every run re-assigns the
    # same id to the same recurring item (K1308 collided 5x before this fix).
    in_flight_ids = _existing_ids(tasks)
    new_briefs = []
    next_k = find_next_k_id(start=1302, existing_task_ids=in_flight_ids)
    for item in items:
        if len(new_briefs) >= max_new:
            break
        if already_in_next_tasks(item, tasks):
            continue
        brief = build_experiment_brief(item, next_k)
        new_briefs.append(brief)
        in_flight_ids.add(brief["id"])
        next_k = find_next_k_id(start=next_k + 1, existing_task_ids=in_flight_ids)

    if not new_briefs:
        return _journal_fallback_result(
            payload=payload,
            tasks=tasks,
            dry_run=dry_run,
            reason="all_already_covered_or_in_progress",
        )

    if dry_run:
        return {
            "ok": True, "dry_run": True, "would_add": len(new_briefs),
            "preview": [{"id": b["id"], "title": b["title"][:80]} for b in new_briefs],
        }

    tasks.extend(new_briefs)
    _save_tasks(payload, tasks)
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
