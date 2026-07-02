#!/usr/bin/env python3
"""Daily token-usage report email — embedded beautiful HTML, multi-angle.

Angles (每個都有真數據支撐，來源 = token_usage_report.py 讀 ~/.claude/projects JSONL):
  - 當日總覽（billable / cost / messages / sessions, vs 昨日）
  - 當週每日趨勢（daily_breakdown 每天 billable 長條）
  - 當週 × 使用類型（by_category 19 類 = 使用類型/任務內容）
  - 當週 × 模型（by_model）
  - 週 cap 進度

寄送：EmailNotifier.notify(html_body=...) 內嵌 HTML（非夾檔）。
用法：
  uv run python scripts/token_report_email.py --dry-run   # 只 render 到檔，不寄
  uv run python scripts/token_report_email.py             # 寄給老闆
  uv run python scripts/token_report_email.py --to me@x   # 寄指定收件人
"""
from __future__ import annotations
import argparse
import html
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _claude_project_dir import (  # noqa: E402
    detect_claude_projects_dir as _detect_claude_projects_dir,
)

TPE = ZoneInfo("Asia/Taipei")
CALIB_PATH = ROOT / "config" / "token_quota_calibration.json"


def _load_calibration() -> dict:
    """Weekly cap calibrated to the official Claude usage display (ground truth)."""
    try:
        return json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"derived_weekly_cap": 222_525_528, "official_pct": 0.76, "reading_date": "?"}


CALIB = _load_calibration()
WEEKLY_CAP = int(CALIB.get("derived_weekly_cap") or 222_525_528)

C_INK = "#1f2937"; C_SUB = "#6b7280"; C_LINE = "#e5e7eb"
BARS = ["#2563eb", "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626",
        "#db2777", "#65a30d", "#0d9488", "#9333ea", "#64748b"]


def _report(*flags) -> dict:
    """Call token_usage_report.py (stdlib-only) and return parsed JSON."""
    cmd = [sys.executable, str(ROOT / "scripts" / "token_usage_report.py"),
           "--json", "--no-save", *flags]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"token_usage_report failed rc={out.returncode}: {out.stderr[:300]}")
    return json.loads(out.stdout)


def _thinking_estimate(week_range: str) -> dict:
    """Deduped-by-message.id estimate of reasoning(thinking) as a share of output.
    thinking = output - text_tokens - tool_tokens (text/tool measurable; thinking
    redacted). Calibrated chars/token from text-only turns. Best-effort, honest."""
    import glob
    try:
        ws, we = [s.strip() for s in week_range.split("→")]
    except Exception as exc:
        logging.warning("thinking_estimate: unparseable week_range=%r: %s", week_range, exc)
        return {}
    from datetime import date as _date, timedelta as _td
    we_excl = (_date.fromisoformat(we) + _td(days=1)).isoformat()
    proj = _detect_claude_projects_dir()
    turns: dict = {}
    files = glob.glob(str(proj / "*.jsonl")) + glob.glob(str(proj / "subagents" / "**" / "*.jsonl"), recursive=True)
    for f in files:
        try:
            for line in open(f, encoding="utf-8"):
                try:
                    o = json.loads(line)
                except Exception as exc:
                    logging.debug("thinking_estimate: malformed JSONL line in %s: %s", f, exc)
                    continue
                mm = o.get("message", {})
                if not isinstance(mm, dict) or mm.get("role") != "assistant":
                    continue
                d = str(o.get("timestamp", ""))[:10]
                if not (ws <= d < we_excl):
                    continue
                mid = mm.get("id")
                if not mid:
                    continue
                e = turns.setdefault(mid, {"out": 0, "txt": 0, "tool": 0, "think": False})
                u = mm.get("usage") or {}
                e["out"] = max(e["out"], u.get("output_tokens", 0) or 0)
                for b in (mm.get("content") or []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        e["txt"] += len(b.get("text", "") or "")
                    elif b.get("type") == "tool_use":
                        e["tool"] += len(json.dumps(b.get("input", {}), ensure_ascii=False))
                    elif b.get("type") == "thinking":
                        e["think"] = True
        except Exception as exc:
            logging.warning("thinking_estimate: failed reading %s: %s", f, exc)
            continue
    cc = co = 0
    for e in turns.values():
        if not e["think"] and e["tool"] == 0 and e["out"] > 50:
            cc += e["txt"]; co += e["out"]
    ratio = cc / co if co else 1.5
    out_tot = sum(e["out"] for e in turns.values())
    think = sum(max(0, e["out"] - e["txt"] / ratio - e["tool"] / 3.5) for e in turns.values() if e["think"])
    return {"thinking": int(think), "output_total": out_tot,
            "pct": (think / out_tot * 100) if out_tot else 0}


def _bill(d: dict) -> int:
    if "billable_total" in d:
        return int(d.get("billable_total") or 0)
    return int((d.get("input_tokens") or 0) + (d.get("output_tokens") or 0) + (d.get("cache_create_tokens") or 0))


def m(n) -> str:
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return f"{n:.0f}"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _bar(pct: float, color: str, h: int = 14) -> str:
    pct = max(0.0, min(100.0, pct))
    return (f"<div style='background:#f1f5f9;border-radius:4px;height:{h}px;width:100%;overflow:hidden'>"
            f"<div style='background:{color};height:{h}px;width:{pct:.1f}%'></div></div>")


def build_html(today: dict, week: dict, now_tw: datetime) -> tuple[str, str]:
    tot_t = today.get("totals", {})
    tot_w = week.get("totals", {})
    day_bill = _bill(tot_t)
    week_bill = _bill(tot_w)
    cap_pct = week_bill / WEEKLY_CAP * 100 if WEEKLY_CAP else 0
    week_range = esc(week.get("week_range", ""))

    # per-day
    db = week.get("daily_breakdown", {}) or {}
    days = sorted(db.items())
    day_max = max((_bill(v) for _, v in days), default=1) or 1
    today_key = now_tw.strftime("%Y-%m-%d")

    # categories (week)
    cats = week.get("by_category", {}) or {}
    cat_rows = sorted(((_bill(v), k, v.get("messages", 0)) for k, v in cats.items()), reverse=True)
    cat_max = cat_rows[0][0] if cat_rows else 1

    # models (week)
    models = week.get("by_model", {}) or {}
    mod_rows = sorted(((_bill(v), k, v.get("messages", 0)) for k, v in models.items() if k != "<synthetic>"), reverse=True)

    css = """<style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:680px;margin:18px auto;padding:0 16px;color:#1f2937;line-height:1.55;background:#ffffff}
    h1{font-size:19px;margin:0 0 4px}
    h2{font-size:14px;margin:26px 0 8px;color:#111827;border-bottom:2px solid #e5e7eb;padding-bottom:5px}
    table{width:100%;border-collapse:collapse;font-size:13px}
    td{padding:5px 6px;vertical-align:middle}
    .sub{font-size:12px;color:#6b7280}
    .big{font-size:30px;font-weight:700;letter-spacing:-.5px}
    .card{background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;padding:16px 18px;margin:10px 0}
    .kpi{display:inline-block;margin-right:26px}
    .kpi .n{font-size:20px;font-weight:700}
    .kpi .l{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px}
    .num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
    .tag{font-family:ui-monospace,Menlo,monospace;font-size:12px}
    </style>"""

    p = [f"<!DOCTYPE html><html><head><meta charset='utf-8'>{css}</head><body>"]
    p.append(f"<h1>VolPred Token 使用報表</h1>")
    p.append(f"<div class='sub'>{esc(now_tw.strftime('%Y-%m-%d %H:%M'))} 台灣時間 · 本週 {week_range}</div>")

    # headline: week cap progress
    cap_color = "#059669" if cap_pct < 70 else ("#d97706" if cap_pct < 90 else "#dc2626")
    p.append("<div class='card'>")
    p.append(f"<div class='sub'>本週累計已用（billable）</div>")
    p.append(f"<div class='big' style='color:{cap_color}'>{m(week_bill)} <span style='font-size:15px;color:#6b7280;font-weight:400'>/ {m(WEEKLY_CAP)} cap · {cap_pct:.0f}%</span></div>")
    p.append(_bar(cap_pct, cap_color, 16))
    p.append("<div style='margin-top:14px'>")
    p.append(f"<span class='kpi'><span class='n'>{m(day_bill)}</span><br><span class='l'>今日 billable</span></span>")
    p.append(f"<span class='kpi'><span class='n'>${float(tot_t.get('estimated_cost_usd',0)):,.0f}</span><br><span class='l'>今日估計成本</span></span>")
    p.append(f"<span class='kpi'><span class='n'>{int(tot_t.get('assistant_messages',0)):,}</span><br><span class='l'>今日 AI 訊息</span></span>")
    p.append(f"<span class='kpi'><span class='n'>{int(tot_t.get('unique_sessions',0))}</span><br><span class='l'>今日 session</span></span>")
    p.append("</div></div>")

    # per-day trend
    p.append("<h2>當週每日趨勢（billable）</h2><table>")
    for date, v in days:
        b = _bill(v)
        is_today = date == today_key
        color = "#2563eb" if is_today else "#94a3b8"
        label = f"<strong>{esc(date)}</strong> ·今日" if is_today else esc(date)
        p.append(f"<tr><td style='width:130px'>{label}</td>"
                 f"<td>{_bar(b/day_max*100, color)}</td>"
                 f"<td class='num' style='width:70px'>{m(b)}</td></tr>")
    p.append("</table>")

    # by category
    p.append("<h2>當週 × 使用類型 / 任務內容</h2><table>")
    for b, k, msgs in cat_rows[:12]:
        color = BARS[cat_rows.index((b, k, msgs)) % len(BARS)]
        pct = b / week_bill * 100 if week_bill else 0
        p.append(f"<tr><td class='tag' style='width:170px'>{esc(k)}</td>"
                 f"<td>{_bar(b/cat_max*100, color)}</td>"
                 f"<td class='num' style='width:70px'>{m(b)}</td>"
                 f"<td class='num sub' style='width:44px'>{pct:.0f}%</td></tr>")
    p.append("</table>")
    p.append(f"<div class='sub'>共 {len(cat_rows)} 類；上表為前 12 大。</div>")

    # by model
    p.append("<h2>當週 × 模型</h2><table>")
    for b, k, msgs in mod_rows:
        pct = b / week_bill * 100 if week_bill else 0
        cost = float(models.get(k, {}).get("estimated_cost_usd", 0))
        p.append(f"<tr><td class='tag' style='width:170px'>{esc(k)}</td>"
                 f"<td>{_bar(b/(mod_rows[0][0] or 1)*100, '#7c3aed')}</td>"
                 f"<td class='num' style='width:70px'>{m(b)}</td>"
                 f"<td class='num sub' style='width:44px'>{pct:.0f}%</td>"
                 f"<td class='num sub' style='width:66px'>${cost:,.0f}</td></tr>")
    p.append("</table>")

    # output composition (reasoning) + cached context
    th = _thinking_estimate(week.get("week_range", ""))
    cr_w = int(tot_w.get("cache_read_tokens", 0) or 0)
    p.append("<h2>輸出組成（reasoning）＋ cached context</h2><table>")
    if th and th.get("output_total"):
        tk = th["thinking"]; ot = th["output_total"]; tx = max(0, ot - tk)
        p.append(f"<tr><td style='width:150px'>reasoning（thinking）</td>"
                 f"<td>{_bar(th['pct'], '#7c3aed')}</td>"
                 f"<td class='num' style='width:70px'>{m(tk)}</td><td class='num sub' style='width:44px'>{th['pct']:.0f}%</td></tr>")
        p.append(f"<tr><td>text / 工具輸出</td><td>{_bar(100-th['pct'], '#2563eb')}</td>"
                 f"<td class='num'>{m(tx)}</td><td class='num sub'>{100-th['pct']:.0f}%</td></tr>")
    p.append("</table>")
    p.append(f"<div class='sub'>reasoning 佔 output 約 {th.get('pct',0):.0f}%（去重後估算：output − text − tool；thinking 已 redact 故用相減）。"
             f"上表 % 是「佔 output」，output 只是總 billable 的一小片。</div>")
    p.append(f"<div class='card' style='margin-top:12px'><span class='sub'>cached context 本週被重讀（cache_read）</span><br>"
             f"<span class='n' style='font-size:22px;font-weight:700'>{m(cr_w)}</span> "
             f"<span class='sub'>tokens —— 每個 turn 都把整段 context 重讀一次；量最大但以約 0.1× input 計費（不進 billable）。長 session／不 compact 會放大這塊。</span></div>")

    # caveats
    p.append("<h2>說明（誠實 caveat）</h2><div class='sub'>")
    p.append("· billable = input + output + cache_create（cache_read 量大但不以全費計）；per-record 加總，口徑與官方一致。<br>")
    p.append(f"· 週 cap {m(WEEKLY_CAP)} 由**官方用量顯示校準**（{esc(CALIB.get('reading_date','?'))} 官方 Weekly {int(CALIB.get('official_pct',0.76)*100)}% 反推）；官方是額度 ground truth，飄移時用 `--calibrate <官方%>` 重新錨定。<br>")
    p.append("· reasoning(thinking) 已 redact 且 output 為合計，無法可靠單獨拆分，故不列。<br>")
    p.append("· 數據源：~/.claude/projects/*.jsonl 的 message.usage（含 subagent），由 token_usage_report.py 聚合。")
    p.append("</div>")

    p.append("</body></html>")
    html_body = "".join(p)

    text_body = (f"VolPred Token 報表 {now_tw.strftime('%Y-%m-%d %H:%M')} 台灣\n"
                 f"本週 {week_bill:,} / {WEEKLY_CAP:,} billable ({cap_pct:.0f}% cap)\n"
                 f"今日 {day_bill:,} billable, ${float(tot_t.get('estimated_cost_usd',0)):,.0f}\n"
                 f"前 3 使用類型: " + ", ".join(f"{k}={m(b)}" for b, k, _ in cat_rows[:3]))
    return html_body, text_body


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="render HTML to file, do not send")
    ap.add_argument("--to", default=None, help="override recipient")
    ap.add_argument("--force", action="store_true", help="bypass email dedup")
    ap.add_argument("--calibrate", type=float, default=None,
                    help="re-anchor weekly cap to the official display: pass the official weekly fraction (e.g. 0.76). Recomputes derived_weekly_cap from current billable and exits.")
    args = ap.parse_args(argv)

    now_tw = datetime.now(TPE)

    if args.calibrate is not None:
        pct = args.calibrate
        if not (0 < pct < 1):
            print(f"[token-report] --calibrate expects a fraction in (0,1), got {pct}", file=sys.stderr)
            return 1
        week = _report("--weekly")
        billable = _bill(week.get("totals", {}))
        cap = int(round(billable / pct))
        calib = {
            "_meta": CALIB.get("_meta", "Weekly-cap calibration anchored to the official Claude usage display."),
            "official_pct": pct,
            "billable_at_reading": billable,
            "reading_date": now_tw.strftime("%Y-%m-%d"),
            "reset_day": CALIB.get("reset_day", ""),
            "derived_weekly_cap": cap,
            "note": f"Re-anchored {now_tw.strftime('%Y-%m-%d %H:%M')} 台灣: official Weekly {pct*100:.0f}%, billable {billable:,} -> cap {cap:,}.",
        }
        CALIB_PATH.write_text(json.dumps(calib, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[token-report] calibrated: official {pct*100:.0f}% × billable {billable:,} -> weekly_cap {cap:,} ({cap/1e6:.0f}M), written {CALIB_PATH}")
        return 0

    today = _report()
    week = _report("--weekly")
    html_body, text_body = build_html(today, week, now_tw)

    if args.dry_run:
        out = ROOT / "storage" / "logs" / f"token_report_{now_tw.strftime('%Y%m%d_%H%M')}.html"
        out.write_text(html_body, encoding="utf-8")
        print(f"[token-report] dry-run: wrote {out} ({len(html_body)} bytes)")
        return 0

    sys.path.insert(0, str(ROOT / "src"))
    from volpred.publisher.email_notifier import EmailNotifier
    try:
        from volpred.ops.alerts import ALERT_RECIPIENT
    except Exception:
        ALERT_RECIPIENT = None
    recipients = [args.to] if args.to else ([ALERT_RECIPIENT] if ALERT_RECIPIENT else [])
    if not recipients:
        print("[token-report] no recipient", file=sys.stderr)
        return 1
    notifier = EmailNotifier()
    title = f"[VolPred Token 報表] {now_tw.strftime('%Y-%m-%d')} — 本週 {m(_bill(week.get('totals',{})))} / {m(WEEKLY_CAP)} cap"
    result = notifier.notify(
        subject=title,
        body=text_body,
        html_body=html_body,
        recipients=recipients,
        dedupe_type="token_report",
        dedupe_key=now_tw.strftime("%Y-%m-%d"),
        force_send=args.force,
    )
    print(f"[token-report] sent id={result.get('notification_id') if isinstance(result, dict) else result} subject={title}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
