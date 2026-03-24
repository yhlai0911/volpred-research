"""
K249: Risk-On/Risk-Off Regime Trading — Multi-Signal Regime Classification

Background:
- Instead of using a single signal (VIX, momentum, etc.), combine multiple
  signals into a composite regime classifier.
- When multiple signals agree "risk-on", go aggressive; when they agree
  "risk-off", go defensive.
- Tests whether COMBINING signals adds value over any single signal.

Data:
- SPY, GLD, TLT, VIX, HYG (high yield bond ETF) daily from yfinance
- Period: 2007-2024

Methodology:
1. Five binary risk signals:
   - VIX < 20 (vol regime)
   - SPY > 200d MA (trend)
   - SPY 12m return > 0 (momentum)
   - HYG-TLT spread narrowing (credit condition)
   - VIX term structure in contango (fear fading) — proxied by VIX 20d MA < VIX 5d MA
2. Composite score: sum of 5 signals (0-5)
   - 4-5: aggressive (80% SPY, 20% GLD)
   - 2-3: balanced (50% SPY, 50% GLD)
   - 0-1: defensive (20% SPY, 80% GLD)
3. Monthly rebalance, with and without VT overlay (12/VIX)
4. Compare vs 50/50+VT, SPY B&H, TSMOM 6_1
5. 5-period cross-OOS, Harvey threshold (t>3.0), DM test

[提出: 用戶, 執行: Claude]
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
# 1. Data Download
# ============================================================
print("=" * 70)
print("K249: Risk-On/Risk-Off Regime Trading — Multi-Signal Regime Classification")
print("=" * 70)

print("\n[1] Downloading data from yfinance...")
tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'TLT': 'TLT',
    'VIX': '^VIX',
    'HYG': 'HYG',
}

raw = {}
for name, ticker in tickers.items():
    data = yf.download(ticker, start="2006-01-01", end="2025-01-01", progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    raw[name] = data['Close']
    print(f"  {name}: {len(data)} rows, {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")

# Build unified DataFrame
df = pd.DataFrame(index=raw['SPY'].index)
for name in ['SPY', 'GLD', 'TLT', 'VIX', 'HYG']:
    df[name] = raw[name].reindex(df.index, method='ffill')

df = df.dropna()
print(f"\n  Unified data: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Compute Returns
# ============================================================
print("\n[2] Computing returns...")
for asset in ['SPY', 'GLD', 'TLT', 'HYG']:
    df[f'{asset}_ret'] = df[asset].pct_change()

df = df.dropna()

# ============================================================
# 3. Build Risk Signals (all lagged by 1 day to avoid look-ahead)
# ============================================================
print("\n[3] Building 5 risk signals (all lagged to avoid look-ahead bias)...")

# Signal 1: VIX < 20 (vol regime — low fear = risk-on)
df['sig_vix_low'] = (df['VIX'] < 20).astype(int)

# Signal 2: SPY > 200d MA (trend — above long-term trend = risk-on)
df['SPY_200d'] = df['SPY'].rolling(200).mean()
df['sig_trend'] = (df['SPY'] > df['SPY_200d']).astype(int)

# Signal 3: SPY 12m (252d) return > 0 (momentum — positive = risk-on)
df['SPY_12m_ret'] = df['SPY'].pct_change(252)
df['sig_momentum'] = (df['SPY_12m_ret'] > 0).astype(int)

# Signal 4: HYG-TLT spread narrowing (credit condition)
# HYG outperforming TLT = credit improving = risk-on
# Use 63d (3-month) rolling relative return
df['hyg_tlt_rel'] = (df['HYG'] / df['TLT']).pct_change(63)
df['sig_credit'] = (df['hyg_tlt_rel'] > 0).astype(int)

# Signal 5: VIX term structure in contango proxy
# VIX 5d MA < VIX 20d MA means short-term fear fading = risk-on
df['VIX_5d'] = df['VIX'].rolling(5).mean()
df['VIX_20d'] = df['VIX'].rolling(20).mean()
df['sig_vix_contango'] = (df['VIX_5d'] < df['VIX_20d']).astype(int)

# Lag ALL signals by 1 day (use yesterday's signals for today's position)
signal_cols = ['sig_vix_low', 'sig_trend', 'sig_momentum', 'sig_credit', 'sig_vix_contango']
for col in signal_cols:
    df[col] = df[col].shift(1)

# Drop rows with NaN from rolling calculations + lagging
df = df.dropna()

# Composite score (0-5)
df['composite_score'] = df[signal_cols].sum(axis=1)

print(f"  Analysis period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# Signal distribution
print("\n  Composite Score Distribution:")
score_counts = df['composite_score'].value_counts().sort_index()
for score, count in score_counts.items():
    pct = count / len(df) * 100
    regime = "AGGRESSIVE" if score >= 4 else ("BALANCED" if score >= 2 else "DEFENSIVE")
    print(f"    Score {int(score)}: {count:5d} days ({pct:5.1f}%) → {regime}")

# Individual signal stats
print("\n  Individual Signal Risk-On % (lagged):")
for col in signal_cols:
    pct_on = df[col].mean() * 100
    print(f"    {col:20s}: {pct_on:5.1f}%")

# ============================================================
# 4. Build Regime Allocations
# ============================================================
print("\n[4] Building regime-based allocations...")

# Map composite score to SPY/GLD weights
def score_to_weights(score):
    """Map composite score (0-5) to SPY/GLD allocation."""
    if score >= 4:
        return 0.80, 0.20  # Aggressive
    elif score >= 2:
        return 0.50, 0.50  # Balanced
    else:
        return 0.20, 0.80  # Defensive

df['w_spy_regime'] = df['composite_score'].apply(lambda s: score_to_weights(s)[0])
df['w_gld_regime'] = df['composite_score'].apply(lambda s: score_to_weights(s)[1])

# Regime statistics
regime_labels = {
    'Aggressive (4-5)': df['composite_score'] >= 4,
    'Balanced (2-3)': (df['composite_score'] >= 2) & (df['composite_score'] < 4),
    'Defensive (0-1)': df['composite_score'] < 2,
}

print("\n  Regime allocation summary:")
for label, mask in regime_labels.items():
    days = mask.sum()
    pct = days / len(df) * 100
    print(f"    {label:20s}: {days:5d} days ({pct:5.1f}%)")

# ============================================================
# 5. Build All Strategy Returns
# ============================================================
print("\n[5] Building strategy return series...")

# --- Strategy 1: Multi-Signal Regime (daily rebalance within month buckets)
# For fair comparison, use monthly rebalance: on first trading day of month,
# lock in the regime weights for the whole month.
df['month'] = df.index.to_period('M')
monthly_weights = df.groupby('month')[['w_spy_regime', 'w_gld_regime']].first()
df['w_spy_monthly'] = df['month'].map(monthly_weights['w_spy_regime'])
df['w_gld_monthly'] = df['month'].map(monthly_weights['w_gld_regime'])

df['ret_regime'] = df['w_spy_monthly'] * df['SPY_ret'] + df['w_gld_monthly'] * df['GLD_ret']

# --- Strategy 2: Multi-Signal + VT overlay (12/VIX)
df['vt_weight'] = np.clip(12.0 / df['VIX'].shift(1), 0, 1.5)
df['ret_regime_vt'] = df['vt_weight'] * df['ret_regime']

# --- Strategy 3: 50/50 SPY/GLD (static benchmark)
df['ret_5050'] = 0.50 * df['SPY_ret'] + 0.50 * df['GLD_ret']

# --- Strategy 4: 50/50 + VT (12/VIX)
df['ret_5050_vt'] = df['vt_weight'] * df['ret_5050']

# --- Strategy 5: SPY Buy & Hold
df['ret_spy_bh'] = df['SPY_ret']

# --- Strategy 6: TSMOM 6_1 (6-month lookback, 1-month hold)
df['SPY_6m_ret'] = df['SPY'].pct_change(126)
df['tsmom_sig'] = df['SPY_6m_ret'].shift(1).apply(lambda x: 1.0 if x > 0 else 0.0)
# Monthly rebalance for TSMOM
tsmom_monthly = df.groupby('month')['tsmom_sig'].first()
df['tsmom_sig_monthly'] = df['month'].map(tsmom_monthly)
df['ret_tsmom'] = df['tsmom_sig_monthly'] * df['SPY_ret']

# --- Strategy 7: Single signal benchmarks (each signal alone)
# For each individual signal, use it alone as risk-on/risk-off (80/20 vs 20/80)
single_signal_rets = {}
for col in signal_cols:
    w_spy = df[col].apply(lambda s: 0.80 if s == 1 else 0.20)
    w_gld = 1 - w_spy
    # Monthly rebalance
    w_spy_m = df.groupby('month')[col].first().apply(lambda s: 0.80 if s == 1 else 0.20)
    w_gld_m = 1 - w_spy_m
    df[f'w_spy_{col}'] = df['month'].map(w_spy_m)
    df[f'w_gld_{col}'] = df['month'].map(1 - w_spy_m)
    df[f'ret_{col}'] = df[f'w_spy_{col}'] * df['SPY_ret'] + df[f'w_gld_{col}'] * df['GLD_ret']
    single_signal_rets[col] = f'ret_{col}'

# Clean up
df = df.dropna()
print(f"  Final analysis period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Final observations: {len(df)}")

# ============================================================
# 6. Performance Metrics Function
# ============================================================
def calc_metrics(returns, name, rf_annual=0.02):
    """Calculate comprehensive performance metrics."""
    r = returns.dropna()
    n = len(r)
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    rf_daily = rf_annual / 252
    sharpe = (r.mean() - rf_daily) / r.std() * np.sqrt(252) if r.std() > 0 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (ann_ret - rf_annual) / downside if downside > 0 else 0

    # Sharpe t-stat
    n_years = n / 252
    sharpe_t = sharpe * np.sqrt(n_years)

    # Turnover (monthly rebalance ≈ 12 rebalances/year)
    # Approximate from weight changes

    return {
        'name': name,
        'ann_ret': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'sharpe_t': sharpe_t,
        'mdd': mdd,
        'calmar': calmar,
        'sortino': sortino,
        'n_obs': n,
        'n_years': n_years,
    }


# ============================================================
# 7. Full-Sample Performance Comparison
# ============================================================
print("\n" + "=" * 70)
print("[6] FULL-SAMPLE PERFORMANCE COMPARISON")
print("=" * 70)

strategies = {
    'Multi-Signal Regime': 'ret_regime',
    'Multi-Signal + VT': 'ret_regime_vt',
    '50/50 SPY/GLD': 'ret_5050',
    '50/50 + VT': 'ret_5050_vt',
    'SPY B&H': 'ret_spy_bh',
    'TSMOM 6_1': 'ret_tsmom',
}

# Add single signals
signal_names = {
    'sig_vix_low': 'VIX<20 Only',
    'sig_trend': '200d MA Only',
    'sig_momentum': '12m Mom Only',
    'sig_credit': 'Credit Only',
    'sig_vix_contango': 'VIX Contango Only',
}

for col, nice_name in signal_names.items():
    strategies[nice_name] = f'ret_{col}'

full_metrics = {}
for name, col in strategies.items():
    m = calc_metrics(df[col], name)
    full_metrics[name] = m

# Print table
print(f"\n{'Strategy':<25s} {'Ann Ret':>8s} {'Ann Vol':>8s} {'Sharpe':>7s} {'t-stat':>7s} {'MDD':>8s} {'Calmar':>7s} {'Sortino':>8s}")
print("-" * 90)
for name in strategies:
    m = full_metrics[name]
    marker = " ***" if m['sharpe_t'] > 3.0 else (" **" if m['sharpe_t'] > 2.0 else "")
    print(f"{m['name']:<25s} {m['ann_ret']:>7.1%} {m['ann_vol']:>7.1%} {m['sharpe']:>7.3f} {m['sharpe_t']:>7.2f} {m['mdd']:>7.1%} {m['calmar']:>7.3f} {m['sortino']:>8.3f}{marker}")

# ============================================================
# 8. DM Tests: Multi-Signal vs Each Benchmark
# ============================================================
print("\n" + "=" * 70)
print("[7] DIEBOLD-MARIANO TESTS: Multi-Signal Regime vs Benchmarks")
print("=" * 70)

def dm_test_sharpe(r1, r2, h=1):
    """DM test on excess returns (Sharpe comparison).
    Tests H0: E[r1] = E[r2] vs H1: E[r1] > E[r2].
    Uses Newey-West HAC for autocorrelation.
    """
    d = r1 - r2
    d = d.dropna()
    n = len(d)
    d_mean = d.mean()

    # Newey-West HAC variance
    max_lag = int(np.ceil(n ** (1/3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * w * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 1 - stats.norm.cdf(t_stat)  # one-sided
    return t_stat, p_value

print(f"\n{'Comparison':<45s} {'DM t':>7s} {'p-value':>8s} {'Result':>12s}")
print("-" * 80)

regime_ret = df['ret_regime']
comparisons = [
    ('Multi-Signal vs 50/50', 'ret_5050'),
    ('Multi-Signal vs 50/50+VT', 'ret_5050_vt'),
    ('Multi-Signal vs SPY B&H', 'ret_spy_bh'),
    ('Multi-Signal vs TSMOM 6_1', 'ret_tsmom'),
    ('Multi-Signal+VT vs 50/50+VT', 'ret_5050_vt'),
]

# Also compare regime vs each single signal
for col, nice_name in signal_names.items():
    comparisons.append((f'Multi-Signal vs {nice_name}', f'ret_{col}'))

for label, bench_col in comparisons:
    if '+VT' in label.split(' vs ')[0] and bench_col == 'ret_5050_vt':
        r1 = df['ret_regime_vt']
    else:
        r1 = regime_ret
    r2 = df[bench_col]
    t, p = dm_test_sharpe(r1, r2)
    sig = "SIGNIFICANT" if p < 0.05 else "n.s."
    print(f"  {label:<43s} {t:>7.3f} {p:>8.4f} {sig:>12s}")

# ============================================================
# 9. Signal Correlation Analysis
# ============================================================
print("\n" + "=" * 70)
print("[8] SIGNAL CORRELATION MATRIX")
print("=" * 70)

corr = df[signal_cols].corr()
print(f"\n{'':>20s}", end="")
for c in signal_cols:
    print(f"{c[-12:]:>14s}", end="")
print()
for i, r in enumerate(signal_cols):
    print(f"{r[-18:]:>20s}", end="")
    for j, c in enumerate(signal_cols):
        print(f"{corr.loc[r, c]:>14.3f}", end="")
    print()

# ============================================================
# 10. Signal Contribution Analysis (Marginal Value)
# ============================================================
print("\n" + "=" * 70)
print("[9] MARGINAL VALUE OF EACH SIGNAL (Leave-One-Out)")
print("=" * 70)

# For each signal, compute the 4-signal composite (excluding that signal)
# and compare performance to full 5-signal composite
print(f"\n{'Excluded Signal':<25s} {'4-Sig Sharpe':>12s} {'5-Sig Sharpe':>12s} {'Delta':>8s} {'Marginal':>10s}")
print("-" * 70)

full_sharpe = full_metrics['Multi-Signal Regime']['sharpe']

for exclude_col in signal_cols:
    remaining_cols = [c for c in signal_cols if c != exclude_col]
    score_4 = df[remaining_cols].sum(axis=1)
    # Map 4-signal score (0-4) to weights
    w_spy_4 = score_4.apply(lambda s: 0.80 if s >= 3 else (0.50 if s >= 1.5 else 0.20))
    # Monthly rebalance
    temp_df = pd.DataFrame({'w': w_spy_4, 'month': df['month']})
    w_monthly = temp_df.groupby('month')['w'].first()
    w_spy_m = df['month'].map(w_monthly)
    ret_4 = w_spy_m * df['SPY_ret'] + (1 - w_spy_m) * df['GLD_ret']
    m_4 = calc_metrics(ret_4, f'excl_{exclude_col}')
    delta = full_sharpe - m_4['sharpe']
    direction = "ADDS VALUE" if delta > 0 else "DETRACTS"
    nice = signal_names.get(exclude_col, exclude_col)
    print(f"  {nice:<23s} {m_4['sharpe']:>12.4f} {full_sharpe:>12.4f} {delta:>+8.4f} {direction:>10s}")


# ============================================================
# 11. 5-Period Cross-OOS Validation
# ============================================================
print("\n" + "=" * 70)
print("[10] 5-PERIOD CROSS-OOS VALIDATION")
print("=" * 70)

# Define 5 OOS periods (each ~2 years, covering different market regimes)
oos_periods = [
    ('2009-01-01', '2011-12-31', 'Recovery 2009-11'),
    ('2012-01-01', '2014-12-31', 'Bull 2012-14'),
    ('2015-01-01', '2017-12-31', 'Mixed 2015-17'),
    ('2018-01-01', '2020-12-31', 'Crisis 2018-20'),
    ('2021-01-01', '2024-12-31', 'Post-COVID 21-24'),
]

oos_results = []

print(f"\n{'Period':<22s} {'Regime Sharpe':>13s} {'5050 Sharpe':>12s} {'5050VT Sharpe':>13s} {'SPYBH Sharpe':>12s} {'Regime Wins':>12s}")
print("-" * 90)

key_strategies_oos = {
    'Multi-Signal Regime': 'ret_regime',
    '50/50 SPY/GLD': 'ret_5050',
    '50/50 + VT': 'ret_5050_vt',
    'SPY B&H': 'ret_spy_bh',
}

regime_wins = 0
regime_total = 0

for start, end, label in oos_periods:
    mask = (df.index >= start) & (df.index <= end)
    sub = df[mask]
    if len(sub) < 100:
        print(f"  {label:<20s} — insufficient data ({len(sub)} obs)")
        continue

    period_metrics = {}
    for sname, scol in key_strategies_oos.items():
        m = calc_metrics(sub[scol], sname)
        period_metrics[sname] = m

    r_sharpe = period_metrics['Multi-Signal Regime']['sharpe']
    b1_sharpe = period_metrics['50/50 SPY/GLD']['sharpe']
    b2_sharpe = period_metrics['50/50 + VT']['sharpe']
    b3_sharpe = period_metrics['SPY B&H']['sharpe']

    # Count wins vs 50/50
    wins = 0
    total = 3
    if r_sharpe > b1_sharpe:
        wins += 1
    if r_sharpe > b2_sharpe:
        wins += 1
    if r_sharpe > b3_sharpe:
        wins += 1

    regime_wins += wins
    regime_total += total

    win_str = f"{wins}/{total}"
    print(f"  {label:<20s} {r_sharpe:>13.3f} {b1_sharpe:>12.3f} {b2_sharpe:>13.3f} {b3_sharpe:>12.3f} {win_str:>12s}")

    oos_results.append({
        'period': label,
        'start': start,
        'end': end,
        'n_obs': len(sub),
        'regime_sharpe': r_sharpe,
        'regime_mdd': period_metrics['Multi-Signal Regime']['mdd'],
        '5050_sharpe': b1_sharpe,
        '5050vt_sharpe': b2_sharpe,
        'spy_sharpe': b3_sharpe,
        'wins': wins,
        'total': total,
    })

print(f"\n  Overall OOS win rate vs benchmarks: {regime_wins}/{regime_total} ({regime_wins/regime_total*100:.1f}%)")

# ============================================================
# 12. OOS DM Tests Per Period
# ============================================================
print("\n" + "=" * 70)
print("[11] OOS DM TESTS: Multi-Signal Regime vs 50/50 (per period)")
print("=" * 70)

print(f"\n{'Period':<22s} {'DM t':>7s} {'p-value':>8s} {'Result':>12s}")
print("-" * 55)

oos_dm_wins = 0
for start, end, label in oos_periods:
    mask = (df.index >= start) & (df.index <= end)
    sub = df[mask]
    if len(sub) < 100:
        continue
    t, p = dm_test_sharpe(sub['ret_regime'], sub['ret_5050'])
    sig = "SIG (p<.05)" if p < 0.05 else "n.s."
    if p < 0.05:
        oos_dm_wins += 1
    print(f"  {label:<20s} {t:>7.3f} {p:>8.4f} {sig:>12s}")

print(f"\n  Significant OOS periods: {oos_dm_wins}/{len(oos_periods)}")

# ============================================================
# 13. Regime Timing Analysis — Does the regime switch at the right time?
# ============================================================
print("\n" + "=" * 70)
print("[12] REGIME TIMING ANALYSIS")
print("=" * 70)

# Average return by regime
print("\n  Average daily return by regime allocation:")
for label, mask in regime_labels.items():
    sub = df[mask]
    avg_spy = sub['SPY_ret'].mean() * 252 * 100
    avg_gld = sub['GLD_ret'].mean() * 252 * 100
    avg_regime = sub['ret_regime'].mean() * 252 * 100
    print(f"    {label:<20s}: SPY ann={avg_spy:>+6.1f}%, GLD ann={avg_gld:>+6.1f}%, Regime ann={avg_regime:>+6.1f}%")

# Transition matrix
print("\n  Monthly regime transition matrix:")
monthly_regime = df.groupby('month')['composite_score'].first()
regime_cat = monthly_regime.apply(lambda s: 'A(4-5)' if s >= 4 else ('B(2-3)' if s >= 2 else 'D(0-1)'))
transitions = pd.crosstab(regime_cat.shift(1).dropna(), regime_cat.iloc[1:], normalize='index')
print(transitions.to_string())

# ============================================================
# 14. Harvey Threshold Check
# ============================================================
print("\n" + "=" * 70)
print("[13] HARVEY (2016) THRESHOLD CHECK (t > 3.0)")
print("=" * 70)

# Test if Multi-Signal Regime alpha is significant
# Alpha = regime return - 50/50 return (excess return over passive benchmark)
alpha = df['ret_regime'] - df['ret_5050']
alpha_mean = alpha.mean()
alpha_se = alpha.std() / np.sqrt(len(alpha))
alpha_t = alpha_mean / alpha_se
alpha_ann = alpha_mean * 252

print(f"\n  Multi-Signal Regime alpha vs 50/50 SPY/GLD:")
print(f"    Annualized alpha:     {alpha_ann:>+.4f} ({alpha_ann*100:>+.2f}%)")
print(f"    t-statistic:          {alpha_t:>+.3f}")
print(f"    Harvey threshold:     3.000")
print(f"    PASS Harvey?          {'YES' if abs(alpha_t) > 3.0 else 'NO'}")

# Also check regime+VT vs 50/50+VT
alpha_vt = df['ret_regime_vt'] - df['ret_5050_vt']
alpha_vt_mean = alpha_vt.mean()
alpha_vt_se = alpha_vt.std() / np.sqrt(len(alpha_vt))
alpha_vt_t = alpha_vt_mean / alpha_vt_se
alpha_vt_ann = alpha_vt_mean * 252

print(f"\n  Multi-Signal+VT alpha vs 50/50+VT:")
print(f"    Annualized alpha:     {alpha_vt_ann:>+.4f} ({alpha_vt_ann*100:>+.2f}%)")
print(f"    t-statistic:          {alpha_vt_t:>+.3f}")
print(f"    PASS Harvey?          {'YES' if abs(alpha_vt_t) > 3.0 else 'NO'}")

# ============================================================
# 15. Bootstrap Confidence Intervals for Sharpe Difference
# ============================================================
print("\n" + "=" * 70)
print("[14] BOOTSTRAP CI FOR SHARPE DIFFERENCE (Regime vs 50/50)")
print("=" * 70)

n_boot = 10000
np.random.seed(42)
boot_sharpe_diff = []
r_regime = df['ret_regime'].values
r_5050 = df['ret_5050'].values
n = len(r_regime)

for _ in range(n_boot):
    idx = np.random.choice(n, size=n, replace=True)
    s_r = r_regime[idx].mean() / r_regime[idx].std() * np.sqrt(252)
    s_b = r_5050[idx].mean() / r_5050[idx].std() * np.sqrt(252)
    boot_sharpe_diff.append(s_r - s_b)

boot_sharpe_diff = np.array(boot_sharpe_diff)
ci_lo = np.percentile(boot_sharpe_diff, 2.5)
ci_hi = np.percentile(boot_sharpe_diff, 97.5)
boot_mean = boot_sharpe_diff.mean()
pct_positive = (boot_sharpe_diff > 0).mean() * 100

print(f"  Bootstrap (n={n_boot}):")
print(f"    Mean Sharpe diff:     {boot_mean:>+.4f}")
print(f"    95% CI:               [{ci_lo:>+.4f}, {ci_hi:>+.4f}]")
print(f"    % positive:           {pct_positive:.1f}%")
print(f"    CI includes zero?     {'YES (NOT significant)' if ci_lo <= 0 <= ci_hi else 'NO (Significant)'}")

# ============================================================
# 16. Crisis Period Specific Analysis
# ============================================================
print("\n" + "=" * 70)
print("[15] CRISIS PERIOD ANALYSIS")
print("=" * 70)

crises = [
    ('2008-09-01', '2009-03-31', 'GFC (Sep08-Mar09)'),
    ('2011-07-01', '2011-10-31', 'EU Debt (Jul-Oct 11)'),
    ('2015-08-01', '2015-10-31', 'China Deval (Aug-Oct 15)'),
    ('2018-10-01', '2018-12-31', 'Vol Shock (Oct-Dec 18)'),
    ('2020-02-15', '2020-04-30', 'COVID (Feb-Apr 20)'),
    ('2022-01-01', '2022-10-31', 'Rate Hike (Jan-Oct 22)'),
]

print(f"\n{'Crisis':<25s} {'Regime MDD':>10s} {'50/50 MDD':>10s} {'SPY MDD':>10s} {'Regime Ret':>10s} {'50/50 Ret':>10s}")
print("-" * 80)

for start, end, label in crises:
    mask = (df.index >= start) & (df.index <= end)
    sub = df[mask]
    if len(sub) < 10:
        continue

    # MDD for each strategy
    for col_name, col in [('regime', 'ret_regime'), ('5050', 'ret_5050'), ('spy', 'ret_spy_bh')]:
        cum = (1 + sub[col]).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        if col_name == 'regime':
            r_mdd = dd.min()
            r_ret = cum.iloc[-1] - 1
        elif col_name == '5050':
            b_mdd = dd.min()
            b_ret = cum.iloc[-1] - 1
        else:
            s_mdd = dd.min()

    print(f"  {label:<23s} {r_mdd:>9.1%} {b_mdd:>9.1%} {s_mdd:>9.1%} {r_ret:>9.1%} {b_ret:>9.1%}")

# ============================================================
# 17. Turnover Analysis
# ============================================================
print("\n" + "=" * 70)
print("[16] TURNOVER ANALYSIS")
print("=" * 70)

# Calculate monthly weight changes for regime strategy
monthly_w = df.groupby('month')['w_spy_monthly'].first()
turnover = abs(monthly_w.diff()).dropna()
annual_turnover = turnover.mean() * 12  # annualized

# 50/50 has zero turnover (static)
# TSMOM
monthly_tsmom = df.groupby('month')['tsmom_sig_monthly'].first()
turnover_tsmom = abs(monthly_tsmom.diff()).dropna()
annual_turnover_tsmom = turnover_tsmom.mean() * 12

print(f"\n  Multi-Signal Regime:")
print(f"    Mean monthly turnover:  {turnover.mean():.4f}")
print(f"    Annualized turnover:    {annual_turnover:.4f}")
print(f"    Avg regime changes/yr:  {(turnover > 0).sum() / (len(monthly_w)/12):.1f}")
print(f"\n  TSMOM 6_1:")
print(f"    Mean monthly turnover:  {turnover_tsmom.mean():.4f}")
print(f"    Annualized turnover:    {annual_turnover_tsmom:.4f}")

# Estimate transaction cost impact
tc_bps = 10  # 10 bps round-trip
tc_annual_regime = annual_turnover * tc_bps / 10000
tc_annual_tsmom = annual_turnover_tsmom * tc_bps / 10000

print(f"\n  Est. annual TC (10 bps round-trip):")
print(f"    Regime strategy:        {tc_annual_regime*100:.3f}%")
print(f"    TSMOM:                  {tc_annual_tsmom*100:.3f}%")

# Net Sharpe
regime_m = full_metrics['Multi-Signal Regime']
net_sharpe_regime = (regime_m['ann_ret'] - tc_annual_regime - 0.02) / regime_m['ann_vol']
print(f"\n  Net Sharpe (after TC):")
print(f"    Multi-Signal Regime:    {net_sharpe_regime:.4f} (gross: {regime_m['sharpe']:.4f})")

# ============================================================
# 18. Comprehensive Summary
# ============================================================
print("\n" + "=" * 70)
print("[17] COMPREHENSIVE SUMMARY")
print("=" * 70)

r_m = full_metrics['Multi-Signal Regime']
b_m = full_metrics['50/50 SPY/GLD']
vt_m = full_metrics['50/50 + VT']
spy_m = full_metrics['SPY B&H']

print(f"""
  Research Question: Does combining 5 risk signals into a composite regime
  classifier add value over simple 50/50 or individual signals?

  DATA SOURCE: yfinance (real market data)
  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} obs)
  Assets: SPY, GLD, TLT, VIX, HYG (all real ETF/index data)

  FULL-SAMPLE RESULTS:
    Multi-Signal Regime:  Sharpe={r_m['sharpe']:.3f}, MDD={r_m['mdd']:.1%}, Ann Ret={r_m['ann_ret']:.1%}
    50/50 SPY/GLD:        Sharpe={b_m['sharpe']:.3f}, MDD={b_m['mdd']:.1%}, Ann Ret={b_m['ann_ret']:.1%}
    50/50 + VT:           Sharpe={vt_m['sharpe']:.3f}, MDD={vt_m['mdd']:.1%}, Ann Ret={vt_m['ann_ret']:.1%}
    SPY B&H:              Sharpe={spy_m['sharpe']:.3f}, MDD={spy_m['mdd']:.1%}, Ann Ret={spy_m['ann_ret']:.1%}

  ALPHA vs 50/50:
    Annualized alpha:     {alpha_ann*100:>+.2f}%
    t-statistic:          {alpha_t:>+.3f}
    Harvey (t>3.0):       {'PASS' if abs(alpha_t) > 3.0 else 'FAIL'}

  BOOTSTRAP (n=10,000):
    Sharpe diff mean:     {boot_mean:>+.4f}
    95% CI:               [{ci_lo:>+.4f}, {ci_hi:>+.4f}]
    Significant:          {'YES' if ci_lo > 0 or ci_hi < 0 else 'NO'}

  CROSS-OOS (5 periods):
    Win rate vs benchmarks: {regime_wins}/{regime_total} ({regime_wins/regime_total*100:.1f}%)
    DM significant periods: {oos_dm_wins}/5

  VERDICT: """, end="")

# Determine verdict
if abs(alpha_t) > 3.0 and regime_wins / regime_total > 0.6:
    verdict = "SIGNIFICANT — Multi-signal regime adds value over static allocation"
elif r_m['sharpe'] > b_m['sharpe'] and boot_mean > 0:
    verdict = "MARGINAL — Slight improvement but not statistically significant (fails Harvey)"
elif r_m['sharpe'] <= b_m['sharpe']:
    verdict = "NULL — Multi-signal regime does NOT beat simple 50/50"
else:
    verdict = "INCONCLUSIVE — Mixed results across periods"

print(verdict)

print(f"""
  LIMITATIONS:
    - VIX term structure proxied by 5d/20d MA (no actual VIX futures data)
    - Monthly rebalance (daily rebalance would differ)
    - HYG only available from 2007 (limits analysis period)
    - Transaction costs estimated at 10 bps (actual may vary)
    - Single asset pair (SPY/GLD); multi-asset extension not tested
    - No VT overlay optimization (used standard 12/VIX)
""")

# ============================================================
# 19. Save Results
# ============================================================
results = {
    'experiment': 'K249',
    'title': 'Risk-On/Risk-Off Regime Trading — Multi-Signal Regime Classification',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (real market data)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(df),
    'assets': ['SPY', 'GLD', 'TLT', 'VIX', 'HYG'],
    'signals': signal_cols,
    'full_sample': {name: {k: float(v) if isinstance(v, (np.floating, float)) else v
                           for k, v in m.items()}
                    for name, m in full_metrics.items()},
    'alpha_vs_5050': {
        'annualized': float(alpha_ann),
        't_stat': float(alpha_t),
        'passes_harvey': bool(abs(alpha_t) > 3.0),
    },
    'alpha_vt_vs_5050vt': {
        'annualized': float(alpha_vt_ann),
        't_stat': float(alpha_vt_t),
        'passes_harvey': bool(abs(alpha_vt_t) > 3.0),
    },
    'bootstrap': {
        'n_boot': n_boot,
        'mean_sharpe_diff': float(boot_mean),
        'ci_95_lo': float(ci_lo),
        'ci_95_hi': float(ci_hi),
        'pct_positive': float(pct_positive),
    },
    'cross_oos': oos_results,
    'oos_win_rate': f"{regime_wins}/{regime_total}",
    'oos_dm_significant': oos_dm_wins,
    'turnover_annual': float(annual_turnover),
    'net_sharpe_after_tc': float(net_sharpe_regime),
    'verdict': verdict,
}

# Convert any remaining numpy types
def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(i) for i in obj]
    return obj

results = convert_numpy(results)

output_path = 'experiments/k249_risk_on_off_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 70)
print("K249 COMPLETE")
print("=" * 70)
