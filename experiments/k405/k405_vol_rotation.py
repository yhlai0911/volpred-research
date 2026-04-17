"""
K405: Can We Time Asset Class ROTATION Using Volatility?
=========================================================
Follow-up to K404 (vol ranks near-deterministic, rho=0.837).
Question: Even if vol LEVELS are persistent, do RELATIVE vol changes signal regime shifts?

Related: K404 cross-section rank persistent, K383 3-cluster, K391 market cycles.

Data: yfinance SPY, GLD, BTC-USD, CL=F, TLT daily 2015-2024.
Real data only. No simulation.

Methodology:
  1. Relative vol changes (vol_ratio = σ_A / σ_B, rolling 22d)
     - When ratio changes significantly (z-score > 2), does it predict returns?
  2. Vol regime rotation strategy: overweight declining-vol, underweight rising-vol
  3. Compare vs equal-weight and 50/50 SPY/GLD
  4. Cross-sectional vol momentum (buy declining vol)
  5. Cross-asset vol dispersion convergence → regime shift predictor

Author: [提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
import os
warnings.filterwarnings('ignore')

# ─── Configuration ───────────────────────────────────────────────────────────

ASSETS = ['SPY', 'GLD', 'BTC-USD', 'CL=F', 'TLT']
ASSET_NAMES = {'SPY': 'S&P 500', 'GLD': 'Gold', 'BTC-USD': 'Bitcoin',
               'CL=F': 'Oil (WTI)', 'TLT': 'Long Treasury'}
START = '2015-01-01'
END = '2024-12-31'
VOL_WINDOW = 22  # 1-month rolling vol
ZSCORE_THRESHOLD = 2.0
REBAL_FREQ = 22  # Monthly rebalance (trading days)
RISK_FREE = 0.04 / 252  # Daily risk-free rate (~4% annual)

print("=" * 80)
print("K405: Can We Time Asset Class ROTATION Using Volatility?")
print("=" * 80)

# ─── 1. Data Download ────────────────────────────────────────────────────────

print("\n[1] Downloading data from yfinance...")
data = {}
for asset in ASSETS:
    try:
        df = yf.download(asset, start=START, end=END, progress=False)
        if len(df) > 500:
            data[asset] = df['Close'].squeeze()
            print(f"  {asset}: {len(df)} days, {df.index[0].date()} to {df.index[-1].date()}")
        else:
            print(f"  {asset}: insufficient data ({len(df)} days), skipping")
    except Exception as e:
        print(f"  {asset}: download failed: {e}")

# Build aligned returns DataFrame
prices = pd.DataFrame(data)
prices = prices.ffill().dropna()
returns = prices.pct_change().dropna()
log_returns = np.log(prices / prices.shift(1)).dropna()

print(f"\nAligned dataset: {len(returns)} days, {returns.index[0].date()} to {returns.index[-1].date()}")
print(f"Assets available: {list(returns.columns)}")

N_ASSETS = len(returns.columns)
asset_list = list(returns.columns)

# ─── 2. Rolling Volatility & Relative Vol Changes ────────────────────────────

print("\n" + "=" * 80)
print("[2] Relative Volatility Changes Analysis")
print("=" * 80)

# Rolling realized vol (annualized)
rolling_vol = returns.rolling(VOL_WINDOW).std() * np.sqrt(252)
rolling_vol = rolling_vol.dropna()

# Vol changes (pct change of vol over 22 days)
vol_change = rolling_vol.pct_change(VOL_WINDOW).dropna()

# Vol rank (cross-sectional rank each day)
vol_rank = rolling_vol.rank(axis=1)

# Vol ratio for all pairs
print("\n--- Vol Ratio Analysis (σ_A / σ_B) ---")
pairs = []
for i in range(N_ASSETS):
    for j in range(i+1, N_ASSETS):
        a, b = asset_list[i], asset_list[j]
        pairs.append((a, b))

ratio_results = {}
print(f"\n{'Pair':<20} {'Mean Ratio':>10} {'Std':>8} {'Z>2 Events':>12} {'Fwd 22d Ret(A-B)':>18} {'t-stat':>8} {'p-val':>8}")
print("-" * 90)

for a, b in pairs:
    ratio = rolling_vol[a] / rolling_vol[b]
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()

    # Z-score of ratio changes
    ratio_change = ratio.pct_change(VOL_WINDOW).dropna()
    ratio_zscore = (ratio_change - ratio_change.mean()) / ratio_change.std()

    # Find extreme events (z > 2 or z < -2)
    extreme_up = ratio_zscore[ratio_zscore > ZSCORE_THRESHOLD]   # A vol rising vs B
    extreme_down = ratio_zscore[ratio_zscore < -ZSCORE_THRESHOLD]  # A vol falling vs B

    # Forward returns after extreme events
    fwd_ret = (returns[a] - returns[b]).rolling(REBAL_FREQ).sum().shift(-REBAL_FREQ)

    # After A vol rises relative to B (z > 2): does B outperform?
    if len(extreme_up) > 10:
        common_idx = extreme_up.index.intersection(fwd_ret.dropna().index)
        fwd_after_up = fwd_ret.loc[common_idx]
        t_up, p_up = stats.ttest_1samp(fwd_after_up.dropna(), 0)
    else:
        t_up, p_up = np.nan, np.nan
        fwd_after_up = pd.Series(dtype=float)

    n_extreme = len(extreme_up) + len(extreme_down)
    mean_fwd = fwd_after_up.mean() if len(fwd_after_up) > 0 else np.nan

    ratio_results[(a, b)] = {
        'mean_ratio': ratio.mean(),
        'std_ratio': ratio.std(),
        'n_extreme': n_extreme,
        'fwd_ret_after_up': mean_fwd,
        't_stat': t_up,
        'p_val': p_up
    }

    print(f"{a}/{b:<14} {ratio.mean():>10.3f} {ratio.std():>8.3f} {n_extreme:>12d} "
          f"{mean_fwd:>18.4f}" if not np.isnan(mean_fwd) else f"{a}/{b:<14} {ratio.mean():>10.3f} {ratio.std():>8.3f} {n_extreme:>12d} {'N/A':>18}",
          end="")
    if not np.isnan(t_up):
        print(f" {t_up:>8.3f} {p_up:>8.4f}")
    else:
        print(f" {'N/A':>8} {'N/A':>8}")

# ─── 3. Vol Regime Rotation Strategy ─────────────────────────────────────────

print("\n" + "=" * 80)
print("[3] Vol Regime Rotation Strategy")
print("=" * 80)
print("Rule: Overweight assets with DECLINING vol, underweight RISING vol")

# Align all data
common_idx = vol_change.dropna().index.intersection(returns.index)
vol_chg_aligned = vol_change.loc[common_idx]
ret_aligned = returns.loc[common_idx]

# Rebalance dates (every REBAL_FREQ days)
rebal_dates = common_idx[::REBAL_FREQ]

# Strategy 1: Vol Momentum Rotation (overweight declining vol)
def vol_rotation_strategy(ret_df, vol_chg_df, rebal_dates, method='rank'):
    """
    Overweight assets whose vol is declining, underweight rising vol.
    method='rank': rank-based weights
    method='zscore': z-score based weights
    """
    weights_history = []
    portfolio_returns = []

    current_weights = np.ones(N_ASSETS) / N_ASSETS  # Start equal weight

    for i in range(len(rebal_dates) - 1):
        rebal_date = rebal_dates[i]
        next_rebal = rebal_dates[i + 1]

        # Get vol changes at rebalance date
        vc = vol_chg_df.loc[rebal_date]

        if vc.isna().any():
            # Keep equal weight if data missing
            current_weights = np.ones(N_ASSETS) / N_ASSETS
        else:
            if method == 'rank':
                # Rank: lowest vol change (most declining) gets highest weight
                ranks = vc.rank()  # 1 = most negative change
                inv_ranks = (N_ASSETS + 1) - ranks  # Invert: 1 = most positive change
                current_weights = inv_ranks.values / inv_ranks.sum()
            elif method == 'zscore':
                # Z-score based: negative z → higher weight
                z = (vc - vc.mean()) / vc.std()
                # Softmax of negative z-scores
                exp_neg_z = np.exp(-z.values)
                current_weights = exp_neg_z / exp_neg_z.sum()

        # Apply weights for the period
        period_mask = (ret_df.index > rebal_date) & (ret_df.index <= next_rebal)
        period_ret = ret_df.loc[period_mask]

        for _, row in period_ret.iterrows():
            port_ret = (current_weights * row.values).sum()
            portfolio_returns.append(port_ret)
            weights_history.append(current_weights.copy())

    return np.array(portfolio_returns), weights_history

# Strategy 2: Equal weight benchmark
def equal_weight_strategy(ret_df, rebal_dates):
    weights = np.ones(N_ASSETS) / N_ASSETS
    portfolio_returns = []

    for i in range(len(rebal_dates) - 1):
        rebal_date = rebal_dates[i]
        next_rebal = rebal_dates[i + 1]

        period_mask = (ret_df.index > rebal_date) & (ret_df.index <= next_rebal)
        period_ret = ret_df.loc[period_mask]

        for _, row in period_ret.iterrows():
            port_ret = (weights * row.values).sum()
            portfolio_returns.append(port_ret)

    return np.array(portfolio_returns)

# Strategy 3: 50/50 SPY/GLD
def spy_gld_strategy(ret_df, rebal_dates):
    spy_idx = asset_list.index('SPY')
    gld_idx = asset_list.index('GLD')
    weights = np.zeros(N_ASSETS)
    weights[spy_idx] = 0.5
    weights[gld_idx] = 0.5

    portfolio_returns = []
    for i in range(len(rebal_dates) - 1):
        rebal_date = rebal_dates[i]
        next_rebal = rebal_dates[i + 1]

        period_mask = (ret_df.index > rebal_date) & (ret_df.index <= next_rebal)
        period_ret = ret_df.loc[period_mask]

        for _, row in period_ret.iterrows():
            port_ret = (weights * row.values).sum()
            portfolio_returns.append(port_ret)

    return np.array(portfolio_returns)

# Run strategies
print("\nRunning strategies...")
vol_rot_rank, weights_rank = vol_rotation_strategy(ret_aligned, vol_chg_aligned, rebal_dates, 'rank')
vol_rot_zscore, weights_zscore = vol_rotation_strategy(ret_aligned, vol_chg_aligned, rebal_dates, 'zscore')
ew_ret = equal_weight_strategy(ret_aligned, rebal_dates)
sg_ret = spy_gld_strategy(ret_aligned, rebal_dates)

# Ensure same length
min_len = min(len(vol_rot_rank), len(ew_ret), len(sg_ret), len(vol_rot_zscore))
vol_rot_rank = vol_rot_rank[:min_len]
vol_rot_zscore = vol_rot_zscore[:min_len]
ew_ret = ew_ret[:min_len]
sg_ret = sg_ret[:min_len]

def compute_metrics(rets, name, rf=RISK_FREE):
    """Compute strategy performance metrics."""
    ann_ret = np.mean(rets) * 252
    ann_vol = np.std(rets) * np.sqrt(252)
    sharpe = (np.mean(rets) - rf) / np.std(rets) * np.sqrt(252) if np.std(rets) > 0 else 0

    # Max drawdown
    cum = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar ratio
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino ratio
    downside = rets[rets < 0]
    downside_std = np.std(downside) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - rf * 252) / downside_std if downside_std > 0 else 0

    # Hit rate
    hit_rate = np.mean(rets > 0)

    # Skewness and kurtosis
    skew = stats.skew(rets)
    kurt = stats.kurtosis(rets)

    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'sortino': sortino,
        'hit_rate': hit_rate,
        'skewness': skew,
        'kurtosis': kurt,
        'n_days': len(rets)
    }

strategies = {
    'Vol Rotation (Rank)': vol_rot_rank,
    'Vol Rotation (Z-score)': vol_rot_zscore,
    'Equal Weight': ew_ret,
    '50/50 SPY/GLD': sg_ret
}

print(f"\n{'Strategy':<25} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>8} {'MDD':>8} "
      f"{'Calmar':>8} {'Sortino':>8} {'Hit%':>6} {'Skew':>6} {'Kurt':>6}")
print("-" * 110)

metrics_all = {}
for name, rets in strategies.items():
    m = compute_metrics(rets, name)
    metrics_all[name] = m
    print(f"{name:<25} {m['ann_return']:>8.3f} {m['ann_vol']:>8.3f} {m['sharpe']:>8.3f} "
          f"{m['mdd']:>8.3f} {m['calmar']:>8.3f} {m['sortino']:>8.3f} "
          f"{m['hit_rate']:>6.3f} {m['skewness']:>6.2f} {m['kurtosis']:>6.2f}")

# ─── 4. Statistical Tests: Vol Rotation vs Benchmarks ─────────────────────────

print("\n" + "=" * 80)
print("[4] Statistical Tests: Vol Rotation vs Benchmarks")
print("=" * 80)

# Diebold-Mariano style test: compare daily returns
def paired_return_test(ret_a, ret_b, name_a, name_b):
    """Test if strategy A significantly outperforms B."""
    diff = ret_a - ret_b
    t_stat, p_val = stats.ttest_1samp(diff, 0)
    mean_diff = diff.mean() * 252  # Annualized
    return t_stat, p_val, mean_diff

print(f"\n{'Comparison':<45} {'Ann Diff':>10} {'t-stat':>8} {'p-val':>8} {'Sig?':>6}")
print("-" * 82)

comparisons = [
    ('Vol Rotation (Rank)', 'Equal Weight'),
    ('Vol Rotation (Rank)', '50/50 SPY/GLD'),
    ('Vol Rotation (Z-score)', 'Equal Weight'),
    ('Vol Rotation (Z-score)', '50/50 SPY/GLD'),
    ('Vol Rotation (Rank)', 'Vol Rotation (Z-score)'),
]

for a_name, b_name in comparisons:
    t, p, diff = paired_return_test(strategies[a_name], strategies[b_name], a_name, b_name)
    sig = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.10 else ''))
    print(f"{a_name} vs {b_name:<20} {diff:>10.4f} {t:>8.3f} {p:>8.4f} {sig:>6}")

# ─── 5. Cross-Sectional Vol Momentum ─────────────────────────────────────────

print("\n" + "=" * 80)
print("[5] Cross-Sectional Vol Momentum (Buy Declining Vol)")
print("=" * 80)
print("Long-short: Buy bottom tertile (declining vol), short top tertile (rising vol)")

# Monthly cross-sectional vol momentum
vol_mom_returns = []
long_returns = []
short_returns = []

for i in range(len(rebal_dates) - 1):
    rebal_date = rebal_dates[i]
    next_rebal = rebal_dates[i + 1]

    vc = vol_chg_aligned.loc[rebal_date]
    if vc.isna().any():
        continue

    # Sort assets by vol change
    sorted_assets = vc.sort_values()

    # Bottom tertile (declining vol) → long
    n_long = max(1, N_ASSETS // 3)
    n_short = max(1, N_ASSETS // 3)

    long_assets = sorted_assets.index[:n_long + 1]  # Most declining
    short_assets = sorted_assets.index[-(n_short + 1):]  # Most rising

    # Forward returns
    period_mask = (ret_aligned.index > rebal_date) & (ret_aligned.index <= next_rebal)
    period_ret = ret_aligned.loc[period_mask]

    if len(period_ret) == 0:
        continue

    long_ret = period_ret[long_assets].mean(axis=1)
    short_ret = period_ret[short_assets].mean(axis=1)
    ls_ret = long_ret - short_ret

    for r in ls_ret:
        vol_mom_returns.append(r)
    for r in long_ret:
        long_returns.append(r)
    for r in short_ret:
        short_returns.append(r)

vol_mom_returns = np.array(vol_mom_returns)
long_returns = np.array(long_returns)
short_returns = np.array(short_returns)

# Test if vol momentum is significant
t_mom, p_mom = stats.ttest_1samp(vol_mom_returns, 0)
ann_mom = vol_mom_returns.mean() * 252
vol_mom = vol_mom_returns.std() * np.sqrt(252)
sharpe_mom = ann_mom / vol_mom if vol_mom > 0 else 0

print(f"\nVol Momentum L/S Results:")
print(f"  Annual Return (L/S):  {ann_mom:.4f} ({ann_mom*100:.2f}%)")
print(f"  Annual Volatility:    {vol_mom:.4f}")
print(f"  Sharpe Ratio:         {sharpe_mom:.4f}")
print(f"  t-statistic:          {t_mom:.4f}")
print(f"  p-value:              {p_mom:.4f}")
print(f"  N observations:       {len(vol_mom_returns)}")
print(f"  Significant (t>3.0):  {'YES' if abs(t_mom) > 3.0 else 'NO'}")
print(f"  Significant (p<0.05): {'YES' if p_mom < 0.05 else 'NO'}")

# Long-only and short-only
m_long = compute_metrics(long_returns, 'Long (Declining Vol)')
m_short = compute_metrics(short_returns, 'Short (Rising Vol)')
print(f"\n  Long leg (declining vol):  Ann Ret = {m_long['ann_return']:.4f}, Sharpe = {m_long['sharpe']:.4f}")
print(f"  Short leg (rising vol):    Ann Ret = {m_short['ann_return']:.4f}, Sharpe = {m_short['sharpe']:.4f}")

# ─── 6. Vol Dispersion Analysis ──────────────────────────────────────────────

print("\n" + "=" * 80)
print("[6] Cross-Asset Vol Dispersion → Regime Shift Prediction")
print("=" * 80)
print("When all asset vols converge (low dispersion), is a regime shift coming?")

# Cross-sectional vol dispersion (std of vols across assets each day)
vol_dispersion = rolling_vol.std(axis=1)
vol_dispersion_norm = vol_dispersion / rolling_vol.mean(axis=1)  # Normalized

# Regime: low dispersion = bottom quintile
disp_q20 = vol_dispersion_norm.quantile(0.20)
disp_q80 = vol_dispersion_norm.quantile(0.80)

low_disp = vol_dispersion_norm[vol_dispersion_norm <= disp_q20]
high_disp = vol_dispersion_norm[vol_dispersion_norm >= disp_q80]
mid_disp = vol_dispersion_norm[(vol_dispersion_norm > disp_q20) & (vol_dispersion_norm < disp_q80)]

print(f"\nVol Dispersion (normalized CoV) Statistics:")
print(f"  Mean: {vol_dispersion_norm.mean():.4f}")
print(f"  Std:  {vol_dispersion_norm.std():.4f}")
print(f"  Q20:  {disp_q20:.4f} (low convergence threshold)")
print(f"  Q80:  {disp_q80:.4f} (high divergence threshold)")

# Forward realized vol change after low/high dispersion
print(f"\n--- Forward Regime Shift After Vol Convergence/Divergence ---")

# Use equal-weight portfolio for aggregate analysis
eq_ret = returns.mean(axis=1)
fwd_vol_change = rolling_vol.mean(axis=1).pct_change(REBAL_FREQ).shift(-REBAL_FREQ)
fwd_abs_ret = eq_ret.rolling(REBAL_FREQ).apply(lambda x: np.abs(x).mean()).shift(-REBAL_FREQ)

# Forward dispersion change
fwd_disp_change = vol_dispersion_norm.pct_change(REBAL_FREQ).shift(-REBAL_FREQ)

for label, idx_set in [('Low Dispersion (convergence)', low_disp.index),
                         ('High Dispersion (divergence)', high_disp.index),
                         ('Mid Dispersion', mid_disp.index)]:
    common = idx_set.intersection(fwd_disp_change.dropna().index)
    fwd_dc = fwd_disp_change.loc[common]
    fwd_vc = fwd_vol_change.loc[common].dropna()

    if len(fwd_dc) > 20:
        t_dc, p_dc = stats.ttest_1samp(fwd_dc.dropna(), 0)
        print(f"\n  {label} ({len(common)} obs):")
        print(f"    Fwd 22d dispersion change: {fwd_dc.mean():.4f} (t={t_dc:.3f}, p={p_dc:.4f})")
        if len(fwd_vc) > 20:
            t_vc, p_vc = stats.ttest_1samp(fwd_vc.dropna(), 0)
            print(f"    Fwd 22d avg vol change:    {fwd_vc.mean():.4f} (t={t_vc:.3f}, p={p_vc:.4f})")

# ─── 7. Does Vol Convergence Predict HIGHER Future Vol? ───────────────────────

print("\n" + "=" * 80)
print("[7] Vol Convergence → Future Vol Spike?")
print("=" * 80)

# After low dispersion, does TOTAL vol increase?
fwd_total_vol = rolling_vol.mean(axis=1).shift(-REBAL_FREQ)

results_convergence = {}
for label, idx_set in [('Low Dispersion', low_disp.index),
                         ('High Dispersion', high_disp.index)]:
    # Current vol level
    common = idx_set.intersection(fwd_total_vol.dropna().index)
    current_vol = rolling_vol.mean(axis=1).loc[common]
    future_vol = fwd_total_vol.loc[common]
    vol_ratio = (future_vol / current_vol).dropna()

    if len(vol_ratio) > 20:
        t_vr, p_vr = stats.ttest_1samp(vol_ratio, 1.0)  # Test if ratio > 1
        results_convergence[label] = {
            'mean_ratio': vol_ratio.mean(),
            'median_ratio': vol_ratio.median(),
            't_stat': t_vr,
            'p_val': p_vr,
            'n': len(vol_ratio),
            'pct_vol_increase': (vol_ratio > 1.0).mean()
        }
        print(f"\n  {label} ({len(vol_ratio)} obs):")
        print(f"    Future/Current vol ratio: {vol_ratio.mean():.4f} (median: {vol_ratio.median():.4f})")
        print(f"    t-stat (H0: ratio=1):     {t_vr:.4f}")
        print(f"    p-value:                  {p_vr:.4f}")
        print(f"    % cases vol increases:    {(vol_ratio > 1.0).mean()*100:.1f}%")
        print(f"    Significant (t>3.0):      {'YES' if abs(t_vr) > 3.0 else 'NO'}")

# ─── 8. Rolling Sharpe: Does Vol Rotation Improve Over Time? ──────────────────

print("\n" + "=" * 80)
print("[8] Sub-Period Analysis: Does Vol Rotation Work in Specific Regimes?")
print("=" * 80)

# Split into sub-periods
sub_periods = {
    '2016-2017 (Low Vol)': ('2016-01-01', '2017-12-31'),
    '2018-2019 (Vol Return)': ('2018-01-01', '2019-12-31'),
    '2020 (COVID)': ('2020-01-01', '2020-12-31'),
    '2021 (Recovery)': ('2021-01-01', '2021-12-31'),
    '2022 (Bear)': ('2022-01-01', '2022-12-31'),
    '2023-2024 (Mixed)': ('2023-01-01', '2024-12-31'),
}

# Need dates for the strategies
strat_dates = []
for i in range(len(rebal_dates) - 1):
    rebal_date = rebal_dates[i]
    next_rebal = rebal_dates[i + 1]
    period_mask = (ret_aligned.index > rebal_date) & (ret_aligned.index <= next_rebal)
    period_dates = ret_aligned.index[period_mask]
    strat_dates.extend(period_dates[:])

strat_dates = strat_dates[:min_len]
strat_dates_idx = pd.DatetimeIndex(strat_dates)

print(f"\n{'Period':<25} {'VolRot(R) SR':>12} {'VolRot(Z) SR':>12} {'EW SR':>12} "
      f"{'SPY/GLD SR':>12} {'VolRot-EW':>10}")
print("-" * 90)

for period_name, (start, end) in sub_periods.items():
    mask = (strat_dates_idx >= start) & (strat_dates_idx <= end)
    if mask.sum() < 50:
        continue

    vr_r = vol_rot_rank[mask]
    vr_z = vol_rot_zscore[mask]
    ew_r = ew_ret[mask]
    sg_r = sg_ret[mask]

    sr_vr_r = (vr_r.mean() - RISK_FREE) / vr_r.std() * np.sqrt(252) if vr_r.std() > 0 else 0
    sr_vr_z = (vr_z.mean() - RISK_FREE) / vr_z.std() * np.sqrt(252) if vr_z.std() > 0 else 0
    sr_ew = (ew_r.mean() - RISK_FREE) / ew_r.std() * np.sqrt(252) if ew_r.std() > 0 else 0
    sr_sg = (sg_r.mean() - RISK_FREE) / sg_r.std() * np.sqrt(252) if sg_r.std() > 0 else 0

    diff = sr_vr_r - sr_ew
    print(f"{period_name:<25} {sr_vr_r:>12.3f} {sr_vr_z:>12.3f} {sr_ew:>12.3f} "
          f"{sr_sg:>12.3f} {diff:>10.3f}")

# ─── 9. Robustness: Different Vol Windows ────────────────────────────────────

print("\n" + "=" * 80)
print("[9] Robustness: Different Vol Estimation Windows")
print("=" * 80)

vol_windows_test = [10, 22, 44, 66]
print(f"\n{'Window':>8} {'Ann Ret':>10} {'Sharpe':>8} {'MDD':>8} {'vs EW':>8}")
print("-" * 50)

for w in vol_windows_test:
    rv = returns.rolling(w).std() * np.sqrt(252)
    rv = rv.dropna()
    vc = rv.pct_change(w).dropna()

    cidx = vc.dropna().index.intersection(returns.index)
    vc_a = vc.loc[cidx]
    ret_a = returns.loc[cidx]
    rb_dates = cidx[::REBAL_FREQ]

    if len(rb_dates) < 10:
        continue

    vr, _ = vol_rotation_strategy(ret_a, vc_a, rb_dates, 'rank')
    ew = equal_weight_strategy(ret_a, rb_dates)
    ml = min(len(vr), len(ew))
    vr = vr[:ml]
    ew = ew[:ml]

    if len(vr) < 50:
        continue

    sr_vr = (vr.mean() - RISK_FREE) / vr.std() * np.sqrt(252) if vr.std() > 0 else 0
    sr_ew = (ew.mean() - RISK_FREE) / ew.std() * np.sqrt(252) if ew.std() > 0 else 0
    ann_r = vr.mean() * 252
    cum_vr = np.cumprod(1 + vr)
    peak = np.maximum.accumulate(cum_vr)
    mdd = ((cum_vr - peak) / peak).min()

    print(f"{w:>8}d {ann_r:>10.4f} {sr_vr:>8.3f} {mdd:>8.3f} {sr_vr - sr_ew:>+8.3f}")

# ─── 10. Turnover & Transaction Cost Analysis ────────────────────────────────

print("\n" + "=" * 80)
print("[10] Turnover & Transaction Cost Impact")
print("=" * 80)

if len(weights_rank) > 1:
    weights_arr = np.array(weights_rank)
    # Turnover at each rebalance (sum of abs weight changes)
    turnovers = []
    for i in range(1, len(weights_arr)):
        if i % REBAL_FREQ == 0 or True:  # Already at rebal frequency
            to = np.sum(np.abs(weights_arr[i] - weights_arr[i-1]))
            turnovers.append(to)

    avg_turnover = np.mean(turnovers) if turnovers else 0

    # With different TC assumptions
    print(f"\nAverage monthly turnover: {avg_turnover:.4f} ({avg_turnover*100:.2f}%)")
    print(f"Rebalances per year: ~{252/REBAL_FREQ:.0f}")

    print(f"\n{'TC (bps)':>10} {'Net Ann Ret':>12} {'Net Sharpe':>10} {'Gross-Net':>10}")
    print("-" * 48)

    gross_ret = metrics_all['Vol Rotation (Rank)']['ann_return']
    gross_vol = metrics_all['Vol Rotation (Rank)']['ann_vol']

    for tc_bps in [5, 10, 20, 50]:
        tc_per_rebal = avg_turnover * tc_bps / 10000
        annual_tc = tc_per_rebal * (252 / REBAL_FREQ)
        net_ret = gross_ret - annual_tc
        net_sharpe = (net_ret - RISK_FREE * 252) / gross_vol
        print(f"{tc_bps:>10} {net_ret:>12.4f} {net_sharpe:>10.3f} {annual_tc:>10.4f}")

# ─── 11. Predictive Regression: Vol Changes → Forward Returns ────────────────

print("\n" + "=" * 80)
print("[11] Predictive Regression: Vol Change → Forward Return")
print("=" * 80)
print("For each asset: Does its own vol change predict forward returns?")

print(f"\n{'Asset':<12} {'β(vol_chg)':>10} {'t-stat':>8} {'p-val':>8} {'R²':>8} {'N':>6} {'Sig?':>6}")
print("-" * 65)

for asset in asset_list:
    vc_a = vol_change[asset].dropna()
    fwd = returns[asset].rolling(REBAL_FREQ).sum().shift(-REBAL_FREQ)

    common = vc_a.index.intersection(fwd.dropna().index)
    x = vc_a.loc[common].values
    y = fwd.loc[common].values

    # Remove NaN
    valid = ~(np.isnan(x) | np.isnan(y))
    x, y = x[valid], y[valid]

    if len(x) > 50:
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        t_stat = slope / std_err if std_err > 0 else 0
        sig = '***' if p_value < 0.01 else ('**' if p_value < 0.05 else ('*' if p_value < 0.10 else ''))
        print(f"{asset:<12} {slope:>10.4f} {t_stat:>8.3f} {p_value:>8.4f} {r_value**2:>8.4f} {len(x):>6} {sig:>6}")

# ─── 12. Summary & Conclusions ───────────────────────────────────────────────

print("\n" + "=" * 80)
print("[12] SUMMARY & CONCLUSIONS")
print("=" * 80)

# Key metrics summary
vr_sharpe = metrics_all['Vol Rotation (Rank)']['sharpe']
ew_sharpe = metrics_all['Equal Weight']['sharpe']
sg_sharpe = metrics_all['50/50 SPY/GLD']['sharpe']
vr_mdd = metrics_all['Vol Rotation (Rank)']['mdd']

print(f"""
K405 Results Summary:
=====================

1. RELATIVE VOL CHANGES:
   - Vol ratios between asset pairs show extreme events (z>2) occurring
     across {sum(r['n_extreme'] for r in ratio_results.values())} total events
   - Predictive power for forward returns is {'weak' if all(abs(r['t_stat']) < 2 for r in ratio_results.values() if not np.isnan(r['t_stat'])) else 'mixed'}

2. VOL REGIME ROTATION STRATEGY:
   - Rank-based Sharpe: {vr_sharpe:.3f} vs Equal Weight: {ew_sharpe:.3f} vs 50/50: {sg_sharpe:.3f}
   - Sharpe improvement over EW: {vr_sharpe - ew_sharpe:+.3f}
   - MDD: {vr_mdd:.3f}

3. VOL MOMENTUM (L/S):
   - Annual Return: {ann_mom:.4f} ({ann_mom*100:.2f}%)
   - t-statistic: {t_mom:.3f} (Harvey threshold t>3.0: {'PASS' if abs(t_mom) > 3.0 else 'FAIL'})
   - {'SIGNIFICANT' if p_mom < 0.05 else 'NOT SIGNIFICANT'} at 5% level

4. VOL DISPERSION:
   - {'Convergence predicts vol increase' if 'Low Dispersion' in results_convergence and results_convergence['Low Dispersion']['mean_ratio'] > 1 else 'No clear convergence signal'}

5. CONCLUSION:
   - Vol rotation {'DOES' if vr_sharpe > ew_sharpe + 0.1 else 'does NOT'} meaningfully improve on equal weight
   - Cross-sectional vol momentum is {'a promising' if abs(t_mom) > 2.0 else 'NOT a reliable'} timing signal
   - Despite K404's finding of persistent vol ranks, relative changes {'DO' if abs(t_mom) > 2.0 else 'do NOT'}
     contain actionable rotation information
""")

# ─── Save Results ─────────────────────────────────────────────────────────────

results = {
    'experiment': 'K405',
    'title': 'Can We Time Asset Class ROTATION Using Volatility?',
    'data_source': 'yfinance',
    'assets': asset_list,
    'period': f'{returns.index[0].date()} to {returns.index[-1].date()}',
    'n_days': len(returns),
    'vol_window': VOL_WINDOW,
    'rebal_freq': REBAL_FREQ,
    'strategy_metrics': {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else vv
                              for kk, vv in v.items()}
                         for k, v in metrics_all.items()},
    'vol_momentum_ls': {
        'annual_return': float(ann_mom),
        'sharpe': float(sharpe_mom),
        't_stat': float(t_mom),
        'p_val': float(p_mom),
        'n_obs': int(len(vol_mom_returns)),
        'significant_harvey': bool(abs(t_mom) > 3.0),
        'significant_p05': bool(p_mom < 0.05)
    },
    'vol_dispersion': {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else int(vv) if isinstance(vv, (np.integer, int)) else vv
                           for kk, vv in v.items()}
                       for k, v in results_convergence.items()},
    'ratio_analysis': {f'{a}/{b}': {kk: float(vv) if isinstance(vv, (np.floating, float)) else vv
                                     for kk, vv in v.items()}
                       for (a, b), v in ratio_results.items()},
    'conclusion': {
        'vol_rotation_beats_ew': bool(vr_sharpe > ew_sharpe + 0.1),
        'vol_momentum_significant': bool(abs(t_mom) > 2.0),
        'harvey_threshold_pass': bool(abs(t_mom) > 3.0),
        'relative_vol_changes_actionable': bool(abs(t_mom) > 2.0),
    }
}

output_path = os.path.join(os.path.dirname(__file__), 'k405_vol_rotation_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to: {output_path}")
print("\n" + "=" * 80)
print("K405 COMPLETE")
print("=" * 80)
