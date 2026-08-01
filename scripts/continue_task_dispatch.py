#!/usr/bin/env python3
"""Slot-aware continuation dispatcher (replaces stub-only continue_task host cron).

讀 storage/next_tasks.json 的 pending queue，候選排序最外層先按 lane rank
（task_urgency：urgent boss 急件 → time_critical 時效任務 → 其餘；lane 內 FIFO），
lane 之後才是既有 priority asc + 餓死保護 + 同 priority 多樣性輪替，
count 當前正式 execution lease / active agent slot（worktree 只作 artifact custody），
若 slot < cap (4) 且有可派 agent 的 task → 列出 / 派出（依 mode）。

執行模式：
  --dry-run    read-only 巡檢：retire/sweep/refill/promote 一律不執行寫入，
               report 只進 stdout、不落地（2026-07-20 WS-H4 修真：此旗標過去
               宣告後從未被 main() 讀取，掛著 --dry-run 也跑含寫入的完整流程，
               見 docs/dispatch-decision-pipeline-design.md §1.2）
  --report     寫 report 到 storage/ops/dispatch_report_latest.json（--dry-run 時改印 stdout）
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

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from model_router import pick_topology  # noqa: E402  (2026-07-10 topology-audit：拓撲隨 lane 一起機械路由)


def _coerce_priority(v) -> int:
    """Normalize priority to int: 1/"1"/"P1" → 1; unknown → 999 (queue tail).

    2026-07-05: the pool has 90 string-form "P<n>" priorities written by
    agents; every reader must coerce identically or P1 semantics silently
    break (routing, sorting, handoff display).
    """
    s = str(v).strip()
    if s.upper().startswith("P") and s[1:].isdigit():
        return int(s[1:])
    if s.isdigit():
        return int(s)
    return 999


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
# No WORKTREES_DIR / AGENTS_DIR here: `dispatch_slot_budget` owns occupancy and
# owns those paths. Re-declaring them would give a test something to monkeypatch
# that nothing reads — a patch that silently no-ops and lets the test fall
# through to the real repo. That is what broke CI on 2026-07-13.
REPORT_PATH = ROOT / "storage" / "ops" / "dispatch_report_latest.json"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
# Slot cap AND occupancy both live in `scripts/dispatch_slot_budget.py` — it is the
# single enforcement owner. A hardcoded `SLOT_CAP = 4` used to sit here while the
# budget module computed 4/6/2 dynamically; the two disagreed and this one won,
# because it was the one the dispatcher actually read (2026-07-13). Do not
# reintroduce a literal here — `scripts/tests/test_dispatch_slot_budget.py`
# fails the build if one comes back.

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_slot_budget as _slot_budget  # noqa: E402

from volpred.ops.next_tasks import normalize_task_priorities, normalize_task_priority  # noqa: E402
from volpred.ops.task_dispatch_collision import (  # noqa: E402
    find_task_dispatch_collisions as _find_task_dispatch_collisions,
)
from volpred.ops.task_pool_selection import (  # noqa: E402
    STARVATION_HOURS,
    STARVATION_HOURS_DEFAULT,  # noqa: F401 - compatibility re-export
    find_starved,
    starvation_threshold_hours,  # noqa: F401 - compatibility re-export
    task_age_hours,
)
# 2026-07-01 3-STRIKE fix (dreaming persistent_alert draft_pool_low, 5x/73d):
# `draft_pool_low` alert (src/volpred/ops/alerts.py::_parse_draft_pool_state)
# measures feed.json `status=="draft"` article count directly — a DIFFERENT
# signal from `REFILL_FLOOR` below, which only counts pending `next_tasks.json`
# agentable tasks (any task_type). Root cause of the recurring breach: a pool
# can satisfy REFILL_FLOOR with 4 agentable `experiment`/`platform_ops` tasks
# while daily_article production silently starves — `_maybe_refill` never
# looks at feed.json, so draft-pool depletion never forces a daily_article-
# specific top-up. This constant is the dedicated floor for that separate
# signal; see `_draft_pool_deficit()` / `_maybe_refill_draft_pool()`.
DRAFT_POOL_FLOOR = 6
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
from volpred.ops.next_tasks import (  # noqa: E402
    AGENT_DISPATCH_LANES,
    BLOCKED_DISPATCH_LANES,
    MAIN_THREAD_DISPATCH_LANES,
)

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
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops import task_urgency as _task_urgency  # noqa: E402  (2026-07-21 R1: lane rank 的唯一判定 owner)
from volpred.ops.diagnostics import warn as _diag_warn  # noqa: E402
from volpred.ops.task_pool_selection import (  # noqa: E402
    GENERIC_BACKGROUND_HARD_DENY_TASK_TYPES,
    normalize_task_type_value,
    requires_supervisor_preassignment,
)
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

SELF_OPTIONAL_PATTERN = re.compile(
    r"\(\s*optional\s*\)|（\s*optional\s*）|"
    r"only\s+if\s+truly\s+new|"
    r"否則跳過|skip\s+if\s+already",
    re.IGNORECASE,
)


def _warn_dispatch(message: str) -> None:
    _diag_warn("dispatch", message)


def count_active_slots() -> dict:
    """Occupied slots. Thin delegate — `dispatch_slot_budget.occupancy()` owns this.

    Worktree directories, commits and dirty-file mtimes are artifact custody,
    never capacity authority. Only formal running/unverified execution receipts
    and active agent records hold slots; terminal/unleased worktrees remain in
    the report for salvage without blocking admission. See the budget module's
    lifecycle contract.
    """
    return _slot_budget.occupancy()


def load_pending_tasks() -> list[dict]:
    if not NEXT_TASKS.exists():
        return []
    try:
        data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _warn_dispatch(
            "next_tasks read failed; treating pending queue as empty "
            f"path={NEXT_TASKS} error={type(exc).__name__}: {exc}"
        )
        return []
    if isinstance(data, dict):
        data = data.get("tasks", [])
    if not isinstance(data, list):
        _warn_dispatch(
            "next_tasks schema invalid; expected list or object.tasks list "
            f"path={NEXT_TASKS} type={type(data).__name__}"
        )
        return []
    pending: list[dict] = []
    for idx, task in enumerate(data):
        if not isinstance(task, dict):
            _warn_dispatch(
                "next_tasks entry schema invalid; skipping "
                f"path={NEXT_TASKS} index={idx} type={type(task).__name__}"
            )
            continue
        if (task.get("status") or "").lower() == "pending":
            pending.append(task)
    return pending


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
        _warn_dispatch(
            "work_log is not a list; treating recent task type counts as empty "
            f"path={WORK_LOG} type={type(data).__name__}"
        )
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
            deadline = parse_iso_warn(
                unblock_at,
                tag="dispatch",
                field_name="blocked_until",
                fallback=None,
                task_id=str(task.get("id", "<unknown>")),
            )
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                return None
            # parse failed → WARN already emitted; keep hard block (don't auto-recheck)
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

    Fix: short-circuit when task_type is an article flow (articles about
    papers are still articles, not paper writing work). Other task_types
    follow the original regex.
    """
    task_type = (task.get("task_type") or "").lower()
    # daily_article + paper_review are both agentable; their ids may contain
    # `paper_` (paper_review_mile_*) or descriptions may cite paper sources.
    # 2026-05-11 incidents: K898/K904 daily_article + paper_review_mile_7ba7ee54.
    if task_type in ("daily_article", "daily_digest", "paper_review"):
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


def apply_starved_tail_floor(
    starved: list[dict],
    candidates: list[dict],
    free_slots: int,
    preempt_ids: set,
) -> list[dict]:
    """Reserve one candidate slot for the lowest starved priority band.

    `find_starved` orders the starved set priority-first, and that ordering is
    right on its own terms (see its docstring). But the candidate list is then
    truncated to `free_slots`, and when the starved set is *dominated* by higher
    priorities the tail never appears in it — starved in the report, unreachable
    in practice. 2026-07-21 (boss telegram-1224): 20 dreaming-derived rows, the
    oldest 84h past its own 72h P3 line, sat behind 37 pending P1 and 53 P2. The
    lockout said "先清光餓死的任務"; the P3 band had no arrival rate at which it
    could ever be cleared, so the critical findings those rows owned stayed red
    indefinitely and the review alert kept re-reporting them.

    The floor is one slot, taken from the *last* non-preempt candidate: it drains
    the tail at ≥1 task per fire while costing the top band at most one seat per
    fire, and it never displaces an incident preempt (already-materialised P1
    response work — displacing it is what the preempt lane exists to prevent).
    Below 2 free slots there is no floor: a single slot must go to the top band,
    otherwise the P1 starvation this whole mechanism exists to end comes back.
    """
    if free_slots < 2 or not starved or not candidates:
        return candidates
    tail_priority = max(_coerce_priority(s["task"].get("priority", 999)) for s in starved)
    present = {_coerce_priority(t.get("priority", 999)) for t in candidates}
    if tail_priority in present:
        return candidates
    chosen_ids = {t.get("id") for t in candidates}
    tail_rows = [
        s
        for s in starved
        if _coerce_priority(s["task"].get("priority", 999)) == tail_priority
        and s["task"].get("id") not in chosen_ids
        and s["task"].get("id") not in preempt_ids
    ]
    if not tail_rows:
        return candidates
    tail_task = max(tail_rows, key=lambda s: s["over_by_hours"])["task"]
    kept = list(candidates)
    if len(kept) < free_slots:
        kept.append(tail_task)
        return kept
    # At capacity: evict the last candidate that is not an incident preempt.
    for idx in range(len(kept) - 1, -1, -1):
        if kept[idx].get("id") not in preempt_ids:
            kept[idx] = tail_task
            return kept
    return candidates


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
        task_type = normalize_task_type_value(t.get("task_type"))
        if lane in BLOCKED_DISPATCH_LANES:
            blocked.append({"task": t, "reason": f"dispatch_lane:{lane}"})
            continue
        if lane in MAIN_THREAD_DISPATCH_LANES:
            main_thread.append(t)
            continue
        if task_type in GENERIC_BACKGROUND_HARD_DENY_TASK_TYPES:
            main_thread.append(t)
            continue
        if lane in AGENT_DISPATCH_LANES:
            agentable.append(t)
            continue
        if lane:
            blocked.append({"task": t, "reason": f"unknown_dispatch_lane:{lane}"})
            continue

        # P1 conservative default: P1 tasks are critical-tier, main-thread owns.
        # Legacy fallback still overrides via explicit task_type for known
        # agent-runnable auto flows when dispatch_lane is absent.
        priority = t.get("priority", 999)
        # 2026-07-05 fix: agents sometimes write string "P1"/"P3" priorities;
        # `priority == 1` missed "P1" so a boss-assigned P1 task leaked out of
        # the conservative main-thread lane (msg143 task sat 27h). Coerce first.
        is_p1 = _coerce_priority(priority) == 1
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
        explicit_agentable = task_type in (
            "experiment",
            "event_article",
            "member_qa",
            "daily_article",
            "daily_digest",
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
        return _coerce_priority(v)

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


def resolve_dispatch_ownership(
    tasks: list[dict],
    *,
    recent_type_counts: Counter | None = None,
    repo_root: Path = ROOT,
    now: datetime | None = None,
) -> dict:
    """Resolve the shared worker/supervisor boundary and collision gate.

    Both the read-only dispatch report and the supervisor's pre-spawn admission
    call this seam. Keeping categorisation or worktree-collision filtering in
    either caller would let the report advertise one task while the real fire
    admits another.
    """

    cats = categorize(tasks, recent_type_counts=recent_type_counts)
    supervisor_only = [
        task
        for task in cats["agentable"]
        if requires_supervisor_preassignment(task)
    ]
    worker_claimable = [
        task
        for task in cats["agentable"]
        if not requires_supervisor_preassignment(task)
    ]
    collision_blocked_tasks: list[dict] = []
    collision_scan_error: str | None = None
    if worker_claimable:
        try:
            collision_by_id = _find_task_dispatch_collisions(
                repo_root=repo_root,
                task_ids=(
                    str(task.get("id") or "")
                    for task in worker_claimable
                ),
                target_workdir=repo_root,
            )
        except RuntimeError as exc:
            collision_scan_error = f"{type(exc).__name__}: {exc}"
            collision_by_id = {}
        if collision_scan_error is None:
            collision_blocked_tasks = [
                {
                    "id": task.get("id"),
                    "priority": task.get("priority"),
                    "task_type": task.get("task_type"),
                    "age_hours": task_age_hours(task, now=now),
                    **collision_by_id[str(task.get("id") or "")],
                }
                for task in worker_claimable
                if str(task.get("id") or "") in collision_by_id
            ]
            collision_blocked_ids = {
                item["id"] for item in collision_blocked_tasks
            }
            worker_claimable = [
                task
                for task in worker_claimable
                if task.get("id") not in collision_blocked_ids
            ]
        else:
            worker_claimable = []
    return {
        "categories": cats,
        "supervisor_only": supervisor_only,
        "worker_claimable": worker_claimable,
        "collision_blocked_tasks": collision_blocked_tasks,
        "collision_scan_error": collision_scan_error,
    }


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
    normalize_task_priority(task)

    guard_canonical_write(NEXT_TASKS)
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

            if isinstance(payload, dict):
                # WS-A1b：dict 包裝殼只剩讀取容忍；canonical root 自 2026-07-16
                # single-gateway 起固定為 list（兩份 live queue 皆已實測
                # list-root）。原本這裡保留一份 write_tasks_to_handle 的手抄
                # serialize-first 複本 —— 正是 helper 演進時最會漂移的形狀 ——
                # 現改為 loud reject，與其他 writer 的 dict-root 處置一致。
                _diag_warn(
                    "next_tasks_write",
                    "dict-root next_tasks shape is no longer writable; canonical root is a list",
                )
                return {
                    "ok": False,
                    "added": 0,
                    "error": "next_tasks.json root must be a list (single-gateway 2026-07-16)",
                }
            tasks.insert(0, task)
            normalize_task_priorities(tasks)
            from volpred.ops.next_tasks import write_tasks_to_handle

            write_tasks_to_handle(fh, tasks)
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


def _run_article_refill(
    target: int, *, dry_run: bool = False, reader_facing_only: bool = False
) -> dict:
    """Run article refill with a hard timeout so dispatch cannot hang forever.

    `reader_facing_only=True` (2026-07-04 ROOTFIX) makes refill produce ONLY
    reader-facing article tasks and skip the `experiment` fallback that fires
    when the uncovered-K article pool is exhausted — experiment tasks never
    become releasable drafts, so letting refill "succeed" with them masks a real
    reader-content drought (the draft-pool refill must heal reader throughput,
    not the research backlog). Matches remediate_publish_drought.py's choice.
    """
    from refill_task_pool import refill as _refill_fn  # type: ignore

    timeout_s = ARTICLE_REFILL_TIMEOUT_SECONDS
    if timeout_s <= 0:
        return _refill_fn(target=target, dry_run=dry_run, reader_facing_only=reader_facing_only)

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(_signum, _frame):
        raise ArticleRefillTimeoutError(f"timed out after {timeout_s}s")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return _refill_fn(target=target, dry_run=dry_run, reader_facing_only=reader_facing_only)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _raw_draft_count() -> int:
    """Raw status=="draft" count in feed.json (legacy signal / fail-open fallback)."""
    if not FEED_PATH.exists():
        _warn_dispatch(f"draft_pool_deficit: feed path missing at {FEED_PATH}")
        return 0
    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(feed, list):
        _warn_dispatch(f"draft_pool_deficit: feed.json top-level is {type(feed).__name__}, expected list")
        return 0
    return sum(1 for item in feed if isinstance(item, dict) and item.get("status") == "draft")


def _releasable_draft_count() -> int | None:
    """Count drafts that release_pool_by_settings can ACTUALLY release right now.

    Reuses the release path's own post-dedup `eligible` count
    (preview_release_pool_by_settings.pool_counts.eligible) so the draft-floor
    signal cannot drift from what release actually publishes — single source of
    truth, no new dedup heuristic (anti-stacking).

    Returns None on ANY failure (import error, preview raise, or non-numeric
    eligible) so `_draft_pool_deficit` falls back to the raw draft count rather
    than mis-reading a preview failure as "0 releasable → deficit 0 → no refill"
    (Codex CONDITIONAL_PASS finding, 2026-07-04: a raise here must degrade to
    the raw-count path, not to a silent zero deficit that would re-drought).
    """
    try:
        from volpred.ops.content import preview_release_pool_by_settings

        counts = preview_release_pool_by_settings().get("pool_counts") or {}
        eligible = counts.get("eligible")
        return int(eligible) if isinstance(eligible, (int, float)) else None
    except Exception as e:  # noqa: BLE001 — failure must degrade to raw-count fallback, not zero
        _warn_dispatch(f"releasable_draft_count: preview failed ({e!r}); caller falls back to raw draft count")
        return None


def _in_flight_article_task_count() -> int:
    """Reader-facing `daily_article` tasks already queued/running in next_tasks.json.

    These are pipeline stock: a freshly-refilled daily_article task takes hours
    to be dispatched into a published draft, during which `_releasable_draft_count`
    stays low. Counting in-flight article tasks against the deficit makes the
    refill self-limiting — without it the releasability-aware deficit would
    re-fire every tick and pile up dozens of pending article tasks before the
    first fresh draft lands. Fail-open to 0 (never crash dispatch).
    """
    try:
        if not NEXT_TASKS.exists():
            return 0
        data = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        if not isinstance(tasks, list):
            return 0
        active = {"pending", "pending_main_thread", "in_progress", "claimed", "running"}
        return sum(
            1
            for t in tasks
            if isinstance(t, dict)
            and str(t.get("task_type") or "") == "daily_article"
            and str(t.get("status") or "pending").lower() in active
        )
    except Exception as e:  # noqa: BLE001 — fail-open, but observable
        _warn_dispatch(f"in_flight_article_task_count: read failed ({e!r}); treating as 0")
        return 0


def _draft_pool_deficit() -> int:
    """Fresh reader-facing article tasks needed to keep the RELEASABLE draft
    buffer at DRAFT_POOL_FLOOR.

    2026-07-04 ROOTFIX (release-layer deadlock; boss telegram msg114
    「頭痛醫頭腳痛醫腳」): publish throughput depends on drafts release can
    ACTUALLY release, not the raw status=="draft" count. The prior raw-count
    version was blind to releasability — a pool of 6 arc-dup / dedup-flagged
    drafts (all unreleasable) read as fully stocked (deficit=0), so the
    2026-07-01 proactive refill never fired, the release cadence released
    nothing, and publishing droughted (07-03 blocked_pool=6, eligible=0). Root
    fix: stock = release path's own post-dedup `eligible` count + in-flight
    daily_article tasks (pipeline that becomes releasable drafts), so the
    draft-floor signal agrees with what release can publish and self-limits
    against re-refill pile-up. Fail-open to the legacy raw draft count on any
    error (never crash dispatch).
    """
    try:
        releasable = _releasable_draft_count()
        if releasable is None:
            _warn_dispatch("draft_pool_deficit: releasable count unavailable; falling back to raw draft count")
            releasable = _raw_draft_count()
        stock = releasable + _in_flight_article_task_count()
        return max(0, DRAFT_POOL_FLOOR - stock)
    except Exception as e:  # noqa: BLE001 — fail-open by design, but must not be silent
        _warn_dispatch(f"draft_pool_deficit: compute failed ({e!r}); treating as no deficit")
        return 0


def _promote_starved_article_tasks(limit: int) -> int:
    """Releasable-drought escalation：把餓死的 pending 文章任務**一次批次**升 P1。

    2026-07-15 owner 指令（「你要補滿文章補到最低門檻 不是一篇一篇補」，01:0x）：
    當晚 releasable drafts=0，但 next_tasks 有 6 個 pending daily_article 掛在
    P3/P4 —— `_draft_pool_deficit()` 把它們算成 in-flight 庫存（deficit=0，refill
    不動），dispatch 卻每班都被 ops P1/P2 搶走，pending 是「餓死的庫存」。
    Pending ≠ pipeline，除非 dispatch 優先序真的搆得到它。

    修法：釋出池真乾涸（releasable==0）時，晉升既有 pending 文章任務到 P1（最多
    `limit` 個、一次到位），而不是加開新任務 —— 保留 in-flight 自我節制（防
    pile-up），只修 dispatch 搆不到的問題。Fail-open：任何錯誤回 0 並留 trace。

    **本函式是 R2 admission clamp（``clamp_machine_priority_inflation``）的
    deliberate exception，不得收編進 gateway**（2026-07-21 dispatch-lanes）：
    clamp 擋的是生成端在**建單時**自封 P1（機器來源無權宣告自己緊急）；這裡是
    dispatch 端在**現場量測到 releasable==0** 後的事後晉升 —— 緊急性來自當下實測
    的乾涸訊號，不是生成器的自我宣告，語意上正是 clamp 要保護的那種「真時效」
    授權點。若把這條 in-place 提升改走 append_task_record，clamp 會把晉升立刻
    夾回 P2，drought escalation 整條失效（pin test：
    scripts/tests/test_promote_starved_article_tasks.py
    ::test_promotion_is_deliberate_exception_to_machine_p1_clamp）。
    """
    if not NEXT_TASKS.exists():
        return 0
    # Outside the try on purpose: the guard's whole job is to abort a write from a
    # context that must not touch canonical storage, and an except that swallows it
    # would turn that abort back into the write it exists to stop.
    guard_canonical_write(NEXT_TASKS)
    try:
        with open(NEXT_TASKS, "r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                _warn_dispatch("promote_starved_articles: next_tasks not a list; skip")
                return 0
            promoted = 0
            for t in tasks:
                if promoted >= limit:
                    break
                try:
                    pri = int(t.get("priority") or 9)
                except (TypeError, ValueError):
                    pri = 9
                if (
                    isinstance(t, dict)
                    and str(t.get("task_type") or "") == "daily_article"
                    and str(t.get("status") or "pending").lower() == "pending"
                    and pri > 1
                ):
                    t["priority"] = 1
                    t["priority_note"] = (
                        "auto-promoted to P1 by _promote_starved_article_tasks: "
                        "releasable drafts=0 while this task sat below dispatch reach "
                        "(owner rule 2026-07-15: fill to floor in one batch)"
                    )
                    promoted += 1
            if promoted:
                from volpred.ops.next_tasks import write_tasks_to_handle

                write_tasks_to_handle(fh, tasks)
                _warn_dispatch(
                    f"promote_starved_articles: promoted {promoted} pending daily_article task(s) to P1"
                )
            return promoted
    except Exception as e:  # noqa: BLE001 — fail-open, but observable
        _warn_dispatch(f"promote_starved_articles: failed ({e!r}); promoted nothing")
        return 0


def _maybe_refill_draft_pool(*, auto_refill: bool, dry_run: bool = False) -> dict | None:
    """Force a daily_article-specific top-up when feed.json draft count is low.

    2026-07-01 3-STRIKE fix: `_maybe_refill` below only reacts to the
    next_tasks.json agentable-task-count signal, which can stay >= REFILL_FLOOR
    while composed entirely of non-article task types (experiment,
    platform_ops, ...). That leaves the actual publish-ready draft buffer
    (feed.json status=="draft") free to run dry even though the dispatcher
    "sees" a healthy pool — this was the root cause of `draft_pool_low` firing
    5x over 73 days (docs/error_log.md 2026-07-01 entry). This function checks
    the feed-level signal directly and, if deficient, calls the same
    `refill_task_pool.refill()` used by `_maybe_refill` but targeted at the
    feed deficit specifically — bypassing the diversity de-prioritization that
    would otherwise let a thin draft buffer sit unaddressed while other task
    types occupy the agentable queue.
    """
    if not auto_refill:
        return None
    # 2026-07-15 owner order（「補滿到最低門檻 不是一篇一篇補」）：releasable==0 是
    # 真乾涸訊號 —— 下面的 deficit 會被 in-flight pending 遮住（設計上防 pile-up），
    # 但 pending 掛在 P>1 時 dispatch 永遠搆不到。先批次晉升，再談要不要加新任務。
    try:
        _releasable_now = _releasable_draft_count()
    except Exception:  # noqa: BLE001 — 訊號取不到就不晉升，refill 路徑照舊
        _releasable_now = None
    if dry_run:
        # WS-H4 dry-run 修真：只預覽訊號，不晉升、不補池。這條路徑上任何寫入都是
        # 「以為在 dry-run 卻改了 state」的事故面（design doc §1.2）。
        return {
            "ok": True,
            "added": 0,
            "dry_run": True,
            "reason": "dry_run_refill_suppressed",
            "deficit_at_check": _draft_pool_deficit(),
            "would_promote_starved": _releasable_now == 0,
        }
    if _releasable_now == 0:
        _promote_starved_article_tasks(DRAFT_POOL_FLOOR)
    deficit = _draft_pool_deficit()
    if deficit <= 0:
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        # 2026-07-04 ROOTFIX: reader_facing_only so a releasable-draft deficit is
        # healed with reader articles, not masked by the experiment fallback that
        # fires when the uncovered-K article pool is exhausted (experiment tasks
        # never become releasable drafts). When reader candidates ARE exhausted
        # this now honestly returns added=0 (surfacing the real content-supply
        # gap) instead of "succeeding" with useless experiment tasks.
        article = _run_article_refill(target=deficit, dry_run=False, reader_facing_only=True)
        added_ids = article.get("added_ids") or []
        if article.get("added") and added_ids:
            # refill_task_pool.refill() falls back to task_type="experiment"
            # (auto_research_fallback) when the uncovered-K article candidate
            # pool itself is exhausted (see _make_research_task in
            # refill_task_pool.py). Report the REAL task_type mix instead of
            # assuming daily_article, so dispatch_report_latest.json / dreaming
            # don't get a false "draft pool problem solved" signal when the
            # fallback actually queued research instead of an article.
            by_type: dict[str, int] = {}
            try:
                pending_now = load_pending_tasks()
                id_to_type = {
                    t.get("id"): str(t.get("task_type") or "unknown")
                    for t in pending_now
                    if isinstance(t, dict)
                }
                for tid in added_ids:
                    tt = id_to_type.get(tid, "unknown")
                    by_type[tt] = by_type.get(tt, 0) + 1
            except Exception:  # noqa: BLE001  # silent-ok: reporting-only, falls back below
                by_type = {"daily_article": article["added"]}
            return {
                "ok": True,
                "added": article["added"],
                "added_ids": added_ids,
                "by_type": by_type,
                "reason": "draft_pool_deficit_forced_refill",
                "deficit_at_check": deficit,
                "note": (
                    None
                    if by_type.get("daily_article", 0) == article["added"]
                    else "fallback_added_non_article_task; draft deficit NOT closed by this refill"
                ),
            }
        if article.get("ok") is False:
            return {
                "ok": False,
                "added": 0,
                "reason": article.get("reason") or article.get("error") or "article_refill_failed",
                "deficit_at_check": deficit,
            }
        return {"ok": True, "added": 0, "reason": "no_new_candidates", "deficit_at_check": deficit}
    except ArticleRefillTimeoutError as exc:
        return {"ok": False, "added": 0, "reason": f"timeout: {exc}", "deficit_at_check": deficit}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "added": 0, "reason": f"error: {exc}", "deficit_at_check": deficit}


def _maybe_refill(agentable_count: int, *, auto_refill: bool, dry_run: bool = False) -> dict | None:
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
    if dry_run:
        # WS-H4 dry-run 修真：refill 各 stage（diverse/event/article/research/
        # pool-dry breaker）全是 next_tasks.json writer，dry-run 一律不觸發。
        return {
            "ok": True,
            "added": 0,
            "dry_run": True,
            "reason": "dry_run_refill_suppressed",
            "would_refill_gap": max(0, REFILL_FLOOR - agentable_count),
        }
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


def _maybe_retire_covered_article_tasks(*, auto_refill: bool, dry_run: bool = False) -> dict | None:
    """Retire pending `*_article_<audience>` tasks already covered in feed.json.

    2026-07-01 root cause: an article task can be queued when the K is genuinely
    uncovered, then the covering article gets written minutes later by another
    path (Codex daemon / parallel refill). The stale task is never retracted, so
    the dispatcher keeps offering it → duplicate-article dispatch (K1590 →
    mile_4518e9d8, 7-min race; recurring class K1449/K1091).

    Running the sweep here (gated on auto_refill, same as _maybe_refill) makes
    every canonical dispatch self-heal instead of depending on prompt-level
    discipline to run the standalone script.
    """
    if not auto_refill:
        return None
    try:
        from mark_covered_article_tasks import sweep as _retire_covered
    except Exception as exc:  # noqa: BLE001
        _warn_dispatch(f"covered_article_dedup import failed: {exc}")
        return None
    try:
        # dry-run: same detection pass, apply=False so nothing is retired on disk.
        return _retire_covered(apply=not dry_run)
    except Exception as exc:  # noqa: BLE001
        _warn_dispatch(f"covered_article_dedup sweep failed: {exc}")
        return None


def _sweep_cleared_dreaming_tasks(*, dry_run: bool = False) -> list[dict]:
    """Close dreaming tasks whose condition dissolved, before they can be candidates.

    A dreaming finding is a snapshot of one night. Without this sweep a task whose
    condition cleared on its own just sits pending until the 24h starvation lockout
    force-feeds it to a fire, which burns a whole slot discovering it is a no-op —
    or worse, executes the stale imperative (2026-07-17: four `orphaned_experiment`
    tasks still demanding knowledge entries that backfill had already written).

    Same shape as `_sweep_cleared_ordinary_tasks` on the alert side. Best-effort:
    a failure here must never stop the dispatch report from being produced.
    """
    if dry_run:
        # WS-H4 dry-run 修真：同一套 revalidation 判定、零寫入。不取 flock、不過
        # canonical-write guard（沒有寫入就沒有要 guard 的東西）——讓 --dry-run
        # 從任何 checkout 都能當純診斷跑。
        try:
            from volpred.ops import dreaming_revalidate

            if not NEXT_TASKS.exists():
                return []
            tasks = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
            if not isinstance(tasks, list):
                return []
            return dreaming_revalidate.sweep_cleared(
                tasks,
                by="dispatcher-dry-run",
                now=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            _warn_dispatch(f"dreaming revalidation dry-run preview failed: {exc}")
            return []
    # Outside the best-effort try, same as the alert-side sweep: writing the
    # canonical queue from a foreign tree is not a transient hiccup to warn
    # about and continue past, and a guard swallowed by `except Exception`
    # reads like protection while only downgrading the violation to a log line.
    guard_canonical_write(NEXT_TASKS)
    try:
        import fcntl

        from volpred.ops import dreaming_revalidate
        from volpred.ops.next_tasks import write_tasks_to_handle

        if not NEXT_TASKS.exists():
            return []
        with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # same lock every queue writer takes
            try:
                tasks = json.load(fh)
                if not isinstance(tasks, list):
                    return []
                closed = dreaming_revalidate.sweep_cleared(
                    tasks,
                    by="dispatcher",
                    now=datetime.now(timezone.utc).isoformat(),
                )
                if closed:
                    write_tasks_to_handle(fh, tasks)
                return closed
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001
        _warn_dispatch(f"dreaming revalidation sweep failed: {exc}")
        return []


def build_report(*, auto_refill: bool = True, now: datetime | None = None,
                 dry_run: bool = False) -> dict:
    """Build the dispatch report.

    `now` exists so starvation verdicts can be pinned to a fixed instant. Without
    it the only clock is the wall clock, and any test that dates its fixtures
    relative to a literal `datetime(...)` ages a little more every real hour: a
    "fresh" P2 written on 2026-07-13 crossed its own 24h starvation line the next
    day and joined the starved set, so the lockout assertion started failing on a
    calendar boundary rather than on a code change (CI red, 2026-07-14).

    `dry_run=True` (WS-H4, 2026-07-20) makes this a read-only pass: the
    retire/sweep/refill/promote maintenance stages are suppressed or run in
    preview mode, so `storage/next_tasks.json` is byte-identical before and
    after. The report is still produced, flagged `dry_run: true`.
    """
    slots = count_active_slots()
    # Retire covered article tasks BEFORE categorizing so duplicates never reach
    # the agentable candidate list this run.
    _maybe_retire_covered_article_tasks(auto_refill=auto_refill, dry_run=dry_run)
    # Same reason, dreaming's snapshots: a dissolved condition must not reach the
    # candidate list, nor age into the starvation lockout that force-feeds it.
    cleared_dreaming = _sweep_cleared_dreaming_tasks(dry_run=dry_run)
    pending = load_pending_tasks()
    recent_type_counts = load_recent_task_type_counts()
    cats = categorize(pending, recent_type_counts=recent_type_counts)

    refill_result = _maybe_refill(len(cats["agentable"]), auto_refill=auto_refill,
                                  dry_run=dry_run)
    if refill_result and refill_result.get("added"):
        # Reload after refill so the report shows the fresh tasks
        pending = load_pending_tasks()
        cats = categorize(pending, recent_type_counts=recent_type_counts)

    # 2026-07-01 3-STRIKE fix: draft-pool-specific top-up runs independently of
    # the agentable-count-based `_maybe_refill` above — see `_maybe_refill_draft_pool`
    # docstring for why the two signals can diverge (task-type mix vs feed content).
    draft_refill_result = _maybe_refill_draft_pool(auto_refill=auto_refill, dry_run=dry_run)
    if draft_refill_result and draft_refill_result.get("added"):
        pending = load_pending_tasks()
        cats = categorize(pending, recent_type_counts=recent_type_counts)

    slot_budget = _slot_budget.budget()
    slot_cap = slot_budget["cap"]
    free_slots = max(0, slot_cap - slots["occupied"])

    # Mutating platform/governance work is admitted before worker spawn by the
    # supervisor.  Generic worker ownership and collision filtering must come
    # from the same seam the supervisor calls during preassignment.
    ownership = resolve_dispatch_ownership(
        pending,
        recent_type_counts=recent_type_counts,
        repo_root=ROOT,
        now=now,
    )
    cats = ownership["categories"]
    supervisor_only = ownership["supervisor_only"]
    worker_claimable = ownership["worker_claimable"]
    collision_blocked_tasks = ownership["collision_blocked_tasks"]
    collision_scan_error = ownership["collision_scan_error"]

    # 2026-07-21 dispatch-lanes R1: lane rank is the OUTERMOST ordering key.
    # `task_urgency.classify()` has been the single urgency owner since
    # 2026-07-18, but this dispatcher never consulted it — ordering was
    # priority + starvation + rotation only, so the fire a boss P1 woke via
    # `request_fire` still picked the longest-starved *machine* P1 (2026-07-21:
    # 33 pending P1, only 8 boss-sourced; the boss item queued behind 25
    # generator-self-assigned P1s). Urgent (boss-source P1) rides first,
    # oldest-first; time-critical types second, same FIFO; everything else
    # keeps the existing priority / starvation-lockout / rotation logic
    # UNCHANGED, operating only on the slots that remain after the lane head
    # is seated — so the starved tail-floor reserve can never evict urgent or
    # time-critical work.
    lane_by_id: dict = {}
    urgent_lane: list[dict] = []
    time_critical_lane: list[dict] = []
    scheduled_pool: list[dict] = []
    for task in worker_claimable:
        lane = _task_urgency.classify(task)
        lane_by_id[task.get("id")] = lane
        if lane == _task_urgency.LANE_URGENT:
            urgent_lane.append(task)
        elif lane == _task_urgency.LANE_TIME_CRITICAL:
            time_critical_lane.append(task)
        else:
            scheduled_pool.append(task)
    urgent_lane.sort(key=lambda t: str(t.get("created_at") or ""))
    time_critical_lane.sort(key=lambda t: str(t.get("created_at") or ""))
    lane_head = (urgent_lane + time_critical_lane)[:free_slots]
    scheduled_slots = max(0, free_slots - len(lane_head))

    # Starvation lockout — over the scheduled lane only. A starved urgent /
    # time-critical task does not need the lockout: its lane already puts it at
    # the head of the queue. When agentable scheduled work has aged past its
    # threshold, the scheduled portion of the menu collapses to starved tasks
    # plus explicit incident preemption.
    # ``dispatch_preempt`` is reserved for already-materialized P1 response work
    # (currently CI red repair): request_fire only wakes this generic dispatcher,
    # so omitting a fresh incident under lockout would consume the wake-up on an
    # unrelated old task and leave CI red. Ordinary fresh work remains excluded.
    starved = find_starved(scheduled_pool, now=now)
    starved_ids = {s["task"].get("id") for s in starved}
    # Main-thread tasks starve too (a boss-assigned P1 sat 27h — see `_coerce_priority`),
    # but the fix there cannot be a lockout: nothing in the agent lane can claim them.
    # Surface them so the fire has to look at them, and let the alert bridge nag.
    starved_main_thread = find_starved(cats["main_thread"], now=now)
    preemptive = [task for task in scheduled_pool if task.get("dispatch_preempt") is True]
    preempt_ids = {task.get("id") for task in preemptive}
    if starved:
        scheduled_candidates = (
            preemptive + [s["task"] for s in starved if s["task"].get("id") not in preempt_ids]
        )[:scheduled_slots]
        _before_ids = [t.get("id") for t in scheduled_candidates]
        scheduled_candidates = apply_starved_tail_floor(
            starved, scheduled_candidates, scheduled_slots, preempt_ids
        )
        tail_floor_ids = [
            t.get("id") for t in scheduled_candidates if t.get("id") not in _before_ids
        ]
    else:
        scheduled_candidates = (
            preemptive + [task for task in scheduled_pool if task.get("id") not in preempt_ids]
        )[:scheduled_slots]
        tail_floor_ids = []
    candidates_to_dispatch = (
        []
        if collision_scan_error is not None
        else lane_head + scheduled_candidates
    )

    pending_summary = {
        "agentable": len(cats["agentable"]),
        "worker_claimable": len(worker_claimable),
        "supervisor_only": len(supervisor_only),
        "main_thread": len(cats["main_thread"]),
        "blocked": len(cats["blocked"]),
        "label": (
            f"agentable {len(cats['agentable'])} "
            f"(worker {len(worker_claimable)} / supervisor {len(supervisor_only)}) / "
            f"main_thread {len(cats['main_thread'])} / "
            f"blocked {len(cats['blocked'])}"
        ),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "slot_cap": slot_cap,
        "slot_budget": slot_budget,
        "slot_state": slots,
        "free_slots": free_slots,
        "pending_total": len(pending),
        "pending_agentable": len(cats["agentable"]),
        "pending_worker_claimable": len(worker_claimable),
        "pending_supervisor_only": len(supervisor_only),
        "pending_main_thread": len(cats["main_thread"]),
        "pending_blocked": len(cats["blocked"]),
        "pending_summary": pending_summary,
        # R1 lane visibility: how much of the agentable queue outranks the
        # scheduled lane this fire, and which ids took lane-head seats.
        "lanes": {
            "urgent_pending": len(urgent_lane),
            "time_critical_pending": len(time_critical_lane),
            "lane_head_task_ids": [t.get("id") for t in lane_head],
        },
        "supervisor_preassignment": {
            "required_count": len(supervisor_only),
            "hourly_claimable": False,
            "directive": (
                "這些 mutating tasks 只能由 supervisor 在 worker spawn 前"
                "綁定 execution contract；generic hourly worker 不得 claim。"
            ),
            "tasks": [
                {
                    "id": task.get("id"),
                    "priority": task.get("priority"),
                    "task_type": task.get("task_type"),
                    "age_hours": (
                        lambda age: round(age, 1) if age is not None else None
                    )(task_age_hours(task, now=now)),
                    "title": (task.get("title") or "")[:120],
                }
                for task in supervisor_only[:10]
            ],
        },
        "starvation": {
            "locked": bool(starved),
            "incident_preempt_count": len(preemptive),
            "starved_count": len(starved),
            "collision_blocked_count": len(collision_blocked_tasks),
            "collision_blocked_tasks": collision_blocked_tasks,
            "collision_scan_error": collision_scan_error,
            # Which candidate (if any) is sitting in the reserved tail seat, so the
            # trade this fire made is auditable rather than inferred from ordering.
            "tail_floor_task_ids": tail_floor_ids,
            "thresholds_hours": {f"P{k}": v for k, v in STARVATION_HOURS.items()},
            "directive": (
                "⛔ STARVATION LOCKOUT — 以下任務已超過其優先序的容忍時數。"
                "本班 dispatch_candidates 先列 urgent / time-critical lane（如有），"
                "scheduled 部分只列 incident preempt 與這些餓死任務，"
                "diversity rotation 暫停："
                "先清光餓死的任務，才能回到一般輪替。"
                if starved
                else "無餓死任務；一般 diversity rotation 適用。"
            ),
            "starved_tasks": [
                {
                    "id": s["task"].get("id"),
                    "priority": s["task"].get("priority"),
                    "task_type": s["task"].get("task_type"),
                    "age_hours": s["age_hours"],
                    "threshold_hours": s["threshold_hours"],
                    "over_by_hours": s["over_by_hours"],
                    "title": (s["task"].get("title") or "")[:120],
                }
                for s in starved[:10]
            ],
            "incident_preempt_tasks": [
                {
                    "id": task.get("id"),
                    "priority": task.get("priority"),
                    "task_type": task.get("task_type"),
                    "title": (task.get("title") or "")[:120],
                }
                for task in preemptive[:10]
            ],
            "starved_main_thread_count": len(starved_main_thread),
            "starved_main_thread": [
                {
                    "id": s["task"].get("id"),
                    "priority": s["task"].get("priority"),
                    "task_type": s["task"].get("task_type"),
                    "age_hours": s["age_hours"],
                    "title": (s["task"].get("title") or "")[:120],
                }
                for s in starved_main_thread[:10]
            ],
        },
        # Auto-closing a task is a real decision; it must not be silent. Whoever
        # reads this report should see which snapshots dissolved and why.
        "dreaming_cleared": cleared_dreaming,
        "dispatch_candidates": [
            {
                "id": t.get("id"),
                "priority": t.get("priority"),
                "title": (t.get("title") or t.get("description") or "")[:120],
                # 拓撲建議（task.topology 欄位優先，否則 task_type 預設）— orchestrator
                # 依此選載具，僅明顯不合時 override 並在 work_log 記原因
                "topology": pick_topology(t.get("task_type"), t)["topology"],
                "lane": lane_by_id.get(t.get("id"), _task_urgency.LANE_SCHEDULED),
                "starved": t.get("id") in starved_ids,
                "dispatch_preempt": t.get("dispatch_preempt") is True,
                "age_hours": (lambda a: round(a, 1) if a is not None else None)(task_age_hours(t)),
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
        "draft_pool_refill": draft_refill_result,
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
    if report.get("dry_run"):
        print("[dispatch] DRY-RUN — read-only pass: retire/sweep/refill/promote "
              "suppressed, report not persisted")
    s = report["slot_state"]
    pending_summary = report.get("pending_summary", {})
    pending_label = pending_summary.get(
        "label",
        f"agentable {report['pending_agentable']} / "
        f"main_thread {report['pending_main_thread']} / "
        f"blocked {report.get('pending_blocked', 0)}",
    )
    budget = report.get("slot_budget") or {}
    print(
        f"[dispatch] slots: occupied={s['occupied']}/{report['slot_cap']} "
        f"(worktrees={len(s['worktrees'])}, active_agents={len(s['active_agents'])}) "
        f"free={report['free_slots']}"
        + (f" | cap: {budget['reason']}" if budget.get("reason") else "")
    )
    # Released artifact custody must not become invisible. It no longer owns a
    # slot, but the reason tells operators whether it needs salvage or lease GC.
    for st in s.get("stale") or []:
        idle = "unknown" if st.get("idle_hours") is None else f"{st['idle_hours']}h"
        print(
            f"  ⚠️ slot released / artifact retained: {st['name']} — "
            f"reason={st.get('release_reason', 'unknown')} idle={idle}；"
            "不再占 capacity，成果仍走正式 merge/salvage lifecycle"
        )
    for c in report.get("dreaming_cleared") or []:
        print(
            f"  ✅ dreaming no-op closed: {c['id']} [{c['pattern_type']}] — {c['detail']}"
        )
    print(
        f"[dispatch] pending: total={report['pending_total']} "
        f"{pending_label} "
        f"blocked={report.get('pending_blocked', 0)}"
    )

    supervisor = report.get("supervisor_preassignment") or {}
    if supervisor.get("required_count"):
        print(
            "[dispatch] SUPERVISOR-ONLY "
            f"({supervisor['required_count']}): "
            f"{supervisor['directive']}"
        )
        for task in supervisor.get("tasks") or []:
            age = (
                "unknown"
                if task.get("age_hours") is None
                else f"{task['age_hours']}h"
            )
            print(
                f"  ↳ P{task['priority']} {task['id']} "
                f"[{task['task_type']}] :: aged {age}"
            )

    starvation = report.get("starvation") or {}
    if starvation.get("collision_scan_error"):
        print(
            "[dispatch] ⛔ task/worktree collision scan failed closed: "
            f"{starvation['collision_scan_error']}"
        )
    for blocked in starvation.get("collision_blocked_tasks", []):
        print(
            "  ↳ collision-blocked "
            f"P{blocked['priority']} {blocked['id']} :: "
            f"{blocked['worktree']} ({blocked['branch']} "
            f"{blocked['commit'][:12]})"
        )
    if starvation.get("locked"):
        print(f"[dispatch] {starvation['directive']}")
        for s in starvation.get("starved_tasks", []):
            print(
                f"  ! P{s['priority']} {s['id']} :: aged {s['age_hours']}h "
                f"(threshold {s['threshold_hours']}h, over by {s['over_by_hours']}h)"
            )

    if report["dispatch_candidates"]:
        label = "STARVED — 本班只能從這裡挑" if starvation.get("locked") else "candidates to dispatch"
        print(f"[dispatch] {label} ({len(report['dispatch_candidates'])}):")
        tail_floor = set(starvation.get("tail_floor_task_ids") or [])
        for c in report["dispatch_candidates"]:
            seat = " ⟵ 保底席（最低 starved 優先序，本班必挑）" if c["id"] in tail_floor else ""
            print(f"  - P{c['priority']} [{c['topology']}] {c['id']} :: {c['title']}{seat}")
    else:
        print(
            "[dispatch] NO agent dispatch candidates "
            "(slot full or no worker-claimable candidates)"
        )

    if report["main_thread_queue_top5"]:
        print("[dispatch] main-thread queue (top 5):")
        for c in report["main_thread_queue_top5"]:
            print(f"  - P{c['priority']} {c['id']} :: {c['title']}")

    if starvation.get("starved_main_thread_count"):
        print(
            f"[dispatch] ⚠️ main-thread 餓死 {starvation['starved_main_thread_count']} 筆"
            "（agent lane 無法認領 — 主線程本班要處理或改 lane）："
        )
        for s in starvation.get("starved_main_thread", []):
            print(f"  ! P{s['priority']} {s['id']} :: aged {s['age_hours']}h :: {s['title']}")

    refill = report.get("refill") or {}
    if refill.get("added"):
        print(f"[dispatch] auto-refill: +{refill['added']} tasks {refill.get('added_ids')}")
    elif refill.get("ok") is False:
        print(f"[dispatch] auto-refill error: {refill.get('error') or refill.get('reason')}")

    draft_refill = report.get("draft_pool_refill") or {}
    if draft_refill.get("added"):
        print(f"[dispatch] draft-pool refill: +{draft_refill['added']} tasks "
              f"by_type={draft_refill.get('by_type')} (deficit_at_check={draft_refill.get('deficit_at_check')})")
        if draft_refill.get("note"):
            print(f"  NOTE: {draft_refill['note']}")
    elif draft_refill.get("ok") is False:
        print(f"[dispatch] draft-pool refill error: {draft_refill.get('reason')}")

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
    parser.add_argument("--dry-run", action="store_true",
                        help="read-only 巡檢：不 retire/sweep/refill/promote、不寫任何檔案")
    parser.add_argument("--report", action="store_true", help="寫 report 到 dispatch_report_latest.json")
    parser.add_argument("--execute", action="store_true", help="reserved (尚未實作 actual spawn)")
    parser.add_argument("--no-refill", action="store_true",
                        help="skip auto-refill even if agentable < floor (debug only)")
    args = parser.parse_args()

    report = build_report(auto_refill=not args.no_refill, dry_run=args.dry_run)
    print_report(report)

    if args.report:
        if args.dry_run:
            # dry-run must not persist anything — emit the payload to stdout instead.
            print(json.dumps(report, indent=2, ensure_ascii=False))
            print("[dispatch] DRY-RUN: report NOT written "
                  f"(would have gone to {REPORT_PATH})")
        else:
            guard_canonical_write(REPORT_PATH)
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(f"[dispatch] report written: {REPORT_PATH}")
            try:
                from volpred.ops.control_gate_lifecycle import (
                    record_dispatch_gate_decisions,
                )

                gate_receipt = record_dispatch_gate_decisions(
                    report,
                    storage_dir=str(ROOT / "storage"),
                )
                if gate_receipt["recorded"]:
                    print(
                        "[dispatch] control-gate evidence: "
                        f"{gate_receipt['recorded']} "
                        f"{gate_receipt['gate_ids']}"
                    )
            except Exception as exc:  # noqa: BLE001 - audit loss must not veto dispatch
                _warn_dispatch(f"control-gate evidence write failed: {exc}")

    if args.execute:
        print("[dispatch] --execute not yet implemented; main-thread should pick up candidates and dispatch agents (Task tool / claude general-purpose / codex-rescue) per .claude/rules/agent-delegation.md")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
