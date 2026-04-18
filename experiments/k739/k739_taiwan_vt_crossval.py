"""
K739: Taiwan 0050.TW VT Cross-Validation — Do US Findings Hold in Taiwan?
[提出: Claude, 執行: Claude]

Tests whether key US VT findings (K730-K738) generalize to Taiwan:
  Test 1: VIX sufficiency — does lagged US VIX predict 0050 RV better than own-vol?
  Test 2: Optimal 2-asset allocation for Taiwan investors
  Test 3: Calendar anomaly (Sell in May) in Taiwan
  Test 4: Rebalancing frequency (daily vs weekly vs monthly)

Data: yfinance (0050.TW, ^VIX, GLD, SPY, 2670.TW bond ETF proxy)
Period: 2006-01 to 2026-03 (20 years)
TX cost: 10 bps for Taiwan (includes ETF securities transaction tax)

References:
  K82/K88 — Taiwan VT guide (8.63/VIX target)
  K636 — Amplification 4.6x
  K733 — US monthly rebalancing optimal
  K736 — US calendar anomaly (VIX seasonal but return diff insignificant)
  K738 — VT insurance cost-benefit
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# Data Download
# ============================================================
print("=" * 70)
print("K739: Taiwan 0050.TW VT Cross-Validation")
print("=" * 70)

tickers = {
    '0050.TW': '0050.TW',
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX',
}

start_date = '2006-01-01'
end_date = '2026-03-30'

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].rename(name)
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge all data
prices = pd.DataFrame(data)
prices = prices.sort_index()

# Forward-fill for holidays (Taiwan vs US different trading days)
prices = prices.ffill()
prices = prices.dropna()

print(f"\nMerged dataset: {len(prices)} days ({prices.index[0].date()} to {prices.index[-1].date()})")

# Calculate returns
returns = prices.pct_change().dropna()

# Realized volatility (21-day rolling for monthly, annualized)
rv_0050 = returns['0050.TW'].rolling(21).std() * np.sqrt(252)
rv_spy = returns['SPY'].rolling(21).std() * np.sqrt(252)

results = {}

# ============================================================
# TEST 1: VIX Sufficiency for Taiwan
# ============================================================
print("\n" + "=" * 70)
print("TEST 1: VIX Sufficiency for Taiwan 0050.TW")
print("=" * 70)

# Prepare regression data
# RV_0050(t+1 month) = alpha + beta1 * VIX(t-1) + beta2 * own_RV(t) + eps
# Note: VIX lagged 1 day for Taiwan (US closes before Taiwan opens)

reg_data = pd.DataFrame({
    'rv_0050_lead': rv_0050.shift(-21),       # Forward 1 month RV
    'vix_lag1': prices['VIX'].shift(1) / 100,  # VIX as decimal, lagged 1 day
    'own_rv': rv_0050,                         # Own realized vol
    'rv_spy': rv_spy,                          # SPY realized vol (control)
}).dropna()

print(f"Regression sample: {len(reg_data)} observations")
print(f"  Period: {reg_data.index[0].date()} to {reg_data.index[-1].date()}")

# Model 1: VIX only
from numpy.linalg import lstsq

def ols_regression(y, X, var_names):
    """Simple OLS with t-stats and R-squared."""
    X_const = np.column_stack([np.ones(len(X)), X])
    beta, residuals, rank, sv = lstsq(X_const, y, rcond=None)
    y_hat = X_const @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot
    n, k = len(y), X_const.shape[1]
    adj_r2 = 1 - (1 - r2) * (n - 1) / (n - k)
    mse = ss_res / (n - k)
    se = np.sqrt(np.diag(mse * np.linalg.inv(X_const.T @ X_const)))
    t_stats = beta / se
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), n - k))

    result = {
        'r2': r2,
        'adj_r2': adj_r2,
        'n': n,
        'coefficients': {}
    }
    names = ['const'] + var_names
    for i, name in enumerate(names):
        result['coefficients'][name] = {
            'beta': float(beta[i]),
            't_stat': float(t_stats[i]),
            'p_value': float(p_vals[i]),
            'significant_5pct': bool(p_vals[i] < 0.05)
        }
    return result

y = reg_data['rv_0050_lead'].values

# Model 1: VIX only
m1 = ols_regression(y, reg_data[['vix_lag1']].values, ['vix_lag1'])
print(f"\nModel 1 (VIX only): R² = {m1['r2']:.4f}")
for name, c in m1['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

# Model 2: Own RV only
m2 = ols_regression(y, reg_data[['own_rv']].values, ['own_rv'])
print(f"\nModel 2 (Own RV only): R² = {m2['r2']:.4f}")
for name, c in m2['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

# Model 3: VIX + Own RV (horse race)
m3 = ols_regression(y, reg_data[['vix_lag1', 'own_rv']].values, ['vix_lag1', 'own_rv'])
print(f"\nModel 3 (VIX + Own RV): R² = {m3['r2']:.4f}")
for name, c in m3['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

# Correlation test
vix_rv_corr = reg_data['vix_lag1'].corr(reg_data['rv_0050_lead'])
own_rv_corr = reg_data['own_rv'].corr(reg_data['rv_0050_lead'])
print(f"\nCorrelations with future 0050 RV:")
print(f"  VIX(t-1):      {vix_rv_corr:.4f}")
print(f"  Own RV(t):      {own_rv_corr:.4f}")

# R² improvement from adding own_rv to VIX
r2_gain = m3['r2'] - m1['r2']
print(f"\nR² gain from adding own RV to VIX: {r2_gain:.4f} ({r2_gain/m1['r2']*100:.1f}%)")

results['test1_vix_sufficiency'] = {
    'model1_vix_only': {
        'r2': round(m1['r2'], 4),
        'adj_r2': round(m1['adj_r2'], 4),
        'vix_lag1_beta': round(m1['coefficients']['vix_lag1']['beta'], 4),
        'vix_lag1_t': round(m1['coefficients']['vix_lag1']['t_stat'], 2),
        'vix_lag1_sig': m1['coefficients']['vix_lag1']['significant_5pct'],
    },
    'model2_own_rv_only': {
        'r2': round(m2['r2'], 4),
        'adj_r2': round(m2['adj_r2'], 4),
        'own_rv_beta': round(m2['coefficients']['own_rv']['beta'], 4),
        'own_rv_t': round(m2['coefficients']['own_rv']['t_stat'], 2),
        'own_rv_sig': m2['coefficients']['own_rv']['significant_5pct'],
    },
    'model3_combined': {
        'r2': round(m3['r2'], 4),
        'adj_r2': round(m3['adj_r2'], 4),
        'vix_lag1_beta': round(m3['coefficients']['vix_lag1']['beta'], 4),
        'vix_lag1_t': round(m3['coefficients']['vix_lag1']['t_stat'], 2),
        'own_rv_beta': round(m3['coefficients']['own_rv']['beta'], 4),
        'own_rv_t': round(m3['coefficients']['own_rv']['t_stat'], 2),
    },
    'r2_gain_from_own_rv': round(r2_gain, 4),
    'r2_gain_pct': round(r2_gain / m1['r2'] * 100, 1),
    'corr_vix_future_rv': round(vix_rv_corr, 4),
    'corr_own_rv_future_rv': round(own_rv_corr, 4),
    'n_observations': int(m1['n']),
    'conclusion': ''  # filled below
}

if r2_gain < 0.01:
    results['test1_vix_sufficiency']['conclusion'] = 'VIX sufficient — adding own RV provides negligible improvement'
elif m3['coefficients']['own_rv']['significant_5pct']:
    results['test1_vix_sufficiency']['conclusion'] = 'Own RV adds significant incremental info beyond VIX'
else:
    results['test1_vix_sufficiency']['conclusion'] = 'VIX dominant but own RV has some marginal value'


# ============================================================
# TEST 2: Optimal Taiwan 2-Asset Allocation
# ============================================================
print("\n" + "=" * 70)
print("TEST 2: Optimal 2-Asset Allocation for Taiwan Investors")
print("=" * 70)

# Test combinations:
# A) 0050.TW + GLD (gold hedge — universal)
# B) 0050.TW + SPY (diversify into US — international)
# C) 0050.TW + Cash (TWD cash = 0 return proxy)

TX_COST_TW = 0.0010  # 10 bps for Taiwan ETFs

def run_vt_strategy(equity_ret, safe_ret, vix, target_vol, weight_name,
                    tx_cost=TX_COST_TW, rebal='monthly'):
    """
    Run VT strategy: weight = target_vol / VIX, rest in safe asset.
    Uses signal.shift(1) for lag.
    """
    # Weight signal: target_vol / VIX (both in percentage points)
    # e.g., 8.63 / 19 = 0.454 (45.4% equity)
    # VIX is already in percentage points (e.g., 19 means 19%)
    signal = (target_vol / vix).clip(0, 1)
    signal = signal.shift(1)  # MANDATORY: lag 1 day for signal
    # Note: US VIX closes ~13 hours before Taiwan opens next day.
    # By using shift(1) on the merged calendar, we use VIX from
    # US close t-1 to set Taiwan weight on day t — correct lag.

    if rebal == 'monthly':
        # Only rebalance on first trading day of month
        month_change = signal.index.to_series().dt.month.diff().ne(0)
        signal_rebal = signal.copy()
        signal_rebal[~month_change] = np.nan
        signal_rebal = signal_rebal.ffill()
        signal_rebal = signal_rebal.dropna()
    elif rebal == 'weekly':
        # Rebalance on Mondays
        is_monday = signal.index.dayofweek == 0
        signal_rebal = signal.copy()
        signal_rebal[~is_monday] = np.nan
        signal_rebal = signal_rebal.ffill()
        signal_rebal = signal_rebal.dropna()
    else:  # daily
        signal_rebal = signal

    # Align data
    idx = equity_ret.index.intersection(safe_ret.index).intersection(signal_rebal.index)
    eq = equity_ret.loc[idx]
    sf = safe_ret.loc[idx]
    w = signal_rebal.loc[idx]

    # Transaction costs
    w_change = w.diff().abs()
    tx = w_change * tx_cost * 2  # buy + sell

    # Portfolio return
    port_ret = w * eq + (1 - w) * sf - tx
    port_ret = port_ret.dropna()

    # Metrics
    n_years = len(port_ret) / 252
    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + port_ret).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0
    sortino = ann_ret / (port_ret[port_ret < 0].std() * np.sqrt(252)) if len(port_ret[port_ret < 0]) > 0 else 0

    # Annual turnover
    ann_turnover = w_change.sum() / n_years * 100
    tx_drag = tx.sum() / n_years * 100

    return {
        'name': weight_name,
        'ann_ret': round(float(ann_ret) * 100, 2),
        'ann_vol': round(float(ann_vol) * 100, 2),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd) * 100, 2),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'n_days': len(port_ret),
        'n_years': round(n_years, 1),
        'ann_turnover_pct': round(float(ann_turnover), 1),
        'ann_tx_drag_pct': round(float(tx_drag), 3),
    }


def run_bh_strategy(equity_ret, safe_ret, equity_wt, name, tx_cost=TX_COST_TW,
                    rebal='monthly'):
    """Buy-and-hold with fixed weights, monthly rebalance."""
    idx = equity_ret.index.intersection(safe_ret.index)
    eq = equity_ret.loc[idx]
    sf = safe_ret.loc[idx]

    w = pd.Series(equity_wt, index=idx)

    if rebal == 'monthly':
        month_change = w.index.to_series().dt.month.diff().ne(0)
        w_rebal = w.copy()
        w_rebal[~month_change] = np.nan
        w_rebal.iloc[0] = equity_wt
        w_rebal = w_rebal.ffill()
    else:
        w_rebal = w

    w_change = w_rebal.diff().abs().fillna(0)
    tx = w_change * tx_cost * 2

    port_ret = w_rebal * eq + (1 - w_rebal) * sf - tx
    port_ret = port_ret.dropna()

    n_years = len(port_ret) / 252
    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + port_ret).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0
    sortino = ann_ret / (port_ret[port_ret < 0].std() * np.sqrt(252)) if len(port_ret[port_ret < 0]) > 0 else 0

    return {
        'name': name,
        'ann_ret': round(float(ann_ret) * 100, 2),
        'ann_vol': round(float(ann_vol) * 100, 2),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd) * 100, 2),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'n_days': len(port_ret),
        'n_years': round(n_years, 1),
    }


# Returns
ret_0050 = returns['0050.TW']
ret_spy = returns['SPY']
ret_gld = returns['GLD']
ret_cash = pd.Series(0.0, index=returns.index)  # TWD cash proxy (0% return)

vix = prices['VIX']
target_tw = 8.63  # Taiwan target from K82

# Strategies for each combination
combos = {
    '0050+GLD': {
        'equity': ret_0050, 'safe': ret_gld,
        'label': '0050.TW + GLD',
    },
    '0050+SPY': {
        'equity': ret_0050, 'safe': ret_spy,
        'label': '0050.TW + SPY',
    },
    '0050+Cash': {
        'equity': ret_0050, 'safe': ret_cash,
        'label': '0050.TW + Cash (TWD)',
    },
}

# Grid search: weight from 0.1 to 0.9
print("\n--- Grid Search: Optimal Static Weight ---")
grid_results = {}
for combo_key, combo in combos.items():
    best_sharpe = -999
    best_w = 0.5
    for w_pct in range(10, 91, 10):
        w = w_pct / 100
        r = run_bh_strategy(combo['equity'], combo['safe'], w,
                            f"{combo['label']} {w_pct}/{100-w_pct}", rebal='monthly')
        if r['sharpe'] > best_sharpe:
            best_sharpe = r['sharpe']
            best_w = w

    # Run the best and some key weights
    results_combo = {}
    for w_pct in [30, 40, 50, 60, 70, round(best_w * 100)]:
        w = w_pct / 100
        r = run_bh_strategy(combo['equity'], combo['safe'], w,
                            f"BH {w_pct}/{100-w_pct}", rebal='monthly')
        results_combo[f"bh_{w_pct}_{100-w_pct}"] = r

    # VT strategy with 8.63/VIX
    vt_r = run_vt_strategy(combo['equity'], combo['safe'], vix, target_tw,
                           f"VT 8.63/VIX", rebal='monthly')
    results_combo['vt_8.63'] = vt_r

    grid_results[combo_key] = {
        'best_static_weight': round(best_w, 2),
        'best_static_sharpe': round(best_sharpe, 4),
        'strategies': results_combo,
    }

    print(f"\n{combo['label']}:")
    print(f"  Best static: {best_w*100:.0f}% equity → Sharpe {best_sharpe:.4f}")
    print(f"  VT 8.63/VIX: Sharpe {vt_r['sharpe']:.4f}, MDD {vt_r['mdd']:.1f}%")
    for key, r in results_combo.items():
        if key.startswith('bh_50'):
            print(f"  BH 50/50: Sharpe {r['sharpe']:.4f}, MDD {r['mdd']:.1f}%")

results['test2_optimal_allocation'] = grid_results


# ============================================================
# TEST 3: Calendar Anomaly in Taiwan
# ============================================================
print("\n" + "=" * 70)
print("TEST 3: Calendar Anomaly (Sell in May) in Taiwan 0050.TW")
print("=" * 70)

# Monthly returns for 0050.TW
monthly_0050 = ret_0050.resample('ME').apply(lambda x: (1 + x).prod() - 1)

# Average return by month
monthly_avg = {}
monthly_n = {}
for m in range(1, 13):
    mask = monthly_0050.index.month == m
    monthly_avg[m] = float(monthly_0050[mask].mean()) * 100
    monthly_n[m] = int(mask.sum())

print("\n0050.TW Average Monthly Returns (%):")
for m, r in monthly_avg.items():
    bar = '█' * max(0, int(r * 5)) if r > 0 else '░' * max(0, int(-r * 5))
    print(f"  Month {m:2d}: {r:+6.2f}% (N={monthly_n[m]:2d}) {bar}")

# Winter (Nov-Apr) vs Summer (May-Oct) — "Sell in May"
winter_rets = ret_0050[ret_0050.index.month.isin([11, 12, 1, 2, 3, 4])]
summer_rets = ret_0050[ret_0050.index.month.isin([5, 6, 7, 8, 9, 10])]

winter_ann = float(winter_rets.mean()) * 252 * 100
summer_ann = float(summer_rets.mean()) * 252 * 100
diff = winter_ann - summer_ann

t_cal, p_cal = stats.ttest_ind(winter_rets, summer_rets)

print(f"\nWinter (Nov-Apr) annualized: {winter_ann:+.2f}%")
print(f"Summer (May-Oct) annualized: {summer_ann:+.2f}%")
print(f"Difference: {diff:+.2f}% (t={t_cal:.3f}, p={p_cal:.4f})")

# Year-by-year Halloween effect
years = sorted(set(ret_0050.index.year))
halloween_wins = 0
halloween_total = 0
for yr in years:
    if yr == years[0] or yr == years[-1]:
        continue
    winter_yr = ret_0050[(ret_0050.index >= f'{yr-1}-11-01') & (ret_0050.index < f'{yr}-05-01')]
    summer_yr = ret_0050[(ret_0050.index >= f'{yr}-05-01') & (ret_0050.index < f'{yr}-11-01')]
    if len(winter_yr) > 20 and len(summer_yr) > 20:
        w_ret = float((1 + winter_yr).prod() - 1)
        s_ret = float((1 + summer_yr).prod() - 1)
        if w_ret > s_ret:
            halloween_wins += 1
        halloween_total += 1

halloween_rate = halloween_wins / halloween_total if halloween_total > 0 else 0
print(f"\nHalloween win rate (year-by-year): {halloween_wins}/{halloween_total} = {halloween_rate:.1%}")

# Taiwan-specific: Chinese New Year effect
cny_months = [1, 2]  # Jan-Feb (CNY window)
cny_rets = ret_0050[ret_0050.index.month.isin(cny_months)]
non_cny_rets = ret_0050[~ret_0050.index.month.isin(cny_months)]
cny_ann = float(cny_rets.mean()) * 252 * 100
non_cny_ann = float(non_cny_rets.mean()) * 252 * 100
t_cny, p_cny = stats.ttest_ind(cny_rets, non_cny_rets)
print(f"\nChinese New Year window (Jan-Feb) annualized: {cny_ann:+.2f}%")
print(f"Non-CNY annualized: {non_cny_ann:+.2f}%")
print(f"Difference: {cny_ann - non_cny_ann:+.2f}% (t={t_cny:.3f}, p={p_cny:.4f})")

# Compare US findings: VIX seasonal pattern
vix_by_month = {}
for m in range(1, 13):
    vix_by_month[m] = round(float(prices['VIX'][prices['VIX'].index.month == m].mean()), 2)

results['test3_calendar_anomaly'] = {
    'monthly_avg_return_pct': {str(k): round(v, 2) for k, v in monthly_avg.items()},
    'monthly_n': {str(k): v for k, v in monthly_n.items()},
    'winter_annualized_pct': round(winter_ann, 2),
    'summer_annualized_pct': round(summer_ann, 2),
    'diff_annualized_pct': round(diff, 2),
    'sell_in_may_t_stat': round(float(t_cal), 3),
    'sell_in_may_p_value': round(float(p_cal), 4),
    'sell_in_may_significant_5pct': bool(p_cal < 0.05),
    'halloween_win_rate': round(halloween_rate, 3),
    'halloween_wins_total': f"{halloween_wins}/{halloween_total}",
    'cny_window_annualized_pct': round(cny_ann, 2),
    'non_cny_annualized_pct': round(non_cny_ann, 2),
    'cny_diff_pct': round(cny_ann - non_cny_ann, 2),
    'cny_t_stat': round(float(t_cny), 3),
    'cny_p_value': round(float(p_cny), 4),
    'cny_significant_5pct': bool(p_cny < 0.05),
    'vix_by_month': vix_by_month,
}


# ============================================================
# TEST 4: Rebalancing Frequency for Taiwan VT
# ============================================================
print("\n" + "=" * 70)
print("TEST 4: Rebalancing Frequency for Taiwan VT (8.63/VIX)")
print("=" * 70)

# Use 0050.TW + Cash (the standard Taiwan VT setup)
freq_results = {}
for freq in ['daily', 'weekly', 'monthly']:
    r = run_vt_strategy(ret_0050, ret_cash, vix, target_tw,
                        f"VT {freq}", tx_cost=TX_COST_TW, rebal=freq)
    freq_results[freq] = r
    print(f"\n{freq.capitalize()} rebalancing:")
    print(f"  Sharpe: {r['sharpe']:.4f}, CAGR: {r['ann_ret']:.2f}%, "
          f"Vol: {r['ann_vol']:.2f}%, MDD: {r['mdd']:.1f}%")
    print(f"  Turnover: {r['ann_turnover_pct']:.1f}%/yr, "
          f"TX drag: {r['ann_tx_drag_pct']:.3f}%/yr")

# BH baseline for comparison
bh_100 = run_bh_strategy(ret_0050, ret_cash, 1.0, "BH 100% 0050.TW")
print(f"\nBaseline BH 100% 0050.TW:")
print(f"  Sharpe: {bh_100['sharpe']:.4f}, CAGR: {bh_100['ann_ret']:.2f}%, "
      f"Vol: {bh_100['ann_vol']:.2f}%, MDD: {bh_100['mdd']:.1f}%")

# US comparison: K733 found monthly optimal for 12/VIX
# For Taiwan: is monthly also optimal?
best_freq = max(freq_results, key=lambda k: freq_results[k]['sharpe'])
us_monthly_optimal = True  # K733 finding

results['test4_rebalancing_frequency'] = {
    'strategies': freq_results,
    'baseline_bh_100': bh_100,
    'best_frequency': best_freq,
    'best_sharpe': freq_results[best_freq]['sharpe'],
    'monthly_sharpe': freq_results['monthly']['sharpe'],
    'daily_sharpe': freq_results['daily']['sharpe'],
    'us_monthly_optimal': us_monthly_optimal,
    'taiwan_agrees_with_us': best_freq == 'monthly',
}

print(f"\nBest frequency for Taiwan: {best_freq} (Sharpe {freq_results[best_freq]['sharpe']:.4f})")
print(f"  US finding (K733): Monthly optimal → Taiwan agrees: {best_freq == 'monthly'}")


# ============================================================
# Additional: VT Insurance Cost-Benefit for Taiwan
# ============================================================
print("\n" + "=" * 70)
print("BONUS: VT Insurance Cost-Benefit (Taiwan vs US)")
print("=" * 70)

# Compare VT vs BH for Taiwan
vt_tw = freq_results['monthly']
bh_tw = bh_100

sharpe_cost = round(bh_tw['sharpe'] - vt_tw['sharpe'], 4)
mdd_benefit = round(bh_tw['mdd'] - vt_tw['mdd'], 2)  # positive = VT better
cagr_cost = round(bh_tw['ann_ret'] - vt_tw['ann_ret'], 2)

print(f"\nTaiwan VT Insurance:")
print(f"  Sharpe cost: {sharpe_cost:+.4f} (BH {bh_tw['sharpe']:.4f} vs VT {vt_tw['sharpe']:.4f})")
print(f"  MDD benefit: {mdd_benefit:+.1f}pp (BH {bh_tw['mdd']:.1f}% vs VT {vt_tw['mdd']:.1f}%)")
print(f"  CAGR cost: {cagr_cost:+.2f}pp (BH {bh_tw['ann_ret']:.2f}% vs VT {vt_tw['ann_ret']:.2f}%)")

# US reference (from K738): Sharpe cost ~0.08, MDD benefit ~15pp
print(f"\n  US reference (K738): Sharpe cost ~0.08, MDD benefit ~15pp")
print(f"  Taiwan: Sharpe cost {sharpe_cost:+.4f}, MDD benefit {mdd_benefit:+.1f}pp")

# Cross-market comparison
results['bonus_insurance_cost_benefit'] = {
    'taiwan': {
        'vt_sharpe': vt_tw['sharpe'],
        'bh_sharpe': bh_tw['sharpe'],
        'sharpe_cost': sharpe_cost,
        'vt_mdd': vt_tw['mdd'],
        'bh_mdd': bh_tw['mdd'],
        'mdd_benefit_pp': mdd_benefit,
        'vt_cagr': vt_tw['ann_ret'],
        'bh_cagr': bh_tw['ann_ret'],
        'cagr_cost_pp': cagr_cost,
    },
    'us_reference_k738': {
        'sharpe_cost': 0.08,
        'mdd_benefit_pp': 15.0,
    },
}


# ============================================================
# Cross-Market Summary
# ============================================================
print("\n" + "=" * 70)
print("CROSS-MARKET SUMMARY: US vs Taiwan")
print("=" * 70)

summary = {
    'finding_1_vix_sufficiency': {
        'us': 'VIX sufficient for SPY vol prediction (R² ~0.35)',
        'taiwan': f"VIX(t-1) R²={m1['r2']:.3f}, +own_rv R²={m3['r2']:.3f}, gain={r2_gain:.4f}",
        'generalizes': r2_gain < 0.02,  # If own_rv adds <2pp, VIX is sufficient
    },
    'finding_2_optimal_allocation': {
        'us': '50/50 SPY/GLD is optimal (K702)',
        'taiwan_0050_gld': grid_results.get('0050+GLD', {}).get('best_static_weight', 'N/A'),
        'taiwan_0050_spy': grid_results.get('0050+SPY', {}).get('best_static_weight', 'N/A'),
        'taiwan_0050_cash': grid_results.get('0050+Cash', {}).get('best_static_weight', 'N/A'),
    },
    'finding_3_calendar': {
        'us': 'VIX seasonal significant but return diff insignificant (K736)',
        'taiwan_sell_in_may_sig': bool(p_cal < 0.05),
        'taiwan_halloween_win_rate': round(halloween_rate, 3),
        'taiwan_cny_effect_sig': bool(p_cny < 0.05),
    },
    'finding_4_rebalancing': {
        'us': 'Monthly optimal for 12/VIX (K733)',
        'taiwan_best': best_freq,
        'generalizes': best_freq == 'monthly',
    },
}

for key, s in summary.items():
    print(f"\n{key}:")
    for k2, v2 in s.items():
        print(f"  {k2}: {v2}")

results['cross_market_summary'] = summary


# ============================================================
# Save Results
# ============================================================
results['experiment_id'] = 'K739'
results['title'] = 'Taiwan 0050.TW VT Cross-Validation — Do US Findings Hold in Taiwan?'
results['data_source'] = 'yfinance'
results['assets'] = ['0050.TW', 'SPY', 'GLD', '^VIX']
results['period'] = f"{prices.index[0].date()} to {prices.index[-1].date()}"
results['n_trading_days'] = len(prices)
results['tx_cost_bps_taiwan'] = 10
results['signal_lag'] = 'shift(1) — US VIX lagged 1 day for Taiwan'
results['references'] = [
    'K82/K88: Taiwan VT guide',
    'K636: Amplification 4.6x',
    'K733: US monthly rebalancing optimal',
    'K736: US calendar anomaly',
    'K738: VT insurance cost-benefit',
]
results['timestamp'] = datetime.now().isoformat()

output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k739_taiwan_vt_crossval_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {output_path}")
print("=" * 70)
print("K739 COMPLETE")
print("=" * 70)
