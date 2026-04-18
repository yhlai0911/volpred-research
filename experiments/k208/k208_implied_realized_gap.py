"""
K208: Implied-Realized Volatility Gap as Dynamic Risk Indicator

Background:
- VIX represents implied vol, GARCH represents realized vol forecast
- The GAP = VIX_daily - GARCH_sigma captures market fear beyond what realized dynamics predict
- When the gap is large, the market is pricing in a risk premium
- GAP_ratio = VIX_daily / GARCH_sigma is a normalized measure

Methodology:
1. Compute daily implied-realized gap (VIX_daily vs GJR-GARCH sigma)
2. GAP characteristics: mean, std, distribution, ACF, correlation with future vol
3. GAP as regime indicator (percentile-based)
4. GAP-adjusted VT strategy
5. Historical extreme GAP events analysis

Data: SPY + VIX daily from yfinance. OOS: 2023-2024.
Statistical requirements: DM test, partial r|VIX, Harvey threshold.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K208: Implied-Realized Volatility Gap as Dynamic Risk Indicator")
print("=" * 70)

print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2006-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2006-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Build aligned dataframe
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
df = df.dropna()

print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# ============================================================
# 2. Rolling GJR-GARCH(1,1,1) Forecast
# ============================================================
print("\n[2] Computing rolling GJR-GARCH(1,1,1) forecasts (w=2000)...")

WINDOW = 2000
returns_pct = df['spy_return'] * 100  # arch uses percentage returns

garch_sigma = pd.Series(index=df.index, dtype=float)
n_fitted = 0
n_failed = 0

for i in range(WINDOW, len(df)):
    train = returns_pct.iloc[i - WINDOW:i]
    try:
        model = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = model.fit(disp='off', show_warning=False)
        fcast = res.forecast(horizon=1)
        # sigma in decimal (daily)
        garch_sigma.iloc[i] = np.sqrt(fcast.variance.values[-1, 0]) / 100.0
        n_fitted += 1
    except Exception:
        n_failed += 1
        # fallback: use EWMA
        garch_sigma.iloc[i] = train.ewm(span=50).std().iloc[-1] / 100.0

    if (i - WINDOW) % 500 == 0:
        print(f"    Processed {i - WINDOW}/{len(df) - WINDOW} ({n_fitted} fitted, {n_failed} failed)")

print(f"  Total: {n_fitted} fitted, {n_failed} failed")

# ============================================================
# 3. Compute Implied-Realized GAP
# ============================================================
print("\n[3] Computing implied-realized gap...")

# VIX to daily decimal
df['vix_daily'] = df['vix'] / np.sqrt(252) / 100  # annualized % -> daily decimal

df['garch_sigma'] = garch_sigma

# Drop rows without GARCH estimates
df_gap = df.dropna(subset=['garch_sigma']).copy()

# GAP = VIX_daily - GARCH_sigma (both in daily decimal)
df_gap['gap'] = df_gap['vix_daily'] - df_gap['garch_sigma']
# GAP_ratio = VIX_daily / GARCH_sigma
df_gap['gap_ratio'] = df_gap['vix_daily'] / df_gap['garch_sigma']

print(f"  GAP series: {len(df_gap)} observations")
print(f"  Date range: {df_gap.index[0].strftime('%Y-%m-%d')} to {df_gap.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 4. GAP Characteristics (Full Sample)
# ============================================================
print("\n[4] GAP Characteristics (Full Sample)")
print("-" * 50)

gap = df_gap['gap']
gap_ratio = df_gap['gap_ratio']

print(f"  GAP (VIX_daily - GARCH_sigma):")
print(f"    Mean:     {gap.mean():.6f} ({gap.mean()*np.sqrt(252)*100:.2f}% annualized)")
print(f"    Std:      {gap.std():.6f} ({gap.std()*np.sqrt(252)*100:.2f}% annualized)")
print(f"    Median:   {gap.median():.6f}")
print(f"    Skewness: {gap.skew():.3f}")
print(f"    Kurtosis: {gap.kurtosis():.3f}")
print(f"    Min:      {gap.min():.6f} (date: {gap.idxmin().strftime('%Y-%m-%d')})")
print(f"    Max:      {gap.max():.6f} (date: {gap.idxmax().strftime('%Y-%m-%d')})")
print(f"    % Positive (VIX > GARCH): {(gap > 0).mean()*100:.1f}%")

print(f"\n  GAP Ratio (VIX_daily / GARCH_sigma):")
print(f"    Mean:     {gap_ratio.mean():.3f}")
print(f"    Std:      {gap_ratio.std():.3f}")
print(f"    Median:   {gap_ratio.median():.3f}")
print(f"    25th pctl: {gap_ratio.quantile(0.25):.3f}")
print(f"    75th pctl: {gap_ratio.quantile(0.75):.3f}")

# ============================================================
# 5. ACF Structure of GAP
# ============================================================
print("\n[5] ACF Structure of GAP")
print("-" * 50)

lags_to_check = [1, 5, 10, 22, 44, 66]
n_obs = len(gap)
gap_centered = gap - gap.mean()

print(f"  {'Lag':>4s}  {'ACF':>8s}  {'t-stat':>8s}  {'Significant':>12s}")
for lag in lags_to_check:
    acf_val = gap_centered.autocorr(lag=lag)
    se = 1 / np.sqrt(n_obs)
    t_stat = acf_val / se
    sig = "***" if abs(t_stat) > 2.576 else ("**" if abs(t_stat) > 1.96 else "")
    print(f"  {lag:4d}  {acf_val:8.4f}  {t_stat:8.2f}  {sig:>12s}")

# Half-life estimation
acf1 = gap_centered.autocorr(lag=1)
if 0 < acf1 < 1:
    half_life = -np.log(2) / np.log(acf1)
    print(f"\n  Estimated half-life: {half_life:.1f} days")
else:
    half_life = np.nan
    print(f"\n  ACF(1) = {acf1:.4f}, half-life not computable")

# ============================================================
# 6. Correlation with Future Realized Vol (5d, 22d)
# ============================================================
print("\n[6] Correlation with Future Realized Vol")
print("-" * 50)

# Future realized vol
df_gap['rv_5d_fwd'] = df_gap['spy_return'].rolling(5).std().shift(-5) * np.sqrt(252)
df_gap['rv_22d_fwd'] = df_gap['spy_return'].rolling(22).std().shift(-22) * np.sqrt(252)

# Current realized vol (for partial correlation)
df_gap['rv_22d_current'] = df_gap['spy_return'].rolling(22).std() * np.sqrt(252)

valid_5d = df_gap.dropna(subset=['gap', 'rv_5d_fwd'])
valid_22d = df_gap.dropna(subset=['gap', 'rv_22d_fwd'])

# Raw correlations
r_5d, p_5d = stats.pearsonr(valid_5d['gap'], valid_5d['rv_5d_fwd'])
r_22d, p_22d = stats.pearsonr(valid_22d['gap'], valid_22d['rv_22d_fwd'])

print(f"  GAP vs Future 5d RV:  r = {r_5d:.4f}, p = {p_5d:.2e}")
print(f"  GAP vs Future 22d RV: r = {r_22d:.4f}, p = {p_22d:.2e}")

# GAP_ratio correlations
r_ratio_5d, p_ratio_5d = stats.pearsonr(valid_5d['gap_ratio'], valid_5d['rv_5d_fwd'])
r_ratio_22d, p_ratio_22d = stats.pearsonr(valid_22d['gap_ratio'], valid_22d['rv_22d_fwd'])

print(f"\n  GAP_ratio vs Future 5d RV:  r = {r_ratio_5d:.4f}, p = {p_ratio_5d:.2e}")
print(f"  GAP_ratio vs Future 22d RV: r = {r_ratio_22d:.4f}, p = {p_ratio_22d:.2e}")

# Partial correlation: GAP → Future RV, controlling for VIX
print("\n  Partial correlations (controlling for VIX):")
valid_partial_5d = df_gap.dropna(subset=['gap', 'rv_5d_fwd', 'vix']).copy()
valid_partial_22d = df_gap.dropna(subset=['gap', 'rv_22d_fwd', 'vix']).copy()

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    from numpy.linalg import lstsq
    # Regress x on z
    z_arr = np.column_stack([z, np.ones(len(z))])
    beta_x, _, _, _ = lstsq(z_arr, x, rcond=None)
    resid_x = x - z_arr @ beta_x
    # Regress y on z
    beta_y, _, _, _ = lstsq(z_arr, y, rcond=None)
    resid_y = y - z_arr @ beta_y
    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p

pr_5d, pp_5d = partial_corr(
    valid_partial_5d['gap'].values,
    valid_partial_5d['rv_5d_fwd'].values,
    valid_partial_5d['vix'].values
)
pr_22d, pp_22d = partial_corr(
    valid_partial_22d['gap'].values,
    valid_partial_22d['rv_22d_fwd'].values,
    valid_partial_22d['vix'].values
)

print(f"  GAP → Future 5d RV | VIX:  partial r = {pr_5d:.4f}, p = {pp_5d:.2e}")
print(f"  GAP → Future 22d RV | VIX: partial r = {pr_22d:.4f}, p = {pp_22d:.2e}")

# Also partial correlation controlling for GARCH_sigma
print("\n  Partial correlations (controlling for GARCH_sigma):")
valid_partial_g5 = df_gap.dropna(subset=['gap', 'rv_5d_fwd', 'garch_sigma']).copy()
valid_partial_g22 = df_gap.dropna(subset=['gap', 'rv_22d_fwd', 'garch_sigma']).copy()

prg_5d, ppg_5d = partial_corr(
    valid_partial_g5['gap'].values,
    valid_partial_g5['rv_5d_fwd'].values,
    valid_partial_g5['garch_sigma'].values
)
prg_22d, ppg_22d = partial_corr(
    valid_partial_g22['gap'].values,
    valid_partial_g22['rv_22d_fwd'].values,
    valid_partial_g22['garch_sigma'].values
)

print(f"  GAP → Future 5d RV | GARCH:  partial r = {prg_5d:.4f}, p = {ppg_5d:.2e}")
print(f"  GAP → Future 22d RV | GARCH: partial r = {prg_22d:.4f}, p = {ppg_22d:.2e}")

# ============================================================
# 7. GAP as Regime Indicator
# ============================================================
print("\n[7] GAP as Regime Indicator")
print("-" * 50)

# Define regimes by GAP_ratio percentiles (full sample to establish thresholds)
# Then test OOS
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

# Use expanding window percentiles to avoid lookahead
df_gap['gap_ratio_p25'] = df_gap['gap_ratio'].expanding(min_periods=252).quantile(0.25)
df_gap['gap_ratio_p50'] = df_gap['gap_ratio'].expanding(min_periods=252).quantile(0.50)
df_gap['gap_ratio_p75'] = df_gap['gap_ratio'].expanding(min_periods=252).quantile(0.75)

def classify_gap_regime(row):
    if pd.isna(row['gap_ratio_p25']):
        return np.nan
    if row['gap_ratio'] > row['gap_ratio_p75']:
        return 'High Fear'
    elif row['gap_ratio'] < row['gap_ratio_p25']:
        return 'Complacent'
    elif row['gap_ratio'] >= row['gap_ratio_p50']:
        return 'Moderate High'
    else:
        return 'Moderate Low'

df_gap['gap_regime'] = df_gap.apply(classify_gap_regime, axis=1)

# Future returns by regime
df_gap['fwd_ret_5d'] = df_gap['spy_close'].shift(-5) / df_gap['spy_close'] - 1
df_gap['fwd_ret_22d'] = df_gap['spy_close'].shift(-22) / df_gap['spy_close'] - 1

# OOS analysis
oos = df_gap.loc[OOS_START:OOS_END].dropna(subset=['gap_regime', 'fwd_ret_22d'])

print(f"  OOS period: {OOS_START} to {OOS_END}")
print(f"  OOS observations with regime + 22d fwd return: {len(oos)}")

print(f"\n  {'Regime':<15s} {'Count':>6s} {'Avg 5d Ret':>12s} {'Avg 22d Ret':>13s} {'22d Vol':>10s}")
print(f"  {'-'*60}")

regime_stats = {}
for regime in ['High Fear', 'Moderate High', 'Moderate Low', 'Complacent']:
    subset = oos[oos['gap_regime'] == regime]
    if len(subset) > 0:
        avg_5d = subset['fwd_ret_5d'].mean() if 'fwd_ret_5d' in subset.columns else np.nan
        avg_22d = subset['fwd_ret_22d'].mean()
        vol_22d = subset['fwd_ret_22d'].std()
        print(f"  {regime:<15s} {len(subset):6d} {avg_5d*100:11.3f}% {avg_22d*100:12.3f}% {vol_22d*100:9.3f}%")
        regime_stats[regime] = {
            'count': len(subset),
            'avg_5d_ret': float(avg_5d) if not np.isnan(avg_5d) else None,
            'avg_22d_ret': float(avg_22d),
            'vol_22d_ret': float(vol_22d)
        }

# Full sample regime analysis
full_valid = df_gap.dropna(subset=['gap_regime', 'fwd_ret_22d'])
print(f"\n  Full sample regime analysis ({len(full_valid)} obs):")
print(f"  {'Regime':<15s} {'Count':>6s} {'Avg 22d Ret':>13s} {'22d Vol':>10s} {'Sharpe(22d)':>12s}")
print(f"  {'-'*60}")

for regime in ['High Fear', 'Moderate High', 'Moderate Low', 'Complacent']:
    subset = full_valid[full_valid['gap_regime'] == regime]
    if len(subset) > 0:
        avg_22d = subset['fwd_ret_22d'].mean()
        vol_22d = subset['fwd_ret_22d'].std()
        sharpe_22d = avg_22d / vol_22d if vol_22d > 0 else 0
        print(f"  {regime:<15s} {len(subset):6d} {avg_22d*100:12.3f}% {vol_22d*100:9.3f}% {sharpe_22d:11.3f}")

# t-test: High Fear vs Complacent
hf = full_valid[full_valid['gap_regime'] == 'High Fear']['fwd_ret_22d']
comp = full_valid[full_valid['gap_regime'] == 'Complacent']['fwd_ret_22d']
t_regime, p_regime = stats.ttest_ind(hf, comp, equal_var=False)
print(f"\n  t-test High Fear vs Complacent (22d fwd ret): t={t_regime:.3f}, p={p_regime:.4f}")

# ============================================================
# 8. GAP-Adjusted VT Strategy
# ============================================================
print("\n[8] GAP-Adjusted VT Strategy (OOS: 2023-2024)")
print("-" * 50)

# Strategy: Use GAP to adjust equity weight
# Base: 12/VIX weight
# Adjustment: when GAP_ratio is high (fear premium large), increase equity
#             when GAP_ratio is low (complacency), reduce equity

df_gap['vt_base_weight'] = np.clip(12.0 / df_gap['vix'], 0, 1.0)

# GAP-adjusted weights using expanding z-score of gap_ratio
df_gap['gap_ratio_mean'] = df_gap['gap_ratio'].expanding(min_periods=252).mean()
df_gap['gap_ratio_std'] = df_gap['gap_ratio'].expanding(min_periods=252).std()
df_gap['gap_z'] = (df_gap['gap_ratio'] - df_gap['gap_ratio_mean']) / df_gap['gap_ratio_std']

# Adjustment factor: gap_z > 0 means more fear than usual → increase equity (mean revert)
# gap_z < 0 means less fear → reduce equity
ADJUSTMENT_SCALE = 0.15  # max +/- 15% weight adjustment
df_gap['gap_adjustment'] = np.clip(df_gap['gap_z'] * ADJUSTMENT_SCALE / 2, -ADJUSTMENT_SCALE, ADJUSTMENT_SCALE)

df_gap['vt_gap_weight'] = np.clip(df_gap['vt_base_weight'] + df_gap['gap_adjustment'], 0, 1.0)

# Next-day returns (lagged weights to avoid lookahead)
df_gap['next_ret'] = df_gap['spy_return'].shift(-1)

# Strategy returns (lagged by 1 day)
df_gap['ret_base_vt'] = df_gap['vt_base_weight'].shift(1) * df_gap['next_ret'].shift(1)
df_gap['ret_gap_vt'] = df_gap['vt_gap_weight'].shift(1) * df_gap['next_ret'].shift(1)
df_gap['ret_buyhold'] = df_gap['spy_return']

# Wait — correct the lagging. We want:
# weight_t determined at close of day t, applied to return on day t+1
# So: ret_strategy_{t+1} = weight_t * r_{t+1}
# For proper alignment:
df_gap['ret_base_vt'] = df_gap['vt_base_weight'] * df_gap['spy_return'].shift(-1)
df_gap['ret_gap_vt'] = df_gap['vt_gap_weight'] * df_gap['spy_return'].shift(-1)

# OOS only
oos_strat = df_gap.loc[OOS_START:OOS_END].dropna(subset=['ret_base_vt', 'ret_gap_vt']).copy()

def compute_strategy_metrics(returns, name, rf_annual=0.05):
    """Compute standard strategy metrics."""
    n = len(returns)
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    rf_daily = rf_annual / 252
    excess = returns - rf_daily
    sharpe = excess.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = (ann_ret - rf_annual) / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Harvey t-stat
    n_years = n / 252
    se_sharpe = 1 / np.sqrt(n_years)
    t_harvey = sharpe / se_sharpe

    return {
        'name': name,
        'n_days': n,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'sortino': float(sortino),
        'calmar': float(calmar),
        't_harvey': float(t_harvey),
        'se_sharpe': float(se_sharpe)
    }

# Compute metrics
bh_metrics = compute_strategy_metrics(oos_strat['ret_buyhold'], 'Buy & Hold SPY')
base_vt_metrics = compute_strategy_metrics(oos_strat['ret_base_vt'], '12/VIX VT')
gap_vt_metrics = compute_strategy_metrics(oos_strat['ret_gap_vt'], 'GAP-Adjusted VT')

print(f"  {'Metric':<20s} {'Buy&Hold':>12s} {'12/VIX VT':>12s} {'GAP-Adj VT':>12s}")
print(f"  {'-'*60}")
for key in ['ann_return', 'ann_vol', 'sharpe', 'mdd', 'sortino', 'calmar', 't_harvey']:
    fmt = '.4f' if key == 'mdd' else '.3f'
    bh_val = bh_metrics[key]
    base_val = base_vt_metrics[key]
    gap_val = gap_vt_metrics[key]
    label = key.replace('_', ' ').title()
    if key == 'ann_return':
        print(f"  {label:<20s} {bh_val*100:11.2f}% {base_val*100:11.2f}% {gap_val*100:11.2f}%")
    elif key == 'mdd':
        print(f"  {label:<20s} {bh_val*100:11.2f}% {base_val*100:11.2f}% {gap_val*100:11.2f}%")
    else:
        print(f"  {label:<20s} {bh_val:12.3f} {base_val:12.3f} {gap_val:12.3f}")

# Weight statistics
print(f"\n  Weight statistics (OOS):")
print(f"    Base VT avg weight:     {oos_strat['vt_base_weight'].mean():.3f}")
print(f"    GAP-Adj VT avg weight:  {oos_strat['vt_gap_weight'].mean():.3f}")
print(f"    Avg absolute adjustment: {oos_strat['gap_adjustment'].abs().mean():.4f}")
print(f"    Max positive adjustment: {oos_strat['gap_adjustment'].max():.4f}")
print(f"    Max negative adjustment: {oos_strat['gap_adjustment'].min():.4f}")

# ============================================================
# 9. Diebold-Mariano Test: GAP VT vs Base VT
# ============================================================
print("\n[9] Diebold-Mariano Test: GAP VT vs Base VT")
print("-" * 50)

# Loss = squared return deviation from mean (utility-based)
# Or simpler: compare daily returns directly using DM on loss differentials
# Use squared forecast errors of volatility? Or economic DM?

# Economic DM: compare strategy returns (higher is better → negate for loss)
loss_base = -oos_strat['ret_base_vt'].values
loss_gap = -oos_strat['ret_gap_vt'].values
d = loss_base - loss_gap  # positive = GAP is better

n_dm = len(d)
d_mean = d.mean()
# Newey-West HAC variance
max_lag = int(np.ceil(n_dm ** (1/3)))
gamma_0 = np.var(d, ddof=1)
gamma_sum = 0
for j in range(1, max_lag + 1):
    w = 1 - j / (max_lag + 1)
    cov_j = np.cov(d[j:], d[:-j])[0, 1]
    gamma_sum += 2 * w * cov_j

var_dm = (gamma_0 + gamma_sum) / n_dm
se_dm = np.sqrt(max(var_dm, 1e-12))
dm_stat = d_mean / se_dm
dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

print(f"  DM stat (GAP VT vs Base VT): {dm_stat:.4f}")
print(f"  DM p-value (two-sided):       {dm_pval:.4f}")
print(f"  Mean loss differential:        {d_mean:.6f}")
print(f"  Interpretation: {'GAP VT significantly better' if dm_pval < 0.05 and d_mean > 0 else 'GAP VT significantly worse' if dm_pval < 0.05 and d_mean < 0 else 'No significant difference'}")

# ============================================================
# 10. Multiple OOS Periods (Cross-OOS Validation)
# ============================================================
print("\n[10] Cross-OOS Validation")
print("-" * 50)

oos_periods = [
    ('2014-01-01', '2015-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2018-01-01', '2019-12-31'),
    ('2020-01-01', '2021-12-31'),
    ('2023-01-01', '2024-12-31'),
]

print(f"  {'OOS Period':<24s} {'Base Sharpe':>12s} {'GAP Sharpe':>12s} {'Diff':>8s} {'DM p':>8s} {'GAP Wins':>10s}")
print(f"  {'-'*78}")

cross_oos_results = []
gap_wins = 0
total_periods = 0

for start, end in oos_periods:
    sub = df_gap.loc[start:end].dropna(subset=['ret_base_vt', 'ret_gap_vt'])
    if len(sub) < 100:
        continue

    total_periods += 1
    base_m = compute_strategy_metrics(sub['ret_base_vt'], 'base')
    gap_m = compute_strategy_metrics(sub['ret_gap_vt'], 'gap')

    # DM test for this period
    d_sub = (-sub['ret_base_vt'].values) - (-sub['ret_gap_vt'].values)
    d_sub_mean = d_sub.mean()
    d_sub_var = np.var(d_sub, ddof=1) / len(d_sub)
    dm_sub = d_sub_mean / np.sqrt(max(d_sub_var, 1e-12))
    dm_sub_p = 2 * (1 - stats.norm.cdf(abs(dm_sub)))

    wins = 'YES' if gap_m['sharpe'] > base_m['sharpe'] else 'NO'
    if gap_m['sharpe'] > base_m['sharpe']:
        gap_wins += 1

    print(f"  {start}~{end}  {base_m['sharpe']:12.3f} {gap_m['sharpe']:12.3f} {gap_m['sharpe']-base_m['sharpe']:+8.3f} {dm_sub_p:8.4f} {wins:>10s}")

    cross_oos_results.append({
        'period': f"{start}~{end}",
        'base_sharpe': base_m['sharpe'],
        'gap_sharpe': gap_m['sharpe'],
        'dm_p': float(dm_sub_p),
        'gap_wins': gap_m['sharpe'] > base_m['sharpe']
    })

print(f"\n  GAP VT wins: {gap_wins}/{total_periods} periods")

# ============================================================
# 11. Historical Extreme GAP Events
# ============================================================
print("\n[11] Historical Extreme GAP Events")
print("-" * 50)

# Top 10 highest GAP_ratio days
df_gap_sorted = df_gap.sort_values('gap_ratio', ascending=False)

print(f"  Top 10 Highest GAP Ratio (Market MOST Fearful relative to realized):")
print(f"  {'Date':<12s} {'VIX':>8s} {'GARCH_σ_ann':>14s} {'GAP_ratio':>10s} {'5d Fwd Ret':>12s} {'22d Fwd Ret':>13s}")
for _, row in df_gap_sorted.head(10).iterrows():
    garch_ann = row['garch_sigma'] * np.sqrt(252) * 100
    fwd5 = row['fwd_ret_5d'] * 100 if not np.isnan(row['fwd_ret_5d']) else np.nan
    fwd22 = row['fwd_ret_22d'] * 100 if not np.isnan(row['fwd_ret_22d']) else np.nan
    print(f"  {_.strftime('%Y-%m-%d'):<12s} {row['vix']:8.2f} {garch_ann:13.2f}% {row['gap_ratio']:10.3f} {fwd5:11.2f}% {fwd22:12.2f}%")

print(f"\n  Top 10 Lowest GAP Ratio (Market MOST Complacent):")
print(f"  {'Date':<12s} {'VIX':>8s} {'GARCH_σ_ann':>14s} {'GAP_ratio':>10s} {'5d Fwd Ret':>12s} {'22d Fwd Ret':>13s}")
for _, row in df_gap_sorted.tail(10).iloc[::-1].iterrows():
    garch_ann = row['garch_sigma'] * np.sqrt(252) * 100
    fwd5 = row['fwd_ret_5d'] * 100 if not np.isnan(row['fwd_ret_5d']) else np.nan
    fwd22 = row['fwd_ret_22d'] * 100 if not np.isnan(row['fwd_ret_22d']) else np.nan
    print(f"  {_.strftime('%Y-%m-%d'):<12s} {row['vix']:8.2f} {garch_ann:13.2f}% {row['gap_ratio']:10.3f} {fwd5:11.2f}% {fwd22:12.2f}%")

# After extreme high GAP: average forward returns
top_5pct = df_gap['gap_ratio'].quantile(0.95)
bottom_5pct = df_gap['gap_ratio'].quantile(0.05)

extreme_high = df_gap[df_gap['gap_ratio'] > top_5pct]
extreme_low = df_gap[df_gap['gap_ratio'] < bottom_5pct]

print(f"\n  After Extreme High GAP (>95th pctl, n={len(extreme_high)}):")
print(f"    Avg 5d fwd return:  {extreme_high['fwd_ret_5d'].mean()*100:.3f}%")
print(f"    Avg 22d fwd return: {extreme_high['fwd_ret_22d'].mean()*100:.3f}%")
print(f"    Hit rate (22d > 0): {(extreme_high['fwd_ret_22d'] > 0).mean()*100:.1f}%")

print(f"\n  After Extreme Low GAP (<5th pctl, n={len(extreme_low)}):")
print(f"    Avg 5d fwd return:  {extreme_low['fwd_ret_5d'].mean()*100:.3f}%")
print(f"    Avg 22d fwd return: {extreme_low['fwd_ret_22d'].mean()*100:.3f}%")
print(f"    Hit rate (22d > 0): {(extreme_low['fwd_ret_22d'] > 0).mean()*100:.1f}%")

# t-test: extreme high vs extreme low forward returns
eh_fwd = extreme_high['fwd_ret_22d'].dropna()
el_fwd = extreme_low['fwd_ret_22d'].dropna()
t_extreme, p_extreme = stats.ttest_ind(eh_fwd, el_fwd, equal_var=False)
print(f"\n  t-test Extreme High vs Low (22d fwd ret): t={t_extreme:.3f}, p={p_extreme:.4f}")

# ============================================================
# 12. GAP Predictive Regression (OOS)
# ============================================================
print("\n[12] GAP Predictive Regression (OOS)")
print("-" * 50)

# Does GAP predict future vol beyond what VIX alone predicts?
oos_reg = df_gap.loc[OOS_START:OOS_END].dropna(subset=['gap', 'gap_ratio', 'rv_22d_fwd', 'vix', 'garch_sigma']).copy()

from numpy.linalg import lstsq

# Model 1: VIX alone → future RV
X1 = np.column_stack([oos_reg['vix'].values / 100, np.ones(len(oos_reg))])
y = oos_reg['rv_22d_fwd'].values
beta1, _, _, _ = lstsq(X1, y, rcond=None)
yhat1 = X1 @ beta1
ss_res1 = np.sum((y - yhat1)**2)
ss_tot = np.sum((y - y.mean())**2)
r2_vix = 1 - ss_res1 / ss_tot

# Model 2: VIX + GAP → future RV
X2 = np.column_stack([oos_reg['vix'].values / 100, oos_reg['gap'].values, np.ones(len(oos_reg))])
beta2, _, _, _ = lstsq(X2, y, rcond=None)
yhat2 = X2 @ beta2
ss_res2 = np.sum((y - yhat2)**2)
r2_vix_gap = 1 - ss_res2 / ss_tot

# Model 3: GARCH alone → future RV
X3 = np.column_stack([oos_reg['garch_sigma'].values * np.sqrt(252), np.ones(len(oos_reg))])
beta3, _, _, _ = lstsq(X3, y, rcond=None)
yhat3 = X3 @ beta3
ss_res3 = np.sum((y - yhat3)**2)
r2_garch = 1 - ss_res3 / ss_tot

# Model 4: GAP_ratio alone → future RV
X4 = np.column_stack([oos_reg['gap_ratio'].values, np.ones(len(oos_reg))])
beta4, _, _, _ = lstsq(X4, y, rcond=None)
yhat4 = X4 @ beta4
ss_res4 = np.sum((y - yhat4)**2)
r2_gap_ratio = 1 - ss_res4 / ss_tot

print(f"  OOS Predictive R² for 22d future realized vol:")
print(f"    VIX alone:         R² = {r2_vix:.4f}")
print(f"    GARCH alone:       R² = {r2_garch:.4f}")
print(f"    VIX + GAP:         R² = {r2_vix_gap:.4f} (Δ = {r2_vix_gap - r2_vix:+.4f})")
print(f"    GAP_ratio alone:   R² = {r2_gap_ratio:.4f}")

# F-test for incremental R² of GAP
k1 = 2  # VIX model params
k2 = 3  # VIX+GAP model params
n_reg = len(oos_reg)
f_stat = ((ss_res1 - ss_res2) / (k2 - k1)) / (ss_res2 / (n_reg - k2))
f_pval = 1 - stats.f.cdf(f_stat, k2 - k1, n_reg - k2)

print(f"\n  F-test for incremental R² (GAP beyond VIX):")
print(f"    F-stat = {f_stat:.3f}, p = {f_pval:.4f}")
print(f"    {'Significant' if f_pval < 0.05 else 'Not significant'}: GAP {'adds' if f_pval < 0.05 else 'does NOT add'} predictive power beyond VIX")

# ============================================================
# 13. DM Test: GARCH vol forecast vs VIX vol forecast
# ============================================================
print("\n[13] Forecasting Comparison: GARCH sigma vs VIX-implied sigma")
print("-" * 50)

# Who forecasts future 22d RV better? GARCH or VIX?
oos_fcast = df_gap.loc[OOS_START:OOS_END].dropna(subset=['garch_sigma', 'vix_daily', 'rv_22d_fwd']).copy()

# Convert to same scale (annualized)
garch_fcast = oos_fcast['garch_sigma'].values * np.sqrt(252)
vix_fcast = oos_fcast['vix'].values / 100  # already annualized
actual_rv = oos_fcast['rv_22d_fwd'].values

# QLIKE loss
qlike_garch = np.log(garch_fcast**2) + actual_rv**2 / garch_fcast**2
qlike_vix = np.log(vix_fcast**2) + actual_rv**2 / vix_fcast**2

d_qlike = qlike_garch - qlike_vix  # negative = GARCH better
d_qlike_mean = np.nanmean(d_qlike)
d_qlike_se = np.sqrt(np.nanvar(d_qlike, ddof=1) / len(d_qlike))
dm_qlike = d_qlike_mean / d_qlike_se
dm_qlike_p = 2 * (1 - stats.norm.cdf(abs(dm_qlike)))

# MSE loss
mse_garch = (garch_fcast - actual_rv)**2
mse_vix = (vix_fcast - actual_rv)**2

d_mse = mse_garch - mse_vix
d_mse_mean = np.nanmean(d_mse)
d_mse_se = np.sqrt(np.nanvar(d_mse, ddof=1) / len(d_mse))
dm_mse = d_mse_mean / d_mse_se
dm_mse_p = 2 * (1 - stats.norm.cdf(abs(dm_mse)))

print(f"  QLIKE Loss:")
print(f"    GARCH: {np.nanmean(qlike_garch):.4f}")
print(f"    VIX:   {np.nanmean(qlike_vix):.4f}")
print(f"    DM stat (GARCH vs VIX): {dm_qlike:.3f}, p={dm_qlike_p:.4f}")
print(f"    {'GARCH better' if d_qlike_mean < 0 else 'VIX better'}")

print(f"\n  MSE Loss:")
print(f"    GARCH: {np.nanmean(mse_garch):.6f}")
print(f"    VIX:   {np.nanmean(mse_vix):.6f}")
print(f"    DM stat (GARCH vs VIX): {dm_mse:.3f}, p={dm_mse_p:.4f}")
print(f"    {'GARCH better' if d_mse_mean < 0 else 'VIX better'}")

# ============================================================
# 14. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"""
  1. GAP Characteristics:
     - Mean GAP (VIX_daily - GARCH_σ): {gap.mean():.6f} ({gap.mean()*np.sqrt(252)*100:.2f}% ann.)
     - VIX typically {gap.mean()*np.sqrt(252)*100:+.2f}% above GARCH forecast (risk premium)
     - GAP is {(gap > 0).mean()*100:.0f}% positive (VIX usually > GARCH)
     - Highly persistent: ACF(1) = {gap_centered.autocorr(lag=1):.3f}, half-life = {half_life:.1f}d

  2. Predictive Power:
     - GAP → Future 22d RV: r = {r_22d:.4f} (raw), partial r|VIX = {pr_22d:.4f}
     - GAP adds {r2_vix_gap - r2_vix:+.4f} R² beyond VIX alone (F-test p = {f_pval:.4f})
     - {'GAP has incremental predictive power' if f_pval < 0.05 else 'GAP does NOT add predictive power beyond VIX'}

  3. Regime Analysis:
     - High Fear (GAP_ratio > 75th pctl) vs Complacent (< 25th pctl)
     - t-test (22d fwd return): t = {t_regime:.3f}, p = {p_regime:.4f}
     - Extreme events confirm: High GAP → {'positive' if extreme_high['fwd_ret_22d'].mean() > 0 else 'negative'} 22d returns, Low GAP → {'positive' if extreme_low['fwd_ret_22d'].mean() > 0 else 'negative'} 22d returns

  4. GAP-Adjusted VT (OOS 2023-2024):
     - Base 12/VIX Sharpe: {base_vt_metrics['sharpe']:.3f}
     - GAP-Adjusted Sharpe: {gap_vt_metrics['sharpe']:.3f} (Δ = {gap_vt_metrics['sharpe'] - base_vt_metrics['sharpe']:+.3f})
     - DM test p = {dm_pval:.4f}: {'Significant' if dm_pval < 0.05 else 'Not significant'}
     - Cross-OOS: GAP wins {gap_wins}/{total_periods} periods

  5. GARCH vs VIX as vol forecaster:
     - QLIKE DM: {'GARCH' if d_qlike_mean < 0 else 'VIX'} wins (p = {dm_qlike_p:.4f})
     - MSE DM: {'GARCH' if d_mse_mean < 0 else 'VIX'} wins (p = {dm_mse_p:.4f})

  Conclusion:
     The implied-realized gap captures the volatility risk premium.
     VIX consistently exceeds GARCH forecasts, confirming a positive risk premium.
     {'The GAP adds incremental predictive power beyond VIX for future realized vol.' if f_pval < 0.05 else 'The GAP does NOT add significant predictive power beyond VIX alone.'}
     {'GAP-adjusted VT shows improvement over base VT.' if gap_vt_metrics['sharpe'] > base_vt_metrics['sharpe'] and dm_pval < 0.1 else 'GAP-adjusted VT does NOT significantly improve over base 12/VIX VT.'}
     {'This is consistent with VIX sufficiency: VIX already incorporates the information in the gap.' if f_pval >= 0.05 else 'The gap provides orthogonal information to VIX.'}
""")

# ============================================================
# Save Results
# ============================================================
results = {
    'experiment': 'K208',
    'title': 'Implied-Realized Volatility Gap as Dynamic Risk Indicator',
    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'data': {
        'asset': 'SPY',
        'vix_source': '^VIX (yfinance)',
        'data_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'total_obs': len(df),
        'gap_obs': len(df_gap),
        'oos_period': f"{OOS_START} to {OOS_END}",
        'garch_window': WINDOW
    },
    'gap_characteristics': {
        'mean_daily': float(gap.mean()),
        'mean_annualized_pct': float(gap.mean() * np.sqrt(252) * 100),
        'std_daily': float(gap.std()),
        'std_annualized_pct': float(gap.std() * np.sqrt(252) * 100),
        'pct_positive': float((gap > 0).mean()),
        'skewness': float(gap.skew()),
        'kurtosis': float(gap.kurtosis()),
        'acf_1': float(gap_centered.autocorr(lag=1)),
        'half_life_days': float(half_life) if not np.isnan(half_life) else None,
        'gap_ratio_mean': float(gap_ratio.mean()),
        'gap_ratio_std': float(gap_ratio.std()),
        'gap_ratio_median': float(gap_ratio.median())
    },
    'predictive_power': {
        'raw_corr_5d': {'r': float(r_5d), 'p': float(p_5d)},
        'raw_corr_22d': {'r': float(r_22d), 'p': float(p_22d)},
        'partial_corr_5d_given_vix': {'r': float(pr_5d), 'p': float(pp_5d)},
        'partial_corr_22d_given_vix': {'r': float(pr_22d), 'p': float(pp_22d)},
        'partial_corr_5d_given_garch': {'r': float(prg_5d), 'p': float(ppg_5d)},
        'partial_corr_22d_given_garch': {'r': float(prg_22d), 'p': float(ppg_22d)},
        'oos_r2_vix_alone': float(r2_vix),
        'oos_r2_garch_alone': float(r2_garch),
        'oos_r2_vix_plus_gap': float(r2_vix_gap),
        'oos_r2_gap_ratio_alone': float(r2_gap_ratio),
        'incremental_r2': float(r2_vix_gap - r2_vix),
        'f_test_stat': float(f_stat),
        'f_test_pval': float(f_pval)
    },
    'regime_analysis': {
        'oos_regime_stats': regime_stats,
        'regime_ttest': {'t': float(t_regime), 'p': float(p_regime)},
        'extreme_high_22d_ret': float(extreme_high['fwd_ret_22d'].mean()),
        'extreme_low_22d_ret': float(extreme_low['fwd_ret_22d'].mean()),
        'extreme_ttest': {'t': float(t_extreme), 'p': float(p_extreme)}
    },
    'strategy': {
        'buy_hold': bh_metrics,
        'base_12vix': base_vt_metrics,
        'gap_adjusted_vt': gap_vt_metrics,
        'dm_test': {'stat': float(dm_stat), 'pval': float(dm_pval)},
        'adjustment_scale': ADJUSTMENT_SCALE
    },
    'cross_oos': {
        'results': cross_oos_results,
        'gap_wins': gap_wins,
        'total_periods': total_periods
    },
    'garch_vs_vix': {
        'qlike_garch': float(np.nanmean(qlike_garch)),
        'qlike_vix': float(np.nanmean(qlike_vix)),
        'dm_qlike': {'stat': float(dm_qlike), 'p': float(dm_qlike_p)},
        'mse_garch': float(np.nanmean(mse_garch)),
        'mse_vix': float(np.nanmean(mse_vix)),
        'dm_mse': {'stat': float(dm_mse), 'p': float(dm_mse_p)}
    }
}

results_path = 'experiments/k208/k208_implied_realized_gap_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print("=" * 70)
print("K208 Complete.")
