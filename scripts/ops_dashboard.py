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

FB_POST_TERMINAL_STATUSES = {"success", "wont_fix", "fb_silent_reject", "expired_skip"}
FB_POST_HANDOFF_STATUSES = {"awaiting_interactive_session"}
CLAUDE_ONLY_TASK_TYPES = {
    "paper_body",
    "paper_decision",
    "event_article",
    "member_qa",
    "trending_repost",
    "strategy_lifecycle",
    "email_reply",
}


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


def warn_json_read_failed(path: Path, exc: Exception) -> None:
    print(
        f"[ops_dashboard] WARN JSON read failed: "
        f"path={path} error={type(exc).__name__}: {exc}"
    )


def _warn_http_check_failed(url: str, exc: Exception) -> None:
    print(
        f"[ops_dashboard] WARN HTTP check failed: "
        f"url={url} error={type(exc).__name__}: {exc}"
    )


def _warn_inflight_timestamp_failed(task_id: str, raw_ts: object, exc: Exception) -> None:
    print(
        f"[ops_dashboard] WARN in-flight timestamp parse failed: "
        f"task_id={task_id} raw={raw_ts!r} error={type(exc).__name__}: {exc}"
    )


def jl(p, default=None):
    path = Path(p)
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        warn_json_read_failed(path, exc)
        return default


def http_ok(url, timeout=8):
    try:
        with request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception as exc:
        _warn_http_check_failed(url, exc)
        return False


def section(name, status, tldr, next_action=None, **details):
    return {"section": name, "status": status, "tldr": tldr, "next": next_action, **details}


def write_dashboard_latest(payload: dict) -> None:
    path = REPO / "storage" / "ops" / "dashboard_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    # 2026-06-08 (boss mandate「立刻徹底解決 warning」): production_pending was
    # firing CRITICAL whenever the *article* pending pool emptied — even when
    # research was actively in flight (experiments compute_queued / claimed).
    # An empty article-pending pool with research running is NOT an idle platform;
    # it's the healthy state between research→article cycles. Count in-flight work
    # so "0 pending" only escalates to CRITICAL when the platform is TRULY idle
    # (nothing pending, nothing main-thread, nothing compute-queued, nothing claimed).
    # 2026-06-09: staleness guard. The original in_flight count let MONTH-OLD
    # orphan compute_queued tasks (e.g. queued 2026-05-13/05-19, never run by a
    # defunct compute worker) masquerade as "healthy research in flight" for weeks,
    # hiding a thin pipeline behind a benign-looking warn. Only count in-flight
    # items whose timestamp is RECENT (< STALE_INFLIGHT_HOURS) as healthy; older
    # ones are stuck orphans → surfaced separately for triage, not counted as work.
    STALE_INFLIGHT_HOURS = 48
    _now = time.time()
    def _inflight_age_h(t):
        ts = t.get("compute_queued_at") or t.get("claimed_at") or t.get("started_at") or t.get("created_at")
        if not ts:
            return None
        try:
            dt = time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
            return (_now - dt) / 3600.0
        except Exception as exc:
            _warn_inflight_timestamp_failed(str(t.get("id") or "?"), ts, exc)
            return None
    _all_inflight = [t for t in nt if t.get("status") in ("compute_queued", "claimed", "in_progress")]
    in_flight = []
    stale_inflight = []
    for t in _all_inflight:
        age = _inflight_age_h(t)
        if age is not None and age > STALE_INFLIGHT_HOURS:
            stale_inflight.append(t)
        else:
            in_flight.append(t)
    by_type = {}
    for t in actionable:
        by_type[t.get("task_type", "?")] = by_type.get(t.get("task_type", "?"), 0) + 1
    pending_claude_only = [
        t for t in pending
        if str(t.get("task_type") or "").strip().lower() in CLAUDE_ONLY_TASK_TYPES
    ]
    # Health threshold counts ALL active pipeline work, not just dispatchable
    # `pending`: pending + pending_main + in_flight (compute_queued/claimed/in_progress).
    # A platform with 2 pending + 2 compute_queued experiments has 4 work items
    # flowing — it is NOT under-supplied. (boss mandate 2026-06-08：persistent warn
    # at "2 pending" while research was compute-queued was a false signal.)
    total_active = len(actionable) + len(in_flight)
    if pending:
        pending_tldr = (
            f"{len(pending)} pending tasks"
            + (f" + {len(pending_main)} pending_main_thread" if pending_main else "")
            + (f" + {len(in_flight)} in-flight" if in_flight else "")
            + f" (top types: {sorted(by_type.items(), key=lambda x:-x[1])[:3]})"
        )
        # 2026-06-14: threshold 對齊 dispatcher auto-refill 設計。REFILL_FLOOR=4，
        # 消耗 1 後自然在 3 振盪 → 原 `>=4 else warn` 讓「3 pending」永遠假警報
        # （benign、自我修復，但連續多 tick 噪音）。trough=3 視為健康 ok；warn 留給
        # 真正低（≤2 = refill 跟不上消耗）；critical 維持 0-idle（下方 else 分支）。
        pending_status = "ok" if total_active >= 3 else "warn"
        if len(pending_claude_only) == len(pending):
            pending_next = "Claude-only pending backlog; Codex should skip and Claude main thread should claim"
        else:
            pending_next = "dispatch top P1-P3 if slots free"
    elif pending_main:
        pending_tldr = (
            f"0 pending tasks, but {len(pending_main)} pending_main_thread tasks"
            f" (top types: {sorted(by_type.items(), key=lambda x:-x[1])[:3]})"
        )
        pending_status = "warn"
        pending_next = "main-thread backlog exists; do not auto-refill agentable pool blindly"
    elif in_flight:
        # Article pool empty but research/work is in flight → healthy-but-low, not idle.
        flt_types = {}
        for t in in_flight:
            flt_types[t.get("task_type", "?")] = flt_types.get(t.get("task_type", "?"), 0) + 1
        pending_tldr = (
            f"0 pending tasks, but {len(in_flight)} in-flight "
            f"(compute_queued/claimed/in_progress: {sorted(flt_types.items(), key=lambda x:-x[1])[:3]})"
        )
        pending_status = "warn"
        pending_next = "research in flight; refill articles when experiments complete (or auto research-fallback)"
    else:
        pending_tldr = "0 pending tasks, 0 in-flight — platform idle (top types: [])"
        pending_status = "critical"
        pending_next = "refill pool (article candidates + research-backlog fallback)"
    out.append(section(
        "production_pending",
        pending_status,
        pending_tldr,
        pending_next,
        pending_count=len(pending),
        pending_main_thread_count=len(pending_main),
        pending_claude_only_count=len(pending_claude_only),
        in_flight_count=len(in_flight),
        stale_inflight_count=len(stale_inflight),
    ))

    # Stale in-flight orphans (compute_queued/claimed/in_progress > 48h) — these
    # are stuck tasks that masquerade as healthy work; surface them for triage so
    # they don't silently accumulate for weeks (2026-06-09: two tasks queued
    # 2026-05-13 / 05-19 sat unnoticed for ~1 month behind a benign warn).
    if stale_inflight:
        items = [
            {"id": t.get("id"), "status": t.get("status"),
             "age_h": round(_inflight_age_h(t) or 0, 1)}
            for t in sorted(stale_inflight, key=lambda x: _inflight_age_h(x) or 0, reverse=True)
        ]
        out.append(section(
            "stale_inflight",
            "warn" if len(stale_inflight) <= 3 else "critical",
            f"{len(stale_inflight)} stuck in-flight task(s) > 48h (orphans, not real work)",
            "triage: 標 succeeded（已完成）/ blocked（卡死）/ release（重派）— 別讓它們撐 in-flight 計數",
            items=items[:8],
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
    supa_error = None
    if recent_ids:
        if env.get("SUPABASE_URL") and (env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")):
            key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
            try:
                url = f"{env['SUPABASE_URL'].rstrip('/')}/rest/v1/articles?select=slug,status&slug=in.({quote(','.join(recent_ids), safe=',')})"
                req = request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
                with request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                    supa_synced = {x["slug"] for x in data if x.get("status") == "published"}
            except Exception as e:
                supa_error = f"{type(e).__name__}: {e}"
        else:
            supa_error = "missing Supabase URL or service key"
    if supa_error:
        out.append(section(
            "distribution_supabase",
            "warn",
            f"parity check unavailable: {supa_error}",
            "fix Supabase env/connectivity before running sync remediation",
            recent_ids=recent_ids[:5],
            error=supa_error,
        ))
    else:
        miss_supa = sorted(set(recent_ids) - supa_synced)
        out.append(section(
            "distribution_supabase",
            "ok" if not miss_supa else "warn" if len(miss_supa) <= 2 else "critical",
            f"{len(recent_ids) - len(miss_supa)}/{len(recent_ids)} last-24h articles synced",
            f"uv run python scripts/supabase_sync.py full ({len(miss_supa)} missing)" if miss_supa else None,
            missing=miss_supa[:5]
        ))

    # L3 Verification: live URL sample (3 newest reports + core pages)
    # 2026-06-11 incident: /paper full-page React render error (unknown
    # status crashed STATUS_CONFIG) went undetected — HTTP was 200 and the
    # page wasn't in the sample. Fix: (a) include core pages, (b) content
    # check — a client-crash page still returns 200 but its SSR shell loses
    # the expected anchor text / carries Next.js error markers.
    sample = recent_ids[:3]
    live_404 = []
    for mid in sample:
        if not http_ok(f"https://volpred.zeabur.app/v3/reports/{mid}"):
            live_404.append(mid)
    CORE_PAGES = {  # path -> anchor text that must appear in the SSR HTML
        "/": "VolPred",
        "/paper": "VolPred",
        "/v3": "VolPred",
    }
    page_fail = []
    for path, anchor in CORE_PAGES.items():
        try:
            import urllib.request
            req = urllib.request.Request(f"https://volpred.zeabur.app{path}",
                                         headers={"User-Agent": "volpred-ops-dashboard"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
            if anchor not in html or "Application error" in html or "__next_error__" in html:
                page_fail.append(path)
        except Exception:
            page_fail.append(path)
    out.append(section(
        "verification_live_url",
        "ok" if not (live_404 or page_fail) else "critical",
        f"{len(sample) - len(live_404)}/{len(sample)} sample report URLs ok; "
        f"{len(CORE_PAGES) - len(page_fail)}/{len(CORE_PAGES)} core pages content-ok",
        "查 frontend route / render error / Zeabur cache" if (live_404 or page_fail) else None,
        sample=sample, dead=live_404, core_page_fail=page_fail
    ))

    # L3 FB pipeline
    fb_log = jl(REPO / "storage" / "reports" / "trending_repost_log.json", [])
    # 2026-06-10 process-audit CRITICAL #2: event_article FB statuses live as
    # top-level fb_post_status on feed.json entries, NOT in trending_repost_log
    # — both this dashboard and audit_fb_pipeline.py were blind to them (6
    # awaiting found, oldest 06-05 past the 72h auto-expire bar; structural
    # repeat of the 2026-06-03 FB-audit incident). Merge feed-side entries in;
    # normalize id key to mile_id for the section output.
    fb_feed_entries = [
        {**a, "mile_id": a.get("mile_id") or a.get("id")}
        for a in feed
        if isinstance(a, dict) and str(a.get("fb_post_status") or "").strip()
    ]
    seen_mile_ids = {x.get("mile_id") for x in fb_log if isinstance(x, dict)}
    fb_all = list(fb_log) + [e for e in fb_feed_entries if e.get("mile_id") not in seen_mile_ids]
    fb_pending, fb_awaiting = classify_fb_pipeline(fb_all)
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
    job_log_map = {}  # 2026-05-29: piggy_back_skip 的 job 不更新 cron_last_run.json(LaunchAgent 不寫),
                      # 用 log 檔 mtime 當「是否有 fire」的補充證據,避免 false-positive stale。
    for item in (schedules.get("system_crontab", {}) or {}).get("items", []):
        if isinstance(item, dict) and item.get("id") and item.get("cron"):
            job_cron_map[item["id"]] = item["cron"]
        if isinstance(item, dict) and item.get("id") and item.get("log_path"):
            job_log_map[item["id"]] = item["log_path"]
    for item in (schedules.get("cron_jobs", []) or []):
        if isinstance(item, dict) and item.get("id") and item.get("cron"):
            # cron_jobs use 'volpred-XXX' ids; map to underscore form for cron_last_run.json
            job_cron_map[item["id"].replace("volpred-", "").replace("-", "_")] = item["cron"]
    # Jobs we monitor + grace_min (allow up to grace_min late before flagging)
    monitored = {
        "collect_us_data": 60, "collect_tw_data": 60, "release_pool": 30,
        "check_alerts": 30, "paper_sync_all": 60, "memory_health_daily": 60,
        "market_calendar_sync": 120, "refresh_paper_snapshots": 120,
        # 2026-06-10 process-audit HIGH 4-1: the four MOST critical jobs were
        # absent — a dead LaunchAgent (log frozen at exit 0) never breached
        # anything. hourly_dispatch/compute_worker live in cron_jobs (not
        # system_crontab), so their cron/log maps are seeded below.
        "hourly_dispatch": 30, "gmail_poll": 30,
        "compute_worker": 60, "handoff_regen": 90,
    }
    # cron_jobs-section jobs (LaunchAgent-fired) aren't in system_crontab.items
    # — seed their cron + log mappings explicitly so staleness math works.
    job_cron_map.setdefault("hourly_dispatch", "7 * * * *")
    job_log_map.setdefault("hourly_dispatch", "storage/logs/cron/hourly_dispatch.log")
    job_cron_map.setdefault("compute_worker", "*/15 * * * *")
    job_log_map.setdefault("compute_worker", "storage/logs/cron/compute_worker.log")
    # handoff_regen: spec log_path (cron/handoff_regen.log) does not exist on
    # disk (4-2 spec-drift instance) — its freshest fire evidence is the
    # artifact it regenerates. Override the spec-seeded mapping.
    job_log_map["handoff_regen"] = "storage/ops/handoff_latest.md"
    stale = []
    cron_warnings = []
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
        last_ts = None
        if last:
            try:
                last_ts = calendar.timegm(time.strptime(last[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                last_ts = None
        # LaunchAgent-fired (piggy_back_skip) jobs touch their log on each fire but
        # do NOT update cron_last_run.json → use log mtime as additional "did it fire"
        # evidence (success/failure is host_cron_fail's job, not staleness).
        log_rel = job_log_map.get(job)
        if log_rel:
            log_path = REPO / log_rel
            try:
                if log_path.exists():
                    last_ts = max(last_ts or 0, int(log_path.stat().st_mtime))
            except Exception as exc:
                cron_warnings.append({
                    "job": job,
                    "source": "log_mtime",
                    "log_path": str(log_path),
                    "error": f"{type(exc).__name__}: {exc}",
                })
        if not last_ts:
            # 2026-06-10 process-audit 4-1: a monitored job with NO fire
            # evidence at all (no cron_last_run entry, no log file) was
            # silently skipped — the worst failure (never ran / log deleted /
            # plist unloaded) was the least visible. Flag it.
            stale.append({"job": job, "last_run": None, "reason": "no_fire_evidence"})
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
            except Exception as exc:
                cron_warnings.append({
                    "job": job,
                    "source": "croniter",
                    "cron": cron_str,
                    "error": f"{type(exc).__name__}: {exc}",
                })
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
        stale=stale,
        warnings=cron_warnings[:10],
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
        "generated_by": "scripts/ops_dashboard.py",
        "age_seconds": 0,
        "overall_status": "critical" if critical else "warn" if breaches else "ok",
        "section_breaches": breaches,
        "section_critical": critical,
        "sections": out,
    }
    try:
        write_dashboard_latest(payload)
    except Exception as exc:
        payload["dashboard_write_error"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Dashboard is a reporting surface, not an execution gate. Non-zero exit
    # here would be misclassified by host_cron_fail as wrapper breakage.
    return 0


if __name__ == "__main__":
    sys.exit(main())
