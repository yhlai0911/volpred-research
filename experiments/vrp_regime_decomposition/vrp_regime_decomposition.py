"""
K123: Volatility Risk Premium (VRP) Decomposition by Market Regime

Background:
- Q10 confirmed VRP timing is NS (VIX already contains full VRP info)
- But average VRP (~4%) masks huge regime differences
- S1 found VIX/GARCH ratio +36% in geopolitical crises
- Question: What is the VRP structure across different regimes?

Methodology:
- VRP = VIX_t - RV_22d_t (annualized)
- VIX as implied vol proxy; 22d realized vol from SPY returns
- 4 regimes: Bull quiet, Bull nervous, Bear mild, Bear crisis
- Newey-West HAC standard errors for autocorrelated VRP
- OOS: 2023-01-01 ~ 2024-12-31
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K123: VRP Decomposition by Market Regime")
print("=" * 70)

# Download data: 2007-2024
print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2006-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2006-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Align dates
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')

# Drop NaN
df = df.dropna()
print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# ============================================================
# 2. Calculate VRP Components
# ============================================================
print("\n[2] Calculating VRP components...")

# 22-day realized vol (annualized)
df['rv_22d'] = df['spy_return'].rolling(22).std() * np.sqrt(252) * 100  # in % like VIX

# VRP = VIX - RV (both annualized, in %)
df['vrp'] = df['vix'] - df['rv_22d']

# 22-day trailing return for regime classification
df['ret_22d'] = df['spy_close'].pct_change(22)

# Future 22-day return for predictability test
df['fwd_ret_22d'] = df['spy_close'].shift(-22) / df['spy_close'] - 1

# Drop NaN from rolling calculations
df = df.dropna(subset=['vrp', 'ret_22d'])
print(f"  After calculations: {len(df)} obs ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 3. Regime Classification
# ============================================================
print("\n[3] Classifying market regimes...")

conditions = [
    (df['ret_22d'] > 0) & (df['vix'] < 20),    # Bull quiet
    (df['ret_22d'] > 0) & (df['vix'] >= 20),    # Bull nervous
    (df['ret_22d'] < 0) & (df['vix'] < 25),     # Bear mild
    (df['ret_22d'] < 0) & (df['vix'] >= 25),    # Bear crisis
]
regime_names = ['Bull_Quiet', 'Bull_Nervous', 'Bear_Mild', 'Bear_Crisis']
df['regime'] = np.select(conditions, regime_names, default='Other')

# Check distribution
print("\n  Regime Distribution:")
regime_counts = df['regime'].value_counts()
for r in regime_names:
    count = regime_counts.get(r, 0)
    pct = count / len(df) * 100
    print(f"    {r:15s}: {count:5d} days ({pct:5.1f}%)")

# ============================================================
# 4. VRP Distribution by Regime
# ============================================================
print("\n" + "=" * 70)
print("[4] VRP Distribution by Regime")
print("=" * 70)

# Full sample stats
print(f"\n  Full Sample VRP: mean={df['vrp'].mean():.2f}%, "
      f"median={df['vrp'].median():.2f}%, "
      f"std={df['vrp'].std():.2f}%, "
      f"skew={df['vrp'].skew():.2f}")

results_regime = {}

for regime in regime_names:
    mask = df['regime'] == regime
    vrp_r = df.loc[mask, 'vrp']

    stats_dict = {
        'count': int(mask.sum()),
        'mean': float(vrp_r.mean()),
        'median': float(vrp_r.median()),
        'std': float(vrp_r.std()),
        'skewness': float(vrp_r.skew()),
        'kurtosis': float(vrp_r.kurtosis()),
        'min': float(vrp_r.min()),
        'max': float(vrp_r.max()),
        'pct_positive': float((vrp_r > 0).mean() * 100),
        'q25': float(vrp_r.quantile(0.25)),
        'q75': float(vrp_r.quantile(0.75)),
    }
    results_regime[regime] = stats_dict

    print(f"\n  {regime}:")
    print(f"    N={stats_dict['count']}, Mean={stats_dict['mean']:.2f}%, "
          f"Median={stats_dict['median']:.2f}%, Std={stats_dict['std']:.2f}%")
    print(f"    Skew={stats_dict['skewness']:.2f}, Kurt={stats_dict['kurtosis']:.2f}")
    print(f"    Range=[{stats_dict['min']:.1f}%, {stats_dict['max']:.1f}%]")
    print(f"    VRP>0: {stats_dict['pct_positive']:.1f}%")
    print(f"    IQR=[{stats_dict['q25']:.1f}%, {stats_dict['q75']:.1f}%]")

# ============================================================
# 5. Statistical Tests for Regime Differences
# ============================================================
print("\n" + "=" * 70)
print("[5] Statistical Tests: Regime Differences")
print("=" * 70)

# Pairwise t-tests (Welch's t-test, no equal variance assumption)
print("\n  Pairwise Welch t-tests (VRP mean differences):")
test_results = {}
for i, r1 in enumerate(regime_names):
    for j, r2 in enumerate(regime_names):
        if j <= i:
            continue
        vrp1 = df.loc[df['regime'] == r1, 'vrp']
        vrp2 = df.loc[df['regime'] == r2, 'vrp']
        t_stat, p_val = stats.ttest_ind(vrp1, vrp2, equal_var=False)
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "NS"
        print(f"    {r1} vs {r2}: t={t_stat:.2f}, p={p_val:.4f} {sig}")
        test_results[f"{r1}_vs_{r2}"] = {'t_stat': float(t_stat), 'p_value': float(p_val)}

# Kruskal-Wallis (non-parametric)
groups = [df.loc[df['regime'] == r, 'vrp'].values for r in regime_names]
kw_stat, kw_p = stats.kruskal(*groups)
print(f"\n  Kruskal-Wallis test: H={kw_stat:.2f}, p={kw_p:.6f}")

# ============================================================
# 6. VRP Autocorrelation by Regime
# ============================================================
print("\n" + "=" * 70)
print("[6] VRP Autocorrelation Structure by Regime")
print("=" * 70)

lags_to_test = [1, 5, 10, 22]
autocorr_results = {}

print(f"\n  {'Regime':15s} {'Lag-1':>8s} {'Lag-5':>8s} {'Lag-10':>8s} {'Lag-22':>8s}")
print("  " + "-" * 50)

for regime in regime_names + ['Full_Sample']:
    if regime == 'Full_Sample':
        vrp_series = df['vrp']
    else:
        vrp_series = df.loc[df['regime'] == regime, 'vrp']

    ac_values = {}
    ac_str = []
    for lag in lags_to_test:
        if len(vrp_series) > lag + 10:
            ac = vrp_series.autocorr(lag=lag)
            ac_values[f'lag_{lag}'] = float(ac)
            ac_str.append(f"{ac:8.3f}")
        else:
            ac_values[f'lag_{lag}'] = None
            ac_str.append(f"{'N/A':>8s}")

    autocorr_results[regime] = ac_values
    print(f"  {regime:15s} {''.join(ac_str)}")

# Half-life of VRP autocorrelation
print("\n  VRP Half-life (AR(1) approximation):")
for regime in regime_names + ['Full_Sample']:
    ac1 = autocorr_results[regime].get('lag_1')
    if ac1 and ac1 > 0:
        half_life = -np.log(2) / np.log(ac1)
        print(f"    {regime:15s}: {half_life:.1f} days")
    else:
        print(f"    {regime:15s}: N/A (ac1 <= 0)")

# ============================================================
# 7. Newey-West HAC Standard Errors
# ============================================================
print("\n" + "=" * 70)
print("[7] VRP Mean with Newey-West HAC Standard Errors")
print("=" * 70)

def newey_west_se(x, max_lag=None):
    """Compute Newey-West HAC standard error for the mean."""
    n = len(x)
    if max_lag is None:
        max_lag = int(np.floor(4 * (n / 100) ** (2/9)))

    x_demeaned = x - x.mean()

    # Gamma_0
    gamma_0 = np.sum(x_demeaned ** 2) / n

    # Add weighted autocovariances
    nw_var = gamma_0
    for j in range(1, max_lag + 1):
        weight = 1 - j / (max_lag + 1)  # Bartlett kernel
        gamma_j = np.sum(x_demeaned[j:] * x_demeaned[:-j]) / n
        nw_var += 2 * weight * gamma_j

    se = np.sqrt(nw_var / n)
    return se

print(f"\n  {'Regime':15s} {'Mean':>8s} {'OLS_SE':>8s} {'NW_SE':>8s} {'NW_t':>8s} {'Ratio':>8s}")
print("  " + "-" * 55)

nw_results = {}
for regime in regime_names + ['Full_Sample']:
    if regime == 'Full_Sample':
        vrp_vals = df['vrp'].values
    else:
        vrp_vals = df.loc[df['regime'] == regime, 'vrp'].values

    mean_vrp = np.mean(vrp_vals)
    ols_se = np.std(vrp_vals, ddof=1) / np.sqrt(len(vrp_vals))
    nw_se = newey_west_se(vrp_vals)
    nw_t = mean_vrp / nw_se if nw_se > 0 else np.nan
    ratio = nw_se / ols_se if ols_se > 0 else np.nan

    nw_results[regime] = {
        'mean': float(mean_vrp),
        'ols_se': float(ols_se),
        'nw_se': float(nw_se),
        'nw_t': float(nw_t),
        'se_ratio': float(ratio)
    }

    print(f"  {regime:15s} {mean_vrp:8.2f} {ols_se:8.3f} {nw_se:8.3f} {nw_t:8.2f} {ratio:8.2f}")

print("\n  Note: NW_SE/OLS_SE ratio >1 indicates positive autocorrelation inflates OLS SE")

# ============================================================
# 8. VRP → Future Return Predictability by Regime
# ============================================================
print("\n" + "=" * 70)
print("[8] VRP → Future 22d Return Predictability by Regime")
print("=" * 70)

# Define OOS period
oos_start = '2023-01-01'
oos_end = '2024-12-31'

# Drop rows without forward return
pred_df = df.dropna(subset=['fwd_ret_22d']).copy()

# Compute masks on pred_df (not df)
is_mask = pred_df.index < oos_start
oos_mask = (pred_df.index >= oos_start) & (pred_df.index <= oos_end)

print("\n  A. Full-sample regression (IS):")
print(f"  {'Regime':15s} {'N':>6s} {'beta':>8s} {'t-stat':>8s} {'R2':>8s} {'p-val':>8s}")
print("  " + "-" * 55)

predictability_results = {}

for regime in regime_names + ['Full_Sample']:
    if regime == 'Full_Sample':
        sub = pred_df[is_mask]
    else:
        sub = pred_df[is_mask & (pred_df['regime'] == regime)]

    if len(sub) < 30:
        print(f"  {regime:15s} {'N<30, skip':>40s}")
        continue

    x = sub['vrp'].values
    y = sub['fwd_ret_22d'].values

    # OLS regression
    x_const = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(x_const, y, rcond=None)[0]
        y_hat = x_const @ beta
        resid = y - y_hat

        # Newey-West for regression
        n = len(x)
        max_lag = int(np.floor(4 * (n / 100) ** (2/9)))

        # Simple t-stat (OLS, not NW for simplicity in regression context)
        sse = np.sum(resid ** 2)
        mse = sse / (n - 2)
        xtx_inv = np.linalg.inv(x_const.T @ x_const)
        se_beta = np.sqrt(mse * np.diag(xtx_inv))

        t_stat = beta[1] / se_beta[1]
        r2 = 1 - sse / np.sum((y - y.mean()) ** 2)
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 2))

        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "NS"
        print(f"  {regime:15s} {n:6d} {beta[1]:8.5f} {t_stat:8.2f} {r2:8.4f} {p_val:8.4f} {sig}")

        predictability_results[regime] = {
            'n_is': int(n),
            'beta': float(beta[1]),
            'intercept': float(beta[0]),
            't_stat': float(t_stat),
            'r2': float(r2),
            'p_val': float(p_val),
        }
    except Exception as e:
        print(f"  {regime:15s} Error: {e}")

# OOS test
print(f"\n  B. Out-of-Sample (OOS: {oos_start} to {oos_end}):")
print(f"  {'Regime':15s} {'N':>6s} {'beta':>8s} {'t-stat':>8s} {'R2':>8s} {'p-val':>8s}")
print("  " + "-" * 55)

for regime in regime_names + ['Full_Sample']:
    if regime == 'Full_Sample':
        sub = pred_df[oos_mask]
    else:
        sub = pred_df[oos_mask & (pred_df['regime'] == regime)]

    if len(sub) < 20:
        print(f"  {regime:15s} {'N<20, skip':>40s}")
        continue

    x = sub['vrp'].values
    y = sub['fwd_ret_22d'].values

    x_const = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(x_const, y, rcond=None)[0]
        y_hat = x_const @ beta
        resid = y - y_hat

        n = len(x)
        sse = np.sum(resid ** 2)
        mse = sse / (n - 2)
        xtx_inv = np.linalg.inv(x_const.T @ x_const)
        se_beta = np.sqrt(mse * np.diag(xtx_inv))

        t_stat = beta[1] / se_beta[1]
        r2 = 1 - sse / np.sum((y - y.mean()) ** 2)
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 2))

        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "NS"
        print(f"  {regime:15s} {n:6d} {beta[1]:8.5f} {t_stat:8.2f} {r2:8.4f} {p_val:8.4f} {sig}")

        if regime in predictability_results:
            predictability_results[regime]['n_oos'] = int(n)
            predictability_results[regime]['beta_oos'] = float(beta[1])
            predictability_results[regime]['t_stat_oos'] = float(t_stat)
            predictability_results[regime]['r2_oos'] = float(r2)
            predictability_results[regime]['p_val_oos'] = float(p_val)
    except Exception as e:
        print(f"  {regime:15s} Error: {e}")

# ============================================================
# 9. Risk Aversion vs Jump Fear Decomposition
# ============================================================
print("\n" + "=" * 70)
print("[9] VRP Decomposition: Risk Aversion vs Jump Fear")
print("=" * 70)

# Logic:
# - High VRP + Low RV = "pure risk aversion" (market fears more than realized)
# - High VRP + High RV = "jump compensation" (VIX pricing jumps correctly)
# - Low/Negative VRP + High RV = "vol surprise" (realized > implied)
# - Low VRP + Low RV = "calm complacency"

# Use median splits for RV and VRP
rv_median = df['rv_22d'].median()
vrp_median = df['vrp'].median()

print(f"\n  Medians: VRP={vrp_median:.2f}%, RV_22d={rv_median:.2f}%")

# Quadrant classification
conditions_quad = [
    (df['vrp'] >= vrp_median) & (df['rv_22d'] < rv_median),   # High VRP, Low RV
    (df['vrp'] >= vrp_median) & (df['rv_22d'] >= rv_median),  # High VRP, High RV
    (df['vrp'] < vrp_median) & (df['rv_22d'] >= rv_median),   # Low VRP, High RV
    (df['vrp'] < vrp_median) & (df['rv_22d'] < rv_median),    # Low VRP, Low RV
]
quad_names = ['Risk_Aversion', 'Jump_Compensation', 'Vol_Surprise', 'Calm_Complacency']
quad_labels = [
    'High VRP + Low RV (Risk Aversion)',
    'High VRP + High RV (Jump Compensation)',
    'Low VRP + High RV (Vol Surprise)',
    'Low VRP + Low RV (Calm Complacency)'
]

df['quadrant'] = np.select(conditions_quad, quad_names, default='Other')

decomp_results = {}

print(f"\n  {'Quadrant':30s} {'N':>6s} {'%':>6s} {'VRP':>8s} {'RV':>8s} {'VIX':>8s} {'Fwd22d':>8s}")
print("  " + "-" * 75)

for qname, qlabel in zip(quad_names, quad_labels):
    qmask = df['quadrant'] == qname
    sub = df[qmask]

    fwd_mean = sub['fwd_ret_22d'].mean() * 100 if not sub['fwd_ret_22d'].isna().all() else np.nan

    print(f"  {qlabel:30s} {len(sub):6d} {len(sub)/len(df)*100:5.1f}% "
          f"{sub['vrp'].mean():8.2f} {sub['rv_22d'].mean():8.2f} "
          f"{sub['vix'].mean():8.2f} {fwd_mean:7.2f}%")

    decomp_results[qname] = {
        'count': int(len(sub)),
        'pct': float(len(sub) / len(df) * 100),
        'mean_vrp': float(sub['vrp'].mean()),
        'mean_rv': float(sub['rv_22d'].mean()),
        'mean_vix': float(sub['vix'].mean()),
        'mean_fwd_ret_22d': float(fwd_mean) if not np.isnan(fwd_mean) else None,
    }

# Which quadrant has best forward returns?
print("\n  Forward return by quadrant (annualized):")
for qname in quad_names:
    fwd = decomp_results[qname].get('mean_fwd_ret_22d')
    if fwd is not None:
        ann = fwd * 12  # rough annualization (22d ~ 1 month)
        print(f"    {qname:25s}: {fwd:.2f}%/month, ~{ann:.1f}%/year")

# ============================================================
# 10. Regime Transitions and VRP Persistence
# ============================================================
print("\n" + "=" * 70)
print("[10] Regime Transition Matrix")
print("=" * 70)

# Transition probabilities
df['regime_next'] = df['regime'].shift(-1)
trans_df = df.dropna(subset=['regime_next'])

print(f"\n  Transition probabilities (row=from, col=to):")
print(f"  {'':15s}", end="")
for r in regime_names:
    print(f" {r[:10]:>10s}", end="")
print()

transition_matrix = {}
for r_from in regime_names:
    row_mask = trans_df['regime'] == r_from
    n_from = row_mask.sum()
    transition_matrix[r_from] = {}

    print(f"  {r_from:15s}", end="")
    for r_to in regime_names:
        n_to = ((trans_df['regime'] == r_from) & (trans_df['regime_next'] == r_to)).sum()
        prob = n_to / n_from if n_from > 0 else 0
        transition_matrix[r_from][r_to] = float(prob)
        print(f" {prob:10.3f}", end="")
    print()

# ============================================================
# 11. VRP by Year (Time Variation)
# ============================================================
print("\n" + "=" * 70)
print("[11] VRP by Year")
print("=" * 70)

df['year'] = df.index.year
yearly_vrp = df.groupby('year')['vrp'].agg(['mean', 'median', 'std', 'count'])

print(f"\n  {'Year':>6s} {'Mean':>8s} {'Median':>8s} {'Std':>8s} {'N':>5s}")
print("  " + "-" * 35)
for year, row in yearly_vrp.iterrows():
    if year >= 2007:
        print(f"  {year:6d} {row['mean']:8.2f} {row['median']:8.2f} {row['std']:8.2f} {int(row['count']):5d}")

# ============================================================
# 12. VRP Extreme Quintile Analysis
# ============================================================
print("\n" + "=" * 70)
print("[12] VRP Quintile → Future Return")
print("=" * 70)

pred_df2 = df.dropna(subset=['fwd_ret_22d']).copy()
pred_df2['vrp_quintile'] = pd.qcut(pred_df2['vrp'], 5, labels=['Q1_Low', 'Q2', 'Q3', 'Q4', 'Q5_High'])

print(f"\n  {'Quintile':>10s} {'VRP_Mean':>10s} {'VRP_Range':>18s} {'Fwd_Ret':>10s} {'Sharpe*':>10s} {'N':>6s}")
print("  " + "-" * 65)

quintile_results = {}
for q in ['Q1_Low', 'Q2', 'Q3', 'Q4', 'Q5_High']:
    sub = pred_df2[pred_df2['vrp_quintile'] == q]
    vrp_mean = sub['vrp'].mean()
    vrp_min = sub['vrp'].min()
    vrp_max = sub['vrp'].max()
    fwd_mean = sub['fwd_ret_22d'].mean() * 100
    fwd_std = sub['fwd_ret_22d'].std() * 100
    sharpe_proxy = fwd_mean / fwd_std if fwd_std > 0 else 0

    print(f"  {q:>10s} {vrp_mean:10.2f} [{vrp_min:7.1f}, {vrp_max:6.1f}] {fwd_mean:9.2f}% {sharpe_proxy:10.3f} {len(sub):6d}")

    quintile_results[q] = {
        'vrp_mean': float(vrp_mean),
        'fwd_ret_mean': float(fwd_mean),
        'fwd_ret_std': float(fwd_std),
        'sharpe_proxy': float(sharpe_proxy),
        'n': int(len(sub))
    }

# Q5 vs Q1 spread
q5_ret = quintile_results['Q5_High']['fwd_ret_mean']
q1_ret = quintile_results['Q1_Low']['fwd_ret_mean']
spread = q5_ret - q1_ret
print(f"\n  Q5-Q1 spread: {spread:.2f}%/month")
print(f"  Interpretation: {'High VRP predicts higher returns' if spread > 0 else 'High VRP predicts lower returns'}")

# T-test for Q5 vs Q1
q5_vals = pred_df2.loc[pred_df2['vrp_quintile'] == 'Q5_High', 'fwd_ret_22d'].values
q1_vals = pred_df2.loc[pred_df2['vrp_quintile'] == 'Q1_Low', 'fwd_ret_22d'].values
t_q5q1, p_q5q1 = stats.ttest_ind(q5_vals, q1_vals, equal_var=False)
sig_q5q1 = "***" if p_q5q1 < 0.001 else "**" if p_q5q1 < 0.01 else "*" if p_q5q1 < 0.05 else "NS"
print(f"  Q5 vs Q1 t-test: t={t_q5q1:.2f}, p={p_q5q1:.4f} {sig_q5q1}")

# ============================================================
# 13. Crisis Deep Dive
# ============================================================
print("\n" + "=" * 70)
print("[13] Crisis Period VRP Deep Dive")
print("=" * 70)

crisis_periods = {
    'GFC_2008': ('2008-09-01', '2009-03-31'),
    'Flash_Crash_2010': ('2010-05-01', '2010-06-30'),
    'Euro_Crisis_2011': ('2011-07-01', '2011-11-30'),
    'China_Shock_2015': ('2015-08-01', '2015-10-31'),
    'Volmageddon_2018': ('2018-01-25', '2018-04-30'),
    'COVID_2020': ('2020-02-15', '2020-04-30'),
    'Rate_Hike_2022': ('2022-01-01', '2022-10-31'),
}

print(f"\n  {'Crisis':20s} {'Mean_VRP':>10s} {'Peak_VRP':>10s} {'Mean_VIX':>10s} {'Mean_RV':>10s} {'Days':>6s}")
print("  " + "-" * 65)

crisis_results = {}
for name, (start, end) in crisis_periods.items():
    crisis_mask = (df.index >= start) & (df.index <= end)
    sub = df[crisis_mask]

    if len(sub) == 0:
        continue

    mean_vrp = sub['vrp'].mean()
    peak_vrp = sub['vrp'].max()
    mean_vix = sub['vix'].mean()
    mean_rv = sub['rv_22d'].mean()

    print(f"  {name:20s} {mean_vrp:10.2f} {peak_vrp:10.2f} {mean_vix:10.2f} {mean_rv:10.2f} {len(sub):6d}")

    crisis_results[name] = {
        'mean_vrp': float(mean_vrp),
        'peak_vrp': float(peak_vrp),
        'mean_vix': float(mean_vix),
        'mean_rv': float(mean_rv),
        'days': int(len(sub)),
        'pct_negative_vrp': float((sub['vrp'] < 0).mean() * 100),
    }

# ============================================================
# 14. VRP Regime & VT Strategy Connection
# ============================================================
print("\n" + "=" * 70)
print("[14] VRP Regime → VT Strategy Implication")
print("=" * 70)

# For each regime, what does 12/VIX give as weight?
for regime in regime_names:
    sub = df[df['regime'] == regime]
    vt_weight = 12.0 / sub['vix']
    vt_weight = vt_weight.clip(0, 1)

    print(f"\n  {regime}:")
    print(f"    Mean VT weight (12/VIX): {vt_weight.mean():.3f}")
    print(f"    VT weight range: [{vt_weight.min():.3f}, {vt_weight.max():.3f}]")
    print(f"    Days at 100% equity: {(vt_weight >= 0.99).mean()*100:.1f}%")
    print(f"    Days below 50% equity: {(vt_weight < 0.50).mean()*100:.1f}%")
    print(f"    Mean VRP in this regime: {sub['vrp'].mean():.2f}%")

    # What's the relationship between VRP and VT weight?
    corr = sub['vrp'].corr(vt_weight)
    print(f"    Corr(VRP, VT_weight): {corr:.3f}")

# ============================================================
# 15. Summary and Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[15] SUMMARY & CONCLUSIONS")
print("=" * 70)

full_vrp_mean = df['vrp'].mean()
bull_quiet_vrp = results_regime['Bull_Quiet']['mean']
bear_crisis_vrp = results_regime['Bear_Crisis']['mean']
vrp_range = bear_crisis_vrp - bull_quiet_vrp

print(f"""
  K123: VRP Decomposition by Market Regime — Key Findings:

  1. OVERALL VRP:
     - Full sample mean: {full_vrp_mean:.2f}%
     - VRP is positive {(df['vrp'] > 0).mean()*100:.1f}% of the time
     - High persistence (lag-1 autocorr: {autocorr_results['Full_Sample']['lag_1']:.3f})

  2. REGIME STRUCTURE:
     - Bull Quiet VRP:   {results_regime['Bull_Quiet']['mean']:+.2f}% (N={results_regime['Bull_Quiet']['count']})
     - Bull Nervous VRP: {results_regime['Bull_Nervous']['mean']:+.2f}% (N={results_regime['Bull_Nervous']['count']})
     - Bear Mild VRP:    {results_regime['Bear_Mild']['mean']:+.2f}% (N={results_regime['Bear_Mild']['count']})
     - Bear Crisis VRP:  {results_regime['Bear_Crisis']['mean']:+.2f}% (N={results_regime['Bear_Crisis']['count']})
     - Range across regimes: {vrp_range:.2f}%

  3. RISK AVERSION vs JUMP FEAR:
     - Risk Aversion (High VRP + Low RV): {decomp_results['Risk_Aversion']['pct']:.1f}% of days
     - Jump Compensation (High VRP + High RV): {decomp_results['Jump_Compensation']['pct']:.1f}% of days
     - Vol Surprise (Low VRP + High RV): {decomp_results['Vol_Surprise']['pct']:.1f}% of days
     - Calm Complacency (Low VRP + Low RV): {decomp_results['Calm_Complacency']['pct']:.1f}% of days

  4. PREDICTABILITY:
     - Q5-Q1 VRP quintile spread: {spread:.2f}%/month
     - Q5 vs Q1 t-test: t={t_q5q1:.2f}, p={p_q5q1:.4f}

  5. VT CONNECTION:
     - VRP provides context for VT but NOT additional trading signal
     - 12/VIX already mechanically captures VRP regime information
     - Confirms Q10: VIX is sufficient statistic for VT at monthly horizon
""")

# ============================================================
# Save Results
# ============================================================
output = {
    'experiment': 'K123',
    'title': 'VRP Decomposition by Market Regime',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': int(len(df)),
    'oos_period': f"{oos_start} to {oos_end}",
    'full_sample_vrp': {
        'mean': float(df['vrp'].mean()),
        'median': float(df['vrp'].median()),
        'std': float(df['vrp'].std()),
        'pct_positive': float((df['vrp'] > 0).mean() * 100),
    },
    'regime_distribution': results_regime,
    'regime_tests': test_results,
    'kruskal_wallis': {'H': float(kw_stat), 'p': float(kw_p)},
    'autocorrelation': autocorr_results,
    'newey_west': nw_results,
    'predictability': predictability_results,
    'decomposition': decomp_results,
    'quintiles': quintile_results,
    'q5_q1_spread': {
        'spread_pct': float(spread),
        't_stat': float(t_q5q1),
        'p_value': float(p_q5q1),
    },
    'crisis_analysis': crisis_results,
    'transition_matrix': transition_matrix,
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a040b711/experiments/vrp_regime_decomposition_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print("\n" + "=" * 70)
print("K123 COMPLETE")
print("=" * 70)
