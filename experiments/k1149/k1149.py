#!/usr/bin/env python3
"""
K1149: Pooled EAV vs PCA-based systematic factor competition (absorption test)
=============================================================================
[提出: Claude (Paper 2 §5 absorption test), 執行: Claude]

Motivation:
  K1148_d2 reported US panel DM t=-5.58 / -5.25 (binary/continuous) PASS;
  K1148 & K1148_d1 TW both FAILED OOS. Before Paper 2 §5 claims the US
  PASS is a "true firm-event effect", we must rule out: θ_EAV simply
  picks up that earnings days cluster in market-stress periods (2020-Q1
  COVID, 2022 hawkish-Fed, 2023 banking). If we add a market-factor
  stress term |PC1_{t-1}| (orthogonal to VIX) and θ_EAV shrinks + loses
  significance, then universal-magnitude is factor effect, not firm-
  event effect.

Design (nested specs, strictly aligned with K1148 / K1148_d1):
  M1 (EAV only):   τ = θ₀ + θ_VIX·VIX²_{t-1} + θ_EAV·EAV_{t-1}
  M2 (factor only): τ = θ₀ + θ_VIX·VIX²_{t-1} + γ_PC1·|PC1|_{t-1}
  M3 (both):        τ = θ₀ + θ_VIX·VIX²_{t-1} + θ_EAV·EAV_{t-1}
                        + γ_PC1·|PC1|_{t-1}
  M4 (EAV × stress interaction):
                   τ = M3 + θ_stress·EAV_{t-1}·|PC1|_{t-1}

  σ²_{i,t} = g_{i,t} · τ_{i,t};  g_{i,t} = GJR(1,1)_i

PCA leakage control (CRITICAL):
  • Fit PCA on IS panel returns only (pooled across stocks and dates)
  • OOS PC1 = OOS returns × IS loadings (no refit)
  • Use |PC1_{t-1}| (absolute stress; lag-1 same as other regressors)

Hypotheses:
  H1 absorption (per market):
    • Compare M3 vs M2 (LRT) and M3 OOS panel DM vs M2 OOS panel DM
    • PASS  = θ_EAV in M3 still has t ≥ 3 AND OOS DM M3-vs-M2 t ≤ -2
    • FAIL = θ_EAV absorbed (t < 3 OR LR p-value collapse)

  H2 market-specific: Run H1 on US + TW separately.
  H3 interaction: Compare M4 vs M3 (LRT) on θ_stress.

Paper 2 §5 branching:
  Scenario A: US PASS + TW PASS → Paper 2 strong (firm-event real both markets)
  Scenario B: US PASS + TW FAIL → heterogeneity stronger (US real, TW IS artifact)
  Scenario C: US FAIL + TW FAIL → universal-magnitude is factor effect (weakened)
  Scenario D: H3 PASS → EAV is conditional-on-stress effect (reframe)

Reuse:
  • US: 30 stocks from K1147/K1148_d2 cache (2014-2025)
  • TW: 29 stocks from K1148_d1 (財報公告日.txt binary EAV, cache from K1148)
  • VIX^2: K1148_d2 spec (lag-1)
  • earnings: US = yfinance get_earnings_dates (cached in k1148_d2/data/),
              TW = 財報公告日.txt (as K1145/K1148_d1)

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
EXPERIMENT_ID = 'K1149'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_PATH = SCRIPT_DIR / 'k1149_results.json'

# Caches (reuse prior experiments — no new yfinance hits needed for prices)
K1147_CACHE_DIR = PROJECT_ROOT / 'experiments' / 'k1147' / 'data'
K1148_CACHE_DIR = PROJECT_ROOT / 'experiments' / 'k1148' / 'data'
K1148_D2_DATA_DIR = PROJECT_ROOT / 'experiments' / 'k1148_d2' / 'data'
US_SURPRISE_CACHE = K1148_D2_DATA_DIR / 'earnings_dates_surprise_us.json'

TW_EARNINGS_FILE = PROJECT_ROOT / '財報公告日.txt'

US_DATA_START = '2014-01-01'
TW_DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2020-01-01'

BCD_MAX_OUTER = 8
BCD_TIME_BUDGET = 600
N_STOCK_BOOTSTRAP = 10000
OOS_DM_THRESHOLD = -2.0
HARVEY_T_THRESHOLD = 3.0  # Harvey (2016) IS identification

# K1147 US 30-stock panel
US_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]

# K1148_d1 TW 29-stock panel (identical subset)
TW_TICKERS = [
    '2330.TW', '2303.TW', '6239.TW', '2454.TW', '2379.TW', '3034.TW',
    '3035.TW', '3443.TW', '2881.TW', '2882.TW', '2886.TW', '2887.TW',
    '2603.TW', '2615.TW', '2609.TW', '1301.TW', '1303.TW', '1326.TW',
    '2002.TW', '2027.TW', '2317.TW', '3045.TW', '2382.TW', '2912.TW',
    '2637.TW', '1215.TW', '2347.TW', '1210.TW', '2892.TW',
]


# ======================================================================
# Price & earnings loaders
# ======================================================================
def load_cached_price(ticker, cache_dir):
    safe = ticker.replace('^', 'IDX_').replace('-', '_')
    path = cache_dir / f"{safe}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_us_surprises(tickers):
    """K1148_d2 cached surprise data."""
    if not US_SURPRISE_CACHE.exists():
        raise FileNotFoundError(f'{US_SURPRISE_CACHE} not found — run K1148_d2 first')
    with open(US_SURPRISE_CACHE) as f:
        cached = json.load(f)
    out = {}
    for tk, rows in cached.items():
        if not rows:
            out[tk] = pd.DataFrame(columns=['surprise_pct'])
            continue
        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        out[tk] = df
    print(f'  [US surprise cache] {len(out)} tickers from {US_SURPRISE_CACHE.name}')
    return out


def winsorize_surprises(surprise_dict, q_lo=0.05, q_hi=0.95):
    pooled = np.concatenate(
        [df['surprise_pct'].values for df in surprise_dict.values()
         if len(df) > 0]
    )
    if len(pooled) == 0:
        return surprise_dict
    lo = float(np.percentile(pooled, q_lo * 100))
    hi = float(np.percentile(pooled, q_hi * 100))
    out = {}
    for tk, df in surprise_dict.items():
        if len(df) == 0:
            out[tk] = df
            continue
        df2 = df.copy()
        df2['surprise_pct'] = df2['surprise_pct'].clip(lower=lo, upper=hi)
        out[tk] = df2
    return out


def load_tw_earnings_binary(code):
    """Load TW earnings announcement dates (Big5 text file)."""
    with open(TW_EARNINGS_FILE, 'rb') as f:
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
    di = di[(di >= TW_DATA_START) & (di <= DATA_END)]
    return di


def build_binary_eav(trading_days, ann_dates):
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        if 0 <= p < len(trading_days):
            eav[p] = 1.0
    return eav


def load_us_stock(ticker, surprise_df, data_start):
    raw = load_cached_price(ticker, K1147_CACHE_DIR)
    if raw is None:
        return None
    prices = raw['Close'].dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = load_cached_price('^VIX', K1147_CACHE_DIR)
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    df = df[(df.index >= data_start) & (df.index <= DATA_END)]
    if len(surprise_df) == 0:
        return None
    ann_dates = pd.DatetimeIndex(surprise_df.index)
    eav_bin = build_binary_eav(df.index, ann_dates)
    n_events = int((eav_bin != 0).sum())
    if len(df) < 500 or n_events < 15:
        return None
    return {
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav': eav_bin,
        'index': df.index,
        'n_obs': len(df),
        'n_events': n_events,
    }


def load_tw_stock(ticker):
    code = ticker.replace('.TW', '')
    raw = load_cached_price(ticker, K1148_CACHE_DIR)
    if raw is None:
        return None
    prices = raw['Close'].dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = load_cached_price('^VIX', K1148_CACHE_DIR)
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    df = df[(df.index >= TW_DATA_START) & (df.index <= DATA_END)]
    ann_dates = load_tw_earnings_binary(code)
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
# PCA factor construction (IS-only fit, no OOS leakage)
# ======================================================================
def build_pca_factor(stocks, oos_start_ts, n_components=3):
    """Fit PCA on pooled IS returns (aligned on common trading days).
    Return a DataFrame indexed by trading date with columns PC1, PC2, PC3.
    OOS values are computed by projecting OOS returns onto IS loadings
    (no refit → no look-ahead).

    Methodology:
      1. Build wide return matrix (date × stock) using each stock's
         aligned index.
      2. Split by OOS_START: IS_returns (pre-2020), OOS_returns (2020+).
      3. Demean using IS mean per stock (NO OOS mean used).
      4. SVD on IS_demeaned → components (loadings W, k = n_components).
      5. IS_factors = IS_demeaned @ W.
         OOS_factors = (OOS_raw - IS_mean) @ W.  (IS mean, IS loadings.)
    """
    # Align all stocks on common trading days
    all_r = pd.concat(
        [pd.Series(st['r'], index=st['index'], name=st['ticker'])
         for st in stocks], axis=1
    )
    # Forward-fill short gaps (inter-stock holidays); drop rows with >50% NA
    all_r = all_r.dropna(thresh=int(0.5 * len(stocks)))
    # Fill remaining NaN with 0 (non-trading in that stock on that day)
    all_r = all_r.fillna(0.0)

    is_mask = all_r.index < oos_start_ts
    IS = all_r[is_mask]
    OOS = all_r[~is_mask]

    if len(IS) < 252 or len(OOS) < 252:
        raise RuntimeError(
            f'PCA: insufficient IS or OOS (IS={len(IS)}, OOS={len(OOS)})'
        )

    is_mean = IS.mean(axis=0).values  # 1 × n_stocks (IS only)
    IS_dem = IS.values - is_mean
    OOS_dem = OOS.values - is_mean  # Use IS mean for OOS → no leakage

    # SVD on IS_demeaned only
    U, S, Vt = np.linalg.svd(IS_dem, full_matrices=False)
    W = Vt[:n_components].T  # n_stocks × k loadings
    # Explained variance on IS
    total_var = float((IS_dem ** 2).sum())
    ev = [float((S[k] ** 2)) / total_var for k in range(n_components)]

    IS_factors = IS_dem @ W   # T_IS × k
    OOS_factors = OOS_dem @ W  # T_OOS × k (projection only)

    factors_all = pd.DataFrame(
        np.concatenate([IS_factors, OOS_factors], axis=0),
        index=IS.index.append(OOS.index),
        columns=[f'PC{i+1}' for i in range(n_components)],
    ).sort_index()

    # Sign convention: make PC1 positively correlated with average IS return
    # (so |PC1| cleanly reflects 'market stress')
    mean_is_ret = IS.mean(axis=1).values
    corr_pc1 = np.corrcoef(mean_is_ret, IS_factors[:, 0])[0, 1]
    if corr_pc1 < 0:
        factors_all['PC1'] = -factors_all['PC1']
        W[:, 0] = -W[:, 0]

    return {
        'factors': factors_all,
        'loadings': pd.DataFrame(W, index=all_r.columns,
                                  columns=[f'PC{i+1}' for i in range(n_components)]),
        'explained_var_is': ev,
        'is_mean': pd.Series(is_mean, index=all_r.columns),
        'n_is_days': int(len(IS)),
        'n_oos_days': int(len(OOS)),
    }


# ======================================================================
# Likelihood (generalized to support M1/M2/M3/M4)
# spec_code:
#   1 = M1 (EAV only): uses theta_eav, ignores gamma_pc1, theta_stress
#   2 = M2 (factor only): uses gamma_pc1, ignores theta_eav, theta_stress
#   3 = M3 (both): uses theta_eav and gamma_pc1
#   4 = M4 (M3 + interaction): adds theta_stress * eav * |pc1|
# ======================================================================
@njit(cache=True, fastmath=True)
def _negll_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                  r, vix, eav, abs_pc1,
                  theta_vix, theta_eav, gamma_pc1, theta_stress,
                  spec_code):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if omega_g <= 0.0 or alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e10
    if persist >= 0.999:
        return 1e10
    tau = np.empty(n)
    tau[0] = theta0 if theta0 > 1e-16 else 1e-16
    for t in range(1, n):
        vl = vix[t - 1]
        el = eav[t - 1]
        pl = abs_pc1[t - 1]
        raw = theta0 + theta_vix * vl * vl
        if spec_code == 1 or spec_code == 3 or spec_code == 4:
            raw += theta_eav * el
        if spec_code == 2 or spec_code == 3 or spec_code == 4:
            raw += gamma_pc1 * pl
        if spec_code == 4:
            raw += theta_stress * el * pl
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
                            r, vix, eav, abs_pc1,
                            theta_vix, theta_eav, gamma_pc1, theta_stress,
                            spec_code):
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
        pl = abs_pc1[t - 1]
        raw = theta0 + theta_vix * vl * vl
        if spec_code == 1 or spec_code == 3 or spec_code == 4:
            raw += theta_eav * el
        if spec_code == 2 or spec_code == 3 or spec_code == 4:
            raw += gamma_pc1 * pl
        if spec_code == 4:
            raw += theta_stress * el * pl
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


def per_stock_negll(sp, r, vix, eav, abs_pc1,
                     theta_vix, theta_eav, gamma_pc1, theta_stress, spec_code):
    t0, og, a, gp, bp = sp
    return _negll_numba(float(t0), float(og), float(a), float(gp), float(bp),
                         r, vix, eav, abs_pc1,
                         float(theta_vix), float(theta_eav),
                         float(gamma_pc1), float(theta_stress),
                         int(spec_code))


def fit_one_stock_given_shared(r, vix, eav, abs_pc1,
                                theta_vix, theta_eav, gamma_pc1, theta_stress,
                                spec_code, init=None):
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
                per_stock_negll, s,
                args=(r, vix, eav, abs_pc1,
                      theta_vix, theta_eav, gamma_pc1, theta_stress, spec_code),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


def pooled_negll(stocks, params_list,
                  theta_vix, theta_eav, gamma_pc1, theta_stress, spec_code):
    total = 0.0
    for st, p in zip(stocks, params_list):
        total += per_stock_negll(p, st['r'], st['vix'], st['eav'],
                                  st['abs_pc1'],
                                  theta_vix, theta_eav, gamma_pc1, theta_stress,
                                  spec_code)
    return total


def fit_pooled_spec(stocks_is, spec_code, max_outer=BCD_MAX_OUTER,
                    init_vix=1e-7, init_eav=5e-5,
                    init_gamma_pc1=1e-5, init_theta_stress=0.0,
                    verbose=True, time_budget=BCD_TIME_BUDGET):
    """BCD for pooled MLE. Shared params active per spec:
      M1: (theta_vix, theta_eav)
      M2: (theta_vix, gamma_pc1)
      M3: (theta_vix, theta_eav, gamma_pc1)
      M4: (theta_vix, theta_eav, gamma_pc1, theta_stress)
    """
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_eav = float(init_eav) if spec_code in (1, 3, 4) else 0.0
    gamma_pc1 = float(init_gamma_pc1) if spec_code in (2, 3, 4) else 0.0
    theta_stress = float(init_theta_stress) if spec_code == 4 else 0.0
    params_list = [None] * len(stocks_is)
    prev_negll = np.inf
    history = []
    converged = False

    # Bounds (binary EAV magnitude is 0/1; |PC1| scale varies so wider bounds)
    # We determine |PC1| IS scale and set gamma_pc1 bound conservatively.
    bound_vix = (1e-9, 1e-3)
    bound_eav = (-1e-2, 1e-2)
    # gamma_pc1 bound scaled by 1/|PC1| scale; compute inside
    pc1_scale = np.mean([np.mean(st['abs_pc1']) for st in stocks_is])
    # we want gamma_pc1 * pc1_scale to be comparable to theta_eav (≈ 1e-4)
    # so gamma_pc1 ≈ 1e-4 / pc1_scale; bound allows ±100x
    gamma_pc1_bound_max = max(1e-2 / max(pc1_scale, 1e-6), 1e-2)
    bound_pc1 = (-gamma_pc1_bound_max, gamma_pc1_bound_max)
    bound_stress = (-10.0 / max(pc1_scale, 1e-6), 10.0 / max(pc1_scale, 1e-6))

    # Build shared-vector layout per spec
    def unpack(v):
        idx = 0
        tv = v[idx]; idx += 1
        te = v[idx] if spec_code in (1, 3, 4) else 0.0
        if spec_code in (1, 3, 4): idx += 1
        gp = v[idx] if spec_code in (2, 3, 4) else 0.0
        if spec_code in (2, 3, 4): idx += 1
        ts = v[idx] if spec_code == 4 else 0.0
        if spec_code == 4: idx += 1
        return tv, te, gp, ts

    def pack():
        v = [theta_vix]
        if spec_code in (1, 3, 4):
            v.append(theta_eav)
        if spec_code in (2, 3, 4):
            v.append(gamma_pc1)
        if spec_code == 4:
            v.append(theta_stress)
        return v

    def bounds():
        bs = [bound_vix]
        if spec_code in (1, 3, 4):
            bs.append(bound_eav)
        if spec_code in (2, 3, 4):
            bs.append(bound_pc1)
        if spec_code == 4:
            bs.append(bound_stress)
        return bs

    for outer in range(max_outer):
        if time_budget is not None and time.time() - t_start > time_budget:
            if verbose:
                print(f'    [BCD] outer {outer}: time budget reached')
            break
        total_negll = 0.0
        for i, st in enumerate(stocks_is):
            pi = params_list[i]
            p, ll = fit_one_stock_given_shared(
                st['r'], st['vix'], st['eav'], st['abs_pc1'],
                theta_vix, theta_eav, gamma_pc1, theta_stress, spec_code,
                init=pi,
            )
            if p is None:
                if params_list[i] is None:
                    raise RuntimeError(f'Stock {st["ticker"]} initial fit failed')
                continue
            params_list[i] = p
            total_negll += ll

        def obj(shared):
            tv, te, gp, ts = unpack(shared)
            return pooled_negll(stocks_is, params_list, tv, te, gp, ts, spec_code)

        res = optimize.minimize(
            obj, pack(), method='L-BFGS-B', bounds=bounds(),
            options={'maxiter': 200, 'ftol': 1e-10},
        )
        nv, ne, ng, ns = unpack(res.x)
        d_ll = prev_negll - res.fun
        if verbose:
            print(f'    [M{spec_code} BCD outer {outer}] '
                  f'θ_VIX={nv:.3e}, θ_EAV={ne:+.4e}, γ_PC1={ng:+.4e}, '
                  f'θ_stress={ns:+.4e}, pooled_negll={res.fun:.2f}, '
                  f'Δll={d_ll:+.4f}')
        history.append({
            'outer_iter': outer,
            'theta_vix': float(nv), 'theta_eav': float(ne),
            'gamma_pc1': float(ng), 'theta_stress': float(ns),
            'pooled_negll': float(res.fun),
        })
        theta_vix, theta_eav, gamma_pc1, theta_stress = (
            float(nv), float(ne), float(ng), float(ns)
        )
        if outer >= 1 and d_ll < 1e-2:
            converged = True
            if verbose:
                print(f'    [M{spec_code} BCD] converged')
            break
        prev_negll = res.fun

    # Final inner pass
    final_negll = 0.0
    final_params = []
    for i, st in enumerate(stocks_is):
        p, ll = fit_one_stock_given_shared(
            st['r'], st['vix'], st['eav'], st['abs_pc1'],
            theta_vix, theta_eav, gamma_pc1, theta_stress, spec_code,
            init=params_list[i],
        )
        if p is None:
            p = params_list[i]
            ll = per_stock_negll(p, st['r'], st['vix'], st['eav'],
                                  st['abs_pc1'],
                                  theta_vix, theta_eav, gamma_pc1, theta_stress,
                                  spec_code)
        final_params.append(p)
        final_negll += ll
    return {
        'spec_code': spec_code,
        'theta_vix': theta_vix,
        'theta_eav': theta_eav,
        'gamma_pc1': gamma_pc1,
        'theta_stress': theta_stress,
        'per_stock_params': [p.tolist() for p in final_params],
        'pooled_loglik': float(-final_negll),
        'pooled_negll': float(final_negll),
        'n_outer_iters': len(history),
        'converged': converged,
        'history': history,
        'pc1_scale_is_mean_abs': float(pc1_scale),
    }


def hessian_se_shared(stocks_is, fit, spec_code, param_name,
                       eps_scale=1e-3):
    """Hessian SE for one shared parameter (profile, holding per-stock
    params at their MLE). param_name ∈ {theta_eav, gamma_pc1, theta_stress}."""
    params_list = [np.array(p) for p in fit['per_stock_params']]
    tv = fit['theta_vix']
    te = fit['theta_eav']
    gp = fit['gamma_pc1']
    ts = fit['theta_stress']
    if param_name == 'theta_eav':
        base = te
        def f(x):
            return pooled_negll(stocks_is, params_list, tv, x, gp, ts, spec_code)
    elif param_name == 'gamma_pc1':
        base = gp
        def f(x):
            return pooled_negll(stocks_is, params_list, tv, te, x, ts, spec_code)
    elif param_name == 'theta_stress':
        base = ts
        def f(x):
            return pooled_negll(stocks_is, params_list, tv, te, gp, x, spec_code)
    else:
        raise ValueError(f'Unknown param_name {param_name}')

    eps = max(abs(base) * eps_scale, eps_scale * 1e-4)
    ll0 = f(base)
    ll_p = f(base + eps)
    ll_m = f(base - eps)
    h = (ll_p - 2 * ll0 + ll_m) / (eps ** 2)
    if h > 0 and np.isfinite(h):
        return float(np.sqrt(1.0 / h))
    return None


# ======================================================================
# Pure-GJR baseline
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


def forecast_pure_gjr(p, r):
    persist = p[1] + p[2] / 2.0 + p[3]
    sigma2 = np.empty(len(r))
    h = p[0] / (1.0 - persist) if persist < 0.999 else 1.0
    sigma2[0] = h
    for t in range(1, len(r)):
        u_prev = r[t - 1]
        asym = p[2] * u_prev * u_prev if u_prev < 0.0 else 0.0
        h = p[0] + p[1] * u_prev * u_prev + asym + p[3] * h
        if h < 1e-10:
            h = 1e-10
        sigma2[t] = h
    return sigma2


def qlike(sigma2, r2):
    sigma2 = np.maximum(sigma2, 1e-16)
    r2 = np.maximum(r2, 1e-16)
    return np.log(sigma2) + r2 / sigma2


def dm_hln(L1, L2):
    """One-sided DM-HLN (h=1) — returns (stat, p_one_m1_better)."""
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
    p_one_m1_better = float(stats.t.cdf(stat, df=T - 1))
    return float(stat), p_one_m1_better


# ======================================================================
# Panel DM (per-stock + stock-bootstrap)
# ======================================================================
def panel_dm(stocks_oos, fit_specA, fit_specB, specA_code, specB_code,
              label_a='A', label_b='B', rng_seed=123):
    """Panel DM (A vs B): negative means specA beats specB (QLIKE lower).
    Per-stock DM-HLN, stock-bootstrap panel t.
    """
    per_stock = []
    L_A_all, L_B_all = [], []
    for i, st in enumerate(stocks_oos):
        pA = np.array(fit_specA['per_stock_params'][i])
        pB = np.array(fit_specB['per_stock_params'][i])
        s2A = _forecast_sigma2_numba(
            pA[0], pA[1], pA[2], pA[3], pA[4],
            st['r'], st['vix'], st['eav'], st['abs_pc1'],
            fit_specA['theta_vix'], fit_specA['theta_eav'],
            fit_specA['gamma_pc1'], fit_specA['theta_stress'],
            specA_code,
        )
        s2B = _forecast_sigma2_numba(
            pB[0], pB[1], pB[2], pB[3], pB[4],
            st['r'], st['vix'], st['eav'], st['abs_pc1'],
            fit_specB['theta_vix'], fit_specB['theta_eav'],
            fit_specB['gamma_pc1'], fit_specB['theta_stress'],
            specB_code,
        )
        r2 = st['r'] ** 2
        L_A = qlike(s2A[1:], r2[1:])
        L_B = qlike(s2B[1:], r2[1:])
        s_i, p_i = dm_hln(L_A, L_B)
        per_stock.append({
            'ticker': st['ticker'],
            'dm_stat': s_i,
            'p_A_better': p_i,
            'mean_qlike_A': float(np.nanmean(L_A)),
            'mean_qlike_B': float(np.nanmean(L_B)),
            'A_wins': bool(np.nanmean(L_A) < np.nanmean(L_B)),
        })
        L_A_all.append(L_A)
        L_B_all.append(L_B)

    dm_stats = np.array([d['dm_stat'] for d in per_stock
                          if d['dm_stat'] is not None])
    n_valid = len(dm_stats)
    if n_valid < 5:
        return {
            'label_a': label_a, 'label_b': label_b,
            'n_stocks_valid': n_valid,
            'per_stock_dm': per_stock,
            'panel_dm_mean': None, 'panel_dm_t': None,
            'panel_dm_se_bootstrap': None,
            'panel_dm_ci_95': None,
            'panel_dm_one_sided_p_A_better': None,
        }
    mean_dm = float(np.mean(dm_stats))
    median_dm = float(np.median(dm_stats))
    rng_b = np.random.default_rng(rng_seed)
    boot = np.array([
        np.mean(rng_b.choice(dm_stats, size=n_valid, replace=True))
        for _ in range(N_STOCK_BOOTSTRAP)
    ])
    se_b = float(np.std(boot, ddof=1))
    t_panel = mean_dm / se_b if se_b > 0 else None
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    p_one = (float(np.mean(boot >= 0)) if mean_dm < 0
             else float(np.mean(boot <= 0)))
    n_indiv = int(np.sum(dm_stats <= -2.0))
    joint = (t_panel is not None and t_panel <= -2.0 and p_one < 0.05)
    return {
        'label_a': label_a, 'label_b': label_b,
        'n_stocks_valid': n_valid,
        'per_stock_dm': per_stock,
        'panel_dm_mean': mean_dm,
        'panel_dm_median': median_dm,
        'panel_dm_se_bootstrap': se_b,
        'panel_dm_t': t_panel,
        'panel_dm_ci_95': ci,
        'panel_dm_one_sided_p_A_better': p_one,
        'n_individual_dm_le_neg2': n_indiv,
        'joint_pass_harvey': joint,
        'mean_qlike_A_pooled': float(np.nanmean(np.concatenate(L_A_all))),
        'mean_qlike_B_pooled': float(np.nanmean(np.concatenate(L_B_all))),
    }


def panel_dm_vs_gjr(stocks_oos, fit_spec, spec_code,
                     gjr_params_list, label='M'):
    """Per-stock DM vs pure-GJR baseline (spec beats baseline = DM < 0)."""
    per_stock = []
    L_S_all, L_G_all = [], []
    for i, st in enumerate(stocks_oos):
        pS = np.array(fit_spec['per_stock_params'][i])
        s2S = _forecast_sigma2_numba(
            pS[0], pS[1], pS[2], pS[3], pS[4],
            st['r'], st['vix'], st['eav'], st['abs_pc1'],
            fit_spec['theta_vix'], fit_spec['theta_eav'],
            fit_spec['gamma_pc1'], fit_spec['theta_stress'],
            spec_code,
        )
        pG = gjr_params_list[i]
        if pG is None:
            continue
        s2G = forecast_pure_gjr(pG, st['r'])
        r2 = st['r'] ** 2
        L_S = qlike(s2S[1:], r2[1:])
        L_G = qlike(s2G[1:], r2[1:])
        s_i, p_i = dm_hln(L_S, L_G)
        per_stock.append({
            'ticker': st['ticker'],
            'dm_stat': s_i,
            'p_spec_better': p_i,
            'spec_wins': bool(np.nanmean(L_S) < np.nanmean(L_G)),
        })
        L_S_all.append(L_S)
        L_G_all.append(L_G)
    dm_stats = np.array([d['dm_stat'] for d in per_stock
                          if d['dm_stat'] is not None])
    n_valid = len(dm_stats)
    if n_valid < 5:
        return None
    mean_dm = float(np.mean(dm_stats))
    rng_b = np.random.default_rng(321)
    boot = np.array([
        np.mean(rng_b.choice(dm_stats, size=n_valid, replace=True))
        for _ in range(N_STOCK_BOOTSTRAP)
    ])
    se_b = float(np.std(boot, ddof=1))
    t_panel = mean_dm / se_b if se_b > 0 else None
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    p_one = (float(np.mean(boot >= 0)) if mean_dm < 0
             else float(np.mean(boot <= 0)))
    joint = (t_panel is not None and t_panel <= -2.0 and p_one < 0.05)
    return {
        'label': label,
        'n_stocks_valid': n_valid,
        'panel_dm_mean': mean_dm,
        'panel_dm_se_bootstrap': se_b,
        'panel_dm_t': t_panel,
        'panel_dm_ci_95': ci,
        'panel_dm_one_sided_p_spec_better': p_one,
        'joint_pass_harvey': joint,
        'mean_qlike_spec_pooled': float(np.nanmean(np.concatenate(L_S_all))),
        'mean_qlike_gjr_pooled': float(np.nanmean(np.concatenate(L_G_all))),
    }


# ======================================================================
# Main pipeline for one market
# ======================================================================
def run_market(market_name, stocks_loaded, data_start_for_market):
    print(f'\n{"#" * 72}')
    print(f'# MARKET: {market_name}  ({len(stocks_loaded)} stocks)')
    print(f'{"#" * 72}\n')

    # --- PCA factor construction (IS-only fit) ---
    print('[PCA] Fitting factor on IS-only panel returns ...')
    oos_start_ts = pd.Timestamp(OOS_START)
    pca = build_pca_factor(stocks_loaded, oos_start_ts, n_components=3)
    print(f'  IS days={pca["n_is_days"]}, OOS days={pca["n_oos_days"]}')
    print(f'  Explained var (IS): PC1={pca["explained_var_is"][0]:.3f}, '
          f'PC2={pca["explained_var_is"][1]:.3f}, '
          f'PC3={pca["explained_var_is"][2]:.3f}')

    factors = pca['factors']
    abs_pc1_series = factors['PC1'].abs()
    # Attach |PC1| to each stock, aligned on its date index
    for st in stocks_loaded:
        aligned = abs_pc1_series.reindex(st['index'], method='ffill')
        # Fill any residual NaN (at series start) with IS mean |PC1|
        mean_abs_pc1_is = float(
            abs_pc1_series.loc[abs_pc1_series.index < oos_start_ts].mean()
        )
        aligned = aligned.fillna(mean_abs_pc1_is)
        st['abs_pc1'] = aligned.values

    # --- IS/OOS split ---
    print('[split] IS/OOS by calendar date ...')
    is_stocks, oos_stocks = [], []
    for st in stocks_loaded:
        idx = st['index']
        mask_is = np.asarray(idx < oos_start_ts, dtype=bool)
        mask_oos = np.asarray(idx >= oos_start_ts, dtype=bool)
        if mask_is.sum() < 500 or mask_oos.sum() < 250:
            print(f'    {st["ticker"]}: skip (IS={int(mask_is.sum())}, '
                  f'OOS={int(mask_oos.sum())})')
            continue
        rec_is = {
            'ticker': st['ticker'],
            'r': st['r'][mask_is], 'vix': st['vix'][mask_is],
            'eav': st['eav'][mask_is], 'abs_pc1': st['abs_pc1'][mask_is],
            'index': idx[mask_is],
            'n_obs': int(mask_is.sum()),
            'n_events': int((st['eav'][mask_is] != 0).sum()),
        }
        rec_oos = {
            'ticker': st['ticker'],
            'r': st['r'][mask_oos], 'vix': st['vix'][mask_oos],
            'eav': st['eav'][mask_oos], 'abs_pc1': st['abs_pc1'][mask_oos],
            'index': idx[mask_oos],
            'n_obs': int(mask_oos.sum()),
            'n_events': int((st['eav'][mask_oos] != 0).sum()),
        }
        is_stocks.append(rec_is)
        oos_stocks.append(rec_oos)

    print(f'  IS stocks: {len(is_stocks)} / OOS stocks: {len(oos_stocks)}')
    print(f'  IS total obs: {sum(s["n_obs"] for s in is_stocks):,}')
    print(f'  OOS total obs: {sum(s["n_obs"] for s in oos_stocks):,}')

    # --- Fit M1/M2/M3/M4 ---
    fits = {}
    for spec_code, name in [(1, 'M1_EAV_only'), (2, 'M2_factor_only'),
                             (3, 'M3_both'), (4, 'M4_interaction')]:
        print(f'\n[IS fit {name}] ...')
        fit = fit_pooled_spec(is_stocks, spec_code)
        fits[name] = fit
        print(f'  → θ_VIX={fit["theta_vix"]:.3e}, '
              f'θ_EAV={fit["theta_eav"]:+.4e}, '
              f'γ_PC1={fit["gamma_pc1"]:+.4e}, '
              f'θ_stress={fit["theta_stress"]:+.4e}, '
              f'loglik={fit["pooled_loglik"]:.2f}')
        # Hessian SE for key shared params
        if spec_code in (1, 3, 4):
            se_eav = hessian_se_shared(is_stocks, fit, spec_code, 'theta_eav')
            fit['theta_eav_se_hessian'] = se_eav
            fit['theta_eav_t_hessian'] = (
                fit['theta_eav'] / se_eav if (se_eav and se_eav > 0)
                else None
            )
            print(f'  θ_EAV Hessian SE={se_eav}, t={fit["theta_eav_t_hessian"]}')
        if spec_code in (2, 3, 4):
            se_pc1 = hessian_se_shared(is_stocks, fit, spec_code, 'gamma_pc1')
            fit['gamma_pc1_se_hessian'] = se_pc1
            fit['gamma_pc1_t_hessian'] = (
                fit['gamma_pc1'] / se_pc1 if (se_pc1 and se_pc1 > 0)
                else None
            )
            print(f'  γ_PC1 Hessian SE={se_pc1}, '
                  f't={fit["gamma_pc1_t_hessian"]}')
        if spec_code == 4:
            se_st = hessian_se_shared(is_stocks, fit, spec_code, 'theta_stress')
            fit['theta_stress_se_hessian'] = se_st
            fit['theta_stress_t_hessian'] = (
                fit['theta_stress'] / se_st if (se_st and se_st > 0)
                else None
            )
            print(f'  θ_stress Hessian SE={se_st}, '
                  f't={fit["theta_stress_t_hessian"]}')

    # --- LRT tests (H1, H3) ---
    # H1: M3 vs M2 → does θ_EAV add incremental explanatory power?
    lr_h1 = 2 * (fits['M3_both']['pooled_loglik']
                  - fits['M2_factor_only']['pooled_loglik'])
    p_h1 = float(1.0 - stats.chi2.cdf(lr_h1, df=1)) if lr_h1 >= 0 else 1.0
    # H3: M4 vs M3 → is θ_stress significant?
    lr_h3 = 2 * (fits['M4_interaction']['pooled_loglik']
                  - fits['M3_both']['pooled_loglik'])
    p_h3 = float(1.0 - stats.chi2.cdf(lr_h3, df=1)) if lr_h3 >= 0 else 1.0
    # Also M1 vs M0-equivalent for reference: M3 vs M1 (factor incremental)
    lr_factor_inc = 2 * (fits['M3_both']['pooled_loglik']
                          - fits['M1_EAV_only']['pooled_loglik'])
    p_factor_inc = float(1.0 - stats.chi2.cdf(lr_factor_inc, df=1)) if lr_factor_inc >= 0 else 1.0

    print(f'\n[LRT] H1 M3 vs M2 (EAV incremental over factor): '
          f'LR={lr_h1:.3f}, p={p_h1:.4e}')
    print(f'[LRT] M3 vs M1 (factor incremental over EAV): '
          f'LR={lr_factor_inc:.3f}, p={p_factor_inc:.4e}')
    print(f'[LRT] H3 M4 vs M3 (EAV × |PC1| interaction): '
          f'LR={lr_h3:.3f}, p={p_h3:.4e}')

    # --- Pure-GJR baseline per stock for OOS reference ---
    print('\n[baseline] Fitting pure-GJR on IS per stock ...')
    gjr_params = []
    for st in is_stocks:
        p, _ = fit_pure_gjr(st['r'])
        gjr_params.append(p)

    # --- OOS DM comparisons ---
    print('\n[OOS] Panel DM M3 vs M2 (EAV incremental, factor controlled) ...')
    dm_m3_vs_m2 = panel_dm(oos_stocks, fits['M3_both'], fits['M2_factor_only'],
                            3, 2, label_a='M3', label_b='M2')
    if dm_m3_vs_m2['panel_dm_t'] is not None:
        print(f'  Panel DM t={dm_m3_vs_m2["panel_dm_t"]:.4f}, '
              f'p_one={dm_m3_vs_m2["panel_dm_one_sided_p_A_better"]:.4f}, '
              f'JOINT={dm_m3_vs_m2["joint_pass_harvey"]}')

    print('\n[OOS] Panel DM M3 vs M1 (factor incremental, EAV controlled) ...')
    dm_m3_vs_m1 = panel_dm(oos_stocks, fits['M3_both'], fits['M1_EAV_only'],
                            3, 1, label_a='M3', label_b='M1')

    print('\n[OOS] Panel DM M4 vs M3 (interaction incremental) ...')
    dm_m4_vs_m3 = panel_dm(oos_stocks, fits['M4_interaction'], fits['M3_both'],
                            4, 3, label_a='M4', label_b='M3')

    print('\n[OOS] Panel DM M1 vs GJR (EAV-only vs baseline, sanity) ...')
    dm_m1_vs_gjr = panel_dm_vs_gjr(oos_stocks, fits['M1_EAV_only'], 1,
                                     gjr_params, label='M1')
    print('\n[OOS] Panel DM M3 vs GJR (EAV+factor vs baseline) ...')
    dm_m3_vs_gjr = panel_dm_vs_gjr(oos_stocks, fits['M3_both'], 3,
                                     gjr_params, label='M3')

    return {
        'market': market_name,
        'n_is_stocks': len(is_stocks),
        'n_oos_stocks': len(oos_stocks),
        'n_is_obs': int(sum(s['n_obs'] for s in is_stocks)),
        'n_oos_obs': int(sum(s['n_obs'] for s in oos_stocks)),
        'n_is_events': int(sum(s['n_events'] for s in is_stocks)),
        'n_oos_events': int(sum(s['n_events'] for s in oos_stocks)),
        'pca': {
            'n_is_days': pca['n_is_days'],
            'n_oos_days': pca['n_oos_days'],
            'explained_var_is': pca['explained_var_is'],
            'pc1_loadings': pca['loadings']['PC1'].to_dict(),
        },
        'fits': {
            name: {
                'theta_vix': f['theta_vix'],
                'theta_eav': f['theta_eav'],
                'gamma_pc1': f['gamma_pc1'],
                'theta_stress': f['theta_stress'],
                'pooled_loglik': f['pooled_loglik'],
                'theta_eav_t_hessian': f.get('theta_eav_t_hessian'),
                'theta_eav_se_hessian': f.get('theta_eav_se_hessian'),
                'gamma_pc1_t_hessian': f.get('gamma_pc1_t_hessian'),
                'gamma_pc1_se_hessian': f.get('gamma_pc1_se_hessian'),
                'theta_stress_t_hessian': f.get('theta_stress_t_hessian'),
                'theta_stress_se_hessian': f.get('theta_stress_se_hessian'),
                'converged': f['converged'],
                'n_outer_iters': f['n_outer_iters'],
                'pc1_scale_is_mean_abs': f.get('pc1_scale_is_mean_abs'),
            }
            for name, f in fits.items()
        },
        'lrt': {
            'H1_M3_vs_M2': {'lr': lr_h1, 'df': 1, 'p_value': p_h1},
            'M3_vs_M1': {'lr': lr_factor_inc, 'df': 1, 'p_value': p_factor_inc},
            'H3_M4_vs_M3': {'lr': lr_h3, 'df': 1, 'p_value': p_h3},
        },
        'oos_dm': {
            'M3_vs_M2_panel_dm_t': dm_m3_vs_m2.get('panel_dm_t'),
            'M3_vs_M2_p_one': dm_m3_vs_m2.get('panel_dm_one_sided_p_A_better'),
            'M3_vs_M2_joint_pass': dm_m3_vs_m2.get('joint_pass_harvey'),
            'M3_vs_M2_detail': dm_m3_vs_m2,
            'M3_vs_M1_detail': dm_m3_vs_m1,
            'M4_vs_M3_detail': dm_m4_vs_m3,
            'M1_vs_GJR': dm_m1_vs_gjr,
            'M3_vs_GJR': dm_m3_vs_gjr,
        },
        '_is_stocks_for_plots': [{'ticker': s['ticker'],
                                   'n_events': s['n_events']}
                                  for s in is_stocks],
    }


# ======================================================================
# Main
# ======================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: Pooled EAV vs PCA systematic factor competition')
    print(f'{"=" * 72}\n')

    # --- Load US panel ---
    print('[1/3] Loading US panel ...')
    sur_dict = winsorize_surprises(load_us_surprises(US_TICKERS))
    us_stocks = []
    for tk in US_TICKERS:
        sdf = sur_dict.get(tk, pd.DataFrame())
        st = load_us_stock(tk, sdf, US_DATA_START)
        if st is not None:
            us_stocks.append(st)
    print(f'  Loaded {len(us_stocks)}/{len(US_TICKERS)} US stocks')

    # --- Load TW panel ---
    print('\n[2/3] Loading TW panel ...')
    tw_stocks = []
    for tk in TW_TICKERS:
        st = load_tw_stock(tk)
        if st is not None:
            tw_stocks.append(st)
    print(f'  Loaded {len(tw_stocks)}/{len(TW_TICKERS)} TW stocks')

    if len(us_stocks) < 15 or len(tw_stocks) < 15:
        print(f'ABORT: insufficient stocks US={len(us_stocks)}, '
              f'TW={len(tw_stocks)}')
        sys.exit(1)

    # --- Run both markets ---
    print('\n[3/3] Running absorption test on both markets ...')
    us_res = run_market('US', us_stocks, US_DATA_START)
    tw_res = run_market('TW', tw_stocks, TW_DATA_START)

    # --- Scenario determination ---
    # H1 PASS criteria (per market):
    #   IS: θ_EAV t ≥ Harvey (3.0)
    #   OOS: M3 vs M2 panel DM t ≤ -2 AND joint pass
    def h1_pass(res):
        m3 = res['fits']['M3_both']
        t_is = m3.get('theta_eav_t_hessian')
        oos_t = res['oos_dm']['M3_vs_M2_panel_dm_t']
        oos_joint = res['oos_dm']['M3_vs_M2_joint_pass']
        is_pass = (t_is is not None and t_is >= HARVEY_T_THRESHOLD)
        oos_pass = (oos_t is not None and oos_t <= OOS_DM_THRESHOLD
                    and oos_joint)
        return {
            'is_pass': is_pass,
            'oos_pass': oos_pass,
            'overall_pass': is_pass and oos_pass,
            't_is': t_is,
            'oos_t': oos_t,
            'oos_joint': oos_joint,
        }

    us_h1 = h1_pass(us_res)
    tw_h1 = h1_pass(tw_res)

    def h3_pass(res):
        t_stress = res['fits']['M4_interaction'].get('theta_stress_t_hessian')
        p_h3 = res['lrt']['H3_M4_vs_M3']['p_value']
        return {
            't_stress': t_stress,
            'lrt_p': p_h3,
            'pass': (t_stress is not None and abs(t_stress) >= 2.0
                     and p_h3 < 0.05),
        }

    us_h3 = h3_pass(us_res)
    tw_h3 = h3_pass(tw_res)

    if us_h1['overall_pass'] and tw_h1['overall_pass']:
        scenario = 'A'
    elif us_h1['overall_pass'] and not tw_h1['overall_pass']:
        scenario = 'B'
    elif not us_h1['overall_pass'] and not tw_h1['overall_pass']:
        scenario = 'C'
    else:
        scenario = 'B_flip'  # TW PASS, US FAIL (unlikely but possible)

    if us_h3['pass'] or tw_h3['pass']:
        scenario += '+D'

    # --- Verdict ---
    if scenario.startswith('A'):
        verdict = (
            f'Scenario A: θ_EAV survives factor control in BOTH markets '
            f'(US IS t={us_h1["t_is"]:.2f}, OOS DM={us_h1["oos_t"]:.2f}; '
            f'TW IS t={tw_h1["t_is"]:.2f}, OOS DM={tw_h1["oos_t"]:.2f}). '
            'Universal-magnitude is TRUE firm-event effect, not factor.'
        )
        paper2_impl = (
            'Paper 2 §5 narrative STRENGTHENED: "Earnings-day volatility is '
            'a firm-specific event effect orthogonal to the market factor. '
            'The universal-magnitude regularity survives PCA-based systematic '
            'risk control in both markets."'
        )
    elif scenario.startswith('B') and scenario != 'B_flip':
        verdict = (
            f'Scenario B: US PASS (IS t={us_h1["t_is"]:.2f}, '
            f'OOS DM={us_h1["oos_t"]:.2f}), TW FAIL '
            f'(IS t={tw_h1["t_is"]:.2f}, OOS DM={tw_h1["oos_t"]:.2f}). '
            'US universal-magnitude is real firm-event; TW IS identification '
            'was dominated by systematic factor.'
        )
        paper2_impl = (
            'Paper 2 §5 narrative should EMPHASIZE cross-market heterogeneity: '
            '"US earnings-day volatility is a genuine firm-event effect; '
            'Taiwan market earnings-day volatility is largely absorbed by '
            'the systematic factor, suggesting microstructure-dependent '
            'information processing."'
        )
    elif scenario.startswith('C'):
        verdict = (
            f'Scenario C: Both markets FAIL after factor control. '
            f'US IS t={us_h1["t_is"]:.2f}, OOS DM={us_h1["oos_t"]:.2f}; '
            f'TW IS t={tw_h1["t_is"]:.2f}, OOS DM={tw_h1["oos_t"]:.2f}. '
            'Universal-magnitude is FACTOR effect, not firm-event effect.'
        )
        paper2_impl = (
            'Paper 2 §5 narrative must be WEAKENED or REFRAMED: "Apparent '
            'universal-magnitude regularity is predominantly driven by '
            'systematic market factor; firm-event channel offers limited '
            'incremental predictive value once PC1 stress is controlled."'
        )
    else:  # B_flip
        verdict = (
            f'Scenario B_flip: TW PASS, US FAIL. Unusual. '
            f'US IS t={us_h1["t_is"]:.2f}, OOS DM={us_h1["oos_t"]:.2f}; '
            f'TW IS t={tw_h1["t_is"]:.2f}, OOS DM={tw_h1["oos_t"]:.2f}.'
        )
        paper2_impl = (
            'Paper 2 §5 narrative contradicts K1148_d2 US PASS; possibly '
            'PCA absorbs US market factor effect more than TW. Needs deeper '
            'diagnostic.'
        )

    if '+D' in scenario:
        verdict += (
            f' ADDITIONAL: EAV × |PC1| interaction SIGNIFICANT '
            f'(US t_stress={us_h3["t_stress"]}, TW t_stress={tw_h3["t_stress"]})'
            ' — EAV effect is conditional on market stress.'
        )
        paper2_impl += (
            ' Additional dimension: consider reframing §5 as "conditional '
            'firm-event effect amplified by systematic stress".'
        )

    print(f'\n{"=" * 72}')
    print(f'SCENARIO: {scenario}')
    print(f'VERDICT: {verdict}')
    print(f'PAPER 2 IMPLICATION: {paper2_impl}')
    print('=' * 72)

    # --- Plots ---
    print('\n[plots] Generating figures ...')

    # Plot 1: θ_EAV with vs without factor (4 panels: US-IS, US-OOS, TW-IS, TW-OOS)
    plot1_path = SCRIPT_DIR / 'theta_eav_with_vs_without_factor.png'
    fig, axes = plt.subplots(1, 4, figsize=(18, 5))

    # (a) IS θ_EAV t-stat (M1 vs M3) — US
    us_m1_t = us_res['fits']['M1_EAV_only']['theta_eav_t_hessian'] or 0
    us_m3_t = us_res['fits']['M3_both']['theta_eav_t_hessian'] or 0
    tw_m1_t = tw_res['fits']['M1_EAV_only']['theta_eav_t_hessian'] or 0
    tw_m3_t = tw_res['fits']['M3_both']['theta_eav_t_hessian'] or 0

    axes[0].bar(['M1\n(EAV only)', 'M3\n(EAV+factor)'], [us_m1_t, us_m3_t],
                 color=['steelblue', 'firebrick'], edgecolor='black', alpha=0.85)
    axes[0].axhline(HARVEY_T_THRESHOLD, color='black', linestyle='--',
                    label=f'Harvey t={HARVEY_T_THRESHOLD}')
    axes[0].axhline(0, color='gray', linestyle=':')
    axes[0].set_title('(a) US — IS θ_EAV t')
    axes[0].set_ylabel('θ_EAV t (Hessian)')
    axes[0].legend()

    axes[1].bar(['M1', 'M3'], [tw_m1_t, tw_m3_t],
                 color=['steelblue', 'firebrick'], edgecolor='black', alpha=0.85)
    axes[1].axhline(HARVEY_T_THRESHOLD, color='black', linestyle='--',
                    label=f'Harvey t={HARVEY_T_THRESHOLD}')
    axes[1].axhline(0, color='gray', linestyle=':')
    axes[1].set_title('(b) TW — IS θ_EAV t')
    axes[1].set_ylabel('θ_EAV t (Hessian)')
    axes[1].legend()

    # (c) OOS DM: M3 vs M2 (EAV incremental) for both markets
    us_dm = us_res['oos_dm']['M3_vs_M2_panel_dm_t'] or 0
    tw_dm = tw_res['oos_dm']['M3_vs_M2_panel_dm_t'] or 0
    axes[2].bar(['US', 'TW'], [us_dm, tw_dm],
                 color=['steelblue', 'firebrick'], edgecolor='black', alpha=0.85)
    axes[2].axhline(-2.0, color='black', linestyle='--', label='DM=-2')
    axes[2].axhline(0, color='gray', linestyle=':')
    axes[2].set_title('(c) OOS M3 vs M2 panel DM t\n(EAV incremental over factor)')
    axes[2].set_ylabel('panel DM t (lower = EAV incremental)')
    axes[2].legend()

    # (d) Scenario PASS/FAIL flag
    us_col = 'green' if us_h1['overall_pass'] else 'gray'
    tw_col = 'green' if tw_h1['overall_pass'] else 'gray'
    axes[3].bar(['US', 'TW'], [1 if us_h1['overall_pass'] else 0,
                                 1 if tw_h1['overall_pass'] else 0],
                 color=[us_col, tw_col], edgecolor='black', alpha=0.85)
    axes[3].set_ylim(-0.1, 1.3)
    axes[3].set_yticks([0, 1])
    axes[3].set_yticklabels(['FAIL', 'PASS'])
    axes[3].set_title(f'(d) H1 absorption (Scenario {scenario})')

    plt.suptitle(f'K1149: EAV absorption test vs PCA systematic factor '
                  f'(Scenario {scenario})', fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(plot1_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {plot1_path}')

    # Plot 2: PC1 loadings heatmap (proxy for market factor interpretation)
    plot2_path = SCRIPT_DIR / 'factor_loadings_matrix.png'
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))

    us_loadings = us_res['pca']['pc1_loadings']
    tw_loadings = tw_res['pca']['pc1_loadings']
    us_df = pd.DataFrame(us_loadings.items(), columns=['ticker', 'PC1'])
    us_df = us_df.sort_values('PC1', ascending=False)
    tw_df = pd.DataFrame(tw_loadings.items(), columns=['ticker', 'PC1'])
    tw_df = tw_df.sort_values('PC1', ascending=False)

    axes[0].barh(us_df['ticker'], us_df['PC1'], color='steelblue',
                 edgecolor='black', alpha=0.85)
    axes[0].set_title(f'(a) US PC1 loadings (IS, EV={us_res["pca"]["explained_var_is"][0]:.1%})')
    axes[0].set_xlabel('PC1 loading')
    axes[0].invert_yaxis()

    axes[1].barh(tw_df['ticker'], tw_df['PC1'], color='firebrick',
                 edgecolor='black', alpha=0.85)
    axes[1].set_title(f'(b) TW PC1 loadings (IS, EV={tw_res["pca"]["explained_var_is"][0]:.1%})')
    axes[1].set_xlabel('PC1 loading')
    axes[1].invert_yaxis()

    plt.suptitle('K1149: PC1 market-factor loadings (IS-only fit, no OOS leakage)',
                  fontsize=12, y=1.01)
    plt.tight_layout()
    plt.savefig(plot2_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {plot2_path}')

    # --- Save JSON (convert numpy to native for serialization) ---
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(x) for x in o]
        if isinstance(o, (np.integer, np.int64, np.int32)):
            return int(o)
        if isinstance(o, (np.floating, np.float64, np.float32)):
            return float(o) if np.isfinite(o) else None
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, np.ndarray):
            return [clean(x) for x in o.tolist()]
        if isinstance(o, pd.Timestamp):
            return o.isoformat()
        return o

    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Pooled EAV vs PCA-based systematic factor competition '
                 '(Paper 2 §5 absorption test)',
        'proposer': 'Claude (Paper 2 §5 universal-magnitude absorption test)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'oos_start': OOS_START,
        'data_end': DATA_END,
        'us_data_start': US_DATA_START,
        'tw_data_start': TW_DATA_START,
        'harvey_threshold': HARVEY_T_THRESHOLD,
        'oos_dm_threshold': OOS_DM_THRESHOLD,
        'n_stock_bootstrap_reps': N_STOCK_BOOTSTRAP,
        'us_market': us_res,
        'tw_market': tw_res,
        'h1_absorption': {
            'us': us_h1,
            'tw': tw_h1,
        },
        'h3_interaction': {
            'us': us_h3,
            'tw': tw_h3,
        },
        'scenario': scenario,
        'verdict': verdict,
        'paper2_implication': paper2_impl,
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    out = clean(out)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE VERDICT: {verdict}')
    print(f'  Paper 2 §5 implication: {paper2_impl}\n')


if __name__ == '__main__':
    main()
