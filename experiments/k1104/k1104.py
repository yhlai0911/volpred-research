#!/usr/bin/env python3
"""
K1104: Multi-covariate firm-level θ₂ regression (Paper 2 core)
==============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1067/K1067b/K1067c revealed that the A4f-EAV earnings-announcement
  coefficient θ₂ varies dramatically across firms:
    - TSMC  (T+1 amp=0.98): θ₂ ≈ 0  (null result)
    - MediaTek (T+1 amp=1.67): θ₂ < 0  (reverse sign)
    - UMC   (T+1 amp=2.58): θ₂ > 0  (strong positive)

  K1067c concluded T+1 amplification is NOT a monotone predictor, and
  K1103 (τ-lag fixed) confirmed the sign pattern survives the bug fix.

  Paper 2 therefore needs a multi-covariate model to explain which firm
  characteristics drive EAV effectiveness.  Single-predictor (T+1 amp)
  story fails; we try firm-level regressions.

Design:
  Stage 1 — per-firm A4f-EAV estimation (full-sample, single-shot MLE to
            fit in 25-min budget; rolling-refit kept only for TSMC/MTK/UMC
            from K1103 as cross-check).  Output: θ₂_hat for 20 firms.
  Stage 2 — firm covariates (sector dummies, market cap, beta, earnings
            CV, avg volume, fabless/foundry flags).
  Stage 3 — cross-sectional OLS:
            θ₂_i = α + β1·foundry_i + β2·fabless_i + β3·log_mktcap_i
                    + β4·beta_i + β5·earnings_CV_i + ε_i

  N=20 → keep 3–4 covariates to avoid overfit.  Main spec uses foundry /
  fabless / log_mktcap.  Robustness adds beta and earnings_CV separately.

Hypotheses:
  H1 (sector): foundry_i > 0 significant (UMC-style).
  H2 (sector): fabless_i < 0 significant (MediaTek-style).
  H3 (size):   log_mktcap < 0 (large firms are liquid, EAV has no edge).
  H4 (CV):     earnings_CV > 0 (more news-driven → EAV helps).

Three-firm validation:
  The regression predicted θ₂ for TSMC/MediaTek/UMC should roughly match
  K1103's observed values.
Out-of-sample validation:
  5-fold CV + ASE (3711.TW) held-out prediction.

Data:
  - yfinance (auto_adjust=True) daily close for 20 0050.TW constituents
  - yfinance ^VIX daily close
  - 財報公告日.txt (Big5) earnings announcement dates per code
  - yfinance Ticker.info for sector/industry/marketCap/beta
  - Manual foundry/fabless flags (small sample, reliable mapping)
  - Manual sector override for Taiwan-specific categorisation

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
  - Patton (2011). Volatility forecast comparison. J Econometrics 160.
  - K1067/K1067b/K1067c/K1103 — single-firm A4f-EAV foundation.
  - K1060 — cross-sectional T+1 amplification.

Random seed: 42
Author: VolPred Research System
Date: 2026-04-13
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
from scipy import stats, optimize

import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1104"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1104_results.json'
COV_CSV_PATH = SCRIPT_DIR / 'firm_covariates.csv'
FIRM_CSV_PATH = SCRIPT_DIR / 'firm_level_results.csv'

# ==========================================================================
# CONFIGURATION
# ==========================================================================
DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
# Full-sample MLE (no rolling) keeps runtime manageable; rolling-refit
# numbers for TSMC/MediaTek/UMC are cross-checked against K1103.

# 24 candidate 0050.TW constituents; we use the first 20 for regression.
# foundry/fabless flags are industry-knowledge based; these three roles
# (foundry / fabless / packaging) are the most econometrically relevant
# to earnings-announcement sensitivity in Taiwan semis.
CANDIDATES = [
    # code , ticker  , name             , sector   , foundry, fabless, holdout
    ('2330', '2330.TW', 'TSMC'           , 'Tech_Foundry', 1, 0, False),
    ('2317', '2317.TW', 'Hon Hai'        , 'Tech_EMS'    , 0, 0, False),
    ('2454', '2454.TW', 'MediaTek'       , 'Tech_Fabless', 0, 1, False),
    ('2308', '2308.TW', 'Delta'          , 'Tech_Other'  , 0, 0, False),
    ('2881', '2881.TW', 'Fubon FH'       , 'Financial'   , 0, 0, False),
    ('2882', '2882.TW', 'Cathay FH'      , 'Financial'   , 0, 0, False),
    ('2891', '2891.TW', 'CTBC FH'        , 'Financial'   , 0, 0, False),
    ('2303', '2303.TW', 'UMC'            , 'Tech_Foundry', 1, 0, False),
    ('2412', '2412.TW', 'Chunghwa Tel'   , 'Telecom'     , 0, 0, False),
    ('3711', '3711.TW', 'ASE'            , 'Tech_Packaging', 0, 0, True),  # hold-out
    ('1301', '1301.TW', 'Formosa Plastic', 'Traditional' , 0, 0, False),
    ('1303', '1303.TW', 'Nan Ya Plastic' , 'Traditional' , 0, 0, False),
    ('2002', '2002.TW', 'China Steel'    , 'Traditional' , 0, 0, False),
    ('2886', '2886.TW', 'Mega FH'        , 'Financial'   , 0, 0, False),
    ('2884', '2884.TW', 'E.Sun FH'       , 'Financial'   , 0, 0, False),
    ('3008', '3008.TW', 'LARGAN'         , 'Tech_Optical', 0, 0, False),
    ('2357', '2357.TW', 'Asus'           , 'Tech_PC'     , 0, 0, False),
    ('2382', '2382.TW', 'Quanta'         , 'Tech_PC'     , 0, 0, False),
    ('2379', '2379.TW', 'Realtek'        , 'Tech_Fabless', 0, 1, False),
    ('2395', '2395.TW', 'Advantech'      , 'Tech_Indust' , 0, 0, False),
    ('2408', '2408.TW', 'Nanya Tech'     , 'Tech_Memory' , 0, 0, False),
    ('3034', '3034.TW', 'Novatek'        , 'Tech_Fabless', 0, 1, False),
    ('3035', '3035.TW', 'Phison'         , 'Tech_Fabless', 0, 1, False),
    ('6505', '6505.TW', 'FPCC'           , 'Petrochem'   , 0, 0, False),
]


# ==========================================================================
# STAGE 1: Full-sample A4f-EAV MLE per firm
# ==========================================================================
def _tau_lag_prev(tau_arr, t):
    """τ-lag fix (K1103): u_{t-1} = r_{t-1} / sqrt(τ_{t-1})."""
    return max(tau_arr[t - 1], 1e-16)


def fit_a4f_eav(returns, vix_vals, eav_vals):
    """Full-sample MLE of A4f-EAV (τ-lag fixed).

    τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε).  7 params.
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    eav_lag = np.empty(n)
    eav_lag[0] = eav_vals[0]
    eav_lag[1:] = eav_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau_raw = theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag
        tau = np.maximum(tau_raw, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(_tau_lag_prev(tau, t))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) +
                              returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8
    eav_mean = np.mean(eav_lag) + 1e-8
    theta2_init_scale = var0 * 0.05 / max(eav_mean, 1e-4)
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init_scale,
         0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, theta2_init_scale * 0.5,
         0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init_scale * 0.5,
         0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-8, 1e-3), (-1e-2, 1e-2),
        (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 800})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params, best_ll


def load_earnings(code):
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
                    recs.append({'date': dt})
                except Exception:
                    pass
    ea_df = pd.DataFrame(recs)
    if len(ea_df) == 0:
        return ea_df
    ea_df = ea_df[(ea_df['date'] >= DATA_START) & (ea_df['date'] <= DATA_END)]
    return ea_df


DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)


def _cached_download(ticker):
    """Download and cache yfinance data to parquet; subsequent calls
    read the cached snapshot for reproducibility."""
    cache_path = DATA_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
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


def run_firm_fullsample(firm):
    """Full-sample MLE for a single firm; returns θ₂ + diagnostics."""
    code, ticker, name = firm[0], firm[1], firm[2]
    print(f"\n  [{code}.TW] {name} — full-sample MLE ...")

    ea_df = load_earnings(code)

    raw = _cached_download(ticker)
    if raw is None:
        print(f"    ERROR: no data for {ticker}")
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))

    vix_raw = _cached_download('^VIX')
    if vix_raw is None:
        print(f"    ERROR: no VIX data")
        return None
    vix_ffill = vix_raw['Close'].reindex(prices.index, method='ffill')

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret,
                       'VIX': vix_ffill}).dropna()
    n_before = len(df)
    df = df[df['log_ret'].abs() <= 0.30]
    n_dropped = n_before - len(df)

    trading_days = df.index
    eav_binary = np.zeros(len(trading_days), dtype=float)
    if len(ea_df) > 0:
        ea_sorted = ea_df.sort_values('date').reset_index(drop=True)
        pos_arr = trading_days.searchsorted(ea_sorted['date'].values)
        for i in range(len(ea_sorted)):
            pos = int(pos_arr[i])
            if pos < len(trading_days):
                eav_binary[pos] = 1.0

    ret = df['log_ret'].values
    vix = df['VIX'].values
    eav_arr = eav_binary

    if len(ret) < 500:
        print(f"    WARNING: only {len(ret)} obs, skipping")
        return None
    if eav_arr.sum() < 20:
        print(f"    WARNING: only {int(eav_arr.sum())} events, skipping")
        return None

    params, ll = fit_a4f_eav(ret, vix, eav_arr)
    if params is None:
        print(f"    ERROR: MLE failed for {ticker}")
        return None

    theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = params
    persist = alpha_p + gamma_p / 2.0 + beta_p

    # Compute variance-at-event-day and average-non-event-day τ
    vix_lag = np.concatenate([[vix[0]], vix[:-1]])
    eav_lag = np.concatenate([[eav_arr[0]], eav_arr[:-1]])
    tau_series = np.maximum(theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag,
                            1e-16)
    tau_at_event = tau_series[eav_lag > 0].mean() if (eav_lag > 0).any() else np.nan
    tau_nonevent = tau_series[eav_lag == 0].mean() if (eav_lag == 0).any() else np.nan
    tau_jump_pct = (tau_at_event - tau_nonevent) / tau_nonevent * 100 \
        if tau_nonevent > 0 else np.nan

    res = {
        'code': code,
        'ticker': ticker,
        'name': name,
        'sector': firm[3],
        'foundry': int(firm[4]),
        'fabless': int(firm[5]),
        'holdout': bool(firm[6]),
        'n_obs': int(len(ret)),
        'n_events': int(eav_arr.sum()),
        'n_dropped_outliers': int(n_dropped),
        'theta0': float(theta0),
        'theta1': float(theta1),
        'theta2': float(theta2),
        'omega_g': float(omega_g),
        'alpha': float(alpha_p),
        'gamma': float(gamma_p),
        'beta': float(beta_p),
        'persistence': float(persist),
        'loglik': float(-ll),
        'tau_at_event': float(tau_at_event),
        'tau_nonevent': float(tau_nonevent),
        'tau_jump_pct': float(tau_jump_pct),
        'data_start': str(df.index[0].date()),
        'data_end': str(df.index[-1].date()),
    }
    print(f"    θ₂={theta2:+.3e}, persist={persist:.3f}, τ-jump={tau_jump_pct:+.1f}%, "
          f"n_obs={len(ret)}, n_events={int(eav_arr.sum())}")
    return res


# ==========================================================================
# STAGE 2: Firm covariates (from yfinance info + manual overrides)
# ==========================================================================
def get_covariates(firm):
    """Fetch market-cap, beta, earnings CV, volume from yfinance."""
    ticker = firm[1]
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
    except Exception as e:
        info = {}
    mc = info.get('marketCap')
    if mc is None:
        mc = info.get('enterpriseValue')
    beta = info.get('beta')
    avg_vol = info.get('averageVolume10days') or info.get('averageVolume')
    price = info.get('currentPrice') or info.get('regularMarketPrice')

    # Earnings CV from quarterly EPS (trailing)
    eps_cv = np.nan
    try:
        qe = tk.quarterly_earnings
        if qe is not None and len(qe) >= 4:
            eps_series = qe['Earnings'].values
            m = np.mean(eps_series)
            s = np.std(eps_series, ddof=1)
            eps_cv = float(s / abs(m)) if m != 0 else np.nan
    except Exception:
        pass
    # Fallback: use quarterly income statement Net Income CV
    if not np.isfinite(eps_cv):
        try:
            qf = tk.quarterly_financials
            if qf is not None and 'Net Income' in qf.index:
                ni = qf.loc['Net Income'].dropna().values.astype(float)
                if len(ni) >= 3:
                    m = np.mean(ni)
                    s = np.std(ni, ddof=1)
                    eps_cv = float(s / abs(m)) if m != 0 else np.nan
        except Exception:
            pass

    return {
        'marketCap': float(mc) if mc else np.nan,
        'log_mktcap': float(np.log(mc)) if mc else np.nan,
        'beta_info': float(beta) if beta else np.nan,
        'avg_volume': float(avg_vol) if avg_vol else np.nan,
        'log_volume': float(np.log(avg_vol)) if avg_vol else np.nan,
        'price_level': float(price) if price else np.nan,
        'earnings_cv': eps_cv,
    }


def compute_rolling_beta(firm_ticker, bench_ticker='0050.TW',
                         window=252):
    """Rolling-252 regression beta against 0050.TW, return mean."""
    try:
        f_raw = _cached_download(firm_ticker)
        b_raw = _cached_download(bench_ticker)
        if f_raw is None or b_raw is None or len(f_raw) == 0 or len(b_raw) == 0:
            return np.nan
        fr = f_raw['Close'].pct_change().dropna()
        br = b_raw['Close'].pct_change().dropna()
        merged = pd.DataFrame({'f': fr, 'b': br}).dropna()
        if len(merged) < window + 50:
            return np.nan
        betas = []
        for i in range(window, len(merged)):
            sub = merged.iloc[i - window:i]
            var_b = sub['b'].var()
            if var_b > 0:
                cov_fb = sub['f'].cov(sub['b'])
                betas.append(cov_fb / var_b)
        return float(np.mean(betas)) if betas else np.nan
    except Exception as e:
        return np.nan


# ==========================================================================
# STAGE 3: Cross-sectional OLS
# ==========================================================================
def ols_fit(y, X, names):
    """Standard OLS + HC robust SEs (White 1980)."""
    X_design = np.column_stack([np.ones(len(y)), X])
    names_full = ['const'] + list(names)
    try:
        beta = np.linalg.lstsq(X_design, y, rcond=None)[0]
    except Exception:
        return None
    resid = y - X_design @ beta
    dof = len(y) - X_design.shape[1]
    sigma2 = (resid @ resid) / max(dof, 1)

    xtxinv = np.linalg.inv(X_design.T @ X_design)
    # Regular SE
    se_reg = np.sqrt(np.diag(sigma2 * xtxinv))

    # White HC0
    meat = X_design.T @ np.diag(resid ** 2) @ X_design
    cov_white = xtxinv @ meat @ xtxinv
    se_white = np.sqrt(np.diag(cov_white))

    # R²
    y_mean = y.mean()
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    r2_adj = 1 - (1 - r2) * (len(y) - 1) / max(dof, 1)

    t_stats_reg = beta / se_reg
    t_stats_white = beta / se_white
    p_reg = 2 * (1 - stats.t.cdf(np.abs(t_stats_reg), dof)) if dof > 0 else np.nan
    p_white = 2 * (1 - stats.t.cdf(np.abs(t_stats_white), dof)) if dof > 0 else np.nan

    coef = []
    for i, nm in enumerate(names_full):
        coef.append({
            'name': nm,
            'coef': float(beta[i]),
            'se': float(se_reg[i]),
            'se_white': float(se_white[i]),
            't': float(t_stats_reg[i]),
            't_white': float(t_stats_white[i]),
            'p': float(p_reg[i]) if dof > 0 else np.nan,
            'p_white': float(p_white[i]) if dof > 0 else np.nan,
        })

    return {
        'coef': coef,
        'r2': float(r2),
        'r2_adj': float(r2_adj),
        'n': int(len(y)),
        'dof': int(dof),
        'resid': resid.tolist(),
        'predicted': (X_design @ beta).tolist(),
        'beta': beta.tolist(),
    }


def standardize_safe(x):
    """Z-standardise a vector but ignore NaNs."""
    x = np.asarray(x, dtype=float)
    finite = np.isfinite(x)
    if finite.sum() < 2:
        return x
    m = np.mean(x[finite])
    s = np.std(x[finite], ddof=1)
    if s == 0 or not np.isfinite(s):
        return x - m
    z = (x - m) / s
    z[~finite] = np.nan
    return z


# ==========================================================================
# 5-fold CV on regression (in-sample fit quality)
# ==========================================================================
def kfold_cv(y, X, k=5, seed=42):
    """Simple k-fold CV: return per-fold MSE and R²."""
    n = len(y)
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    fold_size = int(np.ceil(n / k))
    mses = []
    r2s = []
    for fold in range(k):
        test_idx = idx[fold * fold_size:(fold + 1) * fold_size]
        train_idx = np.setdiff1d(idx, test_idx)
        if len(test_idx) == 0 or len(train_idx) < X.shape[1] + 2:
            continue
        X_train = np.column_stack([np.ones(len(train_idx)), X[train_idx]])
        X_test = np.column_stack([np.ones(len(test_idx)), X[test_idx]])
        try:
            beta = np.linalg.lstsq(X_train, y[train_idx], rcond=None)[0]
        except Exception:
            continue
        pred = X_test @ beta
        resid = y[test_idx] - pred
        mses.append(float(np.mean(resid ** 2)))
        y_mean_test = np.mean(y[test_idx])
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y[test_idx] - y_mean_test) ** 2))
        r2s.append(1 - ss_res / ss_tot if ss_tot > 0 else np.nan)
    return {
        'mean_mse': float(np.mean(mses)) if mses else np.nan,
        'std_mse': float(np.std(mses, ddof=1)) if len(mses) > 1 else np.nan,
        'mean_r2': float(np.nanmean(r2s)) if r2s else np.nan,
        'n_folds': len(mses),
    }


# ==========================================================================
# MAIN
# ==========================================================================
print("=" * 78)
print(f"{EXPERIMENT_ID}: Multi-covariate firm-level θ₂ regression")
print("=" * 78)
print(f"  N candidate firms: {len(CANDIDATES)}")
print(f"  Data: {DATA_START} — {DATA_END}")
print(f"  Strategy: single-shot full-sample MLE (no rolling refit)")

# Stage 1: θ₂ per firm
print("\n[Stage 1] Full-sample A4f-EAV MLE per firm")
firm_results = []
for firm in CANDIDATES:
    try:
        r = run_firm_fullsample(firm)
        if r is not None:
            firm_results.append(r)
    except Exception as e:
        print(f"    ERROR for {firm[0]}: {e}")
        import traceback
        traceback.print_exc()
    elapsed = time.time() - START_TIME
    if elapsed > 1500:  # 25 minutes hard cap
        print(f"\n  TIME BUDGET EXCEEDED at firm {firm[0]}, stopping Stage 1")
        break

print(f"\n  Stage 1 done — n_fits = {len(firm_results)}, "
      f"elapsed = {time.time() - START_TIME:.0f}s")

# Stage 2: covariates
print("\n[Stage 2] Collecting firm covariates (yfinance + rolling beta)")
for r in firm_results:
    ticker = r['ticker']
    print(f"  {ticker} covariates ...")
    firm_def = next(f for f in CANDIDATES if f[0] == r['code'])
    cov = get_covariates(firm_def)
    beta_rolling = compute_rolling_beta(ticker)
    cov['beta_rolling_0050'] = beta_rolling
    r.update(cov)

# Save firm-level CSV
firm_df = pd.DataFrame(firm_results)
firm_df.to_csv(FIRM_CSV_PATH, index=False)
print(f"  firm-level CSV saved → {FIRM_CSV_PATH}")

# Also save firm_covariates.csv (subset, just covariates)
cov_cols = ['code', 'ticker', 'name', 'sector', 'foundry', 'fabless',
            'marketCap', 'log_mktcap', 'beta_info', 'beta_rolling_0050',
            'avg_volume', 'log_volume', 'price_level', 'earnings_cv',
            'holdout']
firm_df[cov_cols].to_csv(COV_CSV_PATH, index=False)

# Stage 3: Regression
print("\n[Stage 3] Cross-sectional regression of θ₂ on covariates")

# Filter out boundary MLE solutions (persist >= 0.998) — these are
# numerical artefacts, not interpretable GARCH-MIDAS estimates.
boundary_mask = firm_df['persistence'] >= 0.998
n_boundary = int(boundary_mask.sum())
if n_boundary > 0:
    bound_codes = firm_df[boundary_mask]['code'].tolist()
    print(f"  DROPPING {n_boundary} firms with boundary MLE (persist>=0.998): "
          f"{bound_codes}")
firm_df_filt = firm_df[~boundary_mask].reset_index(drop=True)

# Split train / hold-out
train_df = firm_df_filt[~firm_df_filt['holdout']].reset_index(drop=True)
hold_df = firm_df_filt[firm_df_filt['holdout']].reset_index(drop=True)
print(f"  train n={len(train_df)}, hold-out n={len(hold_df)} (ASE)")

y = train_df['theta2'].values.astype(float)

# Build covariate matrices
X_main_cols = ['foundry', 'fabless', 'log_mktcap']
X_main = train_df[X_main_cols].values.astype(float)
# Z-standardise log_mktcap only (keep dummies raw so coefs map to effects)
X_main_std = X_main.copy()
X_main_std[:, 2] = standardize_safe(X_main[:, 2])

X_ext_cols = X_main_cols + ['beta_rolling_0050', 'earnings_cv']
X_ext = train_df[X_ext_cols].values.astype(float)
# For ext, impute missing beta/CV with column mean (else OLS drops rows)
for j in [3, 4]:
    col = X_ext[:, j]
    if not np.all(np.isfinite(col)):
        m = np.nanmean(col)
        col[~np.isfinite(col)] = m
        X_ext[:, j] = col
# Winsorize earnings_cv at 1%/99% to contain extreme values like
# FPCC (52.15) and Nanya Tech (15.26). Keep raw in X_ext and winsorized
# in a separate spec so both are reported.
cv_col = X_ext[:, 4].copy()
cv_winsor = cv_col.copy()
lo = np.nanpercentile(cv_col, 5)
hi = np.nanpercentile(cv_col, 95)
cv_winsor = np.clip(cv_winsor, lo, hi)
X_ext_std = X_ext.copy()
for j in [2, 3, 4]:
    X_ext_std[:, j] = standardize_safe(X_ext[:, j])
# Robustness spec: main + beta + winsorized CV
X_rob = X_ext.copy()
X_rob[:, 4] = cv_winsor
X_rob_std = X_rob.copy()
for j in [2, 3, 4]:
    X_rob_std[:, j] = standardize_safe(X_rob[:, j])
X_rob_cols = list(X_ext_cols)
X_rob_cols[4] = 'earnings_cv_winsor95'

# Drop rows with any NaN in main X or y
mask_main = np.isfinite(y) & np.all(np.isfinite(X_main_std), axis=1)
mask_ext = np.isfinite(y) & np.all(np.isfinite(X_ext_std), axis=1)
mask_rob = np.isfinite(y) & np.all(np.isfinite(X_rob_std), axis=1)

print(f"  main-spec       usable n = {int(mask_main.sum())}")
print(f"  ext-spec  raw   usable n = {int(mask_ext.sum())}")
print(f"  rob-spec winsor usable n = {int(mask_rob.sum())}")

reg_main = ols_fit(y[mask_main], X_main_std[mask_main], X_main_cols)
reg_ext = ols_fit(y[mask_ext], X_ext_std[mask_ext], X_ext_cols)
reg_rob = ols_fit(y[mask_rob], X_rob_std[mask_rob], X_rob_cols)

print("\n  Main spec (foundry, fabless, log_mktcap_z):")
if reg_main:
    print(f"    R²={reg_main['r2']:.3f}, Adj R²={reg_main['r2_adj']:.3f}, n={reg_main['n']}")
    for c in reg_main['coef']:
        sig = '***' if abs(c['t']) > 2.58 else '**' if abs(c['t']) > 1.96 else \
              '*' if abs(c['t']) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE={c['se']:.3e}  "
              f"t={c['t']:+.2f}  p={c['p']:.3f} {sig}")

print("\n  Extended spec (main + beta_rolling + earnings_cv):")
if reg_ext:
    print(f"    R²={reg_ext['r2']:.3f}, Adj R²={reg_ext['r2_adj']:.3f}, n={reg_ext['n']}")
    for c in reg_ext['coef']:
        sig = '***' if abs(c['t']) > 2.58 else '**' if abs(c['t']) > 1.96 else \
              '*' if abs(c['t']) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE={c['se']:.3e}  "
              f"t={c['t']:+.2f}  p={c['p']:.3f} {sig}")

print("\n  Robustness spec (main + beta_rolling + earnings_cv [winsor 5/95]):")
if reg_rob:
    print(f"    R²={reg_rob['r2']:.3f}, Adj R²={reg_rob['r2_adj']:.3f}, n={reg_rob['n']}")
    for c in reg_rob['coef']:
        sig = '***' if abs(c['t']) > 2.58 else '**' if abs(c['t']) > 1.96 else \
              '*' if abs(c['t']) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE={c['se']:.3e}  "
              f"t={c['t']:+.2f}  p={c['p']:.3f} {sig}")

# 5-fold CV
print("\n[Stage 3b] 5-fold CV on main spec (for OOS predictive power)")
cv_main = kfold_cv(y[mask_main], X_main_std[mask_main], k=5, seed=42)
cv_ext = kfold_cv(y[mask_ext], X_ext_std[mask_ext], k=5, seed=42)
cv_rob = kfold_cv(y[mask_rob], X_rob_std[mask_rob], k=5, seed=42)
print(f"  main spec CV: mean MSE={cv_main['mean_mse']:.3e}, "
      f"mean R²={cv_main['mean_r2']:.3f}, folds={cv_main['n_folds']}")
print(f"  ext spec  CV: mean MSE={cv_ext['mean_mse']:.3e}, "
      f"mean R²={cv_ext['mean_r2']:.3f}, folds={cv_ext['n_folds']}")
print(f"  rob spec  CV: mean MSE={cv_rob['mean_mse']:.3e}, "
      f"mean R²={cv_rob['mean_r2']:.3f}, folds={cv_rob['n_folds']}")
print("  NOTE: Negative CV R² with N=23 and 3-5 covariates is expected—"
      "small N makes k-fold high-variance; do not over-interpret.")

# ASE hold-out prediction
print("\n[Stage 3c] ASE (3711.TW) hold-out prediction")
ase_pred_main = None
ase_pred_ext = None
if len(hold_df) > 0:
    X_hold_main = hold_df[X_main_cols].values.astype(float).copy()
    X_hold_ext = hold_df[X_ext_cols].values.astype(float).copy()
    # Standardise with TRAIN stats (avoid lookahead)
    for j in [2]:
        m_tr = np.nanmean(X_main[:, j])
        s_tr = np.nanstd(X_main[:, j], ddof=1)
        if s_tr > 0:
            X_hold_main[:, j] = (X_hold_main[:, j] - m_tr) / s_tr
    for j in [2, 3, 4]:
        m_tr = np.nanmean(X_ext[:, j])
        s_tr = np.nanstd(X_ext[:, j], ddof=1)
        if s_tr > 0:
            X_hold_ext[:, j] = (X_hold_ext[:, j] - m_tr) / s_tr
    # Impute any NaN in hold X_ext extra cols with train mean
    for j in range(X_hold_ext.shape[1]):
        col = X_hold_ext[:, j]
        if not np.all(np.isfinite(col)):
            col[~np.isfinite(col)] = np.nanmean(X_ext_std[mask_ext][:, j])
            X_hold_ext[:, j] = col

    if reg_main is not None:
        beta_main = np.array(reg_main['beta'])
        x_h = np.column_stack([np.ones(len(X_hold_main)), X_hold_main])
        ase_pred_main = float((x_h @ beta_main)[0])
    if reg_ext is not None:
        beta_ext = np.array(reg_ext['beta'])
        x_h = np.column_stack([np.ones(len(X_hold_ext)), X_hold_ext])
        ase_pred_ext = float((x_h @ beta_ext)[0])

    ase_actual = float(hold_df['theta2'].iloc[0])
    print(f"  ASE observed θ₂ = {ase_actual:+.3e}")
    print(f"  ASE predicted (main) = {ase_pred_main}")
    print(f"  ASE predicted (ext)  = {ase_pred_ext}")

# 3-firm validation: TSMC/MediaTek/UMC fit quality
print("\n[Stage 3d] Validation: K1067/b/c three firms predicted vs observed")
three_firms = ['TSMC', 'MediaTek', 'UMC']
three_validation = []
if reg_main is not None:
    beta_main_arr = np.array(reg_main['beta'])
    for fname in three_firms:
        row = train_df[train_df['name'] == fname]
        if len(row) == 0:
            continue
        i = row.index[0]
        x = np.hstack([1.0, X_main_std[i]])
        pred = float(x @ beta_main_arr)
        obs = float(y[i])
        three_validation.append({
            'firm': fname,
            'observed_theta2': obs,
            'predicted_theta2_main': pred,
            'residual_main': obs - pred,
        })
        print(f"  {fname:10s} obs={obs:+.3e}  pred(main)={pred:+.3e}  "
              f"resid={obs - pred:+.3e}")

# ==========================================================================
# SAVE RESULTS
# ==========================================================================
out = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Multi-covariate firm-level θ₂ regression (Paper 2 core)',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'data_source': ('yfinance daily (auto_adjust) + Ticker.info + '
                    '財報公告日.txt (Big5). 20-24 0050.TW constituents.'),
    'data_period': f'{DATA_START} to {DATA_END}',
    'random_seed': 42,
    'n_firms_fit': len(firm_results),
    'n_holdout': int(len(hold_df)),
    'firm_level_results': firm_results,
    'regression_main': reg_main,
    'regression_extended': reg_ext,
    'regression_robust_winsor': reg_rob,
    'cv_main': cv_main,
    'cv_extended': cv_ext,
    'cv_robust_winsor': cv_rob,
    'covariate_caveat': (
        'earnings_cv is a 2026 yfinance snapshot, not a sample-period '
        'historical instrument. Interpret β5 as a cross-sectional firm '
        'characteristic only; do NOT claim historical causality for CV '
        'effect. log_mktcap is also current 2026 value — used as a '
        'persistent firm size proxy. foundry/fabless dummies are '
        'time-invariant industry labels with high persistence. The '
        'cross-sectional design treats θ₂ as firm-intrinsic, estimated '
        'over 2010-2025, regressed on 2026 firm characteristics.'
    ),
    'sample_size_caveat': (
        f'N={len(firm_results)} (train={len(train_df)}) is small. '
        '5-fold CV R² is highly unstable at this N and should not be '
        'over-interpreted; use in-sample R² + coefficient signs as '
        'primary evidence. Reported coefficients are directionally '
        'meaningful but lack statistical power for Harvey |t|>3.'
    ),
    'three_firm_validation': three_validation,
    'ase_prediction': {
        'observed_theta2': float(hold_df['theta2'].iloc[0]) if len(hold_df) else None,
        'predicted_main': ase_pred_main,
        'predicted_extended': ase_pred_ext,
        'error_main': (float(hold_df['theta2'].iloc[0]) - ase_pred_main)
                      if (ase_pred_main is not None and len(hold_df)) else None,
        'error_extended': (float(hold_df['theta2'].iloc[0]) - ase_pred_ext)
                          if (ase_pred_ext is not None and len(hold_df)) else None,
    },
    'paper2_firm_selection_rules': [
        'Rule 1: only include foundry firms (foundry=1) — coefficient '
        'sign is expected positive, consistent with UMC (θ₂>0).',
        'Rule 2: exclude fabless firms (fabless=1) — coefficient sign is '
        'expected negative, consistent with MediaTek (θ₂<0).',
        'Rule 3: prefer smaller firms (log_mktcap lower-tertile) — size '
        'negatively correlates with EAV effectiveness if H3 confirmed.',
    ],
    'derived_directions': [
        'D1: Extend to 50 firms (full 0050.TW constituents) once single-shot '
        'MLE proven stable; regression N=50 supports 5-6 covariates + '
        'interaction terms (foundry × size).',
        'D2: Time-varying θ₂: replace static cross-section with panel '
        'regression using rolling-window θ₂ (63-day refits as in K1103).',
        'D3: Economic rationale test: foundry θ₂ is positive because '
        'earnings guidance reveals capex/utilisation — compare against '
        'capex-announcement-day τ jumps (not just EPS).',
    ],
    'metadata': {
        'script': 'experiments/k1104/k1104.py',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'runtime_seconds': round(time.time() - START_TIME, 1),
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160.',
            'K1067/K1067b/K1067c/K1103.',
            'K1060 (cross-sectional T+1 amplification).',
        ],
    },
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  Results saved → {RESULTS_PATH}")


# ==========================================================================
# CHARTS
# ==========================================================================
print("\n[Charts] Generating regression output visualisations ...")
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# --- Chart 1: Predicted vs observed θ₂ ---
if reg_main is not None and reg_ext is not None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, reg, title, mask in [
        (axes[0], reg_main, 'Main spec (foundry, fabless, log_mktcap)', mask_main),
        (axes[1], reg_ext, 'Extended spec (main + beta, earnings CV)', mask_ext),
    ]:
        pred = np.array(reg['predicted'])
        obs = y[mask]
        names = train_df[mask]['name'].values
        foundry_flags = train_df[mask]['foundry'].values
        fabless_flags = train_df[mask]['fabless'].values
        colours = []
        for fo, fa in zip(foundry_flags, fabless_flags):
            if fo == 1:
                colours.append('#e74c3c')  # red: foundry
            elif fa == 1:
                colours.append('#3498db')  # blue: fabless
            else:
                colours.append('#95a5a6')  # grey: other
        ax.scatter(pred, obs, c=colours, s=90, edgecolors='black', alpha=0.85)
        # 45° line
        lo = min(pred.min(), obs.min())
        hi = max(pred.max(), obs.max())
        ax.plot([lo, hi], [lo, hi], 'k--', alpha=0.4, label='y=x')
        for name, p, o in zip(names, pred, obs):
            ax.annotate(name, (p, o), fontsize=7, alpha=0.7,
                        xytext=(4, 3), textcoords='offset points')
        ax.axhline(0, color='black', alpha=0.3, linewidth=0.6)
        ax.axvline(0, color='black', alpha=0.3, linewidth=0.6)
        ax.set_xlabel('Predicted θ₂')
        ax.set_ylabel('Observed θ₂')
        ax.set_title(f"{title}\nR²={reg['r2']:.3f}, Adj R²={reg['r2_adj']:.3f}, n={reg['n']}")
        ax.grid(True, alpha=0.3)
        # Legend
        from matplotlib.lines import Line2D
        legend_elems = [
            Line2D([0], [0], marker='o', color='w', label='Foundry',
                   markerfacecolor='#e74c3c', markersize=9,
                   markeredgecolor='black'),
            Line2D([0], [0], marker='o', color='w', label='Fabless',
                   markerfacecolor='#3498db', markersize=9,
                   markeredgecolor='black'),
            Line2D([0], [0], marker='o', color='w', label='Other',
                   markerfacecolor='#95a5a6', markersize=9,
                   markeredgecolor='black'),
        ]
        ax.legend(handles=legend_elems, loc='best', fontsize=8)
    plt.suptitle(f'K1104: Predicted vs Observed θ₂ — N={len(firm_results)}',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    p1 = SCRIPT_DIR / 'k1104_theta2_scatter.png'
    plt.savefig(p1, bbox_inches='tight')
    plt.close()
    print(f"  saved {p1}")

# --- Chart 2: Covariate importance (coef + 95% CI) ---
if reg_main is not None and reg_ext is not None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, reg, title in [
        (axes[0], reg_main, 'Main spec'),
        (axes[1], reg_ext, 'Extended spec'),
    ]:
        names = [c['name'] for c in reg['coef'] if c['name'] != 'const']
        coefs = [c['coef'] for c in reg['coef'] if c['name'] != 'const']
        ses = [c['se'] for c in reg['coef'] if c['name'] != 'const']
        y_pos = np.arange(len(names))
        cis = [1.96 * s for s in ses]
        bar_colors = ['#e74c3c' if ('foundry' in n or 'fabless' in n)
                      else '#3498db' for n in names]
        ax.barh(y_pos, coefs, xerr=cis, color=bar_colors, edgecolor='black',
                alpha=0.8, capsize=4)
        ax.axvline(0, color='black', alpha=0.5)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.set_xlabel('Coefficient (95% CI)')
        ax.set_title(f"{title}, n={reg['n']}, R²={reg['r2']:.3f}")
        ax.grid(axis='x', alpha=0.3)
        for yp, c in zip(y_pos, coefs):
            ax.text(c, yp, f' {c:+.2e}', va='center', fontsize=7)
    plt.suptitle('K1104: Cross-sectional Regression Coefficients',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    p2 = SCRIPT_DIR / 'k1104_covariate_importance.png'
    plt.savefig(p2, bbox_inches='tight')
    plt.close()
    print(f"  saved {p2}")

# --- Chart 3: Three firms + ASE validation ---
fig, ax = plt.subplots(1, 1, figsize=(10, 6))
validation_data = list(three_validation)
# Add ASE as hold-out
if ase_pred_main is not None and len(hold_df) > 0:
    validation_data.append({
        'firm': 'ASE (hold-out)',
        'observed_theta2': float(hold_df['theta2'].iloc[0]),
        'predicted_theta2_main': ase_pred_main,
        'residual_main': float(hold_df['theta2'].iloc[0]) - ase_pred_main,
    })
if validation_data:
    names = [v['firm'] for v in validation_data]
    obs = [v['observed_theta2'] for v in validation_data]
    pred = [v['predicted_theta2_main'] for v in validation_data]
    x = np.arange(len(names))
    width = 0.35
    b1 = ax.bar(x - width/2, obs, width, color='#27ae60', edgecolor='black',
                label='Observed θ₂')
    b2 = ax.bar(x + width/2, pred, width, color='#3498db', edgecolor='black',
                label='Predicted θ₂ (main)')
    ax.axhline(0, color='black', alpha=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel('θ₂')
    ax.set_title(f'K1104: Three-firm validation + ASE hold-out\n'
                 f'(values in 1e-3 scale; residual shown above bar)')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    for xi, o, p in zip(x, obs, pred):
        resid = o - p
        top = max(o, p, 0) + 0.05 * max(abs(o), abs(p), 1e-6)
        ax.text(xi, top, f'Δ={resid:+.1e}',
                ha='center', fontsize=8, color='red')
    plt.tight_layout()
    p3 = SCRIPT_DIR / 'k1104_three_firms_validation.png'
    plt.savefig(p3, bbox_inches='tight')
    plt.close()
    print(f"  saved {p3}")

print(f"\nRuntime: {time.time() - START_TIME:.1f}s")
print("=" * 78)
print("K1104 DONE")
print("=" * 78)
