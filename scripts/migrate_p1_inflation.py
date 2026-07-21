#!/usr/bin/env python3
"""migrate_p1_inflation — 存量 P1 通膨一次性遷移（2026-07-21 dispatch-lanes R3）。

R2 讓 gateway（`append_task_record`）對**新入池**的機器來源 P1 夾到 P2；本 script
把**已在池內**的存量比照同一判定夾平 —— 不清存量的話，boss 急件仍要在 25 張
generator 自封的 P1 後面排隊（R1 的 lane rank 雖已保證 urgent 先派，但 scheduled
lane 內的 priority 語意仍是壞的：餓死保護 / 排序 / 報表全都把假 P1 當真 P1）。

判定與 R2 **同一個函數**（`volpred.ops.next_tasks.clamp_machine_priority_inflation`
—— 內部全部重用 `task_urgency` 的常數，無第二套 source 清單）：

* boss 來源（telegram/user/owner/boss token）→ 不動
* 時效 task_type（event_article / trending_repost / daily_digest）→ 不動
* dedicated-owner ingress（email_reply / telegram_reply）→ 不動
* 其餘 pending P1 → 夾到 2 + ``priority_capped_from: 1`` + ``migrated_at``

**只改 priority 欄位**（外加上面兩個 audit stamp）；status / claim / blocked 等
狀態機欄位一概不碰。寫入走 canonical 寫入路徑（同 gateway：LOCK_EX 持鎖跨
load+mutate，`write_tasks_to_handle` serialize-first）。冪等：夾過的已是 P2，
重跑第二次零變更。

⚠️ 不在 worktree 內對 canonical pool 實跑 —— 主線程 merge 後執行：

    uv run python scripts/migrate_p1_inflation.py --dry-run   # 先看清單
    uv run python scripts/migrate_p1_inflation.py             # 實際夾平

遷移清單同時輸出 stdout（JSON）與 receipt 檔
``storage/ops/p1_inflation_migration_<UTC日期>.json``（零變更時不寫檔，
避免同日重跑覆蓋掉真正的遷移紀錄）。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    clamp_machine_priority_inflation,
    write_tasks_to_handle,
)

DEFAULT_TASKS = ROOT / "storage" / "next_tasks.json"


def migrate(path: Path, *, dry_run: bool = False) -> dict:
    """套 R2 判定於 pending 存量；回傳 {migrated: [...], total_pending_p1_kept: n}。"""
    guard_canonical_write(path)
    now_iso = datetime.now(timezone.utc).isoformat()
    migrated: list[dict] = []
    kept_p1 = 0
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # same lock every queue writer takes
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise ValueError(f"{path} root is not a list")
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                if (task.get("status") or "").lower() != "pending":
                    continue
                if clamp_machine_priority_inflation(task):
                    task["migrated_at"] = now_iso
                    migrated.append(
                        {
                            "id": task.get("id"),
                            "title": (task.get("title") or "")[:120],
                            "source": task.get("source"),
                            "task_type": task.get("task_type"),
                        }
                    )
                elif task.get("priority") in (1, "1", "P1"):
                    kept_p1 += 1
            if migrated and not dry_run:
                write_tasks_to_handle(fh, tasks)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return {
        "migrated_at": now_iso,
        "dry_run": dry_run,
        "tasks_path": str(path),
        "migrated_count": len(migrated),
        "kept_p1_count": kept_p1,  # boss / time-critical / dedicated-owner 保留的真 P1
        "migrated": migrated,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="存量機器 P1 → P2 一次性遷移（R3）")
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS), help="task pool 路徑（測試用 override）")
    ap.add_argument("--out", default=None,
                    help="receipt JSON 路徑（預設 storage/ops/p1_inflation_migration_<日期>.json）")
    ap.add_argument("--dry-run", action="store_true", help="只列清單，不寫池、不寫 receipt")
    args = ap.parse_args(argv)

    path = Path(args.tasks)
    if not path.exists():
        print(f"[migrate_p1_inflation] tasks file not found: {path}", file=sys.stderr)
        return 1
    summary = migrate(path, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if summary["migrated"] and not args.dry_run:
        out = Path(args.out) if args.out else (
            ROOT / "storage" / "ops"
            / f"p1_inflation_migration_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[migrate_p1_inflation] receipt written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
