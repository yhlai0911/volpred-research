"""Re-run a dreaming finding's own detector before anyone acts on the task.

A dreaming task is a SNAPSHOT of a condition observed on some night. Between that
night and the moment a fire claims the task, the condition can dissolve on its own.
When it does, the task keeps carrying its original imperative — and that is worse
than a wasted slot.

The incident (2026-07-17 16:07 fire, 4/4): four `orphaned_experiment` tasks
(k1697 / k1699 / k1608 / k1609) were queued 07-12~07-13 for "no knowledge entry →
write one". On 07-14 `kb_backfill_unrecorded_experiments` wrote entries for all
four. The tasks were still dispatched three days later still saying "寫
knowledge.json" — an agent following the description literally would have written
DUPLICATE entries. Nothing caught it except the main thread choosing to verify by
hand. That is discipline, not a mechanism.

This is the same invariant the alert system already enforces
(`alert_remediation._sweep_cleared_ordinary_tasks` +
`_REVALIDATION_INSTRUCTION`): re-run the ORIGINAL detector before executing a
snapshot, and if the condition cleared on its own, close it as a fresh no-op
instead. Dreaming had neither half. This module is dreaming's half.

## Per-pattern audit (class sweep, not just the one that bit us)

Only some dreaming patterns are stale-snapshot-prone. A pattern qualifies when its
finding asserts a LIVE condition that some other actor can satisfy independently.
Patterns whose evidence is a historical observation are not re-checkable — the log
window that produced them does not un-happen, so "re-verify" has no meaning.

  orphaned_experiment  RE-CHECKABLE — "no downstream consumer for <kid>" is live
                       state over knowledge.json / feed.json / paper / open tasks,
                       and backfill, an article, or another fire can satisfy it.
                       Registered below.
  persistent_alert     Live, but NOT ours: alert_remediation already owns closing
                       tasks whose alert cleared (`_sweep_cleared_ordinary_tasks`).
                       Registering a second owner here would be the stacking the
                       anti-stacking rule forbids.
  stale_knowledge      Live-ish (a flagged article can be corrected or retracted),
                       but the finding is propose_only and resolution is a judgement
                       call about semantic overlap — auto-closing it would suppress
                       review, not save a slot. Deliberately unregistered.
  repeated_tool_failure / recurring_error / loop_metric_regression /
  semantic_concentration / memory_skill_gap / memory_hygiene /
  missing_retry_strategy
                       Historical: each summarises a window of logs, loop metrics,
                       or memory contents as they WERE. Re-running the detector now
                       answers a different question ("is it still happening?"), not
                       "was this observation stale". Unregistered by design.

An unregistered pattern returns None from `revalidate()` and is left completely
alone — silence here means "no opinion", never "condition cleared".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from volpred.ops.common import project_path
from volpred.ops.diagnostics import warn

# Terminal result text written onto a task whose condition dissolved. Kept as a
# constant so the dispatcher sweep and the claim guard cannot drift apart, and so a
# grep for it finds every no-op closure.
CLEARED_RESULT = "dreaming condition cleared before dispatch (fresh no-op)"
CLEARED_NOTE = "dreaming_condition_cleared"
CLEARED_REASON = "dreaming_condition_cleared"

# Embedded in every dreaming task description. Covers the patterns that have NO
# registered revalidator too — there the instruction is the only guard, and a human
# or agent re-reading the detector is exactly the right amount of automation.
REVALIDATION_INSTRUCTION = (
    "⚠️ 執行前必須用原 detector 重新驗證此條件「現在」仍成立。"
    "dreaming 任務是某一晚的快照，條件可能已被別的 actor 自然解除"
    "（例：orphaned_experiment 的 knowledge.json 條目已由 backfill 補上）。"
    "已解除 → 只記錄 fresh no-op 後 complete succeeded，不得照舊快照執行。"
    "若條件已解除是因為存在「未經 review」的自動補寫條目，"
    "請走 scripts/revise_knowledge_entry.py 修訂既有條目，"
    "不要用 add_knowledge 另寫一筆（會產生重複）。"
)

_SIGNATURE_KID = re.compile(r"^orphaned_experiment:(k\d{3,4})$", re.IGNORECASE)
_OPEN_STATUSES = ("pending", "pending_main_thread", "in_progress", "claimed")


@dataclass(frozen=True)
class Revalidation:
    """Verdict of re-running one finding's detector. `cleared` drives the action."""

    pattern_type: str
    cleared: bool
    reason: str
    detail: str


def _consumer_sources(
    storage_dir: str, *, exclude_task_ids: Sequence[str] = ()
) -> dict[str, str]:
    """The four downstream surfaces that can own an experiment, lowercased.

    Returns them LABELLED rather than pre-joined so a clearance can say which
    surface satisfied it — "cleared by knowledge.json" is auditable, "cleared" is
    not. `detect_orphaned_experiments` joins the values back into one blob, so the
    detector and this revalidator cannot drift about what "consumer" means.

    `exclude_task_ids` exists for one reason and it is load-bearing: the dreaming
    task itself is an OPEN task whose description contains the K-id. Re-running the
    scan without excluding it would find the task's own text and declare every
    orphan consumed — the revalidator would clear 100% of what it checks. Other
    open tasks still count: someone else on their way to it means owned, not
    orphaned, which is the detector's original semantics.
    """
    root = project_path(storage_dir).parent
    out: dict[str, str] = {}
    for label, rel in (
        ("knowledge.json", "storage/memory/knowledge.json"),
        ("feed.json", "storage/reports/feed.json"),
    ):
        try:
            out[label] = (root / rel).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError as exc:
            warn("dreaming", "consumer source unreadable", path=rel, err=str(exc))
    paper: list[str] = []
    try:
        for tex in sorted((root / "paper").rglob("*.tex")):
            paper.append(tex.read_text(encoding="utf-8", errors="ignore").lower())
    except OSError as exc:
        warn("dreaming", "paper tree unreadable", err=str(exc))
    out["paper"] = "\n".join(paper)

    from volpred.ops.loop_health import _load_next_tasks  # local: avoids import cycle

    excluded = {str(t) for t in exclude_task_ids if t}
    open_tasks = [
        t
        for t in _load_next_tasks(storage_dir)
        if str(t.get("status") or "").lower() in ("pending", "in_progress")
        and str(t.get("id") or "") not in excluded
    ]
    out["open task"] = json.dumps(open_tasks, ensure_ascii=False).lower()
    return out


def consumer_blob(storage_dir: str, *, exclude_task_ids: Sequence[str] = ()) -> str:
    """Flat lowercase blob of every consumer surface — the detector's view."""
    return "\n".join(_consumer_sources(storage_dir, exclude_task_ids=exclude_task_ids).values())


def _kid_of(task: dict[str, Any]) -> str | None:
    dreaming = task.get("dreaming")
    signature = ""
    if isinstance(dreaming, dict):
        signature = str(dreaming.get("signature") or "")
    m = _SIGNATURE_KID.match(signature.strip())
    return m.group(1).lower() if m else None


def _revalidate_orphaned_experiment(
    task: dict[str, Any], *, storage_dir: str
) -> Revalidation | None:
    """Cleared iff some downstream surface now mentions the K-id."""
    kid = _kid_of(task)
    if not kid:
        # Signature not in the expected shape — we cannot name the experiment, so we
        # have no opinion. Fail-open: an unrecognised task is dispatched as before.
        return None
    task_id = str(task.get("id") or "")
    try:
        sources = _consumer_sources(storage_dir, exclude_task_ids=(task_id,))
    except (OSError, ValueError) as exc:  # fail-open, exactly like the detector
        warn("dreaming", "revalidate: consumer scan failed; leaving task alone", err=str(exc))
        return None
    hits = [label for label, text in sources.items() if kid in text]
    if not hits:
        return Revalidation(
            pattern_type="orphaned_experiment",
            cleared=False,
            reason="still_orphaned",
            detail=f"{kid} 仍無下游消費者（knowledge.json / feed.json / paper / 其他 open task 皆無）",
        )
    return Revalidation(
        pattern_type="orphaned_experiment",
        cleared=True,
        reason=CLEARED_REASON,
        detail=(
            f"{kid} 已被下游消費（{', '.join(hits)}）——孤兒條件在建單後自然解除。"
            f"若該條目係自動 backfill 未經 review，改走 revise_knowledge_entry.py，勿另寫一筆。"
        ),
    )


_REVALIDATORS: dict[str, Callable[..., Revalidation | None]] = {
    "orphaned_experiment": _revalidate_orphaned_experiment,
}


def pattern_type_of(task: dict[str, Any]) -> str | None:
    """The dreaming pattern this task came from, or None if it is not a dreaming task."""
    if str(task.get("source") or "").strip().lower() != "dreaming":
        return None
    dreaming = task.get("dreaming")
    if not isinstance(dreaming, dict):
        return None
    pattern = str(dreaming.get("pattern_type") or "").strip()
    return pattern or None


def requires_live_revalidation(task: dict[str, Any]) -> bool:
    """Whether claiming this open task must run a registered live detector."""

    pattern = pattern_type_of(task)
    status = str(task.get("status") or "").strip().lower()
    return pattern in _REVALIDATORS and status in _OPEN_STATUSES


def revalidate(task: dict[str, Any], *, storage_dir: str | None = None) -> Revalidation | None:
    """Re-run this dreaming task's own detector. None = no opinion, leave it alone.

    None is returned for non-dreaming tasks, for patterns with no registered
    revalidator (see the module docstring's audit), and whenever the check itself
    fails. Only a returned `cleared=True` may close a task.
    """
    pattern = pattern_type_of(task)
    if not pattern:
        return None
    fn = _REVALIDATORS.get(pattern)
    if fn is None:
        return None
    if str(task.get("status") or "").strip().lower() not in _OPEN_STATUSES:
        return None  # terminal tasks are history; never re-open the question
    try:
        return fn(task, storage_dir=storage_dir or "storage")
    except Exception as exc:  # never let a revalidator break claim or dispatch
        warn("dreaming", "revalidate raised; leaving task alone", pattern=pattern, err=str(exc))
        return None


def close_as_cleared(task: dict[str, Any], verdict: Revalidation, *, by: str, now: str) -> None:
    """Terminalise a task whose condition dissolved. Mutates `task` in place.

    Writes the same shape `alert_remediation` writes for a cleared alert: terminal
    `succeeded` (it IS done — by someone else), an explicit result naming why, and
    a status-history note that greps.
    """
    previous = str(task.get("status") or "").strip().lower() or "pending"
    task["status"] = "succeeded"
    task["completed_at"] = now
    task["result"] = f"{CLEARED_RESULT}: {verdict.detail}"
    for field in (
        "claimed_by",
        "claimed_at",
        "claim_expires_at",
        "claim_session_id",
    ):
        task.pop(field, None)
    history = task.setdefault("status_history", [])
    if isinstance(history, list):
        history.append(
            {"from": previous, "to": "succeeded", "by": by, "at": now, "note": CLEARED_NOTE}
        )


def sweep_cleared(
    tasks: Iterable[dict[str, Any]], *, storage_dir: str = "storage", by: str, now: str
) -> list[dict[str, Any]]:
    """Close every open dreaming task whose condition dissolved. Returns the closures.

    Called before the dispatcher categorises, so a dissolved task never becomes a
    candidate and never ages into the 24h starvation lockout that would force-feed
    it to a fire — the exact waste `_sweep_cleared_ordinary_tasks` was written to
    stop on the alert side.
    """
    closed: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        # Only UNCLAIMED work. The claim guard owns the claimed/in-progress case,
        # where it runs once at claim time with the claimer present. Sweeping a
        # task another fire is mid-way through would flip its status to succeeded
        # underneath a live agent — the dispatcher must never do that.
        if str(task.get("status") or "").strip().lower() not in ("pending", "pending_main_thread"):
            continue
        if task.get("claimed_by"):
            continue
        verdict = revalidate(task, storage_dir=storage_dir)
        if verdict is None or not verdict.cleared:
            continue
        close_as_cleared(task, verdict, by=by, now=now)
        closed.append(
            {"id": task.get("id"), "pattern_type": verdict.pattern_type, "detail": verdict.detail}
        )
    return closed
