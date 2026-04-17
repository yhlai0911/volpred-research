#!/usr/bin/env python3
"""
K624: HAR-PD Path-Dependent Volatility (Daily Frequency Adaptation)

Background:
  Liu, Fu, Hong (arXiv:2503.00851, 2025) "Forecasting realized volatility:
  a path-dependent perspective" — volatility depends on historical price PATH,
  not just recent values.

  Path features:
    R1_t = Σ λ₁ exp(-λ₁τ) × r_{t-τ}  (trend: exponentially weighted past returns)
    R2_t = Σ λ₂ exp(-λ₂τ) × r²_{t-τ}  (vol memory: exponentially weighted squared returns)

Daily Adaptation:
  Without 5-min RV data, we use daily squared returns as vol proxy.

  Models:
    HAR:       σ²_t = β₀ + β₁ r²_{t-1} + β₂ avg5 + β₃ avg22
    HAR-PD:    HAR + β₄ R1_t + β₅ R2_t + β₆ |R1_t|
    HAR-PD-Asym: HAR + β₄ R1_t + β₅ R2_t + β₆ |R1_t| + β₇ RV⁻_t  (downside semivariance)
    GJR-GARCH(1,1) baseline (arch package)

  Note: naive {R1+, R1-} decomposition is linearly equivalent to {R1, |R1|}, so
  HAR-PD-Asym instead adds downside semivariance RV⁻ = Σ w(τ) r²_{t-τ} I(r_{t-τ}<0)
  to capture leverage effect (negative returns → higher future vol).

  λ estimation: Grid search over {0.01, 0.02, 0.05, 0.1, 0.2, 0.5} by IS BIC

Design:
  Rolling OOS: window=2000, OOS 2023-01-01 to 2024-12-31, refit every 21 days
  Assets: SPY, GLD, 0050.TW
  Metrics: QLIKE, MSE, R²_OOS, DM test vs GJR

Refs:
  Liu, Fu, Hong (2025) arXiv:2503.00851 — path-dependent vol forecasting
  Corsi (2009) J Financial Econometrics — HAR model
  Glosten, Jagannathan, Runkle (1993) JoF — GJR-GARCH
  Hansen, Lunde (2005) JoE — comparison framework

Data: yfinance, 2006-01-01 to 2026-03-27
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
from itertools import product

warnings.filterwarnings('ignore')

print("=" * 70)
print("K624: HAR-PD Path-Dependent Volatility (Daily Frequency)")
print("  Liu, Fu, Hong (2025) — path-dependent perspective, daily adaptation")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
ASSETS = {
    'SPY': {'name': 'US Large Cap', 'start': '2006-01-01'},
    'GLD': {'name': 'Gold ETF', 'start': '2006-01-01'},
    '0050.TW': {'name': 'Taiwan Top 50', 'start': '2006-01-01'},
}

OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
WINDOW = 2000
REFIT_EVERY = 21

LAMBDA_GRID = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5]
LOOKBACK_L = 252  # for exponential weights

# ============================================================
# Helper Functions
# ============================================================

def compute_path_features(returns, lambda1, lambda2, L=252):
    """
    Compute path-dependent features R1 (trend), R2 (vol memory), and RV_neg (downside semivariance).

    R1_t = Σ_{τ=1}^{L} w1(τ) × r_{t-τ}   (normalized exponential weights)
    R2_t = Σ_{τ=1}^{L} w2(τ) × r²_{t-τ}   (normalized exponential weights)
    RV_neg_t = Σ_{τ=1}^{L} w2(τ) × r²_{t-τ} × I(r_{t-τ} < 0)  (downside semivariance)

    w(τ) = exp(-λ*τ) / Σ exp(-λ*τ)  (normalized)
    """
    n = len(returns)
    r = returns.values if hasattr(returns, 'values') else returns
    r2 = r ** 2

    # Precompute normalized weights
    taus = np.arange(1, L + 1, dtype=np.float64)
    w1_raw = np.exp(-lambda1 * taus)
    w1 = w1_raw / w1_raw.sum()

    w2_raw = np.exp(-lambda2 * taus)
    w2 = w2_raw / w2_raw.sum()

    R1 = np.full(n, np.nan)
    R2 = np.full(n, np.nan)
    RV_neg = np.full(n, np.nan)

    # Vectorized computation using convolution-like approach
    for t in range(L, n):
        # r_{t-1}, r_{t-2}, ..., r_{t-L}  → weights w(1), w(2), ..., w(L)
        past_r = r[t - L:t][::-1]  # most recent first
        past_r2 = r2[t - L:t][::-1]

        R1[t] = np.dot(w1, past_r)
        R2[t] = np.dot(w2, past_r2)
        # Downside semivariance: only squared returns where return was negative
        neg_mask = past_r < 0
        RV_neg[t] = np.dot(w2, past_r2 * neg_mask)

    return R1, R2, RV_neg


def build_har_features(returns, squared_returns):
    """Build standard HAR features: r²_{t-1}, avg5, avg22."""
    n = len(returns)
    r2 = squared_returns

    lag1 = np.full(n, np.nan)
    avg5 = np.full(n, np.nan)
    avg22 = np.full(n, np.nan)

    for t in range(22, n):
        lag1[t] = r2[t - 1]
        avg5[t] = np.mean(r2[t - 5:t])
        avg22[t] = np.mean(r2[t - 22:t])

    return lag1, avg5, avg22


def compute_bic_for_lambda(returns, squared_returns, target, lambda1, lambda2, L=252):
    """Compute BIC for HAR-PD model with given lambda values (in-sample)."""
    r = returns.values if hasattr(returns, 'values') else returns
    r2 = squared_returns

    R1, R2, _RV_neg = compute_path_features(returns, lambda1, lambda2, L)
    lag1, avg5, avg22 = build_har_features(returns, r2)

    # Build design matrix (only valid rows)
    valid = ~(np.isnan(lag1) | np.isnan(avg5) | np.isnan(avg22) |
              np.isnan(R1) | np.isnan(R2) | np.isnan(target))

    X = np.column_stack([
        np.ones(valid.sum()),
        lag1[valid], avg5[valid], avg22[valid],
        R1[valid], R2[valid], np.abs(R1[valid])
    ])
    y = target[valid]

    if len(y) < X.shape[1] + 5:
        return np.inf

    # OLS estimation
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residuals = y - X @ beta
        n_obs = len(y)
        k = X.shape[1]
        sigma2 = np.sum(residuals ** 2) / n_obs

        if sigma2 <= 0:
            return np.inf

        bic = n_obs * np.log(sigma2) + k * np.log(n_obs)
        return bic
    except Exception:
        return np.inf


def grid_search_lambda(returns, squared_returns, target, lambda_grid, L=252):
    """Grid search for optimal λ₁, λ₂ using in-sample BIC."""
    best_bic = np.inf
    best_l1, best_l2 = lambda_grid[1], lambda_grid[1]  # default

    for l1, l2 in product(lambda_grid, lambda_grid):
        bic = compute_bic_for_lambda(returns, squared_returns, target, l1, l2, L)
        if bic < best_bic:
            best_bic = bic
            best_l1, best_l2 = l1, l2

    return best_l1, best_l2, best_bic


def ols_forecast(X_train, y_train, X_test):
    """OLS fit and predict."""
    try:
        beta = np.linalg.lstsq(X_train, y_train, rcond=None)[0]
        pred = X_test @ beta
        return max(pred[0], 1e-10)  # floor at near-zero
    except Exception:
        return np.mean(y_train)  # fallback


def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1.
    Lower is better. Robust loss for variance forecasting."""
    a = np.array(actual)
    f = np.array(forecast)

    # Filter valid
    valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    a, f = a[valid], f[valid]

    if len(a) == 0:
        return np.nan

    ratio = a / f
    return np.mean(ratio - np.log(ratio) - 1)


def mse(actual, forecast):
    """Mean Squared Error."""
    a = np.array(actual)
    f = np.array(forecast)
    valid = np.isfinite(a) & np.isfinite(f)
    return np.mean((a[valid] - f[valid]) ** 2)


def r2_oos(actual, forecast):
    """Out-of-sample R²: 1 - SSE/SST."""
    a = np.array(actual)
    f = np.array(forecast)
    valid = np.isfinite(a) & np.isfinite(f)
    a, f = a[valid], f[valid]

    sse = np.sum((a - f) ** 2)
    sst = np.sum((a - np.mean(a)) ** 2)

    if sst == 0:
        return np.nan
    return 1 - sse / sst


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns t-stat and p-value. Negative t-stat means model 1 is better."""
    d = np.array(loss1) - np.array(loss2)
    valid = np.isfinite(d)
    d = d[valid]

    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1] if len(d) > k else 0
        var_d += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(var_d / n)
    if se == 0:
        return np.nan, np.nan

    t_stat = d_mean / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return t_stat, p_value


# ============================================================
# Main Experiment
# ============================================================

all_results = {}
start_time = time.time()

for ticker, info in ASSETS.items():
    print(f"\n{'=' * 60}")
    print(f"Asset: {ticker} ({info['name']})")
    print(f"{'=' * 60}")

    # Download data
    try:
        df = yf.download(ticker, start=info['start'], end='2026-03-28', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close'])
        print(f"  Data: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} obs)")
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")
        continue

    if len(df) < WINDOW + 300:
        print(f"  SKIP: insufficient data ({len(df)} < {WINDOW + 300})")
        continue

    # Compute returns and squared returns
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
    df = df.dropna(subset=['log_ret'])

    returns = df['log_ret'].values
    r2_proxy = returns ** 2  # daily squared return as vol proxy

    # ---- Diagnostics ----
    print(f"\n  --- Diagnostics ---")
    print(f"  Mean return: {np.mean(returns):.6f}")
    print(f"  Std return:  {np.std(returns):.6f}")
    print(f"  Skewness:    {stats.skew(returns):.3f}")
    print(f"  Kurtosis:    {stats.kurtosis(returns):.3f}")
    print(f"  Mean r²:     {np.mean(r2_proxy):.8f}")
    print(f"  ADF stat:    {stats.normaltest(returns[:1000])[1]:.4f} (normality p-val)")

    # ---- Build full features for indexing ----
    lag1_full, avg5_full, avg22_full = build_har_features(returns, r2_proxy)

    # ---- OOS setup ----
    dates = df.index
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        print(f"  SKIP: no OOS data in {OOS_START} to {OOS_END}")
        continue

    oos_start_idx = oos_indices[0]
    oos_end_idx = oos_indices[-1]
    print(f"\n  OOS: {dates[oos_start_idx].date()} to {dates[oos_end_idx].date()} ({len(oos_indices)} obs)")

    if oos_start_idx < WINDOW + LOOKBACK_L:
        print(f"  SKIP: not enough history for window={WINDOW} + lookback={LOOKBACK_L}")
        continue

    # ---- Containers for forecasts ----
    forecasts = {
        'HAR': [],
        'HAR_PD': [],
        'HAR_PD_Asym': [],
        'GJR_GARCH': [],
    }
    actuals = []
    oos_dates_list = []
    lambda_history = []

    # ---- Rolling OOS ----
    last_refit = -999
    cached_betas = {}
    cached_lambdas = (0.05, 0.05)
    cached_R1_full = None
    cached_R2_full = None
    cached_RV_neg_full = None
    gjr_var_forecast = None

    print(f"\n  Running rolling OOS (refit every {REFIT_EVERY} days)...")

    for i, t in enumerate(range(oos_start_idx, oos_end_idx + 1)):
        need_refit = (t - last_refit >= REFIT_EVERY) or (last_refit == -999)

        if need_refit:
            # Training window
            train_start = max(0, t - WINDOW)
            train_end = t  # predict t, use data up to t-1

            train_ret = returns[train_start:train_end]
            train_r2 = r2_proxy[train_start:train_end]
            train_target = r2_proxy[train_start:train_end]  # target is r²_t (shifted below)

            # Grid search for λ (using training data)
            # For efficiency, use a subset if training is large
            gs_ret = train_ret
            gs_r2 = train_r2
            gs_target = train_r2

            best_l1, best_l2, best_bic = grid_search_lambda(
                gs_ret, gs_r2, gs_target, LAMBDA_GRID, LOOKBACK_L
            )
            cached_lambdas = (best_l1, best_l2)
            lambda_history.append({
                'date': str(dates[t].date()),
                'lambda1': best_l1,
                'lambda2': best_l2,
                'bic': round(best_bic, 2)
            })

            # Compute path features for full available data up to t
            avail_ret = returns[:t]
            R1_full, R2_full, RV_neg_full = compute_path_features(avail_ret, best_l1, best_l2, LOOKBACK_L)
            cached_R1_full = R1_full
            cached_R2_full = R2_full
            cached_RV_neg_full = RV_neg_full

            # Build training matrices
            # Features at time s predict target at time s+1
            # But for HAR: features at time t use lags ending at t-1, predict r²_t
            # So: X[s] = [1, r²_{s-1}, avg5(s), avg22(s), R1(s), R2(s), |R1(s)|]
            # y[s] = r²_s

            lag1_tr, avg5_tr, avg22_tr = build_har_features(avail_ret, r2_proxy[:t])

            # Valid training indices: need all features and target
            valid_tr = np.arange(train_start, train_end)
            mask = (~np.isnan(lag1_tr[valid_tr]) & ~np.isnan(avg5_tr[valid_tr]) &
                    ~np.isnan(avg22_tr[valid_tr]))
            if cached_R1_full is not None:
                r1_avail = np.full(t, np.nan)
                r1_avail[:len(cached_R1_full)] = cached_R1_full
                r2_avail = np.full(t, np.nan)
                r2_avail[:len(cached_R2_full)] = cached_R2_full
                rv_neg_avail = np.full(t, np.nan)
                rv_neg_avail[:len(cached_RV_neg_full)] = cached_RV_neg_full
                mask_pd = mask & ~np.isnan(r1_avail[valid_tr]) & ~np.isnan(r2_avail[valid_tr]) & ~np.isnan(rv_neg_avail[valid_tr])
            else:
                mask_pd = mask
                r1_avail = np.full(t, np.nan)
                r2_avail = np.full(t, np.nan)
                rv_neg_avail = np.full(t, np.nan)

            train_idx = valid_tr[mask]
            train_idx_pd = valid_tr[mask_pd]

            if len(train_idx) < 50:
                # Not enough data — use previous betas
                pass
            else:
                # === HAR ===
                X_har = np.column_stack([
                    np.ones(len(train_idx)),
                    lag1_tr[train_idx],
                    avg5_tr[train_idx],
                    avg22_tr[train_idx]
                ])
                y_har = r2_proxy[train_idx]  # target: r²_t at each index
                try:
                    cached_betas['HAR'] = np.linalg.lstsq(X_har, y_har, rcond=None)[0]
                except Exception:
                    cached_betas['HAR'] = None

                if len(train_idx_pd) >= 50:
                    # === HAR-PD ===
                    X_pd = np.column_stack([
                        np.ones(len(train_idx_pd)),
                        lag1_tr[train_idx_pd],
                        avg5_tr[train_idx_pd],
                        avg22_tr[train_idx_pd],
                        r1_avail[train_idx_pd],
                        r2_avail[train_idx_pd],
                        np.abs(r1_avail[train_idx_pd])
                    ])
                    y_pd = r2_proxy[train_idx_pd]
                    try:
                        cached_betas['HAR_PD'] = np.linalg.lstsq(X_pd, y_pd, rcond=None)[0]
                    except Exception:
                        cached_betas['HAR_PD'] = None

                    # === HAR-PD-Asym ===
                    # Adds downside semivariance (RV_neg) to HAR-PD
                    # This captures leverage effect: negative returns contribute more to future vol
                    X_asym = np.column_stack([
                        np.ones(len(train_idx_pd)),
                        lag1_tr[train_idx_pd],
                        avg5_tr[train_idx_pd],
                        avg22_tr[train_idx_pd],
                        r1_avail[train_idx_pd],
                        r2_avail[train_idx_pd],
                        np.abs(r1_avail[train_idx_pd]),
                        rv_neg_avail[train_idx_pd]
                    ])
                    y_asym = r2_proxy[train_idx_pd]
                    try:
                        cached_betas['HAR_PD_Asym'] = np.linalg.lstsq(X_asym, y_asym, rcond=None)[0]
                    except Exception:
                        cached_betas['HAR_PD_Asym'] = None

            # === GJR-GARCH ===
            try:
                train_ret_pct = train_ret * 100  # arch uses percentage returns
                gjr = arch_model(train_ret_pct, vol='GARCH', p=1, o=1, q=1, dist='t')
                gjr_fit = gjr.fit(disp='off', show_warning=False)

                # Get one-step-ahead forecast
                gjr_fcast = gjr_fit.forecast(horizon=1)
                gjr_var_forecast = gjr_fcast.variance.values[-1, 0] / 10000  # back to decimal
                cached_betas['GJR_converged'] = True
            except Exception:
                gjr_var_forecast = np.mean(train_r2)
                cached_betas['GJR_converged'] = False

            last_refit = t
        else:
            # Update GJR forecast using GARCH recursion (approximate)
            # For non-refit days, just use the expanding mean as simple update
            if gjr_var_forecast is not None:
                # Simple EWMA update between refits
                alpha_ewma = 0.06
                gjr_var_forecast = (1 - alpha_ewma) * gjr_var_forecast + alpha_ewma * r2_proxy[t - 1]

        # ---- Generate forecasts for time t ----
        actual_t = r2_proxy[t]
        actuals.append(actual_t)
        oos_dates_list.append(str(dates[t].date()))

        # Floor for variance predictions: use 1% of recent 1-year average
        var_floor_har = np.mean(r2_proxy[max(0, t - 252):t]) * 0.01

        # HAR forecast
        if cached_betas.get('HAR') is not None:
            x_t = np.array([1.0, r2_proxy[t - 1], np.mean(r2_proxy[t - 5:t]), np.mean(r2_proxy[t - 22:t])])
            pred_har = max(x_t @ cached_betas['HAR'], var_floor_har)
        else:
            pred_har = np.mean(r2_proxy[max(0, t - 22):t])
        forecasts['HAR'].append(pred_har)

        # HAR-PD forecast
        # Compute R1, R2 at time t for both HAR-PD and HAR-PD-Asym
        r1_t = np.nan
        r2f_t = np.nan
        if cached_R1_full is not None:
            if t - 1 < len(cached_R1_full) and not np.isnan(cached_R1_full[t - 1]):
                r1_t = cached_R1_full[t - 1]
                r2f_t = cached_R2_full[t - 1]

        if np.isnan(r1_t) and t >= LOOKBACK_L:
            # Compute on the fly
            l1, l2 = cached_lambdas
            taus = np.arange(1, min(LOOKBACK_L, t) + 1)
            w1 = np.exp(-l1 * taus)
            w1 /= w1.sum()
            w2 = np.exp(-l2 * taus)
            w2 /= w2.sum()
            past = returns[t - len(taus):t][::-1]
            r1_t = np.dot(w1[:len(past)], past)
            r2f_t = np.dot(w2[:len(past)], past ** 2)

        if cached_betas.get('HAR_PD') is not None and not np.isnan(r1_t) and not np.isnan(r2f_t):
            x_t = np.array([1.0, r2_proxy[t - 1], np.mean(r2_proxy[t - 5:t]),
                            np.mean(r2_proxy[t - 22:t]), r1_t, r2f_t, abs(r1_t)])
            pred_pd = max(x_t @ cached_betas['HAR_PD'], var_floor_har)
        else:
            pred_pd = pred_har
        forecasts['HAR_PD'].append(pred_pd)

        # HAR-PD-Asym forecast (HAR-PD + downside semivariance)
        if cached_betas.get('HAR_PD_Asym') is not None:
            # Compute RV_neg at time t
            if t >= LOOKBACK_L:
                l1, l2 = cached_lambdas
                taus_t = np.arange(1, min(LOOKBACK_L, t) + 1)
                w2_t = np.exp(-l2 * taus_t)
                w2_t /= w2_t.sum()
                past_t = returns[t - len(taus_t):t][::-1]
                neg_mask_t = past_t < 0
                rv_neg_t = np.dot(w2_t[:len(past_t)], (past_t ** 2) * neg_mask_t)
            else:
                rv_neg_t = np.nan

            if not np.isnan(r1_t) and not np.isnan(r2f_t) and not np.isnan(rv_neg_t):
                x_t = np.array([1.0, r2_proxy[t - 1], np.mean(r2_proxy[t - 5:t]),
                                np.mean(r2_proxy[t - 22:t]), r1_t, r2f_t, abs(r1_t), rv_neg_t])
                pred_asym = max(x_t @ cached_betas['HAR_PD_Asym'], var_floor_har)
            else:
                pred_asym = pred_har
        else:
            pred_asym = pred_har
        forecasts['HAR_PD_Asym'].append(pred_asym)

        # GJR-GARCH forecast
        if gjr_var_forecast is not None:
            forecasts['GJR_GARCH'].append(max(gjr_var_forecast, 1e-10))
        else:
            forecasts['GJR_GARCH'].append(np.mean(r2_proxy[max(0, t - 22):t]))

        if (i + 1) % 100 == 0:
            print(f"    ... {i + 1}/{len(oos_indices)} OOS forecasts done")

    print(f"  Completed {len(actuals)} OOS forecasts")

    # ---- Compute Metrics ----
    actuals_arr = np.array(actuals)

    print(f"\n  --- Results ---")
    print(f"  {'Model':<16} {'QLIKE':>8} {'MSE(×1e6)':>10} {'R²_OOS':>8}")
    print(f"  {'-'*44}")

    asset_results = {
        'asset': ticker,
        'asset_name': info['name'],
        'oos_period': f"{OOS_START} to {OOS_END}",
        'n_oos': len(actuals),
        'n_refits': len(lambda_history),
        'models': {},
        'dm_tests': {},
        'lambda_history': lambda_history,
    }

    # Per-model metrics
    model_losses_qlike = {}

    for model_name in ['HAR', 'HAR_PD', 'HAR_PD_Asym', 'GJR_GARCH']:
        fcast = np.array(forecasts[model_name])

        q = qlike(actuals_arr, fcast)
        m = mse(actuals_arr, fcast)
        r2 = r2_oos(actuals_arr, fcast)

        # Per-observation QLIKE for DM test
        valid = (actuals_arr > 0) & (fcast > 0) & np.isfinite(actuals_arr) & np.isfinite(fcast)
        ratio = actuals_arr[valid] / fcast[valid]
        losses = ratio - np.log(ratio) - 1
        model_losses_qlike[model_name] = losses

        display_name = model_name.replace('_', '-')
        print(f"  {display_name:<16} {q:>8.4f} {m * 1e6:>10.4f} {r2:>8.4f}")

        asset_results['models'][model_name] = {
            'QLIKE': round(float(q), 6),
            'MSE': round(float(m), 10),
            'R2_OOS': round(float(r2), 6),
        }

    # DM tests vs GJR-GARCH baseline
    print(f"\n  --- DM Tests vs GJR-GARCH (QLIKE loss) ---")
    print(f"  {'Model':<16} {'t-stat':>8} {'p-value':>8} {'Winner':>10}")
    print(f"  {'-'*44}")

    gjr_losses = model_losses_qlike['GJR_GARCH']

    for model_name in ['HAR', 'HAR_PD', 'HAR_PD_Asym']:
        model_losses = model_losses_qlike[model_name]

        # Ensure same length
        min_len = min(len(model_losses), len(gjr_losses))
        t_stat, p_val = dm_test(model_losses[:min_len], gjr_losses[:min_len])

        if not np.isnan(t_stat):
            winner = model_name.replace('_', '-') if t_stat < 0 else 'GJR-GARCH'
            sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.1 else ''))
            print(f"  {model_name.replace('_', '-'):<16} {t_stat:>8.3f} {p_val:>8.4f} {winner:>10} {sig}")
        else:
            winner = 'N/A'
            t_stat, p_val = 0.0, 1.0
            print(f"  {model_name.replace('_', '-'):<16} {'N/A':>8} {'N/A':>8} {'N/A':>10}")

        asset_results['dm_tests'][f'{model_name}_vs_GJR'] = {
            't_stat': round(float(t_stat), 4) if not np.isnan(t_stat) else None,
            'p_value': round(float(p_val), 4) if not np.isnan(p_val) else None,
            'winner': winner,
        }

    # HAR-PD vs HAR (does path-dependence add value?)
    print(f"\n  --- DM Test: HAR-PD vs HAR ---")
    har_losses = model_losses_qlike['HAR']
    pd_losses = model_losses_qlike['HAR_PD']
    min_len = min(len(har_losses), len(pd_losses))
    t_stat, p_val = dm_test(pd_losses[:min_len], har_losses[:min_len])

    if not np.isnan(t_stat):
        winner = 'HAR-PD' if t_stat < 0 else 'HAR'
        sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.1 else ''))
        print(f"  t-stat: {t_stat:.3f}, p-value: {p_val:.4f}, Winner: {winner} {sig}")
    else:
        winner = 'N/A'
        t_stat, p_val = 0.0, 1.0
        print(f"  DM test failed (insufficient data)")

    asset_results['dm_tests']['HAR_PD_vs_HAR'] = {
        't_stat': round(float(t_stat), 4) if not np.isnan(t_stat) else None,
        'p_value': round(float(p_val), 4) if not np.isnan(p_val) else None,
        'winner': winner,
    }

    # Lambda stability analysis
    if lambda_history:
        l1_vals = [h['lambda1'] for h in lambda_history]
        l2_vals = [h['lambda2'] for h in lambda_history]

        print(f"\n  --- Lambda Stability ---")
        print(f"  λ₁ (trend):      mode={stats.mode(l1_vals, keepdims=False).mode:.3f}, "
              f"unique={len(set(l1_vals))}/{len(l1_vals)}")
        print(f"  λ₂ (vol memory): mode={stats.mode(l2_vals, keepdims=False).mode:.3f}, "
              f"unique={len(set(l2_vals))}/{len(l2_vals)}")

        # Distribution of λ values
        from collections import Counter
        l1_counts = Counter(l1_vals)
        l2_counts = Counter(l2_vals)

        print(f"  λ₁ distribution: {dict(sorted(l1_counts.items()))}")
        print(f"  λ₂ distribution: {dict(sorted(l2_counts.items()))}")

        asset_results['lambda_stability'] = {
            'lambda1_mode': float(stats.mode(l1_vals, keepdims=False).mode),
            'lambda2_mode': float(stats.mode(l2_vals, keepdims=False).mode),
            'lambda1_distribution': {str(k): v for k, v in sorted(l1_counts.items())},
            'lambda2_distribution': {str(k): v for k, v in sorted(l2_counts.items())},
            'n_refits': len(lambda_history),
        }

    # Best model ranking
    model_rankings = sorted(asset_results['models'].items(), key=lambda x: x[1]['QLIKE'])
    best_model = model_rankings[0][0]
    asset_results['best_model_qlike'] = best_model
    print(f"\n  Best model (QLIKE): {best_model.replace('_', '-')}")

    all_results[ticker] = asset_results

# ============================================================
# Cross-Asset Summary
# ============================================================
elapsed = time.time() - start_time
print(f"\n{'=' * 60}")
print(f"CROSS-ASSET SUMMARY")
print(f"{'=' * 60}")

print(f"\n  {'Asset':<10} {'Best Model':>14} {'HAR-PD vs HAR':>14} {'HAR-PD vs GJR':>14}")
print(f"  {'-'*54}")

for ticker, res in all_results.items():
    best = res.get('best_model_qlike', 'N/A').replace('_', '-')

    pd_har = res.get('dm_tests', {}).get('HAR_PD_vs_HAR', {})
    pd_har_str = f"t={pd_har.get('t_stat', 'N/A')}" if pd_har.get('t_stat') else 'N/A'

    pd_gjr = res.get('dm_tests', {}).get('HAR_PD_vs_GJR', {})
    pd_gjr_str = f"t={pd_gjr.get('t_stat', 'N/A')}" if pd_gjr.get('t_stat') else 'N/A'

    print(f"  {ticker:<10} {best:>14} {pd_har_str:>14} {pd_gjr_str:>14}")

# Key finding summary
print(f"\n  Key Findings:")
n_pd_wins = sum(1 for r in all_results.values()
                if r.get('best_model_qlike', '') == 'HAR_PD')
n_pd_asym_wins = sum(1 for r in all_results.values()
                     if r.get('best_model_qlike', '') == 'HAR_PD_Asym')
n_har_wins = sum(1 for r in all_results.values()
                 if r.get('best_model_qlike', '') == 'HAR')
n_gjr_wins = sum(1 for r in all_results.values()
                 if r.get('best_model_qlike', '') == 'GJR_GARCH')

print(f"  - HAR-PD wins: {n_pd_wins}/{len(all_results)}")
print(f"  - HAR-PD-Asym wins: {n_pd_asym_wins}/{len(all_results)}")
print(f"  - HAR wins: {n_har_wins}/{len(all_results)}")
print(f"  - GJR-GARCH wins: {n_gjr_wins}/{len(all_results)}")

path_adds_value = any(
    r.get('dm_tests', {}).get('HAR_PD_vs_HAR', {}).get('p_value', 1) < 0.10 and
    r.get('dm_tests', {}).get('HAR_PD_vs_HAR', {}).get('t_stat', 0) < 0
    for r in all_results.values()
)
print(f"  - Path-dependence adds significant value (any asset, p<0.10): {path_adds_value}")

# ============================================================
# Save Results
# ============================================================
output = {
    'experiment_id': 'K624',
    'title': 'HAR-PD Path-Dependent Volatility (Daily Frequency)',
    'description': 'Tests path-dependent volatility features (trend + vol memory) adapted from Liu, Fu, Hong (2025) for daily frequency forecasting',
    'methodology': 'HAR with exponentially weighted path features, OLS estimation, grid search for decay parameters',
    'data_source': 'yfinance',
    'data_period': f"{min(info['start'] for info in ASSETS.values())} to 2026-03-27",
    'oos_period': f"{OOS_START} to {OOS_END}",
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'lambda_grid': LAMBDA_GRID,
    'lookback_L': LOOKBACK_L,
    'models': ['HAR', 'HAR-PD', 'HAR-PD-Asym', 'GJR-GARCH(1,1)'],
    'metrics': ['QLIKE', 'MSE', 'R2_OOS'],
    'references': [
        'Liu, Fu, Hong (2025) arXiv:2503.00851 - Forecasting realized volatility: a path-dependent perspective',
        'Corsi (2009) J Financial Econometrics - A simple approximate long-memory model of realized volatility',
        'Glosten, Jagannathan, Runkle (1993) JoF - On the relation between expected value and volatility of the nominal excess return on stocks',
    ],
    'results': all_results,
    'summary': {
        'HAR_PD_wins': n_pd_wins,
        'HAR_PD_Asym_wins': n_pd_asym_wins,
        'HAR_wins': n_har_wins,
        'GJR_wins': n_gjr_wins,
        'path_dependence_significant': path_adds_value,
        'n_assets': len(all_results),
    },
    'execution_time_seconds': round(elapsed, 1),
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

output_path = 'experiments/k624_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"  Total execution time: {elapsed:.1f}s")
print(f"\n{'=' * 60}")
print(f"K624 COMPLETE")
print(f"{'=' * 60}")
