#!/usr/bin/env python3
"""
K1258: Forgetting-Factor Bayesian Model Averaging Volatility Forecast
=====================================================================
[提出: Claude, 執行: Claude sub-agent — K1257 H3 FAIL structural-fix extension]

Research question: Does forgetting-factor BMA (Raftery, Kárný, Ettler 2010) —
i.e. exponentially-discounted log posterior update

    log w_{i,t+1} = lambda * log w_{i,t} + log p(y_{t+1} | M_i, F_t)

— recover regime-adaptive weight switching that K1257 standard BMA (lambda=1)
failed to achieve (H3 FAIL: posterior concentrates within ~500 days and cannot
un-concentrate across regime shifts)?

Test grid (per asset):
  lambda in {1.00 (K1257 reproduction), 0.99, 0.975, 0.95, 0.90}

Candidate models (same 6 as K1257 for apples-to-apples):
  1. GARCH-N    2. GJR-N    3. GJR-t
  4. EGARCH-N   5. HAR-ABS  6. A4f-IV2

Data:  SPY + GLD + 0050.TW daily (yfinance, auto_adjust=False)
       IV proxy: ^VIX for SPY / ^GVZ for GLD / ^VIX fallback for 0050.TW
       Regime bucket: always ^VIX (global risk proxy)
Period: 2010-01-04 ~ 2026-04-18
OOS:    2020-01-01 onwards
Rolling window 1250, refit every 63 trading days, seed=42.

Posterior state carried across refit windows (NOT reset) — open-question from
README.md answered carry-across.

Evaluation:
  - QLIKE (primary, mean over OOS), MSE, FZ(1%), FZ(2.5%)
  - Harvey (2016) DM test: each lambda<1 variant vs lambda=1 baseline, per asset
  - Per-regime QLIKE (VIX buckets: <15, 15-20, 20-25, >25)
  - Weight-switching frequency (% OOS days where max-weight model changes from
    prior day)
  - Average posterior max weight (concentration measure)

Numerical guards:
  - log-sum-exp for posterior normalization
  - floor log-weight at -700 before discount (avoid underflow)
  - Forgetting factor applied BEFORE adding new log-likelihood (README L109)

Caching:
  - Cache per-model per-day sigma^2 forecasts to
    experiments/k1258/forecasts_<asset>.parquet keyed by (date, model).
    The lambda sweep then reuses forecasts (no need to refit models 5x).
  - Cache per-day log predictive density log_pred(y_t | M_i) similarly so
    lambda sweep is pure posterior recursion.

Outputs:
  - k1258_results.json                (primary deliverable)
  - forecasts_<asset>.parquet         (cache, committable but optional)
  - k1258_qlike_by_lambda.png         (diagnostic)
  - k1258_weight_switch_freq.png      (diagnostic)
"""

from __future__ import annotations

import os
import sys
import json
import time
import math
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist
from scipy.special import logsumexp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
np.random.seed(42)

# ---------------------------------------------------------------------------
# Configuration (apples-to-apples with K1257)
# ---------------------------------------------------------------------------
EXPERIMENT_ID = "K1258"
SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR

DATA_START = "2010-01-01"
DATA_END = "2026-04-18"
OOS_START = "2020-01-01"
WINDOW = 1250
REFIT_EVERY = 63
SEED = 42

ASSETS = ["SPY", "GLD", "0050.TW"]
IV_PROXY = {"SPY": "^VIX", "GLD": "^GVZ", "0050.TW": "^VIX"}
MODEL_NAMES = ["GARCH_N", "GJR_N", "GJR_t", "EGARCH_N", "HAR_ABS", "A4f_IV2"]
LAMBDAS = [1.00, 0.99, 0.975, 0.95, 0.90]

QUICK_MODE = "--quick" in sys.argv
if QUICK_MODE:
    DATA_START = "2016-01-01"
    OOS_START = "2022-01-01"
    WINDOW = 750
    REFIT_EVERY = 126
    ASSETS = ["SPY"]
    print("*** QUICK MODE: SPY only, 2016-2026, W=750, refit=126 ***")

START_TIME = time.time()
print("=" * 72)
print(f"{EXPERIMENT_ID}: Forgetting-Factor BMA Volatility Forecast")
print(f"Lambdas: {LAMBDAS}  Assets: {ASSETS}")
print("=" * 72)

# ---------------------------------------------------------------------------
# Data loading (matches K1257 load_asset)
# ---------------------------------------------------------------------------
import yfinance as yf


def load_asset(ticker: str, iv_ticker: str, start: str, end: str) -> pd.DataFrame:
    px = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    iv = yf.download(iv_ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    if isinstance(iv.columns, pd.MultiIndex):
        iv.columns = iv.columns.get_level_values(0)
    # Regime bucket — always SPY's VIX regardless of asset
    vix = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)
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


# ---------------------------------------------------------------------------
# Model recursions (IDENTICAL to K1257 for apples-to-apples)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Fit functions (IDENTICAL to K1257)
# ---------------------------------------------------------------------------
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
            h = garch_h(p[0], p[1], p[2], returns)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    x0 = [var0 * 0.05, 0.08, 0.90]
    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 300})
    h = garch_h(res.x[0], res.x[1], res.x[2], returns)
    return {"params": res.x, "h": h, "converged": res.success, "dist": "normal"}


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
    return {"params": res.x, "h": h, "converged": res.success, "dist": "normal"}


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
            h, _, _ = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5], returns, iv2)
            v = nll_normal(returns, h)
            return v if np.isfinite(v) else 1e10
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
                "converged": False, "dist": "normal"}
    return {"params": best.x, "converged": best.success, "dist": "normal"}


def log_pred_density(y, h, dist, df=None):
    if h <= 0 or not np.isfinite(h):
        return -1e10
    if dist == "normal":
        return float(norm.logpdf(y, loc=0.0, scale=np.sqrt(h)))
    elif dist == "t":
        scale = np.sqrt(h * (df - 2.0) / df)
        return float(t_dist.logpdf(y, df, loc=0.0, scale=scale))
    return -1e10


# ---------------------------------------------------------------------------
# Forecast builder — identical logic to K1257 but writes per-model per-day
# forecasts + log-likelihoods to a parquet cache so lambda sweep is O(T) not
# O(T * 6 * 5 fits).
# ---------------------------------------------------------------------------
def build_forecasts(asset: str, df: pd.DataFrame) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"forecasts_{asset.replace('.', '_')}.parquet"
    if cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
            print(f"  [cache] loaded {cache_path.name} rows={len(cached)}",
                  flush=True)
            return cached
        except Exception as e:
            print(f"  [cache] failed to load ({e}); rebuilding")

    print(f"  [build] computing 6-model forecasts for {asset} (this takes "
          "several minutes)...", flush=True)

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
                print(f"    refit t={t} ({pct:.0f}%) elapsed={elapsed:.0f}s",
                      flush=True)
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
            state["last_fit"] = t
            if state.get("garch_n") is not None:
                state["h_garch_n"] = state["garch_n"]["h"][-1]
            if state.get("gjr_n") is not None:
                state["h_gjr_n"] = state["gjr_n"]["h"][-1]
            if state.get("gjr_t") is not None:
                state["h_gjr_t"] = state["gjr_t"]["h"][-1]
            if state.get("egarch_n") is not None:
                state["h_egarch_n"] = state["egarch_n"]["h"][-1]
            if state.get("a4f") is not None:
                p = state["a4f"]["params"]
                _, _, g_in = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5], tr, tv)
                state["g_a4f"] = g_in[-1]

        r_prev = returns[t - 1]
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0

        if state.get("garch_n") is not None:
            p = state["garch_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * state["h_garch_n"], 1e-16)
            forecasts["GARCH_N"][t] = h_t
            state["h_garch_n"] = h_t
        if state.get("gjr_n") is not None:
            p = state["gjr_n"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_n"], 1e-16)
            forecasts["GJR_N"][t] = h_t
            state["h_gjr_n"] = h_t
        if state.get("gjr_t") is not None:
            p = state["gjr_t"]["params"]
            h_t = max(p[0] + p[1] * r2_prev + p[2] * r2_prev * ind
                      + p[3] * state["h_gjr_t"], 1e-16)
            forecasts["GJR_t"][t] = h_t
            state["h_gjr_t"] = h_t
        if state.get("egarch_n") is not None:
            p = state["egarch_n"]["params"]
            e_abs_z = state["egarch_n"]["e_abs_z"]
            z_prev = r_prev / np.sqrt(max(state["h_egarch_n"], 1e-16))
            log_h_t = (p[0] + p[1] * (abs(z_prev) - e_abs_z)
                       + p[2] * z_prev
                       + p[3] * np.log(max(state["h_egarch_n"], 1e-16)))
            log_h_t = max(min(log_h_t, 0.0), -30.0)
            h_t = math.exp(log_h_t)
            forecasts["EGARCH_N"][t] = h_t
            state["h_egarch_n"] = h_t
        if state.get("har") is not None and t >= 22:
            b = state["har"]["params"]
            x1_h = abs_ret[t - 1]
            x5_h = np.mean(abs_ret[t - 5:t])
            x22_h = np.mean(abs_ret[t - 22:t])
            pred_abs = max(b[0] + b[1] * x1_h + b[2] * x5_h + b[3] * x22_h, 1e-8)
            forecasts["HAR_ABS"][t] = (pred_abs / C_GAMMA_NORMAL) ** 2
        if state.get("a4f") is not None:
            p = state["a4f"]["params"]
            tau_t = max(p[0] + p[1] * iv2[t - 1], 1e-16)
            u2 = r2_prev / tau_t
            g_t = max(p[2] + p[3] * u2 + p[4] * u2 * ind
                      + p[5] * state["g_a4f"], 1e-16)
            h_t = tau_t * g_t
            forecasts["A4f_IV2"][t] = h_t
            state["g_a4f"] = g_t

        # --- log predictive density p(y_t | M_i, F_{t-1}) ---
        y_t = returns[t]
        for m in MODEL_NAMES:
            h_pred = forecasts[m][t]
            if not np.isfinite(h_pred) or h_pred <= 0:
                log_preds[m][t] = np.nan
                continue
            if m == "GJR_t" and state.get("gjr_t") is not None:
                lp = log_pred_density(y_t, h_pred, "t", df=state["gjr_t"]["df"])
            else:
                lp = log_pred_density(y_t, h_pred, "normal")
            log_preds[m][t] = lp

    # Build a single DataFrame indexed by date
    out = pd.DataFrame(index=df.index)
    out["ret"] = returns
    out["r2"] = r2
    out["vix_regime"] = vix_regime
    for m in MODEL_NAMES:
        out[f"sigma2_{m}"] = forecasts[m]
        out[f"loglik_{m}"] = log_preds[m]

    try:
        out.to_parquet(cache_path, engine="pyarrow")
        print(f"  [cache] wrote {cache_path.name}", flush=True)
    except Exception as e:
        print(f"  [cache] WARN could not write parquet ({e}); continuing")

    return out


# ---------------------------------------------------------------------------
# Forgetting-factor BMA posterior recursion (O(T) on cached forecasts)
# ---------------------------------------------------------------------------
def ffbma_posterior(log_lik_matrix: np.ndarray, lambda_: float,
                    log_floor: float = -700.0) -> np.ndarray:
    """
    log_lik_matrix: shape (T, M) — NaN where model missing that day.
    lambda_      : forgetting factor in (0, 1].
    Returns      : weight_history shape (T, M), NaN rows before first valid
                   day; posterior BEFORE seeing y_t is stored at row t.
    """
    T, M = log_lik_matrix.shape
    log_w = np.full(M, -np.log(M))          # uniform prior
    weight_hist = np.full((T, M), np.nan)

    for t in range(T):
        # Record posterior BEFORE update (this is the posterior used to form
        # the BMA forecast for day t — matches K1257 convention)
        ll_row = log_lik_matrix[t]
        any_valid = np.any(np.isfinite(ll_row))
        if any_valid:
            weight_hist[t] = np.exp(log_w - logsumexp(log_w))

        # Forgetting decay, then update with current log-likelihoods
        log_w = lambda_ * log_w
        # Floor to avoid underflow
        log_w = np.maximum(log_w, log_floor)

        if any_valid:
            # Only add likelihood for models with valid forecasts this day;
            # models missing today keep their decayed weight unchanged.
            valid = np.isfinite(ll_row)
            log_w[valid] = log_w[valid] + ll_row[valid]
            log_w = log_w - logsumexp(log_w)

    return weight_hist


# ---------------------------------------------------------------------------
# Harvey DM test
# ---------------------------------------------------------------------------
def dm_harvey(loss1: np.ndarray, loss2: np.ndarray) -> Tuple[float, float, bool]:
    d = loss1 - loss2
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, False
    d_bar = float(np.mean(d))
    max_lag = max(1, int(n ** (1 / 3)))
    gamma0 = float(np.var(d, ddof=1))
    g_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        g_k = float(np.mean((d[k:] - d_bar) * (d[:-k] - d_bar)))
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


# ---------------------------------------------------------------------------
# FZ loss (Fissler-Ziegel joint VaR-ES loss) — VaR+ES robust scoring
# ---------------------------------------------------------------------------
def fz_loss(returns: np.ndarray, sigma2: np.ndarray, alpha: float,
            dist: str = "normal", nu: float = 8.0) -> float:
    """Mean FZ0 loss at confidence alpha. Use Gaussian quantile for
    BMA (the BMA forecast is a mixture, but for a single scalar loss
    we use the BMA sigma and treat it as Gaussian — standard in
    GARCH forecasting benchmark literature)."""
    sigma = np.sqrt(np.where(sigma2 > 0, sigma2, np.nan))
    if dist == "normal":
        q = norm.ppf(alpha)
    else:
        q = t_dist.ppf(alpha, nu) * math.sqrt((nu - 2) / nu)
    VaR = q * sigma
    # ES for gaussian, lower tail: -phi(q)/alpha * sigma
    if dist == "normal":
        ES = -norm.pdf(q) / alpha * sigma
    else:
        ES = -((nu + q ** 2) / (nu - 1)) * t_dist.pdf(q, nu) / alpha * sigma
    # Fissler-Ziegel 0-homogeneous loss
    hit = (returns <= VaR).astype(float)
    # Standard FZ0 formulation:
    # L = (1/(alpha*ES)) * (hit*(returns-VaR)) + (VaR/ES) + log(-ES) - 1
    with np.errstate(invalid="ignore", divide="ignore"):
        term1 = hit * (returns - VaR) / (alpha * ES)
        term2 = VaR / ES
        term3 = np.log(-ES)
        loss = term1 + term2 + term3 - 1
    loss = loss[np.isfinite(loss)]
    return float(np.mean(loss)) if len(loss) > 0 else float("nan")


# ---------------------------------------------------------------------------
# Evaluation for a single (asset, lambda)
# ---------------------------------------------------------------------------
def evaluate_lambda(fc: pd.DataFrame, lambda_: float) -> Dict:
    T = len(fc)
    oos_mask = fc.index >= pd.Timestamp(OOS_START)

    sigma2_mat = np.column_stack([fc[f"sigma2_{m}"].values for m in MODEL_NAMES])
    ll_mat = np.column_stack([fc[f"loglik_{m}"].values for m in MODEL_NAMES])

    weight_hist = ffbma_posterior(ll_mat, lambda_)

    # BMA point forecast (variance-weighted)
    bma_sigma2 = np.full(T, np.nan)
    for t in range(T):
        h_vec = sigma2_mat[t]
        w = weight_hist[t]
        valid = np.isfinite(h_vec) & (h_vec > 0) & np.isfinite(w)
        if valid.any():
            ws = w[valid] / w[valid].sum()
            bma_sigma2[t] = float(np.sum(ws * h_vec[valid]))

    r2 = fc["r2"].values
    ret = fc["ret"].values
    vix = fc["vix_regime"].values

    # QLIKE pointwise
    qlike_pw = np.full(T, np.nan)
    mask = np.isfinite(bma_sigma2) & (bma_sigma2 > 0)
    qlike_pw[mask] = np.log(bma_sigma2[mask]) + r2[mask] / bma_sigma2[mask]

    oos_idx = np.where(oos_mask)[0]
    qlike_oos_pw = qlike_pw[oos_idx]
    qlike_mean = float(np.nanmean(qlike_oos_pw))

    # MSE on r2 vs sigma2
    mse_oos = float(np.nanmean((r2[oos_idx] - bma_sigma2[oos_idx]) ** 2))

    # FZ losses on BMA sigma (Gaussian quantile; paper-standard benchmark)
    fz1 = fz_loss(ret[oos_idx], bma_sigma2[oos_idx], alpha=0.01, dist="normal")
    fz25 = fz_loss(ret[oos_idx], bma_sigma2[oos_idx], alpha=0.025, dist="normal")

    # Per-regime QLIKE
    regimes = {"VIX<15": (0, 15), "15-20": (15, 20),
               "20-25": (20, 25), ">25": (25, 999)}
    per_regime_qlike = {}
    for rname, (lo, hi) in regimes.items():
        rmask = (vix[oos_idx] >= lo) & (vix[oos_idx] < hi)
        if rmask.sum() < 10:
            per_regime_qlike[rname] = {"n_days": int(rmask.sum())}
            continue
        per_regime_qlike[rname] = {
            "n_days": int(rmask.sum()),
            "qlike": float(np.nanmean(qlike_oos_pw[rmask])),
        }

    # Weight-switch frequency: % OOS days where argmax differs from prior day
    wh_oos = weight_hist[oos_idx]
    argmax_series = np.full(len(oos_idx), -1, dtype=int)
    for i in range(len(oos_idx)):
        row = wh_oos[i]
        if np.any(np.isfinite(row)):
            argmax_series[i] = int(np.nanargmax(row))
    switch_count = 0
    valid_pairs = 0
    for i in range(1, len(argmax_series)):
        if argmax_series[i] >= 0 and argmax_series[i - 1] >= 0:
            valid_pairs += 1
            if argmax_series[i] != argmax_series[i - 1]:
                switch_count += 1
    switch_freq = switch_count / valid_pairs if valid_pairs > 0 else float("nan")

    # Average posterior max weight (concentration)
    max_w = np.nanmax(wh_oos, axis=1)
    avg_max_weight = float(np.nanmean(max_w))

    # Final weights distribution
    final_w = wh_oos[-1] if len(oos_idx) > 0 else np.full(len(MODEL_NAMES), np.nan)
    final_weights = {m: float(final_w[i]) if np.isfinite(final_w[i]) else 0.0
                     for i, m in enumerate(MODEL_NAMES)}

    return {
        "qlike": qlike_mean,
        "mse": mse_oos,
        "fz_1pct": fz1,
        "fz_2_5pct": fz25,
        "per_regime_qlike": per_regime_qlike,
        "weight_switch_freq": float(switch_freq),
        "posterior_avg_max_weight": avg_max_weight,
        "final_weights": final_weights,
        "_qlike_pw": qlike_oos_pw,  # pop before JSON serialization
    }


# ---------------------------------------------------------------------------
# Run one asset (5 lambdas)
# ---------------------------------------------------------------------------
def run_asset(asset: str) -> Dict:
    iv_ticker = IV_PROXY[asset]
    print(f"\n[Asset: {asset}] loading data...", flush=True)
    df = load_asset(asset, iv_ticker, DATA_START, DATA_END)
    print(f"  N={len(df)}, span={df.index[0].date()} -> {df.index[-1].date()}",
          flush=True)

    fc = build_forecasts(asset, df)

    per_lambda = {}
    # First pass: compute all lambda results (keep qlike pointwise for DM test)
    for lam in LAMBDAS:
        print(f"  [eval] lambda={lam:.3f}...", flush=True)
        res = evaluate_lambda(fc, lam)
        per_lambda[lam] = res

    # Harvey DM: each lambda<1 vs lambda=1 baseline (same asset)
    base_pw = per_lambda[1.00]["_qlike_pw"]
    for lam in LAMBDAS:
        pw = per_lambda[lam]["_qlike_pw"]
        if lam == 1.00:
            per_lambda[lam]["harvey_dm_vs_lambda1"] = 0.0
            per_lambda[lam]["harvey_p_vs_lambda1"] = 1.0
            per_lambda[lam]["harvey_pass_vs_lambda1"] = False
        else:
            t, p, passed = dm_harvey(pw, base_pw)
            per_lambda[lam]["harvey_dm_vs_lambda1"] = t
            per_lambda[lam]["harvey_p_vs_lambda1"] = p
            per_lambda[lam]["harvey_pass_vs_lambda1"] = passed
        # drop pointwise before returning
        per_lambda[lam].pop("_qlike_pw", None)

        r = per_lambda[lam]
        print(f"    lambda={lam:.3f}  QLIKE={r['qlike']:+.5f}  "
              f"switch_freq={r['weight_switch_freq']:.4f}  "
              f"avg_max_w={r['posterior_avg_max_weight']:.3f}  "
              f"Harvey t={r['harvey_dm_vs_lambda1']:+.2f} "
              f"pass={r['harvey_pass_vs_lambda1']}")

    return {str(lam): per_lambda[lam] for lam in LAMBDAS}


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
def verdict_h1(per_asset: Dict) -> Dict:
    """H1: any lambda<1 variant has Harvey |t|>3 (vs lambda=1) AND lower QLIKE."""
    passing_cells = []
    for asset, lams in per_asset.items():
        base_q = lams["1.0"]["qlike"]
        for lam_str, r in lams.items():
            if lam_str == "1.0":
                continue
            if r["harvey_pass_vs_lambda1"] and r["qlike"] < base_q:
                passing_cells.append({"asset": asset, "lambda": float(lam_str),
                                      "qlike_delta": r["qlike"] - base_q,
                                      "harvey_t": r["harvey_dm_vs_lambda1"]})
    if not passing_cells:
        verdict = "FAIL"
    elif len({c["asset"] for c in passing_cells}) == 3:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"
    return {
        "null": "ff-BMA QLIKE >= standard BMA (lambda=1) QLIKE",
        "alt": "At least one lambda<1 variant has Harvey |t|>3 AND lower QLIKE",
        "verdict": verdict,
        "passing_cells": passing_cells,
    }


def verdict_h2(per_asset: Dict) -> Dict:
    """H2: lambda<1 weight-switch-freq substantially higher than lambda=1."""
    evidence = {}
    passes = []
    for asset, lams in per_asset.items():
        base_sf = lams["1.0"]["weight_switch_freq"]
        asset_ev = {"baseline_switch_freq": base_sf}
        asset_pass = False
        for lam_str, r in lams.items():
            if lam_str == "1.0":
                continue
            sf = r["weight_switch_freq"]
            # "substantially higher" = at least 2x baseline AND >= 0.01
            if np.isfinite(sf) and np.isfinite(base_sf):
                if sf >= max(2 * base_sf, 0.01):
                    asset_pass = True
            asset_ev[lam_str] = sf
        evidence[asset] = asset_ev
        passes.append(asset_pass)
    if not passes:
        verdict = "NULL"
    elif all(passes):
        verdict = "PASS"
    elif any(passes):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return {
        "null": "Weight-switch-frequency not higher for lambda<1 than lambda=1",
        "alt": "lambda<1 substantially increases switch-freq (>=2x baseline)",
        "verdict": verdict,
        "evidence": evidence,
    }


def verdict_h3(per_asset: Dict) -> Dict:
    """H3: optimal lambda varies by asset."""
    optimal = {}
    for asset, lams in per_asset.items():
        best_lam = min(lams, key=lambda k: lams[k]["qlike"])
        optimal[asset] = float(best_lam)
    unique = set(optimal.values())
    if len(unique) == 1:
        verdict = "FAIL"    # all assets share same optimum
    else:
        verdict = "PASS"    # asset-specific optima
    return {
        "null": "Optimal lambda universal across assets",
        "alt": "Optimal lambda is asset-specific",
        "verdict": verdict,
        "optimal_per_asset": optimal,
    }


def verdict_h4(per_asset: Dict, h1: Dict, h3: Dict) -> Dict:
    """H4: production default lambda recommendation."""
    # If H1 FAIL everywhere → lambda=1 default (standard BMA).
    # Else if H3 PASS → need adaptive; report per-asset optima.
    # Else → report the single lambda that wins majority assets.
    if h1["verdict"] == "FAIL":
        rec = "lambda=1.0 (standard BMA); no forgetting variant improves QLIKE"
    elif h3["verdict"] == "PASS":
        rec = ("adaptive-needed: optimal lambda is asset-specific "
               f"({h3['optimal_per_asset']})")
    else:
        # count most common optimum
        vals = list(h3["optimal_per_asset"].values())
        most = max(set(vals), key=vals.count)
        rec = f"lambda={most} (optimal for majority of tested assets)"
    return {
        "verdict": rec,
        "rationale": ("Chosen by combining H1 (which lambdas actually beat "
                      "baseline QLIKE with Harvey |t|>3) and H3 (whether the "
                      "optimum is shared across assets)."),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    per_asset: Dict[str, Dict] = {}
    for asset in ASSETS:
        try:
            per_asset[asset] = run_asset(asset)
        except Exception as e:
            import traceback
            traceback.print_exc()
            per_asset[asset] = {"error": str(e)}

    # Hypothesis verdicts
    assets_ok = {a: r for a, r in per_asset.items() if "error" not in r}
    if assets_ok:
        h1 = verdict_h1(assets_ok)
        h2 = verdict_h2(assets_ok)
        h3 = verdict_h3(assets_ok)
        h4 = verdict_h4(assets_ok, h1, h3)
    else:
        h1 = h2 = h3 = h4 = {"verdict": "NULL", "reason": "no assets succeeded"}

    runtime = time.time() - START_TIME

    # Detect whether any forecast parquet was reused
    cache_reuse = any(
        (CACHE_DIR / f"forecasts_{a.replace('.', '_')}.parquet").exists()
        for a in ASSETS)

    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("K1258: Forgetting-Factor BMA Volatility Forecast — "
                  "extending K1257 with exponentially-discounted log-posterior"),
        "proposer": "Claude",
        "executor": "Claude sub-agent (main-thread direct run)",
        "oos_period": "2020-2026",
        "data_period": f"{DATA_START} to {DATA_END}",
        "window": WINDOW,
        "refit": REFIT_EVERY,
        "seed": SEED,
        "models": MODEL_NAMES,
        "lambdas": LAMBDAS,
        "assets": ASSETS,
        "results": per_asset,
        "hypotheses": {"H1": h1, "H2": h2, "H3": h3, "H4": h4},
        "provenance": {
            "k1257_forecast_cache_reuse": cache_reuse,
            "cache_paths": [str((CACHE_DIR / f"forecasts_{a.replace('.', '_')}.parquet").name)
                            for a in ASSETS],
            "runtime_min": round(runtime / 60, 2),
            "quick_mode": QUICK_MODE,
        },
    }

    out_path = SCRIPT_DIR / "k1258_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    # -------------------------------------------------------------------
    # Diagnostic charts
    # -------------------------------------------------------------------
    try:
        _plot_qlike_by_lambda(per_asset)
        _plot_weight_switch_freq(per_asset)
    except Exception as e:
        print(f"  [plot] warning: {e}")

    # Print verdict summary
    print("\n=== Hypothesis verdicts ===")
    for hk in ["H1", "H2", "H3", "H4"]:
        v = out["hypotheses"][hk]
        print(f"  {hk}: {v.get('verdict', 'NA')}")
    print(f"\n=== Runtime: {runtime / 60:.2f} min ===")


def _plot_qlike_by_lambda(per_asset: Dict):
    assets_ok = [a for a, r in per_asset.items() if "error" not in r]
    if not assets_ok:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for asset in assets_ok:
        qs = [per_asset[asset][str(lam)]["qlike"] for lam in LAMBDAS]
        ax.plot(LAMBDAS, qs, marker="o", lw=1.8, label=asset)
    ax.set_xlabel("lambda (forgetting factor)")
    ax.set_ylabel("OOS QLIKE (lower = better)")
    ax.set_title("K1258: OOS QLIKE vs forgetting factor lambda")
    ax.grid(alpha=0.3)
    ax.invert_xaxis()
    ax.legend()
    plt.tight_layout()
    fig_path = SCRIPT_DIR / "k1258_qlike_by_lambda.png"
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {fig_path}")


def _plot_weight_switch_freq(per_asset: Dict):
    assets_ok = [a for a, r in per_asset.items() if "error" not in r]
    if not assets_ok:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for asset in assets_ok:
        sfs = [per_asset[asset][str(lam)]["weight_switch_freq"]
               for lam in LAMBDAS]
        ax.plot(LAMBDAS, sfs, marker="s", lw=1.8, label=asset)
    ax.set_xlabel("lambda (forgetting factor)")
    ax.set_ylabel("Weight-switching frequency (% OOS days)")
    ax.set_title("K1258: posterior argmax switch frequency vs lambda")
    ax.grid(alpha=0.3)
    ax.invert_xaxis()
    ax.legend()
    plt.tight_layout()
    fig_path = SCRIPT_DIR / "k1258_weight_switch_freq.png"
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {fig_path}")


if __name__ == "__main__":
    main()
