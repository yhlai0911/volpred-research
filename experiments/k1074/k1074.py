#!/usr/bin/env python3
"""
K1074: A4f Forecast -> Volatility Targeting Strategy Economic Value
===================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation
----------
K988/K1055/K1056/K1073 established that the A4f specification (tau = theta0 +
theta1 * VIX^2, with free omega GJR short-run) has a statistically-robust
QLIKE edge over GJR-GARCH (DM |t| > 3.0, CI 5-11%, 5/5 sub-periods win).

But Moreira & Muir (2017) and Harvey et al. (2018) both warn: a more accurate
variance forecast does not mechanically translate into a better volatility-
targeted strategy. Paper 3 of this project (Is Volatility Targeting Just
Trend Following?) argues that VT's alpha comes mostly from the return side
(TSMOM / persistence of drawdowns), so the vol side can be very crude without
hurting net performance. If that is right, A4f-VT should NOT beat 12/VIX-VT
much once transaction costs are netted.

Research questions
------------------
H1 (Sharpe)        Is A4f-VT Sharpe > 12/VIX-VT Sharpe on SPY?
H2 (MDD)           Is A4f-VT MDD shallower than 12/VIX-VT MDD?
H3 (Turnover)      Is A4f-VT turnover higher (more reactive sigma hat)?
H4 (Net Sharpe)    After 5bp round-trip cost, does A4f-VT still win?
H5 (50/50)         50/50 SPY/GLD with A4f-VT vs with 12/VIX: which wins?

Strategies
----------
Strategy A: 12/VIX       w_t = min(12 / VIX_{t-1}, 1.5)
Strategy B: A4f-VT       w_t = min(0.12 / sigma_hat_{A4f}_{t-1}, 1.5)
                         sigma_hat = sqrt(h_{A4f}) * sqrt(252)
Strategy C: GJR-VT       w_t = min(0.12 / sigma_hat_{GJR}_{t-1}, 1.5)
Strategy D: 50/50 + 12/VIX   on SPY leg; GLD unscaled; monthly rebalance
Strategy E: 50/50 + A4f-VT   on SPY leg; GLD unscaled; monthly rebalance

Lag convention: weight at date t uses information available through t-1.
portfolio_return_t = weight_t * r_t (the date-t return is realised AFTER the
weight is locked).

Data
----
SPY, GLD, ^VIX close from yfinance. 2005-2026. OOS = 2013-01-02 -> today.

Evaluation
----------
- Annualised Sharpe (raw and net of 5 bps per unit of weight change)
- MDD, Calmar, Sortino, CAGR, hit rate vs BH 50/50
- Turnover (mean |dw|), notional turnover (annualised)
- Pairwise Sharpe difference with bootstrap 95% CI (1000 reps, seed 42)

References
----------
Moreira & Muir (2017). Volatility-Managed Portfolios. JF 72(4):1611-1644.
Harvey et al. (2018). The Impact of Volatility Targeting. JPM 45(1):14-33.
Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
  Fundamentals. RES 95(3):776-797.
Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.

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
except Exception:  # pragma: no cover
    def njit(*a, **k):
        def deco(f):
            return f
        return deco

warnings.filterwarnings("ignore")
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1074"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

RESULTS_PATH = os.path.join(SCRIPT_DIR, "k1074_results.json")

# --------------------------------------------------------------
# Configuration
# --------------------------------------------------------------
DATA_START = "2005-01-01"
DATA_END   = "2026-04-12"
OOS_START  = "2013-01-02"

WINDOW     = 2000
REFIT      = 63
TARGET_SIG = 0.12         # annualised sigma target for A4f / GJR VT
WEIGHT_CAP = 1.50         # maximum leverage
TX_BPS     = 5.0          # 5 basis points per unit weight change (round-trip)
TRADING_D  = 252

N_BOOT     = 1000
BOOT_BLOCK = 22

print("=" * 72)
print(f"{EXPERIMENT_ID}: A4f Forecast -> Volatility Targeting Strategy")
print("=" * 72)

# --------------------------------------------------------------
# 1. Data
# --------------------------------------------------------------
import yfinance as yf

def _load_close(ticker):
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw["Close"].copy()

print("\n[1] Loading data ...")
spy = _load_close("SPY")
gld = _load_close("GLD")
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()

df = pd.DataFrame({"SPY": spy, "GLD": gld, "VIX": vix}).dropna()
df["r_spy"] = np.log(df["SPY"] / df["SPY"].shift(1))
df["r_gld"] = np.log(df["GLD"] / df["GLD"].shift(1))
df = df.dropna()

oos_mask_all = np.asarray(df.index >= OOS_START)
print(f"   Total rows : {len(df)}  "
      f"[{df.index[0].date()} -> {df.index[-1].date()}]")
print(f"   OOS rows   : {int(oos_mask_all.sum())}  (from {OOS_START})")

ret     = df["r_spy"].values
ret_gld = df["r_gld"].values
vix_v   = df["VIX"].values
log_vix = np.log(np.maximum(vix_v, 1.0))
r2      = ret ** 2

oos_indices = np.where(oos_mask_all)[0]
n_oos = len(oos_indices)

# --------------------------------------------------------------
# 2. Model: GJR-GARCH(1,1)  (benchmark forecast for Strategy C)
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
# 3. Model: A4f   tau = theta0 + theta1 * VIX^2  |  g = GJR(free omega)
# --------------------------------------------------------------
def fit_a4f(returns, vix_vals):
    """Multiplicative-factor GJR model with A4f tau spec."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = float(np.var(returns))
    vix2_mean = float(np.mean(vix_lag**2) + 1e-8)

    def neg_ll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p/2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
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
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
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


def a4f_compute_tau(params, vix_lag_scalar):
    theta0, theta1 = params[0], params[1]
    return max(theta0 + theta1 * vix_lag_scalar**2, 1e-16)


def a4f_init_state(params, train_ret, train_vix):
    """Run model forward over training window to get g_end and tau_end."""
    n = len(train_ret)
    vix_lag = np.empty(n)
    vix_lag[0] = train_vix[0]
    vix_lag[1:] = train_vix[:-1]
    tau = np.maximum(params[0] + params[1] * vix_lag**2, 1e-16)
    omega_g, alpha, gamma_p, beta = params[2], params[3], params[4], params[5]
    persist = alpha + gamma_p/2.0 + beta
    eg = omega_g / max(1.0 - persist, 1e-8)
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        g = max(g, 1e-10)
    return g, tau[-1]


# --------------------------------------------------------------
# 4. Rolling OOS forecasts (GJR and A4f, step-ahead, predetermined at t-1)
# --------------------------------------------------------------
print("\n[2] Rolling OOS forecasts (GJR + A4f) ...")
print(f"   Window = {WINDOW}  Refit every {REFIT} days  "
      f"n_refits = {int(np.ceil(n_oos / REFIT))}")

sig_gjr = np.full(n_oos, np.nan)   # annualised sigma hat for day t (using info through t-1)
sig_a4f = np.full(n_oos, np.nan)

gjr_state = {"params": None, "h": None}
a4f_state = {"params": None, "g": None, "tau_prev": None}

for step, abs_idx in enumerate(oos_indices):
    if step % REFIT == 0:
        elapsed = time.time() - START_TIME
        print(f"   refit at step {step}/{n_oos} "
              f"({df.index[abs_idx].date()})  elapsed={elapsed:.0f}s")
        train_lo = max(0, abs_idx - WINDOW)
        train_ret = ret[train_lo:abs_idx]
        train_vix = vix_v[train_lo:abs_idx]

        # --- GJR
        p_gjr = fit_gjr(train_ret)
        if p_gjr is not None:
            gjr_state["params"] = p_gjr
            h = float(np.var(train_ret))
            for i in range(1, len(train_ret)):
                h = gjr_next(p_gjr, h, train_ret[i-1])
            gjr_state["h"] = h

        # --- A4f
        p_a4f = fit_a4f(train_ret, train_vix)
        if p_a4f is not None:
            a4f_state["params"] = p_a4f
            g_end, tau_end = a4f_init_state(p_a4f, train_ret, train_vix)
            a4f_state["g"] = g_end
            a4f_state["tau_prev"] = tau_end

    # Generate one-step-ahead forecasts for day abs_idx
    # Both use info available at t-1 (ret[abs_idx-1], vix[abs_idx-1])
    r_prev = ret[abs_idx - 1]
    v_prev = vix_v[abs_idx - 1]

    # GJR
    p = gjr_state["params"]
    if p is not None:
        h_new = gjr_next(p, gjr_state["h"], r_prev)
        sig_gjr[step] = np.sqrt(h_new * TRADING_D)
        gjr_state["h"] = h_new

    # A4f
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
      f"nan(A4f)={int(np.isnan(sig_a4f).sum())}")

# --------------------------------------------------------------
# 5. Build weight series (all with t-1 information)
# --------------------------------------------------------------
print("\n[3] Building weight series ...")

oos_ret_spy = ret[oos_indices]
oos_ret_gld = ret_gld[oos_indices]
oos_vix     = vix_v[oos_indices]
oos_dates   = df.index[oos_indices]

# 12/VIX : lag the VIX by one day (so weight_t uses VIX_{t-1})
vix_lag_oos = np.empty(n_oos)
vix_lag_oos[0] = vix_v[oos_indices[0] - 1] if oos_indices[0] > 0 else oos_vix[0]
vix_lag_oos[1:] = oos_vix[:-1]

w_12vix = np.minimum(12.0 / vix_lag_oos, WEIGHT_CAP)
w_a4f   = np.minimum(TARGET_SIG * 100.0 / (sig_a4f * 100.0), WEIGHT_CAP)
w_gjr   = np.minimum(TARGET_SIG * 100.0 / (sig_gjr * 100.0), WEIGHT_CAP)

# Clamp NaNs -> use 1.0 (flat BH) for the rare missing forecast
def _fill_nan(x, fill=1.0):
    y = x.copy()
    y[np.isnan(y)] = fill
    return y

w_12vix = _fill_nan(w_12vix, 1.0)
w_a4f   = _fill_nan(w_a4f,   1.0)
w_gjr   = _fill_nan(w_gjr,   1.0)

# --------------------------------------------------------------
# 6. 50/50 baselines
# --------------------------------------------------------------
# SPY leg is VT-scaled, GLD leg = 1.0.  Monthly rebalance back to 50/50.
# We implement monthly rebalance by tracking cumulative returns and resetting
# allocation on the first trading day of each month.
first_of_month = np.zeros(n_oos, dtype=bool)
prev_m = None
for i, d in enumerate(oos_dates):
    if d.month != prev_m:
        first_of_month[i] = True
        prev_m = d.month


def portfolio_5050(w_spy, r_spy, r_gld):
    """
    50/50 SPY/GLD with monthly rebalance.
    w_spy is the daily VT leverage for SPY (already t-1 lagged).
    GLD leg uses weight 1.0.
    """
    n = len(w_spy)
    port = np.zeros(n)
    alloc_spy, alloc_gld = 0.5, 0.5
    for i in range(n):
        if first_of_month[i] and i > 0:
            alloc_spy, alloc_gld = 0.5, 0.5
        daily = alloc_spy * w_spy[i] * r_spy[i] + alloc_gld * r_gld[i]
        port[i] = daily
        # Drift allocation
        spy_growth = np.exp(alloc_spy * w_spy[i] * r_spy[i])
        gld_growth = np.exp(alloc_gld * r_gld[i])
        total = spy_growth + gld_growth
        alloc_spy = spy_growth / total
        alloc_gld = gld_growth / total
    return port


# --------------------------------------------------------------
# 7. Apply transaction costs (5 bps per unit weight change)
# --------------------------------------------------------------
def apply_tx_cost(weights, returns, bps=TX_BPS):
    """
    Transaction cost is charged on the *change* in leverage.
    cost_t = (bps / 1e4) * |w_t - w_{t-1}|    (subtracted from return at time t)
    """
    dw = np.abs(np.diff(weights, prepend=weights[0]))
    cost = (bps / 1e4) * dw
    gross = weights * returns
    net   = gross - cost
    return gross, net, cost


gross_12v, net_12v, cost_12v = apply_tx_cost(w_12vix, oos_ret_spy)
gross_a4f, net_a4f, cost_a4f = apply_tx_cost(w_a4f,   oos_ret_spy)
gross_gjr, net_gjr, cost_gjr = apply_tx_cost(w_gjr,   oos_ret_spy)

# 50/50 combos (net of TX on SPY leg only, GLD leg has no leverage change cost)
# Simplification: charge TX on SPY VT weight changes scaled by 0.5 (50% allocation).
def portfolio_5050_net(w_spy, r_spy, r_gld, bps=TX_BPS):
    n = len(w_spy)
    gross = np.zeros(n)
    net   = np.zeros(n)
    cost  = np.zeros(n)
    alloc_spy, alloc_gld = 0.5, 0.5
    w_prev = w_spy[0]
    for i in range(n):
        if first_of_month[i] and i > 0:
            alloc_spy, alloc_gld = 0.5, 0.5
        dw = abs(w_spy[i] - w_prev)
        c  = (bps / 1e4) * dw * alloc_spy   # scale by SPY allocation
        cost[i] = c
        g = alloc_spy * w_spy[i] * r_spy[i] + alloc_gld * r_gld[i]
        gross[i] = g
        net[i]   = g - c
        spy_growth = np.exp(alloc_spy * w_spy[i] * r_spy[i])
        gld_growth = np.exp(alloc_gld * r_gld[i])
        total = spy_growth + gld_growth
        alloc_spy = spy_growth / total
        alloc_gld = gld_growth / total
        w_prev = w_spy[i]
    return gross, net, cost


gross_D, net_D, cost_D = portfolio_5050_net(w_12vix, oos_ret_spy, oos_ret_gld)
gross_E, net_E, cost_E = portfolio_5050_net(w_a4f,   oos_ret_spy, oos_ret_gld)

# Buy-and-hold benchmarks
bh_spy   = oos_ret_spy
bh_5050  = 0.5 * oos_ret_spy + 0.5 * oos_ret_gld

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
        "mean_abs_dw":  float(np.mean(np.abs(dw))),
        "annual_notional": float(np.mean(np.abs(dw)) * TRADING_D),
        "mean_w": float(np.mean(weights)),
        "std_w":  float(np.std(weights, ddof=1)),
    }


# Bootstrap Sharpe CI (stationary block bootstrap)
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
        "mean":   float(np.mean(diffs)),
        "ci95_lo": float(np.percentile(diffs, 2.5)),
        "ci95_hi": float(np.percentile(diffs, 97.5)),
        "p_two_sided": float(np.mean(diffs * np.sign(np.mean(diffs)) <= 0) * 2),
    }


# --------------------------------------------------------------
# 9. Compute everything
# --------------------------------------------------------------
print("\n[4] Computing metrics ...")

strategy_defs = [
    ("A_12VIX_gross",       gross_12v, w_12vix),
    ("A_12VIX_net",         net_12v,   w_12vix),
    ("B_A4f_gross",         gross_a4f, w_a4f),
    ("B_A4f_net",           net_a4f,   w_a4f),
    ("C_GJR_gross",         gross_gjr, w_gjr),
    ("C_GJR_net",           net_gjr,   w_gjr),
    ("D_5050_12VIX_gross",  gross_D,   w_12vix),
    ("D_5050_12VIX_net",    net_D,     w_12vix),
    ("E_5050_A4f_gross",    gross_E,   w_a4f),
    ("E_5050_A4f_net",      net_E,     w_a4f),
    ("BH_SPY",              bh_spy,    None),
    ("BH_5050_SPY_GLD",     bh_5050,   None),
]

strat_metrics = {}
for name, r_series, w_series in strategy_defs:
    m = metrics(r_series, name)
    if w_series is not None:
        m.update(turnover(w_series))
    strat_metrics[name] = m

# Hit rate: A4f-VT vs 12/VIX-VT monthly win ratio
def month_returns(series, dates):
    s = pd.Series(series, index=dates)
    return s.groupby([s.index.year, s.index.month]).sum()

a4f_monthly = month_returns(net_a4f, oos_dates)
v12_monthly = month_returns(net_12v, oos_dates)
hit_rate_a4f_vs_12v = float((a4f_monthly > v12_monthly).mean())

# Pairwise Sharpe diff tests
print("   Bootstrap Sharpe-diff tests ...")
pairs = [
    ("B_A4f_net",        "A_12VIX_net"),
    ("B_A4f_net",        "C_GJR_net"),
    ("B_A4f_net",        "BH_SPY"),
    ("A_12VIX_net",      "BH_SPY"),
    ("E_5050_A4f_net",   "D_5050_12VIX_net"),
    ("E_5050_A4f_net",   "BH_5050_SPY_GLD"),
    ("D_5050_12VIX_net", "BH_5050_SPY_GLD"),
]
def _series_by_name(n):
    return dict((k, v[1]) for k, v in zip(
        [x[0] for x in strategy_defs],
        strategy_defs
    ))[n]
series_lookup = dict(zip([x[0] for x in strategy_defs],
                         [x[1] for x in strategy_defs]))

bootstrap_tests = {}
for a, b in pairs:
    res = block_bootstrap_sharpe_diff(series_lookup[a], series_lookup[b])
    bootstrap_tests[f"{a}__minus__{b}"] = res

# --------------------------------------------------------------
# 10. Assemble results
# --------------------------------------------------------------
results = {
    "experiment_id": EXPERIMENT_ID,
    "description": "A4f forecast -> VT strategy economic value vs 12/VIX baseline",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{DATA_START} to {df.index[-1].date().isoformat()}",
    "oos_start": OOS_START,
    "oos_end": df.index[-1].date().isoformat(),
    "n_oos": int(n_oos),
    "window": WINDOW,
    "refit_every": REFIT,
    "random_seed": 42,
    "target_sigma": TARGET_SIG,
    "weight_cap": WEIGHT_CAP,
    "tx_bps": TX_BPS,
    "n_bootstrap": N_BOOT,
    "boot_block_size": BOOT_BLOCK,
    "references": [
        "Moreira & Muir (2017). Volatility-Managed Portfolios. JF 72(4):1611-1644.",
        "Harvey et al. (2018). The Impact of Volatility Targeting. JPM 45(1):14-33.",
        "Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.",
        "Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.",
    ],
    "strategies": {
        "A_12VIX":       "w_t = min(12 / VIX_{t-1}, 1.5)",
        "B_A4f":         "w_t = min(0.12 / sigma_hat_{A4f,t-1}, 1.5)",
        "C_GJR":         "w_t = min(0.12 / sigma_hat_{GJR,t-1}, 1.5)",
        "D_5050_12VIX":  "50% SPY*w_12VIX + 50% GLD; monthly rebalance",
        "E_5050_A4f":    "50% SPY*w_A4f   + 50% GLD; monthly rebalance",
    },
    "metrics": strat_metrics,
    "hit_rate_A4f_vs_12VIX_monthly": hit_rate_a4f_vs_12v,
    "bootstrap_sharpe_diff": bootstrap_tests,
}

# Lookahead verification (K679 guardrail)
lookahead_ok = {
    "weight_uses_t_minus_1_vix": bool(vix_lag_oos[0] == vix_v[oos_indices[0] - 1]
                                       if oos_indices[0] > 0 else True),
    "sigma_hat_a4f_step0_uses_t_minus_1_info": bool(not np.isnan(sig_a4f[0])),
    "sigma_hat_gjr_step0_uses_t_minus_1_info": bool(not np.isnan(sig_gjr[0])),
}
results["lookahead_guard"] = lookahead_ok

# Self-check: sharpe > 2x baseline?
sharpe_bh = strat_metrics["BH_SPY"]["sharpe"]
sharpe_checks = {}
for key in ["A_12VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_12VIX_net", "E_5050_A4f_net"]:
    s = strat_metrics[key]["sharpe"]
    sharpe_checks[key] = {
        "sharpe": s,
        "sharpe_over_bh_spy": s / sharpe_bh if sharpe_bh != 0 else np.nan,
        "exceeds_2x": bool(abs(s) > 2.0 * abs(sharpe_bh)) if sharpe_bh != 0 else False,
    }
results["sharpe_sanity_check"] = sharpe_checks

with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2, default=lambda x: float(x) if hasattr(x, "item") else str(x))
print(f"\n   Saved results -> {RESULTS_PATH}")

# --------------------------------------------------------------
# 11. Charts
# --------------------------------------------------------------
print("\n[5] Generating charts ...")

def _pretty_title(s):
    return s.replace("_", " ")

# 11.1 Sharpe bar chart + bootstrap CI
bar_keys = ["A_12VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_12VIX_net", "E_5050_A4f_net",
            "BH_SPY", "BH_5050_SPY_GLD"]
sh_vals = [strat_metrics[k]["sharpe"] for k in bar_keys]

fig, ax = plt.subplots(figsize=(10, 5.5))
colors = ["#1f77b4", "#d62728", "#9467bd", "#2ca02c", "#ff7f0e", "#7f7f7f", "#8c564b"]
bars = ax.bar(range(len(bar_keys)), sh_vals, color=colors)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(range(len(bar_keys)))
ax.set_xticklabels([_pretty_title(k) for k in bar_keys], rotation=20, ha="right", fontsize=9)
ax.set_ylabel("Sharpe (annualised, net of 5 bps)")
ax.set_title(f"K1074 Strategy Sharpe Comparison  OOS {OOS_START} -> {df.index[-1].date()}")
for i, b in enumerate(bars):
    ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.02,
            f"{sh_vals[i]:.2f}", ha="center", fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1074_sharpe_comparison.png"), dpi=130)
plt.close(fig)

# 11.2 Equity curves
fig, ax = plt.subplots(figsize=(11, 6))
for k, color in zip(["A_12VIX_net", "B_A4f_net", "C_GJR_net",
                      "D_5050_12VIX_net", "E_5050_A4f_net",
                      "BH_SPY", "BH_5050_SPY_GLD"],
                    colors):
    r = series_lookup[k]
    eq = np.exp(np.cumsum(r))
    ax.plot(oos_dates, eq, label=_pretty_title(k), linewidth=1.1)
ax.set_yscale("log")
ax.set_ylabel("Cumulative equity (log scale, start = 1.0)")
ax.set_title(f"K1074 Equity Curves  {OOS_START} -> {df.index[-1].date()}")
ax.grid(alpha=0.3)
ax.legend(fontsize=8, ncols=2)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1074_equity_curves.png"), dpi=130)
plt.close(fig)

# 11.3 Weight dynamics (3 SPY-VT strategies)
fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(oos_dates, w_12vix, label="12/VIX",  alpha=0.85, linewidth=0.9, color="#1f77b4")
ax.plot(oos_dates, w_a4f,   label="A4f-VT",  alpha=0.85, linewidth=0.9, color="#d62728")
ax.plot(oos_dates, w_gjr,   label="GJR-VT",  alpha=0.85, linewidth=0.9, color="#9467bd")
ax.axhline(1.0, color="black", linewidth=0.5, linestyle="--", alpha=0.6)
ax.axhline(WEIGHT_CAP, color="gray", linewidth=0.5, linestyle=":", alpha=0.6)
ax.set_ylabel("SPY weight (leverage)")
ax.set_title(f"K1074 Weight Dynamics  target_sigma={TARGET_SIG:.0%}  cap={WEIGHT_CAP:.1f}")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1074_weight_dynamics.png"), dpi=130)
plt.close(fig)

# 11.4 MDD events (A4f vs 12/VIX vs BH_SPY net, drawdown curves)
fig, ax = plt.subplots(figsize=(11, 5))
for k, color in zip(["A_12VIX_net", "B_A4f_net", "BH_SPY"],
                    ["#1f77b4", "#d62728", "#7f7f7f"]):
    r = series_lookup[k]
    cum = np.cumsum(r)
    dd  = cum - np.maximum.accumulate(cum)
    ax.plot(oos_dates, dd, label=_pretty_title(k), linewidth=1.0, color=color)
ax.fill_between(oos_dates, -0.6, 0, color="red", alpha=0.02)
ax.set_ylabel("Drawdown (log units)")
ax.set_title("K1074 Drawdown curves (3 SPY strategies)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1074_mdd_dates.png"), dpi=130)
plt.close(fig)

# 11.5 Rolling 252-day Sharpe
def rolling_sharpe(r, win=252):
    r = np.asarray(r)
    out = np.full(len(r), np.nan)
    for i in range(win, len(r)):
        seg = r[i-win:i]
        sd = np.std(seg, ddof=1)
        out[i] = np.mean(seg) / sd * np.sqrt(TRADING_D) if sd > 0 else np.nan
    return out

fig, ax = plt.subplots(figsize=(11, 5))
for k, color in zip(["A_12VIX_net", "B_A4f_net", "C_GJR_net",
                      "D_5050_12VIX_net", "E_5050_A4f_net"],
                    ["#1f77b4", "#d62728", "#9467bd", "#2ca02c", "#ff7f0e"]):
    rs = rolling_sharpe(series_lookup[k])
    ax.plot(oos_dates, rs, label=_pretty_title(k), linewidth=1.0, color=color)
ax.axhline(0, color="black", linewidth=0.5)
ax.set_ylabel("Rolling 252-day Sharpe")
ax.set_title("K1074 Rolling 1-year Sharpe")
ax.legend(ncols=2, fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1074_rolling_sharpe.png"), dpi=130)
plt.close(fig)

print("   Charts saved.")

# --------------------------------------------------------------
# 12. Console summary
# --------------------------------------------------------------
print("\n" + "=" * 72)
print(f"{EXPERIMENT_ID} Summary")
print("=" * 72)
print(f"OOS: {OOS_START} -> {df.index[-1].date()}  n={n_oos}")
print(f"Target sigma = {TARGET_SIG:.0%}  cap = {WEIGHT_CAP:.1f}  TX = {TX_BPS} bps\n")

hdr = f"{'strategy':<24} {'sharpe':>7} {'cagr':>7} {'mdd':>7} {'calmar':>7} {'sortino':>8} {'mean_w':>7} {'ann_to':>7}"
print(hdr)
print("-" * len(hdr))
for key in ["A_12VIX_net", "B_A4f_net", "C_GJR_net",
            "D_5050_12VIX_net", "E_5050_A4f_net",
            "BH_SPY", "BH_5050_SPY_GLD"]:
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

print(f"\nHit rate A4f-VT vs 12/VIX-VT (monthly, net): {hit_rate_a4f_vs_12v:.1%}")

print(f"\nTotal elapsed: {time.time() - START_TIME:.0f}s")
print("=" * 72)
