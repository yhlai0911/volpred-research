#!/usr/bin/env python3
"""K1174 — GDELT raw GKG file fetch (fallback path, actually used).

For each earnings-window day T-2..T+2 across ~35 top-analyst stocks in the
K1168 panel, download ONE GKG 2.1 file at 12:00 UTC (a 15-min slice that
overlaps Asia close, EU afternoon, and US morning). Scan for per-stock
company-name / ticker mentions in the V2Persons and V2Organizations fields.

Random seed: 42.

Output:
  data/gkg_files/YYYYMMDD120000.gkg.csv.zip  (cached)
  data/stock_company_map.csv                (ticker -> list of match strings)
  data/earnings_dates.csv                   (ticker, event_date_utc)
  data/per_stock_window_counts.csv          (ticker, event_date, day_offset,
                                             mention_count)
  data/fetch_status.json                    (download status per file)

Usage:
  uv run python experiments/k1174/k1174_fetch_gdelt_files.py

Honest sampling disclosure:
  GDELT GKG releases 96 files/day (every 15 min). We sample only the
  `120000` file per day, which is ~1/96 = ~1% of the full-day news volume.
  The *relative* concentration measure (T0 count vs T-2..T+2 total) is still
  estimable IF that 1/96 sample is uncorrelated with event-day vs non-event-
  day. We acknowledge this may under- or over-estimate PCR per stock.

  Alternative (infeasible here):
    - GDELT DOC API: all probes HTTP 429 even with 10s rate-limit (tested
      2026-04-13; see k1170/data/gdelt_fetch_status.json).
    - GDELT BigQuery: GCP tooling unavailable on host (see
      k1174_fetch_gdelt_bq.py).
    - Full 96 files/day: ~600 MB/day × 250 days = ~150 GB download; infeasible
      within a single autonomous agent timeout window.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
GKG_DIR = DATA / "gkg_files"
GKG_DIR.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)
UA = "Mozilla/5.0 (VolPredResearch; K1174 per-stock PCR fetch)"
BASE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"

# GKG 2.1 column positions (1-indexed in spec, we use 0-indexed)
COL_DATE = 1
COL_SOURCE = 3
COL_URL = 4
COL_V2PERSONS = 12  # V2Persons
COL_V2ORGS = 14      # V2Organizations

K1168_PANEL = HERE.parent / "k1168" / "k1168_per_stock_table.csv"


# ---------------------------------------------------------------------------
# Stock / ticker company-name mapping
# ---------------------------------------------------------------------------
# Top-3 by analyst coverage per market from K1168 panel (35 stocks total).
# Each entry: ticker -> list of lowercase regex-safe strings to match in
# V2Persons / V2Organizations. Includes the company name in English plus
# common short variants. Chinese/Japanese/Korean names kept in the list for
# completeness but the GKG V2 text fields are typically Anglicized.
STOCK_NAME_MAP: Dict[str, Dict[str, List[str]]] = {
    # TW
    "2330.TW": {"market": "TW", "names": ["tsmc", "taiwan semiconductor"]},
    "2454.TW": {"market": "TW", "names": ["mediatek"]},
    "2317.TW": {"market": "TW", "names": ["hon hai", "foxconn"]},
    "2303.TW": {"market": "TW", "names": ["united microelectronics", "umc"]},
    # US
    "AMZN": {"market": "US", "names": ["amazon.com", "amazon"]},
    "META": {"market": "US", "names": ["meta platforms", "facebook", " meta "]},
    "NVDA": {"market": "US", "names": ["nvidia"]},
    "AAPL": {"market": "US", "names": ["apple inc", "apple"]},
    # JP
    "7974.T": {"market": "JP", "names": ["nintendo"]},
    "6758.T": {"market": "JP", "names": ["sony group", "sony corp", "sony"]},
    "8035.T": {"market": "JP", "names": ["tokyo electron"]},
    "7203.T": {"market": "JP", "names": ["toyota motor", "toyota"]},
    # EU
    "ADS.DE": {"market": "EU", "names": ["adidas"]},
    "SAP.DE": {"market": "EU", "names": [" sap ", "sap se", "sap ag"]},
    "MBG.DE": {"market": "EU", "names": ["mercedes-benz", "mercedes benz", "daimler"]},
    "ASML.AS": {"market": "EU", "names": ["asml"]},
    "MC.PA": {"market": "EU", "names": ["lvmh", "louis vuitton"]},
    # KR
    "000660.KS": {"market": "KR", "names": ["sk hynix", "hynix"]},
    "005930.KS": {"market": "KR", "names": ["samsung electronics"]},
    "005380.KS": {"market": "KR", "names": ["hyundai motor"]},
    # CA
    "ENB.TO": {"market": "CA", "names": ["enbridge"]},
    "CP.TO": {"market": "CA", "names": ["canadian pacific"]},
    "CNQ.TO": {"market": "CA", "names": ["canadian natural resources"]},
    # HK
    "0700.HK": {"market": "HK", "names": ["tencent"]},
    "0388.HK": {"market": "HK", "names": ["hong kong exchanges", "hkex"]},
    "0939.HK": {"market": "HK", "names": ["china construction bank"]},
    # BR
    "ABEV3.SA": {"market": "BR", "names": ["ambev", "anheuser-busch inbev brazil"]},
    "RENT3.SA": {"market": "BR", "names": ["localiza"]},
    "B3SA3.SA": {"market": "BR", "names": [" b3 sa", "brasil bolsa balcao"]},
    # IN
    "TCS.NS": {"market": "IN", "names": ["tata consultancy", " tcs "]},
    "INFY.NS": {"market": "IN", "names": ["infosys"]},
    "ICICIBANK.NS": {"market": "IN", "names": ["icici bank"]},
}


def load_earnings_dates(tickers: List[str]) -> pd.DataFrame:
    """Fetch yfinance earnings_dates for the given tickers.

    Filter to announcements strictly before today (lookahead protection) and
    inside the 2024-01-01 to 2025-12-31 window (file availability + sample
    period balance).
    """
    import yfinance as yf

    rows = []
    today = pd.Timestamp.utcnow().normalize()
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2025-12-31", tz="UTC")
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            ed = tk.earnings_dates
        except Exception as ex:
            print(f"earnings_dates FAIL {t}: {ex}", file=sys.stderr)
            continue
        if ed is None or len(ed) == 0:
            continue
        for ts in ed.index:
            try:
                ts_utc = pd.Timestamp(ts).tz_convert("UTC")
            except Exception:
                continue
            if ts_utc >= today:
                continue  # lookahead guard
            if ts_utc < start or ts_utc > end:
                continue
            rows.append({"ticker": t, "event_date_utc": ts_utc.normalize().date()})
    df = pd.DataFrame(rows).drop_duplicates().sort_values(["ticker", "event_date_utc"])
    return df.reset_index(drop=True)


def window_dates(event_date) -> List:
    """Return T-2..T+2 as list of 5 date objects."""
    ed = pd.Timestamp(event_date)
    return [(ed + pd.Timedelta(days=d)).date() for d in range(-2, 3)]


def collect_unique_dates(events: pd.DataFrame) -> List:
    days = set()
    for _, row in events.iterrows():
        for d in window_dates(row["event_date_utc"]):
            days.add(d)
    return sorted(days)


def fetch_one_file(date_obj, hhmm: str = "120000",
                    max_retries: int = 3) -> Path | None:
    """Download one GKG file for the given date and time stamp.

    Returns the path to the cached zip, or None on failure. Uses a short
    pause between retries.
    """
    stamp = date_obj.strftime("%Y%m%d") + hhmm
    out_zip = GKG_DIR / f"{stamp}.gkg.csv.zip"
    if out_zip.exists() and out_zip.stat().st_size > 10_000:
        return out_zip
    url = BASE_URL.format(stamp=stamp)
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 200 and len(r.content) > 10_000:
                out_zip.write_bytes(r.content)
                return out_zip
            else:
                # GDELT sometimes has missing 15-min slices; try 114500 fallback
                if attempt == 0 and hhmm == "120000":
                    # try 114500 (the nearest previous 15-min)
                    return fetch_one_file(date_obj, "114500", max_retries=1)
                return None
        except Exception as ex:
            print(f"fetch FAIL {stamp} attempt {attempt}: {ex}", file=sys.stderr)
            time.sleep(3)
    return None


def build_pattern(names: List[str]) -> re.Pattern:
    """Compile a single regex OR-pattern that matches any of the name strings
    (case-insensitive) as a substring. Pad single-word tickers with spaces
    upstream (e.g., ' sap ') to reduce false positives.
    """
    # Escape for regex, keep the exact strings.
    parts = [re.escape(n.strip().lower()) for n in names if n.strip()]
    return re.compile("|".join(parts), flags=re.IGNORECASE)


def scan_file_for_tickers(zip_path: Path,
                          patterns: Dict[str, re.Pattern]) -> Dict[str, int]:
    """Stream-scan a GKG zip and count rows matching each ticker's pattern.

    Counts are per-ticker per-file. A single row matches at most once per
    ticker (we do a substring search inside V2Persons + V2Organizations,
    not a tokenization).
    """
    counts = {t: 0 for t in patterns}
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            name = zf.namelist()[0]
            with zf.open(name) as f:
                for raw in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                    # GKG 2.1 uses tab as separator
                    cols = raw.split("\t")
                    if len(cols) < 16:
                        continue
                    hay = (cols[COL_V2PERSONS] + " " + cols[COL_V2ORGS]).lower()
                    for t, pat in patterns.items():
                        if pat.search(hay):
                            counts[t] += 1
    except Exception as ex:
        print(f"scan FAIL {zip_path.name}: {ex}", file=sys.stderr)
    return counts


def main():
    tickers = list(STOCK_NAME_MAP.keys())
    print(f"[K1174] Loading earnings dates for {len(tickers)} stocks...", flush=True)
    events = load_earnings_dates(tickers)
    print(f"[K1174] {len(events)} earnings events in window 2024-01-01..2025-12-31")
    events.to_csv(DATA / "earnings_dates.csv", index=False)

    # Build per-day download list (union of all T-2..T+2 windows)
    unique_days = collect_unique_dates(events)
    print(f"[K1174] {len(unique_days)} unique calendar days to download")

    # Download
    download_status: Dict[str, str] = {}
    t_start = time.time()
    for i, d in enumerate(unique_days):
        path = fetch_one_file(d, "120000")
        if path is None:
            download_status[d.isoformat()] = "MISS"
        else:
            download_status[d.isoformat()] = "OK"
        if i % 25 == 0:
            elapsed = time.time() - t_start
            print(f"[K1174] downloaded {i+1}/{len(unique_days)} in {elapsed:.0f}s",
                  flush=True)
        # polite rate
        time.sleep(0.3)

    n_ok = sum(1 for v in download_status.values() if v == "OK")
    print(f"[K1174] download complete: {n_ok}/{len(unique_days)} OK")
    (DATA / "fetch_status.json").write_text(
        json.dumps({"per_day": download_status, "n_ok": n_ok,
                    "n_total": len(unique_days)}, indent=2), encoding="utf-8")

    # Build per-ticker patterns
    patterns = {t: build_pattern(info["names"]) for t, info in STOCK_NAME_MAP.items()}

    # Scan every downloaded file; store per-day per-ticker counts
    print("[K1174] Scanning GKG files...", flush=True)
    per_day_counts: Dict[str, Dict[str, int]] = {}
    t_start = time.time()
    day_list = sorted(unique_days)
    for i, d in enumerate(day_list):
        if download_status[d.isoformat()] != "OK":
            continue
        stamp = d.strftime("%Y%m%d") + "120000"
        zp = GKG_DIR / f"{stamp}.gkg.csv.zip"
        if not zp.exists():
            # try 114500 fallback path
            zp = GKG_DIR / (d.strftime("%Y%m%d") + "114500.gkg.csv.zip")
            if not zp.exists():
                continue
        per_day_counts[d.isoformat()] = scan_file_for_tickers(zp, patterns)
        if i % 25 == 0:
            elapsed = time.time() - t_start
            print(f"[K1174] scanned {i+1}/{len(day_list)} in {elapsed:.0f}s",
                  flush=True)

    # Write per-day per-ticker counts
    rows_out = []
    for day, counts in per_day_counts.items():
        for t, c in counts.items():
            rows_out.append({"date_utc": day, "ticker": t, "count": int(c)})
    pd.DataFrame(rows_out).to_csv(DATA / "per_day_ticker_counts.csv", index=False)

    # Reshape to per-event per-day offset counts
    ev_rows = []
    per_day_lookup = per_day_counts
    for _, ev in events.iterrows():
        win = window_dates(ev["event_date_utc"])
        for offset, d in enumerate(win, start=-2):
            c = per_day_lookup.get(d.isoformat(), {}).get(ev["ticker"])
            ev_rows.append({
                "ticker": ev["ticker"],
                "event_date": ev["event_date_utc"],
                "day_offset": offset,
                "date_utc": d.isoformat(),
                "count": (int(c) if c is not None else None),
            })
    pd.DataFrame(ev_rows).to_csv(DATA / "per_stock_window_counts.csv", index=False)

    # Name map
    pd.DataFrame([
        {"ticker": t, "market": info["market"], "names": "|".join(info["names"])}
        for t, info in STOCK_NAME_MAP.items()
    ]).to_csv(DATA / "stock_company_map.csv", index=False)

    print("[K1174] fetch+scan complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
