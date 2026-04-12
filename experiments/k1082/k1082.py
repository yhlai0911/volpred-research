#!/usr/bin/env python3
"""
K1082: Single-Country EM ETFs (EWT / EWZ / FXI) — USD Wrapper Diagnostic
========================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation
----------
K1075-K1081 established the Paper 9 cross-asset map:
    K1075 SPY       : DM t = +7.92, Harvey-PASS (theta1 span < 1)
    K1078 QQQ       : DM t = +5.99, Harvey-PASS (theta1 span = 1.91)
    K1080 IWM       : DM t = +4.80, Harvey-PASS (theta1 span = 3.54)
    K1081 EEM       : DM t = +5.25, Harvey-PASS (EM basket, USD-denominated)
    K1077 0050.TW   : DM t = -0.49, Harvey-FAIL (Taiwan 50 equivalent, TWD)

Open puzzle: 0050.TW failed. Is it because
    (H_tw_uniq)     Taiwan market structure is unique
                    (local retail flow, concentrated TSMC, political risk), or
    (H_currency)    Currency denomination matters
                    (TWD-denominated fail, USD-denominated pass)?

K1082 is the discriminator. EWT tracks the MSCI Taiwan index — essentially
the same underlying stocks as 0050.TW (top weight TSMC) — but is priced
in USD on NYSE. If EWT A4f PASSES while 0050.TW FAILS, currency wrapper
is the necessary condition. If EWT also FAILS, Taiwan market structure
is indeed unique.

Add EWZ (Brazil) and FXI (China large-cap) as single-country USD EM
benchmarks, to locate EWT within the EM ETF cross-section.

Design (strict parity with K1075 / K1078 / K1080 / K1081)
---------------------------------------------------------
    - Three non-overlapping OOS windows:
        Early    2007-01-01 ~ 2012-12-31 (GFC + Euro crisis)
        Middle   2013-01-01 ~ 2018-12-31 (China 2015, Trump tariff)
        Late     2019-01-01 ~ 2026-04-11 (COVID + rate hike + China)
    - Rolling GARCH with WINDOW=2000, REFIT_EVERY=63
    - GJR baseline vs A4f (tau_t = theta0 + theta1 * VIX_{t-1}^2,
      g_t = GJR on u = r/sqrt(tau), free omega_g). Identical to K1081.
    - Evaluation: QLIKE, DM HAC-NW (Harvey |t|>3), Spearman, bootstrap CI.
    - Crisis sub-periods: GFC, China 2015, COVID, Bear 2022.
    - VIX buckets: Low/Normal/High/Extreme/Crisis (lagged VIX).

Pre-OOS training adequacy
    FXI IPO 2004-10-08 -> at 2007-01-01 only ~562 training obs
    (vs WINDOW=2000 requested). Same max(0, abs_idx - WINDOW) policy
    as K1081, so the first refit uses all available history. Flag if
    this weakens the Early_Crisis window for FXI.

Hypotheses
----------
    H1 (per ETF)    : Full OOS A4f > GJR with |DM t| > 3 (Harvey-PASS)
    H2              : EWT vs 0050.TW is a clean currency test —
                      same underlying stocks, different wrapper.
                      Predict: EWT PASSES -> USD wrapper is necessary.
    H3              : All three single-country ETFs pass -> A4f effect
                      is about currency / listing, not region.
    H4              : theta1 stability (orders of magnitude span,
                      P10-P90 robust) is lower for USD EWT than 0050.TW.
    H5              : No A4f breakdown at VIX > 40 across ETFs.

Data
----
    EWT  : yfinance 2000-06-20 -> 2026-04-12   (Taiwan, USD)
    EWZ  : yfinance 2000-07-14 -> 2026-04-12   (Brazil, USD)
    FXI  : yfinance 2004-10-05 -> 2026-04-12   (China large-cap, USD)
    ^VIX : yfinance (shared, daily close)

Key diagnostic table (Paper 9)
------------------------------
    Asset    Market      Currency    Source   DM t    Harvey
    SPY      US          USD         K1075    +7.92   PASS
    QQQ      US tech     USD         K1078    +5.99   PASS
    EEM      EM basket   USD         K1081    +5.25   PASS
    IWM      US small    USD         K1080    +4.80   PASS
    EWT      Taiwan      USD         K1082    ?       ?
    EWZ      Brazil      USD         K1082    ?       ?
    FXI      China       USD         K1082    ?       ?
    0050.TW  Taiwan      TWD         K1077    -0.49   FAIL

Paper 9 discrimination matrix (EWT outcome)
-------------------------------------------
    EWT PASS + 0050.TW FAIL  -> USD wrapper = necessary condition
                                (strongest claim; same stocks,
                                 different wrapper -> different result)
    EWT FAIL + 0050.TW FAIL  -> Taiwan market structure really different
    EWT PASS + EWZ/FXI PASS  -> all USD EM ETFs work
    All NULL                 -> A4f bounded to US-native ETFs

References
----------
    Engle, Ghysels & Sohn (2013) GARCH-MIDAS. RES 95(3): 776-797.
    Patton (2011) Volatility forecast comparison. J Econometrics 160.
    Harvey, Leybourne & Newbold (2016). Multiple-testing t-threshold.
    Hansen & Lunde (2005). A forecast comparison of volatility models.

Upstream experiments
--------------------
    K988  SPY A4f proof-of-concept
    K1075 SPY extended 2007-2026 — PASS
    K1077 0050.TW extended — FAIL (the puzzle)
    K1078 QQQ extended — PASS
    K1080 IWM extended — PASS
    K1081 EEM extended — PASS (non-US but USD)

Author: VolPred Research System
Date:   2026-04-12
Experiment ID: K1082
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)  # required by preamble for all randomness

START_TIME = time.time()
EXPERIMENT_ID = "K1082"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1082_results.json')

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
DATA_END   = '2026-04-12'
WINDOW     = 2000
REFIT_EVERY = 63

ETFS = [
    # (ticker, IPO start, display_name, composition, currency)
    ('EWT', '2000-06-20', 'iShares MSCI Taiwan ETF',  'Taiwan (proxy for 0050.TW)', 'USD'),
    ('EWZ', '2000-07-14', 'iShares MSCI Brazil ETF',  'Brazil',                      'USD'),
    ('FXI', '2004-10-05', 'iShares China Large-Cap',  'China H-shares',              'USD'),
]

OOS_WINDOWS = [
    ('Early_Crisis',    '2007-01-01', '2012-12-31'),
    ('Middle_Recovery', '2013-01-01', '2018-12-31'),
    ('Late_COVID',      '2019-01-01', '2026-04-11'),
]

CRISIS_PERIODS = [
    ('GFC',         '2008-01-01', '2009-12-31'),
    ('China_2015',  '2015-06-01', '2016-02-29'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Bear_2022',   '2022-01-01', '2022-12-31'),
]

VIX_BUCKETS = [
    ('Low',     0,  15),
    ('Normal', 15, 25),
    ('High',   25, 40),
    ('Extreme',40, 60),
    ('Crisis', 60, 200),
]

# Reference result paths for the 8-asset final comparison
K1075_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1075', 'k1075_results.json'))
K1077_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1077', 'k1077_results.json'))
K1078_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1078', 'k1078_results.json'))
K1080_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1080', 'k1080_results.json'))
K1081_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1081', 'k1081_results.json'))

print("=" * 72)
print(f"{EXPERIMENT_ID}: Single-Country EM ETFs (EWT / EWZ / FXI) — USD Wrapper Diagnostic")
print("  3 ETFs x (3 OOS windows + 4 crisis sub-periods + 5 VIX buckets)")
print("  Key test: EWT (Taiwan stocks, USD) vs 0050.TW (Taiwan stocks, TWD)")
print("=" * 72)


# ==================================================================
# MODEL IMPLEMENTATIONS (identical to K1081)
# ==================================================================
@njit(cache=True)
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) negative log-likelihood."""
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
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    converged = False
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vol_vals):
    """
    A4f specification (K988 winner):
      tau_t  = max(theta0 + theta1 * VIX_{t-1}^2, eps)
      u_{t-1}= r_{t-1} / sqrt(tau_t)
      g_t    = omega_g + alpha*u^2 + gamma*u^2*I(u<0) + beta*g_{t-1}
      sig2_t = tau_t * g_t
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    vol_lag = np.empty(n)
    vol_lag[0] = vol_vals[0]
    vol_lag[1:] = vol_vals[:-1]
    vol_lag_sq = vol_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vol_lag_sq, 1e-16)

        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                              + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vol2_mean = np.mean(vol_lag_sq) + 1e-8
    starts = [
        [var0 * 0.1,  var0 / vol2_mean,       0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vol2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vol2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),    # theta0
        (1e-10, 1e-2),    # theta1
        (1e-6, 1.0),      # omega_g
        (1e-4, 0.3),      # alpha
        (1e-4, 0.3),      # gamma
        (0.5, 0.999),     # beta
    ]

    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def qlike_loss(fc, r2_vals):
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array):
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        if not blocks:
            return (np.nan, np.nan)
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


# ==================================================================
# DATA LOADING (shared VIX)
# ==================================================================
print("\n[1] Loading ^VIX (shared exogenous)...")
import yfinance as yf

vix_raw = yf.download('^VIX', start='2000-06-01', end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_master = vix_raw['Close'].copy()
print(f"  VIX: {vix_master.index[0].strftime('%Y-%m-%d')} to "
      f"{vix_master.index[-1].strftime('%Y-%m-%d')}, n={len(vix_master)}")


def run_one_etf(ticker, ipo_start, display_name, composition, currency):
    """Execute the full A4f pipeline for a single ETF."""
    print("\n" + "=" * 72)
    print(f"[ETF] {ticker}: {display_name}  ({composition}, priced in {currency})")
    print("=" * 72)

    raw = yf.download(ticker, start=ipo_start, end=DATA_END,
                      progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    prices = raw['Adj Close'].copy() if 'Adj Close' in raw.columns else raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret,
                       'VIX': vix_master}).dropna()
    n_total = len(df)
    print(f"  Joined data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

    ret = df['log_ret'].values
    vix = df['VIX'].values
    r2  = ret ** 2
    dates = df.index

    # Diagnostics
    print(f"  Full-sample diagnostics:")
    print(f"    Return mean (ann): {np.mean(ret)*252:.4f}")
    print(f"    Return std  (ann): {np.std(ret)*np.sqrt(252):.4f}")
    print(f"    Return skew:       {stats.skew(ret):.3f}")
    print(f"    Return kurt:       {stats.kurtosis(ret):.3f}")
    print(f"    VIX mean: {np.mean(vix):.2f}, max: {np.max(vix):.2f} on "
          f"{dates[np.argmax(vix)].strftime('%Y-%m-%d')}")

    # OOS mask per window
    oos_full_mask = np.zeros(n_total, dtype=bool)
    window_tags = np.empty(n_total, dtype=object)
    for name, start, end in OOS_WINDOWS:
        m = (dates >= start) & (dates <= end)
        oos_full_mask |= m
        for idx in np.where(m)[0]:
            window_tags[idx] = name

    oos_indices = np.where(oos_full_mask)[0]
    n_oos_actual = len(oos_indices)
    print(f"  OOS observations (union): {n_oos_actual}")

    pre_oos_training = {}
    for name, start, end in OOS_WINDOWS:
        idx_arr = np.where(dates >= start)[0]
        if len(idx_arr) == 0:
            continue
        start_idx = int(idx_arr[0])
        avail = min(start_idx, WINDOW)
        pre_oos_training[name] = {
            'start_idx': start_idx,
            'avail_pre_window': int(start_idx),
            'effective_window': avail,
            'sufficient': bool(start_idx >= WINDOW),
        }
        print(f"    {name}: pre-OOS obs={start_idx}, "
              f"sufficient(>=2000)={'YES' if start_idx >= WINDOW else 'NO'}")

    # Rolling forecast
    gjr_forecasts = np.full(n_oos_actual, np.nan)
    a4f_forecasts = np.full(n_oos_actual, np.nan)
    refit_log = []

    gjr_h = None
    gjr_params = None
    a4f_g = None
    a4f_params = None

    prev_window = None
    refit_count = 0

    for t_idx, abs_idx in enumerate(oos_indices):
        current_window = window_tags[abs_idx]

        if t_idx == 0 or current_window != prev_window:
            need_refit = True
        else:
            window_start = next(s for n, s, e in OOS_WINDOWS
                                if n == current_window)
            window_start_idx = np.where(dates >= window_start)[0][0]
            days_in_window = abs_idx - window_start_idx
            need_refit = (days_in_window % REFIT_EVERY == 0)

        if need_refit:
            refit_count += 1
            train_start = max(0, abs_idx - WINDOW)
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            gjr_p, gjr_conv = fit_gjr(train_ret)
            if gjr_p is not None:
                gjr_params = gjr_p
                h = np.var(train_ret[:min(250, len(train_ret))])
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
                gjr_h = h
            else:
                gjr_conv = False

            a4f_p, a4f_conv = fit_a4f(train_ret, train_vix)
            if a4f_p is not None:
                a4f_params = a4f_p
                theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_p
                vol_lag_tr = np.empty(len(train_vix))
                vol_lag_tr[0] = train_vix[0]
                vol_lag_tr[1:] = train_vix[:-1]
                tau_tr = np.maximum(theta0 + theta1 * vol_lag_tr**2, 1e-16)
                persist = alpha_p + gamma_p / 2.0 + beta_p
                g = omega_g / (1.0 - persist)
                for i in range(1, len(train_ret)):
                    u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                a4f_g = g
            else:
                a4f_conv = False

            refit_log.append({
                'date': dates[abs_idx].strftime('%Y-%m-%d'),
                'window': current_window,
                'gjr_conv': bool(gjr_conv),
                'a4f_conv': bool(a4f_conv),
                'a4f_theta0':  float(a4f_params[0]) if a4f_params is not None else None,
                'a4f_theta1':  float(a4f_params[1]) if a4f_params is not None else None,
                'a4f_omega':   float(a4f_params[2]) if a4f_params is not None else None,
                'a4f_persist': (float(a4f_params[3] + a4f_params[4]/2 + a4f_params[5])
                                if a4f_params is not None else None),
            })

            if refit_count % 10 == 0:
                elapsed = time.time() - START_TIME
                print(f"    Refit #{refit_count} at "
                      f"{dates[abs_idx].strftime('%Y-%m-%d')} "
                      f"({current_window}), elapsed {elapsed:.0f}s")

        # Forecast at t_idx using most recent parameters
        if gjr_params is not None:
            r_prev = ret[abs_idx - 1]
            h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
            gjr_forecasts[t_idx] = h_new
            gjr_h = h_new

        if a4f_params is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            v_lag = vix[abs_idx - 1]
            tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)

            r_prev = ret[abs_idx - 1]
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
            g_new = max(g_new, 1e-10)

            a4f_forecasts[t_idx] = tau_t * g_new
            a4f_g = g_new

        prev_window = current_window

    elapsed = time.time() - START_TIME
    print(f"  Forecast done, {refit_count} refits, elapsed {elapsed:.0f}s")

    # Evaluation
    oos_r2   = r2[oos_indices]
    oos_dates = dates[oos_indices]
    oos_vix  = vix[oos_indices]
    oos_window_tags = np.array([window_tags[i] for i in oos_indices])

    both_valid = (~np.isnan(gjr_forecasts) & (gjr_forecasts > 0)
                  & ~np.isnan(a4f_forecasts) & (a4f_forecasts > 0))
    n_both = int(both_valid.sum())
    print(f"  Valid joint observations: {n_both}/{n_oos_actual}")

    etf_results = {
        'metadata': {
            'ticker': ticker,
            'display_name': display_name,
            'composition': composition,
            'currency': currency,
            'ipo_start': ipo_start,
            'data_start': dates[0].strftime('%Y-%m-%d'),
            'data_end':   dates[-1].strftime('%Y-%m-%d'),
            'n_total': int(n_total),
            'n_oos_actual': int(n_oos_actual),
            'n_refits': int(refit_count),
            'pre_oos_training': pre_oos_training,
        },
        'full_oos': {},
        'per_window': {},
        'crisis_subperiods': {},
        'vix_buckets': {},
        'refit_log': refit_log,
    }

    if n_both == 0:
        print("  WARN: no valid joint observations; skipping evaluation.")
        return etf_results

    fc_g_all = gjr_forecasts[both_valid]
    fc_a_all = a4f_forecasts[both_valid]
    r2_all   = oos_r2[both_valid]

    ql_g_all = float(np.mean(qlike_loss(fc_g_all, r2_all)))
    ql_a_all = float(np.mean(qlike_loss(fc_a_all, r2_all)))
    d_all    = qlike_loss(fc_g_all, r2_all) - qlike_loss(fc_a_all, r2_all)

    dm_t, dm_p, _ = hac_dm_test(d_all)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(d_all, n_boot=1000)
    rho_g, _ = stats.spearmanr(fc_g_all, r2_all)
    rho_a, _ = stats.spearmanr(fc_a_all, r2_all)

    etf_results['full_oos'] = {
        'n': n_both,
        'qlike_gjr': ql_g_all,
        'qlike_a4f': ql_a_all,
        'qlike_diff_pct': (ql_a_all - ql_g_all) / abs(ql_g_all) * 100,
        'dm_t': dm_t,
        'dm_p': dm_p,
        'harvey_pass': bool(np.isfinite(dm_t) and abs(dm_t) > 3.0),
        'spearman_gjr': float(rho_g),
        'spearman_a4f': float(rho_a),
        'bootstrap_ci_95': [ci_lo, ci_hi],
    }
    print(f"  FULL OOS  n={n_both}  QL_GJR={ql_g_all:.6f}  "
          f"QL_A4f={ql_a_all:.6f}  diff={(ql_a_all-ql_g_all)/abs(ql_g_all)*100:+.3f}% "
          f" DM t={dm_t:+.3f}  Harvey-{'PASS' if abs(dm_t) > 3.0 else 'FAIL'}")

    print(f"  {'Window':<20} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} "
          f"{'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
    for name, start, end in OOS_WINDOWS:
        mask = (oos_window_tags == name) & both_valid
        n_w = int(mask.sum())
        if n_w < 30:
            continue
        fc_g = gjr_forecasts[mask]
        fc_a = a4f_forecasts[mask]
        r2_v = oos_r2[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))
        d    = qlike_loss(fc_g, r2_v) - qlike_loss(fc_a, r2_v)
        dm_w, dm_p_w, _ = hac_dm_test(d)
        ci_l, ci_h = bootstrap_ci_mean_diff(d, n_boot=1000)
        rho_g_w, _ = stats.spearmanr(fc_g, r2_v)
        rho_a_w, _ = stats.spearmanr(fc_a, r2_v)
        harvey = bool(np.isfinite(dm_w) and abs(dm_w) > 3.0)
        print(f"  {name:<20} {n_w:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
              f"{(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_w:>+8.3f} "
              f"{'PASS' if harvey else 'FAIL':>8}")
        etf_results['per_window'][name] = {
            'start': start, 'end': end, 'n': n_w,
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
            'dm_t': float(dm_w) if np.isfinite(dm_w) else None,
            'dm_p': float(dm_p_w) if np.isfinite(dm_p_w) else None,
            'harvey_pass': harvey,
            'spearman_gjr': float(rho_g_w),
            'spearman_a4f': float(rho_a_w),
            'bootstrap_ci_95': [ci_l, ci_h],
        }

    # Crisis sub-periods
    print(f"  Crisis sub-periods:")
    print(f"  {'Crisis':<15} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} "
          f"{'Diff%':>8} {'DM t':>8}")
    for cname, cstart, cend in CRISIS_PERIODS:
        mask = (oos_dates >= cstart) & (oos_dates <= cend) & both_valid
        n_c = int(mask.sum())
        if n_c < 30:
            print(f"  {cname:<15} insufficient n={n_c}")
            continue
        fc_g = gjr_forecasts[mask]
        fc_a = a4f_forecasts[mask]
        r2_v = oos_r2[mask]
        vix_v = oos_vix[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))
        d    = qlike_loss(fc_g, r2_v) - qlike_loss(fc_a, r2_v)
        dm_c, dm_p_c, _ = hac_dm_test(d)
        crisis_refits = [r for r in refit_log
                         if cstart <= r['date'] <= cend
                         and r.get('a4f_theta1') is not None]
        mean_theta1 = (float(np.mean([r['a4f_theta1'] for r in crisis_refits]))
                       if crisis_refits else None)
        harvey = bool(np.isfinite(dm_c) and abs(dm_c) > 3.0)
        print(f"  {cname:<15} {n_c:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
              f"{(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_c:>+8.3f}")
        etf_results['crisis_subperiods'][cname] = {
            'start': cstart, 'end': cend, 'n': n_c,
            'vix_mean': float(np.mean(vix_v)), 'vix_max': float(np.max(vix_v)),
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
            'dm_t': float(dm_c) if np.isfinite(dm_c) else None,
            'dm_p': float(dm_p_c) if np.isfinite(dm_p_c) else None,
            'harvey_pass': harvey,
            'mean_theta1': mean_theta1,
        }

    # VIX buckets (lagged VIX — matches A4f's tau_t depending on VIX_{t-1})
    oos_vix_lag = np.empty(n_oos_actual)
    for i, idx in enumerate(oos_indices):
        oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]
    print(f"  VIX buckets (lagged):")
    print(f"  {'Bucket':<10} {'Range':<12} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} "
          f"{'Diff%':>8} {'DM t':>8}")
    for bname, bmin, bmax in VIX_BUCKETS:
        mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & both_valid
        n_b = int(mask.sum())
        if n_b < 20:
            etf_results['vix_buckets'][bname] = {
                'status': 'insufficient', 'n': n_b, 'range': [bmin, bmax]}
            continue
        fc_g = gjr_forecasts[mask]
        fc_a = a4f_forecasts[mask]
        r2_v = oos_r2[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))
        d    = qlike_loss(fc_g, r2_v) - qlike_loss(fc_a, r2_v)
        dm_b, dm_p_b, _ = hac_dm_test(d)
        harvey = bool(np.isfinite(dm_b) and abs(dm_b) > 3.0)
        print(f"  {bname:<10} [{bmin},{bmax})  {n_b:>6} {ql_g:>10.5f} "
              f"{ql_a:>10.5f} {(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_b:>+8.3f}")
        etf_results['vix_buckets'][bname] = {
            'range': [bmin, bmax], 'n': n_b,
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
            'dm_t': float(dm_b) if np.isfinite(dm_b) else None,
            'dm_p': float(dm_p_b) if np.isfinite(dm_p_b) else None,
            'harvey_pass': harvey,
        }

    # theta1 stability
    valid_theta1 = [r['a4f_theta1'] for r in refit_log
                    if r.get('a4f_theta1') is not None and r.get('a4f_conv')]
    if valid_theta1:
        t1 = np.array(valid_theta1)
        theta1_stats = {
            'n_refits_converged': int(len(t1)),
            'median': float(np.median(t1)),
            'mean':   float(np.mean(t1)),
            'std':    float(np.std(t1)),
            'min':    float(np.min(t1)),
            'max':    float(np.max(t1)),
            'cv':     float(np.std(t1) / (np.mean(t1) + 1e-30)),
            'orders_of_magnitude_span': float(
                np.log10(np.max(t1) / max(np.min(t1), 1e-30))),
        }
        p10 = float(np.percentile(t1, 10))
        p90 = float(np.percentile(t1, 90))
        theta1_stats['p10'] = p10
        theta1_stats['p90'] = p90
        theta1_stats['orders_of_magnitude_span_p10p90'] = float(
            np.log10(p90 / max(p10, 1e-30)))
        etf_results['theta1_stability'] = theta1_stats
        print(f"  theta1 stability: median={theta1_stats['median']:.3e}, "
              f"span full={theta1_stats['orders_of_magnitude_span']:.2f}, "
              f"P10-P90={theta1_stats['orders_of_magnitude_span_p10p90']:.2f}")

    return etf_results


# ==================================================================
# MAIN LOOP — run each ETF
# ==================================================================
per_etf_results = {}
for ticker, ipo_start, display_name, composition, currency in ETFS:
    try:
        per_etf_results[ticker] = run_one_etf(
            ticker, ipo_start, display_name, composition, currency)
    except Exception as e:
        print(f"  ERROR running {ticker}: {e}")
        per_etf_results[ticker] = {'error': str(e)}

# ==================================================================
# CROSS-ETF AGGREGATION + REFERENCE LOAD (Paper 9 final table)
# ==================================================================
print("\n" + "=" * 72)
print("Cross-ETF Paper 9 final table (8 assets)")
print("=" * 72)

def load_ref(path, key):
    try:
        with open(path) as f:
            r = json.load(f)
        return {
            'full_dm': r['full_oos']['dm_t'],
            'full_diff_pct': r['full_oos']['qlike_diff_pct'],
            'full_n': r['full_oos']['n'],
            'harvey_pass': r['full_oos']['harvey_pass'],
            'theta1_orders': (r.get('theta1_stability') or {}).get(
                'orders_of_magnitude_span'),
            'theta1_orders_p10p90': (r.get('theta1_stability') or {}).get(
                'orders_of_magnitude_span_p10p90'),
        }
    except Exception as e:
        print(f"  Warning: cannot load {key}: {e}")
        return None

ref = {
    'SPY_K1075':  load_ref(K1075_PATH, 'SPY_K1075'),
    'QQQ_K1078':  load_ref(K1078_PATH, 'QQQ_K1078'),
    'IWM_K1080':  load_ref(K1080_PATH, 'IWM_K1080'),
    'EEM_K1081':  load_ref(K1081_PATH, 'EEM_K1081'),
    'TW_K1077':   load_ref(K1077_PATH, 'TW_K1077'),
}

# Add current K1082 ETFs
for ticker, r in per_etf_results.items():
    if 'full_oos' in r and r['full_oos']:
        ref[f'{ticker}_K1082'] = {
            'full_dm': r['full_oos']['dm_t'],
            'full_diff_pct': r['full_oos']['qlike_diff_pct'],
            'full_n': r['full_oos']['n'],
            'harvey_pass': r['full_oos']['harvey_pass'],
            'theta1_orders': r.get('theta1_stability', {}).get(
                'orders_of_magnitude_span'),
            'theta1_orders_p10p90': r.get('theta1_stability', {}).get(
                'orders_of_magnitude_span_p10p90'),
        }

# Display table
print(f"  {'Asset':<14} {'Market':<12} {'Curr':<5} {'DM t':>10} "
      f"{'Diff%':>10} {'Harvey':>8} {'θ1 span':>10}")
row_order = [
    ('SPY_K1075',  'US',       'USD'),
    ('QQQ_K1078',  'US tech',  'USD'),
    ('IWM_K1080',  'US small', 'USD'),
    ('EEM_K1081',  'EM bskt',  'USD'),
    ('EWT_K1082',  'Taiwan',   'USD'),
    ('EWZ_K1082',  'Brazil',   'USD'),
    ('FXI_K1082',  'China',    'USD'),
    ('TW_K1077',   'Taiwan',   'TWD'),
]
for key, market, curr in row_order:
    r = ref.get(key)
    if r is None:
        print(f"  {key:<14} {market:<12} {curr:<5} {'N/A':>10} {'N/A':>10} "
              f"{'N/A':>8} {'N/A':>10}")
        continue
    orders = f"{r['theta1_orders']:.2f}" if r.get('theta1_orders') is not None else 'N/A'
    print(f"  {key:<14} {market:<12} {curr:<5} {r['full_dm']:>+10.3f} "
          f"{r['full_diff_pct']:>+9.2f}% "
          f"{'PASS' if r['harvey_pass'] else 'FAIL':>8} {orders:>10}")

# ==================================================================
# HYPOTHESIS VERDICTS
# ==================================================================
print("\n" + "=" * 72)
print("HYPOTHESIS VERDICTS")
print("=" * 72)

verdicts = {}

# H1 per ETF
for ticker in ['EWT', 'EWZ', 'FXI']:
    r = per_etf_results.get(ticker, {})
    full = r.get('full_oos', {}) or {}
    dm_t = full.get('dm_t')
    if dm_t is not None and np.isfinite(dm_t):
        v = 'PASS' if abs(dm_t) > 3.0 and dm_t > 0 else 'FAIL'
        print(f"  H1 ({ticker} Full OOS |DM t|>3, A4f beats GJR): {v} "
              f"(t={dm_t:+.3f})")
    else:
        v = 'N/A'
        print(f"  H1 ({ticker}): N/A")
    verdicts[f'H1_{ticker}_harvey'] = v

# H2 — EWT vs 0050.TW currency discrimination (main payoff)
ewt_full = per_etf_results.get('EWT', {}).get('full_oos', {}) or {}
ewt_dm   = ewt_full.get('dm_t')
tw_dm    = (ref.get('TW_K1077') or {}).get('full_dm')
if ewt_dm is not None and tw_dm is not None and np.isfinite(ewt_dm):
    ewt_pass = abs(ewt_dm) > 3.0 and ewt_dm > 0
    tw_pass  = abs(tw_dm) > 3.0 and tw_dm > 0
    if ewt_pass and not tw_pass:
        h2 = 'USD_WRAPPER_NECESSARY'
        h2_interp = ('EWT (USD, Taiwan stocks) PASSES but 0050.TW (TWD, '
                     'same stocks) FAILS. USD wrapper is a necessary '
                     'condition for A4f in Taiwan equity exposure.')
    elif ewt_pass and tw_pass:
        h2 = 'BOTH_PASS'
        h2_interp = ('Both wrappers work -> currency not decisive. '
                     'Earlier 0050.TW null may have been sample-specific.')
    elif (not ewt_pass) and (not tw_pass):
        h2 = 'TAIWAN_STRUCTURE_UNIQUE'
        h2_interp = ('EWT and 0050.TW both FAIL despite different currencies '
                     '-> Taiwan market structure is unique (not currency).')
    else:
        h2 = 'TW_PASS_EWT_FAIL'
        h2_interp = ('Unexpected: 0050.TW passed but EWT failed.')
    print(f"  H2 (currency discrimination): {h2}")
    print(f"      {h2_interp}")
else:
    h2 = 'N/A'
    h2_interp = 'EWT DM unavailable'
    print(f"  H2: N/A")
verdicts['H2_currency_discrimination'] = h2
verdicts['H2_interpretation'] = h2_interp

# H3 — all three single-country ETFs pass
passes = []
for t in ['EWT', 'EWZ', 'FXI']:
    full = per_etf_results.get(t, {}).get('full_oos', {}) or {}
    dm_t = full.get('dm_t')
    if dm_t is not None and np.isfinite(dm_t):
        passes.append(abs(dm_t) > 3.0 and dm_t > 0)
h3 = 'PASS' if len(passes) == 3 and all(passes) else (
    'PARTIAL' if sum(passes) >= 2 else 'FAIL')
print(f"  H3 (all 3 single-country USD ETFs Harvey-PASS): {h3} "
      f"({sum(passes)}/{len(passes)})")
verdicts['H3_all_usd_em_pass'] = h3

# H4 — EWT theta1 stability better than 0050.TW
ewt_span_p = (per_etf_results.get('EWT', {}) or {}).get('theta1_stability', {}).get(
    'orders_of_magnitude_span_p10p90')
tw_span_p  = (ref.get('TW_K1077') or {}).get('theta1_orders_p10p90')
if ewt_span_p is not None and tw_span_p is not None:
    h4 = 'PASS' if ewt_span_p < tw_span_p else 'FAIL'
    print(f"  H4 (EWT theta1 P10-P90 span < 0050.TW): {h4}  "
          f"(EWT={ewt_span_p:.2f} vs TW={tw_span_p:.2f})")
else:
    # Fallback: use full span
    ewt_span_f = (per_etf_results.get('EWT', {}) or {}).get('theta1_stability', {}).get(
        'orders_of_magnitude_span')
    tw_span_f  = (ref.get('TW_K1077') or {}).get('theta1_orders')
    if ewt_span_f is not None and tw_span_f is not None:
        h4 = 'PASS' if ewt_span_f < tw_span_f else 'FAIL'
        print(f"  H4 (EWT theta1 full span < 0050.TW): {h4}  "
              f"(EWT={ewt_span_f:.2f} vs TW={tw_span_f:.2f})")
    else:
        h4 = 'N/A'
        print(f"  H4: N/A")
verdicts['H4_ewt_theta1_more_stable'] = h4

# H5 — no breakdown at extreme VIX
h5_flags = []
for ticker in ['EWT', 'EWZ', 'FXI']:
    buckets = per_etf_results.get(ticker, {}).get('vix_buckets', {}) or {}
    for bname in ['Extreme', 'Crisis']:
        b = buckets.get(bname, {})
        if b.get('qlike_diff_pct') is not None:
            h5_flags.append(b['qlike_diff_pct'] < 5.0)
if h5_flags:
    h5 = 'PASS' if all(h5_flags) else 'FAIL'
else:
    h5 = 'N/A'
print(f"  H5 (no A4f breakdown at VIX>40 any ETF): {h5} "
      f"({sum(h5_flags)}/{len(h5_flags)})")
verdicts['H5_no_extreme_breakdown'] = h5

# ==================================================================
# PAPER 9 FINAL CLAIM
# ==================================================================
print("\n" + "=" * 72)
print("Paper 9 final claim (based on H2 discrimination)")
print("=" * 72)
if h2 == 'USD_WRAPPER_NECESSARY':
    paper9_claim = (
        "A4f's effectiveness depends on USD-denominated exposure. Same "
        "underlying stocks in local currency fail (0050.TW), but the "
        "USD wrapper succeeds (EWT). VIX likely captures systemic "
        "USD-funding / cross-border risk that propagates only through "
        "USD-denominated assets globally (SPY, QQQ, IWM, EEM, EWT, "
        "and EM single-country ETFs), while local-currency Taiwan "
        "exposure (0050.TW) bypasses this channel.")
elif h2 == 'TAIWAN_STRUCTURE_UNIQUE':
    paper9_claim = (
        "Taiwan market structure itself is unusual for VIX-A4f: neither "
        "EWT (USD) nor 0050.TW (TWD) respond. Currency wrapper is not "
        "the explanation. Possible drivers: retail dominance, limit-up/"
        "down mechanism, concentrated TSMC exposure, or distinct "
        "macro volatility source.")
elif h2 == 'BOTH_PASS':
    paper9_claim = (
        "EWT and 0050.TW both PASS. The earlier K1077 null was likely "
        "sample-period dependent or sensitive to clean_tw50_data "
        "timing. Revisit K1077 with matched OOS window.")
else:
    paper9_claim = f"Unexpected discrimination pattern: {h2}."

print(f"  {paper9_claim}")
verdicts['paper9_claim'] = paper9_claim

# ==================================================================
# SAVE RESULTS
# ==================================================================
results = {
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Single-Country EM ETFs (EWT/EWZ/FXI) — USD Wrapper Diagnostic',
        'data_source': 'yfinance',
        'data_end': DATA_END,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'etfs': [(t, ipo, name, comp, curr) for t, ipo, name, comp, curr in ETFS],
        'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
        'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
        'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
        'random_seed': 42,
        'elapsed_seconds': time.time() - START_TIME,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'proposer': 'User (via K1082 brief)',
        'executor': 'Claude',
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
            'Harvey, Leybourne & Newbold (2016). Multiple-testing t-threshold.',
            'Hansen & Lunde (2005). A forecast comparison of volatility models.',
        ],
        'upstream_experiments': [
            'K1075 SPY extended 2007-2026 DM t=+7.92 Harvey-PASS',
            'K1077 0050.TW extended 2010-2025 DM t=-0.49 Harvey-FAIL',
            'K1078 QQQ extended 2007-2026 DM t=+5.99 Harvey-PASS',
            'K1080 IWM extended 2007-2026 DM t=+4.80 Harvey-PASS',
            'K1081 EEM extended 2007-2026 DM t=+5.25 Harvey-PASS',
        ],
        'notes': (
            'EWT/EWZ start ~2000; FXI IPO 2004-10-05 -> at 2007-01-01 FXI has '
            '~562 training obs vs WINDOW=2000 requested. Same max(0, abs_idx '
            '- WINDOW) policy as K1081 -> first refit uses all available '
            'history. Flag FXI Early_Crisis as training-light. VIX is the '
            'shared exogenous IV regressor (global risk-off signal; test '
            'currency vs structure not country-specific IV).'),
    },
    'per_etf': per_etf_results,
    'eight_asset_comparison': ref,
    'hypothesis_verdicts': verdicts,
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")

# ==================================================================
# PLOTS
# ==================================================================
print("\n[Plots] Generating 7 figures...")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # ------- Plot 1: k1082_dm_comparison.png (3 ETFs Full OOS DM)
    fig, ax = plt.subplots(figsize=(10, 6))
    etfs = ['EWT', 'EWZ', 'FXI']
    dms = [per_etf_results.get(t, {}).get('full_oos', {}).get('dm_t', np.nan)
           for t in etfs]
    colors = ['green' if np.isfinite(d) and abs(d) > 3.0
              else ('orange' if np.isfinite(d) and abs(d) > 1.96 else 'gray')
              for d in dms]
    bars = ax.bar(etfs, dms, color=colors, alpha=0.75)
    ax.axhline(3.0, ls='--', color='red', label='Harvey |t|=3')
    ax.axhline(-3.0, ls='--', color='red')
    ax.axhline(1.96, ls=':', color='gray', label='95% |t|=1.96')
    ax.axhline(-1.96, ls=':', color='gray')
    ax.axhline(0, color='black', lw=0.6)
    for i, d in enumerate(dms):
        if np.isfinite(d):
            ax.text(i, d, f'{d:+.2f}', ha='center',
                    va='bottom' if d >= 0 else 'top', fontweight='bold')
    ax.set_ylabel('DM t-stat (A4f vs GJR, >0 = A4f better)')
    ax.set_title(f'{EXPERIMENT_ID}: Single-Country EM ETF A4f — Full OOS DM')
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_dm_comparison.png'), dpi=120)
    plt.close()
    print("    k1082_dm_comparison.png")

    # ------- Plot 2: k1082_ewt_vs_0050tw.png (direct currency test)
    fig, ax = plt.subplots(figsize=(10, 6))
    ewt_dm_v = per_etf_results.get('EWT', {}).get('full_oos', {}).get('dm_t', np.nan)
    tw_dm_v  = (ref.get('TW_K1077') or {}).get('full_dm', np.nan)
    labels = ['EWT\n(Taiwan, USD)\nK1082', '0050.TW\n(Taiwan, TWD)\nK1077']
    dms2 = [ewt_dm_v, tw_dm_v]
    colors2 = ['green' if np.isfinite(d) and abs(d) > 3.0 and d > 0
               else ('red' if np.isfinite(d) and d < 0 else 'gray')
               for d in dms2]
    ax.bar(labels, dms2, color=colors2, alpha=0.8, width=0.5)
    ax.axhline(3.0, ls='--', color='red', label='Harvey |t|=3')
    ax.axhline(-3.0, ls='--', color='red')
    ax.axhline(0, color='black', lw=0.6)
    for i, d in enumerate(dms2):
        if np.isfinite(d):
            ax.text(i, d, f'{d:+.2f}', ha='center',
                    va='bottom' if d >= 0 else 'top',
                    fontweight='bold', fontsize=13)
    ax.set_ylabel('DM t-stat (A4f vs GJR)')
    ax.set_title(f'{EXPERIMENT_ID}: EWT (USD) vs 0050.TW (TWD) — '
                 'Currency Wrapper Test')
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_ewt_vs_0050tw.png'), dpi=120)
    plt.close()
    print("    k1082_ewt_vs_0050tw.png")

    # ------- Plot 3: k1082_theta1_by_etf.png
    fig, ax = plt.subplots(figsize=(10, 6))
    for ticker, color in zip(['EWT', 'EWZ', 'FXI'],
                             ['steelblue', 'coral', 'mediumseagreen']):
        log = per_etf_results.get(ticker, {}).get('refit_log', [])
        dates_t = []
        theta1_t = []
        for entry in log:
            if entry.get('a4f_theta1') is not None and entry.get('a4f_conv'):
                dates_t.append(pd.Timestamp(entry['date']))
                theta1_t.append(entry['a4f_theta1'])
        if dates_t:
            ax.plot(dates_t, theta1_t, marker='o', ms=3, lw=1.0,
                    color=color, label=f'{ticker}', alpha=0.85)
    ax.set_yscale('log')
    ax.set_ylabel('theta1 (log scale)')
    ax.set_xlabel('Refit date')
    ax.set_title(f'{EXPERIMENT_ID}: theta1 evolution by single-country ETF')
    ax.grid(True, alpha=0.3, which='both')
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_theta1_by_etf.png'), dpi=120)
    plt.close()
    print("    k1082_theta1_by_etf.png")

    # ------- Plot 4: k1082_currency_hypothesis.png
    fig, ax = plt.subplots(figsize=(10, 6))
    usd_keys = ['SPY_K1075', 'QQQ_K1078', 'IWM_K1080', 'EEM_K1081',
                'EWT_K1082', 'EWZ_K1082', 'FXI_K1082']
    twd_key = 'TW_K1077'
    usd_dms = []
    usd_labels = []
    for k in usd_keys:
        r = ref.get(k)
        if r is not None and np.isfinite(r.get('full_dm', np.nan)):
            usd_dms.append(r['full_dm'])
            usd_labels.append(k.replace('_K10', '\n(K10'))
    twd_dm = (ref.get(twd_key) or {}).get('full_dm', np.nan)
    positions = list(range(len(usd_dms))) + [len(usd_dms) + 0.5]
    all_dms = usd_dms + [twd_dm]
    all_labels = usd_labels + ['TW_K1077\n(TWD)']
    colors_all = (['steelblue'] * len(usd_dms)) + ['red']
    ax.bar(positions, all_dms, color=colors_all, alpha=0.80, width=0.75)
    ax.axhline(3.0, ls='--', color='red', label='Harvey |t|=3')
    ax.axhline(-3.0, ls='--', color='red')
    ax.axhline(0, color='black', lw=0.6)
    for i, d in enumerate(all_dms):
        if np.isfinite(d):
            ax.text(positions[i], d, f'{d:+.2f}', ha='center',
                    va='bottom' if d >= 0 else 'top', fontsize=9,
                    fontweight='bold')
    ax.set_xticks(positions)
    ax.set_xticklabels(all_labels, fontsize=9)
    ax.set_ylabel('DM t-stat (A4f vs GJR)')
    ax.set_title(f'{EXPERIMENT_ID}: USD vs TWD Wrapper — Cross-Asset DM')
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_currency_hypothesis.png'), dpi=120)
    plt.close()
    print("    k1082_currency_hypothesis.png")

    # ------- Plot 5: k1082_six_asset_final.png  (8-asset final)
    fig, ax = plt.subplots(figsize=(12, 6))
    order8 = [
        ('SPY_K1075',  'SPY',     'USD'),
        ('QQQ_K1078',  'QQQ',     'USD'),
        ('IWM_K1080',  'IWM',     'USD'),
        ('EEM_K1081',  'EEM',     'USD'),
        ('EWT_K1082',  'EWT',     'USD'),
        ('EWZ_K1082',  'EWZ',     'USD'),
        ('FXI_K1082',  'FXI',     'USD'),
        ('TW_K1077',   '0050.TW', 'TWD'),
    ]
    names8  = [n for _, n, _ in order8]
    dms8    = [(ref.get(k) or {}).get('full_dm', np.nan) for k, _, _ in order8]
    colors8 = ['steelblue' if c == 'USD' else 'red' for _, _, c in order8]
    alphas8 = [0.85 if np.isfinite(d) and abs(d) > 3 else 0.4 for d in dms8]
    for i, (n, d, c, a) in enumerate(zip(names8, dms8, colors8, alphas8)):
        ax.bar(i, d, color=c, alpha=a)
        if np.isfinite(d):
            ax.text(i, d, f'{d:+.2f}', ha='center',
                    va='bottom' if d >= 0 else 'top', fontweight='bold')
    ax.axhline(3.0, ls='--', color='red', label='Harvey |t|=3')
    ax.axhline(-3.0, ls='--', color='red')
    ax.axhline(0, color='black', lw=0.6)
    ax.set_xticks(range(len(names8)))
    ax.set_xticklabels(names8, fontsize=10)
    ax.set_ylabel('Full OOS DM t-stat (A4f vs GJR)')
    ax.set_title(f'{EXPERIMENT_ID}: 8-Asset Paper 9 Final Map '
                 '(blue=USD, red=TWD)')
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_six_asset_final.png'), dpi=120)
    plt.close()
    print("    k1082_six_asset_final.png")

    # ------- Plot 6: QLIKE per ETF per window
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    for ax_i, ticker in enumerate(['EWT', 'EWZ', 'FXI']):
        ax = axes[ax_i]
        per_w = per_etf_results.get(ticker, {}).get('per_window', {}) or {}
        win_names = [n for n in [w[0] for w in OOS_WINDOWS] if n in per_w]
        ql_g = [per_w[n]['qlike_gjr'] for n in win_names]
        ql_a = [per_w[n]['qlike_a4f'] for n in win_names]
        dm_w = [per_w[n]['dm_t'] for n in win_names]
        x = np.arange(len(win_names))
        w_b = 0.35
        ax.bar(x - w_b/2, ql_g, w_b, label='GJR', color='steelblue', alpha=0.85)
        ax.bar(x + w_b/2, ql_a, w_b, label='A4f', color='coral', alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels([n.replace('_', '\n') for n in win_names], fontsize=9)
        ax.set_ylabel('QLIKE (lower better)')
        ax.set_title(f'{ticker}')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        for i, d in enumerate(dm_w):
            if d is not None and np.isfinite(d):
                col = 'green' if abs(d) > 3 else ('orange' if abs(d) > 1.96 else 'gray')
                ax.text(x[i], max(ql_g[i], ql_a[i]), f'DM={d:+.2f}',
                        ha='center', va='bottom', fontsize=8, color=col,
                        fontweight='bold')
    plt.suptitle(f'{EXPERIMENT_ID}: QLIKE per OOS window by ETF', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_qlike_per_window.png'), dpi=120)
    plt.close()
    print("    k1082_qlike_per_window.png")

    # ------- Plot 7: VIX bucket (Diff%) per ETF
    fig, ax = plt.subplots(figsize=(11, 6))
    bucket_names = [b[0] for b in VIX_BUCKETS]
    x = np.arange(len(bucket_names))
    w_b = 0.25
    for i, (ticker, color) in enumerate(zip(['EWT', 'EWZ', 'FXI'],
                                            ['steelblue', 'coral', 'mediumseagreen'])):
        buckets = per_etf_results.get(ticker, {}).get('vix_buckets', {}) or {}
        diffs = []
        for bn in bucket_names:
            b = buckets.get(bn, {})
            diffs.append(b.get('qlike_diff_pct') if b.get('qlike_diff_pct') is not None
                         else np.nan)
        ax.bar(x + (i - 1) * w_b, diffs, w_b, label=ticker, color=color, alpha=0.85)
    ax.axhline(0, color='black', lw=0.6)
    ax.axhline(5, color='red', ls=':', alpha=0.5, label='A4f breakdown (Diff>+5%)')
    ax.set_xticks(x)
    ax.set_xticklabels(bucket_names)
    ax.set_ylabel('QLIKE Diff % (A4f vs GJR; <0 = A4f better)')
    ax.set_title(f'{EXPERIMENT_ID}: A4f performance by VIX bucket (lagged)')
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1082_vix_bucket.png'), dpi=120)
    plt.close()
    print("    k1082_vix_bucket.png")

except Exception as e:
    print(f"    Plot error: {e}")

print("\n" + "=" * 72)
print(f"  {EXPERIMENT_ID} complete in {time.time() - START_TIME:.0f}s")
print("=" * 72)
