#!/usr/bin/env python3
"""Boss report — the SOLE periodic operations email to the boss.

Cadence (config/runtime_schedules.json `boss_report_4h`, TW 08:10 / 14:10 / 20:10):
  - 08:10 morning  : --window-hours 12 (covers overnight since the 20:10 close)
  - 14:10 midday   : --window-hours 6  (covers since 08:10)
  - 20:10 evening  : --daily-close     (24h window + day-close sections)

Structure (per user 2026-05-19 directive — user is boss, receives reports only):
  1. Platform state (dashboard snapshot)
  2. Cycle activity (commits, dispatches)
  3. Autonomous decisions made
  4. Signal for boss (strategic input wanted, no ask)
  5. Next cycle plan (no input needed)
  6. Direction recommendations
  Daily-close extras (2026-07-20 WS-H2, merged from retired work_summary_6h):
  Mission-5 progress, articles published/drafted, work-log entries, active
  worktree agents, notifications, top files changed.

Channel contract (WS-H2): work_summary_6h is RETIRED — its content lives here
in the 20:10 daily-close edition. Do not add a second periodic boss email; the
outbound-channel matrix in .claude/skills/platform-ops-manager/references/
loop-health-and-dreaming.md is the owner of that rule.

Reuses EmailNotifier.notify(html_body=...) (multipart/alternative).
"""
from __future__ import annotations
import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.ops.boss_facing import plainify_boss_text

# Absolute uv path — host-cron processes get a minimal PATH (/usr/bin:/bin)
# without Homebrew, so bare "uv" subprocess calls fail with FileNotFoundError
# (2026-05-22: 16:10 boss_report Overall ERROR — dashboard + cron_review both
# "[Errno 2] No such file or directory: 'uv'"). Resolve once, absolutely.
import shutil as _shutil
UV = next((p for p in ("/opt/homebrew/bin/uv",
                       str(Path.home() / ".local/bin/uv"),
                       "/usr/local/bin/uv") if Path(p).exists()),
          _shutil.which("uv") or "uv")

# 所有 email 顯示時間以台灣時間 (UTC+8) 為準（用戶 2026-05-20 要求）
TW = timezone(timedelta(hours=8))
NOW = datetime.now(timezone.utc)        # 內部比較仍用 UTC（git log / ISO 比對）
NOW_TW = NOW.astimezone(TW)             # 顯示用台灣時間
WINDOW = timedelta(hours=4)
SINCE = NOW - WINDOW
_REPORT_WARNINGS: list[str] = []


def _configure_window(hours: float) -> None:
    """Set the module-level reporting window before build_html().

    Collectors read module globals WINDOW/SINCE at call time, so mutating them
    once at startup (main/argparse) reconfigures every section consistently.
    """
    global WINDOW, SINCE
    WINDOW = timedelta(hours=hours)
    SINCE = NOW - WINDOW


def _warn_report(source: str, exc: Exception) -> None:
    _REPORT_WARNINGS.append(f"{source}: {type(exc).__name__}: {str(exc)[:200]}")


def _git(args):
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT)] + args,
            stderr=subprocess.STDOUT, text=True, timeout=30,
        )
    except Exception as e:
        return f"(git failed: {e})"


def _commits_in_window():
    raw = _git(["log", f"--since={SINCE.isoformat()}", "--pretty=format:%h|%s|%ai"])
    out = []
    for ln in raw.splitlines():
        if "|" not in ln: continue
        parts = ln.split("|", 2)
        if len(parts) == 3:
            out.append({"sha": parts[0], "subject": parts[1], "iso": parts[2]})
    return out


def _cron_review():
    """Per-scheduler run outcomes — did each cron job complete / succeed?
    Added 2026-05-21: the boss email must let the boss GRASP whether the
    autonomous schedulers actually ran, not just that they exist."""
    try:
        return subprocess.run(
            [UV, "run", "python", "scripts/cron_review.py"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=90,
        ).stdout.strip()
    except Exception as e:
        return f"cron_review 取得失敗：{str(e)[:200]}"


def _dashboard():
    try:
        out = subprocess.check_output(
            [UV, "run", "python", "scripts/ops_dashboard.py"],
            cwd=str(PROJECT_ROOT), stderr=subprocess.STDOUT, text=True, timeout=120,
        )
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        # dashboard exits 1 on critical but still emits JSON
        try:
            return json.loads(e.output)
        except Exception as parse_exc:
            _warn_report("ops_dashboard JSON parse failed", parse_exc)
            return {"overall_status": "error", "sections": [], "_err": str(e)[:200]}
    except Exception as e:
        return {"overall_status": "error", "sections": [], "_err": str(e)[:200]}


def _paper_portfolio():
    p = PROJECT_ROOT / "paper"
    out = []
    if not p.exists(): return out
    for sub in sorted(p.iterdir()):
        if not sub.is_dir(): continue
        readme = sub / "README.md"
        status = "?"
        if readme.exists():
            try:
                txt = readme.read_text()[:2000]
                for line in txt.splitlines():
                    low = line.lower()
                    if "status" in low and (":" in line or "：" in line):
                        status = line.split(":" if ":" in line else "：", 1)[1].strip()[:40]
                        break
            except Exception as exc:
                _warn_report(f"paper README parse failed ({sub.name})", exc)
        out.append({"name": sub.name, "status": status})
    return out


def _pending_tasks():
    p = PROJECT_ROOT / "storage" / "next_tasks.json"
    if not p.exists(): return {"total": 0, "by_type": {}, "by_priority": {}}
    try:
        data = json.loads(p.read_text())
        pending = [t for t in data if t.get("status") == "pending"]
        bt, bp = {}, {}
        for t in pending:
            bt[t.get("task_type", "?")] = bt.get(t.get("task_type", "?"), 0) + 1
            bp[str(t.get("priority", "?"))] = bp.get(str(t.get("priority", "?")), 0) + 1
        return {"total": len(pending), "by_type": bt, "by_priority": bp}
    except Exception as exc:
        _warn_report("next_tasks read failed", exc)
        return {"total": 0, "by_type": {}, "by_priority": {}}


def _autonomous_decisions():
    """Read from a log of autonomous decisions I keep. Each entry includes intent + reasoning + outcome + next."""
    decisions_log = PROJECT_ROOT / "storage" / "ops" / "autonomous_decisions.jsonl"
    out = []
    if decisions_log.exists():
        try:
            for line in decisions_log.read_text().splitlines():
                try:
                    d = json.loads(line)
                    ts = d.get("timestamp", "")
                    if ts >= SINCE.isoformat():
                        out.append(d)
                except Exception as exc:
                    _warn_report("autonomous_decisions line parse failed", exc)
        except Exception as exc:
            _warn_report("autonomous_decisions read failed", exc)
    return out


def _cycle_intent():
    """Read my current cycle's intent + goal + plan from a small state file."""
    f = PROJECT_ROOT / "storage" / "ops" / "current_cycle_intent.json"
    if not f.exists(): return {}
    try: return json.loads(f.read_text())
    except Exception as exc:
        _warn_report("current_cycle_intent read failed", exc)
        return {}


def _blockers():
    """Read boss_blockers.md and return a list of items."""
    f = PROJECT_ROOT / "docs" / "boss_blockers.md"
    if not f.exists(): return []
    txt = f.read_text()
    out = []
    current_priority = None
    current_item = None
    for line in txt.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 🔴"):
            current_priority = "P1"
        elif stripped.startswith("## 🟡"):
            current_priority = "P2"
        elif stripped.startswith("## 🟢"):
            current_priority = "P3"
        elif stripped.startswith("## 過去已解"):
            current_priority = None
        elif stripped.startswith("### ") and current_priority:
            if current_item: out.append(current_item)
            current_item = {"priority": current_priority, "title": stripped[4:], "lines": []}
        elif current_item and stripped.startswith("- "):
            current_item["lines"].append(stripped[2:])
    if current_item: out.append(current_item)
    return out


def _next_actions():
    """Read rolling next-actions from ops_team_structure.md."""
    f = PROJECT_ROOT / "docs" / "ops_team_structure.md"
    if not f.exists(): return []
    txt = f.read_text()
    actions = []
    in_section = False
    for line in txt.splitlines():
        if line.startswith("## Next actions"):
            in_section = True; continue
        if in_section:
            if line.startswith("## ") or line.startswith("---"): break
            stripped = line.strip()
            if stripped.startswith(("1.", "2.", "3.", "4.", "5.", "-")):
                actions.append(stripped)
    return actions[:8]


# ── daily-close collectors (ported 2026-07-20 WS-H2 from retired work_summary_6h) ──

def _parse_ts_utc(value):
    """ISO string -> aware UTC datetime, or None (caller logs context)."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _work_log_entries():
    """work_log.json entries whose timestamp falls inside the window."""
    path = PROJECT_ROOT / "storage" / "work_log.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_report("work_log read failed", exc)
        return []
    if not isinstance(data, list):
        _warn_report("work_log schema invalid",
                     TypeError(f"expected list, got {type(data).__name__}"))
        return []
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts") or entry.get("timestamp") or entry.get("completed_at")
        try:
            dt = _parse_ts_utc(ts)
        except Exception as exc:
            _warn_report("work_log entry timestamp unparseable", exc)
            continue
        if dt is not None and dt >= SINCE:
            out.append(entry)
    return out


def _articles_in_window():
    """Feed articles published (or drafted) inside the window."""
    feed_path = PROJECT_ROOT / "storage" / "reports" / "feed.json"
    empty = {"published": [], "drafts": []}
    if not feed_path.exists():
        return empty
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_report("feed read failed", exc)
        return empty
    if not isinstance(feed, list):
        _warn_report("feed schema invalid",
                     TypeError(f"expected list, got {type(feed).__name__}"))
        return empty
    pub, drafts = [], []
    for art in feed:
        if not isinstance(art, dict):
            continue
        try:
            pub_dt = _parse_ts_utc(art.get("published_at"))
        except Exception:
            pub_dt = None  # silent-ok: historical feed rows carry free-form timestamps; one bad row must not spam 1000+ warnings
        try:
            create_dt = _parse_ts_utc(art.get("created_at"))
        except Exception:
            create_dt = None  # silent-ok: same free-form historical timestamp tolerance as published_at above
        row = {"id": art.get("id"), "title": str(art.get("title", ""))[:100],
               "audience": art.get("audience", "")}
        if pub_dt and pub_dt >= SINCE and art.get("status") == "published":
            pub.append({**row, "ts": pub_dt.astimezone(TW).strftime("%H:%M")})
        elif create_dt and create_dt >= SINCE and art.get("status") == "draft":
            drafts.append({**row, "ts": create_dt.astimezone(TW).strftime("%H:%M")})
    return {"published": pub, "drafts": drafts}


def _new_notifications():
    """Notification JSON files written inside the window."""
    nd = PROJECT_ROOT / "storage" / "notifications"
    if not nd.exists():
        return []
    out = []
    for f in sorted(nd.glob("*.json")):
        if f.name == "notification_log.json":
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue  # silent-ok: stat race — notification file removed between glob and stat
        if mtime < SINCE:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            title = data.get("subject") or data.get("title") or str(data.get("message", ""))[:80]
            title = plainify_boss_text(title)
            level = data.get("level") or (data.get("metadata") or {}).get("alert_level", "")
        except Exception as exc:
            _warn_report(f"notification parse failed ({f.name})", exc)
            title, level = f.name, ""
        out.append({"time": mtime.astimezone(TW).strftime("%H:%M"), "title": title, "level": level})
    return out


def _active_worktrees():
    wd = PROJECT_ROOT / ".claude" / "worktrees"
    if not wd.exists():
        return []
    return [d.name for d in wd.iterdir() if d.is_dir() and d.name != ".DS_Store"]


def _files_changed_in_window():
    raw = _git(["log", f"--since={SINCE.isoformat()}", "--name-only", "--pretty=format:"])
    files: dict = {}
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln:
            files[ln] = files.get(ln, 0) + 1
    return files


_KNUM_RE = re.compile(r"\bk\d{3,4}\b", re.IGNORECASE)


def _mission_progress(commits, articles):
    """Heuristic Mission-5 scoring from this window's activity (from work_summary_6h)."""
    progress = {}
    m1 = len(articles["published"]) + len(articles["drafts"])
    progress["M1 把文章寫好"] = {
        "evidence": f"{len(articles['published'])} published + {len(articles['drafts'])} drafts",
        "status": "active" if m1 > 0 else "idle"}
    exp = [c for c in commits if _KNUM_RE.search(c["subject"])
           or any(k in c["subject"].lower() for k in ["experiment", "research("])]
    kn = [c for c in commits if "knowledge" in c["subject"].lower()]
    progress["M2 把實驗與研究做好"] = {
        "evidence": f"{len(exp)} experiment commits + {len(kn)} knowledge updates",
        "status": "active" if (exp or kn) else "idle"}
    paper = [c for c in commits if "paper" in c["subject"].lower()]
    progress["M3 把學術論文寫好"] = {
        "evidence": f"{len(paper)} paper-related commits",
        "status": "active" if paper else "idle"}
    ops = [c for c in commits if any(k in c["subject"].lower()
           for k in ["fix(", "fix:", "alert", "cron", "release", "ops:", "ops("])]
    progress["M4 把網頁平台運營好"] = {
        "evidence": f"{len(ops)} ops/fix commits",
        "status": "active" if ops else "idle"}
    progress["M5 把曝光流量拉高"] = {
        "evidence": f"{len(articles['published'])} published (流量 surface)",
        "status": "active" if articles["published"] else "idle"}
    return progress


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _render_roadmap_coverage():
    """Machine reconcile of the direction doc's roadmap against the real task pool."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from audit_roadmap_coverage import audit

        rep = audit()
    except Exception as exc:
        _warn_report("roadmap_coverage", exc)
        return ""
    if rep.get("error") or not rep.get("items"):
        return ""

    counts = rep["coverage_counts"]
    live, missing = counts.get("live", 0), counts.get("no_task", 0) + counts.get("dangling", 0)
    age = rep.get("doc_age_days")
    tone = "#b91c1c" if (missing or (age is not None and age > 14)) else "#0a8a3a"

    rows = []
    for item in rep["items"]:
        label = {
            "live": ("進行中", "#0a8a3a"),
            "parked": ("已擱置", "#6b7280"),
            "closed": ("已結案（doc 待更新）", "#6b7280"),
            "no_task": ("未開工", "#b91c1c"),
            "dangling": ("task 已消失", "#b91c1c"),
        }.get(item["coverage"], ("?", "#6b7280"))
        rows.append(
            f"<tr><td class='small'>{_esc(item['priority'])}</td>"
            f"<td class='small'>{_esc(item['text'][:52])}</td>"
            f"<td class='small' style='color:{label[1]};white-space:nowrap'>{label[0]}</td>"
            f"<td class='small' style='color:#6b7280'>{_esc(item['task_id'] or '—')}</td></tr>"
        )

    return (
        f"<div style='border-left:4px solid {tone};padding:8px 12px;margin:8px 0;background:#fafbfc'>"
        f"<div class='small'><strong>Roadmap 對帳</strong>（doc 更新於 {_esc(rep['doc_updated'])}，"
        f"{_esc(age)} 天前）：{live} 項有 backing task，{missing} 項未開工。"
        f"來源 <code>scripts/audit_roadmap_coverage.py</code> — 文字宣稱無法蓋過 pool 真實狀態。</div>"
        f"<table style='width:100%;margin-top:6px'>{''.join(rows)}</table></div>"
    )


def _iso_to_tw(iso_str):
    """UTC ISO 字串 → 台灣時間顯示 'MM-DD HH:MM'。失敗回原字串。"""
    if not iso_str:
        return ""
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TW).strftime("%m-%d %H:%M")
    except Exception:
        return iso_str[:16]


def build_html(daily_close: bool = False):
    _REPORT_WARNINGS.clear()
    dash = _dashboard()
    commits = _commits_in_window()
    papers = _paper_portfolio()
    pending = _pending_tasks()
    decisions = _autonomous_decisions()
    next_actions = _next_actions()
    intent = _cycle_intent()
    blockers = _blockers()
    articles = _articles_in_window() if daily_close else {"published": [], "drafts": []}
    work = _work_log_entries() if daily_close else []
    worktrees = _active_worktrees() if daily_close else []
    notifs = _new_notifications() if daily_close else []
    files_changed = _files_changed_in_window() if daily_close else {}
    mission = _mission_progress(commits, articles) if daily_close else {}

    edition = "每日日結" if daily_close else "平台運營報告"
    title = f"[VolPred Boss Report] {NOW_TW.strftime('%Y-%m-%d %H:%M')} 台灣時間 {edition}"
    overall_color = {"ok": "#0a8a3a", "warn": "#d97706", "critical": "#b91c1c", "error": "#6b7280"}.get(dash.get("overall_status", "ok"), "#444")

    css = """<style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 720px; margin: 20px auto; padding: 0 16px; color: #1f2937; line-height: 1.5; }
    h1 { font-size: 18px; padding: 12px 14px; border-radius: 6px; color: white; margin: 0 0 16px 0; }
    h2 { font-size: 15px; margin-top: 24px; border-bottom: 2px solid #e5e7eb; padding-bottom: 4px; color: #111827; }
    h3 { font-size: 13px; margin-top: 14px; color: #374151; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0 12px; }
    th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }
    th { background: #f3f4f6; font-weight: 600; }
    .ok { color: #0a8a3a; font-weight: 600; }
    .warn { color: #d97706; font-weight: 600; }
    .critical { color: #b91c1c; font-weight: 600; }
    .error { color: #6b7280; font-weight: 600; }
    .small { font-size: 12px; color: #6b7280; }
    .commit { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #1f2937; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #f3f4f6; font-size: 12px; margin: 2px; }
    code { background: #f3f4f6; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
    </style>"""

    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>{css}</head><body>"]
    parts.append(f"<h1 style='background:{overall_color}'>VolPred Boss Report · {_esc(NOW_TW.strftime('%Y-%m-%d %H:%M'))} 台灣時間 · Overall <strong>{_esc(dash.get('overall_status', '?').upper())}</strong></h1>")

    if _REPORT_WARNINGS:
        parts.append("<h2 style='color:#d97706'>ⓘ Report generation warnings</h2><ul>")
        for warning in _REPORT_WARNINGS:
            parts.append(f"<li class='small'>{_esc(warning)}</li>")
        parts.append("</ul>")

    # 0. Current cycle intent / goal / plan
    if intent:
        parts.append("<h2>⓪ 本 cycle 意圖 / 目標 / 規劃</h2>")
        parts.append("<table>")
        for k_zh, k_en in [("意圖 Intent", "intent"), ("本週目標 Weekly Goal", "weekly_goal"),
                            ("本 cycle 計劃 Plan", "plan"), ("成功標準 Success Criteria", "success_criteria"),
                            ("已知風險 Known Risks", "risks")]:
            v = intent.get(k_en)
            if v:
                if isinstance(v, list): v = "<br>".join("• " + _esc(x) for x in v)
                else: v = _esc(v)
                parts.append(f"<tr><td><strong>{_esc(k_zh)}</strong></td><td>{v}</td></tr>")
        parts.append("</table>")

    # 1. State
    parts.append("<h2>① 平台狀態</h2>")
    parts.append("<table><tr><th>區段</th><th>狀態</th><th>說明</th><th>建議行動</th></tr>")
    for s in dash.get("sections", []):
        st = s.get("status", "?")
        parts.append(
            f"<tr><td>{_esc(plainify_boss_text(s.get('section')))}</td>"
            f"<td class='{st}'>{_esc(st)}</td>"
            f"<td>{_esc(plainify_boss_text(s.get('tldr')))}</td>"
            f"<td class='small'>{_esc(plainify_boss_text(s.get('next') or '—'))}</td></tr>"
        )
    parts.append("</table>")

    # 1b. Cron run outcomes — did the autonomous schedulers actually run?
    cron_txt = _cron_review()
    parts.append("<h2>①-b 排程器成果掌握（cron 跑完沒 / 成功沒）</h2>")
    cron_cls = "critical" if "🔴" in cron_txt else ("warn" if "⚠️" in cron_txt else "ok")
    parts.append(f"<p class='small'>每個定時排程器的 runs / exit / 完成狀態。"
                 f"<span class='{cron_cls}'>"
                 f"{'有需要掌握的項目 ↓' if cron_cls != 'ok' else '全部正常'}</span></p>")
    parts.append(f"<pre style='font-size:11px;background:#f9fafb;padding:8px;"
                 f"border-radius:4px;overflow-x:auto'>{_esc(cron_txt)}</pre>")

    # 2. Cycle activity
    parts.append(f"<h2>② 本 cycle 活動（過去 {int(WINDOW.total_seconds()/3600)}h）</h2>")
    parts.append(f"<p><strong>{len(commits)}</strong> commits</p>")
    if commits:
        parts.append("<table><tr><th>SHA</th><th>Subject</th><th>Time</th></tr>")
        for c in commits[:15]:
            parts.append(f"<tr><td class='commit'>{_esc(c['sha'])}</td><td>{_esc(c['subject'])}</td><td class='small'>{_esc(c['iso'][11:16])}</td></tr>")
        parts.append("</table>")

    # 2b. Daily-close sections (20:10 edition; merged from retired work_summary_6h)
    if daily_close:
        parts.append("<h2>②-b 日結 · Mission 5 大目標推進（24h）</h2>")
        parts.append("<table><tr><th>Mission</th><th>狀態</th><th>證據</th></tr>")
        for name, row in mission.items():
            cls = "ok" if row["status"] == "active" else "small"
            parts.append(f"<tr><td>{_esc(name)}</td><td class='{cls}'>{_esc(row['status'])}</td>"
                         f"<td class='small'>{_esc(row['evidence'])}</td></tr>")
        parts.append("</table>")

        parts.append(f"<h2>②-c 日結 · 文章（published {len(articles['published'])} / drafts {len(articles['drafts'])}）</h2>")
        if articles["published"] or articles["drafts"]:
            parts.append("<table><tr><th>時間</th><th>狀態</th><th>標題</th><th>受眾</th></tr>")
            for a in articles["published"]:
                parts.append(f"<tr><td class='small'>{_esc(a['ts'])}</td><td class='ok'>published</td>"
                             f"<td>{_esc(plainify_boss_text(a['title']))}</td><td class='small'>{_esc(a['audience'])}</td></tr>")
            for a in articles["drafts"]:
                parts.append(f"<tr><td class='small'>{_esc(a['ts'])}</td><td class='small'>draft</td>"
                             f"<td>{_esc(plainify_boss_text(a['title']))}</td><td class='small'>{_esc(a['audience'])}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p class='small'>窗口內無新文章。</p>")

        parts.append(f"<h2>②-d 日結 · Work log（{len(work)} 筆）</h2>")
        if work:
            parts.append("<ul>")
            for entry in work[:20]:
                label = entry.get("task_type") or entry.get("type") or "task"
                summary = entry.get("summary") or entry.get("title") or entry.get("task_id") or ""
                parts.append(f"<li class='small'><span class='pill'>{_esc(plainify_boss_text(label))}</span> "
                             f"{_esc(plainify_boss_text(str(summary)[:140]))}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p class='small'>窗口內無 work log 條目。</p>")

        if worktrees:
            parts.append(f"<h2>②-e 日結 · 進行中 worktree agents（{len(worktrees)}）</h2><ul>")
            for w in worktrees:
                parts.append(f"<li class='small'><code>{_esc(w)}</code></li>")
            parts.append("</ul>")

        if notifs:
            parts.append(f"<h2>②-f 日結 · Notifications（{len(notifs)}）</h2>")
            parts.append("<table><tr><th>時間</th><th>Level</th><th>標題</th></tr>")
            for n in notifs[:20]:
                cls = "critical" if n.get("level") == "critical" else "small"
                parts.append(f"<tr><td class='small'>{_esc(n['time'])}</td><td class='{cls}'>{_esc(n.get('level') or '-')}</td>"
                             f"<td class='small'>{_esc(n['title'])}</td></tr>")
            parts.append("</table>")

        if files_changed:
            top = sorted(files_changed.items(), key=lambda x: -x[1])[:10]
            parts.append("<h2>②-g 日結 · Top files changed</h2><ul>")
            for path, cnt in top:
                parts.append(f"<li class='small'><code>{_esc(path)}</code> × {cnt}</li>")
            parts.append("</ul>")

    # 3. Pending pool snapshot
    parts.append("<h2>③ Pending 池與論文組合</h2>")
    parts.append(f"<p>Pending tasks: <strong>{pending['total']}</strong></p>")
    parts.append("<p>By type: ")
    for t, n in sorted(pending["by_type"].items(), key=lambda x: -x[1])[:6]:
        parts.append(f"<span class='pill'>{_esc(plainify_boss_text(t))} · {n}</span>")
    parts.append("</p>")
    parts.append("<h3>論文組合</h3>")
    parts.append("<table><tr><th>Paper</th><th>Status</th></tr>")
    for p in papers:
        parts.append(f"<tr><td><code>{_esc(p['name'])}</code></td><td class='small'>{_esc(p['status'])}</td></tr>")
    parts.append("</table>")

    # 4. Autonomous decisions (with intent / reasoning / outcome / next)
    if decisions:
        parts.append("<h2>④ 自主決策 + 推理</h2>")
        for d in decisions:
            cat = d.get("category", "")
            pill_color = {"structural": "#1d4ed8", "delegation": "#7c3aed", "monetization": "#059669",
                          "infra": "#0891b2", "fb_incident": "#b91c1c", "paper": "#ca8a04",
                          "research": "#0a8a3a"}.get(cat, "#6b7280")
            parts.append(f"<div style='border-left:3px solid {pill_color};padding:6px 12px;margin:8px 0;background:#fafbfc'>")
            parts.append(f"<div><span class='pill' style='background:{pill_color};color:white'>{_esc(plainify_boss_text(cat))}</span> <strong>{_esc(plainify_boss_text(d.get('summary', '')))}</strong> <span class='small'>{_esc(_iso_to_tw(d.get('timestamp', '')))} 台灣時間</span></div>")
            for label, key in [("意圖", "intent"), ("推理", "reasoning"), ("執行成果", "outcome"), ("下一步", "next")]:
                v = d.get(key)
                if v:
                    parts.append(f"<div class='small' style='margin-top:4px'><strong>{label}</strong>：{_esc(plainify_boss_text(v))}</div>")
            parts.append("</div>")

    # 5. Next actions
    if next_actions:
        parts.append("<h2>⑤ 下個 cycle 行動（無需你決策）</h2><ul>")
        for a in next_actions:
            parts.append(f"<li>{_esc(plainify_boss_text(a))}</li>")
        parts.append("</ul>")

    # 6. Direction recommendations (read from a markdown file I curate)
    rec_file = PROJECT_ROOT / "docs" / "boss_direction_recommendations.md"
    if rec_file.exists():
        rec_txt = rec_file.read_text()[:3000]
        parts.append("<h2>⑥ 方向建議（你的決策可能改變）</h2>")

        # The doc is prose I write, so it can claim progress that never happened -- it did,
        # for 26 days, until the boss asked (email-12157, 2026-07-18). Lead with the machine
        # reconcile so every roadmap item shows its real pool status before the prose speaks.
        parts.append(_render_roadmap_coverage())

        rendered = _esc(rec_txt).replace("\n", "<br>")
        parts.append(f"<div class='small' style='background:#fafbfc;padding:10px;border-radius:6px'>{rendered}</div>")

    # 7. BLOCKERS — needs boss help (RED FRAME)
    if blockers:
        parts.append("<h2 style='color:#b91c1c;border-bottom-color:#fecaca'>🚨 ⑦ 需要老闆協助 / 資源</h2>")
        parts.append("<p class='small'>下列項目我無法自主解決，需要你的協助或決策。</p>")
        for b in blockers:
            color = {"P1": "#b91c1c", "P2": "#d97706", "P3": "#0a8a3a"}.get(b["priority"], "#6b7280")
            parts.append(f"<div style='border-left:4px solid {color};padding:8px 12px;margin:8px 0;background:#fef2f2'>")
            parts.append(f"<div><span class='pill' style='background:{color};color:white'>{b['priority']}</span> <strong>{_esc(b['title'])}</strong></div>")
            for ln in b["lines"][:6]:
                parts.append(f"<div class='small' style='margin-top:2px'>• {_esc(ln)}</div>")
            parts.append("</div>")

    parts.append(f"<p class='small'>Report generated {_esc(NOW_TW.strftime('%Y-%m-%d %H:%M:%S'))} 台灣時間 · Window {int(WINDOW.total_seconds()/3600)}h · Source: <code>scripts/boss_report.py</code></p>")
    parts.append("</body></html>")

    # Plain-text fallback
    plain_lines = [
        f"VolPred Boss Report — {NOW_TW.strftime('%Y-%m-%d %H:%M')} 台灣時間",
        f"Overall: {dash.get('overall_status', '?').upper()}",
        "",
        "== State ==",
    ]
    if _REPORT_WARNINGS:
        plain_lines.append("\n== Report generation warnings ==")
        for warning in _REPORT_WARNINGS:
            plain_lines.append(f"  {warning}")
    for s in dash.get("sections", []):
        plain_lines.append(
            f"  [{s.get('status', '?')}] "
            f"{plainify_boss_text(s.get('section'))}: {plainify_boss_text(s.get('tldr'))}"
        )
    plain_lines.append(f"\n== {len(commits)} commits in window ==")
    for c in commits[:10]:
        plain_lines.append(f"  {c['sha']} {c['subject']}")
    plain_lines.append(f"\n== Pending: {pending['total']} ==")
    if daily_close:
        plain_lines.append(
            f"\n== Daily close (24h) == published={len(articles['published'])} "
            f"drafts={len(articles['drafts'])} work_log={len(work)} "
            f"worktrees={len(worktrees)} notifications={len(notifs)}"
        )
    plain_lines.append(f"\n== Next actions ==")
    for a in next_actions[:5]:
        plain_lines.append(f"  {plainify_boss_text(a)}")
    plain = "\n".join(plain_lines)

    return title, "".join(parts), plain


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--daily-close", action="store_true",
                        help="24h window + day-close sections (the 20:10 edition)")
    parser.add_argument("--window-hours", type=float, default=None,
                        help="override reporting window in hours (default 4; daily-close forces 24)")
    parser.add_argument("--force", action="store_true",
                        help="bypass email dedup for manual / immediate re-send")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if args.daily_close:
        _configure_window(24.0)
    elif args.window_hours:
        _configure_window(args.window_hours)
    title, html_body, plain = build_html(daily_close=args.daily_close)
    try:
        from volpred.publisher.email_notifier import EmailNotifier
        notifier = EmailNotifier()
        # Use notify() with html_body for multipart/alternative
        from volpred.ops.alerts import ALERT_RECIPIENT
        force = args.force
        result = notifier.notify(
            subject=title,
            body=plain,
            html_body=html_body,
            recipients=[ALERT_RECIPIENT],
            dedupe_type="boss_report",
            dedupe_key=NOW.strftime("%Y-%m-%d-%H"),
            force_send=force,
        )
        print(f"[boss_report] sent notification_id={result.get('notification_id') if isinstance(result, dict) else result} subject={title}")
    except Exception as e:
        print(f"[boss_report] FAILED: {e}", file=sys.stderr)
        # Fallback: write to /tmp for manual inspection
        out_path = Path("/tmp/boss_report_latest.html")
        out_path.write_text(html_body)
        print(f"[boss_report] HTML saved to {out_path}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
