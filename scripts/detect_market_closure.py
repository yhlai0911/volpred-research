#!/usr/bin/env python3
"""
Detect same-day EMERGENCY market closures (typhoon 颱風) that exchange_calendars
is blind to, and auto-populate config/market_closures_adhoc.json so the whole
platform (market-status banner + daily_update content gate + next-trading-day
logic) reflects reality.

Why this exists (2026-07-10 incident): 台股 closed for typhoon 巴威 on 7/10 but
exchange_calendars (XTAI) still reported it as a trading session, so the site
showed "台股正常開盤" and published "本日持倉建議" for a closed day. exchange_calendars
only knows PRE-SCHEDULED holidays; typhoon closures are announced the evening
before. This bridges that gap.

Authoritative source: NCDR 停班停課 CAP RSS feed (行政院人事行政總處 open data,
data.gov.tw dataset 20457). TWSE closes when 臺北市 declares a FULL-DAY 停止上班
(this is the actual rule the exchange follows).

Usage:
  uv run python scripts/detect_market_closure.py            # detect + apply + resync + alert
  uv run python scripts/detect_market_closure.py --dry-run  # detect only, no writes
  uv run python scripts/detect_market_closure.py --json     # machine-readable result

Called at the start of daily_update.py (fresh gate before 00:03 content) and by
an hourly LaunchAgent (com.volpred.market-closure-detect) so a same-day
announcement flips the live banner within the hour.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_PATH = REPO_ROOT / "config" / "market_closures_adhoc.json"
NCDR_FEED = "https://alerts.ncdr.nat.gov.tw/RssAtomFeed.ashx?AlertType=33"
sys.path.insert(0, str(REPO_ROOT / "src"))

from volpred.ops.scheduled_writer_commit import (  # noqa: E402
    commit_owned_outputs,
    dirty_paths_before_write,
    writable_output_paths,
)

# TWSE follows 臺北市 full-day work suspension for its own closure decision.
TWSE_TRIGGER_CITY = "臺北市"


def _warn(msg: str) -> None:
    print(f"[detect_market_closure] {msg}", file=sys.stderr)


def _taipei_today() -> date:
    # Host TZ is Asia/Taipei; local date is the Taipei calendar day.
    return datetime.now().astimezone().date()


def _fetch_feed(timeout: int = 25) -> str:
    req = Request(NCDR_FEED, headers={"User-Agent": "volpred-market-closure/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_full_day_closures(feed_text: str, city: str) -> set[date]:
    """
    Dates for which `city` has a FULL-DAY 停止上班 declaration.

    The CAP <summary> reads e.g. "[停班停課通知]臺北市:7/10停止上班、停止上課。".
    Excluded (not a full-day exchange closure):
      - "X:XX起停止上班"  → partial-day (afternoon) suspension
      - "已達停止上班...標準" → advisory/forecast, not a declaration

    Parsed with regex over the flat <summary> blocks rather than an XML parser —
    this avoids XXE / billion-laughs entirely (no entity expansion), and the feed
    schema is simple/stable enough that regex is the safer choice here.
    """
    year = _taipei_today().year
    out: set[date] = set()
    for raw in re.findall(r"<summary[^>]*>(.*?)</summary>", feed_text, flags=re.DOTALL):
        summary = html.unescape(raw)
        if city not in summary or "停止上班" not in summary:
            continue
        if "起" in summary or "已達" in summary:
            continue  # partial-day or advisory → TWSE not necessarily closed
        m = re.search(rf"{re.escape(city)}[:：](\d{{1,2}})/(\d{{1,2}})停止上班", summary)
        if not m:
            continue
        try:
            out.add(date(year, int(m.group(1)), int(m.group(2))))
        except ValueError as e:
            _warn(f"closure_date_parse_failed: {e} | summary_head={summary[:80]}")
            continue
    return out


def _load_override() -> dict:
    if not OVERRIDE_PATH.exists():
        return {"closures": []}
    data = json.loads(OVERRIDE_PATH.read_text())
    data.setdefault("closures", [])
    return data


def _save_override(data: dict) -> None:
    OVERRIDE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _is_scheduled_session(d: date) -> bool:
    import exchange_calendars as ecals
    import pandas as pd

    cal = ecals.get_calendar("XTAI")
    return bool(cal.is_session(pd.Timestamp(d)))


def detect_and_apply(apply: bool = True) -> dict:
    """
    Returns {detected: [iso...], added: [entry...], skipped: [...], error: str|None}.
    Only overrides days that ARE otherwise scheduled TWSE sessions and are not
    already recorded (idempotent).
    """
    result: dict = {"detected": [], "added": [], "skipped": [], "error": None,
                    "source": "ncdr_dgpa_stopwork_rss"}
    try:
        xml_text = _fetch_feed()
    except Exception as e:  # network / HTTP — fail-open, but never silent
        result["error"] = f"feed_fetch_failed: {e}"
        _warn(result["error"])
        return result
    try:
        closure_dates = _parse_full_day_closures(xml_text, TWSE_TRIGGER_CITY)
    except Exception as e:  # XML parse / regex — fail-open, but never silent
        result["error"] = f"feed_parse_failed: {e}"
        _warn(result["error"])
        return result

    result["detected"] = [d.isoformat() for d in sorted(closure_dates)]
    override = _load_override()
    existing_keys = {(c.get("market"), c.get("date")) for c in override["closures"]}

    for d in sorted(closure_dates):
        key = ("tw", d.isoformat())
        if key in existing_keys:
            result["skipped"].append({"date": d.isoformat(), "why": "already_in_override"})
            continue
        try:
            scheduled = _is_scheduled_session(d)
        except Exception as e:
            result["error"] = f"calendar_check_failed: {e}"
            _warn(result["error"])
            return result
        if not scheduled:
            result["skipped"].append({"date": d.isoformat(), "why": "not_a_scheduled_session"})
            continue
        entry = {
            "market": "tw",
            "date": d.isoformat(),
            "reason": "颱風休市",
            "reason_en": "Typhoon closure",
            "source": f"NCDR/DGPA 停班停課 RSS — {TWSE_TRIGGER_CITY}全日停止上班",
            "added_at": _taipei_today().isoformat(),
            "added_by": "detect_market_closure.py (auto)",
        }
        override["closures"].append(entry)
        existing_keys.add(key)
        result["added"].append(entry)

    if apply and result["added"]:
        _save_override(override)
    return result


def _resync_supabase() -> bool:
    try:
        from volpred.market_calendar import sync_market_status_to_supabase
        return bool(sync_market_status_to_supabase())
    except Exception as e:
        _warn(f"resync_failed: {e}")
        return False


def _send_alert(added: list[dict]) -> None:
    days = "、".join(a["date"] for a in added)
    body = (
        "## 觸發條件\n"
        f"NCDR/人事行政總處停班停課 RSS 偵測到 {TWSE_TRIGGER_CITY} 全日停止上班：{days}。"
        f"exchange_calendars 原判定為交易日 → 已自動加入 config/market_closures_adhoc.json 覆蓋層。\n\n"
        "## 影響\n"
        "台股當日休市已反映到：市場狀態橫幅（銀行/首頁）、每日持倉建議發佈閘門（不再發「本日進場指示」）、"
        "下一交易日計算。服務 Mission #4 平台正確性。\n\n"
        "## 系統已自動執行\n"
        f"1. 覆蓋層新增 {days}（tw / 颱風休市）\n"
        "2. 已重新同步 market_status 到 Supabase（橫幅 5 分鐘內翻為休市）\n"
        "3. daily_update 當日自動跳過本日持倉/策略建議\n"
        "無需人工介入；若判斷有誤請手動編輯 config/market_closures_adhoc.json。"
    )
    try:
        subprocess.run(
            ["uv", "run", "volpred", "ops", "send-alert", "--level", "warn",
             "--title", f"台股臨時休市自動偵測：{days}（颱風）", "--body", body],
            cwd=str(REPO_ROOT), timeout=90, check=False,
        )
    except Exception as e:
        _warn(f"alert_send_failed: {e}")  # non-fatal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="detect only, no writes/resync/alert")
    ap.add_argument("--json", action="store_true", help="print machine-readable result")
    args = ap.parse_args()

    dirty_before = (
        dirty_paths_before_write(
            REPO_ROOT,
            [OVERRIDE_PATH],
            label="detect_market_closure",
        )
        if not args.dry_run
        else frozenset()
    )
    if not args.dry_run and not writable_output_paths(
        REPO_ROOT,
        [OVERRIDE_PATH],
        dirty_before=dirty_before,
        label="detect_market_closure",
    ):
        return 1
    result = detect_and_apply(apply=not args.dry_run)

    if result["added"] and not args.dry_run:
        commit_owned_outputs(
            REPO_ROOT,
            [OVERRIDE_PATH],
            dirty_before=dirty_before,
            message=(
                "ops(market-calendar): record "
                f"{len(result['added'])} emergency market closure(s)"
            ),
            label="detect_market_closure",
        )
        result["resynced"] = _resync_supabase()
        _send_alert(result["added"])

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["error"]:
            _warn(f"completed with error: {result['error']}")
        _warn(f"detected={result['detected']} added={[a['date'] for a in result['added']]} "
             f"skipped={[s['date'] for s in result['skipped']]}")

    # Exit semantics: 0 normal (incl. nothing-to-do). 3 = source error (fail-open,
    # daily_update still runs; hourly cron alerts on repeated failures via log).
    return 3 if result["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
