#!/usr/bin/env python3
"""
K1317: Forgetting-factor BMA Volatility Forecast
=================================================
[提出: Claude, 執行: Claude agent]

Parent experiment: K1257 (BMA with standard posterior update)

Research question: Does adding a forgetting factor δ < 1 to BMA posterior update
fix K1257's H3 FAIL (posterior concentrates to single model within ~500 days)?
Can regime-adaptive BMA improve QLIKE vs standard BMA (δ=1.0)?

Forgetting-factor BMA update (Raftery et al. 2010 DMA):
  1. Apply forgetting BEFORE likelihood update:
     log_prior = δ × log_posterior_{t-1}   (element-wise)
     log_prior = log_prior - logsumexp(log_prior)  # renormalize
  2. Standard Bayesian update with current day likelihood:
     log_posterior_t = log_prior + log_likelihood_t
     log_posterior_t = log_posterior_t - logsumexp(log_posterior_t)  # normalize

When δ=1.0: identical to standard BMA (K1257 baseline)
When δ<1:   "forgetting" past performance → allows inferior model posterior to recover

Candidate models (same 6 as K1257):
  1. GARCH-N:   GARCH(1,1) + Normal
  2. GJR-N:     GJR-GARCH(1,1) + Normal
  3. GJR-t:     GJR-GARCH(1,1) + Student-t
  4. EGARCH-N:  EGARCH(1,1) + Normal
  5. HAR-ABS:   HAR(1,5,22) on |r_t| (proxy for RV when no 5-min data)
  6. A4f-IV2:   MF-GJR-X with asset-matched IV² (VIX² for SPY, GVZ² for GLD)

Forgetting factors: δ ∈ {0.90, 0.95, 0.99, 1.00}

Assets: SPY, GLD, 0050.TW
IV proxy: SPY→^VIX, GLD→^GVZ, 0050.TW→^VIX
Data period: 2010-01-01 to 2026-04-18
OOS start: 2020-01-01
Rolling window: 1250 days (~5 year)
Refit every: 63 days (quarter)
Seed: 42

Hypotheses:
  H1: Best δ∈{0.90,0.95,0.99} achieves DM Harvey |t|>3 improvement over
      standard BMA (δ=1.00) on ≥1 asset
  H2: Posterior Shannon entropy with best δ significantly higher than
      standard BMA throughout OOS (regime tracking restored), p<0.05
  H3: 0050.TW H1 PASS with best δ (K1257 original H3 FAIL: posterior
      concentrated on GJR-t)

References:
  - Raftery et al. (2010) "Online Prediction Under Model Uncertainty via
    Dynamic Model Averaging" JASA 105(490):1303-1316
  - Cogley & Sargent (2005) "Drifts and Volatilities" — macro forgetting factor
  - Geweke & Amisano (2011) "Optimal Prediction Pools" J. Econometrics 164(1):130-141

Lookahead protection (indexing convention):
  - IS window [s..t-1] used for MLE fit
  - posterior update: log p(y_t | F_{t-1}) uses h_{i,t} formed from F_{t-1}
  - BMA forecast: h_t = sum_i w_{i,t-1} * h_{i,t}  (uses t-1's posterior weights)
  - QLIKE_t = log(h_t) + r_t²/h_t  (observation at time t, forecast from t-1)
  - No lookahead: w_{t-1} recorded BEFORE y_t is observed
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
EXPERIMENT_ID = "K1317"
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

# K1317 specific: forgetting factor grid
DELTA_GRID = [0.90, 0.95, 0.99, 1.00]  # 1.00 = standard BMA (K1257 baseline)

QUICK_MODE = "--quick" in sys.argv

if QUICK_MODE:
    DATA_START = "2016-01-01"
    OOS_START = "2022-01-01"
    WINDOW = 750
    REFIT_EVERY = 126
    ASSETS = ["SPY"]  # only SPY in quick mode
    print("*** QUICK MODE: SPY only, 2016-2026, W=750, refit=126 ***")

print("=" * 72)
print(f"{EXPERIMENT_ID}: Forgetting-factor BMA Volatility Forecast")
print(f"Delta grid: {DELTA_GRID}")
print("=" * 72)

# -----------------------------------------------------------------
# Data loading (identical to K1257)
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
# Model recursions (pure-NumPy, identical to K1257)
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
# Fit functions (identical to K1257)
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
# BMA log predictive density at single point (identical to K1257)
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
# DM Harvey test (identical to K1257)
# -----------------------------------------------------------------
def dm_harvey(loss1, loss2):
    """DM Harvey test: H0: loss1 == loss2. Negative t_stat → loss1 < loss2 (loss1 wins)."""
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


# -----------------------------------------------------------------
# Shannon entropy helper
# -----------------------------------------------------------------
def shannon_entropy(weights_vec):
    """Shannon entropy H = -sum(w * log(w)), clips w < 1e-300 to avoid -inf."""
    w = np.clip(weights_vec, 1e-300, None)
    return float(-np.sum(w * np.log(w)))


# -----------------------------------------------------------------
# K1317 Core: BMA OOS with forgetting factor delta
# -----------------------------------------------------------------
def run_bma_oos(asset, df, delta):
    """
    Run BMA OOS forecasting with forgetting factor delta.
    delta=1.0 → standard BMA (K1257 baseline)
    delta<1   → forgetting-factor BMA (regime-adaptive)

    Lookahead protection:
    - At time t, we have posterior from t-1 (log_weights)
    - We compute h_{i,t} from fit using data[s:t] (NOT including t)
    - BMA forecast for t = sum_i w_{i,t-1} * h_{i,t}  (used for QLIKE at t)
    - After seeing r_t, we update posterior via forgetting then likelihood
    - QLIKE_t = log(bma_forecast_t) + r_t^2 / bma_forecast_t
    """
    returns = df["ret"].values
    iv2 = df["iv2"].values
    r2 = df["r2"].values
    abs_ret = df["abs_ret"].values
    T = len(df)
    oos_start_idx = int(np.where(df.index >= OOS_START)[0][0])
    n_oos = T - oos_start_idx

    forecasts = {m: np.full(T, np.nan) for m in MODEL_NAMES}

    # initial log-prior: uniform
    log_weights = np.log(np.full(len(MODEL_NAMES), 1.0 / len(MODEL_NAMES)))

    bma_forecasts = np.full(T, np.nan)
    # weight_history[t]: pre-update posterior used to form BMA forecast for day t
    weight_history = np.full((T, len(MODEL_NAMES)), np.nan)
    # entropy_history[t]: post-update posterior entropy (reflects forgetting effect)
    entropy_history = np.full(T, np.nan)

    state = {"last_fit": -1}
    C_GAMMA_NORMAL = math.sqrt(2.0 / math.pi)

    for t in range(oos_start_idx, T):
        need_refit = (state["last_fit"] < 0
                      or (t - state["last_fit"]) >= REFIT_EVERY)
        if need_refit:
            s = max(0, t - WINDOW)
            tr = returns[s:t]   # IS window = [s, t-1], length up to WINDOW
            tv = iv2[s:t]       # same IS window for IV
            # Refit all models using data strictly before t (no lookahead)
            try:
                state["garch_n"] = fit_garch_n(tr)
            except Exception as e:
                state["garch_n"] = None
            try:
                state["gjr_n"] = fit_gjr_n(tr)
            except Exception as e:
                state["gjr_n"] = None
            try:
                state["gjr_t"] = fit_gjr_t(tr)
            except Exception as e:
                state["gjr_t"] = None
            try:
                state["egarch_n"] = fit_egarch_n(tr)
            except Exception as e:
                state["egarch_n"] = None
            try:
                state["har"] = fit_har_abs(tr)
            except Exception as e:
                state["har"] = None
            try:
                state["a4f"] = fit_a4f(tr, tv)
            except Exception as e:
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
                p = state["a4f"]["params"]
                h_in, tau_in, g_in = a4f_h(p[0], p[1], p[2], p[3], p[4], p[5],
                                           tr, tv)
                state["g_a4f"] = g_in[-1]

        # --- Generate h_{i,t} forecasts using info at t-1 ---
        r_prev = returns[t - 1]    # r_{t-1}: available at start of day t
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0

        # GARCH-N: h_t = omega + alpha*r_{t-1}^2 + beta*h_{t-1}
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
        # A4f: uses iv2[t-1] and r_{t-1} (both available at start of day t)
        if state.get("a4f") is not None:
            p = state["a4f"]["params"]
            tau_t = max(p[0] + p[1] * iv2[t - 1], 1e-16)
            u2 = r2_prev / tau_t
            g_t = max(p[2] + p[3] * u2 + p[4] * u2 * ind
                      + p[5] * state["g_a4f"], 1e-16)
            h_t = tau_t * g_t
            forecasts["A4f_IV2"][t] = h_t
            state["g_a4f"] = g_t

        # --- Record pre-update weights (used for BMA forecast at day t) ---
        # weight_history[t] = w_{t-1}: the posterior BEFORE today's update
        # This is what forms the BMA forecast — no lookahead
        weight_history[t, :] = np.exp(log_weights)

        # --- BMA forecast = sum_i w_{i,t-1} * h_{i,t} ---
        h_vec = np.array([forecasts[m][t] for m in MODEL_NAMES])
        valid = np.isfinite(h_vec) & (h_vec > 0)
        if valid.any():
            # normalize weights over valid models only
            w_valid = np.exp(log_weights[valid] - logsumexp(log_weights[valid]))
            bma_forecasts[t] = float(np.sum(w_valid * h_vec[valid]))

        # --- K1317: Forgetting-factor posterior update ---
        # Step 1: Apply forgetting factor BEFORE likelihood update
        # Clip log_w > -500 to avoid nan when delta * (-inf) scenarios
        log_w_clipped = np.clip(log_weights, -500.0, None)
        log_w_forgotten = delta * log_w_clipped           # scale: δ × log_w
        log_w_forgotten = log_w_forgotten - logsumexp(log_w_forgotten)  # renormalize

        # Step 2: Standard Bayesian update with today's observation y_t = returns[t]
        y_t = returns[t]
        log_liks = np.zeros(len(MODEL_NAMES))
        for mi, m in enumerate(MODEL_NAMES):
            h_pred = forecasts[m][t]
            if not np.isfinite(h_pred) or h_pred <= 0:
                log_liks[mi] = -1e10  # effectively zero weight for failed model
                continue
            if m == "GJR_t" and state.get("gjr_t") is not None:
                lp = log_pred_density(y_t, h_pred, "t",
                                      df=state["gjr_t"]["df"])
            else:
                lp = log_pred_density(y_t, h_pred, "normal")
            log_liks[mi] = lp

        log_weights = log_w_forgotten + log_liks      # Bayesian update
        log_weights = log_weights - logsumexp(log_weights)  # normalize

        # --- Record post-update entropy (H2 metric: does forgetting maintain diversity?) ---
        # entropy_history[t] = H(w_t): entropy AFTER updating with y_t
        # This correctly measures the forgetting factor's effect on posterior concentration
        entropy_history[t] = shannon_entropy(np.exp(log_weights))

    # -----------------------------------------------------------------
    # OOS evaluation
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
    oos_weights = weight_history[oos_idx]
    oos_entropy = entropy_history[oos_idx]

    # Entropy collapse metric: fraction of days with max(w_i) > 0.99
    max_weight_daily = np.max(oos_weights, axis=1)
    collapsed_mask = max_weight_daily > 0.99
    entropy_collapsed_frac = float(np.nanmean(collapsed_mask))

    mean_qlike = float(np.nanmean(qlike_bma_pw))
    mean_entropy = float(np.nanmean(oos_entropy[np.isfinite(oos_entropy)]))
    final_weights = {m: float(np.exp(log_weights[i])) for i, m in enumerate(MODEL_NAMES)}

    return {
        "qlike": mean_qlike,
        "mean_entropy": mean_entropy,
        "entropy_collapsed_frac": entropy_collapsed_frac,
        "final_weights": final_weights,
        "_oos_idx": oos_idx,
        "_qlike_pw": qlike_bma_pw,
        "_weight_history": oos_weights,
        "_entropy_history": oos_entropy,
        "_forecasts": forecasts,
    }


# -----------------------------------------------------------------
# Run per asset: all deltas + individual model forecasts for benchmarks
# -----------------------------------------------------------------
def run_asset(asset, df):
    print(f"\n[Asset: {asset}] N={len(df)}, span={df.index[0].date()} -> "
          f"{df.index[-1].date()}", flush=True)

    returns = df["ret"].values
    r2 = df["r2"].values
    T = len(df)
    oos_start_idx = int(np.where(df.index >= OOS_START)[0][0])
    oos_idx = np.arange(oos_start_idx, T)
    oos_r2 = r2[oos_idx]
    n_oos = T - oos_start_idx

    # Run BMA for each delta
    delta_results = {}
    delta_charts = {}  # for plotting
    gjr_t_forecasts_ref = None  # will grab from delta=1.0 run

    for delta in DELTA_GRID:
        delta_str = str(delta)
        print(f"  Running delta={delta}...", flush=True)
        t0 = time.time()
        res = run_bma_oos(asset, df, delta)
        elapsed = time.time() - t0
        print(f"    done in {elapsed:.0f}s, QLIKE={res['qlike']:.6f}, "
              f"mean_entropy={res['mean_entropy']:.4f}, "
              f"collapsed_frac={res['entropy_collapsed_frac']:.3f}", flush=True)

        # Store GJR-t individual forecasts from standard BMA run (delta=1.0)
        # for DM comparison against best-delta BMA
        if delta == 1.00:
            gjr_t_forecasts_ref = res["_forecasts"]["GJR_t"]

        delta_results[delta_str] = {
            "qlike": res["qlike"],
            "mean_entropy": res["mean_entropy"],
            "entropy_collapsed_frac": res["entropy_collapsed_frac"],
            "final_weights": res["final_weights"],
        }
        delta_charts[delta_str] = {
            "qlike_pw": res["_qlike_pw"],
            "weight_history": res["_weight_history"],
            "entropy_history": res["_entropy_history"],
        }

    # -----------------------------------------------------------------
    # Split OOS into selection half and inference half
    # Selection half (first 50%): pick best delta by lowest mean QLIKE
    # Inference half (second 50%): run DM Harvey tests on held-out data
    # This avoids winner's curse from selecting delta on the same data used for inference
    # -----------------------------------------------------------------
    n_oos = len(oos_idx)
    n_sel = n_oos // 2                    # selection half length
    sel_idx = oos_idx[:n_sel]             # first 50% of OOS → delta selection
    inf_idx = oos_idx[n_sel:]             # second 50% of OOS → hypothesis testing
    inf_r2 = r2[inf_idx]

    def qlike_on_subset(pw_series, subset_relative_mask=None):
        """Extract QLIKE for inference half from pointwise loss array (length=n_oos)."""
        # pw_series is indexed 0..n_oos-1, corresponding to oos_idx
        return pw_series[n_sel:]   # second half

    non_baseline = [str(d) for d in DELTA_GRID if d < 1.0]
    # Select best delta on FIRST HALF of OOS (selection split)
    best_delta_str = min(non_baseline,
                         key=lambda d: float(np.nanmean(delta_charts[d]["qlike_pw"][:n_sel])))
    best_delta = float(best_delta_str)
    print(f"  Best delta (selected on first {n_sel} OOS days): {best_delta_str}", flush=True)

    # -----------------------------------------------------------------
    # DM Harvey tests — evaluated on INFERENCE HALF only (held-out from selection)
    # -----------------------------------------------------------------
    # (a) Best delta vs standard BMA (delta=1.00)
    qlike_best_inf = qlike_on_subset(delta_charts[best_delta_str]["qlike_pw"])
    qlike_standard_inf = qlike_on_subset(delta_charts["1.0"]["qlike_pw"])

    dm_best_vs_standard = dm_harvey(qlike_best_inf, qlike_standard_inf)
    # Note: negative t_stat means best_delta QLIKE < standard BMA QLIKE (best wins)

    # (b) Best delta BMA vs GJR-t individual model (on inference half)
    if gjr_t_forecasts_ref is not None:
        def qlike_pointwise_arr(h_arr):
            h = h_arr[oos_idx]
            out = np.full(len(oos_idx), np.nan)
            mask = np.isfinite(h) & (h > 0)
            out[mask] = np.log(h[mask]) + oos_r2[mask] / h[mask]
            return out
        qlike_gjr_t_pw = qlike_pointwise_arr(gjr_t_forecasts_ref)
        qlike_gjr_t_inf = qlike_on_subset(qlike_gjr_t_pw)
        dm_best_vs_gjr_t = dm_harvey(qlike_best_inf, qlike_gjr_t_inf)
    else:
        dm_best_vs_gjr_t = (0.0, 1.0, False)
        qlike_gjr_t_pw = np.full(len(oos_idx), np.nan)

    # Also store full-OOS QLIKE for reporting/charting
    qlike_best_fulloos = delta_charts[best_delta_str]["qlike_pw"]
    qlike_standard_fulloos = delta_charts["1.0"]["qlike_pw"]

    # -----------------------------------------------------------------
    # H2: entropy comparison (best delta vs standard BMA)
    # HAC t-test (DM-style, Newey-West kernel) on entropy difference series
    # Uses INFERENCE HALF to match H1 test discipline
    # -----------------------------------------------------------------
    ent_best_full = delta_charts[best_delta_str]["entropy_history"]
    ent_standard_full = delta_charts["1.0"]["entropy_history"]
    ent_diff_full = ent_best_full - ent_standard_full
    # Use inference half for consistent split discipline
    ent_diff_inf = ent_diff_full[n_sel:]
    valid_diff = ent_diff_inf[np.isfinite(ent_diff_inf)]
    if len(valid_diff) > 10:
        # HAC t-test: same DM-Harvey kernel as used for QLIKE comparisons
        # This is robust to autocorrelation in entropy differences
        t_ent_harvey, p_ent_twosided, _ = dm_harvey(
            -ent_best_full[n_sel:],      # negate so dm_harvey(loss1,loss2) → loss1<loss2 = ent_best wins
            -ent_standard_full[n_sel:]   # negate: higher entropy = "lower loss"
        )
        # dm_harvey negative t_stat → first series lower (i.e., entropy_best > entropy_standard)
        # We want t < 0 for H2 PASS (best entropy is higher)
        t_ent = -t_ent_harvey   # flip sign: positive = best_delta has higher entropy
        p_ent_onesided = float(p_ent_twosided / 2) if t_ent > 0 else 1.0
        h2_pass = bool(t_ent > 0 and p_ent_onesided < 0.05)
    else:
        t_ent, p_ent_onesided, h2_pass = 0.0, 1.0, False

    # -----------------------------------------------------------------
    # Compile per-asset result
    # -----------------------------------------------------------------
    # H1 PASS check: DM Harvey |t|>3 AND best_delta QLIKE < standard QLIKE
    # Both criteria evaluated on INFERENCE HALF (held-out from delta selection)
    qlike_best_inf_mean = float(np.nanmean(qlike_best_inf))
    qlike_standard_inf_mean = float(np.nanmean(qlike_standard_inf))
    h1_pass = (abs(dm_best_vs_standard[0]) > 3.0 and
               qlike_best_inf_mean < qlike_standard_inf_mean)
    # H3 PASS: 0050.TW H1 PASS with best delta — same criterion as H1 but restricted to TW
    # (K1257 H3 FAIL = posterior concentrated on GJR-t; H3 here asks if forgetting fixes this)
    # Criterion: DM Harvey |t|>3 AND best_delta QLIKE < standard BMA QLIKE on inference half
    h3_pass_tw = bool(h1_pass) if asset == "0050.TW" else None

    result = {
        "n_oos": int(n_oos),
        "n_oos_selection_half": int(n_sel),
        "n_oos_inference_half": int(n_oos - n_sel),
        "per_delta": delta_results,
        "best_delta": best_delta_str,
        "best_delta_selection_note": (
            f"delta selected on first {n_sel} OOS days; "
            f"DM/H2 tests on remaining {n_oos - n_sel} inference days"
        ),
        "gjr_t_individual_qlike_fulloos": float(np.nanmean(qlike_gjr_t_pw))
                                           if gjr_t_forecasts_ref is not None else None,
        "gjr_t_individual_qlike_inf": float(np.nanmean(qlike_gjr_t_inf))
                                       if gjr_t_forecasts_ref is not None else None,
        "qlike_best_inf_mean": qlike_best_inf_mean,
        "qlike_standard_inf_mean": qlike_standard_inf_mean,
        "dm_best_vs_standard": {
            "t_stat": dm_best_vs_standard[0],
            "p_value": dm_best_vs_standard[1],
            "harvey_pass": dm_best_vs_standard[2],
            "evaluated_on": "inference_half",
            "note": "negative t_stat = best_delta BMA wins (lower QLIKE)"
        },
        "dm_best_vs_gjr_t": {
            "t_stat": dm_best_vs_gjr_t[0],
            "p_value": dm_best_vs_gjr_t[1],
            "harvey_pass": dm_best_vs_gjr_t[2],
            "evaluated_on": "inference_half",
            "note": "negative t_stat = best_delta BMA wins vs GJR-t individual"
        },
        "h1_pass_this_asset": bool(h1_pass),
        "h2_entropy_hac_tstat": float(t_ent),
        "h2_entropy_pvalue_onesided": float(p_ent_onesided),
        "h2_pass_this_asset": bool(h2_pass),
        "h2_note": "HAC Newey-West t-test on entropy diff (best_delta - standard), inference half",
        "h3_pass_tw": h3_pass_tw,
    }

    # Keep chart data separate
    result["_charts"] = {
        "oos_idx": oos_idx,
        "dates": df.index[oos_idx],
        "delta_charts": delta_charts,
        "qlike_gjr_t_pw": qlike_gjr_t_pw,
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

        print(f"\n[{asset}] Summary:")
        print(f"  Best delta: {res['best_delta']}")
        for d_str, dr in res["per_delta"].items():
            print(f"  delta={d_str}: QLIKE={dr['qlike']:.6f}, "
                  f"entropy={dr['mean_entropy']:.4f}, "
                  f"collapsed={dr['entropy_collapsed_frac']:.3f}")
        print(f"  DM best_delta vs standard: t={res['dm_best_vs_standard']['t_stat']:+.2f}, "
              f"p={res['dm_best_vs_standard']['p_value']:.4f}, "
              f"harvey_pass={res['dm_best_vs_standard']['harvey_pass']}")
        print(f"  DM best_delta vs GJR-t: t={res['dm_best_vs_gjr_t']['t_stat']:+.2f}, "
              f"p={res['dm_best_vs_gjr_t']['p_value']:.4f}, "
              f"harvey_pass={res['dm_best_vs_gjr_t']['harvey_pass']}")
        print(f"  H1 PASS this asset: {res['h1_pass_this_asset']}")
        print(f"  H2 PASS this asset: {res['h2_pass_this_asset']} "
              f"(HAC t={res['h2_entropy_hac_tstat']:+.2f}, p={res['h2_entropy_pvalue_onesided']:.4f})")

    # -----------------------------------------------------------------
    # Hypothesis verdicts
    # -----------------------------------------------------------------
    assets_ok = [a for a in per_asset if "error" not in per_asset[a]]

    # H1: best delta achieves |t|>3 AND lower QLIKE than standard BMA on ≥1 asset
    h1_any = any(per_asset[a]["h1_pass_this_asset"] for a in assets_ok)
    h1_verdict = "PASS" if h1_any else "FAIL"

    # H2: mean posterior entropy with best delta > standard BMA (p<0.05) on ≥1 asset
    h2_any = any(per_asset[a]["h2_pass_this_asset"] for a in assets_ok)
    h2_verdict = "PASS" if h2_any else "FAIL"

    # H3: 0050.TW H1 PASS with best delta
    if "0050.TW" in assets_ok:
        tw_res = per_asset["0050.TW"]
        h3_verdict = "PASS" if tw_res.get("h3_pass_tw") else "FAIL"
    else:
        h3_verdict = "NULL"

    # Overall: PASS if any H is PASS (at least 1 dimension of improvement)
    overall_pass = any(v == "PASS" for v in [h1_verdict, h2_verdict, h3_verdict])
    overall_verdict = "PASS" if overall_pass else "NULL"

    verdicts = {"H1": h1_verdict, "H2": h2_verdict, "H3": h3_verdict}
    print("\n=== Hypothesis verdicts ===")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    print(f"  Overall: {overall_verdict}")

    # -----------------------------------------------------------------
    # Conclusions
    # -----------------------------------------------------------------
    asset_lines = []
    for a in assets_ok:
        r = per_asset[a]
        bd = r["best_delta"]
        bq = r["per_delta"][bd]["qlike"]
        sq = r["per_delta"]["1.0"]["qlike"]
        diff = bq - sq
        asset_lines.append(
            f"{a}: best_delta={bd}, QLIKE={bq:.5f} vs standard={sq:.5f} "
            f"(diff={diff:+.5f}), "
            f"DM t={r['dm_best_vs_standard']['t_stat']:+.2f} "
            f"(harvey_pass={r['dm_best_vs_standard']['harvey_pass']}), "
            f"entropy {r['per_delta'][bd]['mean_entropy']:.4f} vs "
            f"{r['per_delta']['1.0']['mean_entropy']:.4f} "
            f"(H2 pass={r['h2_pass_this_asset']})"
        )

    conclusions = {
        "summary": (
            f"K1317 Forgetting-factor BMA: tested δ∈{{0.90,0.95,0.99,1.00}} "
            f"on {list(assets_ok)} 2020-2026 OOS. "
            f"H1 verdict: {h1_verdict} (best δ achieves DM Harvey |t|>3 vs standard BMA on ≥1 asset). "
            f"H2 verdict: {h2_verdict} (entropy improvement significant p<0.05). "
            f"H3 verdict: {h3_verdict} (0050.TW H1 pass). "
            f"Overall: {overall_verdict}."
        ),
        "per_asset": asset_lines,
        "interpretation": (
            "If H1=FAIL and H2=PASS: forgetting factor successfully maintains "
            "posterior diversity (entropy restored) but QLIKE improvement not "
            "statistically significant — vol forecasting BMA is fast-converging "
            "benign (best model is stable, not regime-dependent). "
            "If H1=PASS: forgetting factor genuinely helps regime tracking in QLIKE sense. "
            "NULL result is valuable: confirms K1257 finding that BMA quickly "
            "selects best model is correct behavior, not a deficiency. "
            "Raftery (2010) DMA forgetting factor design is appropriate for "
            "TV-parameter models; for stable GARCH pool, convergence is expected."
        ),
        "paper_implication": (
            "For Paper 2/3 (BMA framework): K1317 null result would strengthen "
            "the narrative that the 6-model pool converges correctly to the "
            "dominant model (GJR-t), supporting parsimony. "
            "K1317 pass would justify including DMA as robustness extension."
        ),
    }

    # -----------------------------------------------------------------
    # Build final JSON
    # -----------------------------------------------------------------
    runtime = time.time() - START_TIME

    # Build clean per_asset for JSON (remove _charts)
    per_asset_clean = {}
    for a in per_asset:
        if "error" in per_asset[a]:
            per_asset_clean[a] = per_asset[a]
        else:
            per_asset_clean[a] = {k: v for k, v in per_asset[a].items()
                                   if not k.startswith("_")}

    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("K1317: Forgetting-factor BMA Volatility Forecast "
                  "— Testing δ∈{0.90,0.95,0.99,1.00} on 6-model GARCH/HAR/IV pool"),
        "parent_experiment": "K1257",
        "proposer": "Claude",
        "executor": "Claude agent",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_start": OOS_START,
        "rolling_window": WINDOW,
        "refit_freq": REFIT_EVERY,
        "seed": SEED,
        "delta_grid": DELTA_GRID,
        "models": MODEL_NAMES,
        "assets": list(per_asset_clean.keys()),
        "per_asset": per_asset_clean,
        "hypothesis_verdicts": verdicts,
        "overall_verdict": overall_verdict,
        "conclusions": conclusions,
        "runtime_seconds": round(runtime, 1),
        "quick_mode": QUICK_MODE,
        "references": [
            "Raftery et al. (2010) JASA 105(490):1303-1316 — DMA forgetting factor",
            "Cogley & Sargent (2005) — macro forecasting forgetting factor",
            "Geweke & Amisano (2011) J.Econometrics 164(1):130-141 — optimal prediction pools",
        ],
    }

    out_path = os.path.join(SCRIPT_DIR, "k1317_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    # -----------------------------------------------------------------
    # Chart 1: Entropy evolution (3 assets × 4 delta)
    # -----------------------------------------------------------------
    n_assets = len(charts_data)
    if n_assets > 0:
        n_deltas = len(DELTA_GRID)
        fig, axes = plt.subplots(n_assets, 1, figsize=(14, 4 * n_assets),
                                 sharex=False)
        if n_assets == 1:
            axes = [axes]
        delta_colors = {
            "0.9": "#e74c3c",
            "0.95": "#e67e22",
            "0.99": "#27ae60",
            "1.0": "#7f8c8d",
        }
        for ax, (a, cd) in zip(axes, charts_data.items()):
            dates = cd["dates"]
            for d_str, dc in cd["delta_charts"].items():
                ent = dc["entropy_history"]
                color = delta_colors.get(d_str, "#333")
                lw = 2.0 if d_str == "1.0" else 1.5
                ls = "--" if d_str == "1.0" else "-"
                label = f"δ={d_str}" + (" (standard BMA)" if d_str == "1.0" else "")
                valid_mask = np.isfinite(ent)
                if valid_mask.any():
                    ax.plot(dates[valid_mask], ent[valid_mask],
                            label=label, color=color, lw=lw, ls=ls, alpha=0.85)
            ax.set_title(f"{a}: Posterior Shannon Entropy over OOS (higher = more diverse)")
            ax.set_ylabel("Shannon Entropy (nats)")
            ax.grid(alpha=0.3)
            ax.legend(loc="upper right", fontsize=9)
        plt.tight_layout()
        fig_path = os.path.join(SCRIPT_DIR, "k1317_entropy_evolution.png")
        plt.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fig_path}")

    # -----------------------------------------------------------------
    # Chart 2: QLIKE comparison bar chart
    # -----------------------------------------------------------------
    if assets_ok:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        ax1, ax2 = axes

        x = np.arange(len(assets_ok))
        n_d = len(DELTA_GRID)
        bar_w = 0.8 / n_d
        bar_colors = ["#e74c3c", "#e67e22", "#27ae60", "#7f8c8d"]

        for di, delta in enumerate(DELTA_GRID):
            d_str = str(delta)
            qlike_vals = [per_asset_clean[a]["per_delta"][d_str]["qlike"]
                          for a in assets_ok]
            label = f"δ={d_str}" + (" (standard)" if delta == 1.0 else "")
            offset = (di - n_d / 2 + 0.5) * bar_w
            ax1.bar(x + offset, qlike_vals, bar_w, label=label,
                    color=bar_colors[di], alpha=0.85)

        ax1.set_xticks(x)
        ax1.set_xticklabels(assets_ok)
        ax1.set_ylabel("Mean QLIKE (lower = better)")
        ax1.set_title("OOS QLIKE by δ — K1317 Forgetting-factor BMA")
        ax1.legend(fontsize=8)
        ax1.grid(alpha=0.3, axis="y")

        # DM t-stats: best delta vs standard BMA
        dm_tstats = [per_asset_clean[a]["dm_best_vs_standard"]["t_stat"]
                     for a in assets_ok]
        dm_colors = ["#27ae60" if t < -3 else "#e74c3c" if t > 3 else "#95a5a6"
                     for t in dm_tstats]
        ax2.bar(x, dm_tstats, 0.5, color=dm_colors, alpha=0.85,
                label="DM t-stat (best δ vs δ=1.0)")
        ax2.axhline(-3.0, ls="--", color="k", lw=1.2, label="Harvey |t|>3 threshold")
        ax2.axhline(3.0, ls="--", color="k", lw=1.2)
        ax2.axhline(0.0, ls="-", color="gray", lw=0.8)
        ax2.set_xticks(x)
        ax2.set_xticklabels(assets_ok)
        ax2.set_ylabel("DM-Harvey t-stat (negative = best δ BMA wins)")
        ax2.set_title("DM Harvey: Best δ vs Standard BMA (δ=1.0)")
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.3, axis="y")

        plt.tight_layout()
        fig_path = os.path.join(SCRIPT_DIR, "k1317_qlike_comparison.png")
        plt.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {fig_path}")

    print(f"\n=== Runtime: {time.time() - START_TIME:.1f}s ===")


if __name__ == "__main__":
    main()
