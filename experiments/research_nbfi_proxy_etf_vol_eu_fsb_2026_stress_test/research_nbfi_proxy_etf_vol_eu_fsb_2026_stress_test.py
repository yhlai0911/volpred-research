#!/usr/bin/env python3
"""Free-data NBFI run-pressure proxy and bank/credit ETF risk."""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test"
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"

START_DATE = "2013-01-01"
ETF_TICKERS = ["HYG", "LQD", "BKLN", "BIZD", "KRE", "KBE", "XLF", "SPY", "^VIX"]
PRESSURE_ETFS = ["HYG", "BKLN", "BIZD"]
TARGET_ETFS = ["KRE", "KBE", "XLF", "HYG"]
HORIZONS = [5, 22]
REFIT_EVERY = 21
EPS = 1e-12

FRED_SERIES = {
    "retail_mmf_assets": "WRMFNS",
    "total_mmf_assets": "MMMFFAQ027S",
    "bank_credit": "TOTBKCR",
    "sofr": "SOFR",
    "iorb": "IORB",
}

BASE_STATIC_COLS = [
    "spy_rv22_lag1",
    "vix_log_lag1",
    "hyg_lqd_gap_22_lag1",
]


@dataclass
class FittedOLS:
    cols: list[str]
    means: pd.Series
    stds: pd.Series
    params: pd.Series


def fred_csv(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text))
    if "observation_date" not in df.columns or series_id not in df.columns:
        raise RuntimeError(f"unexpected FRED schema for {series_id}")
    values = pd.to_numeric(df[series_id].replace(".", np.nan), errors="coerce")
    out = pd.Series(values.to_numpy(dtype=float), index=pd.to_datetime(df["observation_date"]), name=series_id)
    return out.dropna().sort_index()


def download_yfinance(tickers: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        raw = yf.download(
            list(tickers),
            start=START_DATE,
            auto_adjust=True,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(1):
            close = raw.xs("Close", axis=1, level=1, drop_level=True)
            volume = raw.xs("Volume", axis=1, level=1, drop_level=True)
        else:
            close = raw.xs("Close", axis=1, level=0, drop_level=True)
            volume = raw.xs("Volume", axis=1, level=0, drop_level=True)
    else:
        close = raw[["Close"]]
        volume = raw[["Volume"]]
    close.columns = [str(c) for c in close.columns]
    volume.columns = [str(c) for c in volume.columns]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    volume.index = pd.to_datetime(volume.index).tz_localize(None)
    return close.sort_index().dropna(axis=1, how="all"), volume.sort_index().reindex(close.index)


def rolling_zscore(series: pd.Series, window: int = 252, min_periods: int = 63) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def backward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(1)


def forward_average_pairwise_corr(returns: pd.DataFrame, horizon: int) -> pd.Series:
    values: list[float] = []
    idx = returns.index
    for pos in range(len(idx)):
        window = returns.iloc[pos : pos + horizon].dropna(axis=1, how="any")
        if len(window) < horizon or window.shape[1] < 3:
            values.append(float("nan"))
            continue
        corr = window.corr()
        mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
        values.append(float(corr.where(mask).stack().mean()))
    return pd.Series(values, index=idx, name=f"cross_sector_corr_{horizon}d")


def backward_average_pairwise_corr(returns: pd.DataFrame, horizon: int) -> pd.Series:
    values: list[float] = []
    idx = returns.index
    for pos in range(len(idx)):
        window = returns.iloc[max(0, pos - horizon) : pos].dropna(axis=1, how="any")
        if len(window) < horizon or window.shape[1] < 3:
            values.append(float("nan"))
            continue
        corr = window.corr()
        mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
        values.append(float(corr.where(mask).stack().mean()))
    return pd.Series(values, index=idx, name=f"cross_sector_corr_back_{horizon}d")


def build_fred_frame(index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, object]]:
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
                "n": int(series.shape[0]),
                "url": f"https://fred.stlouisfed.org/series/{sid}",
            }
        except Exception as exc:
            status[label] = {"series_id": sid, "status": "failed", "error": repr(exc)}
    fred = pd.DataFrame(downloaded).sort_index()
    daily = fred.reindex(index.union(fred.index)).ffill().reindex(index)
    return daily, status


def build_run_pressure(close: pd.DataFrame, volume: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    returns = np.log(close).diff().replace([np.inf, -np.inf], np.nan)
    dollar_volume = (close * volume).replace(0.0, np.nan)
    panel = pd.DataFrame(index=close.index)

    volume_components = []
    illiq_components = []
    for ticker in PRESSURE_ETFS:
        if ticker in close.columns and ticker in volume.columns:
            volume_components.append(rolling_zscore(np.log(dollar_volume[ticker])))
            illiq_components.append(
                rolling_zscore((returns[ticker].abs() / dollar_volume[ticker]).replace([np.inf, -np.inf], np.nan))
            )
    panel["etf_volume_shock_z"] = pd.concat(volume_components, axis=1).mean(axis=1)
    panel["etf_illiquidity_z"] = pd.concat(illiq_components, axis=1).mean(axis=1)

    if {"HYG", "LQD"}.issubset(returns.columns):
        panel["credit_underperformance_z"] = rolling_zscore(-(returns["HYG"] - returns["LQD"]).rolling(22).sum())
        panel["hyg_lqd_gap_22_lag1"] = (-(returns["HYG"] - returns["LQD"]).rolling(22).sum()).shift(1)
    if {"BIZD", "HYG"}.issubset(returns.columns):
        panel["bdc_discount_proxy_z"] = rolling_zscore(-(returns["BIZD"] - returns["HYG"]).rolling(22).sum())

    if "retail_mmf_assets" in fred.columns:
        panel["retail_mmf_flow_z"] = rolling_zscore(fred["retail_mmf_assets"].pct_change(21))
    if "total_mmf_assets" in fred.columns:
        panel["total_mmf_flow_z"] = rolling_zscore(fred["total_mmf_assets"].pct_change(63))
    if "bank_credit" in fred.columns:
        panel["bank_credit_contraction_z"] = rolling_zscore(-fred["bank_credit"].pct_change(63))
    if {"sofr", "iorb"}.issubset(fred.columns):
        panel["sofr_iorb_spread_z"] = rolling_zscore(fred["sofr"] - fred["iorb"], window=126, min_periods=30)

    component_cols = [
        "etf_volume_shock_z",
        "etf_illiquidity_z",
        "credit_underperformance_z",
        "bdc_discount_proxy_z",
        "retail_mmf_flow_z",
        "total_mmf_flow_z",
        "bank_credit_contraction_z",
        "sofr_iorb_spread_z",
    ]
    panel["run_pressure_raw"] = panel[[c for c in component_cols if c in panel.columns]].mean(axis=1)
    panel["run_pressure_index"] = rolling_zscore(panel["run_pressure_raw"])

    rv22 = returns.pow(2).rolling(22, min_periods=18).sum()
    panel["spy_rv22_lag1"] = rv22["SPY"].shift(1) if "SPY" in rv22.columns else np.nan
    panel["vix_log_lag1"] = np.log(close["^VIX"]).shift(1) if "^VIX" in close.columns else np.nan
    # Critical lookahead guard: all composite pressure information is lagged.
    panel["run_pressure_lag1"] = panel["run_pressure_index"].shift(1)
    return panel


def build_targets(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    returns = np.log(close).diff().replace([np.inf, -np.inf], np.nan)
    targets: dict[str, pd.DataFrame] = {}
    for ticker in TARGET_ETFS:
        if ticker not in returns.columns:
            continue
        squared = returns[ticker].pow(2)
        downside = returns[ticker].clip(upper=0.0).pow(2)
        for horizon in HORIZONS:
            targets[f"{ticker}_future_rv_{horizon}d"] = pd.DataFrame(
                {
                    "target": forward_sum(squared, horizon),
                    "target_back_lag1": backward_sum(squared, horizon),
                    "target_type": "variance",
                }
            )
            targets[f"{ticker}_future_downside_var_{horizon}d"] = pd.DataFrame(
                {
                    "target": forward_sum(downside, horizon),
                    "target_back_lag1": backward_sum(downside, horizon),
                    "target_type": "variance",
                }
            )
    corr_cols = [t for t in TARGET_ETFS if t in returns.columns]
    corr = forward_average_pairwise_corr(returns[corr_cols], 22)
    targets["bank_credit_cross_sector_corr_22d"] = pd.DataFrame(
        {
            "target": corr,
            "target_back_lag1": backward_average_pairwise_corr(returns[corr_cols], 22),
            "target_type": "correlation",
        }
    )
    return targets


def qlike(actual: pd.Series | np.ndarray, forecast: pd.Series | np.ndarray) -> np.ndarray:
    actual_arr = np.asarray(actual, dtype=float)
    forecast_arr = np.asarray(forecast, dtype=float)
    ratio = np.clip(actual_arr, EPS, None) / np.clip(forecast_arr, EPS, None)
    return ratio - np.log(ratio) - 1.0


def hac_mean_test(x: Iterable[float], maxlags: int) -> dict[str, float]:
    arr = pd.Series(list(x), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(arr) < 30 or float(arr.std(ddof=1)) <= EPS:
        return {"mean": float(arr.mean()) if len(arr) else math.nan, "t": math.nan, "p": math.nan, "n": int(len(arr))}
    model = sm.OLS(arr.to_numpy(), np.ones((len(arr), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags}
    )
    return {
        "mean": float(model.params[0]),
        "t": float(model.tvalues[0]),
        "p": float(model.pvalues[0]),
        "n": int(len(arr)),
    }


def fit_ols(train: pd.DataFrame, target_col: str, cols: list[str], target_type: str) -> FittedOLS:
    x = train[cols].astype(float)
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    xz = sm.add_constant((x - means) / stds, has_constant="add")
    if target_type == "variance":
        y = np.log(train[target_col].clip(lower=EPS))
    else:
        y = train[target_col].astype(float)
    result = sm.OLS(y, xz).fit()
    return FittedOLS(cols=cols, means=means, stds=stds, params=result.params)


def predict_ols(model: FittedOLS, row: pd.Series, target_type: str) -> float:
    x = row[model.cols].astype(float)
    xz = (x - model.means) / model.stds
    xz = pd.Series({"const": 1.0, **xz.to_dict()}).reindex(model.params.index)
    pred = float(np.dot(xz.to_numpy(dtype=float), model.params.to_numpy(dtype=float)))
    if target_type == "variance":
        return float(np.exp(np.clip(pred, -40.0, 20.0)))
    return pred


def split_position(clean: pd.DataFrame, horizon: int, min_train: int) -> int:
    calendar_pos = int(clean.index.searchsorted(pd.Timestamp("2021-01-04")))
    if calendar_pos >= min_train + horizon and len(clean) - calendar_pos >= 252:
        pos = calendar_pos
    else:
        pos = int(len(clean) * 0.70)
    return max(pos, min_train + horizon)


def expanding_oos(
    data: pd.DataFrame,
    target_col: str,
    base_cols: list[str],
    aug_cols: list[str],
    horizon: int,
    target_type: str,
    min_train: int = 756,
) -> tuple[pd.DataFrame, dict[str, object]]:
    cols = list(dict.fromkeys([target_col] + base_cols + aug_cols))
    clean = data[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if target_type == "variance":
        clean = clean.loc[clean[target_col] > EPS]
    if len(clean) < min_train + horizon + 80:
        return pd.DataFrame(), {
            "status": "skipped",
            "reason": "insufficient_clean_rows",
            "clean_rows": int(len(clean)),
        }
    first_oos = split_position(clean, horizon, min_train)
    records: list[dict[str, object]] = []
    base_model: FittedOLS | None = None
    aug_model: FittedOLS | None = None
    last_refit_pos = -10**9
    refit_count = 0
    for i in range(first_oos, len(clean)):
        train_stop = i - horizon + 1
        if train_stop < min_train:
            continue
        if base_model is None or i - last_refit_pos >= REFIT_EVERY:
            train = clean.iloc[:train_stop]
            base_model = fit_ols(train, target_col, base_cols, target_type)
            aug_model = fit_ols(train, target_col, aug_cols, target_type)
            last_refit_pos = i
            refit_count += 1
        row = clean.iloc[i]
        assert base_model is not None and aug_model is not None
        records.append(
            {
                "date": clean.index[i],
                "actual": float(row[target_col]),
                "pred_base": predict_ols(base_model, row, target_type),
                "pred_aug": predict_ols(aug_model, row, target_type),
            }
        )
    pred = pd.DataFrame.from_records(records)
    if pred.empty:
        return pred, {"status": "skipped", "reason": "no_oos_predictions"}
    pred["date"] = pd.to_datetime(pred["date"])
    pred = pred.set_index("date").sort_index()
    meta = {
        "status": "ok",
        "clean_rows": int(len(clean)),
        "oos_rows": int(len(pred)),
        "first_clean_date": clean.index.min().date().isoformat(),
        "last_clean_date": clean.index.max().date().isoformat(),
        "first_oos_date": pred.index.min().date().isoformat(),
        "last_oos_date": pred.index.max().date().isoformat(),
        "min_train": int(min_train),
        "refit_every": int(REFIT_EVERY),
        "refit_count": int(refit_count),
    }
    return pred, meta


def evaluate_prediction(pred: pd.DataFrame, horizon: int, target_type: str) -> dict[str, object]:
    if pred.empty:
        return {"status": "skipped"}
    mse_base = np.square(pred["actual"] - pred["pred_base"])
    mse_aug = np.square(pred["actual"] - pred["pred_aug"])
    mse_diff = mse_base - mse_aug
    out = {
        "status": "ok",
        "mse_base": float(np.mean(mse_base)),
        "mse_aug": float(np.mean(mse_aug)),
        "mse_improvement_pct": float(100.0 * (np.mean(mse_base) - np.mean(mse_aug)) / np.mean(mse_base)),
        "mse_dm": hac_mean_test(mse_diff, maxlags=max(5, horizon)),
    }
    if target_type == "variance":
        loss_base = qlike(pred["actual"], pred["pred_base"])
        loss_aug = qlike(pred["actual"], pred["pred_aug"])
        qlike_diff = loss_base - loss_aug
        out.update(
            {
                "qlike_base": float(np.mean(loss_base)),
                "qlike_aug": float(np.mean(loss_aug)),
                "qlike_improvement_pct": float(100.0 * (np.mean(loss_base) - np.mean(loss_aug)) / np.mean(loss_base)),
                "qlike_dm": hac_mean_test(qlike_diff, maxlags=max(5, horizon)),
            }
        )
    return out


def hac_signal_coefficient(data: pd.DataFrame, target_col: str, cols: list[str], horizon: int, target_type: str) -> dict[str, float]:
    clean = data[[target_col] + cols].replace([np.inf, -np.inf], np.nan).dropna()
    if target_type == "variance":
        clean = clean.loc[clean[target_col] > EPS]
        y = np.log(clean[target_col].clip(lower=EPS))
    else:
        y = clean[target_col]
    if len(clean) < 200:
        return {}
    x = clean[cols].astype(float)
    x = (x - x.mean()) / x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    result = sm.OLS(y, sm.add_constant(x, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(5, horizon)}
    )
    return {
        "coef": float(result.params["run_pressure_lag1"]),
        "t": float(result.tvalues["run_pressure_lag1"]),
        "p": float(result.pvalues["run_pressure_lag1"]),
        "n": int(len(clean)),
    }


def plot_run_pressure(panel: pd.DataFrame) -> str:
    fig_path = FIG_DIR / "nbfi_run_pressure_timeseries.png"
    fig, ax = plt.subplots(figsize=(10, 4.8))
    panel["run_pressure_index"].dropna().plot(ax=ax, linewidth=1.0, color="#375a7f")
    ax.axhline(0.0, color="#222222", linewidth=0.8)
    ax.set_title("Free-data NBFI run-pressure proxy")
    ax.set_ylabel("Rolling z-score")
    ax.set_xlabel("")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)
    return str(fig_path.relative_to(OUT_DIR))


def plot_dm(summary_rows: list[dict[str, object]]) -> str:
    fig_path = FIG_DIR / "oos_dm_tstats.png"
    rows = [r for r in summary_rows if r.get("status") == "ok"]
    labels = [f"{r['target']} {r['horizon']}d {r['target_type']}" for r in rows]
    vals = [float(r.get("qlike_dm_t") if r.get("target_type") == "variance" else r.get("mse_dm_t")) for r in rows]
    fig, ax = plt.subplots(figsize=(10, max(5.0, 0.31 * len(labels))))
    y = np.arange(len(labels))
    colors = ["#2f7d59" if v > 0 else "#b24b4b" for v in vals]
    ax.barh(y, vals, color=colors, alpha=0.82)
    ax.axvline(0.0, color="#222222", linewidth=0.8)
    ax.axvline(3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.axvline(-3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("DM/HAC t-statistic; positive favors NBFI-pressure augmented model")
    ax.set_title("Out-of-sample comparison")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)
    return str(fig_path.relative_to(OUT_DIR))


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    close, volume = download_yfinance(ETF_TICKERS)
    fred, fred_status = build_fred_frame(close.index)
    panel = build_run_pressure(close, volume, fred)
    target_panels = build_targets(close)

    summary_rows: list[dict[str, object]] = []
    detailed: dict[str, object] = {}
    for target_name, target_df in target_panels.items():
        target_type = str(target_df["target_type"].dropna().iloc[0])
        target_col = f"{target_name}_target"
        horizon = 22 if "22d" in target_name else 5
        data = target_df.drop(columns=["target_type"]).rename(columns={"target": target_col})
        data = pd.concat([data, panel.reindex(data.index)], axis=1)
        base_cols = ["target_back_lag1"] + BASE_STATIC_COLS
        aug_cols = base_cols + ["run_pressure_lag1"]
        pred, meta = expanding_oos(data, target_col, base_cols, aug_cols, horizon, target_type)
        eval_result = evaluate_prediction(pred, horizon, target_type)
        coeff = hac_signal_coefficient(data, target_col, aug_cols, horizon, target_type)
        detailed[target_name] = {
            "meta": meta,
            "eval": eval_result,
            "signal_hac_coefficient": coeff,
            "base_columns": base_cols,
            "augmented_columns": aug_cols,
            "target_type": target_type,
        }
        row = {
            "target": target_name,
            "target_type": target_type,
            "horizon": horizon,
            "status": eval_result.get("status", "skipped"),
        }
        if eval_result.get("status") == "ok":
            row.update(
                {
                    "oos_rows": meta["oos_rows"],
                    "first_oos_date": meta["first_oos_date"],
                    "last_oos_date": meta["last_oos_date"],
                    "mse_improvement_pct": eval_result["mse_improvement_pct"],
                    "mse_dm_t": eval_result["mse_dm"]["t"],
                    "signal_hac_t": coeff.get("t"),
                    "signal_hac_beta": coeff.get("coef"),
                }
            )
            if target_type == "variance":
                row.update(
                    {
                        "qlike_improvement_pct": eval_result["qlike_improvement_pct"],
                        "qlike_dm_t": eval_result["qlike_dm"]["t"],
                        "qlike_base": eval_result["qlike_base"],
                        "qlike_aug": eval_result["qlike_aug"],
                    }
                )
        else:
            row["skip_meta"] = meta
        summary_rows.append(row)

    ok_rows = [r for r in summary_rows if r.get("status") == "ok"]
    variance_rows = [r for r in ok_rows if r.get("target_type") == "variance"]
    positive_harvey = [
        r
        for r in variance_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) > 3.0
        and float(r["qlike_improvement_pct"]) > 0.0
    ]
    negative_harvey = [
        r
        for r in variance_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) < -3.0
        and float(r["qlike_improvement_pct"]) < 0.0
    ]
    median_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in variance_rows]).median())
    mean_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in variance_rows]).mean())
    if positive_harvey and median_improvement > 0:
        verdict = "mixed_positive"
        conclusion = (
            "The free-data NBFI run-pressure proxy has at least one Harvey-significant "
            "positive OOS QLIKE cell, but scope depends on target and horizon."
        )
    else:
        verdict = "null_or_weak_diagnostic"
        conclusion = (
            "The free-data NBFI run-pressure proxy does not robustly improve OOS QLIKE "
            "for bank/credit ETF variance targets after own-risk, SPY, VIX, and HYG-LQD controls."
        )

    figures = {
        "run_pressure_timeseries": plot_run_pressure(panel),
        "oos_dm_tstats": plot_dm(summary_rows),
    }

    result = {
        "experiment_id": EXPERIMENT_ID,
        "run_timestamp_local": datetime.now().astimezone().isoformat(),
        "data_sources": {
            "yfinance": {
                "tickers_requested": ETF_TICKERS,
                "tickers_downloaded": close.columns.tolist(),
                "first_date": close.index.min().date().isoformat(),
                "last_date": close.index.max().date().isoformat(),
            },
            "fred": fred_status,
        },
        "literature_checked": [
            {
                "title": "FSB Global Monitoring Report on Non-Bank Financial Intermediation 2025",
                "url": "https://www.fsb.org/2025/12/global-monitoring-report-on-nonbank-financial-intermediation-2025/",
                "role": "NBFI liquidity/maturity transformation and market-volatility amplification motivation.",
            },
            {
                "title": "ESRB/ECB 2026 report on bank-NBFI linkages",
                "url": "https://www.esrb.europa.eu/pub/pdf/reports/esrb.report202602_financialstabilityrisks.en.pdf",
                "role": "bank liquidity/leverage/market-making channels from NBFI stress.",
            },
            {
                "title": "FRED WRMFNS retail money market funds",
                "url": "https://fred.stlouisfed.org/series/WRMFNS",
                "role": "weekly ICI-based MMF assets component used as cash-migration proxy.",
            },
            {
                "title": "BIS WP 972 Non-bank financial intermediaries and financial stability",
                "url": "https://www.bis.org/publ/work972.pdf",
                "role": "liquidity-demand shock and NBFI amplification background.",
            },
        ],
        "design": {
            "proxy_components": [
                "HYG/BKLN/BIZD ETF dollar-volume shock",
                "HYG/BKLN/BIZD ETF Amihud-style illiquidity",
                "HYG vs LQD credit underperformance",
                "BIZD vs HYG BDC discount-style pressure",
                "FRED WRMFNS retail MMF flow",
                "FRED MMMFFAQ027S total MMF asset flow",
                "FRED TOTBKCR bank-credit contraction",
                "FRED SOFR minus IORB spread",
            ],
            "feature_lag_rule": "Composite run_pressure_index is used only through run_pressure_index.shift(1).",
            "target_alignment": "Variance targets at date t are forward sums over t..t+h-1; OOS training at t excludes rows whose target window ends after t-1.",
            "baseline_model": "own lagged target, SPY 22d RV, log VIX, HYG-LQD 22d gap.",
            "augmented_model": "baseline plus lagged NBFI run-pressure index.",
            "loss": "Variance targets use QLIKE(actual, predicted); correlation target is diagnostic MSE only.",
            "formal_test": "DM/HAC on baseline loss minus augmented loss; Harvey-style practical threshold |t| > 3 for variance QLIKE cells.",
        },
        "summary": {
            "n_ok_cells": int(len(ok_rows)),
            "n_variance_cells": int(len(variance_rows)),
            "positive_harvey_cells": int(len(positive_harvey)),
            "negative_harvey_cells": int(len(negative_harvey)),
            "median_qlike_improvement_pct": median_improvement,
            "mean_qlike_improvement_pct": mean_improvement,
            "verdict": verdict,
            "conclusion": conclusion,
        },
        "summary_rows": summary_rows,
        "detailed_results": detailed,
        "figures": figures,
        "limitations": [
            "This is a pure free-data proxy, not ICI full MMF flow by fund, TRACE liquidity, fund NAV discount, or supervisory NBFI exposure data.",
            "WRMFNS is a retail MMF component built from weekly ICI data; total MMF assets are quarterly flow-of-funds data and are forward-filled for daily alignment.",
            "ETF price/volume pressure can mix NBFI liquidity stress with ordinary market beta and risk-off regimes.",
            "Correlation target is a diagnostic MSE cell, not a variance-forecast QLIKE cell.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "summary_table.csv", index=False)
    panel.to_csv(OUT_DIR / "daily_panel.csv", index_label="date")
    print(json.dumps(json_safe(result["summary"]), indent=2))


if __name__ == "__main__":
    main()
