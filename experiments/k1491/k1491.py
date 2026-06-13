#!/usr/bin/env python3
"""K1491 — Fix K1490 crypto VoV tail-spillover methodology.

K1490 used a sparse binary tail event indicator on a panel whose traditional
ETF rolling windows were broken by weekend NaNs. This reconstruction keeps the
same research question but uses pairwise valid trading days and a continuous
rolling quantile-crossing tail signal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.tsa.stattools import grangercausalitytests

warnings.filterwarnings("ignore")

SEED = 42
RNG = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "k1491_results.json"
OUT_HEATMAP = HERE / "k1491_spillover_heatmap.png"
OUT_TIMESERIES = HERE / "k1491_tail_signal_timeseries.png"
LOCAL_SNAPSHOT_DIR = HERE.parents[1] / "experiments" / "k1090b" / "data"

START = "2018-01-01"
END = "2025-12-31"
ROLL = 20
TAIL_Q = 0.95
MAX_LAG = 5

CRYPTO = ["BTC-USD", "ETH-USD"]
TRAD = ["SPY", "GLD", "USO", "TLT"]
ALL_TICKERS = CRYPTO + TRAD


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


def _load_local_snapshot() -> pd.DataFrame | None:
    frames = []
    for ticker in ALL_TICKERS:
        path = LOCAL_SNAPSHOT_DIR / f"{ticker}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path)
        if "Date" not in df.columns:
            raise RuntimeError(f"local snapshot missing Date column: {path}")
        price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
        if price_col not in df.columns:
            raise RuntimeError(f"local snapshot missing Close/Adj Close column: {path}")
        s = pd.Series(
            pd.to_numeric(df[price_col], errors="coerce").values,
            index=pd.to_datetime(df["Date"]),
            name=ticker,
        ).dropna()
        frames.append(s)
    return pd.concat(frames, axis=1).sort_index()


def fetch_close() -> tuple[pd.DataFrame, str]:
    local = _load_local_snapshot()
    if local is not None:
        return local, f"local snapshot CSV: {LOCAL_SNAPSHOT_DIR.relative_to(HERE.parents[1])}"

    data = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"].copy()
    else:
        close = data[["Close"]].copy()
        close.columns = ALL_TICKERS
    close = close.dropna(how="all")
    missing = [ticker for ticker in ALL_TICKERS if ticker not in close.columns or close[ticker].dropna().empty]
    if missing:
        raise RuntimeError(f"missing downloaded close data for: {missing}")
    return close, "yfinance adjusted daily close"


def log_returns(close: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for ticker in ALL_TICKERS:
        s = close[ticker].dropna()
        out[ticker] = np.log(s / s.shift(1)).dropna()
    return out


def rolling_sigma(ret: pd.Series) -> pd.Series:
    return ret.rolling(ROLL, min_periods=ROLL).std()


def rolling_vov(ret: pd.Series) -> pd.Series:
    sigma = rolling_sigma(ret)
    return sigma.rolling(ROLL, min_periods=ROLL).std()


def quantile_crossing_signal(abs_ret: pd.Series) -> pd.Series:
    """Continuous tail magnitude above the lagged rolling 95% threshold."""
    threshold = abs_ret.rolling(ROLL, min_periods=ROLL).quantile(TAIL_Q).shift(1)
    signal = (abs_ret - threshold).clip(lower=0.0)
    return signal.dropna()


def describe_series(s: pd.Series) -> dict:
    x = s.dropna()
    if x.empty:
        return {"n": 0}
    return {
        "n": int(x.shape[0]),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)),
        "min": float(x.min()),
        "p50": float(x.quantile(0.50)),
        "p95": float(x.quantile(0.95)),
        "max": float(x.max()),
        "nonzero_n": int((x > 0).sum()),
        "nonzero_rate": float((x > 0).mean()),
    }


def zscore(s: pd.Series) -> pd.Series:
    x = s.dropna()
    sd = x.std(ddof=1)
    if not np.isfinite(sd) or sd <= 1e-12:
        return s * np.nan
    return (s - x.mean()) / sd


def granger_tail_signal(predictor_lag1: pd.Series, tail_signal: pd.Series) -> dict:
    df = pd.concat([tail_signal, predictor_lag1], axis=1).dropna()
    df.columns = ["y", "x"]
    if df.shape[0] < 120:
        return {"error": "insufficient_samples", "n": int(df.shape[0])}
    if df["y"].std(ddof=1) <= 1e-12 or df["x"].std(ddof=1) <= 1e-12:
        return {
            "error": "constant_column",
            "n": int(df.shape[0]),
            "y_nonzero_n": int((df["y"] > 0).sum()),
        }

    try:
        res = grangercausalitytests(df[["y", "x"]], maxlag=MAX_LAG, verbose=False)
    except Exception as exc:
        return {"error": f"granger_failed: {exc}", "n": int(df.shape[0])}

    per_lag = {}
    for lag, val in res.items():
        ftest = val[0].get("ssr_ftest")
        if ftest is None:
            continue
        per_lag[str(lag)] = {
            "F": float(ftest[0]),
            "p_value": float(ftest[1]),
        }
    if not per_lag:
        return {"error": "no_ftest_returned", "n": int(df.shape[0])}

    best_lag = min(per_lag, key=lambda k: per_lag[k]["p_value"])
    raw_p = float(per_lag[best_lag]["p_value"])
    lag_adjusted_p = min(raw_p * MAX_LAG, 1.0)
    return {
        "n": int(df.shape[0]),
        "y_nonzero_n": int((df["y"] > 0).sum()),
        "y_nonzero_rate": float((df["y"] > 0).mean()),
        "per_lag": per_lag,
        "best_lag": int(best_lag),
        "best_raw_p_value": raw_p,
        "pair_p_value_lag_bonferroni": lag_adjusted_p,
    }


def quantile_reg_absret(predictor_lag1: pd.Series, abs_ret: pd.Series) -> dict:
    df = pd.concat([abs_ret, predictor_lag1], axis=1).dropna()
    df.columns = ["y", "x_raw"]
    if df.shape[0] < 200:
        return {"error": "insufficient_samples", "n": int(df.shape[0])}
    df["x"] = zscore(df["x_raw"])
    df = df.dropna()
    if df["x"].std(ddof=1) <= 1e-12:
        return {"error": "constant_predictor", "n": int(df.shape[0])}

    X = sm.add_constant(df["x"].values)
    y = df["y"].values
    try:
        model = QuantReg(y, X).fit(q=TAIL_Q, max_iter=5000)
    except Exception as exc:
        return {"error": f"quantreg_failed: {exc}", "n": int(df.shape[0])}

    # Smaller bootstrap than K1490 to stay within hourly budget while keeping CI.
    boot = []
    n = len(y)
    for _ in range(500):
        idx = RNG.integers(0, n, n)
        try:
            b = QuantReg(y[idx], X[idx]).fit(q=TAIL_Q, max_iter=2000)
            boot.append(float(b.params[1]))
        except Exception:
            continue
    boot_arr = np.asarray(boot, dtype=float)
    ci = [float("nan"), float("nan")]
    if boot_arr.size >= 100:
        ci = [float(np.quantile(boot_arr, 0.025)), float(np.quantile(boot_arr, 0.975))]

    return {
        "n": int(df.shape[0]),
        "q": TAIL_Q,
        "target": "absolute log return",
        "predictor": "lagged crypto VoV z-score",
        "intercept": float(model.params[0]),
        "slope_per_1sd_vov": float(model.params[1]),
        "t_stat": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "bootstrap_ci95": ci,
        "n_bootstrap": int(boot_arr.size),
    }


def finite_or_none(obj):
    if isinstance(obj, dict):
        return {k: finite_or_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite_or_none(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    return obj


def plot_heatmap(granger_grid: pd.DataFrame, qr_p_grid: pd.DataFrame, qr_slope_grid: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    matrices = [
        (granger_grid, "Granger pair p after lag-Bonferroni", "viridis_r", 0, 0.20),
        (qr_p_grid, "QuantReg q=.95 p-value", "viridis_r", 0, 0.20),
        (qr_slope_grid, "QuantReg slope per 1sd crypto VoV", "coolwarm", None, None),
    ]

    for ax, (mat, title, cmap, vmin, vmax) in zip(axes, matrices):
        values = mat.values.astype(float)
        im = ax.imshow(values, cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_xticks(range(len(mat.columns)))
        ax.set_yticks(range(len(mat.index)))
        ax.set_xticklabels(mat.columns, rotation=30, ha="right")
        ax.set_yticklabels(mat.index)
        ax.set_title(title)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                v = values[i, j]
                txt = "n/a" if np.isnan(v) else f"{v:.3f}"
                ax.text(j, i, txt, ha="center", va="center", fontsize=8, color="white")
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("K1491: lagged crypto vol-of-vol -> traditional tail crossing")
    fig.tight_layout()
    fig.savefig(OUT_HEATMAP, dpi=160)
    plt.close(fig)


def plot_tail_timeseries(tail_signals: dict[str, pd.Series], crypto_vov: dict[str, pd.Series]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for c, s in crypto_vov.items():
        z = zscore(s).dropna()
        axes[0].plot(z.index.to_numpy(), z.to_numpy(), label=f"{c} VoV z", lw=1.0, alpha=0.85)
    axes[0].set_title("Lag predictors: crypto VoV z-scores")
    axes[0].legend(ncol=2)
    axes[0].grid(alpha=0.25)

    for t, s in tail_signals.items():
        clean = s.dropna()
        axes[1].plot(clean.index.to_numpy(), clean.to_numpy(), label=t, lw=0.9, alpha=0.75)
    axes[1].set_title("Target tail signals: max(0, |r| - lagged rolling q95)")
    axes[1].legend(ncol=4)
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT_TIMESERIES, dpi=160)
    plt.close(fig)


def summarise_p_grid(grid: pd.DataFrame, label: str) -> dict:
    arr = grid.values.astype(float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"label": label, "n_tests": 0}
    alpha = 0.05 / arr.size
    return {
        "label": label,
        "n_tests": int(arr.size),
        "min_p": float(arr.min()),
        "n_p_lt_0_10": int((arr < 0.10).sum()),
        "n_p_lt_0_05": int((arr < 0.05).sum()),
        "bonferroni_alpha_pairs": float(alpha),
        "n_bonferroni_pair_pass": int((arr < alpha).sum()),
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print(f"[K1491] start UTC={started} seed={SEED} git={git_rev()}")
    close, data_source = fetch_close()
    returns = log_returns(close)
    crypto_vov = {c: rolling_vov(returns[c]) for c in CRYPTO}
    target_abs = {t: returns[t].abs() for t in TRAD}
    tail_signals = {t: quantile_crossing_signal(target_abs[t]) for t in TRAD}

    granger_results = {}
    qr_results = {}
    granger_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    granger_raw_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    qr_p_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    qr_slope_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)

    for c in CRYPTO:
        predictor_lag1 = crypto_vov[c].shift(1)
        for t in TRAD:
            key = f"{c}__to__{t}"
            g = granger_tail_signal(predictor_lag1, tail_signals[t])
            granger_results[key] = g
            if "pair_p_value_lag_bonferroni" in g:
                granger_grid.loc[c, t] = g["pair_p_value_lag_bonferroni"]
                granger_raw_grid.loc[c, t] = g["best_raw_p_value"]

            q = quantile_reg_absret(predictor_lag1, target_abs[t])
            qr_results[key] = q
            if "p_value" in q:
                qr_p_grid.loc[c, t] = q["p_value"]
                qr_slope_grid.loc[c, t] = q["slope_per_1sd_vov"]

    granger_summary = summarise_p_grid(granger_grid, "granger_tail_signal_lag_adjusted")
    qr_summary = summarise_p_grid(qr_p_grid, "quantreg_abs_return_q95")
    n_granger_errors = sum(1 for v in granger_results.values() if "error" in v)

    if n_granger_errors:
        interpretation = "METHOD_FAIL: at least one Granger pair still failed; do not use inferentially."
    elif granger_summary.get("n_bonferroni_pair_pass", 0) or qr_summary.get("n_bonferroni_pair_pass", 0):
        interpretation = "PARTIAL: at least one crypto -> traditional tail pair survives pairwise Bonferroni."
    elif granger_summary.get("n_p_lt_0_05", 0) or qr_summary.get("n_p_lt_0_05", 0):
        interpretation = "WEAK: nominal p<0.05 exists, but no pair survives Bonferroni across 8 crypto-target pairs."
    else:
        interpretation = "NULL: no robust evidence that lagged crypto VoV predicts traditional tail crossings."

    plot_heatmap(granger_grid, qr_p_grid, qr_slope_grid)
    plot_tail_timeseries(tail_signals, crypto_vov)

    results = {
        "experiment_id": "K1491",
        "title": "Crypto VoV tail-spillover methodology fix for K1490",
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "seed": SEED,
        "data_source": data_source,
        "sample_request": {"start": START, "end": END},
        "tickers": ALL_TICKERS,
        "crypto_predictors": CRYPTO,
        "traditional_targets": TRAD,
        "methodology": {
            "return": "log close-to-close return per asset using pairwise valid non-missing closes",
            "crypto_vov": "20-day rolling std of 20-day rolling return std",
            "tail_signal": "max(0, |r_t| - rolling q0.95(|r|) over t-20:t-1)",
            "lookahead_control": "crypto_vov predictor shifted by .shift(1); tail threshold shifted by one target trading day",
            "granger": "statsmodels grangercausalitytests y=tail_signal, x=lagged crypto_vov, maxlag=5",
            "granger_main_p": "best raw lag p-value multiplied by MAX_LAG to reduce lag-mining overclaim",
            "quantile_regression": "QuantReg q=0.95 of target |r| on lagged crypto_vov z-score",
        },
        "sample_by_ticker": {
            t: {
                "first_return_date": str(returns[t].index.min().date()),
                "last_return_date": str(returns[t].index.max().date()),
                "return_obs": int(returns[t].shape[0]),
            }
            for t in ALL_TICKERS
        },
        "crypto_vov_descriptive": {c: describe_series(crypto_vov[c]) for c in CRYPTO},
        "tail_signal_descriptive": {t: describe_series(tail_signals[t]) for t in TRAD},
        "granger_lag1_to_5_tail_signal": granger_results,
        "quantile_reg_q95_abs_return": qr_results,
        "granger_pair_p_lag_adjusted_grid": granger_grid.round(6).to_dict(),
        "granger_best_raw_p_grid": granger_raw_grid.round(6).to_dict(),
        "quantreg_p_grid": qr_p_grid.round(6).to_dict(),
        "quantreg_slope_grid": qr_slope_grid.round(6).to_dict(),
        "verdict_summary": {
            "granger": granger_summary,
            "quantile_regression": qr_summary,
            "n_granger_pairs": len(granger_results),
            "n_granger_errors": int(n_granger_errors),
            "interpretation": interpretation,
        },
        "k1490_comparison": {
            "k1490_failure": "traditional rolling sigma/vov were all NaN and binary tail indicators were all zero; Granger failed with constant-column errors",
            "k1491_fix": "pairwise valid trading-day returns plus continuous quantile-crossing tail_signal",
            "granger_valid_pairs": int(len(granger_results) - n_granger_errors),
            "granger_total_pairs": int(len(granger_results)),
        },
        "figures": [str(OUT_HEATMAP.relative_to(HERE.parents[1])), str(OUT_TIMESERIES.relative_to(HERE.parents[1]))],
        "literature": [
            "Diebold & Yilmaz (2012), Better to Give than to Receive: Predictive Directional Measurement of Volatility Spillovers.",
            "Mazzarisi et al. (2020), Tail Granger causalities and where to find them.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies.",
        ],
    }

    OUT_JSON.write_text(json.dumps(finite_or_none(results), ensure_ascii=False, indent=2) + "\n")
    print(f"[K1491] wrote {OUT_JSON}")
    print(f"[K1491] wrote {OUT_HEATMAP}")
    print(f"[K1491] wrote {OUT_TIMESERIES}")
    print(f"[K1491] verdict: {interpretation}")
    print(f"[K1491] Granger errors: {n_granger_errors}/8")
    print(f"[K1491] Granger summary: {granger_summary}")
    print(f"[K1491] QuantReg summary: {qr_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
