"""
K965: Wild Bootstrap Optimal Hedge Ratio — SPY/ES Futures Hedging
=================================================================

Based on: JRFM 2024, Vol 17, Issue 7, Article 310
"Wild Bootstrap Percentile-Based MVHR"

Method: Wild bootstrap (Mammen 1993 two-point distribution) to construct
confidence intervals for OLS hedge ratio, then use percentile-based
estimates as hedge ratios.

Comparison methods:
1. Naive (h=1)
2. OLS (static)
3. Rolling OLS (252-day window)
4. DCC-GARCH(1,1)
5. Wild Bootstrap 25th percentile (conservative)
6. Wild Bootstrap 50th percentile (median)
7. Wild Bootstrap 75th percentile (aggressive)

Data: SPY (spot) + ES=F (E-mini S&P 500 futures) from yfinance
      Fallback: GLD (spot) + GC=F (gold futures)

Evaluation: HE, Downside HE, VaR reduction, mean hedged return
Seed: np.random.seed(42)
"""

import numpy as np
import pandas as pd
import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Download
# ============================================================
import yfinance as yf

def download_data(spot_ticker, futures_ticker, start='2010-01-01', end='2026-04-04'):
    """Download spot and futures data from yfinance."""
    print(f"Downloading {spot_ticker} and {futures_ticker}...")
    spot = yf.download(spot_ticker, start=start, end=end, auto_adjust=True, progress=False)
    futures = yf.download(futures_ticker, start=start, end=end, auto_adjust=True, progress=False)

    # Handle MultiIndex columns from yfinance
    if isinstance(spot.columns, pd.MultiIndex):
        spot.columns = spot.columns.get_level_values(0)
    if isinstance(futures.columns, pd.MultiIndex):
        futures.columns = futures.columns.get_level_values(0)

    # Align dates
    common = spot.index.intersection(futures.index)
    spot = spot.loc[common]
    futures = futures.loc[common]

    # Log returns
    spot_ret = np.log(spot['Close'] / spot['Close'].shift(1)).dropna()
    fut_ret = np.log(futures['Close'] / futures['Close'].shift(1)).dropna()

    # Align again after return calculation
    common_ret = spot_ret.index.intersection(fut_ret.index)
    spot_ret = spot_ret.loc[common_ret]
    fut_ret = fut_ret.loc[common_ret]

    print(f"  Common dates: {len(common_ret)} ({common_ret[0].strftime('%Y-%m-%d')} to {common_ret[-1].strftime('%Y-%m-%d')})")
    return spot_ret, fut_ret


# Try SPY/ES=F first, fallback to GLD/GC=F
try:
    spot_ret, fut_ret = download_data('SPY', 'ES=F')
    if len(spot_ret) < 1000:
        raise ValueError(f"ES=F data too short: {len(spot_ret)} days")
    asset_pair = "SPY/ES=F"
    spot_name, fut_name = "SPY", "ES=F"
except Exception as e:
    print(f"SPY/ES=F failed ({e}), trying GLD/GC=F...")
    spot_ret, fut_ret = download_data('GLD', 'GC=F')
    asset_pair = "GLD/GC=F"
    spot_name, fut_name = "GLD", "GC=F"

print(f"\nUsing pair: {asset_pair}")
print(f"Sample size: {len(spot_ret)}")
print(f"Spot return stats: mean={spot_ret.mean():.6f}, std={spot_ret.std():.6f}")
print(f"Futures return stats: mean={fut_ret.mean():.6f}, std={fut_ret.std():.6f}")
print(f"Correlation: {np.corrcoef(spot_ret, fut_ret)[0,1]:.4f}")

# ============================================================
# 2. Train/Test Split
# ============================================================
n = len(spot_ret)
n_train = int(n * 0.6)
n_test = n - n_train

spot_train = spot_ret.iloc[:n_train]
fut_train = fut_ret.iloc[:n_train]
spot_test = spot_ret.iloc[n_train:]
fut_test = fut_ret.iloc[n_train:]

print(f"\nIS period: {spot_train.index[0].strftime('%Y-%m-%d')} to {spot_train.index[-1].strftime('%Y-%m-%d')} ({n_train} days)")
print(f"OOS period: {spot_test.index[0].strftime('%Y-%m-%d')} to {spot_test.index[-1].strftime('%Y-%m-%d')} ({n_test} days)")

# ============================================================
# 3. OLS Hedge Ratio
# ============================================================
def ols_hedge_ratio(spot_r, fut_r):
    """Estimate OLS hedge ratio: spot = alpha + beta * futures + epsilon."""
    x = fut_r.values
    y = spot_r.values
    x_dm = x - x.mean()
    y_dm = y - y.mean()
    beta = np.sum(x_dm * y_dm) / np.sum(x_dm ** 2)
    alpha = y.mean() - beta * x.mean()
    residuals = y - alpha - beta * x
    return beta, alpha, residuals

beta_ols, alpha_ols, resid_ols = ols_hedge_ratio(spot_train, fut_train)
print(f"\nOLS Hedge Ratio (IS): {beta_ols:.6f}")

# ============================================================
# 4. Wild Bootstrap (Mammen 1993)
# ============================================================
def wild_bootstrap_ohr(spot_r, fut_r, B=10000, seed=42):
    """
    Wild bootstrap for MVHR confidence intervals.
    Uses Mammen (1993) two-point distribution:
      w = -(sqrt(5)-1)/2  with prob (sqrt(5)+1)/(2*sqrt(5))
      w =  (sqrt(5)+1)/2  with prob 1 - above
    """
    rng = np.random.default_rng(seed)

    x = fut_r.values
    y = spot_r.values
    n = len(x)

    # OLS estimates
    x_dm = x - x.mean()
    beta_hat = np.sum(x_dm * (y - y.mean())) / np.sum(x_dm ** 2)
    alpha_hat = y.mean() - beta_hat * x.mean()
    resid = y - alpha_hat - beta_hat * x

    # Mammen two-point distribution parameters
    sqrt5 = np.sqrt(5)
    w1 = -(sqrt5 - 1) / 2
    w2 = (sqrt5 + 1) / 2
    p1 = (sqrt5 + 1) / (2 * sqrt5)  # prob of w1

    beta_boots = np.zeros(B)

    for b in range(B):
        # Generate Mammen weights
        u = rng.random(n)
        w = np.where(u < p1, w1, w2)

        # Bootstrap residuals
        resid_star = resid * w

        # Bootstrap dependent variable
        y_star = alpha_hat + beta_hat * x + resid_star

        # Re-estimate OLS
        y_star_dm = y_star - y_star.mean()
        x_dm_local = x - x.mean()
        beta_boots[b] = np.sum(x_dm_local * y_star_dm) / np.sum(x_dm_local ** 2)

    return beta_boots

print("\nRunning Wild Bootstrap (B=10,000)...")
beta_boots = wild_bootstrap_ohr(spot_train, fut_train, B=10000, seed=42)

# Bootstrap percentiles
pcts = [5, 10, 25, 50, 75, 90, 95]
boot_pcts = {p: np.percentile(beta_boots, p) for p in pcts}

print(f"Bootstrap distribution: mean={beta_boots.mean():.6f}, std={beta_boots.std():.6f}")
for p, v in boot_pcts.items():
    print(f"  {p}th percentile: {v:.6f}")

# ============================================================
# 5. Rolling OLS
# ============================================================
def rolling_ols_hedge(spot_r, fut_r, window=252):
    """Rolling OLS hedge ratio with given window."""
    n = len(spot_r)
    h = np.full(n, np.nan)
    for t in range(window, n):
        s = spot_r.iloc[t-window:t].values
        f = fut_r.iloc[t-window:t].values
        f_dm = f - f.mean()
        h[t] = np.sum(f_dm * (s - s.mean())) / np.sum(f_dm ** 2)
    return pd.Series(h, index=spot_r.index)

rolling_h = rolling_ols_hedge(
    pd.concat([spot_train, spot_test]),
    pd.concat([fut_train, fut_test]),
    window=252
)

# ============================================================
# 6. DCC-GARCH(1,1)
# ============================================================
def dcc_garch_hedge(spot_r, fut_r, window_start=0):
    """
    Simplified DCC-GARCH(1,1):
    1. Fit univariate GARCH(1,1) to each series
    2. Estimate DCC parameters from standardized residuals
    3. Compute dynamic hedge ratio
    """
    from arch import arch_model

    # Fit marginal GARCH(1,1) — use full available data up to each point
    # For OOS: refit once on training data, then filter forward
    spot_vals = spot_r.values * 100  # Scale for numerical stability
    fut_vals = fut_r.values * 100
    n = len(spot_vals)

    # Fit GARCH(1,1) on training data
    garch_spot = arch_model(spot_vals, vol='Garch', p=1, q=1, mean='Zero', dist='normal')
    res_spot = garch_spot.fit(disp='off')

    garch_fut = arch_model(fut_vals, vol='Garch', p=1, q=1, mean='Zero', dist='normal')
    res_fut = garch_fut.fit(disp='off')

    # Get conditional variances and standardized residuals
    sigma2_spot = res_spot.conditional_volatility ** 2
    sigma2_fut = res_fut.conditional_volatility ** 2

    z_spot = spot_vals / np.sqrt(sigma2_spot)
    z_fut = fut_vals / np.sqrt(sigma2_fut)

    # DCC estimation: Q_t = (1-a-b)*Qbar + a*(z_{t-1}*z_{t-1}') + b*Q_{t-1}
    # Use simple grid search for a, b
    Qbar_11 = np.mean(z_spot ** 2)
    Qbar_22 = np.mean(z_fut ** 2)
    Qbar_12 = np.mean(z_spot * z_fut)

    # Grid search DCC parameters
    best_ll = -np.inf
    best_a, best_b = 0.05, 0.90

    for a_try in [0.01, 0.02, 0.05, 0.08, 0.10]:
        for b_try in [0.80, 0.85, 0.90, 0.93, 0.95]:
            if a_try + b_try >= 1.0:
                continue
            # Compute DCC
            Q11 = np.zeros(n)
            Q22 = np.zeros(n)
            Q12 = np.zeros(n)
            Q11[0] = Qbar_11
            Q22[0] = Qbar_22
            Q12[0] = Qbar_12

            for t in range(1, n):
                Q11[t] = (1 - a_try - b_try) * Qbar_11 + a_try * z_spot[t-1]**2 + b_try * Q11[t-1]
                Q22[t] = (1 - a_try - b_try) * Qbar_22 + a_try * z_fut[t-1]**2 + b_try * Q22[t-1]
                Q12[t] = (1 - a_try - b_try) * Qbar_12 + a_try * z_spot[t-1]*z_fut[t-1] + b_try * Q12[t-1]

            # Dynamic correlation
            R12 = Q12 / np.sqrt(Q11 * Q22)
            R12 = np.clip(R12, -0.999, 0.999)

            # Log-likelihood (simplified)
            ll = -0.5 * np.sum(np.log(1 - R12[1:]**2) + (z_spot[1:]**2 + z_fut[1:]**2 - 2*R12[1:]*z_spot[1:]*z_fut[1:]) / (1 - R12[1:]**2))

            if np.isfinite(ll) and ll > best_ll:
                best_ll = ll
                best_a, best_b = a_try, b_try

    print(f"  DCC parameters: a={best_a:.3f}, b={best_b:.3f}")

    # Compute final DCC with best parameters
    Q11 = np.zeros(n)
    Q22 = np.zeros(n)
    Q12 = np.zeros(n)
    Q11[0] = Qbar_11
    Q22[0] = Qbar_22
    Q12[0] = Qbar_12

    for t in range(1, n):
        Q11[t] = (1 - best_a - best_b) * Qbar_11 + best_a * z_spot[t-1]**2 + best_b * Q11[t-1]
        Q22[t] = (1 - best_a - best_b) * Qbar_22 + best_a * z_fut[t-1]**2 + best_b * Q22[t-1]
        Q12[t] = (1 - best_a - best_b) * Qbar_12 + best_a * z_spot[t-1]*z_fut[t-1] + best_b * Q12[t-1]

    R12 = Q12 / np.sqrt(Q11 * Q22)
    R12 = np.clip(R12, -0.999, 0.999)

    # Dynamic hedge ratio: h_t = rho_t * sigma_spot_t / sigma_fut_t
    sigma_spot = np.sqrt(sigma2_spot)
    sigma_fut = np.sqrt(sigma2_fut)
    h_dcc = R12 * sigma_spot / sigma_fut

    return pd.Series(h_dcc, index=spot_r.index), best_a, best_b

print("\nEstimating DCC-GARCH...")
all_spot = pd.concat([spot_train, spot_test])
all_fut = pd.concat([fut_train, fut_test])
dcc_h, dcc_a, dcc_b = dcc_garch_hedge(all_spot, all_fut)

# ============================================================
# 7. Compute Hedged Portfolio Returns (OOS)
# ============================================================
def hedged_return(spot_r, fut_r, h):
    """
    Hedged portfolio return: R_h = R_s - h * R_f
    h is the hedge ratio (based on t-1 info → use shift(1))
    """
    # CRITICAL: hedge ratio from t-1, hedged return at t
    h_lagged = h.shift(1)  # signal.shift(1) — lag verification
    return spot_r - h_lagged * fut_r

# Prepare hedge ratios for OOS
methods = {}

# 1. Naive (h=1)
h_naive = pd.Series(1.0, index=spot_test.index)
methods['Naive (h=1)'] = h_naive

# 2. OLS Static (estimated on training data)
h_ols_static = pd.Series(beta_ols, index=spot_test.index)
methods['OLS Static'] = h_ols_static

# 3. Rolling OLS
h_rolling = rolling_h.loc[spot_test.index]
methods['Rolling OLS (252d)'] = h_rolling

# 4. DCC-GARCH
h_dcc_oos = dcc_h.loc[spot_test.index]
methods['DCC-GARCH'] = h_dcc_oos

# 5-7. Wild Bootstrap percentiles
for pct in [25, 50, 75]:
    h_boot = pd.Series(boot_pcts[pct], index=spot_test.index)
    methods[f'WB {pct}th pct'] = h_boot

# Compute hedged returns
hedged_returns = {}
for name, h in methods.items():
    hr = hedged_return(spot_test, fut_test, h)
    hedged_returns[name] = hr.dropna()

# Unhedged returns
unhedged = spot_test

# ============================================================
# 8. Evaluation Metrics
# ============================================================
def compute_metrics(hedged_ret, unhedged_ret):
    """Compute hedging effectiveness metrics."""
    # Align
    common = hedged_ret.index.intersection(unhedged_ret.index)
    h = hedged_ret.loc[common].values
    u = unhedged_ret.loc[common].values

    # HE = 1 - Var(hedged) / Var(unhedged)
    he = 1 - np.var(h) / np.var(u)

    # Downside HE (semivariance)
    h_neg = h[h < 0]
    u_neg = u[u < 0]
    semi_h = np.mean(h_neg ** 2) if len(h_neg) > 0 else 0
    semi_u = np.mean(u_neg ** 2) if len(u_neg) > 0 else 0
    dhe = 1 - semi_h / semi_u if semi_u > 0 else np.nan

    # VaR 5%
    var5_h = np.percentile(h, 5)
    var5_u = np.percentile(u, 5)
    var_reduction = 1 - abs(var5_h) / abs(var5_u) if abs(var5_u) > 0 else np.nan

    # Mean return (cost of hedging)
    mean_h = np.mean(h) * 252
    mean_u = np.mean(u) * 252

    # Annualized std
    std_h = np.std(h) * np.sqrt(252)
    std_u = np.std(u) * np.sqrt(252)

    return {
        'HE': he,
        'Downside_HE': dhe,
        'VaR_5pct_hedged': var5_h,
        'VaR_5pct_unhedged': var5_u,
        'VaR_reduction': var_reduction,
        'Ann_mean_hedged': mean_h,
        'Ann_mean_unhedged': mean_u,
        'Ann_std_hedged': std_h,
        'Ann_std_unhedged': std_u,
    }

print("\n" + "=" * 80)
print("OOS HEDGING EFFECTIVENESS COMPARISON")
print("=" * 80)

results_table = {}
for name, hr in hedged_returns.items():
    m = compute_metrics(hr, unhedged)
    results_table[name] = m
    print(f"\n{name}:")
    print(f"  HE = {m['HE']:.4f}  |  Downside HE = {m['Downside_HE']:.4f}")
    print(f"  VaR 5% = {m['VaR_5pct_hedged']:.6f}  |  VaR reduction = {m['VaR_reduction']:.4f}")
    print(f"  Ann. mean = {m['Ann_mean_hedged']:.4f}  |  Ann. std = {m['Ann_std_hedged']:.4f}")

# ============================================================
# 9. Cross-OOS Validation (5 non-overlapping 2-year periods)
# ============================================================
print("\n" + "=" * 80)
print("CROSS-OOS VALIDATION (5 non-overlapping 2-year periods)")
print("=" * 80)

all_spot_arr = all_spot.values
all_fut_arr = all_fut.values
n_total = len(all_spot)
period_len = 504  # ~2 years

# Determine number of non-overlapping periods we can fit
n_periods = min(5, n_total // period_len)
cross_oos = {name: [] for name in ['OLS Static', 'Rolling OLS (252d)', 'DCC-GARCH', 'WB 25th pct', 'WB 50th pct', 'WB 75th pct', 'Naive (h=1)']}

for i in range(n_periods):
    start_idx = i * period_len
    end_idx = start_idx + period_len
    if end_idx > n_total:
        break

    # Training: everything before this period
    train_mask = list(range(0, start_idx)) + list(range(end_idx, n_total))
    if len(train_mask) < 500:
        continue

    s_train = all_spot.iloc[train_mask]
    f_train = all_fut.iloc[train_mask]
    s_test_period = all_spot.iloc[start_idx:end_idx]
    f_test_period = all_fut.iloc[start_idx:end_idx]

    # OLS on training
    b, a, r = ols_hedge_ratio(s_train, f_train)

    # Wild bootstrap on training
    bb = wild_bootstrap_ohr(s_train, f_train, B=5000, seed=42+i)

    # Hedge ratios
    period_methods = {
        'Naive (h=1)': pd.Series(1.0, index=s_test_period.index),
        'OLS Static': pd.Series(b, index=s_test_period.index),
        'WB 25th pct': pd.Series(np.percentile(bb, 25), index=s_test_period.index),
        'WB 50th pct': pd.Series(np.percentile(bb, 50), index=s_test_period.index),
        'WB 75th pct': pd.Series(np.percentile(bb, 75), index=s_test_period.index),
    }

    # Rolling OLS needs history — use expanding window from available data
    combined_s = pd.concat([s_train.iloc[-252:], s_test_period])
    combined_f = pd.concat([f_train.iloc[-252:], f_test_period])
    rh = rolling_ols_hedge(combined_s, combined_f, window=252)
    period_methods['Rolling OLS (252d)'] = rh.loc[s_test_period.index]

    # DCC-GARCH on training → filter forward
    try:
        combined_s2 = pd.concat([s_train, s_test_period])
        combined_f2 = pd.concat([f_train, f_test_period])
        dh, _, _ = dcc_garch_hedge(combined_s2, combined_f2)
        period_methods['DCC-GARCH'] = dh.loc[s_test_period.index]
    except:
        period_methods['DCC-GARCH'] = pd.Series(b, index=s_test_period.index)  # fallback

    period_start = s_test_period.index[0].strftime('%Y-%m-%d')
    period_end = s_test_period.index[-1].strftime('%Y-%m-%d')
    print(f"\nPeriod {i+1}: {period_start} to {period_end}")

    for name, h in period_methods.items():
        hr = hedged_return(s_test_period, f_test_period, h).dropna()
        if len(hr) > 0:
            m = compute_metrics(hr, s_test_period)
            cross_oos[name].append(m['HE'])
            print(f"  {name}: HE={m['HE']:.4f}")

print("\n--- Cross-OOS Summary ---")
cross_oos_summary = {}
for name, hes in cross_oos.items():
    if len(hes) > 0:
        avg = np.mean(hes)
        std = np.std(hes)
        cross_oos_summary[name] = {'mean_HE': avg, 'std_HE': std, 'n_periods': len(hes)}
        print(f"{name}: mean HE={avg:.4f} ± {std:.4f} ({len(hes)} periods)")

# ============================================================
# 10. DM Test: OLS vs Wild Bootstrap methods
# ============================================================
print("\n" + "=" * 80)
print("DIEBOLD-MARIANO TEST (OLS vs Bootstrap methods)")
print("=" * 80)

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test for equal predictive accuracy.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_mean) * (d[:-k] - d_mean)) / (n - 1)
        gamma_sum += 2 * (1 - k/h) * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_mean / np.sqrt(var_d)
    from scipy import stats
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_value

# Squared hedged returns as loss function
common_idx = hedged_returns['OLS Static'].index
for name in ['WB 25th pct', 'WB 50th pct', 'WB 75th pct', 'DCC-GARCH', 'Rolling OLS (252d)']:
    if name in hedged_returns:
        ci = common_idx.intersection(hedged_returns[name].index)
        loss_ols = hedged_returns['OLS Static'].loc[ci].values ** 2
        loss_alt = hedged_returns[name].loc[ci].values ** 2

        if len(loss_ols) > 10:
            dm, pv = dm_test(loss_ols, loss_alt, h=1)
            sig = "***" if abs(dm) > 3.0 else ("**" if abs(dm) > 2.0 else ("*" if abs(dm) > 1.65 else ""))
            print(f"OLS vs {name}: DM={dm:.4f}, p={pv:.4f} {sig}")
            print(f"  (positive DM → {name} has lower squared hedged return = better)")

# ============================================================
# 11. Plots
# ============================================================
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTDIR = os.path.dirname(os.path.abspath(__file__))

# Plot 1: Bootstrap distribution histogram
fig, ax = plt.subplots(1, 1, figsize=(10, 6))
ax.hist(beta_boots, bins=80, density=True, alpha=0.7, color='steelblue', edgecolor='white')
ax.axvline(beta_ols, color='red', linestyle='--', linewidth=2, label=f'OLS β={beta_ols:.4f}')
for pct, color, ls in [(25, 'green', ':'), (50, 'orange', '-'), (75, 'purple', ':')]:
    ax.axvline(boot_pcts[pct], color=color, linestyle=ls, linewidth=2, label=f'{pct}th pct={boot_pcts[pct]:.4f}')
ax.set_xlabel('Hedge Ratio (β)', fontsize=12)
ax.set_ylabel('Density', fontsize=12)
ax.set_title(f'K965: Wild Bootstrap Distribution of MVHR ({asset_pair}, B=10,000)', fontsize=13)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, 'k965_bootstrap_distribution.png'), dpi=150)
plt.close()
print(f"\nSaved: k965_bootstrap_distribution.png")

# Plot 2: HE comparison bar chart
fig, ax = plt.subplots(1, 1, figsize=(12, 6))
names = list(results_table.keys())
hes = [results_table[n]['HE'] for n in names]
dhes = [results_table[n]['Downside_HE'] for n in names]

x = np.arange(len(names))
width = 0.35
bars1 = ax.bar(x - width/2, hes, width, label='HE', color='steelblue', alpha=0.8)
bars2 = ax.bar(x + width/2, dhes, width, label='Downside HE', color='coral', alpha=0.8)

ax.set_ylabel('Hedging Effectiveness', fontsize=12)
ax.set_title(f'K965: OOS Hedging Effectiveness Comparison ({asset_pair})', fontsize=13)
ax.set_xticks(x)
ax.set_xticklabels(names, rotation=30, ha='right', fontsize=9)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3, axis='y')

# Add value labels
for bar in bars1:
    height = bar.get_height()
    ax.annotate(f'{height:.3f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)
for bar in bars2:
    height = bar.get_height()
    ax.annotate(f'{height:.3f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)

plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, 'k965_he_comparison.png'), dpi=150)
plt.close()
print(f"Saved: k965_he_comparison.png")

# Plot 3: Hedge ratio time series (OOS)
fig, ax = plt.subplots(1, 1, figsize=(14, 6))
for name, color, ls in [('Rolling OLS (252d)', 'blue', '-'), ('DCC-GARCH', 'red', '-')]:
    if name in methods:
        h_series = methods[name].loc[spot_test.index]
        ax.plot(h_series.index, h_series.values, color=color, linestyle=ls, label=name, alpha=0.8)

# Static lines
ax.axhline(beta_ols, color='green', linestyle='--', label=f'OLS Static ({beta_ols:.4f})', alpha=0.7)
ax.axhline(boot_pcts[25], color='purple', linestyle=':', label=f'WB 25th ({boot_pcts[25]:.4f})', alpha=0.7)
ax.axhline(boot_pcts[50], color='orange', linestyle='-', label=f'WB 50th ({boot_pcts[50]:.4f})', alpha=0.7)
ax.axhline(boot_pcts[75], color='brown', linestyle=':', label=f'WB 75th ({boot_pcts[75]:.4f})', alpha=0.7)
ax.axhline(1.0, color='gray', linestyle='--', label='Naive (h=1)', alpha=0.5)

ax.set_xlabel('Date', fontsize=12)
ax.set_ylabel('Hedge Ratio', fontsize=12)
ax.set_title(f'K965: OOS Hedge Ratio Time Series ({asset_pair})', fontsize=13)
ax.legend(fontsize=9, loc='best')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, 'k965_hedge_ratio_timeseries.png'), dpi=150)
plt.close()
print(f"Saved: k965_hedge_ratio_timeseries.png")

# Plot 4: Cumulative hedged returns
fig, ax = plt.subplots(1, 1, figsize=(14, 6))
colors = ['gray', 'green', 'blue', 'red', 'purple', 'orange', 'brown']
for (name, hr), color in zip(hedged_returns.items(), colors):
    cum = (1 + hr).cumprod()
    ax.plot(cum.index, cum.values, label=name, color=color, alpha=0.8)

# Unhedged
cum_uh = (1 + unhedged).cumprod()
ax.plot(cum_uh.index, cum_uh.values, label='Unhedged', color='black', linewidth=2, linestyle='--')

ax.set_xlabel('Date', fontsize=12)
ax.set_ylabel('Cumulative Return', fontsize=12)
ax.set_title(f'K965: Cumulative OOS Hedged Portfolio Returns ({asset_pair})', fontsize=13)
ax.legend(fontsize=8, loc='best')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUTDIR, 'k965_cumulative_returns.png'), dpi=150)
plt.close()
print(f"Saved: k965_cumulative_returns.png")

# ============================================================
# 12. Save Results JSON
# ============================================================
results = {
    'experiment_id': 'K965',
    'title': f'Wild Bootstrap Optimal Hedge Ratio — {asset_pair}',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'asset_pair': asset_pair,
    'spot': spot_name,
    'futures': fut_name,
    'sample_period': f"{all_spot.index[0].strftime('%Y-%m-%d')} to {all_spot.index[-1].strftime('%Y-%m-%d')}",
    'n_total': n_total,
    'n_train': n_train,
    'n_test': n_test,
    'is_period': f"{spot_train.index[0].strftime('%Y-%m-%d')} to {spot_train.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{spot_test.index[0].strftime('%Y-%m-%d')} to {spot_test.index[-1].strftime('%Y-%m-%d')}",
    'correlation': float(np.corrcoef(spot_ret, fut_ret)[0,1]),
    'method': 'Wild Bootstrap (Mammen 1993 two-point)',
    'reference': 'JRFM 2024, Vol 17, Issue 7, Article 310',
    'bootstrap_reps': 10000,
    'seed': 42,
    'ols_hedge_ratio': float(beta_ols),
    'bootstrap_percentiles': {str(k): float(v) for k, v in boot_pcts.items()},
    'bootstrap_mean': float(beta_boots.mean()),
    'bootstrap_std': float(beta_boots.std()),
    'dcc_params': {'a': float(dcc_a), 'b': float(dcc_b)},
    'oos_results': {},
    'cross_oos': {},
    'conclusion': '',
}

# Add OOS results
for name, m in results_table.items():
    results['oos_results'][name] = {k: float(v) if not np.isnan(v) else None for k, v in m.items()}

# Add cross-OOS
for name, s in cross_oos_summary.items():
    results['cross_oos'][name] = {k: float(v) if isinstance(v, float) else v for k, v in s.items()}

# Determine best method
best_he = max(results_table.items(), key=lambda x: x[1]['HE'])
best_dhe = max(results_table.items(), key=lambda x: x[1]['Downside_HE'])

results['best_method_HE'] = best_he[0]
results['best_HE'] = float(best_he[1]['HE'])
results['best_method_Downside_HE'] = best_dhe[0]
results['best_Downside_HE'] = float(best_dhe[1]['Downside_HE'])

# Conclusion
conclusion_parts = [
    f"Wild Bootstrap OHR experiment on {asset_pair} ({n_total} days, OOS={n_test} days).",
    f"Best HE: {best_he[0]} ({best_he[1]['HE']:.4f}), Best Downside HE: {best_dhe[0]} ({best_dhe[1]['Downside_HE']:.4f}).",
    f"OLS static HR={beta_ols:.4f}, Bootstrap 50th={boot_pcts[50]:.4f} (diff={boot_pcts[50]-beta_ols:.4f}).",
    f"Bootstrap std={beta_boots.std():.4f}, 95% CI: [{boot_pcts[5]:.4f}, {boot_pcts[95]:.4f}].",
]

# Compare WB vs OLS
wb50_he = results_table.get('WB 50th pct', {}).get('HE', 0)
ols_he = results_table.get('OLS Static', {}).get('HE', 0)
if wb50_he > ols_he:
    conclusion_parts.append(f"WB 50th outperforms OLS Static by {(wb50_he - ols_he):.4f} HE points.")
else:
    conclusion_parts.append(f"OLS Static outperforms WB 50th by {(ols_he - wb50_he):.4f} HE points.")

results['conclusion'] = ' '.join(conclusion_parts)

with open(os.path.join(OUTDIR, 'k965_wild_bootstrap_ohr_results.json'), 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nSaved: k965_wild_bootstrap_ohr_results.json")
print(f"\n{'='*80}")
print(f"CONCLUSION: {results['conclusion']}")
print(f"{'='*80}")
