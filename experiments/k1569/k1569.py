#!/usr/bin/env python3
"""K1569: legacy-asset overhang, transition shock, and sector ETF volatility.

This is a public-disclosure proxy screen. It does not observe true stranded
assets, plant-level redeployability, internal transformation spending, or
private credit spreads. It combines SEC CompanyFacts annual XBRL balance-sheet
items with public ETF prices to ask whether sectors with higher PP&E-minus-
intangibles exposure show stronger RV/downside/volume responses after green-tech
or automation market shocks.

Lookahead policy:
- SEC XBRL ratios become usable only after their filing date plus one calendar
  day and are aligned to the first subsequent ETF trading date.
- Market shock predictors are explicitly shifted once: signal_lag1 = signal.shift(1).
- Forward targets use strictly [t+1, t+H].
- Primary inference uses date-level high-legacy minus low-legacy spreads, not
  stacked sector-day iid inference.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
RNG = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SEC_DIR = DATA_DIR / "sec_companyfacts"
OUT_JSON = HERE / "k1569_results.json"
OUT_DATA = HERE / "k1569_analysis_dataset.csv"
OUT_SCORES = HERE / "k1569_sector_legacy_scores.csv"
FIG1 = HERE / "fig1_sector_legacy_scores.png"
FIG2 = HERE / "fig2_transition_credit_signals.png"
FIG3 = HERE / "fig3_primary_hac_heatmap.png"

START = "2018-01-01"
LAST_COMPLETE_UTC_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)
END = (LAST_COMPLETE_UTC_DATE + timedelta(days=1)).isoformat()

ROLL_Z = 252
RV_WINDOW = 21
VOL_BASE_WINDOW = 63
BOOTSTRAP_B = 1000

SECTOR_TARGETS = ["XLE", "KRE", "KBE", "XLF", "XLI", "XLY", "XLK", "ICLN", "TAN", "BOTZ", "ROBO"]
GREEN_AUTOMATION_ETFS = ["ICLN", "TAN", "BOTZ", "ROBO"]
LEGACY_MARKET_ETFS = ["XLE", "KRE", "KBE", "XLI", "XLY"]
CONTROL_TICKERS = ["SPY", "^VIX", "HYG", "LQD"]
PRICE_TICKERS = sorted(set(SECTOR_TARGETS + GREEN_AUTOMATION_ETFS + LEGACY_MARKET_ETFS + CONTROL_TICKERS))
HORIZONS = [5, 21]
OUTCOMES = ["log_rv", "log_downside_var", "volume_shock"]
SIGNALS = ["transition_shock", "credit_stress", "transition_credit_stress"]

COMPANY_BASKETS = {
    "XLE": ["XOM", "CVX", "COP", "EOG", "SLB", "MPC"],
    "KRE": ["RF", "KEY", "FITB", "CFG", "ZION", "HBAN"],
    "KBE": ["JPM", "BAC", "WFC", "C", "USB", "PNC"],
    "XLF": ["JPM", "BAC", "WFC", "GS", "MS", "BLK"],
    "XLI": ["CAT", "GE", "BA", "HON", "DE", "UNP"],
    "XLY": ["F", "GM", "TSLA", "AMZN", "HD", "NKE"],
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "ADBE"],
    "ICLN": ["FSLR", "ENPH", "RUN", "PLUG", "SEDG", "BE"],
    "TAN": ["FSLR", "ENPH", "RUN", "SEDG", "NOVA", "ARRY"],
    "BOTZ": ["NVDA", "ISRG", "TER", "CGNX", "ROK", "ABBV"],
    "ROBO": ["TER", "CGNX", "ROK", "ISRG", "ZBRA", "ABBV"],
}

SEC_HEADERS = {
    "User-Agent": "volpred-research k1569 contact: research@volpred.local",
    "Accept-Encoding": "gzip, deflate",
}

ASSET_TAGS = ["Assets"]
PPE_TAGS = [
    "PropertyPlantAndEquipmentNet",
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
]
GOODWILL_TAGS = ["Goodwill"]
INTANGIBLE_TAGS = [
    "IntangibleAssetsNetExcludingGoodwill",
    "FiniteLivedIntangibleAssetsNet",
    "IndefiniteLivedIntangibleAssetsExcludingGoodwill",
    "OtherIntangibleAssetsNet",
    "GoodwillAndIntangibleAssetsNet",
]


@dataclass
class SourceInfo:
    path: Path
    source_url: str
    fetched: bool


def git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=HERE.parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_or_none(obj):
    if isinstance(obj, dict):
        return {k: finite_or_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite_or_none(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    return obj


def rolling_z(s: pd.Series, window: int = ROLL_Z, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(30, window // 4)
    mu = s.rolling(window, min_periods=min_periods).mean().shift(1)
    sd = s.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


def describe_series(s: pd.Series) -> dict:
    x = s.dropna()
    if x.empty:
        return {"n": 0}
    return {
        "n": int(x.shape[0]),
        "start": str(x.index.min().date()),
        "end": str(x.index.max().date()),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)),
        "p05": float(x.quantile(0.05)),
        "p50": float(x.quantile(0.50)),
        "p95": float(x.quantile(0.95)),
    }


def fetch_ohlcv(refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    close_path = DATA_DIR / "yfinance_close.csv"
    volume_path = DATA_DIR / "yfinance_volume.csv"
    if close_path.exists() and volume_path.exists() and not refresh:
        close = pd.read_csv(close_path, index_col=0, parse_dates=True)
        volume = pd.read_csv(volume_path, index_col=0, parse_dates=True)
        return close, volume, SourceInfo(close_path, "yfinance adjusted OHLCV cache", False)

    raw = yf.download(
        PRICE_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Expected yfinance multi-ticker OHLCV response")
    close = raw["Close"].copy()
    volume = raw["Volume"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    volume.index = pd.to_datetime(volume.index).tz_localize(None).normalize()
    close = close.sort_index()
    volume = volume.sort_index()
    keep = [t for t in PRICE_TICKERS if t in close.columns and close[t].dropna().shape[0] >= 500]
    required = ["SPY", "^VIX", "HYG", "LQD", "XLE", "XLF", "XLI", "XLK"]
    missing = [t for t in required if t not in keep]
    if missing:
        raise RuntimeError(f"missing required yfinance data: {missing}")
    close = close[keep]
    volume = volume[[t for t in keep if t in volume.columns]]
    close.to_csv(close_path)
    volume.to_csv(volume_path)
    return close, volume, SourceInfo(close_path, f"yfinance adjusted OHLCV {START} to {END}", True)


def fetch_sec_ticker_map(refresh: bool) -> tuple[dict[str, dict], SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "sec_company_tickers.json"
    url = "https://www.sec.gov/files/company_tickers.json"
    if path.exists() and not refresh:
        raw = json.loads(path.read_text())
        return {v["ticker"].upper(): v for v in raw.values()}, SourceInfo(path, url, False)
    resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    raw = resp.json()
    return {v["ticker"].upper(): v for v in raw.values()}, SourceInfo(path, url, True)


def fetch_companyfacts(ticker: str, cik: int, refresh: bool) -> tuple[dict, SourceInfo]:
    SEC_DIR.mkdir(parents=True, exist_ok=True)
    cik_padded = f"{cik:010d}"
    path = SEC_DIR / f"{ticker}_{cik_padded}.json.gz"
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f), SourceInfo(path, url, False)
    resp = requests.get(url, headers=SEC_HEADERS, timeout=45)
    resp.raise_for_status()
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(resp.content)
    time.sleep(0.12)
    return resp.json(), SourceInfo(path, url, True)


def annual_tag_rows(facts: dict, tag_candidates: list[str]) -> pd.DataFrame:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    rows = []
    for tag in tag_candidates:
        units = gaap.get(tag, {}).get("units", {})
        vals = units.get("USD") or units.get("shares")
        if not vals:
            continue
        for item in vals:
            form = str(item.get("form", ""))
            if not form.startswith("10-K"):
                continue
            if item.get("fy") is None or item.get("filed") is None:
                continue
            fp = str(item.get("fp", ""))
            if fp and fp != "FY":
                continue
            val = pd.to_numeric(item.get("val"), errors="coerce")
            if not np.isfinite(val):
                continue
            rows.append(
                {
                    "fy": int(item["fy"]),
                    "filed": pd.Timestamp(item["filed"]).normalize(),
                    "value": float(val),
                    "tag": tag,
                }
            )
        if rows:
            break
    if not rows:
        return pd.DataFrame(columns=["fy", "filed", "value", "tag"])
    df = pd.DataFrame(rows)
    return df.sort_values(["fy", "filed"]).drop_duplicates(["fy"], keep="last")


def extract_company_legacy_table(ticker: str, facts: dict) -> pd.DataFrame:
    assets = annual_tag_rows(facts, ASSET_TAGS).rename(
        columns={"filed": "filed_assets", "value": "assets", "tag": "assets_tag"}
    )
    ppe = annual_tag_rows(facts, PPE_TAGS).rename(
        columns={"filed": "filed_ppe", "value": "ppe", "tag": "ppe_tag"}
    )
    goodwill = annual_tag_rows(facts, GOODWILL_TAGS).rename(
        columns={"filed": "filed_goodwill", "value": "goodwill", "tag": "goodwill_tag"}
    )
    intangible = annual_tag_rows(facts, INTANGIBLE_TAGS).rename(
        columns={"filed": "filed_intangibles", "value": "intangibles", "tag": "intangibles_tag"}
    )
    if assets.empty or ppe.empty:
        return pd.DataFrame()
    out = assets[["fy", "filed_assets", "assets", "assets_tag"]].merge(
        ppe[["fy", "filed_ppe", "ppe", "ppe_tag"]], on="fy", how="left"
    )
    if goodwill.empty:
        out["filed_goodwill"] = pd.NaT
        out["goodwill"] = 0.0
        out["goodwill_tag"] = ""
    else:
        out = out.merge(goodwill[["fy", "filed_goodwill", "goodwill", "goodwill_tag"]], on="fy", how="left")
    if intangible.empty:
        out["filed_intangibles"] = pd.NaT
        out["intangibles"] = 0.0
        out["intangibles_tag"] = ""
    else:
        out = out.merge(
            intangible[["fy", "filed_intangibles", "intangibles", "intangibles_tag"]],
            on="fy",
            how="left",
        )
    out["goodwill"] = out["goodwill"].fillna(0.0)
    out["intangibles"] = out["intangibles"].fillna(0.0)
    out["asset_proxy_filed"] = out[
        ["filed_assets", "filed_ppe", "filed_goodwill", "filed_intangibles"]
    ].max(axis=1)
    out["available_after"] = out["asset_proxy_filed"] + pd.Timedelta(days=1)
    out["ppe_to_assets"] = out["ppe"] / out["assets"].where(out["assets"] > 0)
    combined_tag = out["intangibles_tag"].fillna("").eq("GoodwillAndIntangibleAssetsNet")
    intangible_total = np.where(combined_tag, out["intangibles"], out["goodwill"] + out["intangibles"])
    out["intangible_to_assets"] = intangible_total / out["assets"].where(out["assets"] > 0)
    out["legacy_asset_score"] = out["ppe_to_assets"] - out["intangible_to_assets"]
    out["ticker"] = ticker
    keep_cols = [
        "ticker",
        "fy",
        "available_after",
        "assets",
        "ppe",
        "goodwill",
        "intangibles",
        "ppe_to_assets",
        "intangible_to_assets",
        "legacy_asset_score",
        "assets_tag",
        "ppe_tag",
        "goodwill_tag",
        "intangibles_tag",
    ]
    return out[keep_cols].replace([np.inf, -np.inf], np.nan).dropna(subset=["legacy_asset_score"])


def build_company_legacy_tables(refresh: bool) -> tuple[pd.DataFrame, dict]:
    ticker_map, map_info = fetch_sec_ticker_map(refresh=refresh)
    all_tickers = sorted({t for tickers in COMPANY_BASKETS.values() for t in tickers})
    rows = []
    company_meta = {}
    for ticker in all_tickers:
        info = ticker_map.get(ticker)
        if not info:
            company_meta[ticker] = {"error": "ticker_not_in_sec_map"}
            continue
        try:
            facts, source = fetch_companyfacts(ticker, int(info["cik_str"]), refresh=refresh)
            tbl = extract_company_legacy_table(ticker, facts)
            if not tbl.empty:
                rows.append(tbl)
            company_meta[ticker] = {
                "cik": int(info["cik_str"]),
                "title": info.get("title"),
                "path": str(source.path.relative_to(HERE)),
                "sha256": sha256_file(source.path),
                "n_annual_rows": int(tbl.shape[0]),
            }
        except Exception as exc:
            company_meta[ticker] = {"error": f"{type(exc).__name__}: {exc}"}
    if not rows:
        raise RuntimeError("No SEC CompanyFacts legacy tables could be built")
    company_table = pd.concat(rows, ignore_index=True).sort_values(["ticker", "available_after", "fy"])
    path = DATA_DIR / "company_legacy_xbrl_table.csv"
    company_table.to_csv(path, index=False)
    meta = {
        "ticker_map": {
            "url": map_info.source_url,
            "path": str(map_info.path.relative_to(HERE)),
            "sha256": sha256_file(map_info.path),
        },
        "companyfacts": company_meta,
        "company_legacy_table": {
            "path": str(path.relative_to(HERE)),
            "sha256": sha256_file(path),
        },
    }
    return company_table, meta


def company_daily_score(company_table: pd.DataFrame, ticker: str, trading_index: pd.DatetimeIndex) -> pd.Series:
    d = company_table.loc[company_table["ticker"] == ticker].copy()
    if d.empty:
        return pd.Series(index=trading_index, dtype=float, name=ticker)
    d["available_after"] = pd.to_datetime(d["available_after"])
    s = pd.Series(index=trading_index, dtype=float, name=ticker)
    for row in d.itertuples(index=False):
        pos = trading_index.searchsorted(pd.Timestamp(row.available_after).normalize(), side="left")
        if pos < len(trading_index):
            s.iloc[pos] = row.legacy_asset_score
    return s.ffill()


def build_sector_legacy_scores(
    company_table: pd.DataFrame, trading_index: pd.DatetimeIndex, available_targets: list[str]
) -> pd.DataFrame:
    company_scores = {
        ticker: company_daily_score(company_table, ticker, trading_index)
        for ticker in sorted({t for tickers in COMPANY_BASKETS.values() for t in tickers})
    }
    company_scores_df = pd.DataFrame(company_scores, index=trading_index)
    sector_scores = pd.DataFrame(index=trading_index)
    for target, tickers in COMPANY_BASKETS.items():
        if target not in available_targets:
            continue
        existing = [t for t in tickers if t in company_scores_df.columns]
        if not existing:
            continue
        sector_scores[f"{target}_legacy_score"] = company_scores_df[existing].mean(axis=1, skipna=True).where(
            company_scores_df[existing].count(axis=1) >= max(2, len(existing) // 2)
        )
    sector_scores.to_csv(OUT_SCORES)
    return sector_scores


def equal_weight_return(ret: pd.DataFrame, tickers: list[str], min_count: int = 2) -> pd.Series:
    available = [t for t in tickers if t in ret.columns]
    if not available:
        return pd.Series(index=ret.index, dtype=float)
    return ret[available].mean(axis=1, skipna=True).where(ret[available].count(axis=1) >= min_count)


def build_feature_matrix(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    close, volume, price_info = fetch_ohlcv(refresh=refresh)
    close = close.loc[(close.index >= pd.Timestamp(START)) & (close.index <= pd.Timestamp(LAST_COMPLETE_UTC_DATE))]
    close = close.loc[close[["SPY", "^VIX", "HYG", "LQD"]].notna().all(axis=1)].copy()
    volume = volume.reindex(close.index)
    ret = np.log(close / close.shift(1))
    available_targets = [t for t in SECTOR_TARGETS if t in close.columns and close[t].notna().sum() >= 500]
    df = close.copy()

    company_table, sec_meta = build_company_legacy_tables(refresh=refresh)
    sector_scores = build_sector_legacy_scores(company_table, df.index, available_targets)
    df = pd.concat([df, sector_scores], axis=1)

    green_ret = equal_weight_return(ret, GREEN_AUTOMATION_ETFS, min_count=2)
    legacy_ret = equal_weight_return(ret, LEGACY_MARKET_ETFS, min_count=3)
    green_ret_5d = green_ret.rolling(5, min_periods=5).sum()
    legacy_ret_5d = legacy_ret.rolling(5, min_periods=5).sum()
    spread_ret_5d = green_ret_5d - legacy_ret_5d
    green_rv21 = green_ret.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=1) * np.sqrt(252)
    df["green_auto_ret_5d"] = green_ret_5d
    df["legacy_market_ret_5d"] = legacy_ret_5d
    df["green_minus_legacy_ret_5d"] = spread_ret_5d
    df["green_auto_rv21"] = green_rv21
    df["transition_shock"] = pd.concat(
        [
            rolling_z(spread_ret_5d.abs()),
            rolling_z(green_ret_5d.abs()),
            rolling_z(green_rv21),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)

    credit_spread_ret_5d = ret["HYG"].rolling(5, min_periods=5).sum() - ret["LQD"].rolling(5, min_periods=5).sum()
    df["credit_spread_ret_5d"] = credit_spread_ret_5d
    df["credit_stress"] = rolling_z(-credit_spread_ret_5d)
    df["transition_credit_stress"] = df["transition_shock"] * df["credit_stress"]
    for sig in SIGNALS:
        df[f"{sig}_lag1"] = df[sig].shift(1)

    for ticker in available_targets + ["SPY"]:
        r = ret[ticker]
        rv21 = r.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=1).pow(2) * 252
        down21 = r.clip(upper=0).pow(2).rolling(RV_WINDOW, min_periods=RV_WINDOW).mean() * 252
        df[f"{ticker}_ret"] = r
        df[f"{ticker}_log_rv21_lag1"] = np.log(rv21 + 1e-12).shift(1)
        df[f"{ticker}_log_downside21_lag1"] = np.log(down21 + 1e-12).shift(1)
        if ticker in volume.columns:
            logv = np.log(volume[ticker].replace(0, np.nan))
            vol_mu = logv.rolling(VOL_BASE_WINDOW, min_periods=30).mean().shift(1)
            vol_sd = logv.rolling(VOL_BASE_WINDOW, min_periods=30).std(ddof=1).shift(1)
            df[f"{ticker}_volume_z"] = ((logv - vol_mu) / vol_sd).replace([np.inf, -np.inf], np.nan)
            df[f"{ticker}_volume_z_lag1"] = df[f"{ticker}_volume_z"].shift(1)
        if ticker in available_targets:
            for horizon in HORIZONS:
                future_r2 = pd.concat([r.pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
                future_down = pd.concat([r.clip(upper=0).pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
                future_ret = pd.concat([r.shift(-i) for i in range(1, horizon + 1)], axis=1)
                df[f"{ticker}_fwd_rv_{horizon}d"] = future_r2.mean(axis=1, skipna=False) * 252
                df[f"{ticker}_fwd_log_rv_{horizon}d"] = np.log(df[f"{ticker}_fwd_rv_{horizon}d"] + 1e-12)
                df[f"{ticker}_fwd_downside_var_{horizon}d"] = future_down.mean(axis=1, skipna=False) * 252
                df[f"{ticker}_fwd_log_downside_var_{horizon}d"] = np.log(
                    df[f"{ticker}_fwd_downside_var_{horizon}d"] + 1e-12
                )
                df[f"{ticker}_fwd_cumret_{horizon}d"] = np.exp(future_ret.sum(axis=1, skipna=False)) - 1.0
                if ticker in volume.columns:
                    logv = np.log(volume[ticker].replace(0, np.nan))
                    future_logv = pd.concat([logv.shift(-i) for i in range(1, horizon + 1)], axis=1)
                    base_mu = logv.rolling(VOL_BASE_WINDOW, min_periods=30).mean().shift(1)
                    base_sd = logv.rolling(VOL_BASE_WINDOW, min_periods=30).std(ddof=1).shift(1)
                    df[f"{ticker}_fwd_volume_shock_{horizon}d"] = (
                        (future_logv.mean(axis=1, skipna=False) - base_mu) / base_sd
                    ).replace([np.inf, -np.inf], np.nan)

    df["VIX_level_lag1"] = close["^VIX"].shift(1)
    build_high_low_outcomes(df, available_targets)
    df.to_csv(OUT_DATA)
    source_meta = {
        "yfinance_ohlcv": {
            "url": price_info.source_url,
            "close_path": str((DATA_DIR / "yfinance_close.csv").relative_to(HERE)),
            "volume_path": str((DATA_DIR / "yfinance_volume.csv").relative_to(HERE)),
            "close_sha256": sha256_file(DATA_DIR / "yfinance_close.csv"),
            "volume_sha256": sha256_file(DATA_DIR / "yfinance_volume.csv"),
        },
        "sec_xbrl": sec_meta,
        "sector_legacy_scores": {"path": str(OUT_SCORES.relative_to(HERE)), "sha256": sha256_file(OUT_SCORES)},
        "analysis_dataset": {"path": str(OUT_DATA.relative_to(HERE)), "sha256": sha256_file(OUT_DATA)},
    }
    return df, source_meta


def outcome_col(target: str, horizon: int, outcome: str) -> str:
    if outcome == "log_rv":
        return f"{target}_fwd_log_rv_{horizon}d"
    if outcome == "log_downside_var":
        return f"{target}_fwd_log_downside_var_{horizon}d"
    if outcome == "volume_shock":
        return f"{target}_fwd_volume_shock_{horizon}d"
    raise ValueError(outcome)


def build_high_low_outcomes(df: pd.DataFrame, targets: list[str]) -> None:
    score_cols = {t: f"{t}_legacy_score" for t in targets if f"{t}_legacy_score" in df.columns}
    group_records = []
    for dt, row in df[list(score_cols.values())].iterrows():
        scores = row.dropna()
        if scores.shape[0] < 6:
            group_records.append({"date": dt, "high_group": "", "low_group": "", "n_scores": int(scores.shape[0])})
            continue
        ranked = scores.sort_values()
        n_each = max(2, scores.shape[0] // 3)
        low_cols = list(ranked.index[:n_each])
        high_cols = list(ranked.index[-n_each:])
        high_targets = [c.replace("_legacy_score", "") for c in high_cols]
        low_targets = [c.replace("_legacy_score", "") for c in low_cols]
        group_records.append(
            {
                "date": dt,
                "high_group": "|".join(high_targets),
                "low_group": "|".join(low_targets),
                "n_scores": int(scores.shape[0]),
            }
        )
        for horizon in HORIZONS:
            for outcome in OUTCOMES:
                high_vals = [df.at[dt, outcome_col(t, horizon, outcome)] for t in high_targets if outcome_col(t, horizon, outcome) in df.columns]
                low_vals = [df.at[dt, outcome_col(t, horizon, outcome)] for t in low_targets if outcome_col(t, horizon, outcome) in df.columns]
                if len(high_vals) >= 2 and len(low_vals) >= 2:
                    df.at[dt, f"HL_fwd_{outcome}_{horizon}d"] = float(np.nanmean(high_vals) - np.nanmean(low_vals))
    group_df = pd.DataFrame(group_records).set_index("date")
    for col in ["high_group", "low_group", "n_scores"]:
        df[f"group_{col}"] = group_df[col]


def ols_hac(y: pd.Series, x: pd.Series, horizon: int, controls: pd.DataFrame | None = None) -> dict:
    pieces = [y.rename("y"), x.rename("x")]
    if controls is not None:
        pieces.append(controls)
    d = pd.concat(pieces, axis=1).dropna()
    if d.shape[0] < 240 or d["x"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(d.shape[0])}
    x_cols = ["x"] + ([] if controls is None else list(controls.columns))
    X = sm.add_constant(d[x_cols].values)
    model = sm.OLS(d["y"].values, X).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "n": int(d.shape[0]),
        "coef": float(model.params[1]),
        "hac_t": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "r2": float(model.rsquared),
        "controls": x_cols[1:],
    }


def block_bootstrap_spearman(x: pd.Series, y: pd.Series, block: int, reps: int = BOOTSTRAP_B) -> dict:
    d = pd.concat([x, y], axis=1).dropna()
    d.columns = ["x", "y"]
    n = d.shape[0]
    if n < max(240, block * 10) or d["x"].std(ddof=1) <= 1e-12 or d["y"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(n)}
    rho, p = stats.spearmanr(d["x"], d["y"])
    vals = []
    arr_x = d["x"].to_numpy()
    arr_y = d["y"].to_numpy()
    for _ in range(reps):
        idx: list[int] = []
        while len(idx) < n:
            start = int(RNG.integers(0, max(n - block + 1, 1)))
            idx.extend(range(start, min(start + block, n)))
        idx_arr = np.asarray(idx[:n])
        brho, _ = stats.spearmanr(arr_x[idx_arr], arr_y[idx_arr])
        if np.isfinite(brho):
            vals.append(float(brho))
    ci = [None, None]
    if len(vals) >= 100:
        ci = [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))]
    return {
        "n": int(n),
        "rho": float(rho),
        "p_value": float(p),
        "block": int(block),
        "bootstrap_reps": int(len(vals)),
        "ci95": ci,
    }


def holm_bonferroni(rows: list[dict], alpha: float = 0.05) -> dict:
    valid = [r for r in rows if np.isfinite(r.get("p_value", np.nan))]
    ordered = sorted(valid, key=lambda r: r["p_value"])
    decisions = []
    still_reject = True
    m = len(ordered)
    for i, row in enumerate(ordered):
        threshold = alpha / (m - i)
        reject = bool(still_reject and row["p_value"] <= threshold)
        if not reject:
            still_reject = False
        decisions.append(
            {
                "label": row["label"],
                "p_value": float(row["p_value"]),
                "holm_threshold": float(threshold),
                "reject": reject,
                "coef": float(row["coef"]),
                "hac_t": float(row["hac_t"]),
            }
        )
    return {
        "alpha": alpha,
        "n_tests": m,
        "bonferroni_alpha": float(alpha / m) if m else None,
        "bonferroni_survivors": [r["label"] for r in valid if r["p_value"] <= alpha / m],
        "holm_decisions": decisions,
        "holm_survivors": [r["label"] for r in decisions if r["reject"]],
    }


def run_primary_tests(df: pd.DataFrame) -> tuple[dict, list[dict]]:
    out: dict = {}
    p_rows: list[dict] = []
    for horizon in HORIZONS:
        hkey = f"{horizon}d"
        out[hkey] = {}
        for outcome in OUTCOMES:
            y = df[f"HL_fwd_{outcome}_{horizon}d"]
            out[hkey][outcome] = {}
            for sig in SIGNALS:
                control_cols = ["SPY_log_rv21_lag1", "VIX_level_lag1"]
                if sig != "credit_stress":
                    control_cols.append("credit_stress_lag1")
                controls = df[control_cols].copy()
                x = df[f"{sig}_lag1"]
                hac = ols_hac(y, x, horizon=horizon, controls=controls)
                spear = block_bootstrap_spearman(x, y, block=horizon)
                out[hkey][outcome][sig] = {"controlled_hac": hac, "spearman": spear}
                if "p_value" in hac:
                    p_rows.append(
                        {
                            "label": f"HL|{hkey}|{outcome}|{sig}",
                            "p_value": hac["p_value"],
                            "coef": hac["coef"],
                            "hac_t": hac["hac_t"],
                        }
                    )
    return out, p_rows


def run_sector_diagnostics(df: pd.DataFrame, targets: list[str]) -> dict:
    diagnostics: dict = {}
    for target in targets:
        diagnostics[target] = {}
        control_cols = [f"{target}_log_rv21_lag1", "SPY_log_rv21_lag1", "VIX_level_lag1", "credit_stress_lag1"]
        controls = df[[c for c in control_cols if c in df.columns]].copy()
        controls.columns = [c.replace(f"{target}_", "own_").replace("SPY_", "market_") for c in controls.columns]
        score = df.get(f"{target}_legacy_score")
        if score is None:
            continue
        for horizon in HORIZONS:
            hkey = f"{horizon}d"
            diagnostics[target][hkey] = {}
            for sig in ["transition_shock", "transition_credit_stress"]:
                x = (df[f"{sig}_lag1"] * score).rename(f"{sig}_x_legacy")
                y = df[f"{target}_fwd_log_rv_{horizon}d"]
                diagnostics[target][hkey][sig] = ols_hac(y, x, horizon=horizon, controls=controls)
    return diagnostics


def assess_verdict(primary: dict, mt: dict) -> dict:
    raw_positive = []
    positive_survivors = []
    bonf = set(mt.get("bonferroni_survivors", []))
    holm = set(mt.get("holm_survivors", []))
    for hkey, by_outcome in primary.items():
        for outcome, by_sig in by_outcome.items():
            for sig, res in by_sig.items():
                hac = res["controlled_hac"]
                if "p_value" not in hac:
                    continue
                label = f"HL|{hkey}|{outcome}|{sig}"
                if hac["coef"] > 0 and hac["p_value"] < 0.05:
                    raw_positive.append(label)
                if hac["coef"] > 0 and (label in bonf or label in holm):
                    positive_survivors.append(label)
    if positive_survivors:
        verdict = "MIXED_PROXY_POSITIVE"
        rationale = "At least one high-minus-low positive response survives family correction, but the design remains a public proxy."
    elif raw_positive:
        verdict = "WEAK_RAW_ONLY"
        rationale = "Some high-minus-low responses are raw-significant, but none survives the primary family correction."
    else:
        verdict = "NULL"
        rationale = "No positive high-minus-low response is raw-significant; the public proxy does not support the legacy-overhang RV amplification claim."
    return {
        "verdict": verdict,
        "positive_raw_p_lt_0_05": raw_positive,
        "positive_family_survivors": positive_survivors,
        "rationale": rationale,
    }


def top_primary_rows(primary: dict) -> list[dict]:
    rows = []
    for hkey, by_outcome in primary.items():
        for outcome, by_sig in by_outcome.items():
            for sig, res in by_sig.items():
                hac = res["controlled_hac"]
                if "p_value" not in hac:
                    continue
                rows.append(
                    {
                        "label": f"HL|{hkey}|{outcome}|{sig}",
                        "coef": hac["coef"],
                        "hac_t": hac["hac_t"],
                        "p_value": hac["p_value"],
                        "n": hac["n"],
                        "spearman_rho": res["spearman"].get("rho"),
                        "spearman_ci95": res["spearman"].get("ci95"),
                    }
                )
    return sorted(rows, key=lambda r: r["p_value"])


def make_plots(df: pd.DataFrame, primary: dict) -> None:
    score_cols = [c for c in df.columns if c.endswith("_legacy_score")]
    latest = df[score_cols].ffill().iloc[-1].sort_values()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    labels = [c.replace("_legacy_score", "") for c in latest.index]
    ax.bar(labels, latest.values, color=["tab:red" if v > 0 else "tab:blue" for v in latest.values])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("Latest SEC/XBRL legacy-asset score by ETF proxy")
    ax.set_ylabel("PP&E/assets minus goodwill+intangibles/assets")
    fig.tight_layout()
    fig.savefig(FIG1, dpi=160)
    plt.close(fig)

    plot_df = df.loc[df.index >= "2020-01-01"].copy()
    fig, ax = plt.subplots(figsize=(11, 5))
    for col, color in [("transition_shock", "tab:green"), ("credit_stress", "tab:purple"), ("transition_credit_stress", "tab:red")]:
        ax.plot(plot_df.index, plot_df[col], lw=0.9, alpha=0.8, label=col, color=color)
    ax.axhline(0, color="black", lw=0.7)
    ax.set_title("K1569 transition and credit-stress public-market proxies")
    ax.set_ylabel("z-score style signal")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG2, dpi=160)
    plt.close(fig)

    rows = []
    labels_y = []
    for horizon in HORIZONS:
        for outcome in OUTCOMES:
            rows.append([primary[f"{horizon}d"][outcome][sig]["controlled_hac"].get("hac_t", np.nan) for sig in SIGNALS])
            labels_y.append(f"{horizon}d {outcome}")
    arr = np.asarray(rows, dtype=float)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(np.arange(len(SIGNALS)))
    ax.set_xticklabels(SIGNALS, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(labels_y)))
    ax.set_yticklabels(labels_y)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            txt = "" if not np.isfinite(arr[i, j]) else f"{arr[i, j]:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)
    ax.set_title("Primary HAC t-stat: high-legacy minus low-legacy future outcomes")
    fig.colorbar(im, ax=ax, label="controlled HAC t-stat")
    fig.tight_layout()
    fig.savefig(FIG3, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance/SEC data")
    args = parser.parse_args()

    df, source_meta = build_feature_matrix(refresh=args.refresh)
    score_targets = sorted([c.replace("_legacy_score", "") for c in df.columns if c.endswith("_legacy_score")])
    primary, p_rows = run_primary_tests(df)
    mt = holm_bonferroni(p_rows)
    verdict = assess_verdict(primary, mt)
    diagnostics = run_sector_diagnostics(df, score_targets)
    top_rows = top_primary_rows(primary)
    make_plots(df, primary)

    latest_scores = df[[c for c in df.columns if c.endswith("_legacy_score")]].ffill().iloc[-1].sort_values()
    descriptions = {
        "signals": {c: describe_series(df[c]) for c in SIGNALS + [f"{s}_lag1" for s in SIGNALS] if c in df.columns},
        "high_low_outcomes": {
            f"HL_fwd_{outcome}_{h}d": describe_series(df[f"HL_fwd_{outcome}_{h}d"])
            for h in HORIZONS
            for outcome in OUTCOMES
            if f"HL_fwd_{outcome}_{h}d" in df.columns
        },
        "latest_legacy_scores": {k.replace("_legacy_score", ""): float(v) for k, v in latest_scores.dropna().items()},
    }
    results = {
        "metadata": {
            "experiment_id": "K1569",
            "title": "Legacy-asset overhang public proxy and transition-shock ETF volatility",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "git_commit": git_rev(),
            "verdict": verdict["verdict"],
        },
        "data_sources": source_meta,
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_trading_rows": int(df.shape[0]),
            "sector_targets_with_scores": score_targets,
            "green_automation_etfs": GREEN_AUTOMATION_ETFS,
            "legacy_market_etfs": LEGACY_MARKET_ETFS,
        },
        "methodology": {
            "proxy_limit": (
                "SEC CompanyFacts PP&E/assets minus goodwill+intangibles/assets is a public balance-sheet proxy. "
                "It is not true stranded-asset exposure, asset redeployability, transformation capex, or private credit-spread data."
            ),
            "xbrl_availability": "Annual XBRL facts are usable only after filing date + 1 calendar day, aligned to the first subsequent ETF trading date.",
            "transition_signal": "Green/automation ETF basket shock uses lag-safe z-scores of green-minus-legacy 5d absolute return, green basket absolute 5d return, and green basket 21d RV.",
            "credit_signal": "Credit stress is the negative HYG-LQD 5d return spread, rolling-z scored with a t-1 baseline.",
            "lookahead_policy": "All market signals are signal.shift(1); forward outcomes use strictly [t+1,t+H].",
            "primary_design": "Date-level high legacy score group minus low legacy score group. This avoids stacked sector-day iid inference.",
            "primary_regression": "HL_forward_outcome ~ signal_lag1 + SPY_log_RV21_lag1 + VIX_level_lag1 + credit_stress_lag1, OLS-HAC maxlags=H.",
            "primary_family": f"{len(HORIZONS)} horizons x {len(OUTCOMES)} outcomes x {len(SIGNALS)} signals = {len(HORIZONS) * len(OUTCOMES) * len(SIGNALS)} controlled-HAC tests.",
            "spearman_ci": f"Moving-block bootstrap with block=H, B={BOOTSTRAP_B}, seed={SEED}.",
            "success_gate": "Positive high-minus-low controlled-HAC coefficient must survive Bonferroni/Holm correction.",
        },
        "descriptive": descriptions,
        "primary_tests": primary,
        "top_primary_tests": top_rows,
        "multiple_testing": mt,
        "sector_diagnostics": diagnostics,
        "verdict_assessment": verdict,
        "figures": [str(FIG1.relative_to(HERE)), str(FIG2.relative_to(HERE)), str(FIG3.relative_to(HERE))],
    }
    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "verdict": verdict["verdict"],
                "assessment": verdict,
                "n_tests": mt["n_tests"],
                "top_primary_tests": top_rows[:6],
                "results": str(OUT_JSON),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
