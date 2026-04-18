#!/usr/bin/env python3
"""
K671: VIX Futures Roll Yield as Strategy Signal
=================================================

Motivation:
  K638 tested VIX term structure slope (VIX3M/VIX) and found partial r=-0.19
  but no OOS value for vol prediction. But we didn't test the ROLL YIELD angle:
  VIX futures ETPs (like VXX) lose money from contango roll. Can we exploit this?
  When contango is steep → short vol pays; when backwardation → long vol pays.

  Prior knowledge from VolPred research:
  - K638: VIX slope partial r=-0.19, no OOS improvement in GARCH-X
  - K309/K314: Daily VIX TS signal worsens VT (0.59→0.48)
  - P41: Backwardation-enhanced VT works for SPY (+0.219 Sharpe, t=4.49)
  - N177: Contango boost +20% → COVID recovery +1.5pp but Sharpe -0.032
  - N102: Multi-factor (VIX+momentum+TS) only +0.022 Sharpe
  - Key question: Does the VIX term structure SHAPE add tradeable info?

Strategy Design:
  1. Baseline: 12/VIX (standard VT)
  2. Contango-enhanced: contango>5% → boost allocation +20%
  3. Backwardation-reduced: backwardation (<0) → reduce allocation 50%
  4. Combined: both contango boost + backwardation reduction
  5. Contango binary: only invest when contango>0%, else 100% cash

Data source: yfinance (SPY, ^VIX, ^VIX3M), 2008-01-01 to 2026-03-27

References:
  - Lu & Zhu (2010) "Volatility components" JFE — term structure of implied vol
  - Johnson (2017) "VIX term structure" JFQA — contango/backwardation predictive power
  - Mixon (2007) "The implied volatility term structure of stock index options"
    Journal of Empirical Finance — IV term structure dynamics
  - Alexander & Korovilas (2013) "Diversification of equity with VIX futures"
    Journal of Risk — roll yield and VIX carry
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download & Construction
# ============================================================
print("=" * 70)
print("K671: VIX Futures Roll Yield as Strategy Signal")
print("=" * 70)

print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2008-01-01", end="2026-03-28", progress=False)
vix = yf.download("^VIX", start="2008-01-01", end="2026-03-28", progress=False)
vix3m_raw = yf.download("^VIX3M", start="2008-01-01", end="2026-03-28", progress=False)

# Handle multi-level columns
for frame in [spy, vix, vix3m_raw]:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

vix3m_available = len(vix3m_raw) > 100
if not vix3m_available:
    print("  ^VIX3M not available, trying ^VXMT...")
    vix3m_raw = yf.download("^VXMT", start="2008-01-01", end="2026-03-28", progress=False)
    if isinstance(vix3m_raw.columns, pd.MultiIndex):
        vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
    vix3m_available = len(vix3m_raw) > 100
    ts_source = "^VXMT" if vix3m_available else "VIX_63d_MA_proxy"
else:
    ts_source = "^VIX3M"

if not vix3m_available:
    print("  No VIX3M available. Using VIX 63d MA as proxy.")
    ts_source = "VIX_63d_MA_proxy"

print(f"  Term structure source: {ts_source}")
print(f"  SPY: {len(spy)} days")
print(f"  VIX: {len(vix)} days")
if vix3m_available:
    print(f"  VIX3M: {len(vix3m_raw)} days")

# Build unified dataframe
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')

if vix3m_available:
    df['vix3m'] = vix3m_raw['Close'].reindex(spy.index, method='ffill')
else:
    df['vix3m'] = df['vix'].rolling(63).mean()

df = df.dropna()

# ============================================================
# 2. Construct Roll Yield / Contango Signal
# ============================================================
print("\n[2] Constructing roll yield signals...")

# Contango = (VIX3M - VIX) / VIX  (positive = normal contango)
df['contango'] = (df['vix3m'] - df['vix']) / df['vix']

# Also compute daily realized volatility for context
df['rv_22d'] = df['spy_return'].rolling(22).std() * np.sqrt(252) * 100  # annualized %

print(f"  Total observations: {len(df)}")
print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 3. Descriptive Statistics
# ============================================================
print("\n[3] Descriptive statistics of contango signal...")

contango = df['contango'].dropna()
desc_stats = {
    'mean': float(contango.mean()),
    'std': float(contango.std()),
    'min': float(contango.min()),
    'q25': float(contango.quantile(0.25)),
    'median': float(contango.median()),
    'q75': float(contango.quantile(0.75)),
    'max': float(contango.max()),
    'skewness': float(contango.skew()),
    'kurtosis': float(contango.kurtosis()),
}
print(f"  Mean contango: {desc_stats['mean']:.4f} ({desc_stats['mean']*100:.1f}%)")
print(f"  Std: {desc_stats['std']:.4f}")
print(f"  Min: {desc_stats['min']:.4f} (max backwardation)")
print(f"  Max: {desc_stats['max']:.4f} (max contango)")
print(f"  Skewness: {desc_stats['skewness']:.3f}")
print(f"  Kurtosis: {desc_stats['kurtosis']:.3f}")

# Regime counts
n_contango = (contango > 0).sum()
n_backwardation = (contango < 0).sum()
n_steep_contango = (contango > 0.05).sum()
pct_contango = n_contango / len(contango) * 100
pct_backwardation = n_backwardation / len(contango) * 100
pct_steep = n_steep_contango / len(contango) * 100

print(f"\n  Regime breakdown:")
print(f"    Contango (>0): {n_contango} days ({pct_contango:.1f}%)")
print(f"    Steep contango (>5%): {n_steep_contango} days ({pct_steep:.1f}%)")
print(f"    Backwardation (<0): {n_backwardation} days ({pct_backwardation:.1f}%)")

regime_stats = {
    'contango_days': int(n_contango),
    'contango_pct': round(pct_contango, 1),
    'steep_contango_days': int(n_steep_contango),
    'steep_contango_pct': round(pct_steep, 1),
    'backwardation_days': int(n_backwardation),
    'backwardation_pct': round(pct_backwardation, 1),
}

# ============================================================
# 4. Contango vs Future Returns Analysis
# ============================================================
print("\n[4] Contango vs future SPY returns...")

# Next 5d, 22d returns
df['fwd_5d'] = df['spy_return'].rolling(5).sum().shift(-5)
df['fwd_22d'] = df['spy_return'].rolling(22).sum().shift(-22)

analysis_df = df.dropna(subset=['contango', 'fwd_5d', 'fwd_22d'])

# Correlation: contango vs future returns
corr_5d, p_5d = stats.pearsonr(analysis_df['contango'], analysis_df['fwd_5d'])
corr_22d, p_22d = stats.pearsonr(analysis_df['contango'], analysis_df['fwd_22d'])

print(f"  Contango vs next 5d return: r={corr_5d:.4f} (p={p_5d:.4e})")
print(f"  Contango vs next 22d return: r={corr_22d:.4f} (p={p_22d:.4e})")

# Conditional returns by contango regime
regimes = {
    'deep_backwardation': analysis_df[analysis_df['contango'] < -0.05],
    'mild_backwardation': analysis_df[(analysis_df['contango'] >= -0.05) & (analysis_df['contango'] < 0)],
    'mild_contango': analysis_df[(analysis_df['contango'] >= 0) & (analysis_df['contango'] < 0.05)],
    'normal_contango': analysis_df[(analysis_df['contango'] >= 0.05) & (analysis_df['contango'] < 0.15)],
    'steep_contango': analysis_df[analysis_df['contango'] >= 0.15],
}

print(f"\n  Conditional next-22d returns by contango regime:")
regime_returns = {}
for name, subset in regimes.items():
    if len(subset) > 10:
        mean_ret = subset['fwd_22d'].mean() * 252 / 22  # annualized
        mean_vol = subset['rv_22d'].mean()
        n = len(subset)
        print(f"    {name:25s}: ann_ret={mean_ret*100:.1f}%, vol={mean_vol:.1f}%, n={n}")
        regime_returns[name] = {
            'annualized_return_pct': round(float(mean_ret * 100), 2),
            'avg_realized_vol_pct': round(float(mean_vol), 2),
            'n_days': int(n),
        }

# ============================================================
# 5. Strategy Backtests
# ============================================================
print("\n[5] Strategy backtests (full period)...")
print("  NOTE: Using LAGGED contango signal (t-1) to avoid look-ahead bias.")
print("  All weights based on yesterday's VIX term structure, applied to today's return.")

# Use log returns for SPY
# SHY proxy: rf ≈ 0.01/252 per day (rough approximation)
rf_daily = 0.01 / 252

# Full backtest period: start after enough data for VIX3M
bt_start = '2008-06-01'  # After 63d MA warmup
bt_df = df.loc[bt_start:].copy()
bt_df = bt_df.dropna(subset=['contango', 'spy_return'])

# CRITICAL: Lag the contango signal by 1 day to avoid look-ahead bias
# We observe yesterday's term structure → set today's weight → earn today's return
bt_df['contango_lag1'] = bt_df['contango'].shift(1)
bt_df = bt_df.dropna(subset=['contango_lag1'])

print(f"  Backtest period: {bt_df.index[0].strftime('%Y-%m-%d')} to {bt_df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Backtest days: {len(bt_df)}")

def compute_strategy_metrics(weights, returns, name, rf=rf_daily):
    """Compute strategy metrics given daily weights and returns."""
    # Strategy return = weight * spy_return + (1 - weight) * rf
    strat_ret = weights * returns + (1 - weights) * rf

    # Cumulative return
    cum_ret = np.exp(strat_ret.cumsum())
    total_ret = cum_ret.iloc[-1] - 1

    # Annualized return
    n_years = len(strat_ret) / 252
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    # Annualized vol
    ann_vol = strat_ret.std() * np.sqrt(252)

    # Sharpe
    sharpe = (strat_ret.mean() - rf) / strat_ret.std() * np.sqrt(252) if strat_ret.std() > 0 else 0

    # Max drawdown
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min()

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    downside = strat_ret[strat_ret < 0].std() * np.sqrt(252)
    sortino = (cagr - 0.01) / downside if downside > 0 else 0

    # Average turnover (daily weight change)
    turnover = weights.diff().abs().mean() * 252

    # Win rate
    win_rate = (strat_ret > 0).mean()

    # Average weight (to check leverage effect)
    avg_weight = float(weights.mean())

    return {
        'name': name,
        'cagr_pct': round(float(cagr * 100), 2),
        'ann_vol_pct': round(float(ann_vol * 100), 2),
        'sharpe': round(float(sharpe), 4),
        'max_dd_pct': round(float(max_dd * 100), 2),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'total_return_pct': round(float(total_ret * 100), 2),
        'ann_turnover': round(float(turnover), 2),
        'win_rate_pct': round(float(win_rate * 100), 1),
        'avg_weight': round(avg_weight, 4),
        'n_days': int(len(strat_ret)),
    }


# Strategy 1: Buy & Hold SPY (benchmark)
w_bh = pd.Series(1.0, index=bt_df.index)

# Strategy 2: Standard 12/VIX (baseline VT)
# NOTE: VIX is also lagged — in reality you'd use yesterday's VIX close
# For 12/VIX this is already standard practice (VIX close = decision, next day = trade)
w_12vix = np.clip(12.0 / bt_df['vix'].shift(1), 0, 1.5)
w_12vix = w_12vix.dropna()
# Align all to same index
bt_df = bt_df.loc[w_12vix.index]

# Strategy 3: Contango-enhanced 12/VIX (using LAGGED contango)
# When contango > 5%, increase allocation by 20%
w_contango_enhanced = w_12vix.copy()
mask_steep = bt_df['contango_lag1'] > 0.05
w_contango_enhanced[mask_steep] = w_contango_enhanced[mask_steep] * 1.20
w_contango_enhanced = np.clip(w_contango_enhanced, 0, 1.5)

# Strategy 4: Backwardation-reduced 12/VIX (using LAGGED contango)
# When backwardation (contango < 0), reduce allocation by 50%
w_backwardation_reduced = w_12vix.copy()
mask_backwardation = bt_df['contango_lag1'] < 0
w_backwardation_reduced[mask_backwardation] = w_backwardation_reduced[mask_backwardation] * 0.50
w_backwardation_reduced = np.clip(w_backwardation_reduced, 0, 1.5)

# Strategy 5: Combined (contango boost + backwardation reduction, LAGGED)
w_combined = w_12vix.copy()
w_combined[mask_steep] = w_combined[mask_steep] * 1.20
w_combined[mask_backwardation] = w_combined[mask_backwardation] * 0.50
w_combined = np.clip(w_combined, 0, 1.5)

# Strategy 6: Contango binary (only invest when lagged contango > 0, else cash)
w_binary = w_12vix.copy()
mask_no_contango = bt_df['contango_lag1'] <= 0
w_binary[mask_no_contango] = 0.0

# Strategy 7: Leverage-matched baseline (same avg weight as combined)
# This controls for the leverage effect — combined has higher avg weight
# We scale 12/VIX so its average weight matches combined's average weight
avg_w_combined = w_combined.mean()
avg_w_baseline = w_12vix.mean()
leverage_scale = avg_w_combined / avg_w_baseline if avg_w_baseline > 0 else 1.0
w_leverage_matched = np.clip(w_12vix * leverage_scale, 0, 1.5)

strategies = {
    'buy_hold': (w_bh, 'Buy & Hold SPY'),
    'standard_12vix': (w_12vix, 'Standard 12/VIX'),
    'contango_enhanced': (w_contango_enhanced, 'Contango Enhanced (+20% if >5%)'),
    'backwardation_reduced': (w_backwardation_reduced, 'Backwardation Reduced (-50% if <0)'),
    'combined': (w_combined, 'Combined (boost + reduce)'),
    'contango_binary': (w_binary, 'Contango Binary (only invest if >0)'),
    'leverage_matched': (w_leverage_matched, 'Leverage-Matched 12/VIX'),
}

all_results = {}
print(f"\n  {'Strategy':<40s} {'CAGR':>7s} {'Sharpe':>7s} {'MDD':>8s} {'AvgWt':>7s} {'Sortino':>8s}")
print(f"  {'-'*40} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")

for key, (w, name) in strategies.items():
    metrics = compute_strategy_metrics(w, bt_df['spy_return'], name)
    all_results[key] = metrics
    print(f"  {name:<40s} {metrics['cagr_pct']:>6.1f}% {metrics['sharpe']:>7.3f} {metrics['max_dd_pct']:>7.1f}% {metrics['avg_weight']:>7.3f} {metrics['sortino']:>7.3f}")

print(f"\n  Leverage check: 12/VIX avg weight={avg_w_baseline:.4f}, Combined avg weight={avg_w_combined:.4f}, scale={leverage_scale:.4f}")

# ============================================================
# 6. Sub-period Analysis
# ============================================================
print("\n[6] Sub-period analysis...")

sub_periods = {
    'GFC_recovery_2009_2012': ('2009-03-01', '2012-12-31'),
    'bull_2013_2019': ('2013-01-01', '2019-12-31'),
    'COVID_2020': ('2020-01-01', '2020-12-31'),
    'post_COVID_2021_2023': ('2021-01-01', '2023-12-31'),
    'recent_2024_2026': ('2024-01-01', '2026-03-27'),
}

sub_period_results = {}
for period_name, (start, end) in sub_periods.items():
    sub = bt_df.loc[start:end]
    if len(sub) < 50:
        continue

    sub_metrics = {}
    for key, (w, name) in strategies.items():
        w_sub = w.loc[start:end]
        if len(w_sub) < 50:
            continue
        m = compute_strategy_metrics(w_sub, sub['spy_return'], name)
        sub_metrics[key] = m

    sub_period_results[period_name] = sub_metrics

    # Print comparison
    baseline_sharpe = sub_metrics.get('standard_12vix', {}).get('sharpe', 0)
    combined_sharpe = sub_metrics.get('combined', {}).get('sharpe', 0)
    delta = combined_sharpe - baseline_sharpe
    print(f"  {period_name:<30s}: 12/VIX Sharpe={baseline_sharpe:.3f}, Combined={combined_sharpe:.3f}, Δ={delta:+.3f}")

# ============================================================
# 7. Statistical Tests: Is the Improvement Significant?
# ============================================================
print("\n[7] Statistical tests...")

# Paired t-test on daily returns: combined vs 12/VIX
ret_baseline = w_12vix * bt_df['spy_return'] + (1 - w_12vix) * rf_daily
ret_combined = w_combined * bt_df['spy_return'] + (1 - w_combined) * rf_daily
ret_contango = w_contango_enhanced * bt_df['spy_return'] + (1 - w_contango_enhanced) * rf_daily
ret_backwardation = w_backwardation_reduced * bt_df['spy_return'] + (1 - w_backwardation_reduced) * rf_daily
ret_binary = w_binary * bt_df['spy_return'] + (1 - w_binary) * rf_daily
ret_leverage_matched = w_leverage_matched * bt_df['spy_return'] + (1 - w_leverage_matched) * rf_daily

tests = {}

# Paired t-tests vs baseline AND vs leverage-matched
for name, ret_alt, ret_base in [
    ('contango_enhanced', ret_contango, ret_baseline),
    ('backwardation_reduced', ret_backwardation, ret_baseline),
    ('combined', ret_combined, ret_baseline),
    ('contango_binary', ret_binary, ret_baseline),
    ('combined_vs_lev_matched', ret_combined, ret_leverage_matched),
]:
    diff = ret_alt - ret_base
    t_stat, p_val = stats.ttest_1samp(diff, 0)
    # Newey-West style: account for serial correlation (use HAC)
    n = len(diff)
    mean_diff = diff.mean()
    # Simple Newey-West with L=22 lags
    L = 22
    gamma0 = ((diff - mean_diff) ** 2).sum() / n
    gamma_sum = 0
    for l in range(1, L + 1):
        gamma_l = ((diff.iloc[l:].values - mean_diff) * (diff.iloc[:-l].values - mean_diff)).sum() / n
        w_l = 1 - l / (L + 1)  # Bartlett kernel
        gamma_sum += 2 * w_l * gamma_l
    nw_var = (gamma0 + gamma_sum) / n
    nw_t = mean_diff / np.sqrt(nw_var) if nw_var > 0 else 0
    nw_p = 2 * (1 - stats.t.cdf(abs(nw_t), df=n - 1))

    ann_diff = mean_diff * 252 * 100  # annualized bps

    tests[name] = {
        'mean_daily_diff': round(float(mean_diff), 8),
        'ann_diff_bps': round(float(ann_diff), 2),
        'paired_t': round(float(t_stat), 4),
        'paired_p': round(float(p_val), 6),
        'newey_west_t': round(float(nw_t), 4),
        'newey_west_p': round(float(nw_p), 6),
    }
    sig = "★" if abs(nw_t) > 3.0 else ("*" if abs(nw_t) > 1.96 else "NS")
    print(f"  {name:<25s}: Δ={ann_diff:+.1f}bps/yr, NW t={nw_t:.3f} (p={nw_p:.4f}) {sig}")

# ============================================================
# 8. Rolling Sharpe Comparison
# ============================================================
print("\n[8] Rolling Sharpe ratio (252d window)...")

rolling_window = 252
rolling_sharpes = {}

for name, ret_series in [
    ('standard_12vix', ret_baseline),
    ('combined', ret_combined),
    ('contango_binary', ret_binary),
]:
    rolling_mean = ret_series.rolling(rolling_window).mean()
    rolling_std = ret_series.rolling(rolling_window).std()
    rolling_sharpe = (rolling_mean - rf_daily) / rolling_std * np.sqrt(252)
    rolling_sharpes[name] = rolling_sharpe

# Count periods where combined beats baseline
rs_base = rolling_sharpes['standard_12vix'].dropna()
rs_combined = rolling_sharpes['combined'].reindex(rs_base.index)
combined_wins = (rs_combined > rs_base).sum()
combined_total = len(rs_base)
combined_win_pct = combined_wins / combined_total * 100 if combined_total > 0 else 0

print(f"  Combined beats 12/VIX: {combined_wins}/{combined_total} days ({combined_win_pct:.1f}%)")

# ============================================================
# 9. Contango Signal Persistence
# ============================================================
print("\n[9] Contango signal persistence & autocorrelation...")

from statsmodels.tsa.stattools import acf

contango_acf = acf(bt_df['contango'].dropna(), nlags=20, fft=True)
print(f"  Contango autocorrelation:")
print(f"    Lag 1: {contango_acf[1]:.4f}")
print(f"    Lag 5: {contango_acf[5]:.4f}")
print(f"    Lag 22: {contango_acf[min(20, len(contango_acf)-1)]:.4f}")

# Average duration of contango/backwardation regimes
contango_flag = (bt_df['contango'] > 0).astype(int)
regime_changes = contango_flag.diff().abs()
n_regime_switches = int(regime_changes.sum())
avg_regime_duration = len(bt_df) / n_regime_switches if n_regime_switches > 0 else len(bt_df)

print(f"  Regime switches: {n_regime_switches}")
print(f"  Average regime duration: {avg_regime_duration:.1f} days")

persistence_stats = {
    'acf_lag1': round(float(contango_acf[1]), 4),
    'acf_lag5': round(float(contango_acf[5]), 4),
    'acf_lag20': round(float(contango_acf[min(20, len(contango_acf)-1)]), 4),
    'n_regime_switches': n_regime_switches,
    'avg_regime_duration_days': round(float(avg_regime_duration), 1),
}

# ============================================================
# 10. Transaction Cost Sensitivity
# ============================================================
print("\n[10] Transaction cost sensitivity...")

tx_costs_bps = [0, 5, 10, 20, 50]
tx_results = {}

for tc in tx_costs_bps:
    tc_daily = tc / 10000  # convert bps to daily fraction

    for key, (w, name) in [('standard_12vix', (w_12vix, 'Standard 12/VIX')),
                            ('combined', (w_combined, 'Combined'))]:
        strat_ret = w * bt_df['spy_return'] + (1 - w) * rf_daily
        # Subtract transaction cost proportional to turnover
        turnover_daily = w.diff().abs()
        strat_ret_net = strat_ret - turnover_daily * tc_daily

        # Sharpe
        sharpe_net = (strat_ret_net.mean() - rf_daily) / strat_ret_net.std() * np.sqrt(252) if strat_ret_net.std() > 0 else 0

        if tc not in tx_results:
            tx_results[tc] = {}
        tx_results[tc][key] = round(float(sharpe_net), 4)

print(f"  {'TX Cost (bps)':<15s} {'12/VIX Sharpe':>14s} {'Combined Sharpe':>16s} {'Δ Sharpe':>10s}")
print(f"  {'-'*15} {'-'*14} {'-'*16} {'-'*10}")
for tc in tx_costs_bps:
    s_base = tx_results[tc]['standard_12vix']
    s_comb = tx_results[tc]['combined']
    delta = s_comb - s_base
    print(f"  {tc:<15d} {s_base:>14.4f} {s_comb:>16.4f} {delta:>+10.4f}")

# ============================================================
# 11. Key Insight: When Does Roll Yield Signal Add Value?
# ============================================================
print("\n[11] Key insight analysis...")

# During which VIX regimes does contango signal help most?
vix_regimes = {
    'low_vix_<15': bt_df['vix'] < 15,
    'normal_15_20': (bt_df['vix'] >= 15) & (bt_df['vix'] < 20),
    'elevated_20_30': (bt_df['vix'] >= 20) & (bt_df['vix'] < 30),
    'high_vix_>30': bt_df['vix'] >= 30,
}

print(f"\n  Performance difference (Combined - 12/VIX) by VIX regime:")
vix_regime_analysis = {}
for regime_name, mask in vix_regimes.items():
    sub_base = ret_baseline[mask]
    sub_comb = ret_combined[mask]
    if len(sub_base) > 50:
        diff = sub_comb - sub_base
        mean_diff_ann = diff.mean() * 252 * 100
        sharpe_base = (sub_base.mean() - rf_daily) / sub_base.std() * np.sqrt(252) if sub_base.std() > 0 else 0
        sharpe_comb = (sub_comb.mean() - rf_daily) / sub_comb.std() * np.sqrt(252) if sub_comb.std() > 0 else 0
        n = len(sub_base)
        print(f"    {regime_name:<20s}: Δ={mean_diff_ann:+.1f}bps/yr, Sharpe Δ={sharpe_comb-sharpe_base:+.4f}, n={n}")
        vix_regime_analysis[regime_name] = {
            'delta_bps_ann': round(float(mean_diff_ann), 2),
            'sharpe_baseline': round(float(sharpe_base), 4),
            'sharpe_combined': round(float(sharpe_comb), 4),
            'sharpe_delta': round(float(sharpe_comb - sharpe_base), 4),
            'n_days': int(n),
        }

# ============================================================
# 12. Cross-OOS Validation (multiple OOS periods)
# ============================================================
print("\n[12] Cross-OOS validation...")

oos_periods = [
    ('2014-2015', '2014-01-01', '2015-12-31'),
    ('2016-2017', '2016-01-01', '2017-12-31'),
    ('2018-2019', '2018-01-01', '2019-12-31'),
    ('2020-2021', '2020-01-01', '2021-12-31'),
    ('2022-2023', '2022-01-01', '2023-12-31'),
    ('2024-2026', '2024-01-01', '2026-03-27'),
]

cross_oos_results = {}
combined_wins_oos = 0
combined_total_oos = 0
# Also track combined vs leverage-matched in cross-OOS
lev_match_wins_oos = 0

print(f"  {'OOS Period':<15s} {'12/VIX':>8s} {'Combined':>10s} {'LevMatch':>10s} {'Δ vs 12V':>10s} {'Δ vs LM':>10s}")
print(f"  {'-'*15} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

for period_label, oos_start, oos_end in oos_periods:
    oos = bt_df.loc[oos_start:oos_end]
    if len(oos) < 50:
        continue

    # Baseline 12/VIX (using lagged VIX — already applied in w_12vix)
    w_b = w_12vix.loc[oos_start:oos_end]
    ret_b = w_b * oos.loc[w_b.index, 'spy_return'] + (1 - w_b) * rf_daily
    sharpe_b = (ret_b.mean() - rf_daily) / ret_b.std() * np.sqrt(252) if ret_b.std() > 0 else 0

    # Combined (using lagged contango — already applied in w_combined)
    w_c = w_combined.loc[oos_start:oos_end]
    ret_c = w_c * oos.loc[w_c.index, 'spy_return'] + (1 - w_c) * rf_daily
    sharpe_c = (ret_c.mean() - rf_daily) / ret_c.std() * np.sqrt(252) if ret_c.std() > 0 else 0

    # Leverage-matched (already computed)
    w_lm = w_leverage_matched.loc[oos_start:oos_end]
    ret_lm = w_lm * oos.loc[w_lm.index, 'spy_return'] + (1 - w_lm) * rf_daily
    sharpe_lm = (ret_lm.mean() - rf_daily) / ret_lm.std() * np.sqrt(252) if ret_lm.std() > 0 else 0

    delta_vs_base = sharpe_c - sharpe_b
    delta_vs_lm = sharpe_c - sharpe_lm
    winner = "Combined" if delta_vs_base > 0 else "12/VIX"
    combined_total_oos += 1
    if delta_vs_base > 0:
        combined_wins_oos += 1
    if delta_vs_lm > 0:
        lev_match_wins_oos += 1

    print(f"  {period_label:<15s} {sharpe_b:>8.3f} {sharpe_c:>10.3f} {sharpe_lm:>10.3f} {delta_vs_base:>+10.3f} {delta_vs_lm:>+10.3f}")
    cross_oos_results[period_label] = {
        'sharpe_baseline': round(float(sharpe_b), 4),
        'sharpe_combined': round(float(sharpe_c), 4),
        'sharpe_leverage_matched': round(float(sharpe_lm), 4),
        'delta_vs_baseline': round(float(delta_vs_base), 4),
        'delta_vs_leverage_matched': round(float(delta_vs_lm), 4),
        'winner': winner,
    }

win_rate_oos = combined_wins_oos / combined_total_oos * 100 if combined_total_oos > 0 else 0
lev_win_rate_oos = lev_match_wins_oos / combined_total_oos * 100 if combined_total_oos > 0 else 0
print(f"\n  Combined wins vs 12/VIX: {combined_wins_oos}/{combined_total_oos} ({win_rate_oos:.0f}%)")
print(f"  Combined wins vs LevMatch: {lev_match_wins_oos}/{combined_total_oos} ({lev_win_rate_oos:.0f}%)")
print(f"  ★ The LevMatch comparison controls for leverage effect")

# ============================================================
# 13. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

baseline_sharpe = all_results['standard_12vix']['sharpe']
combined_sharpe = all_results['combined']['sharpe']
lev_matched_sharpe = all_results['leverage_matched']['sharpe']
delta_sharpe = combined_sharpe - baseline_sharpe
delta_sharpe_lm = combined_sharpe - lev_matched_sharpe

print(f"\n  Full-period 12/VIX Sharpe: {baseline_sharpe:.4f} (avg weight={all_results['standard_12vix']['avg_weight']:.4f})")
print(f"  Full-period Combined Sharpe: {combined_sharpe:.4f} (avg weight={all_results['combined']['avg_weight']:.4f})")
print(f"  Full-period LevMatch Sharpe: {lev_matched_sharpe:.4f} (avg weight={all_results['leverage_matched']['avg_weight']:.4f})")
print(f"  Delta vs 12/VIX: {delta_sharpe:+.4f}")
print(f"  Delta vs LevMatch: {delta_sharpe_lm:+.4f} ← THIS IS THE FAIR COMPARISON")
print(f"  Cross-OOS win rate vs 12/VIX: {win_rate_oos:.0f}%")
print(f"  Cross-OOS win rate vs LevMatch: {lev_win_rate_oos:.0f}%")
print(f"  NW t-stat (combined vs baseline): {tests.get('combined', {}).get('newey_west_t', 'N/A')}")
print(f"  NW t-stat (combined vs LevMatch): {tests.get('combined_vs_lev_matched', {}).get('newey_west_t', 'N/A')}")

# Determine conclusion — use the FAIR comparison (vs leverage-matched)
nw_t_combined = tests.get('combined', {}).get('newey_west_t', 0)
nw_t_fair = tests.get('combined_vs_lev_matched', {}).get('newey_west_t', 0)

# The backwardation-only strategy is the purest test (no leverage effect)
nw_t_backwardation = tests.get('backwardation_reduced', {}).get('newey_west_t', 0)

if abs(nw_t_fair) > 3.0:
    conclusion = f"SIGNIFICANT: Roll yield signal adds value beyond leverage (NW t={nw_t_fair:.2f} vs LevMatch, Harvey threshold met)"
elif abs(nw_t_backwardation) > 3.0:
    conclusion = f"PARTIAL: Backwardation reduction significant (NW t={nw_t_backwardation:.2f}), but combined improvement may be leverage artifact"
elif abs(nw_t_fair) > 1.96:
    conclusion = f"MARGINAL: Some evidence (NW t={nw_t_fair:.2f} vs LevMatch) but does not meet Harvey (2016) t>3.0 threshold"
else:
    conclusion = f"NULL: Roll yield signal does not add value beyond simple leverage change (NW t={nw_t_fair:.2f} vs LevMatch)"

print(f"\n  Conclusion: {conclusion}")
print(f"\n  CRITICAL CAVEAT: Contango >5% occurs {regime_stats['steep_contango_pct']}% of the time.")
print(f"  The contango-enhanced strategy is effectively 12/VIX × 1.2 most of the time.")
print(f"  The backwardation-reduced strategy is the purer signal test (only {regime_stats['backwardation_pct']}% of days affected).")

# ============================================================
# 14. Save Results
# ============================================================
print("\n[14] Saving results...")

results = {
    'experiment_id': 'K671',
    'title': 'VIX Futures Roll Yield as Strategy Signal',
    'timestamp': datetime.now().isoformat(),
    'data_source': f'yfinance (SPY, ^VIX, {ts_source})',
    'data_period': f"{bt_df.index[0].strftime('%Y-%m-%d')} to {bt_df.index[-1].strftime('%Y-%m-%d')}",
    'total_observations': int(len(bt_df)),
    'term_structure_source': ts_source,
    'descriptive_statistics': desc_stats,
    'regime_breakdown': regime_stats,
    'contango_vs_future_returns': {
        'corr_5d': round(float(corr_5d), 4),
        'corr_5d_p': round(float(p_5d), 6),
        'corr_22d': round(float(corr_22d), 4),
        'corr_22d_p': round(float(p_22d), 6),
    },
    'conditional_returns_by_regime': regime_returns,
    'strategy_results_full_period': all_results,
    'sub_period_results': sub_period_results,
    'statistical_tests_vs_baseline': tests,
    'rolling_sharpe_combined_win_pct': round(float(combined_win_pct), 1),
    'persistence_stats': persistence_stats,
    'transaction_cost_sensitivity': tx_results,
    'vix_regime_analysis': vix_regime_analysis,
    'cross_oos_validation': cross_oos_results,
    'cross_oos_win_rate_vs_baseline_pct': round(float(win_rate_oos), 1),
    'cross_oos_win_rate_vs_levmatch_pct': round(float(lev_win_rate_oos), 1),
    'leverage_analysis': {
        'avg_weight_baseline': round(float(avg_w_baseline), 4),
        'avg_weight_combined': round(float(avg_w_combined), 4),
        'leverage_scale': round(float(leverage_scale), 4),
        'sharpe_leverage_matched': lev_matched_sharpe,
        'delta_combined_vs_levmatch': round(float(delta_sharpe_lm), 4),
    },
    'look_ahead_bias_fix': 'All weights use lagged (t-1) contango and VIX signals',
    'conclusion': conclusion,
    'key_findings': [
        f"Contango signal mean={desc_stats['mean']*100:.1f}%, backwardation {regime_stats['backwardation_pct']}% of time",
        f"Contango vs 22d future return: r={corr_22d:.4f} (p={p_22d:.4e})",
        f"Combined Sharpe delta vs 12/VIX: {delta_sharpe:+.4f} (but leverage effect)",
        f"Combined Sharpe delta vs LevMatch: {delta_sharpe_lm:+.4f} (fair comparison)",
        f"NW t-stat vs baseline: {nw_t_combined:.3f}",
        f"NW t-stat vs LevMatch: {nw_t_fair:.3f} (★ this is the real test)",
        f"Backwardation reduction NW t-stat: {nw_t_backwardation:.3f}",
        f"Cross-OOS win rate vs 12/VIX: {win_rate_oos:.0f}%, vs LevMatch: {lev_win_rate_oos:.0f}%",
        f"Contango signal highly persistent (ACF lag-1={persistence_stats['acf_lag1']:.3f})",
        f"CAVEAT: contango>5% = {regime_stats['steep_contango_pct']}% of time → contango boost is nearly constant leverage increase",
    ],
    'references': [
        'Lu & Zhu (2010) "Volatility components" JFE',
        'Johnson (2017) "VIX term structure" JFQA',
        'Mixon (2007) "The implied volatility term structure" JEF',
        'Alexander & Korovilas (2013) "Diversification of equity with VIX futures" JoR',
        'K638: VIX Term Structure Slope (prior VolPred experiment)',
    ],
}

import os
output_path = os.path.join(os.path.dirname(__file__), 'k671_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"\n{'='*70}")
print("K671 COMPLETE")
print(f"{'='*70}")
