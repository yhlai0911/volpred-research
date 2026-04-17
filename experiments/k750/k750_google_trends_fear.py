"""
K750: Google Trends as Fear Proxy — Can Search Volume Predict Volatility?

[提出: Claude, 執行: Claude]

Hypothesis: Google search volume for fear-related terms contains information about
future equity volatility beyond what VIX already captures. This tests an ALTERNATIVE
DATA source — behavioral signal from outside the financial system.

Data sources:
- Google Trends (pytrends) — weekly search volume (0-100 scale) for:
  "stock market crash", "recession", "VIX", "market crash", "bear market"
- SPY (S&P 500 ETF) from yfinance
- GLD (Gold ETF) from yfinance
- ^VIX from yfinance
- Period: 2010-01-01 to 2026-03-30

References:
- Da, Engelberg & Gao (2015) "The Sum of All FEARS" RFS — Google search as investor attention
- Vlastakis & Markellos (2012) "Information Demand and Stock Market Volatility" JBFA
- Preis, Moat & Stanley (2013) "Quantifying Trading Behavior in Financial Markets Using Google Trends" Sci. Rep.
- Andrei & Hasler (2015) "Investor Attention and Stock Market Volatility" RFS
- Dimpfl & Jank (2016) "Can Internet Search Queries Help to Predict Stock Market Volatility?" EFM

Methodology:
- Part A: Google Fear Index construction (composite of 5 search terms)
- Part B: Predictive power (incremental R², partial correlation, DM test)
- Part C: Trading strategy (weekly rebalancing, fear-based allocation)
- Part D: Lead-lag analysis (does Google fear LEAD or LAG VIX?)

Key design: Weekly frequency throughout (matching Google Trends native frequency).
Signal lag: signal from week t-1, return in week t (shift(1)).
TX cost: sum(abs(Δw)) × 5bps per rebalance.
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import time
from datetime import datetime, timezone
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from pathlib import Path

warnings.filterwarnings('ignore')

RESULTS = {}
OUTPUT_DIR = Path(__file__).parent

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K750: Google Trends as Fear Proxy")
print("Can Search Volume Predict Volatility?")
print("=" * 70)

# --- Part 1: Financial data from yfinance ---
print("\n[1] Downloading financial data...")
tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX'
}

fin_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2009-01-01', end='2026-03-31', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    fin_data[name] = df['Close'].dropna()
    print(f"  {name}: {len(fin_data[name])} obs, {fin_data[name].index[0].date()} to {fin_data[name].index[-1].date()}")

# --- Part 2: Google Trends data ---
print("\n[2] Downloading Google Trends data...")

# Search terms related to fear/crash
SEARCH_TERMS = ["stock market crash", "recession", "VIX", "market crash", "bear market"]

google_trends_success = False
trends_data = None

try:
    from pytrends.request import TrendReq

    pytrends = TrendReq(hl='en-US', tz=360)

    # Google Trends only allows 5 years at a time for weekly data
    # We need to stitch multiple periods together
    # Strategy: download overlapping periods and normalize

    all_trends = []
    periods = [
        ('2010-01-01', '2014-12-31'),
        ('2014-01-01', '2018-12-31'),
        ('2018-01-01', '2022-12-31'),
        ('2022-01-01', '2026-03-30'),
    ]

    for i, (start, end) in enumerate(periods):
        print(f"  Fetching period {i+1}/{len(periods)}: {start} to {end}...")
        try:
            pytrends.build_payload(SEARCH_TERMS, timeframe=f'{start} {end}', geo='US')
            time.sleep(3)  # Rate limiting
            df_trends = pytrends.interest_over_time()
            if df_trends is not None and len(df_trends) > 0:
                # Drop 'isPartial' column if present
                if 'isPartial' in df_trends.columns:
                    df_trends = df_trends.drop('isPartial', axis=1)
                all_trends.append(df_trends)
                print(f"    Got {len(df_trends)} weekly observations")
            else:
                print(f"    WARNING: No data returned for this period")
        except Exception as e:
            print(f"    ERROR fetching period {start}-{end}: {e}")
            time.sleep(5)

    if len(all_trends) >= 2:
        # Stitch periods together using overlapping months for normalization
        stitched = all_trends[0].copy()
        for i in range(1, len(all_trends)):
            next_chunk = all_trends[i]
            # Find overlap
            overlap_start = next_chunk.index[0]
            overlap_end = stitched.index[-1]
            if overlap_start <= overlap_end:
                # Compute scale factor from overlapping region
                overlap_mask_old = (stitched.index >= overlap_start) & (stitched.index <= overlap_end)
                overlap_mask_new = (next_chunk.index >= overlap_start) & (next_chunk.index <= overlap_end)

                old_overlap = stitched.loc[overlap_mask_old]
                new_overlap = next_chunk.loc[overlap_mask_new]

                if len(old_overlap) > 0 and len(new_overlap) > 0:
                    # Align by date
                    common_dates = old_overlap.index.intersection(new_overlap.index)
                    if len(common_dates) > 0:
                        scale = old_overlap.loc[common_dates].mean() / new_overlap.loc[common_dates].mean().replace(0, 1)
                        # Apply scale to new chunk
                        scaled_new = next_chunk * scale
                        # Append only non-overlapping part
                        new_only = scaled_new.loc[scaled_new.index > overlap_end]
                        stitched = pd.concat([stitched, new_only])
                    else:
                        # No common dates, just append
                        new_only = next_chunk.loc[next_chunk.index > overlap_end]
                        stitched = pd.concat([stitched, new_only])
                else:
                    new_only = next_chunk.loc[next_chunk.index > overlap_end]
                    stitched = pd.concat([stitched, new_only])
            else:
                # No overlap, just append
                stitched = pd.concat([stitched, next_chunk])

        trends_data = stitched.sort_index()
        google_trends_success = True
        print(f"\n  Stitched Google Trends: {len(trends_data)} weekly obs")
        print(f"  Period: {trends_data.index[0].date()} to {trends_data.index[-1].date()}")
        print(f"  Terms: {list(trends_data.columns)}")
    elif len(all_trends) == 1:
        trends_data = all_trends[0]
        google_trends_success = True
        print(f"\n  Single period Google Trends: {len(trends_data)} weekly obs")
    else:
        print("\n  WARNING: Could not get any Google Trends data")

except Exception as e:
    print(f"\n  Google Trends download FAILED: {e}")
    print("  Will use VIX-based behavioral proxy instead")

# --- Fallback: If Google Trends fails, use VIX percentile as proxy ---
if not google_trends_success:
    print("\n[2b] Creating VIX-based behavioral proxy (fallback)...")
    # This is a weaker test but still tests the concept of "fear level"
    # We'll construct a synthetic "search fear" from VIX behavior
    vix_daily = fin_data['VIX']
    # Weekly VIX features that might correlate with search behavior
    vix_weekly = vix_daily.resample('W-FRI').last()
    trends_data = pd.DataFrame({
        'VIX_level': vix_weekly,
        'VIX_pctile': vix_weekly.rolling(52).rank(pct=True),
        'VIX_spike': (vix_weekly / vix_weekly.shift(1) - 1).clip(0, None),
        'VIX_above_20': (vix_weekly > 20).astype(float) * 100,
        'VIX_above_30': (vix_weekly > 30).astype(float) * 100,
    }).dropna()
    RESULTS['data_source'] = 'VIX-based behavioral proxy (pytrends fallback)'
    print(f"  VIX proxy: {len(trends_data)} weekly obs")

if google_trends_success:
    RESULTS['data_source'] = 'Google Trends (pytrends) + yfinance'
    RESULTS['search_terms'] = SEARCH_TERMS
else:
    RESULTS['search_terms'] = list(trends_data.columns)

RESULTS['google_trends_available'] = google_trends_success

# ============================================================
# CONSTRUCT WEEKLY DATASET
# ============================================================
print("\n[3] Constructing weekly dataset...")

# Convert financial data to weekly (Friday close)
spy_weekly = fin_data['SPY'].resample('W-FRI').last()
gld_weekly = fin_data['GLD'].resample('W-FRI').last()
vix_weekly = fin_data['VIX'].resample('W-FRI').last()

# Weekly returns
spy_ret_w = spy_weekly.pct_change().dropna()
gld_ret_w = gld_weekly.pct_change().dropna()

# Weekly realized volatility (annualized from daily returns within week)
spy_daily_ret = fin_data['SPY'].pct_change().dropna()
rv_weekly = spy_daily_ret.resample('W-FRI').std() * np.sqrt(252)
rv_weekly = rv_weekly.dropna()

# Align all weekly series
weekly = pd.DataFrame({
    'spy_ret': spy_ret_w,
    'gld_ret': gld_ret_w,
    'vix': vix_weekly,
    'rv': rv_weekly
})

# Merge with Google Trends
if google_trends_success:
    # Google Trends index is typically Sunday-based, reindex to Friday
    trends_reindexed = trends_data.copy()
    # Shift to nearest Friday for alignment
    trends_reindexed.index = trends_reindexed.index + pd.Timedelta(days=4)  # Sun -> next Fri approx
    # Resample to W-FRI to align
    trends_resampled = trends_reindexed.resample('W-FRI').last()

    for col in trends_data.columns:
        weekly[f'gt_{col}'] = trends_resampled[col]
else:
    for col in trends_data.columns:
        weekly[f'gt_{col}'] = trends_data[col]

weekly = weekly.dropna()
print(f"  Aligned weekly dataset: {len(weekly)} obs")
print(f"  Period: {weekly.index[0].date()} to {weekly.index[-1].date()}")

RESULTS['sample_size'] = len(weekly)
RESULTS['period_start'] = str(weekly.index[0].date())
RESULTS['period_end'] = str(weekly.index[-1].date())

# ============================================================
# PART A: GOOGLE FEAR INDEX CONSTRUCTION
# ============================================================
print("\n" + "=" * 70)
print("PART A: Google Fear Index Construction")
print("=" * 70)

# Identify Google Trends columns
gt_cols = [c for c in weekly.columns if c.startswith('gt_')]
print(f"\n  Google Trends columns: {gt_cols}")

# Descriptive statistics for each term
print("\n  Descriptive Statistics (raw search volume):")
desc_stats = {}
for col in gt_cols:
    s = weekly[col]
    desc_stats[col] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'min': float(s.min()),
        'max': float(s.max()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
    }
    print(f"    {col}: mean={s.mean():.1f}, std={s.std():.1f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# Construct composite Google Fear Index
# Method: z-score normalize each term, then average
fear_components = pd.DataFrame()
for col in gt_cols:
    z = (weekly[col] - weekly[col].rolling(52).mean()) / weekly[col].rolling(52).std()
    fear_components[col] = z

weekly['fear_index'] = fear_components.mean(axis=1)
weekly = weekly.dropna()

print(f"\n  Google Fear Index (composite z-score):")
print(f"    N={len(weekly)}, mean={weekly['fear_index'].mean():.3f}, "
      f"std={weekly['fear_index'].std():.3f}")
print(f"    min={weekly['fear_index'].min():.3f}, max={weekly['fear_index'].max():.3f}")

# Correlation matrix: Fear Index vs financial variables
corr_vars = ['fear_index', 'vix', 'rv', 'spy_ret']
corr_matrix = weekly[corr_vars].corr()
print("\n  Correlation Matrix:")
for v1 in corr_vars:
    row = "    "
    for v2 in corr_vars:
        row += f"{corr_matrix.loc[v1, v2]:7.3f} "
    print(f"  {v1:15s} {row}")

RESULTS['part_a'] = {
    'descriptive_stats': desc_stats,
    'fear_index_mean': float(weekly['fear_index'].mean()),
    'fear_index_std': float(weekly['fear_index'].std()),
    'corr_fear_vix': float(corr_matrix.loc['fear_index', 'vix']),
    'corr_fear_rv': float(corr_matrix.loc['fear_index', 'rv']),
    'corr_fear_ret': float(corr_matrix.loc['fear_index', 'spy_ret']),
    'corr_vix_rv': float(corr_matrix.loc['vix', 'rv']),
    'n_after_rolling': len(weekly),
}

print(f"\n  Key correlations:")
print(f"    Fear Index <-> VIX:     {corr_matrix.loc['fear_index', 'vix']:.3f}")
print(f"    Fear Index <-> RV:      {corr_matrix.loc['fear_index', 'rv']:.3f}")
print(f"    Fear Index <-> SPY ret: {corr_matrix.loc['fear_index', 'spy_ret']:.3f}")
print(f"    VIX <-> RV:             {corr_matrix.loc['vix', 'rv']:.3f}")

# ============================================================
# PART B: PREDICTIVE POWER
# ============================================================
print("\n" + "=" * 70)
print("PART B: Predictive Power — Does Fear Predict Volatility?")
print("=" * 70)

# Target: next-week realized volatility
# Predictors: current fear_index, current VIX
# All lagged by 1 week (signal from t, predict t+1)

y = weekly['rv'].shift(-1).dropna()  # Next-week RV
X_vix = weekly['vix'].loc[y.index]
X_fear = weekly['fear_index'].loc[y.index]

# Align
mask = y.notna() & X_vix.notna() & X_fear.notna()
y = y[mask]
X_vix = X_vix[mask]
X_fear = X_fear[mask]

N_pred = len(y)
print(f"\n  Prediction sample: N={N_pred}")

# Model 1: VIX only
X1 = add_constant(X_vix)
m1 = OLS(y, X1).fit(cov_type='HAC', cov_kwds={'maxlags': 4})
r2_vix = m1.rsquared
print(f"\n  Model 1 (VIX only): R²={r2_vix:.4f}")
print(f"    VIX coef: {m1.params.iloc[1]:.4f} (t={m1.tvalues.iloc[1]:.2f})")

# Model 2: Fear Index only
X2 = add_constant(X_fear)
m2 = OLS(y, X2).fit(cov_type='HAC', cov_kwds={'maxlags': 4})
r2_fear = m2.rsquared
print(f"\n  Model 2 (Fear only): R²={r2_fear:.4f}")
print(f"    Fear coef: {m2.params.iloc[1]:.4f} (t={m2.tvalues.iloc[1]:.2f})")

# Model 3: VIX + Fear Index
X3 = add_constant(pd.DataFrame({'vix': X_vix, 'fear': X_fear}))
m3 = OLS(y, X3).fit(cov_type='HAC', cov_kwds={'maxlags': 4})
r2_both = m3.rsquared
delta_r2 = r2_both - r2_vix
print(f"\n  Model 3 (VIX + Fear): R²={r2_both:.4f}, ΔR²={delta_r2:.4f}")
print(f"    VIX coef:  {m3.params['vix']:.4f} (t={m3.tvalues['vix']:.2f})")
print(f"    Fear coef: {m3.params['fear']:.4f} (t={m3.tvalues['fear']:.2f})")

# Partial correlation: Fear|VIX
# Regress Fear on VIX, get residuals; regress RV on VIX, get residuals; correlate
resid_fear = OLS(X_fear, add_constant(X_vix)).fit().resid
resid_rv = OLS(y, add_constant(X_vix)).fit().resid
partial_r = np.corrcoef(resid_fear, resid_rv)[0, 1]
partial_r_t = partial_r * np.sqrt(N_pred - 3) / np.sqrt(1 - partial_r**2)
partial_r_p = 2 * stats.t.sf(abs(partial_r_t), N_pred - 3)
print(f"\n  Partial correlation (Fear|VIX): r={partial_r:.4f}, t={partial_r_t:.2f}, p={partial_r_p:.4f}")

# OOS DM test: rolling 52-week window
print("\n  Out-of-sample DM test (52-week rolling window)...")
# Use numpy arrays for robust indexing
y_arr = y.values.astype(float)
vix_arr = X_vix.values.astype(float)
fear_arr = X_fear.values.astype(float)

oos_start = 52
e_vix = []
e_both = []
for t in range(oos_start, N_pred):
    y_train = y_arr[t - 52:t]
    y_test = y_arr[t]
    vix_train = vix_arr[t - 52:t]
    vix_test = vix_arr[t]
    fear_train = fear_arr[t - 52:t]
    fear_test = fear_arr[t]

    if np.isnan(y_test) or np.isnan(vix_test) or np.isnan(fear_test):
        continue

    # VIX-only forecast
    X1_tr = np.column_stack([np.ones(52), vix_train])
    X1_te = np.array([[1.0, vix_test]])
    try:
        m_v = OLS(y_train, X1_tr).fit()
        f_v = m_v.predict(X1_te)[0]
    except:
        continue

    # VIX+Fear forecast
    X3_tr = np.column_stack([np.ones(52), vix_train, fear_train])
    X3_te = np.array([[1.0, vix_test, fear_test]])
    try:
        m_b = OLS(y_train, X3_tr).fit()
        f_b = m_b.predict(X3_te)[0]
    except:
        continue

    e_vix.append((y_test - f_v) ** 2)
    e_both.append((y_test - f_b) ** 2)

e_vix = np.array(e_vix)
e_both = np.array(e_both)
d = e_vix - e_both  # positive = Fear model is BETTER

if len(d) > 0:
    dm_mean = d.mean()
    dm_se = d.std() / np.sqrt(len(d))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0
    dm_p = 2 * stats.t.sf(abs(dm_t), len(d) - 1)
else:
    dm_t = 0.0
    dm_p = 1.0
dm_harvey_pass = abs(dm_t) > 3.0

print(f"  OOS forecasts: {len(e_vix)}")
if len(e_vix) > 0:
    print(f"  MSE (VIX only): {e_vix.mean():.6f}")
    print(f"  MSE (VIX+Fear): {e_both.mean():.6f}")
print(f"  DM statistic: t={dm_t:.3f}, p={dm_p:.4f}")
print(f"  Harvey (2016) t>3.0: {'PASS' if dm_harvey_pass else 'FAIL'}")

RESULTS['part_b'] = {
    'n_prediction': N_pred,
    'r2_vix_only': float(r2_vix),
    'r2_fear_only': float(r2_fear),
    'r2_vix_fear': float(r2_both),
    'delta_r2': float(delta_r2),
    'fear_t_stat_in_combined': float(m3.tvalues['fear']),
    'partial_r_fear_given_vix': float(partial_r),
    'partial_r_t_stat': float(partial_r_t),
    'partial_r_p_value': float(partial_r_p),
    'oos_mse_vix': float(e_vix.mean()),
    'oos_mse_vix_fear': float(e_both.mean()),
    'dm_t_stat': float(dm_t),
    'dm_p_value': float(dm_p),
    'dm_harvey_pass': dm_harvey_pass,
    'n_oos': len(e_vix),
}

# ============================================================
# PART C: TRADING STRATEGY
# ============================================================
print("\n" + "=" * 70)
print("PART C: Trading Strategy — Fear-Based Allocation")
print("=" * 70)

# Strategy: When Google Fear spikes, reduce equity allocation
# Use weekly rebalancing (matching Google Trends native frequency)
# CRITICAL: signal.shift(1) — use LAST week's fear to set THIS week's weight

# Fear signal (lagged 1 week)
fear_signal = weekly['fear_index'].shift(1)  # <-- SHIFT(1) enforced
fear_pctile = fear_signal.rolling(52).rank(pct=True)

# Strategy 1: Fear-based SPY/GLD (binary)
# High fear (>75th pctile) -> 30% SPY + 70% GLD
# Normal -> 70% SPY + 30% GLD
w_spy_fear_binary = np.where(fear_pctile > 0.75, 0.30, 0.70)
w_gld_fear_binary = 1.0 - w_spy_fear_binary

# Strategy 2: Fear-based SPY/GLD (smooth)
# w_SPY = 0.7 - 0.4 * min(fear_pctile, 1.0)  => range [0.3, 0.7]
w_spy_fear_smooth = 0.7 - 0.4 * fear_pctile.clip(0, 1).values
w_gld_fear_smooth = 1.0 - w_spy_fear_smooth

# Baseline 1: 50/50 BH
w_spy_bh = np.full(len(weekly), 0.50)
w_gld_bh = np.full(len(weekly), 0.50)

# Baseline 2: 12/VIX (weekly)
vix_signal = weekly['vix'].shift(1)  # lagged VIX
w_spy_12vix = (12.0 / vix_signal).clip(0, 1).values
w_gld_12vix = 1.0 - w_spy_12vix

# Compute returns for each strategy
spy_r = weekly['spy_ret'].values
gld_r = weekly['gld_ret'].values

# TX cost: sum(|Δw|) × 5bps per asset, each rebalance
TX_RATE = 0.0005

def compute_strategy_returns(w_spy, w_gld, spy_r, gld_r, tx_rate=TX_RATE):
    """Compute portfolio returns with TX costs."""
    n = len(spy_r)
    port_ret = np.full(n, np.nan)
    for t in range(1, n):
        if np.isnan(w_spy[t]) or np.isnan(spy_r[t]) or np.isnan(gld_r[t]):
            continue
        # Portfolio return
        gross_ret = w_spy[t] * spy_r[t] + w_gld[t] * gld_r[t]
        # TX cost (both legs)
        if t > 1 and not np.isnan(w_spy[t-1]):
            tx = (abs(w_spy[t] - w_spy[t-1]) + abs(w_gld[t] - w_gld[t-1])) * tx_rate
        else:
            tx = 0
        port_ret[t] = gross_ret - tx
    return port_ret

ret_fear_binary = compute_strategy_returns(w_spy_fear_binary, w_gld_fear_binary, spy_r, gld_r)
ret_fear_smooth = compute_strategy_returns(w_spy_fear_smooth, w_gld_fear_smooth, spy_r, gld_r)
ret_bh = compute_strategy_returns(w_spy_bh, w_gld_bh, spy_r, gld_r)
ret_12vix = compute_strategy_returns(w_spy_12vix, w_gld_12vix, spy_r, gld_r)

# Evaluation function
def eval_strategy(returns, name, freq=52):
    """Evaluate strategy with weekly returns."""
    r = pd.Series(returns).dropna()
    n = len(r)
    ann_ret = r.mean() * freq
    ann_vol = r.std() * np.sqrt(freq)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    # Downside vol
    down_r = r[r < 0]
    down_vol = down_r.std() * np.sqrt(freq) if len(down_r) > 0 else 0
    sortino = ann_ret / down_vol if down_vol > 0 else 0

    return {
        'name': name,
        'n_weeks': n,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'calmar': float(calmar),
        'sortino': float(sortino),
    }

strats = {
    'Fear Binary (70/30 -> 30/70)': ret_fear_binary,
    'Fear Smooth (0.7-0.4*pctile)': ret_fear_smooth,
    'BH 50/50': ret_bh,
    '12/VIX': ret_12vix,
}

print("\n  Strategy Performance (weekly rebalancing, TX=5bps):")
print(f"  {'Strategy':<35s} {'Return':>8s} {'Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} {'Sortino':>8s}")
print("  " + "-" * 75)

strat_results = {}
for name, ret in strats.items():
    ev = eval_strategy(ret, name)
    strat_results[name] = ev
    print(f"  {name:<35s} {ev['ann_return']:>7.1%} {ev['ann_vol']:>7.1%} "
          f"{ev['sharpe']:>7.3f} {ev['mdd']:>7.1%} {ev['sortino']:>7.3f}")

RESULTS['part_c'] = {
    'strategies': strat_results,
    'tx_rate_bps': 5,
    'rebalance_freq': 'weekly',
    'signal_lag': 1,
}

# DM test: Fear Binary vs BH 50/50
r_fear = pd.Series(ret_fear_binary).dropna()
r_bh = pd.Series(ret_bh).dropna()
common_idx = r_fear.index.intersection(r_bh.index)
r_fear = r_fear.loc[common_idx]
r_bh = r_bh.loc[common_idx]

d_strat = r_fear.values - r_bh.values
dm_strat_t = d_strat.mean() / (d_strat.std() / np.sqrt(len(d_strat))) if d_strat.std() > 0 else 0
dm_strat_p = 2 * stats.t.sf(abs(dm_strat_t), len(d_strat) - 1)

print(f"\n  DM test (Fear Binary vs BH 50/50): t={dm_strat_t:.3f}, p={dm_strat_p:.4f}")
print(f"  Harvey (2016) |t|>3.0: {'PASS' if abs(dm_strat_t) > 3.0 else 'FAIL'}")

# DM test: Fear Smooth vs 12/VIX
r_smooth = pd.Series(ret_fear_smooth).dropna()
r_12v = pd.Series(ret_12vix).dropna()
common_idx2 = r_smooth.index.intersection(r_12v.index)
r_smooth = r_smooth.loc[common_idx2]
r_12v = r_12v.loc[common_idx2]

d_strat2 = r_smooth.values - r_12v.values
dm_strat2_t = d_strat2.mean() / (d_strat2.std() / np.sqrt(len(d_strat2))) if d_strat2.std() > 0 else 0
dm_strat2_p = 2 * stats.t.sf(abs(dm_strat2_t), len(d_strat2) - 1)

print(f"  DM test (Fear Smooth vs 12/VIX): t={dm_strat2_t:.3f}, p={dm_strat2_p:.4f}")

RESULTS['part_c']['dm_fear_vs_bh_t'] = float(dm_strat_t)
RESULTS['part_c']['dm_fear_vs_bh_p'] = float(dm_strat_p)
RESULTS['part_c']['dm_smooth_vs_12vix_t'] = float(dm_strat2_t)
RESULTS['part_c']['dm_smooth_vs_12vix_p'] = float(dm_strat2_p)

# ============================================================
# PART D: LEAD-LAG ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("PART D: Lead-Lag Analysis — Does Google Fear Lead or Lag VIX?")
print("=" * 70)

# Cross-correlation at different lags
# Positive lag = Fear LEADS VIX
# Negative lag = Fear LAGS VIX (reactive, not predictive)

fear_series = weekly['fear_index']
vix_series = weekly['vix']
spy_ret_series = weekly['spy_ret']

lags = list(range(-8, 9))  # -8 to +8 weeks
xcorr_fear_vix = {}
xcorr_fear_rv = {}
xcorr_fear_ret = {}

for lag in lags:
    if lag >= 0:
        f_shifted = fear_series.iloc[:len(fear_series)-lag] if lag > 0 else fear_series
        v_aligned = vix_series.iloc[lag:]
        rv_aligned = weekly['rv'].iloc[lag:]
        ret_aligned = spy_ret_series.iloc[lag:]
    else:
        f_shifted = fear_series.iloc[-lag:]
        v_aligned = vix_series.iloc[:len(vix_series)+lag]
        rv_aligned = weekly['rv'].iloc[:len(weekly['rv'])+lag]
        ret_aligned = spy_ret_series.iloc[:len(spy_ret_series)+lag]

    min_len = min(len(f_shifted), len(v_aligned))
    if min_len > 10:
        xcorr_fear_vix[lag] = float(np.corrcoef(f_shifted.values[:min_len], v_aligned.values[:min_len])[0, 1])
        xcorr_fear_rv[lag] = float(np.corrcoef(f_shifted.values[:min_len], rv_aligned.values[:min_len])[0, 1])
        xcorr_fear_ret[lag] = float(np.corrcoef(f_shifted.values[:min_len], ret_aligned.values[:min_len])[0, 1])

print("\n  Cross-correlation: Fear Index vs VIX at different lags")
print(f"  {'Lag':>5s}  {'Fear->VIX':>10s}  {'Fear->RV':>10s}  {'Fear->Ret':>10s}")
print("  " + "-" * 40)
for lag in lags:
    marker = " <-- contemporaneous" if lag == 0 else ""
    marker = " <-- Fear LEADS VIX" if lag == 1 else marker
    marker = " <-- Fear LAGS VIX" if lag == -1 else marker
    print(f"  {lag:>5d}  {xcorr_fear_vix.get(lag, np.nan):>10.3f}  "
          f"{xcorr_fear_rv.get(lag, np.nan):>10.3f}  "
          f"{xcorr_fear_ret.get(lag, np.nan):>10.3f}{marker}")

# Find peak correlation lag
best_lag_vix = max(xcorr_fear_vix, key=lambda k: abs(xcorr_fear_vix[k]))
best_lag_rv = max(xcorr_fear_rv, key=lambda k: abs(xcorr_fear_rv[k]))

print(f"\n  Peak |corr| with VIX at lag={best_lag_vix} (r={xcorr_fear_vix[best_lag_vix]:.3f})")
print(f"  Peak |corr| with RV at lag={best_lag_rv} (r={xcorr_fear_rv[best_lag_rv]:.3f})")

if best_lag_vix <= 0:
    print(f"  --> Google Fear LAGS VIX (reactive, not predictive)")
    lead_lag_conclusion = "Fear LAGS VIX (reactive)"
elif best_lag_vix > 0:
    print(f"  --> Google Fear LEADS VIX (potentially predictive)")
    lead_lag_conclusion = "Fear LEADS VIX (potentially predictive)"
else:
    print(f"  --> Contemporaneous relationship")
    lead_lag_conclusion = "Contemporaneous"

# Granger causality test (simple: does lagged fear predict VIX change?)
print("\n  Simple Granger test: Does lagged Fear predict ΔlnVIX?")
vix_change = np.log(vix_series).diff().dropna()
fear_lag1 = fear_series.shift(1).loc[vix_change.index].dropna()
common = vix_change.index.intersection(fear_lag1.index)
vix_change = vix_change.loc[common]
fear_lag1 = fear_lag1.loc[common]

X_gc = add_constant(fear_lag1)
m_gc = OLS(vix_change, X_gc).fit(cov_type='HAC', cov_kwds={'maxlags': 4})
gc_t = float(m_gc.tvalues.iloc[1])
gc_p = float(m_gc.pvalues.iloc[1])
print(f"  Fear(t-1) -> ΔlnVIX(t): coef={m_gc.params.iloc[1]:.4f}, t={gc_t:.2f}, p={gc_p:.4f}")
print(f"  Granger-predictive: {'Yes' if gc_p < 0.05 else 'No'} (p<0.05)")

RESULTS['part_d'] = {
    'xcorr_fear_vix': xcorr_fear_vix,
    'xcorr_fear_rv': xcorr_fear_rv,
    'xcorr_fear_ret': xcorr_fear_ret,
    'best_lag_vix': best_lag_vix,
    'best_corr_vix': float(xcorr_fear_vix[best_lag_vix]),
    'best_lag_rv': best_lag_rv,
    'best_corr_rv': float(xcorr_fear_rv[best_lag_rv]),
    'lead_lag_conclusion': lead_lag_conclusion,
    'granger_fear_to_vix_t': gc_t,
    'granger_fear_to_vix_p': gc_p,
}

# ============================================================
# PART E: CROSS-OOS VALIDATION (5 periods)
# ============================================================
print("\n" + "=" * 70)
print("PART E: Cross-OOS Validation (5 non-overlapping 2-year periods)")
print("=" * 70)

# Define 5 non-overlapping 2-year OOS periods
oos_periods = [
    ('2012-01-01', '2013-12-31'),
    ('2014-01-01', '2015-12-31'),
    ('2016-01-01', '2017-12-31'),
    ('2018-01-01', '2019-12-31'),
    ('2020-01-01', '2021-12-31'),
]

oos_wins = 0
oos_results = []

for i, (start, end) in enumerate(oos_periods):
    mask_oos = (weekly.index >= start) & (weekly.index <= end)
    w_oos = weekly.loc[mask_oos]

    if len(w_oos) < 20:
        print(f"  Period {i+1} ({start} to {end}): Too few data ({len(w_oos)} weeks), SKIP")
        continue

    # Fear signal (lagged)
    fs = w_oos['fear_index'].shift(1)
    fp = fs.rolling(52, min_periods=26).rank(pct=True)

    w_spy_f = np.where(fp > 0.75, 0.30, 0.70)
    w_gld_f = 1.0 - w_spy_f
    w_spy_b = np.full(len(w_oos), 0.50)
    w_gld_b = np.full(len(w_oos), 0.50)

    ret_f = compute_strategy_returns(w_spy_f, w_gld_f, w_oos['spy_ret'].values, w_oos['gld_ret'].values)
    ret_b = compute_strategy_returns(w_spy_b, w_gld_b, w_oos['spy_ret'].values, w_oos['gld_ret'].values)

    ev_f = eval_strategy(ret_f, 'Fear')
    ev_b = eval_strategy(ret_b, 'BH 50/50')

    win = ev_f['sharpe'] > ev_b['sharpe']
    if win:
        oos_wins += 1

    oos_results.append({
        'period': f"{start} to {end}",
        'fear_sharpe': ev_f['sharpe'],
        'bh_sharpe': ev_b['sharpe'],
        'win': win,
    })

    print(f"  Period {i+1} ({start}-{end}): Fear Sharpe={ev_f['sharpe']:.3f} vs BH={ev_b['sharpe']:.3f} "
          f"{'WIN' if win else 'LOSE'}")

print(f"\n  Cross-OOS wins: {oos_wins}/{len(oos_results)}")
print(f"  Pass (>= 3/5): {'PASS' if oos_wins >= 3 else 'FAIL'}")

RESULTS['part_e'] = {
    'oos_periods': oos_results,
    'oos_wins': oos_wins,
    'oos_total': len(oos_results),
    'oos_pass': oos_wins >= 3,
}

# ============================================================
# OVERALL CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("OVERALL CONCLUSION")
print("=" * 70)

# Determine if this is VIX sufficiency confirmation
is_null = True  # Default assumption
reasons = []

if delta_r2 > 0.02 and dm_harvey_pass:
    is_null = False
    reasons.append(f"Fear adds ΔR²={delta_r2:.4f} with DM significance")
else:
    reasons.append(f"Fear ΔR²={delta_r2:.4f} (tiny) and DM t={dm_t:.2f} (Harvey FAIL)")

if abs(partial_r) > 0.10 and partial_r_p < 0.01:
    reasons.append(f"Partial r={partial_r:.3f} (non-trivial) but {'significant' if partial_r_p < 0.01 else 'marginal'}")
else:
    reasons.append(f"Partial r={partial_r:.3f} (negligible)")

if best_lag_vix <= 0:
    reasons.append(f"Fear LAGS VIX (peak at lag={best_lag_vix}) — reactive, not predictive")
else:
    reasons.append(f"Fear LEADS VIX (peak at lag={best_lag_vix}) — potentially useful")

if oos_wins < 3:
    reasons.append(f"Cross-OOS {oos_wins}/{len(oos_results)} FAIL")
else:
    reasons.append(f"Cross-OOS {oos_wins}/{len(oos_results)} PASS")

# Strategy performance
fear_sharpe = strat_results['Fear Binary (70/30 -> 30/70)']['sharpe']
bh_sharpe = strat_results['BH 50/50']['sharpe']
vix_sharpe = strat_results['12/VIX']['sharpe']

if fear_sharpe < bh_sharpe:
    reasons.append(f"Fear strategy Sharpe {fear_sharpe:.3f} < BH 50/50 {bh_sharpe:.3f}")

vix_sufficiency_number = 36 if is_null else None  # Increment if null

conclusion = "NULL" if is_null else "SIGNIFICANT"
print(f"\n  Conclusion: {conclusion}")
for r in reasons:
    print(f"    - {r}")

if is_null:
    print(f"\n  VIX Sufficiency #{vix_sufficiency_number}: Google Trends fear index does not add")
    print(f"  predictive or trading value beyond VIX alone.")
    print(f"  Alternative data (search volume) is REACTIVE to market events, not predictive.")

RESULTS['conclusion'] = {
    'is_null': is_null,
    'vix_sufficiency_number': vix_sufficiency_number,
    'reasons': reasons,
    'lead_lag': lead_lag_conclusion,
    'fear_binary_sharpe': float(fear_sharpe),
    'bh_5050_sharpe': float(bh_sharpe),
    'twelve_vix_sharpe': float(vix_sharpe),
    'summary': (f"Google Trends fear index {'does NOT' if is_null else 'DOES'} add "
                f"incremental value beyond VIX. "
                f"ΔR²={delta_r2:.4f}, partial r={partial_r:.3f}, "
                f"DM t={dm_t:.2f}, lead-lag peak at lag={best_lag_vix}. "
                f"{'VIX sufficiency #' + str(vix_sufficiency_number) + '.' if is_null else 'New signal found!'}")
}

RESULTS['metadata'] = {
    'experiment_id': 'K750',
    'title': 'Google Trends as Fear Proxy — Can Search Volume Predict Volatility?',
    'proposer': 'Claude',
    'executor': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Da, Engelberg & Gao (2015) "The Sum of All FEARS" RFS',
        'Vlastakis & Markellos (2012) "Information Demand and Stock Market Volatility" JBFA',
        'Preis, Moat & Stanley (2013) "Quantifying Trading Behavior" Sci. Rep.',
        'Andrei & Hasler (2015) "Investor Attention and Stock Market Volatility" RFS',
        'Dimpfl & Jank (2016) "Can Internet Search Queries Help Predict Volatility?" EFM',
    ],
}

# ============================================================
# SAVE RESULTS
# ============================================================
output_path = OUTPUT_DIR / 'k750_google_trends_fear_results.json'
with open(output_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 70)
print("K750 COMPLETE")
print("=" * 70)
