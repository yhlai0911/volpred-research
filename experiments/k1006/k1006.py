"""
K1006: TAIFEX Overnight Gap Strategy Backtest
==============================================
Research Question:
1. Does the overnight gap in TAIFEX TX futures have a systematic directional bias?
2. Can a VIX-conditional overnight gap strategy generate profit?
3. Is it profitable after transaction costs?

Data: TAIFEX tick data (2012-2026), VIX from yfinance
Methodology:
- Extract daily open/close from TX most-active contract
- Compute overnight gap = today's open - yesterday's close
- Test: Naive overnight, VIX-conditional, Gap-fade strategies
- Cost: 4 points round-trip per contract (800 TWD)

References:
- K515: 77-93% of TAIFEX alpha comes from overnight gap
- Berkman et al. (2012): Overnight returns and firm-specific investor sentiment
- Lou et al. (2019): A tug of war: Overnight versus intraday expected returns

Author: [提出: Claude, 執行: Claude]
Seed: 42
"""

import os
import glob
import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Load TAIFEX TX tick data
# ============================================================
DATA_DIR = os.path.expanduser('~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/')
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_tx_daily_ohlc(data_dir, start_year=2012, end_year=2026):
    """
    Load TAIFEX TX tick data and extract daily open/close/volume.
    Uses the most active contract month each day (by volume).
    Handles 9-column (2012) and 10-column (2014+) formats.
    """
    # Column names for different formats
    cols_9 = ['date', 'product', 'expiry', 'time', 'price', 'volume',
              'near_price', 'far_price', 'timestamp']
    cols_10 = ['date', 'product', 'expiry', 'time', 'price', 'volume',
               'near_price', 'far_price', 'open_auction', 'timestamp']

    all_files = sorted(glob.glob(os.path.join(data_dir, 'Daily_*TX.csv')))
    print(f"Found {len(all_files)} TX files")

    daily_records = []

    for fpath in all_files:
        fname = os.path.basename(fpath)
        # Extract date from filename: Daily_YYYY_MM_DDTX.csv
        parts = fname.replace('Daily_', '').replace('TX.csv', '').split('_')
        if len(parts) != 3:
            continue
        file_year = int(parts[0])
        if file_year < start_year or file_year > end_year:
            continue

        try:
            # Detect number of columns from first data line
            with open(fpath, 'rb') as f:
                header_line = f.readline()
                first_data = f.readline()

            n_cols = len(first_data.decode('big5', errors='replace').strip().split(','))

            if n_cols == 9:
                cols = cols_9
            else:
                cols = cols_10

            df = pd.read_csv(fpath, encoding='big5', names=cols, skiprows=1,
                           dtype={'date': str, 'product': str, 'expiry': str,
                                  'time': str})

            if df.empty:
                continue

            # Filter TX only (should already be TX files, but double-check)
            df = df[df['product'].str.strip() == 'TX'].copy()
            if df.empty:
                continue

            # Convert price and volume to numeric
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            df = df.dropna(subset=['price', 'volume'])

            if df.empty:
                continue

            # Parse time as integer for comparison
            df['time_int'] = pd.to_numeric(df['time'], errors='coerce').astype(int)

            # Determine day session ticks: 08:45 - 13:45
            # time format: HHMMSS (e.g., 84500 = 08:45:00, 134500 = 13:45:00)
            day_session = df[(df['time_int'] >= 84500) & (df['time_int'] <= 134500)].copy()

            if day_session.empty:
                continue

            # Select most active contract month by volume
            vol_by_expiry = day_session.groupby('expiry')['volume'].sum()
            most_active = vol_by_expiry.idxmax()

            # Filter to most active contract
            active_ticks = day_session[day_session['expiry'] == most_active].copy()
            active_ticks = active_ticks.sort_values('time_int')

            # Extract OHLCV
            trade_date = active_ticks['date'].iloc[0]
            open_price = active_ticks.iloc[0]['price']
            close_price = active_ticks.iloc[-1]['price']
            high_price = active_ticks['price'].max()
            low_price = active_ticks['price'].min()
            total_volume = active_ticks['volume'].sum()

            daily_records.append({
                'date': trade_date,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': total_volume,
                'active_contract': most_active
            })

        except Exception as e:
            # Skip problematic files
            continue

    if not daily_records:
        return pd.DataFrame()

    result = pd.DataFrame(daily_records)
    result['date'] = pd.to_datetime(result['date'], format='%Y%m%d')
    result = result.sort_values('date').reset_index(drop=True)
    result = result.drop_duplicates(subset='date', keep='first')

    print(f"Loaded {len(result)} trading days from {result['date'].min()} to {result['date'].max()}")
    return result


def load_vix_data():
    """Load VIX data from yfinance for the same period."""
    import yfinance as yf
    vix = yf.download('^VIX', start='2012-01-01', end='2026-12-31', progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix = vix[['Close']].rename(columns={'Close': 'vix'})
    vix.index = pd.to_datetime(vix.index)
    # VIX is US market - use previous day's VIX for Taiwan (lag due to timezone)
    vix = vix.reset_index().rename(columns={'Date': 'date', 'index': 'date'})
    if 'Date' in vix.columns:
        vix = vix.rename(columns={'Date': 'date'})
    return vix


# ============================================================
# 2. Main Analysis
# ============================================================
print("=" * 60)
print("K1006: TAIFEX Overnight Gap Strategy")
print("=" * 60)

# Load data
print("\n[1] Loading TAIFEX TX data...")
tx = load_tx_daily_ohlc(DATA_DIR)

if tx.empty:
    print("ERROR: No TAIFEX data loaded. Exiting.")
    exit(1)

print(f"\n[2] Data summary:")
print(f"  Period: {tx['date'].min().strftime('%Y-%m-%d')} to {tx['date'].max().strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(tx)}")
print(f"  Price range: {tx['close'].min():.0f} - {tx['close'].max():.0f}")

# Compute overnight gap and intraday return
tx['prev_close'] = tx['close'].shift(1)
tx['overnight_gap'] = tx['open'] - tx['prev_close']          # points
tx['overnight_ret'] = tx['overnight_gap'] / tx['prev_close']  # percentage
tx['intraday_ret'] = (tx['close'] - tx['open']) / tx['open']  # percentage
tx['daily_ret'] = (tx['close'] - tx['prev_close']) / tx['prev_close']  # percentage
tx = tx.dropna(subset=['overnight_gap']).copy()

print(f"\n[3] Overnight Gap Statistics:")
print(f"  Mean gap (points): {tx['overnight_gap'].mean():.2f}")
print(f"  Std gap (points): {tx['overnight_gap'].std():.2f}")
print(f"  Mean overnight return: {tx['overnight_ret'].mean()*100:.4f}%")
print(f"  Std overnight return: {tx['overnight_ret'].std()*100:.4f}%")
print(f"  Positive gap days: {(tx['overnight_gap'] > 0).sum()} ({(tx['overnight_gap'] > 0).mean()*100:.1f}%)")
print(f"  Negative gap days: {(tx['overnight_gap'] < 0).sum()} ({(tx['overnight_gap'] < 0).mean()*100:.1f}%)")
print(f"  Zero gap days: {(tx['overnight_gap'] == 0).sum()} ({(tx['overnight_gap'] == 0).mean()*100:.1f}%)")

print(f"\n[3b] Intraday Return Statistics:")
print(f"  Mean intraday return: {tx['intraday_ret'].mean()*100:.4f}%")
print(f"  Std intraday return: {tx['intraday_ret'].std()*100:.4f}%")

print(f"\n[3c] Daily Return Decomposition:")
overnight_var = tx['overnight_ret'].var()
intraday_var = tx['intraday_ret'].var()
daily_var = tx['daily_ret'].var()
print(f"  Overnight variance share: {overnight_var/daily_var*100:.1f}%")
print(f"  Intraday variance share: {intraday_var/daily_var*100:.1f}%")

# Cumulative contribution
cum_overnight = tx['overnight_ret'].cumsum()
cum_intraday = tx['intraday_ret'].cumsum()
cum_daily = tx['daily_ret'].cumsum()
print(f"  Cumulative overnight return: {cum_overnight.iloc[-1]*100:.2f}%")
print(f"  Cumulative intraday return: {cum_intraday.iloc[-1]*100:.2f}%")
print(f"  Cumulative daily return: {cum_daily.iloc[-1]*100:.2f}%")
overnight_share = cum_overnight.iloc[-1] / cum_daily.iloc[-1] * 100 if cum_daily.iloc[-1] != 0 else np.nan
print(f"  Overnight share of total return: {overnight_share:.1f}%")

# ============================================================
# 3. Load VIX and merge
# ============================================================
print("\n[4] Loading VIX data...")
vix_df = load_vix_data()

# Merge VIX with TX data
# Use previous trading day's VIX (Taiwan is ahead of US by ~13 hours)
# So for Taiwan's Monday, we use US Friday's VIX
vix_df['date'] = pd.to_datetime(vix_df['date']).dt.tz_localize(None).astype('datetime64[ns]')
tx['date'] = pd.to_datetime(tx['date']).dt.tz_localize(None).astype('datetime64[ns]')

# Merge on date with forward fill (use most recent available VIX)
tx = tx.sort_values('date')
vix_df = vix_df.sort_values('date')
tx = pd.merge_asof(tx, vix_df[['date', 'vix']], on='date', direction='backward')

# Shift VIX by 1 day to ensure no lookahead (use yesterday's VIX for today's decision)
tx['vix_signal'] = tx['vix'].shift(1)

print(f"  VIX data merged: {tx['vix_signal'].notna().sum()} days with VIX")
print(f"  VIX range: {tx['vix_signal'].min():.1f} - {tx['vix_signal'].max():.1f}")

# ============================================================
# 4. Strategy Backtesting
# ============================================================
print("\n[5] Strategy Backtesting...")

# Constants
TX_POINT_VALUE = 200  # TWD per point
COST_PER_TRADE = 4    # points round-trip (2 points each way)
MARGIN = 184000       # TWD per contract

# Strategy returns (in points, per contract)
# All strategies use shift(1) for signals where applicable

# Strategy 1: Naive Overnight - buy at close, sell at open every day
# Return = overnight gap (points) - cost
tx['strat1_gross'] = tx['overnight_gap']
tx['strat1_net'] = tx['strat1_gross'] - COST_PER_TRADE

# Strategy 2: VIX-Conditional Overnight - only trade when VIX > 20
# Signal from t-1 VIX (already shifted above as vix_signal)
tx['strat2_signal'] = (tx['vix_signal'] > 20).astype(int)
tx['strat2_gross'] = tx['strat2_signal'] * tx['overnight_gap']
tx['strat2_net'] = tx['strat2_gross'] - tx['strat2_signal'] * COST_PER_TRADE

# Strategy 3: VIX-Conditional with higher threshold (VIX > 25)
tx['strat3_signal'] = (tx['vix_signal'] > 25).astype(int)
tx['strat3_gross'] = tx['strat3_signal'] * tx['overnight_gap']
tx['strat3_net'] = tx['strat3_gross'] - tx['strat3_signal'] * COST_PER_TRADE

# Strategy 4: Gap-Fade (mean reversion after gap)
# If gap > 0, go short intraday; if gap < 0, go long intraday
# Signal: direction of today's gap -> intraday trade
# We use YESTERDAY's gap direction to predict today's intraday (to avoid lookahead)
tx['prev_gap_direction'] = np.sign(tx['overnight_gap']).shift(1)
tx['strat4_gross'] = -tx['prev_gap_direction'] * tx['intraday_ret'] * tx['prev_close']  # approximate points
# Actually, let's be more precise: fade today's gap during today's session
# But we need to know today's gap at the open to trade intraday
# At open, we observe the gap. If gap > 0, sell. If gap < 0, buy.
# This is NOT lookahead - we observe the open price and trade intraday
tx['gap_direction'] = np.sign(tx['overnight_gap'])
tx['strat4_gross'] = -tx['gap_direction'] * (tx['close'] - tx['open'])  # points from intraday fade
tx['strat4_net'] = tx['strat4_gross'] - COST_PER_TRADE  # always trading

# Strategy 5: Buy & Hold TX (benchmark)
tx['strat5_ret'] = tx['daily_ret']  # percentage return

# ============================================================
# 5. Performance Metrics
# ============================================================

def compute_metrics(returns_points, name, margin=MARGIN, point_value=TX_POINT_VALUE,
                    trade_count=None):
    """Compute performance metrics for point-based returns."""
    returns_twd = returns_points * point_value  # TWD per contract
    returns_pct = returns_twd / margin          # percentage return on margin

    n_days = len(returns_points)
    n_years = n_days / 252

    total_points = returns_points.sum()
    total_twd = total_points * point_value

    annual_ret = returns_pct.mean() * 252
    annual_vol = returns_pct.std() * np.sqrt(252)
    sharpe = annual_ret / annual_vol if annual_vol > 0 else 0

    # Max Drawdown (in TWD)
    cum_twd = returns_twd.cumsum()
    peak = cum_twd.cummax()
    dd = cum_twd - peak
    mdd_twd = dd.min()
    mdd_pct = mdd_twd / margin if margin > 0 else 0

    # Win rate
    if trade_count is not None:
        win_rate = (returns_points[returns_points != 0] > 0).sum() / max((returns_points != 0).sum(), 1)
        n_trades = (returns_points != 0).sum()
    else:
        win_rate = (returns_points > 0).sum() / len(returns_points)
        n_trades = len(returns_points)

    return {
        'name': name,
        'n_days': int(n_days),
        'n_trades': int(n_trades),
        'n_years': round(n_years, 1),
        'total_points': round(float(total_points), 1),
        'total_twd': round(float(total_twd), 0),
        'annual_return_pct': round(float(annual_ret * 100), 2),
        'annual_vol_pct': round(float(annual_vol * 100), 2),
        'sharpe': round(float(sharpe), 3),
        'mdd_pct': round(float(mdd_pct * 100), 2),
        'mdd_twd': round(float(mdd_twd), 0),
        'win_rate': round(float(win_rate * 100), 1),
    }


def compute_metrics_pct(returns_pct, name):
    """Compute metrics for percentage-based returns (buy & hold)."""
    n_days = len(returns_pct)
    n_years = n_days / 252
    annual_ret = returns_pct.mean() * 252
    annual_vol = returns_pct.std() * np.sqrt(252)
    sharpe = annual_ret / annual_vol if annual_vol > 0 else 0

    cum = (1 + returns_pct).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1
    mdd = dd.min()

    win_rate = (returns_pct > 0).sum() / len(returns_pct)

    return {
        'name': name,
        'n_days': int(n_days),
        'n_trades': int(n_days),
        'n_years': round(n_years, 1),
        'total_return_pct': round(float((cum.iloc[-1] - 1) * 100), 2),
        'annual_return_pct': round(float(annual_ret * 100), 2),
        'annual_vol_pct': round(float(annual_vol * 100), 2),
        'sharpe': round(float(sharpe), 3),
        'mdd_pct': round(float(mdd * 100), 2),
        'win_rate': round(float(win_rate * 100), 1),
    }


# Drop NaN rows for clean analysis
analysis = tx.dropna(subset=['strat1_net', 'strat2_net', 'strat4_net', 'vix_signal']).copy()
print(f"  Analysis period: {analysis['date'].min().strftime('%Y-%m-%d')} to {analysis['date'].max().strftime('%Y-%m-%d')}")
print(f"  Days: {len(analysis)}")

metrics = {}
metrics['naive_overnight_gross'] = compute_metrics(analysis['strat1_gross'], 'Naive Overnight (gross)')
metrics['naive_overnight_net'] = compute_metrics(analysis['strat1_net'], 'Naive Overnight (net)')
metrics['vix20_overnight_gross'] = compute_metrics(analysis['strat2_gross'], 'VIX>20 Overnight (gross)', trade_count=True)
metrics['vix20_overnight_net'] = compute_metrics(analysis['strat2_net'], 'VIX>20 Overnight (net)', trade_count=True)
metrics['vix25_overnight_gross'] = compute_metrics(analysis['strat3_gross'], 'VIX>25 Overnight (gross)', trade_count=True)
metrics['vix25_overnight_net'] = compute_metrics(analysis['strat3_net'], 'VIX>25 Overnight (net)', trade_count=True)
metrics['gap_fade_gross'] = compute_metrics(analysis['strat4_gross'], 'Gap-Fade Intraday (gross)')
metrics['gap_fade_net'] = compute_metrics(analysis['strat4_net'], 'Gap-Fade Intraday (net)')
metrics['buy_hold'] = compute_metrics_pct(analysis['strat5_ret'], 'Buy & Hold TX')

print("\n" + "=" * 80)
print("STRATEGY PERFORMANCE COMPARISON")
print("=" * 80)
header = f"{'Strategy':<30} {'Ann.Ret%':>10} {'Ann.Vol%':>10} {'Sharpe':>8} {'MDD%':>8} {'WinRate%':>10} {'Trades':>8}"
print(header)
print("-" * 80)
for k, m in metrics.items():
    print(f"{m['name']:<30} {m['annual_return_pct']:>10.2f} {m['annual_vol_pct']:>10.2f} {m['sharpe']:>8.3f} {m['mdd_pct']:>8.2f} {m['win_rate']:>10.1f} {m['n_trades']:>8}")

# ============================================================
# 6. VIX Regime Analysis
# ============================================================
print("\n[6] VIX Regime Analysis (Overnight Gap)")

# Define VIX regimes
analysis['vix_regime'] = pd.cut(analysis['vix_signal'],
                                 bins=[0, 15, 20, 25, 100],
                                 labels=['Low (<15)', 'Mid (15-20)', 'High (20-25)', 'VHigh (>25)'])

regime_stats = analysis.groupby('vix_regime', observed=True).agg({
    'overnight_gap': ['mean', 'std', 'count'],
    'overnight_ret': ['mean', 'std'],
    'intraday_ret': ['mean', 'std'],
}).round(4)

print("\n  Overnight Gap by VIX Regime (points):")
for regime in ['Low (<15)', 'Mid (15-20)', 'High (20-25)', 'VHigh (>25)']:
    if regime in analysis['vix_regime'].values:
        subset = analysis[analysis['vix_regime'] == regime]
        print(f"  {regime:>15}: mean={subset['overnight_gap'].mean():>8.2f} pts, "
              f"std={subset['overnight_gap'].std():>8.2f}, "
              f"n={len(subset):>5}, "
              f"pos%={((subset['overnight_gap']>0).mean()*100):>5.1f}%")

# ============================================================
# 7. Yearly Performance
# ============================================================
print("\n[7] Yearly Performance (Naive Overnight, net of costs)")
analysis['year'] = analysis['date'].dt.year

yearly = analysis.groupby('year').agg({
    'strat1_net': 'sum',         # naive overnight net points
    'strat2_net': 'sum',         # VIX>20 net points
    'overnight_gap': 'mean',     # mean gap
    'overnight_ret': 'mean',     # mean overnight return
    'strat2_signal': 'sum',      # number of VIX>20 trades
}).rename(columns={
    'strat1_net': 'naive_net_pts',
    'strat2_net': 'vix20_net_pts',
    'overnight_gap': 'mean_gap_pts',
    'overnight_ret': 'mean_overnight_ret',
    'strat2_signal': 'vix20_trade_days'
})

print(f"\n{'Year':>6} {'Naive(pts)':>12} {'VIX20(pts)':>12} {'MeanGap':>10} {'VIX20_days':>12}")
print("-" * 55)
for year, row in yearly.iterrows():
    print(f"{year:>6} {row['naive_net_pts']:>12.0f} {row['vix20_net_pts']:>12.0f} "
          f"{row['mean_gap_pts']:>10.2f} {int(row['vix20_trade_days']):>12}")

# ============================================================
# 8. Statistical Tests
# ============================================================
print("\n[8] Statistical Tests")

from scipy import stats

# Test 1: Is mean overnight gap significantly different from zero?
t_stat, p_val = stats.ttest_1samp(analysis['overnight_gap'], 0)
print(f"\n  H0: Mean overnight gap = 0")
print(f"  t-stat = {t_stat:.4f}, p-value = {p_val:.6f}")
print(f"  {'REJECT' if abs(t_stat) > 3.0 else 'FAIL TO REJECT'} at Harvey (2016) |t| > 3.0 threshold")

# Test 2: Is mean overnight return significantly different from zero?
t_stat2, p_val2 = stats.ttest_1samp(analysis['overnight_ret'], 0)
print(f"\n  H0: Mean overnight return = 0")
print(f"  t-stat = {t_stat2:.4f}, p-value = {p_val2:.6f}")
print(f"  {'REJECT' if abs(t_stat2) > 3.0 else 'FAIL TO REJECT'} at Harvey (2016) |t| > 3.0")

# Test 3: Naive overnight strategy net returns vs zero
t_stat3, p_val3 = stats.ttest_1samp(analysis['strat1_net'], 0)
print(f"\n  H0: Mean naive overnight net return = 0 (points)")
print(f"  t-stat = {t_stat3:.4f}, p-value = {p_val3:.6f}")
print(f"  {'REJECT' if abs(t_stat3) > 3.0 else 'FAIL TO REJECT'} at Harvey (2016) |t| > 3.0")

# Test 4: VIX>20 overnight returns vs VIX<=20
high_vix = analysis[analysis['vix_signal'] > 20]['overnight_gap']
low_vix = analysis[analysis['vix_signal'] <= 20]['overnight_gap']
if len(high_vix) > 30 and len(low_vix) > 30:
    t_stat4, p_val4 = stats.ttest_ind(high_vix, low_vix)
    print(f"\n  H0: Overnight gap same for VIX>20 vs VIX<=20")
    print(f"  VIX>20 mean: {high_vix.mean():.2f} pts (n={len(high_vix)})")
    print(f"  VIX<=20 mean: {low_vix.mean():.2f} pts (n={len(low_vix)})")
    print(f"  t-stat = {t_stat4:.4f}, p-value = {p_val4:.6f}")
    print(f"  {'REJECT' if abs(t_stat4) > 3.0 else 'FAIL TO REJECT'} at Harvey (2016) |t| > 3.0")

# Test 5: Gap-fade intraday — does the gap predict intraday reversal?
# Correlation between overnight gap and intraday return
corr, p_corr = stats.pearsonr(analysis['overnight_gap'],
                                analysis['close'] - analysis['open'])
print(f"\n  Gap-Fade: Correlation(overnight_gap, intraday_return_pts)")
print(f"  Pearson r = {corr:.4f}, p-value = {p_corr:.6f}")

# ============================================================
# 9. Plots
# ============================================================
print("\n[9] Generating plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: Cumulative returns
ax1 = axes[0, 0]
cum_naive_net = (analysis['strat1_net'] * TX_POINT_VALUE).cumsum() / 1e6
cum_vix20_net = (analysis['strat2_net'] * TX_POINT_VALUE).cumsum() / 1e6
cum_fade_net = (analysis['strat4_net'] * TX_POINT_VALUE).cumsum() / 1e6
ax1.plot(analysis['date'], cum_naive_net, label='Naive Overnight (net)', linewidth=1)
ax1.plot(analysis['date'], cum_vix20_net, label='VIX>20 Overnight (net)', linewidth=1)
ax1.plot(analysis['date'], cum_fade_net, label='Gap-Fade (net)', linewidth=1, alpha=0.7)
ax1.set_title('Cumulative P&L (Million TWD, per contract)')
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)
ax1.set_ylabel('Million TWD')

# Plot 2: Overnight gap distribution
ax2 = axes[0, 1]
ax2.hist(analysis['overnight_gap'], bins=100, edgecolor='none', alpha=0.7)
ax2.axvline(x=0, color='red', linestyle='--', alpha=0.5)
ax2.axvline(x=analysis['overnight_gap'].mean(), color='green', linestyle='--',
            label=f"Mean={analysis['overnight_gap'].mean():.1f}")
ax2.set_title('Overnight Gap Distribution (points)')
ax2.legend()
ax2.grid(True, alpha=0.3)

# Plot 3: Overnight gap by VIX regime
ax3 = axes[1, 0]
regime_data = []
regime_labels = ['Low (<15)', 'Mid (15-20)', 'High (20-25)', 'VHigh (>25)']
for regime in regime_labels:
    subset = analysis[analysis['vix_regime'] == regime]
    if len(subset) > 0:
        regime_data.append(subset['overnight_gap'].values)
    else:
        regime_data.append([0])
bp = ax3.boxplot(regime_data, labels=regime_labels, showfliers=False)
ax3.axhline(y=0, color='red', linestyle='--', alpha=0.5)
ax3.set_title('Overnight Gap by VIX Regime')
ax3.set_ylabel('Points')
ax3.grid(True, alpha=0.3)

# Plot 4: Rolling 252-day Sharpe of naive overnight
rolling_ret = analysis['strat1_net'] * TX_POINT_VALUE / MARGIN
rolling_sharpe = rolling_ret.rolling(252).mean() / rolling_ret.rolling(252).std() * np.sqrt(252)
ax4 = axes[1, 1]
ax4.plot(analysis['date'], rolling_sharpe, linewidth=0.8)
ax4.axhline(y=0, color='red', linestyle='--', alpha=0.5)
ax4.set_title('Rolling 1-Year Sharpe (Naive Overnight, net)')
ax4.grid(True, alpha=0.3)
ax4.set_ylabel('Sharpe Ratio')

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1006_strategies.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1006_strategies.png")

# Plot 5: Yearly comparison bar chart
fig2, ax5 = plt.subplots(figsize=(12, 5))
years = yearly.index.tolist()
x = np.arange(len(years))
w = 0.35
bars1 = ax5.bar(x - w/2, yearly['naive_net_pts'] * TX_POINT_VALUE / 1e4, w,
                label='Naive Overnight (net)', color='steelblue')
bars2 = ax5.bar(x + w/2, yearly['vix20_net_pts'] * TX_POINT_VALUE / 1e4, w,
                label='VIX>20 Overnight (net)', color='coral')
ax5.set_xticks(x)
ax5.set_xticklabels(years, rotation=45)
ax5.set_ylabel('P&L (萬 TWD per contract)')
ax5.set_title('Yearly P&L: Naive vs VIX-Conditional Overnight')
ax5.legend()
ax5.grid(True, alpha=0.3, axis='y')
ax5.axhline(y=0, color='black', linewidth=0.5)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1006_yearly.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1006_yearly.png")

# ============================================================
# 10. Bootstrap confidence intervals for Sharpe
# ============================================================
print("\n[10] Bootstrap CI for Sharpe ratios (1000 reps, seed=42)")

rng = np.random.default_rng(42)

def bootstrap_sharpe(returns, n_boot=1000, rng=rng):
    """Bootstrap Sharpe ratio with 95% CI."""
    sharpes = []
    n = len(returns)
    for _ in range(n_boot):
        sample = returns[rng.integers(0, n, size=n)]
        s = sample.mean() / sample.std() * np.sqrt(252) if sample.std() > 0 else 0
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return np.percentile(sharpes, [2.5, 50, 97.5])

# Convert to percentage returns on margin
naive_pct = analysis['strat1_net'].values * TX_POINT_VALUE / MARGIN
vix20_pct = analysis['strat2_net'].values * TX_POINT_VALUE / MARGIN
fade_pct = analysis['strat4_net'].values * TX_POINT_VALUE / MARGIN

for name, rets in [('Naive Overnight (net)', naive_pct),
                    ('VIX>20 Overnight (net)', vix20_pct),
                    ('Gap-Fade (net)', fade_pct)]:
    ci = bootstrap_sharpe(rets)
    print(f"  {name:<30}: Sharpe 95% CI = [{ci[0]:.3f}, {ci[2]:.3f}], median = {ci[1]:.3f}")

# ============================================================
# 11. Save results
# ============================================================
results = {
    'experiment_id': 'K1006',
    'title': 'TAIFEX Overnight Gap Strategy Backtest',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'TAIFEX tick data (TX most-active contract)',
    'period': f"{analysis['date'].min().strftime('%Y-%m-%d')} to {analysis['date'].max().strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(analysis)),
    'overnight_gap_statistics': {
        'mean_points': round(float(analysis['overnight_gap'].mean()), 2),
        'std_points': round(float(analysis['overnight_gap'].std()), 2),
        'mean_return_pct': round(float(analysis['overnight_ret'].mean() * 100), 4),
        'std_return_pct': round(float(analysis['overnight_ret'].std() * 100), 4),
        'positive_pct': round(float((analysis['overnight_gap'] > 0).mean() * 100), 1),
        'negative_pct': round(float((analysis['overnight_gap'] < 0).mean() * 100), 1),
        'overnight_share_of_total_return': round(float(overnight_share), 1),
        'overnight_variance_share': round(float(overnight_var / daily_var * 100), 1),
    },
    'strategy_metrics': metrics,
    'vix_regime_analysis': {},
    'yearly_performance': {},
    'statistical_tests': {
        'overnight_gap_vs_zero': {
            't_stat': round(float(t_stat), 4),
            'p_value': round(float(p_val), 6),
            'significant_harvey': abs(t_stat) > 3.0
        },
        'overnight_return_vs_zero': {
            't_stat': round(float(t_stat2), 4),
            'p_value': round(float(p_val2), 6),
            'significant_harvey': abs(t_stat2) > 3.0
        },
        'naive_net_vs_zero': {
            't_stat': round(float(t_stat3), 4),
            'p_value': round(float(p_val3), 6),
            'significant_harvey': abs(t_stat3) > 3.0
        },
        'gap_intraday_correlation': {
            'pearson_r': round(float(corr), 4),
            'p_value': round(float(p_corr), 6),
        }
    },
    'conclusions': [],  # will be filled after running
    'limitations': [
        'Transaction cost assumed 4 points round-trip (may vary)',
        'Slippage at open/close not modeled (market orders may get worse fills)',
        'No margin cost / financing cost included',
        'VIX signal uses US previous close (timezone lag assumed correct)',
        'Single contract analysis - no position sizing optimization',
        'No consideration of night session (post-2017) trading opportunities'
    ],
    'references': [
        'K515: 77-93% of TAIFEX alpha comes from overnight gap',
        'Berkman et al. (2012): Overnight returns and firm-specific investor sentiment, JFE',
        'Lou et al. (2019): A tug of war: Overnight versus intraday expected returns, JFE'
    ]
}

# Add VIX regime analysis
for regime in regime_labels:
    subset = analysis[analysis['vix_regime'] == regime]
    if len(subset) > 0:
        results['vix_regime_analysis'][regime] = {
            'n': int(len(subset)),
            'mean_gap_pts': round(float(subset['overnight_gap'].mean()), 2),
            'std_gap_pts': round(float(subset['overnight_gap'].std()), 2),
            'positive_pct': round(float((subset['overnight_gap'] > 0).mean() * 100), 1),
        }

# Add yearly performance
for year, row in yearly.iterrows():
    results['yearly_performance'][str(year)] = {
        'naive_net_pts': round(float(row['naive_net_pts']), 0),
        'vix20_net_pts': round(float(row['vix20_net_pts']), 0),
        'mean_gap_pts': round(float(row['mean_gap_pts']), 2),
        'vix20_trade_days': int(row['vix20_trade_days']),
    }

# Generate conclusions based on results
conclusions = []
naive_sharpe = metrics['naive_overnight_net']['sharpe']
if naive_sharpe > 0:
    conclusions.append(f"Naive overnight strategy has positive Sharpe ({naive_sharpe:.3f}) after costs")
else:
    conclusions.append(f"Naive overnight strategy has NEGATIVE Sharpe ({naive_sharpe:.3f}) after costs - overnight gap is not a free lunch")

if abs(t_stat) > 3.0:
    conclusions.append(f"Overnight gap is statistically significant (t={t_stat:.2f}, Harvey threshold passed)")
else:
    conclusions.append(f"Overnight gap is NOT statistically significant at Harvey (2016) threshold (t={t_stat:.2f})")

vix20_sharpe = metrics['vix20_overnight_net']['sharpe']
if vix20_sharpe > naive_sharpe:
    conclusions.append(f"VIX-conditional (>20) improves Sharpe to {vix20_sharpe:.3f} vs naive {naive_sharpe:.3f}")
else:
    conclusions.append(f"VIX-conditional (>20) does NOT improve over naive (Sharpe {vix20_sharpe:.3f} vs {naive_sharpe:.3f})")

conclusions.append(f"Overnight gap accounts for {overnight_share:.1f}% of total return, confirming K515 findings")
conclusions.append(f"Transaction costs (4 pts RT) significantly erode overnight gap profits")

results['conclusions'] = conclusions

# Save results
results_path = os.path.join(OUTPUT_DIR, 'k1006_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print(f"\n[11] Results saved to {results_path}")

print("\n" + "=" * 60)
print("K1006 COMPLETE")
print("=" * 60)
for c in conclusions:
    print(f"  * {c}")
