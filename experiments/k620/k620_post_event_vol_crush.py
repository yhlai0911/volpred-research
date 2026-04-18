"""
K620: Post-Event Vol Crush Trading Strategy
============================================
[提出: 用戶, 執行: Claude]

研究問題:
K617 found post-TSMC-revenue vol crush of -13% (p=0.014) — the ONLY significant
finding in the TSMC event study. K528 found NO vol crush for NFP.
Can we exploit the TSMC revenue vol crush by adjusting 0050.TW weight around events?

Hypothesis:
After TSMC monthly revenue announcement (~10th of each month), 0050.TW vol drops.
If we INCREASE 0050 weight slightly after the announcement (lower vol = safer to hold more),
we capture the post-event calm period.

Strategies:
a. Post-Revenue Boost: for 5 days after TSMC revenue, increase 0050 weight by 20%
b. Pre-Revenue Defense: for 3 days before revenue, reduce weight by 20%
c. Combined: defense before + boost after
d. Quarterly Earnings version: same logic around ~15th of Jan/Apr/Jul/Oct

Benchmark: standard 8.63/VIX
Cross-OOS: 3 periods
Harvey t>3.0 threshold

Data: yfinance (0050.TW, ^VIX), 2015-2026
References:
- K617: TSMC Event Study — post-rev vol crush -12.9% (t=-2.50, p=0.014)
- K528: NFP Event Study — no vol crush found
- Patell & Wolfson (1984) JFE — intraday earnings vol
- Savor & Wilson (2013) RFS — macro risk premium
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("K620: Post-Event Vol Crush Trading Strategy")
print("=" * 70)

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n[1] Downloading 0050.TW and ^VIX data...")
etf = yf.download('0050.TW', start='2015-01-01', end='2026-12-31', progress=False)
vix = yf.download('^VIX', start='2015-01-01', end='2026-12-31', progress=False)

# Flatten multi-index if present
if isinstance(etf.columns, pd.MultiIndex):
    etf.columns = etf.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

etf['Return'] = etf['Close'].pct_change()
etf = etf.dropna(subset=['Return'])

# Forward-fill VIX to match trading days (VIX has US holidays, 0050 has TW holidays)
vix_close = vix['Close'].rename('VIX')

print(f"  0050.TW: {etf.index[0].strftime('%Y-%m-%d')} to {etf.index[-1].strftime('%Y-%m-%d')}")
print(f"  0050.TW trading days: {len(etf)}")
print(f"  VIX data points: {len(vix)}")

# Descriptive stats
print(f"\n  0050.TW mean daily return: {etf['Return'].mean()*100:.4f}%")
print(f"  0050.TW std daily return:  {etf['Return'].std()*100:.4f}%")
print(f"  0050.TW annualized return: {etf['Return'].mean()*252*100:.2f}%")
print(f"  0050.TW annualized vol:    {etf['Return'].std()*np.sqrt(252)*100:.2f}%")

# =============================================================================
# 2. GENERATE TSMC EVENT DATES
# =============================================================================
print("\n[2] Generating TSMC event dates...")

trading_days = sorted(etf.index.normalize())
trading_days_set = set(trading_days)

def find_next_trading_day(date, td_set, max_search=10):
    """Find the next trading day on or after the given date."""
    for i in range(max_search):
        candidate = pd.Timestamp(date + timedelta(days=i))
        if candidate in td_set:
            return candidate
    return None

# Monthly revenue dates: 10th of each month
revenue_dates = []
start_year, end_year = 2015, 2026
for year in range(start_year, end_year + 1):
    for month in range(1, 13):
        target = datetime(year, month, 10)
        td = find_next_trading_day(target, trading_days_set)
        if td is not None and td in trading_days_set:
            revenue_dates.append(td)

# Quarterly earnings dates: ~15th of Jan/Apr/Jul/Oct
earnings_dates = []
for year in range(start_year, end_year + 1):
    for month in [1, 4, 7, 10]:
        target = datetime(year, month, 15)
        td = find_next_trading_day(target, trading_days_set)
        if td is not None and td in trading_days_set:
            earnings_dates.append(td)

print(f"  Monthly revenue events: {len(revenue_dates)}")
print(f"  Quarterly earnings events: {len(earnings_dates)}")
print(f"  Sample revenue dates: {[d.strftime('%Y-%m-%d') for d in revenue_dates[:5]]}")

# =============================================================================
# 3. BUILD DAILY STRATEGY SIGNALS
# =============================================================================
print("\n[3] Building daily strategy signals...")

# Create a DataFrame with daily VIX and returns
df = etf[['Close', 'Return']].copy()
df = df.join(vix_close, how='left')
df['VIX'] = df['VIX'].ffill()  # Forward-fill VIX for TW-only trading days
df = df.dropna(subset=['VIX'])

trading_days_list = list(df.index)
td_to_idx = {td: i for i, td in enumerate(trading_days_list)}

# Create event proximity indicators
df['days_to_revenue'] = np.nan  # negative = before, positive = after
df['days_to_earnings'] = np.nan
df['is_pre_revenue'] = False    # 3 days before revenue
df['is_post_revenue'] = False   # 5 days after revenue
df['is_pre_earnings'] = False   # 3 days before earnings
df['is_post_earnings'] = False  # 5 days after earnings

PRE_DAYS = 3
POST_DAYS = 5
BOOST_FACTOR = 1.20   # +20% weight
DEFENSE_FACTOR = 0.80  # -20% weight

for rev_date in revenue_dates:
    if rev_date not in td_to_idx:
        continue
    rev_idx = td_to_idx[rev_date]

    # Mark pre-revenue days (3 days before)
    for offset in range(1, PRE_DAYS + 1):
        pre_idx = rev_idx - offset
        if 0 <= pre_idx < len(trading_days_list):
            df.iloc[pre_idx, df.columns.get_loc('is_pre_revenue')] = True

    # Mark post-revenue days (5 days after, including event day)
    for offset in range(0, POST_DAYS + 1):
        post_idx = rev_idx + offset
        if 0 <= post_idx < len(trading_days_list):
            df.iloc[post_idx, df.columns.get_loc('is_post_revenue')] = True

for earn_date in earnings_dates:
    if earn_date not in td_to_idx:
        continue
    earn_idx = td_to_idx[earn_date]

    for offset in range(1, PRE_DAYS + 1):
        pre_idx = earn_idx - offset
        if 0 <= pre_idx < len(trading_days_list):
            df.iloc[pre_idx, df.columns.get_loc('is_pre_earnings')] = True

    for offset in range(0, POST_DAYS + 1):
        post_idx = earn_idx + offset
        if 0 <= post_idx < len(trading_days_list):
            df.iloc[post_idx, df.columns.get_loc('is_post_earnings')] = True

# Count affected days
n_pre_rev = df['is_pre_revenue'].sum()
n_post_rev = df['is_post_revenue'].sum()
n_pre_earn = df['is_pre_earnings'].sum()
n_post_earn = df['is_post_earnings'].sum()
n_total = len(df)

print(f"  Pre-revenue days:  {n_pre_rev} ({n_pre_rev/n_total*100:.1f}%)")
print(f"  Post-revenue days: {n_post_rev} ({n_post_rev/n_total*100:.1f}%)")
print(f"  Pre-earnings days: {n_pre_earn} ({n_pre_earn/n_total*100:.1f}%)")
print(f"  Post-earnings days:{n_post_earn} ({n_post_earn/n_total*100:.1f}%)")
print(f"  Normal days:       {n_total - n_pre_rev - n_post_rev} (excl. overlap)")

# =============================================================================
# 4. COMPUTE STRATEGY RETURNS
# =============================================================================
print("\n[4] Computing strategy returns...")

# Baseline: 8.63/VIX (capped at 1.0)
df['w_base'] = (8.63 / df['VIX']).clip(upper=1.0)

# Strategy A: Post-Revenue Boost (only boost after revenue)
df['w_post_boost'] = df['w_base'].copy()
mask_post = df['is_post_revenue']
df.loc[mask_post, 'w_post_boost'] = (df.loc[mask_post, 'w_base'] * BOOST_FACTOR).clip(upper=1.0)

# Strategy B: Pre-Revenue Defense (only reduce before revenue)
df['w_pre_defense'] = df['w_base'].copy()
mask_pre = df['is_pre_revenue']
df.loc[mask_pre, 'w_pre_defense'] = df.loc[mask_pre, 'w_base'] * DEFENSE_FACTOR

# Strategy C: Combined (defense before + boost after)
df['w_combined'] = df['w_base'].copy()
df.loc[mask_pre, 'w_combined'] = df.loc[mask_pre, 'w_base'] * DEFENSE_FACTOR
df.loc[mask_post, 'w_combined'] = (df.loc[mask_post, 'w_base'] * BOOST_FACTOR).clip(upper=1.0)

# Strategy D: Quarterly Earnings version
df['w_earnings'] = df['w_base'].copy()
mask_pre_e = df['is_pre_earnings']
mask_post_e = df['is_post_earnings']
df.loc[mask_pre_e, 'w_earnings'] = df.loc[mask_pre_e, 'w_base'] * DEFENSE_FACTOR
df.loc[mask_post_e, 'w_earnings'] = (df.loc[mask_post_e, 'w_base'] * BOOST_FACTOR).clip(upper=1.0)

# Compute portfolio returns for each strategy
# Portfolio return = w * stock_return + (1-w) * risk_free_return
# Assume risk-free = 0 for simplicity (same as existing VT strategies)
for strat in ['base', 'post_boost', 'pre_defense', 'combined', 'earnings']:
    w_col = f'w_{strat}'
    df[f'ret_{strat}'] = df[w_col].shift(1) * df['Return']  # weight is known at t-1

df = df.dropna(subset=['ret_base'])

print(f"  Total trading days with returns: {len(df)}")
print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# =============================================================================
# 5. FULL-SAMPLE PERFORMANCE
# =============================================================================
print("\n[5] Full-sample performance comparison...")

strategies = {
    'Baseline (8.63/VIX)': 'ret_base',
    'A: Post-Revenue Boost': 'ret_post_boost',
    'B: Pre-Revenue Defense': 'ret_pre_defense',
    'C: Combined': 'ret_combined',
    'D: Quarterly Earnings': 'ret_earnings',
}

results_full = {}
for name, col in strategies.items():
    rets = df[col]
    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Maximum drawdown
    cum_ret = (1 + rets).cumprod()
    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    mdd = dd.min()

    # Cumulative return
    total_ret = cum_ret.iloc[-1] - 1

    results_full[name] = {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'total_return': float(total_ret),
    }

    print(f"  {name}:")
    print(f"    Ann Return: {ann_ret*100:.2f}%, Ann Vol: {ann_vol*100:.2f}%")
    print(f"    Sharpe: {sharpe:.4f}, MDD: {mdd*100:.2f}%")
    print(f"    Total Return: {total_ret*100:.2f}%")

# =============================================================================
# 6. STATISTICAL TESTS (vs Baseline)
# =============================================================================
print("\n[6] Statistical tests (each strategy vs baseline)...")

test_results = {}
baseline_rets = df['ret_base']

for name, col in strategies.items():
    if col == 'ret_base':
        continue

    strat_rets = df[col]
    diff = strat_rets - baseline_rets

    # Paired t-test on return differences
    t_stat, p_value = stats.ttest_1samp(diff, 0)

    # Mean difference (annualized)
    mean_diff_ann = diff.mean() * 252

    # Newey-West adjusted t-stat (simple version with lag=5)
    n = len(diff)
    mean_d = diff.mean()
    resid = diff - mean_d

    # Newey-West variance with 5 lags
    nw_lags = 5
    gamma0 = (resid ** 2).sum() / n
    nw_var = gamma0
    for lag in range(1, nw_lags + 1):
        gamma_l = (resid[lag:].values * resid[:-lag].values).sum() / n
        weight = 1 - lag / (nw_lags + 1)  # Bartlett kernel
        nw_var += 2 * weight * gamma_l

    nw_se = np.sqrt(nw_var / n)
    nw_t = mean_d / nw_se if nw_se > 0 else 0
    nw_p = 2 * (1 - stats.t.cdf(abs(nw_t), n - 1))

    test_results[name] = {
        'mean_diff_daily': float(mean_d),
        'mean_diff_annual': float(mean_diff_ann),
        't_stat': float(t_stat),
        'p_value': float(p_value),
        'nw_t_stat': float(nw_t),
        'nw_p_value': float(nw_p),
        'harvey_pass': abs(nw_t) > 3.0,
        'n_obs': int(n),
    }

    harvey_flag = "PASS" if abs(nw_t) > 3.0 else "FAIL"
    print(f"  {name}:")
    print(f"    Mean daily diff: {mean_d*10000:.4f} bps")
    print(f"    Ann diff:        {mean_diff_ann*100:.4f}%")
    print(f"    t-stat:          {t_stat:.4f} (p={p_value:.4f})")
    print(f"    NW t-stat:       {nw_t:.4f} (p={nw_p:.4f})")
    print(f"    Harvey t>3:      {harvey_flag}")

# =============================================================================
# 7. CROSS-OOS VALIDATION (3 periods)
# =============================================================================
print("\n[7] Cross-OOS validation (3 periods)...")

# Define 3 OOS periods
oos_periods = [
    ('OOS1: 2015-2018', '2015-01-01', '2018-12-31'),
    ('OOS2: 2019-2022', '2019-01-01', '2022-12-31'),
    ('OOS3: 2023-2026', '2023-01-01', '2026-12-31'),
]

cross_oos_results = {}
for period_name, start, end in oos_periods:
    mask_period = (df.index >= start) & (df.index <= end)
    df_oos = df[mask_period]

    if len(df_oos) < 50:
        print(f"  {period_name}: SKIP (only {len(df_oos)} days)")
        continue

    period_results = {}
    for strat_name, col in strategies.items():
        rets = df_oos[col]
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        period_results[strat_name] = {
            'ann_return': float(ann_ret),
            'sharpe': float(sharpe),
            'n_days': int(len(rets)),
        }

    # Test best strategy (Combined) vs baseline in each period
    base_rets = df_oos['ret_base']
    comb_rets = df_oos['ret_combined']
    diff = comb_rets - base_rets

    if diff.std() > 0:
        t_stat, p_val = stats.ttest_1samp(diff, 0)
    else:
        t_stat, p_val = 0.0, 1.0

    period_results['combined_vs_base_t'] = float(t_stat)
    period_results['combined_vs_base_p'] = float(p_val)

    cross_oos_results[period_name] = period_results

    print(f"\n  {period_name} ({len(df_oos)} days):")
    for sn, sr in period_results.items():
        if isinstance(sr, dict):
            print(f"    {sn}: Sharpe={sr['sharpe']:.4f}, AnnRet={sr['ann_return']*100:.2f}%")
    print(f"    Combined vs Base: t={t_stat:.4f}, p={p_val:.4f}")

# =============================================================================
# 8. EFFECT DECOMPOSITION: Post-event vs Normal days
# =============================================================================
print("\n[8] Effect decomposition: post-event vs normal day returns...")

# Compare 0050 returns on post-revenue days vs normal days
post_rev_rets = df.loc[df['is_post_revenue'], 'Return']
normal_rets = df.loc[~df['is_post_revenue'] & ~df['is_pre_revenue'], 'Return']
pre_rev_rets = df.loc[df['is_pre_revenue'], 'Return']

print(f"  Post-revenue days ({len(post_rev_rets)}):")
print(f"    Mean return:  {post_rev_rets.mean()*100:.4f}%")
print(f"    Std return:   {post_rev_rets.std()*100:.4f}%")
print(f"    Mean |return|:{post_rev_rets.abs().mean()*100:.4f}%")

print(f"  Pre-revenue days ({len(pre_rev_rets)}):")
print(f"    Mean return:  {pre_rev_rets.mean()*100:.4f}%")
print(f"    Std return:   {pre_rev_rets.std()*100:.4f}%")
print(f"    Mean |return|:{pre_rev_rets.abs().mean()*100:.4f}%")

print(f"  Normal days ({len(normal_rets)}):")
print(f"    Mean return:  {normal_rets.mean()*100:.4f}%")
print(f"    Std return:   {normal_rets.std()*100:.4f}%")
print(f"    Mean |return|:{normal_rets.abs().mean()*100:.4f}%")

# t-test: post-revenue vs normal (mean return)
t_ret, p_ret = stats.ttest_ind(post_rev_rets, normal_rets)
print(f"\n  Post-revenue vs Normal (mean return): t={t_ret:.4f}, p={p_ret:.4f}")

# t-test: post-revenue vs normal (volatility = |return|)
t_vol, p_vol = stats.ttest_ind(post_rev_rets.abs(), normal_rets.abs())
print(f"  Post-revenue vs Normal (|return|):     t={t_vol:.4f}, p={p_vol:.4f}")

# t-test: pre-revenue vs normal (volatility)
t_pre_vol, p_pre_vol = stats.ttest_ind(pre_rev_rets.abs(), normal_rets.abs())
print(f"  Pre-revenue vs Normal (|return|):      t={t_pre_vol:.4f}, p={p_pre_vol:.4f}")

decomp_results = {
    'post_revenue': {
        'n': int(len(post_rev_rets)),
        'mean_return': float(post_rev_rets.mean()),
        'std_return': float(post_rev_rets.std()),
        'mean_abs_return': float(post_rev_rets.abs().mean()),
    },
    'pre_revenue': {
        'n': int(len(pre_rev_rets)),
        'mean_return': float(pre_rev_rets.mean()),
        'std_return': float(pre_rev_rets.std()),
        'mean_abs_return': float(pre_rev_rets.abs().mean()),
    },
    'normal': {
        'n': int(len(normal_rets)),
        'mean_return': float(normal_rets.mean()),
        'std_return': float(normal_rets.std()),
        'mean_abs_return': float(normal_rets.abs().mean()),
    },
    'post_vs_normal_return_t': float(t_ret),
    'post_vs_normal_return_p': float(p_ret),
    'post_vs_normal_vol_t': float(t_vol),
    'post_vs_normal_vol_p': float(p_vol),
    'pre_vs_normal_vol_t': float(t_pre_vol),
    'pre_vs_normal_vol_p': float(p_pre_vol),
}

# =============================================================================
# 9. SENSITIVITY ANALYSIS
# =============================================================================
print("\n[9] Sensitivity analysis: different boost/defense factors...")

sensitivity_results = {}
for boost in [1.10, 1.15, 1.20, 1.25, 1.30, 1.50]:
    for defense in [0.70, 0.80, 0.90, 1.00]:
        # Combined strategy with different factors
        w = df['w_base'].copy()
        w[df['is_pre_revenue']] = (df.loc[df['is_pre_revenue'], 'w_base'] * defense)
        w[df['is_post_revenue']] = (df.loc[df['is_post_revenue'], 'w_base'] * boost).clip(upper=1.0)

        ret = w.shift(1) * df['Return']
        ret = ret.dropna()

        ann_ret = ret.mean() * 252
        ann_vol = ret.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        # Diff vs baseline
        diff = ret - df.loc[ret.index, 'ret_base']
        mean_diff = diff.mean() * 252

        key = f"boost={boost:.2f}_defense={defense:.2f}"
        sensitivity_results[key] = {
            'boost': boost,
            'defense': defense,
            'sharpe': float(sharpe),
            'ann_return': float(ann_ret),
            'ann_diff_vs_base': float(mean_diff),
        }

# Find best combo
best_key = max(sensitivity_results, key=lambda k: sensitivity_results[k]['sharpe'])
best = sensitivity_results[best_key]
print(f"  Best combination: {best_key}")
print(f"    Sharpe: {best['sharpe']:.4f}")
print(f"    Ann diff vs base: {best['ann_diff_vs_base']*100:.4f}%")

# Print sensitivity grid
print("\n  Sensitivity grid (Sharpe, boost x defense):")
print(f"  {'':>12s}", end="")
for defense in [0.70, 0.80, 0.90, 1.00]:
    print(f"  def={defense:.2f}", end="")
print()
for boost in [1.10, 1.15, 1.20, 1.25, 1.30, 1.50]:
    print(f"  boost={boost:.2f}", end="")
    for defense in [0.70, 0.80, 0.90, 1.00]:
        key = f"boost={boost:.2f}_defense={defense:.2f}"
        s = sensitivity_results[key]['sharpe']
        print(f"    {s:.4f}", end="")
    print()

# =============================================================================
# 10. BOOTSTRAP CONFIDENCE INTERVALS
# =============================================================================
print("\n[10] Bootstrap CI for Combined strategy excess return...")

diff_series = df['ret_combined'] - df['ret_base']
diff_values = diff_series.dropna().values
n_boot = 10000

np.random.seed(42)
boot_means = np.zeros(n_boot)
for i in range(n_boot):
    sample = np.random.choice(diff_values, size=len(diff_values), replace=True)
    boot_means[i] = sample.mean()

ci_lower = np.percentile(boot_means, 2.5) * 252  # annualized
ci_upper = np.percentile(boot_means, 97.5) * 252
ci_mean = boot_means.mean() * 252

print(f"  Bootstrap mean excess return: {ci_mean*100:.4f}%/yr")
print(f"  95% CI: [{ci_lower*100:.4f}%, {ci_upper*100:.4f}%]")
print(f"  Zero in CI: {'YES' if ci_lower <= 0 <= ci_upper else 'NO'}")

bootstrap_results = {
    'mean_excess_annual': float(ci_mean),
    'ci_95_lower': float(ci_lower),
    'ci_95_upper': float(ci_upper),
    'zero_in_ci': bool(ci_lower <= 0 <= ci_upper),
    'n_bootstrap': n_boot,
}

# =============================================================================
# 11. TRANSACTION COST ANALYSIS
# =============================================================================
print("\n[11] Transaction cost impact...")

# Count weight changes (strategy adjustments)
def count_weight_changes(w_series):
    """Count number of days where weight changes by more than 1%."""
    w_diff = w_series.diff().abs()
    return (w_diff > 0.01).sum()

n_changes_base = count_weight_changes(df['w_base'])
n_changes_combined = count_weight_changes(df['w_combined'])
extra_changes = n_changes_combined - n_changes_base

# With transaction costs
tx_cost_bps = 10  # 10 bps per trade (Taiwan market)
tx_per_trade = tx_cost_bps / 10000

# Weight changes for combined strategy
w_diff_combined = df['w_combined'].diff().abs().fillna(0)
w_diff_base = df['w_base'].diff().abs().fillna(0)
extra_tx = (w_diff_combined - w_diff_base) * tx_per_trade

total_extra_tx = extra_tx.sum()
annual_extra_tx = total_extra_tx / (len(df) / 252)

# Net excess return after TX costs
mean_diff_ann = (df['ret_combined'] - df['ret_base']).mean() * 252
net_excess = mean_diff_ann - annual_extra_tx

print(f"  Baseline weight changes: {n_changes_base}")
print(f"  Combined weight changes: {n_changes_combined}")
print(f"  Extra changes from strategy: {extra_changes}")
print(f"  Extra TX cost (annual): {annual_extra_tx*100:.4f}%")
print(f"  Gross excess return: {mean_diff_ann*100:.4f}%")
print(f"  Net excess (after TX): {net_excess*100:.4f}%")

tx_results = {
    'baseline_changes': int(n_changes_base),
    'combined_changes': int(n_changes_combined),
    'extra_changes': int(extra_changes),
    'tx_cost_bps': tx_cost_bps,
    'annual_extra_tx': float(annual_extra_tx),
    'gross_excess_annual': float(mean_diff_ann),
    'net_excess_annual': float(net_excess),
}

# =============================================================================
# 12. MONTHLY ALPHA ANALYSIS
# =============================================================================
print("\n[12] Monthly alpha analysis...")

# Check if the effect is concentrated in certain months
df['YearMonth'] = df.index.to_period('M')
monthly_diff = df.groupby('YearMonth').apply(
    lambda x: (x['ret_combined'] - x['ret_base']).sum()
)

pos_months = (monthly_diff > 0).sum()
neg_months = (monthly_diff <= 0).sum()
total_months = len(monthly_diff)

print(f"  Total months: {total_months}")
print(f"  Positive months: {pos_months} ({pos_months/total_months*100:.1f}%)")
print(f"  Negative months: {neg_months} ({neg_months/total_months*100:.1f}%)")
print(f"  Mean monthly alpha: {monthly_diff.mean()*100:.4f}%")
print(f"  Median monthly alpha: {monthly_diff.median()*100:.4f}%")

# Binomial test: is win rate significantly different from 50%?
from scipy.stats import binomtest
binom_p = binomtest(pos_months, total_months, 0.5).pvalue
print(f"  Binomial test (win rate vs 50%): p={binom_p:.4f}")

monthly_alpha_results = {
    'total_months': int(total_months),
    'positive_months': int(pos_months),
    'negative_months': int(neg_months),
    'win_rate': float(pos_months / total_months),
    'mean_monthly_alpha': float(monthly_diff.mean()),
    'median_monthly_alpha': float(monthly_diff.median()),
    'binomial_p': float(binom_p),
}

# =============================================================================
# 13. OVERALL VERDICT
# =============================================================================
print("\n" + "=" * 70)
print("OVERALL VERDICT")
print("=" * 70)

# Check if any strategy passes Harvey t>3
any_harvey_pass = any(v['harvey_pass'] for v in test_results.values())

# Check cross-OOS consistency
oos_sharpe_improvements = []
for period_name, period_data in cross_oos_results.items():
    if isinstance(period_data, dict):
        base_sharpe = period_data.get('Baseline (8.63/VIX)', {}).get('sharpe', 0)
        comb_sharpe = period_data.get('C: Combined', {}).get('sharpe', 0)
        if base_sharpe != 0:
            oos_sharpe_improvements.append(comb_sharpe - base_sharpe)

consistent_improvement = all(x > 0 for x in oos_sharpe_improvements) if oos_sharpe_improvements else False

if any_harvey_pass:
    verdict = "SIGNIFICANT — At least one strategy passes Harvey t>3.0"
elif net_excess > 0 and consistent_improvement:
    verdict = "MARGINAL — Positive net alpha but fails Harvey t>3.0, consistent across OOS"
elif net_excess > 0:
    verdict = "WEAK — Positive net alpha but fails Harvey t>3.0, inconsistent OOS"
else:
    verdict = "NULL — No economically meaningful improvement"

print(f"\n  Verdict: {verdict}")
print(f"  Harvey t>3 passed: {any_harvey_pass}")
print(f"  Best NW t-stat: {max(abs(v['nw_t_stat']) for v in test_results.values()):.4f}")
print(f"  Net excess (Combined, after TX): {net_excess*100:.4f}%/yr")
print(f"  OOS consistent: {consistent_improvement}")
print(f"  Bootstrap 95% CI contains zero: {bootstrap_results['zero_in_ci']}")

# Key insight about small effect
total_affected_days = n_pre_rev + n_post_rev
pct_affected = total_affected_days / n_total * 100
print(f"\n  KEY LIMITATION:")
print(f"  Only {total_affected_days}/{n_total} days ({pct_affected:.1f}%) are affected")
print(f"  12 events/year x 8 days each = ~96 days = ~38% of trading year")
print(f"  Need very large per-event alpha to show significance")

# =============================================================================
# SAVE RESULTS
# =============================================================================
print("\n[SAVE] Writing results...")

final_results = {
    'experiment_id': 'k620',
    'title': 'K620: Post-Event Vol Crush Trading Strategy',
    'proposer': '用戶',
    'executor': 'Claude',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (0050.TW, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(df)),
    'n_revenue_events': len(revenue_dates),
    'n_earnings_events': len(earnings_dates),
    'references': [
        'K617: TSMC Event Study — post-rev vol crush -12.9% (t=-2.50, p=0.014)',
        'K528: NFP Event Study — no vol crush',
        'Patell & Wolfson (1984) JFE',
        'Savor & Wilson (2013) RFS',
    ],
    'strategies': {
        'A_post_boost': 'For 5 days after TSMC revenue, increase 0050 weight by 20%',
        'B_pre_defense': 'For 3 days before TSMC revenue, reduce 0050 weight by 20%',
        'C_combined': 'Defense before (-20%) + Boost after (+20%)',
        'D_earnings': 'Same logic for quarterly earnings dates',
    },
    'full_sample_performance': results_full,
    'statistical_tests': test_results,
    'cross_oos': cross_oos_results,
    'effect_decomposition': decomp_results,
    'best_sensitivity': {best_key: best},
    'bootstrap': bootstrap_results,
    'transaction_costs': tx_results,
    'monthly_alpha': monthly_alpha_results,
    'verdict': verdict,
    'any_harvey_pass': any_harvey_pass,
    'best_nw_t': float(max(abs(v['nw_t_stat']) for v in test_results.values())),
    'key_findings': [
        f"Combined strategy ann excess: {mean_diff_ann*100:.4f}%",
        f"After TX: {net_excess*100:.4f}%",
        f"Best NW t-stat: {max(abs(v['nw_t_stat']) for v in test_results.values()):.4f}",
        f"Harvey t>3: {'PASS' if any_harvey_pass else 'FAIL'}",
        f"Only {pct_affected:.1f}% of trading days affected",
        f"Bootstrap 95% CI: [{ci_lower*100:.4f}%, {ci_upper*100:.4f}%]",
    ],
    'limitations': [
        'TSMC revenue dates are approximate (10th of month, adjusted to next trading day)',
        'VIX is US-based; VIXTWN would be more appropriate but less available',
        'Small fraction of days affected limits statistical power',
        '20% boost/defense factors are arbitrary; sensitivity tested',
        'No consideration of TSMC revenue surprise direction',
        'Forward-filled VIX may introduce lag for Taiwan trading',
    ],
}

with open('experiments/k620_post_event_vol_crush_results.json', 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print("  Saved: experiments/k620_post_event_vol_crush_results.json")
print("\n" + "=" * 70)
print(f"K620 COMPLETE — Verdict: {verdict}")
print("=" * 70)
