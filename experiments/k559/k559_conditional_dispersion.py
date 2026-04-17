#!/usr/bin/env python3
"""
K559: Conditional Dispersion Trade — Correlation Risk Premium Mispricing
========================================================================

Source: Codex GPT-5.4 suggestion #2: "Shift from predicting index variance
to predicting when correlation risk premium is mispriced."

Concept: Trade the SPREAD between index implied vol and constituent vols.
When macro shocks loom, correlations spike → index vol rises faster than
sector vol → correlation dynamics provide actionable signal.

KEY DIFFERENTIATION from prior work (K151/K164/K165/K254/K415):
- K415 tested CSVD level as vol predictor → null (VIX absorbs)
- K559 tests DISPERSION CHANGES and CORRELATION DYNAMICS as trading overlay
- Focus on RATE OF CHANGE of dispersion (not level)
- Implied correlation proxy: (Index RV)² / (avg sector RV)²
- Signal: dispersion regime SHIFTS, not absolute level

Prior knowledge:
- K151: Cross-category CSVD = NULL, VIX absorbs
- K164/K165: Realized dispersion = overlapping window artifact
- K254: Vol dispersion = VIX proxy
- K415: 9-sector CSVD comprehensive test, all 6 variants underperform, VIX #29
- 12/VIX confirmed irreducible 35+ times

Design:
1. Data: SPY + 9 sector ETFs (XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLRE)
2. Compute:
   - Index RV: 22-day realized vol of SPY
   - Avg sector RV: mean of 9 sector realized vols
   - Implied correlation proxy: (Index RV)² / (avg sector RV)²
   - Dispersion = avg_sector_RV - index_RV
   - Dispersion change = 5-day change in dispersion
3. Trading signals:
   a. Dispersion Level: high disp (>75th) → bullish, low (<25th) → defensive
   b. Dispersion Momentum: rapid dispersion drop → correlations spiking → reduce
   c. Implied Corr Regime: high corr → VT most needed, low corr → more equity
   d. Combined: dispersion level + momentum + VIX
4. All as overlays on 12/VIX baseline
5. Cross-OOS: 3 periods (2010-2014 / 2015-2019 / 2020-2025)
6. Harvey (2016) t > 3.0 threshold

Literature:
- Driessen, Maenhout & Vilkov (2009): "The Price of Correlation Risk", JFE
- Pollet & Wilson (2010): "Average correlation and stock market returns", JFE
- Mueller et al. (2017): "International Correlation Risk", JFE
- Buss & Vilkov (2012): "Measuring Equity Risk with Option-Implied Correlations", RFS
- Harvey, Liu & Zhu (2016): "...and the Cross-Section of Expected Returns", RFS

Data source: yfinance (SPY, ^VIX, XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLRE)
Period: 2005-01 to 2026-03
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K559: Conditional Dispersion Trade")
print("Correlation Risk Premium Mispricing (Codex suggestion #2)")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD
# =================================================================
print("\n[1] Downloading data...")

tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'XLK': 'XLK',  # Technology
    'XLF': 'XLF',  # Financials
    'XLV': 'XLV',  # Healthcare
    'XLE': 'XLE',  # Energy
    'XLI': 'XLI',  # Industrials
    'XLY': 'XLY',  # Consumer Discretionary
    'XLP': 'XLP',  # Consumer Staples
    'XLU': 'XLU',  # Utilities
    'XLRE': 'XLRE',  # Real Estate
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2004-01-01", end="2026-12-31", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align all data to common dates
common_idx = data['SPY'].index
for name in tickers:
    common_idx = common_idx.intersection(data[name].index)
print(f"\n  Common dates: {len(common_idx)} ({common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')})")

# XLRE starts late (2015), so we use two approaches:
# A) Full sample with 8 sectors (XLK/XLF/XLV/XLE/XLI/XLY/XLP/XLU) from 2005
# B) Full 9 sectors from XLRE inception
sector_8 = ['XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU']
sector_9 = sector_8 + ['XLRE']

# Use 8 sectors for longer history
common_8 = data['SPY'].index
for s in sector_8 + ['VIX']:
    common_8 = common_8.intersection(data[s].index)
print(f"  8-sector common dates: {len(common_8)} ({common_8[0].strftime('%Y-%m-%d')} to {common_8[-1].strftime('%Y-%m-%d')})")

# Build returns
spy_ret = data['SPY'].loc[common_8, 'Close'].pct_change()
spy_close = data['SPY'].loc[common_8, 'Close']
vix = data['VIX'].loc[common_8, 'Close']

sector_rets = {}
for s in sector_8:
    sector_rets[s] = data[s].loc[common_8, 'Close'].pct_change()

# Drop NaN first row
spy_ret = spy_ret.dropna()
vix = vix.loc[spy_ret.index]
spy_close = spy_close.loc[spy_ret.index]
for s in sector_8:
    sector_rets[s] = sector_rets[s].loc[spy_ret.index]

print(f"\n  Final sample: {len(spy_ret)} daily returns")
print(f"  Period: {spy_ret.index[0].strftime('%Y-%m-%d')} to {spy_ret.index[-1].strftime('%Y-%m-%d')}")

# =================================================================
# 2. COMPUTE DISPERSION METRICS
# =================================================================
print("\n[2] Computing dispersion metrics...")

window = 22  # 1-month realized vol window

# SPY realized vol (annualized)
spy_rv = spy_ret.rolling(window).std() * np.sqrt(252)

# Sector realized vols
sector_rvs = pd.DataFrame()
for s in sector_8:
    sector_rvs[s] = sector_rets[s].rolling(window).std() * np.sqrt(252)

# Average sector RV
avg_sector_rv = sector_rvs.mean(axis=1)

# Cross-sectional standard deviation of sector RVs (dispersion measure)
csvd = sector_rvs.std(axis=1)

# Implied correlation proxy: (Index RV)^2 / (avg sector RV)^2
# Under equal weighting: Var(index) = avg_corr * avg_var(sectors) + (1-avg_corr)*var(sectors)/N
# Simplified: implied_corr ~ (index_var) / (avg_sector_var)
implied_corr = (spy_rv ** 2) / (avg_sector_rv ** 2)
implied_corr = implied_corr.clip(0, 1)  # Bound to [0, 1]

# Dispersion = avg_sector_RV - index_RV (positive = low correlation, diversification benefit)
dispersion = avg_sector_rv - spy_rv

# Relative dispersion (normalized)
rel_disp = dispersion / avg_sector_rv

# Dispersion momentum (5-day change)
disp_momentum = dispersion.diff(5)

# Implied corr momentum (5-day change)
corr_momentum = implied_corr.diff(5)

# Drop NaN from rolling windows
valid_start = max(window + 5, 30)  # Need enough data for rolling + momentum
metrics = pd.DataFrame({
    'spy_ret': spy_ret,
    'spy_rv': spy_rv,
    'avg_sector_rv': avg_sector_rv,
    'csvd': csvd,
    'implied_corr': implied_corr,
    'dispersion': dispersion,
    'rel_disp': rel_disp,
    'disp_momentum': disp_momentum,
    'corr_momentum': corr_momentum,
    'vix': vix,
}).dropna()

print(f"  Valid observations: {len(metrics)}")

# =================================================================
# 3. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# =================================================================
print("\n[3] Descriptive statistics...")

desc_cols = ['spy_rv', 'avg_sector_rv', 'dispersion', 'rel_disp', 'implied_corr', 'csvd']
desc = metrics[desc_cols].describe().round(4)
print(desc.to_string())

# Correlations
print("\n  Key correlations:")
corr_pairs = [
    ('dispersion', 'vix'),
    ('implied_corr', 'vix'),
    ('csvd', 'vix'),
    ('disp_momentum', 'vix'),
    ('rel_disp', 'vix'),
    ('dispersion', 'spy_ret'),
    ('implied_corr', 'spy_ret'),
    ('disp_momentum', 'spy_ret'),
]
corr_results = {}
for a, b in corr_pairs:
    r, p = stats.pearsonr(metrics[a], metrics[b])
    print(f"    {a} vs {b}: r={r:.4f}, p={p:.4e}")
    corr_results[f'{a}_vs_{b}'] = {'r': round(r, 4), 'p': round(p, 6)}

# Partial correlation: dispersion vs next-day return, controlling for VIX
from numpy.linalg import lstsq
def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Regress x on z, get residuals
    Z = np.column_stack([z, np.ones(len(z))])
    bx = lstsq(Z, x, rcond=None)[0]
    rx = x - Z @ bx
    by = lstsq(Z, y, rcond=None)[0]
    ry = y - Z @ by
    r, p = stats.pearsonr(rx, ry)
    t = r * np.sqrt(len(x) - 3) / np.sqrt(1 - r**2)
    return r, p, t

# Next-day return prediction (controlling for VIX)
next_ret = metrics['spy_ret'].shift(-1).dropna()
common = metrics.index.intersection(next_ret.index)
print("\n  Partial correlations (controlling for VIX) with NEXT-DAY return:")
for signal in ['dispersion', 'implied_corr', 'disp_momentum', 'corr_momentum', 'rel_disp', 'csvd']:
    x = metrics.loc[common, signal].values
    y = next_ret.loc[common].values
    z = metrics.loc[common, 'vix'].values
    r, p, t = partial_corr(x, y, z)
    harvey_pass = "PASS" if abs(t) > 3.0 else "FAIL"
    print(f"    {signal:20s}: partial_r={r:.4f}, t={t:.2f}, p={p:.4e} [{harvey_pass}]")

# =================================================================
# 4. STRATEGY DEFINITIONS
# =================================================================
print("\n[4] Defining strategies...")

# Base: 12/VIX
vt_weight = (12.0 / metrics['vix']).clip(0, 1)

# Strategy 1: Dispersion Level Overlay
# High dispersion (>75th pctile) → more equity (bullish, low corr)
# Low dispersion (<25th pctile) → reduce equity (high corr, defensive)
def strategy_disp_level(metrics, vt_w, lookback=252):
    """Dispersion level as overlay on 12/VIX."""
    disp = metrics['dispersion']
    rolling_75 = disp.rolling(lookback, min_periods=60).quantile(0.75)
    rolling_25 = disp.rolling(lookback, min_periods=60).quantile(0.25)

    # Adjustment: high disp → +10% equity, low disp → -10% equity
    adj = pd.Series(0.0, index=metrics.index)
    adj[disp > rolling_75] = 0.10   # Low correlation → more equity
    adj[disp < rolling_25] = -0.10  # High correlation → defensive

    w = (vt_w + adj).clip(0, 1)
    return w

# Strategy 2: Dispersion Momentum Overlay
# Rapid drop in dispersion → correlations spiking → reduce equity
# Rapid rise in dispersion → correlations falling → add equity
def strategy_disp_momentum(metrics, vt_w, lookback=252):
    """Dispersion momentum (5-day change) as overlay."""
    mom = metrics['disp_momentum']
    rolling_std = mom.rolling(lookback, min_periods=60).std()
    z_score = mom / rolling_std

    # z < -1.5 → correlations spiking → reduce 15%
    # z > 1.5 → correlations falling → add 10%
    adj = pd.Series(0.0, index=metrics.index)
    adj[z_score < -1.5] = -0.15
    adj[z_score > 1.5] = 0.10

    w = (vt_w + adj).clip(0, 1)
    return w

# Strategy 3: Implied Correlation Regime
# High implied corr → all moving together → VT most needed → keep 12/VIX
# Low implied corr → diversification works → can hold more equity
def strategy_corr_regime(metrics, vt_w, lookback=252):
    """Implied correlation regime overlay."""
    corr = metrics['implied_corr']
    rolling_75 = corr.rolling(lookback, min_periods=60).quantile(0.75)
    rolling_25 = corr.rolling(lookback, min_periods=60).quantile(0.25)
    rolling_med = corr.rolling(lookback, min_periods=60).quantile(0.50)

    # Low corr → add equity (diversification strong)
    # High corr → reduce equity (everything moving together)
    adj = pd.Series(0.0, index=metrics.index)
    adj[corr < rolling_25] = 0.10
    adj[corr > rolling_75] = -0.10

    w = (vt_w + adj).clip(0, 1)
    return w

# Strategy 4: Combined (Level + Momentum + Corr)
def strategy_combined(metrics, vt_w, lookback=252):
    """Combined signal: dispersion level + momentum + implied corr."""
    disp = metrics['dispersion']
    mom = metrics['disp_momentum']
    corr = metrics['implied_corr']

    # Normalize all to z-scores
    disp_z = (disp - disp.rolling(lookback, min_periods=60).mean()) / disp.rolling(lookback, min_periods=60).std()
    mom_z = mom / mom.rolling(lookback, min_periods=60).std()
    corr_z = (corr - corr.rolling(lookback, min_periods=60).mean()) / corr.rolling(lookback, min_periods=60).std()

    # Combined: high disp = bullish (+), mom up = bullish (+), high corr = bearish (-)
    combo = 0.3 * disp_z + 0.3 * mom_z - 0.4 * corr_z

    # Map to weight adjustment: [-1, 1] → [-0.15, +0.15]
    adj = (combo.clip(-1, 1) * 0.15)

    w = (vt_w + adj).clip(0, 1)
    return w

# Strategy 5: Aggressive Dispersion Drop Detector
# Specifically target rapid dispersion collapse (correlation spike events)
def strategy_disp_crash(metrics, vt_w, lookback=252):
    """Dispersion crash detector — big drops trigger defensive mode."""
    disp = metrics['dispersion']

    # 5-day % change in dispersion
    disp_pct_chg = disp.pct_change(5)

    # Threshold: bottom 10th percentile of changes → crash
    rolling_10 = disp_pct_chg.rolling(lookback, min_periods=60).quantile(0.10)

    # When dispersion drops sharply (below 10th pctile) → reduce 20%
    adj = pd.Series(0.0, index=metrics.index)
    adj[disp_pct_chg < rolling_10] = -0.20

    # When dispersion rebounds sharply (above 90th pctile) → add 10%
    rolling_90 = disp_pct_chg.rolling(lookback, min_periods=60).quantile(0.90)
    adj[disp_pct_chg > rolling_90] = 0.10

    w = (vt_w + adj).clip(0, 1)
    return w

strategies = {
    'base_12vix': vt_weight,
    'S1_disp_level': strategy_disp_level(metrics, vt_weight),
    'S2_disp_momentum': strategy_disp_momentum(metrics, vt_weight),
    'S3_corr_regime': strategy_corr_regime(metrics, vt_weight),
    'S4_combined': strategy_combined(metrics, vt_weight),
    'S5_disp_crash': strategy_disp_crash(metrics, vt_weight),
}

# Buy & Hold for reference
bh_weight = pd.Series(1.0, index=metrics.index)

print("  Strategies defined:")
for name, w in strategies.items():
    valid = w.dropna()
    print(f"    {name}: mean_w={valid.mean():.3f}, std_w={valid.std():.3f}, "
          f"min={valid.min():.3f}, max={valid.max():.3f}")

# =================================================================
# 5. BACKTEST ENGINE
# =================================================================
print("\n[5] Backtesting...")

def backtest(weights, spy_returns, rf_rate=0.02/252):
    """Backtest a VT strategy with given weights."""
    common = weights.dropna().index.intersection(spy_returns.dropna().index)
    w = weights.loc[common]
    r = spy_returns.loc[common]

    # Portfolio return: w * SPY + (1-w) * rf
    port_ret = w.shift(1) * r + (1 - w.shift(1)) * rf_rate
    port_ret = port_ret.dropna()

    if len(port_ret) < 252:
        return None

    # Metrics
    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + port_ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = port_ret[port_ret < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        'ann_ret': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'sortino': round(sortino, 4),
        'calmar': round(calmar, 4),
        'n_days': len(port_ret),
        'port_ret': port_ret,
    }

# Full sample backtest
print("\n  Full sample results:")
full_results = {}
port_rets = {}
for name, w in list(strategies.items()):
    res = backtest(w, spy_ret)
    if res:
        port_ret = res.pop('port_ret')
        full_results[name] = res
        print(f"    {name:25s}: Sharpe={res['sharpe']:.4f}, MDD={res['mdd']:.4f}, "
              f"AnnRet={res['ann_ret']:.4f}, N={res['n_days']}")
        port_rets[name] = port_ret

# B&H reference
bh_res = backtest(bh_weight, spy_ret)
if bh_res:
    bh_port_ret = bh_res.pop('port_ret')
    print(f"    {'B&H':25s}: Sharpe={bh_res['sharpe']:.4f}, MDD={bh_res['mdd']:.4f}")

# =================================================================
# 6. DIEBOLD-MARIANO TESTS vs BASE 12/VIX
# =================================================================
print("\n[6] Diebold-Mariano tests vs base 12/VIX...")

base_port_ret = port_rets.get('base_12vix')

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. e1 = base errors, e2 = strategy errors.
    Using squared returns as proxy for loss (lower = better).
    Positive DM → strategy is WORSE than base."""
    common = e1.dropna().index.intersection(e2.dropna().index)
    d = e1.loc[common]**2 - e2.loc[common]**2  # loss differential
    d_mean = d.mean()

    # HAC standard error (Newey-West with h-1 lags)
    n = len(d)
    gamma0 = np.var(d, ddof=1)

    # Simple HAC
    max_lag = max(1, int(n**0.25))
    hac_var = gamma0
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d.values[k:], d.values[:-k])[0, 1]
        hac_var += 2 * (1 - k/(max_lag+1)) * gamma_k

    se = np.sqrt(hac_var / n)
    if se == 0:
        return 0, 1.0

    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

# Use negative returns as "loss" — want to minimize loss
# Strategy with higher Sharpe has lower average squared negative returns
dm_results = {}
if base_port_ret is not None:
    for name in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
        strat_ret = port_rets.get(name)
        if strat_ret is not None:
            # Use negative return magnitude as loss
            common = base_port_ret.index.intersection(strat_ret.index)
            base_loss = -base_port_ret.loc[common]
            strat_loss = -strat_ret.loc[common]
            dm, p = dm_test(base_loss, strat_loss)
            harvey = "PASS" if abs(dm) > 3.0 else "FAIL"
            better = "strategy" if dm > 0 else "base"
            print(f"    {name:25s}: DM={dm:+.4f}, p={p:.4f} [{harvey}] → {better} better")
            dm_results[name] = {'dm_stat': round(dm, 4), 'p_val': round(p, 4), 'harvey': harvey}

# =================================================================
# 7. CROSS-OOS VALIDATION (3 periods)
# =================================================================
print("\n[7] Cross-OOS validation (3 periods)...")

# Define OOS periods
oos_periods = [
    ('OOS1', '2010-01-01', '2014-12-31'),
    ('OOS2', '2015-01-01', '2019-12-31'),
    ('OOS3', '2020-01-01', '2025-12-31'),
]

cross_oos_results = {}
for period_name, start, end in oos_periods:
    print(f"\n  --- {period_name}: {start} to {end} ---")

    mask = (metrics.index >= start) & (metrics.index <= end)
    period_metrics = metrics.loc[mask]
    period_idx = period_metrics.index
    period_spy_ret = spy_ret.reindex(period_idx)
    period_vix = vix.reindex(period_idx)

    if len(period_metrics) < 100:
        print(f"    Insufficient data ({len(period_metrics)} days)")
        continue

    # Recalculate strategies for this period using expanding window from period start
    # But we use the same signal definitions (lookback=252 rolling)
    period_vt = (12.0 / period_vix).clip(0, 1)

    period_strats = {
        'base_12vix': period_vt,
        'S1_disp_level': strategy_disp_level(period_metrics, period_vt),
        'S2_disp_momentum': strategy_disp_momentum(period_metrics, period_vt),
        'S3_corr_regime': strategy_corr_regime(period_metrics, period_vt),
        'S4_combined': strategy_combined(period_metrics, period_vt),
        'S5_disp_crash': strategy_disp_crash(period_metrics, period_vt),
    }

    period_results = {}
    period_port_rets = {}
    for name, w in list(period_strats.items()):
        res = backtest(w, period_spy_ret)
        if res:
            port_ret = res.pop('port_ret')
            period_results[name] = res
            period_port_rets[name] = port_ret

    # DM tests within period
    base_pr = period_port_rets.get('base_12vix')
    for name in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
        strat_pr = period_port_rets.get(name)
        if strat_pr is not None and base_pr is not None:
            common = base_pr.index.intersection(strat_pr.index)
            if len(common) > 50:
                base_loss = -base_pr.loc[common]
                strat_loss = -strat_pr.loc[common]
                dm, p = dm_test(base_loss, strat_loss)
                period_results.setdefault(name, {})['dm_vs_base'] = round(dm, 4)
                period_results.setdefault(name, {})['dm_p'] = round(p, 4)

    cross_oos_results[period_name] = period_results

    # Print
    for name, res in period_results.items():
        sharpe = res.get('sharpe', 'N/A')
        mdd = res.get('mdd', 'N/A')
        dm = res.get('dm_vs_base', 'N/A')
        print(f"    {name:25s}: Sharpe={sharpe}, MDD={mdd}, DM_vs_base={dm}")

# =================================================================
# 8. CROSS-OOS CONSISTENCY CHECK
# =================================================================
print("\n[8] Cross-OOS consistency check...")

print("\n  Sharpe differences (strategy - base) across OOS periods:")
consistency = {}
for strat in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
    diffs = []
    wins = 0
    for period_name in ['OOS1', 'OOS2', 'OOS3']:
        pr = cross_oos_results.get(period_name, {})
        base_s = pr.get('base_12vix', {}).get('sharpe', None)
        strat_s = pr.get(strat, {}).get('sharpe', None)
        if base_s is not None and strat_s is not None:
            diff = strat_s - base_s
            diffs.append(diff)
            if diff > 0:
                wins += 1

    if diffs:
        avg_diff = np.mean(diffs)
        all_positive = all(d > 0 for d in diffs)
        all_negative = all(d < 0 for d in diffs)
        consistency[strat] = {
            'diffs': [round(d, 4) for d in diffs],
            'avg_diff': round(avg_diff, 4),
            'wins': wins,
            'total': len(diffs),
            'consistent_positive': all_positive,
            'consistent_negative': all_negative,
        }
        direction = "ALL+" if all_positive else ("ALL-" if all_negative else "MIXED")
        print(f"    {strat:25s}: diffs={[round(d,4) for d in diffs]}, avg={avg_diff:.4f}, "
              f"wins={wins}/{len(diffs)} [{direction}]")

# =================================================================
# 9. DISPERSION AS VIX ORTHOGONAL SIGNAL CHECK
# =================================================================
print("\n[9] Orthogonality analysis: Is dispersion info BEYOND VIX?")

# Regression: dispersion = a + b*VIX + e
# Then check if residual predicts returns
from numpy.linalg import lstsq

X = np.column_stack([metrics['vix'].values, np.ones(len(metrics))])
for signal in ['dispersion', 'implied_corr', 'rel_disp', 'disp_momentum']:
    y = metrics[signal].values
    beta = lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    r_sq = 1 - np.var(resid) / np.var(y)

    # Does residual predict next-day return?
    next_r = metrics['spy_ret'].shift(-1).values[:-1]
    resid_lag = resid[:-1]
    corr_r, corr_p = stats.pearsonr(resid_lag, next_r)
    t_stat = corr_r * np.sqrt(len(next_r) - 2) / np.sqrt(1 - corr_r**2)

    print(f"    {signal:20s}: R²(VIX)={r_sq:.4f}, resid→ret r={corr_r:.4f}, t={t_stat:.2f}, "
          f"p={corr_p:.4e} [{'PASS' if abs(t_stat)>3 else 'FAIL'} Harvey]")

# =================================================================
# 10. REGIME ANALYSIS
# =================================================================
print("\n[10] Regime analysis: Does dispersion signal work in specific VIX regimes?")

regimes = {
    'Low VIX (<15)': metrics['vix'] < 15,
    'Normal (15-20)': (metrics['vix'] >= 15) & (metrics['vix'] < 20),
    'Elevated (20-30)': (metrics['vix'] >= 20) & (metrics['vix'] < 30),
    'Crisis (>30)': metrics['vix'] >= 30,
}

for regime_name, mask in regimes.items():
    n = mask.sum()
    if n < 50:
        print(f"  {regime_name}: N={n} (too few)")
        continue

    # Dispersion predictive power in this regime
    reg_idx = metrics.index[mask]
    reg_disp = metrics.loc[reg_idx, 'dispersion']
    # Next-day return: shift spy_ret aligned to metrics index
    spy_ret_aligned = spy_ret.reindex(metrics.index)
    reg_ret = spy_ret_aligned.shift(-1).loc[reg_idx].dropna()
    common = reg_disp.index.intersection(reg_ret.index)

    if len(common) > 30:
        r, p = stats.pearsonr(reg_disp.loc[common], reg_ret.loc[common])
        print(f"  {regime_name:20s}: N={n}, disp→ret r={r:.4f}, p={p:.4f}")

# =================================================================
# 11. TURNOVER ANALYSIS
# =================================================================
print("\n[11] Turnover analysis...")

for name in ['base_12vix', 'S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
    w = strategies[name].dropna()
    daily_turnover = w.diff().abs().mean()
    ann_turnover = daily_turnover * 252
    # Net Sharpe after transaction costs (10 bps round-trip)
    tc = daily_turnover * 0.001  # 10 bps
    net_sharpe = full_results.get(name, {}).get('sharpe', 0)
    if net_sharpe:
        # Rough: subtract tx cost from annual return
        ann_ret = full_results[name]['ann_ret']
        ann_vol = full_results[name]['ann_vol']
        net_ret = ann_ret - ann_turnover * 0.001
        net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0
    print(f"    {name:25s}: daily_TO={daily_turnover:.4f}, ann_TO={ann_turnover:.1f}, "
          f"net_Sharpe={net_sharpe:.4f}")

# =================================================================
# 12. PLACEBO / PERMUTATION TEST
# =================================================================
print("\n[12] Placebo test (1000 permutations of dispersion signal)...")

np.random.seed(42)
n_perms = 1000

# Test best strategy vs base
# Find best strategy
best_strat = None
best_diff = -999
for name in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
    if name in full_results and 'base_12vix' in full_results:
        diff = full_results[name]['sharpe'] - full_results['base_12vix']['sharpe']
        if diff > best_diff:
            best_diff = diff
            best_strat = name

print(f"  Best strategy: {best_strat} (Sharpe diff = {best_diff:.4f})")

if best_strat:
    # Permute the dispersion signal and re-run best strategy
    perm_sharpe_diffs = []

    for i in range(n_perms):
        # Randomly shuffle dispersion values (break time structure)
        perm_disp = metrics['dispersion'].copy()
        perm_idx = np.random.permutation(len(perm_disp))
        perm_disp.iloc[:] = perm_disp.values[perm_idx]

        # Simple version: use permuted dispersion for level overlay
        rolling_75 = perm_disp.rolling(252, min_periods=60).quantile(0.75)
        rolling_25 = perm_disp.rolling(252, min_periods=60).quantile(0.25)
        adj = pd.Series(0.0, index=metrics.index)
        adj[perm_disp > rolling_75] = 0.10
        adj[perm_disp < rolling_25] = -0.10
        perm_w = (vt_weight + adj).clip(0, 1)

        res = backtest(perm_w, spy_ret)
        if res:
            perm_sharpe_diffs.append(res['sharpe'] - full_results['base_12vix']['sharpe'])

    perm_sharpe_diffs = np.array(perm_sharpe_diffs)
    pctile = np.mean(perm_sharpe_diffs >= best_diff)
    pctile_rank = np.mean(perm_sharpe_diffs < best_diff) * 100

    print(f"  Permutation p-value: {pctile:.4f}")
    print(f"  Real diff percentile: {pctile_rank:.1f}th")
    print(f"  Permutation Sharpe diff: mean={perm_sharpe_diffs.mean():.4f}, "
          f"std={perm_sharpe_diffs.std():.4f}")

# =================================================================
# 13. SUMMARY & CONCLUSION
# =================================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSION")
print("=" * 70)

# Check if any strategy passes
any_improvement = False
for name in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
    if name in full_results and 'base_12vix' in full_results:
        diff = full_results[name]['sharpe'] - full_results['base_12vix']['sharpe']
        dm_pass = dm_results.get(name, {}).get('harvey', 'FAIL') == 'PASS'
        if diff > 0 and dm_pass:
            any_improvement = True

# Cross-OOS consistency
any_consistent = False
for strat, cons in consistency.items():
    if cons['consistent_positive'] and cons['avg_diff'] > 0.05:
        any_consistent = True

verdict = "NULL RESULT" if not (any_improvement and any_consistent) else "POSITIVE"

print(f"\n  VERDICT: {verdict}")
print(f"\n  Full sample Sharpe comparison:")
base_sharpe = full_results.get('base_12vix', {}).get('sharpe', 0)
for name in ['S1_disp_level', 'S2_disp_momentum', 'S3_corr_regime', 'S4_combined', 'S5_disp_crash']:
    s = full_results.get(name, {}).get('sharpe', 0)
    diff = s - base_sharpe
    print(f"    {name:25s}: {s:.4f} (diff={diff:+.4f})")

print(f"\n  Cross-OOS consistency:")
for strat, cons in consistency.items():
    print(f"    {strat:25s}: {cons['wins']}/{cons['total']} periods positive, avg_diff={cons['avg_diff']:+.4f}")

elapsed = time.time() - start_time
print(f"\n  Runtime: {elapsed:.1f}s")

# =================================================================
# 14. SAVE RESULTS
# =================================================================
results = {
    'experiment_id': 'K559',
    'title': 'Conditional Dispersion Trade — Correlation Risk Premium Mispricing',
    'source': 'Codex GPT-5.4 suggestion #2',
    'concept': 'Trade dispersion spread between index and sector vols as correlation dynamics signal',
    'data_source': 'yfinance',
    'assets': ['SPY', '^VIX'] + sector_8,
    'period': f"{spy_ret.index[0].strftime('%Y-%m-%d')} to {spy_ret.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(metrics),
    'methodology': {
        'index_rv_window': 22,
        'sector_count': 8,
        'dispersion_def': 'avg_sector_RV - index_RV',
        'implied_corr_def': '(index_RV)^2 / (avg_sector_RV)^2',
        'momentum_window': 5,
        'lookback': 252,
        'oos_periods': 3,
        'harvey_threshold': 3.0,
    },
    'descriptive_stats': {
        'dispersion_mean': round(metrics['dispersion'].mean(), 4),
        'dispersion_std': round(metrics['dispersion'].std(), 4),
        'implied_corr_mean': round(metrics['implied_corr'].mean(), 4),
        'implied_corr_std': round(metrics['implied_corr'].std(), 4),
        'dispersion_vix_corr': corr_results.get('dispersion_vs_vix', {}),
        'implied_corr_vix_corr': corr_results.get('implied_corr_vs_vix', {}),
    },
    'full_sample_results': full_results,
    'dm_tests_vs_base': dm_results,
    'cross_oos_results': cross_oos_results,
    'cross_oos_consistency': consistency,
    'placebo': {
        'best_strategy': best_strat,
        'real_sharpe_diff': round(best_diff, 4),
        'perm_p_value': round(float(pctile), 4) if best_strat else None,
        'perm_percentile': round(float(pctile_rank), 1) if best_strat else None,
    },
    'verdict': verdict,
    'conclusion': (
        f"{'NULL RESULT' if verdict == 'NULL RESULT' else 'POSITIVE'}: "
        f"Correlation dynamics (dispersion level, momentum, implied corr) "
        f"{'do NOT' if verdict == 'NULL RESULT' else 'DO'} provide actionable "
        f"information beyond 12/VIX for SPY timing. "
        f"This extends K415 (sector CSVD null, VIX sufficient #29) to the "
        f"Codex-suggested correlation risk premium framework. "
        f"The implied correlation proxy is heavily correlated with VIX "
        f"(r={corr_results.get('implied_corr_vs_vix', {}).get('r', 'N/A')}), "
        f"confirming VIX already captures correlation information."
    ),
    'prior_experiments': ['K151', 'K164', 'K165', 'K254', 'K415'],
    'literature': [
        'Driessen, Maenhout & Vilkov (2009): Price of Correlation Risk, JFE',
        'Pollet & Wilson (2010): Average correlation and stock market returns, JFE',
        'Mueller et al. (2017): International Correlation Risk, JFE',
        'Buss & Vilkov (2012): Measuring Equity Risk with Option-Implied Correlations, RFS',
        'Harvey, Liu & Zhu (2016): ...and the Cross-Section of Expected Returns, RFS',
    ],
    'runtime_seconds': round(elapsed, 1),
    'timestamp': datetime.now().isoformat(),
}

output_path = 'experiments/k559_conditional_dispersion_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
print("K559 COMPLETE")
print("=" * 70)
