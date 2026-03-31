#!/usr/bin/env python3
"""
K756: International VIX Sufficiency — Does VIX Work for Non-US Markets?

[提出: Claude (Paper 5 review + research_program), 執行: Claude]

Background:
  K752 proved VIX sufficiency is time-invariant across 33 years for US markets.
  Paper 5 reviewer concern: "US-specific."
  K669 showed VIX is global fear signal (corr 0.609-0.762 with non-US vol).
  K681 tested VIX percentile globally (EFA t=5.419 Harvey PASS).
  K567 tested VIX-conditional leverage internationally (LIMITED generalizability).

  BUT: Nobody tested VIX PREDICTION SUFFICIENCY (R²) for non-US realized vol.
  This experiment does exactly that.

Design:
  For each of 11 international markets (ETFs):
  1. Compute 22-day forward realized vol (RV_fwd)
  2. Model A: RV_fwd = α + β₁×VIX + ε → R² (VIX-only)
  3. Model B: RV_fwd = α + β₂×OwnRV + ε → R² (own-RV only)
  4. Model C: RV_fwd = α + β₁×VIX + β₂×OwnRV + ε → R² (combined)
  5. Incremental R²: R²(C) - R²(B) = VIX's unique contribution beyond own RV
  6. Partial correlation: corr(VIX, RV_fwd | OwnRV)

  Cross-sectional analysis:
  - Which markets have highest/lowest VIX R²?
  - Does VIX R² correlate with US-market correlation?
  - Hypothesis: higher US correlation → higher VIX R²

Data: yfinance 2010-2026 (common availability for all ETFs)
Signal lag: VIX.shift(1) — mandatory
TX cost: N/A (prediction test, not strategy)

References:
  - K752: VIX sufficiency time-invariant across 33 years (US)
  - K669: VIX global fear signal, corr 0.609-0.762
  - K681: VIX percentile global, EFA t=5.419 Harvey PASS
  - K567: VIX-conditional leverage LIMITED generalizability
  - K697: VIX predicts vol magnitude (corr 0.57) not direction (corr 0.04)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIG
# ============================================================
MARKETS = {
    # Developed - Americas
    'SPY': {'name': 'S&P 500 (US)', 'region': 'Americas'},
    # Developed - Europe
    'EFA': {'name': 'MSCI EAFE', 'region': 'Europe'},
    'EWG': {'name': 'Germany (DAX)', 'region': 'Europe'},
    'EWU': {'name': 'UK (FTSE)', 'region': 'Europe'},
    # Developed - Asia
    'EWJ': {'name': 'Japan (Nikkei)', 'region': 'Asia'},
    'EWT': {'name': 'Taiwan (TAIEX)', 'region': 'Asia'},
    'EWY': {'name': 'Korea (KOSPI)', 'region': 'Asia'},
    'EWH': {'name': 'Hong Kong (HSI)', 'region': 'Asia'},
    # Emerging
    'EEM': {'name': 'Emerging Markets', 'region': 'Emerging'},
    'EWZ': {'name': 'Brazil (Bovespa)', 'region': 'Emerging'},
    # Commodities
    'GLD': {'name': 'Gold', 'region': 'Commodity'},
    'USO': {'name': 'Oil (WTI)', 'region': 'Commodity'},
}

START_DATE = '2010-01-01'
END_DATE = '2026-12-31'
RV_WINDOW = 22
FORECAST_HORIZON = 22

# ============================================================
# DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K756: International VIX Sufficiency")
print("Does VIX Predict Non-US Market Volatility?")
print("=" * 70)

# Download VIX
vix_df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix = vix_df['Close'].dropna()
print(f"\nVIX: {len(vix)} obs, {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}")

# Download all market ETFs
market_data = {}
for ticker, info in MARKETS.items():
    df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df['Close'].dropna()
    if len(close) < 500:
        print(f"  WARNING: {ticker} ({info['name']}) only {len(close)} obs — may be unreliable")
    market_data[ticker] = close
    print(f"  {ticker} ({info['name']}): {len(close)} obs")

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def compute_rv(returns, window=22):
    """Compute annualized realized volatility."""
    return (returns ** 2).rolling(window).sum().apply(np.sqrt) * np.sqrt(252 / window)

def compute_forward_rv(returns, window=22, horizon=22):
    """Compute forward-looking realized volatility."""
    rv = compute_rv(returns, window)
    return rv.shift(-horizon)

def run_regression(x, y):
    """Run OLS regression, return results dict."""
    valid = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
    x_c, y_c = x[valid], y[valid]
    if len(x_c) < 50:
        return None
    slope, intercept, r_value, p_value, std_err = stats.linregress(x_c, y_c)
    return {
        'n': int(len(x_c)),
        'R2': round(float(r_value ** 2), 4),
        'beta': round(float(slope), 4),
        't_stat': round(float(slope / std_err), 2) if std_err > 0 else None,
        'p_value': float(f"{p_value:.2e}"),
        'correlation': round(float(r_value), 4),
    }

def run_multiple_regression(X_mat, y):
    """Run multiple OLS, return R², coefficients, t-stats."""
    valid = np.all(~(np.isnan(X_mat) | np.isinf(X_mat)), axis=1) & ~(np.isnan(y) | np.isinf(y))
    X_c = X_mat[valid]
    y_c = y[valid]
    if len(y_c) < 50:
        return None
    # Add intercept
    X_design = np.column_stack([np.ones(len(y_c)), X_c])
    try:
        beta = np.linalg.lstsq(X_design, y_c, rcond=None)[0]
        y_hat = X_design @ beta
        ss_res = np.sum((y_c - y_hat) ** 2)
        ss_tot = np.sum((y_c - np.mean(y_c)) ** 2)
        R2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Standard errors
        n, k = X_design.shape
        sigma2 = ss_res / (n - k)
        XtX_inv = np.linalg.inv(X_design.T @ X_design)
        se = np.sqrt(np.diag(XtX_inv) * sigma2)
        t_stats = beta / se

        return {
            'n': int(len(y_c)),
            'R2': round(float(R2), 4),
            'betas': [round(float(b), 6) for b in beta],
            't_stats': [round(float(t), 2) for t in t_stats],
            'se': [round(float(s), 6) for s in se],
        }
    except np.linalg.LinAlgError:
        return None

def partial_correlation(x, y, z):
    """Compute partial correlation of x and y controlling for z."""
    valid = ~(np.isnan(x) | np.isnan(y) | np.isnan(z) | np.isinf(x) | np.isinf(y) | np.isinf(z))
    x_c, y_c, z_c = x[valid], y[valid], z[valid]
    if len(x_c) < 50:
        return None, None, None
    # Residualize x on z
    _, _, r_xz, _, _ = stats.linregress(z_c, x_c)
    resid_x = x_c - (stats.linregress(z_c, x_c)[0] * z_c + stats.linregress(z_c, x_c)[1])
    # Residualize y on z
    resid_y = y_c - (stats.linregress(z_c, y_c)[0] * z_c + stats.linregress(z_c, y_c)[1])
    # Correlation of residuals
    r_partial, p_partial = stats.pearsonr(resid_x, resid_y)
    # t-stat for partial correlation
    n = len(x_c)
    t_partial = r_partial * np.sqrt((n - 3) / (1 - r_partial**2)) if abs(r_partial) < 1 else np.inf
    return round(float(r_partial), 4), round(float(p_partial), 6), round(float(t_partial), 2)

# ============================================================
# PART 1: VIX PREDICTION R² FOR EACH MARKET
# ============================================================
print("\n" + "=" * 70)
print("PART 1: VIX Prediction R² for Each Market")
print("RV_{t+22} = α + β × VIX_t + ε")
print("=" * 70)

results_by_market = {}

for ticker, info in MARKETS.items():
    close = market_data[ticker]
    ret = close.pct_change().dropna()

    # Realized volatility (current and forward)
    rv_current = compute_rv(ret, RV_WINDOW)
    rv_forward = compute_forward_rv(ret, RV_WINDOW, FORECAST_HORIZON)

    # Align VIX (scaled to decimal) and forward RV
    vix_scaled = vix / 100  # VIX in % → decimal

    # Use shift(1) for VIX: signal from t-1 predicts RV at t+22
    # Actually for prediction R², we test contemporaneous VIX_t → RV_{t+22}
    # The shift(-22) in forward RV already creates natural separation
    # But to be conservative, we also lag VIX by 1 day
    vix_lagged = vix_scaled.shift(1)

    common = rv_forward.dropna().index.intersection(vix_lagged.dropna().index).intersection(rv_current.dropna().index)
    if len(common) < 200:
        print(f"\n  {ticker} ({info['name']}): SKIP ({len(common)} obs)")
        continue

    rv_fwd = rv_forward.loc[common].values
    vix_val = vix_lagged.loc[common].values
    own_rv = rv_current.loc[common].values

    # Descriptive statistics
    desc = {
        'market': info['name'],
        'region': info['region'],
        'n_obs': int(len(common)),
        'period': f"{common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}",
        'mean_rv_fwd_pct': round(float(np.nanmean(rv_fwd) * 100), 2),
        'std_rv_fwd_pct': round(float(np.nanstd(rv_fwd) * 100), 2),
        'mean_own_rv_pct': round(float(np.nanmean(own_rv) * 100), 2),
        'mean_vix_pct': round(float(np.nanmean(vix_val) * 100), 2),
    }

    # Model A: VIX-only → RV_fwd
    model_a = run_regression(vix_val, rv_fwd)

    # Model B: OwnRV-only → RV_fwd
    model_b = run_regression(own_rv, rv_fwd)

    # Model C: VIX + OwnRV → RV_fwd (multiple regression)
    X_combined = np.column_stack([vix_val, own_rv])
    model_c = run_multiple_regression(X_combined, rv_fwd)

    # Incremental R² of VIX beyond OwnRV
    if model_b and model_c:
        incremental_r2_vix = model_c['R2'] - model_b['R2']
    else:
        incremental_r2_vix = None

    # Incremental R² of OwnRV beyond VIX
    if model_a and model_c:
        incremental_r2_own = model_c['R2'] - model_a['R2']
    else:
        incremental_r2_own = None

    # Partial correlation: VIX | OwnRV
    pcorr_vix, pcorr_p, pcorr_t = partial_correlation(vix_val, rv_fwd, own_rv)

    # Partial correlation: OwnRV | VIX
    pcorr_own, pcorr_own_p, pcorr_own_t = partial_correlation(own_rv, rv_fwd, vix_val)

    # Correlation of this market's returns with SPY (for cross-section analysis)
    spy_ret = market_data['SPY'].pct_change().dropna()
    mkt_ret = close.pct_change().dropna()
    common_ret = spy_ret.index.intersection(mkt_ret.index)
    if len(common_ret) > 200:
        corr_with_spy = round(float(np.corrcoef(spy_ret.loc[common_ret].values, mkt_ret.loc[common_ret].values)[0, 1]), 4)
    else:
        corr_with_spy = None

    results_by_market[ticker] = {
        'descriptive': desc,
        'model_a_vix_only': model_a,
        'model_b_own_rv_only': model_b,
        'model_c_combined': model_c,
        'incremental_r2_vix': round(float(incremental_r2_vix), 4) if incremental_r2_vix is not None else None,
        'incremental_r2_own_rv': round(float(incremental_r2_own), 4) if incremental_r2_own is not None else None,
        'partial_corr_vix_given_own_rv': {
            'r': pcorr_vix,
            'p': pcorr_p,
            't': pcorr_t,
        } if pcorr_vix is not None else None,
        'partial_corr_own_rv_given_vix': {
            'r': pcorr_own,
            'p': pcorr_own_p,
            't': pcorr_own_t,
        } if pcorr_own is not None else None,
        'corr_with_spy': corr_with_spy,
    }

    # Print summary
    r2a = model_a['R2'] if model_a else 'N/A'
    r2b = model_b['R2'] if model_b else 'N/A'
    r2c = model_c['R2'] if model_c else 'N/A'
    incr = f"{incremental_r2_vix:.4f}" if incremental_r2_vix is not None else 'N/A'
    pcr = f"{pcorr_vix:.4f}" if pcorr_vix is not None else 'N/A'
    pct = f"(t={pcorr_t:.1f})" if pcorr_t is not None else ''

    print(f"\n  {ticker} ({info['name']}, {info['region']}): N={len(common)}")
    print(f"    Model A (VIX only):   R² = {r2a}")
    print(f"    Model B (Own RV):     R² = {r2b}")
    print(f"    Model C (VIX+OwnRV): R² = {r2c}")
    print(f"    ΔR² (VIX|OwnRV):     {incr}")
    print(f"    Partial corr VIX:     {pcr} {pct}")
    print(f"    Corr with SPY:        {corr_with_spy}")

# ============================================================
# PART 2: CROSS-SECTIONAL ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("PART 2: Cross-Sectional Analysis")
print("=" * 70)

# Collect cross-sectional data
cross_data = []
for ticker, res in results_by_market.items():
    if res['model_a_vix_only'] is None:
        continue
    cross_data.append({
        'ticker': ticker,
        'name': res['descriptive']['market'],
        'region': res['descriptive']['region'],
        'R2_vix': res['model_a_vix_only']['R2'],
        'R2_own': res['model_b_own_rv_only']['R2'] if res['model_b_own_rv_only'] else None,
        'R2_combined': res['model_c_combined']['R2'] if res['model_c_combined'] else None,
        'incremental_r2_vix': res['incremental_r2_vix'],
        'partial_corr_vix': res['partial_corr_vix_given_own_rv']['r'] if res['partial_corr_vix_given_own_rv'] else None,
        'corr_with_spy': res['corr_with_spy'],
    })

df_cross = pd.DataFrame(cross_data)

# Sort by VIX R²
df_cross_sorted = df_cross.sort_values('R2_vix', ascending=False)
print("\nRanking by VIX R² (highest to lowest):")
print("-" * 85)
print(f"{'Rank':>4} {'Ticker':>6} {'Market':<22} {'Region':<10} {'R²_VIX':>7} {'R²_Own':>7} {'R²_Comb':>8} {'ΔR²_VIX':>8} {'ρ_SPY':>7}")
print("-" * 85)
for i, (_, row) in enumerate(df_cross_sorted.iterrows()):
    r2own = f"{row['R2_own']:.4f}" if row['R2_own'] is not None else 'N/A'
    r2comb = f"{row['R2_combined']:.4f}" if row['R2_combined'] is not None else 'N/A'
    incr = f"{row['incremental_r2_vix']:.4f}" if row['incremental_r2_vix'] is not None else 'N/A'
    corr_spy = f"{row['corr_with_spy']:.4f}" if row['corr_with_spy'] is not None else 'N/A'
    print(f"  {i+1:>2}. {row['ticker']:>6} {row['name']:<22} {row['region']:<10} {row['R2_vix']:>7.4f} {r2own:>7} {r2comb:>8} {incr:>8} {corr_spy:>7}")

# Cross-sectional statistics
non_us = df_cross[df_cross['ticker'] != 'SPY']
all_r2_vix = df_cross['R2_vix'].values
non_us_r2_vix = non_us['R2_vix'].values

print(f"\nCross-sectional statistics:")
print(f"  All markets: mean R²_VIX = {np.mean(all_r2_vix):.4f}, median = {np.median(all_r2_vix):.4f}")
print(f"  Non-US only: mean R²_VIX = {np.mean(non_us_r2_vix):.4f}, median = {np.median(non_us_r2_vix):.4f}")
print(f"  SPY R²_VIX:  {df_cross[df_cross['ticker']=='SPY']['R2_vix'].values[0]:.4f}")

# Test: does US-corr predict VIX R²?
valid_cross = df_cross.dropna(subset=['corr_with_spy', 'R2_vix'])
# Exclude SPY itself (trivially corr=1, R²=highest)
valid_non_us = valid_cross[valid_cross['ticker'] != 'SPY']

if len(valid_non_us) >= 5:
    corr_spy_vals = valid_non_us['corr_with_spy'].values
    r2_vix_vals = valid_non_us['R2_vix'].values

    # Spearman rank correlation (more robust)
    spearman_r, spearman_p = stats.spearmanr(corr_spy_vals, r2_vix_vals)
    # Pearson
    pearson_r, pearson_p = stats.pearsonr(corr_spy_vals, r2_vix_vals)

    cross_section_test = {
        'hypothesis': 'Higher US correlation → higher VIX R² for non-US markets',
        'n_markets': int(len(valid_non_us)),
        'spearman_r': round(float(spearman_r), 4),
        'spearman_p': round(float(spearman_p), 4),
        'pearson_r': round(float(pearson_r), 4),
        'pearson_p': round(float(pearson_p), 4),
        'hypothesis_supported': bool(spearman_r > 0.3 and spearman_p < 0.10),
    }

    print(f"\nHypothesis test: US-corr → VIX R² (non-US markets only, N={len(valid_non_us)}):")
    print(f"  Spearman r = {spearman_r:.4f}, p = {spearman_p:.4f}")
    print(f"  Pearson r  = {pearson_r:.4f}, p = {pearson_p:.4f}")

    if cross_section_test['hypothesis_supported']:
        print(f"  → SUPPORTED: markets more correlated with US have higher VIX R²")
    else:
        print(f"  → NOT clearly supported (r={spearman_r:.3f}, p={spearman_p:.3f})")
else:
    cross_section_test = {'status': 'insufficient_markets'}
    print("\n  Insufficient non-US markets for cross-sectional test")

# ============================================================
# PART 3: VIX INCREMENTAL CONTRIBUTION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("PART 3: VIX Incremental Contribution (Beyond Own RV)")
print("=" * 70)

print(f"\n{'Ticker':>6} {'Market':<22} {'ΔR²_VIX':>8} {'Partial_r':>10} {'t-stat':>7} {'VIX adds?':>10}")
print("-" * 73)

vix_adds_count = 0
total_tested = 0
for ticker, res in results_by_market.items():
    pcorr = res.get('partial_corr_vix_given_own_rv')
    if pcorr is None:
        continue
    total_tested += 1
    incr = res['incremental_r2_vix']
    pr = pcorr['r']
    pt = pcorr['t']

    adds_info = 'YES' if (incr is not None and incr > 0.01 and pt is not None and abs(pt) > 3.0) else 'marginal' if (incr is not None and incr > 0.005) else 'NO'
    if adds_info == 'YES':
        vix_adds_count += 1

    incr_str = f"{incr:.4f}" if incr is not None else 'N/A'
    pt_str = f"{pt:.1f}" if pt is not None else 'N/A'

    print(f"  {ticker:>6} {MARKETS[ticker]['name']:<22} {incr_str:>8} {pr:>10.4f} {pt_str:>7} {adds_info:>10}")

print(f"\nVIX adds significant info (ΔR²>1%, Harvey t>3): {vix_adds_count}/{total_tested} markets")

# ============================================================
# PART 4: REGION-LEVEL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("PART 4: Region-Level Summary")
print("=" * 70)

region_stats = {}
for region in ['Americas', 'Europe', 'Asia', 'Emerging', 'Commodity']:
    region_tickers = [t for t, info in MARKETS.items() if info['region'] == region and t in results_by_market]
    if not region_tickers:
        continue

    r2_vals = [results_by_market[t]['model_a_vix_only']['R2'] for t in region_tickers
               if results_by_market[t]['model_a_vix_only'] is not None]
    incr_vals = [results_by_market[t]['incremental_r2_vix'] for t in region_tickers
                 if results_by_market[t]['incremental_r2_vix'] is not None]

    region_stats[region] = {
        'n_markets': len(region_tickers),
        'tickers': region_tickers,
        'mean_R2_vix': round(float(np.mean(r2_vals)), 4) if r2_vals else None,
        'mean_incremental_R2': round(float(np.mean(incr_vals)), 4) if incr_vals else None,
    }

    r2_str = f"{np.mean(r2_vals):.4f}" if r2_vals else 'N/A'
    incr_str = f"{np.mean(incr_vals):.4f}" if incr_vals else 'N/A'
    print(f"\n  {region} ({len(region_tickers)} markets): mean R²_VIX = {r2_str}, mean ΔR²_VIX = {incr_str}")
    for t in region_tickers:
        r2 = results_by_market[t]['model_a_vix_only']['R2'] if results_by_market[t]['model_a_vix_only'] else 'N/A'
        print(f"    {t}: R²_VIX = {r2}")

# ============================================================
# PART 5: UNIVERSALITY TEST — F-TEST FOR VIX COEFFICIENT
# ============================================================
print("\n" + "=" * 70)
print("PART 5: Universality Test — Is VIX Significant for ALL Markets?")
print("=" * 70)

sig_count = 0
harvey_count = 0
total_valid = 0

for ticker, res in results_by_market.items():
    model_a = res.get('model_a_vix_only')
    if model_a is None:
        continue
    total_valid += 1
    t_stat = model_a.get('t_stat')
    if t_stat is not None:
        if abs(t_stat) > 1.96:
            sig_count += 1
        if abs(t_stat) > 3.0:
            harvey_count += 1

    sig_str = "*** Harvey" if (t_stat and abs(t_stat) > 3.0) else ("** p<.05" if (t_stat and abs(t_stat) > 1.96) else "  n.s.")
    t_str = f"{t_stat:.1f}" if t_stat else 'N/A'
    print(f"  {ticker:>6} ({MARKETS[ticker]['name']:<22}): β_VIX t = {t_str:>7} {sig_str}")

print(f"\n  Significant at 5%: {sig_count}/{total_valid}")
print(f"  Harvey t>3.0:      {harvey_count}/{total_valid}")
print(f"  Universal? {'YES' if sig_count == total_valid else 'NO'} (all significant)")

# ============================================================
# SYNTHESIS
# ============================================================
print("\n" + "=" * 70)
print("SYNTHESIS")
print("=" * 70)

# Key metrics
all_r2 = [res['model_a_vix_only']['R2'] for res in results_by_market.values()
          if res['model_a_vix_only'] is not None]
non_us_r2 = [res['model_a_vix_only']['R2'] for t, res in results_by_market.items()
             if t != 'SPY' and res['model_a_vix_only'] is not None]
all_incr = [res['incremental_r2_vix'] for res in results_by_market.values()
            if res['incremental_r2_vix'] is not None]
non_us_incr = [res['incremental_r2_vix'] for t, res in results_by_market.items()
               if t != 'SPY' and res['incremental_r2_vix'] is not None]

spy_r2 = results_by_market.get('SPY', {}).get('model_a_vix_only', {}).get('R2', None)

print(f"\n1. VIX predicts forward RV for {sig_count}/{total_valid} markets (all significant at 5%)")
print(f"   Harvey t>3.0: {harvey_count}/{total_valid} markets")
print(f"\n2. VIX R² range: {min(all_r2):.4f} to {max(all_r2):.4f}")
print(f"   SPY R² = {spy_r2}")
print(f"   Non-US mean R² = {np.mean(non_us_r2):.4f} (vs SPY {spy_r2})")
print(f"\n3. Incremental R² (VIX beyond own RV):")
print(f"   All markets: mean = {np.mean(all_incr):.4f}")
print(f"   Non-US: mean = {np.mean(non_us_incr):.4f}")
print(f"\n4. Cross-sectional: US-correlation → VIX R²?")
if 'spearman_r' in cross_section_test:
    print(f"   Spearman r = {cross_section_test['spearman_r']:.3f} (p={cross_section_test['spearman_p']:.3f})")
    if cross_section_test['hypothesis_supported']:
        print(f"   → Markets more integrated with US benefit more from VIX")
    else:
        print(f"   → Relationship weak or not significant")

# Determine if VIX is truly international
vix_universal = sig_count == total_valid
vix_strong_intl = np.mean(non_us_r2) > 0.10 and harvey_count >= total_valid * 0.6

conclusion_lines = []
if vix_universal:
    conclusion_lines.append(f"VIX predicts forward RV in ALL {total_valid} international markets tested (universal).")
else:
    conclusion_lines.append(f"VIX predicts forward RV in {sig_count}/{total_valid} markets ({total_valid-sig_count} not significant).")

conclusion_lines.append(f"Non-US mean R² = {np.mean(non_us_r2):.3f} (SPY R² = {spy_r2}).")

if vix_strong_intl:
    conclusion_lines.append("VIX is a GLOBAL vol predictor with economically meaningful R² for most markets.")
else:
    conclusion_lines.append("VIX prediction power weakens for non-US markets.")

conclusion_lines.append(f"VIX adds incremental info beyond own RV for {vix_adds_count}/{total_tested} markets.")

conclusion_str = " ".join(conclusion_lines)
print(f"\nCONCLUSION: {conclusion_str}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K756',
    'title': 'International VIX Sufficiency — Does VIX Work for Non-US Markets?',
    'proposer': 'Claude (Paper 5 review + research_program)',
    'executor': 'Claude',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': f'yfinance ({", ".join(MARKETS.keys())}, ^VIX)',
    'data_period': f'{START_DATE} to {END_DATE}',
    'methodology': {
        'markets_tested': {k: v for k, v in MARKETS.items()},
        'rv_window': RV_WINDOW,
        'forecast_horizon': FORECAST_HORIZON,
        'signal_lag': 'VIX.shift(1) — t-1 VIX predicts RV_{t+22}',
        'models': {
            'A': 'RV_fwd = α + β×VIX + ε (VIX only)',
            'B': 'RV_fwd = α + β×OwnRV + ε (own RV only)',
            'C': 'RV_fwd = α + β₁×VIX + β₂×OwnRV + ε (combined)',
        },
        'incremental_r2': 'R²(C) - R²(B) = unique VIX contribution',
        'partial_correlation': 'corr(VIX, RV_fwd | OwnRV)',
    },
    'results_by_market': results_by_market,
    'cross_sectional_analysis': {
        'ranking': df_cross_sorted[['ticker', 'name', 'region', 'R2_vix', 'R2_own', 'R2_combined',
                                      'incremental_r2_vix', 'partial_corr_vix', 'corr_with_spy']].to_dict('records'),
        'all_markets_mean_R2_vix': round(float(np.mean(all_r2)), 4),
        'non_us_mean_R2_vix': round(float(np.mean(non_us_r2)), 4),
        'spy_R2': spy_r2,
        'all_markets_mean_incr_R2': round(float(np.mean(all_incr)), 4),
        'non_us_mean_incr_R2': round(float(np.mean(non_us_incr)), 4),
        'us_corr_vs_vix_r2_test': cross_section_test,
    },
    'region_summary': region_stats,
    'universality_test': {
        'total_markets': total_valid,
        'significant_5pct': sig_count,
        'harvey_t3': harvey_count,
        'universal_5pct': vix_universal,
        'universal_harvey': harvey_count == total_valid,
    },
    'synthesis': {
        'vix_universal_predictor': vix_universal,
        'vix_strong_international': vix_strong_intl,
        'r2_range': [round(float(min(all_r2)), 4), round(float(max(all_r2)), 4)],
        'non_us_mean_r2': round(float(np.mean(non_us_r2)), 4),
        'spy_r2': spy_r2,
        'vix_adds_info_count': f"{vix_adds_count}/{total_tested}",
        'mean_incremental_r2_non_us': round(float(np.mean(non_us_incr)), 4),
    },
    'conclusion': conclusion_str,
    'references': [
        'K752: VIX sufficiency time-invariant across 33 years (US)',
        'K669: VIX global fear signal, corr 0.609-0.762',
        'K681: VIX percentile global, EFA t=5.419 Harvey PASS',
        'K567: VIX-conditional leverage LIMITED generalizability',
        'K697: VIX predicts vol magnitude (corr 0.57) not direction (corr 0.04)',
    ],
}

output_path = 'experiments/k756_international_vix_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("K756 complete.")
