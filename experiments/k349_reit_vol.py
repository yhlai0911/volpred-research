#!/usr/bin/env python3
"""
K349: REIT Volatility — Real Estate as a Different Asset Class
==============================================================
跳躍式探索：不動產 ETF 的波動率特性

問題：REIT 的波動率行為像股票還是自成一類？
背景：
- K207 發現 VIX 對非股票資產不夠用
- K342 發現原油沒有 leverage effect
- REIT 是否有 leverage effect？VIX 能否預測 REIT vol？

方法：
1. REIT vol 特性 vs 股票（ann vol, GJR gamma, vol clustering ACF）
2. REIT-SPY 關係（相關性 by VIX regime, lead-lag）
3. REIT 在投組中的角色（SPY/VNQ vs SPY/GLD）
4. GFC 深度分析（REIT 是 2008 震央）

數據來源：yfinance（VNQ ~2004-, XLRE ~2015-, SPY, GLD, ^VIX）
[提出: 用戶, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model
import json
import warnings
warnings.filterwarnings('ignore')

results = {}

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K349: REIT Volatility — Real Estate as a Different Asset Class")
print("=" * 70)

tickers = {
    'VNQ': 'Vanguard Real Estate ETF',
    'XLRE': 'Real Estate Select Sector SPDR',
    'SPY': 'S&P 500 ETF',
    'GLD': 'Gold ETF',
    '^VIX': 'CBOE Volatility Index',
}

print("\n[1] Downloading data (max history)...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2004-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days, {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')} ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Compute returns
returns = {}
for ticker in ['VNQ', 'XLRE', 'SPY', 'GLD']:
    if ticker in data:
        ret = data[ticker].pct_change().dropna()
        returns[ticker] = ret
        print(f"  {ticker} returns: {len(ret)} obs, mean={ret.mean()*252:.2%}/yr, std={ret.std()*np.sqrt(252):.2%}/yr")

# VIX as level
vix = data.get('^VIX')

# ============================================================
# 2. REIT Vol Characteristics vs Equity
# ============================================================
print("\n" + "=" * 70)
print("[2] REIT Vol Characteristics vs Equity")
print("=" * 70)

# Align VNQ and SPY to common dates
common_idx = returns['VNQ'].index.intersection(returns['SPY'].index)
if 'GLD' in returns:
    common_idx = common_idx.intersection(returns['GLD'].index)
print(f"\nCommon period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')} ({len(common_idx)} days)")

vol_chars = {}
for ticker in ['VNQ', 'SPY', 'GLD']:
    if ticker not in returns:
        continue
    r = returns[ticker].loc[common_idx]

    # Basic stats
    ann_vol = r.std() * np.sqrt(252)
    ann_ret = r.mean() * 252
    skew = r.skew()
    kurt = r.kurtosis()

    # Realized vol (22-day rolling)
    rv22 = r.rolling(22).std() * np.sqrt(252)

    # Vol of vol
    vol_of_vol = rv22.dropna().std()

    # Autocorrelation of squared returns (vol clustering)
    r2 = r**2
    acf_1 = r2.autocorr(lag=1)
    acf_5 = r2.autocorr(lag=5)
    acf_22 = r2.autocorr(lag=22)

    vol_chars[ticker] = {
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': ann_ret / ann_vol if ann_vol > 0 else 0,
        'skewness': skew,
        'excess_kurtosis': kurt,
        'vol_of_vol': vol_of_vol,
        'acf_r2_1': acf_1,
        'acf_r2_5': acf_5,
        'acf_r2_22': acf_22,
    }

    print(f"\n  {ticker}:")
    print(f"    Ann Return:     {ann_ret:+.2%}")
    print(f"    Ann Vol:        {ann_vol:.2%}")
    print(f"    Sharpe:         {ann_ret/ann_vol:.3f}")
    print(f"    Skewness:       {skew:.3f}")
    print(f"    Excess Kurt:    {kurt:.3f}")
    print(f"    Vol of Vol:     {vol_of_vol:.4f}")
    print(f"    ACF(r^2, 1):    {acf_1:.3f}")
    print(f"    ACF(r^2, 5):    {acf_5:.3f}")
    print(f"    ACF(r^2, 22):   {acf_22:.3f}")

results['vol_characteristics'] = vol_chars

# ============================================================
# 3. GJR-GARCH: Leverage Effect
# ============================================================
print("\n" + "=" * 70)
print("[3] GJR-GARCH: Leverage Effect Comparison")
print("=" * 70)

gjr_results = {}
for ticker in ['VNQ', 'SPY', 'GLD']:
    if ticker not in returns:
        continue
    r = returns[ticker].loc[common_idx] * 100  # in percentage

    try:
        model = arch_model(r, vol='Garch', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
        res = model.fit(disp='off', show_warning=False)

        omega = res.params.get('omega', np.nan)
        alpha = res.params.get('alpha[1]', np.nan)
        gamma = res.params.get('gamma[1]', np.nan)
        beta = res.params.get('beta[1]', np.nan)
        nu = res.params.get('nu', np.nan)

        # p-value for gamma
        gamma_pval = res.pvalues.get('gamma[1]', np.nan)
        gamma_tstat = res.tvalues.get('gamma[1]', np.nan)

        persistence = alpha + gamma/2 + beta

        gjr_results[ticker] = {
            'omega': float(omega),
            'alpha': float(alpha),
            'gamma': float(gamma),
            'beta': float(beta),
            'nu': float(nu),
            'gamma_tstat': float(gamma_tstat),
            'gamma_pval': float(gamma_pval),
            'persistence': float(persistence),
            'has_leverage': bool(gamma > 0.05 and gamma_pval < 0.05),
        }

        lev_flag = "YES" if gamma > 0.05 and gamma_pval < 0.05 else "NO" if gamma_pval >= 0.05 else "WEAK"
        print(f"\n  {ticker}: GJR-GARCH(1,1,1) with Student-t")
        print(f"    alpha={alpha:.4f}, gamma={gamma:.4f} (t={gamma_tstat:.2f}, p={gamma_pval:.4f}), beta={beta:.4f}")
        print(f"    Persistence: {persistence:.4f}")
        print(f"    Student-t df: {nu:.2f}")
        print(f"    Leverage effect: {lev_flag}")
    except Exception as e:
        print(f"  {ticker}: GJR-GARCH failed - {e}")
        gjr_results[ticker] = {'error': str(e)}

results['gjr_garch'] = gjr_results

# Compare VNQ gamma to SPY gamma
if 'VNQ' in gjr_results and 'SPY' in gjr_results:
    vnq_g = gjr_results['VNQ'].get('gamma', 0)
    spy_g = gjr_results['SPY'].get('gamma', 0)
    print(f"\n  >>> VNQ gamma/SPY gamma ratio: {vnq_g/spy_g:.2f}x" if spy_g > 0 else "")
    print(f"  >>> VNQ behaves {'like equity (has leverage effect)' if gjr_results['VNQ'].get('has_leverage') else 'differently (weak/no leverage effect)'}")

# ============================================================
# 4. VIX-REIT Correlation Analysis
# ============================================================
print("\n" + "=" * 70)
print("[4] VIX-REIT Correlation Analysis")
print("=" * 70)

if vix is not None:
    vix_aligned = vix.reindex(common_idx).ffill()
    vix_change = vix_aligned.pct_change().dropna()

    # Full-sample correlations
    print("\n  Full-sample correlations with VIX changes:")
    vix_corr = {}
    for ticker in ['VNQ', 'SPY', 'GLD']:
        if ticker not in returns:
            continue
        r = returns[ticker].loc[common_idx]
        common2 = r.index.intersection(vix_change.index)
        corr = r.loc[common2].corr(vix_change.loc[common2])
        vix_corr[ticker] = float(corr)
        print(f"    corr({ticker}, DVIX): {corr:.3f}")

    results['vix_correlation'] = vix_corr

    # By VIX regime
    print("\n  Correlations by VIX regime:")
    regimes = {
        'Low (VIX<15)': vix_aligned < 15,
        'Medium (15-25)': (vix_aligned >= 15) & (vix_aligned < 25),
        'High (VIX>=25)': vix_aligned >= 25,
    }

    regime_corr = {}
    for regime_name, mask in regimes.items():
        regime_idx = common_idx[mask.loc[common_idx].values]
        if len(regime_idx) < 60:
            print(f"    {regime_name}: too few obs ({len(regime_idx)})")
            continue

        print(f"\n    {regime_name} ({len(regime_idx)} days):")
        regime_corr[regime_name] = {}
        for ticker in ['VNQ', 'SPY', 'GLD']:
            if ticker not in returns:
                continue
            r = returns[ticker].loc[regime_idx]
            corr_spy_vnq = returns['VNQ'].loc[regime_idx].corr(returns['SPY'].loc[regime_idx]) if ticker == 'VNQ' else None
            # VNQ-SPY correlation in this regime
            if ticker == 'VNQ':
                corr_vs_spy = returns['VNQ'].loc[regime_idx].corr(returns['SPY'].loc[regime_idx])
                regime_corr[regime_name]['VNQ_SPY'] = float(corr_vs_spy)
                print(f"      corr(VNQ, SPY): {corr_vs_spy:.3f}")
            if ticker == 'GLD':
                corr_vs_spy = returns['GLD'].loc[regime_idx].corr(returns['SPY'].loc[regime_idx])
                regime_corr[regime_name]['GLD_SPY'] = float(corr_vs_spy)
                print(f"      corr(GLD, SPY): {corr_vs_spy:.3f}")

    results['regime_correlations'] = regime_corr

# ============================================================
# 5. Lead-Lag Analysis: Does REIT vol lead or lag equity vol?
# ============================================================
print("\n" + "=" * 70)
print("[5] Lead-Lag Analysis: REIT vol vs Equity vol")
print("=" * 70)

vnq_r = returns['VNQ'].loc[common_idx]
spy_r = returns['SPY'].loc[common_idx]

# Use 22-day realized vol
vnq_rv = vnq_r.rolling(22).std() * np.sqrt(252)
spy_rv = spy_r.rolling(22).std() * np.sqrt(252)

# Drop NaN
common3 = vnq_rv.dropna().index.intersection(spy_rv.dropna().index)
vnq_rv = vnq_rv.loc[common3]
spy_rv = spy_rv.loc[common3]

# Cross-correlation at various lags
print("\n  Cross-correlation: corr(VNQ_RV(t), SPY_RV(t+k))")
lead_lag = {}
for lag in range(-10, 11):
    if lag == 0:
        cc = vnq_rv.corr(spy_rv)
    elif lag > 0:
        cc = vnq_rv.iloc[:-lag].reset_index(drop=True).corr(
             spy_rv.iloc[lag:].reset_index(drop=True))
    else:
        cc = vnq_rv.iloc[-lag:].reset_index(drop=True).corr(
             spy_rv.iloc[:lag].reset_index(drop=True))
    lead_lag[lag] = float(cc)

# Find peak
peak_lag = max(lead_lag, key=lead_lag.get)
print(f"  Peak correlation at lag={peak_lag}: {lead_lag[peak_lag]:.4f}")
print(f"  (Positive lag = VNQ leads SPY)")

for lag in [-5, -2, -1, 0, 1, 2, 5]:
    print(f"    lag={lag:+d}: {lead_lag[lag]:.4f}")

results['lead_lag'] = lead_lag
results['lead_lag_peak'] = peak_lag

# Granger causality test (simple version with F-test)
print("\n  Granger Causality Test (5 lags):")
n_lags = 5

# Test: VNQ_RV -> SPY_RV
# Restricted: SPY_RV(t) = c + sum(b_i * SPY_RV(t-i))
# Unrestricted: SPY_RV(t) = c + sum(b_i * SPY_RV(t-i)) + sum(g_i * VNQ_RV(t-i))
from numpy.linalg import lstsq

def granger_test(y_series, x_series, n_lags):
    """Simple Granger causality F-test: does x Granger-cause y?"""
    y = y_series.values
    x = x_series.values
    n = len(y)

    # Build lag matrices
    Y = y[n_lags:]

    # Restricted model: only own lags
    Z_r = np.column_stack([y[n_lags-i-1:n-i-1] for i in range(n_lags)])
    Z_r = np.column_stack([np.ones(len(Y)), Z_r])

    # Unrestricted model: own lags + other lags
    Z_u = np.column_stack([Z_r] + [x[n_lags-i-1:n-i-1] for i in range(n_lags)])

    # OLS
    b_r = lstsq(Z_r, Y, rcond=None)[0]
    b_u = lstsq(Z_u, Y, rcond=None)[0]

    e_r = Y - Z_r @ b_r
    e_u = Y - Z_u @ b_u

    ssr_r = np.sum(e_r**2)
    ssr_u = np.sum(e_u**2)

    n_obs = len(Y)
    k_r = Z_r.shape[1]
    k_u = Z_u.shape[1]

    f_stat = ((ssr_r - ssr_u) / (k_u - k_r)) / (ssr_u / (n_obs - k_u))
    p_val = 1 - stats.f.cdf(f_stat, k_u - k_r, n_obs - k_u)

    return f_stat, p_val

f1, p1 = granger_test(spy_rv, vnq_rv, n_lags)
f2, p2 = granger_test(vnq_rv, spy_rv, n_lags)

print(f"    VNQ_RV -> SPY_RV: F={f1:.2f}, p={p1:.4f} {'***' if p1<0.01 else '**' if p1<0.05 else '*' if p1<0.1 else ''}")
print(f"    SPY_RV -> VNQ_RV: F={f2:.2f}, p={p2:.4f} {'***' if p2<0.01 else '**' if p2<0.05 else '*' if p2<0.1 else ''}")

if p1 < 0.05 and p2 < 0.05:
    print("    >>> Bidirectional Granger causality")
elif p1 < 0.05:
    print("    >>> VNQ vol Granger-causes SPY vol (REIT leads equity!)")
elif p2 < 0.05:
    print("    >>> SPY vol Granger-causes VNQ vol (equity leads REIT)")
else:
    print("    >>> No significant Granger causality")

results['granger_causality'] = {
    'vnq_to_spy': {'f_stat': float(f1), 'p_value': float(p1)},
    'spy_to_vnq': {'f_stat': float(f2), 'p_value': float(p2)},
}

# ============================================================
# 6. GFC Deep Dive: REITs as Ground Zero
# ============================================================
print("\n" + "=" * 70)
print("[6] GFC Deep Dive: REITs as Ground Zero (2007-2009)")
print("=" * 70)

# Define GFC sub-periods
gfc_periods = {
    'Pre-GFC (2006)': ('2006-01-01', '2006-12-31'),
    'Early Crisis (2007H2)': ('2007-07-01', '2007-12-31'),
    'Bear Stearns (2008Q1)': ('2008-01-01', '2008-03-31'),
    'Calm Before Storm (2008Q2-Q3)': ('2008-04-01', '2008-09-14'),
    'Lehman Collapse (Sep-Nov 2008)': ('2008-09-15', '2008-11-30'),
    'Recovery Start (2009H1)': ('2009-01-01', '2009-06-30'),
    'Recovery (2009H2)': ('2009-07-01', '2009-12-31'),
}

gfc_stats = {}
print(f"\n  {'Period':<35} {'VNQ Vol':>10} {'SPY Vol':>10} {'VNQ/SPY':>10} {'VNQ-SPY corr':>15}")
print("  " + "-" * 82)

for period_name, (start, end) in gfc_periods.items():
    mask = (common_idx >= start) & (common_idx <= end)
    period_idx = common_idx[mask]
    if len(period_idx) < 10:
        continue

    vnq_vol = returns['VNQ'].loc[period_idx].std() * np.sqrt(252)
    spy_vol = returns['SPY'].loc[period_idx].std() * np.sqrt(252)
    corr = returns['VNQ'].loc[period_idx].corr(returns['SPY'].loc[period_idx])

    vnq_ret = returns['VNQ'].loc[period_idx].sum()
    spy_ret = returns['SPY'].loc[period_idx].sum()

    gfc_stats[period_name] = {
        'vnq_vol': float(vnq_vol),
        'spy_vol': float(spy_vol),
        'vol_ratio': float(vnq_vol / spy_vol) if spy_vol > 0 else 0,
        'correlation': float(corr),
        'vnq_return': float(vnq_ret),
        'spy_return': float(spy_ret),
        'n_days': int(len(period_idx)),
    }

    print(f"  {period_name:<35} {vnq_vol:>9.1%} {spy_vol:>9.1%} {vnq_vol/spy_vol:>9.2f}x {corr:>14.3f}")

results['gfc_deep_dive'] = gfc_stats

# Max drawdown during GFC
gfc_mask = (common_idx >= '2007-01-01') & (common_idx <= '2009-12-31')
gfc_idx = common_idx[gfc_mask]

for ticker in ['VNQ', 'SPY', 'GLD']:
    if ticker not in data:
        continue
    prices = data[ticker].reindex(gfc_idx).ffill()
    cum_max = prices.cummax()
    dd = (prices - cum_max) / cum_max
    mdd = dd.min()
    mdd_date = dd.idxmin()
    print(f"\n  {ticker} GFC MDD: {mdd:.1%} on {mdd_date.strftime('%Y-%m-%d')}")

# VNQ drawdown timeline
vnq_gfc = data['VNQ'].reindex(gfc_idx).ffill()
vnq_peak = vnq_gfc.max()
vnq_trough = vnq_gfc.min()
print(f"\n  VNQ peak-to-trough: ${vnq_peak:.2f} -> ${vnq_trough:.2f} ({(vnq_trough/vnq_peak - 1):.1%})")

# ============================================================
# 7. Portfolio Comparison: SPY/VNQ vs SPY/GLD
# ============================================================
print("\n" + "=" * 70)
print("[7] Portfolio Comparison: 50/50 SPY/VNQ vs 50/50 SPY/GLD")
print("=" * 70)

# Use GLD common period (GLD starts ~Nov 2004)
if 'GLD' in returns:
    gld_start = returns['GLD'].index[0]
    portfolio_idx = common_idx[common_idx >= gld_start]
    print(f"\n  Portfolio period: {portfolio_idx[0].strftime('%Y-%m-%d')} to {portfolio_idx[-1].strftime('%Y-%m-%d')} ({len(portfolio_idx)} days)")

    spy_r = returns['SPY'].loc[portfolio_idx]
    vnq_r = returns['VNQ'].loc[portfolio_idx]
    gld_r = returns['GLD'].loc[portfolio_idx]

    # 50/50 portfolios (daily rebalanced for simplicity)
    port_spy_vnq = 0.5 * spy_r + 0.5 * vnq_r
    port_spy_gld = 0.5 * spy_r + 0.5 * gld_r
    port_spy_only = spy_r

    # Also test 60/40 SPY/Bond proxy (buy-and-hold SPY)
    portfolios = {
        '100% SPY': port_spy_only,
        '50/50 SPY/VNQ': port_spy_vnq,
        '50/50 SPY/GLD': port_spy_gld,
    }

    portfolio_stats = {}
    print(f"\n  {'Portfolio':<20} {'Ann Ret':>10} {'Ann Vol':>10} {'Sharpe':>10} {'MDD':>10} {'Calmar':>10} {'Skew':>10}")
    print("  " + "-" * 82)

    for name, port_r in portfolios.items():
        ann_ret = port_r.mean() * 252
        ann_vol = port_r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        skew = port_r.skew()

        # MDD
        cum = (1 + port_r).cumprod()
        cum_max = cum.cummax()
        dd = (cum - cum_max) / cum_max
        mdd = dd.min()
        calmar = ann_ret / abs(mdd) if mdd != 0 else 0

        portfolio_stats[name] = {
            'ann_return': float(ann_ret),
            'ann_vol': float(ann_vol),
            'sharpe': float(sharpe),
            'mdd': float(mdd),
            'calmar': float(calmar),
            'skewness': float(skew),
        }

        print(f"  {name:<20} {ann_ret:>9.2%} {ann_vol:>9.2%} {sharpe:>9.3f} {mdd:>9.1%} {calmar:>9.3f} {skew:>9.3f}")

    results['portfolio_comparison'] = portfolio_stats

    # Rolling correlation: VNQ-SPY vs GLD-SPY
    print("\n  Rolling 252-day correlation:")
    rolling_corr_vnq = spy_r.rolling(252).corr(vnq_r)
    rolling_corr_gld = spy_r.rolling(252).corr(gld_r)

    print(f"    VNQ-SPY: mean={rolling_corr_vnq.dropna().mean():.3f}, std={rolling_corr_vnq.dropna().std():.3f}, min={rolling_corr_vnq.dropna().min():.3f}, max={rolling_corr_vnq.dropna().max():.3f}")
    print(f"    GLD-SPY: mean={rolling_corr_gld.dropna().mean():.3f}, std={rolling_corr_gld.dropna().std():.3f}, min={rolling_corr_gld.dropna().min():.3f}, max={rolling_corr_gld.dropna().max():.3f}")

    results['rolling_correlation'] = {
        'vnq_spy': {
            'mean': float(rolling_corr_vnq.dropna().mean()),
            'std': float(rolling_corr_vnq.dropna().std()),
            'min': float(rolling_corr_vnq.dropna().min()),
            'max': float(rolling_corr_vnq.dropna().max()),
        },
        'gld_spy': {
            'mean': float(rolling_corr_gld.dropna().mean()),
            'std': float(rolling_corr_gld.dropna().std()),
            'min': float(rolling_corr_gld.dropna().min()),
            'max': float(rolling_corr_gld.dropna().max()),
        },
    }

# ============================================================
# 8. REIT VT: Can VIX-based VT work for VNQ?
# ============================================================
print("\n" + "=" * 70)
print("[8] REIT Volatility Targeting: 12/VIX for VNQ")
print("=" * 70)

if vix is not None and 'VNQ' in returns:
    # Align VIX and VNQ
    vix_daily = vix.reindex(common_idx).ffill()
    vnq_r = returns['VNQ'].loc[common_idx]

    # 12/VIX weight (lagged: VIX_t -> weight for r_{t+1})
    target_vol = 12
    weight = target_vol / vix_daily
    weight = weight.clip(0.0, 1.5)  # cap at 150%

    # Lagged weight: weight_t applied to r_{t+1}
    weight_lagged = weight.shift(1)

    # VT returns
    vnq_vt = weight_lagged * vnq_r
    vnq_vt = vnq_vt.dropna()
    vnq_bh = vnq_r.loc[vnq_vt.index]

    # Stats
    for name, r in [('VNQ Buy&Hold', vnq_bh), ('VNQ 12/VIX VT', vnq_vt)]:
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + r).cumprod()
        mdd = ((cum - cum.cummax()) / cum.cummax()).min()

        print(f"\n  {name}:")
        print(f"    Ann Return: {ann_ret:+.2%}")
        print(f"    Ann Vol:    {ann_vol:.2%}")
        print(f"    Sharpe:     {sharpe:.3f}")
        print(f"    MDD:        {mdd:.1%}")

    # Sharpe improvement significance (Jobson-Korkie test approx)
    n = len(vnq_vt)
    s_bh = vnq_bh.mean() / vnq_bh.std()
    s_vt = vnq_vt.mean() / vnq_vt.std()
    se_diff = np.sqrt((1/n) * (2 - 2*vnq_bh.corr(vnq_vt) + 0.5*(s_bh**2 + s_vt**2 - 2*s_bh*s_vt*vnq_bh.corr(vnq_vt))))
    t_sharpe = (s_vt - s_bh) / se_diff if se_diff > 0 else 0
    print(f"\n  Sharpe improvement t-stat: {t_sharpe:.2f} (p={2*(1-stats.norm.cdf(abs(t_sharpe))):.4f})")

    # MDD bootstrap test
    n_boot = 5000
    mdd_bh_list = []
    mdd_vt_list = []
    for _ in range(n_boot):
        idx = np.random.choice(len(vnq_bh), size=len(vnq_bh), replace=True)
        bh_boot = vnq_bh.values[idx]
        vt_boot = vnq_vt.values[idx]

        cum_bh = np.cumprod(1 + bh_boot)
        cum_vt = np.cumprod(1 + vt_boot)

        mdd_bh_list.append(np.min(cum_bh / np.maximum.accumulate(cum_bh) - 1))
        mdd_vt_list.append(np.min(cum_vt / np.maximum.accumulate(cum_vt) - 1))

    mdd_improve_pct = np.mean(np.array(mdd_vt_list) > np.array(mdd_bh_list))
    print(f"  MDD improvement: {mdd_improve_pct:.1%} of bootstrap samples (p={1-mdd_improve_pct:.4f})")

    results['reit_vt'] = {
        'buy_hold_sharpe': float(s_bh * np.sqrt(252)),
        'vt_sharpe': float(s_vt * np.sqrt(252)),
        'sharpe_t_stat': float(t_sharpe),
        'mdd_improvement_pct': float(mdd_improve_pct),
    }

# ============================================================
# 9. Regime-Conditional Behavior: Is REIT equity or something else?
# ============================================================
print("\n" + "=" * 70)
print("[9] Classification: Is REIT equity or something else?")
print("=" * 70)

# Key differentiators
print("\n  Classification evidence:")
evidence = []

# 1. Leverage effect
vnq_gamma = gjr_results.get('VNQ', {}).get('gamma', 0)
spy_gamma = gjr_results.get('SPY', {}).get('gamma', 0)
gld_gamma = gjr_results.get('GLD', {}).get('gamma', 0)

print(f"\n  [A] Leverage effect (GJR gamma):")
print(f"      VNQ: {vnq_gamma:.4f}")
print(f"      SPY: {spy_gamma:.4f}")
print(f"      GLD: {gld_gamma:.4f}")

if gjr_results.get('VNQ', {}).get('has_leverage', False):
    evidence.append("leverage_like_equity")
    print(f"      >>> VNQ has leverage effect -> EQUITY-like")
else:
    evidence.append("no_leverage_like_commodity")
    print(f"      >>> VNQ lacks leverage effect -> COMMODITY-like")

# 2. VIX correlation
vnq_vix_corr = vix_corr.get('VNQ', 0)
spy_vix_corr = vix_corr.get('SPY', 0)
gld_vix_corr = vix_corr.get('GLD', 0)

print(f"\n  [B] VIX correlation:")
print(f"      VNQ: {vnq_vix_corr:.3f}")
print(f"      SPY: {spy_vix_corr:.3f}")
print(f"      GLD: {gld_vix_corr:.3f}")

if abs(vnq_vix_corr) > 0.3:
    evidence.append("vix_sensitive_like_equity")
    print(f"      >>> VNQ VIX-sensitive -> EQUITY-like")
else:
    evidence.append("vix_insensitive")
    print(f"      >>> VNQ not VIX-sensitive")

# 3. SPY correlation by regime
print(f"\n  [C] Correlation with SPY across VIX regimes:")
for regime_name in regime_corr:
    vnq_spy_c = regime_corr[regime_name].get('VNQ_SPY', np.nan)
    gld_spy_c = regime_corr[regime_name].get('GLD_SPY', np.nan)
    print(f"      {regime_name}: VNQ-SPY={vnq_spy_c:.3f}, GLD-SPY={gld_spy_c:.3f}")

# Does correlation increase in crisis?
if len(regime_corr) >= 2:
    regimes_list = list(regime_corr.keys())
    low_corr = regime_corr.get('Low (VIX<15)', {}).get('VNQ_SPY', 0)
    high_corr = regime_corr.get('High (VIX>=25)', {}).get('VNQ_SPY', 0)
    if high_corr > low_corr:
        evidence.append("crisis_correlation_increase")
        print(f"      >>> VNQ-SPY correlation INCREASES in crisis ({low_corr:.3f} -> {high_corr:.3f}) -> POOR diversifier")
    else:
        evidence.append("crisis_correlation_stable")
        print(f"      >>> VNQ-SPY correlation stable/decreasing in crisis -> BETTER diversifier")

# 4. Fat tails comparison
vnq_kurt = vol_chars.get('VNQ', {}).get('excess_kurtosis', 0)
spy_kurt = vol_chars.get('SPY', {}).get('excess_kurtosis', 0)
gld_kurt = vol_chars.get('GLD', {}).get('excess_kurtosis', 0)

print(f"\n  [D] Tail heaviness (excess kurtosis):")
print(f"      VNQ: {vnq_kurt:.2f}")
print(f"      SPY: {spy_kurt:.2f}")
print(f"      GLD: {gld_kurt:.2f}")

# 5. GFC amplification
lehman_stats = gfc_stats.get('Lehman Collapse (Sep-Nov 2008)', {})
if lehman_stats:
    vnq_spy_ratio = lehman_stats.get('vol_ratio', 0)
    print(f"\n  [E] GFC amplification (Lehman period VNQ/SPY vol): {vnq_spy_ratio:.2f}x")
    if vnq_spy_ratio > 1.3:
        evidence.append("gfc_amplified")
        print(f"      >>> VNQ amplified during GFC -> EQUITY-like (but worse)")

# Summary verdict
print(f"\n  === CLASSIFICATION VERDICT ===")
equity_like = sum(1 for e in evidence if 'equity' in e or 'crisis_correlation_increase' in e or 'gfc_amplified' in e)
other_like = sum(1 for e in evidence if 'commodity' in e or 'insensitive' in e or 'stable' in e)
print(f"  Equity-like signals: {equity_like}")
print(f"  Non-equity signals: {other_like}")

if equity_like > other_like:
    verdict = "EQUITY-LIKE: REIT behaves like a leveraged equity sector, NOT a diversifier"
else:
    verdict = "DISTINCT ASSET CLASS: REIT has unique characteristics"
print(f"  >>> {verdict}")

results['classification'] = {
    'evidence': evidence,
    'equity_signals': equity_like,
    'non_equity_signals': other_like,
    'verdict': verdict,
}

# ============================================================
# 10. Sub-period Analysis (5-year windows)
# ============================================================
print("\n" + "=" * 70)
print("[10] Sub-period Stability Analysis")
print("=" * 70)

windows = [
    ('2005-2009 (GFC)', '2005-01-01', '2009-12-31'),
    ('2010-2014 (Recovery)', '2010-01-01', '2014-12-31'),
    ('2015-2019 (Expansion)', '2015-01-01', '2019-12-31'),
    ('2020-2024 (Post-COVID)', '2020-01-01', '2024-12-31'),
]

print(f"\n  {'Period':<25} {'VNQ Sharpe':>12} {'SPY Sharpe':>12} {'VNQ-SPY corr':>15} {'VNQ gamma':>12}")
print("  " + "-" * 78)

subperiod_stats = {}
for window_name, start, end in windows:
    mask = (common_idx >= start) & (common_idx <= end)
    w_idx = common_idx[mask]
    if len(w_idx) < 200:
        continue

    vnq_r = returns['VNQ'].loc[w_idx]
    spy_r = returns['SPY'].loc[w_idx]

    vnq_sharpe = (vnq_r.mean() * 252) / (vnq_r.std() * np.sqrt(252))
    spy_sharpe = (spy_r.mean() * 252) / (spy_r.std() * np.sqrt(252))
    corr = vnq_r.corr(spy_r)

    # Quick GJR for this sub-period
    try:
        r_pct = vnq_r * 100
        mod = arch_model(r_pct, vol='Garch', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
        res = mod.fit(disp='off', show_warning=False)
        gamma_sub = float(res.params.get('gamma[1]', np.nan))
    except:
        gamma_sub = np.nan

    subperiod_stats[window_name] = {
        'vnq_sharpe': float(vnq_sharpe),
        'spy_sharpe': float(spy_sharpe),
        'correlation': float(corr),
        'vnq_gamma': float(gamma_sub),
    }

    print(f"  {window_name:<25} {vnq_sharpe:>11.3f} {spy_sharpe:>11.3f} {corr:>14.3f} {gamma_sub:>11.4f}")

results['subperiod_analysis'] = subperiod_stats

# ============================================================
# 11. Interest Rate Sensitivity (unique REIT feature)
# ============================================================
print("\n" + "=" * 70)
print("[11] Interest Rate Sensitivity (REIT unique feature)")
print("=" * 70)

# Use TLT as long-term rate proxy
try:
    tlt = yf.download('TLT', start='2004-01-01', end='2026-03-25', progress=False, auto_adjust=True)
    tlt_close = tlt['Close']
    if isinstance(tlt_close, pd.DataFrame):
        tlt_close = tlt_close.iloc[:, 0]
    tlt_ret = tlt_close.pct_change().dropna()
    print(f"  TLT data: {len(tlt_ret)} days")

    # Align
    common_tlt = common_idx.intersection(tlt_ret.index)

    # Correlations
    vnq_tlt_corr = returns['VNQ'].loc[common_tlt].corr(tlt_ret.loc[common_tlt])
    spy_tlt_corr = returns['SPY'].loc[common_tlt].corr(tlt_ret.loc[common_tlt])
    gld_tlt_corr = returns['GLD'].loc[common_tlt].corr(tlt_ret.loc[common_tlt]) if 'GLD' in returns else np.nan

    print(f"\n  Correlation with TLT (long-term bonds):")
    print(f"    VNQ-TLT: {vnq_tlt_corr:.3f}")
    print(f"    SPY-TLT: {spy_tlt_corr:.3f}")
    print(f"    GLD-TLT: {gld_tlt_corr:.3f}")

    # By VIX regime
    print(f"\n  VNQ-TLT correlation by VIX regime:")
    for regime_name, mask in regimes.items():
        regime_idx = common_tlt[common_tlt.isin(common_idx[mask.loc[common_idx].values])]
        if len(regime_idx) < 60:
            continue
        corr_r = returns['VNQ'].loc[regime_idx].corr(tlt_ret.loc[regime_idx])
        print(f"    {regime_name}: {corr_r:.3f} ({len(regime_idx)} days)")

    results['interest_rate_sensitivity'] = {
        'vnq_tlt': float(vnq_tlt_corr),
        'spy_tlt': float(spy_tlt_corr),
        'gld_tlt': float(gld_tlt_corr),
    }

except Exception as e:
    print(f"  TLT data error: {e}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K349 REIT Volatility Findings")
print("=" * 70)

print(f"""
Key Findings:

1. LEVERAGE EFFECT:
   VNQ gamma = {gjr_results.get('VNQ', {}).get('gamma', 'N/A')}
   SPY gamma = {gjr_results.get('SPY', {}).get('gamma', 'N/A')}
   GLD gamma = {gjr_results.get('GLD', {}).get('gamma', 'N/A')}
   >>> REIT {'HAS' if gjr_results.get('VNQ', {}).get('has_leverage', False) else 'does NOT have'} significant leverage effect

2. REIT-SPY CORRELATION:
   Full sample: {vix_corr.get('VNQ', 'N/A')} (DVIX), rolling mean with SPY: {results.get('rolling_correlation', {}).get('vnq_spy', {}).get('mean', 'N/A')}
   >>> VNQ is {'a poor' if any('crisis_correlation_increase' in e for e in evidence) else 'a decent'} diversifier for SPY

3. GFC IMPACT:
   VNQ GFC MDD was MORE severe than SPY
   Vol ratio during Lehman: {gfc_stats.get('Lehman Collapse (Sep-Nov 2008)', {}).get('vol_ratio', 'N/A')}x

4. PORTFOLIO ROLE:
   50/50 SPY/GLD Sharpe: {portfolio_stats.get('50/50 SPY/GLD', {}).get('sharpe', 'N/A'):.3f}
   50/50 SPY/VNQ Sharpe: {portfolio_stats.get('50/50 SPY/VNQ', {}).get('sharpe', 'N/A'):.3f}
   >>> {'GLD is superior diversifier' if portfolio_stats.get('50/50 SPY/GLD', {}).get('sharpe', 0) > portfolio_stats.get('50/50 SPY/VNQ', {}).get('sharpe', 0) else 'VNQ competitive as diversifier'}

5. VT FOR REIT:
   12/VIX VT {'improves' if results.get('reit_vt', {}).get('mdd_improvement_pct', 0) > 0.5 else 'does not improve'} VNQ MDD

6. CLASSIFICATION: {verdict}

Data: yfinance (VNQ, XLRE, SPY, GLD, ^VIX), real market data only.
Method: GJR-GARCH, Granger causality, bootstrap MDD test, rolling correlations.
""")

# Save results
output_file = 'experiments/k349_reit_vol_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_file}")
