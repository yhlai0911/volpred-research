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

    title = f"6h 工作摘要 {SINCE.strftime('%Y-%m-%d %H:%MZ')} → {NOW.strftime('%H:%MZ')}"

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
    parts.append(f"<div class='meta'>窗口 {esc(SINCE.strftime('%Y-%m-%d %H:%M UTC'))} → {esc(NOW.strftime('%H:%M UTC'))} ｜ 寄送 {esc(NOW.strftime('%Y-%m-%d %H:%M UTC'))}</div>")

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
        f"## Commits ({len(commits)})",
    ]
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
