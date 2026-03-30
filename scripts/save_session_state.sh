#!/bin/bash
# PreCompact hook: save session state before context is compressed
# This captures everything needed to resume work after compact/clear

cd /Users/yhlai0911/Desktop/volpred-research

STATE_FILE="storage/session_state.json"

python3 << 'PYEOF'
import json, subprocess, os
from datetime import datetime, timezone
from pathlib import Path

state = {
    "saved_at": datetime.now(timezone.utc).isoformat(),
    "reason": "pre-compact auto-save",
}

# 1. Recent git commits (what was done)
try:
    result = subprocess.run(["git", "log", "--oneline", "-30"], capture_output=True, text=True)
    state["recent_commits"] = result.stdout.strip().split("\n")[:30]
except:
    state["recent_commits"] = []

# 2. Knowledge count
try:
    k = json.load(open("storage/memory/knowledge.json"))
    state["knowledge_count"] = len(k)
    state["last_experiment"] = k[-1].get("id", "?") if k else "?"
except:
    state["knowledge_count"] = "?"

# 3. Uncommitted changes
try:
    result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True)
    state["uncommitted_files"] = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
except:
    state["uncommitted_files"] = "?"

# 4. Article pool status
try:
    with open("storage/reports/feed.json") as f:
        feed = json.load(f)
    items = feed if isinstance(feed, list) else feed.get("items", [])
    state["draft_count"] = sum(1 for a in items if isinstance(a, dict) and a.get("status") == "draft")
except:
    state["draft_count"] = "?"

# 5. Strategy metrics freshness
try:
    mtime = os.path.getmtime("storage/strategy_metrics.json")
    age_hours = (datetime.now().timestamp() - mtime) / 3600
    state["metrics_age_hours"] = round(age_hours, 1)
except:
    state["metrics_age_hours"] = "?"

# 6. Read research_program.md Next Session Priorities (first 30 lines)
try:
    with open("research_program.md") as f:
        content = f.read()
    idx = content.find("## Next Session Priorities")
    if idx >= 0:
        state["next_priorities"] = content[idx:idx+1500].strip()
except:
    state["next_priorities"] = "read research_program.md"

# 7. Pending events
state["pending_events"] = [
    "NFP 04/03 — post-event article template ready (mile_nfp_040326)",
    "TSMC 04/10 — pre-event article ready (mile_4d9dfebc)",
    "HAR-RV 5min 04/11 — SPY 51d, 0050 40d, need 60d",
    "TSMC earnings call 04/16",
]

# 8. Paper status
state["papers"] = {
    "leverage-direction": "52p, K628 trimmed, K585 partial fix",
    "taiwan-vt": "34p, K636 amplification resolved, TX cost corrected",
    "vt-trend-following": "29p, K585 all 6 fixes done",
    "volatility-absorption": "33p, 3 Codex reviews, NEAR-FINAL (4 minor residuals)",
}

# 9. Architecture state
state["architecture"] = [
    "evaluate_new_strategy.py: composite ranking (CAGR+Sharpe+Calmar+WinRate)",
    "recalc_metrics.py: auto-syncs to Supabase strategy_metrics_cache",
    "supabase_sync.py: reads only storage/reports/feed.json (storage/feed.json deprecated)",
    "Remote Trigger: platform-ops-patrol every 6h (trig_01HzWX2ZUmsGHnzwciGpHeNz)",
    "PreToolUse Hook: experiment lag/Codex reminder",
    "Strategy listing: 5 criteria (composite≥median, cross-OOS≥3/5, Codex, sensitivity, MDD<-20%)",
]

# 10. Key conclusions (don't re-derive these)
state["settled_conclusions"] = [
    "VIX predicts vol (0.57) NOT direction (0.04) — K697",
    "BH 50/50 SPY/GLD = best Sharpe (0.548) — K702",
    "VT = drawdown insurance for gamma>=5, not alpha — K687/K688",
    "Panic paralysis confirmed: endogenous absorbed, exogenous not — K716/K721",
    "No signal beats VIX for vol prediction — K710/K711",
    "Don't modify historical paper_trading data — K693 lesson",
    "Verify before publish, lag in code not memory — K679/K686 lesson",
]

with open("storage/session_state.json", "w") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print(json.dumps({"systemMessage": f"Session state saved: {state['knowledge_count']} knowledge, {state['last_experiment']} last experiment, {len(state['recent_commits'])} recent commits"}, ensure_ascii=False))
PYEOF
