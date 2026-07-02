#!/usr/bin/env python3
"""Anti-stockholder identity public proxy and retail-risk-off volatility.

This is a bounded public-data pilot. The target backlog item asks whether
"not owning stocks" / anti-stockholder identity can be turned into a leading
retail-risk-off volatility proxy. Direct survey identity measures are not
available at daily frequency, and Google Trends / GDELT access was rate-limited
in this environment. This script therefore tests a weaker public-attention
fallback: Wikimedia pageviews for identity-relevant retail/gambling/market
manipulation pages, normalized by broad finance pageviews.

Lookahead policy:
- The primary and secondary attention signals use explicit `.shift(1)`.
- Generic fear attention controls also use `.shift(1)`.
- FINRA margin debt controls are lagged by 22 trading days after monthly
  forward filling, reflecting publication delay conservatism.
- Forecast targets start at t+1 and run through t+h.
- Expanding OOS forecasts embargo train rows whose forward target would not
  yet be observable at the forecast origin.
"""

from __future__ import annotations

import json
import math
import re
import time
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_anti_stockholder_identity_retail_risk_off_volati"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"

SEED = 42
START_DATE = "2020-01-01"
END_DATE = "2026-07-01"
YFINANCE_END_DATE = "2026-07-02"
PAGEVIEW_START = "20200101"
PAGEVIEW_END = "20260701"
ROLL_Z_WINDOW = 126
ROLL_Z_MIN = 42
TRAILING_WINDOW = 22
HORIZONS = [5, 22]
MIN_TRAIN = 504
REFIT_EVERY = 21
EPS = 1e-12
USER_AGENT = "volpred-research/0.1 (research reproducibility script)"

PRIMARY_SIGNAL = "wiki_identity_attention_21d_z_lag1"
SECONDARY_SIGNAL = "wiki_identity_attention_7d_z_lag1"

IDENTITY_PAGES = {
    "WallStreetBets": "retail-speculation identity / online investing community",
    "Meme_stock": "meme-stock identity and stockholder-as-gambler narrative",
    "GameStop_short_squeeze": "retail crowd episode",
    "Short_squeeze": "retail crowd / squeeze attention",
    "Market_manipulation": "rigged-market narrative",
    "Day_trading": "retail speculative trading identity",
    "Robinhood_Markets": "retail brokerage attention",
}

GENERIC_FEAR_PAGES = {
    "Stock_market_crash": "generic equity crash fear",
    "Bear_market": "generic bearish sentiment",
    "Recession": "macro risk-off attention",
    "VIX": "volatility/fear index attention",
    "Financial_crisis": "generic financial-stress attention",
    "Stock_market_bubble": "generic bubble/crash concern",
}

ANCHOR_PAGES = {
    "Stock_market": "broad stock-market pageview denominator",
    "S&P_500": "large-cap equity market pageview denominator",
    "Nasdaq_Composite": "technology equity pageview denominator",
    "Dow_Jones_Industrial_Average": "broad equity index pageview denominator",
    "Investment": "broad investing pageview denominator",
}

TARGET_GROUPS = {
    "retail_meme": [
        "GME",
        "AMC",
        "KOSS",
        "BB",
        "NOK",
        "HOOD",
        "PLTR",
        "SOFI",
        "OPEN",
        "CHWY",
        "DKNG",
        "RIVN",
        "LCID",
    ],
    "arkk": ["ARKK"],
    "iwm": ["IWM"],
    "high_idio": [
        "CVNA",
        "AFRM",
        "UPST",
        "MARA",
        "RIOT",
        "COIN",
        "RBLX",
        "U",
        "AI",
        "SNOW",
        "PTON",
        "BYND",
        "FUBO",
    ],
}

CONTROL_TICKERS = ["SPY", "QQQ", "^VIX"]
FINRA_MARGIN_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"


@dataclass
class StandardizedFit:
    cols: list[str]
    means: pd.Series
    stds: pd.Series
    params: pd.Series


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return value


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def rolling_zscore(series: pd.Series, window: int = ROLL_Z_WINDOW, min_periods: int = ROLL_Z_MIN) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    # At origin t this is sum of observations t+1 through t+h.
    return series.rolling(horizon, min_periods=horizon).sum().shift(-horizon)


def forward_mean(series: pd.Series, horizon: int) -> pd.Series:
    # At origin t this is mean of observations t+1 through t+h.
    return series.rolling(horizon, min_periods=horizon).mean().shift(-horizon)


def fetch_pageviews(article: str) -> tuple[pd.Series, dict[str, object]]:
    cache = DATA_DIR / f"wikimedia_pageviews_{sanitize_filename(article)}.csv"
    meta: dict[str, object] = {
        "article": article,
        "project": "en.wikipedia.org",
        "start": PAGEVIEW_START,
        "end": PAGEVIEW_END,
        "url": (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            f"en.wikipedia.org/all-access/user/{quote(article, safe='')}/daily/{PAGEVIEW_START}/{PAGEVIEW_END}"
        ),
    }
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if {"date", "views"}.issubset(df.columns) and df.shape[0] > 100:
            series = pd.Series(df["views"].to_numpy(float), index=pd.to_datetime(df["date"]), name=article)
            meta.update(
                {
                    "status": "ok_cache",
                    "first_date": series.index.min().date().isoformat(),
                    "last_date": series.index.max().date().isoformat(),
                    "n_obs": int(series.shape[0]),
                    "total_views": float(series.sum()),
                }
            )
            return series, meta

    response = None
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(meta["url"], headers={"User-Agent": USER_AGENT}, timeout=30)
            break
        except requests.RequestException as exc:
            last_error = repr(exc)
            time.sleep(1.5 * (attempt + 1))
    if response is None:
        meta.update({"status": "request_failed", "error": last_error})
        return pd.Series(dtype=float, name=article), meta
    if response.status_code == 404:
        meta.update({"status": "missing_article", "http_status": 404})
        empty = pd.Series(dtype=float, name=article)
        return empty, meta
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        meta.update({"status": "http_failed", "http_status": response.status_code, "error": repr(exc)})
        return pd.Series(dtype=float, name=article), meta
    payload = response.json()
    rows = []
    for item in payload.get("items", []):
        timestamp = str(item.get("timestamp", ""))
        if len(timestamp) < 8:
            continue
        rows.append({"date": pd.to_datetime(timestamp[:8]), "views": float(item.get("views", 0.0))})
    if not rows:
        meta.update({"status": "empty_response", "http_status": response.status_code})
        return pd.Series(dtype=float, name=article), meta
    df = pd.DataFrame(rows).sort_values("date")
    df.to_csv(cache, index=False)
    series = pd.Series(df["views"].to_numpy(float), index=pd.to_datetime(df["date"]), name=article)
    meta.update(
        {
            "status": "ok_download",
            "first_date": series.index.min().date().isoformat(),
            "last_date": series.index.max().date().isoformat(),
            "n_obs": int(series.shape[0]),
            "total_views": float(series.sum()),
        }
    )
    time.sleep(0.15)
    return series, meta


def build_pageview_signals(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, object]]:
    daily_index = pd.date_range(START_DATE, END_DATE, freq="D")
    groups = {
        "identity_pages": IDENTITY_PAGES,
        "generic_fear_pages": GENERIC_FEAR_PAGES,
        "anchor_pages": ANCHOR_PAGES,
    }
    source_meta: dict[str, object] = {}
    group_frames: dict[str, pd.DataFrame] = {}
    for group_name, pages in groups.items():
        series_map: dict[str, pd.Series] = {}
        group_meta: dict[str, object] = {}
        for article, role in pages.items():
            series, meta = fetch_pageviews(article)
            group_meta[article] = {"role": role, **meta}
            if not series.empty:
                series_map[article] = series.reindex(daily_index).fillna(0.0)
        source_meta[group_name] = group_meta
        if series_map:
            group_frames[group_name] = pd.DataFrame(series_map).reindex(daily_index).fillna(0.0)
        else:
            group_frames[group_name] = pd.DataFrame(index=daily_index)

    identity_views = group_frames["identity_pages"].sum(axis=1, min_count=1).fillna(0.0)
    fear_views = group_frames["generic_fear_pages"].sum(axis=1, min_count=1).fillna(0.0)
    anchor_views = group_frames["anchor_pages"].sum(axis=1, min_count=1).replace(0.0, np.nan)

    identity_rel_7d = np.log1p(identity_views.rolling(7, min_periods=3).sum()) - np.log1p(
        anchor_views.rolling(7, min_periods=3).sum()
    )
    identity_rel_21d = np.log1p(identity_views.rolling(21, min_periods=7).sum()) - np.log1p(
        anchor_views.rolling(21, min_periods=7).sum()
    )
    fear_rel_7d = np.log1p(fear_views.rolling(7, min_periods=3).sum()) - np.log1p(
        anchor_views.rolling(7, min_periods=3).sum()
    )
    fear_rel_21d = np.log1p(fear_views.rolling(21, min_periods=7).sum()) - np.log1p(
        anchor_views.rolling(21, min_periods=7).sum()
    )

    out = pd.DataFrame(index=daily_index)
    out["wiki_identity_views"] = identity_views
    out["wiki_generic_fear_views"] = fear_views
    out["wiki_anchor_views"] = anchor_views
    out["wiki_identity_logrel_21d"] = identity_rel_21d
    out["wiki_generic_fear_logrel_21d"] = fear_rel_21d
    # HARD lookahead guard: predictor at t is last available signal from t-1.
    out["wiki_identity_attention_7d_z_lag1"] = rolling_zscore(identity_rel_7d).shift(1)
    out["wiki_identity_attention_21d_z_lag1"] = rolling_zscore(identity_rel_21d).shift(1)
    out["wiki_generic_fear_attention_7d_z_lag1"] = rolling_zscore(fear_rel_7d).shift(1)
    out["wiki_generic_fear_attention_21d_z_lag1"] = rolling_zscore(fear_rel_21d).shift(1)
    out = out.reindex(calendar, method="ffill")
    out.index.name = "date"
    out.to_csv(DATA_DIR / "wikimedia_attention_panel.csv")
    return out, source_meta


def download_finra_margin_xlsx() -> bytes:
    cache = DATA_DIR / "finra_margin_statistics.xlsx"
    if cache.exists() and cache.stat().st_size > 10_000:
        return cache.read_bytes()
    response = requests.get(FINRA_MARGIN_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    cache.write_bytes(response.content)
    return response.content


def xlsx_rows_from_sheet(xlsx_bytes: bytes) -> list[list[str | None]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(DATA_DIR / "finra_margin_statistics.xlsx") as workbook:
        root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str | None]] = []
    for row in root.findall(".//a:sheetData/a:row", ns):
        values: dict[int, str | None] = {}
        for cell in row.findall("a:c", ns):
            ref = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", ref)
            if not match:
                continue
            col_letters = match.group(1)
            col_idx = 0
            for char in col_letters:
                col_idx = col_idx * 26 + (ord(char) - ord("A") + 1)
            col_idx -= 1
            texts = [node.text or "" for node in cell.findall(".//a:t", ns)]
            if texts:
                value = "".join(texts)
            else:
                value_node = cell.find("a:v", ns)
                value = value_node.text if value_node is not None else None
            values[col_idx] = value
        if values:
            max_col = max(values)
            rows.append([values.get(i) for i in range(max_col + 1)])
    return rows


def build_finra_controls(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, object]]:
    xlsx_bytes = download_finra_margin_xlsx()
    rows = xlsx_rows_from_sheet(xlsx_bytes)
    if len(rows) < 10:
        raise RuntimeError("FINRA margin xlsx did not contain enough rows")
    header = rows[0]
    records = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        year_month = str(row[0])
        if not re.match(r"\d{4}-\d{2}", year_month):
            continue
        padded = row + [None] * (4 - len(row))
        records.append(
            {
                "date": pd.to_datetime(year_month + "-01") + pd.offsets.MonthEnd(0),
                "debit_balances_margin_millions": pd.to_numeric(padded[1], errors="coerce"),
                "free_credit_cash_millions": pd.to_numeric(padded[2], errors="coerce"),
                "free_credit_margin_millions": pd.to_numeric(padded[3], errors="coerce"),
            }
        )
    monthly = pd.DataFrame(records).dropna(subset=["debit_balances_margin_millions"]).sort_values("date")
    monthly.to_csv(DATA_DIR / "finra_margin_statistics.csv", index=False)
    monthly = monthly.set_index("date")
    monthly["margin_debt_yoy"] = np.log(monthly["debit_balances_margin_millions"]).diff(12)
    monthly["margin_debt_mom"] = np.log(monthly["debit_balances_margin_millions"]).diff(1)
    daily = monthly.reindex(calendar.union(monthly.index)).sort_index().ffill().reindex(calendar)
    out = pd.DataFrame(index=calendar)
    out["finra_margin_debt_yoy_z_lag22"] = rolling_zscore(daily["margin_debt_yoy"]).shift(22)
    out["finra_margin_debt_mom_z_lag22"] = rolling_zscore(daily["margin_debt_mom"]).shift(22)
    out.index.name = "date"
    out.to_csv(DATA_DIR / "finra_margin_controls.csv")
    meta = {
        "url": FINRA_MARGIN_URL,
        "status": "ok",
        "parser": "stdlib_zip_xml_no_openpyxl",
        "columns": header,
        "first_month": monthly.index.min().date().isoformat(),
        "last_month": monthly.index.max().date().isoformat(),
        "n_months": int(monthly.shape[0]),
        "lookahead_guard": "monthly values forward-filled to trading days then shifted 22 trading days",
    }
    return out, meta


def extract_symbol_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw.empty:
        raise ValueError("empty yfinance download")
    data = raw.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if symbol in data.columns.get_level_values(0):
            data = data[symbol]
        elif symbol in data.columns.get_level_values(-1):
            data = data.xs(symbol, axis=1, level=-1)
        else:
            raise ValueError(f"{symbol} not found in multi-index columns")
    needed = ["Close", "High", "Low", "Volume"]
    missing = [col for col in needed if col not in data.columns]
    if missing:
        raise ValueError(f"{symbol} missing yfinance columns {missing}")
    out = data.copy()
    if "Adj Close" not in out.columns:
        out["Adj Close"] = out["Close"]
    out = out[["Adj Close", "Close", "High", "Low", "Volume"]].copy()
    out = out.dropna(subset=["Close"])
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")]
    return out.sort_index()


def download_yfinance_ohlcv(symbols: Iterable[str]) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    symbols = list(dict.fromkeys(symbols))
    cache = DATA_DIR / "yfinance_ohlcv_panel.csv"
    meta: dict[str, object] = {"symbols_requested": symbols, "status": "download"}
    if cache.exists():
        cached = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        frames = {}
        for symbol in symbols:
            if symbol in cached.columns.get_level_values(0):
                frame = cached[symbol].copy()
                if frame.shape[0] > 100 and "Close" in frame.columns:
                    frames[symbol] = frame
        if len(frames) >= 4:
            meta.update({"status": "ok_cache", "usable_symbols": sorted(frames)})
            return frames, meta

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        raw = yf.download(
            symbols,
            start=START_DATE,
            end=YFINANCE_END_DATE,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="ticker",
            timeout=30,
        )
    frames = {}
    errors = {}
    for symbol in symbols:
        try:
            frames[symbol] = extract_symbol_frame(raw, symbol)
        except Exception as exc:
            errors[symbol] = repr(exc)
    if not frames:
        raise RuntimeError(f"yfinance returned no usable symbols; errors={errors}")
    panel = pd.concat(frames, axis=1)
    panel.to_csv(cache)
    meta.update(
        {
            "usable_symbols": sorted(frames),
            "errors": errors,
            "first_date": min(frame.index.min() for frame in frames.values()).date().isoformat(),
            "last_date": max(frame.index.max() for frame in frames.values()).date().isoformat(),
        }
    )
    return frames, meta


def build_market_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close = pd.concat({sym: df["Adj Close"].astype(float) for sym, df in frames.items()}, axis=1).sort_index()
    raw_close = pd.concat({sym: df["Close"].astype(float) for sym, df in frames.items()}, axis=1).reindex(close.index)
    high = pd.concat({sym: df["High"].astype(float) for sym, df in frames.items()}, axis=1).reindex(close.index)
    low = pd.concat({sym: df["Low"].astype(float) for sym, df in frames.items()}, axis=1).reindex(close.index)
    volume = pd.concat({sym: df["Volume"].astype(float) for sym, df in frames.items()}, axis=1).reindex(close.index)
    adj_factor = (close / raw_close).replace([np.inf, -np.inf], np.nan)
    return {
        "close": close,
        "high": high * adj_factor,
        "low": low * adj_factor,
        "volume": volume,
    }


def build_group_daily_series(
    group_name: str,
    symbols: list[str],
    market: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, object]]:
    available = [symbol for symbol in symbols if symbol in market["close"].columns]
    if not available:
        raise RuntimeError(f"no yfinance symbols available for {group_name}")
    close = market["close"][available]
    volume = market["volume"][available].reindex(close.index)
    returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)
    dollar_volume = (close * volume).replace([np.inf, -np.inf], np.nan)
    min_components = 1 if len(available) == 1 else min(4, len(available))
    component_count = returns.notna().sum(axis=1)
    group_ret = returns.mean(axis=1, skipna=True)
    group_ret = group_ret.where(component_count >= min_components)
    group_dollar_volume = dollar_volume.sum(axis=1, min_count=min_components)
    out = pd.DataFrame(index=close.index)
    out[f"{group_name}_ret"] = group_ret
    out[f"{group_name}_rv_daily"] = group_ret.pow(2)
    out[f"{group_name}_downside_daily"] = group_ret.clip(upper=0.0).pow(2)
    out[f"{group_name}_log_dollar_volume"] = np.log(group_dollar_volume.replace(0.0, np.nan))
    out[f"{group_name}_component_count"] = component_count
    meta = {
        "requested_symbols": symbols,
        "available_symbols": available,
        "min_components": min_components,
        "first_valid_date": group_ret.dropna().index.min().date().isoformat() if group_ret.notna().any() else None,
        "last_valid_date": group_ret.dropna().index.max().date().isoformat() if group_ret.notna().any() else None,
    }
    return out, meta


def build_analysis_panel(market: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, object]]:
    close = market["close"]
    calendar = close.index[(close.index >= pd.Timestamp(START_DATE)) & (close.index <= pd.Timestamp(END_DATE))]
    calendar = pd.DatetimeIndex(calendar).sort_values()

    pageview_signals, pageview_meta = build_pageview_signals(calendar)
    finra_controls, finra_meta = build_finra_controls(calendar)

    group_meta: dict[str, object] = {}
    group_frames = []
    for group_name, symbols in TARGET_GROUPS.items():
        frame, meta = build_group_daily_series(group_name, symbols, market)
        group_meta[group_name] = meta
        group_frames.append(frame.reindex(calendar))

    panel = pd.concat(group_frames, axis=1).reindex(calendar)
    panel = panel.join(pageview_signals, how="left")
    panel = panel.join(finra_controls, how="left")

    if "^VIX" in close.columns:
        panel["vix_log_lag1"] = np.log(close["^VIX"].reindex(calendar)).shift(1)
    if "SPY" in close.columns:
        spy_close = close["SPY"].reindex(calendar)
        spy_ret = np.log(spy_close / spy_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        panel["spy_ret_5d_lag1"] = spy_ret.rolling(5, min_periods=5).sum().shift(1)
        panel["spy_ret_22d_lag1"] = spy_ret.rolling(22, min_periods=22).sum().shift(1)
        panel["spy_log_rv22_lag1"] = np.log(spy_ret.pow(2).rolling(22, min_periods=22).sum().shift(1) + EPS)
    if "QQQ" in close.columns:
        qqq_close = close["QQQ"].reindex(calendar)
        qqq_ret = np.log(qqq_close / qqq_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        panel["qqq_ret_22d_lag1"] = qqq_ret.rolling(22, min_periods=22).sum().shift(1)

    for group_name in TARGET_GROUPS:
        ret = panel[f"{group_name}_ret"]
        rv_daily = panel[f"{group_name}_rv_daily"]
        downside_daily = panel[f"{group_name}_downside_daily"]
        log_dv = panel[f"{group_name}_log_dollar_volume"]
        panel[f"{group_name}_ret_5d_lag1"] = ret.rolling(5, min_periods=5).sum().shift(1)
        panel[f"{group_name}_ret_22d_lag1"] = ret.rolling(22, min_periods=22).sum().shift(1)
        panel[f"{group_name}_lag_log_rv22"] = np.log(
            rv_daily.rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum().shift(1) + EPS
        )
        panel[f"{group_name}_lag_log_downside22"] = np.log(
            downside_daily.rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum().shift(1) + EPS
        )
        panel[f"{group_name}_lag_log_dollar_volume22"] = log_dv.rolling(
            TRAILING_WINDOW, min_periods=TRAILING_WINDOW
        ).mean().shift(1)
        for horizon in HORIZONS:
            panel[f"future_log_rv__{group_name}__{horizon}d"] = np.log(forward_sum(rv_daily, horizon) + EPS)
            panel[f"future_log_downside__{group_name}__{horizon}d"] = np.log(
                forward_sum(downside_daily, horizon) + EPS
            )
            panel[f"future_volume_crash__{group_name}__{horizon}d"] = (
                panel[f"{group_name}_lag_log_dollar_volume22"] - forward_mean(log_dv, horizon)
            )

    panel.index.name = "date"
    panel.to_csv(DATA_DIR / "analysis_panel.csv")
    meta = {
        "pageviews": pageview_meta,
        "finra_margin": finra_meta,
        "target_groups": group_meta,
        "calendar_start": calendar.min().date().isoformat(),
        "calendar_end": calendar.max().date().isoformat(),
    }
    return panel, meta


def target_specs() -> list[tuple[str, str, int, str]]:
    specs: list[tuple[str, str, int, str]] = []
    for group_name in TARGET_GROUPS:
        for horizon in HORIZONS:
            specs.append((f"future_log_rv__{group_name}__{horizon}d", group_name, horizon, "rv"))
            specs.append((f"future_log_downside__{group_name}__{horizon}d", group_name, horizon, "downside"))
            specs.append((f"future_volume_crash__{group_name}__{horizon}d", group_name, horizon, "volume_crash"))
    return specs


def available_controls(panel: pd.DataFrame, group_name: str, family: str) -> list[str]:
    family_control = {
        "rv": f"{group_name}_lag_log_rv22",
        "downside": f"{group_name}_lag_log_downside22",
        "volume_crash": f"{group_name}_lag_log_dollar_volume22",
    }[family]
    controls = [
        family_control,
        f"{group_name}_ret_5d_lag1",
        f"{group_name}_ret_22d_lag1",
        "wiki_generic_fear_attention_21d_z_lag1",
        "vix_log_lag1",
        "spy_ret_5d_lag1",
        "spy_ret_22d_lag1",
        "spy_log_rv22_lag1",
        "qqq_ret_22d_lag1",
        "finra_margin_debt_yoy_z_lag22",
    ]
    return [col for col in controls if col in panel.columns]


def fit_hac_regression(
    data: pd.DataFrame,
    y_col: str,
    signal_col: str,
    controls: list[str],
    horizon: int,
) -> dict[str, object]:
    cols = [signal_col] + controls
    reg = data[[y_col] + cols].replace([np.inf, -np.inf], np.nan).dropna()
    if reg.shape[0] < 180:
        return {"status": "insufficient_data", "n": int(reg.shape[0])}
    x_raw = reg[cols].copy()
    means = x_raw.mean()
    stds = x_raw.std(ddof=0).replace(0.0, np.nan)
    x = (x_raw - means) / stds
    x = sm.add_constant(x, has_constant="add")
    model = sm.OLS(reg[y_col], x).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "status": "ok",
        "n": int(reg.shape[0]),
        "sample_start": reg.index.min().date().isoformat(),
        "sample_end": reg.index.max().date().isoformat(),
        "controls": controls,
        "coef": float(model.params[signal_col]),
        "t": float(model.tvalues[signal_col]),
        "p": float(model.pvalues[signal_col]),
        "r2": float(model.rsquared),
        "hac_maxlags": horizon,
    }


def fit_standardized(train: pd.DataFrame, y_col: str, cols: list[str]) -> StandardizedFit | None:
    clean = train[[y_col] + cols].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.shape[0] < MIN_TRAIN:
        return None
    means = clean[cols].mean()
    stds = clean[cols].std(ddof=0).replace(0.0, np.nan)
    if stds.isna().any():
        return None
    x = (clean[cols] - means) / stds
    x = sm.add_constant(x, has_constant="add")
    model = sm.OLS(clean[y_col], x).fit()
    return StandardizedFit(cols=cols, means=means, stds=stds, params=model.params)


def predict_standardized(fit: StandardizedFit, row: pd.Series) -> float | None:
    values = row[fit.cols].replace([np.inf, -np.inf], np.nan)
    if values.isna().any():
        return None
    x = (values - fit.means) / fit.stds
    x = pd.concat([pd.Series({"const": 1.0}), x])
    return float(np.dot(x[fit.params.index].to_numpy(float), fit.params.to_numpy(float)))


def expanding_oos(
    data: pd.DataFrame,
    y_col: str,
    signal_col: str,
    controls: list[str],
    horizon: int,
) -> dict[str, object]:
    cols_base = controls
    cols_aug = [signal_col] + controls
    clean = data[[y_col] + cols_aug].replace([np.inf, -np.inf], np.nan).copy()
    preds: list[dict[str, object]] = []
    base_fit: StandardizedFit | None = None
    aug_fit: StandardizedFit | None = None
    last_refit = -10**9
    for pos in range(MIN_TRAIN + horizon + 1, clean.shape[0]):
        row = clean.iloc[pos]
        if row[[y_col] + cols_aug].isna().any():
            continue
        # Embargo: target for train row j uses j+1..j+h. At forecast origin i,
        # only rows ending strictly before i enter training.
        train_end = pos - horizon
        if train_end < MIN_TRAIN:
            continue
        if base_fit is None or pos - last_refit >= REFIT_EVERY:
            train = clean.iloc[:train_end]
            base_fit = fit_standardized(train, y_col, cols_base)
            aug_fit = fit_standardized(train, y_col, cols_aug)
            last_refit = pos
        if base_fit is None or aug_fit is None:
            continue
        pred_base = predict_standardized(base_fit, row)
        pred_aug = predict_standardized(aug_fit, row)
        if pred_base is None or pred_aug is None:
            continue
        y = float(row[y_col])
        preds.append(
            {
                "date": clean.index[pos],
                "y": y,
                "pred_base": pred_base,
                "pred_aug": pred_aug,
                "base_loss": (y - pred_base) ** 2,
                "aug_loss": (y - pred_aug) ** 2,
            }
        )
    if len(preds) < 80:
        return {"status": "insufficient_oos", "n": len(preds)}
    pred_df = pd.DataFrame(preds).set_index("date")
    pred_df.to_csv(DATA_DIR / f"oos_{sanitize_filename(y_col)}.csv")
    loss_diff = pred_df["base_loss"] - pred_df["aug_loss"]
    dm_model = sm.OLS(loss_diff, np.ones((len(loss_diff), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": horizon}
    )
    base_mean = float(pred_df["base_loss"].mean())
    aug_mean = float(pred_df["aug_loss"].mean())
    return {
        "status": "ok",
        "n": int(pred_df.shape[0]),
        "sample_start": pred_df.index.min().date().isoformat(),
        "sample_end": pred_df.index.max().date().isoformat(),
        "base_mse": base_mean,
        "aug_mse": aug_mean,
        "mse_improvement_pct": float(100.0 * (1.0 - aug_mean / base_mean)) if base_mean > 0 else None,
        "dm_lossdiff_t": float(dm_model.tvalues.iloc[0]),
        "dm_lossdiff_p": float(dm_model.pvalues.iloc[0]),
        "lossdiff_definition": "base squared-error loss minus augmented squared-error loss; positive means identity proxy improves",
        "train_embargo_rows": horizon,
        "refit_every": REFIT_EVERY,
    }


def holm_adjust(pairs: list[tuple[str, float]]) -> dict[str, float]:
    valid = [(key, p) for key, p in pairs if p is not None and not math.isnan(float(p))]
    m = len(valid)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(sorted(valid, key=lambda item: item[1]), start=1):
        adj = min(1.0, float(p) * (m - rank + 1))
        running = max(running, adj)
        adjusted[key] = running
    return adjusted


def shock_contrast(panel: pd.DataFrame, y_col: str, signal_col: str) -> dict[str, object]:
    data = panel[[y_col, signal_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if data.shape[0] < 180:
        return {"status": "insufficient_data", "n": int(data.shape[0])}
    threshold = float(data[signal_col].quantile(0.90))
    high = data.loc[data[signal_col] >= threshold, y_col]
    rest = data.loc[data[signal_col] < threshold, y_col]
    if high.shape[0] < 20 or rest.shape[0] < 20:
        return {"status": "insufficient_shock_rows", "n_high": int(high.shape[0]), "n_rest": int(rest.shape[0])}
    stacked = pd.concat([high, rest])
    indicator = pd.Series([1] * len(high) + [0] * len(rest), index=list(high.index) + list(rest.index), name="top_decile")
    model = sm.OLS(stacked, sm.add_constant(indicator)).fit(cov_type="HAC", cov_kwds={"maxlags": 22})
    return {
        "status": "ok",
        "threshold": threshold,
        "n_high": int(high.shape[0]),
        "n_rest": int(rest.shape[0]),
        "high_mean": float(high.mean()),
        "rest_mean": float(rest.mean()),
        "diff_high_minus_rest": float(high.mean() - rest.mean()),
        "hac_t": float(model.tvalues["top_decile"]),
        "hac_p": float(model.pvalues["top_decile"]),
        "note": "descriptive top-decile contrast; overlapping windows are HAC-adjusted but not causal",
    }


def run_tests(panel: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    results: dict[str, object] = {
        "primary_signal": PRIMARY_SIGNAL,
        "secondary_signal": SECONDARY_SIGNAL,
        "primary_hac": {},
        "secondary_hac": {},
        "oos": {},
        "shock_contrasts": {},
    }
    rows: list[dict[str, object]] = []
    pvals: list[tuple[str, float]] = []
    for y_col, group_name, horizon, family in target_specs():
        controls = available_controls(panel, group_name, family)
        key = f"{y_col}__{PRIMARY_SIGNAL}"
        hac = fit_hac_regression(panel, y_col, PRIMARY_SIGNAL, controls, horizon)
        secondary = fit_hac_regression(panel, y_col, SECONDARY_SIGNAL, controls, horizon)
        oos = expanding_oos(panel, y_col, PRIMARY_SIGNAL, controls, horizon)
        contrast = shock_contrast(panel, y_col, PRIMARY_SIGNAL)
        results["primary_hac"][y_col] = hac
        results["secondary_hac"][y_col] = secondary
        results["oos"][y_col] = oos
        results["shock_contrasts"][y_col] = contrast
        if hac.get("status") == "ok":
            pvals.append((y_col, float(hac["p"])))
        rows.append(
            {
                "target": y_col,
                "group": group_name,
                "horizon": horizon,
                "family": family,
                "primary_coef": hac.get("coef"),
                "primary_t": hac.get("t"),
                "primary_p": hac.get("p"),
                "oos_mse_improvement_pct": oos.get("mse_improvement_pct"),
                "oos_dm_t": oos.get("dm_lossdiff_t"),
                "oos_dm_p": oos.get("dm_lossdiff_p"),
                "n_hac": hac.get("n"),
                "n_oos": oos.get("n"),
                "controls": ",".join(controls),
                "key": key,
            }
        )
    holm = holm_adjust(pvals)
    for row in rows:
        row["primary_holm_p"] = holm.get(row["target"])
        if row["target"] in results["primary_hac"]:
            results["primary_hac"][row["target"]]["holm_p"] = holm.get(row["target"])
    summary = pd.DataFrame(rows)
    summary.to_csv(DATA_DIR / "summary_table.csv", index=False)
    results["summary_table_path"] = str(DATA_DIR / "summary_table.csv")
    return results, summary


def make_figures(panel: pd.DataFrame, summary: pd.DataFrame) -> list[str]:
    paths: list[str] = []

    fig, axes = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True)
    panel["wiki_identity_views"].rolling(21, min_periods=7).sum().plot(ax=axes[0], color="#4c78a8", linewidth=1.4)
    axes[0].set_title("Wikimedia identity-relevant attention pages, 21-day views")
    axes[0].set_ylabel("views")
    axes[0].grid(alpha=0.25)
    panel["wiki_generic_fear_views"].rolling(21, min_periods=7).sum().plot(
        ax=axes[1], color="#f58518", linewidth=1.4
    )
    axes[1].set_title("Wikimedia generic bearish/fear pages, 21-day views")
    axes[1].set_ylabel("views")
    axes[1].grid(alpha=0.25)
    panel[PRIMARY_SIGNAL].plot(ax=axes[2], color="#54a24b", linewidth=1.2)
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_title("Lagged normalized identity-attention z-score")
    axes[2].set_ylabel("z")
    axes[2].grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "wikimedia_attention_signal.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 6.8))
    plot_df = summary.copy()
    plot_df["label"] = plot_df["group"] + " " + plot_df["family"] + " " + plot_df["horizon"].astype(str) + "d"
    plot_df = plot_df.sort_values("primary_t", na_position="last")
    axes[0].barh(plot_df["label"], plot_df["primary_t"], color="#4c78a8")
    axes[0].axvline(3, color="#d62728", linestyle="--", linewidth=1.0)
    axes[0].axvline(-3, color="#d62728", linestyle="--", linewidth=1.0)
    axes[0].set_title("Primary HAC t-stat")
    axes[0].set_xlabel("t")
    axes[0].grid(axis="x", alpha=0.25)

    axes[1].barh(plot_df["label"], plot_df["oos_mse_improvement_pct"], color="#59a14f")
    axes[1].axvline(0, color="black", linewidth=0.8)
    axes[1].set_title("Expanding OOS MSE improvement")
    axes[1].set_xlabel("%, augmented vs baseline")
    axes[1].grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "primary_test_diagnostics.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    return paths


def decide_verdict(summary: pd.DataFrame) -> tuple[str, list[str], list[str], list[str]]:
    robust_passes: list[str] = []
    weak_raw_positive: list[str] = []
    raw_negative: list[str] = []
    for _, row in summary.iterrows():
        coef = row.get("primary_coef")
        t_value = row.get("primary_t")
        holm_p = row.get("primary_holm_p")
        oos_t = row.get("oos_dm_t")
        oos_improvement = row.get("oos_mse_improvement_pct")
        if pd.isna(coef) or pd.isna(t_value):
            continue
        target = str(row["target"])
        if float(coef) > 0 and float(t_value) >= 3.0:
            if pd.notna(holm_p) and float(holm_p) < 0.05:
                if pd.notna(oos_t) and pd.notna(oos_improvement):
                    if float(oos_t) >= 3.0 and float(oos_improvement) > 0:
                        robust_passes.append(target)
        if float(coef) > 0 and float(t_value) >= 2.0:
            weak_raw_positive.append(target)
        if float(coef) < 0 and float(t_value) <= -2.0:
            raw_negative.append(target)
    if robust_passes:
        verdict = "PASS_PUBLIC_PROXY_SIGNAL"
    elif weak_raw_positive:
        verdict = "WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS"
    elif raw_negative:
        verdict = "NEGATIVE_OR_REACTIVE_PUBLIC_PROXY_SIGNAL"
    else:
        verdict = "NULL_NO_ROBUST_PUBLIC_PROXY_SIGNAL"
    return verdict, robust_passes, weak_raw_positive, raw_negative


def make_knowledge_candidate(results: dict[str, object]) -> dict[str, object]:
    return {
        "candidate_only": True,
        "not_written_to_storage_memory_knowledge_json": True,
        "reason": "Codex failover experiment completed artifacts; canonical knowledge write is deferred to Claude/K1259 gate.",
        "experiment_id": EXPERIMENT_ID,
        "date": results["run_timestamp_utc"][:10],
        "claim": "Wikimedia identity-relevant public-attention fallback does not provide a robust leading retail-risk-off volatility signal.",
        "evidence": {
            "verdict": results["verdict"],
            "sample": results["sample"],
            "best_cells": results["diagnostics"]["top_positive_hac_cells"],
        },
        "limitations": results["limitations"],
    }


def main() -> dict[str, object]:
    ensure_dirs()
    np.random.seed(SEED)
    symbols = sorted(set(sum(TARGET_GROUPS.values(), []) + CONTROL_TICKERS))
    frames, yf_meta = download_yfinance_ohlcv(symbols)
    market = build_market_frames(frames)
    panel, source_meta = build_analysis_panel(market)
    tests, summary = run_tests(panel)
    figure_paths = make_figures(panel, summary)
    verdict, robust_passes, weak_raw_positive, raw_negative = decide_verdict(summary)

    top_positive = (
        summary.sort_values("primary_t", ascending=False)
        .head(5)[
            [
                "target",
                "primary_coef",
                "primary_t",
                "primary_p",
                "primary_holm_p",
                "oos_mse_improvement_pct",
                "oos_dm_t",
            ]
        ]
        .to_dict(orient="records")
    )
    top_oos = (
        summary.sort_values("oos_mse_improvement_pct", ascending=False)
        .head(5)[
            [
                "target",
                "primary_coef",
                "primary_t",
                "primary_holm_p",
                "oos_mse_improvement_pct",
                "oos_dm_t",
            ]
        ]
        .to_dict(orient="records")
    )

    results: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Anti-stockholder identity public proxy and retail-risk-off volatility",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "seed": SEED,
        "verdict": verdict,
        "sample": {
            "start": panel.index.min().date().isoformat(),
            "end": panel.index.max().date().isoformat(),
            "n_trading_days": int(panel.shape[0]),
            "n_targets": int(summary.shape[0]),
        },
        "data_sources": {
            "wikimedia_pageviews": source_meta["pageviews"],
            "finra_margin_statistics": source_meta["finra_margin"],
            "yfinance": yf_meta,
            "google_trends": {
                "status": "not_used_runtime_unavailable",
                "note": "Local pytrends probe returned Google 429 during pilot setup; no Google Trends data were used.",
            },
            "gdelt_doc": {
                "status": "not_used_runtime_rate_limited",
                "note": "GDELT DOC probe returned public endpoint rate-limit text during pilot setup; no GDELT data were used.",
            },
        },
        "method": {
            "target_groups": TARGET_GROUPS,
            "primary_signal": PRIMARY_SIGNAL,
            "secondary_signal": SECONDARY_SIGNAL,
            "target_families": [
                "future log realized variance",
                "future log downside semivariance",
                "future log dollar-volume crash proxy",
            ],
            "horizons": HORIZONS,
            "controls": [
                "own target-family trailing measure",
                "own recent group returns",
                "generic bearish/fear pageview attention",
                "VIX level",
                "SPY recent returns and realized variance",
                "QQQ recent return",
                "FINRA margin debt YoY growth lagged 22 trading days",
            ],
            "lookahead_guards": [
                "identity attention signals use .shift(1)",
                "generic fear attention controls use .shift(1)",
                "FINRA monthly margin controls use .shift(22) after forward fill",
                "targets are t+1..t+h",
                "OOS expanding forecasts embargo train rows by horizon",
            ],
            "statistical_gate": "positive coefficient + HAC t>=3 + Holm p<0.05 across all target cells + positive OOS MSE improvement with DM t>=3",
        },
        "tests": tests,
        "summary_table": to_jsonable(summary.to_dict(orient="records")),
        "diagnostics": {
            "robust_passes": robust_passes,
            "weak_raw_positive_cells": weak_raw_positive,
            "raw_negative_cells": raw_negative,
            "top_positive_hac_cells": to_jsonable(top_positive),
            "top_oos_improvement_cells": to_jsonable(top_oos),
        },
        "figures": figure_paths,
        "limitations": [
            "Wikimedia pageviews are a weak public-attention fallback, not a direct measure of anti-stockholder identity or non-participation attitudes.",
            "Google Trends and GDELT phrase proxies were not used because access probes were rate-limited in this run environment.",
            "FINRA margin debt is monthly, broad, and lagged; it anchors retail leverage context but cannot identify high-frequency household risk-budget shocks.",
            "Daily OHLCV targets cannot observe retail order imbalance, broker-specific flow, or options activity.",
            "The experiment is diagnostic for public proxy usefulness only; it is not a causal test of identity formation or household non-participation.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(to_jsonable(results), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (EXP_DIR / "knowledge_candidate.json").write_text(
        json.dumps(to_jsonable(make_knowledge_candidate(results)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            to_jsonable(
                {
                    "verdict": verdict,
                    "sample": results["sample"],
                    "robust_passes": robust_passes,
                    "weak_raw_positive_cells": weak_raw_positive[:5],
                    "top_positive_hac_cells": top_positive[:3],
                }
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
    return results


if __name__ == "__main__":
    main()
