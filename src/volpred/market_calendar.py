"""
Market calendar module — provides trading day status for NYSE and TWSE.

Uses exchange_calendars as the authoritative source. Produces structured
market status data consumed by daily_update.py → Supabase → frontend.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as ecals
import pandas as pd

# ── Calendar instances (lazy singletons) ────────────────────────────
_calendars: dict[str, ecals.ExchangeCalendar] = {}

MARKETS = {
    "us": {"exchange_code": "XNYS", "label": "美股 (NYSE)", "tz": "America/New_York"},
    "tw": {"exchange_code": "XTAI", "label": "台股 (TWSE)", "tz": "Asia/Taipei"},
}

# ── Holiday name translations ───────────────────────────────────────
_NYSE_HOLIDAY_ZH: dict[str, str] = {
    "Good Friday": "耶穌受難日",
    "New Year's Day": "元旦",
    "Martin Luther King Jr. Day": "馬丁路德金恩日",
    "Washington's Birthday": "華盛頓誕辰 / 總統日",
    "Presidents' Day": "華盛頓誕辰 / 總統日",
    "Memorial Day": "陣亡將士紀念日",
    "Juneteenth National Independence Day": "六月節",
    "Independence Day": "獨立紀念日",
    "Labor Day": "勞動節",
    "Thanksgiving Day": "感恩節",
    "Christmas Day": "聖誕節",
}

_TWSE_HOLIDAY_ZH: dict[str, str] = {
    "New Year's Day": "元旦",
    "Peace Memorial Day": "和平紀念日",
    "Peace Memorial Day extra Monday": "和平紀念日（補假）",
    "Women and Children's Day": "婦幼節 / 清明節",
    "National Day": "國慶日",
    "National Day extra Monday": "國慶日（補假）",
}

# TWSE adhoc holidays (no name in exchange_calendars) — common patterns
# These are approximate date→name mappings for well-known recurring holidays.
# We match by month-day proximity since exact dates shift yearly.
_TWSE_ADHOC_PATTERNS: list[tuple[tuple[int, int], tuple[int, int], str]] = [
    # (month_start, day_start), (month_end, day_end), name
    ((1, 20), (2, 15), "農曆新年"),
    ((2, 27), (3, 1), "和平紀念日（連假）"),
    ((4, 2), (4, 7), "清明節（連假）"),
    ((5, 28), (6, 3), "端午節"),
    ((6, 1), (6, 15), "端午節"),
    ((9, 15), (10, 5), "中秋節"),
    ((10, 9), (10, 12), "國慶日（連假）"),
]


def _get_calendar(market_key: str) -> ecals.ExchangeCalendar:
    if market_key not in _calendars:
        code = MARKETS[market_key]["exchange_code"]
        _calendars[market_key] = ecals.get_calendar(code)
    return _calendars[market_key]


def _guess_twse_adhoc_name(d: date) -> str:
    """Best-effort name for TWSE adhoc holidays based on date patterns."""
    m, day = d.month, d.day
    for (m1, d1), (m2, d2), name in _TWSE_ADHOC_PATTERNS:
        if (m1, d1) <= (m, day) <= (m2, d2):
            return name
    return "彈性放假"


def _translate_holiday(market_key: str, eng_name: str, d: date) -> str:
    """Translate an English holiday name to Chinese."""
    table = _NYSE_HOLIDAY_ZH if market_key == "us" else _TWSE_HOLIDAY_ZH
    if eng_name in table:
        return table[eng_name]
    # Partial match
    for k, v in table.items():
        if k.lower() in eng_name.lower():
            return v
    # TWSE adhoc fallback
    if market_key == "tw":
        return _guess_twse_adhoc_name(d)
    return eng_name


# ── Core API ────────────────────────────────────────────────────────

def get_market_status(d: date, market_key: str) -> dict[str, Any]:
    """
    Return market status for a single market on a given date.

    Returns:
        {
            "market": "us",
            "label": "美股 (NYSE)",
            "date": "2026-04-03",
            "is_open": false,
            "reason": "耶穌受難日",
            "reason_en": "Good Friday",
            "prev_trading_day": "2026-04-02",
            "next_trading_day": "2026-04-06",
        }
    """
    cal = _get_calendar(market_key)
    ts = pd.Timestamp(d)
    is_open = bool(cal.is_session(ts))

    reason = ""
    reason_en = ""

    if not is_open:
        weekday = ts.weekday()
        if weekday >= 5:
            reason = "週末"
            reason_en = "Weekend"
        else:
            # It's a weekday but market is closed → holiday
            # Check regular holidays first
            hols = cal.regular_holidays.holidays(
                start=ts, end=ts, return_name=True
            )
            if len(hols) > 0:
                reason_en = hols.iloc[0]
                reason = _translate_holiday(market_key, reason_en, d)
            else:
                # Adhoc holiday
                reason_en = "Exchange Holiday"
                if market_key == "tw":
                    reason = _guess_twse_adhoc_name(d)
                else:
                    reason = "交易所休市"

    # Previous / next trading day
    search_start = ts - pd.Timedelta(days=10)
    search_end = ts + pd.Timedelta(days=10)

    prev_sessions = cal.sessions_in_range(search_start, ts - pd.Timedelta(days=1))
    next_sessions = cal.sessions_in_range(ts + pd.Timedelta(days=1), search_end)

    prev_day = prev_sessions[-1].date().isoformat() if len(prev_sessions) > 0 else None
    next_day = next_sessions[0].date().isoformat() if len(next_sessions) > 0 else None

    return {
        "market": market_key,
        "label": MARKETS[market_key]["label"],
        "date": d.isoformat(),
        "is_open": is_open,
        "reason": reason,
        "reason_en": reason_en,
        "prev_trading_day": prev_day,
        "next_trading_day": next_day,
    }


def get_all_market_status(d: date | None = None) -> dict[str, Any]:
    """
    Return market status for all tracked markets on a given date.
    Defaults to today (UTC).

    Returns:
        {
            "date": "2026-04-03",
            "generated_at": "2026-04-03T22:03:00+00:00",
            "markets": {
                "us": { ... },
                "tw": { ... },
            },
            "summary": "美股休市（耶穌受難日）、台股休市（婦幼節 / 清明節）",
            "any_closed": true,
            "all_closed": true,
        }
    """
    if d is None:
        d = datetime.now(timezone.utc).date()

    markets = {}
    for key in MARKETS:
        markets[key] = get_market_status(d, key)

    closed_markets = [m for m in markets.values() if not m["is_open"]]
    any_closed = len(closed_markets) > 0
    all_closed = len(closed_markets) == len(MARKETS)

    # Build summary string
    parts = []
    for m in markets.values():
        if not m["is_open"]:
            r = m["reason"] or "休市"
            parts.append(f"{m['label'].split(' ')[0]}休市（{r}）")
        else:
            parts.append(f"{m['label'].split(' ')[0]}正常開盤")
    summary = "、".join(parts)

    return {
        "date": d.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "summary": summary,
        "any_closed": any_closed,
        "all_closed": all_closed,
    }


def get_upcoming_holidays(
    market_key: str, from_date: date | None = None, days_ahead: int = 30
) -> list[dict[str, str]]:
    """
    List upcoming non-weekend market holidays within the next N days.
    Useful for advance notice ("下週五休市").
    """
    if from_date is None:
        from_date = datetime.now(timezone.utc).date()

    cal = _get_calendar(market_key)
    start = pd.Timestamp(from_date)
    end = start + pd.Timedelta(days=days_ahead)

    results = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and not cal.is_session(cursor):
            status = get_market_status(cursor.date(), market_key)
            results.append({
                "date": cursor.date().isoformat(),
                "reason": status["reason"],
                "reason_en": status["reason_en"],
            })
        cursor += pd.Timedelta(days=1)

    return results


def save_market_status(storage_dir: str | Path = "storage") -> Path:
    """
    Generate market_status.json in storage directory.
    Called by daily_update.py as part of the regular flow.
    """
    storage = Path(storage_dir)
    status = get_all_market_status()

    # Add upcoming holidays (next 14 days)
    status["upcoming_holidays"] = {
        "us": get_upcoming_holidays("us", days_ahead=14),
        "tw": get_upcoming_holidays("tw", days_ahead=14),
    }

    out_path = storage / "market_status.json"
    out_path.write_text(json.dumps(status, ensure_ascii=False, indent=2))
    return out_path


# ── CLI test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    result = get_all_market_status(d)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    for mk in MARKETS:
        upcoming = get_upcoming_holidays(mk, d, days_ahead=14)
        if upcoming:
            print(f"{MARKETS[mk]['label']} 未來 14 天假日:")
            for h in upcoming:
                print(f"  {h['date']} — {h['reason']}")
