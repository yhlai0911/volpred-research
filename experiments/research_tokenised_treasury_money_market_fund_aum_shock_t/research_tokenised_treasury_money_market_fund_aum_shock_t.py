#!/usr/bin/env python3
"""Tokenised Treasury/MMF AUM shock and short-end Treasury ETF liquidity-vol.

This is a bounded public-data pilot. It uses DefiLlama protocol TVL for
tokenised Treasury / money-market-fund-like RWA wrappers, yfinance OHLCV for
short-end Treasury ETFs, and FRED for SOFR/IORB plus retail money-market fund
assets.

Lookahead policy:
- Tokenised AUM growth signals are explicitly shifted one ETF trading day:
  `signal.shift(1)`.
- Traditional MMF AUM control uses an even more conservative five-trading-day
  shift after daily forward filling of the weekly FRED series.
- Forecast targets start at t+1 and run through t+h.
- Expanding OOS forecasts embargo train rows whose forward target would not
  yet be observed at the forecast origin.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_tokenised_treasury_money_market_fund_aum_shock_t"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"

SEED = 42
START_DATE = "2023-01-01"
MIN_TOKENISED_TVL_USD = 100_000_000
ROLL_Z_WINDOW = 126
ROLL_Z_MIN = 42
TRAILING_WINDOW = 22
HORIZONS = [5, 22]
REFIT_EVERY = 21
MIN_TRAIN = 252
EPS = 1e-12

TARGET_ETFS = ["BIL", "SHV", "SGOV", "USFR", "TFLO"]
CONTROL_TICKERS = ["SPY", "TLT", "^VIX", "BTC-USD", "ETH-USD"]

TOKENISED_TREASURY_SLUGS = {
    "blackrock-buidl": "BlackRock BUIDL",
    "circle-usyc": "Circle USYC / Hashnote USYC",
    "ondo-yield-assets": "Ondo Yield Assets",
    "invesco-ustb": "Invesco / Superstate USTB",
    "spiko": "Spiko tokenised T-bill funds",
    "anemoy-capital": "Anemoy Capital",
    "openeden-tbill": "OpenEden TBILL",
    "matrixdock-stbt": "MatrixDock STBT",
    "vaneck-treasury-fund": "VanEck Treasury Fund",
    "arca-labs-arcoin": "Arca Labs ArCoin",
}

FRED_SERIES = {
    "sofr": "SOFR",
    "iorb": "IORB",
    "retail_mmf_assets": "WRMFNS",
}

PRIMARY_SIGNAL = "token_tvl_growth_21d_z_lag1"
SECONDARY_SIGNAL = "token_tvl_growth_7d_z_lag1"
PRIMARY_TARGETS = [
    ("future_log_rv_5d", 5, "rv"),
    ("future_log_rv_22d", 22, "rv"),
    ("future_log_range_5d", 5, "range"),
    ("future_log_range_22d", 22, "range"),
    ("future_log_amihud_5d", 5, "amihud"),
    ("future_log_amihud_22d", 22, "amihud"),
]


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
    if pd.isna(value):
        return None
    return value


def rolling_zscore(series: pd.Series, window: int = ROLL_Z_WINDOW, min_periods: int = ROLL_Z_MIN) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    # At origin t this is sum of observations t+1 through t+h.
    return series.rolling(horizon, min_periods=horizon).sum().shift(-horizon)


def forward_mean(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).mean().shift(-horizon)


def fred_csv(series_id: str) -> pd.Series:
    cache = DATA_DIR / f"fred_{series_id}.csv"
    if cache.exists():
        df = pd.read_csv(cache)
        if "date" not in df.columns and "observation_date" in df.columns:
            df = df.rename(columns={"observation_date": "date"})
        if "date" not in df.columns or series_id not in df.columns:
            cache.unlink()
            return fred_csv(series_id)
        df["date"] = pd.to_datetime(df["date"])
        if df.shape[0] > 10:
            return pd.Series(df[series_id].to_numpy(float), index=pd.to_datetime(df["date"]), name=series_id)

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text))
    if "observation_date" not in df.columns or series_id not in df.columns:
        raise RuntimeError(f"unexpected FRED schema for {series_id}")
    values = pd.to_numeric(df[series_id].replace(".", np.nan), errors="coerce")
    out = pd.Series(values.to_numpy(dtype=float), index=pd.to_datetime(df["observation_date"]), name=series_id)
    out = out.dropna().sort_index()
    out.index.name = "date"
    out.reset_index().to_csv(cache, index=False)
    return out


def fetch_protocol_tvl(slug: str) -> tuple[pd.Series, dict[str, object]]:
    cache = DATA_DIR / f"defillama_protocol_{slug}.csv"
    meta: dict[str, object] = {"slug": slug, "url": f"https://api.llama.fi/protocol/{slug}"}
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if df.shape[0] > 0:
            series = pd.Series(df["totalLiquidityUSD"].to_numpy(float), index=pd.to_datetime(df["date"]), name=slug)
            meta.update(
                {
                    "status": "ok_cache",
                    "first_date": series.index.min().date().isoformat(),
                    "last_date": series.index.max().date().isoformat(),
                    "n_obs": int(series.shape[0]),
                }
            )
            return series, meta

    response = requests.get(meta["url"], timeout=30)
    response.raise_for_status()
    data = response.json()
    rows = []
    for row in data.get("tvl", []):
        if "date" not in row or "totalLiquidityUSD" not in row:
            continue
        rows.append(
            {
                "date": pd.to_datetime(int(row["date"]), unit="s").normalize(),
                "totalLiquidityUSD": float(row["totalLiquidityUSD"] or 0.0),
            }
        )
    if not rows:
        raise RuntimeError(f"DefiLlama protocol {slug} returned no TVL rows")
    df = pd.DataFrame(rows).sort_values("date")
    df = df.groupby("date", as_index=False)["totalLiquidityUSD"].last()
    df.to_csv(cache, index=False)
    series = pd.Series(df["totalLiquidityUSD"].to_numpy(float), index=pd.to_datetime(df["date"]), name=slug)
    meta.update(
        {
            "status": "ok_download",
            "name": data.get("name"),
            "category": data.get("category"),
            "first_date": series.index.min().date().isoformat(),
            "last_date": series.index.max().date().isoformat(),
            "n_obs": int(series.shape[0]),
            "latest_tvl_usd": float(series.iloc[-1]),
        }
    )
    return series, meta


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
    meta: dict[str, object] = {"symbols": symbols, "status": "download"}
    if cache.exists():
        cached = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        frames = {}
        for symbol in symbols:
            if symbol in cached.columns.get_level_values(0):
                frames[symbol] = cached[symbol].copy()
        if len(frames) == len(symbols):
            meta["status"] = "ok_cache"
            return frames, meta

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        raw = yf.download(
            symbols,
            start=START_DATE,
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
    adj_high = high * adj_factor
    adj_low = low * adj_factor
    return {
        "close": close,
        "high": adj_high,
        "low": adj_low,
        "volume": volume,
    }


def build_tokenised_tvl_panel(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, object]]:
    raw_daily_index = pd.date_range(calendar.min(), calendar.max(), freq="D")
    components: dict[str, pd.Series] = {}
    source_meta: dict[str, object] = {}
    for slug, label in TOKENISED_TREASURY_SLUGS.items():
        series, meta = fetch_protocol_tvl(slug)
        source_meta[slug] = {"label": label, **meta}
        daily = series.reindex(raw_daily_index.union(series.index)).sort_index().ffill().reindex(raw_daily_index)
        daily = daily.fillna(0.0).clip(lower=0.0)
        components[slug] = daily
    tvl = pd.DataFrame(components).reindex(calendar, method="ffill").fillna(0.0)
    tvl["tokenised_tvl_usd"] = tvl.sum(axis=1)
    tvl["active_components"] = (tvl[list(TOKENISED_TREASURY_SLUGS)] > 1_000_000).sum(axis=1)
    tvl.index.name = "date"
    tvl.to_csv(DATA_DIR / "tokenised_treasury_tvl_panel.csv")
    return tvl, source_meta


def build_fred_controls(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, object]]:
    downloaded: dict[str, pd.Series] = {}
    status: dict[str, object] = {}
    for label, sid in FRED_SERIES.items():
        try:
            series = fred_csv(sid)
            downloaded[label] = series
            status[label] = {
                "series_id": sid,
                "status": "ok",
                "first_date": series.index.min().date().isoformat(),
                "last_date": series.index.max().date().isoformat(),
                "n_obs": int(series.shape[0]),
                "url": f"https://fred.stlouisfed.org/series/{sid}",
            }
        except Exception as exc:
            status[label] = {"series_id": sid, "status": "failed", "error": repr(exc)}
    fred = pd.DataFrame(downloaded).sort_index()
    daily = fred.reindex(calendar.union(fred.index)).ffill().reindex(calendar)
    out = pd.DataFrame(index=calendar)
    if {"sofr", "iorb"}.issubset(daily.columns):
        out["sofr_iorb_spread_z_lag1"] = rolling_zscore(daily["sofr"] - daily["iorb"]).shift(1)
    if "retail_mmf_assets" in daily.columns:
        growth_21d = np.log(daily["retail_mmf_assets"]).diff(21)
        out["traditional_mmf_growth_21d_z_lag5"] = rolling_zscore(growth_21d).shift(5)
    out.index.name = "date"
    out.to_csv(DATA_DIR / "fred_controls.csv")
    return out, status


def build_analysis_panel(market: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, object]]:
    close = market["close"]
    high = market["high"]
    low = market["low"]
    volume = market["volume"]

    target_calendar = close[TARGET_ETFS].dropna(how="all").index
    target_calendar = target_calendar[target_calendar >= pd.Timestamp(START_DATE)]
    target_calendar = pd.DatetimeIndex(target_calendar).sort_values()
    tvl, tvl_meta = build_tokenised_tvl_panel(target_calendar)
    fred_controls, fred_meta = build_fred_controls(target_calendar)

    target_close = close[TARGET_ETFS].reindex(target_calendar)
    target_high = high[TARGET_ETFS].reindex(target_calendar)
    target_low = low[TARGET_ETFS].reindex(target_calendar)
    target_volume = volume[TARGET_ETFS].reindex(target_calendar)
    target_ret = np.log(target_close / target_close.shift(1)).replace([np.inf, -np.inf], np.nan)
    target_range_sq_raw = (np.log(target_high / target_low).replace([np.inf, -np.inf], np.nan) ** 2).clip(lower=0.0)
    target_dollar_volume = (target_close * target_volume).replace(0.0, np.nan)
    target_amihud_raw = (target_ret.abs() / target_dollar_volume).replace([np.inf, -np.inf], np.nan)

    target_ret_sq = target_ret.pow(2).mean(axis=1)
    target_range_sq = target_range_sq_raw.mean(axis=1)
    target_amihud = target_amihud_raw.mean(axis=1)

    panel = pd.DataFrame(index=target_calendar)
    panel["tokenised_tvl_usd"] = tvl["tokenised_tvl_usd"]
    panel["active_components"] = tvl["active_components"]
    log_tvl = np.log(panel["tokenised_tvl_usd"].clip(lower=1_000_000))
    token_growth_7d_z = rolling_zscore(log_tvl.diff(7))
    token_growth_21d_z = rolling_zscore(log_tvl.diff(21))
    # HARD lookahead guard: predictor at t is last available signal from t-1.
    panel["token_tvl_growth_7d_z_lag1"] = token_growth_7d_z.shift(1)
    panel["token_tvl_growth_21d_z_lag1"] = token_growth_21d_z.shift(1)
    panel["token_tvl_abs_growth_21d_z_lag1"] = token_growth_21d_z.abs().shift(1)

    panel["lag_log_rv22"] = np.log(target_ret_sq.rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum().shift(1) + EPS)
    panel["lag_log_range22"] = np.log(target_range_sq.rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum().shift(1) + EPS)
    panel["lag_log_amihud22"] = np.log(target_amihud.rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).mean().shift(1) + EPS)

    for horizon in HORIZONS:
        panel[f"future_log_rv_{horizon}d"] = np.log(forward_sum(target_ret_sq, horizon) + EPS)
        panel[f"future_log_range_{horizon}d"] = np.log(forward_sum(target_range_sq, horizon) + EPS)
        panel[f"future_log_amihud_{horizon}d"] = np.log(forward_mean(target_amihud, horizon) + EPS)

    if "^VIX" in close.columns:
        panel["vix_log_lag1"] = np.log(close["^VIX"].reindex(target_calendar)).shift(1)
    if "SPY" in close.columns:
        spy_close = close["SPY"].reindex(target_calendar)
        spy_ret = np.log(spy_close / spy_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        spy_rv22 = spy_ret.pow(2).rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum()
        panel["spy_log_rv22_lag1"] = np.log(spy_rv22.shift(1) + EPS)
    if "TLT" in close.columns:
        tlt_close = close["TLT"].reindex(target_calendar)
        tlt_ret = np.log(tlt_close / tlt_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        tlt_rv22 = tlt_ret.pow(2).rolling(TRAILING_WINDOW, min_periods=TRAILING_WINDOW).sum()
        panel["tlt_log_rv22_lag1"] = np.log(tlt_rv22.shift(1) + EPS)
    crypto_symbols = [sym for sym in ["BTC-USD", "ETH-USD"] if sym in close.columns]
    if crypto_symbols:
        crypto_close = close[crypto_symbols].reindex(target_calendar)
        crypto_volume = volume[crypto_symbols].reindex(target_calendar)
        crypto_ret = np.log(crypto_close / crypto_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        crypto_dv = (crypto_close * crypto_volume).replace([np.inf, -np.inf], np.nan)
        crypto_dv_z = rolling_zscore(np.log(crypto_dv.sum(axis=1).replace(0.0, np.nan)))
        crypto_rv = crypto_ret.pow(2).mean(axis=1).rolling(7, min_periods=5).sum()
        panel["crypto_volume_z_lag1"] = crypto_dv_z.shift(1)
        panel["crypto_log_rv7_lag1"] = np.log(crypto_rv.shift(1) + EPS)

    panel = panel.join(fred_controls, how="left")
    panel = panel[panel["tokenised_tvl_usd"] >= MIN_TOKENISED_TVL_USD].copy()
    panel.index.name = "date"
    panel.to_csv(DATA_DIR / "analysis_panel.csv")

    meta = {
        "tvl_sources": tvl_meta,
        "fred_sources": fred_meta,
        "target_etfs_available": [ticker for ticker in TARGET_ETFS if ticker in close.columns],
        "calendar_start": target_calendar.min().date().isoformat(),
        "calendar_end": target_calendar.max().date().isoformat(),
    }
    return panel, meta


def available_controls(panel: pd.DataFrame, target_family: str) -> list[str]:
    controls = {
        "rv": ["lag_log_rv22"],
        "range": ["lag_log_range22"],
        "amihud": ["lag_log_amihud22"],
    }[target_family]
    optional = [
        "vix_log_lag1",
        "spy_log_rv22_lag1",
        "tlt_log_rv22_lag1",
        "sofr_iorb_spread_z_lag1",
        "traditional_mmf_growth_21d_z_lag5",
        "crypto_volume_z_lag1",
    ]
    for col in optional:
        if col in panel.columns:
            controls.append(col)
    return controls


def fit_hac_regression(
    data: pd.DataFrame,
    y_col: str,
    signal_col: str,
    controls: list[str],
    horizon: int,
) -> dict[str, object]:
    cols = [signal_col] + controls
    reg = data[[y_col] + cols].replace([np.inf, -np.inf], np.nan).dropna()
    if reg.shape[0] < 120:
        return {"status": "insufficient_data", "n": int(reg.shape[0])}
    x = reg[cols].copy()
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, np.nan)
    x = (x - means) / stds
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
    pred_df.to_csv(DATA_DIR / f"oos_{y_col}.csv")
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
        "lossdiff_definition": "base squared-error loss minus augmented squared-error loss; positive means AUM signal improves",
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
    data = panel[[y_col, signal_col]].dropna()
    if data.shape[0] < 120:
        return {"status": "insufficient_data", "n": int(data.shape[0])}
    threshold = float(data[signal_col].quantile(0.90))
    high = data.loc[data[signal_col] >= threshold, y_col]
    rest = data.loc[data[signal_col] < threshold, y_col]
    if high.shape[0] < 20 or rest.shape[0] < 20:
        return {"status": "insufficient_shock_rows", "n_high": int(high.shape[0]), "n_rest": int(rest.shape[0])}
    model = sm.OLS(
        pd.concat([high, rest]),
        sm.add_constant(pd.Series([1] * len(high) + [0] * len(rest), index=list(high.index) + list(rest.index), name="top_decile")),
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 22})
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
        "note": "descriptive top-decile contrast; daily overlapping windows are HAC-adjusted but not a causal event study",
    }


def run_tests(panel: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    primary_rows: list[dict[str, object]] = []
    results: dict[str, object] = {
        "primary_signal": PRIMARY_SIGNAL,
        "secondary_signal": SECONDARY_SIGNAL,
        "primary_hac": {},
        "secondary_hac": {},
        "oos": {},
        "shock_contrasts": {},
    }

    pvals: list[tuple[str, float]] = []
    for y_col, horizon, family in PRIMARY_TARGETS:
        controls = available_controls(panel, family)
        key = f"{y_col}__{PRIMARY_SIGNAL}"
        hac = fit_hac_regression(panel, y_col, PRIMARY_SIGNAL, controls, horizon)
        results["primary_hac"][y_col] = hac
        if hac.get("status") == "ok":
            pvals.append((y_col, float(hac["p"])))
        secondary = fit_hac_regression(panel, y_col, SECONDARY_SIGNAL, controls, horizon)
        results["secondary_hac"][y_col] = secondary
        oos = expanding_oos(panel, y_col, PRIMARY_SIGNAL, controls, horizon)
        results["oos"][y_col] = oos
        results["shock_contrasts"][y_col] = shock_contrast(panel, y_col, PRIMARY_SIGNAL)

        primary_rows.append(
            {
                "target": y_col,
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
    for row in primary_rows:
        row["primary_holm_p"] = holm.get(row["target"])
        if row["target"] in results["primary_hac"]:
            results["primary_hac"][row["target"]]["holm_p"] = holm.get(row["target"])
    summary = pd.DataFrame(primary_rows)
    summary.to_csv(DATA_DIR / "summary_table.csv", index=False)
    results["summary_table_path"] = str(DATA_DIR / "summary_table.csv")
    return results, summary


def make_figures(panel: pd.DataFrame, summary: pd.DataFrame) -> list[str]:
    paths: list[str] = []

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    panel["tokenised_tvl_usd"].div(1e9).plot(ax=axes[0], color="#1f77b4", linewidth=2.0)
    axes[0].set_title("Tokenised Treasury / MMF-like RWA TVL")
    axes[0].set_ylabel("USD bn")
    axes[0].grid(alpha=0.25)
    panel[PRIMARY_SIGNAL].plot(ax=axes[1], color="#d62728", linewidth=1.2)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Lagged 21-trading-day TVL growth z-score")
    axes[1].set_ylabel("z")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "tokenised_tvl_signal.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    plot_df = summary.copy()
    plot_df["label"] = plot_df["target"].str.replace("future_log_", "", regex=False)
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


def main() -> dict[str, object]:
    ensure_dirs()
    np.random.seed(SEED)
    symbols = TARGET_ETFS + CONTROL_TICKERS
    frames, yf_meta = download_yfinance_ohlcv(symbols)
    market = build_market_frames(frames)
    panel, source_meta = build_analysis_panel(market)
    tests, summary = run_tests(panel)
    figure_paths = make_figures(panel, summary)

    primary_passes = []
    raw_positive = []
    for _, row in summary.iterrows():
        t_value = row.get("primary_t")
        holm_p = row.get("primary_holm_p")
        coef = row.get("primary_coef")
        oos_t = row.get("oos_dm_t")
        oos_improvement = row.get("oos_mse_improvement_pct")
        if pd.notna(coef) and coef > 0 and pd.notna(t_value):
            if abs(float(t_value)) >= 3.0 and pd.notna(holm_p) and float(holm_p) < 0.05:
                if pd.notna(oos_t) and float(oos_t) >= 3.0 and pd.notna(oos_improvement) and float(oos_improvement) > 0:
                    primary_passes.append(row["target"])
            if abs(float(t_value)) >= 2.0:
                raw_positive.append(row["target"])

    if primary_passes:
        verdict = "PASS_PUBLIC_PROXY_SIGNAL"
    elif raw_positive:
        verdict = "WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS"
    else:
        verdict = "NULL_NO_ROBUST_PUBLIC_PROXY_SIGNAL"

    results: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Tokenised Treasury / money-market-fund AUM shock to T-bill ETF liquidity-vol",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "seed": SEED,
        "verdict": verdict,
        "sample": {
            "start": panel.index.min().date().isoformat(),
            "end": panel.index.max().date().isoformat(),
            "n_trading_days": int(panel.shape[0]),
            "min_tokenised_tvl_usd": MIN_TOKENISED_TVL_USD,
            "latest_tokenised_tvl_usd": float(panel["tokenised_tvl_usd"].iloc[-1]),
            "latest_active_components": int(panel["active_components"].iloc[-1]),
        },
        "data_sources": {
            "defillama_protocols": source_meta["tvl_sources"],
            "yfinance": yf_meta,
            "fred": source_meta["fred_sources"],
        },
        "method": {
            "target_etfs": TARGET_ETFS,
            "controls": [
                "lagged own target family",
                "VIX level",
                "SPY/TLT trailing RV",
                "SOFR-IORB spread",
                "traditional retail MMF AUM growth",
                "BTC/ETH dollar-volume activity",
            ],
            "primary_signal": PRIMARY_SIGNAL,
            "secondary_signal": SECONDARY_SIGNAL,
            "lookahead_guards": [
                "token_tvl_growth signals use .shift(1)",
                "traditional MMF control uses .shift(5)",
                "targets are t+1..t+h",
                "OOS expanding forecasts embargo train rows by horizon",
            ],
            "statistical_gate": "positive coefficient + |HAC t|>=3 + Holm p<0.05 + positive OOS MSE improvement with DM t>=3",
        },
        "tests": tests,
        "summary_table": to_jsonable(summary.to_dict(orient="records")),
        "figures": figure_paths,
        "limitations": [
            "DefiLlama protocol TVL is a public proxy, not a complete RWA.xyz or issuer-by-issuer collateral ledger.",
            "Daily ETF OHLCV cannot observe bid-ask spreads, creation/redemption baskets, or primary-market Treasury bill flow.",
            "Tokenised Treasury history is short and dominated by 2024-2026 adoption growth, so coefficients can reflect trend/regime timing.",
            "The experiment is diagnostic for public proxy usefulness only; it is not a causal test of tokenised-fund flows.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(to_jsonable(results), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(to_jsonable({"verdict": verdict, "sample": results["sample"]}), indent=2, ensure_ascii=False))
    return results


if __name__ == "__main__":
    main()
