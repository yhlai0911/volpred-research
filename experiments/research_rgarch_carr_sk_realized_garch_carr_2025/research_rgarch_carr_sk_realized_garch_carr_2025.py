#!/usr/bin/env python3
"""Daily proxy gate for the RGARCH-CARR-SK backlog item.

The 2025 RGARCH-CARR-SK paper is a high-frequency model: Realized GARCH plus a
CARR/range channel and dynamic higher moments. This script does not claim to
replicate that model. It tests a lower-cost prerequisite:

    Do lagged daily range proxies and rolling realized skew/kurtosis add
    out-of-sample QLIKE value beyond calibrated HAR baselines on public OHLC?

If this proxy gate is null, the result argues against spending hourly-loop
capacity on a full implementation before a longer 5-minute realized-volatility
panel is available.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "research_rgarch_carr_sk_realized_garch_carr_2025"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = OUT_DIR / "data"
PRICE_CACHE = DATA_DIR / "ohlc_yfinance.csv"
OUT_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_qlike_diff.png"

SEED = 42
DATA_START = "2010-01-01"
DATA_END_EXCLUSIVE = "2026-07-02"
OOS_START = pd.Timestamp("2019-01-02")
EPS = 1.0e-10
BOOTSTRAP_REPS = 1000
ALPHA_GRID = [0.1, 1.0, 5.0, 20.0, 100.0, 500.0]

TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "HYG", "EEM", "USO"]

HAR_FEATURES = ["log_rv_lag1", "log_rv_lag5", "log_rv_lag22"]
RANGE_FEATURES = [
    "log_yz_lag1",
    "log_yz_lag5",
    "log_yz_lag22",
    "log_parkinson_lag1",
    "log_parkinson_lag5",
    "log_parkinson_lag22",
]
SK_FEATURES = [
    "skew_22_lag1",
    "kurt_22_lag1",
    "skew_63_lag1",
    "kurt_63_lag1",
    "neg_semivar_22_lag1",
    "pos_semivar_22_lag1",
]
ASYM_FEATURES = ["ret_lag1", "abs_ret_lag1", "neg_ret_lag1"]

MODEL_FEATURES = {
    "har_rv": HAR_FEATURES,
    "har_rv_asym": HAR_FEATURES + ASYM_FEATURES,
    "har_range": HAR_FEATURES + RANGE_FEATURES,
    "har_sk": HAR_FEATURES + SK_FEATURES,
    "rgarch_carr_sk_proxy": HAR_FEATURES + RANGE_FEATURES + SK_FEATURES + ASYM_FEATURES,
}
TRADITIONAL_BASELINE_CANDIDATES = ["naive_har22", "har_rv", "har_rv_asym", "har_range", "har_sk"]


@dataclass(frozen=True)
class AssetResult:
    ticker: str
    train_start: str
    train_end: str
    oos_start: str
    oos_end: str
    train_rows: int
    oos_rows: int
    qlike: dict[str, float]
    calibration_factors: dict[str, float]
    selected_alphas: dict[str, float]
    dm_vs_primary: dict[str, dict[str, float]]
    dm_vs_har_range: dict[str, dict[str, float]]
    feature_correlations: dict[str, float]


def download_ohlc(refresh: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PRICE_CACHE.exists() and not refresh:
        cached = pd.read_csv(
            PRICE_CACHE,
            header=[0, 1],
            index_col=0,
            skiprows=[2],
            parse_dates=True,
        ).sort_index()
        cached.index.name = "Date"
        return cached

    import yfinance as yf

    raw = yf.download(
        TICKERS,
        start=DATA_START,
        end=DATA_END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty dataframe")

    keep = [field for field in ["Open", "High", "Low", "Close"] if field in raw.columns.get_level_values(0)]
    if not keep:
        raise RuntimeError(f"Cannot locate OHLC fields in yfinance output: {raw.columns}")
    ohlc = raw[keep].copy().sort_index()
    ohlc.to_csv(PRICE_CACHE, index_label="Date")
    return ohlc


def extract_asset(ohlc: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if ticker not in ohlc.columns.get_level_values(1):
        raise KeyError(f"{ticker} missing from OHLC cache")
    out = pd.DataFrame(
        {
            "open": ohlc[("Open", ticker)],
            "high": ohlc[("High", ticker)],
            "low": ohlc[("Low", ticker)],
            "close": ohlc[("Close", ticker)],
        }
    )
    return out.dropna().astype(float).sort_index()


def rolling_semivar(ret: pd.Series, window: int, positive: bool) -> pd.Series:
    if positive:
        values = ret.where(ret > 0.0, 0.0).pow(2)
    else:
        values = ret.where(ret < 0.0, 0.0).pow(2)
    return values.rolling(window).mean()


def make_feature_frame(asset: pd.DataFrame) -> pd.DataFrame:
    px = asset["close"]
    ret = np.log(px / px.shift(1))
    rv = ret.pow(2).clip(lower=EPS)

    log_hl = np.log(asset["high"] / asset["low"]).replace([np.inf, -np.inf], np.nan)
    log_co = np.log(asset["close"] / asset["open"]).replace([np.inf, -np.inf], np.nan)
    log_oc = np.log(asset["open"] / asset["close"].shift(1)).replace([np.inf, -np.inf], np.nan)
    parkinson = (log_hl.pow(2) / (4.0 * math.log(2.0))).clip(lower=EPS)
    garman_klass = (0.5 * log_hl.pow(2) - (2.0 * math.log(2.0) - 1.0) * log_co.pow(2)).clip(lower=EPS)
    yz_style = (log_oc.pow(2) + garman_klass).clip(lower=EPS)

    out = pd.DataFrame(index=asset.index)
    out["ret"] = ret
    out["rv"] = rv
    out["log_rv"] = np.log(rv + EPS)
    out["naive_har22"] = rv.rolling(22).mean().shift(1).clip(lower=EPS)

    # Every model feature is explicitly lagged through t-1.
    out["log_rv_lag1"] = np.log(rv.shift(1) + EPS)
    out["log_rv_lag5"] = np.log(rv.rolling(5).mean().shift(1) + EPS)
    out["log_rv_lag22"] = np.log(rv.rolling(22).mean().shift(1) + EPS)
    out["log_parkinson_lag1"] = np.log(parkinson.shift(1) + EPS)
    out["log_parkinson_lag5"] = np.log(parkinson.rolling(5).mean().shift(1) + EPS)
    out["log_parkinson_lag22"] = np.log(parkinson.rolling(22).mean().shift(1) + EPS)
    out["log_yz_lag1"] = np.log(yz_style.shift(1) + EPS)
    out["log_yz_lag5"] = np.log(yz_style.rolling(5).mean().shift(1) + EPS)
    out["log_yz_lag22"] = np.log(yz_style.rolling(22).mean().shift(1) + EPS)
    out["ret_lag1"] = ret.shift(1)
    out["abs_ret_lag1"] = ret.abs().shift(1)
    out["neg_ret_lag1"] = (-ret.clip(upper=0.0)).shift(1)
    out["skew_22_lag1"] = ret.rolling(22).skew().shift(1)
    out["kurt_22_lag1"] = ret.rolling(22).kurt().shift(1)
    out["skew_63_lag1"] = ret.rolling(63).skew().shift(1)
    out["kurt_63_lag1"] = ret.rolling(63).kurt().shift(1)
    out["neg_semivar_22_lag1"] = rolling_semivar(ret, 22, positive=False).shift(1)
    out["pos_semivar_22_lag1"] = rolling_semivar(ret, 22, positive=True).shift(1)
    out["target_log_rv"] = out["log_rv"]
    out["date"] = out.index

    required = sorted(set(sum(MODEL_FEATURES.values(), [])) | {"rv", "target_log_rv", "naive_har22"})
    valid = out[required].notna().all(axis=1)
    return out.loc[valid].reset_index(drop=True)


def standardize(panel: pd.DataFrame, features: list[str], train_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = panel[features].astype(float).to_numpy()
    mean = x[train_mask].mean(axis=0)
    sd = x[train_mask].std(axis=0)
    sd = np.where(sd < 1.0e-12, 1.0, sd)
    return (x - mean) / sd, mean, sd


def fit_log_ridge(panel: pd.DataFrame, features: list[str], train_mask: np.ndarray) -> tuple[np.ndarray, float]:
    x_std, _, _ = standardize(panel, features, train_mask)
    y = panel["target_log_rv"].astype(float).to_numpy()
    actual = panel["rv"].astype(float).to_numpy()

    train_idx = np.flatnonzero(train_mask)
    split = int(len(train_idx) * 0.8)
    fit_idx = train_idx[:split]
    val_idx = train_idx[split:]
    best_alpha = ALPHA_GRID[0]
    best_loss = float("inf")
    if len(fit_idx) >= 200 and len(val_idx) >= 100:
        fit_mask = np.zeros(len(panel), dtype=bool)
        val_mask = np.zeros(len(panel), dtype=bool)
        fit_mask[fit_idx] = True
        val_mask[val_idx] = True
        for alpha in ALPHA_GRID:
            trial = Ridge(alpha=alpha)
            trial.fit(x_std[fit_mask], y[fit_mask])
            pred_log = trial.predict(x_std)
            pred = np.exp(np.clip(pred_log, np.log(EPS), np.log(0.25)))
            pred, _ = qlike_scalar_calibrate(actual, pred, fit_mask)
            loss = qlike(actual[val_mask], pred[val_mask])
            if math.isfinite(loss) and loss < best_loss:
                best_loss = loss
                best_alpha = alpha

    model = Ridge(alpha=best_alpha)
    model.fit(x_std[train_mask], y[train_mask])
    pred_log = model.predict(x_std)
    return np.exp(np.clip(pred_log, np.log(EPS), np.log(0.25))), best_alpha


def qlike_scalar_calibrate(actual: np.ndarray, predicted: np.ndarray, train_mask: np.ndarray) -> tuple[np.ndarray, float]:
    pred = np.maximum(np.asarray(predicted, dtype=float), EPS)
    actual = np.maximum(np.asarray(actual, dtype=float), EPS)
    valid = train_mask & np.isfinite(pred) & np.isfinite(actual) & (pred > 0)
    if valid.sum() < 50:
        return pred, 1.0
    factor = float(np.mean(actual[valid] / pred[valid]))
    if not math.isfinite(factor):
        factor = 1.0
    factor = float(np.clip(factor, 0.02, 50.0))
    return np.maximum(pred * factor, EPS), factor


def safe_corr(a: pd.Series, b: pd.Series) -> float:
    valid = a.notna() & b.notna()
    if int(valid.sum()) < 50:
        return float("nan")
    return float(a.loc[valid].corr(b.loc[valid]))


def asset_backtest(ticker: str, asset: pd.DataFrame, primary_baseline: str) -> AssetResult:
    panel = make_feature_frame(asset)
    train_mask = (panel["date"] < OOS_START).to_numpy()
    oos_mask = (panel["date"] >= OOS_START).to_numpy()
    if train_mask.sum() < 750 or oos_mask.sum() < 252:
        raise RuntimeError(f"{ticker}: insufficient train/OOS rows")

    actual = panel["rv"].astype(float).to_numpy()
    predictions: dict[str, np.ndarray] = {"naive_har22": panel["naive_har22"].astype(float).to_numpy()}
    selected_alphas: dict[str, float] = {}
    for model_name, features in MODEL_FEATURES.items():
        predictions[model_name], selected_alphas[model_name] = fit_log_ridge(panel, features, train_mask)

    calibration_factors: dict[str, float] = {}
    for name, pred in list(predictions.items()):
        calibrated, factor = qlike_scalar_calibrate(actual, pred, train_mask)
        predictions[name] = calibrated
        calibration_factors[name] = factor

    qlike_by_model = {
        name: qlike(actual[oos_mask], pred[oos_mask]) for name, pred in predictions.items()
    }

    primary_loss = qlike_pointwise(actual[oos_mask], predictions[primary_baseline][oos_mask])
    range_loss = qlike_pointwise(actual[oos_mask], predictions["har_range"][oos_mask])
    dm_vs_primary: dict[str, dict[str, float]] = {}
    dm_vs_range: dict[str, dict[str, float]] = {}
    for name, pred in predictions.items():
        if name != primary_baseline:
            loss = qlike_pointwise(actual[oos_mask], pred[oos_mask])
            t_stat, p_val = dm_test(loss, primary_loss, h=1)
            dm_vs_primary[name] = {
                "t": t_stat,
                "p": p_val,
                "mean_loss_diff": float(np.mean(loss - primary_loss)),
            }
        if name != "har_range":
            loss = qlike_pointwise(actual[oos_mask], pred[oos_mask])
            t_stat, p_val = dm_test(loss, range_loss, h=1)
            dm_vs_range[name] = {
                "t": t_stat,
                "p": p_val,
                "mean_loss_diff": float(np.mean(loss - range_loss)),
            }

    feature_correlations = {
        "yz_lag22_vs_rv_nextday": safe_corr(panel["log_yz_lag22"], panel["rv"]),
        "skew22_lag1_vs_rv_nextday": safe_corr(panel["skew_22_lag1"], panel["rv"]),
        "kurt22_lag1_vs_rv_nextday": safe_corr(panel["kurt_22_lag1"], panel["rv"]),
        "neg_semivar22_lag1_vs_rv_nextday": safe_corr(panel["neg_semivar_22_lag1"], panel["rv"]),
    }
    dates = panel.loc[oos_mask, "date"]
    return AssetResult(
        ticker=ticker,
        train_start=pd.Timestamp(panel.loc[train_mask, "date"].min()).strftime("%Y-%m-%d"),
        train_end=pd.Timestamp(panel.loc[train_mask, "date"].max()).strftime("%Y-%m-%d"),
        oos_start=pd.Timestamp(dates.min()).strftime("%Y-%m-%d"),
        oos_end=pd.Timestamp(dates.max()).strftime("%Y-%m-%d"),
        train_rows=int(train_mask.sum()),
        oos_rows=int(oos_mask.sum()),
        qlike=qlike_by_model,
        calibration_factors=calibration_factors,
        selected_alphas=selected_alphas,
        dm_vs_primary=dm_vs_primary,
        dm_vs_har_range=dm_vs_range,
        feature_correlations=feature_correlations,
    )


def choose_primary_baseline(prelim: list[dict[str, float]]) -> str:
    means = {
        model: float(np.mean([row[model] for row in prelim]))
        for model in TRADITIONAL_BASELINE_CANDIDATES
    }
    return min(means, key=lambda model: means[model])


def preliminary_qlike(asset: pd.DataFrame) -> dict[str, float]:
    panel = make_feature_frame(asset)
    train_mask = (panel["date"] < OOS_START).to_numpy()
    oos_mask = (panel["date"] >= OOS_START).to_numpy()
    actual = panel["rv"].astype(float).to_numpy()
    predictions = {"naive_har22": panel["naive_har22"].astype(float).to_numpy()}
    for model_name, features in MODEL_FEATURES.items():
        if model_name in TRADITIONAL_BASELINE_CANDIDATES:
            predictions[model_name], _ = fit_log_ridge(panel, features, train_mask)
    out: dict[str, float] = {}
    for name, pred in predictions.items():
        calibrated, _ = qlike_scalar_calibrate(actual, pred, train_mask)
        out[name] = qlike(actual[oos_mask], calibrated[oos_mask])
    return out


def bootstrap_asset_mean(diffs: np.ndarray, seed: int = SEED) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    boot = np.empty(BOOTSTRAP_REPS, dtype=float)
    for idx in range(BOOTSTRAP_REPS):
        sample = rng.choice(diffs, size=len(diffs), replace=True)
        boot[idx] = float(np.mean(sample))
    return {
        "B": BOOTSTRAP_REPS,
        "seed": seed,
        "n_assets": int(len(diffs)),
        "mean": float(np.mean(diffs)),
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "prob_mean_below_zero": float(np.mean(boot < 0.0)),
    }


def summarize(asset_results: list[AssetResult], primary_baseline: str) -> dict[str, Any]:
    models = list(asset_results[0].qlike.keys())
    panel_means = {
        model: float(np.mean([asset.qlike[model] for asset in asset_results]))
        for model in models
    }
    diff_vs_primary: dict[str, dict[str, Any]] = {}
    for model in models:
        if model == primary_baseline:
            continue
        diffs = np.asarray(
            [asset.qlike[model] - asset.qlike[primary_baseline] for asset in asset_results],
            dtype=float,
        )
        diff_vs_primary[model] = {
            "mean": float(np.mean(diffs)),
            "asset_wins": int(np.sum(diffs < 0.0)),
            "n_assets": int(len(diffs)),
            "bootstrap": bootstrap_asset_mean(diffs),
        }

    full_diff = diff_vs_primary["rgarch_carr_sk_proxy"]
    sk_increment = np.asarray(
        [asset.qlike["rgarch_carr_sk_proxy"] - asset.qlike["har_range"] for asset in asset_results],
        dtype=float,
    )
    if full_diff["mean"] < 0 and full_diff["asset_wins"] >= 5 and full_diff["bootstrap"]["ci95"][1] < 0:
        verdict = "PASS_PROXY_GATE"
    elif full_diff["mean"] < 0:
        verdict = "MIXED_WEAK_PROXY_GATE"
    else:
        verdict = "NULL_VS_PRIMARY_BASELINE"

    return {
        "primary_baseline": primary_baseline,
        "panel_qlike_means": panel_means,
        "diff_vs_primary_baseline": diff_vs_primary,
        "sk_increment_vs_har_range": {
            "mean": float(np.mean(sk_increment)),
            "asset_wins": int(np.sum(sk_increment < 0.0)),
            "n_assets": int(len(sk_increment)),
            "bootstrap": bootstrap_asset_mean(sk_increment),
        },
        "verdict": verdict,
    }


def make_figure(asset_results: list[AssetResult], summary: dict[str, Any]) -> None:
    primary = summary["primary_baseline"]
    models = ["naive_har22", "har_rv", "har_range", "har_sk", "rgarch_carr_sk_proxy"]
    labels = {
        "naive_har22": "Naive HAR22",
        "har_rv": "HAR RV",
        "har_range": "HAR + range",
        "har_sk": "HAR + SK",
        "rgarch_carr_sk_proxy": "Range + SK proxy",
    }

    fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
    means = summary["panel_qlike_means"]
    rel = {
        model: 100.0 * (means[primary] - means[model]) / abs(means[primary])
        for model in models
    }
    axes[0].bar([labels[m] for m in models], [rel[m] for m in models], color=["#2f7d57" if rel[m] > 0 else "#a33f3f" for m in models])
    axes[0].axhline(0, color="black", linewidth=0.9)
    axes[0].set_ylabel("Panel QLIKE improvement vs primary baseline (%)")
    axes[0].set_title(f"Primary baseline: {primary}")
    axes[0].tick_params(axis="x", rotation=25)

    tickers = [asset.ticker for asset in asset_results]
    full_diff = [
        100.0
        * (asset.qlike[primary] - asset.qlike["rgarch_carr_sk_proxy"])
        / abs(asset.qlike[primary])
        for asset in asset_results
    ]
    axes[1].bar(tickers, full_diff, color=["#2f7d57" if value > 0 else "#a33f3f" for value in full_diff])
    axes[1].axhline(0, color="black", linewidth=0.9)
    axes[1].set_ylabel("Full proxy improvement vs primary baseline (%)")
    axes[1].set_title("Asset-level range + SK proxy")
    axes[1].tick_params(axis="x", rotation=20)

    fig.suptitle("RGARCH-CARR-SK daily OHLC proxy gate", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    np.random.seed(SEED)
    ohlc = download_ohlc(refresh=refresh)
    assets: dict[str, pd.DataFrame] = {}
    skipped: dict[str, str] = {}
    for ticker in TICKERS:
        try:
            assets[ticker] = extract_asset(ohlc, ticker)
        except Exception as exc:
            skipped[ticker] = repr(exc)

    prelim = []
    for ticker, asset in assets.items():
        try:
            prelim.append(preliminary_qlike(asset))
        except Exception as exc:
            skipped[ticker] = repr(exc)
    if not prelim:
        raise RuntimeError("No assets passed preliminary baseline selection")

    primary_baseline = choose_primary_baseline(prelim)
    asset_results: list[AssetResult] = []
    for ticker, asset in assets.items():
        if ticker in skipped:
            continue
        try:
            asset_results.append(asset_backtest(ticker, asset, primary_baseline))
        except Exception as exc:
            skipped[ticker] = repr(exc)
    if not asset_results:
        raise RuntimeError("No assets completed")

    summary = summarize(asset_results, primary_baseline)
    make_figure(asset_results, summary)

    full = summary["diff_vs_primary_baseline"]["rgarch_carr_sk_proxy"]
    sk_increment = summary["sk_increment_vs_har_range"]
    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "verdict": summary["verdict"],
        "seed": SEED,
        "hypothesis": (
            "Daily OHLC range proxies plus rolling realized skew/kurtosis should improve "
            "one-day-ahead variance forecasts beyond the best calibrated traditional HAR-style baseline "
            "if the RGARCH-CARR-SK information channels are visible in free daily data."
        ),
        "literature_checked": [
            "Liu, Zhou, and Chen (2025), A RGARCH-CARR-SK model: A new high-frequency volatility forecasting and risk measurement model based on dynamic higher moments and generalized realized measures, North American Journal of Economics and Finance.",
            "Hansen, Huang, and Shek (2012), Realized GARCH: a joint model for returns and realized measures of volatility, Journal of Applied Econometrics.",
            "Xu and Wu (2025), Real-time GARCH@CARR: A joint model of returns, realized measure of volatility and current intraday information, North American Journal of Economics and Finance.",
            "Corsi (2009), A simple approximate long-memory model of realized volatility, Journal of Financial Econometrics.",
        ],
        "data": {
            "source": "yfinance adjusted daily OHLC, auto_adjust=True",
            "download_start": DATA_START,
            "download_end_exclusive": DATA_END_EXCLUSIVE,
            "tickers": TICKERS,
            "data_cache": str(PRICE_CACHE.relative_to(ROOT)),
            "coverage": {
                ticker: {
                    "first": pd.Timestamp(asset.index.min()).strftime("%Y-%m-%d"),
                    "last": pd.Timestamp(asset.index.max()).strftime("%Y-%m-%d"),
                    "n_rows": int(asset.shape[0]),
                }
                for ticker, asset in assets.items()
            },
            "skipped": skipped,
        },
        "method": {
            "scope": "Daily OHLC proxy gate, not a full high-frequency RGARCH-CARR-SK replication.",
            "target": "same-day close-to-close squared log return r_t^2; all predictors lagged through t-1.",
            "range_channel": "lagged Parkinson and Yang-Zhang-style overnight-adjusted range variance lags.",
            "higher_moment_channel": "lagged rolling 22d/63d daily-return skewness and excess kurtosis plus downside/upside semivariance.",
            "lookahead_guard": "features use shift(1) or rolling(...).shift(1); training and calibration rows date < 2019-01-02; OOS rows date >= 2019-01-02.",
            "models": {
                "naive_har22": "22-day lagged rolling mean variance",
                "har_rv": "Ridge on daily/weekly/monthly lagged log r^2",
                "har_rv_asym": "HAR plus lagged return/asymmetry",
                "har_range": "HAR plus lagged daily range proxies, CARR-lite channel",
                "har_sk": "HAR plus rolling skew/kurtosis and semivariance",
                "rgarch_carr_sk_proxy": "HAR plus range, skew/kurtosis, semivariance, and asymmetry features",
            },
            "evaluation": "Patton QLIKE on r^2 after train-only scalar QLIKE calibration for every model; primary gate baseline is best calibrated traditional model; DM-HAC via volpred.stats.model_evaluation.dm_test; asset bootstrap B=1000 seed=42.",
            "ridge_alpha_selection": f"Each Ridge model selects alpha from {ALPHA_GRID} using the last 20% of the training window as a chronological validation set.",
        },
        "summary": summary,
        "assets": [asset.__dict__ for asset in asset_results],
        "main_findings": [
            f"Full range+SK proxy mean QLIKE diff vs {primary_baseline} = {full['mean']:.6g}, wins {full['asset_wins']}/{full['n_assets']}, bootstrap CI [{full['bootstrap']['ci95'][0]:.6g}, {full['bootstrap']['ci95'][1]:.6g}].",
            f"SK increment over HAR+range mean diff = {sk_increment['mean']:.6g}, wins {sk_increment['asset_wins']}/{sk_increment['n_assets']}, bootstrap CI [{sk_increment['bootstrap']['ci95'][0]:.6g}, {sk_increment['bootstrap']['ci95'][1]:.6g}].",
            "All predictors are lagged; no OOS target labels are used in fitting or calibration.",
        ],
        "limitations": [
            "No high-frequency realized variance, realized skewness, or realized kurtosis is used.",
            "The CARR component is represented by lagged daily range proxies, not a full CARR likelihood.",
            "The SK component uses rolling daily-return moments, which are weaker than intraday realized higher moments.",
            "This gate cannot refute the 2025 RGARCH-CARR-SK paper; it only tests whether a cheap daily proxy justifies immediate implementation.",
        ],
        "figure": str(FIG_PATH.relative_to(ROOT)),
    }

    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance OHLC")
    args = parser.parse_args()
    result = run(refresh=args.refresh)
    print(
        json.dumps(
            {
                "experiment_id": result["experiment_id"],
                "verdict": result["verdict"],
                "assets_completed": len(result["assets"]),
                "primary_baseline": result["summary"]["primary_baseline"],
                "panel_qlike_means": result["summary"]["panel_qlike_means"],
                "results": str(OUT_PATH.relative_to(ROOT)),
                "figure": str(FIG_PATH.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
