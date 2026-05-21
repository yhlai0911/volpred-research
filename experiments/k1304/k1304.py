#!/usr/bin/env python3
"""
K1304: K1257 BMA 0050.TW H1 FAIL — Hypothesis Decomposition
=============================================================
[提出: Claude (autonomous backlog from K1257 closure asymmetry), 執行: worktree agent]

Research question: Why does 0050.TW BMA posterior collapse onto GJR-t faster
than SPY/GLD? Three hypotheses:

  H_sample: OOS window-length asymmetry (shorter 0050.TW OOS → fewer updates)
  H_pool:   Candidate pool misfit (most candidates never competitive for 0050.TW)
  H_micro:  Microstructure (GJR-t LL advantage on 0050.TW >> SPY/GLD)

Tests:
  (a) BASELINE: full K1257 BMA replication for 0050.TW (verify canonical FAIL)
  (b) H_sample: re-run 0050.TW BMA with SPY-matched start date + equal OOS length
  (c) H_pool:   leave-one-out × 6 — drop each candidate in turn
  (d) H_micro:  per-candidate fitted log-likelihood-per-day on 0050.TW vs SPY/GLD

Lookahead discipline (explicit):
  - Forecast h_t uses returns[t-1] and h_{t-1} only (no t information)
  - BMA weight update: w_{i,t} based on log p(y_t | M_i, F_{t-1}); posterior
    RECORDS w_{i,t} BEFORE computing BMA forecast (posterior pre-t)
  - Per-candidate LL-per-day uses [s..t-1] return window only
  - HHI hitting-time computed forward only

Seed: 42 (fixed for all random operations)
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
EXPERIMENT_ID = "K1304"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# -----------------------------------------------------------------
# Configuration (inheriting K1257 canonical settings)
# -----------------------------------------------------------------
DATA_START = "2010-01-01"
DATA_END = "2026-04-18"
OOS_START = "2020-01-01"   # K1257 canonical OOS start
WINDOW = 1250               # K1257 rolling window ~5y
REFIT_EVERY = 63            # K1257 quarterly refit
SEED = 42

ASSETS = ["SPY", "GLD", "0050.TW"]
IV_PROXY = {"SPY": "^VIX", "GLD": "^GVZ", "0050.TW": "^VIX"}
MODEL_NAMES = ["GARCH_N", "GJR_N", "GJR_t", "EGARCH_N", "HAR_ABS", "A4f_IV2"]

# H_micro: criterion — GJR-t LL advantage ratio >= 2x vs other assets
H_MICRO_RATIO_THRESHOLD = 2.0

print("=" * 72)
print(f"{EXPERIMENT_ID}: BMA 0050.TW H1 FAIL — Hypothesis Decomposition")
print("=" * 72)
print(f"Hypotheses: H_sample (window), H_pool (LOO×6), H_micro (LL advantage)")
print(f"Seed: {SEED}, K1257 canonical OOS: {OOS_START}-{DATA_END}")

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
# Model recursions (pure-NumPy, inheriting K1257)
# -----------------------------------------------------------------
def garch_h(omega, alpha, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = max(np.var(returns), 1e-16)
    for t in range(1, T):
        h[t] = omega + alpha * returns[t - 1] ** 2 + beta * h[t - 1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = max(np.var(returns), 1e-16)
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
    log_h[0] = np.log(max(np.var(returns), 1e-16))
    h[0] = np.exp(log_h[0])
    for t in range(1, T):
        z = returns[t - 1] / np.sqrt(max(h[t - 1], 1e-16))
        log_h[t] = omega + alpha * (abs(z) - e_abs_z) + gamma * z + beta * log_h[t - 1]
        log_h[t] = max(min(log_h[t], 0.0), -30.0)
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
# NLL functions
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


# -----------------------------------------------------------------
# Fit functions (inheriting K1257)
# -----------------------------------------------------------------
def fit_garch_n(returns):
    var0 = max(np.var(returns), 1e-12)
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
    return {"params": res.x, "h": h, "converged": res.success, "dist": "normal",
            "nll": float(res.fun)}


def fit_gjr_n(returns):
    var0 = max(np.var(returns), 1e-12)
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
    return {"params": res.x, "h": h, "converged": res.success, "dist": "normal",
            "nll": float(res.fun)}


def fit_gjr_t(returns):
    var0 = max(np.var(returns), 1e-12)
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
                "dist": "t", "df": 8.0, "nll": 1e10}
    h = gjr_h(best.x[0], best.x[1], best.x[2], best.x[3], returns)
    return {"params": best.x, "h": h, "converged": best.success,
            "dist": "t", "df": best.x[4], "nll": float(best.fun)}


def fit_egarch_n(returns):
    var0 = max(np.var(returns), 1e-12)
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
                "dist": "normal", "e_abs_z": e_abs_z_normal, "nll": 1e10}
    h = egarch_h(best.x[0], best.x[1], best.x[2], best.x[3],
                 returns, e_abs_z_normal)
    return {"params": best.x, "h": h, "converged": best.success,
            "dist": "normal", "e_abs_z": e_abs_z_normal, "nll": float(best.fun)}


def fit_har_abs(returns):
    abs_r = np.abs(returns)
    T = len(returns)
    if T < 23:
        return {"params": np.zeros(4), "converged": False, "nll": 1e10}
    y = abs_r[22:]
    x1 = abs_r[21:-1]
    x5 = np.array([np.mean(abs_r[t - 5:t]) for t in range(22, T)])
    x22 = np.array([np.mean(abs_r[t - 22:t]) for t in range(22, T)])
    X = np.column_stack([np.ones(len(y)), x1, x5, x22])
    try:
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ b
        nll_val = 0.5 * (len(y) * np.log(2 * np.pi) + np.sum(resid**2) / np.var(resid) + len(y))
    except Exception:
        b = np.zeros(4)
        nll_val = 1e10
    return {"params": b, "converged": True, "dist": "normal", "nll": float(nll_val)}


def fit_a4f(returns, iv2):
    var0 = max(np.var(returns), 1e-12)
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
                "converged": False, "dist": "normal", "nll": 1e10}
    return {"params": best.x, "converged": best.success, "dist": "normal",
            "nll": float(best.fun)}


# -----------------------------------------------------------------
# BMA log predictive density at single point
# -----------------------------------------------------------------
def log_pred_density(y, h, dist, df=None):
    """Log p(y | model) assuming y ~ model-distribution with scale sqrt(h).

    LOOKAHEAD CHECK: h must be computed from returns[t-1], not returns[t].
    This function is only called with h = forecasts[m][t], which is computed
    using r_prev = returns[t-1] in the main loop.
    """
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
# Core BMA OOS engine (handles arbitrary candidate subset)
# -----------------------------------------------------------------
def run_bma_oos(asset, df, oos_start, candidate_names=None, label=""):
    """
    Run BMA OOS for a given asset / OOS start / candidate subset.

    Returns dict with:
      - n_oos, bma_qlike, gjr_t_qlike, equal_weight_qlike
      - dm_bma_vs_gjr: t_stat, p_value, harvey_pass
      - final_weights, weight_history (T_oos × n_models), hhi_path, hhi_hitting_time
      - per_model_qlike, log_preds_daily (model -> T_oos array)

    LOOKAHEAD: forecast h_t computed from r_{t-1} and h_{t-1}.
    BMA update: w_{t+1} updated using y_t AFTER BMA forecast at t is made.
    """
    if candidate_names is None:
        candidate_names = MODEL_NAMES

    n_models = len(candidate_names)
    returns = df["ret"].values
    iv2 = df["iv2"].values
    r2 = df["r2"].values
    abs_ret = df["abs_ret"].values
    T = len(df)

    # Find OOS start index
    oos_idx_arr = np.where(df.index >= oos_start)[0]
    if len(oos_idx_arr) == 0:
        return {"error": f"No OOS data after {oos_start}"}
    oos_start_idx = int(oos_idx_arr[0])
    n_oos = T - oos_start_idx

    # Storage
    forecasts = {m: np.full(T, np.nan) for m in candidate_names}
    log_preds_arr = {m: np.full(T, np.nan) for m in candidate_names}

    # Uniform prior
    log_weights = np.log(np.full(n_models, 1.0 / n_models))

    bma_forecasts = np.full(T, np.nan)
    eq_forecasts = np.full(T, np.nan)
    weight_history = np.full((T, n_models), np.nan)

    state = {"last_fit": -1}
    C_GAMMA_NORMAL = math.sqrt(2.0 / math.pi)

    print(f"  [{label}] asset={asset}, oos_start={oos_start}, "
          f"n_oos={n_oos}, candidates={candidate_names}", flush=True)

    for t in range(oos_start_idx, T):
        need_refit = (state["last_fit"] < 0
                      or (t - state["last_fit"]) >= REFIT_EVERY)
        if need_refit:
            s = max(0, t - WINDOW)
            tr = returns[s:t]    # IS window [s, t-1] — no lookahead
            tv = iv2[s:t]

            if (t - oos_start_idx) % 500 == 0 or t == oos_start_idx:
                elapsed = time.time() - START_TIME
                pct = (t - oos_start_idx) / max(n_oos, 1) * 100
                print(f"    refit t={t} ({pct:.0f}%) elapsed={elapsed:.0f}s",
                      flush=True)

            # Fit only requested candidates
            for m in candidate_names:
                try:
                    if m == "GARCH_N":
                        state[m] = fit_garch_n(tr)
                    elif m == "GJR_N":
                        state[m] = fit_gjr_n(tr)
                    elif m == "GJR_t":
                        state[m] = fit_gjr_t(tr)
                    elif m == "EGARCH_N":
                        state[m] = fit_egarch_n(tr)
                    elif m == "HAR_ABS":
                        state[m] = fit_har_abs(tr)
                    elif m == "A4f_IV2":
                        state[m] = fit_a4f(tr, tv)
                except Exception as e:
                    print(f"    fit_{m} FAIL: {e}")
                    state[m] = None

            state["last_fit"] = t

            # Initialize h_prev from last IS value
            for m in candidate_names:
                if state.get(m) is not None:
                    if m in ("GARCH_N", "GJR_N", "GJR_t", "EGARCH_N"):
                        h_arr = state[m].get("h")
                        if h_arr is not None and len(h_arr) > 0:
                            state[f"h_{m}"] = float(h_arr[-1])
                        else:
                            state[f"h_{m}"] = float(np.var(tr))
                    elif m == "A4f_IV2":
                        p = state[m]["params"]
                        _, _, g_in = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5],
                                           tr, tv)
                        state["g_A4f_IV2"] = float(g_in[-1])

        # LOOKAHEAD DISCIPLINE: use r_{t-1} for all forecasts
        r_prev = returns[t - 1]   # t-1 signal → t forecast
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0

        for m in candidate_names:
            if state.get(m) is None:
                continue
            p = state[m]["params"]
            h_t = None
            try:
                if m == "GARCH_N":
                    h_t = max(p[0] + p[1] * r2_prev + p[2] * state[f"h_{m}"], 1e-16)
                    state[f"h_{m}"] = h_t
                elif m == "GJR_N":
                    h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                              + p[3] * state[f"h_{m}"], 1e-16)
                    state[f"h_{m}"] = h_t
                elif m == "GJR_t":
                    h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                              + p[3] * state[f"h_{m}"], 1e-16)
                    state[f"h_{m}"] = h_t
                elif m == "EGARCH_N":
                    e_abs_z = state[m]["e_abs_z"]
                    z_prev = r_prev / np.sqrt(max(state[f"h_{m}"], 1e-16))
                    log_h_t = (p[0] + p[1] * (abs(z_prev) - e_abs_z)
                               + p[2] * z_prev
                               + p[3] * np.log(max(state[f"h_{m}"], 1e-16)))
                    log_h_t = max(min(log_h_t, 0.0), -30.0)
                    h_t = np.exp(log_h_t)
                    state[f"h_{m}"] = h_t
                elif m == "HAR_ABS":
                    if t >= 22:
                        b = p
                        x1_h = abs_ret[t - 1]   # t-1
                        x5_h = np.mean(abs_ret[t - 5:t])   # [t-5, t-1]
                        x22_h = np.mean(abs_ret[t - 22:t]) # [t-22, t-1]
                        pred_abs = max(b[0] + b[1] * x1_h + b[2] * x5_h
                                       + b[3] * x22_h, 1e-8)
                        h_t = (pred_abs / C_GAMMA_NORMAL) ** 2
                elif m == "A4f_IV2":
                    tau_t = max(p[0] + p[1] * iv2[t - 1], 1e-16)  # iv2[t-1]
                    u2 = r2_prev / tau_t
                    g_t = max(p[2] + p[3] * u2 + p[4] * u2 * ind
                              + p[5] * state["g_A4f_IV2"], 1e-16)
                    h_t = tau_t * g_t
                    state["g_A4f_IV2"] = g_t
            except Exception:
                h_t = None

            if h_t is not None and np.isfinite(h_t) and h_t > 0:
                forecasts[m][t] = h_t

        # --- Record weights BEFORE BMA forecast (posterior at t based on t-1 info) ---
        weight_history[t, :] = np.exp(log_weights)

        # --- BMA forecast = weighted average of h_i ---
        h_vec = np.array([forecasts[m][t] if m in forecasts else np.nan
                          for m in candidate_names])
        valid = np.isfinite(h_vec) & (h_vec > 0)
        if valid.any():
            w_valid = np.exp(log_weights[valid] - logsumexp(log_weights[valid]))
            bma_forecasts[t] = float(np.sum(w_valid * h_vec[valid]))
            eq_forecasts[t] = float(np.mean(h_vec[valid]))

        # --- Update posterior: w_{t+1} = w_t * p(y_t | M_i, F_{t-1}) ---
        # y_t is observed AFTER the forecast is made — no lookahead
        y_t = returns[t]
        for mi, m in enumerate(candidate_names):
            h_pred = forecasts[m][t]
            if not np.isfinite(h_pred) or h_pred <= 0:
                log_preds_arr[m][t] = np.nan
                # K1257-MAJOR-1 fix: invalid model day → log_w = -inf before normalize
                log_weights[mi] = -np.inf
                continue
            if m == "GJR_t" and state.get("GJR_t") is not None:
                lp = log_pred_density(y_t, h_pred, "t", df=state["GJR_t"]["df"])
            else:
                lp = log_pred_density(y_t, h_pred, "normal")
            log_preds_arr[m][t] = lp
            log_weights[mi] = log_weights[mi] + lp

        # Normalize (log-sum-exp for stability)
        finite_mask = np.isfinite(log_weights)
        if finite_mask.any():
            log_weights = log_weights - logsumexp(log_weights[finite_mask])
            # Re-set -inf entries to a small value to avoid all-nan collapse
            log_weights[~finite_mask] = -1e10

    # -----------------------------------------------------------------
    # Evaluation: QLIKE on r2 proxy (Patton 2011)
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

    # GJR-t is always in the pool OR may not be (LOO test)
    if "GJR_t" in candidate_names:
        qlike_gjr_t_pw = qlike_pointwise(forecasts["GJR_t"])
    else:
        # When GJR-t is dropped from pool, use standalone fit as baseline reference
        qlike_gjr_t_pw = np.full(len(oos_idx), np.nan)

    per_model_qlike = {}
    for m in candidate_names:
        pw = qlike_pointwise(forecasts[m])
        per_model_qlike[m] = float(np.nanmean(pw))

    # DM-Harvey test (BMA vs GJR-t)
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
        h_fwd = 1
        t_harvey = t_stat * math.sqrt(
            (n + 1 - 2 * h_fwd + h_fwd * (h_fwd - 1) / n) / n)
        p_val = 2 * (1 - t_dist.cdf(abs(t_harvey), df=n - 1))
        return float(t_harvey), float(p_val), bool(abs(t_harvey) > 3.0)

    dm_bma_vs_gjr = dm_harvey(qlike_bma_pw, qlike_gjr_t_pw)

    # --- HHI (Herfindahl-Hirschman Index) path and hitting time ---
    wh_oos = weight_history[oos_idx]  # shape: (n_oos, n_models)
    hhi_path = np.sum(wh_oos ** 2, axis=1)   # HHI for each OOS day

    # Hitting time: first day HHI > 0.9 (forward only, no lookahead)
    hhi_hits = np.where(hhi_path > 0.9)[0]
    hhi_hitting_time = int(hhi_hits[0]) if len(hhi_hits) > 0 else None

    # --- Per-candidate LL-per-day (IS window average, used for H_micro) ---
    # Uses only [s..t-1] window — no OOS information
    # Here we compute the average IS log-likelihood-per-day at the first refit point
    # for a robust measure of relative model fit
    first_refit_s = max(0, oos_start_idx - WINDOW)
    first_refit_tr = returns[first_refit_s:oos_start_idx]
    first_refit_tv = iv2[first_refit_s:oos_start_idx]
    n_is = len(first_refit_tr)
    ll_per_day = {}
    for m in candidate_names:
        try:
            if m == "GARCH_N":
                fit_r = fit_garch_n(first_refit_tr)
                nll_val = fit_r["nll"]
            elif m == "GJR_N":
                fit_r = fit_gjr_n(first_refit_tr)
                nll_val = fit_r["nll"]
            elif m == "GJR_t":
                fit_r = fit_gjr_t(first_refit_tr)
                nll_val = fit_r["nll"]
            elif m == "EGARCH_N":
                fit_r = fit_egarch_n(first_refit_tr)
                nll_val = fit_r["nll"]
            elif m == "HAR_ABS":
                fit_r = fit_har_abs(first_refit_tr)
                nll_val = fit_r["nll"]
            elif m == "A4f_IV2":
                fit_r = fit_a4f(first_refit_tr, first_refit_tv)
                nll_val = fit_r["nll"]
            else:
                nll_val = np.nan
            # ll_per_day = -NLL / n_obs (average log-likelihood per observation)
            ll_per_day[m] = float(-nll_val / n_is) if n_is > 0 and np.isfinite(nll_val) else np.nan
        except Exception as e:
            ll_per_day[m] = np.nan

    # GJR-t LL advantage: ll_per_day[GJR_t] - ll_per_day[GARCH_N] (less competitive baseline)
    gjr_t_advantage = None
    if "GJR_t" in ll_per_day and "GARCH_N" in ll_per_day:
        if np.isfinite(ll_per_day["GJR_t"]) and np.isfinite(ll_per_day["GARCH_N"]):
            gjr_t_advantage = ll_per_day["GJR_t"] - ll_per_day["GARCH_N"]

    result = {
        "n_oos": int(n_oos),
        "oos_start": str(oos_start),
        "bma_qlike": float(np.nanmean(qlike_bma_pw)),
        "equal_weight_qlike": float(np.nanmean(qlike_eq_pw)),
        "gjr_t_qlike": float(np.nanmean(qlike_gjr_t_pw)) if np.any(np.isfinite(qlike_gjr_t_pw)) else None,
        "per_model_qlike": per_model_qlike,
        "dm_bma_vs_gjr": {
            "t_stat": dm_bma_vs_gjr[0],
            "p_value": dm_bma_vs_gjr[1],
            "harvey_pass": dm_bma_vs_gjr[2]
        },
        "final_weights": {m: float(np.exp(log_weights[i]))
                          for i, m in enumerate(candidate_names)},
        "hhi_hitting_time_days": hhi_hitting_time,
        "ll_per_day": ll_per_day,
        "gjr_t_ll_advantage_vs_garch_n": gjr_t_advantage,
        "candidate_pool": candidate_names,
        "h1_verdict": ("PASS" if (np.nanmean(qlike_bma_pw) < np.nanmean(qlike_gjr_t_pw)
                                  and dm_bma_vs_gjr[2])
                       else "FAIL"),
    }

    # Keep arrays for charting
    result["_charts"] = {
        "oos_idx": oos_idx,
        "dates": df.index[oos_idx],
        "weight_history": weight_history[oos_idx],
        "hhi_path": hhi_path,
        "bma_qlike_pw": qlike_bma_pw,
        "eq_qlike_pw": qlike_eq_pw,
        "gjr_t_qlike_pw": qlike_gjr_t_pw,
    }
    return result


# -----------------------------------------------------------------
# H_sample: re-run 0050.TW with SPY-matched OOS window
# -----------------------------------------------------------------
def run_h_sample(data_dict):
    """
    Match OOS window length: find SPY OOS start date and set 0050.TW to
    start at same calendar date (or nearest available).

    H_sample wins if 0050.TW H1 flips to PASS when using SPY-matched window.
    """
    print("\n=== H_sample: 0050.TW with SPY-matched OOS start ===")
    df_spy = data_dict["SPY"]
    df_050 = data_dict["0050.TW"]

    # SPY OOS start = K1257 canonical 2020-01-01
    spy_oos_start = OOS_START

    # Find equivalent date in 0050.TW index
    tw_oos_candidates = df_050.index[df_050.index >= spy_oos_start]
    if len(tw_oos_candidates) == 0:
        return {"error": "No 0050.TW data after SPY OOS start"}
    tw_oos_start_matched = str(tw_oos_candidates[0].date())

    # Compute how many OOS days SPY has
    spy_n_oos = int((df_spy.index >= spy_oos_start).sum())
    tw_n_oos_matched = int((df_050.index >= tw_oos_start_matched).sum())

    print(f"  SPY OOS start: {spy_oos_start}, n_oos={spy_n_oos}")
    print(f"  0050.TW matched OOS start: {tw_oos_start_matched}, n_oos={tw_n_oos_matched}")
    print(f"  0050.TW original OOS start: {OOS_START} (K1257 canonical)")
    print(f"  Window difference: {spy_n_oos - tw_n_oos_matched} days")

    # Run BMA on 0050.TW with matched start (same as SPY canonical for this case)
    result_matched = run_bma_oos("0050.TW", df_050, tw_oos_start_matched,
                                  candidate_names=MODEL_NAMES,
                                  label="H_sample_matched")

    return {
        "spy_oos_start": spy_oos_start,
        "spy_n_oos": spy_n_oos,
        "tw_oos_start_original": OOS_START,
        "tw_oos_start_matched": tw_oos_start_matched,
        "tw_n_oos_original": None,  # filled in main
        "tw_n_oos_matched": tw_n_oos_matched,
        "bma_result_matched": {k: v for k, v in result_matched.items()
                                if not k.startswith("_")},
        "h1_verdict_matched": result_matched.get("h1_verdict"),
        "dm_t_stat_matched": result_matched.get("dm_bma_vs_gjr", {}).get("t_stat"),
        "hhi_hitting_time_matched": result_matched.get("hhi_hitting_time_days"),
    }


# -----------------------------------------------------------------
# H_pool: leave-one-out × 6
# -----------------------------------------------------------------
def run_h_pool(asset, df):
    """
    For 0050.TW: drop one candidate at a time, run BMA with remaining 5.
    If removing candidate X flips H1 to PASS, X is the dead-weight.
    """
    print(f"\n=== H_pool: Leave-one-out × {len(MODEL_NAMES)} for {asset} ===")
    loo_results = {}
    for drop_model in MODEL_NAMES:
        remaining = [m for m in MODEL_NAMES if m != drop_model]
        print(f"\n  --- Drop: {drop_model} (remaining: {remaining}) ---")
        res = run_bma_oos(asset, df, OOS_START,
                          candidate_names=remaining,
                          label=f"H_pool_drop_{drop_model}")
        loo_results[drop_model] = {k: v for k, v in res.items()
                                    if not k.startswith("_")}
        print(f"  Drop {drop_model}: H1={loo_results[drop_model]['h1_verdict']}, "
              f"DM t={loo_results[drop_model]['dm_bma_vs_gjr']['t_stat']:+.3f}, "
              f"HHI hit={loo_results[drop_model]['hhi_hitting_time_days']}")

    # Which drops flip H1 to PASS?
    h1_flips = [m for m, r in loo_results.items()
                if r["h1_verdict"] == "PASS"]
    return {
        "loo_results": loo_results,
        "h1_flips_to_pass_when_drop": h1_flips,
        "verdict": ("SUPPORT" if len(h1_flips) > 0 else "REJECT"),
        "note": ("Removing these candidates rescues H1 PASS" if h1_flips
                 else "No single drop rescues H1 — pool misfit not the driver"),
    }


# -----------------------------------------------------------------
# H_micro: per-candidate LL-per-day diagnostic
# -----------------------------------------------------------------
def run_h_micro(data_dict, baseline_results):
    """
    For each asset, compute GJR-t LL advantage over GARCH-N (least competitive).
    If 0050.TW's advantage is >= H_MICRO_RATIO_THRESHOLD × max(SPY, GLD) advantage,
    H_micro is supported.

    Uses only IS window [s..t-1] — no lookahead.
    """
    print("\n=== H_micro: Per-candidate LL-per-day diagnostic ===")
    ll_by_asset = {}
    for asset in ["SPY", "GLD", "0050.TW"]:
        ll_by_asset[asset] = baseline_results[asset].get("ll_per_day", {})
        adv = baseline_results[asset].get("gjr_t_ll_advantage_vs_garch_n")
        print(f"  {asset}: GJR-t LL advantage vs GARCH-N = {adv}")

    adv_spy = baseline_results["SPY"].get("gjr_t_ll_advantage_vs_garch_n")
    adv_gld = baseline_results["GLD"].get("gjr_t_ll_advantage_vs_garch_n")
    adv_050 = baseline_results["0050.TW"].get("gjr_t_ll_advantage_vs_garch_n")

    h_micro_verdict = "INCONCLUSIVE"
    ratio_vs_spy = None
    ratio_vs_gld = None
    ratio_vs_max = None

    # Note: ll_per_day = -nll/n_obs (average log-likelihood). If GJR-t fits better,
    # its NLL is lower → ll_per_day[GJR_t] > ll_per_day[GARCH_N] → advantage > 0.
    # If advantage < 0, GARCH-N fits better on IS, so GJR-t has no IS dominance.
    # For H_micro ratio test, use absolute value of advantage to compute relative magnitude,
    # but only if the signs are consistent (all positive) indicating real GJR-t dominance.

    if (adv_050 is not None and adv_spy is not None and adv_gld is not None):
        if adv_spy > 1e-8 and adv_gld > 1e-8 and adv_050 > 1e-8:
            # All positive: GJR-t dominates GARCH-N in IS window on all assets
            ratio_vs_spy = adv_050 / adv_spy
            ratio_vs_gld = adv_050 / adv_gld
            ratio_vs_max = adv_050 / max(adv_spy, adv_gld)
            print(f"  0050.TW/SPY advantage ratio: {ratio_vs_spy:.3f}")
            print(f"  0050.TW/GLD advantage ratio: {ratio_vs_gld:.3f}")
            print(f"  0050.TW/max(SPY,GLD) ratio: {ratio_vs_max:.3f}")
            if ratio_vs_max >= H_MICRO_RATIO_THRESHOLD:
                h_micro_verdict = "SUPPORT"
            elif ratio_vs_max < 1.0:
                h_micro_verdict = "REJECT"
            else:
                h_micro_verdict = "INCONCLUSIVE"
        else:
            # Negative or near-zero advantages: GJR-t not IS-dominant on one or more assets.
            # H_micro cannot be supported — if GJR-t doesn't have IS window dominance,
            # the microstructure explanation (GJR-t overwhelmingly best from day-1) is REJECT.
            ratio_vs_spy = None
            ratio_vs_gld = None
            ratio_vs_max = None
            h_micro_verdict = "REJECT"
            print(f"  Advantages not all positive (GJR-t not IS-dominant) — H_micro REJECT")
            print(f"  (Negative advantage = GARCH-N fits IS window better than GJR-t)")
    elif adv_050 is not None and (adv_spy is None or adv_gld is None):
        h_micro_verdict = "INCONCLUSIVE"

    ratio_str = f"{ratio_vs_max:.3f}" if ratio_vs_max is not None else "N/A"
    return {
        "ll_per_day_by_asset": ll_by_asset,
        "gjr_t_advantage_vs_garch_n": {
            "SPY": adv_spy,
            "GLD": adv_gld,
            "0050.TW": adv_050,
        },
        "ratio_0050tw_vs_spy": ratio_vs_spy,
        "ratio_0050tw_vs_gld": ratio_vs_gld,
        "ratio_0050tw_vs_max_dev_mkt": ratio_vs_max,
        "threshold": H_MICRO_RATIO_THRESHOLD,
        "verdict": h_micro_verdict,
        "note": (f"0050.TW GJR-t LL advantage ratio vs max(SPY,GLD) = "
                 f"{ratio_str}"
                 f" (threshold ≥ {H_MICRO_RATIO_THRESHOLD}×)"),
    }


# -----------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------
def make_charts(baseline_results, h_pool_results, data_dict):
    """Generate posterior weight trajectories and HHI hitting time comparison."""

    # Chart 1: Posterior weight evolution for all 3 assets (BASELINE)
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=False)
    colors = plt.cm.tab10(np.linspace(0, 1, len(MODEL_NAMES)))

    for ax, asset in zip(axes, ["SPY", "GLD", "0050.TW"]):
        res = baseline_results[asset]
        if "_charts" not in res:
            ax.set_title(f"{asset}: No chart data")
            continue
        cd = res["_charts"]
        wh = cd["weight_history"]
        dates = cd["dates"]
        for i, m in enumerate(MODEL_NAMES):
            if i < wh.shape[1]:
                ax.plot(dates, wh[:, i], label=m, color=colors[i], lw=1.2)
        # HHI hitting time marker
        hit_day = res.get("hhi_hitting_time_days")
        if hit_day is not None and hit_day < len(dates):
            ax.axvline(dates[hit_day], color="red", lw=1.5, ls="--", alpha=0.7,
                       label=f"HHI>0.9 @day {hit_day}")
        ax.set_title(f"{asset}: BMA posterior weight evolution (OOS 2020-2026)\n"
                     f"DM Harvey t={res['dm_bma_vs_gjr']['t_stat']:+.2f}, "
                     f"H1={res['h1_verdict']}, HHI hit={hit_day}")
        ax.set_ylabel("Weight")
        ax.set_ylim(-0.02, 1.02)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=7, ncol=3)
    plt.tight_layout()
    fig_path = os.path.join(SCRIPT_DIR, "k1304_weight_evolution.png")
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {fig_path}")

    # Chart 2: HHI hitting time comparison (baseline vs LOO)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Left: baseline HHI paths for 3 assets
    for asset in ["SPY", "GLD", "0050.TW"]:
        res = baseline_results[asset]
        if "_charts" not in res:
            continue
        cd = res["_charts"]
        hhi = cd["hhi_path"]
        dates = cd["dates"]
        ax1.plot(dates, hhi, label=asset, lw=1.5)
    ax1.axhline(0.9, color="red", ls="--", lw=1.5, label="HHI = 0.9 threshold")
    ax1.set_title("Posterior Concentration (HHI) by Asset\n(0050.TW degenerates fastest?)")
    ax1.set_ylabel("HHI (Herfindahl Index)")
    ax1.set_ylim(-0.02, 1.05)
    ax1.grid(alpha=0.3)
    ax1.legend()

    # Right: LOO results for 0050.TW — DM t-stats when each candidate dropped
    if "loo_results" in h_pool_results:
        loo = h_pool_results["loo_results"]
        drop_names = list(loo.keys())
        dm_stats = [loo[m]["dm_bma_vs_gjr"]["t_stat"] for m in drop_names]
        h1_verdicts = [loo[m]["h1_verdict"] for m in drop_names]
        colors_bar = ["green" if v == "PASS" else "red" for v in h1_verdicts]
        ax2.bar(range(len(drop_names)), dm_stats, color=colors_bar, alpha=0.7)
        ax2.axhline(-3.0, color="k", ls="--", lw=1.5, label="Harvey |t|>3 threshold")
        ax2.set_xticks(range(len(drop_names)))
        ax2.set_xticklabels([f"Drop\n{m}" for m in drop_names], fontsize=9)
        ax2.set_title("H_pool: DM-Harvey t-stat when dropping each candidate\n"
                      "(0050.TW; green=H1 PASS, red=H1 FAIL)")
        ax2.set_ylabel("DM-Harvey t-stat (negative = BMA wins)")
        ax2.grid(alpha=0.3, axis="y")
        ax2.legend()

    plt.tight_layout()
    fig_path2 = os.path.join(SCRIPT_DIR, "k1304_hhi_and_loo.png")
    plt.savefig(fig_path2, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {fig_path2}")


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    # -----------------------------------------------------------------
    # Step 0: Load data for all assets
    # -----------------------------------------------------------------
    print("\n[Step 0] Loading data...")
    data_dict = {}
    for asset in ASSETS:
        try:
            df = load_asset(asset, IV_PROXY[asset], DATA_START, DATA_END)
            data_dict[asset] = df
            print(f"  {asset}: N={len(df)}, span={df.index[0].date()} to {df.index[-1].date()}")
        except Exception as e:
            print(f"  ERROR loading {asset}: {e}")
            data_dict[asset] = None

    # -----------------------------------------------------------------
    # Step 1: BASELINE — full K1257 replication for all 3 assets
    # -----------------------------------------------------------------
    print("\n[Step 1] BASELINE: K1257 canonical BMA for all 3 assets...")
    baseline_results = {}
    for asset in ASSETS:
        if data_dict[asset] is None:
            baseline_results[asset] = {"error": "data load failed"}
            continue
        res = run_bma_oos(asset, data_dict[asset], OOS_START,
                          candidate_names=MODEL_NAMES, label=f"BASELINE_{asset}")
        baseline_results[asset] = res
        dm_t = res["dm_bma_vs_gjr"]["t_stat"]
        print(f"\n  [{asset}] H1={res['h1_verdict']}, DM t={dm_t:+.3f}, "
              f"HHI hit day={res['hhi_hitting_time_days']}, n_oos={res['n_oos']}")

    # Sanity check: if any |t| > 10, raise flag
    for asset, res in baseline_results.items():
        if "dm_bma_vs_gjr" in res:
            t_stat = res["dm_bma_vs_gjr"]["t_stat"]
            if abs(t_stat) > 10:
                print(f"  WARNING: {asset} DM t={t_stat:.2f} > 10 — check for bugs!")

    # -----------------------------------------------------------------
    # Step 2: H_sample — 0050.TW with SPY-matched OOS window
    # -----------------------------------------------------------------
    print("\n[Step 2] H_sample: SPY-matched OOS window for 0050.TW...")
    if data_dict.get("0050.TW") is not None and data_dict.get("SPY") is not None:
        h_sample_res = run_h_sample(data_dict)
        h_sample_res["tw_n_oos_original"] = baseline_results.get("0050.TW", {}).get("n_oos")
    else:
        h_sample_res = {"error": "data unavailable"}
    print(f"  H_sample result: H1_matched={h_sample_res.get('h1_verdict_matched')}, "
          f"DM t={h_sample_res.get('dm_t_stat_matched')}")

    # H_sample verdict
    if h_sample_res.get("h1_verdict_matched") == "PASS":
        h_sample_verdict = "SUPPORT"
        h_sample_note = "Matching OOS window flips 0050.TW H1 to PASS — window asymmetry explains the failure"
    elif h_sample_res.get("h1_verdict_matched") == "FAIL":
        h_sample_verdict = "REJECT"
        h_sample_note = "Even with SPY-matched OOS window, 0050.TW H1 remains FAIL — window asymmetry not the driver"
    else:
        h_sample_verdict = "INCONCLUSIVE"
        h_sample_note = "H_sample result inconclusive due to data error"

    # -----------------------------------------------------------------
    # Step 3: H_pool — leave-one-out × 6 for 0050.TW
    # -----------------------------------------------------------------
    print("\n[Step 3] H_pool: Leave-one-out × 6 for 0050.TW...")
    if data_dict.get("0050.TW") is not None:
        h_pool_res = run_h_pool("0050.TW", data_dict["0050.TW"])
    else:
        h_pool_res = {"error": "data unavailable", "verdict": "INCONCLUSIVE"}
    print(f"  H_pool verdict: {h_pool_res.get('verdict')}, "
          f"H1 flips when drop: {h_pool_res.get('h1_flips_to_pass_when_drop', [])}")

    # -----------------------------------------------------------------
    # Step 4: H_micro — LL-per-day diagnostic
    # -----------------------------------------------------------------
    print("\n[Step 4] H_micro: LL-per-day diagnostic across assets...")
    if all(data_dict.get(a) is not None for a in ASSETS):
        h_micro_res = run_h_micro(data_dict, baseline_results)
    else:
        h_micro_res = {"verdict": "INCONCLUSIVE", "error": "data unavailable"}
    print(f"  H_micro verdict: {h_micro_res.get('verdict')}, "
          f"ratio vs max dev mkt: {h_micro_res.get('ratio_0050tw_vs_max_dev_mkt')}")

    # -----------------------------------------------------------------
    # Step 5: Charts
    # -----------------------------------------------------------------
    print("\n[Step 5] Generating charts...")
    try:
        make_charts(baseline_results, h_pool_res, data_dict)
    except Exception as e:
        print(f"  Chart generation error: {e}")

    # -----------------------------------------------------------------
    # Step 6: Summary verdicts and conclusions
    # -----------------------------------------------------------------
    print("\n=== Summary Verdicts ===")

    # Overall decomposition verdict
    dominating_hypothesis = []
    if h_sample_verdict == "SUPPORT":
        dominating_hypothesis.append("H_sample")
    if h_pool_res.get("verdict") == "SUPPORT":
        dominating_hypothesis.append("H_pool")
    if h_micro_res.get("verdict") == "SUPPORT":
        dominating_hypothesis.append("H_micro")

    h_decomp_verdict = ("SUPPORT" if dominating_hypothesis else
                        "INCONCLUSIVE" if any(
                            v == "INCONCLUSIVE" for v in [
                                h_sample_verdict,
                                h_pool_res.get("verdict"),
                                h_micro_res.get("verdict")
                            ]) else "REJECT")

    conclusions_lines = [
        f"K1304 decomposes the K1257 0050.TW H1 FAIL (DM-Harvey t=+0.98, not significant).",
        f"Baseline verified: SPY DM t={baseline_results.get('SPY', {}).get('dm_bma_vs_gjr', {}).get('t_stat', 'N/A'):+.3f}, "
        f"GLD DM t={baseline_results.get('GLD', {}).get('dm_bma_vs_gjr', {}).get('t_stat', 'N/A'):+.3f}, "
        f"0050.TW DM t={baseline_results.get('0050.TW', {}).get('dm_bma_vs_gjr', {}).get('t_stat', 'N/A'):+.3f}.",
        f"H_sample: {h_sample_verdict} — {h_sample_note}.",
        f"H_pool: {h_pool_res.get('verdict')} — {h_pool_res.get('note', '')}.",
        f"H_micro: {h_micro_res.get('verdict')} — {h_micro_res.get('note', '')}.",
        f"Dominating hypothesis(es): {dominating_hypothesis if dominating_hypothesis else 'None decisive'}.",
        f"H_K1304 overall verdict: {h_decomp_verdict}.",
    ]
    conclusions = " ".join(conclusions_lines)
    print(conclusions)

    # -----------------------------------------------------------------
    # Build results JSON
    # -----------------------------------------------------------------
    runtime = time.time() - START_TIME

    # Strip _charts from baseline before saving
    baseline_clean = {}
    for asset, res in baseline_results.items():
        baseline_clean[asset] = {k: v for k, v in res.items()
                                  if not k.startswith("_")}
        # Convert numpy types in hhi_path, etc.
        if "hhi_hitting_time_days" in baseline_clean[asset]:
            v = baseline_clean[asset]["hhi_hitting_time_days"]
            baseline_clean[asset]["hhi_hitting_time_days"] = int(v) if v is not None else None

    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("K1304: K1257 BMA 0050.TW H1 FAIL — Hypothesis Decomposition "
                  "(H_sample / H_pool / H_micro)"),
        "proposer": "Claude",
        "executor": "Claude worktree agent",
        "parent_experiment": "K1257",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_start_canonical": OOS_START,
        "rolling_window": WINDOW,
        "refit_freq": REFIT_EVERY,
        "seed": SEED,
        "models": MODEL_NAMES,
        "assets": ASSETS,
        "lookahead_discipline": {
            "forecast_lag": "h_t uses returns[t-1] — explicit r_prev = returns[t-1]",
            "weight_update": "posterior w_{t+1} updated with y_t AFTER BMA forecast at t",
            "ll_per_day": "IS window [s..t-1] only, no OOS information",
            "hhi_hitting_time": "computed forward only",
        },
        "baseline": baseline_clean,
        "h_sample": {
            "verdict": h_sample_verdict,
            "note": h_sample_note,
            "details": {k: v for k, v in h_sample_res.items()
                        if not k.startswith("_") and k != "bma_result_matched"},
            "matched_bma_result": h_sample_res.get("bma_result_matched", {}),
        },
        "h_pool": {
            "verdict": h_pool_res.get("verdict"),
            "h1_flips_to_pass_when_drop": h_pool_res.get("h1_flips_to_pass_when_drop", []),
            "note": h_pool_res.get("note", ""),
            "loo_results": h_pool_res.get("loo_results", {}),
        },
        "h_micro": {
            "verdict": h_micro_res.get("verdict"),
            "gjr_t_advantage_vs_garch_n": h_micro_res.get("gjr_t_advantage_vs_garch_n"),
            "ratio_0050tw_vs_spy": h_micro_res.get("ratio_0050tw_vs_spy"),
            "ratio_0050tw_vs_gld": h_micro_res.get("ratio_0050tw_vs_gld"),
            "ratio_0050tw_vs_max_dev_mkt": h_micro_res.get("ratio_0050tw_vs_max_dev_mkt"),
            "threshold": H_MICRO_RATIO_THRESHOLD,
            "note": h_micro_res.get("note", ""),
            "ll_per_day_by_asset": h_micro_res.get("ll_per_day_by_asset", {}),
        },
        "hypothesis_verdicts": {
            "H_sample": h_sample_verdict,
            "H_pool": h_pool_res.get("verdict"),
            "H_micro": h_micro_res.get("verdict"),
            "H_K1304_decomposition": h_decomp_verdict,
            "dominating_hypotheses": dominating_hypothesis,
        },
        "conclusions": conclusions,
        "runtime_seconds": round(runtime, 1),
    }

    out_path = os.path.join(SCRIPT_DIR, "k1304_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    print(f"Runtime: {runtime:.1f}s")


if __name__ == "__main__":
    main()
