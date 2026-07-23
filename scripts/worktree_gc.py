#!/usr/bin/env python3
"""Mechanical GC gate for agent worktrees — three gates, all must PASS.

Why this exists (boss directive 2026-07-21, assign_de13fd1b):
"worktree 回收要有機械 gate，不要再人工判斷". Every previous reclamation was a
human reading `git worktree list` and deciding. That is how k1709 lost three
revision commits and how docs/error_log.md 2026-07-19 got its entry:
**removing an unmerged checkout is how the next zombie gets made.**

A worktree is reclaimable ONLY if all three of these hold simultaneously:

  gate1 no_process   — no open file handle anywhere under the worktree path
                       (`lsof +D`). A live agent's checkout is never touched.
  gate2 no_unmerged  — `git rev-list --count <main>..<branch>` == 0. The branch
                       surviving is NOT the same as the work being harvested.
  gate3 no_open_task — no task in storage/next_tasks.json with an open status
                       (pending/claimed/in_progress) whose id/title/description
                       names this worktree. An open receipt means someone is
                       still owed this directory.

FAIL-CLOSED IS THE WHOLE POINT. Every gate treats "I could not determine this"
as BLOCK, never as PASS:
  - lsof times out or errors      -> gate1 BLOCK (assume a process holds it)
  - git rev-list fails / non-int  -> gate2 BLOCK (assume unmerged work exists)
  - next_tasks.json missing/bad   -> gate3 BLOCK (assume an open receipt exists)
There is no flag that turns this off. A gate that cannot run is a gate that
blocks, because the alternative is deleting someone's only copy.

This script only READS storage/next_tasks.json. It never writes it.

Usage:
    uv run python scripts/worktree_gc.py                    # dry-run table
    uv run python scripts/worktree_gc.py --json             # dry-run, machine
    uv run python scripts/worktree_gc.py --apply            # actually reclaim
    uv run python scripts/worktree_gc.py --exclude-task ID  # repeatable

`--exclude-task` exists for ONE mechanical reason: the task that orders the
cleanup necessarily names the worktrees it is cleaning up, so gate3 would
deadlock on itself. Excluding it is an explicit, logged operator statement
(the ids land in the JSON under `excluded_task_ids`), not a silent default.
Never use it to wave away a genuine receipt.

Reclamation is `git worktree remove` (NEVER --force; banned repo-wide by
CLAUDE.md and blocked by the L1 hook) followed by `git branch -d` (lowercase
-d, which itself refuses unmerged branches — gate2 belt, this suspenders).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

WORKTREES_DIR = REPO / ".claude" / "worktrees"
NEXT_TASKS = REPO / "storage" / "next_tasks.json"

#: Statuses that mean "someone is still owed this worktree".
OPEN_STATUSES = frozenset({"pending", "claimed", "in_progress"})

LSOF_TIMEOUT_S = 25
GIT_TIMEOUT_S = 30

PASS = "PASS"
BLOCK = "BLOCK"


def _gate(status: str, reason: str, **extra: Any) -> dict:
    return {"status": status, "reason": reason, **extra}


# ── gate 1: no process ──────────────────────────────────────────────────────


def gate_no_process(path: Path, *, timeout_s: int = LSOF_TIMEOUT_S) -> dict:
    """PASS only if we positively observed zero open handles under `path`.

    `lsof +D` walks the whole subtree and is slow on a big checkout, so it gets
    a timeout — and a timeout is BLOCK. Fail-open here would mean SIGKILLing a
    working agent's directory out from under it because the filesystem was busy
    (which is precisely when lsof is slow).
    """
    if not path.exists():
        return _gate(BLOCK, f"worktree 路徑不存在: {path}", holder_pids=[])
    try:
        proc = subprocess.run(
            ["lsof", "-t", f"+D{path}"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _gate(
            BLOCK,
            f"lsof 逾時（{timeout_s}s）— 無法證明無 process，保守判定為有 process（fail-closed）",
            holder_pids=None,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return _gate(
            BLOCK,
            f"lsof 執行失敗（{type(exc).__name__}: {exc}）— 無法證明無 process（fail-closed）",
            holder_pids=None,
        )

    # lsof exits 1 when nothing matches; that is a legitimate empty answer, so
    # returncode alone cannot distinguish "clean" from "broken". Anything other
    # than 0/1 is a real malfunction and must block.
    if proc.returncode not in (0, 1):
        return _gate(
            BLOCK,
            f"lsof 回傳非預期 exit={proc.returncode}（{proc.stderr.strip()[:120]}）"
            "— 無法證明無 process（fail-closed）",
            holder_pids=None,
        )

    pids = []
    for tok in proc.stdout.split():
        try:
            pid = int(tok)
        except ValueError:
            continue  # silent-ok: lsof warning line, not a pid
        if pid != os.getpid():
            pids.append(pid)
    pids = sorted(set(pids))
    if pids:
        return _gate(
            BLOCK,
            f"有 {len(pids)} 個 process 持有此 worktree 的檔案: {pids} — 活的，不可回收",
            holder_pids=pids,
        )
    return _gate(PASS, "無任何 process 持有此 worktree 的檔案", holder_pids=[])


# ── gate 2: no unmerged commits ─────────────────────────────────────────────


def gate_no_unmerged(branch: str | None, *, main_ref: str = "main") -> dict:
    """PASS only if `main_ref..branch` is provably empty.

    Any failure to compute it is BLOCK. docs/error_log.md 2026-07-19: keeping
    the branch is not harvesting the work, and a branch can vanish with its
    checkout. If we cannot count the commits we do not get to delete anything.
    """
    if not branch:
        return _gate(BLOCK, "讀不到 branch 名稱 — 無法確認是否已合併（fail-closed）",
                     unmerged_commits=None)
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "rev-list", "--count", f"{main_ref}..{branch}"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        )
    except subprocess.TimeoutExpired:
        return _gate(BLOCK, f"git rev-list 逾時（{GIT_TIMEOUT_S}s）— 無法確認是否已合併（fail-closed）",
                     unmerged_commits=None)
    except subprocess.CalledProcessError as exc:
        return _gate(
            BLOCK,
            f"git rev-list 失敗 exit={exc.returncode}（{(exc.stderr or '').strip()[:120]}）"
            "— 無法確認是否已合併（fail-closed）",
            unmerged_commits=None,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return _gate(BLOCK, f"git rev-list 執行失敗（{type(exc).__name__}: {exc}）（fail-closed）",
                     unmerged_commits=None)

    try:
        count = int(proc.stdout.strip())
    except ValueError:
        return _gate(
            BLOCK,
            f"git rev-list 輸出無法解析為數字: {proc.stdout.strip()[:60]!r}（fail-closed）",
            unmerged_commits=None,
        )
    if count > 0:
        return _gate(
            BLOCK,
            f"branch 有 {count} 個 commit 未進 {main_ref} — 先走 scripts/merge_worktree.sh 收割，"
            "移除未合併 checkout 就是製造下一個殭屍（docs/error_log.md 2026-07-19）",
            unmerged_commits=count,
        )
    return _gate(PASS, f"{main_ref}..{branch} 為 0，成果已全部進 {main_ref}", unmerged_commits=0)


# ── gate 3: no open receipt ─────────────────────────────────────────────────


def load_tasks(path: Path) -> list[dict]:
    """Read the task queue. Raises on anything unreadable — caller blocks."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("tasks", [])
    if not isinstance(data, list):
        raise ValueError(f"next_tasks.json 結構非 list: {type(data).__name__}")
    return [t for t in data if isinstance(t, dict)]


def gate_no_open_task(
    name: str,
    *,
    tasks_path: Path | None = None,
    tasks: list[dict] | None = None,
    exclude_task_ids: frozenset[str] | set[str] = frozenset(),
) -> dict:
    """PASS only if no open-status task names this worktree.

    `tasks` is accepted pre-loaded so a batch run reads the queue once; passing
    neither is a programming error, not a reason to pass the gate.
    """
    if tasks is None:
        path = tasks_path if tasks_path is not None else NEXT_TASKS
        try:
            tasks = load_tasks(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _gate(
                BLOCK,
                f"讀不到/解析不了 {path}（{type(exc).__name__}: {exc}）"
                "— 無法確認有無未結收件單（fail-closed）",
                open_tasks=None,
            )

    hits = []
    for task in tasks:
        if str(task.get("status") or "") not in OPEN_STATUSES:
            continue
        tid = str(task.get("id") or "")
        if tid in exclude_task_ids:
            continue
        haystack = " ".join(
            str(task.get(field) or "") for field in ("id", "title", "description")
        )
        if name in haystack:
            hits.append({"id": tid, "status": task.get("status"),
                         "title": str(task.get("title") or "")[:80]})
    if hits:
        listed = ", ".join(f"{h['id']}({h['status']})" for h in hits)
        return _gate(
            BLOCK,
            f"有 {len(hits)} 張未結收件單提及此 worktree: {listed} — 先收件再回收",
            open_tasks=hits,
        )
    return _gate(PASS, "無任何 pending/claimed/in_progress 收件單提及此 worktree",
                 open_tasks=[])


# ── worktree discovery ──────────────────────────────────────────────────────


def discover_worktrees() -> list[dict]:
    """All linked worktrees under .claude/worktrees, with their branches.

    Parsed from `git worktree list --porcelain` rather than from directory
    listing, so a stale directory git no longer tracks is not mistaken for a
    worktree (and a registered worktree is never missed).
    """
    out = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=True,
    ).stdout
    entries: list[dict] = []
    cur: dict = {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if cur.get("path"):
                entries.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur["path"] = val
        elif key == "branch":
            cur["branch"] = val.replace("refs/heads/", "", 1)
        elif key == "detached":
            cur["branch"] = None
    result = []
    for e in entries:
        path = Path(e["path"])
        if path.resolve() == REPO.resolve():
            continue  # the main checkout is never a GC candidate
        try:
            path.relative_to(WORKTREES_DIR)
        except ValueError:  # silent-ok: relative_to used as a predicate — "outside WORKTREES_DIR" is the answer, not an error
            continue  # not one of ours
        result.append({"name": path.name, "path": path, "branch": e.get("branch")})
    return sorted(result, key=lambda r: r["name"])


# ── evaluation + reclamation ────────────────────────────────────────────────


def evaluate(
    *,
    tasks_path: Path | None = None,
    exclude_task_ids: frozenset[str] | set[str] = frozenset(),
    main_ref: str = "main",
    worktrees: list[dict] | None = None,
) -> list[dict]:
    """Run all three gates over every worktree. Pure read-only."""
    wts = worktrees if worktrees is not None else discover_worktrees()
    path = tasks_path if tasks_path is not None else NEXT_TASKS
    try:
        tasks: list[dict] | None = load_tasks(path)
        tasks_error: str | None = None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        tasks, tasks_error = None, f"{type(exc).__name__}: {exc}"

    rows = []
    for wt in wts:
        if tasks is None:
            g3 = _gate(
                BLOCK,
                f"讀不到/解析不了 {path}（{tasks_error}）— 無法確認有無未結收件單（fail-closed）",
                open_tasks=None,
            )
        else:
            g3 = gate_no_open_task(wt["name"], tasks=tasks,
                                   exclude_task_ids=exclude_task_ids)
        gates = {
            "gate1_no_process": gate_no_process(Path(wt["path"])),
            "gate2_no_unmerged": gate_no_unmerged(wt["branch"], main_ref=main_ref),
            "gate3_no_open_task": g3,
        }
        blocked_by = [k for k, v in gates.items() if v["status"] != PASS]
        rows.append({
            "worktree": wt["name"],
            "path": str(wt["path"]),
            "branch": wt["branch"],
            "gates": gates,
            "reclaimable": not blocked_by,
            "blocked_by": blocked_by,
        })
    return rows


def _reclaim_one(row: dict) -> dict:
    """`git worktree remove` (no --force) + `git branch -d`. Never destructive
    beyond that: -d refuses an unmerged branch, so even a gate2 bug cannot lose
    commits here."""
    from volpred.ops.git_writer_lock import (
        git_writer_lock,
        git_writer_subprocess_kwargs,
    )

    outcome = {"removed": False, "branch_deleted": False, "error": None}
    with git_writer_lock(REPO, actor=f"worktree-gc:{row['worktree']}", timeout_s=30):
        try:
            subprocess.run(
                ["git", "-C", str(REPO), "worktree", "remove", row["path"]],
                capture_output=True, text=True, timeout=120, check=True,
                **git_writer_subprocess_kwargs(),
            )
            outcome["removed"] = True
        except subprocess.CalledProcessError as exc:
            outcome["error"] = (
                f"worktree remove 失敗（不使用 --force）: {(exc.stderr or '').strip()[:200]}"
            )
            return outcome
        except (subprocess.SubprocessError, OSError) as exc:
            outcome["error"] = f"worktree remove 失敗: {type(exc).__name__}: {exc}"
            return outcome

        if row.get("branch"):
            try:
                subprocess.run(
                    ["git", "-C", str(REPO), "branch", "-d", row["branch"]],
                    capture_output=True, text=True, timeout=60, check=True,
                    **git_writer_subprocess_kwargs(),
                )
                outcome["branch_deleted"] = True
            except subprocess.CalledProcessError as exc:
                # -d refused => something is unmerged after all. Keep the branch,
                # say so loudly; the checkout is gone but nothing is lost.
                outcome["error"] = (
                    f"branch -d 拒絕（可能仍有未合併 commit），branch 保留: "
                    f"{(exc.stderr or '').strip()[:200]}"
                )
            except (subprocess.SubprocessError, OSError) as exc:
                outcome["error"] = f"branch -d 失敗: {type(exc).__name__}: {exc}"
    return outcome


def run(
    *,
    apply: bool = False,
    tasks_path: Path | None = None,
    exclude_task_ids: frozenset[str] | set[str] = frozenset(),
    main_ref: str = "main",
) -> dict:
    rows = evaluate(tasks_path=tasks_path, exclude_task_ids=exclude_task_ids,
                    main_ref=main_ref)
    for row in rows:
        if not apply:
            row["action"] = "would_reclaim" if row["reclaimable"] else "skip"
            continue
        if not row["reclaimable"]:
            row["action"] = "skip"
            continue
        # Re-run the gates immediately before destroying anything: the dry-run
        # snapshot may be minutes old and a process can attach in between.
        recheck = evaluate(tasks_path=tasks_path, exclude_task_ids=exclude_task_ids,
                           main_ref=main_ref,
                           worktrees=[{"name": row["worktree"],
                                       "path": Path(row["path"]),
                                       "branch": row["branch"]}])
        if not recheck or not recheck[0]["reclaimable"]:
            row["action"] = "skip"
            row["recheck_blocked_by"] = recheck[0]["blocked_by"] if recheck else ["recheck_failed"]
            row["gates"] = recheck[0]["gates"] if recheck else row["gates"]
            row["reclaimable"] = False
            continue
        row["action"] = "reclaimed"
        row["result"] = _reclaim_one(row)
        if row["result"].get("error") and not row["result"].get("removed"):
            row["action"] = "skip"
    return {
        "apply": apply,
        "main_ref": main_ref,
        "excluded_task_ids": sorted(exclude_task_ids),
        "worktree_count": len(rows),
        "reclaimable_count": sum(1 for r in rows if r["reclaimable"]),
        "worktrees": rows,
    }


GATE_LABELS = {
    "gate1_no_process": "gate1 無 process",
    "gate2_no_unmerged": "gate2 無未合併",
    "gate3_no_open_task": "gate3 無未結收件單",
}


def print_table(report: dict) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"[worktree_gc] mode={mode}  worktrees={report['worktree_count']}  "
          f"reclaimable={report['reclaimable_count']}")
    if report["excluded_task_ids"]:
        print(f"  排除的 task id（操作者明示）: {', '.join(report['excluded_task_ids'])}")
    for row in report["worktrees"]:
        verdict = "RECLAIMABLE" if row["reclaimable"] else "HELD"
        print(f"\n── {row['worktree']}  [{verdict}]  branch={row['branch']}"
              f"  action={row.get('action')}")
        for key, label in GATE_LABELS.items():
            gate = row["gates"][key]
            print(f"   {gate['status']:5}  {label}: {gate['reason']}")
        if row.get("result"):
            print(f"   結果: {json.dumps(row['result'], ensure_ascii=False)}")
    if not report["apply"] and report["reclaimable_count"]:
        print("\n[dry-run] 加 --apply 才會實際回收（git worktree remove，禁 --force）")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="真的回收（預設 dry-run）")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="輸出 JSON 供其他腳本消費")
    ap.add_argument("--exclude-task", dest="exclude", action="append", default=[],
                    help="gate3 忽略此 task id（可重複；用於排除下令清理本身的 task）")
    ap.add_argument("--tasks", default=None,
                    help="收件單佇列路徑（預設 storage/next_tasks.json；測試用）")
    ap.add_argument("--main-ref", default="main", help="比較基準 ref（預設 main）")
    args = ap.parse_args()

    report = run(
        apply=args.apply,
        tasks_path=Path(args.tasks) if args.tasks else None,
        exclude_task_ids=frozenset(args.exclude),
        main_ref=args.main_ref,
    )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
