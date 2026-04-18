#!/usr/bin/env python3
"""
K487: GJR-GARCH-X(VIX) Cross-Asset Validation
===============================================
Background:
  K486: GJR-X(VIX) broke the "impossible triangle" on SPY:
    - Forecasting improvement: -17% QLIKE (mean across 5 OOS periods)
    - VaR: 5/5 periods pass Trinity at 1% and 5%
  K462: GARCH-X(VIX) on Taiwan 0050.TW: IS significant delta but OOS worse
  K483: Commodity leverage is inverted -> GJR-X(VIX) may not apply

Core Question:
  Is the GJR-X(VIX) success SPY-specific, equity-specific, or cross-asset general?
  VIX is SPY's implied vol -> strongest signal for SPY/QQQ.
  For TLT/GLD/EEM, VIX is a cross-market fear proxy, not native IV.

Assets (6, covering different asset classes):
  1. SPY  -- US large-cap equity (control, K486 validated)
  2. QQQ  -- US tech equity (high SPY correlation)
  3. EEM  -- Emerging markets equity
  4. TLT  -- US long-term bonds
  5. GLD  -- Gold
  6. 0050.TW -- Taiwan equity (lag-1 VIX for timezone)

Model:
  GJR-GARCH-X(VIX):
    h_t = omega + alpha*eps^2_{t-1} + gamma*I(eps<0)*eps^2_{t-1} + beta*h_{t-1} + delta*VIX^2_{t-1}/252

  Baseline: GJR-GARCH(1,1) (no VIX)

OOS: 2023-2024 (single period, same as K486 period 5)
IS: 2000 trading days rolling window
Refit: every 21 days

Evaluation:
  - QLIKE with r^2 proxy (Patton 2011)
  - Diebold-Mariano test
  - VaR Trinity at 1% (Kupiec + Christoffersen + DQ)
  - delta coefficient statistics per asset

Efficiency: 6 assets x 2 models x ~24 refits = 288 fits, target < 3 min
  Key: between refits, use cached params + forward recursion (no re-MLE)

Data: yfinance -- empirical data
Refs:
  Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models
  Christoffersen (1998) Evaluating Interval Forecasts, International Economic Review
  Engle & Manganelli (2004) CAViaR: Conditional Autoregressive VaR, JBES
  Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE
  Hansen & Lunde (2005) A Forecast Comparison of Volatility Models, JoAE
  Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES
  K486 (GJR-X(VIX) SPY final validation)
  K462 (Taiwan 0050.TW methods)
  K483 (Commodity volatility -- inverted leverage)
Author: [Proposed: User, Executed: Claude]
"""

import sys
import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.special import gammaln
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')
# Force unbuffered output for real-time progress
sys.stdout.reconfigure(line_buffering=True)

print("=" * 70)
print("K487: GJR-GARCH-X(VIX) Cross-Asset Validation")
print("  6 assets x 2 models x OOS 2023-2024 x QLIKE + VaR Trinity")
print("  Core Q: Is GJR-X(VIX) cross-asset or SPY-specific?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
REFIT_INTERVAL = 21
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2005-01-01"

ASSETS = {
    'SPY': {'name': 'S&P 500 ETF', 'class': 'US equity', 'vix_lag': 0,
            'note': 'Control (K486 validated). VIX is SPY implied vol.'},
    'QQQ': {'name': 'Nasdaq 100 ETF', 'class': 'US equity', 'vix_lag': 0,
            'note': 'High SPY correlation. VIX relevant via market-wide fear.'},
    'EEM': {'name': 'Emerging Markets ETF', 'class': 'EM equity', 'vix_lag': 0,
            'note': 'VIX as cross-market fear proxy, not native IV.'},
    'TLT': {'name': 'US 20+ Year Treasury ETF', 'class': 'US bonds', 'vix_lag': 0,
            'note': 'Bonds. VIX measures equity fear, not bond vol. Flight-to-quality link.'},
    'GLD': {'name': 'Gold ETF', 'class': 'commodity', 'vix_lag': 0,
            'note': 'Gold. VIX as risk-off indicator. K483: commodity leverage inverted.'},
    '0050.TW': {'name': 'Taiwan 50 ETF', 'class': 'Taiwan equity', 'vix_lag': 1,
                'note': 'Taiwan. VIX lagged 1 day for timezone (US close -> TW next day).'},
}

# ============================================================
# Helper Functions
# ============================================================

def gjr_garchx_loglik(params, returns, vix_var_lag):
    """
    Custom log-likelihood for GJR-GARCH-X(VIX) with Student-t.
    params = [mu, omega, alpha, gamma, beta, delta, nu]
    """
    mu, omega, alpha, gamma, beta, delta, nu = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0
    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * shock2 + gamma * asym + beta * h[t-1] + delta * vix_var_lag[t]
        if h[t] <= 0:
            h[t] = 1e-6
    ll = (
        gammaln((nu + 1) / 2) - gammaln(nu / 2)
        - 0.5 * np.log(np.pi * (nu - 2))
        - 0.5 * np.log(h)
        - (nu + 1) / 2 * np.log(1 + eps**2 / (h * (nu - 2)))
    )
    return -np.sum(ll)


def fit_gjr_garchx(returns_pct, vix_daily_var):
    """Fit GJR-GARCH-X(VIX) via custom MLE. Returns dict or None."""
    T = len(returns_pct)
    ret = returns_pct.copy()
    vix_lag = np.zeros(T)
    vix_lag[1:] = vix_daily_var[:-1]
    vix_lag[0] = vix_daily_var[0]

    mu0 = np.mean(ret)
    x0 = [mu0, 0.01, 0.05, 0.05, 0.90, 0.01, 6.0]
    bounds = [
        (-1.0, 1.0), (1e-6, 10.0), (1e-6, 0.5),
        (0.0, 0.5), (0.3, 0.999), (0.0, 1.0), (2.1, 50.0),
    ]
    try:
        result = optimize.minimize(
            gjr_garchx_loglik, x0, args=(ret, vix_lag),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )
        if not result.success and result.fun > 1e10:
            return None
        mu, omega, alpha, gamma_val, beta, delta, nu = result.x
        persistence = alpha + gamma_val / 2 + beta
        return {
            'params': {
                'mu': float(mu), 'omega': float(omega),
                'alpha': float(alpha), 'gamma': float(gamma_val),
                'beta': float(beta), 'delta': float(delta), 'nu': float(nu),
            },
            'persistence': float(persistence),
            'loglik': float(-result.fun),
            'converged': result.success,
        }
    except Exception:
        return None


def gjrx_forecast_h(params, returns_pct, vix_daily_var):
    """
    Given cached GJR-X params, compute 1-step-ahead h_{T+1} forecast.
    This uses forward recursion through the IS window with cached params
    (NO re-optimization -- just filtering).
    returns_pct: IS window returns in %
    vix_daily_var: IS window VIX^2/252 in %^2
    Returns h_{T+1} in %^2, or None on failure.
    """
    mu = params['mu']
    omega = params['omega']
    alpha = params['alpha']
    gamma_val = params['gamma']
    beta = params['beta']
    delta = params['delta']

    T = len(returns_pct)
    eps = returns_pct - mu

    # Lag VIX
    vix_lag = np.zeros(T)
    vix_lag[1:] = vix_daily_var[:-1]
    vix_lag[0] = vix_daily_var[0]

    # Forward recursion
    h = np.zeros(T)
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0
    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * shock2 + gamma_val * asym + beta * h[t-1] + delta * vix_lag[t]
        if h[t] <= 0:
            h[t] = 1e-6

    # 1-step ahead
    shock2_last = eps[-1]**2
    asym_last = shock2_last * (1.0 if eps[-1] < 0 else 0.0)
    h_fcast = omega + alpha * shock2_last + gamma_val * asym_last + beta * h[-1] + delta * vix_daily_var[-1]
    if h_fcast <= 0:
        h_fcast = 1e-6
    return float(h_fcast)


def fit_gjr_garch(returns_pct):
    """Standard GJR-GARCH(1,1) with Student-t via arch package."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        return res
    except Exception:
        return None


# VaR Test Functions
def kupiec_test(violations, n_total, alpha):
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_total if n_total > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0
    lr = -2 * (n_viol * np.log(alpha / p_hat) +
               (n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)))
    pval = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(pval)


def christoffersen_test(violations):
    n = len(violations)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i-1] == 0 and violations[i] == 0: n00 += 1
        elif violations[i-1] == 0 and violations[i] == 1: n01 += 1
        elif violations[i-1] == 1 and violations[i] == 0: n10 += 1
        else: n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n
    if p == 0 or p == 1 or p01 == 0 or p01 == 1 or p11 == 0 or p11 == 1:
        return 0.0, 1.0
    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(pval)


def dq_test(violations, var_forecasts, n_lags=4):
    alpha = np.mean(violations)
    if alpha <= 0 or alpha >= 1:
        return 0.0, 1.0
    hit = violations.astype(float) - alpha
    T = len(hit)
    if T <= n_lags + 2:
        return 0.0, 1.0
    y = hit[n_lags:]
    X_cols = [np.ones(T - n_lags)]
    for lag in range(1, n_lags + 1):
        X_cols.append(hit[n_lags - lag:T - lag])
    X_cols.append(var_forecasts[n_lags:])
    X = np.column_stack(X_cols)
    try:
        XtX = X.T @ X
        Xty = X.T @ y
        XtX_inv = np.linalg.inv(XtX)
        dq_stat = float(Xty.T @ XtX_inv @ Xty / (alpha * (1 - alpha)))
        k = X.shape[1]
        dq_pval = 1 - stats.chi2.cdf(dq_stat, df=k)
        return float(dq_stat), float(dq_pval)
    except Exception:
        return 0.0, 1.0


def run_var_trinity(violations, var_forecasts, n_total, alpha_level):
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n_total if n_total > 0 else 0
    kup_stat, kup_p = kupiec_test(violations, n_total, alpha_level)
    chr_stat, chr_p = christoffersen_test(violations)
    dq_stat, dq_p = dq_test(violations, var_forecasts)
    kupiec_pass = bool(kup_p > 0.05)
    chris_pass = bool(chr_p > 0.05)
    dq_pass = bool(dq_p > 0.05)
    n_pass = int(kupiec_pass) + int(chris_pass) + int(dq_pass)
    return {
        'n_obs': n_total, 'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4), 'expected_rate': alpha_level,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4), 'pass': kupiec_pass},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(chr_p, 4), 'pass': chris_pass},
        'dq': {'stat': round(dq_stat, 4), 'p_value': round(dq_p, 4), 'pass': dq_pass},
        'trinity_pass': n_pass == 3, 'tests_passed': f"{n_pass}/3",
    }


def diebold_mariano_test(loss1, loss2, h=1):
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    V = gamma_0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        V += 2 * (1 - k / h) * gamma_k
    if V <= 0:
        return 0.0, 1.0
    dm_stat = d_bar / np.sqrt(V / T)
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_pval)


# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
sys.stdout.flush()
t_start_total = time.time()

vix_raw = yf.download('^VIX', start=DATA_START, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].astype(float)
if hasattr(vix_close, 'values') and vix_close.ndim > 1:
    vix_close = vix_close.iloc[:, 0]
print(f"  VIX: {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")

asset_data = {}
for ticker, info in ASSETS.items():
    start = '2008-01-01' if ticker == '0050.TW' else DATA_START
    raw = yf.download(ticker, start=start, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw['Close'].astype(float)
    if hasattr(close, 'values') and close.ndim > 1:
        close = close.iloc[:, 0]
    asset_data[ticker] = {'close': close, 'raw': raw}
    print(f"  {ticker}: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")

sys.stdout.flush()

# ============================================================
# 2. PROCESS EACH ASSET
# ============================================================
print("\n[2] Processing assets...")
sys.stdout.flush()

all_results = {}
summary_table = []

for ticker, info in ASSETS.items():
    print(f"\n{'='*60}")
    print(f"  Asset: {ticker} ({info['name']}) -- {info['class']}")
    print(f"  Note: {info['note']}")
    print(f"{'='*60}")
    sys.stdout.flush()

    close = asset_data[ticker]['close']

    # Returns in %
    log_ret = np.log(close / close.shift(1)) * 100
    r2_proxy = (np.log(close / close.shift(1)))**2  # decimal^2

    df_asset = pd.DataFrame({
        'return_pct': log_ret,
        'r2_proxy': r2_proxy,
    }, index=close.index)

    # VIX daily variance: VIX^2/252 in %^2
    vix_var = (vix_close**2 / 252.0)

    # For Taiwan, lag VIX by 1 additional day (timezone)
    if info['vix_lag'] > 0:
        vix_var_series = vix_var.shift(info['vix_lag'])
    else:
        vix_var_series = vix_var

    df_vix = pd.DataFrame({'vix_daily_var': vix_var_series}, index=vix_var_series.index)

    feat = df_asset.join(df_vix, how='inner').dropna()
    print(f"  Combined: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")

    # Diagnostics
    ret = feat['return_pct'].values
    adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
    arch_stat_val, arch_p, _, _ = het_arch(ret, nlags=10)
    lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)

    diagnostics = {
        'n_obs': len(feat),
        'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
        'return_mean_pct': float(np.mean(ret)),
        'return_std_pct': float(np.std(ret)),
        'return_skew': float(stats.skew(ret)),
        'return_kurt': float(stats.kurtosis(ret)),
        'adf_stat': float(adf_stat),
        'adf_p': float(adf_p),
        'is_stationary': bool(adf_p < 0.05),
        'arch_lm_stat': float(arch_stat_val),
        'arch_lm_p': float(arch_p),
        'has_arch_effects': bool(arch_p < 0.05),
        'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
        'vix_daily_var_mean': float(feat['vix_daily_var'].mean()),
        'return_var_pct2': float(np.var(ret)),
        'corr_vix_var_r2': float(feat['vix_daily_var'].corr(feat['r2_proxy'])),
    }

    print(f"  Stationary: {'YES' if diagnostics['is_stationary'] else 'NO'} (ADF p={adf_p:.2e})")
    print(f"  ARCH effects: {'YES' if diagnostics['has_arch_effects'] else 'NO'} (p={arch_p:.2e})")
    print(f"  Corr(VIX_var, r^2): {diagnostics['corr_vix_var_r2']:.4f}")
    print(f"  Return: mean={np.mean(ret):.4f}%, std={np.std(ret):.4f}%, skew={stats.skew(ret):.2f}, kurt={stats.kurtosis(ret):.2f}")
    sys.stdout.flush()

    # OOS backtest
    oos_mask = (feat.index >= OOS_START) & (feat.index <= OOS_END)
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data")
        all_results[ticker] = {'status': 'skipped', 'reason': 'no OOS data'}
        continue

    first_oos_loc = feat.index.get_loc(oos_dates[0])
    if first_oos_loc < IS_WINDOW:
        print(f"  SKIP: insufficient IS data ({first_oos_loc} < {IS_WINDOW})")
        all_results[ticker] = {'status': 'skipped', 'reason': f'insufficient IS ({first_oos_loc} < {IS_WINDOW})'}
        continue

    n_oos = len(oos_dates)
    is_start_date = feat.index[first_oos_loc - IS_WINDOW]
    print(f"  IS start: {is_start_date.date()} ({IS_WINDOW} obs)")
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")
    sys.stdout.flush()

    # Storage
    sigma2_gjr = np.full(n_oos, np.nan)
    sigma2_gjrx = np.full(n_oos, np.nan)
    actual_returns = np.full(n_oos, np.nan)
    actual_r2 = np.full(n_oos, np.nan)
    deltas_list = []
    nu_gjr_list = []
    nu_gjrx_list = []

    # Cached model results
    cached_gjr_params = None  # arch result params for starting_values
    cached_gjrx_params = None  # dict of {mu, omega, alpha, gamma, beta, delta, nu}
    last_fit_idx = -REFIT_INTERVAL
    fit_count = 0
    gjrx_fail_count = 0

    t_asset = time.time()

    for i, oos_date in enumerate(oos_dates):
        oos_loc = feat.index.get_loc(oos_date)
        actual_returns[i] = feat.iloc[oos_loc]['return_pct']
        actual_r2[i] = feat.iloc[oos_loc]['r2_proxy']

        need_refit = (i - last_fit_idx >= REFIT_INTERVAL) or (cached_gjr_params is None)

        window_start = oos_loc - IS_WINDOW
        ret_w = feat.iloc[window_start:oos_loc]['return_pct'].values
        vix_w = feat.iloc[window_start:oos_loc]['vix_daily_var'].values

        if need_refit:
            # Fit GJR baseline
            gjr_res = fit_gjr_garch(ret_w)
            if gjr_res is not None:
                cached_gjr_params = gjr_res.params.values
                nu_gjr_list.append(float(gjr_res.params.get('nu', 6.0)))

            # Fit GJR-X(VIX) -- full MLE only at refit
            gjrx_res = fit_gjr_garchx(ret_w, vix_w)
            if gjrx_res is not None:
                cached_gjrx_params = gjrx_res['params']
                deltas_list.append(gjrx_res['params']['delta'])
                nu_gjrx_list.append(gjrx_res['params']['nu'])
            else:
                gjrx_fail_count += 1

            last_fit_idx = i
            fit_count += 1

        # --- GJR forecast: use arch package with cached starting_values ---
        if cached_gjr_params is not None:
            try:
                am = arch_model(ret_w, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
                res = am.fit(disp='off', show_warning=False, starting_values=cached_gjr_params)
                fc = res.forecast(horizon=1)
                s2 = float(fc.variance.values[-1, 0])
                if s2 > 0 and np.isfinite(s2):
                    sigma2_gjr[i] = s2
            except Exception:
                pass

        # --- GJR-X forecast: forward recursion with cached params (NO re-MLE) ---
        if cached_gjrx_params is not None:
            try:
                h_fcast = gjrx_forecast_h(cached_gjrx_params, ret_w, vix_w)
                if h_fcast is not None and h_fcast > 0 and np.isfinite(h_fcast):
                    sigma2_gjrx[i] = h_fcast
            except Exception:
                pass

        if (i + 1) % 100 == 0:
            print(f"    ... {i+1}/{n_oos} OOS days ({fit_count} refits so far)")
            sys.stdout.flush()

    elapsed_asset = time.time() - t_asset
    print(f"  Completed: {n_oos} OOS days, {fit_count} refits, {elapsed_asset:.1f}s")
    if gjrx_fail_count > 0:
        print(f"  WARNING: GJR-X failed {gjrx_fail_count}/{fit_count} refits")
    sys.stdout.flush()

    # --- QLIKE ---
    valid = np.isfinite(sigma2_gjr) & np.isfinite(sigma2_gjrx) & np.isfinite(actual_r2) & (actual_r2 > 0)
    n_valid = int(np.sum(valid))

    if n_valid < 50:
        print(f"  WARN: only {n_valid} valid forecasts -- insufficient")
        all_results[ticker] = {
            'status': 'insufficient_valid',
            'n_valid': n_valid,
            'diagnostics': diagnostics,
        }
        continue

    r2_v = actual_r2[valid]
    s2_gjr_v = sigma2_gjr[valid]
    s2_gjrx_v = sigma2_gjrx[valid]

    # Convert sigma^2 from %^2 to decimal^2
    s2_gjr_dec = s2_gjr_v / 10000.0
    s2_gjrx_dec = s2_gjrx_v / 10000.0

    qlike_gjr_arr = r2_v / s2_gjr_dec + np.log(s2_gjr_dec)
    qlike_gjrx_arr = r2_v / s2_gjrx_dec + np.log(s2_gjrx_dec)

    qlike_gjr = float(np.mean(qlike_gjr_arr))
    qlike_gjrx = float(np.mean(qlike_gjrx_arr))
    qlike_pct = (qlike_gjrx - qlike_gjr) / abs(qlike_gjr) * 100

    dm_stat, dm_pval = diebold_mariano_test(qlike_gjr_arr, qlike_gjrx_arr, h=1)

    print(f"\n  QLIKE Results:")
    print(f"    GJR:      {qlike_gjr:.6f}")
    print(f"    GJR-X:    {qlike_gjrx:.6f}")
    print(f"    Delta:    {qlike_pct:+.3f}%")
    print(f"    DM stat:  {dm_stat:.4f}, p={dm_pval:.4f}")
    print(f"    GJR-X better: {qlike_gjrx < qlike_gjr}")

    # --- VaR Trinity at 1% ---
    nu_gjr = float(np.median(nu_gjr_list)) if nu_gjr_list else 6.0
    nu_gjrx = float(np.median(nu_gjrx_list)) if nu_gjrx_list else 6.0

    alpha_var = 0.01
    q_gjr = stats.t.ppf(alpha_var, df=nu_gjr)
    q_gjrx = stats.t.ppf(alpha_var, df=nu_gjrx)

    # Standardized Student-t scale factor
    scale_gjr = np.sqrt((nu_gjr - 2) / nu_gjr) if nu_gjr > 2 else 1.0
    scale_gjrx = np.sqrt((nu_gjrx - 2) / nu_gjrx) if nu_gjrx > 2 else 1.0

    var_gjr = np.full(n_oos, np.nan)
    var_gjrx = np.full(n_oos, np.nan)

    for i in range(n_oos):
        if np.isfinite(sigma2_gjr[i]) and sigma2_gjr[i] > 0:
            var_gjr[i] = q_gjr * np.sqrt(sigma2_gjr[i]) * scale_gjr
        if np.isfinite(sigma2_gjrx[i]) and sigma2_gjrx[i] > 0:
            var_gjrx[i] = q_gjrx * np.sqrt(sigma2_gjrx[i]) * scale_gjrx

    valid_var = np.isfinite(var_gjr) & np.isfinite(var_gjrx) & np.isfinite(actual_returns)
    ret_var = actual_returns[valid_var]
    vgjr = var_gjr[valid_var]
    vgjrx = var_gjrx[valid_var]
    n_var = len(ret_var)

    viol_gjr = (ret_var < vgjr).astype(int)
    viol_gjrx = (ret_var < vgjrx).astype(int)

    trinity_gjr = run_var_trinity(viol_gjr, vgjr, n_var, alpha_var)
    trinity_gjrx = run_var_trinity(viol_gjrx, vgjrx, n_var, alpha_var)

    print(f"\n  VaR Trinity (1%):")
    print(f"    GJR:   violations={trinity_gjr['n_violations']}/{n_var} ({trinity_gjr['violation_rate']:.4f}), {trinity_gjr['tests_passed']} pass")
    print(f"    GJR-X: violations={trinity_gjrx['n_violations']}/{n_var} ({trinity_gjrx['violation_rate']:.4f}), {trinity_gjrx['tests_passed']} pass")

    # Delta statistics
    delta_stats = {}
    if deltas_list:
        delta_stats = {
            'mean': float(np.mean(deltas_list)),
            'std': float(np.std(deltas_list)),
            'min': float(np.min(deltas_list)),
            'max': float(np.max(deltas_list)),
            'n_refits': len(deltas_list),
            'all_positive': bool(np.all(np.array(deltas_list) > 0)),
        }
        print(f"\n  Delta (VIX coef): mean={delta_stats['mean']:.4f}, std={delta_stats['std']:.4f}, range=[{delta_stats['min']:.4f}, {delta_stats['max']:.4f}]")
    sys.stdout.flush()

    # Store
    asset_result = {
        'status': 'completed',
        'asset_info': info,
        'diagnostics': diagnostics,
        'oos': {
            'start': OOS_START, 'end': OOS_END,
            'n_oos': n_oos, 'n_valid': n_valid, 'n_refits': fit_count,
        },
        'qlike': {
            'GJR': qlike_gjr,
            'GJR-X(VIX)': qlike_gjrx,
            'relative_pct': round(qlike_pct, 3),
            'DM_stat': round(dm_stat, 4),
            'DM_pval': round(dm_pval, 4),
            'GJR-X_better': bool(qlike_gjrx < qlike_gjr),
            'significant_10pct': bool(dm_pval < 0.10),
            'significant_5pct': bool(dm_pval < 0.05),
        },
        'delta_stats': delta_stats,
        'var_trinity_1pct': {
            'GJR': trinity_gjr,
            'GJR-X(VIX)': trinity_gjrx,
        },
        'nu_estimates': {
            'GJR_median': round(nu_gjr, 2),
            'GJR-X_median': round(nu_gjrx, 2),
        },
        'elapsed_sec': round(elapsed_asset, 1),
    }
    all_results[ticker] = asset_result

    summary_table.append({
        'asset': ticker,
        'class': info['class'],
        'qlike_pct': round(qlike_pct, 2),
        'dm_stat': round(dm_stat, 3),
        'dm_pval': round(dm_pval, 4),
        'gjrx_better': qlike_gjrx < qlike_gjr,
        'sig_10pct': dm_pval < 0.10,
        'gjr_var_pass': trinity_gjr['tests_passed'],
        'gjrx_var_pass': trinity_gjrx['tests_passed'],
        'gjrx_trinity': trinity_gjrx['trinity_pass'],
        'delta_mean': round(delta_stats.get('mean', 0), 4),
        'corr_vix_r2': round(diagnostics['corr_vix_var_r2'], 4),
    })


total_elapsed = time.time() - t_start_total

# ============================================================
# 3. CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

header = f"{'Asset':<10} {'Class':<15} {'QLIKE%':>8} {'DM':>7} {'DM_p':>7} {'Sig':>5} {'GJR_VaR':>8} {'GJRX_VaR':>9} {'Trin':>5} {'delta':>7} {'corr':>7}"
print(f"\n{header}")
print("-" * len(header))

n_qlike_better = 0
n_sig_better = 0
n_trinity_pass = 0
n_completed = 0

for row in summary_table:
    sig_mark = "**" if row['dm_pval'] < 0.05 else ("*" if row['sig_10pct'] else "")
    trin = "PASS" if row['gjrx_trinity'] else "FAIL"
    print(f"{row['asset']:<10} {row['class']:<15} {row['qlike_pct']:>+8.2f} {row['dm_stat']:>7.3f} {row['dm_pval']:>7.4f} {sig_mark:>5} {row['gjr_var_pass']:>8} {row['gjrx_var_pass']:>9} {trin:>5} {row['delta_mean']:>7.4f} {row['corr_vix_r2']:>7.4f}")
    n_completed += 1
    if row['gjrx_better']:
        n_qlike_better += 1
    if row['sig_10pct'] and row['gjrx_better']:
        n_sig_better += 1
    if row['gjrx_trinity']:
        n_trinity_pass += 1

print(f"\nAssets with QLIKE improvement: {n_qlike_better}/{n_completed}")
print(f"Assets with significant improvement (p<0.10): {n_sig_better}/{n_completed}")
print(f"Assets with GJR-X VaR Trinity pass: {n_trinity_pass}/{n_completed}")

# ============================================================
# 4. JUDGEMENT
# ============================================================
print("\n" + "=" * 70)
print("JUDGEMENT")
print("=" * 70)

equity_tickers = [r for r in summary_table if r['class'] in ('US equity', 'EM equity', 'Taiwan equity')]
non_equity = [r for r in summary_table if r['class'] not in ('US equity', 'EM equity', 'Taiwan equity')]

equity_better = sum(1 for r in equity_tickers if r['gjrx_better'])
equity_sig = sum(1 for r in equity_tickers if r['sig_10pct'] and r['gjrx_better'])
non_eq_better = sum(1 for r in non_equity if r['gjrx_better'])

if n_qlike_better >= 4 and n_trinity_pass >= 4:
    verdict = "CROSS-ASSET VALIDATED"
    detail = f"GJR-X(VIX) improves QLIKE in {n_qlike_better}/{n_completed} assets AND passes VaR Trinity in {n_trinity_pass}/{n_completed}."
elif equity_better >= 3 and non_eq_better <= 1:
    verdict = "EQUITY-SPECIFIC"
    detail = f"GJR-X(VIX) works for equities ({equity_better}/{len(equity_tickers)} better) but not other classes ({non_eq_better}/{len(non_equity)})."
elif n_qlike_better >= 4 and n_trinity_pass < 4:
    verdict = "FORECASTING ONLY (VaR degraded)"
    detail = f"QLIKE improvement in {n_qlike_better}/{n_completed} assets, but VaR Trinity pass only in {n_trinity_pass}/{n_completed}."
elif n_qlike_better <= 2:
    verdict = "SPY-SPECIFIC"
    detail = f"Only {n_qlike_better}/{n_completed} assets show QLIKE improvement. VIX is SPY's implied vol."
else:
    verdict = "PARTIAL"
    detail = f"Mixed results: {n_qlike_better}/{n_completed} QLIKE better, {n_sig_better}/{n_completed} significant, {n_trinity_pass}/{n_completed} VaR pass."

print(f"\n  Verdict: {verdict}")
print(f"  Detail: {detail}")
print(f"  Total time: {total_elapsed:.1f}s")

# ============================================================
# 5. SAVE RESULTS
# ============================================================
output = {
    'experiment_id': 'K487',
    'title': 'GJR-GARCH-X(VIX) Cross-Asset Validation',
    'method': 'GJR-GARCH-X with VIX exogenous regressor, 6 assets, OOS 2023-2024',
    'proposed_by': 'User (publication-critical)',
    'data_source': 'yfinance -- empirical data',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'configuration': {
        'IS_window': IS_WINDOW,
        'refit_interval': REFIT_INTERVAL,
        'OOS_period': f'{OOS_START} to {OOS_END}',
        'assets': list(ASSETS.keys()),
        'n_assets': len(ASSETS),
        'models': ['GJR-GARCH(1,1)', 'GJR-GARCH-X(VIX)'],
        'variance_equation_GJRX': 'h_t = omega + alpha*eps^2_{t-1} + gamma*I(eps<0)*eps^2_{t-1} + beta*h_{t-1} + delta*VIX^2_{t-1}/252',
        'loss_function': 'QLIKE (Patton 2011)',
        'VaR_level': 0.01,
        'VaR_tests': ['Kupiec (1995)', 'Christoffersen (1998)', 'DQ (Engle-Manganelli 2004)'],
    },
    'asset_results': {},
    'summary_table': summary_table,
    'cross_asset_summary': {
        'n_completed': n_completed,
        'n_qlike_better': n_qlike_better,
        'n_significant_10pct': n_sig_better,
        'n_trinity_pass': n_trinity_pass,
        'equity_qlike_better': equity_better,
        'equity_count': len(equity_tickers),
        'non_equity_qlike_better': non_eq_better,
        'non_equity_count': len(non_equity),
    },
    'verdict': verdict,
    'verdict_detail': detail,
    'total_elapsed_sec': round(total_elapsed, 1),
    'references': [
        'Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models',
        'Christoffersen (1998) Evaluating Interval Forecasts, International Economic Review',
        'Engle & Manganelli (2004) CAViaR, JBES',
        'Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE',
        'Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES',
        'K486: GJR-X(VIX) SPY final validation -- broke impossible triangle',
        'K462: GARCH-X(VIX) on Taiwan 0050.TW -- IS sig but OOS worse',
        'K483: Commodity volatility -- inverted leverage',
    ],
}

for ticker in ASSETS:
    if ticker in all_results:
        output['asset_results'][ticker] = all_results[ticker]

out_path = 'experiments/k487_gjr_vix_cross_asset_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved: {out_path}")
print(f"\n{'='*70}")
print(f"K487 COMPLETE -- Verdict: {verdict}")
print(f"{'='*70}")
