#!/usr/bin/env python3
"""Clean up worktrees that stopped making progress. HYGIENE, not capacity.

Capacity is already handled: `dispatch_slot_budget.occupancy()` stops counting a
stale worktree the moment it goes quiet, so the dispatcher is unblocked whether
or not this script ever runs. That separation is deliberate — reclaiming capacity
must not depend on a destructive cleanup succeeding. What this script does is
stop the hung agent from burning CPU/RAM and get the directory out of the way.

Staleness is defined in one place (`dispatch_slot_budget.STALE_HOURS`, measured
by progress, not by process liveness — the 2026-07-13 zombies both had live
processes and zero output for two days).

Safety rules, in order:
  - The branch is ALWAYS preserved. Every worktree is a git branch; removing the
    checkout throws nothing away, and the work is recoverable via the branch.
  - A DIRTY worktree is never removed. Uncommitted work is work. It is reported
    and left alone for a human/main-thread decision.
  - An UNMERGED worktree is never removed either. Committed-but-unmerged work is
    also work, and the surviving branch is not a harvest — k1709 proved a branch
    can vanish with its checkout and strand the task pointing at it. Those are
    routed to merge_worktree.sh instead.
  - `git worktree remove --force` is BANNED repo-wide (CLAUDE.md) and is not
    used here, not even as a fallback.
  - Default is dry-run. `--apply` is required to kill or remove anything.

Detection alone is not landing (WS-I, 2026-07-20): a held worktree (dirty or
unmerged) used to surface only as a ``skipped`` line in a dry-run nobody was
scheduled to read, so 16 worktrees accumulated up to 138h of stranded work
(k1380's only valid results sat uncommitted in agent-a6325a478bff05509 while
main carried the INVALID copy). ``--open-tasks`` is the actuator: every held
worktree becomes ONE idempotent adjudication task (``worktree_salvage_<name>``,
P3, main_thread lane) in the pending queue, so the merge/salvage/discard
decision reaches a decision-maker instead of dying in a log. This is also the
mandated exit path for the merge-certify gate: a worktree whose merge was
refused (no verdict / FAIL / sha drift) stays held here until someone rules on
it — blocked, but never silently parked forever.

Usage:
    uv run python scripts/reclaim_stale_worktrees.py            # dry-run
    uv run python scripts/reclaim_stale_worktrees.py --apply
    uv run python scripts/reclaim_stale_worktrees.py --open-tasks
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from volpred.ops import termination  # noqa: E402
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import dispatch_slot_budget as slot_budget  # noqa: E402

from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.git_writer_lock import (  # noqa: E402
    git_writer_lock,
    git_writer_subprocess_kwargs,
)
from volpred.ops.remediation_throttle import (  # noqa: E402
    INCIDENT_ADJUDICATION_SOURCE,
)


def _holder_pids(worktree: Path) -> list[int]:
    """PIDs whose cwd is inside this worktree."""
    try:
        out = subprocess.run(
            ["lsof", "-t", "-a", "-d", "cwd", f"+D{worktree}"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        warn("reclaim", f"lsof 失敗 {worktree.name} ({exc}) — 當作無持有 process")
        return []
    pids = []
    for line in out.split():
        try:
            pids.append(int(line))
        except ValueError:
            continue  # silent-ok: lsof noise line, not a pid
    return [p for p in pids if p != os.getpid()]


def _is_dirty(worktree: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True, text=True, timeout=20, check=True,
            **git_writer_subprocess_kwargs(),
        ).stdout.strip()
        return bool(out)
    except (subprocess.SubprocessError, OSError) as exc:
        # Fail closed: if we cannot prove it is clean, we do not touch it.
        warn("reclaim", f"git status 失敗 {worktree.name} ({exc}) — 保守視為 dirty，不移除")
        return True


def _unmerged_count(branch: str | None) -> int:
    """Commits on `branch` that main does not have yet.

    Preserving the branch is NOT the same as harvesting the work. k1709 was a
    clean worktree whose branch held 3 revision commits; the checkout went away,
    the ref went away with it, and the task pointing at it sat blocked forever
    with no mechanism to notice (2026-07-19 boss report). A clean tree only
    proves nothing is uncommitted — it says nothing about whether those commits
    ever reached main. Removing an unmerged checkout is how the next zombie gets
    made, so it is gated here and routed to merge_worktree.sh instead.
    """
    if not branch:
        return 0
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-list", "--count", f"HEAD..{branch}"],
            capture_output=True, text=True, timeout=20, check=True,
            **git_writer_subprocess_kwargs(),
        ).stdout.strip()
        return int(out or 0)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        # Fail closed, same posture as _is_dirty: unprovable => do not touch.
        warn("reclaim", f"rev-list 失敗 {branch} ({exc}) — 保守視為有未合併 commits，不移除")
        return -1


def _unmerged_reason(unmerged: int) -> str:
    if unmerged < 0:
        return "無法判定是否已合併 — 保守保留（fail closed）"
    return (
        f"unmerged — branch 有 {unmerged} 個 commits 未進 main；"
        "先走 merge_worktree.sh 收割再回收（保留 branch 不等於收割成果）"
    )


def _branch_of(worktree: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
            **git_writer_subprocess_kwargs(),
        ).stdout.strip() or None
    except (subprocess.SubprocessError, OSError) as exc:
        warn("reclaim", f"讀不到 {worktree.name} 的 branch ({exc})")
        return None


def reclaim(apply: bool) -> dict:
    results = []
    for wt in slot_budget.worktree_slots():
        if wt["live"]:
            continue

        path = slot_budget.WORKTREES_DIR / wt["name"]
        branch = _branch_of(path)
        dirty = _is_dirty(path)
        pids = _holder_pids(path)
        unmerged = _unmerged_count(branch)
        action = {
            "worktree": wt["name"],
            "branch": branch,
            "idle_hours": wt["idle_hours"],
            "dirty": dirty,
            "unmerged_commits": unmerged,
            "holder_pids": pids,
            "killed": [],
            "removed": False,
        }

        if dirty and not apply:
            action["skipped"] = "dirty — 有未提交工作，保留待人工裁決"
            results.append(action)
            continue

        if unmerged != 0 and not apply:
            action["skipped"] = _unmerged_reason(unmerged)
            results.append(action)
            continue

        if apply:
            with git_writer_lock(
                REPO, actor=f"reclaim-worktree:{wt['name']}", timeout_s=30
            ):
                # Re-evaluate every destructive precondition inside the same
                # lease as common-dir metadata removal.
                branch = _branch_of(path)
                dirty = _is_dirty(path)
                pids = _holder_pids(path)
                unmerged = _unmerged_count(branch)
                action.update(
                    branch=branch, dirty=dirty, holder_pids=pids,
                    unmerged_commits=unmerged,
                )
                if dirty:
                    action["skipped"] = "dirty — 有未提交工作，保留待人工裁決"
                    results.append(action)
                    continue
                if unmerged != 0:
                    action["skipped"] = _unmerged_reason(unmerged)
                    results.append(action)
                    continue
                for pid in pids:
                    try:
                        intent = termination.arm(
                            target_kind="pid", target_id=pid,
                            reason="stale_worktree_holder_reclaim",
                            actor="reclaim_stale_worktrees",
                            signal_sequence=[signal.SIGTERM],
                        )
                        termination.send_pid(intent, signal.SIGTERM)
                        action["killed"].append(pid)
                    except OSError as exc:
                        warn("reclaim", f"kill {pid} 失敗 ({exc}) — worktree 仍會嘗試移除")
                try:
                    # No --force, ever (CLAUDE.md hard rule). Clean tree => plain remove
                    # succeeds; the branch survives, so nothing is lost.
                    subprocess.run(
                        ["git", "-C", str(REPO), "worktree", "remove", str(path)],
                        capture_output=True, text=True, timeout=60, check=True,
                        **git_writer_subprocess_kwargs(),
                    )
                    action["removed"] = True
                except subprocess.CalledProcessError as exc:
                    action["skipped"] = f"worktree remove 失敗（不 --force）: {exc.stderr.strip()[:160]}"
                except (subprocess.SubprocessError, OSError) as exc:
                    action["skipped"] = f"worktree remove 失敗: {exc}"

        results.append(action)

    return {"apply": apply, "stale_count": len(results), "actions": results}


SALVAGE_INCIDENT_KIND = "worktree_unmerged"


def _is_held(action: dict) -> bool:
    """Held = this worktree carries work the reclaimer refuses to touch."""
    return bool(action.get("dirty")) or action.get("unmerged_commits", 0) != 0


def _build_aggregate_salvage_task(*, incident_id: str, episode: int,
                                  task_id: str, now_iso: str) -> dict:
    """ONE adjudication task per incident episode, never one per worktree.

    The per-worktree ``worktree_salvage_<name>`` shape was plan §2.3's
    per-instance bug: 19 tasks with zero duplicates and one root cause.  The
    held worktrees now live as instances of the single ``worktree_unmerged``
    incident; this task is the batch adjudication exit.
    """
    return {
        "id": task_id,
        "task_type": "platform_ops",
        "priority": 3,
        "source": INCIDENT_ADJUDICATION_SOURCE,
        "status": "pending",
        "dispatch_lane": "main_thread",
        "incident_id": incident_id,
        "created_at": now_iso,
        "created_by": "reclaim_stale_worktrees",
        "title": f"worktree 產物批次裁決（worktree_unmerged，episode {episode}）",
        "description": (
            "一個或多個 stale worktree 持有未落地成果，reclaim 依 fail-closed 規則"
            f"不動它們。全部未清實例見 `storage/ops/incidents.json` 的 `{incident_id}` "
            "row（instances[] 中 cleared_at 為空者）。這單是批次裁決出口，逐實例三選一，"
            "不准放著：\n"
            "1. merge：成果完整（實驗須有 review_verdict.json PASS）→ 主線程 cd 回主 repo 後 "
            "`bash scripts/merge_worktree.sh <name>`；\n"
            "2. salvage：branch 不能整包進（審查 FAIL / 混入雜物）但有可救檔 → "
            "path-scoped 抽取需要的檔（memory feedback_worktree_stale_base_extract_by_path），"
            "抽完按 3 收尾；\n"
            "3. discard：判定無可救援（寫明理由）→ commit/丟棄 dirty 檔後走 "
            "`git worktree remove`（禁 --force）+ 保留 branch。\n"
            "裁決寫進本 task 的 result；worktree 消失後下次 reclaim 會自動 clear 對應 "
            "instance。來源：scripts/reclaim_stale_worktrees.py --open-tasks（WS-I / "
            "incident-lifecycle P3）。"
        ),
    }


def open_salvage_tasks(results: dict, *, queue_path: Path | None = None) -> list[dict]:
    """Actuator: held-worktree findings → ONE aggregate adjudication task.

    Each held worktree registers as an instance of the ``worktree_unmerged``
    incident (plan §3.3); the incident carries at most one aggregate task per
    episode.  Instances whose worktree directory no longer exists are cleared
    here (reconciliation), so the incident can resolve once everything is
    adjudicated and quiet for 24h.  Failures are loud (no-silent-fallback).
    """
    from datetime import datetime, timezone

    from volpred.ops import incident as incident_store
    from volpred.ops.next_tasks import append_task_record

    path = queue_path if queue_path is not None else REPO / "storage" / "next_tasks.json"
    store = path.parent / "ops" / "incidents.json"
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    receipts: list[dict] = []

    held_names = {
        a["worktree"] for a in results.get("actions", []) if _is_held(a)
    }
    for action in results.get("actions", []):
        if not _is_held(action):
            continue
        name = action["worktree"]
        receipt: dict = {"worktree": name}
        try:
            outcome = incident_store.route_breach(
                store,
                kind=SALVAGE_INCIDENT_KIND,
                instance_key=name,
                instance_detail={
                    "branch": action.get("branch"),
                    "idle_hours": action.get("idle_hours"),
                    "dirty": action.get("dirty"),
                    "unmerged_commits": action.get("unmerged_commits"),
                },
                details=f"held worktree {name}",
                now=now,
                task_status_probe=incident_store.next_tasks_status_probe(path),
            )
            receipt["incident_id"] = outcome.get("incident_id")
            receipt["action"] = outcome.get("action")
            if outcome["action"] == "escalate":
                esc = incident_store.actuate_escalation(
                    store, str(outcome["incident_id"]), queue_path=path, now=now
                )
                receipt["task_id"] = esc.get("root_cause_task_id")
                receipt["created"] = bool(esc.get("task_created"))
            elif outcome["action"] == "create_task":
                task = _build_aggregate_salvage_task(
                    incident_id=str(outcome["incident_id"]),
                    episode=int(outcome.get("episode_count") or 0),
                    task_id=str(outcome["suggested_task_id"]),
                    now_iso=now_iso,
                )
                stored, created = append_task_record(task, path=path, if_exists="skip")
                if stored.get("throttled_by_remediation_cap"):
                    incident_store.record_throttled(
                        store, str(outcome["incident_id"]), now=now
                    )
                    receipt["created"] = False
                    receipt["throttled"] = True
                else:
                    incident_store.bind_task(
                        store, str(outcome["incident_id"]), str(stored.get("id")), now=now
                    )
                    receipt["task_id"] = stored.get("id")
                    receipt["created"] = created
            else:
                receipt["task_id"] = outcome.get("active_task_id")
                receipt["created"] = False
        except Exception as exc:  # noqa: BLE001 — 一實例失敗不擋其他實例，但必留 trace
            warn(
                "reclaim_salvage",
                f"incident routing 失敗 {name} ({type(exc).__name__}: {exc})",
            )
            receipt["created"] = False
            receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipts.append(receipt)

    _reconcile_cleared_instances(store, now=now, currently_held=held_names)
    return receipts


def _reconcile_cleared_instances(store: Path, *, now, currently_held: set[str]) -> None:
    """Instances whose worktree directory is gone have been adjudicated."""
    from volpred.ops import incident as incident_store

    row = incident_store.load_incident(
        store, incident_store.incident_id_for(SALVAGE_INCIDENT_KIND)
    )
    if not row:
        return
    for inst in row.get("instances") or []:
        key = str(inst.get("key") or "")
        if not key or inst.get("cleared_at") or key in currently_held:
            continue
        if not (slot_budget.WORKTREES_DIR / key).exists():
            try:
                incident_store.clear_instance(
                    store,
                    kind=SALVAGE_INCIDENT_KIND,
                    instance_key=key,
                    now=now,
                    by="reclaim_reconcile",
                )
            except Exception as exc:  # noqa: BLE001 — bookkeeping; next pass retries
                warn("reclaim_salvage", f"clear_instance 失敗 {key} ({exc})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的 kill + remove（預設 dry-run）")
    ap.add_argument(
        "--open-tasks",
        action="store_true",
        help="對每個 held（dirty/unmerged）worktree 冪等開一張 P3 裁決任務",
    )
    ap.add_argument(
        "--queue",
        default=None,
        help="salvage task 佇列路徑（預設 canonical storage/next_tasks.json；測試/驗證用）",
    )
    args = ap.parse_args()
    out = reclaim(apply=args.apply)
    if args.open_tasks:
        out["salvage_tasks"] = open_salvage_tasks(
            out, queue_path=Path(args.queue) if args.queue else None
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.apply and out["stale_count"]:
        print("\n[dry-run] 加 --apply 才會實際 kill + remove（branch 一律保留）")


if __name__ == "__main__":
    main()
