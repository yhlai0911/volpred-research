"""
K1042: Congressional Trades as Volatility/Return Signal
========================================================

Core question: Does the aggregate buy/sell flow of US congressional trades
predict SPY volatility or returns?

Data sources:
- Congressional trades: data/congressional_trades_house.csv (15,674 rows, 2019-2022)
- SPY prices: yfinance (2019-01-01 to 2023-06-30)

Key design choices:
- Use disclosure_date (not transaction_date) as signal availability date
  to prevent lookahead bias. Investors cannot act until disclosure.
- Signal lagged by 1 day: signal constructed from disclosures up to t-1,
  used to predict r_t or vol_t. This is conservative.
- Amount parsed from string ranges to midpoint dollar estimates.
- Sparse signal filled forward (last known value carries).

References:
- Ziobrowski et al. (2004) "Abnormal Returns from the Common Stock
  Investments of the U.S. Senate" JFQA 39(4).
- Ziobrowski et al. (2011) "Abnormal Returns from the Common Stock
  Investments of Members of the U.S. House" Business and Politics 13(1).
- Eggers & Hainmueller (2014) "Capitol Losses: The Mediocre Performance
  of Congressional Stock Portfolios" Journal of Politics 76(2).

Seed: 42
"""

import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant
from statsmodels.tsa.stattools import grangercausalitytests
import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

OUT_DIR = Path(__file__).parent
RESULTS = {}

# ============================================================
# 1. Load and clean congressional trades
# ============================================================
print("=" * 60)
print("Step 1: Loading congressional trades data")
print("=" * 60)

df_raw = pd.read_csv('data/congressional_trades_house.csv')
print(f"Raw rows: {len(df_raw)}")

# Parse dates
df_raw['disclosure_dt'] = pd.to_datetime(df_raw['disclosure_date'], format='%m/%d/%Y', errors='coerce')
df_raw['transaction_dt'] = pd.to_datetime(df_raw['transaction_date'], errors='coerce')

# Filter reasonable dates
mask = (
    df_raw['transaction_dt'].notna() &
    df_raw['disclosure_dt'].notna() &
    (df_raw['transaction_dt'] >= '2018-01-01') &
    (df_raw['transaction_dt'] <= '2023-12-31')
)
df = df_raw[mask].copy()
print(f"After date filter: {len(df)}")

# Classify trade direction
def classify_trade(t):
    t = str(t).lower()
    if 'purchase' in t:
        return 'buy'
    elif 'sale' in t:
        return 'sell'
    elif 'exchange' in t:
        return 'exchange'
    return 'other'

df['direction'] = df['type'].apply(classify_trade)
print(f"\nTrade direction counts:")
print(df['direction'].value_counts())

# Parse amount ranges to midpoint
def parse_amount(s):
    """Parse amount string like '$1,001 - $15,000' to midpoint."""
    s = str(s).replace('$', '').replace(',', '').strip()
    if ' - ' in s:
        parts = s.split(' - ')
        try:
            lo = float(parts[0])
            hi = float(parts[1])
            return (lo + hi) / 2
        except (ValueError, IndexError):
            return np.nan
    elif '+' in s:
        # e.g., "$1,000,000 +"
        try:
            return float(s.replace('+', '').strip()) * 1.5  # conservative estimate
        except ValueError:
            return np.nan
    else:
        try:
            return float(s)
        except ValueError:
            return np.nan

df['amount_mid'] = df['amount'].apply(parse_amount)
print(f"\nAmount parsed OK: {df['amount_mid'].notna().sum()}/{len(df)}")
print(f"Amount stats:\n{df['amount_mid'].describe()}")

# Disclosure lag statistics
df['disclosure_lag'] = (df['disclosure_dt'] - df['transaction_dt']).dt.days
print(f"\nDisclosure lag (days):")
print(f"  Mean: {df['disclosure_lag'].mean():.1f}")
print(f"  Median: {df['disclosure_lag'].median():.1f}")
print(f"  P75: {df['disclosure_lag'].quantile(0.75):.1f}")
print(f"  P95: {df['disclosure_lag'].quantile(0.95):.1f}")

RESULTS['data_summary'] = {
    'total_trades': int(len(df)),
    'buy_count': int((df['direction'] == 'buy').sum()),
    'sell_count': int((df['direction'] == 'sell').sum()),
    'unique_tickers': int(df['ticker'].nunique()),
    'unique_representatives': int(df['representative'].nunique()),
    'transaction_date_range': [str(df['transaction_dt'].min().date()), str(df['transaction_dt'].max().date())],
    'disclosure_date_range': [str(df['disclosure_dt'].min().date()), str(df['disclosure_dt'].max().date())],
    'median_disclosure_lag_days': float(df['disclosure_lag'].median()),
    'mean_amount_usd': float(df['amount_mid'].mean()),
}

# ============================================================
# 2. Build aggregate daily signals (using disclosure_date)
# ============================================================
print("\n" + "=" * 60)
print("Step 2: Building aggregate daily signals")
print("=" * 60)

# --- Signal A: Count-based net flow (on disclosure_date) ---
# Group by disclosure_date, count buys and sells
buys_by_disc = df[df['direction'] == 'buy'].groupby('disclosure_dt').size().rename('buy_count')
sells_by_disc = df[df['direction'] == 'sell'].groupby('disclosure_dt').size().rename('sell_count')

daily = pd.DataFrame(index=pd.date_range('2019-01-01', '2023-06-30', freq='B'))
daily = daily.join(buys_by_disc).join(sells_by_disc)
daily = daily.fillna(0)
daily['net_count'] = daily['buy_count'] - daily['sell_count']

# --- Signal B: Dollar-weighted net flow (on disclosure_date) ---
buy_vol = df[df['direction'] == 'buy'].groupby('disclosure_dt')['amount_mid'].sum().rename('buy_volume')
sell_vol = df[df['direction'] == 'sell'].groupby('disclosure_dt')['amount_mid'].sum().rename('sell_volume')
daily = daily.join(buy_vol).join(sell_vol)
daily[['buy_volume', 'sell_volume']] = daily[['buy_volume', 'sell_volume']].fillna(0)
daily['net_volume'] = daily['buy_volume'] - daily['sell_volume']

# --- Signal C: Using transaction_date (for comparison) ---
buys_tx = df[df['direction'] == 'buy'].groupby('transaction_dt').size().rename('buy_count_tx')
sells_tx = df[df['direction'] == 'sell'].groupby('transaction_dt').size().rename('sell_count_tx')
daily = daily.join(buys_tx).join(sells_tx)
daily[['buy_count_tx', 'sell_count_tx']] = daily[['buy_count_tx', 'sell_count_tx']].fillna(0)
daily['net_count_tx'] = daily['buy_count_tx'] - daily['sell_count_tx']

# Rolling smoothing
for window in [5, 21]:
    daily[f'net_count_roll{window}'] = daily['net_count'].rolling(window, min_periods=1).mean()
    daily[f'net_volume_roll{window}'] = daily['net_volume'].rolling(window, min_periods=1).mean()
    daily[f'net_count_tx_roll{window}'] = daily['net_count_tx'].rolling(window, min_periods=1).mean()

# Cumulative z-score signal
daily['cum_net'] = daily['net_count'].cumsum()
roll_mean = daily['cum_net'].rolling(63, min_periods=21).mean()
roll_std = daily['cum_net'].rolling(63, min_periods=21).std()
daily['cum_net_zscore'] = (daily['cum_net'] - roll_mean) / roll_std.replace(0, np.nan)

print(f"Daily signal rows: {len(daily)}")
print(f"Days with trades (disclosure): {(daily['buy_count'] + daily['sell_count'] > 0).sum()}")
print(f"Days with no trades: {(daily['buy_count'] + daily['sell_count'] == 0).sum()}")

# ============================================================
# 3. Load SPY data
# ============================================================
print("\n" + "=" * 60)
print("Step 3: Loading SPY data")
print("=" * 60)

spy = yf.download('SPY', start='2019-01-01', end='2023-07-01', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.droplevel(1)
spy.index = spy.index.tz_localize(None)
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = spy['ret'].abs()
spy['ret_sq'] = spy['ret'] ** 2
spy['rv5'] = spy['ret_sq'].rolling(5).mean()
spy['rv21'] = spy['ret_sq'].rolling(21).mean()

print(f"SPY rows: {len(spy)}")
print(f"SPY date range: {spy.index[0].date()} to {spy.index[-1].date()}")

# Merge signals with SPY
merged = spy[['ret', 'abs_ret', 'ret_sq', 'rv5', 'rv21', 'Close']].join(daily, how='inner')
print(f"Merged rows: {len(merged)}")

# ============================================================
# 4. Apply signal lag (CRITICAL: prevent lookahead)
# ============================================================
print("\n" + "=" * 60)
print("Step 4: Applying signal lag (shift 1)")
print("=" * 60)

signal_cols = [
    'net_count', 'net_volume',
    'net_count_roll5', 'net_count_roll21',
    'net_volume_roll5', 'net_volume_roll21',
    'net_count_tx', 'net_count_tx_roll5', 'net_count_tx_roll21',
    'cum_net_zscore',
]

for col in signal_cols:
    merged[f'{col}_lag1'] = merged[col].shift(1)  # signal.shift(1) prevents lookahead

# Drop NaN rows from shifting and rolling
merged = merged.dropna(subset=['ret', 'net_count_lag1', 'rv5'])
print(f"After dropna: {len(merged)} rows")

# ============================================================
# 5. Descriptive statistics
# ============================================================
print("\n" + "=" * 60)
print("Step 5: Descriptive statistics")
print("=" * 60)

print("\n--- SPY return stats ---")
print(f"  Mean daily return: {merged['ret'].mean():.6f}")
print(f"  Std daily return:  {merged['ret'].std():.6f}")
print(f"  Skewness:          {merged['ret'].skew():.4f}")
print(f"  Kurtosis:          {merged['ret'].kurtosis():.4f}")
print(f"  N obs:             {len(merged)}")

print("\n--- Signal stats (lagged) ---")
for col in ['net_count_lag1', 'net_volume_lag1', 'net_count_roll5_lag1',
            'net_count_roll21_lag1', 'cum_net_zscore_lag1']:
    s = merged[col].dropna()
    print(f"  {col}: mean={s.mean():.4f}, std={s.std():.4f}, "
          f"min={s.min():.2f}, max={s.max():.2f}")

# ============================================================
# 6. Correlation analysis
# ============================================================
print("\n" + "=" * 60)
print("Step 6: Correlation analysis")
print("=" * 60)

corr_results = {}
for sig in ['net_count_lag1', 'net_volume_lag1', 'net_count_roll5_lag1',
            'net_count_roll21_lag1', 'cum_net_zscore_lag1',
            'net_count_tx_lag1', 'net_count_tx_roll5_lag1']:
    for target in ['ret', 'abs_ret', 'ret_sq']:
        sub = merged[[sig, target]].dropna()
        r_pearson, p_pearson = stats.pearsonr(sub[sig], sub[target])
        r_spearman, p_spearman = stats.spearmanr(sub[sig], sub[target])
        key = f"{sig}_vs_{target}"
        corr_results[key] = {
            'pearson_r': float(r_pearson),
            'pearson_p': float(p_pearson),
            'spearman_r': float(r_spearman),
            'spearman_p': float(p_spearman),
            'n': int(len(sub)),
        }
        if p_pearson < 0.1 or p_spearman < 0.1:
            flag = " ***" if min(p_pearson, p_spearman) < 0.01 else " **" if min(p_pearson, p_spearman) < 0.05 else " *"
        else:
            flag = ""
        print(f"  {sig:35s} vs {target:8s}: Pearson r={r_pearson:+.4f} (p={p_pearson:.4f}), "
              f"Spearman r={r_spearman:+.4f} (p={p_spearman:.4f}){flag}")

RESULTS['correlations'] = corr_results

# ============================================================
# 7. Granger causality tests
# ============================================================
print("\n" + "=" * 60)
print("Step 7: Granger causality tests")
print("=" * 60)

granger_results = {}
for sig_col in ['net_count', 'net_count_roll5', 'net_volume', 'cum_net_zscore',
                'net_count_tx', 'net_count_tx_roll5']:
    for target_col in ['ret', 'abs_ret', 'ret_sq']:
        sub = merged[[target_col, sig_col]].dropna()
        if len(sub) < 50:
            continue
        try:
            gc = grangercausalitytests(sub, maxlag=5, verbose=False)
            gc_pvals = {}
            for lag in range(1, 6):
                f_stat = gc[lag][0]['ssr_ftest'][0]
                f_pval = gc[lag][0]['ssr_ftest'][1]
                gc_pvals[f'lag{lag}'] = {'F': float(f_stat), 'p': float(f_pval)}
            key = f"{sig_col}_causes_{target_col}"
            granger_results[key] = gc_pvals
            # Report
            min_p = min(gc_pvals[k]['p'] for k in gc_pvals)
            best_lag = min(gc_pvals, key=lambda k: gc_pvals[k]['p'])
            flag = " ***" if min_p < 0.01 else " **" if min_p < 0.05 else " *" if min_p < 0.10 else ""
            print(f"  {sig_col:25s} -> {target_col:8s}: best lag={best_lag}, "
                  f"F={gc_pvals[best_lag]['F']:.3f}, p={gc_pvals[best_lag]['p']:.4f}{flag}")
        except Exception as e:
            print(f"  {sig_col:25s} -> {target_col:8s}: ERROR {e}")

RESULTS['granger_causality'] = granger_results

# ============================================================
# 8. Predictive regressions (Newey-West HAC)
# ============================================================
print("\n" + "=" * 60)
print("Step 8: Predictive regressions (HAC standard errors)")
print("=" * 60)

regression_results = {}

# A. Return prediction: r_{t} = a + b * signal_{t-1} + e
print("\n--- Return prediction ---")
for sig in ['net_count_roll5_lag1', 'net_count_roll21_lag1', 'net_volume_roll5_lag1',
            'cum_net_zscore_lag1', 'net_count_tx_roll5_lag1']:
    sub = merged[['ret', sig]].dropna()
    y = sub['ret'].values
    X = add_constant(sub[sig].values)
    try:
        model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
        b = model.params[1]
        t = model.tvalues[1]
        p = model.pvalues[1]
        r2 = model.rsquared
        flag = " ***" if abs(t) > 3.0 else " **" if p < 0.05 else " *" if p < 0.10 else ""
        print(f"  {sig:35s}: b={b:+.6f}, t={t:+.3f}, p={p:.4f}, R2={r2:.6f}{flag}")
        regression_results[f'ret_on_{sig}'] = {
            'beta': float(b), 't_stat': float(t), 'p_value': float(p),
            'r_squared': float(r2), 'n': int(len(sub)),
            'passes_harvey_threshold': bool(abs(t) > 3.0),
        }
    except Exception as e:
        print(f"  {sig:35s}: ERROR {e}")

# B. Volatility prediction: |r_t| = a + b * signal_{t-1} + e
print("\n--- Volatility prediction (|r|) ---")
for sig in ['net_count_roll5_lag1', 'net_count_roll21_lag1', 'net_volume_roll5_lag1',
            'cum_net_zscore_lag1', 'net_count_tx_roll5_lag1']:
    sub = merged[['abs_ret', sig]].dropna()
    y = sub['abs_ret'].values
    X = add_constant(sub[sig].values)
    try:
        model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
        b = model.params[1]
        t = model.tvalues[1]
        p = model.pvalues[1]
        r2 = model.rsquared
        flag = " ***" if abs(t) > 3.0 else " **" if p < 0.05 else " *" if p < 0.10 else ""
        print(f"  {sig:35s}: b={b:+.6f}, t={t:+.3f}, p={p:.4f}, R2={r2:.6f}{flag}")
        regression_results[f'abs_ret_on_{sig}'] = {
            'beta': float(b), 't_stat': float(t), 'p_value': float(p),
            'r_squared': float(r2), 'n': int(len(sub)),
            'passes_harvey_threshold': bool(abs(t) > 3.0),
        }
    except Exception as e:
        print(f"  {sig:35s}: ERROR {e}")

# C. Squared return prediction: r^2_t = a + b * signal_{t-1} + e
print("\n--- Volatility prediction (r^2) ---")
for sig in ['net_count_roll5_lag1', 'net_count_roll21_lag1', 'net_volume_roll5_lag1',
            'cum_net_zscore_lag1', 'net_count_tx_roll5_lag1']:
    sub = merged[['ret_sq', sig]].dropna()
    y = sub['ret_sq'].values
    X = add_constant(sub[sig].values)
    try:
        model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
        b = model.params[1]
        t = model.tvalues[1]
        p = model.pvalues[1]
        r2 = model.rsquared
        flag = " ***" if abs(t) > 3.0 else " **" if p < 0.05 else " *" if p < 0.10 else ""
        print(f"  {sig:35s}: b={b:+.6f}, t={t:+.3f}, p={p:.4f}, R2={r2:.6f}{flag}")
        regression_results[f'ret_sq_on_{sig}'] = {
            'beta': float(b), 't_stat': float(t), 'p_value': float(p),
            'r_squared': float(r2), 'n': int(len(sub)),
            'passes_harvey_threshold': bool(abs(t) > 3.0),
        }
    except Exception as e:
        print(f"  {sig:35s}: ERROR {e}")

RESULTS['regressions'] = regression_results

# ============================================================
# 9. Direction accuracy analysis
# ============================================================
print("\n" + "=" * 60)
print("Step 9: Direction accuracy (sign agreement)")
print("=" * 60)

direction_results = {}
for sig in ['net_count_roll5_lag1', 'net_count_roll21_lag1', 'cum_net_zscore_lag1',
            'net_count_tx_roll5_lag1']:
    sub = merged[['ret', sig]].dropna()
    # Exclude zero-signal days
    mask = sub[sig] != 0
    sub2 = sub[mask]
    if len(sub2) < 30:
        continue
    correct = (np.sign(sub2[sig]) == np.sign(sub2['ret'])).mean()
    n = len(sub2)
    # Binomial test: is accuracy > 50%?
    k = int(correct * n)
    binom_p = stats.binomtest(k, n, 0.5).pvalue
    print(f"  {sig:35s}: accuracy={correct:.4f} ({k}/{n}), binom p={binom_p:.4f}")
    direction_results[sig] = {
        'accuracy': float(correct),
        'correct': int(k),
        'total': int(n),
        'binom_p': float(binom_p),
    }

RESULTS['direction_accuracy'] = direction_results

# ============================================================
# 10. Conditional return analysis (high buy vs high sell periods)
# ============================================================
print("\n" + "=" * 60)
print("Step 10: Conditional return analysis")
print("=" * 60)

conditional_results = {}

# Quintile analysis based on net_count_roll21_lag1
sig_col = 'net_count_roll21_lag1'
sub = merged[['ret', 'abs_ret', sig_col]].dropna()
sub['quintile'] = pd.qcut(sub[sig_col], 5, labels=False, duplicates='drop')

print(f"\n--- Quintile analysis on {sig_col} ---")
q_stats = sub.groupby('quintile').agg(
    mean_ret=('ret', 'mean'),
    std_ret=('ret', 'std'),
    mean_vol=('abs_ret', 'mean'),
    n=('ret', 'count'),
).reset_index()

for _, row in q_stats.iterrows():
    sharpe_ann = row['mean_ret'] / row['std_ret'] * np.sqrt(252)
    print(f"  Q{int(row['quintile'])}: mean_ret={row['mean_ret']*252*100:.2f}%/yr, "
          f"vol={row['std_ret']*np.sqrt(252)*100:.1f}%, "
          f"Sharpe={sharpe_ann:.3f}, n={int(row['n'])}")

# T-test: top quintile (high net buy) vs bottom quintile (high net sell)
q_top = sub[sub['quintile'] == sub['quintile'].max()]['ret']
q_bot = sub[sub['quintile'] == sub['quintile'].min()]['ret']
t_stat, t_pval = stats.ttest_ind(q_top, q_bot, equal_var=False)
print(f"\n  Top vs Bottom quintile: t={t_stat:.3f}, p={t_pval:.4f}")
print(f"  Top mean: {q_top.mean()*252*100:.2f}%/yr, Bottom mean: {q_bot.mean()*252*100:.2f}%/yr")

conditional_results['quintile_analysis'] = {
    'signal': sig_col,
    'quintile_stats': q_stats.to_dict(orient='records'),
    'top_vs_bottom_t': float(t_stat),
    'top_vs_bottom_p': float(t_pval),
    'top_ann_ret_pct': float(q_top.mean() * 252 * 100),
    'bottom_ann_ret_pct': float(q_bot.mean() * 252 * 100),
}

# Also test: high net buy (>0 21d avg) vs high net sell (<0 21d avg)
pos_ret = sub[sub[sig_col] > 0]['ret']
neg_ret = sub[sub[sig_col] < 0]['ret']
if len(pos_ret) > 30 and len(neg_ret) > 30:
    t2, p2 = stats.ttest_ind(pos_ret, neg_ret, equal_var=False)
    print(f"\n  Net buy (>0) vs Net sell (<0): t={t2:.3f}, p={p2:.4f}")
    print(f"  Net buy mean: {pos_ret.mean()*252*100:.2f}%/yr (n={len(pos_ret)})")
    print(f"  Net sell mean: {neg_ret.mean()*252*100:.2f}%/yr (n={len(neg_ret)})")
    conditional_results['buy_vs_sell'] = {
        'signal': sig_col,
        'buy_ann_ret_pct': float(pos_ret.mean() * 252 * 100),
        'sell_ann_ret_pct': float(neg_ret.mean() * 252 * 100),
        'buy_n': int(len(pos_ret)),
        'sell_n': int(len(neg_ret)),
        't_stat': float(t2),
        'p_value': float(p2),
    }

RESULTS['conditional_returns'] = conditional_results

# ============================================================
# 11. COVID period analysis (March 2020)
# ============================================================
print("\n" + "=" * 60)
print("Step 11: COVID period analysis (2020-02 to 2020-04)")
print("=" * 60)

covid_mask = (merged.index >= '2020-02-01') & (merged.index <= '2020-04-30')
covid = merged[covid_mask]
print(f"COVID period rows: {len(covid)}")
if len(covid) > 20:
    # Did congressional net flow anticipate the crash?
    pre_crash = merged[(merged.index >= '2020-01-15') & (merged.index < '2020-02-20')]
    crash = merged[(merged.index >= '2020-02-20') & (merged.index <= '2020-03-23')]
    post_crash = merged[(merged.index >= '2020-03-24') & (merged.index <= '2020-05-01')]

    for period_name, period_data in [('Pre-crash', pre_crash), ('Crash', crash), ('Post-crash', post_crash)]:
        if len(period_data) > 0:
            net = period_data['net_count'].mean()
            ret = period_data['ret'].mean() * 252 * 100
            vol = period_data['abs_ret'].mean() * np.sqrt(252) * 100
            print(f"  {period_name:12s}: net_count={net:+.2f}, ret={ret:+.1f}%/yr, vol={vol:.1f}%")

    RESULTS['covid_analysis'] = {
        'pre_crash_net_flow': float(pre_crash['net_count'].mean()) if len(pre_crash) > 0 else None,
        'crash_net_flow': float(crash['net_count'].mean()) if len(crash) > 0 else None,
        'post_crash_net_flow': float(post_crash['net_count'].mean()) if len(post_crash) > 0 else None,
    }

# ============================================================
# 12. OOS prediction (expanding window)
# ============================================================
print("\n" + "=" * 60)
print("Step 12: OOS prediction (expanding window)")
print("=" * 60)

# Use first 252 days as initial IS, then expand
sig_col = 'net_count_roll21_lag1'
sub = merged[['ret', 'abs_ret', sig_col]].dropna()

init_window = 252
if len(sub) > init_window + 50:
    oos_preds_ret = []
    oos_actual_ret = []
    oos_preds_vol = []
    oos_actual_vol = []
    oos_dates = []

    for t in range(init_window, len(sub)):
        train = sub.iloc[:t]
        test_row = sub.iloc[t]

        # Return prediction
        y_train = train['ret'].values
        X_train = add_constant(train[sig_col].values)
        try:
            model_ret = OLS(y_train, X_train).fit()
            x_test = np.array([1.0, test_row[sig_col]])
            pred_ret = model_ret.predict(x_test)[0]
            oos_preds_ret.append(pred_ret)
            oos_actual_ret.append(test_row['ret'])
        except:
            continue

        # Volatility prediction (abs_ret)
        y_train_vol = train['abs_ret'].values
        try:
            model_vol = OLS(y_train_vol, X_train).fit()
            pred_vol = model_vol.predict(x_test)[0]
            oos_preds_vol.append(pred_vol)
            oos_actual_vol.append(test_row['abs_ret'])
        except:
            pass

        oos_dates.append(sub.index[t])

    oos_preds_ret = np.array(oos_preds_ret)
    oos_actual_ret = np.array(oos_actual_ret)
    oos_preds_vol = np.array(oos_preds_vol)
    oos_actual_vol = np.array(oos_actual_vol)

    # OOS R^2 for return
    ss_res = np.sum((oos_actual_ret - oos_preds_ret) ** 2)
    ss_tot = np.sum((oos_actual_ret - oos_actual_ret.mean()) ** 2)
    oos_r2_ret = 1 - ss_res / ss_tot

    # OOS R^2 for vol
    if len(oos_preds_vol) > 0:
        ss_res_vol = np.sum((oos_actual_vol - oos_preds_vol) ** 2)
        ss_tot_vol = np.sum((oos_actual_vol - oos_actual_vol.mean()) ** 2)
        oos_r2_vol = 1 - ss_res_vol / ss_tot_vol
    else:
        oos_r2_vol = np.nan

    # Direction accuracy OOS
    oos_dir_acc = (np.sign(oos_preds_ret) == np.sign(oos_actual_ret)).mean()

    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}")
    print(f"  OOS N: {len(oos_preds_ret)}")
    print(f"  OOS R2 (return): {oos_r2_ret:.6f}")
    print(f"  OOS R2 (|return|): {oos_r2_vol:.6f}")
    print(f"  OOS direction accuracy: {oos_dir_acc:.4f}")

    RESULTS['oos_prediction'] = {
        'signal': sig_col,
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'oos_n': int(len(oos_preds_ret)),
        'oos_r2_return': float(oos_r2_ret),
        'oos_r2_vol': float(oos_r2_vol),
        'oos_direction_accuracy': float(oos_dir_acc),
    }

# ============================================================
# 13. Simple strategy backtest
# ============================================================
print("\n" + "=" * 60)
print("Step 13: Simple strategy backtest")
print("=" * 60)

# Strategy: when 21d rolling net count (lagged) > 0, go long SPY (weight=1)
#           when <= 0, reduce exposure (weight=0.5)
sig_col = 'net_count_roll21_lag1'
bt = merged[['ret', sig_col]].dropna().copy()

# Signal is already lagged by shift(1) above
bt['weight'] = np.where(bt[sig_col] > 0, 1.0, 0.5)
bt['strat_ret'] = bt['weight'] * bt['ret']
bt['bh_ret'] = bt['ret']

# Performance metrics
def calc_perf(returns, name):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + returns).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    return {
        'name': name,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'n_days': int(len(returns)),
    }

strat_perf = calc_perf(bt['strat_ret'], 'Congressional Signal')
bh_perf = calc_perf(bt['bh_ret'], 'Buy & Hold SPY')

print(f"\n  {'Metric':<20s} {'Congressional':>15s} {'Buy & Hold':>15s}")
print(f"  {'-'*50}")
for k in ['ann_return', 'ann_vol', 'sharpe', 'mdd']:
    v1 = strat_perf[k]
    v2 = bh_perf[k]
    if k in ['ann_return', 'ann_vol', 'mdd']:
        print(f"  {k:<20s} {v1*100:>14.2f}% {v2*100:>14.2f}%")
    else:
        print(f"  {k:<20s} {v1:>15.3f} {v2:>15.3f}")

# DM-like comparison (simplified t-test on return difference)
diff = bt['strat_ret'] - bt['bh_ret']
t_dm, p_dm = stats.ttest_1samp(diff, 0)
print(f"\n  Return diff t-test: t={t_dm:.3f}, p={p_dm:.4f}")

RESULTS['strategy_backtest'] = {
    'congressional_signal': strat_perf,
    'buy_and_hold': bh_perf,
    'diff_t_stat': float(t_dm),
    'diff_p_value': float(p_dm),
}

# ============================================================
# 14. Robustness: transaction_date signal (with lookahead caveat)
# ============================================================
print("\n" + "=" * 60)
print("Step 14: Robustness check — transaction_date signal (lookahead caveat)")
print("=" * 60)

sig_tx = 'net_count_tx_roll5_lag1'
sub_tx = merged[['ret', 'abs_ret', sig_tx]].dropna()
for target in ['ret', 'abs_ret']:
    y = sub_tx[target].values
    X = add_constant(sub_tx[sig_tx].values)
    model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
    b = model.params[1]
    t = model.tvalues[1]
    p = model.pvalues[1]
    print(f"  {sig_tx} -> {target}: b={b:+.6f}, t={t:+.3f}, p={p:.4f}")
    RESULTS.setdefault('robustness_transaction_date', {})[f'{target}'] = {
        'beta': float(b), 't_stat': float(t), 'p_value': float(p),
    }

print("\n  NOTE: transaction_date signals have lookahead bias because investors")
print("  don't know about trades until disclosure. Included for comparison only.")

# ============================================================
# 15. Plots
# ============================================================
print("\n" + "=" * 60)
print("Step 15: Generating plots")
print("=" * 60)

fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

# Panel A: SPY price
ax1 = axes[0]
ax1.plot(merged.index, merged['Close'], color='steelblue', linewidth=0.8)
ax1.set_ylabel('SPY Price ($)')
ax1.set_title('Congressional Trades Net Flow vs SPY (K1042)')
ax1.grid(True, alpha=0.3)

# Panel B: Net flow (21d rolling, disclosure-based)
ax2 = axes[1]
colors = np.where(merged['net_count_roll21'] > 0, 'green', 'red')
ax2.bar(merged.index, merged['net_count_roll21'], color=colors, alpha=0.6, width=1.5)
ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Net Flow (21d MA)')
ax2.set_title('Congressional Net Buy/Sell Flow (Disclosure Date, 21d Rolling)')
ax2.grid(True, alpha=0.3)

# Panel C: SPY daily return
ax3 = axes[2]
ax3.bar(merged.index, merged['ret'] * 100, color='gray', alpha=0.5, width=1.5)
ax3.set_ylabel('SPY Return (%)')
ax3.set_xlabel('Date')
ax3.grid(True, alpha=0.3)

# Format x-axis
for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

plt.tight_layout()
plt.savefig(OUT_DIR / 'k1042_net_flow_vs_spy.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1042_net_flow_vs_spy.png")

# Plot 2: Quintile bar chart
fig2, ax = plt.subplots(figsize=(8, 5))
q_data = pd.DataFrame(conditional_results['quintile_analysis']['quintile_stats'])
q_labels = [f'Q{int(q)}' for q in q_data['quintile']]
ann_rets = [r['mean_ret'] * 252 * 100 for r in conditional_results['quintile_analysis']['quintile_stats']]
bar_colors = ['red' if r < 0 else 'green' for r in ann_rets]
bars = ax.bar(q_labels, ann_rets, color=bar_colors, alpha=0.7)
ax.axhline(0, color='black', linewidth=0.5)
ax.set_ylabel('Annualized Return (%)')
ax.set_xlabel('Congressional Net Flow Quintile (Low=Net Sell, High=Net Buy)')
ax.set_title('SPY Returns by Congressional Net Flow Quintile (K1042)')
ax.grid(True, alpha=0.3, axis='y')

# Add value labels
for bar, val in zip(bars, ann_rets):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=10)

plt.tight_layout()
plt.savefig(OUT_DIR / 'k1042_quintile_returns.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1042_quintile_returns.png")

# ============================================================
# 16. Summary & conclusions
# ============================================================
print("\n" + "=" * 60)
print("Step 16: Summary")
print("=" * 60)

# Count significant results
n_sig_corr = sum(1 for v in corr_results.values() if v['pearson_p'] < 0.05 or v['spearman_p'] < 0.05)
n_sig_granger = sum(1 for v in granger_results.values()
                    if any(vv['p'] < 0.05 for vv in v.values()))
n_sig_reg = sum(1 for v in regression_results.values() if v['p_value'] < 0.05)
n_harvey = sum(1 for v in regression_results.values() if v.get('passes_harvey_threshold', False))

print(f"  Significant correlations (p<0.05): {n_sig_corr}/{len(corr_results)}")
print(f"  Significant Granger (any lag p<0.05): {n_sig_granger}/{len(granger_results)}")
print(f"  Significant regressions (p<0.05): {n_sig_reg}/{len(regression_results)}")
print(f"  Pass Harvey threshold (|t|>3.0): {n_harvey}/{len(regression_results)}")

conclusion = []
if n_harvey > 0:
    conclusion.append("Some signals pass Harvey (2016) threshold — potentially significant.")
elif n_sig_reg > 0:
    conclusion.append("Some signals significant at conventional levels but do NOT pass Harvey (2016) |t|>3.0 threshold.")
else:
    conclusion.append("No significant predictive power detected from congressional trades.")

if oos_r2_ret < 0:
    conclusion.append(f"OOS R2 for return prediction is negative ({oos_r2_ret:.4f}), confirming no real predictive power.")
else:
    conclusion.append(f"OOS R2 for return prediction is positive but tiny ({oos_r2_ret:.6f}).")

conclusion_text = " ".join(conclusion)
print(f"\n  CONCLUSION: {conclusion_text}")

RESULTS['summary'] = {
    'n_significant_correlations': n_sig_corr,
    'n_significant_granger': n_sig_granger,
    'n_significant_regressions': n_sig_reg,
    'n_pass_harvey': n_harvey,
    'conclusion': conclusion_text,
}

RESULTS['experiment_metadata'] = {
    'experiment_id': 'K1042',
    'title': 'Congressional Trades as Volatility/Return Signal',
    'data_source': 'data/congressional_trades_house.csv + yfinance (SPY)',
    'sample_period': '2019-01 to 2023-06',
    'n_trades': int(len(df)),
    'n_trading_days': int(len(merged)),
    'seed': 42,
    'timestamp': datetime.now().isoformat(),
    'references': [
        'Ziobrowski et al. (2004) JFQA 39(4)',
        'Ziobrowski et al. (2011) Business and Politics 13(1)',
        'Eggers & Hainmueller (2014) Journal of Politics 76(2)',
        'Harvey (2016) Journal of Finance — t>3.0 threshold',
    ],
}

# Save results
with open(OUT_DIR / 'k1042_results.json', 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n  Results saved to {OUT_DIR / 'k1042_results.json'}")

print("\n" + "=" * 60)
print("K1042 COMPLETE")
print("=" * 60)
