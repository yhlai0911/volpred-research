"""
K982: Sector Dispersion & Correlation Regime Analysis
=====================================================
Research Question: Do sector dispersion and inter-sector correlation
have predictive power for SPY volatility beyond VIX?

Data Source: yfinance (11 SPDR sector ETFs + SPY + VIX)
Period: 2015-01-01 to 2026-04-07
Methods: OLS regression with IS/OOS split, DM test, correlation regime analysis

References:
- Solnik, Roulet (2000): "Dispersion as cross-sectional volatility", FAJ
- Pollet, Wilson (2010): "Average correlation and stock market returns", JFE
- Stivers (2003): "Firm-level return dispersion and the future volatility of
  aggregate stock market returns", JFQA

[Proposed: Claude, Executed: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy import stats
from itertools import combinations

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 60)
print("K982: Sector Dispersion & Correlation Regime Analysis")
print("=" * 60)

sectors = ['XLK', 'XLF', 'XLV', 'XLC', 'XLY', 'XLI', 'XLP', 'XLE', 'XLU', 'XLRE', 'XLB']
start_date = '2015-01-01'
end_date = '2026-04-07'

print("\n[Step 1] Downloading data...")
spy = yf.download('SPY', start=start_date, end=end_date, progress=False)
vix = yf.download('^VIX', start=start_date, end=end_date, progress=False)

sector_data = {}
for s in sectors:
    df = yf.download(s, start=start_date, end=end_date, progress=False)
    if len(df) > 100:
        sector_data[s] = df
        print(f"  {s}: {len(df)} rows")
    else:
        print(f"  {s}: SKIPPED (only {len(df)} rows)")

# Handle multi-level columns from yfinance
def get_close(df, ticker=None):
    if isinstance(df.columns, pd.MultiIndex):
        return df['Close'].iloc[:, 0] if ticker is None else df['Close'][ticker]
    return df['Close']

spy_close = get_close(spy)
vix_close = get_close(vix)

# Compute returns
spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()

sector_returns = pd.DataFrame()
for s, df in sector_data.items():
    close = get_close(df)
    sector_returns[s] = np.log(close / close.shift(1))

sector_returns = sector_returns.dropna()

# Align all data
common_idx = spy_ret.index.intersection(sector_returns.index).intersection(vix_close.index)
spy_ret = spy_ret.loc[common_idx]
sector_returns = sector_returns.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"\nCommon period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(common_idx)}")

# ============================================================
# 2. Compute Dispersion and Correlation Indicators
# ============================================================
print("\n[Step 2] Computing dispersion and correlation indicators...")

# Cross-sectional dispersion: std of sector returns on day t
dispersion = sector_returns.std(axis=1)
dispersion.name = 'dispersion'

# Rolling average pairwise correlation (22-day window)
window = 22
n_sectors = len(sector_data)
pairs = list(combinations(sector_returns.columns, 2))

print(f"  Computing rolling {window}-day pairwise correlations for {len(pairs)} pairs...")

# Efficient computation: rolling correlation matrix
avg_corr_list = []
for i in range(window, len(sector_returns)):
    chunk = sector_returns.iloc[i-window:i]
    corr_mat = chunk.corr()
    # Average of upper triangle (excluding diagonal)
    upper = corr_mat.values[np.triu_indices(n_sectors, k=1)]
    avg_corr_list.append(upper.mean())

avg_corr = pd.Series(avg_corr_list, index=sector_returns.index[window:], name='avg_corr')

# Realized volatility: 22-day rolling std of SPY returns (annualized)
rv_22 = spy_ret.rolling(window).std() * np.sqrt(252)
rv_22.name = 'rv_22'

# Align everything
df_all = pd.DataFrame({
    'spy_ret': spy_ret,
    'vix': vix_close,
    'dispersion': dispersion,
    'rv_22': rv_22
}).dropna()
df_all = df_all.join(avg_corr, how='inner').dropna()

print(f"  Final aligned observations: {len(df_all)}")

# ============================================================
# 3. Descriptive Statistics
# ============================================================
print("\n[Step 3] Descriptive Statistics")
desc_vars = ['rv_22', 'vix', 'dispersion', 'avg_corr']
desc_stats = df_all[desc_vars].describe().T
desc_stats['skew'] = df_all[desc_vars].skew()
desc_stats['kurtosis'] = df_all[desc_vars].kurtosis()
print(desc_stats[['mean', 'std', 'min', 'max', 'skew', 'kurtosis']].round(4))

# Unconditional correlations
print("\nUnconditional correlations:")
corr_table = df_all[desc_vars].corr()
print(corr_table.round(4))

# ============================================================
# 4. Predictive Regressions (IS / OOS)
# ============================================================
print("\n[Step 4] Predictive Regressions")

# Target: future 22-day RV (shifted forward by 1 day to avoid lookahead)
df_all['rv_future'] = rv_22.shift(-22)  # future RV
df_all = df_all.dropna()

# All predictors lagged by 1 day (shift(1)) to prevent lookahead
df_all['vix_lag'] = df_all['vix'].shift(1)
df_all['disp_lag'] = df_all['dispersion'].shift(1)
df_all['corr_lag'] = df_all['avg_corr'].shift(1)
df_all = df_all.dropna()

# IS / OOS split
split_date = '2021-01-01'
is_data = df_all[df_all.index < split_date]
oos_data = df_all[df_all.index >= split_date]
print(f"  IS: {len(is_data)} obs ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {len(oos_data)} obs ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score

def run_regression(X_cols, y_col, is_df, oos_df, name):
    """Run regression and return IS/OOS metrics."""
    X_is = is_df[X_cols].values
    y_is = is_df[y_col].values
    X_oos = oos_df[X_cols].values
    y_oos = oos_df[y_col].values

    model = LinearRegression()
    model.fit(X_is, y_is)

    y_is_pred = model.predict(X_is)
    y_oos_pred = model.predict(X_oos)

    r2_is = r2_score(y_is, y_is_pred)
    r2_oos = r2_score(y_oos, y_oos_pred)
    mse_is = mean_squared_error(y_is, y_is_pred)
    mse_oos = mean_squared_error(y_oos, y_oos_pred)

    # t-stats for coefficients
    n = len(y_is)
    k = X_is.shape[1]
    resid = y_is - y_is_pred
    s2 = np.sum(resid**2) / (n - k - 1)
    XtX_inv = np.linalg.inv(X_is.T @ X_is)
    se = np.sqrt(s2 * np.diag(XtX_inv))
    t_stats = model.coef_ / se

    return {
        'name': name,
        'coefs': dict(zip(X_cols, model.coef_.tolist())),
        'intercept': float(model.intercept_),
        't_stats': dict(zip(X_cols, t_stats.tolist())),
        'r2_is': float(r2_is),
        'r2_oos': float(r2_oos),
        'mse_is': float(mse_is),
        'mse_oos': float(mse_oos),
        'oos_predictions': y_oos_pred,
        'oos_actual': y_oos
    }

# Model specifications
models = [
    (['vix_lag'], 'M1: VIX only'),
    (['vix_lag', 'disp_lag'], 'M2: VIX + Dispersion'),
    (['vix_lag', 'corr_lag'], 'M3: VIX + Avg Correlation'),
    (['vix_lag', 'disp_lag', 'corr_lag'], 'M4: VIX + Disp + Corr'),
    (['disp_lag'], 'M5: Dispersion only'),
    (['corr_lag'], 'M6: Avg Correlation only'),
]

results = {}
for cols, name in models:
    r = run_regression(cols, 'rv_future', is_data, oos_data, name)
    results[name] = r
    print(f"\n  {name}")
    print(f"    IS R2: {r['r2_is']:.4f}  OOS R2: {r['r2_oos']:.4f}")
    print(f"    IS MSE: {r['mse_is']:.6f}  OOS MSE: {r['mse_oos']:.6f}")
    for var in cols:
        sig = '***' if abs(r['t_stats'][var]) > 3.0 else ('**' if abs(r['t_stats'][var]) > 2.0 else ('*' if abs(r['t_stats'][var]) > 1.65 else ''))
        print(f"    {var}: coef={r['coefs'][var]:.6f}, t={r['t_stats'][var]:.3f} {sig}")

# ============================================================
# 5. Diebold-Mariano Test
# ============================================================
print("\n[Step 5] Diebold-Mariano Tests (vs M1 baseline)")

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = e1**2 - e2**2
    d_bar = np.mean(d)
    n = len(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return 0.0, 1.0
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

baseline_errors = oos_data['rv_future'].values - results['M1: VIX only']['oos_predictions']
dm_results = {}

for name, r in results.items():
    if name == 'M1: VIX only':
        continue
    model_errors = oos_data['rv_future'].values - r['oos_predictions']
    dm_stat, dm_p = dm_test(baseline_errors, model_errors, h=22)
    dm_results[name] = {'dm_stat': dm_stat, 'dm_p': dm_p}
    sig = '***' if dm_p < 0.01 else ('**' if dm_p < 0.05 else ('*' if dm_p < 0.10 else ''))
    print(f"  {name} vs M1: DM={dm_stat:.3f}, p={dm_p:.4f} {sig}")

# ============================================================
# 6. Correlation Regime Analysis
# ============================================================
print("\n[Step 6] Correlation Regime Analysis")

# Define regimes
high_corr_thresh = 0.6
low_corr_thresh = 0.4

df_all['corr_regime'] = 'medium'
df_all.loc[df_all['avg_corr'] > high_corr_thresh, 'corr_regime'] = 'high'
df_all.loc[df_all['avg_corr'] < low_corr_thresh, 'corr_regime'] = 'low'

regime_stats = df_all.groupby('corr_regime').agg({
    'rv_future': ['mean', 'std', 'count'],
    'vix': 'mean',
    'dispersion': 'mean',
    'avg_corr': 'mean'
}).round(4)
print(regime_stats)

# Test: high vs low regime RV difference
high_rv = df_all[df_all['corr_regime'] == 'high']['rv_future']
low_rv = df_all[df_all['corr_regime'] == 'low']['rv_future']
if len(high_rv) > 10 and len(low_rv) > 10:
    t_regime, p_regime = stats.ttest_ind(high_rv, low_rv)
    print(f"\n  High vs Low regime t-test: t={t_regime:.3f}, p={p_regime:.4f}")
    print(f"  High regime mean RV: {high_rv.mean():.4f} ({len(high_rv)} obs)")
    print(f"  Low regime mean RV: {low_rv.mean():.4f} ({len(low_rv)} obs)")
else:
    t_regime, p_regime = np.nan, np.nan
    print("  Insufficient data for regime t-test")

# Correlation change (delta) as predictor
df_all['corr_change'] = df_all['avg_corr'].diff(5)  # 5-day change
df_all_cc = df_all.dropna(subset=['corr_change'])

# Does correlation spike predict vol spike?
corr_spike = df_all_cc['corr_change'] > df_all_cc['corr_change'].quantile(0.9)
normal = ~corr_spike

spike_rv = df_all_cc.loc[corr_spike, 'rv_future']
normal_rv = df_all_cc.loc[normal, 'rv_future']

if len(spike_rv) > 10:
    t_spike, p_spike = stats.ttest_ind(spike_rv, normal_rv)
    print(f"\n  Correlation spike (top 10% 5d change) vs normal:")
    print(f"  Spike mean RV: {spike_rv.mean():.4f} ({len(spike_rv)} obs)")
    print(f"  Normal mean RV: {normal_rv.mean():.4f} ({len(normal_rv)} obs)")
    print(f"  t={t_spike:.3f}, p={p_spike:.4f}")
else:
    t_spike, p_spike = np.nan, np.nan

# ============================================================
# 7. Dispersion in Different Correlation Regimes
# ============================================================
print("\n[Step 7] Dispersion predictive power by correlation regime")

for regime in ['low', 'medium', 'high']:
    regime_df = df_all[df_all['corr_regime'] == regime].copy()
    if len(regime_df) < 50:
        print(f"  {regime}: insufficient data ({len(regime_df)} obs)")
        continue
    corr_disp_rv = regime_df[['disp_lag', 'rv_future']].corr().iloc[0, 1]
    corr_vix_rv = regime_df[['vix_lag', 'rv_future']].corr().iloc[0, 1]
    print(f"  {regime} regime ({len(regime_df)} obs):")
    print(f"    Dispersion-RV corr: {corr_disp_rv:.4f}")
    print(f"    VIX-RV corr: {corr_vix_rv:.4f}")

# ============================================================
# 8. Strategy Implication: Correlation-overlay on 12/VIX
# ============================================================
print("\n[Step 8] Strategy backtest: Correlation overlay on 12/VIX")

# Base: 12/VIX weight
df_strat = df_all[['spy_ret', 'vix', 'avg_corr']].copy()
df_strat['w_base'] = (12.0 / df_strat['vix']).clip(0, 1)

# Overlay: reduce exposure when correlation is high
df_strat['corr_adj'] = 1.0
df_strat.loc[df_strat['avg_corr'] > 0.6, 'corr_adj'] = 0.7
df_strat.loc[df_strat['avg_corr'] > 0.7, 'corr_adj'] = 0.5

df_strat['w_overlay'] = (df_strat['w_base'] * df_strat['corr_adj']).clip(0, 1)

# Apply lag (signal from t-1)
df_strat['w_base_lag'] = df_strat['w_base'].shift(1)
df_strat['w_overlay_lag'] = df_strat['w_overlay'].shift(1)
df_strat = df_strat.dropna()

# Returns
df_strat['ret_base'] = df_strat['w_base_lag'] * df_strat['spy_ret']
df_strat['ret_overlay'] = df_strat['w_overlay_lag'] * df_strat['spy_ret']
df_strat['ret_bh'] = df_strat['spy_ret']

# OOS only
strat_oos = df_strat[df_strat.index >= split_date]

def compute_metrics(returns, name):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + returns).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    return {
        'name': name,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd)
    }

strat_metrics = {}
for col, name in [('ret_bh', 'Buy & Hold'), ('ret_base', '12/VIX'), ('ret_overlay', '12/VIX + Corr Overlay')]:
    m = compute_metrics(strat_oos[col], name)
    strat_metrics[name] = m
    print(f"  {name}: Sharpe={m['sharpe']:.3f}, Ann.Ret={m['ann_return']:.4f}, Ann.Vol={m['ann_vol']:.4f}, MDD={m['mdd']:.4f}")

# ============================================================
# 9. Plots
# ============================================================
print("\n[Step 9] Generating plots...")
exp_dir = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a7c71930/experiments/k982'

# Plot 1: Rolling correlation + VIX overlay
fig, ax1 = plt.subplots(figsize=(14, 6))
dates = df_all.index.to_numpy()
ax1.plot(dates, df_all['avg_corr'].values, color='steelblue', alpha=0.8, linewidth=0.8, label='Avg Pairwise Corr (22d)')
ax1.axhline(y=0.6, color='red', linestyle='--', alpha=0.5, label='High corr threshold (0.6)')
ax1.axhline(y=0.4, color='green', linestyle='--', alpha=0.5, label='Low corr threshold (0.4)')
ax1.set_ylabel('Average Pairwise Correlation', color='steelblue')
ax1.set_xlabel('Date')
ax1.tick_params(axis='y', labelcolor='steelblue')

ax2 = ax1.twinx()
ax2.plot(dates, df_all['vix'].values, color='orange', alpha=0.6, linewidth=0.8, label='VIX')
ax2.set_ylabel('VIX', color='orange')
ax2.tick_params(axis='y', labelcolor='orange')

# Combine legends
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9)

plt.title('K982: Rolling Sector Correlation vs VIX (2015-2026)')
plt.tight_layout()
plt.savefig(f'{exp_dir}/k982_correlation_regime.png', dpi=150)
plt.close()
print(f"  Saved k982_correlation_regime.png")

# Plot 2: Dispersion vs Future RV scatter
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Scatter: dispersion vs future RV
ax = axes[0]
colors = {'low': 'green', 'medium': 'gray', 'high': 'red'}
for regime in ['low', 'medium', 'high']:
    mask = df_all['corr_regime'] == regime
    ax.scatter(df_all.loc[mask, 'disp_lag'].values, df_all.loc[mask, 'rv_future'].values,
               alpha=0.3, s=5, c=colors[regime], label=f'{regime} corr')
ax.set_xlabel('Lagged Dispersion')
ax.set_ylabel('Future 22-day RV (annualized)')
ax.set_title('Dispersion vs Future Volatility by Correlation Regime')
ax.legend()

# Scatter: avg_corr vs future RV
ax = axes[1]
ax.scatter(df_all['corr_lag'].values, df_all['rv_future'].values, alpha=0.2, s=5, c='steelblue')
ax.set_xlabel('Lagged Avg Pairwise Correlation')
ax.set_ylabel('Future 22-day RV (annualized)')
ax.set_title('Average Correlation vs Future Volatility')

plt.tight_layout()
plt.savefig(f'{exp_dir}/k982_dispersion_analysis.png', dpi=150)
plt.close()
print(f"  Saved k982_dispersion_analysis.png")

# ============================================================
# 10. Save Results
# ============================================================
print("\n[Step 10] Saving results...")

# Clean results for JSON
model_results_clean = {}
for name, r in results.items():
    model_results_clean[name] = {
        'coefs': r['coefs'],
        'intercept': r['intercept'],
        't_stats': r['t_stats'],
        'r2_is': r['r2_is'],
        'r2_oos': r['r2_oos'],
        'mse_is': r['mse_is'],
        'mse_oos': r['mse_oos']
    }

output = {
    'experiment_id': 'K982',
    'title': 'Sector Dispersion & Correlation Regime Analysis',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': f'{start_date} to {end_date}',
    'n_observations': len(df_all),
    'is_period': f'{is_data.index[0].strftime("%Y-%m-%d")} to {is_data.index[-1].strftime("%Y-%m-%d")}',
    'oos_period': f'{oos_data.index[0].strftime("%Y-%m-%d")} to {oos_data.index[-1].strftime("%Y-%m-%d")}',
    'is_n': len(is_data),
    'oos_n': len(oos_data),
    'sectors_used': list(sector_data.keys()),
    'descriptive_stats': {
        var: {
            'mean': float(df_all[var].mean()),
            'std': float(df_all[var].std()),
            'min': float(df_all[var].min()),
            'max': float(df_all[var].max()),
            'skew': float(df_all[var].skew()),
            'kurtosis': float(df_all[var].kurtosis())
        }
        for var in desc_vars
    },
    'unconditional_correlations': {
        var: {v2: float(corr_table.loc[var, v2]) for v2 in desc_vars}
        for var in desc_vars
    },
    'regression_results': model_results_clean,
    'dm_tests_vs_m1': {
        name: {'dm_stat': v['dm_stat'], 'p_value': v['dm_p']}
        for name, v in dm_results.items()
    },
    'correlation_regime_analysis': {
        'thresholds': {'high': high_corr_thresh, 'low': low_corr_thresh},
        'regime_counts': df_all['corr_regime'].value_counts().to_dict(),
        'regime_mean_rv': df_all.groupby('corr_regime')['rv_future'].mean().to_dict(),
        'high_vs_low_t_test': {
            't_stat': float(t_regime) if not np.isnan(t_regime) else None,
            'p_value': float(p_regime) if not np.isnan(p_regime) else None
        },
        'correlation_spike_test': {
            'spike_mean_rv': float(spike_rv.mean()) if len(spike_rv) > 0 else None,
            'normal_mean_rv': float(normal_rv.mean()) if len(normal_rv) > 0 else None,
            't_stat': float(t_spike) if not np.isnan(t_spike) else None,
            'p_value': float(p_spike) if not np.isnan(p_spike) else None
        }
    },
    'strategy_backtest': {
        'period': f'{strat_oos.index[0].strftime("%Y-%m-%d")} to {strat_oos.index[-1].strftime("%Y-%m-%d")}',
        'n_days': len(strat_oos),
        'metrics': strat_metrics,
        'signal_lag': 'shift(1) applied to all signals'
    },
    'conclusions': [],
    'limitations': [
        'XLC only available from 2018, XLRE from 2015 -- sector count varies early in sample',
        'Equal-weighted dispersion, not market-cap weighted',
        '22-day rolling window -- sensitive to window choice',
        'OOS period includes COVID crash (high correlation) and 2022 rate hikes',
        'No transaction cost in strategy backtest'
    ],
    'references': [
        'Solnik & Roulet (2000), Dispersion as cross-sectional volatility, FAJ',
        'Pollet & Wilson (2010), Average correlation and stock market returns, JFE',
        'Stivers (2003), Firm-level return dispersion and the future volatility, JFQA'
    ]
}

# Generate conclusions based on results
conclusions = []

# Incremental R2 from dispersion
r2_m1 = model_results_clean['M1: VIX only']['r2_oos']
r2_m2 = model_results_clean['M2: VIX + Dispersion']['r2_oos']
r2_m3 = model_results_clean['M3: VIX + Avg Correlation']['r2_oos']
r2_m4 = model_results_clean['M4: VIX + Disp + Corr']['r2_oos']

conclusions.append(
    f"VIX alone explains {r2_m1:.1%} of OOS future RV variance (OOS R2)."
)
conclusions.append(
    f"Adding dispersion to VIX changes OOS R2 from {r2_m1:.4f} to {r2_m2:.4f} (delta={r2_m2-r2_m1:+.4f})."
)
conclusions.append(
    f"Adding avg correlation to VIX changes OOS R2 from {r2_m1:.4f} to {r2_m3:.4f} (delta={r2_m3-r2_m1:+.4f})."
)
conclusions.append(
    f"Full model (VIX+Disp+Corr) OOS R2 = {r2_m4:.4f} (delta vs VIX-only = {r2_m4-r2_m1:+.4f})."
)

# Regime analysis
if not np.isnan(t_regime):
    if abs(t_regime) > 3.0:
        conclusions.append(
            f"High-corr regime has significantly higher future RV than low-corr regime (t={t_regime:.3f}, passes Harvey threshold)."
        )
    elif p_regime < 0.05:
        conclusions.append(
            f"High-corr regime has higher future RV than low-corr regime (t={t_regime:.3f}, p={p_regime:.4f}), but does not pass Harvey |t|>3 threshold."
        )

# Strategy
base_sharpe = strat_metrics['12/VIX']['sharpe']
overlay_sharpe = strat_metrics['12/VIX + Corr Overlay']['sharpe']
conclusions.append(
    f"Correlation overlay on 12/VIX: Sharpe changes from {base_sharpe:.3f} to {overlay_sharpe:.3f} in OOS period."
)

# DM test significance
any_significant = any(v['dm_p'] < 0.05 for v in dm_results.values())
if not any_significant:
    conclusions.append(
        "No model with dispersion/correlation significantly outperforms VIX-only by DM test (p<0.05)."
    )

output['conclusions'] = conclusions

with open(f'{exp_dir}/k982_dispersion_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved k982_dispersion_results.json")

# ============================================================
# Print Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for c in conclusions:
    print(f"  - {c}")

print("\nDone.")
