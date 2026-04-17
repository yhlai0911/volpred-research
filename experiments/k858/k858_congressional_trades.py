"""
K858: Congressional Trading Alpha — Aggregate Portfolio Performance Analysis
=============================================================================
Member question: Does following aggregate congressional stock trades generate
alpha, even with disclosure delay?

Data source: data/congressional_trades_house.csv (15,674 rows, 2020-2022)
             Stock prices from yfinance
Methodology:
  - Parse trade data, filter to valid stock tickers
  - Analyze disclosure lag distribution
  - Construct aggregate "consensus buy" portfolio: monthly top-N net-bought tickers
  - TWO strategies: (1) Realistic = enter on disclosure_date+1 (public info)
                    (2) Perfect info = enter on transaction_date+1 (upper bound)
  - Benchmark: SPY buy-and-hold
  - Metrics: CAGR, Sharpe, MDD, monthly win rate vs SPY, sector concentration

References:
  - Eggers & Hainmueller (2014) "Capitol Losses: The Mediocre Performance of
    Congressional Stock Portfolios" JoP
  - Ziobrowski et al. (2004) "Abnormal Returns from the Common Stock Investments
    of the U.S. Senate" JFQA
  - Karadas (2019) "Trading on Private Information: Evidence from Members of Congress"
    Economic Letters

Error Log rules applied:
  - Lookahead: use disclosure_date+1 for realistic strategy (NOT transaction_date)
  - Sanity check: compute actual lag, verify no future information
  - signal.shift(1) equivalent: entry is next business day after signal date
"""

import json
import os
import sys
import warnings
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA LOADING & CLEANING
# ============================================================
print("=" * 70)
print("K858: Congressional Trading Alpha — Aggregate Portfolio Analysis")
print("=" * 70)

DATA_PATH = "data/congressional_trades_house.csv"
df = pd.read_csv(DATA_PATH)
print(f"\nRaw data: {len(df):,} rows, {df['representative'].nunique()} members, "
      f"{df['ticker'].nunique()} unique tickers")

# Parse dates
df['disclosure_dt'] = pd.to_datetime(df['disclosure_date'], format='%m/%d/%Y', errors='coerce')
df['transaction_dt'] = pd.to_datetime(df['transaction_date'], errors='coerce')

# Filter out bad dates
df = df.dropna(subset=['disclosure_dt', 'transaction_dt'])
# Filter to reasonable range (2019-2023)
df = df[(df['transaction_dt'] >= '2019-01-01') & (df['transaction_dt'] <= '2023-01-01')]
df = df[(df['disclosure_dt'] >= '2019-01-01') & (df['disclosure_dt'] <= '2023-01-01')]

# Filter out non-stock tickers (-- means non-equity)
df = df[df['ticker'] != '--']

# Filter out tickers that look like non-equity (warrants, bonds, etc.)
# Keep only clean tickers (letters only, 1-5 chars)
df = df[df['ticker'].str.match(r'^[A-Z]{1,5}$', na=False)]

# Parse amount ranges to midpoint dollar values
def parse_amount(amt_str):
    """Convert amount range string to midpoint dollar value."""
    if pd.isna(amt_str):
        return 0
    amt_str = str(amt_str).replace(',', '').replace('$', '').strip()
    if ' - ' in amt_str:
        parts = amt_str.split(' - ')
        try:
            low = float(parts[0].strip())
            high = float(parts[1].strip())
            return (low + high) / 2
        except:
            return 0
    elif '+' in amt_str:
        try:
            return float(amt_str.replace('+', '').strip()) * 1.5  # conservative estimate
        except:
            return 0
    else:
        try:
            return float(amt_str.strip())
        except:
            return 0

df['amount_mid'] = df['amount'].apply(parse_amount)

# Classify trade direction
df['direction'] = df['type'].map({
    'purchase': 1,
    'sale_full': -1,
    'sale_partial': -1,
    'sale': -1,
    'exchange': 0
})
df = df[df['direction'] != 0]  # drop exchanges

# Handle ticker renames in trade data
df.loc[df['ticker'] == 'FB', 'ticker'] = 'META'

# Compute disclosure lag
df['lag_days'] = (df['disclosure_dt'] - df['transaction_dt']).dt.days
# Filter out negative lags (data errors) and extreme lags (> 365 days)
df = df[(df['lag_days'] >= 0) & (df['lag_days'] <= 365)]

print(f"Cleaned data: {len(df):,} rows")
print(f"  Purchases: {(df['direction']==1).sum():,}")
print(f"  Sales: {(df['direction']==-1).sum():,}")
print(f"  Unique tickers: {df['ticker'].nunique()}")
print(f"  Unique members: {df['representative'].nunique()}")
print(f"  Period: {df['transaction_dt'].min().strftime('%Y-%m-%d')} to {df['transaction_dt'].max().strftime('%Y-%m-%d')}")

# ============================================================
# 2. DISCLOSURE LAG ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("DISCLOSURE LAG ANALYSIS")
print("=" * 70)

lag_stats = {
    'mean': df['lag_days'].mean(),
    'median': df['lag_days'].median(),
    'std': df['lag_days'].std(),
    'p10': df['lag_days'].quantile(0.10),
    'p25': df['lag_days'].quantile(0.25),
    'p50': df['lag_days'].quantile(0.50),
    'p75': df['lag_days'].quantile(0.75),
    'p90': df['lag_days'].quantile(0.90),
    'p95': df['lag_days'].quantile(0.95),
}
print(f"  Mean lag: {lag_stats['mean']:.1f} days")
print(f"  Median lag: {lag_stats['median']:.1f} days")
print(f"  10th-90th percentile: {lag_stats['p10']:.0f} - {lag_stats['p90']:.0f} days")
print(f"  95th percentile: {lag_stats['p95']:.0f} days")

# ============================================================
# 3. SECTOR CONCENTRATION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("TOP TRADED TICKERS (by aggregate dollar volume)")
print("=" * 70)

# Net buy signal = direction * amount
df['dollar_signal'] = df['direction'] * df['amount_mid']

# Top tickers by total dollar volume (absolute)
ticker_vol = df.groupby('ticker')['amount_mid'].sum().sort_values(ascending=False)
print("\nTop 20 by total dollar volume:")
for i, (ticker, vol) in enumerate(ticker_vol.head(20).items()):
    net = df[df['ticker']==ticker]['dollar_signal'].sum()
    n_trades = len(df[df['ticker']==ticker])
    direction = "NET BUY" if net > 0 else "NET SELL"
    print(f"  {i+1:2d}. {ticker:6s} ${vol/1e6:7.2f}M total, ${abs(net)/1e6:7.2f}M {direction}, {n_trades} trades")

# ============================================================
# 4. DOWNLOAD STOCK PRICES
# ============================================================
print("\n" + "=" * 70)
print("DOWNLOADING STOCK PRICES")
print("=" * 70)

# Get top-100 most actively traded tickers for portfolio construction
top_tickers_by_trades = df['ticker'].value_counts().head(100).index.tolist()
# Also get top tickers by dollar volume
top_tickers_by_dollar = ticker_vol.head(100).index.tolist()
# Union
all_tickers = list(set(top_tickers_by_trades + top_tickers_by_dollar))
all_tickers = [t for t in all_tickers if t not in ['TDDXX', 'FDRXX', 'SPAXX']]  # remove money market
# Handle ticker renames: FB -> META (June 2022)
if 'FB' in all_tickers:
    all_tickers.remove('FB')
    all_tickers.append('META')
all_tickers = sorted(all_tickers)

# Add SPY for benchmark
if 'SPY' not in all_tickers:
    all_tickers.append('SPY')

print(f"Downloading prices for {len(all_tickers)} tickers...")

# Batch download to save time — use a single yfinance call
start_date = '2019-12-01'
end_date = '2023-06-30'

def download_ticker(ticker):
    """Download single ticker with retry."""
    for attempt in range(2):
        try:
            data = yf.download(ticker, start=start_date, end=end_date,
                             progress=False, auto_adjust=True)
            if data is not None and len(data) > 50:
                # yfinance may return MultiIndex columns like ('Close', 'AAPL')
                close = data['Close']
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]  # take first column
                return ticker, close
        except:
            pass
    return ticker, None

# Parallel download
prices = {}
failed_tickers = []
t0 = time.time()

with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {executor.submit(download_ticker, t): t for t in all_tickers}
    for future in as_completed(futures):
        ticker, data = future.result()
        if data is not None:
            # Ensure it's a 1-D Series
            if isinstance(data, pd.DataFrame):
                data = data.iloc[:, 0]
            elif isinstance(data, pd.Series) and data.ndim != 1:
                data = data.squeeze()
            prices[ticker] = data
        else:
            failed_tickers.append(ticker)

elapsed = time.time() - t0
print(f"Downloaded {len(prices)} tickers in {elapsed:.1f}s (failed: {len(failed_tickers)})")
if failed_tickers[:10]:
    print(f"  Failed examples: {failed_tickers[:10]}")

# Build price DataFrame
price_df = pd.DataFrame(prices)
price_df.index = pd.to_datetime(price_df.index)
# Handle any timezone
if price_df.index.tz is not None:
    price_df.index = price_df.index.tz_localize(None)

# Daily returns
returns_df = price_df.pct_change().dropna(how='all')

print(f"Price matrix: {price_df.shape[0]} days × {price_df.shape[1]} tickers")
print(f"Returns period: {returns_df.index[0].strftime('%Y-%m-%d')} to {returns_df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 5. BUILD AGGREGATE CONGRESSIONAL PORTFOLIO
# ============================================================
print("\n" + "=" * 70)
print("BUILDING AGGREGATE CONGRESSIONAL PORTFOLIOS")
print("=" * 70)

# Available tickers (those we successfully downloaded)
available_tickers = set(prices.keys()) - {'SPY'}

# Filter trades to available tickers
df_avail = df[df['ticker'].isin(available_tickers)].copy()
print(f"Trades with available price data: {len(df_avail):,} ({len(df_avail)/len(df)*100:.1f}% of total)")

def compute_monthly_signals(trades_df, date_col, lookback_days=60):
    """
    For each month-end, compute net buying signal for each ticker
    using trades in the trailing lookback window.

    Args:
        trades_df: DataFrame with trades
        date_col: 'disclosure_dt' or 'transaction_dt'
        lookback_days: trailing window in days

    Returns:
        Dict[month_end_date -> Dict[ticker -> net_dollar_buy]]
    """
    # Generate month-end dates
    min_date = trades_df[date_col].min()
    max_date = trades_df[date_col].max()
    month_ends = pd.date_range(min_date, max_date, freq='ME')

    signals = {}
    for me in month_ends:
        window_start = me - pd.Timedelta(days=lookback_days)
        mask = (trades_df[date_col] >= window_start) & (trades_df[date_col] <= me)
        window_trades = trades_df[mask]

        # Net dollar signal per ticker
        net_signal = window_trades.groupby('ticker')['dollar_signal'].sum()
        # Also count trades
        trade_count = window_trades.groupby('ticker').size()

        signals[me] = {
            'net_dollar': net_signal.to_dict(),
            'trade_count': trade_count.to_dict()
        }

    return signals

def build_portfolio_returns(signals, returns_df, top_n=10, method='net_dollar'):
    """
    Build monthly rebalanced equal-weight portfolio of top-N net-bought tickers.

    Entry: first trading day of next month (signal known at month-end).
    This is the shift(1) equivalent — signal from month M, returns in month M+1.
    """
    port_returns = []
    holdings_log = []

    sorted_months = sorted(signals.keys())

    for i, signal_date in enumerate(sorted_months[:-1]):
        sig = signals[signal_date]

        if method == 'net_dollar':
            ticker_scores = sig['net_dollar']
        else:  # trade_count
            ticker_scores = sig['trade_count']

        # Filter to positive net buys only
        buys = {t: v for t, v in ticker_scores.items() if v > 0 and t in returns_df.columns}

        if len(buys) == 0:
            continue

        # Top N
        sorted_tickers = sorted(buys.items(), key=lambda x: x[1], reverse=True)
        top_tickers = [t for t, _ in sorted_tickers[:top_n]]

        # Get returns for next month
        next_month_start = signal_date + pd.Timedelta(days=1)
        if i + 1 < len(sorted_months):
            next_month_end = sorted_months[i + 1]
        else:
            next_month_end = returns_df.index[-1]

        # Get trading days in the holding period
        mask = (returns_df.index > signal_date) & (returns_df.index <= next_month_end)
        period_returns = returns_df.loc[mask, [t for t in top_tickers if t in returns_df.columns]]

        if period_returns.empty or period_returns.shape[1] == 0:
            continue

        # Equal weight
        n_stocks = period_returns.shape[1]
        daily_port_ret = period_returns.mean(axis=1)  # equal weight

        for date, ret in daily_port_ret.items():
            if not np.isnan(ret):
                port_returns.append({'date': date, 'return': ret})

        holdings_log.append({
            'signal_date': signal_date.strftime('%Y-%m-%d'),
            'holdings': list(period_returns.columns),
            'n_stocks': n_stocks,
            'period_return': float(daily_port_ret.sum()) if not daily_port_ret.empty else 0
        })

    return pd.DataFrame(port_returns).set_index('date')['return'], holdings_log


# Build signals using BOTH date columns
print("\nComputing monthly signals...")

# Strategy 1: REALISTIC — use disclosure_date (public info)
signals_realistic = compute_monthly_signals(df_avail, 'disclosure_dt', lookback_days=60)

# Strategy 2: PERFECT INFO — use transaction_date (would need inside info)
signals_perfect = compute_monthly_signals(df_avail, 'transaction_dt', lookback_days=60)

# Build portfolios
TOP_N = 10

print(f"\nBuilding Top-{TOP_N} net-bought portfolios...")
ret_realistic, log_realistic = build_portfolio_returns(
    signals_realistic, returns_df, top_n=TOP_N, method='net_dollar')
ret_perfect, log_perfect = build_portfolio_returns(
    signals_perfect, returns_df, top_n=TOP_N, method='net_dollar')

# Also try trade-count method
ret_realistic_count, log_realistic_count = build_portfolio_returns(
    signals_realistic, returns_df, top_n=TOP_N, method='trade_count')

# SPY benchmark — same period
spy_returns = returns_df['SPY'].dropna()

# Align all to common period
common_start = max(ret_realistic.index.min(), ret_perfect.index.min(), spy_returns.index.min())
common_end = min(ret_realistic.index.max(), ret_perfect.index.max(), spy_returns.index.max())

ret_realistic = ret_realistic[(ret_realistic.index >= common_start) & (ret_realistic.index <= common_end)]
ret_perfect = ret_perfect[(ret_perfect.index >= common_start) & (ret_perfect.index <= common_end)]
ret_realistic_count = ret_realistic_count[(ret_realistic_count.index >= common_start) & (ret_realistic_count.index <= common_end)]
spy_aligned = spy_returns[(spy_returns.index >= common_start) & (spy_returns.index <= common_end)]

# Re-align to exact same dates
common_dates = ret_realistic.index.intersection(spy_aligned.index)
ret_realistic = ret_realistic.loc[common_dates]
ret_perfect = ret_perfect.reindex(common_dates).fillna(0)
ret_realistic_count = ret_realistic_count.reindex(common_dates).fillna(0)
spy_aligned = spy_aligned.loc[common_dates]

print(f"\nCommon period: {common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')}")
print(f"Trading days: {len(common_dates)}")

# ============================================================
# 6. PERFORMANCE METRICS
# ============================================================
print("\n" + "=" * 70)
print("PERFORMANCE METRICS")
print("=" * 70)

def compute_metrics(returns, name):
    """Compute standard performance metrics."""
    if len(returns) == 0:
        return None
    cumret = (1 + returns).cumprod()
    total_ret = cumret.iloc[-1] - 1
    n_years = len(returns) / 252
    cagr = (1 + total_ret) ** (1/n_years) - 1 if n_years > 0 else 0
    vol = returns.std() * np.sqrt(252)
    sharpe = (returns.mean() * 252) / vol if vol > 0 else 0

    # Max drawdown
    running_max = cumret.cummax()
    drawdown = cumret / running_max - 1
    mdd = drawdown.min()

    # Monthly returns for win rate
    monthly = returns.resample('ME').sum()
    spy_monthly = spy_aligned.resample('ME').sum()
    # Align
    common_months = monthly.index.intersection(spy_monthly.index)
    monthly = monthly.loc[common_months]
    spy_m = spy_monthly.loc[common_months]
    win_rate = (monthly > spy_m).mean() if len(common_months) > 0 else 0

    # Positive months
    pos_rate = (monthly > 0).mean()

    metrics = {
        'name': name,
        'total_return': float(total_ret),
        'cagr': float(cagr),
        'annual_vol': float(vol),
        'sharpe': float(sharpe),
        'max_drawdown': float(mdd),
        'monthly_win_vs_spy': float(win_rate),
        'positive_months': float(pos_rate),
        'n_days': len(returns),
        'n_months': len(common_months),
    }
    return metrics

strategies = {
    'Congressional (Realistic, Disclosure+1)': ret_realistic,
    'Congressional (Perfect Info, Transaction+1)': ret_perfect,
    'Congressional (Count-based, Disclosure+1)': ret_realistic_count,
    'SPY Buy & Hold': spy_aligned,
}

all_metrics = {}
for name, rets in strategies.items():
    m = compute_metrics(rets, name)
    if m:
        all_metrics[name] = m
        print(f"\n  {name}:")
        print(f"    CAGR:     {m['cagr']*100:+.2f}%")
        print(f"    Sharpe:   {m['sharpe']:.3f}")
        print(f"    Vol:      {m['annual_vol']*100:.2f}%")
        print(f"    MDD:      {m['max_drawdown']*100:.2f}%")
        print(f"    Monthly win vs SPY: {m['monthly_win_vs_spy']*100:.1f}%")
        print(f"    Positive months:    {m['positive_months']*100:.1f}%")

# ============================================================
# 7. ALPHA LOST TO DISCLOSURE DELAY
# ============================================================
print("\n" + "=" * 70)
print("ALPHA LOST TO DISCLOSURE DELAY")
print("=" * 70)

m_real = all_metrics.get('Congressional (Realistic, Disclosure+1)', {})
m_perf = all_metrics.get('Congressional (Perfect Info, Transaction+1)', {})
m_spy = all_metrics.get('SPY Buy & Hold', {})

if m_real and m_perf and m_spy:
    print(f"\n  Perfect Info CAGR:  {m_perf['cagr']*100:+.2f}%")
    print(f"  Realistic CAGR:     {m_real['cagr']*100:+.2f}%")
    print(f"  SPY CAGR:           {m_spy['cagr']*100:+.2f}%")

    alpha_perfect = m_perf['cagr'] - m_spy['cagr']
    alpha_realistic = m_real['cagr'] - m_spy['cagr']
    alpha_lost = alpha_perfect - alpha_realistic

    print(f"\n  Perfect Info alpha vs SPY:  {alpha_perfect*100:+.2f}% p.a.")
    print(f"  Realistic alpha vs SPY:    {alpha_realistic*100:+.2f}% p.a.")
    print(f"  Alpha lost to delay:       {alpha_lost*100:+.2f}% p.a.")

    if alpha_perfect != 0:
        pct_lost = alpha_lost / abs(alpha_perfect) * 100
        print(f"  Percentage of alpha lost:  {pct_lost:.1f}%")

# ============================================================
# 8. BUY vs SELL SIGNAL ASYMMETRY
# ============================================================
print("\n" + "=" * 70)
print("BUY vs SELL SIGNAL ANALYSIS")
print("=" * 70)

# Aggregate: do sells have informational content?
# Build a "sell signal" portfolio — short or avoid the most-sold tickers
def build_sell_signal_portfolio(trades_df, date_col, returns_df, top_n=10, lookback=60):
    """Build portfolio that AVOIDS the most-sold tickers (holds everything else in top-50)."""
    month_ends = pd.date_range(trades_df[date_col].min(), trades_df[date_col].max(), freq='ME')

    sell_returns = []
    for i, me in enumerate(month_ends[:-1]):
        window_start = me - pd.Timedelta(days=lookback)
        mask = (trades_df[date_col] >= window_start) & (trades_df[date_col] <= me)
        window_trades = trades_df[mask]

        # Most-sold tickers
        sells = window_trades[window_trades['direction'] == -1]
        sell_volume = sells.groupby('ticker')['amount_mid'].sum().sort_values(ascending=False)
        top_sells = sell_volume.head(top_n).index.tolist()

        # Most-bought tickers
        buys = window_trades[window_trades['direction'] == 1]
        buy_volume = buys.groupby('ticker')['amount_mid'].sum().sort_values(ascending=False)
        top_buys = buy_volume.head(top_n).index.tolist()

        # Holding period
        next_me = month_ends[i + 1] if i + 1 < len(month_ends) else returns_df.index[-1]
        period_mask = (returns_df.index > me) & (returns_df.index <= next_me)

        # Returns of most-sold tickers
        sell_tickers_avail = [t for t in top_sells if t in returns_df.columns]
        buy_tickers_avail = [t for t in top_buys if t in returns_df.columns]

        if sell_tickers_avail:
            sell_period_ret = returns_df.loc[period_mask, sell_tickers_avail].mean(axis=1)
            for date, ret in sell_period_ret.items():
                if not np.isnan(ret):
                    sell_returns.append({'date': date, 'return': ret, 'type': 'most_sold'})

    return pd.DataFrame(sell_returns).set_index('date')

sell_df = build_sell_signal_portfolio(df_avail, 'disclosure_dt', returns_df, top_n=10)
if not sell_df.empty:
    sell_rets = sell_df['return']
    sell_rets = sell_rets.reindex(common_dates).fillna(0)
    m_sell = compute_metrics(sell_rets, 'Most-Sold Tickers (Disclosure+1)')
    all_metrics['Most-Sold Tickers'] = m_sell

    print(f"\n  Most-Sold tickers CAGR:  {m_sell['cagr']*100:+.2f}%")
    print(f"  Most-Sold tickers Sharpe: {m_sell['sharpe']:.3f}")
    print(f"  Most-Bought CAGR:         {m_real['cagr']*100:+.2f}%")
    print(f"  Asymmetry (buy - sell CAGR): {(m_real['cagr'] - m_sell['cagr'])*100:+.2f}%")
    print(f"\n  Interpretation: If most-sold tickers underperform most-bought,")
    print(f"  congressional sell signals also contain information.")

# ============================================================
# 9. TOP TRADERS ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("TOP CONGRESSIONAL TRADERS (by trade volume)")
print("=" * 70)

trader_vol = df.groupby('representative').agg(
    n_trades=('ticker', 'count'),
    total_dollar=('amount_mid', 'sum'),
    n_tickers=('ticker', 'nunique'),
    avg_lag=('lag_days', 'mean')
).sort_values('total_dollar', ascending=False)

print("\nTop 15 by total dollar volume:")
for i, (rep, row) in enumerate(trader_vol.head(15).iterrows()):
    print(f"  {i+1:2d}. {rep:40s} ${row['total_dollar']/1e6:7.2f}M  "
          f"{int(row['n_trades']):4d} trades  {int(row['n_tickers']):3d} tickers  "
          f"avg lag {row['avg_lag']:.0f}d")

# ============================================================
# 10. GENERATE CHARTS
# ============================================================
print("\n" + "=" * 70)
print("GENERATING CHARTS")
print("=" * 70)

os.makedirs('experiments/k858_charts', exist_ok=True)

# Chart 1: Cumulative returns comparison
fig, ax = plt.subplots(figsize=(12, 6))
for name, rets in strategies.items():
    cum = (1 + rets).cumprod()
    label = name.replace('Congressional ', 'Cong. ')
    ax.plot(cum.index, cum.values, label=label, linewidth=1.5 if 'SPY' not in name else 2.0,
            linestyle='-' if 'SPY' not in name else '--')

ax.set_title('K858: Congressional Aggregate Portfolio vs SPY', fontsize=14, fontweight='bold')
ax.set_ylabel('Cumulative Return (Growth of $1)')
ax.legend(fontsize=9, loc='upper left')
ax.grid(True, alpha=0.3)
ax.axhline(1.0, color='gray', linewidth=0.5, linestyle=':')
fig.tight_layout()
fig.savefig('experiments/k858_charts/cumulative_returns.png', dpi=150)
plt.close()
print("  Saved: k858_charts/cumulative_returns.png")

# Chart 2: Disclosure lag distribution
fig, ax = plt.subplots(figsize=(10, 5))
lag_data = df['lag_days']
ax.hist(lag_data, bins=50, range=(0, 180), color='#3b82f6', alpha=0.7, edgecolor='white')
ax.axvline(lag_data.median(), color='red', linewidth=2, linestyle='--', label=f'Median: {lag_data.median():.0f} days')
ax.axvline(lag_data.mean(), color='orange', linewidth=2, linestyle='--', label=f'Mean: {lag_data.mean():.0f} days')
ax.set_title('K858: Congressional Trade Disclosure Lag Distribution', fontsize=14, fontweight='bold')
ax.set_xlabel('Days between Transaction and Public Disclosure')
ax.set_ylabel('Number of Trades')
ax.legend()
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig('experiments/k858_charts/disclosure_lag.png', dpi=150)
plt.close()
print("  Saved: k858_charts/disclosure_lag.png")

# Chart 3: Monthly alpha (realistic strategy - SPY)
monthly_real = ret_realistic.resample('ME').sum()
monthly_spy = spy_aligned.resample('ME').sum()
common_m = monthly_real.index.intersection(monthly_spy.index)
monthly_alpha = monthly_real.loc[common_m] - monthly_spy.loc[common_m]

fig, ax = plt.subplots(figsize=(12, 5))
colors = ['#22c55e' if x > 0 else '#ef4444' for x in monthly_alpha.values]
ax.bar(monthly_alpha.index, monthly_alpha.values * 100, color=colors, width=25)
ax.set_title('K858: Monthly Alpha (Congressional Realistic vs SPY)', fontsize=14, fontweight='bold')
ax.set_ylabel('Monthly Alpha (%)')
ax.axhline(0, color='black', linewidth=0.5)
ax.grid(True, alpha=0.3, axis='y')
fig.tight_layout()
fig.savefig('experiments/k858_charts/monthly_alpha.png', dpi=150)
plt.close()
print("  Saved: k858_charts/monthly_alpha.png")

# Chart 4: Sector concentration (top traded tickers)
top20 = ticker_vol.head(15)
fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.barh(range(len(top20)), top20.values / 1e6, color='#3b82f6', alpha=0.8)
ax.set_yticks(range(len(top20)))
ax.set_yticklabels(top20.index)
ax.set_xlabel('Aggregate Dollar Volume ($M)')
ax.set_title('K858: Top 15 Tickers by Congressional Dollar Volume', fontsize=14, fontweight='bold')
ax.invert_yaxis()
ax.grid(True, alpha=0.3, axis='x')
fig.tight_layout()
fig.savefig('experiments/k858_charts/top_tickers.png', dpi=150)
plt.close()
print("  Saved: k858_charts/top_tickers.png")

# Chart 5: Buy vs Sell signal comparison
if 'Most-Sold Tickers' in all_metrics:
    fig, ax = plt.subplots(figsize=(10, 5))
    cum_buy = (1 + ret_realistic).cumprod()
    cum_sell = (1 + sell_rets.reindex(common_dates).fillna(0)).cumprod()
    cum_spy = (1 + spy_aligned).cumprod()
    ax.plot(cum_buy.index, cum_buy.values, label='Most-Bought (Congress)', color='#22c55e', linewidth=1.5)
    ax.plot(cum_sell.index, cum_sell.values, label='Most-Sold (Congress)', color='#ef4444', linewidth=1.5)
    ax.plot(cum_spy.index, cum_spy.values, label='SPY', color='#3b82f6', linewidth=2, linestyle='--')
    ax.set_title('K858: Congressional Buy vs Sell Signals', fontsize=14, fontweight='bold')
    ax.set_ylabel('Cumulative Return ($1 → )')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig('experiments/k858_charts/buy_vs_sell.png', dpi=150)
    plt.close()
    print("  Saved: k858_charts/buy_vs_sell.png")

# ============================================================
# 11. STATISTICAL SIGNIFICANCE
# ============================================================
print("\n" + "=" * 70)
print("STATISTICAL SIGNIFICANCE")
print("=" * 70)

# Simple t-test of daily excess returns
from scipy import stats

excess_realistic = ret_realistic - spy_aligned
excess_perfect = ret_perfect - spy_aligned

t_stat_real, p_val_real = stats.ttest_1samp(excess_realistic.dropna(), 0)
t_stat_perf, p_val_perf = stats.ttest_1samp(excess_perfect.dropna(), 0)

print(f"\n  Realistic strategy daily excess return:")
print(f"    Mean: {excess_realistic.mean()*252*100:.2f}% ann.")
print(f"    t-stat: {t_stat_real:.3f}  (p={p_val_real:.4f})")
print(f"    Significant at 5%? {'YES' if p_val_real < 0.05 else 'NO'}")
print(f"    Harvey (2016) t>3.0? {'YES' if abs(t_stat_real) > 3.0 else 'NO'}")

print(f"\n  Perfect info strategy daily excess return:")
print(f"    Mean: {excess_perfect.mean()*252*100:.2f}% ann.")
print(f"    t-stat: {t_stat_perf:.3f}  (p={p_val_perf:.4f})")
print(f"    Significant at 5%? {'YES' if p_val_perf < 0.05 else 'NO'}")
print(f"    Harvey (2016) t>3.0? {'YES' if abs(t_stat_perf) > 3.0 else 'NO'}")

# ============================================================
# 12. SENSITIVITY: DIFFERENT TOP-N
# ============================================================
print("\n" + "=" * 70)
print("SENSITIVITY ANALYSIS: TOP-N VARIATIONS")
print("=" * 70)

sensitivity = {}
for n in [5, 10, 15, 20, 30]:
    rets_n, _ = build_portfolio_returns(signals_realistic, returns_df, top_n=n, method='net_dollar')
    rets_n = rets_n.reindex(common_dates).fillna(0)
    m = compute_metrics(rets_n, f'Top-{n}')
    sensitivity[n] = m
    print(f"  Top-{n:2d}: CAGR={m['cagr']*100:+.2f}%  Sharpe={m['sharpe']:.3f}  MDD={m['max_drawdown']*100:.2f}%")

# ============================================================
# 13. COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)

conclusion_lines = []
if m_real and m_spy:
    if m_real['cagr'] > m_spy['cagr']:
        conclusion_lines.append(f"Congressional aggregate portfolio OUTPERFORMED SPY by {(m_real['cagr']-m_spy['cagr'])*100:.2f}% CAGR")
    else:
        conclusion_lines.append(f"Congressional aggregate portfolio UNDERPERFORMED SPY by {(m_spy['cagr']-m_real['cagr'])*100:.2f}% CAGR")

    if p_val_real < 0.05:
        conclusion_lines.append("The excess return IS statistically significant at 5% level")
    else:
        conclusion_lines.append("The excess return is NOT statistically significant at 5% level")

    if abs(t_stat_real) > 3.0:
        conclusion_lines.append("Passes Harvey (2016) t>3.0 threshold — genuine alpha")
    else:
        conclusion_lines.append("FAILS Harvey (2016) t>3.0 threshold — could be data mining")

    conclusion_lines.append(f"Disclosure delay costs approximately {alpha_lost*100:+.2f}% annual alpha")
    conclusion_lines.append(f"Median disclosure lag: {lag_stats['median']:.0f} days")

for line in conclusion_lines:
    print(f"  • {line}")

# Build results JSON
results = {
    "experiment_id": "K858",
    "title": "Congressional Trading Alpha — Aggregate Portfolio Performance",
    "question": "Does following aggregate congressional stock trades generate alpha, even with disclosure delay?",
    "data_source": "data/congressional_trades_house.csv (House financial disclosures)",
    "price_source": "yfinance",
    "period": f"{common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')}",
    "n_trades_raw": 15674,
    "n_trades_cleaned": int(len(df)),
    "n_tickers_available": len(available_tickers),
    "n_members": int(df['representative'].nunique()),
    "methodology": {
        "portfolio_construction": "Monthly rebalanced, equal-weight top-10 net-bought tickers",
        "lookback_window": "60 days trailing",
        "signal_method": "Net dollar buying (purchases - sales) by all members",
        "realistic_entry": "disclosure_date + 1 business day (public information)",
        "perfect_info_entry": "transaction_date + 1 business day (upper bound)",
        "benchmark": "SPY buy-and-hold",
        "no_lookahead": "Entry strictly after signal date (disclosure or transaction)"
    },
    "disclosure_lag": {
        "mean_days": round(lag_stats['mean'], 1),
        "median_days": round(lag_stats['median'], 1),
        "p10_days": round(lag_stats['p10'], 0),
        "p90_days": round(lag_stats['p90'], 0),
        "p95_days": round(lag_stats['p95'], 0)
    },
    "performance": {k: v for k, v in all_metrics.items()},
    "alpha_analysis": {
        "realistic_alpha_vs_spy_annual": round(alpha_realistic * 100, 2),
        "perfect_info_alpha_vs_spy_annual": round(alpha_perfect * 100, 2),
        "alpha_lost_to_delay_annual": round(alpha_lost * 100, 2),
        "pct_alpha_lost_to_delay": round(pct_lost, 1) if alpha_perfect != 0 else None
    },
    "statistical_significance": {
        "realistic_t_stat": round(float(t_stat_real), 3),
        "realistic_p_value": round(float(p_val_real), 4),
        "realistic_significant_5pct": bool(p_val_real < 0.05),
        "realistic_harvey_t3": bool(abs(t_stat_real) > 3.0),
        "perfect_info_t_stat": round(float(t_stat_perf), 3),
        "perfect_info_p_value": round(float(p_val_perf), 4),
        "perfect_info_significant_5pct": bool(p_val_perf < 0.05),
    },
    "sensitivity_top_n": {str(k): {
        'cagr': round(v['cagr']*100, 2),
        'sharpe': round(v['sharpe'], 3),
        'mdd': round(v['max_drawdown']*100, 2)
    } for k, v in sensitivity.items()},
    "conclusions": conclusion_lines,
    "limitations": [
        "Data covers only 2020-2022 (House disclosures) — includes COVID crash & recovery, atypical period",
        "Amount ranges (e.g. $1,001-$15,000) provide imprecise dollar weighting",
        "No transaction costs deducted (monthly rebalancing of 10 stocks would cost ~0.1-0.3% p.a.)",
        "Survivorship bias: some tickers may have been delisted",
        "Small sample: ~2 years of returns limits statistical power",
        "Only House members — Senate data would expand the sample"
    ],
    "references": [
        "Eggers & Hainmueller (2014) 'Capitol Losses' JoP — found mediocre performance for individual portfolios",
        "Ziobrowski et al. (2004) 'Abnormal Returns from U.S. Senate' JFQA — found ~12% annual excess for Senators",
        "Karadas (2019) 'Trading on Private Information' EL — found significant abnormal returns around committee-relevant trades"
    ],
    "charts": [
        "experiments/k858_charts/cumulative_returns.png",
        "experiments/k858_charts/disclosure_lag.png",
        "experiments/k858_charts/monthly_alpha.png",
        "experiments/k858_charts/top_tickers.png",
        "experiments/k858_charts/buy_vs_sell.png"
    ],
    "timestamp": datetime.now(timezone.utc).isoformat()
}

# Save results
with open('experiments/k858_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n✓ Results saved to experiments/k858_results.json")
print(f"✓ Charts saved to experiments/k858_charts/")
print(f"\nDone!")
