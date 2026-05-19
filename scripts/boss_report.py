#!/usr/bin/env python3
"""Boss report — HTML email to user every 4h (or on demand).

Structure (per user 2026-05-19 directive — user is boss, receives reports only):
  1. Platform state (dashboard snapshot)
  2. Cycle activity (commits, dispatches)
  3. Autonomous decisions made
  4. Signal for boss (strategic input wanted, no ask)
  5. Next cycle plan (no input needed)
  6. Direction recommendations

Reuses EmailNotifier.notify(html_body=...) — same multipart/alternative as 6h summary.
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

NOW = datetime.now(timezone.utc)
WINDOW = timedelta(hours=4)
SINCE = NOW - WINDOW


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


def _dashboard():
    try:
        out = subprocess.check_output(
            ["uv", "run", "python", "scripts/ops_dashboard.py"],
            cwd=str(PROJECT_ROOT), stderr=subprocess.STDOUT, text=True, timeout=120,
        )
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        # dashboard exits 1 on critical but still emits JSON
        try: return json.loads(e.output)
        except: return {"overall_status": "error", "sections": [], "_err": str(e)[:200]}
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
            except: pass
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
    except: return {"total": 0, "by_type": {}, "by_priority": {}}


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
                except: pass
        except: pass
    return out


def _cycle_intent():
    """Read my current cycle's intent + goal + plan from a small state file."""
    f = PROJECT_ROOT / "storage" / "ops" / "current_cycle_intent.json"
    if not f.exists(): return {}
    try: return json.loads(f.read_text())
    except: return {}


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


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def build_html():
    dash = _dashboard()
    commits = _commits_in_window()
    papers = _paper_portfolio()
    pending = _pending_tasks()
    decisions = _autonomous_decisions()
    next_actions = _next_actions()
    intent = _cycle_intent()
    blockers = _blockers()

    title = f"[VolPred Boss Report] {NOW.strftime('%Y-%m-%d %H:%MZ')} 平台運營報告"
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
    parts.append(f"<h1 style='background:{overall_color}'>VolPred Boss Report · {_esc(NOW.strftime('%Y-%m-%d %H:%M UTC'))} · Overall <strong>{_esc(dash.get('overall_status', '?').upper())}</strong></h1>")

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
        parts.append(f"<tr><td>{_esc(s.get('section'))}</td><td class='{st}'>{_esc(st)}</td><td>{_esc(s.get('tldr'))}</td><td class='small'>{_esc(s.get('next') or '—')}</td></tr>")
    parts.append("</table>")

    # 2. Cycle activity
    parts.append(f"<h2>② 本 cycle 活動（過去 {int(WINDOW.total_seconds()/3600)}h）</h2>")
    parts.append(f"<p><strong>{len(commits)}</strong> commits</p>")
    if commits:
        parts.append("<table><tr><th>SHA</th><th>Subject</th><th>Time</th></tr>")
        for c in commits[:15]:
            parts.append(f"<tr><td class='commit'>{_esc(c['sha'])}</td><td>{_esc(c['subject'])}</td><td class='small'>{_esc(c['iso'][11:16])}</td></tr>")
        parts.append("</table>")

    # 3. Pending pool snapshot
    parts.append("<h2>③ Pending 池與論文組合</h2>")
    parts.append(f"<p>Pending tasks: <strong>{pending['total']}</strong></p>")
    parts.append("<p>By type: ")
    for t, n in sorted(pending["by_type"].items(), key=lambda x: -x[1])[:6]:
        parts.append(f"<span class='pill'>{_esc(t)} · {n}</span>")
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
            parts.append(f"<div><span class='pill' style='background:{pill_color};color:white'>{_esc(cat)}</span> <strong>{_esc(d.get('summary', ''))}</strong> <span class='small'>{_esc(d.get('timestamp', '')[:16])}</span></div>")
            for label, key in [("意圖", "intent"), ("推理", "reasoning"), ("執行成果", "outcome"), ("下一步", "next")]:
                v = d.get(key)
                if v:
                    parts.append(f"<div class='small' style='margin-top:4px'><strong>{label}</strong>：{_esc(v)}</div>")
            parts.append("</div>")

    # 5. Next actions
    if next_actions:
        parts.append("<h2>⑤ 下個 cycle 行動（無需你決策）</h2><ul>")
        for a in next_actions:
            parts.append(f"<li>{_esc(a)}</li>")
        parts.append("</ul>")

    # 6. Direction recommendations (read from a markdown file I curate)
    rec_file = PROJECT_ROOT / "docs" / "boss_direction_recommendations.md"
    if rec_file.exists():
        rec_txt = rec_file.read_text()[:3000]
        parts.append("<h2>⑥ 方向建議（你的決策可能改變）</h2>")
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

    parts.append(f"<p class='small'>Report generated {_esc(NOW.isoformat())} · Window {int(WINDOW.total_seconds()/3600)}h · Source: <code>scripts/boss_report.py</code></p>")
    parts.append("</body></html>")

    # Plain-text fallback
    plain_lines = [
        f"VolPred Boss Report — {NOW.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Overall: {dash.get('overall_status', '?').upper()}",
        "",
        "== State ==",
    ]
    for s in dash.get("sections", []):
        plain_lines.append(f"  [{s.get('status', '?')}] {s.get('section')}: {s.get('tldr')}")
    plain_lines.append(f"\n== {len(commits)} commits in window ==")
    for c in commits[:10]:
        plain_lines.append(f"  {c['sha']} {c['subject']}")
    plain_lines.append(f"\n== Pending: {pending['total']} ==")
    plain_lines.append(f"\n== Next actions ==")
    for a in next_actions[:5]:
        plain_lines.append(f"  {a}")
    plain = "\n".join(plain_lines)

    return title, "".join(parts), plain


def main():
    title, html_body, plain = build_html()
    try:
        from volpred.publisher.email_notifier import EmailNotifier
        notifier = EmailNotifier()
        # Use notify() with html_body for multipart/alternative
        from volpred.ops.alerts import ALERT_RECIPIENT
        # CLI flag --force bypasses dedup for manual / immediate re-send
        force = "--force" in sys.argv
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
