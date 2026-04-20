#!/usr/bin/env python3
"""
K1257: Bayesian Model Averaging (BMA) Volatility Forecast
=========================================================
[提出: Claude, 執行: Claude agent]

Research question: Does BMA with dynamic posterior-weighted combination of
multiple volatility specs outperform the single best (GJR-t) and equal-weight
ensemble on OOS QLIKE? (Motivated by K593 "no universal winner, regime-dependent").

Candidate models (6; Realized-GARCH skipped — no 5-min data available for
SPY/GLD/0050.TW in this experiment):
  1. GARCH-N:   GARCH(1,1) + Normal
  2. GJR-N:     GJR-GARCH(1,1) + Normal
  3. GJR-t:     GJR-GARCH(1,1) + Student-t
  4. EGARCH-N:  EGARCH(1,1) + Normal
  5. HAR-ABS:   HAR(1,5,22) on |r_t|  (proxy for RV when no 5-min data)
  6. A4f-IV2:   MF-GJR-X with asset-matched IV² (VIX² for SPY, GVZ² for GLD,
                VIX² for 0050.TW fallback)

BMA posterior update: w_{i,t+1} \\propto w_{i,t} * p(y_{t+1} | M_i, F_t)
With log-sum-exp for numerical stability.

Data: SPY + GLD + 0050.TW daily (yfinance, auto_adjust=False)
Period: 2010-01-04 ~ 2026-04-17
IS: 2010-2019, OOS: 2020-2026
Rolling window 1250 (~5y), refit 63 (quarter), seed=42.

Evaluation: QLIKE on r² proxy (Patton 2011), Harvey (2016) |t|>3 DM,
VIX-regime weight analysis (4 buckets: <15, 15-20, 20-25, >25).

Outputs:
  - k1257_results.json
  - k1257_weight_evolution.png
  - k1257_qlike_comparison.png
"""

import os
import sys
import json
import time
import math
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist
from scipy.special import logsumexp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1257"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------
DATA_START = "2010-01-01"
DATA_END = "2026-04-18"
OOS_START = "2020-01-01"
WINDOW = 1250
REFIT_EVERY = 63
SEED = 42

ASSETS = ["SPY", "GLD", "0050.TW"]
IV_PROXY = {"SPY": "^VIX", "GLD": "^GVZ", "0050.TW": "^VIX"}
MODEL_NAMES = ["GARCH_N", "GJR_N", "GJR_t", "EGARCH_N", "HAR_ABS", "A4f_IV2"]

QUICK_MODE = "--quick" in sys.argv

if QUICK_MODE:
    DATA_START = "2016-01-01"
    OOS_START = "2022-01-01"
    WINDOW = 750
    REFIT_EVERY = 126
    ASSETS = ["SPY"]  # only SPY in quick mode
    print("*** QUICK MODE: SPY only, 2016-2026, W=750, refit=126 ***")

print("=" * 72)
print(f"{EXPERIMENT_ID}: Bayesian Model Averaging Volatility Forecast")
print("=" * 72)

# -----------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------
import yfinance as yf


def load_asset(ticker, iv_ticker, start, end):
    px = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=False)
    iv = yf.download(iv_ticker, start=start, end=end, progress=False,
                     auto_adjust=False)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    if isinstance(iv.columns, pd.MultiIndex):
        iv.columns = iv.columns.get_level_values(0)
    # VIX for regime classification — always SPY's VIX regardless of asset
    vix = yf.download("^VIX", start=start, end=end, progress=False,
                      auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["iv"] = iv["Close"].reindex(px.index, method="ffill")
    df["vix_regime"] = vix["Close"].reindex(px.index, method="ffill")
    df["ret"] = np.log(df["close"] / df["close"].shift(1))
    df = df.dropna()
    df["ret"] = df["ret"].clip(-0.20, 0.20)
    df["r2"] = df["ret"] ** 2
    df["iv2"] = (df["iv"] / 100) ** 2
    df["abs_ret"] = np.abs(df["ret"])
    return df


# -----------------------------------------------------------------
# Model recursions (pure-NumPy, no numba to keep deps simple)
# -----------------------------------------------------------------
def garch_h(omega, alpha, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        h[t] = omega + alpha * returns[t - 1] ** 2 + beta * h[t - 1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t - 1] ** 2
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t - 1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


def egarch_h(omega, alpha, gamma, beta, returns, e_abs_z):
    T = len(returns)
    log_h = np.empty(T)
    h = np.empty(T)
    log_h[0] = np.log(np.var(returns))
    h[0] = np.exp(log_h[0])
    for t in range(1, T):
        z = returns[t - 1] / np.sqrt(h[t - 1])
        log_h[t] = omega + alpha * (abs(z) - e_abs_z) + gamma * z + beta * log_h[t - 1]
        if log_h[t] > 0:
            log_h[t] = 0.0
        if log_h[t] < -30:
            log_h[t] = -30.0
        h[t] = np.exp(log_h[t])
    return h


def a4f_h(theta0, theta1, omega, alpha, gamma, beta, returns, iv2):
    T = len(returns)
    h = np.empty(T)
    tau = np.empty(T)
    g = np.empty(T)
    tau[0] = max(theta0 + theta1 * iv2[0], 1e-16)
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = max(theta0 + theta1 * iv2[t - 1], 1e-16)
        u2 = (returns[t - 1] ** 2) / tau[t]
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t - 1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


# -----------------------------------------------------------------
# Fit functions
# -----------------------------------------------------------------
def nll_normal(returns, h):
    return 0.5 * np.sum(np.log(h) + returns ** 2 / h)


def nll_t(returns, h, df):
    T = len(returns)
    scale = np.sqrt((df - 2.0) / df)
    c = (math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0)
         - 0.5 * np.log(np.pi * df))
    s = np.sqrt(h) * scale
    z = returns / s
    ll = c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return -ll.sum()


def fit_garch_n(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.4), (0.5, 0.999)]

    def obj(p):
        if p[1] + p[2] >= 1.0:
            return 1e10
        try:
            h = garch_h(p[0], p[1], p[2], returns)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    x0 = [var0 * 0.05, 0.08, 0.90]
    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 300})
    h = garch_h(res.x[0], res.x[1], res.x[2], returns)
    return {"params": res.x, "h": h, "converged": res.success,
            "dist": "normal"}


def fit_gjr_n(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    def obj(p):
        if p[1] + 0.5 * p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h(p[0], p[1], p[2], p[3], returns)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    x0 = [var0 * 0.05, 0.05, 0.05, 0.90]
    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 300})
    h = gjr_h(res.x[0], res.x[1], res.x[2], res.x[3], returns)
    return {"params": res.x, "h": h, "converged": res.success,
            "dist": "normal"}


def fit_gjr_t(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.5), (1e-6, 0.5),
              (0.5, 0.999), (3.0, 50.0)]

    def obj(p):
        if p[1] + 0.5 * p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h(p[0], p[1], p[2], p[3], returns)
            v = nll_t(returns, h, p[4])
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    best = None
    best_nll = 1e10
    for df0 in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df0]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best = res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([var0 * 0.05, 0.05, 0.05, 0.90, 8.0]),
                "h": np.full(len(returns), var0), "converged": False,
                "dist": "t", "df": 8.0}
    h = gjr_h(best.x[0], best.x[1], best.x[2], best.x[3], returns)
    return {"params": best.x, "h": h, "converged": best.success,
            "dist": "t", "df": best.x[4]}


def fit_egarch_n(returns):
    var0 = np.var(returns)
    e_abs_z_normal = math.sqrt(2.0 / math.pi)
    bounds = [(-5.0, 0.0), (0.0, 1.0), (-0.5, 0.5), (0.5, 0.9999)]

    def obj(p):
        omega, alpha, gamma_e, beta = p
        if abs(beta) >= 1.0:
            return 1e10
        try:
            h = egarch_h(omega, alpha, gamma_e, beta, returns, e_abs_z_normal)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    best = None
    best_nll = 1e10
    for omega0 in [np.log(var0) * (1 - 0.95), -0.1]:
        x0 = [omega0, 0.1, -0.08, 0.95]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best = res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([-0.1, 0.1, -0.08, 0.95]),
                "h": np.full(len(returns), var0), "converged": False,
                "dist": "normal", "e_abs_z": e_abs_z_normal}
    h = egarch_h(best.x[0], best.x[1], best.x[2], best.x[3],
                 returns, e_abs_z_normal)
    return {"params": best.x, "h": h, "converged": best.success,
            "dist": "normal", "e_abs_z": e_abs_z_normal}


def fit_har_abs(returns):
    abs_r = np.abs(returns)
    T = len(returns)
    if T < 23:
        return {"params": np.zeros(4), "converged": False}
    y = abs_r[22:]
    x1 = abs_r[21:-1]
    x5 = np.array([np.mean(abs_r[t - 5:t]) for t in range(22, T)])
    x22 = np.array([np.mean(abs_r[t - 22:t]) for t in range(22, T)])
    X = np.column_stack([np.ones(len(y)), x1, x5, x22])
    try:
        b = np.linalg.lstsq(X, y, rcond=None)[0]
    except Exception:
        b = np.zeros(4)
    return {"params": b, "converged": True, "dist": "normal"}


def fit_a4f(returns, iv2):
    var0 = np.var(returns)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    def obj(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5],
                            returns, iv2)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    best = None
    best_nll = 1e10
    for th1 in [0.3, 0.8, 2.0]:
        x0 = [1e-5, th1, 0.05, 0.04, 0.06, 0.90]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best = res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]),
                "converged": False, "dist": "normal"}
    return {"params": best.x, "converged": best.success, "dist": "normal"}


# -----------------------------------------------------------------
# BMA log predictive density at single point
# -----------------------------------------------------------------
def log_pred_density(y, h, dist, df=None):
    """Log p(y | model) assuming y ~ model-distribution with scale sqrt(h)."""
    if h <= 0 or not np.isfinite(h):
        return -1e10
    if dist == "normal":
        return float(norm.logpdf(y, loc=0.0, scale=np.sqrt(h)))
    elif dist == "t":
        scale = np.sqrt(h * (df - 2.0) / df)
        return float(t_dist.logpdf(y, df, loc=0.0, scale=scale))
    else:
        return -1e10


# -----------------------------------------------------------------
# OOS forecasting engine per asset
# -----------------------------------------------------------------
def run_asset(asset, df):
    print(f"\n[Asset: {asset}] N={len(df)}, span={df.index[0].date()} -> "
          f"{df.index[-1].date()}", flush=True)

    returns = df["ret"].values
    iv2 = df["iv2"].values
    r2 = df["r2"].values
    abs_ret = df["abs_ret"].values
    vix_regime = df["vix_regime"].values
    T = len(df)
    oos_start_idx = int(np.where(df.index >= OOS_START)[0][0])
    n_oos = T - oos_start_idx

    forecasts = {m: np.full(T, np.nan) for m in MODEL_NAMES}
    log_preds = {m: np.full(T, np.nan) for m in MODEL_NAMES}

    # initial prior: uniform
    weights = np.full(len(MODEL_NAMES), 1.0 / len(MODEL_NAMES))
    log_weights = np.log(weights)

    bma_forecasts = np.full(T, np.nan)
    eq_forecasts = np.full(T, np.nan)
    weight_history = np.full((T, len(MODEL_NAMES)), np.nan)

    state = {"last_fit": -1}

    C_GAMMA_NORMAL = math.sqrt(2.0 / math.pi)

    for t in range(oos_start_idx, T):
        need_refit = (state["last_fit"] < 0
                      or (t - state["last_fit"]) >= REFIT_EVERY)
        if need_refit:
            s = max(0, t - WINDOW)
            tr = returns[s:t]
            tv = iv2[s:t]
            if (t - oos_start_idx) % 250 == 0 or t == oos_start_idx:
                elapsed = time.time() - START_TIME
                pct = (t - oos_start_idx) / max(n_oos, 1) * 100
                print(f"  refit t={t} ({pct:.0f}%) elapsed={elapsed:.0f}s",
                      flush=True)
            try:
                state["garch_n"] = fit_garch_n(tr)
            except Exception as e:
                print(f"    fit_garch_n FAIL: {e}")
                state["garch_n"] = None
            try:
                state["gjr_n"] = fit_gjr_n(tr)
            except Exception as e:
                print(f"    fit_gjr_n FAIL: {e}")
                state["gjr_n"] = None
            try:
                state["gjr_t"] = fit_gjr_t(tr)
            except Exception as e:
                print(f"    fit_gjr_t FAIL: {e}")
                state["gjr_t"] = None
            try:
                state["egarch_n"] = fit_egarch_n(tr)
            except Exception as e:
                print(f"    fit_egarch_n FAIL: {e}")
                state["egarch_n"] = None
            try:
                state["har"] = fit_har_abs(tr)
            except Exception as e:
                print(f"    fit_har FAIL: {e}")
                state["har"] = None
            try:
                state["a4f"] = fit_a4f(tr, tv)
            except Exception as e:
                print(f"    fit_a4f FAIL: {e}")
                state["a4f"] = None

            state["last_fit"] = t
            # init recursive h_prev from last in-sample value
            if state["garch_n"] is not None:
                state["h_garch_n"] = state["garch_n"]["h"][-1]
            if state["gjr_n"] is not None:
                state["h_gjr_n"] = state["gjr_n"]["h"][-1]
            if state["gjr_t"] is not None:
                state["h_gjr_t"] = state["gjr_t"]["h"][-1]
            if state["egarch_n"] is not None:
                state["h_egarch_n"] = state["egarch_n"]["h"][-1]
            if state["a4f"] is not None:
                # rebuild tau/g arrays from full fit
                p = state["a4f"]["params"]
                h_in, tau_in, g_in = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5],
                                           tr, tv)
                state["g_a4f"] = g_in[-1]

        r_prev = returns[t - 1]
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0

        # GARCH-N forecast
        if state.get("garch_n") is not None:
            p = state["garch_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * state["h_garch_n"], 1e-16)
            forecasts["GARCH_N"][t] = h_t
            state["h_garch_n"] = h_t
        # GJR-N
        if state.get("gjr_n") is not None:
            p = state["gjr_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_n"], 1e-16)
            forecasts["GJR_N"][t] = h_t
            state["h_gjr_n"] = h_t
        # GJR-t
        if state.get("gjr_t") is not None:
            p = state["gjr_t"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_t"], 1e-16)
            forecasts["GJR_t"][t] = h_t
            state["h_gjr_t"] = h_t
        # EGARCH-N
        if state.get("egarch_n") is not None:
            p = state["egarch_n"]["params"]
            e_abs_z = state["egarch_n"]["e_abs_z"]
            z_prev = r_prev / np.sqrt(max(state["h_egarch_n"], 1e-16))
            log_h_t = (p[0] + p[1] * (abs(z_prev) - e_abs_z)
                       + p[2] * z_prev
                       + p[3] * np.log(max(state["h_egarch_n"], 1e-16)))
            log_h_t = max(min(log_h_t, 0.0), -30.0)
            h_t = np.exp(log_h_t)
            forecasts["EGARCH_N"][t] = h_t
            state["h_egarch_n"] = h_t
        # HAR-ABS
        if state.get("har") is not None and t >= 22:
            b = state["har"]["params"]
            x1_h = abs_ret[t - 1]
            x5_h = np.mean(abs_ret[t - 5:t])
            x22_h = np.mean(abs_ret[t - 22:t])
            pred_abs = max(b[0] + b[1] * x1_h + b[2] * x5_h + b[3] * x22_h,
                           1e-8)
            forecasts["HAR_ABS"][t] = (pred_abs / C_GAMMA_NORMAL) ** 2
        # A4f
        if state.get("a4f") is not None:
            p = state["a4f"]["params"]
            tau_t = max(p[0] + p[1] * iv2[t - 1], 1e-16)
            u2 = r2_prev / tau_t
            g_t = max(p[2] + p[3] * u2 + p[4] * u2 * ind
                      + p[5] * state["g_a4f"], 1e-16)
            h_t = tau_t * g_t
            forecasts["A4f_IV2"][t] = h_t
            state["g_a4f"] = g_t

        # --- record weights BEFORE computing BMA forecast (posterior pre-t) ---
        weight_history[t, :] = np.exp(log_weights)

        # --- BMA forecast = sum_i w_i * h_i (weight-sum variance) ---
        h_vec = np.array([forecasts[m][t] for m in MODEL_NAMES])
        valid = np.isfinite(h_vec) & (h_vec > 0)
        if valid.any():
            # normalize weights over valid models
            w_valid = np.exp(log_weights[valid] - logsumexp(log_weights[valid]))
            bma_forecasts[t] = float(np.sum(w_valid * h_vec[valid]))
            eq_forecasts[t] = float(np.mean(h_vec[valid]))
        # else NaN

        # --- update log posterior using predictive density of y_t given F_{t-1} ---
        y_t = returns[t]
        for mi, m in enumerate(MODEL_NAMES):
            h_pred = forecasts[m][t]
            if not np.isfinite(h_pred) or h_pred <= 0:
                log_preds[m][t] = np.nan
                continue
            if m == "GJR_t" and state.get("gjr_t") is not None:
                lp = log_pred_density(y_t, h_pred, "t",
                                      df=state["gjr_t"]["df"])
            else:
                lp = log_pred_density(y_t, h_pred, "normal")
            log_preds[m][t] = lp
            # posterior update: log w_new = log w_old + log p(y_t | M_i)
            log_weights[mi] = log_weights[mi] + lp

        # normalize via log-sum-exp
        log_weights = log_weights - logsumexp(log_weights)

    # final state
    print(f"  final weights: " + ", ".join(
        f"{m}={np.exp(log_weights[i]):.3f}" for i, m in enumerate(MODEL_NAMES)),
          flush=True)

    # -----------------------------------------------------------------
    # Evaluation: QLIKE on r2 proxy
    # -----------------------------------------------------------------
    oos_idx = np.arange(oos_start_idx, T)
    oos_r2 = r2[oos_idx]

    def qlike_pointwise(h_arr):
        h = h_arr[oos_idx]
        out = np.full(len(oos_idx), np.nan)
        mask = np.isfinite(h) & (h > 0)
        out[mask] = np.log(h[mask]) + oos_r2[mask] / h[mask]
        return out

    qlike_bma_pw = qlike_pointwise(bma_forecasts)
    qlike_eq_pw = qlike_pointwise(eq_forecasts)
    qlike_gjr_t_pw = qlike_pointwise(forecasts["GJR_t"])

    per_model_qlike = {}
    for m in MODEL_NAMES:
        pw = qlike_pointwise(forecasts[m])
        per_model_qlike[m] = float(np.nanmean(pw))

    # --- DM Harvey test ---
    def dm_harvey(loss1, loss2):
        d = loss1 - loss2
        valid = np.isfinite(d)
        d = d[valid]
        n = len(d)
        if n < 10:
            return 0.0, 1.0, False
        d_bar = np.mean(d)
        max_lag = max(1, int(n ** (1 / 3)))
        gamma0 = np.var(d, ddof=1)
        g_sum = 0.0
        for k in range(1, max_lag + 1):
            w = 1 - k / (max_lag + 1)
            g_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            g_sum += 2 * w * g_k
        var_d = (gamma0 + g_sum) / n
        if var_d <= 0:
            return 0.0, 1.0, False
        t_stat = d_bar / math.sqrt(var_d)
        # Harvey correction: t* = t * sqrt((n+1-2h+h(h-1)/n)/n), with h=1 (1-step)
        h_fwd = 1
        adj = math.sqrt(max(
            (n + 1 - 2 * h_fwd + h_fwd * (h_fwd - 1) / n) / n, 1e-12))
        t_adj = t_stat * adj * math.sqrt(n)  # sqrt(n) because d_bar/sqrt(var_d) form
        # Above gets the Harvey-corrected; but we built var_d already as sample var / n.
        # Keep t_stat as-is (already properly-scaled DM-HAC); Harvey adj:
        t_harvey = t_stat * math.sqrt(
            (n + 1 - 2 * h_fwd + h_fwd * (h_fwd - 1) / n) / n)
        p_val = 2 * (1 - t_dist.cdf(abs(t_harvey), df=n - 1))
        return float(t_harvey), float(p_val), bool(abs(t_harvey) > 3.0)

    dm_bma_vs_gjr = dm_harvey(qlike_bma_pw, qlike_gjr_t_pw)
    dm_bma_vs_eq = dm_harvey(qlike_bma_pw, qlike_eq_pw)

    # --- regime-dependent weights (4 VIX buckets) ---
    regimes = {"VIX<15": (0, 15), "15-20": (15, 20),
               "20-25": (20, 25), ">25": (25, 999)}
    regime_weights = {}
    for rname, (lo, hi) in regimes.items():
        mask = (vix_regime[oos_idx] >= lo) & (vix_regime[oos_idx] < hi)
        # use weight_history at oos rows
        wh = weight_history[oos_idx][mask]
        if wh.shape[0] == 0:
            regime_weights[rname] = {"n_days": 0}
            continue
        avg = np.nanmean(wh, axis=0)
        regime_weights[rname] = {
            "n_days": int(mask.sum()),
            **{m: float(avg[i]) for i, m in enumerate(MODEL_NAMES)}
        }

    # regime-conditional QLIKE for BMA vs GJR-t
    regime_qlike = {}
    for rname, (lo, hi) in regimes.items():
        mask = (vix_regime[oos_idx] >= lo) & (vix_regime[oos_idx] < hi)
        if mask.sum() < 10:
            regime_qlike[rname] = {"n_days": int(mask.sum())}
            continue
        regime_qlike[rname] = {
            "n_days": int(mask.sum()),
            "bma_qlike": float(np.nanmean(qlike_bma_pw[mask])),
            "gjr_t_qlike": float(np.nanmean(qlike_gjr_t_pw[mask])),
            "equal_qlike": float(np.nanmean(qlike_eq_pw[mask])),
        }

    result = {
        "n_oos": int(n_oos),
        "bma_qlike": float(np.nanmean(qlike_bma_pw)),
        "equal_weight_qlike": float(np.nanmean(qlike_eq_pw)),
        "gjr_t_qlike": float(np.nanmean(qlike_gjr_t_pw)),
        "per_model_qlike": per_model_qlike,
        "dm_bma_vs_gjr": {
            "t_stat": dm_bma_vs_gjr[0], "p_value": dm_bma_vs_gjr[1],
            "harvey_pass": dm_bma_vs_gjr[2]
        },
        "dm_bma_vs_equal": {
            "t_stat": dm_bma_vs_eq[0], "p_value": dm_bma_vs_eq[1],
            "harvey_pass": dm_bma_vs_eq[2]
        },
        "regime_weights": regime_weights,
        "regime_qlike": regime_qlike,
        "final_weights": {m: float(np.exp(log_weights[i]))
                          for i, m in enumerate(MODEL_NAMES)},
    }

    # Keep arrays for charting
    result["_charts"] = {
        "oos_idx": oos_idx,
        "dates": df.index[oos_idx],
        "weight_history": weight_history[oos_idx],
        "bma_qlike_pw": qlike_bma_pw,
        "eq_qlike_pw": qlike_eq_pw,
        "gjr_t_qlike_pw": qlike_gjr_t_pw,
    }
    return result


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    per_asset = {}
    charts_data = {}

    for asset in ASSETS:
        try:
            df = load_asset(asset, IV_PROXY[asset], DATA_START, DATA_END)
        except Exception as e:
            print(f"  ERROR loading {asset}: {e}")
            per_asset[asset] = {"error": str(e)}
            continue
        res = run_asset(asset, df)
        charts_data[asset] = res.pop("_charts")
        per_asset[asset] = res
        print(f"\n[{asset}] BMA QLIKE={res['bma_qlike']:.6f}  "
              f"GJR-t QLIKE={res['gjr_t_qlike']:.6f}  "
              f"Equal QLIKE={res['equal_weight_qlike']:.6f}")
        print(f"  DM BMA vs GJR-t: t={res['dm_bma_vs_gjr']['t_stat']:+.2f} "
              f"p={res['dm_bma_vs_gjr']['p_value']:.4f} "
              f"Harvey pass={res['dm_bma_vs_gjr']['harvey_pass']}")
        print(f"  DM BMA vs Equal: t={res['dm_bma_vs_equal']['t_stat']:+.2f} "
              f"p={res['dm_bma_vs_equal']['p_value']:.4f} "
              f"Harvey pass={res['dm_bma_vs_equal']['harvey_pass']}")

    # -----------------------------------------------------------------
    # Hypothesis verdicts
    # -----------------------------------------------------------------
    def verdict_h1(asset_results):
        # H1: BMA beats GJR-t on QLIKE + Harvey |t|>3
        passes = []
        for a, r in asset_results.items():
            if "error" in r:
                continue
            better = r["bma_qlike"] < r["gjr_t_qlike"]
            harvey = r["dm_bma_vs_gjr"]["harvey_pass"]
            passes.append(better and harvey)
        if not passes:
            return "NULL"
        if all(passes):
            return "PASS"
        if any(passes):
            return "PARTIAL"
        return "FAIL"

    def verdict_h2(asset_results):
        passes = []
        for a, r in asset_results.items():
            if "error" in r:
                continue
            better = r["bma_qlike"] < r["equal_weight_qlike"]
            harvey = r["dm_bma_vs_equal"]["harvey_pass"]
            passes.append(better and harvey)
        if not passes:
            return "NULL"
        if all(passes):
            return "PASS"
        if any(passes):
            return "PARTIAL"
        return "FAIL"

    def verdict_h3(asset_results):
        # H3: regime weight shift — check whether max-weight model differs
        # across at least 2 regimes for at least 1 asset
        shifts = []
        for a, r in asset_results.items():
            if "error" in r:
                continue
            rw = r["regime_weights"]
            winners = []
            for rname, vals in rw.items():
                if vals.get("n_days", 0) < 10:
                    continue
                model_weights = {m: vals[m] for m in MODEL_NAMES if m in vals}
                if model_weights:
                    winners.append(max(model_weights, key=model_weights.get))
            shifts.append(len(set(winners)) >= 2)
        if not shifts:
            return "NULL"
        if any(shifts):
            return "PASS"
        return "FAIL"

    verdicts = {
        "H1_bma_beats_gjr": verdict_h1(per_asset),
        "H2_bma_beats_equal": verdict_h2(per_asset),
        "H3_regime_weight_shift": verdict_h3(per_asset),
    }
    print("\n=== Hypothesis verdicts ===")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")

    # -----------------------------------------------------------------
    # Conclusions prose
    # -----------------------------------------------------------------
    lines = []
    for a, r in per_asset.items():
        if "error" in r:
            lines.append(f"{a}: ERROR ({r['error']})")
            continue
        diff_vs_gjr = r["bma_qlike"] - r["gjr_t_qlike"]
        diff_vs_eq = r["bma_qlike"] - r["equal_weight_qlike"]
        lines.append(
            f"{a}: BMA={r['bma_qlike']:.5f}, GJR-t={r['gjr_t_qlike']:.5f} "
            f"(BMA-GJR={diff_vs_gjr:+.5f}, Harvey t="
            f"{r['dm_bma_vs_gjr']['t_stat']:+.2f}); "
            f"Equal={r['equal_weight_qlike']:.5f} "
            f"(BMA-Eq={diff_vs_eq:+.5f}, Harvey t="
            f"{r['dm_bma_vs_equal']['t_stat']:+.2f})"
        )
    conclusions = (
        "BMA posterior-weighted combination tested vs single-best (GJR-t) "
        "and equal-weight ensemble on SPY/GLD/0050.TW 2020-2026 OOS. "
        "Per-asset summary: " + " | ".join(lines) + ". "
        f"H1 verdict: {verdicts['H1_bma_beats_gjr']}; "
        f"H2: {verdicts['H2_bma_beats_equal']}; "
        f"H3 (regime weight shift): {verdicts['H3_regime_weight_shift']}. "
        "Research-honesty: null results reported as-is; the purpose of BMA "
        "is principled posterior weighting, not guaranteed QLIKE win. If "
        "posterior concentrates quickly on a single model, BMA effectively "
        "reduces to that model's forecast and differences vs single-best "
        "shrink."
    )

    # -----------------------------------------------------------------
    # Build final JSON
    # -----------------------------------------------------------------
    runtime = time.time() - START_TIME
    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("K1257: Bayesian Model Averaging (BMA) Volatility Forecast"
                  " — Posterior-weighted combination of 6 GARCH/HAR/IV-mix specs"),
        "proposer": "Claude",
        "executor": "Claude agent",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_start": OOS_START,
        "rolling_window": WINDOW,
        "refit_freq": REFIT_EVERY,
        "seed": SEED,
        "models": MODEL_NAMES,
        "assets": list(per_asset.keys()),
        "per_asset": per_asset,
        "hypothesis_verdicts": verdicts,
        "conclusions": conclusions,
        "runtime_seconds": round(runtime, 1),
        "quick_mode": QUICK_MODE,
    }

    out_path = os.path.join(SCRIPT_DIR, "k1257_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    # -----------------------------------------------------------------
    # Charts
    # -----------------------------------------------------------------
    # Chart 1: weight evolution (stacked for first asset if available)
    if charts_data:
        first_asset = list(charts_data.keys())[0]
        cd = charts_data[first_asset]
        fig, axes = plt.subplots(len(charts_data), 1,
                                 figsize=(12, 3.5 * len(charts_data)),
                                 sharex=False)
        if len(charts_data) == 1:
            axes = [axes]
        colors = plt.cm.tab10(np.linspace(0, 1, len(MODEL_NAMES)))
        for ax, (a, cd) in zip(axes, charts_data.items()):
            wh = cd["weight_history"]
            dates = cd["dates"]
            for i, m in enumerate(MODEL_NAMES):
                ax.plot(dates, wh[:, i], label=m, color=colors[i], lw=1.2)
            ax.set_title(f"{a}: BMA posterior weight evolution (OOS)")
            ax.set_ylabel("Weight")
            ax.set_ylim(-0.02, 1.02)
            ax.grid(alpha=0.3)
            ax.legend(loc="upper right", fontsize=8, ncol=3)
        plt.tight_layout()
        fig_path = os.path.join(SCRIPT_DIR, "k1257_weight_evolution.png")
        plt.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fig_path}")

    # Chart 2: QLIKE comparison bars with DM Harvey t-stat
    assets_ok = [a for a in per_asset if "error" not in per_asset[a]]
    if assets_ok:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        x = np.arange(len(assets_ok))
        w = 0.25
        bma_q = [per_asset[a]["bma_qlike"] for a in assets_ok]
        gjr_q = [per_asset[a]["gjr_t_qlike"] for a in assets_ok]
        eq_q = [per_asset[a]["equal_weight_qlike"] for a in assets_ok]
        ax1.bar(x - w, bma_q, w, label="BMA", color="#e74c3c")
        ax1.bar(x, gjr_q, w, label="GJR-t", color="#3498db")
        ax1.bar(x + w, eq_q, w, label="Equal", color="#95a5a6")
        ax1.set_xticks(x)
        ax1.set_xticklabels(assets_ok)
        ax1.set_ylabel("Mean QLIKE (lower = better)")
        ax1.set_title("OOS QLIKE: BMA vs GJR-t vs Equal-weight")
        ax1.legend()
        ax1.grid(alpha=0.3, axis="y")

        dm_bma_gjr = [per_asset[a]["dm_bma_vs_gjr"]["t_stat"] for a in assets_ok]
        dm_bma_eq = [per_asset[a]["dm_bma_vs_equal"]["t_stat"] for a in assets_ok]
        ax2.bar(x - w / 2, dm_bma_gjr, w, label="BMA vs GJR-t",
                color="#e67e22")
        ax2.bar(x + w / 2, dm_bma_eq, w, label="BMA vs Equal",
                color="#27ae60")
        ax2.axhline(3.0, ls="--", color="k", lw=1, label="Harvey |t|>3")
        ax2.axhline(-3.0, ls="--", color="k", lw=1)
        ax2.set_xticks(x)
        ax2.set_xticklabels(assets_ok)
        ax2.set_ylabel("DM-Harvey t-stat (negative = BMA wins)")
        ax2.set_title("DM-Harvey test: BMA vs benchmarks")
        ax2.legend()
        ax2.grid(alpha=0.3, axis="y")

        plt.tight_layout()
        fig_path = os.path.join(SCRIPT_DIR, "k1257_qlike_comparison.png")
        plt.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fig_path}")

    print(f"\n=== Runtime: {runtime:.1f}s ===")


if __name__ == "__main__":
    main()
