#!/usr/bin/env python3
"""非 canonical 鏡像單的本文摘要（read-only），供逐筆判 disposition。"""
import json
import re
from pathlib import Path

INBOX = Path("storage/org/departments/platform_eng/inbox")
LIMIT = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 800
items = []
for p in sorted(INBOX.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    if re.match(r"【canonical 任務】", (d.get("task") or "").strip()):
        continue
    items.append(d)
items.sort(key=lambda d: d.get("created_at", ""))
print(f"# 非 canonical {len(items)} 件\n")
for i, d in enumerate(items, 1):
    t = (d.get("task") or "").strip().replace("\n\n", "\n")
    print(f"---[{i:02d}] {d.get('priority')} {d.get('kind')} from={d.get('from')} {d.get('id')}")
    if d.get("reply_to"):
        print(f"reply_to={d['reply_to']}")
    print(t[:LIMIT])
    print()
