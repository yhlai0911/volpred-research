#!/usr/bin/env python3
"""
K1094: A4f-VT vs 8.63/VIX on 0050.TW — Paper 3 Cross-Market Replication of K1074
================================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation
----------
K1074 tested A4f-VT vs 12/VIX-VT on SPY and found:
  - 12/VIX-VT Sharpe ≈ 0.86
  - A4f-VT    Sharpe ≈ 0.84
  - Difference p=0.64 NS
  → statistical edge (A4f) does NOT translate into strategy edge

K1077 showed A4f is statistically NULL on 0050.TW (DM t=-0.49).

Research questions
------------------
H1: If A4f is statistically NULL on 0050.TW, does it also LOSE to 8.63/VIX
    as a strategy? (statistical null -> economic null?)
H2: Or do both deliver similar Sharpe, mirroring K1074's SPY pattern
    (statistical edge ≠ strategy edge)?

Strategies
----------
A: 8.63/VIX              w_t = min(8.63 / VIX_{t-1}, 1.0)   [Taiwan VT baseline]
B: A4f-VT                w_t = min(target_σ / sigma_hat_{A4f,t-1}, 1.5)
C: GJR-VT                w_t = min(target_σ / sigma_hat_{GJR,t-1}, 1.5)
D: 50/50 0050+GLD + 8.63/VIX on TW leg
E: 50/50 0050+GLD + A4f-VT on TW leg

Lag convention
--------------
- weight at date t uses information known at close of t-1
- Taiwan-specific: US VIX at date t-1 (US close) is available before
  TW open on date t+1 in US calendar, but TW close on date t follows
  US close on date t-1 by ~8 hours. yfinance VIX is indexed by US date;
  we forward-fill VIX to TW trading calendar and then shift(1) so that
  w_t uses VIX indexed at the TW trading day t-1 (which reflects US close
  at least 8 hours earlier).

Data
----
0050.TW (clean_tw50_data, 2014 Yahoo split fix)
GLD (yfinance)
^VIX (yfinance)
2005-07-01 -> 2026-04-12. OOS 2013-01-02 -> today.

Evaluation
----------
- Raw + Net Sharpe (2 bp per unit weight change; Taiwan ETF spread)
- MDD, Calmar, Sortino, CAGR
- Annualised turnover
- Bootstrap 95% CI for Sharpe differences (stationary block, 1000 reps)

References
----------
Moreira & Muir (2017). Volatility-Managed Portfolios. JF 72(4):1611-1644.
Harvey et al. (2018). The Impact of Volatility Targeting. JPM 45(1):14-33.
K1074 (SPY analogue), K1077 (A4f statistical test on 0050.TW),
K62/K461 (Taiwan 8.63/VIX calibration), K1058 (Taiwan A4f VaR Trinity PASS).

Author : VolPred Research System
Date   : 2026-04-12
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import optimize

try:
    from numba import njit
except Exception:
    def njit(*a, **k):
        def deco(f):
            return f
        return deco

warnings.filterwarnings("ignore")
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1094"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from volpred.utils import clean_tw50_data  # MANDATORY for 0050.TW

RESULTS_PATH = os.path.join(SCRIPT_DIR, "k1094_results.json")

# --------------------------------------------------------------
# Configuration
# --------------------------------------------------------------
DATA_START = "2005-07-01"
DATA_END   = "2026-04-13"
OOS_START  = "2013-01-02"

WINDOW     = 2000
REFIT      = 63
TARGET_SIG = 0.15          # annualised sigma target for A4f/GJR VT on 0050.TW
                            # Taiwan 0050.TW typical σ ≈ 18-22%; target 15% is
                            # conservative, matching K1058 calibration.
WEIGHT_CAP_VT      = 1.50   # cap for A4f-VT / GJR-VT
WEIGHT_CAP_VIX_TW  = 1.00   # Taiwan 8.63/VIX cap (K461 calibration)
TX_BPS     = 2.0           # Taiwan ETF 2 bp per unit weight change
TRADING_D  = 252

N_BOOT     = 1000
BOOT_BLOCK = 22

print("=" * 72)
print(f"{EXPERIMENT_ID}: A4f-VT vs 8.63/VIX on 0050.TW")
print("       Paper 3 cross-market replication of K1074 (SPY)")
print("=" * 72)

# --------------------------------------------------------------
# 1. Data
# --------------------------------------------------------------
import yfinance as yf

print("\n[1] Loading data ...")

# 0050.TW (mandatory cleaning)
raw_tw = yf.download("0050.TW", start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
if isinstance(raw_tw.columns, pd.MultiIndex):
    raw_tw.columns = raw_tw.columns.get_level_values(0)
prices_tw_raw = raw_tw["Close"].copy()
prices_tw, _ = clean_tw50_data(prices_tw_raw)

# GLD  (USD denominated).  For TW-based 50/50, we use GLD in USD terms;
# we assume a TW investor can hold GLD ETF (e.g., 00635U-equivalent gold
# futures ETF).  This is the same choice as K1074's SPY/GLD split.
raw_gld = yf.download("GLD", start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=True)
if isinstance(raw_gld.columns, pd.MultiIndex):
    raw_gld.columns = raw_gld.columns.get_level_values(0)
gld = raw_gld["Close"].copy()

# VIX
raw_vix = yf.download("^VIX", start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(raw_vix.columns, pd.MultiIndex):
    raw_vix.columns = raw_vix.columns.get_level_values(0)
vix = raw_vix["Close"].copy()

# Align to 0050.TW trading days (TW calendar master)
# Forward-fill VIX and GLD, both use US calendar
vix_tw = vix.reindex(prices_tw.index, method="ffill")
gld_tw = gld.reindex(prices_tw.index, method="ffill")

df = pd.DataFrame({
    "TW": prices_tw,
    "GLD": gld_tw,
    "VIX": vix_tw,
}).dropna()

df["r_tw"]  = np.log(df["TW"]  / df["TW"].shift(1))
df["r_gld"] = np.log(df["GLD"] / df["GLD"].shift(1))
df = df.dropna()

# Safety net on extreme TW returns
max_abs = df["r_tw"].abs().max()
if max_abs > 0.30:
    bad = df[df["r_tw"].abs() > 0.30]
    print(f"   ⚠ Dropping {len(bad)} extreme |log_ret|>0.30 days")
    df = df[df["r_tw"].abs() <= 0.30]

oos_mask_all = np.asarray(df.index >= OOS_START)
print(f"   Total rows : {len(df)}  "
      f"[{df.index[0].date()} -> {df.index[-1].date()}]")
print(f"   OOS rows   : {int(oos_mask_all.sum())}  (from {OOS_START})")
print(f"   |r_tw| max : {df['r_tw'].abs().max():.4f}   "
      f"mean VIX : {df['VIX'].mean():.2f}")

ret     = df["r_tw"].values
ret_gld = df["r_gld"].values
vix_v   = df["VIX"].values
r2      = ret ** 2
dates   = df.index

oos_indices = np.where(oos_mask_all)[0]
n_oos = len(oos_indices)

# --------------------------------------------------------------
# 2. GJR-GARCH(1,1)
# --------------------------------------------------------------
@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = float(np.var(returns))
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll, best = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method="L-BFGS-B", bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best = res.x
        except Exception:
            continue
    return best


def gjr_next(p, h_prev, r_prev):
    omega, alpha, gamma, beta = p
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --------------------------------------------------------------
# 3. A4f multiplicative GARCH-X:
#    tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps)
#    g_t   = omega_g + alpha u^2 + gamma u^2 I(u<0) + beta g_{t-1}
#    u_{t-1} = r_{t-1} / sqrt(tau_t)
#    sigma2_t = tau_t * g_t
# --------------------------------------------------------------
def fit_a4f(returns, vix_vals):
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_lag_sq = vix_lag ** 2

    var0 = float(np.var(returns))
    vix2_mean = float(np.mean(vix_lag_sq) + 1e-8)

    def neg_ll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)
        g = np.empty(n)
        eg = omega_g / max(1.0 - persist, 1e-8)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    starts = [
        [var0 * 0.10, var0 / vix2_mean,        0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5,  0.10, 0.03, 0.08, 0.88],
        [var0 * 0.20, var0 / vix2_mean * 1.5,  0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-10, 1e-2),
              (1e-6, 1.0),   (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll, best = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_ll, s, method="L-BFGS-B", bounds=bounds,
                                    options={"maxiter": 400})
            if res.fun < best_ll:
                best_ll = res.fun
                best = res.x
        except Exception:
            continue
    return best


def a4f_init_state(params, train_ret, train_vix):
    n = len(train_ret)
    vix_lag = np.empty(n)
    vix_lag[0] = train_vix[0]
    vix_lag[1:] = train_vix[:-1]
    tau = np.maximum(params[0] + params[1] * vix_lag**2, 1e-16)
    omega_g, alpha, gamma_p, beta = params[2], params[3], params[4], params[5]
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / max(1.0 - persist, 1e-8)
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        g = max(g, 1e-10)
    return g, tau[-1]


# --------------------------------------------------------------
# 4. Rolling OOS forecasts  (GJR + A4f)
# --------------------------------------------------------------
print("\n[2] Rolling OOS forecasts (GJR + A4f) ...")
print(f"   Window = {WINDOW}  Refit every {REFIT} days  "
      f"n_refits = {int(np.ceil(n_oos / REFIT))}")

sig_gjr = np.full(n_oos, np.nan)   # annualised sigma hat (info t-1)
sig_a4f = np.full(n_oos, np.nan)

gjr_state = {"params": None, "h": None}
a4f_state = {"params": None, "g": None, "tau_prev": None}

convergence_log = {"gjr_fails": 0, "a4f_fails": 0, "refits": 0}

for step, abs_idx in enumerate(oos_indices):
    if step % REFIT == 0:
        convergence_log["refits"] += 1
        elapsed = time.time() - START_TIME
        print(f"   refit at step {step}/{n_oos} "
              f"({df.index[abs_idx].date()})  elapsed={elapsed:.0f}s")
        train_lo = max(0, abs_idx - WINDOW)
        train_ret = ret[train_lo:abs_idx]
        train_vix = vix_v[train_lo:abs_idx]

        p_gjr = fit_gjr(train_ret)
        if p_gjr is not None:
            gjr_state["params"] = p_gjr
            h = float(np.var(train_ret))
            for i in range(1, len(train_ret)):
                h = gjr_next(p_gjr, h, train_ret[i-1])
            gjr_state["h"] = h
        else:
            convergence_log["gjr_fails"] += 1

        p_a4f = fit_a4f(train_ret, train_vix)
        if p_a4f is not None:
            a4f_state["params"] = p_a4f
            g_end, tau_end = a4f_init_state(p_a4f, train_ret, train_vix)
            a4f_state["g"] = g_end
            a4f_state["tau_prev"] = tau_end
        else:
            convergence_log["a4f_fails"] += 1

    r_prev = ret[abs_idx - 1]
    v_prev = vix_v[abs_idx - 1]

    p = gjr_state["params"]
    if p is not None:
        h_new = gjr_next(p, gjr_state["h"], r_prev)
        sig_gjr[step] = np.sqrt(h_new * TRADING_D)
        gjr_state["h"] = h_new

    p = a4f_state["params"]
    if p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p
        tau_t = max(theta0 + theta1 * v_prev**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_state["g"]
        g_new = max(g_new, 1e-10)
        sig_a4f[step] = np.sqrt(tau_t * g_new * TRADING_D)
        a4f_state["g"] = g_new
        a4f_state["tau_prev"] = tau_t

elapsed = time.time() - START_TIME
print(f"   Rolling OOS done in {elapsed:.0f}s. "
      f"nan(GJR)={int(np.isnan(sig_gjr).sum())}  "
      f"nan(A4f)={int(np.isnan(sig_a4f).sum())}  "
      f"refits={convergence_log['refits']}  "
      f"gjr_fails={convergence_log['gjr_fails']}  "
      f"a4f_fails={convergence_log['a4f_fails']}")

# --------------------------------------------------------------
# 5. Weight series (all with t-1 information)
# --------------------------------------------------------------
print("\n[3] Building weight series ...")

oos_ret_tw  = ret[oos_indices]
oos_ret_gld = ret_gld[oos_indices]
oos_vix     = vix_v[oos_indices]
oos_dates   = df.index[oos_indices]

# VIX lag: for TW, 8.63/VIX weight uses VIX as observed at TW close of t-1.
# Since VIX is already forward-filled onto TW calendar, oos_vix[step] is
# the US-close VIX at TW date (step).  We want weight_t to use VIX_{t-1}.
vix_lag_oos = np.empty(n_oos)
vix_lag_oos[0] = vix_v[oos_indices[0] - 1] if oos_indices[0] > 0 else oos_vix[0]
vix_lag_oos[1:] = oos_vix[:-1]

# Strategy A: 8.63/VIX Taiwan VT
w_8vix = np.minimum(8.63 / vix_lag_oos, WEIGHT_CAP_VIX_TW)

# Strategy B: A4f-VT
w_a4f = np.minimum(TARGET_SIG / sig_a4f, WEIGHT_CAP_VT)

# Strategy C: GJR-VT
w_gjr = np.minimum(TARGET_SIG / sig_gjr, WEIGHT_CAP_VT)


def _fill_nan(x, fill=1.0):
    y = x.copy()
    y[np.isnan(y)] = fill
    return y


w_8vix = _fill_nan(w_8vix, 1.0)
w_a4f  = _fill_nan(w_a4f,  1.0)
w_gjr  = _fill_nan(w_gjr,  1.0)

# --------------------------------------------------------------
# 6. Monthly rebalance helpers (50/50)
# --------------------------------------------------------------
first_of_month = np.zeros(n_oos, dtype=bool)
prev_m = None
for i, d in enumerate(oos_dates):
    if d.month != prev_m:
        first_of_month[i] = True
        prev_m = d.month


def portfolio_5050_net(w_leg, r_leg, r_gld, bps=TX_BPS):
    """50% (TW * w_leg) + 50% GLD with monthly rebalance, TX on w_leg changes."""
    n = len(w_leg)
    gross = np.zeros(n)
    net   = np.zeros(n)
    cost  = np.zeros(n)
    alloc_leg, alloc_gld = 0.5, 0.5
    w_prev = w_leg[0]
    for i in range(n):
        if first_of_month[i] and i > 0:
            alloc_leg, alloc_gld = 0.5, 0.5
        dw = abs(w_leg[i] - w_prev)
        c  = (bps / 1e4) * dw * alloc_leg
        cost[i] = c
        g = alloc_leg * w_leg[i] * r_leg[i] + alloc_gld * r_gld[i]
        gross[i] = g
        net[i]   = g - c
        leg_growth = np.exp(alloc_leg * w_leg[i] * r_leg[i])
        gld_growth = np.exp(alloc_gld * r_gld[i])
        total = leg_growth + gld_growth
        alloc_leg = leg_growth / total
        alloc_gld = gld_growth / total
        w_prev = w_leg[i]
    return gross, net, cost


# --------------------------------------------------------------
# 7. Apply transaction costs (2 bps per unit weight change)
# --------------------------------------------------------------
def apply_tx_cost(weights, returns, bps=TX_BPS):
    dw = np.abs(np.diff(weights, prepend=weights[0]))
    cost = (bps / 1e4) * dw
    gross = weights * returns
    net   = gross - cost
    return gross, net, cost


gross_A, net_A, cost_A = apply_tx_cost(w_8vix, oos_ret_tw)
gross_B, net_B, cost_B = apply_tx_cost(w_a4f,  oos_ret_tw)
gross_C, net_C, cost_C = apply_tx_cost(w_gjr,  oos_ret_tw)

gross_D, net_D, cost_D = portfolio_5050_net(w_8vix, oos_ret_tw, oos_ret_gld)
gross_E, net_E, cost_E = portfolio_5050_net(w_a4f,  oos_ret_tw, oos_ret_gld)

# Buy-and-hold benchmarks
bh_tw    = oos_ret_tw
bh_5050  = 0.5 * oos_ret_tw + 0.5 * oos_ret_gld

# --------------------------------------------------------------
# 8. Metrics
# --------------------------------------------------------------
def metrics(returns, name=""):
    r = np.asarray(returns, dtype=float)
    n = len(r)
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    sharpe = mu / sd * np.sqrt(TRADING_D) if sd > 0 else 0.0
    cagr = float(np.exp(mu * TRADING_D) - 1.0)
    cum = np.cumsum(r)
    dd  = cum - np.maximum.accumulate(cum)
    mdd = float(np.min(dd))
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    downside = r[r < 0]
    dd_sd = float(np.std(downside, ddof=1)) if len(downside) > 1 else np.nan
    sortino = mu / dd_sd * np.sqrt(TRADING_D) if dd_sd > 0 else np.nan
    return {
        "name": name,
        "n": int(n),
        "mean_daily": mu,
        "std_daily": sd,
        "sharpe": sharpe,
        "cagr": cagr,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "mean_return_annual": float(mu * TRADING_D),
        "vol_annual": float(sd * np.sqrt(TRADING_D)),
    }


def turnover(weights):
    dw = np.diff(weights)
    return {
        "mean_abs_dw": float(np.mean(np.abs(dw))),
        "annual_notional": float(np.mean(np.abs(dw)) * TRADING_D),
        "mean_w": float(np.mean(weights)),
        "std_w":  float(np.std(weights, ddof=1)),
    }


rng = np.random.default_rng(42)

def block_bootstrap_sharpe_diff(r1, r2, n_boot=N_BOOT, block=BOOT_BLOCK):
    n = len(r1)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n - block + 1)
            idx.extend(range(start, start + block))
        idx = np.asarray(idx[:n])
        a = r1[idx]
        c = r2[idx]
        s1 = np.mean(a) / np.std(a, ddof=1) * np.sqrt(TRADING_D) if np.std(a, ddof=1) > 0 else 0.0
        s2 = np.mean(c) / np.std(c, ddof=1) * np.sqrt(TRADING_D) if np.std(c, ddof=1) > 0 else 0.0
        diffs[b] = s1 - s2
    return {
        "mean":    float(np.mean(diffs)),
        "ci95_lo": float(np.percentile(diffs, 2.5)),
        "ci95_hi": float(np.percentile(diffs, 97.5)),
        "p_two_sided": float(np.mean(diffs * np.sign(np.mean(diffs)) <= 0) * 2),
    }


# --------------------------------------------------------------
# 9. Compute everything
# --------------------------------------------------------------
print("\n[4] Computing metrics ...")

strategy_defs = [
    ("A_8VIX_gross",        gross_A, w_8vix),
    ("A_8VIX_net",          net_A,   w_8vix),
    ("B_A4f_gross",         gross_B, w_a4f),
    ("B_A4f_net",           net_B,   w_a4f),
    ("C_GJR_gross",         gross_C, w_gjr),
    ("C_GJR_net",           net_C,   w_gjr),
    ("D_5050_8VIX_gross",   gross_D, w_8vix),
    ("D_5050_8VIX_net",     net_D,   w_8vix),
    ("E_5050_A4f_gross",    gross_E, w_a4f),
    ("E_5050_A4f_net",      net_E,   w_a4f),
    ("BH_TW",               bh_tw,   None),
    ("BH_5050_TW_GLD",      bh_5050, None),
]

strat_metrics = {}
for name, r_series, w_series in strategy_defs:
    m = metrics(r_series, name)
    if w_series is not None:
        m.update(turnover(w_series))
    strat_metrics[name] = m

# Monthly hit rate: A4f-VT net vs 8.63/VIX net
def month_returns(series, d_index):
    s = pd.Series(series, index=d_index)
    return s.groupby([s.index.year, s.index.month]).sum()


a4f_monthly  = month_returns(net_B, oos_dates)
v8_monthly   = month_returns(net_A, oos_dates)
hit_rate_a4f_vs_8v = float((a4f_monthly > v8_monthly).mean())

series_lookup = dict(zip([x[0] for x in strategy_defs],
                         [x[1] for x in strategy_defs]))

print("   Bootstrap Sharpe-diff tests ...")
pairs = [
    ("B_A4f_net",        "A_8VIX_net"),
    ("B_A4f_net",        "C_GJR_net"),
    ("B_A4f_net",        "BH_TW"),
    ("A_8VIX_net",       "BH_TW"),
    ("E_5050_A4f_net",   "D_5050_8VIX_net"),
    ("E_5050_A4f_net",   "BH_5050_TW_GLD"),
    ("D_5050_8VIX_net",  "BH_5050_TW_GLD"),
]
bootstrap_tests = {}
for a, b in pairs:
    res = block_bootstrap_sharpe_diff(series_lookup[a], series_lookup[b])
    bootstrap_tests[f"{a}__minus__{b}"] = res

# --------------------------------------------------------------
# 10. Assemble results
# --------------------------------------------------------------
results = {
    "experiment_id": EXPERIMENT_ID,
    "description": (
        "A4f-VT vs 8.63/VIX on 0050.TW: Paper 3 cross-market replication of "
        "K1074 (SPY). Tests whether A4f's statistical NULL on 0050.TW (K1077) "
        "also translates into strategy NULL vs 8.63/VIX, or mirrors K1074's "
        "SPY pattern (statistical edge ≠ strategy edge)."
    ),
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (0050.TW via clean_tw50_data, GLD, ^VIX)",
    "data_period": f"{DATA_START} to {df.index[-1].date().isoformat()}",
    "oos_start": OOS_START,
    "oos_end": df.index[-1].date().isoformat(),
    "n_oos": int(n_oos),
    "window": WINDOW,
    "refit_every": REFIT,
    "random_seed": 42,
    "target_sigma": TARGET_SIG,
    "weight_cap_vt": WEIGHT_CAP_VT,
    "weight_cap_vix_tw": WEIGHT_CAP_VIX_TW,
    "tx_bps": TX_BPS,
    "n_bootstrap": N_BOOT,
    "boot_block_size": BOOT_BLOCK,
    "convergence_log": convergence_log,
    "references": [
        "Moreira & Muir (2017). Volatility-Managed Portfolios. JF 72(4):1611-1644.",
        "Harvey et al. (2018). The Impact of Volatility Targeting. JPM 45(1):14-33.",
        "Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.",
        "Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.",
        "K1074 (SPY analogue), K1077 (TW statistical test),"
        " K62/K461 (Taiwan 8.63/VIX calibration), K1058 (TW A4f Trinity PASS).",
    ],
    "strategies": {
        "A_8VIX":       "w_t = min(8.63 / VIX_{t-1}, 1.0)",
        "B_A4f":        "w_t = min(0.15 / sigma_hat_{A4f,t-1}, 1.5)",
        "C_GJR":        "w_t = min(0.15 / sigma_hat_{GJR,t-1}, 1.5)",
        "D_5050_8VIX":  "50% 0050*w_8VIX + 50% GLD; monthly rebalance",
        "E_5050_A4f":   "50% 0050*w_A4f  + 50% GLD; monthly rebalance",
    },
    "metrics": strat_metrics,
    "hit_rate_A4f_vs_8VIX_monthly": hit_rate_a4f_vs_8v,
    "bootstrap_sharpe_diff": bootstrap_tests,
}

# Lookahead guard
lookahead_ok = {
    "weight_uses_t_minus_1_vix": bool(vix_lag_oos[0] == vix_v[oos_indices[0] - 1]
                                       if oos_indices[0] > 0 else True),
    "sigma_hat_a4f_step0_uses_t_minus_1_info": bool(not np.isnan(sig_a4f[0])),
    "sigma_hat_gjr_step0_uses_t_minus_1_info": bool(not np.isnan(sig_gjr[0])),
    "note": "weight_t constructed from VIX_{t-1} and sigma_hat_{t-1}; returns_t realised after.",
}
results["lookahead_guard"] = lookahead_ok

# Sanity vs BH
sharpe_bh = strat_metrics["BH_TW"]["sharpe"]
sanity = {}
for key in ["A_8VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_8VIX_net", "E_5050_A4f_net"]:
    s = strat_metrics[key]["sharpe"]
    sanity[key] = {
        "sharpe": s,
        "sharpe_over_bh_tw": s / sharpe_bh if sharpe_bh != 0 else np.nan,
        "exceeds_2x": bool(abs(s) > 2.0 * abs(sharpe_bh)) if sharpe_bh != 0 else False,
    }
results["sharpe_sanity_check"] = sanity

with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2,
              default=lambda x: float(x) if hasattr(x, "item") else str(x))
print(f"\n   Saved results -> {RESULTS_PATH}")

# --------------------------------------------------------------
# 11. Charts
# --------------------------------------------------------------
print("\n[5] Generating charts ...")


def _pretty_title(s):
    return s.replace("_", " ")


# 11.1 Sharpe bar chart
bar_keys = ["A_8VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_8VIX_net", "E_5050_A4f_net",
            "BH_TW", "BH_5050_TW_GLD"]
sh_vals = [strat_metrics[k]["sharpe"] for k in bar_keys]

fig, ax = plt.subplots(figsize=(10, 5.5))
colors = ["#1f77b4", "#d62728", "#9467bd", "#2ca02c", "#ff7f0e", "#7f7f7f", "#8c564b"]
bars = ax.bar(range(len(bar_keys)), sh_vals, color=colors)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(range(len(bar_keys)))
ax.set_xticklabels([_pretty_title(k) for k in bar_keys], rotation=20, ha="right", fontsize=9)
ax.set_ylabel("Sharpe (annualised, net of 2 bps)")
ax.set_title(f"K1094 0050.TW Strategy Sharpe  OOS {OOS_START} -> {df.index[-1].date()}")
for i, b in enumerate(bars):
    ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.02,
            f"{sh_vals[i]:.2f}", ha="center", fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1094_sharpe_comparison.png"), dpi=130)
plt.close(fig)

# 11.2 Equity curves
fig, ax = plt.subplots(figsize=(11, 6))
for k, color in zip(["A_8VIX_net", "B_A4f_net", "C_GJR_net",
                     "D_5050_8VIX_net", "E_5050_A4f_net",
                     "BH_TW", "BH_5050_TW_GLD"], colors):
    r = series_lookup[k]
    eq = np.exp(np.cumsum(r))
    ax.plot(oos_dates, eq, label=_pretty_title(k), linewidth=1.1)
ax.set_yscale("log")
ax.set_ylabel("Cumulative equity (log scale, start = 1.0)")
ax.set_title(f"K1094 0050.TW Equity Curves  {OOS_START} -> {df.index[-1].date()}")
ax.grid(alpha=0.3)
ax.legend(fontsize=8, ncols=2)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1094_equity_curves.png"), dpi=130)
plt.close(fig)

# 11.3 Weight dynamics
fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(oos_dates, w_8vix, label="8.63/VIX",  alpha=0.85, linewidth=0.9, color="#1f77b4")
ax.plot(oos_dates, w_a4f,  label="A4f-VT",    alpha=0.85, linewidth=0.9, color="#d62728")
ax.plot(oos_dates, w_gjr,  label="GJR-VT",    alpha=0.85, linewidth=0.9, color="#9467bd")
ax.axhline(1.0, color="black", linewidth=0.5, linestyle="--", alpha=0.6)
ax.axhline(WEIGHT_CAP_VT, color="gray", linewidth=0.5, linestyle=":", alpha=0.6)
ax.set_ylabel("0050.TW weight (leverage)")
ax.set_title(f"K1094 Weight Dynamics  target_sigma={TARGET_SIG:.0%}  caps: 8.63VIX={WEIGHT_CAP_VIX_TW:.1f}, VT={WEIGHT_CAP_VT:.1f}")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1094_weight_dynamics.png"), dpi=130)
plt.close(fig)

# 11.4 Rolling Sharpe
def rolling_sharpe(r, win=252):
    r = np.asarray(r)
    out = np.full(len(r), np.nan)
    for i in range(win, len(r)):
        seg = r[i-win:i]
        sd = np.std(seg, ddof=1)
        out[i] = np.mean(seg) / sd * np.sqrt(TRADING_D) if sd > 0 else np.nan
    return out


fig, ax = plt.subplots(figsize=(11, 5))
for k, color in zip(["A_8VIX_net", "B_A4f_net", "C_GJR_net",
                     "D_5050_8VIX_net", "E_5050_A4f_net"],
                    ["#1f77b4", "#d62728", "#9467bd", "#2ca02c", "#ff7f0e"]):
    rs = rolling_sharpe(series_lookup[k])
    ax.plot(oos_dates, rs, label=_pretty_title(k), linewidth=1.0, color=color)
ax.axhline(0, color="black", linewidth=0.5)
ax.set_ylabel("Rolling 252-day Sharpe")
ax.set_title("K1094 Rolling 1-year Sharpe (0050.TW strategies)")
ax.legend(ncols=2, fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1094_rolling_sharpe.png"), dpi=130)
plt.close(fig)

# 11.5 US vs TW comparison (K1074 vs K1094)
# Load K1074 results if available
k1074_path = os.path.join(PROJECT_ROOT, "experiments", "k1074", "k1074_results.json")
us_vals = None
if os.path.exists(k1074_path):
    try:
        with open(k1074_path) as f:
            k1074 = json.load(f)
        k1074_m = k1074.get("metrics", {})
        us_vals = {
            "VIX-VT":     k1074_m.get("A_12VIX_net", {}).get("sharpe", np.nan),
            "A4f-VT":     k1074_m.get("B_A4f_net",   {}).get("sharpe", np.nan),
            "GJR-VT":     k1074_m.get("C_GJR_net",   {}).get("sharpe", np.nan),
            "50/50+VIX":  k1074_m.get("D_5050_12VIX_net", {}).get("sharpe", np.nan),
            "50/50+A4f":  k1074_m.get("E_5050_A4f_net",   {}).get("sharpe", np.nan),
        }
    except Exception as e:
        print(f"   ⚠ Could not load K1074: {e}")

tw_vals = {
    "VIX-VT":     strat_metrics["A_8VIX_net"]["sharpe"],
    "A4f-VT":     strat_metrics["B_A4f_net"]["sharpe"],
    "GJR-VT":     strat_metrics["C_GJR_net"]["sharpe"],
    "50/50+VIX":  strat_metrics["D_5050_8VIX_net"]["sharpe"],
    "50/50+A4f":  strat_metrics["E_5050_A4f_net"]["sharpe"],
}

fig, ax = plt.subplots(figsize=(10, 5.5))
labels = list(tw_vals.keys())
x = np.arange(len(labels))
width = 0.38
if us_vals is not None:
    ax.bar(x - width/2, [us_vals[k] for k in labels], width,
           color="#1f77b4", label="K1074 SPY (US)")
ax.bar(x + width/2, [tw_vals[k] for k in labels], width,
       color="#d62728", label="K1094 0050.TW")
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=10, fontsize=9)
ax.set_ylabel("Net Sharpe")
ax.set_title("US vs Taiwan: A4f-VT Strategy Replication (K1074 vs K1094)")
ax.legend()
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1094_us_vs_tw.png"), dpi=130)
plt.close(fig)

print("   Charts saved.")

# --------------------------------------------------------------
# 12. Console summary
# --------------------------------------------------------------
print("\n" + "=" * 72)
print(f"{EXPERIMENT_ID} Summary (0050.TW)")
print("=" * 72)
print(f"OOS: {OOS_START} -> {df.index[-1].date()}  n={n_oos}")
print(f"Target sigma = {TARGET_SIG:.0%}  caps: 8VIX={WEIGHT_CAP_VIX_TW:.1f} / VT={WEIGHT_CAP_VT:.1f}   TX = {TX_BPS} bps\n")

hdr = f"{'strategy':<24} {'sharpe':>7} {'cagr':>7} {'mdd':>7} {'calmar':>7} {'sortino':>8} {'mean_w':>7} {'ann_to':>7}"
print(hdr)
print("-" * len(hdr))
for key in ["A_8VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_8VIX_net", "E_5050_A4f_net",
            "BH_TW", "BH_5050_TW_GLD"]:
    m = strat_metrics[key]
    mean_w = m.get("mean_w", np.nan)
    ann_to = m.get("annual_notional", np.nan)
    print(f"{key:<24} {m['sharpe']:>7.3f} {m['cagr']:>7.2%} "
          f"{m['mdd']:>7.2%} "
          f"{(m['calmar'] if not np.isnan(m['calmar']) else 0):>7.2f} "
          f"{(m['sortino'] if not np.isnan(m['sortino']) else 0):>8.2f} "
          f"{mean_w:>7.2f} {ann_to:>7.1f}")

print("\nBootstrap Sharpe-diff tests (95% CI, block=22, 1000 reps):")
for k, v in bootstrap_tests.items():
    print(f"  {k:<45}  diff={v['mean']:+.3f}  "
          f"CI=[{v['ci95_lo']:+.3f}, {v['ci95_hi']:+.3f}]  p={v['p_two_sided']:.3f}")

print(f"\nHit rate A4f-VT vs 8.63/VIX (monthly, net): {hit_rate_a4f_vs_8v:.1%}")

print(f"\nTotal elapsed: {time.time() - START_TIME:.0f}s")
print("=" * 72)
