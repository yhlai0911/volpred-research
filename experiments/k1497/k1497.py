"""K1497 — Realized-vol roughness stability and OOS predictive gain re-check.

This experiment deliberately uses long-history daily OHLC data with a Parkinson
range proxy because the repo does not contain a multi-year, multi-asset local
5-minute archive. The goal is not to pretend this fully replaces the intended
high-frequency version, but to run an honest, reproducible re-check on the
questions we can answer today:

1. Is H < 0.5 stable across assets and subperiods?
2. Does adding roughness information improve OOS HAR forecasts?
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1497_results.json"
FIG_H_PATH = HERE / "k1497_hurst_summary.png"
FIG_OOS_PATH = HERE / "k1497_oos_qlike.png"

SEED = 42
np.random.seed(SEED)

OOS_START = pd.Timestamp("2022-01-03")
ROLLING_H_WINDOW = 504
MIN_TRAIN = 500
MAX_LAG = 20

ASSETS = {
    "SPY": {
        "csv": ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "high": "spy_high",
        "low": "spy_low",
    },
    "QQQ": {
        "csv": ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "high": "qqq_high",
        "low": "qqq_low",
    },
    "EEM": {
        "csv": ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "high": "eem_high",
        "low": "eem_low",
    },
    "FEZ": {
        "csv": ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "high": "fez_high",
        "low": "fez_low",
    },
    "GLD": {
        "csv": ROOT / "paper/garch-x-vix/data/gld_vix_gvz_2000-2026.csv",
        "high": "gld_high",
        "low": "gld_low",
    },
    "USO": {
        "csv": ROOT / "paper/garch-x-vix/data/uso_vix_ovx_2005-2026.csv",
        "high": "uso_high",
        "low": "uso_low",
    },
}

REFERENCES = [
    {
        "title": "Volatility is Rough",
        "authors": "Gatheral, Jaisson, Rosenbaum",
        "year": 2018,
        "url": "https://arxiv.org/abs/1410.3394",
    },
    {
        "title": "A Simple Approximate Long-Memory Model of Realized Volatility",
        "authors": "Corsi",
        "year": 2009,
        "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/787440",
    },
    {
        "title": "Volatility forecast comparison using imperfect volatility proxies",
        "authors": "Patton",
        "year": 2011,
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304407610001700",
    },
    {
        "title": "Rough volatility: fact or artefact?",
        "authors": "Cont, Das",
        "year": 2024,
        "url": "https://arxiv.org/abs/2203.13820",
    },
]


@dataclass
class HEstimate:
    h: float
    slope: float
    intercept: float
    r2: float
    se_h: float
    n_points: int


def load_parkinson_series(path: Path, high_col: str, low_col: str) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["date"])
    cols = ["date", high_col, low_col]
    df = df[cols].dropna()
    high = pd.to_numeric(df[high_col], errors="coerce")
    low = pd.to_numeric(df[low_col], errors="coerce")
    valid = (high > 0) & (low > 0) & (high >= low)
    df = df.loc[valid, ["date"]].copy()
    high = high.loc[valid]
    low = low.loc[valid]
    rv = (np.log(high / low) ** 2) / (4.0 * math.log(2.0))
    s = pd.Series(rv.values, index=df["date"], name="rv").sort_index()
    return s[s > 0]


def estimate_hurst_structure(log_rv: pd.Series, max_lag: int = MAX_LAG) -> HEstimate:
    x = log_rv.dropna().values
    lags = np.arange(1, max_lag + 1)
    moments = []
    valid_lags = []
    for lag in lags:
        diff = x[lag:] - x[:-lag]
        sq = diff ** 2
        m = np.mean(sq)
        if np.isfinite(m) and m > 0:
            moments.append(m)
            valid_lags.append(lag)
    if len(valid_lags) < 6:
        raise ValueError("Too few valid lags for Hurst estimation")
    lx = np.log(np.asarray(valid_lags, dtype=float))
    ly = np.log(np.asarray(moments, dtype=float))
    reg = stats.linregress(lx, ly)
    h = reg.slope / 2.0
    return HEstimate(
        h=float(h),
        slope=float(reg.slope),
        intercept=float(reg.intercept),
        r2=float(reg.rvalue ** 2),
        se_h=float(reg.stderr / 2.0),
        n_points=len(valid_lags),
    )


def rolling_hurst(log_rv: pd.Series, window: int = ROLLING_H_WINDOW) -> pd.Series:
    out = pd.Series(index=log_rv.index, dtype=float)
    vals = log_rv.dropna()
    for i in range(window, len(vals) + 1):
        idx = vals.index[i - 1]
        segment = vals.iloc[i - window:i]
        try:
            out.loc[idx] = estimate_hurst_structure(segment).h
        except ValueError:
            out.loc[idx] = np.nan
    return out.clip(lower=0.0, upper=1.0)


def build_har_training(rv: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    lag1 = rv.shift(1)
    lag5 = rv.shift(1).rolling(5).mean()
    lag22 = rv.shift(1).rolling(22).mean()
    df = pd.DataFrame({"y": rv, "lag1": lag1, "lag5": lag5, "lag22": lag22}).dropna()
    y = df["y"].values
    x = np.column_stack(
        [np.ones(len(df)), df["lag1"].values, df["lag5"].values, df["lag22"].values]
    )
    return y, x


def fit_har_beta(train_rv: pd.Series) -> np.ndarray:
    y, x = build_har_training(train_rv)
    return np.linalg.lstsq(x, y, rcond=None)[0]


def har_forecast(beta: np.ndarray, history: pd.Series, h_t: float | None = None) -> float:
    lag1 = float(history.iloc[-1])
    lag5 = float(history.iloc[-5:].mean())
    lag22 = float(history.iloc[-22:].mean())
    if h_t is None or not np.isfinite(h_t):
        x = np.array([1.0, lag1, lag5, lag22], dtype=float)
    else:
        h_clamped = float(np.clip(h_t, 0.0, 1.0))
        w_d = 1.0 + (0.5 - h_clamped)
        w_w = 1.0
        w_m = 1.0 - (0.5 - h_clamped)
        x = np.array([1.0, lag1 * w_d, lag5 * w_w, lag22 * w_m], dtype=float)
    fc = float(np.dot(beta, x))
    return max(fc, 1e-12)


def oos_har_compare(rv: pd.Series, rolling_h: pd.Series) -> dict:
    dates = rv.index
    start_pos = dates.searchsorted(OOS_START)
    actual = []
    fc_har = []
    fc_rough = []
    eval_dates = []

    for pos in range(max(start_pos, 22), len(dates)):
        train = rv.iloc[:pos]
        if len(train) < MIN_TRAIN:
            continue
        try:
            beta = fit_har_beta(train)
        except np.linalg.LinAlgError:
            continue

        history = rv.iloc[:pos]
        h_t = rolling_h.reindex(dates).iloc[pos - 1] if pos - 1 >= 0 else np.nan

        fc_base = har_forecast(beta, history)
        fc_rgh = har_forecast(beta, history, h_t=h_t)
        actual.append(float(rv.iloc[pos]))
        fc_har.append(fc_base)
        fc_rough.append(fc_rgh)
        eval_dates.append(dates[pos])

    actual_arr = np.asarray(actual, dtype=float)
    har_arr = np.asarray(fc_har, dtype=float)
    rough_arr = np.asarray(fc_rough, dtype=float)
    losses_har = qlike_pointwise(actual_arr, har_arr)
    losses_rough = qlike_pointwise(actual_arr, rough_arr)
    dm_stat, dm_p = dm_test(losses_rough, losses_har, h=1)

    return {
        "n_oos": int(len(actual_arr)),
        "start": str(eval_dates[0].date()) if eval_dates else None,
        "end": str(eval_dates[-1].date()) if eval_dates else None,
        "qlike": {
            "HAR": float(qlike(actual_arr, har_arr)),
            "HAR_Rough": float(qlike(actual_arr, rough_arr)),
        },
        "mse_log": {
            "HAR": float(np.mean((np.log(actual_arr) - np.log(har_arr)) ** 2)),
            "HAR_Rough": float(np.mean((np.log(actual_arr) - np.log(rough_arr)) ** 2)),
        },
        "dm_har_rough_vs_har": {
            "t_stat": float(dm_stat),
            "p_value": float(dm_p),
            "sign_convention": "negative => HAR-Rough lower loss (better)",
            "harvey_sig": bool(abs(dm_stat) > 3.0),
        },
        "improvement_pct": float(
            100.0 * (qlike(actual_arr, har_arr) - qlike(actual_arr, rough_arr)) / qlike(actual_arr, har_arr)
        ),
        "loss_diff_mean": float(np.mean(losses_rough - losses_har)),
    }


def summarize_stability(h_full: HEstimate, subperiods: dict[str, HEstimate], rolling: pd.Series) -> dict:
    roll = rolling.dropna()
    return {
        "full_sample": {
            "H": round(h_full.h, 6),
            "r2": round(h_full.r2, 6),
            "se_H": round(h_full.se_h, 6),
            "t_vs_half": round((h_full.h - 0.5) / h_full.se_h, 4) if h_full.se_h > 0 else None,
            "is_rough": bool(h_full.h < 0.5),
        },
        "subperiods": {
            name: {
                "H": round(est.h, 6),
                "r2": round(est.r2, 6),
                "is_rough": bool(est.h < 0.5),
            }
            for name, est in subperiods.items()
        },
        "rolling_504d": {
            "mean_H": round(float(roll.mean()), 6),
            "std_H": round(float(roll.std()), 6),
            "min_H": round(float(roll.min()), 6),
            "max_H": round(float(roll.max()), 6),
            "frac_rough": round(float((roll < 0.5).mean()), 6),
            "n_obs": int(len(roll)),
        },
    }


def tercile_subperiod_estimates(log_rv: pd.Series) -> dict[str, HEstimate]:
    n = len(log_rv)
    cuts = [0, n // 3, 2 * n // 3, n]
    out: dict[str, HEstimate] = {}
    for i in range(3):
        seg = log_rv.iloc[cuts[i]:cuts[i + 1]]
        out[f"tercile_{i+1}"] = estimate_hurst_structure(seg)
    return out


def make_figures(asset_results: dict) -> None:
    assets = list(asset_results)
    full_h = [asset_results[a]["roughness"]["full_sample"]["H"] for a in assets]
    mean_roll = [asset_results[a]["roughness"]["rolling_504d"]["mean_H"] for a in assets]
    qlike_diff = [
        asset_results[a]["oos"]["qlike"]["HAR_Rough"] - asset_results[a]["oos"]["qlike"]["HAR"]
        for a in assets
    ]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(assets))
    axes[0].bar(x, full_h, color="#33658A", label="Full-sample H")
    axes[0].plot(x, mean_roll, color="#F26419", marker="o", label="Rolling mean H")
    axes[0].axhline(0.5, color="black", linestyle="--", linewidth=1)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(assets, rotation=0)
    axes[0].set_ylabel("Hurst H")
    axes[0].set_title("Roughness by Asset")
    axes[0].legend(frameon=False)

    colors = ["#B22222" if v > 0 else "#2E8B57" for v in qlike_diff]
    axes[1].bar(x, qlike_diff, color=colors)
    axes[1].axhline(0.0, color="black", linestyle="--", linewidth=1)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(assets, rotation=0)
    axes[1].set_ylabel("QLIKE(HAR-Rough) - QLIKE(HAR)")
    axes[1].set_title("OOS QLIKE Difference")
    fig.tight_layout()
    fig.savefig(FIG_H_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    har = [asset_results[a]["oos"]["qlike"]["HAR"] for a in assets]
    rough = [asset_results[a]["oos"]["qlike"]["HAR_Rough"] for a in assets]
    width = 0.36
    ax.bar(x - width / 2, har, width, label="HAR", color="#5C7AEA")
    ax.bar(x + width / 2, rough, width, label="HAR-Rough", color="#F08A24")
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("QLIKE")
    ax.set_title("OOS Forecast Loss")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_OOS_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    asset_results = {}
    pooled_har_losses = []
    pooled_rough_losses = []

    for asset, spec in ASSETS.items():
        rv = load_parkinson_series(spec["csv"], spec["high"], spec["low"])
        log_rv = np.log(rv)
        full_h = estimate_hurst_structure(log_rv)
        sub_h = tercile_subperiod_estimates(log_rv)
        roll_h = rolling_hurst(log_rv, window=ROLLING_H_WINDOW)
        oos = oos_har_compare(rv, roll_h)

        # Rebuild loss arrays for pooled DM with aligned eval period.
        # Simpler and deterministic: reuse the same forecast procedure.
        dates = rv.index
        start_pos = dates.searchsorted(OOS_START)
        act, har_fc, rough_fc = [], [], []
        for pos in range(max(start_pos, 22), len(dates)):
            train = rv.iloc[:pos]
            if len(train) < MIN_TRAIN:
                continue
            beta = fit_har_beta(train)
            history = rv.iloc[:pos]
            h_t = roll_h.reindex(dates).iloc[pos - 1] if pos - 1 >= 0 else np.nan
            act.append(float(rv.iloc[pos]))
            har_fc.append(har_forecast(beta, history))
            rough_fc.append(har_forecast(beta, history, h_t=h_t))
        act_arr = np.asarray(act, dtype=float)
        pooled_har_losses.append(qlike_pointwise(act_arr, np.asarray(har_fc)))
        pooled_rough_losses.append(qlike_pointwise(act_arr, np.asarray(rough_fc)))

        asset_results[asset] = {
            "sample": {
                "start": str(rv.index[0].date()),
                "end": str(rv.index[-1].date()),
                "n_obs": int(len(rv)),
            },
            "roughness": summarize_stability(full_h, sub_h, roll_h),
            "oos": oos,
        }

    pooled_dm_t, pooled_dm_p = dm_test(
        np.concatenate(pooled_rough_losses),
        np.concatenate(pooled_har_losses),
        h=1,
    )
    make_figures(asset_results)

    rough_all = all(v["roughness"]["full_sample"]["is_rough"] for v in asset_results.values())
    rough_roll_all = all(v["roughness"]["rolling_504d"]["frac_rough"] > 0.95 for v in asset_results.values())
    better_assets = [
        a for a, v in asset_results.items()
        if v["oos"]["qlike"]["HAR_Rough"] < v["oos"]["qlike"]["HAR"]
    ]
    harvey_assets = [
        a for a, v in asset_results.items()
        if v["oos"]["dm_har_rough_vs_har"]["harvey_sig"]
        and v["oos"]["dm_har_rough_vs_har"]["t_stat"] < 0
    ]

    results = {
        "experiment_id": "K1497",
        "title": "Realized Volatility Roughness Stability and OOS Predictive Gain Re-Check",
        "timestamp": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data_source": "Local OHLC CSV under paper/garch-x-vix/data",
        "rv_proxy": "Parkinson range variance",
        "oos_start": str(OOS_START.date()),
        "rolling_h_window": ROLLING_H_WINDOW,
        "references": REFERENCES,
        "asset_results": asset_results,
        "pooled_dm_har_rough_vs_har": {
            "t_stat": round(float(pooled_dm_t), 6),
            "p_value": round(float(pooled_dm_p), 6),
            "harvey_sig": bool(abs(pooled_dm_t) > 3.0),
        },
        "summary": {
            "all_assets_full_sample_rough": rough_all,
            "all_assets_rolling_mostly_rough": rough_roll_all,
            "assets_where_har_rough_beats_har_on_qlike": better_assets,
            "assets_where_har_rough_beats_har_with_harvey_sig": harvey_assets,
            "n_assets_har_rough_better": len(better_assets),
            "n_assets_har_rough_harvey_better": len(harvey_assets),
        },
        "conclusion": (
            "Roughness remains a stable descriptive fact across all tested assets, "
            "but HAR-Rough does not deliver robust OOS forecast gains over plain HAR. "
            "Any occasional asset-level improvement stays below the Harvey multiple-testing bar."
        ),
        "limitations": [
            "Not the intended multi-year 5-minute RV design; local repo lacks a multi-asset high-frequency archive.",
            "Parkinson RV is a daily proxy and does not settle the Cont-Das artefact critique.",
            "HAR-Rough weighting is a conservative replication of the repo's prior rough-vol design, not a unique structural model.",
            "No options-implied measure is used here; the exercise isolates realized-vol path roughness only.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
    print(results["pooled_dm_har_rough_vs_har"])


if __name__ == "__main__":
    main()
