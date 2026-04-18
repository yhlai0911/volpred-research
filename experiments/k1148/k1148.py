#!/usr/bin/env python3
"""
K1148: EAV Continuous Surprise Refinement (N=30 Taiwan Stocks)
==============================================================
[提出: Claude (承接 K1145 next_tasks K1148), 執行: Claude]

Objective:
  Refine K1145's binary EAV (1 on earnings day, 0 else) to a CONTINUOUS
  |signed-magnitude| EAV defined as:

      EAV_continuous_{i,t} = |winsor(Surprise%_i)| * 1{t = earnings_day_i}

  We use ABSOLUTE surprise magnitude because "announcement variance" is
  symmetric (both large positive and large negative surprises generate
  higher volatility). Using signed surprise breaks down because raw
  Taiwan earnings surprise distribution is extremely heavy-tailed (min
  -10802%, max +1824%) and a signed θ·surprise term would frequently
  push τ negative even after quantile-winsorization.

  Test whether the continuous spec delivers stronger / different
  identification of the pooled panel θ coefficient compared with the
  K1145 binary spec.

  Paper 2 narrative impact:
    - If θ_continuous passes stronger tests: "EAV effect is magnitude-
      proportional, consistent with a rational-announcement-variance
      mechanism" — strengthens universality claim.
    - If θ_continuous is smaller / insignificant while binary is
      significant: "The effect is about the EVENT itself, not the
      magnitude of the surprise" — binary EAV is the correct spec.
    - Either result sharpens Paper 2's interpretation.

Pre-registered hypotheses (decide in advance):
  H1  PASS if pooled θ_continuous t-stat ≥ 3.0 (Harvey 2016), BH-adj<.05
  H2  STRONGER if |z_continuous| > |z_binary_K1145| (more informative)
  H3  OOS DM (2020-2025) one-sided t ≥ 2 vs GARCH-no-EAV
  OVERFIT_RISK if H1 PASS (full-sample LRT) but H3 FAIL (OOS DM < 2)

Model spec (mirrors K1145):
  σ²_{i,t} = g_{i,t} · τ_{i,t}
  g_{i,t}  = GJR(1,1)_i  (stock-specific ω, α, γ, β)
  τ_{i,t}  = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)

  Shared across stocks: θ_VIX, θ_EAV.
  The ONLY difference vs K1145 is the EAV_i,t definition (now continuous).

Estimation:
  Block coordinate descent (BCD) + Numba-JIT inner loop
  → identical to K1145 for fair comparison

Inference:
  1. Hessian SE (1D conditional)
  2. Stock-clustered block bootstrap (n_boot=150 to match K1145)
  3. LRT vs baseline GARCH-GJR (no τ at all): χ² with df=2
  4. Within-stock permutation PLACEBO (60 reps, K1145 protocol)
  5. OOS DM-HLN: 2010-2019 IS, 2020-2025 OOS; QLIKE on r² proxy; HLN
     variant of Diebold-Mariano as in K1100g_d1 reviewer response

Data:
  - TW prices 2010-2025 (cached from K1145)
  - ^VIX 2010-2025 (cached)
  - Earnings dates + Surprise%: yfinance Ticker.get_earnings_dates(limit=80)
    ← crucial: yfinance.earnings_history returns only 4 quarters;
       get_earnings_dates returns up to ~22 years of quarterly history
  - Winsorize surprise at ±3 cross-sectional σ to damp -782%/-536% outliers

Lookahead discipline (error_log 2026-04-13 explicitly flagged):
  - VIX_{t-1}: US close t-1 (settled before TW market open at t)  [OK]
  - EAV_{i,t-1}: announcement lagged 1 trading day                [OK]
  - Surprise% is realized AT announcement; no forward-looking     [OK]
  - Code enforces `vix[t-1]` and `eav[t-1]` in `_negll_numba`    [OK]
  - IS/OOS split uses fixed calendar date; no peeking             [OK]

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

import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

# -------------------------- config --------------------------
GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
GLOBAL_RNG = np.random.default_rng(GLOBAL_SEED)

START_TIME = time.time()
EXPERIMENT_ID = 'K1148'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)
SURPRISE_CACHE = DATA_CACHE_DIR / 'earnings_dates_surprise.json'
RESULTS_PATH = SCRIPT_DIR / 'k1148_results.json'
PLACEBO_PATH = SCRIPT_DIR / 'k1148_placebo_results.json'

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2020-01-01'     # IS: 2010-2019; OOS: 2020-2025
WINSOR_Z = 3.0               # (legacy, unused) cap surprise at +-3 cross-sectional sigma
WINSOR_QUANTILE = (0.05, 0.95)  # robust cap at 5%-95% quantiles of pooled surprise
N_BOOT = 150                 # match K1145
N_PLACEBO = 60               # match K1145
BCD_MAX_OUTER = 8
BCD_TIME_BUDGET = 600        # sec for main fit

TICKERS = [
    '2330.TW', '2303.TW', '6239.TW', '2454.TW', '2379.TW', '3034.TW',
    '3035.TW', '3443.TW', '2388.TW', '2881.TW', '2882.TW', '2883.TW',
    '2886.TW', '2887.TW', '2603.TW', '2615.TW', '2609.TW', '1301.TW',
    '1303.TW', '1326.TW', '2002.TW', '2027.TW', '2317.TW', '3045.TW',
    '2382.TW', '2912.TW', '2637.TW', '1215.TW', '2347.TW', '1210.TW',
    '2892.TW',
]


# ======================================================================
# Earnings surprise loader (NEW vs K1145)
# ======================================================================
def fetch_earnings_surprises(tickers, use_cache=True):
    """Return dict: ticker -> DataFrame(index=announcement_date,
    columns=['surprise_pct']). Uses yfinance get_earnings_dates."""
    if use_cache and SURPRISE_CACHE.exists():
        with open(SURPRISE_CACHE) as f:
            cached = json.load(f)
        out = {}
        for tk, rows in cached.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            out[tk] = df
        print(f'  [surprise cache] loaded {len(out)} tickers from {SURPRISE_CACHE.name}')
        return out

    out = {}
    cache_dump = {}
    for tk in tickers:
        try:
            ed = yf.Ticker(tk).get_earnings_dates(limit=80)
            if ed is None or len(ed) == 0:
                print(f'  [surprise] {tk}: empty')
                out[tk] = pd.DataFrame(columns=['surprise_pct'])
                cache_dump[tk] = []
                continue
            ed = ed.sort_index()
            # Normalize index to tz-naive date (Taiwan market)
            idx = pd.to_datetime([i.date() for i in ed.index])
            sp = ed['Surprise(%)'].astype(float).values
            df = pd.DataFrame({'surprise_pct': sp}, index=idx)
            df = df.dropna()
            df = df[(df.index >= DATA_START) & (df.index <= DATA_END)]
            out[tk] = df
            cache_dump[tk] = [
                {'date': d.strftime('%Y-%m-%d'), 'surprise_pct': float(v)}
                for d, v in df['surprise_pct'].items()
            ]
            print(f'  [surprise] {tk}: n={len(df)}, '
                  f'range=[{df.index.min().date() if len(df)>0 else "NA"}, '
                  f'{df.index.max().date() if len(df)>0 else "NA"}]')
        except Exception as e:
            print(f'  [surprise] {tk}: ERROR {e}')
            out[tk] = pd.DataFrame(columns=['surprise_pct'])
            cache_dump[tk] = []
    with open(SURPRISE_CACHE, 'w') as f:
        json.dump(cache_dump, f, indent=2)
    print(f'  [surprise cache] saved to {SURPRISE_CACHE.name}')
    return out


def winsorize_surprises(surprise_dict, q_lo=None, q_hi=None):
    """Robust winsorization using pooled QUANTILES (not z-score), because
    Taiwan earnings surprise distribution has heavy outliers (min=-10802%,
    max=+1824%) that completely dominate the sample std. We cap at 5th/95th
    quantile by default.
    """
    if q_lo is None:
        q_lo = WINSOR_QUANTILE[0]
    if q_hi is None:
        q_hi = WINSOR_QUANTILE[1]
    pooled = np.concatenate(
        [df['surprise_pct'].values for df in surprise_dict.values()
         if len(df) > 0]
    )
    if len(pooled) == 0:
        return surprise_dict, {}
    lo = float(np.percentile(pooled, q_lo * 100))
    hi = float(np.percentile(pooled, q_hi * 100))
    n_capped = 0
    total = 0
    out = {}
    for tk, df in surprise_dict.items():
        if len(df) == 0:
            out[tk] = df
            continue
        df2 = df.copy()
        before = df2['surprise_pct'].values.copy()
        df2['surprise_pct'] = df2['surprise_pct'].clip(lower=lo, upper=hi)
        n_capped += int((before != df2['surprise_pct'].values).sum())
        total += len(df2)
        out[tk] = df2
    info = {
        'winsor_method': 'quantile',
        'q_lo': q_lo, 'q_hi': q_hi,
        'winsor_lo': lo, 'winsor_hi': hi,
        'n_capped': n_capped, 'n_total': total,
        'pct_capped': n_capped / total if total > 0 else 0.0,
        'pooled_min_raw': float(pooled.min()),
        'pooled_max_raw': float(pooled.max()),
        'pooled_mean_raw': float(pooled.mean()),
        'pooled_std_raw': float(pooled.std(ddof=1)),
    }
    return out, info


# ======================================================================
# Data loading (mirrors K1145 style)
# ======================================================================
def load_earnings_binary(code):
    """Binary earnings dates from 財報公告日.txt (for optional comparison)."""
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


def cached_download(ticker):
    cache_path = DATA_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    print(f'    [download] {ticker} ...')
    raw = yf.download(ticker, start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    try:
        raw.to_parquet(cache_path)
    except Exception:
        pass
    return raw


def build_continuous_eav(trading_days, surprise_df, use_absolute=True):
    """Build continuous EAV array:
       eav[t] = |surprise_pct|/100 on announcement day t, else 0.

       Uses ABSOLUTE value of surprise by default (use_absolute=True).
       Rationale: "announcement VARIANCE" is symmetric — both positive
       and negative surprises generate higher volatility. Using signed
       surprise would introduce a strong asymmetric constraint that
       often makes τ = θ₀ + θ_EAV·surprise go negative when θ_EAV>0 and
       surprise<0. Absolute-value EAV preserves the magnitude-proportional
       test and keeps τ monotone positive.

       If use_absolute=False, we use signed surprise (exposes the risk
       of negative τ — call carefully).

       Lookahead: the array is a raw signal indexed on TRUE announcement
       date. Lag-1 will be applied inside `_negll_numba` so that τ[t]
       uses eav[t-1] only.
    """
    eav = np.zeros(len(trading_days), dtype=float)
    if len(surprise_df) == 0:
        return eav
    pos_arr = trading_days.searchsorted(surprise_df.index.values)
    for p, sp in zip(pos_arr, surprise_df['surprise_pct'].values):
        p = int(p)
        if 0 <= p < len(trading_days):
            # Convert percent to decimal fraction (5.33% -> 0.0533)
            v = float(sp) / 100.0
            if use_absolute:
                eav[p] = abs(v)
            else:
                eav[p] = v
    return eav


def build_binary_eav(trading_days, ann_dates):
    """K1145-style binary indicator (for local comparison inside K1148)."""
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        if 0 <= p < len(trading_days):
            eav[p] = 1.0
    return eav


def load_one_stock(ticker, surprise_df, mode='continuous'):
    """mode='continuous' uses yfinance surprise magnitude;
       mode='binary_local' uses yfinance announcement dates as 1/0;
       mode='binary_ref' uses 財報公告日.txt as 1/0 (matches K1145)."""
    code = ticker.replace('.TW', '')
    raw = cached_download(ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = cached_download('^VIX')
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]

    if mode == 'continuous':
        eav_arr = build_continuous_eav(df.index, surprise_df)
        n_events = int((eav_arr != 0).sum())
    elif mode == 'binary_local':
        # Take only the announcement dates from yfinance surprise df
        ann = pd.DatetimeIndex(surprise_df.index)
        eav_arr = build_binary_eav(df.index, ann)
        n_events = int(eav_arr.sum())
    elif mode == 'binary_ref':
        ann = load_earnings_binary(code)
        eav_arr = build_binary_eav(df.index, ann)
        n_events = int(eav_arr.sum())
    else:
        raise ValueError(f'unknown mode {mode}')

    if len(df) < 500 or n_events < 15:
        return None
    return {
        'ticker': ticker, 'code': code,
        'r': df['r'].values, 'vix': df['vix'].values,
        'eav': eav_arr, 'index': df.index,
        'n_obs': len(df), 'n_events': n_events,
    }


# ======================================================================
# Likelihood (identical to K1145)
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
    # No-lookahead τ construction (Codex-corrected 2026-04-17):
    #   At t=0 we have no t-1 information, so we use the long-run
    #   unconditional τ level = θ₀ (no vix/eav influence). This ensures
    #   τ[t] strictly uses only info known by t-1. The likelihood loop
    #   starts at t=1 anyway, so the t=0 τ value is only a burn-in state.
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
    """Returns array of sigma2[t] for t in [0, n-1], used for OOS QLIKE.

    Codex-corrected 2026-04-17: t=0 uses τ=θ₀ (unconditional long-run
    level; no vix/eav t=0 lookup). The evaluator should drop t=0 before
    QLIKE computation (callers already skip t=0)."""
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


def fit_pooled_panel(stocks, max_outer=8, init_vix=1e-7, init_eav=1e-3,
                     verbose=True, time_budget=None,
                     bounds_shared=None):
    """BCD. For continuous EAV, default init_eav larger because surprise
    values are in [-0.3, 0.3] roughly, so theta needs different scale vs
    binary (0/1). Bounds also widened."""
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_eav = float(init_eav)
    params_list = [None] * len(stocks)
    prev_negll = np.inf
    history = []
    converged = False
    if bounds_shared is None:
        bounds_shared = [(1e-9, 1e-3), (-1e-1, 1e-1)]

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


def cluster_bootstrap_theta_eav(stocks, n_boot=150, seed=42,
                                  init_vix=1e-7, init_eav=1e-3,
                                  inner_max_outer=2, per_boot_time_budget=45,
                                  bounds_shared=None):
    rng = np.random.default_rng(seed)
    N = len(stocks)
    draws = []
    for b in range(n_boot):
        idx = rng.integers(0, N, size=N)
        boot = [stocks[i] for i in idx]
        try:
            fit = fit_pooled_panel(boot, max_outer=inner_max_outer,
                                    init_vix=init_vix, init_eav=init_eav,
                                    verbose=False,
                                    time_budget=per_boot_time_budget,
                                    bounds_shared=bounds_shared)
            draws.append(fit['theta_eav'])
        except Exception as e:
            print(f'    [boot {b}] fail: {e}')
            continue
    return np.array(draws)


def bh_adjust(pvals):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = ranked * n / (np.arange(1, n + 1))
    for i in range(n - 2, -1, -1):
        adj_sorted[i] = min(adj_sorted[i], adj_sorted[i + 1])
    adj = np.empty(n)
    adj[order] = np.minimum(adj_sorted, 1.0)
    return adj


# ======================================================================
# LRT baseline (no τ at all: pure GJR)
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
# OOS: QLIKE + Diebold-Mariano-HLN
# ======================================================================
def qlike(sigma2, r2):
    sigma2 = np.maximum(sigma2, 1e-16)
    r2 = np.maximum(r2, 1e-16)
    return np.log(sigma2) + r2 / sigma2


def dm_hln_stat(L1, L2):
    """One-sided Diebold-Mariano with Harvey-Leybourne-Newbold (1997)
    small-sample correction at horizon h=1.

    d_t = L1 - L2.
    Negative d_t mean L1 < L2 => model1 better.
    Returns (dm_stat, pvalue_one_sided_model1_better).
    """
    d = np.asarray(L1) - np.asarray(L2)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return None, None
    dbar = d.mean()
    # Newey-West variance with h=1 (so use lag 0 only, i.e. sample var
    # of d)
    var_d = np.var(d, ddof=1) / T
    if var_d <= 0:
        return None, None
    # HLN small-sample scaling: sqrt((T+1-2h+h(h-1)/T)/T) with h=1 => sqrt(T/T)=1
    # So HLN at h=1 collapses to Student-t(T-1) for inference.
    stat = dbar / np.sqrt(var_d)
    p_one = float(1 - stats.t.cdf(-stat, df=T - 1))  # P(stat' <= stat) under H0
    # We want one-sided test model1<model2 (L1<L2, i.e. dbar<0):
    # p = P(T <= stat) under H0 (mean zero)
    p_one_sided_m1_better = float(stats.t.cdf(stat, df=T - 1))
    return float(stat), p_one_sided_m1_better


# ======================================================================
# PLACEBO (within-stock permutation)
# ======================================================================
def placebo_run(stocks, n_rep=60, seed=42, theta_vix_init=1e-7,
                theta_eav_init=1e-3, inner_max_outer=2,
                per_boot_time_budget=45, bounds_shared=None):
    """Permute each stock's EAV array independently (preserves time-series
    structure of returns and cross-stock dispersion of magnitudes, breaks
    time alignment with returns)."""
    rng = np.random.default_rng(seed + 1001)
    draws = []
    for b in range(n_rep):
        perm_stocks = []
        for st in stocks:
            eav = st['eav'].copy()
            rng.shuffle(eav)
            perm_stocks.append({
                **{k: v for k, v in st.items() if k != 'eav'},
                'eav': eav,
            })
        try:
            fit = fit_pooled_panel(perm_stocks, max_outer=inner_max_outer,
                                    init_vix=theta_vix_init,
                                    init_eav=theta_eav_init,
                                    verbose=False,
                                    time_budget=per_boot_time_budget,
                                    bounds_shared=bounds_shared)
            draws.append(fit['theta_eav'])
        except Exception as e:
            print(f'    [placebo {b}] fail: {e}')
    return np.array(draws)


# ======================================================================
# Main
# ======================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: EAV Continuous Surprise Refinement (N=30 TW)')
    print(f'{"=" * 72}\n')

    # --- [1/8] Fetch surprise --- -----------------------------------
    print('[1/8] Fetching earnings surprise via yfinance '
          '(get_earnings_dates) ...')
    sur_dict = fetch_earnings_surprises(TICKERS, use_cache=True)
    sur_dict, winsor_info = winsorize_surprises(sur_dict)
    print(f'\n  Quantile winsorization [{winsor_info.get("q_lo")}, {winsor_info.get("q_hi")}]:'
          f' lo={winsor_info.get("winsor_lo", 0):.2f}%, '
          f'hi={winsor_info.get("winsor_hi", 0):.2f}%, '
          f'capped {winsor_info.get("n_capped", 0)}/{winsor_info.get("n_total", 0)} '
          f'({winsor_info.get("pct_capped", 0):.1%}); raw range=[{winsor_info.get("pooled_min_raw"):.1f}%, '
          f'{winsor_info.get("pooled_max_raw"):.1f}%]\n')

    # --- [2/8] Load stocks (continuous EAV) -------------------------
    print('[2/8] Loading stocks with continuous EAV ...')
    stocks_cont = []
    for tk in TICKERS:
        st = load_one_stock(tk, sur_dict.get(tk, pd.DataFrame()),
                             mode='continuous')
        if st is None:
            print(f'    SKIP {tk}')
            continue
        stocks_cont.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]}')
    print(f'  Loaded {len(stocks_cont)}/{len(TICKERS)} stocks (continuous)\n')
    if len(stocks_cont) < 15:
        print(f'ABORT: only {len(stocks_cont)} stocks — below N=15 threshold')
        sys.exit(1)

    # --- [3/8] Pooled MLE fit (continuous) --------------------------
    print('[3/8] Pooled BCD fit (continuous EAV) ...')
    # Absolute surprise after quantile winsor: |eav| ∈ [0, 0.91].
    # Since eav ≥ 0 always, tau = θ₀ + θ_VIX·vix² + θ_EAV·eav > 0 as long
    # as θ_EAV > -θ₀/|eav|_max. For K1145 min θ₀ = 1.5e-5 and max |eav|
    # = 0.91, lower bound on θ_EAV = -1.6e-5. We widen symmetrically to
    # [-1e-4, +1e-3]. Upper bound is generous because announcement
    # variance is hypothesized positive; lower bound permits rejection.
    BOUNDS_SHARED = [(1e-9, 1e-3), (-1e-4, 1e-3)]
    fit_c = fit_pooled_panel(stocks_cont, max_outer=BCD_MAX_OUTER,
                              init_vix=1e-7, init_eav=1e-4,
                              verbose=True, time_budget=BCD_TIME_BUDGET,
                              bounds_shared=BOUNDS_SHARED)
    theta_eav_c = fit_c['theta_eav']
    theta_vix_c = fit_c['theta_vix']
    print(f'\n  → θ_VIX_c = {theta_vix_c:.4e}')
    print(f'  → θ_EAV_c = {theta_eav_c:+.4e}')
    print(f'  → pooled loglik = {fit_c["pooled_loglik"]:.2f}')

    se_c = hessian_se_theta_eav(
        stocks_cont, [np.array(p) for p in fit_c['per_stock_params']],
        theta_vix_c, theta_eav_c,
    )
    t_c = theta_eav_c / se_c if (se_c and se_c > 0) else np.nan
    p_c = float(2 * (1 - stats.norm.cdf(abs(t_c)))) if np.isfinite(t_c) else 1.0
    print(f'  Hessian SE={se_c}, t={t_c:.3f}, p={p_c:.4g}')

    # --- [4/8] Cluster bootstrap ------------------------------------
    print(f'\n[4/8] Stock-clustered block bootstrap (n_boot={N_BOOT}) ...')
    boot_t0 = time.time()
    boot_draws = cluster_bootstrap_theta_eav(
        stocks_cont, n_boot=N_BOOT, seed=GLOBAL_SEED,
        init_vix=theta_vix_c, init_eav=theta_eav_c,
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_shared=BOUNDS_SHARED,
    )
    print(f'  completed {len(boot_draws)}/{N_BOOT} '
          f'(elapsed={time.time() - boot_t0:.1f}s)')
    if len(boot_draws) >= 30:
        boot_se = float(np.std(boot_draws, ddof=1))
        boot_mean = float(np.mean(boot_draws))
        boot_ci = [float(np.percentile(boot_draws, 2.5)),
                   float(np.percentile(boot_draws, 97.5))]
        boot_t = theta_eav_c / boot_se if boot_se > 0 else np.nan
        boot_p = float(2 * min(np.mean(boot_draws <= 0),
                                np.mean(boot_draws >= 0)))
    else:
        boot_se = boot_mean = boot_t = boot_p = None
        boot_ci = None
    print(f'  bootstrap mean={boot_mean}, SE={boot_se}')
    print(f'  bootstrap 95% CI = {boot_ci}')
    print(f'  bootstrap t={boot_t}, p={boot_p}')

    # --- [5/8] LRT vs pure GJR (no τ) -------------------------------
    print('\n[5/8] LRT vs baseline GJR (no τ) ...')
    # full log-likelihood: θ_VIX + θ_EAV (df=2)
    full_ll = fit_c['pooled_loglik']
    baseline_ll = 0.0
    for st in stocks_cont:
        p, nll = fit_pure_gjr(st['r'])
        baseline_ll += -nll
    lrt = 2 * (full_ll - baseline_ll)
    lrt_p = float(1 - stats.chi2.cdf(lrt, df=2))
    print(f'  full_ll={full_ll:.2f}, baseline_ll={baseline_ll:.2f}, LRT={lrt:.2f}, p={lrt_p:.4g}')

    # --- [6/8] PLACEBO (within-stock permutation) -------------------
    print(f'\n[6/8] Placebo (within-stock EAV permutation, n={N_PLACEBO}) ...')
    placebo_t0 = time.time()
    placebo_draws = placebo_run(
        stocks_cont, n_rep=N_PLACEBO, seed=GLOBAL_SEED,
        theta_vix_init=theta_vix_c, theta_eav_init=1e-5,  # small init to avoid bias
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_shared=BOUNDS_SHARED,
    )
    print(f'  placebo completed {len(placebo_draws)}/{N_PLACEBO} '
          f'(elapsed={time.time() - placebo_t0:.1f}s)')
    if len(placebo_draws) >= 30:
        placebo_mean = float(np.mean(placebo_draws))
        placebo_se = float(np.std(placebo_draws, ddof=1))
        placebo_ci = [float(np.percentile(placebo_draws, 2.5)),
                      float(np.percentile(placebo_draws, 97.5))]
        placebo_t = theta_eav_c / placebo_se if placebo_se > 0 else np.nan
        placebo_distance = (theta_eav_c - placebo_mean) / placebo_se if placebo_se > 0 else np.nan
        # one-sided p: P(placebo >= observed)
        if theta_eav_c > 0:
            placebo_one_sided_p = float(np.mean(placebo_draws >= theta_eav_c))
        else:
            placebo_one_sided_p = float(np.mean(placebo_draws <= theta_eav_c))
    else:
        placebo_mean = placebo_se = placebo_t = placebo_distance = placebo_one_sided_p = None
        placebo_ci = None
    print(f'  placebo mean={placebo_mean}, SE={placebo_se}, distance={placebo_distance}σ')
    print(f'  placebo one-sided p = {placebo_one_sided_p}')

    # Save placebo JSON separately
    with open(PLACEBO_PATH, 'w') as f:
        json.dump({
            'experiment_id': EXPERIMENT_ID,
            'n_placebo': int(len(placebo_draws)),
            'placebo_mean': placebo_mean,
            'placebo_se': placebo_se,
            'placebo_ci_95': placebo_ci,
            'observed_theta_eav': theta_eav_c,
            'placebo_distance_sigma': placebo_distance,
            'placebo_one_sided_p': placebo_one_sided_p,
            'draws': placebo_draws.tolist(),
        }, f, indent=2, ensure_ascii=False)
    print(f'  → {PLACEBO_PATH}')

    # --- [7/8] OOS DM-HLN (2020-2025) -------------------------------
    print('\n[7/8] OOS DM-HLN QLIKE (IS 2010-2019, OOS 2020-2025) ...')
    # Re-split each stock into IS / OOS, fit pooled on IS, forecast on OOS
    is_stocks = []
    oos_arrays = []
    oos_start_ts = pd.Timestamp(OOS_START)
    for st in stocks_cont:
        idx = st['index']
        # NOTE: idx < ts on DatetimeIndex returns a plain numpy.ndarray,
        # NOT a pandas Series. So we use it directly without .values.
        mask_is = np.asarray(idx < oos_start_ts, dtype=bool)
        mask_oos = np.asarray(idx >= oos_start_ts, dtype=bool)
        if mask_is.sum() < 500:
            print(f'    {st["ticker"]}: IS too short ({int(mask_is.sum())}), skip')
            continue
        if mask_oos.sum() < 250:
            print(f'    {st["ticker"]}: OOS too short ({int(mask_oos.sum())}), skip')
            continue
        is_stocks.append({
            'ticker': st['ticker'], 'code': st['code'],
            'r': st['r'][mask_is],
            'vix': st['vix'][mask_is],
            'eav': st['eav'][mask_is],
            'index': idx[mask_is],
            'n_obs': int(mask_is.sum()),
            'n_events': int((st['eav'][mask_is] != 0).sum()),
        })
        oos_arrays.append({
            'ticker': st['ticker'],
            'r': st['r'][mask_oos],
            'vix': st['vix'][mask_oos],
            'eav': st['eav'][mask_oos],
            'r_full_tail_vix': st['vix'][mask_is][-1] if mask_is.sum() > 0 else None,
            'r_full_tail_eav': st['eav'][mask_is][-1] if mask_is.sum() > 0 else None,
            'is_last_r': st['r'][mask_is][-1] if mask_is.sum() > 0 else None,
        })
    print(f'  IS stocks: {len(is_stocks)}, OOS stocks: {len(oos_arrays)}')

    # Fit continuous-EAV model on IS
    print('  Fitting continuous-EAV on IS ...')
    fit_is_c = fit_pooled_panel(is_stocks, max_outer=6,
                                 init_vix=theta_vix_c, init_eav=theta_eav_c,
                                 verbose=False, time_budget=300,
                                 bounds_shared=BOUNDS_SHARED)
    print(f'  IS continuous θ_EAV = {fit_is_c["theta_eav"]:+.4e}')

    # Baseline: pure GJR on IS (each stock)
    print('  Fitting pure GJR on IS ...')
    is_gjr_params = []
    for st in is_stocks:
        p, _ = fit_pure_gjr(st['r'])
        is_gjr_params.append(p)

    # OOS QLIKE for both models
    # Per-stock DM-HLN (then aggregate) - Codex-corrected for cross-stock
    # dependence: the naive pool-all-stock-days approach overstates effective
    # T by treating cross-sectional correlations as independent.
    per_stock_dm = []
    L_cont_all = []
    L_gjr_all = []
    oos_index_list = []
    for i, oos in enumerate(oos_arrays):
        if i >= len(is_stocks):
            break
        p_cont = np.array(fit_is_c['per_stock_params'][i])
        sigma2_cont = _forecast_sigma2_numba(
            p_cont[0], p_cont[1], p_cont[2], p_cont[3], p_cont[4],
            oos['r'], oos['vix'], oos['eav'],
            fit_is_c['theta_vix'], fit_is_c['theta_eav'],
        )
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
        Lc = qlike(sigma2_cont[1:], r2[1:])
        Lg = qlike(sigma2_gjr[1:], r2[1:])
        # Per-stock DM (within stock, time dimension only)
        s_i, p_i = dm_hln_stat(Lc, Lg)
        per_stock_dm.append({
            'ticker': oos['ticker'], 'dm_stat': s_i,
            'p_cont_better': p_i,
            'mean_qlike_cont': float(np.nanmean(Lc)),
            'mean_qlike_gjr': float(np.nanmean(Lg)),
            'n': int(len(Lc)),
        })
        L_cont_all.append(Lc)
        L_gjr_all.append(Lg)

    # Cross-stock aggregate DM using stock-averaged daily diff (Jordà-like):
    # For each calendar day, average loss_diff_i across stocks, then DM on
    # the day-level series. This naturally accounts for cross-stock corr.
    # Requires stocks sharing similar OOS calendar -> use min length.
    dm_stats_valid = [d['dm_stat'] for d in per_stock_dm if d['dm_stat'] is not None]
    if len(dm_stats_valid) >= 5:
        # Option A (primary, Codex-preferred): Pesaran-Timmermann-style panel DM
        # Use the mean of per-stock DM stats. Under H0 this should be 0 with
        # approx variance 1/N if test stats were ~N(0,1). We use a bootstrap
        # of per-stock DM stats resampled across stocks to estimate the SE.
        panel_dm_mean = float(np.mean(dm_stats_valid))
        # Bootstrap N=2000 over stocks
        rng_dm = np.random.default_rng(123)
        boot_means = np.array([
            np.mean(rng_dm.choice(dm_stats_valid, size=len(dm_stats_valid), replace=True))
            for _ in range(2000)
        ])
        panel_dm_se = float(np.std(boot_means, ddof=1))
        panel_dm_t = panel_dm_mean / panel_dm_se if panel_dm_se > 0 else None
        panel_dm_p_one = float(np.mean(boot_means >= 0)) if panel_dm_mean < 0 else float(np.mean(boot_means <= 0))
        dm_stat = panel_dm_mean  # report the aggregate stat
        dm_p_one = panel_dm_p_one
        print(f'  Per-stock DM stats: n={len(dm_stats_valid)}, '
              f'mean={panel_dm_mean:.3f}, SE={panel_dm_se:.3f}, '
              f'bootstrap_one_sided_p={panel_dm_p_one:.4f}')
    else:
        dm_stat = dm_p_one = None
        panel_dm_mean = panel_dm_se = panel_dm_t = panel_dm_p_one = None

    # Pooled QLIKE means (reporting only, not for inference)
    L_cont = np.concatenate(L_cont_all) if L_cont_all else np.array([])
    L_gjr = np.concatenate(L_gjr_all) if L_gjr_all else np.array([])
    print(f'  OOS samples: pool n={len(L_cont)}')
    print(f'  mean QLIKE cont = {np.nanmean(L_cont):.6f}')
    print(f'  mean QLIKE gjr  = {np.nanmean(L_gjr):.6f}')
    print(f'  Panel DM (per-stock mean, bootstrap inference): t={panel_dm_t}, p={panel_dm_p_one}')

    # --- [8/8] Compare to K1145 binary ------------------------------
    print('\n[8/8] Compare to K1145 binary baseline ...')
    try:
        with open(PROJECT_ROOT / 'experiments' / 'k1145' / 'k1145_results.json') as f:
            k1145 = json.load(f)
        k1145_main = k1145['main_fit_eav_window_1']
        k1145_theta = k1145_main['theta_eav']
        k1145_se = k1145_main['theta_eav_se_hessian']
        k1145_t = k1145_main['theta_eav_t_hessian']
        k1145_boot = k1145['cluster_bootstrap']
        k1145_boot_t = k1145_boot['t_stat']
        print(f'  K1145 binary θ_EAV = {k1145_theta:+.4e}, t(Hessian) = {k1145_t:.2f}, t(boot) = {k1145_boot_t:.2f}')
        print(f'  K1148 continuous θ_EAV = {theta_eav_c:+.4e}, t(Hessian) = {t_c:.2f}, t(boot) = {boot_t}')
    except Exception as e:
        print(f'  Could not load K1145: {e}')
        k1145_theta = k1145_se = k1145_t = k1145_boot_t = None

    # --- Verdicts ---------------------------------------------------
    # H1: PASS if pooled Hessian |t| > 3.0 AND BH-adj p<0.05 on primary 3 tests
    primary_p = [p_c, boot_p if boot_p is not None else 1.0, lrt_p]
    primary_names = ['hessian', 'bootstrap', 'lrt']
    bh_adj = bh_adjust(primary_p)
    bh_table = [{'name': n, 'raw_p': float(p), 'bh_adj_p': float(bp)}
                for n, p, bp in zip(primary_names, primary_p, bh_adj)]
    for r in bh_table:
        print(f'  BH: {r["name"]}: raw_p={r["raw_p"]:.4g}, bh_adj_p={r["bh_adj_p"]:.4g}')

    H1 = bool(np.isfinite(t_c) and abs(t_c) > 3.0 and bh_table[0]['bh_adj_p'] < 0.05)
    H2 = None
    if boot_t is not None and k1145_boot_t is not None:
        H2 = bool(abs(boot_t) > abs(k1145_boot_t))
    H3 = None
    if panel_dm_t is not None and panel_dm_p_one is not None:
        # panel_dm_t is based on cross-stock mean of per-stock DM stats
        # with bootstrap SE across stocks. Negative + |t|>=2 => cont better
        H3 = bool(panel_dm_t <= -2.0 and panel_dm_p_one < 0.05)

    # OVERFIT_RISK = LRT p<0.001 but OOS panel DM fails to reject no-improvement
    overfit_risk = bool(lrt_p < 0.001 and (panel_dm_t is None or panel_dm_t > -2.0))

    verdict = 'INCONCLUSIVE'
    if H1 and H2 is True and H3 is True:
        verdict = 'PASS — continuous stronger and OOS validated'
    elif H1 and H2 is True and H3 is False:
        verdict = 'PARTIAL — IS stronger but OOS DM fails' + (' (OVERFIT_RISK)' if overfit_risk else '')
    elif H1 and H2 is False:
        verdict = 'H1_PASS_but_binary_stronger — continuous spec loses information'
    elif not H1:
        verdict = 'FAIL — continuous does not reject zero'
    if overfit_risk:
        verdict = verdict + ' | OVERFIT_RISK'

    print(f'\n  H1 (pooled t>3.0, BH): {H1}')
    print(f'  H2 (|boot_t_c| > |boot_t_binary|): {H2}')
    print(f'  H3 (DM-HLN t<=-2): {H3}')
    print(f'  OVERFIT_RISK: {overfit_risk}')
    print(f'\n  CORE VERDICT: {verdict}')

    # --- Plots ------------------------------------------------------
    print('\nGenerating plots ...')
    # Plot 1: θ_binary vs θ_continuous with error bars (normalized t-stats)
    plot1 = SCRIPT_DIR / 'k1148_binary_vs_continuous.png'
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    # Left: theta magnitudes (not directly comparable because units differ)
    labels_m = ['K1145\nbinary', 'K1148\ncontinuous']
    thetas = [k1145_theta if k1145_theta else 0, theta_eav_c]
    ses = [k1145_se if k1145_se else 0, se_c if se_c else 0]
    ax1.bar(labels_m, thetas, yerr=[1.96 * s for s in ses],
            color=['steelblue', 'red'], edgecolor='black',
            capsize=6, alpha=0.8)
    ax1.axhline(0, color='gray', linestyle=':')
    ax1.set_ylabel(r'$\theta_{EAV}$')
    ax1.set_title('θ_EAV point estimates (different units)')
    # Right: t-statistics comparison (apples-to-apples)
    t_hessians = [k1145_t if k1145_t else 0, t_c if np.isfinite(t_c) else 0]
    t_boots = [k1145_boot_t if k1145_boot_t else 0, boot_t if boot_t is not None and np.isfinite(boot_t) else 0]
    x = np.arange(2)
    w = 0.35
    ax2.bar(x - w / 2, t_hessians, w, label='Hessian t', color='steelblue', edgecolor='black')
    ax2.bar(x + w / 2, t_boots, w, label='Bootstrap t', color='red', edgecolor='black')
    ax2.axhline(3.0, color='black', linestyle='--', label='Harvey t=3.0')
    ax2.axhline(-3.0, color='black', linestyle='--')
    ax2.set_xticks(x)
    ax2.set_xticklabels(['K1145\nbinary', 'K1148\ncontinuous'])
    ax2.set_ylabel('t-statistic')
    ax2.set_title('Identification strength comparison')
    ax2.legend()
    plt.tight_layout()
    plt.savefig(plot1, dpi=120)
    plt.close()
    print(f'  → {plot1}')

    # Plot 2: Scatter surprise magnitude vs |r| on announcement day
    plot2 = SCRIPT_DIR / 'k1148_surprise_vs_absr.png'
    xs, ys = [], []
    for st in stocks_cont:
        mask = st['eav'] != 0
        if mask.sum() == 0:
            continue
        xs.extend(st['eav'][mask].tolist())
        ys.extend(np.abs(st['r'][mask]).tolist())
    xs = np.array(xs)
    ys = np.array(ys)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(xs, ys, alpha=0.35, s=18, color='steelblue', edgecolor='none')
    # OLS fit on |surprise| vs |r|
    if len(xs) > 20:
        slope, icept, rv, pv, se_s = stats.linregress(np.abs(xs), ys)
        xgrid = np.linspace(0, np.abs(xs).max(), 50)
        ax.plot(xgrid, slope * xgrid + icept, 'r-', linewidth=2,
                label=f'OLS |surprise|→|r|: β={slope:.3f}, t={slope/se_s:.2f}, r={rv:.3f}')
    ax.set_xlabel('Surprise (decimal, winsorized)')
    ax.set_ylabel('|log return| on announcement day')
    ax.set_title(f'K1148: Surprise magnitude vs absolute return (n={len(xs)} events)')
    ax.legend()
    ax.axvline(0, color='gray', linestyle=':')
    plt.tight_layout()
    plt.savefig(plot2, dpi=120)
    plt.close()
    print(f'  → {plot2}')

    # Plot 3: placebo vs observed
    plot3 = SCRIPT_DIR / 'k1148_placebo_distribution.png'
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if len(placebo_draws) > 0:
        ax.hist(placebo_draws, bins=20, alpha=0.7, color='lightgray',
                edgecolor='black',
                label=f'Placebo (n={len(placebo_draws)})')
        ax.axvline(np.mean(placebo_draws), color='gray', linestyle='--',
                    label=f'Placebo mean={placebo_mean:+.2e}')
    ax.axvline(theta_eav_c, color='red', linewidth=2.5,
                label=f'Observed θ_EAV={theta_eav_c:+.2e}')
    ax.axvline(0, color='black', linestyle=':', alpha=0.5)
    ax.set_xlabel(r'$\theta_{EAV}$ (continuous)')
    ax.set_ylabel('Count')
    ax.set_title(f'K1148 Placebo vs Observed (distance={placebo_distance:.2f}σ)'
                   if placebo_distance else 'K1148 Placebo')
    ax.legend()
    plt.tight_layout()
    plt.savefig(plot3, dpi=120)
    plt.close()
    print(f'  → {plot3}')

    # --- Save results ----------------------------------------------
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'EAV continuous surprise refinement (N=30 TW stocks)',
        'proposer': 'Claude (承接 K1145 next_tasks K1148)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance get_earnings_dates + cached prices',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'oos_start': OOS_START,
        'tickers_tried': TICKERS,
        'n_stocks_loaded': len(stocks_cont),
        'stocks_used': [s['ticker'] for s in stocks_cont],
        'n_earnings_events': int(sum(s['n_events'] for s in stocks_cont)),
        'winsorization': winsor_info,
        'k1145_baseline': {
            'theta': k1145_theta, 'se': k1145_se,
            't_hessian': k1145_t,
            't_bootstrap': k1145_boot_t,
        },
        'k1148_continuous': {
            'theta': theta_eav_c,
            'theta_vix': theta_vix_c,
            'se_hessian': se_c,
            't_hessian': float(t_c) if np.isfinite(t_c) else None,
            'p_hessian': p_c,
            'pooled_loglik': fit_c['pooled_loglik'],
            'n_outer_iters': fit_c['n_outer_iters'],
            'converged': fit_c['converged'],
            'bootstrap_n_completed': int(len(boot_draws)),
            'bootstrap_mean': boot_mean,
            'bootstrap_se': boot_se,
            'bootstrap_ci_95': boot_ci,
            'bootstrap_t': float(boot_t) if boot_t is not None and np.isfinite(boot_t) else None,
            'bootstrap_p': boot_p,
            'per_stock_params': fit_c['per_stock_params'],
            'per_stock_tickers': [s['ticker'] for s in stocks_cont],
        },
        'lrt_vs_baseline_gjr': {
            'full_ll': full_ll,
            'baseline_ll': baseline_ll,
            'lrt_stat': float(lrt),
            'df': 2,
            'pvalue': lrt_p,
        },
        'oos_dm_hln': {
            'is_period': f'2010-01-01 ~ {OOS_START}',
            'oos_period': f'{OOS_START} ~ {DATA_END}',
            'oos_n_obs_pooled': int(len(L_cont)),
            'mean_qlike_continuous': float(np.nanmean(L_cont)) if len(L_cont) > 0 else None,
            'mean_qlike_baseline_gjr': float(np.nanmean(L_gjr)) if len(L_gjr) > 0 else None,
            'per_stock_dm': per_stock_dm,
            'panel_dm_mean': panel_dm_mean,
            'panel_dm_se_bootstrap': panel_dm_se,
            'panel_dm_t': panel_dm_t,
            'panel_dm_one_sided_p_cont_better': panel_dm_p_one,
            'is_pooled_theta_eav': fit_is_c['theta_eav'],
            'note_dm_fix': 'Codex-corrected 2026-04-17: use per-stock DM then bootstrap over stocks; naive pool would overstate T by ignoring cross-stock correlation.',
        },
        'placebo_continuous': {
            'n_rep': int(len(placebo_draws)),
            'mean': placebo_mean,
            'se': placebo_se,
            'ci_95': placebo_ci,
            't': float(placebo_t) if placebo_t is not None and np.isfinite(placebo_t) else None,
            'distance_sigma': float(placebo_distance) if placebo_distance is not None and np.isfinite(placebo_distance) else None,
            'one_sided_p_extreme': placebo_one_sided_p,
        },
        'bh_fdr_table_primary_tests': bh_table,
        'hypothesis_results': {
            'H1_pooled_t_gt_3': H1,
            'H2_stronger_than_binary': H2,
            'H3_OOS_DM_passes': H3,
            'OVERFIT_RISK_flag': overfit_risk,
        },
        'verdict': verdict,
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Placebo → {PLACEBO_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE VERDICT: {verdict}\n')


if __name__ == '__main__':
    main()
