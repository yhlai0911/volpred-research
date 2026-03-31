"""
K739b: Taiwan 0050.TW VT Cross-Validation — Holiday-Bug Fix
[提出: Codex (K739 review), 執行: Claude]

Fixes 2 HIGH bugs from Codex review of K739:
  BUG 1: Union calendar + ffill creates synthetic zero returns on mismatched
         holidays → pollutes RV, regression, seasonality analysis.
  BUG 2: Strategy rebalances/pays TX on days 0050.TW is closed (ghost trades).

FIX APPROACH:
  - Download each asset separately, compute returns on each market's OWN
    trading calendar (no ffill across markets).
  - For cross-market analysis (VIX vs 0050 RV): align by DATE but skip
    days where either market is closed.
  - For VIX lag: use VIX from the PREVIOUS US trading day available before
    each TW trading day (not necessarily t-1 calendar day).
  - TX cost charged ONLY on days 0050.TW market is OPEN.

Data: yfinance (0050.TW, ^VIX, GLD, SPY)
Period: 2006-01 to 2026-03 (20 years)
TX cost: 10 bps for Taiwan (includes ETF securities transaction tax)

References:
  K739: Original (buggy) cross-validation
  K82/K88: Taiwan VT guide (8.63/VIX target)
  K636: Amplification 4.6x
  K733: US monthly rebalancing optimal
  K736: US calendar anomaly
  K738: VT insurance cost-benefit
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
# Data Download — SEPARATE calendars
# ============================================================
print("=" * 70)
print("K739b: Taiwan VT Cross-Validation — Holiday-Bug Fix")
print("=" * 70)

start_date = '2006-01-01'
end_date = '2026-03-30'

# Download each asset individually — keep their OWN trading calendars
print("\nDownloading data (separate calendars)...")

raw = {}
for name, ticker in [('0050', '0050.TW'), ('SPY', 'SPY'),
                      ('GLD', 'GLD'), ('VIX', '^VIX')]:
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df['Close'].rename(name)
    print(f"  {name}: {len(df)} trading days "
          f"({df.index[0].date()} to {df.index[-1].date()})")

# Compute returns on each market's OWN calendar (no ffill!)
ret_0050_own = raw['0050'].pct_change().dropna()  # TW calendar
ret_spy_own  = raw['SPY'].pct_change().dropna()   # US calendar
ret_gld_own  = raw['GLD'].pct_change().dropna()   # US calendar
# VIX is a level, not a return — we keep the raw series

# Trading-day counts
tw_days = set(ret_0050_own.index)
us_days = set(ret_spy_own.index)
both_days = tw_days & us_days
tw_only  = tw_days - us_days
us_only  = us_days - tw_days

print(f"\nCalendar analysis:")
print(f"  TW trading days: {len(tw_days)}")
print(f"  US trading days: {len(us_days)}")
print(f"  Both open:       {len(both_days)}")
print(f"  TW-only:         {len(tw_only)}  (US holiday, TW open)")
print(f"  US-only:         {len(us_only)}  (TW holiday, US open)")
print(f"  Holiday mismatch: {len(tw_only) + len(us_only)} days "
      f"({(len(tw_only)+len(us_only))/max(len(tw_days),len(us_days))*100:.1f}%)")

# ============================================================
# Build VIX-for-Taiwan series: most recent US VIX for each TW day
# ============================================================
# For each TW trading day, find the most recent VIX close
# (VIX only trades on US days; US closes ~04:00 TW time,
#  so the "previous US close" VIX is available before TW opens)

vix_raw = raw['VIX'].sort_index()
tw_dates = sorted(tw_days)

# Use asof to get the most recent VIX for each TW date
# This correctly handles:
#   - TW Mon + US Mon: uses Friday's VIX (US Mon hasn't closed yet when TW opens Mon morning)
#     Actually: US Mon close = TW Tue 04:00. So for TW Tue, we have Mon VIX.
#     For TW Mon, we have *Friday's* VIX (the last US close before TW Mon open).
#
# More precisely: TW opens at 09:00 TW (01:00 UTC).
# US closes at 16:00 ET (20:00 or 21:00 UTC, depending on DST).
# So US day T close happens at ~04:00-05:00 TW time on day T+1.
# When TW opens on day D, the latest US VIX available is from US day D-1 (calendar)
# or the most recent US trading day before D.
#
# shift(1) on the merged union calendar was WRONG because it didn't account for
# TW-only days (shift would use the ffill'd zero-return day's VIX).
#
# Correct approach: for each TW day D, use VIX from the last US trading day
# that is STRICTLY BEFORE D.

vix_for_tw = pd.Series(index=pd.DatetimeIndex(tw_dates), dtype=float, name='VIX')
for d in tw_dates:
    # Find last US VIX strictly before this TW day
    mask = vix_raw.index < d
    if mask.any():
        vix_for_tw.loc[d] = vix_raw.loc[mask].iloc[-1]
    else:
        vix_for_tw.loc[d] = np.nan

vix_for_tw = vix_for_tw.dropna()
print(f"\nVIX-for-Taiwan series: {len(vix_for_tw)} days")
print(f"  (Each TW day mapped to most recent prior US VIX close)")

# ============================================================
# Realized Volatility — on EACH market's OWN calendar
# ============================================================
# 0050 RV: computed on TW trading days only (no fake zero returns)
rv_0050 = ret_0050_own.rolling(21, min_periods=15).std() * np.sqrt(252)
rv_spy  = ret_spy_own.rolling(21, min_periods=15).std() * np.sqrt(252)

results = {}

# ============================================================
# TEST 1: VIX Sufficiency for Taiwan
# ============================================================
print("\n" + "=" * 70)
print("TEST 1: VIX Sufficiency for Taiwan 0050.TW")
print("  (Holiday-fixed: RV on TW calendar, VIX from prior US close)")
print("=" * 70)

# Prepare regression data — align by date, no ffill
# RV_0050 forward 21 TW trading days
rv_0050_lead = rv_0050.shift(-21)  # shift on TW calendar

# Align: only dates where we have TW RV and VIX-for-Taiwan
reg_idx = rv_0050_lead.dropna().index.intersection(vix_for_tw.index).intersection(rv_0050.dropna().index)

reg_data = pd.DataFrame({
    'rv_0050_lead': rv_0050_lead.loc[reg_idx],
    'vix_lag': vix_for_tw.loc[reg_idx] / 100,  # VIX as decimal
    'own_rv': rv_0050.loc[reg_idx],
}).dropna()

print(f"Regression sample: {len(reg_data)} observations")
print(f"  Period: {reg_data.index[0].date()} to {reg_data.index[-1].date()}")

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
m1 = ols_regression(y, reg_data[['vix_lag']].values, ['vix_lag'])
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
m3 = ols_regression(y, reg_data[['vix_lag', 'own_rv']].values, ['vix_lag', 'own_rv'])
print(f"\nModel 3 (VIX + Own RV): R² = {m3['r2']:.4f}")
for name, c in m3['coefficients'].items():
    sig = '*' if c['significant_5pct'] else ''
    print(f"  {name:12s}: β={c['beta']:.4f}, t={c['t_stat']:.2f}{sig}")

# Correlations
vix_rv_corr = reg_data['vix_lag'].corr(reg_data['rv_0050_lead'])
own_rv_corr = reg_data['own_rv'].corr(reg_data['rv_0050_lead'])
print(f"\nCorrelations with future 0050 RV:")
print(f"  VIX(prior US):  {vix_rv_corr:.4f}")
print(f"  Own RV(t):       {own_rv_corr:.4f}")

r2_gain = m3['r2'] - m1['r2']
print(f"\nR² gain from adding own RV to VIX: {r2_gain:.4f} ({r2_gain/m1['r2']*100:.1f}%)")

results['test1_vix_sufficiency'] = {
    'model1_vix_only': {
        'r2': round(m1['r2'], 4),
        'adj_r2': round(m1['adj_r2'], 4),
        'vix_lag_beta': round(m1['coefficients']['vix_lag']['beta'], 4),
        'vix_lag_t': round(m1['coefficients']['vix_lag']['t_stat'], 2),
        'vix_lag_sig': m1['coefficients']['vix_lag']['significant_5pct'],
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
        'vix_lag_beta': round(m3['coefficients']['vix_lag']['beta'], 4),
        'vix_lag_t': round(m3['coefficients']['vix_lag']['t_stat'], 2),
        'own_rv_beta': round(m3['coefficients']['own_rv']['beta'], 4),
        'own_rv_t': round(m3['coefficients']['own_rv']['t_stat'], 2),
    },
    'r2_gain_from_own_rv': round(r2_gain, 4),
    'r2_gain_pct': round(r2_gain / m1['r2'] * 100, 1),
    'corr_vix_future_rv': round(vix_rv_corr, 4),
    'corr_own_rv_future_rv': round(own_rv_corr, 4),
    'n_observations': int(m1['n']),
    'vix_lag_method': 'Most recent prior US VIX close (not shift(1) on union calendar)',
    'rv_calendar': 'TW trading days only (no synthetic zero returns)',
    'conclusion': ''
}

if r2_gain < 0.01:
    results['test1_vix_sufficiency']['conclusion'] = \
        'VIX sufficient — adding own RV provides negligible improvement'
elif m3['coefficients']['own_rv']['significant_5pct']:
    results['test1_vix_sufficiency']['conclusion'] = \
        'Own RV adds significant incremental info beyond VIX'
else:
    results['test1_vix_sufficiency']['conclusion'] = \
        'VIX dominant but own RV has some marginal value'


# ============================================================
# TEST 2: Optimal Taiwan 2-Asset Allocation
# ============================================================
print("\n" + "=" * 70)
print("TEST 2: Optimal 2-Asset Allocation for Taiwan Investors")
print("  (Holiday-fixed: returns on own calendars, align by intersection)")
print("=" * 70)

TX_COST_TW = 0.0010  # 10 bps for Taiwan ETFs


def run_vt_strategy_fixed(equity_ret, safe_ret, vix_signal, target_vol,
                          weight_name, tx_cost=TX_COST_TW, rebal='monthly'):
    """
    Run VT strategy with proper calendar handling.

    equity_ret: returns on equity's OWN calendar
    safe_ret: returns on safe asset's OWN calendar (or cash=0)
    vix_signal: VIX aligned to equity's calendar (already lagged correctly)
    target_vol: e.g. 8.63 for Taiwan
    tx_cost: per-trade cost
    rebal: 'daily', 'weekly', 'monthly'

    Key fix: only trade on days when BOTH assets have returns.
    VIX signal already properly lagged (prior US close).
    """
    # Weight signal: target_vol / VIX
    signal = (target_vol / vix_signal).clip(0, 1)
    # signal is already lagged (vix_signal is from prior US close)
    # No additional shift needed — the lag is built into vix_for_tw construction

    if rebal == 'monthly':
        month_change = signal.index.to_series().dt.month.diff().ne(0)
        signal_rebal = signal.copy()
        signal_rebal[~month_change] = np.nan
        signal_rebal = signal_rebal.ffill()
        signal_rebal = signal_rebal.dropna()
    elif rebal == 'weekly':
        is_monday = signal.index.dayofweek == 0
        signal_rebal = signal.copy()
        signal_rebal[~is_monday] = np.nan
        signal_rebal = signal_rebal.ffill()
        signal_rebal = signal_rebal.dropna()
    else:  # daily
        signal_rebal = signal

    # CRITICAL FIX: only use days where BOTH assets have returns
    # For 0050+SPY or 0050+GLD: intersection of TW and US calendars
    # For 0050+Cash: all TW days (cash always available)
    idx = equity_ret.index.intersection(safe_ret.index).intersection(signal_rebal.index)
    eq = equity_ret.loc[idx]
    sf = safe_ret.loc[idx]
    w = signal_rebal.loc[idx]

    # Transaction costs — only on days we actually trade
    w_change = w.diff().abs()
    tx = w_change * tx_cost * 2  # buy + sell

    # Portfolio return
    port_ret = w * eq + (1 - w) * sf - tx
    port_ret = port_ret.dropna()

    # Metrics
    n_years = len(port_ret) / 252
    if n_years == 0:
        return {'name': weight_name, 'sharpe': 0, 'n_days': 0, 'error': 'no data'}

    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + port_ret).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0
    down_ret = port_ret[port_ret < 0]
    sortino = ann_ret / (down_ret.std() * np.sqrt(252)) if len(down_ret) > 0 else 0

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


def run_bh_strategy_fixed(equity_ret, safe_ret, equity_wt, name,
                          tx_cost=TX_COST_TW, rebal='monthly'):
    """Buy-and-hold with fixed weights. Only trades on days both markets open."""
    # Intersection of calendars
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


# Returns on their OWN calendars
ret_cash_tw = pd.Series(0.0, index=ret_0050_own.index)  # cash on TW calendar

# VIX signal for Taiwan (already properly lagged)
vix_tw = vix_for_tw

target_tw = 8.63

# Combinations
combos = {
    '0050+GLD': {
        'equity': ret_0050_own,
        'safe': ret_gld_own,  # US calendar — intersection handles alignment
        'label': '0050.TW + GLD',
    },
    '0050+SPY': {
        'equity': ret_0050_own,
        'safe': ret_spy_own,  # US calendar
        'label': '0050.TW + SPY',
    },
    '0050+Cash': {
        'equity': ret_0050_own,
        'safe': ret_cash_tw,  # TW calendar (always available)
        'label': '0050.TW + Cash (TWD)',
    },
}

# Grid search
print("\n--- Grid Search: Optimal Static Weight ---")
grid_results = {}
for combo_key, combo in combos.items():
    best_sharpe = -999
    best_w = 0.5
    for w_pct in range(10, 91, 10):
        w = w_pct / 100
        r = run_bh_strategy_fixed(combo['equity'], combo['safe'], w,
                                  f"{combo['label']} {w_pct}/{100-w_pct}",
                                  rebal='monthly')
        if r['sharpe'] > best_sharpe:
            best_sharpe = r['sharpe']
            best_w = w

    # Run key weights + best
    results_combo = {}
    test_weights = sorted(set([20, 30, 40, 50, 60, 70, round(best_w * 100)]))
    for w_pct in test_weights:
        w = w_pct / 100
        r = run_bh_strategy_fixed(combo['equity'], combo['safe'], w,
                                  f"BH {w_pct}/{100-w_pct}", rebal='monthly')
        results_combo[f"bh_{w_pct}_{100-w_pct}"] = r

    # VT strategy
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
    for key, r in results_combo.items():
        if 'bh_50_50' in key:
            print(f"  BH 50/50: Sharpe {r['sharpe']:.4f}, MDD {r['mdd']:.1f}%")

results['test2_optimal_allocation'] = grid_results


# ============================================================
# TEST 3: Calendar Anomaly in Taiwan
# ============================================================
print("\n" + "=" * 70)
print("TEST 3: Calendar Anomaly (Sell in May) in Taiwan 0050.TW")
print("  (Holiday-fixed: returns on TW calendar only)")
print("=" * 70)

# Use ret_0050_own (TW calendar only, no fake zero returns from US holidays)
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

# Winter vs Summer
winter_rets = ret_0050_own[ret_0050_own.index.month.isin([11, 12, 1, 2, 3, 4])]
summer_rets = ret_0050_own[ret_0050_own.index.month.isin([5, 6, 7, 8, 9, 10])]

winter_ann = float(winter_rets.mean()) * 252 * 100
summer_ann = float(summer_rets.mean()) * 252 * 100
diff = winter_ann - summer_ann

t_cal, p_cal = stats.ttest_ind(winter_rets, summer_rets)

print(f"\nWinter (Nov-Apr) annualized: {winter_ann:+.2f}%")
print(f"Summer (May-Oct) annualized: {summer_ann:+.2f}%")
print(f"Difference: {diff:+.2f}% (t={t_cal:.3f}, p={p_cal:.4f})")

# Year-by-year Halloween effect
years = sorted(set(ret_0050_own.index.year))
halloween_wins = 0
halloween_total = 0
for yr in years:
    if yr == years[0] or yr == years[-1]:
        continue
    winter_yr = ret_0050_own[
        (ret_0050_own.index >= f'{yr-1}-11-01') &
        (ret_0050_own.index < f'{yr}-05-01')
    ]
    summer_yr = ret_0050_own[
        (ret_0050_own.index >= f'{yr}-05-01') &
        (ret_0050_own.index < f'{yr}-11-01')
    ]
    if len(winter_yr) > 20 and len(summer_yr) > 20:
        w_ret = float((1 + winter_yr).prod() - 1)
        s_ret = float((1 + summer_yr).prod() - 1)
        if w_ret > s_ret:
            halloween_wins += 1
        halloween_total += 1

halloween_rate = halloween_wins / halloween_total if halloween_total > 0 else 0
print(f"\nHalloween win rate: {halloween_wins}/{halloween_total} = {halloween_rate:.1%}")

# CNY effect
cny_months = [1, 2]
cny_rets = ret_0050_own[ret_0050_own.index.month.isin(cny_months)]
non_cny_rets = ret_0050_own[~ret_0050_own.index.month.isin(cny_months)]
cny_ann = float(cny_rets.mean()) * 252 * 100
non_cny_ann = float(non_cny_rets.mean()) * 252 * 100
t_cny, p_cny = stats.ttest_ind(cny_rets, non_cny_rets)
print(f"\nChinese New Year window (Jan-Feb) annualized: {cny_ann:+.2f}%")
print(f"Non-CNY annualized: {non_cny_ann:+.2f}%")
print(f"Difference: {cny_ann - non_cny_ann:+.2f}% (t={t_cny:.3f}, p={p_cny:.4f})")

# VIX by month (on US calendar)
vix_by_month = {}
for m in range(1, 13):
    vix_m = raw['VIX'][raw['VIX'].index.month == m]
    vix_by_month[m] = round(float(vix_m.mean()), 2)

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
    'calendar_fix': 'Returns computed on TW trading days only; no synthetic zeros from US holidays',
}


# ============================================================
# TEST 4: Rebalancing Frequency for Taiwan VT
# ============================================================
print("\n" + "=" * 70)
print("TEST 4: Rebalancing Frequency for Taiwan VT (8.63/VIX)")
print("  (Holiday-fixed: 0050+Cash on TW calendar, VIX from prior US close)")
print("=" * 70)

freq_results = {}
for freq in ['daily', 'weekly', 'monthly']:
    r = run_vt_strategy_fixed(ret_0050_own, ret_cash_tw, vix_tw, target_tw,
                              f"VT {freq}", tx_cost=TX_COST_TW, rebal=freq)
    freq_results[freq] = r
    print(f"\n{freq.capitalize()} rebalancing:")
    print(f"  Sharpe: {r['sharpe']:.4f}, CAGR: {r['ann_ret']:.2f}%, "
          f"Vol: {r['ann_vol']:.2f}%, MDD: {r['mdd']:.1f}%")
    print(f"  Turnover: {r['ann_turnover_pct']:.1f}%/yr, "
          f"TX drag: {r['ann_tx_drag_pct']:.3f}%/yr")

# BH baseline
bh_100 = run_bh_strategy_fixed(ret_0050_own, ret_cash_tw, 1.0,
                                "BH 100% 0050.TW")
print(f"\nBaseline BH 100% 0050.TW:")
print(f"  Sharpe: {bh_100['sharpe']:.4f}, CAGR: {bh_100['ann_ret']:.2f}%, "
      f"Vol: {bh_100['ann_vol']:.2f}%, MDD: {bh_100['mdd']:.1f}%")

best_freq = max(freq_results, key=lambda k: freq_results[k]['sharpe'])

results['test4_rebalancing_frequency'] = {
    'strategies': freq_results,
    'baseline_bh_100': bh_100,
    'best_frequency': best_freq,
    'best_sharpe': freq_results[best_freq]['sharpe'],
    'monthly_sharpe': freq_results['monthly']['sharpe'],
    'daily_sharpe': freq_results['daily']['sharpe'],
    'us_monthly_optimal': True,
    'taiwan_agrees_with_us': best_freq == 'monthly',
    'calendar_fix': 'TX only on TW open days; no ghost trades on US-only days',
}

print(f"\nBest frequency for Taiwan: {best_freq} "
      f"(Sharpe {freq_results[best_freq]['sharpe']:.4f})")


# ============================================================
# Bonus: VT Insurance Cost-Benefit
# ============================================================
print("\n" + "=" * 70)
print("BONUS: VT Insurance Cost-Benefit (Taiwan, Holiday-Fixed)")
print("=" * 70)

vt_tw = freq_results['monthly']
bh_tw = bh_100

sharpe_cost = round(bh_tw['sharpe'] - vt_tw['sharpe'], 4)
mdd_benefit = round(bh_tw['mdd'] - vt_tw['mdd'], 2)
cagr_cost = round(bh_tw['ann_ret'] - vt_tw['ann_ret'], 2)

print(f"\nTaiwan VT Insurance:")
print(f"  Sharpe cost: {sharpe_cost:+.4f} "
      f"(BH {bh_tw['sharpe']:.4f} vs VT {vt_tw['sharpe']:.4f})")
print(f"  MDD benefit: {mdd_benefit:+.1f}pp "
      f"(BH {bh_tw['mdd']:.1f}% vs VT {vt_tw['mdd']:.1f}%)")
print(f"  CAGR cost: {cagr_cost:+.2f}pp "
      f"(BH {bh_tw['ann_ret']:.2f}% vs VT {vt_tw['ann_ret']:.2f}%)")

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
# COMPARISON: K739 (buggy) vs K739b (fixed)
# ============================================================
print("\n" + "=" * 70)
print("COMPARISON: K739 (buggy) vs K739b (fixed)")
print("=" * 70)

# Load K739 results for comparison
k739_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k739_taiwan_vt_crossval_results.json'
try:
    with open(k739_path) as f:
        k739 = json.load(f)

    print("\n--- Test 1: VIX Sufficiency ---")
    print(f"  K739 (buggy):  VIX R²={k739['test1_vix_sufficiency']['model1_vix_only']['r2']:.4f}, "
          f"+own_rv R²={k739['test1_vix_sufficiency']['model3_combined']['r2']:.4f}, "
          f"gain={k739['test1_vix_sufficiency']['r2_gain_from_own_rv']:.4f}")
    print(f"  K739b (fixed): VIX R²={m1['r2']:.4f}, "
          f"+own_rv R²={m3['r2']:.4f}, "
          f"gain={r2_gain:.4f}")
    print(f"  Conclusion change: {'YES' if (r2_gain < 0.01) != (k739['test1_vix_sufficiency']['r2_gain_from_own_rv'] < 0.01) else 'NO'}")

    print("\n--- Test 2: Optimal Allocation ---")
    for combo in ['0050+GLD', '0050+SPY', '0050+Cash']:
        old_w = k739['test2_optimal_allocation'].get(combo, {}).get('best_static_weight', 'N/A')
        new_w = grid_results.get(combo, {}).get('best_static_weight', 'N/A')
        old_s = k739['test2_optimal_allocation'].get(combo, {}).get('best_static_sharpe', 'N/A')
        new_s = grid_results.get(combo, {}).get('best_static_sharpe', 'N/A')
        changed = old_w != new_w
        print(f"  {combo}: weight {old_w} → {new_w}, Sharpe {old_s} → {new_s}"
              f"  {'*** CHANGED ***' if changed else '(same)'}")

    print("\n--- Test 3: Calendar Anomaly ---")
    old_p = k739['test3_calendar_anomaly']['sell_in_may_p_value']
    new_p = float(p_cal)
    print(f"  Sell-in-May p-value: {old_p:.4f} → {new_p:.4f}")
    old_hw = k739['test3_calendar_anomaly']['halloween_win_rate']
    new_hw = halloween_rate
    print(f"  Halloween win rate: {old_hw:.3f} → {new_hw:.3f}")

    print("\n--- Test 4: Rebalancing ---")
    old_best = k739['test4_rebalancing_frequency']['best_frequency']
    new_best = best_freq
    print(f"  Best frequency: {old_best} → {new_best}"
          f"  {'*** CHANGED ***' if old_best != new_best else '(same)'}")
    for f_name in ['daily', 'weekly', 'monthly']:
        old_s = k739['test4_rebalancing_frequency']['strategies'][f_name]['sharpe']
        new_s = freq_results[f_name]['sharpe']
        print(f"    {f_name:8s}: Sharpe {old_s:.4f} → {new_s:.4f}")

    # Store comparison
    results['comparison_k739_vs_k739b'] = {
        'test1_conclusion_changed': (r2_gain < 0.01) != (k739['test1_vix_sufficiency']['r2_gain_from_own_rv'] < 0.01),
        'test1_r2_old': k739['test1_vix_sufficiency']['model1_vix_only']['r2'],
        'test1_r2_new': round(m1['r2'], 4),
        'test2_allocation_changed': {
            combo: grid_results.get(combo, {}).get('best_static_weight') != k739['test2_optimal_allocation'].get(combo, {}).get('best_static_weight')
            for combo in ['0050+GLD', '0050+SPY', '0050+Cash']
        },
        'test3_sell_in_may_p_old': old_p,
        'test3_sell_in_may_p_new': round(new_p, 4),
        'test4_best_freq_old': old_best,
        'test4_best_freq_new': new_best,
        'test4_best_freq_changed': old_best != new_best,
        'holiday_mismatch_days': len(tw_only) + len(us_only),
        'holiday_mismatch_pct': round((len(tw_only)+len(us_only))/max(len(tw_days),len(us_days))*100, 1),
    }

except FileNotFoundError:
    print("  K739 results not found — skipping comparison")


# ============================================================
# Cross-Market Summary
# ============================================================
print("\n" + "=" * 70)
print("CROSS-MARKET SUMMARY: US vs Taiwan (Holiday-Fixed)")
print("=" * 70)

summary = {
    'finding_1_vix_sufficiency': {
        'us': 'VIX sufficient for SPY vol prediction (R² ~0.35)',
        'taiwan_fixed': f"VIX(prior US) R²={m1['r2']:.3f}, +own_rv R²={m3['r2']:.3f}, gain={r2_gain:.4f}",
        'generalizes': r2_gain < 0.02,
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
        'taiwan_best_fixed': best_freq,
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
results['experiment_id'] = 'K739b'
results['title'] = 'Taiwan VT Cross-Validation — Holiday-Bug Fix (Codex Review)'
results['data_source'] = 'yfinance'
results['assets'] = ['0050.TW', 'SPY', 'GLD', '^VIX']
results['period'] = f"{raw['0050'].index[0].date()} to {raw['0050'].index[-1].date()}"
results['n_tw_trading_days'] = len(tw_days)
results['n_us_trading_days'] = len(us_days)
results['n_both_open'] = len(both_days)
results['n_holiday_mismatch'] = len(tw_only) + len(us_only)
results['tx_cost_bps_taiwan'] = 10
results['vix_lag_method'] = 'Most recent prior US VIX close for each TW trading day'
results['bug_fixes'] = [
    'BUG 1 FIXED: No longer ffill across calendars — returns computed on own market days only',
    'BUG 2 FIXED: TX only charged on days when market is actually open (no ghost trades)',
    'VIX lag: uses asof-style lookup (most recent prior US close) instead of shift(1) on union calendar',
]
results['references'] = [
    'K739: Original (buggy) cross-validation',
    'K82/K88: Taiwan VT guide',
    'K636: Amplification 4.6x',
    'K733: US monthly rebalancing optimal',
    'K736: US calendar anomaly',
    'K738: VT insurance cost-benefit',
]
results['timestamp'] = datetime.now().isoformat()

output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k739b_taiwan_vt_fixed_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {output_path}")
print("=" * 70)
print("K739b COMPLETE — Holiday bugs fixed")
print("=" * 70)
