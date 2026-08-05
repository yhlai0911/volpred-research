#!/usr/bin/env python3
"""Claude 側每小時速率與併發 session 數（並行部門制 vs 單線程的對照基線）。"""
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

R = Path("/Users/yhlai0911/volpred-research")
sys.path.insert(0, str(R / "scripts"))
from token_usage_report import (  # noqa: E402
    _billable_total, _scan_jsonl, _deduplicated_turns, discover_claude_project_dirs,
)

TPE = timezone(timedelta(hours=8))
d0, d1 = date(2026, 7, 29), date(2026, 8, 6)
per = defaultdict(int)
sess = defaultdict(set)
seen = set()

for pd_ in discover_claude_project_dirs():
    srcs = [(p, False) for p in sorted(pd_.glob("*.jsonl"))]
    srcs += [(p, True) for p in sorted(pd_.glob("*/subagents/*.jsonl"))]
    for jp, isb in srcs:
        sid = jp.stem if not isb else jp.parent.parent.name + "/" + jp.stem
        recs = []
        for r in _scan_jsonl(jp, sid, isb, d0, d1):
            rid = r.get("record_id")
            if isinstance(rid, str) and rid:
                if rid in seen:
                    continue
                seen.add(rid)
            recs.append(r)
        for t in _deduplicated_turns(recs):
            ts = t.get("timestamp")
            if not ts:
                continue
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(TPE)
            k = (dt.date().isoformat(), dt.strftime("%H"))
            per[k] += _billable_total(t.get("usage") or {})
            sess[k].add(sid)

byday = defaultdict(list)
for (d, h), v in per.items():
    byday[d].append((h, v, len(sess[(d, h)])))

for d in sorted(byday):
    rows = sorted(byday[d])
    tot = sum(v for _, v, _ in rows)
    act = [r for r in rows if r[1] > 0]
    peak = max(rows, key=lambda r: r[1])
    maxc = max(rows, key=lambda r: r[2])
    print(f"{d} 全日 {tot:>10,}  活躍小時 {len(act):>2}  平均/活躍時 {tot // max(len(act), 1):>9,}  "
          f"尖峰 {peak[0]}時 {peak[1]:,}（{peak[2]} sess）  最高併發 {maxc[2]} sess（{maxc[0]}時）")
