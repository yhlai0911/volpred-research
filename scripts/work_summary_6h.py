#!/usr/bin/env python3
"""
6-hour work summary email (HTML body) — every 6h, gather what changed in the
past 6h and send via EmailNotifier (HTML rendered, plain-text fallback).

Sources scanned:
- git log --since 6h  → commits
- storage/work_log.json  → task entries with timestamp in window
- storage/notifications/  → new notification JSON files
- storage/reports/feed.json  → articles published/created in window
- .claude/worktrees/  → currently-active agent worktrees

Output: HTML email (multipart/alternative with plain-text fallback).
Recipient: yihao.lai@gmail.com (ALERT_RECIPIENT).

Invoke: bash wrapper at ~/.volpred/bin/cron_work_summary.sh
Schedule: LaunchAgent com.volpred.work-summary, fires 0/6/12/18 UTC + 5min offset
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

STORAGE = PROJECT_ROOT / "storage"
NOW = datetime.now(timezone.utc)
WINDOW = timedelta(hours=6)
SINCE = NOW - WINDOW


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT)] + cmd,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
    except Exception as e:
        return f"(git failed: {e})"


def _commits_in_window() -> list[dict]:
    since_iso = SINCE.isoformat()
    raw = _git(["log", f"--since={since_iso}", "--pretty=format:%h|%s|%ai"])
    out: list[dict] = []
    for ln in raw.splitlines():
        if "|" not in ln:
            continue
        parts = ln.split("|", 2)
        if len(parts) == 3:
            out.append({"sha": parts[0], "subject": parts[1], "iso": parts[2]})
    return out


def _files_changed_in_window() -> dict[str, int]:
    since_iso = SINCE.isoformat()
    raw = _git(["log", f"--since={since_iso}", "--name-only", "--pretty=format:"])
    files: dict[str, int] = {}
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        files[ln] = files.get(ln, 0) + 1
    return files


def _work_log_entries() -> list[dict]:
    path = STORAGE / "work_log.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for entry in data:
        ts = entry.get("ts") or entry.get("timestamp") or entry.get("completed_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt >= SINCE:
            out.append(entry)
    return out


def _new_notifications() -> list[dict]:
    nd = STORAGE / "notifications"
    if not nd.exists():
        return []
    out = []
    for f in sorted(nd.glob("*.json")):
        if f.name == "notification_log.json":
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < SINCE:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            title = data.get("subject") or data.get("title") or data.get("message", "")[:80]
            level = data.get("level") or data.get("metadata", {}).get("alert_level", "")
        except Exception:
            title = f.name
            level = ""
        out.append({"time": mtime.strftime("%H:%M"), "title": title, "level": level})
    return out


def _articles_in_window() -> dict[str, list[dict]]:
    feed_path = STORAGE / "reports" / "feed.json"
    if not feed_path.exists():
        return {"published": [], "drafts": []}
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception:
        return {"published": [], "drafts": []}
    if not isinstance(feed, list):
        return {"published": [], "drafts": []}
    pub: list[dict] = []
    drafts: list[dict] = []
    for art in feed:
        if not isinstance(art, dict):
            continue
        pub_at = art.get("published_at")
        created_at = art.get("created_at")
        try:
            pub_dt = datetime.fromisoformat(str(pub_at).replace("Z", "+00:00")) if pub_at else None
            if pub_dt and pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = None
        try:
            create_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")) if created_at else None
            if create_dt and create_dt.tzinfo is None:
                create_dt = create_dt.replace(tzinfo=timezone.utc)
        except Exception:
            create_dt = None
        if pub_dt and pub_dt >= SINCE and art.get("status") == "published":
            pub.append({"id": art.get("id"), "title": art.get("title", "")[:100], "ts": pub_dt.strftime("%H:%M"), "audience": art.get("audience", "")})
        elif create_dt and create_dt >= SINCE and art.get("status") == "draft":
            drafts.append({"id": art.get("id"), "title": art.get("title", "")[:100], "ts": create_dt.strftime("%H:%M"), "audience": art.get("audience", "")})
    return {"published": pub, "drafts": drafts}


def _active_worktrees() -> list[str]:
    wd = PROJECT_ROOT / ".claude" / "worktrees"
    if not wd.exists():
        return []
    return [d.name for d in wd.iterdir() if d.is_dir() and d.name != ".DS_Store"]


def _platform_health() -> dict:
    """Snapshot of platform key health metrics."""
    health = {}
    # Draft pool
    feed_path = STORAGE / "reports" / "feed.json"
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            if isinstance(feed, list):
                health["draft_count"] = sum(1 for a in feed if isinstance(a, dict) and a.get("status") == "draft")
                health["published_total"] = sum(1 for a in feed if isinstance(a, dict) and a.get("status") == "published")
            else:
                health["draft_count"] = None
        except Exception:
            health["draft_count"] = None
    # Release pool cadence
    rs_path = STORAGE / ".release_settings.json"
    if rs_path.exists():
        try:
            rs = json.loads(rs_path.read_text(encoding="utf-8"))
            last_iso = rs.get("last_released_at")
            interval = rs.get("interval_minutes", 180)
            health["release_interval_min"] = interval
            if last_iso:
                last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                gap_min = (NOW - last_dt).total_seconds() / 60
                health["last_release_gap_min"] = round(gap_min, 1)
                health["last_release_at"] = last_dt.strftime("%H:%M UTC")
        except Exception:
            health["release_interval_min"] = None
    # Knowledge.json size + freshness
    kj = STORAGE / "memory" / "knowledge.json"
    if kj.exists():
        try:
            stat = kj.stat()
            health["knowledge_size_mb"] = round(stat.st_size / (1024 * 1024), 2)
            health["knowledge_mtime"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
    # Active alerts (current)
    health["alert_breaches"] = 0
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from volpred.ops.alerts import build_alert_condition_report
        rpt = build_alert_condition_report()
        if isinstance(rpt, dict):
            health["alert_breaches"] = sum(1 for c in rpt.get("conditions", []) if c.get("breached"))
            health["alert_total_checked"] = len(rpt.get("conditions", []))
    except Exception as e:
        health["alert_check_err"] = str(e)[:80]
    # Pending dispatch queue
    nt = STORAGE / "next_tasks.json"
    if nt.exists():
        try:
            tasks = json.loads(nt.read_text(encoding="utf-8"))
            health["pending_tasks"] = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "pending")
        except Exception:
            pass
    return health


def _mission_progress(commits: list[dict], articles: dict, work: list[dict]) -> dict:
    """Heuristic score 5 Mission goals from this window's activity."""
    progress: dict[str, dict] = {}

    # M1 文章 — published count + draft fresh
    m1 = len(articles["published"]) + len(articles["drafts"])
    progress["M1 把文章寫好"] = {
        "evidence": f"{len(articles['published'])} published + {len(articles['drafts'])} drafts",
        "status": "active" if m1 > 0 else "idle",
        "note": "draft pool 釋出節奏 + 新草稿補充" if m1 > 0 else "本窗口無新文章",
    }

    # M2 研究 — experiment commits + knowledge.json entries
    exp_commits = [c for c in commits if any(k in c["subject"].lower() for k in ["experiment", "k13", "k12", "k11", "k10"])]
    knowledge_commits = [c for c in commits if "knowledge" in c["subject"].lower()]
    m2_count = len(exp_commits) + len(knowledge_commits)
    progress["M2 把實驗與研究做好"] = {
        "evidence": f"{len(exp_commits)} experiment commits + {len(knowledge_commits)} knowledge updates",
        "status": "active" if m2_count > 0 else "idle",
        "note": "新 K 實驗 + Codex review + knowledge entry" if m2_count > 0 else "本窗口無新實驗 closure",
    }

    # M3 論文 — paper/ commits
    paper_commits = [c for c in commits if any(k in c["subject"].lower() for k in ["paper(", "paper:", "paper2", "paper3", "paper4", "paper8", "paper9", "paper10", "taiwan-vt", "vix-suff", "garch-x", "crypto-fear", "vol-absor", "vt-trend", "leverage-dir", "vt-crowd"])]
    progress["M3 把學術論文寫好"] = {
        "evidence": f"{len(paper_commits)} paper-related commits",
        "status": "active" if len(paper_commits) > 0 else "idle",
        "note": "body.tex 更新 / reproduce gate / paper-update sync" if len(paper_commits) > 0 else "本窗口無論文異動",
    }

    # M4 平台運營 — fix/ops/alert/cron commits
    ops_commits = [c for c in commits if any(k in c["subject"].lower() for k in ["fix(", "fix:", "alert", "cron", "release", "ops:", "ops("])]
    progress["M4 把網頁平台運營好"] = {
        "evidence": f"{len(ops_commits)} ops/fix commits",
        "status": "active" if len(ops_commits) > 0 else "idle",
        "note": "ops 修復 / alert 處理 / cron 調整" if len(ops_commits) > 0 else "本窗口無 ops 異動",
    }

    # M5 曝光 — published articles (re-use M1 but specifically count published)
    progress["M5 把曝光流量拉高"] = {
        "evidence": f"{len(articles['published'])} published (流量 surface)",
        "status": "active" if len(articles["published"]) > 0 else "idle",
        "note": "新發佈進入索引 + Supabase mirror" if len(articles["published"]) > 0 else "釋出排程未達 due",
    }
    return progress


def _notable_events(commits: list[dict], notifs: list[dict], health: dict) -> list[str]:
    """Detect notable / anomalous events worth flagging."""
    events = []
    # Alert breaches now
    if health.get("alert_breaches", 0) > 0:
        events.append(f"⚠️ 當前有 {health['alert_breaches']} 個 alert breach（總 check {health.get('alert_total_checked','?')} 個）")
    # Release cadence stretched
    rg = health.get("last_release_gap_min")
    interval = health.get("release_interval_min", 180)
    if rg is not None and rg > interval + 60:
        events.append(f"⚠️ 釋出 gap {rg:.0f}min 超過 interval+60min ({interval+60}min) — 應 review piggy-back")
    # Draft pool low
    dc = health.get("draft_count")
    if dc is not None and dc < 4:
        events.append(f"🔴 Draft pool 僅 {dc} 篇（<4 threshold）— 派寫文章 agent 優先")
    # Large commits (>1000 lines or > 5 files)
    # (we don't have line counts here, so skip)
    # Many fix commits → instability indicator
    fix_count = sum(1 for c in commits if c["subject"].lower().startswith("fix"))
    if fix_count >= 3:
        events.append(f"🔧 {fix_count} 個 fix commits — 系統異動較多，留意 regression")
    # Knowledge.json bloat
    ks = health.get("knowledge_size_mb")
    if ks and ks > 50:
        events.append(f"📊 knowledge.json {ks}MB（>50MB 建議跑 memory-health audit）")
    # Recent critical alert in notifs
    for n in notifs:
        if n.get("level") == "critical":
            events.append(f"🚨 critical alert 記錄：{n['time']} {n.get('title','')[:60]}")
            break  # 1 example sufficient
    # Worktree lingering
    wt = health.get("active_worktrees", [])
    if isinstance(wt, list) and len(wt) >= 3:
        events.append(f"🌿 {len(wt)} 個 worktree 進行中 — merge 節奏需跟上")
    return events


def _recommendations(commits: list[dict], articles: dict, health: dict, work: list[dict]) -> list[str]:
    """Rule-based next-6h playbook."""
    recs = []
    # Draft pool top-up
    dc = health.get("draft_count")
    if dc is not None and dc < 10:
        recs.append(f"草稿池僅 {dc} 篇 — 派 agent 寫 {min(3, max(1, 10-dc))} 篇 daily_article 補池（次優先）")
    # Release cadence
    rg = health.get("last_release_gap_min")
    interval = health.get("release_interval_min", 180)
    if rg is not None and rg > interval:
        recs.append(f"釋出已 due（gap={rg:.0f}min > interval={interval}min）— 跑 `VOLPRED_ACTOR=claude uv run volpred ops release-pool-by-settings`")
    # New experiments pending Codex
    if any("experiment" in c["subject"].lower() and "merge" in c["subject"].lower() for c in commits):
        recs.append("最近 merge 了實驗 worktree — 主線程確認已跑 Codex review + knowledge.json 入庫")
    # Pending tasks high
    pending = health.get("pending_tasks", 0)
    if pending > 100:
        recs.append(f"pending tasks {pending} 個 — 排程下次 refill_task_pool 視必要性，避免 noise 累積")
    # Worktree backlog
    wt_count = health.get("active_worktrees", 0)
    if isinstance(wt_count, int) and wt_count >= 2:
        recs.append(f"{wt_count} 個 worktree 進行 — 等下批 agent 完成通知再合併")
    # Paper milestone — if K1370 / Paper 2 paper commits seen
    paper_milestone = [c for c in commits if any(k in c["subject"].lower() for k in ["k1370", "paper2", "paper 2", "taiwan-vt"])]
    if paper_milestone:
        recs.append("Paper 2 narrative 有更新 — 確認 `reproduce.py` gate 仍 green + Supabase paper-update 已 sync")
    # If quiet (very few commits), suggest dispatch
    if len(commits) < 3:
        recs.append("窗口活動偏低（commits < 3）— 檢查 dispatch slot 是否閒置 + agent 是否有 hang")
    # If many ops fix, suggest cooldown
    ops_count = sum(1 for c in commits if any(k in c["subject"].lower() for k in ["fix(", "fix:", "alert", "cron"]))
    if ops_count >= 5:
        recs.append(f"窗口內 {ops_count} 個 ops fix — 系統可能仍不穩，建議下窗口減少並行 dispatch 觀察")
    if not recs:
        recs.append("各 KPI 正常，維持當前節奏")
    return recs


def _executive_summary(commits: list[dict], articles: dict, work: list[dict], health: dict, mission: dict, events: list[str], cats: dict) -> str:
    """1-2 sentence summary at top of report."""
    if len(commits) == 0 and len(articles["published"]) == 0 and len(articles["drafts"]) == 0:
        return "本窗口無實質活動（無 commits、無新文章），可能在等 agent 結果或 idle slot。"
    active_missions = [k for k, v in mission.items() if v["status"] == "active"]
    dominant = max(cats.items(), key=lambda x: x[1]) if cats else ("無", 0)
    pieces = [f"本窗口 {len(commits)} commits + {len(articles['published'])} published + {len(articles['drafts'])} drafts；{len(active_missions)}/5 Mission 目標有活動（{'/'.join(m.split()[0] for m in active_missions)}）。"]
    if dominant[1] > 0:
        pieces.append(f"主要產出類型：{dominant[0]} ({dominant[1]} 件)。")
    if events:
        pieces.append(f"{len(events)} 個值得關注事件（見下表）。")
    else:
        pieces.append("無異常事件。")
    return " ".join(pieces)


def _categorize_commits(commits: list[dict]) -> dict[str, int]:
    cats = {"paper/experiment": 0, "fix/ops": 0, "feed/article": 0, "infra/governance": 0, "other": 0}
    for c in commits:
        s = c["subject"].lower()
        if any(k in s for k in ["paper", "k13", "k12", "k11", "experiment", "k10", "k9"]):
            cats["paper/experiment"] += 1
        elif any(k in s for k in ["fix", "alert", "cron", "release", "ops"]):
            cats["fix/ops"] += 1
        elif any(k in s for k in ["feed:", "mile_", "trending_repost", "daily_article", "publish"]):
            cats["feed/article"] += 1
        elif any(k in s for k in ["chore", "skill", "config", "docs", "rules", "memory"]):
            cats["infra/governance"] += 1
        else:
            cats["other"] += 1
    return cats


def build_html() -> tuple[str, str, str]:
    commits = _commits_in_window()
    files = _files_changed_in_window()
    work = _work_log_entries()
    notifs = _new_notifications()
    articles = _articles_in_window()
    worktrees = _active_worktrees()
    cats = _categorize_commits(commits)
    top_files = sorted(files.items(), key=lambda x: -x[1])[:12]
    health = _platform_health()
    health["active_worktrees"] = worktrees
    mission = _mission_progress(commits, articles, work)
    events = _notable_events(commits, notifs, health)
    recs = _recommendations(commits, articles, health, work)
    exec_summary = _executive_summary(commits, articles, work, health, mission, events, cats)

    title = f"6h 平台運營彙報 {SINCE.strftime('%Y-%m-%d %H:%MZ')} → {NOW.strftime('%H:%MZ')}"

    # ── HTML ───────────────────────────────────────────────────
    css = """
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang TC", "Microsoft JhengHei", sans-serif; color: #222; max-width: 760px; margin: 24px auto; padding: 0 16px; line-height: 1.55; }
      h1 { font-size: 20px; border-bottom: 2px solid #2a6df4; padding-bottom: 6px; color: #1d4ed8; }
      h2 { font-size: 16px; margin-top: 28px; padding: 6px 10px; background: #f1f5f9; border-left: 4px solid #2563eb; }
      .meta { color: #64748b; font-size: 13px; margin-bottom: 12px; }
      .badges { margin: 8px 0 16px; }
      .badge { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 3px 9px; border-radius: 10px; font-size: 12px; margin-right: 6px; }
      .badge.paper { background: #fef3c7; color: #92400e; }
      .badge.ops { background: #fee2e2; color: #991b1b; }
      .badge.feed { background: #dcfce7; color: #166534; }
      .badge.infra { background: #ede9fe; color: #5b21b6; }
      table { border-collapse: collapse; width: 100%; margin: 8px 0 18px; font-size: 13px; }
      th, td { border-bottom: 1px solid #e2e8f0; padding: 6px 9px; text-align: left; vertical-align: top; }
      th { background: #f8fafc; font-weight: 600; color: #475569; }
      code { background: #f1f5f9; padding: 1px 6px; border-radius: 3px; font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #be123c; }
      .empty { color: #94a3b8; font-style: italic; }
      .level-warn { color: #b45309; }
      .level-critical { color: #b91c1c; font-weight: 600; }
      .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #cbd5e1; font-size: 11px; color: #64748b; }
    </style>
    """

    def esc(s: str) -> str:
        return html.escape(str(s) if s is not None else "")

    parts: list[str] = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{esc(title)}</title>{css}</head><body>"]
    parts.append(f"<h1>{esc(title)}</h1>")
    parts.append(f"<div class='meta'>窗口 {esc(SINCE.strftime('%Y-%m-%d %H:%M UTC'))} → {esc(NOW.strftime('%H:%M UTC'))} ｜ 寄送 {esc(NOW.strftime('%Y-%m-%d %H:%M UTC'))} ｜ 報告人：AI 平台運營經理（自主系統）</div>")

    # ───────────────────── Executive Summary ─────────────────────
    parts.append("<h2>執行摘要</h2>")
    parts.append(f"<p style='background:#fffbeb;border-left:4px solid #f59e0b;padding:10px 14px;margin:10px 0;font-size:14px;'>{esc(exec_summary)}</p>")

    # ───────────────────── Mission Goals Progress ─────────────────────
    parts.append("<h2>Mission 5 大目標推進</h2>")
    parts.append("<table><thead><tr><th>目標</th><th>狀態</th><th>本期證據</th><th>備註</th></tr></thead><tbody>")
    for goal, info in mission.items():
        status_emoji = "✅" if info["status"] == "active" else "⚪"
        status_label = "active" if info["status"] == "active" else "idle"
        parts.append(f"<tr><td><strong>{esc(goal)}</strong></td><td>{status_emoji} {esc(status_label)}</td><td>{esc(info['evidence'])}</td><td>{esc(info['note'])}</td></tr>")
    parts.append("</tbody></table>")

    # ───────────────────── Platform Health Dashboard ─────────────────────
    parts.append("<h2>平台健康儀表板</h2>")
    parts.append("<table><thead><tr><th>指標</th><th>當前值</th><th>判讀</th></tr></thead><tbody>")
    # Draft pool
    dc = health.get("draft_count", "?")
    dc_judge = "🟢 充足" if isinstance(dc, int) and dc >= 10 else ("🟡 注意" if isinstance(dc, int) and dc >= 4 else "🔴 偏低")
    parts.append(f"<tr><td>Draft pool 文章數</td><td>{esc(dc)}</td><td>{dc_judge}</td></tr>")
    parts.append(f"<tr><td>Published 累積</td><td>{esc(health.get('published_total', '?'))}</td><td>—</td></tr>")
    # Release cadence
    rg = health.get("last_release_gap_min")
    interval = health.get("release_interval_min", "?")
    if rg is not None and isinstance(interval, int):
        rg_judge = "🟢 正常" if rg <= interval + 30 else ("🟡 接近警戒" if rg <= interval + 60 else "🔴 已 due / 超期")
        parts.append(f"<tr><td>釋出 gap (interval={interval}min)</td><td>{rg:.0f} min</td><td>{rg_judge}</td></tr>")
    parts.append(f"<tr><td>Last release time</td><td>{esc(health.get('last_release_at', '?'))}</td><td>—</td></tr>")
    # Alerts
    ab = health.get("alert_breaches", 0)
    at = health.get("alert_total_checked", "?")
    ab_judge = "🟢 無 breach" if ab == 0 else f"🔴 {ab} breach"
    parts.append(f"<tr><td>Alert breaches (current)</td><td>{ab} / {esc(at)} checks</td><td>{ab_judge}</td></tr>")
    # Knowledge.json
    ks = health.get("knowledge_size_mb", "?")
    ks_judge = "🟢 正常" if isinstance(ks, (int, float)) and ks < 50 else ("🟡 偏大" if isinstance(ks, (int, float)) and ks < 100 else "🔴 過大")
    parts.append(f"<tr><td>knowledge.json size</td><td>{esc(ks)} MB</td><td>{ks_judge}</td></tr>")
    parts.append(f"<tr><td>knowledge.json mtime</td><td>{esc(health.get('knowledge_mtime', '?'))}</td><td>—</td></tr>")
    # Pending tasks
    pt = health.get("pending_tasks", "?")
    parts.append(f"<tr><td>Pending tasks queue</td><td>{esc(pt)}</td><td>—</td></tr>")
    # Active worktrees
    parts.append(f"<tr><td>Active worktrees</td><td>{len(worktrees)}</td><td>{'🟢' if len(worktrees) <= 2 else '🟡'}</td></tr>")
    parts.append("</tbody></table>")

    # ───────────────────── Notable Events ─────────────────────
    parts.append("<h2>異常與值得關注事件</h2>")
    if events:
        parts.append("<ul>")
        for e in events:
            parts.append(f"<li>{esc(e)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p class='empty'>無異常 — 系統運作平順。</p>")

    # ───────────────────── Recommendations ─────────────────────
    parts.append("<h2>下個 6h 建議行動</h2>")
    parts.append("<ol>")
    for r in recs:
        parts.append(f"<li>{esc(r)}</li>")
    parts.append("</ol>")

    parts.append("<hr style='margin:32px 0;border:none;border-top:1px solid #cbd5e1;'>")
    parts.append("<h2 style='color:#64748b;'>原始數據（供查證）</h2>")

    # Categories badges
    parts.append("<div class='badges'>")
    for k, v in cats.items():
        if v == 0:
            continue
        cls = ""
        if "paper" in k: cls = "paper"
        elif "fix" in k: cls = "ops"
        elif "feed" in k: cls = "feed"
        elif "infra" in k: cls = "infra"
        parts.append(f"<span class='badge {cls}'>{esc(k)}: {v}</span>")
    parts.append("</div>")

    # Commits
    parts.append(f"<h2>Git commits ({len(commits)})</h2>")
    if commits:
        parts.append("<table><thead><tr><th>SHA</th><th>Subject</th><th>Time</th></tr></thead><tbody>")
        for c in commits[:30]:
            short_time = c["iso"].split(" ")[1][:5] if " " in c["iso"] else c["iso"][:5]
            parts.append(f"<tr><td><code>{esc(c['sha'])}</code></td><td>{esc(c['subject'])}</td><td>{esc(short_time)}</td></tr>")
        if len(commits) > 30:
            parts.append(f"<tr><td colspan='3' class='empty'>… +{len(commits)-30} more</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p class='empty'>(無)</p>")

    # Articles
    parts.append(f"<h2>文章 (published {len(articles['published'])} / drafts {len(articles['drafts'])})</h2>")
    if articles["published"] or articles["drafts"]:
        parts.append("<table><thead><tr><th>Status</th><th>ID</th><th>Audience</th><th>Title</th><th>Time</th></tr></thead><tbody>")
        for a in articles["published"][:15]:
            parts.append(f"<tr><td><span class='badge feed'>published</span></td><td><code>{esc(a['id'])}</code></td><td>{esc(a['audience'])}</td><td>{esc(a['title'])}</td><td>{esc(a['ts'])}</td></tr>")
        for a in articles["drafts"][:10]:
            parts.append(f"<tr><td><span class='badge'>draft</span></td><td><code>{esc(a['id'])}</code></td><td>{esc(a['audience'])}</td><td>{esc(a['title'])}</td><td>{esc(a['ts'])}</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p class='empty'>(無)</p>")

    # Work log
    parts.append(f"<h2>Work log task entries ({len(work)})</h2>")
    if work:
        parts.append("<table><thead><tr><th>Type</th><th>Result</th><th>Title</th></tr></thead><tbody>")
        for w in work[-15:]:
            ttype = w.get("task_type", "?")
            result = w.get("result") or w.get("outcome") or w.get("status", "?")
            title_w = (w.get("title") or w.get("task") or w.get("description", ""))[:120]
            parts.append(f"<tr><td><code>{esc(ttype)}</code></td><td>{esc(result)}</td><td>{esc(title_w)}</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p class='empty'>(無)</p>")

    # Worktrees
    if worktrees:
        parts.append(f"<h2>進行中 worktree agents ({len(worktrees)})</h2>")
        parts.append("<ul>")
        for w in worktrees:
            parts.append(f"<li><code>{esc(w)}</code></li>")
        parts.append("</ul>")

    # Notifications
    if notifs:
        parts.append(f"<h2>Notifications ({len(notifs)})</h2>")
        parts.append("<table><thead><tr><th>Time</th><th>Level</th><th>Title</th></tr></thead><tbody>")
        for n in notifs[-12:]:
            lvl = n.get("level", "")
            lvl_class = "level-warn" if lvl == "warn" else ("level-critical" if lvl == "critical" else "")
            parts.append(f"<tr><td>{esc(n['time'])}</td><td class='{lvl_class}'>{esc(lvl)}</td><td>{esc(n['title'])}</td></tr>")
        parts.append("</tbody></table>")

    # Top files
    if top_files:
        parts.append("<h2>Top files changed</h2>")
        parts.append("<table><thead><tr><th>×</th><th>Path</th></tr></thead><tbody>")
        for fname, n in top_files:
            parts.append(f"<tr><td>{n}</td><td><code>{esc(fname)}</code></td></tr>")
        parts.append("</tbody></table>")

    parts.append(f"<div class='footer'>VolPred 自主運營系統 ｜ Generated by scripts/work_summary_6h.py @ {esc(NOW.isoformat())}</div>")
    parts.append("</body></html>")
    html_body = "\n".join(parts)

    # ── Plain text fallback ───────────────────────────────────
    text_lines = [
        f"# {title}",
        f"窗口 {SINCE.strftime('%Y-%m-%d %H:%M UTC')} → {NOW.strftime('%H:%M UTC')}",
        "",
        "## 執行摘要",
        exec_summary,
        "",
        "## Mission 推進",
    ]
    for goal, info in mission.items():
        text_lines.append(f"- [{info['status']}] {goal}: {info['evidence']} — {info['note']}")
    text_lines.append("")
    text_lines.append("## 平台健康")
    text_lines.append(f"- Draft pool: {health.get('draft_count','?')} 篇 ｜ Published 累積: {health.get('published_total','?')}")
    text_lines.append(f"- 釋出 gap: {health.get('last_release_gap_min','?')}min (interval={health.get('release_interval_min','?')}min, last={health.get('last_release_at','?')})")
    text_lines.append(f"- Alerts: {health.get('alert_breaches',0)}/{health.get('alert_total_checked','?')} breach")
    text_lines.append(f"- knowledge.json: {health.get('knowledge_size_mb','?')}MB @ {health.get('knowledge_mtime','?')}")
    text_lines.append(f"- Pending tasks: {health.get('pending_tasks','?')} ｜ Worktrees: {len(worktrees)}")
    text_lines.append("")
    if events:
        text_lines.append("## 異常事件")
        for e in events:
            text_lines.append(f"- {e}")
        text_lines.append("")
    text_lines.append("## 下個 6h 建議")
    for r in recs:
        text_lines.append(f"- {r}")
    text_lines.append("")
    text_lines.append(f"## Commits ({len(commits)})")
    for c in commits[:20]:
        text_lines.append(f"- {c['sha']} {c['subject']}")
    if len(commits) > 20:
        text_lines.append(f"- ... +{len(commits)-20} more")
    text_lines.append("")
    text_lines.append(f"## 文章 (published {len(articles['published'])} / drafts {len(articles['drafts'])})")
    for a in articles["published"][:10]:
        text_lines.append(f"- [{a['ts']}] published {a['id']} {a['title']}")
    for a in articles["drafts"][:5]:
        text_lines.append(f"- [{a['ts']}] draft {a['id']} {a['title']}")
    text_lines.append("")
    text_lines.append(f"## Work log ({len(work)} entries)")
    for w in work[-10:]:
        text_lines.append(f"- [{w.get('task_type','?')}/{w.get('result') or w.get('outcome') or w.get('status','?')}] {(w.get('title') or w.get('task') or '')[:60]}")
    if worktrees:
        text_lines.append("")
        text_lines.append(f"## Active worktrees ({len(worktrees)}): {', '.join(worktrees)}")
    text_body = "\n".join(text_lines)

    return title, html_body, text_body


def main() -> int:
    from volpred.publisher.email_notifier import EmailNotifier
    from volpred.ops.alerts import ALERT_RECIPIENT

    title, html_body, text_body = build_html()
    subject = f"[VolPred 6h Summary] {title}"

    notifier = EmailNotifier(storage_dir="storage")
    try:
        notif_id = notifier.notify(
            subject=subject,
            body=text_body,
            html_body=html_body,
            level="info",
            metadata={
                "notification_type": "work_summary_6h",
                "window_start": SINCE.isoformat(),
                "window_end": NOW.isoformat(),
            },
            recipients=[ALERT_RECIPIENT],
        )
        print(f"[work_summary_6h] sent notification_id={notif_id} subject={subject}")
        return 0
    except Exception as e:
        print(f"[work_summary_6h] error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
