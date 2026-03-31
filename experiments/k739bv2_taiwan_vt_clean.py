"""
K739bv2: Taiwan 0050.TW VT Cross-Validation — CLEAN Split-Corrected Data
=========================================================================
Reruns K739b (holiday-bug-fixed Taiwan VT cross-validation) with clean 0050.TW data.

Problem in K739b:
  - Used raw yfinance 0050.TW data that has a split artifact at 2014-01-02
  - Pre-2014 prices ~4x too high, creating a phantom -75% return
  - This corrupts: RV computation, VIX sufficiency R², optimal allocation Sharpe,
    calendar anomaly statistics, rebalancing frequency comparison

Fix:
  - Uses `from volpred.utils import clean_tw50_data` to properly fix the split
  - Pre-2014 prices divided by 4
  - Returns recomputed from clean prices

Key questions:
  1. Does VIX sufficiency R² change?
  2. Does 20/80 optimal allocation survive?
  3. Does daily > monthly rebalancing hold?
  4. Do calendar anomaly results change?

Data source: yfinance (0050.TW, SPY, GLD, ^VIX) with split correction
Period: 2006-01-01 to 2026-03-31

[提出: User (split artifact fix), 執行: Claude]
Author: VolPred Research System
Date: 2026-03-31
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
from datetime import datetime
from numpy.linalg import lstsq

# CRITICAL FIX
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

# ============================================================
# Data Download — SEPARATE calendars, CLEAN 0050.TW
# ============================================================
print("=" * 70)
print("K739bv2: Taiwan VT Cross-Validation — CLEAN 0050.TW Data")
print("=" * 70)

start_date = '2006-01-01'
end_date = '2026-03-31'

print("\nDownloading data (separate calendars, clean 0050.TW)...")

raw = {}
for name, ticker in [('SPY', 'SPY'), ('GLD', 'GLD'), ('VIX', '^VIX')]:
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df['Close'].rename(name)
    print(f"  {name}: {len(df)} trading days "
          f"({df.index[0].date()} to {df.index[-1].date()})")

# 0050.TW — CLEAN DATA
tw_raw = yf.download('0050.TW', start=start_date, end=end_date, progress=False)
if isinstance(tw_raw.columns, pd.MultiIndex):
    tw_raw.columns = tw_raw.columns.get_level_values(0)
tw_prices_raw = tw_raw['Close'].copy()
tw_prices_clean, tw_ret_clean = clean_tw50_data(tw_prices_raw)
raw['0050'] = tw_prices_clean.rename('0050')
print(f"  0050 (CLEAN): {len(tw_prices_clean)} trading days "
      f"({tw_prices_clean.index[0].date()} to {tw_prices_clean.index[-1].date()})")

# Verify split fix
split_date = pd.Timestamp('2014-01-02')
if split_date in tw_prices_clean.index:
    pre_date = tw_prices_clean.index[tw_prices_clean.index < split_date][-1]
    pre_clean = float(tw_prices_clean.loc[pre_date])
    post_clean = float(tw_prices_clean.loc[split_date])
    pre_raw = float(tw_prices_raw.loc[pre_date])
    post_raw = float(tw_prices_raw.loc[split_date])
    print(f"\n  Split artifact check at {split_date.date()}:")
    print(f"    RAW:   {pre_raw:.2f} → {post_raw:.2f} (ratio: {pre_raw/post_raw:.2f})")
    print(f"    CLEAN: {pre_clean:.2f} → {post_clean:.2f} (ratio: {pre_clean/post_clean:.2f})")

# Compute returns on each market's OWN calendar
ret_0050_own = tw_ret_clean.dropna()
ret_spy_own = raw['SPY'].pct_change().dropna()
ret_gld_own = raw['GLD'].pct_change().dropna()

tw_days = set(ret_0050_own.index)
us_days = set(ret_spy_own.index)
both_days = tw_days & us_days
tw_only = tw_days - us_days
us_only = us_days - tw_days

print(f"\nCalendar analysis:")
print(f"  TW trading days: {len(tw_days)}")
print(f"  US trading days: {len(us_days)}")
print(f"  Both open:       {len(both_days)}")
print(f"  TW-only:         {len(tw_only)}")
print(f"  US-only:         {len(us_only)}")

# ============================================================
# Build VIX-for-Taiwan series (same method as K739b)
# ============================================================
vix_raw = raw['VIX'].sort_index()
tw_dates = sorted(tw_days)

vix_for_tw = pd.Series(index=pd.DatetimeIndex(tw_dates), dtype=float, name='VIX')
for d in tw_dates:
    mask = vix_raw.index < d
    if mask.any():
        vix_for_tw.loc[d] = vix_raw.loc[mask].iloc[-1]
    else:
        vix_for_tw.loc[d] = np.nan

vix_for_tw = vix_for_tw.dropna()
print(f"\nVIX-for-Taiwan series: {len(vix_for_tw)} days")

# ============================================================
# RV on OWN calendar
# ============================================================
rv_0050 = ret_0050_own.rolling(21, min_periods=15).std() * np.sqrt(252)
rv_spy = ret_spy_own.rolling(21, min_periods=15).std() * np.sqrt(252)

results = {}

# ============================================================
# TEST 1: VIX Sufficiency for Taiwan
# ============================================================
print("\n" + "=" * 70)
print("TEST 1: VIX Sufficiency for Taiwan 0050.TW (CLEAN data)")
print("=" * 70)

rv_0050_lead = rv_0050.shift(-21)
reg_idx = rv_0050_lead.dropna().index.intersection(vix_for_tw.index).intersection(rv_0050.dropna().index)

reg_data = pd.DataFrame({
    'rv_0050_lead': rv_0050_lead.loc[reg_idx],
    'vix_lag': vix_for_tw.loc[reg_idx] / 100,
    'own_rv': rv_0050.loc[reg_idx],
}).dropna()

print(f"Regression sample: {len(reg_data)} observations")
print(f"  Period: {reg_data.index[0].date()} to {reg_data.index[-1].date()}")


def ols_regression(y, X, var_names):
    X_const = np.column_stack([np.ones(len(X)), X])
    beta, residuals, rank, sv = lstsq(X_const, y, rcond=None)
    y_hat = X_const @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot
    adj_r2 = 1 - (1 - r2) * (len(y) - 1) / (len(y) - X_const.shape[1])
    mse = ss_res / (len(y) - X_const.shape[1])
    se = np.sqrt(np.diag(mse * np.linalg.inv(X_const.T @ X_const)))
    t_stats = beta / se
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), len(y) - X_const.shape[1]))
    result = {'r2': r2, 'adj_r2': adj_r2, 'n': len(y), 'coefficients': {}}
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

m1 = ols_regression(y, reg_data[['vix_lag']].values, ['vix_lag'])
print(f"\nModel 1 (VIX only): R² = {m1['r2']:.4f}")
for name, c in m1['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

m2 = ols_regression(y, reg_data[['own_rv']].values, ['own_rv'])
print(f"\nModel 2 (Own RV only): R² = {m2['r2']:.4f}")

m3 = ols_regression(y, reg_data[['vix_lag', 'own_rv']].values, ['vix_lag', 'own_rv'])
print(f"\nModel 3 (VIX + Own RV): R² = {m3['r2']:.4f}")
for name, c in m3['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

vix_rv_corr = reg_data['vix_lag'].corr(reg_data['rv_0050_lead'])
own_rv_corr = reg_data['own_rv'].corr(reg_data['rv_0050_lead'])
r2_gain = m3['r2'] - m1['r2']
print(f"\nCorrelations: VIX→future RV: {vix_rv_corr:.4f}, Own RV→future RV: {own_rv_corr:.4f}")
print(f"R² gain from adding own RV: {r2_gain:.4f} ({r2_gain/m1['r2']*100:.1f}%)")

results['test1_vix_sufficiency'] = {
    'model1_vix_only': {'r2': round(m1['r2'], 4), 'adj_r2': round(m1['adj_r2'], 4)},
    'model2_own_rv_only': {'r2': round(m2['r2'], 4), 'adj_r2': round(m2['adj_r2'], 4)},
    'model3_combined': {'r2': round(m3['r2'], 4), 'adj_r2': round(m3['adj_r2'], 4)},
    'r2_gain_from_own_rv': round(r2_gain, 4),
    'r2_gain_pct': round(r2_gain / m1['r2'] * 100, 1),
    'corr_vix_future_rv': round(vix_rv_corr, 4),
    'corr_own_rv_future_rv': round(own_rv_corr, 4),
    'n_observations': int(m1['n']),
    'data_fix': 'CLEAN 0050.TW — split artifact corrected',
}


# ============================================================
# TEST 2: Optimal Taiwan 2-Asset Allocation
# ============================================================
print("\n" + "=" * 70)
print("TEST 2: Optimal 2-Asset Allocation for Taiwan Investors (CLEAN)")
print("=" * 70)

TX_COST_TW = 0.0010


def run_vt_strategy_fixed(equity_ret, safe_ret, vix_signal, target_vol,
                          weight_name, tx_cost=TX_COST_TW, rebal='monthly'):
    signal = (target_vol / vix_signal).clip(0, 1)
    if rebal == 'monthly':
        month_change = signal.index.to_series().dt.month.diff().ne(0)
        signal_rebal = signal.copy()
        signal_rebal[~month_change] = np.nan
        signal_rebal = signal_rebal.ffill().dropna()
    elif rebal == 'weekly':
        is_monday = signal.index.dayofweek == 0
        signal_rebal = signal.copy()
        signal_rebal[~is_monday] = np.nan
        signal_rebal = signal_rebal.ffill().dropna()
    else:
        signal_rebal = signal

    idx = equity_ret.index.intersection(safe_ret.index).intersection(signal_rebal.index)
    eq = equity_ret.loc[idx]
    sf = safe_ret.loc[idx]
    w = signal_rebal.loc[idx]

    w_change = w.diff().abs()
    tx = w_change * tx_cost * 2
    port_ret = w * eq + (1 - w) * sf - tx
    port_ret = port_ret.dropna()

    n_years = len(port_ret) / 252
    if n_years == 0:
        return {'name': weight_name, 'sharpe': 0, 'n_days': 0}

    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + port_ret).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0
    down_ret = port_ret[port_ret < 0]
    sortino = ann_ret / (down_ret.std() * np.sqrt(252)) if len(down_ret) > 0 else 0

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
        'ann_turnover_pct': round(float(w_change.sum() / n_years * 100), 1),
        'ann_tx_drag_pct': round(float(tx.sum() / n_years * 100), 3),
    }


def run_bh_strategy_fixed(equity_ret, safe_ret, equity_wt, name,
                          tx_cost=TX_COST_TW, rebal='monthly'):
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
    if n_years == 0:
        return {'name': name, 'sharpe': 0, 'n_days': 0}

    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + port_ret).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0
    down_ret = port_ret[port_ret < 0]
    sortino = ann_ret / (down_ret.std() * np.sqrt(252)) if len(down_ret) > 0 else 0

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


ret_cash_tw = pd.Series(0.0, index=ret_0050_own.index)
vix_tw = vix_for_tw
target_tw = 8.63

combos = {
    '0050+GLD': {'equity': ret_0050_own, 'safe': ret_gld_own, 'label': '0050.TW + GLD'},
    '0050+SPY': {'equity': ret_0050_own, 'safe': ret_spy_own, 'label': '0050.TW + SPY'},
    '0050+Cash': {'equity': ret_0050_own, 'safe': ret_cash_tw, 'label': '0050.TW + Cash (TWD)'},
}

grid_results = {}
for combo_key, combo in combos.items():
    best_sharpe = -999
    best_w = 0.5
    for w_pct in range(10, 91, 10):
        w = w_pct / 100
        r = run_bh_strategy_fixed(combo['equity'], combo['safe'], w,
                                  f"{combo['label']} {w_pct}/{100-w_pct}", rebal='monthly')
        if r['sharpe'] > best_sharpe:
            best_sharpe = r['sharpe']
            best_w = w

    results_combo = {}
    test_weights = sorted(set([20, 30, 40, 50, 60, 70, round(best_w * 100)]))
    for w_pct in test_weights:
        w = w_pct / 100
        r = run_bh_strategy_fixed(combo['equity'], combo['safe'], w,
                                  f"BH {w_pct}/{100-w_pct}", rebal='monthly')
        results_combo[f"bh_{w_pct}_{100-w_pct}"] = r

    vt_r = run_vt_strategy_fixed(combo['equity'], combo['safe'], vix_tw,
                                 target_tw, f"VT 8.63/VIX", rebal='monthly')
    results_combo['vt_8.63'] = vt_r

    grid_results[combo_key] = {
        'best_static_weight': round(best_w, 2),
        'best_static_sharpe': round(best_sharpe, 4),
        'strategies': results_combo,
    }

    print(f"\n{combo['label']}:")
    print(f"  Best static: {best_w*100:.0f}% equity → Sharpe {best_sharpe:.4f}")
    print(f"  VT 8.63/VIX: Sharpe {vt_r['sharpe']:.4f}, MDD {vt_r['mdd']:.1f}%")

results['test2_optimal_allocation'] = grid_results


# ============================================================
# TEST 3: Calendar Anomaly
# ============================================================
print("\n" + "=" * 70)
print("TEST 3: Calendar Anomaly (Sell in May) in Taiwan 0050.TW (CLEAN)")
print("=" * 70)

monthly_0050 = ret_0050_own.resample('ME').apply(lambda x: (1 + x).prod() - 1)
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

winter_rets = ret_0050_own[ret_0050_own.index.month.isin([11, 12, 1, 2, 3, 4])]
summer_rets = ret_0050_own[ret_0050_own.index.month.isin([5, 6, 7, 8, 9, 10])]

winter_ann = float(winter_rets.mean()) * 252 * 100
summer_ann = float(summer_rets.mean()) * 252 * 100
diff = winter_ann - summer_ann
t_cal, p_cal = stats.ttest_ind(winter_rets, summer_rets)

print(f"\nWinter (Nov-Apr) annualized: {winter_ann:+.2f}%")
print(f"Summer (May-Oct) annualized: {summer_ann:+.2f}%")
print(f"Difference: {diff:+.2f}% (t={t_cal:.3f}, p={p_cal:.4f})")

# Halloween effect
years = sorted(set(ret_0050_own.index.year))
halloween_wins = 0
halloween_total = 0
for yr in years:
    if yr == years[0] or yr == years[-1]:
        continue
    winter_yr = ret_0050_own[
        (ret_0050_own.index >= f'{yr-1}-11-01') & (ret_0050_own.index < f'{yr}-05-01')]
    summer_yr = ret_0050_own[
        (ret_0050_own.index >= f'{yr}-05-01') & (ret_0050_own.index < f'{yr}-11-01')]
    if len(winter_yr) > 20 and len(summer_yr) > 20:
        w_ret = float((1 + winter_yr).prod() - 1)
        s_ret = float((1 + summer_yr).prod() - 1)
        if w_ret > s_ret:
            halloween_wins += 1
        halloween_total += 1

halloween_rate = halloween_wins / halloween_total if halloween_total > 0 else 0
print(f"\nHalloween win rate: {halloween_wins}/{halloween_total} = {halloween_rate:.1%}")

# CNY effect
cny_rets = ret_0050_own[ret_0050_own.index.month.isin([1, 2])]
non_cny_rets = ret_0050_own[~ret_0050_own.index.month.isin([1, 2])]
cny_ann = float(cny_rets.mean()) * 252 * 100
non_cny_ann = float(non_cny_rets.mean()) * 252 * 100
t_cny, p_cny = stats.ttest_ind(cny_rets, non_cny_rets)

print(f"\nCNY window (Jan-Feb) annualized: {cny_ann:+.2f}%")
print(f"Non-CNY annualized: {non_cny_ann:+.2f}%")
print(f"Difference: {cny_ann - non_cny_ann:+.2f}% (t={t_cny:.3f}, p={p_cny:.4f})")

results['test3_calendar_anomaly'] = {
    'monthly_avg_return_pct': {str(k): round(v, 2) for k, v in monthly_avg.items()},
    'winter_annualized_pct': round(winter_ann, 2),
    'summer_annualized_pct': round(summer_ann, 2),
    'diff_annualized_pct': round(diff, 2),
    'sell_in_may_t_stat': round(float(t_cal), 3),
    'sell_in_may_p_value': round(float(p_cal), 4),
    'sell_in_may_significant_5pct': bool(p_cal < 0.05),
    'halloween_win_rate': round(halloween_rate, 3),
    'halloween_wins_total': f"{halloween_wins}/{halloween_total}",
    'cny_window_annualized_pct': round(cny_ann, 2),
    'cny_t_stat': round(float(t_cny), 3),
    'cny_p_value': round(float(p_cny), 4),
    'data_fix': 'CLEAN 0050.TW — split artifact corrected',
}


# ============================================================
# TEST 4: Rebalancing Frequency
# ============================================================
print("\n" + "=" * 70)
print("TEST 4: Rebalancing Frequency for Taiwan VT (8.63/VIX) (CLEAN)")
print("=" * 70)

freq_results = {}
for freq in ['daily', 'weekly', 'monthly']:
    r = run_vt_strategy_fixed(ret_0050_own, ret_cash_tw, vix_tw, target_tw,
                              f"VT {freq}", tx_cost=TX_COST_TW, rebal=freq)
    freq_results[freq] = r
    print(f"\n{freq.capitalize()} rebalancing:")
    print(f"  Sharpe: {r['sharpe']:.4f}, CAGR: {r['ann_ret']:.2f}%, "
          f"Vol: {r['ann_vol']:.2f}%, MDD: {r['mdd']:.1f}%")

bh_100 = run_bh_strategy_fixed(ret_0050_own, ret_cash_tw, 1.0, "BH 100% 0050.TW")
print(f"\nBaseline BH 100% 0050.TW:")
print(f"  Sharpe: {bh_100['sharpe']:.4f}, CAGR: {bh_100['ann_ret']:.2f}%, "
      f"Vol: {bh_100['ann_vol']:.2f}%, MDD: {bh_100['mdd']:.1f}%")

best_freq = max(freq_results, key=lambda k: freq_results[k]['sharpe'])

results['test4_rebalancing_frequency'] = {
    'strategies': freq_results,
    'baseline_bh_100': bh_100,
    'best_frequency': best_freq,
    'best_sharpe': freq_results[best_freq]['sharpe'],
    'data_fix': 'CLEAN 0050.TW — split artifact corrected',
}

print(f"\nBest frequency for Taiwan: {best_freq} (Sharpe {freq_results[best_freq]['sharpe']:.4f})")


# ============================================================
# COMPARISON: K739b (raw) vs K739bv2 (clean)
# ============================================================
print("\n" + "=" * 70)
print("COMPARISON: K739b (raw) vs K739bv2 (clean)")
print("=" * 70)

k739b_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k739b_taiwan_vt_fixed_results.json'
comparison = {}
try:
    with open(k739b_path) as f:
        k739b = json.load(f)

    print("\n--- Test 1: VIX Sufficiency ---")
    old_r2_vix = k739b['test1_vix_sufficiency']['model1_vix_only']['r2']
    old_r2_combined = k739b['test1_vix_sufficiency']['model3_combined']['r2']
    old_gain = k739b['test1_vix_sufficiency']['r2_gain_from_own_rv']
    new_r2_vix = round(m1['r2'], 4)
    new_r2_combined = round(m3['r2'], 4)
    new_gain = round(r2_gain, 4)
    print(f"  K739b (raw):   VIX R²={old_r2_vix:.4f}, +own_rv R²={old_r2_combined:.4f}, gain={old_gain:.4f}")
    print(f"  K739bv2 (clean): VIX R²={new_r2_vix:.4f}, +own_rv R²={new_r2_combined:.4f}, gain={new_gain:.4f}")

    comparison['test1'] = {
        'r2_vix_old': old_r2_vix, 'r2_vix_new': new_r2_vix,
        'r2_combined_old': old_r2_combined, 'r2_combined_new': new_r2_combined,
        'gain_old': old_gain, 'gain_new': new_gain,
        'conclusion_changed': (old_gain < 0.01) != (new_gain < 0.01),
    }

    print("\n--- Test 2: Optimal Allocation ---")
    for combo in ['0050+GLD', '0050+SPY', '0050+Cash']:
        old_w = k739b['test2_optimal_allocation'].get(combo, {}).get('best_static_weight', 'N/A')
        new_w = grid_results.get(combo, {}).get('best_static_weight', 'N/A')
        old_s = k739b['test2_optimal_allocation'].get(combo, {}).get('best_static_sharpe', 'N/A')
        new_s = grid_results.get(combo, {}).get('best_static_sharpe', 'N/A')
        changed = old_w != new_w
        print(f"  {combo}: weight {old_w} → {new_w}, Sharpe {old_s} → {new_s}"
              f"  {'*** CHANGED ***' if changed else '(same)'}")

    comparison['test2'] = {
        combo: {
            'weight_old': k739b['test2_optimal_allocation'].get(combo, {}).get('best_static_weight'),
            'weight_new': grid_results.get(combo, {}).get('best_static_weight'),
            'sharpe_old': k739b['test2_optimal_allocation'].get(combo, {}).get('best_static_sharpe'),
            'sharpe_new': grid_results.get(combo, {}).get('best_static_sharpe'),
            'changed': k739b['test2_optimal_allocation'].get(combo, {}).get('best_static_weight') !=
                       grid_results.get(combo, {}).get('best_static_weight'),
        }
        for combo in ['0050+GLD', '0050+SPY', '0050+Cash']
    }

    print("\n--- Test 3: Calendar Anomaly ---")
    old_p_cal = k739b['test3_calendar_anomaly']['sell_in_may_p_value']
    new_p_cal = round(float(p_cal), 4)
    old_hw = k739b['test3_calendar_anomaly']['halloween_win_rate']
    new_hw = round(halloween_rate, 3)
    print(f"  Sell-in-May p-value: {old_p_cal:.4f} → {new_p_cal:.4f}")
    print(f"  Halloween win rate: {old_hw:.3f} → {new_hw:.3f}")

    comparison['test3'] = {
        'p_value_old': old_p_cal, 'p_value_new': new_p_cal,
        'halloween_old': old_hw, 'halloween_new': new_hw,
    }

    print("\n--- Test 4: Rebalancing ---")
    old_best = k739b['test4_rebalancing_frequency']['best_frequency']
    new_best = best_freq
    print(f"  Best frequency: {old_best} → {new_best}"
          f"  {'*** CHANGED ***' if old_best != new_best else '(same)'}")
    for f_name in ['daily', 'weekly', 'monthly']:
        old_s = k739b['test4_rebalancing_frequency']['strategies'][f_name]['sharpe']
        new_s = freq_results[f_name]['sharpe']
        print(f"    {f_name:8s}: Sharpe {old_s:.4f} → {new_s:.4f}")

    comparison['test4'] = {
        'best_freq_old': old_best, 'best_freq_new': new_best,
        'best_freq_changed': old_best != new_best,
        'sharpe_changes': {
            f: {'old': k739b['test4_rebalancing_frequency']['strategies'][f]['sharpe'],
                'new': freq_results[f]['sharpe']}
            for f in ['daily', 'weekly', 'monthly']
        }
    }

except FileNotFoundError:
    print("  K739b results not found")
    comparison['error'] = 'K739b results not found'

# ============================================================
# Save Results
# ============================================================
results['experiment_id'] = 'K739bv2'
results['title'] = 'Taiwan VT Cross-Validation — CLEAN 0050.TW Data (Split Fix)'
results['data_source'] = 'yfinance + clean_tw50_data (volpred.utils)'
results['data_fix'] = 'Pre-2014 0050.TW prices divided by 4 (split ratio) to remove discontinuity'
results['original_experiment'] = 'K739b'
results['assets'] = ['0050.TW (clean)', 'SPY', 'GLD', '^VIX']
results['period'] = f"{raw['0050'].index[0].date()} to {raw['0050'].index[-1].date()}"
results['n_tw_trading_days'] = len(tw_days)
results['n_us_trading_days'] = len(us_days)
results['comparison_k739b_vs_k739bv2'] = comparison
results['timestamp'] = datetime.now().isoformat()
results['proposer'] = 'User (split artifact fix)'
results['executor'] = 'Claude'
results['references'] = [
    'K739b: Holiday-bug-fixed Taiwan VT cross-validation (raw 0050.TW)',
    'K738: VT insurance cost-benefit (raw data)',
    'K82/K88: Taiwan VT guide (8.63/VIX target)',
]

output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k739bv2_taiwan_vt_clean_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {output_path}")
print("=" * 70)
print("K739bv2 COMPLETE — Clean 0050.TW data")
print("=" * 70)
