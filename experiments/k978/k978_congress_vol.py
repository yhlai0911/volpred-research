"""
K978: Congressional Trading vs SPY Volatility
==============================================
Research question: Does aggregate congressional trading activity predict SPY volatility?
Data sources:
  - Congressional trades: data/congressional_trades_house.csv (15,675 records, 2021+)
  - SPY/VIX: yfinance (2020-01-01 to 2026-04-07)
Signal: disclosure_date (publicly available), NOT transaction_date (lookahead)
References:
  - Eggers & Hainmueller (2013) "Capitol Losses"
  - Ziobrowski et al. (2004) JFE "Abnormal Returns from the Common Stock Investments of the US Senate"
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import warnings
import os
from datetime import datetime, timezone

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTDIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 1: Load and process congressional trades
# ============================================================
print("=" * 60)
print("Step 1: Congressional Trades Data Exploration")
print("=" * 60)

df_congress = pd.read_csv('data/congressional_trades_house.csv')
print(f"Total records: {len(df_congress)}")
print(f"Columns: {list(df_congress.columns)}")

# Parse dates - use disclosure_date as signal (publicly available, no lookahead)
df_congress['disclosure_dt'] = pd.to_datetime(df_congress['disclosure_date'], format='mixed', errors='coerce')
df_congress['transaction_dt'] = pd.to_datetime(df_congress['transaction_date'], format='mixed', errors='coerce')

# Drop rows with missing disclosure date
valid_mask = df_congress['disclosure_dt'].notna()
print(f"Records with valid disclosure_date: {valid_mask.sum()} / {len(df_congress)}")
df_congress = df_congress[valid_mask].copy()

# Date range
print(f"Disclosure date range: {df_congress['disclosure_dt'].min().date()} to {df_congress['disclosure_dt'].max().date()}")
print(f"Transaction date range: {df_congress['transaction_dt'].min().date()} to {df_congress['transaction_dt'].max().date()}")

# Disclosure delay
df_congress['delay_days'] = (df_congress['disclosure_dt'] - df_congress['transaction_dt']).dt.days
print(f"\nDisclosure delay (days): mean={df_congress['delay_days'].mean():.1f}, "
      f"median={df_congress['delay_days'].median():.0f}, "
      f"max={df_congress['delay_days'].max():.0f}")

# Transaction types
print(f"\nTransaction types:\n{df_congress['type'].value_counts()}")

# Classify as buy/sell
buy_types = ['purchase']
sell_types = ['sale_partial', 'sale_full', 'sale']
df_congress['is_buy'] = df_congress['type'].str.lower().isin(buy_types)
df_congress['is_sell'] = df_congress['type'].str.lower().isin(sell_types)
print(f"\nBuys: {df_congress['is_buy'].sum()}, Sells: {df_congress['is_sell'].sum()}, "
      f"Other: {(~df_congress['is_buy'] & ~df_congress['is_sell']).sum()}")

# Parse amount ranges to midpoint estimates
def parse_amount(amt_str):
    """Parse amount range string to midpoint estimate."""
    if pd.isna(amt_str):
        return np.nan
    amt_str = str(amt_str).replace('$', '').replace(',', '').strip()
    if ' - ' in amt_str:
        parts = amt_str.split(' - ')
        try:
            lo = float(parts[0].strip())
            hi = float(parts[1].strip())
            return (lo + hi) / 2
        except ValueError:
            return np.nan
    try:
        return float(amt_str)
    except ValueError:
        return np.nan

df_congress['amount_mid'] = df_congress['amount'].apply(parse_amount)
print(f"\nAmount midpoint: mean=${df_congress['amount_mid'].mean():,.0f}, "
      f"median=${df_congress['amount_mid'].median():,.0f}")

# Top tickers
print(f"\nTop 10 tickers traded by Congress:")
print(df_congress['ticker'].value_counts().head(10))

# Top representatives
print(f"\nTop 10 most active representatives:")
print(df_congress['representative'].value_counts().head(10))

# ============================================================
# Aggregate daily trading activity (by DISCLOSURE date)
# ============================================================
daily_trades = df_congress.groupby(df_congress['disclosure_dt'].dt.date).agg(
    daily_buys=('is_buy', 'sum'),
    daily_sells=('is_sell', 'sum'),
    daily_volume=('type', 'count'),
    daily_buy_amount=('amount_mid', lambda x: x[df_congress.loc[x.index, 'is_buy']].sum()),
    daily_sell_amount=('amount_mid', lambda x: x[df_congress.loc[x.index, 'is_sell']].sum()),
).reset_index()
daily_trades.columns = ['date', 'daily_buys', 'daily_sells', 'daily_volume', 'daily_buy_amount', 'daily_sell_amount']
daily_trades['date'] = pd.to_datetime(daily_trades['date'])
daily_trades['daily_net'] = daily_trades['daily_buys'] - daily_trades['daily_sells']
daily_trades['daily_net_amount'] = daily_trades['daily_buy_amount'] - daily_trades['daily_sell_amount']

print(f"\n{'='*60}")
print(f"Daily aggregated activity (by disclosure date):")
print(f"Trading days with disclosures: {len(daily_trades)}")
print(daily_trades[['daily_buys', 'daily_sells', 'daily_volume', 'daily_net']].describe())

# ============================================================
# Step 2: SPY + VIX data
# ============================================================
print(f"\n{'='*60}")
print("Step 2: SPY + VIX Data")
print("=" * 60)

import yfinance as yf

spy = yf.download('SPY', start='2020-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2020-01-01', end='2026-04-07', progress=False)

# Flatten multi-index if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['ret'] = spy['Close'].pct_change()
spy['abs_ret'] = spy['ret'].abs()

# Realized volatility
spy['rv5'] = spy['ret'].rolling(5).std() * np.sqrt(252)
spy['rv22'] = spy['ret'].rolling(22).std() * np.sqrt(252)

# Forward realized volatility (what we want to predict)
spy['fwd_rv5'] = spy['rv5'].shift(-5)
spy['fwd_rv22'] = spy['rv22'].shift(-22)

print(f"SPY data: {len(spy)} rows, {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"VIX data: {len(vix)} rows")

# ============================================================
# Merge datasets
# ============================================================
# Create a complete business day index
market = spy[['ret', 'abs_ret', 'rv5', 'rv22', 'fwd_rv5', 'fwd_rv22', 'Close']].copy()
market['vix'] = vix['Close']
market.index = pd.to_datetime(market.index)

# Merge congressional data - fill non-disclosure days with 0
daily_trades = daily_trades.set_index('date')
merged = market.join(daily_trades, how='left')
merged[['daily_buys', 'daily_sells', 'daily_volume', 'daily_net', 'daily_net_amount']] = \
    merged[['daily_buys', 'daily_sells', 'daily_volume', 'daily_net', 'daily_net_amount']].fillna(0)

# Focus on period where we have congressional data
congress_start = df_congress['disclosure_dt'].min()
merged_valid = merged.loc[congress_start:].dropna(subset=['rv5', 'fwd_rv5', 'vix'])
print(f"\nMerged dataset: {len(merged_valid)} rows from {merged_valid.index[0].date()} to {merged_valid.index[-1].date()}")
print(f"Days with congressional disclosures: {(merged_valid['daily_volume'] > 0).sum()}")
print(f"Days without disclosures: {(merged_valid['daily_volume'] == 0).sum()}")

# ============================================================
# Step 3: Predictive Analysis
# ============================================================
print(f"\n{'='*60}")
print("Step 3: Predictive Analysis")
print("=" * 60)

# --- 3a: Granger Causality ---
print("\n--- 3a: Granger Causality Test ---")
from statsmodels.tsa.stattools import grangercausalitytests

# Prepare series for Granger test
gc_data = merged_valid[['rv5', 'daily_volume']].dropna()
if len(gc_data) > 50:
    print(f"Sample size for Granger test: {len(gc_data)}")
    try:
        gc_results = grangercausalitytests(gc_data[['rv5', 'daily_volume']], maxlag=5, verbose=False)
        for lag in range(1, 6):
            f_stat = gc_results[lag][0]['ssr_ftest'][0]
            p_val = gc_results[lag][0]['ssr_ftest'][1]
            print(f"  Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {'*' if p_val < 0.05 else ''}")
    except Exception as e:
        print(f"  Granger test failed: {e}")

# Also test: daily_net -> rv5
gc_data2 = merged_valid[['rv5', 'daily_net']].dropna()
if len(gc_data2) > 50:
    print(f"\nGranger: daily_net -> rv5")
    try:
        gc_results2 = grangercausalitytests(gc_data2[['rv5', 'daily_net']], maxlag=5, verbose=False)
        for lag in range(1, 6):
            f_stat = gc_results2[lag][0]['ssr_ftest'][0]
            p_val = gc_results2[lag][0]['ssr_ftest'][1]
            print(f"  Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {'*' if p_val < 0.05 else ''}")
    except Exception as e:
        print(f"  Granger test failed: {e}")

# --- 3b: Partial Correlation ---
print("\n--- 3b: Partial Correlation (controlling for VIX) ---")
from scipy import stats

# Simple correlations first
valid_corr = merged_valid.dropna(subset=['fwd_rv5', 'daily_net', 'daily_volume', 'vix'])
print(f"Sample for correlation: {len(valid_corr)}")

corr_vol_fwd, p_vol_fwd = stats.pearsonr(valid_corr['daily_volume'], valid_corr['fwd_rv5'])
corr_net_fwd, p_net_fwd = stats.pearsonr(valid_corr['daily_net'], valid_corr['fwd_rv5'])
corr_vix_fwd, p_vix_fwd = stats.pearsonr(valid_corr['vix'], valid_corr['fwd_rv5'])

print(f"Correlation(daily_volume, fwd_rv5): r={corr_vol_fwd:.4f}, p={p_vol_fwd:.4f}")
print(f"Correlation(daily_net, fwd_rv5): r={corr_net_fwd:.4f}, p={p_net_fwd:.4f}")
print(f"Correlation(VIX, fwd_rv5): r={corr_vix_fwd:.4f}, p={p_vix_fwd:.4f}")

# Partial correlation: congress | VIX -> fwd_rv5
# Using regression-based approach
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation between x and y controlling for z."""
    # Residualize x on z
    z_mat = np.column_stack([z, np.ones(len(z))])
    beta_xz = lstsq(z_mat, x, rcond=None)[0]
    resid_x = x - z_mat @ beta_xz
    # Residualize y on z
    beta_yz = lstsq(z_mat, y, rcond=None)[0]
    resid_y = y - z_mat @ beta_yz
    return stats.pearsonr(resid_x, resid_y)

pcorr_vol, pp_vol = partial_corr(
    valid_corr['daily_volume'].values,
    valid_corr['fwd_rv5'].values,
    valid_corr['vix'].values
)
pcorr_net, pp_net = partial_corr(
    valid_corr['daily_net'].values,
    valid_corr['fwd_rv5'].values,
    valid_corr['vix'].values
)
print(f"\nPartial corr(daily_volume, fwd_rv5 | VIX): r={pcorr_vol:.4f}, p={pp_vol:.4f}")
print(f"Partial corr(daily_net, fwd_rv5 | VIX): r={pcorr_net:.4f}, p={pp_net:.4f}")

# --- 3c: Regression ---
print("\n--- 3c: Regression: fwd_rv5 = a + b1*VIX + b2*Congress ---")
import statsmodels.api as sm

reg_data = merged_valid.dropna(subset=['fwd_rv5', 'vix', 'daily_volume', 'daily_net']).copy()
print(f"Regression sample: {len(reg_data)}")

# Model 1: VIX only
X1 = sm.add_constant(reg_data['vix'])
y = reg_data['fwd_rv5']
m1 = sm.OLS(y, X1).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"\nModel 1 (VIX only): R²={m1.rsquared:.4f}, AIC={m1.aic:.1f}")
print(f"  VIX coef: {m1.params.iloc[1]:.6f}, t={m1.tvalues.iloc[1]:.3f}, p={m1.pvalues.iloc[1]:.4f}")

# Model 2: VIX + daily_volume
X2 = sm.add_constant(reg_data[['vix', 'daily_volume']])
m2 = sm.OLS(y, X2).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"\nModel 2 (VIX + volume): R²={m2.rsquared:.4f}, AIC={m2.aic:.1f}")
print(f"  VIX coef: {m2.params.iloc[1]:.6f}, t={m2.tvalues.iloc[1]:.3f}")
print(f"  Volume coef: {m2.params.iloc[2]:.6f}, t={m2.tvalues.iloc[2]:.3f}, p={m2.pvalues.iloc[2]:.4f}")

# Model 3: VIX + daily_net
X3 = sm.add_constant(reg_data[['vix', 'daily_net']])
m3 = sm.OLS(y, X3).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"\nModel 3 (VIX + net): R²={m3.rsquared:.4f}, AIC={m3.aic:.1f}")
print(f"  VIX coef: {m3.params.iloc[1]:.6f}, t={m3.tvalues.iloc[1]:.3f}")
print(f"  Net coef: {m3.params.iloc[2]:.6f}, t={m3.tvalues.iloc[2]:.3f}, p={m3.pvalues.iloc[2]:.4f}")

# Model 4: VIX + daily_volume + daily_net
X4 = sm.add_constant(reg_data[['vix', 'daily_volume', 'daily_net']])
m4 = sm.OLS(y, X4).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"\nModel 4 (VIX + volume + net): R²={m4.rsquared:.4f}, AIC={m4.aic:.1f}")
for i, name in enumerate(m4.params.index):
    print(f"  {name}: coef={m4.params.iloc[i]:.6f}, t={m4.tvalues.iloc[i]:.3f}, p={m4.pvalues.iloc[i]:.4f}")

# --- 3d: Rolling window analysis ---
print("\n--- 3d: Rolling Window Correlation ---")
# 60-day rolling correlation between congress activity and forward vol
rolling_corr_vol = merged_valid['daily_volume'].rolling(60).corr(merged_valid['fwd_rv5'])
rolling_corr_net = merged_valid['daily_net'].rolling(60).corr(merged_valid['fwd_rv5'])
print(f"60d rolling corr(volume, fwd_rv5): mean={rolling_corr_vol.mean():.4f}, std={rolling_corr_vol.std():.4f}")
print(f"60d rolling corr(net, fwd_rv5): mean={rolling_corr_net.mean():.4f}, std={rolling_corr_net.std():.4f}")

# --- 3e: Event Analysis ---
print("\n--- 3e: Event Analysis (High Activity Days) ---")

# Define high activity as > mean + 2*std
vol_mean = merged_valid['daily_volume'].mean()
vol_std = merged_valid['daily_volume'].std()
threshold = vol_mean + 2 * vol_std
high_activity = merged_valid[merged_valid['daily_volume'] > threshold]
normal_activity = merged_valid[(merged_valid['daily_volume'] > 0) & (merged_valid['daily_volume'] <= threshold)]
no_activity = merged_valid[merged_valid['daily_volume'] == 0]

print(f"Threshold (mean+2sd): {threshold:.1f}")
print(f"High activity days: {len(high_activity)}")
print(f"Normal activity days: {len(normal_activity)}")
print(f"No disclosure days: {len(no_activity)}")

if len(high_activity) > 0:
    # Compare forward vol after high vs normal vs no activity
    fwd_rv5_high = high_activity['fwd_rv5'].dropna()
    fwd_rv5_normal = normal_activity['fwd_rv5'].dropna()
    fwd_rv5_no = no_activity['fwd_rv5'].dropna()

    print(f"\nForward 5d RV after:")
    print(f"  High activity:   mean={fwd_rv5_high.mean():.4f}, median={fwd_rv5_high.median():.4f}, n={len(fwd_rv5_high)}")
    print(f"  Normal activity: mean={fwd_rv5_normal.mean():.4f}, median={fwd_rv5_normal.median():.4f}, n={len(fwd_rv5_normal)}")
    print(f"  No disclosure:   mean={fwd_rv5_no.mean():.4f}, median={fwd_rv5_no.median():.4f}, n={len(fwd_rv5_no)}")

    # T-test: high vs normal
    if len(fwd_rv5_high) >= 5 and len(fwd_rv5_normal) >= 5:
        t_stat, p_val = stats.ttest_ind(fwd_rv5_high, fwd_rv5_normal, equal_var=False)
        print(f"\n  T-test (high vs normal): t={t_stat:.3f}, p={p_val:.4f}")

    # Mann-Whitney U (non-parametric)
    if len(fwd_rv5_high) >= 5 and len(fwd_rv5_normal) >= 5:
        u_stat, p_val_mw = stats.mannwhitneyu(fwd_rv5_high, fwd_rv5_normal, alternative='two-sided')
        print(f"  Mann-Whitney U (high vs normal): U={u_stat:.0f}, p={p_val_mw:.4f}")

# --- 3f: Net selling as vol predictor ---
print("\n--- 3f: Net Selling as Vol Signal ---")
# Hypothesis: net selling predicts higher vol (congressmen sell before bad news)
# Use lagged signal: signal.shift(1) - signal from yesterday predicts today's vol
merged_valid = merged_valid.copy()
merged_valid['net_sell_signal'] = (-merged_valid['daily_net']).shift(1)  # positive = more selling

# Quintile analysis
valid_signal = merged_valid.dropna(subset=['net_sell_signal', 'fwd_rv5'])
valid_signal = valid_signal[valid_signal['net_sell_signal'] != 0]  # exclude no-activity days

if len(valid_signal) > 100:
    valid_signal['quintile'] = pd.qcut(valid_signal['net_sell_signal'], 5, labels=False, duplicates='drop')
    quintile_stats = valid_signal.groupby('quintile')['fwd_rv5'].agg(['mean', 'median', 'std', 'count'])
    print(f"Quintile analysis (net selling signal -> fwd_rv5):")
    print(quintile_stats.round(4))

    # Monotonicity test
    q_means = quintile_stats['mean'].values
    is_monotonic = all(q_means[i] <= q_means[i+1] for i in range(len(q_means)-1)) or \
                   all(q_means[i] >= q_means[i+1] for i in range(len(q_means)-1))
    print(f"Monotonic relationship: {is_monotonic}")
else:
    print(f"Insufficient non-zero signal observations: {len(valid_signal)}")
    quintile_stats = None

# ============================================================
# Step 4: Visualization
# ============================================================
print(f"\n{'='*60}")
print("Step 4: Generating Charts")
print("=" * 60)

# --- Chart 1: Congressional Trading Activity Time Series ---
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
fig.suptitle('K978: Congressional Trading Activity vs SPY Volatility', fontsize=14, fontweight='bold')

# Panel A: Daily trading volume
idx = merged_valid.index.to_numpy()
axes[0].bar(idx, merged_valid['daily_buys'].values, color='green', alpha=0.6, label='Buys')
axes[0].bar(idx, -merged_valid['daily_sells'].values, color='red', alpha=0.6, label='Sells')
axes[0].set_ylabel('Trade Count')
axes[0].set_title('(A) Congressional Trading Activity (by disclosure date)')
axes[0].legend(loc='upper right')
axes[0].axhline(0, color='gray', linewidth=0.5)
if threshold > 0:
    axes[0].axhline(threshold, color='orange', linestyle='--', alpha=0.5, label=f'High activity threshold ({threshold:.0f})')

# Panel B: SPY 5d Realized Volatility
axes[1].plot(idx, merged_valid['rv5'].values, color='blue', alpha=0.7, linewidth=0.8)
axes[1].set_ylabel('5d RV (annualized)')
axes[1].set_title('(B) SPY 5-day Realized Volatility')

# Panel C: VIX
axes[2].plot(idx, merged_valid['vix'].values, color='purple', alpha=0.7, linewidth=0.8)
axes[2].set_ylabel('VIX')
axes[2].set_title('(C) VIX Index')
axes[2].set_xlabel('Date')

plt.tight_layout()
chart1_path = os.path.join(OUTDIR, 'k978_trading_activity.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {chart1_path}")

# --- Chart 2: Conditional Volatility Analysis ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K978: Conditional Volatility Analysis', fontsize=14, fontweight='bold')

# Panel A: Scatter - volume vs fwd_rv5
ax = axes[0, 0]
sc = ax.scatter(merged_valid['daily_volume'], merged_valid['fwd_rv5'],
                alpha=0.3, s=10, c=merged_valid['vix'], cmap='RdYlGn_r')
ax.set_xlabel('Daily Disclosure Volume')
ax.set_ylabel('Forward 5d RV')
ax.set_title(f'(A) Volume vs Fwd RV5\nr={corr_vol_fwd:.3f} (p={p_vol_fwd:.3f})')
plt.colorbar(sc, ax=ax, label='VIX')

# Panel B: Event analysis boxplot
ax = axes[0, 1]
groups_data = []
group_labels = []
if len(fwd_rv5_high) > 0:
    groups_data.append(fwd_rv5_high.values)
    group_labels.append(f'High\n(n={len(fwd_rv5_high)})')
if len(fwd_rv5_normal) > 0:
    groups_data.append(fwd_rv5_normal.values)
    group_labels.append(f'Normal\n(n={len(fwd_rv5_normal)})')
if len(fwd_rv5_no) > 0:
    groups_data.append(fwd_rv5_no.values)
    group_labels.append(f'None\n(n={len(fwd_rv5_no)})')

bp = ax.boxplot(groups_data, labels=group_labels, showfliers=False, patch_artist=True)
colors = ['#ff6b6b', '#ffd93d', '#6bcf7f']
for patch, color in zip(bp['boxes'], colors[:len(groups_data)]):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)
ax.set_ylabel('Forward 5d RV')
ax.set_title('(B) Fwd RV5 by Congressional Activity Level')

# Panel C: Rolling correlation
ax = axes[1, 0]
ax.plot(rolling_corr_vol.index.to_numpy(), rolling_corr_vol.values, color='blue', alpha=0.7, linewidth=0.8, label='Volume')
ax.plot(rolling_corr_net.index.to_numpy(), rolling_corr_net.values, color='red', alpha=0.7, linewidth=0.8, label='Net')
ax.axhline(0, color='gray', linewidth=0.5)
ax.set_ylabel('60d Rolling Correlation')
ax.set_xlabel('Date')
ax.set_title('(C) Rolling Correlation with Fwd RV5')
ax.legend()

# Panel D: Quintile analysis (if available)
ax = axes[1, 1]
if quintile_stats is not None and len(quintile_stats) > 0:
    q_labels = [f'Q{i+1}\n(low sell)' if i == 0 else (f'Q{i+1}\n(high sell)' if i == len(quintile_stats)-1 else f'Q{i+1}')
                for i in range(len(quintile_stats))]
    bars = ax.bar(range(len(quintile_stats)), quintile_stats['mean'],
                  yerr=quintile_stats['std']/np.sqrt(quintile_stats['count']),
                  color=['#6bcf7f', '#a8d4a8', '#ffd93d', '#ffb366', '#ff6b6b'],
                  alpha=0.7, capsize=5)
    ax.set_xticks(range(len(quintile_stats)))
    ax.set_xticklabels(q_labels)
    ax.set_ylabel('Mean Forward 5d RV')
    ax.set_title('(D) Fwd RV5 by Net Selling Quintile')
else:
    ax.text(0.5, 0.5, 'Insufficient data\nfor quintile analysis',
            ha='center', va='center', transform=ax.transAxes)
    ax.set_title('(D) Fwd RV5 by Net Selling Quintile')

plt.tight_layout()
chart2_path = os.path.join(OUTDIR, 'k978_conditional_vol.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {chart2_path}")

# ============================================================
# Step 5: Compile Results
# ============================================================
print(f"\n{'='*60}")
print("Step 5: Compile Results")
print("=" * 60)

results = {
    "experiment_id": "K978",
    "title": "Congressional Trading vs SPY Volatility",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_sources": {
        "congressional_trades": "data/congressional_trades_house.csv",
        "spy_vix": "yfinance"
    },
    "sample": {
        "congress_records": len(df_congress),
        "congress_date_range": f"{df_congress['disclosure_dt'].min().date()} to {df_congress['disclosure_dt'].max().date()}",
        "merged_observations": len(merged_valid),
        "merged_date_range": f"{merged_valid.index[0].date()} to {merged_valid.index[-1].date()}",
        "disclosure_delay_mean_days": round(df_congress['delay_days'].mean(), 1),
        "disclosure_delay_median_days": int(df_congress['delay_days'].median()),
        "days_with_disclosures": int((merged_valid['daily_volume'] > 0).sum()),
        "days_without_disclosures": int((merged_valid['daily_volume'] == 0).sum()),
        "high_activity_days": len(high_activity),
        "high_activity_threshold": round(threshold, 1)
    },
    "correlations": {
        "volume_fwd_rv5": {"r": round(corr_vol_fwd, 4), "p": round(p_vol_fwd, 4)},
        "net_fwd_rv5": {"r": round(corr_net_fwd, 4), "p": round(p_net_fwd, 4)},
        "vix_fwd_rv5": {"r": round(corr_vix_fwd, 4), "p": round(p_vix_fwd, 4)},
        "partial_volume_fwd_rv5_given_vix": {"r": round(pcorr_vol, 4), "p": round(pp_vol, 4)},
        "partial_net_fwd_rv5_given_vix": {"r": round(pcorr_net, 4), "p": round(pp_net, 4)}
    },
    "granger_causality": {},
    "regressions": {
        "model1_vix_only": {
            "R2": round(m1.rsquared, 4),
            "AIC": round(m1.aic, 1),
            "vix_t": round(float(m1.tvalues.iloc[1]), 3),
            "vix_p": round(float(m1.pvalues.iloc[1]), 4)
        },
        "model2_vix_volume": {
            "R2": round(m2.rsquared, 4),
            "AIC": round(m2.aic, 1),
            "volume_t": round(float(m2.tvalues.iloc[2]), 3),
            "volume_p": round(float(m2.pvalues.iloc[2]), 4)
        },
        "model3_vix_net": {
            "R2": round(m3.rsquared, 4),
            "AIC": round(m3.aic, 1),
            "net_t": round(float(m3.tvalues.iloc[2]), 3),
            "net_p": round(float(m3.pvalues.iloc[2]), 4)
        },
        "model4_full": {
            "R2": round(m4.rsquared, 4),
            "AIC": round(m4.aic, 1),
            "coefficients": {name: {"coef": round(float(m4.params.iloc[i]), 6),
                                     "t": round(float(m4.tvalues.iloc[i]), 3),
                                     "p": round(float(m4.pvalues.iloc[i]), 4)}
                             for i, name in enumerate(m4.params.index)}
        }
    },
    "event_analysis": {
        "high_activity_fwd_rv5_mean": round(float(fwd_rv5_high.mean()), 4) if len(fwd_rv5_high) > 0 else None,
        "normal_activity_fwd_rv5_mean": round(float(fwd_rv5_normal.mean()), 4) if len(fwd_rv5_normal) > 0 else None,
        "no_activity_fwd_rv5_mean": round(float(fwd_rv5_no.mean()), 4) if len(fwd_rv5_no) > 0 else None,
    },
    "rolling_correlation": {
        "volume_fwd_rv5_60d_mean": round(float(rolling_corr_vol.mean()), 4),
        "volume_fwd_rv5_60d_std": round(float(rolling_corr_vol.std()), 4),
        "net_fwd_rv5_60d_mean": round(float(rolling_corr_net.mean()), 4),
        "net_fwd_rv5_60d_std": round(float(rolling_corr_net.std()), 4)
    },
    "conclusion": "",
    "limitations": [
        "Short sample period (~4 years of congressional data)",
        "Disclosure delay (median ~30 days) reduces signal timeliness",
        "Cannot distinguish informed trading from routine portfolio management",
        "Many zero-activity days dilute signal",
        "Amount data is range-based, using midpoint is an approximation",
        "No control for market-wide factors beyond VIX"
    ]
}

# Fill Granger results
try:
    for lag in range(1, 6):
        results["granger_causality"][f"volume_rv5_lag{lag}"] = {
            "F": round(gc_results[lag][0]['ssr_ftest'][0], 3),
            "p": round(gc_results[lag][0]['ssr_ftest'][1], 4)
        }
except:
    pass

# Determine conclusion
sig_level = 0.05
harvey_threshold = 3.0

vol_predictive = abs(m2.tvalues.iloc[2]) > harvey_threshold
net_predictive = abs(m3.tvalues.iloc[2]) > harvey_threshold
partial_vol_sig = pp_vol < sig_level
partial_net_sig = pp_net < sig_level

if vol_predictive or net_predictive:
    conclusion = (f"Congressional trading activity shows statistically significant predictive power "
                  f"for SPY volatility beyond VIX (|t| > {harvey_threshold}). "
                  f"Volume t={m2.tvalues.iloc[2]:.3f}, Net t={m3.tvalues.iloc[2]:.3f}. "
                  f"However, the incremental R-squared is small "
                  f"(delta R2 = {m2.rsquared - m1.rsquared:.4f} for volume). "
                  f"Practical significance is limited given disclosure delays.")
elif partial_vol_sig or partial_net_sig:
    conclusion = (f"Congressional trading shows weak partial correlation with future SPY volatility "
                  f"after controlling for VIX (partial r={pcorr_vol:.4f} for volume, "
                  f"partial r={pcorr_net:.4f} for net). However, regression coefficients fail the "
                  f"Harvey (2016) threshold (|t| > 3.0): volume t={m2.tvalues.iloc[2]:.3f}, "
                  f"net t={m3.tvalues.iloc[2]:.3f}. No reliable predictive signal detected.")
else:
    conclusion = (f"Congressional trading activity does NOT provide significant incremental "
                  f"predictive power for SPY volatility beyond VIX. "
                  f"Partial correlations are weak (volume: r={pcorr_vol:.4f}, net: r={pcorr_net:.4f}). "
                  f"Regression coefficients fail Harvey (2016) threshold: "
                  f"volume |t|={abs(m2.tvalues.iloc[2]):.3f}, net |t|={abs(m3.tvalues.iloc[2]):.3f} < 3.0. "
                  f"Likely causes: disclosure delays (~{int(df_congress['delay_days'].median())} day median), "
                  f"sparse signal, VIX already captures most vol information.")

results["conclusion"] = conclusion
results["passes_harvey_threshold"] = bool(vol_predictive or net_predictive)

# Save results
results_path = os.path.join(OUTDIR, 'k978_congress_vol_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"Saved: {results_path}")

print(f"\n{'='*60}")
print("CONCLUSION:")
print(conclusion)
print(f"{'='*60}")
