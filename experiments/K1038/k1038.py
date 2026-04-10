"""
K1038: GAS-t Score-Driven Volatility Model vs GARCH (Multi-Asset)
=================================================================
[提出: 用戶, 執行: Claude]

Research Questions:
1. Does GAS-t outperform GJR-GARCH in QLIKE on r² (Patton 2011)?
2. Does GAS-t + leverage outperform plain GAS-t?
3. Does GAS-t's built-in Student-t produce better VaR/ES?
4. Do tail-heavy assets benefit more from GAS-t's score robustification?

Literature:
- Creal, Koopman, Lucas (2013) JASA 108(501):1-18 — GAS framework
- Harvey (2013) Dynamic Models for Volatility & Heavy Tails — Cambridge UP
- Blasques, Koopman, Lucas (2015) Biometrika 102(2):325-343 — info-theoretic optimality
- Patton (2011) — QLIKE on r² for proxy-robust comparison
- Harvey (2016) — DM test |t| > 3.0 threshold

Prior: K437 found GAS-t underperforms GARCH family for SPY only (OOS 2023-2024).
K1038 extends: 4 assets, 7-year OOS, leverage variant, VaR/ES backtesting.

Data: yfinance (SPY, QQQ, GLD, 0050.TW), 2005-01-01 ~ 2026-04-10
OOS: 2019-01-01 onwards (~7 years)
Window: 2000, refit_every: 63
Seed: 42
"""

import sys
import os
import numpy as np
import pandas as pd
import json
import time
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 70)
print("K1038: GAS-t Score-Driven Volatility Model vs GARCH (Multi-Asset)")
print("Creal, Koopman, Lucas (2013) JASA; Harvey (2013)")
print("=" * 70)
sys.stdout.flush()

# ============================================================
# STEP 0: Data Download
# ============================================================
import yfinance as yf

ASSETS = {
    'SPY': {'start': '2005-01-01', 'end': '2026-04-11'},
    'QQQ': {'start': '2005-01-01', 'end': '2026-04-11'},
    'GLD': {'start': '2005-01-01', 'end': '2026-04-11'},
    '0050.TW': {'start': '2005-01-01', 'end': '2026-04-11'},
}

OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

asset_data = {}
for ticker, params in ASSETS.items():
    print(f"\n[0] Downloading {ticker}...")
    df = yf.download(ticker, start=params['start'], end=params['end'], progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    prices = df[price_col].dropna()

    # 0050.TW split adjustment: pre-2014 prices may not be adjusted for 1:4 split
    if ticker == '0050.TW':
        # Check for obvious split issue: prices before 2014 that are 4x higher
        pre_2014 = prices[prices.index < '2014-01-01']
        post_2014 = prices[(prices.index >= '2014-01-01') & (prices.index < '2015-01-01')]
        if len(pre_2014) > 0 and len(post_2014) > 0:
            ratio = pre_2014.iloc[-1] / post_2014.iloc[0]
            if ratio > 3.0:  # Likely unadjusted split
                print(f"  WARNING: Detected unadjusted 1:4 split for 0050.TW, adjusting pre-2014 prices")
                prices[prices.index < '2014-01-01'] = prices[prices.index < '2014-01-01'] / 4.0

    returns_pct = prices.pct_change().dropna() * 100  # percentage returns
    print(f"  Observations: {len(returns_pct)}")
    print(f"  Date range: {returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean: {returns_pct.mean():.4f}%, Std: {returns_pct.std():.4f}%")
    print(f"  Skew: {returns_pct.skew():.3f}, Kurt: {returns_pct.kurtosis():.3f}")

    asset_data[ticker] = returns_pct

sys.stdout.flush()

# ============================================================
# MODEL IMPLEMENTATIONS
# ============================================================

def garch11_negloglik(params, returns):
    """GARCH(1,1) negative log-likelihood (Normal)."""
    omega, alpha, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)

    for t in range(1, T):
        sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10

    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def gjr_garch_negloglik(params, returns):
    """GJR-GARCH(1,1) negative log-likelihood (Normal)."""
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)

    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * indicator + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10

    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def gas_t_negloglik(params, returns):
    """
    GAS-t(1,1) negative log-likelihood.
    f_t = log(sigma2_t), updated by scaled score of Student-t density.

    Parameters: omega, alpha, beta, nu (df)
    """
    omega, alpha, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0  # ensure nu > 2

    T = len(returns)
    f = np.zeros(T)  # log-volatility
    f[0] = np.log(np.var(returns))

    nll = 0.0

    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        sigma_t = np.sqrt(sigma2_t)

        # Standardized residual
        eps2 = (returns[t] / sigma_t) ** 2

        # Student-t log-likelihood contribution
        # p(y|f,nu) = Gamma((nu+1)/2) / (Gamma(nu/2) * sqrt(pi*(nu-2)*sigma2))
        #           * (1 + eps2/(nu-2))^(-(nu+1)/2)
        from scipy.special import gammaln
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2_t)
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t

        if t < T - 1:
            # Score: d log p / d f_t
            # = -1/2 + (nu+1)/2 * eps2 / ((nu-2) + eps2)  * 1
            # (using f = log(sigma2), chain rule gives factor of 1)
            score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)

            # Fisher information scaling: S = 2*nu / ((nu+3)*(nu-2))
            # Scaled score: s = S * score
            S = 2 * nu / ((nu + 3) * (nu - 2))
            scaled_score = S * score

            f[t+1] = omega + alpha * scaled_score + beta * f[t]

    return nll if np.isfinite(nll) else 1e10


def gas_t_leverage_negloglik(params, returns):
    """
    GAS-t(1,1) with leverage effect.
    f_t = omega + alpha*s_{t-1} + gamma*s_{t-1}*I(y_{t-1}<0) + beta*f_{t-1}

    Parameters: omega, alpha, gamma, beta, log_nu_minus2
    """
    omega, alpha, gamma_lev, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0

    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns))

    nll = 0.0

    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        sigma_t = np.sqrt(sigma2_t)

        eps2 = (returns[t] / sigma_t) ** 2

        from scipy.special import gammaln
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2_t)
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t

        if t < T - 1:
            score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
            S = 2 * nu / ((nu + 3) * (nu - 2))
            scaled_score = S * score

            leverage_term = scaled_score * (1.0 if returns[t] < 0 else 0.0)
            f[t+1] = omega + alpha * scaled_score + gamma_lev * leverage_term + beta * f[t]

    return nll if np.isfinite(nll) else 1e10


def fit_garch(returns):
    """Fit GARCH(1,1) and return parameters + sigma2 series."""
    T = len(returns)
    var_r = np.var(returns)

    x0 = [var_r * 0.05, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (0.3, 0.999)]

    try:
        res = minimize(garch11_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success:
            res = minimize(garch11_negloglik, x0, args=(returns,), method='Nelder-Mead',
                          options={'maxiter': 2000})
    except:
        return None, None

    omega, alpha, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10

    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta}, sigma2


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) and return parameters + sigma2 series."""
    T = len(returns)
    var_r = np.var(returns)

    x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]

    try:
        res = minimize(gjr_garch_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success:
            res = minimize(gjr_garch_negloglik, x0, args=(returns,), method='Nelder-Mead',
                          options={'maxiter': 2000})
    except:
        return None, None

    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * indicator + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10

    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + gamma / 2 + beta}, sigma2


def fit_gas_t(returns):
    """Fit GAS-t(1,1) and return parameters + sigma2 series."""
    T = len(returns)
    var_r = np.var(returns)

    x0 = [0.01, 0.05, 0.95, np.log(6.0)]  # omega, alpha, beta, log(nu-2)
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))]

    try:
        res = minimize(gas_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90, np.log(4.0)],
                [0.02, 0.03, 0.97, np.log(10.0)],
                [0.0, 0.08, 0.92, np.log(8.0)],
            ]:
                try:
                    res2 = minimize(gas_t_negloglik, x0_alt, args=(returns,), method='L-BFGS-B',
                                  bounds=bounds, options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except:
                    pass
    except:
        return None, None

    omega, alpha, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0

    # Reconstruct sigma2 series
    f = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = (returns[t] / np.sqrt(sigma2_t)) ** 2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        f[t+1] = omega + alpha * scaled_score + beta * f[t]

    sigma2 = np.exp(f)

    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
            'persistence': beta}, sigma2


def fit_gas_t_leverage(returns):
    """Fit GAS-t(1,1) with leverage and return parameters + sigma2 series."""
    T = len(returns)
    var_r = np.var(returns)

    x0 = [0.01, 0.03, 0.03, 0.95, np.log(6.0)]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))]

    try:
        res = minimize(gas_t_leverage_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.05, 0.05, 0.90, np.log(4.0)],
                [0.02, 0.02, 0.02, 0.97, np.log(10.0)],
            ]:
                try:
                    res2 = minimize(gas_t_leverage_negloglik, x0_alt, args=(returns,),
                                  method='L-BFGS-B', bounds=bounds, options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except:
                    pass
    except:
        return None, None

    omega, alpha, gamma_lev, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0

    f = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = (returns[t] / np.sqrt(sigma2_t)) ** 2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        leverage_term = scaled_score * (1.0 if returns[t] < 0 else 0.0)
        f[t+1] = omega + alpha * scaled_score + gamma_lev * leverage_term + beta * f[t]

    sigma2 = np.exp(f)

    return {'omega': omega, 'alpha': alpha, 'gamma': gamma_lev, 'beta': beta, 'nu': nu,
            'persistence': beta}, sigma2


def forecast_one_step(model_type, params, last_return, last_sigma2, last_f=None):
    """One-step-ahead forecast: h[t] = f(h[t-1], r[t-1])."""
    if model_type == 'GARCH':
        h = params['omega'] + params['alpha'] * last_return**2 + params['beta'] * last_sigma2
    elif model_type == 'GJR':
        indicator = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * indicator + params['beta'] * last_sigma2)
    elif model_type == 'GAS-t':
        nu = params['nu']
        eps2 = (last_return / np.sqrt(last_sigma2))**2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
        h = np.exp(new_f)
    elif model_type == 'GAS-t-Lev':
        nu = params['nu']
        eps2 = (last_return / np.sqrt(last_sigma2))**2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        leverage_term = scaled_score * (1.0 if last_return < 0 else 0.0)
        new_f = (params['omega'] + params['alpha'] * scaled_score
                + params['gamma'] * leverage_term + params['beta'] * last_f)
        h = np.exp(new_f)
    else:
        raise ValueError(f"Unknown model: {model_type}")

    return max(h, 1e-10)


# ============================================================
# EVALUATION METRICS
# ============================================================

def qlike(actual_r2, predicted_sigma2):
    """QLIKE loss: proxy-robust (Patton 2011).
    Excludes days with r²=0 (zero returns) to avoid log(0).
    """
    valid = ((predicted_sigma2 > 0) & np.isfinite(predicted_sigma2)
             & np.isfinite(actual_r2) & (actual_r2 > 0))
    a = actual_r2[valid]
    p = predicted_sigma2[valid]
    loss = a / p - np.log(a / p) - 1
    return np.mean(loss)


def mse_loss(actual_r2, predicted_sigma2):
    """MSE loss on r²."""
    valid = np.isfinite(predicted_sigma2) & np.isfinite(actual_r2)
    return np.mean((actual_r2[valid] - predicted_sigma2[valid])**2)


def dm_test(loss1, loss2):
    """Diebold-Mariano test (two-sided)."""
    d = loss1 - loss2
    d = d[np.isfinite(d) & ~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)

    # HAC variance (Newey-West with auto lag)
    max_lag = int(np.floor(n**(1/3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value


def var_violations(returns, sigma2, alpha_level, dist='normal', nu=None):
    """
    Count VaR violations.
    VaR_alpha = sigma * z_alpha where z depends on distribution.
    """
    sigma = np.sqrt(sigma2)
    if dist == 'normal':
        z = stats.norm.ppf(alpha_level)
    elif dist == 't' and nu is not None and nu > 2:
        # Student-t VaR: scale by sqrt((nu-2)/nu) for standardized t
        z = stats.t.ppf(alpha_level, df=nu) * np.sqrt((nu - 2) / nu)
    else:
        z = stats.norm.ppf(alpha_level)

    var_threshold = z * sigma  # negative number
    violations = returns < var_threshold
    return violations


def kupiec_test(violations, alpha_level, n):
    """Kupiec (1995) LR test for unconditional coverage."""
    n_viol = np.sum(violations)
    if n_viol == 0 or n_viol == n:
        return 0.0, 1.0

    p_hat = n_viol / n
    lr = 2 * (n_viol * np.log(p_hat / alpha_level) +
              (n - n_viol) * np.log((1 - p_hat) / (1 - alpha_level)))
    p_value = 1 - stats.chi2.cdf(lr, 1)
    return lr, p_value


def christoffersen_cc_test(violations):
    """Christoffersen (1998) conditional coverage test."""
    n = len(violations)
    v = violations.astype(int)

    # Count transitions
    n00, n01, n10, n11 = 0, 0, 0, 0
    for t in range(1, n):
        if v[t-1] == 0 and v[t] == 0: n00 += 1
        elif v[t-1] == 0 and v[t] == 1: n01 += 1
        elif v[t-1] == 1 and v[t] == 0: n10 += 1
        else: n11 += 1

    if n01 + n11 == 0 or n00 + n10 == 0:
        return 0.0, 1.0

    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n

    if p <= 0 or p >= 1 or (p01 <= 0 and p11 <= 0):
        return 0.0, 1.0

    try:
        ll_ind = 0
        if n00 > 0 and p01 > 0: ll_ind += n00 * np.log(1 - p01)
        if n01 > 0 and p01 > 0: ll_ind += n01 * np.log(p01)
        if n10 > 0 and p11 > 0: ll_ind += n10 * np.log(1 - p11)
        if n11 > 0 and p11 > 0: ll_ind += n11 * np.log(p11)

        ll_0 = (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p) if p > 0 and p < 1 else 0

        lr = -2 * (ll_0 - ll_ind)
        p_value = 1 - stats.chi2.cdf(lr, 1)
        return lr, p_value
    except:
        return 0.0, 1.0


def acerbi_szekely_es_test(returns, sigma2, alpha_level, dist='normal', nu=None):
    """
    Acerbi-Szekely (2014) ES backtest.
    Z = (1/n_violations) * sum(r_t * I(r_t < VaR)) / ES - 1
    Under H0: Z ~ N(0, 1/n * ...)
    """
    sigma = np.sqrt(sigma2)
    n = len(returns)

    if dist == 'normal':
        z_var = stats.norm.ppf(alpha_level)
        es_scale = -stats.norm.pdf(z_var) / alpha_level
    elif dist == 't' and nu is not None and nu > 2:
        z_var = stats.t.ppf(alpha_level, df=nu) * np.sqrt((nu - 2) / nu)
        # ES for standardized t: E[X | X < VaR]
        t_quantile = stats.t.ppf(alpha_level, df=nu)
        es_scale = -(stats.t.pdf(t_quantile, df=nu) / alpha_level *
                     (nu + t_quantile**2) / (nu - 1)) * np.sqrt((nu - 2) / nu)
    else:
        z_var = stats.norm.ppf(alpha_level)
        es_scale = -stats.norm.pdf(z_var) / alpha_level

    var_threshold = z_var * sigma
    es_threshold = es_scale * sigma  # negative

    violations = returns < var_threshold
    n_viol = np.sum(violations)

    if n_viol < 3:
        return 0.0, 1.0  # Not enough violations

    # Test statistic
    Z = np.sum(returns[violations] / es_threshold[violations]) / n_viol - 1

    # Approximate p-value (bootstrap would be better but too slow)
    # Under H0, Z has mean 0. Large negative Z means ES is too small.
    se_approx = 1.0 / np.sqrt(n_viol)
    z_stat = Z / se_approx
    p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))

    return z_stat, p_value


# ============================================================
# OOS FORECASTING LOOP
# ============================================================

all_results = {}

for ticker, returns_pct in asset_data.items():
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker}")
    print(f"{'='*60}")
    sys.stdout.flush()

    returns = returns_pct.values
    dates = returns_pct.index

    # Find OOS start index
    oos_mask = dates >= OOS_START
    if not any(oos_mask):
        print(f"  SKIP: No OOS data for {ticker}")
        continue

    oos_start_idx = np.where(oos_mask)[0][0]

    if oos_start_idx < WINDOW:
        print(f"  SKIP: Not enough IS data ({oos_start_idx} < {WINDOW})")
        continue

    n_oos = len(returns) - oos_start_idx
    print(f"  OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS observations: {n_oos}")

    # Storage for OOS forecasts
    models = ['GARCH', 'GJR', 'GAS-t', 'GAS-t-Lev']
    forecasts = {m: np.full(n_oos, np.nan) for m in models}
    params_history = {m: [] for m in models}

    # Current model state
    current_params = {m: None for m in models}
    current_sigma2 = {m: None for m in models}
    current_f = {m: None for m in models}  # for GAS models (log-vol)

    t0 = time.time()
    last_fit = -REFIT_EVERY  # Force initial fit

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos  # absolute index

        # Refit if needed
        if t_oos - last_fit >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_data = returns[train_start:t_abs]

            if len(train_data) < 500:
                continue

            # Fit all models
            p_garch, s2_garch = fit_garch(train_data)
            p_gjr, s2_gjr = fit_gjr(train_data)
            p_gas, s2_gas = fit_gas_t(train_data)
            p_gas_lev, s2_gas_lev = fit_gas_t_leverage(train_data)

            if p_garch is not None:
                current_params['GARCH'] = p_garch
                current_sigma2['GARCH'] = s2_garch[-1]
            if p_gjr is not None:
                current_params['GJR'] = p_gjr
                current_sigma2['GJR'] = s2_gjr[-1]
            if p_gas is not None:
                current_params['GAS-t'] = p_gas
                current_sigma2['GAS-t'] = s2_gas[-1]
                current_f['GAS-t'] = np.log(max(s2_gas[-1], 1e-10))
            if p_gas_lev is not None:
                current_params['GAS-t-Lev'] = p_gas_lev
                current_sigma2['GAS-t-Lev'] = s2_gas_lev[-1]
                current_f['GAS-t-Lev'] = np.log(max(s2_gas_lev[-1], 1e-10))

            last_fit = t_oos

            if t_oos % (REFIT_EVERY * 3) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% done ({t_oos}/{n_oos}), {elapsed:.1f}s elapsed")
                sys.stdout.flush()

        # One-step-ahead forecasts: h[t] = f(h[t-1], r[t-1])
        last_r = returns[t_abs - 1]

        for model_name in models:
            if current_params[model_name] is None:
                continue

            if model_name in ['GAS-t', 'GAS-t-Lev']:
                h = forecast_one_step(model_name, current_params[model_name],
                                     last_r, current_sigma2[model_name],
                                     last_f=current_f[model_name])
                forecasts[model_name][t_oos] = h
                # Update state for next step
                current_sigma2[model_name] = h
                current_f[model_name] = np.log(max(h, 1e-10))
            else:
                h = forecast_one_step(model_name, current_params[model_name],
                                     last_r, current_sigma2[model_name])
                forecasts[model_name][t_oos] = h
                current_sigma2[model_name] = h

    elapsed = time.time() - t0
    print(f"  [{ticker}] Completed in {elapsed:.1f}s")
    sys.stdout.flush()

    # ============================================================
    # EVALUATION
    # ============================================================
    actual_r2 = returns[oos_start_idx:]**2
    oos_returns = returns[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # Remove NaN entries (from failed fits)
    valid_mask = np.ones(n_oos, dtype=bool)
    for m in models:
        valid_mask &= np.isfinite(forecasts[m])

    if np.sum(valid_mask) < 100:
        print(f"  SKIP: Too few valid forecasts for {ticker}")
        continue

    actual_r2_v = actual_r2[valid_mask]
    oos_returns_v = oos_returns[valid_mask]
    n_valid = len(actual_r2_v)
    print(f"\n  Valid OOS observations: {n_valid}")

    # QLIKE and MSE
    results_ticker = {}
    qlike_losses = {}

    for model_name in models:
        fc = forecasts[model_name][valid_mask]
        q = qlike(actual_r2_v, fc)
        m = mse_loss(actual_r2_v, fc)
        rank_corr, rank_p = stats.spearmanr(actual_r2_v, fc)

        # Compute per-observation QLIKE loss (set to NaN for r²=0 days)
        ratio = actual_r2_v / fc
        ql_individual = ratio - np.log(np.where(ratio > 0, ratio, 1e-30)) - 1
        ql_individual[actual_r2_v == 0] = np.nan
        qlike_losses[model_name] = ql_individual

        results_ticker[model_name] = {
            'QLIKE': float(q),
            'MSE': float(m),
            'Spearman_rho': float(rank_corr),
            'Spearman_p': float(rank_p),
        }

        print(f"\n  {model_name}:")
        print(f"    QLIKE = {q:.6f}")
        print(f"    MSE   = {m:.6f}")
        print(f"    Spearman rho = {rank_corr:.4f} (p={rank_p:.2e})")

    # DM tests (all pairs vs GJR baseline)
    dm_results = {}
    for model_name in models:
        if model_name == 'GJR':
            continue

        loss_gjr = qlike_losses['GJR']
        loss_m = qlike_losses[model_name]
        t_stat, p_val = dm_test(loss_gjr, loss_m)

        # Positive t means GJR has higher loss (model_name is better)
        dm_results[f'{model_name}_vs_GJR'] = {
            'DM_t': float(t_stat),
            'DM_p': float(p_val),
            'significant_Harvey': bool(abs(t_stat) > 3.0),
            'better_model': model_name if t_stat > 0 else 'GJR',
        }

        print(f"\n  DM test: {model_name} vs GJR")
        print(f"    t = {t_stat:.4f}, p = {p_val:.4e}")
        print(f"    |t| > 3.0 (Harvey): {'YES' if abs(t_stat) > 3.0 else 'NO'}")
        print(f"    Better: {model_name if t_stat > 0 else 'GJR'}")

    # GAS-t vs GAS-t-Lev
    t_stat_gl, p_val_gl = dm_test(qlike_losses['GAS-t'], qlike_losses['GAS-t-Lev'])
    dm_results['GAS-t-Lev_vs_GAS-t'] = {
        'DM_t': float(t_stat_gl),
        'DM_p': float(p_val_gl),
        'significant_Harvey': bool(abs(t_stat_gl) > 3.0),
        'better_model': 'GAS-t-Lev' if t_stat_gl > 0 else 'GAS-t',
    }
    print(f"\n  DM test: GAS-t-Lev vs GAS-t")
    print(f"    t = {t_stat_gl:.4f}, p = {p_val_gl:.4e}")

    # VaR Backtest at 1% and 2.5%
    print(f"\n  --- VaR & ES Backtests ---")
    var_results = {}

    for alpha in [0.01, 0.025]:
        var_results[f'alpha_{alpha}'] = {}

        for model_name in models:
            fc = forecasts[model_name][valid_mask]

            # For GARCH/GJR use Normal dist, for GAS-t use Student-t
            if model_name in ['GAS-t', 'GAS-t-Lev']:
                # Get average nu from params
                # Use last fitted nu
                nu_val = current_params[model_name]['nu'] if current_params[model_name] else 8.0
                dist = 't'
            else:
                nu_val = None
                dist = 'normal'

            viols = var_violations(oos_returns_v, fc, alpha, dist=dist, nu=nu_val)
            viol_rate = np.mean(viols)
            n_viols = np.sum(viols)

            # Kupiec
            kup_lr, kup_p = kupiec_test(viols, alpha, n_valid)
            # Christoffersen CC
            cc_lr, cc_p = christoffersen_cc_test(viols)
            # Basel traffic light (250 day window approximation)
            # Green: <= alpha*250*1.5 approx
            n_250 = min(n_valid, 250)
            viols_250 = viols[-n_250:]
            n_viols_250 = np.sum(viols_250)
            if alpha == 0.01:
                basel = 'Green' if n_viols_250 <= 4 else ('Yellow' if n_viols_250 <= 9 else 'Red')
            else:
                basel = 'Green' if n_viols_250 <= 10 else ('Yellow' if n_viols_250 <= 15 else 'Red')

            trinity_pass = bool((kup_p > 0.05) and (cc_p > 0.05) and (basel == 'Green'))

            # ES backtest
            es_z, es_p = acerbi_szekely_es_test(oos_returns_v, fc, alpha, dist=dist, nu=nu_val)

            var_results[f'alpha_{alpha}'][model_name] = {
                'violation_rate': float(viol_rate),
                'n_violations': int(n_viols),
                'expected_violations': float(alpha * n_valid),
                'Kupiec_p': float(kup_p),
                'CC_p': float(cc_p),
                'Basel': basel,
                'Trinity_PASS': trinity_pass,
                'ES_z': float(es_z),
                'ES_p': float(es_p),
                'ES_PASS': bool(es_p > 0.05),
                'distribution': dist,
                'nu': float(nu_val) if nu_val else None,
            }

            print(f"\n  {model_name} @ {alpha*100:.1f}%:")
            print(f"    Violations: {n_viols}/{n_valid} ({viol_rate*100:.2f}%, expected {alpha*100:.1f}%)")
            print(f"    Kupiec p={kup_p:.4f}, CC p={cc_p:.4f}, Basel={basel}")
            print(f"    Trinity: {'PASS' if trinity_pass else 'FAIL'}")
            print(f"    ES z={es_z:.3f}, p={es_p:.4f} ({'PASS' if es_p > 0.05 else 'FAIL'})")

    # Store results
    all_results[ticker] = {
        'n_oos': n_valid,
        'oos_start': str(oos_dates[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates[-1].strftime('%Y-%m-%d')),
        'model_metrics': results_ticker,
        'dm_tests': dm_results,
        'var_es_backtests': var_results,
        'kurtosis': float(returns_pct.kurtosis()),
        'skewness': float(returns_pct.skew()),
    }

    # Store forecasts for plotting (only for SPY)
    if ticker == 'SPY':
        spy_forecasts = {m: forecasts[m][valid_mask] for m in models}
        spy_actual_r2 = actual_r2_v
        spy_dates = oos_dates[valid_mask]

sys.stdout.flush()

# ============================================================
# CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

# Summary table
print(f"\n{'Asset':<10} {'GARCH':>10} {'GJR':>10} {'GAS-t':>10} {'GAS-t-Lev':>10} {'Best':>10}")
print("-" * 60)
for ticker in all_results:
    metrics = all_results[ticker]['model_metrics']
    best = min(models, key=lambda m: metrics[m]['QLIKE'])
    print(f"{ticker:<10} {metrics['GARCH']['QLIKE']:>10.4f} {metrics['GJR']['QLIKE']:>10.4f} "
          f"{metrics['GAS-t']['QLIKE']:>10.4f} {metrics['GAS-t-Lev']['QLIKE']:>10.4f} {best:>10}")

# DM summary
print(f"\n{'Asset':<10} {'GAS-t vs GJR':>20} {'GAS-t-Lev vs GJR':>20} {'GAS-t-Lev vs GAS-t':>20}")
print("-" * 70)
for ticker in all_results:
    dm = all_results[ticker]['dm_tests']
    gt = dm.get('GAS-t_vs_GJR', {})
    gl = dm.get('GAS-t-Lev_vs_GJR', {})
    gg = dm.get('GAS-t-Lev_vs_GAS-t', {})
    print(f"{ticker:<10} t={gt.get('DM_t',0):>6.2f}{'*' if gt.get('significant_Harvey') else ' ':>1} "
          f"       t={gl.get('DM_t',0):>6.2f}{'*' if gl.get('significant_Harvey') else ' ':>1} "
          f"       t={gg.get('DM_t',0):>6.2f}{'*' if gg.get('significant_Harvey') else ' ':>1}")

# Trinity summary
print(f"\n{'Asset':<10} {'Model':>12} {'1% Trinity':>12} {'2.5% Trinity':>14} {'1% ES':>8} {'2.5% ES':>8}")
print("-" * 70)
for ticker in all_results:
    vr = all_results[ticker]['var_es_backtests']
    for m in models:
        t1 = vr['alpha_0.01'][m]['Trinity_PASS']
        t25 = vr['alpha_0.025'][m]['Trinity_PASS']
        e1 = vr['alpha_0.01'][m]['ES_PASS']
        e25 = vr['alpha_0.025'][m]['ES_PASS']
        print(f"{ticker:<10} {m:>12} {'PASS' if t1 else 'FAIL':>12} {'PASS' if t25 else 'FAIL':>14} "
              f"{'PASS' if e1 else 'FAIL':>8} {'PASS' if e25 else 'FAIL':>8}")

sys.stdout.flush()

# ============================================================
# CHARTS
# ============================================================

# Chart 1: QLIKE comparison bar chart
fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(len(all_results))
width = 0.2
colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63']

for i, model in enumerate(models):
    qlikes = [all_results[t]['model_metrics'][model]['QLIKE'] for t in all_results]
    bars = ax.bar(x + i * width, qlikes, width, label=model, color=colors[i], alpha=0.85)

ax.set_xlabel('Asset', fontsize=12)
ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
ax.set_title('K1038: QLIKE Comparison — GAS-t vs GARCH Family\n(OOS 2019-2026, Patton 2011)', fontsize=13)
ax.set_xticks(x + width * 1.5)
ax.set_xticklabels(list(all_results.keys()))
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1038_qlike_comparison.png')
plt.savefig(chart1_path, dpi=150)
plt.close()
print(f"\n  Chart 1 saved: {chart1_path}")

# Chart 2: Volatility path overlay (SPY)
if 'spy_forecasts' in dir():
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # Top: sigma forecasts
    ax1 = axes[0]
    spy_dates_plot = pd.to_datetime(spy_dates)
    for i, model in enumerate(models):
        sigma = np.sqrt(spy_forecasts[model])
        ax1.plot(spy_dates_plot, sigma, label=model, alpha=0.7, linewidth=0.8, color=colors[i])

    ax1.set_ylabel('Forecast sigma (%)', fontsize=11)
    ax1.set_title('K1038: SPY Volatility Forecasts — GAS-t vs GARCH Family (OOS)', fontsize=13)
    ax1.legend(fontsize=9, ncol=4, loc='upper left')
    ax1.grid(alpha=0.3)

    # Bottom: actual |r| vs forecasts
    ax2 = axes[1]
    ax2.bar(spy_dates_plot, np.abs(np.sqrt(spy_actual_r2)), alpha=0.3, color='gray', label='|return|', width=1.5)
    ax2.plot(spy_dates_plot, np.sqrt(spy_forecasts['GJR']), color=colors[1],
             alpha=0.8, linewidth=0.8, label='GJR sigma')
    ax2.plot(spy_dates_plot, np.sqrt(spy_forecasts['GAS-t-Lev']), color=colors[3],
             alpha=0.8, linewidth=0.8, label='GAS-t-Lev sigma')
    ax2.set_ylabel('|return| and sigma (%)', fontsize=11)
    ax2.set_xlabel('Date', fontsize=11)
    ax2.legend(fontsize=9, loc='upper left')
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    chart2_path = os.path.join(SCRIPT_DIR, 'k1038_spy_volatility_path.png')
    plt.savefig(chart2_path, dpi=150)
    plt.close()
    print(f"  Chart 2 saved: {chart2_path}")

# ============================================================
# SAVE RESULTS
# ============================================================

results_output = {
    'experiment_id': 'K1038',
    'title': 'GAS-t Score-Driven Volatility Model vs GARCH (Multi-Asset)',
    'description': 'Compare GAS-t and GAS-t+leverage against GARCH(1,1) and GJR-GARCH for OOS volatility forecasting',
    'methodology': {
        'models': ['GARCH(1,1)', 'GJR-GARCH(1,1)', 'GAS-t(1,1)', 'GAS-t(1,1)+Leverage'],
        'assets': list(ASSETS.keys()),
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'evaluation_target': 'r² (squared returns, GARCH-native proxy)',
        'metrics': ['QLIKE (Patton 2011)', 'MSE', 'Spearman rank correlation',
                    'VaR Kupiec/CC/Basel Trinity at 1% and 2.5%',
                    'ES Acerbi-Szekely backtest'],
        'dm_threshold': 'Harvey (2016) |t| > 3.0',
    },
    'data_source': 'yfinance',
    'seed': 42,
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108(501):1-18',
        'Harvey (2013) Dynamic Models for Volatility & Heavy Tails, Cambridge UP',
        'Blasques, Koopman, Lucas (2015) Biometrika 102(2):325-343',
        'Patton (2011) — QLIKE proxy-robust loss',
        'Harvey (2016) — DM |t|>3.0 threshold',
    ],
    'results': all_results,
    'charts': ['k1038_qlike_comparison.png', 'k1038_spy_volatility_path.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

results_path = os.path.join(SCRIPT_DIR, 'k1038_results.json')
with open(results_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)

print(f"\n  Results saved: {results_path}")
print("\nK1038 COMPLETE.")
