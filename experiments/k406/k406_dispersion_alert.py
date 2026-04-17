"""
K406: Vol Dispersion as Regime Shift Early Warning — Can It Beat VIX Alone?
==========================================================================
Follow-up to K405 (dispersion convergence t=10.17), K165 (dispersion level ~ VIX proxy),
K282 (VIX alert system), K394 (black swan AUC=0.87).

KEY INSIGHT: K165 found dispersion LEVEL is a VIX proxy (redundant).
But K405 found dispersion CHANGE (convergence) passes Harvey threshold.
This tests whether CHANGE in dispersion adds to VIX for early warning.

Data: yfinance — SPY, QQQ, GLD, TLT, EEM, IWM, ^VIX. 2005-2024.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K406: Vol Dispersion as Regime Shift Early Warning")
print("=" * 70)

tickers = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'IWM', '^VIX']
start_date = '2005-01-01'
end_date = '2024-12-31'

print(f"\nDownloading {tickers} from {start_date} to {end_date}...")
raw = yf.download(tickers, start=start_date, end=end_date, auto_adjust=True)

# Extract close prices
close = raw['Close'].dropna()
print(f"Data shape: {close.shape}")
print(f"Date range: {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}")
print(f"Trading days: {len(close)}")

# Separate VIX from assets
vix = close['^VIX']
assets = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'IWM']
prices = close[assets]

# ============================================================
# 2. COMPUTE FEATURES
# ============================================================
print("\n" + "=" * 70)
print("STEP 2: Computing vol dispersion and related features")
print("=" * 70)

# Daily returns
returns = prices.pct_change().dropna()

# Rolling 22-day realized vol for each asset
rolling_vols = returns.rolling(22).std() * np.sqrt(252)
rolling_vols = rolling_vols.dropna()

# Vol dispersion = std of rolling vols across 6 assets (cross-sectional)
vol_dispersion = rolling_vols.std(axis=1)
vol_dispersion.name = 'vol_dispersion'

# Vol dispersion CHANGE (K405 key finding: convergence matters)
disp_change = vol_dispersion.pct_change(5)  # 5-day change
disp_change.name = 'disp_change_5d'

# Dispersion convergence flag: when dispersion drops below 20th percentile
disp_20pct = vol_dispersion.expanding(min_periods=252).quantile(0.20)
convergence_flag = (vol_dispersion < disp_20pct).astype(int)
convergence_flag.name = 'convergence'

# SPY realized vol (future, for prediction target)
spy_returns = returns['SPY']
spy_rv_22d = spy_returns.rolling(22).std() * np.sqrt(252)
spy_rv_future = spy_rv_22d.shift(-22)  # 22 days ahead
spy_rv_future.name = 'spy_rv_future'

# Align VIX
vix_aligned = vix.reindex(rolling_vols.index)

# Build analysis DataFrame
df = pd.DataFrame({
    'vol_dispersion': vol_dispersion,
    'disp_change_5d': disp_change,
    'convergence': convergence_flag,
    'vix': vix_aligned,
    'spy_rv_future': spy_rv_future,
    'spy_rv_current': spy_rv_22d.reindex(rolling_vols.index),
}).dropna()

print(f"Analysis sample: {len(df)} observations")
print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Convergence days: {df['convergence'].sum()} ({df['convergence'].mean()*100:.1f}%)")

# ============================================================
# 3. PARTIAL CORRELATION: Does dispersion change ADD beyond VIX?
# ============================================================
print("\n" + "=" * 70)
print("STEP 3: Partial correlation — disp_change | VIX → future SPY RV")
print("=" * 70)

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Regress x on z
    slope_xz = np.polyfit(z, x, 1)
    resid_x = x - np.polyval(slope_xz, z)
    # Regress y on z
    slope_yz = np.polyfit(z, y, 1)
    resid_y = y - np.polyval(slope_yz, z)
    # Correlation of residuals
    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p

# Full sample partial correlation
x = df['disp_change_5d'].values
y = df['spy_rv_future'].values
z = df['vix'].values

r_partial, p_partial = partial_corr(x, y, z)
n = len(x)
t_stat = r_partial * np.sqrt((n - 3) / (1 - r_partial**2))

print(f"\nFull sample partial correlation:")
print(f"  partial r(disp_change_5d, future_SPY_RV | VIX) = {r_partial:.4f}")
print(f"  t-statistic = {t_stat:.2f}")
print(f"  p-value = {p_partial:.2e}")
print(f"  Harvey (2016) threshold (t > 3.0): {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}")
print(f"  n = {n}")

# Also test: dispersion LEVEL partial correlation (should be weak per K165)
r_level, p_level = partial_corr(df['vol_dispersion'].values, y, z)
t_level = r_level * np.sqrt((n - 3) / (1 - r_level**2))
print(f"\nComparison — dispersion LEVEL:")
print(f"  partial r(vol_dispersion, future_SPY_RV | VIX) = {r_level:.4f}")
print(f"  t-statistic = {t_level:.2f}")
print(f"  Confirms K165: level is {'redundant with VIX' if abs(t_level) < 3.0 else 'still informative'}")

# Also test: convergence flag (binary)
r_conv, p_conv = partial_corr(df['convergence'].values.astype(float), y, z)
t_conv = r_conv * np.sqrt((n - 3) / (1 - r_conv**2))
print(f"\nConvergence flag (binary):")
print(f"  partial r(convergence, future_SPY_RV | VIX) = {r_conv:.4f}")
print(f"  t-statistic = {t_conv:.2f}")

# ============================================================
# 4. EARLY WARNING: Lead time analysis
# ============================================================
print("\n" + "=" * 70)
print("STEP 4: Early warning — does convergence precede VIX spikes?")
print("=" * 70)

# Define VIX spike: VIX crosses above 25
vix_spike = (df['vix'] > 25) & (df['vix'].shift(1) <= 25)
spike_dates = df.index[vix_spike]
print(f"\nVIX spike events (crosses above 25): {len(spike_dates)}")

# For each VIX spike, look back up to 60 days for convergence signal
lead_times = []
convergence_before_spike = 0
no_convergence = 0

for spike_date in spike_dates:
    # Look back 60 trading days
    lookback_start = df.index.get_loc(spike_date) - 60
    lookback_end = df.index.get_loc(spike_date)
    if lookback_start < 0:
        continue

    window = df.iloc[lookback_start:lookback_end]
    conv_days = window[window['convergence'] == 1]

    if len(conv_days) > 0:
        # Most recent convergence day before spike
        last_conv = conv_days.index[-1]
        lead = (spike_date - last_conv).days
        lead_times.append(lead)
        convergence_before_spike += 1
    else:
        no_convergence += 1

print(f"\nSpikes with prior convergence (60d lookback): {convergence_before_spike}/{convergence_before_spike + no_convergence}")
if lead_times:
    print(f"  Mean lead time: {np.mean(lead_times):.1f} calendar days")
    print(f"  Median lead time: {np.median(lead_times):.1f} calendar days")
    print(f"  Std: {np.std(lead_times):.1f} days")
    print(f"  Range: {np.min(lead_times)}-{np.max(lead_times)} days")
    pct_with_signal = convergence_before_spike / (convergence_before_spike + no_convergence)
    print(f"  Detection rate: {pct_with_signal*100:.1f}%")
else:
    print("  No convergence signals found before spikes")
    pct_with_signal = 0.0

# ============================================================
# 5. COMBINED ALERT: VIX + Dispersion convergence
# ============================================================
print("\n" + "=" * 70)
print("STEP 5: Combined alert — VIX level + dispersion convergence")
print("=" * 70)

# Define "stress event" = SPY 22d realized vol > 25% (future)
stress_threshold = 0.25
actual_stress = (df['spy_rv_future'] > stress_threshold).astype(int)
total_stress = actual_stress.sum()
print(f"\nStress events (future SPY RV > 25%): {total_stress} ({actual_stress.mean()*100:.1f}%)")

# Alert 1: VIX only (VIX > 20)
vix_alert = (df['vix'] > 20).astype(int)
# Alert 2: Dispersion convergence only
disp_alert = df['convergence'].astype(int)
# Alert 3: VIX > 18 OR dispersion convergence (combined, lower VIX threshold)
combined_alert = ((df['vix'] > 18) | (df['convergence'] == 1)).astype(int)
# Alert 4: VIX > 20 AND NOT in convergence (VIX high but dispersion confirms)
# Actually let's think about this differently:
# Convergence = low dispersion = assets moving together = potential for contagion
# So combined = VIX elevated OR convergence happening
# Alert 5: Dispersion change < -20% (5d) — sharp convergence move
sharp_convergence = (df['disp_change_5d'] < df['disp_change_5d'].quantile(0.10)).astype(int)
combined_alert_v2 = ((df['vix'] > 18) | (sharp_convergence == 1)).astype(int)

def alert_metrics(alert_signal, actual, label):
    """Compute precision, recall, F1 for binary alert."""
    tp = ((alert_signal == 1) & (actual == 1)).sum()
    fp = ((alert_signal == 1) & (actual == 0)).sum()
    fn = ((alert_signal == 0) & (actual == 1)).sum()
    tn = ((alert_signal == 0) & (actual == 0)).sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    false_alarm_rate = fp / (fp + tn) if (fp + tn) > 0 else 0
    alert_rate = alert_signal.mean()

    print(f"  {label}:")
    print(f"    Alerts fired: {alert_signal.sum()} ({alert_rate*100:.1f}%)")
    print(f"    Precision: {precision:.3f}  Recall: {recall:.3f}  F1: {f1:.3f}")
    print(f"    False alarm rate: {false_alarm_rate:.3f}")
    return {'precision': precision, 'recall': recall, 'f1': f1,
            'false_alarm_rate': false_alarm_rate, 'alert_rate': alert_rate}

print(f"\nAlert system comparison (target: future SPY RV > 25%):")
print(f"{'='*60}")
m1 = alert_metrics(vix_alert, actual_stress, "VIX > 20 only")
print()
m2 = alert_metrics(disp_alert, actual_stress, "Dispersion convergence only")
print()
m3 = alert_metrics(combined_alert, actual_stress, "VIX > 18 OR convergence")
print()
m4 = alert_metrics(sharp_convergence, actual_stress, "Sharp convergence (10th pctile)")
print()
m5 = alert_metrics(combined_alert_v2, actual_stress, "VIX > 18 OR sharp convergence")

# ============================================================
# 6. REGRESSION: Incremental R² from dispersion change
# ============================================================
print("\n" + "=" * 70)
print("STEP 6: Incremental R² — does dispersion change improve on VIX?")
print("=" * 70)

from numpy.linalg import lstsq

def ols_r2(X, y):
    """Simple OLS R²."""
    X_with_const = np.column_stack([np.ones(len(X)), X])
    beta, _, _, _ = lstsq(X_with_const, y, rcond=None)
    y_hat = X_with_const @ beta
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2 = 1 - ss_res / ss_tot
    return r2, beta

y = df['spy_rv_future'].values

# Model 1: VIX only
X1 = df[['vix']].values
r2_vix, _ = ols_r2(X1, y)

# Model 2: VIX + dispersion change
X2 = df[['vix', 'disp_change_5d']].values
r2_vix_disp, _ = ols_r2(X2, y)

# Model 3: VIX + dispersion level
X3 = df[['vix', 'vol_dispersion']].values
r2_vix_level, _ = ols_r2(X3, y)

# Model 4: VIX + convergence flag
X4 = df[['vix', 'convergence']].values
r2_vix_conv, _ = ols_r2(X4, y)

# Model 5: VIX + dispersion change + convergence
X5 = df[['vix', 'disp_change_5d', 'convergence']].values
r2_full, _ = ols_r2(X5, y)

print(f"\nR² comparison for predicting future SPY RV (22d):")
print(f"  Model 1 (VIX only):                    R² = {r2_vix:.4f}")
print(f"  Model 2 (VIX + disp change):            R² = {r2_vix_disp:.4f}  (+{(r2_vix_disp - r2_vix)*100:.2f}pp)")
print(f"  Model 3 (VIX + disp level):             R² = {r2_vix_level:.4f}  (+{(r2_vix_level - r2_vix)*100:.2f}pp)")
print(f"  Model 4 (VIX + convergence flag):       R² = {r2_vix_conv:.4f}  (+{(r2_vix_conv - r2_vix)*100:.2f}pp)")
print(f"  Model 5 (VIX + disp change + conv):     R² = {r2_full:.4f}  (+{(r2_full - r2_vix)*100:.2f}pp)")

# F-test for incremental R² (Model 2 vs Model 1)
k_restricted = 1  # VIX only
k_full = 2  # VIX + disp_change
n_obs = len(y)
f_stat = ((r2_vix_disp - r2_vix) / (k_full - k_restricted)) / ((1 - r2_vix_disp) / (n_obs - k_full - 1))
f_pvalue = 1 - stats.f.cdf(f_stat, k_full - k_restricted, n_obs - k_full - 1)
print(f"\n  F-test (Model 2 vs 1): F = {f_stat:.2f}, p = {f_pvalue:.2e}")
print(f"  Incremental contribution: {'Significant' if f_pvalue < 0.01 else 'Not significant'}")

# ============================================================
# 7. OOS ROLLING VALIDATION (K266 protocol)
# ============================================================
print("\n" + "=" * 70)
print("STEP 7: OOS Rolling Validation")
print("=" * 70)

# Rolling OOS: train on 5 years, test on next 1 year
train_years = 5
test_years = 1
train_days = train_years * 252
test_days = test_years * 252

oos_results = []

idx = 0
while idx + train_days + test_days <= len(df):
    train = df.iloc[idx:idx + train_days]
    test = df.iloc[idx + train_days:idx + train_days + test_days]

    if len(test) < 100:
        break

    period_start = test.index[0].strftime('%Y-%m-%d')
    period_end = test.index[-1].strftime('%Y-%m-%d')

    # Train: fit OLS
    y_train = train['spy_rv_future'].values
    X_train_1 = train[['vix']].values
    X_train_2 = train[['vix', 'disp_change_5d']].values

    # Model 1: VIX only
    X1_c = np.column_stack([np.ones(len(X_train_1)), X_train_1])
    beta1, _, _, _ = lstsq(X1_c, y_train, rcond=None)

    # Model 2: VIX + disp change
    X2_c = np.column_stack([np.ones(len(X_train_2)), X_train_2])
    beta2, _, _, _ = lstsq(X2_c, y_train, rcond=None)

    # OOS predictions
    y_test = test['spy_rv_future'].values
    X_test_1 = np.column_stack([np.ones(len(test)), test[['vix']].values])
    X_test_2 = np.column_stack([np.ones(len(test)), test[['vix', 'disp_change_5d']].values])

    pred1 = X_test_1 @ beta1
    pred2 = X_test_2 @ beta2

    # OOS R² (relative to naive = mean of training target)
    y_bar = y_train.mean()
    ss_tot = np.sum((y_test - y_bar)**2)
    oos_r2_1 = 1 - np.sum((y_test - pred1)**2) / ss_tot
    oos_r2_2 = 1 - np.sum((y_test - pred2)**2) / ss_tot

    # MSE comparison
    mse1 = np.mean((y_test - pred1)**2)
    mse2 = np.mean((y_test - pred2)**2)

    # Diebold-Mariano style: paired difference
    e1 = (y_test - pred1)**2
    e2 = (y_test - pred2)**2
    d = e1 - e2  # positive = Model 2 better
    dm_t = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))

    oos_results.append({
        'period': f"{period_start} to {period_end}",
        'n': len(test),
        'oos_r2_vix': oos_r2_1,
        'oos_r2_combined': oos_r2_2,
        'mse_vix': mse1,
        'mse_combined': mse2,
        'dm_t': dm_t,
        'mse_improvement_pct': (mse1 - mse2) / mse1 * 100
    })

    idx += test_days  # roll by 1 year

print(f"\nOOS Rolling Results ({len(oos_results)} periods, {train_years}y train / {test_years}y test):")
print(f"{'Period':<30} {'OOS R² VIX':>12} {'OOS R² Comb':>12} {'MSE Impr%':>10} {'DM-t':>8}")
print("-" * 75)

dm_t_values = []
improvements = []
for r in oos_results:
    print(f"{r['period']:<30} {r['oos_r2_vix']:>12.4f} {r['oos_r2_combined']:>12.4f} {r['mse_improvement_pct']:>10.2f} {r['dm_t']:>8.2f}")
    dm_t_values.append(r['dm_t'])
    improvements.append(r['mse_improvement_pct'])

print("-" * 75)
avg_improvement = np.mean(improvements)
periods_better = sum(1 for x in improvements if x > 0)
avg_dm_t = np.mean(dm_t_values)
print(f"{'Average':<30} {'':>12} {'':>12} {avg_improvement:>10.2f} {avg_dm_t:>8.2f}")
print(f"\nPeriods where combined model wins: {periods_better}/{len(oos_results)}")
print(f"Average DM t-stat: {avg_dm_t:.2f} ({'Significant' if abs(avg_dm_t) > 1.96 else 'Not significant'})")

# ============================================================
# 8. CONDITIONAL ANALYSIS: Is dispersion useful in specific regimes?
# ============================================================
print("\n" + "=" * 70)
print("STEP 8: Conditional analysis — when does dispersion help most?")
print("=" * 70)

# Split by VIX regime
vix_low = df['vix'] < 15
vix_mid = (df['vix'] >= 15) & (df['vix'] < 25)
vix_high = df['vix'] >= 25

for regime, mask, label in [(vix_low, vix_low, 'VIX < 15 (calm)'),
                              (vix_mid, vix_mid, '15 ≤ VIX < 25 (normal)'),
                              (vix_high, vix_high, 'VIX ≥ 25 (stressed)')]:
    sub = df[mask]
    if len(sub) < 100:
        print(f"\n  {label}: too few observations ({len(sub)})")
        continue

    x_sub = sub['disp_change_5d'].values
    y_sub = sub['spy_rv_future'].values
    z_sub = sub['vix'].values

    r_p, p_p = partial_corr(x_sub, y_sub, z_sub)
    n_sub = len(sub)
    t_sub = r_p * np.sqrt((n_sub - 3) / (1 - r_p**2))

    print(f"\n  {label} (n={n_sub}):")
    print(f"    partial r = {r_p:.4f}, t = {t_sub:.2f}, p = {p_p:.4f}")
    print(f"    Harvey threshold: {'PASS' if abs(t_sub) > 3.0 else 'FAIL'}")

# ============================================================
# 9. BOOTSTRAP CONFIDENCE INTERVALS
# ============================================================
print("\n" + "=" * 70)
print("STEP 9: Bootstrap confidence intervals (10,000 reps)")
print("=" * 70)

np.random.seed(42)
n_boot = 10000
boot_partial_r = np.zeros(n_boot)
boot_incr_r2 = np.zeros(n_boot)

x_full = df['disp_change_5d'].values
y_full = df['spy_rv_future'].values
z_full = df['vix'].values

for b in range(n_boot):
    idx_boot = np.random.choice(len(df), size=len(df), replace=True)
    xb, yb, zb = x_full[idx_boot], y_full[idx_boot], z_full[idx_boot]

    # Partial correlation
    r_b, _ = partial_corr(xb, yb, zb)
    boot_partial_r[b] = r_b

    # Incremental R²
    X1b = zb.reshape(-1, 1)
    X2b = np.column_stack([zb, xb])
    r2_1b, _ = ols_r2(X1b, yb)
    r2_2b, _ = ols_r2(X2b, yb)
    boot_incr_r2[b] = r2_2b - r2_1b

ci_r_low, ci_r_high = np.percentile(boot_partial_r, [2.5, 97.5])
ci_r2_low, ci_r2_high = np.percentile(boot_incr_r2, [2.5, 97.5])

print(f"\nPartial r(disp_change | VIX):")
print(f"  Point estimate: {r_partial:.4f}")
print(f"  95% CI: [{ci_r_low:.4f}, {ci_r_high:.4f}]")
print(f"  CI excludes zero: {'Yes' if ci_r_low > 0 or ci_r_high < 0 else 'No'}")

print(f"\nIncremental R²:")
print(f"  Point estimate: {(r2_vix_disp - r2_vix)*100:.2f} pp")
print(f"  95% CI: [{ci_r2_low*100:.2f}, {ci_r2_high*100:.2f}] pp")
print(f"  CI excludes zero: {'Yes' if ci_r2_low > 0 or ci_r2_high < 0 else 'No'}")

# ============================================================
# 10. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K406 SUMMARY")
print("=" * 70)

print(f"""
DATA:
  Assets: {assets}
  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}
  Observations: {len(df)}
  Source: yfinance (real market data)

PARTIAL CORRELATION (disp_change_5d → future SPY RV | VIX):
  partial r = {r_partial:.4f}, t = {t_stat:.2f}
  Harvey (2016) t > 3.0: {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}
  Bootstrap 95% CI: [{ci_r_low:.4f}, {ci_r_high:.4f}]

  vs dispersion LEVEL: partial r = {r_level:.4f}, t = {t_level:.2f}
  → Change is {'more' if abs(r_partial) > abs(r_level) else 'less'} informative than level

EARLY WARNING (convergence → VIX spike):
  VIX spike events: {len(spike_dates)}
  Convergence detected before spike: {convergence_before_spike}/{convergence_before_spike + no_convergence} ({pct_with_signal*100:.0f}%)
  Mean lead time: {np.mean(lead_times):.1f} days (when detected)

INCREMENTAL R²:
  VIX alone: R² = {r2_vix:.4f}
  VIX + disp change: R² = {r2_vix_disp:.4f} (+{(r2_vix_disp - r2_vix)*100:.2f} pp)
  F-test p-value: {f_pvalue:.2e}

ALERT SYSTEM (target: SPY RV > 25%):
  VIX > 20:                  F1 = {m1['f1']:.3f}, FAR = {m1['false_alarm_rate']:.3f}
  Convergence only:          F1 = {m2['f1']:.3f}, FAR = {m2['false_alarm_rate']:.3f}
  VIX>18 OR convergence:     F1 = {m3['f1']:.3f}, FAR = {m3['false_alarm_rate']:.3f}
  VIX>18 OR sharp conv:      F1 = {m5['f1']:.3f}, FAR = {m5['false_alarm_rate']:.3f}

OOS ROLLING VALIDATION:
  Periods where combined beats VIX-only: {periods_better}/{len(oos_results)}
  Average MSE improvement: {avg_improvement:.2f}%
  Average DM t-stat: {avg_dm_t:.2f}
""")

# Assessment
pass_count = 0
if abs(t_stat) > 3.0:
    pass_count += 1
if ci_r_low > 0 or ci_r_high < 0:
    pass_count += 1
if f_pvalue < 0.01:
    pass_count += 1
if periods_better > len(oos_results) / 2:
    pass_count += 1
if m3['f1'] > m1['f1']:
    pass_count += 1

print(f"QUALITY GATES PASSED: {pass_count}/5")
print(f"  [{'X' if abs(t_stat) > 3.0 else ' '}] Harvey threshold (t > 3.0)")
print(f"  [{'X' if ci_r_low > 0 or ci_r_high < 0 else ' '}] Bootstrap CI excludes zero")
print(f"  [{'X' if f_pvalue < 0.01 else ' '}] F-test significant (p < 0.01)")
print(f"  [{'X' if periods_better > len(oos_results) / 2 else ' '}] OOS majority wins")
print(f"  [{'X' if m3['f1'] > m1['f1'] else ' '}] Combined alert F1 > VIX-only F1")

verdict = "POSITIVE" if pass_count >= 3 else "MIXED" if pass_count >= 2 else "NEGATIVE"
print(f"\nOVERALL VERDICT: {verdict}")
print(f"Vol dispersion change {'adds useful information' if pass_count >= 3 else 'has limited incremental value' if pass_count >= 2 else 'does not add'} beyond VIX alone for regime shift early warning.")

# Save results
results = {
    'experiment': 'K406',
    'title': 'Vol Dispersion as Regime Shift Early Warning',
    'data_source': 'yfinance',
    'assets': assets,
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df),
    'partial_correlation': {
        'disp_change_5d': {'r': round(r_partial, 4), 't': round(t_stat, 2), 'p': float(f'{p_partial:.2e}')},
        'disp_level': {'r': round(r_level, 4), 't': round(t_level, 2)},
        'convergence_flag': {'r': round(r_conv, 4), 't': round(t_conv, 2)},
    },
    'bootstrap_ci': {
        'partial_r': [round(ci_r_low, 4), round(ci_r_high, 4)],
        'incremental_r2_pp': [round(ci_r2_low * 100, 2), round(ci_r2_high * 100, 2)],
    },
    'early_warning': {
        'vix_spikes': len(spike_dates),
        'detection_rate': round(pct_with_signal, 3),
        'mean_lead_days': round(np.mean(lead_times), 1) if lead_times else None,
    },
    'incremental_r2': {
        'vix_only': round(r2_vix, 4),
        'vix_plus_disp_change': round(r2_vix_disp, 4),
        'increment_pp': round((r2_vix_disp - r2_vix) * 100, 2),
        'f_test_p': float(f'{f_pvalue:.2e}'),
    },
    'alert_comparison': {
        'vix_only': {k: round(v, 3) for k, v in m1.items()},
        'convergence_only': {k: round(v, 3) for k, v in m2.items()},
        'combined_v1': {k: round(v, 3) for k, v in m3.items()},
        'combined_v2': {k: round(v, 3) for k, v in m5.items()},
    },
    'oos_validation': {
        'periods_better': periods_better,
        'total_periods': len(oos_results),
        'avg_mse_improvement_pct': round(avg_improvement, 2),
        'avg_dm_t': round(avg_dm_t, 2),
    },
    'quality_gates_passed': pass_count,
    'verdict': verdict,
}

with open('experiments/k406_dispersion_alert_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to experiments/k406_dispersion_alert_results.json")
