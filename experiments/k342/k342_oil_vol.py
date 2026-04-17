#!/usr/bin/env python3
"""
K342: Crude Oil Volatility Prediction — A Completely Different Asset
=====================================================================
新研究路線：原油波動率預測

Background: All prior vol prediction work focused on equities/gold/bonds.
Crude oil (CL=F) is fundamentally different — driven by geopolitics, OPEC,
and supply/demand dynamics. This experiment asks:
  - Does GARCH work for oil?
  - Is there an "oil VIX" (OVX)?
  - Does VIX predict oil vol?
  - Are there oil→equity vol spillovers?

Data: yfinance
  - CL=F (WTI Crude Oil futures, 20+ years)
  - OVX (CBOE Crude Oil Volatility Index)
  - SPY, ^VIX

Methodology:
  1. Oil vol characteristics (ann vol, kurtosis, skew, ACF of r², leverage effect)
  2. VIX vs OVX for oil vol prediction (correlation, partial r)
  3. GJR-GARCH on oil (vs GARCH(1,1), QLIKE comparison with SPY)
  4. Oil-equity vol spillover (Granger causality)

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

RESULTS = {}

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K342: Crude Oil Volatility Prediction")
print("=" * 70)

tickers = {
    'CL=F': 'WTI Crude Oil Futures',
    '^OVX': 'CBOE Oil Volatility Index (OVX)',
    'SPY': 'S&P 500 ETF',
    '^VIX': 'VIX (Equity Fear Gauge)',
}

print("\n[1] Downloading data 2001-2025...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2001-01-01', end='2025-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc}), "
                  f"{close.index[0].date()} to {close.index[-1].date()}")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Check OVX availability
has_ovx = '^OVX' in data and len(data['^OVX']) > 500
print(f"\n  OVX available: {has_ovx}")
if has_ovx:
    print(f"  OVX range: {data['^OVX'].index[0].date()} to {data['^OVX'].index[-1].date()}")
    print(f"  OVX obs: {len(data['^OVX'])}")

# ============================================================
# 2. Oil Volatility Characteristics
# ============================================================
print("\n" + "=" * 70)
print("[2] Oil Volatility Characteristics")
print("=" * 70)

# Align oil + SPY + VIX
oil_spy = pd.DataFrame({
    'CL': data['CL=F'],
    'SPY': data['SPY'],
    'VIX': data['^VIX'],
}).dropna()

print(f"\nAligned CL+SPY+VIX: {len(oil_spy)} days")
print(f"  Period: {oil_spy.index[0].date()} to {oil_spy.index[-1].date()}")

# Returns
ret_cl = oil_spy['CL'].pct_change().dropna() * 100  # percentage returns
ret_spy = oil_spy['SPY'].pct_change().dropna() * 100
vix = oil_spy['VIX'].reindex(ret_cl.index)

# Basic statistics comparison
print("\n--- Return Distribution Comparison ---")
print(f"{'Statistic':<25} {'CL (Oil)':<15} {'SPY (Equity)':<15}")
print("-" * 55)

stats_table = {}
for name, r in [('CL', ret_cl), ('SPY', ret_spy)]:
    ann_vol = r.std() * np.sqrt(252)
    skew = r.skew()
    kurt = r.kurtosis()  # excess kurtosis
    jb_stat, jb_p = stats.jarque_bera(r.dropna())

    stats_table[name] = {
        'ann_vol': round(float(ann_vol), 2),
        'skewness': round(float(skew), 4),
        'excess_kurtosis': round(float(kurt), 4),
        'jarque_bera_stat': round(float(jb_stat), 1),
        'jarque_bera_p': float(jb_p),
        'min_daily_pct': round(float(r.min()), 2),
        'max_daily_pct': round(float(r.max()), 2),
        'n_obs': len(r),
    }

    print(f"  {'Ann. Vol (%)':<25} {ann_vol:>12.2f}%")
    print(f"  {'Skewness':<25} {skew:>12.4f}")
    print(f"  {'Excess Kurtosis':<25} {kurt:>12.4f}")
    print(f"  {'Jarque-Bera stat':<25} {jb_stat:>12.1f}")
    print(f"  {'Min daily (%)':<25} {r.min():>12.2f}%")
    print(f"  {'Max daily (%)':<25} {r.max():>12.2f}%")
    print()

RESULTS['return_stats'] = stats_table

# ============================================================
# 2b. ACF of r² (Volatility Clustering)
# ============================================================
print("--- Volatility Clustering (ACF of r²) ---")

r2_cl = (ret_cl ** 2)
r2_spy = (ret_spy ** 2)

acf_lags = [1, 5, 10, 22, 44]
acf_results = {}
for name, r2 in [('CL', r2_cl), ('SPY', r2_spy)]:
    acfs = []
    for lag in acf_lags:
        acf_val = r2.autocorr(lag=lag)
        acfs.append(round(float(acf_val), 4))
    acf_results[name] = dict(zip([str(l) for l in acf_lags], acfs))
    print(f"  {name} ACF(r²): {dict(zip(acf_lags, acfs))}")

RESULTS['acf_r_squared'] = acf_results

# Ljung-Box test for vol clustering
from statsmodels.stats.diagnostic import acorr_ljungbox
for name, r2 in [('CL', r2_cl), ('SPY', r2_spy)]:
    lb = acorr_ljungbox(r2.dropna(), lags=[10], return_df=True)
    lb_stat = float(lb['lb_stat'].iloc[0])
    lb_p = float(lb['lb_pvalue'].iloc[0])
    print(f"  {name} Ljung-Box(10): stat={lb_stat:.1f}, p={lb_p:.6f}")
    acf_results[f'{name}_ljung_box_10'] = {'stat': round(lb_stat, 1), 'p': lb_p}

print()

# ============================================================
# 2c. Leverage Effect in Oil (GJR gamma)
# ============================================================
print("--- Leverage Effect: GJR Asymmetry ---")
print("  (Equity: negative returns → higher vol. Oil: does this hold?)")

leverage_results = {}
for name, r in [('CL', ret_cl), ('SPY', ret_spy)]:
    # Fit GJR-GARCH(1,1)
    am = arch_model(r.dropna(), vol='Garch', p=1, o=1, q=1, dist='Normal')
    res = am.fit(disp='off', show_warning=False)

    omega = res.params.get('omega', 0)
    alpha = res.params.get('alpha[1]', 0)
    gamma = res.params.get('gamma[1]', 0)
    beta = res.params.get('beta[1]', 0)

    # gamma > 0 means negative shock amplifies vol (classic leverage)
    # gamma < 0 or ~0 means no leverage effect
    leverage_results[name] = {
        'omega': round(float(omega), 6),
        'alpha': round(float(alpha), 4),
        'gamma': round(float(gamma), 4),
        'beta': round(float(beta), 4),
        'gamma_pvalue': round(float(res.pvalues.get('gamma[1]', 1)), 4),
        'persistence': round(float(alpha + gamma / 2 + beta), 4),
    }

    has_leverage = gamma > 0 and res.pvalues.get('gamma[1]', 1) < 0.05
    print(f"\n  {name} GJR-GARCH(1,1):")
    print(f"    alpha={alpha:.4f}, gamma={gamma:.4f} (p={res.pvalues.get('gamma[1]', 1):.4f}), beta={beta:.4f}")
    print(f"    Persistence: {alpha + gamma / 2 + beta:.4f}")
    print(f"    Leverage effect: {'YES' if has_leverage else 'NO / WEAK'}")
    if name == 'CL':
        if gamma < 0:
            print(f"    → Oil shows INVERSE leverage (positive shocks raise vol MORE)")
            print(f"    → Makes sense: supply shocks → price spikes → higher vol")
        elif gamma > 0:
            print(f"    → Oil shows STANDARD leverage (negative shocks raise vol)")
        else:
            print(f"    → Oil shows NO asymmetry")

RESULTS['leverage_effect'] = leverage_results
print()

# ============================================================
# 3. VIX vs OVX for Oil Volatility Prediction
# ============================================================
print("=" * 70)
print("[3] VIX vs OVX for Oil Vol Prediction")
print("=" * 70)

# Realized volatility (22-day rolling)
rv_cl_22 = (ret_cl ** 2).rolling(22).mean().apply(np.sqrt) * np.sqrt(252)
rv_spy_22 = (ret_spy ** 2).rolling(22).mean().apply(np.sqrt) * np.sqrt(252)

# Forward 22-day RV (what we want to predict)
fwd_rv_cl = rv_cl_22.shift(-22)
fwd_rv_spy = rv_spy_22.shift(-22)

# Align with VIX
pred_df = pd.DataFrame({
    'VIX': vix,
    'RV_CL_fwd': fwd_rv_cl,
    'RV_CL_now': rv_cl_22,
    'RV_SPY_fwd': fwd_rv_spy,
}).dropna()

print(f"\nPrediction dataset (VIX only): {len(pred_df)} obs")

# 3a. VIX → future oil RV
corr_vix_oil = pred_df['VIX'].corr(pred_df['RV_CL_fwd'])
print(f"\n  Corr(VIX, future oil RV22): {corr_vix_oil:.4f}")

# VIX → future SPY RV (for comparison)
corr_vix_spy = pred_df['VIX'].corr(pred_df['RV_SPY_fwd'])
print(f"  Corr(VIX, future SPY RV22): {corr_vix_spy:.4f}")

# Partial correlation: VIX → future oil RV | controlling for current oil RV
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation of x and y, controlling for z."""
    # Residualize x on z
    X_z = np.column_stack([z, np.ones(len(z))])
    coef_x, _, _, _ = lstsq(X_z, x, rcond=None)
    resid_x = x - X_z @ coef_x

    coef_y, _, _, _ = lstsq(X_z, y, rcond=None)
    resid_y = y - X_z @ coef_y

    return np.corrcoef(resid_x, resid_y)[0, 1]

pr_vix_oilrv = partial_corr(
    pred_df['VIX'].values,
    pred_df['RV_CL_fwd'].values,
    pred_df['RV_CL_now'].values,
)
print(f"\n  Partial r(VIX, future oil RV | current oil RV): {pr_vix_oilrv:.4f}")

vix_pred_results = {
    'corr_vix_future_oil_rv': round(float(corr_vix_oil), 4),
    'corr_vix_future_spy_rv': round(float(corr_vix_spy), 4),
    'partial_r_vix_oil_rv': round(float(pr_vix_oilrv), 4),
    'n_obs': len(pred_df),
}

# 3b. OVX analysis (if available)
if has_ovx:
    ovx = data['^OVX']
    pred_df_ovx = pd.DataFrame({
        'VIX': vix,
        'OVX': ovx,
        'RV_CL_fwd': fwd_rv_cl,
        'RV_CL_now': rv_cl_22,
    }).dropna()

    print(f"\n  OVX prediction dataset: {len(pred_df_ovx)} obs")
    print(f"  OVX period: {pred_df_ovx.index[0].date()} to {pred_df_ovx.index[-1].date()}")

    corr_ovx_oil = pred_df_ovx['OVX'].corr(pred_df_ovx['RV_CL_fwd'])
    corr_vix_oil_ovx = pred_df_ovx['VIX'].corr(pred_df_ovx['RV_CL_fwd'])
    print(f"\n  Corr(OVX, future oil RV): {corr_ovx_oil:.4f}")
    print(f"  Corr(VIX, future oil RV): {corr_vix_oil_ovx:.4f}  (same period)")
    print(f"  → OVX {'better' if abs(corr_ovx_oil) > abs(corr_vix_oil_ovx) else 'worse'} than VIX for oil vol prediction")

    # Partial r: OVX → future oil RV | current oil RV
    pr_ovx_oilrv = partial_corr(
        pred_df_ovx['OVX'].values,
        pred_df_ovx['RV_CL_fwd'].values,
        pred_df_ovx['RV_CL_now'].values,
    )
    pr_vix_oilrv_ovx = partial_corr(
        pred_df_ovx['VIX'].values,
        pred_df_ovx['RV_CL_fwd'].values,
        pred_df_ovx['RV_CL_now'].values,
    )
    print(f"\n  Partial r(OVX, future oil RV | current oil RV): {pr_ovx_oilrv:.4f}")
    print(f"  Partial r(VIX, future oil RV | current oil RV): {pr_vix_oilrv_ovx:.4f}")

    # OVX vs VIX correlation
    ovx_vix_corr = pred_df_ovx['OVX'].corr(pred_df_ovx['VIX'])
    print(f"\n  Corr(OVX, VIX): {ovx_vix_corr:.4f}")

    # Does OVX add info beyond VIX?
    # Partial r: OVX → future oil RV | VIX + current oil RV
    controls = np.column_stack([
        pred_df_ovx['VIX'].values,
        pred_df_ovx['RV_CL_now'].values,
        np.ones(len(pred_df_ovx)),
    ])
    coef_x, _, _, _ = lstsq(controls, pred_df_ovx['OVX'].values, rcond=None)
    resid_ovx = pred_df_ovx['OVX'].values - controls @ coef_x
    coef_y, _, _, _ = lstsq(controls, pred_df_ovx['RV_CL_fwd'].values, rcond=None)
    resid_fwd = pred_df_ovx['RV_CL_fwd'].values - controls @ coef_y
    pr_ovx_beyond_vix = np.corrcoef(resid_ovx, resid_fwd)[0, 1]
    print(f"  Partial r(OVX, future oil RV | VIX + current RV): {pr_ovx_beyond_vix:.4f}")
    print(f"  → OVX {'adds' if abs(pr_ovx_beyond_vix) > 0.05 else 'does NOT add'} info beyond VIX")

    vix_pred_results['ovx_period_n_obs'] = len(pred_df_ovx)
    vix_pred_results['corr_ovx_future_oil_rv'] = round(float(corr_ovx_oil), 4)
    vix_pred_results['corr_vix_future_oil_rv_same_period'] = round(float(corr_vix_oil_ovx), 4)
    vix_pred_results['partial_r_ovx_oil_rv'] = round(float(pr_ovx_oilrv), 4)
    vix_pred_results['partial_r_vix_oil_rv_same_period'] = round(float(pr_vix_oilrv_ovx), 4)
    vix_pred_results['corr_ovx_vix'] = round(float(ovx_vix_corr), 4)
    vix_pred_results['partial_r_ovx_beyond_vix'] = round(float(pr_ovx_beyond_vix), 4)
else:
    print("\n  OVX not available — using VIX only analysis")

RESULTS['vix_ovx_prediction'] = vix_pred_results
print()

# ============================================================
# 4. GJR-GARCH on Oil — QLIKE Forecast Evaluation
# ============================================================
print("=" * 70)
print("[4] GJR-GARCH vs GARCH(1,1) on Oil — OOS Forecast Comparison")
print("=" * 70)

# Use 5 rolling OOS windows
window_size = 1000  # in-sample
oos_size = 252      # 1-year OOS
n_total = len(ret_cl.dropna())

# Calculate number of possible windows
n_windows = min(5, (n_total - window_size) // oos_size)
print(f"\n  Total obs: {n_total}, IS window: {window_size}, OOS: {oos_size}")
print(f"  Number of OOS windows: {n_windows}")

ret_cl_clean = ret_cl.dropna()

# Also do SPY for comparison
ret_spy_clean = ret_spy.dropna().reindex(ret_cl_clean.index).dropna()
ret_cl_aligned = ret_cl_clean.reindex(ret_spy_clean.index).dropna()
ret_spy_aligned = ret_spy_clean.reindex(ret_cl_aligned.index).dropna()

# Common index
common_idx = ret_cl_aligned.index.intersection(ret_spy_aligned.index)
ret_cl_aligned = ret_cl_aligned.loc[common_idx]
ret_spy_aligned = ret_spy_aligned.loc[common_idx]

def run_garch_oos(returns, model_type='Garch', o=0, window=1000, oos=252, n_win=5):
    """Run rolling OOS GARCH forecast and compute QLIKE."""
    n = len(returns)
    qlikes = []
    mses = []

    for w in range(n_win):
        start = w * oos
        end_is = start + window
        end_oos = end_is + oos

        if end_oos > n:
            break

        is_data = returns.iloc[start:end_is]
        oos_data = returns.iloc[end_is:end_oos]

        # Fit on in-sample
        try:
            am = arch_model(is_data, vol=model_type, p=1, o=o, q=1, dist='Normal')
            res = am.fit(disp='off', show_warning=False, options={'maxiter': 500})

            # Forecast OOS (one-step-ahead, re-estimate every day is too slow;
            # use fixed parameters + recursive variance)
            forecasts = res.forecast(horizon=1, start=is_data.index[-1],
                                     method='simulation', simulations=100,
                                     reindex=False)

            # Alternative: simple expanding forecast
            # For each OOS day, predict variance using fitted params
            params = res.params
            cond_var = res.conditional_volatility ** 2

            # Initialize with last in-sample conditional variance
            last_var = float(cond_var.iloc[-1])
            last_ret = float(is_data.iloc[-1])

            omega = float(params.get('omega', 0))
            alpha = float(params.get('alpha[1]', 0))
            gamma_param = float(params.get('gamma[1]', 0)) if o > 0 else 0.0
            beta = float(params.get('beta[1]', 0))

            pred_vars = []
            actual_vars = []
            h = last_var
            r_prev = last_ret

            for t in range(len(oos_data)):
                # Predict
                indicator = 1.0 if r_prev < 0 else 0.0
                h = omega + (alpha + gamma_param * indicator) * r_prev**2 + beta * h
                h = max(h, 1e-8)
                pred_vars.append(h)

                # Actual
                r_t = float(oos_data.iloc[t])
                actual_vars.append(r_t ** 2)
                r_prev = r_t

            pred_vars = np.array(pred_vars)
            actual_vars = np.array(actual_vars)

            # QLIKE: mean(rv/h + log(h))
            # Use realized variance (r²) as proxy for actual variance
            # Avoid division by zero
            valid = pred_vars > 1e-10
            qlike = np.mean(actual_vars[valid] / pred_vars[valid] + np.log(pred_vars[valid]))
            mse = np.mean((actual_vars - pred_vars) ** 2)

            qlikes.append(qlike)
            mses.append(mse)

        except Exception as e:
            print(f"    Window {w}: fit failed ({e})")
            continue

    return {
        'mean_qlike': float(np.mean(qlikes)) if qlikes else None,
        'std_qlike': float(np.std(qlikes)) if len(qlikes) > 1 else None,
        'mean_mse': float(np.mean(mses)) if mses else None,
        'n_windows': len(qlikes),
        'qlikes': [round(q, 4) for q in qlikes],
    }

garch_results = {}
print("\n--- Oil (CL=F) ---")
for model_name, vol_type, o_param in [
    ('GARCH(1,1)', 'Garch', 0),
    ('GJR-GARCH(1,1)', 'Garch', 1),
]:
    print(f"\n  {model_name}:")
    res = run_garch_oos(ret_cl_aligned, model_type=vol_type, o=o_param,
                        window=window_size, oos=oos_size, n_win=n_windows)
    garch_results[f'CL_{model_name}'] = res
    if res['mean_qlike'] is not None:
        print(f"    Mean QLIKE: {res['mean_qlike']:.4f} (±{res['std_qlike']:.4f})")
        print(f"    Per-window: {res['qlikes']}")
    else:
        print(f"    FAILED")

print("\n--- SPY (for comparison) ---")
for model_name, vol_type, o_param in [
    ('GARCH(1,1)', 'Garch', 0),
    ('GJR-GARCH(1,1)', 'Garch', 1),
]:
    print(f"\n  {model_name}:")
    res = run_garch_oos(ret_spy_aligned, model_type=vol_type, o=o_param,
                        window=window_size, oos=oos_size, n_win=n_windows)
    garch_results[f'SPY_{model_name}'] = res
    if res['mean_qlike'] is not None:
        print(f"    Mean QLIKE: {res['mean_qlike']:.4f} (±{res['std_qlike']:.4f})")
        print(f"    Per-window: {res['qlikes']}")
    else:
        print(f"    FAILED")

# Compare GJR vs GARCH for oil
cl_garch_q = garch_results.get('CL_GARCH(1,1)', {}).get('mean_qlike')
cl_gjr_q = garch_results.get('CL_GJR-GARCH(1,1)', {}).get('mean_qlike')
spy_garch_q = garch_results.get('SPY_GARCH(1,1)', {}).get('mean_qlike')
spy_gjr_q = garch_results.get('SPY_GJR-GARCH(1,1)', {}).get('mean_qlike')

print("\n--- Summary ---")
if cl_garch_q and cl_gjr_q:
    improvement = (cl_garch_q - cl_gjr_q) / abs(cl_garch_q) * 100
    print(f"  Oil: GJR {'beats' if cl_gjr_q < cl_garch_q else 'loses to'} GARCH by {abs(improvement):.2f}%")
if spy_garch_q and spy_gjr_q:
    improvement_spy = (spy_garch_q - spy_gjr_q) / abs(spy_garch_q) * 100
    print(f"  SPY: GJR {'beats' if spy_gjr_q < spy_garch_q else 'loses to'} GARCH by {abs(improvement_spy):.2f}%")
if cl_garch_q and spy_garch_q:
    print(f"  Oil QLIKE: {cl_garch_q:.4f} vs SPY QLIKE: {spy_garch_q:.4f}")
    print(f"  → Oil is {'harder' if cl_garch_q > spy_garch_q else 'easier'} to predict than SPY")

# DM test: GJR vs GARCH for oil
cl_garch_qlikes = garch_results.get('CL_GARCH(1,1)', {}).get('qlikes', [])
cl_gjr_qlikes = garch_results.get('CL_GJR-GARCH(1,1)', {}).get('qlikes', [])
if len(cl_garch_qlikes) >= 3 and len(cl_gjr_qlikes) >= 3:
    dm_diff = [g - j for g, j in zip(cl_garch_qlikes, cl_gjr_qlikes)]
    dm_mean = np.mean(dm_diff)
    dm_se = np.std(dm_diff, ddof=1) / np.sqrt(len(dm_diff))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0
    dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), df=len(dm_diff) - 1))
    print(f"\n  DM test (GARCH vs GJR for oil): t={dm_t:.3f}, p={dm_p:.4f}")
    print(f"  → {'Significant' if abs(dm_t) > 2 else 'Not significant'} at 5% level")
    garch_results['dm_test_oil_gjr_vs_garch'] = {
        't_stat': round(float(dm_t), 3),
        'p_value': round(float(dm_p), 4),
        'significant_5pct': abs(dm_t) > 2,
    }

RESULTS['garch_comparison'] = garch_results
print()

# ============================================================
# 5. Oil-Equity Volatility Spillover
# ============================================================
print("=" * 70)
print("[5] Oil-Equity Volatility Spillover (Granger Causality)")
print("=" * 70)

# Use 5-day realized vol for Granger
rv5_cl = (ret_cl_aligned ** 2).rolling(5).mean().apply(np.sqrt) * np.sqrt(252)
rv5_spy = (ret_spy_aligned ** 2).rolling(5).mean().apply(np.sqrt) * np.sqrt(252)

rv_df = pd.DataFrame({
    'rv_cl': rv5_cl,
    'rv_spy': rv5_spy,
}).dropna()

print(f"\n  RV5 dataset: {len(rv_df)} obs")

# Granger causality test (using statsmodels)
from statsmodels.tsa.stattools import grangercausalitytests

print("\n--- Granger Causality: Oil vol → SPY vol ---")
granger_oil_spy = {}
try:
    gc_data = rv_df[['rv_spy', 'rv_cl']].values  # [Y, X] — test if X Granger-causes Y
    gc_result = grangercausalitytests(gc_data, maxlag=5, verbose=False)
    for lag in [1, 2, 5]:
        if lag in gc_result:
            f_stat = gc_result[lag][0]['ssr_ftest'][0]
            f_p = gc_result[lag][0]['ssr_ftest'][1]
            print(f"  Lag {lag}: F={f_stat:.3f}, p={f_p:.6f} {'***' if f_p < 0.001 else '**' if f_p < 0.01 else '*' if f_p < 0.05 else ''}")
            granger_oil_spy[f'lag_{lag}'] = {
                'F_stat': round(float(f_stat), 3),
                'p_value': round(float(f_p), 6),
                'significant_5pct': f_p < 0.05,
            }
except Exception as e:
    print(f"  Error: {e}")

print("\n--- Granger Causality: SPY vol → Oil vol ---")
granger_spy_oil = {}
try:
    gc_data2 = rv_df[['rv_cl', 'rv_spy']].values
    gc_result2 = grangercausalitytests(gc_data2, maxlag=5, verbose=False)
    for lag in [1, 2, 5]:
        if lag in gc_result2:
            f_stat = gc_result2[lag][0]['ssr_ftest'][0]
            f_p = gc_result2[lag][0]['ssr_ftest'][1]
            print(f"  Lag {lag}: F={f_stat:.3f}, p={f_p:.6f} {'***' if f_p < 0.001 else '**' if f_p < 0.01 else '*' if f_p < 0.05 else ''}")
            granger_spy_oil[f'lag_{lag}'] = {
                'F_stat': round(float(f_stat), 3),
                'p_value': round(float(f_p), 6),
                'significant_5pct': f_p < 0.05,
            }
except Exception as e:
    print(f"  Error: {e}")

# Bi-directional summary
oil_causes_spy = any(v.get('significant_5pct', False) for v in granger_oil_spy.values())
spy_causes_oil = any(v.get('significant_5pct', False) for v in granger_spy_oil.values())
print(f"\n  Oil vol → SPY vol: {'YES' if oil_causes_spy else 'NO'}")
print(f"  SPY vol → Oil vol: {'YES' if spy_causes_oil else 'NO'}")
if oil_causes_spy and spy_causes_oil:
    print(f"  → BIDIRECTIONAL spillover (feedback loop)")
elif oil_causes_spy:
    print(f"  → Oil vol leads equity vol (energy crisis channel)")
elif spy_causes_oil:
    print(f"  → Equity vol leads oil vol (risk-off channel)")
else:
    print(f"  → No significant vol spillover detected")

RESULTS['granger_causality'] = {
    'oil_causes_spy': granger_oil_spy,
    'spy_causes_oil': granger_spy_oil,
    'bidirectional': oil_causes_spy and spy_causes_oil,
}

# ============================================================
# 5b. Cross-correlation structure
# ============================================================
print("\n--- Cross-correlation: Oil vol vs SPY vol ---")
cross_corrs = {}
for lag in [-5, -3, -1, 0, 1, 3, 5]:
    if lag >= 0:
        cc = rv_df['rv_cl'].corr(rv_df['rv_spy'].shift(lag))
    else:
        cc = rv_df['rv_spy'].corr(rv_df['rv_cl'].shift(-lag))
    cross_corrs[lag] = round(float(cc), 4)
    direction = "oil leads" if lag > 0 else ("spy leads" if lag < 0 else "concurrent")
    print(f"  Lag {lag:+d} ({direction}): {cc:.4f}")

RESULTS['cross_correlation'] = cross_corrs

# ============================================================
# 6. Oil-specific phenomena
# ============================================================
print("\n" + "=" * 70)
print("[6] Oil-Specific Volatility Phenomena")
print("=" * 70)

# 6a. Contango/Backwardation effect (using rolling return as proxy)
# Oil in contango → negative roll yield → different vol dynamics
print("\n--- Oil Roll/Trend Regime ---")

# Use 60-day return as trend indicator
oil_trend = data['CL=F'].pct_change(60)
oil_trend_aligned = oil_trend.reindex(ret_cl.index).dropna()
rv22_aligned = rv_cl_22.reindex(oil_trend_aligned.index).dropna()
oil_trend_final = oil_trend_aligned.reindex(rv22_aligned.index)

# Contango regime: oil price falling (negative 60d return)
# Backwardation regime: oil price rising (positive 60d return)
contango = rv22_aligned[oil_trend_final < 0]
backwardation = rv22_aligned[oil_trend_final > 0]

print(f"  Contango-like periods (falling oil, 60d ret < 0): {len(contango)} days")
print(f"    Mean RV22: {contango.mean():.2f}%")
print(f"  Backwardation-like periods (rising oil, 60d ret > 0): {len(backwardation)} days")
print(f"    Mean RV22: {backwardation.mean():.2f}%")
t_regime, p_regime = stats.ttest_ind(contango.dropna(), backwardation.dropna())
print(f"  t-test: t={t_regime:.3f}, p={p_regime:.6f}")
print(f"  → Oil vol is {'higher' if contango.mean() > backwardation.mean() else 'lower'} when prices are falling")

RESULTS['oil_regime'] = {
    'contango_mean_rv': round(float(contango.mean()), 2),
    'backwardation_mean_rv': round(float(backwardation.mean()), 2),
    'contango_n': len(contango),
    'backwardation_n': len(backwardation),
    't_stat': round(float(t_regime), 3),
    'p_value': round(float(p_regime), 6),
}

# 6b. Extreme event frequency
print("\n--- Extreme Event Frequency ---")
for threshold in [3, 5, 10]:
    n_extreme_cl = (ret_cl.abs() > threshold).sum()
    n_extreme_spy = (ret_spy.abs() > threshold).sum()
    print(f"  |return| > {threshold}%: Oil={n_extreme_cl}, SPY={n_extreme_spy}")

RESULTS['extreme_events'] = {
    'oil_gt_3pct': int((ret_cl.abs() > 3).sum()),
    'oil_gt_5pct': int((ret_cl.abs() > 5).sum()),
    'oil_gt_10pct': int((ret_cl.abs() > 10).sum()),
    'spy_gt_3pct': int((ret_spy.abs() > 3).sum()),
    'spy_gt_5pct': int((ret_spy.abs() > 5).sum()),
    'spy_gt_10pct': int((ret_spy.abs() > 10).sum()),
}

# ============================================================
# 7. Full-Sample GJR Parameter Comparison
# ============================================================
print("\n" + "=" * 70)
print("[7] Full-Sample GJR-GARCH Parameter Comparison")
print("=" * 70)

full_params = {}
for name, r in [('CL', ret_cl_aligned), ('SPY', ret_spy_aligned)]:
    am = arch_model(r.dropna(), vol='Garch', p=1, o=1, q=1, dist='Normal')
    res = am.fit(disp='off', show_warning=False)
    params = {k: round(float(v), 6) for k, v in res.params.items()}
    pvals = {k: round(float(v), 4) for k, v in res.pvalues.items()}
    full_params[name] = {
        'params': params,
        'pvalues': pvals,
        'log_likelihood': round(float(res.loglikelihood), 2),
        'aic': round(float(res.aic), 2),
        'bic': round(float(res.bic), 2),
    }

    print(f"\n  {name}:")
    print(f"    omega = {params.get('omega', 0):.6f}")
    print(f"    alpha = {params.get('alpha[1]', 0):.4f} (p={pvals.get('alpha[1]', 1):.4f})")
    print(f"    gamma = {params.get('gamma[1]', 0):.4f} (p={pvals.get('gamma[1]', 1):.4f})")
    print(f"    beta  = {params.get('beta[1]', 0):.4f} (p={pvals.get('beta[1]', 1):.4f})")
    alpha_v = params.get('alpha[1]', 0)
    gamma_v = params.get('gamma[1]', 0)
    beta_v = params.get('beta[1]', 0)
    persist = alpha_v + gamma_v / 2 + beta_v
    print(f"    Persistence = {persist:.4f}")
    print(f"    AIC = {res.aic:.2f}, BIC = {res.bic:.2f}")
    full_params[name]['persistence'] = round(float(persist), 4)

# Key finding: compare gamma (leverage) between oil and SPY
cl_gamma = full_params['CL']['params'].get('gamma[1]', 0)
spy_gamma = full_params['SPY']['params'].get('gamma[1]', 0)
print(f"\n  Key finding:")
print(f"    Oil gamma = {cl_gamma:.4f}")
print(f"    SPY gamma = {spy_gamma:.4f}")
if cl_gamma < spy_gamma:
    print(f"    → Oil has WEAKER leverage effect ({cl_gamma:.4f} vs {spy_gamma:.4f})")
    print(f"    → This makes economic sense: oil volatility responds to supply shocks")
    print(f"      (positive price jumps) not just negative shocks")
else:
    print(f"    → Oil has STRONGER leverage effect than expected")

RESULTS['full_sample_params'] = full_params

# ============================================================
# 8. Overall Summary
# ============================================================
print("\n" + "=" * 70)
print("[8] OVERALL SUMMARY — K342 Oil Volatility Prediction")
print("=" * 70)

print("""
Key Findings:
""")

print(f"1. Oil Vol Characteristics:")
cl_stats = stats_table['CL']
spy_stats = stats_table['SPY']
print(f"   - Oil ann. vol: {cl_stats['ann_vol']}% vs SPY: {spy_stats['ann_vol']}%")
print(f"   - Oil kurtosis: {cl_stats['excess_kurtosis']} vs SPY: {spy_stats['excess_kurtosis']}")
print(f"   - Oil skewness: {cl_stats['skewness']} vs SPY: {spy_stats['skewness']}")

print(f"\n2. Leverage Effect:")
print(f"   - Oil gamma: {leverage_results['CL']['gamma']} (p={leverage_results['CL']['gamma_pvalue']})")
print(f"   - SPY gamma: {leverage_results['SPY']['gamma']} (p={leverage_results['SPY']['gamma_pvalue']})")
has_oil_leverage = leverage_results['CL']['gamma'] > 0 and leverage_results['CL']['gamma_pvalue'] < 0.05
print(f"   - Oil leverage effect: {'Present' if has_oil_leverage else 'Absent/Weak'}")

print(f"\n3. VIX for Oil Prediction:")
print(f"   - Corr(VIX, future oil RV): {vix_pred_results['corr_vix_future_oil_rv']}")
print(f"   - Partial r(VIX, oil RV | current RV): {vix_pred_results['partial_r_vix_oil_rv']}")
if has_ovx:
    print(f"   - Corr(OVX, future oil RV): {vix_pred_results.get('corr_ovx_future_oil_rv', 'N/A')}")
    print(f"   - OVX adds info beyond VIX: partial r = {vix_pred_results.get('partial_r_ovx_beyond_vix', 'N/A')}")

print(f"\n4. GARCH Performance:")
if cl_garch_q and cl_gjr_q:
    print(f"   - Oil GARCH QLIKE: {cl_garch_q:.4f}")
    print(f"   - Oil GJR QLIKE:   {cl_gjr_q:.4f}")
if spy_garch_q:
    print(f"   - SPY GARCH QLIKE: {spy_garch_q:.4f}")

print(f"\n5. Vol Spillover:")
print(f"   - Oil vol → SPY vol: {'YES' if oil_causes_spy else 'NO'}")
print(f"   - SPY vol → Oil vol: {'YES' if spy_causes_oil else 'NO'}")

print(f"\n6. Oil-Specific:")
print(f"   - Falling oil → higher vol: {RESULTS['oil_regime']['contango_mean_rv']:.2f}%")
print(f"   - Rising oil → lower vol:  {RESULTS['oil_regime']['backwardation_mean_rv']:.2f}%")

# Limitations
print(f"""
Limitations:
- CL=F is continuous futures (roll effects may introduce noise)
- OVX history shorter than VIX (if available)
- GARCH QLIKE uses r² as RV proxy (no intraday data for oil)
- Granger causality uses 5-day RV (overlapping windows → serially correlated)
- No OPEC event study (would require event dating)
- No inventory data (EIA weekly storage reports)
- Sample: {ret_cl_aligned.index[0].date()} to {ret_cl_aligned.index[-1].date()}
""")

# Save results
RESULTS['experiment'] = 'K342'
RESULTS['title'] = 'Crude Oil Volatility Prediction — A Completely Different Asset'
RESULTS['data_source'] = 'yfinance (CL=F, ^OVX, SPY, ^VIX)'
RESULTS['sample_period'] = f"{ret_cl_aligned.index[0].date()} to {ret_cl_aligned.index[-1].date()}"
RESULTS['n_obs'] = len(ret_cl_aligned)

output_path = 'experiments/k342_oil_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("DONE.")
