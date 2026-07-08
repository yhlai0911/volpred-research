"""
research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har
================================================================

Diagnostic experiment for the task:

    TSFM (TimesFM / TTM weights) x Log-HAR forecast combinations, evaluated by
    MCS + DM-HLN on SPY / 0050.TW / TAIFEX TX.

Research-honesty note
---------------------
The current project venv did not contain TimesFM/TTM at claim time. Installing
TimesFM was possible, but downloading google/timesfm-2.5-200m-pytorch weights
did not complete within the interactive smoke-test cap. Installing Granite TTM
would downgrade the project-required scikit-learn version from 1.8.0 to 1.7.2,
so it is treated as environment-blocked rather than installed into the shared
venv.

This script therefore produces a reproducible baseline/combination harness and
an explicit TSFM environment audit. It does not claim that TimesFM or TTM was
empirically evaluated unless their weights are present and code is extended to
run them.

Lookahead policy
----------------
For every forecast origin t:
  * y_t is already observed at close/session end t.
  * all HAR/EWMA features use y up to and including t.
  * the forecast target is y_{t+1}.
  * bias-correction for the combination uses only previous OOS forecast rows.
Pooled inference first aggregates losses by target date across assets, avoiding
asset-day iid pooling.
"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.stats.mcs import model_confidence_set
from volpred.stats.model_evaluation import qlike_pointwise
from volpred.utils import clean_tw50_data


EXPERIMENT_ID = "research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har"
HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
FORECAST_PATH = HERE / f"{EXPERIMENT_ID}_oos_forecasts.csv"

START = "2000-01-01"
END = "2026-07-01"
OOS_START_DEFAULT = "2019-01-01"
TX_OOS_START = "2021-01-01"
ROLL_WIN = 750
MIN_CALIBRATION_ROWS = 60
MCS_BOOT = 750
SEED = 42
EPS = 1e-12


@dataclass
class AssetSpec:
    asset: str
    source: str
    start: str
    end: str
    n_total: int
    n_oos: int
    target: str


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(text, encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def _flatten_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", ticker) in raw.columns:
            close = raw[("Close", ticker)]
        elif ("Adj Close", ticker) in raw.columns:
            close = raw[("Adj Close", ticker)]
        else:
            close = raw.xs("Close", axis=1, level=0).iloc[:, 0]
    else:
        close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
    close = close.dropna()
    close.name = ticker
    return close


def load_yfinance_variance(ticker: str) -> tuple[pd.DataFrame, AssetSpec]:
    raw = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError(f"yfinance returned empty data for {ticker}")
    close = _flatten_close(raw, ticker)
    if ticker == "0050.TW":
        close, ret_simple = clean_tw50_data(close)
        ret = np.log1p(ret_simple).replace([np.inf, -np.inf], np.nan)
        source = "Yahoo Finance adjusted close, cleaned with volpred.utils.clean_tw50_data"
    else:
        ret = np.log(close / close.shift(1))
        source = "Yahoo Finance adjusted close"
    y = (ret**2).rename("y")
    df = pd.DataFrame({"y": y}).dropna()
    df = df[df["y"] > 0]
    spec = AssetSpec(
        asset=ticker,
        source=source,
        start=str(df.index.min().date()),
        end=str(df.index.max().date()),
        n_total=int(len(df)),
        n_oos=0,
        target="next trading day's close-to-close squared log return",
    )
    return df, spec


def load_tx_variance() -> tuple[pd.DataFrame, AssetSpec]:
    path = Path("experiments/k1303/data/_tx1_daily_cj_2017-2026.parquet")
    df_raw = pd.read_parquet(path)
    df_raw["date"] = pd.to_datetime(df_raw["date"])
    df = (
        df_raw.set_index("date")
        .sort_index()[["rv"]]
        .rename(columns={"rv": "y"})
        .dropna()
    )
    df = df[df["y"] > 0]
    spec = AssetSpec(
        asset="TAIFEX_TX",
        source=str(path) + " (TAIFEX TX1 5-minute realized variance cache from prior reviewed experiment)",
        start=str(df.index.min().date()),
        end=str(df.index.max().date()),
        n_total=int(len(df)),
        n_oos=0,
        target="next trading session's TAIFEX TX 5-minute realized variance",
    )
    return df, spec


def _har_design(log_y: pd.Series) -> pd.DataFrame:
    # Origin t features for target y_{t+1}; rolling windows include y_t only.
    return pd.DataFrame(
        {
            "const": 1.0,
            "log_y_d": log_y,
            "log_y_w": log_y.rolling(5, min_periods=5).mean(),
            "log_y_m": log_y.rolling(22, min_periods=22).mean(),
        },
        index=log_y.index,
    )


def _ols_forecast(X_train: np.ndarray, y_train: np.ndarray, x_now: np.ndarray) -> float:
    try:
        beta, *_ = np.linalg.lstsq(X_train, y_train, rcond=None)
        pred = float(np.dot(x_now, beta))
    except Exception:
        pred = float(np.nanmean(y_train))
    return pred


def build_forecasts(asset: str, df: pd.DataFrame, oos_start: str) -> pd.DataFrame:
    y = df["y"].astype(float).clip(lower=EPS)
    log_y = np.log(y)
    X = _har_design(log_y)
    ewma = y.ewm(alpha=1 - 0.94, adjust=False).mean()
    rolling_mean = y.rolling(ROLL_WIN, min_periods=126).mean()

    rows: list[dict[str, Any]] = []
    values = y.to_numpy()
    log_values = log_y.to_numpy()
    dates = y.index
    X_values = X.to_numpy(dtype=float)

    for i in range(max(ROLL_WIN, 22), len(y) - 1):
        origin = dates[i]
        target_date = dates[i + 1]
        if origin < pd.Timestamp(oos_start):
            continue
        train_start = max(0, i - ROLL_WIN)
        # Train on prior forecast origins j whose y[j+1] is already observed at
        # origin i. The current origin i is excluded because y[i+1] is unknown.
        train_origins = np.arange(train_start, i)
        train_targets = train_origins + 1
        valid = (
            np.isfinite(X_values[train_origins]).all(axis=1)
            & np.isfinite(log_values[train_targets])
        )
        train_origins = train_origins[valid]
        train_targets = train_targets[valid]
        if len(train_origins) < 126 or not np.isfinite(X_values[i]).all():
            continue

        log_pred = _ols_forecast(X_values[train_origins], log_values[train_targets], X_values[i])
        har_pred = float(np.exp(log_pred))
        ewma_pred = float(ewma.iloc[i])
        const_pred = float(rolling_mean.iloc[i])
        if not np.isfinite(const_pred):
            const_pred = float(np.nanmean(values[train_targets]))

        rows.append(
            {
                "asset": asset,
                "origin_date": origin,
                "target_date": target_date,
                "actual": float(values[i + 1]),
                "HAR_log": max(har_pred, EPS),
                "EWMA_094": max(ewma_pred, EPS),
                "CONST_rollmean": max(const_pred, EPS),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["COMBO_equal_HAR_EWMA"] = 0.5 * out["HAR_log"] + 0.5 * out["EWMA_094"]

    corrected: list[float] = []
    prev_x: list[float] = []
    prev_y: list[float] = []
    for _, row in out.iterrows():
        base = float(row["COMBO_equal_HAR_EWMA"])
        if len(prev_x) >= MIN_CALIBRATION_ROWS:
            x = np.asarray(prev_x, dtype=float)
            yy = np.asarray(prev_y, dtype=float)
            A = np.column_stack([np.ones(len(x)), x])
            beta, *_ = np.linalg.lstsq(A, yy, rcond=None)
            pred = float(np.exp(beta[0] + beta[1] * np.log(max(base, EPS))))
        else:
            pred = base
        corrected.append(max(pred, EPS))
        prev_x.append(float(np.log(max(base, EPS))))
        prev_y.append(float(np.log(max(float(row["actual"]), EPS))))

    out["COMBO_biascorr_HAR_EWMA"] = corrected
    return out


def dm_hln(loss_model: np.ndarray, loss_benchmark: np.ndarray, h: int = 1) -> dict[str, Any]:
    d = np.asarray(loss_model, dtype=float) - np.asarray(loss_benchmark, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"t": None, "p_two": None, "n": int(n), "mean_diff": None, "harvey_pass": False}
    mean = float(d.mean())
    demeaned = d - mean
    # h=1 here, but keep NW form explicit.
    lag = max(0, h - 1)
    lrv = float(np.dot(demeaned, demeaned) / n)
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        lrv += 2.0 * w * float(np.dot(demeaned[k:], demeaned[:-k]) / n)
    se = float(np.sqrt(max(lrv, EPS) / n))
    hln_arg = (n + 1 - 2 * h + h * (h - 1) / n) / n
    hln = float(np.sqrt(hln_arg)) if hln_arg > 0 else 1.0
    t = float((mean / se) * hln)
    p = float(2 * (1 - stats.t.cdf(abs(t), df=n - 1)))
    return {
        "t": t,
        "p_two": p,
        "n": int(n),
        "mean_diff": mean,
        "hln_factor": hln,
        "harvey_pass": bool(abs(t) > 3.0),
        "direction": "model lower loss than benchmark" if mean < 0 else "model higher loss than benchmark",
    }


def evaluate(forecasts: pd.DataFrame, models: list[str]) -> dict[str, Any]:
    loss_cols: dict[str, np.ndarray] = {}
    for model in models:
        forecasts[f"loss_{model}"] = qlike_pointwise(forecasts["actual"].to_numpy(), forecasts[model].to_numpy())
        loss_cols[model] = forecasts[f"loss_{model}"].to_numpy()

    asset_summary: dict[str, Any] = {}
    for asset, g in forecasts.groupby("asset"):
        asset_summary[asset] = {
            "n_oos": int(len(g)),
            "period": [str(g["target_date"].min().date()), str(g["target_date"].max().date())],
            "mean_qlike": {m: float(g[f"loss_{m}"].mean()) for m in models},
            "combo_in_asset_mcs": None,
            "dm_vs_HAR_log": {
                m: dm_hln(g[f"loss_{m}"].to_numpy(), g["loss_HAR_log"].to_numpy())
                for m in models
                if m != "HAR_log"
            },
        }
        try:
            mcs = model_confidence_set(
                {m: g[f"loss_{m}"].to_numpy() for m in models},
                alpha=0.10,
                n_boot=MCS_BOOT,
                seed=SEED,
            )
            asset_summary[asset]["mcs"] = mcs
            asset_summary[asset]["combo_in_asset_mcs"] = {
                "COMBO_equal_HAR_EWMA": "COMBO_equal_HAR_EWMA" in mcs["mcs_models"],
                "COMBO_biascorr_HAR_EWMA": "COMBO_biascorr_HAR_EWMA" in mcs["mcs_models"],
            }
        except Exception as exc:
            asset_summary[asset]["mcs_error"] = repr(exc)

    # Date-level pooling: average loss per target date across available assets.
    pooled = (
        forecasts[["target_date"] + [f"loss_{m}" for m in models]]
        .groupby("target_date")
        .mean()
        .sort_index()
    )
    pooled_losses = {m: pooled[f"loss_{m}"].to_numpy() for m in models}
    pooled_mcs = model_confidence_set(pooled_losses, alpha=0.10, n_boot=MCS_BOOT, seed=SEED)

    return {
        "models": models,
        "asset_summary": asset_summary,
        "pooled_by_date": {
            "n_dates": int(len(pooled)),
            "period": [str(pooled.index.min().date()), str(pooled.index.max().date())],
            "mean_qlike": {m: float(pooled[f"loss_{m}"].mean()) for m in models},
            "mcs": pooled_mcs,
            "combo_in_pooled_mcs": {
                "COMBO_equal_HAR_EWMA": "COMBO_equal_HAR_EWMA" in pooled_mcs["mcs_models"],
                "COMBO_biascorr_HAR_EWMA": "COMBO_biascorr_HAR_EWMA" in pooled_mcs["mcs_models"],
            },
            "dm_vs_HAR_log": {
                m: dm_hln(pooled[f"loss_{m}"].to_numpy(), pooled["loss_HAR_log"].to_numpy())
                for m in models
                if m != "HAR_log"
            },
        },
    }


def audit_tsfm_environment() -> dict[str, Any]:
    audit: dict[str, Any] = {
        "timesfm": {
            "package_available": importlib.util.find_spec("timesfm") is not None,
            "repo": "google/timesfm-2.5-200m-pytorch",
            "weight_filename": "model.safetensors",
        },
        "ttm": {
            "granite_tsfm_available": importlib.util.find_spec("granite_tsfm") is not None,
            "transformers_available": importlib.util.find_spec("transformers") is not None,
            "repo_examples": [
                "ibm-granite/granite-timeseries-ttm-r1",
                "ibm-granite/granite-timeseries-ttm-r2",
            ],
        },
    }
    try:
        from huggingface_hub import try_to_load_from_cache

        repo = audit["timesfm"]["repo"]
        config_path = try_to_load_from_cache(repo, "config.json")
        weights_path = try_to_load_from_cache(repo, "model.safetensors")
        audit["timesfm"]["config_cached"] = bool(config_path and not isinstance(config_path, type(None)))
        audit["timesfm"]["weights_cached"] = bool(weights_path and not isinstance(weights_path, type(None)))
        audit["timesfm"]["cache_paths"] = {
            "config": str(config_path) if config_path else None,
            "weights": str(weights_path) if weights_path else None,
        }
    except Exception as exc:
        audit["timesfm"]["cache_check_error"] = repr(exc)

    audit["blocking_reasons"] = [
        "TimesFM package import is possible, but model.safetensors was not cached after a >150s smoke-test download attempt; no TimesFM forecasts are included.",
        "Granite TTM dry-run install would downgrade scikit-learn 1.8.0 to 1.7.2 in the shared project venv; no TTM forecasts are included.",
    ]
    return audit


def main() -> None:
    rng = np.random.default_rng(SEED)
    _ = rng.random()  # documents deterministic seed use for MCS and any future stochastic extension.

    asset_frames: list[pd.DataFrame] = []
    specs: list[AssetSpec] = []

    for ticker in ["SPY", "0050.TW"]:
        df, spec = load_yfinance_variance(ticker)
        f = build_forecasts(ticker, df, OOS_START_DEFAULT)
        spec.n_oos = int(len(f))
        asset_frames.append(f)
        specs.append(spec)

    tx_df, tx_spec = load_tx_variance()
    tx_f = build_forecasts("TAIFEX_TX", tx_df, TX_OOS_START)
    tx_spec.n_oos = int(len(tx_f))
    asset_frames.append(tx_f)
    specs.append(tx_spec)

    forecasts = pd.concat(asset_frames, ignore_index=True)
    forecasts["origin_date"] = pd.to_datetime(forecasts["origin_date"])
    forecasts["target_date"] = pd.to_datetime(forecasts["target_date"])
    forecasts = forecasts.sort_values(["asset", "origin_date"]).reset_index(drop=True)

    models = [
        "HAR_log",
        "EWMA_094",
        "CONST_rollmean",
        "COMBO_equal_HAR_EWMA",
        "COMBO_biascorr_HAR_EWMA",
    ]
    evaluation = evaluate(forecasts, models)
    forecasts.to_csv(FORECAST_PATH, index=False)

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "status": "BLOCKED_FOR_PRIMARY_TSFMS_BUT_BASELINE_HARNESS_EXECUTED",
        "seed": SEED,
        "data_sources": [asdict(s) for s in specs],
        "lookahead_policy": {
            "target": "forecast origin t predicts y[t+1]",
            "feature_lag": "HAR/EWMA features use y through t only; no y[t+1] feature leakage",
            "bias_correction": "uses previous OOS forecast rows only; first 60 rows fall back to equal-weight combo",
            "pooled_inference": "losses are averaged by target_date before pooled DM/MCS",
        },
        "tsfm_environment_audit": audit_tsfm_environment(),
        "executed_models": models,
        "evaluation": evaluation,
        "files": {
            "forecasts_csv": str(FORECAST_PATH.relative_to(HERE)),
            "results_json": str(RESULTS_PATH.relative_to(HERE)),
        },
        "literature_checked": [
            "Das et al. (2024), TimesFM / decoder-only foundation model for time-series forecasting, arXiv:2310.10688.",
            "Ekambaram et al. (2024), Tiny Time Mixers, arXiv:2401.03955.",
            "Hansen, Lunde and Nason (2011), Model Confidence Set, Econometrica.",
            "Diebold and Mariano (1995) plus Harvey-Leybourne-Newbold small-sample adjustment for forecast comparison.",
        ],
        "verdict": (
            "BLOCKED_PRIMARY_TSFMS: TimesFM/TTM weights were not available in this shared environment, "
            "so this run cannot answer whether TSFM+HAR combinations enter MCS. The baseline harness is "
            "complete and shows only HAR/EWMA combinations, not TSFM models."
        ),
    }
    _atomic_write_json(RESULTS_PATH, payload)

    print(json.dumps({"ok": True, "results": str(RESULTS_PATH), "n_rows": int(len(forecasts))}, indent=2))


if __name__ == "__main__":
    main()
