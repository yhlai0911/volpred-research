#!/usr/bin/env python3
"""
K931: Copula-GARCH Hedge -- 0050.TW Hedged with 2330.TW (TSMC)

Question: Does copula-based hedging work for high-correlation pairs?
K923 showed copula hedge is NULL for SPY-GLD (r=0.058).
0050.TW-2330.TW should have r>0.85 (TSMC is ~50% of 0050.TW).

Method:
  1. Five hedge ratio methods: OLS, Rolling OLS, DCC, Copula-GARCH, Copula Quantile
  2. GJR-GARCH(1,1) Student-t marginals for both assets
  3. Student-t copula for joint dependence
  4. Hedging metrics: HE, VaR Reduction, ES Reduction, Utility, Turnover
  5. IS (2006-2018) and OOS (2019-2026) evaluation
  6. Cross-comparison with K923 SPY-GLD

Data: 0050.TW, 2330.TW daily from yfinance, 2006-01-01 to 2026-04-04
IS: 2006-2018, OOS: 2019-2026

References:
  - Ederington (1979): The Hedging Performance of the New Futures Markets, JF
  - Lai & Sheu (2010): Copula-based hedging
  - Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM
  - Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER

Prior work:
  - K923: Copula hedge NULL for SPY-GLD (r=0.058, HE<3%)
  - K920: Student-t copula best for SPY-GLD

Error log rules applied:
  - Fixed seed: np.random.seed(42)
  - 0050.TW: must use clean_tw50_data()
  - Hedge ratio uses shift(1) -- no lookahead
  - Student-t scale: must consider sqrt((df-2)/df)
  - Hedging uses hedging metrics (HE/VaR/Utility), NOT Sharpe/CAGR

Author: VolPred Research System
"""

import json
import os
import sys
import warnings
from datetime import datetime

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
SPOT_TICKER = '0050.TW'
HEDGE_TICKER = '2330.TW'
SPOT_NAME = '0050'
HEDGE_NAME = 'TSMC'
START_DATE = '2006-01-01'
END_DATE = '2026-04-04'
OOS_START = '2019-01-01'
ROLLING_WINDOW = 250
DCC_REFIT_FREQ = 63   # Refit every ~quarter
N_SIM = 10000          # Monte Carlo for copula quantile hedge
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# Step 1: Data Collection
# ============================================================
def fetch_data():
    """Fetch daily prices for 0050.TW and 2330.TW from yfinance."""
    import yfinance as yf

    # Add project root to path for clean_tw50_data
    project_root = os.path.abspath(os.path.join(OUTPUT_DIR, '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from src.volpred.utils import clean_tw50_data

    tickers = [SPOT_TICKER, HEDGE_TICKER]
    data = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

    if isinstance(data.columns, pd.MultiIndex):
        prices = data['Close']
    else:
        prices = data[['Close']]

    prices = prices.dropna()

    # Clean 0050.TW split artifact
    if SPOT_TICKER in prices.columns:
        spot_prices = prices[SPOT_TICKER]
        spot_returns_raw = spot_prices.pct_change()
        clean_p, clean_r = clean_tw50_data(spot_prices, spot_returns_raw)
        prices[SPOT_TICKER] = clean_p
        print(f"Applied clean_tw50_data() to {SPOT_TICKER}")

    # Check 2330.TW for split issues (2014 forward split check)
    hedge_prices = prices[HEDGE_TICKER]
    hedge_returns_check = hedge_prices.pct_change().dropna()
    extreme_returns = hedge_returns_check[hedge_returns_check.abs() > 0.5]
    if len(extreme_returns) > 0:
        print(f"WARNING: {HEDGE_TICKER} has {len(extreme_returns)} returns > 50%:")
        for dt, val in extreme_returns.items():
            print(f"  {dt.date()}: {val:.4f}")

    returns = prices.pct_change().dropna()

    # Rename columns for clarity
    prices.columns = [SPOT_NAME, HEDGE_NAME]
    returns.columns = [SPOT_NAME, HEDGE_NAME]

    print(f"\nData: {returns.index[0].date()} to {returns.index[-1].date()}, {len(returns)} obs")
    print(f"Pearson correlation: {returns[SPOT_NAME].corr(returns[HEDGE_NAME]):.4f}")
    print(f"Spearman correlation: {returns[SPOT_NAME].corr(returns[HEDGE_NAME], method='spearman'):.4f}")

    return prices, returns


# ============================================================
# Step 2: Descriptive Statistics
# ============================================================
def compute_descriptive_stats(returns):
    """Compute descriptive statistics for both assets."""
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch

    stats_dict = {}
    corr_pearson = returns.corr().iloc[0, 1]
    corr_spearman = returns.corr(method='spearman').iloc[0, 1]

    for col in returns.columns:
        r = returns[col].dropna()
        adf = adfuller(r, maxlag=20, autolag='AIC')

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
            'pearson_corr': round(float(corr_pearson), 4),
            'spearman_corr': round(float(corr_spearman), 4),
        }
        print(f"\n{col}: mean={stats_dict[col]['mean']:.6f}, std={stats_dict[col]['std']:.6f}, "
              f"skew={stats_dict[col]['skew']:.4f}, kurt={stats_dict[col]['kurtosis']:.4f}")
        print(f"  ADF={stats_dict[col]['adf_stat']}, ARCH LM={stats_dict[col]['arch_lm_stat']}")

    print(f"\nPearson correlation: {corr_pearson:.4f}")
    print(f"Spearman correlation: {corr_spearman:.4f}")

    return stats_dict


# ============================================================
# Step 2b: Rolling Correlation Analysis
# ============================================================
def compute_rolling_correlation(returns, window=250):
    """Compute rolling Pearson and Spearman correlation."""
    rolling_pearson = returns[SPOT_NAME].rolling(window).corr(returns[HEDGE_NAME])
    rolling_spearman = returns[SPOT_NAME].rolling(window).apply(
        lambda x: sp_stats.spearmanr(x, returns[HEDGE_NAME].loc[x.index])[0],
        raw=False
    )

    stats = {
        'rolling_pearson_mean': float(rolling_pearson.mean()),
        'rolling_pearson_std': float(rolling_pearson.std()),
        'rolling_pearson_min': float(rolling_pearson.min()),
        'rolling_pearson_max': float(rolling_pearson.max()),
    }

    print(f"\nRolling {window}d Pearson correlation:")
    print(f"  Mean={stats['rolling_pearson_mean']:.4f}, "
          f"Std={stats['rolling_pearson_std']:.4f}, "
          f"Min={stats['rolling_pearson_min']:.4f}, "
          f"Max={stats['rolling_pearson_max']:.4f}")

    # Plot rolling correlation
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(rolling_pearson.index, rolling_pearson.values, 'b-', alpha=0.7, label='Rolling Pearson')
    ax.axhline(y=rolling_pearson.mean(), color='r', linestyle='--', label=f'Mean={rolling_pearson.mean():.3f}')
    ax.axhline(y=0.85, color='g', linestyle=':', label='r=0.85 threshold')
    ax.set_title(f'{SPOT_NAME}-{HEDGE_NAME} Rolling {window}d Correlation', fontsize=14)
    ax.set_ylabel('Correlation')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'k931_rolling_correlation.png'), dpi=150)
    plt.close()

    return stats, rolling_pearson


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
    # Good initial guess for high-correlation pairs
    rho_init = np.corrcoef(sp_stats.t.ppf(u1, df=5), sp_stats.t.ppf(u2, df=5))[0, 1]
    rho_init_param = np.arctanh(np.clip(rho_init, -0.999, 0.999))

    res = minimize(student_t_copula_ll, x0=[rho_init_param, 1.0], args=(u1, u2),
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

    cov_matrix = np.array([[1.0, rho], [rho, 1.0]])
    z = rng.multivariate_normal(mean=[0, 0], cov=cov_matrix, size=n_sim)

    chi2 = rng.chisquare(df=nu, size=n_sim)
    scale = np.sqrt(nu / chi2)

    t_samples = z * scale[:, np.newaxis]

    u1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
    u2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

    return u1, u2


# ============================================================
# Step 5: DCC-GARCH (simplified)
# ============================================================
def compute_dcc_correlation(std_resid_spot, std_resid_hedge, a=0.01, b=0.95):
    """
    Compute DCC dynamic correlation.
    DCC(1,1): Q_t = (1-a-b)*Qbar + a*eps_{t-1}*eps_{t-1}' + b*Q_{t-1}
    """
    T = len(std_resid_spot)
    eps1 = std_resid_spot.values if hasattr(std_resid_spot, 'values') else std_resid_spot
    eps2 = std_resid_hedge.values if hasattr(std_resid_hedge, 'values') else std_resid_hedge

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
def compute_hedge_ratios(returns, garch_spot, garch_hedge, oos_start_idx):
    """
    Compute 5 hedge ratio series, all using shift(1) to avoid lookahead.
    """
    r_spot = returns[SPOT_NAME].values
    r_hedge = returns[HEDGE_NAME].values
    T = len(r_spot)
    idx = returns.index

    sig_spot = garch_spot['cond_vol'].values
    sig_hedge = garch_hedge['cond_vol'].values
    std_r_spot = garch_spot['std_resid']
    std_r_hedge = garch_hedge['std_resid']
    nu_spot = garch_spot['nu']
    nu_hedge = garch_hedge['nu']

    # ---- Method 1: OLS (expanding window) ----
    h_ols = np.full(T, np.nan)
    for t in range(ROLLING_WINDOW, T):
        cov_ = np.cov(r_spot[:t], r_hedge[:t])[0, 1]
        var_ = np.var(r_hedge[:t])
        if var_ > 0:
            h_ols[t] = cov_ / var_
    first_valid = h_ols[ROLLING_WINDOW]
    h_ols[:ROLLING_WINDOW] = first_valid

    # ---- Method 2: Rolling OLS (250-day window) ----
    h_rolling = np.full(T, np.nan)
    for t in range(ROLLING_WINDOW, T):
        window_spot = r_spot[t - ROLLING_WINDOW:t]
        window_hedge = r_hedge[t - ROLLING_WINDOW:t]
        cov_ = np.cov(window_spot, window_hedge)[0, 1]
        var_ = np.var(window_hedge)
        if var_ > 0:
            h_rolling[t] = cov_ / var_
    h_rolling[:ROLLING_WINDOW] = h_rolling[ROLLING_WINDOW]

    # ---- Method 3: DCC-GARCH ----
    rho_dcc = compute_dcc_correlation(std_r_spot, std_r_hedge)
    h_dcc = np.full(T, np.nan)
    for t in range(T):
        if sig_hedge[t] > 0:
            h_dcc[t] = rho_dcc[t] * sig_spot[t] / sig_hedge[t]

    # ---- Method 4: Copula-GARCH ----
    h_copula = np.full(T, np.nan)
    copula_rho_series = np.full(T, np.nan)
    copula_nu_series = np.full(T, np.nan)

    min_fit_window = 500

    u1_all = probability_integral_transform(std_r_spot, nu_spot)
    u2_all = probability_integral_transform(std_r_hedge, nu_hedge)

    last_refit = 0
    current_copula_rho = 0.0
    current_copula_nu = 5.0

    print("\nFitting copula hedge ratios (refit every 63 days)...")
    for t in range(min_fit_window, T):
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
                pass

        copula_rho_series[t] = current_copula_rho
        copula_nu_series[t] = current_copula_nu

        if sig_hedge[t] > 0:
            h_copula[t] = current_copula_rho * sig_spot[t] / sig_hedge[t]

    h_copula[:min_fit_window] = h_copula[min_fit_window]

    # ---- Method 5: Copula Quantile Hedge ----
    h_quantile = np.full(T, np.nan)

    print("Computing copula quantile hedge ratios...")
    last_refit_q = 0
    current_h_q = 0.0
    rng = np.random.default_rng(42)

    for t in range(min_fit_window, T):
        if t - last_refit_q >= DCC_REFIT_FREQ or t == min_fit_window:
            rho_c = copula_rho_series[t] if np.isfinite(copula_rho_series[t]) else 0.0
            nu_c = current_copula_nu

            u1_sim, u2_sim = simulate_copula(rho_c, nu_c, N_SIM, rng)

            z1 = sp_stats.t.ppf(u1_sim, df=nu_spot)
            z2 = sp_stats.t.ppf(u2_sim, df=nu_hedge)

            # Scale by GARCH vol with Student-t correction
            scale_spot = np.sqrt((nu_spot - 2) / nu_spot) if nu_spot > 2 else 1.0
            scale_hedge = np.sqrt((nu_hedge - 2) / nu_hedge) if nu_hedge > 2 else 1.0

            r_spot_sim = sig_spot[t] * z1 * scale_spot
            r_hedge_sim = sig_hedge[t] * z2 * scale_hedge

            # Find h that maximizes 5th percentile (minimizes VaR)
            h_candidates = np.linspace(-0.2, 1.5, 171)
            vars_5 = np.array([np.percentile(r_spot_sim - h * r_hedge_sim, 5) for h in h_candidates])
            best_idx = np.argmax(vars_5)
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

    for name in hedge_ratios:
        hedge_ratios[name] = hedge_ratios[name].ffill().bfill()

    return hedge_ratios, copula_rho_series, copula_nu_series


# ============================================================
# Step 7: Hedging Evaluation Metrics
# ============================================================
def compute_hedging_metrics(returns_spot, returns_hedge, hedge_ratio, period_name):
    """
    Compute hedging effectiveness metrics.
    Hedge portfolio: R_h = R_spot - h * R_hedge
    """
    r_spot = returns_spot.values
    r_hedge = returns_hedge.values
    h = hedge_ratio.values

    r_hedged = r_spot - h * r_hedge
    r_unhedged = r_spot

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
    var_5_reduction = var_5_hedged / var_5_unhedged if var_5_unhedged != 0 else np.nan

    # ES at 5%
    es_mask_u = r_unhedged <= var_5_unhedged
    es_mask_h = r_hedged <= var_5_hedged
    es_unhedged = np.mean(r_unhedged[es_mask_u]) if es_mask_u.sum() > 0 else np.nan
    es_hedged = np.mean(r_hedged[es_mask_h]) if es_mask_h.sum() > 0 else np.nan
    es_5_reduction = es_hedged / es_unhedged if es_unhedged != 0 else np.nan

    # VaR at 1%
    var_1_unhedged = np.percentile(r_unhedged, 1)
    var_1_hedged = np.percentile(r_hedged, 1)
    var_1_reduction = var_1_hedged / var_1_unhedged if var_1_unhedged != 0 else np.nan

    # ES at 1%
    es1_mask_u = r_unhedged <= var_1_unhedged
    es1_mask_h = r_hedged <= var_1_hedged
    es1_unhedged = np.mean(r_unhedged[es1_mask_u]) if es1_mask_u.sum() > 0 else np.nan
    es1_hedged = np.mean(r_hedged[es1_mask_h]) if es1_mask_h.sum() > 0 else np.nan
    es_1_reduction = es1_hedged / es1_unhedged if es1_unhedged != 0 else np.nan

    # CRRA Utility
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

    # Turnover
    h_changes = np.abs(np.diff(h_valid))
    turnover = float(np.mean(h_changes))

    return {
        'period': period_name,
        'n_obs': len(r_hedged),
        'HE': round(float(HE), 6),
        'var_hedged': float(var_hedged),
        'var_unhedged': float(var_unhedged),
        'VaR_5pct_unhedged': float(var_5_unhedged),
        'VaR_5pct_hedged': float(var_5_hedged),
        'VaR_5pct_reduction': round(float(var_5_reduction), 4),
        'ES_5pct_unhedged': float(es_unhedged),
        'ES_5pct_hedged': float(es_hedged),
        'ES_5pct_reduction': round(float(es_5_reduction), 4),
        'VaR_1pct_unhedged': float(var_1_unhedged),
        'VaR_1pct_hedged': float(var_1_hedged),
        'VaR_1pct_reduction': round(float(var_1_reduction), 4),
        'ES_1pct_unhedged': float(es1_unhedged),
        'ES_1pct_hedged': float(es1_hedged),
        'ES_1pct_reduction': round(float(es_1_reduction), 4),
        'mean_return_hedged': float(mean_hedged),
        'mean_return_unhedged': float(mean_unhedged),
        'utility': utility_results,
        'turnover': round(turnover, 6),
        'mean_hedge_ratio': round(float(np.mean(h_valid)), 4),
        'std_hedge_ratio': round(float(np.std(h_valid)), 4),
    }


# ============================================================
# Step 8: Tail Event Analysis
# ============================================================
def analyze_tail_events(returns, hedge_ratios, threshold_sigma=2.0):
    """Analyze hedging during tail events (spot drops > threshold * sigma)."""
    r_spot = returns[SPOT_NAME]
    r_hedge = returns[HEDGE_NAME]

    sigma_spot = r_spot.std()
    threshold = -threshold_sigma * sigma_spot

    tail_mask = r_spot < threshold
    n_tail = tail_mask.sum()
    print(f"\nTail events ({SPOT_NAME} < {threshold:.4f}, {threshold_sigma}*sigma): {n_tail} days")

    if n_tail < 5:
        return {'n_tail_events': int(n_tail), 'note': 'Too few tail events'}

    tail_results = {}
    for name, hr in hedge_ratios.items():
        r_hedged_tail = (r_spot - hr * r_hedge)[tail_mask]
        r_unhedged_tail = r_spot[tail_mask]

        var_reduction_tail = r_hedged_tail.var() / r_unhedged_tail.var()
        mean_loss_hedged = r_hedged_tail.mean()
        mean_loss_unhedged = r_unhedged_tail.mean()

        tail_results[name] = {
            'mean_hedged_return': round(float(mean_loss_hedged), 6),
            'mean_unhedged_return': round(float(mean_loss_unhedged), 6),
            'loss_reduction_pct': round(float((1 - mean_loss_hedged / mean_loss_unhedged) * 100), 2),
            'var_ratio': round(float(var_reduction_tail), 4),
        }

    return {
        'n_tail_events': int(n_tail),
        'threshold': round(float(threshold), 6),
        'threshold_sigma': threshold_sigma,
        'methods': tail_results,
    }


# ============================================================
# Step 9: Plotting
# ============================================================
def plot_hedge_comparison(is_results, oos_results, hedge_ratios, returns):
    """Plot hedge effectiveness comparison and hedge ratio time series."""

    # --- Plot 1: HE comparison ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    methods = list(is_results.keys())
    he_is = [is_results[m]['HE'] for m in methods]
    he_oos = [oos_results[m]['HE'] for m in methods]

    x = np.arange(len(methods))
    width = 0.35

    bars1 = axes[0].bar(x - width/2, he_is, width, label='In-Sample', color='steelblue', alpha=0.8)
    bars2 = axes[0].bar(x + width/2, he_oos, width, label='Out-of-Sample', color='coral', alpha=0.8)
    axes[0].set_xlabel('Method')
    axes[0].set_ylabel('Hedging Effectiveness (HE)')
    axes[0].set_title(f'{SPOT_NAME}-{HEDGE_NAME} Hedging Effectiveness')
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(methods, rotation=45, ha='right')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3, axis='y')
    axes[0].axhline(y=0, color='k', linestyle='-', linewidth=0.5)

    # Add value labels
    for bar in bars1:
        height = bar.get_height()
        axes[0].annotate(f'{height:.3f}',
                         xy=(bar.get_x() + bar.get_width() / 2, height),
                         xytext=(0, 3), textcoords="offset points",
                         ha='center', va='bottom', fontsize=8)
    for bar in bars2:
        height = bar.get_height()
        axes[0].annotate(f'{height:.3f}',
                         xy=(bar.get_x() + bar.get_width() / 2, height),
                         xytext=(0, 3), textcoords="offset points",
                         ha='center', va='bottom', fontsize=8)

    # --- Plot 2: VaR/ES reduction ---
    var_is = [is_results[m].get('VaR_5pct_reduction', 1.0) for m in methods]
    var_oos = [oos_results[m].get('VaR_5pct_reduction', 1.0) for m in methods]

    bars3 = axes[1].bar(x - width/2, var_is, width, label='IS VaR5% Ratio', color='steelblue', alpha=0.8)
    bars4 = axes[1].bar(x + width/2, var_oos, width, label='OOS VaR5% Ratio', color='coral', alpha=0.8)
    axes[1].set_xlabel('Method')
    axes[1].set_ylabel('VaR Ratio (hedged/unhedged)')
    axes[1].set_title(f'{SPOT_NAME}-{HEDGE_NAME} VaR 5% Reduction')
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(methods, rotation=45, ha='right')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3, axis='y')
    axes[1].axhline(y=1.0, color='k', linestyle='--', linewidth=0.5, label='No improvement')

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'k931_hedge_comparison.png'), dpi=150)
    plt.close()

    # --- Plot 3: Hedge ratio time series ---
    fig, ax = plt.subplots(figsize=(14, 6))
    colors = ['blue', 'green', 'red', 'purple', 'orange']
    for (name, hr), color in zip(hedge_ratios.items(), colors):
        ax.plot(hr.index, hr.values, color=color, alpha=0.6, label=name, linewidth=0.8)

    oos_date = pd.Timestamp(OOS_START)
    ax.axvline(x=oos_date, color='k', linestyle='--', alpha=0.5, label='OOS Start')
    ax.set_title(f'{SPOT_NAME}-{HEDGE_NAME} Hedge Ratios Over Time', fontsize=14)
    ax.set_ylabel('Hedge Ratio')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'k931_hedge_ratios_ts.png'), dpi=150)
    plt.close()

    # --- Plot 4: Tail event hedging ---
    fig, ax = plt.subplots(figsize=(12, 5))
    r_spot = returns[SPOT_NAME]
    sigma_spot = r_spot.std()
    threshold = -2.0 * sigma_spot
    tail_mask = r_spot < threshold
    tail_dates = r_spot.index[tail_mask]

    if len(tail_dates) > 0:
        for name, hr in hedge_ratios.items():
            r_hedged = r_spot - hr * returns[HEDGE_NAME]
            ax.scatter(r_spot[tail_mask].values, r_hedged[tail_mask].values,
                       alpha=0.4, s=15, label=name)

        lims = [min(r_spot[tail_mask].min(), -0.08), 0]
        ax.plot(lims, lims, 'k--', alpha=0.3, label='No hedge (45°)')
        ax.set_xlabel(f'Unhedged {SPOT_NAME} Return')
        ax.set_ylabel(f'Hedged Return')
        ax.set_title(f'Tail Event Hedging ({SPOT_NAME} < {threshold:.4f})', fontsize=14)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'k931_tail_hedging.png'), dpi=150)
    plt.close()


# ============================================================
# Step 10: Cross-comparison with K923
# ============================================================
def cross_compare_k923(oos_results, corr_data):
    """Compare K931 (TW) with K923 (US) results."""
    # K923 OOS results (from k923_copula_hedge_ratio_results.json)
    k923_oos = {
        'OLS': {'HE': -0.003281, 'VaR_5pct_reduction': 1.0124},
        'Rolling_OLS': {'HE': -0.002741, 'VaR_5pct_reduction': 1.0075},
        'DCC': {'HE': 0.008556, 'VaR_5pct_reduction': 1.0142},
        'Copula': {'HE': 0.029445, 'VaR_5pct_reduction': 1.0006},
        'Copula_Quantile': {'HE': -0.023759, 'VaR_5pct_reduction': 1.0265},
    }

    comparison = {}
    for method in oos_results:
        k931_he = oos_results[method]['HE']
        k923_he = k923_oos.get(method, {}).get('HE', np.nan)
        comparison[method] = {
            'K931_TW_HE': round(k931_he, 6),
            'K923_US_HE': round(k923_he, 6),
            'HE_improvement': round(k931_he - k923_he, 6),
        }

    comparison['correlation_comparison'] = {
        'K931_TW_pearson': round(corr_data.get('pearson_corr', np.nan), 4),
        'K923_US_pearson': 0.0583,
        'correlation_ratio': round(corr_data.get('pearson_corr', 0) / 0.0583, 2),
    }

    return comparison


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("K931: Copula-GARCH Hedge -- 0050.TW Hedged with 2330.TW (TSMC)")
    print("=" * 70)

    # Step 1: Fetch data
    prices, returns = fetch_data()

    # Step 2: Descriptive statistics
    desc_stats = compute_descriptive_stats(returns)

    # Step 2b: Rolling correlation
    rolling_stats, rolling_corr = compute_rolling_correlation(returns)

    # Check if correlation is high enough for hedging
    corr = returns[SPOT_NAME].corr(returns[HEDGE_NAME])
    if corr < 0.5:
        print(f"\nWARNING: Correlation ({corr:.4f}) may be too low for effective hedging")

    # Step 3: Fit GJR-GARCH marginals
    returns_pct = returns * 100  # arch expects percentage returns

    garch_spot = fit_gjr_garch(returns_pct[SPOT_NAME], SPOT_NAME)
    garch_hedge = fit_gjr_garch(returns_pct[HEDGE_NAME], HEDGE_NAME)

    # Step 4-6: Compute hedge ratios
    oos_start_idx = returns.index.get_indexer([pd.Timestamp(OOS_START)], method='nearest')[0]
    hedge_ratios, copula_rho, copula_nu = compute_hedge_ratios(
        returns, garch_spot, garch_hedge, oos_start_idx
    )

    # Print hedge ratio summaries
    print("\n" + "=" * 50)
    print("Hedge Ratio Summaries:")
    print("=" * 50)
    hr_summaries = {}
    for name, hr in hedge_ratios.items():
        valid = hr.dropna()
        hr_summaries[name] = {
            'mean': round(float(valid.mean()), 4),
            'std': round(float(valid.std()), 4),
            'min': round(float(valid.min()), 4),
            'max': round(float(valid.max()), 4),
        }
        print(f"  {name}: mean={valid.mean():.4f}, std={valid.std():.4f}, "
              f"min={valid.min():.4f}, max={valid.max():.4f}")

    # Step 7: Evaluate IS and OOS
    oos_start = pd.Timestamp(OOS_START)
    is_mask = returns.index < oos_start
    oos_mask = returns.index >= oos_start

    is_results = {}
    oos_results = {}

    print("\n" + "=" * 50)
    print("In-Sample Results:")
    print("=" * 50)
    for name, hr in hedge_ratios.items():
        is_metrics = compute_hedging_metrics(
            returns[SPOT_NAME][is_mask], returns[HEDGE_NAME][is_mask],
            hr[is_mask], f'IS_{name}'
        )
        if is_metrics:
            is_results[name] = is_metrics
            print(f"\n  {name}: HE={is_metrics['HE']:.4f}, "
                  f"VaR5%={is_metrics['VaR_5pct_reduction']:.4f}, "
                  f"ES5%={is_metrics['ES_5pct_reduction']:.4f}, "
                  f"Turnover={is_metrics['turnover']:.6f}")

    print("\n" + "=" * 50)
    print("Out-of-Sample Results:")
    print("=" * 50)
    for name, hr in hedge_ratios.items():
        oos_metrics = compute_hedging_metrics(
            returns[SPOT_NAME][oos_mask], returns[HEDGE_NAME][oos_mask],
            hr[oos_mask], f'OOS_{name}'
        )
        if oos_metrics:
            oos_results[name] = oos_metrics
            print(f"\n  {name}: HE={oos_metrics['HE']:.4f}, "
                  f"VaR5%={oos_metrics['VaR_5pct_reduction']:.4f}, "
                  f"ES5%={oos_metrics['ES_5pct_reduction']:.4f}, "
                  f"Turnover={oos_metrics['turnover']:.6f}")

    # Step 8: Tail event analysis
    tail_all = analyze_tail_events(returns, hedge_ratios, threshold_sigma=2.0)
    tail_oos = analyze_tail_events(
        returns[oos_mask].copy(),
        {k: v[oos_mask] for k, v in hedge_ratios.items()},
        threshold_sigma=2.0
    )

    # Step 9: Plots
    plot_hedge_comparison(is_results, oos_results, hedge_ratios, returns)

    # Step 10: Cross-comparison with K923
    cross_comparison = cross_compare_k923(
        oos_results,
        desc_stats[SPOT_NAME]
    )

    # Copula statistics
    copula_stats = {
        'copula_rho_mean': round(float(np.nanmean(copula_rho)), 4),
        'copula_rho_std': round(float(np.nanstd(copula_rho)), 4),
        'copula_rho_min': round(float(np.nanmin(copula_rho)), 4),
        'copula_rho_max': round(float(np.nanmax(copula_rho)), 4),
        'copula_nu_mean': round(float(np.nanmean(copula_nu)), 4),
    }

    print("\n" + "=" * 50)
    print("Copula Statistics:")
    print(f"  rho: mean={copula_stats['copula_rho_mean']}, "
          f"std={copula_stats['copula_rho_std']}")
    print(f"  nu: mean={copula_stats['copula_nu_mean']}")

    print("\n" + "=" * 50)
    print("Cross-comparison with K923 (SPY-GLD):")
    print("=" * 50)
    for method, comp in cross_comparison.items():
        if method != 'correlation_comparison':
            print(f"  {method}: K931(TW)={comp['K931_TW_HE']:.4f}, "
                  f"K923(US)={comp['K923_US_HE']:.4f}, "
                  f"Diff={comp['HE_improvement']:.4f}")

    corr_comp = cross_comparison.get('correlation_comparison', {})
    print(f"\n  Correlation: TW={corr_comp.get('K931_TW_pearson', 'N/A')}, "
          f"US={corr_comp.get('K923_US_pearson', 'N/A')}, "
          f"Ratio={corr_comp.get('correlation_ratio', 'N/A')}x")

    # Determine conclusion
    best_oos = max(oos_results.items(), key=lambda x: x[1]['HE'])
    best_method = best_oos[0]
    best_he = best_oos[1]['HE']

    conclusion = f"Best OOS method: {best_method} (HE={best_he:.4f}). "
    if best_he > 0.5:
        conclusion += "Copula hedging is EFFECTIVE for high-correlation pairs."
    elif best_he > 0.1:
        conclusion += "Copula hedging shows MODERATE effectiveness."
    elif best_he > 0:
        conclusion += "Copula hedging shows MARGINAL improvement."
    else:
        conclusion += "Even high correlation is INSUFFICIENT for effective hedging."

    tw_he = best_he
    us_he = max(cross_comparison.get(m, {}).get('K923_US_HE', -1) for m in ['OLS', 'Rolling_OLS', 'DCC', 'Copula', 'Copula_Quantile'] if m in cross_comparison)
    conclusion += f" TW best HE ({tw_he:.4f}) vs US best HE ({us_he:.4f}): "
    if tw_he > us_he + 0.05:
        conclusion += "High correlation significantly improves hedging."
    else:
        conclusion += "High correlation does not dramatically improve hedging."

    print(f"\n{'=' * 50}")
    print(f"CONCLUSION: {conclusion}")
    print(f"{'=' * 50}")

    # Save results
    results = {
        'experiment_id': 'K931',
        'title': f'Copula-GARCH Hedge -- {SPOT_NAME} Hedged with {HEDGE_NAME}',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance',
        'data_period': f"{returns.index[0].date()} to {returns.index[-1].date()}",
        'oos_start': OOS_START,
        'n_obs': len(returns),
        'n_is': int(is_mask.sum()),
        'n_oos': int(oos_mask.sum()),
        'assets': {
            'spot': SPOT_TICKER,
            'hedge': HEDGE_TICKER,
        },
        'descriptive_stats': desc_stats,
        'rolling_correlation': rolling_stats,
        'garch_marginals': {
            SPOT_NAME: {
                'params': garch_spot['params'],
                'persistence': round(garch_spot['persistence'], 4),
                'converged': garch_spot['converged'],
            },
            HEDGE_NAME: {
                'params': garch_hedge['params'],
                'persistence': round(garch_hedge['persistence'], 4),
                'converged': garch_hedge['converged'],
            },
        },
        'copula_stats': copula_stats,
        'hedge_ratio_summaries': hr_summaries,
        'in_sample_results': is_results,
        'out_of_sample_results': oos_results,
        'tail_analysis_all': tail_all,
        'tail_analysis_oos': tail_oos,
        'cross_comparison_k923': cross_comparison,
        'conclusion': conclusion,
        'references': [
            'Ederington (1979): The Hedging Performance of the New Futures Markets, JF',
            'Lai & Sheu (2010): Copula-based hedging',
            'Hsu, Tseng & Wang (2008): Dynamic Hedging with Futures, JFM',
            'Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER',
        ],
    }

    output_path = os.path.join(OUTPUT_DIR, 'k931_copula_hedge_tw_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == '__main__':
    main()
