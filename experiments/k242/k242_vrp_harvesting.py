"""
K242: Volatility Risk Premium Harvesting — Short Vol as Alpha Source

Background:
- K208 found VRP = +2.9%/yr (VIX > realized vol 83% of time)
- Can we systematically harvest this premium?
- This is the basis of many hedge fund strategies (e.g., selling straddles/strangles)

Data: SPY, VIX, SVXY (inverse VIX ETF) daily from yfinance. 2012-2024.

Methodology:
1. VRP signal: VIX / realized_vol_22d ratio
   - VRP > 1: market overpricing risk → short vol profitable
   - VRP < 1: market underpricing risk → avoid short vol
2. Strategy variants:
   a. Simple: always short vol (constant VRP harvest)
   b. Conditional: short vol only when VRP > 1.2 (high premium)
   c. VRP-timed: weight = min(1, VRP - 1) proportional to premium
   d. Combined: 50% SPY + 50% VRP harvest
   e. 50/50 SPY/GLD + VRP overlay
3. Short vol proxy: SVXY (ProShares Short VIX Short-Term Futures ETF)
   - If SVXY unavailable, use synthetic: -1 × daily VIX pct change (capped)
4. Compare vs 50/50+VT, SPY B&H
5. Risk: VRP harvesting has EXTREME tail risk (Volmageddon 2018)
   - Must track worst single day/week
   - Feb 5, 2018 episode explicitly
6. 5-period cross-OOS

CRITICAL: This strategy has known tail risk. Report max 1-day loss,
max 1-week loss, and 2018 Feb episode explicitly.

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
print("K242: Volatility Risk Premium Harvesting — Short Vol as Alpha Source")
print("=" * 70)

print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2011-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2011-01-01", end="2025-01-01", progress=False)
gld = yf.download("GLD", start="2011-01-01", end="2025-01-01", progress=False)

# Try SVXY (inverse VIX ETF, available from Oct 2011)
try:
    svxy = yf.download("SVXY", start="2011-01-01", end="2025-01-01", progress=False)
    if isinstance(svxy.columns, pd.MultiIndex):
        svxy.columns = svxy.columns.get_level_values(0)
    has_svxy = len(svxy) > 100
    if has_svxy:
        print(f"  SVXY data: {len(svxy)} days ({svxy.index[0].strftime('%Y-%m-%d')} to {svxy.index[-1].strftime('%Y-%m-%d')})")
except Exception:
    has_svxy = False

# Handle multi-level columns
for df_tmp in [spy, vix, gld]:
    if isinstance(df_tmp.columns, pd.MultiIndex):
        df_tmp.columns = df_tmp.columns.get_level_values(0)

# Build master dataframe
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
df['gld_close'] = gld['Close'].reindex(spy.index, method='ffill')
df['gld_return'] = np.log(df['gld_close'] / df['gld_close'].shift(1))

if has_svxy:
    df['svxy_close'] = svxy['Close'].reindex(spy.index, method='ffill')
    df['svxy_return'] = np.log(df['svxy_close'] / df['svxy_close'].shift(1))

df = df.dropna(subset=['spy_return', 'vix'])
print(f"  SPY data: {len(spy)} days")
print(f"  VIX data: {len(vix)} days")
print(f"  Combined: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Calculate VRP Components
# ============================================================
print("\n[2] Calculating VRP components...")

# 22-day realized vol (annualized, in %)
df['rv_22d'] = df['spy_return'].rolling(22).std() * np.sqrt(252) * 100

# VRP ratio = VIX / RV (both annualized)
df['vrp_ratio'] = df['vix'] / df['rv_22d']

# VRP level = VIX - RV (in %)
df['vrp_level'] = df['vix'] - df['rv_22d']

df = df.dropna(subset=['rv_22d', 'vrp_ratio'])
print(f"  After VRP calc: {len(df)} obs ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

# VRP summary statistics
vrp_positive_pct = (df['vrp_level'] > 0).mean() * 100
vrp_mean = df['vrp_level'].mean()
vrp_median = df['vrp_level'].median()
print(f"\n  VRP Summary:")
print(f"    VIX > RV (VRP positive): {vrp_positive_pct:.1f}% of time")
print(f"    Mean VRP level: {vrp_mean:.2f}%")
print(f"    Median VRP level: {vrp_median:.2f}%")
print(f"    Mean VRP ratio: {df['vrp_ratio'].mean():.3f}")
print(f"    VRP > 1.2 (high premium): {(df['vrp_ratio'] > 1.2).mean()*100:.1f}% of time")

# ============================================================
# 3. Short Vol Proxy Construction
# ============================================================
print("\n[3] Constructing short vol proxy...")

# Method 1: SVXY returns (actual inverse VIX ETF)
if has_svxy:
    # SVXY is already -0.5x VIX futures since 2018 reset (was -1x before)
    # We use it directly as our short vol proxy
    df['short_vol_return'] = df['svxy_return']
    # Clip extreme returns for safety
    df['short_vol_return'] = df['short_vol_return'].clip(-0.5, 0.5)
    short_vol_method = "SVXY (inverse VIX ETF)"
    print(f"  Using SVXY as short vol proxy")
    print(f"  SVXY mean daily return: {df['short_vol_return'].mean()*252*100:.2f}%/yr")
    print(f"  SVXY daily vol: {df['short_vol_return'].std()*np.sqrt(252)*100:.1f}%")
else:
    # Method 2: Synthetic - daily VIX pct change (inverted)
    df['vix_pct_change'] = df['vix'].pct_change()
    df['short_vol_return'] = -df['vix_pct_change'] * 0.5  # scale down for realism
    df['short_vol_return'] = df['short_vol_return'].clip(-0.3, 0.3)
    short_vol_method = "Synthetic (-0.5x VIX daily change)"
    print(f"  SVXY not available, using synthetic proxy")
    print(f"  Synthetic mean daily return: {df['short_vol_return'].mean()*252*100:.2f}%/yr")

df = df.dropna(subset=['short_vol_return'])

# ============================================================
# 4. Strategy Definitions (all use LAGGED signals to avoid look-ahead)
# ============================================================
print("\n[4] Defining strategies...")

# CRITICAL: Use lagged VRP signal (yesterday's VRP → today's position)
df['vrp_ratio_lag'] = df['vrp_ratio'].shift(1)
df['vrp_level_lag'] = df['vrp_level'].shift(1)
df['vix_lag'] = df['vix'].shift(1)

# Strategy A: Always short vol (constant VRP harvest)
df['strat_a_ret'] = df['short_vol_return']

# Strategy B: Conditional — short vol only when VRP ratio > 1.2
df['strat_b_weight'] = (df['vrp_ratio_lag'] > 1.2).astype(float)
df['strat_b_ret'] = df['strat_b_weight'] * df['short_vol_return']

# Strategy C: VRP-timed — weight proportional to premium
df['strat_c_weight'] = (df['vrp_ratio_lag'] - 1.0).clip(0, 1)
df['strat_c_ret'] = df['strat_c_weight'] * df['short_vol_return']

# Strategy D: 50% SPY + 50% VRP harvest (conditional)
df['strat_d_ret'] = 0.5 * df['spy_return'] + 0.5 * df['strat_b_ret']

# Strategy E: 50/50 SPY/GLD base + 10% VRP overlay
# (reduce cash, add short vol when VRP high)
df['base_5050'] = 0.5 * df['spy_return'] + 0.5 * df['gld_return']
df['strat_e_weight'] = ((df['vrp_ratio_lag'] > 1.2) & (df['vix_lag'] < 30)).astype(float) * 0.10
df['strat_e_ret'] = df['base_5050'] + df['strat_e_weight'] * df['short_vol_return']

# Benchmarks
# 12/VIX VT (lagged)
df['vt_weight'] = (12.0 / df['vix_lag']).clip(0, 1)
df['vt_spy_ret'] = df['vt_weight'] * df['spy_return']
df['bench_5050vt'] = 0.5 * df['vt_spy_ret'] + 0.5 * df['gld_return'] * df['vt_weight']

# SPY buy & hold
df['bench_spy'] = df['spy_return']

# 50/50 SPY/GLD
df['bench_5050'] = df['base_5050']

df = df.dropna()

# ============================================================
# 5. Performance Metrics Function
# ============================================================
def calc_metrics(returns, name, rf_annual=0.04):
    """Calculate comprehensive performance metrics."""
    r = returns.dropna()
    n_years = len(r) / 252

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()
    mdd_date = dd.idxmin()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252) if (r < 0).any() else 1
    sortino = (ann_ret - rf_annual) / downside

    # Worst day / week
    worst_day = r.min()
    worst_day_date = r.idxmin()

    # 5-day rolling returns for worst week
    r_5d = r.rolling(5).sum()
    worst_week = r_5d.min()
    worst_week_date = r_5d.idxmin()

    # Win rate
    win_rate = (r > 0).mean()

    # Skewness / kurtosis
    skew = r.skew()
    kurt = r.kurtosis()

    # Sharpe SE and t-stat
    sharpe_se = np.sqrt((1 + 0.5 * sharpe**2) / len(r)) * np.sqrt(252)
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'sharpe_t': sharpe_t,
        'sortino': sortino,
        'mdd': mdd,
        'mdd_date': str(mdd_date)[:10] if pd.notna(mdd_date) else 'N/A',
        'calmar': calmar,
        'worst_day': worst_day,
        'worst_day_date': str(worst_day_date)[:10] if pd.notna(worst_day_date) else 'N/A',
        'worst_week': worst_week,
        'worst_week_date': str(worst_week_date)[:10] if pd.notna(worst_week_date) else 'N/A',
        'win_rate': win_rate,
        'skewness': skew,
        'kurtosis': kurt,
        'n_years': n_years,
        'n_obs': len(r),
    }


def print_metrics(m):
    """Pretty print metrics."""
    print(f"\n  {m['name']}")
    print(f"    Return: {m['ann_return']*100:.2f}%/yr | Vol: {m['ann_vol']*100:.1f}%")
    print(f"    Sharpe: {m['sharpe']:.3f} (t={m['sharpe_t']:.2f})")
    print(f"    Sortino: {m['sortino']:.3f} | Calmar: {m['calmar']:.3f}")
    print(f"    MDD: {m['mdd']*100:.1f}% ({m['mdd_date']})")
    print(f"    Worst day: {m['worst_day']*100:.2f}% ({m['worst_day_date']})")
    print(f"    Worst week: {m['worst_week']*100:.2f}% ({m['worst_week_date']})")
    print(f"    Win rate: {m['win_rate']*100:.1f}% | Skew: {m['skewness']:.2f} | Kurt: {m['kurtosis']:.1f}")


# ============================================================
# 6. Full Sample Analysis
# ============================================================
print("\n" + "=" * 70)
print("[5] Full Sample Performance")
print("=" * 70)

strategies = {
    'A: Always Short Vol': 'strat_a_ret',
    'B: Conditional (VRP>1.2)': 'strat_b_ret',
    'C: VRP-Timed (proportional)': 'strat_c_ret',
    'D: 50% SPY + 50% VRP(cond)': 'strat_d_ret',
    'E: 50/50+VRP overlay(10%)': 'strat_e_ret',
    'BM1: SPY B&H': 'bench_spy',
    'BM2: 50/50 SPY/GLD': 'bench_5050',
    'BM3: 50/50+VT (12/VIX)': 'bench_5050vt',
}

full_metrics = {}
for name, col in strategies.items():
    m = calc_metrics(df[col], name)
    print_metrics(m)
    full_metrics[name] = m

# ============================================================
# 7. Volmageddon Analysis (Feb 2018)
# ============================================================
print("\n" + "=" * 70)
print("[6] Volmageddon Episode (Feb 2018)")
print("=" * 70)

# Feb 2018 crisis: VIX went from ~13 to ~37 in one day (Feb 5, 2018)
volmageddon_start = '2018-01-26'
volmageddon_end = '2018-02-28'
mask = (df.index >= volmageddon_start) & (df.index <= volmageddon_end)
volma_df = df[mask]

if len(volma_df) > 0:
    print(f"\n  Period: {volmageddon_start} to {volmageddon_end} ({len(volma_df)} days)")

    # Find the worst day for short vol
    print(f"\n  VIX during episode:")
    print(f"    VIX start: {volma_df['vix'].iloc[0]:.1f}")
    print(f"    VIX peak: {volma_df['vix'].max():.1f}")
    print(f"    VIX peak date: {volma_df['vix'].idxmax().strftime('%Y-%m-%d')}")

    for name, col in strategies.items():
        if 'BM' in name:
            continue
        ep_ret = volma_df[col]
        cum_ret = (1 + ep_ret).prod() - 1
        worst_day = ep_ret.min()
        worst_day_date = ep_ret.idxmin()
        print(f"\n  {name}:")
        print(f"    Cumulative return: {cum_ret*100:.2f}%")
        print(f"    Worst single day: {worst_day*100:.2f}% ({worst_day_date.strftime('%Y-%m-%d')})")

# ============================================================
# 8. COVID Crash (March 2020)
# ============================================================
print("\n" + "=" * 70)
print("[7] COVID Crash Episode (Feb-Mar 2020)")
print("=" * 70)

covid_start = '2020-02-19'
covid_end = '2020-04-01'
mask_covid = (df.index >= covid_start) & (df.index <= covid_end)
covid_df = df[mask_covid]

if len(covid_df) > 0:
    print(f"\n  Period: {covid_start} to {covid_end} ({len(covid_df)} days)")
    print(f"  VIX start: {covid_df['vix'].iloc[0]:.1f}")
    print(f"  VIX peak: {covid_df['vix'].max():.1f} ({covid_df['vix'].idxmax().strftime('%Y-%m-%d')})")

    for name, col in strategies.items():
        if 'BM' in name:
            continue
        ep_ret = covid_df[col]
        cum_ret = (1 + ep_ret).prod() - 1
        worst_day = ep_ret.min()
        print(f"  {name}: cum={cum_ret*100:.1f}%, worst_day={worst_day*100:.2f}%")

# ============================================================
# 9. Five-Period Cross-OOS Validation
# ============================================================
print("\n" + "=" * 70)
print("[8] 5-Period Cross-OOS Validation")
print("=" * 70)

# Define 5 OOS periods (each ~2 years)
oos_periods = [
    ('2012-01-01', '2013-12-31', 'OOS1: 2012-2013'),
    ('2014-01-01', '2015-12-31', 'OOS2: 2014-2015'),
    ('2016-01-01', '2017-12-31', 'OOS3: 2016-2017'),
    ('2018-01-01', '2019-12-31', 'OOS4: 2018-2019 (Volmageddon)'),
    ('2020-01-01', '2022-12-31', 'OOS5: 2020-2022 (COVID+Inflation)'),
]

oos_results = {}
test_strategies = {
    'B: Conditional (VRP>1.2)': 'strat_b_ret',
    'C: VRP-Timed (proportional)': 'strat_c_ret',
    'D: 50% SPY + 50% VRP(cond)': 'strat_d_ret',
    'E: 50/50+VRP overlay(10%)': 'strat_e_ret',
}
benchmarks_oos = {
    'BM1: SPY B&H': 'bench_spy',
    'BM2: 50/50 SPY/GLD': 'bench_5050',
    'BM3: 50/50+VT': 'bench_5050vt',
}

for start, end, label in oos_periods:
    mask = (df.index >= start) & (df.index <= end)
    oos_df = df[mask]
    if len(oos_df) < 100:
        print(f"\n  {label}: insufficient data ({len(oos_df)} obs), skipping")
        continue

    print(f"\n  {label} ({len(oos_df)} obs)")
    print(f"  {'Strategy':<28} {'Return':>8} {'Sharpe':>8} {'MDD':>8} {'Worst Day':>10}")
    print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    period_results = {}
    all_strats = {**test_strategies, **benchmarks_oos}
    for sname, col in all_strats.items():
        m = calc_metrics(oos_df[col], sname)
        marker = '***' if sname in benchmarks_oos else '   '
        print(f"  {marker}{sname:<25} {m['ann_return']*100:>7.2f}% {m['sharpe']:>8.3f} {m['mdd']*100:>7.1f}% {m['worst_day']*100:>9.2f}%")
        period_results[sname] = m

    oos_results[label] = period_results

# ============================================================
# 10. Cross-OOS Summary: Strategy B wins vs benchmarks?
# ============================================================
print("\n" + "=" * 70)
print("[9] Cross-OOS Win Count Summary")
print("=" * 70)

print(f"\n  Sharpe wins (strategy > benchmark):")
print(f"  {'Strategy':<28} {'vs SPY':>8} {'vs 50/50':>8} {'vs 50/50+VT':>11}")
print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*11}")

for sname in test_strategies:
    wins_spy = 0
    wins_5050 = 0
    wins_vt = 0
    n_periods = 0
    for label, period_results in oos_results.items():
        if sname in period_results and 'BM1: SPY B&H' in period_results:
            n_periods += 1
            if period_results[sname]['sharpe'] > period_results['BM1: SPY B&H']['sharpe']:
                wins_spy += 1
            if period_results[sname]['sharpe'] > period_results['BM2: 50/50 SPY/GLD']['sharpe']:
                wins_5050 += 1
            if period_results[sname]['sharpe'] > period_results['BM3: 50/50+VT']['sharpe']:
                wins_vt += 1
    print(f"  {sname:<28} {wins_spy}/{n_periods:>5} {wins_5050}/{n_periods:>5} {wins_vt}/{n_periods:>8}")

print(f"\n  MDD wins (less drawdown than benchmark):")
print(f"  {'Strategy':<28} {'vs SPY':>8} {'vs 50/50':>8} {'vs 50/50+VT':>11}")
print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*11}")

for sname in test_strategies:
    wins_spy = 0
    wins_5050 = 0
    wins_vt = 0
    n_periods = 0
    for label, period_results in oos_results.items():
        if sname in period_results and 'BM1: SPY B&H' in period_results:
            n_periods += 1
            if period_results[sname]['mdd'] > period_results['BM1: SPY B&H']['mdd']:
                wins_spy += 1
            if period_results[sname]['mdd'] > period_results['BM2: 50/50 SPY/GLD']['mdd']:
                wins_5050 += 1
            if period_results[sname]['mdd'] > period_results['BM3: 50/50+VT']['mdd']:
                wins_vt += 1
    print(f"  {sname:<28} {wins_spy}/{n_periods:>5} {wins_5050}/{n_periods:>5} {wins_vt}/{n_periods:>8}")


# ============================================================
# 11. Tail Risk Analysis
# ============================================================
print("\n" + "=" * 70)
print("[10] Tail Risk Deep Dive")
print("=" * 70)

for sname, col in {**test_strategies, 'A: Always Short Vol (SVXY)': 'strat_a_ret'}.items():
    r = df[col].dropna()
    print(f"\n  {sname}:")
    # Percentiles
    p1 = np.percentile(r, 1)
    p5 = np.percentile(r, 5)
    p99 = np.percentile(r, 99)
    print(f"    1st percentile (daily): {p1*100:.3f}%")
    print(f"    5th percentile (daily): {p5*100:.3f}%")
    print(f"    99th percentile (daily): {p99*100:.3f}%")

    # Days with >5% loss
    big_loss_days = (r < -0.05).sum()
    print(f"    Days with >5% loss: {big_loss_days}")

    # Days with >10% loss
    huge_loss_days = (r < -0.10).sum()
    print(f"    Days with >10% loss: {huge_loss_days}")

    # Worst 5 days
    worst5 = r.nsmallest(5)
    print(f"    Worst 5 days:")
    for date, ret in worst5.items():
        print(f"      {str(date)[:10]}: {ret*100:.2f}%")


# ============================================================
# 12. VRP Regime Analysis
# ============================================================
print("\n" + "=" * 70)
print("[11] VRP Regime Analysis")
print("=" * 70)

# Analyze short vol returns conditional on VRP regime
regimes = {
    'VRP < 0.8 (vol underpriced)': df['vrp_ratio_lag'] < 0.8,
    'VRP 0.8-1.0 (near fair)': (df['vrp_ratio_lag'] >= 0.8) & (df['vrp_ratio_lag'] < 1.0),
    'VRP 1.0-1.2 (mild premium)': (df['vrp_ratio_lag'] >= 1.0) & (df['vrp_ratio_lag'] < 1.2),
    'VRP 1.2-1.5 (high premium)': (df['vrp_ratio_lag'] >= 1.2) & (df['vrp_ratio_lag'] < 1.5),
    'VRP > 1.5 (extreme premium)': df['vrp_ratio_lag'] >= 1.5,
}

print(f"\n  {'Regime':<32} {'Freq':>6} {'Mean Ret':>10} {'Vol':>8} {'Sharpe':>8} {'Skew':>6} {'Worst':>8}")
print(f"  {'-'*32} {'-'*6} {'-'*10} {'-'*8} {'-'*8} {'-'*6} {'-'*8}")

for regime_name, mask in regimes.items():
    r = df.loc[mask, 'short_vol_return']
    if len(r) < 10:
        continue
    freq = mask.sum() / len(df) * 100
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    skew = r.skew()
    worst = r.min()
    print(f"  {regime_name:<32} {freq:>5.1f}% {ann_ret*100:>9.2f}% {ann_vol*100:>7.1f}% {sharpe:>8.3f} {skew:>6.2f} {worst*100:>7.2f}%")


# ============================================================
# 13. Monthly Rolling Sharpe Comparison
# ============================================================
print("\n" + "=" * 70)
print("[12] Rolling 1-Year Sharpe Comparison")
print("=" * 70)

# Calculate rolling 252-day Sharpe
rolling_window = 252
for sname, col in [('B: Conditional', 'strat_b_ret'),
                    ('E: 50/50+VRP', 'strat_e_ret'),
                    ('50/50+VT', 'bench_5050vt'),
                    ('SPY', 'bench_spy')]:
    roll_mean = df[col].rolling(rolling_window).mean() * 252
    roll_std = df[col].rolling(rolling_window).std() * np.sqrt(252)
    roll_sharpe = roll_mean / roll_std
    valid = roll_sharpe.dropna()
    if len(valid) > 0:
        print(f"  {sname:<25} median rolling Sharpe: {valid.median():.3f} | "
              f"pct negative: {(valid < 0).mean()*100:.1f}%")


# ============================================================
# 14. Statistical Tests: DM Test vs Benchmarks
# ============================================================
print("\n" + "=" * 70)
print("[13] Statistical Tests")
print("=" * 70)

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    e1, e2: loss series. Positive DM → e2 better (lower loss)."""
    d = e1 - e2
    d = d.dropna()
    n = len(d)
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma0 += 2 * (1 - k / h) * gamma_k
    dm_stat = d_mean / np.sqrt(gamma0 / n) if gamma0 > 0 else 0
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_value

# Use negative returns as "loss" for DM test (higher = worse)
print(f"\n  DM Test: Strategy vs Benchmark (using -return as loss)")
print(f"  {'Comparison':<45} {'DM stat':>8} {'p-value':>8} {'Winner':>12}")
print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*12}")

comparisons = [
    ('B: Conditional', 'strat_b_ret', 'SPY B&H', 'bench_spy'),
    ('B: Conditional', 'strat_b_ret', '50/50 SPY/GLD', 'bench_5050'),
    ('B: Conditional', 'strat_b_ret', '50/50+VT', 'bench_5050vt'),
    ('E: 50/50+VRP overlay', 'strat_e_ret', '50/50 SPY/GLD', 'bench_5050'),
    ('E: 50/50+VRP overlay', 'strat_e_ret', '50/50+VT', 'bench_5050vt'),
    ('D: 50%SPY+50%VRP', 'strat_d_ret', 'SPY B&H', 'bench_spy'),
]

for s1_name, s1_col, s2_name, s2_col in comparisons:
    loss1 = -df[s1_col]
    loss2 = -df[s2_col]
    dm, p = dm_test(loss1, loss2)
    winner = s1_name if dm > 0 else s2_name
    sig = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.10 else ''))
    label = f"{s1_name} vs {s2_name}"
    print(f"  {label:<45} {dm:>8.3f} {p:>7.4f}{sig} {winner:>12}")


# ============================================================
# 15. Drawdown Duration Analysis
# ============================================================
print("\n" + "=" * 70)
print("[14] Drawdown Duration Analysis")
print("=" * 70)

for sname, col in [('B: Conditional (VRP>1.2)', 'strat_b_ret'),
                    ('E: 50/50+VRP overlay(10%)', 'strat_e_ret'),
                    ('BM3: 50/50+VT', 'bench_5050vt')]:
    r = df[col].dropna()
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak

    # Find drawdown episodes > 5%
    in_dd = dd < -0.05
    episodes = []
    start_idx = None
    for i in range(len(in_dd)):
        if in_dd.iloc[i] and start_idx is None:
            start_idx = i
        elif not in_dd.iloc[i] and start_idx is not None:
            episodes.append((start_idx, i, dd.iloc[start_idx:i].min()))
            start_idx = None
    if start_idx is not None:
        episodes.append((start_idx, len(in_dd)-1, dd.iloc[start_idx:].min()))

    if episodes:
        durations = [(e[1] - e[0]) for e in episodes]
        max_dur = max(durations)
        avg_dur = np.mean(durations)
        print(f"\n  {sname}:")
        print(f"    Drawdown episodes >5%: {len(episodes)}")
        print(f"    Max duration: {max_dur} trading days")
        print(f"    Avg duration: {avg_dur:.0f} trading days")
        print(f"    Deepest: {min(e[2] for e in episodes)*100:.1f}%")
    else:
        print(f"\n  {sname}: No drawdown episodes >5%")


# ============================================================
# 16. Risk-Adjusted Summary Table
# ============================================================
print("\n" + "=" * 70)
print("[15] FINAL SUMMARY TABLE")
print("=" * 70)

print(f"\n  {'Strategy':<28} {'Return':>8} {'Vol':>6} {'Sharpe':>7} {'MDD':>7} {'Worst Day':>10} {'Worst Wk':>9} {'Skew':>6}")
print(f"  {'-'*28} {'-'*8} {'-'*6} {'-'*7} {'-'*7} {'-'*10} {'-'*9} {'-'*6}")

for name in strategies:
    m = full_metrics[name]
    marker = '>>>' if 'BM' not in name else '   '
    print(f"  {marker}{name:<25} {m['ann_return']*100:>7.2f}% {m['ann_vol']*100:>5.1f}% {m['sharpe']:>7.3f} "
          f"{m['mdd']*100:>6.1f}% {m['worst_day']*100:>9.2f}% {m['worst_week']*100:>8.2f}% {m['skewness']:>6.2f}")

# ============================================================
# 17. Key Findings
# ============================================================
print("\n" + "=" * 70)
print("[16] KEY FINDINGS")
print("=" * 70)

# Determine if any VRP strategy beats benchmarks
best_vrp_sharpe = max(full_metrics[s]['sharpe'] for s in test_strategies)
bench_vt_sharpe = full_metrics['BM3: 50/50+VT (12/VIX)']['sharpe']
bench_5050_sharpe = full_metrics['BM2: 50/50 SPY/GLD']['sharpe']

best_vrp_name = max(test_strategies, key=lambda s: full_metrics[s]['sharpe'])
all_vrp_keys = list(test_strategies.keys()) + ['A: Always Short Vol']
# Filter to keys that exist in full_metrics
all_vrp_keys = [k for k in all_vrp_keys if k in full_metrics]
worst_vrp_mdd = min(full_metrics[s]['mdd'] for s in all_vrp_keys)
worst_vrp_name = min(all_vrp_keys, key=lambda s: full_metrics[s]['mdd'])

# Worst day across VRP strategies
worst_vrp_day = min(full_metrics[s]['worst_day'] for s in all_vrp_keys)

print(f"""
  1. VRP exists: VIX > realized vol {vrp_positive_pct:.0f}% of time, mean premium = {vrp_mean:.1f}%

  2. Best VRP strategy: {best_vrp_name}
     Sharpe = {full_metrics[best_vrp_name]['sharpe']:.3f}
     vs 50/50+VT Sharpe = {bench_vt_sharpe:.3f}
     vs 50/50 Sharpe = {bench_5050_sharpe:.3f}

  3. TAIL RISK IS REAL:
     Worst single day (any VRP strat): {worst_vrp_day*100:.2f}%
     Worst MDD (any VRP strat): {full_metrics[worst_vrp_name]['mdd']*100:.1f}% ({worst_vrp_name})

  4. Short vol proxy: {short_vol_method}

  5. VRP harvesting conclusion:
     {'VRP strategy BEATS benchmarks on Sharpe' if best_vrp_sharpe > bench_vt_sharpe else 'VRP strategy DOES NOT beat 50/50+VT benchmark'}
     {'BUT tail risk is extreme — not suitable for retail investors' if worst_vrp_day < -0.10 else 'Tail risk manageable with conditional entry'}
""")


# ============================================================
# 18. Save Results
# ============================================================
results = {
    'experiment': 'K242',
    'title': 'Volatility Risk Premium Harvesting — Short Vol as Alpha Source',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, ^VIX, GLD, SVXY)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df),
    'short_vol_method': short_vol_method,
    'vrp_summary': {
        'vrp_positive_pct': round(vrp_positive_pct, 1),
        'mean_vrp_level': round(vrp_mean, 2),
        'median_vrp_level': round(vrp_median, 2),
        'mean_vrp_ratio': round(df['vrp_ratio'].mean(), 3),
    },
    'full_sample_metrics': {k: {kk: round(vv, 6) if isinstance(vv, float) else vv
                                 for kk, vv in v.items()}
                            for k, v in full_metrics.items()},
    'cross_oos_results': {},
    'key_findings': {
        'vrp_exists': vrp_positive_pct > 70,
        'best_vrp_strategy': best_vrp_name,
        'best_vrp_sharpe': round(best_vrp_sharpe, 4),
        'benchmark_vt_sharpe': round(bench_vt_sharpe, 4),
        'benchmark_5050_sharpe': round(bench_5050_sharpe, 4),
        'beats_vt_benchmark': best_vrp_sharpe > bench_vt_sharpe,
        'worst_single_day': round(worst_vrp_day, 6),
        'has_extreme_tail_risk': worst_vrp_day < -0.10,
    }
}

# Add OOS results
for label, period_results in oos_results.items():
    results['cross_oos_results'][label] = {
        k: {kk: round(vv, 6) if isinstance(vv, float) else vv for kk, vv in v.items()}
        for k, v in period_results.items()
    }

output_path = 'experiments/k242_vrp_harvesting_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K242 COMPLETE")
print("=" * 70)
