#!/usr/bin/env python3
"""
K344: Cross-Commodity Hedge Portfolio — Optimal Diversification Across Futures
==============================================================================
[提出: 用戶, 執行: Claude]

Background:
  K341 established futures hedging framework.
  K342 showed oil has different vol dynamics.
  Can a PORTFOLIO of commodity futures provide better diversification than GLD alone?

Data: yfinance
  - GC=F (Gold futures), CL=F (Oil futures), HG=F (Copper futures),
    NG=F (Natural Gas futures), SI=F (Silver futures)
  - SPY, ^VIX

Methodology:
  1. Correlation matrix of 5 commodity futures (full sample + VIX regimes)
  2. Equal-weight commodity portfolio vs GLD alone (vol, Sharpe, MDD, corr w/ SPY)
  3. Portfolio construction:
     a. 50/50 SPY / EW-Commodity (5 commodities)
     b. 50/50 SPY / GC=F (gold futures only)
     c. 50/50 SPY / (GC=F + CL=F + HG=F) EW 3-commodity
     d. 50/50 SPY / GLD (benchmark)
  4. VT overlay: 12/VIX on each portfolio
  5. KEY QUESTION: Is GLD's diversification benefit unique, or do other commodities too?
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
print("K344: Cross-Commodity Hedge Portfolio")
print("=" * 70)

tickers = {
    'GC=F': 'Gold Futures',
    'CL=F': 'WTI Crude Oil Futures',
    'HG=F': 'Copper Futures',
    'NG=F': 'Natural Gas Futures',
    'SI=F': 'Silver Futures',
    'SPY':  'S&P 500 ETF',
    '^VIX': 'VIX',
}

print("\n[1] Downloading data from yfinance...")
raw = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            raw[ticker] = df['Close'].squeeze()
            print(f"  {ticker:8s} ({desc}): {len(df):,} rows, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {ticker:8s}: NO DATA")
    except Exception as e:
        print(f"  {ticker:8s}: ERROR — {e}")

# CL=F sometimes fails with yfinance. Try USO as oil proxy if CL=F missing.
if 'CL=F' not in raw:
    print("  CL=F failed, trying USO (US Oil Fund ETF) as oil proxy...")
    try:
        df = yf.download('USO', start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            raw['CL=F'] = df['Close'].squeeze()  # label as CL=F for consistency
            print(f"  USO (Oil proxy for CL=F): {len(df):,} rows, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print("  USO: NO DATA either")
    except Exception as e:
        print(f"  USO: ERROR — {e}")

# If oil still missing, try BNO (Brent Oil Fund)
if 'CL=F' not in raw:
    print("  USO also failed. Trying BNO (Brent Oil Fund)...")
    try:
        df = yf.download('BNO', start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            raw['CL=F'] = df['Close'].squeeze()
            print(f"  BNO (Oil proxy for CL=F): {len(df):,} rows")
        else:
            print("  BNO: NO DATA either, proceeding without oil")
    except Exception as e:
        print(f"  BNO: ERROR — {e}")

# GC=F sometimes fails too. Use GLD as gold proxy.
if 'GC=F' not in raw:
    print("  GC=F failed, trying GLD as gold proxy...")
    try:
        df = yf.download('GLD', start='2005-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            raw['GC=F'] = df['Close'].squeeze()  # label as GC=F for consistency
            print(f"  GLD (Gold proxy for GC=F): {len(df):,} rows, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
            # Flag that we used GLD
            RESULTS['gold_proxy'] = 'GLD (ETF) used as GC=F proxy'
        else:
            print("  GLD: NO DATA either")
    except Exception as e:
        print(f"  GLD: ERROR — {e}")

# Check which commodities we actually have
available_commodities = [c for c in ['GC=F', 'CL=F', 'HG=F', 'NG=F', 'SI=F'] if c in raw]
print(f"\n  Available commodities: {available_commodities}")
if len(available_commodities) < 3:
    print("  WARNING: Less than 3 commodities available, results will be limited")

# Align to common dates
prices = pd.DataFrame(raw)
prices = prices.dropna()
print(f"\n  Common date range: {prices.index[0].strftime('%Y-%m-%d')} to "
      f"{prices.index[-1].strftime('%Y-%m-%d')} ({len(prices):,} days)")

RESULTS['data'] = {
    'common_start': prices.index[0].strftime('%Y-%m-%d'),
    'common_end': prices.index[-1].strftime('%Y-%m-%d'),
    'n_days': len(prices),
    'tickers': list(prices.columns),
}

# Daily returns
rets = prices.pct_change().dropna()
# Rename VIX column for clarity
vix_col = '^VIX'
commodity_cols = [c for c in ['GC=F', 'CL=F', 'HG=F', 'NG=F', 'SI=F'] if c in prices.columns]
spy_col = 'SPY'
print(f"  Using {len(commodity_cols)} commodity futures: {commodity_cols}")

# ============================================================
# 2. Commodity Correlation Matrix (Full Sample)
# ============================================================
print("\n" + "=" * 70)
print("[2] Commodity Correlation Matrix (Full Sample)")
print("=" * 70)

comm_rets = rets[commodity_cols]
corr_full = comm_rets.corr()
print("\nDaily return correlations among 5 commodity futures:")
print(corr_full.round(3).to_string())

# Find most/least correlated pairs
pairs = []
for i, c1 in enumerate(commodity_cols):
    for j, c2 in enumerate(commodity_cols):
        if i < j:
            pairs.append((c1, c2, corr_full.loc[c1, c2]))

pairs_sorted = sorted(pairs, key=lambda x: x[2], reverse=True)
print(f"\n  Most correlated:  {pairs_sorted[0][0]} & {pairs_sorted[0][1]}: "
      f"{pairs_sorted[0][2]:.4f}")
print(f"  Least correlated: {pairs_sorted[-1][0]} & {pairs_sorted[-1][1]}: "
      f"{pairs_sorted[-1][2]:.4f}")

RESULTS['correlation_full'] = {
    'matrix': {c1: {c2: round(corr_full.loc[c1, c2], 4) for c2 in commodity_cols}
               for c1 in commodity_cols},
    'most_correlated': {'pair': f"{pairs_sorted[0][0]} & {pairs_sorted[0][1]}",
                        'corr': round(pairs_sorted[0][2], 4)},
    'least_correlated': {'pair': f"{pairs_sorted[-1][0]} & {pairs_sorted[-1][1]}",
                         'corr': round(pairs_sorted[-1][2], 4)},
}

# Correlation of each commodity with SPY
spy_corrs = {}
print("\n  Commodity correlations with SPY:")
for c in commodity_cols:
    r = rets[c].corr(rets[spy_col])
    spy_corrs[c] = round(r, 4)
    print(f"    {c:8s}: {r:+.4f}")

RESULTS['correlation_with_spy'] = spy_corrs

# ============================================================
# 3. VIX Regime-Dependent Correlations
# ============================================================
print("\n" + "=" * 70)
print("[3] VIX Regime-Dependent Correlations")
print("=" * 70)

vix_levels = prices[vix_col].reindex(rets.index).dropna()
common_idx = vix_levels.index.intersection(rets.index)
vix_for_regime = vix_levels.loc[common_idx]

low_mask = vix_for_regime < 15
mid_mask = (vix_for_regime >= 15) & (vix_for_regime < 25)
high_mask = vix_for_regime >= 25

regime_corrs = {}
for regime_name, mask in [('low_vix_lt15', low_mask), ('mid_vix_15_25', mid_mask),
                           ('high_vix_gt25', high_mask)]:
    idx = mask[mask].index
    if len(idx) < 30:
        print(f"\n  {regime_name}: Only {len(idx)} obs, skipping")
        continue
    sub = rets.loc[idx]
    corr_regime = sub[commodity_cols].corr()
    spy_corr_regime = {c: round(sub[c].corr(sub[spy_col]), 4) for c in commodity_cols}

    print(f"\n  {regime_name} ({len(idx):,} days):")
    print(f"    Commodity-SPY correlations:")
    for c in commodity_cols:
        print(f"      {c:8s}: {spy_corr_regime[c]:+.4f}")

    regime_corrs[regime_name] = {
        'n_days': int(len(idx)),
        'commodity_spy_corr': spy_corr_regime,
        'inter_commodity_avg_corr': round(
            corr_regime.values[np.triu_indices_from(corr_regime.values, k=1)].mean(), 4),
    }

RESULTS['regime_correlations'] = regime_corrs

# ============================================================
# 4. Individual Commodity Performance Stats
# ============================================================
print("\n" + "=" * 70)
print("[4] Individual Commodity Performance Stats")
print("=" * 70)

def compute_stats(ret_series, name):
    """Compute ann return, vol, Sharpe, MDD, skew, kurtosis."""
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + ret_series).cumprod()
    dd = cum / cum.cummax() - 1
    mdd = dd.min()
    return {
        'name': name,
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'skew': round(float(ret_series.skew()), 4),
        'kurtosis': round(float(ret_series.kurtosis()), 4),
    }

print(f"\n{'Asset':10s} {'Ann Ret':>8s} {'Ann Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} "
      f"{'Skew':>8s} {'Kurt':>8s}")
print("-" * 62)

indiv_stats = {}
for c in commodity_cols + [spy_col]:
    s = compute_stats(rets[c], c)
    indiv_stats[c] = s
    print(f"{c:10s} {s['ann_return']:>8.2%} {s['ann_vol']:>8.2%} {s['sharpe']:>8.3f} "
          f"{s['mdd']:>8.2%} {s['skew']:>8.3f} {s['kurtosis']:>8.2f}")

RESULTS['individual_stats'] = indiv_stats

# ============================================================
# 5. Equal-Weight Commodity Portfolio vs GLD Alone
# ============================================================
print("\n" + "=" * 70)
print("[5] Equal-Weight (EW) Commodity Portfolio vs Gold Alone")
print("=" * 70)

# EW commodity = simple average of 5 commodity returns
ew_comm_ret = comm_rets.mean(axis=1)
gc_ret = rets['GC=F']

n_comm = len(commodity_cols)
ew_stats = compute_stats(ew_comm_ret, f'EW-{n_comm}-Commodity')
gc_stats = compute_stats(gc_ret, 'GC=F (Gold)')

ew_spy_corr = ew_comm_ret.corr(rets[spy_col])
gc_spy_corr = gc_ret.corr(rets[spy_col])

print(f"\n{'Portfolio':20s} {'Ann Ret':>8s} {'Ann Vol':>8s} {'Sharpe':>8s} "
      f"{'MDD':>8s} {'Corr(SPY)':>10s}")
print("-" * 62)
print(f"{'EW-5-Commodity':20s} {ew_stats['ann_return']:>8.2%} {ew_stats['ann_vol']:>8.2%} "
      f"{ew_stats['sharpe']:>8.3f} {ew_stats['mdd']:>8.2%} {ew_spy_corr:>10.4f}")
print(f"{'GC=F (Gold)':20s} {gc_stats['ann_return']:>8.2%} {gc_stats['ann_vol']:>8.2%} "
      f"{gc_stats['sharpe']:>8.3f} {gc_stats['mdd']:>8.2%} {gc_spy_corr:>10.4f}")

RESULTS['ew_vs_gold'] = {
    'ew_5_commodity': {**ew_stats, 'corr_spy': round(float(ew_spy_corr), 4)},
    'gc_gold': {**gc_stats, 'corr_spy': round(float(gc_spy_corr), 4)},
    'conclusion': ('EW diversifies vol but may increase SPY correlation '
                   'if industrial commodities (copper, oil) are pro-cyclical'),
}

# ============================================================
# 6. Portfolio Construction — 4 Portfolios
# ============================================================
print("\n" + "=" * 70)
print("[6] Portfolio Construction (50/50 with SPY)")
print("=" * 70)

spy_ret = rets[spy_col]

# Portfolio A: 50/50 SPY / EW-5-Commodity
port_a_ret = 0.5 * spy_ret + 0.5 * ew_comm_ret

# Portfolio B: 50/50 SPY / GC=F
port_b_ret = 0.5 * spy_ret + 0.5 * gc_ret

# Portfolio C: 50/50 SPY / EW(GC+CL+HG) 3-commodity (use available ones)
three_comm = [c for c in ['GC=F', 'CL=F', 'HG=F'] if c in commodity_cols]
print(f"  3-commodity basket: {three_comm}")
ew3_ret = rets[three_comm].mean(axis=1)
port_c_ret = 0.5 * spy_ret + 0.5 * ew3_ret

# Portfolio D (benchmark): 50/50 SPY / GLD
# If we already used GLD as GC=F proxy, use the same data; otherwise download fresh
if RESULTS.get('gold_proxy'):
    print("  Using GLD data (already downloaded as GC=F proxy) for benchmark")
    gld_ret_raw = gc_ret.copy()  # GC=F IS GLD in this case
else:
    print("  Downloading GLD for benchmark...")
    gld_data = yf.download('GLD', start='2005-01-01', end='2026-03-25',
                           progress=False, auto_adjust=True)
    gld_ret_raw = gld_data['Close'].squeeze().pct_change().dropna()

# Align all to common index
common_all = spy_ret.index.intersection(ew_comm_ret.index).intersection(gld_ret_raw.index)
spy_ret_a = spy_ret.loc[common_all]
gld_ret_a = gld_ret_raw.loc[common_all]
port_a_a = (0.5 * spy_ret.loc[common_all] + 0.5 * ew_comm_ret.loc[common_all])
port_b_a = (0.5 * spy_ret.loc[common_all] + 0.5 * gc_ret.loc[common_all])
port_c_a = (0.5 * spy_ret.loc[common_all] + 0.5 * ew3_ret.loc[common_all])
port_d_a = (0.5 * spy_ret.loc[common_all] + 0.5 * gld_ret_a)

portfolios = {
    'A_SPY_EW5Comm':   port_a_a,
    'B_SPY_GoldFut':   port_b_a,
    'C_SPY_EW3Comm':   port_c_a,
    'D_SPY_GLD':       port_d_a,
    'SPY_only':        spy_ret_a,
}

print(f"\n  Common period: {common_all[0].strftime('%Y-%m-%d')} to "
      f"{common_all[-1].strftime('%Y-%m-%d')} ({len(common_all):,} days)")

print(f"\n{'Portfolio':22s} {'Ann Ret':>8s} {'Ann Vol':>8s} {'Sharpe':>8s} "
      f"{'MDD':>8s} {'Corr(SPY)':>10s}")
print("-" * 64)

port_stats = {}
for name, ret_s in portfolios.items():
    s = compute_stats(ret_s, name)
    corr_spy = ret_s.corr(spy_ret_a)
    s['corr_spy'] = round(float(corr_spy), 4)
    port_stats[name] = s
    print(f"{name:22s} {s['ann_return']:>8.2%} {s['ann_vol']:>8.2%} "
          f"{s['sharpe']:>8.3f} {s['mdd']:>8.2%} {corr_spy:>10.4f}")

RESULTS['portfolio_stats'] = port_stats

# ============================================================
# 7. Drawdown Analysis — Which Portfolio Survives Crises Best?
# ============================================================
print("\n" + "=" * 70)
print("[7] Crisis Drawdown Analysis")
print("=" * 70)

# Compute cumulative returns
cum_rets = {}
for name, ret_s in portfolios.items():
    cum_rets[name] = (1 + ret_s).cumprod()

# Key crisis periods
crises = {
    'GFC_2008':       ('2007-10-01', '2009-03-31'),
    'COVID_2020':     ('2020-01-01', '2020-04-30'),
    'Rate_Hike_2022': ('2022-01-01', '2022-12-31'),
}

crisis_results = {}
for crisis_name, (start, end) in crises.items():
    print(f"\n  {crisis_name}:")
    crisis_data = {}
    for port_name, ret_s in portfolios.items():
        mask = (ret_s.index >= start) & (ret_s.index <= end)
        crisis_ret = ret_s[mask]
        if len(crisis_ret) < 10:
            continue
        cum = (1 + crisis_ret).cumprod()
        dd = cum / cum.cummax() - 1
        mdd = dd.min()
        total_ret = cum.iloc[-1] - 1
        crisis_data[port_name] = {
            'mdd': round(float(mdd), 4),
            'total_return': round(float(total_ret), 4),
        }
        print(f"    {port_name:22s}  MDD: {mdd:>8.2%}  Total Return: {total_ret:>8.2%}")
    crisis_results[crisis_name] = crisis_data

RESULTS['crisis_drawdowns'] = crisis_results

# ============================================================
# 8. VT Overlay — 12/VIX Allocation on Each Portfolio
# ============================================================
print("\n" + "=" * 70)
print("[8] VT Overlay (12/VIX) on Each Portfolio")
print("=" * 70)

vix_for_vt = prices[vix_col].shift(1).reindex(common_all).dropna()
vt_idx = vix_for_vt.index.intersection(pd.DatetimeIndex(common_all))

# VT weight: min(12/VIX, 1.5) — capped at 150%
vt_weight = (12.0 / vix_for_vt.loc[vt_idx]).clip(upper=1.5)

# Cash rate proxy (roughly 2% annual)
daily_rf = 0.02 / 252

print(f"\n  VT period: {vt_idx[0].strftime('%Y-%m-%d')} to "
      f"{vt_idx[-1].strftime('%Y-%m-%d')} ({len(vt_idx):,} days)")
print(f"  Avg VT weight: {vt_weight.mean():.3f}")
print(f"  VT weight range: [{vt_weight.min():.3f}, {vt_weight.max():.3f}]")

print(f"\n{'Portfolio':22s} {'No VT Sharpe':>12s} {'VT Sharpe':>12s} {'VT Improve':>12s} "
      f"{'VT MDD':>8s}")
print("-" * 72)

vt_results = {}
for name, ret_s in portfolios.items():
    # No-VT stats
    no_vt = ret_s.loc[vt_idx]
    no_vt_ann_ret = no_vt.mean() * 252
    no_vt_ann_vol = no_vt.std() * np.sqrt(252)
    no_vt_sharpe = no_vt_ann_ret / no_vt_ann_vol if no_vt_ann_vol > 0 else 0

    # VT overlay
    vt_ret = vt_weight * ret_s.loc[vt_idx] + (1 - vt_weight) * daily_rf
    vt_ann_ret = vt_ret.mean() * 252
    vt_ann_vol = vt_ret.std() * np.sqrt(252)
    vt_sharpe = vt_ann_ret / vt_ann_vol if vt_ann_vol > 0 else 0

    # VT MDD
    vt_cum = (1 + vt_ret).cumprod()
    vt_dd = vt_cum / vt_cum.cummax() - 1
    vt_mdd = vt_dd.min()

    improvement = vt_sharpe - no_vt_sharpe

    vt_results[name] = {
        'no_vt_sharpe': round(float(no_vt_sharpe), 4),
        'vt_sharpe': round(float(vt_sharpe), 4),
        'vt_improvement': round(float(improvement), 4),
        'vt_mdd': round(float(vt_mdd), 4),
        'vt_ann_return': round(float(vt_ann_ret), 4),
        'vt_ann_vol': round(float(vt_ann_vol), 4),
    }

    print(f"{name:22s} {no_vt_sharpe:>12.4f} {vt_sharpe:>12.4f} "
          f"{improvement:>+12.4f} {vt_mdd:>8.2%}")

RESULTS['vt_overlay'] = vt_results

# ============================================================
# 9. Rolling Correlation — Does Diversification Benefit Persist?
# ============================================================
print("\n" + "=" * 70)
print("[9] Rolling 252-Day Correlation with SPY")
print("=" * 70)

roll_window = 252
rolling_corr_data = {}

for name, ret_col in [('GC=F', gc_ret), ('EW-5-Commodity', ew_comm_ret),
                       ('CL=F', rets['CL=F']), ('HG=F', rets['HG=F']),
                       ('NG=F', rets['NG=F']), ('SI=F', rets['SI=F'])]:
    rc = ret_col.rolling(roll_window).corr(spy_ret)
    rc = rc.dropna()
    rolling_corr_data[name] = {
        'mean': round(float(rc.mean()), 4),
        'min': round(float(rc.min()), 4),
        'max': round(float(rc.max()), 4),
        'std': round(float(rc.std()), 4),
        'pct_negative': round(float((rc < 0).mean()), 4),
    }
    print(f"  {name:18s} Mean={rc.mean():+.4f}  Min={rc.min():+.4f}  "
          f"Max={rc.max():+.4f}  %Negative={100*(rc<0).mean():.1f}%")

RESULTS['rolling_corr_with_spy'] = rolling_corr_data

# ============================================================
# 10. Optimal Commodity Mix (Mean-Variance on Commodities Only)
# ============================================================
print("\n" + "=" * 70)
print("[10] Optimal Commodity Mix — Min-Variance & Max-Sharpe")
print("=" * 70)

from scipy.optimize import minimize

comm_rets_aligned = rets[commodity_cols].loc[common_all]
n_assets = len(commodity_cols)
mu = comm_rets_aligned.mean().values * 252
cov = comm_rets_aligned.cov().values * 252

def port_vol(w, cov_mat):
    return np.sqrt(w @ cov_mat @ w)

def neg_sharpe(w, mu_vec, cov_mat):
    ret = w @ mu_vec
    vol = np.sqrt(w @ cov_mat @ w)
    return -ret / vol if vol > 0 else 0

constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
bounds = [(0, 1)] * n_assets

# Min-variance portfolio
res_mv = minimize(port_vol, np.ones(n_assets)/n_assets, args=(cov,),
                  method='SLSQP', bounds=bounds, constraints=constraints)
w_mv = res_mv.x

# Max-Sharpe portfolio
res_ms = minimize(neg_sharpe, np.ones(n_assets)/n_assets, args=(mu, cov),
                  method='SLSQP', bounds=bounds, constraints=constraints)
w_ms = res_ms.x

print("\n  Min-Variance Commodity Weights:")
for i, c in enumerate(commodity_cols):
    print(f"    {c:8s}: {w_mv[i]:.4f}")
mv_ret = w_mv @ mu
mv_vol = port_vol(w_mv, cov)
print(f"    Portfolio: Ann Ret={mv_ret:.4f}, Ann Vol={mv_vol:.4f}, Sharpe={mv_ret/mv_vol:.4f}")

print("\n  Max-Sharpe Commodity Weights:")
for i, c in enumerate(commodity_cols):
    print(f"    {c:8s}: {w_ms[i]:.4f}")
ms_ret = w_ms @ mu
ms_vol = port_vol(w_ms, cov)
print(f"    Portfolio: Ann Ret={ms_ret:.4f}, Ann Vol={ms_vol:.4f}, Sharpe={ms_ret/ms_vol:.4f}")

# Compute actual performance of min-variance commodity mix + SPY
opt_comm_ret = comm_rets_aligned @ w_mv
opt_port_ret = 0.5 * spy_ret_a + 0.5 * opt_comm_ret
opt_stats = compute_stats(opt_port_ret, 'SPY+OptComm')
opt_spy_corr = opt_comm_ret.corr(spy_ret_a)

print(f"\n  50/50 SPY + Min-Var Commodity:")
print(f"    Ann Ret: {opt_stats['ann_return']:.4f}, Vol: {opt_stats['ann_vol']:.4f}, "
      f"Sharpe: {opt_stats['sharpe']:.4f}, MDD: {opt_stats['mdd']:.4f}")
print(f"    Commodity leg corr(SPY): {opt_spy_corr:.4f}")

RESULTS['optimal_mix'] = {
    'min_variance': {
        'weights': {c: round(float(w_mv[i]), 4) for i, c in enumerate(commodity_cols)},
        'ann_return': round(float(mv_ret), 4),
        'ann_vol': round(float(mv_vol), 4),
        'sharpe': round(float(mv_ret/mv_vol), 4),
    },
    'max_sharpe': {
        'weights': {c: round(float(w_ms[i]), 4) for i, c in enumerate(commodity_cols)},
        'ann_return': round(float(ms_ret), 4),
        'ann_vol': round(float(ms_vol), 4),
        'sharpe': round(float(ms_ret/ms_vol), 4),
    },
    'spy_opt_portfolio': {
        **opt_stats,
        'corr_spy': round(float(opt_spy_corr), 4),
    },
}

# ============================================================
# 11. Sub-Period Robustness (2005-2014 vs 2015-2025)
# ============================================================
print("\n" + "=" * 70)
print("[11] Sub-Period Robustness")
print("=" * 70)

sub_periods = {
    '2005-2014': ('2005-01-01', '2014-12-31'),
    '2015-2025': ('2015-01-01', '2026-01-01'),
}

sub_results = {}
for period_name, (start, end) in sub_periods.items():
    mask = (pd.DatetimeIndex(common_all) >= start) & (pd.DatetimeIndex(common_all) < end)
    idx_sub = pd.DatetimeIndex(common_all)[mask]
    if len(idx_sub) < 100:
        continue

    print(f"\n  {period_name} ({len(idx_sub):,} days):")
    sub_data = {}
    for pname, ret_s in portfolios.items():
        sub_ret = ret_s.loc[idx_sub]
        s = compute_stats(sub_ret, pname)
        sub_data[pname] = s
        print(f"    {pname:22s}  Sharpe={s['sharpe']:>7.4f}  MDD={s['mdd']:>8.2%}")
    sub_results[period_name] = sub_data

RESULTS['sub_period_robustness'] = sub_results

# ============================================================
# 12. Statistical Tests — Is Diversification Significant?
# ============================================================
print("\n" + "=" * 70)
print("[12] Statistical Tests")
print("=" * 70)

# Test 1: DM-like test — is Portfolio A (EW5) significantly different from D (GLD)?
diff_ad = port_a_a - port_d_a
t_ad, p_ad = stats.ttest_1samp(diff_ad, 0)
print(f"\n  Portfolio A (EW5Comm) vs D (GLD) return difference:")
print(f"    Mean daily diff: {diff_ad.mean()*10000:.2f} bps")
print(f"    t-stat: {t_ad:.4f}, p-value: {p_ad:.4f}")

# Test 2: Variance ratio — is EW5 vol significantly lower?
# F-test on variances
var_a = port_a_a.var()
var_d = port_d_a.var()
f_stat = var_a / var_d
# Two-tailed F-test
n = len(port_a_a)
p_f = 2 * min(stats.f.cdf(f_stat, n-1, n-1), 1 - stats.f.cdf(f_stat, n-1, n-1))
print(f"\n  Variance test (EW5 vs GLD portfolio):")
print(f"    Var(A)/Var(D) = {f_stat:.4f}")
print(f"    F-stat p-value: {p_f:.6f}")
print(f"    {'EW5 significantly different variance' if p_f < 0.05 else 'No sig difference'}")

# Test 3: Bootstrap Sharpe difference
n_boot = 10000
sharpe_diffs_boot = []
for _ in range(n_boot):
    idx_boot = np.random.randint(0, len(port_a_a), len(port_a_a))
    boot_a = port_a_a.values[idx_boot]
    boot_d = port_d_a.values[idx_boot]
    sr_a = boot_a.mean() / boot_a.std() * np.sqrt(252)
    sr_d = boot_d.mean() / boot_d.std() * np.sqrt(252)
    sharpe_diffs_boot.append(sr_a - sr_d)

sharpe_diffs_boot = np.array(sharpe_diffs_boot)
ci_lo = np.percentile(sharpe_diffs_boot, 2.5)
ci_hi = np.percentile(sharpe_diffs_boot, 97.5)
boot_mean = sharpe_diffs_boot.mean()
boot_t = boot_mean / sharpe_diffs_boot.std() if sharpe_diffs_boot.std() > 0 else 0

print(f"\n  Bootstrap Sharpe Difference (EW5 - GLD portfolio), {n_boot:,} reps:")
print(f"    Mean diff: {boot_mean:.4f}")
print(f"    95% CI: [{ci_lo:.4f}, {ci_hi:.4f}]")
print(f"    t-stat: {boot_t:.4f}")
print(f"    {'Significant (CI excludes 0)' if ci_lo > 0 or ci_hi < 0 else 'NOT significant'}")

RESULTS['statistical_tests'] = {
    'return_diff_ew5_vs_gld': {
        'mean_daily_diff_bps': round(float(diff_ad.mean()*10000), 2),
        't_stat': round(float(t_ad), 4),
        'p_value': round(float(p_ad), 4),
    },
    'variance_ratio_test': {
        'var_ratio': round(float(f_stat), 4),
        'p_value': round(float(p_f), 6),
    },
    'bootstrap_sharpe_diff': {
        'mean_diff': round(float(boot_mean), 4),
        'ci_95_lo': round(float(ci_lo), 4),
        'ci_95_hi': round(float(ci_hi), 4),
        't_stat': round(float(boot_t), 4),
        'significant': bool(ci_lo > 0 or ci_hi < 0),
    },
}

# ============================================================
# 13. SYNTHESIS — Answer the Key Question
# ============================================================
print("\n" + "=" * 70)
print("[13] SYNTHESIS — Is GLD's Diversification Benefit Unique?")
print("=" * 70)

# Compare gold vs EW commodity basket correlation with SPY
gc_spy_corr_val = spy_corrs.get('GC=F', 0)
ew_spy_corr_val = round(float(ew_spy_corr), 4)

print(f"\n  Gold (GC=F) correlation with SPY:          {gc_spy_corr_val:+.4f}")
print(f"  EW-5-Commodity correlation with SPY:        {ew_spy_corr_val:+.4f}")
print(f"  Oil (CL=F) correlation with SPY:            {spy_corrs.get('CL=F', 0):+.4f}")
print(f"  Copper (HG=F) correlation with SPY:         {spy_corrs.get('HG=F', 0):+.4f}")
print(f"  Natural Gas (NG=F) correlation with SPY:    {spy_corrs.get('NG=F', 0):+.4f}")

# Best portfolio
best_port = max(port_stats.items(), key=lambda x: x[1]['sharpe'])
print(f"\n  Best portfolio by Sharpe: {best_port[0]} (Sharpe={best_port[1]['sharpe']:.4f})")
print(f"  Best portfolio by MDD:   ", end="")
best_mdd_port = max(port_stats.items(), key=lambda x: x[1]['mdd'])
print(f"{best_mdd_port[0]} (MDD={best_mdd_port[1]['mdd']:.2%})")

# VT overlay best
best_vt = max(vt_results.items(), key=lambda x: x[1]['vt_sharpe'])
print(f"  Best VT portfolio:       {best_vt[0]} (VT Sharpe={best_vt[1]['vt_sharpe']:.4f})")

# Conclusion
conclusion_lines = []
if abs(gc_spy_corr_val) < abs(ew_spy_corr_val):
    conclusion_lines.append("Gold provides BETTER diversification (lower |corr| with SPY) than EW commodity basket")
else:
    conclusion_lines.append("EW commodity basket provides comparable or better diversification than gold alone")

port_a_sharpe = port_stats['A_SPY_EW5Comm']['sharpe']
port_d_sharpe = port_stats['D_SPY_GLD']['sharpe']
if port_d_sharpe > port_a_sharpe:
    conclusion_lines.append(f"SPY/GLD outperforms SPY/EW5Comm on Sharpe ({port_d_sharpe:.4f} vs {port_a_sharpe:.4f})")
else:
    conclusion_lines.append(f"SPY/EW5Comm outperforms SPY/GLD on Sharpe ({port_a_sharpe:.4f} vs {port_d_sharpe:.4f})")

if not (ci_lo > 0 or ci_hi < 0):
    conclusion_lines.append("But the Sharpe difference is NOT statistically significant (bootstrap)")

for line in conclusion_lines:
    print(f"\n  >>> {line}")

RESULTS['synthesis'] = {
    'gc_spy_corr': gc_spy_corr_val,
    'ew_spy_corr': ew_spy_corr_val,
    'best_portfolio_sharpe': best_port[0],
    'best_portfolio_sharpe_value': best_port[1]['sharpe'],
    'best_portfolio_mdd': best_mdd_port[0],
    'best_vt_portfolio': best_vt[0],
    'conclusion': conclusion_lines,
}

# ============================================================
# SAVE RESULTS
# ============================================================
results_file = 'experiments/k344_cross_commodity_results.json'
with open(results_file, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n\nResults saved to {results_file}")
print("=" * 70)
print("K344 COMPLETE")
print("=" * 70)
