"""
K336: Carbon Credit Market Volatility — A New Asset Class
=========================================================
[提出: Gemini, 執行: Claude]

PRELIMINARY — KRBN only available since mid-2020 (~4 years of data).
All conclusions are tentative given the short sample.

Research questions:
1. How does carbon credit (KRBN) volatility compare to traditional assets?
2. Is carbon diversifying relative to equities, gold, bonds, crypto?
3. Does adding KRBN improve portfolio Sharpe?
4. Does VIX predict carbon volatility?

Data: yfinance (KRBN, SPY, GLD, TLT, BTC-USD, XLE, ^VIX)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K336: Carbon Credit Market Volatility — A New Asset Class")
print("=" * 70)

tickers = {
    'KRBN': 'KRBN',       # KraneShares Global Carbon ETF
    'SPY': 'SPY',         # S&P 500
    'GLD': 'GLD',         # Gold
    'TLT': 'TLT',         # Long-term Treasuries
    'BTC': 'BTC-USD',     # Bitcoin
    'XLE': 'XLE',         # Energy Select Sector
    'VIX': '^VIX',        # CBOE VIX
}

print("\n[1] Downloading data from yfinance...")
raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2020-07-01', end='2026-03-25', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df
    print(f"  {name} ({ticker}): {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

# Build returns dataframe
prices = pd.DataFrame({name: df['Close'] for name, df in raw.items()})
prices = prices.dropna(subset=['KRBN'])  # align to KRBN availability

returns = np.log(prices / prices.shift(1)).dropna()
print(f"\nCommon sample: {returns.index[0].date()} to {returns.index[-1].date()}, N={len(returns)}")

# ============================================================
# 2. CARBON VOL CHARACTERISTICS
# ============================================================
print("\n" + "=" * 70)
print("[2] Carbon Volatility Characteristics")
print("=" * 70)

results = {}

# Basic stats
stats_table = {}
for asset in ['KRBN', 'SPY', 'GLD', 'TLT', 'BTC', 'XLE']:
    r = returns[asset].dropna()
    ann_vol = r.std() * np.sqrt(252)
    ann_ret = r.mean() * 252
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)  # excess kurtosis
    stats_table[asset] = {
        'Ann Return (%)': round(ann_ret * 100, 2),
        'Ann Vol (%)': round(ann_vol * 100, 2),
        'Sharpe': round(ann_ret / ann_vol, 3) if ann_vol > 0 else 0,
        'Skewness': round(skew, 3),
        'Excess Kurtosis': round(kurt, 3),
        'Min Daily (%)': round(r.min() * 100, 2),
        'Max Daily (%)': round(r.max() * 100, 2),
    }

stats_df = pd.DataFrame(stats_table).T
print("\nDescriptive Statistics:")
print(stats_df.to_string())
results['descriptive_stats'] = stats_table

# ACF of squared returns (volatility clustering)
print("\n--- Volatility Clustering (ACF of r^2) ---")
acf_results = {}
for asset in ['KRBN', 'SPY', 'GLD', 'TLT', 'BTC', 'XLE']:
    r = returns[asset].dropna()
    r2 = r ** 2
    # Manual ACF for lags 1, 5, 10, 20
    acf_vals = {}
    for lag in [1, 5, 10, 20]:
        if len(r2) > lag:
            acf_val = r2.autocorr(lag=lag)
            acf_vals[f'lag_{lag}'] = round(acf_val, 4)
    acf_results[asset] = acf_vals
    print(f"  {asset}: " + ", ".join([f"lag-{k.split('_')[1]}={v:.4f}" for k, v in acf_vals.items()]))

results['acf_squared_returns'] = acf_results

# GJR-GARCH estimation for leverage effect
print("\n--- GJR-GARCH(1,1) — Leverage Effect ---")
gjr_results = {}
for asset in ['KRBN', 'SPY', 'GLD', 'TLT', 'BTC', 'XLE']:
    r = returns[asset].dropna() * 100  # percentage returns
    try:
        model = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='t')
        res = model.fit(disp='off')
        params = res.params
        gjr_results[asset] = {
            'omega': round(float(params.get('omega', 0)), 6),
            'alpha': round(float(params.get('alpha[1]', 0)), 4),
            'gamma': round(float(params.get('gamma[1]', 0)), 4),
            'beta': round(float(params.get('beta[1]', 0)), 4),
            'persistence': round(float(params.get('alpha[1]', 0)) + float(params.get('gamma[1]', 0)) / 2 + float(params.get('beta[1]', 0)), 4),
            'nu': round(float(params.get('nu', 0)), 2),
        }
        gamma = float(params.get('gamma[1]', 0))
        alpha = float(params.get('alpha[1]', 0))
        lev_ratio = gamma / alpha if alpha > 0.001 else float('nan')
        gjr_results[asset]['leverage_ratio'] = round(lev_ratio, 3)
        print(f"  {asset}: alpha={gjr_results[asset]['alpha']:.4f}, "
              f"gamma={gjr_results[asset]['gamma']:.4f}, "
              f"beta={gjr_results[asset]['beta']:.4f}, "
              f"leverage_ratio={lev_ratio:.3f}, "
              f"persistence={gjr_results[asset]['persistence']:.4f}")
    except Exception as e:
        print(f"  {asset}: GJR estimation failed — {e}")
        gjr_results[asset] = {'error': str(e)}

results['gjr_garch'] = gjr_results

# ============================================================
# 3. CORRELATION STRUCTURE
# ============================================================
print("\n" + "=" * 70)
print("[3] Correlation Structure")
print("=" * 70)

# Full-sample correlations
corr_assets = ['KRBN', 'SPY', 'GLD', 'TLT', 'BTC', 'XLE']
corr_matrix = returns[corr_assets].corr()
print("\nFull-sample correlation matrix:")
print(corr_matrix.round(3).to_string())
results['correlation_matrix'] = {a: {b: round(corr_matrix.loc[a, b], 4) for b in corr_assets} for a in corr_assets}

# Rolling 63-day (quarterly) correlation KRBN vs SPY, GLD, XLE
print("\n--- Rolling 63-day Correlations with KRBN ---")
rolling_corrs = {}
for other in ['SPY', 'GLD', 'XLE', 'TLT', 'BTC']:
    rc = returns['KRBN'].rolling(63).corr(returns[other])
    rolling_corrs[other] = {
        'mean': round(rc.mean(), 4),
        'std': round(rc.std(), 4),
        'min': round(rc.min(), 4),
        'max': round(rc.max(), 4),
        'pct_negative': round((rc < 0).mean() * 100, 1),
    }
    print(f"  KRBN-{other}: mean={rolling_corrs[other]['mean']:.3f}, "
          f"std={rolling_corrs[other]['std']:.3f}, "
          f"range=[{rolling_corrs[other]['min']:.3f}, {rolling_corrs[other]['max']:.3f}], "
          f"neg%={rolling_corrs[other]['pct_negative']:.1f}%")

results['rolling_correlations_63d'] = rolling_corrs

# Regime-dependent correlation: high VIX vs low VIX
print("\n--- Regime-Dependent Correlation (VIX high/low) ---")
vix_median = returns['VIX'].median()  # use VIX level changes as regime proxy
# Better: use VIX level
vix_level = prices['VIX'].reindex(returns.index).ffill()
vix_med = vix_level.median()
high_vix = returns.loc[vix_level > vix_med]
low_vix = returns.loc[vix_level <= vix_med]

print(f"  VIX median: {vix_med:.1f}")
print(f"  High-VIX days: {len(high_vix)}, Low-VIX days: {len(low_vix)}")

regime_corrs = {}
for regime_name, regime_data in [('high_vix', high_vix), ('low_vix', low_vix)]:
    regime_corrs[regime_name] = {}
    for other in ['SPY', 'GLD', 'XLE']:
        c = regime_data[['KRBN', other]].corr().iloc[0, 1]
        regime_corrs[regime_name][f'KRBN_{other}'] = round(c, 4)
    print(f"  {regime_name}: " + ", ".join([f"KRBN-{k.split('_')[1]}={v:.3f}" for k, v in regime_corrs[regime_name].items()]))

results['regime_correlations'] = regime_corrs

# ============================================================
# 4. PORTFOLIO IMPLICATIONS
# ============================================================
print("\n" + "=" * 70)
print("[4] Portfolio Implications — Does KRBN Improve Risk-Adjusted Returns?")
print("=" * 70)

def portfolio_metrics(weights, ret_df, asset_list):
    """Calculate annualized portfolio metrics."""
    w = np.array(weights)
    port_ret = (ret_df[asset_list] * w).sum(axis=1)
    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    # Max drawdown
    cum = (1 + port_ret).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    mdd = dd.min()
    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0
    # Sortino
    downside = port_ret[port_ret < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0
    return {
        'Ann Return (%)': round(ann_ret * 100, 2),
        'Ann Vol (%)': round(ann_vol * 100, 2),
        'Sharpe': round(sharpe, 3),
        'Max DD (%)': round(mdd * 100, 2),
        'Calmar': round(calmar, 3),
        'Sortino': round(sortino, 3),
    }

portfolios = {
    '100% SPY': ([1.0], ['SPY']),
    '50/50 SPY/GLD': ([0.5, 0.5], ['SPY', 'GLD']),
    '60/40 SPY/TLT': ([0.6, 0.4], ['SPY', 'TLT']),
    '40/40/20 SPY/GLD/KRBN': ([0.4, 0.4, 0.2], ['SPY', 'GLD', 'KRBN']),
    '50/30/20 SPY/GLD/KRBN': ([0.5, 0.3, 0.2], ['SPY', 'GLD', 'KRBN']),
    '40/30/20/10 SPY/GLD/TLT/KRBN': ([0.4, 0.3, 0.2, 0.1], ['SPY', 'GLD', 'TLT', 'KRBN']),
    '100% KRBN': ([1.0], ['KRBN']),
    '100% XLE': ([1.0], ['XLE']),
}

port_results = {}
for name, (weights, assets) in portfolios.items():
    m = portfolio_metrics(weights, returns, assets)
    port_results[name] = m
    print(f"  {name:40s} Sharpe={m['Sharpe']:+.3f}  Vol={m['Ann Vol (%)']:5.1f}%  "
          f"Ret={m['Ann Return (%)']:+6.2f}%  MDD={m['Max DD (%)']:6.2f}%")

results['portfolio_comparison'] = port_results

# Statistical test: is the Sharpe improvement significant? (bootstrap)
print("\n--- Bootstrap test: 50/50 SPY/GLD vs 40/40/20 SPY/GLD/KRBN ---")
np.random.seed(42)
n_boot = 10000
r_base = (returns['SPY'] * 0.5 + returns['GLD'] * 0.5).values
r_krbn = (returns['SPY'] * 0.4 + returns['GLD'] * 0.4 + returns['KRBN'] * 0.2).values
n = len(r_base)

sharpe_diffs = []
for _ in range(n_boot):
    idx = np.random.choice(n, size=n, replace=True)
    s_base = r_base[idx].mean() / r_base[idx].std() * np.sqrt(252)
    s_krbn = r_krbn[idx].mean() / r_krbn[idx].std() * np.sqrt(252)
    sharpe_diffs.append(s_krbn - s_base)

sharpe_diffs = np.array(sharpe_diffs)
p_value = (sharpe_diffs < 0).mean()  # one-sided: is KRBN portfolio better?
ci_lo, ci_hi = np.percentile(sharpe_diffs, [2.5, 97.5])
mean_diff = sharpe_diffs.mean()

print(f"  Mean Sharpe diff (KRBN portfolio - base): {mean_diff:+.4f}")
print(f"  95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
print(f"  p-value (KRBN better): {p_value:.4f}")
print(f"  Significant at 5%: {'Yes' if p_value < 0.05 else 'No'}")

results['sharpe_bootstrap'] = {
    'comparison': '40/40/20 SPY/GLD/KRBN vs 50/50 SPY/GLD',
    'mean_sharpe_diff': round(mean_diff, 4),
    'ci_95': [round(ci_lo, 4), round(ci_hi, 4)],
    'p_value': round(p_value, 4),
    'n_bootstrap': n_boot,
    'significant_5pct': p_value < 0.05,
}

# ============================================================
# 5. VIX PREDICTING CARBON VOLATILITY
# ============================================================
print("\n" + "=" * 70)
print("[5] Does VIX Predict Carbon Volatility?")
print("=" * 70)

# Realized vol (21-day rolling) for KRBN
rv_krbn = returns['KRBN'].rolling(21).std() * np.sqrt(252) * 100  # annualized %
vix_lag = vix_level.shift(1)  # lagged VIX

# Align
pred_df = pd.DataFrame({
    'rv_krbn': rv_krbn,
    'vix_lag': vix_lag,
    'rv_spy': returns['SPY'].rolling(21).std() * np.sqrt(252) * 100,
}).dropna()

# Correlation: lagged VIX vs KRBN realized vol
corr_vix_krbn = pred_df['vix_lag'].corr(pred_df['rv_krbn'])
corr_vix_spy = pred_df['vix_lag'].corr(pred_df['rv_spy'])
print(f"\n  Corr(VIX_lag1, KRBN_RV21): {corr_vix_krbn:.4f}")
print(f"  Corr(VIX_lag1, SPY_RV21):  {corr_vix_spy:.4f}")

# OLS regression: KRBN_RV = a + b*VIX_lag
from numpy.linalg import lstsq

X = np.column_stack([np.ones(len(pred_df)), pred_df['vix_lag'].values])
y = pred_df['rv_krbn'].values
beta, _, _, _ = lstsq(X, y, rcond=None)
y_hat = X @ beta
resid = y - y_hat
sse = (resid ** 2).sum()
sst = ((y - y.mean()) ** 2).sum()
r_squared = 1 - sse / sst

# t-stat for slope
n_obs = len(y)
se_beta = np.sqrt(sse / (n_obs - 2) / ((pred_df['vix_lag'].values - pred_df['vix_lag'].mean()) ** 2).sum())
t_stat = beta[1] / se_beta
p_val_ols = 2 * (1 - stats.t.cdf(abs(t_stat), n_obs - 2))

print(f"\n  OLS: KRBN_RV21 = {beta[0]:.2f} + {beta[1]:.4f} * VIX_lag1")
print(f"  R^2 = {r_squared:.4f}, t-stat = {t_stat:.2f}, p = {p_val_ols:.6f}")
print(f"  Interpretation: 1-point VIX increase -> {beta[1]:.2f}pp change in KRBN ann. vol")

results['vix_predicts_carbon'] = {
    'corr_vix_krbn_rv': round(corr_vix_krbn, 4),
    'corr_vix_spy_rv': round(corr_vix_spy, 4),
    'ols_intercept': round(beta[0], 4),
    'ols_slope': round(beta[1], 4),
    'r_squared': round(r_squared, 4),
    't_stat': round(t_stat, 2),
    'p_value': round(p_val_ols, 6),
    'n_obs': n_obs,
}

# Granger causality test (simple: VIX -> KRBN vol)
print("\n--- Granger-like predictive regression (5-lag) ---")
# Use 5 lags of VIX and 5 lags of KRBN_RV to predict KRBN_RV
from numpy.linalg import lstsq

n_lags = 5
df_gc = pred_df[['rv_krbn', 'vix_lag']].copy()
for i in range(1, n_lags + 1):
    df_gc[f'rv_lag{i}'] = df_gc['rv_krbn'].shift(i)
    df_gc[f'vix_lag{i}'] = df_gc['vix_lag'].shift(i)
df_gc = df_gc.dropna()

# Restricted model: only own lags
X_r = df_gc[[f'rv_lag{i}' for i in range(1, n_lags + 1)]].values
X_r = np.column_stack([np.ones(len(df_gc)), X_r])
y_gc = df_gc['rv_krbn'].values

beta_r, _, _, _ = lstsq(X_r, y_gc, rcond=None)
sse_r = ((y_gc - X_r @ beta_r) ** 2).sum()

# Unrestricted model: own lags + VIX lags
X_u = df_gc[[f'rv_lag{i}' for i in range(1, n_lags + 1)] +
            [f'vix_lag{i}' for i in range(1, n_lags + 1)]].values
X_u = np.column_stack([np.ones(len(df_gc)), X_u])

beta_u, _, _, _ = lstsq(X_u, y_gc, rcond=None)
sse_u = ((y_gc - X_u @ beta_u) ** 2).sum()

# F-test
k_extra = n_lags  # number of VIX lag coefficients
n_gc = len(y_gc)
k_u = X_u.shape[1]
f_stat = ((sse_r - sse_u) / k_extra) / (sse_u / (n_gc - k_u))
p_val_gc = 1 - stats.f.cdf(f_stat, k_extra, n_gc - k_u)

print(f"  F-stat (VIX Granger-causes KRBN vol): {f_stat:.3f}")
print(f"  p-value: {p_val_gc:.6f}")
print(f"  Significant at 5%: {'Yes' if p_val_gc < 0.05 else 'No'}")
print(f"  Interpretation: VIX {'does' if p_val_gc < 0.05 else 'does NOT'} Granger-cause carbon volatility")

results['granger_vix_carbon'] = {
    'f_stat': round(f_stat, 3),
    'p_value': round(p_val_gc, 6),
    'n_lags': n_lags,
    'n_obs': n_gc,
    'significant_5pct': p_val_gc < 0.05,
}

# ============================================================
# 6. YEAR-BY-YEAR ANALYSIS (regime shift check)
# ============================================================
print("\n" + "=" * 70)
print("[6] Year-by-Year Carbon Statistics (structural change?)")
print("=" * 70)

yearly = {}
for year in sorted(returns.index.year.unique()):
    r_year = returns.loc[returns.index.year == year, 'KRBN']
    if len(r_year) < 20:
        continue
    ann_vol = r_year.std() * np.sqrt(252)
    ann_ret = r_year.mean() * 252
    corr_spy = returns.loc[returns.index.year == year, ['KRBN', 'SPY']].corr().iloc[0, 1]
    corr_xle = returns.loc[returns.index.year == year, ['KRBN', 'XLE']].corr().iloc[0, 1]
    yearly[str(year)] = {
        'Ann Return (%)': round(ann_ret * 100, 1),
        'Ann Vol (%)': round(ann_vol * 100, 1),
        'Corr SPY': round(corr_spy, 3),
        'Corr XLE': round(corr_xle, 3),
        'N': len(r_year),
    }
    print(f"  {year}: Ret={ann_ret*100:+6.1f}%, Vol={ann_vol*100:5.1f}%, "
          f"Corr(SPY)={corr_spy:+.3f}, Corr(XLE)={corr_xle:+.3f}, N={len(r_year)}")

results['yearly_stats'] = yearly

# ============================================================
# 7. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("[7] SUMMARY & CONCLUSIONS")
print("=" * 70)

krbn_stats = stats_table['KRBN']
spy_stats = stats_table['SPY']

print(f"""
PRELIMINARY FINDINGS (K336 — Carbon Credit Market Volatility):
Data: KRBN ETF ({returns.index[0].date()} to {returns.index[-1].date()}, N={len(returns)})
WARNING: ~4 years only — all conclusions are tentative.

1. VOLATILITY CHARACTERISTICS:
   - KRBN annualized vol: {krbn_stats['Ann Vol (%)']:.1f}%
     (vs SPY {spy_stats['Ann Vol (%)']:.1f}%,
      XLE {stats_table['XLE']['Ann Vol (%)']:.1f}%,
      BTC {stats_table['BTC']['Ann Vol (%)']:.1f}%)
   - KRBN excess kurtosis: {krbn_stats['Excess Kurtosis']:.2f} (vs SPY {spy_stats['Excess Kurtosis']:.2f})
   - Vol clustering (ACF r^2 lag-1): KRBN={acf_results['KRBN'].get('lag_1', 'N/A')}, SPY={acf_results['SPY'].get('lag_1', 'N/A')}

2. LEVERAGE EFFECT (GJR gamma):
   - KRBN gamma: {gjr_results.get('KRBN', {}).get('gamma', 'N/A')}
   - SPY gamma: {gjr_results.get('SPY', {}).get('gamma', 'N/A')}
   - {'Carbon shows leverage effect (vol rises after losses)' if gjr_results.get('KRBN', {}).get('gamma', 0) > 0.01 else 'Carbon shows weak/no leverage effect'}

3. CORRELATION (DIVERSIFICATION):
   - KRBN-SPY: {corr_matrix.loc['KRBN', 'SPY']:.3f}
   - KRBN-GLD: {corr_matrix.loc['KRBN', 'GLD']:.3f}
   - KRBN-XLE: {corr_matrix.loc['KRBN', 'XLE']:.3f}
   - KRBN-BTC: {corr_matrix.loc['KRBN', 'BTC']:.3f}
   - {'Carbon is moderately correlated with equities — limited diversification' if abs(corr_matrix.loc['KRBN', 'SPY']) > 0.3 else 'Carbon has low correlation with equities — potential diversifier'}

4. PORTFOLIO IMPACT:
   - 50/50 SPY/GLD Sharpe: {port_results['50/50 SPY/GLD']['Sharpe']:.3f}
   - 40/40/20 SPY/GLD/KRBN Sharpe: {port_results['40/40/20 SPY/GLD/KRBN']['Sharpe']:.3f}
   - Sharpe diff: {port_results['40/40/20 SPY/GLD/KRBN']['Sharpe'] - port_results['50/50 SPY/GLD']['Sharpe']:+.3f}
   - Bootstrap p-value: {results['sharpe_bootstrap']['p_value']:.4f}
   - {'KRBN IMPROVES portfolio Sharpe (significant)' if results['sharpe_bootstrap']['significant_5pct'] else 'KRBN does NOT significantly improve portfolio Sharpe'}

5. VIX PREDICTING CARBON VOL:
   - Corr(VIX_lag1, KRBN_RV21): {results['vix_predicts_carbon']['corr_vix_krbn_rv']:.3f}
   - R^2 (OLS): {results['vix_predicts_carbon']['r_squared']:.4f}
   - Granger F-stat: {results['granger_vix_carbon']['f_stat']:.3f}, p={results['granger_vix_carbon']['p_value']:.6f}
   - {'VIX DOES predict carbon volatility' if results['granger_vix_carbon']['significant_5pct'] else 'VIX does NOT predict carbon volatility'}

LIMITATIONS:
- Only ~4 years of data (KRBN inception mid-2020)
- Period includes COVID recovery, 2022 energy crisis, 2023-2025 normalization
- KRBN tracks carbon futures (roll costs embedded), not spot carbon price
- EU ETS policy changes (CBAM, REPowerEU) create structural breaks
- No transaction cost adjustment in portfolio analysis
""")

results['metadata'] = {
    'experiment': 'K336',
    'title': 'Carbon Credit Market Volatility — A New Asset Class',
    'proposed_by': 'Gemini',
    'executed_by': 'Claude',
    'data_source': 'yfinance',
    'sample_start': str(returns.index[0].date()),
    'sample_end': str(returns.index[-1].date()),
    'n_observations': len(returns),
    'status': 'PRELIMINARY — short sample (~4 years)',
    'assets': list(tickers.keys()),
}

# Save results
output_path = 'experiments/k336_carbon_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
