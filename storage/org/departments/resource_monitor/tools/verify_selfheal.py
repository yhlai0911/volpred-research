#!/usr/bin/env python3
"""(1) 今日 0 的根因驗證：現行程式碼明天會不會自己重產 daily_2026-08-05.json。

不預測，直接呼叫 planner 問它。
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from volpred.ops.summaries import build_token_usage_maintenance, _report_covers_its_period  # noqa: E402

p = Path("storage/reports/token_usage/daily_2026-08-05.json")
print("=== A. 完整性判定（現行程式碼，as_of=2026-08-06）===")
print("  _report_covers_its_period(daily_2026-08-05, 08-06) =",
      _report_covers_its_period(p, date(2026, 8, 6)))

print("\n=== B. 模擬明早 08:00 台灣（= 08-06T00:00Z）那班 maintain ===")
plan = build_token_usage_maintenance(target_date=date(2026, 8, 5))
for k in ("target_date", "action", "skip", "daily_report_exists",
          "weekly_due", "weekly_report_exists"):
    print(f"  {k} = {plan.get(k)}")
print("  recommended_actions =", plan.get("recommended_actions"))
print("  execution_commands =", plan.get("execution_commands"))

print("\n=== C. 對照：今天這班（target=08-04，現行程式碼）===")
plan2 = build_token_usage_maintenance(target_date=date(2026, 8, 4))
print("  action =", plan2.get("action"), "| daily_report_exists =",
      plan2.get("daily_report_exists"))

print("\n=== D. weekly cap 的來源（(2) 儀表混用查證）===")
wq = Path("scripts/weekly_quota_estimate.py").read_text(encoding="utf-8")
import re
for m in re.finditer(r"^.*(cap|CAP|quota|QUOTA|allowance).*$", wq, re.M):
    line = m.group(0).strip()
    if line.startswith("#") or "=" in line or "def " in line:
        print("   ", line[:130])
