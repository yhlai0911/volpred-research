#!/usr/bin/env python3
"""把 platform_eng 收件匣的『canonical 任務』鏡像單對回 storage/next_tasks.json 的狀態。

這是 (c) already_done / (d) obsolete 的機器證據來源：鏡像單本身不是工作，
真相在任務池。
"""
import json
import re
from pathlib import Path

INBOX = Path("storage/org/departments/platform_eng/inbox")
pool = json.loads(Path("storage/next_tasks.json").read_text(encoding="utf-8"))
tasks = pool if isinstance(pool, list) else pool.get("tasks", pool.get("items", []))
print("task pool 型別:", type(pool).__name__, "筆數:", len(tasks))
if tasks:
    print("欄位樣本:", sorted(tasks[0].keys())[:20])

by_title = {}
for t in tasks:
    title = (t.get("title") or t.get("task") or t.get("description") or "").strip()
    by_title[title] = t

rows = []
for p in sorted(INBOX.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    task = (d.get("task") or "")
    m = re.match(r"【canonical 任務】(.+)", task.strip())
    if not m:
        continue
    title = m.group(1).strip().splitlines()[0].strip()
    # canonical_task_id 若有直接用
    cid = d.get("canonical_task_id")
    hit = None
    if cid:
        hit = next((t for t in tasks if t.get("id") == cid or t.get("task_id") == cid), None)
    if hit is None:
        hit = by_title.get(title)
    if hit is None:
        cand = [t for t in tasks
                if title[:40] and title[:40] in (t.get("title") or t.get("task") or "")]
        hit = cand[0] if len(cand) == 1 else None
    rows.append((d["id"], title[:70], cid,
                 (hit or {}).get("id") or (hit or {}).get("task_id"),
                 (hit or {}).get("status"), (hit or {}).get("assignee") or (hit or {}).get("owner")))

print(f"\n=== {len(rows)} 件 canonical 鏡像單 ===")
for i, (iid, title, cid, tid, status, owner) in enumerate(rows, 1):
    print(f"{i:02d} status={str(status):<14} pool_id={str(tid)[:24]:<24} {title}")
    print(f"   inbox={iid}  canonical_task_id={cid}")
