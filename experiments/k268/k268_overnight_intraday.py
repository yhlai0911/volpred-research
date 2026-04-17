"""
K268: Overnight vs Intraday Return Decomposition for Portfolio Construction

Background:
- K156/K187 found overnight gaps = 50% of daily variance
- K196 confirmed RV AC=0.414 vs c2c AC=-0.118
- Question: Can separating overnight and intraday returns improve portfolio construction?

Data: SPY, GLD, TLT daily OHLC from yfinance, 2005-2024
Method: Decompose daily returns into overnight (close-to-open) and intraday (open-to-close)

[提出: Claude, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K268: Overnight vs Intraday Return Decomposition")
print("=" * 70)

assets = ['SPY', 'GLD', 'TLT']
start_date = '2005-01-01'
end_date = '2024-12-31'

data = {}
for asset in assets:
    print(f"\nDownloading {asset} from yfinance...")
    df = yf.download(asset, start=start_date, end=end_date, auto_adjust=False, progress=False)
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[asset] = df[['Open', 'High', 'Low', 'Close', 'Adj Close']].copy()
    print(f"  {asset}: {len(df)} trading days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align dates across all assets
common_idx = data['SPY'].index
for asset in assets:
    common_idx = common_idx.intersection(data[asset].index)

print(f"\nCommon trading days: {len(common_idx)}")
for asset in assets:
    data[asset] = data[asset].loc[common_idx]

# ============================================================
# 2. Return Decomposition
# ============================================================
print("\n" + "=" * 70)
print("SECTION 2: Return Decomposition")
print("=" * 70)

returns = {}
for asset in assets:
    df = data[asset]
    # Use Adj Close for total return (accounts for dividends/splits)
    adj_factor = df['Adj Close'] / df['Close']

    # Overnight: Open_t / Close_{t-1} - 1
    # We use raw prices here since overnight gap is between close and next open
    overnight = df['Open'].values[1:] / df['Close'].values[:-1] - 1

    # Intraday: Close_t / Open_t - 1
    intraday = df['Close'].values[1:] / df['Open'].values[1:] - 1

    # Total: Close_t / Close_{t-1} - 1 (using Adj Close for dividend adjustment)
    total = df['Adj Close'].values[1:] / df['Adj Close'].values[:-1] - 1

    idx = df.index[1:]
    returns[asset] = pd.DataFrame({
        'overnight': overnight,
        'intraday': intraday,
        'total': total,
    }, index=idx)

# ============================================================
# 3. Descriptive Statistics per Component
# ============================================================
print("\n" + "=" * 70)
print("SECTION 3: Descriptive Statistics")
print("=" * 70)

results_stats = {}
for asset in assets:
    r = returns[asset]
    stats = {}
    for comp in ['overnight', 'intraday', 'total']:
        s = r[comp]
        ann_mean = s.mean() * 252
        ann_vol = s.std() * np.sqrt(252)
        sharpe = ann_mean / ann_vol if ann_vol > 0 else 0
        skew = s.skew()
        kurt = s.kurtosis()

        # Variance contribution
        var_contrib = s.var() / r['total'].var() if r['total'].var() > 0 else 0

        stats[comp] = {
            'ann_mean_pct': round(ann_mean * 100, 3),
            'ann_vol_pct': round(ann_vol * 100, 3),
            'sharpe': round(sharpe, 4),
            'skewness': round(skew, 4),
            'kurtosis': round(kurt, 4),
            'var_contribution': round(var_contrib, 4),
            'n_obs': len(s),
        }
    results_stats[asset] = stats

print(f"\n{'Asset':<6} {'Component':<12} {'Ann Mean%':>10} {'Ann Vol%':>10} {'Sharpe':>8} {'Skew':>8} {'Kurt':>8} {'VarCont':>8}")
print("-" * 78)
for asset in assets:
    for comp in ['overnight', 'intraday', 'total']:
        s = results_stats[asset][comp]
        print(f"{asset:<6} {comp:<12} {s['ann_mean_pct']:>10.3f} {s['ann_vol_pct']:>10.3f} {s['sharpe']:>8.4f} {s['skewness']:>8.4f} {s['kurtosis']:>8.4f} {s['var_contribution']:>8.4f}")
    print()

# ============================================================
# 4. Cross-Asset Correlations: Overnight vs Intraday
# ============================================================
print("=" * 70)
print("SECTION 4: Cross-Asset Correlations by Component")
print("=" * 70)

pairs = [('SPY', 'GLD'), ('SPY', 'TLT'), ('GLD', 'TLT')]
corr_results = {}

for a1, a2 in pairs:
    pair_key = f"{a1}-{a2}"
    corr_results[pair_key] = {}
    for comp in ['overnight', 'intraday', 'total']:
        corr = returns[a1][comp].corr(returns[a2][comp])
        corr_results[pair_key][comp] = round(corr, 4)

print(f"\n{'Pair':<12} {'Overnight':>12} {'Intraday':>12} {'Total':>12} {'Diff(ON-ID)':>12}")
print("-" * 62)
for pair_key in corr_results:
    c = corr_results[pair_key]
    diff = c['overnight'] - c['intraday']
    print(f"{pair_key:<12} {c['overnight']:>12.4f} {c['intraday']:>12.4f} {c['total']:>12.4f} {diff:>12.4f}")

# ============================================================
# 5. Statistical Tests: Are overnight/intraday means different?
# ============================================================
print("\n" + "=" * 70)
print("SECTION 5: Mean Return Tests (overnight vs intraday)")
print("=" * 70)

from scipy import stats as sp_stats

mean_tests = {}
for asset in assets:
    r = returns[asset]
    on = r['overnight']
    id_ = r['intraday']

    # Two-sample t-test (unequal variance)
    t_stat, p_val = sp_stats.ttest_ind(on, id_, equal_var=False)

    mean_tests[asset] = {
        'on_mean_ann_pct': round(on.mean() * 252 * 100, 3),
        'id_mean_ann_pct': round(id_.mean() * 252 * 100, 3),
        'diff_ann_pct': round((on.mean() - id_.mean()) * 252 * 100, 3),
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 6),
    }

    print(f"\n{asset}:")
    print(f"  Overnight ann mean: {mean_tests[asset]['on_mean_ann_pct']:.3f}%")
    print(f"  Intraday ann mean:  {mean_tests[asset]['id_mean_ann_pct']:.3f}%")
    print(f"  Difference:         {mean_tests[asset]['diff_ann_pct']:.3f}%")
    print(f"  t-statistic:        {mean_tests[asset]['t_stat']:.4f}")
    print(f"  p-value:            {mean_tests[asset]['p_value']:.6f}")

# ============================================================
# 6. Rolling Correlation Analysis (252-day window)
# ============================================================
print("\n" + "=" * 70)
print("SECTION 6: Rolling Correlation Stability (252-day window)")
print("=" * 70)

window = 252
rolling_corr_stats = {}
for a1, a2 in pairs:
    pair_key = f"{a1}-{a2}"
    rolling_corr_stats[pair_key] = {}
    for comp in ['overnight', 'intraday', 'total']:
        rc = returns[a1][comp].rolling(window).corr(returns[a2][comp]).dropna()
        rolling_corr_stats[pair_key][comp] = {
            'mean': round(rc.mean(), 4),
            'std': round(rc.std(), 4),
            'min': round(rc.min(), 4),
            'max': round(rc.max(), 4),
        }

print(f"\n{'Pair':<12} {'Comp':<10} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
print("-" * 58)
for pair_key in rolling_corr_stats:
    for comp in ['overnight', 'intraday', 'total']:
        s = rolling_corr_stats[pair_key][comp]
        print(f"{pair_key:<12} {comp:<10} {s['mean']:>8.4f} {s['std']:>8.4f} {s['min']:>8.4f} {s['max']:>8.4f}")
    print()

# ============================================================
# 7. Variance Decomposition (Overnight vs Intraday + Covariance)
# ============================================================
print("=" * 70)
print("SECTION 7: Variance Decomposition")
print("=" * 70)
print("Var(total) = Var(overnight) + Var(intraday) + 2*Cov(overnight, intraday)")

var_decomp = {}
for asset in assets:
    r = returns[asset]
    var_on = r['overnight'].var()
    var_id = r['intraday'].var()
    cov_on_id = r['overnight'].cov(r['intraday'])  # renamed to avoid name collision
    var_total = r['total'].var()

    # The total should be close: var_on + var_id + 2*cov
    var_sum = var_on + var_id + 2 * cov_on_id

    var_decomp[asset] = {
        'var_overnight_pct': round(var_on / var_total * 100, 2),
        'var_intraday_pct': round(var_id / var_total * 100, 2),
        'cov_2x_pct': round(2 * cov_on_id / var_total * 100, 2),
        'sum_pct': round(var_sum / var_total * 100, 2),
        'on_id_corr': round(r['overnight'].corr(r['intraday']), 4),
    }

    print(f"\n{asset}:")
    print(f"  Var(overnight):      {var_decomp[asset]['var_overnight_pct']:>7.2f}% of total variance")
    print(f"  Var(intraday):       {var_decomp[asset]['var_intraday_pct']:>7.2f}% of total variance")
    print(f"  2*Cov(ON,ID):        {var_decomp[asset]['cov_2x_pct']:>7.2f}% of total variance")
    print(f"  Sum:                 {var_decomp[asset]['sum_pct']:>7.2f}%")
    print(f"  ON-ID correlation:   {var_decomp[asset]['on_id_corr']:>7.4f}")

# ============================================================
# 8. Portfolio Strategy Backtests
# ============================================================
print("\n" + "=" * 70)
print("SECTION 8: Portfolio Strategy Backtests (2005-2024)")
print("=" * 70)

# Strategy A: "Overnight Portfolio" - equal weight, only overnight returns
# Simulates: buy at close, sell at open
# Strategy B: "Intraday Portfolio" - equal weight, only intraday returns
# Simulates: buy at open, sell at close
# Strategy C: "Full Day" - buy and hold equal weight
# Strategy D: "50/50 SPY-GLD" versions of above

def calc_portfolio_metrics(daily_returns, name=""):
    """Calculate annualized performance metrics for a return series."""
    cum = (1 + daily_returns).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(daily_returns) / 252
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = daily_returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = daily_returns[daily_returns < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        'name': name,
        'ann_ret_pct': round(ann_ret * 100, 3),
        'ann_vol_pct': round(ann_vol * 100, 3),
        'sharpe': round(sharpe, 4),
        'mdd_pct': round(mdd * 100, 2),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'total_ret_pct': round(total_ret * 100, 2),
        'n_years': round(n_years, 1),
    }

# Build portfolio return series
# Equal weight across all 3 assets
ew_overnight = (returns['SPY']['overnight'] + returns['GLD']['overnight'] + returns['TLT']['overnight']) / 3
ew_intraday = (returns['SPY']['intraday'] + returns['GLD']['intraday'] + returns['TLT']['intraday']) / 3
ew_total = (returns['SPY']['total'] + returns['GLD']['total'] + returns['TLT']['total']) / 3

# 50/50 SPY-GLD
sg_overnight = (returns['SPY']['overnight'] + returns['GLD']['overnight']) / 2
sg_intraday = (returns['SPY']['intraday'] + returns['GLD']['intraday']) / 2
sg_total = (returns['SPY']['total'] + returns['GLD']['total']) / 2

strategies = {
    'EW3_overnight': calc_portfolio_metrics(ew_overnight, "EW3 Overnight"),
    'EW3_intraday': calc_portfolio_metrics(ew_intraday, "EW3 Intraday"),
    'EW3_total': calc_portfolio_metrics(ew_total, "EW3 Total (B&H)"),
    'SG_overnight': calc_portfolio_metrics(sg_overnight, "SPY-GLD Overnight"),
    'SG_intraday': calc_portfolio_metrics(sg_intraday, "SPY-GLD Intraday"),
    'SG_total': calc_portfolio_metrics(sg_total, "SPY-GLD Total (B&H)"),
}

print(f"\n{'Strategy':<22} {'Ann Ret%':>9} {'Ann Vol%':>9} {'Sharpe':>8} {'MDD%':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 82)
for key in strategies:
    s = strategies[key]
    print(f"{s['name']:<22} {s['ann_ret_pct']:>9.3f} {s['ann_vol_pct']:>9.3f} {s['sharpe']:>8.4f} {s['mdd_pct']:>8.2f} {s['calmar']:>8.4f} {s['sortino']:>8.4f}")

# ============================================================
# 9. Yearly Analysis: Overnight vs Intraday Alpha Persistence
# ============================================================
print("\n" + "=" * 70)
print("SECTION 9: Yearly Overnight vs Intraday Mean Returns (SPY)")
print("=" * 70)

spy_r = returns['SPY'].copy()
spy_r['year'] = spy_r.index.year
yearly_stats = []

for year, grp in spy_r.groupby('year'):
    if len(grp) < 100:  # skip partial years
        continue
    on_mean = grp['overnight'].mean() * 252 * 100
    id_mean = grp['intraday'].mean() * 252 * 100
    total_mean = grp['total'].mean() * 252 * 100
    yearly_stats.append({
        'year': year,
        'overnight_ann_pct': round(on_mean, 2),
        'intraday_ann_pct': round(id_mean, 2),
        'total_ann_pct': round(total_mean, 2),
        'on_wins': 1 if on_mean > id_mean else 0,
    })

yearly_df = pd.DataFrame(yearly_stats)
print(f"\n{'Year':>6} {'Overnight%':>12} {'Intraday%':>12} {'Total%':>12} {'ON>ID?':>8}")
print("-" * 54)
for _, row in yearly_df.iterrows():
    winner = "YES" if row['on_wins'] else "no"
    print(f"{int(row['year']):>6} {row['overnight_ann_pct']:>12.2f} {row['intraday_ann_pct']:>12.2f} {row['total_ann_pct']:>12.2f} {winner:>8}")

on_win_rate = yearly_df['on_wins'].mean()
print(f"\nOvernight wins in {yearly_df['on_wins'].sum()}/{len(yearly_df)} years = {on_win_rate*100:.1f}%")

# ============================================================
# 10. Autocorrelation Structure: Overnight vs Intraday
# ============================================================
print("\n" + "=" * 70)
print("SECTION 10: Autocorrelation Structure")
print("=" * 70)

print(f"\n{'Asset':<6} {'Component':<12} {'AC(1)':>8} {'AC(2)':>8} {'AC(5)':>8} {'AC(10)':>8} {'AC(21)':>8}")
print("-" * 64)
ac_results = {}
for asset in assets:
    ac_results[asset] = {}
    for comp in ['overnight', 'intraday', 'total']:
        s = returns[asset][comp]
        acs = [round(s.autocorr(lag=lag), 4) for lag in [1, 2, 5, 10, 21]]
        ac_results[asset][comp] = acs
        print(f"{asset:<6} {comp:<12} {acs[0]:>8.4f} {acs[1]:>8.4f} {acs[2]:>8.4f} {acs[3]:>8.4f} {acs[4]:>8.4f}")

    # Also check |return| autocorrelation (volatility clustering)
    for comp in ['overnight', 'intraday', 'total']:
        s = returns[asset][comp].abs()
        acs = [round(s.autocorr(lag=lag), 4) for lag in [1, 2, 5, 10, 21]]
        ac_results[asset][f"|{comp}|"] = acs
        print(f"{asset:<6} {'|'+comp+'|':<12} {acs[0]:>8.4f} {acs[1]:>8.4f} {acs[2]:>8.4f} {acs[3]:>8.4f} {acs[4]:>8.4f}")
    print()

# ============================================================
# 11. Cross-component: Does overnight predict intraday (or vice versa)?
# ============================================================
print("=" * 70)
print("SECTION 11: Cross-Component Predictability")
print("=" * 70)
print("Does overnight return predict same-day intraday return?")
print("Does intraday return predict next-day overnight return?")

from scipy.stats import pearsonr

predict_results = {}
for asset in assets:
    r = returns[asset]

    # Same-day: overnight -> intraday
    corr_same, p_same = pearsonr(r['overnight'], r['intraday'])

    # Next-day: intraday_t -> overnight_{t+1}
    corr_next, p_next = pearsonr(r['intraday'].iloc[:-1].values, r['overnight'].iloc[1:].values)

    # Next-day: overnight_t -> overnight_{t+1} (persistence)
    corr_on_on, p_on_on = pearsonr(r['overnight'].iloc[:-1].values, r['overnight'].iloc[1:].values)

    predict_results[asset] = {
        'on_to_id_same_day': {'corr': round(corr_same, 4), 'p': round(p_same, 6)},
        'id_to_on_next_day': {'corr': round(corr_next, 4), 'p': round(p_next, 6)},
        'on_to_on_next_day': {'corr': round(corr_on_on, 4), 'p': round(p_on_on, 6)},
    }

    print(f"\n{asset}:")
    print(f"  ON_t -> ID_t (same-day):  r={corr_same:.4f}, p={p_same:.6f}")
    print(f"  ID_t -> ON_{'{t+1}'}:         r={corr_next:.4f}, p={p_next:.6f}")
    print(f"  ON_t -> ON_{'{t+1}'}:         r={corr_on_on:.4f}, p={p_on_on:.6f}")

# ============================================================
# 12. Sub-period Analysis (Pre/Post 2015)
# ============================================================
print("\n" + "=" * 70)
print("SECTION 12: Sub-period Analysis")
print("=" * 70)

periods = {
    '2005-2014': ('2005-01-01', '2014-12-31'),
    '2015-2024': ('2015-01-01', '2024-12-31'),
}

for period_name, (p_start, p_end) in periods.items():
    print(f"\n--- {period_name} ---")
    for asset in assets:
        r = returns[asset].loc[p_start:p_end]
        on_mean = r['overnight'].mean() * 252 * 100
        id_mean = r['intraday'].mean() * 252 * 100
        on_vol = r['overnight'].std() * np.sqrt(252) * 100
        id_vol = r['intraday'].std() * np.sqrt(252) * 100
        on_sharpe = (r['overnight'].mean() * 252) / (r['overnight'].std() * np.sqrt(252)) if r['overnight'].std() > 0 else 0
        id_sharpe = (r['intraday'].mean() * 252) / (r['intraday'].std() * np.sqrt(252)) if r['intraday'].std() > 0 else 0
        print(f"  {asset}: ON mean={on_mean:>7.2f}% vol={on_vol:>6.2f}% SR={on_sharpe:>6.3f} | ID mean={id_mean:>7.2f}% vol={id_vol:>6.2f}% SR={id_sharpe:>6.3f}")

# ============================================================
# 13. Practical Relevance: Impact on VT-based Strategy
# ============================================================
print("\n" + "=" * 70)
print("SECTION 13: Practical Relevance for VT-based Strategy")
print("=" * 70)
print("Which component drives 50/50 SPY-GLD + VT performance?")

# Create 50/50 SPY-GLD portfolio returns by component
spy_gld_on = (returns['SPY']['overnight'] + returns['GLD']['overnight']) / 2
spy_gld_id = (returns['SPY']['intraday'] + returns['GLD']['intraday']) / 2
spy_gld_total = (returns['SPY']['total'] + returns['GLD']['total']) / 2

# Variance decomposition for the portfolio
var_port_on = spy_gld_on.var()
var_port_id = spy_gld_id.var()
cov_port_on_id = spy_gld_on.cov(spy_gld_id)
var_port_total = spy_gld_total.var()

print(f"\n50/50 SPY-GLD Portfolio Variance Decomposition:")
print(f"  Var(overnight):      {var_port_on / var_port_total * 100:>7.2f}%")
print(f"  Var(intraday):       {var_port_id / var_port_total * 100:>7.2f}%")
print(f"  2*Cov(ON,ID):        {2 * cov_port_on_id / var_port_total * 100:>7.2f}%")
print(f"  ON-ID correlation:   {spy_gld_on.corr(spy_gld_id):>7.4f}")

# VT overlay simulation: volatility targeting at 10%
target_vol = 0.10
lookback = 21  # 1-month realized vol

for comp_name, comp_returns in [('Total', spy_gld_total), ('Overnight', spy_gld_on), ('Intraday', spy_gld_id)]:
    rv = comp_returns.rolling(lookback).std() * np.sqrt(252)
    leverage = target_vol / rv
    leverage = leverage.clip(0.5, 2.0)  # reasonable bounds
    vt_returns = comp_returns * leverage.shift(1)
    vt_returns = vt_returns.dropna()

    metrics = calc_portfolio_metrics(vt_returns, f"VT-{comp_name}")
    base_metrics = calc_portfolio_metrics(comp_returns.loc[vt_returns.index], f"Base-{comp_name}")

    print(f"\n  {comp_name}:")
    print(f"    Base: Sharpe={base_metrics['sharpe']:.4f}, MDD={base_metrics['mdd_pct']:.2f}%")
    print(f"    VT:   Sharpe={metrics['sharpe']:.4f}, MDD={metrics['mdd_pct']:.2f}%")
    print(f"    VT improvement: {(metrics['sharpe'] - base_metrics['sharpe']):.4f}")

# ============================================================
# 14. Transaction Cost Impact
# ============================================================
print("\n" + "=" * 70)
print("SECTION 14: Transaction Cost Analysis")
print("=" * 70)
print("Overnight/Intraday strategies require daily round-trip trades.")

# SPY bid-ask spread ~0.01% one-way, commission ~0 for retail
one_way_cost_bps = [0, 1, 2, 5, 10]  # basis points

print(f"\n{'Strategy':<22} {'Gross SR':>9}", end="")
for cost in one_way_cost_bps:
    print(f" {'Net@'+str(cost)+'bp':>9}", end="")
print()
print("-" * 82)

for label, ret_series in [
    ('EW3 Overnight', ew_overnight),
    ('EW3 Intraday', ew_intraday),
    ('EW3 Total (B&H)', ew_total),
    ('SG Overnight', sg_overnight),
    ('SG Intraday', sg_intraday),
    ('SG Total (B&H)', sg_total),
]:
    gross = calc_portfolio_metrics(ret_series, label)
    print(f"{label:<22} {gross['sharpe']:>9.4f}", end="")
    for cost in one_way_cost_bps:
        # Daily round-trip cost = 2 * one-way for overnight/intraday
        # B&H has no daily trading cost
        if 'Total' in label:
            net_ret = ret_series  # no daily trading
        else:
            daily_cost = 2 * cost / 10000  # round trip
            net_ret = ret_series - daily_cost
        net_metrics = calc_portfolio_metrics(net_ret, label)
        print(f" {net_metrics['sharpe']:>9.4f}", end="")
    print()

# ============================================================
# 15. Summary and Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SECTION 15: Summary and Key Findings")
print("=" * 70)

# Find key insights
spy_on_mean = results_stats['SPY']['overnight']['ann_mean_pct']
spy_id_mean = results_stats['SPY']['intraday']['ann_mean_pct']
gld_on_mean = results_stats['GLD']['overnight']['ann_mean_pct']
gld_id_mean = results_stats['GLD']['intraday']['ann_mean_pct']

print(f"""
1. RETURN DECOMPOSITION:
   - SPY: Overnight={spy_on_mean:.2f}% vs Intraday={spy_id_mean:.2f}% annual
   - GLD: Overnight={gld_on_mean:.2f}% vs Intraday={gld_id_mean:.2f}% annual
   - TLT: Overnight={results_stats['TLT']['overnight']['ann_mean_pct']:.2f}% vs Intraday={results_stats['TLT']['intraday']['ann_mean_pct']:.2f}%

2. VARIANCE DECOMPOSITION:
   - SPY: Overnight={var_decomp['SPY']['var_overnight_pct']:.1f}% vs Intraday={var_decomp['SPY']['var_intraday_pct']:.1f}% of total variance
   - GLD: Overnight={var_decomp['GLD']['var_overnight_pct']:.1f}% vs Intraday={var_decomp['GLD']['var_intraday_pct']:.1f}%
   - TLT: Overnight={var_decomp['TLT']['var_overnight_pct']:.1f}% vs Intraday={var_decomp['TLT']['var_intraday_pct']:.1f}%

3. CROSS-ASSET CORRELATIONS:
   - SPY-GLD: Overnight corr={corr_results['SPY-GLD']['overnight']:.4f} vs Intraday corr={corr_results['SPY-GLD']['intraday']:.4f}
   - SPY-TLT: Overnight corr={corr_results['SPY-TLT']['overnight']:.4f} vs Intraday corr={corr_results['SPY-TLT']['intraday']:.4f}
   → Diversification benefit differs by time of day

4. STRATEGY COMPARISON:
   - EW3 Overnight Sharpe: {strategies['EW3_overnight']['sharpe']:.4f}
   - EW3 Intraday Sharpe:  {strategies['EW3_intraday']['sharpe']:.4f}
   - EW3 Total Sharpe:     {strategies['EW3_total']['sharpe']:.4f}

5. PREDICTABILITY:
   - ON_t -> ID_t:  SPY r={predict_results['SPY']['on_to_id_same_day']['corr']:.4f}
   - ID_t -> ON_t+1: SPY r={predict_results['SPY']['id_to_on_next_day']['corr']:.4f}

6. PRACTICAL IMPLICATION:
   - Overnight portfolio requires daily open/close trades (high TX cost)
   - After {one_way_cost_bps[-1]}bp one-way cost, net Sharpe may be negative
   - Key insight: understanding which component drives returns/vol
     can inform VT parameter tuning even without explicit overnight trading
""")

# ============================================================
# Save results
# ============================================================
output = {
    'experiment': 'K268',
    'title': 'Overnight vs Intraday Return Decomposition',
    'data_source': 'yfinance',
    'assets': assets,
    'period': f'{start_date} to {end_date}',
    'n_common_days': len(common_idx),
    'descriptive_stats': results_stats,
    'cross_asset_correlations': corr_results,
    'rolling_correlation_stats': rolling_corr_stats,
    'variance_decomposition': var_decomp,
    'mean_tests': mean_tests,
    'strategy_backtests': strategies,
    'yearly_stats': yearly_stats,
    'autocorrelation': ac_results,
    'predictability': predict_results,
}

output_path = 'experiments/k268_overnight_intraday_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("K268 complete.")
