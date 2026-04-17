"""
K404: Cross-Sectional Volatility Factors
=========================================
What predicts WHICH asset will be most volatile?

This is fundamentally different from time-series vol prediction.
Time-series: "will SPY vol be HIGH or LOW next month?"
Cross-section: "will SPY or GLD or BTC be MORE volatile next month?"

Data: yfinance real data, 2015-2024, 8 assets:
  SPY, QQQ, GLD, TLT, EEM, IWM, CL=F, BTC-USD

Methodology:
1. Monthly cross-section: rank 8 assets by realized vol, VIX beta, momentum
2. Rank persistence: Spearman correlation of vol ranks month-to-month
3. Cross-sectional vol factor: long low-vol, short high-vol
4. Regime dependence: calm vs crisis rank stability

[Proposed: Claude, Executed: Claude]
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
print("K404: Cross-Sectional Volatility Factors")
print("=" * 70)

ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'IWM', 'CL=F', 'BTC-USD']
ASSET_NAMES = {
    'SPY': 'S&P 500', 'QQQ': 'Nasdaq 100', 'GLD': 'Gold',
    'TLT': '20Y Treasury', 'EEM': 'EM Equity', 'IWM': 'Russell 2000',
    'CL=F': 'Crude Oil', 'BTC-USD': 'Bitcoin'
}
START = '2015-01-01'
END = '2024-12-31'

print(f"\nDownloading {len(ASSETS)} assets from {START} to {END}...")

# Download all assets
prices = {}
for asset in ASSETS:
    try:
        df = yf.download(asset, start=START, end=END, auto_adjust=True, progress=False)
        if len(df) > 500:
            prices[asset] = df['Close'].squeeze()
            print(f"  {asset}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"  {asset}: INSUFFICIENT DATA ({len(df)} days), skipping")
    except Exception as e:
        print(f"  {asset}: DOWNLOAD FAILED ({e}), skipping")

# Also download VIX for regime classification and VIX beta
vix = yf.download('^VIX', start=START, end=END, auto_adjust=True, progress=False)['Close'].squeeze()
print(f"  VIX: {len(vix)} days")

# Align all prices to common dates
common_dates = prices[list(prices.keys())[0]].index
for asset in prices:
    common_dates = common_dates.intersection(prices[asset].index)
common_dates = common_dates.intersection(vix.index)
common_dates = common_dates.sort_values()

print(f"\nCommon trading days: {len(common_dates)}")
print(f"Period: {common_dates[0].date()} to {common_dates[-1].date()}")

# Build aligned DataFrames
price_df = pd.DataFrame({asset: prices[asset].reindex(common_dates) for asset in prices})
ret_df = price_df.pct_change().dropna()
vix_aligned = vix.reindex(ret_df.index)

# Drop rows with any NaN
mask = ret_df.notna().all(axis=1) & vix_aligned.notna()
ret_df = ret_df[mask]
vix_aligned = vix_aligned[mask]

active_assets = list(ret_df.columns)
N_ASSETS = len(active_assets)
print(f"Active assets: {N_ASSETS} — {active_assets}")
print(f"Clean return days: {len(ret_df)}")

# ============================================================
# 2. MONTHLY CROSS-SECTIONAL CHARACTERISTICS
# ============================================================
print("\n" + "=" * 70)
print("STEP 2: Computing monthly cross-sectional characteristics")
print("=" * 70)

# Resample to month-end dates
month_ends = ret_df.resample('ME').last().index

results_monthly = []

for i, me in enumerate(month_ends):
    if i < 1:  # need at least 1 prior month
        continue

    # Get trading days in this month
    if i == 0:
        prev_me = ret_df.index[0]
    else:
        prev_me = month_ends[i - 1]

    month_mask = (ret_df.index > prev_me) & (ret_df.index <= me)
    month_rets = ret_df[month_mask]

    if len(month_rets) < 15:  # need enough days
        continue

    # Also get trailing 22-day window ending at month-end for realized vol
    idx_pos = ret_df.index.get_loc(me) if me in ret_df.index else None
    if idx_pos is None:
        # Find closest
        idx_pos = ret_df.index.searchsorted(me) - 1
    if idx_pos < 22:
        continue

    trailing_22d = ret_df.iloc[idx_pos - 21:idx_pos + 1]

    # Get trailing 60-day for VIX beta
    trailing_60d = ret_df.iloc[max(0, idx_pos - 59):idx_pos + 1]
    vix_60d = vix_aligned.iloc[max(0, idx_pos - 59):idx_pos + 1]
    vix_ret_60d = vix_60d.pct_change().dropna()

    record = {'date': me}

    for asset in active_assets:
        # 1. Realized vol (annualized, trailing 22d)
        rv = trailing_22d[asset].std() * np.sqrt(252)
        record[f'{asset}_rv'] = rv

        # 2. VIX beta (trailing 60d)
        common_vix = vix_ret_60d.index.intersection(trailing_60d.index)
        if len(common_vix) > 20:
            asset_rets_60 = trailing_60d[asset].reindex(common_vix).dropna()
            vix_rets_60 = vix_ret_60d.reindex(common_vix).dropna()
            common_idx = asset_rets_60.index.intersection(vix_rets_60.index)
            if len(common_idx) > 20:
                slope, _, _, _, _ = stats.linregress(
                    vix_rets_60.reindex(common_idx).values,
                    asset_rets_60.reindex(common_idx).values
                )
                record[f'{asset}_vix_beta'] = slope
            else:
                record[f'{asset}_vix_beta'] = np.nan
        else:
            record[f'{asset}_vix_beta'] = np.nan

        # 3. Past month return (momentum)
        mom = (1 + month_rets[asset]).prod() - 1
        record[f'{asset}_mom'] = mom

    # VIX level at month-end
    record['vix_level'] = vix_aligned.iloc[idx_pos]

    results_monthly.append(record)

monthly_df = pd.DataFrame(results_monthly).set_index('date')
print(f"Monthly observations: {len(monthly_df)}")
print(f"Period: {monthly_df.index[0].date()} to {monthly_df.index[-1].date()}")

# ============================================================
# 3. RANK PERSISTENCE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("STEP 3: Volatility Rank Persistence")
print("=" * 70)

# Extract vol ranks each month
rv_cols = [f'{a}_rv' for a in active_assets]
rv_df = monthly_df[rv_cols].copy()
rv_df.columns = active_assets

# Rank: 1 = lowest vol, N = highest vol
rank_df = rv_df.rank(axis=1)

# Month-to-month Spearman correlation of ranks
spearman_corrs = []
for i in range(1, len(rank_df)):
    corr, pval = stats.spearmanr(rank_df.iloc[i - 1].values, rank_df.iloc[i].values)
    spearman_corrs.append({
        'date': rank_df.index[i],
        'spearman_rho': corr,
        'pval': pval,
        'vix': monthly_df.iloc[i]['vix_level']
    })

spearman_df = pd.DataFrame(spearman_corrs).set_index('date')

mean_rho = spearman_df['spearman_rho'].mean()
median_rho = spearman_df['spearman_rho'].median()
std_rho = spearman_df['spearman_rho'].std()
pct_significant = (spearman_df['pval'] < 0.05).mean() * 100

# T-test: is mean rho significantly different from 0?
t_stat_rho, p_val_rho = stats.ttest_1samp(spearman_df['spearman_rho'].dropna(), 0)

print(f"\nMonth-to-month rank correlation (Spearman rho):")
print(f"  Mean rho:   {mean_rho:.4f}")
print(f"  Median rho: {median_rho:.4f}")
print(f"  Std rho:    {std_rho:.4f}")
print(f"  t-stat:     {t_stat_rho:.2f}  (H0: rho=0)")
print(f"  p-value:    {p_val_rho:.6f}")
print(f"  % months with p<0.05: {pct_significant:.1f}%")

print(f"\n  INTERPRETATION: ", end="")
if mean_rho > 0.5 and t_stat_rho > 3.0:
    print("STRONG persistence — vol ranking is highly sticky")
elif mean_rho > 0.3 and p_val_rho < 0.01:
    print("MODERATE persistence — vol ranking has predictable structure")
elif mean_rho > 0 and p_val_rho < 0.05:
    print("WEAK persistence — some signal but noisy")
else:
    print("NO significant persistence — vol ranking is essentially random")

# Longer-horizon persistence: 3-month, 6-month, 12-month
print(f"\n  Multi-horizon rank persistence:")
for lag in [1, 3, 6, 12]:
    lag_corrs = []
    for i in range(lag, len(rank_df)):
        corr, _ = stats.spearmanr(rank_df.iloc[i - lag].values, rank_df.iloc[i].values)
        lag_corrs.append(corr)
    if lag_corrs:
        mean_c = np.mean(lag_corrs)
        t_c, p_c = stats.ttest_1samp(lag_corrs, 0)
        print(f"    {lag:2d}-month lag: mean rho = {mean_c:.4f}, t = {t_c:.2f}, p = {p_c:.4f}")

# ============================================================
# 4. WHICH CHARACTERISTICS PREDICT NEXT-MONTH VOL RANK?
# ============================================================
print("\n" + "=" * 70)
print("STEP 4: Cross-Sectional Predictors of Vol Rank")
print("=" * 70)

# For each month, run cross-sectional regression:
# next_month_vol_rank = a + b1 * this_month_vol_rank + b2 * vix_beta_rank + b3 * momentum_rank
# (Fama-MacBeth style: run cross-section each month, then average coefficients)

fm_results = {'const': [], 'rv_rank': [], 'vix_beta_rank': [], 'mom_rank': []}

for i in range(len(monthly_df) - 1):
    this_month = monthly_df.iloc[i]
    next_month = monthly_df.iloc[i + 1]

    # Current month characteristics
    rvs = np.array([this_month[f'{a}_rv'] for a in active_assets])
    vix_betas = np.array([this_month[f'{a}_vix_beta'] for a in active_assets])
    moms = np.array([this_month[f'{a}_mom'] for a in active_assets])

    # Next month realized vol
    next_rvs = np.array([next_month[f'{a}_rv'] for a in active_assets])

    # Check for NaN
    valid = ~(np.isnan(rvs) | np.isnan(vix_betas) | np.isnan(moms) | np.isnan(next_rvs))
    if valid.sum() < 5:
        continue

    # Rank everything (within cross-section)
    from scipy.stats import rankdata
    rv_rank = rankdata(rvs[valid])
    vb_rank = rankdata(vix_betas[valid])  # more negative = more risk-off
    mom_rank = rankdata(moms[valid])
    next_rv_rank = rankdata(next_rvs[valid])

    # Cross-sectional OLS
    X = np.column_stack([np.ones(valid.sum()), rv_rank, vb_rank, mom_rank])
    y = next_rv_rank

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        fm_results['const'].append(beta[0])
        fm_results['rv_rank'].append(beta[1])
        fm_results['vix_beta_rank'].append(beta[2])
        fm_results['mom_rank'].append(beta[3])
    except:
        continue

print(f"\nFama-MacBeth Cross-Sectional Regressions ({len(fm_results['rv_rank'])} months)")
print(f"Dependent variable: NEXT month vol rank")
print(f"Independent variables: THIS month characteristics (all ranked)")
print(f"\n{'Variable':<20} {'Mean Coef':>10} {'t-stat':>8} {'p-value':>10} {'Significant':>12}")
print("-" * 62)

fm_summary = {}
for var in ['rv_rank', 'vix_beta_rank', 'mom_rank']:
    coefs = np.array(fm_results[var])
    mean_coef = coefs.mean()
    # Newey-West would be ideal, but for now use standard t-test
    t_stat = mean_coef / (coefs.std() / np.sqrt(len(coefs)))
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(coefs) - 1))
    sig = "***" if abs(t_stat) > 3.0 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""

    label = {'rv_rank': 'Realized Vol', 'vix_beta_rank': 'VIX Beta', 'mom_rank': 'Momentum'}[var]
    print(f"  {label:<18} {mean_coef:>10.4f} {t_stat:>8.2f} {p_val:>10.4f} {sig:>12}")

    fm_summary[var] = {'mean_coef': float(mean_coef), 't_stat': float(t_stat), 'p_val': float(p_val)}

# ============================================================
# 5. LOW-VOL ANOMALY: CROSS-SECTIONAL PORTFOLIO
# ============================================================
print("\n" + "=" * 70)
print("STEP 5: Low-Volatility Anomaly (Cross-Sectional)")
print("=" * 70)
print("Strategy: Each month, rank assets by trailing vol.")
print("  Long bottom 50% (low vol), Short top 50% (high vol)")
print("  Equal weight within each leg.")

# Build long-short portfolio
portfolio_rets = []
long_leg_rets = []
short_leg_rets = []

for i in range(len(monthly_df) - 1):
    this_month = monthly_df.iloc[i]
    next_month_start = monthly_df.index[i]
    next_month_end = monthly_df.index[i + 1]

    # Current vol ranking
    rvs = {a: this_month[f'{a}_rv'] for a in active_assets}
    rvs_clean = {k: v for k, v in rvs.items() if not np.isnan(v)}

    if len(rvs_clean) < 4:
        continue

    sorted_assets = sorted(rvs_clean.keys(), key=lambda x: rvs_clean[x])
    n_half = len(sorted_assets) // 2
    low_vol_assets = sorted_assets[:n_half]
    high_vol_assets = sorted_assets[n_half:]

    # Get next month returns
    next_mask = (ret_df.index > next_month_start) & (ret_df.index <= next_month_end)
    next_rets = ret_df[next_mask]

    if len(next_rets) < 10:
        continue

    # Monthly return for each leg
    long_ret = np.mean([(1 + next_rets[a]).prod() - 1 for a in low_vol_assets])
    short_ret = np.mean([(1 + next_rets[a]).prod() - 1 for a in high_vol_assets])
    ls_ret = long_ret - short_ret

    portfolio_rets.append({
        'date': next_month_end,
        'long_ret': long_ret,
        'short_ret': short_ret,
        'ls_ret': ls_ret,
        'vix': this_month['vix_level'],
        'long_assets': low_vol_assets,
        'short_assets': high_vol_assets
    })

port_df = pd.DataFrame(portfolio_rets).set_index('date')

# Performance metrics
ls_mean = port_df['ls_ret'].mean() * 12  # annualized
ls_std = port_df['ls_ret'].std() * np.sqrt(12)
ls_sharpe = ls_mean / ls_std if ls_std > 0 else 0
ls_t = port_df['ls_ret'].mean() / (port_df['ls_ret'].std() / np.sqrt(len(port_df)))

long_mean = port_df['long_ret'].mean() * 12
long_std = port_df['long_ret'].std() * np.sqrt(12)
long_sharpe = long_mean / long_std if long_std > 0 else 0

short_mean = port_df['short_ret'].mean() * 12
short_std = port_df['short_ret'].std() * np.sqrt(12)
short_sharpe = short_mean / short_std if short_std > 0 else 0

# Cumulative returns
cum_ls = (1 + port_df['ls_ret']).cumprod()
cum_long = (1 + port_df['long_ret']).cumprod()
cum_short = (1 + port_df['short_ret']).cumprod()

# Max drawdown
def max_drawdown(cum_rets):
    peak = cum_rets.cummax()
    dd = (cum_rets - peak) / peak
    return dd.min()

mdd_ls = max_drawdown(cum_ls)
mdd_long = max_drawdown(cum_long)

print(f"\nSample: {len(port_df)} months ({port_df.index[0].date()} to {port_df.index[-1].date()})")
print(f"\n{'Metric':<25} {'Long (Low-Vol)':>15} {'Short (High-Vol)':>17} {'Long-Short':>12}")
print("-" * 72)
print(f"{'Ann. Return':<25} {long_mean:>14.2%} {short_mean:>16.2%} {ls_mean:>11.2%}")
print(f"{'Ann. Volatility':<25} {long_std:>14.2%} {short_std:>16.2%} {ls_std:>11.2%}")
print(f"{'Sharpe Ratio':<25} {long_sharpe:>14.3f} {short_sharpe:>16.3f} {ls_sharpe:>11.3f}")
print(f"{'Max Drawdown':<25} {mdd_long:>14.2%} {'':>16} {mdd_ls:>11.2%}")
print(f"{'t-stat (H0: ret=0)':<25} {'':>15} {'':>17} {ls_t:>11.2f}")

# Win rate
win_rate = (port_df['ls_ret'] > 0).mean()
print(f"{'Win Rate':<25} {'':>15} {'':>17} {win_rate:>11.1%}")

# ============================================================
# 6. REGIME DEPENDENCE
# ============================================================
print("\n" + "=" * 70)
print("STEP 6: Regime Dependence of Vol Rank Persistence")
print("=" * 70)

# Classify months by VIX level
vix_median = spearman_df['vix'].median()
vix_75 = spearman_df['vix'].quantile(0.75)

calm = spearman_df[spearman_df['vix'] < vix_median]
elevated = spearman_df[(spearman_df['vix'] >= vix_median) & (spearman_df['vix'] < vix_75)]
crisis = spearman_df[spearman_df['vix'] >= vix_75]

print(f"\nVIX thresholds: median={vix_median:.1f}, 75th pctl={vix_75:.1f}")
print(f"\n{'Regime':<20} {'N months':>10} {'Mean Rho':>10} {'Std':>8} {'t-stat':>8} {'p-value':>10}")
print("-" * 68)

regime_results = {}
for name, subset in [('Calm (VIX<med)', calm), ('Elevated', elevated), ('Crisis (VIX>75p)', crisis)]:
    n = len(subset)
    if n < 5:
        print(f"  {name:<18} {n:>10} — insufficient data")
        continue
    mean_r = subset['spearman_rho'].mean()
    std_r = subset['spearman_rho'].std()
    t_r, p_r = stats.ttest_1samp(subset['spearman_rho'].dropna(), 0)
    print(f"  {name:<18} {n:>10} {mean_r:>10.4f} {std_r:>8.4f} {t_r:>8.2f} {p_r:>10.4f}")
    regime_results[name] = {'n': int(n), 'mean_rho': float(mean_r), 't_stat': float(t_r), 'p_val': float(p_r)}

# Test difference between calm and crisis
if len(calm) >= 5 and len(crisis) >= 5:
    t_diff, p_diff = stats.ttest_ind(calm['spearman_rho'].dropna(), crisis['spearman_rho'].dropna())
    print(f"\n  Calm vs Crisis difference: t={t_diff:.2f}, p={p_diff:.4f}")
    if p_diff < 0.05:
        print("  -> Rank persistence differs SIGNIFICANTLY between regimes")
    else:
        print("  -> No significant difference in rank persistence across regimes")

# ============================================================
# 7. LOW-VOL ANOMALY BY REGIME
# ============================================================
print("\n" + "=" * 70)
print("STEP 7: Low-Vol Anomaly by VIX Regime")
print("=" * 70)

port_vix_median = port_df['vix'].median()

calm_port = port_df[port_df['vix'] < port_vix_median]
crisis_port = port_df[port_df['vix'] >= port_vix_median]

print(f"\n{'Regime':<20} {'N':>5} {'Ann. L-S Ret':>14} {'Sharpe':>8} {'Win Rate':>10} {'t-stat':>8}")
print("-" * 68)

for name, subset in [('Calm (VIX<med)', calm_port), ('Crisis (VIX>=med)', crisis_port)]:
    n = len(subset)
    if n < 5:
        continue
    ann_ret = subset['ls_ret'].mean() * 12
    ann_vol = subset['ls_ret'].std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    wr = (subset['ls_ret'] > 0).mean()
    t_s = subset['ls_ret'].mean() / (subset['ls_ret'].std() / np.sqrt(n))
    print(f"  {name:<18} {n:>5} {ann_ret:>13.2%} {sharpe:>8.3f} {wr:>9.1%} {t_s:>8.2f}")

# ============================================================
# 8. INDIVIDUAL ASSET VOL RANK STABILITY
# ============================================================
print("\n" + "=" * 70)
print("STEP 8: Asset-Level Vol Rank Stability")
print("=" * 70)
print("How stable is each asset's vol rank over time?")

print(f"\n{'Asset':<12} {'Mean Rank':>10} {'Std Rank':>10} {'% in Top 3':>12} {'% in Bot 3':>12} {'Predictable':>12}")
print("-" * 70)

asset_rank_stats = {}
for asset in active_assets:
    ranks = rank_df[asset]
    mean_r = ranks.mean()
    std_r = ranks.std()
    pct_top3 = (ranks >= N_ASSETS - 2).mean() * 100  # top 3 = highest vol
    pct_bot3 = (ranks <= 3).mean() * 100  # bottom 3 = lowest vol

    # Autocorrelation of rank (is this asset's rank predictable?)
    rank_ac = ranks.autocorr(lag=1)
    predictable = "Yes" if rank_ac > 0.5 else "Moderate" if rank_ac > 0.3 else "No"

    label = f"{asset}"
    print(f"  {label:<10} {mean_r:>10.1f} {std_r:>10.2f} {pct_top3:>11.0f}% {pct_bot3:>11.0f}% {predictable:>12} (AC={rank_ac:.2f})")

    asset_rank_stats[asset] = {
        'mean_rank': float(mean_r),
        'std_rank': float(std_r),
        'rank_autocorr': float(rank_ac),
        'pct_top3': float(pct_top3),
        'pct_bot3': float(pct_bot3)
    }

# ============================================================
# 9. TRANSITION MATRIX: WHO BECOMES HIGH-VOL?
# ============================================================
print("\n" + "=" * 70)
print("STEP 9: Vol Rank Transition Matrix")
print("=" * 70)
print("Probability that an asset in vol quartile Q this month")
print("ends up in quartile Q' next month.")

# Quartiles: 1=low vol, 2=mid-low, 3=mid-high, 4=high vol
quartile_df = rv_df.rank(axis=1).apply(lambda x: pd.qcut(x, 4, labels=[1, 2, 3, 4], duplicates='drop'), axis=1)

# Handle potential issues with qcut on small cross-section
# Use simple quartile assignment instead
def assign_quartile(ranks, n_assets):
    """Assign quartiles based on rank position."""
    q = np.ceil(ranks / n_assets * 4).clip(1, 4).astype(int)
    return q

quartile_df2 = rank_df.apply(lambda row: assign_quartile(row, N_ASSETS), axis=1)

transition = np.zeros((4, 4))
for i in range(1, len(quartile_df2)):
    for asset in active_assets:
        q_this = quartile_df2.iloc[i - 1][asset]
        q_next = quartile_df2.iloc[i][asset]
        if not np.isnan(q_this) and not np.isnan(q_next):
            transition[int(q_this) - 1][int(q_next) - 1] += 1

# Normalize to probabilities
transition_prob = transition / transition.sum(axis=1, keepdims=True)

print(f"\n{'From \\ To':<12} {'Q1(Low)':>10} {'Q2':>10} {'Q3':>10} {'Q4(High)':>10}")
print("-" * 54)
for i in range(4):
    label = ['Q1 (Low)', 'Q2', 'Q3', 'Q4 (High)'][i]
    row = transition_prob[i]
    print(f"  {label:<10} {row[0]:>9.1%} {row[1]:>9.1%} {row[2]:>9.1%} {row[3]:>9.1%}")

print(f"\n  Diagonal dominance = vol quartile persistence")
diag_mean = np.mean(np.diag(transition_prob))
print(f"  Average diagonal probability: {diag_mean:.1%}")
print(f"  Random baseline: 25.0%")
print(f"  Excess persistence: {diag_mean - 0.25:.1%}")

# ============================================================
# 10. CROSS-SECTIONAL VOL DISPERSION
# ============================================================
print("\n" + "=" * 70)
print("STEP 10: Cross-Sectional Vol Dispersion Over Time")
print("=" * 70)

# Monthly cross-sectional std of realized vols
cs_dispersion = rv_df.std(axis=1)
cs_mean_vol = rv_df.mean(axis=1)
cs_cv = cs_dispersion / cs_mean_vol  # coefficient of variation

print(f"\nCross-sectional vol dispersion (std of vol across assets each month):")
print(f"  Mean dispersion:   {cs_dispersion.mean():.4f}")
print(f"  Std of dispersion: {cs_dispersion.std():.4f}")
print(f"  Mean CV:           {cs_cv.mean():.3f}")

# Does dispersion predict next-month average vol?
cs_disp_shifted = cs_dispersion.shift(1)
valid_mask = cs_disp_shifted.notna() & cs_mean_vol.notna()
corr_disp_vol, p_disp_vol = stats.pearsonr(
    cs_disp_shifted[valid_mask].values,
    cs_mean_vol[valid_mask].values
)
print(f"\n  Dispersion(t) -> Mean Vol(t+1): r={corr_disp_vol:.4f}, p={p_disp_vol:.4f}")

# Does dispersion correlate with VIX?
vix_monthly = monthly_df['vix_level']
valid_mask2 = cs_dispersion.index.isin(vix_monthly.index)
cs_disp_aligned = cs_dispersion[valid_mask2]
vix_aligned2 = vix_monthly.reindex(cs_disp_aligned.index).dropna()
common_idx = cs_disp_aligned.index.intersection(vix_aligned2.index)

if len(common_idx) > 10:
    corr_disp_vix, p_disp_vix = stats.pearsonr(
        cs_disp_aligned.reindex(common_idx).values,
        vix_aligned2.reindex(common_idx).values
    )
    print(f"  Dispersion vs VIX level:        r={corr_disp_vix:.4f}, p={p_disp_vix:.4f}")

# ============================================================
# 11. BOOTSTRAP CONFIDENCE INTERVALS
# ============================================================
print("\n" + "=" * 70)
print("STEP 11: Bootstrap Confidence Intervals")
print("=" * 70)

N_BOOT = 10000
np.random.seed(42)

# Bootstrap the key statistics
ls_rets = port_df['ls_ret'].values
rho_vals = spearman_df['spearman_rho'].dropna().values

boot_sharpes = []
boot_rhos = []
for _ in range(N_BOOT):
    # Resample monthly L-S returns
    idx = np.random.choice(len(ls_rets), size=len(ls_rets), replace=True)
    boot_ret = ls_rets[idx]
    boot_sharpe = (boot_ret.mean() * 12) / (boot_ret.std() * np.sqrt(12)) if boot_ret.std() > 0 else 0
    boot_sharpes.append(boot_sharpe)

    # Resample rank correlations
    idx2 = np.random.choice(len(rho_vals), size=len(rho_vals), replace=True)
    boot_rhos.append(rho_vals[idx2].mean())

boot_sharpes = np.array(boot_sharpes)
boot_rhos = np.array(boot_rhos)

sharpe_ci = np.percentile(boot_sharpes, [2.5, 97.5])
rho_ci = np.percentile(boot_rhos, [2.5, 97.5])

print(f"\nBootstrap ({N_BOOT} replications):")
print(f"  L-S Sharpe: {ls_sharpe:.3f}  95% CI: [{sharpe_ci[0]:.3f}, {sharpe_ci[1]:.3f}]")
print(f"  Mean Rho:   {mean_rho:.4f}  95% CI: [{rho_ci[0]:.4f}, {rho_ci[1]:.4f}]")

sharpe_pct_positive = (boot_sharpes > 0).mean() * 100
rho_pct_positive = (boot_rhos > 0).mean() * 100
print(f"  P(Sharpe > 0): {sharpe_pct_positive:.1f}%")
print(f"  P(Rho > 0):    {rho_pct_positive:.1f}%")

# ============================================================
# 12. SUB-PERIOD ROBUSTNESS
# ============================================================
print("\n" + "=" * 70)
print("STEP 12: Sub-Period Robustness")
print("=" * 70)

# Split into 2 halves
mid_idx = len(port_df) // 2
half1 = port_df.iloc[:mid_idx]
half2 = port_df.iloc[mid_idx:]

mid_idx_rho = len(spearman_df) // 2
rho_half1 = spearman_df.iloc[:mid_idx_rho]
rho_half2 = spearman_df.iloc[mid_idx_rho:]

print(f"\n{'Sub-period':<30} {'L-S Sharpe':>12} {'Mean Rho':>10} {'N months':>10}")
print("-" * 64)

for name, port_sub, rho_sub in [
    (f'First half ({half1.index[0].date()}-{half1.index[-1].date()})', half1, rho_half1),
    (f'Second half ({half2.index[0].date()}-{half2.index[-1].date()})', half2, rho_half2)
]:
    ann_ret = port_sub['ls_ret'].mean() * 12
    ann_vol = port_sub['ls_ret'].std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    mr = rho_sub['spearman_rho'].mean()
    print(f"  {name:<28} {sharpe:>12.3f} {mr:>10.4f} {len(port_sub):>10}")

# Year-by-year
print(f"\n  Year-by-year L-S Sharpe:")
for year in range(2015, 2025):
    year_mask = port_df.index.year == year
    if year_mask.sum() < 6:
        continue
    yr = port_df[year_mask]
    ann_ret = yr['ls_ret'].mean() * 12
    ann_vol = yr['ls_ret'].std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    print(f"    {year}: Sharpe = {sharpe:>7.3f}  (N={year_mask.sum()} months, ret={ann_ret:>7.2%})")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K404 SUMMARY: Cross-Sectional Volatility Factors")
print("=" * 70)

print(f"""
DATA: {N_ASSETS} assets, {len(ret_df)} trading days, {len(monthly_df)} months
      {ret_df.index[0].date()} to {ret_df.index[-1].date()}
      Source: yfinance (real data)

KEY FINDINGS:

1. VOL RANK PERSISTENCE:
   - Month-to-month Spearman rho = {mean_rho:.4f} (t={t_stat_rho:.2f})
   - Interpretation: {'Strong' if mean_rho > 0.5 else 'Moderate' if mean_rho > 0.3 else 'Weak' if mean_rho > 0 else 'No'} persistence
   - Transition matrix diagonal: {diag_mean:.1%} (random = 25%)
   - Bootstrap 95% CI for rho: [{rho_ci[0]:.4f}, {rho_ci[1]:.4f}]

2. CROSS-SECTIONAL PREDICTORS (Fama-MacBeth):
   - Realized Vol rank: coef={fm_summary['rv_rank']['mean_coef']:.4f}, t={fm_summary['rv_rank']['t_stat']:.2f}
   - VIX Beta rank:     coef={fm_summary['vix_beta_rank']['mean_coef']:.4f}, t={fm_summary['vix_beta_rank']['t_stat']:.2f}
   - Momentum rank:     coef={fm_summary['mom_rank']['mean_coef']:.4f}, t={fm_summary['mom_rank']['t_stat']:.2f}

3. LOW-VOL ANOMALY:
   - Long-Short ann. return: {ls_mean:.2%}
   - Long-Short Sharpe: {ls_sharpe:.3f} (t={ls_t:.2f})
   - Bootstrap 95% CI: [{sharpe_ci[0]:.3f}, {sharpe_ci[1]:.3f}]
   - Win rate: {win_rate:.1%}

4. REGIME DEPENDENCE:
   - Vol ranks are {'MORE' if regime_results.get('Calm (VIX<med)', {}).get('mean_rho', 0) > regime_results.get('Crisis (VIX>75p)', {}).get('mean_rho', 0) else 'LESS'} persistent in calm markets

5. CROSS-SECTIONAL DISPERSION:
   - Mean dispersion: {cs_dispersion.mean():.4f}
   - Dispersion predicts next-month vol: r={corr_disp_vol:.4f}

LIMITATIONS:
- Small cross-section (8 assets) limits statistical power
- BTC available only from ~2015 (shorter for some analyses)
- Monthly rebalance ignores intra-month dynamics
- No transaction costs in L-S portfolio
- Survivorship bias: only liquid, well-known assets included
""")

# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    'experiment': 'K404',
    'title': 'Cross-Sectional Volatility Factors',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': f'{ret_df.index[0].date()} to {ret_df.index[-1].date()}',
    'n_assets': N_ASSETS,
    'assets': active_assets,
    'n_months': len(monthly_df),
    'n_trading_days': len(ret_df),
    'rank_persistence': {
        'mean_spearman_rho': float(mean_rho),
        'median_rho': float(median_rho),
        'std_rho': float(std_rho),
        't_stat': float(t_stat_rho),
        'p_value': float(p_val_rho),
        'pct_significant_months': float(pct_significant),
        'bootstrap_ci_95': [float(rho_ci[0]), float(rho_ci[1])],
        'transition_matrix_diagonal': float(diag_mean)
    },
    'fama_macbeth': fm_summary,
    'low_vol_anomaly': {
        'long_short_ann_return': float(ls_mean),
        'long_short_ann_vol': float(ls_std),
        'long_short_sharpe': float(ls_sharpe),
        'long_short_t_stat': float(ls_t),
        'long_leg_sharpe': float(long_sharpe),
        'short_leg_sharpe': float(short_sharpe),
        'win_rate': float(win_rate),
        'max_drawdown': float(mdd_ls),
        'bootstrap_sharpe_ci_95': [float(sharpe_ci[0]), float(sharpe_ci[1])]
    },
    'regime_dependence': regime_results,
    'asset_rank_stats': asset_rank_stats,
    'cross_sectional_dispersion': {
        'mean_dispersion': float(cs_dispersion.mean()),
        'dispersion_predicts_vol': {
            'correlation': float(corr_disp_vol),
            'p_value': float(p_disp_vol)
        }
    }
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a3597046/experiments/k404_cross_section_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to: {output_path}")
print("DONE.")
