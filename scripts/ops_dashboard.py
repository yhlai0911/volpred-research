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
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.ops.alerts import build_alert_condition_report

FB_POST_TERMINAL_STATUSES = {"success", "wont_fix", "fb_silent_reject"}
FB_POST_HANDOFF_STATUSES = {"awaiting_interactive_session"}


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


def classify_fb_pipeline(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    actionable = []
    awaiting = []
    for item in entries:
        status = str(item.get("fb_post_status") or "").strip().lower()
        if status in FB_POST_TERMINAL_STATUSES:
            continue
        if status in FB_POST_HANDOFF_STATUSES:
            awaiting.append(item)
            continue
        actionable.append(item)
    return actionable, awaiting


def main():
    env = load_env()
    out = []
    now = time.time()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # L1 Production
    nt = jl(REPO / "storage" / "next_tasks.json", [])
    pending = [t for t in nt if t.get("status") == "pending"]
    pending_main = [t for t in nt if t.get("status") == "pending_main_thread"]
    actionable = pending + pending_main
    by_type = {}
    for t in actionable:
        by_type[t.get("task_type", "?")] = by_type.get(t.get("task_type", "?"), 0) + 1
    if pending:
        pending_tldr = (
            f"{len(pending)} pending tasks"
            + (f" + {len(pending_main)} pending_main_thread" if pending_main else "")
            + f" (top types: {sorted(by_type.items(), key=lambda x:-x[1])[:3]})"
        )
        pending_status = "ok" if len(actionable) >= 4 else "warn"
        pending_next = "dispatch top P1-P3 if slots free"
    elif pending_main:
        pending_tldr = (
            f"0 pending tasks, but {len(pending_main)} pending_main_thread tasks"
            f" (top types: {sorted(by_type.items(), key=lambda x:-x[1])[:3]})"
        )
        pending_status = "warn"
        pending_next = "main-thread backlog exists; do not auto-refill agentable pool blindly"
    else:
        pending_tldr = "0 pending tasks (top types: [])"
        pending_status = "critical"
        pending_next = "refill pool"
    out.append(section(
        "production_pending",
        pending_status,
        pending_tldr,
        pending_next,
        pending_count=len(pending),
        pending_main_thread_count=len(pending_main),
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
    fb_pending, fb_awaiting = classify_fb_pipeline(fb_log)
    fb_status = "ok" if len(fb_pending) == 0 else "warn" if len(fb_pending) <= 2 else "critical"
    fb_tldr = (
        f"{len(fb_awaiting)} FB posts awaiting interactive session"
        if len(fb_pending) == 0 and fb_awaiting
        else f"{len(fb_pending)} FB posts pending sync"
    )
    fb_next = None
    if fb_pending:
        fb_next = "handoff doc + manual paste or retry MCP"
    elif fb_awaiting:
        fb_next = "interactive session / Chrome MCP available時接手貼文與留言"
    out.append(section(
        "verification_fb_pipeline",
        fb_status,
        fb_tldr,
        fb_next,
        actionable_pending=[x.get("mile_id") for x in fb_pending[:5]],
        awaiting_interactive=[x.get("mile_id") for x in fb_awaiting[:5]],
    ))

    # L4 cron health — schedule-aware: read cron string from runtime_schedules.json,
    # compute expected_next_fire via croniter, flag stale only when
    # now > next_expected_fire + grace AND last_run < prev_expected_fire.
    # Hardcoded max_h was a false-positive trap for weekday-only / weekly cron.
    cron = jl(REPO / "storage" / "ops" / "cron_last_run.json", {})
    schedules = jl(REPO / "config" / "runtime_schedules.json", {})
    # Build {job_id: cron_string} from system_crontab + cron_jobs sections
    job_cron_map = {}
    for item in (schedules.get("system_crontab", {}) or {}).get("items", []):
        if isinstance(item, dict) and item.get("id") and item.get("cron"):
            job_cron_map[item["id"]] = item["cron"]
    for item in (schedules.get("cron_jobs", []) or []):
        if isinstance(item, dict) and item.get("id") and item.get("cron"):
            # cron_jobs use 'volpred-XXX' ids; map to underscore form for cron_last_run.json
            job_cron_map[item["id"].replace("volpred-", "").replace("-", "_")] = item["cron"]
    # Jobs we monitor + grace_min (allow up to grace_min late before flagging)
    monitored = {
        "collect_us_data": 60, "collect_tw_data": 60, "release_pool": 30,
        "check_alerts": 30, "paper_sync_all": 60, "memory_health_daily": 60,
        "market_calendar_sync": 120, "refresh_paper_snapshots": 120,
    }
    stale = []
    try:
        from croniter import croniter
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo("Asia/Taipei")  # host crontab runs in local (Taipei)
        except Exception:
            local_tz = None
    except Exception:
        croniter = None
        local_tz = None
    for job, grace_min in monitored.items():
        last = cron.get(job, "")
        if not last:
            continue
        try:
            last_ts = calendar.timegm(time.strptime(last[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        cron_str = job_cron_map.get(job)
        if cron_str and croniter:
            # Compute prev expected fire (before now) using local TZ (host crontab runs local).
            try:
                now_dt = datetime.now(local_tz) if local_tz else datetime.now()
                itr = croniter(cron_str, now_dt)
                prev_fire = itr.get_prev()  # epoch seconds (tz-aware → correct UTC epoch)
                next_fire = itr.get_next()
                # stale only if last_run was BEFORE prev_expected_fire
                # AND we are past prev_fire + grace
                grace_s = grace_min * 60
                if last_ts < prev_fire - 60 and time.time() > prev_fire + grace_s:
                    age_h = (time.time() - last_ts) / 3600.0
                    stale.append({
                        "job": job,
                        "age_h": round(age_h, 1),
                        "missed_expected_fire_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(prev_fire)),
                    })
                continue
            except Exception:
                pass
        # Fallback: simple max-age (legacy behavior)
        legacy_max_h = {
            "collect_us_data": 50, "collect_tw_data": 80, "release_pool": 4,
            "check_alerts": 2, "paper_sync_all": 8, "memory_health_daily": 30,
            "market_calendar_sync": 192, "refresh_paper_snapshots": 192,
        }.get(job, 26)
        age_h = (now - last_ts) / 3600.0
        if age_h > legacy_max_h:
            stale.append({"job": job, "age_h": round(age_h, 1), "max_h": legacy_max_h})
    out.append(section(
        "health_cron",
        "ok" if not stale else "warn" if len(stale) <= 2 else "critical",
        f"{len(stale)} cron jobs stale (over max-age)",
        f"manual fire ~/.volpred/bin/cron_<id>.sh" if stale else None,
        stale=stale
    ))

    # L4 alerts — reflect CURRENT breached conditions, not historical notification
    # rows. Otherwise a resolved incident can keep dashboard red for hours merely
    # because old alert emails remain unresolved in notification_log.json.
    alert_report = build_alert_condition_report(storage_dir=str(REPO / "storage"))
    recent_breach = []
    for item in alert_report.get("conditions", []):
        if not item.get("breached"):
            continue
        recent_breach.append({
            "ts": now_iso[11:16],
            "level": item.get("level", "info"),
            "subject": str(item.get("title") or "")[:80],
        })
    out.append(section(
        "health_alerts_unhandled",
        "ok" if not recent_breach else "warn" if len(recent_breach) <= 2 else "critical",
        f"{len(recent_breach)} current warn/critical alert conditions",
        "ingest alerts → run remediation per alert.md auto-action table" if recent_breach else None,
        breaches=recent_breach[:8],
    ))

    # Summary header
    breaches = sum(1 for s in out if s["status"] in ("warn", "critical"))
    critical = sum(1 for s in out if s["status"] == "critical")
    payload = {
        "dashboard_generated_at": now_iso,
        "overall_status": "critical" if critical else "warn" if breaches else "ok",
        "section_breaches": breaches,
        "section_critical": critical,
        "sections": out,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Dashboard is a reporting surface, not an execution gate. Non-zero exit
    # here would be misclassified by host_cron_fail as wrapper breakage.
    return 0


if __name__ == "__main__":
    sys.exit(main())
