#!/usr/bin/env python3
"""
K1170 — GDELT 2.0 DOC API fetch attempt for per-stock press_concentration_ratio.

Design:
  press_concentration_ratio_i = count(articles mentioning stock name
                                      on announcement day T0)
                                / sum(count T-2..T+2 window)

Interpretation:
  1.0  -> all coverage on T0 (perfectly concentrated)
  0.2  -> uniform across 5 days (perfectly dispersed)

GDELT 2.0 DOC API: https://api.gdeltproject.org/api/v2/doc/doc
  mode=timelinevol returns daily article-volume timeseries
  mode=ArtList returns article list

STATUS (as executed 2026-04-13): GDELT API returns HTTP 429 Too Many Requests
from this host; no articles retrievable. K1170 therefore falls back to a
hardcoded market-level proxy constructed from English-language financial
press density × primary-language press concentration (see k1170.py).

This script is retained for reproducibility — if GDELT rate-limits lift, rerun
and merge per-stock ratios into k1170.py in place of the hardcoded market means.

Run:
    python3 k1170_fetch_gdelt.py > data/gdelt_fetch.log 2>&1

Outputs:
    data/gdelt_raw/<ticker>.json  per-ticker article time series
    data/gdelt_fetch_status.json  global status (which tickers succeeded)

Random seed: 42 (for any sampling / retry ordering).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib import request, parse, error

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "gdelt_raw"
RAW.mkdir(parents=True, exist_ok=True)

# Small, safe stock sample per market (top 3 by analyst coverage from K1168 panel)
# Full panel fetch is infeasible under GDELT rate limits even when working.
PROBE_TICKERS = {
    "TW": ["TSMC", "Foxconn", "MediaTek"],
    "US": ["Apple", "Microsoft", "Amazon"],
    "JP": ["Toyota", "Sony", "SoftBank"],
    "EU": ["ASML", "LVMH", "Nestle"],
    "KR": ["Samsung", "SK Hynix", "Hyundai"],
    "CA": ["Shopify", "RBC", "TD Bank"],
    "HK": ["HSBC", "Tencent", "AIA"],
}

# 2024 calendar year earnings windows (Q1..Q4). These are sample windows only;
# actual per-stock announcement dates would require K1168-style yfinance fetch.
SAMPLE_WINDOWS = [
    ("20240125000000", "20240131000000"),  # Q4 2023 reporting season
    ("20240425000000", "20240501000000"),  # Q1 2024
    ("20240725000000", "20240731000000"),  # Q2 2024
    ("20241025000000", "20241031000000"),  # Q3 2024
]

UA = "Mozilla/5.0 (VolPredResearch GDELTProbe; k1170 mechanism test)"


def fetch_timelinevol(query: str, start: str, end: str) -> dict:
    params = {
        "query": query,
        "mode": "timelinevol",
        "startdatetime": start,
        "enddatetime": end,
        "format": "json",
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + parse.urlencode(params)
    req = request.Request(url, headers={"User-Agent": UA})
    with request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def main() -> int:
    status = {
        "attempted_at_utc": pd.Timestamp.utcnow().isoformat(),
        "per_ticker": {},
        "fatal": None,
    }
    total_attempts = 0
    total_success = 0
    for market, tickers in PROBE_TICKERS.items():
        for t in tickers:
            for (s, e) in SAMPLE_WINDOWS:
                total_attempts += 1
                try:
                    # polite rate: GDELT guidance suggests <= 5 req/min
                    time.sleep(1.8)
                    data = fetch_timelinevol(t + " earnings", s, e)
                    out = RAW / f"{market}_{t.replace(' ', '_')}_{s[:8]}.json"
                    out.write_text(json.dumps(data), encoding="utf-8")
                    status["per_ticker"].setdefault(f"{market}/{t}", []).append(
                        {"window": s[:8], "ok": True, "file": str(out.relative_to(HERE))}
                    )
                    total_success += 1
                except error.HTTPError as he:
                    status["per_ticker"].setdefault(f"{market}/{t}", []).append(
                        {"window": s[:8], "ok": False, "http": he.code}
                    )
                    if he.code == 429:
                        # rate-limit, wait longer
                        time.sleep(1.8)
                except Exception as ex:
                    status["per_ticker"].setdefault(f"{market}/{t}", []).append(
                        {"window": s[:8], "ok": False, "err": repr(ex)}
                    )
    status["n_attempts"] = total_attempts
    status["n_success"] = total_success
    if total_success == 0:
        status["fatal"] = "All GDELT DOC API calls returned error (likely HTTP 429 rate-limit)."
    (DATA / "gdelt_fetch_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )
    print(f"GDELT fetch complete: {total_success}/{total_attempts} windows succeeded.")
    if total_success == 0:
        print("FALLBACK: hardcoded market-level press_concentration used in k1170.py.")
    return 0 if total_success > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
