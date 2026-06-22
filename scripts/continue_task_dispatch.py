#!/usr/bin/env python3
"""Slot-aware continuation dispatcher (replaces stub-only continue_task host cron).

讀 storage/next_tasks.json 的 pending queue，按 priority asc 排序，
count 當前 slot 占用（.claude/worktrees/ + storage/ops/agents/ active），
若 slot < cap (4) 且有可派 agent 的 task → 列出 / 派出（依 mode）。

執行模式：
  --dry-run    僅列 candidates 不派任何工作（default 安全）
  --report     寫 report 到 storage/ops/dispatch_report_latest.json
  --execute    真的 spawn agent（需 cron-runtime；目前主線程 fallback = print 指令給人類）

main-thread-only 任務優先看 schema-level `dispatch_lane="main_thread"`；
legacy title/description「main thread」/「NOT agent」標記仍作 fallback。

Usage::
    uv run python scripts/continue_task_dispatch.py --dry-run
    uv run python scripts/continue_task_dispatch.py --report
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import signal
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
WORKTREES_DIR = ROOT / ".claude" / "worktrees"
AGENTS_DIR = ROOT / "storage" / "ops" / "agents"
REPORT_PATH = ROOT / "storage" / "ops" / "dispatch_report_latest.json"
SLOT_CAP = 4
# Refill threshold: when agentable count drops below this, dispatcher
# auto-runs refill_task_pool.py to top up. Keeps the rule "任務池永遠要有
# 待辦任務" enforceable by mechanism, not by main-thread discipline.
REFILL_FLOOR = 4
POOL_DRY_DIAGNOSTIC_PREFIX = "platform_ops_dispatch_pool_dry_diagnostic"
ARTICLE_REFILL_TIMEOUT_SECONDS = 45

MAIN_THREAD_MARKERS = re.compile(
    r"main\s*thread|NOT\s*agent|main-thread|主線程",
    re.IGNORECASE,
)
AGENT_DISPATCH_LANES = {"agent", "agentable", "auto", "auto_dispatch", "headless", "worker"}
MAIN_THREAD_DISPATCH_LANES = {"main", "main_thread", "manual", "interactive"}
BLOCKED_DISPATCH_LANES = {"blocked", "blocked_on_user", "hold"}

# 2026-05-04 finding: dispatcher previously had no concept of "blocked".
# Tasks that can never be dispatched (awaiting external auth, prior compute
# failures, self-tagged optional, K-id collision, etc.) sat in `pending`
# and got recommended every cycle, forcing main thread into a skip-loop.
#
# Hard blocks are persisted on the task itself via `blocked_reason` (set
# by scripts/mark_task_blocked.py or schema-level edits). Soft blocks are
# auto-detected from title/description patterns below; they can be
# upgraded to hard blocks on first encounter so the dispatcher is
# self-correcting.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
from volpred.ops.blocked_reasons import BLOCKED_REASONS  # noqa: E402

SELF_OPTIONAL_PATTERN = re.compile(
    r"\(\s*optional\s*\)|（\s*optional\s*）|"
    r"only\s+if\s+truly\s+new|"
    r"否則跳過|skip\s+if\s+already",
    re.IGNORECASE,
)


def _warn_dispatch(message: str) -> None:
    print(f"[dispatch] WARN {message}", file=sys.stderr)


def count_active_slots() -> dict:
    """Count occupied slots across worktrees + agent records."""
    worktrees = []
    if WORKTREES_DIR.exists():
        for p in WORKTREES_DIR.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                worktrees.append(p.name)

    active_agents = []
    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                _warn_dispatch(
                    "agent record read failed; skipping "
                    f"path={f} error={type(exc).__name__}: {exc}"
                )
                continue
            status = (data.get("status") or "").lower()
            if status in {"running", "active", "in_progress", "claimed"}:
                active_agents.append(f.stem)

    return {
        "worktrees": worktrees,
        "active_agents": active_agents,
        "occupied": len(worktrees) + len(active_agents),
    }


def load_pending_tasks() -> list[dict]:
    if not NEXT_TASKS.exists():
        return []
    data = json.loads(NEXT_TASKS.read_text())
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return [t for t in data if (t.get("status") or "").lower() == "pending"]


def load_recent_task_type_counts(limit: int = 10) -> Counter:
    """Count recent dispatched task types from work_log for same-priority rotation.

    Lower counts should be preferred inside the same priority bucket so that
    one prolific type (for example experiments) does not crowd out newly
    arrived but equally important types such as event_article or
    trending_repost.
    """
    if not WORK_LOG.exists():
        return Counter()
    try:
        data = json.loads(WORK_LOG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _warn_dispatch(
            "work_log read failed; treating recent task type counts as empty "
            f"path={WORK_LOG} error={type(exc).__name__}: {exc}"
        )
        return Counter()
    if not isinstance(data, list):
        return Counter()

    recent = data[-limit:]
    counts: Counter = Counter()
    for item in recent:
        if not isinstance(item, dict):
            continue
        task_type = (item.get("task_type") or "").strip().lower()
        if task_type:
            counts[task_type] += 1
    return counts


def is_main_thread_only(task: dict) -> bool:
    """Detect main-thread-only markers in title, description, or tags.

    Triple-check: regex over text fields (covers descriptions phrased
    naturally with "main thread" / "NOT agent") AND explicit
    tags=['main-thread-only'] (covers cases where the task author wants
    to mark explicitly without relying on free-text phrasing).
    """
    tags = task.get("tags") or []
    if isinstance(tags, list) and "main-thread-only" in tags:
        return True
    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "notes")
    )
    return bool(MAIN_THREAD_MARKERS.search(blob))


def dispatch_lane(task: dict) -> str:
    """Return normalized schema-level dispatch lane, if present.

    `dispatch_lane` is the preferred ownership signal for newly materialized
    tasks. Free-text regex remains only as a legacy fallback because workflow
    descriptions often legitimately mention "main thread" without meaning the
    task itself is main-thread-owned.
    """
    lane = str(task.get("dispatch_lane") or task.get("dispatchLane") or "").strip().lower()
    return lane.replace("-", "_")


def detect_block_reason(task: dict) -> str | None:
    """Return blocked reason if task should be filtered from dispatch, else None.

    Priority order:
    1. Explicit task.blocked_reason field (hard block, set via CLI)
    2. blocked_until timestamp still in future
    3. Auto-detected from title/description (soft block — caller may
       optionally promote to hard block)
    """
    explicit = (task.get("blocked_reason") or "").strip().lower()
    if explicit:
        # Honor blocked_until expiry (auto-recheck): if blocked_until is in
        # the past, treat block as expired and let task return to pending.
        unblock_at = task.get("blocked_until")
        if unblock_at:
            try:
                deadline = datetime.fromisoformat(str(unblock_at).replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= deadline:
                    return None
            except (TypeError, ValueError) as exc:
                _warn_dispatch(
                    "invalid blocked_until for "
                    f"task {task.get('id', '<unknown>')}: {unblock_at!r} "
                    f"({type(exc).__name__}: {exc})"
                )
        return explicit

    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "notes")
    )
    if SELF_OPTIONAL_PATTERN.search(blob):
        return "self_tagged_optional"
    return None


def is_paper_task(task: dict) -> bool:
    """Paper writing tasks are main-thread-only per CLAUDE.md.

    2026-05-11 K898/K904 incident: daily_article tasks whose description
    cited a paper source (e.g. "[提出: Paper 3 R1 A.1, 執行: Claude]")
    were misclassified as paper writing — the regex `paper\\s*\\d+` matched
    in the verdict_preview but the task itself was a feed article about a
    K experiment, not body.tex editing.

    Fix: short-circuit when task_type=='daily_article' (articles about
    papers are still articles, not paper writing work). Other task_types
    follow the original regex.
    """
    task_type = (task.get("task_type") or "").lower()
    # daily_article + paper_review are both agentable; their ids may contain
    # `paper_` (paper_review_mile_*) or descriptions may cite paper sources.
    # 2026-05-11 incidents: K898/K904 daily_article + paper_review_mile_7ba7ee54.
    if task_type in ("daily_article", "paper_review"):
        return False
    blob = " ".join(
        str(task.get(k, "") or "") for k in ("title", "description", "id", "task_type")
    )
    return bool(
        re.search(
            r"paper\s*\d+|paper_|paper/.*\.tex|narrative\s*rewrite|"
            r"vix.sufficiency|paper.synthesis|integrate.*K\d+/K\d+",
            blob,
            re.IGNORECASE,
        )
    )


def categorize(tasks: list[dict], recent_type_counts: Counter | None = None) -> dict:
    recent_type_counts = recent_type_counts or Counter()
    agentable = []
    main_thread = []
    blocked = []
    for t in tasks:
        # Block check first — blocked tasks never enter dispatch or main_thread
        # queue (they're surfaced separately so the user/main thread can
        # periodically review and unblock).
        block_reason = detect_block_reason(t)
        if block_reason:
            blocked.append({"task": t, "reason": block_reason})
            continue

        lane = dispatch_lane(t)
        if lane in BLOCKED_DISPATCH_LANES:
            blocked.append({"task": t, "reason": f"dispatch_lane:{lane}"})
            continue
        if lane in AGENT_DISPATCH_LANES:
            agentable.append(t)
            continue
        if lane in MAIN_THREAD_DISPATCH_LANES:
            main_thread.append(t)
            continue
        if lane:
            blocked.append({"task": t, "reason": f"unknown_dispatch_lane:{lane}"})
            continue

        # P1 conservative default: P1 tasks are critical-tier, main-thread owns.
        # Legacy fallback still overrides via explicit task_type for known
        # agent-runnable auto flows when dispatch_lane is absent.
        priority = t.get("priority", 999)
        is_p1 = priority == 1
        # Explicit task_type overrides MAIN_THREAD_MARKERS regex false positives.
        # 2026-06-10 (strike 1): research backlog task descriptions contain
        # "主線程派 experiment agent 前先讀..." (= main thread DISPATCHES the
        # agent, not main thread does it), triggering MAIN_THREAD_MARKERS regex
        # on bare "主線程" → 5 yfinance experiments mis-tagged → pool stuck.
        # 2026-06-19 (strike 2, SAME ROOT): member_qa task descriptions contain
        # "主線程逐題做 4 維度評分 / 主線程派..." → member_qa mis-tagged
        # main_thread → hourly dispatch never picks it → member Q&A stale 28h.
        # Root: task ownership must come from the task_type SCHEMA field, not
        # free-text grep of the description (which legitimately describes
        # workflow steps mentioning 主線程). These types are cron-materialized
        # auto-flows that hourly dispatch should route (member_qa stays Claude-
        # only via task-routing rule + model_router, agentable just means
        # auto-dispatchable rather than waiting for an interactive session).
        explicit_agentable = (t.get("task_type") or "").lower() in (
            "experiment",
            "member_qa",
        )
        if explicit_agentable:
            agentable.append(t)
        elif is_main_thread_only(t) or is_paper_task(t):
            main_thread.append(t)
        elif is_p1:
            main_thread.append(t)
        else:
            agentable.append(t)

    def _prio_key(v):
        s = str(v)
        return int(s[1:]) if s.startswith("P") and s[1:].isdigit() else (int(s) if str(s).isdigit() else 999)

    def _agentable_sort_key(task: dict) -> tuple[int, int, str]:
        task_type = str(task.get("task_type") or "").strip().lower()
        return (
            _prio_key(task.get("priority", 999)),
            recent_type_counts.get(task_type, 0),
            str(task.get("id", "")),
        )

    agentable.sort(key=_agentable_sort_key)
    main_thread.sort(key=lambda t: (_prio_key(t.get("priority", 999)), str(t.get("id", ""))))
    blocked.sort(key=lambda b: (_prio_key(b["task"].get("priority", 999)), str(b["task"].get("id", ""))))
    return {"agentable": agentable, "main_thread": main_thread, "blocked": blocked}


def _current_agentable_count() -> int:
    """Recompute live agentable pending count after refill side effects."""
    recent_type_counts = load_recent_task_type_counts()
    cats = categorize(load_pending_tasks(), recent_type_counts=recent_type_counts)
    return len(cats["agentable"])


def _materialize_pool_dry_diagnostic_task(now: datetime | None = None) -> dict:
    """Create one daily platform_ops task when all refill sources are dry.

    This is a last-resort breaker, not a content generator. If every refill
    source adds zero tasks, hourly dispatch should surface an actionable
    platform task instead of silently no-oping with an empty pool.
    """
    now = now or datetime.now(timezone.utc)
    task_id = f"{POOL_DRY_DIAGNOSTIC_PREFIX}_{now.strftime('%Y%m%d')}"
    task = {
        "id": task_id,
        "title": "Dispatcher pool-dry diagnostic: all refill sources returned no new tasks",
        "description": (
            "continue_task_dispatch saw agentable=0, and diverse/event/article/"
            "research refill all added 0 tasks. Diagnose why the pool is dry, "
            "verify publication_candidates/research_program/backlog freshness, "
            "and either fix the generator or explicitly document that the pool "
            "is intentionally exhausted."
        ),
        "task_type": "platform_ops",
        "priority": 3,
        "status": "pending",
        "created_at": now.isoformat(),
        "source": "continue_task_dispatch_pool_dry_breaker",
        "tags": ["dispatch", "refill", "pool-dry", "platform_ops"],
    }

    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]\n", encoding="utf-8")

    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            payload = json.load(fh)
            tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
            if not isinstance(tasks, list):
                return {"ok": False, "added": 0, "error": "next_tasks.json is not a list"}

            if any(item.get("id") == task_id for item in tasks if isinstance(item, dict)):
                return {
                    "ok": True,
                    "added": 0,
                    "reason": "pool_dry_diagnostic_already_exists_today",
                    "added_ids": [],
                }

            tasks.insert(0, task)
            fh.seek(0)
            fh.truncate()
            json.dump(payload if isinstance(payload, dict) else tasks, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            return {
                "ok": True,
                "added": 1,
                "added_ids": [task_id],
                "by_type": {"platform_ops": 1},
            }
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class ArticleRefillTimeoutError(TimeoutError):
    pass


def _run_article_refill(target: int, *, dry_run: bool = False) -> dict:
    """Run article refill with a hard timeout so dispatch cannot hang forever."""
    from refill_task_pool import refill as _refill_fn  # type: ignore

    timeout_s = ARTICLE_REFILL_TIMEOUT_SECONDS
    if timeout_s <= 0:
        return _refill_fn(target=target, dry_run=dry_run)

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(_signum, _frame):
        raise ArticleRefillTimeoutError(f"timed out after {timeout_s}s")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return _refill_fn(target=target, dry_run=dry_run)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _maybe_refill(agentable_count: int, *, auto_refill: bool) -> dict | None:
    """Auto-trigger pool refill when agentable < REFILL_FLOOR.

    Two-stage refill (2026-05-06 diversity fix):
    1. `generate_diverse_tasks.generate()` — non-article sources (paper_review,
       platform_ops, governance). Quota-capped, won't dominate pool, but ensures
       pool isn't 100% daily_article (CLAUDE.md 關 2 diversity rule).
    2. `refill_task_pool.refill()` — backfill remaining gap with auto-discovered
       daily_article tasks from publication_candidates.

    Returns combined result dict; quiet-on-no-add for healthy steady state.
    """
    if not auto_refill:
        return None
    if agentable_count >= REFILL_FLOOR:
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    combined: dict = {"ok": True, "added": 0, "added_ids": [], "by_type": {}}
    try:
        from generate_diverse_tasks import generate as _diverse_gen  # type: ignore
        diverse = _diverse_gen(dry_run=False)
        if diverse.get("added"):
            combined["added"] += diverse["added"]
            combined["added_ids"].extend(diverse.get("added_ids") or [])
            combined["by_type"].update(diverse.get("by_type") or {})
    except Exception as exc:  # noqa: BLE001
        combined.setdefault("warnings", []).append(f"diverse_gen: {exc}")

    try:
        current_agentable = _current_agentable_count()
        if current_agentable < REFILL_FLOOR:
            try:
                from refill_reader_facing_pool import refill_event_candidates as _event_refill  # type: ignore
                event_result = _event_refill(horizon_days=14)
                event_added = len(event_result.get("added") or [])
                if event_added:
                    combined["added"] += event_added
                    combined["added_ids"].extend(event_result.get("added") or [])
                    combined["by_type"]["event_article"] = event_added
            except Exception as exc:  # noqa: BLE001
                combined.setdefault("warnings", []).append(f"event_refill: {exc}")

        current_agentable = _current_agentable_count()
        gap = max(0, REFILL_FLOOR - current_agentable)
        if gap > 0:
            try:
                article = _run_article_refill(target=gap, dry_run=False)
                if article.get("added"):
                    combined["added"] += article["added"]
                    combined["added_ids"].extend(article.get("added_ids") or [])
                    combined["by_type"]["daily_article"] = article["added"]
                elif article.get("ok") is False:
                    combined.setdefault("warnings", []).append(
                        f"article_refill: {article.get('reason') or article.get('error')}"
                    )
            except Exception as exc:  # noqa: BLE001
                combined.setdefault("warnings", []).append(f"article_refill: {exc}")

        # Stage 3 (2026-05-12 fix): If pool still below floor, auto-spawn
        # K-experiment briefs from research_program.md unchecked items. Closes
        # the recurring `agentable=0` plateau where publication_candidates
        # is fully covered but research_program.md still has open questions.
        # The dispatcher must NEVER idle when the project has unfinished
        # research — pool stays full via autonomous research generation.
        current_agentable = _current_agentable_count()
        gap = max(0, REFILL_FLOOR - current_agentable)
        if gap > 0:
            try:
                from generate_research_backlog import generate as _research_gen  # type: ignore
                research = _research_gen(dry_run=False, max_new=gap)
                if research.get("added"):
                    combined["added"] += research["added"]
                    combined["added_ids"].extend(research.get("added_ids") or [])
                    combined["by_type"]["experiment_autonomous"] = research["added"]
            except Exception as exc:  # noqa: BLE001
                combined.setdefault("warnings", []).append(f"research_backlog: {exc}")

        # Last-resort breaker: if every refill source returned zero additions,
        # leave an agentable diagnostic task instead of letting hourly no-op.
        if agentable_count == 0 and combined["added"] == 0:
            diagnostic = _materialize_pool_dry_diagnostic_task()
            if diagnostic.get("added"):
                combined["added"] += diagnostic["added"]
                combined["added_ids"].extend(diagnostic.get("added_ids") or [])
                combined["by_type"].update(diagnostic.get("by_type") or {})
            elif diagnostic.get("ok") is False:
                combined.setdefault("warnings", []).append(
                    f"pool_dry_diagnostic: {diagnostic.get('error') or diagnostic.get('reason')}"
                )
            else:
                combined["reason"] = diagnostic.get("reason") or "pool_dry_diagnostic_not_added"
    except Exception as exc:  # noqa: BLE001
        combined.setdefault("warnings", []).append(f"article_refill: {exc}")
        combined["ok"] = combined.get("ok", True)

    if combined["added"] == 0 and not combined.get("warnings"):
        return {"ok": True, "added": 0, "reason": "no_new_signal"}
    return combined


def build_report(*, auto_refill: bool = True) -> dict:
    slots = count_active_slots()
    pending = load_pending_tasks()
    recent_type_counts = load_recent_task_type_counts()
    cats = categorize(pending, recent_type_counts=recent_type_counts)

    refill_result = _maybe_refill(len(cats["agentable"]), auto_refill=auto_refill)
    if refill_result and refill_result.get("added"):
        # Reload after refill so the report shows the fresh tasks
        pending = load_pending_tasks()
        cats = categorize(pending, recent_type_counts=recent_type_counts)

    free_slots = max(0, SLOT_CAP - slots["occupied"])
    candidates_to_dispatch = cats["agentable"][:free_slots]
    pending_summary = {
        "agentable": len(cats["agentable"]),
        "main_thread": len(cats["main_thread"]),
        "blocked": len(cats["blocked"]),
        "label": (
            f"agentable {len(cats['agentable'])} / "
            f"main_thread {len(cats['main_thread'])} / "
            f"blocked {len(cats['blocked'])}"
        ),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slot_cap": SLOT_CAP,
        "slot_state": slots,
        "free_slots": free_slots,
        "pending_total": len(pending),
        "pending_agentable": len(cats["agentable"]),
        "pending_main_thread": len(cats["main_thread"]),
        "pending_blocked": len(cats["blocked"]),
        "pending_summary": pending_summary,
        "dispatch_candidates": [
            {
                "id": t.get("id"),
                "priority": t.get("priority"),
                "title": (t.get("title") or t.get("description") or "")[:120],
            }
            for t in candidates_to_dispatch
        ],
        "main_thread_queue_top5": [
            {
                "id": t.get("id"),
                "priority": t.get("priority"),
                "title": (t.get("title") or t.get("description") or "")[:120],
            }
            for t in cats["main_thread"][:5]
        ],
        "refill": refill_result,
        "blocked_tasks": [
            {
                "id": b["task"].get("id"),
                "priority": b["task"].get("priority"),
                "reason": b["reason"],
                "title": (b["task"].get("title") or b["task"].get("description") or "")[:120],
                "blocked_at": b["task"].get("blocked_at"),
                "blocked_until": b["task"].get("blocked_until"),
            }
            for b in cats["blocked"]
        ],
    }


def print_report(report: dict) -> None:
    print(f"[dispatch] generated_at={report['generated_at']}")
    s = report["slot_state"]
    pending_summary = report.get("pending_summary", {})
    pending_label = pending_summary.get(
        "label",
        f"agentable {report['pending_agentable']} / "
        f"main_thread {report['pending_main_thread']} / "
        f"blocked {report.get('pending_blocked', 0)}",
    )
    print(
        f"[dispatch] slots: occupied={s['occupied']}/{report['slot_cap']} "
        f"(worktrees={len(s['worktrees'])}, active_agents={len(s['active_agents'])}) "
        f"free={report['free_slots']}"
    )
    print(
        f"[dispatch] pending: total={report['pending_total']} "
        f"{pending_label} "
        f"blocked={report.get('pending_blocked', 0)}"
    )

    if report["dispatch_candidates"]:
        print(f"[dispatch] candidates to dispatch ({len(report['dispatch_candidates'])}):")
        for c in report["dispatch_candidates"]:
            print(f"  - P{c['priority']} {c['id']} :: {c['title']}")
    else:
        print("[dispatch] NO agent dispatch candidates "
              "(slot full or all pending are main-thread-only)")

    if report["main_thread_queue_top5"]:
        print("[dispatch] main-thread queue (top 5):")
        for c in report["main_thread_queue_top5"]:
            print(f"  - P{c['priority']} {c['id']} :: {c['title']}")

    refill = report.get("refill") or {}
    if refill.get("added"):
        print(f"[dispatch] auto-refill: +{refill['added']} tasks {refill.get('added_ids')}")
    elif refill.get("ok") is False:
        print(f"[dispatch] auto-refill error: {refill.get('error') or refill.get('reason')}")

    blocked = report.get("blocked_tasks") or []
    if blocked:
        print(f"[dispatch] blocked ({len(blocked)}):")
        for b in blocked[:8]:
            until = f" until={b['blocked_until']}" if b.get("blocked_until") else ""
            print(f"  - P{b['priority']} {b['id']} reason={b['reason']}{until}")
        if len(blocked) > 8:
            print(f"  ... and {len(blocked) - 8} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只列 candidates，不派工")
    parser.add_argument("--report", action="store_true", help="寫 report 到 dispatch_report_latest.json")
    parser.add_argument("--execute", action="store_true", help="reserved (尚未實作 actual spawn)")
    parser.add_argument("--no-refill", action="store_true",
                        help="skip auto-refill even if agentable < floor (debug only)")
    args = parser.parse_args()

    report = build_report(auto_refill=not args.no_refill)
    print_report(report)

    if args.report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"[dispatch] report written: {REPORT_PATH}")

    if args.execute:
        print("[dispatch] --execute not yet implemented; main-thread should pick up candidates and dispatch agents (Task tool / claude general-purpose / codex-rescue) per .claude/rules/agent-delegation.md")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
