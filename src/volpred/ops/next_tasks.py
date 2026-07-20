"""Helpers for the legacy ``storage/next_tasks.json`` pending queue.

Single enforcement owner for two invariants on the canonical queue:

1. **Status controlled vocabulary** (``TASK_STATUSES`` / ``validate_task_status``).
   Before this module owned it, 15 writers each ``json.dump``-ed the queue with no
   shared status check, so 27 out-of-vocab rows accumulated from ad-hoc jq/Edit
   hand-writes and one-off scripts: ``completed`` (x11),
   ``superseded_audience_null_fix`` (x5), ``partially_completed`` (x2), plus a long
   one-off tail (``completed_local`` / ``completed_null`` / ``partial`` /
   ``partial_success`` / ``dropped_false_positive`` /
   ``fail_no_data_data_source_blocker`` /
   ``partially_resolved_K1180_done_awaiting_K1179`` /
   ``phase1_failed_codex_review_superseded_by_v2`` /
   ``setup_done_superseded_by_v2``, one each). Those 27 legacy rows are frozen as
   the baseline (永遠修流程，不修資料); the regression stop lives in
   ``scripts/validate_next_tasks_status.py``. New writes route through
   ``write_tasks_to_handle`` / ``write_tasks_locked`` here.

2. **Corruption-safe writes** (serialize-first-then-truncate). ``content.py`` and
   ``questions.py`` previously did ``fh.seek(0); fh.truncate(); json.dump(...)`` --
   truncate BEFORE serialize. A mid-serialize failure (e.g. a lone surrogate from
   surrogateescape argv raising ``UnicodeEncodeError``) then left the queue
   truncated to invalid JSON, and PHASE-Z auto-committed the wreck to main
   (incident 2026-07-05, docs/error_log.md:329). ``write_tasks_to_handle`` builds
   the full payload FIRST and only truncates once serialization has succeeded --
   the same hardening ``scripts/task_pool_claim.py`` grew inline in 2026-07-05,
   now shared here so every writer inherits it.

3. **Blocked rows always have an exit** (``enforce_blocked_until`` /
   ``_audit_blocked_until``). ``scripts/unblock_expired_blocked_tasks.py`` only
   re-pends a block whose ``blocked_until`` has PASSED, so a row that reached
   ``status=blocked`` with no ``blocked_until`` at all was invisible to the
   sweeper and parked forever -- 19 such rows by 2026-07-18. Strict writers call
   ``enforce_blocked_until`` (auto-fill the default window, or raise); the
   whole-file path only audits against the frozen legacy baseline.
"""
from __future__ import annotations

import fcntl
import json
import re
from collections import Counter
from pathlib import Path
from typing import IO, Any

from volpred.canonical_write import guard_canonical_write

from .diagnostics import warn


class InvalidTaskPriority(ValueError):
    """Raised when a task priority cannot be represented as a positive int."""


_DIGIT_PRIORITY_RE = re.compile(r"^\d+$")
_P_LABEL_PRIORITY_RE = re.compile(r"^[Pp]+(\d+)$")


def normalize_priority(value: Any, *, default: int | None = None) -> int:
    """Return an integer priority from legacy queue values.

    Accepted forms:
    - ``1`` / ``2`` / ... (int)
    - ``"1"`` / ``"2"`` / ... (legacy string int)
    - ``"P1"`` / ``"P2"`` / ... (legacy label)

    A few old rows accidentally contain repeated ``P`` prefixes because display
    code prepended ``P`` to an already-labelled value. Treat those as legacy
    labels too, so the one-time queue sweep can remove all string priorities.
    """
    if value is None:
        if default is not None:
            return _validate_priority(default)
        raise InvalidTaskPriority("priority is missing")

    if isinstance(value, bool):
        raise InvalidTaskPriority(f"priority must be int-like, got bool {value!r}")

    if isinstance(value, int):
        return _validate_priority(value)

    if isinstance(value, float) and value.is_integer():
        return _validate_priority(int(value))

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            if default is not None:
                return _validate_priority(default)
            raise InvalidTaskPriority("priority is blank")
        if _DIGIT_PRIORITY_RE.fullmatch(raw):
            return _validate_priority(int(raw))
        match = _P_LABEL_PRIORITY_RE.fullmatch(raw)
        if match:
            return _validate_priority(int(match.group(1)))

    raise InvalidTaskPriority(f"priority must be int-like, got {value!r}")


def _validate_priority(priority: int) -> int:
    if priority < 1:
        raise InvalidTaskPriority(f"priority must be >= 1, got {priority!r}")
    return priority


def normalize_task_priority(
    task: dict[str, Any],
    *,
    default_priority: int = 3,
    mutate: bool = True,
) -> bool:
    """Normalize one task's ``priority`` field.

    Returns ``True`` when the stored representation would change. Non-dict
    callers should filter before calling this helper; the function is strict on
    malformed priority values so writers fail before corrupting the queue.
    """
    old = task.get("priority")
    new = normalize_priority(old, default=default_priority)
    changed = old != new or not isinstance(old, int)
    if mutate and changed:
        task["priority"] = new
    return changed


def normalize_task_priorities(
    tasks: list[dict[str, Any]],
    *,
    default_priority: int = 3,
    mutate: bool = True,
) -> int:
    """Normalize every dict entry in a next_tasks payload; return change count."""
    changed = 0
    for task in tasks:
        if isinstance(task, dict) and normalize_task_priority(
            task,
            default_priority=default_priority,
            mutate=mutate,
        ):
            changed += 1
    return changed


def priority_sort_key(value: Any, *, default: int = 999) -> int:
    """Priority key for read paths; invalid values sort last."""
    try:
        return normalize_priority(value, default=default)
    except InvalidTaskPriority:
        return default


class InvalidTaskStatus(ValueError):
    """Raised when a task status is not in the controlled vocabulary."""


# Canonical status vocabulary. Mirrors the shape of ``blocked_reasons.py``:
# adding a status here is the only sanctioned way to extend it. Any status not
# listed is an out-of-vocab pollutant counted by the CI baseline gate.
TASK_STATUSES: frozenset[str] = frozenset(
    {
        "pending",                              # queued, agent-dispatchable
        "pending_main_thread",                  # queued, main-thread only
        "claimed",                              # claimed by a session, not started
        "in_progress",                          # started
        "succeeded",                            # done, real result
        "succeeded_null_result",                # done; null/negative result (terminal per sync_next_tasks_status.py:160)
        "failed",                               # genuine failure
        "blocked",                              # hard/soft blocked (paired with blocked_reason)
        "blocked_on_user",                      # awaiting an owner decision (distinct from blocked)
        "superseded",                           # replaced by another task
        "closed_no_action",                     # closed, nothing to do
        "decision_made_awaiting_body_rewrite",  # paper narrative state (CLAUDE.md)
        "cancelled",                            # explicitly cancelled
        "expired",                              # aged out past its window
    }
)

# Frozen count of pre-2026-07 rows whose status predates the vocabulary above.
# Per "永遠修流程，不修資料" these rows are never rewritten; the write path stays
# quiet at or below this line and CI fails above it.
# MIRRORED in scripts/validate_next_tasks_status.py::DEFAULT_BASELINE, which
# cannot import this module (it runs on a deps-free CI runner).
# tests/test_task_status_vocab.py asserts the two stay equal.
LEGACY_OUT_OF_VOCAB_BASELINE = 27


# Canonical dispatch-lane vocabulary — who is allowed to claim a task.
# Same shape as TASK_STATUSES above: this is the ONLY sanctioned place to add a
# lane. Before 2026-07-20 the vocabulary was copy-pasted across three owners
# (continue_task_dispatch.py listed 4 main-thread spellings, task_pool_claim.py's
# claim gate hard-coded only "main_thread", task_urgency.py knew nothing about
# lanes at all). That divergence is what let `dispatch_lane="manual"` be filtered
# out of PHASE B candidates yet still be claimable by a burst fire.
AGENT_DISPATCH_LANES: frozenset[str] = frozenset(
    {"agent", "agentable", "auto", "auto_dispatch", "headless", "worker"}
)
MAIN_THREAD_DISPATCH_LANES: frozenset[str] = frozenset(
    {"main", "main_thread", "manual", "interactive"}
)
BLOCKED_DISPATCH_LANES: frozenset[str] = frozenset({"blocked", "blocked_on_user", "hold"})


def normalize_dispatch_lane(task: dict) -> str:
    """Return the task's normalized schema-level dispatch lane ("" if unset).

    Accepts both ``dispatch_lane`` and the legacy camelCase ``dispatchLane``,
    and folds ``main-thread`` → ``main_thread`` so hyphen/underscore spellings
    are the same lane.
    """
    if not isinstance(task, dict):
        return ""
    raw = task.get("dispatch_lane") or task.get("dispatchLane") or ""
    return str(raw).strip().lower().replace("-", "_")


def is_agent_claimable_lane(task: dict) -> bool:
    """Return True iff a headless/hourly session may claim this task.

    An unset lane stays claimable — the vast majority of the queue predates the
    field, and defaulting those to "reserved" would freeze the whole pool.
    """
    lane = normalize_dispatch_lane(task)
    if not lane:
        return True
    return lane not in MAIN_THREAD_DISPATCH_LANES and lane not in BLOCKED_DISPATCH_LANES


def is_valid_status(status: str | None) -> bool:
    """Return True iff ``status`` is a registered task status."""
    if not status:
        return False
    return status.strip().lower() in TASK_STATUSES


def validate_task_status(status: str | None) -> str:
    """Return the normalized status, or raise ``InvalidTaskStatus``.

    Strict raise for callers that set a NEW status (writers building a task,
    scripts/migrate_blocked_lane_terminal.py). The whole-file write path
    (``write_tasks_to_handle``) deliberately does NOT raise on the 27 frozen
    legacy rows -- see module docstring -- it surfaces them observably instead.
    """
    if not is_valid_status(status):
        raise InvalidTaskStatus(
            f"task status {status!r} not in TASK_STATUSES; add it to "
            "src/volpred/ops/next_tasks.py if it is a real new state"
        )
    return str(status).strip().lower()


class InvalidBlockedUntil(ValueError):
    """Raised when a ``status=blocked`` row cannot be given a valid ``blocked_until``."""


# Default auto-recheck window for a block with no explicit expiry. Semantics are
# owned here and re-exported to scripts/mark_task_blocked.py (which defined the
# 14-day window first) so one number cannot drift into two.
DEFAULT_BLOCKED_UNTIL_DAYS = 14

# Allowed count of status=blocked rows carrying NO blocked_until. Zero, and it
# must stay zero: such a row has no exit at all, because
# scripts/unblock_expired_blocked_tasks.py only ever re-pends an EXPIRED block.
#
# History: 19 such rows had accumulated by 2026-07-18 (30 blocked rows, 19 with
# no expiry), the oldest parked >45 days -- the hole boss Telegram msg 937 P1
# ordered closed. All 19 were adjudicated that day (see the sweeper's escalate
# pass), so there is no legacy population left to grandfather and the baseline
# drops to 0. Raising this number again would re-open the hole; adjudicate the
# rows instead. Per 永遠修流程，不修資料 a writer never silently rewrites an
# existing blocked row -- the strict path only fills an expiry on rows it owns.
# MIRRORED in tests/test_task_status_vocab.py::BLOCKED_NO_UNTIL_BASELINE.
LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE = 0


def default_blocked_until(now: "datetime | None" = None) -> str:
    """ISO timestamp ``DEFAULT_BLOCKED_UNTIL_DAYS`` from now (seconds precision)."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    base = now or _dt.now(_tz.utc)
    return (base + _td(days=DEFAULT_BLOCKED_UNTIL_DAYS)).isoformat(timespec="seconds")


def enforce_blocked_until(task: dict[str, Any], *, now: "datetime | None" = None) -> bool:
    """Strict path: a row a caller just set to ``blocked`` MUST carry an expiry.

    Mirrors ``validate_task_status``'s split of strictness. Use this wherever a
    writer sets ``status="blocked"`` on a row it owns; returns ``True`` when a
    default expiry was filled in.

    Why this is an invariant and not a lint: the dispatcher only ever re-pends a
    block whose ``blocked_until`` has passed, so a blocked row without one has no
    exit at all -- it parks forever with nobody notified (19 rows accumulated
    before 2026-07-18). Auto-filling the default window gives every new block an
    exit; a present-but-unusable value cannot be second-guessed by a writer, so
    it raises instead.

    NOT called from the whole-file write path -- see ``_audit_blocked_until``.
    """
    if str(task.get("status") or "").strip().lower() != "blocked":
        return False
    until = task.get("blocked_until")
    if until is None or (isinstance(until, str) and not until.strip()):
        task["blocked_until"] = default_blocked_until(now)
        return True
    if not isinstance(until, str):
        raise InvalidBlockedUntil(
            f"task {task.get('id')!r} blocked_until must be an ISO string, got "
            f"{type(until).__name__} {until!r}"
        )
    return False


def _audit_blocked_until(tasks: list[Any]) -> int:
    """Surface ``blocked`` rows with no ``blocked_until`` (observable, non-fatal).

    Same non-fatal contract as ``_audit_task_statuses`` and for the same reason:
    the canonical queue still carries the frozen legacy rows, and raising on a
    whole-file rewrite would brick every task materializer. Warns only ABOVE the
    baseline, so a frozen known fact never becomes hot-path noise; the mechanical
    stop is the baseline gate in tests/test_task_status_vocab.py.

    Deliberately does NOT auto-fill: rewriting legacy rows here would erase the
    very evidence the human adjudication queue works from (永遠修流程，不修資料).
    """
    bad: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status") or "").strip().lower() != "blocked":
            continue
        until = task.get("blocked_until")
        if until is None or (isinstance(until, str) and not until.strip()):
            bad.append(str(task.get("id") or "<no-id>"))
    if len(bad) > LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE:
        warn(
            "next_tasks_blocked_until",
            "blocked task(s) with no blocked_until ABOVE frozen baseline -- "
            "these can never be re-pended and will park forever",
            count=len(bad),
            baseline=LEGACY_BLOCKED_WITHOUT_UNTIL_BASELINE,
            examples=bad[:5],
        )
    return len(bad)


def _audit_task_statuses(tasks: list[Any]) -> int:
    """Surface out-of-vocab statuses (observable, non-fatal); return the count.

    Non-fatal by design: the canonical queue still carries the legacy rows we are
    forbidden to rewrite, and a raise here would brick every task materializer.
    New pollution is hard-stopped by scripts/validate_next_tasks_status.py's
    baseline gate.

    Warns only ABOVE the baseline. Warning on every write would put a
    known-and-frozen fact on the hot dispatch path (claim/complete/materialize
    all pass through here), training the reader to ignore the tag -- so the one
    time it means "someone just added new pollution" it reads like the usual noise.
    """
    bad: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        if status is not None and not is_valid_status(status):
            bad.append(str(status))
    if len(bad) > LEGACY_OUT_OF_VOCAB_BASELINE:
        warn(
            "next_tasks_status",
            "out-of-vocab task status(es) ABOVE frozen baseline -- new pollution",
            count=len(bad),
            baseline=LEGACY_OUT_OF_VOCAB_BASELINE,
            distinct=dict(Counter(bad)),
        )
    return len(bad)


def _normalize_priorities_tolerant(tasks: list[Any]) -> int:
    """Normalize priorities across a whole-file payload without bricking it.

    The strict `normalize_task_priorities` is correct for a row a caller just
    built -- fail before the bad value reaches disk. It is wrong for a whole-file
    rewrite: one malformed legacy priority would make EVERY materializer write
    raise (content, questions, task_pool_claim claim/complete), which is exactly
    the bricking `_audit_task_statuses` is written to avoid. Leave the bad row's
    priority untouched, keep it visible, and let the row through.
    """
    changed = 0
    skipped: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        try:
            if normalize_task_priority(task):
                changed += 1
        except InvalidTaskPriority as exc:
            skipped.append(f"{task.get('id', '<no-id>')}: {exc}")
    if skipped:
        warn(
            "next_tasks_write",
            "left malformed priority row(s) untouched rather than failing the write",
            count=len(skipped),
            examples=skipped[:3],
        )
    return changed


# ---------------------------------------------------------------------------
# Terminal-task tombstone compaction (2026-07-14 refactor_plan_token_ops_waste
# WS2a). The queue file carried 2,296 succeeded full records (4.5MB) that every
# dispatcher/claim/refill pass re-parsed. Readers dedup by task id across ANY
# status (refill_task_pool, build_publication_candidates, ...), so records must
# NOT leave the file -- instead old terminal records collapse to a tombstone
# (id/status/type/title + timestamps) and the full record is appended to
# storage/next_tasks_archive/YYYY-MM.jsonl. Id-based dedup semantics are
# preserved for every reader with zero reader changes.
# ---------------------------------------------------------------------------

TERMINAL_COMPACTABLE_STATUSES: frozenset[str] = frozenset(
    {
        "succeeded",
        "succeeded_null_result",
        "failed",
        "superseded",
        "closed_no_action",
        "cancelled",
        "expired",
    }
)

_TOMBSTONE_KEEP_FIELDS = (
    "id",
    "status",
    "task_type",
    "title",
    "priority",
    "source",
    "created_at",
    "completed_at",
)


def _task_terminal_ts(task: dict) -> str | None:
    """Best-effort terminal timestamp for age gating; None = not compactable."""
    for key in ("completed_at", "finished_at", "closed_at", "updated_at"):
        v = task.get(key)
        if v:
            return str(v)
    hist = task.get("status_history")
    if isinstance(hist, list) and hist:
        last = hist[-1]
        if isinstance(last, dict) and last.get("at"):
            return str(last["at"])
    return None


def compact_terminal_tasks(
    tasks: list[Any],
    *,
    age_days: int = 30,
    now: "datetime | None" = None,
) -> tuple[int, list[dict]]:
    """Collapse old terminal records to tombstones; return (n, full_records).

    Mutates ``tasks`` in place. Conservative skips: non-dict rows, statuses
    outside ``TERMINAL_COMPACTABLE_STATUSES`` (the 27 frozen legacy rows are
    out-of-vocab and therefore never touched -- 永遠修流程，不修資料), rows
    already tombstoned, unresolved internal-alert attempts (their state is the
    escalation receipt), rows younger than ``age_days``, and rows with no
    parseable terminal timestamp. Caller must persist the returned full
    records to the archive BEFORE writing the compacted queue.
    """
    from datetime import datetime, timedelta, timezone as _tz

    now_dt = now or datetime.now(_tz.utc)
    cutoff = now_dt - timedelta(days=age_days)
    archived: list[dict] = []
    for i, task in enumerate(tasks):
        if not isinstance(task, dict) or task.get("tombstone"):
            continue
        if task.get("internal_alert_watermark") is True:
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in TERMINAL_COMPACTABLE_STATUSES:
            continue
        internal_state = task.get("internal_alert_state")
        if (
            task.get("internal_remediable") is True
            and isinstance(internal_state, dict)
            and not internal_state.get("resolved_at")
        ):
            # A terminal attempt is counted by the next signal.  Compacting its
            # episode metadata first would silently reset the two-attempt
            # escalation threshold after a detector outage.
            continue
        ts_raw = _task_terminal_ts(task)
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
        except ValueError:
            warn(
                "next_tasks_compact",
                "unparseable terminal timestamp; leaving row uncompacted",
                task_id=str(task.get("id") or ""),
                ts=ts_raw[:40],
            )
            continue
        if ts > cutoff:
            continue
        archived.append(dict(task))
        stone = {k: task[k] for k in _TOMBSTONE_KEEP_FIELDS if k in task}
        stone["tombstone"] = True
        stone.setdefault("completed_at", ts_raw)
        stone["archived_at"] = now_dt.isoformat()
        tasks[i] = stone
    return len(archived), archived


def write_tasks_to_handle(fh: IO[str], tasks: list[Any]) -> None:
    """Serialize ``tasks`` to an already-open, ``LOCK_EX``-held handle.

    Serialize-FIRST-then-truncate: build the full UTF-8 payload before touching
    the file, so a serialization failure cannot leave the canonical queue
    truncated to invalid JSON (incident 2026-07-05). Lone surrogates arriving via
    surrogateescape argv (e.g. a shell-mangled ``--result`` char) are scrubbed
    with an observable warning rather than raising mid-write.
    """
    # A handle opened by a higher-level read/modify/write caller is still a
    # mutation primitive. Guard it here so every caller shares the same check.
    handle_name = getattr(fh, "name", None)
    if isinstance(handle_name, (str, Path)):
        guard_canonical_write(handle_name)

    _normalize_priorities_tolerant(tasks)
    _audit_task_statuses(tasks)
    _audit_blocked_until(tasks)
    payload = json.dumps(tasks, indent=2, ensure_ascii=False)
    try:
        payload.encode("utf-8")
    except UnicodeEncodeError as exc:
        warn("next_tasks_write", "scrubbed non-encodable char(s) before write", err=str(exc))
        payload = payload.encode("utf-8", "replace").decode("utf-8")
    fh.seek(0)
    fh.truncate()
    fh.write(payload)
    fh.write("\n")


def write_tasks_locked(path: str | Path, tasks: list[Any]) -> None:
    """Atomically replace the task file at ``path`` with ``tasks`` under LOCK_EX.

    One-shot writer for callers that already hold the full list (e.g.
    scripts/migrate_blocked_lane_terminal.py). Callers doing a read-modify-write
    that must stay atomic against concurrent writers should instead hold the lock
    across load+mutate and call ``write_tasks_to_handle`` on that same handle --
    opening a second descriptor here would deadlock on the same-process flock.
    """
    p = Path(path)
    guard_canonical_write(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("[]\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# --- Single-gateway append (2026-07-16 refactor) -----------------------------
# docs/refactor_plan_single_gateway_task_system.md: `volpred ops assign` used to
# write storage/ops/tasks/*.json — a queue no dispatcher consumes. This is the
# one canonical append path it now routes through.

_ASSIGN_FAMILY_TO_TASK_TYPE = {
    "ops": "platform_ops",
    "research": "experiment",
    "article": "daily_article",
    "paper": "paper_review",
    "content": "daily_article",
    "strategy": "strategy_lifecycle",
}


def _legacy_priority_to_p(legacy: int) -> int:
    """Map local-control-plane large-number priority (30/80/100…) to P1-P4."""
    if legacy <= 10:
        return 1
    if legacy <= 50:
        return 2
    if legacy <= 100:
        return 3
    return 4


#: 只有寫進**正牌**佇列才准叫醒 supervisor（測試/暫存佇列不得觸發真實派工）。
CANONICAL_NEXT_TASKS = Path(__file__).resolve().parents[3] / "storage" / "next_tasks.json"


def _request_urgent_fire(record: dict[str, Any], path: Path) -> bool:
    """急件入池 → 立刻要求 supervisor out-of-band 派工，不等下一班 hourly cron。

    2026-07-18 boss Telegram msg 981「急件和一般排程應該要分開。急件就不進入排班
    直接派工」。這條路徑本來只有 email (`gmail_inbox_poll.py:754`) 和 CI red
    (`check_alerts.py:1168`) 接上；Telegram 進來的 P1 只 append 就結束，等下一班
    hourly（實例：assign_998ad2be / assign_33a9151f 建單 16:49/17:42，18:06 仍
    pending）。這裡是 **single gateway**（`volpred ops assign` 唯一的 append 路
    徑），所以接在這裡就同時涵蓋 telegram / user / owner / boss 所有人為 ingress。

    範圍界線（2026-07-19 查證，別再「補接線」）：`scripts/telegram_poll.py` 自己組
    record 直寫佇列、不經本函式，看起來像漏網，其實不是 —— 它建的是
    `telegram_reply`，屬 `DEDICATED_OWNER_TASK_TYPES`，`is_urgent()` 一律回 False，
    因為那類有專屬 owner（`_spawn_responder()` 即時處理，失敗則由 poll 迴圈在
    `RETRY_AGE_THRESHOLD_SEC`=120s 內重派），本來就不該叫醒 hourly dispatcher —— 叫
    醒了它也只會 skip 掉 telegram_reply。硬接一行 `request_urgent_fire` 是 no-op。

    `request_fire()` 只是在 supervisor state 寫一個 flag（同一把 fcntl 鎖），由
    scheduler 下一個 ≤60s tick 消費並走正常 `reserve_fire()` slot —— 不 spawn 任何
    平行 agent，slot 滿就留著等，不是 double dispatch。

    失敗不 raise：任務已經入池，最壞情況就是退回原本的 hourly 行為；但必須留
    warn（no-silent-fallback）。回傳是否真的送出 fire request。
    """
    from volpred.ops.task_urgency import is_urgent

    if not is_urgent(record):
        return False
    try:
        if path.resolve() != CANONICAL_NEXT_TASKS.resolve():
            return False  # scratch / test queue：不得叫醒真的 supervisor
    except OSError:  # silent-ok: 同 585 —— 無法確認是 canonical queue 就不叫醒 supervisor，非失敗兜底
        return False
    try:
        import sys

        root = str(CANONICAL_NEXT_TASKS.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.dispatch_supervisor import state as dispatch_state

        dispatch_state.request_fire(f"{record.get('source')}:{record['id']}")
        return True
    except Exception as exc:  # noqa: BLE001 — 任務已入池，hourly 兜底
        from volpred.ops.diagnostics import warn

        warn(
            "urgent_fire_request",
            "request_fire failed; urgent task falls back to hourly cadence",
            task_id=str(record.get("id")),
            source=str(record.get("source")),
            err=f"{type(exc).__name__}: {exc}",
        )
        return False


def append_next_task(
    *,
    title: str,
    description: str,
    source: str = "user",
    task_family: str = "ops",
    legacy_priority: int = 100,
    payload: dict[str, Any] | None = None,
    parent_task_id: str | None = None,
    created_by: str | None = None,
    path: str | Path = "storage/next_tasks.json",
) -> dict[str, Any]:
    """Append one pending task to the canonical queue under LOCK_EX.

    Returns the created record. Raises ValueError on duplicate id (uuid4-based,
    practically unreachable) so callers never silently double-queue.
    """
    import uuid
    from datetime import datetime, timezone

    task_type = _ASSIGN_FAMILY_TO_TASK_TYPE.get(task_family, "platform_ops")
    record: dict[str, Any] = {
        "id": f"assign_{uuid.uuid4().hex[:8]}",
        "title": title,
        "description": description,
        "task_type": task_type,
        "priority": _legacy_priority_to_p(int(legacy_priority)),
        "status": "pending",
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload:
        record["payload"] = payload
    if parent_task_id:
        record["parent_task_id"] = parent_task_id
    if created_by:
        record["created_by"] = created_by

    p = Path(path)
    guard_canonical_write(p)
    if not p.exists():
        p.write_text("[]\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            raw = fh.read()
            tasks = json.loads(raw) if raw.strip() else []
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json root is not a list")
            existing = {t.get("id") for t in tasks if isinstance(t, dict)}
            if record["id"] in existing:
                raise ValueError(f"duplicate task id {record['id']}")
            tasks.append(record)
            write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    # 急件不進排班：入池成功後（鎖已釋放）立刻請 supervisor 派工。
    # `fire_requested` 是 **return-only receipt**（給 CLI 印 / 給測試斷言），
    # 刻意不寫回佇列 —— 它是這次 append 的動作結果，不是 task 的狀態欄位。
    record["fire_requested"] = _request_urgent_fire(record, p)
    return record
