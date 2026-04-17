#!/usr/bin/env python3
"""K1172 data fetch — 3 additional markets (MX, ZA, ID) for N=13 cross-market test.

Extends K1168's 10-market design (TW/EU/JP/US + KR/CA/HK + BR/CH/IN) with:
 - MX (Bolsa Mexicana top 10): WALMEX, AMXB, GFNORTE, FEMSA, CEMEX, BIMBOA, GMEXICOB, etc.
 - ZA (JSE Top 40 subset top 10): NPN, BHP, AGL, SOL, MTN, SBK, FSR, ABG, etc.
 - ID (IDX Composite large-caps top 10): BBCA, BBRI, TLKM, ASII, UNVR, ICBP, BMRI, ADRO, etc.

Same yfinance pipeline as K1168_fetch.py — reuse exact functions.
No data-fetch pipeline rewrite (K1168 methodology preserved).

Random seed: 42.
"""
from __future__ import annotations

import json
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

# MX — Bolsa Mexicana de Valores top 10 market-cap (yfinance .MX suffix)
MX_TICKERS = [
    "WALMEX.MX",    # Walmart de Mexico
    "AMXB.MX",      # America Movil L (replaced AMX.MX in recent yfinance)
    "GFNORTEO.MX",  # Grupo Financiero Banorte
    "FEMSAUBD.MX",  # FEMSA (UB class)
    "CEMEXCPO.MX",  # CEMEX
    "BIMBOA.MX",    # Grupo Bimbo
    "GMEXICOB.MX",  # Grupo Mexico (mining)
    "KOFUBL.MX",    # Coca-Cola FEMSA
    "TLEVISACPO.MX",# Televisa
    "GRUMAB.MX",    # Gruma (replaced ALFAA.MX delisted 2022)
]

# ZA — JSE Top 40 subset (yfinance .JO suffix)
ZA_TICKERS = [
    "NPN.JO",       # Naspers
    "BHG.JO",       # BHP Group (JSE listing)
    "AGL.JO",       # Anglo American
    "SOL.JO",       # Sasol
    "MTN.JO",       # MTN Group
    "SBK.JO",       # Standard Bank
    "FSR.JO",       # FirstRand
    "ABG.JO",       # Absa Group
    "SLM.JO",       # Sanlam
    "CPI.JO",       # Capitec Bank
]

# ID — IDX Composite large-caps (yfinance .JK suffix)
ID_TICKERS = [
    "BBCA.JK",      # Bank Central Asia
    "BBRI.JK",      # Bank Rakyat Indonesia
    "TLKM.JK",      # Telkom Indonesia
    "ASII.JK",      # Astra International
    "UNVR.JK",      # Unilever Indonesia
    "ICBP.JK",      # Indofood CBP
    "BMRI.JK",      # Bank Mandiri
    "ADRO.JK",      # Adaro Energy
    "GGRM.JK",      # Gudang Garam
    "INDF.JK",      # Indofood Sukses Makmur
]

MARKET_TICKERS = {"MX": MX_TICKERS, "ZA": ZA_TICKERS, "ID": ID_TICKERS}


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
    ac = info.get("numberOfAnalystOpinions")
    if ac is None:
        ac = info.get("targetMeanAnalysts") or info.get("analystCount")
    out["analyst_count"] = ac
    return out


def main() -> None:
    today = pd.Timestamp(datetime.now(timezone.utc).date())

    earnings_cache: dict[str, list[str]] = {}
    holders_cache: dict = {"records": []}
    info_cache: dict = {}

    for market, tickers in MARKET_TICKERS.items():
        print(f"\n[{market}] n={len(tickers)}")
        for i, tkr in enumerate(tickers, 1):
            safe = _safe_name(tkr)
            parquet = DATA / f"{safe}.parquet"
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

            if tkr not in earnings_cache:
                try:
                    dates = fetch_earnings(tkr, today)
                except Exception as e:
                    print(f"          earnings error: {e}")
                    dates = []
                earnings_cache[tkr] = dates
                print(f"          earnings n={len(dates)}")
                time.sleep(1.0)

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

            if tkr not in info_cache:
                try:
                    info = fetch_info(tkr)
                except Exception as e:
                    info = {"error": str(e)}
                info["market"] = market
                info_cache[tkr] = info
                print(f"          analyst_count={info.get('analyst_count')}"
                      f" mcap={info.get('marketCap')}")
                time.sleep(1.0)

    (DATA / "earnings_dates_k1172.json").write_text(
        json.dumps(earnings_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    holders_cache["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    holders_cache["source"] = "yfinance Ticker.major_holders"
    (DATA / "institutional_ownership_k1172.json").write_text(
        json.dumps(holders_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "ticker_info_k1172.json").write_text(
        json.dumps(info_cache, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\n[K1172-fetch] wrote earnings_dates_k1172.json / institutional_ownership_k1172.json / ticker_info_k1172.json")


if __name__ == "__main__":
    main()
