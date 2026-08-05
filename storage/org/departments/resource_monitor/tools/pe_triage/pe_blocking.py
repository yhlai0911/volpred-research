#!/usr/bin/env python3
"""(a) still_actionable 的 blocking_on 分類（機械規則，可複驗）＋ item 09 的證據補驗。

規則（保守、逐字比對，不猜語意）：
  zone_a        — 文字出現 src/volpred/ 或 supabase/migrations 或 scripts/dispatch_supervisor
  awaiting_boss — 文字出現 老闆核准／請老闆／等老闆／approve／授權老闆
  unblocked     — 其餘（platform_eng 已擁有 config/ scripts/ tests/ frontend-v2-fix/）
zone_a 與 awaiting_boss 同時命中時取 zone_a（機械禁區優先於人的核准）。
"""
import json
import re
from pathlib import Path

INBOX = Path("storage/org/departments/platform_eng/inbox")
ACTIONABLE = set("""
item_20260805T074417886798Z item_20260805T074725725563Z item_20260805T084057987085Z
item_20260805T084221595527Z item_20260805T090056509920Z item_20260805T093217798679Z
item_20260805T094148149003Z item_20260805T100532370603Z item_20260805T100546390989Z
item_20260805T100607105976Z item_20260805T101120748271Z item_20260805T101958376601Z
item_20260805T102123189092Z item_20260805T102432346800Z item_20260805T110315022042Z
item_20260805T110522567776Z item_20260805T110609309419Z item_20260805T110622123356Z
item_20260805T110947158509Z item_20260805T110947440403Z item_20260805T111505681611Z
item_20260805T111527078096Z item_20260805T111650705093Z item_20260805T111959791797Z
item_20260805T112038226719Z item_20260805T130317364814Z
""".split())

ZONE_A = re.compile(r"src/volpred/|supabase/migrations|scripts/dispatch_supervisor")
BOSS = re.compile(r"老闆核准|請老闆|等老闆|老闆授權|授權老闆|approve\b")

buckets = {"zone_a": [], "awaiting_boss": [], "unblocked": []}
canon = []
for p in sorted(INBOX.glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    iid = d["id"]
    task = d.get("task") or ""
    is_canon = task.strip().startswith("【canonical 任務】")
    if not is_canon and iid.split("_")[0] + "_" + iid.split("_")[1] not in ACTIONABLE:
        continue
    key = "zone_a" if ZONE_A.search(task) else ("awaiting_boss" if BOSS.search(task) else "unblocked")
    (canon if is_canon else buckets[key]).append((iid, key, task.strip().splitlines()[0][:60]))
    if is_canon:
        buckets[key].append((iid, key, "[canonical] " + task.strip().splitlines()[0][:50]))

print("=== (a) still_actionable 的 blocking_on 分佈 ===")
for k, v in buckets.items():
    print(f"{k:<14} {len(v)}")
print("總計", sum(len(v) for v in buckets.values()), "（其中 canonical 鏡像", len(canon), "）")
for k, v in buckets.items():
    print(f"\n--- {k} ---")
    for iid, _, head in v:
        print("  ", iid[:40], head)

print("\n=== item 09 補驗：paper-workflow.md 是否仍列 taiwan-vt 為樣板 ===")
txt = Path(".claude/rules/paper-workflow.md").read_text(encoding="utf-8")
for i, ln in enumerate(txt.splitlines(), 1):
    if "taiwan-vt" in ln:
        print(f"  L{i}: {ln[:160]}")
print("  全檔 taiwan-vt 出現次數:", txt.count("taiwan-vt"))
