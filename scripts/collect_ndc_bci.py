#!/usr/bin/env python3
"""
Collect Taiwan Business Cycle Indicators (BCI) from NDC website.
景氣領先指標 + 景氣對策信號 抓取腳本

NDC 發布時間：每月 27 日 16:00（台灣時間），資料落後 2 個月
例如：4/27 發布 2 月數據

Data source: https://index.ndc.gov.tw/n/zh_tw/data/eco/indicators_table1
Method: Selenium-free — uses requests + BeautifulSoup to parse the Angular-rendered table page.
        Falls back to hardcoded recent data if scraping fails.

Usage:
    uv run python scripts/collect_ndc_bci.py
    uv run python scripts/collect_ndc_bci.py --check  # only show what's missing
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

BCI_PATH = PROJECT_ROOT / 'storage' / 'macro' / 'tw_dgbas_bci_m.csv'


def get_latest_period(df, item_pattern):
    """Get latest period for a given item pattern."""
    import pandas as pd
    mask = df['item'].str.contains(item_pattern, na=False, regex=True)
    subset = df[mask]
    if len(subset) == 0:
        return None
    return subset['period'].max()


def fetch_ndc_table():
    """
    Fetch BCI data from NDC indicators_table1 page.
    This page is an Angular SPA, so plain `requests` GET returns the SPA HTML
    shell, not data.

    2026-06-24 finding (via Chrome MCP investigation, do not lose this):
    - A JSON data endpoint DOES exist: `/n/json/data/eco/indicators` on
      index.ndc.gov.tw. The earlier "NDC has no clean API" comment was wrong.
    - BUT a plain GET (even with the page's own query string) still returns the
      SPA HTML — the Angular app reaches it via POST with params built inside
      `/n/include/js/app/indicators.min.js`. Wiring the pure-Python collector to
      it requires reverse-engineering that POST body (TODO, low priority — no
      active knowledge/strategy currently depends on this series).
    - What DOES work cheaply: the rendered table at indicators_table1 is readable
      via Chrome MCP (get_page_text / DOM read). 景氣對策信號(分) sits in the
      default table; 領先指標 series need the leading-indicator view.
    - Manual refresh procedure: open the page in Chrome MCP, read the table,
      upsert into BCI_PATH (item/unit/freq/period/value schema).
    - Last manual refresh: 2026-06-24 — 景氣對策信號 brought current to 2026M04
      (2026M02 revised 40->41, M03=39, M04=39). 領先指標 series NOT refreshed
      that pass (still ~M01).
    """
    print("  NDC indicators page is an Angular SPA (data via POST /n/json/data/eco/indicators).")
    print("  Plain-Python auto-fetch not wired yet (POST params live in indicators.min.js).")
    print("  Refresh path: read the rendered table via Chrome MCP, then upsert BCI_PATH.")
    print("  Run: claude 'update NDC BCI data from website'")
    return None


def check_freshness():
    """Check how stale the BCI data is."""
    import pandas as pd

    if not BCI_PATH.exists():
        print("ERROR: BCI file not found!")
        return False

    df = pd.read_csv(BCI_PATH)

    # Check leading indicator
    lead_latest = get_latest_period(df, r'景氣領先指標不含趨勢指數\(點\)$')
    signal_latest = get_latest_period(df, r'^景氣對策信號\(分\)$')

    now = datetime.now()
    current_period = f"{now.year}M{now.month:02d}"

    # NDC publishes with 2-month lag on 27th
    # e.g., April 27 publishes February data
    expected_latest_month = now.month - 2
    expected_latest_year = now.year
    if expected_latest_month <= 0:
        expected_latest_month += 12
        expected_latest_year -= 1
    expected = f"{expected_latest_year}M{expected_latest_month:02d}"

    print(f"  Leading indicator latest: {lead_latest}")
    print(f"  Signal score latest: {signal_latest}")
    print(f"  Expected (with 2-month lag): {expected}")
    print(f"  Current: {current_period}")

    is_fresh = (lead_latest or '') >= expected
    if not is_fresh:
        months_behind = _period_diff(expected, lead_latest or '2020M01')
        print(f"  ⚠️ Data is ~{months_behind} months behind expected!")
    else:
        print(f"  ✅ Data is up to date")

    return is_fresh


def _period_diff(p1, p2):
    """Calculate month difference between two period strings like 2026M01."""
    y1, m1 = int(p1[:4]), int(p1[5:])
    y2, m2 = int(p2[:4]), int(p2[5:])
    return (y1 - y2) * 12 + (m1 - m2)


def main():
    parser = argparse.ArgumentParser(description='Collect NDC BCI data')
    parser.add_argument('--check', action='store_true', help='Only check freshness')
    args = parser.parse_args()

    print("=== NDC Business Cycle Indicators ===")
    print(f"  File: {BCI_PATH}")

    import pandas as pd

    if args.check:
        check_freshness()
        return

    # Check freshness first
    is_fresh = check_freshness()
    if is_fresh:
        print("\n  Data is current, no update needed.")
        return

    print("\n  Attempting to fetch from NDC...")
    data = fetch_ndc_table()

    if data is None:
        print("\n  Auto-fetch not available. Please update manually:")
        print("  1. Open https://index.ndc.gov.tw/n/zh_tw/data/eco/indicators_table1")
        print("  2. Click '領先指標不含趨勢指數' to add column")
        print("  3. Read the table values")
        print("  4. Or use Claude with Chrome DevTools MCP to scrape")


if __name__ == '__main__':
    main()
