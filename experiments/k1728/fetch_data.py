#!/usr/bin/env python3
"""K1728 one-time data fetcher.

Downloads every raw source ONCE and writes clean, deterministic CSVs to
``experiments/k1728/data/``. The analysis script ``k1728.py`` then reads only
those cached CSVs, so the analysis is fully reproducible offline and never
depends on live network or optional packages (openpyxl).

Sources (all FREE):
  * yfinance          -> SPY, QQQ daily OHLC             -> spy_ohlc.csv, qqq_ohlc.csv
  * FRED official API -> USEPUINDXD (EPU), VIXCLS (VIX)  -> fred_USEPUINDXD.csv, fred_VIXCLS.csv
  * SF Fed FRBSF      -> Daily News Sentiment Index      -> sf_news_sentiment.csv

Google Trends (pytrends) was ATTEMPTED as a media-attention proxy but the free
endpoint returned HTTP 429 (rate limited) on 2026-07-27; per the experiment
brief we fall back to FRED-based attention/uncertainty proxies (EPU, VIX) and
document the limitation in the README. No paid API is used.

FRED public ``fredgraph.csv`` scraping is bot-blocked (repo error_log 2026-05-29),
so we use the official API with FRED_API_KEY loaded from the main checkout's
``.env.local`` (git-ignored). Run with ``uv run --with openpyxl python`` so the
one-time xlsx parse works even though openpyxl is not a project dependency.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

# Repo root that holds .env.local (worktrees do not carry the git-ignored file).
MAIN_CHECKOUT = Path("/Users/yhlai0911/volpred-research")

START = "2005-01-01"          # SPY history is deep; EPU/VIX both start 1990.
UA = {"User-Agent": "volpred-research k1728"}


def log(msg: str) -> None:
    print(f"[fetch] {msg}", flush=True)


def _fred_api_key() -> str:
    env_local = MAIN_CHECKOUT / ".env.local"
    if not env_local.exists():
        raise RuntimeError(f"FRED_API_KEY source missing: {env_local}")
    for line in env_local.read_text().splitlines():
        line = line.strip()
        if line.startswith("FRED_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("FRED_API_KEY not found in .env.local")


def fetch_fred(series_id: str) -> pd.DataFrame:
    key = _fred_api_key()
    params = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": "1990-01-01",
    })
    url = "https://api.stlouisfed.org/fred/series/observations?" + params
    req = urllib.request.Request(url, headers=UA)
    payload = json.load(urllib.request.urlopen(req, timeout=90))
    rows = [
        (o["date"], o["value"])
        for o in payload["observations"]
        if o["value"] not in (".", "", None)
    ]
    df = pd.DataFrame(rows, columns=["DATE", series_id])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    out = DATA / f"fred_{series_id}.csv"
    df.to_csv(out, index=False)
    log(f"FRED {series_id}: n={len(df)} {df['DATE'].iloc[0]}..{df['DATE'].iloc[-1]} -> {out.name}")
    return df


def fetch_yf(ticker: str, fname: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(ticker, start=START, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index.name = "DATE"
    df = df.reset_index()
    df["DATE"] = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")
    out = DATA / fname
    df.to_csv(out, index=False)
    log(f"yfinance {ticker}: n={len(df)} {df['DATE'].iloc[0]}..{df['DATE'].iloc[-1]} -> {out.name}")
    return df


def fetch_sf_news() -> pd.DataFrame:
    url = "https://www.frbsf.org/wp-content/uploads/sites/4/news_sentiment_data.xlsx"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=90).read()
    (DATA / "sf_news_sentiment_data.xlsx").write_bytes(raw)
    df = pd.read_excel(io.BytesIO(raw), sheet_name="Data")
    df.columns = ["DATE", "news_sentiment"]
    df["DATE"] = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")
    df["news_sentiment"] = pd.to_numeric(df["news_sentiment"], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    out = DATA / "sf_news_sentiment.csv"
    df.to_csv(out, index=False)
    log(f"SF Fed news sentiment: n={len(df)} {df['DATE'].iloc[0]}..{df['DATE'].iloc[-1]} -> {out.name}")
    return df


def main() -> int:
    prov: dict[str, dict] = {}

    spy = fetch_yf("SPY", "spy_ohlc.csv")
    prov["SPY"] = {"source": "yfinance", "ticker": "SPY", "n": int(len(spy)),
                   "start": spy["DATE"].iloc[0], "end": spy["DATE"].iloc[-1]}
    qqq = fetch_yf("QQQ", "qqq_ohlc.csv")
    prov["QQQ"] = {"source": "yfinance", "ticker": "QQQ", "n": int(len(qqq)),
                   "start": qqq["DATE"].iloc[0], "end": qqq["DATE"].iloc[-1]}

    epu = fetch_fred("USEPUINDXD")
    prov["EPU"] = {"source": "FRED official API", "series_id": "USEPUINDXD",
                   "name": "Daily Economic Policy Uncertainty Index (Baker-Bloom-Davis)",
                   "n": int(len(epu)), "start": epu["DATE"].iloc[0], "end": epu["DATE"].iloc[-1]}
    vix = fetch_fred("VIXCLS")
    prov["VIX"] = {"source": "FRED official API", "series_id": "VIXCLS",
                   "name": "CBOE Volatility Index (VIX) Close",
                   "n": int(len(vix)), "start": vix["DATE"].iloc[0], "end": vix["DATE"].iloc[-1]}

    news = fetch_sf_news()
    prov["news_sentiment"] = {
        "source": "Federal Reserve Bank of San Francisco",
        "series": "Daily News Sentiment Index (Buckman-Shapiro-Sudhof-Wilson)",
        "url": "https://www.frbsf.org/wp-content/uploads/sites/4/news_sentiment_data.xlsx",
        "n": int(len(news)), "start": news["DATE"].iloc[0], "end": news["DATE"].iloc[-1]}

    prov["google_trends"] = {
        "source": "pytrends (Google Trends)",
        "status": "UNAVAILABLE",
        "reason": "HTTP 429 rate-limited on 2026-07-27; fell back to FRED EPU/VIX per brief.",
    }

    (DATA / "provenance.json").write_text(json.dumps(prov, indent=2))
    log("wrote provenance.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
