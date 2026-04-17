"""
K210: VIX-SKEW Ratio as Volatility Smile Proxy — Extending K184

Background:
- K184 found SKEW has statistically detectable but economically negligible signal.
- K207 showed non-equity assets reject VIX sufficiency.
- This experiment asks: Does VIX/SKEW *ratio* (or interaction) work better
  for specific assets or specific VIX regimes?

Methodology:
1. VIX-SKEW interaction features:
   - Ratio: VIX/SKEW  (fear level relative to tail risk perception)
   - Product: VIX * (SKEW-100)/100  (combined fear + tail signal)
   - SKEW change: d(SKEW)/dt 5-day
2. Regime-conditional analysis:
   - Does VIX/SKEW predict vol better in high-VIX vs low-VIX regimes?
   - Split by VIX terciles
3. Asset-specific test:
   - For each of SPY, QQQ: partial correlation of VIX/SKEW features with
     future realized vol, controlling for VIX
4. GARCH-X with VIX/SKEW features
5. VT overlay with smile signal

Data: SPY, QQQ, GLD, ^VIX, ^SKEW daily from yfinance. OOS: 2023-2024.
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA LOADING
# ============================================================
print("=" * 72)
print("K210: VIX-SKEW Ratio as Volatility Smile Proxy")
print("Extending K184 — Does VIX/SKEW interaction add value?")
print("=" * 72)

DATA_START = '2006-01-01'
DATA_END = '2025-12-31'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
WINDOW = 2000

# Download all data
tickers = {
    'SPY': 'SPY',
    'QQQ': 'QQQ',
    'GLD': 'GLD',
    'VIX': '^VIX',
    'SKEW': '^SKEW',
}

raw_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end=DATA_END,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    raw_data[name] = df['close'].copy()
    print(f"  {name}: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# Build aligned DataFrame
prices = pd.DataFrame(raw_data)
prices = prices.dropna(subset=['VIX', 'SKEW'])  # need both VIX and SKEW
prices = prices.ffill()  # forward-fill any remaining gaps
prices = prices.dropna()
print(f"\nAligned data: {prices.index[0].date()} to {prices.index[-1].date()}, N={len(prices)}")

# ============================================================
# 2. FEATURE ENGINEERING
# ============================================================
print("\n" + "=" * 72)
print("2. VIX-SKEW Interaction Features")
print("=" * 72)

# Returns
for asset in ['SPY', 'QQQ', 'GLD']:
    prices[f'{asset}_ret'] = np.log(prices[asset] / prices[asset].shift(1))

# Realized vol proxies (5-day and 22-day)
for asset in ['SPY', 'QQQ', 'GLD']:
    prices[f'{asset}_rv5'] = prices[f'{asset}_ret'].rolling(5).std() * np.sqrt(252) * 100
    prices[f'{asset}_rv22'] = prices[f'{asset}_ret'].rolling(22).std() * np.sqrt(252) * 100
    # Forward realized vol (target)
    prices[f'{asset}_fwd_rv5'] = prices[f'{asset}_ret'].shift(-1).rolling(5).std() * np.sqrt(252) * 100
    prices[f'{asset}_fwd_rv22'] = prices[f'{asset}_ret'].shift(-1).rolling(22).std() * np.sqrt(252) * 100

# VIX-SKEW features
prices['VIX_SKEW_ratio'] = prices['VIX'] / prices['SKEW']
prices['VIX_SKEW_product'] = prices['VIX'] * (prices['SKEW'] - 100) / 100
prices['SKEW_chg5'] = prices['SKEW'] - prices['SKEW'].shift(5)
prices['VIX_chg5'] = prices['VIX'] - prices['VIX'].shift(5)
prices['SKEW_z'] = (prices['SKEW'] - prices['SKEW'].rolling(63).mean()) / prices['SKEW'].rolling(63).std()
prices['VIX_z'] = (prices['VIX'] - prices['VIX'].rolling(63).mean()) / prices['VIX'].rolling(63).std()
prices['ratio_z'] = (prices['VIX_SKEW_ratio'] - prices['VIX_SKEW_ratio'].rolling(63).mean()) / \
                    prices['VIX_SKEW_ratio'].rolling(63).std()

# VIX terciles for regime analysis
prices['VIX_tercile'] = pd.qcut(prices['VIX'].rolling(252).rank(pct=True),
                                  q=3, labels=['Low', 'Mid', 'High'])

# Drop NaN rows after feature creation
feature_cols = ['VIX', 'SKEW', 'VIX_SKEW_ratio', 'VIX_SKEW_product',
                'SKEW_chg5', 'VIX_chg5', 'SKEW_z', 'VIX_z', 'ratio_z']
analysis_df = prices.dropna(subset=feature_cols + ['SPY_fwd_rv22', 'VIX_tercile']).copy()
print(f"Analysis sample: {analysis_df.index[0].date()} to {analysis_df.index[-1].date()}, N={len(analysis_df)}")

# Summary stats of features
print("\nFeature Summary Statistics:")
print(analysis_df[feature_cols].describe().round(4).to_string())

# ============================================================
# 3. FULL-SAMPLE CORRELATION ANALYSIS
# ============================================================
print("\n" + "=" * 72)
print("3. Full-Sample Correlations: Features vs Future RV")
print("=" * 72)

results = {}

for asset in ['SPY', 'QQQ', 'GLD']:
    print(f"\n--- {asset} ---")
    target = f'{asset}_fwd_rv22'
    valid = analysis_df.dropna(subset=[target])

    corrs = {}
    for feat in feature_cols:
        r, p = stats.pearsonr(valid[feat], valid[target])
        corrs[feat] = {'r': r, 'p': p}
        sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else ''
        print(f"  corr({feat}, fwd_rv22) = {r:+.4f}  (p={p:.4e}) {sig}")

    results[asset] = corrs

# ============================================================
# 4. PARTIAL CORRELATION: VIX/SKEW features controlling for VIX
# ============================================================
print("\n" + "=" * 72)
print("4. Partial Correlations (controlling for VIX)")
print("=" * 72)
print("Key question: Does SKEW info add BEYOND what VIX already captures?")

def partial_corr(x, y, z):
    """Partial correlation of x and y, controlling for z."""
    # Residualize x on z
    from numpy.linalg import lstsq
    z_arr = np.column_stack([np.ones(len(z)), z])
    beta_x, _, _, _ = lstsq(z_arr, x, rcond=None)
    resid_x = x - z_arr @ beta_x
    beta_y, _, _, _ = lstsq(z_arr, y, rcond=None)
    resid_y = y - z_arr @ beta_y
    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p

partial_results = {}

for asset in ['SPY', 'QQQ', 'GLD']:
    print(f"\n--- {asset} ---")
    target = f'{asset}_fwd_rv22'
    valid = analysis_df.dropna(subset=[target]).copy()

    vix_arr = valid['VIX'].values
    target_arr = valid[target].values

    partial_results[asset] = {}
    for feat in ['SKEW', 'VIX_SKEW_ratio', 'VIX_SKEW_product', 'SKEW_chg5', 'SKEW_z', 'ratio_z']:
        feat_arr = valid[feat].values
        r_partial, p_partial = partial_corr(feat_arr, target_arr, vix_arr)
        partial_results[asset][feat] = {'r_partial': r_partial, 'p_partial': p_partial}
        sig = '***' if p_partial < 0.001 else '**' if p_partial < 0.01 else '*' if p_partial < 0.05 else ''
        print(f"  partial_r({feat}|VIX, fwd_rv22) = {r_partial:+.4f}  (p={p_partial:.4e}) {sig}")

# ============================================================
# 5. REGIME-CONDITIONAL ANALYSIS
# ============================================================
print("\n" + "=" * 72)
print("5. Regime-Conditional Analysis (VIX terciles)")
print("=" * 72)

regime_results = {}

for asset in ['SPY', 'QQQ']:
    print(f"\n--- {asset} ---")
    target = f'{asset}_fwd_rv22'
    valid = analysis_df.dropna(subset=[target, 'VIX_tercile']).copy()

    regime_results[asset] = {}
    for regime in ['Low', 'Mid', 'High']:
        subset = valid[valid['VIX_tercile'] == regime]
        n_obs = len(subset)
        print(f"\n  VIX Regime: {regime} (N={n_obs})")

        regime_results[asset][regime] = {'n': n_obs}
        for feat in ['VIX', 'SKEW', 'VIX_SKEW_ratio', 'VIX_SKEW_product', 'SKEW_chg5']:
            r, p = stats.pearsonr(subset[feat], subset[target])
            regime_results[asset][regime][feat] = {'r': r, 'p': p}
            sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else ''
            print(f"    corr({feat}, fwd_rv22) = {r:+.4f}  (p={p:.4e}) {sig}")

        # Partial correlation in this regime
        if n_obs > 50:
            vix_sub = subset['VIX'].values
            target_sub = subset[target].values
            for feat in ['SKEW', 'VIX_SKEW_ratio']:
                feat_sub = subset[feat].values
                r_p, p_p = partial_corr(feat_sub, target_sub, vix_sub)
                regime_results[asset][regime][f'{feat}_partial'] = {'r': r_p, 'p': p_p}
                sig = '***' if p_p < 0.001 else '**' if p_p < 0.01 else '*' if p_p < 0.05 else ''
                print(f"    partial_r({feat}|VIX) = {r_p:+.4f}  (p={p_p:.4e}) {sig}")

# ============================================================
# 6. OUT-OF-SAMPLE PREDICTIVE REGRESSION
# ============================================================
print("\n" + "=" * 72)
print("6. OOS Predictive Regression (2023-2024)")
print("=" * 72)

oos_mask = (analysis_df.index >= OOS_START) & (analysis_df.index <= OOS_END)
is_data = analysis_df[~oos_mask]
oos_data = analysis_df[oos_mask]
print(f"IS: {is_data.index[0].date()} to {is_data.index[-1].date()}, N={len(is_data)}")
print(f"OOS: {oos_data.index[0].date()} to {oos_data.index[-1].date()}, N={len(oos_data)}")

oos_results = {}

for asset in ['SPY', 'QQQ', 'GLD']:
    print(f"\n--- {asset} ---")
    target = f'{asset}_fwd_rv22'

    # Model 1: VIX only
    is_valid = is_data.dropna(subset=[target])
    oos_valid = oos_data.dropna(subset=[target])

    from numpy.linalg import lstsq

    # Fit on IS
    X_is_vix = np.column_stack([np.ones(len(is_valid)), is_valid['VIX'].values])
    beta_vix, _, _, _ = lstsq(X_is_vix, is_valid[target].values, rcond=None)

    # Model 2: VIX + SKEW
    X_is_vs = np.column_stack([np.ones(len(is_valid)),
                                is_valid['VIX'].values,
                                is_valid['SKEW'].values])
    beta_vs, _, _, _ = lstsq(X_is_vs, is_valid[target].values, rcond=None)

    # Model 3: VIX + VIX/SKEW ratio
    X_is_vr = np.column_stack([np.ones(len(is_valid)),
                                is_valid['VIX'].values,
                                is_valid['VIX_SKEW_ratio'].values])
    beta_vr, _, _, _ = lstsq(X_is_vr, is_valid[target].values, rcond=None)

    # Model 4: VIX + product + SKEW_chg5
    X_is_full = np.column_stack([np.ones(len(is_valid)),
                                  is_valid['VIX'].values,
                                  is_valid['VIX_SKEW_product'].values,
                                  is_valid['SKEW_chg5'].values])
    beta_full, _, _, _ = lstsq(X_is_full, is_valid[target].values, rcond=None)

    # OOS predictions
    X_oos_vix = np.column_stack([np.ones(len(oos_valid)), oos_valid['VIX'].values])
    pred_vix = X_oos_vix @ beta_vix

    X_oos_vs = np.column_stack([np.ones(len(oos_valid)),
                                 oos_valid['VIX'].values,
                                 oos_valid['SKEW'].values])
    pred_vs = X_oos_vs @ beta_vs

    X_oos_vr = np.column_stack([np.ones(len(oos_valid)),
                                 oos_valid['VIX'].values,
                                 oos_valid['VIX_SKEW_ratio'].values])
    pred_vr = X_oos_vr @ beta_vr

    X_oos_full = np.column_stack([np.ones(len(oos_valid)),
                                   oos_valid['VIX'].values,
                                   oos_valid['VIX_SKEW_product'].values,
                                   oos_valid['SKEW_chg5'].values])
    pred_full = X_oos_full @ beta_full

    actual = oos_valid[target].values

    # OOS R-squared (using IS mean as benchmark)
    ss_total = np.sum((actual - np.mean(is_valid[target].values)) ** 2)

    models = {
        'VIX_only': pred_vix,
        'VIX+SKEW': pred_vs,
        'VIX+ratio': pred_vr,
        'VIX+product+dSKEW': pred_full,
    }

    oos_results[asset] = {}
    for mname, pred in models.items():
        ss_res = np.sum((actual - pred) ** 2)
        r2_oos = 1 - ss_res / ss_total
        mae = np.mean(np.abs(actual - pred))
        # QLIKE-style loss
        pred_clipped = np.maximum(pred, 1.0)  # avoid log(0)
        qlike = np.mean(np.log(pred_clipped ** 2) + (actual ** 2) / (pred_clipped ** 2))
        oos_results[asset][mname] = {'r2_oos': r2_oos, 'mae': mae, 'qlike': qlike}
        print(f"  {mname:25s}: OOS R²={r2_oos:.4f}, MAE={mae:.2f}, QLIKE={qlike:.4f}")

    # DM test: VIX+SKEW vs VIX_only
    e_vix = (actual - pred_vix) ** 2
    e_vs = (actual - pred_vs) ** 2
    d = e_vix - e_vs  # positive if VIX+SKEW is better
    dm_stat = np.mean(d) / (np.std(d) / np.sqrt(len(d)))
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    oos_results[asset]['DM_VIX_vs_VIXSKEW'] = {'stat': dm_stat, 'p': dm_p}
    sig = '***' if dm_p < 0.001 else '**' if dm_p < 0.01 else '*' if dm_p < 0.05 else ''
    print(f"  DM test (VIX_only vs VIX+SKEW): t={dm_stat:.3f}, p={dm_p:.4f} {sig}")

    # DM test: VIX+ratio vs VIX_only
    e_vr = (actual - pred_vr) ** 2
    d2 = e_vix - e_vr
    dm_stat2 = np.mean(d2) / (np.std(d2) / np.sqrt(len(d2)))
    dm_p2 = 2 * (1 - stats.norm.cdf(abs(dm_stat2)))
    oos_results[asset]['DM_VIX_vs_VIXratio'] = {'stat': dm_stat2, 'p': dm_p2}
    sig = '***' if dm_p2 < 0.001 else '**' if dm_p2 < 0.01 else '*' if dm_p2 < 0.05 else ''
    print(f"  DM test (VIX_only vs VIX+ratio): t={dm_stat2:.3f}, p={dm_p2:.4f} {sig}")

# ============================================================
# 7. GARCH-X with VIX/SKEW FEATURES
# ============================================================
print("\n" + "=" * 72)
print("7. GARCH-X: Adding VIX/SKEW to variance equation")
print("=" * 72)

garchx_results = {}

for asset in ['SPY', 'QQQ']:
    print(f"\n--- {asset} ---")
    ret_pct = (analysis_df[f'{asset}_ret'] * 100).dropna()
    target = f'{asset}_fwd_rv22'

    # Align everything
    common_idx = ret_pct.index.intersection(analysis_df.dropna(subset=['VIX_SKEW_ratio', target]).index)
    ret_sub = ret_pct.loc[common_idx]
    feat_sub = analysis_df.loc[common_idx]

    oos_mask_g = common_idx >= pd.Timestamp(OOS_START)
    is_idx = common_idx[~oos_mask_g]
    oos_idx = common_idx[oos_mask_g]

    # Need at least WINDOW obs for IS
    if len(is_idx) < WINDOW:
        print(f"  Skipping: only {len(is_idx)} IS obs (need {WINDOW})")
        continue

    print(f"  IS: {is_idx[0].date()} to {is_idx[-1].date()}, N={len(is_idx)}")
    print(f"  OOS: {oos_idx[0].date()} to {oos_idx[-1].date()}, N={len(oos_idx)}")

    # Model A: GJR-GARCH (baseline)
    try:
        am_base = arch_model(ret_sub.loc[is_idx], vol='GARCH', p=1, o=1, q=1, dist='t')
        res_base = am_base.fit(disp='off', show_warning=False)
        print(f"  GJR-GARCH fitted: omega={res_base.params.get('omega', 0):.6f}, "
              f"alpha={res_base.params.get('alpha[1]', 0):.4f}, "
              f"gamma={res_base.params.get('gamma[1]', 0):.4f}, "
              f"beta={res_base.params.get('beta[1]', 0):.4f}")
        garchx_results[f'{asset}_base'] = {
            'BIC': float(res_base.bic),
            'LogLik': float(res_base.loglikelihood),
        }
    except Exception as e:
        print(f"  GJR-GARCH failed: {e}")
        continue

    # Model B: GARCH-X with VIX/SKEW ratio as exogenous variable in variance
    # arch library supports GARCH-X via arch_model(..., x=exog)
    # The exogenous variable enters the variance equation
    try:
        exog_ratio = feat_sub.loc[is_idx, 'VIX_SKEW_ratio'].values.reshape(-1, 1)
        am_x = arch_model(ret_sub.loc[is_idx], vol='GARCH', p=1, o=1, q=1, dist='t',
                          x=pd.DataFrame(exog_ratio, index=is_idx, columns=['VIX_SKEW_ratio']))
        res_x = am_x.fit(disp='off', show_warning=False)
        print(f"  GARCH-X (ratio) fitted: BIC={res_x.bic:.2f}")
        # Check if exogenous coefficient is significant
        for pname in res_x.params.index:
            if 'VIX_SKEW' in pname or 'x' in pname.lower():
                coef = res_x.params[pname]
                se = res_x.std_err.get(pname, np.nan)
                t_val = coef / se if se > 0 else np.nan
                p_val = 2 * (1 - stats.norm.cdf(abs(t_val)))
                sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
                print(f"    {pname}: coef={coef:.6f}, t={t_val:.3f}, p={p_val:.4f} {sig}")
                garchx_results[f'{asset}_x_ratio'] = {
                    'BIC': float(res_x.bic),
                    'LogLik': float(res_x.loglikelihood),
                    'exog_coef': float(coef),
                    'exog_t': float(t_val),
                    'exog_p': float(p_val),
                }
        delta_bic = res_x.bic - res_base.bic
        print(f"  Delta BIC (X - base): {delta_bic:.2f} ({'X better' if delta_bic < 0 else 'base better'})")
    except Exception as e:
        print(f"  GARCH-X (ratio) failed: {e}")

    # Model C: GARCH-X with SKEW change
    try:
        exog_skchg = feat_sub.loc[is_idx, 'SKEW_chg5'].values.reshape(-1, 1)
        am_x2 = arch_model(ret_sub.loc[is_idx], vol='GARCH', p=1, o=1, q=1, dist='t',
                           x=pd.DataFrame(exog_skchg, index=is_idx, columns=['SKEW_chg5']))
        res_x2 = am_x2.fit(disp='off', show_warning=False)
        print(f"  GARCH-X (SKEW_chg5) fitted: BIC={res_x2.bic:.2f}")
        for pname in res_x2.params.index:
            if 'SKEW' in pname or 'x' in pname.lower():
                coef = res_x2.params[pname]
                se = res_x2.std_err.get(pname, np.nan)
                t_val = coef / se if se > 0 else np.nan
                p_val = 2 * (1 - stats.norm.cdf(abs(t_val)))
                sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
                print(f"    {pname}: coef={coef:.6f}, t={t_val:.3f}, p={p_val:.4f} {sig}")
                garchx_results[f'{asset}_x_skewchg'] = {
                    'BIC': float(res_x2.bic),
                    'LogLik': float(res_x2.loglikelihood),
                    'exog_coef': float(coef),
                    'exog_t': float(t_val),
                    'exog_p': float(p_val),
                }
        delta_bic2 = res_x2.bic - res_base.bic
        print(f"  Delta BIC (X - base): {delta_bic2:.2f} ({'X better' if delta_bic2 < 0 else 'base better'})")
    except Exception as e:
        print(f"  GARCH-X (SKEW_chg5) failed: {e}")

# ============================================================
# 8. ROLLING OOS GARCH-X FORECAST COMPARISON
# ============================================================
print("\n" + "=" * 72)
print("8. Rolling OOS GARCH-X Forecast Comparison (2023-2024)")
print("=" * 72)

rolling_results = {}

for asset in ['SPY', 'QQQ']:
    print(f"\n--- {asset} ---")
    ret_pct = (analysis_df[f'{asset}_ret'] * 100).dropna()
    common_idx = ret_pct.index.intersection(
        analysis_df.dropna(subset=['VIX_SKEW_ratio', 'SKEW_chg5']).index)
    ret_aligned = ret_pct.loc[common_idx]
    feat_aligned = analysis_df.loc[common_idx]

    oos_dates = common_idx[common_idx >= pd.Timestamp(OOS_START)]
    if len(oos_dates) == 0:
        continue

    REFIT_FREQ = 22
    forecasts_base = {}
    forecasts_x = {}
    actuals = {}

    n_fits = 0
    last_params_base = None
    last_params_x = None

    for i, dt in enumerate(oos_dates):
        loc = common_idx.get_loc(dt)
        if loc < WINDOW:
            continue

        train_idx = common_idx[loc - WINDOW:loc]
        train_ret = ret_aligned.loc[train_idx]

        need_refit = (i % REFIT_FREQ == 0) or (last_params_base is None)

        if need_refit:
            n_fits += 1
            # Base GJR-GARCH
            try:
                am_b = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='t')
                res_b = am_b.fit(disp='off', show_warning=False, options={'maxiter': 500})
                fc_b = res_b.forecast(horizon=1)
                last_var_base = fc_b.variance.values[-1, 0]
            except:
                last_var_base = train_ret.var()

            # GARCH-X with ratio
            try:
                exog_train = feat_aligned.loc[train_idx, 'VIX_SKEW_ratio'].values.reshape(-1, 1)
                am_xr = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='t',
                                   x=pd.DataFrame(exog_train, index=train_idx, columns=['ratio']))
                res_xr = am_xr.fit(disp='off', show_warning=False, options={'maxiter': 500})
                # For forecast, we need to provide the exogenous value at forecast time
                exog_fc = feat_aligned.loc[dt, 'VIX_SKEW_ratio']
                fc_x = res_xr.forecast(horizon=1,
                                       x={1: np.array([[exog_fc]])})
                last_var_x = fc_x.variance.values[-1, 0]
            except:
                last_var_x = last_var_base  # fallback

        forecasts_base[dt] = last_var_base
        forecasts_x[dt] = last_var_x
        # Actual: next-day squared return
        if loc + 1 < len(common_idx):
            next_dt = common_idx[loc + 1]
            actuals[dt] = ret_aligned.loc[next_dt] ** 2
        else:
            actuals[dt] = np.nan

    print(f"  Refits: {n_fits}")

    # Evaluate
    common_dates = sorted(set(forecasts_base.keys()) & set(actuals.keys()))
    fc_b_arr = np.array([forecasts_base[d] for d in common_dates])
    fc_x_arr = np.array([forecasts_x[d] for d in common_dates])
    act_arr = np.array([actuals[d] for d in common_dates])

    valid_mask = ~np.isnan(act_arr) & ~np.isnan(fc_b_arr) & ~np.isnan(fc_x_arr) & (fc_b_arr > 0) & (fc_x_arr > 0)
    fc_b_arr = fc_b_arr[valid_mask]
    fc_x_arr = fc_x_arr[valid_mask]
    act_arr = act_arr[valid_mask]
    print(f"  Valid OOS forecasts: N={len(act_arr)}")

    if len(act_arr) > 30:
        # QLIKE
        qlike_base = np.mean(np.log(fc_b_arr) + act_arr / fc_b_arr)
        qlike_x = np.mean(np.log(fc_x_arr) + act_arr / fc_x_arr)

        # MSE
        mse_base = np.mean((act_arr - fc_b_arr) ** 2)
        mse_x = np.mean((act_arr - fc_x_arr) ** 2)

        print(f"  QLIKE — Base: {qlike_base:.4f}, GARCH-X(ratio): {qlike_x:.4f}, "
              f"diff: {qlike_x - qlike_base:+.4f}")
        print(f"  MSE   — Base: {mse_base:.4f}, GARCH-X(ratio): {mse_x:.4f}, "
              f"diff: {mse_x - mse_base:+.4f}")

        # DM test on QLIKE
        d_qlike = (np.log(fc_b_arr) + act_arr / fc_b_arr) - (np.log(fc_x_arr) + act_arr / fc_x_arr)
        dm_qlike = np.mean(d_qlike) / (np.std(d_qlike) / np.sqrt(len(d_qlike)))
        dm_qlike_p = 2 * (1 - stats.norm.cdf(abs(dm_qlike)))
        sig = '***' if dm_qlike_p < 0.001 else '**' if dm_qlike_p < 0.01 else '*' if dm_qlike_p < 0.05 else ''
        print(f"  DM test (QLIKE, base vs X): t={dm_qlike:.3f}, p={dm_qlike_p:.4f} {sig}")

        rolling_results[asset] = {
            'n_oos': int(len(act_arr)),
            'qlike_base': float(qlike_base),
            'qlike_x': float(qlike_x),
            'mse_base': float(mse_base),
            'mse_x': float(mse_x),
            'dm_qlike_t': float(dm_qlike),
            'dm_qlike_p': float(dm_qlike_p),
        }

# ============================================================
# 9. VT OVERLAY WITH SMILE SIGNAL
# ============================================================
print("\n" + "=" * 72)
print("9. VT Overlay with Smile Signal (VIX/SKEW ratio)")
print("=" * 72)
print("Base strategy: 12/VIX. Overlay: adjust weight by VIX/SKEW ratio z-score.")

# Only test on SPY
asset = 'SPY'
ret_daily = analysis_df[f'{asset}_ret'].copy()
vix = analysis_df['VIX'].copy()
ratio_z = analysis_df['ratio_z'].copy()

oos_mask = (analysis_df.index >= OOS_START) & (analysis_df.index <= OOS_END)
oos_ret = ret_daily[oos_mask].dropna()
oos_vix = vix[oos_mask].reindex(oos_ret.index)
oos_ratio_z = ratio_z[oos_mask].reindex(oos_ret.index)

# Base: 12/VIX (lagged)
w_base = (12 / oos_vix.shift(1)).clip(0, 1)

# Overlay A: reduce weight when ratio_z is high (VIX high relative to SKEW → more fearful)
# Intuition: when VIX/SKEW is abnormally high, market fear is disproportionate to tail risk → extra caution
w_overlay_a = w_base * (1 - 0.2 * oos_ratio_z.shift(1).clip(-2, 2))
w_overlay_a = w_overlay_a.clip(0, 1)

# Overlay B: binary rule — if ratio_z > 1, halve the weight
w_overlay_b = w_base.copy()
w_overlay_b[oos_ratio_z.shift(1) > 1] = w_base * 0.5
w_overlay_b = w_overlay_b.clip(0, 1)

# Strategy returns (with lagged weights → no look-ahead)
ret_base = w_base * oos_ret
ret_overlay_a = w_overlay_a * oos_ret
ret_overlay_b = w_overlay_b * oos_ret
ret_bh = oos_ret

# Drop initial NaN
ret_base = ret_base.dropna()
ret_overlay_a = ret_overlay_a.dropna()
ret_overlay_b = ret_overlay_b.dropna()
ret_bh = ret_bh.loc[ret_base.index]

def compute_metrics(r, name):
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    return {'name': name, 'ann_ret': ann_ret, 'ann_vol': ann_vol,
            'sharpe': sharpe, 'mdd': mdd}

vt_results = {}
for strat_name, strat_ret in [('Buy&Hold', ret_bh), ('12/VIX', ret_base),
                                ('12/VIX+ratio_z_adj', ret_overlay_a),
                                ('12/VIX+ratio_z_binary', ret_overlay_b)]:
    m = compute_metrics(strat_ret, strat_name)
    vt_results[strat_name] = m
    print(f"  {strat_name:25s}: Sharpe={m['sharpe']:.3f}, Ret={m['ann_ret']*100:.1f}%, "
          f"Vol={m['ann_vol']*100:.1f}%, MDD={m['mdd']*100:.1f}%")

# DM test on daily returns: overlay vs base
d_ret = ret_overlay_a.values ** 2 - ret_base.values ** 2
dm_vt = np.mean(d_ret) / (np.std(d_ret) / np.sqrt(len(d_ret)))
dm_vt_p = 2 * (1 - stats.norm.cdf(abs(dm_vt)))
print(f"\n  DM test (12/VIX vs overlay_A, squared returns): t={dm_vt:.3f}, p={dm_vt_p:.4f}")

# ============================================================
# 10. EXTENDED OOS: 5-PERIOD ROBUSTNESS
# ============================================================
print("\n" + "=" * 72)
print("10. Cross-OOS Robustness (5 periods)")
print("=" * 72)

oos_periods = [
    ('2015-01-01', '2016-12-31'),
    ('2017-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2021-01-01', '2022-12-31'),
    ('2023-01-01', '2024-12-31'),
]

cross_oos = {}

for p_start, p_end in oos_periods:
    period_name = f"{p_start[:4]}-{p_end[:4]}"
    pmask = (analysis_df.index >= p_start) & (analysis_df.index <= p_end)
    pdata = analysis_df[pmask].dropna(subset=['SPY_fwd_rv22'])

    if len(pdata) < 100:
        print(f"  {period_name}: insufficient data ({len(pdata)} obs), skipping")
        continue

    # IS = everything before this period
    is_pre = analysis_df[analysis_df.index < p_start].dropna(subset=['SPY_fwd_rv22'])
    if len(is_pre) < 500:
        print(f"  {period_name}: insufficient IS data ({len(is_pre)} obs), skipping")
        continue

    # Fit VIX-only and VIX+ratio on IS, predict OOS
    X_is_v = np.column_stack([np.ones(len(is_pre)), is_pre['VIX'].values])
    beta_v, _, _, _ = lstsq(X_is_v, is_pre['SPY_fwd_rv22'].values, rcond=None)

    X_is_vr = np.column_stack([np.ones(len(is_pre)),
                                is_pre['VIX'].values,
                                is_pre['VIX_SKEW_ratio'].values])
    beta_vr, _, _, _ = lstsq(X_is_vr, is_pre['SPY_fwd_rv22'].values, rcond=None)

    X_oos_v = np.column_stack([np.ones(len(pdata)), pdata['VIX'].values])
    pred_v = X_oos_v @ beta_v

    X_oos_vr = np.column_stack([np.ones(len(pdata)),
                                 pdata['VIX'].values,
                                 pdata['VIX_SKEW_ratio'].values])
    pred_vr = X_oos_vr @ beta_vr

    actual = pdata['SPY_fwd_rv22'].values

    mse_v = np.mean((actual - pred_v) ** 2)
    mse_vr = np.mean((actual - pred_vr) ** 2)

    # DM test
    d_mse = (actual - pred_v) ** 2 - (actual - pred_vr) ** 2
    dm_t = np.mean(d_mse) / (np.std(d_mse) / np.sqrt(len(d_mse)))
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

    winner = 'VIX+ratio' if mse_vr < mse_v else 'VIX_only'
    sig = '***' if dm_p < 0.001 else '**' if dm_p < 0.01 else '*' if dm_p < 0.05 else ''
    print(f"  {period_name}: MSE_VIX={mse_v:.2f}, MSE_VIX+ratio={mse_vr:.2f}, "
          f"winner={winner}, DM t={dm_t:.3f} p={dm_p:.4f} {sig}")

    cross_oos[period_name] = {
        'n_oos': int(len(pdata)),
        'mse_vix': float(mse_v),
        'mse_vix_ratio': float(mse_vr),
        'winner': winner,
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
    }

# ============================================================
# 11. GRANGER CAUSALITY: SKEW → VOL
# ============================================================
print("\n" + "=" * 72)
print("11. Granger Causality: SKEW → Realized Vol")
print("=" * 72)

for asset in ['SPY', 'QQQ']:
    print(f"\n--- {asset} ---")
    target = f'{asset}_rv22'
    valid = analysis_df.dropna(subset=[target, 'SKEW', 'VIX']).copy()

    # Test: does SKEW Granger-cause RV22, beyond VIX?
    # Restricted: RV22_t = a + b1*RV22_{t-1} + b2*VIX_{t-1}
    # Unrestricted: RV22_t = a + b1*RV22_{t-1} + b2*VIX_{t-1} + b3*SKEW_{t-1} + b4*SKEW_chg5_{t-1}
    y = valid[target].values[5:]  # skip first 5 for SKEW_chg5
    rv_lag = valid[target].shift(1).values[5:]
    vix_lag = valid['VIX'].shift(1).values[5:]
    skew_lag = valid['SKEW'].shift(1).values[5:]
    skewchg_lag = valid['SKEW_chg5'].shift(1).values[5:]

    mask = ~(np.isnan(y) | np.isnan(rv_lag) | np.isnan(vix_lag) | np.isnan(skew_lag) | np.isnan(skewchg_lag))
    y = y[mask]
    rv_lag = rv_lag[mask]
    vix_lag = vix_lag[mask]
    skew_lag = skew_lag[mask]
    skewchg_lag = skewchg_lag[mask]

    n = len(y)

    # Restricted model
    X_r = np.column_stack([np.ones(n), rv_lag, vix_lag])
    beta_r, _, _, _ = lstsq(X_r, y, rcond=None)
    resid_r = y - X_r @ beta_r
    ssr_r = np.sum(resid_r ** 2)

    # Unrestricted model
    X_u = np.column_stack([np.ones(n), rv_lag, vix_lag, skew_lag, skewchg_lag])
    beta_u, _, _, _ = lstsq(X_u, y, rcond=None)
    resid_u = y - X_u @ beta_u
    ssr_u = np.sum(resid_u ** 2)

    k_diff = X_u.shape[1] - X_r.shape[1]  # 2 extra params
    f_stat = ((ssr_r - ssr_u) / k_diff) / (ssr_u / (n - X_u.shape[1]))
    f_p = 1 - stats.f.cdf(f_stat, k_diff, n - X_u.shape[1])

    sig = '***' if f_p < 0.001 else '**' if f_p < 0.01 else '*' if f_p < 0.05 else ''
    print(f"  Granger F-test (SKEW → RV22 | VIX): F={f_stat:.3f}, p={f_p:.4f} {sig}")
    print(f"  SSR_restricted={ssr_r:.2f}, SSR_unrestricted={ssr_u:.2f}, "
          f"reduction={((ssr_r-ssr_u)/ssr_r)*100:.3f}%")

# ============================================================
# 12. SYNTHESIS & CONCLUSIONS
# ============================================================
print("\n" + "=" * 72)
print("12. SYNTHESIS")
print("=" * 72)

# Collect all results
all_results = {
    'experiment': 'K210',
    'title': 'VIX-SKEW Ratio as Volatility Smile Proxy',
    'data': f'{prices.index[0].date()} to {prices.index[-1].date()}',
    'oos': f'{OOS_START} to {OOS_END}',
    'partial_correlations': {},
    'oos_predictive_regression': {},
    'rolling_garchx': rolling_results,
    'vt_overlay': {},
    'cross_oos': cross_oos,
}

# Summarize partial correlations
for asset in ['SPY', 'QQQ', 'GLD']:
    if asset in partial_results:
        all_results['partial_correlations'][asset] = {
            k: {'r': round(v['r_partial'], 4), 'p': round(v['p_partial'], 6)}
            for k, v in partial_results[asset].items()
        }

# Summarize OOS regression
for asset in ['SPY', 'QQQ', 'GLD']:
    if asset in oos_results:
        all_results['oos_predictive_regression'][asset] = {
            k: {kk: round(vv, 6) for kk, vv in v.items()}
            for k, v in oos_results[asset].items()
        }

# VT overlay
for k, v in vt_results.items():
    all_results['vt_overlay'][k] = {
        'sharpe': round(v['sharpe'], 4),
        'ann_ret': round(v['ann_ret'] * 100, 2),
        'mdd': round(v['mdd'] * 100, 2),
    }

# Key findings summary
print("\nKEY FINDINGS:")
print("-" * 60)

# 1. Partial correlations
max_partial = 0
for asset in partial_results:
    for feat in partial_results[asset]:
        r = abs(partial_results[asset][feat]['r_partial'])
        if r > max_partial:
            max_partial = r
            max_partial_info = f"{asset}/{feat}"

print(f"1. Largest partial r|VIX: {max_partial:.4f} ({max_partial_info})")
print(f"   → SKEW features have {'weak' if max_partial < 0.05 else 'modest' if max_partial < 0.10 else 'notable'} "
      f"incremental information beyond VIX")

# 2. OOS regression
for asset in ['SPY', 'QQQ', 'GLD']:
    if asset in oos_results:
        r2_vix = oos_results[asset].get('VIX_only', {}).get('r2_oos', 0)
        r2_vr = oos_results[asset].get('VIX+ratio', {}).get('r2_oos', 0)
        print(f"2. OOS R² {asset}: VIX_only={r2_vix:.4f}, VIX+ratio={r2_vr:.4f}, "
              f"delta={r2_vr-r2_vix:+.4f}")

# 3. GARCH-X
print("3. GARCH-X results:")
for k, v in garchx_results.items():
    if 'exog_t' in v:
        print(f"   {k}: exog t={v['exog_t']:.3f}, p={v['exog_p']:.4f}")

# 4. VT overlay
base_sharpe = vt_results.get('12/VIX', {}).get('sharpe', 0)
overlay_sharpe = vt_results.get('12/VIX+ratio_z_adj', {}).get('sharpe', 0)
print(f"4. VT Overlay: 12/VIX Sharpe={base_sharpe:.3f} vs "
      f"12/VIX+ratio_z Sharpe={overlay_sharpe:.3f}, "
      f"delta={overlay_sharpe-base_sharpe:+.3f}")

# 5. Cross-OOS
n_ratio_wins = sum(1 for v in cross_oos.values() if v['winner'] == 'VIX+ratio')
n_periods = len(cross_oos)
print(f"5. Cross-OOS: VIX+ratio wins {n_ratio_wins}/{n_periods} periods")

# Final verdict
print("\n" + "=" * 72)
print("VERDICT:")
any_significant = any(
    abs(v.get('dm_t', 0)) > 1.96
    for v in cross_oos.values()
)
any_garchx_sig = any(
    v.get('exog_p', 1.0) < 0.05
    for v in garchx_results.values()
)

if any_significant or any_garchx_sig:
    print("  VIX/SKEW ratio shows SOME statistically significant signal")
    print("  but needs economic significance assessment")
else:
    print("  VIX/SKEW ratio does NOT significantly improve upon VIX alone")
    print("  → Confirms K184: SKEW is statistically detectable but economically negligible")
    print("  → VIX sufficiency holds for equity vol prediction")
print("=" * 72)

# Save results
output_path = 'experiments/k210_vix_skew_ratio_results.json'
with open(output_path, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
