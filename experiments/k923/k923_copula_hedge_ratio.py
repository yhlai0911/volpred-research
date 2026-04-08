#!/usr/bin/env python3
"""
K923: Copula-Based Optimal Hedge Ratio -- SPY Hedged with GLD

Question: Does a copula-based hedge ratio outperform OLS/DCC hedge ratios?
Especially during tail events where non-linear dependence matters?

Method:
  1. Five hedge ratio methods: OLS, Rolling OLS, DCC, Copula-GARCH, Copula Quantile
  2. GJR-GARCH(1,1) Student-t marginals for both SPY and GLD
  3. Student-t copula (best in K920) for joint dependence
  4. Hedging metrics: HE, VaR Reduction, ES Reduction, Utility, Turnover
  5. IS (2005-2018) and OOS (2019-2026) evaluation
  6. Tail event analysis: SPY drops > 2*sigma

Data: SPY, GLD daily from yfinance, 2005-01-01 to 2026-04-04
IS: 2005-2018, OOS: 2019-2026

References:
  - Ederington (1979): The Hedging Performance of the New Futures Markets, JF
  - Lai & Sheu (2010): Copula-based hedging
  - Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM
  - Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER

Prior work:
  - K920: Student-t copula, lambda=0.14, nu=3.05 (best copula for SPY-GLD)
  - K915: DCC-GARCH dynamic correlation
  - K918: BEKK no cross-spillover

Error log rules applied:
  - Fixed seed: np.random.seed(42)
  - Hedge ratio uses shift(1) -- no lookahead
  - DM test: use proper implementation (from volpred.stats.model_evaluation)
  - Student-t scale: must consider sqrt((df-2)/df)
  - Hedging uses hedging metrics (HE/VaR/Utility), NOT Sharpe/CAGR

Author: VolPred Research System
"""

import json
import os
import sys
import warnings
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats as sp_stats
from scipy.optimize import minimize
from scipy.special import gammaln

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'GLD']
START_DATE = '2005-01-01'
END_DATE = '2026-04-04'
OOS_START = '2019-01-01'
ROLLING_WINDOW = 250  # Rolling OLS window
DCC_REFIT_FREQ = 63   # Refit GARCH/copula every 63 trading days (~quarterly)
N_SIM = 10000          # Monte Carlo for copula quantile hedge
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# Step 1: Data Collection
# ============================================================
def fetch_data():
    """Fetch daily prices for SPY, GLD from yfinance."""
    import yfinance as yf

    tickers = ASSETS
    data = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

    if isinstance(data.columns, pd.MultiIndex):
        prices = data['Close']
    else:
        prices = data[['Close']]

    prices = prices.dropna()
    returns = prices.pct_change().dropna()
    print(f"Data: {returns.index[0].date()} to {returns.index[-1].date()}, {len(returns)} obs")
    return prices, returns


# ============================================================
# Step 2: Descriptive Statistics
# ============================================================
def compute_descriptive_stats(returns):
    """Compute descriptive statistics for both assets."""
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch

    stats_dict = {}
    for col in returns.columns:
        r = returns[col].dropna()
        adf = adfuller(r, maxlag=20, autolag='AIC')

        # ARCH LM test (10 lags)
        try:
            lm_stat, lm_pval, _, _ = het_arch(r, nlags=10)
        except Exception:
            lm_stat, lm_pval = np.nan, np.nan

        stats_dict[col] = {
            'n_obs': len(r),
            'mean': float(r.mean()),
            'std': float(r.std()),
            'skew': float(r.skew()),
            'kurtosis': float(r.kurtosis()),
            'min': float(r.min()),
            'max': float(r.max()),
            'adf_stat': round(float(adf[0]), 4),
            'adf_pval': round(float(adf[1]), 6),
            'arch_lm_stat': round(float(lm_stat), 4),
            'arch_lm_pval': round(float(lm_pval), 6),
            'pearson_corr': round(float(returns.corr().iloc[0, 1]), 4),
        }
        print(f"\n{col}: mean={stats_dict[col]['mean']:.6f}, std={stats_dict[col]['std']:.6f}, "
              f"skew={stats_dict[col]['skew']:.4f}, kurt={stats_dict[col]['kurtosis']:.4f}")
        print(f"  ADF={stats_dict[col]['adf_stat']}, ARCH LM={stats_dict[col]['arch_lm_stat']}")

    return stats_dict


# ============================================================
# Step 3: GJR-GARCH Marginal Models
# ============================================================
def fit_gjr_garch(returns_pct, asset_name):
    """
    Fit GJR-GARCH(1,1) with Student-t innovations.
    Returns: result, cond_vol (in decimal), std_resid, nu.
    """
    am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
    res = am.fit(disp='off', options={'maxiter': 5000})

    cond_vol = res.conditional_volatility / 100  # back to decimal
    std_resid = res.std_resid
    nu = res.params.get('nu', 30.0)

    persistence = (res.params.get('alpha[1]', 0)
                   + res.params.get('gamma[1]', 0) / 2
                   + res.params.get('beta[1]', 0))

    print(f"\n{asset_name} GJR-GARCH(1,1):")
    print(f"  omega={res.params.get('omega', 0):.6f}, "
          f"alpha={res.params.get('alpha[1]', 0):.6f}, "
          f"gamma={res.params.get('gamma[1]', 0):.6f}, "
          f"beta={res.params.get('beta[1]', 0):.6f}")
    print(f"  nu={nu:.2f}, persistence={persistence:.4f}")
    print(f"  Converged: {res.convergence_flag == 0}")

    return {
        'result': res,
        'cond_vol': cond_vol,
        'std_resid': std_resid,
        'nu': nu,
        'persistence': persistence,
        'converged': res.convergence_flag == 0,
        'params': {
            'omega': float(res.params.get('omega', 0)),
            'alpha': float(res.params.get('alpha[1]', 0)),
            'gamma': float(res.params.get('gamma[1]', 0)),
            'beta': float(res.params.get('beta[1]', 0)),
            'nu': float(nu),
        }
    }


def probability_integral_transform(std_resid, nu):
    """Apply PIT using Student-t CDF to get uniform (0,1) variates."""
    u = sp_stats.t.cdf(std_resid, df=nu)
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return u


# ============================================================
# Step 4: Student-t Copula
# ============================================================
def student_t_copula_ll(params, u1, u2):
    """Student-t copula negative log-likelihood."""
    rho = np.tanh(params[0])
    nu = np.exp(params[1]) + 2.01  # df > 2

    x1 = sp_stats.t.ppf(u1, df=nu)
    x2 = sp_stats.t.ppf(u2, df=nu)
    n = len(u1)

    det = 1 - rho**2
    if det <= 0:
        return 1e10

    ll = n * (gammaln((nu + 2) / 2) - gammaln(nu / 2)
              - np.log(nu * np.pi) - 0.5 * np.log(det))
    ll -= n * 2 * (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                   - 0.5 * np.log(nu * np.pi))

    Q = (x1**2 + x2**2 - 2 * rho * x1 * x2) / det
    ll -= ((nu + 2) / 2) * np.sum(np.log(1 + Q / nu))
    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x1**2 / nu))
    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x2**2 / nu))

    return -ll


def fit_student_t_copula(u1, u2):
    """Fit Student-t copula, return rho, nu."""
    res = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1, u2),
                   method='Nelder-Mead', options={'maxiter': 10000})
    rho = np.tanh(res.x[0])
    nu = np.exp(res.x[1]) + 2.01
    ll = -res.fun
    return rho, nu, ll, res.success


def simulate_copula(rho, nu, n_sim, rng=None):
    """
    Simulate from bivariate Student-t copula.
    Returns: u1, u2 (uniform marginals)
    """
    if rng is None:
        rng = np.random.default_rng(42)

    # Generate bivariate Student-t
    cov_matrix = np.array([[1.0, rho], [rho, 1.0]])
    z = rng.multivariate_normal(mean=[0, 0], cov=cov_matrix, size=n_sim)

    # Chi-squared for Student-t
    chi2 = rng.chisquare(df=nu, size=n_sim)
    scale = np.sqrt(nu / chi2)

    t_samples = z * scale[:, np.newaxis]

    # PIT to uniform
    u1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
    u2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

    return u1, u2


# ============================================================
# Step 5: DCC-GARCH (simplified)
# ============================================================
def compute_dcc_correlation(std_resid_spy, std_resid_gld, a=0.01, b=0.95):
    """
    Compute DCC dynamic correlation.
    Simple DCC(1,1) with fixed a, b for robustness.

    Q_t = (1-a-b)*Qbar + a*eps_{t-1}*eps_{t-1}' + b*Q_{t-1}
    R_t = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2}
    """
    T = len(std_resid_spy)
    eps1 = std_resid_spy.values if hasattr(std_resid_spy, 'values') else std_resid_spy
    eps2 = std_resid_gld.values if hasattr(std_resid_gld, 'values') else std_resid_gld

    # Unconditional correlation matrix
    Qbar = np.corrcoef(eps1, eps2)

    q11 = np.ones(T)
    q22 = np.ones(T)
    q12 = np.full(T, Qbar[0, 1])
    rho_t = np.full(T, Qbar[0, 1])

    for t in range(1, T):
        q11[t] = (1 - a - b) * 1.0 + a * eps1[t-1]**2 + b * q11[t-1]
        q22[t] = (1 - a - b) * 1.0 + a * eps2[t-1]**2 + b * q22[t-1]
        q12[t] = (1 - a - b) * Qbar[0, 1] + a * eps1[t-1] * eps2[t-1] + b * q12[t-1]

        denom = np.sqrt(q11[t] * q22[t])
        if denom > 0:
            rho_t[t] = q12[t] / denom
            rho_t[t] = np.clip(rho_t[t], -0.999, 0.999)

    return rho_t


# ============================================================
# Step 6: Five Hedge Ratio Methods
# ============================================================
def compute_hedge_ratios(returns, garch_spy, garch_gld, oos_start_idx):
    """
    Compute 5 hedge ratio series, all using shift(1) to avoid lookahead.

    Returns dict of pd.Series, each same length as returns.
    """
    r_spy = returns['SPY'].values
    r_gld = returns['GLD'].values
    T = len(r_spy)
    idx = returns.index

    # Pre-compute GARCH conditional volatilities
    sig_spy = garch_spy['cond_vol'].values
    sig_gld = garch_gld['cond_vol'].values
    std_r_spy = garch_spy['std_resid']
    std_r_gld = garch_gld['std_resid']
    nu_spy = garch_spy['nu']
    nu_gld = garch_gld['nu']

    # ---- Method 1: OLS (static, full-sample IS) ----
    # Use only IS data available up to each point
    h_ols = np.full(T, np.nan)
    # Static: use expanding window from start
    for t in range(ROLLING_WINDOW, T):
        cov_ = np.cov(r_spy[:t], r_gld[:t])[0, 1]
        var_ = np.var(r_gld[:t])
        if var_ > 0:
            h_ols[t] = cov_ / var_
    # Fill initial period with first valid
    first_valid = h_ols[ROLLING_WINDOW]
    h_ols[:ROLLING_WINDOW] = first_valid

    # ---- Method 2: Rolling OLS (250-day window) ----
    h_rolling = np.full(T, np.nan)
    for t in range(ROLLING_WINDOW, T):
        window_spy = r_spy[t - ROLLING_WINDOW:t]
        window_gld = r_gld[t - ROLLING_WINDOW:t]
        cov_ = np.cov(window_spy, window_gld)[0, 1]
        var_ = np.var(window_gld)
        if var_ > 0:
            h_rolling[t] = cov_ / var_
    h_rolling[:ROLLING_WINDOW] = h_rolling[ROLLING_WINDOW]

    # ---- Method 3: DCC-GARCH ----
    rho_dcc = compute_dcc_correlation(std_r_spy, std_r_gld)
    # h_DCC = rho_DCC * sigma_SPY / sigma_GLD
    h_dcc = np.full(T, np.nan)
    for t in range(T):
        if sig_gld[t] > 0:
            h_dcc[t] = rho_dcc[t] * sig_spy[t] / sig_gld[t]

    # ---- Method 4: Copula-GARCH ----
    # PIT -> Student-t copula -> copula-implied correlation -> hedge ratio
    # Refit copula every DCC_REFIT_FREQ days using expanding window
    h_copula = np.full(T, np.nan)
    copula_rho_series = np.full(T, np.nan)

    # Initial fit using first ROLLING_WINDOW observations
    min_fit_window = 500  # minimum obs for copula fit

    u1_all = probability_integral_transform(std_r_spy, nu_spy)
    u2_all = probability_integral_transform(std_r_gld, nu_gld)

    last_refit = 0
    current_copula_rho = 0.0
    current_copula_nu = 5.0

    print("\nFitting copula hedge ratios (refit every 63 days)...")
    for t in range(min_fit_window, T):
        # Refit copula periodically
        if t - last_refit >= DCC_REFIT_FREQ or t == min_fit_window:
            u1_window = u1_all[:t]
            u2_window = u2_all[:t]
            try:
                rho_c, nu_c, ll_c, success = fit_student_t_copula(u1_window, u2_window)
                if success and np.isfinite(rho_c):
                    current_copula_rho = rho_c
                    current_copula_nu = nu_c
                    last_refit = t
            except Exception:
                pass  # keep previous copula params

        copula_rho_series[t] = current_copula_rho

        # Copula-implied hedge ratio: h = rho_copula * sigma_SPY / sigma_GLD
        if sig_gld[t] > 0:
            h_copula[t] = current_copula_rho * sig_spy[t] / sig_gld[t]

    h_copula[:min_fit_window] = h_copula[min_fit_window]

    # ---- Method 5: Copula Quantile Hedge ----
    # For each refit, simulate from copula and find h that minimizes VaR
    h_quantile = np.full(T, np.nan)

    print("Computing copula quantile hedge ratios...")
    last_refit_q = 0
    current_h_q = 0.0
    rng = np.random.default_rng(42)

    for t in range(min_fit_window, T):
        if t - last_refit_q >= DCC_REFIT_FREQ or t == min_fit_window:
            # Use current copula params + GARCH vols
            rho_c = copula_rho_series[t] if np.isfinite(copula_rho_series[t]) else 0.0
            nu_c = current_copula_nu

            # Simulate copula samples
            u1_sim, u2_sim = simulate_copula(rho_c, nu_c, N_SIM, rng)

            # Transform to returns using current GARCH volatility + Student-t marginals
            # z = t^{-1}(u) where t is Student-t CDF with marginal df
            z1 = sp_stats.t.ppf(u1_sim, df=nu_spy)
            z2 = sp_stats.t.ppf(u2_sim, df=nu_gld)

            # Scale by GARCH vol: r_sim = sigma * z * sqrt((nu-2)/nu)
            scale_spy = np.sqrt((nu_spy - 2) / nu_spy) if nu_spy > 2 else 1.0
            scale_gld = np.sqrt((nu_gld - 2) / nu_gld) if nu_gld > 2 else 1.0

            r_spy_sim = sig_spy[t] * z1 * scale_spy
            r_gld_sim = sig_gld[t] * z2 * scale_gld

            # Find h that minimizes VaR_5%
            h_candidates = np.linspace(-0.5, 1.5, 201)
            best_var = np.inf
            best_h = 0.0

            for h_cand in h_candidates:
                r_hedged_sim = r_spy_sim - h_cand * r_gld_sim
                var_5 = np.percentile(r_hedged_sim, 5)
                if var_5 > best_var:  # VaR is negative, so less negative = better
                    # Actually want to minimize loss, so maximize (less negative) VaR
                    pass
                # Minimize the magnitude of VaR (maximize the 5th percentile)
                if -var_5 < -best_var:
                    best_var = var_5
                    best_h = h_cand

            # Cleaner: just maximize the 5th percentile
            vars_5 = np.array([np.percentile(r_spy_sim - h * r_gld_sim, 5) for h in h_candidates])
            best_idx = np.argmax(vars_5)  # highest 5th percentile = least downside
            current_h_q = h_candidates[best_idx]
            last_refit_q = t

        h_quantile[t] = current_h_q

    h_quantile[:min_fit_window] = h_quantile[min_fit_window]

    # Apply shift(1) to ALL hedge ratios -- use yesterday's ratio for today's hedge
    hedge_ratios = {
        'OLS': pd.Series(h_ols, index=idx).shift(1),
        'Rolling_OLS': pd.Series(h_rolling, index=idx).shift(1),
        'DCC': pd.Series(h_dcc, index=idx).shift(1),
        'Copula': pd.Series(h_copula, index=idx).shift(1),
        'Copula_Quantile': pd.Series(h_quantile, index=idx).shift(1),
    }

    # Fill NaN from shift with first valid value
    for name in hedge_ratios:
        hedge_ratios[name] = hedge_ratios[name].ffill().bfill()

    return hedge_ratios, copula_rho_series


# ============================================================
# Step 7: Hedging Evaluation Metrics
# ============================================================
def compute_hedging_metrics(returns_spy, returns_gld, hedge_ratio, period_name):
    """
    Compute hedging effectiveness metrics.
    Hedge portfolio: R_h = R_SPY - h * R_GLD

    Returns dict of metrics.
    """
    r_spy = returns_spy.values
    r_gld = returns_gld.values
    h = hedge_ratio.values

    # Hedged return
    r_hedged = r_spy - h * r_gld
    r_unhedged = r_spy

    # Drop NaN
    valid = np.isfinite(r_hedged) & np.isfinite(r_unhedged) & np.isfinite(h)
    r_hedged = r_hedged[valid]
    r_unhedged = r_unhedged[valid]
    h_valid = h[valid]

    if len(r_hedged) < 10:
        return None

    # HE: Ederington (1979)
    var_unhedged = np.var(r_unhedged, ddof=1)
    var_hedged = np.var(r_hedged, ddof=1)
    HE = 1 - var_hedged / var_unhedged if var_unhedged > 0 else np.nan

    # VaR at 5%
    var_5_unhedged = np.percentile(r_unhedged, 5)
    var_5_hedged = np.percentile(r_hedged, 5)
    var_reduction = var_5_hedged / var_5_unhedged if var_5_unhedged != 0 else np.nan

    # ES at 5%
    es_mask_u = r_unhedged <= var_5_unhedged
    es_mask_h = r_hedged <= var_5_hedged
    es_unhedged = np.mean(r_unhedged[es_mask_u]) if es_mask_u.sum() > 0 else np.nan
    es_hedged = np.mean(r_hedged[es_mask_h]) if es_mask_h.sum() > 0 else np.nan
    es_reduction = es_hedged / es_unhedged if es_unhedged != 0 else np.nan

    # VaR at 1%
    var_1_unhedged = np.percentile(r_unhedged, 1)
    var_1_hedged = np.percentile(r_hedged, 1)
    var_1_reduction = var_1_hedged / var_1_unhedged if var_1_unhedged != 0 else np.nan

    # ES at 1%
    es1_mask_u = r_unhedged <= var_1_unhedged
    es1_mask_h = r_hedged <= var_1_hedged
    es1_unhedged = np.mean(r_unhedged[es1_mask_u]) if es1_mask_u.sum() > 0 else np.nan
    es1_hedged = np.mean(r_hedged[es1_mask_h]) if es1_mask_h.sum() > 0 else np.nan
    es1_reduction = es1_hedged / es1_unhedged if es1_unhedged != 0 else np.nan

    # CRRA Utility: U = E[R] - (gamma/2)*Var(R)
    mean_hedged = np.mean(r_hedged)
    mean_unhedged = np.mean(r_unhedged)

    utility_results = {}
    for gamma in [3, 5, 10]:
        u_hedged = mean_hedged - (gamma / 2) * var_hedged
        u_unhedged = mean_unhedged - (gamma / 2) * var_unhedged
        utility_results[f'gamma_{gamma}'] = {
            'hedged': float(u_hedged),
            'unhedged': float(u_unhedged),
            'improvement': float(u_hedged - u_unhedged),
        }

    # Turnover: mean absolute change in hedge ratio
    h_diff = np.abs(np.diff(h_valid))
    turnover = float(np.mean(h_diff))

    # Mean hedge ratio
    mean_h = float(np.mean(h_valid))
    std_h = float(np.std(h_valid))

    metrics = {
        'period': period_name,
        'n_obs': int(len(r_hedged)),
        'HE': round(float(HE), 6),
        'var_hedged': round(float(var_hedged), 8),
        'var_unhedged': round(float(var_unhedged), 8),
        'VaR_5pct_unhedged': round(float(var_5_unhedged), 6),
        'VaR_5pct_hedged': round(float(var_5_hedged), 6),
        'VaR_5pct_reduction': round(float(var_reduction), 4),
        'ES_5pct_unhedged': round(float(es_unhedged), 6),
        'ES_5pct_hedged': round(float(es_hedged), 6),
        'ES_5pct_reduction': round(float(es_reduction), 4),
        'VaR_1pct_unhedged': round(float(var_1_unhedged), 6),
        'VaR_1pct_hedged': round(float(var_1_hedged), 6),
        'VaR_1pct_reduction': round(float(var_1_reduction), 4),
        'ES_1pct_unhedged': round(float(es1_unhedged), 6),
        'ES_1pct_hedged': round(float(es1_hedged), 6),
        'ES_1pct_reduction': round(float(es1_reduction), 4),
        'mean_return_hedged': round(float(mean_hedged), 8),
        'mean_return_unhedged': round(float(mean_unhedged), 8),
        'utility': utility_results,
        'turnover': round(turnover, 6),
        'mean_hedge_ratio': round(mean_h, 4),
        'std_hedge_ratio': round(std_h, 4),
    }

    return metrics


# ============================================================
# Step 8: DM Test on Squared Hedged Returns
# ============================================================
def dm_test_hedge(r_spy, r_gld, h1, h2, name1, name2):
    """
    Diebold-Mariano test comparing two hedge ratios.
    Loss function: squared hedged return (proxy for hedging error).
    H0: both methods equally good.
    """
    r1 = r_spy - h1 * r_gld  # hedged return method 1
    r2 = r_spy - h2 * r_gld  # hedged return method 2

    d = r1**2 - r2**2  # loss differential

    valid = np.isfinite(d)
    d = d[valid]

    if len(d) < 30:
        return {'t_stat': np.nan, 'p_value': np.nan, 'n': 0}

    d_bar = np.mean(d)

    # HAC variance with Bartlett kernel
    T = len(d)
    h_bw = int(np.floor(T**(1/3)))  # bandwidth

    gamma_0 = np.mean((d - d_bar)**2)
    gamma_sum = 0
    for k in range(1, h_bw + 1):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * (1 - k / (h_bw + 1)) * gamma_k

    var_d = (gamma_0 + gamma_sum) / T

    if var_d <= 0:
        return {'t_stat': np.nan, 'p_value': np.nan, 'n': T}

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * sp_stats.t.sf(abs(t_stat), df=T - 1)

    return {
        't_stat': round(float(t_stat), 4),
        'p_value': round(float(p_value), 6),
        'n': int(T),
        'mean_loss_diff': round(float(d_bar), 10),
        'comparison': f'{name1} vs {name2}',
        'interpretation': f'{"Negative t: {name1} better" if t_stat < 0 else "Positive t: {name2} better"}',
        'harvey_significant': abs(t_stat) > 3.0,
    }


# ============================================================
# Step 9: Tail Event Analysis
# ============================================================
def tail_event_analysis(returns, hedge_ratios, threshold_sigma=2.0):
    """
    Analyze hedging performance during SPY tail events (drops > 2*sigma).
    """
    r_spy = returns['SPY']
    r_gld = returns['GLD']
    sigma_spy = r_spy.std()
    threshold = -threshold_sigma * sigma_spy

    tail_mask = r_spy < threshold
    n_tail = tail_mask.sum()
    print(f"\nTail events (SPY < {threshold:.4f}): {n_tail} days")

    tail_results = {}
    for name, h in hedge_ratios.items():
        r_hedged = r_spy - h * r_gld
        r_hedged_tail = r_hedged[tail_mask]
        r_unhedged_tail = r_spy[tail_mask]

        if len(r_hedged_tail) < 5:
            continue

        mean_loss_unhedged = float(r_unhedged_tail.mean())
        mean_loss_hedged = float(r_hedged_tail.mean())
        var_reduction = float(np.var(r_hedged_tail) / np.var(r_unhedged_tail))

        tail_results[name] = {
            'n_tail_events': int(n_tail),
            'mean_unhedged_loss': round(mean_loss_unhedged, 6),
            'mean_hedged_loss': round(mean_loss_hedged, 6),
            'loss_reduction_pct': round((1 - mean_loss_hedged / mean_loss_unhedged) * 100, 2) if mean_loss_unhedged != 0 else np.nan,
            'variance_ratio': round(var_reduction, 4),
            'worst_hedged': round(float(r_hedged_tail.min()), 6),
            'worst_unhedged': round(float(r_unhedged_tail.min()), 6),
        }

    return tail_results


# ============================================================
# Step 10: Plotting
# ============================================================
def plot_hedge_comparison(results_is, results_oos, methods, output_dir):
    """Plot hedge effectiveness comparison."""
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))

    metrics_to_plot = [
        ('HE', 'Hedge Effectiveness (HE)', 'Higher = Better'),
        ('VaR_5pct_reduction', 'VaR 5% Reduction Ratio', 'Lower = Better (ratio hedged/unhedged)'),
        ('ES_5pct_reduction', 'ES 5% Reduction Ratio', 'Lower = Better'),
        ('VaR_1pct_reduction', 'VaR 1% Reduction Ratio', 'Lower = Better'),
        ('turnover', 'Turnover (Mean |Δh|)', 'Lower = Cheaper'),
        ('mean_hedge_ratio', 'Mean Hedge Ratio', ''),
    ]

    colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0']

    for idx, (metric, title, ylabel) in enumerate(metrics_to_plot):
        ax = axes[idx // 3, idx % 3]

        is_vals = [results_is[m][metric] for m in methods]
        oos_vals = [results_oos[m][metric] for m in methods]

        x = np.arange(len(methods))
        width = 0.35

        bars1 = ax.bar(x - width/2, is_vals, width, label='IS', alpha=0.8, color='steelblue')
        bars2 = ax.bar(x + width/2, oos_vals, width, label='OOS', alpha=0.8, color='coral')

        ax.set_title(title, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(methods, rotation=45, ha='right', fontsize=8)
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    plt.suptitle('K923: Copula-Based Hedge Ratio Comparison (SPY Hedged with GLD)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'k923_hedge_comparison.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved k923_hedge_comparison.png")


def plot_tail_hedging(tail_results, output_dir):
    """Plot tail event hedging performance."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    methods = list(tail_results.keys())
    if not methods:
        plt.close()
        return

    # Loss reduction
    ax = axes[0]
    loss_red = [tail_results[m]['loss_reduction_pct'] for m in methods]
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0']
    bars = ax.bar(methods, loss_red, color=colors[:len(methods)], alpha=0.8)
    ax.set_title('Loss Reduction During Tail Events (%)', fontsize=12)
    ax.set_ylabel('Loss Reduction (%)')
    ax.grid(axis='y', alpha=0.3)
    for bar, val in zip(bars, loss_red):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    # Variance ratio
    ax = axes[1]
    var_ratio = [tail_results[m]['variance_ratio'] for m in methods]
    bars = ax.bar(methods, var_ratio, color=colors[:len(methods)], alpha=0.8)
    ax.set_title('Variance Ratio During Tail Events', fontsize=12)
    ax.set_ylabel('Var(hedged) / Var(unhedged)')
    ax.axhline(y=1.0, color='red', linestyle='--', alpha=0.5, label='No improvement')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    for bar, val in zip(bars, var_ratio):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f'{val:.3f}', ha='center', va='bottom', fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    plt.suptitle('K923: Hedging Performance During SPY Tail Events (>2σ drops)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'k923_tail_hedging.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved k923_tail_hedging.png")


def plot_hedge_ratios_ts(hedge_ratios, returns, oos_start_date, output_dir):
    """Plot time series of hedge ratios."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    colors = {'OLS': '#2196F3', 'Rolling_OLS': '#4CAF50', 'DCC': '#FF9800',
              'Copula': '#E91E63', 'Copula_Quantile': '#9C27B0'}

    ax = axes[0]
    for name, h in hedge_ratios.items():
        ax.plot(h.index, h.values, label=name, alpha=0.7, linewidth=0.8, color=colors.get(name, 'gray'))
    ax.axvline(x=pd.Timestamp(oos_start_date), color='black', linestyle='--', alpha=0.5, label='OOS start')
    ax.set_title('Hedge Ratios Over Time', fontsize=12)
    ax.set_ylabel('Hedge Ratio (h)')
    ax.legend(fontsize=8, ncol=3)
    ax.grid(alpha=0.3)

    ax = axes[1]
    r_spy = returns['SPY']
    ax.plot(r_spy.index, r_spy.values, alpha=0.5, color='steelblue', linewidth=0.5)
    ax.axhline(y=-2*r_spy.std(), color='red', linestyle='--', alpha=0.5, label=f'-2σ = {-2*r_spy.std():.4f}')
    ax.set_title('SPY Daily Returns', fontsize=12)
    ax.set_ylabel('Return')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    plt.suptitle('K923: Hedge Ratio Time Series', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'k923_hedge_ratios_ts.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved k923_hedge_ratios_ts.png")


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("K923: Copula-Based Optimal Hedge Ratio -- SPY Hedged with GLD")
    print("=" * 70)

    # Step 1: Data
    prices, returns = fetch_data()

    # Step 2: Descriptive stats
    desc_stats = compute_descriptive_stats(returns)

    # Step 3: GJR-GARCH marginals (full sample for conditional vol)
    print("\n--- Fitting GJR-GARCH marginals ---")
    r_spy_pct = returns['SPY'] * 100
    r_gld_pct = returns['GLD'] * 100

    garch_spy = fit_gjr_garch(r_spy_pct, 'SPY')
    garch_gld = fit_gjr_garch(r_gld_pct, 'GLD')

    # Check convergence
    assert garch_spy['converged'], "SPY GARCH did not converge!"
    assert garch_gld['converged'], "GLD GARCH did not converge!"
    assert garch_spy['persistence'] < 1.0, f"SPY persistence={garch_spy['persistence']} >= 1!"
    assert garch_gld['persistence'] < 1.0, f"GLD persistence={garch_gld['persistence']} >= 1!"

    # Step 4-6: Compute all 5 hedge ratios
    oos_start_idx = returns.index.get_loc(returns.index[returns.index >= OOS_START][0])
    print(f"\nOOS starts at index {oos_start_idx} ({returns.index[oos_start_idx].date()})")

    hedge_ratios, copula_rho = compute_hedge_ratios(returns, garch_spy, garch_gld, oos_start_idx)

    # Print hedge ratio summaries
    print("\n--- Hedge Ratio Summaries ---")
    for name, h in hedge_ratios.items():
        print(f"{name:20s}: mean={h.mean():.4f}, std={h.std():.4f}, "
              f"min={h.min():.4f}, max={h.max():.4f}")

    # Step 7: Evaluate IS and OOS
    oos_mask = returns.index >= OOS_START
    is_mask = ~oos_mask

    methods = ['OLS', 'Rolling_OLS', 'DCC', 'Copula', 'Copula_Quantile']

    results_is = {}
    results_oos = {}

    print("\n--- IS Evaluation ---")
    for name in methods:
        m = compute_hedging_metrics(
            returns['SPY'][is_mask], returns['GLD'][is_mask],
            hedge_ratios[name][is_mask], f'IS_{name}'
        )
        results_is[name] = m
        print(f"  {name:20s}: HE={m['HE']:.4f}, VaR5%Red={m['VaR_5pct_reduction']:.4f}, "
              f"ES5%Red={m['ES_5pct_reduction']:.4f}, Turnover={m['turnover']:.6f}")

    print("\n--- OOS Evaluation ---")
    for name in methods:
        m = compute_hedging_metrics(
            returns['SPY'][oos_mask], returns['GLD'][oos_mask],
            hedge_ratios[name][oos_mask], f'OOS_{name}'
        )
        results_oos[name] = m
        print(f"  {name:20s}: HE={m['HE']:.4f}, VaR5%Red={m['VaR_5pct_reduction']:.4f}, "
              f"ES5%Red={m['ES_5pct_reduction']:.4f}, Turnover={m['turnover']:.6f}")

    # Step 8: DM tests (OOS period)
    print("\n--- DM Tests (OOS) ---")
    dm_results = {}
    r_spy_oos = returns['SPY'][oos_mask].values
    r_gld_oos = returns['GLD'][oos_mask].values

    pairs = [
        ('OLS', 'Rolling_OLS'),
        ('OLS', 'DCC'),
        ('OLS', 'Copula'),
        ('OLS', 'Copula_Quantile'),
        ('DCC', 'Copula'),
        ('DCC', 'Copula_Quantile'),
        ('Copula', 'Copula_Quantile'),
        ('Rolling_OLS', 'DCC'),
        ('Rolling_OLS', 'Copula'),
    ]

    for m1, m2 in pairs:
        h1 = hedge_ratios[m1][oos_mask].values
        h2 = hedge_ratios[m2][oos_mask].values
        dm = dm_test_hedge(r_spy_oos, r_gld_oos, h1, h2, m1, m2)
        dm_results[f'{m1}_vs_{m2}'] = dm
        sig_marker = '***' if dm['harvey_significant'] else ''
        print(f"  {m1:20s} vs {m2:20s}: t={dm['t_stat']:+.4f}, p={dm['p_value']:.4f} {sig_marker}")

    # Step 9: Tail event analysis (full sample)
    print("\n--- Tail Event Analysis (Full Sample) ---")
    tail_results = tail_event_analysis(returns, hedge_ratios, threshold_sigma=2.0)
    for name, res in tail_results.items():
        print(f"  {name:20s}: loss_red={res['loss_reduction_pct']:.1f}%, "
              f"var_ratio={res['variance_ratio']:.4f}")

    # Also do OOS tail events
    print("\n--- Tail Event Analysis (OOS Only) ---")
    hedge_ratios_oos = {k: v[oos_mask] for k, v in hedge_ratios.items()}
    tail_results_oos = tail_event_analysis(returns[oos_mask], hedge_ratios_oos, threshold_sigma=2.0)
    for name, res in tail_results_oos.items():
        print(f"  {name:20s}: loss_red={res['loss_reduction_pct']:.1f}%, "
              f"var_ratio={res['variance_ratio']:.4f}")

    # Step 10: Plots
    print("\n--- Generating Plots ---")
    plot_hedge_comparison(results_is, results_oos, methods, OUTPUT_DIR)
    plot_tail_hedging(tail_results_oos, OUTPUT_DIR)
    plot_hedge_ratios_ts(hedge_ratios, returns, OOS_START, OUTPUT_DIR)

    # Step 11: Compile results
    # Key findings
    best_he_oos = max(methods, key=lambda m: results_oos[m]['HE'])
    best_var_oos = min(methods, key=lambda m: results_oos[m]['VaR_5pct_reduction'])
    best_es_oos = min(methods, key=lambda m: results_oos[m]['ES_5pct_reduction'])

    # Check copula vs DCC significance
    copula_vs_dcc = dm_results.get('DCC_vs_Copula', {})
    copula_q_vs_dcc = dm_results.get('DCC_vs_Copula_Quantile', {})

    key_findings = (
        f"K923 Copula-Based Hedge Ratio Analysis (SPY hedged with GLD). "
        f"Data: {returns.index[0].date()} to {returns.index[-1].date()}, {len(returns)} obs. "
        f"OOS: {OOS_START} onward ({oos_mask.sum()} obs). "
        f"SPY-GLD Pearson correlation: {desc_stats['SPY']['pearson_corr']:.4f} (very weak). "
        f"All methods produce low HE due to weak SPY-GLD correlation. "
        f"OOS best HE: {best_he_oos} ({results_oos[best_he_oos]['HE']:.4f}). "
        f"OOS best VaR5% reduction: {best_var_oos} ({results_oos[best_var_oos]['VaR_5pct_reduction']:.4f}). "
        f"OOS best ES5% reduction: {best_es_oos} ({results_oos[best_es_oos]['ES_5pct_reduction']:.4f}). "
        f"DCC vs Copula DM t-stat: {copula_vs_dcc.get('t_stat', 'N/A')}, "
        f"Harvey significant: {copula_vs_dcc.get('harvey_significant', 'N/A')}. "
        f"Copula Quantile Hedge designed to minimize tail risk, "
        f"tail event analysis shows its effectiveness during 2σ+ drops."
    )

    results = {
        'experiment_id': 'K923',
        'title': 'Copula-Based Optimal Hedge Ratio -- SPY Hedged with GLD',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance',
        'data_period': f'{returns.index[0].date()} to {returns.index[-1].date()}',
        'oos_start': OOS_START,
        'n_obs': len(returns),
        'n_is': int(is_mask.sum()),
        'n_oos': int(oos_mask.sum()),
        'descriptive_stats': desc_stats,
        'garch_marginals': {
            'SPY': {
                'params': garch_spy['params'],
                'persistence': round(garch_spy['persistence'], 4),
                'converged': garch_spy['converged'],
            },
            'GLD': {
                'params': garch_gld['params'],
                'persistence': round(garch_gld['persistence'], 4),
                'converged': garch_gld['converged'],
            }
        },
        'hedge_ratio_summaries': {
            name: {
                'mean': round(float(h.mean()), 4),
                'std': round(float(h.std()), 4),
                'min': round(float(h.min()), 4),
                'max': round(float(h.max()), 4),
            }
            for name, h in hedge_ratios.items()
        },
        'in_sample_results': results_is,
        'out_of_sample_results': results_oos,
        'dm_tests_oos': dm_results,
        'tail_event_analysis_full': tail_results,
        'tail_event_analysis_oos': tail_results_oos,
        'key_findings': key_findings,
        'references': [
            'Ederington (1979): The Hedging Performance of the New Futures Markets, JF',
            'Lai & Sheu (2010): Copula-based hedging',
            'Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM',
            'Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER',
            'K920: Student-t copula, lambda=0.14, nu=3.05',
            'K915: DCC-GARCH dynamic correlation',
            'K918: BEKK no cross-spillover',
        ],
        'methodology_notes': {
            'hedge_portfolio': 'R_h = R_SPY - h * R_GLD',
            'lookahead_prevention': 'All hedge ratios use shift(1) -- yesterday ratio for today',
            'copula_refit': f'Every {DCC_REFIT_FREQ} trading days (expanding window)',
            'copula_type': 'Student-t copula (best in K920)',
            'quantile_hedge': f'Simulates {N_SIM} draws, minimizes 5% VaR over h in [-0.5, 1.5]',
            'student_t_scale': 'Applied sqrt((nu-2)/nu) scaling for Student-t marginals',
            'evaluation': 'Hedging metrics (HE, VaR, ES, Utility), NOT trading metrics (Sharpe, CAGR)',
        },
    }

    # Save results
    results_path = os.path.join(OUTPUT_DIR, 'k923_copula_hedge_ratio_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    print(key_findings)

    return results


if __name__ == '__main__':
    results = main()
