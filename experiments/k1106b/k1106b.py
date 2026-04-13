#!/usr/bin/env python3
"""
K1106b: Sector-diversified firm θ₂ heterogeneity
=================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1104 found TSMC foundry θ₂>0 weakly, MediaTek/Realtek fabless θ₂<0
  strongly, but the 0050.TW-constituents sample was 80%+ semiconductor-
  related. Sector heterogeneity of EAV effectiveness therefore was not
  truly tested: financials, shipping, traditional manufacturing,
  consumer defensive were all under-represented.

  K1106b deliberately picks 6 sectors × 2-3 firms each (total N=14) to
  test whether θ₂ varies systematically across sectors, using the same
  K1104 full-sample single-shot A4f-EAV MLE methodology (τ-lag fixed
  from K1103).

Design:
  Stage 1 — per-firm A4f-EAV estimation (single-window full-sample, no
            rolling refit, to stay under 25-min budget).
  Stage 2 — sector covariates: sector dummies + log_mktcap + beta.
  Stage 3 — cross-sectional OLS (θ₂ ~ sector_dummies + log_mktcap + beta)
            with ANOVA F-test for joint significance of sector dummies.

Hypotheses:
  H1 (sector F-test): sector dummies joint F-test p < 0.05.
  H2 (foundry > fabless): foundry dummy coef - fabless dummy coef > 0,
       t-test p < 0.05.
  H3 (shipping): shipping dummy > 0 — earnings releases reveal freight
       rate shocks that translate to vol amplification.
  H4 (consumer defensive): consumer dummy coef near 0 — low EPS variance
       ⇒ earnings news carries little vol information.

Firms (N=14):
  foundry:    2330 TSMC,       2303 UMC
  fabless:    2454 MediaTek,   2379 Realtek
  financials: 2881 Fubon FH,   2886 Mega FH,   2882 Cathay FH
  shipping:   2603 Evergreen,  2615 Wanhai Lines
  trad_mfg:   1301 Formosa,    2002 China Steel
  electronics:2317 Hon Hai      (EMS, non-semi)
  consumer:   2912 Pres. Chain (statutory), 1216 Uni-President

Data:
  - yfinance (auto_adjust=True) daily close for 14 listed firms, 2010-2025
  - yfinance ^VIX daily close
  - 財報公告日.txt (Big5) earnings announcement dates per code
  - yfinance Ticker.info for marketCap/beta
  - 0050.TW as the beta benchmark

Limitations (stated upfront — small sample):
  N=14, each sector has 1-3 firms. Sector dummies have limited power;
  ANOVA F-test with N=14 and 6 sector dummies has only 6 dof for
  numerator, ~6 for denominator — underpowered. Treat reported ps with
  caution. Direction of effect is the primary evidence; statistical
  significance is secondary.

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
  - Patton (2011). Volatility forecast comparison. J Econometrics 160.
  - K1067/K1067b/K1067c/K1103/K1104 — EAV and firm heterogeneity.

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
EXPERIMENT_ID = "K1106b"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1106b_results.json'
COV_CSV_PATH = SCRIPT_DIR / 'firm_covariates.csv'
FIRM_CSV_PATH = SCRIPT_DIR / 'firm_level_results.csv'

DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'

# ==========================================================================
# FIRM ROSTER: 7 sectors × 1-3 firms for deliberate diversification
# ==========================================================================
# Column format: (code, ticker, name, sector, is_alternate)
# sector buckets:  foundry / fabless / financials / shipping /
#                   trad_mfg / electronics / consumer
CANDIDATES = [
    # Foundry (semi)
    ('2330', '2330.TW', 'TSMC',           'foundry'),
    ('2303', '2303.TW', 'UMC',            'foundry'),
    # Fabless (semi)
    ('2454', '2454.TW', 'MediaTek',       'fabless'),
    ('2379', '2379.TW', 'Realtek',        'fabless'),
    # Financials
    ('2881', '2881.TW', 'Fubon FH',       'financials'),
    ('2886', '2886.TW', 'Mega FH',        'financials'),
    ('2882', '2882.TW', 'Cathay FH',      'financials'),
    # Shipping
    ('2603', '2603.TW', 'Evergreen',      'shipping'),
    ('2615', '2615.TW', 'Wanhai',         'shipping'),
    # Traditional manufacturing
    ('1301', '1301.TW', 'Formosa',        'trad_mfg'),
    ('2002', '2002.TW', 'China Steel',    'trad_mfg'),
    # Electronics (non-semi)
    ('2317', '2317.TW', 'Hon Hai',        'electronics'),
    # Consumer defensive
    ('2912', '2912.TW', 'Pres. Chain',    'consumer'),
    ('1216', '1216.TW', 'Uni-President',  'consumer'),
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
    Returns (best_params, best_loglik, hessian_se_theta2).
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
    best_res = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 800})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                best_res = res
        except Exception:
            continue

    # Compute Hessian-based SE for θ₂ using numerical 2nd derivative.
    # Try multiple epsilons; fall back to NaN if all fail.
    # Note: τ=max(...) introduces a kink so h22 can be noisy; we try
    # progressively larger eps to find a stable region.
    theta2_se = np.nan
    if best_params is not None:
        ll_0 = neg_loglik(best_params)
        theta2_bound = 1e-2  # from bounds list
        for eps_scale in [1e-4, 1e-3, 1e-2]:
            eps = max(abs(best_params[2]) * eps_scale, eps_scale * 1e-4)
            # Keep perturbed θ₂ inside bounds
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
    """Download and cache yfinance data to parquet."""
    cache_path = DATA_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    print(f"    [download] fetching {ticker} ...")
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
    code, ticker, name, sector = firm[0], firm[1], firm[2], firm[3]
    print(f"\n  [{code}.TW] {name} ({sector}) — full-sample MLE ...")

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
    if eav_arr.sum() < 15:
        print(f"    WARNING: only {int(eav_arr.sum())} events, skipping")
        return None

    params, ll, theta2_se = fit_a4f_eav(ret, vix, eav_arr)
    if params is None:
        print(f"    ERROR: MLE failed for {ticker}")
        return None

    theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = params
    persist = alpha_p + gamma_p / 2.0 + beta_p

    # τ jump at event day vs non-event day
    vix_lag = np.concatenate([[vix[0]], vix[:-1]])
    eav_lag = np.concatenate([[eav_arr[0]], eav_arr[:-1]])
    tau_series = np.maximum(theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag,
                            1e-16)
    tau_at_event = tau_series[eav_lag > 0].mean() if (eav_lag > 0).any() else np.nan
    tau_nonevent = tau_series[eav_lag == 0].mean() if (eav_lag == 0).any() else np.nan
    tau_jump_pct = (tau_at_event - tau_nonevent) / tau_nonevent * 100 \
        if tau_nonevent > 0 else np.nan

    # θ₂ t-stat based on Hessian SE
    theta2_t = theta2 / theta2_se if np.isfinite(theta2_se) and theta2_se > 0 else np.nan

    res = {
        'code': code,
        'ticker': ticker,
        'name': name,
        'sector': sector,
        'n_obs': int(len(ret)),
        'n_events': int(eav_arr.sum()),
        'n_dropped_outliers': int(n_dropped),
        'theta0': float(theta0),
        'theta1': float(theta1),
        'theta2': float(theta2),
        'theta2_se': float(theta2_se) if np.isfinite(theta2_se) else None,
        'theta2_t': float(theta2_t) if np.isfinite(theta2_t) else None,
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
    print(f"    θ₂={theta2:+.3e} (SE={theta2_se:.3e}, t={theta2_t:+.2f}), "
          f"persist={persist:.3f}, τ-jump={tau_jump_pct:+.1f}%, "
          f"n_ev={int(eav_arr.sum())}")
    return res


# ==========================================================================
# STAGE 2: Firm covariates (from yfinance info)
# ==========================================================================
def get_covariates(firm):
    """Fetch market-cap, beta from yfinance."""
    ticker = firm[1]
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
    except Exception:
        info = {}
    mc = info.get('marketCap')
    if mc is None:
        mc = info.get('enterpriseValue')
    beta = info.get('beta')
    return {
        'marketCap': float(mc) if mc else np.nan,
        'log_mktcap': float(np.log(mc)) if mc else np.nan,
        'beta_info': float(beta) if beta else np.nan,
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
    except Exception:
        return np.nan


# ==========================================================================
# STAGE 3: Cross-sectional regression with ANOVA F-test
# ==========================================================================
def ols_fit(y, X, names):
    """Standard OLS + HC0 SEs."""
    X_design = np.column_stack([np.ones(len(y)), X])
    names_full = ['const'] + list(names)
    try:
        beta = np.linalg.lstsq(X_design, y, rcond=None)[0]
    except Exception:
        return None
    resid = y - X_design @ beta
    dof = len(y) - X_design.shape[1]
    sigma2 = (resid @ resid) / max(dof, 1)

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
    p_reg = 2 * (1 - stats.t.cdf(np.abs(t_stats_reg), dof)) if dof > 0 else np.nan
    t_stats_white = beta / se_white
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
        'ss_res': ss_res,
        'ss_tot': ss_tot,
        'beta': beta.tolist(),
        'predicted': (X_design @ beta).tolist(),
        'resid': resid.tolist(),
    }


def anova_f_test(y, X_full, X_reduced, df_full_dim, df_reduced_dim):
    """F-test: is X_full significantly better than X_reduced?
    X_full includes sector dummies; X_reduced drops them.
    H0: all sector dummy coefficients are zero.
    F = ((SSR_r - SSR_f) / q) / (SSR_f / (n - p_full))
    where q = number of restrictions (columns dropped).
    """
    X_full_design = np.column_stack([np.ones(len(y)), X_full])
    X_reduced_design = np.column_stack([np.ones(len(y)), X_reduced])
    try:
        b_f = np.linalg.lstsq(X_full_design, y, rcond=None)[0]
        b_r = np.linalg.lstsq(X_reduced_design, y, rcond=None)[0]
    except Exception:
        return None
    ssr_full = float(np.sum((y - X_full_design @ b_f) ** 2))
    ssr_red = float(np.sum((y - X_reduced_design @ b_r) ** 2))
    n = len(y)
    p_full = X_full_design.shape[1]
    q = p_full - X_reduced_design.shape[1]
    if q <= 0 or n - p_full <= 0 or ssr_full <= 0:
        return None
    f_stat = ((ssr_red - ssr_full) / q) / (ssr_full / (n - p_full))
    p_val = 1 - stats.f.cdf(f_stat, q, n - p_full)
    return {
        'f_stat': float(f_stat),
        'p_value': float(p_val),
        'df_num': int(q),
        'df_den': int(n - p_full),
        'ssr_full': ssr_full,
        'ssr_reduced': ssr_red,
    }


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


# ==========================================================================
# MAIN
# ==========================================================================
print("=" * 78)
print(f"{EXPERIMENT_ID}: Sector-diversified firm θ₂ heterogeneity")
print("=" * 78)
print(f"  N candidate firms: {len(CANDIDATES)}")
print(f"  Sectors: 7 (foundry, fabless, financials, shipping, trad_mfg, "
      f"electronics, consumer)")
print(f"  Data: {DATA_START} — {DATA_END}")

# ---- Stage 1: θ₂ per firm ----
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
    if elapsed > 1500:  # 25-min hard cap
        print(f"\n  TIME BUDGET EXCEEDED at firm {firm[0]}")
        break

print(f"\n  Stage 1 done — n_fits={len(firm_results)}, "
      f"elapsed={time.time() - START_TIME:.0f}s")

# ---- Stage 2: covariates ----
print("\n[Stage 2] Collecting firm covariates")
for r in firm_results:
    ticker = r['ticker']
    firm_def = next(f for f in CANDIDATES if f[0] == r['code'])
    cov = get_covariates(firm_def)
    beta_rolling = compute_rolling_beta(ticker)
    cov['beta_rolling_0050'] = beta_rolling
    r.update(cov)
    print(f"  {ticker}: log_mktcap={cov['log_mktcap']:.2f}  "
          f"beta_info={cov['beta_info']}  beta_rolling={beta_rolling}")

firm_df = pd.DataFrame(firm_results)
firm_df.to_csv(FIRM_CSV_PATH, index=False)
print(f"  firm-level CSV saved → {FIRM_CSV_PATH}")

# Also save the covariate-only subset
cov_cols = ['code', 'ticker', 'name', 'sector',
            'marketCap', 'log_mktcap', 'beta_info', 'beta_rolling_0050']
firm_df[cov_cols].to_csv(COV_CSV_PATH, index=False)

# ---- Stage 3: regression ----
print("\n[Stage 3] Cross-sectional regression of θ₂ on sector dummies + covariates")

# Filter boundary MLE solutions
boundary_mask = firm_df['persistence'] >= 0.998
n_boundary = int(boundary_mask.sum())
if n_boundary > 0:
    print(f"  DROPPING {n_boundary} firms with boundary MLE (persist>=0.998)")
firm_df_filt = firm_df[~boundary_mask].reset_index(drop=True)

y = firm_df_filt['theta2'].values.astype(float)

# Sector dummies — use foundry as the reference group (k-1 dummies for k sectors)
all_sectors = sorted(firm_df_filt['sector'].unique().tolist())
# Defensive: if foundry was filtered out (both TSMC+UMC hit boundary persist),
# fall back to the largest remaining sector as reference to keep dummies
# orthogonal to the intercept (avoid singular matrix in OLS).
preferred_reference = 'foundry'
if preferred_reference in all_sectors:
    reference_sector = preferred_reference
else:
    # Pick the sector with most firms as reference
    sector_counts = firm_df_filt['sector'].value_counts()
    reference_sector = sector_counts.idxmax()
    print(f"  WARNING: '{preferred_reference}' not in sample; "
          f"falling back to '{reference_sector}' as reference")
dummy_sectors = [s for s in all_sectors if s != reference_sector]
print(f"  Reference sector: {reference_sector}")
print(f"  Sector dummies: {dummy_sectors}")

sector_dummies = np.zeros((len(firm_df_filt), len(dummy_sectors)))
for j, s in enumerate(dummy_sectors):
    sector_dummies[:, j] = (firm_df_filt['sector'] == s).astype(float).values

# Stack sector dummies + log_mktcap + beta_rolling
log_mc = firm_df_filt['log_mktcap'].values.astype(float)
beta_roll = firm_df_filt['beta_rolling_0050'].values.astype(float)

# Impute beta missing with column mean
if not np.all(np.isfinite(beta_roll)):
    beta_roll[~np.isfinite(beta_roll)] = np.nanmean(beta_roll)
# Impute log_mktcap missing with column mean
if not np.all(np.isfinite(log_mc)):
    log_mc[~np.isfinite(log_mc)] = np.nanmean(log_mc)

log_mc_z = standardize_safe(log_mc)
beta_z = standardize_safe(beta_roll)

# ---- Full spec: sector dummies + log_mktcap + beta ----
X_full = np.column_stack([sector_dummies, log_mc_z, beta_z])
X_full_names = [f'sector_{s}' for s in dummy_sectors] + ['log_mktcap_z', 'beta_rolling_z']

# Guard against NaN in y
mask_y = np.isfinite(y)
print(f"  usable n after y finite check = {int(mask_y.sum())}")

reg_full = ols_fit(y[mask_y], X_full[mask_y], X_full_names)

# ---- Reduced spec: log_mktcap + beta only (no sector) ----
X_reduced = np.column_stack([log_mc_z, beta_z])
X_reduced_names = ['log_mktcap_z', 'beta_rolling_z']
reg_reduced = ols_fit(y[mask_y], X_reduced[mask_y], X_reduced_names)

# ---- Sector-only spec ----
reg_sector = ols_fit(y[mask_y], sector_dummies[mask_y],
                     [f'sector_{s}' for s in dummy_sectors])

# ---- ANOVA F-test: sector dummies jointly significant? ----
anova = anova_f_test(
    y[mask_y],
    X_full[mask_y],
    X_reduced[mask_y],
    df_full_dim=X_full.shape[1] + 1,
    df_reduced_dim=X_reduced.shape[1] + 1,
)

# ---- Per-sector mean θ₂ with 95% CI (t-distribution) ----
sector_stats = {}
for s in all_sectors:
    sub = firm_df_filt[firm_df_filt['sector'] == s]['theta2'].values
    n_s = len(sub)
    if n_s == 0:
        continue
    mean_s = float(np.mean(sub))
    sd_s = float(np.std(sub, ddof=1)) if n_s > 1 else np.nan
    se_s = sd_s / np.sqrt(n_s) if n_s > 1 else np.nan
    if np.isfinite(se_s):
        tcrit = stats.t.ppf(0.975, n_s - 1) if n_s > 1 else np.nan
        ci_low = mean_s - tcrit * se_s
        ci_high = mean_s + tcrit * se_s
    else:
        ci_low = ci_high = np.nan
    sector_stats[s] = {
        'sector': s,
        'n_firms': int(n_s),
        'mean_theta2': mean_s,
        'sd_theta2': sd_s,
        'se_theta2': float(se_s) if np.isfinite(se_s) else None,
        'ci_low': float(ci_low) if np.isfinite(ci_low) else None,
        'ci_high': float(ci_high) if np.isfinite(ci_high) else None,
    }

# ---- Print summary ----
print("\n[Sector summary] per-sector mean θ₂:")
for s, info in sector_stats.items():
    sd_str = f"{info['sd_theta2']:+.3e}" if info['sd_theta2'] is not None and np.isfinite(info['sd_theta2']) else "—"
    print(f"  {s:14s} n={info['n_firms']}  mean_θ₂={info['mean_theta2']:+.3e}  SD={sd_str}")

print("\n[Full regression] θ₂ ~ sector_dummies + log_mktcap_z + beta_rolling_z:")
if reg_full is not None and not reg_full.get('singular'):
    print(f"  R²={reg_full['r2']:.3f}, Adj R²={reg_full['r2_adj']:.3f}, "
          f"n={reg_full['n']}, dof={reg_full['dof']}")
    for c in reg_full['coef']:
        sig = '***' if abs(c['t']) > 2.58 else '**' if abs(c['t']) > 1.96 else \
              '*' if abs(c['t']) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE={c['se']:.3e}  "
              f"t={c['t']:+.2f}  p={c['p']:.3f} {sig}")
else:
    print("  WARNING: full regression failed or singular")

print("\n[Reduced regression] θ₂ ~ log_mktcap_z + beta_rolling_z (no sector):")
if reg_reduced is not None and not reg_reduced.get('singular'):
    print(f"  R²={reg_reduced['r2']:.3f}, Adj R²={reg_reduced['r2_adj']:.3f}, "
          f"n={reg_reduced['n']}")

print("\n[ANOVA F-test] Sector dummies jointly significant?")
if anova is not None:
    print(f"  F({anova['df_num']}, {anova['df_den']}) = {anova['f_stat']:.3f}, "
          f"p = {anova['p_value']:.4f}")
    verdict = "REJECT H0 — sector heterogeneity empirically supported" \
        if anova['p_value'] < 0.05 else \
        "FAIL TO REJECT H0 — no statistically significant sector heterogeneity"
    print(f"  → {verdict}")
else:
    print("  WARNING: ANOVA F-test failed")

# ---- Pairwise tests: key hypotheses ----
print("\n[Hypothesis tests]")
# H2: foundry vs fabless (fabless dummy != 0 because foundry is reference)
if reg_full is not None and not reg_full.get('singular'):
    coef_dict = {c['name']: c for c in reg_full['coef']}
    fabless_coef_name = 'sector_fabless'
    if fabless_coef_name in coef_dict:
        c = coef_dict[fabless_coef_name]
        print(f"  H2 (fabless vs foundry reference): β={c['coef']:+.3e}, "
              f"t={c['t']:+.2f}, p={c['p']:.4f} "
              f"{'(fabless more negative than foundry)' if c['coef'] < 0 else '(fabless MORE positive than foundry)'}")
    # H3: shipping dummy sign
    shipping_name = 'sector_shipping'
    if shipping_name in coef_dict:
        c = coef_dict[shipping_name]
        print(f"  H3 (shipping vs foundry reference): β={c['coef']:+.3e}, "
              f"t={c['t']:+.2f}, p={c['p']:.4f}")
    # H4: consumer dummy sign/magnitude
    consumer_name = 'sector_consumer'
    if consumer_name in coef_dict:
        c = coef_dict[consumer_name]
        print(f"  H4 (consumer vs foundry reference): β={c['coef']:+.3e}, "
              f"t={c['t']:+.2f}, p={c['p']:.4f}")

# ---- Replicability vs K1104 (2 semi sectors) ----
print("\n[Replicability vs K1104]")
k1104_path = PROJECT_ROOT / 'experiments' / 'k1104' / 'k1104_results.json'
k1104_comparison = []
if k1104_path.exists():
    with open(k1104_path) as f:
        k1104 = json.load(f)
    k1104_by_code = {x['code']: x for x in k1104.get('firm_level_results', [])}
    for r in firm_results:
        if r['code'] in k1104_by_code:
            k_theta = k1104_by_code[r['code']]['theta2']
            delta = r['theta2'] - k_theta
            rel_delta = delta / abs(k_theta) * 100 if abs(k_theta) > 0 else np.nan
            print(f"  {r['code']} {r['name']:15s} K1104 θ₂={k_theta:+.3e}, "
                  f"K1106b θ₂={r['theta2']:+.3e}, Δ={rel_delta:+.1f}%")
            k1104_comparison.append({
                'code': r['code'],
                'name': r['name'],
                'theta2_k1104': float(k_theta),
                'theta2_k1106b': float(r['theta2']),
                'relative_change_pct': float(rel_delta) if np.isfinite(rel_delta) else None,
            })

# ==========================================================================
# SAVE RESULTS
# ==========================================================================
out = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Sector-diversified firm θ₂ heterogeneity',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'data_source': (
        'yfinance daily (auto_adjust) + Ticker.info + 財報公告日.txt (Big5). '
        '14 firms across 7 sectors (foundry, fabless, financials, shipping, '
        'trad_mfg, electronics, consumer).'
    ),
    'data_period': f'{DATA_START} to {DATA_END}',
    'random_seed': 42,
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
    'k1104_comparison': k1104_comparison,
    'sample_size_caveat': (
        f'N={len(firm_results)} (each sector has 1-3 firms). '
        'ANOVA F-test with ~6 dof numerator and ~6 dof denominator is '
        'underpowered. Direction of sector means is the primary '
        'descriptive evidence; statistical significance secondary.'
    ),
    'hypotheses': {
        'H1 (sector F-test)': 'p < 0.05',
        'H2 (foundry > fabless)': 'fabless dummy coef < 0, p < 0.05',
        'H3 (shipping)': 'shipping dummy > 0 (freight shock → vol)',
        'H4 (consumer defensive)': 'consumer dummy ≈ 0 (|coef| < fabless |coef|)',
    },
    'metadata': {
        'script': 'experiments/k1106b/k1106b.py',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'runtime_seconds': round(time.time() - START_TIME, 1),
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160.',
            'K1067/K1067b/K1067c/K1103/K1104 — EAV and firm heterogeneity.',
        ],
    },
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  Results saved → {RESULTS_PATH}")


# ==========================================================================
# CHARTS
# ==========================================================================
print("\n[Charts] Generating sector visualisations ...")
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# --- Chart 1: 7-sector ranking bar chart with error bars ---
ordered_sectors = sorted(sector_stats.items(),
                         key=lambda kv: kv[1]['mean_theta2'])
fig, ax = plt.subplots(figsize=(10, 6))
xs = [k for k, _ in ordered_sectors]
means = [v['mean_theta2'] for _, v in ordered_sectors]
ses = [v['se_theta2'] if v['se_theta2'] is not None else 0 for _, v in ordered_sectors]
ns = [v['n_firms'] for _, v in ordered_sectors]
colours = []
for s in xs:
    if s == 'foundry':
        colours.append('#e74c3c')
    elif s == 'fabless':
        colours.append('#3498db')
    elif s == 'financials':
        colours.append('#2ecc71')
    elif s == 'shipping':
        colours.append('#9b59b6')
    elif s == 'trad_mfg':
        colours.append('#f39c12')
    elif s == 'electronics':
        colours.append('#1abc9c')
    elif s == 'consumer':
        colours.append('#95a5a6')
    else:
        colours.append('#7f8c8d')
bars = ax.bar(xs, means, yerr=ses, capsize=5, color=colours,
              edgecolor='black', alpha=0.85)
for i, (m, n) in enumerate(zip(means, ns)):
    ax.annotate(f'n={n}\n{m:+.2e}', (i, m),
                textcoords='offset points', xytext=(0, 8),
                ha='center', fontsize=8)
ax.axhline(0, color='black', linewidth=0.8, alpha=0.6)
ax.set_ylabel('Mean θ₂ (EAV coefficient)')
ax.set_xlabel('Sector')
ax.set_title('K1106b: Sector-level θ₂ ranking (error bars = 95% CI)\n'
             f'N_firms={len(firm_results)} across {len(all_sectors)} sectors, '
             f'2010-2025')
ax.grid(True, alpha=0.3, axis='y')
ax.tick_params(axis='x', rotation=20)
plt.tight_layout()
chart1_path = SCRIPT_DIR / 'k1106b_sector_theta2_ranking.png'
plt.savefig(chart1_path, bbox_inches='tight')
plt.close()
print(f"  Chart 1 saved → {chart1_path}")

# --- Chart 2: firm-level scatter θ₂ vs τ-jump% colored by sector ---
fig, ax = plt.subplots(figsize=(11, 7))
sector_colour_map = {s: c for s, c in [
    ('foundry', '#e74c3c'),
    ('fabless', '#3498db'),
    ('financials', '#2ecc71'),
    ('shipping', '#9b59b6'),
    ('trad_mfg', '#f39c12'),
    ('electronics', '#1abc9c'),
    ('consumer', '#95a5a6'),
]}
for s in all_sectors:
    sub = firm_df_filt[firm_df_filt['sector'] == s]
    if len(sub) == 0:
        continue
    ax.scatter(sub['theta2'], sub['tau_jump_pct'],
               s=110, color=sector_colour_map.get(s, '#7f8c8d'),
               edgecolors='black', alpha=0.85, label=s)
    for _, row in sub.iterrows():
        ax.annotate(row['name'], (row['theta2'], row['tau_jump_pct']),
                    fontsize=8, alpha=0.75,
                    xytext=(4, 3), textcoords='offset points')
ax.axhline(0, color='black', linewidth=0.6, alpha=0.4)
ax.axvline(0, color='black', linewidth=0.6, alpha=0.4)
ax.set_xlabel('θ₂ (EAV coefficient)')
ax.set_ylabel('τ-jump at event day (%)')
ax.set_title('K1106b: θ₂ vs τ-jump% by sector\n'
             f'Coloured points group firms within the same sector')
ax.legend(loc='upper left', fontsize=9, framealpha=0.9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
chart2_path = SCRIPT_DIR / 'k1106b_firm_scatter.png'
plt.savefig(chart2_path, bbox_inches='tight')
plt.close()
print(f"  Chart 2 saved → {chart2_path}")

# --- Chart 3: Decision tree for Paper 2 sector-based selection rules ---
fig, ax = plt.subplots(figsize=(11, 7))
ax.axis('off')

# Compute sector ranking
ranked = sorted(sector_stats.items(),
                key=lambda kv: kv[1]['mean_theta2'], reverse=True)

# Draw a decision tree structure (textual, laid out manually)
box_style = dict(boxstyle='round,pad=0.5', facecolor='#ecf0f1',
                 edgecolor='black', linewidth=1.2)
sect_style = dict(boxstyle='round,pad=0.4', facecolor='#d5dbdb',
                  edgecolor='black', linewidth=1.0)

# Title box
ax.text(0.5, 0.96, 'Paper 2 — Sector-based A4f-EAV selection decision tree',
        ha='center', fontsize=13, fontweight='bold', transform=ax.transAxes)
ax.text(0.5, 0.91,
        f'Based on K1106b N={len(firm_results)} firms × {len(all_sectors)} sectors '
        f'(descriptive only, underpowered ANOVA)',
        ha='center', fontsize=9.5, style='italic', transform=ax.transAxes)

# Root
ax.text(0.5, 0.80, 'Firm candidate', ha='center', fontsize=11, bbox=box_style,
        transform=ax.transAxes)

# Branch 1: sector mean > 0
y_pos = 0.62
ax.text(0.25, y_pos, 'mean θ₂ > 0 → consider A4f-EAV',
        ha='center', fontsize=10, bbox=box_style,
        transform=ax.transAxes)
ax.text(0.75, y_pos, 'mean θ₂ < 0 / ~0 → A4f-EAV not recommended',
        ha='center', fontsize=10, bbox=box_style,
        transform=ax.transAxes)

# Arrows
ax.annotate('', xy=(0.25, y_pos + 0.04), xytext=(0.5, 0.77),
            arrowprops=dict(arrowstyle='->', lw=1.2), xycoords='axes fraction')
ax.annotate('', xy=(0.75, y_pos + 0.04), xytext=(0.5, 0.77),
            arrowprops=dict(arrowstyle='->', lw=1.2), xycoords='axes fraction')

# Sector lists
positive_sects = [s for s, v in ranked if v['mean_theta2'] > 0]
negative_sects = [s for s, v in ranked if v['mean_theta2'] <= 0]

pos_txt = '\n'.join(
    [f"{s}: mean θ₂={sector_stats[s]['mean_theta2']:+.2e} (n={sector_stats[s]['n_firms']})"
     for s in positive_sects])
neg_txt = '\n'.join(
    [f"{s}: mean θ₂={sector_stats[s]['mean_theta2']:+.2e} (n={sector_stats[s]['n_firms']})"
     for s in negative_sects])

ax.text(0.25, 0.35, pos_txt if pos_txt else '(none)',
        ha='center', va='center', fontsize=9, bbox=sect_style,
        transform=ax.transAxes)
ax.text(0.75, 0.35, neg_txt if neg_txt else '(none)',
        ha='center', va='center', fontsize=9, bbox=sect_style,
        transform=ax.transAxes)

# ANOVA note
anova_txt = ('ANOVA F-test: '
             + (f"F={anova['f_stat']:.2f}, p={anova['p_value']:.3f}" if anova else "n/a"))
ax.text(0.5, 0.08, anova_txt,
        ha='center', fontsize=10, bbox=box_style,
        transform=ax.transAxes)
ax.text(0.5, 0.02,
        'Caveat: small N per sector; treat direction as leading evidence, '
        'not causal inference.',
        ha='center', fontsize=8.5, style='italic',
        transform=ax.transAxes)

plt.tight_layout()
chart3_path = SCRIPT_DIR / 'k1106b_sector_decision_tree.png'
plt.savefig(chart3_path, bbox_inches='tight', dpi=120)
plt.close()
print(f"  Chart 3 saved → {chart3_path}")

print("\n" + "=" * 78)
print(f"Done. Total runtime: {time.time() - START_TIME:.0f}s")
print("=" * 78)
