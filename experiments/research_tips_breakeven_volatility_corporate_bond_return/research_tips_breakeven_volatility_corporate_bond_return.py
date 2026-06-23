#!/usr/bin/env python3
"""TIPS breakeven volatility and corporate bond ETF risk.

The experiment tests whether lagged realized volatility of 5y/10y breakeven
inflation changes adds out-of-sample predictive content for corporate bond ETF
future realized variance, downside variance, and credit-spread variance.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_tips_breakeven_volatility_corporate_bond_return"
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"

START_DATE = "2003-01-01"
ETF_TICKERS = ["LQD", "HYG", "BKLN", "SPY", "^VIX"]
CORPORATE_ETFS = ["LQD", "HYG", "BKLN"]
HORIZONS = [5, 22]
REFIT_EVERY = 21
EPS = 1e-12

FRED_SERIES = {
    "T5YIE": "5-year breakeven inflation rate",
    "T10YIE": "10-year breakeven inflation rate",
    "BAMLH0A0HYM2": "ICE BofA US High Yield Index option-adjusted spread",
    "BAMLC0A0CM": "ICE BofA US Corporate Index option-adjusted spread",
}

BASE_STATIC_COLS = [
    "t5_level_lag1",
    "t10_level_lag1",
    "bei_slope_lag1",
    "t5_chg_bp_lag1",
    "t10_chg_bp_lag1",
    "vix_level_lag1",
    "vix_chg5_lag1",
    "spy_rv22_lag1",
]

VOL_COLS = [
    "bei_vol21_avg_lag1",
    "bei_vol63_avg_lag1",
    "bei_vol21_slope_lag1",
    "bei_vol63_slope_lag1",
]


@dataclass
class FittedOLS:
    cols: list[str]
    means: pd.Series
    stds: pd.Series
    result: sm.regression.linear_model.RegressionResultsWrapper


def fred_csv(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(url)
    if df.shape[1] != 2:
        raise ValueError(f"Unexpected FRED CSV shape for {series_id}: {df.shape}")
    date_col, value_col = df.columns
    series = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        index=pd.to_datetime(df[date_col]),
        name=series_id,
    )
    return series.dropna().sort_index()


def download_yfinance_series(ticker: str) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        df = yf.download(
            ticker,
            start=START_DATE,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    if df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Close" if "Close" in df.columns else "Adj Close"
    s = df[col].dropna().copy()
    s.name = ticker
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.sort_index()


def build_features(fred: dict[str, pd.Series], prices: dict[str, pd.Series]) -> pd.DataFrame:
    bei = pd.concat([fred["T5YIE"], fred["T10YIE"]], axis=1).dropna()
    bei.columns = ["t5_level", "t10_level"]
    bei["bei_slope"] = bei["t10_level"] - bei["t5_level"]
    bei["t5_chg_bp"] = bei["t5_level"].diff() * 100.0
    bei["t10_chg_bp"] = bei["t10_level"].diff() * 100.0
    bei["t5_vol21"] = bei["t5_chg_bp"].rolling(21, min_periods=15).std()
    bei["t10_vol21"] = bei["t10_chg_bp"].rolling(21, min_periods=15).std()
    bei["t5_vol63"] = bei["t5_chg_bp"].rolling(63, min_periods=45).std()
    bei["t10_vol63"] = bei["t10_chg_bp"].rolling(63, min_periods=45).std()
    bei["bei_vol21_avg"] = (bei["t5_vol21"] + bei["t10_vol21"]) / 2.0
    bei["bei_vol63_avg"] = (bei["t5_vol63"] + bei["t10_vol63"]) / 2.0
    bei["bei_vol21_slope"] = bei["t10_vol21"] - bei["t5_vol21"]
    bei["bei_vol63_slope"] = bei["t10_vol63"] - bei["t5_vol63"]

    close = pd.concat(prices, axis=1).sort_index()
    returns = np.log(close).diff()
    vix = close["^VIX"].rename("vix_level")
    vix_chg5 = vix.diff(5).rename("vix_chg5")
    spy_rv22 = returns["SPY"].pow(2).rolling(22, min_periods=15).sum().rename("spy_rv22")

    master_index = close.index.union(bei.index).sort_values()
    raw = pd.concat(
        [
            bei[
                [
                    "t5_level",
                    "t10_level",
                    "bei_slope",
                    "t5_chg_bp",
                    "t10_chg_bp",
                    "bei_vol21_avg",
                    "bei_vol63_avg",
                    "bei_vol21_slope",
                    "bei_vol63_slope",
                ]
            ].reindex(master_index).ffill(),
            vix.reindex(master_index).ffill(),
            vix_chg5.reindex(master_index).ffill(),
            spy_rv22.reindex(master_index).ffill(),
        ],
        axis=1,
    )
    # All model signals are lagged one trading day before they meet any target.
    return raw.shift(1).add_suffix("_lag1")


def forward_sum(x: pd.Series, horizon: int) -> pd.Series:
    return x.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def backward_sum(x: pd.Series, horizon: int) -> pd.Series:
    return x.rolling(horizon, min_periods=horizon).sum().shift(1)


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


def fit_ols(train: pd.DataFrame, target_col: str, cols: list[str]) -> FittedOLS:
    x = train[cols].astype(float)
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    xz = (x - means) / stds
    y = np.log(train[target_col].clip(lower=EPS))
    result = sm.OLS(y, sm.add_constant(xz, has_constant="add")).fit()
    return FittedOLS(cols=cols, means=means, stds=stds, result=result)


def predict_ols(model: FittedOLS, row: pd.Series) -> float:
    x = row[model.cols].astype(float)
    xz = (x - model.means) / model.stds
    xdf = pd.DataFrame([xz.to_dict()])
    xdf = sm.add_constant(xdf, has_constant="add")
    pred_log = float(model.result.predict(xdf)[0])
    return float(np.exp(np.clip(pred_log, -40.0, 20.0)))


def split_position(clean: pd.DataFrame, horizon: int, min_train: int) -> int:
    calendar_pos = int(clean.index.searchsorted(pd.Timestamp("2018-01-02")))
    if calendar_pos >= min_train + horizon and len(clean) - calendar_pos >= 250:
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
    min_train: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    cols = list(dict.fromkeys([target_col] + base_cols + aug_cols))
    clean = (
        data[cols]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .loc[lambda d: d[target_col] > EPS]
        .copy()
    )
    if len(clean) < min_train + horizon + 60:
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
            base_model = fit_ols(train, target_col, base_cols)
            aug_model = fit_ols(train, target_col, aug_cols)
            last_refit_pos = i
            refit_count += 1
        row = clean.iloc[i]
        assert base_model is not None and aug_model is not None
        records.append(
            {
                "date": clean.index[i],
                "actual": float(row[target_col]),
                "pred_base": predict_ols(base_model, row),
                "pred_aug": predict_ols(aug_model, row),
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


def evaluate_prediction(pred: pd.DataFrame, horizon: int) -> dict[str, object]:
    if pred.empty:
        return {"status": "skipped"}
    loss_base = qlike(pred["actual"], pred["pred_base"])
    loss_aug = qlike(pred["actual"], pred["pred_aug"])
    mse_base = np.square(pred["actual"] - pred["pred_base"])
    mse_aug = np.square(pred["actual"] - pred["pred_aug"])
    qlike_diff = loss_base - loss_aug
    mse_diff = mse_base - mse_aug
    return {
        "status": "ok",
        "qlike_base": float(np.mean(loss_base)),
        "qlike_aug": float(np.mean(loss_aug)),
        "qlike_improvement_pct": float(100.0 * (np.mean(loss_base) - np.mean(loss_aug)) / np.mean(loss_base)),
        "qlike_dm": hac_mean_test(qlike_diff, maxlags=max(5, horizon)),
        "mse_base": float(np.mean(mse_base)),
        "mse_aug": float(np.mean(mse_aug)),
        "mse_improvement_pct": float(100.0 * (np.mean(mse_base) - np.mean(mse_aug)) / np.mean(mse_base)),
        "mse_dm": hac_mean_test(mse_diff, maxlags=max(5, horizon)),
    }


def hac_coefficients(
    data: pd.DataFrame,
    target_col: str,
    cols: list[str],
    horizon: int,
) -> dict[str, dict[str, float]]:
    clean = (
        data[[target_col] + cols]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .loc[lambda d: d[target_col] > EPS]
    )
    if len(clean) < 120:
        return {}
    x = clean[cols].astype(float)
    x = (x - x.mean()) / x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    y = np.log(clean[target_col].clip(lower=EPS))
    result = sm.OLS(y, sm.add_constant(x, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(5, horizon)}
    )
    out: dict[str, dict[str, float]] = {}
    for col in VOL_COLS:
        if col in result.params.index:
            out[col] = {
                "coef": float(result.params[col]),
                "t": float(result.tvalues[col]),
                "p": float(result.pvalues[col]),
            }
    return out


def target_panel_for_etf(
    ticker: str,
    returns: pd.Series,
    features: pd.DataFrame,
    horizon: int,
    target_kind: str,
) -> tuple[pd.DataFrame, str]:
    if target_kind == "future_rv":
        target_source = returns.pow(2)
    elif target_kind == "future_downside_var":
        target_source = np.minimum(returns, 0.0).pow(2)
    else:
        raise ValueError(target_kind)
    target_col = f"{ticker}_{target_kind}_{horizon}d"
    back_col = f"{ticker}_{target_kind}_back_{horizon}d_lag1"
    target = forward_sum(target_source, horizon).rename(target_col)
    back = backward_sum(target_source, horizon).rename(back_col)
    data = pd.concat([target, back, features.reindex(returns.index)], axis=1)
    return data, back_col


def target_panel_for_spread(
    name: str,
    spread: pd.Series,
    features: pd.DataFrame,
    horizon: int,
) -> tuple[pd.DataFrame, str, str]:
    chg_bp = spread.diff() * 100.0
    target_col = f"{name}_spread_change_var_{horizon}d"
    back_col = f"{name}_spread_change_var_back_{horizon}d_lag1"
    target = forward_sum(chg_bp.pow(2), horizon).rename(target_col)
    back = backward_sum(chg_bp.pow(2), horizon).rename(back_col)
    data = pd.concat([target, back, features.reindex(spread.index)], axis=1)
    return data, target_col, back_col


def plot_bei_vol(features: pd.DataFrame) -> str:
    fig_path = FIG_DIR / "bei_vol_timeseries.png"
    fig, ax = plt.subplots(figsize=(10, 4.8))
    raw = features[["bei_vol21_avg_lag1", "bei_vol63_avg_lag1"]].dropna()
    raw.loc["2005":].plot(ax=ax, linewidth=1.0)
    ax.set_title("Lagged realized breakeven-inflation volatility")
    ax.set_ylabel("Daily BEI change std. dev. (bp)")
    ax.set_xlabel("")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)
    return str(fig_path.relative_to(OUT_DIR))


def plot_dm(summary_rows: list[dict[str, object]]) -> str:
    fig_path = FIG_DIR / "oos_qlike_dm_tstats.png"
    rows = [r for r in summary_rows if r.get("status") == "ok"]
    labels = [
        f"{r['asset']} {r['target_kind']} {r['horizon']}d"
        for r in rows
    ]
    vals = [float(r["qlike_dm_t"]) for r in rows]
    fig_h = max(5.0, 0.28 * len(labels))
    fig, ax = plt.subplots(figsize=(10, fig_h))
    y = np.arange(len(labels))
    colors = ["#2f7d59" if v > 0 else "#b24b4b" for v in vals]
    ax.barh(y, vals, color=colors, alpha=0.82)
    ax.axvline(0.0, color="#222222", linewidth=0.8)
    ax.axvline(3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.axvline(-3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("HAC/DM t-statistic, QLIKE loss: baseline minus BEI-vol augmented")
    ax.set_title("Out-of-sample forecast comparison")
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

    fred = {sid: fred_csv(sid) for sid in FRED_SERIES}
    prices = {ticker: download_yfinance_series(ticker) for ticker in ETF_TICKERS}
    close = pd.concat(prices, axis=1).sort_index()
    returns = np.log(close[CORPORATE_ETFS + ["SPY"]]).diff()
    features = build_features(fred, prices)

    summary_rows: list[dict[str, object]] = []
    detailed: dict[str, object] = {}

    for ticker in CORPORATE_ETFS:
        for horizon in HORIZONS:
            for target_kind in ["future_rv", "future_downside_var"]:
                data, back_col = target_panel_for_etf(
                    ticker, returns[ticker].dropna(), features, horizon, target_kind
                )
                target_col = f"{ticker}_{target_kind}_{horizon}d"
                base_cols = [back_col] + BASE_STATIC_COLS
                aug_cols = base_cols + VOL_COLS
                pred, meta = expanding_oos(
                    data=data,
                    target_col=target_col,
                    base_cols=base_cols,
                    aug_cols=aug_cols,
                    horizon=horizon,
                    min_train=756,
                )
                eval_result = evaluate_prediction(pred, horizon)
                coeffs = hac_coefficients(data, target_col, aug_cols, horizon)
                key = f"{ticker}_{target_kind}_{horizon}d"
                detailed[key] = {
                    "meta": meta,
                    "eval": eval_result,
                    "vol_term_hac_coefficients": coeffs,
                    "base_columns": base_cols,
                    "augmented_columns": aug_cols,
                }
                if eval_result.get("status") == "ok":
                    qdm = eval_result["qlike_dm"]
                    mdm = eval_result["mse_dm"]
                    summary_rows.append(
                        {
                            "asset": ticker,
                            "target_kind": target_kind,
                            "horizon": horizon,
                            "status": "ok",
                            "oos_rows": meta["oos_rows"],
                            "first_oos_date": meta["first_oos_date"],
                            "last_oos_date": meta["last_oos_date"],
                            "qlike_base": eval_result["qlike_base"],
                            "qlike_aug": eval_result["qlike_aug"],
                            "qlike_improvement_pct": eval_result["qlike_improvement_pct"],
                            "qlike_dm_t": qdm["t"],
                            "qlike_dm_mean": qdm["mean"],
                            "mse_improvement_pct": eval_result["mse_improvement_pct"],
                            "mse_dm_t": mdm["t"],
                        }
                    )
                else:
                    summary_rows.append(
                        {
                            "asset": ticker,
                            "target_kind": target_kind,
                            "horizon": horizon,
                            "status": eval_result.get("status", "skipped"),
                            "skip_meta": meta,
                        }
                    )

    spread_map = {
        "HY_OAS": fred["BAMLH0A0HYM2"],
        "IG_OAS": fred["BAMLC0A0CM"],
    }
    for name, spread in spread_map.items():
        for horizon in HORIZONS:
            data, target_col, back_col = target_panel_for_spread(name, spread, features, horizon)
            base_cols = [back_col] + BASE_STATIC_COLS
            aug_cols = base_cols + VOL_COLS
            pred, meta = expanding_oos(
                data=data,
                target_col=target_col,
                base_cols=base_cols,
                aug_cols=aug_cols,
                horizon=horizon,
                min_train=252,
            )
            eval_result = evaluate_prediction(pred, horizon)
            coeffs = hac_coefficients(data, target_col, aug_cols, horizon)
            key = f"{name}_spread_change_var_{horizon}d"
            detailed[key] = {
                "meta": meta,
                "eval": eval_result,
                "vol_term_hac_coefficients": coeffs,
                "base_columns": base_cols,
                "augmented_columns": aug_cols,
            }
            if eval_result.get("status") == "ok":
                qdm = eval_result["qlike_dm"]
                mdm = eval_result["mse_dm"]
                summary_rows.append(
                    {
                        "asset": name,
                        "target_kind": "spread_change_var",
                        "horizon": horizon,
                        "status": "ok",
                        "oos_rows": meta["oos_rows"],
                        "first_oos_date": meta["first_oos_date"],
                        "last_oos_date": meta["last_oos_date"],
                        "qlike_base": eval_result["qlike_base"],
                        "qlike_aug": eval_result["qlike_aug"],
                        "qlike_improvement_pct": eval_result["qlike_improvement_pct"],
                        "qlike_dm_t": qdm["t"],
                        "qlike_dm_mean": qdm["mean"],
                        "mse_improvement_pct": eval_result["mse_improvement_pct"],
                        "mse_dm_t": mdm["t"],
                    }
                )
            else:
                summary_rows.append(
                    {
                        "asset": name,
                        "target_kind": "spread_change_var",
                        "horizon": horizon,
                        "status": eval_result.get("status", "skipped"),
                        "skip_meta": meta,
                    }
                )

    ok_rows = [r for r in summary_rows if r.get("status") == "ok"]
    positive_harvey = [
        r
        for r in ok_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) > 3.0
        and float(r["qlike_improvement_pct"]) > 0.0
    ]
    negative_harvey = [
        r
        for r in ok_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) < -3.0
        and float(r["qlike_improvement_pct"]) < 0.0
    ]
    median_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in ok_rows]).median())
    mean_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in ok_rows]).mean())

    if positive_harvey and median_improvement > 0:
        verdict = "mixed_positive"
        conclusion = (
            "Lagged breakeven volatility has some Harvey-significant positive "
            "OOS QLIKE cells, but the result should be scoped by target and horizon."
        )
    else:
        verdict = "null_or_mixed_negative"
        conclusion = (
            "Lagged breakeven volatility does not provide a robust cross-target "
            "OOS QLIKE improvement once BEI levels, BEI changes, VIX, SPY risk, "
            "and the target's own lagged variance are controlled."
        )

    figures = {
        "bei_vol_timeseries": plot_bei_vol(features),
        "oos_qlike_dm_tstats": plot_dm(summary_rows),
    }

    result = {
        "experiment_id": EXPERIMENT_ID,
        "run_timestamp_local": datetime.now().astimezone().isoformat(),
        "data_sources": {
            "fred": {
                sid: {
                    "description": desc,
                    "first_date": fred[sid].index.min().date().isoformat(),
                    "last_date": fred[sid].index.max().date().isoformat(),
                    "n": int(fred[sid].shape[0]),
                    "url": f"https://fred.stlouisfed.org/series/{sid}",
                }
                for sid, desc in FRED_SERIES.items()
            },
            "yfinance": {
                ticker: {
                    "first_date": prices[ticker].index.min().date().isoformat(),
                    "last_date": prices[ticker].index.max().date().isoformat(),
                    "n": int(prices[ticker].shape[0]),
                }
                for ticker in ETF_TICKERS
            },
        },
        "literature_checked": [
            {
                "title": "Inflation Volatility Risk and the Cross-section of Corporate Bond Returns",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3883556",
                "role": "corporate-bond inflation-volatility risk motivation",
            },
            {
                "title": "Inflation Risk in Corporate Bonds",
                "url": "https://cpflueger.github.io/carolinpflueger_repository/KangPfluegerInflRisk20130918.pdf",
                "role": "corporate-bond inflation-risk pricing background",
            },
            {
                "title": "FRED T5YIE and T10YIE breakeven inflation series",
                "url": "https://fred.stlouisfed.org/series/T5YIE",
                "role": "public daily breakeven source",
            },
        ],
        "design": {
            "feature_lag_rule": "All non-target features are shifted by one trading day via raw.shift(1).",
            "target_alignment": "Target at date t is the forward sum over t..t+h-1; OOS training at forecast date t excludes rows whose target window ends after t-1.",
            "baseline_model": "log target OLS with own lagged target variance, BEI levels/changes, VIX, VIX change, and SPY 22d realized variance.",
            "augmented_model": "baseline plus 21d/63d average and curve-slope realized volatility of T5YIE/T10YIE daily changes.",
            "loss": "QLIKE(actual, predicted) = actual/predicted - log(actual/predicted) - 1; positive DM diff means augmented model has lower loss.",
            "formal_test": "HAC/DM test on baseline loss minus augmented loss; Harvey-style practical threshold |t| > 3.",
        },
        "summary": {
            "n_ok_cells": int(len(ok_rows)),
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
            "FRED corporate OAS CSV endpoints available in this session only returned 2023-06-26 onward, so spread-variance tests are short-sample diagnostics.",
            "ETF results use adjusted-close yfinance data, not intraday or option-implied volatility.",
            "Overlapping future targets require HAC inference; cell-level positives are not interpreted as a broad strategy edge without cross-target robustness.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "summary_table.csv", index=False)
    print(json.dumps(json_safe(result["summary"]), indent=2))


if __name__ == "__main__":
    main()
