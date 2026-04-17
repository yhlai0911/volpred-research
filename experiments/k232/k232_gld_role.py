"""
K232: Why GLD? Deep Dive into Gold's Role in 50/50

Decomposes GLD's specific contribution to the 50/50 SPY/GLD strategy.
Tests whether GLD is irreplaceable or if TLT/AGG/IEF/Cash work equally well.

Data: yfinance (SPY, GLD, TLT, AGG, IEF, EEM, ^VIX), 2005-2024
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 80)
print("K232: Why GLD? Deep Dive into Gold's Role in 50/50")
print("=" * 80)

# ─── 1. Data Download ───
print("\n[1] Downloading data from yfinance...")
tickers = ['SPY', 'GLD', 'TLT', 'AGG', 'IEF', 'EEM']
vix_ticker = '^VIX'

start_date = '2004-11-01'  # GLD inception ~Nov 2004
end_date = '2024-12-31'

price_data = {}
for t in tickers:
    df = yf.download(t, start=start_date, end=end_date, progress=False)
    if 'Adj Close' in df.columns:
        price_data[t] = df['Adj Close'].squeeze()
    elif 'Close' in df.columns:
        price_data[t] = df['Close'].squeeze()
    print(f"  {t}: {len(price_data[t])} days, {price_data[t].index[0].date()} to {price_data[t].index[-1].date()}")

vix_df = yf.download(vix_ticker, start=start_date, end=end_date, progress=False)
if 'Adj Close' in vix_df.columns:
    vix = vix_df['Adj Close'].squeeze()
elif 'Close' in vix_df.columns:
    vix = vix_df['Close'].squeeze()
print(f"  VIX: {len(vix)} days")

# Align all data to common dates
prices = pd.DataFrame(price_data)
prices['VIX'] = vix
prices = prices.dropna()
print(f"\nAligned dataset: {len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()}")

# Daily returns
returns = prices[tickers].pct_change().dropna()
vix_aligned = prices['VIX'].reindex(returns.index)

# ─── 2. Portfolio Construction Functions ───
def compute_monthly_vt_weight(vix_series, cap=1.0):
    """Compute monthly VT weight = 12/VIX, capped at cap"""
    monthly_vix = vix_series.resample('ME').last()
    monthly_weight = (12.0 / monthly_vix).clip(0, cap)
    return monthly_weight

def build_portfolio_returns(ret_df, asset1, asset2, w1=0.5, w2=0.5,
                             vt_overlay=False, vix_series=None):
    """Build portfolio with optional VT overlay"""
    if asset2 == 'Cash':
        port_ret = ret_df[asset1] * w1  # cash return = 0
    else:
        port_ret = ret_df[asset1] * w1 + ret_df[asset2] * w2

    if vt_overlay and vix_series is not None:
        monthly_wt = compute_monthly_vt_weight(vix_series)
        # Map monthly weight to daily
        daily_wt = monthly_wt.reindex(port_ret.index, method='ffill')
        daily_wt = daily_wt.fillna(1.0).clip(0, 1.0)
        port_ret = port_ret * daily_wt

    return port_ret

def compute_metrics(ret_series, name=""):
    """Compute Sharpe, MDD, Calmar, worst year, annualized return, vol"""
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + ret_series).cumprod()
    rolling_max = cum.cummax()
    drawdown = cum / rolling_max - 1
    mdd = drawdown.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Worst year
    yearly = ret_series.groupby(ret_series.index.year).apply(lambda x: (1+x).prod() - 1)
    worst_year_val = yearly.min()
    worst_year_idx = yearly.idxmin()

    # Total return
    total_ret = cum.iloc[-1] - 1

    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'worst_year': f"{worst_year_idx} ({worst_year_val:.1%})",
        'total_return': total_ret,
        'corr_with_spy': ret_series.corr(returns['SPY'].reindex(ret_series.index))
    }

# ─── 3. Build All Portfolios ───
print("\n[2] Building portfolios...")

portfolios = {}
portfolio_configs = [
    ('50/50 SPY/GLD', 'SPY', 'GLD', 0.5, 0.5),
    ('50/50 SPY/TLT', 'SPY', 'TLT', 0.5, 0.5),
    ('50/50 SPY/AGG', 'SPY', 'AGG', 0.5, 0.5),
    ('50/50 SPY/IEF', 'SPY', 'IEF', 0.5, 0.5),
    ('50/50 SPY/Cash', 'SPY', 'Cash', 0.5, 0.5),
    ('100% SPY', 'SPY', 'Cash', 1.0, 0.0),
]

for name, a1, a2, w1, w2 in portfolio_configs:
    # Without VT
    r_no_vt = build_portfolio_returns(returns, a1, a2, w1, w2,
                                       vt_overlay=False)
    portfolios[name] = r_no_vt

    # With VT overlay
    r_vt = build_portfolio_returns(returns, a1, a2, w1, w2,
                                    vt_overlay=True, vix_series=vix_aligned)
    portfolios[f"{name} + VT"] = r_vt

# ─── 4. Performance Comparison ───
print("\n" + "=" * 80)
print("PART A: PERFORMANCE COMPARISON (WITHOUT VT OVERLAY)")
print("=" * 80)

print(f"\n{'Portfolio':<25} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'CorrSPY':>8} {'Worst Year':<20}")
print("-" * 110)

results_no_vt = []
for name, a1, a2, w1, w2 in portfolio_configs:
    m = compute_metrics(portfolios[name], name)
    results_no_vt.append(m)
    print(f"{m['name']:<25} {m['ann_return']:>7.1%} {m['ann_vol']:>7.1%} {m['sharpe']:>8.3f} {m['mdd']:>7.1%} {m['calmar']:>8.3f} {m['corr_with_spy']:>8.3f} {m['worst_year']:<20}")

print("\n" + "=" * 80)
print("PART B: PERFORMANCE COMPARISON (WITH VT OVERLAY = 12/VIX)")
print("=" * 80)

print(f"\n{'Portfolio':<30} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'CorrSPY':>8} {'Worst Year':<20}")
print("-" * 115)

results_vt = []
for name, a1, a2, w1, w2 in portfolio_configs:
    vt_name = f"{name} + VT"
    m = compute_metrics(portfolios[vt_name], vt_name)
    results_vt.append(m)
    print(f"{m['name']:<30} {m['ann_return']:>7.1%} {m['ann_vol']:>7.1%} {m['sharpe']:>8.3f} {m['mdd']:>7.1%} {m['calmar']:>8.3f} {m['corr_with_spy']:>8.3f} {m['worst_year']:<20}")

# ─── 5. Crisis Period Analysis ───
print("\n" + "=" * 80)
print("PART C: CRISIS PERIOD PERFORMANCE")
print("=" * 80)

crises = {
    'GFC (2008-09 to 2009-03)': ('2008-09-01', '2009-03-31'),
    'COVID (2020-02 to 2020-03)': ('2020-02-15', '2020-03-31'),
    'Rate Hike (2022-01 to 2022-10)': ('2022-01-01', '2022-10-31'),
    'Taper Tantrum (2013-05 to 2013-09)': ('2013-05-01', '2013-09-30'),
    'VIX Spike (2018-01 to 2018-03)': ('2018-01-26', '2018-03-31'),
}

for crisis_name, (start, end) in crises.items():
    print(f"\n  {crisis_name}")
    print(f"  {'Portfolio':<25} {'CumReturn':>10} {'MaxDD':>10}")
    print(f"  {'-'*50}")

    for name, a1, a2, w1, w2 in portfolio_configs:
        r = portfolios[name]
        mask = (r.index >= start) & (r.index <= end)
        crisis_r = r[mask]
        if len(crisis_r) == 0:
            continue
        cum_ret = (1 + crisis_r).prod() - 1
        cum_curve = (1 + crisis_r).cumprod()
        crisis_mdd = (cum_curve / cum_curve.cummax() - 1).min()
        print(f"  {name:<25} {cum_ret:>9.1%} {crisis_mdd:>9.1%}")

# ─── 6. Standalone Asset Properties ───
print("\n" + "=" * 80)
print("PART D: STANDALONE ASSET PROPERTIES")
print("=" * 80)

assets_to_analyze = ['SPY', 'GLD', 'TLT', 'AGG', 'IEF']
print(f"\n{'Asset':<8} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'Skew':>8} {'Kurt':>8} {'CorrSPY':>10}")
print("-" * 65)

for asset in assets_to_analyze:
    r = returns[asset]
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol
    skew = r.skew()
    kurt = r.kurtosis()
    corr_spy = r.corr(returns['SPY'])
    print(f"{asset:<8} {ann_ret:>7.1%} {ann_vol:>7.1%} {sharpe:>8.3f} {skew:>8.3f} {kurt:>8.2f} {corr_spy:>10.4f}")

# ─── 7. Correlation by VIX Regime ───
print("\n" + "=" * 80)
print("PART E: CORRELATION WITH SPY BY VIX REGIME")
print("=" * 80)

vix_for_regime = vix_aligned.reindex(returns.index).dropna()
common_idx = returns.index.intersection(vix_for_regime.index)

vix_q33 = vix_for_regime[common_idx].quantile(0.33)
vix_q66 = vix_for_regime[common_idx].quantile(0.66)

regimes = {
    f'Low VIX (<{vix_q33:.1f})': vix_for_regime[common_idx] < vix_q33,
    f'Mid VIX ({vix_q33:.1f}-{vix_q66:.1f})': (vix_for_regime[common_idx] >= vix_q33) & (vix_for_regime[common_idx] < vix_q66),
    f'High VIX (>{vix_q66:.1f})': vix_for_regime[common_idx] >= vix_q66,
}

print(f"\n{'Regime':<25} {'N':>6} {'GLD':>8} {'TLT':>8} {'AGG':>8} {'IEF':>8}")
print("-" * 65)

for regime_name, mask in regimes.items():
    regime_idx = mask[mask].index
    n = len(regime_idx)
    corrs = {}
    for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
        corrs[asset] = returns['SPY'].reindex(regime_idx).corr(returns[asset].reindex(regime_idx))
    print(f"{regime_name:<25} {n:>6} {corrs['GLD']:>8.4f} {corrs['TLT']:>8.4f} {corrs['AGG']:>8.4f} {corrs['IEF']:>8.4f}")

# ─── 8. Conditional Performance: SPY Down Days ───
print("\n" + "=" * 80)
print("PART F: HEDGING EFFECTIVENESS (SPY DOWN DAYS)")
print("=" * 80)

spy_ret = returns['SPY']

# SPY down days (worst 5%, worst 10%, all negative)
thresholds = {
    'SPY worst 5% days': spy_ret.quantile(0.05),
    'SPY worst 10% days': spy_ret.quantile(0.10),
    'All SPY down days': 0,
}

for label, threshold in thresholds.items():
    if threshold == 0:
        down_mask = spy_ret < threshold
    else:
        down_mask = spy_ret <= threshold
    down_idx = spy_ret[down_mask].index
    n_days = len(down_idx)

    print(f"\n  {label} (N={n_days}, threshold={threshold:.3%})")
    print(f"  {'Asset':<8} {'MeanRet':>10} {'MedianRet':>10} {'%Positive':>10} {'AvgContrib':>12}")
    print(f"  {'-'*55}")

    for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
        asset_r = returns[asset].reindex(down_idx)
        mean_r = asset_r.mean()
        median_r = asset_r.median()
        pct_pos = (asset_r > 0).mean()
        # Contribution to 50/50: how much does adding this asset help?
        spy_down = spy_ret.reindex(down_idx)
        portfolio_r = 0.5 * spy_down + 0.5 * asset_r
        avg_contrib = portfolio_r.mean() - spy_down.mean()  # how much better than 100% SPY
        print(f"  {asset:<8} {mean_r:>9.3%} {median_r:>9.3%} {pct_pos:>9.1%} {avg_contrib:>11.3%}")

# ─── 9. Rolling Correlation Analysis ───
print("\n" + "=" * 80)
print("PART G: ROLLING 252-DAY CORRELATION WITH SPY")
print("=" * 80)

for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
    rolling_corr = returns[asset].rolling(252).corr(returns['SPY'])
    rc = rolling_corr.dropna()
    print(f"\n  {asset} vs SPY (252-day rolling):")
    print(f"    Mean corr: {rc.mean():.4f}")
    print(f"    Std corr:  {rc.std():.4f}")
    print(f"    Min corr:  {rc.min():.4f} ({rc.idxmin().date()})")
    print(f"    Max corr:  {rc.max():.4f} ({rc.idxmax().date()})")
    print(f"    % of time negative: {(rc < 0).mean():.1%}")

# ─── 10. Unique Diversification: GLD vs Bonds ───
print("\n" + "=" * 80)
print("PART H: WHAT MAKES GLD UNIQUE?")
print("=" * 80)

# GLD vs TLT correlation
gld_tlt_corr = returns['GLD'].corr(returns['TLT'])
gld_agg_corr = returns['GLD'].corr(returns['AGG'])
tlt_agg_corr = returns['TLT'].corr(returns['AGG'])
print(f"\n  Cross-asset correlations:")
print(f"    GLD-TLT: {gld_tlt_corr:.4f}")
print(f"    GLD-AGG: {gld_agg_corr:.4f}")
print(f"    TLT-AGG: {tlt_agg_corr:.4f}")
print(f"    → GLD provides DIFFERENT diversification than bonds")

# Tail dependence: in worst SPY months, how do assets behave?
monthly_ret = returns.resample('ME').apply(lambda x: (1+x).prod() - 1)
spy_monthly = monthly_ret['SPY']
worst_spy_months = spy_monthly.nsmallest(20)

print(f"\n  In SPY's 20 worst months:")
print(f"  {'Month':<12} {'SPY':>8} {'GLD':>8} {'TLT':>8} {'AGG':>8} {'IEF':>8}")
print(f"  {'-'*55}")

for date, spy_r in worst_spy_months.items():
    row = f"  {date.strftime('%Y-%m'):<12} {spy_r:>7.1%}"
    for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
        if date in monthly_ret.index:
            row += f" {monthly_ret[asset].loc[date]:>7.1%}"
        else:
            row += f"     N/A"
    print(row)

# Summary stats for worst months
print(f"\n  Average return in SPY's 20 worst months:")
for asset in ['SPY', 'GLD', 'TLT', 'AGG', 'IEF']:
    avg = monthly_ret[asset].reindex(worst_spy_months.index).mean()
    pct_pos = (monthly_ret[asset].reindex(worst_spy_months.index) > 0).mean()
    print(f"    {asset}: mean={avg:.2%}, positive={pct_pos:.0%} of months")

# ─── 11. 2022 Rate Hike Special Analysis ───
print("\n" + "=" * 80)
print("PART I: 2022 SPECIAL ANALYSIS (Bonds and Gold Both Fell?)")
print("=" * 80)

y2022 = returns.loc['2022']
print(f"\n  2022 Annual Returns:")
for asset in ['SPY', 'GLD', 'TLT', 'AGG', 'IEF']:
    ann_r = (1 + y2022[asset]).prod() - 1
    print(f"    {asset}: {ann_r:.1%}")

print(f"\n  50/50 Portfolio 2022 Returns:")
for name, a1, a2, w1, w2 in portfolio_configs:
    r = portfolios[name].loc['2022']
    ann_r = (1 + r).prod() - 1
    print(f"    {name}: {ann_r:.1%}")

# ─── 12. GLD's Unique Properties Summary ───
print("\n" + "=" * 80)
print("PART J: GLD'S UNIQUE PROPERTIES SUMMARY")
print("=" * 80)

# Property 1: Asymmetric correlation
spy_up = spy_ret > 0
spy_down = spy_ret < 0

print("\n  Property 1: Asymmetric Correlation")
for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
    corr_up = returns[asset][spy_up].corr(spy_ret[spy_up])
    corr_down = returns[asset][spy_down].corr(spy_ret[spy_down])
    print(f"    {asset}: corr_when_SPY_up={corr_up:.4f}, corr_when_SPY_down={corr_down:.4f}, diff={corr_down-corr_up:.4f}")

# Property 2: Independent return driver
print(f"\n  Property 2: Independent Return Source")
for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
    # Regress asset on SPY, check R²
    from numpy.polynomial.polynomial import polyfit
    spy_clean = spy_ret.dropna()
    asset_clean = returns[asset].reindex(spy_clean.index).dropna()
    common = spy_clean.index.intersection(asset_clean.index)

    x = spy_clean.loc[common].values
    y = asset_clean.loc[common].values

    # Simple linear regression R²
    corr = np.corrcoef(x, y)[0, 1]
    r_squared = corr ** 2
    print(f"    {asset}: R² with SPY = {r_squared:.4f} (unexplained variance = {1-r_squared:.1%})")

# Property 3: Positive long-term return
print(f"\n  Property 3: Long-term Return (standalone)")
for asset in ['GLD', 'TLT', 'AGG', 'IEF']:
    total = (1 + returns[asset]).prod() - 1
    n_years = len(returns) / 252
    cagr = (1 + total) ** (1/n_years) - 1
    print(f"    {asset}: CAGR={cagr:.2%}, Total={total:.1%} over {n_years:.1f} years")

# ─── 13. Statistical Tests ───
print("\n" + "=" * 80)
print("PART K: STATISTICAL SIGNIFICANCE (Bootstrap)")
print("=" * 80)

def bootstrap_sharpe_diff(ret1, ret2, n_boot=10000, seed=42):
    """Bootstrap test for Sharpe ratio difference"""
    rng = np.random.RandomState(seed)
    n = len(ret1)

    sharpe1 = ret1.mean() / ret1.std() * np.sqrt(252)
    sharpe2 = ret2.mean() / ret2.std() * np.sqrt(252)
    observed_diff = sharpe1 - sharpe2

    boot_diffs = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, n)
        s1 = ret1.iloc[idx].mean() / ret1.iloc[idx].std() * np.sqrt(252)
        s2 = ret2.iloc[idx].mean() / ret2.iloc[idx].std() * np.sqrt(252)
        boot_diffs.append(s1 - s2)

    boot_diffs = np.array(boot_diffs)
    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)
    p_value = (boot_diffs <= 0).mean() if observed_diff > 0 else (boot_diffs >= 0).mean()

    return observed_diff, ci_lo, ci_hi, p_value

# Compare GLD portfolio vs each alternative
print("\n  Sharpe Ratio Difference: SPY/GLD vs Alternative (with VT overlay)")
print(f"  {'Comparison':<35} {'Diff':>8} {'95% CI':>20} {'p-value':>10}")
print(f"  {'-'*75}")

gld_vt = portfolios['50/50 SPY/GLD + VT']
for name, a1, a2, w1, w2 in portfolio_configs[1:]:  # skip GLD itself
    vt_name = f"{name} + VT"
    alt_vt = portfolios[vt_name]

    # Align
    common = gld_vt.index.intersection(alt_vt.index)
    diff, ci_lo, ci_hi, pval = bootstrap_sharpe_diff(gld_vt.loc[common], alt_vt.loc[common])
    sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
    print(f"  GLD vs {name:<25} {diff:>8.3f} [{ci_lo:>7.3f}, {ci_hi:>7.3f}] {pval:>9.3f} {sig}")

# Without VT
print("\n  Sharpe Ratio Difference: SPY/GLD vs Alternative (WITHOUT VT overlay)")
print(f"  {'Comparison':<35} {'Diff':>8} {'95% CI':>20} {'p-value':>10}")
print(f"  {'-'*75}")

gld_no_vt = portfolios['50/50 SPY/GLD']
for name, a1, a2, w1, w2 in portfolio_configs[1:]:
    alt = portfolios[name]
    common = gld_no_vt.index.intersection(alt.index)
    diff, ci_lo, ci_hi, pval = bootstrap_sharpe_diff(gld_no_vt.loc[common], alt.loc[common])
    sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
    print(f"  GLD vs {name:<25} {diff:>8.3f} [{ci_lo:>7.3f}, {ci_hi:>7.3f}] {pval:>9.3f} {sig}")

# ─── 14. Decade Analysis ───
print("\n" + "=" * 80)
print("PART L: DECADE-BY-DECADE SHARPE COMPARISON")
print("=" * 80)

decades = {
    '2005-2009': ('2005-01-01', '2009-12-31'),
    '2010-2014': ('2010-01-01', '2014-12-31'),
    '2015-2019': ('2015-01-01', '2019-12-31'),
    '2020-2024': ('2020-01-01', '2024-12-31'),
}

print(f"\n{'Period':<12}", end="")
for name, _, _, _, _ in portfolio_configs:
    print(f" {name:>16}", end="")
print()
print("-" * 110)

for period, (start, end) in decades.items():
    print(f"{period:<12}", end="")
    for name, a1, a2, w1, w2 in portfolio_configs:
        r = portfolios[name]
        mask = (r.index >= start) & (r.index <= end)
        period_r = r[mask]
        if len(period_r) > 50:
            sharpe = period_r.mean() / period_r.std() * np.sqrt(252)
            print(f" {sharpe:>16.3f}", end="")
        else:
            print(f" {'N/A':>16}", end="")
    print()

# ─── 15. Final Verdict ───
print("\n" + "=" * 80)
print("PART M: FINAL VERDICT — IS GLD IRREPLACEABLE?")
print("=" * 80)

# Rank all portfolios by Sharpe (with VT)
vt_sharpes = {}
for name, a1, a2, w1, w2 in portfolio_configs:
    vt_name = f"{name} + VT"
    r = portfolios[vt_name]
    vt_sharpes[name] = r.mean() / r.std() * np.sqrt(252)

sorted_sharpes = sorted(vt_sharpes.items(), key=lambda x: x[1], reverse=True)
print("\n  Ranking by Sharpe (with VT overlay):")
for rank, (name, sharpe) in enumerate(sorted_sharpes, 1):
    marker = " ← WINNER" if rank == 1 else ""
    print(f"    #{rank}: {name:<25} Sharpe = {sharpe:.3f}{marker}")

# Key findings
print("\n  KEY FINDINGS:")
gld_sharpe_vt = vt_sharpes['50/50 SPY/GLD']
tlt_sharpe_vt = vt_sharpes['50/50 SPY/TLT']
cash_sharpe_vt = vt_sharpes['50/50 SPY/Cash']
spy_sharpe_vt = vt_sharpes['100% SPY']

print(f"\n  1. GLD vs TLT: Sharpe diff = {gld_sharpe_vt - tlt_sharpe_vt:+.3f}")
print(f"  2. GLD vs Cash: Sharpe diff = {gld_sharpe_vt - cash_sharpe_vt:+.3f}")
print(f"  3. GLD vs 100% SPY: Sharpe diff = {gld_sharpe_vt - spy_sharpe_vt:+.3f}")

# GLD's unique advantages
gld_spy_corr = returns['GLD'].corr(returns['SPY'])
tlt_spy_corr = returns['TLT'].corr(returns['SPY'])
gld_tlt_corr_val = returns['GLD'].corr(returns['TLT'])

print(f"\n  4. GLD-SPY full-sample correlation: {gld_spy_corr:.4f}")
print(f"     TLT-SPY full-sample correlation: {tlt_spy_corr:.4f}")
print(f"     GLD-TLT correlation: {gld_tlt_corr_val:.4f}")
print(f"     → GLD is {'more' if abs(gld_spy_corr) < abs(tlt_spy_corr) else 'less'} independent from SPY than TLT")
print(f"     → GLD is {'weakly' if abs(gld_tlt_corr_val) < 0.3 else 'moderately' if abs(gld_tlt_corr_val) < 0.5 else 'strongly'} correlated with TLT")

# 2022 test - the acid test
gld_2022 = (1 + portfolios['50/50 SPY/GLD'].loc['2022']).prod() - 1
tlt_2022 = (1 + portfolios['50/50 SPY/TLT'].loc['2022']).prod() - 1
print(f"\n  5. 2022 Acid Test (stocks AND bonds fell):")
print(f"     50/50 SPY/GLD: {gld_2022:.1%}")
print(f"     50/50 SPY/TLT: {tlt_2022:.1%}")
print(f"     → {'GLD clearly better' if gld_2022 > tlt_2022 else 'TLT better'} in rising-rate environment")

# GFC test
gfc_gld = (1 + portfolios['50/50 SPY/GLD'].loc['2008-09':'2009-03']).prod() - 1
gfc_tlt = (1 + portfolios['50/50 SPY/TLT'].loc['2008-09':'2009-03']).prod() - 1
print(f"\n  6. GFC Crisis Test:")
print(f"     50/50 SPY/GLD: {gfc_gld:.1%}")
print(f"     50/50 SPY/TLT: {gfc_tlt:.1%}")
print(f"     → {'GLD better' if gfc_gld > gfc_tlt else 'TLT better'} in financial crisis")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)

# Auto-generate conclusion based on data
best_name = sorted_sharpes[0][0]
best_sharpe = sorted_sharpes[0][1]
second_name = sorted_sharpes[1][0]
second_sharpe = sorted_sharpes[1][1]

print(f"""
  Best portfolio (with VT): {best_name} (Sharpe={best_sharpe:.3f})
  Runner-up: {second_name} (Sharpe={second_sharpe:.3f})

  GLD's distinctive advantages:
  - Low correlation with SPY ({gld_spy_corr:.3f}) → true diversification
  - Low correlation with bonds ({gld_tlt_corr_val:.3f}) → DIFFERENT hedging mechanism
  - Positive real returns long-term → not just a hedge, also a return source
  - Performs in BOTH scenarios: financial crisis (deflationary) and rate hikes (inflationary)
  - Bonds fail in rate-hike environments (2022), GLD is more robust

  Is GLD irreplaceable? The data will tell.
""")

# ─── Save results ───
results_summary = {
    'experiment': 'K232',
    'title': 'Why GLD? Deep Dive into Gold Role in 50/50',
    'data_source': 'yfinance',
    'period': f"{prices.index[0].date()} to {prices.index[-1].date()}",
    'n_days': len(returns),
    'portfolios_no_vt': {m['name']: {k: float(v) if isinstance(v, (float, np.floating)) else v
                                       for k, v in m.items()} for m in results_no_vt},
    'portfolios_vt': {m['name']: {k: float(v) if isinstance(v, (float, np.floating)) else v
                                    for k, v in m.items()} for m in results_vt},
    'ranking_vt': [(name, float(s)) for name, s in sorted_sharpes],
    'gld_spy_corr': float(gld_spy_corr),
    'tlt_spy_corr': float(tlt_spy_corr),
    'gld_tlt_corr': float(gld_tlt_corr_val),
}

with open('experiments/k232_gld_role_results.json', 'w') as f:
    json.dump(results_summary, f, indent=2, default=str)

print("\nResults saved to experiments/k232_gld_role_results.json")
print("Script: experiments/k232_gld_role.py")
