#!/usr/bin/env python3
"""Ops dashboard — single-call read of platform health across layers.

Designed for main-thread cycle start: I run this first, get state, triage.

Layers reported:
  L1 Production: pending tasks, recent publish count, paper pipeline
  L2 Distribution: feed.json published count, release_pool cadence, supabase parity
  L3 Verification: live URL sample, FB pipeline depth
  L4 Health: cron last_run gaps, alerts active

Each section emits {ok|warn|critical} + 1-line tldr + actionable next.
"""
from __future__ import annotations
import json, os, sys, time, calendar
from pathlib import Path
from urllib import request, error
from urllib.parse import quote

REPO = Path(__file__).parent.parent


def load_env():
    env = {}
    for fname in (".env.local", ".env"):
        p = REPO / fname
        if not p.exists(): continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def jl(p, default=None):
    try: return json.loads(Path(p).read_text())
    except Exception: return default


def http_ok(url, timeout=8):
    try:
        with request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def section(name, status, tldr, next_action=None, **details):
    return {"section": name, "status": status, "tldr": tldr, "next": next_action, **details}


def main():
    env = load_env()
    out = []
    now = time.time()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # L1 Production
    nt = jl(REPO / "storage" / "next_tasks.json", [])
    pending = [t for t in nt if t.get("status") == "pending"]
    by_type = {}
    for t in pending:
        by_type[t.get("task_type", "?")] = by_type.get(t.get("task_type", "?"), 0) + 1
    out.append(section(
        "production_pending",
        "ok" if len(pending) >= 4 else "warn" if len(pending) >= 1 else "critical",
        f"{len(pending)} pending tasks (top types: {sorted(by_type.items(), key=lambda x:-x[1])[:3]})",
        "dispatch top P1-P3 if slots free" if len(pending) > 0 else "refill pool"
    ))

    feed = jl(REPO / "storage" / "reports" / "feed.json", [])
    last_24h_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 86400))
    pub_24h = [a for a in feed if isinstance(a, dict) and a.get("status") == "published" and a.get("published_at", "") >= last_24h_iso]
    target = 6  # Mission 1: ~6+ articles/day target
    out.append(section(
        "production_throughput",
        "ok" if len(pub_24h) >= target else "warn" if len(pub_24h) >= target // 2 else "critical",
        f"{len(pub_24h)} articles published last 24h (target {target}/day)",
        "派 daily_article + trending_repost agent" if len(pub_24h) < target else None
    ))

    # L2 Distribution: Supabase parity for recent 24h
    recent_ids = [a.get("id") for a in pub_24h if a.get("id")]
    supa_synced = set()
    if recent_ids and env.get("SUPABASE_URL") and (env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")):
        key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
        try:
            url = f"{env['SUPABASE_URL'].rstrip('/')}/rest/v1/articles?select=slug,status&slug=in.({quote(','.join(recent_ids), safe=',')})"
            req = request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            with request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                supa_synced = {x["slug"] for x in data if x.get("status") == "published"}
        except Exception as e:
            pass
    miss_supa = sorted(set(recent_ids) - supa_synced)
    out.append(section(
        "distribution_supabase",
        "ok" if not miss_supa else "warn" if len(miss_supa) <= 2 else "critical",
        f"{len(recent_ids) - len(miss_supa)}/{len(recent_ids)} last-24h articles synced",
        f"uv run python scripts/supabase_sync.py full ({len(miss_supa)} missing)" if miss_supa else None,
        missing=miss_supa[:5]
    ))

    # L3 Verification: live URL sample (3 newest)
    sample = recent_ids[:3]
    live_404 = []
    for mid in sample:
        if not http_ok(f"https://volpred.zeabur.app/v3/reports/{mid}"):
            live_404.append(mid)
    out.append(section(
        "verification_live_url",
        "ok" if not live_404 else "critical",
        f"{len(sample) - len(live_404)}/{len(sample)} sample live URLs return 200",
        "查 frontend route + Zeabur cache" if live_404 else None,
        sample=sample, dead=live_404
    ))

    # L3 FB pipeline
    fb_log = jl(REPO / "storage" / "reports" / "trending_repost_log.json", [])
    fb_pending = [x for x in fb_log if x.get("fb_post_status") not in ("success", "wont_fix", "fb_silent_reject")]
    out.append(section(
        "verification_fb_pipeline",
        "ok" if len(fb_pending) == 0 else "warn" if len(fb_pending) <= 2 else "critical",
        f"{len(fb_pending)} FB posts pending sync",
        "handoff doc + manual paste or retry MCP" if fb_pending else None
    ))

    # L4 cron health
    cron = jl(REPO / "storage" / "ops" / "cron_last_run.json", {})
    stale = []
    expected_max_age_hours = {
        # collect_* run once daily (collect_tw 15:00 Mon-Fri, collect_us 07:03
        # Tue-Sat) — a 12h max-age chronically false-flags them every day in
        # the ~22h gap between daily runs. 26h covers normal daily cadence.
        "collect_us_data": 26, "collect_tw_data": 26, "release_pool": 4,
        "check_alerts": 2, "paper_sync_all": 8, "memory_health_daily": 30,
        "market_calendar_sync": 30, "refresh_paper_snapshots": 30,
    }
    for job, max_h in expected_max_age_hours.items():
        last = cron.get(job, "")
        if not last: continue
        try:
            # cron_last_run.json stores UTC ISO timestamps; parse as UTC
            # (time.mktime would mis-read them as local time → spurious +8h age)
            last_ts = calendar.timegm(time.strptime(last[:19], "%Y-%m-%dT%H:%M:%S"))
            age_h = (now - last_ts) / 3600.0
            if age_h > max_h:
                stale.append({"job": job, "age_h": round(age_h, 1), "max_h": max_h})
        except Exception:
            pass
    out.append(section(
        "health_cron",
        "ok" if not stale else "warn" if len(stale) <= 2 else "critical",
        f"{len(stale)} cron jobs stale (over max-age)",
        f"manual fire ~/.volpred/bin/cron_<id>.sh" if stale else None,
        stale=stale
    ))

    # L4 alerts — INGEST recent warn/critical from notification_log + surface as actionable
    nlog = jl(REPO / "storage" / "notifications" / "notification_log.json", [])
    cutoff_6h = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 6 * 3600))
    recent_breach = []
    if isinstance(nlog, list):
        for n in nlog:
            if not isinstance(n, dict): continue
            ts = n.get("timestamp", "")
            if ts < cutoff_6h: continue
            level = n.get("level", "info")
            if level in ("warn", "critical"):
                recent_breach.append({
                    "ts": ts[11:16],
                    "level": level,
                    "subject": (n.get("subject") or n.get("title") or "")[:80],
                })
    out.append(section(
        "health_alerts_unhandled",
        "ok" if not recent_breach else "warn" if len(recent_breach) <= 2 else "critical",
        f"{len(recent_breach)} warn/critical alerts last 6h (read + act per .claude/rules/alert.md)",
        "ingest alerts → run remediation per alert.md auto-action table" if recent_breach else None,
        breaches=recent_breach[:8],
    ))

    # Summary header
    breaches = sum(1 for s in out if s["status"] in ("warn", "critical"))
    critical = sum(1 for s in out if s["status"] == "critical")
    print(json.dumps({
        "dashboard_generated_at": now_iso,
        "overall_status": "critical" if critical else "warn" if breaches else "ok",
        "section_breaches": breaches,
        "section_critical": critical,
        "sections": out,
    }, ensure_ascii=False, indent=2))
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
