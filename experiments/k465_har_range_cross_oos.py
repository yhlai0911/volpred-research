#!/usr/bin/env python3
"""
K465: HAR Log-Range Cross-OOS Validation (5 OOS Periods)

Background:
  K464: HAR log-range best model in 6/6 markets (DM p<0.001 vs AR(1))
  K460: Semivariance passed cross-OOS (4/5 periods)
  K459: VRP failed cross-OOS (0/5 periods)

  Must validate HAR log-range with 5-period cross-OOS (J9 protocol).

Design:
  5 OOS periods (same as K459/K460):
    1. 2015-2016 (low vol)
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2025 (post-COVID)

  For each period:
    IS: preceding 2000 trading days (~8 years)
    OOS: ~500 trading days (~2 years)

  Models:
    1. AR(1) log-range (quasi-SV baseline)
    2. HAR log-range (1d + 5d + 21d) — KEY MODEL
    3. GJR-GARCH(1,1) with Student-t
    4. AR(1) + VIX threshold (K464 threshold model)

  Metrics:
    - QLIKE with Parkinson proxy
    - MSE
    - DM test: HAR vs AR(1), HAR vs GJR, HAR vs threshold

  Assets: SPY (primary) + EWT (Taiwan validation)

  Judgment:
    ≥4/5 periods significant → Publication ready
    ≤2/5 periods → Period-specific (downgrade)

Data: yfinance, 2005-01-01 to present
Refs: Corsi (2009) J. Financial Econometrics, Alizadeh Brandt Diebold (2002) JFE,
      K464 results, K459/K460 cross-OOS framework
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K465: HAR Log-Range Cross-OOS Validation (5 OOS Periods)")
print("  J9 Protocol: Does HAR log-range advantage hold across all regimes?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
ASSETS = {
    'SPY': {'name': 'US Large Cap (primary)', 'start': '2005-01-01'},
    'EWT': {'name': 'Taiwan (validation)', 'start': '2005-01-01'},
}

OOS_PERIODS = [
    {"name": "2015-2016 (low vol)", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2025 (post-COVID)", "start": "2023-01-01", "end": "2025-12-31"},
]

IS_WINDOW = 2000  # trading days (~8 years)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
raw_data = {}
for ticker, info in ASSETS.items():
    raw = yf.download(ticker, start=info['start'], progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw_data[ticker] = raw
    print(f"  {ticker}: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")

# Also download VIX for threshold model
vix_raw = yf.download('^VIX', start='2005-01-01', progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
print(f"  VIX: {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")


def compute_features(df, vix_df=None):
    """Compute log-range, returns, Parkinson var, HAR components."""
    high = df['High'].values.astype(float).ravel()
    low = df['Low'].values.astype(float).ravel()
    close = df['Close'].values.astype(float).ravel()

    # Log range (quasi-SV state variable)
    ratio = high / low
    ratio = np.maximum(ratio, 1.0001)  # avoid log(1)=0
    log_range = np.log(ratio)

    # Parkinson variance proxy
    parkinson_var = log_range**2 / (4 * np.log(2))

    # Log returns in %
    ret = np.log(close[1:] / close[:-1]) * 100

    # Build DataFrame (drop first obs for return alignment)
    idx = df.index[1:]
    feat = pd.DataFrame({
        'log_range': log_range[1:],
        'parkinson_var': parkinson_var[1:],
        'return': ret,
        'abs_return': np.abs(ret),
    }, index=idx)

    # HAR components: 5d and 21d averages of log_range
    feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
    feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

    # VIX for threshold model
    if vix_df is not None:
        vix_close = vix_df['Close'].values.astype(float).ravel()
        vix_series = pd.Series(vix_close, index=vix_df.index)
        feat['vix'] = vix_series.reindex(idx)

    feat = feat.dropna()
    return feat


features = {}
for ticker in ASSETS:
    features[ticker] = compute_features(raw_data[ticker], vix_raw)
    print(f"  {ticker}: {len(features[ticker])} obs with all features")


# ============================================================
# 3. DIAGNOSTICS (per CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")


def data_diagnostics(feat, name):
    """Pre-estimation diagnostics."""
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
    }

    # ADF test
    adf_stat, adf_p, _, _, _, _ = adfuller(lr, maxlag=21)
    diag['adf_stat'] = float(adf_stat)
    diag['adf_p'] = float(adf_p)
    diag['is_stationary'] = adf_p < 0.05

    # Ljung-Box
    lb = acorr_ljungbox(lr, lags=[10], return_df=True)
    diag['ljung_box_p_10'] = float(lb['lb_pvalue'].values[0])
    diag['has_autocorrelation'] = float(lb['lb_pvalue'].values[0]) < 0.05

    # AR(1) persistence
    y = lr[1:]
    x = np.column_stack([np.ones(len(y)), lr[:-1]])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    diag['ar1_persistence'] = float(beta[1])

    print(f"  {name}: n={diag['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'}), "
          f"AR(1)={beta[1]:.3f}, LB p={diag['ljung_box_p_10']:.2e}")

    return diag


diagnostics = {}
for ticker in ASSETS:
    diagnostics[ticker] = data_diagnostics(features[ticker], ticker)


# ============================================================
# 4. MODEL FUNCTIONS
# ============================================================

def fit_ar1_log_range(lr_train, lr_test):
    """Model 1: Simple AR(1) on log-range."""
    y = lr_train.values
    n = len(y)

    # OLS: y_t = a0 + a1*y_{t-1}
    X = np.column_stack([np.ones(n - 1), y[:-1]])
    Y = y[1:]
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]

    # OOS: rolling 1-step forecast
    forecasts = []
    y_prev = y[-1]
    for t in range(len(lr_test)):
        fc = beta[0] + beta[1] * y_prev
        forecasts.append(fc)
        y_prev = lr_test.values[t]  # update with actual

    # Convert: Parkinson var = log_range^2 / (4*ln2)
    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts, {'alpha0': float(beta[0]), 'alpha1': float(beta[1]),
                           'persistence': float(beta[1])}


def fit_har_log_range(feat_train, feat_test):
    """Model 2: HAR log-range (1d + 5d + 21d).
    y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t} + e_t
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    train = feat_train[cols].dropna()
    test = feat_test[cols].dropna()

    Y = train['log_range'].values[1:]  # y_{t+1}
    X = train[cols].values[:-1]  # y_t, y_{5d,t}, y_{21d,t}
    X = np.column_stack([np.ones(len(Y)), X])

    beta = np.linalg.lstsq(X, Y, rcond=None)[0]

    # OOS: use actual values to form HAR components, forecast 1-step ahead
    forecasts = []
    for t in range(len(test)):
        x_t = test[cols].values[t]
        fc = beta[0] + beta[1:] @ x_t
        forecasts.append(fc)

    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts, {
        'b0': float(beta[0]), 'b1_daily': float(beta[1]),
        'b2_weekly': float(beta[2]), 'b3_monthly': float(beta[3])
    }


def fit_gjr_garch(returns_train, returns_test):
    """Model 3: GJR-GARCH(1,1) with Student-t.
    Returns variance in decimal (log-return)^2 units.
    """
    am = arch_model(returns_train, vol='GARCH', p=1, o=1, q=1, dist='t')
    res = am.fit(disp='off', show_warning=False)

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

    # GARCH gives variance in %^2 (since returns are in %)
    # Parkinson var is in (log-return decimal)^2
    # Convert: %^2 / 10000 = decimal^2
    var_forecasts = np.array(forecasts) / 10000.0

    params = {k: float(v) for k, v in res.params.items()}
    params['convergence'] = bool(res.convergence_flag == 0)
    return var_forecasts, params


def fit_threshold_ar_vix(feat_train, feat_test):
    """Model 4: Threshold AR(1) on log-range with VIX transition.
    Low regime:  y_t = a0_L + a1_L*y_{t-1} when VIX_{t-1} < c
    High regime: y_t = a0_H + a1_H*y_{t-1} when VIX_{t-1} >= c
    """
    y_train = feat_train['log_range'].values
    s_train = feat_train['vix'].values
    y_test = feat_test['log_range'].values
    s_test = feat_test['vix'].values

    n = len(y_train)
    Y = y_train[1:]
    X_lag = y_train[:-1]
    S = s_train[:-1]  # lagged transition

    # Grid search: 15th-85th percentile
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

        X_L = np.column_stack([np.ones(n_L), X_lag[mask_L]])
        beta_L = np.linalg.lstsq(X_L, Y[mask_L], rcond=None)[0]
        resid_L = Y[mask_L] - X_L @ beta_L

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

    # OOS forecasts
    forecasts = []
    y_prev = y_train[-1]
    for t in range(len(y_test)):
        s_val = s_train[-1] if t == 0 else s_test[t - 1]

        if s_val < best_c:
            fc = best_params_L[0] + best_params_L[1] * y_prev
        else:
            fc = best_params_H[0] + best_params_H[1] * y_prev

        forecasts.append(fc)
        y_prev = y_test[t]

    var_forecasts = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts, {
        'threshold_c': float(best_c),
        'persistence_L': float(best_params_L[1]),
        'persistence_H': float(best_params_H[1]),
    }


# ============================================================
# 5. EVALUATION FUNCTIONS
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast."""
    valid = (forecast > 0) & (actual > 0) & np.isfinite(forecast) & np.isfinite(actual)
    a = actual[valid]
    f = forecast[valid]
    return np.mean(np.log(f) + a / f)


def mse_loss(actual, forecast):
    """MSE loss."""
    valid = np.isfinite(forecast) & np.isfinite(actual)
    return np.mean((actual[valid] - forecast[valid])**2)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Positive t-stat = model 1 has LARGER loss."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max(h, 2)):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * (1 - k / max(h, 2)) * gamma_k

    se = np.sqrt(max(hac_var, 1e-20) / n)
    if se < 1e-12:
        return np.nan, np.nan

    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# 6. MAIN CROSS-OOS LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Running Cross-OOS Validation (5 periods × 2 assets × 4 models)")
print("=" * 70)

all_results = {}
t_start = time.time()

for ticker, info in ASSETS.items():
    feat = features[ticker]
    asset_results = {
        'diagnostics': diagnostics[ticker],
        'periods': [],
        'summary': {}
    }

    print(f"\n{'='*60}")
    print(f"  ASSET: {ticker} ({info['name']})")
    print(f"{'='*60}")

    har_wins_ar1 = 0
    har_wins_gjr = 0
    har_wins_threshold = 0

    for p_idx, period in enumerate(OOS_PERIODS):
        period_name = period['name']
        print(f"\n  --- Period {p_idx+1}/5: {period_name} ---")

        # Define OOS range
        oos_start = pd.Timestamp(period['start'])
        oos_end = pd.Timestamp(period['end'])

        # Find OOS indices
        oos_mask = (feat.index >= oos_start) & (feat.index <= oos_end)
        oos_dates = feat.index[oos_mask]

        if len(oos_dates) < 50:
            print(f"    SKIP: insufficient OOS data ({len(oos_dates)} obs)")
            asset_results['periods'].append({
                'period': period_name,
                'status': 'skipped',
                'reason': f'insufficient OOS data ({len(oos_dates)} obs)'
            })
            continue

        # Find IS range: IS_WINDOW days before OOS start
        all_before_oos = feat.index[feat.index < oos_start]
        if len(all_before_oos) < IS_WINDOW:
            print(f"    SKIP: insufficient IS data ({len(all_before_oos)} < {IS_WINDOW})")
            asset_results['periods'].append({
                'period': period_name,
                'status': 'skipped',
                'reason': f'insufficient IS data ({len(all_before_oos)} < {IS_WINDOW})'
            })
            continue

        is_start_idx = len(all_before_oos) - IS_WINDOW
        is_dates = all_before_oos[is_start_idx:]

        feat_train = feat.loc[is_dates]
        feat_test = feat.loc[oos_dates]

        n_is = len(feat_train)
        n_oos = len(feat_test)
        print(f"    IS: {feat_train.index[0].date()} to {feat_train.index[-1].date()} ({n_is} obs)")
        print(f"    OOS: {feat_test.index[0].date()} to {feat_test.index[-1].date()} ({n_oos} obs)")

        # Actual variance proxy (Parkinson)
        actual_var = feat_test['parkinson_var'].values

        period_result = {
            'period': period_name,
            'is_range': f"{feat_train.index[0].date()} to {feat_train.index[-1].date()}",
            'oos_range': f"{feat_test.index[0].date()} to {feat_test.index[-1].date()}",
            'n_is': n_is,
            'n_oos': n_oos,
            'models': {}
        }

        # ------ Model 1: AR(1) log-range ------
        try:
            var_ar1, params_ar1 = fit_ar1_log_range(
                feat_train['log_range'], feat_test['log_range'])
            qlike_ar1 = qlike(actual_var, var_ar1)
            mse_ar1 = mse_loss(actual_var, var_ar1)
            loss_ar1 = np.log(var_ar1) + actual_var / var_ar1  # per-obs QLIKE
            period_result['models']['ar1'] = {
                'qlike': float(qlike_ar1), 'mse': float(mse_ar1),
                'params': params_ar1
            }
            print(f"    AR(1):      QLIKE={qlike_ar1:.6f}")
        except Exception as e:
            print(f"    AR(1) FAILED: {e}")
            loss_ar1 = None
            period_result['models']['ar1'] = {'error': str(e)}

        # ------ Model 2: HAR log-range ------
        try:
            var_har, params_har = fit_har_log_range(feat_train, feat_test)
            # Align lengths (HAR may have fewer forecasts due to rolling window)
            n_har = len(var_har)
            actual_har = actual_var[-n_har:] if n_har < len(actual_var) else actual_var
            qlike_har = qlike(actual_har, var_har)
            mse_har = mse_loss(actual_har, var_har)
            loss_har = np.log(var_har) + actual_har / var_har
            period_result['models']['har'] = {
                'qlike': float(qlike_har), 'mse': float(mse_har),
                'params': params_har
            }
            print(f"    HAR:        QLIKE={qlike_har:.6f}")
        except Exception as e:
            print(f"    HAR FAILED: {e}")
            loss_har = None
            period_result['models']['har'] = {'error': str(e)}

        # ------ Model 3: GJR-GARCH ------
        try:
            var_gjr, params_gjr = fit_gjr_garch(
                feat_train['return'], feat_test['return'])
            qlike_gjr = qlike(actual_var, var_gjr)
            mse_gjr = mse_loss(actual_var, var_gjr)
            loss_gjr = np.log(var_gjr) + actual_var / var_gjr
            period_result['models']['gjr_garch'] = {
                'qlike': float(qlike_gjr), 'mse': float(mse_gjr),
                'params': params_gjr
            }
            print(f"    GJR-GARCH:  QLIKE={qlike_gjr:.6f}")
        except Exception as e:
            print(f"    GJR-GARCH FAILED: {e}")
            loss_gjr = None
            period_result['models']['gjr_garch'] = {'error': str(e)}

        # ------ Model 4: Threshold AR + VIX ------
        try:
            if 'vix' in feat_train.columns:
                var_thr, params_thr = fit_threshold_ar_vix(feat_train, feat_test)
                if var_thr is not None:
                    qlike_thr = qlike(actual_var, var_thr)
                    mse_thr = mse_loss(actual_var, var_thr)
                    loss_thr = np.log(var_thr) + actual_var / var_thr
                    period_result['models']['threshold_vix'] = {
                        'qlike': float(qlike_thr), 'mse': float(mse_thr),
                        'params': params_thr
                    }
                    print(f"    Threshold:  QLIKE={qlike_thr:.6f}")
                else:
                    loss_thr = None
                    period_result['models']['threshold_vix'] = params_thr
            else:
                loss_thr = None
                period_result['models']['threshold_vix'] = {'error': 'no VIX data'}
        except Exception as e:
            print(f"    Threshold FAILED: {e}")
            loss_thr = None
            period_result['models']['threshold_vix'] = {'error': str(e)}

        # ------ DM Tests ------
        dm_results = {}

        # HAR vs AR(1) — key test
        if loss_har is not None and loss_ar1 is not None:
            # Align lengths
            min_len = min(len(loss_ar1), len(loss_har))
            t_stat, p_val = dm_test(loss_ar1[-min_len:], loss_har[-min_len:])
            sig = p_val < 0.05 if not np.isnan(p_val) else False
            dm_results['har_vs_ar1'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig),
                'direction': 'HAR better' if t_stat > 0 else 'AR(1) better'
            }
            if sig and t_stat > 0:
                har_wins_ar1 += 1
            print(f"    DM(HAR vs AR1): t={t_stat:.3f}, p={p_val:.4f} {'***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'}")

        # HAR vs GJR-GARCH
        if loss_har is not None and loss_gjr is not None:
            min_len = min(len(loss_gjr), len(loss_har))
            t_stat, p_val = dm_test(loss_gjr[-min_len:], loss_har[-min_len:])
            sig = p_val < 0.05 if not np.isnan(p_val) else False
            dm_results['har_vs_gjr'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig),
                'direction': 'HAR better' if t_stat > 0 else 'GJR better'
            }
            if sig and t_stat > 0:
                har_wins_gjr += 1
            print(f"    DM(HAR vs GJR): t={t_stat:.3f}, p={p_val:.4f} {'***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'}")

        # HAR vs Threshold
        if loss_har is not None and loss_thr is not None:
            min_len = min(len(loss_thr), len(loss_har))
            t_stat, p_val = dm_test(loss_thr[-min_len:], loss_har[-min_len:])
            sig = p_val < 0.05 if not np.isnan(p_val) else False
            dm_results['har_vs_threshold'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig),
                'direction': 'HAR better' if t_stat > 0 else 'Threshold better'
            }
            if sig and t_stat > 0:
                har_wins_threshold += 1
            print(f"    DM(HAR vs THR): t={t_stat:.3f}, p={p_val:.4f} {'***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'}")

        period_result['dm_tests'] = dm_results
        asset_results['periods'].append(period_result)

    # ------ Summary for this asset ------
    n_valid_periods = len([p for p in asset_results['periods'] if p.get('status') != 'skipped'])
    asset_results['summary'] = {
        'n_valid_periods': n_valid_periods,
        'har_wins_vs_ar1': har_wins_ar1,
        'har_wins_vs_gjr': har_wins_gjr,
        'har_wins_vs_threshold': har_wins_threshold,
        'har_vs_ar1_rate': f"{har_wins_ar1}/{n_valid_periods}",
        'har_vs_gjr_rate': f"{har_wins_gjr}/{n_valid_periods}",
        'har_vs_threshold_rate': f"{har_wins_threshold}/{n_valid_periods}",
        'har_robust_vs_ar1': har_wins_ar1 >= 4,
        'har_robust_vs_gjr': har_wins_gjr >= 4,
    }

    # Average QLIKE across periods
    qlike_by_model = {'ar1': [], 'har': [], 'gjr_garch': [], 'threshold_vix': []}
    for p in asset_results['periods']:
        if p.get('status') == 'skipped':
            continue
        for model_name in qlike_by_model:
            if model_name in p.get('models', {}) and 'qlike' in p['models'][model_name]:
                qlike_by_model[model_name].append(p['models'][model_name]['qlike'])

    asset_results['summary']['avg_qlike'] = {
        m: float(np.mean(v)) if v else None for m, v in qlike_by_model.items()
    }

    print(f"\n  === {ticker} Summary ===")
    print(f"  HAR vs AR(1): {har_wins_ar1}/{n_valid_periods} periods significant")
    print(f"  HAR vs GJR:   {har_wins_gjr}/{n_valid_periods} periods significant")
    print(f"  HAR vs THR:   {har_wins_threshold}/{n_valid_periods} periods significant")
    print(f"  Robust (≥4/5)? HAR vs AR1: {'YES' if har_wins_ar1 >= 4 else 'NO'}, "
          f"HAR vs GJR: {'YES' if har_wins_gjr >= 4 else 'NO'}")
    if asset_results['summary']['avg_qlike']['har'] and asset_results['summary']['avg_qlike']['ar1']:
        improvement = (1 - asset_results['summary']['avg_qlike']['har'] /
                       asset_results['summary']['avg_qlike']['ar1']) * 100
        print(f"  Avg QLIKE improvement over AR(1): {improvement:.2f}%")

    all_results[ticker] = asset_results

elapsed = time.time() - t_start
print(f"\n  Total runtime: {elapsed:.1f}s")


# ============================================================
# 7. OVERALL JUDGMENT
# ============================================================
print("\n" + "=" * 70)
print("[5] OVERALL JUDGMENT")
print("=" * 70)

spy_res = all_results.get('SPY', {}).get('summary', {})
ewt_res = all_results.get('EWT', {}).get('summary', {})

spy_ar1_wins = spy_res.get('har_wins_vs_ar1', 0)
ewt_ar1_wins = ewt_res.get('har_wins_vs_ar1', 0)
spy_gjr_wins = spy_res.get('har_wins_vs_gjr', 0)
ewt_gjr_wins = ewt_res.get('har_wins_vs_gjr', 0)

judgment = ""
if spy_ar1_wins >= 4 and ewt_ar1_wins >= 4:
    judgment = "PUBLICATION READY — HAR log-range robust across both assets and all regimes"
elif spy_ar1_wins >= 4 or ewt_ar1_wins >= 4:
    judgment = "PARTIALLY ROBUST — HAR strong in one asset but not both"
elif spy_ar1_wins >= 3 or ewt_ar1_wins >= 3:
    judgment = "MARGINAL — HAR advantage exists but not fully robust"
else:
    judgment = "PERIOD-SPECIFIC — HAR advantage does not generalize (like VRP in K459)"

print(f"\n  SPY: HAR wins {spy_ar1_wins}/5 vs AR(1), {spy_gjr_wins}/5 vs GJR")
print(f"  EWT: HAR wins {ewt_ar1_wins}/5 vs AR(1), {ewt_gjr_wins}/5 vs GJR")
print(f"\n  JUDGMENT: {judgment}")


# ============================================================
# 8. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "k465",
    "title": "HAR Log-Range Cross-OOS Validation (5 Periods)",
    "background": "K464 found HAR log-range best in 6/6 markets. J9 protocol requires 5-period cross-OOS.",
    "references": [
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Alizadeh, Brandt & Diebold (2002) JFE — Range-based vol estimation",
        "K464 — HAR log-range discovery",
        "K459 — VRP cross-OOS failure (0/5)",
        "K460 — Semivariance cross-OOS success (4/5)"
    ],
    "method": "5-period cross-OOS with IS=2000d, QLIKE evaluation, DM test",
    "assets": list(ASSETS.keys()),
    "oos_periods": [p['name'] for p in OOS_PERIODS],
    "is_window": IS_WINDOW,
    "models": [
        "AR(1) log-range (baseline quasi-SV)",
        "HAR log-range (1d+5d+21d) — KEY MODEL",
        "GJR-GARCH(1,1) Student-t",
        "Threshold AR log-range (VIX transition)"
    ],
    "data_source": "yfinance (SPY, EWT, ^VIX)",
    "evaluation_proxy": "Parkinson variance (K441)",
    "judgment_criteria": "≥4/5 periods significant = robust; ≤2/5 = period-specific",
    "results": all_results,
    "judgment": judgment,
    "runtime_seconds": round(elapsed, 1),
    "timestamp": datetime.now(timezone.utc).isoformat()
}

output_path = "experiments/k465_har_range_cross_oos_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K465 COMPLETE")
print("=" * 70)
