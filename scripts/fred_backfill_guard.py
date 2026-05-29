#!/usr/bin/env python3
"""Self-healing FRED daily-rate backfill guard (2026-05-29).

Context: FRED public scraping endpoint got bot-blocked ~2026-04-16, freezing
daily-rate series (DGS10/DGS2/EFFR/BAMLH0A0HYM2/T10YIE/WALCL) for 6 weeks.
Fixed collect_us_data._collect_fred to use the official API + key, but at fix
time FRED's API itself was returning 504 (server-side outage). Rather than
defer the backfill to "next session" (boss directive: finish continuation
tasks, don't punt), this guard runs on a short host-cron interval and
self-heals the moment FRED recovers — no human/session dependency.

Behaviour (cheap + idempotent):
1. Check newest date among guarded daily-rate series.
2. If freshest <= STALE_DAYS old → already current → exit 0 quietly.
3. Else probe FRED API (1-row call). If not 200 → still down → exit 0
   (log only; try again next cron tick).
4. If API up → run full _collect_fred() backfill, then email boss ONCE that
   the gap closed (state file prevents repeat emails).

Run: uv run python scripts/fred_backfill_guard.py
Cron: */30 * * * * (until gap closes; self-noops when fresh)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parents[1]
MACRO_DIR = PROJECT / "storage" / "macro"
STATE_FILE = PROJECT / "storage" / "ops" / "fred_backfill_guard_state.json"
GUARDED = ["DGS10", "DGS2", "EFFR", "BAMLH0A0HYM2", "T10YIE", "WALCL"]
STALE_DAYS = 4  # daily rates publish T+1; >4 calendar days = genuinely stale


def _api_key() -> str | None:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    env_local = PROJECT / ".env.local"
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            line = line.strip()
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _latest_date(ticker: str) -> datetime | None:
    f = MACRO_DIR / f"fred_{ticker}.csv"
    if not f.exists():
        return None
    last = None
    for line in f.read_text().splitlines():
        d = line.split(",", 1)[0].strip()
        if len(d) == 10 and d[4] == "-":
            try:
                last = datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
    return last


def main() -> int:
    now = datetime.now()
    freshest = None
    for t in GUARDED:
        d = _latest_date(t)
        if d and (freshest is None or d > freshest):
            freshest = d

    if freshest is None:
        print("[fred_guard] no guarded series found — nothing to check")
        return 0

    age = (now - freshest).days
    print(f"[fred_guard] freshest guarded series = {freshest:%Y-%m-%d} ({age}d old)")
    if age <= STALE_DAYS:
        print(f"[fred_guard] within {STALE_DAYS}d → current, no backfill needed")
        return 0

    key = _api_key()
    if not key:
        print("[fred_guard] FRED_API_KEY missing — cannot backfill")
        return 0

    # Probe FRED API health (lightweight 1-row call)
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "DGS10", "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": 1},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[fred_guard] FRED API still down (HTTP {r.status_code}) — retry next tick")
            return 0
    except requests.exceptions.RequestException as e:
        print(f"[fred_guard] FRED API probe failed ({e}) — retry next tick")
        return 0

    # API is up + data is stale → backfill
    print("[fred_guard] FRED API recovered — running backfill")
    sys.path.insert(0, str(PROJECT / "scripts"))
    from collect_us_data import _collect_fred
    _collect_fred()

    new_freshest = None
    for t in GUARDED:
        d = _latest_date(t)
        if d and (new_freshest is None or d > new_freshest):
            new_freshest = d
    new_age = (now - new_freshest).days if new_freshest else 999
    print(f"[fred_guard] post-backfill freshest = {new_freshest:%Y-%m-%d} ({new_age}d)")

    # Email boss ONCE on successful gap-close (state prevents repeat)
    if new_age <= STALE_DAYS:
        prev = {}
        if STATE_FILE.exists():
            try:
                prev = json.loads(STATE_FILE.read_text())
            except Exception:
                prev = {}
        if not prev.get("gap_closed"):
            try:
                from volpred.ops import ALERT_RECIPIENT, send_alert
                send_alert(
                    "info",
                    f"FRED daily-rate backfill 完成 — gap 補到 {new_freshest:%Y-%m-%d}",
                    f"# FRED 自癒 backfill 成功\n\n"
                    f"FRED API 恢復後自動補齊日頻利率缺口（先前卡 4/16，bot-block + 504 outage）。\n\n"
                    f"- 最新日期：{new_freshest:%Y-%m-%d}\n"
                    f"- guarded series：{', '.join(GUARDED)}\n"
                    f"- 由 `scripts/fred_backfill_guard.py` (host cron */30) 自動完成，無需人工介入。\n",
                    recipient=ALERT_RECIPIENT,
                    storage_dir=str(PROJECT / "storage"),
                )
                print("[fred_guard] gap-close email sent to boss")
            except Exception as e:
                print(f"[fred_guard] email failed ({e}) — backfill still OK")
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "gap_closed": True,
            "closed_at": now.isoformat(),
            "freshest": f"{new_freshest:%Y-%m-%d}",
        }, indent=2))
    else:
        # Still stale after backfill attempt → reset state so next success emails
        if STATE_FILE.exists():
            STATE_FILE.write_text(json.dumps({"gap_closed": False}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
