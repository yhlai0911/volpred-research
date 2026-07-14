#!/usr/bin/env python3
"""Queue maintenance sweep for storage/next_tasks.json（每班 dispatch PRE-PHASE-0）.

兩項職責（同一 owner、同一把鎖 — anti-stacking）：

1. **Unblock expired**：blocked 且 blocked_until 已過期 → status="pending"，
   清 blocked_* 欄位並寫 status_history audit。
   Why: dispatcher (continue_task_dispatch.py:102) 只把 status=="pending" 當
   candidates；categorize() 的 blocked_until check 只 gate runtime dispatch，
   永遠不會把 status 翻回來 → 過期 blocked task 永遠進不了 agentable pool。

2. **Compact terminal**（2026-07-14 refactor_plan_token_ops_waste WS2a）：
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
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    compact_terminal_tasks,
    write_tasks_to_handle,
)

PATH = Path("storage/next_tasks.json")
ARCHIVE_DIR = Path("storage/next_tasks_archive")
BLOCKED_FIELDS = ("blocked_reason", "blocked_at", "blocked_until", "blocked_note")
# 3 天：唯一讀 recent-terminal 全文的 reader 是 generate_handoff 的
# recently_completed（24h 窗口，只用 completed_at/title）；其餘 reader 全部
# 只做 id 查重（tombstone 保留）。2026-07-14 實測 30 天窗口留下 1.96MB 殘量。
COMPACT_AGE_DAYS = 3


def _sweep_unblock(tasks: list, *, apply: bool) -> list[dict]:
    now = datetime.now(timezone.utc)
    swept: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if (t.get("status") or "").lower() != "blocked":
            continue
        until = t.get("blocked_until")
        if not until:
            continue
        # Strict ISO parsing still accepts the plain `YYYY-MM-DD` form. Invalid
        # blocked_until values must stay blocked; a lexical fallback can unblock
        # malformed metadata by accident.
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
        swept.append(
            {
                "id": t.get("id"),
                "task_type": t.get("task_type"),
                "blocked_reason": t.get("blocked_reason"),
                "blocked_until": until,
            }
        )
        if apply:
            t["status"] = "pending"
            t.setdefault("status_history", []).append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "from": "blocked",
                    "to": "pending",
                    "reason": f"blocked_until_expired ({until})",
                }
            )
            for k in BLOCKED_FIELDS:
                t.pop(k, None)
    return swept


def _persist_archive(archived: list[dict]) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m')}.jsonl"
    with dest.open("a", encoding="utf-8") as fh:
        for rec in archived:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
    return dest


def main(apply: bool) -> int:
    if not PATH.exists():
        print("[queue-maint] next_tasks.json missing; nothing to do")
        return 0
    with PATH.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.loads(fh.read() or "[]")
            if isinstance(tasks, dict):
                tasks = tasks.get("tasks", [])
            swept = _sweep_unblock(tasks, apply=apply)
            n_compact, archived = compact_terminal_tasks(tasks, age_days=COMPACT_AGE_DAYS)
            if apply:
                if archived:
                    dest = _persist_archive(archived)  # archive FIRST, queue second
                    print(f"[queue-maint] archived {n_compact} full records → {dest}")
                write_tasks_to_handle(fh, tasks)
                print(
                    f"[queue-maint] applied: {len(swept)} unblocked, "
                    f"{n_compact} compacted to tombstones"
                )
            else:
                print(
                    f"[queue-maint] dry-run: would unblock {len(swept)}, "
                    f"would compact {n_compact} (>{COMPACT_AGE_DAYS}d terminal)"
                )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    for s in swept:
        print(
            f"  - {s['id']} ({s['task_type']}) "
            f"reason={s['blocked_reason']} until={s['blocked_until']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply=("--apply" in sys.argv)))
