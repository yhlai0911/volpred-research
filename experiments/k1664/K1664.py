#!/usr/bin/env python3
"""K1664: 0050.TW local 5-minute HAR-RV pilot.

This experiment intentionally treats the current 0050.TW 5-minute archive as a
short-sample pilot.  Every forecasting feature is shifted by one trading day:
the row for target day t may only use RV information available through t-1.
"""

from __future__ import annotations

import argparse
import json
import math
import os
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
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

EXPERIMENT_ID = "K1664"
SEED = 42
EPS = 1e-16
ANNUALIZATION = 252

EXP_DIR = Path(__file__).resolve().parent
FIG_DIR = EXP_DIR / "figures"
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"
INTRADAY_DIR = REPO_ROOT / "data" / "intraday"
FILE_PATTERN = "0050_TW_5min_*.csv"


@dataclass(frozen=True)
class OLSFit:
    beta: np.ndarray
    residual_var: float
    r2: float


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, (np.ndarray,)):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp,)):
        return obj.date().isoformat()
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    with tmp.open("r", encoding="utf-8") as fh:
        json.load(fh)
    os.replace(tmp, path)


def parse_0050_file(path: Path) -> dict[str, Any]:
    """Parse a yfinance-style 5-minute CSV and return one daily RV row."""
    date = path.stem.replace("0050_TW_5min_", "")
    # yfinance wrote a three-row header.  Keeping the first row and skipping the
    # ticker/datetime metadata rows gives ordinary OHLCV columns.
    df = pd.read_csv(path, skiprows=[1, 2])
    if "Price" not in df.columns:
        raise ValueError(f"unexpected schema in {path}")
    df = df.rename(columns={"Price": "Datetime"})
    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True, errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Datetime", "Close"]).sort_values("Datetime")
    close = df["Close"].replace(0, np.nan).dropna()
    log_close = np.log(close)
    intraday_rets = log_close.diff().dropna()
    rv = float(np.sum(np.square(intraday_rets)))
    open_price = float(df["Open"].replace(0, np.nan).dropna().iloc[0])
    close_price = float(close.iloc[-1])
    high_price = float(df["High"].replace(0, np.nan).max())
    low_price = float(df["Low"].replace(0, np.nan).min())
    volume = float(df["Volume"].fillna(0).sum())
    return {
        "date": date,
        "path": str(path.relative_to(REPO_ROOT)),
        "n_rows": int(len(df)),
        "n_close": int(len(close)),
        "n_returns": int(len(intraday_rets)),
        "first_ts_utc": df["Datetime"].iloc[0].isoformat() if len(df) else None,
        "last_ts_utc": df["Datetime"].iloc[-1].isoformat() if len(df) else None,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "rv_5min_intraday": rv,
        "intraday_log_return": float(math.log(close_price / open_price)),
        "valid_for_har": bool(len(close) >= 45 and len(intraday_rets) >= 44 and rv > 0),
    }


def build_daily_rv() -> pd.DataFrame:
    files = sorted(INTRADAY_DIR.glob(FILE_PATTERN))
    rows = [parse_0050_file(path) for path in files]
    daily = pd.DataFrame(rows)
    if daily.empty:
        raise RuntimeError(f"no files matched {INTRADAY_DIR / FILE_PATTERN}")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").set_index("date")
    snapshot = daily.copy()
    snapshot.index = snapshot.index.strftime("%Y-%m-%d")
    snapshot.to_csv(DATA_DIR / "K1664_daily_5min_rv.csv", index_label="date")
    return daily


def add_forecast_features(daily: pd.DataFrame) -> pd.DataFrame:
    rv = daily.loc[daily["valid_for_har"], "rv_5min_intraday"].astype(float).sort_index()
    raw_signal = pd.DataFrame(
        {
            "rv_d": rv,
            "rv_w": rv.rolling(5, min_periods=5).mean(),
            "rv_m": rv.rolling(22, min_periods=22).mean(),
            "ewma20_raw": rv.ewm(span=20, adjust=False).mean(),
        }
    )
    # Explicit anti-lookahead rule: target day t uses only signals through t-1.
    signal = raw_signal.shift(1)
    data = signal.copy()
    data["target_rv"] = rv
    data["log_target_rv"] = np.log(np.maximum(data["target_rv"], EPS))
    for col in ["rv_d", "rv_w", "rv_m", "ewma20_raw"]:
        data[f"log_{col}"] = np.log(np.maximum(data[col], EPS))
    data.to_csv(DATA_DIR / "K1664_har_design_matrix.csv", index_label="date")
    return data


def fit_log_ols(df: pd.DataFrame, feature_cols: list[str]) -> OLSFit:
    y = df["log_target_rv"].to_numpy(dtype=float)
    x = df[feature_cols].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    residual_var = float(np.var(resid, ddof=min(len(beta), max(len(resid) - 1, 1))))
    return OLSFit(beta=beta, residual_var=max(residual_var, 0.0), r2=r2)


def predict_log_ols(fit: OLSFit, row: pd.Series, feature_cols: list[str]) -> float:
    x = np.array([1.0] + [float(row[col]) for col in feature_cols], dtype=float)
    pred_log = float(x @ fit.beta)
    # Lognormal mean correction.  Without it, log-HAR forecasts are medians and
    # can understate variance under QLIKE.
    return float(np.exp(pred_log + 0.5 * fit.residual_var))


def in_sample_summary(design: pd.DataFrame) -> dict[str, Any]:
    models = {
        "AR1_log": ["log_rv_d"],
        "HAR_DW_log": ["log_rv_d", "log_rv_w"],
        "HAR_DWM_log": ["log_rv_d", "log_rv_w", "log_rv_m"],
    }
    out: dict[str, Any] = {}
    for name, cols in models.items():
        df = design.dropna(subset=["target_rv", "log_target_rv", *cols])
        fit = fit_log_ols(df, cols)
        out[name] = {
            "n": int(len(df)),
            "features": cols,
            "r2_log_rv": fit.r2,
            "beta": fit.beta.tolist(),
            "residual_var_log": fit.residual_var,
        }
    return out


def circular_block_bootstrap_improvement(
    base_loss: np.ndarray,
    model_loss: np.ndarray,
    *,
    n_boot: int = 2000,
    block_len: int = 5,
    seed: int = SEED,
) -> dict[str, Any]:
    base = np.asarray(base_loss, dtype=float)
    model = np.asarray(model_loss, dtype=float)
    n = len(base)
    rng = np.random.default_rng(seed)
    stats_out: list[float] = []
    for _ in range(n_boot):
        idx: list[int] = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            idx.extend([(start + j) % n for j in range(block_len)])
        idx_arr = np.array(idx[:n], dtype=int)
        base_mean = float(np.mean(base[idx_arr]))
        model_mean = float(np.mean(model[idx_arr]))
        stats_out.append(100.0 * (base_mean - model_mean) / abs(base_mean))
    arr = np.asarray(stats_out)
    return {
        "n_boot": n_boot,
        "block_len": block_len,
        "seed": seed,
        "ci95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
        "mean": float(np.mean(arr)),
    }


def expanding_oos(design: pd.DataFrame, min_train: int = 60) -> tuple[pd.DataFrame, dict[str, Any]]:
    common = design.dropna(
        subset=[
            "target_rv",
            "rv_d",
            "rv_w",
            "rv_m",
            "ewma20_raw",
            "log_rv_d",
            "log_rv_w",
            "log_rv_m",
        ]
    ).copy()
    if len(common) <= min_train + 5:
        raise RuntimeError(f"not enough rows for OOS: rows={len(common)}, min_train={min_train}")

    model_features = {
        "HAR_DW_log": ["log_rv_d", "log_rv_w"],
        "HAR_DWM_log": ["log_rv_d", "log_rv_w", "log_rv_m"],
    }
    records: list[dict[str, Any]] = []
    for i in range(min_train, len(common)):
        train = common.iloc[:i]
        test = common.iloc[i]
        rec = {
            "date": common.index[i],
            "actual_rv": float(test["target_rv"]),
            "Persistence": float(test["rv_d"]),
            "EWMA20": float(test["ewma20_raw"]),
        }
        for name, cols in model_features.items():
            fit = fit_log_ols(train.dropna(subset=cols + ["target_rv", "log_target_rv"]), cols)
            rec[name] = predict_log_ols(fit, test, cols)
        records.append(rec)

    forecast_df = pd.DataFrame(records).set_index("date")
    forecast_out = forecast_df.copy()
    forecast_out.index = forecast_out.index.strftime("%Y-%m-%d")
    forecast_out.to_csv(DATA_DIR / "K1664_oos_forecasts.csv", index_label="date")

    actual = forecast_df["actual_rv"].to_numpy(dtype=float)
    model_names = ["Persistence", "EWMA20", "HAR_DW_log", "HAR_DWM_log"]
    losses = {name: qlike_pointwise(actual, forecast_df[name].to_numpy(dtype=float)) for name in model_names}
    metrics: dict[str, Any] = {}
    for name in model_names:
        pred = forecast_df[name].to_numpy(dtype=float)
        rho, rho_p = stats.spearmanr(actual, pred)
        metrics[name] = {
            "qlike": float(np.mean(losses[name])),
            "mse": float(np.mean((actual - pred) ** 2)),
            "log_mse": float(np.mean((np.log(np.maximum(actual, EPS)) - np.log(np.maximum(pred, EPS))) ** 2)),
            "mean_forecast_rv": float(np.mean(pred)),
            "spearman_rho": float(rho),
            "spearman_p": float(rho_p),
        }

    base = "Persistence"
    dm_vs_persistence: dict[str, Any] = {}
    for name in ["EWMA20", "HAR_DW_log", "HAR_DWM_log"]:
        t_stat, p_val = dm_test(losses[name], losses[base], h=1)
        q_improve = 100.0 * (metrics[base]["qlike"] - metrics[name]["qlike"]) / abs(metrics[base]["qlike"])
        dm_vs_persistence[name] = {
            "qlike_improvement_pct_vs_persistence": q_improve,
            "dm_t_model_minus_persistence": t_stat,
            "dm_p": p_val,
            "harvey_pass_model_better": bool(t_stat < -3.0),
            "block_bootstrap_improvement_pct": circular_block_bootstrap_improvement(
                losses[base], losses[name]
            ),
        }

    summary = {
        "n_common_rows_after_22d_lag": int(len(common)),
        "min_train": int(min_train),
        "n_oos": int(len(forecast_df)),
        "oos_start": forecast_df.index.min().date().isoformat(),
        "oos_end": forecast_df.index.max().date().isoformat(),
        "metrics": metrics,
        "dm_vs_persistence": dm_vs_persistence,
        "best_by_qlike": min(metrics, key=lambda k: metrics[k]["qlike"]),
        "forecast_file": str((DATA_DIR / "K1664_oos_forecasts.csv").relative_to(REPO_ROOT)),
    }
    return forecast_df, summary


def make_figures(daily: pd.DataFrame, forecast_df: pd.DataFrame, oos_summary: dict[str, Any]) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    valid = daily.loc[daily["valid_for_har"]].copy()
    ann_vol = np.sqrt(valid["rv_5min_intraday"].astype(float) * ANNUALIZATION) * 100
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.plot(valid.index, ann_vol, color="#2f6b9a", linewidth=1.8)
    ax.axhline(float(ann_vol.mean()), color="#9a2f2f", linewidth=1.2, linestyle="--", label="sample mean")
    ax.set_title("K1664 0050.TW 5-minute intraday realized volatility")
    ax.set_ylabel("Annualized intraday vol (%)")
    ax.set_xlabel("Date")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    p1 = FIG_DIR / "K1664_fig1_daily_5min_rv.png"
    fig.savefig(p1)
    plt.close(fig)
    paths.append(str(p1.relative_to(REPO_ROOT)))

    metrics = oos_summary["metrics"]
    names = list(metrics.keys())
    qlikes = [metrics[name]["qlike"] for name in names]
    colors = ["#666666", "#4d7c0f", "#b45309", "#1d4ed8"]
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    ax.bar(names, qlikes, color=colors)
    ax.set_title(f"K1664 one-step OOS QLIKE, n={oos_summary['n_oos']}")
    ax.set_ylabel("QLIKE loss (lower is better)")
    ax.grid(axis="y", alpha=0.25)
    for i, value in enumerate(qlikes):
        ax.text(i, value, f"{value:.3f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    p2 = FIG_DIR / "K1664_fig2_oos_qlike.png"
    fig.savefig(p2)
    plt.close(fig)
    paths.append(str(p2.relative_to(REPO_ROOT)))
    return paths


def run() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    daily = build_daily_rv()
    design = add_forecast_features(daily)
    forecast_df, oos_summary = expanding_oos(design, min_train=60)
    figures = make_figures(daily, forecast_df, oos_summary)

    valid = daily.loc[daily["valid_for_har"]].copy()
    rows_by_day = valid["n_rows"].astype(int)
    rv = valid["rv_5min_intraday"].astype(float)
    ann_vol = np.sqrt(rv * ANNUALIZATION) * 100
    best = oos_summary["best_by_qlike"]
    har_dwm_dm = oos_summary["dm_vs_persistence"]["HAR_DWM_log"]
    if har_dwm_dm["harvey_pass_model_better"]:
        verdict = "CONDITIONAL_PASS_SHORT_SAMPLE_HAR_DWM_BEATS_PERSISTENCE"
    elif har_dwm_dm["qlike_improvement_pct_vs_persistence"] > 0:
        verdict = "PILOT_DIRECTIONAL_HAR_EDGE_NO_HARVEY_PASS"
    else:
        verdict = "PILOT_NULL_SHORT_SAMPLE_NO_HAR_EDGE"

    payload: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "research_question": (
            "With the accumulated local 0050.TW 5-minute archive, can a lagged "
            "HAR-RV model forecast next-day intraday realized variance better "
            "than simple persistence?"
        ),
        "data": {
            "source": "local yfinance-style 5-minute CSV snapshots",
            "glob": str((INTRADAY_DIR / FILE_PATTERN).relative_to(REPO_ROOT)),
            "file_count": int(len(daily)),
            "valid_days": int(valid["valid_for_har"].sum()),
            "first_valid_date": valid.index.min().date().isoformat(),
            "last_valid_date": valid.index.max().date().isoformat(),
            "rows_per_day": {
                "min": int(rows_by_day.min()),
                "median": float(rows_by_day.median()),
                "max": int(rows_by_day.max()),
            },
            "rv_definition": (
                "intraday RV = sum of squared 5-minute close-to-close log returns "
                "within the regular Taiwan session; overnight return is excluded"
            ),
            "daily_snapshot": str((DATA_DIR / "K1664_daily_5min_rv.csv").relative_to(REPO_ROOT)),
            "design_matrix": str((DATA_DIR / "K1664_har_design_matrix.csv").relative_to(REPO_ROOT)),
        },
        "descriptive_stats": {
            "mean_daily_intraday_rv": float(rv.mean()),
            "median_daily_intraday_rv": float(rv.median()),
            "std_daily_intraday_rv": float(rv.std(ddof=1)),
            "mean_annualized_intraday_vol_pct": float(ann_vol.mean()),
            "median_annualized_intraday_vol_pct": float(ann_vol.median()),
            "max_annualized_intraday_vol_pct": float(ann_vol.max()),
            "max_vol_date": ann_vol.idxmax().date().isoformat(),
            "rv_lag1_autocorr": float(rv.autocorr(lag=1)),
            "rv_lag5_autocorr": float(rv.autocorr(lag=5)),
        },
        "method": {
            "model_family": "log-HAR-RV OLS, one-step expanding OOS",
            "features": {
                "rv_d": "previous trading day's 5-minute intraday RV",
                "rv_w": "mean of previous 5 trading days' RV, shifted one day",
                "rv_m": "mean of previous 22 trading days' RV, shifted one day",
            },
            "anti_lookahead": "raw_signal.shift(1) in add_forecast_features(); train rows strictly precede each OOS target row",
            "forecast_units": "daily intraday variance, not annualized",
            "evaluation": "Patton QLIKE via volpred.stats.model_evaluation.qlike_pointwise; DM/HAC h=1",
            "harvey_gate": "model improvement considered formal only when DM t < -3.0 versus persistence",
        },
        "in_sample": in_sample_summary(design),
        "oos": oos_summary,
        "figures": figures,
        "literature": [
            {
                "citation": "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064",
            },
            {
                "citation": "Andersen, Bollerslev, Diebold and Labys (2003), Modeling and Forecasting Realized Volatility",
                "url": "https://econ.duke.edu/~boller/Published_Papers/ecta_03.pdf",
            },
            {
                "citation": "Patton (2011), Volatility forecast comparison using imperfect volatility proxies",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S030440761000076X",
            },
            {
                "citation": "Liu, Patton and Sheppard (2015), Does anything beat 5-minute RV?",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304407615000329",
            },
        ],
        "limitations": [
            "The archive currently has only about half a year of 0050.TW 5-minute snapshots, so OOS inference is low power.",
            "RV is intraday-only and excludes overnight moves, which matter for Taiwan ETF close-to-close risk.",
            "The yfinance-style files are local snapshots rather than an exchange-certified historical feed.",
            "No claim is made about production superiority unless HAR beats persistence by the Harvey |t|>3 gate.",
        ],
        "review": {
            "reviewer": "Codex self-review primary path",
            "review_file": str((EXP_DIR / "codex_review.md").relative_to(REPO_ROOT)),
            "minimum_verdict_required_for_knowledge": "CONDITIONAL_PASS methodology review, even if empirical model edge is NULL",
        },
    }
    atomic_write_json(RESULTS_PATH, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    payload = run()
    if args.print_summary:
        print(json.dumps(_jsonable({
            "verdict": payload["verdict"],
            "valid_days": payload["data"]["valid_days"],
            "n_oos": payload["oos"]["n_oos"],
            "best_by_qlike": payload["oos"]["best_by_qlike"],
            "har_dwm_vs_persistence": payload["oos"]["dm_vs_persistence"]["HAR_DWM_log"],
        }), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
