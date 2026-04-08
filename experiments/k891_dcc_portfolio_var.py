#!/usr/bin/env python3
"""
K891: DCC-GARCH Portfolio VaR — Does Dynamic Correlation Help?
================================================================
[提出: research_program.md 面向 A, 執行: Claude]

Motivation:
  Our current portfolio VaR approach estimates each asset's volatility
  independently (GJR per asset) then combines with constant correlation.
  DCC-GARCH (Engle 2002) models time-varying correlations, which should
  improve portfolio-level VaR, especially for SPY/GLD where correlation
  swings from -0.5 (crisis) to +0.4 (normal).

Prior knowledge:
  - K104: DCC-GARCH SPY-GLD correlation exists (a=0.032, b=0.955)
    but does NOT improve 2-asset Risk Parity allocation
  - K824v2: FHS > Student-t for single-asset VaR
  - K846: 50/50 three moats (diversification + rebalancing + crisis alpha)

THIS EXPERIMENT: Does DCC improve portfolio-level VaR estimation?
  NOT about allocation (K104 answered that). About risk measurement.

Models (5):
  M1: Independent GJR + constant corr + Normal VaR
  M2: DCC-GJR + Normal VaR
  M3: DCC-GJR + Student-t VaR
  M4: DCC-GJR + Historical Simulation VaR
  M5: Independent GJR + constant corr + HistSim VaR (current best)

Data:
  - yfinance: SPY, GLD (2005-01-01 to 2026-04-01)
  - Portfolio: 50% SPY + 50% GLD (monthly rebalanced)
  - OOS: 2019-01-01 to latest (~1800 days)
  - Refit: every 63 trading days

Evaluation:
  - VaR 1% and 5%: Kupiec + Christoffersen + Basel Trinity
  - ES backtest: Acerbi-Szekely Z-test (Z1 and Z2)
  - DM test on VaR QLIKE losses (Harvey |t| > 3.0)
  - Capital efficiency: average VaR width

Error log rules applied:
  - DM test: use volpred.stats.model_evaluation.dm_test
  - Student-t: scale term sqrt((df-2)/df) for proper standardization
  - GARCH OOS: recursive h[t] = f(h[t-1], r²[t-1])
  - Basel traffic light: standard thresholds (green/yellow/red)

References:
  - Engle (2002): Dynamic Conditional Correlation, J Business & Econ Stat
  - Engle & Sheppard (2001): Theoretical and empirical properties of DCC
  - GJR-GARCH: Glosten, Jagannathan & Runkle (1993), J Finance
  - Kupiec (1995): VaR coverage test
  - Christoffersen (1998): VaR independence test
  - Acerbi & Szekely (2014): ES backtesting
  - Patton (2011): QLIKE proxy-robust loss
  - Harvey et al. (2016): multiple testing threshold t>3.0

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats as sp_stats
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k891_dcc_portfolio_var_results.json')
ASSETS = ['SPY', 'GLD']
WEIGHTS = np.array([0.5, 0.5])
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
MIN_TRAIN = 1000  # min training days
HIST_SIM_WINDOW = 500  # for historical simulation

# ============================================================
# Data Loading
# ============================================================
def load_data():
    """Load SPY and GLD from yfinance."""
    import yfinance as yf

    print("Downloading SPY and GLD data...")
    data = yf.download(ASSETS, start=DATA_START, end=DATA_END, auto_adjust=True)

    # Handle multi-level columns from yfinance
    if isinstance(data.columns, pd.MultiIndex):
        close = data['Close']
    else:
        close = data

    close = close.dropna()
    returns = close.pct_change().dropna()

    print(f"Data period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total days: {len(returns)}")

    return close, returns


# ============================================================
# GJR-GARCH Estimation (using arch package)
# ============================================================
def fit_gjr(returns_series, p=1, o=1, q=1, dist='normal'):
    """Fit GJR-GARCH(1,1) using arch package. Returns model result."""
    from arch import arch_model

    # Scale returns to percentage for numerical stability
    r_pct = returns_series * 100

    am = arch_model(r_pct, vol='GARCH', p=p, o=o, q=q, mean='Constant', dist=dist)
    res = am.fit(disp='off', show_warning=False)
    return res


def gjr_forecast_oos(returns_df, oos_start, refit_every=63):
    """
    Recursive OOS forecasting with GJR-GARCH for each asset.
    Returns DataFrame of conditional variances (in return scale, not pct).

    CRITICAL: h[t] = f(h[t-1], r²[t-1]) — no lookahead.
    """
    from arch import arch_model

    oos_idx = returns_df.index >= oos_start
    oos_dates = returns_df.index[oos_idx]
    n_oos = len(oos_dates)

    if n_oos == 0:
        raise ValueError(f"No OOS data after {oos_start}")

    assets = returns_df.columns.tolist()
    sigma2_oos = pd.DataFrame(index=oos_dates, columns=assets, dtype=float)

    for asset in assets:
        r_all = returns_df[asset]
        r_pct = r_all * 100

        # Track fitted model
        last_fit_idx = -refit_every  # force initial fit
        model_params = None
        h_prev = None

        for i, date in enumerate(oos_dates):
            loc = returns_df.index.get_loc(date)

            # Refit?
            if i - last_fit_idx >= refit_every or model_params is None:
                train_data = r_pct.iloc[:loc]
                if len(train_data) < MIN_TRAIN:
                    train_data = r_pct.iloc[:loc]

                am = arch_model(train_data, vol='GARCH', p=1, o=1, q=1,
                                mean='Constant', dist='normal')
                try:
                    res = am.fit(disp='off', show_warning=False)
                    model_params = {
                        'omega': res.params.get('omega', 0.01),
                        'alpha': res.params.get('alpha[1]', 0.05),
                        'gamma': res.params.get('gamma[1]', 0.05),
                        'beta': res.params.get('beta[1]', 0.90),
                        'mu': res.params.get('mu', 0.0),
                    }
                    # Get last conditional variance from the fit
                    h_prev = float(res.conditional_volatility.iloc[-1] ** 2)
                    last_fit_idx = i
                except Exception:
                    if model_params is None:
                        model_params = {'omega': 0.01, 'alpha': 0.05,
                                        'gamma': 0.05, 'beta': 0.90, 'mu': 0.0}
                        h_prev = float(np.var(train_data))

            # Recursive forecast: h[t] = omega + (alpha + gamma*I)*r²[t-1] + beta*h[t-1]
            r_prev = float(r_pct.iloc[loc - 1])  # yesterday's return (pct)
            eps_prev = r_prev - model_params['mu']
            indicator = 1.0 if eps_prev < 0 else 0.0

            h_t = (model_params['omega']
                   + (model_params['alpha'] + model_params['gamma'] * indicator) * eps_prev**2
                   + model_params['beta'] * h_prev)

            # Store in return scale (not pct): divide by 10000
            sigma2_oos.loc[date, asset] = h_t / 10000.0
            h_prev = h_t

    return sigma2_oos.astype(float)


# ============================================================
# DCC Estimation (manual implementation)
# ============================================================
def standardize_residuals(returns_df, sigma2_df):
    """Compute standardized residuals: z_t = r_t / sigma_t"""
    sigma = np.sqrt(sigma2_df)
    z = returns_df / sigma
    return z


def estimate_dcc_params(z_df, method='mle'):
    """
    Estimate DCC parameters (a, b) from standardized residuals.

    DCC model (Engle 2002):
      Q_t = (1-a-b) * Q_bar + a * z_{t-1} z'_{t-1} + b * Q_{t-1}
      R_t = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2}

    Parameters:
      a > 0, b > 0, a + b < 1 (stationarity)

    For efficiency, subsample every 3rd observation for optimization,
    then return parameters. Full sample for Q_bar.
    """
    z = z_df.values
    T, k = z.shape

    # Q_bar = unconditional correlation of standardized residuals
    Q_bar = np.corrcoef(z.T)

    # Use subsampled data for optimization (speed)
    step = max(1, T // 1500)  # cap at ~1500 obs for optimization
    z_sub = z[::step]
    T_sub = len(z_sub)

    def neg_loglik(params):
        a, b = params
        if a <= 0 or b <= 0 or a + b >= 0.9999:
            return 1e10

        Q = Q_bar.copy()
        total_ll = 0.0

        for t in range(1, T_sub):
            z_prev = z_sub[t-1]  # shape (k,)
            outer = np.outer(z_prev, z_prev)
            Q = (1 - a - b) * Q_bar + a * outer + b * Q

            # R_t = diag(Q)^{-1/2} Q diag(Q)^{-1/2}
            dQ = np.sqrt(np.diag(Q))
            if np.any(dQ < 1e-10):
                return 1e10
            R = Q / np.outer(dQ, dQ)

            # Clamp correlation to valid range
            R = np.clip(R, -0.9999, 0.9999)
            np.fill_diagonal(R, 1.0)

            # Log-likelihood for 2x2 case (fast closed-form)
            det_R = R[0,0]*R[1,1] - R[0,1]*R[1,0]
            if det_R <= 1e-10:
                return 1e10

            zt = z_sub[t]  # shape (k,)
            # z'R^{-1}z for 2x2
            R_inv_00 = R[1,1] / det_R
            R_inv_11 = R[0,0] / det_R
            R_inv_01 = -R[0,1] / det_R
            zRz = zt[0]**2 * R_inv_00 + zt[1]**2 * R_inv_11 + 2*zt[0]*zt[1]*R_inv_01
            zz = zt[0]**2 + zt[1]**2

            ll_t = -0.5 * (np.log(det_R) + zRz - zz)
            total_ll += ll_t

        return -total_ll  # minimize negative log-likelihood

    # Optimize
    result = minimize(neg_loglik, x0=[0.03, 0.95], method='L-BFGS-B',
                      bounds=[(1e-6, 0.3), (0.5, 0.999)],
                      options={'maxiter': 200})

    a_hat, b_hat = result.x
    return a_hat, b_hat, Q_bar


def dcc_rolling_correlation(z_df, a, b, Q_bar):
    """
    Compute DCC time-varying correlation series.
    Returns DataFrame of correlation R_{12,t} for 2-asset case.
    """
    z = z_df.values
    T, k = z.shape

    Q = Q_bar.copy()
    rho_series = np.zeros(T)
    rho_series[0] = Q_bar[0, 1]  # initial

    for t in range(1, T):
        z_prev = z[t-1:t].T
        Q = (1 - a - b) * Q_bar + a * (z_prev @ z_prev.T) + b * Q

        dQ = np.sqrt(np.diag(Q))
        if np.any(dQ < 1e-10):
            rho_series[t] = rho_series[t-1]
            continue
        R = Q / np.outer(dQ, dQ)
        rho_series[t] = np.clip(R[0, 1], -0.9999, 0.9999)

    return pd.Series(rho_series, index=z_df.index, name='dcc_rho')


# ============================================================
# Portfolio Variance
# ============================================================
def portfolio_variance(sigma2_df, rho_series, weights):
    """
    Compute portfolio variance given individual variances and correlation.
    sigma2_p = w1^2*s1^2 + w2^2*s2^2 + 2*w1*w2*rho*s1*s2
    """
    s1_sq = sigma2_df.iloc[:, 0].values
    s2_sq = sigma2_df.iloc[:, 1].values
    rho = rho_series.values if hasattr(rho_series, 'values') else rho_series

    w1, w2 = weights[0], weights[1]

    port_var = (w1**2 * s1_sq + w2**2 * s2_sq
                + 2 * w1 * w2 * rho * np.sqrt(s1_sq) * np.sqrt(s2_sq))

    # Ensure positive
    port_var = np.maximum(port_var, 1e-10)

    return port_var


# ============================================================
# VaR and ES Computation
# ============================================================
def compute_var_normal(sigma_portfolio, alpha):
    """VaR from Normal distribution: VaR = sigma * z_alpha"""
    z = norm.ppf(alpha)
    return sigma_portfolio * z  # negative


def compute_var_student_t(sigma_portfolio, alpha, df=5):
    """VaR from Student-t: VaR = sigma * t_alpha * sqrt((df-2)/df)"""
    scale = np.sqrt((df - 2) / df) if df > 2 else 1.0
    t_quantile = t_dist.ppf(alpha, df=df)
    return sigma_portfolio * t_quantile / scale  # more conservative than normal


def compute_var_histsim(port_returns, sigma_portfolio, alpha, window=500):
    """
    Filtered Historical Simulation VaR.
    Standardize past returns by their sigma, then re-scale by current sigma.
    """
    T = len(port_returns)
    var_series = np.full(T, np.nan)

    for t in range(window, T):
        # Past window of portfolio returns
        past_r = port_returns[t-window:t]
        past_sigma = sigma_portfolio[t-window:t]

        # Standardize
        valid = past_sigma > 1e-8
        if valid.sum() < 100:
            # Fall back to simple historical
            var_series[t] = np.nanpercentile(past_r, alpha * 100)
            continue

        z_past = past_r[valid] / past_sigma[valid]

        # Re-scale by current sigma
        scaled = z_past * sigma_portfolio[t]
        var_series[t] = np.percentile(scaled, alpha * 100)

    return var_series


def compute_es(port_returns, var_series):
    """Expected Shortfall: average loss conditional on VaR violation."""
    T = len(port_returns)
    es_series = np.full(T, np.nan)

    for t in range(252, T):
        past_r = port_returns[max(0, t-500):t]
        var_t = var_series[t]
        if np.isnan(var_t):
            continue
        violations = past_r[past_r < var_t]
        if len(violations) >= 3:
            es_series[t] = np.mean(violations)
        else:
            es_series[t] = var_t * 1.3  # conservative fallback

    return es_series


# ============================================================
# Backtesting: Kupiec + Christoffersen + Basel + ES
# ============================================================
def kupiec_test(violations, n, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0

    if n1 == 0 or n1 == n:
        return {'stat': 0.0, 'p_value': 1.0, 'violations': n1, 'rate': pi_hat, 'pass': True}

    lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
               - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
    p_val = 1 - chi2.cdf(lr, df=1)

    return {
        'stat': float(lr),
        'p_value': float(p_val),
        'violations': n1,
        'rate': float(pi_hat),
        'expected_rate': float(alpha),
        'pass': p_val > 0.05
    }


def christoffersen_test(violations):
    """Christoffersen (1998) independence test."""
    v = violations.astype(int)
    n = len(v)

    t00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    t01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    t10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    t11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

    pi_all = (t01 + t11) / (n - 1) if n > 1 else 0
    pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
    pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0

    try:
        if (pi01 > 0 and pi01 < 1 and pi11 > 0 and pi11 < 1
            and pi_all > 0 and pi_all < 1):
            lr_ind = (-2 * ((t00 + t10) * np.log(1 - pi_all) + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11)))
            p_val = 1 - chi2.cdf(lr_ind, df=1)
        else:
            lr_ind, p_val = 0.0, 1.0
    except (ValueError, RuntimeWarning):
        lr_ind, p_val = 0.0, 1.0

    return {
        'stat': float(lr_ind),
        'p_value': float(p_val),
        'clustering': {'t00': int(t00), 't01': int(t01), 't10': int(t10), 't11': int(t11)},
        'pass': p_val > 0.05
    }


def basel_traffic_light(violations, n, alpha):
    """Basel traffic light test for 250-day windows."""
    n1 = int(violations.sum())
    expected = n * alpha

    # Basel III thresholds (for 250-day window at 1%)
    if alpha == 0.01:
        if n1 <= 4:
            zone = 'green'
        elif n1 <= 9:
            zone = 'yellow'
        else:
            zone = 'red'
    elif alpha == 0.05:
        # Scale thresholds for 5%
        if n1 <= int(n * 0.065):
            zone = 'green'
        elif n1 <= int(n * 0.085):
            zone = 'yellow'
        else:
            zone = 'red'
    else:
        # Generic
        ratio = n1 / expected if expected > 0 else 0
        if ratio <= 1.6:
            zone = 'green'
        elif ratio <= 2.5:
            zone = 'yellow'
        else:
            zone = 'red'

    return {
        'zone': zone,
        'violations': n1,
        'expected': float(expected),
        'pass': zone in ('green', 'yellow')
    }


def trinity_test(returns, var_series, alpha, n_days=None):
    """Full VaR Trinity: Kupiec + Christoffersen + Basel."""
    valid = ~np.isnan(var_series)
    r = returns[valid]
    v = var_series[valid]

    if n_days is not None:
        r = r[-n_days:]
        v = v[-n_days:]

    violations = (r < v).astype(int)
    n = len(r)

    kupiec = kupiec_test(violations, n, alpha)
    cc = christoffersen_test(violations)
    basel = basel_traffic_light(violations, n, alpha)

    trinity_pass = kupiec['pass'] and cc['pass'] and (basel['zone'] in ('green', 'yellow'))

    return {
        'kupiec': kupiec,
        'christoffersen': cc,
        'basel': basel,
        'trinity_pass': trinity_pass,
        'n_days': n,
        'violation_rate': float(kupiec['rate']),
        'alpha': float(alpha),
    }


def acerbi_szekely_es_test(returns, var_series, es_series, alpha):
    """
    Acerbi & Szekely (2014) ES backtest.
    Z1 = (1/(n*alpha)) * sum_t [r_t * I(r_t < VaR_t)] / ES_t + 1
    Under H0: E[Z1] = 0. Z1 < 0 → ES underestimates risk.
    """
    valid = (~np.isnan(var_series)) & (~np.isnan(es_series)) & (es_series < -1e-10)
    r = returns[valid]
    v = var_series[valid]
    es = es_series[valid]

    n = len(r)
    if n < 100:
        return {'z1': np.nan, 'z2': np.nan, 'pass': True, 'note': 'insufficient data'}

    violations = r < v
    n_viol = violations.sum()

    if n_viol < 3:
        return {'z1': np.nan, 'z2': np.nan, 'pass': True, 'note': 'too few violations'}

    # Z1 statistic
    z1 = (1.0 / (n * alpha)) * np.sum(r[violations] / es[violations]) + 1.0

    # Z2 statistic (simpler version)
    z2 = np.mean(r[violations]) / np.mean(es[violations]) - 1.0

    # Bootstrap p-value for Z1
    np.random.seed(42)
    n_boot = 5000
    z1_boot = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        r_b = r[idx]
        v_b = v[idx]
        es_b = es[idx]
        viol_b = r_b < v_b
        if viol_b.sum() > 0:
            z1_boot[b] = (1.0 / (n * alpha)) * np.sum(r_b[viol_b] / es_b[viol_b]) + 1.0

    p_val = np.mean(z1_boot <= z1)  # one-sided: reject if Z1 too negative

    return {
        'z1': float(z1),
        'z2': float(z2),
        'p_value': float(p_val),
        'n_violations': int(n_viol),
        'pass': p_val > 0.05,
    }


# ============================================================
# DM Test for VaR (using QLIKE on portfolio variance)
# ============================================================
def dm_test_var(loss1, loss2, h=1):
    """DM test on VaR losses. Harvey (2016): |t| > 3.0."""
    from volpred.stats.model_evaluation import dm_test
    return dm_test(loss1, loss2, h=h)


# ============================================================
# Descriptive Statistics
# ============================================================
def descriptive_stats(returns_df):
    """Compute descriptive statistics for each asset."""
    stats_dict = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        stats_dict[col] = {
            'n': len(r),
            'mean_ann': float(r.mean() * 252),
            'std_ann': float(r.std() * np.sqrt(252)),
            'skewness': float(r.skew()),
            'kurtosis': float(r.kurtosis()),
            'min': float(r.min()),
            'max': float(r.max()),
        }

    # Portfolio
    port_r = (returns_df * WEIGHTS).sum(axis=1)
    stats_dict['Portfolio'] = {
        'n': len(port_r),
        'mean_ann': float(port_r.mean() * 252),
        'std_ann': float(port_r.std() * np.sqrt(252)),
        'skewness': float(port_r.skew()),
        'kurtosis': float(port_r.kurtosis()),
        'min': float(port_r.min()),
        'max': float(port_r.max()),
    }

    # Correlation
    corr = returns_df.corr()
    stats_dict['correlation'] = float(corr.iloc[0, 1])

    return stats_dict


# ============================================================
# Main Experiment
# ============================================================
def main():
    t0 = time.time()
    results = {
        'experiment_id': 'K891',
        'title': 'DCC-GARCH Portfolio VaR: Does Dynamic Correlation Help?',
        'data_source': 'yfinance',
        'assets': ASSETS,
        'weights': WEIGHTS.tolist(),
        'oos_start': OOS_START,
        'refit_every': REFIT_EVERY,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 1: Load data ──
    print("=" * 70)
    print("K891: DCC-GARCH Portfolio VaR")
    print("=" * 70)

    close, returns = load_data()

    # ── Step 2: Descriptive statistics ──
    print("\n--- Descriptive Statistics ---")
    desc = descriptive_stats(returns)
    for k, v in desc.items():
        if isinstance(v, dict):
            print(f"  {k}: mean={v.get('mean_ann', 'N/A'):.4f}, "
                  f"std={v.get('std_ann', 'N/A'):.4f}, "
                  f"skew={v.get('skewness', 'N/A'):.3f}, "
                  f"kurt={v.get('kurtosis', 'N/A'):.3f}")
        else:
            print(f"  {k}: {v:.4f}")
    results['descriptive_stats'] = desc

    # ── Step 3: GJR-GARCH OOS forecasts for each asset ──
    print("\n--- GJR-GARCH OOS Forecasting ---")
    sigma2_oos = gjr_forecast_oos(returns, OOS_START, refit_every=REFIT_EVERY)
    print(f"  OOS period: {sigma2_oos.index[0].strftime('%Y-%m-%d')} to "
          f"{sigma2_oos.index[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS days: {len(sigma2_oos)}")

    # ── Step 4: Compute standardized residuals for DCC ──
    print("\n--- DCC Estimation ---")

    # Use full sample up to OOS start for initial DCC estimation
    # Then update recursively
    oos_returns = returns.loc[sigma2_oos.index]
    z_oos = standardize_residuals(oos_returns, sigma2_oos)

    # For DCC parameter estimation, use in-sample data
    is_end_idx = returns.index.get_loc(sigma2_oos.index[0])
    is_returns = returns.iloc[:is_end_idx]

    # Fit GJR on IS to get IS standardized residuals
    print("  Fitting IS GJR models for DCC parameter estimation...")
    from arch import arch_model

    is_z = pd.DataFrame(index=is_returns.index, columns=ASSETS, dtype=float)
    for asset in ASSETS:
        r_pct = is_returns[asset] * 100
        am = arch_model(r_pct, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
        res = am.fit(disp='off', show_warning=False)
        cond_vol = res.conditional_volatility
        resid = res.resid
        is_z[asset] = (resid / cond_vol).values

    is_z = is_z.dropna()

    # Estimate DCC parameters from IS standardized residuals
    a_dcc, b_dcc, Q_bar = estimate_dcc_params(is_z)
    persistence = a_dcc + b_dcc
    print(f"  DCC parameters: a={a_dcc:.4f}, b={b_dcc:.4f}, persistence={persistence:.4f}")
    print(f"  Q_bar[0,1] (unconditional correlation): {Q_bar[0,1]:.4f}")

    results['dcc_params'] = {
        'a': float(a_dcc), 'b': float(b_dcc),
        'persistence': float(persistence),
        'q_bar_rho': float(Q_bar[0, 1]),
    }

    # ── Step 5: Compute DCC correlation series (OOS, rolling) ──
    # We need to update DCC through OOS with recursive approach
    # Use IS z for burn-in, then OOS z for actual correlation series
    print("  Computing DCC time-varying correlation (OOS)...")

    # Concatenate IS and OOS standardized residuals
    all_z = pd.concat([is_z, z_oos], axis=0)
    all_z = all_z.dropna()

    # Compute DCC rho for the full series
    rho_full = dcc_rolling_correlation(all_z, a_dcc, b_dcc, Q_bar)

    # Extract OOS portion
    rho_oos = rho_full.loc[sigma2_oos.index]

    # Constant correlation (from IS)
    const_rho = float(is_returns[ASSETS[0]].corr(is_returns[ASSETS[1]]))
    print(f"  Constant correlation (IS): {const_rho:.4f}")
    print(f"  DCC correlation range (OOS): [{rho_oos.min():.4f}, {rho_oos.max():.4f}]")
    print(f"  DCC correlation mean (OOS): {rho_oos.mean():.4f}")

    results['correlation_stats'] = {
        'constant_rho_IS': float(const_rho),
        'dcc_rho_mean': float(rho_oos.mean()),
        'dcc_rho_std': float(rho_oos.std()),
        'dcc_rho_min': float(rho_oos.min()),
        'dcc_rho_max': float(rho_oos.max()),
    }

    # ── Step 6: Portfolio returns and variance forecasts ──
    print("\n--- Portfolio Variance Forecasts ---")
    port_returns_oos = (oos_returns * WEIGHTS).sum(axis=1).values

    # M1: Independent GJR + constant corr
    port_var_const = portfolio_variance(sigma2_oos, const_rho * np.ones(len(sigma2_oos)), WEIGHTS)
    port_sigma_const = np.sqrt(port_var_const)

    # M2-M4: DCC-based portfolio variance
    port_var_dcc = portfolio_variance(sigma2_oos, rho_oos, WEIGHTS)
    port_sigma_dcc = np.sqrt(port_var_dcc)

    print(f"  Avg port sigma (constant corr): {np.mean(port_sigma_const):.6f}")
    print(f"  Avg port sigma (DCC): {np.mean(port_sigma_dcc):.6f}")

    # ── Step 7: Compute VaR for all 5 models ──
    print("\n--- VaR Computation ---")

    # Estimate Student-t df from portfolio standardized residuals
    port_z = port_returns_oos / port_sigma_dcc
    port_z_clean = port_z[np.isfinite(port_z)]

    # MLE for Student-t df
    def neg_ll_t(df_param):
        if df_param <= 2.01:
            return 1e10
        return -np.sum(t_dist.logpdf(port_z_clean, df=df_param))

    from scipy.optimize import minimize_scalar
    opt_df = minimize_scalar(neg_ll_t, bounds=(2.5, 30), method='bounded')
    estimated_df = opt_df.x
    print(f"  Estimated Student-t df: {estimated_df:.2f}")
    results['student_t_df'] = float(estimated_df)

    models = {}

    for alpha in ALPHA_LEVELS:
        alpha_key = f'{int(alpha*100)}pct'

        # M1: Constant corr + Normal
        var_m1 = compute_var_normal(port_sigma_const, alpha)

        # M2: DCC + Normal
        var_m2 = compute_var_normal(port_sigma_dcc, alpha)

        # M3: DCC + Student-t
        var_m3 = compute_var_student_t(port_sigma_dcc, alpha, df=estimated_df)

        # M4: DCC + HistSim (FHS)
        var_m4 = compute_var_histsim(port_returns_oos, port_sigma_dcc, alpha, HIST_SIM_WINDOW)

        # M5: Constant corr + HistSim (FHS)
        var_m5 = compute_var_histsim(port_returns_oos, port_sigma_const, alpha, HIST_SIM_WINDOW)

        models[alpha_key] = {
            'M1_ConstCorr_Normal': var_m1,
            'M2_DCC_Normal': var_m2,
            'M3_DCC_StudentT': var_m3,
            'M4_DCC_HistSim': var_m4,
            'M5_ConstCorr_HistSim': var_m5,
        }

    # ── Step 8: VaR Trinity Test ──
    print("\n--- VaR Trinity Test Results ---")
    var_results = {}

    for alpha in ALPHA_LEVELS:
        alpha_key = f'{int(alpha*100)}pct'
        print(f"\n  === {alpha_key} VaR ===")
        var_results[alpha_key] = {}

        for model_name, var_series in models[alpha_key].items():
            trinity = trinity_test(port_returns_oos, var_series, alpha)

            # Compute ES and ES test
            es_series = compute_es(port_returns_oos, var_series)
            es_test = acerbi_szekely_es_test(port_returns_oos, var_series, es_series, alpha)

            # Average VaR width (capital efficiency)
            valid_var = var_series[~np.isnan(var_series)]
            avg_var = float(np.mean(np.abs(valid_var))) if len(valid_var) > 0 else np.nan

            var_results[alpha_key][model_name] = {
                'trinity': trinity,
                'es_test': es_test,
                'avg_var_width': avg_var,
                'avg_var_pct': float(avg_var * 100) if not np.isnan(avg_var) else np.nan,
            }

            pass_str = "PASS" if trinity['trinity_pass'] else "FAIL"
            es_pass = "PASS" if es_test.get('pass', False) else "FAIL"
            print(f"    {model_name:30s}: Trinity={pass_str}  "
                  f"viol={trinity['violation_rate']:.4f} "
                  f"(exp={alpha:.3f})  "
                  f"Kupiec={'P' if trinity['kupiec']['pass'] else 'F'}  "
                  f"CC={'P' if trinity['christoffersen']['pass'] else 'F'}  "
                  f"Basel={trinity['basel']['zone']:6s}  "
                  f"ES={es_pass}  "
                  f"AvgVaR={avg_var:.4f}")

    results['var_backtest'] = {}
    for alpha_key, model_dict in var_results.items():
        results['var_backtest'][alpha_key] = {}
        for model_name, res_dict in model_dict.items():
            # Convert numpy types for JSON serialization
            results['var_backtest'][alpha_key][model_name] = {
                'trinity_pass': res_dict['trinity']['trinity_pass'],
                'violation_rate': res_dict['trinity']['violation_rate'],
                'kupiec_p': res_dict['trinity']['kupiec']['p_value'],
                'kupiec_pass': res_dict['trinity']['kupiec']['pass'],
                'cc_p': res_dict['trinity']['christoffersen']['p_value'],
                'cc_pass': res_dict['trinity']['christoffersen']['pass'],
                'basel_zone': res_dict['trinity']['basel']['zone'],
                'basel_pass': res_dict['trinity']['basel']['pass'],
                'es_z1': res_dict['es_test'].get('z1', None),
                'es_pass': res_dict['es_test'].get('pass', None),
                'n_days': res_dict['trinity']['n_days'],
                'avg_var_width': res_dict['avg_var_width'],
                'avg_var_pct': res_dict['avg_var_pct'],
            }

    # ── Step 9: DM Test (pairwise on QLIKE loss of portfolio variance) ──
    print("\n--- DM Tests (QLIKE on portfolio variance) ---")

    # Realized portfolio variance proxy: r_p^2
    r2_port = port_returns_oos ** 2

    from volpred.stats.model_evaluation import qlike_pointwise, dm_test, qlike

    # Compute QLIKE for each model's portfolio variance forecast
    model_port_vars = {
        'M1_ConstCorr': port_var_const,
        'M2_DCC': port_var_dcc,
    }

    qlike_scores = {}
    for name, pvar in model_port_vars.items():
        ql = qlike(r2_port, pvar)
        qlike_scores[name] = ql
        print(f"  QLIKE({name}): {ql:.6f}")

    results['qlike_portfolio_var'] = {k: float(v) for k, v in qlike_scores.items()}

    # DM test: DCC vs Constant
    loss_const = qlike_pointwise(r2_port, port_var_const)
    loss_dcc = qlike_pointwise(r2_port, port_var_dcc)

    dm_stat, dm_p = dm_test(loss_const, loss_dcc)
    print(f"\n  DM test (ConstCorr vs DCC on QLIKE): t={dm_stat:.3f}, p={dm_p:.4f}")
    print(f"  {'DCC better' if dm_stat > 0 else 'Constant better'} "
          f"{'(SIGNIFICANT |t|>3.0)' if abs(dm_stat) > 3.0 else '(not significant)'}")

    results['dm_test_qlike'] = {
        'stat': float(dm_stat),
        'p_value': float(dm_p),
        'significant_harvey': abs(dm_stat) > 3.0,
        'better_model': 'DCC' if dm_stat > 0 else 'Constant',
    }

    # DM test on VaR violations (tick loss function)
    print("\n--- DM Tests (VaR Tick Loss) ---")
    dm_results_var = {}

    for alpha in ALPHA_LEVELS:
        alpha_key = f'{int(alpha*100)}pct'
        dm_results_var[alpha_key] = {}

        model_names = list(models[alpha_key].keys())

        for i in range(len(model_names)):
            for j in range(i+1, len(model_names)):
                m1_name = model_names[i]
                m2_name = model_names[j]

                var1 = models[alpha_key][m1_name]
                var2 = models[alpha_key][m2_name]

                # Tick loss: L(r, VaR) = (alpha - I(r < VaR)) * (r - VaR)
                valid = (~np.isnan(var1)) & (~np.isnan(var2))
                r_v = port_returns_oos[valid]
                v1 = var1[valid]
                v2 = var2[valid]

                tick1 = (alpha - (r_v < v1).astype(float)) * (r_v - v1)
                tick2 = (alpha - (r_v < v2).astype(float)) * (r_v - v2)

                t_stat, p_val = dm_test(tick1, tick2)

                pair_key = f'{m1_name}_vs_{m2_name}'
                dm_results_var[alpha_key][pair_key] = {
                    'stat': float(t_stat),
                    'p_value': float(p_val),
                    'significant_harvey': abs(t_stat) > 3.0,
                    'better': m1_name if t_stat > 0 else m2_name,
                }

                if abs(t_stat) > 3.0:
                    better = m1_name if t_stat > 0 else m2_name
                    print(f"  {alpha_key} {pair_key}: t={t_stat:.3f} *** {better} wins")

    results['dm_test_var_tick'] = dm_results_var

    # ── Step 10: Capital Efficiency Comparison ──
    print("\n--- Capital Efficiency (Average VaR Width) ---")
    cap_eff = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f'{int(alpha*100)}pct'
        cap_eff[alpha_key] = {}
        for model_name, var_series in models[alpha_key].items():
            valid = ~np.isnan(var_series)
            avg_width = float(np.mean(np.abs(var_series[valid]))) * 100 if valid.sum() > 0 else np.nan
            cap_eff[alpha_key][model_name] = avg_width
            print(f"  {alpha_key} {model_name:30s}: {avg_width:.4f}%")

    results['capital_efficiency'] = cap_eff

    # ── Step 11: DCC Correlation Dynamics ──
    print("\n--- DCC Correlation Dynamics ---")

    # Annual breakdown
    rho_annual = {}
    for year in range(2019, 2027):
        mask = rho_oos.index.year == year
        if mask.sum() > 0:
            rho_yr = rho_oos[mask]
            rho_annual[str(year)] = {
                'mean': float(rho_yr.mean()),
                'std': float(rho_yr.std()),
                'min': float(rho_yr.min()),
                'max': float(rho_yr.max()),
            }
            print(f"  {year}: mean={rho_yr.mean():.4f}, "
                  f"std={rho_yr.std():.4f}, "
                  f"range=[{rho_yr.min():.4f}, {rho_yr.max():.4f}]")

    results['dcc_rho_annual'] = rho_annual

    # ── Step 12: Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY: Does DCC Improve Portfolio VaR?")
    print("=" * 70)

    summary_lines = []

    # Count trinity passes
    for alpha in ALPHA_LEVELS:
        alpha_key = f'{int(alpha*100)}pct'
        print(f"\n  {alpha_key} VaR Trinity PASS/FAIL:")
        for model_name in models[alpha_key].keys():
            res = results['var_backtest'][alpha_key][model_name]
            status = "PASS" if res['trinity_pass'] else "FAIL"
            print(f"    {model_name:30s}: {status} (viol={res['violation_rate']:.4f})")
            summary_lines.append(f"{alpha_key} {model_name}: Trinity={status}")

    # DCC vs Constant headline
    dm_ql = results['dm_test_qlike']
    if dm_ql['significant_harvey']:
        print(f"\n  DCC vs Constant QLIKE: {dm_ql['better_model']} is SIGNIFICANTLY better "
              f"(DM t={dm_ql['stat']:.3f})")
    else:
        print(f"\n  DCC vs Constant QLIKE: NOT significantly different "
              f"(DM t={dm_ql['stat']:.3f})")

    results['summary'] = {
        'dcc_improves_qlike': dm_ql['significant_harvey'] and dm_ql['better_model'] == 'DCC',
        'dcc_qlike_dm_t': dm_ql['stat'],
        'conclusion': '',
    }

    # Determine conclusion
    dcc_trinity_1pct = results['var_backtest']['1pct']['M2_DCC_Normal']['trinity_pass']
    const_trinity_1pct = results['var_backtest']['1pct']['M1_ConstCorr_Normal']['trinity_pass']
    dcc_hs_trinity_1pct = results['var_backtest']['1pct']['M4_DCC_HistSim']['trinity_pass']
    const_hs_trinity_1pct = results['var_backtest']['1pct']['M5_ConstCorr_HistSim']['trinity_pass']

    if dcc_hs_trinity_1pct and not const_hs_trinity_1pct:
        conclusion = "DCC+HistSim passes Trinity where Constant+HistSim fails — DCC adds value for VaR"
    elif not dcc_hs_trinity_1pct and const_hs_trinity_1pct:
        conclusion = "Constant+HistSim passes Trinity where DCC+HistSim fails — DCC hurts VaR"
    elif dcc_hs_trinity_1pct == const_hs_trinity_1pct:
        if dm_ql['significant_harvey']:
            conclusion = f"Same Trinity outcome but DCC is significantly better on QLIKE (t={dm_ql['stat']:.2f})"
        else:
            conclusion = "DCC does NOT significantly improve portfolio VaR — constant correlation sufficient for 2-asset"
    else:
        conclusion = "Mixed results"

    results['summary']['conclusion'] = conclusion
    print(f"\n  CONCLUSION: {conclusion}")

    # ── Save ──
    elapsed = time.time() - t0
    results['elapsed_seconds'] = float(elapsed)
    print(f"\n  Elapsed: {elapsed:.1f}s")

    # Convert any remaining numpy types
    def convert_numpy(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_numpy(i) for i in obj]
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    results = convert_numpy(results)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    return results


if __name__ == '__main__':
    main()
