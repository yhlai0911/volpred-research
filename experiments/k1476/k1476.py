#!/usr/bin/env python3
"""K1476: TAIFEX OFI -> RV across horizon and regime.

Uses the local 5-minute TAIFEX cache from K1124 and avoids external data.
Core question: does OFI add predictive value for 5-min / 30-min / next-day RV,
and is any gain concentrated in high-volatility regimes?
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mplconfig"))
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

SEED = 42
np.random.seed(SEED)

CACHE_PATH = Path("experiments/k1124/_cache_bars_2017-01-01_2021-12-31.parquet")
RESULTS_PATH = HERE / "k1476_results.json"
FIG_HORIZON = HERE / "k1476_horizon_qlike.png"
FIG_REGIME = HERE / "k1476_regime_gain.png"

IS_END = pd.Timestamp("2019-12-31")
OOS_START = pd.Timestamp("2020-01-01")


def qlike_loss(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    y_true = np.clip(y_true, 1e-12, None)
    y_pred = np.clip(y_pred, 1e-12, None)
    return y_true / y_pred - np.log(y_true / y_pred) - 1.0


def dm_hln(loss_base: np.ndarray, loss_alt: np.ndarray) -> dict:
    d = loss_base - loss_alt
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"t_stat": np.nan, "p_value": np.nan, "n": int(n)}
    mean_d = d.mean()
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0 / n
    if var_d <= 0:
        return {"t_stat": np.nan, "p_value": np.nan, "n": int(n)}
    dm = mean_d / np.sqrt(var_d)
    k = ((n - 1) / n) ** 0.5
    stat = dm * k
    p = 2 * stats.t.sf(abs(stat), df=n - 1)
    return {"t_stat": round(float(stat), 4), "p_value": round(float(p), 4), "n": int(n)}


def load_bars() -> pd.DataFrame:
    df = pd.read_parquet(CACHE_PATH).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    return df


def expanding_regime_from_lagged_daily_rv(daily_rv: pd.Series, min_hist: int = 60) -> pd.Series:
    lagged = daily_rv.shift(1)
    labels = []
    for i, val in enumerate(lagged):
        hist = lagged.iloc[:i].dropna()
        if len(hist) < min_hist or pd.isna(val):
            labels.append(np.nan)
            continue
        q1, q2 = hist.quantile([1 / 3, 2 / 3])
        if val <= q1:
            labels.append("low")
        elif val <= q2:
            labels.append("mid")
        else:
            labels.append("high")
    return pd.Series(labels, index=daily_rv.index)


def build_bar_level_panel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    g = out.groupby("date", group_keys=False)

    out["rv_lag1"] = g["rv"].shift(1)
    out["rv_mean6"] = g["rv"].shift(1).rolling(6).mean().reset_index(level=0, drop=True)
    out["rv_mean12"] = g["rv"].shift(1).rolling(12).mean().reset_index(level=0, drop=True)
    out["abs_ofi"] = out["ofi"].abs()
    out["signed_ofi"] = out["ofi"]

    out["rv_fwd_1"] = g["rv"].shift(-1)
    out["rv_fwd_6"] = (
        g["rv"]
        .apply(lambda s: s.shift(-1).rolling(6, min_periods=6).sum().shift(-5))
        .reset_index(level=0, drop=True)
    )

    daily_rv = g["rv"].sum()
    daily_regime = expanding_regime_from_lagged_daily_rv(daily_rv)
    out["prev_day_rv"] = out["date"].map(daily_rv.shift(1))
    out["regime"] = out["date"].map(daily_regime)

    keep = out.dropna(subset=["rv_lag1", "rv_mean6", "rv_mean12", "rv_fwd_1", "rv_fwd_6", "regime"]).copy()
    return keep


def build_daily_panel(df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        df.groupby("date")
        .agg(
            daily_rv=("rv", "sum"),
            abs_ofi_mean=("ofi", lambda x: float(np.abs(x).mean())),
            signed_ofi_mean=("ofi", "mean"),
            abs_ofi_last12=("ofi", lambda x: float(np.abs(x.tail(12)).mean())),
            signed_ofi_last12=("ofi", lambda x: float(x.tail(12).mean())),
        )
        .sort_index()
    )
    daily["rv_lag1"] = daily["daily_rv"].shift(1)
    daily["rv_mean5"] = daily["daily_rv"].shift(1).rolling(5).mean()
    daily["rv_mean22"] = daily["daily_rv"].shift(1).rolling(22).mean()
    daily["target"] = daily["daily_rv"].shift(-1)
    daily["regime"] = expanding_regime_from_lagged_daily_rv(daily["daily_rv"])
    daily = daily.dropna().copy()
    return daily


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, xcols: list[str], ycol: str) -> tuple[np.ndarray, np.ndarray]:
    X_train = sm.add_constant(train[xcols], has_constant="add")
    X_test = sm.add_constant(test[xcols], has_constant="add")
    model = sm.OLS(train[ycol], X_train).fit()
    pred = np.asarray(model.predict(X_test), dtype=float)
    return pred, np.asarray(model.params, dtype=float)


def fit_predict_log_target(train: pd.DataFrame, test: pd.DataFrame, xcols: list[str], ycol: str) -> tuple[np.ndarray, np.ndarray]:
    X_train = sm.add_constant(train[xcols], has_constant="add")
    X_test = sm.add_constant(test[xcols], has_constant="add")
    y_train = np.log(np.clip(train[ycol].to_numpy(), 1e-12, None))
    model = sm.OLS(y_train, X_train).fit()
    pred_log = np.asarray(model.predict(X_test), dtype=float)
    pred = np.exp(pred_log)
    return pred, np.asarray(model.params, dtype=float)


def summarize_regime_gains(frame: pd.DataFrame, ycol: str, loss_base: np.ndarray, loss_ofi: np.ndarray) -> dict:
    tmp = frame[["regime"]].copy()
    tmp["loss_base"] = loss_base
    tmp["loss_ofi"] = loss_ofi
    out = {}
    for regime, g in tmp.groupby("regime"):
        gain = (g["loss_base"] - g["loss_ofi"]).mean()
        out[str(regime)] = {
            "n": int(len(g)),
            "avg_qlike_gain": round(float(gain), 6),
        }
    return out


def run_bar_horizon(panel: pd.DataFrame, ycol: str) -> dict:
    train = panel[panel["date"] <= IS_END].copy()
    test = panel[panel["date"] >= OOS_START].copy()
    base_cols = ["rv_lag1", "rv_mean6", "rv_mean12"]
    ofi_cols = base_cols + ["abs_ofi", "signed_ofi"]

    pred_base, beta_base = fit_predict(train, test, base_cols, ycol)
    pred_ofi, beta_ofi = fit_predict(train, test, ofi_cols, ycol)
    y = test[ycol].to_numpy()
    loss_base = qlike_loss(y, pred_base)
    loss_ofi = qlike_loss(y, pred_ofi)

    return {
        "n_is": int(len(train)),
        "n_oos": int(len(test)),
        "qlike_base": round(float(np.mean(loss_base)), 6),
        "qlike_ofi": round(float(np.mean(loss_ofi)), 6),
        "qlike_gain_pct": round(float((np.mean(loss_base) - np.mean(loss_ofi)) / np.mean(loss_base) * 100), 4),
        "dm_vs_base": dm_hln(loss_base, loss_ofi),
        "beta_base": [round(float(x), 8) for x in beta_base],
        "beta_ofi": [round(float(x), 8) for x in beta_ofi],
        "regime_oos_gain": summarize_regime_gains(test, ycol, loss_base, loss_ofi),
        "regime_counts_oos": {str(k): int(v) for k, v in test["regime"].value_counts().sort_index().items()},
    }


def run_daily_horizon(panel: pd.DataFrame) -> dict:
    train = panel[panel.index <= IS_END].copy()
    test = panel[panel.index >= OOS_START].copy()
    base_cols = ["rv_lag1", "rv_mean5", "rv_mean22"]
    ofi_cols = base_cols + ["abs_ofi_mean", "signed_ofi_mean", "abs_ofi_last12", "signed_ofi_last12"]

    pred_base, beta_base = fit_predict_log_target(train, test, base_cols, "target")
    pred_ofi, beta_ofi = fit_predict_log_target(train, test, ofi_cols, "target")
    y = test["target"].to_numpy()
    loss_base = qlike_loss(y, pred_base)
    loss_ofi = qlike_loss(y, pred_ofi)

    return {
        "n_is": int(len(train)),
        "n_oos": int(len(test)),
        "qlike_base": round(float(np.mean(loss_base)), 6),
        "qlike_ofi": round(float(np.mean(loss_ofi)), 6),
        "qlike_gain_pct": round(float((np.mean(loss_base) - np.mean(loss_ofi)) / np.mean(loss_base) * 100), 4),
        "dm_vs_base": dm_hln(loss_base, loss_ofi),
        "beta_base": [round(float(x), 8) for x in beta_base],
        "beta_ofi": [round(float(x), 8) for x in beta_ofi],
        "regime_oos_gain": summarize_regime_gains(test.reset_index(), "target", loss_base, loss_ofi),
        "regime_counts_oos": {str(k): int(v) for k, v in test["regime"].value_counts().sort_index().items()},
    }


def make_figures(results: dict) -> None:
    horizons = ["5min", "30min", "1day"]
    qlike_base = [results[h]["qlike_base"] for h in horizons]
    qlike_ofi = [results[h]["qlike_ofi"] for h in horizons]
    x = np.arange(len(horizons))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - width / 2, qlike_base, width, label="Baseline HAR-style")
    ax.bar(x + width / 2, qlike_ofi, width, label="Baseline + OFI")
    ax.set_xticks(x)
    ax.set_xticklabels(horizons)
    ax.set_title("OOS QLIKE by Horizon")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_HORIZON, dpi=180)
    plt.close(fig)

    regimes = ["low", "mid", "high"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, horizon in zip(axes, horizons):
        gains = [results[horizon]["regime_oos_gain"].get(r, {}).get("avg_qlike_gain", np.nan) for r in regimes]
        ax.bar(regimes, gains, color=["#8ecae6", "#ffb703", "#d62828"])
        ax.axhline(0.0, color="black", lw=1)
        ax.set_title(horizon)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("avg QLIKE gain of OFI model")
    fig.suptitle("OOS OFI Gain by Prior-Day RV Regime")
    fig.tight_layout()
    fig.savefig(FIG_REGIME, dpi=180)
    plt.close(fig)


def main() -> None:
    bars = load_bars()
    bar_panel = build_bar_level_panel(bars)
    daily_panel = build_daily_panel(bars)

    results = {
        "experiment_id": "K1476",
        "title": "TAIFEX OFI -> RV across horizon and adaptive prior-day RV regime",
        "seed": SEED,
        "data": {
            "source": str(CACHE_PATH),
            "bar_period": f"{bars['date'].min().date()} to {bars['date'].max().date()}",
            "n_bar_rows": int(len(bars)),
            "n_days": int(bars["date"].nunique()),
            "regime_definition": "expanding tertiles of lagged prior-day daily RV with 60-day warmup",
            "is_period": f"{bars['date'].min().date()} to {IS_END.date()}",
            "oos_period": f"{OOS_START.date()} to {bars['date'].max().date()}",
        },
        "methodology": {
            "5min_target": "next-bar RV",
            "30min_target": "sum of next 6 bars RV within same day",
            "1day_target": "next-day daily RV",
            "baseline_controls_bar": ["rv_lag1", "rv_mean6", "rv_mean12"],
            "baseline_controls_day": ["rv_lag1", "rv_mean5", "rv_mean22"],
            "ofi_features_bar": ["abs_ofi", "signed_ofi"],
            "ofi_features_day": ["abs_ofi_mean", "signed_ofi_mean", "abs_ofi_last12", "signed_ofi_last12"],
            "timing_rule": "all OFI features at t predict strictly future RV; no same-bar target leakage",
        },
    }

    results["5min"] = run_bar_horizon(bar_panel, "rv_fwd_1")
    results["30min"] = run_bar_horizon(bar_panel, "rv_fwd_6")
    results["1day"] = run_daily_horizon(daily_panel)

    best_horizon = max(
        ["5min", "30min", "1day"],
        key=lambda h: results[h]["qlike_gain_pct"],
    )
    results["verdict"] = {
        "best_horizon": best_horizon,
        "best_gain_pct": results[best_horizon]["qlike_gain_pct"],
        "high_regime_best_horizon_gain": results[best_horizon]["regime_oos_gain"].get("high", {}).get("avg_qlike_gain"),
        "summary": (
            "OFI only helps in the shortest horizon / highest-volatility regime"
            if results["5min"]["qlike_gain_pct"] > results["30min"]["qlike_gain_pct"] > results["1day"]["qlike_gain_pct"]
            else "OFI regime/horizon pattern is mixed"
        ),
    }

    make_figures(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps({k: results[k] for k in ["5min", "30min", "1day", "verdict"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
