"""
K979: CBOE SKEW Index as Volatility Predictor
=============================================
Research question: Does SKEW provide incremental vol prediction beyond VIX?

Data: SPY, ^VIX, ^SKEW from yfinance (2010-01-01 to 2026-04-07)
Target: Realized volatility (squared daily returns, annualized)
Method: OLS regressions with shift(1) for all predictors (no lookahead)
IS: 2010-2018, OOS: 2019-2026

References:
- Patton (2011) - QLIKE loss for volatility evaluation
- Harvey (2016) - t > 3.0 threshold for significance
- CBOE SKEW methodology whitepaper

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

SAVE_DIR = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a18b2ccf/experiments/k979'

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K979: CBOE SKEW Index as Volatility Predictor")
print("=" * 60)

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2010-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-04-07', progress=False)
skew = yf.download('^SKEW', start='2010-01-01', end='2026-04-07', progress=False)

# Handle MultiIndex columns if present
for df_name, df in [('spy', spy), ('vix', vix), ('skew', skew)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"  SPY: {len(spy)} rows ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX: {len(vix)} rows ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")
print(f"  SKEW: {len(skew)} rows ({skew.index[0].strftime('%Y-%m-%d')} to {skew.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Construct Variables
# ============================================================
print("\n[2] Constructing variables...")

# Daily log returns
spy_ret = np.log(spy['Close'] / spy['Close'].shift(1))
# Realized volatility proxies (squared returns, annualized)
rv_1 = spy_ret ** 2 * 252  # 1-day RV proxy
rv_5 = spy_ret.rolling(5).apply(lambda x: np.sum(x**2) * 252 / 5, raw=True)  # 5-day avg RV
rv_22 = spy_ret.rolling(22).apply(lambda x: np.sum(x**2) * 252 / 22, raw=True)  # 22-day avg RV

# Combine into DataFrame
df = pd.DataFrame({
    'ret': spy_ret,
    'rv1': rv_1,
    'rv5': rv_5,
    'rv22': rv_22,
    'vix': vix['Close'],
    'skew': skew['Close']
}).dropna()

print(f"  Combined dataset: {len(df)} observations")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 3. Part 1: Descriptive Statistics
# ============================================================
print("\n" + "=" * 60)
print("[3] PART 1: Descriptive Statistics")
print("=" * 60)

desc_vars = {'VIX': df['vix'], 'SKEW': df['skew'], 'RV1 (ann.)': df['rv1'], 'RV5 (ann.)': df['rv5']}
desc_stats = {}
for name, series in desc_vars.items():
    s = series.dropna()
    desc_stats[name] = {
        'count': int(len(s)),
        'mean': float(s.mean()),
        'std': float(s.std()),
        'min': float(s.min()),
        'q25': float(s.quantile(0.25)),
        'median': float(s.median()),
        'q75': float(s.quantile(0.75)),
        'max': float(s.max()),
        'skewness': float(stats.skew(s)),
        'kurtosis': float(stats.kurtosis(s))
    }
    print(f"\n  {name}:")
    print(f"    N={desc_stats[name]['count']}, Mean={desc_stats[name]['mean']:.4f}, "
          f"Std={desc_stats[name]['std']:.4f}")
    print(f"    Min={desc_stats[name]['min']:.4f}, Median={desc_stats[name]['median']:.4f}, "
          f"Max={desc_stats[name]['max']:.4f}")
    print(f"    Skew={desc_stats[name]['skewness']:.4f}, Kurt={desc_stats[name]['kurtosis']:.4f}")

# Correlation
corr_vix_skew = df['vix'].corr(df['skew'])
corr_vix_rv1 = df['vix'].corr(df['rv1'])
corr_skew_rv1 = df['skew'].corr(df['rv1'])
print(f"\n  Correlations:")
print(f"    VIX-SKEW:  {corr_vix_skew:.4f}")
print(f"    VIX-RV1:   {corr_vix_rv1:.4f}")
print(f"    SKEW-RV1:  {corr_skew_rv1:.4f}")

# Autocorrelation (lag 1, 5, 22)
for name, series in [('VIX', df['vix']), ('SKEW', df['skew'])]:
    ac1 = series.autocorr(lag=1)
    ac5 = series.autocorr(lag=5)
    ac22 = series.autocorr(lag=22)
    print(f"    {name} autocorr: lag1={ac1:.4f}, lag5={ac5:.4f}, lag22={ac22:.4f}")

# ============================================================
# 4. Figure 1: SKEW vs VIX Scatter
# ============================================================
print("\n[4] Generating SKEW vs VIX scatter plot...")

fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# Scatter: VIX vs SKEW
ax = axes[0]
ax.scatter(df['vix'].values, df['skew'].values, alpha=0.15, s=5, c='steelblue')
ax.set_xlabel('VIX', fontsize=12)
ax.set_ylabel('SKEW', fontsize=12)
ax.set_title(f'VIX vs SKEW (corr={corr_vix_skew:.3f})', fontsize=13)
ax.grid(True, alpha=0.3)

# Time series: VIX
ax = axes[1]
ax.plot(df.index.to_numpy(), df['vix'].values, color='red', alpha=0.7, linewidth=0.5)
ax.set_title('VIX Time Series', fontsize=13)
ax.set_ylabel('VIX Level')
ax.grid(True, alpha=0.3)

# Time series: SKEW
ax = axes[2]
ax.plot(df.index.to_numpy(), df['skew'].values, color='purple', alpha=0.7, linewidth=0.5)
ax.set_title('SKEW Time Series', fontsize=13)
ax.set_ylabel('SKEW Level')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f'{SAVE_DIR}/k979_skew_vix_scatter.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k979_skew_vix_scatter.png")

# ============================================================
# 5. Part 2: Vol Prediction Regressions (OLS)
# ============================================================
print("\n" + "=" * 60)
print("[5] PART 2: Volatility Prediction Regressions")
print("=" * 60)

# All predictors shift(1) to avoid lookahead
df['vix_lag'] = df['vix'].shift(1)
df['skew_lag'] = df['skew'].shift(1)
df['vix_sq_lag'] = (df['vix'].shift(1))**2  # VIX squared for nonlinearity

# Forward RV targets
df['rv1_fwd'] = df['rv1'].shift(-1)   # next day RV
df['rv5_fwd'] = df['rv5'].shift(-5)   # 5-day forward RV
df['rv22_fwd'] = df['rv22'].shift(-22) # 22-day forward RV

# Drop NaN
reg_df = df[['rv1_fwd', 'rv5_fwd', 'rv22_fwd', 'vix_lag', 'skew_lag', 'vix_sq_lag']].dropna()

# IS/OOS split
is_mask = reg_df.index < '2019-01-01'
oos_mask = reg_df.index >= '2019-01-01'

print(f"  IS: {is_mask.sum()} obs, OOS: {oos_mask.sum()} obs")

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error

def run_regression(y_name, X_cols, label, data_is, data_oos):
    """Run OLS regression and return stats."""
    y_is = data_is[y_name].values
    X_is = data_is[X_cols].values
    y_oos = data_oos[y_name].values
    X_oos = data_oos[X_cols].values

    model = LinearRegression()
    model.fit(X_is, y_is)

    # IS stats
    y_pred_is = model.predict(X_is)
    r2_is = r2_score(y_is, y_pred_is)

    # OOS stats
    y_pred_oos = model.predict(X_oos)
    r2_oos = 1 - np.sum((y_oos - y_pred_oos)**2) / np.sum((y_oos - np.mean(y_oos))**2)
    mse_oos = mean_squared_error(y_oos, y_pred_oos)

    # QLIKE (Patton 2011)
    eps = 1e-10
    y_pred_oos_pos = np.maximum(y_pred_oos, eps)
    qlike = np.mean(y_oos / y_pred_oos_pos - np.log(y_oos / y_pred_oos_pos) - 1)

    # Coefficient t-stats (manual OLS for proper inference)
    n = len(y_is)
    k = X_is.shape[1] + 1  # +1 for intercept
    X_is_c = np.column_stack([np.ones(n), X_is])
    beta = np.linalg.lstsq(X_is_c, y_is, rcond=None)[0]
    residuals = y_is - X_is_c @ beta
    s2 = np.sum(residuals**2) / (n - k)
    # Newey-West would be better, but OLS SE for comparison
    cov = s2 * np.linalg.inv(X_is_c.T @ X_is_c)
    se = np.sqrt(np.diag(cov))
    t_stats = beta / se

    coef_names = ['intercept'] + X_cols
    result = {
        'label': label,
        'target': y_name,
        'predictors': X_cols,
        'r2_is': float(r2_is),
        'r2_oos': float(r2_oos),
        'mse_oos': float(mse_oos),
        'qlike_oos': float(qlike),
        'coefficients': {name: {'beta': float(b), 'se': float(s), 't_stat': float(t)}
                        for name, b, s, t in zip(coef_names, beta, se, t_stats)},
        'n_is': int(n),
        'n_oos': int(len(y_oos))
    }
    return result, y_pred_oos

# Run all regressions
regression_results = {}

# === 1-day horizon ===
print("\n  --- 1-Day Horizon (RV_{t+1}) ---")

r1, _ = run_regression('rv1_fwd', ['vix_lag'], 'M1: VIX only', reg_df[is_mask], reg_df[oos_mask])
regression_results['m1_vix_1d'] = r1
print(f"    M1 (VIX):       IS R²={r1['r2_is']:.4f}, OOS R²={r1['r2_oos']:.4f}, QLIKE={r1['qlike_oos']:.4f}")
for c, v in r1['coefficients'].items():
    if c != 'intercept':
        print(f"      {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

r2, pred_m2 = run_regression('rv1_fwd', ['vix_lag', 'skew_lag'], 'M2: VIX+SKEW', reg_df[is_mask], reg_df[oos_mask])
regression_results['m2_vix_skew_1d'] = r2
print(f"    M2 (VIX+SKEW):  IS R²={r2['r2_is']:.4f}, OOS R²={r2['r2_oos']:.4f}, QLIKE={r2['qlike_oos']:.4f}")
for c, v in r2['coefficients'].items():
    if c != 'intercept':
        print(f"      {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

delta_r2_1d = r2['r2_oos'] - r1['r2_oos']
print(f"    Delta OOS R² (SKEW increment): {delta_r2_1d:.6f}")

# === 5-day horizon ===
print("\n  --- 5-Day Horizon (RV_{t+5}) ---")

r3, _ = run_regression('rv5_fwd', ['vix_lag'], 'M3: VIX only (5d)', reg_df[is_mask], reg_df[oos_mask])
regression_results['m3_vix_5d'] = r3
print(f"    M3 (VIX):       IS R²={r3['r2_is']:.4f}, OOS R²={r3['r2_oos']:.4f}, QLIKE={r3['qlike_oos']:.4f}")

r4, _ = run_regression('rv5_fwd', ['vix_lag', 'skew_lag'], 'M4: VIX+SKEW (5d)', reg_df[is_mask], reg_df[oos_mask])
regression_results['m4_vix_skew_5d'] = r4
print(f"    M4 (VIX+SKEW):  IS R²={r4['r2_is']:.4f}, OOS R²={r4['r2_oos']:.4f}, QLIKE={r4['qlike_oos']:.4f}")
for c, v in r4['coefficients'].items():
    if c != 'intercept':
        print(f"      {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

delta_r2_5d = r4['r2_oos'] - r3['r2_oos']
print(f"    Delta OOS R² (SKEW increment): {delta_r2_5d:.6f}")

# === 22-day horizon ===
print("\n  --- 22-Day Horizon (RV_{t+22}) ---")

r5, _ = run_regression('rv22_fwd', ['vix_lag'], 'M5: VIX only (22d)', reg_df[is_mask], reg_df[oos_mask])
regression_results['m5_vix_22d'] = r5
print(f"    M5 (VIX):       IS R²={r5['r2_is']:.4f}, OOS R²={r5['r2_oos']:.4f}, QLIKE={r5['qlike_oos']:.4f}")

r6, _ = run_regression('rv22_fwd', ['vix_lag', 'skew_lag'], 'M6: VIX+SKEW (22d)', reg_df[is_mask], reg_df[oos_mask])
regression_results['m6_vix_skew_22d'] = r6
print(f"    M6 (VIX+SKEW):  IS R²={r6['r2_is']:.4f}, OOS R²={r6['r2_oos']:.4f}, QLIKE={r6['qlike_oos']:.4f}")
for c, v in r6['coefficients'].items():
    if c != 'intercept':
        print(f"      {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

delta_r2_22d = r6['r2_oos'] - r5['r2_oos']
print(f"    Delta OOS R² (SKEW increment): {delta_r2_22d:.6f}")

# ============================================================
# 6. Diebold-Mariano Test (1-day horizon)
# ============================================================
print("\n" + "=" * 60)
print("[6] Diebold-Mariano Test (M1 vs M2, 1-day)")
print("=" * 60)

# Reconstruct OOS predictions for DM test
oos_data = reg_df[oos_mask].copy()
y_oos = oos_data['rv1_fwd'].values

# M1 predictions
from sklearn.linear_model import LinearRegression
m1 = LinearRegression().fit(reg_df[is_mask][['vix_lag']].values, reg_df[is_mask]['rv1_fwd'].values)
pred_m1 = m1.predict(oos_data[['vix_lag']].values)

# M2 predictions
m2 = LinearRegression().fit(reg_df[is_mask][['vix_lag', 'skew_lag']].values, reg_df[is_mask]['rv1_fwd'].values)
pred_m2_dm = m2.predict(oos_data[['vix_lag', 'skew_lag']].values)

# DM test (squared error loss)
e1 = (y_oos - pred_m1)**2
e2 = (y_oos - pred_m2_dm)**2
d = e1 - e2  # positive = M2 better

n_oos = len(d)
d_mean = np.mean(d)
# Newey-West SE (lag = int(n^(1/3)))
lag_nw = int(n_oos**(1/3))
gamma_0 = np.var(d, ddof=1)
gamma_sum = 0
for j in range(1, lag_nw + 1):
    w = 1 - j / (lag_nw + 1)  # Bartlett kernel
    gamma_j = np.cov(d[j:], d[:-j])[0, 1]
    gamma_sum += 2 * w * gamma_j
var_d = gamma_0 + gamma_sum
se_d = np.sqrt(var_d / n_oos)
dm_stat = d_mean / se_d
dm_pvalue = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

print(f"  DM statistic: {dm_stat:.4f}")
print(f"  DM p-value:   {dm_pvalue:.4f}")
print(f"  Mean loss diff (M1-M2): {d_mean:.6f}")
if dm_stat > 0:
    print(f"  -> M2 (VIX+SKEW) has lower squared error")
else:
    print(f"  -> M1 (VIX only) has lower squared error")
if abs(dm_stat) > 3.0:
    print(f"  -> Significant at Harvey (2016) threshold |t|>3.0")
else:
    print(f"  -> NOT significant at Harvey (2016) threshold |t|>3.0")

dm_results = {
    'dm_statistic': float(dm_stat),
    'dm_pvalue': float(dm_pvalue),
    'mean_loss_diff': float(d_mean),
    'nw_lag': int(lag_nw),
    'n_oos': int(n_oos),
    'harvey_significant': bool(abs(dm_stat) > 3.0)
}

# ============================================================
# 7. Part 3: SKEW Extreme Value Analysis
# ============================================================
print("\n" + "=" * 60)
print("[7] PART 3: SKEW Extreme Value Analysis")
print("=" * 60)

# Percentile-based thresholds
skew_p90 = df['skew'].quantile(0.90)
skew_p10 = df['skew'].quantile(0.10)
skew_p95 = df['skew'].quantile(0.95)
skew_p05 = df['skew'].quantile(0.05)

print(f"  SKEW P5={skew_p05:.1f}, P10={skew_p10:.1f}, P90={skew_p90:.1f}, P95={skew_p95:.1f}")

# Forward returns and vol conditional on SKEW regimes
def analyze_conditional(mask, label):
    """Analyze forward returns/vol conditional on mask."""
    # Use shift(-1) for forward return, shift(-5) for 5-day
    fwd_ret_1 = df['ret'].shift(-1)
    fwd_rv_1 = df['rv1'].shift(-1)
    fwd_rv_5 = df['rv5'].shift(-5)

    sub_ret = fwd_ret_1[mask].dropna()
    sub_rv1 = fwd_rv_1[mask].dropna()
    sub_rv5 = fwd_rv_5[mask].dropna()

    result = {
        'n': int(len(sub_ret)),
        'mean_ret_1d': float(sub_ret.mean()),
        'std_ret_1d': float(sub_ret.std()),
        'mean_rv1': float(sub_rv1.mean()),
        'mean_rv5': float(sub_rv5.mean()),
        'sharpe_ann': float(sub_ret.mean() / sub_ret.std() * np.sqrt(252)) if sub_ret.std() > 0 else 0
    }
    print(f"  {label} (N={result['n']}):")
    print(f"    Mean 1d ret: {result['mean_ret_1d']*100:.4f}%")
    print(f"    Mean RV1 (ann): {result['mean_rv1']:.4f}")
    print(f"    Mean RV5 (ann): {result['mean_rv5']:.4f}")
    print(f"    Ann. Sharpe: {result['sharpe_ann']:.3f}")
    return result

extreme_analysis = {}
extreme_analysis['high_skew_p90'] = analyze_conditional(df['skew'] > skew_p90, f'High SKEW (>{skew_p90:.0f}, P90)')
extreme_analysis['low_skew_p10'] = analyze_conditional(df['skew'] < skew_p10, f'Low SKEW (<{skew_p10:.0f}, P10)')
extreme_analysis['high_skew_p95'] = analyze_conditional(df['skew'] > skew_p95, f'High SKEW (>{skew_p95:.0f}, P95)')
extreme_analysis['low_skew_p05'] = analyze_conditional(df['skew'] < skew_p05, f'Low SKEW (<{skew_p05:.0f}, P05)')
extreme_analysis['normal_skew'] = analyze_conditional(
    (df['skew'] >= skew_p10) & (df['skew'] <= skew_p90),
    f'Normal SKEW ({skew_p10:.0f}-{skew_p90:.0f})'
)

# SKEW spike detection (daily change > 2 std)
skew_change = df['skew'].diff()
skew_change_std = skew_change.std()
spike_up = skew_change > 2 * skew_change_std
spike_down = skew_change < -2 * skew_change_std

extreme_analysis['skew_spike_up'] = analyze_conditional(spike_up, f'SKEW Spike Up (>2σ, threshold={2*skew_change_std:.1f})')
extreme_analysis['skew_spike_down'] = analyze_conditional(spike_down, f'SKEW Spike Down (<-2σ)')

# ============================================================
# 8. Figure 2: Conditional Volatility by SKEW Regime
# ============================================================
print("\n[8] Generating conditional volatility figure...")

fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# Panel 1: Box plot of forward RV by SKEW quintile
skew_quintile = pd.qcut(df['skew'], 5, labels=['Q1\n(Low)', 'Q2', 'Q3', 'Q4', 'Q5\n(High)'])
fwd_rv = df['rv1'].shift(-1)
box_data = [fwd_rv[skew_quintile == q].dropna().values for q in ['Q1\n(Low)', 'Q2', 'Q3', 'Q4', 'Q5\n(High)']]

ax = axes[0]
bp = ax.boxplot(box_data, labels=['Q1\n(Low)', 'Q2', 'Q3', 'Q4', 'Q5\n(High)'],
                showfliers=False, patch_artist=True)
colors = ['#2196F3', '#64B5F6', '#90CAF9', '#E57373', '#F44336']
for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)
ax.set_title('Forward RV by SKEW Quintile', fontsize=13)
ax.set_ylabel('Realized Volatility (ann.)')
ax.set_xlabel('SKEW Quintile')
ax.grid(True, alpha=0.3, axis='y')

# Panel 2: Rolling correlation VIX-SKEW (252d)
ax = axes[1]
rolling_corr = df['vix'].rolling(252).corr(df['skew'])
ax.plot(df.index.to_numpy(), rolling_corr.values, color='darkgreen', linewidth=0.8)
ax.axhline(y=0, color='black', linestyle='--', alpha=0.5)
ax.set_title('Rolling 252d Corr: VIX vs SKEW', fontsize=13)
ax.set_ylabel('Correlation')
ax.grid(True, alpha=0.3)
ax.set_ylim(-0.8, 0.8)

# Panel 3: SKEW quintile mean forward vol
ax = axes[2]
quintile_means = [np.nanmean(d) for d in box_data]
quintile_labels = ['Q1\n(Low)', 'Q2', 'Q3', 'Q4', 'Q5\n(High)']
bars = ax.bar(quintile_labels, quintile_means, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
ax.set_title('Mean Forward RV by SKEW Quintile', fontsize=13)
ax.set_ylabel('Mean Realized Volatility (ann.)')
ax.set_xlabel('SKEW Quintile')
ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig(f'{SAVE_DIR}/k979_conditional_vol.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k979_conditional_vol.png")

# Quintile statistics for results
quintile_stats = {}
for i, (q_label, q_data) in enumerate(zip(['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'], box_data)):
    quintile_stats[q_label] = {
        'mean_rv': float(np.nanmean(q_data)),
        'median_rv': float(np.nanmedian(q_data)),
        'n': int(len(q_data[~np.isnan(q_data)]))
    }
    print(f"  {q_label}: mean_rv={quintile_stats[q_label]['mean_rv']:.4f}, N={quintile_stats[q_label]['n']}")

# ============================================================
# 9. Part 4: VIX-SKEW Interaction
# ============================================================
print("\n" + "=" * 60)
print("[9] PART 4: VIX-SKEW Interaction")
print("=" * 60)

# Add interaction term
df['vix_skew_interact'] = df['vix_lag'] * df['skew_lag']
reg_df2 = df[['rv1_fwd', 'vix_lag', 'skew_lag', 'vix_skew_interact']].dropna()
is_mask2 = reg_df2.index < '2019-01-01'
oos_mask2 = reg_df2.index >= '2019-01-01'

r7, _ = run_regression('rv1_fwd', ['vix_lag', 'skew_lag', 'vix_skew_interact'],
                        'M7: VIX+SKEW+Interact', reg_df2[is_mask2], reg_df2[oos_mask2])
regression_results['m7_interaction_1d'] = r7
print(f"  M7 (VIX+SKEW+Interact): IS R²={r7['r2_is']:.4f}, OOS R²={r7['r2_oos']:.4f}")
for c, v in r7['coefficients'].items():
    if c != 'intercept':
        print(f"    {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

# VIX squared + SKEW
df['vix_sq_lag2'] = df['vix_lag'] ** 2
reg_df3 = df[['rv1_fwd', 'vix_lag', 'vix_sq_lag2', 'skew_lag']].dropna()
is_mask3 = reg_df3.index < '2019-01-01'
oos_mask3 = reg_df3.index >= '2019-01-01'

r8, _ = run_regression('rv1_fwd', ['vix_lag', 'vix_sq_lag2', 'skew_lag'],
                        'M8: VIX+VIX²+SKEW', reg_df3[is_mask3], reg_df3[oos_mask3])
regression_results['m8_vix_sq_skew_1d'] = r8
print(f"  M8 (VIX+VIX²+SKEW): IS R²={r8['r2_is']:.4f}, OOS R²={r8['r2_oos']:.4f}")
for c, v in r8['coefficients'].items():
    if c != 'intercept':
        print(f"    {c}: beta={v['beta']:.6f}, t={v['t_stat']:.3f}")

# ============================================================
# 10. Rolling OOS R² (expanding window)
# ============================================================
print("\n" + "=" * 60)
print("[10] Rolling OOS Analysis (expanding window from 2019)")
print("=" * 60)

oos_years = sorted(reg_df[oos_mask].index.year.unique())
yearly_results = {}

for year in oos_years:
    year_mask = (reg_df.index >= f'{year}-01-01') & (reg_df.index < f'{year+1}-01-01')
    if year_mask.sum() < 10:
        continue

    # Expanding IS: everything before this year
    is_exp = reg_df.index < f'{year}-01-01'

    # M1: VIX only
    m1_y = LinearRegression()
    m1_y.fit(reg_df[is_exp][['vix_lag']].values, reg_df[is_exp]['rv1_fwd'].values)
    pred_m1_y = m1_y.predict(reg_df[year_mask][['vix_lag']].values)
    y_true = reg_df[year_mask]['rv1_fwd'].values
    r2_m1_y = 1 - np.sum((y_true - pred_m1_y)**2) / np.sum((y_true - np.mean(y_true))**2)

    # M2: VIX + SKEW
    m2_y = LinearRegression()
    m2_y.fit(reg_df[is_exp][['vix_lag', 'skew_lag']].values, reg_df[is_exp]['rv1_fwd'].values)
    pred_m2_y = m2_y.predict(reg_df[year_mask][['vix_lag', 'skew_lag']].values)
    r2_m2_y = 1 - np.sum((y_true - pred_m2_y)**2) / np.sum((y_true - np.mean(y_true))**2)

    yearly_results[str(year)] = {
        'r2_m1': float(r2_m1_y),
        'r2_m2': float(r2_m2_y),
        'delta_r2': float(r2_m2_y - r2_m1_y),
        'n': int(year_mask.sum())
    }
    print(f"  {year}: M1 R²={r2_m1_y:.4f}, M2 R²={r2_m2_y:.4f}, Delta={r2_m2_y - r2_m1_y:.6f} (N={year_mask.sum()})")

# ============================================================
# 11. Summary and Conclusions
# ============================================================
print("\n" + "=" * 60)
print("[11] SUMMARY")
print("=" * 60)

# Key findings
skew_t_stat_1d = r2['coefficients']['skew_lag']['t_stat']
skew_beta_1d = r2['coefficients']['skew_lag']['beta']
skew_t_stat_5d = r4['coefficients']['skew_lag']['t_stat']
skew_t_stat_22d = r6['coefficients']['skew_lag']['t_stat']

print(f"\n  Key Findings:")
print(f"  1. VIX-SKEW correlation: {corr_vix_skew:.4f} (low, measuring different dimensions)")
print(f"  2. SKEW incremental prediction (1d):")
print(f"     - Beta: {skew_beta_1d:.6f}, t-stat: {skew_t_stat_1d:.3f}")
print(f"     - Delta OOS R²: {delta_r2_1d:.6f}")
print(f"     - Harvey significant (|t|>3): {abs(skew_t_stat_1d) > 3.0}")
print(f"  3. SKEW incremental prediction (5d):")
print(f"     - t-stat: {skew_t_stat_5d:.3f}, Delta OOS R²: {delta_r2_5d:.6f}")
print(f"  4. SKEW incremental prediction (22d):")
print(f"     - t-stat: {skew_t_stat_22d:.3f}, Delta OOS R²: {delta_r2_22d:.6f}")
print(f"  5. DM test (M1 vs M2): stat={dm_stat:.4f}, p={dm_pvalue:.4f}")
print(f"  6. High SKEW (P90) forward vol: {extreme_analysis['high_skew_p90']['mean_rv1']:.4f}")
print(f"     Low SKEW (P10) forward vol:  {extreme_analysis['low_skew_p10']['mean_rv1']:.4f}")

conclusion = ""
if abs(skew_t_stat_1d) > 3.0 and delta_r2_1d > 0.001:
    conclusion = "SKEW provides statistically AND economically significant incremental vol prediction beyond VIX"
elif abs(skew_t_stat_1d) > 2.0 and delta_r2_1d > 0:
    conclusion = "SKEW provides marginally significant incremental vol prediction, but effect is small"
elif abs(skew_t_stat_1d) > 1.96:
    conclusion = "SKEW is conventionally significant but fails Harvey (2016) threshold; incremental R² is negligible"
else:
    conclusion = "SKEW does NOT provide significant incremental vol prediction beyond VIX"

print(f"\n  CONCLUSION: {conclusion}")

# ============================================================
# 12. Save Results
# ============================================================
print("\n[12] Saving results...")

results = {
    'experiment_id': 'K979',
    'title': 'CBOE SKEW Index as Volatility Predictor',
    'data_source': 'yfinance (SPY, ^VIX, ^SKEW)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': int(len(df)),
    'is_period': '2010-2018',
    'oos_period': '2019-2026',
    'descriptive_stats': desc_stats,
    'correlations': {
        'vix_skew': float(corr_vix_skew),
        'vix_rv1': float(corr_vix_rv1),
        'skew_rv1': float(corr_skew_rv1)
    },
    'regression_results': regression_results,
    'dm_test': dm_results,
    'extreme_analysis': extreme_analysis,
    'quintile_stats': quintile_stats,
    'yearly_oos': yearly_results,
    'skew_thresholds': {
        'p05': float(skew_p05),
        'p10': float(skew_p10),
        'p90': float(skew_p90),
        'p95': float(skew_p95)
    },
    'conclusion': conclusion,
    'key_findings': {
        'skew_vix_corr': float(corr_vix_skew),
        'skew_beta_1d': float(skew_beta_1d),
        'skew_tstat_1d': float(skew_t_stat_1d),
        'delta_oos_r2_1d': float(delta_r2_1d),
        'delta_oos_r2_5d': float(delta_r2_5d),
        'delta_oos_r2_22d': float(delta_r2_22d),
        'dm_stat': float(dm_stat),
        'dm_pvalue': float(dm_pvalue),
        'harvey_significant': bool(abs(skew_t_stat_1d) > 3.0)
    },
    'seed': 42
}

with open(f'{SAVE_DIR}/k979_skew_vol_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("  Saved: k979_skew_vol_results.json")
print("\n[DONE] K979 experiment complete.")
