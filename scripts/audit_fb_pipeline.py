#!/usr/bin/env python3
"""FB pipeline audit: detect stale fb_post_status > 24h + auto-expire >72h awaiting.

Cron: every 6h. Alert if stale count >= 2.

2026-06-03 改寫（email-11939 用戶抱怨「FB 一直發不出去」根因追蹤）：
- awaiting_interactive_session 從 TERMINAL set 拿掉 — 它不是 terminal，是「無限期等」
  → 之前 4 篇 5/29-6/01 連續 4 天卡這狀態，audit 0 alert，dashboard 沒抓到
- awaiting >72h 自動降為 expired_skip（時效已過，補發無 ROI）
- 仍 awaiting >24h 計入 stale_pending，觸發 alert
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).parent.parent
LOG = REPO / "storage" / "reports" / "trending_repost_log.json"
STALE_HOURS = 24
AUTO_EXPIRE_HOURS = 72
TERMINAL_STATUSES = {
    "success",
    "wont_fix",
    "fb_silent_reject",
    "expired_skip",
}
HANDOFF_STATUSES = {
    "awaiting_interactive_session",
}


def _auto_expire_stale_awaiting(data: list, expire_cutoff_iso: str) -> list[dict]:
    """awaiting_interactive_session > 72h → auto-mark expired_skip。回傳被處理的條目清單。"""
    expired = []
    for e in data:
        s = str(e.get("fb_post_status", "")).strip().lower()
        if s != "awaiting_interactive_session":
            continue
        created = e.get("date") or e.get("created_at") or e.get("timestamp", "")
        if not created or created >= expire_cutoff_iso:
            continue
        mile_id = e.get("mile_id")
        if not mile_id:
            continue
        try:
            subprocess.run(
                [
                    "uv", "run", "python", "scripts/mark_fb_post_status.py",
                    "--mile-id", mile_id,
                    "--status", "expired_skip",
                    "--note", f"auto-expired by audit_fb_pipeline (>{AUTO_EXPIRE_HOURS}h awaiting, time-value lost)",
                ],
                cwd=REPO, check=True, capture_output=True,
            )
            expired.append({"mile_id": mile_id, "date": created})
        except Exception as exc:
            print(f"auto-expire failed for {mile_id}: {exc}", file=sys.stderr)
    return expired


def main():
    if not LOG.exists():
        print(json.dumps({"audit": "fb_pipeline", "skip": "no log"}))
        return 0
    data = json.loads(LOG.read_text())
    now = time.time()
    stale_cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - STALE_HOURS * 3600))
    expire_cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - AUTO_EXPIRE_HOURS * 3600))

    # 1) Auto-expire awaiting >72h（不再無限期等）
    auto_expired = _auto_expire_stale_awaiting(data, expire_cutoff_iso)
    if auto_expired:
        # 重 load log（mark_fb_post_status 已寫盤）
        data = json.loads(LOG.read_text())

    # 2) 掃 stale pending（含仍未過 72h 的 awaiting）
    pending = []
    for e in data:
        s = str(e.get("fb_post_status", "")).strip().lower()
        if s in TERMINAL_STATUSES:
            continue
        created = e.get("date") or e.get("created_at") or e.get("timestamp", "")
        if created and created < stale_cutoff_iso:
            pending.append({
                "mile_id": e.get("mile_id"),
                "fb_post_status": s,
                "date": created,
                "has_draft": bool(e.get("fb_post_draft") or e.get("fb_draft")),
            })

    report = {
        "audit": "fb_pipeline",
        "stale_hours": STALE_HOURS,
        "auto_expire_hours": AUTO_EXPIRE_HOURS,
        "stale_pending_count": len(pending),
        "stale_pending": pending,
        "auto_expired_count": len(auto_expired),
        "auto_expired": auto_expired,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if len(pending) >= 2 or len(auto_expired) >= 1:
        sections = []
        if len(pending) >= 2:
            sections.append(
                f"## Stale pending（>={STALE_HOURS}h）{len(pending)} 篇\n"
                + "\n".join(
                    f"- {p['mile_id']} status={p['fb_post_status']} date={p['date']} has_draft={p['has_draft']}"
                    for p in pending
                )
            )
        if auto_expired:
            sections.append(
                f"## Auto-expired（awaiting >{AUTO_EXPIRE_HOURS}h → expired_skip）{len(auto_expired)} 篇\n"
                + "\n".join(f"- {p['mile_id']} ({p['date']})" for p in auto_expired)
            )
        sections.append(
            "## 根因\n個人 FB 帳號無 headless API。stale 累積 = 等不到 interactive session。\n"
            "## 永久解\n見 `docs/fb_pipeline_permanent_fix.md`（VolPred FB Page + Graph API）。"
        )
        body = "\n\n".join(sections)
        try:
            from src.volpred.ops.alerts import send_alert
            level = "warn" if pending else "info"
            send_alert(
                level=level,
                title=f"FB pipeline: {len(pending)} stale + {len(auto_expired)} auto-expired",
                body=body,
            )
        except Exception as e:
            print(f"alert send failed: {e}", file=sys.stderr)
    return 0 if not pending else 1


if __name__ == "__main__":
    sys.exit(main())
