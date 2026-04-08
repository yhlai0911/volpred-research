#!/usr/bin/env python3
"""
K830: BTC Skewed-t VaR — Fixing the K829 Positive-Skew Paradox
================================================================
[提出: 用戶, 執行: Claude]

K829 finding: BTC 1% VaR paradox — Normal PASS (3/731) but Student-t and HistSim
FAIL due to over-conservatism (1/731 violations each, Kupiec p=0.003).

Root cause: BTC has positive skewness (0.619), making the left tail naturally
thinner than symmetric distributions assume. Student-t adds symmetric heavy-tail
correction → over-protects the left tail.

Solution: Skewed Student-t (Hansen 1994 / Fernandez-Steel 1998) allows
asymmetric tail thickness. For positive-skew BTC, it should correctly model:
  - Thinner left tail (fewer extreme losses)
  - Thicker right tail (more extreme gains)

Methods compared:
  1. Normal (K829 baseline — PASS at 1%)
  2. Student-t (K829 — FAIL, 1/731 too conservative)
  3. HistSim (K829 — FAIL, 1/731 too conservative)
  4. **Skewed-t** (NEW: Hansen 1994 / Fernandez-Steel 1998)
  5. **Asymmetric HistSim** (NEW: only negative residuals for left-tail quantile)

OOS: 2023-01-01 ~ 2024-12-31
Refit: every 63 trading days
VaR levels: 1%, 5%
Evaluation: Kupiec + Christoffersen + Basel + Trinity + Pinball loss

Error Log rules applied:
  - Student-t: scale=sqrt((df-2)/df), per-refit df (K824v2 fix)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Skewed-t: Hansen (1994) density has conditional scale term
  - Per-refit df AND skew parameter (K825 lesson)

References:
  - K829: BTC Normal PASS, Student-t/HistSim FAIL (over-conservative)
  - K802: GJR+Skewed-t for SPY (Fernandez-Steel 1998 ppf)
  - K824v2: Student-t scale=sqrt((df-2)/df) fix
  - Hansen (1994) Int. Econ. Rev. — skewed-t distribution
  - Fernandez & Steel (1998) JASA 93 — skewed distributions
  - Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)

Data source: yfinance (BTC-USD)
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2, skew, kurtosis

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k830_btc_skewed_var_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]


# ==============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ==============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ==============================================================
# B. GJR-GARCH model fitting
# ==============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


# ==============================================================
# C. One-step-ahead forecast + standardized residuals
# ==============================================================

def gjr_one_step_forecast(returns, params):
    """σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    """z_t = r_t / σ_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ==============================================================
# D. Distribution parameter estimation
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """MLE for Student-t df from unit-variance standardized residuals.
    Uses scale = sqrt((df-2)/df) so fitted distribution has unit variance.
    (K824v2 Bug 1 fix)"""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0

    def neg_loglik(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        scale = np.sqrt((df - 2.0) / df)
        ll = np.sum(t_dist.logpdf(z, df=df, loc=0.0, scale=scale))
        return -ll if np.isfinite(ll) else 1e10

    best_nll = 1e10
    best_df = 5.0
    for df_init in [3.0, 5.0, 8.0, 15.0]:
        res = minimize(neg_loglik, x0=[np.log(df_init)],
                       method='L-BFGS-B',
                       bounds=[(np.log(df_min), np.log(df_max))],
                       options={'maxiter': 500})
        if res.fun < best_nll:
            best_nll = res.fun
            best_df = float(np.exp(res.x[0]))

    return float(np.clip(best_df, df_min, df_max))


def estimate_skewt_params(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate Fernandez-Steel (1998) skewed-t parameters (df, xi) via MLE.

    PDF: f(z; df, xi) = (2/(xi + 1/xi)) * g(z*xi; df)  if z < 0
                                           g(z/xi; df)  if z >= 0
    where g(.; df) is the symmetric Student-t PDF.

    xi > 0:
      xi < 1 → left-skewed (heavier left tail, typical for equities)
      xi > 1 → right-skewed (heavier right tail, typical for BTC)
      xi = 1 → symmetric Student-t

    Returns dict with 'df' and 'xi'.
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return {'df': 5.0, 'xi': 1.0}

    def skewt_logpdf(x, df, xi):
        """Log PDF of Fernandez-Steel skewed-t."""
        c = 2.0 / (xi + 1.0 / xi)
        y = np.where(x >= 0, x / xi, x * xi)
        return np.log(c) + t_dist.logpdf(y, df=df)

    def neg_loglik(params):
        log_df, log_xi = params
        df = np.exp(log_df)
        xi = np.exp(log_xi)
        if df < df_min or df > df_max:
            return 1e10
        if xi < 0.2 or xi > 5.0:
            return 1e10
        ll = np.sum(skewt_logpdf(z, df, xi))
        return -ll if np.isfinite(ll) else 1e10

    best_nll, best_df, best_xi = 1e10, 5.0, 1.0
    for df_init in [3.0, 5.0, 8.0]:
        for xi_init in [0.7, 1.0, 1.3]:
            res = minimize(neg_loglik,
                           x0=[np.log(df_init), np.log(xi_init)],
                           method='L-BFGS-B',
                           bounds=[(np.log(df_min), np.log(df_max)),
                                   (np.log(0.2), np.log(5.0))],
                           options={'maxiter': 1000})
            if res.fun < best_nll:
                best_nll = res.fun
                best_df = float(np.exp(res.x[0]))
                best_xi = float(np.exp(res.x[1]))

    return {'df': float(np.clip(best_df, df_min, df_max)),
            'xi': float(np.clip(best_xi, 0.2, 5.0))}


def skewt_ppf(p, df, xi):
    """
    Quantile function (PPF) of Fernandez-Steel (1998) skewed-t.

    CDF derivation:
      For z < 0:  F(z) = (2/(xi+1/xi)) * (1/xi) * T(xi*z; df)
      For z >= 0: F(z) = 1/(1+xi²) + (2*xi/(xi+1/xi)) * (T(z/xi; df) - 0.5)

    CDF at z=0: p0 = 1/(1+xi²)

    For BTC with xi>1 (right-skewed):
      p0 = 1/(1+xi²) < 0.5 → more mass on right side
      Left quantiles are closer to 0 (thinner left tail) → less conservative VaR
    """
    c = 2.0 / (xi + 1.0 / xi)
    p0 = 1.0 / (1.0 + xi ** 2)

    if p <= p0:
        # Left branch: z < 0
        inner = p * xi / c
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = float(t_dist.ppf(inner, df=df)) / xi
    else:
        # Right branch: z >= 0
        inner = 0.5 + (p - p0) / (xi * c)
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = xi * float(t_dist.ppf(inner, df=df))

    return z


# ==============================================================
# E. VaR Backtest: Kupiec + Christoffersen + Basel + Pinball
# ==============================================================

def pinball_loss(returns, var_series, alpha):
    """Pinball (tick/quantile) loss for VaR evaluation.
    Lower is better. Measures calibration quality."""
    r = np.asarray(returns, dtype=np.float64)
    v = np.asarray(var_series, dtype=np.float64)
    diff = r - v
    loss = np.where(diff < 0, (alpha - 1) * diff, alpha * diff)
    return float(np.mean(loss))


def basel_traffic_light_250(violations_array, n_lookback=250, alpha_var=0.01):
    """Standard Basel II/III traffic light."""
    v = np.asarray(violations_array, dtype=int)
    n = len(v)
    window = min(n, n_lookback)
    v_window = v[-window:]
    n_viol = int(v_window.sum())

    alpha_scale = alpha_var / 0.01
    if window >= 250:
        green_max = int(np.floor(4 * alpha_scale))
        yellow_max = int(np.floor(9 * alpha_scale))
    else:
        green_max = int(np.floor(window * 4.0 * alpha_scale / 250.0))
        yellow_max = int(np.floor(window * 9.0 * alpha_scale / 250.0))

    green_max = max(green_max, 0)
    yellow_max = max(yellow_max, max(green_max + 1, 1))

    if n_viol <= green_max:
        color = 'green'
    elif n_viol <= yellow_max:
        color = 'yellow'
    else:
        color = 'red'

    return color, n_viol, window


def var_backtest(returns, var_series, alpha_var=0.01):
    """Kupiec (1995) + Christoffersen (1998) + Basel traffic light + Pinball."""
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen independence
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                           + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    traffic, n_viol_window, window_size = basel_traffic_light_250(violations, alpha_var=alpha_var)

    # Pinball loss
    pb = pinball_loss(r, var, alpha_var)

    return {
        'violation_rate': round(float(pi_hat), 6),
        'expected_rate': float(alpha_var),
        'n_violations': n1,
        'n_total': n,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': n_viol_window,
        'basel_window_size': window_size,
        'pinball_loss': round(pb, 8),
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# F. Main experiment
# ==============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K830: BTC Skewed-t VaR — Fixing the K829 Positive-Skew Paradox")
    print("  Asset: BTC-USD")
    print("  Methods: Normal, Student-t, HistSim, Skewed-t, Asymmetric HistSim")
    print("  OOS: 2023-01-01 ~ 2024-12-31")
    print("  Refit: every 63 trading days")
    print("=" * 70)

    # 1. Download BTC data
    print("\n[1] Downloading BTC-USD...")
    df = yf.download('BTC-USD', start='2015-01-01', end='2026-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])

    prices = df['Close']
    returns = prices.pct_change().dropna()

    # Filter extreme returns (>50% daily = data error)
    extreme = returns.abs() > 0.50
    if extreme.any():
        n_extreme = extreme.sum()
        print(f"  [!] Removed {n_extreme} extreme return(s) (|r| > 50%)")
        returns = returns[~extreme]

    print(f"  Total returns: {len(returns)} ({returns.index[0].date()} ~ {returns.index[-1].date()})")

    # 2. Identify OOS period
    oos_mask = (returns.index >= OOS_START) & (returns.index <= OOS_END)
    oos_returns = returns[oos_mask]
    n_oos = len(oos_returns)
    print(f"  OOS: {n_oos} days ({oos_returns.index[0].date()} ~ {oos_returns.index[-1].date()})")

    # 3. Descriptive stats
    r_oos = oos_returns.values
    full_r = returns.values
    stats_oos = {
        'mean': float(np.mean(r_oos)),
        'std': float(np.std(r_oos)),
        'skewness': float(skew(r_oos)),
        'kurtosis': float(kurtosis(r_oos, fisher=True)),
        'min': float(np.min(r_oos)),
        'max': float(np.max(r_oos)),
    }
    stats_full = {
        'mean': float(np.mean(full_r)),
        'std': float(np.std(full_r)),
        'skewness': float(skew(full_r)),
        'kurtosis': float(kurtosis(full_r, fisher=True)),
    }
    print(f"  OOS stats: mean={stats_oos['mean']:.6f}, std={stats_oos['std']:.4f}, "
          f"skew={stats_oos['skewness']:.3f}, kurt={stats_oos['kurtosis']:.2f}")
    print(f"  Full stats: mean={stats_full['mean']:.6f}, std={stats_full['std']:.4f}, "
          f"skew={stats_full['skewness']:.3f}, kurt={stats_full['kurtosis']:.2f}")

    # 4. Expanding window with refit
    all_returns = returns.values
    all_dates = returns.index
    oos_start_idx = np.searchsorted(all_dates, pd.Timestamp(OOS_START))
    oos_end_idx = np.searchsorted(all_dates, pd.Timestamp(OOS_END), side='right')

    # Storage for VaR forecasts: 5 methods
    methods = ['normal', 'student_t', 'histsim', 'skewed_t', 'asym_histsim']
    var_forecasts = {alpha: {m: [] for m in methods} for alpha in ALPHA_LEVELS}

    current_params = None
    current_z = None
    current_df = None
    current_skewt = None  # {'df': ..., 'xi': ...}
    last_refit = -999
    n_refits = 0
    refit_params_log = []

    print(f"\n[2] Running expanding window OOS forecast...")
    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        # Refit?
        if day_idx - last_refit >= REFIT_EVERY or current_params is None:
            train_r = all_returns[:i]  # data up to (but not including) day i
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                current_z = compute_standardized_residuals(train_r, params)
                current_df = estimate_t_df(current_z)
                current_skewt = estimate_skewt_params(current_z)
                n_refits += 1
                last_refit = day_idx

                refit_params_log.append({
                    'refit_num': n_refits,
                    'day_idx': day_idx,
                    'date': str(all_dates[i].date()),
                    'n_train': len(train_r),
                    'gjr_persistence': round(params['persistence'], 4),
                    'student_df': round(current_df, 2),
                    'skewt_df': round(current_skewt['df'], 2),
                    'skewt_xi': round(current_skewt['xi'], 4),
                    'residual_skewness': round(float(skew(current_z)), 4),
                    'residual_kurtosis': round(float(kurtosis(current_z, fisher=True)), 2),
                })

                print(f"  Refit {n_refits}: day={day_idx}, date={all_dates[i].date()}, "
                      f"n_train={len(train_r)}, persist={params['persistence']:.3f}, "
                      f"df_t={current_df:.1f}, df_skewt={current_skewt['df']:.1f}, "
                      f"xi={current_skewt['xi']:.3f}, z_skew={skew(current_z):.3f}")

        if current_params is None:
            for alpha in ALPHA_LEVELS:
                for m in methods:
                    var_forecasts[alpha][m].append(np.nan)
            continue

        # One-step forecast: σ²_{t+1|t}
        train_r = all_returns[:i]
        sigma2_f = gjr_one_step_forecast(train_r, current_params)
        sigma_f = np.sqrt(sigma2_f)

        # Compute VaR for each alpha and method
        for alpha in ALPHA_LEVELS:
            # M1: Normal VaR
            z_normal = norm.ppf(alpha)
            var_normal = sigma_f * z_normal
            var_forecasts[alpha]['normal'].append(float(var_normal))

            # M2: Student-t VaR (with proper scale correction)
            scale_t = np.sqrt((current_df - 2.0) / current_df) if current_df > 2 else 1.0
            z_t = t_dist.ppf(alpha, df=current_df, loc=0.0, scale=scale_t)
            var_student = sigma_f * z_t
            var_forecasts[alpha]['student_t'].append(float(var_student))

            # M3: HistSim VaR (empirical quantile of all standardized residuals)
            z_hist = np.percentile(current_z, alpha * 100)
            var_histsim = sigma_f * z_hist
            var_forecasts[alpha]['histsim'].append(float(var_histsim))

            # M4: Skewed-t VaR (Fernandez-Steel 1998)
            z_skewt = skewt_ppf(alpha, df=current_skewt['df'], xi=current_skewt['xi'])
            var_skewt = sigma_f * z_skewt
            var_forecasts[alpha]['skewed_t'].append(float(var_skewt))

            # M5: Asymmetric HistSim — only use negative residuals for left-tail
            # Rationale: For positive-skew assets, the full distribution overweights
            # positive residuals, making left-tail quantile too conservative.
            # Using only negative residuals gives a better estimate of the left tail.
            neg_z = current_z[current_z < 0]
            if len(neg_z) > 30:
                # Rescale: we need the alpha quantile of the full distribution,
                # but using only the negative half.
                # P(Z < q) = alpha. If we condition on Z<0, then:
                # P(Z < q | Z < 0) = alpha / P(Z < 0)
                p_neg = np.mean(current_z < 0)
                # The conditional quantile: what fraction of negative residuals
                # fall below q? It's alpha / p_neg.
                cond_alpha = alpha / p_neg
                if cond_alpha < 1.0:
                    z_asym = np.percentile(neg_z, cond_alpha * 100)
                else:
                    # alpha > p_neg: all negative values are below the threshold
                    # This shouldn't happen for alpha=0.01 or 0.05
                    z_asym = np.percentile(current_z, alpha * 100)
            else:
                z_asym = np.percentile(current_z, alpha * 100)
            var_asym = sigma_f * z_asym
            var_forecasts[alpha]['asym_histsim'].append(float(var_asym))

    print(f"  Refits: {n_refits}, OOS forecasts: {len(var_forecasts[0.01]['normal'])}")

    # 5. Backtest each method at each alpha
    method_names = {
        'normal': 'Normal',
        'student_t': 'Student-t',
        'histsim': 'HistSim',
        'skewed_t': 'Skewed-t',
        'asym_histsim': 'Asym-HistSim',
    }

    results = {}
    oos_r = oos_returns.values

    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}")

    for alpha in ALPHA_LEVELS:
        alpha_key = f"{alpha:.0%}"
        results[alpha_key] = {}

        print(f"\n  === {alpha_key} VaR ===")
        print(f"  {'Method':<15} {'Viol':>5} {'Rate':>8} {'Kupiec_p':>10} "
              f"{'Christ_p':>10} {'Basel':>7} {'Trinity':>8} {'Pinball':>10}")
        print(f"  {'-'*75}")

        for method_key, method_name in method_names.items():
            var_arr = np.array(var_forecasts[alpha][method_key])
            valid = np.isfinite(var_arr)
            if valid.sum() < 50:
                results[alpha_key][method_name] = {'error': 'insufficient valid forecasts'}
                continue

            bt = var_backtest(oos_r[valid], var_arr[valid], alpha_var=alpha)
            results[alpha_key][method_name] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {method_name:<15} {bt['n_violations']:>5}/{bt['n_total']}"
                  f" {bt['violation_rate']:>8.4f}"
                  f" {bt['kupiec']['p_value']:>10.4f}"
                  f" {bt['christoffersen']['p_value']:>10.4f}"
                  f" {bt['basel_traffic_light']:>7}"
                  f" {status:>8}"
                  f" {bt['pinball_loss']:>10.6f}")

    # 6. Key analysis: How Skewed-t fixes the paradox
    print(f"\n{'='*70}")
    print("ANALYSIS: How Skewed-t fixes the BTC positive-skew paradox")
    print(f"{'='*70}")

    # Show how xi > 1 makes left tail thinner
    if refit_params_log:
        avg_xi = np.mean([r['skewt_xi'] for r in refit_params_log])
        avg_df_skewt = np.mean([r['skewt_df'] for r in refit_params_log])
        avg_df_t = np.mean([r['student_df'] for r in refit_params_log])
        avg_z_skew = np.mean([r['residual_skewness'] for r in refit_params_log])

        print(f"  Average skewed-t xi: {avg_xi:.3f} {'(right-skewed, xi>1)' if avg_xi > 1 else '(left-skewed)'}")
        print(f"  Average residual skewness: {avg_z_skew:.3f}")
        print(f"  Average df (symmetric t): {avg_df_t:.1f}")
        print(f"  Average df (skewed-t): {avg_df_skewt:.1f}")

        # Compare quantiles at 1%
        z_norm_1 = norm.ppf(0.01)
        z_t_1 = t_dist.ppf(0.01, df=avg_df_t, loc=0.0,
                            scale=np.sqrt((avg_df_t - 2) / avg_df_t) if avg_df_t > 2 else 1.0)
        z_skewt_1 = skewt_ppf(0.01, df=avg_df_skewt, xi=avg_xi)

        print(f"\n  1% quantile comparison (z-scores):")
        print(f"    Normal:   z = {z_norm_1:.4f}")
        print(f"    Student-t: z = {z_t_1:.4f}  (more negative → more conservative)")
        print(f"    Skewed-t:  z = {z_skewt_1:.4f}  {'(less negative → less conservative)' if z_skewt_1 > z_t_1 else ''}")
        print(f"    Normal vs Student-t: Student-t is {abs(z_t_1/z_norm_1 - 1)*100:.1f}% more conservative")
        if z_skewt_1 != 0:
            print(f"    Skewed-t vs Student-t: Skewed-t is {abs(1 - z_skewt_1/z_t_1)*100:.1f}% "
                  f"{'less' if abs(z_skewt_1) < abs(z_t_1) else 'more'} conservative")

    # 7. Pinball loss comparison
    print(f"\n  === Pinball Loss Ranking (lower = better calibration) ===")
    for alpha in ALPHA_LEVELS:
        alpha_key = f"{alpha:.0%}"
        print(f"\n  {alpha_key} VaR:")
        pinball_ranks = []
        for method_name in method_names.values():
            if method_name in results[alpha_key] and 'pinball_loss' in results[alpha_key][method_name]:
                pinball_ranks.append((method_name, results[alpha_key][method_name]['pinball_loss']))
        pinball_ranks.sort(key=lambda x: x[1])
        for rank, (name, loss) in enumerate(pinball_ranks, 1):
            trinity = results[alpha_key][name].get('trinity_pass', False)
            print(f"    #{rank} {name:<15}: {loss:.6f} {'[Trinity PASS]' if trinity else '[Trinity FAIL]'}")

    elapsed_total = time.time() - t0
    print(f"\n  Total elapsed: {elapsed_total:.1f}s")

    # 8. Save results
    output = {
        'experiment_id': 'K830',
        'title': 'K830: BTC Skewed-t VaR — Fixing the K829 Positive-Skew Paradox',
        'method': 'GJR-GARCH(1,1) expanding window + 5 VaR methods (Normal/Student-t/HistSim/Skewed-t/Asym-HistSim)',
        'asset': 'BTC-USD',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'data_source': 'yfinance',
        'hypothesis': 'Skewed-t (xi>1 for BTC positive skew) should fix Student-t over-conservatism at 1% VaR',
        'error_log_rules': [
            'Student-t: scale=sqrt((df-2)/df) per-refit (K824v2 fix)',
            'GARCH OOS: recursive h[t]=f(h[t-1], r^2[t-1])',
            'Skewed-t: Fernandez-Steel (1998) with per-refit df and xi',
            'Per-refit parameters updated every 63 trading days (K825 lesson)',
        ],
        'references': [
            'K829: BTC Normal PASS (3/731), Student-t/HistSim FAIL (1/731, over-conservative)',
            'K802: GJR+Skewed-t for SPY, Fernandez-Steel (1998)',
            'K824v2: Student-t scale=sqrt((df-2)/df) fix',
            'Hansen (1994) Int. Econ. Rev. — skewed-t distribution',
            'Fernandez & Steel (1998) JASA 93 — skewed distributions',
            'Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_total_sec': round(elapsed_total, 1),
        'oos_stats': stats_oos,
        'full_sample_stats': stats_full,
        'n_oos': n_oos,
        'n_refits': n_refits,
        'refit_params_log': refit_params_log,
        'var_results': results,
        'analysis': {
            'avg_skewt_xi': round(avg_xi, 4) if refit_params_log else None,
            'avg_student_df': round(avg_df_t, 2) if refit_params_log else None,
            'avg_skewt_df': round(avg_df_skewt, 2) if refit_params_log else None,
            'avg_residual_skewness': round(avg_z_skew, 4) if refit_params_log else None,
            'quantile_comparison_1pct': {
                'normal': round(z_norm_1, 4) if refit_params_log else None,
                'student_t': round(z_t_1, 4) if refit_params_log else None,
                'skewed_t': round(z_skewt_1, 4) if refit_params_log else None,
            },
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    print("=" * 70)


if __name__ == '__main__':
    main()
