"""
K757: Taiwan CoVaR Contagion Structure — 0050→TSMC→Financial Sector

Research question: How does volatility/risk transmit across Taiwan's concentrated market?
- 0050.TW (index ETF), 2330.TW (TSMC), 2881.TW (Fubon FHC), 2882.TW (Cathay FHC)
- Pairwise rolling correlations, Granger causality, CoVaR (Adrian & Brunnermeier 2016)

Prior work:
- T16: TSMC vol r=0.885 with 0050 but no Granger causality; SPY Granger-causes 0050
- K82: TSMC explains 52.5% of 0050 variance; rolling beta 0.38→0.72

References:
- Adrian & Brunnermeier (2016) "CoVaR", American Economic Review
- Acharya et al. (2017) "Measuring Systemic Risk", RFS
- Engle & Manganelli (2004) "CAViaR", JBES

Data source: yfinance (0050.TW, 2330.TW, 2881.TW, 2882.TW, ^VIX)
Period: 2010-01-01 to 2026-03-28

[提出: Claude (from research_program), 執行: Claude]
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.regression.quantile_regression import QuantReg

warnings.filterwarnings('ignore')

# ============================================================
# Part 0: Data Download
# ============================================================
print("=" * 70)
print("K757: Taiwan CoVaR Contagion Structure")
print("=" * 70)

import yfinance as yf

tickers = {
    '0050': '0050.TW',
    'TSMC': '2330.TW',
    'Fubon': '2881.TW',
    'Cathay': '2882.TW',
    'VIX': '^VIX'
}

data = {}
for name, ticker in tickers.items():
    print(f"Downloading {name} ({ticker})...")
    df = yf.download(ticker, start='2010-01-01', end='2026-03-29', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].copy()
    print(f"  {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Merge into single DataFrame
prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"\nMerged dataset: {len(prices)} obs, {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Compute simple returns
returns = prices.pct_change().dropna()
print(f"Returns: {len(returns)} obs")

# Realized volatility (20-day rolling std, annualized)
rv = returns.rolling(20).std() * np.sqrt(252)
rv = rv.dropna()

results = {
    'experiment_id': 'K757',
    'title': 'Taiwan CoVaR Contagion Structure',
    'data_source': 'yfinance',
    'tickers': tickers,
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_obs_prices': len(prices),
    'n_obs_returns': len(returns),
}

# ============================================================
# Part A: Pairwise Correlation Structure
# ============================================================
print("\n" + "=" * 70)
print("Part A: Pairwise Correlation Structure")
print("=" * 70)

# Full-sample return correlations
assets = ['0050', 'TSMC', 'Fubon', 'Cathay']
corr_full = returns[assets].corr()
print("\nFull-sample return correlations:")
print(corr_full.round(3))

results['part_a'] = {
    'full_sample_corr': corr_full.to_dict(),
}

# Rolling 60-day correlations
roll_window = 60
pairs = [('0050', 'TSMC'), ('0050', 'Fubon'), ('0050', 'Cathay'), ('TSMC', 'Fubon'), ('TSMC', 'Cathay'), ('Fubon', 'Cathay')]

rolling_corr_stats = {}
for a, b in pairs:
    rc = returns[a].rolling(roll_window).corr(returns[b]).dropna()
    pair_key = f"{a}-{b}"
    rolling_corr_stats[pair_key] = {
        'mean': float(rc.mean()),
        'std': float(rc.std()),
        'min': float(rc.min()),
        'max': float(rc.max()),
        'q5': float(rc.quantile(0.05)),
        'q95': float(rc.quantile(0.95)),
        'pct_below_0.3': float((rc < 0.3).mean() * 100),
        'pct_above_0.8': float((rc > 0.8).mean() * 100),
    }
    print(f"\n{pair_key}: mean={rc.mean():.3f}, std={rc.std():.3f}, range=[{rc.min():.3f}, {rc.max():.3f}]")

results['part_a']['rolling_60d_corr'] = rolling_corr_stats

# Correlation stability: crisis vs calm
# Define crisis periods (VIX > 30)
vix_aligned = prices['VIX'].reindex(returns.index)
crisis_mask = vix_aligned > 30
calm_mask = vix_aligned <= 20
n_crisis = crisis_mask.sum()
n_calm = calm_mask.sum()
print(f"\nCrisis days (VIX>30): {n_crisis}, Calm days (VIX<=20): {n_calm}")

crisis_corr = {}
calm_corr = {}
for a, b in pairs:
    pair_key = f"{a}-{b}"
    if crisis_mask.sum() > 30:
        crisis_corr[pair_key] = float(returns.loc[crisis_mask, a].corr(returns.loc[crisis_mask, b]))
    if calm_mask.sum() > 30:
        calm_corr[pair_key] = float(returns.loc[calm_mask, a].corr(returns.loc[calm_mask, b]))

print("\nCrisis correlations (VIX>30):")
for k, v in crisis_corr.items():
    print(f"  {k}: {v:.3f}")

print("\nCalm correlations (VIX<=20):")
for k, v in calm_corr.items():
    print(f"  {k}: {v:.3f}")

results['part_a']['crisis_corr'] = crisis_corr
results['part_a']['calm_corr'] = calm_corr
results['part_a']['n_crisis_days'] = int(n_crisis)
results['part_a']['n_calm_days'] = int(n_calm)

# ============================================================
# Part B: Granger Causality Network (Realized Vol)
# ============================================================
print("\n" + "=" * 70)
print("Part B: Granger Causality Network (Realized Vol)")
print("=" * 70)

# ADF tests first
print("\nADF tests on realized vol:")
adf_results = {}
for asset in assets:
    adf_stat, adf_p, _, _, _, _ = adfuller(rv[asset].dropna(), maxlag=10)
    adf_results[asset] = {'stat': float(adf_stat), 'p_value': float(adf_p)}
    print(f"  {asset}: ADF stat={adf_stat:.3f}, p={adf_p:.6f} {'✓ stationary' if adf_p < 0.05 else '✗ non-stationary'}")

# If non-stationary, use first-differenced RV
use_diff = any(r['p_value'] > 0.05 for r in adf_results.values())
if use_diff:
    print("\nSome RV series non-stationary -> using first-differenced RV")
    rv_test = rv.diff().dropna()
else:
    rv_test = rv.copy()

# Granger causality tests (lag selection by AIC via maxlag=10)
gc_pairs = [
    ('0050', 'TSMC'), ('TSMC', '0050'),
    ('0050', 'Fubon'), ('Fubon', '0050'),
    ('0050', 'Cathay'), ('Cathay', '0050'),
    ('TSMC', 'Fubon'), ('Fubon', 'TSMC'),
    ('TSMC', 'Cathay'), ('Cathay', 'TSMC'),
    ('Fubon', 'Cathay'), ('Cathay', 'Fubon'),
]

granger_results = {}
print("\nGranger Causality Tests (H0: X does NOT Granger-cause Y):")
print(f"{'X → Y':<20} {'Best Lag':>8} {'F-stat':>10} {'p-value':>10} {'Significant':>12}")
print("-" * 65)

for x_name, y_name in gc_pairs:
    gc_data = pd.DataFrame({
        'y': rv_test[y_name],
        'x': rv_test[x_name]
    }).dropna()

    # Test up to 10 lags
    try:
        gc_test = grangercausalitytests(gc_data[['y', 'x']], maxlag=10, verbose=False)

        # Select best lag by minimum p-value (conservative) and also report AIC-selected
        best_lag = None
        best_p = 1.0
        best_f = 0.0
        for lag in range(1, 11):
            f_stat = gc_test[lag][0]['ssr_ftest'][0]
            p_val = gc_test[lag][0]['ssr_ftest'][1]
            if p_val < best_p:
                best_p = p_val
                best_f = f_stat
                best_lag = lag

        sig = '***' if best_p < 0.001 else '**' if best_p < 0.01 else '*' if best_p < 0.05 else ''
        pair_key = f"{x_name}→{y_name}"
        granger_results[pair_key] = {
            'best_lag': int(best_lag),
            'f_stat': float(best_f),
            'p_value': float(best_p),
            'significant': best_p < 0.05
        }
        print(f"{pair_key:<20} {best_lag:>8} {best_f:>10.3f} {best_p:>10.6f} {sig:>12}")
    except Exception as e:
        print(f"{x_name}→{y_name}: ERROR - {e}")
        granger_results[f"{x_name}→{y_name}"] = {'error': str(e)}

results['part_b'] = {
    'adf_results': adf_results,
    'used_differenced_rv': use_diff,
    'granger_causality': granger_results,
}

# ============================================================
# Part C: CoVaR (Adrian & Brunnermeier 2016)
# ============================================================
print("\n" + "=" * 70)
print("Part C: CoVaR Analysis (Adrian & Brunnermeier 2016)")
print("=" * 70)

def compute_covar(y_returns, x_returns, state_vars=None, tau=0.05):
    """
    Compute CoVaR using quantile regression.

    CoVaR^{y|x=VaR_x} = alpha + beta * VaR_x(tau) + gamma * state

    Steps:
    1. Estimate VaR_x via quantile regression on state vars
    2. Estimate CoVaR_y|x via quantile regression: y on x and state vars
    3. CoVaR = predicted y when x = VaR_x(tau)
    4. CoVaR_median = predicted y when x = VaR_x(0.50)
    5. DeltaCoVaR = CoVaR - CoVaR_median
    """
    # Align data
    df = pd.DataFrame({'y': y_returns, 'x': x_returns}).dropna()

    if state_vars is not None:
        for col in state_vars.columns:
            df[col] = state_vars[col]
        df = df.dropna()

    n = len(df)
    if n < 100:
        return None

    # Build regressor matrix for y equation: x + state_vars (lagged)
    X_cols = ['x']
    if state_vars is not None:
        X_cols += list(state_vars.columns)

    X = df[X_cols].copy()
    X = X.shift(1)  # signal.shift(1) — lag to avoid lookahead
    X['const'] = 1.0

    y = df['y']

    # Drop NaN from shift
    mask = X.notna().all(axis=1)
    X = X[mask]
    y = y[mask]

    if len(y) < 100:
        return None

    # Quantile regression at tau (VaR level)
    try:
        model_tau = QuantReg(y, X)
        res_tau = model_tau.fit(q=tau, max_iter=5000)

        model_med = QuantReg(y, X)
        res_med = model_med.fit(q=0.50, max_iter=5000)
    except Exception as e:
        print(f"  QuantReg failed: {e}")
        return None

    # Compute time-varying CoVaR
    covar_tau = res_tau.predict(X)
    covar_med = res_med.predict(X)
    delta_covar = covar_tau - covar_med

    # Also compute unconditional VaR for comparison
    unconditional_var = np.percentile(y, tau * 100)

    return {
        'covar_tau_mean': float(covar_tau.mean()),
        'covar_tau_std': float(covar_tau.std()),
        'covar_med_mean': float(covar_med.mean()),
        'delta_covar_mean': float(delta_covar.mean()),
        'delta_covar_std': float(delta_covar.std()),
        'unconditional_var': float(unconditional_var),
        'beta_x_tau': float(res_tau.params.get('x', np.nan)),
        'beta_x_tau_pval': float(res_tau.pvalues.get('x', np.nan)),
        'beta_x_med': float(res_med.params.get('x', np.nan)),
        'n_obs': int(len(y)),
        'covar_tau_series': covar_tau,
        'delta_covar_series': delta_covar,
        'covar_index': y.index,
    }

# State variables: VIX (lagged), market vol
vix_ret = prices['VIX'].pct_change()
state = pd.DataFrame({
    'vix_level': prices['VIX'],
    'mkt_vol': returns['0050'].rolling(20).std() * np.sqrt(252),
}).reindex(returns.index)

# CoVaR pairs: contribution of each asset to 0050
covar_pairs = [
    ('0050', 'TSMC', 'TSMC → 0050'),
    ('0050', 'Fubon', 'Fubon → 0050'),
    ('0050', 'Cathay', 'Cathay → 0050'),
    ('TSMC', 'Fubon', 'Fubon → TSMC'),
]

covar_results = {}
print(f"\nCoVaR at tau=0.05 (left-tail risk contribution):")
print(f"{'Pair':<20} {'ΔCoVaR mean':>12} {'ΔCoVaR std':>12} {'β(x,τ=.05)':>12} {'p-value':>10} {'Uncondit VaR':>14}")
print("-" * 85)

covar_series_data = {}  # Store for Part D

for y_name, x_name, label in covar_pairs:
    result = compute_covar(
        returns[y_name],
        returns[x_name],
        state_vars=state,
        tau=0.05
    )

    if result is not None:
        # Store series for later use
        covar_series_data[label] = {
            'delta_covar': result['delta_covar_series'],
            'index': result['covar_index'],
        }

        # Remove non-serializable items for JSON
        result_json = {k: v for k, v in result.items()
                      if k not in ['covar_tau_series', 'delta_covar_series', 'covar_index']}
        covar_results[label] = result_json

        sig = '***' if result['beta_x_tau_pval'] < 0.001 else '**' if result['beta_x_tau_pval'] < 0.01 else '*' if result['beta_x_tau_pval'] < 0.05 else ''
        print(f"{label:<20} {result['delta_covar_mean']:>12.6f} {result['delta_covar_std']:>12.6f} {result['beta_x_tau']:>12.4f} {result['beta_x_tau_pval']:>9.4f}{sig} {result['unconditional_var']:>14.6f}")
    else:
        print(f"{label:<20} FAILED")

results['part_c'] = {'covar_analysis': covar_results}

# Time-varying ΔCoVaR: Is TSMC's contribution increasing?
print("\n--- Time-Varying ΔCoVaR for TSMC → 0050 ---")
if 'TSMC → 0050' in covar_series_data:
    dc = covar_series_data['TSMC → 0050']['delta_covar']
    idx = covar_series_data['TSMC → 0050']['index']

    # Split into 3-year periods
    periods = {}
    for yr_start in range(2011, 2025, 3):
        yr_end = yr_start + 3
        mask = (idx.year >= yr_start) & (idx.year < yr_end)
        if mask.sum() > 50:
            period_key = f"{yr_start}-{yr_end}"
            periods[period_key] = {
                'mean_delta_covar': float(dc[mask].mean()),
                'std_delta_covar': float(dc[mask].std()),
                'n_obs': int(mask.sum()),
            }

    print(f"{'Period':<12} {'Mean ΔCoVaR':>14} {'Std':>10} {'N':>6}")
    print("-" * 46)
    for period, vals in periods.items():
        print(f"{period:<12} {vals['mean_delta_covar']:>14.6f} {vals['std_delta_covar']:>10.6f} {vals['n_obs']:>6}")

    # Trend test: regress ΔCoVaR on time
    dc_df = pd.DataFrame({'dc': dc, 'time': np.arange(len(dc))})
    from scipy.stats import linregress
    slope, intercept, r, p, se = linregress(dc_df['time'], dc_df['dc'])
    print(f"\nLinear trend in ΔCoVaR: slope={slope:.2e}, r²={r**2:.4f}, p={p:.6f}")

    results['part_c']['tsmc_covar_periods'] = periods
    results['part_c']['tsmc_covar_trend'] = {
        'slope': float(slope),
        'r_squared': float(r**2),
        'p_value': float(p),
        'interpretation': 'TSMC systemic risk increasing' if slope < 0 and p < 0.05 else
                         'No significant trend' if p >= 0.05 else 'TSMC systemic risk decreasing'
    }

# ============================================================
# Part D: Implications for VT — Does TSMC RV improve 0050 prediction?
# ============================================================
print("\n" + "=" * 70)
print("Part D: TSMC RV as Predictor for 0050 VT (Beyond VIX)")
print("=" * 70)

# Prepare data: predict 0050 next-day RV
from sklearn.linear_model import LinearRegression
from scipy.stats import spearmanr

# Use 5-day RV instead of 20-day for more responsiveness
rv5 = returns.rolling(5).std() * np.sqrt(252)

# Predictors (all lagged by 1 day)
pred_df = pd.DataFrame({
    '0050_rv': rv5['0050'],
    'TSMC_rv': rv5['TSMC'].shift(1),  # signal.shift(1)
    'Fubon_rv': rv5['Fubon'].shift(1),  # signal.shift(1)
    'Cathay_rv': rv5['Cathay'].shift(1),  # signal.shift(1)
    'VIX': prices['VIX'].shift(1),  # signal.shift(1) — lagged for Taiwan
    'TSMC_ret_abs': returns['TSMC'].abs().shift(1),  # signal.shift(1)
}).dropna()

# Target: next-day 0050 absolute return (proxy for realized vol)
pred_df['target'] = returns['0050'].abs().shift(-1)  # Next-day |return|
pred_df = pred_df.dropna()

print(f"Prediction sample: {len(pred_df)} obs")

# Model 1: VIX only
X1 = pred_df[['VIX']]
# Model 2: VIX + TSMC_rv
X2 = pred_df[['VIX', 'TSMC_rv']]
# Model 3: VIX + TSMC_rv + Financial_rv
X3 = pred_df[['VIX', 'TSMC_rv', 'Fubon_rv', 'Cathay_rv']]
# Model 4: TSMC_rv only (no VIX)
X4 = pred_df[['TSMC_rv']]

y = pred_df['target']

# OOS evaluation (rolling 500-day window)
oos_window = 500
models_oos = {'VIX_only': [], 'VIX+TSMC': [], 'VIX+TSMC+Fin': [], 'TSMC_only': []}
model_Xs = {'VIX_only': X1, 'VIX+TSMC': X2, 'VIX+TSMC+Fin': X3, 'TSMC_only': X4}

print("\nOut-of-sample evaluation (rolling 500-day window)...")
for i in range(oos_window, len(pred_df) - 1):
    for mname, X in model_Xs.items():
        X_train = X.iloc[i-oos_window:i]
        y_train = y.iloc[i-oos_window:i]
        X_test = X.iloc[i:i+1]
        y_test = y.iloc[i]

        reg = LinearRegression().fit(X_train, y_train)
        pred = reg.predict(X_test)[0]
        models_oos[mname].append((y_test, pred))

# Compute R² OOS and QLIKE
print(f"\n{'Model':<20} {'R² OOS':>10} {'QLIKE':>10} {'Spearman ρ':>12} {'N':>6}")
print("-" * 62)

oos_metrics = {}
for mname, preds in models_oos.items():
    actual = np.array([p[0] for p in preds])
    predicted = np.array([p[1] for p in preds])

    # Clip predictions to positive
    predicted = np.maximum(predicted, 1e-8)

    # R² OOS
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot

    # QLIKE
    qlike = np.mean(np.log(predicted) + actual / predicted)

    # Spearman
    rho, p_rho = spearmanr(actual, predicted)

    oos_metrics[mname] = {
        'r2_oos': float(r2_oos),
        'qlike': float(qlike),
        'spearman_rho': float(rho),
        'spearman_p': float(p_rho),
        'n': len(preds),
    }
    print(f"{mname:<20} {r2_oos:>10.4f} {qlike:>10.4f} {rho:>12.4f} {len(preds):>6}")

results['part_d'] = {'oos_prediction': oos_metrics}

# Partial correlation: TSMC_RV → 0050_RV | VIX
# Regress both on VIX, then correlate residuals
from numpy.linalg import lstsq

X_vix = pred_df['VIX'].values.reshape(-1, 1)
X_vix_c = np.column_stack([X_vix, np.ones(len(X_vix))])

# Residualize 0050_rv on VIX
beta1, _, _, _ = lstsq(X_vix_c, pred_df['0050_rv'].values, rcond=None)
resid_0050 = pred_df['0050_rv'].values - X_vix_c @ beta1

# Residualize TSMC_rv on VIX
beta2, _, _, _ = lstsq(X_vix_c, pred_df['TSMC_rv'].values, rcond=None)
resid_tsmc = pred_df['TSMC_rv'].values - X_vix_c @ beta2

partial_r, partial_p = spearmanr(resid_0050, resid_tsmc)
print(f"\nPartial correlation TSMC_RV → 0050_RV | VIX: ρ={partial_r:.4f}, p={partial_p:.2e}")

results['part_d']['partial_corr_tsmc_0050_given_vix'] = {
    'spearman_rho': float(partial_r),
    'p_value': float(partial_p),
    'interpretation': 'TSMC RV adds information beyond VIX' if partial_p < 0.05 and abs(partial_r) > 0.1 else 'TSMC RV adds minimal information beyond VIX'
}

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Key findings
findings = []

# A: Correlation structure
tsmc_0050_corr = corr_full.loc['0050', 'TSMC']
fin_0050_corr = (corr_full.loc['0050', 'Fubon'] + corr_full.loc['0050', 'Cathay']) / 2
findings.append(f"A1: 0050-TSMC correlation = {tsmc_0050_corr:.3f}, 0050-Financials avg = {fin_0050_corr:.3f}")

# Crisis vs calm
if crisis_corr and calm_corr:
    crisis_diff = crisis_corr.get('0050-TSMC', 0) - calm_corr.get('0050-TSMC', 0)
    findings.append(f"A2: Crisis-Calm correlation shift (0050-TSMC): {crisis_diff:+.3f}")

# B: Granger causality
sig_gc = [(k, v) for k, v in granger_results.items() if isinstance(v, dict) and v.get('significant')]
findings.append(f"B1: Significant Granger causality pairs: {len(sig_gc)}/12")
for k, v in sig_gc:
    findings.append(f"    {k}: F={v['f_stat']:.2f}, p={v['p_value']:.6f}, lag={v['best_lag']}")

# C: CoVaR
if covar_results:
    tsmc_dc = covar_results.get('TSMC → 0050', {}).get('delta_covar_mean', None)
    fubon_dc = covar_results.get('Fubon → 0050', {}).get('delta_covar_mean', None)
    if tsmc_dc is not None:
        findings.append(f"C1: TSMC ΔCoVaR to 0050 = {tsmc_dc:.6f}")
    if fubon_dc is not None:
        findings.append(f"C2: Fubon ΔCoVaR to 0050 = {fubon_dc:.6f}")
    if tsmc_dc and fubon_dc:
        ratio = abs(tsmc_dc) / abs(fubon_dc) if fubon_dc != 0 else float('inf')
        findings.append(f"C3: TSMC/Fubon systemic risk ratio = {ratio:.2f}x")

# D: VT implications
if oos_metrics:
    vix_only_r2 = oos_metrics.get('VIX_only', {}).get('r2_oos', 0)
    vix_tsmc_r2 = oos_metrics.get('VIX+TSMC', {}).get('r2_oos', 0)
    improvement = vix_tsmc_r2 - vix_only_r2
    findings.append(f"D1: VIX-only OOS R² = {vix_only_r2:.4f}, VIX+TSMC = {vix_tsmc_r2:.4f}, improvement = {improvement:+.4f}")

findings.append(f"D2: Partial corr TSMC_RV→0050_RV|VIX = {partial_r:.4f} (p={partial_p:.2e})")

for f in findings:
    print(f)

results['summary'] = {
    'findings': findings,
    'conclusion': '',  # Will be filled below
}

# Generate conclusion
conclusion_parts = []
conclusion_parts.append(f"Taiwan market shows high concentration: 0050-TSMC corr={tsmc_0050_corr:.3f}.")

if sig_gc:
    gc_directions = [k for k, _ in sig_gc]
    conclusion_parts.append(f"Granger causality found in {len(sig_gc)} directions: {', '.join(gc_directions)}.")
else:
    conclusion_parts.append("No significant Granger causality in realized vol (confirming T16).")

if covar_results.get('TSMC → 0050'):
    tsmc_beta = covar_results['TSMC → 0050'].get('beta_x_tau', 0)
    tsmc_pval = covar_results['TSMC → 0050'].get('beta_x_tau_pval', 1)
    if tsmc_pval < 0.05:
        conclusion_parts.append(f"TSMC has significant tail-risk contribution to 0050 (β={tsmc_beta:.4f}, p={tsmc_pval:.4f}).")
    else:
        conclusion_parts.append(f"TSMC tail-risk contribution to 0050 is not significant at 5% (β={tsmc_beta:.4f}, p={tsmc_pval:.4f}).")

conclusion_parts.append(f"TSMC RV adds {'meaningful' if abs(partial_r) > 0.1 else 'minimal'} information beyond VIX for 0050 prediction (partial ρ={partial_r:.4f}).")

conclusion = ' '.join(conclusion_parts)
results['summary']['conclusion'] = conclusion
print(f"\n{conclusion}")

# ============================================================
# Save results
# ============================================================
output_path = os.path.join(os.path.dirname(__file__), 'k757_taiwan_covar_results.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {output_path}")
print("K757 complete.")
