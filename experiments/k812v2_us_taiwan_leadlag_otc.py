"""
K812v2: US→Taiwan Lead-Lag — Open-to-Close, Correct Calendar Alignment
==========================================================================
Fixes 3 HIGH bugs from K812 (Codex review):

BUG 1 — Mixed calendar shift(1):
  K812 stacked SPY onto Taiwan calendar via ffill, then shift(1).
  After a Taiwan holiday the "most recent" SPY return could be stale
  and the shift counted wrong calendar days.
  FIX: merge on date, explicitly map SPY_{t-1 US trading day} to
  TW date t. ffill for TW holidays only touches the signal column,
  and the lag is guaranteed to be ≥ 1 US trading day.

BUG 2 — Sanity check hard-coded:
  K812 wrote `lookahead_sharpe: 1.938` etc. as literals.
  FIX: actually compute shift(0) vs shift(1) and report both.

BUG 3 — Close-to-close return captures untradable overnight gap:
  K502 already showed 77-93 % of lead-lag alpha is in the overnight gap.
  Using close-to-close inflates performance with unrealisable return.
  FIX: use open-to-close intraday return:
    r_otc = (close_t − open_t) / open_t

Strategies (trade 0050.TW):
  S0: Buy-and-Hold 0050.TW (baseline)
  S4: Smooth tanh(SPY_{t-1}) — continuous weight
  S5: 8.63/VIX (Taiwan VT baseline)

Data: yfinance (SPY, 0050.TW, ^VIX), 2006-2026
OOS: 2023-01-01 ~ 2024-12-31
TX cost: 5 bps per weight change

Expected result: NULL (I8 already showed SPY Momentum o2c FAIL).
But this is a *clean* NULL — no calendar bug, no untradable gap.

References:
  - K812: Original lead-lag (3 HIGH bugs)
  - K502: 77-93 % of lead-lag in overnight gap
  - T32/T33: SPY→Taiwan r=0.376, Harvey t=3.75
  - U5: DeltaLag SPY→TW50 rolling corr mean=0.41
  - I8: SPY Momentum o2c FAIL

[提出: Codex(bug review) + 用戶(K812 fix), 執行: Claude]
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

# ============================================================
# 1. Data Download & Cleaning
# ============================================================
print("=" * 70)
print("K812v2: US→Taiwan Lead-Lag — Open-to-Close, Correct Calendar")
print("=" * 70)

start_date = '2006-01-01'
end_date = '2026-04-01'
oos_start = '2023-01-01'
oos_end = '2024-12-31'
TX_COST_BPS = 5  # 5 basis points per weight change

print(f"\nDownloading data: {start_date} to {end_date}")
print(f"OOS period: {oos_start} to {oos_end}")
print(f"TX cost: {TX_COST_BPS} bps")

# --- Download SPY and VIX (US calendar) ---
raw_us = {}
for name, ticker in [('SPY', 'SPY'), ('VIX', '^VIX')]:
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_us[name] = df[['Close']].rename(columns={'Close': f'{name}_close'})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

spy_df = raw_us['SPY'].copy()
spy_df['SPY_return'] = spy_df['SPY_close'].pct_change()
vix_df = raw_us['VIX'].copy()

# Merge SPY + VIX on US calendar
us_df = spy_df.join(vix_df, how='outer')
us_df.index.name = 'date'

# --- Download 0050.TW (Taiwan calendar) — need Open + Close ---
tw_raw = yf.download('0050.TW', start=start_date, end=end_date, progress=False)
if isinstance(tw_raw.columns, pd.MultiIndex):
    tw_raw.columns = tw_raw.columns.get_level_values(0)

tw_close_raw = tw_raw['Close'].squeeze()
tw_open_raw = tw_raw['Open'].squeeze()

# Apply split fix to Close prices
tw_close_clean, _ = clean_tw50_data(tw_close_raw)

# Apply same split fix to Open prices
# We need to replicate the logic: divide pre-2014 prices by 4
_TW50_SPLIT_DATE = "2014-01-02"
_TW50_SPLIT_RATIO = 4.0
tw_open_clean = tw_open_raw.copy()
split_date = pd.Timestamp(_TW50_SPLIT_DATE)
if split_date in tw_open_clean.index:
    pre_split_mask = tw_open_clean.index < split_date
    if pre_split_mask.any():
        last_pre = tw_open_clean[pre_split_mask].iloc[-1]
        first_post = tw_open_clean.loc[split_date]
        ratio = last_pre / first_post
        if 3.5 < ratio < 4.5:
            tw_open_clean[pre_split_mask] = tw_open_clean[pre_split_mask] / _TW50_SPLIT_RATIO
            print(f"  0050.TW Open: split fix applied (pre/post ratio was {ratio:.2f})")

# Handle Open=0 or NaN in 0050.TW
open_bad = (tw_open_clean <= 0) | tw_open_clean.isna()
if open_bad.any():
    n_bad = open_bad.sum()
    print(f"  WARNING: {n_bad} bad Open prices detected, replacing with Close")
    tw_open_clean[open_bad] = tw_close_clean[open_bad]

# Compute open-to-close return: r = (close - open) / open
tw_otc_return = (tw_close_clean - tw_open_clean) / tw_open_clean

# Also compute close-to-close for comparison
tw_c2c_return = tw_close_clean.pct_change()

# Handle extreme returns from split artifacts
for ret_series in [tw_otc_return, tw_c2c_return]:
    extreme = ret_series.abs() > 0.50
    if extreme.any():
        ret_series[extreme] = 0.0

print(f"  0050.TW (CLEAN): {len(tw_close_clean)} days "
      f"({tw_close_clean.index[0].date()} to {tw_close_clean.index[-1].date()})")

# Verify split fix
if split_date in tw_close_clean.index:
    pre_date = tw_close_clean.index[tw_close_clean.index < split_date][-1]
    pre_clean = float(tw_close_clean.loc[pre_date])
    post_clean = float(tw_close_clean.loc[split_date])
    ratio = pre_clean / post_clean
    print(f"  Split fix check (Close): pre/post ratio = {ratio:.2f} (should be ~1.0)")
    if abs(ratio - 1.0) > 0.1:
        print("  WARNING: Split fix may have failed!")

# Return comparison
print(f"\n--- Return Type Comparison ---")
otc_mean = tw_otc_return.dropna().mean() * 252
otc_std = tw_otc_return.dropna().std() * np.sqrt(252)
c2c_mean = tw_c2c_return.dropna().mean() * 252
c2c_std = tw_c2c_return.dropna().std() * np.sqrt(252)
print(f"  Open-to-Close:  mean={otc_mean:.4f}, vol={otc_std:.4f}")
print(f"  Close-to-Close: mean={c2c_mean:.4f}, vol={c2c_std:.4f}")
print(f"  OtC / CtC mean ratio: {otc_mean / c2c_mean:.2f}" if c2c_mean != 0 else "")

# ============================================================
# 2. Cross-Market Calendar Alignment (FIX for BUG 1)
# ============================================================
print("\n--- Cross-Market Calendar Alignment (FIX: merge on date) ---")

# Build Taiwan trading day DataFrame
tw_df = pd.DataFrame({
    'tw_close': tw_close_clean,
    'tw_open': tw_open_clean,
    'tw_otc_return': tw_otc_return,
    'tw_c2c_return': tw_c2c_return,
})
tw_df.index.name = 'date'

# For each Taiwan trading day t, we need the LAST US trading day's data.
# Correct method:
#   1. Build US data with its own calendar
#   2. For each TW date, find the most recent US date < TW date
#   3. This naturally handles TW holidays (no US data gets "skipped")

# Create the signal: SPY return and VIX from the PREVIOUS US trading day
# relative to each Taiwan trading day.

# All dates in the union
all_dates = tw_df.index.sort_values()

# For each TW date, find the most recent US date strictly BEFORE it.
# Because of timezone: US t closes ~05:00 UTC+8 on day t+1,
# Taiwan t opens ~09:00 UTC+8 on day t.
# So for TW date t, the most recent completed US session is:
#   - If US traded on t-1: use t-1
#   - If US was closed on t-1 (weekend/holiday): use last US trading day before t
# This is equivalent to: forward-fill US data, then look up TW date.

# Build a continuous calendar version of US data (ffill across US holidays/weekends)
us_signal = us_df[['SPY_return', 'VIX_close']].copy()
# Reindex to daily calendar and ffill
daily_idx = pd.date_range(start=us_signal.index.min(), end=us_signal.index.max(), freq='B')
us_signal_daily = us_signal.reindex(daily_idx).ffill()

# For the lag: we want SPY_{t-1} signal for TW trade on day t.
# The "natural" timezone lag already gives us ~1 day:
#   US closes on calendar day d (evening US time = early morning d+1 Asia time)
#   TW opens on calendar day d+1
# So looking up us_signal_daily on (TW_date - 1 business day) gives SPY close from
# the most recent US session before TW open.

# Method: shift the US signal forward by 1 day (so date d contains d-1's data)
us_signal_lagged = us_signal_daily.shift(1)  # date d now has SPY data from d-1
us_signal_lagged.columns = ['spy_ret_signal', 'vix_signal']

# Merge onto Taiwan calendar
combined = tw_df.join(us_signal_lagged, how='left')

# Forward-fill any remaining NaN in signals (e.g., TW trading day where
# no US data exists yet due to calendar edge)
combined['spy_ret_signal'] = combined['spy_ret_signal'].ffill()
combined['vix_signal'] = combined['vix_signal'].ffill()

# Drop rows without valid signals
combined = combined.dropna(subset=['spy_ret_signal', 'vix_signal', 'tw_otc_return'])

print(f"  Combined dataset: {len(combined)} Taiwan trading days")
print(f"  Date range: {combined.index[0].date()} to {combined.index[-1].date()}")

# Verify: count how many unique SPY return values vs Taiwan days
n_unique_signal = combined['spy_ret_signal'].nunique()
print(f"  Unique SPY signal values: {n_unique_signal} (should be < TW days due to ffill on TW holidays)")

# ============================================================
# 3. Sanity Check: shift(0) vs shift(1) (FIX for BUG 2)
# ============================================================
print("\n--- Sanity Check: Lookahead Detection (COMPUTED, not hard-coded) ---")

# Build a shift(0) version: same-day SPY signal (lookahead / not available at TW open)
us_signal_shift0 = us_signal_daily.copy()
us_signal_shift0.columns = ['spy_ret_signal_s0lag', 'vix_signal_s0lag']
combined_sanity = tw_df.join(us_signal_shift0, how='left')
combined_sanity['spy_ret_signal_s0lag'] = combined_sanity['spy_ret_signal_s0lag'].ffill()
combined_sanity['vix_signal_s0lag'] = combined_sanity['vix_signal_s0lag'].ffill()
combined_sanity = combined_sanity.dropna(subset=['spy_ret_signal_s0lag', 'tw_otc_return'])

# Compute Sharpe for shift(0) = lookahead
spy_std_s0 = combined_sanity['spy_ret_signal_s0lag'].rolling(60).std()
w_lookahead = 0.5 + 0.5 * np.tanh(combined_sanity['spy_ret_signal_s0lag'] / spy_std_s0)
ret_lookahead = w_lookahead * combined_sanity['tw_otc_return']
ret_lookahead = ret_lookahead.dropna()
lookahead_sharpe = float(ret_lookahead.mean() / ret_lookahead.std() * np.sqrt(252)) if ret_lookahead.std() > 0 else 0.0

# Compute Sharpe for shift(1) = correct lag
spy_ret_std = combined['spy_ret_signal'].rolling(60).std()
w_correct = 0.5 + 0.5 * np.tanh(combined['spy_ret_signal'] / spy_ret_std)
ret_correct = w_correct * combined['tw_otc_return']
ret_correct = ret_correct.dropna()
correct_lag_sharpe = float(ret_correct.mean() / ret_correct.std() * np.sqrt(252)) if ret_correct.std() > 0 else 0.0

# Random baseline: shuffle signal 1000 times
rng = np.random.default_rng(42)
tw_rets_arr = combined['tw_otc_return'].values
spy_sig_arr = combined['spy_ret_signal'].values
spy_std_arr = spy_ret_std.values
valid_mask = np.isfinite(spy_sig_arr) & np.isfinite(spy_std_arr) & (spy_std_arr > 0) & np.isfinite(tw_rets_arr)
tw_valid = tw_rets_arr[valid_mask]
spy_sig_valid = spy_sig_arr[valid_mask]
spy_std_valid = spy_std_arr[valid_mask]

random_sharpes = []
for _ in range(1000):
    perm = rng.permutation(len(spy_sig_valid))
    w_rand = 0.5 + 0.5 * np.tanh(spy_sig_valid[perm] / spy_std_valid)
    ret_rand = w_rand * tw_valid
    s = ret_rand.mean() / ret_rand.std() * np.sqrt(252) if ret_rand.std() > 0 else 0
    random_sharpes.append(s)
random_sharpes = np.array(random_sharpes)
random_mean = float(random_sharpes.mean())
random_std = float(random_sharpes.std())
z_score = (correct_lag_sharpe - random_mean) / random_std if random_std > 0 else 0.0

print(f"  Lookahead (shift=0) Sharpe:  {lookahead_sharpe:.4f}")
print(f"  Correct lag (shift=1) Sharpe: {correct_lag_sharpe:.4f}")
print(f"  Random baseline Sharpe:       {random_mean:.4f} ± {random_std:.4f}")
print(f"  Z-score vs random:            {z_score:.2f}")
if lookahead_sharpe > correct_lag_sharpe * 1.5:
    print("  ⚠️ WARNING: Lookahead Sharpe >> correct lag — possible residual bug!")
elif correct_lag_sharpe > lookahead_sharpe * 1.5:
    print("  ⚠️ NOTE: Correct lag >> lookahead — unusual, investigate")
else:
    print("  ✓ Lookahead and correct lag in similar range — lag structure plausible")

sanity_results = {
    'lookahead_sharpe': round(lookahead_sharpe, 4),
    'correct_lag_sharpe': round(correct_lag_sharpe, 4),
    'random_baseline_mean': round(random_mean, 4),
    'random_baseline_std': round(random_std, 4),
    'z_score_vs_random': round(z_score, 2),
    'computed_not_hardcoded': True,
}

# ============================================================
# 4. Compute Signals for Strategies
# ============================================================
print("\n--- Computing Strategy Signals ---")

# Rolling std for smooth strategy (already lagged via the signal construction)
combined['spy_ret_std'] = combined['spy_ret_signal'].rolling(60).std()

# Drop NaN from rolling window
combined = combined.dropna(subset=['spy_ret_std'])
print(f"  After signal computation: {len(combined)} days")

# ============================================================
# 5. Define Strategies
# ============================================================
print("\n--- Defining Strategies ---")


def compute_tx_cost(weights: pd.Series, cost_bps: float = TX_COST_BPS) -> pd.Series:
    """Compute transaction cost from weight changes."""
    weight_changes = weights.diff().abs()
    weight_changes.iloc[0] = abs(weights.iloc[0])  # initial position
    return weight_changes * cost_bps / 10000


# S0: Buy-and-Hold 0050.TW (baseline) — uses open-to-close return
combined['w_s0'] = 1.0

# S4: Smooth — weight = 0.5 + 0.5 × tanh(SPY_return_{t-1} / σ)
# Signal is already lagged by construction (us_signal_daily.shift(1))
combined['w_s4'] = 0.5 + 0.5 * np.tanh(
    combined['spy_ret_signal'] / combined['spy_ret_std']
)

# S5: Taiwan VT baseline (8.63/VIX, capped [0.2, 1.0])
# VIX signal is already lagged by construction
combined['w_s5'] = (8.63 / combined['vix_signal']).clip(0.2, 1.0)

strategy_names = {
    's0': 'BH 0050.TW',
    's4': 'Smooth tanh(SPY)',
    's5': '8.63/VIX Taiwan VT',
}

# ============================================================
# 6. Compute Strategy Returns (open-to-close, with TX costs)
# ============================================================
print("\n--- Computing Strategy Returns (Open-to-Close) ---")

for s_key in strategy_names:
    w_col = f'w_{s_key}'
    tx = compute_tx_cost(combined[w_col])
    # FIX BUG 3: use open-to-close return, not close-to-close
    combined[f'ret_otc_{s_key}'] = combined[w_col] * combined['tw_otc_return'] - tx
    # Also compute close-to-close for comparison (to show the bug's impact)
    combined[f'ret_c2c_{s_key}'] = combined[w_col] * combined['tw_c2c_return'] - tx

# ============================================================
# 7. Direction Accuracy Analysis
# ============================================================
print("\n--- Direction Accuracy Analysis ---")

spy_up = combined['spy_ret_signal'] > 0
spy_down = combined['spy_ret_signal'] <= 0
tw_up_otc = combined['tw_otc_return'] > 0
tw_up_c2c = combined['tw_c2c_return'] > 0

# OtC direction accuracy
dir_acc_up_otc = tw_up_otc[spy_up].mean()
dir_acc_down_otc = (~tw_up_otc)[spy_down].mean()
overall_dir_otc = ((spy_up & tw_up_otc) | (spy_down & ~tw_up_otc)).mean()

# C2C direction accuracy (for comparison)
dir_acc_up_c2c = tw_up_c2c[spy_up].mean()
dir_acc_down_c2c = (~tw_up_c2c)[spy_down].mean()
overall_dir_c2c = ((spy_up & tw_up_c2c) | (spy_down & ~tw_up_c2c)).mean()

print(f"  {'Metric':<35} {'OtC':>8} {'C2C':>8}")
print(f"  {'-'*55}")
print(f"  {'SPY up → TW50 up':<35} {dir_acc_up_otc:>8.3f} {dir_acc_up_c2c:>8.3f}")
print(f"  {'SPY down → TW50 down':<35} {dir_acc_down_otc:>8.3f} {dir_acc_down_c2c:>8.3f}")
print(f"  {'Overall direction accuracy':<35} {overall_dir_otc:>8.3f} {overall_dir_c2c:>8.3f}")
print(f"  SPY up days: {spy_up.sum()}, SPY down days: {spy_down.sum()}")

# Conditional return analysis (OtC)
mean_tw_otc_up = combined.loc[spy_up, 'tw_otc_return'].mean() * 252
mean_tw_otc_down = combined.loc[spy_down, 'tw_otc_return'].mean() * 252
t_diff, p_diff = stats.ttest_ind(
    combined.loc[spy_up, 'tw_otc_return'].values,
    combined.loc[spy_down, 'tw_otc_return'].values,
)
print(f"\n  Mean TW OtC ret when SPY up:   {mean_tw_otc_up:.4f} (ann.)")
print(f"  Mean TW OtC ret when SPY down: {mean_tw_otc_down:.4f} (ann.)")
print(f"  Difference t-stat: {t_diff:.3f} (p={p_diff:.4f})")

# ============================================================
# 8. Performance Comparison: OtC vs C2C (shows BUG 3 impact)
# ============================================================
print("\n--- Performance: OtC vs C2C (shows BUG 3 impact) ---")
print(f"  {'Strategy':<25} {'OtC Sharpe':>11} {'C2C Sharpe':>11} {'Δ':>8}")
print(f"  {'-'*58}")

otc_vs_c2c = {}
for s_key, s_name in strategy_names.items():
    otc_rets = combined[f'ret_otc_{s_key}'].dropna()
    c2c_rets = combined[f'ret_c2c_{s_key}'].dropna()

    otc_sharpe = otc_rets.mean() / otc_rets.std() * np.sqrt(252) if otc_rets.std() > 0 else 0
    c2c_sharpe = c2c_rets.mean() / c2c_rets.std() * np.sqrt(252) if c2c_rets.std() > 0 else 0
    delta = c2c_sharpe - otc_sharpe

    print(f"  {s_name:<25} {otc_sharpe:>11.4f} {c2c_sharpe:>11.4f} {delta:>+8.4f}")

    otc_vs_c2c[s_key] = {
        'name': s_name,
        'otc_sharpe': round(float(otc_sharpe), 4),
        'c2c_sharpe': round(float(c2c_sharpe), 4),
        'delta': round(float(delta), 4),
    }

# ============================================================
# 9. Full-Sample Performance (OtC)
# ============================================================
print(f"\n--- Full-Sample Performance (Open-to-Close) ---")
print(f"  {'Strategy':<25} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Vol':>8} {'Turnover':>8}")
print(f"  {'-'*68}")

full_results = {}
for s_key, s_name in strategy_names.items():
    ret_col = f'ret_otc_{s_key}'
    w_col = f'w_{s_key}'
    rets = combined[ret_col].dropna()

    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum_ret = (1 + rets).cumprod()
    mdd = (cum_ret / cum_ret.cummax() - 1).min()
    cagr = cum_ret.iloc[-1] ** (252 / len(rets)) - 1

    turnover = combined[w_col].diff().abs().mean() * 252

    print(f"  {s_name:<25} {sharpe:>8.3f} {cagr:>7.1%} {mdd:>7.1%} {ann_vol:>7.1%} {turnover:>8.2f}")

    full_results[s_key] = {
        'name': s_name,
        'sharpe': round(float(sharpe), 4),
        'cagr': round(float(cagr), 4),
        'mdd': round(float(mdd), 4),
        'ann_vol': round(float(ann_vol), 4),
        'ann_return': round(float(ann_ret), 4),
        'turnover': round(float(turnover), 4),
        'n_days': len(rets),
    }

# ============================================================
# 10. Out-of-Sample Performance (2023-2024)
# ============================================================
print(f"\n--- OOS Performance ({oos_start} to {oos_end}) ---")
oos_mask = (combined.index >= oos_start) & (combined.index <= oos_end)
oos_data = combined[oos_mask].copy()
print(f"  OOS days: {len(oos_data)}")
print(f"  {'Strategy':<25} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Vol':>8}")
print(f"  {'-'*53}")

oos_results = {}
for s_key, s_name in strategy_names.items():
    ret_col = f'ret_otc_{s_key}'
    rets = oos_data[ret_col].dropna()

    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum_ret = (1 + rets).cumprod()
    mdd = (cum_ret / cum_ret.cummax() - 1).min()
    cagr = cum_ret.iloc[-1] ** (252 / len(rets)) - 1 if len(rets) > 0 else 0

    print(f"  {s_name:<25} {sharpe:>8.3f} {cagr:>7.1%} {mdd:>7.1%} {ann_vol:>7.1%}")

    oos_results[s_key] = {
        'name': s_name,
        'sharpe': round(float(sharpe), 4),
        'cagr': round(float(cagr), 4),
        'mdd': round(float(mdd), 4),
        'ann_vol': round(float(ann_vol), 4),
        'ann_return': round(float(ann_ret), 4),
        'n_days': len(rets),
    }

# ============================================================
# 11. DM Tests (Strategy vs BH Baseline)
# ============================================================
print(f"\n--- DM Tests vs BH 0050.TW (Full Sample, OtC) ---")
print(f"  {'Strategy':<25} {'DM t-stat':>10} {'p-value':>10} {'Harvey':>8}")
print(f"  {'-'*56}")

dm_results = {}
baseline_rets = combined['ret_otc_s0'].dropna().values
for s_key in ['s4', 's5']:
    s_name = strategy_names[s_key]
    strat_rets = combined[f'ret_otc_{s_key}'].dropna().values

    min_len = min(len(strat_rets), len(baseline_rets))
    t_stat, p_val = strategy_dm_test(
        strat_rets[:min_len], baseline_rets[:min_len],
        loss_fn="negative_return"
    )
    harvey_pass = "PASS" if abs(t_stat) > 3.0 else "FAIL"

    print(f"  {s_name:<25} {t_stat:>10.3f} {p_val:>10.4f} {harvey_pass:>8}")

    dm_results[s_key] = {
        'name': s_name,
        't_stat': round(float(t_stat), 4),
        'p_value': round(float(p_val), 4),
        'harvey_pass': harvey_pass,
    }

# OOS DM tests
print(f"\n--- DM Tests vs BH 0050.TW (OOS: {oos_start} to {oos_end}, OtC) ---")
print(f"  {'Strategy':<25} {'DM t-stat':>10} {'p-value':>10} {'Harvey':>8}")
print(f"  {'-'*56}")

dm_oos_results = {}
baseline_rets_oos = oos_data['ret_otc_s0'].dropna().values
for s_key in ['s4', 's5']:
    s_name = strategy_names[s_key]
    strat_rets = oos_data[f'ret_otc_{s_key}'].dropna().values

    min_len = min(len(strat_rets), len(baseline_rets_oos))
    t_stat, p_val = strategy_dm_test(
        strat_rets[:min_len], baseline_rets_oos[:min_len],
        loss_fn="negative_return"
    )
    harvey_pass = "PASS" if abs(t_stat) > 3.0 else "FAIL"

    print(f"  {s_name:<25} {t_stat:>10.3f} {p_val:>10.4f} {harvey_pass:>8}")

    dm_oos_results[s_key] = {
        'name': s_name,
        't_stat': round(float(t_stat), 4),
        'p_value': round(float(p_val), 4),
        'harvey_pass': harvey_pass,
    }

# ============================================================
# 12. Cross-OOS: 5 × 2-Year Non-Overlapping Periods
# ============================================================
print("\n--- Cross-OOS: 5 × 2-Year Periods (OtC) ---")

cross_oos_periods = [
    ('2008-01-01', '2009-12-31'),
    ('2012-01-01', '2013-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2023-01-01', '2024-12-31'),
]

cross_oos_results = {}
for s_key in ['s4', 's5']:
    s_name = strategy_names[s_key]
    wins = 0
    period_sharpes = []
    bh_sharpes = []

    for p_start, p_end in cross_oos_periods:
        mask = (combined.index >= p_start) & (combined.index <= p_end)
        period_data = combined[mask]
        if len(period_data) < 20:
            continue

        s_rets = period_data[f'ret_otc_{s_key}'].dropna()
        bh_rets = period_data['ret_otc_s0'].dropna()

        s_sharpe = s_rets.mean() / s_rets.std() * np.sqrt(252) if s_rets.std() > 0 else 0
        bh_sharpe = bh_rets.mean() / bh_rets.std() * np.sqrt(252) if bh_rets.std() > 0 else 0

        if s_sharpe > bh_sharpe:
            wins += 1
        period_sharpes.append(round(float(s_sharpe), 3))
        bh_sharpes.append(round(float(bh_sharpe), 3))

    cross_oos_results[s_key] = {
        'name': s_name,
        'wins': wins,
        'total': len(cross_oos_periods),
        'period_sharpes': period_sharpes,
        'bh_sharpes': bh_sharpes,
    }
    win_str = f"{wins}/{len(cross_oos_periods)}"
    print(f"  {s_name:<25} Wins: {win_str}  "
          f"Strategy: {period_sharpes}  BH: {bh_sharpes}")

# ============================================================
# 13. Rolling Lead-Lag Correlation (OtC vs C2C)
# ============================================================
print("\n--- Rolling Lead-Lag Correlation ---")

rolling_corr_otc = combined['spy_ret_signal'].rolling(60).corr(combined['tw_otc_return'])
rolling_corr_c2c = combined['spy_ret_signal'].rolling(60).corr(combined['tw_c2c_return'])

print(f"  {'Metric':<25} {'OtC':>8} {'C2C':>8}")
print(f"  {'-'*43}")
print(f"  {'Mean':<25} {rolling_corr_otc.mean():>8.3f} {rolling_corr_c2c.mean():>8.3f}")
print(f"  {'Std':<25} {rolling_corr_otc.std():>8.3f} {rolling_corr_c2c.std():>8.3f}")
print(f"  {'Min':<25} {rolling_corr_otc.min():>8.3f} {rolling_corr_c2c.min():>8.3f}")
print(f"  {'Max':<25} {rolling_corr_otc.max():>8.3f} {rolling_corr_c2c.max():>8.3f}")

# ============================================================
# 14. Granger-Like Predictive Regression (OtC)
# ============================================================
print("\n--- Granger-Like Predictive Regression (OtC) ---")

y = combined['tw_otc_return'].values
x = combined['spy_ret_signal'].values
valid = np.isfinite(y) & np.isfinite(x)
y_reg, x_reg = y[valid], x[valid]

X_mat = np.column_stack([np.ones(len(x_reg)), x_reg])
beta = np.linalg.lstsq(X_mat, y_reg, rcond=None)[0]
resid = y_reg - X_mat @ beta
se = np.sqrt(np.diag(np.sum(resid ** 2) / (len(y_reg) - 2) * np.linalg.inv(X_mat.T @ X_mat)))
t_beta = beta[1] / se[1]
p_beta = 2 * (1 - stats.t.cdf(abs(t_beta), df=len(y_reg) - 2))
r_sq = 1 - np.sum(resid**2) / np.sum((y_reg - y_reg.mean())**2)

print(f"  TW50_OtC_t = {beta[0]:.6f} + {beta[1]:.4f} × SPY_{{t-1}}")
print(f"  beta t-stat: {t_beta:.3f} (p={p_beta:.6f})")
print(f"  R²: {r_sq:.6f}")

granger_results = {
    'intercept': round(float(beta[0]), 6),
    'beta': round(float(beta[1]), 4),
    't_stat': round(float(t_beta), 3),
    'p_value': round(float(p_beta), 6),
    'r_squared': round(float(r_sq), 6),
    'n_obs': int(len(y_reg)),
    'target': 'open-to-close',
}

# ============================================================
# 15. TX Cost Sensitivity (OtC)
# ============================================================
print("\n--- TX Cost Sensitivity (OtC) ---")
print(f"  {'Strategy':<25} {'0 bps':>8} {'5 bps':>8} {'10 bps':>8} {'20 bps':>8}")
print(f"  {'-'*58}")

tx_sensitivity = {}
for s_key in ['s4', 's5']:
    s_name = strategy_names[s_key]
    w_col = f'w_{s_key}'
    sharpes_by_tx = []

    for tx_bps in [0, 5, 10, 20]:
        tx = compute_tx_cost(combined[w_col], cost_bps=tx_bps)
        rets = combined[w_col] * combined['tw_otc_return'] - tx
        rets = rets.dropna()
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        sharpes_by_tx.append(round(float(sharpe), 3))

    print(f"  {s_name:<25} {sharpes_by_tx[0]:>8.3f} {sharpes_by_tx[1]:>8.3f} "
          f"{sharpes_by_tx[2]:>8.3f} {sharpes_by_tx[3]:>8.3f}")

    tx_sensitivity[s_key] = {
        'name': s_name,
        'sharpe_0bps': sharpes_by_tx[0],
        'sharpe_5bps': sharpes_by_tx[1],
        'sharpe_10bps': sharpes_by_tx[2],
        'sharpe_20bps': sharpes_by_tx[3],
    }

# ============================================================
# 16. Weight Statistics
# ============================================================
print("\n--- Weight Statistics ---")
print(f"  {'Strategy':<25} {'Mean w':>8} {'Std w':>8} {'Switches/yr':>12} {'Ann Turn':>10}")
print(f"  {'-'*66}")

weight_stats = {}
for s_key in ['s4', 's5']:
    s_name = strategy_names[s_key]
    w_col = f'w_{s_key}'
    weights = combined[w_col]

    mean_w = weights.mean()
    std_w = weights.std()
    switches = (weights.diff().abs() > 0.01).sum()
    n_years = len(combined) / 252
    switches_per_year = switches / n_years
    ann_turnover = weights.diff().abs().mean() * 252

    print(f"  {s_name:<25} {mean_w:>8.3f} {std_w:>8.3f} {switches_per_year:>12.1f} {ann_turnover:>10.3f}")

    weight_stats[s_key] = {
        'name': s_name,
        'mean_weight': round(float(mean_w), 4),
        'std_weight': round(float(std_w), 4),
        'switches_per_year': round(float(switches_per_year), 1),
        'ann_turnover': round(float(ann_turnover), 4),
    }

# ============================================================
# 17. Regime Analysis (High vs Low VIX)
# ============================================================
print("\n--- Regime Analysis (High vs Low VIX, OtC) ---")

vix_median = combined['vix_signal'].median()
high_vix = combined['vix_signal'] > vix_median
low_vix = ~high_vix

print(f"  VIX median: {vix_median:.1f}")
print(f"  {'Strategy':<25} {'Low VIX':>10} {'High VIX':>10} {'Diff':>8}")
print(f"  {'-'*56}")

regime_results = {}
for s_key, s_name in strategy_names.items():
    ret_col = f'ret_otc_{s_key}'
    low_rets = combined.loc[low_vix, ret_col].dropna()
    high_rets = combined.loc[high_vix, ret_col].dropna()

    low_sharpe = low_rets.mean() / low_rets.std() * np.sqrt(252) if low_rets.std() > 0 else 0
    high_sharpe = high_rets.mean() / high_rets.std() * np.sqrt(252) if high_rets.std() > 0 else 0

    print(f"  {s_name:<25} {low_sharpe:>10.3f} {high_sharpe:>10.3f} {high_sharpe - low_sharpe:>+8.3f}")

    regime_results[s_key] = {
        'name': s_name,
        'low_vix_sharpe': round(float(low_sharpe), 4),
        'high_vix_sharpe': round(float(high_sharpe), 4),
    }

# ============================================================
# 18. Summary & Conclusion
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY — K812v2 (3 bugs fixed)")
print("=" * 70)

print("\n  Bugs fixed:")
print("  1. Calendar: merge-on-date with explicit shift(1) on US daily calendar")
print("  2. Sanity: all checks computed live (not hard-coded)")
print("  3. Returns: open-to-close (not close-to-close)")

# Find best strategy
best_full = max(full_results.items(), key=lambda x: x[1]['sharpe'])
best_oos = max(oos_results.items(), key=lambda x: x[1]['sharpe'])
print(f"\n  Best full-sample: {best_full[1]['name']} (Sharpe {best_full[1]['sharpe']:.3f})")
print(f"  Best OOS:         {best_oos[1]['name']} (Sharpe {best_oos[1]['sharpe']:.3f})")

# Check if any strategy beats BH at Harvey threshold
any_beats_bh = False
for s_key in ['s4', 's5']:
    if full_results[s_key]['sharpe'] > full_results['s0']['sharpe']:
        if dm_results[s_key]['t_stat'] < -3.0:  # negative t = strategy better
            any_beats_bh = True
            print(f"  ★ {strategy_names[s_key]} PASSES Harvey threshold!")

if not any_beats_bh:
    print("  No strategy passes Harvey t>3.0 vs BH (OtC)")

print(f"\n  Direction accuracy (OtC): {overall_dir_otc:.1%}")
print(f"  Lead-lag beta (SPY→TW50 OtC): {granger_results['beta']:.4f} (t={granger_results['t_stat']:.2f})")

# Show impact of BUG 3 fix
print(f"\n  BUG 3 impact (C2C vs OtC Sharpe):")
for s_key, s_name in strategy_names.items():
    delta = otc_vs_c2c[s_key]['delta']
    print(f"    {s_name}: C2C inflation = {delta:+.4f}")

# ============================================================
# 19. Save Results
# ============================================================
bh_sharpe_full = full_results['s0']['sharpe']
best_strat_full = max((v for k, v in full_results.items() if k != 's0'),
                       key=lambda x: x['sharpe'])
any_harvey = any(v['harvey_pass'] == 'PASS' for v in dm_results.values())

if any_harvey:
    conclusion = (
        f"Lead-lag strategies beat BH on open-to-close returns. "
        f"Best: {best_strat_full['name']} "
        f"(Sharpe {best_strat_full['sharpe']:.4f} vs BH {bh_sharpe_full:.4f}). "
        f"Harvey threshold PASSED. "
        f"Direction accuracy (OtC) {overall_dir_otc:.1%}. "
        f"Beta(SPY→TW50 OtC) = {granger_results['beta']:.4f} (t={granger_results['t_stat']:.2f}). "
        f"All sanity checks COMPUTED (not hard-coded): "
        f"lookahead Sharpe {sanity_results['lookahead_sharpe']:.4f}, "
        f"correct lag {sanity_results['correct_lag_sharpe']:.4f}, "
        f"z vs random {sanity_results['z_score_vs_random']:.1f}."
    )
else:
    conclusion = (
        f"NULL — Lead-lag strategies do NOT beat BH on open-to-close returns "
        f"at Harvey t>3.0. "
        f"Best: {best_strat_full['name']} "
        f"(Sharpe {best_strat_full['sharpe']:.4f} vs BH {bh_sharpe_full:.4f}). "
        f"Direction accuracy (OtC) {overall_dir_otc:.1%}. "
        f"Beta(SPY→TW50 OtC) = {granger_results['beta']:.4f} (t={granger_results['t_stat']:.2f}). "
        f"Consistent with K502: lead-lag is real but alpha is in untradable overnight gap. "
        f"C2C inflates Sharpe by {otc_vs_c2c['s4']['delta']:+.4f} for Smooth and "
        f"{otc_vs_c2c['s5']['delta']:+.4f} for 8.63/VIX — confirming BUG 3 impact. "
        f"All sanity checks COMPUTED (not hard-coded): "
        f"lookahead Sharpe {sanity_results['lookahead_sharpe']:.4f}, "
        f"correct lag {sanity_results['correct_lag_sharpe']:.4f}, "
        f"z vs random {sanity_results['z_score_vs_random']:.1f}."
    )

results = {
    'experiment_id': 'k812v2',
    'title': 'K812v2: US→Taiwan Lead-Lag — Open-to-Close, Correct Calendar',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': f'{start_date} to {end_date}',
    'oos_period': f'{oos_start} to {oos_end}',
    'n_days_total': len(combined),
    'tx_cost_bps': TX_COST_BPS,
    'bugs_fixed': {
        'bug1_calendar': 'Replaced ffill+shift(1) on mixed calendar with merge-on-date + explicit shift on US daily calendar',
        'bug2_sanity': 'All sanity checks (lookahead, random baseline) computed live, not hard-coded',
        'bug3_return': 'Open-to-close return instead of close-to-close (removes untradable overnight gap)',
    },
    'prior_work': {
        'K812': 'Original lead-lag (3 HIGH bugs: calendar, sanity, c2c return)',
        'K502': 'Lead-lag alpha 77-93% in overnight gap, NOT tradable',
        'T32': 'SPY→Taiwan r=0.376, Harvey t=3.75',
        'I8': 'SPY Momentum o2c FAIL (confirms expected NULL)',
    },
    'return_comparison': {
        'otc_ann_mean': round(float(otc_mean), 4),
        'otc_ann_vol': round(float(otc_std), 4),
        'c2c_ann_mean': round(float(c2c_mean), 4),
        'c2c_ann_vol': round(float(c2c_std), 4),
    },
    'otc_vs_c2c_sharpe': otc_vs_c2c,
    'direction_accuracy': {
        'otc': {
            'spy_up_tw_up': round(float(dir_acc_up_otc), 4),
            'spy_down_tw_down': round(float(dir_acc_down_otc), 4),
            'overall': round(float(overall_dir_otc), 4),
        },
        'c2c': {
            'spy_up_tw_up': round(float(dir_acc_up_c2c), 4),
            'spy_down_tw_down': round(float(dir_acc_down_c2c), 4),
            'overall': round(float(overall_dir_c2c), 4),
        },
        'conditional_return_diff_t': round(float(t_diff), 3),
        'conditional_return_diff_p': round(float(p_diff), 4),
    },
    'granger_regression': granger_results,
    'rolling_correlation': {
        'otc': {
            'mean': round(float(rolling_corr_otc.mean()), 4),
            'std': round(float(rolling_corr_otc.std()), 4),
        },
        'c2c': {
            'mean': round(float(rolling_corr_c2c.mean()), 4),
            'std': round(float(rolling_corr_c2c.std()), 4),
        },
    },
    'sanity_checks': sanity_results,
    'full_sample': full_results,
    'oos': oos_results,
    'dm_tests_full': dm_results,
    'dm_tests_oos': dm_oos_results,
    'cross_oos_5x2yr': cross_oos_results,
    'tx_sensitivity': tx_sensitivity,
    'weight_stats': weight_stats,
    'regime_analysis': regime_results,
    'conclusion': conclusion,
    'codex_severity': 'All 3 HIGH bugs from K812 resolved',
    'references': [
        'K812: Original experiment (3 HIGH bugs)',
        'K502: Lead-lag alpha in overnight gap (VolPred)',
        'T32/T33: Asia-Pacific Time-Zone Arbitrage (VolPred)',
        'I8: SPY Momentum o2c FAIL (VolPred)',
        'U5: DeltaLag SPY→TW50 rolling corr mean=0.41 (VolPred)',
        'Lin, Engle & Ito (1994) Meteor showers vs heat waves',
    ],
}

print(f"\n  Conclusion: {conclusion}")

output_path = 'experiments/k812v2_us_taiwan_leadlag_otc_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n  Results saved to: {output_path}")
print("\nDone.")
