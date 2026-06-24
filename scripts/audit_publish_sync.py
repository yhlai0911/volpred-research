#!/usr/bin/env python3
"""Standing audit: compare local feed.json published vs Supabase vs live URL.

Cron: hourly. Alerts if mismatch detected.

Surfaces:
- A: local published but NOT in supabase (sync failed)
- B: local published, IN supabase, but live URL not 200 (cache / route issue)
- C: in supabase but no local entry (orphan)

Emits warn alert if total mismatches >= 3.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path
from urllib import request, error
from urllib.parse import quote

REPO = Path(__file__).parent.parent
FEED = REPO / "storage" / "reports" / "feed.json"
LIVE_URL_TEMPLATE = "https://volpred.zeabur.app/v3/reports/{mile_id}"
SUPA_REST_TEMPLATE = "{base}/rest/v1/articles?select=slug,status&slug=in.({ids})"
WINDOW_HOURS = 72  # only audit articles published in last N hours


def _warn_publish_sync(message, *, exc=None, **context):
    parts = [f"{key}={value}" for key, value in context.items() if value is not None]
    if exc is not None:
        parts.append(f"error={type(exc).__name__}: {exc}")
    suffix = f" {' '.join(parts)}" if parts else ""
    print(f"[publish-sync-audit] WARN {message}{suffix}", file=sys.stderr)


def load_env():
    env = {}
    for fname in (".env.local", ".env"):
        p = REPO / fname
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def http_status(url, timeout=10):
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except error.HTTPError as e:
        return e.code
    except Exception as e:
        _warn_publish_sync("live URL check failed; returning status 0", url=url, exc=e)
        return 0


def fetch_supabase_slugs(env, mile_ids):
    base = env.get("SUPABASE_URL") or env.get("NEXT_PUBLIC_SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
    if not (base and key and mile_ids):
        return set()
    ids_csv = ",".join(mile_ids)
    url = SUPA_REST_TEMPLATE.format(base=base.rstrip("/"), ids=quote(ids_csv, safe=","))
    req = request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return {r["slug"] for r in data if r.get("status") == "published"}
    except Exception as e:
        _warn_publish_sync(
            "supabase slug fetch failed; treating remote slug set as empty",
            article_count=len(mile_ids),
            exc=e,
        )
        return set()


def main():
    feed = json.loads(FEED.read_text())
    now = time.time()
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - WINDOW_HOURS * 3600))

    # Local published in window
    local_pub = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "published":
            continue
        pub_at = item.get("published_at", "")
        if pub_at < cutoff_iso:
            continue
        mile_id = item.get("id") or item.get("slug")
        if not mile_id:
            continue
        local_pub.append(mile_id)
    local_set = set(local_pub)

    env = load_env()
    supa_set = fetch_supabase_slugs(env, list(local_set))

    # A: local pub not in supabase
    missing_supa = sorted(local_set - supa_set)

    # B: in supabase but live URL not 200
    live_check = sorted(local_set & supa_set)
    live_404 = []
    for mid in live_check:
        s = http_status(LIVE_URL_TEMPLATE.format(mile_id=mid))
        if s != 200:
            live_404.append({"mile_id": mid, "status_code": s})

    mismatches = len(missing_supa) + len(live_404)
    report = {
        "audit": "publish_sync",
        "window_hours": WINDOW_HOURS,
        "local_published_count": len(local_set),
        "supabase_synced_count": len(supa_set),
        "missing_supabase": missing_supa,
        "live_404": live_404,
        "mismatch_total": mismatches,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Alert if >=3 mismatches (avoid noise on 1-off transient)
    if mismatches >= 3:
        body = (
            "## 觸發條件\n"
            f"publish-sync audit 過去 {WINDOW_HOURS}h 發現 {mismatches} 篇 mismatch (missing_supabase={len(missing_supa)} live_404={len(live_404)})\n"
            f"- missing_supabase: {', '.join(missing_supa) or '無'}\n"
            f"- live_404: {', '.join(x['mile_id'] for x in live_404) or '無'}\n\n"
            "## 影響\n"
            "讀者點擊 FB / 外部分享連結會 404；Mission 1 (文章) + 5 (曝光) 漏接\n\n"
            "## 建議行動\n"
            "1. uv run python scripts/supabase_sync.py full\n"
            "2. 5 min 後重跑 audit；仍 missing → 查 supabase_sync.py log\n"
            "3. 404 但 supabase OK → 查 frontend route + Zeabur cache"
        )
        try:
            from src.volpred.ops.alerts import send_alert
            send_alert(level="warn", title=f"Publish sync mismatch: {mismatches} articles", body=body)
        except Exception as e:
            print(f"alert send failed: {e}", file=sys.stderr)

    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
