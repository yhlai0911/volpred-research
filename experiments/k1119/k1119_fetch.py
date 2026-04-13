"""K1119 data fetcher: BTC-USD OHLCV + Deribit DVOL + yfinance ^VIX.

Outputs:
    experiments/k1119/data/btc_ohlcv.csv   (daily UTC close)
    experiments/k1119/data/dvol_daily.csv  (Deribit BTC DVOL, daily UTC)
    experiments/k1119/data/vix_daily.csv   (yfinance ^VIX, daily)

Deribit DVOL endpoint (public, no auth):
    GET https://www.deribit.com/api/v2/public/get_volatility_index_data
    Params: currency=BTC, start_timestamp, end_timestamp, resolution=1D
    Returns [ts_ms, open, high, low, close] for the volatility index in percent.
    (Note: `get_historical_volatility` is a separate short-window realized vol
     endpoint; we do NOT use it here — that is *not* DVOL.)

References:
    Deribit API docs — https://docs.deribit.com/#public-get_volatility_index_data
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True, parents=True)

START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
END = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)


def log(msg: str) -> None:
    ts = dt.datetime.now(dt.UTC).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_dvol_daily() -> pd.DataFrame:
    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    all_rows: list[list] = []
    iteration = 0
    current_end = end_ms
    while iteration < 20:
        params = {
            "currency": "BTC",
            "start_timestamp": start_ms,
            "end_timestamp": current_end,
            "resolution": "1D",
        }
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        payload = r.json().get("result", {})
        data = payload.get("data", [])
        cont = payload.get("continuation")
        if not data:
            break
        all_rows.extend(data)
        log(
            f"  DVOL page {iteration}: {len(data)} rows, "
            f"first={dt.datetime.fromtimestamp(data[0][0] / 1000, dt.UTC).date()} "
            f"last={dt.datetime.fromtimestamp(data[-1][0] / 1000, dt.UTC).date()}, "
            f"cont={cont}"
        )
        iteration += 1
        if cont is None:
            break
        current_end = int(cont)
        if current_end <= start_ms:
            break
        time.sleep(0.2)

    # Deduplicate + sort asc
    seen = set()
    uniq: list[list] = []
    for row in all_rows:
        if row[0] not in seen:
            seen.add(row[0])
            uniq.append(row)
    uniq.sort(key=lambda x: x[0])
    df = pd.DataFrame(uniq, columns=["ts_ms", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert(None).dt.normalize()
    df = df.set_index("date")[["open", "high", "low", "close"]]
    df.index.name = "date"
    return df


def fetch_btc_daily() -> pd.DataFrame:
    import yfinance as yf

    log("Fetching BTC-USD via yfinance...")
    df = yf.download("BTC-USD", start="2020-01-01", end="2026-04-14", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    df["log_r"] = np.log(df["Close"]).diff()
    return df


def fetch_vix_daily() -> pd.DataFrame:
    import yfinance as yf

    log("Fetching ^VIX via yfinance...")
    df = yf.download("^VIX", start="2020-01-01", end="2026-04-14", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].rename(columns={"Close": "vix"}).copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df


def main() -> int:
    log("K1119 fetch: BTC DVOL + BTC-USD + ^VIX")

    dvol = fetch_dvol_daily()
    dvol_path = OUT / "dvol_daily.csv"
    dvol.to_csv(dvol_path)
    log(
        f"DVOL saved -> {dvol_path}  n={len(dvol)} "
        f"range=[{dvol.index.min().date()}..{dvol.index.max().date()}]"
    )

    btc = fetch_btc_daily()
    btc_path = OUT / "btc_ohlcv.csv"
    btc.to_csv(btc_path)
    log(
        f"BTC saved  -> {btc_path}   n={len(btc)}  "
        f"range=[{btc.index.min().date()}..{btc.index.max().date()}]"
    )

    vix = fetch_vix_daily()
    vix_path = OUT / "vix_daily.csv"
    vix.to_csv(vix_path)
    log(
        f"VIX saved  -> {vix_path}   n={len(vix)}  "
        f"range=[{vix.index.min().date()}..{vix.index.max().date()}]"
    )

    summary = {
        "dvol_n": int(len(dvol)),
        "dvol_start": str(dvol.index.min().date()),
        "dvol_end": str(dvol.index.max().date()),
        "btc_n": int(len(btc)),
        "btc_start": str(btc.index.min().date()),
        "btc_end": str(btc.index.max().date()),
        "vix_n": int(len(vix)),
        "vix_start": str(vix.index.min().date()),
        "vix_end": str(vix.index.max().date()),
        "fetched_at_utc": dt.datetime.now(dt.UTC).isoformat(),
    }
    (OUT / "fetch_summary.json").write_text(json.dumps(summary, indent=2))
    log(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
