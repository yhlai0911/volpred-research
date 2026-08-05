#!/usr/bin/env python3
"""platform_eng 收件匣 read-only 索引：欄位 + 首行 + 引用到的 id/commit/path。"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

INBOX = Path("storage/org/departments/platform_eng/inbox")
now = datetime.now(timezone.utc)
rows = []
for p in sorted(INBOX.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    task = (d.get("task") or "").strip()
    created = d.get("created_at", "")
    try:
        age = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 86400
    except ValueError:
        age = -1
    refs = set(re.findall(r"item_2026\d{4}T\d{6}\w{6}Z", task))
    shas = set(re.findall(r"\b[0-9a-f]{7,40}\b", task))
    shas = {s for s in shas if not s.isdigit()}
    rows.append({
        "id": d.get("id"), "from": d.get("from"), "kind": d.get("kind"),
        "pri": d.get("priority"), "created": created, "age_d": round(age, 1),
        "reply_to": d.get("reply_to"), "task": task,
        "refs": sorted(refs), "shas": sorted(shas)[:4],
        "head": " / ".join(task.splitlines()[:2])[:230],
    })

rows.sort(key=lambda r: r["created"])
print(f"# {len(rows)} 件\n")
for i, r in enumerate(rows, 1):
    print(f"[{i:02d}] {str(r['pri']):<3} {str(r['kind']):<10} from={str(r['from']):<16} age={r['age_d']:>5}d {r['id']}")
    print(f"     {r['head']}")
    if r["refs"]:
        print(f"     refs={r['refs']}")
    if r["reply_to"]:
        print(f"     reply_to={r['reply_to']}")
    print()
