#!/usr/bin/env python3
"""K1378 corrected leave-COVID-out A4f versus GJR comparison.

This rerun preserves K1378's broad COVID sensitivity window while replacing
the invalid loss orientation, iid DM inference, inconsistent A4f recursion,
and mutable duplicate-date input.  K1393 remains the Paper 9 narrow-window
COVID analysis; K1378 is a supplemental broad-window/public-claim repair.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize, stats

from volpred.stats.model_evaluation import (
    dm_test as canonical_dm_test,
    qlike_pointwise,
)


SEED = 42
OOS_START = "2019-01-01"
OOS_END = "2026-05-18"
WINDOW = 2000
REFIT_EVERY = 63
HORIZON = 1
HARVEY_THRESHOLD = 3.0
COVID_START = "2020-03-01"
COVID_END = "2021-06-30"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
SNAPSHOT_CSV = (
    PROJECT_ROOT
    / "experiments"
    / "k1685"
    / "data"
    / "k1685_spy_vix_snapshot.csv"
)
EXPECTED_SNAPSHOT_SHA256 = (
    "eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb"
)


@njit(cache=True)
def gjr_loglik(params: np.ndarray, returns: np.ndarray) -> float:
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[: min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (
                np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t]
            )
    return -ll


def fit_gjr(returns: np.ndarray) -> np.ndarray | None:
    """Fit GJR by deterministic multistart MLE; reject failed optimizers."""
    var0 = float(np.var(returns))
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (1e-8, var0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    for start in starts:
        try:
            result = optimize.minimize(
                gjr_loglik,
                start,
                args=(returns,),
                method="L-BFGS-B",
                bounds=bounds,
            )
            if (
                result.success
                and np.isfinite(result.fun)
                and np.all(np.isfinite(result.x))
                and result.fun < best_ll
            ):
                best_ll = float(result.fun)
                best_params = np.asarray(result.x, dtype=np.float64)
        except Exception:  # silent-ok: one deterministic start may diverge; caller fails closed if every start fails.
            pass
    return best_params


def gjr_1step(params: np.ndarray, h_prev: float, r_prev: float) -> float:
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns: np.ndarray, log_vix_values: np.ndarray) -> np.ndarray | None:
    """Fit A4f with tau_t predetermined by VIX_{t-1}."""
    infeasible_objective = 1e10
    n = len(returns)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_values[0]
    log_vix_lag[1:] = log_vix_values[:-1]
    vix_lag = np.exp(log_vix_lag)

    def negative_loglik(params: np.ndarray) -> float:
        theta0, theta1, omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return infeasible_objective
        persistence = alpha + gamma / 2.0 + beta
        if persistence >= 1.0:
            return infeasible_objective
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
        g = omega / (1.0 - persistence)
        ll = 0.0
        for t in range(1, n):
            # Engle-style contemporaneous scale: tau_t is known from VIX_{t-1}.
            u_prev = returns[t - 1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma * u_prev**2 if u_prev < 0 else 0.0
            g = omega + alpha * u_prev**2 + asym + beta * g
            g = max(g, 1e-10)
            sigma2 = tau[t] * g
            ll += -0.5 * (
                np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2
            )
        return -ll

    var0 = float(np.var(returns))
    mean_vix2 = float(np.mean(vix_lag**2)) + 1e-8
    starts = [
        [var0 * 0.1, var0 / mean_vix2, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / mean_vix2 * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / mean_vix2 * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-8, 1e-3),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for start in starts:
        try:
            result = optimize.minimize(
                negative_loglik,
                start,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 500},
            )
            params = np.asarray(result.x, dtype=np.float64)
            persistence = params[3] + params[4] / 2.0 + params[5]
            if (
                result.success
                and np.isfinite(result.fun)
                and np.all(np.isfinite(params))
                and result.fun < infeasible_objective
                and params[2] > 0
                and params[3] >= 0
                and params[4] >= 0
                and params[5] >= 0
                and persistence < 1.0
                and result.fun < best_ll
            ):
                best_ll = float(result.fun)
                best_params = params
        except Exception:  # silent-ok: one deterministic start may diverge; caller fails closed if every start fails.
            pass
    return best_params


def load_analysis_data() -> tuple[pd.DataFrame, dict]:
    """Load and validate the hash-pinned, unique-date source packet."""
    snapshot_bytes = SNAPSHOT_CSV.read_bytes()
    snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
    if snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise RuntimeError(
            "Pinned snapshot hash mismatch: "
            f"expected {EXPECTED_SNAPSHOT_SHA256}, got {snapshot_sha256}"
        )

    raw = pd.read_csv(SNAPSHOT_CSV, parse_dates=["date"], index_col="date")
    raw.index = pd.to_datetime(raw.index)
    required_columns = {"spy_close", "vix_close"}
    if not required_columns.issubset(raw.columns):
        raise RuntimeError(
            f"Pinned snapshot is missing columns: {sorted(required_columns - set(raw.columns))}"
        )
    if raw.index.has_duplicates:
        duplicate_dates = raw.index[raw.index.duplicated(keep=False)].unique()
        raise RuntimeError(
            "Pinned snapshot contains duplicate dates: "
            + ", ".join(str(value.date()) for value in duplicate_dates[:10])
        )
    if not raw.index.is_monotonic_increasing:
        raise RuntimeError("Pinned snapshot dates are not strictly increasing")

    snapshot_start = raw.index.min()
    snapshot_end = raw.index.max()
    analysis_raw = raw.loc[:OOS_END].copy()
    analysis_slice_csv = analysis_raw.to_csv(
        index=True,
        index_label="date",
        date_format="%Y-%m-%d",
        float_format="%.17g",
        na_rep="",
        lineterminator="\n",
    )
    analysis_slice_sha256 = hashlib.sha256(
        analysis_slice_csv.encode("utf-8")
    ).hexdigest()

    prices = analysis_raw["spy_close"].dropna()
    log_returns = np.log(prices / prices.shift(1))
    vix_close = analysis_raw["vix_close"].dropna()
    frame = pd.DataFrame({"log_ret": log_returns, "VIX": vix_close}).dropna()
    metadata = {
        "snapshot_sha256": snapshot_sha256,
        "snapshot_start": str(snapshot_start.date()),
        "snapshot_end": str(snapshot_end.date()),
        "analysis_slice_sha256": analysis_slice_sha256,
    }
    return frame, metadata


def rolling_forecasts(
    returns: np.ndarray,
    vix: np.ndarray,
    oos_indices: np.ndarray,
    started_at: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Generate strictly one-step-ahead forecasts from t-1 information."""
    n_oos = len(oos_indices)
    forecast_gjr = np.full(n_oos, np.nan)
    forecast_a4f = np.full(n_oos, np.nan)
    log_vix = np.log(np.maximum(vix, 1.0))
    gjr_state: dict[str, np.ndarray | float | None] = {
        "params": None,
        "h": None,
    }
    a4f_state: dict[str, np.ndarray | float | None] = {
        "params": None,
        "g": None,
    }
    refit_count = 0

    for oos_position, absolute_index in enumerate(oos_indices):
        if oos_position % 500 == 0:
            print(
                f"  OOS step {oos_position}/{n_oos} "
                f"({time.time() - started_at:.1f}s)"
            )

        if oos_position % REFIT_EVERY == 0:
            train_start = max(0, absolute_index - WINDOW)
            train_returns = returns[train_start:absolute_index]
            train_log_vix = log_vix[train_start:absolute_index]
            refit_count += 1

            gjr_params = fit_gjr(train_returns)
            if gjr_params is None:
                raise RuntimeError(
                    f"All GJR optimizer starts failed at OOS step {oos_position}"
                )
            gjr_state["params"] = gjr_params
            h_state = float(np.var(train_returns))
            for index in range(1, len(train_returns)):
                h_state = gjr_1step(
                    gjr_params,
                    h_state,
                    float(train_returns[index - 1]),
                )
            gjr_state["h"] = h_state

            a4f_params = fit_a4f(train_returns, train_log_vix)
            if a4f_params is None:
                raise RuntimeError(
                    f"All A4f optimizer starts failed at OOS step {oos_position}"
                )
            a4f_state["params"] = a4f_params
            theta0, theta1, omega, alpha, gamma, beta = a4f_params
            persistence = alpha + gamma / 2.0 + beta
            lagged_log_vix = np.empty(len(train_returns))
            lagged_log_vix[0] = train_log_vix[0]
            lagged_log_vix[1:] = train_log_vix[:-1]
            tau_train = np.maximum(
                theta0 + theta1 * np.exp(lagged_log_vix) ** 2,
                1e-16,
            )
            g_state = omega / (1.0 - persistence)
            for index in range(1, len(train_returns)):
                u_prev = train_returns[index - 1] / np.sqrt(tau_train[index])
                asym = gamma * u_prev**2 if u_prev < 0 else 0.0
                g_state = omega + alpha * u_prev**2 + asym + beta * g_state
                g_state = max(g_state, 1e-10)
            a4f_state["g"] = g_state

        gjr_params = np.asarray(gjr_state["params"], dtype=np.float64)
        h_state = gjr_1step(
            gjr_params,
            float(gjr_state["h"]),
            float(returns[absolute_index - 1]),
        )
        forecast_gjr[oos_position] = h_state
        gjr_state["h"] = h_state

        a4f_params = np.asarray(a4f_state["params"], dtype=np.float64)
        theta0, theta1, omega, alpha, gamma, beta = a4f_params
        # Forecast sigma_t^2 uses VIX_{t-1}; no day-t return or VIX enters.
        tau_t = max(theta0 + theta1 * vix[absolute_index - 1] ** 2, 1e-16)
        u_prev = returns[absolute_index - 1] / np.sqrt(tau_t)
        asym = gamma * u_prev**2 if u_prev < 0 else 0.0
        g_state = (
            omega
            + alpha * u_prev**2
            + asym
            + beta * float(a4f_state["g"])
        )
        g_state = max(g_state, 1e-10)
        forecast_a4f[oos_position] = tau_t * g_state
        a4f_state["g"] = g_state

    return forecast_gjr, forecast_a4f, refit_count


def acf_diagnostics(values: np.ndarray, max_lag: int = 5) -> dict[str, float | None]:
    values = np.asarray(values, dtype=np.float64)
    centered = values - np.mean(values)
    denominator = float(np.dot(centered, centered))
    diagnostics: dict[str, float | None] = {}
    for lag in range(1, max_lag + 1):
        diagnostics[f"lag_{lag}"] = (
            float(np.dot(centered[lag:], centered[:-lag]) / denominator)
            if len(values) > lag and denominator > 0
            else None
        )
    return diagnostics


def canonical_hac_lag(n: int, horizon: int = HORIZON) -> int:
    return max(
        1,
        min(int(np.ceil(horizon ** (1 / 3) * n ** (1 / 3))), n // 4),
    )


def nw_t_at_lag(values: np.ndarray, max_lag: int) -> float | None:
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    mean = float(np.mean(values))
    centered = values - mean
    long_run_variance = float(np.mean(centered**2))
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocovariance = float(np.mean(centered[lag:] * centered[:-lag]))
        long_run_variance += 2.0 * weight * autocovariance
    if not np.isfinite(long_run_variance) or long_run_variance <= 0:
        return None
    return float(mean / np.sqrt(long_run_variance / n))


def summarize_period(
    label: str,
    mask: np.ndarray,
    dates: pd.DatetimeIndex,
    loss_a4f: np.ndarray,
    loss_gjr: np.ndarray,
) -> dict:
    """Summarize one exact date subset with its own canonical HAC bandwidth."""
    period_dates = dates[mask]
    a4f = loss_a4f[mask]
    gjr = loss_gjr[mask]
    if len(a4f) < 10:
        raise RuntimeError(f"{label}: insufficient valid observations ({len(a4f)})")
    differential = a4f - gjr
    dm_t, dm_p = canonical_dm_test(a4f, gjr, h=HORIZON)
    hac_lag = canonical_hac_lag(len(differential))
    sensitivity_lags = sorted({0, 1, 5, 10, hac_lag, 20})
    sensitivity = {
        f"lag_{lag}": {
            "dm_t": nw_t_at_lag(differential, lag),
            "hac_applied": bool(lag > 0),
        }
        for lag in sensitivity_lags
    }
    if not np.isclose(
        dm_t,
        sensitivity[f"lag_{hac_lag}"]["dm_t"],
        rtol=1e-12,
        atol=1e-12,
    ):
        raise RuntimeError(f"{label}: canonical DM disagrees with HAC audit path")

    hln_factor = float(
        np.sqrt(
            (
                len(differential)
                + 1
                - 2 * HORIZON
                + HORIZON * (HORIZON - 1) / len(differential)
            )
            / len(differential)
        )
    )
    hln_t = float(dm_t * hln_factor)
    hln_p = float(2.0 * stats.t.sf(abs(hln_t), df=len(differential) - 1))
    harvey_pass = bool(abs(dm_t) > HARVEY_THRESHOLD)
    harvey_winner = "A4f" if harvey_pass and dm_t < 0 else "GJR" if harvey_pass else None
    mean_a4f = float(np.mean(a4f))
    mean_gjr = float(np.mean(gjr))
    return {
        "label": label,
        "n": int(len(differential)),
        "start": str(period_dates[0].date()),
        "end": str(period_dates[-1].date()),
        "a4f_qlike_mean": mean_a4f,
        "gjr_qlike_mean": mean_gjr,
        "loss_differential": "A4f_minus_GJR",
        "mean_loss_differential": float(np.mean(differential)),
        "a4f_qlike_advantage_pct": float(
            100.0 * (mean_gjr - mean_a4f) / mean_gjr
        ),
        "loss_differential_acf": acf_diagnostics(differential),
        "hac_max_lag": hac_lag,
        "hac_lag_sensitivity": sensitivity,
        "dm_t": float(dm_t),
        "dm_p": float(dm_p),
        "dm_sign_convention": "A4f loss minus GJR loss; negative t favors A4f",
        "harvey_threshold": HARVEY_THRESHOLD,
        "harvey_pass": harvey_pass,
        "harvey_winner": harvey_winner,
        "hln_diagnostic": {
            "factor": hln_factor,
            "dm_t": hln_t,
            "dm_p": hln_p,
            "primary": False,
        },
    }


def atomic_save_npy(path: Path, values: np.ndarray) -> str:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            np.save(handle, values, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        verified = np.load(temporary, allow_pickle=False)
        if (
            verified.shape != values.shape
            or verified.dtype != values.dtype
            or not np.array_equal(verified, values, equal_nan=True)
        ):
            raise RuntimeError(f"Atomic NPY verification failed for {path.name}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with temporary.open(encoding="utf-8") as handle:
            json.load(handle)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def corrected_verdict(no_covid_result: dict) -> str:
    if no_covid_result["harvey_winner"] == "A4f":
        return "A4F_ROBUST_OUTSIDE_BROAD_COVID_WINDOW"
    if no_covid_result["harvey_winner"] == "GJR":
        return "GJR_ROBUST_OUTSIDE_BROAD_COVID_WINDOW"
    return "NO_HARVEY_WINNER_OUTSIDE_BROAD_COVID_WINDOW"


def main() -> None:
    np.random.seed(SEED)
    started_at = time.time()
    print("=" * 72)
    print("K1378 corrected leave-COVID-out A4f versus GJR comparison")
    print("=" * 72)

    frame, source_metadata = load_analysis_data()
    returns = frame["log_ret"].to_numpy(dtype=np.float64)
    vix = frame["VIX"].to_numpy(dtype=np.float64)
    squared_returns = returns**2
    oos_mask = (frame.index >= OOS_START) & (frame.index <= OOS_END)
    oos_indices = np.flatnonzero(oos_mask)
    oos_dates = frame.index[oos_indices]
    print(
        f"Data {frame.index[0].date()} to {frame.index[-1].date()}, "
        f"n={len(frame):,}; OOS forecast dates={len(oos_indices):,}"
    )

    forecast_gjr, forecast_a4f, refit_count = rolling_forecasts(
        returns,
        vix,
        oos_indices,
        started_at,
    )
    actual_oos = squared_returns[oos_indices]
    if not np.all(np.isfinite(actual_oos)):
        bad_dates = oos_dates[~np.isfinite(actual_oos)]
        raise RuntimeError(
            "Non-finite OOS squared returns: "
            + ", ".join(str(value.date()) for value in bad_dates[:10])
        )
    forecast_valid = (
        np.isfinite(forecast_gjr)
        & (forecast_gjr > 0)
        & np.isfinite(forecast_a4f)
        & (forecast_a4f > 0)
    )
    if not np.all(forecast_valid):
        bad_dates = oos_dates[~forecast_valid]
        raise RuntimeError(
            "Non-finite or non-positive OOS forecasts: "
            + ", ".join(str(value.date()) for value in bad_dates[:10])
        )
    valid = actual_oos > 1e-16
    excluded_zero_returns = int(
        np.sum(np.isfinite(actual_oos) & (actual_oos <= 1e-16))
    )
    if int(np.sum(valid)) != len(actual_oos) - excluded_zero_returns:
        raise RuntimeError("Shared scoring mask does not match zero-return policy")

    # Patton QLIKE is actual / predicted, never predicted / actual.
    loss_gjr = qlike_pointwise(actual_oos, forecast_gjr)
    loss_a4f = qlike_pointwise(actual_oos, forecast_a4f)
    covid_dates = (oos_dates >= COVID_START) & (oos_dates <= COVID_END)
    period_masks = {
        "full_oos": valid,
        "no_covid_oos": valid & ~covid_dates,
        "pre_covid_oos": valid & (oos_dates < COVID_START),
        "covid_only_oos": valid & covid_dates,
        "post_covid_oos": valid & (oos_dates > COVID_END),
    }
    pre_mask = period_masks["pre_covid_oos"]
    covid_mask = period_masks["covid_only_oos"]
    post_mask = period_masks["post_covid_oos"]
    if np.any(pre_mask & covid_mask) or np.any(pre_mask & post_mask) or np.any(
        covid_mask & post_mask
    ):
        raise RuntimeError("Pre/COVID/post scoring periods are not mutually exclusive")
    if not np.array_equal(pre_mask | covid_mask | post_mask, valid):
        raise RuntimeError("Pre/COVID/post scoring periods do not partition full OOS")
    if not np.array_equal(
        pre_mask | post_mask,
        period_masks["no_covid_oos"],
    ):
        raise RuntimeError("Combined non-COVID mask does not equal pre plus post")
    labels = {
        "full_oos": "Full OOS",
        "no_covid_oos": "OOS excluding broad COVID window",
        "pre_covid_oos": "Pre-COVID OOS",
        "covid_only_oos": "Broad COVID window only",
        "post_covid_oos": "Post-COVID OOS",
    }
    periods = {
        key: summarize_period(
            labels[key],
            mask,
            oos_dates,
            loss_a4f,
            loss_gjr,
        )
        for key, mask in period_masks.items()
    }

    array_values = {
        "k1378_losses_gjr.npy": loss_gjr,
        "k1378_losses_a4f.npy": loss_a4f,
        "k1378_valid_mask.npy": valid,
        "k1378_no_covid_mask.npy": np.asarray(~covid_dates, dtype=bool),
    }
    array_hashes = {
        name: atomic_save_npy(SCRIPT_DIR / name, values)
        for name, values in array_values.items()
    }

    elapsed = time.time() - started_at
    no_covid = periods["no_covid_oos"]
    zero_return_dates = [
        str(value.date())
        for value in oos_dates[
            np.isfinite(actual_oos) & (actual_oos <= 1e-16)
        ]
    ]
    code_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    results = {
        "experiment_id": "k1378",
        "title": "Corrected broad-window leave-COVID-out A4f versus GJR comparison",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "metadata": {
            "methodology_type": "empirical one-step-ahead forecast comparison",
            "data_source": "experiments/k1685/data/k1685_spy_vix_snapshot.csv",
            "data_source_provenance": "Independent yfinance 1.2.0 SPY/^VIX fetch pinned by K1685 on 2026-07-11; unique dates verified before analysis.",
            "input_columns": {
                "price": "spy_close (unadjusted close; matches corrected K1379 protocol)",
                "volatility_index": "vix_close",
            },
            "snapshot_expected_sha256": EXPECTED_SNAPSHOT_SHA256,
            "code_sha256": code_sha256,
            **source_metadata,
            "data_start": str(frame.index[0].date()),
            "data_end": str(frame.index[-1].date()),
            "n_data": int(len(frame)),
            "oos_policy_start": OOS_START,
            "oos_end": OOS_END,
            "first_forecast_date": str(oos_dates[0].date()),
            "last_forecast_date": str(oos_dates[-1].date()),
            "first_valid_oos_date": str(oos_dates[valid][0].date()),
            "last_valid_oos_date": str(oos_dates[valid][-1].date()),
            "n_oos_forecast_dates": int(len(oos_dates)),
            "n_valid_oos": int(np.sum(valid)),
            "n_zero_return_excluded": excluded_zero_returns,
            "zero_return_excluded_dates": zero_return_dates,
            "zero_return_policy": "Exclude r_squared <= 1e-16 from the shared QLIKE/DM mask for both models.",
            "covid_exclusion_start": COVID_START,
            "covid_exclusion_end": COVID_END,
            "covid_window_scope": "K1378 broad sensitivity window; K1393 uses the narrower Paper 9 window 2020-02-01 to 2020-06-30.",
            "covid_exclusion_semantics": "Scoring-only exclusion: post-COVID rolling fits may contain COVID observations in their trailing estimation window.",
            "window": WINDOW,
            "refit_every": REFIT_EVERY,
            "refit_count": refit_count,
            "forecast_horizon_days": HORIZON,
            "seed": SEED,
            "qlike_proxy": "daily squared log return",
            "qlike_formula": "actual/predicted - log(actual/predicted) - 1",
            "proxy_caveat": "Daily squared return is a noisy proxy; Patton robustness is an expected-loss result under conditional-unbiasedness assumptions, not a guarantee for every finite sample.",
            "a4f_information_set": "sigma_t uses VIX_{t-1} and r_{t-1}; no day-t information",
            "a4f_normalization": "u_{t-1}=r_{t-1}/sqrt(tau_t), where tau_t is predetermined by VIX_{t-1}; identical in fit and OOS recursion.",
            "dm_method": "volpred.stats.model_evaluation.dm_test with Bartlett Newey-West HAC",
            "dm_hac_bandwidth_rule": "max(1, min(ceil(h^(1/3) * n^(1/3)), n//4)) applied separately to each period",
            "dm_sign_convention": "A4f loss minus GJR loss; negative t favors A4f",
            "dm_small_sample_correction": "none for primary; correct HLN factor reported diagnostically",
            "harvey_reporting_threshold": HARVEY_THRESHOLD,
            "saved_array_sha256": array_hashes,
        },
        "periods": periods,
        # Compatibility aliases are generated from the same period objects.
        "full_oos": periods["full_oos"],
        "no_covid_oos": periods["no_covid_oos"],
        "covid_only_oos": periods["covid_only_oos"],
        "verdict": {
            "primary_period": "no_covid_oos",
            "classification": corrected_verdict(no_covid),
            "harvey_winner": no_covid["harvey_winner"],
            "interpretation": (
                "A4f retains a Harvey-screened lower QLIKE outside K1378's broad COVID window."
                if no_covid["harvey_winner"] == "A4f"
                else "GJR retains a Harvey-screened lower QLIKE outside K1378's broad COVID window."
                if no_covid["harvey_winner"] == "GJR"
                else "Neither model clears the |t|>3 screen outside K1378's broad COVID window."
            ),
        },
        "methodology_repair": {
            "supersedes_k1378_pre_repair_artifact": True,
            "pre_repair_knowledge_item": "k1378_sf1",
            "pre_repair_issues": [
                "QLIKE ratio was inverted as predicted/actual",
                "h=1 DM variance omitted all autocovariances and became iid",
                "A4f fit normalized by tau_t while OOS recursion normalized by tau_{t-1}",
                "mutable Paper 9 CSV was not protected against duplicate dates",
                "optimizer success, finite objectives, and infeasible penalty were not fail-closed",
                "results JSON was written non-atomically",
            ],
            "comparison_caveat": "The rerun jointly changes loss orientation, HAC inference, A4f recursion, optimizer acceptance, and input provenance; old/new differences cannot be attributed to any one repair.",
            "relation_to_k1393": "K1393 remains the Paper 9 narrow-COVID-window result. This corrected K1378 uses its original broader 2020-03-01 to 2021-06-30 sensitivity window and must not replace K1393's paper table.",
        },
        "references": [
            {
                "authors": "Patton, A.J.",
                "year": 2011,
                "title": "Volatility forecast comparison using imperfect volatility proxies",
                "journal": "Journal of Econometrics 160(1), 246-256",
                "doi": "10.1016/j.jeconom.2010.03.034",
            },
            {
                "authors": "Diebold, F.X.; Mariano, R.S.",
                "year": 1995,
                "title": "Comparing Predictive Accuracy",
                "journal": "Journal of Business & Economic Statistics 13(3), 253-263",
                "doi": "10.1080/07350015.1995.10524599",
            },
            {
                "authors": "Newey, W.K.; West, K.D.",
                "year": 1987,
                "title": "A Simple, Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix",
                "journal": "Econometrica 55(3), 703-708",
                "doi": "10.2307/1913610",
            },
            {
                "authors": "Harvey, D.; Leybourne, S.; Newbold, P.",
                "year": 1997,
                "title": "Testing the equality of prediction mean squared errors",
                "journal": "International Journal of Forecasting 13(2), 281-291",
                "doi": "10.1016/S0169-2070(96)00719-4",
            },
        ],
    }
    atomic_write_json(SCRIPT_DIR / "k1378_results.json", results)

    print("\nCorrected period results (negative DM t favors A4f):")
    for key, result in periods.items():
        print(
            f"  {key:18s} n={result['n']:4d} "
            f"A4f={result['a4f_qlike_mean']:.6f} "
            f"GJR={result['gjr_qlike_mean']:.6f} "
            f"t={result['dm_t']:+.3f} p={result['dm_p']:.4g} "
            f"HAC={result['hac_max_lag']} "
            f"Harvey={'PASS' if result['harvey_pass'] else 'FAIL'}"
        )
    print(f"\nVerdict: {results['verdict']['classification']}")
    print(f"Saved atomically in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
