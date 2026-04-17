#!/usr/bin/env python3
"""
K469: HAR Log-Range Cross-OOS with r² Proxy (Correcting K465 Tautology)

Background:
  K465: HAR log-range 10/10 cross-OOS (Parkinson proxy) — seemingly dominant
  K468: Revealed that Parkinson proxy naturally favors range-based models (tautology)
        When evaluated with r² proxy, GJR-GARCH beat HAR in SPY (QLIKE: 1.475 vs 1.903)
  → This experiment re-evaluates K465 using r² (close-to-close squared return) as proxy

Research Question:
  When r² is the evaluation proxy, does HAR log-range still beat GJR-GARCH?
  If HAR still wins ≥3/5 → HAR is genuinely superior
  If HAR wins 0-2/5 → K465 was largely a tautology artifact

Design:
  Same 5 OOS periods as K465:
    1. 2015-2016 (low vol)
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2025 (post-COVID)

  Models:
    1. GJR-GARCH(1,1) Student-t — evaluated with r²
    2. HAR log-range (1d+5d+21d) — converted to σ² scale, evaluated with r²
    3. EWMA (lambda=0.94)
    4. Rolling 21-day variance (std²)

  Key difference from K465:
    - proxy = r²_t = (close-to-close log return)² — NOT Parkinson
    - HAR forecasts converted: σ²_HAR = exp(log_range_hat)² / (4*ln2)
      but this is in Parkinson scale. Need scale calibration to match r² level.
    - Scale calibration: compute IS ratio = mean(r²) / mean(Parkinson_var),
      then σ²_HAR_scaled = σ²_HAR * ratio

  Evaluation:
    - QLIKE with r² proxy: QLIKE(σ², r²) = r²/σ² - log(r²/σ²) - 1
    - DM test: HAR vs GJR, each period
    - Compare rankings with K465 (Parkinson proxy)

Data: yfinance, 2005-01-01 to present
Refs: Corsi (2009) J Financial Econometrics, Alizadeh Brandt Diebold (2002) JFE,
      K465 — HAR cross-OOS with Parkinson proxy (10/10),
      K468 — Yang-Zhang proxy study revealing tautology
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
print("K469: HAR Log-Range Cross-OOS with r² Proxy")
print("  Correcting K465 tautology — does HAR still win with r² evaluation?")
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


# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")


def compute_features(df):
    """Compute log-range, returns, r², Parkinson var, HAR components."""
    high = df['High'].values.astype(float).ravel()
    low = df['Low'].values.astype(float).ravel()
    close = df['Close'].values.astype(float).ravel()

    # Log range
    ratio = high / low
    ratio = np.maximum(ratio, 1.0001)
    log_range = np.log(ratio)

    # Parkinson variance
    parkinson_var = log_range**2 / (4 * np.log(2))

    # Log returns (decimal, NOT percentage — to match r² scale)
    ret_decimal = np.log(close[1:] / close[:-1])
    ret_pct = ret_decimal * 100  # for GARCH estimation (arch expects %)

    # r² = squared return (decimal scale) — our evaluation proxy
    r_squared = ret_decimal**2

    # Build DataFrame (drop first obs for return alignment)
    idx = df.index[1:]
    feat = pd.DataFrame({
        'log_range': log_range[1:],
        'parkinson_var': parkinson_var[1:],
        'r_squared': r_squared,
        'return_pct': ret_pct,
        'return_decimal': ret_decimal,
    }, index=idx)

    # HAR components
    feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
    feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

    # EWMA variance (lambda=0.94, decimal scale)
    ewma_var = np.zeros(len(ret_decimal))
    ewma_var[0] = ret_decimal[0]**2
    for i in range(1, len(ret_decimal)):
        ewma_var[i] = 0.94 * ewma_var[i-1] + 0.06 * ret_decimal[i]**2
    feat['ewma_var'] = ewma_var

    # Rolling 21-day variance (decimal scale)
    feat['rolling_21d_var'] = feat['return_decimal'].rolling(21).var()

    feat = feat.dropna()
    return feat


features = {}
for ticker in ASSETS:
    features[ticker] = compute_features(raw_data[ticker])
    print(f"  {ticker}: {len(features[ticker])} obs with all features")


# ============================================================
# 3. DIAGNOSTICS
# ============================================================
print("\n[3] Data diagnostics...")


def data_diagnostics(feat, name):
    """Pre-estimation diagnostics."""
    lr = feat['log_range'].values
    r2 = feat['r_squared'].values
    pk = feat['parkinson_var'].values

    diag = {
        'n_obs': len(feat),
        'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
        'log_range_mean': float(np.mean(lr)),
        'log_range_std': float(np.std(lr)),
        'r_squared_mean': float(np.mean(r2)),
        'r_squared_std': float(np.std(r2)),
        'parkinson_var_mean': float(np.mean(pk)),
        'r2_over_parkinson_ratio': float(np.mean(r2) / np.mean(pk)),
    }

    # ADF test on log_range
    adf_stat, adf_p, _, _, _, _ = adfuller(lr, maxlag=21)
    diag['adf_stat'] = float(adf_stat)
    diag['adf_p'] = float(adf_p)
    diag['is_stationary'] = bool(adf_p < 0.05)

    # Correlation between proxies
    diag['corr_r2_parkinson'] = float(np.corrcoef(r2, pk)[0, 1])

    # Scale ratio: how much larger r² is vs Parkinson
    diag['scale_note'] = (
        f"r² is {diag['r2_over_parkinson_ratio']:.2f}x Parkinson mean. "
        "HAR forecasts (Parkinson scale) need this scaling to match r² level."
    )

    print(f"  {name}: n={diag['n_obs']}, r²/Parkinson ratio={diag['r2_over_parkinson_ratio']:.2f}, "
          f"corr(r²,Parkinson)={diag['corr_r2_parkinson']:.3f}")

    return diag


diagnostics = {}
for ticker in ASSETS:
    diagnostics[ticker] = data_diagnostics(features[ticker], ticker)


# ============================================================
# 4. MODEL FUNCTIONS
# ============================================================

def fit_har_log_range(feat_train, feat_test):
    """HAR log-range (1d + 5d + 21d).
    Returns variance forecasts in PARKINSON scale (needs scaling for r² eval).
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    train = feat_train[cols].dropna()
    test = feat_test[cols].dropna()

    Y = train['log_range'].values[1:]
    X = train[cols].values[:-1]
    X = np.column_stack([np.ones(len(Y)), X])

    beta = np.linalg.lstsq(X, Y, rcond=None)[0]

    # OOS forecasts
    forecasts = []
    for t in range(len(test)):
        x_t = test[cols].values[t]
        fc = beta[0] + beta[1:] @ x_t
        forecasts.append(fc)

    # Convert log-range forecast to Parkinson variance
    var_forecasts_parkinson = np.array(forecasts)**2 / (4 * np.log(2))

    return var_forecasts_parkinson, {
        'b0': float(beta[0]), 'b1_daily': float(beta[1]),
        'b2_weekly': float(beta[2]), 'b3_monthly': float(beta[3])
    }, len(test)


def fit_gjr_garch(returns_pct_train, returns_pct_test):
    """GJR-GARCH(1,1) Student-t.
    Returns variance in DECIMAL scale (not %).
    """
    am = arch_model(returns_pct_train, vol='GARCH', p=1, o=1, q=1, dist='t')
    res = am.fit(disp='off', show_warning=False)

    full = pd.concat([returns_pct_train, returns_pct_test])
    n_train = len(returns_pct_train)
    n_test = len(returns_pct_test)

    forecasts = []
    for t in range(n_test):
        end_idx = n_train + t
        am_t = arch_model(full.iloc[:end_idx], vol='GARCH', p=1, o=1, q=1, dist='t')
        res_t = am_t.fit(disp='off', show_warning=False,
                         starting_values=res.params.values)
        fc = res_t.forecast(horizon=1)
        forecasts.append(fc.variance.values[-1, 0])

    # GARCH variance is in %² → convert to decimal²
    var_forecasts = np.array(forecasts) / 10000.0

    params = {k: float(v) for k, v in res.params.items()}
    params['convergence'] = bool(res.convergence_flag == 0)
    return var_forecasts, params


def fit_ewma(feat_train, feat_test, lam=0.94):
    """EWMA (lambda=0.94) variance forecast.
    Returns variance in decimal scale.
    """
    # Initialize with IS EWMA
    ret_train = feat_train['return_decimal'].values
    ewma = ret_train[0]**2
    for i in range(1, len(ret_train)):
        ewma = lam * ewma + (1 - lam) * ret_train[i]**2

    # OOS: 1-step ahead forecast = current EWMA value
    ret_test = feat_test['return_decimal'].values
    forecasts = []
    for t in range(len(ret_test)):
        forecasts.append(ewma)  # forecast for next day
        ewma = lam * ewma + (1 - lam) * ret_test[t]**2

    return np.array(forecasts), {'lambda': lam}


def fit_rolling_var(feat_train, feat_test, window=21):
    """Rolling 21-day variance.
    Returns variance in decimal scale.
    """
    ret_all = pd.concat([feat_train['return_decimal'], feat_test['return_decimal']])
    n_train = len(feat_train)

    forecasts = []
    for t in range(len(feat_test)):
        end_idx = n_train + t
        start_idx = max(0, end_idx - window)
        recent = ret_all.iloc[start_idx:end_idx].values
        forecasts.append(np.var(recent, ddof=1))

    return np.array(forecasts), {'window': window}


# ============================================================
# 5. EVALUATION FUNCTIONS
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast.
    Lower is better. actual = r², forecast = model σ².
    """
    valid = (forecast > 0) & (actual > 0) & np.isfinite(forecast) & np.isfinite(actual)
    a = actual[valid]
    f = forecast[valid]
    return float(np.mean(np.log(f) + a / f))


def qlike_losses(actual, forecast):
    """Per-observation QLIKE losses (for DM test)."""
    valid = (forecast > 0) & (actual > 0) & np.isfinite(forecast) & np.isfinite(actual)
    a = actual[valid]
    f = forecast[valid]
    return np.log(f) + a / f


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Positive t-stat = model 1 has LARGER loss (model 2 better)."""
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
print("[4] Running Cross-OOS Validation with r² Proxy")
print("    (2 assets × 4 models × 5 periods)")
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

    har_wins_gjr = 0
    har_wins_ewma = 0
    har_wins_rolling = 0
    gjr_wins_ewma = 0
    gjr_wins_rolling = 0

    for p_idx, period in enumerate(OOS_PERIODS):
        period_name = period['name']
        print(f"\n  --- Period {p_idx+1}/5: {period_name} ---")

        oos_start = pd.Timestamp(period['start'])
        oos_end = pd.Timestamp(period['end'])

        oos_mask = (feat.index >= oos_start) & (feat.index <= oos_end)
        oos_dates = feat.index[oos_mask]

        if len(oos_dates) < 50:
            print(f"    SKIP: insufficient OOS data ({len(oos_dates)} obs)")
            asset_results['periods'].append({
                'period': period_name, 'status': 'skipped',
                'reason': f'insufficient OOS data ({len(oos_dates)} obs)'
            })
            continue

        all_before_oos = feat.index[feat.index < oos_start]
        if len(all_before_oos) < IS_WINDOW:
            print(f"    SKIP: insufficient IS data ({len(all_before_oos)} < {IS_WINDOW})")
            asset_results['periods'].append({
                'period': period_name, 'status': 'skipped',
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

        # ---- Actual proxy: r² (close-to-close squared return, decimal) ----
        actual_r2 = feat_test['r_squared'].values

        # Also compute Parkinson for comparison
        actual_parkinson = feat_test['parkinson_var'].values

        # Scale calibration factor: IS mean(r²) / mean(Parkinson)
        is_scale_ratio = np.mean(feat_train['r_squared'].values) / np.mean(feat_train['parkinson_var'].values)
        print(f"    IS r²/Parkinson ratio: {is_scale_ratio:.3f}")

        period_result = {
            'period': period_name,
            'is_range': f"{feat_train.index[0].date()} to {feat_train.index[-1].date()}",
            'oos_range': f"{feat_test.index[0].date()} to {feat_test.index[-1].date()}",
            'n_is': n_is,
            'n_oos': n_oos,
            'is_scale_ratio': float(is_scale_ratio),
            'models': {},
            'ranking_r2': [],
            'ranking_parkinson': [],
        }

        # Storage for losses (for DM tests)
        model_vars = {}
        model_losses_r2 = {}
        model_losses_parkinson = {}

        # ------ Model 1: GJR-GARCH ------
        try:
            var_gjr, params_gjr = fit_gjr_garch(
                feat_train['return_pct'], feat_test['return_pct'])

            q_r2 = qlike(actual_r2, var_gjr)
            q_pk = qlike(actual_parkinson, var_gjr)
            loss_r2 = qlike_losses(actual_r2, var_gjr)
            loss_pk = qlike_losses(actual_parkinson, var_gjr)

            model_vars['gjr_garch'] = var_gjr
            model_losses_r2['gjr_garch'] = loss_r2
            model_losses_parkinson['gjr_garch'] = loss_pk

            period_result['models']['gjr_garch'] = {
                'qlike_r2': q_r2, 'qlike_parkinson': q_pk,
                'params': params_gjr
            }
            print(f"    GJR-GARCH:  QLIKE(r²)={q_r2:.6f}  QLIKE(Park)={q_pk:.6f}")
        except Exception as e:
            print(f"    GJR-GARCH FAILED: {e}")
            period_result['models']['gjr_garch'] = {'error': str(e)}

        # ------ Model 2: HAR log-range (with scale calibration) ------
        try:
            var_har_parkinson, params_har, n_har = fit_har_log_range(feat_train, feat_test)

            # Scale HAR forecasts from Parkinson scale to r² scale
            var_har_r2_scaled = var_har_parkinson * is_scale_ratio

            # Align actual values if HAR has fewer forecasts
            actual_r2_har = actual_r2[-n_har:] if n_har < len(actual_r2) else actual_r2[:n_har]
            actual_pk_har = actual_parkinson[-n_har:] if n_har < len(actual_parkinson) else actual_parkinson[:n_har]

            # Evaluate with r² proxy using SCALED forecasts
            q_r2 = qlike(actual_r2_har, var_har_r2_scaled)
            # Also evaluate with Parkinson using ORIGINAL (unscaled) forecasts
            q_pk = qlike(actual_pk_har, var_har_parkinson)
            loss_r2 = qlike_losses(actual_r2_har, var_har_r2_scaled)
            loss_pk = qlike_losses(actual_pk_har, var_har_parkinson)

            model_vars['har'] = var_har_r2_scaled
            model_losses_r2['har'] = loss_r2
            model_losses_parkinson['har'] = loss_pk

            period_result['models']['har'] = {
                'qlike_r2': q_r2, 'qlike_parkinson': q_pk,
                'scale_ratio_applied': float(is_scale_ratio),
                'params': params_har
            }
            print(f"    HAR:        QLIKE(r²)={q_r2:.6f}  QLIKE(Park)={q_pk:.6f}  [scale={is_scale_ratio:.3f}]")
        except Exception as e:
            print(f"    HAR FAILED: {e}")
            period_result['models']['har'] = {'error': str(e)}

        # ------ Model 3: EWMA ------
        try:
            var_ewma, params_ewma = fit_ewma(feat_train, feat_test)

            q_r2 = qlike(actual_r2, var_ewma)
            q_pk = qlike(actual_parkinson, var_ewma)
            loss_r2 = qlike_losses(actual_r2, var_ewma)
            loss_pk = qlike_losses(actual_parkinson, var_ewma)

            model_vars['ewma'] = var_ewma
            model_losses_r2['ewma'] = loss_r2
            model_losses_parkinson['ewma'] = loss_pk

            period_result['models']['ewma'] = {
                'qlike_r2': q_r2, 'qlike_parkinson': q_pk,
                'params': params_ewma
            }
            print(f"    EWMA:       QLIKE(r²)={q_r2:.6f}  QLIKE(Park)={q_pk:.6f}")
        except Exception as e:
            print(f"    EWMA FAILED: {e}")
            period_result['models']['ewma'] = {'error': str(e)}

        # ------ Model 4: Rolling 21-day variance ------
        try:
            var_roll, params_roll = fit_rolling_var(feat_train, feat_test)

            q_r2 = qlike(actual_r2, var_roll)
            q_pk = qlike(actual_parkinson, var_roll)
            loss_r2 = qlike_losses(actual_r2, var_roll)
            loss_pk = qlike_losses(actual_parkinson, var_roll)

            model_vars['rolling_21d'] = var_roll
            model_losses_r2['rolling_21d'] = loss_r2
            model_losses_parkinson['rolling_21d'] = loss_pk

            period_result['models']['rolling_21d'] = {
                'qlike_r2': q_r2, 'qlike_parkinson': q_pk,
                'params': params_roll
            }
            print(f"    Rolling21:  QLIKE(r²)={q_r2:.6f}  QLIKE(Park)={q_pk:.6f}")
        except Exception as e:
            print(f"    Rolling21 FAILED: {e}")
            period_result['models']['rolling_21d'] = {'error': str(e)}

        # ------ Rankings ------
        # Rank by r² proxy QLIKE
        r2_scores = {}
        pk_scores = {}
        for m in ['gjr_garch', 'har', 'ewma', 'rolling_21d']:
            if m in period_result['models'] and 'qlike_r2' in period_result['models'][m]:
                r2_scores[m] = period_result['models'][m]['qlike_r2']
            if m in period_result['models'] and 'qlike_parkinson' in period_result['models'][m]:
                pk_scores[m] = period_result['models'][m]['qlike_parkinson']

        if r2_scores:
            period_result['ranking_r2'] = sorted(r2_scores.items(), key=lambda x: x[1])
            print(f"    Ranking (r²):       {' > '.join([f'{m}({v:.4f})' for m, v in period_result['ranking_r2']])}")
        if pk_scores:
            period_result['ranking_parkinson'] = sorted(pk_scores.items(), key=lambda x: x[1])
            print(f"    Ranking (Parkinson): {' > '.join([f'{m}({v:.4f})' for m, v in period_result['ranking_parkinson']])}")

        # ------ DM Tests (using r² proxy losses) ------
        dm_results = {}

        # HAR vs GJR — THE KEY TEST
        if 'har' in model_losses_r2 and 'gjr_garch' in model_losses_r2:
            l_gjr = model_losses_r2['gjr_garch']
            l_har = model_losses_r2['har']
            min_len = min(len(l_gjr), len(l_har))
            t_stat, p_val = dm_test(l_gjr[-min_len:], l_har[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'HAR better' if t_stat > 0 else 'GJR better'
            dm_results['har_vs_gjr_r2'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            if sig and t_stat > 0:
                har_wins_gjr += 1
            stars = '***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'
            print(f"    DM(HAR vs GJR, r²): t={t_stat:.3f}, p={p_val:.4f} {stars} [{direction}]")

        # HAR vs EWMA
        if 'har' in model_losses_r2 and 'ewma' in model_losses_r2:
            l_ewma = model_losses_r2['ewma']
            l_har = model_losses_r2['har']
            min_len = min(len(l_ewma), len(l_har))
            t_stat, p_val = dm_test(l_ewma[-min_len:], l_har[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'HAR better' if t_stat > 0 else 'EWMA better'
            dm_results['har_vs_ewma_r2'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            if sig and t_stat > 0:
                har_wins_ewma += 1
            stars = '***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'
            print(f"    DM(HAR vs EWMA, r²): t={t_stat:.3f}, p={p_val:.4f} {stars} [{direction}]")

        # HAR vs Rolling
        if 'har' in model_losses_r2 and 'rolling_21d' in model_losses_r2:
            l_roll = model_losses_r2['rolling_21d']
            l_har = model_losses_r2['har']
            min_len = min(len(l_roll), len(l_har))
            t_stat, p_val = dm_test(l_roll[-min_len:], l_har[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'HAR better' if t_stat > 0 else 'Rolling better'
            dm_results['har_vs_rolling_r2'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            if sig and t_stat > 0:
                har_wins_rolling += 1

        # GJR vs EWMA
        if 'gjr_garch' in model_losses_r2 and 'ewma' in model_losses_r2:
            l_gjr = model_losses_r2['gjr_garch']
            l_ewma = model_losses_r2['ewma']
            min_len = min(len(l_gjr), len(l_ewma))
            t_stat, p_val = dm_test(l_ewma[-min_len:], l_gjr[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'GJR better' if t_stat > 0 else 'EWMA better'
            dm_results['gjr_vs_ewma_r2'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            if sig and t_stat > 0:
                gjr_wins_ewma += 1

        # GJR vs Rolling
        if 'gjr_garch' in model_losses_r2 and 'rolling_21d' in model_losses_r2:
            l_gjr = model_losses_r2['gjr_garch']
            l_roll = model_losses_r2['rolling_21d']
            min_len = min(len(l_gjr), len(l_roll))
            t_stat, p_val = dm_test(l_roll[-min_len:], l_gjr[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'GJR better' if t_stat > 0 else 'Rolling better'
            dm_results['gjr_vs_rolling_r2'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            if sig and t_stat > 0:
                gjr_wins_rolling += 1

        # Also DM test with Parkinson proxy for comparison
        if 'har' in model_losses_parkinson and 'gjr_garch' in model_losses_parkinson:
            l_gjr = model_losses_parkinson['gjr_garch']
            l_har = model_losses_parkinson['har']
            min_len = min(len(l_gjr), len(l_har))
            t_stat, p_val = dm_test(l_gjr[-min_len:], l_har[-min_len:])
            sig = (p_val < 0.05) if not np.isnan(p_val) else False
            direction = 'HAR better' if t_stat > 0 else 'GJR better'
            dm_results['har_vs_gjr_parkinson'] = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant': bool(sig), 'direction': direction
            }
            stars = '***' if sig and p_val < 0.001 else '**' if sig and p_val < 0.01 else '*' if sig else 'NS'
            print(f"    DM(HAR vs GJR, Parkinson): t={t_stat:.3f}, p={p_val:.4f} {stars} [{direction}] (K465 comparison)")

        period_result['dm_tests'] = dm_results

        # Convert ranking tuples to serializable format
        period_result['ranking_r2'] = [(m, float(v)) for m, v in period_result['ranking_r2']] if period_result['ranking_r2'] else []
        period_result['ranking_parkinson'] = [(m, float(v)) for m, v in period_result['ranking_parkinson']] if period_result['ranking_parkinson'] else []

        asset_results['periods'].append(period_result)

    # ------ Summary for this asset ------
    n_valid = len([p for p in asset_results['periods'] if p.get('status') != 'skipped'])
    asset_results['summary'] = {
        'n_valid_periods': n_valid,
        'har_wins_vs_gjr_r2': har_wins_gjr,
        'har_wins_vs_ewma_r2': har_wins_ewma,
        'har_wins_vs_rolling_r2': har_wins_rolling,
        'gjr_wins_vs_ewma_r2': gjr_wins_ewma,
        'gjr_wins_vs_rolling_r2': gjr_wins_rolling,
        'har_vs_gjr_r2_rate': f"{har_wins_gjr}/{n_valid}",
        'gjr_vs_ewma_r2_rate': f"{gjr_wins_ewma}/{n_valid}",
        'har_robust_vs_gjr_r2': har_wins_gjr >= 3,  # ≥3/5 = still effective
    }

    # Average QLIKE across periods
    qlike_by_model_r2 = {'gjr_garch': [], 'har': [], 'ewma': [], 'rolling_21d': []}
    qlike_by_model_pk = {'gjr_garch': [], 'har': [], 'ewma': [], 'rolling_21d': []}
    for p in asset_results['periods']:
        if p.get('status') == 'skipped':
            continue
        for m in qlike_by_model_r2:
            if m in p.get('models', {}) and 'qlike_r2' in p['models'][m]:
                qlike_by_model_r2[m].append(p['models'][m]['qlike_r2'])
            if m in p.get('models', {}) and 'qlike_parkinson' in p['models'][m]:
                qlike_by_model_pk[m].append(p['models'][m]['qlike_parkinson'])

    asset_results['summary']['avg_qlike_r2'] = {
        m: float(np.mean(v)) if v else None for m, v in qlike_by_model_r2.items()
    }
    asset_results['summary']['avg_qlike_parkinson'] = {
        m: float(np.mean(v)) if v else None for m, v in qlike_by_model_pk.items()
    }

    # Count ranking positions
    har_rank_r2 = []
    gjr_rank_r2 = []
    har_rank_pk = []
    gjr_rank_pk = []
    for p in asset_results['periods']:
        if p.get('status') == 'skipped':
            continue
        if p.get('ranking_r2'):
            models_r2 = [m for m, _ in p['ranking_r2']]
            if 'har' in models_r2:
                har_rank_r2.append(models_r2.index('har') + 1)
            if 'gjr_garch' in models_r2:
                gjr_rank_r2.append(models_r2.index('gjr_garch') + 1)
        if p.get('ranking_parkinson'):
            models_pk = [m for m, _ in p['ranking_parkinson']]
            if 'har' in models_pk:
                har_rank_pk.append(models_pk.index('har') + 1)
            if 'gjr_garch' in models_pk:
                gjr_rank_pk.append(models_pk.index('gjr_garch') + 1)

    asset_results['summary']['avg_rank'] = {
        'har_r2': float(np.mean(har_rank_r2)) if har_rank_r2 else None,
        'gjr_r2': float(np.mean(gjr_rank_r2)) if gjr_rank_r2 else None,
        'har_parkinson': float(np.mean(har_rank_pk)) if har_rank_pk else None,
        'gjr_parkinson': float(np.mean(gjr_rank_pk)) if gjr_rank_pk else None,
    }

    print(f"\n  === {ticker} Summary ===")
    print(f"  HAR wins vs GJR (r² proxy): {har_wins_gjr}/{n_valid}")
    print(f"  HAR wins vs EWMA (r² proxy): {har_wins_ewma}/{n_valid}")
    print(f"  GJR wins vs EWMA (r² proxy): {gjr_wins_ewma}/{n_valid}")
    print(f"  Avg rank (r²):       HAR={asset_results['summary']['avg_rank']['har_r2']:.1f}  "
          f"GJR={asset_results['summary']['avg_rank']['gjr_r2']:.1f}")
    print(f"  Avg rank (Parkinson): HAR={asset_results['summary']['avg_rank']['har_parkinson']:.1f}  "
          f"GJR={asset_results['summary']['avg_rank']['gjr_parkinson']:.1f}")

    all_results[ticker] = asset_results

elapsed = time.time() - t_start
print(f"\n  Total runtime: {elapsed:.1f}s")


# ============================================================
# 7. OVERALL JUDGMENT
# ============================================================
print("\n" + "=" * 70)
print("[5] OVERALL JUDGMENT — Tautology Test")
print("=" * 70)

spy_res = all_results.get('SPY', {}).get('summary', {})
ewt_res = all_results.get('EWT', {}).get('summary', {})

spy_har_gjr = spy_res.get('har_wins_vs_gjr_r2', 0)
ewt_har_gjr = ewt_res.get('har_wins_vs_gjr_r2', 0)
n_spy = spy_res.get('n_valid_periods', 5)
n_ewt = ewt_res.get('n_valid_periods', 5)

# Compare with K465 (Parkinson proxy results)
k465_spy_har_gjr = 5  # K465: SPY HAR won 5/5 vs GJR (Parkinson)
k465_ewt_har_gjr = 5  # K465: EWT HAR won 5/5 vs GJR (Parkinson)

print(f"\n  K465 (Parkinson proxy): SPY HAR vs GJR = {k465_spy_har_gjr}/5, EWT = {k465_ewt_har_gjr}/5")
print(f"  K469 (r² proxy):       SPY HAR vs GJR = {spy_har_gjr}/{n_spy}, EWT = {ewt_har_gjr}/{n_ewt}")

# Determine tautology severity
total_k465 = k465_spy_har_gjr + k465_ewt_har_gjr  # 10 wins with Parkinson
total_k469 = spy_har_gjr + ewt_har_gjr  # wins with r²

if total_k469 >= 8:
    tautology = "MINIMAL — HAR genuinely dominates regardless of proxy"
    judgment = "HAR log-range is ROBUST: wins persist with r² evaluation"
elif total_k469 >= 5:
    tautology = "MODERATE — HAR advantage partially depends on proxy choice"
    judgment = "HAR advantage is PARTIALLY tautological: some wins are proxy-driven"
elif total_k469 >= 2:
    tautology = "SEVERE — Most K465 wins were proxy artifacts"
    judgment = "K465 was LARGELY TAUTOLOGICAL: HAR advantage collapses with r² proxy"
else:
    tautology = "COMPLETE — K465 was entirely a proxy artifact"
    judgment = "K465 was ENTIRELY TAUTOLOGICAL: HAR has no advantage with r² proxy"

print(f"\n  Tautology severity: {tautology}")
print(f"  Judgment: {judgment}")

# Rankings comparison
print(f"\n  Average QLIKE rankings (r² proxy):")
for t in ['SPY', 'EWT']:
    if t in all_results:
        r = all_results[t]['summary']
        print(f"    {t}: HAR rank={r['avg_rank']['har_r2']:.1f}, GJR rank={r['avg_rank']['gjr_r2']:.1f}")
        print(f"    {t} avg QLIKE(r²): HAR={r['avg_qlike_r2'].get('har'):.6f}, "
              f"GJR={r['avg_qlike_r2'].get('gjr_garch'):.6f}, "
              f"EWMA={r['avg_qlike_r2'].get('ewma'):.6f}, "
              f"Roll={r['avg_qlike_r2'].get('rolling_21d'):.6f}")


# ============================================================
# 8. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "K469",
    "title": "HAR Log-Range Cross-OOS with r² Proxy (Correcting K465 Tautology)",
    "background": "K465: HAR 10/10 with Parkinson proxy. K468: Parkinson naturally favors range models (tautology). This experiment uses r² (squared return) as proxy to test if HAR advantage is genuine.",
    "references": [
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Alizadeh, Brandt & Diebold (2002) JFE — Range-based vol estimation",
        "K465 — HAR cross-OOS 10/10 (Parkinson proxy)",
        "K468 — Yang-Zhang study revealing Parkinson tautology",
        "Patton (2011) J Econometrics — Volatility forecast evaluation"
    ],
    "method": "5-period cross-OOS with r² proxy. HAR forecasts scaled from Parkinson to r² level using IS calibration ratio. DM test for statistical significance.",
    "key_innovation": "Using r² (close-to-close squared return) instead of Parkinson as evaluation proxy eliminates tautological bias favoring range-based models.",
    "assets": list(ASSETS.keys()),
    "oos_periods": [p['name'] for p in OOS_PERIODS],
    "is_window": IS_WINDOW,
    "models": [
        "GJR-GARCH(1,1) Student-t",
        "HAR log-range (1d+5d+21d) — scaled to r² level",
        "EWMA (lambda=0.94)",
        "Rolling 21-day variance"
    ],
    "data_source": "yfinance (SPY, EWT)",
    "evaluation_proxy": "r² = (close-to-close log return)² — NOT Parkinson",
    "scale_calibration": "σ²_HAR_scaled = σ²_HAR_parkinson × (IS mean r² / IS mean Parkinson)",
    "judgment_criteria": {
        "har_genuine": "HAR wins ≥3/5 periods vs GJR with r² proxy → advantage is real",
        "tautology_artifact": "HAR wins 0-2/5 with r² → K465 was mainly proxy artifact",
        "comparison": f"K465 (Parkinson): 10/10. K469 (r²): {total_k469}/10"
    },
    "results": all_results,
    "tautology_severity": tautology,
    "judgment": judgment,
    "comparison_with_k465": {
        "k465_parkinson_proxy": {"spy_har_vs_gjr": "5/5", "ewt_har_vs_gjr": "5/5", "total": "10/10"},
        "k469_r2_proxy": {
            "spy_har_vs_gjr": f"{spy_har_gjr}/{n_spy}",
            "ewt_har_vs_gjr": f"{ewt_har_gjr}/{n_ewt}",
            "total": f"{total_k469}/10"
        },
        "drop_in_wins": total_k465 - total_k469,
    },
    "runtime_seconds": round(elapsed, 1),
    "timestamp": datetime.now(timezone.utc).isoformat()
}

output_path = "experiments/k469_har_r2_proxy_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K469 COMPLETE")
print("=" * 70)
