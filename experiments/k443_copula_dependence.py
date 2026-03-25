"""
K443: Copula-Based Tail Dependence for Cross-Asset Hedging
==========================================================
Jump exploration: non-linear dependence structure in cross-asset hedging.

Literature:
- Patton (2006) "Modelling asymmetric exchange rate dependence" IER
- Joe (1997) Multivariate models and dependence concepts
- Hsu, Tseng, Wang (2008) "Dynamic hedging with futures: Copula-based GARCH" JFM
- K425: SPY-TLT structural break (CUSUM break 2020-09, yield-driven)
- K427: SPY-TLT correlation structure breakpoint (Chow F=74.4)

Data: SPY, TLT, GLD from yfinance (2005-2025)
Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats, optimize
from datetime import datetime, timezone
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD & PREPARATION
# ============================================================
print("=" * 70)
print("K443: Copula-Based Tail Dependence for Cross-Asset Hedging")
print("=" * 70)

tickers = ['SPY', 'TLT', 'GLD']
data = yf.download(tickers, start='2005-01-01', end='2025-12-31', auto_adjust=True)

# Extract close prices
close = data['Close'][tickers].dropna()
print(f"\nData range: {close.index[0].date()} to {close.index[-1].date()}")
print(f"Total observations: {len(close)}")

# Log returns
returns = np.log(close / close.shift(1)).dropna()
print(f"Return observations: {len(returns)}")

# ============================================================
# 2. DESCRIPTIVE STATISTICS (mandatory pre-diagnostics)
# ============================================================
print("\n" + "=" * 70)
print("DESCRIPTIVE STATISTICS")
print("=" * 70)

desc_stats = {}
for ticker in tickers:
    r = returns[ticker].values
    adf_stat = stats.normaltest(r).statistic  # D'Agostino-Pearson
    desc_stats[ticker] = {
        'mean': float(np.mean(r) * 252),
        'std': float(np.std(r) * np.sqrt(252)),
        'skew': float(stats.skew(r)),
        'kurt': float(stats.kurtosis(r)),  # excess kurtosis
        'n': len(r),
        'min': float(np.min(r)),
        'max': float(np.max(r)),
        'jb_stat': float(stats.jarque_bera(r).statistic),
        'jb_pval': float(stats.jarque_bera(r).pvalue),
    }
    print(f"\n{ticker}:")
    print(f"  Ann. Mean: {desc_stats[ticker]['mean']:.4f}")
    print(f"  Ann. Std:  {desc_stats[ticker]['std']:.4f}")
    print(f"  Skewness:  {desc_stats[ticker]['skew']:.4f}")
    print(f"  Ex. Kurt:  {desc_stats[ticker]['kurt']:.4f}")
    print(f"  JB test:   stat={desc_stats[ticker]['jb_stat']:.1f}, p={desc_stats[ticker]['jb_pval']:.6f}")

# Linear correlations
print("\n--- Pearson Correlation Matrix ---")
corr_mat = returns.corr()
print(corr_mat.round(4))

# ============================================================
# 3. EMPIRICAL CDF TRANSFORM (Probability Integral Transform)
# ============================================================
def to_uniform(x):
    """Empirical CDF transform to pseudo-uniform [0,1]"""
    return stats.rankdata(x) / (len(x) + 1)

# Store pairs for analysis
pairs = {
    'SPY-TLT': ('SPY', 'TLT'),
    'SPY-GLD': ('SPY', 'GLD'),
}

# ============================================================
# 4. COPULA LOG-LIKELIHOOD FUNCTIONS
# ============================================================

def gaussian_copula_ll(rho, u1, u2):
    """Gaussian copula log-likelihood. Parameter: rho in (-1, 1)."""
    if abs(rho) >= 0.999:
        return -1e10
    x1 = stats.norm.ppf(np.clip(u1, 1e-6, 1 - 1e-6))
    x2 = stats.norm.ppf(np.clip(u2, 1e-6, 1 - 1e-6))
    ll = (-0.5 * np.log(1 - rho**2)
          - (rho**2 * (x1**2 + x2**2) - 2 * rho * x1 * x2) / (2 * (1 - rho**2)))
    return np.sum(ll[np.isfinite(ll)])


def student_t_copula_ll(params, u1, u2):
    """Student-t copula log-likelihood. Parameters: [rho, nu].
    nu = degrees of freedom (>2).
    Has symmetric tail dependence: lambda = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))
    """
    from scipy.special import gammaln
    rho, nu = params
    if abs(rho) >= 0.999 or nu <= 2.01 or nu > 100:
        return -1e10
    x1 = stats.t.ppf(np.clip(u1, 1e-6, 1 - 1e-6), df=nu)
    x2 = stats.t.ppf(np.clip(u2, 1e-6, 1 - 1e-6), df=nu)
    det_R = 1 - rho**2

    # log c(u1,u2) for bivariate t-copula
    # c = f_{2,R,nu}(t^{-1}_nu(u1), t^{-1}_nu(u2)) / (f_{1,nu}(t^{-1}_nu(u1)) * f_{1,nu}(t^{-1}_nu(u2)))
    # Using log-gamma for numerical stability
    ll = (gammaln((nu + 2) / 2) + gammaln(nu / 2)
          - 2 * gammaln((nu + 1) / 2)
          - 0.5 * np.log(det_R)
          + (-(nu + 2) / 2) * np.log(1 + (x1**2 + x2**2 - 2 * rho * x1 * x2) / (nu * det_R))
          + ((nu + 1) / 2) * np.log(1 + x1**2 / nu)
          + ((nu + 1) / 2) * np.log(1 + x2**2 / nu))
    return np.sum(ll[np.isfinite(ll)])


def clayton_copula_ll(theta, u1, u2):
    """Clayton copula log-likelihood. theta > 0.
    Lower tail dependence: lambda_L = 2^(-1/theta).
    """
    if theta <= 0.001:
        return -1e10
    u1c = np.clip(u1, 1e-6, 1 - 1e-6)
    u2c = np.clip(u2, 1e-6, 1 - 1e-6)
    # Clayton density: c(u1,u2) = (1+theta) * (u1*u2)^{-(1+theta)} * (u1^{-theta} + u2^{-theta} - 1)^{-(1/theta + 2)}
    a = u1c ** (-theta) + u2c ** (-theta) - 1.0
    # Handle numerical issues
    valid = a > 0
    ll = np.full_like(u1, -1e5)
    ll[valid] = (np.log(1 + theta)
                 - (1 + theta) * (np.log(u1c[valid]) + np.log(u2c[valid]))
                 + (-1.0 / theta - 2) * np.log(a[valid]))
    return np.sum(ll[np.isfinite(ll)])


def gumbel_copula_ll(theta, u1, u2):
    """Gumbel copula log-likelihood. theta >= 1.
    Upper tail dependence: lambda_U = 2 - 2^(1/theta).
    """
    if theta < 1.001:
        return -1e10
    u1c = np.clip(u1, 1e-6, 1 - 1e-6)
    u2c = np.clip(u2, 1e-6, 1 - 1e-6)

    lu1 = -np.log(u1c)
    lu2 = -np.log(u2c)
    A = (lu1**theta + lu2**theta) ** (1.0 / theta)

    # Gumbel copula: C(u1,u2) = exp(-A)
    # log density is complex, use explicit formula
    t1 = lu1 ** (theta - 1)
    t2 = lu2 ** (theta - 1)

    # log c(u1,u2)
    ll = (-A + np.log(A + theta - 1) + (theta - 1) * (np.log(lu1) + np.log(lu2))
          - (theta - 1) * np.log(A)
          + np.log(A) * (1 - 2 * theta) / theta  # correction
          + (1.0 / theta - 2) * np.log(lu1**theta + lu2**theta)
          + (theta - 1) * np.log(lu1) + (theta - 1) * np.log(lu2)
          )

    # Use a simpler but correct approach via finite differences for verification
    # Actually, let's use the exact Gumbel copula density formula:
    # c(u1,u2) = C(u1,u2) * (u1*u2)^{-1} * A^{2-2/theta} / (lu1*lu2)^{1-theta}
    #            * (A^(1/theta) + theta - 1) * (lu1^theta + lu2^theta)^{1/theta - 2}
    #            * (lu1 * lu2)^{theta-1}

    # Let me rewrite cleanly:
    C_val = np.exp(-A)
    s = lu1**theta + lu2**theta

    log_c = (np.log(C_val) - np.log(u1c) - np.log(u2c)
             + (1.0/theta - 2) * np.log(s)
             + (theta - 1) * (np.log(lu1) + np.log(lu2))
             + np.log(A + theta - 1))

    return np.sum(log_c[np.isfinite(log_c)])


def frank_copula_ll(theta, u1, u2):
    """Frank copula log-likelihood. theta != 0.
    No tail dependence (benchmark).
    """
    if abs(theta) < 0.01:
        return -1e10
    u1c = np.clip(u1, 1e-6, 1 - 1e-6)
    u2c = np.clip(u2, 1e-6, 1 - 1e-6)

    et = np.exp(-theta)
    et1 = np.exp(-theta * u1c)
    et2 = np.exp(-theta * u2c)

    # Frank copula density
    num = -theta * (1 - et)  * np.exp(-theta * (u1c + u2c))
    denom = ((1 - et) - (1 - et1) * (1 - et2)) ** 2

    valid = (num != 0) & (denom > 0)
    ll = np.full_like(u1, -1e5)
    ll[valid] = np.log(np.abs(num[valid])) - np.log(denom[valid])

    return np.sum(ll[np.isfinite(ll)])


# ============================================================
# 5. FIT COPULAS (MLE via scipy.optimize)
# ============================================================

def fit_all_copulas(u1, u2, verbose=True):
    """Fit 5 copulas and return results with AIC/BIC."""
    n = len(u1)
    results = {}

    # 1. Gaussian
    neg_ll = lambda rho: -gaussian_copula_ll(rho, u1, u2)
    res = optimize.minimize_scalar(neg_ll, bounds=(-0.99, 0.99), method='bounded')
    ll_gauss = -res.fun
    results['Gaussian'] = {
        'params': {'rho': float(res.x)},
        'loglik': float(ll_gauss),
        'n_params': 1,
        'AIC': float(-2 * ll_gauss + 2 * 1),
        'BIC': float(-2 * ll_gauss + np.log(n) * 1),
        'tail_dep_lower': 0.0,
        'tail_dep_upper': 0.0,
    }

    # 2. Student-t
    neg_ll_t = lambda p: -student_t_copula_ll(p, u1, u2)
    # Multi-start for robustness
    best_t = None
    for rho_init in [-0.3, 0.0, 0.3]:
        for nu_init in [4, 8, 15]:
            try:
                res_t = optimize.minimize(neg_ll_t, [rho_init, nu_init],
                                          bounds=[(-0.99, 0.99), (2.1, 100)],
                                          method='L-BFGS-B')
                if best_t is None or res_t.fun < best_t.fun:
                    best_t = res_t
            except:
                pass

    if best_t is not None:
        rho_t, nu_t = best_t.x
        ll_t = -best_t.fun
        # Tail dependence for t-copula: lambda = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))
        if abs(rho_t) < 0.999:
            arg = -np.sqrt((nu_t + 1) * (1 - rho_t) / (1 + rho_t))
            tail_t = 2 * stats.t.cdf(arg, df=nu_t + 1)
        else:
            tail_t = 0.0
        results['Student-t'] = {
            'params': {'rho': float(rho_t), 'nu': float(nu_t)},
            'loglik': float(ll_t),
            'n_params': 2,
            'AIC': float(-2 * ll_t + 2 * 2),
            'BIC': float(-2 * ll_t + np.log(n) * 2),
            'tail_dep_lower': float(tail_t),  # symmetric
            'tail_dep_upper': float(tail_t),
            'converged': bool(best_t.success),
        }

    # 3. Clayton (lower tail dependence)
    neg_ll_c = lambda theta: -clayton_copula_ll(theta, u1, u2)
    res_c = optimize.minimize_scalar(neg_ll_c, bounds=(0.01, 30), method='bounded')
    ll_c = -res_c.fun
    theta_c = float(res_c.x)
    lambda_L_clayton = 2 ** (-1 / theta_c) if theta_c > 0 else 0.0
    results['Clayton'] = {
        'params': {'theta': theta_c},
        'loglik': float(ll_c),
        'n_params': 1,
        'AIC': float(-2 * ll_c + 2 * 1),
        'BIC': float(-2 * ll_c + np.log(n) * 1),
        'tail_dep_lower': float(lambda_L_clayton),
        'tail_dep_upper': 0.0,
    }

    # 4. Gumbel (upper tail dependence)
    neg_ll_g = lambda theta: -gumbel_copula_ll(theta, u1, u2)
    res_g = optimize.minimize_scalar(neg_ll_g, bounds=(1.01, 20), method='bounded')
    ll_g = -res_g.fun
    theta_g = float(res_g.x)
    lambda_U_gumbel = 2 - 2 ** (1 / theta_g) if theta_g > 1 else 0.0
    results['Gumbel'] = {
        'params': {'theta': theta_g},
        'loglik': float(ll_g),
        'n_params': 1,
        'AIC': float(-2 * ll_g + 2 * 1),
        'BIC': float(-2 * ll_g + np.log(n) * 1),
        'tail_dep_lower': 0.0,
        'tail_dep_upper': float(lambda_U_gumbel),
    }

    # 5. Frank (no tail dependence — benchmark)
    neg_ll_f = lambda theta: -frank_copula_ll(theta, u1, u2)
    # Multi-start
    best_f = None
    for t_init in [-5, -2, -0.5, 0.5, 2, 5]:
        try:
            res_f = optimize.minimize_scalar(neg_ll_f, bounds=(-30, 30), method='bounded')
            if best_f is None or res_f.fun < best_f.fun:
                best_f = res_f
        except:
            pass
    if best_f is not None:
        ll_f = -best_f.fun
        theta_f = float(best_f.x)
        results['Frank'] = {
            'params': {'theta': theta_f},
            'loglik': float(ll_f),
            'n_params': 1,
            'AIC': float(-2 * ll_f + 2 * 1),
            'BIC': float(-2 * ll_f + np.log(n) * 1),
            'tail_dep_lower': 0.0,
            'tail_dep_upper': 0.0,
        }

    if verbose:
        print(f"\n{'Copula':<12} {'LogLik':>10} {'AIC':>10} {'BIC':>10} {'λ_L':>8} {'λ_U':>8} {'Params'}")
        print("-" * 80)
        for name, r in sorted(results.items(), key=lambda x: x[1]['AIC']):
            params_str = ', '.join(f"{k}={v:.4f}" for k, v in r['params'].items())
            print(f"{name:<12} {r['loglik']:>10.1f} {r['AIC']:>10.1f} {r['BIC']:>10.1f} "
                  f"{r['tail_dep_lower']:>8.4f} {r['tail_dep_upper']:>8.4f} {params_str}")

    return results

# ============================================================
# 6. FULL-SAMPLE COPULA FIT
# ============================================================
print("\n" + "=" * 70)
print("FULL-SAMPLE COPULA FIT")
print("=" * 70)

full_results = {}
for pair_name, (a1, a2) in pairs.items():
    print(f"\n--- {pair_name} ---")
    r1 = returns[a1].values
    r2 = returns[a2].values
    u1 = to_uniform(r1)
    u2 = to_uniform(r2)

    res = fit_all_copulas(u1, u2, verbose=True)
    full_results[pair_name] = res

    # Best by AIC
    best = min(res.items(), key=lambda x: x[1]['AIC'])
    print(f"\n  Best copula (AIC): {best[0]}")

# ============================================================
# 7. PRE/POST 2020 COMPARISON (structural break analysis)
# ============================================================
print("\n" + "=" * 70)
print("PRE/POST 2020 COPULA COMPARISON")
print("=" * 70)

# K425 found CUSUM break at 2020-09-17
break_date = pd.Timestamp('2020-09-17')

pre_post_results = {}
for pair_name, (a1, a2) in pairs.items():
    print(f"\n{'='*40}")
    print(f"{pair_name}")
    print(f"{'='*40}")

    r1 = returns[a1]
    r2 = returns[a2]

    for period_name, mask in [('Pre-2020', returns.index < break_date),
                               ('Post-2020', returns.index >= break_date)]:
        r1_sub = r1[mask].values
        r2_sub = r2[mask].values
        n_sub = len(r1_sub)

        print(f"\n--- {period_name} (n={n_sub}) ---")
        print(f"  Linear corr: {np.corrcoef(r1_sub, r2_sub)[0,1]:.4f}")

        u1_sub = to_uniform(r1_sub)
        u2_sub = to_uniform(r2_sub)

        res = fit_all_copulas(u1_sub, u2_sub, verbose=True)
        pre_post_results[f"{pair_name}_{period_name}"] = res

# ============================================================
# 8. ASYMMETRIC TAIL DEPENDENCE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("ASYMMETRIC TAIL DEPENDENCE (Empirical)")
print("=" * 70)

def empirical_tail_dependence(r1, r2, quantiles=[0.01, 0.05, 0.10]):
    """
    Empirical lower and upper tail dependence.
    Lower: P(r2 < Q_q(r2) | r1 < Q_q(r1))
    Upper: P(r2 > Q_{1-q}(r2) | r1 > Q_{1-q}(r1))
    Also: cross-tail (crash together) P(r2 < Q_q(r2) | r1 < Q_q(r1))
    """
    results = {}
    for q in quantiles:
        # Lower tail: both assets crash
        q1_low = np.quantile(r1, q)
        q2_low = np.quantile(r2, q)
        mask_1_low = r1 < q1_low
        n_1_low = np.sum(mask_1_low)
        if n_1_low > 0:
            lower = np.mean(r2[mask_1_low] < q2_low)
        else:
            lower = np.nan

        # Upper tail: both assets rally
        q1_high = np.quantile(r1, 1 - q)
        q2_high = np.quantile(r2, 1 - q)
        mask_1_high = r1 > q1_high
        n_1_high = np.sum(mask_1_high)
        if n_1_high > 0:
            upper = np.mean(r2[mask_1_high] > q2_high)
        else:
            upper = np.nan

        # Cross-tail: r1 crashes, r2 also crashes (relevant for hedging!)
        # For hedging assets (TLT, GLD), we want: when SPY crashes, does hedge crash too?
        # This IS the lower tail dependence above

        # Also: when SPY crashes, does hedge RALLY? (desired for hedging)
        if n_1_low > 0:
            hedge_works = np.mean(r2[mask_1_low] > q2_high)
        else:
            hedge_works = np.nan

        results[f'q={q}'] = {
            'lower_tail': float(lower),  # both crash
            'upper_tail': float(upper),  # both rally
            'hedge_works_in_crash': float(hedge_works),  # SPY crash, hedge rallies
            'n_conditioning': int(n_1_low),
            'expected_under_independence': float(q),
        }
    return results

tail_dep_results = {}
for pair_name, (a1, a2) in pairs.items():
    r1 = returns[a1].values
    r2 = returns[a2].values

    print(f"\n--- {pair_name} ---")
    td = empirical_tail_dependence(r1, r2)
    tail_dep_results[pair_name] = td

    for qname, vals in td.items():
        ratio_lower = vals['lower_tail'] / vals['expected_under_independence']
        ratio_upper = vals['upper_tail'] / vals['expected_under_independence']
        print(f"  {qname}: Lower={vals['lower_tail']:.4f} ({ratio_lower:.1f}x indep), "
              f"Upper={vals['upper_tail']:.4f} ({ratio_upper:.1f}x indep), "
              f"Hedge-in-crash={vals['hedge_works_in_crash']:.4f} "
              f"(n={vals['n_conditioning']})")

# ============================================================
# 9. ROLLING COPULA PARAMETERS (Time-Varying Dependence)
# ============================================================
print("\n" + "=" * 70)
print("ROLLING COPULA ANALYSIS (250-day window)")
print("=" * 70)

window = 250
rolling_results = {}

for pair_name, (a1, a2) in pairs.items():
    r1 = returns[a1].values
    r2 = returns[a2].values
    dates = returns.index

    n = len(r1)
    roll_dates = []
    roll_gauss_rho = []
    roll_clayton_theta = []
    roll_clayton_tail_L = []
    roll_t_rho = []
    roll_t_nu = []
    roll_t_tail = []
    roll_linear_corr = []

    # Subsample every 20 days for efficiency (250/20 = ~12.5 overlap)
    step = 20
    for i in range(window, n, step):
        r1_w = r1[i - window:i]
        r2_w = r2[i - window:i]
        u1_w = to_uniform(r1_w)
        u2_w = to_uniform(r2_w)

        roll_dates.append(str(dates[i].date()))
        roll_linear_corr.append(float(np.corrcoef(r1_w, r2_w)[0, 1]))

        # Gaussian
        try:
            neg_ll = lambda rho: -gaussian_copula_ll(rho, u1_w, u2_w)
            res = optimize.minimize_scalar(neg_ll, bounds=(-0.99, 0.99), method='bounded')
            roll_gauss_rho.append(float(res.x))
        except:
            roll_gauss_rho.append(np.nan)

        # Clayton
        try:
            neg_ll_c = lambda theta: -clayton_copula_ll(theta, u1_w, u2_w)
            res_c = optimize.minimize_scalar(neg_ll_c, bounds=(0.01, 30), method='bounded')
            theta_c = float(res_c.x)
            roll_clayton_theta.append(theta_c)
            roll_clayton_tail_L.append(float(2 ** (-1 / theta_c)))
        except:
            roll_clayton_theta.append(np.nan)
            roll_clayton_tail_L.append(np.nan)

        # Student-t
        try:
            neg_ll_t = lambda p: -student_t_copula_ll(p, u1_w, u2_w)
            best = None
            for rho_init in [-0.3, 0.0]:
                for nu_init in [5, 10]:
                    try:
                        r_t = optimize.minimize(neg_ll_t, [rho_init, nu_init],
                                                bounds=[(-0.99, 0.99), (2.1, 100)],
                                                method='L-BFGS-B')
                        if best is None or r_t.fun < best.fun:
                            best = r_t
                    except:
                        pass
            if best is not None:
                rho_t, nu_t = best.x
                roll_t_rho.append(float(rho_t))
                roll_t_nu.append(float(nu_t))
                arg = -np.sqrt((nu_t + 1) * (1 - rho_t) / (1 + rho_t))
                roll_t_tail.append(float(2 * stats.t.cdf(arg, df=nu_t + 1)))
            else:
                roll_t_rho.append(np.nan)
                roll_t_nu.append(np.nan)
                roll_t_tail.append(np.nan)
        except:
            roll_t_rho.append(np.nan)
            roll_t_nu.append(np.nan)
            roll_t_tail.append(np.nan)

    rolling_results[pair_name] = {
        'dates': roll_dates,
        'linear_corr': roll_linear_corr,
        'gaussian_rho': roll_gauss_rho,
        'clayton_theta': roll_clayton_theta,
        'clayton_tail_L': roll_clayton_tail_L,
        't_rho': roll_t_rho,
        't_nu': roll_t_nu,
        't_tail': roll_t_tail,
    }

    # Summary statistics
    print(f"\n--- {pair_name} Rolling Summary ---")
    print(f"  Windows: {len(roll_dates)}")
    print(f"  Linear corr: mean={np.nanmean(roll_linear_corr):.4f}, "
          f"std={np.nanstd(roll_linear_corr):.4f}, "
          f"min={np.nanmin(roll_linear_corr):.4f}, max={np.nanmax(roll_linear_corr):.4f}")
    print(f"  Gauss rho:   mean={np.nanmean(roll_gauss_rho):.4f}, "
          f"std={np.nanstd(roll_gauss_rho):.4f}")
    print(f"  Clayton λ_L: mean={np.nanmean(roll_clayton_tail_L):.4f}, "
          f"std={np.nanstd(roll_clayton_tail_L):.4f}")
    print(f"  t-copula tail: mean={np.nanmean(roll_t_tail):.4f}, "
          f"std={np.nanstd(roll_t_tail):.4f}")

    # Pre vs post break
    post_mask = [d >= '2020-09-17' for d in roll_dates]
    pre_mask = [not m for m in post_mask]

    pre_linear = [roll_linear_corr[i] for i in range(len(roll_dates)) if pre_mask[i]]
    post_linear = [roll_linear_corr[i] for i in range(len(roll_dates)) if post_mask[i]]
    pre_tail = [roll_t_tail[i] for i in range(len(roll_dates)) if pre_mask[i]]
    post_tail = [roll_t_tail[i] for i in range(len(roll_dates)) if post_mask[i]]

    if pre_linear and post_linear:
        print(f"\n  Pre-break linear corr: {np.nanmean(pre_linear):.4f}")
        print(f"  Post-break linear corr: {np.nanmean(post_linear):.4f}")
        t_stat, p_val = stats.ttest_ind(
            [x for x in pre_linear if not np.isnan(x)],
            [x for x in post_linear if not np.isnan(x)]
        )
        print(f"  t-test for corr shift: t={t_stat:.2f}, p={p_val:.6f}")

    if pre_tail and post_tail:
        pre_tail_clean = [x for x in pre_tail if not np.isnan(x)]
        post_tail_clean = [x for x in post_tail if not np.isnan(x)]
        if pre_tail_clean and post_tail_clean:
            print(f"  Pre-break t-copula tail dep: {np.mean(pre_tail_clean):.4f}")
            print(f"  Post-break t-copula tail dep: {np.mean(post_tail_clean):.4f}")
            t_stat2, p_val2 = stats.ttest_ind(pre_tail_clean, post_tail_clean)
            print(f"  t-test for tail dep shift: t={t_stat2:.2f}, p={p_val2:.6f}")

# ============================================================
# 10. COPULA-BASED HEDGE RATIO vs OLS HEDGE RATIO
# ============================================================
print("\n" + "=" * 70)
print("COPULA vs OLS HEDGE RATIO (OOS: 2023-2024)")
print("=" * 70)

def copula_hedge_ratio(r1, r2, copula_type='gaussian'):
    """
    Copula-based hedge ratio.
    For Gaussian copula: h* = rho * sigma2/sigma1  (same as OLS for Gaussian margins)
    For t-copula: h* depends on tail behavior; we use conditional expectation approach.

    In practice, copula HR ≈ rank-based Spearman correlation × sigma ratio
    (more robust to outliers than OLS).
    """
    u1 = to_uniform(r1)
    u2 = to_uniform(r2)
    sigma1 = np.std(r1)
    sigma2 = np.std(r2)

    if copula_type == 'gaussian':
        neg_ll = lambda rho: -gaussian_copula_ll(rho, u1, u2)
        res = optimize.minimize_scalar(neg_ll, bounds=(-0.99, 0.99), method='bounded')
        rho_cop = res.x
        hr = rho_cop * sigma2 / sigma1
    elif copula_type == 'student_t':
        neg_ll_t = lambda p: -student_t_copula_ll(p, u1, u2)
        best = None
        for rho_init in [-0.3, 0.0, 0.3]:
            for nu_init in [5, 10]:
                try:
                    r_t = optimize.minimize(neg_ll_t, [rho_init, nu_init],
                                            bounds=[(-0.99, 0.99), (2.1, 100)],
                                            method='L-BFGS-B')
                    if best is None or r_t.fun < best.fun:
                        best = r_t
                except:
                    pass
        if best is not None:
            rho_t = best.x[0]
            hr = rho_t * sigma2 / sigma1
        else:
            hr = np.nan
    elif copula_type == 'rank':
        # Spearman rank-based approach (robust to fat tails)
        rho_spearman = stats.spearmanr(r1, r2).statistic
        hr = rho_spearman * sigma2 / sigma1
    else:
        hr = np.nan

    return float(hr)


def ols_hedge_ratio(r1, r2):
    """Standard OLS hedge ratio: h* = cov(r1,r2)/var(r2)
    where r1 = spot, r2 = hedge instrument.
    h* minimizes var(r1 - h * r2)."""
    return float(np.cov(r1, r2)[0, 1] / np.var(r2))


# OOS evaluation
oos_start = pd.Timestamp('2023-01-01')
oos_end = pd.Timestamp('2024-12-31')
estimation_window = 504  # 2 years

oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
oos_returns = returns[oos_mask]

hedging_results = {}

for pair_name, (a1, a2) in pairs.items():
    print(f"\n--- {pair_name} Hedging Comparison (OOS 2023-2024) ---")

    r1_all = returns[a1]
    r2_all = returns[a2]

    # Rolling hedge ratio estimation
    oos_indices = returns.index[oos_mask]

    hedged_ols = []
    hedged_gauss_cop = []
    hedged_t_cop = []
    hedged_rank_cop = []
    unhedged = []
    hr_ols_list = []
    hr_gauss_list = []
    hr_t_list = []
    hr_rank_list = []

    # Estimate hedge ratios monthly (every 21 days), apply for next month
    rebalance_freq = 21
    current_hr_ols = None
    current_hr_gauss = None
    current_hr_t = None
    current_hr_rank = None

    for i_day, date in enumerate(oos_indices):
        idx = returns.index.get_loc(date)

        if i_day % rebalance_freq == 0 or current_hr_ols is None:
            # Estimate on past data
            est_r1 = r1_all.iloc[max(0, idx - estimation_window):idx].values
            est_r2 = r2_all.iloc[max(0, idx - estimation_window):idx].values

            if len(est_r1) < 100:
                continue

            current_hr_ols = ols_hedge_ratio(est_r1, est_r2)
            current_hr_gauss = copula_hedge_ratio(est_r1, est_r2, 'gaussian')
            current_hr_t = copula_hedge_ratio(est_r1, est_r2, 'student_t')
            current_hr_rank = copula_hedge_ratio(est_r1, est_r2, 'rank')

            hr_ols_list.append(current_hr_ols)
            hr_gauss_list.append(current_hr_gauss)
            hr_t_list.append(current_hr_t)
            hr_rank_list.append(current_hr_rank)

        if current_hr_ols is None:
            continue

        r1_day = float(r1_all.iloc[idx])
        r2_day = float(r2_all.iloc[idx])

        unhedged.append(r1_day)
        hedged_ols.append(r1_day - current_hr_ols * r2_day)
        hedged_gauss_cop.append(r1_day - current_hr_gauss * r2_day)
        hedged_t_cop.append(r1_day - current_hr_t * r2_day)
        hedged_rank_cop.append(r1_day - current_hr_rank * r2_day)

    unhedged = np.array(unhedged)
    hedged_ols = np.array(hedged_ols)
    hedged_gauss_cop = np.array(hedged_gauss_cop)
    hedged_t_cop = np.array(hedged_t_cop)
    hedged_rank_cop = np.array(hedged_rank_cop)

    var_unhedged = np.var(unhedged)

    he_ols = 1 - np.var(hedged_ols) / var_unhedged
    he_gauss = 1 - np.var(hedged_gauss_cop) / var_unhedged
    he_t = 1 - np.var(hedged_t_cop) / var_unhedged
    he_rank = 1 - np.var(hedged_rank_cop) / var_unhedged

    # Tail risk comparison: VaR at 5% and 1%
    var5_unhedged = np.quantile(unhedged, 0.05)
    var1_unhedged = np.quantile(unhedged, 0.01)

    var5_ols = np.quantile(hedged_ols, 0.05)
    var1_ols = np.quantile(hedged_ols, 0.01)

    var5_gauss = np.quantile(hedged_gauss_cop, 0.05)
    var1_gauss = np.quantile(hedged_gauss_cop, 0.01)

    var5_t = np.quantile(hedged_t_cop, 0.05)
    var1_t = np.quantile(hedged_t_cop, 0.01)

    var5_rank = np.quantile(hedged_rank_cop, 0.05)
    var1_rank = np.quantile(hedged_rank_cop, 0.01)

    # DM-like test: compare squared hedging errors OLS vs Copula
    se_ols = hedged_ols ** 2
    se_t = hedged_t_cop ** 2
    d = se_ols - se_t  # positive = OLS worse
    dm_stat = np.mean(d) / (np.std(d) / np.sqrt(len(d)))
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    print(f"\n  OOS days: {len(unhedged)}")
    print(f"  Var(unhedged):     {var_unhedged:.8f}")
    print(f"\n  {'Method':<20} {'HE':>8} {'VaR5%':>10} {'VaR1%':>10} {'Mean HR':>10}")
    print(f"  {'-'*60}")
    print(f"  {'OLS':<20} {he_ols:>8.4f} {var5_ols:>10.4f} {var1_ols:>10.4f} {np.mean(hr_ols_list):>10.4f}")
    print(f"  {'Gaussian Copula':<20} {he_gauss:>8.4f} {var5_gauss:>10.4f} {var1_gauss:>10.4f} {np.mean(hr_gauss_list):>10.4f}")
    print(f"  {'Student-t Copula':<20} {he_t:>8.4f} {var5_t:>10.4f} {var1_t:>10.4f} {np.mean(hr_t_list):>10.4f}")
    print(f"  {'Rank-based Copula':<20} {he_rank:>8.4f} {var5_rank:>10.4f} {var1_rank:>10.4f} {np.mean(hr_rank_list):>10.4f}")

    print(f"\n  DM test (OLS vs t-copula): stat={dm_stat:.3f}, p={dm_pval:.4f}")

    hedging_results[pair_name] = {
        'n_oos_days': len(unhedged),
        'var_unhedged': float(var_unhedged),
        'methods': {
            'OLS': {
                'HE': float(he_ols),
                'VaR_5pct': float(var5_ols),
                'VaR_1pct': float(var1_ols),
                'mean_HR': float(np.mean(hr_ols_list)),
                'std_HR': float(np.std(hr_ols_list)),
            },
            'Gaussian_Copula': {
                'HE': float(he_gauss),
                'VaR_5pct': float(var5_gauss),
                'VaR_1pct': float(var1_gauss),
                'mean_HR': float(np.mean(hr_gauss_list)),
                'std_HR': float(np.std(hr_gauss_list)),
            },
            'Student_t_Copula': {
                'HE': float(he_t),
                'VaR_5pct': float(var5_t),
                'VaR_1pct': float(var1_t),
                'mean_HR': float(np.mean(hr_t_list)),
                'std_HR': float(np.std(hr_t_list)),
            },
            'Rank_Copula': {
                'HE': float(he_rank),
                'VaR_5pct': float(var5_rank),
                'VaR_1pct': float(var1_rank),
                'mean_HR': float(np.mean(hr_rank_list)),
                'std_HR': float(np.std(hr_rank_list)),
            },
        },
        'dm_test_ols_vs_t_copula': {
            'statistic': float(dm_stat),
            'p_value': float(dm_pval),
            'conclusion': 'OLS worse' if dm_stat > 1.96 else ('t-copula worse' if dm_stat < -1.96 else 'No significant difference'),
        },
    }

# ============================================================
# 11. CRISIS-PERIOD TAIL ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("CRISIS-PERIOD TAIL DEPENDENCE")
print("=" * 70)

# Identify worst SPY days (bottom 1%, 5%)
spy_ret = returns['SPY'].values
tlt_ret = returns['TLT'].values
gld_ret = returns['GLD'].values

crisis_analysis = {}

for q_label, q_val in [('bottom_1pct', 0.01), ('bottom_5pct', 0.05)]:
    threshold = np.quantile(spy_ret, q_val)
    mask = spy_ret <= threshold
    n_crisis = np.sum(mask)

    print(f"\n--- SPY {q_label} (threshold={threshold:.4f}, n={n_crisis}) ---")

    for hedge_name, hedge_ret in [('TLT', tlt_ret), ('GLD', gld_ret)]:
        # Behavior of hedge asset during SPY crashes
        hedge_in_crash = hedge_ret[mask]
        mean_hedge = np.mean(hedge_in_crash)
        pct_positive = np.mean(hedge_in_crash > 0)

        # Compare with unconditional
        mean_unconditional = np.mean(hedge_ret)

        # t-test: does hedge perform differently in crashes?
        t_stat, p_val = stats.ttest_1samp(hedge_in_crash, mean_unconditional)

        print(f"  {hedge_name}: mean={mean_hedge:.4f} (unconditional={mean_unconditional:.4f}), "
              f"P(positive)={pct_positive:.2%}, t={t_stat:.2f}, p={p_val:.4f}")

        crisis_analysis[f"{q_label}_{hedge_name}"] = {
            'n_crisis_days': int(n_crisis),
            'spy_threshold': float(threshold),
            'mean_hedge_return': float(mean_hedge),
            'mean_unconditional': float(mean_unconditional),
            'pct_hedge_positive': float(pct_positive),
            'ttest_stat': float(t_stat),
            'ttest_pval': float(p_val),
        }

# ============================================================
# 12. KENDALL'S TAU & SPEARMAN (Rank-Based Dependence)
# ============================================================
print("\n" + "=" * 70)
print("RANK-BASED DEPENDENCE MEASURES")
print("=" * 70)

rank_dep = {}
for pair_name, (a1, a2) in pairs.items():
    r1 = returns[a1].values
    r2 = returns[a2].values

    pearson = np.corrcoef(r1, r2)[0, 1]
    spearman, sp_p = stats.spearmanr(r1, r2)
    kendall, kt_p = stats.kendalltau(r1, r2)

    print(f"\n{pair_name}:")
    print(f"  Pearson:  {pearson:.4f}")
    print(f"  Spearman: {spearman:.4f} (p={sp_p:.6f})")
    print(f"  Kendall:  {kendall:.4f} (p={kt_p:.6f})")
    print(f"  Spearman/Pearson ratio: {spearman/pearson:.3f} (>1 means more tail dependence)")

    rank_dep[pair_name] = {
        'pearson': float(pearson),
        'spearman': float(spearman),
        'spearman_pval': float(sp_p),
        'kendall': float(kendall),
        'kendall_pval': float(kt_p),
        'spearman_pearson_ratio': float(spearman / pearson) if pearson != 0 else None,
    }

# ============================================================
# 13. COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & KEY FINDINGS")
print("=" * 70)

# Determine best copula per pair
summary = {}
for pair_name in pairs:
    if pair_name in full_results:
        best = min(full_results[pair_name].items(), key=lambda x: x[1]['AIC'])
        summary[pair_name] = {
            'best_copula': best[0],
            'best_AIC': best[1]['AIC'],
            'tail_dep_lower': best[1]['tail_dep_lower'],
            'tail_dep_upper': best[1]['tail_dep_upper'],
        }
        print(f"\n{pair_name}:")
        print(f"  Best copula: {best[0]} (AIC={best[1]['AIC']:.1f})")
        print(f"  Tail dependence: lower={best[1]['tail_dep_lower']:.4f}, upper={best[1]['tail_dep_upper']:.4f}")

# Key finding summary
print("\n--- KEY FINDINGS ---")

# 1. Asymmetric tail dependence?
for pair_name in pairs:
    td = tail_dep_results[pair_name]['q=0.05']
    asymmetry = td['lower_tail'] - td['upper_tail']
    print(f"\n{pair_name} tail asymmetry (5%): lower={td['lower_tail']:.4f}, upper={td['upper_tail']:.4f}, "
          f"diff={asymmetry:.4f}")

# 2. Copula vs OLS hedging
for pair_name in hedging_results:
    hr = hedging_results[pair_name]
    he_ols = hr['methods']['OLS']['HE']
    he_t = hr['methods']['Student_t_Copula']['HE']
    he_rank = hr['methods']['Rank_Copula']['HE']
    dm_p = hr['dm_test_ols_vs_t_copula']['p_value']
    print(f"\n{pair_name} hedging: OLS HE={he_ols:.4f}, t-copula HE={he_t:.4f}, "
          f"Rank HE={he_rank:.4f}, DM p={dm_p:.4f}")

# ============================================================
# 14. SAVE RESULTS
# ============================================================

# Subsample rolling results for JSON (keep every 5th point)
rolling_results_compact = {}
for pair_name, rr in rolling_results.items():
    n_pts = len(rr['dates'])
    step = max(1, n_pts // 100)  # Keep ~100 points max
    rolling_results_compact[pair_name] = {
        k: [v[i] for i in range(0, n_pts, step)] if isinstance(v, list) else v
        for k, v in rr.items()
    }

output = {
    'experiment_id': 'K443',
    'title': 'Copula-Based Tail Dependence for Cross-Asset Hedging',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_range': f"{close.index[0].date()} to {close.index[-1].date()}",
    'n_observations': len(returns),
    'assets': tickers,
    'pairs_analyzed': list(pairs.keys()),
    'break_date': '2020-09-17',
    'oos_period': '2023-01-01 to 2024-12-31',
    'literature': [
        'Patton (2006) IER',
        'Joe (1997) Multivariate Models',
        'Hsu, Tseng, Wang (2008) JFM',
        'K425 Bond-Equity Decorrelation',
        'K427 SPY-TLT Correlation Breakpoint',
    ],
    'descriptive_stats': desc_stats,
    'correlation_matrix': {
        f"{a1}-{a2}": float(corr_mat.loc[a1, a2])
        for a1 in tickers for a2 in tickers if a1 != a2
    },
    'rank_dependence': rank_dep,
    'full_sample_copula_fit': {
        pair_name: {
            cop_name: {k: v for k, v in cop_res.items() if k != 'converged'}
            for cop_name, cop_res in pair_results.items()
        }
        for pair_name, pair_results in full_results.items()
    },
    'pre_post_break_copula': {
        key: {
            cop_name: {k: v for k, v in cop_res.items() if k != 'converged'}
            for cop_name, cop_res in pair_results.items()
        }
        for key, pair_results in pre_post_results.items()
    },
    'empirical_tail_dependence': tail_dep_results,
    'crisis_analysis': crisis_analysis,
    'rolling_copula': rolling_results_compact,
    'hedging_comparison': hedging_results,
    'summary': summary,
    'key_findings': {},  # Will be filled after analysis
    'limitations': [
        'Copula fit uses ECDF (not parametric margins) — may lose info for small samples',
        'Rolling window (250d) smooths structural breaks — CUSUM would be better for breakpoint detection',
        'Copula HR for Gaussian margins equals OLS — advantage requires non-Gaussian margins',
        'OOS period (2023-2024) is only 2 years — may not generalize',
        'Static copula ignores time-varying dependence within estimation window',
    ],
}

# Fill key findings based on actual results
findings = []

# Finding 1: Best copula
for pair_name in pairs:
    if pair_name in summary:
        findings.append(f"{pair_name}: Best copula is {summary[pair_name]['best_copula']}")

# Finding 2: Tail asymmetry
for pair_name in pairs:
    td = tail_dep_results[pair_name]['q=0.05']
    asymmetry = td['lower_tail'] - td['upper_tail']
    if abs(asymmetry) > 0.02:
        findings.append(f"{pair_name}: Asymmetric tail dependence (lower={td['lower_tail']:.3f} vs upper={td['upper_tail']:.3f})")
    else:
        findings.append(f"{pair_name}: Symmetric tail dependence (lower≈upper≈{td['lower_tail']:.3f})")

# Finding 3: Hedging comparison
for pair_name in hedging_results:
    hr = hedging_results[pair_name]
    dm_p = hr['dm_test_ols_vs_t_copula']['p_value']
    if dm_p < 0.05:
        findings.append(f"{pair_name}: Copula HR significantly different from OLS (DM p={dm_p:.4f})")
    else:
        findings.append(f"{pair_name}: No significant difference between Copula and OLS HR (DM p={dm_p:.4f})")

# Finding 4: Crisis behavior
for hedge_name in ['TLT', 'GLD']:
    ca = crisis_analysis.get(f'bottom_5pct_{hedge_name}')
    if ca:
        if ca['ttest_pval'] < 0.05:
            findings.append(f"{hedge_name} in SPY crashes (5%): mean={ca['mean_hedge_return']:.4f}, "
                          f"significantly different from normal (p={ca['ttest_pval']:.4f})")

output['key_findings'] = findings

# Save
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, 'k443_copula_dependence_results.json')

with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print(f"\nKey findings:")
for i, finding in enumerate(findings, 1):
    print(f"  {i}. {finding}")

print("\n" + "=" * 70)
print("K443 COMPLETE")
print("=" * 70)
