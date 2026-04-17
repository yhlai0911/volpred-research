#!/usr/bin/env python3
"""
K628b: Cross-Asset Volatility Spillover Network
================================================
Jump exploration: volatility transmission across major asset classes
(SPY, GLD, TLT, 0050.TW, USO) using network/spillover framework.

Builds on K455 (Diebold-Yilmaz US→Asia) and K422 (commodity spillover)
but with different asset mix and adds:
  - Forbes-Rigobon contagion test
  - OOS spillover-informed portfolio allocation
  - Rolling Granger causality dynamics

References:
  - Diebold & Yilmaz (2009, 2012) - Spillover index
  - Forbes & Rigobon (2002) - No contagion, only interdependence
  - Engle (2002) - DCC
  - Granger (1969) - Causality tests

Data source: yfinance
Period: 2010-01-01 to 2026-03-27
"""

import json
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

warnings.filterwarnings('ignore')
BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K628b: Cross-Asset Volatility Spillover Network")
print("=" * 60)

TICKERS = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'TLT': 'TLT',
    '0050.TW': '0050.TW',
    'USO': 'USO',
}
DISPLAY_NAMES = {
    'SPY': 'SPY (US Equity)',
    'GLD': 'GLD (Gold)',
    'TLT': 'TLT (US Bond)',
    '0050.TW': '0050.TW (Taiwan)',
    'USO': 'USO (Oil)',
}
START = '2010-01-01'
END = '2026-03-27'

print(f"\nDownloading data: {list(TICKERS.keys())} from {START} to {END}")
raw = yf.download(list(TICKERS.values()), start=START, end=END, auto_adjust=True, progress=False)

# Extract close prices
prices = pd.DataFrame()
for name, ticker in TICKERS.items():
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            prices[name] = raw['Close'][ticker]
        else:
            prices[name] = raw['Close']
    except Exception as e:
        print(f"  Warning: {ticker} - {e}")

# Forward-fill missing (0050.TW holidays when US open)
prices = prices.ffill()
prices = prices.dropna()

print(f"  Price data: {len(prices)} observations, {prices.columns.tolist()}")
print(f"  Period: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Returns
returns = prices.pct_change().dropna()
assets = list(returns.columns)
n_assets = len(assets)
print(f"  Returns: {len(returns)} observations")

# ============================================================
# 2. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n" + "=" * 60)
print("DESCRIPTIVE STATISTICS")
print("=" * 60)

desc_stats = {}
for asset in assets:
    r = returns[asset]
    adf_stat, adf_pval = adfuller(r.dropna(), maxlag=10)[:2]
    # ARCH LM test (on squared returns)
    try:
        arch_lm = het_arch(r.dropna(), nlags=5)
        arch_stat, arch_pval = arch_lm[0], arch_lm[1]
    except:
        arch_stat, arch_pval = np.nan, np.nan

    desc_stats[asset] = {
        'n': int(len(r)),
        'mean': float(r.mean()),
        'std': float(r.std()),
        'skew': float(r.skew()),
        'kurtosis': float(r.kurtosis()),
        'min': float(r.min()),
        'max': float(r.max()),
        'adf_stat': float(adf_stat),
        'adf_pval': float(adf_pval),
        'arch_lm_stat': float(arch_stat) if not np.isnan(arch_stat) else None,
        'arch_lm_pval': float(arch_pval) if not np.isnan(arch_pval) else None,
    }
    print(f"\n  {DISPLAY_NAMES[asset]}:")
    print(f"    N={len(r)}, Mean={r.mean():.6f}, Std={r.std():.4f}")
    print(f"    Skew={r.skew():.3f}, Kurt={r.kurtosis():.3f}")
    print(f"    ADF stat={adf_stat:.3f} (p={adf_pval:.4f})")
    print(f"    ARCH LM={arch_stat:.2f} (p={arch_pval:.4f})" if not np.isnan(arch_stat) else "    ARCH LM: N/A")

# ============================================================
# 3. REALIZED VOLATILITY (22-day rolling)
# ============================================================
print("\n" + "=" * 60)
print("REALIZED VOLATILITY (22-day rolling)")
print("=" * 60)

ROLL_WINDOW = 22
rvol = returns.rolling(ROLL_WINDOW).std() * np.sqrt(252)
rvol = rvol.dropna()
print(f"  RVol observations: {len(rvol)}")

# Check stationarity of rvol
rvol_stationarity = {}
for asset in assets:
    adf_s, adf_p = adfuller(rvol[asset].dropna(), maxlag=10)[:2]
    rvol_stationarity[asset] = {'adf_stat': float(adf_s), 'adf_pval': float(adf_p)}
    print(f"  {asset} RVol ADF: stat={adf_s:.3f}, p={adf_p:.4f} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")

# If any non-stationary, we'll use first-differences for VAR
any_nonstationary = any(v['adf_pval'] >= 0.05 for v in rvol_stationarity.values())
if any_nonstationary:
    print("  -> Some series non-stationary, will use log-rvol for better stationarity")
    rvol_for_var = np.log(rvol + 1e-8)
    # Re-check
    for asset in assets:
        adf_s, adf_p = adfuller(rvol_for_var[asset].dropna(), maxlag=10)[:2]
        if adf_p >= 0.05:
            print(f"  WARNING: log-rvol {asset} still non-stationary, using diff")
    var_input = rvol_for_var
else:
    var_input = rvol

# ============================================================
# 4a. GRANGER CAUSALITY NETWORK
# ============================================================
print("\n" + "=" * 60)
print("GRANGER CAUSALITY NETWORK (5 lags, 5% significance)")
print("=" * 60)

MAX_LAG = 5
granger_results = {}
granger_network = np.zeros((n_assets, n_assets))

for i, cause in enumerate(assets):
    for j, effect in enumerate(assets):
        if i == j:
            continue
        key = f"{cause}->{effect}"
        try:
            data_pair = rvol[[effect, cause]].dropna()
            test = grangercausalitytests(data_pair, maxlag=MAX_LAG, verbose=False)
            # Get the minimum p-value across all lags
            min_pval = min(test[lag][0]['ssr_ftest'][1] for lag in range(1, MAX_LAG + 1))
            best_lag = min(range(1, MAX_LAG + 1), key=lambda l: test[l][0]['ssr_ftest'][1])
            f_stat = test[best_lag][0]['ssr_ftest'][0]

            granger_results[key] = {
                'f_stat': float(f_stat),
                'p_value': float(min_pval),
                'best_lag': int(best_lag),
                'significant': min_pval < 0.05,
            }
            if min_pval < 0.05:
                granger_network[i, j] = f_stat
                print(f"  {key}: F={f_stat:.2f}, p={min_pval:.4f} (lag={best_lag}) ***")
            else:
                print(f"  {key}: F={f_stat:.2f}, p={min_pval:.4f} (lag={best_lag})")
        except Exception as e:
            granger_results[key] = {'error': str(e)}
            print(f"  {key}: ERROR - {e}")

# Network summary
print("\n  Network Summary (Granger causality):")
granger_roles = {}
for i, asset in enumerate(assets):
    out_degree = int(np.sum(granger_network[i, :] > 0))
    in_degree = int(np.sum(granger_network[:, i] > 0))
    net = out_degree - in_degree
    role = 'TRANSMITTER' if net > 0 else ('RECEIVER' if net < 0 else 'BALANCED')
    granger_roles[asset] = {
        'out_degree': out_degree,
        'in_degree': in_degree,
        'net_degree': net,
        'role': role,
    }
    print(f"  {DISPLAY_NAMES[asset]}: OUT={out_degree}, IN={in_degree}, NET={net} -> {role}")

# ============================================================
# 4b. DCC-LIKE ROLLING CORRELATION DYNAMICS
# ============================================================
print("\n" + "=" * 60)
print("ROLLING CORRELATION DYNAMICS (60-day window)")
print("=" * 60)

CORR_WINDOW = 60
sq_returns = returns ** 2

# Rolling correlation between all pairs
rolling_corr = {}
for i in range(n_assets):
    for j in range(i + 1, n_assets):
        a1, a2 = assets[i], assets[j]
        key = f"{a1}-{a2}"
        rc = sq_returns[a1].rolling(CORR_WINDOW).corr(sq_returns[a2])
        rolling_corr[key] = rc

# VIX proxy for regime: use SPY realized vol as VIX substitute
spy_rvol = rvol['SPY']
high_vol = spy_rvol > spy_rvol.quantile(0.75)  # top 25% = "crisis"
low_vol = spy_rvol < spy_rvol.quantile(0.25)   # bottom 25% = "calm"

# Compare correlations in crisis vs calm
crisis_corr_stats = {}
for key, rc in rolling_corr.items():
    rc_aligned = rc.reindex(spy_rvol.index)
    crisis_mean = float(rc_aligned[high_vol].mean()) if high_vol.sum() > 0 else np.nan
    calm_mean = float(rc_aligned[low_vol].mean()) if low_vol.sum() > 0 else np.nan
    overall_mean = float(rc_aligned.mean())

    # t-test for difference
    crisis_vals = rc_aligned[high_vol].dropna()
    calm_vals = rc_aligned[low_vol].dropna()
    if len(crisis_vals) > 10 and len(calm_vals) > 10:
        t_stat, t_pval = stats.ttest_ind(crisis_vals, calm_vals, equal_var=False)
    else:
        t_stat, t_pval = np.nan, np.nan

    crisis_corr_stats[key] = {
        'overall_mean': overall_mean,
        'crisis_mean': crisis_mean,
        'calm_mean': calm_mean,
        'diff': crisis_mean - calm_mean if not (np.isnan(crisis_mean) or np.isnan(calm_mean)) else np.nan,
        't_stat': float(t_stat) if not np.isnan(t_stat) else None,
        't_pval': float(t_pval) if not np.isnan(t_pval) else None,
    }
    sig = '***' if (not np.isnan(t_pval) and t_pval < 0.05) else ''
    print(f"  {key}: Crisis={crisis_mean:.3f}, Calm={calm_mean:.3f}, "
          f"Diff={crisis_mean - calm_mean:.3f} (t={t_stat:.2f}, p={t_pval:.4f}) {sig}")

# ============================================================
# 4c. DIEBOLD-YILMAZ SPILLOVER INDEX
# ============================================================
print("\n" + "=" * 60)
print("DIEBOLD-YILMAZ SPILLOVER INDEX (VAR, forecast horizon=10)")
print("=" * 60)

FORECAST_HORIZON = 10

def compute_spillover_index(data, max_lag=5, h=10):
    """
    Compute Diebold-Yilmaz spillover index using generalized FEVD.
    Returns: total spillover, directional spillovers, FEVD matrix.
    """
    # Fit VAR
    model = VAR(data)
    # Select lag by AIC
    try:
        lag_order = model.select_order(maxlags=max_lag)
        selected_lag = lag_order.aic
        if selected_lag == 0:
            selected_lag = 1
    except:
        selected_lag = min(5, max_lag)

    results = model.fit(selected_lag)

    # Generalized FEVD (Pesaran & Shin, 1998)
    fevd = results.fevd(h)

    # fevd.decomp is a list of n_assets arrays, each (h, n_assets)
    # decomp[i][-1] = h-step FEVD for variable i (row i of the matrix)
    n = len(fevd.decomp)
    fevd_matrix = np.zeros((n, n))
    for i in range(n):
        fevd_matrix[i, :] = fevd.decomp[i][-1]  # h-step-ahead row

    # Normalize rows to sum to 1
    row_sums = fevd_matrix.sum(axis=1, keepdims=True)
    fevd_norm = fevd_matrix / np.where(row_sums > 0, row_sums, 1.0)

    n = fevd_norm.shape[0]

    # Total spillover index = (sum of off-diagonal / sum of all) * 100
    total = np.sum(fevd_norm) - np.trace(fevd_norm)
    total_spillover = (total / n) * 100

    # Directional spillovers
    # "FROM others" = row sum minus diagonal (how much i is influenced by others)
    from_others = np.sum(fevd_norm, axis=1) - np.diag(fevd_norm)
    # "TO others" = column sum minus diagonal (how much i influences others)
    to_others = np.sum(fevd_norm, axis=0) - np.diag(fevd_norm)
    # NET = TO - FROM
    net_spillover = to_others - from_others

    return {
        'total_spillover': float(total_spillover),
        'fevd_matrix': fevd_norm.tolist(),
        'from_others': from_others.tolist(),
        'to_others': to_others.tolist(),
        'net_spillover': net_spillover.tolist(),
        'selected_lag': int(selected_lag),
    }

# Full-sample spillover
try:
    full_spillover = compute_spillover_index(var_input.dropna(), max_lag=5, h=FORECAST_HORIZON)
    print(f"\n  VAR lag selected: {full_spillover['selected_lag']}")
    print(f"  Total Spillover Index: {full_spillover['total_spillover']:.1f}%")

    print(f"\n  Directional Spillovers:")
    print(f"  {'Asset':<20} {'FROM others':>12} {'TO others':>12} {'NET':>12} {'Role':>15}")
    print(f"  {'-'*71}")

    directional_roles = {}
    for i, asset in enumerate(assets):
        from_o = full_spillover['from_others'][i] * 100
        to_o = full_spillover['to_others'][i] * 100
        net_o = full_spillover['net_spillover'][i] * 100
        role = 'TRANSMITTER' if net_o > 5 else ('RECEIVER' if net_o < -5 else 'BALANCED')
        directional_roles[asset] = {
            'from_others_pct': float(from_o),
            'to_others_pct': float(to_o),
            'net_pct': float(net_o),
            'role': role,
        }
        print(f"  {DISPLAY_NAMES[asset]:<20} {from_o:>11.1f}% {to_o:>11.1f}% {net_o:>11.1f}% {role:>15}")

    # FEVD matrix
    print(f"\n  FEVD Matrix (row=response, col=shock, %):")
    header = f"  {'':>12}" + "".join(f"{a:>10}" for a in assets)
    print(header)
    for i, asset in enumerate(assets):
        row = f"  {asset:>12}" + "".join(f"{full_spillover['fevd_matrix'][i][j]*100:>10.1f}" for j in range(n_assets))
        print(row)

except Exception as e:
    print(f"  ERROR in spillover computation: {e}")
    full_spillover = {'error': str(e)}
    directional_roles = {}

# ============================================================
# 4c-2. TIME-VARYING SPILLOVER (rolling 200-day windows)
# ============================================================
print("\n" + "=" * 60)
print("TIME-VARYING SPILLOVER INDEX (200-day rolling window)")
print("=" * 60)

ROLL_SPILL_WINDOW = 200
ROLL_STEP = 20  # Step size to speed up computation

var_data = var_input.dropna()
n_total = len(var_data)

rolling_spillover_dates = []
rolling_spillover_values = []
rolling_spy_net = []

print(f"  Computing rolling spillover (window={ROLL_SPILL_WINDOW}, step={ROLL_STEP})...")
print(f"  Total windows: ~{(n_total - ROLL_SPILL_WINDOW) // ROLL_STEP}")

for start_idx in range(0, n_total - ROLL_SPILL_WINDOW, ROLL_STEP):
    window_data = var_data.iloc[start_idx:start_idx + ROLL_SPILL_WINDOW]
    try:
        sp = compute_spillover_index(window_data, max_lag=3, h=10)
        rolling_spillover_dates.append(window_data.index[-1])
        rolling_spillover_values.append(sp['total_spillover'])
        # SPY net spillover
        spy_idx = assets.index('SPY')
        rolling_spy_net.append(sp['net_spillover'][spy_idx] * 100)
    except:
        pass

print(f"  Computed {len(rolling_spillover_values)} windows")
if rolling_spillover_values:
    print(f"  Total spillover range: {min(rolling_spillover_values):.1f}% - {max(rolling_spillover_values):.1f}%")
    print(f"  Mean total spillover: {np.mean(rolling_spillover_values):.1f}%")

# ============================================================
# 4d. FORBES-RIGOBON CONTAGION TEST (SPY -> 0050.TW)
# ============================================================
print("\n" + "=" * 60)
print("FORBES-RIGOBON CONTAGION TEST (SPY -> 0050.TW)")
print("=" * 60)

def forbes_rigobon_test(x, y, crisis_mask, alpha=0.05):
    """
    Forbes-Rigobon (2002) adjusted correlation test.
    Tests whether correlation during crisis is significantly higher
    than during calm, after adjusting for increased variance.
    """
    x_crisis = x[crisis_mask].dropna()
    y_crisis = y[crisis_mask].dropna()
    x_calm = x[~crisis_mask].dropna()
    y_calm = y[~crisis_mask].dropna()

    if len(x_crisis) < 30 or len(x_calm) < 30:
        return {'error': 'insufficient data'}

    # Unadjusted correlations
    rho_crisis = np.corrcoef(x_crisis, y_crisis)[0, 1]
    rho_calm = np.corrcoef(x_calm, y_calm)[0, 1]

    # Variance ratio
    var_crisis = x_crisis.var()
    var_calm = x_calm.var()
    delta = var_crisis / var_calm - 1  # relative increase in variance

    # Forbes-Rigobon adjusted correlation
    rho_adj = rho_crisis / np.sqrt(1 + delta * (1 - rho_crisis ** 2))

    # Fisher z-transform for testing
    z_adj = np.arctanh(rho_adj)
    z_calm = np.arctanh(rho_calm)

    n_crisis = len(x_crisis)
    n_calm = len(x_calm)

    se = np.sqrt(1 / (n_crisis - 3) + 1 / (n_calm - 3))
    z_stat = (z_adj - z_calm) / se
    p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))

    contagion = p_value < alpha and rho_adj > rho_calm

    return {
        'rho_crisis_unadjusted': float(rho_crisis),
        'rho_calm': float(rho_calm),
        'rho_crisis_adjusted': float(rho_adj),
        'delta_variance': float(delta),
        'z_stat': float(z_stat),
        'p_value': float(p_value),
        'contagion': contagion,
        'n_crisis': int(n_crisis),
        'n_calm': int(n_calm),
        'interpretation': 'CONTAGION' if contagion else 'INTERDEPENDENCE (no contagion)',
    }

# Define crisis periods using SPY RVol top quartile
spy_rvol_aligned = rvol['SPY'].reindex(returns.index)
crisis_mask = spy_rvol_aligned > spy_rvol_aligned.quantile(0.75)
crisis_mask = crisis_mask.fillna(False)

# Test all pairs with SPY as source
contagion_results = {}
for target in assets:
    if target == 'SPY':
        continue
    result = forbes_rigobon_test(returns['SPY'], returns[target], crisis_mask)
    contagion_results[f"SPY->{target}"] = result
    if 'error' not in result:
        print(f"\n  SPY -> {DISPLAY_NAMES[target]}:")
        print(f"    Unadjusted crisis corr: {result['rho_crisis_unadjusted']:.4f}")
        print(f"    Calm corr:              {result['rho_calm']:.4f}")
        print(f"    FR-adjusted crisis corr: {result['rho_crisis_adjusted']:.4f}")
        print(f"    Variance increase (delta): {result['delta_variance']:.2f}")
        print(f"    Z-stat: {result['z_stat']:.3f}, p-value: {result['p_value']:.4f}")
        print(f"    Result: {result['interpretation']}")
    else:
        print(f"  SPY -> {target}: {result['error']}")

# ============================================================
# 4e. VIX REGIME ANALYSIS
# ============================================================
print("\n" + "=" * 60)
print("NETWORK STRUCTURE BY VIX REGIME")
print("=" * 60)

# Use SPY RVol as VIX proxy — high vol (>25% annualized) vs low
# Note: we use realized vol thresholds since we don't download VIX separately here
vol_threshold = 0.25  # 25% annualized = roughly VIX ~25

high_regime = spy_rvol_aligned > vol_threshold
high_regime = high_regime.fillna(False)

print(f"  High vol regime (RVol > {vol_threshold*100:.0f}%): {high_regime.sum()} days ({high_regime.mean()*100:.1f}%)")
print(f"  Low vol regime: {(~high_regime).sum()} days")

# Granger causality in each regime
regime_granger = {'high_vol': {}, 'low_vol': {}}
for regime_name, mask in [('high_vol', high_regime), ('low_vol', ~high_regime)]:
    regime_rvol = rvol[mask].dropna()
    if len(regime_rvol) < 100:
        print(f"  {regime_name}: insufficient data ({len(regime_rvol)} obs)")
        continue

    sig_links = 0
    for i, cause in enumerate(assets):
        for j, effect in enumerate(assets):
            if i == j:
                continue
            try:
                data_pair = regime_rvol[[effect, cause]].dropna()
                if len(data_pair) < 30:
                    continue
                test = grangercausalitytests(data_pair, maxlag=3, verbose=False)
                min_pval = min(test[lag][0]['ssr_ftest'][1] for lag in range(1, 4))
                if min_pval < 0.05:
                    sig_links += 1
                    regime_granger[regime_name][f"{cause}->{effect}"] = float(min_pval)
            except:
                pass

    print(f"  {regime_name}: {sig_links} significant Granger links")

# ============================================================
# 5. OOS APPLICATION: Spillover-informed allocation
# ============================================================
print("\n" + "=" * 60)
print("OOS APPLICATION: Spillover-Informed Portfolio")
print("=" * 60)

# Strategy: When SPY-to-0050.TW spillover is high, reduce 0050.TW weight
# Use rolling Granger F-stat as spillover measure

LOOK_BACK = 120  # rolling window for Granger test
OOS_START = '2020-01-01'  # OOS period

# Compute rolling Granger F-stat: SPY -> 0050.TW
print("  Computing rolling Granger causality (SPY -> 0050.TW)...")
rolling_granger_dates = []
rolling_granger_fstat = []

rvol_data = rvol[['0050.TW', 'SPY']].dropna()
for start_idx in range(0, len(rvol_data) - LOOK_BACK, 5):  # step=5 for speed
    window = rvol_data.iloc[start_idx:start_idx + LOOK_BACK]
    try:
        test = grangercausalitytests(window, maxlag=3, verbose=False)
        best_f = max(test[lag][0]['ssr_ftest'][0] for lag in range(1, 4))
        rolling_granger_dates.append(window.index[-1])
        rolling_granger_fstat.append(best_f)
    except:
        pass

if rolling_granger_dates:
    granger_series = pd.Series(rolling_granger_fstat, index=rolling_granger_dates)
    granger_series = granger_series.reindex(returns.index, method='ffill')

    # High spillover = top 30% of F-stats
    high_spillover = granger_series > granger_series.quantile(0.70)

    # Strategies
    oos_mask = returns.index >= OOS_START
    oos_returns = returns[oos_mask]

    # Equal weight portfolio (SPY 50% + 0050.TW 50%)
    ew_ret = 0.5 * oos_returns['SPY'] + 0.5 * oos_returns['0050.TW']

    # Spillover-informed: when high spillover, shift to 70% SPY / 30% 0050.TW
    # (reduce TW exposure during high spillover from US)
    high_spill_oos = high_spillover.reindex(oos_returns.index, fill_value=False)
    spill_ret = pd.Series(index=oos_returns.index, dtype=float)
    spill_ret[high_spill_oos] = 0.7 * oos_returns['SPY'][high_spill_oos] + 0.3 * oos_returns['0050.TW'][high_spill_oos]
    spill_ret[~high_spill_oos] = 0.5 * oos_returns['SPY'][~high_spill_oos] + 0.5 * oos_returns['0050.TW'][~high_spill_oos]
    spill_ret = spill_ret.dropna()
    ew_ret = ew_ret.reindex(spill_ret.index)

    # Performance metrics
    def calc_metrics(r, name):
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + r).cumprod()
        mdd = float(((cum / cum.cummax()) - 1).min())
        calmar = ann_ret / abs(mdd) if mdd != 0 else 0
        return {
            'name': name,
            'ann_return': float(ann_ret),
            'ann_vol': float(ann_vol),
            'sharpe': float(sharpe),
            'max_drawdown': float(mdd),
            'calmar': float(calmar),
            'n_days': int(len(r)),
        }

    ew_metrics = calc_metrics(ew_ret, 'Equal Weight (50/50)')
    spill_metrics = calc_metrics(spill_ret, 'Spillover-Informed')
    spy_only = calc_metrics(oos_returns['SPY'], 'SPY Only')
    tw_only = calc_metrics(oos_returns['0050.TW'], '0050.TW Only')

    print(f"\n  OOS Period: {OOS_START} to {oos_returns.index[-1].strftime('%Y-%m-%d')}")
    print(f"  High spillover days: {high_spill_oos.sum()} ({high_spill_oos.mean()*100:.1f}%)")
    print(f"\n  {'Strategy':<25} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8}")
    print(f"  {'-'*65}")
    for m in [ew_metrics, spill_metrics, spy_only, tw_only]:
        print(f"  {m['name']:<25} {m['ann_return']*100:>7.1f}% {m['ann_vol']*100:>7.1f}% "
              f"{m['sharpe']:>7.3f} {m['max_drawdown']*100:>7.1f}% {m['calmar']:>7.3f}")

    # t-test for Sharpe difference
    from scipy.stats import ttest_rel
    common_idx = ew_ret.index.intersection(spill_ret.index)
    if len(common_idx) > 100:
        t_diff, p_diff = ttest_rel(spill_ret.reindex(common_idx), ew_ret.reindex(common_idx))
        print(f"\n  Paired t-test (spillover vs equal weight): t={t_diff:.3f}, p={p_diff:.4f}")
    else:
        t_diff, p_diff = np.nan, np.nan

    portfolio_results = {
        'oos_period': f"{OOS_START} to {oos_returns.index[-1].strftime('%Y-%m-%d')}",
        'high_spillover_pct': float(high_spill_oos.mean() * 100),
        'equal_weight': ew_metrics,
        'spillover_informed': spill_metrics,
        'spy_only': spy_only,
        'tw_only': tw_only,
        'paired_ttest_t': float(t_diff) if not np.isnan(t_diff) else None,
        'paired_ttest_p': float(p_diff) if not np.isnan(p_diff) else None,
    }
else:
    portfolio_results = {'error': 'Could not compute rolling Granger'}

# ============================================================
# 6. GENERATE PLOTS
# ============================================================
print("\n" + "=" * 60)
print("GENERATING PLOTS")
print("=" * 60)

# Plot 1: Network Diagram
fig, ax = plt.subplots(1, 1, figsize=(10, 10))

# Position assets in a circle
angles = np.linspace(0, 2 * np.pi, n_assets, endpoint=False)
radius = 3.0
positions = {asset: (radius * np.cos(angle), radius * np.sin(angle))
             for asset, angle in zip(assets, angles)}

# Color by role
role_colors = {'TRANSMITTER': '#e74c3c', 'RECEIVER': '#3498db', 'BALANCED': '#95a5a6'}
node_colors = []
for asset in assets:
    if asset in directional_roles:
        role = directional_roles[asset]['role']
    elif asset in granger_roles:
        role = granger_roles[asset]['role']
    else:
        role = 'BALANCED'
    node_colors.append(role_colors.get(role, '#95a5a6'))

# Draw nodes
for i, asset in enumerate(assets):
    x, y = positions[asset]
    circle = plt.Circle((x, y), 0.5, color=node_colors[i], alpha=0.8, zorder=3)
    ax.add_patch(circle)
    # Node label with info
    if asset in directional_roles:
        net_pct = directional_roles[asset]['net_pct']
        label = f"{asset}\nNET: {net_pct:+.1f}%"
    else:
        label = asset
    ax.text(x, y, label, ha='center', va='center', fontsize=9, fontweight='bold', zorder=4)

# Draw edges (Granger causality)
for i, cause in enumerate(assets):
    for j, effect in enumerate(assets):
        if granger_network[i, j] > 0:
            x1, y1 = positions[cause]
            x2, y2 = positions[effect]

            # Shorten arrow to not overlap with circles
            dx = x2 - x1
            dy = y2 - y1
            dist = np.sqrt(dx**2 + dy**2)
            shrink = 0.55 / dist
            x1_adj = x1 + dx * shrink
            y1_adj = y1 + dy * shrink
            x2_adj = x2 - dx * shrink
            y2_adj = y2 - dy * shrink

            # Width proportional to F-stat
            width = max(0.5, min(3.0, granger_network[i, j] / 10))
            alpha = min(0.8, 0.3 + granger_network[i, j] / 50)

            ax.annotate('', xy=(x2_adj, y2_adj), xytext=(x1_adj, y1_adj),
                        arrowprops=dict(arrowstyle='->', color='#2c3e50',
                                       lw=width, alpha=alpha,
                                       connectionstyle='arc3,rad=0.1'))

# Legend
legend_elements = [
    mpatches.Patch(color='#e74c3c', alpha=0.8, label='Net Transmitter'),
    mpatches.Patch(color='#3498db', alpha=0.8, label='Net Receiver'),
    mpatches.Patch(color='#95a5a6', alpha=0.8, label='Balanced'),
]
ax.legend(handles=legend_elements, loc='upper left', fontsize=10)

ax.set_xlim(-5, 5)
ax.set_ylim(-5, 5)
ax.set_aspect('equal')
ax.set_title('K628b: Cross-Asset Volatility Spillover Network\n'
             '(Arrows = significant Granger causality, width ∝ F-stat)\n'
             f'Data: {START} to {END}, N={len(returns)}',
             fontsize=13, fontweight='bold')
ax.axis('off')

plt.tight_layout()
plot1_path = BASE_DIR / 'k628b_spillover_network.png'
plt.savefig(plot1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot1_path}")

# Plot 2: Time-varying spillover index
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

# Panel A: Total spillover index
if rolling_spillover_values:
    ax1 = axes[0]
    ax1.plot(rolling_spillover_dates, rolling_spillover_values, color='#2c3e50', linewidth=1.2)
    ax1.axhline(np.mean(rolling_spillover_values), color='gray', linestyle='--', alpha=0.5, label=f'Mean={np.mean(rolling_spillover_values):.1f}%')
    ax1.fill_between(rolling_spillover_dates, rolling_spillover_values,
                     alpha=0.3, color='#3498db')
    ax1.set_ylabel('Total Spillover Index (%)', fontsize=11)
    ax1.set_title('K628b: Time-Varying Volatility Spillover\n'
                  f'(Rolling {ROLL_SPILL_WINDOW}-day window, VAR forecast h={FORECAST_HORIZON})',
                  fontsize=13, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Add crisis markers
    for label, start_d, end_d in [
        ('COVID', '2020-02-01', '2020-06-01'),
        ('2022 Bear', '2022-01-01', '2022-10-01'),
    ]:
        try:
            s = pd.Timestamp(start_d)
            e = pd.Timestamp(end_d)
            ax1.axvspan(s, e, alpha=0.15, color='red')
            ax1.text(s, ax1.get_ylim()[1] * 0.95, label, fontsize=8, color='red')
        except:
            pass

# Panel B: SPY net spillover
if rolling_spy_net:
    ax2 = axes[1]
    colors = ['#e74c3c' if v > 0 else '#3498db' for v in rolling_spy_net]
    ax2.bar(rolling_spillover_dates, rolling_spy_net, width=5, color=colors, alpha=0.7)
    ax2.axhline(0, color='black', linewidth=0.5)
    ax2.set_ylabel('SPY Net Spillover (%)', fontsize=11)
    ax2.set_title('SPY Net Directional Spillover (positive = net transmitter)', fontsize=11)
    ax2.grid(True, alpha=0.3)

# Panel C: SPY realized vol
ax3 = axes[2]
spy_rvol_plot = rvol['SPY']
ax3.plot(spy_rvol_plot.index, spy_rvol_plot.values * 100, color='#e74c3c', linewidth=0.8, alpha=0.8)
ax3.axhline(25, color='gray', linestyle='--', alpha=0.5, label='25% threshold')
ax3.fill_between(spy_rvol_plot.index, spy_rvol_plot.values * 100, alpha=0.2, color='#e74c3c')
ax3.set_ylabel('SPY Realized Vol (%)', fontsize=11)
ax3.set_xlabel('Date', fontsize=11)
ax3.set_title('SPY 22-day Realized Volatility', fontsize=11)
ax3.legend(fontsize=9)
ax3.grid(True, alpha=0.3)

plt.tight_layout()
plot2_path = BASE_DIR / 'k628b_spillover_timeseries.png'
plt.savefig(plot2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot2_path}")

# ============================================================
# 7. KEY FINDINGS SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("KEY FINDINGS SUMMARY")
print("=" * 60)

findings = []

# Q1: Is SPY dominant transmitter?
if directional_roles:
    spy_role = directional_roles.get('SPY', {})
    spy_net = spy_role.get('net_pct', 0)
    if spy_net > 5:
        findings.append(f"SPY is dominant NET TRANSMITTER (net={spy_net:.1f}%)")
    else:
        findings.append(f"SPY net spillover is modest ({spy_net:.1f}%)")

# Q2: GLD role
if directional_roles:
    gld_role = directional_roles.get('GLD', {})
    gld_net = gld_role.get('net_pct', 0)
    findings.append(f"GLD is {'RECEIVER' if gld_net < 0 else 'TRANSMITTER'} (net={gld_net:.1f}%)")

# Q3: 0050.TW in network
if directional_roles:
    tw_role = directional_roles.get('0050.TW', {})
    tw_net = tw_role.get('net_pct', 0)
    findings.append(f"0050.TW is {'RECEIVER' if tw_net < 0 else 'TRANSMITTER'} (net={tw_net:.1f}%)")

# Q4: Contagion
spy_tw_contagion = contagion_results.get('SPY->0050.TW', {})
if 'interpretation' in spy_tw_contagion:
    findings.append(f"SPY->0050.TW: {spy_tw_contagion['interpretation']} (FR-adjusted)")

for f in findings:
    print(f"  * {f}")

# ============================================================
# 8. SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K628b',
    'title': 'Cross-Asset Volatility Spillover Network',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'type': 'empirical analysis',
    'data_source': 'yfinance',
    'data_period': f'{START} to {END}',
    'n_observations': int(len(returns)),
    'assets': assets,
    'display_names': DISPLAY_NAMES,
    'methodology': {
        'vol_measure': '22-day rolling realized vol (std × sqrt(252))',
        'granger_lags': MAX_LAG,
        'var_forecast_horizon': FORECAST_HORIZON,
        'rolling_spillover_window': ROLL_SPILL_WINDOW,
        'rolling_corr_window': CORR_WINDOW,
        'contagion_method': 'Forbes-Rigobon (2002) adjusted correlation',
    },
    'references': [
        'Diebold & Yilmaz (2009) "Measuring Financial Asset Return and Volatility Spillovers", EJ',
        'Diebold & Yilmaz (2012) "Better to Give than to Receive", JBES',
        'Forbes & Rigobon (2002) "No Contagion, Only Interdependence", JoF',
        'Granger (1969) "Investigating Causal Relations by Econometric Models", Econometrica',
    ],
    'descriptive_statistics': desc_stats,
    'rvol_stationarity': rvol_stationarity,
    'granger_causality': {
        'results': granger_results,
        'network_roles': granger_roles,
        'total_significant_links': int(np.sum(granger_network > 0)),
    },
    'rolling_correlation': {
        'crisis_vs_calm': crisis_corr_stats,
        'crisis_definition': 'SPY RVol > 75th percentile',
    },
    'diebold_yilmaz': full_spillover if isinstance(full_spillover, dict) else {'error': str(full_spillover)},
    'directional_roles': directional_roles,
    'time_varying_spillover': {
        'n_windows': len(rolling_spillover_values),
        'mean': float(np.mean(rolling_spillover_values)) if rolling_spillover_values else None,
        'std': float(np.std(rolling_spillover_values)) if rolling_spillover_values else None,
        'min': float(min(rolling_spillover_values)) if rolling_spillover_values else None,
        'max': float(max(rolling_spillover_values)) if rolling_spillover_values else None,
    },
    'contagion_test': contagion_results,
    'regime_granger': {
        'high_vol_links': len(regime_granger.get('high_vol', {})),
        'low_vol_links': len(regime_granger.get('low_vol', {})),
        'details': regime_granger,
    },
    'portfolio_application': portfolio_results,
    'key_findings': findings,
    'plots': {
        'network': 'k628b_spillover_network.png',
        'timeseries': 'k628b_spillover_timeseries.png',
    },
    'limitations': [
        'RVol proxy (22-day rolling) smooths out high-frequency dynamics',
        'VAR assumes linearity; threshold/regime-switching VAR could capture nonlinearity',
        '0050.TW holidays filled with ffill may bias Granger tests',
        'Forbes-Rigobon test uses sample-based variance ratio, not time-varying',
        'USO ETF has structural issues (contango, roll) that affect vol measurement',
        'OOS portfolio test is simple (no transaction costs, monthly rebalancing)',
    ],
}

results_path = BASE_DIR / 'k628b_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved: {results_path}")

print("\n" + "=" * 60)
print("K628b COMPLETE")
print("=" * 60)
