"""
K796v2: VIX Spike → Next-Day Taiwan De-Risking (Bar-Timing Fix)
================================================================
Bug fix from K796: original used close-to-close returns, which include the
overnight gap that happened BEFORE the VIX spike signal was available.

Fix applied:
  1. Return calculation: log(Close_t / Open_t)  [open-to-close, intraday only]
     → The strategy can only act AFTER Taiwan opens; overnight gap is NOT
       capturable regardless of the signal.
  2. TX_COST: 0.001 → 0.00186 (actual Taiwan ETF round-trip transaction cost)

Key question: Does Sharpe 1.96 (Spike Binary, full period) survive the fix?

Motivation:
- K628b confirmed SPY → 0050.TW dominant spillover (net transmitter/receiver)
- T5b confirmed Granger causality SPY→Taiwan (F=58.8, p<0.001)
- VIX spike at US close → Taiwan opens lower next day (overnight gap already priced in)
- Open-to-close return = what the strategy can actually capture

Strategies:
  1. Baseline:       8.63/VIX Taiwan VT (standard formula)
  2. Spike Guard:    If ΔVIX_pct > +15% → next day weight = 50% of normal
  3. Spike Binary:   If ΔVIX_pct > +10% → next day weight = 0% (cash)
  4. Level Jump:     If VIX crosses >25 from below → reduce for 5 days to 50%

Signal convention:
  - VIX spike observed at US close on day t
  - Taiwan trades on day t+1 (already enforced by aligning to TW calendar)
  - TX cost: 0.00186 per round-trip weight change (Taiwan ETF actual)

Data:
  - 0050.TW: yfinance + clean_tw50_data (split artifact fix)
  - ^VIX:    yfinance
  - Period:  2009-01-01 to 2024-12-31
  - OOS:     2023-01-01 to 2024-12-31

[提出: 用戶 (bug fix request), 執行: Claude]
References: K796 (original), K502, K628b, T5b
Author: VolPred Research System
Date: 2026-03-31
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
from datetime import datetime

from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

print("=" * 70)
print("K796v2: VIX Spike → Next-Day Taiwan De-Risking (Bar-Timing Fix)")
print("=" * 70)
print("\nFix: close-to-close → open-to-close returns; TX_COST 0.001 → 0.00186")

# ============================================================
# Parameters
# ============================================================
LAMBDA = 8.63          # Taiwan VT constant (from calibrated strategy)
MAX_WEIGHT = 1.5       # Maximum leverage cap
MIN_WEIGHT = 0.0       # Minimum weight (floor)
TX_COST = 0.00186      # FIXED: actual Taiwan ETF round-trip (was 0.001)

SPIKE_GUARD_THRESH = 0.15   # 15% VIX spike → reduce to 50%
SPIKE_BINARY_THRESH = 0.10  # 10% VIX spike → go to cash
LEVEL_JUMP_THRESH = 25.0    # VIX crosses above 25 → reduce for 5 days
LEVEL_GUARD_MULT = 0.50     # Multiplier during spike guard
LEVEL_JUMP_DAYS = 5         # Number of days to reduce after level jump

START_DATE = '2009-01-01'
END_DATE = '2024-12-31'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

# ============================================================
# Data Download
# ============================================================
print(f"\nDownloading data ({START_DATE} to {END_DATE})...")

# VIX — US calendar
vix_raw = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].sort_index()
print(f"  ^VIX: {len(vix_series)} trading days ({vix_series.index[0].date()} to {vix_series.index[-1].date()})")

# 0050.TW — Taiwan calendar (clean split artifact)
# Need Open AND Close prices for open-to-close returns
tw_raw = yf.download('0050.TW', start=START_DATE, end=END_DATE, progress=False)
if isinstance(tw_raw.columns, pd.MultiIndex):
    tw_raw.columns = tw_raw.columns.get_level_values(0)

# Apply split fix to Close prices via clean_tw50_data
tw_prices_clean, _ = clean_tw50_data(tw_raw['Close'].copy())

# Apply same split adjustment ratio to Open prices
# The split on 2025-06-18 (1:4) adjusted Close from 2014-01-02 onwards.
# We need to apply the same adjustment to Open prices.
# Strategy: compute ratio = clean_close / raw_close, apply to raw_open
split_date = pd.Timestamp('2014-01-02')
if split_date in tw_prices_clean.index:
    pre_date = tw_prices_clean.index[tw_prices_clean.index < split_date][-1]
    ratio = float(tw_prices_clean.loc[pre_date]) / float(tw_raw['Close'].loc[pre_date])
    print(f"  Split fix ratio at pre-split: raw/clean = {1/ratio:.2f}")
    # Apply split adjustment to Open
    tw_open_adjusted = tw_raw['Open'].copy()
    # Dates BEFORE split_date are NOT adjusted in the raw data — multiply by ratio
    # (same as what clean_tw50_data does for Close)
    pre_split_dates = tw_raw.index[tw_raw.index < split_date]
    tw_open_adjusted.loc[pre_split_dates] = tw_raw['Open'].loc[pre_split_dates] * ratio
    print(f"  Adjusted Open for {len(pre_split_dates)} pre-split dates")
else:
    # Fallback: no split fix needed (or split_date not in index)
    tw_open_adjusted = tw_raw['Open'].copy()
    print("  Split date not found in index — using raw Open prices")

print(f"  0050.TW (CLEAN Close): {len(tw_prices_clean)} trading days ({tw_prices_clean.index[0].date()} to {tw_prices_clean.index[-1].date()})")

# ============================================================
# Compute open-to-close returns (the FIX)
# ============================================================
# tw_ret_otc[t] = log(Close_t / Open_t)  — intraday return only
# This excludes the overnight gap (Close_{t-1} to Open_t)
# which happens BEFORE the strategy can trade based on VIX signal

# Align Open and Close on same dates
common_price_dates = tw_prices_clean.index.intersection(tw_open_adjusted.index)
tw_close = tw_prices_clean.loc[common_price_dates]
tw_open = tw_open_adjusted.loc[common_price_dates]

# Drop any rows where Open is 0 or NaN (data issues)
valid_mask = (tw_open > 0) & (~tw_open.isna()) & (~tw_close.isna())
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]

tw_ret_otc = np.log(tw_close / tw_open)
tw_ret_otc = tw_ret_otc.dropna()

print(f"\nOpen-to-close return series: {len(tw_ret_otc)} days")
print(f"  Mean: {tw_ret_otc.mean()*100:.4f}%  Std: {tw_ret_otc.std()*100:.4f}%")
print(f"  (Compare: C2C mean was ~0.063% per day)")

# Also compute close-to-close for comparison
_, tw_ret_c2c_clean = clean_tw50_data(tw_raw['Close'].copy())
tw_ret_c2c = tw_ret_c2c_clean.dropna()
print(f"Close-to-close return series: {len(tw_ret_c2c)} days (for comparison)")

# ============================================================
# Build VIX signals aligned to Taiwan trading calendar
# ============================================================
# For each Taiwan trading day t, use the most recent available US VIX close
# (which will be from day t-1 or earlier in US calendar)
# This is the "previous US close" — no lookahead

tw_dates = sorted(tw_ret_otc.index)

# VIX level for each Taiwan day (last US close before TW open)
vix_for_tw = pd.Series(index=pd.DatetimeIndex(tw_dates), dtype=float)
vix_pct_change = pd.Series(index=pd.DatetimeIndex(tw_dates), dtype=float)  # ΔVIX%

for d in tw_dates:
    # Get all VIX observations strictly before Taiwan opens
    mask = vix_series.index < d
    if mask.sum() >= 2:
        recent_vix = vix_series.loc[mask].iloc[-1]
        prev_vix = vix_series.loc[mask].iloc[-2]
        vix_for_tw.loc[d] = recent_vix
        vix_pct_change.loc[d] = (recent_vix - prev_vix) / prev_vix
    elif mask.sum() == 1:
        vix_for_tw.loc[d] = vix_series.loc[mask].iloc[-1]
        vix_pct_change.loc[d] = np.nan
    else:
        vix_for_tw.loc[d] = np.nan
        vix_pct_change.loc[d] = np.nan

vix_for_tw = vix_for_tw.dropna()
vix_pct_change = vix_pct_change.dropna()

print(f"\nVIX-for-Taiwan series: {len(vix_for_tw)} days")

# ============================================================
# Common index: Taiwan dates with valid VIX (open-to-close)
# ============================================================
common_idx = tw_ret_otc.index.intersection(vix_for_tw.index).intersection(vix_pct_change.index)
print(f"Common index (OTC): {len(common_idx)} days ({common_idx[0].date()} to {common_idx[-1].date()})")

tw_ret_aligned = tw_ret_otc.loc[common_idx]
vix_aligned = vix_for_tw.loc[common_idx]
dvix_aligned = vix_pct_change.loc[common_idx]

# Also build C2C aligned for side-by-side comparison
common_idx_c2c = tw_ret_c2c.index.intersection(vix_for_tw.index).intersection(vix_pct_change.index)
tw_ret_c2c_aligned = tw_ret_c2c.loc[common_idx_c2c]
vix_c2c_aligned = vix_for_tw.loc[common_idx_c2c]

# ============================================================
# Strategy weights
# ============================================================
# Strategy 1: Baseline — 8.63/VIX Taiwan VT
base_weight = (LAMBDA / vix_aligned).clip(MIN_WEIGHT, MAX_WEIGHT)
print(f"\nBaseline weight stats: mean={base_weight.mean():.3f}, std={base_weight.std():.3f}")

# Strategy 2: Spike Guard (ΔVIX > +15% → reduce to 50%)
spike_guard_flag = (dvix_aligned > SPIKE_GUARD_THRESH).astype(float)
spike_guard_weight = base_weight * np.where(spike_guard_flag == 1, LEVEL_GUARD_MULT, 1.0)
spike_guard_weight = spike_guard_weight.clip(MIN_WEIGHT, MAX_WEIGHT)

# Strategy 3: Spike Binary (ΔVIX > +10% → cash)
spike_binary_flag = (dvix_aligned > SPIKE_BINARY_THRESH).astype(float)
spike_binary_weight = base_weight * np.where(spike_binary_flag == 1, 0.0, 1.0)
spike_binary_weight = spike_binary_weight.clip(MIN_WEIGHT, MAX_WEIGHT)

# Strategy 4: Level Jump (VIX crosses above 25 → reduce for 5 days)
vix_above = (vix_aligned >= LEVEL_JUMP_THRESH).astype(int)
vix_prev_above = vix_above.shift(1).fillna(0).astype(int)
level_cross_up = ((vix_prev_above == 0) & (vix_above == 1)).astype(int)

level_jump_signal = pd.Series(0, index=common_idx, dtype=float)
for i in range(LEVEL_JUMP_DAYS):
    level_jump_signal = level_jump_signal.add(level_cross_up.shift(i).fillna(0))
level_jump_signal = (level_jump_signal > 0).astype(float)

level_jump_weight = base_weight * np.where(level_jump_signal == 1, LEVEL_GUARD_MULT, 1.0)
level_jump_weight = level_jump_weight.clip(MIN_WEIGHT, MAX_WEIGHT)

print(f"\nSpike guard events (ΔVIX>15%): {spike_guard_flag.sum():.0f} days ({spike_guard_flag.mean()*100:.1f}%)")
print(f"Spike binary events (ΔVIX>10%): {spike_binary_flag.sum():.0f} days ({spike_binary_flag.mean()*100:.1f}%)")
print(f"Level jump events (VIX cross>25): {level_cross_up.sum():.0f} crossings, {level_jump_signal.sum():.0f} reduced days ({level_jump_signal.mean()*100:.1f}%)")

# ============================================================
# Backtest Function with TX costs
# ============================================================
def backtest(weights: pd.Series, returns: pd.Series, tx_cost: float = TX_COST) -> pd.Series:
    """Compute portfolio returns after TX costs based on weight changes."""
    w = weights.reindex(returns.index).fillna(0)
    r = returns.reindex(returns.index).fillna(0)
    # TX cost applied on weight changes
    dw = w.diff().abs().fillna(0)
    port_ret = w * r - dw * tx_cost
    return port_ret


def compute_metrics(port_ret: pd.Series, label: str = '') -> dict:
    """Compute annualized performance metrics."""
    port_ret = port_ret.dropna()
    if len(port_ret) == 0:
        return {}

    n = len(port_ret)
    ann_factor = 252

    mean_r = port_ret.mean() * ann_factor
    std_r = port_ret.std() * np.sqrt(ann_factor)
    sharpe = mean_r / std_r if std_r > 0 else 0.0

    # Sortino
    downside = port_ret[port_ret < 0].std() * np.sqrt(ann_factor)
    sortino = mean_r / downside if downside > 0 else 0.0

    # CAGR
    cum = (1 + port_ret).cumprod()
    years = n / ann_factor
    cagr = float(cum.iloc[-1]) ** (1 / years) - 1

    # MDD
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = float(drawdown.min())

    # Win rate
    win_rate = (port_ret > 0).mean()

    if label:
        print(f"\n{label}:")
        print(f"  Sharpe: {sharpe:.4f}  Sortino: {sortino:.4f}")
        print(f"  CAGR:   {cagr*100:.2f}%  MDD: {mdd*100:.2f}%")
        print(f"  Ann.vol: {std_r*100:.2f}%  Win rate: {win_rate*100:.1f}%")
        print(f"  N days: {n}")

    return {
        'sharpe': round(sharpe, 4),
        'sortino': round(sortino, 4),
        'cagr': round(cagr, 4),
        'mdd': round(mdd, 4),
        'ann_vol': round(std_r, 4),
        'win_rate': round(float(win_rate), 4),
        'n_days': n
    }


# ============================================================
# DM Test (Diebold-Mariano)
# ============================================================
def dm_test(e1: np.ndarray, e2: np.ndarray) -> tuple:
    """
    DM test: H0: equal forecast accuracy.
    Using squared error loss differential: d = e1^2 - e2^2.
    Positive t means e1 > e2 (strategy 2 better than strategy 1).
    """
    d = e1**2 - e2**2
    n = len(d)
    d_mean = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    gamma1 = np.mean((d[1:] - d_mean) * (d[:-1] - d_mean))
    nw_var = (gamma0 + 2 * gamma1) / n
    if nw_var <= 0:
        return 0.0, 1.0
    t_stat = d_mean / np.sqrt(nw_var)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# Full-period backtest (OPEN-TO-CLOSE)
# ============================================================
print("\n" + "=" * 70)
print("FULL PERIOD BACKTEST — OPEN-TO-CLOSE RETURNS (2009-2024)")
print("=" * 70)

port_base = backtest(base_weight, tw_ret_aligned)
port_guard = backtest(spike_guard_weight, tw_ret_aligned)
port_binary = backtest(spike_binary_weight, tw_ret_aligned)
port_jump = backtest(level_jump_weight, tw_ret_aligned)

# Buy-and-hold (open-to-close)
bh_ret = tw_ret_aligned
print(f"\nBuy & Hold 0050.TW (Open-to-Close):")
bh_metrics = compute_metrics(bh_ret, "Buy & Hold 0050.TW (OTC)")

base_metrics = compute_metrics(port_base, "Baseline (8.63/VIX) [OTC]")
guard_metrics = compute_metrics(port_guard, "Spike Guard (ΔVIX>15%→50%) [OTC]")
binary_metrics = compute_metrics(port_binary, "Spike Binary (ΔVIX>10%→0%) [OTC]")
jump_metrics = compute_metrics(port_jump, "Level Jump (VIX>25→50%×5d) [OTC]")

# ============================================================
# OOS backtest
# ============================================================
print("\n" + "=" * 70)
print(f"OOS PERIOD ({OOS_START} to {OOS_END})")
print("=" * 70)

oos_idx = common_idx[(common_idx >= OOS_START) & (common_idx <= OOS_END)]
print(f"OOS days: {len(oos_idx)}")

oos_spike_guard = spike_guard_flag.loc[oos_idx].sum()
oos_spike_binary = spike_binary_flag.loc[oos_idx].sum()
oos_level_jump = level_jump_signal.loc[oos_idx].sum()
oos_level_cross = level_cross_up.loc[oos_idx].sum()

print(f"\nOOS Spike Events:")
print(f"  Spike Guard (ΔVIX>15%): {oos_spike_guard:.0f} days ({oos_spike_guard/len(oos_idx)*100:.1f}%)")
print(f"  Spike Binary (ΔVIX>10%): {oos_spike_binary:.0f} days ({oos_spike_binary/len(oos_idx)*100:.1f}%)")
print(f"  Level Jump crossings:    {oos_level_cross:.0f} events, {oos_level_jump:.0f} reduced days ({oos_level_jump/len(oos_idx)*100:.1f}%)")

port_base_oos = port_base.loc[oos_idx]
port_guard_oos = port_guard.loc[oos_idx]
port_binary_oos = port_binary.loc[oos_idx]
port_jump_oos = port_jump.loc[oos_idx]
bh_oos = bh_ret.loc[oos_idx]

print(f"\nBuy & Hold 0050.TW (OOS, OTC):")
bh_oos_metrics = compute_metrics(bh_oos, "Buy & Hold 0050.TW (OOS, OTC)")
base_oos_metrics = compute_metrics(port_base_oos, "Baseline (OOS, OTC)")
guard_oos_metrics = compute_metrics(port_guard_oos, "Spike Guard (OOS, OTC)")
binary_oos_metrics = compute_metrics(port_binary_oos, "Spike Binary (OOS, OTC)")
jump_oos_metrics = compute_metrics(port_jump_oos, "Level Jump (OOS, OTC)")

# ============================================================
# DM Tests vs Baseline
# ============================================================
print("\n" + "=" * 70)
print("DM TEST vs Baseline (Harvey t>3.0 threshold)")
print("=" * 70)

def dm_vs_baseline(strat_ret, base_ret, label):
    e_base = -base_ret.values
    e_strat = -strat_ret.values
    t, p = dm_test(e_base, e_strat)
    print(f"  {label}: t={t:.3f}, p={p:.4f}, Harvey t>3.0: {'PASS' if abs(t) > 3.0 else 'FAIL'}")
    return {'t_stat': round(t, 4), 'p_value': round(p, 4), 'harvey_pass': bool(abs(t) > 3.0)}

print("\nFull Period:")
dm_guard_full = dm_vs_baseline(port_guard, port_base, "Spike Guard vs Base")
dm_binary_full = dm_vs_baseline(port_binary, port_base, "Spike Binary vs Base")
dm_jump_full = dm_vs_baseline(port_jump, port_base, "Level Jump vs Base")

print("\nOOS Period:")
dm_guard_oos = dm_vs_baseline(port_guard_oos, port_base_oos, "Spike Guard vs Base (OOS)")
dm_binary_oos = dm_vs_baseline(port_binary_oos, port_base_oos, "Spike Binary vs Base (OOS)")
dm_jump_oos = dm_vs_baseline(port_jump_oos, port_base_oos, "Level Jump vs Base (OOS)")

# ============================================================
# Conditional returns on spike days
# ============================================================
print("\n" + "=" * 70)
print("SPIKE EVENT ANALYSIS — Open-to-Close Conditional Returns")
print("=" * 70)

spike_days_15 = dvix_aligned > SPIKE_GUARD_THRESH
spike_days_10 = dvix_aligned > SPIKE_BINARY_THRESH

print(f"\nConditional 0050.TW open-to-close returns on spike-following days:")
print(f"  All days: mean={tw_ret_aligned.mean()*100:.4f}%, std={tw_ret_aligned.std()*100:.4f}%")

for label, flag in [("After ΔVIX>15%", spike_days_15), ("After ΔVIX>10%", spike_days_10)]:
    days_ret = tw_ret_aligned[flag]
    days_ret_no_spike = tw_ret_aligned[~flag]
    t_stat, p_val = stats.ttest_ind(days_ret, days_ret_no_spike)
    print(f"\n  {label}: n={flag.sum():.0f}")
    print(f"    Mean OTC return: {days_ret.mean()*100:.4f}%  (non-spike: {days_ret_no_spike.mean()*100:.4f}%)")
    print(f"    t-stat vs non-spike: {t_stat:.3f}, p={p_val:.4f}")
    print(f"    % negative: {(days_ret < 0).mean()*100:.1f}% (non-spike: {(days_ret_no_spike < 0).mean()*100:.1f}%)")

# ============================================================
# Threshold sensitivity analysis
# ============================================================
print("\n" + "=" * 70)
print("SENSITIVITY: Different ΔVIX thresholds for Spike Guard (OTC)")
print("=" * 70)

thresh_results = {}
for thresh in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
    flag = dvix_aligned > thresh
    w = base_weight * np.where(flag, LEVEL_GUARD_MULT, 1.0)
    w = w.clip(MIN_WEIGHT, MAX_WEIGHT)
    pr = backtest(w, tw_ret_aligned)
    m = compute_metrics(pr)
    n_events = int(flag.sum())
    print(f"  Thresh {thresh*100:.0f}%: Sharpe={m['sharpe']:.4f}, MDD={m['mdd']*100:.1f}%, N_events={n_events}")
    thresh_results[f"thresh_{thresh*100:.0f}pct"] = {'sharpe': m['sharpe'], 'mdd': m['mdd'], 'n_events': n_events}

# ============================================================
# Comparison: K796 (C2C) vs K796v2 (OTC)
# ============================================================
print("\n" + "=" * 70)
print("COMPARISON: K796 (Close-to-Close) vs K796v2 (Open-to-Close)")
print("=" * 70)
print("Original K796 results (from k796_results.json):")
print(f"  Baseline:     Sharpe=1.1371, MDD=-13.7%, CAGR=9.39%")
print(f"  Spike Guard:  Sharpe=1.3643, MDD=-13.1%, CAGR=11.13%")
print(f"  Spike Binary: Sharpe=1.9562, MDD= -9.9%, CAGR=15.81%  ← KEY NUMBER")
print(f"  Level Jump:   Sharpe=1.1059, MDD=-13.9%, CAGR=8.81%")
print(f"  (TX_COST=0.001)")
print()
print("K796v2 results (Open-to-Close, TX_COST=0.00186):")
for label, m in [
    ("Buy & Hold (OTC)", bh_metrics),
    ("Baseline (OTC)", base_metrics),
    ("Spike Guard (OTC)", guard_metrics),
    ("Spike Binary (OTC)", binary_metrics),
    ("Level Jump (OTC)", jump_metrics),
]:
    print(f"  {label:<30} Sharpe={m['sharpe']:.4f}, MDD={m['mdd']*100:.1f}%, CAGR={m['cagr']*100:.2f}%")

# ============================================================
# Summary tables
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY TABLE (Full Period, Open-to-Close)")
print("=" * 70)
print(f"{'Strategy':<35} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8} {'Sortino':>8}")
print("-" * 70)
for label, m in [
    ("Buy & Hold 0050.TW (OTC)", bh_metrics),
    ("1. Baseline (8.63/VIX)", base_metrics),
    ("2. Spike Guard (ΔVIX>15%→50%)", guard_metrics),
    ("3. Spike Binary (ΔVIX>10%→0%)", binary_metrics),
    ("4. Level Jump (VIX>25→50%×5d)", jump_metrics),
]:
    print(f"{label:<35} {m['sharpe']:>8.4f} {m['mdd']*100:>7.1f}% {m['cagr']*100:>7.2f}% {m['sortino']:>8.4f}")

print("\n" + "=" * 70)
print("SUMMARY TABLE (OOS 2023-2024, Open-to-Close)")
print("=" * 70)
print(f"{'Strategy':<35} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8} {'Sortino':>8}")
print("-" * 70)
for label, m in [
    ("Buy & Hold 0050.TW (OTC)", bh_oos_metrics),
    ("1. Baseline (8.63/VIX)", base_oos_metrics),
    ("2. Spike Guard (ΔVIX>15%→50%)", guard_oos_metrics),
    ("3. Spike Binary (ΔVIX>10%→0%)", binary_oos_metrics),
    ("4. Level Jump (VIX>25→50%×5d)", jump_oos_metrics),
]:
    print(f"{label:<35} {m['sharpe']:>8.4f} {m['mdd']*100:>7.1f}% {m['cagr']*100:>7.2f}% {m['sortino']:>8.4f}")

# ============================================================
# Save Results
# ============================================================
results = {
    'experiment_id': 'k796v2',
    'title': 'K796v2: VIX Spike → Next-Day Taiwan De-Risking (Bar-Timing Fix)',
    'bug_fix': {
        'original': 'K796 used close-to-close returns — includes overnight gap before VIX signal available',
        'fixed': 'K796v2 uses open-to-close returns — only captures intraday move after Taiwan opens',
        'tx_cost_original': 0.001,
        'tx_cost_fixed': 0.00186,
        'description': 'Open-to-close return = log(Close_t / Open_t), not log(Close_t / Close_{t-1})'
    },
    'data_source': 'yfinance (0050.TW clean_tw50_data Open+Close, ^VIX)',
    'period_full': {'start': START_DATE, 'end': END_DATE},
    'period_oos': {'start': OOS_START, 'end': OOS_END},
    'n_days_full': int(len(common_idx)),
    'n_days_oos': int(len(oos_idx)),
    'parameters': {
        'lambda': LAMBDA,
        'max_weight': MAX_WEIGHT,
        'tx_cost': TX_COST,
        'spike_guard_thresh': SPIKE_GUARD_THRESH,
        'spike_binary_thresh': SPIKE_BINARY_THRESH,
        'level_jump_thresh': LEVEL_JUMP_THRESH,
        'level_guard_mult': LEVEL_GUARD_MULT,
        'level_jump_days': LEVEL_JUMP_DAYS,
        'return_type': 'open_to_close',
    },
    'spike_events': {
        'full_spike_guard_days': int(spike_guard_flag.sum()),
        'full_spike_guard_pct': round(float(spike_guard_flag.mean()), 4),
        'full_spike_binary_days': int(spike_binary_flag.sum()),
        'full_spike_binary_pct': round(float(spike_binary_flag.mean()), 4),
        'full_level_crossings': int(level_cross_up.sum()),
        'full_level_reduced_days': int(level_jump_signal.sum()),
        'oos_spike_guard_days': int(oos_spike_guard),
        'oos_spike_binary_days': int(oos_spike_binary),
        'oos_level_crossings': int(oos_level_cross),
        'oos_level_reduced_days': int(oos_level_jump),
    },
    'conditional_returns_otc': {
        'all_days_mean': round(float(tw_ret_aligned.mean()), 6),
        'spike_15pct_mean': round(float(tw_ret_aligned[spike_days_15].mean()), 6),
        'spike_15pct_pct_negative': round(float((tw_ret_aligned[spike_days_15] < 0).mean()), 4),
        'spike_10pct_mean': round(float(tw_ret_aligned[spike_days_10].mean()), 6),
        'spike_10pct_pct_negative': round(float((tw_ret_aligned[spike_days_10] < 0).mean()), 4),
    },
    'k796_original_for_comparison': {
        'return_type': 'close_to_close',
        'tx_cost': 0.001,
        'baseline_sharpe': 1.1371,
        'spike_guard_sharpe': 1.3643,
        'spike_binary_sharpe': 1.9562,
        'level_jump_sharpe': 1.1059,
    },
    'full_period_metrics': {
        'buy_hold': bh_metrics,
        'baseline': base_metrics,
        'spike_guard': guard_metrics,
        'spike_binary': binary_metrics,
        'level_jump': jump_metrics,
    },
    'oos_metrics': {
        'buy_hold': bh_oos_metrics,
        'baseline': base_oos_metrics,
        'spike_guard': guard_oos_metrics,
        'spike_binary': binary_oos_metrics,
        'level_jump': jump_oos_metrics,
    },
    'dm_tests': {
        'full_period': {
            'guard_vs_base': dm_guard_full,
            'binary_vs_base': dm_binary_full,
            'jump_vs_base': dm_jump_full,
        },
        'oos': {
            'guard_vs_base': dm_guard_oos,
            'binary_vs_base': dm_binary_oos,
            'jump_vs_base': dm_jump_oos,
        }
    },
    'threshold_sensitivity': thresh_results,
    'timestamp': datetime.now().isoformat(),
}

out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a2179745/experiments/k796v2_vix_spike_taiwan_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {out_path}")
print("\nK796v2 COMPLETE")
