"""
K817: VIX→Taiwan Vol Spillover Trading Strategy
================================================================
Tests whether VIX spikes and SPY crashes can be used as signals
to reduce Taiwan equity exposure, exploiting the US→Taiwan spillover
channel identified in T5b (r=0.376, Granger F=58.8).

Key difference from K796v2 and K812:
  - K796v2: Only tested VIX spike overlays on 8.63/VIX base (OTC returns)
    → Full-period Sharpe near zero; spike guards hurt in OTC domain
  - K812: Used close-to-close returns → INVALID (overnight gap artifact,
    Sharpe 3.4 was inflated by capturing untradable overnight moves)
  - K817: Combines VIX level + VIX spike + SPY crash signals with
    OTC returns + cross-OOS validation + spillover timing analysis

Strategies (all trade 0050.TW, open-to-close returns):
  S0: BH 0050.TW (baseline)
  S1: VIX Spike Guard — VIX_{t-1} spike >15% → next day 30% weight, else 100%
  S2: VIX Level Guard — VIX_{t-1} > 25 → 50%, < 15 → 100%, else 75%
  S3: SPY Crash Guard — SPY_{t-1} < -2% → next day 30% weight
  S4: Combined — VIX>25 OR SPY<-2% → 30% weight
  S5: 8.63/VIX (Taiwan VT baseline, smooth weight)

Signal convention:
  - All signals from US market close on day t-1
  - Taiwan trades on day t (open-to-close return only)
  - signal.shift(1) enforced in code

Data:
  - SPY, 0050.TW, ^VIX from yfinance (2006-01-01 to 2026-03-31)
  - 0050.TW cleaned via clean_tw50_data (split artifact fix)
  - Returns: open-to-close = log(Close_t / Open_t) [K812 lesson: NO c2c]
  - If Open unavailable, fall back to close-to-close with explicit warning

TX cost: 5 bps per absolute weight change

References:
  - T5b: SPY→Taiwan spillover r=0.376, Granger F=58.8
  - K796v2: VIX spike on OTC → near-zero Sharpe (no edge)
  - K812: INVALID (c2c overnight gap artifact)
  - K502: 77-93% of lead-lag alpha in overnight gap → NOT tradable
  - Gemini #1: VIX spike >15% → reduce Taiwan exposure

[提出: 用戶(Gemini #1 方向, K796 延伸), 執行: Claude]
Author: VolPred Research System
Date: 2026-04-01
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
from datetime import datetime

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import strategy_dm_test

warnings.filterwarnings('ignore')

print("=" * 70)
print("K817: VIX→Taiwan Vol Spillover Trading Strategy")
print("=" * 70)

# ============================================================
# Parameters
# ============================================================
START_DATE = '2006-01-01'
END_DATE = '2026-03-31'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
TX_COST_BPS = 5  # 5 bps per weight change
LAMBDA_TW = 8.63  # Taiwan VT constant
MAX_WEIGHT = 1.0
MIN_WEIGHT = 0.0

# Signal thresholds
VIX_SPIKE_THRESH = 0.15   # 15% daily VIX change
VIX_HIGH_LEVEL = 25.0     # VIX > 25 = elevated fear
VIX_LOW_LEVEL = 15.0      # VIX < 15 = calm
SPY_CRASH_THRESH = -0.02  # SPY daily return < -2%

# Cross-OOS windows (5 x 2-year non-overlapping)
CROSS_OOS_WINDOWS = [
    ('2006-01-01', '2007-12-31'),
    ('2008-01-01', '2009-12-31'),
    ('2010-01-01', '2011-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2020-01-01', '2021-12-31'),
]

print(f"\nPeriod: {START_DATE} to {END_DATE}")
print(f"OOS: {OOS_START} to {OOS_END}")
print(f"TX cost: {TX_COST_BPS} bps")
print(f"Return type: OPEN-TO-CLOSE (avoiding K812 c2c artifact)")

# ============================================================
# 1. Data Download & Cleaning
# ============================================================
print("\n" + "=" * 70)
print("1. DATA DOWNLOAD & CLEANING")
print("=" * 70)

# --- Download SPY and VIX (US calendar) ---
spy_raw = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy_prices = spy_raw['Close'].squeeze()
spy_returns = spy_prices.pct_change()
print(f"  SPY: {len(spy_prices)} days ({spy_prices.index[0].date()} to {spy_prices.index[-1].date()})")

vix_raw = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].squeeze()
vix_pct_change_us = vix_series.pct_change()
print(f"  ^VIX: {len(vix_series)} days ({vix_series.index[0].date()} to {vix_series.index[-1].date()})")

# --- Download and clean 0050.TW (Taiwan calendar) ---
tw_raw = yf.download('0050.TW', start=START_DATE, end=END_DATE, progress=False)
if isinstance(tw_raw.columns, pd.MultiIndex):
    tw_raw.columns = tw_raw.columns.get_level_values(0)

# Clean Close prices
tw_close_clean, tw_ret_c2c = clean_tw50_data(tw_raw['Close'].copy())

# --- Open-to-close returns ---
# Attempt to use Open prices for OTC calculation
tw_open_raw = tw_raw['Open'].copy()

# Apply same split adjustment to Open as clean_tw50_data does to Close
split_date = pd.Timestamp('2014-01-02')
tw_open_clean = tw_open_raw.copy()
if split_date in tw_close_clean.index and split_date in tw_open_raw.index:
    pre_split_mask = tw_close_clean.index < split_date
    if pre_split_mask.any():
        # Detect if close has the split discontinuity in raw data
        pre_close_dates = tw_raw['Close'].index[tw_raw['Close'].index < split_date]
        if len(pre_close_dates) > 0:
            last_pre_raw = float(tw_raw['Close'].loc[pre_close_dates[-1]])
            first_post_raw = float(tw_raw['Close'].loc[split_date])
            ratio = last_pre_raw / first_post_raw
            if 3.5 < ratio < 4.5:
                # Apply same ratio to Open for pre-split dates
                pre_open_dates = tw_open_raw.index[tw_open_raw.index < split_date]
                tw_open_clean.loc[pre_open_dates] = tw_open_raw.loc[pre_open_dates] / 4.0
                print(f"  Split-adjusted Open for {len(pre_open_dates)} pre-split dates (ratio {ratio:.2f})")

# Compute OTC returns
common_dates = tw_close_clean.index.intersection(tw_open_clean.index)
valid_mask = (tw_open_clean.loc[common_dates] > 0) & (~tw_open_clean.loc[common_dates].isna()) & (~tw_close_clean.loc[common_dates].isna())
common_dates = common_dates[valid_mask]

tw_ret_otc = np.log(tw_close_clean.loc[common_dates] / tw_open_clean.loc[common_dates])
tw_ret_otc = tw_ret_otc.dropna()

# Verify OTC vs C2C
print(f"\n  0050.TW (CLEAN): {len(tw_close_clean)} days")
print(f"  Open-to-close return: {len(tw_ret_otc)} days")
print(f"    OTC mean: {tw_ret_otc.mean()*100:.4f}%/day, std: {tw_ret_otc.std()*100:.4f}%")
print(f"    C2C mean: {tw_ret_c2c.dropna().mean()*100:.4f}%/day, std: {tw_ret_c2c.dropna().std()*100:.4f}%")

otc_available = len(tw_ret_otc) > 1000
if not otc_available:
    print("  WARNING: OTC data insufficient, falling back to C2C returns (RISK: overnight gap artifact)")
    tw_ret_use = tw_ret_c2c.dropna()
    return_type = 'close_to_close_FALLBACK'
else:
    tw_ret_use = tw_ret_otc
    return_type = 'open_to_close'
    print(f"  Using OPEN-TO-CLOSE returns ({len(tw_ret_use)} days)")

# ============================================================
# 2. Build US Signals Aligned to Taiwan Calendar
# ============================================================
print("\n" + "=" * 70)
print("2. SIGNAL ALIGNMENT (US→Taiwan)")
print("=" * 70)

# For each Taiwan trading day, find the most recent US close
tw_dates = sorted(tw_ret_use.index)

# Build aligned US data: for each TW date, latest US data BEFORE that date
aligned_data = pd.DataFrame(index=pd.DatetimeIndex(tw_dates))
aligned_data['tw_ret'] = tw_ret_use

# Forward-fill US data to TW calendar
# Create daily series for VIX, SPY, VIX change
us_data = pd.DataFrame({
    'vix': vix_series,
    'vix_pct_change': vix_pct_change_us,
    'spy_return': spy_returns,
    'spy_price': spy_prices,
})

# Reindex to all calendar days, then ffill, then select TW trading days
all_dates = pd.date_range(START_DATE, END_DATE, freq='D')
us_daily = us_data.reindex(all_dates).ffill()

# For Taiwan day t, the US data available is from t-1 or earlier
# We shift US data by 1 day to enforce the lag
# us_daily.shift(1) at day t = US data from t-1
us_lagged = us_daily.shift(1)

# Align to Taiwan trading days
for col in us_lagged.columns:
    aligned_data[col] = us_lagged[col].reindex(aligned_data.index)

# Drop rows with missing US data
aligned_data = aligned_data.dropna()
print(f"  Aligned dataset: {len(aligned_data)} Taiwan trading days")
print(f"  Date range: {aligned_data.index[0].date()} to {aligned_data.index[-1].date()}")

# ============================================================
# 3. Compute Trading Signals
# ============================================================
print("\n" + "=" * 70)
print("3. TRADING SIGNALS")
print("=" * 70)

# All signals are already lagged by construction (us_daily.shift(1))
# No additional shift needed -- the lag is baked into the alignment

# VIX spike: VIX_{t-1} day-over-day change > 15%
vix_spike = aligned_data['vix_pct_change'] > VIX_SPIKE_THRESH
print(f"  VIX spike (>15%): {vix_spike.sum()} events ({vix_spike.mean()*100:.1f}% of days)")

# VIX level signals
vix_high = aligned_data['vix'] > VIX_HIGH_LEVEL
vix_low = aligned_data['vix'] < VIX_LOW_LEVEL
print(f"  VIX > 25: {vix_high.sum()} days ({vix_high.mean()*100:.1f}%)")
print(f"  VIX < 15: {vix_low.sum()} days ({vix_low.mean()*100:.1f}%)")

# SPY crash: SPY_{t-1} return < -2%
spy_crash = aligned_data['spy_return'] < SPY_CRASH_THRESH
print(f"  SPY crash (<-2%): {spy_crash.sum()} events ({spy_crash.mean()*100:.1f}%)")

# Combined: VIX>25 OR SPY<-2%
combined_signal = vix_high | spy_crash
print(f"  Combined (VIX>25 OR SPY<-2%): {combined_signal.sum()} days ({combined_signal.mean()*100:.1f}%)")

# ============================================================
# 4. Define Strategy Weights
# ============================================================
print("\n" + "=" * 70)
print("4. STRATEGY WEIGHTS")
print("=" * 70)

n = len(aligned_data)

# S0: Buy-and-Hold
w_s0 = pd.Series(1.0, index=aligned_data.index)

# S1: VIX Spike Guard — VIX spike >15% → 30%, else 100%
w_s1 = pd.Series(1.0, index=aligned_data.index)
w_s1[vix_spike] = 0.30

# S2: VIX Level Guard — VIX>25 → 50%, VIX<15 → 100%, else 75%
w_s2 = pd.Series(0.75, index=aligned_data.index)
w_s2[vix_high] = 0.50
w_s2[vix_low] = 1.00

# S3: SPY Crash Guard — SPY<-2% → 30%, else 100%
w_s3 = pd.Series(1.0, index=aligned_data.index)
w_s3[spy_crash] = 0.30

# S4: Combined — VIX>25 OR SPY<-2% → 30%, else 100%
w_s4 = pd.Series(1.0, index=aligned_data.index)
w_s4[combined_signal] = 0.30

# S5: 8.63/VIX (Taiwan VT baseline, smooth weight)
w_s5 = (LAMBDA_TW / aligned_data['vix']).clip(MIN_WEIGHT, MAX_WEIGHT)

strategies = {
    's0': ('BH 0050.TW', w_s0),
    's1': ('VIX Spike Guard (>15%→30%)', w_s1),
    's2': ('VIX Level Guard', w_s2),
    's3': ('SPY Crash Guard (<-2%→30%)', w_s3),
    's4': ('Combined (VIX>25|SPY<-2%→30%)', w_s4),
    's5': ('8.63/VIX Taiwan VT', w_s5),
}

for key, (name, w) in strategies.items():
    turnover = w.diff().abs().sum()
    print(f"  {key} ({name}): mean_w={w.mean():.3f}, turnover={turnover:.1f}")

# ============================================================
# 5. Backtest Function
# ============================================================

def backtest_strategy(weights: pd.Series, returns: pd.Series, tx_bps: float = TX_COST_BPS):
    """Compute strategy returns with TX costs."""
    w = weights.reindex(returns.index).fillna(0)
    r = returns.reindex(returns.index).fillna(0)
    # TX cost on absolute weight change
    dw = w.diff().abs()
    dw.iloc[0] = abs(w.iloc[0])
    tx = dw * tx_bps / 10000
    port_ret = w * r - tx
    return port_ret


def compute_metrics(port_ret: pd.Series, label: str = '') -> dict:
    """Compute annualized performance metrics."""
    port_ret = port_ret.dropna()
    if len(port_ret) < 10:
        return {'sharpe': 0, 'sortino': 0, 'cagr': 0, 'mdd': 0, 'ann_vol': 0,
                'ann_return': 0, 'win_rate': 0, 'n_days': len(port_ret)}

    n = len(port_ret)
    ann = 252

    mean_r = port_ret.mean() * ann
    std_r = port_ret.std() * np.sqrt(ann)
    sharpe = mean_r / std_r if std_r > 0 else 0.0

    downside = port_ret[port_ret < 0].std() * np.sqrt(ann)
    sortino = mean_r / downside if downside > 0 else 0.0

    cum = (1 + port_ret).cumprod()
    years = n / ann
    cagr = float(cum.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0.0

    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = float(drawdown.min())

    win_rate = float((port_ret > 0).mean())
    if label:
        print(f"  {label:<40} Sharpe={sharpe:.4f}  CAGR={cagr*100:.2f}%  "
              f"MDD={mdd*100:.1f}%  Vol={std_r*100:.1f}%")

    return {
        'sharpe': round(sharpe, 4),
        'sortino': round(sortino, 4),
        'cagr': round(cagr, 4),
        'mdd': round(mdd, 4),
        'ann_vol': round(std_r, 4),
        'ann_return': round(mean_r, 4),
        'win_rate': round(win_rate, 4),
        'n_days': n,
    }


# ============================================================
# 6. Full-Period Backtest
# ============================================================
print("\n" + "=" * 70)
print("6. FULL-PERIOD BACKTEST (Open-to-Close)")
print("=" * 70)

tw_ret = aligned_data['tw_ret']
full_results = {}

for key, (name, w) in strategies.items():
    port_ret = backtest_strategy(w, tw_ret)
    m = compute_metrics(port_ret, name)
    full_results[key] = {**m, 'name': name}

# Summary table
print("\n" + "-" * 80)
print(f"{'Strategy':<40} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Sortino':>9}")
print("-" * 80)
for key in strategies:
    m = full_results[key]
    print(f"  {m['name']:<38} {m['sharpe']:>8.4f} {m['cagr']*100:>7.2f}% {m['mdd']*100:>7.1f}% {m['sortino']:>9.4f}")

# ============================================================
# 7. OOS Backtest
# ============================================================
print("\n" + "=" * 70)
print(f"7. OOS BACKTEST ({OOS_START} to {OOS_END})")
print("=" * 70)

oos_mask = (aligned_data.index >= OOS_START) & (aligned_data.index <= OOS_END)
oos_ret = tw_ret[oos_mask]
print(f"  OOS days: {oos_mask.sum()}")

oos_results = {}
for key, (name, w) in strategies.items():
    port_ret = backtest_strategy(w[oos_mask], oos_ret)
    m = compute_metrics(port_ret, f"{name} [OOS]")
    oos_results[key] = {**m, 'name': name}

print("\n" + "-" * 80)
print(f"{'Strategy [OOS]':<40} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Sortino':>9}")
print("-" * 80)
for key in strategies:
    m = oos_results[key]
    print(f"  {m['name']:<38} {m['sharpe']:>8.4f} {m['cagr']*100:>7.2f}% {m['mdd']*100:>7.1f}% {m['sortino']:>9.4f}")

# ============================================================
# 8. DM Tests (Harvey t>3.0)
# ============================================================
print("\n" + "=" * 70)
print("8. DM TESTS (Harvey t>3.0 threshold)")
print("=" * 70)

# Full-period DM tests vs S0 (BH) and vs S5 (8.63/VIX)
dm_results = {'full_vs_bh': {}, 'full_vs_vt': {}, 'oos_vs_bh': {}, 'oos_vs_vt': {}}

ret_s0_full = backtest_strategy(w_s0, tw_ret)
ret_s5_full = backtest_strategy(w_s5, tw_ret)
ret_s0_oos = backtest_strategy(w_s0[oos_mask], oos_ret)
ret_s5_oos = backtest_strategy(w_s5[oos_mask], oos_ret)

for key in ['s1', 's2', 's3', 's4']:
    name = strategies[key][0]
    w = strategies[key][1]

    # Full period vs BH
    r_strat = backtest_strategy(w, tw_ret)
    t_bh, p_bh = strategy_dm_test(ret_s0_full.values, r_strat.values, loss_fn='negative_return')
    dm_results['full_vs_bh'][key] = {
        'name': name,
        't_stat': round(float(t_bh), 4),
        'p_value': round(float(p_bh), 4),
        'harvey_pass': bool(abs(t_bh) > 3.0),
    }
    print(f"  Full {name} vs BH: t={t_bh:.3f} p={p_bh:.4f} {'PASS' if abs(t_bh)>3 else 'FAIL'}")

    # Full period vs 8.63/VIX
    t_vt, p_vt = strategy_dm_test(ret_s5_full.values, r_strat.values, loss_fn='negative_return')
    dm_results['full_vs_vt'][key] = {
        'name': name,
        't_stat': round(float(t_vt), 4),
        'p_value': round(float(p_vt), 4),
        'harvey_pass': bool(abs(t_vt) > 3.0),
    }
    print(f"  Full {name} vs 8.63/VIX: t={t_vt:.3f} p={p_vt:.4f} {'PASS' if abs(t_vt)>3 else 'FAIL'}")

    # OOS vs BH
    r_strat_oos = backtest_strategy(w[oos_mask], oos_ret)
    t_bh_o, p_bh_o = strategy_dm_test(ret_s0_oos.values, r_strat_oos.values, loss_fn='negative_return')
    dm_results['oos_vs_bh'][key] = {
        'name': name,
        't_stat': round(float(t_bh_o), 4),
        'p_value': round(float(p_bh_o), 4),
        'harvey_pass': bool(abs(t_bh_o) > 3.0),
    }
    print(f"  OOS  {name} vs BH: t={t_bh_o:.3f} p={p_bh_o:.4f} {'PASS' if abs(t_bh_o)>3 else 'FAIL'}")

    # OOS vs 8.63/VIX
    t_vt_o, p_vt_o = strategy_dm_test(ret_s5_oos.values, r_strat_oos.values, loss_fn='negative_return')
    dm_results['oos_vs_vt'][key] = {
        'name': name,
        't_stat': round(float(t_vt_o), 4),
        'p_value': round(float(p_vt_o), 4),
        'harvey_pass': bool(abs(t_vt_o) > 3.0),
    }
    print(f"  OOS  {name} vs 8.63/VIX: t={t_vt_o:.3f} p={p_vt_o:.4f} {'PASS' if abs(t_vt_o)>3 else 'FAIL'}")
    print()

# ============================================================
# 9. Cross-OOS Validation (5 x 2-year windows)
# ============================================================
print("\n" + "=" * 70)
print("9. CROSS-OOS VALIDATION (5 x 2-year windows vs BH)")
print("=" * 70)

cross_oos_results = {key: [] for key in ['s1', 's2', 's3', 's4', 's5']}

for window_start, window_end in CROSS_OOS_WINDOWS:
    win_mask = (aligned_data.index >= window_start) & (aligned_data.index <= window_end)
    win_ret = tw_ret[win_mask]
    n_win = win_mask.sum()

    if n_win < 50:
        print(f"  Window {window_start}~{window_end}: SKIP (only {n_win} days)")
        for key in cross_oos_results:
            cross_oos_results[key].append({'window': f"{window_start}~{window_end}", 'skip': True})
        continue

    # BH Sharpe in this window
    bh_port = backtest_strategy(w_s0[win_mask], win_ret)
    bh_m = compute_metrics(bh_port)

    print(f"\n  Window {window_start}~{window_end} ({n_win} days, BH Sharpe={bh_m['sharpe']:.4f}):")

    for key in ['s1', 's2', 's3', 's4', 's5']:
        w = strategies[key][1]
        strat_port = backtest_strategy(w[win_mask], win_ret)
        strat_m = compute_metrics(strat_port)
        beats_bh = strat_m['sharpe'] > bh_m['sharpe']
        print(f"    {strategies[key][0]:<35} Sharpe={strat_m['sharpe']:.4f} {'WIN' if beats_bh else 'LOSE'}")
        cross_oos_results[key].append({
            'window': f"{window_start}~{window_end}",
            'sharpe': strat_m['sharpe'],
            'bh_sharpe': bh_m['sharpe'],
            'beats_bh': beats_bh,
            'n_days': strat_m['n_days'],
        })

# Summary
print("\n  Cross-OOS Win Rate vs BH (need >= 3/5):")
cross_oos_summary = {}
for key in ['s1', 's2', 's3', 's4', 's5']:
    valid = [r for r in cross_oos_results[key] if not r.get('skip', False)]
    wins = sum(1 for r in valid if r.get('beats_bh', False))
    total = len(valid)
    rate = wins / total if total > 0 else 0
    cross_oos_summary[key] = {
        'name': strategies[key][0],
        'wins': wins,
        'total': total,
        'win_rate': round(rate, 2),
        'pass': wins >= 3,
    }
    print(f"    {strategies[key][0]:<35} {wins}/{total} {'PASS' if wins >= 3 else 'FAIL'}")

# ============================================================
# 10. Spillover Timing Analysis
# ============================================================
print("\n" + "=" * 70)
print("10. SPILLOVER TIMING ANALYSIS")
print("=" * 70)

# After a VIX spike (>15%), what is the Taiwan OTC return distribution
# on day t+1 (immediate), t+1~t+3, t+1~t+5?
spillover_analysis = {}

for event_name, event_mask in [
    ('VIX spike >15%', vix_spike),
    ('VIX spike >10%', aligned_data['vix_pct_change'] > 0.10),
    ('SPY crash <-2%', spy_crash),
    ('VIX > 25', vix_high),
    ('Combined signal', combined_signal),
]:
    event_days = aligned_data.index[event_mask]
    if len(event_days) == 0:
        continue

    # Immediate day return (same as signal day in our aligned data)
    immediate_ret = tw_ret.loc[event_days].dropna()

    # Next 3 days cumulative
    cum_3d = []
    cum_5d = []
    for d in event_days:
        pos = aligned_data.index.get_loc(d)
        # Next 3 days (inclusive of signal day + 2 more)
        end_3 = min(pos + 3, len(aligned_data))
        end_5 = min(pos + 5, len(aligned_data))
        if pos < len(tw_ret):
            ret_3d = tw_ret.iloc[pos:end_3].sum()
            ret_5d = tw_ret.iloc[pos:end_5].sum()
            cum_3d.append(ret_3d)
            cum_5d.append(ret_5d)

    cum_3d = np.array(cum_3d)
    cum_5d = np.array(cum_5d)

    # Non-event comparison
    non_event_ret = tw_ret[~event_mask].dropna()

    # T-test: event days vs non-event days
    if len(immediate_ret) >= 5 and len(non_event_ret) >= 5:
        t_stat, p_val = stats.ttest_ind(immediate_ret.values, non_event_ret.values)
    else:
        t_stat, p_val = 0.0, 1.0

    result = {
        'n_events': int(event_mask.sum()),
        'pct_of_days': round(float(event_mask.mean()), 4),
        'immediate': {
            'mean': round(float(immediate_ret.mean()), 6),
            'median': round(float(immediate_ret.median()), 6),
            'std': round(float(immediate_ret.std()), 6),
            'pct_negative': round(float((immediate_ret < 0).mean()), 4),
            'vs_nonevent_t': round(float(t_stat), 4),
            'vs_nonevent_p': round(float(p_val), 4),
        },
        'cum_3d': {
            'mean': round(float(np.mean(cum_3d)), 6) if len(cum_3d) > 0 else None,
            'median': round(float(np.median(cum_3d)), 6) if len(cum_3d) > 0 else None,
            'pct_negative': round(float(np.mean(cum_3d < 0)), 4) if len(cum_3d) > 0 else None,
        },
        'cum_5d': {
            'mean': round(float(np.mean(cum_5d)), 6) if len(cum_5d) > 0 else None,
            'median': round(float(np.median(cum_5d)), 6) if len(cum_5d) > 0 else None,
            'pct_negative': round(float(np.mean(cum_5d < 0)), 4) if len(cum_5d) > 0 else None,
        },
        'non_event_mean': round(float(non_event_ret.mean()), 6),
    }

    spillover_analysis[event_name] = result

    print(f"\n  {event_name} ({result['n_events']} events, {result['pct_of_days']*100:.1f}% of days):")
    print(f"    Immediate OTC: mean={result['immediate']['mean']*100:.4f}%, "
          f"median={result['immediate']['median']*100:.4f}%, "
          f"pct_neg={result['immediate']['pct_negative']*100:.1f}%")
    print(f"    Non-event OTC: mean={result['non_event_mean']*100:.4f}%")
    print(f"    t-test vs non-event: t={result['immediate']['vs_nonevent_t']:.3f}, "
          f"p={result['immediate']['vs_nonevent_p']:.4f}")
    if result['cum_3d']['mean'] is not None:
        print(f"    Cum 3d: mean={result['cum_3d']['mean']*100:.4f}%, "
              f"pct_neg={result['cum_3d']['pct_negative']*100:.1f}%")
    if result['cum_5d']['mean'] is not None:
        print(f"    Cum 5d: mean={result['cum_5d']['mean']*100:.4f}%, "
              f"pct_neg={result['cum_5d']['pct_negative']*100:.1f}%")

# ============================================================
# 11. Threshold Sensitivity Analysis
# ============================================================
print("\n" + "=" * 70)
print("11. THRESHOLD SENSITIVITY")
print("=" * 70)

# VIX spike threshold sensitivity
print("\n  VIX Spike Guard threshold sweep:")
vix_thresh_sensitivity = {}
for thresh in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]:
    flag = aligned_data['vix_pct_change'] > thresh
    w_test = pd.Series(1.0, index=aligned_data.index)
    w_test[flag] = 0.30
    r_test = backtest_strategy(w_test, tw_ret)
    m_test = compute_metrics(r_test)
    n_events = int(flag.sum())
    vix_thresh_sensitivity[f"thresh_{int(thresh*100)}pct"] = {
        'sharpe': m_test['sharpe'],
        'cagr': m_test['cagr'],
        'mdd': m_test['mdd'],
        'n_events': n_events,
    }
    print(f"    ΔVIX>{thresh*100:.0f}%: Sharpe={m_test['sharpe']:.4f} MDD={m_test['mdd']*100:.1f}% "
          f"Events={n_events}")

# SPY crash threshold sensitivity
print("\n  SPY Crash Guard threshold sweep:")
spy_thresh_sensitivity = {}
for thresh in [-0.01, -0.015, -0.02, -0.025, -0.03, -0.04]:
    flag = aligned_data['spy_return'] < thresh
    w_test = pd.Series(1.0, index=aligned_data.index)
    w_test[flag] = 0.30
    r_test = backtest_strategy(w_test, tw_ret)
    m_test = compute_metrics(r_test)
    n_events = int(flag.sum())
    spy_thresh_sensitivity[f"thresh_{int(abs(thresh)*100)}pct"] = {
        'sharpe': m_test['sharpe'],
        'cagr': m_test['cagr'],
        'mdd': m_test['mdd'],
        'n_events': n_events,
    }
    print(f"    SPY<{thresh*100:.1f}%: Sharpe={m_test['sharpe']:.4f} MDD={m_test['mdd']*100:.1f}% "
          f"Events={n_events}")

# VIX level threshold sensitivity
print("\n  VIX Level Guard high-threshold sweep:")
vix_level_sensitivity = {}
for high_thresh in [20, 22, 25, 28, 30, 35]:
    h_flag = aligned_data['vix'] > high_thresh
    l_flag = aligned_data['vix'] < VIX_LOW_LEVEL
    w_test = pd.Series(0.75, index=aligned_data.index)
    w_test[h_flag] = 0.50
    w_test[l_flag] = 1.00
    r_test = backtest_strategy(w_test, tw_ret)
    m_test = compute_metrics(r_test)
    vix_level_sensitivity[f"high_{high_thresh}"] = {
        'sharpe': m_test['sharpe'],
        'cagr': m_test['cagr'],
        'mdd': m_test['mdd'],
        'n_high_days': int(h_flag.sum()),
    }
    print(f"    VIX>{high_thresh}: Sharpe={m_test['sharpe']:.4f} MDD={m_test['mdd']*100:.1f}% "
          f"High days={h_flag.sum()}")

# ============================================================
# 12. K796v2 vs K817 Comparison
# ============================================================
print("\n" + "=" * 70)
print("12. COMPARISON WITH K796v2 RESULTS")
print("=" * 70)

print("\nK796v2 (2009-2024, OTC, TX=0.00186):")
print(f"  Baseline 8.63/VIX: Sharpe=0.0494")
print(f"  Spike Guard (ΔVIX>15%→50%): Sharpe=-0.0077")
print(f"  Spike Binary (ΔVIX>10%→0%): Sharpe=-0.2407")
print(f"  Level Jump (VIX>25→50%x5d): Sharpe=-0.0168")

print(f"\nK817 (2006-2026, OTC, TX=5bps):")
for key in strategies:
    m = full_results[key]
    print(f"  {m['name']:<35} Sharpe={m['sharpe']:.4f}")

print(f"\nK812 (2006-2026, C2C — INVALID, overnight gap artifact):")
print(f"  SPY Return Signal: Sharpe=2.1766 (inflated)")
print(f"  Smooth tanh(SPY):  Sharpe=3.4002 (inflated)")
print(f"  → K817 uses OTC to avoid this artifact")

# ============================================================
# 13. Conclusions
# ============================================================
print("\n" + "=" * 70)
print("13. CONCLUSIONS")
print("=" * 70)

# Find best strategy
best_key = max(full_results, key=lambda k: full_results[k]['sharpe'])
best_name = full_results[best_key]['name']
best_sharpe = full_results[best_key]['sharpe']

print(f"\nBest full-period strategy: {best_name} (Sharpe={best_sharpe:.4f})")
print(f"Best OOS strategy: {max(oos_results, key=lambda k: oos_results[k]['sharpe'])}: "
      f"Sharpe={max(oos_results.values(), key=lambda x: x['sharpe'])['sharpe']:.4f}")

# Key finding
print("\n--- KEY FINDINGS ---")
print("1. All binary spillover strategies (S1-S4) use OTC returns to avoid K812's c2c artifact")
print("2. Spillover timing analysis shows whether VIX/SPY signals predict OTC Taiwan returns")
print("3. Cross-OOS validation checks robustness across different market regimes")

# ============================================================
# 14. Save Results
# ============================================================
results = {
    'experiment_id': 'k817',
    'title': 'K817: VIX→Taiwan Vol Spillover Trading Strategy',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, 0050.TW clean_tw50_data, ^VIX)',
    'return_type': return_type,
    'period': f'{START_DATE} to {END_DATE}',
    'oos_period': f'{OOS_START} to {OOS_END}',
    'n_days': len(aligned_data),
    'tx_cost_bps': TX_COST_BPS,
    'parameters': {
        'lambda_tw': LAMBDA_TW,
        'max_weight': MAX_WEIGHT,
        'vix_spike_thresh': VIX_SPIKE_THRESH,
        'vix_high_level': VIX_HIGH_LEVEL,
        'vix_low_level': VIX_LOW_LEVEL,
        'spy_crash_thresh': SPY_CRASH_THRESH,
    },
    'prior_work': {
        'K796v2': 'VIX spike on OTC → near-zero Sharpe (no edge)',
        'K812': 'INVALID (c2c overnight gap artifact, Sharpe 3.4 inflated)',
        'K502': '77-93% of lead-lag alpha in overnight gap → NOT tradable',
        'T5b': 'SPY→Taiwan spillover r=0.376, Granger F=58.8',
    },
    'signal_events': {
        'vix_spike_15pct': int(vix_spike.sum()),
        'vix_high_25': int(vix_high.sum()),
        'vix_low_15': int(vix_low.sum()),
        'spy_crash_2pct': int(spy_crash.sum()),
        'combined_signal': int(combined_signal.sum()),
    },
    'full_period_metrics': {k: v for k, v in full_results.items()},
    'oos_metrics': {k: v for k, v in oos_results.items()},
    'dm_tests': dm_results,
    'cross_oos': {
        'windows': [f"{s}~{e}" for s, e in CROSS_OOS_WINDOWS],
        'details': {k: v for k, v in cross_oos_results.items()},
        'summary': cross_oos_summary,
    },
    'spillover_timing': spillover_analysis,
    'threshold_sensitivity': {
        'vix_spike': vix_thresh_sensitivity,
        'spy_crash': spy_thresh_sensitivity,
        'vix_level': vix_level_sensitivity,
    },
    'k796v2_comparison': {
        'k796v2_baseline_sharpe': 0.0494,
        'k796v2_spike_guard_sharpe': -0.0077,
        'k796v2_spike_binary_sharpe': -0.2407,
        'k796v2_level_jump_sharpe': -0.0168,
    },
    'conclusions': {
        'best_full_period': {
            'strategy': best_name,
            'sharpe': best_sharpe,
        },
        'key_findings': [
            'OTC returns used to avoid K812 c2c overnight gap artifact',
            'Spillover timing analysis quantifies VIX→Taiwan transmission',
            'Cross-OOS validates robustness across market regimes',
            'Compare binary switching (S1-S4) vs smooth VT (S5)',
        ],
    },
}

out_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k817_vix_taiwan_spillover_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {out_path}")
print("\n" + "=" * 70)
print("K817 COMPLETE")
print("=" * 70)
