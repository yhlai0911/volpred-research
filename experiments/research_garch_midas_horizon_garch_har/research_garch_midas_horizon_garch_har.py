#!/usr/bin/env python3
"""GARCH/MIDAS long-horizon variance forecast comparison.

This experiment asks whether an RV-driven MIDAS long-run component helps at
22- and 66-trading-day horizons relative to single-component GARCH and HAR
baselines. It is intentionally a daily-data, horizon-specific forecasting test,
not a full Engle-Ghysels-Sohn GARCH-MIDAS MLE replication.
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "research_garch_midas_horizon_garch_har"
SEED = 42
ASSETS = ["SPY", "QQQ", "GLD"]
DATA_START = "2005-01-01"
DATA_END = "2026-07-04"
OOS_START = "2015-01-01"
HORIZONS = [22, 66]
MIN_TRAIN = 1000
GARCH_WINDOW = 1500
GARCH_REFIT_EVERY = 63
MIDAS_BLOCK_DAYS = 22
MIDAS_BLOCKS = 12
MIDAS_OMEGA = 2.0
RIDGE = 1e-8
FLOOR = 1e-12

RESULTS_PATH = SCRIPT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = SCRIPT_DIR / "midas_horizon_qlike_improvement.png"

warnings.filterwarnings("ignore")
np.random.seed(SEED)


@dataclass
class AssetData:
    ticker: str
    frame: pd.DataFrame
    garch_h1: np.ndarray
    garch_params: dict[str, np.ndarray]
    garch_fit_failures: int
    garch_fallback_uses: int


def beta_weights(k: int, omega: float) -> np.ndarray:
    idx = np.arange(1, k + 1, dtype=float)
    raw = np.maximum(1.0 - idx / (k + 1.0), 1e-10) ** (omega - 1.0)
    return raw / raw.sum()


MIDAS_WEIGHTS = beta_weights(MIDAS_BLOCKS, MIDAS_OMEGA)


def download_asset(ticker: str) -> pd.DataFrame:
    print(f"[data] downloading {ticker} {DATA_START}..{DATA_END}", flush=True)
    raw = yf.download(
        ticker,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"No yfinance data returned for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Close"])
    df["ret"] = np.log(df["Close"] / df["Close"].shift(1))
    df["r2"] = df["ret"] ** 2
    df = df.dropna(subset=["ret", "r2"]).copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    return df


def rolling_midas_rv(r2: np.ndarray) -> np.ndarray:
    out = np.full(len(r2), np.nan)
    for t in range(len(r2)):
        values = []
        for block in range(MIDAS_BLOCKS):
            end = t - block * MIDAS_BLOCK_DAYS + 1
            start = end - MIDAS_BLOCK_DAYS
            if start < 0:
                values = []
                break
            values.append(float(np.nanmean(r2[start:end])))
        if len(values) == MIDAS_BLOCKS and np.all(np.isfinite(values)):
            out[t] = float(np.dot(MIDAS_WEIGHTS, np.asarray(values)))
    return np.maximum(out, FLOOR)


def forward_avg_variance(r2: np.ndarray, horizon: int) -> np.ndarray:
    target = np.full(len(r2), np.nan)
    for t in range(len(r2) - horizon):
        window = r2[t + 1 : t + horizon + 1]
        if len(window) == horizon and np.all(np.isfinite(window)):
            target[t] = float(np.mean(window))
    return np.maximum(target, FLOOR)


def garch_multi_step_average(h1: float, omega: float, alpha: float, beta: float, horizon: int) -> float:
    if not np.isfinite(h1) or h1 <= 0:
        return np.nan
    rho = alpha + beta
    if rho >= 0.999:
        rho = 0.999
    vals = [h1]
    h_prev = h1
    for _ in range(1, horizon):
        h_prev = omega + rho * h_prev
        vals.append(h_prev)
    return float(np.mean(vals))


def rolling_garch_forecast(ret: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray], int, int]:
    n = len(ret)
    h1 = np.full(n, np.nan)
    omega_arr = np.full(n, np.nan)
    alpha_arr = np.full(n, np.nan)
    beta_arr = np.full(n, np.nan)
    fit_failures = 0
    fallback_uses = 0
    params: tuple[float, float, float] | None = None

    for i in range(MIN_TRAIN, n - 1):
        need_refit = params is None or (i - MIN_TRAIN) % GARCH_REFIT_EVERY == 0
        if need_refit:
            start = max(0, i + 1 - GARCH_WINDOW)
            train = ret[start : i + 1]
            train = train[np.isfinite(train)]
            try:
                model = arch_model(
                    train * 100.0,
                    mean="Zero",
                    vol="GARCH",
                    p=1,
                    q=1,
                    dist="normal",
                    rescale=False,
                )
                res = model.fit(disp="off", show_warning=False)
                p = res.params
                omega = float(p["omega"]) / 10000.0
                alpha = float(p["alpha[1]"])
                beta = float(p["beta[1]"])
                fc = float(res.forecast(horizon=1, reindex=False).variance.iloc[-1, 0]) / 10000.0
                params = (omega, alpha, beta)
                h1[i] = max(fc, FLOOR)
            except Exception as exc:  # keep observable; never silent.
                fit_failures += 1
                print(f"[garch] WARN fit failed at i={i}: {type(exc).__name__}: {exc}", file=sys.stderr)
                if params is not None and np.isfinite(h1[i - 1]):
                    omega, alpha, beta = params
                    h1[i] = max(omega + alpha * ret[i] ** 2 + beta * h1[i - 1], FLOOR)
                    fallback_uses += 1
                else:
                    continue
        else:
            assert params is not None
            omega, alpha, beta = params
            if np.isfinite(h1[i - 1]):
                h1[i] = max(omega + alpha * ret[i] ** 2 + beta * h1[i - 1], FLOOR)
            else:
                h1[i] = np.nan

        if params is not None:
            omega_arr[i], alpha_arr[i], beta_arr[i] = params

    return h1, {"omega": omega_arr, "alpha": alpha_arr, "beta": beta_arr}, fit_failures, fallback_uses


def prepare_asset(ticker: str) -> AssetData:
    df = download_asset(ticker)
    r2 = df["r2"].to_numpy()
    df["rv5"] = pd.Series(r2, index=df.index).rolling(5).mean()
    df["rv22"] = pd.Series(r2, index=df.index).rolling(22).mean()
    df["midas12"] = rolling_midas_rv(r2)
    garch_h1, params, fit_failures, fallback_uses = rolling_garch_forecast(df["ret"].to_numpy())
    df["garch_h1"] = garch_h1
    return AssetData(
        ticker=ticker,
        frame=df,
        garch_h1=garch_h1,
        garch_params=params,
        garch_fit_failures=fit_failures,
        garch_fallback_uses=fallback_uses,
    )


def log_safe(x: np.ndarray) -> np.ndarray:
    return np.log(np.maximum(np.asarray(x, dtype=float), FLOOR))


def fit_predict_log_ols(x_train: np.ndarray, y_train: np.ndarray, x_pred: np.ndarray) -> tuple[float, float]:
    valid = np.isfinite(y_train) & np.all(np.isfinite(x_train), axis=1)
    x = x_train[valid]
    y = y_train[valid]
    if len(y) < 120:
        return np.nan, np.nan
    x_aug = np.column_stack([np.ones(len(x)), x])
    xtx = x_aug.T @ x_aug
    beta = np.linalg.solve(xtx + RIDGE * np.eye(xtx.shape[0]), x_aug.T @ y)
    resid = y - x_aug @ beta
    resid_var = float(np.var(resid, ddof=max(1, x_aug.shape[1])))
    pred_log = float(np.r_[1.0, x_pred] @ beta)
    pred = math.exp(pred_log + 0.5 * resid_var)
    return max(pred, FLOOR), resid_var


def feature_matrices(df: pd.DataFrame, garch_avg: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "GARCH_log": np.column_stack([log_safe(garch_avg)]),
        "HAR": np.column_stack([
            log_safe(df["r2"].to_numpy()),
            log_safe(df["rv5"].to_numpy()),
            log_safe(df["rv22"].to_numpy()),
        ]),
        "Component_MIDAS": np.column_stack([
            log_safe(garch_avg),
            log_safe(df["midas12"].to_numpy()),
        ]),
        "HAR_MIDAS": np.column_stack([
            log_safe(df["r2"].to_numpy()),
            log_safe(df["rv5"].to_numpy()),
            log_safe(df["rv22"].to_numpy()),
            log_safe(df["midas12"].to_numpy()),
        ]),
    }


def forecast_asset_horizon(asset: AssetData, horizon: int) -> pd.DataFrame:
    df = asset.frame.copy()
    r2 = df["r2"].to_numpy()
    target = forward_avg_variance(r2, horizon)
    garch_avg = np.full(len(df), np.nan)
    for i in range(len(df)):
        omega = asset.garch_params["omega"][i]
        alpha = asset.garch_params["alpha"][i]
        beta = asset.garch_params["beta"][i]
        if np.isfinite(omega) and np.isfinite(alpha) and np.isfinite(beta):
            garch_avg[i] = garch_multi_step_average(asset.garch_h1[i], omega, alpha, beta, horizon)
    features = feature_matrices(df, garch_avg)
    y_log = log_safe(target)

    oos_start_idx = int(np.searchsorted(df.index.values, np.datetime64(OOS_START)))
    rows: list[dict[str, Any]] = []
    positions = np.arange(len(df))
    for i in range(max(MIN_TRAIN, oos_start_idx), len(df) - horizon):
        train_mask = (
            np.isfinite(target)
            & (positions + horizon < i)  # target_end < forecast_origin
            & (positions >= MIN_TRAIN)
        )
        if train_mask.sum() < 250:
            continue
        row: dict[str, Any] = {
            "date": df.index[i],
            "position": i,
            "ticker": asset.ticker,
            "horizon": horizon,
            "actual": target[i],
            "GARCH_raw": garch_avg[i],
        }
        for model_name, xmat in features.items():
            x_pred = xmat[i]
            if not np.all(np.isfinite(x_pred)):
                row[model_name] = np.nan
                continue
            pred, _ = fit_predict_log_ols(xmat[train_mask], y_log[train_mask], x_pred)
            row[model_name] = pred
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_forecasts(forecasts: pd.DataFrame) -> dict[str, Any]:
    models = ["GARCH_raw", "GARCH_log", "HAR", "Component_MIDAS", "HAR_MIDAS"]
    out: dict[str, Any] = {"models": models, "by_horizon": {}}
    for horizon in HORIZONS:
        hdf = forecasts[forecasts["horizon"] == horizon].copy()
        hres: dict[str, Any] = {
            "n_forecasts": int(len(hdf)),
            "date_start": str(hdf["date"].min().date()) if len(hdf) else None,
            "date_end": str(hdf["date"].max().date()) if len(hdf) else None,
            "pooled_qlike": {},
            "by_asset": {},
            "dm_tests_pooled_by_date": {},
            "dm_tests_by_asset": {},
        }
        for model in models:
            hres["pooled_qlike"][model] = qlike(hdf["actual"].to_numpy(), hdf[model].to_numpy())
        best = min(hres["pooled_qlike"], key=lambda k: hres["pooled_qlike"][k])
        hres["best_pooled_model"] = best

        for ticker, adf in hdf.groupby("ticker"):
            asset_res = {"n": int(len(adf)), "qlike": {}}
            for model in models:
                asset_res["qlike"][model] = qlike(adf["actual"].to_numpy(), adf[model].to_numpy())
            hres["by_asset"][ticker] = asset_res

        point_losses = {
            model: qlike_pointwise(hdf["actual"].to_numpy(), hdf[model].to_numpy())
            for model in models
        }
        hdf = hdf.reset_index(drop=True)
        for model, losses in point_losses.items():
            hdf[f"loss_{model}"] = losses

        comparisons = [
            ("Component_MIDAS", "GARCH_raw"),
            ("Component_MIDAS", "HAR"),
            ("HAR_MIDAS", "HAR"),
            ("HAR", "GARCH_raw"),
            ("GARCH_log", "GARCH_raw"),
        ]
        for left, right in comparisons:
            # K1355-compliant pooled inference: average loss differential by date.
            diffs = []
            for date, ddf in hdf.groupby("date"):
                d = ddf[f"loss_{left}"].to_numpy() - ddf[f"loss_{right}"].to_numpy()
                d = d[np.isfinite(d)]
                if len(d):
                    diffs.append(float(np.mean(d)))
            if len(diffs) >= 10:
                t_stat, p_value = dm_test(np.asarray(diffs), np.zeros(len(diffs)), h=horizon)
            else:
                t_stat, p_value = (np.nan, np.nan)
            left_q = hres["pooled_qlike"][left]
            right_q = hres["pooled_qlike"][right]
            hres["dm_tests_pooled_by_date"][f"{left}_vs_{right}"] = {
                "t_stat": float(t_stat) if np.isfinite(t_stat) else None,
                "p_value": float(p_value) if np.isfinite(p_value) else None,
                "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > 3.0) if np.isfinite(t_stat) else False,
                "mean_loss_diff": float(np.nanmean(diffs)) if diffs else None,
                "qlike_left": float(left_q) if np.isfinite(left_q) else None,
                "qlike_right": float(right_q) if np.isfinite(right_q) else None,
                "improvement_pct_left_vs_right": float((right_q - left_q) / abs(right_q) * 100.0)
                if np.isfinite(left_q) and np.isfinite(right_q) and right_q != 0
                else None,
                "direction": "left_better" if np.isfinite(t_stat) and t_stat < 0 else "right_better",
                "horizon_for_hac": horizon,
            }

            hres["dm_tests_by_asset"][f"{left}_vs_{right}"] = {}
            for ticker, adf in hdf.groupby("ticker"):
                l1 = adf[f"loss_{left}"].to_numpy()
                l2 = adf[f"loss_{right}"].to_numpy()
                valid = np.isfinite(l1) & np.isfinite(l2)
                if valid.sum() >= 10:
                    t_a, p_a = dm_test(l1[valid], l2[valid], h=horizon)
                else:
                    t_a, p_a = (np.nan, np.nan)
                hres["dm_tests_by_asset"][f"{left}_vs_{right}"][ticker] = {
                    "n": int(valid.sum()),
                    "t_stat": float(t_a) if np.isfinite(t_a) else None,
                    "p_value": float(p_a) if np.isfinite(p_a) else None,
                    "harvey_pass_abs_t_gt_3": bool(abs(t_a) > 3.0) if np.isfinite(t_a) else False,
                }

        out["by_horizon"][str(horizon)] = hres
    return out


def derive_verdict(summary: dict[str, Any]) -> tuple[str, str]:
    midas_wins = []
    midas_losses = []
    for h in HORIZONS:
        tests = summary["by_horizon"][str(h)]["dm_tests_pooled_by_date"]
        for key in ["Component_MIDAS_vs_HAR", "HAR_MIDAS_vs_HAR", "Component_MIDAS_vs_GARCH_raw"]:
            rec = tests[key]
            t = rec["t_stat"]
            imp = rec["improvement_pct_left_vs_right"]
            if t is not None and t < -3.0 and imp is not None and imp > 0:
                midas_wins.append((h, key, t, imp))
            if t is not None and t > 3.0 and imp is not None and imp < 0:
                midas_losses.append((h, key, t, imp))
    if midas_wins and not midas_losses:
        return (
            "MIDAS_LONG_COMPONENT_HELPS",
            "At least one MIDAS-augmented model beats a baseline at the Harvey |t|>3 pooled-by-date gate without a symmetric MIDAS failure.",
        )
    if midas_losses and not midas_wins:
        return (
            "MIDAS_LONG_COMPONENT_HURTS",
            "MIDAS-augmented models significantly underperform at least one baseline and never clear the positive Harvey gate.",
        )
    if midas_wins and midas_losses:
        return (
            "MIXED_HORIZON_DEPENDENT",
            "MIDAS helps in some pooled tests but hurts in others; this is not a clean long-horizon win.",
        )
    return (
        "NULL_NO_HARVEY_MIDAS_EDGE",
        "The RV-MIDAS long-run component does not produce a Harvey-pass pooled OOS improvement over HAR or GARCH baselines.",
    )


def plot_summary(summary: dict[str, Any]) -> None:
    models = ["GARCH_raw", "HAR", "Component_MIDAS", "HAR_MIDAS"]
    labels = ["GARCH", "HAR", "Component\nMIDAS", "HAR+\nMIDAS"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), dpi=150)
    for ax, h in zip(axes, HORIZONS):
        hres = summary["by_horizon"][str(h)]
        base = hres["pooled_qlike"]["HAR"]
        vals = []
        for m in models:
            q = hres["pooled_qlike"][m]
            vals.append((base - q) / abs(base) * 100.0)
        colors = ["#667085", "#245B9A", "#0F766E", "#237A57"]
        ax.bar(labels, vals, color=colors)
        ax.axhline(0, color="#344054", linewidth=1)
        ax.set_title(f"H={h} trading days: QLIKE improvement vs HAR")
        ax.set_ylabel("% improvement")
        ax.grid(axis="y", alpha=0.25)
        for i, v in enumerate(vals):
            ax.text(i, v + (0.02 if v >= 0 else -0.02), f"{v:+.2f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    fig.suptitle("RV-MIDAS long-run component at long horizons")
    fig.tight_layout()
    fig.savefig(FIG_PATH)
    plt.close(fig)


def main() -> None:
    started = time.time()
    assets = [prepare_asset(ticker) for ticker in ASSETS]

    forecast_frames = []
    for asset in assets:
        print(f"[forecast] {asset.ticker}", flush=True)
        for h in HORIZONS:
            f = forecast_asset_horizon(asset, h)
            forecast_frames.append(f)
            print(f"  H={h}: {len(f)} forecasts", flush=True)
    forecasts = pd.concat(forecast_frames, ignore_index=True)
    summary = summarize_forecasts(forecasts)
    verdict, verdict_text = derive_verdict(summary)
    plot_summary(summary)

    data_meta = {}
    for asset in assets:
        df = asset.frame
        data_meta[asset.ticker] = {
            "first_date": str(df.index.min().date()),
            "last_date": str(df.index.max().date()),
            "n_daily_returns": int(len(df)),
            "garch_fit_failures": int(asset.garch_fit_failures),
            "garch_fallback_uses_after_prior_success": int(asset.garch_fallback_uses),
        }

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": EXPERIMENT_ID,
        "title": "RV-MIDAS long-run component vs GARCH/HAR at 22/66-day horizons",
        "run_date": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "verdict_text": verdict_text,
        "data": {
            "source": "yfinance daily adjusted OHLCV",
            "assets": ASSETS,
            "data_start": DATA_START,
            "data_end_exclusive": DATA_END,
            "oos_start": OOS_START,
            "asset_meta": data_meta,
        },
        "method": {
            "target": "forward average close-to-close variance: mean(r_{t+1}^2 ... r_{t+H}^2)",
            "horizons_trading_days": HORIZONS,
            "lookahead_guard": "features use information through origin t; OOS training rows require target_end j+H < forecast_origin i",
            "models": {
                "GARCH_raw": "rolling GARCH(1,1) normal, window=1500, refit every 63 trading days; H-step average variance recursion",
                "GARCH_log": "OLS calibration: log forward variance on log GARCH_raw",
                "HAR": "log-HAR using log r2_t, log mean r2_{t-4:t}, log mean r2_{t-21:t}",
                "Component_MIDAS": "GARCH-MIDAS proxy: log target on log GARCH_raw short component + log fixed-beta MIDAS long component",
                "HAR_MIDAS": "HAR plus fixed-beta MIDAS long component",
            },
            "midas": {
                "blocks": MIDAS_BLOCKS,
                "block_days": MIDAS_BLOCK_DAYS,
                "omega_fixed": MIDAS_OMEGA,
                "weights_recent_to_old": [float(x) for x in MIDAS_WEIGHTS],
            },
            "inference": "Patton QLIKE via volpred.stats.model_evaluation.qlike_pointwise; DM-HAC with h=forecast horizon; pooled multi-asset inference averages loss differentials by date before DM (K1355 guard).",
            "important_scope_limit": "This is a daily RV-MIDAS/GARCH-component proxy, not a full Engle-Ghysels-Sohn GARCH-MIDAS MLE replication.",
        },
        "summary": summary,
        "artifacts": {
            "script": f"{EXPERIMENT_ID}.py",
            "results": f"{EXPERIMENT_ID}_results.json",
            "figure": FIG_PATH.name,
        },
        "runtime_seconds": float(time.time() - started),
        "references": [
            "Engle, Ghysels, and Sohn (2013), Stock Market Volatility and Macroeconomic Fundamentals, Review of Economics and Statistics.",
            "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility, Journal of Financial Econometrics.",
            "Hansen and Lunde (2005), A Forecast Comparison of Volatility Models, Journal of Applied Econometrics.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies, Journal of Econometrics.",
            "Diebold and Mariano (1995), Comparing predictive accuracy, Journal of Business & Economic Statistics.",
            "Conrad and Loch (2015), Anticipating long-term stock market volatility, Journal of Applied Econometrics.",
        ],
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"[done] verdict={verdict}")
    print(f"[done] wrote {RESULTS_PATH}")
    print(f"[done] wrote {FIG_PATH}")


if __name__ == "__main__":
    main()
