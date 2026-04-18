#!/usr/bin/env python3
"""
K1148_d1: K1145 binary EAV OOS panel DM retest (using K1148 infrastructure)
===========================================================================
[提出: Claude (Paper 2 §5 universal-magnitude claim validation), 執行: Claude]

Motivation:
  K1148 just reported: OOS panel DM for continuous |surprise|-EAV fails
  at t=-1.16, p=0.12 vs pure-GJR baseline, even though pooled θ_EAV
  t(Hessian)=10.43 passed.
  Paper 2 §5 narrative currently pivots to "universal-magnitude three-
  market regularity" built on K1145's binary EAV PASS. BUT K1145 only
  ever reported pooled θ_EAV t-stats (Hessian / cluster bootstrap) +
  robustness; it never ran an OOS panel DM with the per-stock + stock-
  bootstrap spec.

  Risk: if K1145's binary EAV also fails the OOS panel DM retest, the
  Paper 2 §5 narrative has no OOS leg to stand on and must be
  downgraded or pivoted.

  This experiment is a MAIN-EVIDENCE RECHECK, not an extension.

Pre-registered scenarios:
  A. Binary OOS DM t ≤ -2  → PASS. "Magnitude is noise, event is signal."
     Paper 2 §5 universal-magnitude claim can stay, possibly strengthen
     binary-optimality interpretation.
  B. Binary OOS DM t ∈ (-2, 0) → marginal FAIL. Paper 2 §5 downgraded to
     "IS-only pooled θ evidence; OOS inconclusive."
  C. Binary OOS DM t > 0 → both binary & continuous OOS-rejected. Paper
     2 §5 universal-magnitude claim must be withdrawn.

Spec (exactly match K1145 primary + K1148 OOS infrastructure):
  Binary EAV_{i,t} = 1 if t is earnings announcement day of stock i, else 0
    (uses 財報公告日.txt, the same source K1145 used, NOT yfinance surprise)
  Lag-1: τ_{i,t} = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)
  σ²_{i,t} = g_{i,t} · τ_{i,t}, g_{i,t} = GJR(1,1)_i
  Shared across stocks: θ_VIX, θ_EAV

Estimation:
  - Block coordinate descent (BCD) + Numba-JIT inner loop (verbatim K1145)
  - IS: 2010-01-01 ~ 2019-12-31 (fit pooled BCD)
  - OOS: 2020-01-01 ~ 2025-12-31 (forecast, no refit)
  - Same 29 stocks as K1148 (intersect K1145 tickers with yfinance earnings
    surprise availability) to get apples-to-apples binary-vs-continuous DM

OOS DM test (verbatim K1148, Codex-corrected panel spec):
  - Forecast σ²_i,t for each stock t ∈ OOS using IS-fitted binary model
  - Forecast σ²_i,t for each stock using IS-fitted pure GJR (baseline)
  - QLIKE loss on r² proxy
  - Per-stock DM-HLN t-stat
  - Stock-bootstrap: resample 29 per-stock DM t-stats 10,000× → panel
    DM mean t + 95% CI + one-sided p (binary better than baseline)
  - PASS: panel DM t ≤ -2.0 AND bootstrap one-sided p < 0.05

References:
  - K1145 (binary EAV pooled panel, 31 TW stocks)
  - K1148 (continuous |surprise| EAV, 30→29 TW stocks)
  - Diebold & Mariano (1995), JBES 13(3), 253-263
  - Harvey, Leybourne & Newbold (1997) IJF 13, 281-291 [HLN correction]
  - Patton (2011) JoE 160(1), 246-256 [QLIKE robust ranking]

Random seed: 42

Author: VolPred Research System
Date: 2026-04-17
"""
import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats
from numba import njit

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

# -------------------------- config --------------------------
GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
GLOBAL_RNG = np.random.default_rng(GLOBAL_SEED)

START_TIME = time.time()
EXPERIMENT_ID = 'K1148_d1'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
# Reuse K1148 price cache (same yfinance pulls, no re-download)
K1148_CACHE_DIR = PROJECT_ROOT / 'experiments' / 'k1148' / 'data'
RESULTS_PATH = SCRIPT_DIR / 'k1148_d1_results.json'

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2020-01-01'     # exactly match K1148 split

BCD_MAX_OUTER = 8
BCD_TIME_BUDGET = 600        # sec for IS fit
N_STOCK_BOOTSTRAP = 10000    # stock-bootstrap reps for OOS panel DM SE
# Harvey (2016) one-sided threshold for OOS DM PASS:
OOS_DM_THRESHOLD = -2.0      # forecast_binary beats baseline => DM negative

# Subset to the same stocks K1148 actually used (29 survivors; intersection
# with K1145's 31-stock list that had ≥15 yfinance earnings-surprise events)
# This ensures binary-vs-continuous DM is apples-to-apples.
K1148_STOCKS_USED = [
    '2330.TW', '2303.TW', '6239.TW', '2454.TW', '2379.TW', '3034.TW',
    '3035.TW', '3443.TW', '2881.TW', '2882.TW', '2886.TW', '2887.TW',
    '2603.TW', '2615.TW', '2609.TW', '1301.TW', '1303.TW', '1326.TW',
    '2002.TW', '2027.TW', '2317.TW', '3045.TW', '2382.TW', '2912.TW',
    '2637.TW', '1215.TW', '2347.TW', '1210.TW', '2892.TW',
]

# ======================================================================
# Data loading (mirrors K1145, not K1148 — because we want 財報公告日.txt
# as the binary event source, not yfinance surprise)
# ======================================================================
def load_earnings_binary(code):
    """Load earnings announcement dates from 財報公告日.txt for ticker
    code. This is the EXACT same loader K1145 used for binary EAV.
    Returns a sorted DatetimeIndex of announcement dates within data window.
    """
    with open(DATA_FILE, 'rb') as f:
        raw_text = f.read().decode('big5', errors='replace')
    lines = raw_text.strip().split('\n')
    recs = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4 and parts[0].strip() == code:
            ds = parts[3].strip()
            if ds:
                try:
                    dt = pd.Timestamp(ds.replace('/', '-'))
                    recs.append(dt)
                except Exception:
                    pass
    if not recs:
        return pd.DatetimeIndex([])
    di = pd.DatetimeIndex(recs).sort_values()
    di = di[(di >= DATA_START) & (di <= DATA_END)]
    return di


def load_cached_price(ticker):
    """Reuse K1148 parquet cache — no re-download."""
    path = K1148_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def build_binary_eav(trading_days, ann_dates):
    """K1145-style binary indicator: 1 on announcement day, 0 else.
    NO forward window (window=1 per K1145 primary spec).
    Lag-1 will be applied inside `_negll_numba`.
    """
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        if 0 <= p < len(trading_days):
            eav[p] = 1.0
    return eav


def load_one_stock(ticker):
    """Load one stock with binary EAV from 財報公告日.txt.
    Returns stock dict with r/vix/eav arrays and date index.
    """
    code = ticker.replace('.TW', '')
    raw = load_cached_price(ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = load_cached_price('^VIX')
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    ann_dates = load_earnings_binary(code)
    eav_arr = build_binary_eav(df.index, ann_dates)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        'ticker': ticker, 'code': code,
        'r': df['r'].values, 'vix': df['vix'].values,
        'eav': eav_arr, 'index': df.index,
        'n_obs': len(df), 'n_events': int(eav_arr.sum()),
    }


# ======================================================================
# Likelihood (IDENTICAL to K1148 / K1145 — lag-1 via eav[t-1], vix[t-1])
# ======================================================================
@njit(cache=True, fastmath=True)
def _negll_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                  r, vix, eav, theta_vix, theta_eav):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if omega_g <= 0.0 or alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e10
    if persist >= 0.999:
        return 1e10
    # No-lookahead τ: t=0 uses θ₀ (no t-1 info). From t=1 onwards:
    #   τ[t] = θ₀ + θ_VIX · vix[t-1]² + θ_EAV · eav[t-1]
    tau = np.empty(n)
    tau[0] = theta0 if theta0 > 1e-16 else 1e-16
    for t in range(1, n):
        vl = vix[t - 1]
        el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    eg = omega_g / (1.0 - persist)
    g = eg
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(1, n):
        tau_prev = tau[t - 1]
        if tau_prev < 1e-16:
            tau_prev = 1e-16
        u_prev = r[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        g = omega_g + alpha * u_prev * u_prev + asym + beta_p * g
        if g < 1e-10:
            g = 1e-10
        sigma2 = tau[t] * g
        if sigma2 > 0.0:
            ll += -0.5 * (log2pi + np.log(sigma2) + r[t] * r[t] / sigma2)
    return -ll


@njit(cache=True, fastmath=True)
def _forecast_sigma2_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                            r, vix, eav, theta_vix, theta_eav):
    """Forecast σ² on the same (r, vix, eav) arrays. For OOS we pass
    the OOS slice of these arrays and use the IS-fitted parameters.
    t=0 uses unconditional g level (we skip t=0 in loss computation)."""
    n = r.shape[0]
    sigma2 = np.empty(n)
    persist = alpha + gamma_p / 2.0 + beta_p
    eg = omega_g / (1.0 - persist) if persist < 0.999 else 1.0
    g = eg
    tau = np.empty(n)
    tau[0] = theta0 if theta0 > 1e-16 else 1e-16
    for t in range(1, n):
        vl = vix[t - 1]
        el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    sigma2[0] = tau[0] * g
    for t in range(1, n):
        tau_prev = tau[t - 1]
        if tau_prev < 1e-16:
            tau_prev = 1e-16
        u_prev = r[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        g = omega_g + alpha * u_prev * u_prev + asym + beta_p * g
        if g < 1e-10:
            g = 1e-10
        sigma2[t] = tau[t] * g
    return sigma2


def per_stock_neg_loglik(sp, r, vix, eav, theta_vix, theta_eav):
    t0, og, a, gp, bp = sp
    return _negll_numba(float(t0), float(og), float(a), float(gp), float(bp),
                         r, vix, eav, float(theta_vix), float(theta_eav))


def fit_one_stock_given_shared(stock, theta_vix, theta_eav, init=None):
    r, vix, eav = stock['r'], stock['vix'], stock['eav']
    var0 = np.var(r)
    if init is None:
        starts = [
            [var0 * 0.10, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.20, 0.02, 0.08, 0.10, 0.80],
        ]
    else:
        starts = [init, [var0 * 0.10, 0.05, 0.05, 0.05, 0.90]]
    bounds = [(1e-8, 1e-2), (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            res = optimize.minimize(
                per_stock_neg_loglik, s, args=(r, vix, eav, theta_vix, theta_eav),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


def pooled_loglik_given_shared(stocks, params_list, theta_vix, theta_eav):
    total = 0.0
    for st, p in zip(stocks, params_list):
        total += per_stock_neg_loglik(p, st['r'], st['vix'], st['eav'],
                                       theta_vix, theta_eav)
    return total


def shared_objective(shared, stocks, params_list):
    tv, te = shared
    return pooled_loglik_given_shared(stocks, params_list, tv, te)


def fit_pooled_panel(stocks, max_outer=8, init_vix=1e-7, init_eav=5e-5,
                     verbose=True, time_budget=None):
    """BCD for pooled MLE. Uses K1145-style bounds (binary-EAV range).
    Binary EAV magnitude is 0/1 so θ_EAV is in [-1e-2, 1e-2]; K1145 found
    +6.4e-5 in-sample."""
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_eav = float(init_eav)
    params_list = [None] * len(stocks)
    prev_negll = np.inf
    history = []
    converged = False
    # Same bounds as K1145 primary (binary EAV spec)
    bounds_shared = [(1e-9, 1e-3), (-1e-2, 1e-2)]

    for outer in range(max_outer):
        if time_budget is not None and time.time() - t_start > time_budget:
            if verbose:
                print(f'    [BCD] outer {outer}: time budget reached')
            break
        total_negll = 0.0
        for i, st in enumerate(stocks):
            pi = params_list[i]
            p, ll = fit_one_stock_given_shared(st, theta_vix, theta_eav, init=pi)
            if p is None:
                if params_list[i] is None:
                    raise RuntimeError(f'Stock {st["ticker"]} initial fit failed')
                continue
            params_list[i] = p
            total_negll += ll
        res = optimize.minimize(
            shared_objective, [theta_vix, theta_eav],
            args=(stocks, params_list),
            method='L-BFGS-B', bounds=bounds_shared,
            options={'maxiter': 200, 'ftol': 1e-10},
        )
        nv, ne = res.x
        d_ll = prev_negll - res.fun
        if verbose:
            print(f'    [BCD outer {outer}] θ_VIX={nv:.3e}, '
                  f'θ_EAV={ne:+.4e}, pooled_negll={res.fun:.2f}, '
                  f'Δll={d_ll:+.4f}, Δθ_eav={abs(ne-theta_eav):.2e}')
        history.append({
            'outer_iter': outer,
            'theta_vix': float(nv), 'theta_eav': float(ne),
            'pooled_negll': float(res.fun),
        })
        theta_vix, theta_eav = float(nv), float(ne)
        if outer >= 1 and d_ll < 1e-2 and abs(ne - history[-2]['theta_eav']) < 1e-7:
            converged = True
            if verbose:
                print('    [BCD] converged')
            break
        prev_negll = res.fun

    # Final inner pass
    final_negll = 0.0
    final_params = []
    for i, st in enumerate(stocks):
        p, ll = fit_one_stock_given_shared(st, theta_vix, theta_eav, init=params_list[i])
        if p is None:
            p = params_list[i]
            ll = per_stock_neg_loglik(p, st['r'], st['vix'], st['eav'],
                                       theta_vix, theta_eav)
        final_params.append(p)
        final_negll += ll
    return {
        'theta_vix': theta_vix, 'theta_eav': theta_eav,
        'per_stock_params': [p.tolist() for p in final_params],
        'pooled_loglik': float(-final_negll),
        'pooled_negll': float(final_negll),
        'n_outer_iters': len(history),
        'converged': converged,
        'history': history,
    }


def hessian_se_theta_eav(stocks, params_list, theta_vix, theta_eav,
                          eps_scale=1e-3):
    ll0 = pooled_loglik_given_shared(stocks, params_list, theta_vix, theta_eav)
    eps = max(abs(theta_eav) * eps_scale, eps_scale * 1e-4)
    ll_p = pooled_loglik_given_shared(stocks, params_list, theta_vix, theta_eav + eps)
    ll_m = pooled_loglik_given_shared(stocks, params_list, theta_vix, theta_eav - eps)
    h22 = (ll_p - 2 * ll0 + ll_m) / (eps ** 2)
    if h22 > 0 and np.isfinite(h22):
        return float(np.sqrt(1.0 / h22))
    return None


# ======================================================================
# Pure-GJR baseline (OOS comparator — identical to K1148)
# ======================================================================
@njit(cache=True, fastmath=True)
def _negll_pure_gjr(omega, alpha, gamma_p, beta_p, r):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if omega <= 0.0 or alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e10
    if persist >= 0.999:
        return 1e10
    h = omega / (1.0 - persist)
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(1, n):
        u_prev = r[t - 1]
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        h = omega + alpha * u_prev * u_prev + asym + beta_p * h
        if h < 1e-10:
            h = 1e-10
        ll += -0.5 * (log2pi + np.log(h) + r[t] * r[t] / h)
    return -ll


def _pure_gjr_obj(params, r):
    return _negll_pure_gjr(float(params[0]), float(params[1]),
                            float(params[2]), float(params[3]), r)


def fit_pure_gjr(r):
    var0 = np.var(r)
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.10, 0.08, 0.04, 0.85],
        [var0 * 0.15, 0.03, 0.08, 0.85],
    ]
    bounds = [(1e-10, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            res = optimize.minimize(_pure_gjr_obj, s, args=(r,),
                                     method='L-BFGS-B', bounds=bounds,
                                     options={'maxiter': 400, 'ftol': 1e-9})
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


# ======================================================================
# OOS evaluation: QLIKE + DM-HLN (identical to K1148)
# ======================================================================
def qlike(sigma2, r2):
    sigma2 = np.maximum(sigma2, 1e-16)
    r2 = np.maximum(r2, 1e-16)
    return np.log(sigma2) + r2 / sigma2


def dm_hln_stat(L1, L2):
    """One-sided DM test with HLN scaling at h=1.

    d_t = L1 - L2. dbar < 0 means model1 is better.
    Returns (dm_stat, p_one_sided_model1_better) where p uses Student-t.
    """
    d = np.asarray(L1) - np.asarray(L2)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return None, None
    dbar = d.mean()
    var_d = np.var(d, ddof=1) / T
    if var_d <= 0:
        return None, None
    stat = dbar / np.sqrt(var_d)
    p_one_sided_m1_better = float(stats.t.cdf(stat, df=T - 1))
    return float(stat), p_one_sided_m1_better


# ======================================================================
# Main
# ======================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: K1145 binary EAV OOS panel DM retest')
    print(f'{"=" * 72}\n')
    print(f'Ticker pool: {len(K1148_STOCKS_USED)} (match K1148 subset)\n')

    # --- [1/6] Load stocks with binary EAV (from 財報公告日.txt) ---
    print('[1/6] Loading stocks (binary EAV from 財報公告日.txt) ...')
    stocks = []
    for tk in K1148_STOCKS_USED:
        st = load_one_stock(tk)
        if st is None:
            print(f'    SKIP {tk}')
            continue
        stocks.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]}')
    print(f'  Loaded {len(stocks)}/{len(K1148_STOCKS_USED)} stocks\n')
    if len(stocks) < 15:
        print(f'ABORT: only {len(stocks)} stocks')
        sys.exit(1)

    # --- [2/6] Split IS / OOS (same split as K1148) ---
    print('[2/6] IS/OOS split (IS: 2010-2019, OOS: 2020-2025) ...')
    oos_start_ts = pd.Timestamp(OOS_START)
    is_stocks = []
    oos_stocks = []
    for st in stocks:
        idx = st['index']
        mask_is = np.asarray(idx < oos_start_ts, dtype=bool)
        mask_oos = np.asarray(idx >= oos_start_ts, dtype=bool)
        if mask_is.sum() < 500:
            print(f'    {st["ticker"]}: IS too short ({int(mask_is.sum())})')
            continue
        if mask_oos.sum() < 250:
            print(f'    {st["ticker"]}: OOS too short ({int(mask_oos.sum())})')
            continue
        is_stocks.append({
            'ticker': st['ticker'], 'code': st['code'],
            'r': st['r'][mask_is], 'vix': st['vix'][mask_is],
            'eav': st['eav'][mask_is], 'index': idx[mask_is],
            'n_obs': int(mask_is.sum()),
            'n_events': int(st['eav'][mask_is].sum()),
        })
        oos_stocks.append({
            'ticker': st['ticker'],
            'r': st['r'][mask_oos], 'vix': st['vix'][mask_oos],
            'eav': st['eav'][mask_oos], 'index': idx[mask_oos],
            'n_obs': int(mask_oos.sum()),
            'n_events': int(st['eav'][mask_oos].sum()),
        })
    print(f'  IS stocks: {len(is_stocks)}, OOS stocks: {len(oos_stocks)}')
    print(f'  IS total obs: {sum(s["n_obs"] for s in is_stocks):,}')
    print(f'  OOS total obs: {sum(s["n_obs"] for s in oos_stocks):,}')

    # --- [3/6] Pooled IS BCD fit (binary EAV) ---
    print('\n[3/6] Pooled BCD fit on IS (binary EAV) ...')
    fit_is = fit_pooled_panel(is_stocks, max_outer=BCD_MAX_OUTER,
                               init_vix=1e-7, init_eav=5e-5,
                               verbose=True, time_budget=BCD_TIME_BUDGET)
    theta_eav_is = fit_is['theta_eav']
    theta_vix_is = fit_is['theta_vix']
    print(f'\n  → IS θ_VIX = {theta_vix_is:.4e}')
    print(f'  → IS θ_EAV = {theta_eav_is:+.4e}')
    print(f'  → IS pooled loglik = {fit_is["pooled_loglik"]:.2f}')

    se_is = hessian_se_theta_eav(
        is_stocks, [np.array(p) for p in fit_is['per_stock_params']],
        theta_vix_is, theta_eav_is,
    )
    t_is = theta_eav_is / se_is if (se_is and se_is > 0) else np.nan
    print(f'  IS Hessian SE={se_is}, t={t_is:.3f}')

    # --- [4/6] Fit pure-GJR baseline on IS for each stock ---
    print('\n[4/6] Fitting pure-GJR baseline on IS ...')
    is_gjr_params = []
    for st in is_stocks:
        p, _ = fit_pure_gjr(st['r'])
        is_gjr_params.append(p)
    print(f'  Baseline GJR fit complete for {len(is_gjr_params)} stocks')

    # --- [5/6] OOS forecasts + per-stock DM + stock-bootstrap panel DM ---
    print('\n[5/6] OOS forecasts + per-stock DM + stock-bootstrap panel DM ...')
    per_stock_dm = []
    L_binary_all = []
    L_gjr_all = []
    for i, oos in enumerate(oos_stocks):
        if i >= len(is_stocks):
            break
        # Binary-EAV model forecast
        p_bin = np.array(fit_is['per_stock_params'][i])
        sigma2_bin = _forecast_sigma2_numba(
            p_bin[0], p_bin[1], p_bin[2], p_bin[3], p_bin[4],
            oos['r'], oos['vix'], oos['eav'],
            fit_is['theta_vix'], fit_is['theta_eav'],
        )
        # Baseline GJR forecast
        pg = is_gjr_params[i]
        if pg is None:
            continue
        persist_g = pg[1] + pg[2] / 2.0 + pg[3]
        sigma2_gjr = np.empty(len(oos['r']))
        h = pg[0] / (1.0 - persist_g) if persist_g < 0.999 else 1.0
        sigma2_gjr[0] = h
        for t in range(1, len(oos['r'])):
            u_prev = oos['r'][t - 1]
            asym = pg[2] * u_prev * u_prev if u_prev < 0.0 else 0.0
            h = pg[0] + pg[1] * u_prev * u_prev + asym + pg[3] * h
            if h < 1e-10:
                h = 1e-10
            sigma2_gjr[t] = h
        r2 = oos['r'] ** 2
        # Skip t=0 (uses unconditional tau/g level)
        L_bin = qlike(sigma2_bin[1:], r2[1:])
        L_gjr = qlike(sigma2_gjr[1:], r2[1:])
        s_i, p_i = dm_hln_stat(L_bin, L_gjr)
        per_stock_dm.append({
            'ticker': oos['ticker'],
            'dm_stat': s_i,
            'p_cont_better': p_i,
            'mean_qlike_binary': float(np.nanmean(L_bin)),
            'mean_qlike_gjr': float(np.nanmean(L_gjr)),
            'n': int(len(L_bin)),
            'n_events_oos': oos['n_events'],
            'binary_wins_by_qlike': bool(np.nanmean(L_bin) < np.nanmean(L_gjr)),
        })
        L_binary_all.append(L_bin)
        L_gjr_all.append(L_gjr)

    # Stock-bootstrap: resample per-stock DM stats N_STOCK_BOOTSTRAP times
    dm_stats_valid = np.array([d['dm_stat'] for d in per_stock_dm
                                if d['dm_stat'] is not None])
    n_valid = len(dm_stats_valid)
    print(f'  Per-stock DM stats: n_valid={n_valid}')
    if n_valid >= 5:
        panel_dm_mean = float(np.mean(dm_stats_valid))
        panel_dm_median = float(np.median(dm_stats_valid))
        rng_dm = np.random.default_rng(123)
        boot_means = np.array([
            np.mean(rng_dm.choice(dm_stats_valid, size=n_valid, replace=True))
            for _ in range(N_STOCK_BOOTSTRAP)
        ])
        panel_dm_se = float(np.std(boot_means, ddof=1))
        panel_dm_t = panel_dm_mean / panel_dm_se if panel_dm_se > 0 else None
        # 95% percentile CI for panel DM mean
        panel_dm_ci = [
            float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)),
        ]
        # One-sided p for binary-better-than-baseline (DM < 0):
        panel_dm_p_one = (
            float(np.mean(boot_means >= 0))
            if panel_dm_mean < 0
            else float(np.mean(boot_means <= 0))
        )
        # How many individual stocks have DM ≤ -2 (Harvey threshold)
        n_individual_pass = int(np.sum(dm_stats_valid <= -2.0))
        pct_individual_pass = n_individual_pass / n_valid
        print(f'  Panel DM mean={panel_dm_mean:.4f}, '
              f'median={panel_dm_median:.4f}, '
              f'SE(bootstrap,{N_STOCK_BOOTSTRAP})={panel_dm_se:.4f}')
        print(f'  Panel DM t={panel_dm_t:.4f}, '
              f'95% CI=[{panel_dm_ci[0]:.4f}, {panel_dm_ci[1]:.4f}], '
              f'one-sided p={panel_dm_p_one:.4f}')
        print(f'  Individual stocks with DM ≤ -2: {n_individual_pass}/{n_valid} '
              f'({pct_individual_pass:.1%})')
    else:
        panel_dm_mean = panel_dm_median = None
        panel_dm_se = panel_dm_t = panel_dm_p_one = None
        panel_dm_ci = None
        n_individual_pass = 0
        pct_individual_pass = 0.0

    # Pooled QLIKE reporting (not for inference)
    L_binary_pooled = np.concatenate(L_binary_all) if L_binary_all else np.array([])
    L_gjr_pooled = np.concatenate(L_gjr_all) if L_gjr_all else np.array([])
    print(f'  Pooled mean QLIKE binary={np.nanmean(L_binary_pooled):.6f}')
    print(f'  Pooled mean QLIKE GJR   ={np.nanmean(L_gjr_pooled):.6f}')

    # --- [6/6] Verdict and Paper 2 implication ---
    # Scenario A (PASS): panel_dm_t ≤ -2 AND bootstrap one-sided p < 0.05
    #   - Both conditions required per docstring spec and per K1148
    #     corrected verdict logic. t alone is not sufficient because the
    #     stock-bootstrap gives a finite-sample distribution on the
    #     panel DM mean; requiring both rules out the edge case where
    #     the SE happens to be small (giving large |t|) while the
    #     bootstrap distribution still straddles zero.
    # Scenario B (marginal FAIL): panel_dm_t ∈ (-2, 0], OR t ≤ -2 but p ≥ 0.05
    # Scenario C (reverse FAIL): panel_dm_t > 0
    if panel_dm_t is None or panel_dm_p_one is None:
        scenario = 'N/A'
        verdict = 'INCONCLUSIVE (panel DM unavailable)'
    elif panel_dm_t <= OOS_DM_THRESHOLD and panel_dm_p_one < 0.05:
        scenario = 'A'
        verdict = (
            'Scenario A: PASS. Binary EAV OOS panel DM ≤ -2 AND '
            'bootstrap one-sided p < 0.05. Paper 2 §5 universal-magnitude '
            'claim can be retained and strengthened with binary-optimality '
            'interpretation ("event is signal, magnitude is noise").'
        )
    elif panel_dm_t <= 0:
        scenario = 'B'
        verdict = (
            f'Scenario B: Marginal FAIL. Binary OOS panel DM t={panel_dm_t:.3f}, '
            f'p_one={panel_dm_p_one:.4f} — does not meet joint threshold '
            '(t ≤ -2 AND p < 0.05). Paper 2 §5 should be downgraded to '
            'IS-only pooled θ evidence; OOS panel DM inconclusive in both '
            'binary and continuous.'
        )
    else:
        scenario = 'C'
        verdict = (
            'Scenario C: Reverse FAIL. Binary OOS panel DM > 0 (baseline '
            'beats binary EAV). Paper 2 §5 universal-magnitude claim '
            'must be withdrawn. Both binary and continuous specs fail '
            'OOS; IS pooled θ evidence is not generalizable.'
        )
    print(f'\n  SCENARIO: {scenario}')
    print(f'  VERDICT: {verdict}')

    # Load K1148 continuous results for direct comparison
    print('\n  Comparison vs K1148 continuous spec:')
    try:
        with open(PROJECT_ROOT / 'experiments' / 'k1148' / 'k1148_results.json') as f:
            k1148 = json.load(f)
        k1148_cont = k1148['k1148_continuous']
        k1148_dm = k1148['oos_dm_hln']
        cmp_table = {
            'spec': ['K1145 binary (K1148_d1 retest)', 'K1148 continuous'],
            'theta_eav_is_pooled': [theta_eav_is, k1148_cont.get('theta')],
            't_hessian_is_pooled': [
                float(t_is) if np.isfinite(t_is) else None,
                k1148_cont.get('t_hessian'),
            ],
            'panel_dm_t_oos': [
                panel_dm_t,
                k1148_dm.get('panel_dm_t'),
            ],
            'panel_dm_p_one_oos': [
                panel_dm_p_one,
                k1148_dm.get('panel_dm_one_sided_p_cont_better'),
            ],
        }
        print(f'  {"spec":35} | {"θ_EAV IS":>12} | {"t_hess":>7} | '
              f'{"DM_t":>7} | {"p_one":>7}')
        for i in range(2):
            print(f'  {cmp_table["spec"][i]:35} | '
                  f'{cmp_table["theta_eav_is_pooled"][i]:>+.3e} | '
                  f'{cmp_table["t_hessian_is_pooled"][i]:>+.2f} | '
                  f'{cmp_table["panel_dm_t_oos"][i]:>+.3f} | '
                  f'{cmp_table["panel_dm_p_one_oos"][i]:>.4f}')
    except Exception as e:
        print(f'  Could not load K1148: {e}')
        cmp_table = {'error': str(e)}

    # --- Plot: 3-panel bar (pooled θ t, per-stock DM mean, bootstrap panel DM t)
    print('\n[plot] Generating binary_vs_continuous_oos.png ...')
    plot_path = SCRIPT_DIR / 'binary_vs_continuous_oos.png'
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.5))
    # Pull K1148 numbers from cmp_table if available
    try:
        bin_t_hess = float(t_is) if np.isfinite(t_is) else 0
        cont_t_hess = k1148_cont.get('t_hessian') or 0
        bin_dm_mean_indv = panel_dm_mean or 0
        k1148_dm_mean_indv = k1148_dm.get('panel_dm_mean') or 0
        bin_panel_dm_t = panel_dm_t or 0
        cont_panel_dm_t = k1148_dm.get('panel_dm_t') or 0
    except Exception:
        bin_t_hess = cont_t_hess = bin_dm_mean_indv = 0
        k1148_dm_mean_indv = bin_panel_dm_t = cont_panel_dm_t = 0
    labels = ['K1145 binary\n(K1148_d1)', 'K1148\ncontinuous']
    colors = ['steelblue', 'firebrick']

    # (a) pooled θ_EAV IS Hessian t
    ax1.bar(labels, [bin_t_hess, cont_t_hess],
             color=colors, edgecolor='black', alpha=0.8)
    ax1.axhline(3.0, color='black', linestyle='--', label='Harvey t=3.0')
    ax1.axhline(-3.0, color='black', linestyle='--')
    ax1.set_ylabel('IS pooled θ_EAV t-stat (Hessian)')
    ax1.set_title('(a) IS θ_EAV identification')
    ax1.legend()

    # (b) per-stock DM mean (point estimate)
    ax2.bar(labels, [bin_dm_mean_indv, k1148_dm_mean_indv],
             color=colors, edgecolor='black', alpha=0.8)
    ax2.axhline(0, color='gray', linestyle=':')
    ax2.axhline(-2.0, color='black', linestyle='--', label='DM=-2 threshold')
    ax2.set_ylabel('OOS per-stock DM mean')
    ax2.set_title('(b) OOS DM per-stock mean')
    ax2.legend()

    # (c) bootstrap panel DM t
    ax3.bar(labels, [bin_panel_dm_t, cont_panel_dm_t],
             color=colors, edgecolor='black', alpha=0.8)
    ax3.axhline(0, color='gray', linestyle=':')
    ax3.axhline(-2.0, color='black', linestyle='--',
                 label='Harvey t=-2.0 (OOS PASS)')
    ax3.set_ylabel('OOS bootstrap panel DM t')
    ax3.set_title('(c) OOS bootstrap panel DM t-stat')
    ax3.legend()
    plt.suptitle(f'K1148_d1: Binary EAV vs Continuous |surprise| EAV — OOS DM retest',
                   fontsize=11, y=1.02)
    plt.tight_layout()
    plt.savefig(plot_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {plot_path}')

    # --- Save results JSON ---
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'K1145 binary EAV OOS panel DM retest '
                 '(K1148 infrastructure applied to K1145 binary spec)',
        'proposer': 'Claude (Paper 2 §5 universal-magnitude validation)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance daily close (K1148 cache) + 財報公告日.txt',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'is_period': f'{DATA_START} ~ 2019-12-31',
        'oos_period': f'{OOS_START} ~ {DATA_END}',
        'tickers_tried': K1148_STOCKS_USED,
        'n_stocks_loaded': len(stocks),
        'stocks_used': [s['ticker'] for s in is_stocks],
        'n_stock_bootstrap_reps': N_STOCK_BOOTSTRAP,
        'n_is_events_total': int(sum(s['n_events'] for s in is_stocks)),
        'n_oos_events_total': int(sum(s['n_events'] for s in oos_stocks)),
        'is_fit': {
            'theta_vix': theta_vix_is,
            'theta_eav': theta_eav_is,
            'theta_eav_se_hessian': se_is,
            'theta_eav_t_hessian': float(t_is) if np.isfinite(t_is) else None,
            'pooled_loglik': fit_is['pooled_loglik'],
            'n_outer_iters': fit_is['n_outer_iters'],
            'converged': fit_is['converged'],
            'per_stock_tickers': [s['ticker'] for s in is_stocks],
            'per_stock_params': fit_is['per_stock_params'],
        },
        'oos_dm': {
            'n_stocks_valid': n_valid,
            'per_stock_dm': per_stock_dm,
            'panel_dm_mean': panel_dm_mean,
            'panel_dm_median': panel_dm_median,
            'panel_dm_se_bootstrap': panel_dm_se,
            'panel_dm_t': panel_dm_t,
            'panel_dm_ci_95': panel_dm_ci,
            'panel_dm_one_sided_p_binary_better': panel_dm_p_one,
            'n_individual_pass_dm_le_neg2': n_individual_pass,
            'pct_individual_pass_dm_le_neg2': pct_individual_pass,
            'threshold_oos_dm_pass': OOS_DM_THRESHOLD,
            'mean_qlike_binary_pooled': float(np.nanmean(L_binary_pooled))
                if len(L_binary_pooled) > 0 else None,
            'mean_qlike_baseline_gjr_pooled': float(np.nanmean(L_gjr_pooled))
                if len(L_gjr_pooled) > 0 else None,
            'note_dm_spec':
                'Per-stock DM-HLN (time-series within each stock) then '
                'stock-bootstrap (resample 29 t-stats with replacement, '
                f'{N_STOCK_BOOTSTRAP} reps). '
                'Codex-corrected K1148 spec — no naive pool-all-stock-days.',
        },
        'comparison_k1148_continuous': cmp_table,
        'scenario': scenario,
        'verdict': verdict,
        'paper2_implication': {
            'scenario_A_means':
                'universal-magnitude claim retained + binary-optimality narrative',
            'scenario_B_means':
                'downgrade §5 to IS-only evidence; OOS inconclusive',
            'scenario_C_means':
                'withdraw universal-magnitude claim; §5 must pivot',
            'actual_scenario': scenario,
        },
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE VERDICT: {verdict}\n')


if __name__ == '__main__':
    main()
