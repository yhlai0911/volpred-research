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
   ``setup_done_superseded_by_v2``, one each). Those 27 legacy rows were frozen
   as the baseline (永遠修流程，不修資料); the regression stop lives in
   ``scripts/validate_next_tasks_status.py``. New writes route through
   ``write_tasks_to_handle`` / ``write_tasks_locked`` here.
   2026-07-20 WS-A3 (refactor_plan_ops_master): with every writer on the
   canonical helper, the frozen rows are mapped back to the controlled vocab by
   the one-time ``scripts/migrate_status_vocab.py`` (original value preserved
   per-row in ``status_original``); after apply the baseline drops to 0.
   The same migration + ``_audit_blocked_reasons`` extend the vocab gate to the
   ``blocked_reason`` field (canonical vocab: ``blocked_reasons.py``).

2. **Corruption-safe writes** (serialize-first-then-truncate). ``content.py`` and
   ``questions.py`` previously did ``fh.seek(0); fh.truncate(); json.dump(...)`` --
   truncate BEFORE serialize. A mid-serialize failure (e.g. a lone surrogate from
   surrogateescape argv raising ``UnicodeEncodeError``) then left the queue
   truncated to invalid JSON, and PHASE-Z auto-committed the wreck to main
   (incident 2026-07-05, docs/error_log.md:329). ``write_tasks_to_handle`` builds
   the full payload FIRST and only truncates once serialization has succeeded --
   the same hardening ``scripts/task_pool_claim.py`` grew inline in 2026-07-05,
   now shared here so every writer inherits it.

   Readers of the mutable queue must take ``LOCK_SH`` on the same descriptor.
   Serialization-first prevents a failed serializer from truncating the file,
   but a lock-free reader can still observe the intentional truncate/write
   window of a healthy writer. ``read_tasks_locked`` is the canonical snapshot
   reader for tools that do not already own a queue lock.

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
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Callable

from volpred.canonical_write import guard_canonical_write

from .blocked_reasons import (
    INCIDENT_SUSTAINED_CLEAN_GATE,
)
from .blocked_reasons import is_valid as is_valid_blocked_reason
from .diagnostics import warn


class InvalidTaskPriority(ValueError):
    """Raised when a task priority cannot be represented as a positive int."""


class ActiveTaskExecutionFence(ValueError):
    """A writer attempted to mutate a task owned by a running external job."""


def normalize_task_type_value(value: object) -> str:
    """Canonical task-type spelling shared by queue and dispatch contracts."""
    return re.sub(r"[-_\s]+", "_", str(value or "").strip().lower()).strip("_")


def task_type_payload_conflict(
    task: dict[str, Any],
) -> tuple[str, str] | None:
    """Return conflicting top-level/payload task types, if both are declared.

    ``task_type`` owns routing, capability, urgency, and draft-pool accounting.
    A nested payload may repeat that declaration for an external adapter, but
    it cannot advertise a different operation without splitting those owners.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict) or "task_type" not in payload:
        return None
    declared = normalize_task_type_value(task.get("task_type"))
    payload_declared = normalize_task_type_value(payload.get("task_type"))
    if declared == payload_declared:
        return None
    return declared, payload_declared


def task_record_sha256(task: dict[str, Any]) -> str:
    payload = json.dumps(
        task,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def task_execution_fence_paths(
    queue_path: str | Path,
    task_id: str,
) -> tuple[Path, Path]:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    root = Path(queue_path).parent / "ops" / "task_execution_fences"
    return root / f"{digest}.lock", root / f"{digest}.json"


def _enforce_active_task_execution_fences(
    queue_path: str | Path,
    tasks: list[Any],
) -> None:
    fence_root = Path(queue_path).parent / "ops" / "task_execution_fences"
    if not fence_root.exists():
        return
    task_by_id = {
        str(task.get("id")): task
        for task in tasks
        if isinstance(task, dict) and task.get("id")
    }
    for lock_path in fence_root.glob("*.lock"):
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            try:
                fcntl.flock(
                    lock_handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                metadata_path = lock_path.with_suffix(".json")
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ActiveTaskExecutionFence(
                        f"active task fence metadata unreadable: {metadata_path}"
                    ) from exc
                task_id = str(metadata.get("task_id") or "")
                task = task_by_id.get(task_id)
                if (
                    task is None
                    or task_record_sha256(task) != metadata.get("record_sha256")
                ):
                    raise ActiveTaskExecutionFence(
                        f"task is owned by running compute job: {task_id}"
                    )
            else:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


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
        "awaiting_agent_job",                    # durable external compute job owns execution
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
LEGACY_OUT_OF_VOCAB_BASELINE = 0


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


#: Fields that assert "a worker owns this row *right now*".  They are only
#: legal while the status is claimed/running: ``volpred.ops.work.legacy``
#: reports any pending/awaiting_approval row still carrying one as
#: ``invalid_lifecycle`` -- "unclaimed status carries active claim trace".
#:
#: This tuple is the single owner of that field list.  Before it existed, four
#: modules performed the same blocked/claimed -> pending transition and only
#: ``task_pool_claim._repend_task`` cleared the trace; its "single mutation
#: site" docstring was true within one module and false across the queue.  On
#: 2026-08-02 the expiry sweeper re-pended ``assign_ae004ae2`` at 08:05:18Z, the
#: shadow observer recorded the resulting invalid row at 08:15:48Z, and that one
#: receipt reset the Issue #9 seven-day clean soak from 2026-08-03 to 2026-08-09.
CLAIM_OWNERSHIP_FIELDS: tuple[str, ...] = (
    "claimed_by",
    "claimed_at",
    "claim_expires_at",
    "claim_session_id",
    "started_at",
    "dispatch_managed",
    "dispatch_managed_owner",
    "dispatch_job_id",
    "dispatch_settlement_pending",
)


def clear_claim_ownership(task: dict[str, Any]) -> tuple[str, ...]:
    """Strip every active-ownership marker from ``task``; return what was removed.

    Call this from *any* transition that leaves a row unowned (-> pending,
    awaiting_approval, or a terminal state reached without a worker).  It only
    touches ownership: status, blocked metadata and ``status_history`` are the
    caller's business, so the audit trail of who held the row survives in
    ``status_history`` even though the live claim fields are gone.

    Returning the removed keys lets callers log what they actually cleared
    instead of asserting a clean state they never verified.
    """
    if not isinstance(task, dict):
        return ()
    return tuple(
        field for field in CLAIM_OWNERSHIP_FIELDS if task.pop(field, None) is not None
    )


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


def is_main_thread_reserved(task: dict) -> bool:
    """One owner for "this task belongs to the interactive main thread".

    The signal legitimately lives in TWO fields — ``dispatch_lane`` and the
    ``pending_main_thread`` status — and before 2026-07-21 the readers each
    picked one: the claim gate read both, the urgency classifier read only the
    lane.  That split is the dispatch contradiction in
    docs/refactor_plan_incident_lifecycle.md (附註): ``assign_10927b4e`` sat at
    ``status=pending_main_thread`` with no lane field, ``is_urgent()`` saw a
    claimable P1, ``request_fire`` woke an hourly supervisor whose claim was
    then refused with ``main_thread_lane`` — a task with no legal executor
    firing forever.  Every reader must derive from THIS predicate.
    """
    if not isinstance(task, dict):
        return False
    if str(task.get("status") or "").strip().lower() == "pending_main_thread":
        return True
    return normalize_dispatch_lane(task) in MAIN_THREAD_DISPATCH_LANES


def is_agent_claimable_lane(task: dict) -> bool:
    """Return True iff a headless/hourly session may claim this task.

    An unset lane stays claimable — the vast majority of the queue predates the
    field, and defaulting those to "reserved" would freeze the whole pool.
    """
    if is_main_thread_reserved(task):
        return False
    lane = normalize_dispatch_lane(task)
    if not lane:
        return True
    return lane not in BLOCKED_DISPATCH_LANES


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


class InvalidBlockedReason(ValueError):
    """Raised when a task blocked_reason is not in the controlled vocabulary."""


# Frozen count of rows whose ``blocked_reason`` predates the vocab gate
# (2026-07-20 WS-A3): 3 rows — one free-text K400 range note, one long
# owner-sign-off prose paragraph, one hand-written ``decomposed_into_subtasks``.
# scripts/migrate_status_vocab.py maps them back (original preserved in
# ``blocked_reason_original``); after apply this drops to 0.
# MIRRORED in scripts/validate_next_tasks_status.py::DEFAULT_BLOCKED_REASON_BASELINE
# (deps-free CI runner cannot import this module); tests/test_task_status_vocab.py
# asserts the two stay equal.
LEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE = 0


def validate_blocked_reason(reason: str | None) -> str:
    """Return the normalized blocked_reason, or raise ``InvalidBlockedReason``.

    Strict raise for callers that set a NEW blocked_reason (mark_task_blocked
    already enforces via argparse choices; sync_next_tasks_status's review gate
    and any future writer call this). The whole-file write path deliberately
    does NOT raise on frozen legacy rows -- see ``_audit_blocked_reasons``.
    """
    if not is_valid_blocked_reason(reason):
        raise InvalidBlockedReason(
            f"blocked_reason {reason!r} not in BLOCKED_REASONS; add it to "
            "src/volpred/ops/blocked_reasons.py if it is a real new reason"
        )
    return str(reason).strip().lower()


def _audit_blocked_reasons(tasks: list[Any]) -> int:
    """Surface out-of-vocab ``blocked_reason`` values (observable, non-fatal).

    Same non-fatal contract as ``_audit_task_statuses`` and for the same reason:
    raising on a whole-file rewrite would brick every materializer while the
    frozen legacy rows are still in the queue. Warns only ABOVE the baseline;
    the mechanical stop is scripts/validate_next_tasks_status.py's gate.

    Counts the field wherever it is set (including terminal rows -- the
    sync review-gate deliberately keeps blocked_reason as audit trail after
    release), so a polluted value cannot hide behind a status flip.
    """
    bad: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        reason = task.get("blocked_reason")
        if reason is None:
            continue
        if not isinstance(reason, str):
            bad.append(repr(reason)[:60])
            continue
        if not reason.strip():
            continue  # empty string == absent
        if not is_valid_blocked_reason(reason):
            bad.append(reason[:60])
    if len(bad) > LEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE:
        warn(
            "next_tasks_blocked_reason",
            "out-of-vocab blocked_reason(s) ABOVE frozen baseline -- new pollution",
            count=len(bad),
            baseline=LEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE,
            examples=bad[:5],
        )
    return len(bad)


class InvalidBlockedUntil(ValueError):
    """Raised when a ``status=blocked`` row cannot be given a valid ``blocked_until``."""


class InvalidUnblockGate(ValueError):
    """Raised when a task carries an invalid live unblock contract."""


def validate_unblock_gates(tasks: list[Any]) -> None:
    """Reject lifecycle shapes that could make a named gate dispatchable.

    Unknown string gates are intentionally preserved when their task remains
    blocked behind an event window.  This is the rollback/rolling-deploy
    contract: an older reader need not understand a newer gate to keep it
    fail-closed.  The expiry sweeper likewise refuses to execute unknown gates.
    Producer CLIs still allowlist gates they are permitted to create.
    """

    for task in tasks:
        if not isinstance(task, dict):
            continue
        gate = task.get("unblock_gate")
        if gate is None:
            continue
        if (
            not isinstance(gate, str)
            or not gate.strip()
            or str(task.get("status") or "").strip().lower() != "blocked"
            or str(task.get("blocked_reason") or "").strip().lower()
            != "awaiting_event_window"
            or not isinstance(task.get("blocked_until"), str)
            or not str(task["blocked_until"]).strip()
            or (
                gate == INCIDENT_SUSTAINED_CLEAN_GATE
                and (
                    not isinstance(task.get("unblock_incident_id"), str)
                    or not str(task["unblock_incident_id"]).strip()
                )
            )
        ):
            raise InvalidUnblockGate(
                f"task {task.get('id')!r} has invalid unblock_gate lifecycle "
                f"shape: gate={gate!r} status={task.get('status')!r} "
                f"blocked_reason={task.get('blocked_reason')!r}"
            )


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
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

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


def is_tombstoned(task: Any) -> bool:
    """True when this row is a compacted archive stub, not a live task.

    One owner for "is this row still evidence about itself?". Compaction keeps
    only ``_TOMBSTONE_KEEP_FIELDS``; the full record moves to
    ``storage/next_tasks_archive/``. So a tombstone has structurally lost
    ``blocked_reason``, ``follows_up_on``, ``k_id`` and ``status_history`` —
    every field a reader would use to ask "was this task ever disposed of?".

    Any detector that judges a row by the *absence* of such a field must call
    this first, or it will keep re-deriving the same answer from data that was
    deleted on purpose. Terminal rows are compacted at 3 days
    (``unblock_expired_blocked_tasks.COMPACT_AGE_DAYS``) while dreaming's
    ``detect_missing_retry_strategy`` looks back 14
    (``loop_health.LOOP_HEALTH_WINDOW_DAYS``): that 11-day overlap made every
    failed row look like an undisposed orphan once it crossed day 3, which is
    where 31 of 32 standing findings came from on 2026-08-03.
    """
    return isinstance(task, dict) and bool(task.get("tombstone"))


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
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

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
        try:
            is_canonical_queue = (
                Path(handle_name).resolve() == CANONICAL_NEXT_TASKS.resolve()
            )
        except OSError:
            is_canonical_queue = False
        if is_canonical_queue:
            position = fh.tell()
            fh.seek(0)
            raw_existing = fh.read()
            fh.seek(position)
            try:
                existing_tasks = (
                    json.loads(raw_existing) if raw_existing.strip() else []
                )
            except json.JSONDecodeError as exc:
                from volpred.ops.task_pool_mode import TaskPoolAdmissionClosed

                raise TaskPoolAdmissionClosed(
                    f"canonical next_tasks queue is unreadable: {exc}"
                ) from exc
            if not isinstance(existing_tasks, list):
                from volpred.ops.task_pool_mode import TaskPoolAdmissionClosed

                raise TaskPoolAdmissionClosed(
                    "canonical next_tasks queue root is not a list"
                )
            from volpred.ops.task_pool_mode import (
                enforce_task_pool_write,
                task_pool_mode_path,
            )

            enforce_task_pool_write(
                state_path=(
                    TASK_POOL_MODE_PATH
                    if TASK_POOL_MODE_PATH != _DEFAULT_TASK_POOL_MODE_PATH
                    else task_pool_mode_path(CANONICAL_NEXT_TASKS)
                ),
                existing_tasks=existing_tasks,
                proposed_tasks=tasks,
            )
        _enforce_active_task_execution_fences(handle_name, tasks)

    _normalize_priorities_tolerant(tasks)
    _audit_task_statuses(tasks)
    _audit_blocked_until(tasks)
    _audit_blocked_reasons(tasks)
    validate_unblock_gates(tasks)
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
    # Every read/modify/write caller releases its flock immediately after this
    # helper returns, while the text handle itself closes one stack frame later.
    # Flush before that unlock boundary so the next lock owner cannot observe
    # the post-truncate, pre-buffer-flush gap and silently lose its update.
    fh.flush()


def read_tasks_locked(path: str | Path) -> list[Any]:
    """Return one parseable task-pool snapshot under the queue's shared lock.

    Writers lock the queue file itself with ``LOCK_EX`` and rewrite it in place.
    Opening and parsing without ``LOCK_SH`` can therefore observe the brief
    post-truncate, pre-write interval even though the writer is correct.  This
    helper deliberately shares that exact inode lock and validates the root
    shape before returning.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            tasks = json.load(fh)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    if not isinstance(tasks, list):
        raise ValueError("next_tasks.json root is not a list")
    return tasks


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


_CI_REPAIR_PENDING_COMMIT_RE = re.compile(
    r"\brepair_commit\s*[:=]\s*pending_post_commit\b",
    re.IGNORECASE,
)
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def backfill_ci_repair_commit(
    *,
    path: str | Path,
    claim_owners: list[str] | tuple[str, ...] | set[str],
    commit_sha: str,
) -> list[str]:
    """Replace an explicit CI-repair post-commit marker with the real SHA.

    A dispatcher task completes before its enclosing Git owner (PHASE-Z or the
    Codex exact-path commit helper) creates a commit.  The task therefore writes
    ``repair_commit=pending_post_commit`` as an intent receipt.  Once Git has a
    real object id, this function binds only terminal ``ci-red-*`` tasks whose
    successful transition was recorded under one of the supplied fire owners.

    The marker and owner checks are both mandatory: time proximity is not
    authorship, and a fire that merely happens to follow somebody else's CI
    repair must never claim that repair.  The update shares the canonical queue
    lock and hardened serializer used by every other task-pool writer.
    """
    owners = {str(owner).strip() for owner in claim_owners if str(owner).strip()}
    sha = str(commit_sha or "").strip().lower()
    if not owners or not _GIT_COMMIT_RE.fullmatch(sha):
        return []

    p = Path(path)
    guard_canonical_write(p)
    if not p.exists():
        return []

    updated: list[str] = []
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            raw = fh.read()
            tasks = json.loads(raw) if raw.strip() else []
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json root is not a list")
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("id") or "")
                if not task_id.startswith("ci-red-"):
                    continue
                if str(task.get("status") or "").lower() not in {
                    "succeeded", "succeeded_null_result",
                }:
                    continue
                history = task.get("status_history")
                terminal = next(
                    (
                        entry for entry in reversed(history)
                        if isinstance(entry, dict)
                        and str(entry.get("to") or "").lower() in {
                            "succeeded", "succeeded_null_result",
                        }
                    ),
                    None,
                ) if isinstance(history, list) else None
                if not terminal or str(terminal.get("by") or "") not in owners:
                    continue
                result = str(task.get("result") or "")
                replaced, count = _CI_REPAIR_PENDING_COMMIT_RE.subn(
                    f"repair_commit={sha}", result, count=1,
                )
                if count != 1:
                    continue
                task["result"] = replaced
                task["repair_commit_source"] = "post_commit_receipt"
                updated.append(task_id)
            if updated:
                write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return updated


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
_DEFAULT_TASK_POOL_MODE_PATH = (
    Path(__file__).resolve().parents[3] / "storage" / "ops" / "task_pool_mode.json"
)
# Explicit override seam for callers/tests that need a non-standard layout.
# Otherwise the mode receipt follows CANONICAL_NEXT_TASKS, so rebinding a queue
# to an isolated storage root cannot accidentally read the live repo's mode.
TASK_POOL_MODE_PATH = _DEFAULT_TASK_POOL_MODE_PATH


def _warn_if_over_pending_cap(record: dict[str, Any], tasks: list[Any]) -> None:
    """Route-around detector for the drain-first gate. Never raises.

    Observability only — enforcement lives at the generator entry points
    (see ``volpred.ops.pool_pressure`` module docstring for why not here).
    An append must never fail because the watchdog did.
    """
    try:
        from volpred.ops.pool_pressure import warn_if_over_cap

        warn_if_over_cap(record, tasks)
    except Exception as exc:
        warn(
            "next_tasks_pool_pressure",
            "pending-cap watchdog failed; append remains authoritative",
            err=f"{type(exc).__name__}: {exc}",
        )


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
    except Exception as exc:
        from volpred.ops.diagnostics import warn

        warn(
            "urgent_fire_request",
            "request_fire failed; urgent task falls back to hourly cadence",
            task_id=str(record.get("id")),
            source=str(record.get("source")),
            err=f"{type(exc).__name__}: {exc}",
        )
        return False


def clamp_machine_priority_inflation(record: dict[str, Any]) -> bool:
    """機器來源的 P1 在 admission 夾到 P2（2026-07-21 dispatch-lanes R2）。

    2026-07-21 實測：pending 181、P1 33 個，boss 來源（telegram/user）只有 8 個，
    其餘 25 個是系統產生器自封的 P1（auto_discovered / agent / orphan_closeout /
    auto_publish_drought_emergency / internal_alert_remediation_router …）。P1 的
    語意是「boss 當下要的 + 時效性」；產生器人人自封 P1 等於取消 priority —— boss
    的新急件在 33 張 P1 裡排隊，這正是 telegram/email 任務被池阻塞的另一半根因
    （選擇端那一半見 continue_task_dispatch.py 的 lane rank）。

    夾制條件（判定全部重用 `task_urgency`，禁止第二套 source 清單）：

    * source **不是** 人為 ingress（`is_urgent_source` False），且
    * task_type **不是** 時效類（TIME_CRITICAL_TASK_TYPES —— 時效任務依 2026-07-12
      boss 指令必須 P1），且
    * task_type **不是** dedicated-owner ingress（email_reply / telegram_reply ——
      各有專屬即時 owner，priority 對它們是 pass-through），且
    * priority 解析後 == 1

    → priority 夾到 2、蓋 ``priority_capped_from: 1``、留一行 warn。

    **只 clamp 不 block**：writer 層不能 block 的邊界同 `pool_pressure` 模組
    docstring —— 走到 gateway 的任務語意上已被上游接受，在這裡拒絕會把失敗散進
    每個 caller 的錯誤路徑；水位煞車屬生成端（pool_pressure 已 own），這裡只矯正
    priority 語意。回傳是否有夾。
    """
    from volpred.ops import task_urgency  # lazy: task_urgency imports this module

    if task_urgency.is_urgent_source(record.get("source")):
        return False
    task_type = record.get("task_type")
    if task_type in task_urgency.TIME_CRITICAL_TASK_TYPES:
        return False
    if task_type in task_urgency.DEDICATED_OWNER_TASK_TYPES:
        return False
    if priority_sort_key(record.get("priority"), default=999) != 1:
        return False
    record["priority"] = 2
    record["priority_capped_from"] = 1
    warn(
        "task_admission",
        "machine-source P1 clamped to P2 (priority_capped_from=1)",
        task_id=str(record.get("id")),
        source=str(record.get("source")),
        task_type=str(task_type),
    )
    return True


def append_task_record(
    record: dict[str, Any],
    *,
    path: str | Path = "storage/next_tasks.json",
    if_exists: str = "skip",
    semantic_dedupe: bool = True,
    active_unique_fields: tuple[str, ...] = (),
) -> tuple[dict[str, Any], bool]:
    """Append one caller-built task record to the queue under LOCK_EX.

    Record-preserving sibling of :func:`append_next_task` (WS-A1b writer
    convergence): ingress writers whose record shape is an external contract
    (``telegram-<msg_id>`` reply-right guard ids, gmail ``email_reply`` payload
    fields, ``daily_digest_YYYYMMDD`` dedupe ids) must not have the gateway
    rebuild their record — but they must share the same bootstrap + flock +
    duplicate-id + serialize-first discipline. This is the one implementation;
    ``append_next_task`` routes through it.

    ``if_exists='skip'`` returns ``(existing_record, False)`` when the id is
    already queued (idempotent ingress replay); ``'raise'`` raises ValueError.

    ``semantic_dedupe=True`` (default) additionally refuses records that are a
    **semantic** duplicate of an already-open task — same file + symbol +
    failure class, per ``volpred.ops.task_signature``. id-equality alone let the
    same bug be filed twice 15 minutes apart (assign_614e70ee / assign_1d936f52),
    and a post-hoc sweep only finds it after the queue is already polluted; the
    boss requirement is to stop it **at the creation entry point**. Refused
    records come back as ``(record, False)`` with ``duplicate_of`` /
    ``duplicate_reason`` set so the caller can report instead of silently
    growing the pool.

    ``active_unique_fields`` adds an exact machine-identity constraint under
    the same queue ``LOCK_EX``. If every named field matches an already-open
    record, that record is returned with ``created=False``. This covers
    contracts such as one active review per ``gate_review_id`` where generic
    text similarity is the wrong identity and caller-side checking has a
    TOCTOU race.

    After the lock is released an urgent record (``task_urgency.is_urgent``)
    requests an out-of-band supervisor fire; ``record['fire_requested']`` is a
    **return-only receipt** (CLI print / test assertion), deliberately not
    persisted — it is the outcome of this append, not task state. Dedicated
    owner types (email_reply / telegram_reply) are never urgent here by design;
    their ingest daemons own their own immediate paths (see
    ``_request_urgent_fire`` docstring).
    """
    if if_exists not in {"skip", "raise"}:
        raise ValueError(f"if_exists must be 'skip' or 'raise', got {if_exists!r}")
    task_id = record.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task record must carry a non-empty string 'id'")
    type_conflict = task_type_payload_conflict(record)
    if type_conflict is not None:
        declared, payload_declared = type_conflict
        raise ValueError(
            "task record task_type conflicts with payload.task_type: "
            f"{declared or '<missing>'} != {payload_declared or '<missing>'}"
        )
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    created_at = record["created_at"]
    if not isinstance(created_at, str):
        raise ValueError("task record 'created_at' must be a timezone-aware ISO-8601 string")
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError(
            "task record 'created_at' must be a timezone-aware ISO-8601 string"
        ) from exc
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise ValueError("task record 'created_at' must include a timezone offset")
    if "issue_ref" in record:
        if record["issue_ref"] is None:
            record.pop("issue_ref")
        else:
            from volpred.ops.issue_tracker_sync import normalize_issue_ref

            record["issue_ref"] = normalize_issue_ref(record["issue_ref"])

    p = Path(path)
    guard_canonical_write(p)
    is_canonical_queue = p.resolve() == CANONICAL_NEXT_TASKS.resolve()

    # R2 admission clamp（單一 gateway = 單一 enforcement 點）：機器來源不得自封
    # P1。boss 來源 / 時效類 / dedicated-owner ingress 原樣通過。
    clamp_machine_priority_inflation(record)

    # G6 24h 全域上限（incident-lifecycle P2）：決策 owner =
    # volpred.ops.remediation_throttle；這裡只是 gateway 的 choke point。
    from volpred.ops import remediation_throttle

    throttle_denied = False
    dup_verdict: dict[str, Any] | None = None

    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("[]\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            raw = fh.read()
            tasks = json.loads(raw) if raw.strip() else []
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json root is not a list")
            for existing in tasks:
                if isinstance(existing, dict) and existing.get("id") == task_id:
                    if if_exists == "raise":
                        raise ValueError(f"duplicate task id {task_id}")
                    return existing, False
            if active_unique_fields:
                missing_fields = [
                    field
                    for field in active_unique_fields
                    if record.get(field) in (None, "")
                ]
                if missing_fields:
                    raise ValueError(
                        "active_unique_fields require non-empty record values: "
                        f"{missing_fields!r}"
                    )
                active_statuses = {
                    "pending",
                    "pending_main_thread",
                    "claimed",
                    "in_progress",
                    "awaiting_agent_job",
                    "blocked",
                }
                for existing in tasks:
                    if not isinstance(existing, dict):
                        continue
                    if str(existing.get("status") or "") not in active_statuses:
                        continue
                    if all(
                        existing.get(field) == record.get(field)
                        for field in active_unique_fields
                    ):
                        return existing, False
            if is_canonical_queue:
                # Admission ownership precedes payload provenance: direct mode
                # and an unreadable owner-state must fail closed before any
                # lower-level record validation. The check stays under the
                # queue lock so mode admission and the observed task set form
                # one snapshot; write_tasks_to_handle rechecks immediately
                # before mutation to close a concurrent mode transition.
                from volpred.ops.task_pool_mode import (
                    enforce_task_pool_write,
                    task_pool_mode_path,
                )

                enforce_task_pool_write(
                    state_path=(
                        TASK_POOL_MODE_PATH
                        if TASK_POOL_MODE_PATH != _DEFAULT_TASK_POOL_MODE_PATH
                        else task_pool_mode_path(CANONICAL_NEXT_TASKS)
                    ),
                    existing_tasks=tasks,
                    proposed_tasks=[*tasks, record],
                )

                # Only a genuinely new, mode-admitted canonical record needs
                # source provenance. Idempotent replay returned above and must
                # not be retroactively invalidated by a newer schema rule.
                from volpred.ops.work.legacy import classify_next_task_source

                try:
                    classify_next_task_source(record.get("source"))
                except ValueError as exc:
                    raise ValueError(
                        "unreviewed canonical task source: "
                        f"{record.get('source')!r}"
                    ) from exc
            parent_task_id = record.get("parent_task_id")
            if parent_task_id is not None:
                if not isinstance(parent_task_id, str) or not parent_task_id.strip():
                    raise ValueError(
                        "task record 'parent_task_id' must be a non-empty string"
                    )
                if not any(
                    isinstance(existing, dict)
                    and existing.get("id") == parent_task_id
                    for existing in tasks
                ):
                    raise ValueError(
                        "task record parent_task_id is absent from the canonical "
                        f"task pool: {parent_task_id}"
                    )
            # 語意重複閘門（老闆 2026-07-21：「在建單入口擋，不是事後掃」）。
            # 放在 id 檢查之後、append 之前 —— 同一個 LOCK_EX 之內，所以不會有
            # 「兩個 caller 同時通過檢查再雙雙寫入」的 TOCTOU 窗口。
            if semantic_dedupe:
                from volpred.ops.task_signature import find_semantic_duplicate

                dup_verdict = find_semantic_duplicate(record, tasks)

            if dup_verdict is not None:
                pass  # refused below, outside the lock
            elif remediation_throttle.is_auto_remediation(record) and remediation_throttle.over_cap(
                tasks
            ):
                throttle_denied = True
            else:
                tasks.append(record)
                write_tasks_to_handle(fh, tasks)
            # 不擋，只記錄：閘門在 generator entry point（pool_pressure 模組 docstring
            # 說明為何不在此層 enforce），所以任何新的自動 caller 天然繞得過去。這行
            # 讓「繞過」在 log 現形，而不是靜默灌水。
            if not throttle_denied and dup_verdict is None:
                _warn_if_over_pending_cap(record, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    if dup_verdict is not None:
        record["duplicate_of"] = dup_verdict["existing_id"]
        record["duplicate_reason"] = "; ".join(dup_verdict["reasons"])
        record["duplicate_signature"] = dup_verdict["b_key"]
        record["duplicate_score"] = dup_verdict["score"]
        warn(
            "task_admission",
            "semantic duplicate refused at creation entry point",
            task_id=task_id,
            duplicate_of=dup_verdict["existing_id"],
            score=str(dup_verdict["score"]),
            anchor=",".join(dup_verdict["anchor"][:4]),
        )
        # 刻意不 raise（即使 if_exists='raise'）：`raise` 的語意是「id 撞了，
        # uuid4 下實質不可達」，而語意重複是**常態**。把常態走例外路徑會把失敗
        # 散進每個 caller 的錯誤處理。回傳 created=False + duplicate_of 標記，
        # 讓 caller 回報而不是靜默多一張。
        return record, False
    if throttle_denied:
        # 鎖已釋放才寫 ledger（ledger 快，但原則上 side effect 不佔 queue flock）。
        # 摘要信由 check_alerts 的 flush_denial_summary 每日彙整一封（G6）。
        remediation_throttle.record_denial(
            record, ledger_path=remediation_throttle.ledger_path_for(p)
        )
        record["throttled_by_remediation_cap"] = True
        return record, False
    # 急件不進排班：入池成功後（鎖已釋放）立刻請 supervisor 派工。
    record["fire_requested"] = _request_urgent_fire(record, p)
    return record, True


def rollover_active_task_record(
    *,
    path: str | Path,
    active_unique_fields: tuple[str, ...],
    identity: dict[str, Any],
    replacement_builder: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, str | None]:
    """Atomically supersede one active aggregate and append its new hash ID."""

    p = Path(path)
    guard_canonical_write(p)
    # pending_main_thread is already a routing reservation.  Replacing it with
    # the generic record would silently hand it back to an agent lane.
    rollover_statuses = {"pending"}
    with p.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            raw = handle.read()
            tasks = json.loads(raw) if raw.strip() else []
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json root is not a list")
            active_index = next(
                (
                    index
                    for index, row in enumerate(tasks)
                    if isinstance(row, dict)
                    and str(row.get("status") or "") in rollover_statuses
                    and all(
                        row.get(field) == identity.get(field)
                        for field in active_unique_fields
                    )
                ),
                None,
            )
            if active_index is None:
                return None, None
            current = tasks[active_index]
            replacement = replacement_builder(dict(current))
            if replacement is None:
                return current, None
            replacement_id = str(replacement.get("id") or "")
            if not replacement_id:
                raise ValueError("replacement requires id")
            if any(
                isinstance(row, dict) and row.get("id") == replacement_id
                for row in tasks
            ):
                raise ValueError(
                    f"replacement task id already exists: {replacement_id}"
                )
            now = str(
                replacement.get("created_at")
                or datetime.now(timezone.utc).isoformat()
            )
            history = list(current.get("status_history") or [])
            history.append(
                {
                    "ts": now,
                    "from": current.get("status"),
                    "to": "superseded",
                    "by": "control_gate_lifecycle",
                    "reason": "inventory_scope_changed",
                    "superseded_by": replacement_id,
                }
            )
            tasks[active_index] = {
                **current,
                "status": "superseded",
                "completed_at": now,
                "superseded_by": replacement_id,
                "status_history": history,
            }
            replacement_row = {
                **replacement,
                "supersedes_inventory_task_id": current.get("id"),
            }
            tasks.append(replacement_row)
            write_tasks_to_handle(handle, tasks)
            return replacement_row, str(current.get("id") or "")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def refresh_active_task_record(
    *,
    path: str | Path,
    active_unique_fields: tuple[str, ...],
    identity: dict[str, Any],
    refresh_builder: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, bool]:
    """Atomically merge new aggregate scope into one running task.

    Unreserved pending aggregates can be rolled to a new hash-addressed task
    ID.  Once a worker owns the task *or it is reserved for the main thread*,
    changing its ID would sever ownership/routing.  This helper instead
    appends a consumable scope-delta receipt to the same queue row; the
    completion contract then reads the refreshed snapshot and refuses a stale
    close until the live inventory is clean.
    """

    p = Path(path)
    guard_canonical_write(p)
    with p.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            raw = handle.read()
            tasks = json.loads(raw) if raw.strip() else []
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json root is not a list")
            active_index = next(
                (
                    index
                    for index, row in enumerate(tasks)
                    if isinstance(row, dict)
                    and str(row.get("status") or "") in {
                        "pending_main_thread",
                        "claimed",
                        "in_progress",
                        "awaiting_agent_job",
                        "blocked",
                    }
                    and all(
                        row.get(field) == identity.get(field)
                        for field in active_unique_fields
                    )
                ),
                None,
            )
            if active_index is None:
                return None, False
            current = tasks[active_index]
            refreshed = refresh_builder(dict(current))
            if refreshed is None:
                return current, False
            if refreshed.get("id") != current.get("id"):
                raise ValueError("running task refresh cannot change id")
            tasks[active_index] = refreshed
            write_tasks_to_handle(handle, tasks)
            return refreshed, True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    issue_ref: str | None = None,
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
    if issue_ref is not None:
        from volpred.ops.issue_tracker_sync import normalize_issue_ref

        record["issue_ref"] = normalize_issue_ref(issue_ref)

    record, _created = append_task_record(record, path=path, if_exists="raise")
    return record
