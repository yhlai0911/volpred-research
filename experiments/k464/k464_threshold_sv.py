#!/usr/bin/env python3
"""
K464: Threshold Stochastic Volatility (THSV) for Asian Markets

Literature: Chen, Liu, So (2013) "Threshold variable selection of asymmetric
stochastic volatility models" Computational Statistics 28:2415-2447

Instead of full MCMC SV (too slow per K432), we use quasi-SV via log-range:
  log(range_t) = α₀ + α₁·log(range_{t-1}) + η_t   [AR(1) baseline]

Threshold version (2-regime):
  Low regime:  when s_{t-d} < c
  High regime: when s_{t-d} >= c

Models:
  1. Simple AR(1) on log-range (quasi-SV baseline)
  2. GJR-GARCH(1,1)
  3. Threshold AR on log-range with VIX transition variable
  4. Threshold AR on log-range with SPY return transition variable
  5. HAR-style log-range (1d + 5d + 21d components)

Assets: SPY, EWT, EWJ, EWH, EWY, EWS (Chen 2013 Asian markets + US baseline)
OOS: 2023-2025
Evaluation: QLIKE, MSE vs Parkinson proxy
Statistical test: DM test + Hansen (2000) threshold linearity test

Refs: K441 (Parkinson proxy), K432 (MCMC too slow)
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from multiprocessing import Pool, cpu_count

warnings.filterwarnings('ignore')

# ============================================================
# Data
# ============================================================
ASSETS = ['SPY', 'EWT', 'EWJ', 'EWH', 'EWY', 'EWS']
ASSET_NAMES = {
    'SPY': 'US (S&P 500)',
    'EWT': 'Taiwan',
    'EWJ': 'Japan',
    'EWH': 'Hong Kong',
    'EWY': 'South Korea',
    'EWS': 'Singapore'
}
OOS_START = '2023-01-01'
DATA_START = '2005-01-01'  # enough history for stable estimation


def download_data():
    """Download OHLC data for all assets + VIX."""
    tickers = ASSETS + ['^VIX']
    data = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=DATA_START, end='2025-12-31',
                           progress=False, auto_adjust=True)
            if len(df) > 500:
                data[ticker] = df
                print(f"  {ticker}: {len(df)} obs ({df.index[0].date()} to {df.index[-1].date()})")
            else:
                print(f"  {ticker}: insufficient data ({len(df)} obs)")
        except Exception as e:
            print(f"  {ticker}: download failed — {e}")
    return data


def compute_features(data):
    """Compute log-range, returns, Parkinson vol for each asset."""
    features = {}
    vix = data.get('^VIX')

    for asset in ASSETS:
        if asset not in data:
            continue
        df = data[asset].copy()

        # Parkinson range
        high = df['High'].values.astype(float).ravel()
        low = df['Low'].values.astype(float).ravel()
        close = df['Close'].values.astype(float).ravel()

        # Log range (quasi-SV state variable)
        ratio = high / low
        ratio = np.maximum(ratio, 1.0001)  # avoid log(1)=0 issues
        log_range = np.log(ratio)

        # Parkinson variance proxy (annualized)
        parkinson_var = log_range**2 / (4 * np.log(2))

        # Returns
        ret = np.log(close[1:] / close[:-1]) * 100

        # Build DataFrame
        idx = df.index[1:]  # drop first obs for return alignment
        feat = pd.DataFrame({
            'log_range': log_range[1:],
            'parkinson_var': parkinson_var[1:],
            'return': ret,
            'abs_return': np.abs(ret),
        }, index=idx)

        # HAR components: 5d and 21d averages of log_range
        feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
        feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

        # SPY return as transition variable (for all assets)
        if 'SPY' in data:
            spy_close = data['SPY']['Close'].values.astype(float).ravel()
            spy_ret = pd.Series(
                np.log(spy_close[1:] / spy_close[:-1]) * 100,
                index=data['SPY'].index[1:]
            )
            feat['spy_return'] = spy_ret.reindex(idx)

        # VIX as transition variable
        if vix is not None:
            vix_close = vix['Close'].values.astype(float).ravel()
            vix_series = pd.Series(vix_close, index=vix.index)
            feat['vix'] = vix_series.reindex(idx)

        feat = feat.dropna()
        features[asset] = feat

    return features


# ============================================================
# Models
# ============================================================

def fit_ar1_log_range(y_train, y_test, **kwargs):
    """Model 1: Simple AR(1) on log-range (quasi-SV baseline)."""
    n = len(y_train)
    y = y_train.values

    # OLS: y_t = a0 + a1*y_{t-1}
    X = np.column_stack([np.ones(n-1), y[:-1]])
    Y = y[1:]
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    resid = Y - X @ beta
    sigma2 = np.var(resid)

    # OOS forecast: h_{t+1} = a0 + a1*h_t
    forecasts = []
    y_prev = y[-1]
    for t in range(len(y_test)):
        fc = beta[0] + beta[1] * y_prev
        forecasts.append(fc)
        y_prev = y_test.values[t]  # update with actual

    # Convert log-range forecast to variance forecast
    # Parkinson: var = log(H/L)^2 / (4*ln2). log_range IS log(H/L).
    # So var = log_range^2 / (4*ln2). Do NOT exponentiate.
    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts, {
        'alpha0': float(beta[0]),
        'alpha1': float(beta[1]),
        'sigma2_eta': float(sigma2),
        'persistence': float(beta[1])
    }


def fit_gjr_garch(returns_train, returns_test, **kwargs):
    """Model 2: GJR-GARCH(1,1) with Student-t."""
    am = arch_model(returns_train, vol='GARCH', p=1, o=1, q=1, dist='t')
    res = am.fit(disp='off', show_warning=False)

    # OOS rolling forecast
    full = pd.concat([returns_train, returns_test])
    n_train = len(returns_train)
    n_test = len(returns_test)

    forecasts = []
    for t in range(n_test):
        end_idx = n_train + t
        am_t = arch_model(full.iloc[:end_idx], vol='GARCH', p=1, o=1, q=1, dist='t')
        res_t = am_t.fit(disp='off', show_warning=False,
                        starting_values=res.params.values)
        fc = res_t.forecast(horizon=1)
        forecasts.append(fc.variance.values[-1, 0])

    var_forecasts = np.array(forecasts) / (252 * 10000)  # annualized % -> daily decimal
    # Actually, arch returns daily variance in %^2, need to keep consistent
    # Parkinson var is in log-return^2 units (not %^2)
    # Convert: GARCH gives var in (%)^2, Parkinson in decimal^2
    # var_pct / 10000 = var_decimal
    var_forecasts_decimal = np.array(forecasts) / 10000.0

    params = {k: float(v) for k, v in res.params.items()}
    params['convergence'] = bool(res.convergence_flag == 0)
    params['persistence'] = float(params.get('alpha[1]', 0) +
                                   params.get('gamma[1]', 0) * 0.5 +
                                   params.get('beta[1]', 0))

    return var_forecasts_decimal, params


def fit_threshold_ar(y_train, y_test, s_train, s_test, **kwargs):
    """
    Model 3/4: Threshold AR(1) on log-range.

    Low regime:  y_t = a0_L + a1_L*y_{t-1} + e_t   when s_{t-1} < c
    High regime: y_t = a0_H + a1_H*y_{t-1} + e_t   when s_{t-1} >= c

    Grid search over percentiles of s for threshold c.
    """
    y = y_train.values
    s = s_train.values
    n = len(y)

    Y = y[1:]
    X_lag = y[:-1]
    S = s[:-1]  # lagged transition variable

    # Grid search for optimal threshold
    # Search 15th to 85th percentile (Hansen 2000 trimming)
    percentiles = np.arange(15, 86, 1)
    thresholds = np.percentile(S[~np.isnan(S)], percentiles)

    best_sse = np.inf
    best_c = None
    best_params_L = None
    best_params_H = None

    for c in thresholds:
        mask_L = S < c
        mask_H = S >= c

        n_L = mask_L.sum()
        n_H = mask_H.sum()

        if n_L < 30 or n_H < 30:
            continue

        # Low regime OLS
        X_L = np.column_stack([np.ones(n_L), X_lag[mask_L]])
        beta_L = np.linalg.lstsq(X_L, Y[mask_L], rcond=None)[0]
        resid_L = Y[mask_L] - X_L @ beta_L

        # High regime OLS
        X_H = np.column_stack([np.ones(n_H), X_lag[mask_H]])
        beta_H = np.linalg.lstsq(X_H, Y[mask_H], rcond=None)[0]
        resid_H = Y[mask_H] - X_H @ beta_H

        sse = np.sum(resid_L**2) + np.sum(resid_H**2)

        if sse < best_sse:
            best_sse = sse
            best_c = c
            best_params_L = beta_L
            best_params_H = beta_H

    if best_c is None:
        return None, {'error': 'No valid threshold found'}

    # Linear model SSE for Hansen test
    X_full = np.column_stack([np.ones(len(Y)), X_lag])
    beta_lin = np.linalg.lstsq(X_full, Y, rcond=None)[0]
    sse_lin = np.sum((Y - X_full @ beta_lin)**2)

    # Hansen (2000) F-statistic: F = (SSE_linear - SSE_threshold) / (SSE_threshold / (n-4))
    n_eff = len(Y)
    f_stat = (sse_lin - best_sse) / (best_sse / (n_eff - 4))

    # Bootstrap p-value for Hansen test (simplified: 500 reps)
    n_boot = 500
    f_boot = np.zeros(n_boot)
    for b in range(n_boot):
        # Under H0: no threshold, resample residuals
        resid_h0 = Y - X_full @ beta_lin
        resid_perm = resid_h0[np.random.permutation(len(resid_h0))]
        Y_boot = X_full @ beta_lin + resid_perm

        best_sse_b = np.inf
        for c in thresholds[::3]:  # coarser grid for speed
            mask_L = S < c
            mask_H = S >= c
            n_L = mask_L.sum()
            n_H = mask_H.sum()
            if n_L < 30 or n_H < 30:
                continue
            X_L = np.column_stack([np.ones(n_L), X_lag[mask_L]])
            beta_L_b = np.linalg.lstsq(X_L, Y_boot[mask_L], rcond=None)[0]
            resid_L_b = Y_boot[mask_L] - X_L @ beta_L_b
            X_H = np.column_stack([np.ones(n_H), X_lag[mask_H]])
            beta_H_b = np.linalg.lstsq(X_H, Y_boot[mask_H], rcond=None)[0]
            resid_H_b = Y_boot[mask_H] - X_H @ beta_H_b
            sse_b = np.sum(resid_L_b**2) + np.sum(resid_H_b**2)
            if sse_b < best_sse_b:
                best_sse_b = sse_b

        sse_lin_b = np.sum((Y_boot - X_full @ beta_lin)**2)
        f_boot[b] = (sse_lin_b - best_sse_b) / (best_sse_b / (n_eff - 4))

    hansen_p = np.mean(f_boot >= f_stat)

    # OOS forecasts
    forecasts = []
    y_prev = y[-1]
    for t in range(len(y_test)):
        s_val = s_test.values[t] if t == 0 else s_test.values[t-1]
        if t == 0:
            s_val = s[-1]  # use last in-sample transition var
        else:
            s_val = s_test.values[t-1]

        if s_val < best_c:
            fc = best_params_L[0] + best_params_L[1] * y_prev
        else:
            fc = best_params_H[0] + best_params_H[1] * y_prev

        forecasts.append(fc)
        y_prev = y_test.values[t]

    # Parkinson: var = log(H/L)^2 / (4*ln2). log_range IS log(H/L).
    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    # Regime proportions in OOS
    s_oos = s_test.values
    pct_high = np.mean(s_oos >= best_c) if len(s_oos) > 0 else np.nan

    return var_forecasts, {
        'threshold_c': float(best_c),
        'alpha0_L': float(best_params_L[0]),
        'alpha1_L': float(best_params_L[1]),
        'alpha0_H': float(best_params_H[0]),
        'alpha1_H': float(best_params_H[1]),
        'persistence_L': float(best_params_L[1]),
        'persistence_H': float(best_params_H[1]),
        'hansen_F': float(f_stat),
        'hansen_p': float(hansen_p),
        'pct_high_regime_oos': float(pct_high),
        'sse_linear': float(sse_lin),
        'sse_threshold': float(best_sse),
        'sse_reduction_pct': float((sse_lin - best_sse) / sse_lin * 100)
    }


def fit_har_log_range(feat_train, feat_test, **kwargs):
    """
    Model 5: HAR-style log-range.
    y_t = b0 + b1*y_{t-1} + b2*y_{t-1:t-5_avg} + b3*y_{t-1:t-21_avg} + e_t

    Inspired by Corsi (2009) HAR-RV, applied to log-range.
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    train = feat_train[cols].dropna()
    test = feat_test[cols].dropna()

    Y = train['log_range'].values[1:]
    X = train[cols].values[:-1]
    X = np.column_stack([np.ones(len(Y)), X])

    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    resid = Y - X @ beta
    sigma2 = np.var(resid)

    # OOS: use actual values to form HAR components, forecast 1-step
    forecasts = []
    # We need rolling 5d and 21d averages — use the precomputed ones
    for t in range(len(test)):
        x_t = test[cols].values[t]
        fc = beta[0] + beta[1:] @ x_t
        forecasts.append(fc)

    # HAR: y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t}
    # Parkinson: var = log(H/L)^2 / (4*ln2). log_range IS log(H/L).
    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts, {
        'b0': float(beta[0]),
        'b1_daily': float(beta[1]),
        'b2_weekly': float(beta[2]),
        'b3_monthly': float(beta[3]),
        'sigma2_eta': float(sigma2)
    }


# ============================================================
# Evaluation
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast."""
    valid = (forecast > 0) & (actual > 0) & np.isfinite(forecast) & np.isfinite(actual)
    a = actual[valid]
    f = forecast[valid]
    return np.mean(np.log(f) + a / f)


def mse(actual, forecast):
    """MSE loss."""
    valid = np.isfinite(forecast) & np.isfinite(actual)
    return np.mean((actual[valid] - forecast[valid])**2)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * (1 - k/h) * gamma_k

    se = np.sqrt(hac_var / n)
    if se < 1e-12:
        return np.nan, np.nan

    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return float(t_stat), float(p_val)


# ============================================================
# Diagnostics
# ============================================================

def data_diagnostics(feat, asset):
    """Pre-estimation diagnostics per CLAUDE.md rule 4."""
    lr = feat['log_range'].values
    ret = feat['return'].values

    diag = {
        'n_obs': len(feat),
        'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
        'log_range_mean': float(np.mean(lr)),
        'log_range_std': float(np.std(lr)),
        'log_range_skew': float(stats.skew(lr)),
        'log_range_kurt': float(stats.kurtosis(lr)),
        'return_mean': float(np.mean(ret)),
        'return_std': float(np.std(ret)),
        'return_skew': float(stats.skew(ret)),
        'return_kurt': float(stats.kurtosis(ret)),
    }

    # ADF test on log_range
    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_p, _, _, _, _ = adfuller(lr, maxlag=21)
    diag['adf_stat'] = float(adf_stat)
    diag['adf_p'] = float(adf_p)
    diag['is_stationary'] = adf_p < 0.05

    # Ljung-Box on log_range (autocorrelation check)
    from statsmodels.stats.diagnostic import acorr_ljungbox
    lb = acorr_ljungbox(lr, lags=[10], return_df=True)
    diag['ljung_box_stat_10'] = float(lb['lb_stat'].values[0])
    diag['ljung_box_p_10'] = float(lb['lb_pvalue'].values[0])
    diag['has_autocorrelation'] = float(lb['lb_pvalue'].values[0]) < 0.05

    # AR(1) coefficient of log_range (persistence check)
    y = lr[1:]
    x = np.column_stack([np.ones(len(y)), lr[:-1]])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    diag['ar1_coef'] = float(beta[1])

    return diag


# ============================================================
# Main experiment runner for one asset
# ============================================================

def run_asset(args):
    """Run all models for one asset. Designed for multiprocessing."""
    asset, features = args
    feat = features[asset]

    print(f"\n{'='*60}")
    print(f"  {asset} ({ASSET_NAMES[asset]})")
    print(f"{'='*60}")

    # Split in-sample / OOS
    oos_mask = feat.index >= OOS_START
    feat_train = feat[~oos_mask]
    feat_test = feat[oos_mask]

    n_train = len(feat_train)
    n_test = len(feat_test)
    print(f"  In-sample: {n_train} obs, OOS: {n_test} obs")

    if n_test < 50:
        print(f"  WARNING: insufficient OOS data, skipping")
        return asset, None

    # Diagnostics
    diag = data_diagnostics(feat_train, asset)
    print(f"  Log-range: mean={diag['log_range_mean']:.4f}, std={diag['log_range_std']:.4f}")
    print(f"  Log-range: skew={diag['log_range_skew']:.3f}, kurt={diag['log_range_kurt']:.3f}")
    print(f"  ADF: stat={diag['adf_stat']:.3f}, p={diag['adf_p']:.4f} ({'stationary' if diag['is_stationary'] else 'NON-STATIONARY'})")
    print(f"  AR(1) coef: {diag['ar1_coef']:.4f}")
    print(f"  Ljung-Box(10): p={diag['ljung_box_p_10']:.4f} ({'autocorrelated' if diag['has_autocorrelation'] else 'no AC'})")

    # Target: Parkinson variance (OOS)
    target = feat_test['parkinson_var'].values

    results = {'diagnostics': diag}
    model_forecasts = {}
    model_losses = {}

    # ---- Model 1: AR(1) log-range ----
    print(f"\n  [1] AR(1) log-range (quasi-SV baseline)...")
    try:
        fc1, params1 = fit_ar1_log_range(
            feat_train['log_range'], feat_test['log_range'])
        results['ar1_log_range'] = {
            'params': params1,
            'qlike': float(qlike(target, fc1)),
            'mse': float(mse(target, fc1))
        }
        model_forecasts['ar1'] = fc1
        print(f"    persistence={params1['persistence']:.4f}, QLIKE={results['ar1_log_range']['qlike']:.4f}")
    except Exception as e:
        print(f"    FAILED: {e}")
        results['ar1_log_range'] = {'error': str(e)}

    # ---- Model 2: GJR-GARCH ----
    print(f"  [2] GJR-GARCH(1,1)...")
    try:
        fc2, params2 = fit_gjr_garch(
            feat_train['return'], feat_test['return'])
        results['gjr_garch'] = {
            'params': params2,
            'qlike': float(qlike(target, fc2)),
            'mse': float(mse(target, fc2))
        }
        model_forecasts['gjr'] = fc2
        print(f"    persistence={params2.get('persistence', 'N/A'):.4f}, QLIKE={results['gjr_garch']['qlike']:.4f}")
    except Exception as e:
        print(f"    FAILED: {e}")
        results['gjr_garch'] = {'error': str(e)}

    # ---- Model 3: Threshold AR with VIX ----
    if 'vix' in feat.columns and feat['vix'].notna().sum() > 100:
        print(f"  [3] Threshold AR (VIX transition)...")
        try:
            fc3, params3 = fit_threshold_ar(
                feat_train['log_range'], feat_test['log_range'],
                feat_train['vix'], feat_test['vix'])
            if fc3 is not None:
                results['threshold_vix'] = {
                    'params': params3,
                    'qlike': float(qlike(target, fc3)),
                    'mse': float(mse(target, fc3))
                }
                model_forecasts['th_vix'] = fc3
                print(f"    threshold={params3['threshold_c']:.2f}, Hansen F={params3['hansen_F']:.2f}, p={params3['hansen_p']:.3f}")
                print(f"    persistence_L={params3['persistence_L']:.4f}, persistence_H={params3['persistence_H']:.4f}")
                print(f"    QLIKE={results['threshold_vix']['qlike']:.4f}")
            else:
                results['threshold_vix'] = params3
        except Exception as e:
            print(f"    FAILED: {e}")
            results['threshold_vix'] = {'error': str(e)}
    else:
        print(f"  [3] Threshold AR (VIX): skipped (no VIX data)")
        results['threshold_vix'] = {'error': 'no VIX data'}

    # ---- Model 4: Threshold AR with SPY return ----
    if 'spy_return' in feat.columns and feat['spy_return'].notna().sum() > 100:
        print(f"  [4] Threshold AR (SPY return transition)...")
        try:
            fc4, params4 = fit_threshold_ar(
                feat_train['log_range'], feat_test['log_range'],
                feat_train['spy_return'], feat_test['spy_return'])
            if fc4 is not None:
                results['threshold_spy'] = {
                    'params': params4,
                    'qlike': float(qlike(target, fc4)),
                    'mse': float(mse(target, fc4))
                }
                model_forecasts['th_spy'] = fc4
                print(f"    threshold={params4['threshold_c']:.2f}%, Hansen F={params4['hansen_F']:.2f}, p={params4['hansen_p']:.3f}")
                print(f"    persistence_L={params4['persistence_L']:.4f}, persistence_H={params4['persistence_H']:.4f}")
                print(f"    QLIKE={results['threshold_spy']['qlike']:.4f}")
            else:
                results['threshold_spy'] = params4
        except Exception as e:
            print(f"    FAILED: {e}")
            results['threshold_spy'] = {'error': str(e)}
    else:
        print(f"  [4] Threshold AR (SPY return): skipped (no SPY data)")
        results['threshold_spy'] = {'error': 'no SPY data'}

    # ---- Model 5: HAR log-range ----
    print(f"  [5] HAR log-range (1d + 5d + 21d)...")
    try:
        fc5, params5 = fit_har_log_range(feat_train, feat_test)
        # Align: HAR may have fewer forecasts due to NaN in 21d avg
        n_fc5 = len(fc5)
        target5 = feat_test['parkinson_var'].values[-n_fc5:]
        results['har_log_range'] = {
            'params': params5,
            'qlike': float(qlike(target5, fc5)),
            'mse': float(mse(target5, fc5)),
            'n_forecasts': n_fc5
        }
        model_forecasts['har'] = (fc5, target5)
        print(f"    b_daily={params5['b1_daily']:.4f}, b_weekly={params5['b2_weekly']:.4f}, b_monthly={params5['b3_monthly']:.4f}")
        print(f"    QLIKE={results['har_log_range']['qlike']:.4f}")
    except Exception as e:
        print(f"    FAILED: {e}")
        results['har_log_range'] = {'error': str(e)}

    # ---- DM tests ----
    print(f"\n  DM Tests (negative t → model 2 better):")
    dm_results = {}

    # Base losses for DM test
    if 'ar1' in model_forecasts:
        loss_ar1 = np.log(model_forecasts['ar1']) + target / model_forecasts['ar1']

        for name, key in [('gjr', 'gjr'), ('th_vix', 'th_vix'), ('th_spy', 'th_spy')]:
            if key in model_forecasts:
                fc = model_forecasts[key]
                loss_other = np.log(fc) + target / fc
                t_stat, p_val = dm_test(loss_ar1, loss_other)
                dm_results[f'ar1_vs_{name}'] = {'t': t_stat, 'p': p_val}
                sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
                print(f"    AR(1) vs {name}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")

        # AR1 vs HAR
        if 'har' in model_forecasts:
            fc_har, tgt_har = model_forecasts['har']
            n_har = len(fc_har)
            loss_ar1_har = np.log(model_forecasts['ar1'][-n_har:]) + tgt_har / model_forecasts['ar1'][-n_har:]
            loss_har = np.log(fc_har) + tgt_har / fc_har
            t_stat, p_val = dm_test(loss_ar1_har, loss_har)
            dm_results['ar1_vs_har'] = {'t': t_stat, 'p': p_val}
            sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
            print(f"    AR(1) vs HAR: t={t_stat:+.3f}, p={p_val:.4f} {sig}")

    # GJR vs threshold models
    if 'gjr' in model_forecasts:
        loss_gjr = np.log(model_forecasts['gjr']) + target / model_forecasts['gjr']
        for name, key in [('th_vix', 'th_vix'), ('th_spy', 'th_spy')]:
            if key in model_forecasts:
                fc = model_forecasts[key]
                loss_other = np.log(fc) + target / fc
                t_stat, p_val = dm_test(loss_gjr, loss_other)
                dm_results[f'gjr_vs_{name}'] = {'t': t_stat, 'p': p_val}
                sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
                print(f"    GJR vs {name}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")

    results['dm_tests'] = dm_results

    # ---- Summary: best model ----
    model_qlike = {}
    for mname in ['ar1_log_range', 'gjr_garch', 'threshold_vix', 'threshold_spy', 'har_log_range']:
        if mname in results and 'qlike' in results[mname]:
            model_qlike[mname] = results[mname]['qlike']

    if model_qlike:
        best = min(model_qlike, key=model_qlike.get)
        results['best_model'] = best
        results['best_qlike'] = model_qlike[best]
        print(f"\n  BEST: {best} (QLIKE={model_qlike[best]:.4f})")

    return asset, results


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K464: Threshold Stochastic Volatility (THSV) for Asian Markets")
    print("Ref: Chen, Liu, So (2013) Computational Statistics 28:2415-2447")
    print("=" * 70)

    # Download data
    print("\n[1/3] Downloading OHLC data...")
    data = download_data()

    if len(data) < 3:
        print("ERROR: insufficient data downloaded")
        return

    # Compute features
    print("\n[2/3] Computing features (log-range, Parkinson, HAR components)...")
    features = compute_features(data)

    # Run all assets
    print("\n[3/3] Running models for each asset...")

    all_results = {}
    for asset in ASSETS:
        if asset in features:
            _, result = run_asset((asset, features))
            if result is not None:
                all_results[asset] = result

    # ============================================================
    # Cross-asset summary
    # ============================================================
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    summary_table = []
    for asset in ASSETS:
        if asset not in all_results:
            continue
        r = all_results[asset]
        row = {'asset': asset, 'name': ASSET_NAMES[asset]}
        for mname in ['ar1_log_range', 'gjr_garch', 'threshold_vix', 'threshold_spy', 'har_log_range']:
            if mname in r and 'qlike' in r[mname]:
                row[mname] = r[mname]['qlike']
            else:
                row[mname] = np.nan
        summary_table.append(row)

    if summary_table:
        print(f"\n{'Asset':<12} {'AR(1)':<10} {'GJR':<10} {'TH-VIX':<10} {'TH-SPY':<10} {'HAR':<10} {'Best':<15}")
        print("-" * 77)
        for row in summary_table:
            ql = {k: row.get(k, np.nan) for k in ['ar1_log_range', 'gjr_garch', 'threshold_vix', 'threshold_spy', 'har_log_range']}
            valid = {k: v for k, v in ql.items() if np.isfinite(v)}
            best = min(valid, key=valid.get) if valid else 'N/A'
            print(f"{row['asset']:<12} "
                  f"{ql.get('ar1_log_range', np.nan):<10.4f} "
                  f"{ql.get('gjr_garch', np.nan):<10.4f} "
                  f"{ql.get('threshold_vix', np.nan):<10.4f} "
                  f"{ql.get('threshold_spy', np.nan):<10.4f} "
                  f"{ql.get('har_log_range', np.nan):<10.4f} "
                  f"{best:<15}")

    # Hansen test summary
    print(f"\nHansen Threshold Linearity Test (H0: no threshold):")
    print(f"{'Asset':<12} {'VIX F':<10} {'VIX p':<10} {'SPY F':<10} {'SPY p':<10}")
    print("-" * 52)
    for asset in ASSETS:
        if asset not in all_results:
            continue
        r = all_results[asset]
        vix_f = r.get('threshold_vix', {}).get('params', {}).get('hansen_F', np.nan)
        vix_p = r.get('threshold_vix', {}).get('params', {}).get('hansen_p', np.nan)
        spy_f = r.get('threshold_spy', {}).get('params', {}).get('hansen_F', np.nan)
        spy_p = r.get('threshold_spy', {}).get('params', {}).get('hansen_p', np.nan)
        print(f"{asset:<12} {vix_f:<10.2f} {vix_p:<10.3f} {spy_f:<10.2f} {spy_p:<10.3f}")

    # Regime characteristics
    print(f"\nThreshold Regime Characteristics:")
    print(f"{'Asset':<12} {'VIX c':<10} {'Pers_L':<10} {'Pers_H':<10} {'%High OOS':<12}")
    print("-" * 54)
    for asset in ASSETS:
        if asset not in all_results:
            continue
        r = all_results[asset]
        p = r.get('threshold_vix', {}).get('params', {})
        if 'threshold_c' in p:
            print(f"{asset:<12} {p['threshold_c']:<10.2f} "
                  f"{p['persistence_L']:<10.4f} {p['persistence_H']:<10.4f} "
                  f"{p['pct_high_regime_oos']*100:<12.1f}%")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.1f}s")

    # ============================================================
    # Conclusions
    # ============================================================
    conclusions = []

    # Count how many assets have significant threshold effect
    n_sig_vix = 0
    n_sig_spy = 0
    for asset in all_results:
        r = all_results[asset]
        if r.get('threshold_vix', {}).get('params', {}).get('hansen_p', 1.0) < 0.05:
            n_sig_vix += 1
        if r.get('threshold_spy', {}).get('params', {}).get('hansen_p', 1.0) < 0.05:
            n_sig_spy += 1

    conclusions.append(f"VIX threshold significant in {n_sig_vix}/{len(all_results)} assets")
    conclusions.append(f"SPY return threshold significant in {n_sig_spy}/{len(all_results)} assets")

    # Count best model wins
    best_counts = {}
    for asset in all_results:
        best = all_results[asset].get('best_model', 'unknown')
        best_counts[best] = best_counts.get(best, 0) + 1
    conclusions.append(f"Best model distribution: {best_counts}")

    # Check if threshold models ever beat GJR
    th_beats_gjr = 0
    for asset in all_results:
        r = all_results[asset]
        gjr_q = r.get('gjr_garch', {}).get('qlike', np.inf)
        th_vix_q = r.get('threshold_vix', {}).get('qlike', np.inf)
        th_spy_q = r.get('threshold_spy', {}).get('qlike', np.inf)
        if min(th_vix_q, th_spy_q) < gjr_q:
            th_beats_gjr += 1
    conclusions.append(f"Threshold quasi-SV beats GJR in {th_beats_gjr}/{len(all_results)} assets by QLIKE")

    print("\nCONCLUSIONS:")
    for c in conclusions:
        print(f"  - {c}")

    # ============================================================
    # Save results
    # ============================================================
    output = {
        'experiment_id': 'k464',
        'title': 'Threshold Stochastic Volatility (THSV) for Asian Markets',
        'reference': 'Chen, Liu, So (2013) Computational Statistics 28:2415-2447',
        'method': 'Quasi-SV via log-range with Hansen (2000) threshold test',
        'assets': ASSETS,
        'oos_period': f'{OOS_START} to 2025',
        'data_source': 'yfinance (ETF proxies for Asian markets)',
        'models': [
            'AR(1) log-range (quasi-SV baseline)',
            'GJR-GARCH(1,1) Student-t',
            'Threshold AR log-range (VIX transition)',
            'Threshold AR log-range (SPY return transition)',
            'HAR log-range (1d+5d+21d)'
        ],
        'evaluation_proxy': 'Parkinson variance (K441)',
        'results': {},
        'conclusions': conclusions,
        'limitations': [
            'ETF proxies, not local indices (tracking error)',
            'Quasi-SV via log-range, not full SV-MCMC (reduced form)',
            'Hansen bootstrap only 500 reps (for speed)',
            'Single OOS period (2023-2025)',
            'GJR-GARCH re-estimated each step (slow but proper)',
        ],
        'elapsed_seconds': elapsed,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    # Convert results (handle numpy)
    def convert(obj):
        if isinstance(obj, (np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, (np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(i) for i in obj]
        return obj

    output['results'] = convert(all_results)

    out_path = 'experiments/k464_threshold_sv_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {out_path}")


if __name__ == '__main__':
    main()
