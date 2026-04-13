#!/usr/bin/env python3
"""
K1109: Pre-registered random sector sample (confirmatory)
=========================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1106b found "fabless β=-2.29e-3, p=0.004 ***" with a hypothesis-
  driven (cherry-picked) sample of 14 firms. In the fabless bucket it
  only included MediaTek + Realtek (both known-negative from K1067c),
  dropping Novatek/Phison which have POSITIVE θ₂ in K1104. E052 flagged
  this as cherry-pick bias: the "confirmation" just re-estimates an
  already-negative subsample.

  K1109 fixes this with strict pre-registration:
    • Sample locked in `prereg_sample.json` BEFORE any estimation.
    • Each sector pool decided before looking at results.
    • Random draws with numpy.default_rng(seed=42).
    • N≈32 across 8 sectors (vs 14/7 in K1106b).

  This is a CONFIRMATORY test, not exploratory — result is what it is.

Design (pre-registered, identical methodology to K1106b Stage 1):
  Stage 1: per-firm A4f-EAV MLE (full-sample, deterministic).
  Stage 2: firm covariates — log_mktcap, beta_rolling_0050,
           earnings_freq_per_year (new relative to K1106b).
  Stage 3: Cross-sectional OLS + joint ANOVA F-test on *all* sector
           dummies (not individual hypothesis), Bonferroni/BH adjusted.
           Bootstrap 5000-rep 95% CI per sector (cluster by firm).
           Cross-validation: K1104∩K1106b∩K1109 shared firms as OOS.

Pre-registered hypotheses (LOCKED before estimation):
  H1 (joint): ANOVA F-test p<0.05 AND BH-adjusted remains significant.
  H2 (fabless vs foundry): t-test coefficient p<0.05 AND β<0.
  H3 (shipping = 0): bootstrap 95% CI overlaps 0 either direction.

Data:
  - yfinance daily (auto_adjust=True) close, 2010-2025.
  - yfinance ^VIX close.
  - 財報公告日.txt earnings announcement dates.
  - yfinance Ticker.info for marketCap.
  - 0050.TW as beta benchmark.
  - Parquet cache from K1104 + K1106b copied into experiments/k1109/data.

Expected runtime: 20-30 min (32 firms × ~25s MLE + ~15 downloads).

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
  - Patton (2011). Volatility forecast comparison. J Econometrics 160.
  - Benjamini & Hochberg (1995). JRSS B 57(1) — FDR adjustment.
  - K1067/K1103/K1104/K1106b — prior EAV and heterogeneity work.

Random seed: 42.
Author: VolPred Research System.
Date: 2026-04-13.
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
GLOBAL_RNG = np.random.default_rng(42)

START_TIME = time.time()
EXPERIMENT_ID = 'K1109'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
PREREG_PATH = SCRIPT_DIR / 'prereg_sample.json'
RESULTS_PATH = SCRIPT_DIR / 'k1109_results.json'
REGRESSION_PATH = SCRIPT_DIR / 'regression_results.json'
FIRM_CSV = SCRIPT_DIR / 'firm_level_results.csv'

DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'

TIME_BUDGET = 1700  # seconds

N_BOOTSTRAP = 5000


# ==========================================================================
# Load pre-registered sample (NOT hardcoded; loaded from locked JSON)
# ==========================================================================
def load_prereg():
    with open(PREREG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==========================================================================
# A4f-EAV MLE (copied verbatim from K1106b for reproducibility)
# ==========================================================================
def _tau_lag_prev(tau_arr, t):
    return max(tau_arr[t - 1], 1e-16)


def fit_a4f_eav(returns, vix_vals, eav_vals):
    """Full-sample MLE of A4f-EAV. Returns (params, loglik, theta2_SE)."""
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

    theta2_se = np.nan
    if best_params is not None:
        ll_0 = neg_loglik(best_params)
        theta2_bound = 1e-2
        for eps_scale in [1e-4, 1e-3, 1e-2]:
            eps = max(abs(best_params[2]) * eps_scale, eps_scale * 1e-4)
            if abs(best_params[2] + eps) > theta2_bound or \
               abs(best_params[2] - eps) > theta2_bound:
                continue
            try:
                p_plus = best_params.copy(); p_plus[2] += eps
                p_minus = best_params.copy(); p_minus[2] -= eps
                ll_plus = neg_loglik(p_plus)
                ll_minus = neg_loglik(p_minus)
                h22 = (ll_plus - 2 * ll_0 + ll_minus) / (eps ** 2)
                if h22 > 0 and np.isfinite(h22):
                    theta2_se = float(np.sqrt(1.0 / h22))
                    break
            except Exception:
                continue
    return best_params, best_ll, theta2_se


# ==========================================================================
# Earnings dates + data download (verbatim from K1106b)
# ==========================================================================
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


def _cached_download(ticker):
    cache_path = DATA_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    print(f'    [download] fetching {ticker} ...')
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


# ==========================================================================
# Per-firm runner
# ==========================================================================
def run_firm(firm):
    code = firm['code']
    ticker = firm['ticker']
    name = firm['name']
    sector = firm['sector']
    print(f"\n  [{code}] {name} ({sector}) — MLE ...")

    ea_df = load_earnings(code)

    raw = _cached_download(ticker)
    if raw is None:
        print(f'    ERROR: no data for {ticker}')
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))

    vix_raw = _cached_download('^VIX')
    if vix_raw is None:
        print('    ERROR: no VIX data')
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
        print(f'    SKIP: only {len(ret)} obs')
        return None
    if eav_arr.sum() < 15:
        print(f'    SKIP: only {int(eav_arr.sum())} events')
        return None

    params, ll, theta2_se = fit_a4f_eav(ret, vix, eav_arr)
    if params is None:
        print('    MLE failed')
        return None

    theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = params
    persist = alpha_p + gamma_p / 2.0 + beta_p

    vix_lag = np.concatenate([[vix[0]], vix[:-1]])
    eav_lag = np.concatenate([[eav_arr[0]], eav_arr[:-1]])
    tau_series = np.maximum(theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag,
                            1e-16)
    tau_at_event = tau_series[eav_lag > 0].mean() if (eav_lag > 0).any() else np.nan
    tau_nonevent = tau_series[eav_lag == 0].mean() if (eav_lag == 0).any() else np.nan
    tau_jump_pct = (tau_at_event - tau_nonevent) / tau_nonevent * 100 \
        if tau_nonevent > 0 else np.nan

    theta2_t = theta2 / theta2_se if np.isfinite(theta2_se) and theta2_se > 0 else np.nan

    # earnings_freq_per_year = total events / years of data
    years = (df.index[-1] - df.index[0]).days / 365.25
    earnings_freq = float(eav_arr.sum()) / max(years, 1)

    res = {
        'code': code, 'ticker': ticker, 'name': name, 'sector': sector,
        'n_obs': int(len(ret)),
        'n_events': int(eav_arr.sum()),
        'n_dropped_outliers': int(n_dropped),
        'theta0': float(theta0), 'theta1': float(theta1),
        'theta2': float(theta2),
        'theta2_se': float(theta2_se) if np.isfinite(theta2_se) else None,
        'theta2_t': float(theta2_t) if np.isfinite(theta2_t) else None,
        'omega_g': float(omega_g), 'alpha': float(alpha_p),
        'gamma': float(gamma_p), 'beta': float(beta_p),
        'persistence': float(persist),
        'loglik': float(-ll),
        'tau_at_event': float(tau_at_event),
        'tau_nonevent': float(tau_nonevent),
        'tau_jump_pct': float(tau_jump_pct),
        'earnings_freq_per_year': float(earnings_freq),
        'data_start': str(df.index[0].date()),
        'data_end': str(df.index[-1].date()),
    }
    print(f"    θ₂={theta2:+.3e} (SE={theta2_se:.3e}, t={theta2_t:+.2f}), "
          f"persist={persist:.3f}, τ-jump={tau_jump_pct:+.1f}%")
    return res


# ==========================================================================
# Covariates
# ==========================================================================
def get_covariates(firm):
    ticker = firm['ticker']
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
    except Exception:
        info = {}
    mc = info.get('marketCap') or info.get('enterpriseValue')
    beta = info.get('beta')
    return {
        'marketCap': float(mc) if mc else np.nan,
        'log_mktcap': float(np.log(mc)) if mc else np.nan,
        'beta_info': float(beta) if beta else np.nan,
    }


def compute_rolling_beta(firm_ticker, bench='0050.TW', window=252):
    try:
        f_raw = _cached_download(firm_ticker)
        b_raw = _cached_download(bench)
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
    except Exception:
        return np.nan


# ==========================================================================
# OLS + ANOVA (copied from K1106b, tweaked for explicit F-test name)
# ==========================================================================
def ols_fit(y, X, names):
    X_design = np.column_stack([np.ones(len(y)), X])
    names_full = ['const'] + list(names)
    try:
        beta = np.linalg.lstsq(X_design, y, rcond=None)[0]
    except Exception:
        return None
    resid = y - X_design @ beta
    dof = len(y) - X_design.shape[1]
    if dof <= 0:
        return {'singular': True, 'names': names_full, 'dof': int(dof)}
    sigma2 = (resid @ resid) / dof

    try:
        xtxinv = np.linalg.inv(X_design.T @ X_design)
    except np.linalg.LinAlgError:
        return {'singular': True, 'names': names_full}

    se_reg = np.sqrt(np.diag(sigma2 * xtxinv))
    meat = X_design.T @ np.diag(resid ** 2) @ X_design
    cov_white = xtxinv @ meat @ xtxinv
    se_white = np.sqrt(np.diag(cov_white))

    y_mean = y.mean()
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    r2_adj = 1 - (1 - r2) * (len(y) - 1) / max(dof, 1)

    t_stats_reg = beta / se_reg
    p_reg = 2 * (1 - stats.t.cdf(np.abs(t_stats_reg), dof))
    t_stats_white = beta / se_white
    p_white = 2 * (1 - stats.t.cdf(np.abs(t_stats_white), dof))

    coef = []
    for i, nm in enumerate(names_full):
        coef.append({
            'name': nm, 'coef': float(beta[i]),
            'se': float(se_reg[i]), 'se_white': float(se_white[i]),
            't': float(t_stats_reg[i]), 't_white': float(t_stats_white[i]),
            'p': float(p_reg[i]), 'p_white': float(p_white[i]),
        })

    return {
        'coef': coef, 'r2': float(r2), 'r2_adj': float(r2_adj),
        'n': int(len(y)), 'dof': int(dof),
        'ss_res': ss_res, 'ss_tot': ss_tot,
        'beta': beta.tolist(),
    }


def anova_f(y, X_full, X_reduced):
    X_f = np.column_stack([np.ones(len(y)), X_full])
    X_r = np.column_stack([np.ones(len(y)), X_reduced])
    b_f = np.linalg.lstsq(X_f, y, rcond=None)[0]
    b_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
    ssr_f = float(np.sum((y - X_f @ b_f) ** 2))
    ssr_r = float(np.sum((y - X_r @ b_r) ** 2))
    n = len(y)
    p_full = X_f.shape[1]
    q = p_full - X_r.shape[1]
    if q <= 0 or n - p_full <= 0 or ssr_f <= 0:
        return None
    fstat = ((ssr_r - ssr_f) / q) / (ssr_f / (n - p_full))
    pval = float(1 - stats.f.cdf(fstat, q, n - p_full))
    return {'f_stat': float(fstat), 'p_value': pval,
            'df_num': int(q), 'df_den': int(n - p_full),
            'ssr_full': ssr_f, 'ssr_reduced': ssr_r}


def bh_adjust(pvals):
    """Benjamini-Hochberg FDR adjusted p-values."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj = np.empty(n)
    cummin = 1.0
    for i in range(n - 1, -1, -1):
        val = ranked[i] * n / (i + 1)
        cummin = min(cummin, val)
        adj[i] = cummin
    out = np.empty(n)
    for rank_i, orig_i in enumerate(order):
        out[orig_i] = adj[rank_i]
    return out.tolist()


def standardize_safe(x):
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


def bootstrap_sector_ci(firm_df_filt, sectors, n_boot=N_BOOTSTRAP,
                        rng=GLOBAL_RNG, alpha=0.05):
    """Non-parametric firm-level bootstrap of per-sector mean θ₂.
    Resample firms WITHIN each sector with replacement; compute mean.
    Returns dict keyed by sector with (mean, ci_low, ci_high, n_firms)."""
    out = {}
    for s in sectors:
        sub = firm_df_filt[firm_df_filt['sector'] == s]['theta2'].values
        n_s = len(sub)
        if n_s == 0:
            continue
        if n_s < 2:
            out[s] = {'sector': s, 'n_firms': int(n_s),
                      'mean_theta2': float(sub.mean()),
                      'ci_low_boot': None, 'ci_high_boot': None,
                      'boot_note': 'n<2, bootstrap unreliable'}
            continue
        means = np.empty(n_boot)
        for b in range(n_boot):
            idx = rng.integers(0, n_s, size=n_s)
            means[b] = sub[idx].mean()
        lo = float(np.quantile(means, alpha / 2))
        hi = float(np.quantile(means, 1 - alpha / 2))
        out[s] = {'sector': s, 'n_firms': int(n_s),
                  'mean_theta2': float(sub.mean()),
                  'ci_low_boot': lo, 'ci_high_boot': hi,
                  'boot_note': f'firm-level resample, n={n_boot}'}
    return out


# ==========================================================================
# Cross-validation: shared firms in K1104 ∩ K1106b ∩ K1109
# ==========================================================================
def load_prior(path):
    if not path.exists():
        return {}
    with open(path) as f:
        d = json.load(f)
    return {x['code']: x for x in d.get('firm_level_results', [])}


# ==========================================================================
# MAIN
# ==========================================================================
print('=' * 78)
print(f'{EXPERIMENT_ID}: Pre-registered random sector sample (confirmatory)')
print('=' * 78)

prereg = load_prereg()
sample = prereg['sample']
print(f'  Pre-reg sample: N={len(sample)} firms across '
      f'{len(set(f["sector"] for f in sample))} sectors')
print(f'  Pre-reg timestamp: {prereg["pre_registration_timestamp_utc"]}')

# ---- Stage 1: per-firm A4f-EAV MLE ----
print('\n[Stage 1] Full-sample A4f-EAV MLE per firm')
firm_results = []
for firm in sample:
    try:
        r = run_firm(firm)
        if r is not None:
            firm_results.append(r)
    except Exception as e:
        print(f'    ERROR for {firm["code"]}: {e}')
        import traceback
        traceback.print_exc()
    elapsed = time.time() - START_TIME
    if elapsed > TIME_BUDGET:
        print(f'\n  TIME BUDGET EXCEEDED at firm {firm["code"]}')
        break

print(f'\n  Stage 1 done — n_fits={len(firm_results)}, '
      f'elapsed={time.time() - START_TIME:.0f}s')

# ---- Stage 2: covariates ----
print('\n[Stage 2] Firm covariates (marketCap, beta_rolling)')
for r in firm_results:
    firm_def = next(f for f in sample if f['code'] == r['code'])
    cov = get_covariates(firm_def)
    beta_rolling = compute_rolling_beta(r['ticker'])
    cov['beta_rolling_0050'] = beta_rolling
    r.update(cov)
    print(f"  {r['ticker']:10s}: log_mc={cov['log_mktcap']}  "
          f"beta_roll={beta_rolling}")

firm_df = pd.DataFrame(firm_results)
firm_df.to_csv(FIRM_CSV, index=False)
print(f'  firm CSV saved → {FIRM_CSV}')

# ---- Stage 3: regression ----
print('\n[Stage 3] Confirmatory regression & bootstrap CI')

# Filter boundary solutions
boundary_mask = firm_df['persistence'] >= 0.998
n_boundary = int(boundary_mask.sum())
if n_boundary > 0:
    print(f'  DROP {n_boundary} firms with boundary persistence')
firm_df_filt = firm_df[~boundary_mask].reset_index(drop=True)

y = firm_df_filt['theta2'].values.astype(float)

# Sector dummies — foundry as reference
all_sectors = sorted(firm_df_filt['sector'].unique().tolist())
preferred_ref = 'foundry'
reference_sector = preferred_ref if preferred_ref in all_sectors \
    else firm_df_filt['sector'].value_counts().idxmax()
dummy_sectors = [s for s in all_sectors if s != reference_sector]
print(f'  Reference: {reference_sector}')
print(f'  Dummies:   {dummy_sectors}')

sector_dummies = np.zeros((len(firm_df_filt), len(dummy_sectors)))
for j, s in enumerate(dummy_sectors):
    sector_dummies[:, j] = (firm_df_filt['sector'] == s).astype(float).values

log_mc = firm_df_filt['log_mktcap'].values.astype(float)
beta_roll = firm_df_filt['beta_rolling_0050'].values.astype(float)
earn_freq = firm_df_filt['earnings_freq_per_year'].values.astype(float)

if not np.all(np.isfinite(beta_roll)):
    beta_roll[~np.isfinite(beta_roll)] = np.nanmean(beta_roll)
if not np.all(np.isfinite(log_mc)):
    log_mc[~np.isfinite(log_mc)] = np.nanmean(log_mc)
if not np.all(np.isfinite(earn_freq)):
    earn_freq[~np.isfinite(earn_freq)] = np.nanmean(earn_freq)

log_mc_z = standardize_safe(log_mc)
beta_z = standardize_safe(beta_roll)
earn_z = standardize_safe(earn_freq)

# Full: sector + log_mktcap + beta + earnings_freq
X_full = np.column_stack([sector_dummies, log_mc_z, beta_z, earn_z])
X_full_names = ([f'sector_{s}' for s in dummy_sectors] +
                ['log_mktcap_z', 'beta_rolling_z', 'earn_freq_z'])

mask_y = np.isfinite(y)
print(f'  usable n = {int(mask_y.sum())}')

reg_full = ols_fit(y[mask_y], X_full[mask_y], X_full_names)

# Reduced: only covariates (no sectors)
X_reduced = np.column_stack([log_mc_z, beta_z, earn_z])
X_reduced_names = ['log_mktcap_z', 'beta_rolling_z', 'earn_freq_z']
reg_reduced = ols_fit(y[mask_y], X_reduced[mask_y], X_reduced_names)

# Sector-only
reg_sector = ols_fit(y[mask_y], sector_dummies[mask_y],
                     [f'sector_{s}' for s in dummy_sectors])

# ANOVA F: all sector dummies joint
anova = anova_f(y[mask_y], X_full[mask_y], X_reduced[mask_y])

# Per-coefficient BH correction across all sector-dummy t-tests
if reg_full is not None and not reg_full.get('singular'):
    sector_ps = [c['p'] for c in reg_full['coef']
                 if c['name'].startswith('sector_')]
    sector_names = [c['name'] for c in reg_full['coef']
                    if c['name'].startswith('sector_')]
    bh_sector = bh_adjust(sector_ps) if sector_ps else []
    bh_map = dict(zip(sector_names, bh_sector))
else:
    bh_map = {}

# Per-sector bootstrap 95% CI
print(f'  Bootstrapping {N_BOOTSTRAP} reps per sector ...')
boot_ci = bootstrap_sector_ci(firm_df_filt, all_sectors,
                              n_boot=N_BOOTSTRAP, rng=GLOBAL_RNG)

# Per-sector descriptive stats
sector_stats = {}
for s in all_sectors:
    sub = firm_df_filt[firm_df_filt['sector'] == s]['theta2'].values
    n_s = len(sub)
    if n_s == 0:
        continue
    mean_s = float(np.mean(sub))
    sd_s = float(np.std(sub, ddof=1)) if n_s > 1 else None
    se_s = sd_s / np.sqrt(n_s) if sd_s is not None else None
    tcrit = stats.t.ppf(0.975, n_s - 1) if n_s > 1 else None
    ci_low_t = mean_s - tcrit * se_s if tcrit is not None else None
    ci_high_t = mean_s + tcrit * se_s if tcrit is not None else None
    merged = {**boot_ci.get(s, {}),
              'mean_theta2': mean_s,
              'sd_theta2': sd_s,
              'se_theta2': se_s,
              'ci_low_tdist': ci_low_t,
              'ci_high_tdist': ci_high_t}
    sector_stats[s] = merged

# ---- Print summary ----
print('\n[Sector summary]')
for s, info in sector_stats.items():
    ci_lo = info.get('ci_low_boot')
    ci_hi = info.get('ci_high_boot')
    ci_txt = f"bootCI=[{ci_lo:+.2e}, {ci_hi:+.2e}]" \
        if ci_lo is not None else 'boot n/a'
    print(f"  {s:14s} n={info['n_firms']}  "
          f"mean={info['mean_theta2']:+.3e}  {ci_txt}")

print('\n[Full regression] θ₂ ~ sector + log_mc + beta + earn_freq')
if reg_full is not None and not reg_full.get('singular'):
    print(f"  R²={reg_full['r2']:.3f} adj={reg_full['r2_adj']:.3f} "
          f"n={reg_full['n']} dof={reg_full['dof']}")
    for c in reg_full['coef']:
        bh_adj = bh_map.get(c['name'])
        bh_str = f'  BH={bh_adj:.4f}' if bh_adj is not None else ''
        sig = '***' if abs(c['t']) > 2.58 else '**' if abs(c['t']) > 1.96 \
            else '*' if abs(c['t']) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3e} SE={c['se']:.3e} "
              f"t={c['t']:+.2f} p={c['p']:.4f}{bh_str} {sig}")

print('\n[ANOVA] sector dummies jointly significant?')
if anova is not None:
    print(f"  F({anova['df_num']},{anova['df_den']}) = {anova['f_stat']:.3f}"
          f", p = {anova['p_value']:.4f}")
    print('  → ' + ('REJECT H0 (sector heterogeneity)' if anova['p_value'] < 0.05
                    else 'FAIL TO REJECT'))

# Compare to K1106b: what was fabless β?
print('\n[Cherry-pick quantification] K1106b fabless β vs K1109 fabless β')
k1106b_results = {}
k1106b_path = PROJECT_ROOT / 'experiments' / 'k1106b' / 'k1106b_results.json'
if k1106b_path.exists():
    with open(k1106b_path) as f:
        k1106b_results = json.load(f)

k1106b_fabless_beta = None
if k1106b_results.get('regression_full'):
    for c in k1106b_results['regression_full']['coef']:
        if c['name'] == 'sector_fabless':
            k1106b_fabless_beta = c
            break
k1109_fabless_beta = None
if reg_full is not None and not reg_full.get('singular'):
    for c in reg_full['coef']:
        if c['name'] == 'sector_fabless':
            k1109_fabless_beta = c
            break

if k1106b_fabless_beta and k1109_fabless_beta:
    print(f"  K1106b (cherry-pick N=14): β={k1106b_fabless_beta['coef']:+.3e}, "
          f"t={k1106b_fabless_beta['t']:+.2f}, p={k1106b_fabless_beta['p']:.4f}")
    print(f"  K1109  (random  N={len(firm_results)}):  β={k1109_fabless_beta['coef']:+.3e}, "
          f"t={k1109_fabless_beta['t']:+.2f}, p={k1109_fabless_beta['p']:.4f}")
    diff = k1109_fabless_beta['coef'] - k1106b_fabless_beta['coef']
    rel = diff / abs(k1106b_fabless_beta['coef']) * 100 \
        if k1106b_fabless_beta['coef'] != 0 else None
    print(f"  Δβ = {diff:+.3e}" + (f" ({rel:+.1f}% of |K1106b β|)"
                                    if rel is not None else ''))

# Cross-validation with K1104 + K1106b overlap
print('\n[Cross-validation] Shared-firm θ₂ stability across experiments')
k1104_by_code = load_prior(PROJECT_ROOT / 'experiments' / 'k1104' /
                           'k1104_results.json')
k1106b_by_code = load_prior(k1106b_path)
overlap = []
for r in firm_results:
    row = {'code': r['code'], 'name': r['name'], 'sector': r['sector'],
           'theta2_k1109': r['theta2']}
    if r['code'] in k1104_by_code:
        row['theta2_k1104'] = k1104_by_code[r['code']]['theta2']
    if r['code'] in k1106b_by_code:
        row['theta2_k1106b'] = k1106b_by_code[r['code']]['theta2']
    overlap.append(row)
print(f"  Firms with any prior estimate: "
      f"{sum(1 for o in overlap if 'theta2_k1104' in o or 'theta2_k1106b' in o)}")
for o in overlap:
    if 'theta2_k1104' in o or 'theta2_k1106b' in o:
        k4 = o.get('theta2_k1104')
        k6 = o.get('theta2_k1106b')
        k9 = o['theta2_k1109']
        print(f"  {o['code']} {o['name']:15s} "
              f"K1104={k4 if k4 is None else f'{k4:+.2e}'}  "
              f"K1106b={k6 if k6 is None else f'{k6:+.2e}'}  "
              f"K1109={k9:+.2e}")


# ==========================================================================
# CONFIRMATORY VERDICT
# ==========================================================================
print('\n[Confirmatory verdict]')

verdict = {}
# H1: ANOVA p<0.05 AND BH survives
h1_pass = anova is not None and anova['p_value'] < 0.05
# For BH survival, apply BH across all sector dummies' individual p-values
# (conservative). If ANY sector dummy survives, H1 is supported.
any_survives_bh = any(v < 0.05 for v in bh_map.values()) if bh_map else False
h1_strong = h1_pass and any_survives_bh
verdict['H1 (joint ANOVA)'] = {
    'anova_pvalue': anova['p_value'] if anova else None,
    'any_bh_survives': any_survives_bh,
    'passes': bool(h1_strong),
    'rule': 'ANOVA p<0.05 AND at least one sector dummy survives BH-FDR',
}
# H2: fabless p<0.05 AND β<0
if k1109_fabless_beta is not None:
    h2_pass = (k1109_fabless_beta['p'] < 0.05 and
               k1109_fabless_beta['coef'] < 0)
    verdict['H2 (fabless<foundry)'] = {
        'coef': k1109_fabless_beta['coef'],
        't': k1109_fabless_beta['t'],
        'p': k1109_fabless_beta['p'],
        'bh_adj': bh_map.get('sector_fabless'),
        'passes': bool(h2_pass),
        'rule': 'fabless dummy p<0.05 AND β<0',
    }
else:
    verdict['H2 (fabless<foundry)'] = {'passes': False,
                                       'note': 'fabless dummy not in regression'}
# H3: shipping CI crosses 0
ship = boot_ci.get('shipping')
if ship and ship.get('ci_low_boot') is not None:
    lo, hi = ship['ci_low_boot'], ship['ci_high_boot']
    crosses_zero = (lo <= 0 <= hi)
    verdict['H3 (shipping=0)'] = {
        'mean': ship['mean_theta2'], 'ci_low': lo, 'ci_high': hi,
        'crosses_zero': bool(crosses_zero),
        'passes': bool(crosses_zero),
        'rule': 'shipping bootstrap 95% CI overlaps 0',
    }
else:
    verdict['H3 (shipping=0)'] = {'passes': False,
                                  'note': 'shipping CI not computable'}

for hname, v in verdict.items():
    print(f"  {hname}: {'PASS' if v.get('passes') else 'FAIL'}")
    for k, val in v.items():
        if k == 'passes':
            continue
        print(f"    - {k}: {val}")


# ==========================================================================
# SAVE RESULTS
# ==========================================================================
out = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Pre-registered random sector sample (confirmatory)',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'motivation': (
        'K1106b hypothesis-driven N=14 sample found fabless β=-2.29e-3, '
        'p=0.004 but E052 flagged cherry-pick bias. K1109 pre-registers '
        'a larger random sample (N≈32) to confirm or reject.'),
    'data_source': (
        'yfinance daily (auto_adjust) + Ticker.info + 財報公告日.txt (Big5). '
        'Sample pre-registered in prereg_sample.json.'),
    'data_period': f'{DATA_START} to {DATA_END}',
    'random_seed': 42,
    'pre_registration': {
        'locked_at_utc': prereg['pre_registration_timestamp_utc'],
        'sample_file': 'prereg_sample.json',
        'sample_design_rule': prereg['selection_rule'],
        'n_total_planned': prereg['n_total_firms'],
    },
    'n_firms_fit': len(firm_results),
    'n_sectors': len(all_sectors),
    'sectors': all_sectors,
    'reference_sector': reference_sector,
    'firm_level_results': firm_results,
    'sector_stats': list(sector_stats.values()),
    'regression_full': reg_full,
    'regression_reduced': reg_reduced,
    'regression_sector_only': reg_sector,
    'anova_sector_ftest': anova,
    'bh_adjusted_pvalues': bh_map,
    'bootstrap_sector_ci': list(boot_ci.values()),
    'cross_validation_overlap': overlap,
    'k1106b_comparison': {
        'k1106b_fabless_beta': k1106b_fabless_beta,
        'k1109_fabless_beta': k1109_fabless_beta,
    },
    'hypotheses_prereg': {
        'H1': 'ANOVA F-test p<0.05 AND BH survives',
        'H2': 'fabless dummy p<0.05 AND β<0',
        'H3': 'shipping bootstrap 95% CI overlaps 0',
    },
    'confirmatory_verdict': verdict,
    'metadata': {
        'script': 'experiments/k1109/k1109.py',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'runtime_seconds': round(time.time() - START_TIME, 1),
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160.',
            'Benjamini & Hochberg (1995). Controlling the False Discovery Rate. '
            'JRSS B 57(1).',
            'K1067/K1103/K1104/K1106b.',
        ],
    },
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(f'\n  Results → {RESULTS_PATH}')

with open(REGRESSION_PATH, 'w', encoding='utf-8') as f:
    json.dump({
        'regression_full': reg_full,
        'regression_reduced': reg_reduced,
        'anova': anova,
        'bh_adjusted': bh_map,
        'sector_stats': list(sector_stats.values()),
        'bootstrap_ci': list(boot_ci.values()),
        'verdict': verdict,
    }, f, indent=2, ensure_ascii=False, default=str)
print(f'  Regression → {REGRESSION_PATH}')


# ==========================================================================
# CHARTS
# ==========================================================================
print('\n[Charts] Generating forest plot + K1106b comparison ...')
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# -- Chart 1: Forest plot, per-sector mean θ₂ with bootstrap 95% CI --
ordered = sorted(sector_stats.items(),
                 key=lambda kv: kv[1]['mean_theta2'])
fig, ax = plt.subplots(figsize=(10, 6))
ys = np.arange(len(ordered))
means = [v['mean_theta2'] for _, v in ordered]
los = [v.get('ci_low_boot') for _, v in ordered]
his = [v.get('ci_high_boot') for _, v in ordered]
labels = [f"{s} (n={v['n_firms']})" for s, v in ordered]

for i, (m, lo, hi) in enumerate(zip(means, los, his)):
    if lo is None or hi is None:
        ax.plot(m, ys[i], 'o', markersize=10, color='gray')
    else:
        err = [[m - lo], [hi - m]]
        color = 'tab:red' if hi < 0 else 'tab:green' if lo > 0 else 'tab:blue'
        ax.errorbar(m, ys[i], xerr=err, fmt='o', capsize=6,
                    color=color, markersize=10, linewidth=2)
ax.axvline(0, color='black', linestyle='--', alpha=0.6)
ax.set_yticks(ys)
ax.set_yticklabels(labels)
ax.set_xlabel('θ₂ (EAV coefficient)')
ax.set_title(f'K1109: Per-sector θ₂ with bootstrap 95% CI ({N_BOOTSTRAP} reps)\n'
             f'N={len(firm_results)} firms (pre-registered random sample)')
ax.grid(True, alpha=0.3, axis='x')
plt.tight_layout()
chart1_path = SCRIPT_DIR / 'k1109_sector_theta2_forest_plot.png'
plt.savefig(chart1_path, bbox_inches='tight')
plt.close()
print(f'  Chart 1 saved → {chart1_path}')

# -- Chart 2: K1106b vs K1109 fabless beta comparison --
fig, ax = plt.subplots(figsize=(9, 5))
points = []
if k1106b_fabless_beta is not None:
    points.append(('K1106b (cherry-pick, N=14)',
                   k1106b_fabless_beta['coef'], k1106b_fabless_beta['se'],
                   k1106b_fabless_beta['p']))
if k1109_fabless_beta is not None:
    points.append((f'K1109 (random, N={len(firm_results)})',
                   k1109_fabless_beta['coef'], k1109_fabless_beta['se'],
                   k1109_fabless_beta['p']))
for i, (lbl, b, se, p) in enumerate(points):
    ax.errorbar(b, i, xerr=1.96 * se, fmt='o', capsize=8,
                markersize=12, color='tab:red' if b < 0 else 'tab:green')
    ax.annotate(f'β={b:+.2e}\np={p:.4f}', (b, i), textcoords='offset points',
                xytext=(10, -6), fontsize=9)
ax.axvline(0, color='black', linestyle='--', alpha=0.6)
ax.set_yticks(range(len(points)))
ax.set_yticklabels([p[0] for p in points])
ax.set_xlabel('Fabless sector dummy coefficient')
ax.set_title('Cherry-pick bias quantification: K1106b vs K1109')
plt.tight_layout()
chart2_path = SCRIPT_DIR / 'k1109_vs_k1106b_comparison.png'
plt.savefig(chart2_path, bbox_inches='tight')
plt.close()
print(f'  Chart 2 saved → {chart2_path}')

print('\n' + '=' * 78)
print(f'K1109 Done. Total runtime: {time.time() - START_TIME:.0f}s')
print('=' * 78)
