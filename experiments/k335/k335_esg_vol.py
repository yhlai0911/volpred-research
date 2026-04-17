"""
K335: ESG and Volatility — Do ESG Leaders Have Lower Vol?
(跳躍式探索 — ESG/Sustainable Investing × Volatility)

[提出: 用戶, 執行: Claude]

Background:
- ESG (Environmental, Social, Governance) investing is a massive trend
- Hypothesis: companies with better ESG scores have lower stock volatility
  because they face fewer tail risks (lawsuits, scandals, environmental disasters)
- This is a jump-exploration into sustainable finance × volatility

Data (yfinance ETFs as proxies):
- ESGU: iShares ESG Aware MSCI USA (ESG-screened US equities)
- VICE/SIN: Vice Fund / AdvisorShares Vice ETF ("sin stocks")
- SPY: broad market benchmark
- ^VIX: CBOE Volatility Index
- Alternative proxies: XLK/XLV (ESG leaders), XLE/XLF (ESG laggards)

Methodology:
1. Compare volatility characteristics: annualized vol, tail risk, drawdowns
2. Does ESG screening reduce vol? (ESGU vs SPY, sector comparison)
3. VT overlay: does VT work better or worse for ESG portfolios?
4. Partial r: does ESG-vs-non-ESG vol spread predict future vol?

Limitations:
- ESG ETFs have short history (ESGU: 2016+)
- ETF-level analysis, not individual stock ESG scores
- Sector proxies are imperfect ESG approximations
- Survivorship bias in ESG indices (worst ESG firms removed)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K335: ESG and Volatility — Do ESG Leaders Have Lower Vol?")
print("=" * 70)

print("\n[1] Downloading data...")

# Primary ESG ETFs
tickers = {
    'ESGU': 'iShares ESG Aware MSCI USA',
    'VICE': 'AdvisorShares Vice ETF',
    'SPY': 'S&P 500 (benchmark)',
    '^VIX': 'CBOE VIX',
    # Sector proxies
    'XLK': 'Tech (ESG leader proxy)',
    'XLV': 'Healthcare (ESG leader proxy)',
    'XLE': 'Energy (ESG laggard proxy)',
    'XLF': 'Financials (ESG laggard proxy)',
}

data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start="2010-01-01", end="2026-03-25", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 100:
            data[ticker] = df
            print(f"  {ticker} ({desc}): {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} obs)")
        else:
            print(f"  {ticker} ({desc}): INSUFFICIENT DATA ({len(df)} obs), skipping")
    except Exception as e:
        print(f"  {ticker} ({desc}): DOWNLOAD FAILED ({e})")

# Also try SIN ETF as alternative to VICE
if 'VICE' not in data or len(data.get('VICE', pd.DataFrame())) < 200:
    print("  Trying SIN ETF as alternative to VICE...")
    try:
        df = yf.download("SIN", start="2010-01-01", end="2026-03-25", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 100:
            data['SIN'] = df
            print(f"  SIN (SINCLAIR alt): {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} obs)")
    except:
        pass

# Build returns DataFrame
print("\n[2] Building returns matrix...")
returns = pd.DataFrame()
close_prices = pd.DataFrame()

for ticker in data:
    if ticker == '^VIX':
        close_prices['VIX'] = data[ticker]['Close']
    else:
        close_prices[ticker] = data[ticker]['Close']
        returns[ticker] = np.log(data[ticker]['Close'] / data[ticker]['Close'].shift(1))

returns = returns.dropna(how='all')
close_prices = close_prices.dropna(how='all')

# VIX aligned
vix = close_prices['VIX'].reindex(returns.index, method='ffill')

print(f"  Returns matrix: {returns.shape[0]} rows × {returns.shape[1]} assets")
print(f"  Assets: {list(returns.columns)}")

# Define ESG groups
esg_leaders = [t for t in ['ESGU', 'XLK', 'XLV'] if t in returns.columns]
esg_laggards = [t for t in ['VICE', 'SIN', 'XLE', 'XLF'] if t in returns.columns]
benchmark = 'SPY'

print(f"\n  ESG leader proxies: {esg_leaders}")
print(f"  ESG laggard proxies: {esg_laggards}")

# ============================================================
# 2. Volatility Characteristics Comparison
# ============================================================
print("\n" + "=" * 70)
print("[3] Volatility Characteristics Comparison")
print("=" * 70)

# Find common date range for fair comparison
all_assets = esg_leaders + esg_laggards + [benchmark]
all_assets = [a for a in all_assets if a in returns.columns]

# Use the latest start date among all available assets
common_start = max(returns[a].dropna().index[0] for a in all_assets)
common_end = min(returns[a].dropna().index[-1] for a in all_assets)
print(f"\n  Common period: {common_start.strftime('%Y-%m-%d')} to {common_end.strftime('%Y-%m-%d')}")

ret_common = returns.loc[common_start:common_end, all_assets].dropna()
print(f"  Common observations: {len(ret_common)}")

results_vol = {}

print(f"\n  {'Asset':<8} {'Ann.Vol%':>8} {'Skewness':>9} {'Kurtosis':>9} {'VaR1%':>8} {'CVaR1%':>8} {'Max DD%':>8}")
print("  " + "-" * 65)

for asset in all_assets:
    r = ret_common[asset].values
    ann_vol = np.std(r) * np.sqrt(252) * 100
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)  # excess kurtosis
    var_1 = np.percentile(r, 1) * 100
    cvar_1 = np.mean(r[r <= np.percentile(r, 1)]) * 100

    # Max drawdown
    cum_ret = np.exp(np.cumsum(r))
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns) * 100

    group = "LEADER" if asset in esg_leaders else ("LAGGARD" if asset in esg_laggards else "BENCH")

    results_vol[asset] = {
        'group': group,
        'ann_vol': round(ann_vol, 2),
        'skewness': round(skew, 3),
        'kurtosis': round(kurt, 2),
        'var_1pct': round(var_1, 3),
        'cvar_1pct': round(cvar_1, 3),
        'max_dd': round(max_dd, 2),
    }

    print(f"  {asset:<8} {ann_vol:>8.2f} {skew:>9.3f} {kurt:>9.2f} {var_1:>8.3f} {cvar_1:>8.3f} {max_dd:>8.2f}")

# Group averages
print("\n  --- Group Averages ---")
for group_name, group_assets in [("LEADERS", esg_leaders), ("LAGGARDS", esg_laggards)]:
    if not group_assets:
        continue
    avg_vol = np.mean([results_vol[a]['ann_vol'] for a in group_assets])
    avg_kurt = np.mean([results_vol[a]['kurtosis'] for a in group_assets])
    avg_var = np.mean([results_vol[a]['var_1pct'] for a in group_assets])
    avg_dd = np.mean([results_vol[a]['max_dd'] for a in group_assets])
    print(f"  {group_name:<8} AvgVol={avg_vol:.2f}%  AvgKurt={avg_kurt:.2f}  AvgVaR1%={avg_var:.3f}%  AvgMDD={avg_dd:.2f}%")

spy_vol = results_vol[benchmark]['ann_vol']
print(f"  SPY     AvgVol={spy_vol:.2f}%")

# ============================================================
# 3. Statistical Tests: ESG vs Non-ESG Volatility
# ============================================================
print("\n" + "=" * 70)
print("[4] Statistical Tests: ESG vs Non-ESG Vol Difference")
print("=" * 70)

# 3a. ESGU vs SPY (if ESGU available)
if 'ESGU' in returns.columns:
    esgu_start = returns['ESGU'].dropna().index[0]
    esgu_end = returns['ESGU'].dropna().index[-1]
    print(f"\n  ESGU available: {esgu_start.strftime('%Y-%m-%d')} to {esgu_end.strftime('%Y-%m-%d')}")

    r_esgu = returns.loc[esgu_start:esgu_end, 'ESGU'].dropna()
    r_spy_matched = returns.loc[r_esgu.index, 'SPY']

    # Rolling 22-day vol comparison
    vol_esgu_22 = r_esgu.rolling(22).std() * np.sqrt(252)
    vol_spy_22 = r_spy_matched.rolling(22).std() * np.sqrt(252)
    vol_diff = vol_esgu_22 - vol_spy_22
    vol_diff = vol_diff.dropna()

    mean_diff = vol_diff.mean() * 100  # in percentage points
    t_stat, p_val = stats.ttest_1samp(vol_diff.values, 0)

    print(f"\n  ESGU vs SPY (22d rolling vol):")
    print(f"    Mean vol difference: {mean_diff:.4f} pp")
    print(f"    t-stat: {t_stat:.3f}")
    print(f"    p-value: {p_val:.4f}")
    print(f"    Interpretation: ESGU has {'LOWER' if mean_diff < 0 else 'HIGHER'} vol than SPY")

    # Newey-West for autocorrelated vol
    from scipy.stats import t as t_dist
    n = len(vol_diff)
    mean_d = vol_diff.mean()

    # Newey-West with lag = int(4*(n/100)^(2/9))
    nw_lag = int(4 * (n / 100) ** (2/9))
    resid = vol_diff.values - mean_d
    gamma0 = np.mean(resid ** 2)
    nw_var = gamma0
    for j in range(1, nw_lag + 1):
        w = 1 - j / (nw_lag + 1)
        gamma_j = np.mean(resid[j:] * resid[:-j])
        nw_var += 2 * w * gamma_j
    nw_se = np.sqrt(nw_var / n)
    nw_t = mean_d / nw_se
    nw_p = 2 * (1 - t_dist.cdf(abs(nw_t), n - 1))

    print(f"\n    Newey-West adjusted (lag={nw_lag}):")
    print(f"    t-stat: {nw_t:.3f}")
    print(f"    p-value: {nw_p:.4f}")

# 3b. ESG Leader sectors vs Laggard sectors
print(f"\n  Sector-based ESG comparison:")
leader_sectors = [a for a in esg_leaders if a != 'ESGU']
laggard_sectors = [a for a in esg_laggards if a not in ['VICE', 'SIN']]

if leader_sectors and laggard_sectors:
    # Use common period for sectors (should be longer)
    sector_assets = leader_sectors + laggard_sectors
    sector_start = max(returns[a].dropna().index[0] for a in sector_assets)
    sector_end = min(returns[a].dropna().index[-1] for a in sector_assets)

    print(f"  Sector period: {sector_start.strftime('%Y-%m-%d')} to {sector_end.strftime('%Y-%m-%d')}")

    ret_sector = returns.loc[sector_start:sector_end, sector_assets].dropna()

    # Annualized vol per group
    leader_vols = [ret_sector[a].std() * np.sqrt(252) * 100 for a in leader_sectors]
    laggard_vols = [ret_sector[a].std() * np.sqrt(252) * 100 for a in laggard_sectors]

    print(f"    Leaders  ({', '.join(leader_sectors)}): vols = {[f'{v:.1f}%' for v in leader_vols]}")
    print(f"    Laggards ({', '.join(laggard_sectors)}): vols = {[f'{v:.1f}%' for v in laggard_vols]}")

    # Rolling vol difference (avg leader - avg laggard)
    leader_avg_vol = pd.concat([ret_sector[a].rolling(22).std() for a in leader_sectors], axis=1).mean(axis=1) * np.sqrt(252)
    laggard_avg_vol = pd.concat([ret_sector[a].rolling(22).std() for a in laggard_sectors], axis=1).mean(axis=1) * np.sqrt(252)
    sector_vol_diff = leader_avg_vol - laggard_avg_vol
    sector_vol_diff = sector_vol_diff.dropna()

    mean_sector_diff = sector_vol_diff.mean() * 100
    t_sect, p_sect = stats.ttest_1samp(sector_vol_diff.values, 0)

    print(f"\n    Mean vol diff (leader - laggard): {mean_sector_diff:.4f} pp")
    print(f"    t-stat: {t_sect:.3f}")
    print(f"    p-value: {p_sect:.6f}")
    print(f"    => ESG leader sectors have {'LOWER' if mean_sector_diff < 0 else 'HIGHER'} vol")

# ============================================================
# 4. Tail Risk Comparison
# ============================================================
print("\n" + "=" * 70)
print("[5] Tail Risk Analysis: ESG vs Non-ESG")
print("=" * 70)

# 5th percentile returns (left tail)
print(f"\n  {'Asset':<8} {'5th pct':>8} {'1st pct':>8} {'Worst Day':>10} {'Days<-3%':>10} {'Days<-5%':>10}")
print("  " + "-" * 55)

for asset in all_assets:
    r = ret_common[asset].values * 100  # to percent
    p5 = np.percentile(r, 5)
    p1 = np.percentile(r, 1)
    worst = np.min(r)
    days_3 = np.sum(r < -3.0)
    days_5 = np.sum(r < -5.0)
    print(f"  {asset:<8} {p5:>8.2f}% {p1:>8.2f}% {worst:>9.2f}% {days_3:>10d} {days_5:>10d}")

# ============================================================
# 5. VIX Correlation
# ============================================================
print("\n" + "=" * 70)
print("[6] VIX Correlation Analysis")
print("=" * 70)

vix_ret = np.log(vix / vix.shift(1)).reindex(ret_common.index)
valid_idx = vix_ret.dropna().index.intersection(ret_common.index)

print(f"\n  {'Asset':<8} {'corr(r,dVIX)':>12} {'beta_VIX':>10} {'R²':>6}")
print("  " + "-" * 40)

vix_corrs = {}
for asset in all_assets:
    r = ret_common.loc[valid_idx, asset].values
    v = vix_ret.loc[valid_idx].values

    # Remove any remaining NaN
    mask = ~(np.isnan(r) | np.isnan(v))
    r = r[mask]
    v = v[mask]

    corr = np.corrcoef(r, v)[0, 1]
    # Regression: r = alpha + beta * dVIX
    slope, intercept, r_val, p_val, se = stats.linregress(v, r)

    vix_corrs[asset] = corr
    print(f"  {asset:<8} {corr:>12.4f} {slope:>10.4f} {r_val**2:>6.4f}")

# Group averages
leader_corr = np.mean([vix_corrs[a] for a in esg_leaders if a in vix_corrs])
laggard_corr = np.mean([vix_corrs[a] for a in esg_laggards if a in vix_corrs])
print(f"\n  Leaders avg VIX corr: {leader_corr:.4f}")
print(f"  Laggards avg VIX corr: {laggard_corr:.4f}")
print(f"  => Leaders are {'MORE' if abs(leader_corr) > abs(laggard_corr) else 'LESS'} sensitive to VIX")

# ============================================================
# 6. Drawdown Analysis
# ============================================================
print("\n" + "=" * 70)
print("[7] Drawdown Analysis by Crisis Period")
print("=" * 70)

# Define crisis periods
crises = {
    'COVID-2020': ('2020-02-19', '2020-03-23'),
    'Q4-2018': ('2018-09-20', '2018-12-24'),
    'Inflation-2022': ('2022-01-03', '2022-10-12'),
    'SVB-2023': ('2023-02-02', '2023-03-13'),
}

for crisis_name, (start, end) in crises.items():
    print(f"\n  --- {crisis_name} ---")
    available = [a for a in all_assets if start in close_prices.index.strftime('%Y-%m-%d') or True]

    try:
        crisis_prices = close_prices.loc[start:end, [a for a in all_assets if a in close_prices.columns]]
        if len(crisis_prices) < 2:
            print(f"    (insufficient data for this period)")
            continue

        crisis_returns = crisis_prices / crisis_prices.iloc[0] - 1

        print(f"  {'Asset':<8} {'Total Return':>12} {'Max DD':>8}")
        for asset in all_assets:
            if asset in crisis_returns.columns:
                cr = crisis_returns[asset].dropna()
                if len(cr) > 0:
                    total_ret = cr.iloc[-1] * 100
                    max_dd = (cr - cr.cummax()).min() * 100
                    print(f"  {asset:<8} {total_ret:>11.2f}% {max_dd:>7.2f}%")
    except Exception as e:
        print(f"    Error: {e}")

# ============================================================
# 7. VT Overlay Test: ESG vs Non-ESG
# ============================================================
print("\n" + "=" * 70)
print("[8] VT Overlay: Does VT Work Better for ESG Portfolios?")
print("=" * 70)

def vt_backtest(ret_series, vix_series, threshold=12, label=""):
    """Simple 12/VIX VT backtest with lagged weights."""
    common = ret_series.dropna().index.intersection(vix_series.dropna().index)
    r = ret_series.loc[common].values
    v = vix_series.loc[common].values

    if len(r) < 252:
        return None

    # Lagged VT: weight_t = min(1, threshold / VIX_{t-1})
    weights = np.minimum(1.0, threshold / v[:-1])
    r_vt = weights * r[1:]
    r_bh = r[1:]

    sharpe_bh = np.mean(r_bh) / np.std(r_bh) * np.sqrt(252)
    sharpe_vt = np.mean(r_vt) / np.std(r_vt) * np.sqrt(252)

    # MDD
    cum_bh = np.exp(np.cumsum(r_bh))
    mdd_bh = np.min(cum_bh / np.maximum.accumulate(cum_bh) - 1) * 100

    cum_vt = np.exp(np.cumsum(r_vt))
    mdd_vt = np.min(cum_vt / np.maximum.accumulate(cum_vt) - 1) * 100

    return {
        'label': label,
        'n_obs': len(r_bh),
        'sharpe_bh': round(sharpe_bh, 3),
        'sharpe_vt': round(sharpe_vt, 3),
        'sharpe_diff': round(sharpe_vt - sharpe_bh, 3),
        'mdd_bh': round(mdd_bh, 2),
        'mdd_vt': round(mdd_vt, 2),
        'mdd_improve': round(mdd_bh - mdd_vt, 2),
        'ann_vol_bh': round(np.std(r_bh) * np.sqrt(252) * 100, 2),
        'ann_vol_vt': round(np.std(r_vt) * np.sqrt(252) * 100, 2),
    }

print(f"\n  {'Asset':<8} {'BH Sharpe':>10} {'VT Sharpe':>10} {'Diff':>6} {'BH MDD':>8} {'VT MDD':>8} {'MDD Improve':>12}")
print("  " + "-" * 70)

vt_results = {}
for asset in all_assets:
    if asset in returns.columns:
        res = vt_backtest(returns[asset], vix, threshold=12, label=asset)
        if res:
            vt_results[asset] = res
            print(f"  {asset:<8} {res['sharpe_bh']:>10.3f} {res['sharpe_vt']:>10.3f} {res['sharpe_diff']:>+6.3f} "
                  f"{res['mdd_bh']:>7.2f}% {res['mdd_vt']:>7.2f}% {res['mdd_improve']:>+11.2f}pp")

# VT effectiveness by group
if vt_results:
    print("\n  --- VT Effectiveness by Group ---")
    for group_name, group_assets in [("LEADERS", esg_leaders), ("LAGGARDS", esg_laggards), ("BENCHMARK", [benchmark])]:
        group_res = [vt_results[a] for a in group_assets if a in vt_results]
        if group_res:
            avg_sharpe_diff = np.mean([r['sharpe_diff'] for r in group_res])
            avg_mdd_improve = np.mean([r['mdd_improve'] for r in group_res])
            print(f"  {group_name:<10} Avg Sharpe diff: {avg_sharpe_diff:+.3f}  Avg MDD improve: {avg_mdd_improve:+.2f}pp")

# ============================================================
# 8. Partial Correlation: ESG Vol Spread as Predictor
# ============================================================
print("\n" + "=" * 70)
print("[9] ESG Vol Spread as Vol Predictor (Partial Correlation)")
print("=" * 70)

# Use sector proxies for longer history
if leader_sectors and laggard_sectors:
    # Build ESG vol spread: avg leader vol - avg laggard vol
    # Use 22-day rolling vol
    sector_common_start = max(returns[a].dropna().index[0] for a in leader_sectors + laggard_sectors + [benchmark])
    ret_sect = returns.loc[sector_common_start:, leader_sectors + laggard_sectors + [benchmark]].dropna()

    leader_vol_22 = pd.concat([ret_sect[a].rolling(22).std() for a in leader_sectors], axis=1).mean(axis=1)
    laggard_vol_22 = pd.concat([ret_sect[a].rolling(22).std() for a in laggard_sectors], axis=1).mean(axis=1)
    spy_vol_22 = ret_sect[benchmark].rolling(22).std()
    esg_vol_spread = leader_vol_22 - laggard_vol_22  # negative = leaders less volatile

    # Forward SPY vol (next 22 days)
    spy_fwd_vol = ret_sect[benchmark].rolling(22).std().shift(-22)

    # VIX aligned
    vix_aligned = vix.reindex(ret_sect.index, method='ffill')

    # Build regression data
    reg_data = pd.DataFrame({
        'esg_spread': esg_vol_spread,
        'vix': vix_aligned,
        'spy_vol_current': spy_vol_22,
        'spy_vol_fwd': spy_fwd_vol,
    }).dropna()

    print(f"\n  Regression data: {len(reg_data)} obs ({reg_data.index[0].strftime('%Y-%m-%d')} to {reg_data.index[-1].strftime('%Y-%m-%d')})")
    print(f"  Mean ESG spread (leader - laggard): {reg_data['esg_spread'].mean()*100:.4f}%/day")

    # Simple correlation
    corr_spread_fwd = np.corrcoef(reg_data['esg_spread'].values, reg_data['spy_vol_fwd'].values)[0, 1]
    print(f"\n  Bivariate corr(ESG spread, future SPY vol): {corr_spread_fwd:.4f}")

    # Partial correlation controlling for VIX
    # partial_r(X,Y|Z) = (r_XY - r_XZ * r_YZ) / sqrt((1-r_XZ²)(1-r_YZ²))
    x = reg_data['esg_spread'].values
    y = reg_data['spy_vol_fwd'].values
    z = reg_data['vix'].values

    r_xy = np.corrcoef(x, y)[0, 1]
    r_xz = np.corrcoef(x, z)[0, 1]
    r_yz = np.corrcoef(y, z)[0, 1]

    partial_r = (r_xy - r_xz * r_yz) / np.sqrt((1 - r_xz**2) * (1 - r_yz**2))

    # Significance of partial r
    n = len(reg_data)
    t_partial = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
    p_partial = 2 * (1 - stats.t.cdf(abs(t_partial), n - 3))

    print(f"  Partial corr(ESG spread, future SPY vol | VIX): {partial_r:.4f}")
    print(f"    t-stat: {t_partial:.3f}")
    print(f"    p-value: {p_partial:.6f}")
    print(f"    => ESG spread {'ADDS' if p_partial < 0.05 else 'does NOT add'} predictive power beyond VIX")

    # Also: partial r controlling for current vol
    r_xz2 = np.corrcoef(x, reg_data['spy_vol_current'].values)[0, 1]
    r_yz2 = np.corrcoef(y, reg_data['spy_vol_current'].values)[0, 1]
    partial_r2 = (r_xy - r_xz2 * r_yz2) / np.sqrt((1 - r_xz2**2) * (1 - r_yz2**2))
    t_partial2 = partial_r2 * np.sqrt((n - 3) / (1 - partial_r2**2))
    p_partial2 = 2 * (1 - stats.t.cdf(abs(t_partial2), n - 3))

    print(f"\n  Partial corr(ESG spread, future SPY vol | current vol): {partial_r2:.4f}")
    print(f"    t-stat: {t_partial2:.3f}")
    print(f"    p-value: {p_partial2:.6f}")

# ============================================================
# 9. Regime-Dependent Analysis
# ============================================================
print("\n" + "=" * 70)
print("[10] Regime-Dependent ESG Vol Characteristics")
print("=" * 70)

# VIX regimes
vix_common = vix.reindex(ret_common.index).dropna()
ret_regime = ret_common.loc[vix_common.index]

regimes = {
    'Low VIX (<15)': vix_common < 15,
    'Normal (15-25)': (vix_common >= 15) & (vix_common < 25),
    'High (25-35)': (vix_common >= 25) & (vix_common < 35),
    'Crisis (>35)': vix_common >= 35,
}

print(f"\n  {'Regime':<18}", end="")
for asset in all_assets:
    print(f" {asset:>8}", end="")
print(f" {'n_days':>8}")
print("  " + "-" * (18 + 9 * len(all_assets) + 8))

for regime_name, mask in regimes.items():
    if mask.sum() < 10:
        continue
    print(f"  {regime_name:<18}", end="")
    for asset in all_assets:
        r = ret_regime.loc[mask, asset].dropna()
        vol = r.std() * np.sqrt(252) * 100
        print(f" {vol:>7.1f}%", end="")
    print(f" {mask.sum():>8d}")

# ============================================================
# 10. ESG Premium / Discount
# ============================================================
print("\n" + "=" * 70)
print("[11] ESG Return Premium / Discount (Risk-Adjusted)")
print("=" * 70)

for asset in all_assets:
    r = ret_common[asset].values
    ann_ret = np.mean(r) * 252 * 100
    ann_vol = np.std(r) * np.sqrt(252) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    print(f"  {asset:<8} Ann.Return={ann_ret:>6.2f}%  Ann.Vol={ann_vol:>6.2f}%  Sharpe={sharpe:>6.3f}")

if 'ESGU' in ret_common.columns:
    # ESGU - SPY return difference
    ret_diff = ret_common['ESGU'] - ret_common['SPY']
    ann_diff = ret_diff.mean() * 252 * 100
    t_diff, p_diff = stats.ttest_1samp(ret_diff.values, 0)
    print(f"\n  ESGU - SPY annual return diff: {ann_diff:+.2f}%")
    print(f"  t-stat: {t_diff:.3f}, p-value: {p_diff:.4f}")

# ============================================================
# 11. Rolling Beta and Vol Ratio
# ============================================================
print("\n" + "=" * 70)
print("[12] Rolling ESGU/SPY Vol Ratio (Stability Check)")
print("=" * 70)

if 'ESGU' in returns.columns:
    esgu_r = returns['ESGU'].dropna()
    spy_r = returns['SPY'].reindex(esgu_r.index)

    for window in [63, 126, 252]:
        vol_ratio = (esgu_r.rolling(window).std() / spy_r.rolling(window).std()).dropna()
        print(f"\n  Window={window}d ({window//21}m):")
        print(f"    Mean ratio: {vol_ratio.mean():.4f}")
        print(f"    Std ratio: {vol_ratio.std():.4f}")
        print(f"    Min: {vol_ratio.min():.4f}  Max: {vol_ratio.max():.4f}")
        print(f"    % time ESGU < SPY vol: {(vol_ratio < 1.0).mean()*100:.1f}%")

# ============================================================
# 12. Summary and Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[SUMMARY] K335: ESG and Volatility")
print("=" * 70)

summary = {
    'experiment': 'K335',
    'title': 'ESG and Volatility — Do ESG Leaders Have Lower Vol?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'category': 'jump_exploration',
    'attribution': '[提出: 用戶, 執行: Claude]',
    'assets_tested': all_assets,
    'common_period': f"{common_start.strftime('%Y-%m-%d')} to {common_end.strftime('%Y-%m-%d')}",
    'n_obs': len(ret_common),
    'vol_characteristics': results_vol,
    'vt_results': vt_results,
    'findings': [],
    'limitations': [
        'ESGU inception 2016 — limited history compared to sector ETFs',
        'ETF-level proxy, not individual stock ESG scores',
        'Sector proxies are imperfect ESG approximations (XLK is tech, not pure ESG)',
        'Survivorship bias in ESG indices (worst ESG firms removed ex-ante)',
        'VICE/SIN ETF may have limited liquidity / tracking issues',
        'ESG = reduced tail risk hypothesis not directly testable via ETF returns alone',
    ],
}

# Auto-generate findings
print("\n  KEY FINDINGS:")

# F1: Vol comparison
if 'ESGU' in results_vol and benchmark in results_vol:
    vol_diff_pct = results_vol['ESGU']['ann_vol'] - results_vol[benchmark]['ann_vol']
    finding = f"ESGU vol ({results_vol['ESGU']['ann_vol']:.1f}%) vs SPY ({results_vol[benchmark]['ann_vol']:.1f}%): diff = {vol_diff_pct:+.1f}pp"
    summary['findings'].append(finding)
    print(f"  1. {finding}")

# F2: Sector comparison
if leader_sectors and laggard_sectors:
    l_avg = np.mean([results_vol[a]['ann_vol'] for a in leader_sectors])
    lag_avg = np.mean([results_vol[a]['ann_vol'] for a in laggard_sectors])
    finding = f"Sector proxies: Leaders avg vol {l_avg:.1f}% vs Laggards avg vol {lag_avg:.1f}% (diff {l_avg-lag_avg:+.1f}pp)"
    summary['findings'].append(finding)
    print(f"  2. {finding}")

# F3: VT effectiveness
if vt_results:
    leader_vt_sharpe = np.mean([vt_results[a]['sharpe_diff'] for a in esg_leaders if a in vt_results])
    laggard_vt_sharpe = np.mean([vt_results[a]['sharpe_diff'] for a in esg_laggards if a in vt_results])
    finding = f"VT Sharpe improvement: Leaders avg {leader_vt_sharpe:+.3f} vs Laggards avg {laggard_vt_sharpe:+.3f}"
    summary['findings'].append(finding)
    print(f"  3. {finding}")

# F4: Tail risk
if esg_leaders and esg_laggards:
    l_kurt = np.mean([results_vol[a]['kurtosis'] for a in esg_leaders])
    lag_kurt = np.mean([results_vol[a]['kurtosis'] for a in esg_laggards])
    finding = f"Tail risk (kurtosis): Leaders avg {l_kurt:.1f} vs Laggards avg {lag_kurt:.1f}"
    summary['findings'].append(finding)
    print(f"  4. {finding}")

# F5: Partial correlation
if 'partial_r' in dir():
    finding = f"ESG vol spread partial_r with future SPY vol (controlling VIX): {partial_r:.4f} (t={t_partial:.2f}, p={p_partial:.4f})"
    summary['findings'].append(finding)
    print(f"  5. {finding}")

# Overall conclusion
print("\n  OVERALL CONCLUSION:")
if 'ESGU' in results_vol:
    esgu_diff = results_vol['ESGU']['ann_vol'] - results_vol[benchmark]['ann_vol']
    if abs(esgu_diff) < 1.0:
        print("  ESG screening (ESGU) has NEGLIGIBLE impact on portfolio volatility (< 1pp)")
    elif esgu_diff < 0:
        print(f"  ESG screening (ESGU) REDUCES volatility by {abs(esgu_diff):.1f}pp vs SPY")
    else:
        print(f"  ESG screening (ESGU) INCREASES volatility by {esgu_diff:.1f}pp vs SPY")

print("\n  Note: ESG ETFs largely hold the same mega-cap stocks as SPY,")
print("  so the vol difference is expected to be small at the index level.")
print("  Individual stock-level analysis with ESG scores would be more definitive.")

# Save results
results_file = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-ad325b1a/experiments/k335_esg_vol_results.json'
with open(results_file, 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print(f"\n  Results saved to: {results_file}")

print("\n" + "=" * 70)
print("K335 COMPLETE")
print("=" * 70)
