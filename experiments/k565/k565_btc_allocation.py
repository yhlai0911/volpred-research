#!/usr/bin/env python3
"""
K565: Bitcoin Allocation in VT Portfolio — Revisiting K66 with Updated Data

Context: K66 found 5% BTC allocation is the only statistically significant
improvement to 50/50 (p=0.014), but with high coskewness risk (-0.50).
BTC has matured since then (spot ETFs approved Jan 2024, institutional adoption).
This experiment revisits with full 2015-2026 data + sub-period analysis.

References:
- K66: Original BTC allocation deep dive (2015-2026, 4 sub-periods)
- K78: Investor type segmentation (used K66 results)
- Bouri et al. (2017) "On the hedge and safe haven properties of Bitcoin"
- Platanakis & Urquhart (2020) "Should investors include Bitcoin in portfolios?"
- Liu & Tsyvinski (2021) "Risks and Returns of Cryptocurrency" JFE

Data source: yfinance (SPY, GLD, BTC-USD, ^VIX)
Data period: 2015-01-01 to 2026-03-26

Experiment design:
1. Base portfolio: 50/50 SPY/GLD with 12/VIX timing on SPY portion
2. BTC variants: 47.5/47.5/5, 45/45/10, 40/40/20
3. Conditional BTC: VIX-conditional (VIX<20), Momentum (BTC 60d ret>0)
4. Cross-OOS: 3 periods (2016-2019, 2020-2022, 2023-2025)
5. Harvey (2016) t>3.0 threshold
6. Focus on post-2024 ETF era behavior

Author: Yi-Hao Lai + VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K565: Bitcoin Allocation in VT Portfolio — Revisiting K66")
print("=" * 70)

tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'BTC': 'BTC-USD',
    'VIX': '^VIX'
}

start_date = '2015-01-01'
end_date = '2026-03-27'

print(f"\nDownloading data: {start_date} to {end_date}")
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close' if name != 'VIX' else 'Close'].copy()
    print(f"  {name}: {len(df)} observations, {df.index[0].date()} to {df.index[-1].date()}")

# Align all data
prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"\nAligned dataset: {len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()}")

# Calculate returns
returns = prices[['SPY', 'GLD', 'BTC']].pct_change().dropna()
vix = prices['VIX'].reindex(returns.index)

print(f"Returns: {len(returns)} observations")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n" + "=" * 70)
print("DESCRIPTIVE STATISTICS")
print("=" * 70)

desc_stats = {}
for asset in ['SPY', 'GLD', 'BTC']:
    r = returns[asset]
    desc_stats[asset] = {
        'mean_annual': float(r.mean() * 252),
        'std_annual': float(r.std() * np.sqrt(252)),
        'skewness': float(r.skew()),
        'kurtosis': float(r.kurtosis()),
        'min_daily': float(r.min()),
        'max_daily': float(r.max()),
        'sharpe_standalone': float((r.mean() * 252) / (r.std() * np.sqrt(252)))
    }
    print(f"\n{asset}:")
    print(f"  Annual return: {desc_stats[asset]['mean_annual']:.4f}")
    print(f"  Annual vol:    {desc_stats[asset]['std_annual']:.4f}")
    print(f"  Skewness:      {desc_stats[asset]['skewness']:.4f}")
    print(f"  Kurtosis:      {desc_stats[asset]['kurtosis']:.4f}")
    print(f"  Min daily:     {desc_stats[asset]['min_daily']:.4f}")
    print(f"  Max daily:     {desc_stats[asset]['max_daily']:.4f}")
    print(f"  Sharpe:        {desc_stats[asset]['sharpe_standalone']:.4f}")

# Correlations
print("\n--- Correlation Matrix ---")
corr_full = returns[['SPY', 'GLD', 'BTC']].corr()
print(corr_full.round(4))

# Rolling correlation SPY-BTC
rolling_corr_spy_btc = returns['SPY'].rolling(252).corr(returns['BTC'])
print(f"\nSPY-BTC rolling 1yr correlation:")
print(f"  Pre-2020 mean: {rolling_corr_spy_btc.loc[:'2019-12-31'].mean():.4f}")
print(f"  2020-2022 mean: {rolling_corr_spy_btc.loc['2020-01-01':'2022-12-31'].mean():.4f}")
print(f"  2023-2025 mean: {rolling_corr_spy_btc.loc['2023-01-01':'2025-12-31'].mean():.4f}")
print(f"  Post-ETF (2024+) mean: {rolling_corr_spy_btc.loc['2024-01-01':].mean():.4f}")

# ============================================================
# 3. Portfolio Construction Functions
# ============================================================

def compute_12_vix_signal(vix_series):
    """12/VIX timing signal: invest in equity when 12/VIX > 1 (VIX < 12 means calm)"""
    # Actually 12/VIX is a position scalar (capped at 1)
    signal = 12.0 / vix_series
    signal = signal.clip(upper=1.0)
    return signal

def portfolio_returns(returns_df, vix_series, weights, conditional_btc=None):
    """
    Compute portfolio returns with 12/VIX timing on SPY portion.

    weights: dict with 'SPY', 'GLD', 'BTC' allocations (sum to 1)
    conditional_btc: None (always hold), 'vix' (VIX<20), 'momentum' (60d ret>0)
    """
    spy_ret = returns_df['SPY']
    gld_ret = returns_df['GLD']
    btc_ret = returns_df['BTC'] if 'BTC' in returns_df.columns else pd.Series(0, index=returns_df.index)

    # 12/VIX signal for SPY portion
    vix_signal = compute_12_vix_signal(vix_series)
    # Use previous day's VIX to avoid look-ahead
    vix_signal_lag = vix_signal.shift(1).fillna(1.0)

    w_spy = weights.get('SPY', 0)
    w_gld = weights.get('GLD', 0)
    w_btc = weights.get('BTC', 0)

    # SPY portion uses 12/VIX timing
    spy_component = w_spy * vix_signal_lag * spy_ret
    # When VIX signal < 1, the uninvested SPY portion goes to cash (0 return)

    # GLD is static
    gld_component = w_gld * gld_ret

    # BTC allocation — may be conditional
    if w_btc > 0 and conditional_btc is not None:
        if conditional_btc == 'vix':
            # Only hold BTC when VIX < 20 (calm markets)
            btc_on = (vix_series.shift(1) < 20).astype(float)
            btc_component = w_btc * btc_on * btc_ret
        elif conditional_btc == 'momentum':
            # Only hold BTC when 60-day return > 0
            btc_60d = returns_df['BTC'].rolling(60).sum()
            btc_on = (btc_60d.shift(1) > 0).astype(float)
            btc_component = w_btc * btc_on * btc_ret
        else:
            btc_component = w_btc * btc_ret
    else:
        btc_component = w_btc * btc_ret

    port_ret = spy_component + gld_component + btc_component
    return port_ret

def compute_metrics(port_ret, label=""):
    """Compute comprehensive portfolio metrics."""
    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = port_ret[port_ret < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    # MDD
    cum = (1 + port_ret).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Tail metrics
    skewness = port_ret.skew()
    kurtosis = port_ret.kurtosis()
    cvar_5 = port_ret.quantile(0.05)
    max_monthly_loss = port_ret.rolling(21).sum().min()

    return {
        'label': label,
        'annual_return': float(ann_ret),
        'annual_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'sortino': float(sortino),
        'mdd': float(mdd),
        'calmar': float(calmar),
        'skewness': float(skewness),
        'kurtosis': float(kurtosis),
        'cvar_5pct': float(cvar_5),
        'max_monthly_loss': float(max_monthly_loss) if not np.isnan(max_monthly_loss) else None,
        'n_obs': int(len(port_ret))
    }

def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive ability.
    Here we compare portfolio returns (higher is better),
    so we test if e2 - e1 > 0 significantly.
    """
    d = e2 - e1  # positive means e2 is better
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = d.mean()

    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_0 += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(gamma_0 / n)
    if se < 1e-10:
        return np.nan, np.nan

    t_stat = d_mean / se
    p_value = 1 - stats.t.cdf(t_stat, df=n - 1)  # one-sided: e2 > e1
    return float(t_stat), float(p_value)

# ============================================================
# 4. Define Portfolio Variants
# ============================================================

strategies = {
    'base_50_50': {
        'weights': {'SPY': 0.50, 'GLD': 0.50, 'BTC': 0.00},
        'conditional': None,
        'label': '50/50 SPY/GLD (12/VIX)'
    },
    'btc_5pct': {
        'weights': {'SPY': 0.475, 'GLD': 0.475, 'BTC': 0.05},
        'conditional': None,
        'label': '47.5/47.5/5 + BTC (K66 original)'
    },
    'btc_10pct': {
        'weights': {'SPY': 0.45, 'GLD': 0.45, 'BTC': 0.10},
        'conditional': None,
        'label': '45/45/10 + BTC'
    },
    'btc_20pct': {
        'weights': {'SPY': 0.40, 'GLD': 0.40, 'BTC': 0.20},
        'conditional': None,
        'label': '40/40/20 + BTC (aggressive)'
    },
    'btc_5pct_vix_cond': {
        'weights': {'SPY': 0.475, 'GLD': 0.475, 'BTC': 0.05},
        'conditional': 'vix',
        'label': '47.5/47.5/5 BTC (VIX<20 only)'
    },
    'btc_5pct_momentum': {
        'weights': {'SPY': 0.475, 'GLD': 0.475, 'BTC': 0.05},
        'conditional': 'momentum',
        'label': '47.5/47.5/5 BTC (60d mom>0)'
    },
}

# ============================================================
# 5. Full-Period Analysis
# ============================================================
print("\n" + "=" * 70)
print("FULL-PERIOD ANALYSIS (2015-2026)")
print("=" * 70)

full_results = {}
port_returns = {}

for key, strat in strategies.items():
    pr = portfolio_returns(returns, vix, strat['weights'], strat['conditional'])
    port_returns[key] = pr
    metrics = compute_metrics(pr, strat['label'])
    full_results[key] = metrics
    print(f"\n{strat['label']}:")
    print(f"  Return: {metrics['annual_return']:.4f}  Vol: {metrics['annual_vol']:.4f}  "
          f"Sharpe: {metrics['sharpe']:.4f}  Sortino: {metrics['sortino']:.4f}")
    print(f"  MDD: {metrics['mdd']:.4f}  Calmar: {metrics['calmar']:.4f}  "
          f"Skew: {metrics['skewness']:.4f}  Kurt: {metrics['kurtosis']:.4f}")
    print(f"  CVaR(5%): {metrics['cvar_5pct']:.4f}  Max monthly loss: {metrics['max_monthly_loss']}")

# DM tests vs base
print("\n--- Diebold-Mariano Tests vs Base (50/50) ---")
print(f"{'Strategy':<40} {'t-stat':>8} {'p-value':>10} {'Harvey':>8}")
print("-" * 70)

dm_results = {}
base_ret = port_returns['base_50_50']
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct', 'btc_5pct_vix_cond', 'btc_5pct_momentum']:
    t, p = dm_test(base_ret, port_returns[key])
    sig = "***" if t > 3.0 else ("**" if t > 2.0 else ("*" if t > 1.645 else ""))
    dm_results[key] = {'t_stat': t, 'p_value': p, 'passes_harvey': t > 3.0}
    print(f"  {strategies[key]['label']:<38} {t:>8.3f} {p:>10.4f} {'PASS' if t > 3.0 else 'FAIL':>8} {sig}")

# NOTE: 5%/10%/20% BTC have identical DM t-stats because:
# d_10 = 2 * d_5, d_20 = 4 * d_5 (proportional return difference)
# t = mean(d)/se(d) is scale-invariant: t(c*d) = c*mean / (c*std/sqrt(n)) = t(d)
# This is mathematically correct -- DM tests BTC's significance, not optimal size.
# The choice of 5% vs 10% vs 20% is a risk-preference decision, not statistical.
print("\nNOTE: 5/10/20% BTC identical t-stats are correct (DM is scale-invariant)."
      "\n  d_10pct = 2 * d_5pct exactly, so t-stat is unchanged."
      "\n  Allocation size is a risk-preference choice, not a statistical one.")

# ============================================================
# 6. Cross-OOS Analysis (3 periods)
# ============================================================
print("\n" + "=" * 70)
print("CROSS-OOS ANALYSIS")
print("=" * 70)

oos_periods = {
    'P1_2016_2019': ('2016-01-01', '2019-12-31'),
    'P2_2020_2022': ('2020-01-01', '2022-12-31'),
    'P3_2023_2025': ('2023-01-01', '2025-12-31'),
}

oos_results = {}
for period_name, (start, end) in oos_periods.items():
    mask = (returns.index >= start) & (returns.index <= end)
    ret_sub = returns.loc[mask]
    vix_sub = vix.loc[mask]

    print(f"\n--- {period_name} ({start} to {end}, n={len(ret_sub)}) ---")

    period_results = {}
    period_port_returns = {}

    for key, strat in strategies.items():
        pr = portfolio_returns(ret_sub, vix_sub, strat['weights'], strat['conditional'])
        period_port_returns[key] = pr
        metrics = compute_metrics(pr, strat['label'])
        period_results[key] = metrics

    # Print summary table
    print(f"{'Strategy':<40} {'Sharpe':>8} {'MDD':>8} {'Sortino':>8} {'Skew':>8}")
    print("-" * 70)
    for key, strat in strategies.items():
        m = period_results[key]
        print(f"  {strat['label']:<38} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} "
              f"{m['sortino']:>8.4f} {m['skewness']:>8.4f}")

    # DM tests for this period
    base_sub = period_port_returns['base_50_50']
    print(f"\n  DM tests vs base:")
    period_dm = {}
    for key in ['btc_5pct', 'btc_10pct', 'btc_20pct', 'btc_5pct_vix_cond', 'btc_5pct_momentum']:
        t, p = dm_test(base_sub, period_port_returns[key])
        sig = "***" if t > 3.0 else ("**" if t > 2.0 else ("*" if t > 1.645 else ""))
        period_dm[key] = {'t_stat': float(t) if not np.isnan(t) else None,
                          'p_value': float(p) if not np.isnan(p) else None}
        t_str = f"{t:.3f}" if not np.isnan(t) else "N/A"
        p_str = f"{p:.4f}" if not np.isnan(p) else "N/A"
        print(f"    {strategies[key]['label']:<36} t={t_str:>8} p={p_str:>8} {sig}")

    oos_results[period_name] = {
        'metrics': {k: v for k, v in period_results.items()},
        'dm_tests': period_dm
    }

# ============================================================
# 7. Post-ETF Era Focus (2024-01 to present)
# ============================================================
print("\n" + "=" * 70)
print("POST-ETF ERA ANALYSIS (2024-01 to present)")
print("=" * 70)

mask_etf = returns.index >= '2024-01-01'
ret_etf = returns.loc[mask_etf]
vix_etf = vix.loc[mask_etf]
print(f"ETF era: {len(ret_etf)} observations")

etf_results = {}
etf_port_returns = {}

for key, strat in strategies.items():
    pr = portfolio_returns(ret_etf, vix_etf, strat['weights'], strat['conditional'])
    etf_port_returns[key] = pr
    metrics = compute_metrics(pr, strat['label'])
    etf_results[key] = metrics

print(f"\n{'Strategy':<40} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Sortino':>8} {'Skew':>8}")
print("-" * 90)
for key, strat in strategies.items():
    m = etf_results[key]
    print(f"  {strat['label']:<38} {m['annual_return']:>8.4f} {m['annual_vol']:>8.4f} "
          f"{m['sharpe']:>8.4f} {m['mdd']:>8.4f} {m['sortino']:>8.4f} {m['skewness']:>8.4f}")

# DM tests for ETF era
print(f"\n  DM tests vs base (ETF era):")
etf_dm = {}
base_etf = etf_port_returns['base_50_50']
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct', 'btc_5pct_vix_cond', 'btc_5pct_momentum']:
    t, p = dm_test(base_etf, etf_port_returns[key])
    sig = "***" if t > 3.0 else ("**" if t > 2.0 else ("*" if t > 1.645 else ""))
    etf_dm[key] = {'t_stat': float(t) if not np.isnan(t) else None,
                   'p_value': float(p) if not np.isnan(p) else None}
    t_str = f"{t:.3f}" if not np.isnan(t) else "N/A"
    p_str = f"{p:.4f}" if not np.isnan(p) else "N/A"
    print(f"    {strategies[key]['label']:<36} t={t_str:>8} p={p_str:>8} {sig}")

# ============================================================
# 8. Correlation Structure Analysis (Time-Varying)
# ============================================================
print("\n" + "=" * 70)
print("CORRELATION STRUCTURE ANALYSIS")
print("=" * 70)

# Annual rolling correlations
corr_spy_btc = returns['SPY'].rolling(252).corr(returns['BTC'])
corr_gld_btc = returns['GLD'].rolling(252).corr(returns['BTC'])
corr_spy_gld = returns['SPY'].rolling(252).corr(returns['GLD'])

years = ['2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025']
corr_by_year = {}
print(f"\n{'Year':<8} {'SPY-BTC':>10} {'GLD-BTC':>10} {'SPY-GLD':>10}")
print("-" * 40)
for yr in years:
    mask_yr = returns.index.year == int(yr)
    if mask_yr.sum() < 50:
        continue
    r_yr = returns.loc[mask_yr]
    c_sb = r_yr['SPY'].corr(r_yr['BTC'])
    c_gb = r_yr['GLD'].corr(r_yr['BTC'])
    c_sg = r_yr['SPY'].corr(r_yr['GLD'])
    corr_by_year[yr] = {'SPY_BTC': float(c_sb), 'GLD_BTC': float(c_gb), 'SPY_GLD': float(c_sg)}
    print(f"  {yr:<6} {c_sb:>10.4f} {c_gb:>10.4f} {c_sg:>10.4f}")

# ============================================================
# 9. Coskewness Analysis (Portfolio-Level Tail Risk)
# ============================================================
print("\n" + "=" * 70)
print("COSKEWNESS & TAIL RISK ANALYSIS")
print("=" * 70)

# Portfolio skewness and worst drawdowns
tail_analysis = {}
for key, strat in strategies.items():
    pr = port_returns[key]

    # Bottom 1% days
    q01 = pr.quantile(0.01)
    worst_days = pr[pr <= q01]

    # Correlation during crashes (bottom 5% of SPY)
    spy_crash = returns['SPY'].quantile(0.05)
    crash_mask = returns['SPY'] <= spy_crash
    if 'BTC' in strat['weights'] and strat['weights']['BTC'] > 0:
        crash_corr = returns.loc[crash_mask, 'SPY'].corr(returns.loc[crash_mask, 'BTC'])
    else:
        crash_corr = np.nan

    tail_analysis[key] = {
        'skewness': float(pr.skew()),
        'kurtosis': float(pr.kurtosis()),
        'var_1pct': float(q01),
        'cvar_1pct': float(pr[pr <= q01].mean()),
        'crash_corr_spy_btc': float(crash_corr) if not np.isnan(crash_corr) else None,
        'worst_5_days': [float(x) for x in pr.nsmallest(5).values]
    }

    print(f"\n{strat['label']}:")
    print(f"  Skewness: {pr.skew():.4f}  Kurtosis: {pr.kurtosis():.4f}")
    print(f"  VaR(1%): {q01:.4f}  CVaR(1%): {pr[pr <= q01].mean():.4f}")
    if not np.isnan(crash_corr):
        print(f"  Crash correlation (SPY-BTC during SPY bottom 5%): {crash_corr:.4f}")
    print(f"  Worst 5 days: {[f'{x:.4f}' for x in pr.nsmallest(5).values]}")

# ============================================================
# 10. Bootstrap Confidence Intervals for Sharpe Difference
# ============================================================
print("\n" + "=" * 70)
print("BOOTSTRAP ANALYSIS (10,000 reps)")
print("=" * 70)

np.random.seed(42)
n_boot = 10000
n = len(base_ret)

boot_results = {}
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct', 'btc_5pct_vix_cond', 'btc_5pct_momentum']:
    strat_ret = port_returns[key]

    # Aligned returns
    aligned = pd.DataFrame({'base': base_ret, 'strat': strat_ret}).dropna()
    base_arr = aligned['base'].values
    strat_arr = aligned['strat'].values
    n_aligned = len(aligned)

    sharpe_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n_aligned, n_aligned)
        base_b = base_arr[idx]
        strat_b = strat_arr[idx]

        sharpe_base = base_b.mean() / base_b.std() * np.sqrt(252)
        sharpe_strat = strat_b.mean() / strat_b.std() * np.sqrt(252)
        sharpe_diffs[b] = sharpe_strat - sharpe_base

    ci_lower = np.percentile(sharpe_diffs, 2.5)
    ci_upper = np.percentile(sharpe_diffs, 97.5)
    pct_positive = (sharpe_diffs > 0).mean()

    boot_results[key] = {
        'mean_sharpe_diff': float(sharpe_diffs.mean()),
        'ci_95_lower': float(ci_lower),
        'ci_95_upper': float(ci_upper),
        'pct_positive': float(pct_positive),
        'se': float(sharpe_diffs.std())
    }

    print(f"\n{strategies[key]['label']}:")
    print(f"  Mean Sharpe diff: {sharpe_diffs.mean():+.4f}")
    print(f"  95% CI: [{ci_lower:+.4f}, {ci_upper:+.4f}]")
    print(f"  P(Sharpe_BTC > Sharpe_base): {pct_positive:.4f}")

# ============================================================
# 11. Rolling Window Analysis (3-year windows)
# ============================================================
print("\n" + "=" * 70)
print("ROLLING 3-YEAR WINDOW ANALYSIS")
print("=" * 70)

window_size = 756  # ~3 years
step = 63  # ~quarterly step

rolling_wins = {}
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct']:
    wins = 0
    total = 0
    sharpe_diffs_roll = []

    for start_idx in range(0, len(base_ret) - window_size, step):
        end_idx = start_idx + window_size
        base_w = base_ret.iloc[start_idx:end_idx]
        strat_w = port_returns[key].iloc[start_idx:end_idx]

        s_base = base_w.mean() / base_w.std() * np.sqrt(252)
        s_strat = strat_w.mean() / strat_w.std() * np.sqrt(252)

        diff = s_strat - s_base
        sharpe_diffs_roll.append(diff)

        if diff > 0:
            wins += 1
        total += 1

    win_rate = wins / total if total > 0 else 0
    rolling_wins[key] = {
        'win_rate': float(win_rate),
        'total_windows': int(total),
        'wins': int(wins),
        'mean_sharpe_diff': float(np.mean(sharpe_diffs_roll)),
        'min_sharpe_diff': float(np.min(sharpe_diffs_roll)),
        'max_sharpe_diff': float(np.max(sharpe_diffs_roll))
    }

    print(f"\n{strategies[key]['label']}:")
    print(f"  Win rate: {win_rate:.1%} ({wins}/{total} windows)")
    print(f"  Mean Sharpe diff: {np.mean(sharpe_diffs_roll):+.4f}")
    print(f"  Range: [{np.min(sharpe_diffs_roll):+.4f}, {np.max(sharpe_diffs_roll):+.4f}]")

# ============================================================
# 12. Comparison: K66 vs K565 (Key Metrics Side-by-Side)
# ============================================================
print("\n" + "=" * 70)
print("K66 vs K565 COMPARISON")
print("=" * 70)

# K66 reported values (from knowledge base)
k66_values = {
    'btc_5pct_p_value': 0.014,
    'portfolio_skewness_base': -0.31,
    'portfolio_skewness_btc5': -0.50,
    'crash_correlation': 0.44,
    'btc_spy_corr_pre2020': 'near zero',
    'btc_spy_corr_post2020': '0.43-0.56',
    'rolling_3yr_win_rate': 0.97,
}

print(f"\n{'Metric':<35} {'K66 (old)':>12} {'K565 (new)':>12}")
print("-" * 60)
print(f"  {'5% BTC DM p-value':<33} {'0.014':>12} {dm_results['btc_5pct']['p_value']:>12.4f}")
print(f"  {'Base skewness':<33} {'-0.31':>12} {full_results['base_50_50']['skewness']:>12.4f}")
print(f"  {'5% BTC skewness':<33} {'-0.50':>12} {full_results['btc_5pct']['skewness']:>12.4f}")
print(f"  {'Crash corr SPY-BTC':<33} {'0.44':>12} {tail_analysis['btc_5pct']['crash_corr_spy_btc']:>12.4f}" if tail_analysis['btc_5pct']['crash_corr_spy_btc'] else "")
print(f"  {'3yr rolling win rate (5%)':<33} {'97%':>12} {rolling_wins['btc_5pct']['win_rate']:>12.1%}")
print(f"  {'Base Sharpe':<33} {'(not recorded)':>12} {full_results['base_50_50']['sharpe']:>12.4f}")
print(f"  {'5% BTC Sharpe':<33} {'(not recorded)':>12} {full_results['btc_5pct']['sharpe']:>12.4f}")

# ============================================================
# 13. Transaction Cost Sensitivity
# ============================================================
print("\n" + "=" * 70)
print("TRANSACTION COST SENSITIVITY")
print("=" * 70)

# For BTC: higher TX costs due to spread + exchange fees
# Assume monthly rebalancing = 12 trades/year
# BTC spread: 5-20 bps (institutional ETF ~5bps, exchange ~10-20bps)
tx_costs_bps = [0, 5, 10, 20, 50]  # annual TX drag in bps

print(f"\n{'Strategy':<35} ", end="")
for tc in tx_costs_bps:
    print(f"{'TC=' + str(tc) + 'bps':>10}", end="")
print()
print("-" * 85)

tc_analysis = {}
for key in ['base_50_50', 'btc_5pct', 'btc_10pct', 'btc_20pct']:
    strat = strategies[key]
    base_sharpe = full_results[key]['sharpe']

    tc_analysis[key] = {}
    print(f"  {strat['label']:<33} ", end="")
    for tc in tx_costs_bps:
        # TX drag is proportional to BTC weight (BTC has most turnover)
        btc_w = strat['weights']['BTC']
        # Total annual TC = btc_weight * tc_bps * 12 (monthly rebalance) * 2 (buy+sell)
        # Plus SPY portion has VIX-dependent turnover (~monthly effective)
        annual_drag = (btc_w * tc / 10000 * 24 + 0.50 * tc / 10000 * 12)  # BTC + SPY
        net_ret = full_results[key]['annual_return'] - annual_drag
        net_sharpe = net_ret / full_results[key]['annual_vol']
        tc_analysis[key][f'tc_{tc}bps'] = float(net_sharpe)
        print(f"  {net_sharpe:>8.4f}", end="")
    print()

# ============================================================
# 14. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

# Determine which strategies pass Harvey threshold
passing_strategies = [k for k, v in dm_results.items() if v.get('passes_harvey', False)]
print(f"\nStrategies passing Harvey t>3.0 threshold: {passing_strategies if passing_strategies else 'NONE'}")

# Cross-OOS consistency
print("\nCross-OOS Sharpe improvement consistency:")
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct']:
    improvements = 0
    total_periods = 0
    for period_name in oos_periods:
        base_s = oos_results[period_name]['metrics']['base_50_50']['sharpe']
        strat_s = oos_results[period_name]['metrics'][key]['sharpe']
        if strat_s > base_s:
            improvements += 1
        total_periods += 1
    print(f"  {strategies[key]['label']}: {improvements}/{total_periods} periods improved")

# Key finding about ETF era
print(f"\nPost-ETF era (2024+) findings:")
for key in ['btc_5pct', 'btc_10pct', 'btc_20pct']:
    m = etf_results[key]
    base_m = etf_results['base_50_50']
    print(f"  {strategies[key]['label']}:")
    print(f"    Sharpe: {m['sharpe']:.4f} vs base {base_m['sharpe']:.4f} (diff: {m['sharpe']-base_m['sharpe']:+.4f})")
    print(f"    MDD: {m['mdd']:.4f} vs base {base_m['mdd']:.4f}")

# ============================================================
# 15. Save Results
# ============================================================
results = {
    'experiment_id': 'K565',
    'title': 'Bitcoin Allocation in VT Portfolio — Revisiting K66',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, GLD, BTC-USD, ^VIX)',
    'data_period': f"{prices.index[0].date()} to {prices.index[-1].date()}",
    'n_observations': int(len(returns)),
    'references': ['K66', 'K78', 'Bouri et al. 2017', 'Platanakis & Urquhart 2020', 'Liu & Tsyvinski 2021'],
    'methodology': '12/VIX timing on SPY portion, static GLD, fixed/conditional BTC allocation',
    'descriptive_stats': desc_stats,
    'correlation_by_year': corr_by_year,
    'full_period_metrics': full_results,
    'dm_tests_full': dm_results,
    'cross_oos': oos_results,
    'etf_era_metrics': etf_results,
    'etf_era_dm_tests': etf_dm,
    'tail_analysis': tail_analysis,
    'bootstrap': boot_results,
    'rolling_windows': rolling_wins,
    'tx_cost_sensitivity': tc_analysis,
    'conclusions': {
        'harvey_passing': passing_strategies,
        'key_findings': [],
        'dm_scale_invariance_note': (
            '5%/10%/20% BTC have identical DM t-stats because d_10=2*d_5, d_20=4*d_5. '
            'The DM t-statistic is scale-invariant: t(c*d) = c*mean/(c*std/sqrt(n)) = t(d). '
            'This means DM tests whether BTC adds significant return, but cannot distinguish '
            'optimal allocation size. The 5% vs 10% vs 20% choice is purely risk-preference.'
        ),
        'limitations': [
            'BTC data from yfinance may have survivorship bias (only successful crypto)',
            'No futures/ETF fee drag modeled for BTC portion',
            'Monthly rebalancing assumed; daily rebalancing would increase TX costs',
            'VIX-conditional BTC uses same-day VIX (lagged 1 day to avoid look-ahead)',
            'Short sample for post-ETF era (~2 years)',
            'No staking yield or lending income modeled for BTC allocation',
            'DM t-stats identical for 5/10/20% BTC (scale-invariance) — allocation sizing is risk-preference not statistical'
        ]
    }
}

# Fill in key findings based on actual results
findings = []

# Finding 1: Harvey threshold
if len(passing_strategies) > 0:
    findings.append(f"Strategies passing Harvey t>3.0: {', '.join(passing_strategies)}")
else:
    findings.append("No BTC allocation strategy passes the Harvey (2016) t>3.0 threshold on full sample")

# Finding 2: 5% BTC significance
findings.append(
    f"5% BTC (K66 original): DM t={dm_results['btc_5pct']['t_stat']:.3f}, "
    f"p={dm_results['btc_5pct']['p_value']:.4f} (K66 had p=0.014)"
)

# Finding 3: Skewness cost
findings.append(
    f"Skewness cost: base={full_results['base_50_50']['skewness']:.3f}, "
    f"5% BTC={full_results['btc_5pct']['skewness']:.3f}, "
    f"10% BTC={full_results['btc_10pct']['skewness']:.3f}, "
    f"20% BTC={full_results['btc_20pct']['skewness']:.3f}"
)

# Finding 4: ETF era
findings.append(
    f"Post-ETF era (2024+): 5% BTC Sharpe={etf_results['btc_5pct']['sharpe']:.4f} "
    f"vs base {etf_results['base_50_50']['sharpe']:.4f}"
)

# Finding 5: Conditional strategies
findings.append(
    f"VIX-conditional 5% BTC: Sharpe={full_results['btc_5pct_vix_cond']['sharpe']:.4f}, "
    f"Momentum 5% BTC: Sharpe={full_results['btc_5pct_momentum']['sharpe']:.4f}"
)

# Finding 6: Correlation regime change
if '2024' in corr_by_year and '2016' in corr_by_year:
    findings.append(
        f"SPY-BTC correlation regime shift: 2016={corr_by_year['2016']['SPY_BTC']:.3f} → "
        f"2024={corr_by_year['2024']['SPY_BTC']:.3f}"
    )

results['conclusions']['key_findings'] = findings

# Save
output_path = 'experiments/k565_btc_allocation_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("\n" + "=" * 70)
print("EXPERIMENT K565 COMPLETE")
print("=" * 70)
