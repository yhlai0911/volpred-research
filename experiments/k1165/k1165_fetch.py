#!/usr/bin/env python3
"""K1165 data fetch — 4 new markets (AU, KR, CA, HK) for N=8 cross-market confirmation.

Fetches per-ticker:
 - OHLCV daily prices 2014-01-01 → 2025-12-31 (yfinance history) -> parquet cache
 - earnings_dates via Ticker.get_earnings_dates (past 4-8y) -> JSON cache
 - major_holders (institutionsPercentHeld, insidersPercentHeld) -> JSON
 - Ticker.info (trailingAnalystsCount / numberOfAnalystOpinions,
   marketCap, averageDailyVolume10Day) -> JSON

Also fetches local VIX index once per market (^VIX for all — global risk-off proxy).
Writes under experiments/k1165/data/.

Random seed: 42 (convention only; no stochasticity here).
Rate limit: time.sleep(1.0) between tickers to be polite.

Lookahead discipline: earnings_dates beyond today are ignored (yfinance may return
future expected dates); filter `date < today` before building EAV.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

np.random.seed(42)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

START = "2014-01-01"
END = "2025-12-31"

# 4 new markets × 10 stocks each
AU_TICKERS = ["CBA.AX", "BHP.AX", "RIO.AX", "NAB.AX", "ANZ.AX",
              "WBC.AX", "WES.AX", "WOW.AX", "FMG.AX", "MQG.AX"]
KR_TICKERS = ["005930.KS", "000660.KS", "207940.KS", "005380.KS", "035420.KS",
              "005490.KS", "035720.KS", "028260.KS", "105560.KS", "055550.KS"]
CA_TICKERS = ["RY.TO", "TD.TO", "ENB.TO", "BNS.TO", "BMO.TO",
              "CNQ.TO", "BCE.TO", "CP.TO", "MFC.TO", "CSU.TO"]
HK_TICKERS = ["0700.HK", "0388.HK", "0939.HK", "1299.HK", "0005.HK",
              "1398.HK", "0941.HK", "0883.HK", "0016.HK", "1109.HK"]

MARKET_TICKERS = {"AU": AU_TICKERS, "KR": KR_TICKERS, "CA": CA_TICKERS, "HK": HK_TICKERS}


def _safe_name(ticker: str) -> str:
    return ticker.replace(".", "_").replace("-", "_").replace("^", "IDX_")


def fetch_price(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, start=START, end=END, progress=False,
                         auto_adjust=True, threads=False)
    except Exception as e:
        print(f"    price fetch fail: {e}")
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_earnings(ticker: str, today: pd.Timestamp) -> list[str]:
    try:
        t = yf.Ticker(ticker)
        df = t.get_earnings_dates(limit=60)
    except Exception as e:
        print(f"    earnings fetch fail: {e}")
        return []
    if df is None or len(df) == 0:
        return []
    # Index is DatetimeIndex of earnings dates (with tz); drop tz, keep past only
    dates = []
    for idx in df.index:
        try:
            d = pd.Timestamp(idx).tz_convert(None) if getattr(idx, "tzinfo", None) else pd.Timestamp(idx)
            if pd.notna(d) and d < today:
                dates.append(d.strftime("%Y-%m-%d"))
        except Exception:
            continue
    return sorted(set(dates))


def extract_major_holders(df: pd.DataFrame | None) -> dict | None:
    if df is None or df.empty:
        return None
    out: dict = {}
    keyed: dict = {}
    if getattr(df.index, "name", None) == "Breakdown" and "Value" in df.columns:
        for idx in df.index:
            keyed[str(idx)] = df.loc[idx, "Value"]
    elif "Breakdown" in df.columns and "Value" in df.columns:
        keyed = dict(zip(df["Breakdown"].astype(str), df["Value"]))
    else:
        try:
            if df.shape[1] >= 2:
                keyed = dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1]))
            elif df.shape[1] == 1:
                keyed = {str(idx): df.iloc[i, 0] for i, idx in enumerate(df.index)}
        except Exception:
            return None
    for k in ("insidersPercentHeld", "institutionsPercentHeld",
              "institutionsFloatPercentHeld", "institutionsCount"):
        v = keyed.get(k)
        if v is None:
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


def fetch_info(ticker: str) -> dict:
    """Fetch analyst count + market cap + turnover via Ticker.info."""
    out = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        return {"error": str(e)}
    for k in ("numberOfAnalystOpinions", "recommendationKey",
              "marketCap", "averageVolume10days", "averageVolume",
              "trailingPE", "sharesOutstanding", "currency"):
        v = info.get(k)
        if v is not None:
            out[k] = v
    # Prefer `numberOfAnalystOpinions` (yfinance 0.2 field name)
    ac = info.get("numberOfAnalystOpinions")
    if ac is None:
        ac = info.get("targetMeanAnalysts") or info.get("analystCount")
    out["analyst_count"] = ac
    return out


def fetch_vix() -> pd.DataFrame | None:
    return fetch_price("^VIX")


def main() -> None:
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    # ---- VIX (single fetch, shared across markets) ----
    vix_cache = DATA / "IDX_VIX.parquet"
    if not vix_cache.exists():
        print("[K1165-fetch] VIX...")
        vix = fetch_vix()
        if vix is not None:
            vix.to_parquet(vix_cache)
            print(f"  VIX rows={len(vix)}")
        time.sleep(1.0)
    else:
        print(f"[K1165-fetch] VIX cached ({vix_cache.name})")

    # ---- per-market fetch ----
    earnings_cache: dict[str, list[str]] = {}
    holders_cache: dict = {"records": []}
    info_cache: dict = {}

    for market, tickers in MARKET_TICKERS.items():
        print(f"\n[{market}] n={len(tickers)}")
        for i, tkr in enumerate(tickers, 1):
            safe = _safe_name(tkr)
            parquet = DATA / f"{safe}.parquet"
            # price
            if not parquet.exists():
                px = fetch_price(tkr)
                if px is not None and not px.empty and "Close" in px.columns:
                    px.to_parquet(parquet)
                    print(f"  [{i:02d}/{len(tickers)}] {tkr} price rows={len(px)}")
                else:
                    print(f"  [{i:02d}/{len(tickers)}] {tkr} PRICE FAIL")
            else:
                print(f"  [{i:02d}/{len(tickers)}] {tkr} price cached")
            time.sleep(1.0)

            # earnings
            if tkr not in earnings_cache:
                dates = fetch_earnings(tkr, today)
                earnings_cache[tkr] = dates
                print(f"          earnings n={len(dates)}")
                time.sleep(1.0)

            # major_holders
            try:
                mh = yf.Ticker(tkr).major_holders
            except Exception as e:
                mh = None
                print(f"          holders fail: {e}")
            holders_cache["records"].append({
                "ticker": tkr, "market": market,
                "major_holders": extract_major_holders(mh),
            })
            time.sleep(1.0)

            # info
            if tkr not in info_cache:
                info = fetch_info(tkr)
                info["market"] = market
                info_cache[tkr] = info
                print(f"          analyst_count={info.get('analyst_count')}"
                      f" mcap={info.get('marketCap')}")
                time.sleep(1.0)

    # Save caches
    (DATA / "earnings_dates.json").write_text(
        json.dumps(earnings_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    holders_cache["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    holders_cache["source"] = "yfinance Ticker.major_holders"
    (DATA / "institutional_ownership_new.json").write_text(
        json.dumps(holders_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "ticker_info.json").write_text(
        json.dumps(info_cache, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\n[K1165-fetch] wrote earnings_dates.json / institutional_ownership_new.json / ticker_info.json")


if __name__ == "__main__":
    main()
