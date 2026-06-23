#!/usr/bin/env python3
"""K1544 fair-information GJR-X benchmark for PRG v6.

The new benchmark is the minimal current-information repair of the paper's
lagged GJR-X:

    h_t = omega + alpha*r_{t-1}^2 + gamma*I(r_{t-1}<0)*r_{t-1}^2
          + beta*h_{t-1} + delta*x_overnight_t

At OOS date t the model is estimated on observations strictly before t. The
current-day overnight component is allowed because it is realized at the market
open, matching the information used by PRG's intraday h_{d,1} update.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numba import njit
from scipy import stats as sp_stats
from scipy.optimize import minimize


EXPERIMENT_ID = "k1544_prg_fair_info_gjr"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
PAPER_EXP_DIR = ROOT / "paper" / "prg-periodic-garch" / "experiments"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

RNG_SEED = 1544
FAIR_GJR_REFIT_FREQ_DAYS = 63
FAIR_GJR_N_STARTS = 5


@njit(cache=True)
def _gjrx_current_negll(params: np.ndarray, r: np.ndarray, x_on: np.ndarray, n: int) -> float:
    omega, alpha, gamma_p, beta, delta = params
    cnt = 50 if n > 50 else n
    h0 = 0.0
    for i in range(cnt):
        h0 += r[i] * r[i]
    h = h0 / cnt if cnt > 0 else 1e-6
    if h < 1e-12:
        h = 1e-8

    nll = 0.0
    for i in range(1, n):
        if not np.isfinite(r[i]) or not np.isfinite(r[i - 1]) or not np.isfinite(x_on[i]):
            return 1e100
        shock = r[i - 1] * r[i - 1]
        leverage = shock if r[i - 1] < 0.0 else 0.0
        h = omega + alpha * shock + gamma_p * leverage + beta * h + delta * x_on[i]
        if h < 1e-12:
            h = 1e-12
        nll += 0.5 * (np.log(h) + (r[i] * r[i]) / h)
        if not np.isfinite(nll) or nll > 1e99:
            return 1e100
    return nll


@njit(cache=True)
def _gjrx_current_state(params: np.ndarray, r: np.ndarray, x_on: np.ndarray, n: int) -> float:
    omega, alpha, gamma_p, beta, delta = params
    cnt = 50 if n > 50 else n
    h0 = 0.0
    for i in range(cnt):
        h0 += r[i] * r[i]
    h = h0 / cnt if cnt > 0 else 1e-6
    if h < 1e-12:
        h = 1e-8

    for i in range(1, n):
        shock = r[i - 1] * r[i - 1]
        leverage = shock if r[i - 1] < 0.0 else 0.0
        h = omega + alpha * shock + gamma_p * leverage + beta * h + delta * x_on[i]
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _gjrx_current_next(params: np.ndarray, h_prev: float, r_prev: float, x_current: float) -> float:
    omega, alpha, gamma_p, beta, delta = params
    shock = r_prev * r_prev
    leverage = shock if r_prev < 0.0 else 0.0
    h = omega + alpha * shock + gamma_p * leverage + beta * h_prev + delta * x_current
    if h < 1e-12:
        h = 1e-12
    return h


def _load_module(rel_path: str, name: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fit_gjrx_current(
    returns: np.ndarray,
    x_overnight_current: np.ndarray,
    *,
    n_starts: int = FAIR_GJR_N_STARTS,
    seed: int = RNG_SEED,
) -> tuple[np.ndarray | None, float | None]:
    r = np.ascontiguousarray(returns.astype(np.float64))
    x_on = np.ascontiguousarray(x_overnight_current.astype(np.float64))
    valid = np.isfinite(r) & np.isfinite(x_on)
    if valid.sum() != len(r):
        r = r[valid]
        x_on = x_on[valid]
    n = len(r)
    if n < 100:
        return None, None

    var_r = float(np.mean(r[: min(250, n)] ** 2))
    if not np.isfinite(var_r) or var_r <= 1e-12:
        var_r = 1e-6

    bounds = [
        (1e-10, 1e-2),  # omega
        (0.0, 1.0),     # alpha
        (0.0, 1.0),     # gamma
        (1e-8, 0.999),  # beta
        (0.0, 2.0),     # delta, current overnight component
    ]

    rng = np.random.RandomState(seed)
    starts: list[list[float]] = [
        [max(var_r * 0.05, 1e-10), 0.08, 0.06, 0.85, 0.05],
        [max(var_r * 0.02, 1e-10), 0.05, 0.10, 0.75, 0.15],
    ]
    while len(starts) < n_starts:
        starts.append([
            rng.uniform(1e-10, max(1e-4, var_r * 0.25)),
            rng.uniform(0.01, 0.25),
            rng.uniform(0.0, 0.20),
            rng.uniform(0.60, 0.96),
            rng.uniform(0.0, 0.35),
        ])

    best_fun = np.inf
    best_params: np.ndarray | None = None

    def objective(p: np.ndarray) -> float:
        params = np.asarray(p, dtype=np.float64)
        val = float(_gjrx_current_negll(params, r, x_on, n))
        return val

    for x0 in starts:
        try:
            result = minimize(
                objective,
                np.asarray(x0, dtype=np.float64),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 1200, "ftol": 1e-10},
            )
        except Exception:
            continue
        if result.success and np.isfinite(result.fun) and result.fun < best_fun:
            best_fun = float(result.fun)
            best_params = np.asarray(result.x, dtype=np.float64)

    return best_params, best_fun if best_params is not None else None


def gjrx_current_oos_forecast(
    returns: np.ndarray,
    x_overnight_current: np.ndarray,
    is_end: int,
    *,
    refit_freq: int = FAIR_GJR_REFIT_FREQ_DAYS,
    dates: pd.Index | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    r = np.ascontiguousarray(returns.astype(np.float64))
    x_on = np.ascontiguousarray(x_overnight_current.astype(np.float64))
    n = len(r)
    forecasts = np.full(n, np.nan)
    params: np.ndarray | None = None
    h_state: float | None = None
    refits: list[dict[str, Any]] = []

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params_new, nll = _fit_gjrx_current(r[:t], x_on[:t], seed=RNG_SEED + t)
            if params_new is not None:
                params = params_new
                h_state = float(_gjrx_current_state(params, r[:t], x_on[:t], t))
                refits.append({
                    "t": int(t),
                    "date": str(dates[t].date()) if dates is not None else None,
                    "n_train": int(t),
                    "neg_loglik": float(nll) if nll is not None else None,
                    "params": {
                        "omega": float(params[0]),
                        "alpha": float(params[1]),
                        "gamma": float(params[2]),
                        "beta": float(params[3]),
                        "delta_current_overnight": float(params[4]),
                    },
                })

        if params is None or h_state is None:
            continue
        if not np.isfinite(r[t - 1]) or not np.isfinite(x_on[t]):
            continue
        h_t = float(_gjrx_current_next(params, h_state, float(r[t - 1]), float(x_on[t])))
        forecasts[t] = h_t
        h_state = h_t

    diagnostics = {
        "model": "FairInfo_GJR_X_CurrentON",
        "equation": "h_t = omega + alpha*r_c2c[t-1]^2 + gamma*I(r_c2c[t-1]<0)*r_c2c[t-1]^2 + beta*h[t-1] + delta*x_overnight[t]",
        "refit_freq_days": int(refit_freq),
        "n_starts": int(FAIR_GJR_N_STARTS),
        "n_refits": len(refits),
        "refits": refits,
    }
    return forecasts, diagnostics


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    realized = np.asarray(realized, dtype=np.float64)
    forecast = np.asarray(forecast, dtype=np.float64)
    loss = np.full(len(realized), np.nan)
    valid = np.isfinite(realized) & np.isfinite(forecast) & (realized > 0) & (forecast > 0)
    ratio = realized[valid] / forecast[valid]
    loss[valid] = ratio - np.log(ratio) - 1.0
    return loss


def hac_t_stat(diff: np.ndarray) -> dict[str, Any]:
    d = np.asarray(diff, dtype=np.float64)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 50:
        return {"t_stat": math.nan, "p_value": math.nan, "n": int(n), "max_lag": None}

    mean_d = float(np.mean(d))
    centered = d - mean_d
    max_lag = int(np.floor(n ** (1.0 / 3.0)))
    gamma = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        gamma[k] = np.mean(centered[k:] * centered[: n - k])
    hac_var = gamma[0]
    for k in range(1, max_lag + 1):
        hac_var += 2.0 * (1.0 - k / (max_lag + 1.0)) * gamma[k]

    if hac_var <= 0 or not np.isfinite(hac_var):
        return {"t_stat": math.nan, "p_value": math.nan, "n": int(n), "max_lag": int(max_lag)}
    t_stat = mean_d / math.sqrt(hac_var / n)
    p_value = 2.0 * (1.0 - sp_stats.t.cdf(abs(t_stat), n - 1))
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "n": int(n),
        "max_lag": int(max_lag),
    }


def evaluate_market(
    market: str,
    dates: pd.Index,
    target: np.ndarray,
    prg_forecast: np.ndarray,
    prg_open_known_forecast: np.ndarray | None,
    fair_gjr_forecast: np.ndarray,
    is_end: int,
    metadata: dict[str, Any],
    fair_gjr_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    target_oos = np.asarray(target[is_end:], dtype=np.float64)
    prg_oos = np.asarray(prg_forecast[is_end:], dtype=np.float64)
    prg_open_oos = (
        np.asarray(prg_open_known_forecast[is_end:], dtype=np.float64)
        if prg_open_known_forecast is not None
        else None
    )
    fair_oos = np.asarray(fair_gjr_forecast[is_end:], dtype=np.float64)
    dates_oos = dates[is_end:]

    loss_prg = qlike_loss_array(target_oos, prg_oos)
    loss_fair = qlike_loss_array(target_oos, fair_oos)
    common = np.isfinite(loss_prg) & np.isfinite(loss_fair)

    qlike_prg = float(np.mean(loss_prg[common])) if common.any() else math.nan
    qlike_fair = float(np.mean(loss_fair[common])) if common.any() else math.nan
    dm = hac_t_stat(loss_fair[common] - loss_prg[common])
    advantage = (
        100.0 * (qlike_fair - qlike_prg) / qlike_fair
        if np.isfinite(qlike_fair) and qlike_fair != 0
        else math.nan
    )
    winner = "PRG_Extended" if qlike_prg < qlike_fair else "FairInfo_GJR_X_CurrentON"

    open_known_block: dict[str, Any] | None = None
    if prg_open_oos is not None:
        loss_open = qlike_loss_array(target_oos, prg_open_oos)
        common_open = np.isfinite(loss_open) & np.isfinite(loss_fair)
        qlike_open = float(np.mean(loss_open[common_open])) if common_open.any() else math.nan
        dm_open = hac_t_stat(loss_fair[common_open] - loss_open[common_open])
        open_known_block = {
            "qlike": qlike_open,
            "n_common_valid": int(common_open.sum()),
            "prg_open_known_advantage_pct_vs_fair_gjr": (
                float(100.0 * (qlike_fair - qlike_open) / qlike_fair)
                if np.isfinite(qlike_fair) and qlike_fair != 0
                else math.nan
            ),
            "dm_fair_gjr_minus_prg_open_known": {
                **dm_open,
                "orientation": "positive t_stat means FairInfo_GJR_X_CurrentON loss > PRG_Extended_OpenKnownON loss, favoring open-known PRG",
                "harvey_pass_abs_t_gt_3": bool(np.isfinite(dm_open["t_stat"]) and abs(dm_open["t_stat"]) > 3.0),
            },
            "valid_oos": int(np.isfinite(prg_open_oos).sum()),
        }

    return {
        "market": market,
        "metadata": metadata,
        "oos_period": {
            "start": str(dates_oos[0].date()) if len(dates_oos) else None,
            "end": str(dates_oos[-1].date()) if len(dates_oos) else None,
            "n_oos": int(len(dates_oos)),
            "n_common_valid": int(common.sum()),
        },
        "qlike": {
            "PRG_Extended": qlike_prg,
            "FairInfo_GJR_X_CurrentON": qlike_fair,
            "prg_advantage_pct_vs_fair_gjr": float(advantage),
            "winner": winner,
        },
        "diagnostic_prg_open_known_overnight": open_known_block,
        "dm_fair_gjr_minus_prg": {
            **dm,
            "orientation": "positive t_stat means FairInfo_GJR_X_CurrentON loss > PRG_Extended loss, favoring PRG",
            "harvey_pass_abs_t_gt_3": bool(np.isfinite(dm["t_stat"]) and abs(dm["t_stat"]) > 3.0),
        },
        "forecast_diagnostics": {
            "PRG_Extended_valid_oos": int(np.isfinite(prg_oos).sum()),
            "FairInfo_GJR_X_CurrentON_valid_oos": int(np.isfinite(fair_oos).sum()),
            "FairInfo_GJR_X_CurrentON": fair_gjr_diagnostics,
        },
    }


def _ohlc_arrays(df: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "returns_c2c": df["r_c2c"].values.astype(np.float64),
        "r_overnight": df["r_overnight"].values.astype(np.float64),
        "r_intra": df["r_intra"].values.astype(np.float64),
        "x_overnight": df["r2_overnight"].values.astype(np.float64),
        "x_intra": df["r2_intra"].values.astype(np.float64),
        "target": df["sigma2_fullday"].values.astype(np.float64),
    }


def prg_oos_forecast_components_ohlc(
    module: Any,
    r_overnight: np.ndarray,
    r_intra: np.ndarray,
    r2_overnight: np.ndarray,
    r2_intra: np.ndarray,
    is_end: int,
    *,
    refit_freq: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return canonical PRG and open-known overnight PRG forecasts.

    canonical = h_overnight_t + h_intraday_t, matching existing paper code.
    open-known = r2_overnight_t + h_intraday_t, a diagnostic full-day-at-open
    convention that treats the overnight component as already realized.
    """
    n_days = len(r_overnight)
    canonical = np.full(n_days, np.nan)
    open_known = np.full(n_days, np.nan)

    estimator = getattr(module, "estimate_prg_spy", None) or getattr(module, "estimate_prg")
    n_starts = int(getattr(module, "PRG_N_STARTS", 3))

    # k881/k886 path: helper returns both canonical forecast and h_intraday_t.
    if hasattr(module, "_prg_forecast_day"):
        current_params = None
        h_state = None
        for t in range(is_end, n_days):
            if (t - is_end) % refit_freq == 0 or t == is_end:
                params, _ll = estimator(
                    r_overnight[:t],
                    r_intra[:t],
                    r2_overnight[:t],
                    r2_intra[:t],
                    extended=True,
                    n_starts=n_starts,
                )
                if params is not None:
                    current_params = params
                    h_state = module._prg_propagate_full(
                        current_params[0],
                        current_params[1],
                        current_params[2],
                        current_params[3],
                        current_params[4],
                        current_params[5],
                        current_params[6],
                        current_params[7],
                        r_overnight[:t],
                        r_intra[:t],
                        r2_overnight[:t],
                        r2_intra[:t],
                        t,
                    )

            if current_params is None or h_state is None:
                continue

            if (t - is_end) % refit_freq != 0 and t != is_end:
                d = t - 1
                x_prev = r2_intra[d - 1] if d > 0 else r2_overnight[0]
                r_prev = r_intra[d - 1] if d > 0 else r_overnight[0]
                h_state = module._prg_propagate_one_day(
                    current_params[0],
                    current_params[1],
                    current_params[2],
                    current_params[3],
                    current_params[4],
                    current_params[5],
                    current_params[6],
                    current_params[7],
                    h_state,
                    x_prev,
                    r_prev,
                    r2_overnight[d],
                    r_overnight[d],
                )

            fc, h_in_t = module._prg_forecast_day(
                current_params[0],
                current_params[1],
                current_params[2],
                current_params[3],
                current_params[4],
                current_params[5],
                current_params[6],
                current_params[7],
                h_state,
                r2_intra[t - 1],
                r_intra[t - 1],
                r2_overnight[t],
                r_overnight[t],
            )
            canonical[t] = fc
            open_known[t] = r2_overnight[t] + h_in_t
        return canonical, open_known

    # k880 path: same formulas are inlined in its prg_oos_forecast function.
    current_params = None
    h_state = None

    def parse(params: np.ndarray) -> tuple[float, float, float, float, float, float, float, float]:
        return (
            float(params[0]),
            float(params[1]),
            float(params[2]),
            float(params[6]),
            float(params[3]),
            float(params[4]),
            float(params[5]),
            float(params[7]),
        )

    for t in range(is_end, n_days):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, _ll = estimator(
                r_overnight[:t],
                r_intra[:t],
                r2_overnight[:t],
                r2_intra[:t],
                extended=True,
                n_starts=n_starts,
            )
            if params is not None:
                current_params = params
                o0, a0, b0, g0, o1, a1, b1, g1 = parse(current_params)
                h_init = np.mean(r2_overnight[: min(50, t)] + r2_intra[: min(50, t)]) / 2.0
                if h_init < 1e-12:
                    h_init = 1e-8
                h_state = module._prg_propagate_days_numba(
                    o0,
                    a0,
                    b0,
                    g0,
                    o1,
                    a1,
                    b1,
                    g1,
                    r_overnight,
                    r_intra,
                    r2_overnight,
                    r2_intra,
                    0,
                    t,
                    h_init,
                )

        if current_params is None or h_state is None:
            continue

        o0, a0, b0, g0, o1, a1, b1, g1 = parse(current_params)
        lev0 = g0 * r2_intra[t - 1] * (1.0 if r_intra[t - 1] < 0.0 else 0.0)
        h_ov_t = o0 + a0 * r2_intra[t - 1] + lev0 + b0 * h_state
        if h_ov_t < 1e-12:
            h_ov_t = 1e-12
        lev1 = g1 * r2_overnight[t] * (1.0 if r_overnight[t] < 0.0 else 0.0)
        h_in_t = o1 + a1 * r2_overnight[t] + lev1 + b1 * h_ov_t
        if h_in_t < 1e-12:
            h_in_t = 1e-12

        canonical[t] = h_ov_t + h_in_t
        open_known[t] = r2_overnight[t] + h_in_t

        h_state = module._prg_propagate_days_numba(
            o0,
            a0,
            b0,
            g0,
            o1,
            a1,
            b1,
            g1,
            r_overnight,
            r_intra,
            r2_overnight,
            r2_intra,
            t,
            t + 1,
            h_state,
        )

    return canonical, open_known


def run_ohlc_market(
    market: str,
    df: pd.DataFrame,
    module: Any,
    is_end: int,
    prg_refit_freq: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    arrays = _ohlc_arrays(df)
    print(f"\n[{market}] n={len(df)}, IS={is_end}, OOS={len(df) - is_end}")
    print(f"[{market}] running PRG Extended...")
    prg_ext, prg_open_known = prg_oos_forecast_components_ohlc(
        module,
        arrays["r_overnight"],
        arrays["r_intra"],
        arrays["x_overnight"],
        arrays["x_intra"],
        is_end,
        refit_freq=prg_refit_freq,
    )
    print(f"[{market}] running FairInfo GJR-X current overnight...")
    fair_gjr, fair_diag = gjrx_current_oos_forecast(
        arrays["returns_c2c"],
        arrays["x_overnight"],
        is_end,
        refit_freq=FAIR_GJR_REFIT_FREQ_DAYS,
        dates=df.index,
    )
    metadata = {
        **metadata,
        "n_total": int(len(df)),
        "n_is": int(is_end),
        "n_oos": int(len(df) - is_end),
        "period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "overnight_variance_share_pct": float(np.mean(arrays["x_overnight"]) / np.mean(arrays["target"]) * 100.0),
        "prg_refit_freq_days": int(prg_refit_freq),
    }
    return evaluate_market(
        market,
        df.index,
        arrays["target"],
        prg_ext,
        prg_open_known,
        fair_gjr,
        is_end,
        metadata,
        fair_diag,
    )


def taifex_prg_extended_forecast(k883: Any, sess_df: pd.DataFrame, daily_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, int]:
    r_arr = sess_df["r"].values.astype(np.float64)
    x_arr = sess_df["x"].values.astype(np.float64)
    s_arr = sess_df["session_type"].values.astype(np.float64)
    n_sessions = len(sess_df)
    n_days = len(daily_df)
    is_end_sess = int(n_sessions * k883.IS_FRACTION)
    if is_end_sess % 2 != 0:
        is_end_sess += 1
    is_end_days = is_end_sess // 2

    print(f"[TAIFEX] running PRG Extended: sessions={n_sessions}, IS sessions={is_end_sess}")
    params, _ll = k883.estimate_prg(
        r_arr[:is_end_sess],
        x_arr[:is_end_sess],
        s_arr[:is_end_sess],
        extended=True,
        n_starts=5,
    )
    h_all = np.full(n_sessions, np.nan)
    if params is None:
        return np.full(n_days, np.nan), np.full(n_days, np.nan), is_end_days

    current_params = params.copy()
    h_full = k883.prg_recursive_oos(current_params, r_arr, x_arr, s_arr, extended=True)
    h_all[:is_end_sess] = h_full[:is_end_sess]

    for t in range(is_end_sess, n_sessions):
        if (t - is_end_sess) % k883.REFIT_FREQ == 0:
            p_new, _ll_new = k883.estimate_prg(
                r_arr[:t],
                x_arr[:t],
                s_arr[:t],
                extended=True,
                n_starts=3,
            )
            if p_new is not None:
                current_params = p_new
            h_full = k883.prg_recursive_oos(
                current_params,
                r_arr[: t + 1],
                x_arr[: t + 1],
                s_arr[: t + 1],
                extended=True,
            )
            h_all[t] = h_full[t]
        else:
            st = int(s_arr[t])
            omega = np.array([current_params[0], current_params[3]])
            alpha = np.array([current_params[1], current_params[4]])
            beta = np.array([current_params[2], current_params[5]])
            gamma = np.array([current_params[6], current_params[7]])
            h_prev = h_all[t - 1] if np.isfinite(h_all[t - 1]) else 1e-8
            lev = gamma[st] * x_arr[t - 1] * (1.0 if r_arr[t - 1] < 0.0 else 0.0)
            h_all[t] = omega[st] + alpha[st] * x_arr[t - 1] + lev + beta[st] * h_prev
            if h_all[t] < 1e-12:
                h_all[t] = 1e-12

    daily_fc = np.full(n_days, np.nan)
    daily_open_known = np.full(n_days, np.nan)
    x_overnight_daily = daily_df["x_overnight"].values.astype(np.float64)
    for d in range(n_days):
        i_ov = 2 * d
        i_in = 2 * d + 1
        if i_in < n_sessions:
            h_ov = h_all[i_ov] if np.isfinite(h_all[i_ov]) else 0.0
            h_in = h_all[i_in] if np.isfinite(h_all[i_in]) else 0.0
            daily_fc[d] = h_ov + h_in
            daily_open_known[d] = x_overnight_daily[d] + h_in
    return daily_fc, daily_open_known, is_end_days


def run_taifex_market(k883: Any) -> dict[str, Any]:
    print("\n[TAIFEX] loading tick-derived RV data...")
    rv_df = k883.load_all_rv_data()
    sess_df, daily_df = k883.build_session_series(rv_df)
    prg_ext, prg_open_known, is_end_days = taifex_prg_extended_forecast(k883, sess_df, daily_df)

    target = daily_df["rv_fullday"].values.astype(np.float64)
    returns = (daily_df["overnight_gap"].values + daily_df["day_return"].values).astype(np.float64)
    x_overnight = daily_df["x_overnight"].values.astype(np.float64)

    print("[TAIFEX] running FairInfo GJR-X current overnight...")
    fair_gjr, fair_diag = gjrx_current_oos_forecast(
        returns,
        x_overnight,
        is_end_days,
        refit_freq=max(1, int(k883.REFIT_FREQ // 2)),
        dates=daily_df.index,
    )
    metadata = {
        "data_source": "TAIFEX TX tick files via k883 load_all_rv_data",
        "target": "rv_fullday = x_overnight + x_intraday",
        "n_total": int(len(daily_df)),
        "n_is": int(is_end_days),
        "n_oos": int(len(daily_df) - is_end_days),
        "period": f"{daily_df.index[0].date()} to {daily_df.index[-1].date()}",
        "overnight_variance_share_pct": float(np.mean(x_overnight) / np.mean(target) * 100.0),
        "prg_refit_freq_sessions": int(k883.REFIT_FREQ),
        "fair_gjr_refit_freq_days": int(max(1, k883.REFIT_FREQ // 2)),
    }
    return evaluate_market(
        "TAIFEX",
        daily_df.index,
        target,
        prg_ext,
        prg_open_known,
        fair_gjr,
        is_end_days,
        metadata,
        fair_diag,
    )


def _json_clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


def write_tables(results: dict[str, Any]) -> None:
    rows = []
    for market, r in results["markets"].items():
        open_diag = r.get("diagnostic_prg_open_known_overnight") or {}
        open_dm = open_diag.get("dm_fair_gjr_minus_prg_open_known") or {}
        rows.append({
            "market": market,
            "n_common_valid": r["oos_period"]["n_common_valid"],
            "oos_start": r["oos_period"]["start"],
            "oos_end": r["oos_period"]["end"],
            "qlike_prg_extended": r["qlike"]["PRG_Extended"],
            "qlike_prg_open_known_on": open_diag.get("qlike"),
            "qlike_fair_info_gjr_x_current_on": r["qlike"]["FairInfo_GJR_X_CurrentON"],
            "prg_advantage_pct": r["qlike"]["prg_advantage_pct_vs_fair_gjr"],
            "prg_open_known_advantage_pct": open_diag.get("prg_open_known_advantage_pct_vs_fair_gjr"),
            "dm_t_fair_minus_prg": r["dm_fair_gjr_minus_prg"]["t_stat"],
            "dm_t_fair_minus_prg_open_known": open_dm.get("t_stat"),
            "dm_p_value": r["dm_fair_gjr_minus_prg"]["p_value"],
            "harvey_pass_abs_t_gt_3": r["dm_fair_gjr_minus_prg"]["harvey_pass_abs_t_gt_3"],
            "open_known_harvey_pass_abs_t_gt_3": open_dm.get("harvey_pass_abs_t_gt_3"),
            "winner": r["qlike"]["winner"],
        })

    csv_path = EXP_DIR / "per_market_table.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md_path = EXP_DIR / "per_market_table.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("| Market | N | PRG QLIKE | PRG open-known QLIKE | Fair-info GJR-X QLIKE | PRG adv % | Open-known adv % | DM t fair-PRG | DM t fair-openPRG |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for row in rows:
            f.write(
                f"| {row['market']} | {row['n_common_valid']} | "
                f"{row['qlike_prg_extended']:.6f} | "
                f"{row['qlike_prg_open_known_on']:.6f} | "
                f"{row['qlike_fair_info_gjr_x_current_on']:.6f} | "
                f"{row['prg_advantage_pct']:.2f} | "
                f"{row['prg_open_known_advantage_pct']:.2f} | "
                f"{row['dm_t_fair_minus_prg']:.3f} | "
                f"{row['dm_t_fair_minus_prg_open_known']:.3f} |\n"
            )


def make_chart(results: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    markets = list(results["markets"].keys())
    prg = [results["markets"][m]["qlike"]["PRG_Extended"] for m in markets]
    prg_open = [results["markets"][m]["diagnostic_prg_open_known_overnight"]["qlike"] for m in markets]
    fair = [results["markets"][m]["qlike"]["FairInfo_GJR_X_CurrentON"] for m in markets]
    dm_t = [results["markets"][m]["dm_fair_gjr_minus_prg"]["t_stat"] for m in markets]

    x = np.arange(len(markets))
    width = 0.26
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    axes[0].bar(x - width, prg, width, label="PRG Extended", color="#1f77b4")
    axes[0].bar(x, prg_open, width, label="PRG OpenKnownON", color="#2ca02c")
    axes[0].bar(x + width, fair, width, label="FairInfo GJR-X CurrentON", color="#ff7f0e")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(markets)
    axes[0].set_ylabel("OOS QLIKE")
    axes[0].set_title("K1544 QLIKE: PRG Extended vs Fair-Information GJR-X")
    axes[0].legend()

    colors = ["#1f77b4" if v > 0 else "#d62728" for v in dm_t]
    axes[1].bar(x, dm_t, color=colors)
    axes[1].axhline(3.0, color="black", linestyle="--", linewidth=1)
    axes[1].axhline(-3.0, color="black", linestyle="--", linewidth=1)
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(markets)
    axes[1].set_ylabel("DM t: fair-GJR loss minus PRG loss")
    axes[1].set_title("Positive t favors PRG; dashed lines show |t| = 3")

    fig.savefig(EXP_DIR / "fig_prg_vs_fair_gjr.png", dpi=150)
    plt.close(fig)


def main() -> None:
    start = time.time()
    np.random.seed(RNG_SEED)
    try:
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

    print("=" * 72)
    print("K1544: fair-information GJR-X current-overnight benchmark")
    print("=" * 72)

    k880 = _load_module("paper/prg-periodic-garch/experiments/k880_prg_spy_validation.py", "k880_prg_ref")
    k881 = _load_module("paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py", "k881_prg_ref")
    k886 = _load_module("paper/prg-periodic-garch/experiments/k886_prg_0050tw.py", "k886_prg_ref")
    k883 = _load_module("paper/prg-periodic-garch/experiments/k883_taifex_tick_prg.py", "k883_prg_ref")

    markets: dict[str, Any] = {}

    print("\n[SPY] loading data...")
    spy_df = k880.load_spy_data()
    spy_is_end = int((spy_df.index <= k880.IS_END_DATE).sum())
    markets["SPY"] = run_ohlc_market(
        "SPY",
        spy_df,
        k880,
        spy_is_end,
        k880.PRG_REFIT_FREQ,
        {
            "data_source": "yfinance via k880 load_spy_data",
            "target": "sigma2_fullday = r2_overnight + r2_intra",
            "split": f"IS through {k880.IS_END_DATE}",
        },
    )

    for ticker, cfg in k881.ASSETS.items():
        print(f"\n[{ticker}] loading data...")
        df = k881.load_asset_data(ticker, cfg["start"])
        is_end = int(len(df) * k881.IS_FRACTION)
        markets[ticker] = run_ohlc_market(
            ticker,
            df,
            k881,
            is_end,
            k881.REFIT_FREQ_PRG,
            {
                "data_source": f"yfinance via k881 load_asset_data({ticker})",
                "description": cfg["description"],
                "target": "sigma2_fullday = r2_overnight + r2_intra",
                "split": f"{k881.IS_FRACTION:.0%} in-sample / 30% OOS",
            },
        )

    print("\n[0050.TW] loading data...")
    tw50_df = k886.load_0050tw_data(k886.START_DATE, k886.END_DATE)
    tw50_is_end = int(len(tw50_df) * k886.IS_FRACTION)
    markets["0050.TW"] = run_ohlc_market(
        "0050.TW",
        tw50_df,
        k886,
        tw50_is_end,
        k886.REFIT_FREQ_PRG,
        {
            "data_source": "yfinance via k886 load_0050tw_data with clean_tw50_data split fix",
            "target": "sigma2_fullday = r2_overnight + r2_intra",
            "split": f"{k886.IS_FRACTION:.0%} in-sample / 30% OOS",
        },
    )

    markets["TAIFEX"] = run_taifex_market(k883)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "PRG v6 fair-information GJR-X current-overnight benchmark across six markets",
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "random_seed": RNG_SEED,
        "research_question": (
            "Does PRG still beat a GJR-X benchmark that receives the current-day "
            "overnight realization at the day-d open, rather than lagged overnight?"
        ),
        "method_summary": {
            "fair_gjr_equation": (
                "h_t = omega + alpha*r_c2c[t-1]^2 + gamma*I(r_c2c[t-1]<0)*r_c2c[t-1]^2 "
                "+ beta*h[t-1] + delta*x_overnight[t]"
            ),
            "no_lookahead_guard": (
                "At OOS t, fit uses observations < t; forecast may use x_overnight[t] only "
                "because it is realized at the market open. It never uses r_c2c[t] or target[t]."
            ),
            "loss": "QLIKE on common full-day variance target",
            "dm_orientation": "DM t is computed on fair-GJR loss minus PRG loss; positive favors PRG.",
            "prg_open_known_diagnostic": (
                "Also reports PRG_Extended_OpenKnownON = current overnight realized component + PRG h_intraday_t. "
                "This is not the paper's canonical h_overnight_t + h_intraday_t forecast, but diagnoses the "
                "full-day-at-open convention."
            ),
            "harvey_threshold": "|t| > 3.0",
        },
        "markets": markets,
        "references": [
            "Bollerslev and Ghysels (1996), Periodic autoregressive conditional heteroskedasticity.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies.",
            "Diebold and Mariano (1995), Comparing predictive accuracy.",
            "Harvey, Leybourne, and Newbold (1997), Testing equality of prediction mean squared errors.",
            "Harvey, Liu, and Zhu (2016), ...and the cross-section of expected returns.",
            "Linton and Wu (2020), A coupled component DCS-EGARCH model for intraday and overnight volatility.",
            "Opschoor and Lucas (2021), Observation-driven models for realized variances and overnight returns.",
            "Todorova and Soucek (2014), Overnight information flow and realized volatility forecasting.",
        ],
        "runtime_seconds": float(time.time() - start),
    }

    write_tables(results)
    make_chart(results)

    for name in ["k1544_prg_fair_info_gjr_results.json", "results.json"]:
        with (EXP_DIR / name).open("w", encoding="utf-8") as f:
            json.dump(_json_clean(results), f, indent=2, ensure_ascii=False)

    print("\nSummary table:")
    print((EXP_DIR / "per_market_table.md").read_text(encoding="utf-8"))
    print(f"Saved results to {EXP_DIR}")


if __name__ == "__main__":
    main()
