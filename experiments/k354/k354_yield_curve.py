#!/usr/bin/env python3
"""
K354: Yield Curve Inversion and Volatility — The Classic Recession Predictor
=============================================================================
跳躍式探索：殖利率曲線反轉 → 股市波動率預測

問題：殖利率曲線反轉（短天期利率 > 長天期利率）是否能預測股市波動率？
      經典的衰退預測指標對 vol 預測有多少增量價值？

Data sources: yfinance (SHY, IEF, TLT, SPY, ^VIX)
Period: 2003-2024 (covers 2006-07 inversion→GFC, 2019 inversion→COVID, 2022-23 inversion)

Methodology:
1. Yield curve slope proxy: TLT 12m return - SHY 12m return
   - Positive: normal curve (long bonds outperform)
   - Negative: inverted curve (short bonds outperform = inversion)
2. Does curve inversion predict vol?
   - Partial r(slope, future_SPY_RV_22d | VIX)
   - Lead time: how far ahead does inversion predict vol?
3. Curve regime analysis:
   - Normal vs flat vs inverted periods
   - Vol during each regime
   - Does inversion predict vol SPIKES or SUSTAINED high vol?
4. Historical: 2006-2007 inversion→2008 GFC. 2019 inversion→2020 COVID. 2022-2023 inversion→?

[提出: 用戶 (跳躍式探索), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K354: Yield Curve Inversion and Volatility")
print("The Classic Recession Predictor — Does It Predict Vol?")
print("=" * 70)

tickers = {
    'SHY': 'iShares 1-3 Year Treasury Bond ETF (short rate proxy)',
    'IEF': 'iShares 7-10 Year Treasury Bond ETF (intermediate)',
    'TLT': 'iShares 20+ Year Treasury Bond ETF (long rate proxy)',
    'SPY': 'S&P 500 ETF',
    '^VIX': 'CBOE VIX Index',
}

print("\n[1] Downloading data 2002-2024...")
print("    (Starting 2002 to get 12m lookback for slope from 2003)")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2002-01-01', end='2024-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Align all series to common dates
common_idx = data['SHY'].index
for k in data:
    common_idx = common_idx.intersection(data[k].index)
print(f"\n  Common trading days: {len(common_idx)}")
print(f"  Period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

prices = pd.DataFrame({k: data[k].reindex(common_idx) for k in data})
prices.columns = ['SHY', 'IEF', 'TLT', 'SPY', 'VIX']

# ============================================================
# 2. Construct Yield Curve Slope Proxies
# ============================================================
print("\n" + "=" * 70)
print("[2] Constructing Yield Curve Slope Proxies")
print("=" * 70)

# Daily returns
ret = prices[['SHY', 'IEF', 'TLT', 'SPY']].pct_change()

# Yield curve slope proxies (rolling return differences)
# Positive = normal curve, Negative = inverted
for window_name, window_days in [('3m', 63), ('6m', 126), ('12m', 252)]:
    # TLT cumulative return - SHY cumulative return over window
    prices[f'slope_TLT_SHY_{window_name}'] = (
        prices['TLT'].pct_change(window_days) - prices['SHY'].pct_change(window_days)
    )
    # IEF cumulative return - SHY cumulative return over window
    prices[f'slope_IEF_SHY_{window_name}'] = (
        prices['IEF'].pct_change(window_days) - prices['SHY'].pct_change(window_days)
    )

# Also: TLT/SHY price ratio momentum (simpler signal)
prices['tlt_shy_ratio'] = prices['TLT'] / prices['SHY']
prices['tlt_shy_ratio_chg_6m'] = prices['tlt_shy_ratio'].pct_change(126)

# SPY realized volatility (forward-looking, for prediction target)
spy_ret = ret['SPY']
for horizon in [22, 44, 66]:
    prices[f'RV_{horizon}d_fwd'] = (
        spy_ret.rolling(horizon).std() * np.sqrt(252)
    ).shift(-horizon)

# SPY realized vol (backward, for conditioning)
prices['RV_22d'] = spy_ret.rolling(22).std() * np.sqrt(252)

# Drop NaN rows from lookback construction
analysis = prices.dropna(subset=['slope_TLT_SHY_12m', 'RV_22d_fwd', 'RV_22d', 'VIX']).copy()
print(f"\n  Analysis period: {analysis.index[0].strftime('%Y-%m-%d')} to {analysis.index[-1].strftime('%Y-%m-%d')}")
print(f"  Observations: {len(analysis)}")

# Summary of slope proxy
slope_12m = analysis['slope_TLT_SHY_12m']
print(f"\n  Slope (TLT-SHY 12m) statistics:")
print(f"    Mean:   {slope_12m.mean():.4f}")
print(f"    Std:    {slope_12m.std():.4f}")
print(f"    Min:    {slope_12m.min():.4f} ({slope_12m.idxmin().strftime('%Y-%m-%d')})")
print(f"    Max:    {slope_12m.max():.4f} ({slope_12m.idxmax().strftime('%Y-%m-%d')})")
pct_negative = (slope_12m < 0).mean() * 100
print(f"    % Negative (inverted): {pct_negative:.1f}%")

# ============================================================
# 3. Simple Correlations: Slope vs Future Vol
# ============================================================
print("\n" + "=" * 70)
print("[3] Simple Correlations: Slope vs Future Vol")
print("=" * 70)

print("\n  Pearson r(slope, future RV):")
print(f"  {'Slope Proxy':<25} {'→ RV 22d':>10} {'→ RV 44d':>10} {'→ RV 66d':>10}")
print("  " + "-" * 60)

slope_cols = [c for c in analysis.columns if c.startswith('slope_')]
for sc in slope_cols:
    vals = []
    for horizon in [22, 44, 66]:
        fwd_col = f'RV_{horizon}d_fwd'
        mask = analysis[[sc, fwd_col]].dropna().index
        r, p = stats.pearsonr(analysis.loc[mask, sc], analysis.loc[mask, fwd_col])
        vals.append(f"{r:+.4f}{'*' if p<0.05 else ' '}")
    print(f"  {sc:<25} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

# ============================================================
# 4. Partial Correlations (controlling for VIX)
# ============================================================
print("\n" + "=" * 70)
print("[4] Partial Correlations (controlling for current VIX)")
print("=" * 70)

def partial_corr(x, y, z):
    """Partial correlation of x and y, controlling for z."""
    mask = pd.DataFrame({'x': x, 'y': y, 'z': z}).dropna().index
    x_, y_, z_ = x.loc[mask].values, y.loc[mask].values, z.loc[mask].values
    # Residualize x on z
    slope_xz = np.polyfit(z_, x_, 1)
    x_resid = x_ - np.polyval(slope_xz, z_)
    # Residualize y on z
    slope_yz = np.polyfit(z_, y_, 1)
    y_resid = y_ - np.polyval(slope_yz, z_)
    r, p = stats.pearsonr(x_resid, y_resid)
    n = len(x_resid)
    return r, p, n

print(f"\n  Partial r(slope, future RV | VIX):")
print(f"  {'Slope Proxy':<25} {'→ RV 22d':>12} {'→ RV 44d':>12} {'→ RV 66d':>12}")
print("  " + "-" * 65)

# Focus on key slope proxies
key_slopes = ['slope_TLT_SHY_3m', 'slope_TLT_SHY_6m', 'slope_TLT_SHY_12m',
              'slope_IEF_SHY_3m', 'slope_IEF_SHY_6m', 'slope_IEF_SHY_12m']

results_partial = {}
for sc in key_slopes:
    vals = []
    for horizon in [22, 44, 66]:
        fwd_col = f'RV_{horizon}d_fwd'
        r, p, n = partial_corr(analysis[sc], analysis[fwd_col], analysis['VIX'])
        vals.append((r, p, n))
        results_partial[(sc, horizon)] = {'r': r, 'p': p, 'n': n}
    print(f"  {sc:<25} {vals[0][0]:+.4f} (p={vals[0][1]:.3f}) {vals[1][0]:+.4f} (p={vals[1][1]:.3f}) {vals[2][0]:+.4f} (p={vals[2][1]:.3f})")

print(f"\n  n = {vals[0][2]}")
print("  Harvey (2016) threshold: |t| > 3.0 for significance")

# Check Harvey threshold
for key, val in results_partial.items():
    t_stat = val['r'] * np.sqrt(val['n'] - 3) / np.sqrt(1 - val['r']**2)
    val['t_stat'] = t_stat

print(f"\n  t-statistics for key partial correlations:")
print(f"  {'Slope Proxy':<25} {'→ RV 22d':>12} {'→ RV 44d':>12} {'→ RV 66d':>12}")
print("  " + "-" * 65)
for sc in key_slopes:
    ts = []
    for horizon in [22, 44, 66]:
        t = results_partial[(sc, horizon)]['t_stat']
        ts.append(f"t={t:+.2f}")
    print(f"  {sc:<25} {ts[0]:>12} {ts[1]:>12} {ts[2]:>12}")

# ============================================================
# 5. Partial Correlations (controlling for VIX + current RV)
# ============================================================
print("\n" + "=" * 70)
print("[5] Partial Correlations (controlling for VIX + current RV)")
print("=" * 70)

def partial_corr_multi(x, y, controls):
    """Partial correlation of x and y, controlling for multiple variables."""
    df_all = pd.DataFrame({'x': x, 'y': y})
    for i, c in enumerate(controls):
        df_all[f'c{i}'] = c
    df_all = df_all.dropna()
    if len(df_all) < 10:
        return np.nan, np.nan, len(df_all)

    from numpy.linalg import lstsq
    X_ctrl = df_all[[f'c{i}' for i in range(len(controls))]].values
    X_ctrl = np.column_stack([np.ones(len(X_ctrl)), X_ctrl])

    # Residualize x
    beta_x, _, _, _ = lstsq(X_ctrl, df_all['x'].values, rcond=None)
    x_resid = df_all['x'].values - X_ctrl @ beta_x

    # Residualize y
    beta_y, _, _, _ = lstsq(X_ctrl, df_all['y'].values, rcond=None)
    y_resid = df_all['y'].values - X_ctrl @ beta_y

    r, p = stats.pearsonr(x_resid, y_resid)
    return r, p, len(df_all)

print(f"\n  Partial r(slope, future RV | VIX, current RV):")
print(f"  {'Slope Proxy':<25} {'→ RV 22d':>12} {'→ RV 44d':>12} {'→ RV 66d':>12}")
print("  " + "-" * 65)

results_partial_multi = {}
for sc in key_slopes:
    vals = []
    for horizon in [22, 44, 66]:
        fwd_col = f'RV_{horizon}d_fwd'
        r, p, n = partial_corr_multi(
            analysis[sc], analysis[fwd_col],
            [analysis['VIX'], analysis['RV_22d']]
        )
        vals.append((r, p, n))
        t_stat = r * np.sqrt(n - 4) / np.sqrt(1 - r**2) if abs(r) < 1 else np.nan
        results_partial_multi[(sc, horizon)] = {'r': r, 'p': p, 'n': n, 't_stat': t_stat}
    print(f"  {sc:<25} {vals[0][0]:+.4f} (p={vals[0][1]:.3f}) {vals[1][0]:+.4f} (p={vals[1][1]:.3f}) {vals[2][0]:+.4f} (p={vals[2][1]:.3f})")

# ============================================================
# 6. Lead-Lag Analysis: When Does Inversion Signal Vol?
# ============================================================
print("\n" + "=" * 70)
print("[6] Lead-Lag Analysis: How Far Ahead Does Inversion Predict Vol?")
print("=" * 70)

# Use the 12m slope as primary signal
slope_signal = analysis['slope_TLT_SHY_12m']
spy_rv_22d = analysis['RV_22d']

print("\n  Cross-correlation: slope(t) vs RV(t+lag)")
print(f"  {'Lag (days)':<15} {'r':>10} {'p-value':>10} {'t-stat':>10}")
print("  " + "-" * 50)

lag_results = []
for lag in [0, 5, 10, 22, 44, 66, 88, 126, 189, 252]:
    rv_shifted = spy_rv_22d.shift(-lag)
    mask = pd.DataFrame({'s': slope_signal, 'rv': rv_shifted}).dropna().index
    if len(mask) < 50:
        continue
    r, p = stats.pearsonr(slope_signal.loc[mask], rv_shifted.loc[mask])
    n = len(mask)
    t = r * np.sqrt(n - 2) / np.sqrt(1 - r**2)
    sig = "***" if abs(t) > 3.0 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"  {lag:>5}d (~{lag/22:.0f}m)    {r:+.4f}    {p:.4f}    {t:+.2f}  {sig}")
    lag_results.append({'lag': lag, 'r': r, 'p': p, 't': t})

# Find optimal lag
best_lag = max(lag_results, key=lambda x: abs(x['r']))
print(f"\n  Strongest correlation at lag = {best_lag['lag']} days (~{best_lag['lag']/22:.0f} months)")
print(f"    r = {best_lag['r']:+.4f}, t = {best_lag['t']:+.2f}")

# ============================================================
# 7. Regime Analysis: Normal vs Flat vs Inverted
# ============================================================
print("\n" + "=" * 70)
print("[7] Regime Analysis: Normal vs Flat vs Inverted Curve")
print("=" * 70)

# Define regimes using percentiles
slope = analysis['slope_TLT_SHY_12m']
p20 = slope.quantile(0.20)
p80 = slope.quantile(0.80)

analysis['curve_regime'] = 'Flat'
analysis.loc[slope > p80, 'curve_regime'] = 'Steep (normal)'
analysis.loc[slope < p20, 'curve_regime'] = 'Inverted/Flat-neg'

# Also use a simpler threshold: negative = inverted
analysis['is_inverted'] = (slope < 0).astype(int)

print(f"\n  Regime thresholds (percentile-based):")
print(f"    Steep (>80th pctl): slope > {p80:.4f}")
print(f"    Flat (20-80th):     slope in [{p20:.4f}, {p80:.4f}]")
print(f"    Inverted (<20th):   slope < {p20:.4f}")

print(f"\n  {'Regime':<20} {'Count':>8} {'%':>8} {'Mean RV':>10} {'Med RV':>10} {'Mean VIX':>10} {'Med VIX':>10}")
print("  " + "-" * 70)

regime_stats = {}
for regime in ['Steep (normal)', 'Flat', 'Inverted/Flat-neg']:
    mask = analysis['curve_regime'] == regime
    subset = analysis.loc[mask]
    n = len(subset)
    pct = n / len(analysis) * 100
    mean_rv = subset['RV_22d'].mean()
    med_rv = subset['RV_22d'].median()
    mean_vix = subset['VIX'].mean()
    med_vix = subset['VIX'].median()
    regime_stats[regime] = {
        'n': n, 'pct': pct, 'mean_rv': mean_rv, 'med_rv': med_rv,
        'mean_vix': mean_vix, 'med_vix': med_vix
    }
    print(f"  {regime:<20} {n:>8} {pct:>7.1f}% {mean_rv:>10.2f}% {med_rv:>10.2f}% {mean_vix:>10.1f} {med_vix:>10.1f}")

# FORWARD-LOOKING: what does each regime predict for FUTURE vol?
print(f"\n  Forward-looking: regime → future RV")
print(f"  {'Regime':<20} {'→ RV 22d fwd':>15} {'→ RV 44d fwd':>15} {'→ RV 66d fwd':>15}")
print("  " + "-" * 70)

for regime in ['Steep (normal)', 'Flat', 'Inverted/Flat-neg']:
    mask = analysis['curve_regime'] == regime
    vals = []
    for horizon in [22, 44, 66]:
        fwd_col = f'RV_{horizon}d_fwd'
        subset = analysis.loc[mask, fwd_col].dropna()
        vals.append(f"{subset.mean():.2f}%")
    print(f"  {regime:<20} {vals[0]:>15} {vals[1]:>15} {vals[2]:>15}")

# Statistical test: inverted vs steep
print(f"\n  Two-sample t-test: Inverted vs Steep regime future vol")
for horizon in [22, 44, 66]:
    fwd_col = f'RV_{horizon}d_fwd'
    inv = analysis.loc[analysis['curve_regime'] == 'Inverted/Flat-neg', fwd_col].dropna()
    stp = analysis.loc[analysis['curve_regime'] == 'Steep (normal)', fwd_col].dropna()
    t, p = stats.ttest_ind(inv, stp, equal_var=False)
    print(f"  RV {horizon}d fwd: Inverted mean={inv.mean():.2f}% vs Steep mean={stp.mean():.2f}%, "
          f"t={t:.2f}, p={p:.4f} {'***' if abs(t)>3 else '**' if p<0.01 else '*' if p<0.05 else 'NS'}")

# ============================================================
# 8. Simple Binary: Inverted (slope < 0) vs Normal (slope > 0)
# ============================================================
print("\n" + "=" * 70)
print("[8] Simple Binary Analysis: Slope < 0 (Inverted) vs > 0 (Normal)")
print("=" * 70)

inv_mask = analysis['slope_TLT_SHY_12m'] < 0
norm_mask = analysis['slope_TLT_SHY_12m'] > 0

n_inv = inv_mask.sum()
n_norm = norm_mask.sum()
print(f"\n  Inverted periods: {n_inv} days ({n_inv/len(analysis)*100:.1f}%)")
print(f"  Normal periods:   {n_norm} days ({n_norm/len(analysis)*100:.1f}%)")

# Identify inversion episodes
inversion_episodes = []
in_episode = False
start = None
for date, val in analysis['slope_TLT_SHY_12m'].items():
    if val < 0 and not in_episode:
        in_episode = True
        start = date
    elif (val >= 0 or date == analysis.index[-1]) and in_episode:
        end = date
        inversion_episodes.append((start, end))
        in_episode = False

print(f"\n  Inversion episodes (slope_TLT_SHY_12m < 0):")
for i, (s, e) in enumerate(inversion_episodes):
    duration = (e - s).days
    mean_rv_during = analysis.loc[s:e, 'RV_22d'].mean()
    mean_vix_during = analysis.loc[s:e, 'VIX'].mean()
    print(f"    #{i+1}: {s.strftime('%Y-%m-%d')} to {e.strftime('%Y-%m-%d')} "
          f"({duration} days, mean RV={mean_rv_during:.1f}%, mean VIX={mean_vix_during:.1f})")

print(f"\n  {'Metric':<30} {'Inverted':>12} {'Normal':>12} {'Diff':>10} {'t-stat':>10}")
print("  " + "-" * 80)

for metric, label in [
    ('RV_22d', 'Current RV 22d'),
    ('VIX', 'Current VIX'),
    ('RV_22d_fwd', 'Future RV 22d'),
    ('RV_44d_fwd', 'Future RV 44d'),
    ('RV_66d_fwd', 'Future RV 66d'),
]:
    inv_vals = analysis.loc[inv_mask, metric].dropna()
    norm_vals = analysis.loc[norm_mask, metric].dropna()
    diff = inv_vals.mean() - norm_vals.mean()
    t, p = stats.ttest_ind(inv_vals, norm_vals, equal_var=False)
    sig = "***" if abs(t) > 3.0 else "**" if p < 0.01 else "*" if p < 0.05 else "NS"
    print(f"  {label:<30} {inv_vals.mean():>12.2f} {norm_vals.mean():>12.2f} "
          f"{diff:>+10.2f} {t:>8.2f} {sig}")

# ============================================================
# 9. Vol Spike Prediction: Does Inversion Predict Extreme Vol?
# ============================================================
print("\n" + "=" * 70)
print("[9] Vol Spike Prediction: Does Inversion Predict Extreme Vol?")
print("=" * 70)

# Define vol spike as future RV > 80th percentile
rv_80 = analysis['RV_22d_fwd'].quantile(0.80)
rv_90 = analysis['RV_22d_fwd'].quantile(0.90)
print(f"\n  Vol spike thresholds: >80th pctl = {rv_80:.2f}%, >90th pctl = {rv_90:.2f}%")

for threshold_name, threshold in [('80th pctl', rv_80), ('90th pctl', rv_90)]:
    spike = (analysis['RV_22d_fwd'] > threshold).astype(int)

    # Spike rate during inverted vs normal
    spike_inv = spike[inv_mask].mean() * 100
    spike_norm = spike[norm_mask].mean() * 100

    # Chi-squared test
    ct = pd.crosstab(inv_mask.astype(int), spike)
    chi2, p_chi, _, _ = stats.chi2_contingency(ct)

    print(f"\n  Vol spike (>{threshold_name}):")
    print(f"    During inverted:  {spike_inv:.1f}% of days see spike")
    print(f"    During normal:    {spike_norm:.1f}% of days see spike")
    print(f"    Ratio:            {spike_inv/spike_norm:.2f}x" if spike_norm > 0 else "    Ratio: N/A")
    print(f"    Chi-squared: {chi2:.2f}, p={p_chi:.4f} {'***' if chi2 > 10 else '*' if p_chi<0.05 else 'NS'}")

# ============================================================
# 10. Historical Case Studies
# ============================================================
print("\n" + "=" * 70)
print("[10] Historical Case Studies")
print("=" * 70)

events = [
    ('2006-2007 Inversion → GFC', '2006-01-01', '2007-12-31', '2008-01-01', '2009-03-31'),
    ('2019 Inversion → COVID', '2019-01-01', '2019-12-31', '2020-01-01', '2020-06-30'),
    ('2022-2023 Inversion → ?', '2022-01-01', '2023-12-31', '2024-01-01', '2024-12-31'),
]

for event_name, inv_start, inv_end, crisis_start, crisis_end in events:
    print(f"\n  === {event_name} ===")

    # Inversion period stats
    inv_period = analysis.loc[inv_start:inv_end]
    if len(inv_period) == 0:
        print(f"    No data for this period")
        continue

    slope_inv = inv_period['slope_TLT_SHY_12m']
    pct_inv = (slope_inv < 0).mean() * 100
    min_slope = slope_inv.min()
    mean_rv = inv_period['RV_22d'].mean()
    mean_vix = inv_period['VIX'].mean()
    print(f"    Inversion period ({inv_start} to {inv_end}):")
    print(f"      % days inverted: {pct_inv:.1f}%")
    print(f"      Most inverted:   {min_slope:.4f}")
    print(f"      Mean RV:         {mean_rv:.2f}%")
    print(f"      Mean VIX:        {mean_vix:.1f}")

    # Crisis period stats
    crisis = analysis.loc[crisis_start:crisis_end]
    if len(crisis) > 0:
        crisis_max_rv = crisis['RV_22d'].max()
        crisis_max_vix = crisis['VIX'].max()
        crisis_mean_rv = crisis['RV_22d'].mean()
        print(f"    Post-inversion ({crisis_start} to {crisis_end}):")
        print(f"      Max RV:          {crisis_max_rv:.2f}%")
        print(f"      Mean RV:         {crisis_mean_rv:.2f}%")
        print(f"      Max VIX:         {crisis_max_vix:.1f}")

# ============================================================
# 11. Granger Causality (VAR-style)
# ============================================================
print("\n" + "=" * 70)
print("[11] Granger Causality: Does Slope Granger-Cause Vol?")
print("=" * 70)

# Weekly frequency to reduce autocorrelation
weekly = analysis[['slope_TLT_SHY_12m', 'RV_22d', 'VIX']].resample('W').last().dropna()
print(f"\n  Weekly data: {len(weekly)} observations")

# Simple Granger test: regress RV(t) on RV(t-1..t-p) + slope(t-1..t-p)
# Compare with restricted model: RV(t) on RV(t-1..t-p) only
from numpy.linalg import lstsq

for p_lags in [4, 8, 12]:  # 1m, 2m, 3m of weekly lags
    y = weekly['RV_22d'].values[p_lags:]
    n_obs = len(y)

    # Restricted model: only RV lags
    X_r = np.column_stack([
        weekly['RV_22d'].shift(i).values[p_lags:] for i in range(1, p_lags+1)
    ])
    X_r = np.column_stack([np.ones(n_obs), X_r])
    beta_r, res_r, _, _ = lstsq(X_r, y, rcond=None)
    ssr_r = np.sum((y - X_r @ beta_r)**2)

    # Unrestricted model: RV lags + slope lags
    X_u = np.column_stack([
        X_r,
        *[weekly['slope_TLT_SHY_12m'].shift(i).values[p_lags:].reshape(-1,1) for i in range(1, p_lags+1)]
    ])
    beta_u, res_u, _, _ = lstsq(X_u, y, rcond=None)
    ssr_u = np.sum((y - X_u @ beta_u)**2)

    # F-test
    k_extra = p_lags  # number of added slope variables
    k_total = X_u.shape[1]
    F_stat = ((ssr_r - ssr_u) / k_extra) / (ssr_u / (n_obs - k_total))
    p_value = 1 - stats.f.cdf(F_stat, k_extra, n_obs - k_total)

    sig = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*" if p_value < 0.05 else "NS"
    print(f"  Lags={p_lags} weeks (~{p_lags/4:.0f}m): F={F_stat:.3f}, p={p_value:.4f} {sig}")

# ============================================================
# 12. Incremental R² Analysis
# ============================================================
print("\n" + "=" * 70)
print("[12] Incremental R² — How Much Does Slope Add Beyond VIX?")
print("=" * 70)

for horizon in [22, 44, 66]:
    fwd_col = f'RV_{horizon}d_fwd'
    df_reg = analysis[['VIX', 'RV_22d', 'slope_TLT_SHY_12m', fwd_col]].dropna()
    y = df_reg[fwd_col].values
    n = len(y)

    # Model 1: VIX only
    X1 = np.column_stack([np.ones(n), df_reg['VIX'].values])
    beta1, _, _, _ = lstsq(X1, y, rcond=None)
    y_hat1 = X1 @ beta1
    ss_res1 = np.sum((y - y_hat1)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2_vix = 1 - ss_res1 / ss_tot

    # Model 2: VIX + current RV
    X2 = np.column_stack([np.ones(n), df_reg['VIX'].values, df_reg['RV_22d'].values])
    beta2, _, _, _ = lstsq(X2, y, rcond=None)
    y_hat2 = X2 @ beta2
    ss_res2 = np.sum((y - y_hat2)**2)
    r2_vix_rv = 1 - ss_res2 / ss_tot

    # Model 3: VIX + current RV + slope
    X3 = np.column_stack([np.ones(n), df_reg['VIX'].values, df_reg['RV_22d'].values,
                           df_reg['slope_TLT_SHY_12m'].values])
    beta3, _, _, _ = lstsq(X3, y, rcond=None)
    y_hat3 = X3 @ beta3
    ss_res3 = np.sum((y - y_hat3)**2)
    r2_full = 1 - ss_res3 / ss_tot

    delta_r2 = r2_full - r2_vix_rv

    # F-test for incremental R²
    F_incr = (delta_r2 / 1) / ((1 - r2_full) / (n - 4))
    p_incr = 1 - stats.f.cdf(F_incr, 1, n - 4)

    print(f"\n  RV {horizon}d fwd (n={n}):")
    print(f"    R²(VIX only):          {r2_vix:.4f}")
    print(f"    R²(VIX + RV):          {r2_vix_rv:.4f}")
    print(f"    R²(VIX + RV + slope):  {r2_full:.4f}")
    print(f"    ΔR² from slope:        {delta_r2:.4f} ({delta_r2*100:.2f}%)")
    print(f"    F-test for slope:      F={F_incr:.2f}, p={p_incr:.4f} {'***' if abs(np.sqrt(F_incr))>3 else '*' if p_incr<0.05 else 'NS'}")

# ============================================================
# 13. IEF-SHY vs TLT-SHY Comparison
# ============================================================
print("\n" + "=" * 70)
print("[13] IEF-SHY vs TLT-SHY: Which Slope Proxy Works Better?")
print("=" * 70)

print(f"\n  Partial r(slope, RV 22d fwd | VIX, current RV):")
print(f"  {'Proxy':<25} {'3m slope':>12} {'6m slope':>12} {'12m slope':>12}")
print("  " + "-" * 65)

for pair in ['TLT_SHY', 'IEF_SHY']:
    vals = []
    for window in ['3m', '6m', '12m']:
        sc = f'slope_{pair}_{window}'
        r, p, n = partial_corr_multi(
            analysis[sc], analysis['RV_22d_fwd'],
            [analysis['VIX'], analysis['RV_22d']]
        )
        vals.append(f"{r:+.4f} (p={p:.3f})")
    print(f"  {pair:<25} {vals[0]:>18} {vals[1]:>18} {vals[2]:>18}")

# ============================================================
# 14. Slope CHANGE as signal (momentum of steepening/flattening)
# ============================================================
print("\n" + "=" * 70)
print("[14] Slope CHANGE as Signal (Flattening Momentum)")
print("=" * 70)

# Change in slope over 22 days
analysis['slope_change_22d'] = analysis['slope_TLT_SHY_12m'].diff(22)
# Change in slope over 44 days
analysis['slope_change_44d'] = analysis['slope_TLT_SHY_12m'].diff(44)

print(f"\n  Does CHANGE in slope predict vol better than level?")
print(f"  Partial r(Δslope, future RV | VIX, RV):")

for signal_name, signal_col in [
    ('Slope level (12m)', 'slope_TLT_SHY_12m'),
    ('Δ Slope 22d', 'slope_change_22d'),
    ('Δ Slope 44d', 'slope_change_44d'),
]:
    vals = []
    for horizon in [22, 44, 66]:
        fwd_col = f'RV_{horizon}d_fwd'
        r, p, n = partial_corr_multi(
            analysis[signal_col], analysis[fwd_col],
            [analysis['VIX'], analysis['RV_22d']]
        )
        t_stat = r * np.sqrt(n - 4) / np.sqrt(1 - r**2) if abs(r) < 1 else np.nan
        vals.append(f"{r:+.4f} (t={t_stat:+.2f})")
    print(f"  {signal_name:<25} {vals[0]:>18} {vals[1]:>18} {vals[2]:>18}")

# ============================================================
# 15. Interaction: Does Slope Matter More When VIX is Low?
# ============================================================
print("\n" + "=" * 70)
print("[15] Interaction: Does Slope Matter More When VIX is Low?")
print("=" * 70)

vix_med = analysis['VIX'].median()
print(f"\n  VIX median: {vix_med:.1f}")

for vix_regime, vix_mask_fn, label in [
    ('Low VIX', lambda x: x < vix_med, f'VIX < {vix_med:.0f}'),
    ('High VIX', lambda x: x >= vix_med, f'VIX >= {vix_med:.0f}'),
]:
    vmask = vix_mask_fn(analysis['VIX'])
    subset = analysis.loc[vmask]
    r, p = stats.pearsonr(
        subset['slope_TLT_SHY_12m'].dropna(),
        subset.loc[subset['slope_TLT_SHY_12m'].dropna().index, 'RV_22d_fwd'].dropna()
    )
    n = min(len(subset['slope_TLT_SHY_12m'].dropna()), len(subset['RV_22d_fwd'].dropna()))
    common = subset[['slope_TLT_SHY_12m', 'RV_22d_fwd']].dropna()
    r, p = stats.pearsonr(common['slope_TLT_SHY_12m'], common['RV_22d_fwd'])
    n = len(common)
    t = r * np.sqrt(n - 2) / np.sqrt(1 - r**2)
    print(f"  {label}: r(slope, RV_fwd)={r:+.4f}, t={t:+.2f}, n={n}")

# ============================================================
# 16. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[16] SUMMARY: K354 Yield Curve Inversion and Volatility")
print("=" * 70)

# Gather key results
best_partial = results_partial_multi.get(('slope_TLT_SHY_12m', 22), {})
best_r = best_partial.get('r', np.nan)
best_t = best_partial.get('t_stat', np.nan)
best_p = best_partial.get('p', np.nan)

# Determine overall verdict
if abs(best_t) > 3.0:
    verdict = "SIGNIFICANT (Harvey threshold met)"
    stars = "★★★"
elif best_p < 0.05:
    verdict = "MARGINALLY SIGNIFICANT (p<0.05 but |t|<3)"
    stars = "★★"
elif best_p < 0.10:
    verdict = "WEAK SIGNAL (p<0.10)"
    stars = "★"
else:
    verdict = "NOT SIGNIFICANT"
    stars = "NULL"

print(f"""
  Research Question: Does yield curve inversion predict equity volatility?

  Data: SHY/IEF/TLT/SPY/VIX from yfinance, {analysis.index[0].strftime('%Y-%m-%d')} to {analysis.index[-1].strftime('%Y-%m-%d')}
  Observations: {len(analysis)}

  Key Results:
  ─────────────────────────────────────────────
  1. Partial r(slope_12m, RV_22d_fwd | VIX, RV) = {best_r:+.4f}
     t-stat = {best_t:+.2f}, p = {best_p:.4f}

  2. Inverted vs Normal periods:
     Inverted mean future RV: {analysis.loc[inv_mask, 'RV_22d_fwd'].mean():.2f}%
     Normal mean future RV:   {analysis.loc[norm_mask, 'RV_22d_fwd'].mean():.2f}%

  3. Lead time: strongest at ~{best_lag['lag']/22:.0f} months ahead

  4. Inversion episodes identified: {len(inversion_episodes)}
     (covering 2006-07, 2019, 2022-23 inversions)

  Verdict: {stars} {verdict}

  Limitations:
  - ETF return spread is a PROXY for yield curve slope, not actual yields
  - SHY started ~2002, limiting pre-GFC history
  - Only 2-3 major inversion episodes in sample (small N for episode analysis)
  - Forward-looking bias in regime classification (12m lookback)
  - TLT duration (~17yr) vs SHY (~2yr) mismatch with standard 2s10s spread
""")

print("=" * 70)
print("K354 complete.")
print("=" * 70)
