"""
K970: MF2-GARCH (Mixed-Frequency Squared GARCH)
Based on Conrad & Engle (2025, J. Applied Econometrics)

Simplified implementation:
  sigma2_t = tau_t * g_t
  - tau_t: long-run component (rolling RV, VIX, or EMA)
  - g_t: short-run GJR-GARCH on standardized returns r_tilde = r / sqrt(tau)

Variants:
  MF2-RV:  tau = 22-day rolling RV
  MF2-VIX: tau = (VIX / sqrt(252))^2
  MF2-EMA: tau = EMA of r^2 (halflife=22)
  Baseline: standard GJR-GARCH(1,1)

Data: SPY 2006-2026, IS: 2006-2018, OOS: 2019-2026
Target: r^2 (close-to-close squared return)

References:
  - Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous
    long-run dynamics. J. Applied Econometrics.
  - Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and
    macroeconomic fundamentals. Review of Economics and Statistics.
  - Patton, A.J. (2011). Volatility forecast comparison using imperfect
    volatility proxies. J. Econometrics, 160(1), 246-256.

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-04-07
"""

import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

np.random.seed(42)
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
import yfinance as yf

print("Downloading SPY and VIX data...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Log returns (%)
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1)) * 100
spy = spy.dropna(subset=['ret'])

# Align VIX with SPY dates
vix_close = vix['Close'].reindex(spy.index).ffill()

# Squared returns as proxy for realized variance
spy['r2'] = spy['ret'] ** 2

print(f"SPY: {len(spy)} obs, {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"VIX aligned: {vix_close.notna().sum()} obs")

# ============================================================
# 2. Long-run component construction
# ============================================================

def compute_tau_rv(r2, window=22):
    """Rolling 22-day realized variance (average of r^2)."""
    tau = r2.rolling(window=window, min_periods=window).mean()
    return tau

def compute_tau_vix(vix_level):
    """VIX-based long-run component: (VIX/sqrt(252))^2 = daily implied variance."""
    tau = (vix_level / np.sqrt(252)) ** 2
    return tau

def compute_tau_ema(r2, halflife=22):
    """EMA of squared returns."""
    tau = r2.ewm(halflife=halflife, min_periods=22).mean()
    return tau

# Compute all tau variants
spy['tau_rv'] = compute_tau_rv(spy['r2'])
spy['tau_vix'] = compute_tau_vix(vix_close)
spy['tau_ema'] = compute_tau_ema(spy['r2'])

# Floor tau to avoid division by zero
for col in ['tau_rv', 'tau_vix', 'tau_ema']:
    spy[col] = spy[col].clip(lower=1e-6)

# Drop rows where all tau are available
spy = spy.dropna(subset=['tau_rv', 'tau_vix', 'tau_ema'])
print(f"After tau computation: {len(spy)} obs")

# ============================================================
# 3. IS/OOS Split
# ============================================================
IS_END = '2018-12-31'
OOS_START = '2019-01-02'

is_mask = spy.index <= IS_END
oos_mask = spy.index >= OOS_START

spy_is = spy[is_mask].copy()
spy_oos = spy[oos_mask].copy()

print(f"IS: {len(spy_is)} obs ({spy_is.index[0].date()} to {spy_is.index[-1].date()})")
print(f"OOS: {len(spy_oos)} obs ({spy_oos.index[0].date()} to {spy_oos.index[-1].date()})")

# ============================================================
# 4. GJR-GARCH estimation helpers
# ============================================================
from arch import arch_model

def fit_gjr(returns, dist='t'):
    """Fit GJR-GARCH(1,1) with Student-t errors."""
    am = arch_model(returns, vol='GARCH', p=1, o=1, q=1, dist=dist, mean='Zero')
    res = am.fit(disp='off', show_warning=False)
    return res

def gjr_recursion(params, returns, initial_var):
    """
    Run GJR-GARCH(1,1) recursion with fixed parameters.
    h[t] = omega + alpha*r2[t-1] + gamma*r2[t-1]*I(r[t-1]<0) + beta*h[t-1]
    """
    omega = params['omega']
    alpha = params['alpha[1]']
    gamma = params['gamma[1]']
    beta = params['beta[1]']

    n = len(returns)
    h = np.zeros(n)
    h[0] = initial_var

    r = returns.values if hasattr(returns, 'values') else returns

    for t in range(1, n):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * indicator + beta * h[t-1]
        h[t] = max(h[t], 1e-8)

    return h

# ============================================================
# 5. Model estimation and OOS forecasting
# ============================================================

results = {}

# --- 5a. Baseline GJR-GARCH ---
print("\n=== Baseline GJR-GARCH ===")
res_gjr = fit_gjr(spy_is['ret'])
print(f"  Convergence: {res_gjr.convergence_flag == 0}")
params_gjr = res_gjr.params
print(f"  omega={params_gjr['omega']:.6f}, alpha={params_gjr['alpha[1]']:.6f}, "
      f"gamma={params_gjr['gamma[1]']:.6f}, beta={params_gjr['beta[1]']:.6f}")
persistence = params_gjr['alpha[1]'] + params_gjr['gamma[1]']/2 + params_gjr['beta[1]']
print(f"  Persistence: {persistence:.4f}")

# OOS recursion for baseline
all_ret = spy['ret'].values
is_n = len(spy_is)
oos_n = len(spy_oos)

# Initial variance from IS fitted values
initial_var_gjr = res_gjr.conditional_volatility.iloc[-1] ** 2

# Run recursion on full OOS period
oos_h_gjr = gjr_recursion(params_gjr, spy_oos['ret'], initial_var_gjr)
results['GJR'] = {
    'forecast': oos_h_gjr,
    'params': {k: float(v) for k, v in params_gjr.items()},
    'persistence': float(persistence)
}

# --- 5b. MF2 variants ---
tau_variants = {
    'MF2-RV': 'tau_rv',
    'MF2-VIX': 'tau_vix',
    'MF2-EMA': 'tau_ema'
}

for name, tau_col in tau_variants.items():
    print(f"\n=== {name} ===")

    # Standardize IS returns by long-run component
    tau_is = spy_is[tau_col].values
    r_tilde_is = spy_is['ret'].values / np.sqrt(tau_is)

    # Fit GJR on standardized returns
    r_tilde_series = pd.Series(r_tilde_is, index=spy_is.index)
    res_mf2 = fit_gjr(r_tilde_series)
    params_mf2 = res_mf2.params
    print(f"  Convergence: {res_mf2.convergence_flag == 0}")
    print(f"  omega={params_mf2['omega']:.6f}, alpha={params_mf2['alpha[1]']:.6f}, "
          f"gamma={params_mf2['gamma[1]']:.6f}, beta={params_mf2['beta[1]']:.6f}")
    p_mf2 = params_mf2['alpha[1]'] + params_mf2['gamma[1]']/2 + params_mf2['beta[1]']
    print(f"  Persistence (short-run): {p_mf2:.4f}")

    # OOS: standardize returns by tau, then run GJR recursion on standardized returns
    tau_oos = spy_oos[tau_col].values
    r_tilde_oos = spy_oos['ret'].values / np.sqrt(tau_oos)

    initial_var_mf2 = res_mf2.conditional_volatility.iloc[-1] ** 2
    r_tilde_series_oos = pd.Series(r_tilde_oos, index=spy_oos.index)
    oos_g = gjr_recursion(params_mf2, r_tilde_series_oos, initial_var_mf2)

    # Final forecast: sigma2 = tau * g
    oos_h_mf2 = tau_oos * oos_g

    results[name] = {
        'forecast': oos_h_mf2,
        'params': {k: float(v) for k, v in params_mf2.items()},
        'persistence_short': float(p_mf2),
        'tau_col': tau_col
    }

# ============================================================
# 6. Evaluation
# ============================================================
print("\n" + "="*60)
print("OOS EVALUATION")
print("="*60)

r2_oos = spy_oos['r2'].values
ret_oos = spy_oos['ret'].values

def qlike(actual, forecast):
    """QLIKE loss: log(h) + r2/h (Patton 2011, proxy-robust)."""
    h = np.maximum(forecast, 1e-8)
    return np.mean(np.log(h) + actual / h)

def mse(actual, forecast):
    """MSE loss."""
    return np.mean((actual - forecast) ** 2)

def mz_regression(actual, forecast):
    """Mincer-Zarnowitz regression: r2 = a + b*h + e."""
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coefs, _, _, _ = lstsq(X, actual, rcond=None)
    y_hat = X @ coefs
    ss_res = np.sum((actual - y_hat) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r2_score = 1 - ss_res / ss_tot
    return {'intercept': float(coefs[0]), 'slope': float(coefs[1]), 'R2': float(r2_score)}

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided)."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return {'t_stat': 0.0, 'p_value': 1.0}

    t_stat = d_bar / np.sqrt(var_d)
    from scipy import stats
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return {'t_stat': float(t_stat), 'p_value': float(p_value)}

# Compute losses
model_names = ['GJR', 'MF2-RV', 'MF2-VIX', 'MF2-EMA']
losses_qlike = {}
losses_mse = {}

print(f"\n{'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MZ-R2':>8} {'MZ-slope':>10}")
print("-" * 55)

eval_results = {}
for name in model_names:
    h = results[name]['forecast']
    q = qlike(r2_oos, h)
    m = mse(r2_oos, h)
    mz = mz_regression(r2_oos, h)

    losses_qlike[name] = np.log(np.maximum(h, 1e-8)) + r2_oos / np.maximum(h, 1e-8)
    losses_mse[name] = (r2_oos - h) ** 2

    print(f"{name:<12} {q:>10.4f} {m:>12.4f} {mz['R2']:>8.4f} {mz['slope']:>10.4f}")

    eval_results[name] = {
        'QLIKE': float(q),
        'MSE': float(m),
        'MZ_R2': mz['R2'],
        'MZ_intercept': mz['intercept'],
        'MZ_slope': mz['slope']
    }

# DM tests (all pairs, QLIKE-based)
print(f"\n{'Pair':<25} {'DM-stat':>10} {'p-value':>10} {'Harvey |t|>3':>14}")
print("-" * 62)

dm_results = {}
for i, m1 in enumerate(model_names):
    for m2 in model_names[i+1:]:
        dm = dm_test(losses_qlike[m1], losses_qlike[m2])
        pair = f"{m1} vs {m2}"
        sig = "YES" if abs(dm['t_stat']) > 3.0 else "no"
        print(f"{pair:<25} {dm['t_stat']:>10.3f} {dm['p_value']:>10.4f} {sig:>14}")
        dm_results[pair] = dm

# ============================================================
# 7. VaR Backtesting
# ============================================================
print("\n" + "="*60)
print("VaR BACKTESTING")
print("="*60)

from scipy import stats as sp_stats

def var_backtest(returns, forecast_var, alpha=0.05, dist='t', df=5):
    """
    VaR backtesting with Kupiec and Christoffersen tests.
    VaR = mu + sigma * z_alpha (with Student-t scale correction)
    """
    sigma = np.sqrt(np.maximum(forecast_var, 1e-8))

    if dist == 't':
        scale = np.sqrt((df - 2) / df)
        z = sp_stats.t.ppf(alpha, df) * scale
    else:
        z = sp_stats.norm.ppf(alpha)

    var_level = z * sigma  # negative number
    violations = returns < var_level
    n_viol = violations.sum()
    n_total = len(returns)
    viol_rate = n_viol / n_total

    # Kupiec unconditional coverage test
    p_hat = viol_rate
    if p_hat == 0 or p_hat == 1:
        kupiec_stat = 0.0
        kupiec_p = 1.0
    else:
        lr = -2 * (n_total * np.log(1 - alpha) + 0 * np.log(alpha) -
                    (n_total - n_viol) * np.log(1 - p_hat) - n_viol * np.log(p_hat))
        # Correct formula
        lr = -2 * ((n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)) +
                    n_viol * np.log(alpha / p_hat))
        kupiec_stat = float(lr)
        kupiec_p = float(1 - sp_stats.chi2.cdf(abs(lr), 1))

    # Christoffersen independence test
    # Count transitions
    v = violations.astype(int)
    n00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    n01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    n10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    n11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

    if (n00 + n01) > 0 and (n10 + n11) > 0 and n01 > 0 and n10 > 0:
        pi01 = n01 / (n00 + n01)
        pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
        pi = (n01 + n11) / (n00 + n01 + n10 + n11)

        if pi11 > 0 and pi11 < 1 and pi01 > 0 and pi01 < 1:
            lr_ind = -2 * (
                (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
                - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
                - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
            )
            christ_stat = float(lr_ind)
            christ_p = float(1 - sp_stats.chi2.cdf(abs(lr_ind), 1))
        else:
            christ_stat = 0.0
            christ_p = 1.0
    else:
        christ_stat = 0.0
        christ_p = 1.0

    return {
        'alpha': alpha,
        'n_violations': int(n_viol),
        'n_total': int(n_total),
        'violation_rate': float(viol_rate),
        'expected_rate': float(alpha),
        'kupiec_stat': kupiec_stat,
        'kupiec_p': kupiec_p,
        'christoffersen_stat': christ_stat,
        'christoffersen_p': christ_p
    }

# Get df from baseline GJR
df_t = float(params_gjr.get('nu', 5.0))

var_results = {}
for alpha_level in [0.01, 0.05]:
    print(f"\nVaR {int(alpha_level*100)}%:")
    print(f"{'Model':<12} {'Violations':>11} {'Rate':>8} {'Expected':>9} {'Kupiec-p':>10} {'Christ-p':>10}")
    print("-" * 63)

    for name in model_names:
        h = results[name]['forecast']
        vb = var_backtest(ret_oos, h, alpha=alpha_level, dist='t', df=df_t)
        key = f"{name}_VaR{int(alpha_level*100)}"
        var_results[key] = vb
        print(f"{name:<12} {vb['n_violations']:>5}/{vb['n_total']:<5} "
              f"{vb['violation_rate']:>8.4f} {vb['expected_rate']:>9.4f} "
              f"{vb['kupiec_p']:>10.4f} {vb['christoffersen_p']:>10.4f}")

# ============================================================
# 8. Plots
# ============================================================

# --- 8a. Volatility Components ---
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

# Long-run components (IS + OOS)
for ax, (name, col) in zip(axes, [('RV-22d', 'tau_rv'), ('VIX-implied', 'tau_vix'), ('EMA-22d', 'tau_ema')]):
    tau_vals = np.sqrt(spy[col].values) * np.sqrt(252)  # annualized vol
    dates_all = spy.index.to_numpy()
    ax.plot(dates_all, tau_vals, color='steelblue', alpha=0.7, linewidth=0.8)
    ax.axvline(pd.Timestamp(IS_END), color='red', linestyle='--', alpha=0.5, label='IS/OOS split')
    ax.set_ylabel('Ann. Vol (%)')
    ax.set_title(f'Long-run component: {name}')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('experiments/k970/k970_volatility_components.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nSaved: k970_volatility_components.png")

# --- 8b. OOS Comparison ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# Top: forecasts vs realized
ax = axes[0]
dates_oos = spy_oos.index.to_numpy()
ax.plot(dates_oos, np.sqrt(r2_oos) * np.sqrt(252), color='gray', alpha=0.3,
        linewidth=0.5, label='|r| (ann.)')
for name, color in zip(model_names, ['black', 'blue', 'red', 'green']):
    h = results[name]['forecast']
    ax.plot(dates_oos, np.sqrt(h) * np.sqrt(252), color=color,
            alpha=0.7, linewidth=0.8, label=name)
ax.set_ylabel('Annualized Vol (%)')
ax.set_title('OOS Volatility Forecasts (2019-2026)')
ax.legend(loc='upper right', fontsize=8)
ax.grid(True, alpha=0.3)

# Bottom: cumulative QLIKE difference (MF2 vs GJR)
ax = axes[1]
dates_oos_np = spy_oos.index.to_numpy()
for name, color in zip(['MF2-RV', 'MF2-VIX', 'MF2-EMA'], ['blue', 'red', 'green']):
    diff = losses_qlike['GJR'] - losses_qlike[name]  # positive = MF2 better
    cum_diff = np.cumsum(diff)
    ax.plot(dates_oos_np, cum_diff, color=color, linewidth=1.0, label=f'{name} gain')
ax.axhline(0, color='black', linestyle='--', alpha=0.3)
ax.set_ylabel('Cumulative QLIKE gain over GJR')
ax.set_title('Cumulative QLIKE Advantage of MF2 over GJR (positive = MF2 better)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('experiments/k970/k970_oos_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved: k970_oos_comparison.png")

# ============================================================
# 9. Save Results
# ============================================================

# Find best model
best_model = min(eval_results, key=lambda x: eval_results[x]['QLIKE'])

output = {
    'experiment_id': 'K970',
    'title': 'MF2-GARCH: Mixed-Frequency Squared GARCH',
    'method': 'Conrad & Engle (2025) MF2-GARCH simplified implementation',
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{spy.index[0].date()} to {spy.index[-1].date()}",
    'sample_sizes': {
        'total': len(spy),
        'IS': len(spy_is),
        'OOS': len(spy_oos)
    },
    'IS_period': f"{spy_is.index[0].date()} to {spy_is.index[-1].date()}",
    'OOS_period': f"{spy_oos.index[0].date()} to {spy_oos.index[-1].date()}",
    'models': {},
    'evaluation': eval_results,
    'dm_tests': dm_results,
    'var_backtesting': var_results,
    'best_model': best_model,
    'conclusion': '',
    'references': [
        'Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous long-run dynamics. J. Applied Econometrics.',
        'Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. Review of Economics and Statistics.',
        'Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. J. Econometrics, 160(1), 246-256.',
        'Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and the cross-section of expected returns. Review of Financial Studies.'
    ],
    'seed': 42,
    'timestamp': datetime.now().isoformat()
}

# Model details
for name in model_names:
    info = {'params': results[name]['params']}
    if 'persistence' in results[name]:
        info['persistence'] = results[name]['persistence']
    if 'persistence_short' in results[name]:
        info['persistence_short'] = results[name]['persistence_short']
    output['models'][name] = info

# Generate conclusion
qlike_vals = {m: eval_results[m]['QLIKE'] for m in model_names}
gjr_qlike = qlike_vals['GJR']
improvements = {m: (gjr_qlike - q) / gjr_qlike * 100 for m, q in qlike_vals.items() if m != 'GJR'}

conclusion_parts = [
    f"Best model by QLIKE: {best_model} ({eval_results[best_model]['QLIKE']:.4f})",
    f"GJR baseline QLIKE: {gjr_qlike:.4f}",
]
for m, imp in improvements.items():
    direction = "improvement" if imp > 0 else "worse"
    conclusion_parts.append(f"{m}: {abs(imp):.2f}% {direction} over GJR")

# Check DM significance
sig_pairs = [p for p, v in dm_results.items() if abs(v['t_stat']) > 3.0]
if sig_pairs:
    conclusion_parts.append(f"Significant DM pairs (|t|>3.0): {', '.join(sig_pairs)}")
else:
    conclusion_parts.append("No pairs pass Harvey (2016) |t|>3.0 threshold")

output['conclusion'] = '; '.join(conclusion_parts)
output['qlike_improvements_pct'] = improvements

with open('experiments/k970/k970_mf2_garch_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n" + "="*60)
print("CONCLUSION")
print("="*60)
for part in conclusion_parts:
    print(f"  {part}")

print("\nResults saved to experiments/k970/k970_mf2_garch_results.json")
print("Done.")
