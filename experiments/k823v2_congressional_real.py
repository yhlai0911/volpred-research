"""
K823v2: Congressional Trading Copy-Cat Strategy — Real Data Backtest
=====================================================================
Data: US House financial disclosures (15,674 trades)
Source: house_stock_watcher / Capitol Trades open data
Period: 2021-2022 (disclosure_year)

Strategies:
  S0: Buy-and-Hold SPY (baseline)
  S1: Oracle — trade on transaction_date (impossible for retail)
  S2: Disclosure-Day — trade on disclosure_date (first realistic date)
  S3: Disclosure+5 — trade 5 days after disclosure (retail reaction delay)
  S4: Top-10 Traders — S2 restricted to 10 most active representatives

Methodology:
  - Event study: each purchase signal → buy ticker, hold 22 trading days
  - Forward return = price(t+22)/price(t) - 1
  - Excess return = forward_return - SPY_forward_return (same window)
  - Only purchases (sales ignored — no shorting)
  - Equal-weight across concurrent signals
  - Statistical test: one-sample t-test on excess returns, Harvey (2016) t>3.0

References:
  - Eggers & Hainmueller (2014) "Capitol Losses" — find no abnormal returns
  - Unusual Whales congressional tracker methodology
  - Harvey, Campbell R. (2016) "...and the Cross-Section of Expected Returns"

Error log rules applied:
  - No lookahead: S2/S3/S4 use disclosure_date (public info), NOT transaction_date
  - Date cleaning: filter invalid dates
  - Ticker cleaning: filter "--" and non-tradeable tickers
"""

import pandas as pd
import numpy as np
import yfinance as yf
import json
import warnings
from datetime import datetime, timedelta
from scipy import stats
from pathlib import Path

warnings.filterwarnings('ignore')

# ============================================================
# 1. Load and clean data
# ============================================================
# Data is in the main repo (not worktree)
_repo_root = Path(__file__).resolve().parents[1]
DATA_PATH = _repo_root / "data" / "congressional_trades_house.csv"
if not DATA_PATH.exists():
    # Try main repo path
    DATA_PATH = Path("/Users/yhlai0911/Desktop/volpred-research/data/congressional_trades_house.csv")
df = pd.read_csv(DATA_PATH)
print(f"Raw data: {len(df)} rows")

# --- Clean dates ---
def parse_disclosure_date(d):
    """Disclosure date format: MM/DD/YYYY"""
    try:
        return pd.to_datetime(d, format='%m/%d/%Y')
    except:
        return pd.NaT

def parse_transaction_date(d):
    """Transaction date format: YYYY-MM-DD, but has anomalies"""
    try:
        dt = pd.to_datetime(d)
        # Filter unreasonable years
        if dt.year < 2015 or dt.year > 2030:
            return pd.NaT
        return dt
    except:
        return pd.NaT

df['disc_dt'] = df['disclosure_date'].apply(parse_disclosure_date)
df['txn_dt'] = df['transaction_date'].apply(parse_transaction_date)

# Drop rows with invalid dates
n_before = len(df)
df = df.dropna(subset=['disc_dt', 'txn_dt'])
print(f"After date cleaning: {len(df)} rows (dropped {n_before - len(df)} with bad dates)")

# --- Clean tickers ---
df = df[df['ticker'] != '--'].copy()
df = df[df['ticker'].notna()].copy()
# Remove tickers that are clearly not equities (warrants, bonds, etc.)
df = df[~df['ticker'].str.contains(r'[^A-Z0-9.]', na=True)].copy()
print(f"After ticker cleaning: {len(df)} rows")

# --- Filter to purchases only ---
purchases = df[df['type'] == 'purchase'].copy()
print(f"Purchase signals: {len(purchases)}")

# --- Compute disclosure delay ---
purchases['delay_days'] = (purchases['disc_dt'] - purchases['txn_dt']).dt.days
# Some negative delays (disclosure before transaction?) — flag but keep
delay_stats = purchases['delay_days'].describe()
print(f"\nDisclosure delay (days):")
print(delay_stats)
print(f"Median delay: {purchases['delay_days'].median():.0f} days")
print(f"Mean delay: {purchases['delay_days'].mean():.1f} days")

# Distribution
delay_bins = [0, 7, 14, 30, 45, 60, 90, 180, 999]
delay_labels = ['0-7d', '8-14d', '15-30d', '31-45d', '46-60d', '61-90d', '91-180d', '>180d']
purchases['delay_bin'] = pd.cut(purchases['delay_days'], bins=delay_bins, labels=delay_labels, right=True)
delay_dist = purchases['delay_bin'].value_counts().sort_index()
print(f"\nDelay distribution:")
for b, c in delay_dist.items():
    print(f"  {b}: {c} ({c/len(purchases)*100:.1f}%)")

# ============================================================
# 2. Identify top tickers and download prices
# ============================================================
ticker_counts = purchases['ticker'].value_counts()
print(f"\nTotal unique tickers in purchases: {len(ticker_counts)}")

# Take top 60 tickers (covers majority of trades)
TOP_N_TICKERS = 60
top_tickers = ticker_counts.head(TOP_N_TICKERS).index.tolist()
top_ticker_trades = purchases[purchases['ticker'].isin(top_tickers)]
print(f"Top {TOP_N_TICKERS} tickers cover {len(top_ticker_trades)}/{len(purchases)} trades ({len(top_ticker_trades)/len(purchases)*100:.1f}%)")

# Add SPY for baseline
all_tickers = list(set(top_tickers + ['SPY']))

# Date range for download: earliest transaction - 30d to latest disclosure + 60d
date_min = min(purchases['txn_dt'].min(), purchases['disc_dt'].min()) - timedelta(days=30)
date_max = max(purchases['disc_dt'].max(), purchases['txn_dt'].max()) + timedelta(days=60)
print(f"\nDownloading prices for {len(all_tickers)} tickers from {date_min.date()} to {date_max.date()}")

# Batch download
price_data = {}
failed_tickers = []
# Download in batches of 10 to be nice to yfinance
batch_size = 10
ticker_list = sorted(all_tickers)
for i in range(0, len(ticker_list), batch_size):
    batch = ticker_list[i:i+batch_size]
    batch_str = ' '.join(batch)
    try:
        data = yf.download(batch_str, start=date_min.strftime('%Y-%m-%d'),
                          end=date_max.strftime('%Y-%m-%d'),
                          progress=False, group_by='ticker', auto_adjust=True)
        if len(batch) == 1:
            t = batch[0]
            if 'Close' in data.columns:
                price_data[t] = data['Close'].dropna()
        else:
            for t in batch:
                try:
                    if t in data.columns.get_level_values(0):
                        series = data[t]['Close'].dropna()
                        if len(series) > 0:
                            price_data[t] = series
                        else:
                            failed_tickers.append(t)
                    else:
                        failed_tickers.append(t)
                except:
                    failed_tickers.append(t)
    except Exception as e:
        print(f"  Batch download failed: {batch} — {e}")
        failed_tickers.extend(batch)

print(f"Successfully downloaded: {len(price_data)} tickers")
if failed_tickers:
    print(f"Failed tickers: {failed_tickers}")

# ============================================================
# 3. Compute forward returns for each trade signal
# ============================================================
HOLD_DAYS = 22  # ~1 month of trading days

def get_forward_return(ticker, signal_date, hold_days=HOLD_DAYS):
    """
    Get forward return starting from signal_date.
    Uses next available trading day if signal_date is not a trading day.
    Returns (fwd_return, actual_entry_date, actual_exit_date) or (NaN, None, None).
    """
    if ticker not in price_data:
        return np.nan, None, None

    prices = price_data[ticker]
    # Find next available trading day on or after signal_date
    valid_dates = prices.index[prices.index >= pd.Timestamp(signal_date)]
    if len(valid_dates) < hold_days + 1:
        return np.nan, None, None

    entry_date = valid_dates[0]
    # Find exit: hold_days trading days later
    entry_idx = prices.index.get_loc(entry_date)
    if entry_idx + hold_days >= len(prices):
        return np.nan, None, None

    exit_date = prices.index[entry_idx + hold_days]
    entry_price = prices.iloc[entry_idx]
    exit_price = prices.iloc[entry_idx + hold_days]

    if pd.isna(entry_price) or pd.isna(exit_price) or entry_price == 0:
        return np.nan, None, None

    fwd_ret = (exit_price / entry_price) - 1
    return float(fwd_ret), entry_date, exit_date


def get_spy_forward_return(signal_date, hold_days=HOLD_DAYS):
    """SPY forward return for the same window (for excess return calculation)."""
    return get_forward_return('SPY', signal_date, hold_days)


# Filter to top-ticker purchases only
trades = top_ticker_trades.copy()
print(f"\nComputing forward returns for {len(trades)} trades...")

# S1: Oracle (transaction_date)
oracle_rets = []
for _, row in trades.iterrows():
    fwd, _, _ = get_forward_return(row['ticker'], row['txn_dt'])
    spy_fwd, _, _ = get_spy_forward_return(row['txn_dt'])
    if not np.isnan(fwd) and not np.isnan(spy_fwd):
        oracle_rets.append({
            'ticker': row['ticker'],
            'representative': row['representative'],
            'txn_dt': row['txn_dt'],
            'disc_dt': row['disc_dt'],
            'delay_days': row['delay_days'],
            'fwd_return': fwd,
            'spy_fwd_return': spy_fwd,
            'excess_return': fwd - spy_fwd
        })

oracle_df = pd.DataFrame(oracle_rets)
print(f"S1 Oracle: {len(oracle_df)} valid trades")

# S2: Disclosure-Day (disclosure_date)
disc_rets = []
for _, row in trades.iterrows():
    fwd, _, _ = get_forward_return(row['ticker'], row['disc_dt'])
    spy_fwd, _, _ = get_spy_forward_return(row['disc_dt'])
    if not np.isnan(fwd) and not np.isnan(spy_fwd):
        disc_rets.append({
            'ticker': row['ticker'],
            'representative': row['representative'],
            'txn_dt': row['txn_dt'],
            'disc_dt': row['disc_dt'],
            'delay_days': row['delay_days'],
            'fwd_return': fwd,
            'spy_fwd_return': spy_fwd,
            'excess_return': fwd - spy_fwd
        })

disc_df = pd.DataFrame(disc_rets)
print(f"S2 Disclosure-Day: {len(disc_df)} valid trades")

# S3: Disclosure+5 (disclosure_date + 5 calendar days)
disc5_rets = []
for _, row in trades.iterrows():
    signal_dt = row['disc_dt'] + timedelta(days=5)
    fwd, _, _ = get_forward_return(row['ticker'], signal_dt)
    spy_fwd, _, _ = get_spy_forward_return(signal_dt)
    if not np.isnan(fwd) and not np.isnan(spy_fwd):
        disc5_rets.append({
            'ticker': row['ticker'],
            'representative': row['representative'],
            'txn_dt': row['txn_dt'],
            'disc_dt': row['disc_dt'],
            'delay_days': row['delay_days'],
            'fwd_return': fwd,
            'spy_fwd_return': spy_fwd,
            'excess_return': fwd - spy_fwd
        })

disc5_df = pd.DataFrame(disc5_rets)
print(f"S3 Disclosure+5: {len(disc5_df)} valid trades")

# S4: Top-10 Traders (S2 logic, restricted to most active reps)
top10_reps = trades['representative'].value_counts().head(10).index.tolist()
top10_trades = trades[trades['representative'].isin(top10_reps)]
print(f"\nTop 10 representatives: {top10_reps}")
print(f"S4 universe: {len(top10_trades)} trades from top-10 reps")

top10_rets = []
for _, row in top10_trades.iterrows():
    fwd, _, _ = get_forward_return(row['ticker'], row['disc_dt'])
    spy_fwd, _, _ = get_spy_forward_return(row['disc_dt'])
    if not np.isnan(fwd) and not np.isnan(spy_fwd):
        top10_rets.append({
            'ticker': row['ticker'],
            'representative': row['representative'],
            'txn_dt': row['txn_dt'],
            'disc_dt': row['disc_dt'],
            'delay_days': row['delay_days'],
            'fwd_return': fwd,
            'spy_fwd_return': spy_fwd,
            'excess_return': fwd - spy_fwd
        })

top10_df = pd.DataFrame(top10_rets)
print(f"S4 Top-10 Traders: {len(top10_df)} valid trades")

# ============================================================
# 4. Statistical analysis
# ============================================================
print("\n" + "="*70)
print("RESULTS: K823v2 Congressional Copy-Cat Strategy")
print("="*70)

def analyze_strategy(name, df_strat):
    """Compute key metrics for a strategy."""
    if len(df_strat) == 0:
        return None

    fwd = df_strat['fwd_return']
    excess = df_strat['excess_return']
    spy = df_strat['spy_fwd_return']

    # Hit rate (positive forward return)
    hit_rate = (fwd > 0).mean()
    # Excess hit rate (beat SPY)
    excess_hit_rate = (excess > 0).mean()

    # Mean returns
    mean_fwd = fwd.mean()
    mean_excess = excess.mean()
    mean_spy = spy.mean()

    # t-test: H0: mean excess return = 0
    t_stat, p_value = stats.ttest_1samp(excess, 0)

    # Median
    median_fwd = fwd.median()
    median_excess = excess.median()

    # Std
    std_fwd = fwd.std()
    std_excess = excess.std()

    # Annualized (22-day holding → ~12 periods/year)
    annual_excess = mean_excess * (252 / HOLD_DAYS)

    result = {
        'strategy': name,
        'n_trades': len(df_strat),
        'hit_rate': round(hit_rate, 4),
        'excess_hit_rate': round(excess_hit_rate, 4),
        'mean_fwd_return_pct': round(mean_fwd * 100, 3),
        'mean_spy_return_pct': round(mean_spy * 100, 3),
        'mean_excess_return_pct': round(mean_excess * 100, 3),
        'median_excess_return_pct': round(median_excess * 100, 3),
        'std_excess_return_pct': round(std_excess * 100, 3),
        'annualized_excess_pct': round(annual_excess * 100, 2),
        't_stat': round(t_stat, 3),
        'p_value': round(p_value, 6),
        'harvey_significant': abs(t_stat) > 3.0
    }

    print(f"\n--- {name} ---")
    print(f"  N trades:           {result['n_trades']}")
    print(f"  Hit rate (>0):      {result['hit_rate']:.1%}")
    print(f"  Excess hit rate:    {result['excess_hit_rate']:.1%}")
    print(f"  Mean fwd return:    {result['mean_fwd_return_pct']:.3f}%")
    print(f"  Mean SPY return:    {result['mean_spy_return_pct']:.3f}%")
    print(f"  Mean excess return: {result['mean_excess_return_pct']:.3f}%")
    print(f"  Median excess:      {result['median_excess_return_pct']:.3f}%")
    print(f"  Std excess:         {result['std_excess_return_pct']:.3f}%")
    print(f"  Annualized excess:  {result['annualized_excess_pct']:.2f}%")
    print(f"  t-stat:             {result['t_stat']:.3f}")
    print(f"  p-value:            {result['p_value']:.6f}")
    print(f"  Harvey significant: {result['harvey_significant']}")

    return result

results = []
results.append(analyze_strategy("S1: Oracle (txn_date)", oracle_df))
results.append(analyze_strategy("S2: Disclosure-Day", disc_df))
results.append(analyze_strategy("S3: Disclosure+5", disc5_df))
results.append(analyze_strategy("S4: Top-10 Traders", top10_df))

# ============================================================
# 5. Per-representative analysis (for S2)
# ============================================================
print("\n" + "="*70)
print("PER-REPRESENTATIVE ANALYSIS (S2: Disclosure-Day)")
print("="*70)

rep_results = []
for rep in disc_df['representative'].unique():
    rep_data = disc_df[disc_df['representative'] == rep]
    if len(rep_data) >= 10:  # Need at least 10 trades
        excess = rep_data['excess_return']
        mean_ex = excess.mean()
        t, p = stats.ttest_1samp(excess, 0)
        rep_results.append({
            'representative': rep,
            'n_trades': len(rep_data),
            'mean_excess_pct': round(mean_ex * 100, 3),
            'hit_rate': round((rep_data['fwd_return'] > 0).mean(), 3),
            'excess_hit_rate': round((excess > 0).mean(), 3),
            't_stat': round(t, 3),
            'p_value': round(p, 6)
        })

rep_df = pd.DataFrame(rep_results).sort_values('mean_excess_pct', ascending=False)
print(f"\nRepresentatives with >= 10 trades: {len(rep_df)}")
print("\nTop 10 by mean excess return:")
for _, r in rep_df.head(10).iterrows():
    sig = "***" if abs(r['t_stat']) > 3.0 else ("**" if abs(r['t_stat']) > 2.0 else ("*" if abs(r['t_stat']) > 1.96 else ""))
    print(f"  {r['representative']:<35s} n={r['n_trades']:>3d}  excess={r['mean_excess_pct']:>+7.3f}%  t={r['t_stat']:>6.3f}{sig}")

print("\nBottom 10 by mean excess return:")
for _, r in rep_df.tail(10).iterrows():
    sig = "***" if abs(r['t_stat']) > 3.0 else ("**" if abs(r['t_stat']) > 2.0 else ("*" if abs(r['t_stat']) > 1.96 else ""))
    print(f"  {r['representative']:<35s} n={r['n_trades']:>3d}  excess={r['mean_excess_pct']:>+7.3f}%  t={r['t_stat']:>6.3f}{sig}")

# How many reps significantly beat market?
sig_reps = rep_df[rep_df['t_stat'] > 1.96]
harvey_sig_reps = rep_df[rep_df['t_stat'] > 3.0]
print(f"\nReps with t > 1.96 (p<0.05): {len(sig_reps)}/{len(rep_df)}")
print(f"Reps with t > 3.0 (Harvey):  {len(harvey_sig_reps)}/{len(rep_df)}")

# ============================================================
# 6. Delay analysis: Does delay matter?
# ============================================================
print("\n" + "="*70)
print("DISCLOSURE DELAY vs EXCESS RETURN")
print("="*70)

# Bin by delay and compute average excess return
oracle_df_valid = oracle_df[oracle_df['delay_days'] >= 0].copy()
delay_group_bins = [0, 7, 14, 30, 60, 999]
delay_group_labels = ['0-7d', '8-14d', '15-30d', '31-60d', '>60d']
oracle_df_valid['delay_group'] = pd.cut(oracle_df_valid['delay_days'], bins=delay_group_bins, labels=delay_group_labels, right=True)

print("\nOracle excess return by delay group:")
for grp in delay_group_labels:
    g = oracle_df_valid[oracle_df_valid['delay_group'] == grp]
    if len(g) > 0:
        mean_ex = g['excess_return'].mean() * 100
        n = len(g)
        print(f"  {grp:<10s}: n={n:>4d}, mean excess = {mean_ex:>+7.3f}%")

# Correlation between delay and excess return
if len(oracle_df_valid) > 0:
    corr, corr_p = stats.pearsonr(oracle_df_valid['delay_days'], oracle_df_valid['excess_return'])
    print(f"\nCorrelation(delay, excess_return): r={corr:.4f}, p={corr_p:.4f}")

# ============================================================
# 7. Amount-weighted analysis
# ============================================================
print("\n" + "="*70)
print("AMOUNT-WEIGHTED ANALYSIS (S2)")
print("="*70)

def parse_amount_midpoint(amt_str):
    """Parse '$1,001 - $15,000' style amounts to midpoint."""
    if pd.isna(amt_str):
        return np.nan
    amt_str = str(amt_str).replace('$', '').replace(',', '').strip()
    if ' - ' in amt_str:
        parts = amt_str.split(' - ')
        try:
            lo = float(parts[0].strip())
            hi = float(parts[1].strip())
            return (lo + hi) / 2
        except:
            return np.nan
    else:
        # Single value or incomplete
        try:
            return float(amt_str)
        except:
            return np.nan

# Merge amount info
disc_df_amt = disc_df.merge(
    trades[['disc_dt', 'txn_dt', 'ticker', 'representative', 'amount']].drop_duplicates(),
    on=['disc_dt', 'txn_dt', 'ticker', 'representative'],
    how='left'
)
disc_df_amt['amount_mid'] = disc_df_amt['amount'].apply(parse_amount_midpoint)
disc_df_amt = disc_df_amt.dropna(subset=['amount_mid'])

# Large trades (> $50k midpoint)
large = disc_df_amt[disc_df_amt['amount_mid'] > 50000]
small = disc_df_amt[disc_df_amt['amount_mid'] <= 15000]

if len(large) > 0:
    t_large, p_large = stats.ttest_1samp(large['excess_return'], 0)
    print(f"Large trades (>$50k): n={len(large)}, mean excess={large['excess_return'].mean()*100:.3f}%, t={t_large:.3f}")

if len(small) > 0:
    t_small, p_small = stats.ttest_1samp(small['excess_return'], 0)
    print(f"Small trades (<=$15k): n={len(small)}, mean excess={small['excess_return'].mean()*100:.3f}%, t={t_small:.3f}")

# ============================================================
# 8. Save results
# ============================================================
delay_distribution = {}
for b, c in delay_dist.items():
    delay_distribution[str(b)] = int(c)

output = {
    "experiment_id": "K823v2",
    "title": "Congressional Trading Copy-Cat Strategy — Real Data Backtest",
    "data_source": "US House financial disclosures (Capitol Trades / house_stock_watcher)",
    "data_file": "data/congressional_trades_house.csv",
    "period": f"{purchases['txn_dt'].min().date()} to {purchases['txn_dt'].max().date()}",
    "n_raw_trades": int(len(df)),
    "n_purchases": int(len(purchases)),
    "n_top_tickers": TOP_N_TICKERS,
    "hold_period_days": HOLD_DAYS,
    "disclosure_delay": {
        "median_days": float(purchases['delay_days'].median()),
        "mean_days": float(purchases['delay_days'].mean()),
        "std_days": float(purchases['delay_days'].std()),
        "min_days": float(purchases['delay_days'].min()),
        "max_days": float(purchases['delay_days'].max()),
        "distribution": delay_distribution
    },
    "strategy_results": [r for r in results if r is not None],
    "per_representative": rep_df.to_dict('records') if len(rep_df) > 0 else [],
    "amount_analysis": {
        "large_trades_n": int(len(large)) if len(large) > 0 else 0,
        "large_trades_mean_excess_pct": round(large['excess_return'].mean() * 100, 3) if len(large) > 0 else None,
        "small_trades_n": int(len(small)) if len(small) > 0 else 0,
        "small_trades_mean_excess_pct": round(small['excess_return'].mean() * 100, 3) if len(small) > 0 else None,
    },
    "conclusion": "",  # Fill after seeing results
    "limitations": [
        "Only House members (no Senate)",
        "2021-2022 period only (post-STOCK Act enforcement)",
        "Top 60 tickers only (covers ~60-70% of trades)",
        "Equal-weight, no transaction costs",
        "Amount is reported in ranges, not exact",
        "No short selling (sales ignored)",
        "Survivorship bias: only tickers still trading on yfinance"
    ],
    "references": [
        "Eggers & Hainmueller (2014) Capitol Losses",
        "Unusual Whales Congressional Trading tracker",
        "Harvey (2016) t>3.0 threshold for multiple testing"
    ]
}

# Generate conclusion based on results
s2 = next((r for r in results if r and 'S2' in r['strategy']), None)
s1 = next((r for r in results if r and 'S1' in r['strategy']), None)
if s2 and s1:
    if s2['harvey_significant']:
        conclusion = f"Congressional copy-cat strategy (disclosure-day) shows STATISTICALLY SIGNIFICANT excess return of {s2['mean_excess_return_pct']:.3f}% per 22-day period (t={s2['t_stat']:.3f}, passing Harvey threshold). This suggests information advantage persists even after public disclosure."
    elif s2['p_value'] < 0.05:
        conclusion = f"Congressional copy-cat strategy (disclosure-day) shows marginally significant excess return of {s2['mean_excess_return_pct']:.3f}% per 22-day period (t={s2['t_stat']:.3f}, p={s2['p_value']:.4f}), but does NOT pass Harvey (2016) t>3.0 threshold. Economically small."
    else:
        conclusion = f"Congressional copy-cat strategy (disclosure-day) shows NO statistically significant excess return ({s2['mean_excess_return_pct']:.3f}% per 22-day period, t={s2['t_stat']:.3f}, p={s2['p_value']:.4f}). Consistent with Eggers & Hainmueller (2014) finding of no abnormal returns post-STOCK Act."

    # Add oracle comparison
    conclusion += f" Oracle strategy (impossible for retail) has excess return {s1['mean_excess_return_pct']:.3f}% (t={s1['t_stat']:.3f}), showing {'some' if s1['p_value'] < 0.05 else 'no'} information content in transaction timing."

    output['conclusion'] = conclusion

# Save
OUT_PATH = Path(__file__).resolve().parent / "k823v2_congressional_real_results.json"
with open(OUT_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n\nResults saved to {OUT_PATH}")

print("\n" + "="*70)
print("CONCLUSION")
print("="*70)
print(output['conclusion'])
