#!/usr/bin/env python3
"""FB pipeline audit: detect stale fb_post_status pending > 24h.

Cron: every 6h. Alert if pending stale count >= 2.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

REPO = Path(__file__).parent.parent
LOG = REPO / "storage" / "reports" / "trending_repost_log.json"
STALE_HOURS = 24


def main():
    if not LOG.exists():
        print(json.dumps({"audit": "fb_pipeline", "skip": "no log"}))
        return 0
    data = json.loads(LOG.read_text())
    now = time.time()
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - STALE_HOURS * 3600))
    pending = []
    for e in data:
        s = e.get("fb_post_status", "")
        if s in ("success", "wont_fix", "fb_silent_reject"):
            continue
        created = e.get("date") or e.get("created_at") or e.get("timestamp", "")
        if created and created < cutoff_iso:
            pending.append({
                "mile_id": e.get("mile_id"),
                "fb_post_status": s,
                "date": created,
                "has_draft": bool(e.get("fb_post_draft") or e.get("fb_draft")),
            })
    report = {
        "audit": "fb_pipeline",
        "stale_hours": STALE_HOURS,
        "stale_pending_count": len(pending),
        "stale_pending": pending,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if len(pending) >= 2:
        body = (
            f"## 觸發條件\nFB pipeline 累積 {len(pending)} 篇 stale pending > {STALE_HOURS}h\n"
            + "\n".join(f"- {p['mile_id']} status={p['fb_post_status']} has_draft={p['has_draft']}" for p in pending)
            + "\n\n## 影響\nMission 5 (曝光) FB 同步漏接 → 讀者 funnel 入口少一段\n\n"
            "## 建議行動\n1. 跑 trending_repost handoff doc paste\n2. 或 retry MCP FB push（先確認 ext consent 不卡）\n3. 結構性：把 FB push 加進 publish-verifier 才結案"
        )
        try:
            from src.volpred.ops.alerts import send_alert
            send_alert(level="warn", title=f"FB pipeline stale: {len(pending)} pending >24h", body=body)
        except Exception as e:
            print(f"alert send failed: {e}", file=sys.stderr)
    return 0 if not pending else 1


if __name__ == "__main__":
    sys.exit(main())
