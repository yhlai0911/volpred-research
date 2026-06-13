#!/usr/bin/env python3
"""Multi-source task generator v2.

從 5 種來源自動生成任務並 append 到 storage/next_tasks.json。

來源：
  1. experiment      — 從 research_program.md 未完成 [ ] 項目
  2. paper_decision  — 從 paper portfolio 表中 pending 狀態論文
  3. paper_body      — 從 paper/*.tex 中 TODO/\\todo{}/PLACEHOLDER 標記
  4. event_article   — 從硬編碼 FOMC/BLS 日曆（距今 <7 天）
  5. daily_article   — 從已有 results.json（verdict 非 null）但無文章的 K

CLI::
    python3 scripts/task_generator_v2.py --source all --dry-run
    python3 scripts/task_generator_v2.py --source experiment --limit 5
    python3 scripts/task_generator_v2.py --source daily_article --limit 3 --commit
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
RESEARCH_PROGRAM = ROOT / "research_program.md"
FEED_JSON = ROOT / "storage" / "reports" / "feed.json"
EXPERIMENTS_DIR = ROOT / "experiments"
PAPER_DIR = ROOT / "paper"
RUNTIME_SCHEDULES = ROOT / "config" / "runtime_schedules.json"
GENERATOR_SOURCE_TAG = "task_generator_v2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_next_tasks() -> list[dict]:
    """Load existing tasks from storage/next_tasks.json."""
    if not NEXT_TASKS.exists():
        return []
    try:
        with open(NEXT_TASKS) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def existing_ids(tasks: list[dict]) -> set[str]:
    return {t.get("id", "") for t in tasks}


def existing_k_ids_in_tasks(tasks: list[dict]) -> set[str]:
    """Get all K-ids referenced in existing tasks (k_id field or id pattern)."""
    ks: set[str] = set()
    k_pat = re.compile(r"^K(\d+[a-z]*)$", re.IGNORECASE)
    id_pat = re.compile(r"K(\d+[a-z]*)_article", re.IGNORECASE)
    for t in tasks:
        kid = t.get("k_id")
        if kid:
            ks.add(kid.upper())
        # Also extract from task id pattern like K1015_article_general
        m = id_pat.match(t.get("id", ""))
        if m:
            ks.add(f"K{m.group(1).upper()}")
    return ks


def completed_experiment_ids() -> set[str]:
    """Return K-ids that already have an experiment receipt on disk."""
    if not EXPERIMENTS_DIR.exists():
        return set()

    done: set[str] = set()
    for path in EXPERIMENTS_DIR.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(r"k(\d+[a-z]*)", path.name, re.IGNORECASE)
        if not match:
            continue
        has_receipt = (path / "README.md").exists() or any(path.glob("*_results.json"))
        if has_receipt:
            done.add(f"K{match.group(1).upper()}")
    return done


def experiment_readme_corpus() -> str:
    """Concatenate experiment READMEs for conservative stale-backlog checks."""
    if not EXPERIMENTS_DIR.exists():
        return ""

    chunks: list[str] = []
    for readme in EXPERIMENTS_DIR.glob("k*/README.md"):
        try:
            chunks.append(readme.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)


def k_ids_with_feed_articles() -> set[str]:
    """Extract K-ids that already appear in feed.json content."""
    if not FEED_JSON.exists():
        return set()
    # Use grep (shell) rather than loading entire JSON
    try:
        result = subprocess.run(
            ["grep", "-o", r"K[0-9][0-9][0-9][0-9][a-z]*", str(FEED_JSON)],
            capture_output=True, text=True, timeout=30
        )
        ks = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                ks.add(line.upper())
        return ks
    except Exception:
        return set()


def make_task(
    task_id: str,
    title: str,
    description: str,
    task_type: str,
    priority: int = 4,
    tags: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    t: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "description": description,
        "task_type": task_type,
        "priority": priority,
        "status": "pending",
        "tags": tags or [],
        "source": f"{GENERATOR_SOURCE_TAG}_{task_type}",
        "created_at": now_iso(),
        "generated_at": now_iso(),
    }
    if extra:
        t.update(extra)
    return t


# ---------------------------------------------------------------------------
# Source 1: experiment — from research_program.md unchecked [ ] items
# ---------------------------------------------------------------------------

def _clean_checkbox_line(line: str) -> str:
    """Strip checkbox prefix and leading whitespace."""
    return re.sub(r"^[\s*-]*\[[ ]\]\s*", "", line).strip()


def generate_experiment_tasks(
    existing: list[dict],
    limit: int | None = None,
) -> list[dict]:
    """Parse research_program.md for - [ ] unchecked items."""
    if not RESEARCH_PROGRAM.exists():
        print("[experiment] research_program.md not found", file=sys.stderr)
        return []

    text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    lines = text.splitlines()

    ex_ids = existing_ids(existing)
    done_experiment_ids = completed_experiment_ids()
    readme_corpus = experiment_readme_corpus()
    results: list[dict] = []

    # Patterns to SKIP (blocked / conditional / already known)
    skip_patterns = [
        re.compile(r"BLOCKED", re.IGNORECASE),
        re.compile(r"latex-academic-reviewer"),
        re.compile(r"citation-verifier"),
        re.compile(r"\\\\"),  # LaTeX markup lines
    ]

    # Pattern to extract K-numbers from lines
    k_extract = re.compile(r"\bK(\d{4,}[a-z]*)\b", re.IGNORECASE)

    for line in lines:
        # Must be an unchecked checkbox
        if not re.match(r"^\s*[-*]?\s*\[\s\]", line):
            continue

        content = _clean_checkbox_line(line)
        if not content:
            continue

        # Skip blocked / structural items
        if any(pat.search(content) for pat in skip_patterns):
            continue

        # Build a stable ID from content
        k_matches = k_extract.findall(content)
        if k_matches:
            kid = k_matches[0].upper()
            if f"K{kid}" in done_experiment_ids:
                continue
            task_id = f"gen_exp_{kid}"
            title = f"Experiment {kid}: {content[:80]}"
        else:
            # Some old backlog items have no K-id but were later materialized as
            # continuation experiments. If a README quotes the same line, do not
            # re-seed it as a fresh task.
            if len(content) >= 20 and content in readme_corpus:
                continue
            # Create slug from content
            slug = re.sub(r"[^\w一-鿿]", "_", content[:40]).strip("_")
            slug = re.sub(r"_+", "_", slug)[:40]
            task_id = f"gen_exp_{slug}"
            title = content[:100]

        if task_id in ex_ids:
            continue
        ex_ids.add(task_id)

        task = make_task(
            task_id=task_id,
            title=title,
            description=f"Auto-generated from research_program.md unchecked item: {content[:300]}",
            task_type="experiment",
            priority=3,
            tags=["auto-generated", "research-backlog"],
        )
        results.append(task)
        if limit is not None and len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Source 2: paper_decision — papers with pending decisions
# ---------------------------------------------------------------------------

# Known paper IDs and their directory names
KNOWN_PAPERS = {
    "P1": ("leverage-direction", "leverage-direction"),
    "P2": ("taiwan-vt", "taiwan-vt"),
    "P3": ("vt-trend-following", "vt-trend-following"),
    "P4ins": ("vt-insurance-cost", "vt-insurance-cost"),
    "P5": ("vt-crowding-abm", "vt-crowding-abm"),
    "P6": ("prg-periodic-garch", "prg-periodic-garch"),
    "P7": ("vix-sufficiency", "vix-sufficiency"),
    "P8": ("volatility-absorption", "volatility-absorption"),
    "P9": ("garch-x-vix", "garch-x-vix"),
    "P10": ("crypto-fear-channel", "crypto-fear-channel"),
}

# Papers that are clearly NOT needing a new decision task
COMPLETE_PAPER_IDS = {"P4ins", "P5", "P6", "P7", "P10"}  # READY/SUBMISSION stage

# Amber status indicators: 🟡 or partial completion
AMBER_PATTERN = re.compile(r"🟡|MISMATCH|UNTRACE|amber|CRITICAL errata|awaiting.*decision", re.IGNORECASE)
# Red status: 🔴
RED_PATTERN = re.compile(r"🔴|errata_pending|CRITICAL", re.IGNORECASE)


def generate_paper_decision_tasks(
    existing: list[dict],
    limit: int | None = None,
) -> list[dict]:
    """Scan research_program.md Paper Portfolio table for papers needing decisions."""
    if not RESEARCH_PROGRAM.exists():
        return []

    text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    ex_ids = existing_ids(existing)
    results: list[dict] = []

    # Extract the portfolio status table section
    table_match = re.search(
        r"## Paper Portfolio Status.*?(?=\n## |\Z)", text, re.DOTALL
    )
    if not table_match:
        print("[paper_decision] Portfolio Status table not found", file=sys.stderr)
        return []

    table_text = table_match.group(0)
    lines = table_text.splitlines()

    for line in lines:
        if not line.startswith("|"):
            continue
        # Parse table row: | P# | paper-name | Status | Blocker |
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 5:
            continue

        paper_id_raw = cols[1].strip("* ").strip()
        paper_name = cols[2].strip()
        status_col = cols[3].strip()

        # Extract paper ID like P1, P2, P3, P8 etc.
        pid_match = re.search(r"\bP(\d+[a-z]*)\b", paper_id_raw, re.IGNORECASE)
        if not pid_match:
            continue
        pid = f"P{pid_match.group(1)}"

        # Skip completed/submitted papers
        if pid in COMPLETE_PAPER_IDS:
            continue

        # Check if this paper has a pending situation (amber/red/awaiting)
        needs_decision = (
            AMBER_PATTERN.search(status_col)
            or RED_PATTERN.search(status_col)
            or "awaiting" in status_col.lower()
            or "decision" in status_col.lower()
        )
        if not needs_decision:
            continue

        task_id = f"gen_paper_decision_{pid}"
        if task_id in ex_ids:
            continue
        ex_ids.add(task_id)

        # Determine priority based on severity
        if RED_PATTERN.search(status_col):
            priority = 1
        elif "CRITICAL" in status_col:
            priority = 2
        else:
            priority = 3

        title = f"{pid} ({paper_name}): paper decision needed — review status and determine next action"
        desc = f"Paper {pid} ({paper_name}) is in a pending/amber state. Status excerpt: {status_col[:300]}"

        task = make_task(
            task_id=task_id,
            title=title,
            description=desc,
            task_type="paper_decision",
            priority=priority,
            tags=["auto-generated", "paper-decision", pid.lower()],
            extra={"paper_id": pid, "paper_name": paper_name},
        )
        results.append(task)
        if limit is not None and len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Source 3: paper_body — from .tex TODO/\todo{}/PLACEHOLDER markers
# ---------------------------------------------------------------------------

TODO_PATTERN = re.compile(
    r"(\bTODO\b|\\todo\{[^}]*\}|\[PLACEHOLDER\]|\[FIXME\]|\[TBD\])"
)


def generate_paper_body_tasks(
    existing: list[dict],
    limit: int | None = None,
) -> list[dict]:
    """Find TODO/\\todo{}/PLACEHOLDER in paper .tex files."""
    ex_ids = existing_ids(existing)
    results: list[dict] = []

    # Glob all main*.tex files
    tex_files = sorted(PAPER_DIR.glob("*/main*.tex"))
    if not tex_files:
        print("[paper_body] No paper tex files found", file=sys.stderr)
        return []

    for tex_path in tex_files:
        paper_slug = tex_path.parent.name
        tex_name = tex_path.stem

        try:
            lines = tex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        todos: list[tuple[int, str]] = []
        for lineno, line in enumerate(lines, start=1):
            if TODO_PATTERN.search(line):
                snippet = line.strip()[:120]
                todos.append((lineno, snippet))

        if not todos:
            continue

        # Create one task per paper-tex file that has TODOs
        task_id = f"gen_paper_body_{paper_slug}_{tex_name}"
        if task_id in ex_ids:
            continue
        ex_ids.add(task_id)

        # Build description with first few TODOs
        todo_preview = "\n".join(
            f"  L{ln}: {snip}" for ln, snip in todos[:5]
        )
        if len(todos) > 5:
            todo_preview += f"\n  ... and {len(todos) - 5} more"

        title = f"paper_body [{paper_slug}/{tex_name}]: resolve {len(todos)} TODO/PLACEHOLDER markers"
        desc = (
            f"Found {len(todos)} TODO/\\todo{{}}/PLACEHOLDER markers in "
            f"paper/{paper_slug}/{tex_name}.tex that need resolution.\n"
            f"Sample:\n{todo_preview}"
        )

        task = make_task(
            task_id=task_id,
            title=title,
            description=desc,
            task_type="paper_body",
            priority=3,
            tags=["auto-generated", "paper-body", paper_slug],
            extra={
                "paper_slug": paper_slug,
                "tex_file": f"paper/{paper_slug}/{tex_name}.tex",
                "todo_count": len(todos),
            },
        )
        results.append(task)
        if limit is not None and len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Source 4: event_article — FOMC/BLS calendar events within 7 days
# ---------------------------------------------------------------------------

# Hard-coded calendar: (event_type, date_str, description)
EVENT_CALENDAR: list[tuple[str, str, str]] = [
    # FOMC meetings 2026
    ("fomc", "2026-06-18", "FOMC meeting June 2026 — Fed rate decision"),
    ("fomc", "2026-07-30", "FOMC meeting July 2026 — Fed rate decision"),
    ("fomc", "2026-09-17", "FOMC meeting September 2026 — Fed rate decision"),
    ("fomc", "2026-11-05", "FOMC meeting November 2026 — Fed rate decision"),
    ("fomc", "2026-12-17", "FOMC meeting December 2026 — Fed rate decision"),
    # BLS CPI release dates (approximate — every ~2nd Wednesday of each month)
    ("cpi", "2026-05-13", "BLS CPI release May 2026 — US inflation data"),
    ("cpi", "2026-06-11", "BLS CPI release June 2026 — US inflation data"),
    ("cpi", "2026-07-15", "BLS CPI release July 2026 — US inflation data"),
    ("cpi", "2026-08-12", "BLS CPI release August 2026 — US inflation data"),
    ("cpi", "2026-09-11", "BLS CPI release September 2026 — US inflation data"),
    ("cpi", "2026-10-14", "BLS CPI release October 2026 — US inflation data"),
    ("cpi", "2026-11-13", "BLS CPI release November 2026 — US inflation data"),
    ("cpi", "2026-12-11", "BLS CPI release December 2026 — US inflation data"),
    # BLS Jobs report (first Friday each month)
    ("jobs", "2026-06-05", "BLS Jobs report June 2026 — US employment data"),
    ("jobs", "2026-07-02", "BLS Jobs report July 2026 — US employment data"),
    ("jobs", "2026-08-07", "BLS Jobs report August 2026 — US employment data"),
]

EVENT_WINDOW_DAYS = 7  # Generate task if event is within this many days


def _normalize_event_type(raw: str | None) -> str:
    text = str(raw or "").lower()
    if "fomc" in text:
        return "fomc"
    if "cpi" in text:
        return "cpi"
    if "nfp" in text or "jobs" in text or "employment" in text:
        return "jobs"
    return text.strip()


def _iter_managed_event_dates(existing: list[dict]) -> set[tuple[str, date]]:
    """Return event dates already managed by canonical schedules or tasks.

    The legacy hard-coded event calendar can use Taiwan announcement dates
    while runtime_schedules stores US event dates. Treat +/- 1 day as the same
    event to avoid duplicate FOMC/CPI/NFP briefs.
    """
    managed: set[tuple[str, date]] = set()

    if RUNTIME_SCHEDULES.exists():
        try:
            payload = json.loads(RUNTIME_SCHEDULES.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        items = ((payload.get("event_jobs") or {}).get("items") or [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                patch = ((item.get("task_template") or {}).get("payload_patch") or {})
                event_type = _normalize_event_type(patch.get("event_type") or item.get("event_key"))
                event_date_raw = patch.get("event_date")
                if not event_type or not event_date_raw:
                    continue
                try:
                    managed.add((event_type, date.fromisoformat(str(event_date_raw))))
                except ValueError:
                    continue

    for task in existing:
        if not isinstance(task, dict) or task.get("task_type") != "event_article":
            continue
        event_type = _normalize_event_type(task.get("event_type") or task.get("event_key") or task.get("id"))
        event_date_raw = task.get("event_date")
        if not event_type or not event_date_raw:
            continue
        try:
            managed.add((event_type, date.fromisoformat(str(event_date_raw))))
        except ValueError:
            continue

    return managed


def _is_managed_event(event_type: str, event_date: date, managed: set[tuple[str, date]]) -> bool:
    event_type = _normalize_event_type(event_type)
    return any(
        managed_type == event_type and abs((managed_date - event_date).days) <= 1
        for managed_type, managed_date in managed
    )


def generate_event_article_tasks(
    existing: list[dict],
    limit: int | None = None,
    reference_date: date | None = None,
) -> list[dict]:
    """Generate event_article tasks for upcoming macro events."""
    today = reference_date or date.today()
    ex_ids = existing_ids(existing)
    managed_events = _iter_managed_event_dates(existing)
    results: list[dict] = []

    for event_type, date_str, description in EVENT_CALENDAR:
        try:
            event_date = date.fromisoformat(date_str)
        except ValueError:
            continue

        days_until = (event_date - today).days
        # Only generate for events within window (0 = today, up to 7 days ahead)
        # Also allow past events that were very recent (up to 2 days ago)
        if not (-2 <= days_until <= EVENT_WINDOW_DAYS):
            continue

        if _is_managed_event(event_type, event_date, managed_events):
            continue

        date_compact = date_str.replace("-", "")
        task_id = f"event_{event_type}_{date_compact}"
        if task_id in ex_ids:
            continue
        ex_ids.add(task_id)

        if days_until < 0:
            urgency = "已發生（補文）"
            priority = 4
        elif days_until == 0:
            urgency = "今日發生"
            priority = 1
        elif days_until <= 2:
            urgency = f"距今 {days_until} 天（緊急）"
            priority = 1
        else:
            urgency = f"距今 {days_until} 天"
            priority = 2

        event_label = {"fomc": "FOMC 聯準會利率決議", "cpi": "BLS CPI 通膨數據", "jobs": "BLS 非農就業報告"}.get(event_type, event_type.upper())
        title = f"[{urgency}] {date_str} {event_label} — 市場波動率前瞻文章"
        desc = (
            f"{description}。"
            f"距離事件：{urgency}。"
            f"撰寫市場波動率前瞻：VIX 水平、期貨隱含波動率、FOMC/BLS 相關波動規律分析。"
            f"需引用最新 VIX 數據與本平台相關研究（PRG / VIX-sufficiency 等）。"
        )

        task = make_task(
            task_id=task_id,
            title=title,
            description=desc,
            task_type="event_article",
            priority=priority,
            tags=["auto-generated", "event-driven", event_type, date_str[:7]],
            extra={
                "event_type": event_type,
                "event_date": date_str,
                "days_until": days_until,
            },
        )
        results.append(task)
        if limit is not None and len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Source 5: daily_article — K with results.json verdict but no feed article
# ---------------------------------------------------------------------------

def _extract_verdict_and_id(results_path: Path) -> tuple[str | None, str | None]:
    """Safely extract experiment_id and verdict from a results.json."""
    try:
        with open(results_path) as f:
            data = json.load(f)
        verdict = data.get("verdict")
        exp_id = data.get("experiment_id")
        if not exp_id:
            # Fallback: derive from parent dir name
            parent = results_path.parent.name.upper()
            if re.match(r"^K\d+", parent):
                exp_id = parent
        return exp_id, verdict
    except Exception:
        return None, None


def generate_daily_article_tasks(
    existing: list[dict],
    limit: int | None = None,
) -> list[dict]:
    """Find K experiments with non-null verdict but no feed article and no pending task."""
    feed_ks = k_ids_with_feed_articles()
    task_ks = existing_k_ids_in_tasks(existing)
    ex_ids = existing_ids(existing)
    results: list[dict] = []

    # Glob all k*_results.json
    results_paths = sorted(EXPERIMENTS_DIR.glob("k*/k*_results.json"))

    for rpath in results_paths:
        exp_id, verdict = _extract_verdict_and_id(rpath)
        if not exp_id:
            continue
        # Normalize to uppercase K format
        kid = exp_id.upper()
        if not re.match(r"^K\d+", kid):
            continue
        # Only generate if verdict is non-null
        if verdict is None:
            continue

        # Check: already in feed?
        if kid in feed_ks:
            continue
        # Check: already in tasks as daily_article?
        if kid in task_ks:
            continue

        task_id = f"gen_article_{kid.lower()}"
        if task_id in ex_ids:
            continue
        ex_ids.add(task_id)
        task_ks.add(kid)  # prevent duplicate within this run

        verdict_str = str(verdict)[:80] if verdict else "unknown"
        title = f"{kid}: write general-audience article (auto-discovered, verdict={verdict_str[:40]})"
        desc = (
            f"{kid} has a non-null verdict in experiments/{rpath.parent.name}/ "
            f"but no published feed article and no existing task. "
            f"Verdict: {verdict_str}. "
            f"Write a general-audience article summarising key findings."
        )

        task = make_task(
            task_id=task_id,
            title=title,
            description=desc,
            task_type="daily_article",
            priority=4,
            tags=["auto-generated", "audience-general", "uncovered-k"],
            extra={"k_id": kid},
        )
        results.append(task)
        if limit is not None and len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

SOURCES = ["experiment", "paper_decision", "paper_body", "event_article", "daily_article"]

SOURCE_GENERATORS = {
    "experiment": generate_experiment_tasks,
    "paper_decision": generate_paper_decision_tasks,
    "paper_body": generate_paper_body_tasks,
    "event_article": generate_event_article_tasks,
    "daily_article": generate_daily_article_tasks,
}


def run_source(
    source: str,
    existing: list[dict],
    limit: int | None,
) -> list[dict]:
    fn = SOURCE_GENERATORS[source]
    return fn(existing, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-source task generator v2 — appends tasks to storage/next_tasks.json"
    )
    parser.add_argument(
        "--source",
        choices=SOURCES + ["all"],
        default="all",
        help="Which source to run (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max tasks to generate per source",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print generated tasks without writing to disk",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Write generated tasks to storage/next_tasks.json (incompatible with --dry-run)",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=None,
        help="Write generated tasks as JSON to this path (for logging)",
    )

    args = parser.parse_args()

    if args.dry_run and args.commit:
        parser.error("--dry-run and --commit are mutually exclusive")

    existing = load_next_tasks()
    print(f"[task_generator_v2] Loaded {len(existing)} existing tasks from next_tasks.json")

    sources_to_run = SOURCES if args.source == "all" else [args.source]
    all_generated: dict[str, list[dict]] = {}

    for source in sources_to_run:
        print(f"\n[{source}] Generating tasks...")
        tasks = run_source(source, existing, args.limit)
        all_generated[source] = tasks
        print(f"[{source}] → {len(tasks)} new tasks")

        if args.dry_run:
            for i, t in enumerate(tasks):
                print(f"  [{i+1}] {t['id']} — {t['title'][:80]}")
        else:
            # Update existing list so later sources see already-added tasks
            existing = existing + tasks

    total = sum(len(v) for v in all_generated.values())
    print(f"\n[task_generator_v2] Total new tasks: {total}")

    # Summarise counts
    counts = {src: len(tasks) for src, tasks in all_generated.items()}
    print("[task_generator_v2] Counts by source:", json.dumps(counts, ensure_ascii=False))

    # Write to file if --commit
    if args.commit and total > 0:
        new_tasks = [t for tasks in all_generated.values() for t in tasks]
        original = load_next_tasks()
        combined = original + new_tasks
        with open(NEXT_TASKS, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        print(f"[task_generator_v2] Wrote {total} new tasks to {NEXT_TASKS}")
    elif args.commit and total == 0:
        print("[task_generator_v2] No new tasks to write.")

    # Write JSON output log if requested
    if args.json_output:
        out = {
            "generated_at": now_iso(),
            "dry_run": args.dry_run,
            "commit": args.commit,
            "source": args.source,
            "counts": counts,
            "total": total,
            "tasks": [t for tasks in all_generated.values() for t in tasks],
        }
        Path(args.json_output).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[task_generator_v2] JSON log written to {args.json_output}")


if __name__ == "__main__":
    main()
