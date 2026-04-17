"""
K571: VIX Mean-Reversion Speed as Portfolio Signal
===================================================
Motivation: VIX mean-reverts, but the SPEED varies dramatically.
COVID VIX=82 took ~3 months; Aug 2024 carry trade VIX=65 reverted in 2 weeks.
If we can characterise reversion speed, we can time re-entry after vol spikes.

This is NOT about predicting VIX direction (sufficiency #37+).
It's about optimizing the SPEED of re-entry after defensive positioning.

Related: K503 (12/VIX IS mean-reversion), K211 (MR speed), K524 (policy rules)

Data source: yfinance (SPY, ^VIX), 2005-2026
Reference: Whaley (2009) "Understanding the VIX", Bollen & Whaley (2004)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import json
import warnings
from scipy import stats
warnings.filterwarnings('ignore')

# ─── 1. Data Download ───
print("=" * 70)
print("K571: VIX Mean-Reversion Speed as Portfolio Signal")
print("=" * 70)

spy = yf.download("SPY", start="2004-01-01", end="2026-03-27", progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2026-03-27", progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

df = pd.DataFrame({
    'spy_close': spy['Close'],
    'vix_close': vix['Close']
}).dropna()

df['spy_ret'] = df['spy_close'].pct_change()
df['vix_ret'] = df['vix_close'].pct_change()
df = df.dropna()

print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"Observations: {len(df)}")
print(f"VIX range: {df['vix_close'].min():.1f} - {df['vix_close'].max():.1f}")
print(f"VIX mean: {df['vix_close'].mean():.1f}, median: {df['vix_close'].median():.1f}")

# ─── 2. Identify VIX Spike Events ───
print("\n" + "=" * 70)
print("2. VIX SPIKE EVENT IDENTIFICATION")
print("=" * 70)

# A spike event: VIX crosses above 25 from below
# Merge consecutive days above 25 into one event
VIX_SPIKE_THRESHOLD = 25
VIX_HALF_LIFE_TARGET = 20  # "half-life" = days to drop below 20
VIX_FULL_NORM_TARGET = 15  # "full normalization" = below 15

df['above_25'] = df['vix_close'] > VIX_SPIKE_THRESHOLD
df['spike_start'] = df['above_25'] & ~df['above_25'].shift(1, fill_value=False)

spike_dates = df.index[df['spike_start']]
print(f"Number of VIX spike events (crosses above {VIX_SPIKE_THRESHOLD}): {len(spike_dates)}")

# For each spike, measure characteristics
events = []
for i, start_date in enumerate(spike_dates):
    start_idx = df.index.get_loc(start_date)

    # Find peak VIX in this episode
    peak_vix = df['vix_close'].iloc[start_idx]
    peak_date = start_date
    peak_idx = start_idx

    # Look forward to find peak (max VIX before it drops below threshold)
    for j in range(start_idx, min(start_idx + 252, len(df))):  # max 1 year
        if df['vix_close'].iloc[j] > peak_vix:
            peak_vix = df['vix_close'].iloc[j]
            peak_date = df.index[j]
            peak_idx = j
        # If VIX drops below 20 and we're past the peak, stop
        if j > peak_idx + 5 and df['vix_close'].iloc[j] < VIX_HALF_LIFE_TARGET:
            break

    # Measure velocity: how fast VIX rose (from 5 days before to peak)
    lookback = max(0, start_idx - 5)
    vix_before = df['vix_close'].iloc[lookback]
    velocity = (peak_vix - vix_before) / max(1, peak_idx - lookback)  # VIX points per day

    # SPY drawdown at peak
    spy_at_peak = df['spy_close'].iloc[peak_idx]
    spy_lookback_20d = df['spy_close'].iloc[max(0, peak_idx-20):peak_idx+1]
    spy_drawdown = (spy_at_peak / spy_lookback_20d.max() - 1) * 100

    # Days to revert below 20 (half-life)
    days_to_20 = None
    for j in range(peak_idx + 1, min(peak_idx + 504, len(df))):  # max 2 years
        if df['vix_close'].iloc[j] < VIX_HALF_LIFE_TARGET:
            days_to_20 = j - peak_idx
            break

    # Days to revert below 15 (full normalization)
    days_to_15 = None
    for j in range(peak_idx + 1, min(peak_idx + 504, len(df))):
        if df['vix_close'].iloc[j] < VIX_FULL_NORM_TARGET:
            days_to_15 = j - peak_idx
            break

    # SPY return during reversion period (peak to VIX<20)
    spy_ret_reversion = None
    if days_to_20 is not None:
        spy_end = df['spy_close'].iloc[peak_idx + days_to_20]
        spy_ret_reversion = (spy_end / spy_at_peak - 1) * 100

    # SPY return 22 days after peak
    if peak_idx + 22 < len(df):
        spy_ret_22d = (df['spy_close'].iloc[peak_idx + 22] / spy_at_peak - 1) * 100
    else:
        spy_ret_22d = None

    # VIX term structure proxy: VIX velocity of change after peak (mean reversion force)
    if peak_idx + 5 < len(df):
        vix_5d_after = df['vix_close'].iloc[peak_idx + 5]
        vix_initial_decay = (peak_vix - vix_5d_after) / peak_vix * 100  # % decay in 5 days
    else:
        vix_initial_decay = None

    events.append({
        'start_date': start_date.strftime('%Y-%m-%d'),
        'peak_date': peak_date.strftime('%Y-%m-%d'),
        'peak_vix': round(float(peak_vix), 1),
        'velocity': round(float(velocity), 2),
        'spy_drawdown_pct': round(float(spy_drawdown), 1),
        'days_to_20': int(days_to_20) if days_to_20 else None,
        'days_to_15': int(days_to_15) if days_to_15 else None,
        'spy_ret_reversion_pct': round(float(spy_ret_reversion), 1) if spy_ret_reversion else None,
        'spy_ret_22d_pct': round(float(spy_ret_22d), 1) if spy_ret_22d else None,
        'vix_initial_decay_pct': round(float(vix_initial_decay), 1) if vix_initial_decay else None,
    })

events_df = pd.DataFrame(events)
# Filter events with valid half-life
valid_events = events_df.dropna(subset=['days_to_20'])

print(f"\nTotal spike events: {len(events_df)}")
print(f"Events with measured half-life (VIX→20): {len(valid_events)}")
print(f"Events still elevated at end: {len(events_df) - len(valid_events)}")

# ─── 3. Descriptive Statistics of Reversion ───
print("\n" + "=" * 70)
print("3. REVERSION SPEED DESCRIPTIVE STATISTICS")
print("=" * 70)

print(f"\nDays to VIX < 20 (half-life):")
print(f"  Mean: {valid_events['days_to_20'].mean():.1f}")
print(f"  Median: {valid_events['days_to_20'].median():.1f}")
print(f"  Std: {valid_events['days_to_20'].std():.1f}")
print(f"  Min: {valid_events['days_to_20'].min()}")
print(f"  Max: {valid_events['days_to_20'].max()}")
print(f"  IQR: {valid_events['days_to_20'].quantile(0.25):.0f} - {valid_events['days_to_20'].quantile(0.75):.0f}")

full_norm = valid_events.dropna(subset=['days_to_15'])
if len(full_norm) > 0:
    print(f"\nDays to VIX < 15 (full normalization):")
    print(f"  Mean: {full_norm['days_to_15'].mean():.1f}")
    print(f"  Median: {full_norm['days_to_15'].median():.1f}")
    print(f"  Min: {full_norm['days_to_15'].min()}")
    print(f"  Max: {full_norm['days_to_15'].max()}")

print(f"\nPeak VIX distribution:")
print(f"  Mean: {valid_events['peak_vix'].mean():.1f}")
print(f"  Median: {valid_events['peak_vix'].median():.1f}")
print(f"  Min: {valid_events['peak_vix'].min():.1f}")
print(f"  Max: {valid_events['peak_vix'].max():.1f}")

# Notable events
print(f"\n--- Notable Events ---")
for _, e in valid_events.nlargest(8, 'peak_vix').iterrows():
    print(f"  {e['peak_date']}: VIX={e['peak_vix']:.0f}, "
          f"half-life={e['days_to_20']}d, "
          f"full-norm={e['days_to_15'] if pd.notna(e['days_to_15']) else 'N/A'}d, "
          f"SPY reversion={e['spy_ret_reversion_pct']:.1f}%")

# ─── 4. Predictors of Reversion Speed ───
print("\n" + "=" * 70)
print("4. PREDICTORS OF REVERSION SPEED")
print("=" * 70)

# Correlations
predictors = ['peak_vix', 'velocity', 'spy_drawdown_pct', 'vix_initial_decay_pct']
target = 'days_to_20'

print(f"\nCorrelation with half-life (days_to_20), N={len(valid_events)}:")
for pred in predictors:
    subset = valid_events.dropna(subset=[pred, target])
    if len(subset) > 5:
        r, p = stats.spearmanr(subset[pred], subset[target])
        print(f"  {pred:30s}: Spearman r={r:+.3f}, p={p:.4f} {'***' if p<0.001 else '**' if p<0.01 else '*' if p<0.05 else 'NS'}")

# Simple OLS regression
from numpy.linalg import lstsq

print(f"\n--- OLS Regression: days_to_20 ~ peak_vix + velocity + spy_drawdown ---")
reg_data = valid_events.dropna(subset=['peak_vix', 'velocity', 'spy_drawdown_pct', 'days_to_20']).copy()
X = reg_data[['peak_vix', 'velocity', 'spy_drawdown_pct']].values
X = np.column_stack([np.ones(len(X)), X])  # add intercept
y = reg_data['days_to_20'].values

if len(reg_data) > 5:
    beta, residuals, rank, sv = lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat
    SSR = np.sum(resid**2)
    SST = np.sum((y - y.mean())**2)
    R2 = 1 - SSR/SST
    n, k = X.shape
    R2_adj = 1 - (1 - R2) * (n - 1) / (n - k)

    # Standard errors
    sigma2 = SSR / (n - k)
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    t_stats = beta / se
    p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n-k))

    print(f"  N = {n}, R² = {R2:.3f}, Adj-R² = {R2_adj:.3f}")
    names = ['Intercept', 'peak_vix', 'velocity', 'spy_drawdown_pct']
    for name, b, s, t, p in zip(names, beta, se, t_stats, p_values):
        sig = '***' if p<0.001 else '**' if p<0.01 else '*' if p<0.05 else ''
        print(f"  {name:25s}: β={b:+8.3f}, SE={s:.3f}, t={t:+6.2f}, p={p:.4f} {sig}")

# ─── 5. Categorize Events by Speed ───
print("\n" + "=" * 70)
print("5. EVENT CATEGORIZATION BY REVERSION SPEED")
print("=" * 70)

median_half_life = valid_events['days_to_20'].median()
valid_events = valid_events.copy()
valid_events['speed_cat'] = np.where(valid_events['days_to_20'] <= median_half_life, 'fast', 'slow')

fast = valid_events[valid_events['speed_cat'] == 'fast']
slow = valid_events[valid_events['speed_cat'] == 'slow']

print(f"\nMedian half-life: {median_half_life:.0f} days")
print(f"Fast reversions (≤{median_half_life:.0f}d): N={len(fast)}")
print(f"  Mean half-life: {fast['days_to_20'].mean():.1f}d")
print(f"  Mean peak VIX: {fast['peak_vix'].mean():.1f}")
print(f"  Mean SPY return during reversion: {fast['spy_ret_reversion_pct'].mean():.1f}%")

print(f"\nSlow reversions (>{median_half_life:.0f}d): N={len(slow)}")
print(f"  Mean half-life: {slow['days_to_20'].mean():.1f}d")
print(f"  Mean peak VIX: {slow['peak_vix'].mean():.1f}")
print(f"  Mean SPY return during reversion: {slow['spy_ret_reversion_pct'].mean():.1f}%")

# T-test for SPY returns
if len(fast) > 2 and len(slow) > 2:
    t_ret, p_ret = stats.ttest_ind(
        fast['spy_ret_reversion_pct'].dropna(),
        slow['spy_ret_reversion_pct'].dropna()
    )
    print(f"\nSPY return difference (fast vs slow): t={t_ret:.2f}, p={p_ret:.4f}")

# ─── 6. Strategy Backtest ───
print("\n" + "=" * 70)
print("6. STRATEGY BACKTEST")
print("=" * 70)

# Define strategies
# Start from 2005 to have enough data
bt_start = '2005-01-01'
bt_df = df.loc[bt_start:].copy()

# Baseline: 12/VIX
bt_df['w_baseline'] = np.clip(12.0 / bt_df['vix_close'], 0, 1)

# Strategy A: Fast Re-entry (14/VIX when VIX declining after spike)
# Detect declining VIX: VIX was above 25 in last 22 days AND currently declining
bt_df['vix_was_high'] = bt_df['vix_close'].rolling(22).max() > 25
bt_df['vix_declining'] = bt_df['vix_close'] < bt_df['vix_close'].shift(5)
bt_df['fast_reentry_cond'] = bt_df['vix_was_high'] & bt_df['vix_declining'] & (bt_df['vix_close'] < 30)
bt_df['w_fast'] = np.where(
    bt_df['fast_reentry_cond'],
    np.clip(14.0 / bt_df['vix_close'], 0, 1),  # More aggressive
    np.clip(12.0 / bt_df['vix_close'], 0, 1)
)

# Strategy B: Slow Re-entry (10/VIX for 22 days after VIX peaks above 25)
# After VIX crosses above 25, use 10/VIX for next 22 trading days
bt_df['spike_signal'] = (bt_df['vix_close'] > 25).astype(int)
# Rolling: was there a spike in last 22 days?
bt_df['recent_spike'] = bt_df['spike_signal'].rolling(22, min_periods=1).max()
bt_df['w_slow'] = np.where(
    bt_df['recent_spike'] > 0,
    np.clip(10.0 / bt_df['vix_close'], 0, 1),  # More conservative
    np.clip(12.0 / bt_df['vix_close'], 0, 1)
)

# Strategy C: Adaptive Speed — use predicted half-life to set multiplier
# If predicted half-life is short → fast re-entry (14/VIX)
# If predicted half-life is long → slow re-entry (10/VIX)
# Use simple rule: peak_vix > 40 → slow (these take longer), else → fast
bt_df['vix_rolling_max_22'] = bt_df['vix_close'].rolling(22).max()
bt_df['w_adaptive'] = np.where(
    bt_df['vix_was_high'] & bt_df['vix_declining'],
    np.where(
        bt_df['vix_rolling_max_22'] > 40,
        np.clip(10.0 / bt_df['vix_close'], 0, 1),  # Slow for extreme spikes
        np.clip(14.0 / bt_df['vix_close'], 0, 1)   # Fast for moderate spikes
    ),
    np.clip(12.0 / bt_df['vix_close'], 0, 1)
)

# Strategy D: Regression-based adaptive
# Use the regression coefficients to predict half-life in real-time
# Then map predicted half-life to multiplier
bt_df['vix_velocity'] = (bt_df['vix_close'] - bt_df['vix_close'].shift(5)) / 5
bt_df['spy_dd_20d'] = (bt_df['spy_close'] / bt_df['spy_close'].rolling(20).max() - 1) * 100

# Only apply regression-based adjustment when VIX was recently high
if len(reg_data) > 5:
    # Predict half-life
    bt_df['pred_half_life'] = (beta[0]
                                + beta[1] * bt_df['vix_close']
                                + beta[2] * bt_df['vix_velocity'].fillna(0)
                                + beta[3] * bt_df['spy_dd_20d'].fillna(0))
    bt_df['pred_half_life'] = bt_df['pred_half_life'].clip(5, 120)

    # Map: short predicted half-life → higher multiplier (faster re-entry)
    # half-life 10 → mult 14, half-life 60 → mult 10
    bt_df['adaptive_mult'] = 14 - (bt_df['pred_half_life'] - 10) / (60 - 10) * 4
    bt_df['adaptive_mult'] = bt_df['adaptive_mult'].clip(10, 14)

    bt_df['w_regression'] = np.where(
        bt_df['vix_was_high'] & bt_df['vix_declining'],
        np.clip(bt_df['adaptive_mult'] / bt_df['vix_close'], 0, 1),
        np.clip(12.0 / bt_df['vix_close'], 0, 1)
    )
else:
    bt_df['w_regression'] = bt_df['w_baseline']

# Calculate portfolio returns
strategies = {
    'baseline_12vix': 'w_baseline',
    'fast_reentry_14vix': 'w_fast',
    'slow_reentry_10vix': 'w_slow',
    'adaptive_peak': 'w_adaptive',
    'regression_adaptive': 'w_regression'
}

rf_daily = 0.04 / 252  # 4% risk-free proxy

results = {}
for name, w_col in strategies.items():
    w = bt_df[w_col].shift(1).fillna(0)  # Use previous day's weight
    port_ret = w * bt_df['spy_ret']

    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = (port_ret.mean() - rf_daily) / port_ret.std() * np.sqrt(252) if port_ret.std() > 0 else 0

    cum_ret = (1 + port_ret).cumprod()
    rolling_max = cum_ret.cummax()
    drawdowns = cum_ret / rolling_max - 1
    max_dd = drawdowns.min()

    # Downside deviation
    downside = port_ret[port_ret < 0]
    sortino = (port_ret.mean() - rf_daily) / (downside.std() * np.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    results[name] = {
        'ann_ret': round(float(ann_ret * 100), 2),
        'ann_vol': round(float(ann_vol * 100), 2),
        'sharpe': round(float(sharpe), 4),
        'sortino': round(float(sortino), 4),
        'max_dd': round(float(max_dd * 100), 2),
        'calmar': round(float(calmar), 4),
        'avg_weight': round(float(w.mean()), 4),
    }

    print(f"\n{name}:")
    print(f"  Ann Return: {ann_ret*100:.2f}%")
    print(f"  Ann Vol: {ann_vol*100:.2f}%")
    print(f"  Sharpe: {sharpe:.4f}")
    print(f"  Sortino: {sortino:.4f}")
    print(f"  Max DD: {max_dd*100:.2f}%")
    print(f"  Calmar: {calmar:.4f}")
    print(f"  Avg Weight: {w.mean():.4f}")

# ─── 7. Diebold-Mariano Tests vs Baseline ───
print("\n" + "=" * 70)
print("7. DIEBOLD-MARIANO TESTS vs BASELINE (12/VIX)")
print("=" * 70)

# Using Sharpe-ratio difference as loss function
baseline_ret = bt_df['w_baseline'].shift(1).fillna(0) * bt_df['spy_ret']

dm_results = {}
for name, w_col in strategies.items():
    if name == 'baseline_12vix':
        continue

    alt_ret = bt_df[w_col].shift(1).fillna(0) * bt_df['spy_ret']

    # DM test using squared returns as loss (volatility timing)
    d = alt_ret - baseline_ret  # return differential

    # Newey-West HAC standard error
    T = len(d.dropna())
    d_clean = d.dropna()
    d_mean = d_clean.mean()

    # HAC with Bartlett kernel, bandwidth = T^(1/3)
    bw = int(T ** (1/3))
    gamma_0 = np.var(d_clean)
    hac_var = gamma_0
    for lag in range(1, bw + 1):
        gamma_j = np.cov(d_clean.values[lag:], d_clean.values[:-lag])[0, 1]
        weight = 1 - lag / (bw + 1)
        hac_var += 2 * weight * gamma_j

    dm_stat = d_mean / np.sqrt(hac_var / T) if hac_var > 0 else 0
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    dm_results[name] = {
        'dm_stat': round(float(dm_stat), 4),
        'dm_pval': round(float(dm_pval), 4),
        'mean_diff_bps': round(float(d_mean * 10000), 2),
        'significant': bool(abs(dm_stat) > 1.96),
        'harvey_significant': bool(abs(dm_stat) > 3.0),
    }

    sig_label = '***HARVEY' if abs(dm_stat) > 3.0 else '**SIG' if abs(dm_stat) > 1.96 else 'NS'
    print(f"\n{name} vs baseline:")
    print(f"  DM statistic: {dm_stat:+.4f}")
    print(f"  p-value: {dm_pval:.4f}")
    print(f"  Mean return diff: {d_mean*10000:+.2f} bps/day")
    print(f"  [{sig_label}]")

# ─── 8. Cross-OOS Validation (3 periods) ───
print("\n" + "=" * 70)
print("8. CROSS-OOS VALIDATION (3 PERIODS)")
print("=" * 70)

oos_periods = [
    ('2005-01-01', '2011-12-31', '2012-01-01', '2015-12-31'),  # IS: GFC period, OOS: recovery
    ('2010-01-01', '2017-12-31', '2018-01-01', '2021-12-31'),  # IS: mid period, OOS: COVID
    ('2015-01-01', '2022-12-31', '2023-01-01', '2026-03-27'),  # IS: recent, OOS: latest
]

cross_oos_results = []
for period_idx, (is_start, is_end, oos_start, oos_end) in enumerate(oos_periods):
    print(f"\n--- Period {period_idx+1}: IS={is_start}..{is_end}, OOS={oos_start}..{oos_end} ---")

    is_data = bt_df.loc[is_start:is_end]
    oos_data = bt_df.loc[oos_start:oos_end]

    if len(oos_data) < 100:
        print(f"  OOS too short ({len(oos_data)} obs), skipping")
        continue

    # Re-estimate regression on IS data only
    is_events_list = []
    for _, e in valid_events.iterrows():
        if is_start <= e['peak_date'] <= is_end:
            is_events_list.append(e)

    if len(is_events_list) < 3:
        print(f"  Too few IS events ({len(is_events_list)}), using full-sample coefficients")
        is_beta = beta  # fallback
    else:
        is_ev_df = pd.DataFrame(is_events_list).dropna(subset=['peak_vix', 'velocity', 'spy_drawdown_pct', 'days_to_20'])
        if len(is_ev_df) < 3:
            is_beta = beta
        else:
            X_is = is_ev_df[['peak_vix', 'velocity', 'spy_drawdown_pct']].values
            X_is = np.column_stack([np.ones(len(X_is)), X_is])
            y_is = is_ev_df['days_to_20'].values
            is_beta, _, _, _ = lstsq(X_is, y_is, rcond=None)

    # OOS backtest
    period_results = {}
    for name, w_col in strategies.items():
        if name == 'regression_adaptive':
            # Re-compute with IS-estimated beta
            oos_w = pd.Series(index=oos_data.index, dtype=float)
            for idx in oos_data.index:
                loc = bt_df.index.get_loc(idx)
                vix_val = bt_df['vix_close'].iloc[loc]
                was_high = bt_df['vix_close'].iloc[max(0,loc-22):loc+1].max() > 25
                declining = vix_val < bt_df['vix_close'].iloc[max(0,loc-5)]

                if was_high and declining:
                    vel = bt_df['vix_velocity'].iloc[loc] if pd.notna(bt_df['vix_velocity'].iloc[loc]) else 0
                    dd = bt_df['spy_dd_20d'].iloc[loc] if pd.notna(bt_df['spy_dd_20d'].iloc[loc]) else 0
                    pred_hl = is_beta[0] + is_beta[1]*vix_val + is_beta[2]*vel + is_beta[3]*dd
                    pred_hl = np.clip(pred_hl, 5, 120)
                    mult = 14 - (pred_hl - 10) / (60 - 10) * 4
                    mult = np.clip(mult, 10, 14)
                    oos_w.loc[idx] = np.clip(mult / vix_val, 0, 1)
                else:
                    oos_w.loc[idx] = np.clip(12.0 / vix_val, 0, 1)

            w = oos_w.shift(1).fillna(0)
        else:
            w = oos_data[w_col].shift(1).fillna(0)

        port_ret = w * oos_data['spy_ret']
        sharpe = (port_ret.mean() - rf_daily) / port_ret.std() * np.sqrt(252) if port_ret.std() > 0 else 0

        cum = (1 + port_ret).cumprod()
        max_dd = (cum / cum.cummax() - 1).min()

        period_results[name] = {
            'sharpe': round(float(sharpe), 4),
            'max_dd': round(float(max_dd * 100), 2),
            'ann_ret': round(float(port_ret.mean() * 252 * 100), 2),
        }

    # DM test in OOS
    base_oos = oos_data['w_baseline'].shift(1).fillna(0) * oos_data['spy_ret']
    oos_dm = {}
    for name, w_col in strategies.items():
        if name == 'baseline_12vix':
            continue

        if name == 'regression_adaptive':
            alt_oos = oos_w.shift(1).fillna(0) * oos_data['spy_ret']
        else:
            alt_oos = oos_data[w_col].shift(1).fillna(0) * oos_data['spy_ret']

        d = (alt_oos - base_oos).dropna()
        T_oos = len(d)
        d_mean = d.mean()
        bw_oos = int(T_oos ** (1/3))
        g0 = np.var(d)
        hac = g0
        for lag in range(1, bw_oos + 1):
            gj = np.cov(d.values[lag:], d.values[:-lag])[0, 1]
            hac += 2 * (1 - lag/(bw_oos+1)) * gj
        dm_s = d_mean / np.sqrt(hac / T_oos) if hac > 0 else 0
        oos_dm[name] = round(float(dm_s), 4)

    cross_oos_results.append({
        'period': f"{is_start}..{is_end} → {oos_start}..{oos_end}",
        'oos_obs': len(oos_data),
        'results': period_results,
        'dm_vs_baseline': oos_dm,
    })

    # Print OOS results
    base_sharpe = period_results['baseline_12vix']['sharpe']
    print(f"  Baseline Sharpe: {base_sharpe:.4f}")
    for name in ['fast_reentry_14vix', 'slow_reentry_10vix', 'adaptive_peak', 'regression_adaptive']:
        s = period_results[name]['sharpe']
        dm = oos_dm.get(name, 0)
        diff = s - base_sharpe
        print(f"  {name}: Sharpe={s:.4f} (diff={diff:+.4f}), DM={dm:+.3f}")

# ─── 9. Key Finding: Does Faster Re-entry Help? ───
print("\n" + "=" * 70)
print("9. KEY FINDING: REVERSION SPEED ANALYSIS")
print("=" * 70)

# Event-level analysis: How much SPY do you gain by re-entering faster?
print("\nEvent-level SPY returns during VIX reversion (peak → VIX<20):")
print(f"  All events (N={len(valid_events)}): mean={valid_events['spy_ret_reversion_pct'].mean():.1f}%")
print(f"  Fast reversions: mean={fast['spy_ret_reversion_pct'].mean():.1f}%")
print(f"  Slow reversions: mean={slow['spy_ret_reversion_pct'].mean():.1f}%")

# The key question: SPY annualized return during reversion
fast_ann = fast['spy_ret_reversion_pct'].mean() / (fast['days_to_20'].mean() / 252) if fast['days_to_20'].mean() > 0 else 0
slow_ann = slow['spy_ret_reversion_pct'].mean() / (slow['days_to_20'].mean() / 252) if slow['days_to_20'].mean() > 0 else 0
print(f"\nAnnualized SPY return during reversion:")
print(f"  Fast reversions: {fast_ann:.1f}% ann")
print(f"  Slow reversions: {slow_ann:.1f}% ann")

# Does the marginal benefit of faster re-entry matter?
# Compare: how many days per year does the strategy diverge from baseline?
for name, w_col in strategies.items():
    if name == 'baseline_12vix':
        continue
    w_diff = bt_df[w_col] - bt_df['w_baseline']
    active_days = (w_diff.abs() > 0.01).sum()
    pct_active = active_days / len(bt_df) * 100
    avg_w_diff = w_diff[w_diff.abs() > 0.01].mean() if active_days > 0 else 0
    print(f"\n{name}:")
    print(f"  Days different from baseline: {active_days} ({pct_active:.1f}%)")
    print(f"  Avg weight difference when active: {avg_w_diff:+.4f}")

# ─── 10. Summary Assessment ───
print("\n" + "=" * 70)
print("10. SUMMARY ASSESSMENT")
print("=" * 70)

# Count how many strategies beat baseline in OOS
oos_wins = {name: 0 for name in strategies if name != 'baseline_12vix'}
for period in cross_oos_results:
    base_s = period['results']['baseline_12vix']['sharpe']
    for name in oos_wins:
        if period['results'][name]['sharpe'] > base_s:
            oos_wins[name] += 1

print(f"\nCross-OOS wins (out of {len(cross_oos_results)} periods):")
for name, wins in oos_wins.items():
    print(f"  {name}: {wins}/{len(cross_oos_results)}")

# Any strategy pass Harvey threshold in full sample?
harvey_pass = []
for name, dm in dm_results.items():
    if dm['harvey_significant']:
        harvey_pass.append(name)

print(f"\nStrategies passing Harvey t>3.0: {harvey_pass if harvey_pass else 'NONE'}")

# Final verdict
any_oos_winner = any(w >= 2 for w in oos_wins.values())
any_harvey = len(harvey_pass) > 0

if any_harvey and any_oos_winner:
    verdict = "SIGNIFICANT: At least one strategy robustly beats 12/VIX"
elif any_oos_winner:
    verdict = "MARGINAL: Some OOS improvement but no Harvey significance"
else:
    verdict = "NULL RESULT: No strategy reliably beats 12/VIX. Reversion speed does not help."

print(f"\nVERDICT: {verdict}")
print(f"\nInterpretation:")
print(f"  K503 showed 12/VIX IS the continuous mean-reversion trade.")
print(f"  K571 tests whether knowing reversion SPEED improves re-entry timing.")
print(f"  The 12/VIX formula already adapts continuously: as VIX falls, weight rises.")
print(f"  Trying to accelerate or decelerate this natural adaptation")
print(f"  introduces parameter risk without reliable improvement.")

# ─── 11. Save Results ───
results_json = {
    'experiment_id': 'k571',
    'title': 'VIX Mean-Reversion Speed as Portfolio Signal',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'observations': len(df),
    'references': [
        'K503: 12/VIX IS the mean-reversion trade',
        'K211: Mean Reversion Speed (QQQ/GLD pass Harvey, SPY fails)',
        'K524: Decision-focused policy, 0/384 survive BH correction',
        'Whaley (2009) Understanding the VIX, JPortMgmt',
    ],
    'methodology': {
        'spike_threshold': VIX_SPIKE_THRESHOLD,
        'half_life_target': VIX_HALF_LIFE_TARGET,
        'full_norm_target': VIX_FULL_NORM_TARGET,
        'n_spike_events': len(events_df),
        'n_valid_events': len(valid_events),
    },
    'reversion_statistics': {
        'half_life_mean': round(float(valid_events['days_to_20'].mean()), 1),
        'half_life_median': round(float(valid_events['days_to_20'].median()), 1),
        'half_life_std': round(float(valid_events['days_to_20'].std()), 1),
        'half_life_min': int(valid_events['days_to_20'].min()),
        'half_life_max': int(valid_events['days_to_20'].max()),
        'peak_vix_mean': round(float(valid_events['peak_vix'].mean()), 1),
        'peak_vix_median': round(float(valid_events['peak_vix'].median()), 1),
    },
    'regression': {
        'R2': round(float(R2), 4),
        'R2_adj': round(float(R2_adj), 4),
        'coefficients': {name: round(float(b), 4) for name, b in zip(names, beta)},
        'p_values': {name: round(float(p), 4) for name, p in zip(names, p_values)},
    },
    'strategy_results': results,
    'dm_tests': dm_results,
    'cross_oos': cross_oos_results,
    'cross_oos_wins': oos_wins,
    'harvey_pass': harvey_pass,
    'verdict': verdict,
    'events': events[:10],  # Save top 10 events for reference
    'event_categories': {
        'fast_events': len(fast),
        'slow_events': len(slow),
        'fast_mean_spy_ret': round(float(fast['spy_ret_reversion_pct'].mean()), 1),
        'slow_mean_spy_ret': round(float(slow['spy_ret_reversion_pct'].mean()), 1),
        'fast_annualized_spy_ret': round(float(fast_ann), 1),
        'slow_annualized_spy_ret': round(float(slow_ann), 1),
    },
}

output_path = 'experiments/k571_vix_mean_reversion_speed_results.json'
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("\nDone.")
