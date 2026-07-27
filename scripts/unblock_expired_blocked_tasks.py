#!/usr/bin/env python3
"""Queue maintenance sweep for storage/next_tasks.json（每班 dispatch PRE-PHASE-0）.

三項職責（同一 owner、同一把鎖 — anti-stacking）：

1. **Unblock expired**：blocked 且 blocked_until 已過期 → status="pending"，
   清 blocked_* 欄位並寫 status_history audit。`codex_quota_reset_pending`
   是例外：外部額度是可實測狀態，不以日期猜測；每次 apply 最多做一次
   有界 reachability probe，成功即提早解封全部同類任務，失敗則維持 blocked。
   Why: dispatcher (continue_task_dispatch.py:102) 只把 status=="pending" 當
   candidates；categorize() 的 blocked_until check 只 gate runtime dispatch，
   永遠不會把 status 翻回來 → 過期 blocked task 永遠進不了 agentable pool。

2. **Escalate missing blocked_until**（2026-07-18 boss Telegram msg 937 P1）：
   status=blocked 但**沒有** blocked_until 的 row，第 1 項掃不到（它只處理
   已過期者）、dispatcher 也不看（只收 pending）→ 無限停放，2026-07-18 共 19 筆。
   一律列入 escalate 清單（stdout + diagnostics warn），`--apply` 保守處置：
   補預設窗口 + `needs_adjudication=true`，**不** auto re-pend、**不** auto close
   （裁決權在人）。上游 invariant 在 volpred.ops.next_tasks.enforce_blocked_until。

3. **Compact terminal**（2026-07-14 refactor_plan_token_ops_waste WS2a）：
   終態超過 30 天的任務壓成 tombstone（id/status/type/title 留池 → 所有
   reader 的 id 查重零改動），全文 append 到
   storage/next_tasks_archive/YYYY-MM.jsonl。歸檔先落地、queue 後改寫
   （crash-safe：中斷只會留下無害的重複歸檔，下一輪已 tombstone 不會重歸）。

2026-07-14 同時修正：改走 fcntl LOCK_EX 全程持鎖 read-modify-write
（原裸 read_text/write_text 與 task_pool_claim 的鎖協議不相容，有 race）。

Usage:
    uv run python scripts/unblock_expired_blocked_tasks.py            # dry-run
    uv run python scripts/unblock_expired_blocked_tasks.py --apply    # write
"""
from __future__ import annotations

import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
from volpred.canonical_write import guard_canonical_write
from volpred.ops.blocked_reasons import (
    WORK_SHADOW_CUTOVER_GATE,
)
from volpred.ops.diagnostics import warn
from volpred.ops.next_tasks import (
    compact_terminal_tasks,
    default_blocked_until,
    write_tasks_to_handle,
)
from volpred.ops.timestamps import parse_iso_warn

PATH = Path("storage/next_tasks.json")
ARCHIVE_DIR = Path("storage/next_tasks_archive")
BLOCKED_FIELDS = (
    "blocked_reason",
    "blocked_at",
    "blocked_until",
    "blocked_note",
    "unblock_gate",
)
# 3 天：唯一讀 recent-terminal 全文的 reader 是 generate_handoff 的
# recently_completed（24h 窗口，只用 completed_at/title）；其餘 reader 全部
# 只做 id 查重（tombstone 保留）。2026-07-14 實測 30 天窗口留下 1.96MB 殘量。
COMPACT_AGE_DAYS = 3
CODEX_QUOTA_REASON = "codex_quota_reset_pending"


def _probe_codex_available() -> tuple[bool, str]:
    """Return whether a bounded Codex round-trip succeeds right now.

    Import lazily so ordinary queue maintenance (and every dry-run) does not load
    the dispatch supervisor merely to inspect dates.  Reuse the failover probe:
    it is already the single owner for binary resolution, PATH repair, prompt,
    timeout, and reachability semantics.
    """
    from scripts.dispatch_supervisor import codex_failover

    codex_bin = codex_failover.resolve_codex_bin()
    if not codex_bin:
        return False, "codex binary not found"
    ok, rc, detail = codex_failover.preflight(codex_bin)
    if not ok:
        return False, f"preflight rc={rc}: {detail}"
    reachable, rc, detail = codex_failover.check_reachable(codex_bin)
    if not reachable:
        return False, f"reachability rc={rc}: {detail}"
    return True, detail


def _probe_unblock_gate(task: dict) -> tuple[bool, str]:
    """Evaluate one allowlisted durable gate without executing task content."""

    gate = task.get("unblock_gate")
    if gate != WORK_SHADOW_CUTOVER_GATE:
        return False, f"unknown_unblock_gate:{gate!r}"
    from volpred.ops.task_pool_mode import (
        load_task_pool_mode_evidence,
        task_pool_mode_path,
    )
    from volpred.ops.work_shadow_assessment import (
        MAX_OBSERVATION_GAP,
        REQUIRED_OBSERVATION_WINDOW,
        assess_shadow_observation_directory,
    )

    queue_path = _REPO_ROOT / "storage" / "next_tasks.json"
    observation_dir = (
        _REPO_ROOT / "storage" / "ops" / "work_shadow_observations"
    )
    try:
        owner_evidence = load_task_pool_mode_evidence(
            task_pool_mode_path(queue_path)
        )
        report = assess_shadow_observation_directory(
            observation_dir,
            assessed_at=datetime.now(timezone.utc),
            queue_owner=owner_evidence,
            required_window=REQUIRED_OBSERVATION_WINDOW,
            max_gap=MAX_OBSERVATION_GAP,
        )
    except (OSError, TypeError, ValueError) as exc:
        return False, f"work_shadow_assessment_unavailable:{exc}"
    if report.ready_for_cutover:
        return True, "ready_for_cutover"
    return False, ",".join(report.reason_codes) or "not_ready"


def _sweep_unblock(
    tasks: list,
    *,
    apply: bool,
    codex_probe_ok: bool | None = None,
) -> tuple[list[dict], list[dict]]:
    now = datetime.now(timezone.utc)
    swept: list[dict] = []
    gated: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if (t.get("status") or "").lower() != "blocked":
            continue
        blocked_reason = t.get("blocked_reason")
        if blocked_reason == CODEX_QUOTA_REASON:
            # A reset timestamp is an observation made during an earlier
            # failure, not a durable fact.  Success is the only valid unblock
            # condition; failure keeps even an expired row parked instead of
            # feeding a known-unavailable dependency back into dispatch.
            if codex_probe_ok is not True:
                continue
            unblock_reason = "codex_reachability_probe_succeeded"
        else:
            unblock_reason = None
        until = t.get("blocked_until")
        if not until and unblock_reason is None:
            continue
        # Strict ISO parsing still accepts the plain `YYYY-MM-DD` form. Invalid
        # blocked_until values must stay blocked; a lexical fallback can unblock
        # malformed metadata by accident.
        if unblock_reason is None:
            until_dt = parse_iso_warn(
                until,
                tag="unblock",
                field_name="blocked_until",
                fallback=None,
                task_id=str(t.get("id") or ""),
            )
            if until_dt is None:
                continue  # parse failed → WARN already emitted, keep blocked
            if until_dt > now:
                continue
            unblock_reason = f"blocked_until_expired ({until})"
        gate = t.get("unblock_gate")
        if gate is not None:
            gate_ready, gate_detail = _probe_unblock_gate(t)
            if not gate_ready:
                gated.append(
                    {
                        "id": t.get("id"),
                        "task_type": t.get("task_type"),
                        "blocked_reason": blocked_reason,
                        "blocked_until": until,
                        "unblock_gate": gate,
                        "gate_detail": gate_detail,
                    }
                )
                continue
            unblock_reason = f"unblock_gate_satisfied ({gate})"
        swept.append(
            {
                "id": t.get("id"),
                "task_type": t.get("task_type"),
                "blocked_reason": blocked_reason,
                "blocked_until": until,
                "unblock_reason": unblock_reason,
            }
        )
        if apply:
            t["status"] = "pending"
            t.setdefault("status_history", []).append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "from": "blocked",
                    "to": "pending",
                    "reason": unblock_reason,
                }
            )
            for k in BLOCKED_FIELDS:
                t.pop(k, None)
    return swept, gated


def _sweep_missing_until(tasks: list, *, apply: bool) -> list[dict]:
    """Pass 3: blocked rows with NO blocked_until — escalate, never silently skip.

    `_sweep_unblock` above `continue`s on a falsy blocked_until, which was correct
    for its own job (never unblock what has no expiry) but meant the row was
    invisible to every pass: the dispatcher ignores non-pending, the sweeper
    ignores no-expiry, so 19 rows sat parked indefinitely (boss Telegram msg 937,
    2026-07-18). Silence is the bug; these are now always listed.

    `--apply` is deliberately CONSERVATIVE: give the row an exit window and flag
    it for adjudication. It does NOT re-pend (the block may still be real) and
    does NOT close (only a human retires work). The next expiry sweep then picks
    it up through the normal path if nobody has adjudicated it by then.
    """
    escalated: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if (t.get("status") or "").lower() != "blocked":
            continue
        until = t.get("blocked_until")
        if isinstance(until, str) and until.strip():
            continue
        if until is not None and not isinstance(until, str):
            # Present but unusable; enforce_blocked_until refuses to guess.
            escalated.append(
                {
                    "id": t.get("id"),
                    "task_type": t.get("task_type"),
                    "blocked_reason": t.get("blocked_reason"),
                    "detail": f"blocked_until is {type(until).__name__}, not an ISO string",
                    "assigned_until": None,
                }
            )
            continue
        new_until = default_blocked_until()
        escalated.append(
            {
                "id": t.get("id"),
                "task_type": t.get("task_type"),
                "blocked_reason": t.get("blocked_reason"),
                "detail": "no blocked_until — unreachable by the expiry sweep",
                "assigned_until": new_until,
            }
        )
        if apply:
            t["blocked_until"] = new_until
            t["needs_adjudication"] = True
            t.setdefault("status_history", []).append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "from": "blocked",
                    "to": "blocked",
                    "reason": f"missing_blocked_until_backfilled ({new_until}); needs_adjudication",
                }
            )
    return escalated


def _persist_archive(archived: list[dict]) -> Path:
    dest = ARCHIVE_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m')}.jsonl"
    guard_canonical_write(dest)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        for rec in archived:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
    return dest


def main(apply: bool) -> int:
    if not PATH.exists():
        print("[queue-maint] next_tasks.json missing; nothing to do")
        return 0
    if apply:
        # Guard once this invocation has committed to a mutation. The default
        # audit mode opens read-only and remains usable under the test gate.
        guard_canonical_write(PATH)
    mode = "r+" if apply else "r"
    with PATH.open(mode, encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if apply else fcntl.LOCK_SH)
        try:
            tasks = json.loads(fh.read() or "[]")
            if isinstance(tasks, dict):
                tasks = tasks.get("tasks", [])
            quota_blocked = [
                t
                for t in tasks
                if isinstance(t, dict)
                and (t.get("status") or "").lower() == "blocked"
                and t.get("blocked_reason") == CODEX_QUOTA_REASON
            ]
            codex_probe_ok: bool | None = None
            if quota_blocked and apply:
                codex_probe_ok, probe_detail = _probe_codex_available()
                outcome = "available" if codex_probe_ok else "unavailable"
                print(
                    f"[queue-maint] codex quota probe: {outcome}; "
                    f"blocked={len(quota_blocked)}; {probe_detail}"
                )
            elif quota_blocked:
                print(
                    f"[queue-maint] dry-run: would actively probe Codex for "
                    f"{len(quota_blocked)} quota-blocked task(s); no probe sent"
                )
            swept, gated = _sweep_unblock(
                tasks,
                apply=apply,
                codex_probe_ok=codex_probe_ok,
            )
            escalated = _sweep_missing_until(tasks, apply=apply)
            n_compact, archived = compact_terminal_tasks(tasks, age_days=COMPACT_AGE_DAYS)
            if apply:
                if archived:
                    dest = _persist_archive(archived)  # archive FIRST, queue second
                    print(f"[queue-maint] archived {n_compact} full records → {dest}")
                write_tasks_to_handle(fh, tasks)
                print(
                    f"[queue-maint] applied: {len(swept)} unblocked, "
                    f"{len(gated)} live gate(s) retained, "
                    f"{len(escalated)} escalated (blocked_until backfilled + "
                    f"needs_adjudication), {n_compact} compacted to tombstones"
                )
            else:
                print(
                    f"[queue-maint] dry-run: would unblock {len(swept)}, "
                    f"{len(gated)} live gate(s) retained, "
                    f"would escalate {len(escalated)} (blocked w/o usable blocked_until), "
                    f"would compact {n_compact} (>{COMPACT_AGE_DAYS}d terminal)"
                )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    for s in swept:
        print(
            f"  - {s['id']} ({s['task_type']}) "
            f"reason={s['blocked_reason']} until={s['blocked_until']}"
        )
    for g in gated:
        print(
            f"  = {g['id']} ({g['task_type']}) "
            f"gate={g['unblock_gate']} retained: {g['gate_detail']}"
        )
    if escalated:
        print(
            f"[queue-maint] ESCALATE — {len(escalated)} blocked task(s) with no "
            "blocked_until. These can never be re-pended by the expiry sweep; "
            "each needs a human verdict (unblock / re-scope / close):"
        )
        for e in escalated:
            print(
                f"  ! {e['id']} ({e['task_type']}) "
                f"reason={e['blocked_reason']} — {e['detail']}"
                + (f" → until={e['assigned_until']}" if e["assigned_until"] else "")
            )
        warn(
            "queue_maint_blocked_until",
            "blocked task(s) with no blocked_until require adjudication",
            count=len(escalated),
            examples=[str(e["id"]) for e in escalated[:5]],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply=("--apply" in sys.argv)))
