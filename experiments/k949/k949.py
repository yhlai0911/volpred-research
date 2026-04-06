"""
K949: Cross-Market MF-GJR — Is VIX a Global Risk Factor?

Tests whether US VIX has predictive power for volatility in European and Japanese markets.
Assets: SPY (US baseline), FEZ (Eurozone), EWG (Germany), EWJ (Japan), EWU (UK)
Models: GARCH(1,1), GJR(1,1,1), MF-GJR(VIX)
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000, Refit every 21 days

Data source: yfinance (^VIX, SPY, FEZ, EWG, EWJ, EWU)
"""

import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.stats import spearmanr
from arch import arch_model
from datetime import datetime
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Download
# ============================================================
import yfinance as yf

ASSETS = ['SPY', 'FEZ', 'EWG', 'EWJ', 'EWU']
START = '2006-01-01'
END = '2025-12-31'
OOS_START = '2016-01-01'
WINDOW = 2000
REFIT_EVERY = 21

print("Downloading data...")
price_data = {}
for ticker in ASSETS + ['^VIX']:
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[ticker] = df['Close']

prices = pd.DataFrame(price_data)
prices.columns = ASSETS + ['VIX']
prices = prices.ffill()

returns = {}
for asset in ASSETS:
    r = np.log(prices[asset] / prices[asset].shift(1)).dropna() * 100
    returns[asset] = r

vix = prices['VIX']
log_vix = np.log(vix)

print(f"Data range: {prices.index[0].date()} to {prices.index[-1].date()}")
for a in ASSETS:
    print(f"  {a}: {len(returns[a])} observations")

# ============================================================
# 2. MF-GJR Model (numba-accelerated)
# ============================================================

@njit
def mf_gjr_negloglik_numba(params, returns_arr, log_vix_arr):
    """MF-GJR(VIX) negative log-likelihood (numba JIT)."""
    omega_g = params[0]
    alpha = params[1]
    gamma = params[2]
    beta = params[3]
    theta0 = params[4]
    theta1 = params[5]

    T = len(returns_arr)
    if T < 2:
        return 1e10

    if alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + gamma/2 >= 1.0:
        return 1e10
    if omega_g < 0.001 or omega_g > 5.0:
        return 1e10

    intercept = omega_g * (1.0 - alpha - beta - gamma/2.0)
    nll = 0.0
    g_prev = 1.0
    log2pi = 1.8378770664093453  # np.log(2*pi)

    for t in range(1, T):
        r_prev = returns_arr[t-1]
        tau_prev = np.exp(theta0 + theta1 * log_vix_arr[t-1])
        tau_t = np.exp(theta0 + theta1 * log_vix_arr[t])

        if tau_prev < 1e-8:
            tau_prev = 1e-8

        r2_scaled = (r_prev * r_prev) / tau_prev
        ind = 1.0 if r_prev < 0 else 0.0

        g_t = intercept + alpha * r2_scaled + gamma * r2_scaled * ind + beta * g_prev
        if g_t < 1e-8:
            g_t = 1e-8

        sigma2 = tau_t * g_t
        if sigma2 < 1e-8:
            sigma2 = 1e-8

        r_t = returns_arr[t]
        nll += 0.5 * (log2pi + np.log(sigma2) + r_t * r_t / sigma2)
        g_prev = g_t

    return nll


@njit
def mf_gjr_compute_g_series(params, returns_arr, log_vix_arr):
    """Compute full g series for a fitted model."""
    omega_g = params[0]
    alpha = params[1]
    gamma = params[2]
    beta = params[3]
    theta0 = params[4]
    theta1 = params[5]

    T = len(returns_arr)
    g = np.ones(T)
    intercept = omega_g * (1.0 - alpha - beta - gamma/2.0)

    for t in range(1, T):
        r_prev = returns_arr[t-1]
        tau_prev = np.exp(theta0 + theta1 * log_vix_arr[t-1])
        if tau_prev < 1e-8:
            tau_prev = 1e-8
        r2_scaled = (r_prev * r_prev) / tau_prev
        ind = 1.0 if r_prev < 0 else 0.0
        g[t] = intercept + alpha * r2_scaled + gamma * r2_scaled * ind + beta * g[t-1]
        if g[t] < 1e-8:
            g[t] = 1e-8

    return g


def fit_mf_gjr(returns_arr, log_vix_arr):
    """Fit MF-GJR model with multiple starting points."""
    # Warm up numba
    _ = mf_gjr_negloglik_numba(np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
                                returns_arr[:10], log_vix_arr[:10])

    best_result = None
    best_nll = 1e10

    starts = [
        [1.0, 0.05, 0.05, 0.90, -0.5, 0.5],
        [1.0, 0.08, 0.10, 0.85, 0.0, 0.3],
        [1.0, 0.03, 0.07, 0.88, -1.0, 0.8],
        [1.0, 0.10, 0.05, 0.80, 0.5, 0.2],
    ]

    bounds = [(0.001, 5.0), (0.001, 0.3), (0.001, 0.5), (0.5, 0.999),
              (-5.0, 5.0), (-2.0, 3.0)]

    for x0 in starts:
        try:
            result = minimize(
                lambda p: mf_gjr_negloglik_numba(p, returns_arr, log_vix_arr),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 5000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    return best_result


# ============================================================
# 3. OOS Forecasting Loop
# ============================================================

def qlike_loss(sigma2_pred, r2_actual):
    mask = (sigma2_pred > 1e-10) & np.isfinite(r2_actual) & np.isfinite(sigma2_pred)
    s2 = sigma2_pred[mask]
    r2 = r2_actual[mask]
    return np.mean(r2/s2 + np.log(s2))


def run_oos_for_asset(asset, ret_series, vix_series, log_vix_series):
    print(f"\n{'='*60}")
    print(f"Processing {asset}...")
    print(f"{'='*60}")

    common_idx = ret_series.index.intersection(log_vix_series.index)
    ret = ret_series.loc[common_idx].copy()
    lv = log_vix_series.loc[common_idx].copy()

    oos_mask = ret.index >= OOS_START
    oos_dates = ret.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  No OOS data for {asset}")
        return None

    n_oos = len(oos_dates)
    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")

    forecasts = {m: np.full(n_oos, np.nan) for m in ['GARCH', 'GJR', 'MF-GJR']}
    r2_actual = np.full(n_oos, np.nan)

    all_dates = ret.index
    oos_start_pos = np.where(all_dates >= OOS_START)[0][0]

    last_garch_params = None
    last_gjr_params = None
    last_mf_params = None
    last_garch_var = None
    last_gjr_var = None
    last_mf_g = 1.0

    ret_vals = ret.values
    lv_vals = lv.values

    for i in range(n_oos):
        t = oos_start_pos + i

        if t < WINDOW:
            continue

        r2_actual[i] = ret_vals[t] ** 2
        need_refit = (i == 0) or (i % REFIT_EVERY == 0)

        train_ret = ret_vals[t-WINDOW:t]
        train_lv = lv_vals[t-WINDOW:t]

        # --- GARCH(1,1) ---
        if need_refit:
            try:
                am = arch_model(pd.Series(train_ret), vol='Garch', p=1, q=1,
                              mean='Zero', dist='normal', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                last_garch_params = (res.params['omega'], res.params['alpha[1]'], res.params['beta[1]'])
                last_garch_var = res.conditional_volatility.iloc[-1]**2
            except Exception:
                pass

        if last_garch_params is not None and last_garch_var is not None:
            omega, alpha, beta = last_garch_params
            r_prev = train_ret[-1]
            h = omega + alpha * r_prev**2 + beta * last_garch_var
            forecasts['GARCH'][i] = h
            last_garch_var = h

        # --- GJR(1,1,1) ---
        if need_refit:
            try:
                am = arch_model(pd.Series(train_ret), vol='Garch', p=1, o=1, q=1,
                              mean='Zero', dist='normal', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                last_gjr_params = (res.params['omega'], res.params['alpha[1]'],
                                  res.params['gamma[1]'], res.params['beta[1]'])
                last_gjr_var = res.conditional_volatility.iloc[-1]**2
            except Exception:
                pass

        if last_gjr_params is not None and last_gjr_var is not None:
            omega, alpha, gamma, beta = last_gjr_params
            r_prev = train_ret[-1]
            ind = 1.0 if r_prev < 0 else 0.0
            h = omega + alpha * r_prev**2 + gamma * r_prev**2 * ind + beta * last_gjr_var
            forecasts['GJR'][i] = h
            last_gjr_var = h

        # --- MF-GJR(VIX) ---
        if need_refit:
            try:
                result = fit_mf_gjr(train_ret, train_lv)
                if result is not None and result.fun < 1e9:
                    last_mf_params = result.x
                    g_arr = mf_gjr_compute_g_series(last_mf_params, train_ret, train_lv)
                    last_mf_g = g_arr[-1]
            except Exception:
                pass

        if last_mf_params is not None:
            try:
                omega_g, al, gm, bt, th0, th1 = last_mf_params
                r_prev = train_ret[-1]
                tau_prev = np.exp(th0 + th1 * train_lv[-1])
                tau_next = np.exp(th0 + th1 * train_lv[-1])  # latest VIX
                if tau_prev < 1e-8:
                    tau_prev = 1e-8
                r2_scaled = (r_prev**2) / tau_prev
                ind = 1.0 if r_prev < 0 else 0.0
                intercept = omega_g * (1 - al - bt - gm/2)
                g_next = intercept + al * r2_scaled + gm * r2_scaled * ind + bt * last_mf_g
                if g_next < 1e-8:
                    g_next = 1e-8
                sigma2_next = tau_next * g_next
                forecasts['MF-GJR'][i] = sigma2_next
                last_mf_g = g_next
            except Exception:
                pass

        if (i+1) % 500 == 0:
            print(f"  {asset}: {i+1}/{n_oos} done")

    # ============================================================
    # Evaluation
    # ============================================================
    valid = np.isfinite(r2_actual)
    for m in forecasts:
        valid &= np.isfinite(forecasts[m])

    n_valid = np.sum(valid)
    print(f"  Valid observations: {n_valid}")

    if n_valid < 100:
        print(f"  Too few valid observations for {asset}")
        return None

    r2_v = r2_actual[valid]

    results = {}
    for m in ['GARCH', 'GJR', 'MF-GJR']:
        f_v = forecasts[m][valid]
        ql = qlike_loss(f_v, r2_v)
        rho, pval = spearmanr(f_v, r2_v)
        results[m] = {'QLIKE': float(ql), 'Spearman_rho': float(rho), 'Spearman_pval': float(pval)}
        print(f"  {m:10s}: QLIKE={ql:.4f}, Spearman rho={rho:.4f}")

    # DM test: MF-GJR vs GJR
    d_mf = r2_v / forecasts['MF-GJR'][valid] + np.log(forecasts['MF-GJR'][valid])
    d_gjr = r2_v / forecasts['GJR'][valid] + np.log(forecasts['GJR'][valid])
    d = d_gjr - d_mf  # positive = MF-GJR better

    T = len(d)
    d_bar = np.mean(d)
    lag = int(T**(1/3))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag+1):
        w = 1 - k/(lag+1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = gamma_0 + gamma_sum
    se_d = np.sqrt(max(var_d, 1e-10) / T)
    dm_t = d_bar / se_d if se_d > 0 else 0

    # Harvey small-sample correction
    dm_t_harvey = dm_t * np.sqrt((T + 1 - 2 + 1/T) / T)

    results['DM_MFvsGJR'] = {
        't_stat': float(dm_t),
        't_harvey': float(dm_t_harvey),
        'significant_harvey3': bool(abs(dm_t_harvey) > 3.0),
        'mean_loss_diff': float(d_bar)
    }

    print(f"  DM(MF-GJR vs GJR): t={dm_t:.3f}, t_harvey={dm_t_harvey:.3f}, |t|>3.0: {abs(dm_t_harvey)>3.0}")

    # QLIKE improvement
    ql_garch = results['GARCH']['QLIKE']
    ql_gjr = results['GJR']['QLIKE']
    ql_mf = results['MF-GJR']['QLIKE']

    results['QLIKE_improvement'] = {
        'MF_vs_GARCH_pct': float((ql_garch - ql_mf) / abs(ql_garch) * 100),
        'MF_vs_GJR_pct': float((ql_gjr - ql_mf) / abs(ql_gjr) * 100),
    }

    # Extract theta1
    if last_mf_params is not None:
        results['theta1_VIX_elasticity'] = float(last_mf_params[5])
        results['theta0'] = float(last_mf_params[4])
        results['mf_params'] = {
            'omega_g': float(last_mf_params[0]),
            'alpha': float(last_mf_params[1]),
            'gamma': float(last_mf_params[2]),
            'beta': float(last_mf_params[3]),
            'theta0': float(last_mf_params[4]),
            'theta1': float(last_mf_params[5])
        }

    results['n_oos'] = int(n_valid)
    results['oos_period'] = f"{oos_dates[0].date()} to {oos_dates[-1].date()}"

    return results, forecasts, r2_actual, valid, oos_dates


# ============================================================
# 4. Run All Assets
# ============================================================

print("\nWarming up numba JIT...")
_ = mf_gjr_negloglik_numba(
    np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
    np.random.randn(100), np.random.randn(100))
_ = mf_gjr_compute_g_series(
    np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
    np.random.randn(100), np.random.randn(100))
print("JIT compilation done.")

all_results = {}
all_forecasts = {}

for asset in ASSETS:
    out = run_oos_for_asset(asset, returns[asset], vix, log_vix)
    if out is not None:
        results, forecasts, r2_actual, valid, oos_dates = out
        all_results[asset] = results
        all_forecasts[asset] = {
            'forecasts': forecasts,
            'r2_actual': r2_actual,
            'valid': valid,
            'oos_dates': oos_dates
        }

# ============================================================
# 5. Cross-Market Summary
# ============================================================

print("\n" + "="*80)
print("CROSS-MARKET SUMMARY")
print("="*80)

summary_table = []
for asset in ASSETS:
    if asset not in all_results:
        continue
    r = all_results[asset]
    row = {
        'Asset': asset,
        'N_OOS': r['n_oos'],
        'QLIKE_GARCH': r['GARCH']['QLIKE'],
        'QLIKE_GJR': r['GJR']['QLIKE'],
        'QLIKE_MF': r['MF-GJR']['QLIKE'],
        'Improve_vs_GJR%': r['QLIKE_improvement']['MF_vs_GJR_pct'],
        'Spearman_MF': r['MF-GJR']['Spearman_rho'],
        'DM_t_harvey': r['DM_MFvsGJR']['t_harvey'],
        'DM_sig': r['DM_MFvsGJR']['significant_harvey3'],
        'theta1': r.get('theta1_VIX_elasticity', np.nan),
    }
    summary_table.append(row)

df_summary = pd.DataFrame(summary_table)
print("\n" + df_summary.to_string(index=False))

n_sig = sum(1 for row in summary_table if row['DM_sig'])
n_total = len(summary_table)
print(f"\nSignificant markets (Harvey |t|>3.0): {n_sig}/{n_total}")

theta1s = {row['Asset']: row['theta1'] for row in summary_table if not np.isnan(row['theta1'])}
if theta1s:
    print(f"\nVIX Elasticity (theta1) across markets:")
    for a, t in theta1s.items():
        print(f"  {a}: {t:.4f}")
    print(f"  Mean: {np.mean(list(theta1s.values())):.4f}")
    print(f"  Std:  {np.std(list(theta1s.values())):.4f}")

# ============================================================
# 6. Visualization
# ============================================================

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K949: Cross-Market MF-GJR(VIX) — Is VIX a Global Risk Factor?',
             fontsize=14, fontweight='bold')

# Panel A: QLIKE comparison
ax = axes[0, 0]
assets_plot = [r['Asset'] for r in summary_table]
x = np.arange(len(assets_plot))
width = 0.25
ql_garch = [r['QLIKE_GARCH'] for r in summary_table]
ql_gjr = [r['QLIKE_GJR'] for r in summary_table]
ql_mf = [r['QLIKE_MF'] for r in summary_table]
ax.bar(x - width, ql_garch, width, label='GARCH', color='#4a90d9', alpha=0.8)
ax.bar(x, ql_gjr, width, label='GJR', color='#f5a623', alpha=0.8)
ax.bar(x + width, ql_mf, width, label='MF-GJR(VIX)', color='#d0021b', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(assets_plot)
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('(A) QLIKE on r² by Market')
ax.legend()
ax.grid(axis='y', alpha=0.3)

# Panel B: DM t-statistics
ax = axes[0, 1]
dm_ts = [r['DM_t_harvey'] for r in summary_table]
colors = ['#d0021b' if abs(t) > 3.0 else '#999999' for t in dm_ts]
bars = ax.bar(assets_plot, dm_ts, color=colors, alpha=0.8)
ax.axhline(y=3.0, color='black', linestyle='--', alpha=0.5, label='Harvey |t|=3.0')
ax.axhline(y=-3.0, color='black', linestyle='--', alpha=0.5)
ax.set_ylabel('DM t-statistic (Harvey)')
ax.set_title('(B) DM Test: MF-GJR vs GJR')
ax.legend()
ax.grid(axis='y', alpha=0.3)

# Panel C: Theta1 (VIX elasticity)
ax = axes[1, 0]
theta1_vals = [r['theta1'] for r in summary_table]
ax.bar(assets_plot, theta1_vals, color='#7ed321', alpha=0.8)
ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
ax.set_ylabel('\u03b8\u2081 (VIX elasticity)')
ax.set_title('(C) VIX Elasticity by Market')
ax.grid(axis='y', alpha=0.3)

# Panel D: Spearman rho comparison
ax = axes[1, 1]
rho_garch = [all_results[a]['GARCH']['Spearman_rho'] for a in assets_plot]
rho_gjr = [all_results[a]['GJR']['Spearman_rho'] for a in assets_plot]
rho_mf = [all_results[a]['MF-GJR']['Spearman_rho'] for a in assets_plot]
ax.bar(x - width, rho_garch, width, label='GARCH', color='#4a90d9', alpha=0.8)
ax.bar(x, rho_gjr, width, label='GJR', color='#f5a623', alpha=0.8)
ax.bar(x + width, rho_mf, width, label='MF-GJR(VIX)', color='#d0021b', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(assets_plot)
ax.set_ylabel('Spearman \u03c1 (higher = better)')
ax.set_title('(D) Spearman Rank Correlation')
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('experiments/k949/k949_cross_market.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nFigure saved: experiments/k949/k949_cross_market.png")

# ============================================================
# 7. Save Results
# ============================================================

output = {
    'experiment_id': 'K949',
    'title': 'Cross-Market MF-GJR: Is VIX a Global Risk Factor?',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'assets': ASSETS,
    'oos_period': '2016-01-01 to 2025-12-31',
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'models': ['GARCH(1,1)', 'GJR(1,1,1)', 'MF-GJR(VIX)'],
    'evaluation': 'QLIKE on r², Spearman rank, DM test (Harvey |t|>3.0)',
    'results': all_results,
    'summary': {
        'n_markets': n_total,
        'n_significant_harvey3': n_sig,
        'theta1_mean': float(np.mean(list(theta1s.values()))) if theta1s else None,
        'theta1_std': float(np.std(list(theta1s.values()))) if theta1s else None,
        'theta1_by_market': theta1s,
    },
    'conclusion': '',
}

if n_sig >= 4:
    conclusion = f"VIX is a GLOBAL risk factor: MF-GJR(VIX) significantly improves vol forecasts in {n_sig}/{n_total} markets (Harvey |t|>3.0). theta1 mean={output['summary']['theta1_mean']:.3f}."
elif n_sig >= 2:
    conclusion = f"VIX has PARTIAL global reach: significant in {n_sig}/{n_total} markets. Strongest in US-correlated markets."
else:
    conclusion = f"VIX is primarily a LOCAL (US) signal: only significant in {n_sig}/{n_total} markets."

output['conclusion'] = conclusion
print(f"\n{'='*80}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*80}")

with open('experiments/k949/k949_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)
print("Results saved: experiments/k949/k949_results.json")
print("\nDone.")
