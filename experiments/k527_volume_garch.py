#!/usr/bin/env python3
"""
K527: Volume-GARCH — Lamoureux & Lastrapes (1990) Framework
============================================================
[提出: 用戶, 執行: Claude]

Literature:
  Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data:
  Volume versus GARCH Effects" Journal of Finance 45(1):221-229
  - Volume as proxy for information arrival rate (MDH)
  - ARCH effects disappear when volume added to variance equation
  - Persistence (α+β) drops dramatically

  Clark (1973) — Mixture of Distributions Hypothesis (MDH)
  Tauchen & Pitts (1983) — formal MDH derivation

Prior experiments:
  K113: volume GARCH-X null — used microstructure proxy, NOT MDH framework
  K135: GLD volume ratio IS sig but OOS null
  K136: BTC volume-conditioned gamma effective (only positive)
  K418: Taiwan volume null (yfinance proxy too coarse)
  K510: Volume-GARCH L&L replication (5 specs) — all OOS null, persistence
        drop is in-sample artifact. BUT K510 used squared return proxy &
        linear detrend — K527 uses |r_t| proxy & ratio detrend.

Key differences from K510:
  1. Detrending: V_t / MA(V, 252) ratio (not linear detrend of log volume)
  2. Proxy: |r_t| for realized vol (not r²_t)
  3. Volume-replacing specification: σ² = ω + δ·V_t + β·σ²_{t-1} (no ARCH term)
  4. Cross-market: 0050.TW (Taiwan, not QQQ)
  5. GJR+Volume specification included

Models (4):
  a. Standard GARCH(1,1): σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
  b. Volume-GARCH: σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1} + δ·V_t
  c. Volume-replacing: σ²_t = ω + δ·V_t + β·σ²_{t-1} (ARCH term removed)
  d. GJR + Volume: σ²_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I_{t-1} + β·σ²_{t-1} + δ·V_t

Assets: SPY (primary) + 0050.TW (cross-market validation)
OOS: 2023-01-01 to 2024-12-31
Window: 2000 (SPY), adaptive for 0050.TW
Refit: every 21 days
Proxy: |r_t| (absolute return)
Evaluation: QLIKE + MSE + DM test (Harvey t>3.0)
  ** QLIKE computed on variance scale: proxy = r²_t, forecast = h_t (both %) **
  ** Then also report QLIKE on |r| scale: proxy = |r_t|, forecast = sqrt(h_t) **

Hypotheses:
  H1: Volume reduces GARCH persistence (α+β drops)
  H2: Volume-GARCH improves OOS forecasting (QLIKE reduction)
  H3: Volume effect is stronger for Taiwan (higher vol, more info asymmetry)

Data: yfinance (daily OHLCV)

References:
  Lamoureux & Lastrapes (1990) JoF 45(1):221-229
  Clark (1973) "A Subordinated Stochastic Process Model" Econometrica
  Tauchen & Pitts (1983) Econometrica
  Hillebrand (2005) — persistence inflation in misspecified GARCH
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies" JoE
  K113, K135, K136, K418, K510 (prior volume experiments)
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats, optimize
from statsmodels.stats.diagnostic import het_arch

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
ASSETS = {
    'SPY': {'start': '2005-01-01', 'end': '2026-03-27', 'window': 2000},
    '0050.TW': {'start': '2005-01-01', 'end': '2026-03-27', 'window': 1500},
}
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 21
DETREND_WINDOW = 252  # 1-year MA for volume detrending

MODEL_NAMES = {
    'garch11': 'GARCH(1,1) baseline',
    'vol_garch': 'Volume-GARCH (GARCH-X)',
    'vol_replacing': 'Volume-replacing (no ARCH term)',
    'gjr_vol': 'GJR-GARCH + Volume',
}

print("=" * 70)
print("K527: Volume-GARCH — Lamoureux & Lastrapes (1990) Framework")
print("=" * 70)
print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
t0_total = time.time()


# ============================================================
# Data download & preparation
# ============================================================
def download_data():
    """Download daily OHLCV for SPY and 0050.TW."""
    data = {}
    for ticker, cfg in ASSETS.items():
        print(f"\n  Downloading {ticker}...")
        df = yf.download(ticker, start=cfg['start'], end=cfg['end'],
                         progress=False, auto_adjust=True)
        if len(df) > 500:
            data[ticker] = df
            print(f"    {ticker}: {len(df)} obs ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"    {ticker}: insufficient data ({len(df)} obs), skipping")
    return data


def prepare_features(df, ticker):
    """
    Prepare returns (in %), realized vol proxy (|r|, raw scale), and detrended volume.
    Also cleans extreme outliers for 0050.TW.
    """
    close = df['Close'].squeeze()
    volume = df['Volume'].squeeze()

    # Returns in percent (for arch-style estimation)
    log_ret_pct = np.log(close / close.shift(1)) * 100
    # Returns in raw scale (for proxy)
    log_ret_raw = np.log(close / close.shift(1))

    # Realized volatility proxies (raw scale)
    abs_ret = np.abs(log_ret_raw)       # |r_t| — for evaluation
    sq_ret = log_ret_raw ** 2            # r²_t — for QLIKE on variance scale

    # Detrended volume: V_t / MA(V_t, 252)
    vol_ma = volume.rolling(DETREND_WINDOW, min_periods=100).mean()
    detrended_vol = volume / vol_ma

    result = pd.DataFrame({
        'ret_pct': log_ret_pct,
        'ret_raw': log_ret_raw,
        'abs_ret': abs_ret,
        'sq_ret': sq_ret,
        'volume': volume,
        'detrended_vol': detrended_vol,
    })

    result = result.dropna()

    # Clean extreme outliers for 0050.TW (detrended volume)
    # Cap at 99.9th percentile to avoid volume spikes distorting estimation
    vol_cap = result['detrended_vol'].quantile(0.999)
    n_capped = (result['detrended_vol'] > vol_cap).sum()
    if n_capped > 0:
        print(f"  Capping {n_capped} extreme detrended volume values at {vol_cap:.2f}")
        result['detrended_vol'] = result['detrended_vol'].clip(upper=vol_cap)

    # Also cap extreme returns (|r| > 20% = 20 in % scale)
    ret_cap = 20.0  # percent
    n_ret_capped = (result['ret_pct'].abs() > ret_cap).sum()
    if n_ret_capped > 0:
        print(f"  Capping {n_ret_capped} extreme return values at +/-{ret_cap}%")
        result['ret_pct'] = result['ret_pct'].clip(-ret_cap, ret_cap)

    # Descriptive stats
    print(f"\n  {ticker} Data Summary:")
    print(f"    Observations: {len(result)}")
    print(f"    Returns (%): mean={result['ret_pct'].mean():.4f}, std={result['ret_pct'].std():.4f}")
    print(f"    |r| (raw): mean={result['abs_ret'].mean():.6f}, std={result['abs_ret'].std():.6f}")
    print(f"    Detrended vol: mean={result['detrended_vol'].mean():.4f}, "
          f"std={result['detrended_vol'].std():.4f}, "
          f"min={result['detrended_vol'].min():.4f}, max={result['detrended_vol'].max():.4f}")
    print(f"    Skewness(ret%): {result['ret_pct'].skew():.4f}")
    print(f"    Kurtosis(ret%): {result['ret_pct'].kurtosis():.4f}")

    return result


# ============================================================
# Custom GARCH models via MLE (4 specifications)
# All return h in % SQUARED units (matching returns in %)
# ============================================================

def garch11_loglik(params, returns):
    """
    Standard GARCH(1,1): h_t = ω + α·ε²_{t-1} + β·h_{t-1}
    params: [mu, omega, alpha, beta]
    returns: in % units
    h: in %² units
    """
    mu, omega, alpha, beta = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        h[t] = omega + alpha * eps[t-1]**2 + beta * h[t-1]
        if h[t] <= 0:
            h[t] = 1e-8

    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10


def vol_garch_loglik(params, returns, x_vol):
    """
    Volume-GARCH: h_t = ω + α·ε²_{t-1} + β·h_{t-1} + δ·V_t
    params: [mu, omega, alpha, beta, delta]
    """
    mu, omega, alpha, beta, delta = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        h[t] = omega + alpha * eps[t-1]**2 + beta * h[t-1] + delta * x_vol[t]
        if h[t] <= 0:
            h[t] = 1e-8

    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10


def vol_replacing_loglik(params, returns, x_vol):
    """
    Volume-replacing: h_t = ω + δ·V_t + β·h_{t-1} (NO ARCH term)
    params: [mu, omega, delta, beta]
    """
    mu, omega, delta, beta = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        h[t] = omega + delta * x_vol[t] + beta * h[t-1]
        if h[t] <= 0:
            h[t] = 1e-8

    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10


def gjr_vol_loglik(params, returns, x_vol):
    """
    GJR-GARCH + Volume:
    h_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I(ε<0) + β·h_{t-1} + δ·V_t
    params: [mu, omega, alpha, gamma, beta, delta]
    """
    mu, omega, alpha, gamma, beta, delta = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        indicator = 1.0 if eps[t-1] < 0 else 0.0
        h[t] = (omega + alpha * eps[t-1]**2
                + gamma * eps[t-1]**2 * indicator
                + beta * h[t-1]
                + delta * x_vol[t])
        if h[t] <= 0:
            h[t] = 1e-8

    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10


def fit_model(model_type, returns, x_vol=None, verbose=False):
    """
    Fit one of the 4 model specifications via MLE (L-BFGS-B).
    Returns h in %² units.
    """
    T = len(returns)

    # Get initial values from a quick GARCH fit
    try:
        from arch import arch_model
        am = arch_model(pd.Series(returns), vol='GARCH', p=1, q=1,
                        mean='Constant', dist='normal')
        res0 = am.fit(disp='off')
        mu0 = res0.params['mu']
        omega0 = res0.params['omega']
        alpha0 = res0.params.get('alpha[1]', 0.05)
        beta0 = res0.params.get('beta[1]', 0.85)
    except Exception:
        mu0 = np.mean(returns)
        omega0 = 0.01
        alpha0 = 0.05
        beta0 = 0.85

    if model_type == 'garch11':
        x0 = [mu0, omega0, alpha0, beta0]
        bounds = [(None, None), (1e-8, None), (1e-8, 0.5), (1e-8, 0.9999)]
        func = lambda p: garch11_loglik(p, returns)

    elif model_type == 'vol_garch':
        x0 = [mu0, omega0, alpha0, beta0, 0.001]
        bounds = [(None, None), (1e-8, None), (1e-8, 0.5), (1e-8, 0.9999), (None, None)]
        func = lambda p: vol_garch_loglik(p, returns, x_vol)

    elif model_type == 'vol_replacing':
        x0 = [mu0, omega0, 0.01, beta0]
        bounds = [(None, None), (1e-8, None), (None, None), (1e-8, 0.9999)]
        func = lambda p: vol_replacing_loglik(p, returns, x_vol)

    elif model_type == 'gjr_vol':
        x0 = [mu0, omega0, alpha0, 0.05, beta0, 0.001]
        bounds = [(None, None), (1e-8, None), (1e-8, 0.5), (0.0, 0.5),
                  (1e-8, 0.9999), (None, None)]
        func = lambda p: gjr_vol_loglik(p, returns, x_vol)

    else:
        raise ValueError(f"Unknown model_type: {model_type}")

    try:
        res = optimize.minimize(
            func, x0, method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )

        if not res.success and verbose:
            print(f"    Optimization warning: {res.message}")

        params = res.x
        loglik = -res.fun
        nparams = len(params)
        aic = -2 * loglik + 2 * nparams
        bic = -2 * loglik + np.log(T) * nparams

        # Compute conditional variance h (in %² units)
        mu = params[0]
        eps = returns - mu
        h = np.zeros(T)
        h[0] = np.var(returns)

        if model_type == 'garch11':
            _, omega, alpha, beta = params
            for t in range(1, T):
                h[t] = omega + alpha * eps[t-1]**2 + beta * h[t-1]
                if h[t] <= 0: h[t] = 1e-8

        elif model_type == 'vol_garch':
            _, omega, alpha, beta, delta = params
            for t in range(1, T):
                h[t] = omega + alpha * eps[t-1]**2 + beta * h[t-1] + delta * x_vol[t]
                if h[t] <= 0: h[t] = 1e-8

        elif model_type == 'vol_replacing':
            _, omega, delta, beta = params
            for t in range(1, T):
                h[t] = omega + delta * x_vol[t] + beta * h[t-1]
                if h[t] <= 0: h[t] = 1e-8

        elif model_type == 'gjr_vol':
            _, omega, alpha, gamma, beta, delta = params
            for t in range(1, T):
                indicator = 1.0 if eps[t-1] < 0 else 0.0
                h[t] = (omega + alpha * eps[t-1]**2
                        + gamma * eps[t-1]**2 * indicator
                        + beta * h[t-1]
                        + delta * x_vol[t])
                if h[t] <= 0: h[t] = 1e-8

        std_resid = eps / np.sqrt(h)

        # Persistence calculation
        if model_type == 'garch11':
            persistence = params[2] + params[3]  # α + β
        elif model_type == 'vol_garch':
            persistence = params[2] + params[3]  # α + β (without δ)
        elif model_type == 'vol_replacing':
            persistence = params[3]  # β only (no ARCH)
        elif model_type == 'gjr_vol':
            persistence = params[2] + params[3] / 2 + params[4]  # α + γ/2 + β

        return {
            'params': [float(p) for p in params],
            'persistence': float(persistence),
            'loglik': float(loglik),
            'aic': float(aic),
            'bic': float(bic),
            'h': h,          # in %² units
            'std_resid': std_resid,
            'mu': float(mu),
            'success': True,
        }
    except Exception as e:
        if verbose:
            print(f"    Fit failed: {e}")
        return {'success': False, 'error': str(e)}


# ============================================================
# Forecast generation: 1-step-ahead h_t+1 given info at t
# ============================================================
def forecast_one_step(model_type, params, eps_t, h_t, v_tp1=None):
    """
    Generate 1-step-ahead variance forecast h_{t+1}.

    For volume models, v_tp1 is the LAGGED volume (V_t, known at time t).
    This ensures no look-ahead bias: we use yesterday's volume to forecast
    today's variance.

    Returns h_{t+1} in %² units.
    """
    if model_type == 'garch11':
        _, omega, alpha, beta = params
        h_new = omega + alpha * eps_t**2 + beta * h_t

    elif model_type == 'vol_garch':
        _, omega, alpha, beta, delta = params
        h_new = omega + alpha * eps_t**2 + beta * h_t + delta * v_tp1

    elif model_type == 'vol_replacing':
        _, omega, delta, beta = params
        h_new = omega + delta * v_tp1 + beta * h_t

    elif model_type == 'gjr_vol':
        _, omega, alpha, gamma, beta, delta = params
        indicator = 1.0 if eps_t < 0 else 0.0
        h_new = (omega + alpha * eps_t**2
                + gamma * eps_t**2 * indicator
                + beta * h_t
                + delta * v_tp1)

    if h_new <= 0:
        h_new = 1e-8

    return h_new


# ============================================================
# ARCH-LM test
# ============================================================
def arch_lm_test(resid, lags=10):
    """ARCH-LM test on standardized residuals."""
    try:
        clean = resid[np.isfinite(resid)]
        if len(clean) < lags + 10:
            return np.nan, np.nan
        lm_stat, lm_pval, _, _ = het_arch(clean, nlags=lags)
        return float(lm_stat), float(lm_pval)
    except Exception:
        return np.nan, np.nan


# ============================================================
# DM test (Diebold-Mariano with Newey-West HAC)
# ============================================================
def dm_test_hac(loss1, loss2, max_lag=None):
    """
    Diebold-Mariano test with Newey-West HAC standard errors.
    H0: E[loss1 - loss2] = 0
    Positive t-stat → model 2 is better (lower loss).
    """
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    if max_lag is None:
        max_lag = int(np.floor(n ** (1/3)))

    # Newey-West variance estimator
    gamma0 = np.mean((d - d_bar) ** 2)
    nw_var = gamma0
    for j in range(1, max_lag + 1):
        w = 1 - j / (max_lag + 1)  # Bartlett kernel
        gamma_j = np.mean((d[j:] - d_bar) * (d[:-j] - d_bar))
        nw_var += 2 * w * gamma_j

    if nw_var <= 0:
        return np.nan, np.nan

    se = np.sqrt(nw_var / n)
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return float(t_stat), float(p_val)


# ============================================================
# In-sample analysis
# ============================================================
def in_sample_analysis(features, ticker):
    """
    Full-sample estimation: replicate L&L (1990) persistence drop test.
    """
    print(f"\n{'='*60}")
    print(f"IN-SAMPLE ANALYSIS: {ticker}")
    print(f"{'='*60}")

    ret = features['ret_pct'].values
    dvol = features['detrended_vol'].values

    results = {}

    # Diagnostics first
    from statsmodels.stats.diagnostic import acorr_ljungbox
    try:
        lb_ret = acorr_ljungbox(ret ** 2, lags=[10], return_df=True)
        lb_stat = float(lb_ret['lb_stat'].values[0])
        lb_pval = float(lb_ret['lb_pvalue'].values[0])
        print(f"\n  Ljung-Box(10) on r²: stat={lb_stat:.2f}, p={lb_pval:.6f}")
    except Exception:
        lb_stat, lb_pval = np.nan, np.nan

    from statsmodels.tsa.stattools import adfuller
    try:
        adf_stat, adf_pval = adfuller(ret, maxlag=20)[:2]
        print(f"  ADF test on returns: stat={adf_stat:.4f}, p={adf_pval:.6f}")
    except Exception:
        adf_stat, adf_pval = np.nan, np.nan

    arch_raw_stat, arch_raw_pval = arch_lm_test(ret)
    print(f"  ARCH-LM(10) on returns: stat={arch_raw_stat:.2f}, p={arch_raw_pval:.6f}")

    diagnostics = {
        'n_obs': len(ret),
        'ljungbox_stat': lb_stat, 'ljungbox_pval': lb_pval,
        'adf_stat': float(adf_stat) if np.isfinite(adf_stat) else None,
        'adf_pval': float(adf_pval) if np.isfinite(adf_pval) else None,
        'arch_lm_raw_stat': arch_raw_stat, 'arch_lm_raw_pval': arch_raw_pval,
    }

    for model_type, model_name in MODEL_NAMES.items():
        print(f"\n  [{model_type}] {model_name}...")
        uses_vol = model_type != 'garch11'
        res = fit_model(model_type, ret, x_vol=dvol if uses_vol else None, verbose=True)

        if not res['success']:
            print(f"    FAILED: {res.get('error', 'unknown')}")
            results[model_type] = {'success': False}
            continue

        # ARCH-LM on standardized residuals
        lm_stat, lm_pval = arch_lm_test(res['std_resid'])

        param_dict = {}
        if model_type == 'garch11':
            param_dict = {'mu': res['params'][0], 'omega': res['params'][1],
                          'alpha': res['params'][2], 'beta': res['params'][3]}
        elif model_type == 'vol_garch':
            param_dict = {'mu': res['params'][0], 'omega': res['params'][1],
                          'alpha': res['params'][2], 'beta': res['params'][3],
                          'delta': res['params'][4]}
        elif model_type == 'vol_replacing':
            param_dict = {'mu': res['params'][0], 'omega': res['params'][1],
                          'delta': res['params'][2], 'beta': res['params'][3]}
        elif model_type == 'gjr_vol':
            param_dict = {'mu': res['params'][0], 'omega': res['params'][1],
                          'alpha': res['params'][2], 'gamma': res['params'][3],
                          'beta': res['params'][4], 'delta': res['params'][5]}

        results[model_type] = {
            'success': True,
            'params': param_dict,
            'persistence': res['persistence'],
            'loglik': res['loglik'],
            'aic': res['aic'],
            'bic': res['bic'],
            'arch_lm_stat': lm_stat,
            'arch_lm_pval': lm_pval,
        }

        print(f"    Persistence: {res['persistence']:.6f}")
        print(f"    LogLik: {res['loglik']:.2f}, AIC: {res['aic']:.2f}, BIC: {res['bic']:.2f}")
        print(f"    ARCH-LM(10): stat={lm_stat:.2f}, p={lm_pval:.6f}")
        for k, v in param_dict.items():
            if v is not None:
                print(f"    {k}: {v:.6f}")

    # Persistence comparison
    if results.get('garch11', {}).get('success') and results.get('vol_garch', {}).get('success'):
        base_p = results['garch11']['persistence']
        vol_p = results['vol_garch']['persistence']
        drop = (base_p - vol_p) / base_p * 100
        print(f"\n  H1 TEST — Persistence Drop:")
        print(f"    Baseline α+β = {base_p:.6f}")
        print(f"    Volume-GARCH α+β = {vol_p:.6f}")
        print(f"    Drop = {drop:.2f}%")
        results['persistence_drop_pct'] = drop

    if results.get('vol_replacing', {}).get('success'):
        repl_p = results['vol_replacing']['persistence']
        print(f"    Volume-replacing β = {repl_p:.6f}")

    return results, diagnostics


# ============================================================
# OOS rolling forecast (FIXED: proper units + no look-ahead)
# ============================================================
def oos_rolling_forecast(features, ticker, window):
    """
    Rolling window OOS forecast for all 4 model specifications.
    Refit every REFIT_EVERY days.

    Key design decisions:
    - h is in %² units throughout (matching returns in %)
    - Forecast h_{t+1} uses info up to time t only
    - Volume: use V_t (lagged, known at t) to forecast h_{t+1}
    - Evaluation proxy: |r_t| for vol, r²_t for variance (Patton 2011)
    - QLIKE computed on BOTH scales for robustness
    """
    print(f"\n{'='*60}")
    print(f"OOS ROLLING FORECAST: {ticker}")
    print(f"{'='*60}")

    # Identify OOS period
    oos_mask = (features.index >= OOS_START) & (features.index <= OOS_END)
    oos_idx = features.index[oos_mask]

    if len(oos_idx) < 100:
        print(f"  Insufficient OOS data: {len(oos_idx)} days (need >=100)")
        return None

    print(f"  OOS period: {oos_idx[0].date()} to {oos_idx[-1].date()} ({len(oos_idx)} days)")
    print(f"  Window: {window}, Refit every: {REFIT_EVERY} days")

    ret_pct = features['ret_pct'].values   # returns in %
    dvol = features['detrended_vol'].values
    abs_ret = features['abs_ret'].values   # |r_t| raw scale
    sq_ret = features['sq_ret'].values     # r²_t raw scale
    dates = features.index

    # Find OOS indices
    oos_start_iloc = np.where(dates >= pd.Timestamp(OOS_START))[0]
    if len(oos_start_iloc) == 0:
        print("  Cannot find OOS start index")
        return None
    oos_start_iloc = oos_start_iloc[0]

    oos_end_iloc = np.where(dates <= pd.Timestamp(OOS_END))[0]
    if len(oos_end_iloc) == 0:
        print("  Cannot find OOS end index")
        return None
    oos_end_iloc = oos_end_iloc[-1]

    if oos_start_iloc < window:
        window = max(500, oos_start_iloc - 50)
        print(f"  Adaptive window: {window}")

    n_oos = oos_end_iloc - oos_start_iloc + 1
    print(f"  OOS observations: {n_oos}")

    # Storage: h forecasts in %² units
    h_forecasts = {k: np.full(n_oos, np.nan) for k in MODEL_NAMES.keys()}
    actual_abs_ret = np.full(n_oos, np.nan)
    actual_sq_ret = np.full(n_oos, np.nan)

    # Cache: (params, last_h, last_mu)
    cached = {k: None for k in MODEL_NAMES.keys()}
    last_fit_i = -REFIT_EVERY  # force initial fit

    t0 = time.time()

    for i in range(n_oos):
        t_idx = oos_start_iloc + i
        if t_idx >= len(ret_pct):
            break

        # Actual proxies (raw scale)
        actual_abs_ret[i] = abs_ret[t_idx]
        actual_sq_ret[i] = sq_ret[t_idx]

        # Refit if needed
        if i - last_fit_i >= REFIT_EVERY or i == 0:
            train_start = max(0, t_idx - window)
            train_end = t_idx  # exclusive: data up to t-1
            train_ret = ret_pct[train_start:train_end]
            train_dvol = dvol[train_start:train_end]

            for model_type in MODEL_NAMES.keys():
                uses_vol = model_type != 'garch11'
                res = fit_model(model_type, train_ret,
                                x_vol=train_dvol if uses_vol else None)
                if res['success']:
                    # Store params + last h and mu from training
                    cached[model_type] = {
                        'params': res['params'],
                        'h_last': res['h'][-1],  # h at end of training period
                        'mu': res['mu'],
                    }

            last_fit_i = i

        # Generate 1-step-ahead forecast for each model
        # Need: eps_{t-1} = r_{t-1} - mu, h_{t-1} (from last step), V_{t-1} (lagged)
        for model_type in MODEL_NAMES.keys():
            if cached[model_type] is None:
                continue

            params = cached[model_type]['params']
            mu = cached[model_type]['mu']

            # Previous return (known at time t)
            if t_idx == 0:
                continue
            eps_prev = ret_pct[t_idx - 1] - mu

            # Previous h: either from last forecast or from training
            if i == 0 or np.isnan(h_forecasts[model_type][i-1]):
                h_prev = cached[model_type]['h_last']
            else:
                # Use our own previous forecast as h_{t-1}
                h_prev = h_forecasts[model_type][i-1]

            # Volume: use V_{t-1} (lagged, no look-ahead)
            v_lagged = dvol[t_idx - 1] if t_idx > 0 else 1.0

            h_new = forecast_one_step(model_type, params, eps_prev, h_prev,
                                       v_tp1=v_lagged)
            h_forecasts[model_type][i] = h_new

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"    {i+1}/{n_oos} forecasts ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    print(f"  OOS forecasting complete: {elapsed:.1f}s")

    # ---- Evaluation ----
    # QLIKE on VARIANCE scale: proxy = r²_t (raw), forecast = h_t / 10000 (raw)
    # h is in %² → convert to raw: h / (100²) = h / 10000
    # QLIKE = proxy/forecast + log(forecast)

    print(f"\n  EVALUATION:")
    print(f"  (Variance-scale QLIKE: proxy=r²_t, forecast=h/10000)")
    print(f"  (Vol-scale QLIKE: proxy=|r_t|, forecast=sqrt(h)/100)")

    oos_results = {}

    # Baseline evaluation
    h_base = h_forecasts['garch11']
    # Convert h from %² to raw variance: h / 10000
    f_var_base = h_base / 10000.0
    # Convert h from %² to raw std dev: sqrt(h) / 100
    f_vol_base = np.sqrt(np.maximum(h_base, 0)) / 100.0

    valid_base = (np.isfinite(f_var_base) & np.isfinite(actual_sq_ret)
                  & (f_var_base > 0) & np.isfinite(actual_abs_ret))

    if np.sum(valid_base) < 50:
        print(f"  Too few valid baseline forecasts: {np.sum(valid_base)}")
        return None

    # QLIKE on variance scale
    qlike_var_base = actual_sq_ret[valid_base] / f_var_base[valid_base] + np.log(f_var_base[valid_base])
    # QLIKE on vol scale
    qlike_vol_base = actual_abs_ret[valid_base] / f_vol_base[valid_base] + np.log(f_vol_base[valid_base])
    # MSE on vol scale
    mse_base = (actual_abs_ret[valid_base] - f_vol_base[valid_base]) ** 2

    oos_results['garch11'] = {
        'qlike_var': float(np.mean(qlike_var_base)),
        'qlike_vol': float(np.mean(qlike_vol_base)),
        'mse_vol': float(np.mean(mse_base)),
        'n_valid': int(np.sum(valid_base)),
        'mean_h_pct2': float(np.mean(h_base[valid_base])),
        'mean_forecast_vol': float(np.mean(f_vol_base[valid_base])),
        'mean_actual_vol': float(np.mean(actual_abs_ret[valid_base])),
    }
    print(f"\n    GARCH(1,1) baseline:")
    print(f"      QLIKE(var) = {np.mean(qlike_var_base):.6f}")
    print(f"      QLIKE(vol) = {np.mean(qlike_vol_base):.6f}")
    print(f"      MSE(vol) = {np.mean(mse_base):.2e}")
    print(f"      Mean h(%²) = {np.mean(h_base[valid_base]):.4f}")
    print(f"      Mean forecast |r| = {np.mean(f_vol_base[valid_base]):.6f}")
    print(f"      Mean actual |r| = {np.mean(actual_abs_ret[valid_base]):.6f}")

    # Compare each volume model vs baseline
    for model_type in ['vol_garch', 'vol_replacing', 'gjr_vol']:
        h_model = h_forecasts[model_type]
        f_var_model = h_model / 10000.0
        f_vol_model = np.sqrt(np.maximum(h_model, 0)) / 100.0

        valid = (valid_base & np.isfinite(f_var_model)
                 & (f_var_model > 0) & np.isfinite(f_vol_model))

        if np.sum(valid) < 50:
            print(f"\n    {MODEL_NAMES[model_type]}: too few valid ({np.sum(valid)})")
            oos_results[model_type] = {'n_valid': int(np.sum(valid)), 'insufficient': True}
            continue

        # QLIKE on variance scale
        qlike_var_model = actual_sq_ret[valid] / f_var_model[valid] + np.log(f_var_model[valid])
        qlike_var_base_common = actual_sq_ret[valid] / f_var_base[valid] + np.log(f_var_base[valid])

        # QLIKE on vol scale
        qlike_vol_model = actual_abs_ret[valid] / f_vol_model[valid] + np.log(f_vol_model[valid])
        qlike_vol_base_common = actual_abs_ret[valid] / f_vol_base[valid] + np.log(f_vol_base[valid])

        # MSE on vol scale
        mse_model = (actual_abs_ret[valid] - f_vol_model[valid]) ** 2

        # DM tests
        dm_var_stat, dm_var_pval = dm_test_hac(qlike_var_base_common, qlike_var_model)
        dm_vol_stat, dm_vol_pval = dm_test_hac(qlike_vol_base_common, qlike_vol_model)

        harvey_var = abs(dm_var_stat) > 3.0 if np.isfinite(dm_var_stat) else False
        harvey_vol = abs(dm_vol_stat) > 3.0 if np.isfinite(dm_vol_stat) else False

        # QLIKE changes
        qlike_var_mean_base = float(np.mean(qlike_var_base_common))
        qlike_var_mean_model = float(np.mean(qlike_var_model))
        qlike_var_change = (qlike_var_mean_model - qlike_var_mean_base) / abs(qlike_var_mean_base) * 100

        qlike_vol_mean_base = float(np.mean(qlike_vol_base_common))
        qlike_vol_mean_model = float(np.mean(qlike_vol_model))
        qlike_vol_change = (qlike_vol_mean_model - qlike_vol_mean_base) / abs(qlike_vol_mean_base) * 100

        oos_results[model_type] = {
            'qlike_var': qlike_var_mean_model,
            'qlike_vol': qlike_vol_mean_model,
            'mse_vol': float(np.mean(mse_model)),
            'n_valid': int(np.sum(valid)),
            'mean_h_pct2': float(np.mean(h_model[valid])),
            'mean_forecast_vol': float(np.mean(f_vol_model[valid])),
            'mean_actual_vol': float(np.mean(actual_abs_ret[valid])),
            'dm_var_stat': float(dm_var_stat) if np.isfinite(dm_var_stat) else None,
            'dm_var_pval': float(dm_var_pval) if np.isfinite(dm_var_pval) else None,
            'dm_vol_stat': float(dm_vol_stat) if np.isfinite(dm_vol_stat) else None,
            'dm_vol_pval': float(dm_vol_pval) if np.isfinite(dm_vol_pval) else None,
            'qlike_var_change_pct': qlike_var_change,
            'qlike_vol_change_pct': qlike_vol_change,
            'harvey_var_pass': harvey_var,
            'harvey_vol_pass': harvey_vol,
        }

        var_dir = "better" if qlike_var_mean_model < qlike_var_mean_base else "worse"
        vol_dir = "better" if qlike_vol_mean_model < qlike_vol_mean_base else "worse"
        print(f"\n    {MODEL_NAMES[model_type]}:")
        print(f"      QLIKE(var) = {qlike_var_mean_model:.6f} ({var_dir}, {qlike_var_change:+.2f}%)")
        print(f"      QLIKE(vol) = {qlike_vol_mean_model:.6f} ({vol_dir}, {qlike_vol_change:+.2f}%)")
        print(f"      MSE(vol) = {np.mean(mse_model):.2e}")
        print(f"      Mean h(%²) = {np.mean(h_model[valid]):.4f}")
        print(f"      Mean forecast |r| = {np.mean(f_vol_model[valid]):.6f}")
        print(f"      DM(var): t={dm_var_stat:.4f}, p={dm_var_pval:.6f} Harvey={harvey_var}")
        print(f"      DM(vol): t={dm_vol_stat:.4f}, p={dm_vol_pval:.6f} Harvey={harvey_vol}")

    return oos_results


# ============================================================
# Parameter trajectory analysis
# ============================================================
def parameter_trajectory(features, ticker, window):
    """
    Track how volume coefficient δ and persistence change across rolling windows.
    """
    print(f"\n{'='*60}")
    print(f"PARAMETER TRAJECTORY: {ticker}")
    print(f"{'='*60}")

    ret_pct = features['ret_pct'].values
    dvol = features['detrended_vol'].values
    dates = features.index

    # Sample at 63-day (quarterly) intervals
    sample_points = list(range(window, len(ret_pct), 63))
    if len(sample_points) > 30:
        # Subsample to keep it manageable
        sample_points = sample_points[::2]

    trajectories = {
        'dates': [],
        'baseline_persistence': [],
        'vol_garch_persistence': [],
        'vol_garch_delta': [],
        'gjr_vol_persistence': [],
        'gjr_vol_delta': [],
    }

    for idx in sample_points:
        train_ret = ret_pct[idx - window:idx]
        train_dvol = dvol[idx - window:idx]

        # Baseline
        res_base = fit_model('garch11', train_ret)
        # Vol-GARCH
        res_vol = fit_model('vol_garch', train_ret, x_vol=train_dvol)
        # GJR + Vol
        res_gjr = fit_model('gjr_vol', train_ret, x_vol=train_dvol)

        if res_base['success'] and res_vol['success'] and res_gjr['success']:
            trajectories['dates'].append(str(dates[idx].date()))
            trajectories['baseline_persistence'].append(res_base['persistence'])
            trajectories['vol_garch_persistence'].append(res_vol['persistence'])
            trajectories['vol_garch_delta'].append(res_vol['params'][4])
            trajectories['gjr_vol_persistence'].append(res_gjr['persistence'])
            trajectories['gjr_vol_delta'].append(res_gjr['params'][5])

    if len(trajectories['dates']) > 0:
        # Summary statistics
        mean_base_p = np.mean(trajectories['baseline_persistence'])
        mean_vol_p = np.mean(trajectories['vol_garch_persistence'])
        mean_delta = np.mean(trajectories['vol_garch_delta'])
        mean_drop = (mean_base_p - mean_vol_p) / mean_base_p * 100

        print(f"\n  Across {len(trajectories['dates'])} rolling windows:")
        print(f"    Mean baseline persistence: {mean_base_p:.6f}")
        print(f"    Mean volume-GARCH persistence: {mean_vol_p:.6f}")
        print(f"    Mean persistence drop: {mean_drop:.2f}%")
        print(f"    Mean δ (volume coeff): {mean_delta:.6f}")
        print(f"    δ range: [{min(trajectories['vol_garch_delta']):.6f}, "
              f"{max(trajectories['vol_garch_delta']):.6f}]")
        print(f"    δ positive fraction: {np.mean(np.array(trajectories['vol_garch_delta']) > 0):.2f}")

        return trajectories, {
            'mean_baseline_persistence': mean_base_p,
            'mean_vol_persistence': mean_vol_p,
            'mean_drop_pct': mean_drop,
            'mean_delta': mean_delta,
            'delta_positive_frac': float(np.mean(np.array(trajectories['vol_garch_delta']) > 0)),
            'n_windows': len(trajectories['dates']),
        }

    return None, None


# ============================================================
# Main execution
# ============================================================
def main():
    print("\n[1/5] Downloading data...")
    raw_data = download_data()

    all_results = {}

    for ticker, cfg in ASSETS.items():
        if ticker not in raw_data:
            print(f"\n  Skipping {ticker}: no data")
            continue

        print(f"\n\n{'#'*70}")
        print(f"# ASSET: {ticker}")
        print(f"{'#'*70}")

        print(f"\n[2/5] Preparing features for {ticker}...")
        features = prepare_features(raw_data[ticker], ticker)

        print(f"\n[3/5] In-sample analysis for {ticker}...")
        is_results, diagnostics = in_sample_analysis(features, ticker)

        print(f"\n[4/5] OOS rolling forecast for {ticker}...")
        oos_results = oos_rolling_forecast(features, ticker, cfg['window'])

        print(f"\n[5/5] Parameter trajectory for {ticker}...")
        traj, traj_summary = parameter_trajectory(features, ticker, cfg['window'])

        all_results[ticker] = {
            'diagnostics': diagnostics,
            'in_sample': is_results,
            'oos': oos_results,
            'trajectory_summary': traj_summary,
        }

    # ============================================================
    # Summary & Hypothesis testing
    # ============================================================
    print(f"\n\n{'='*70}")
    print("SUMMARY — HYPOTHESIS TESTING")
    print(f"{'='*70}")

    h1_results = {}
    h2_results = {}
    h3_results = {}

    for ticker in all_results:
        r = all_results[ticker]

        # H1: Persistence drop
        if (r['in_sample'].get('garch11', {}).get('success')
                and r['in_sample'].get('vol_garch', {}).get('success')):
            base_p = r['in_sample']['garch11']['persistence']
            vol_p = r['in_sample']['vol_garch']['persistence']
            drop = (base_p - vol_p) / base_p * 100
            h1_results[ticker] = {
                'base_persistence': base_p,
                'vol_persistence': vol_p,
                'drop_pct': drop,
                'confirmed': drop > 5.0,
            }
            # Also add trajectory info if available
            if r['trajectory_summary']:
                h1_results[ticker]['trajectory_mean_drop'] = r['trajectory_summary']['mean_drop_pct']
                h1_results[ticker]['delta_positive_frac'] = r['trajectory_summary']['delta_positive_frac']

            print(f"\n  H1 ({ticker}): Persistence drop = {drop:.2f}% "
                  f"({'CONFIRMED' if drop > 5 else 'SMALL/NULL'})")
            if r['trajectory_summary']:
                print(f"    Trajectory mean drop: {r['trajectory_summary']['mean_drop_pct']:.2f}%")
                print(f"    δ positive fraction: {r['trajectory_summary']['delta_positive_frac']:.2f}")

        # H2: OOS QLIKE improvement
        if r['oos'] is not None:
            best_model = None
            best_change = float('inf')
            any_harvey = False

            for mt in ['vol_garch', 'vol_replacing', 'gjr_vol']:
                if mt in r['oos'] and 'qlike_var_change_pct' in r['oos'][mt]:
                    change = r['oos'][mt]['qlike_var_change_pct']
                    h_var = r['oos'][mt].get('harvey_var_pass', False)
                    h_vol = r['oos'][mt].get('harvey_vol_pass', False)
                    if h_var or h_vol:
                        any_harvey = True
                    if change < best_change:
                        best_change = change
                        best_model = mt

            h2_results[ticker] = {
                'best_model': best_model,
                'best_qlike_var_change_pct': best_change,
                'any_harvey_pass': any_harvey,
            }
            print(f"  H2 ({ticker}): Best = {best_model} "
                  f"(QLIKE(var) {best_change:+.2f}%), Harvey pass = {any_harvey}")

    # H3: Taiwan stronger?
    if 'SPY' in h1_results and '0050.TW' in h1_results:
        spy_drop = h1_results['SPY']['drop_pct']
        tw_drop = h1_results['0050.TW']['drop_pct']
        h3_results = {
            'spy_drop': spy_drop,
            'tw_drop': tw_drop,
            'taiwan_stronger': tw_drop > spy_drop,
        }
        print(f"\n  H3: Taiwan drop ({tw_drop:.2f}%) vs SPY drop ({spy_drop:.2f}%): "
              f"{'TAIWAN STRONGER' if tw_drop > spy_drop else 'NO'}")

    # Overall verdict
    any_oos_pass = any(
        h2_results.get(t, {}).get('any_harvey_pass', False)
        for t in all_results
    )

    # Check if direction is improvement (negative change = better)
    any_improvement = any(
        h2_results.get(t, {}).get('best_qlike_var_change_pct', 0) < -1.0
        for t in all_results
    )

    if any_oos_pass and any_improvement:
        verdict = "POSITIVE — Volume-GARCH improves OOS forecasting with statistical significance"
    elif any_improvement:
        verdict = "MARGINAL — Volume reduces QLIKE but fails Harvey t>3.0 threshold"
    else:
        verdict = ("NEGATIVE — Volume-GARCH fails OOS. Persistence drop is in-sample artifact. "
                   "Confirms K510: MDH volume information is contemporaneous, not predictive.")

    print(f"\n  VERDICT: {verdict}")

    total_time = time.time() - t0_total

    # ============================================================
    # Save results
    # ============================================================
    output = {
        'experiment_id': 'K527',
        'title': 'Volume-GARCH — Lamoureux & Lastrapes (1990) Framework',
        'date': datetime.now(timezone.utc).isoformat(),
        'status': 'completed',
        'attribution': '[提出: 用戶, 執行: Claude]',
        'literature': {
            'primary': 'Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data: Volume versus GARCH Effects" JoF 45(1):221-229',
            'theory': 'Clark (1973) MDH; Tauchen & Pitts (1983) Econometrica',
            'related': 'Hillebrand (2005) persistence inflation; Patton (2011) imperfect proxies',
            'prior_work': 'K113 (vol surprise null), K135 (GLD vol ratio OOS null), K136 (BTC vol-conditioned gamma), K418 (TW vol null), K510 (L&L replication null)',
        },
        'data': {
            'source': 'yfinance (daily OHLCV)',
            'assets': list(all_results.keys()),
            'period': '2005-01-01 to 2026-03-27',
            'oos_period': f'{OOS_START} to {OOS_END}',
            'proxy_variance': 'r²_t (squared return, raw scale)',
            'proxy_volatility': '|r_t| (absolute return, raw scale)',
        },
        'methodology': {
            'models': MODEL_NAMES,
            'key_differences_from_k510': {
                'detrending': 'V_t / MA(V,252) ratio (not linear detrend of log volume)',
                'proxy': '|r_t| and r²_t (K510 used only r²_t)',
                'new_spec': 'Volume-replacing model (ARCH term removed)',
                'cross_market': '0050.TW (not QQQ)',
                'no_lookahead': 'Volume uses V_{t-1} (lagged), not V_t (contemporaneous)',
            },
            'estimation': 'Custom MLE with L-BFGS-B',
            'window': {k: v['window'] for k, v in ASSETS.items()},
            'refit_every': REFIT_EVERY,
            'evaluation': 'QLIKE (var + vol scales), MSE, DM test (Newey-West HAC)',
            'harvey_threshold': 3.0,
            'units_note': 'Returns in %, h in %², converted to raw for QLIKE: var=h/10000, vol=sqrt(h)/100',
        },
        'results': {},
        'hypotheses': {
            'H1_persistence_drop': h1_results,
            'H2_oos_improvement': h2_results,
            'H3_taiwan_stronger': h3_results,
        },
        'verdict': verdict,
        'any_harvey_pass': any_oos_pass,
        'total_time_s': round(total_time, 1),
    }

    # Add per-asset results
    for ticker in all_results:
        r = all_results[ticker]
        is_clean = {}
        for mt, v in r['in_sample'].items():
            if isinstance(v, dict):
                is_clean[mt] = {k: vv for k, vv in v.items()
                                if k not in ['h', 'std_resid', 'eps']}
            else:
                is_clean[mt] = v

        output['results'][ticker] = {
            'diagnostics': r['diagnostics'],
            'in_sample': is_clean,
            'oos': r['oos'],
            'trajectory_summary': r.get('trajectory_summary'),
        }

    out_path = 'experiments/k527_volume_garch_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to {out_path}")
    print(f"  Total time: {total_time:.1f}s")

    return output


if __name__ == '__main__':
    results = main()
