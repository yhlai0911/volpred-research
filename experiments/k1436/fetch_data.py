"""K1436 stage 1: materialize Binance BTCUSDT perpetual funding rate + 5m klines.

Two canonical CSVs are written under experiments/k1436/data/:
  - btc_funding_rate_8h.csv  (fundingTime UTC, fundingRate)  from /fapi/v1/fundingRate
  - btcusdt_5m.csv           (open_time UTC, close)          from /fapi/v1/klines

Both are paginated forward from START_DATE. Provenance (endpoint, fetched_at,
period, row count) is written to data/fetch_provenance.json so the experiment
can cite exactly what it ran on.

Run:  uv run --active python experiments/k1436/fetch_data.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
DATA_DIR = Path(__file__).parent / "data"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "volpred-research/k1436"})


def _to_ms(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").timestamp() * 1000)


def _get(path: str, params: dict, max_retries: int = 5) -> list:
    """GET with backoff. Raises on terminal failure so we never silently truncate."""
    for attempt in range(max_retries):
        resp = SESSION.get(f"{BASE}{path}", params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        # 429/418 = rate limited, 5xx = transient
        if resp.status_code in (429, 418) or resp.status_code >= 500:
            sleep = 2 ** attempt
            print(f"  HTTP {resp.status_code} on {path}, retry in {sleep}s")
            time.sleep(sleep)
            continue
        raise RuntimeError(f"HTTP {resp.status_code} on {path} params={params}: {resp.text[:300]}")
    raise RuntimeError(f"exhausted {max_retries} retries on {path} params={params}")


def fetch_funding(start_ms: int) -> pd.DataFrame:
    """8h funding settlements, paginated forward on fundingTime."""
    rows, cursor, n_req = [], start_ms, 0
    while True:
        batch = _get("/fapi/v1/fundingRate",
                     {"symbol": SYMBOL, "startTime": cursor, "limit": 1000})
        n_req += 1
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1]["fundingTime"]
        if len(batch) < 1000:
            break
        cursor = last + 1
        time.sleep(0.15)
    print(f"  funding: {n_req} requests, {len(rows)} raw rows")

    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df[["fundingTime", "fundingRate"]].drop_duplicates("fundingTime").sort_values("fundingTime")
    return df.reset_index(drop=True)


def fetch_klines(start_ms: int) -> pd.DataFrame:
    """5-minute klines, paginated forward on open_time."""
    rows, cursor, n_req = [], start_ms, 0
    now_ms = int(time.time() * 1000)
    while cursor < now_ms:
        batch = _get("/fapi/v1/klines",
                     {"symbol": SYMBOL, "interval": "5m", "startTime": cursor, "limit": 1500})
        n_req += 1
        if not batch:
            break
        rows.extend([(r[0], r[4]) for r in batch])
        last_open = batch[-1][0]
        if last_open <= cursor and len(batch) < 2:
            break
        cursor = last_open + 1
        if n_req % 50 == 0:
            stamp = pd.to_datetime(last_open, unit="ms", utc=True).date()
            print(f"  klines: {n_req} requests, {len(rows)} bars, at {stamp}")
        time.sleep(0.12)
    print(f"  klines: {n_req} requests, {len(rows)} raw bars")

    df = pd.DataFrame(rows, columns=["open_time", "close"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close"] = df["close"].astype(float)
    df = df.drop_duplicates("open_time").sort_values("open_time")
    return df.reset_index(drop=True)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    start_ms = _to_ms(START_DATE)
    fetched_at = datetime.now(timezone.utc).isoformat()

    print("[1/2] funding rate ...")
    funding = fetch_funding(start_ms)
    funding_path = DATA_DIR / "btc_funding_rate_8h.csv"
    funding.to_csv(funding_path, index=False)

    print("[2/2] 5m klines ...")
    klines = fetch_klines(start_ms)
    klines_path = DATA_DIR / "btcusdt_5m.csv"
    klines.to_csv(klines_path, index=False)

    prov = {
        "fetched_at_utc": fetched_at,
        "exchange": "Binance USDS-M Futures (perpetual)",
        "symbol": SYMBOL,
        "requested_start": START_DATE,
        "funding_rate": {
            "endpoint": f"{BASE}/fapi/v1/fundingRate",
            "file": str(funding_path.relative_to(Path(__file__).parents[2])),
            "n_rows": int(len(funding)),
            "period": [str(funding["fundingTime"].min()), str(funding["fundingTime"].max())],
            "settlement_frequency": "8h (00:00 / 08:00 / 16:00 UTC)",
        },
        "klines_5m": {
            "endpoint": f"{BASE}/fapi/v1/klines",
            "file": str(klines_path.relative_to(Path(__file__).parents[2])),
            "interval": "5m",
            "n_rows": int(len(klines)),
            "period": [str(klines["open_time"].min()), str(klines["open_time"].max())],
        },
    }
    (DATA_DIR / "fetch_provenance.json").write_text(json.dumps(prov, indent=2))
    print(json.dumps(prov, indent=2))


if __name__ == "__main__":
    main()
