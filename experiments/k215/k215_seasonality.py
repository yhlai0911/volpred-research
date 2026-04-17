"""
K215: Day-of-Week and Month-of-Year Volatility Seasonality — Robust Cross-Asset Test

Background: K35 tested VT seasonality for SPY only (ANOVA p=0.69, null).
This experiment extends to SPY, QQQ, GLD, TLT, BTC-USD with comprehensive
seasonal decomposition and cross-asset comparison.

Tests:
1. Day-of-week vol effect (ANOVA) — BTC includes weekends
2. Month-of-year vol effect (ANOVA)
3. Turn-of-month effect (t-test)
4. Partial correlation controlling for VIX
5. Cross-asset pattern comparison

Statistical: Bonferroni correction for multiple comparisons, Harvey threshold.
Data: yfinance full history, OOS = 2023-2024.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD']
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
IS_START = '2005-01-01'  # full history for IS
ALPHA = 0.05
# Number of independent tests per asset: 3 (DOW, MOY, TOM) = 3
# Total tests: 5 assets * 3 tests = 15
N_TESTS = 15
BONFERRONI_ALPHA = ALPHA / N_TESTS
HARVEY_T = 3.0  # Harvey et al. (2016) threshold

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

print("=" * 80)
print("K215: Volatility Seasonality — Robust Cross-Asset Test")
print("=" * 80)

# ── 1. Download Data ──────────────────────────────────────────────
print("\n[1] Downloading data...")
data = {}
for asset in ASSETS:
    start = '2010-01-01' if asset == 'BTC-USD' else IS_START
    df = yf.download(asset, start=start, end='2025-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df['Return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['AbsReturn'] = df['Return'].abs()
    df['SqReturn'] = df['Return'] ** 2
    df = df.dropna(subset=['Return'])
    data[asset] = df
    print(f"  {asset}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Download VIX for partial correlation analysis
vix = yf.download('^VIX', start=IS_START, end='2025-01-01', progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix = vix[['Close']].rename(columns={'Close': 'VIX'})
print(f"  VIX: {len(vix)} obs")

# ── Helper Functions ──────────────────────────────────────────────
def anova_test(groups):
    """Run one-way ANOVA on list of arrays. Returns F, p, effect_size (eta^2)."""
    groups = [g for g in groups if len(g) >= 5]
    if len(groups) < 2:
        return np.nan, np.nan, np.nan
    F, p = stats.f_oneway(*groups)
    # Compute eta-squared
    all_data = np.concatenate(groups)
    grand_mean = np.mean(all_data)
    ss_between = sum(len(g) * (np.mean(g) - grand_mean)**2 for g in groups)
    ss_total = np.sum((all_data - grand_mean)**2)
    eta_sq = ss_between / ss_total if ss_total > 0 else 0
    return F, p, eta_sq

def kruskal_test(groups):
    """Non-parametric alternative to ANOVA."""
    groups = [g for g in groups if len(g) >= 5]
    if len(groups) < 2:
        return np.nan, np.nan
    H, p = stats.kruskal(*groups)
    return H, p

def partial_corr(x, y, z):
    """Partial correlation between x and y, controlling for z."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 10:
        return np.nan, np.nan
    # Regress x on z, y on z, correlate residuals
    slope_xz = np.polyfit(z, x, 1)
    slope_yz = np.polyfit(z, y, 1)
    res_x = x - np.polyval(slope_xz, z)
    res_y = y - np.polyval(slope_yz, z)
    r, p = stats.pearsonr(res_x, res_y)
    return r, p

def t_stat_from_mean(data_arr):
    """t-statistic for mean != 0."""
    n = len(data_arr)
    if n < 3:
        return np.nan
    return np.mean(data_arr) / (np.std(data_arr, ddof=1) / np.sqrt(n))

results = {}

# ── 2. Day-of-Week Analysis ──────────────────────────────────────
print("\n" + "=" * 80)
print("[2] DAY-OF-WEEK VOLATILITY EFFECT")
print("=" * 80)

dow_results = {}
for asset in ASSETS:
    df = data[asset].copy()
    df['DOW'] = df.index.dayofweek  # 0=Mon, 6=Sun

    is_btc = (asset == 'BTC-USD')
    max_dow = 7 if is_btc else 5  # BTC trades 7 days

    # Full sample
    groups_full = [df[df['DOW'] == d]['AbsReturn'].values for d in range(max_dow)]
    F_full, p_full, eta_full = anova_test(groups_full)
    H_full, pk_full = kruskal_test(groups_full)

    # IS period
    df_is = df[df.index < OOS_START]
    groups_is = [df_is[df_is['DOW'] == d]['AbsReturn'].values for d in range(max_dow)]
    F_is, p_is, eta_is = anova_test(groups_is)

    # OOS period
    df_oos = df[(df.index >= OOS_START) & (df.index <= OOS_END)]
    groups_oos = [df_oos[df_oos['DOW'] == d]['AbsReturn'].values for d in range(max_dow)]
    F_oos, p_oos, eta_oos = anova_test(groups_oos)

    # Mean vol by day
    day_means_full = {DAY_NAMES[d]: np.mean(groups_full[d]) * 100 for d in range(max_dow) if len(groups_full[d]) > 0}
    day_means_is = {DAY_NAMES[d]: np.mean(groups_is[d]) * 100 if d < len(groups_is) and len(groups_is[d]) > 0 else np.nan for d in range(max_dow)}
    day_means_oos = {DAY_NAMES[d]: np.mean(groups_oos[d]) * 100 if d < len(groups_oos) and len(groups_oos[d]) > 0 else np.nan for d in range(max_dow)}

    highest_day = max(day_means_full, key=day_means_full.get)
    lowest_day = min(day_means_full, key=day_means_full.get)
    spread = day_means_full[highest_day] / day_means_full[lowest_day] - 1

    dow_results[asset] = {
        'F_full': F_full, 'p_full': p_full, 'eta_full': eta_full,
        'H_full': H_full, 'pk_full': pk_full,
        'F_is': F_is, 'p_is': p_is, 'eta_is': eta_is,
        'F_oos': F_oos, 'p_oos': p_oos, 'eta_oos': eta_oos,
        'day_means_full': day_means_full,
        'day_means_is': day_means_is,
        'day_means_oos': day_means_oos,
        'highest_day': highest_day,
        'lowest_day': lowest_day,
        'spread_pct': spread * 100,
        'sig_bonferroni': p_full < BONFERRONI_ALPHA,
        'n_obs': len(df),
    }

    sig_marker = "***" if p_full < BONFERRONI_ALPHA else ("**" if p_full < 0.01 else ("*" if p_full < 0.05 else ""))
    print(f"\n  {asset}:")
    print(f"    Full sample: F={F_full:.3f}, p={p_full:.4f} {sig_marker}, eta²={eta_full:.6f}")
    print(f"    Kruskal-Wallis: H={H_full:.3f}, p={pk_full:.4f}")
    print(f"    IS:  F={F_is:.3f}, p={p_is:.4f}, eta²={eta_is:.6f}")
    print(f"    OOS: F={F_oos:.3f}, p={p_oos:.4f}, eta²={eta_oos:.6f}")
    print(f"    Highest vol day: {highest_day} ({day_means_full[highest_day]:.4f}%)")
    print(f"    Lowest vol day:  {lowest_day} ({day_means_full[lowest_day]:.4f}%)")
    print(f"    Hi/Lo spread: {spread*100:.1f}%")
    print(f"    Day means (full, %):", {k: f"{v:.4f}" for k, v in day_means_full.items()})

results['day_of_week'] = dow_results

# ── 3. Month-of-Year Analysis ────────────────────────────────────
print("\n" + "=" * 80)
print("[3] MONTH-OF-YEAR VOLATILITY EFFECT")
print("=" * 80)

moy_results = {}
for asset in ASSETS:
    df = data[asset].copy()
    df['Month'] = df.index.month  # 1-12

    # Full sample
    groups_full = [df[df['Month'] == m]['AbsReturn'].values for m in range(1, 13)]
    F_full, p_full, eta_full = anova_test(groups_full)
    H_full, pk_full = kruskal_test(groups_full)

    # IS
    df_is = df[df.index < OOS_START]
    groups_is = [df_is[df_is['Month'] == m]['AbsReturn'].values for m in range(1, 13)]
    F_is, p_is, eta_is = anova_test(groups_is)

    # OOS
    df_oos = df[(df.index >= OOS_START) & (df.index <= OOS_END)]
    groups_oos = [df_oos[df_oos['Month'] == m]['AbsReturn'].values for m in range(1, 13)]
    F_oos, p_oos, eta_oos = anova_test(groups_oos)

    # Monthly means
    month_means_full = {MONTH_NAMES[m-1]: np.mean(groups_full[m-1]) * 100 for m in range(1, 13) if len(groups_full[m-1]) > 0}
    month_means_is = {MONTH_NAMES[m-1]: np.mean(groups_is[m-1]) * 100 if len(groups_is[m-1]) > 0 else np.nan for m in range(1, 13)}

    highest_month = max(month_means_full, key=month_means_full.get)
    lowest_month = min(month_means_full, key=month_means_full.get)
    spread = month_means_full[highest_month] / month_means_full[lowest_month] - 1

    # "Sell in May" test: May-Oct vs Nov-Apr volatility
    summer = df[df['Month'].isin([5, 6, 7, 8, 9, 10])]['AbsReturn'].values
    winter = df[df['Month'].isin([11, 12, 1, 2, 3, 4])]['AbsReturn'].values
    t_sell_may, p_sell_may = stats.ttest_ind(summer, winter, equal_var=False)
    summer_mean = np.mean(summer) * 100
    winter_mean = np.mean(winter) * 100

    moy_results[asset] = {
        'F_full': F_full, 'p_full': p_full, 'eta_full': eta_full,
        'H_full': H_full, 'pk_full': pk_full,
        'F_is': F_is, 'p_is': p_is, 'eta_is': eta_is,
        'F_oos': F_oos, 'p_oos': p_oos, 'eta_oos': eta_oos,
        'month_means_full': month_means_full,
        'highest_month': highest_month,
        'lowest_month': lowest_month,
        'spread_pct': spread * 100,
        'sell_may_t': t_sell_may,
        'sell_may_p': p_sell_may,
        'summer_vol': summer_mean,
        'winter_vol': winter_mean,
        'sig_bonferroni': p_full < BONFERRONI_ALPHA,
    }

    sig_marker = "***" if p_full < BONFERRONI_ALPHA else ("**" if p_full < 0.01 else ("*" if p_full < 0.05 else ""))
    print(f"\n  {asset}:")
    print(f"    Full sample: F={F_full:.3f}, p={p_full:.4f} {sig_marker}, eta²={eta_full:.6f}")
    print(f"    Kruskal-Wallis: H={H_full:.3f}, p={pk_full:.4f}")
    print(f"    IS:  F={F_is:.3f}, p={p_is:.4f}")
    print(f"    OOS: F={F_oos:.3f}, p={p_oos:.4f}")
    print(f"    Highest vol: {highest_month} ({month_means_full[highest_month]:.4f}%)")
    print(f"    Lowest vol:  {lowest_month} ({month_means_full[lowest_month]:.4f}%)")
    print(f"    Hi/Lo spread: {spread*100:.1f}%")
    print(f"    'Sell in May' vol: Summer={summer_mean:.4f}% vs Winter={winter_mean:.4f}%, t={t_sell_may:.3f}, p={p_sell_may:.4f}")

results['month_of_year'] = moy_results

# ── 4. Turn-of-Month Analysis ────────────────────────────────────
print("\n" + "=" * 80)
print("[4] TURN-OF-MONTH EFFECT")
print("=" * 80)

tom_results = {}
for asset in ASSETS:
    df = data[asset].copy()

    # Identify turn-of-month: last 3 + first 3 trading days
    df['Day'] = df.index.day
    df['Month'] = df.index.month
    df['Year'] = df.index.year

    # For each month, find trading days and label TOM vs MID
    tom_flags = []
    for (y, m), grp in df.groupby(['Year', 'Month']):
        n_days = len(grp)
        if n_days < 10:  # skip very short months
            tom_flags.extend([np.nan] * n_days)
            continue
        flags = [0] * n_days
        # First 3 trading days
        for i in range(min(3, n_days)):
            flags[i] = 1
        # Last 3 trading days
        for i in range(max(0, n_days - 3), n_days):
            flags[i] = 1
        tom_flags.extend(flags)

    df['TOM'] = tom_flags
    df_valid = df.dropna(subset=['TOM'])

    tom_vol = df_valid[df_valid['TOM'] == 1]['AbsReturn'].values
    mid_vol = df_valid[df_valid['TOM'] == 0]['AbsReturn'].values

    t_stat, p_val = stats.ttest_ind(tom_vol, mid_vol, equal_var=False)
    # Mann-Whitney U (non-parametric)
    U, p_mw = stats.mannwhitneyu(tom_vol, mid_vol, alternative='two-sided')

    tom_mean = np.mean(tom_vol) * 100
    mid_mean = np.mean(mid_vol) * 100
    diff_pct = (tom_mean / mid_mean - 1) * 100

    # IS/OOS split
    df_is = df_valid[df_valid.index < OOS_START]
    tom_is = df_is[df_is['TOM'] == 1]['AbsReturn'].values
    mid_is = df_is[df_is['TOM'] == 0]['AbsReturn'].values
    t_is, p_is = stats.ttest_ind(tom_is, mid_is, equal_var=False) if len(tom_is) > 5 and len(mid_is) > 5 else (np.nan, np.nan)

    df_oos = df_valid[(df_valid.index >= OOS_START) & (df_valid.index <= OOS_END)]
    tom_oos = df_oos[df_oos['TOM'] == 1]['AbsReturn'].values
    mid_oos = df_oos[df_oos['TOM'] == 0]['AbsReturn'].values
    t_oos, p_oos = stats.ttest_ind(tom_oos, mid_oos, equal_var=False) if len(tom_oos) > 5 and len(mid_oos) > 5 else (np.nan, np.nan)

    tom_results[asset] = {
        't_stat': t_stat, 'p_val': p_val,
        'U_stat': float(U), 'p_mw': p_mw,
        't_is': t_is, 'p_is': p_is,
        't_oos': t_oos, 'p_oos': p_oos,
        'tom_vol': tom_mean, 'mid_vol': mid_mean,
        'diff_pct': diff_pct,
        'n_tom': len(tom_vol), 'n_mid': len(mid_vol),
        'sig_bonferroni': p_val < BONFERRONI_ALPHA,
    }

    sig_marker = "***" if p_val < BONFERRONI_ALPHA else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    print(f"\n  {asset}:")
    print(f"    TOM vol: {tom_mean:.4f}% ({len(tom_vol)} days)")
    print(f"    MID vol: {mid_mean:.4f}% ({len(mid_vol)} days)")
    print(f"    Diff: {diff_pct:+.1f}%")
    print(f"    t={t_stat:.3f}, p={p_val:.4f} {sig_marker}")
    print(f"    Mann-Whitney U: p={p_mw:.4f}")
    print(f"    IS:  t={t_is:.3f}, p={p_is:.4f}" if not np.isnan(t_is) else "    IS:  N/A")
    print(f"    OOS: t={t_oos:.3f}, p={p_oos:.4f}" if not np.isnan(t_oos) else "    OOS: N/A")

results['turn_of_month'] = tom_results

# ── 5. Partial Correlation with VIX ──────────────────────────────
print("\n" + "=" * 80)
print("[5] PARTIAL CORRELATION: SEASONALITY CONTROLLING FOR VIX")
print("=" * 80)

partial_results = {}
for asset in ASSETS:
    df = data[asset].copy()
    df = df.join(vix, how='inner')
    df = df.dropna(subset=['VIX', 'AbsReturn'])

    if len(df) < 50:
        print(f"  {asset}: insufficient overlapping data with VIX")
        partial_results[asset] = {'note': 'insufficient data'}
        continue

    df['DOW'] = df.index.dayofweek
    df['Month'] = df.index.month

    # Create seasonal dummy variables
    # DOW: use Monday as reference
    for d in range(1, 5):
        df[f'DOW_{d}'] = (df['DOW'] == d).astype(int)
    # Month: use January as reference
    for m in range(2, 13):
        df[f'Month_{m}'] = (df['Month'] == m).astype(int)

    # DOW partial correlation: correlation of AbsReturn with DOW dummies, controlling for VIX
    # Use DOW as a numerical variable (0-4) for simple partial corr
    r_dow_raw, p_dow_raw = stats.pearsonr(df['DOW'].values, df['AbsReturn'].values)
    r_dow_partial, p_dow_partial = partial_corr(df['DOW'].values, df['AbsReturn'].values, df['VIX'].values)

    # Month partial correlation
    r_month_raw, p_month_raw = stats.pearsonr(df['Month'].values, df['AbsReturn'].values)
    r_month_partial, p_month_partial = partial_corr(df['Month'].values, df['AbsReturn'].values, df['VIX'].values)

    # More informative: regress AbsReturn on VIX + DOW dummies, check joint F for DOW
    from numpy.linalg import lstsq

    # Regression: AbsReturn ~ VIX + DOW_dummies
    X_vix = np.column_stack([np.ones(len(df)), df['VIX'].values])
    X_full = np.column_stack([X_vix] + [df[f'DOW_{d}'].values for d in range(1, 5)])
    y = df['AbsReturn'].values

    # Restricted model (VIX only)
    beta_r, res_r, _, _ = lstsq(X_vix, y, rcond=None)
    ss_r = np.sum((y - X_vix @ beta_r)**2)

    # Full model (VIX + DOW)
    beta_f, res_f, _, _ = lstsq(X_full, y, rcond=None)
    ss_f = np.sum((y - X_full @ beta_f)**2)

    n = len(y)
    k_r = X_vix.shape[1]
    k_f = X_full.shape[1]

    F_dow_given_vix = ((ss_r - ss_f) / (k_f - k_r)) / (ss_f / (n - k_f))
    p_dow_given_vix = 1 - stats.f.cdf(F_dow_given_vix, k_f - k_r, n - k_f)

    # Same for Month dummies
    X_full_m = np.column_stack([X_vix] + [df[f'Month_{m}'].values for m in range(2, 13)])
    beta_fm, _, _, _ = lstsq(X_full_m, y, rcond=None)
    ss_fm = np.sum((y - X_full_m @ beta_fm)**2)
    k_fm = X_full_m.shape[1]

    F_month_given_vix = ((ss_r - ss_fm) / (k_fm - k_r)) / (ss_fm / (n - k_fm))
    p_month_given_vix = 1 - stats.f.cdf(F_month_given_vix, k_fm - k_r, n - k_fm)

    partial_results[asset] = {
        'r_dow_raw': r_dow_raw, 'p_dow_raw': p_dow_raw,
        'r_dow_partial': r_dow_partial, 'p_dow_partial': p_dow_partial,
        'F_dow_given_vix': F_dow_given_vix, 'p_dow_given_vix': p_dow_given_vix,
        'r_month_raw': r_month_raw, 'p_month_raw': p_month_raw,
        'r_month_partial': r_month_partial, 'p_month_partial': p_month_partial,
        'F_month_given_vix': F_month_given_vix, 'p_month_given_vix': p_month_given_vix,
    }

    print(f"\n  {asset} (n={n}):")
    print(f"    DOW effect | VIX:")
    print(f"      Raw corr: r={r_dow_raw:.4f}, p={p_dow_raw:.4f}")
    print(f"      Partial:  r={r_dow_partial:.4f}, p={p_dow_partial:.4f}")
    print(f"      Joint F:  F={F_dow_given_vix:.3f}, p={p_dow_given_vix:.4f}")
    print(f"    Month effect | VIX:")
    print(f"      Raw corr: r={r_month_raw:.4f}, p={p_month_raw:.4f}")
    print(f"      Partial:  r={r_month_partial:.4f}, p={p_month_partial:.4f}")
    print(f"      Joint F:  F={F_month_given_vix:.3f}, p={p_month_given_vix:.4f}")

results['partial_vix'] = partial_results

# ── 6. Cross-Asset Pattern Comparison ─────────────────────────────
print("\n" + "=" * 80)
print("[6] CROSS-ASSET PATTERN COMPARISON")
print("=" * 80)

# Rank correlation of DOW patterns across assets
print("\n  Day-of-week vol rank correlations (equity assets only):")
equity_assets = ['SPY', 'QQQ', 'GLD', 'TLT']
dow_ranks = {}
for asset in equity_assets:
    means = dow_results[asset]['day_means_full']
    # Get Mon-Fri values
    vals = [means.get(DAY_NAMES[d], np.nan) for d in range(5)]
    dow_ranks[asset] = stats.rankdata(vals)

cross_dow_corr = {}
for i, a1 in enumerate(equity_assets):
    for a2 in equity_assets[i+1:]:
        rho, p = stats.spearmanr(dow_ranks[a1], dow_ranks[a2])
        cross_dow_corr[f"{a1}-{a2}"] = {'rho': rho, 'p': p}
        print(f"    {a1} vs {a2}: rho={rho:.3f}, p={p:.3f}")

# Month-of-year rank correlations
print("\n  Month-of-year vol rank correlations:")
moy_ranks = {}
for asset in ASSETS:
    if asset == 'BTC-USD':
        # BTC may have fewer months of data
        means = moy_results[asset]['month_means_full']
    else:
        means = moy_results[asset]['month_means_full']
    vals = [means.get(MONTH_NAMES[m], np.nan) for m in range(12)]
    moy_ranks[asset] = stats.rankdata(vals)

cross_moy_corr = {}
for i, a1 in enumerate(ASSETS):
    for a2 in ASSETS[i+1:]:
        rho, p = stats.spearmanr(moy_ranks[a1], moy_ranks[a2])
        cross_moy_corr[f"{a1}-{a2}"] = {'rho': rho, 'p': p}
        print(f"    {a1} vs {a2}: rho={rho:.3f}, p={p:.3f}")

results['cross_asset'] = {
    'dow_rank_corr': cross_dow_corr,
    'moy_rank_corr': cross_moy_corr,
}

# ── 7. OOS Stability Check ───────────────────────────────────────
print("\n" + "=" * 80)
print("[7] OOS STABILITY: IS vs OOS PATTERN CONSISTENCY")
print("=" * 80)

stability_results = {}
for asset in ASSETS:
    is_btc = (asset == 'BTC-USD')
    max_dow = 7 if is_btc else 5

    # DOW pattern stability
    is_dow = dow_results[asset]['day_means_is']
    oos_dow = dow_results[asset]['day_means_oos']

    is_vals = [is_dow.get(DAY_NAMES[d], np.nan) for d in range(max_dow)]
    oos_vals = [oos_dow.get(DAY_NAMES[d], np.nan) for d in range(max_dow)]

    # Remove NaN pairs
    valid = [(iv, ov) for iv, ov in zip(is_vals, oos_vals) if not (np.isnan(iv) or np.isnan(ov))]
    if len(valid) >= 3:
        is_v, oos_v = zip(*valid)
        rho_dow, p_dow = stats.spearmanr(is_v, oos_v)
    else:
        rho_dow, p_dow = np.nan, np.nan

    # MOY pattern stability
    is_moy_means = moy_results[asset].get('month_means_full', {})  # We need IS-specific
    # Recompute IS and OOS month means
    df = data[asset].copy()
    df['Month'] = df.index.month
    df_is = df[df.index < OOS_START]
    df_oos = df[(df.index >= OOS_START) & (df.index <= OOS_END)]

    is_mvals = [df_is[df_is['Month'] == m]['AbsReturn'].mean() * 100 for m in range(1, 13)]
    oos_mvals = [df_oos[df_oos['Month'] == m]['AbsReturn'].mean() * 100 for m in range(1, 13)]

    valid_m = [(iv, ov) for iv, ov in zip(is_mvals, oos_mvals) if not (np.isnan(iv) or np.isnan(ov))]
    if len(valid_m) >= 3:
        is_mv, oos_mv = zip(*valid_m)
        rho_moy, p_moy = stats.spearmanr(is_mv, oos_mv)
    else:
        rho_moy, p_moy = np.nan, np.nan

    stability_results[asset] = {
        'dow_rho_is_oos': rho_dow, 'dow_p_is_oos': p_dow,
        'moy_rho_is_oos': rho_moy, 'moy_p_is_oos': p_moy,
    }

    print(f"\n  {asset}:")
    print(f"    DOW pattern IS→OOS: rho={rho_dow:.3f}, p={p_dow:.3f}" if not np.isnan(rho_dow) else f"    DOW pattern: insufficient data")
    print(f"    MOY pattern IS→OOS: rho={rho_moy:.3f}, p={p_moy:.3f}" if not np.isnan(rho_moy) else f"    MOY pattern: insufficient data")

results['stability'] = stability_results

# ── 8. Summary & Trading Implications ────────────────────────────
print("\n" + "=" * 80)
print("[8] SUMMARY TABLE")
print("=" * 80)

print(f"\n  Bonferroni-corrected alpha = {BONFERRONI_ALPHA:.4f} (N_tests={N_TESTS})")
print(f"  Harvey |t| threshold = {HARVEY_T}")

print(f"\n  {'Asset':<10} {'DOW p':>10} {'MOY p':>10} {'TOM p':>10} {'DOW sig':>10} {'MOY sig':>10} {'TOM sig':>10}")
print("  " + "-" * 70)
for asset in ASSETS:
    dow_p = dow_results[asset]['p_full']
    moy_p = moy_results[asset]['p_full']
    tom_p = tom_results[asset]['p_val']

    dow_sig = "YES" if dow_p < BONFERRONI_ALPHA else "no"
    moy_sig = "YES" if moy_p < BONFERRONI_ALPHA else "no"
    tom_sig = "YES" if tom_p < BONFERRONI_ALPHA else "no"

    print(f"  {asset:<10} {dow_p:>10.4f} {moy_p:>10.4f} {tom_p:>10.4f} {dow_sig:>10} {moy_sig:>10} {tom_sig:>10}")

print(f"\n  Effect sizes (eta² for DOW/MOY):")
print(f"  {'Asset':<10} {'DOW eta²':>12} {'MOY eta²':>12} {'TOM diff%':>12}")
print("  " + "-" * 50)
for asset in ASSETS:
    eta_dow = dow_results[asset]['eta_full']
    eta_moy = moy_results[asset]['eta_full']
    tom_diff = tom_results[asset]['diff_pct']
    print(f"  {asset:<10} {eta_dow:>12.6f} {eta_moy:>12.6f} {tom_diff:>+12.1f}%")

# ── 9. VT Overlay Evaluation (if any seasonal pattern survives) ──
print("\n" + "=" * 80)
print("[9] SEASONAL VT OVERLAY BACKTEST (OOS 2023-2024)")
print("=" * 80)

# For each asset with any significant pattern, build a simple seasonal overlay
overlay_results = {}
for asset in ASSETS:
    df = data[asset].copy()
    df_is = df[df.index < OOS_START].copy()
    df_oos = df[(df.index >= OOS_START) & (df.index <= OOS_END)].copy()

    if len(df_oos) < 50:
        print(f"  {asset}: insufficient OOS data")
        continue

    # Strategy: use IS seasonal pattern to adjust weights in OOS
    # Compute IS mean vol by DOW and Month
    df_is['DOW'] = df_is.index.dayofweek
    df_is['Month'] = df_is.index.month

    is_dow_vol = df_is.groupby('DOW')['AbsReturn'].mean()
    is_month_vol = df_is.groupby('Month')['AbsReturn'].mean()

    # Seasonal adjustment: scale weight inversely proportional to expected vol
    # High vol day → lower weight, low vol day → higher weight
    # Normalize so mean weight = 1
    dow_weights = (1.0 / is_dow_vol)
    dow_weights = dow_weights / dow_weights.mean()  # normalize

    month_weights = (1.0 / is_month_vol)
    month_weights = month_weights / month_weights.mean()

    # Apply to OOS
    df_oos = df_oos.copy()
    df_oos['DOW'] = df_oos.index.dayofweek
    df_oos['Month'] = df_oos.index.month

    df_oos['DOW_weight'] = df_oos['DOW'].map(dow_weights)
    df_oos['Month_weight'] = df_oos['Month'].map(month_weights)
    df_oos['Combined_weight'] = df_oos['DOW_weight'] * df_oos['Month_weight']
    # Renormalize
    df_oos['Combined_weight'] = df_oos['Combined_weight'] / df_oos['Combined_weight'].mean()

    # Performance: unweighted vs weighted returns
    unweighted_ret = df_oos['Return'].values
    weighted_ret = df_oos['Return'].values * df_oos['Combined_weight'].values

    # Compare risk-adjusted metrics
    def sharpe(returns, ann=252):
        if np.std(returns) == 0:
            return 0
        return np.mean(returns) / np.std(returns) * np.sqrt(ann)

    def max_dd(returns):
        cum = np.cumsum(returns)
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        return np.min(dd)

    sr_unw = sharpe(unweighted_ret)
    sr_w = sharpe(weighted_ret)
    mdd_unw = max_dd(unweighted_ret)
    mdd_w = max_dd(weighted_ret)
    vol_unw = np.std(unweighted_ret) * np.sqrt(252) * 100
    vol_w = np.std(weighted_ret) * np.sqrt(252) * 100

    overlay_results[asset] = {
        'sharpe_unweighted': sr_unw,
        'sharpe_weighted': sr_w,
        'sharpe_diff': sr_w - sr_unw,
        'mdd_unweighted': mdd_unw * 100,
        'mdd_weighted': mdd_w * 100,
        'vol_unweighted': vol_unw,
        'vol_weighted': vol_w,
    }

    print(f"\n  {asset} OOS:")
    print(f"    Unweighted: Sharpe={sr_unw:.3f}, Vol={vol_unw:.1f}%, MDD={mdd_unw*100:.1f}%")
    print(f"    Seasonal:   Sharpe={sr_w:.3f}, Vol={vol_w:.1f}%, MDD={mdd_w*100:.1f}%")
    print(f"    Delta:      Sharpe={sr_w-sr_unw:+.3f}")

results['overlay'] = overlay_results

# ── 10. Conclusions ───────────────────────────────────────────────
print("\n" + "=" * 80)
print("[10] CONCLUSIONS")
print("=" * 80)

n_sig_bonf = sum(1 for a in ASSETS for test in ['day_of_week', 'month_of_year', 'turn_of_month']
                 for key in ['sig_bonferroni'] if results.get(
                     {'day_of_week': 'day_of_week', 'month_of_year': 'month_of_year', 'turn_of_month': 'turn_of_month'}[test], {}
                 ).get(a, {}).get(key, False))

# Actually count properly
sig_count = 0
for asset in ASSETS:
    if dow_results[asset]['sig_bonferroni']:
        sig_count += 1
    if moy_results[asset]['sig_bonferroni']:
        sig_count += 1
    if tom_results[asset]['sig_bonferroni']:
        sig_count += 1

print(f"\n  Tests significant after Bonferroni: {sig_count} / {N_TESTS}")

# Any nominally significant?
nom_sig = 0
for asset in ASSETS:
    if dow_results[asset]['p_full'] < 0.05:
        nom_sig += 1
        print(f"    * {asset} DOW: p={dow_results[asset]['p_full']:.4f} (nominal)")
    if moy_results[asset]['p_full'] < 0.05:
        nom_sig += 1
        print(f"    * {asset} MOY: p={moy_results[asset]['p_full']:.4f} (nominal)")
    if tom_results[asset]['p_val'] < 0.05:
        nom_sig += 1
        print(f"    * {asset} TOM: p={tom_results[asset]['p_val']:.4f} (nominal)")

print(f"\n  Nominally significant (p<0.05): {nom_sig} / {N_TESTS}")

# Overall assessment
all_eta_dow = [dow_results[a]['eta_full'] for a in ASSETS]
all_eta_moy = [moy_results[a]['eta_full'] for a in ASSETS]
print(f"\n  Average effect sizes:")
print(f"    DOW eta²: {np.mean(all_eta_dow):.6f} (max: {np.max(all_eta_dow):.6f})")
print(f"    MOY eta²: {np.mean(all_eta_moy):.6f} (max: {np.max(all_eta_moy):.6f})")

# Overlay improvement
if overlay_results:
    sr_diffs = [overlay_results[a]['sharpe_diff'] for a in overlay_results]
    print(f"\n  Seasonal overlay Sharpe changes: {[f'{d:+.3f}' for d in sr_diffs]}")
    print(f"    Mean change: {np.mean(sr_diffs):+.3f}")

print(f"\n  VERDICT: ", end="")
if sig_count == 0 and nom_sig <= 2:
    print("NO robust seasonality in volatility across assets.")
    print("  Calendar effects in vol are NOT a viable standalone signal.")
    print("  Consistent with K35 (SPY DOW ANOVA p=0.69).")
elif sig_count > 0:
    print(f"{sig_count} Bonferroni-significant patterns found — warrants further study.")
else:
    print(f"Weak seasonality ({nom_sig} nominal, 0 Bonferroni) — not tradeable.")

# ── Save Results ──────────────────────────────────────────────────
def convert_for_json(obj):
    """Convert numpy types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_for_json(x) for x in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj) if not np.isnan(obj) else None
    elif isinstance(obj, np.ndarray):
        return [convert_for_json(x) for x in obj]
    elif isinstance(obj, np.bool_):
        return bool(obj)
    return obj

output = {
    'experiment': 'K215',
    'title': 'Day-of-Week and Month-of-Year Volatility Seasonality — Robust Cross-Asset Test',
    'assets': ASSETS,
    'oos_period': f'{OOS_START} to {OOS_END}',
    'bonferroni_alpha': BONFERRONI_ALPHA,
    'n_tests': N_TESTS,
    'sig_bonferroni_count': sig_count,
    'sig_nominal_count': nom_sig,
    'results': convert_for_json(results),
}

with open('experiments/k215_seasonality_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to experiments/k215_seasonality_results.json")
print("\nK215 complete.")
