#!/usr/bin/env python3
"""K1670: Interval-valued OHLC range forecasts vs point HAR intervals.

The task asks whether treating daily OHLC high-low data as an interval-valued
object improves interval forecast accuracy relative to a scalar point HAR-RV
style volatility forecast converted into an interval.

Target
------
For each day t, the observed price interval is measured relative to the prior
adjusted close:

    lower_t = log(Low_t / Close_{t-1})
    upper_t = log(High_t / Close_{t-1})

Models forecast [lower_t, upper_t] one day ahead.  Each model is calibrated on
the expanding training sample to an 80% containment target, then evaluated OOS
with interval MSE, containment coverage, and interval score.

Anti-lookahead policy
---------------------
Raw interval features are indexed by the date through which their inputs are
observed, then explicitly shifted with ``signal = raw_signal.shift(1)``.  OOS
row i is fit only on rows strictly before i.
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
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from volpred.stats.model_evaluation import dm_test  # noqa: E402


EXPERIMENT_ID = "K1670"
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
PRICE_CACHE = DATA_DIR / "prices_yfinance_auto_adjust.csv"

TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"]
START = "2005-01-01"
INITIAL_TRAIN = 1000
REFIT_FREQ = 21
NOMINAL_COVERAGE = 0.80
ALPHA = 1.0 - NOMINAL_COVERAGE
EPS = 1e-12

POINT_FEATURES = ["log_radius_d", "log_radius_w", "log_radius_m"]
CENTER_FEATURES = ["center_d", "center_w", "center_m", "close_ret_d", "close_ret_w", "close_ret_m"]
BOUNDS_FEATURES = [
    "lower_d",
    "lower_w",
    "lower_m",
    "upper_d",
    "upper_w",
    "upper_m",
    "center_d",
    "center_w",
    "center_m",
    "log_radius_d",
    "log_radius_w",
    "log_radius_m",
]
MODELS = ["point_har", "center_radius_interval", "bounds_direct_interval"]

REFERENCES = [
    {
        "key": "Huarng-Yu-Li-2025",
        "citation": "Huarng, K.-H., Yu, T. H.-K. and Li, Y. (2025), A Dynamic Fuzzy Modeling Method for Interval Time Series and its Application to Financial Market Forecasting, Journal of Forecasting 44(8), 2459-2477.",
        "url": "https://ideas.repec.org/a/wly/jforec/v44y2025i8p2459-2477.html",
        "role": "Direct interval-valued financial time-series motivation.",
    },
    {
        "key": "Fuzzy-RV-FTS-2026",
        "citation": "A Fuzzy Framework for Realized Volatility Prediction, Journal of Forecasting, 2026.",
        "url": "https://onlinelibrary.wiley.com/doi/10.1002/for.70082",
        "role": "Recent Journal of Forecasting fuzzy realized-volatility motivation.",
    },
    {
        "key": "Martens-van-Dijk-de-Pooter-2009",
        "citation": "Martens, M., van Dijk, D. and de Pooter, M. (2009), Forecasting S&P 500 volatility: Long memory, level shifts, leverage effects, day-of-the-week seasonality, and macroeconomic announcements, IJF 25(2), 282-303.",
        "url": "https://ideas.repec.org/a/eee/intfor/v25y2009i2p282-303.html",
        "role": "HAR-style realized-volatility benchmark motivation.",
    },
    {
        "key": "Christensen-Podolskij-2007",
        "citation": "Christensen, K. and Podolskij, M. (2007), Realized range-based estimation of integrated variance, Journal of Econometrics 141(2), 323-349.",
        "url": "https://public.econ.duke.edu/~get/browse/courses/201/spr12/DOWNLOADS/MicroStructure/cp_range_rv_joe_07.pdf",
        "role": "Range-based volatility estimation foundation.",
    },
]


@dataclass(frozen=True)
class OLSFit:
    beta: np.ndarray
    x_mean: np.ndarray
    x_std: np.ndarray
    residual_var: float
    r2: float
    log_positive: bool


@dataclass(frozen=True)
class IntervalState:
    model: str
    center_fit: OLSFit | None
    radius_fit: OLSFit | None
    lower_fit: OLSFit | None
    upper_fit: OLSFit | None
    calibration_multiplier: float
    train_coverage: float
    train_interval_mse: float


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
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp, datetime)):
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


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_or_load_prices(refresh: bool = False) -> pd.DataFrame:
    if PRICE_CACHE.exists() and not refresh:
        cached = pd.read_csv(PRICE_CACHE, parse_dates=["date"])
        return cached.sort_values(["ticker", "date"]).reset_index(drop=True)

    import yfinance as yf

    raw = yf.download(
        TICKERS,
        start=START,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")

    records: list[pd.DataFrame] = []
    for ticker in TICKERS:
        fields: dict[str, pd.Series] = {}
        for field in ["Open", "High", "Low", "Close", "Volume"]:
            if isinstance(raw.columns, pd.MultiIndex):
                if field not in raw.columns.get_level_values(0) or ticker not in raw[field].columns:
                    raise RuntimeError(f"Missing {field}/{ticker} in yfinance response")
                fields[field.lower()] = raw[field][ticker]
            else:
                fields[field.lower()] = raw[field]
        sub = pd.DataFrame(fields)
        sub.insert(0, "date", pd.to_datetime(sub.index).tz_localize(None))
        sub.insert(1, "ticker", ticker)
        records.append(sub)

    out = pd.concat(records, ignore_index=True)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    out.to_csv(PRICE_CACHE, index=False)
    return out


def build_interval_design(price: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker in TICKERS:
        sub = (
            price.loc[price["ticker"] == ticker]
            .dropna(subset=["open", "high", "low", "close"])
            .drop_duplicates("date", keep="last")
            .sort_values("date")
            .set_index("date")
        )
        for col in ["open", "high", "low", "close"]:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
        valid = (sub[["high", "low", "close"]] > 0).all(axis=1)
        sub = sub.loc[valid].copy()
        prev_close = sub["close"].shift(1)
        lower_raw = np.log(sub["low"] / prev_close)
        upper_raw = np.log(sub["high"] / prev_close)
        lower = np.minimum(lower_raw, upper_raw)
        upper = np.maximum(lower_raw, upper_raw)
        center = (lower + upper) / 2.0
        radius = ((upper - lower) / 2.0).clip(lower=EPS)
        close_ret = np.log(sub["close"] / prev_close)

        base = pd.DataFrame(
            {
                "target_lower": lower,
                "target_upper": upper,
                "target_center": center,
                "target_radius": radius,
                "target_width": upper - lower,
                "close_ret": close_ret,
                "parkinson_var": (np.log(sub["high"] / sub["low"]) ** 2) / (4.0 * np.log(2.0)),
            },
            index=sub.index,
        ).replace([np.inf, -np.inf], np.nan)

        raw_signal = pd.DataFrame(index=base.index)
        raw_signal["lower_d"] = base["target_lower"]
        raw_signal["lower_w"] = base["target_lower"].rolling(5, min_periods=5).mean()
        raw_signal["lower_m"] = base["target_lower"].rolling(22, min_periods=22).mean()
        raw_signal["upper_d"] = base["target_upper"]
        raw_signal["upper_w"] = base["target_upper"].rolling(5, min_periods=5).mean()
        raw_signal["upper_m"] = base["target_upper"].rolling(22, min_periods=22).mean()
        raw_signal["center_d"] = base["target_center"]
        raw_signal["center_w"] = base["target_center"].rolling(5, min_periods=5).mean()
        raw_signal["center_m"] = base["target_center"].rolling(22, min_periods=22).mean()
        raw_signal["log_radius_d"] = np.log(base["target_radius"].clip(lower=EPS))
        raw_signal["log_radius_w"] = np.log(base["target_radius"].rolling(5, min_periods=5).mean().clip(lower=EPS))
        raw_signal["log_radius_m"] = np.log(base["target_radius"].rolling(22, min_periods=22).mean().clip(lower=EPS))
        raw_signal["close_ret_d"] = base["close_ret"]
        raw_signal["close_ret_w"] = base["close_ret"].rolling(5, min_periods=5).mean()
        raw_signal["close_ret_m"] = base["close_ret"].rolling(22, min_periods=22).mean()

        # Explicit anti-lookahead rule: target day t uses interval signals through t-1.
        signal = raw_signal.shift(1)

        out = pd.concat([base, signal], axis=1)
        out["ticker"] = ticker
        frames.append(out.reset_index())

    design = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"])
    design.to_csv(DATA_DIR / "interval_design_matrix_shifted.csv", index=False)
    return design


def fit_ols(df: pd.DataFrame, y_col: str, feature_cols: list[str], *, log_positive: bool = False) -> OLSFit:
    work = df.dropna(subset=[y_col, *feature_cols]).copy()
    y_raw = work[y_col].to_numpy(dtype=float)
    if log_positive:
        y = np.log(np.maximum(y_raw, EPS))
    else:
        y = y_raw
    x_raw = work[feature_cols].to_numpy(dtype=float)
    x_mean = x_raw.mean(axis=0)
    x_std = x_raw.std(axis=0, ddof=0)
    x_std = np.where(x_std > 1e-12, x_std, 1.0)
    x = (x_raw - x_mean) / x_std
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    ddof = min(len(beta), max(len(resid) - 1, 1))
    residual_var = float(np.var(resid, ddof=ddof))
    return OLSFit(
        beta=beta,
        x_mean=x_mean,
        x_std=x_std,
        residual_var=max(residual_var, 0.0),
        r2=r2,
        log_positive=log_positive,
    )


def predict_ols(fit: OLSFit, df: pd.DataFrame | pd.Series, feature_cols: list[str]) -> np.ndarray | float:
    one_row = isinstance(df, pd.Series)
    if one_row:
        x_raw = np.array([[float(df[col]) for col in feature_cols]], dtype=float)
    else:
        x_raw = df[feature_cols].to_numpy(dtype=float)
    x = (x_raw - fit.x_mean) / fit.x_std
    x = np.column_stack([np.ones(len(x)), x])
    y = x @ fit.beta
    if fit.log_positive:
        y = np.exp(y + 0.5 * fit.residual_var)
        y = np.maximum(y, EPS)
    if one_row:
        return float(y[0])
    return y


def interval_losses(actual_lower: np.ndarray, actual_upper: np.ndarray, pred_lower: np.ndarray, pred_upper: np.ndarray) -> dict[str, np.ndarray]:
    width = np.maximum(pred_upper - pred_lower, EPS)
    contained = (pred_lower <= actual_lower) & (pred_upper >= actual_upper)
    interval_mse = (pred_lower - actual_lower) ** 2 + (pred_upper - actual_upper) ** 2
    miss_low = np.maximum(pred_lower - actual_lower, 0.0)
    miss_high = np.maximum(actual_upper - pred_upper, 0.0)
    interval_score = width + (2.0 / ALPHA) * (miss_low + miss_high)
    center_mse = (((pred_lower + pred_upper) / 2.0) - ((actual_lower + actual_upper) / 2.0)) ** 2
    radius_mse = (((pred_upper - pred_lower) / 2.0) - ((actual_upper - actual_lower) / 2.0)) ** 2
    return {
        "interval_mse": interval_mse,
        "interval_score": interval_score,
        "contained": contained.astype(float),
        "width": width,
        "center_mse": center_mse,
        "radius_mse": radius_mse,
    }


def calibrate_multiplier(train: pd.DataFrame, center: np.ndarray, radius: np.ndarray) -> tuple[float, float, float]:
    radius = np.maximum(np.asarray(radius, dtype=float), EPS)
    actual_lower = train["target_lower"].to_numpy(dtype=float)
    actual_upper = train["target_upper"].to_numpy(dtype=float)
    needed = np.maximum((actual_upper - center) / radius, (center - actual_lower) / radius)
    needed = needed[np.isfinite(needed)]
    needed = needed[needed > 0]
    if len(needed) < 10:
        multiplier = 1.0
    else:
        multiplier = float(np.quantile(needed, NOMINAL_COVERAGE))
    pred_lower = center - multiplier * radius
    pred_upper = center + multiplier * radius
    losses = interval_losses(actual_lower, actual_upper, pred_lower, pred_upper)
    train_cov = float(np.mean(losses["contained"]))
    train_imse = float(np.mean(losses["interval_mse"]))
    return max(multiplier, EPS), train_cov, train_imse


def fit_model_state(train: pd.DataFrame, model: str) -> IntervalState:
    if model == "point_har":
        radius_fit = fit_ols(train, "target_radius", POINT_FEATURES, log_positive=True)
        train_radius = predict_ols(radius_fit, train, POINT_FEATURES)
        train_center = np.zeros(len(train), dtype=float)
        multiplier, train_cov, train_imse = calibrate_multiplier(train, train_center, train_radius)
        return IntervalState(
            model=model,
            center_fit=None,
            radius_fit=radius_fit,
            lower_fit=None,
            upper_fit=None,
            calibration_multiplier=multiplier,
            train_coverage=train_cov,
            train_interval_mse=train_imse,
        )

    if model == "center_radius_interval":
        center_fit = fit_ols(train, "target_center", CENTER_FEATURES, log_positive=False)
        radius_fit = fit_ols(train, "target_radius", POINT_FEATURES, log_positive=True)
        train_center = predict_ols(center_fit, train, CENTER_FEATURES)
        train_radius = predict_ols(radius_fit, train, POINT_FEATURES)
        multiplier, train_cov, train_imse = calibrate_multiplier(train, train_center, train_radius)
        return IntervalState(
            model=model,
            center_fit=center_fit,
            radius_fit=radius_fit,
            lower_fit=None,
            upper_fit=None,
            calibration_multiplier=multiplier,
            train_coverage=train_cov,
            train_interval_mse=train_imse,
        )

    if model == "bounds_direct_interval":
        lower_fit = fit_ols(train, "target_lower", BOUNDS_FEATURES, log_positive=False)
        upper_fit = fit_ols(train, "target_upper", BOUNDS_FEATURES, log_positive=False)
        lower = predict_ols(lower_fit, train, BOUNDS_FEATURES)
        upper = predict_ols(upper_fit, train, BOUNDS_FEATURES)
        train_center = (lower + upper) / 2.0
        train_radius = np.maximum((upper - lower) / 2.0, EPS)
        multiplier, train_cov, train_imse = calibrate_multiplier(train, train_center, train_radius)
        return IntervalState(
            model=model,
            center_fit=None,
            radius_fit=None,
            lower_fit=lower_fit,
            upper_fit=upper_fit,
            calibration_multiplier=multiplier,
            train_coverage=train_cov,
            train_interval_mse=train_imse,
        )

    raise ValueError(f"Unknown model: {model}")


def predict_interval(state: IntervalState, row: pd.Series) -> tuple[float, float, float, float]:
    if state.model == "point_har":
        assert state.radius_fit is not None
        center = 0.0
        radius = float(predict_ols(state.radius_fit, row, POINT_FEATURES))
    elif state.model == "center_radius_interval":
        assert state.center_fit is not None and state.radius_fit is not None
        center = float(predict_ols(state.center_fit, row, CENTER_FEATURES))
        radius = float(predict_ols(state.radius_fit, row, POINT_FEATURES))
    elif state.model == "bounds_direct_interval":
        assert state.lower_fit is not None and state.upper_fit is not None
        lower = float(predict_ols(state.lower_fit, row, BOUNDS_FEATURES))
        upper = float(predict_ols(state.upper_fit, row, BOUNDS_FEATURES))
        center = (lower + upper) / 2.0
        radius = max((upper - lower) / 2.0, EPS)
    else:
        raise ValueError(state.model)

    radius = max(radius, EPS) * state.calibration_multiplier
    return center - radius, center + radius, center, radius


def run_asset_oos(design: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    needed_cols = [
        "target_lower",
        "target_upper",
        "target_center",
        "target_radius",
        *POINT_FEATURES,
        *CENTER_FEATURES,
        *BOUNDS_FEATURES,
    ]
    work = (
        design.loc[design["ticker"] == ticker]
        .dropna(subset=list(dict.fromkeys(needed_cols)))
        .sort_values("date")
        .reset_index(drop=True)
    )
    if len(work) <= INITIAL_TRAIN + 252:
        raise RuntimeError(f"{ticker}: insufficient rows after interval lags ({len(work)})")

    records: list[dict[str, Any]] = []
    states: dict[str, IntervalState] = {}
    next_refit = INITIAL_TRAIN
    for i in range(INITIAL_TRAIN, len(work)):
        if i >= next_refit or not states:
            train = work.iloc[:i].copy()
            states = {model: fit_model_state(train, model) for model in MODELS}
            next_refit = i + REFIT_FREQ
        row = work.iloc[i]
        record: dict[str, Any] = {
            "date": row["date"],
            "ticker": ticker,
            "actual_lower": float(row["target_lower"]),
            "actual_upper": float(row["target_upper"]),
            "actual_center": float(row["target_center"]),
            "actual_radius": float(row["target_radius"]),
            "train_n": int(i),
        }
        for model, state in states.items():
            lower, upper, center, radius = predict_interval(state, row)
            record[f"{model}_lower"] = lower
            record[f"{model}_upper"] = upper
            record[f"{model}_center"] = center
            record[f"{model}_radius"] = radius
            record[f"{model}_train_multiplier"] = state.calibration_multiplier
            record[f"{model}_train_coverage"] = state.train_coverage
        records.append(record)

    forecast = pd.DataFrame(records)
    actual_lower = forecast["actual_lower"].to_numpy(dtype=float)
    actual_upper = forecast["actual_upper"].to_numpy(dtype=float)
    summary: dict[str, Any] = {
        "ticker": ticker,
        "n_design_rows": int(len(work)),
        "n_oos": int(len(forecast)),
        "forecast_start": pd.Timestamp(forecast["date"].iloc[0]).date().isoformat(),
        "forecast_end": pd.Timestamp(forecast["date"].iloc[-1]).date().isoformat(),
        "initial_train": INITIAL_TRAIN,
        "refit_freq": REFIT_FREQ,
        "models": {},
        "comparisons_vs_point_har": {},
    }

    for model in MODELS:
        losses = interval_losses(
            actual_lower,
            actual_upper,
            forecast[f"{model}_lower"].to_numpy(dtype=float),
            forecast[f"{model}_upper"].to_numpy(dtype=float),
        )
        for loss_name, values in losses.items():
            forecast[f"{model}_{loss_name}"] = values
        summary["models"][model] = {
            "interval_mse": float(np.mean(losses["interval_mse"])),
            "interval_score": float(np.mean(losses["interval_score"])),
            "coverage": float(np.mean(losses["contained"])),
            "mean_width": float(np.mean(losses["width"])),
            "center_mse": float(np.mean(losses["center_mse"])),
            "radius_mse": float(np.mean(losses["radius_mse"])),
            "mean_train_multiplier": float(np.mean(forecast[f"{model}_train_multiplier"])),
            "mean_train_coverage": float(np.mean(forecast[f"{model}_train_coverage"])),
        }

    base_loss = forecast["point_har_interval_mse"].to_numpy(dtype=float)
    base_score = forecast["point_har_interval_score"].to_numpy(dtype=float)
    for model in ["center_radius_interval", "bounds_direct_interval"]:
        model_loss = forecast[f"{model}_interval_mse"].to_numpy(dtype=float)
        model_score = forecast[f"{model}_interval_score"].to_numpy(dtype=float)
        dm_t, dm_p = dm_test(model_loss, base_loss, h=1)
        score_dm_t, score_dm_p = dm_test(model_score, base_score, h=1)
        base_mean = float(np.mean(base_loss))
        model_mean = float(np.mean(model_loss))
        score_base = float(np.mean(base_score))
        score_model = float(np.mean(model_score))
        summary["comparisons_vs_point_har"][model] = {
            "interval_mse_improvement_pct": float((base_mean - model_mean) / base_mean * 100.0),
            "interval_mse_dm_t": dm_t,
            "interval_mse_dm_p": dm_p,
            "interval_mse_harvey_pass": bool(dm_t < -3.0 and model_mean < base_mean),
            "interval_score_improvement_pct": float((score_base - score_model) / score_base * 100.0),
            "interval_score_dm_t": score_dm_t,
            "interval_score_dm_p": score_dm_p,
            "coverage_minus_point_har_pp": float(
                100.0
                * (
                    summary["models"][model]["coverage"]
                    - summary["models"]["point_har"]["coverage"]
                )
            ),
            "coverage_error_from_nominal_pp": float(
                100.0 * (summary["models"][model]["coverage"] - NOMINAL_COVERAGE)
            ),
        }

    return forecast, summary


def aggregate_comparison(forecasts: pd.DataFrame, model: str) -> dict[str, Any]:
    cols = ["point_har_interval_mse", f"{model}_interval_mse", "point_har_interval_score", f"{model}_interval_score"]
    clustered = forecasts.groupby("date", as_index=False)[cols].mean().sort_values("date")
    base_loss = clustered["point_har_interval_mse"].to_numpy(dtype=float)
    model_loss = clustered[f"{model}_interval_mse"].to_numpy(dtype=float)
    base_score = clustered["point_har_interval_score"].to_numpy(dtype=float)
    model_score = clustered[f"{model}_interval_score"].to_numpy(dtype=float)
    dm_t, dm_p = dm_test(model_loss, base_loss, h=1)
    score_dm_t, score_dm_p = dm_test(model_score, base_score, h=1)
    base_mean = float(np.mean(base_loss))
    model_mean = float(np.mean(model_loss))
    score_base = float(np.mean(base_score))
    score_model = float(np.mean(model_score))
    coverage = forecasts.groupby("date", as_index=False)[
        ["point_har_contained", f"{model}_contained"]
    ].mean()
    return {
        "model": model,
        "n_dates": int(len(clustered)),
        "date_start": pd.Timestamp(clustered["date"].iloc[0]).date().isoformat(),
        "date_end": pd.Timestamp(clustered["date"].iloc[-1]).date().isoformat(),
        "interval_mse_point_har": base_mean,
        f"interval_mse_{model}": model_mean,
        "interval_mse_improvement_pct": float((base_mean - model_mean) / base_mean * 100.0),
        "interval_mse_dm_t": dm_t,
        "interval_mse_dm_p": dm_p,
        "interval_mse_harvey_pass": bool(dm_t < -3.0 and model_mean < base_mean),
        "interval_score_point_har": score_base,
        f"interval_score_{model}": score_model,
        "interval_score_improvement_pct": float((score_base - score_model) / score_base * 100.0),
        "interval_score_dm_t": score_dm_t,
        "interval_score_dm_p": score_dm_p,
        "point_har_coverage": float(coverage["point_har_contained"].mean()),
        f"{model}_coverage": float(coverage[f"{model}_contained"].mean()),
        "coverage_minus_point_har_pp": float(
            100.0 * (coverage[f"{model}_contained"].mean() - coverage["point_har_contained"].mean())
        ),
    }


def make_figures(asset_summaries: dict[str, Any], aggregate: dict[str, Any]) -> list[str]:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    rows = []
    for ticker, item in asset_summaries.items():
        for model in ["center_radius_interval", "bounds_direct_interval"]:
            comp = item["comparisons_vs_point_har"][model]
            rows.append(
                {
                    "ticker": ticker,
                    "model": model,
                    "improvement": comp["interval_mse_improvement_pct"],
                    "pass": comp["interval_mse_harvey_pass"],
                }
            )
    bar = pd.DataFrame(rows)
    labels = TICKERS
    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10.7, 5.3))
    for offset, model, color in [
        (-width / 2, "center_radius_interval", "#4E79A7"),
        (width / 2, "bounds_direct_interval", "#F28E2B"),
    ]:
        vals = [bar.loc[(bar["ticker"] == t) & (bar["model"] == model), "improvement"].iloc[0] for t in labels]
        ax.bar(x + offset, vals, width, label=model.replace("_", " "), color=color, alpha=0.9)
        for idx, val in enumerate(vals):
            ax.text(
                idx + offset,
                val + (0.05 if val >= 0 else -0.05),
                f"{val:+.1f}%",
                ha="center",
                va="bottom" if val >= 0 else "top",
                fontsize=7,
            )
    ax.axhline(0, color="#333333", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Interval MSE improvement vs point HAR (%)")
    ax.set_title("K1670: Interval-valued forecasts vs scalar point HAR interval")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig1 = FIG_DIR / "K1670_fig1_interval_mse_improvement.png"
    fig.savefig(fig1, bbox_inches="tight")
    plt.close(fig)

    cov_rows = []
    for model in MODELS:
        vals = [asset_summaries[t]["models"][model]["coverage"] for t in TICKERS]
        cov_rows.append({"model": model, "coverage": float(np.mean(vals))})
    cov = pd.DataFrame(cov_rows)
    fig, ax = plt.subplots(figsize=(10.7, 5.3))
    colors = ["#59A14F", "#4E79A7", "#F28E2B"]
    ax.bar(cov["model"].str.replace("_", " "), cov["coverage"] * 100.0, color=colors, alpha=0.9)
    ax.axhline(NOMINAL_COVERAGE * 100.0, color="#333333", lw=1.0, ls="--", label="80% nominal")
    for idx, row in cov.iterrows():
        ax.text(idx, row["coverage"] * 100.0 + 0.5, f"{row['coverage']*100.0:.1f}%", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("OOS full-interval containment coverage (%)")
    ax.set_title("K1670: OOS coverage after expanding 80% train calibration")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig2 = FIG_DIR / "K1670_fig2_interval_coverage.png"
    fig.savefig(fig2, bbox_inches="tight")
    plt.close(fig)

    aggregate_df = pd.DataFrame(
        [
            {
                "model": model,
                "improvement": aggregate[model]["interval_mse_improvement_pct"],
                "dm_t": aggregate[model]["interval_mse_dm_t"],
                "coverage": aggregate[model][f"{model}_coverage"],
            }
            for model in ["center_radius_interval", "bounds_direct_interval"]
        ]
    )
    aggregate_df.to_csv(DATA_DIR / "aggregate_interval_comparison_summary.csv", index=False)
    return [str(fig1.relative_to(HERE)), str(fig2.relative_to(HERE))]


def derive_verdict(aggregate: dict[str, Any]) -> dict[str, Any]:
    passes = [
        model
        for model, item in aggregate.items()
        if item["interval_mse_harvey_pass"] and item[f"{model}_coverage"] >= NOMINAL_COVERAGE - 0.05
    ]
    weak = [
        model
        for model, item in aggregate.items()
        if item["interval_mse_improvement_pct"] >= 0.5
        and item[f"{model}_coverage"] >= NOMINAL_COVERAGE - 0.05
    ]
    if passes:
        verdict = "CONDITIONAL_PASS_INTERVAL_IMSE_EDGE"
        plain = "At least one interval-valued model improves date-clustered OOS interval MSE beyond point HAR while keeping coverage near the 80% target."
    elif weak:
        verdict = "WEAK_INTERVAL_EDGE_NO_HARVEY_PASS"
        plain = "Interval-valued models have economically nontrivial positive OOS interval-MSE point estimates but do not clear the Harvey t<-3 gate."
    else:
        verdict = "NULL_NO_INTERVAL_EDGE"
        plain = "Interval-valued OHLC models do not improve OOS interval-MSE forecasts beyond a calibrated scalar point-HAR interval baseline."
    return {"verdict": verdict, "plain_english": plain, "pass_models": passes, "weak_models": weak}


def run(refresh: bool = False) -> dict[str, Any]:
    ensure_dirs()
    price = download_or_load_prices(refresh=refresh)
    design = build_interval_design(price)
    forecasts: list[pd.DataFrame] = []
    asset_summaries: dict[str, Any] = {}
    for ticker in TICKERS:
        forecast, summary = run_asset_oos(design, ticker)
        forecasts.append(forecast)
        asset_summaries[ticker] = summary
    all_forecasts = pd.concat(forecasts, ignore_index=True).sort_values(["date", "ticker"])
    all_forecasts.to_csv(DATA_DIR / "oos_interval_forecasts.csv", index=False)

    aggregate = {
        model: aggregate_comparison(all_forecasts, model)
        for model in ["center_radius_interval", "bounds_direct_interval"]
    }
    figures = make_figures(asset_summaries, aggregate)
    verdict = derive_verdict(aggregate)

    price_summary = (
        price.dropna(subset=["close"])
        .groupby("ticker")
        .agg(first_date=("date", "min"), last_date=("date", "max"), rows=("close", "count"))
        .reset_index()
    )

    payload: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict["verdict"],
        "plain_english": verdict["plain_english"],
        "data": {
            "source": "Yahoo Finance via yfinance.download(auto_adjust=True)",
            "tickers": TICKERS,
            "start": START,
            "price_cache": str(PRICE_CACHE.relative_to(HERE)),
            "price_rows_by_ticker": price_summary.to_dict(orient="records"),
            "target_interval": "[log(Low_t/Close_{t-1}), log(High_t/Close_{t-1})]",
            "nominal_coverage": NOMINAL_COVERAGE,
        },
        "methodology": {
            "baseline": "point_har: scalar log-HAR forecast for interval half-width with zero center, calibrated to 80% training containment",
            "center_radius_interval": "OLS HAR center forecast plus log-HAR radius forecast, calibrated to 80% training containment",
            "bounds_direct_interval": "separate OLS forecasts for next lower and upper interval bounds using lagged interval features, calibrated to 80% training containment",
            "anti_lookahead": "raw interval features are shifted with signal = raw_signal.shift(1); expanding OOS row i uses work.iloc[:i]",
            "primary_loss": "interval_mse = (forecast_lower - actual_lower)^2 + (forecast_upper - actual_upper)^2",
            "secondary_loss": "interval score with alpha=0.20 and penalties for actual interval not contained",
            "inference": "Diebold-Mariano HAC h=1 on date-clustered daily average losses; Harvey pass requires challenger-better t < -3",
            "initial_train": INITIAL_TRAIN,
            "refit_freq": REFIT_FREQ,
        },
        "asset_results": asset_summaries,
        "aggregate_date_clustered": aggregate,
        "verdict_details": verdict,
        "figures": figures,
        "references": REFERENCES,
        "research_honesty_notes": [
            "This is a daily OHLC interval proxy experiment, not a 5-minute realized-volatility replication.",
            "The baseline is intentionally strong: it is calibrated to the same 80% training containment target as the interval-valued models.",
            "Interval containment and interval MSE answer an interval-forecasting question; they should not be rephrased as scalar RV QLIKE superiority.",
        ],
    }
    atomic_write_json(RESULTS_PATH, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download yfinance data")
    args = parser.parse_args()
    payload = run(refresh=args.refresh)
    print(f"{EXPERIMENT_ID} {payload['verdict']}: {payload['plain_english']}")
    for model, item in payload["aggregate_date_clustered"].items():
        print(
            f"  {model}: interval MSE improvement={item['interval_mse_improvement_pct']:+.3f}% "
            f"DM t={item['interval_mse_dm_t']:.3f} coverage={item[f'{model}_coverage']:.3f}"
        )
    print(f"Results: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
