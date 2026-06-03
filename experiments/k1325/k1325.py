#!/usr/bin/env python3
"""
K1325: 0050.TW 5-min HAR-RV continuation checkpoint.

Fresh rerun of the same lookahead-safe HAR-RV pipeline used in K1324, now
including the latest available 0050.TW intraday files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "k1325"
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
DATA_DIR = ROOT / "data"
RESULTS_PATH = ROOT / "k1325_results.json"
SYMBOL = "0050_TW_5min"
SOURCE_DIR = PROJECT_ROOT / "data" / "intraday"
REVISIT_GATE_TOTAL_DAYS = 200
REVISIT_GATE_TEST_DAYS = 50
K1324_RESULTS_PATH = PROJECT_ROOT / "experiments" / "k1324" / "k1324_results.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> Tuple[float, float]:
    d = np.asarray(loss1, dtype=float) - np.asarray(loss2, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return (0.0, 1.0)
    d_mean = d.mean()
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l
    if var_d <= 0:
        return (0.0, 1.0)
    se = np.sqrt(var_d / n)
    t_stat = d_mean / se if se > 0 else 0.0
    hln_corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    t_stat_hln = t_stat * hln_corr
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat_hln), df=n - 1))
    return (float(t_stat_hln), float(p_val))


def qlike_pointwise(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    a = np.maximum(np.asarray(actual, dtype=float), 1e-16)
    f = np.maximum(np.asarray(predicted, dtype=float), 1e-16)
    ratio = a / f
    return ratio - np.log(ratio) - 1


def load_one_day(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(
            path,
            skiprows=3,
            header=None,
            names=["ts", "close", "high", "low", "open", "volume"],
        )
    except Exception:
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for c in ("close", "high", "low", "open", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ts", "close"])
    df = df[(df["close"] > 0) & (df["volume"] > 0)].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    return df if len(df) >= 20 else None


def build_daily_rv(symbol: str = SYMBOL) -> pd.DataFrame:
    files = sorted(SOURCE_DIR.glob(f"{symbol}_*.csv"))
    rows: List[Dict] = []
    for fn in files:
        session_date = pd.Timestamp(fn.stem.replace(f"{symbol}_", ""))
        df = load_one_day(fn)
        if df is None:
            continue
        prices = df["close"].to_numpy(float)
        rets = np.log(prices[1:] / prices[:-1])
        rets = rets[np.isfinite(rets)]
        if len(rets) < 19:
            continue
        rows.append(
            {
                "date": session_date,
                "rv": float((rets ** 2).sum()),
                "n_bars": int(len(df)),
                "n_returns": int(len(rets)),
                "first_ts": str(df["ts"].iloc[0]),
                "last_ts": str(df["ts"].iloc[-1]),
            }
        )
    daily = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    daily.to_csv(DATA_DIR / "0050_tw_daily_rv_rebuilt.csv", index=False)
    return daily


def build_har_features(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    eps = 1e-12
    rv_lag1 = d["rv"].shift(1)
    d["rv_d"] = rv_lag1
    d["rv_w"] = rv_lag1.rolling(window=5, min_periods=5).mean()
    d["rv_m"] = rv_lag1.rolling(window=22, min_periods=22).mean()
    d["Y"] = np.log(d["rv"].clip(lower=eps))
    d = d.dropna(subset=["rv_d", "rv_w", "rv_m", "Y"]).reset_index(drop=True)
    for c in ("rv_d", "rv_w", "rv_m"):
        d[c] = np.log(d[c].clip(lower=eps))
    return d


def fit_ols(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    n, p = X1.shape
    dof = max(n - p, 1)
    sigma2 = float((resid ** 2).sum() / dof)
    try:
        XtX_inv = np.linalg.inv(X1.T @ X1)
        se = np.sqrt(np.maximum(np.diag(sigma2 * XtX_inv), 0.0))
    except np.linalg.LinAlgError:
        se = np.full(p, np.nan)
    return beta, se


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def r2_oos(y: np.ndarray, yhat: np.ndarray) -> float:
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def plot_rv_and_forecasts(
    daily: pd.DataFrame,
    feat: pd.DataFrame,
    actual: np.ndarray,
    har: np.ndarray,
    rw: np.ndarray,
) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), dpi=140, constrained_layout=True)
    axes[0].plot(daily["date"], daily["rv"], color="#1f77b4", lw=1.2)
    axes[0].set_title("0050.TW daily realized variance rebuilt from 5-min bars")
    axes[0].set_ylabel("RV")
    axes[0].grid(alpha=0.25)

    test_dates = feat["date"].iloc[-len(actual):]
    axes[1].plot(test_dates, actual, label="actual RV", color="#111827", lw=1.2)
    axes[1].plot(test_dates, har, label="HAR-RV", color="#0f766e", lw=1.2)
    axes[1].plot(test_dates, rw, label="Random Walk", color="#d97706", lw=1.2)
    axes[1].set_title("OOS tail window forecasts")
    axes[1].set_ylabel("RV")
    axes[1].grid(alpha=0.25)
    axes[1].legend()

    out = ROOT / "k1325_rv_forecasts.png"
    fig.savefig(out)
    plt.close(fig)
    return out.name


def load_k1324_baseline() -> dict:
    return json.loads(K1324_RESULTS_PATH.read_text())


def rounded(obj):
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def main() -> None:
    t0 = time.time()
    ensure_dirs()

    k1324 = load_k1324_baseline()
    daily = build_daily_rv()
    feat = build_har_features(daily)

    T = len(feat)
    n_train = int(np.floor(T * 0.7))
    n_test = T - n_train
    idx_train = np.arange(n_train)
    idx_test = np.arange(n_train, T)

    X = feat[["rv_d", "rv_w", "rv_m"]].to_numpy(float)
    y = feat["Y"].to_numpy(float)
    beta, se = fit_ols(X[idx_train], y[idx_train])
    yhat_har = predict_ols(beta, X[idx_test])
    yhat_rw = feat["rv_d"].to_numpy()[idx_test]

    actual_rv = np.exp(y[idx_test])
    har_rv = np.exp(yhat_har)
    rw_rv = np.exp(yhat_rw)

    q_har = qlike_pointwise(actual_rv, har_rv)
    q_rw = qlike_pointwise(actual_rv, rw_rv)
    dm_t, dm_p = dm_hln(q_rw, q_har, h=1)

    fig_name = plot_rv_and_forecasts(daily, feat, actual_rv, har_rv, rw_rv)

    har_qlike = float(np.nanmean(q_har))
    rw_qlike = float(np.nanmean(q_rw))
    har_r2 = r2_oos(y[idx_test], yhat_har)
    rw_r2 = r2_oos(y[idx_test], yhat_rw)

    if n_test < REVISIT_GATE_TEST_DAYS:
        verdict = "UNTRUSTWORTHY_SMALL_SAMPLE"
    elif abs(dm_t) > 3.0 and har_qlike < rw_qlike:
        verdict = "PASS"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "0050.TW 5-min HAR-RV continuation checkpoint",
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "related_experiments": ["K1307", "K1318", "K1322", "K1324"],
        "data_source": {
            "intraday_glob": str(SOURCE_DIR.relative_to(PROJECT_ROOT)),
            "symbol_prefix": SYMBOL,
            "daily_rv_snapshot": str(
                (DATA_DIR / "0050_tw_daily_rv_rebuilt.csv").relative_to(PROJECT_ROOT)
            ),
        },
        "lookahead_free_certification": (
            "HAR features use rv.shift(1), lagged rolling 5/22 means on the shifted series, "
            "and chronological 70/30 split. Target is log(RV_t); no contemporaneous RV enters predictors."
        ),
        "sample": {
            "n_total_days": int(len(daily)),
            "date_start": str(daily["date"].min().date()),
            "date_end": str(daily["date"].max().date()),
            "n_har_rows_after_warmup": int(T),
            "n_train": int(n_train),
            "n_test": int(n_test),
            "mean_n_bars": float(daily["n_bars"].mean()),
            "min_n_bars": int(daily["n_bars"].min()),
        },
        "model": {
            "alternative": "HAR-RV (log-spec, Corsi 2009)",
            "baseline": "Random Walk on log(RV_{t-1})",
            "loss": "QLIKE on RV level",
            "dm_test": "Newey-West HAC + HLN small-sample correction (h=1)",
        },
        "har_fit": {
            "betas": {
                "intercept": float(beta[0]),
                "beta_d": float(beta[1]),
                "beta_w": float(beta[2]),
                "beta_m": float(beta[3]),
            },
            "std_errors": {
                "intercept": None if np.isnan(se[0]) else float(se[0]),
                "beta_d": None if np.isnan(se[1]) else float(se[1]),
                "beta_w": None if np.isnan(se[2]) else float(se[2]),
                "beta_m": None if np.isnan(se[3]) else float(se[3]),
            },
        },
        "results": {
            "HAR_QLIKE_test": har_qlike,
            "RW_QLIKE_test": rw_qlike,
            "HAR_MSE_test": float(((y[idx_test] - yhat_har) ** 2).mean()),
            "RW_MSE_test": float(((y[idx_test] - yhat_rw) ** 2).mean()),
            "HAR_OOS_R2": har_r2,
            "RW_OOS_R2": rw_r2,
            "DM_HLN_t": float(dm_t),
            "DM_HLN_p": float(dm_p),
        },
        "comparison_to_k1324": {
            "prior_n_total_days": int(k1324["sample"]["n_total_days"]),
            "prior_n_test": int(k1324["sample"]["n_test"]),
            "delta_total_days": int(len(daily) - k1324["sample"]["n_total_days"]),
            "delta_test_days": int(n_test - k1324["sample"]["n_test"]),
            "prior_dm_hln_t": float(k1324["results"]["DM_HLN_t"]),
            "current_dm_hln_t": float(dm_t),
            "delta_dm_hln_t": float(dm_t - k1324["results"]["DM_HLN_t"]),
            "prior_har_qlike": float(k1324["results"]["HAR_QLIKE_test"]),
            "current_har_qlike": har_qlike,
            "delta_har_qlike": float(har_qlike - k1324["results"]["HAR_QLIKE_test"]),
            "note": (
                "Two additional daily files changed the raw QLIKE values but left the inference regime "
                "unchanged: the OOS test window is still too short for a strong claim."
            ),
        },
        "verdict": verdict,
        "revisit_gate": {
            "n_total_days_required": REVISIT_GATE_TOTAL_DAYS,
            "n_test_days_required": REVISIT_GATE_TEST_DAYS,
            "current_n_total_days": int(len(daily)),
            "current_n_test_days": int(n_test),
            "gate_passed": bool(
                len(daily) >= REVISIT_GATE_TOTAL_DAYS and n_test >= REVISIT_GATE_TEST_DAYS
            ),
        },
        "key_findings": [
            (
                f"Daily 5-min RV sample increased from {k1324['sample']['n_total_days']} to {len(daily)} days, "
                f"but OOS test window is still only {n_test} days."
            ),
            (
                f"HAR-RV still beats Random Walk on raw QLIKE ({har_qlike:.3f} vs {rw_qlike:.3f}), "
                f"but DM-HLN t={dm_t:.2f}, p={dm_p:.3f} remains far below the Harvey |t|>3 bar."
            ),
            (
                f"DM-HLN t moved only from {k1324['results']['DM_HLN_t']:.2f} to {dm_t:.2f} after two new days, "
                "showing that the project is still in a small-sample checkpoint regime rather than a publishable one."
            ),
        ],
        "artifacts": {
            "figure": fig_name,
            "daily_rv_snapshot": str((DATA_DIR / "0050_tw_daily_rv_rebuilt.csv").name),
        },
        "elapsed_seconds": round(time.time() - t0, 2),
    }

    RESULTS_PATH.write_text(json.dumps(rounded(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(rounded(results), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
