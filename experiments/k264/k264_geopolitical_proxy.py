#!/usr/bin/env python3
"""
K264: Geopolitical Risk and Volatility — Can Defense Sector Signal Predict Vol?
================================================================================
跳躍式探索：地緣政治風險 × 波動率預測

假說：國防/航太類股（ITA）對地緣政治事件反應最快，
     ITA 相對強度變化可能領先大盤波動率。

方法：
1. Defense sector signals:
   - ITA/SPY relative strength (22d rolling change)
   - ITA vol / SPY vol ratio (defense becoming more volatile = geopolitical tension)
   - ITA-GLD correlation (both respond to geopolitical risk)
2. Predictive power for SPY realized vol (partial r, controlling for VIX)
3. Granger causality: ITA vol → SPY vol
4. Portfolio: geopolitical hedge overlay (GLD allocation when defense outperforming)
5. 5-period cross-OOS validation

Data: SPY, ITA, GLD, ^VIX daily from yfinance, 2006-2024
[提出: 用戶, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

RESULTS = {}

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K264: Geopolitical Risk — Defense Sector as Vol Predictor")
print("=" * 70)

tickers = {
    'SPY': 'S&P 500',
    'ITA': 'iShares US Aerospace & Defense ETF',
    'GLD': 'Gold ETF (geopolitical hedge)',
    '^VIX': 'VIX (fear gauge)',
}

print("\n[1] Downloading data 2006-2024...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2006-01-01', end='2024-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Align all series
prices = pd.DataFrame(data).dropna()
print(f"\nAligned dataset: {len(prices)} trading days")
print(f"  Period: {prices.index[0].date()} to {prices.index[-1].date()}")

returns = prices[['SPY', 'ITA', 'GLD']].pct_change().dropna()
vix = prices['^VIX'].reindex(returns.index)
print(f"Returns: {len(returns)} observations")

RESULTS['data'] = {
    'n_obs': len(returns),
    'start': str(returns.index[0].date()),
    'end': str(returns.index[-1].date()),
}

# ============================================================
# 2. Defense Sector Signal Construction
# ============================================================
print("\n" + "=" * 70)
print("[2] Defense Sector Signal Construction")
print("=" * 70)

# 2a. ITA/SPY relative strength — 22d rolling change
ita_spy_ratio = prices['ITA'] / prices['SPY']
rel_strength_22d = ita_spy_ratio.pct_change(22).reindex(returns.index)

# 2b. ITA vol / SPY vol ratio (rolling 22d)
ita_vol_22d = returns['ITA'].rolling(22).std() * np.sqrt(252)
spy_vol_22d = returns['SPY'].rolling(22).std() * np.sqrt(252)
vol_ratio = (ita_vol_22d / spy_vol_22d).reindex(returns.index)

# 2c. ITA-GLD rolling correlation (66d ~ 3 months)
ita_gld_corr = returns['ITA'].rolling(66).corr(returns['GLD']).reindex(returns.index)

# 2d. Composite geopolitical signal: Z-score each, average
def zscore_rolling(series, window=252):
    mu = series.rolling(window).mean()
    sigma = series.rolling(window).std()
    return (series - mu) / sigma

rel_str_z = zscore_rolling(rel_strength_22d)
vol_ratio_z = zscore_rolling(vol_ratio)
ita_gld_z = zscore_rolling(ita_gld_corr)

# Composite: high rel strength + high vol ratio + high ITA-GLD corr = geopolitical tension
geo_composite = (rel_str_z + vol_ratio_z + ita_gld_z) / 3

signals = pd.DataFrame({
    'rel_strength_22d': rel_strength_22d,
    'vol_ratio': vol_ratio,
    'ita_gld_corr': ita_gld_corr,
    'geo_composite': geo_composite,
    'vix': vix,
}).dropna()

print(f"Signal observations: {len(signals)}")
print(f"\nSignal statistics:")
for col in ['rel_strength_22d', 'vol_ratio', 'ita_gld_corr', 'geo_composite']:
    s = signals[col]
    print(f"  {col}: mean={s.mean():.4f}, std={s.std():.4f}, "
          f"min={s.min():.4f}, max={s.max():.4f}")

# ============================================================
# 3. Predictive Power: Partial Correlation with Future SPY RV
# ============================================================
print("\n" + "=" * 70)
print("[3] Defense Signals → Future SPY Realized Vol (Partial r)")
print("=" * 70)

# Compute future realized vol (22d forward)
spy_rv_fwd = returns['SPY'].rolling(22).std().shift(-22) * np.sqrt(252)
spy_rv_fwd = spy_rv_fwd.reindex(signals.index).dropna()

# Align everything
common_idx = signals.index.intersection(spy_rv_fwd.index)
sig_aligned = signals.loc[common_idx]
rv_aligned = spy_rv_fwd.loc[common_idx]
vix_aligned = sig_aligned['vix']

print(f"Prediction sample: {len(common_idx)} obs")

# Partial correlation: signal → future RV, controlling for VIX
def partial_corr(x, y, z):
    """Partial correlation of x and y, controlling for z."""
    # Regress x on z
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x_, y_, z_ = x[mask], y[mask], z[mask]

    from numpy.linalg import lstsq
    Z = np.column_stack([z_, np.ones(len(z_))])

    res_x = x_ - Z @ lstsq(Z, x_, rcond=None)[0]
    res_y = y_ - Z @ lstsq(Z, y_, rcond=None)[0]

    r, p = stats.pearsonr(res_x, res_y)
    n = len(x_)
    t_stat = r * np.sqrt((n - 3) / (1 - r**2))
    return r, p, t_stat, n

print("\nPartial correlations (controlling for VIX):")
print(f"{'Signal':<25} {'partial_r':>10} {'t-stat':>10} {'p-value':>10} {'n':>6}")
print("-" * 65)

partial_results = {}
for sig_name in ['rel_strength_22d', 'vol_ratio', 'ita_gld_corr', 'geo_composite']:
    r, p, t, n = partial_corr(
        sig_aligned[sig_name].values,
        rv_aligned.values,
        vix_aligned.values
    )
    partial_results[sig_name] = {'partial_r': r, 'p_value': p, 't_stat': t, 'n': n}
    sig_str = '***' if abs(t) > 3.0 else '**' if p < 0.01 else '*' if p < 0.05 else ''
    print(f"  {sig_name:<23} {r:>10.4f} {t:>10.2f} {p:>10.4f} {n:>6d} {sig_str}")

# Also simple correlation (without controlling for VIX)
print("\nSimple correlations (no control):")
print(f"{'Signal':<25} {'corr':>10} {'t-stat':>10} {'p-value':>10}")
print("-" * 60)
simple_results = {}
for sig_name in ['rel_strength_22d', 'vol_ratio', 'ita_gld_corr', 'geo_composite']:
    x = sig_aligned[sig_name].values
    y = rv_aligned.values
    mask = np.isfinite(x) & np.isfinite(y)
    r, p = stats.pearsonr(x[mask], y[mask])
    n = mask.sum()
    t = r * np.sqrt((n - 2) / (1 - r**2))
    simple_results[sig_name] = {'corr': r, 'p_value': p, 't_stat': t}
    sig_str = '***' if abs(t) > 3.0 else '**' if p < 0.01 else '*' if p < 0.05 else ''
    print(f"  {sig_name:<23} {r:>10.4f} {t:>10.2f} {p:>10.4f} {sig_str}")

RESULTS['partial_correlations'] = {k: {kk: round(vv, 6) for kk, vv in v.items()}
                                    for k, v in partial_results.items()}
RESULTS['simple_correlations'] = {k: {kk: round(vv, 6) for kk, vv in v.items()}
                                   for k, v in simple_results.items()}

# ============================================================
# 4. Granger Causality: ITA vol → SPY vol
# ============================================================
print("\n" + "=" * 70)
print("[4] Granger Causality: ITA Vol → SPY Vol")
print("=" * 70)

# Prepare vol series (22d rolling, annualized)
ita_vol = returns['ITA'].rolling(22).std() * np.sqrt(252)
spy_vol = returns['SPY'].rolling(22).std() * np.sqrt(252)

vol_df = pd.DataFrame({
    'spy_vol': spy_vol,
    'ita_vol': ita_vol,
}).dropna()

print(f"Vol series: {len(vol_df)} obs")

# Manual Granger test using OLS (avoid statsmodels dependency issues)
def granger_test_manual(y, x, max_lags=5):
    """
    Test if x Granger-causes y.
    H0: lags of x do not help predict y (beyond lags of y).
    Returns F-stat and p-value for each lag order.
    """
    results = {}
    y_arr = y.values
    x_arr = x.values
    n = len(y_arr)

    for lag in range(1, max_lags + 1):
        # Build lagged matrices
        Y = y_arr[lag:]
        n_eff = len(Y)

        # Restricted model: Y ~ Y_lags only
        Z_r = np.column_stack([y_arr[lag-i-1:n-i-1] for i in range(lag)])
        Z_r = np.column_stack([Z_r, np.ones(n_eff)])

        # Unrestricted model: Y ~ Y_lags + X_lags
        Z_u = np.column_stack([
            *[y_arr[lag-i-1:n-i-1] for i in range(lag)],
            *[x_arr[lag-i-1:n-i-1] for i in range(lag)],
            np.ones(n_eff)
        ])

        # Fit both models
        from numpy.linalg import lstsq
        beta_r = lstsq(Z_r, Y, rcond=None)[0]
        beta_u = lstsq(Z_u, Y, rcond=None)[0]

        ssr_r = np.sum((Y - Z_r @ beta_r) ** 2)
        ssr_u = np.sum((Y - Z_u @ beta_u) ** 2)

        # F-test
        q = lag  # number of restrictions
        k_u = Z_u.shape[1]
        F = ((ssr_r - ssr_u) / q) / (ssr_u / (n_eff - k_u))
        p_value = 1 - stats.f.cdf(F, q, n_eff - k_u)

        results[lag] = {'F_stat': F, 'p_value': p_value, 'n_eff': n_eff}

    return results

# ITA vol → SPY vol
print("\nGranger test: ITA vol → SPY vol")
print(f"{'Lags':>5} {'F-stat':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 35)
granger_ita_spy = granger_test_manual(vol_df['spy_vol'], vol_df['ita_vol'], max_lags=5)
for lag, res in granger_ita_spy.items():
    sig = '***' if res['p_value'] < 0.001 else '**' if res['p_value'] < 0.01 else '*' if res['p_value'] < 0.05 else ''
    print(f"  {lag:>3d} {res['F_stat']:>10.2f} {res['p_value']:>10.4f} {sig:>5s}")

# SPY vol → ITA vol (reverse direction)
print("\nGranger test: SPY vol → ITA vol (reverse)")
print(f"{'Lags':>5} {'F-stat':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 35)
granger_spy_ita = granger_test_manual(vol_df['ita_vol'], vol_df['spy_vol'], max_lags=5)
for lag, res in granger_spy_ita.items():
    sig = '***' if res['p_value'] < 0.001 else '**' if res['p_value'] < 0.01 else '*' if res['p_value'] < 0.05 else ''
    print(f"  {lag:>3d} {res['F_stat']:>10.2f} {res['p_value']:>10.4f} {sig:>5s}")

RESULTS['granger'] = {
    'ita_to_spy': {str(k): {kk: round(vv, 6) for kk, vv in v.items()}
                   for k, v in granger_ita_spy.items()},
    'spy_to_ita': {str(k): {kk: round(vv, 6) for kk, vv in v.items()}
                   for k, v in granger_spy_ita.items()},
}

# ============================================================
# 5. Event Study: Defense Outperformance → Next-Month SPY Vol
# ============================================================
print("\n" + "=" * 70)
print("[5] Event Study: Defense Outperformance Episodes")
print("=" * 70)

# Define defense outperformance: ITA 22d return > SPY 22d return by > 1 std
ita_ret_22d = prices['ITA'].pct_change(22)
spy_ret_22d = prices['SPY'].pct_change(22)
outperf = (ita_ret_22d - spy_ret_22d).reindex(returns.index)
outperf_z = zscore_rolling(outperf, window=252)

# High geopolitical tension = defense outperforming (Z > 1)
high_geo = outperf_z > 1.0
low_geo = outperf_z < -1.0
normal = (outperf_z >= -1.0) & (outperf_z <= 1.0)

# Future 22d SPY realized vol
spy_rv_22d_fwd = returns['SPY'].rolling(22).std().shift(-22) * np.sqrt(252)

event_df = pd.DataFrame({
    'outperf_z': outperf_z,
    'high_geo': high_geo,
    'low_geo': low_geo,
    'spy_rv_fwd': spy_rv_22d_fwd,
    'vix': vix,
}).dropna()

high_rv = event_df.loc[event_df['high_geo'], 'spy_rv_fwd']
low_rv = event_df.loc[event_df['low_geo'], 'spy_rv_fwd']
normal_rv = event_df.loc[~event_df['high_geo'] & ~event_df['low_geo'], 'spy_rv_fwd']

print(f"\nDefense outperformance regimes:")
print(f"  High geopolitical (Z>1):  {len(high_rv):>5d} days, future SPY RV = {high_rv.mean():.2%} (median {high_rv.median():.2%})")
print(f"  Normal (-1<Z<1):          {len(normal_rv):>5d} days, future SPY RV = {normal_rv.mean():.2%} (median {normal_rv.median():.2%})")
print(f"  Low geopolitical (Z<-1):  {len(low_rv):>5d} days, future SPY RV = {low_rv.mean():.2%} (median {low_rv.median():.2%})")

# T-test: high vs normal
t_high_normal, p_high_normal = stats.ttest_ind(high_rv, normal_rv)
t_high_low, p_high_low = stats.ttest_ind(high_rv, low_rv)
print(f"\n  High vs Normal: t={t_high_normal:.2f}, p={p_high_normal:.4f}")
print(f"  High vs Low:    t={t_high_low:.2f}, p={p_high_low:.4f}")

# Rank-biserial for effect size
u_stat, p_mw = stats.mannwhitneyu(high_rv, normal_rv, alternative='two-sided')
r_rb = 1 - 2*u_stat/(len(high_rv)*len(normal_rv))
print(f"  Mann-Whitney U: p={p_mw:.4f}, rank-biserial r={r_rb:.3f}")

RESULTS['event_study'] = {
    'high_geo_n': len(high_rv),
    'high_geo_mean_rv': round(high_rv.mean(), 6),
    'normal_n': len(normal_rv),
    'normal_mean_rv': round(normal_rv.mean(), 6),
    'low_geo_n': len(low_rv),
    'low_geo_mean_rv': round(low_rv.mean(), 6),
    't_high_vs_normal': round(t_high_normal, 4),
    'p_high_vs_normal': round(p_high_normal, 6),
    'rank_biserial_r': round(r_rb, 4),
}

# ============================================================
# 6. Portfolio Backtest: Geopolitical Hedge Overlay
# ============================================================
print("\n" + "=" * 70)
print("[6] Portfolio Backtest: Geopolitical Hedge Overlay")
print("=" * 70)

# Strategy: When defense outperforming (geopolitical tension),
# increase GLD allocation as hedge
# Base: 50/50 SPY/GLD (our benchmark)
# Overlay: When geo_composite Z > 1 → 30/70 SPY/GLD
#          When geo_composite Z < -1 → 70/30 SPY/GLD
#          Normal → 50/50

# Use LAGGED signals (no look-ahead): signal from day t → weights for t+1
geo_z = geo_composite.reindex(returns.index)

# Build weight series (lagged by 1 day)
w_spy_geo = pd.Series(0.5, index=returns.index)
w_gld_geo = pd.Series(0.5, index=returns.index)

high_tension = geo_z.shift(1) > 1.0
low_tension = geo_z.shift(1) < -1.0

w_spy_geo[high_tension] = 0.30
w_gld_geo[high_tension] = 0.70
w_spy_geo[low_tension] = 0.70
w_gld_geo[low_tension] = 0.30

# Portfolio returns
ret_geo = w_spy_geo * returns['SPY'] + w_gld_geo * returns['GLD']
ret_5050 = 0.5 * returns['SPY'] + 0.5 * returns['GLD']

# 12/VIX + VT benchmark
vix_lagged = vix.shift(1)
w_vt = np.minimum(12.0 / vix_lagged, 1.0)
ret_vt_5050 = w_vt * (0.5 * returns['SPY'] + 0.5 * returns['GLD'])
ret_vt_5050 = ret_vt_5050 + (1 - w_vt) * 0.0  # cash = 0

# Align and drop NaN
strat_df = pd.DataFrame({
    'geo_overlay': ret_geo,
    'base_5050': ret_5050,
    'vt_5050': ret_vt_5050,
    'spy': returns['SPY'],
}).dropna()

print(f"Backtest period: {strat_df.index[0].date()} to {strat_df.index[-1].date()}")
print(f"  Observations: {len(strat_df)}")

# Metrics
def compute_metrics(ret_series, name, ann=252):
    r = ret_series.dropna()
    mean_ann = r.mean() * ann
    std_ann = r.std() * np.sqrt(ann)
    sharpe = mean_ann / std_ann if std_ann > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    calmar = mean_ann / abs(mdd) if mdd != 0 else 0
    # Sortino
    downside = r[r < 0].std() * np.sqrt(ann)
    sortino = mean_ann / downside if downside > 0 else 0
    # Sharpe t-stat
    n_years = len(r) / ann
    sharpe_t = sharpe * np.sqrt(n_years)
    return {
        'name': name,
        'ann_return': mean_ann,
        'ann_vol': std_ann,
        'sharpe': sharpe,
        'sharpe_t': sharpe_t,
        'mdd': mdd,
        'calmar': calmar,
        'sortino': sortino,
    }

print(f"\n{'Strategy':<20} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'t-stat':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 85)

metrics_all = {}
for col, name in [('geo_overlay', 'Geo Overlay'), ('base_5050', '50/50 Base'),
                   ('vt_5050', '50/50+VT'), ('spy', 'SPY B&H')]:
    m = compute_metrics(strat_df[col], name)
    metrics_all[col] = m
    print(f"  {name:<18} {m['ann_return']:>7.2%} {m['ann_vol']:>7.2%} {m['sharpe']:>8.3f} "
          f"{m['sharpe_t']:>8.2f} {m['mdd']:>7.2%} {m['calmar']:>8.3f} {m['sortino']:>8.3f}")

# Turnover for geo overlay
w_changes = np.abs(w_spy_geo.diff()).dropna()
turnover_annual = w_changes.sum() / (len(w_changes) / 252)
print(f"\n  Geo Overlay turnover: {turnover_annual:.1f} turns/year")

# How many days in each regime?
n_high = high_tension.sum()
n_low = low_tension.sum()
n_normal = len(geo_z.dropna()) - n_high - n_low
print(f"  Regime days: High={n_high} ({n_high/len(geo_z.dropna())*100:.1f}%), "
      f"Normal={n_normal} ({n_normal/len(geo_z.dropna())*100:.1f}%), "
      f"Low={n_low} ({n_low/len(geo_z.dropna())*100:.1f}%)")

RESULTS['portfolio'] = {k: {kk: round(vv, 6) if isinstance(vv, float) else vv
                            for kk, vv in v.items()}
                        for k, v in metrics_all.items()}
RESULTS['portfolio']['turnover_annual'] = round(turnover_annual, 2)

# ============================================================
# 7. 5-Period Cross-OOS Validation
# ============================================================
print("\n" + "=" * 70)
print("[7] 5-Period Cross-OOS Validation")
print("=" * 70)

# Split into 5 equal periods
n = len(strat_df)
period_size = n // 5
oos_results = []

for i in range(5):
    start = i * period_size
    end = (i + 1) * period_size if i < 4 else n
    period = strat_df.iloc[start:end]

    m_geo = compute_metrics(period['geo_overlay'], f'P{i+1} Geo')
    m_base = compute_metrics(period['base_5050'], f'P{i+1} 50/50')
    m_vt = compute_metrics(period['vt_5050'], f'P{i+1} VT')

    geo_wins_base = m_geo['sharpe'] > m_base['sharpe']
    geo_wins_vt = m_geo['sharpe'] > m_vt['sharpe']
    geo_better_mdd_base = m_geo['mdd'] > m_base['mdd']  # less negative = better

    oos_results.append({
        'period': i + 1,
        'start': str(period.index[0].date()),
        'end': str(period.index[-1].date()),
        'n_days': len(period),
        'geo_sharpe': m_geo['sharpe'],
        'base_sharpe': m_base['sharpe'],
        'vt_sharpe': m_vt['sharpe'],
        'geo_mdd': m_geo['mdd'],
        'base_mdd': m_base['mdd'],
        'vt_mdd': m_vt['mdd'],
        'geo_beats_base_sharpe': geo_wins_base,
        'geo_beats_vt_sharpe': geo_wins_vt,
        'geo_beats_base_mdd': geo_better_mdd_base,
    })

print(f"\n{'Period':>8} {'Dates':<25} {'Geo SR':>8} {'Base SR':>8} {'VT SR':>8} {'Geo>Base':>9} {'Geo>VT':>8}")
print("-" * 80)
for r in oos_results:
    print(f"  P{r['period']:>5d}  {r['start']}~{r['end']}  "
          f"{r['geo_sharpe']:>7.3f} {r['base_sharpe']:>8.3f} {r['vt_sharpe']:>8.3f} "
          f"{'YES' if r['geo_beats_base_sharpe'] else 'no':>9s} "
          f"{'YES' if r['geo_beats_vt_sharpe'] else 'no':>8s}")

print(f"\n{'Period':>8} {'Geo MDD':>10} {'Base MDD':>10} {'VT MDD':>10} {'Geo<Base MDD':>13}")
print("-" * 55)
for r in oos_results:
    print(f"  P{r['period']:>5d}  {r['geo_mdd']:>9.2%} {r['base_mdd']:>10.2%} {r['vt_mdd']:>10.2%} "
          f"{'YES' if r['geo_beats_base_mdd'] else 'no':>13s}")

wins_vs_base = sum(1 for r in oos_results if r['geo_beats_base_sharpe'])
wins_vs_vt = sum(1 for r in oos_results if r['geo_beats_vt_sharpe'])
wins_mdd = sum(1 for r in oos_results if r['geo_beats_base_mdd'])

print(f"\n  Geo Overlay vs 50/50 Base: {wins_vs_base}/5 Sharpe wins")
print(f"  Geo Overlay vs 50/50+VT:   {wins_vs_vt}/5 Sharpe wins")
print(f"  Geo Overlay MDD < Base:    {wins_mdd}/5 wins")

RESULTS['cross_oos'] = {
    'periods': [{k: round(v, 6) if isinstance(v, float) else v for k, v in r.items()}
                for r in oos_results],
    'wins_vs_base_sharpe': wins_vs_base,
    'wins_vs_vt_sharpe': wins_vs_vt,
    'wins_mdd_vs_base': wins_mdd,
}

# ============================================================
# 8. Robustness: Alternative Defense Signal (XAR)
# ============================================================
print("\n" + "=" * 70)
print("[8] Robustness: Alternative Defense ETF (XAR)")
print("=" * 70)

try:
    xar_data = yf.download('XAR', start='2006-01-01', end='2024-12-31',
                           progress=False, auto_adjust=True)
    if len(xar_data) > 100:
        xar_close = xar_data['Close']
        if isinstance(xar_close, pd.DataFrame):
            xar_close = xar_close.iloc[:, 0]
        xar_ret = xar_close.pct_change().dropna()
        xar_ret = xar_ret.reindex(returns.index).dropna()

        # XAR relative strength vs SPY
        xar_spy_ratio = xar_close / prices['SPY'].reindex(xar_close.index)
        xar_rel_str = xar_spy_ratio.pct_change(22)

        # XAR vol ratio
        xar_vol_22d = xar_ret.rolling(22).std() * np.sqrt(252)
        spy_vol_22d_aligned = returns['SPY'].reindex(xar_ret.index).rolling(22).std() * np.sqrt(252)
        xar_vol_ratio = xar_vol_22d / spy_vol_22d_aligned

        # Partial correlation with future SPY RV
        common = xar_rel_str.dropna().index.intersection(spy_rv_fwd.dropna().index).intersection(vix.dropna().index)
        if len(common) > 100:
            r_xar, p_xar, t_xar, n_xar = partial_corr(
                xar_rel_str.loc[common].values,
                spy_rv_fwd.loc[common].values,
                vix.loc[common].values
            )
            print(f"  XAR data: {len(xar_data)} days")
            print(f"  XAR rel_strength partial_r = {r_xar:.4f} (t={t_xar:.2f}, p={p_xar:.4f}, n={n_xar})")

            common2 = xar_vol_ratio.dropna().index.intersection(spy_rv_fwd.dropna().index).intersection(vix.dropna().index)
            if len(common2) > 100:
                r_xar2, p_xar2, t_xar2, n_xar2 = partial_corr(
                    xar_vol_ratio.loc[common2].values,
                    spy_rv_fwd.loc[common2].values,
                    vix.loc[common2].values
                )
                print(f"  XAR vol_ratio partial_r    = {r_xar2:.4f} (t={t_xar2:.2f}, p={p_xar2:.4f}, n={n_xar2})")

            RESULTS['robustness_xar'] = {
                'xar_rel_str_partial_r': round(r_xar, 6),
                'xar_rel_str_t': round(t_xar, 4),
                'xar_rel_str_p': round(p_xar, 6),
            }
        else:
            print(f"  XAR insufficient overlap: {len(common)} obs")
    else:
        print("  XAR: insufficient data")
except Exception as e:
    print(f"  XAR: ERROR - {e}")

# ============================================================
# 9. Additional: Geopolitical Crisis Episodes
# ============================================================
print("\n" + "=" * 70)
print("[9] Known Geopolitical Crises — Signal Behavior")
print("=" * 70)

crises = {
    'Russia-Georgia War 2008': ('2008-08-01', '2008-09-15'),
    'Arab Spring 2011': ('2011-01-15', '2011-03-31'),
    'Crimea Annexation 2014': ('2014-02-15', '2014-04-30'),
    'US-China Trade War 2018': ('2018-03-01', '2018-06-30'),
    'US-Iran Tensions 2020': ('2020-01-01', '2020-01-31'),
    'Russia-Ukraine 2022': ('2022-02-01', '2022-04-30'),
    'Israel-Hamas 2023': ('2023-10-01', '2023-12-31'),
}

print(f"\n{'Crisis':<30} {'Geo Z':>8} {'ITA-SPY':>10} {'SPY Vol':>10} {'VIX':>8}")
print("-" * 70)

crisis_results = {}
for name, (start, end) in crises.items():
    mask = (geo_composite.index >= start) & (geo_composite.index <= end)
    if mask.sum() > 0:
        geo_z_crisis = geo_composite[mask].mean()
        ita_excess = (returns['ITA'] - returns['SPY'])[mask].mean() * 252
        spy_v = returns['SPY'][mask].std() * np.sqrt(252)
        vix_mean = vix[mask].mean()
        print(f"  {name:<28} {geo_z_crisis:>8.2f} {ita_excess:>9.2%} {spy_v:>9.2%} {vix_mean:>8.1f}")
        crisis_results[name] = {
            'geo_z': round(geo_z_crisis, 4),
            'ita_excess_ann': round(ita_excess, 6),
            'spy_vol_ann': round(spy_v, 6),
            'vix_mean': round(vix_mean, 2),
        }
    else:
        print(f"  {name:<28}  (no data in period)")

RESULTS['crisis_episodes'] = crisis_results

# ============================================================
# 10. Summary & Conclusion
# ============================================================
print("\n" + "=" * 70)
print("[10] SUMMARY & CONCLUSION")
print("=" * 70)

# Determine key findings
best_partial_sig = max(partial_results.items(), key=lambda x: abs(x[1]['partial_r']))
best_simple_sig = max(simple_results.items(), key=lambda x: abs(x[1]['corr']))

geo_sharpe = metrics_all['geo_overlay']['sharpe']
base_sharpe = metrics_all['base_5050']['sharpe']
vt_sharpe = metrics_all['vt_5050']['sharpe']

print(f"""
K264 Results:
=============

1. DEFENSE SECTOR SIGNAL → FUTURE SPY VOL:
   Best partial r (ctrl VIX): {best_partial_sig[0]} = {best_partial_sig[1]['partial_r']:.4f} (t={best_partial_sig[1]['t_stat']:.2f})
   Best simple r:             {best_simple_sig[0]} = {best_simple_sig[1]['corr']:.4f} (t={best_simple_sig[1]['t_stat']:.2f})

   Interpretation: {'Significant but small' if abs(best_partial_sig[1]['t_stat']) > 2 else 'Not significant'}
   incremental info beyond VIX.

2. GRANGER CAUSALITY:
   ITA vol → SPY vol: {'YES' if granger_ita_spy[1]['p_value'] < 0.05 else 'NO'} (lag=1 p={granger_ita_spy[1]['p_value']:.4f})
   SPY vol → ITA vol: {'YES' if granger_spy_ita[1]['p_value'] < 0.05 else 'NO'} (lag=1 p={granger_spy_ita[1]['p_value']:.4f})
   {'Bidirectional' if granger_ita_spy[1]['p_value'] < 0.05 and granger_spy_ita[1]['p_value'] < 0.05 else 'ITA leads' if granger_ita_spy[1]['p_value'] < 0.05 else 'SPY leads' if granger_spy_ita[1]['p_value'] < 0.05 else 'No causal relationship'} causality detected.

3. EVENT STUDY:
   High geopolitical tension → SPY RV = {high_rv.mean():.2%}
   Normal                   → SPY RV = {normal_rv.mean():.2%}
   Difference: t={t_high_normal:.2f}, p={p_high_normal:.4f}

4. PORTFOLIO:
   Geo Overlay:  Sharpe={geo_sharpe:.3f}
   50/50 Base:   Sharpe={base_sharpe:.3f}
   50/50+VT:     Sharpe={vt_sharpe:.3f}

   Cross-OOS: Geo beats Base {wins_vs_base}/5, Geo beats VT {wins_vs_vt}/5

5. CONCLUSION:
   Defense sector signals {'provide' if abs(best_partial_sig[1]['t_stat']) > 2 else 'do NOT provide'} meaningful incremental
   vol prediction beyond VIX. {'The geopolitical overlay adds marginal value over static 50/50.' if geo_sharpe > base_sharpe else 'The geopolitical overlay does NOT beat static 50/50.'}
   {'50/50+VT remains superior.' if vt_sharpe > geo_sharpe else 'Geo overlay competitive with VT.'}

   This {'confirms' if vt_sharpe > geo_sharpe else 'challenges'} the VIX sufficient statistic hypothesis:
   defense sector info {'is already captured by' if abs(best_partial_sig[1]['t_stat']) < 3 else 'adds to'} VIX.
""")

harvey_pass = abs(best_partial_sig[1]['t_stat']) > 3.0
RESULTS['conclusion'] = {
    'best_partial_r_signal': best_partial_sig[0],
    'best_partial_r': round(best_partial_sig[1]['partial_r'], 6),
    'best_partial_t': round(best_partial_sig[1]['t_stat'], 4),
    'passes_harvey_threshold': harvey_pass,
    'geo_overlay_sharpe': round(geo_sharpe, 4),
    'base_5050_sharpe': round(base_sharpe, 4),
    'vt_5050_sharpe': round(vt_sharpe, 4),
    'geo_beats_base': geo_sharpe > base_sharpe,
    'geo_beats_vt': geo_sharpe > vt_sharpe,
    'cross_oos_wins_vs_base': wins_vs_base,
    'cross_oos_wins_vs_vt': wins_vs_vt,
    'vix_sufficient_stat_confirmed': abs(best_partial_sig[1]['t_stat']) < 3.0,
}

# Save results
results_file = 'experiments/k264_geopolitical_proxy_results.json'
with open(results_file, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\nResults saved to {results_file}")
print("=" * 70)
