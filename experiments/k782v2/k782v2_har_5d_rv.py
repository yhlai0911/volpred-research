#!/usr/bin/env python3
"""
K782v2: HAR Multi-Horizon Volatility Forecasting — BUGFIX VERSION
==================================================================
[提出: 用戶 + Codex 審查, 執行: Claude]

This is the corrected version of K782, fixing two HIGH-severity bugs
found by Codex review:

BUG 1 (HAR target lookahead):
  Original: train = valid.iloc[:loc]
  The forward targets (target_hd) use returns from t+1 to t+h.
  Rows near the forecast origin have targets that peek into OOS data.
  FIX: train = valid.iloc[:loc - horizon]
  This ensures no training row's target window extends beyond t-1.

BUG 2 (GJR multi-step off-by-one):
  Original: r_last = returns_full.iloc[loc]  (loc = position of dt in OOS)
  This uses the return AT date dt, which is an OOS observation.
  FIX: r_last = returns_full.iloc[loc - 1]  (last IS return)
  Also: last_cond_var after refit uses the IS-only conditional variance
  (already correct in original, but we ensure consistency).

Everything else is identical to K782 — same data, same OOS, same metrics.

RV Construction (no intraday data needed):
  RV_d(t)   = r_squared(t)                    (daily realized variance proxy)
  RV_5d(t)  = (1/5) * Sum r_squared(t-4:t)     (5-day average daily RV)
  RV_22d(t) = (1/22) * Sum r_squared(t-21:t)   (22-day average daily RV)
  RV_66d(t) = (1/66) * Sum r_squared(t-65:t)   (66-day average daily RV)

Models:
  1. HAR-RV (level):     RV_h(t+1:t+h) = c + beta_d RV_d(t) + beta_w RV_5d(t) + beta_m RV_22d(t) + eps
  2. HAR-RV (log):       log(RV_h(t+1:t+h)) = c + beta_d log(RV_d(t)) + ... + eps
  3. GJR-GARCH h-step:   Recursive multi-step from GJR(1,1) -- proper formula
  4. EWMA h-step:        Exponential smoothing projected forward
  5. Rolling Window:     Simple rolling h-day variance (naive benchmark)

Evaluation: QLIKE, MSE, R-squared (Mincer-Zarnowitz), Spearman, DM test (Harvey t>3.0)
Horizons: h=5, h=22, h=66
Data: SPY from yfinance, 2006-01-01 to 2025-12-31
OOS: 2023-01-01 to 2024-12-31 (~504 trading days)
Window: expanding, start=2000 obs, refit every 22 days

References:
  - Corsi (2009) J.Financial Econometrics -- HAR model
  - Patton (2011) J.Econometrics 160 -- QLIKE proxy-robust loss
  - Glosten, Jagannathan, Runkle (1993) JoF -- GJR-GARCH
  - Harvey (2016) -- t>3.0 threshold for multiple testing
  - Hansen, Lunde (2005) -- multi-step GARCH forecasting
  - K530: HAR-ABS dominates GJR daily (DM=-15.45), universal across 7 assets
  - K782: Original version (contains lookahead + off-by-one bugs)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import spearmanr
from datetime import datetime, timezone
from arch import arch_model
import warnings
import os
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k782v2_har_5d_rv_results.json')

# ============================================================
# Part A: Data Download & RV Construction
# ============================================================

def download_data():
    """Download SPY data from yfinance."""
    print("[1/6] Downloading SPY data from yfinance...")
    spy = yf.download('SPY', start='2006-01-01', end='2026-01-01', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy.index = pd.to_datetime(spy.index)
    returns = np.log(spy['Close'] / spy['Close'].shift(1)).dropna()
    returns.name = 'log_return'
    print(f"  SPY: {len(returns)} daily returns, {returns.index[0].date()} to {returns.index[-1].date()}")
    return returns


def construct_rv(returns, horizons=[5, 22, 66]):
    """
    Construct realized variance at multiple horizons using daily squared returns.

    RV_h(t) = (1/h) * Sum_{i=0}^{h-1} r_squared(t-i)

    This is the AVERAGE daily squared return over h days.
    """
    df = pd.DataFrame({'r': returns, 'r2': returns**2})

    # Daily RV = squared return
    df['rv_1d'] = df['r2']

    for h in horizons:
        # Rolling mean of squared returns (average daily variance over h days)
        df[f'rv_{h}d'] = df['r2'].rolling(h).mean()

    return df.dropna()


def construct_targets(df, horizons=[5, 22, 66]):
    """
    Construct forward-looking targets for each horizon.

    Target_h(t) = (1/h) * Sum_{i=1}^{h} r_squared(t+i)

    This is the FUTURE average daily squared return over the next h days.
    CRITICAL: Uses data from t+1 to t+h (no overlap with predictors at t).
    """
    for h in horizons:
        # Forward-looking: average daily squared return over NEXT h days
        df[f'target_{h}d'] = df['r2'].shift(-1).rolling(h).mean().shift(-(h-1))

    return df


# ============================================================
# Part B: Model Implementations
# ============================================================

def fit_har_ols(y, X):
    """OLS estimation for HAR model. Returns coefficients."""
    # Add constant
    X_const = np.column_stack([np.ones(len(X)), X])
    try:
        beta = np.linalg.lstsq(X_const, y, rcond=None)[0]
        return beta
    except Exception:
        return None


def har_predict(beta, X_new):
    """Predict from HAR model."""
    X_const = np.column_stack([np.ones(len(X_new)), X_new])
    return X_const @ beta


def har_forecast_one_horizon(df, oos_start, horizon, use_log=False):
    """
    HAR model for a single horizon.

    HAR-RV: target_h(t) = c + beta_d * rv_1d(t) + beta_w * rv_5d(t) + beta_m * rv_22d(t) + eps

    Expanding window, refit every 22 days.
    Returns forecasts aligned with OOS dates.

    BUG 1 FIX: Training data excludes rows whose target_hd window extends
    beyond the forecast date. The last usable training row is at index loc-horizon
    (because target at row i uses returns from i+1 to i+h, so for the row at
    loc-horizon, the target uses returns up to loc-horizon+horizon = loc,
    which is still one step before the OOS date at loc+1... but since we want
    NO overlap with date loc itself being the forecast origin, we use loc-horizon).
    """
    target_col = f'target_{horizon}d'

    # Prepare data
    valid = df.dropna(subset=['rv_1d', 'rv_5d', 'rv_22d', target_col])

    oos_mask = valid.index >= oos_start
    oos_dates = valid.index[oos_mask]

    if len(oos_dates) == 0:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    forecasts = []
    actuals = []
    dates = []

    last_fit_idx = -999
    beta = None

    for i, dt in enumerate(oos_dates):
        loc = valid.index.get_loc(dt)

        # Refit every 22 days or first time
        if i - last_fit_idx >= 22 or beta is None:
            # ===== BUG 1 FIX =====
            # Original: train = valid.iloc[:loc]
            # This includes rows whose target_hd uses returns AFTER date dt.
            # Fix: Exclude last `horizon` rows before loc so that no training
            # target window extends into the OOS forecast origin.
            # The row at position (loc - horizon) has target using returns
            # from (loc-horizon+1) to (loc-horizon+horizon) = loc.
            # Since loc is the forecast date dt (first OOS return we must not
            # use in training), we need target windows ending at loc-1 at most.
            # So last usable training row is at (loc - horizon - 1), and
            # slice [:loc - horizon] gives indices 0..loc-horizon-1.
            # Wait — let's be precise:
            #   Row at index j has target_hd = mean(r²[j+1], ..., r²[j+h])
            #   For no lookahead: j+h < loc  =>  j < loc - h  =>  j <= loc-h-1
            #   So train = valid.iloc[:loc - horizon] gives indices 0..loc-h-1. Correct.
            train_end = loc - horizon
            train = valid.iloc[:train_end]
            if len(train) < 100:
                continue

            if use_log:
                # Log transform (add small epsilon to avoid log(0))
                eps = 1e-10
                y_train = np.log(train[target_col].values + eps)
                X_train = np.column_stack([
                    np.log(train['rv_1d'].values + eps),
                    np.log(train['rv_5d'].values + eps),
                    np.log(train['rv_22d'].values + eps)
                ])
            else:
                y_train = train[target_col].values
                X_train = np.column_stack([
                    train['rv_1d'].values,
                    train['rv_5d'].values,
                    train['rv_22d'].values
                ])

            new_beta = fit_har_ols(y_train, X_train)
            if new_beta is not None:
                beta = new_beta
                last_fit_idx = i

        if beta is None:
            continue

        # Forecast using data at time t (BEFORE target period)
        row = valid.iloc[loc]
        if use_log:
            eps = 1e-10
            x_new = np.array([[
                np.log(row['rv_1d'] + eps),
                np.log(row['rv_5d'] + eps),
                np.log(row['rv_22d'] + eps)
            ]])
            pred = np.exp(har_predict(beta, x_new)[0])  # Transform back
        else:
            x_new = np.array([[row['rv_1d'], row['rv_5d'], row['rv_22d']]])
            pred = har_predict(beta, x_new)[0]

        # Ensure positive forecast
        pred = max(pred, 1e-10)

        forecasts.append(pred)
        actuals.append(row[target_col])
        dates.append(dt)

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


def gjr_garch_multi_step(df, oos_start, horizon):
    """
    GJR-GARCH h-step ahead forecast.

    For h-step ahead, use recursive formula:
    sigma2(t+1|t) = standard 1-step GJR forecast
    sigma2(t+h|t) = omega/(1-persistence) + persistence^(h-1) * (sigma2(t+1|t) - omega/(1-persistence))

    The h-step target is the AVERAGE variance: (1/h) * Sum sigma2(t+i|t)

    BUG 2 FIX: r_last uses returns_full.iloc[loc-1] (last IS return),
    NOT iloc[loc] which is the OOS return at date dt.
    """
    target_col = f'target_{horizon}d'

    valid = df.dropna(subset=[target_col])
    returns_full = valid['r']

    oos_mask = valid.index >= oos_start
    oos_dates = valid.index[oos_mask]

    forecasts = []
    actuals = []
    dates = []

    last_fit_idx = -999
    model_params = None
    last_cond_var = None

    for i, dt in enumerate(oos_dates):
        loc = valid.index.get_loc(dt)

        # Refit every 22 days
        if i - last_fit_idx >= 22 or model_params is None:
            train_returns = returns_full.iloc[:loc]
            if len(train_returns) < 500:
                continue

            try:
                am = arch_model(train_returns * 100, vol='Garch', p=1, o=1, q=1,
                               dist='normal', mean='Constant')
                res = am.fit(disp='off', show_warning=False)

                omega = res.params.get('omega', None)
                alpha = res.params.get('alpha[1]', None)
                gamma = res.params.get('gamma[1]', 0)
                beta_g = res.params.get('beta[1]', None)

                if omega is None or alpha is None or beta_g is None:
                    continue

                # Convert back from percentage returns (*100) to decimal
                # omega is in (%)^2 units, need to convert to decimal^2
                omega_dec = omega / 10000

                persistence = alpha + gamma / 2 + beta_g

                if persistence >= 1.0:
                    continue

                model_params = {
                    'omega': omega_dec,
                    'alpha': alpha,
                    'gamma': gamma,
                    'beta': beta_g,
                    'persistence': persistence
                }
                last_cond_var = res.conditional_volatility.iloc[-1]**2 / 10000  # Convert to decimal^2
                last_fit_idx = i

            except Exception:
                continue

        if model_params is None:
            continue

        p = model_params

        # ===== BUG 2 FIX =====
        # Original: r_last = returns_full.iloc[loc]
        # This uses the return AT date dt, which is an OOS observation.
        # Fix: Use the last in-sample return (one before dt).
        r_last = returns_full.iloc[loc - 1]
        indicator = 1.0 if r_last < 0 else 0.0

        sigma2_1 = p['omega'] + p['alpha'] * r_last**2 + p['gamma'] * indicator * r_last**2 + p['beta'] * last_cond_var
        sigma2_1 = max(sigma2_1, 1e-10)

        # h-step recursive:
        # sigma2(t+k|t) = unc_var + persistence^(k-1) * (sigma2(t+1|t) - unc_var)
        unc_var = p['omega'] / (1 - p['persistence'])

        # Accumulate for average
        total_var = 0
        for k in range(1, horizon + 1):
            if k == 1:
                sigma2_k = sigma2_1
            else:
                sigma2_k = unc_var + p['persistence']**(k - 1) * (sigma2_1 - unc_var)
            total_var += sigma2_k

        avg_var = total_var / horizon
        avg_var = max(avg_var, 1e-10)

        # Update last_cond_var for next iteration (approximate)
        last_cond_var = sigma2_1

        forecasts.append(avg_var)
        actuals.append(valid.iloc[loc][target_col])
        dates.append(dt)

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


def ewma_multi_step(df, oos_start, horizon, lam=0.94):
    """
    EWMA h-step ahead forecast.

    EWMA variance: sigma2(t) = lam * sigma2(t-1) + (1-lam) * r_squared(t)
    h-step: sigma2(t+h|t) = sigma2(t+1|t) = sigma2(t) (EWMA is flat forecast)

    So h-step average = sigma2(t) (same for all horizons).
    """
    target_col = f'target_{horizon}d'

    valid = df.dropna(subset=[target_col])

    # Compute EWMA variance for full series
    r2 = valid['r2'].values
    n = len(r2)
    ewma_var = np.zeros(n)
    ewma_var[0] = r2[0]
    for t in range(1, n):
        ewma_var[t] = lam * ewma_var[t - 1] + (1 - lam) * r2[t]

    oos_mask = valid.index >= oos_start
    oos_dates = valid.index[oos_mask]

    forecasts = []
    actuals = []
    dates = []

    for dt in oos_dates:
        loc = valid.index.get_loc(dt)
        # EWMA forecast is flat: average over h days = current EWMA
        forecasts.append(max(ewma_var[loc], 1e-10))
        actuals.append(valid.iloc[loc][target_col])
        dates.append(dt)

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


def rolling_window_forecast(df, oos_start, horizon):
    """
    Naive rolling window forecast: use past h-day average variance
    as forecast for next h-day average variance.

    Forecast = rv_{h}d(t) (backward-looking h-day average RV).
    """
    target_col = f'target_{horizon}d'
    rv_col = f'rv_{horizon}d' if horizon > 1 else 'rv_1d'

    valid = df.dropna(subset=[target_col, rv_col])

    oos_mask = valid.index >= oos_start
    oos_dates = valid.index[oos_mask]

    forecasts = []
    actuals = []
    dates = []

    for dt in oos_dates:
        loc = valid.index.get_loc(dt)
        forecasts.append(max(valid.iloc[loc][rv_col], 1e-10))
        actuals.append(valid.iloc[loc][target_col])
        dates.append(dt)

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


# ============================================================
# Part C: Evaluation Metrics
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: L = actual/forecast - log(actual/forecast) - 1"""
    a = np.array(actual)
    f = np.array(forecast)
    # Filter out zeros/negatives
    mask = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    a, f = a[mask], f[mask]
    if len(a) == 0:
        return np.nan
    ratio = a / f
    return np.mean(ratio - np.log(ratio) - 1)


def mse_metric(actual, forecast):
    """Mean Squared Error."""
    a = np.array(actual)
    f = np.array(forecast)
    mask = np.isfinite(a) & np.isfinite(f)
    a, f = a[mask], f[mask]
    return np.mean((a - f)**2)


def mincer_zarnowitz_r2(actual, forecast):
    """Mincer-Zarnowitz R-squared: regress actual on forecast, report R-squared."""
    a = np.array(actual)
    f = np.array(forecast)
    mask = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    a, f = a[mask], f[mask]
    if len(a) < 10:
        return np.nan

    # OLS: actual = alpha + beta * forecast + eps
    X = np.column_stack([np.ones(len(f)), f])
    beta = np.linalg.lstsq(X, a, rcond=None)[0]
    fitted = X @ beta
    ss_res = np.sum((a - fitted)**2)
    ss_tot = np.sum((a - np.mean(a))**2)
    r2 = 1 - ss_res / ss_tot
    return r2


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test with Harvey et al. (1997) small-sample correction.

    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative DM => model 1 is better (lower loss).

    Returns (DM statistic, p-value).
    """
    from scipy.stats import t as t_dist

    d = np.array(loss1) - np.array(loss2)
    mask = np.isfinite(d)
    d = d[mask]
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)

    # Newey-West type variance estimation
    # For h-step ahead, use h-1 lags
    gamma_0 = np.var(d, ddof=1)

    nw_lags = max(h - 1, 0)
    gamma_sum = 0
    for k in range(1, nw_lags + 1):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_bar / np.sqrt(var_d)

    # Harvey et al. (1997) small-sample correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_corrected = dm_stat * correction

    p_value = 2 * t_dist.sf(abs(dm_corrected), df=n - 1)

    return dm_corrected, p_value


def compute_qlike_losses(actual, forecast):
    """Compute element-wise QLIKE losses for DM test."""
    a = np.array(actual)
    f = np.array(forecast)
    ratio = a / f
    return ratio - np.log(ratio) - 1


# ============================================================
# Part D: Main Experiment
# ============================================================

def run_single_horizon(df, oos_start, h):
    """Run all models for a single horizon."""

    print(f"\n{'='*60}")
    print(f"  Horizon: {h}-day")
    print(f"{'='*60}")

    results = {}
    model_forecasts = {}

    # 1. HAR-RV (level)
    print(f"  [h={h}] Fitting HAR-RV (level)...")
    t0 = time.time()
    fc_har, act_har = har_forecast_one_horizon(df, oos_start, h, use_log=False)
    print(f"    Done in {time.time()-t0:.1f}s, N={len(fc_har)}")
    model_forecasts['HAR-RV'] = (fc_har, act_har)

    # 2. HAR-RV (log)
    print(f"  [h={h}] Fitting HAR-RV (log)...")
    t0 = time.time()
    fc_harlog, act_harlog = har_forecast_one_horizon(df, oos_start, h, use_log=True)
    print(f"    Done in {time.time()-t0:.1f}s, N={len(fc_harlog)}")
    model_forecasts['HAR-log'] = (fc_harlog, act_harlog)

    # 3. GJR-GARCH h-step
    print(f"  [h={h}] Fitting GJR-GARCH {h}-step...")
    t0 = time.time()
    fc_gjr, act_gjr = gjr_garch_multi_step(df, oos_start, h)
    print(f"    Done in {time.time()-t0:.1f}s, N={len(fc_gjr)}")
    model_forecasts['GJR-GARCH'] = (fc_gjr, act_gjr)

    # 4. EWMA
    print(f"  [h={h}] Fitting EWMA...")
    t0 = time.time()
    fc_ewma, act_ewma = ewma_multi_step(df, oos_start, h)
    print(f"    Done in {time.time()-t0:.1f}s, N={len(fc_ewma)}")
    model_forecasts['EWMA'] = (fc_ewma, act_ewma)

    # 5. Rolling Window
    print(f"  [h={h}] Fitting Rolling Window...")
    t0 = time.time()
    fc_roll, act_roll = rolling_window_forecast(df, oos_start, h)
    print(f"    Done in {time.time()-t0:.1f}s, N={len(fc_roll)}")
    model_forecasts['Rolling'] = (fc_roll, act_roll)

    # Align all forecasts to common dates
    common_dates = None
    for name, (fc, act) in model_forecasts.items():
        if common_dates is None:
            common_dates = set(fc.index)
        else:
            common_dates = common_dates.intersection(set(fc.index))

    common_dates = sorted(common_dates)
    n_common = len(common_dates)
    print(f"\n  Common OOS dates for h={h}: {n_common}")

    if n_common < 50:
        print(f"  WARNING: Too few common dates ({n_common}), skipping horizon {h}")
        return h, None

    # Evaluate all models
    model_names = ['HAR-RV', 'HAR-log', 'GJR-GARCH', 'EWMA', 'Rolling']

    metrics = {}
    aligned_fc = {}
    aligned_act = None

    for name in model_names:
        fc, act = model_forecasts[name]
        fc_aligned = fc.loc[common_dates].values
        act_aligned = act.loc[common_dates].values

        if aligned_act is None:
            aligned_act = act_aligned

        aligned_fc[name] = fc_aligned

        q = qlike(act_aligned, fc_aligned)
        m = mse_metric(act_aligned, fc_aligned)
        r2 = mincer_zarnowitz_r2(act_aligned, fc_aligned)
        sp, sp_p = spearmanr(act_aligned, fc_aligned)

        metrics[name] = {
            'QLIKE': round(float(q), 6),
            'MSE': float(f'{m:.2e}'),
            'MZ_R2': round(float(r2), 4),
            'Spearman': round(float(sp), 4),
            'Spearman_p': float(f'{sp_p:.2e}'),
            'N_obs': int(n_common)
        }

        print(f"  {name:15s}: QLIKE={q:.4f}  MSE={m:.2e}  R2={r2:.4f}  Spearman={sp:.4f}")

    # DM tests: HAR-RV vs each alternative
    print(f"\n  DM tests (HAR-RV vs alternatives, h={h}):")
    dm_results = {}

    har_losses = compute_qlike_losses(aligned_act, aligned_fc['HAR-RV'])

    for name in model_names:
        if name == 'HAR-RV':
            continue
        alt_losses = compute_qlike_losses(aligned_act, aligned_fc[name])

        # Use horizon as the h parameter for DM test (accounts for serial correlation)
        dm_stat, dm_p = dm_test(har_losses, alt_losses, h=h)

        dm_results[f'HAR-RV_vs_{name}'] = {
            'DM_stat': round(float(dm_stat), 3) if not np.isnan(dm_stat) else None,
            'p_value': round(float(dm_p), 4) if not np.isnan(dm_p) else None,
            'Harvey_significant': bool(abs(dm_stat) > 3.0) if not np.isnan(dm_stat) else False,
            'HAR_better': bool(dm_stat < 0) if not np.isnan(dm_stat) else None
        }

        sig = "***" if not np.isnan(dm_stat) and abs(dm_stat) > 3.0 else ("**" if not np.isnan(dm_stat) and abs(dm_stat) > 2.0 else "")
        direction = "HAR better" if not np.isnan(dm_stat) and dm_stat < 0 else "ALT better"
        print(f"    vs {name:15s}: DM={dm_stat:+.3f} (p={dm_p:.4f}) {sig} [{direction}]")

    # Also: pairwise DM for best model identification
    print(f"\n  Pairwise DM matrix (h={h}):")
    pairwise_dm = {}
    for i_m, name1 in enumerate(model_names):
        losses1 = compute_qlike_losses(aligned_act, aligned_fc[name1])
        for name2 in model_names[i_m + 1:]:
            losses2 = compute_qlike_losses(aligned_act, aligned_fc[name2])
            dm_stat, dm_p = dm_test(losses1, losses2, h=h)
            pair_key = f'{name1}_vs_{name2}'
            pairwise_dm[pair_key] = {
                'DM_stat': round(float(dm_stat), 3) if not np.isnan(dm_stat) else None,
                'p_value': round(float(dm_p), 4) if not np.isnan(dm_p) else None,
                'better_model': name1 if not np.isnan(dm_stat) and dm_stat < 0 else name2
            }
            sig = "***" if not np.isnan(dm_stat) and abs(dm_stat) > 3.0 else ""
            print(f"    {name1:10s} vs {name2:10s}: DM={dm_stat:+.3f} {sig}")

    # Find best model
    best_qlike = min(metrics.items(), key=lambda x: x[1]['QLIKE'])
    best_r2 = max(metrics.items(), key=lambda x: x[1]['MZ_R2'])
    best_spearman = max(metrics.items(), key=lambda x: x[1]['Spearman'])

    horizon_result = {
        'horizon': h,
        'n_obs': n_common,
        'oos_start': str(common_dates[0].date()) if hasattr(common_dates[0], 'date') else str(common_dates[0]),
        'oos_end': str(common_dates[-1].date()) if hasattr(common_dates[-1], 'date') else str(common_dates[-1]),
        'metrics': metrics,
        'dm_tests': dm_results,
        'pairwise_dm': pairwise_dm,
        'best_model': {
            'by_QLIKE': best_qlike[0],
            'by_R2': best_r2[0],
            'by_Spearman': best_spearman[0]
        }
    }

    print(f"\n  BEST by QLIKE: {best_qlike[0]} ({best_qlike[1]['QLIKE']:.4f})")
    print(f"  BEST by R2:    {best_r2[0]} ({best_r2[1]['MZ_R2']:.4f})")
    print(f"  BEST by Spear: {best_spearman[0]} ({best_spearman[1]['Spearman']:.4f})")

    return h, horizon_result


def main():
    print("=" * 70)
    print("K782v2: HAR Multi-Horizon Volatility Forecasting — BUGFIX VERSION")
    print("  Fixes: HAR target lookahead + GJR multi-step off-by-one")
    print("=" * 70)

    t_start = time.time()

    # Step 1: Download data
    returns = download_data()

    # Step 2: Construct RV at multiple horizons
    print("\n[2/6] Constructing realized variance at multiple horizons...")
    df = construct_rv(returns)
    print(f"  After RV construction: {len(df)} observations")

    # Step 3: Construct forward-looking targets
    print("\n[3/6] Constructing forward-looking targets...")
    df = construct_targets(df)

    # Descriptive statistics
    print("\n[4/6] Descriptive Statistics:")
    for col in ['rv_1d', 'rv_5d', 'rv_22d', 'rv_66d']:
        if col in df.columns:
            s = df[col].dropna()
            print(f"  {col:10s}: mean={s.mean():.6f}  std={s.std():.6f}  "
                  f"skew={s.skew():.2f}  kurt={s.kurtosis():.2f}  N={len(s)}")

    for col in ['target_5d', 'target_22d', 'target_66d']:
        if col in df.columns:
            s = df[col].dropna()
            print(f"  {col:10s}: mean={s.mean():.6f}  std={s.std():.6f}  "
                  f"skew={s.skew():.2f}  kurt={s.kurtosis():.2f}  N={len(s)}")

    # Autocorrelation of targets
    print("\n  Target autocorrelations (lag-1, lag-5, lag-22):")
    for col in ['target_5d', 'target_22d', 'target_66d']:
        if col in df.columns:
            s = df[col].dropna()
            ac1 = s.autocorr(lag=1)
            ac5 = s.autocorr(lag=5)
            ac22 = s.autocorr(lag=22)
            print(f"  {col:12s}: rho(1)={ac1:.3f}  rho(5)={ac5:.3f}  rho(22)={ac22:.3f}")

    # Step 5: Run models for each horizon
    print("\n[5/6] Running models for each horizon...")

    oos_start = pd.Timestamp('2023-01-01')
    horizons = [5, 22, 66]

    all_results = {}

    # Run sequentially (GARCH fitting uses arch package which isn't trivially parallelizable)
    for h in horizons:
        h_key, h_result = run_single_horizon(df, oos_start, h)
        if h_result is not None:
            all_results[f'{h_key}d'] = h_result

    # Step 6: Summary
    print("\n" + "=" * 70)
    print("[6/6] SUMMARY")
    print("=" * 70)

    summary = {}

    for h_key, h_result in all_results.items():
        print(f"\n--- {h_key} ---")
        best = h_result['best_model']
        print(f"  Best QLIKE:    {best['by_QLIKE']}")
        print(f"  Best R2:       {best['by_R2']}")
        print(f"  Best Spearman: {best['by_Spearman']}")

        # Check if HAR-RV is significantly better than all alternatives
        har_wins_all = True
        for k, v in h_result['dm_tests'].items():
            if v['DM_stat'] is not None and v['DM_stat'] > 0:
                har_wins_all = False
                break

        har_harvey_wins = sum(1 for v in h_result['dm_tests'].values()
                            if v.get('Harvey_significant', False) and v.get('HAR_better', False))

        summary[h_key] = {
            'best_QLIKE': best['by_QLIKE'],
            'best_R2': best['by_R2'],
            'best_Spearman': best['by_Spearman'],
            'HAR_wins_all_QLIKE': har_wins_all,
            'HAR_Harvey_significant_wins': har_harvey_wins,
            'total_comparisons': len(h_result['dm_tests'])
        }

        print(f"  HAR wins all by QLIKE: {har_wins_all}")
        print(f"  HAR Harvey-significant wins: {har_harvey_wins}/{len(h_result['dm_tests'])}")

    # Cross-horizon analysis
    print("\n--- Cross-Horizon Pattern ---")
    for model in ['HAR-RV', 'HAR-log', 'GJR-GARCH', 'EWMA', 'Rolling']:
        qlike_vals = []
        r2_vals = []
        for h_key, h_result in all_results.items():
            if model in h_result['metrics']:
                qlike_vals.append(h_result['metrics'][model]['QLIKE'])
                r2_vals.append(h_result['metrics'][model]['MZ_R2'])
        if qlike_vals:
            print(f"  {model:15s}: QLIKE=[{', '.join(f'{v:.4f}' for v in qlike_vals)}]  "
                  f"R2=[{', '.join(f'{v:.4f}' for v in r2_vals)}]")

    # ============================================================
    # Comparison with original K782 (buggy version)
    # ============================================================
    print("\n" + "=" * 70)
    print("COMPARISON: K782 (buggy) vs K782v2 (fixed)")
    print("=" * 70)

    k782_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k782_har_5d_rv_results.json')
    try:
        with open(k782_path, 'r') as f:
            k782_results = json.load(f)

        for h_key in ['5d', '22d', '66d']:
            if h_key in k782_results.get('horizon_results', {}) and h_key in all_results:
                print(f"\n--- {h_key} ---")
                old_metrics = k782_results['horizon_results'][h_key]['metrics']
                new_metrics = all_results[h_key]['metrics']

                old_best_q = k782_results['horizon_results'][h_key]['best_model']['by_QLIKE']
                new_best_q = all_results[h_key]['best_model']['by_QLIKE']
                changed = " ** CHANGED **" if old_best_q != new_best_q else ""
                print(f"  Best QLIKE: {old_best_q} -> {new_best_q}{changed}")

                print(f"  {'Model':15s} | {'QLIKE_old':>10s} {'QLIKE_new':>10s} {'diff':>10s} | {'Spear_old':>10s} {'Spear_new':>10s}")
                print(f"  {'-'*15}-+-{'-'*10}-{'-'*10}-{'-'*10}-+-{'-'*10}-{'-'*10}")
                for model in ['HAR-RV', 'HAR-log', 'GJR-GARCH', 'EWMA', 'Rolling']:
                    if model in old_metrics and model in new_metrics:
                        q_old = old_metrics[model]['QLIKE']
                        q_new = new_metrics[model]['QLIKE']
                        q_diff = q_new - q_old
                        sp_old = old_metrics[model]['Spearman']
                        sp_new = new_metrics[model]['Spearman']
                        print(f"  {model:15s} | {q_old:10.4f} {q_new:10.4f} {q_diff:+10.4f} | {sp_old:10.4f} {sp_new:10.4f}")

    except FileNotFoundError:
        print("  [K782 original results not found, skipping comparison]")

    elapsed = time.time() - t_start

    # Compile final results
    final_results = {
        'experiment_id': 'K782v2',
        'title': 'HAR Multi-Horizon Volatility Forecasting — BUGFIX VERSION',
        'description': (
            'Corrected version of K782 fixing two HIGH-severity bugs: '
            '(1) HAR training data included rows whose forward targets peeked into OOS data (lookahead), '
            '(2) GJR multi-step used OOS return at forecast origin (off-by-one). '
            'Fix 1: train = valid.iloc[:loc-horizon]. '
            'Fix 2: r_last = returns_full.iloc[loc-1].'
        ),
        'data_source': 'yfinance SPY',
        'data_period': f'{returns.index[0].date()} to {returns.index[-1].date()}',
        'oos_period': '2023-01-01 to 2024-12-31',
        'window': 'expanding (start=2000, refit every 22 days)',
        'horizons': horizons,
        'bugs_fixed': {
            'bug1_har_lookahead': {
                'description': 'HAR training included rows whose target_hd used returns beyond forecast date',
                'original_code': 'train = valid.iloc[:loc]',
                'fixed_code': 'train = valid.iloc[:loc - horizon]',
                'impact': 'HAR models had access to future information during training'
            },
            'bug2_gjr_off_by_one': {
                'description': 'GJR multi-step used OOS return at forecast date for 1-step forecast',
                'original_code': 'r_last = returns_full.iloc[loc]',
                'fixed_code': 'r_last = returns_full.iloc[loc - 1]',
                'impact': 'GJR 1-step forecast included OOS information'
            }
        },
        'rv_construction': {
            'rv_1d': 'r_squared(t)',
            'rv_5d': '(1/5) * Sum r_squared(t-4:t)',
            'rv_22d': '(1/22) * Sum r_squared(t-21:t)',
            'rv_66d': '(1/66) * Sum r_squared(t-65:t)',
            'target_hd': '(1/h) * Sum r_squared(t+1:t+h)'
        },
        'models': {
            'HAR-RV': 'HAR on level RV: target_h = c + beta_d*rv_1d + beta_w*rv_5d + beta_m*rv_22d',
            'HAR-log': 'HAR on log(RV): same regressors in log space, exp() transform back',
            'GJR-GARCH': 'GJR(1,1) with recursive h-step ahead formula',
            'EWMA': 'Exponential smoothing (lambda=0.94), flat multi-step forecast',
            'Rolling': 'Naive: past h-day average RV as forecast'
        },
        'horizon_results': all_results,
        'summary': summary,
        'elapsed_seconds': round(elapsed, 1),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Corsi (2009) J.Financial Econometrics -- HAR model',
            'Patton (2011) J.Econometrics 160 -- QLIKE proxy-robust loss',
            'Glosten, Jagannathan, Runkle (1993) JoF -- GJR-GARCH',
            'Harvey (2016) -- t>3.0 threshold',
            'Hansen, Lunde (2005) -- multi-step GARCH',
            'K782: Original version (contains HAR lookahead + GJR off-by-one bugs)',
            'K530: HAR-ABS universal breakthrough',
            'K457: Weekly frequency prediction',
            'K778: GJR best on r-squared target'
        ],
        'limitations': [
            'Daily r-squared is a noisy proxy for true variance (no intraday data)',
            'Single asset (SPY only) -- needs cross-asset validation',
            'OOS period (2023-2024) is relatively calm -- may differ in crisis',
            'GARCH multi-step uses approximate recursive formula',
            'HAR-RV estimated by OLS (could use WLS for heteroscedasticity)',
            '66-day horizon has fewer effective independent observations due to overlap'
        ]
    }

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(final_results, f, indent=2, default=str)

    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Total elapsed: {elapsed:.1f}s")

    return final_results


if __name__ == '__main__':
    results = main()
