#!/usr/bin/env python3
"""
K1300: Forgetting-Factor Bayesian Model Averaging (BMA)
=======================================================
[Proposer: Claude, Executor: Claude main thread]

Follow-up to K1257 (standard BMA on SPY/GLD/0050.TW):
- K1257 H2 (BMA > equal-weight, Harvey |t|>3) FAILED on all 3 assets
- K1257 H3 (regime weight shift) FAILED — posterior collapses within ~500 days

K1300 test: does a forgetting factor λ < 1 (Raftery-Kárný-Ettler 2010 DMA)
in the posterior update prevent collapse and recover Harvey-significant
performance vs equal-weight on ≥1 asset?

Update rule:
    log w_{i,t+1} = λ * log w_{i,t} + log p(y_{t+1} | M_i, F_t)
    then log-sum-exp normalize.

Lookahead discipline:
- Models fit on returns [s..t-1] (strict shift).
- Weight used to form forecast at t = posterior pre-y_t (lambda-discounted
  cumulative log-likelihood up to t-1).
- Weight update at t uses log p(y_t | M_i, F_{t-1}) — y_t enters AFTER
  forecast is locked in.
- Seed = 42 everywhere.

Model pool inherited from K1257 (apples-to-apples, only λ changes):
GARCH-N, GJR-N, GJR-t, EGARCH-N, HAR-ABS, A4f-IV2.
See README.md for the rationale on deferring Realized-GARCH / HAR-RV / GAS.
"""

import os
import sys
import json
import time
import math
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist
from scipy.special import logsumexp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

START_TIME = time.time()
EXPERIMENT_ID = "K1300"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------
DATA_START = "2018-01-01"
DATA_END = "2026-04-18"
OOS_START = "2020-01-01"
WINDOW = 1250
REFIT_EVERY = 63
LAMBDA_GRID = [0.95, 0.97, 0.99, 1.00]
BOOTSTRAP_B = 1000
BLOCK_LEN = 22  # ~1 month block for stationary bootstrap of QLIKE diff

ASSETS = ["SPY", "GLD", "0050.TW"]
IV_PROXY = {"SPY": "^VIX", "GLD": "^GVZ", "0050.TW": "^VIX"}
MODEL_NAMES = ["GARCH_N", "GJR_N", "GJR_t", "EGARCH_N", "HAR_ABS", "A4f_IV2"]

QUICK_MODE = "--quick" in sys.argv
if QUICK_MODE:
    DATA_START = "2019-01-01"
    OOS_START = "2022-01-01"
    WINDOW = 750
    REFIT_EVERY = 126
    ASSETS = ["SPY"]
    LAMBDA_GRID = [0.97, 1.00]
    BOOTSTRAP_B = 200
    print("*** QUICK MODE: SPY only, 2019-2026, W=750, λ∈{0.97,1.0} ***")

print("=" * 72)
print(f"{EXPERIMENT_ID}: Forgetting-Factor BMA Volatility Forecast")
print("=" * 72)
print(f"  λ grid: {LAMBDA_GRID}")
print(f"  Assets: {ASSETS}")
print(f"  Data: {DATA_START} → {DATA_END} | OOS start: {OOS_START}")
print(f"  Window={WINDOW} refit={REFIT_EVERY} seed={SEED}")

# -----------------------------------------------------------------
# Data
# -----------------------------------------------------------------
import yfinance as yf


def load_asset(ticker, iv_ticker, start, end):
    px = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=False)
    iv = yf.download(iv_ticker, start=start, end=end, progress=False,
                     auto_adjust=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False,
                      auto_adjust=False)
    for df_ in (px, iv, vix):
        if isinstance(df_.columns, pd.MultiIndex):
            df_.columns = df_.columns.get_level_values(0)
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
# Model recursions (pure NumPy, identical to K1257 — keeps comparability)
# -----------------------------------------------------------------
def garch_h(omega, alpha, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        h[t] = max(omega + alpha * returns[t - 1] ** 2 + beta * h[t - 1], 1e-16)
    return h


def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t - 1] ** 2
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        h[t] = max(omega + alpha * r2 + gamma * r2 * ind + beta * h[t - 1], 1e-16)
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
        log_h[t] = max(min(log_h[t], 0.0), -30.0)
        h[t] = np.exp(log_h[t])
    return h


def a4f_h(theta0, theta1, omega, alpha, gamma, beta, returns, iv2):
    T = len(returns)
    h = np.empty(T)
    g_prev = 1.0
    tau = max(theta0 + theta1 * iv2[0], 1e-16)
    h[0] = tau * g_prev
    for t in range(1, T):
        tau = max(theta0 + theta1 * iv2[t - 1], 1e-16)
        u2 = (returns[t - 1] ** 2) / tau
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        g = max(omega + alpha * u2 + gamma * u2 * ind + beta * g_prev, 1e-16)
        h[t] = max(tau * g, 1e-16)
        g_prev = g
    return h, g_prev


def nll_normal(returns, h):
    return 0.5 * np.sum(np.log(h) + returns ** 2 / h)


def nll_t(returns, h, df):
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
            return nll_normal(returns, garch_h(p[0], p[1], p[2], returns))
        except Exception:
            return 1e10
    res = minimize(obj, [var0 * 0.05, 0.08, 0.90], method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": 300})
    return {"params": res.x, "h_last": garch_h(*res.x, returns)[-1],
            "dist": "normal"}


def fit_gjr_n(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5 * p[2] + p[3] >= 1.0:
            return 1e10
        try:
            return nll_normal(returns, gjr_h(*p, returns))
        except Exception:
            return 1e10
    res = minimize(obj, [var0 * 0.05, 0.05, 0.05, 0.90], method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": 300})
    return {"params": res.x, "h_last": gjr_h(*res.x, returns)[-1],
            "dist": "normal"}


def fit_gjr_t(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.5), (1e-6, 0.5),
              (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[1] + 0.5 * p[2] + p[3] >= 1.0:
            return 1e10
        try:
            return nll_t(returns, gjr_h(p[0], p[1], p[2], p[3], returns), p[4])
        except Exception:
            return 1e10
    best, best_nll = None, 1e10
    for df0 in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df0]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([var0 * 0.05, 0.05, 0.05, 0.90, 8.0]),
                "h_last": var0, "dist": "t", "df": 8.0}
    h_last = gjr_h(best.x[0], best.x[1], best.x[2], best.x[3], returns)[-1]
    return {"params": best.x, "h_last": h_last, "dist": "t",
            "df": best.x[4]}


def fit_egarch_n(returns):
    var0 = np.var(returns)
    e_abs_z = math.sqrt(2.0 / math.pi)
    bounds = [(-5.0, 0.0), (0.0, 1.0), (-0.5, 0.5), (0.5, 0.9999)]
    def obj(p):
        if abs(p[3]) >= 1.0:
            return 1e10
        try:
            return nll_normal(returns, egarch_h(*p, returns, e_abs_z))
        except Exception:
            return 1e10
    best, best_nll = None, 1e10
    for omega0 in [np.log(var0) * (1 - 0.95), -0.1]:
        x0 = [omega0, 0.1, -0.08, 0.95]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([-0.1, 0.1, -0.08, 0.95]),
                "h_last": var0, "dist": "normal", "e_abs_z": e_abs_z}
    h_last = egarch_h(*best.x, returns, e_abs_z)[-1]
    return {"params": best.x, "h_last": h_last, "dist": "normal",
            "e_abs_z": e_abs_z}


def fit_har_abs(returns):
    abs_r = np.abs(returns)
    T = len(returns)
    if T < 23:
        return {"params": np.zeros(4), "dist": "normal"}
    y = abs_r[22:]
    x1 = abs_r[21:-1]
    x5 = np.array([np.mean(abs_r[t - 5:t]) for t in range(22, T)])
    x22 = np.array([np.mean(abs_r[t - 22:t]) for t in range(22, T)])
    X = np.column_stack([np.ones(len(y)), x1, x5, x22])
    try:
        b = np.linalg.lstsq(X, y, rcond=None)[0]
    except Exception:
        b = np.zeros(4)
    return {"params": b, "dist": "normal"}


def fit_a4f(returns, iv2):
    var0 = np.var(returns)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _ = a4f_h(*p, returns, iv2)
            return nll_normal(returns, h)
        except Exception:
            return 1e10
    best, best_nll = None, 1e10
    for th1 in [0.3, 0.8, 2.0]:
        x0 = [1e-5, th1, 0.05, 0.04, 0.06, 0.90]
        try:
            res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return {"params": np.array([1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]),
                "g_last": 1.0, "dist": "normal"}
    _, g_last = a4f_h(*best.x, returns, iv2)
    return {"params": best.x, "g_last": g_last, "dist": "normal"}


# -----------------------------------------------------------------
# Log predictive density
# -----------------------------------------------------------------
def log_pred_density(y, h, dist, df=None):
    if not np.isfinite(h) or h <= 0:
        return -1e10
    if dist == "normal":
        return float(norm.logpdf(y, loc=0.0, scale=math.sqrt(h)))
    if dist == "t":
        scale = math.sqrt(h * (df - 2.0) / df)
        return float(t_dist.logpdf(y, df, loc=0.0, scale=scale))
    return -1e10


# -----------------------------------------------------------------
# DM-Harvey test (matches K1257)
# -----------------------------------------------------------------
def dm_harvey(loss1, loss2):
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, False, 0
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
        return 0.0, 1.0, False, n
    t_stat = d_bar / math.sqrt(var_d)
    h_fwd = 1
    t_harvey = t_stat * math.sqrt(
        (n + 1 - 2 * h_fwd + h_fwd * (h_fwd - 1) / n) / n)
    p_val = 2 * (1 - t_dist.cdf(abs(t_harvey), df=n - 1))
    return float(t_harvey), float(p_val), bool(abs(t_harvey) > 3.0), n


# -----------------------------------------------------------------
# Stationary bootstrap CI for mean QLIKE-diff
# -----------------------------------------------------------------
def stationary_bootstrap_ci(d, B=BOOTSTRAP_B, block_len=BLOCK_LEN,
                            seed=SEED, ci=0.95):
    d = d[np.isfinite(d)]
    n = len(d)
    if n < block_len * 2:
        return None, None
    rng = np.random.default_rng(seed)
    p = 1.0 / block_len  # geometric block-length param (Politis-Romano)
    means = np.empty(B)
    for b in range(B):
        idx = np.empty(n, dtype=int)
        i = 0
        while i < n:
            start = rng.integers(0, n)
            blen = rng.geometric(p)
            for j in range(blen):
                if i >= n:
                    break
                idx[i] = (start + j) % n
                i += 1
        means[b] = d[idx].mean()
    lo = float(np.quantile(means, (1 - ci) / 2))
    hi = float(np.quantile(means, 1 - (1 - ci) / 2))
    return lo, hi


# -----------------------------------------------------------------
# Forecast all 6 models OOS for one asset — returns h_i(t), log p_i(t) arrays
# -----------------------------------------------------------------
def forecast_all_models(asset, df):
    print(f"\n[Asset: {asset}] N={len(df)}, span={df.index[0].date()} → "
          f"{df.index[-1].date()}", flush=True)
    returns = df["ret"].values
    iv2 = df["iv2"].values
    abs_ret = df["abs_ret"].values
    T = len(df)
    oos_start_idx = int(np.where(df.index >= OOS_START)[0][0])
    n_oos = T - oos_start_idx

    forecasts = {m: np.full(T, np.nan) for m in MODEL_NAMES}
    log_preds = {m: np.full(T, np.nan) for m in MODEL_NAMES}

    state = {"last_fit": -1}
    C_GAMMA = math.sqrt(2.0 / math.pi)

    for t in range(oos_start_idx, T):
        need_refit = (state["last_fit"] < 0
                      or (t - state["last_fit"]) >= REFIT_EVERY)
        if need_refit:
            s = max(0, t - WINDOW)
            tr = returns[s:t]
            tv = iv2[s:t]
            if (t - oos_start_idx) % 250 == 0 or t == oos_start_idx:
                pct = (t - oos_start_idx) / max(n_oos, 1) * 100
                print(f"  refit t={t} ({pct:.0f}%) elapsed="
                      f"{time.time()-START_TIME:.0f}s", flush=True)
            try:
                state["garch_n"] = fit_garch_n(tr)
            except Exception:
                state["garch_n"] = None
            try:
                state["gjr_n"] = fit_gjr_n(tr)
            except Exception:
                state["gjr_n"] = None
            try:
                state["gjr_t"] = fit_gjr_t(tr)
            except Exception:
                state["gjr_t"] = None
            try:
                state["egarch_n"] = fit_egarch_n(tr)
            except Exception:
                state["egarch_n"] = None
            try:
                state["har"] = fit_har_abs(tr)
            except Exception:
                state["har"] = None
            try:
                state["a4f"] = fit_a4f(tr, tv)
            except Exception:
                state["a4f"] = None
            # initialize last variance from in-sample tail (matches K1257)
            if state["garch_n"]:
                state["h_garch_n"] = state["garch_n"]["h_last"]
            if state["gjr_n"]:
                state["h_gjr_n"] = state["gjr_n"]["h_last"]
            if state["gjr_t"]:
                state["h_gjr_t"] = state["gjr_t"]["h_last"]
            if state["egarch_n"]:
                state["h_egarch_n"] = state["egarch_n"]["h_last"]
            if state["a4f"]:
                state["g_a4f"] = state["a4f"]["g_last"]
            state["last_fit"] = t

        r_prev = returns[t - 1]
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0

        if state.get("garch_n"):
            p = state["garch_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * state["h_garch_n"], 1e-16)
            forecasts["GARCH_N"][t] = h_t
            state["h_garch_n"] = h_t
        if state.get("gjr_n"):
            p = state["gjr_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_n"], 1e-16)
            forecasts["GJR_N"][t] = h_t
            state["h_gjr_n"] = h_t
        if state.get("gjr_t"):
            p = state["gjr_t"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_t"], 1e-16)
            forecasts["GJR_t"][t] = h_t
            state["h_gjr_t"] = h_t
        if state.get("egarch_n"):
            p = state["egarch_n"]["params"]
            e_abs_z = state["egarch_n"]["e_abs_z"]
            z_prev = r_prev / math.sqrt(max(state["h_egarch_n"], 1e-16))
            log_h_t = (p[0] + p[1] * (abs(z_prev) - e_abs_z) + p[2] * z_prev
                       + p[3] * math.log(max(state["h_egarch_n"], 1e-16)))
            log_h_t = max(min(log_h_t, 0.0), -30.0)
            h_t = math.exp(log_h_t)
            forecasts["EGARCH_N"][t] = h_t
            state["h_egarch_n"] = h_t
        if state.get("har") and t >= 22:
            b = state["har"]["params"]
            x1_h = abs_ret[t - 1]
            x5_h = np.mean(abs_ret[t - 5:t])
            x22_h = np.mean(abs_ret[t - 22:t])
            pred_abs = max(b[0] + b[1] * x1_h + b[2] * x5_h + b[3] * x22_h, 1e-8)
            forecasts["HAR_ABS"][t] = (pred_abs / C_GAMMA) ** 2
        if state.get("a4f"):
            p = state["a4f"]["params"]
            tau_t = max(p[0] + p[1] * iv2[t - 1], 1e-16)
            u2 = r2_prev / tau_t
            g_t = max(p[2] + p[3] * u2 + p[4] * u2 * ind
                      + p[5] * state["g_a4f"], 1e-16)
            forecasts["A4f_IV2"][t] = max(tau_t * g_t, 1e-16)
            state["g_a4f"] = g_t

        # log predictive density of y_t using h_i(t)
        y_t = returns[t]
        for m in MODEL_NAMES:
            h_pred = forecasts[m][t]
            if not np.isfinite(h_pred) or h_pred <= 0:
                continue
            if m == "GJR_t" and state.get("gjr_t"):
                log_preds[m][t] = log_pred_density(
                    y_t, h_pred, "t", df=state["gjr_t"]["df"])
            else:
                log_preds[m][t] = log_pred_density(y_t, h_pred, "normal")

    return forecasts, log_preds, oos_start_idx


# -----------------------------------------------------------------
# Apply BMA with forgetting factor — given forecasts & log_preds
# -----------------------------------------------------------------
def bma_with_lambda(forecasts, log_preds, oos_start_idx, T, lam):
    """log w_{t+1} = lam * log w_t + log p(y_t | M_i); normalize each step."""
    n_models = len(MODEL_NAMES)
    log_weights = np.full(n_models, -math.log(n_models))  # uniform prior
    bma_h = np.full(T, np.nan)
    eq_h = np.full(T, np.nan)
    weight_history = np.full((T, n_models), np.nan)

    for t in range(oos_start_idx, T):
        # record pre-y_t weights
        weight_history[t, :] = np.exp(log_weights)

        # forecast at t using pre-t weights
        h_vec = np.array([forecasts[m][t] for m in MODEL_NAMES])
        valid = np.isfinite(h_vec) & (h_vec > 0)
        if valid.any():
            log_w_valid = log_weights[valid] - logsumexp(log_weights[valid])
            w_valid = np.exp(log_w_valid)
            bma_h[t] = float(np.sum(w_valid * h_vec[valid]))
            eq_h[t] = float(np.mean(h_vec[valid]))

        # posterior update with forgetting factor
        lp_vec = np.array([log_preds[m][t] for m in MODEL_NAMES])
        for i in range(n_models):
            if np.isfinite(lp_vec[i]):
                log_weights[i] = lam * log_weights[i] + lp_vec[i]
            else:
                # missing prediction: decay only (no new evidence)
                log_weights[i] = lam * log_weights[i]
        log_weights = log_weights - logsumexp(log_weights)

    return bma_h, eq_h, weight_history, np.exp(log_weights)


# -----------------------------------------------------------------
# QLIKE
# -----------------------------------------------------------------
def qlike_pw(h_arr, r2_arr):
    out = np.full_like(h_arr, np.nan, dtype=float)
    mask = np.isfinite(h_arr) & (h_arr > 0) & np.isfinite(r2_arr)
    out[mask] = np.log(h_arr[mask]) + r2_arr[mask] / h_arr[mask]
    return out


# -----------------------------------------------------------------
# Main per-asset run
# -----------------------------------------------------------------
def run_asset(asset, df):
    forecasts, log_preds, oos_start_idx = forecast_all_models(asset, df)
    T = len(df)
    r2 = df["r2"].values
    oos_idx = np.arange(oos_start_idx, T)

    out = {"oos_start_date": str(df.index[oos_start_idx].date()),
           "n_oos": int(len(oos_idx)),
           "lambda_results": {},
           "per_model_qlike": {}}

    # per-model mean QLIKE (lambda-invariant)
    for m in MODEL_NAMES:
        pw = qlike_pw(forecasts[m], r2)
        out["per_model_qlike"][m] = float(np.nanmean(pw[oos_idx]))

    best_lam = None
    best_t = 0.0
    best_passes = False
    charts = {"oos_idx": oos_idx, "dates": df.index[oos_idx]}

    for lam in LAMBDA_GRID:
        bma_h, eq_h, wh, final_w = bma_with_lambda(
            forecasts, log_preds, oos_start_idx, T, lam)
        q_bma = qlike_pw(bma_h, r2)
        q_eq = qlike_pw(eq_h, r2)
        mean_bma = float(np.nanmean(q_bma[oos_idx]))
        mean_eq = float(np.nanmean(q_eq[oos_idx]))
        diff = q_bma[oos_idx] - q_eq[oos_idx]  # negative = BMA better
        t_stat, p_val, harvey_pass, n_used = dm_harvey(
            q_bma[oos_idx], q_eq[oos_idx])
        ci_lo, ci_hi = stationary_bootstrap_ci(diff)

        out["lambda_results"][f"{lam:.2f}"] = {
            "lambda": lam,
            "bma_qlike": mean_bma,
            "equal_weight_qlike": mean_eq,
            "qlike_diff_mean": float(np.nanmean(diff)),
            "qlike_diff_ci95": [ci_lo, ci_hi],
            "dm_harvey_t": t_stat,
            "dm_harvey_p": p_val,
            "harvey_pass": harvey_pass,
            "n_oos_eff": n_used,
            "final_weights": {m: float(final_w[i])
                              for i, m in enumerate(MODEL_NAMES)},
            "weight_entropy_final": float(
                -np.sum(final_w[final_w > 0] * np.log(final_w[final_w > 0]))),
        }
        print(f"  λ={lam:.2f}: BMA-QLIKE={mean_bma:.5f} "
              f"Eq={mean_eq:.5f} diff={np.nanmean(diff):+.5f} "
              f"DM-t={t_stat:+.2f} p={p_val:.3f} Harvey-pass={harvey_pass}",
              flush=True)

        # track best
        if harvey_pass and t_stat < best_t:
            best_t = t_stat
            best_lam = lam
            best_passes = True
        charts[f"wh_lam{lam:.2f}"] = wh[oos_idx]

    out["best_lambda"] = best_lam
    out["best_lambda_harvey_pass"] = best_passes
    out["_charts"] = charts
    return out


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
            per_asset[asset] = {"error": str(e)}
            continue
        res = run_asset(asset, df)
        charts_data[asset] = res.pop("_charts")
        per_asset[asset] = res

    # verdict: any asset with λ<1 and harvey_pass with negative DM-t (BMA better)
    recovered_assets = []
    for a, r in per_asset.items():
        if "error" in r:
            continue
        for lam_key, lr in r["lambda_results"].items():
            if lr["lambda"] < 1.0 and lr["harvey_pass"] and lr["dm_harvey_t"] < 0:
                recovered_assets.append((a, lr["lambda"], lr["dm_harvey_t"]))
                break  # one λ is enough per asset

    if recovered_assets:
        verdict = "H_K1300_RECOVERED"
        verdict_detail = ", ".join(
            f"{a}@λ={lam:.2f} t={t:+.2f}" for a, lam, t in recovered_assets)
    else:
        verdict = "H_K1300_CONFIRMED_FAIL"
        # report best t across assets / lambdas for context
        best_per_asset = []
        for a, r in per_asset.items():
            if "error" in r:
                continue
            best = min(
                (lr for lr in r["lambda_results"].values() if lr["lambda"] < 1.0),
                key=lambda lr: lr["dm_harvey_t"], default=None)
            if best:
                best_per_asset.append(
                    f"{a}: best λ<1 DM-t={best['dm_harvey_t']:+.2f} "
                    f"(λ={best['lambda']:.2f}, p={best['dm_harvey_p']:.3f})")
        verdict_detail = "; ".join(best_per_asset)

    conclusions = (
        f"K1300 forgetting-factor BMA tested λ∈{LAMBDA_GRID} on "
        f"{', '.join([a for a in per_asset if 'error' not in per_asset[a]])} "
        f"over {OOS_START}→{DATA_END} OOS. Verdict: {verdict}. "
        f"Detail: {verdict_detail}. "
        "K1257 baseline (λ=1) reported here for direct comparison. "
        "Lookahead discipline: posterior used for forecast at t is "
        "λ-discounted log-likelihood through t-1; weight update at t "
        "uses log p(y_t | M_i, F_{t-1}) computed AFTER forecast locked."
    )

    runtime = time.time() - START_TIME
    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("K1300: Forgetting-Factor BMA — K1257 H3 follow-up. "
                  "Tests whether λ<1 posterior discounting recovers "
                  "Harvey-significant performance vs equal-weight."),
        "proposer": "Claude",
        "executor": "Claude main thread",
        "predecessor": "K1257 (standard BMA, H2/H3 FAIL)",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_start": OOS_START,
        "rolling_window": WINDOW,
        "refit_freq": REFIT_EVERY,
        "lambda_grid": LAMBDA_GRID,
        "models": MODEL_NAMES,
        "assets": list(per_asset.keys()),
        "seed": SEED,
        "bootstrap_B": BOOTSTRAP_B,
        "bootstrap_block_len": BLOCK_LEN,
        "harvey_threshold": 3.0,
        "per_asset": per_asset,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "conclusions": conclusions,
        "runtime_seconds": round(runtime, 1),
        "quick_mode": QUICK_MODE,
    }

    out_path = os.path.join(SCRIPT_DIR, "k1300_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    # ---- Chart 1: QLIKE vs λ + DM-Harvey t ----
    assets_ok = [a for a in per_asset if "error" not in per_asset[a]]
    if assets_ok:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        for a in assets_ok:
            lams = [per_asset[a]["lambda_results"][f"{l:.2f}"]["lambda"]
                    for l in LAMBDA_GRID]
            qs = [per_asset[a]["lambda_results"][f"{l:.2f}"]["bma_qlike"]
                  for l in LAMBDA_GRID]
            eq = per_asset[a]["lambda_results"][f"{LAMBDA_GRID[-1]:.2f}"]["equal_weight_qlike"]
            ax1.plot(lams, qs, "o-", label=f"{a} BMA")
            ax1.axhline(eq, ls="--", alpha=0.4,
                        label=f"{a} equal-weight" if a == assets_ok[0] else None)
            ts = [per_asset[a]["lambda_results"][f"{l:.2f}"]["dm_harvey_t"]
                  for l in LAMBDA_GRID]
            ax2.plot(lams, ts, "o-", label=a)
        ax1.set_xlabel("Forgetting factor λ")
        ax1.set_ylabel("OOS mean QLIKE (lower = better)")
        ax1.set_title("BMA QLIKE vs λ (per asset)")
        ax1.legend(fontsize=8)
        ax1.grid(alpha=0.3)
        ax2.axhline(-3.0, ls="--", color="k", label="Harvey |t|=3")
        ax2.axhline(3.0, ls="--", color="k")
        ax2.set_xlabel("Forgetting factor λ")
        ax2.set_ylabel("DM-Harvey t-stat (negative = BMA wins)")
        ax2.set_title("BMA vs equal-weight (DM-Harvey)")
        ax2.legend(fontsize=8)
        ax2.grid(alpha=0.3)
        plt.tight_layout()
        fp = os.path.join(SCRIPT_DIR, "k1300_qlike_lambda.png")
        plt.savefig(fp, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fp}")

        # ---- Chart 2: weight evolution (compare λ=1.0 vs lowest λ for first asset) ----
        first = assets_ok[0]
        cd = charts_data[first]
        lam_low = LAMBDA_GRID[0]
        lam_high = LAMBDA_GRID[-1]
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        colors = plt.cm.tab10(np.linspace(0, 1, len(MODEL_NAMES)))
        for ax, lam in [(axes[0], lam_high), (axes[1], lam_low)]:
            wh = cd[f"wh_lam{lam:.2f}"]
            for i, m in enumerate(MODEL_NAMES):
                ax.plot(cd["dates"], wh[:, i], label=m, color=colors[i], lw=1.1)
            ax.set_title(f"{first}: BMA posterior weight evolution (λ={lam:.2f})")
            ax.set_ylabel("Weight")
            ax.set_ylim(-0.02, 1.02)
            ax.grid(alpha=0.3)
            ax.legend(loc="upper right", fontsize=8, ncol=3)
        plt.tight_layout()
        fp = os.path.join(SCRIPT_DIR, "k1300_weights_lambda.png")
        plt.savefig(fp, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fp}")

    print(f"\n=== Verdict: {verdict} | Runtime: {runtime:.1f}s ===")


if __name__ == "__main__":
    main()
