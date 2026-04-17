#!/usr/bin/env python3
"""
K824: Probabilistic Realized Volatility Quantile Forecasting
=============================================================
[提出: 用戶, 執行: Claude]

Research Question:
  Can data-driven quantile regression on GJR-GARCH standardized residuals
  provide better conditional quantile forecasts than parametric distributions
  (Normal, Student-t)?

Background:
  - arXiv:2508.15922: Extending GARCH/HAR point predictions to conditional
    quantile distributions
  - K802: GJR + Skewed-t = dual champion (QLIKE #1 + VaR PASS)
  - K800v2: Conformal VaR calibration was artifact; real fix = fat-tail dist.
  - Our GJR-GARCH is the confirmed point-prediction champion
  - Quantile regression is fully nonparametric — no distribution assumption

Method:
  Step 1: Fit GJR-GARCH(1,1) to get conditional variance σ²_t (expanding window)
  Step 2: Compute standardized residuals z_t = r_t / σ_t
  Step 3: For each quantile τ, estimate conditional quantile of z_t
  Step 4: Conditional quantile of r_t = σ_t × q_τ(z_t)

  Models compared (all use same GJR σ² forecast):
    M1: GJR + Normal quantiles (z_τ = Φ^{-1}(τ))
    M2: GJR + Student-t quantiles (df estimated from residuals via MLE)
    M3: GJR + Quantile Regression (statsmodels QuantReg on z_t features)
    M4: GJR + Historical Simulation (empirical quantile of z_t, expanding)

  Quantile levels: τ = 0.01, 0.05, 0.10, 0.50, 0.90, 0.95, 0.99

Evaluation:
  - Quantile Coverage: actual coverage vs nominal for each τ
  - Pinball Loss (tick loss): ρ_τ(y - q_τ) = (τ - I{y < q_τ}) × (y - q_τ)
  - VaR 1% Kupiec + Christoffersen + Basel traffic light
  - Winkler Score for prediction intervals (1%-99%, 5%-95%, 10%-90%)
  - DM test on pinball loss (Harvey t>3.0 threshold)

OOS: 2023-01-01 ~ 2024-12-31
Asset: SPY
Data source: yfinance
Expanding window, GJR refit every 63 trading days

signal.shift(1) enforced: forecast from t-1 data, evaluate against r_t

References:
  - arXiv:2508.15922 — Probabilistic quantile forecasting from GARCH/HAR
  - Koenker & Bassett (1978) Econometrica 46 — Quantile Regression
  - Engle & Manganelli (2004) JBES 22 — CAViaR
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss
  - Kupiec (1995) — unconditional VaR coverage
  - Christoffersen (1998) — conditional VaR independence
  - Gneiting & Raftery (2007) JASA 102 — Scoring rules, pinball loss
  - Winkler (1972) JASA 67 — Winkler score for interval forecasts
  - Harvey et al. (2016) — multiple testing threshold t>3.0
  - K802: GJR + Skewed-t = dual champion
  - K800v2: Conformal VaR (artifact, fat-tail is real fix)
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k824_quantile_forecasting_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63  # quarterly refit
TAUS = [0.01, 0.05, 0.10, 0.50, 0.90, 0.95, 0.99]


# ==============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ==============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ==============================================================
# B. GJR-GARCH model fitting
# ==============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


# ==============================================================
# C. GJR one-step-ahead forecast + standardized residuals
# ==============================================================

def gjr_one_step_forecast(returns, params):
    """GJR one-step forecast: σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    """z_t = r_t / σ_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ==============================================================
# D. Student-t df estimation from standardized residuals
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """Estimate Student-t df from standardized residuals via MLE."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0

    def neg_loglik(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        ll = np.sum(t_dist.logpdf(z, df=df))
        return -ll if np.isfinite(ll) else 1e10

    res = minimize(neg_loglik, x0=[np.log(5.0)],
                   method='L-BFGS-B',
                   bounds=[(np.log(df_min), np.log(df_max))],
                   options={'maxiter': 500})
    df_est = float(np.exp(res.x[0]))
    return float(np.clip(df_est, df_min, df_max))


# ==============================================================
# E. Quantile Regression on standardized residuals
# ==============================================================

def fit_quantile_regression(z_residuals, tau, n_lags=5):
    """
    Fit quantile regression: q_τ(z_t) = β_0 + β_1·|z_{t-1}| + β_2·z²_{t-1}
    + β_3·I(z_{t-1}<0)·|z_{t-1}| + β_4·MA5(|z|) + β_5·MA5(z²)

    Uses Koenker & Bassett (1978) quantile regression via statsmodels.

    Features capture:
      - Intercept: unconditional quantile level
      - |z_{t-1}|: recent magnitude effect (volatility clustering in residuals)
      - z²_{t-1}: squared effect (heavier weight on extremes)
      - Asymmetric term: negative shocks have different impact (leverage in residuals)
      - MA5(|z|): short-term average magnitude
      - MA5(z²): short-term variance of residuals

    Returns: fitted model or None.
    """
    import statsmodels.api as sm

    z = np.asarray(z_residuals, dtype=np.float64)
    n = len(z)
    if n < 100:
        return None

    # Build features (lagged — no lookahead)
    abs_z = np.abs(z)
    z_sq = z ** 2

    # Rolling MA of |z| and z²
    ma_abs = pd.Series(abs_z).rolling(n_lags, min_periods=1).mean().values
    ma_sq = pd.Series(z_sq).rolling(n_lags, min_periods=1).mean().values

    # Lagged features (shift by 1 to avoid lookahead)
    start = n_lags + 1
    y = z[start:]
    X = np.column_stack([
        abs_z[start - 1:-1],                                     # |z_{t-1}|
        z_sq[start - 1:-1],                                       # z²_{t-1}
        (z[start - 1:-1] < 0).astype(float) * abs_z[start - 1:-1],  # asymmetric
        ma_abs[start - 1:-1],                                     # MA5(|z|)
        ma_sq[start - 1:-1],                                      # MA5(z²)
    ])
    X = sm.add_constant(X)

    try:
        model = sm.QuantReg(y, X)
        result = model.fit(q=tau, max_iter=1000)
        return result
    except Exception:
        return None


def predict_quantile_regression(z_residuals, qr_model, n_lags=5):
    """
    Predict the next quantile from the last observation of z.
    Returns the predicted quantile of z_{t+1}.
    """
    import statsmodels.api as sm

    z = np.asarray(z_residuals, dtype=np.float64)
    abs_z = np.abs(z)
    z_sq = z ** 2
    ma_abs = pd.Series(abs_z).rolling(n_lags, min_periods=1).mean().values
    ma_sq = pd.Series(z_sq).rolling(n_lags, min_periods=1).mean().values

    # Use the last observation as features for the next prediction
    x_new = np.array([
        1.0,                                               # constant
        abs_z[-1],                                         # |z_T|
        z_sq[-1],                                          # z²_T
        float(z[-1] < 0) * abs_z[-1],                     # asymmetric
        ma_abs[-1],                                        # MA5(|z|)
        ma_sq[-1],                                         # MA5(z²)
    ])

    try:
        q_pred = float(qr_model.predict(x_new.reshape(1, -1))[0])
        # Clip to prevent insane quantiles
        q_pred = np.clip(q_pred, -8.0, 8.0)
        return q_pred
    except Exception:
        return None


# ==============================================================
# F. VaR backtest (Kupiec + Christoffersen + Basel)
# ==============================================================

def var_backtest(returns, var_series, alpha_var=0.01):
    """
    VaR backtest: Kupiec (1995) + Christoffersen (1998) + Basel traffic light.
    returns: OOS realized returns
    var_series: VaR threshold (negative values, e.g. -0.02 means 2% loss)
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec (1995) unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen (1998) independence
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                           + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    # Basel traffic light
    if pi_hat <= alpha_var * 1.5:
        traffic = 'green'
    elif pi_hat <= alpha_var * 2.0:
        traffic = 'yellow'
    else:
        traffic = 'red'

    return {
        'violation_rate': round(float(pi_hat), 6),
        'expected_rate': float(alpha_var),
        'n_violations': n1,
        'n_total': n,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# G. Pinball (Tick) Loss
# ==============================================================

def pinball_loss(y, q, tau):
    """
    Pinball (tick) loss: ρ_τ(y - q) = (τ - I{y < q}) × (y - q)
    Gneiting & Raftery (2007), Koenker & Bassett (1978).
    Lower is better.
    """
    y = np.asarray(y, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    e = y - q
    loss = np.where(e >= 0, tau * e, (tau - 1.0) * e)
    return float(np.mean(loss))


def pointwise_pinball(y, q, tau):
    """Pointwise pinball loss (for DM test)."""
    y = np.asarray(y, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1.0) * e)


# ==============================================================
# H. Winkler Score for prediction intervals
# ==============================================================

def winkler_score(y, lower, upper, alpha):
    """
    Winkler (1972) score for (1-α) prediction intervals.
    Penalizes width + exceedances. Lower is better.
    """
    y = np.asarray(y, dtype=np.float64)
    lower = np.asarray(lower, dtype=np.float64)
    upper = np.asarray(upper, dtype=np.float64)
    width = upper - lower
    penalties = np.zeros_like(y)
    below = y < lower
    above = y > upper
    penalties[below] = (2.0 / alpha) * (lower[below] - y[below])
    penalties[above] = (2.0 / alpha) * (y[above] - upper[above])
    scores = width + penalties
    return float(np.mean(scores))


# ==============================================================
# I. Diebold-Mariano test
# ==============================================================

def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t → model 1 better."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * w * gamma_l
    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    t_stat = d_mean / se
    p_value = float(2 * (1 - norm.cdf(abs(t_stat))))
    return float(t_stat), p_value


# ==============================================================
# MAIN: Expanding-window OOS quantile forecasting
# ==============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K824: Probabilistic Realized Volatility Quantile Forecasting")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Download data
    # ----------------------------------------------------------
    print("\n[1/5] Downloading SPY data...")
    spy = yf.download('SPY', start='2006-01-01', end='2026-01-01', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.dropna(subset=['Close'])
    returns = spy['Close'].pct_change().dropna()
    returns.index = pd.to_datetime(returns.index)
    returns = returns.loc[~returns.index.duplicated(keep='first')]
    r_values = returns.values.astype(np.float64)
    dates = returns.index

    print(f"  Total data: {len(returns)} days ({dates[0].date()} to {dates[-1].date()})")

    # OOS range
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_idx = np.where(oos_mask)[0]
    n_oos = len(oos_idx)
    print(f"  OOS period: {OOS_START} to {OOS_END}, {n_oos} days")

    if n_oos == 0:
        print("ERROR: No OOS data found!")
        sys.exit(1)

    # ----------------------------------------------------------
    # 2. Expanding-window GJR-GARCH + quantile forecasting
    # ----------------------------------------------------------
    print("\n[2/5] Running expanding-window GJR + quantile forecasting...")
    print(f"  Quantile levels: {TAUS}")
    print(f"  Refit every {REFIT_EVERY} days")

    # Storage: one row per OOS day, one column per (model, tau)
    model_names = ['M1_Normal', 'M2_StudentT', 'M3_QuantReg', 'M4_HistSim']
    # quantile_forecasts[model][tau] = array of length n_oos
    quantile_forecasts = {m: {tau: np.full(n_oos, np.nan) for tau in TAUS}
                          for m in model_names}
    sigma_forecasts = np.full(n_oos, np.nan)

    gjr_params = None
    last_fit_idx = -999
    t_df = 5.0  # initial Student-t df
    qr_models = {}  # {tau: fitted QuantReg model}

    for i, oos_pos in enumerate(oos_idx):
        # Expanding window: use all data up to (but not including) oos_pos
        train_end = oos_pos  # exclusive: data[0:train_end]
        r_train = r_values[:train_end]

        # Refit GJR every REFIT_EVERY days
        if oos_pos - last_fit_idx >= REFIT_EVERY:
            gjr_params = fit_gjr(r_train)
            if gjr_params is None:
                print(f"  WARNING: GJR fit failed at index {oos_pos}, using previous")
                continue
            last_fit_idx = oos_pos

            # Compute standardized residuals for distribution estimation
            z_train = compute_standardized_residuals(r_train, gjr_params)

            # Estimate Student-t df
            t_df = estimate_t_df(z_train)

            # Fit quantile regression models for each tau
            qr_models = {}
            for tau in TAUS:
                qr_model = fit_quantile_regression(z_train, tau)
                if qr_model is not None:
                    qr_models[tau] = qr_model

            if i % 100 == 0 or i == 0:
                print(f"  Refit at OOS day {i}/{n_oos}: "
                      f"persistence={gjr_params['persistence']:.4f}, "
                      f"t_df={t_df:.2f}, "
                      f"QR models fitted: {len(qr_models)}/{len(TAUS)}")

        if gjr_params is None:
            continue

        # One-step-ahead variance forecast (uses data up to t-1)
        sigma2_fcast = gjr_one_step_forecast(r_train, gjr_params)
        sigma_fcast = np.sqrt(sigma2_fcast)
        sigma_forecasts[i] = sigma_fcast

        # Compute current standardized residuals for QR/HS prediction
        z_train = compute_standardized_residuals(r_train, gjr_params)

        for tau in TAUS:
            # M1: Normal quantiles
            z_normal = norm.ppf(tau)
            quantile_forecasts['M1_Normal'][tau][i] = sigma_fcast * z_normal

            # M2: Student-t quantiles (scaled for unit variance)
            # Student-t with df has variance df/(df-2), so scale factor = sqrt((df-2)/df)
            if t_df > 2.0:
                scale = np.sqrt((t_df - 2.0) / t_df)
                z_t = t_dist.ppf(tau, df=t_df) * scale
            else:
                z_t = t_dist.ppf(tau, df=t_df)
            quantile_forecasts['M2_StudentT'][tau][i] = sigma_fcast * z_t

            # M3: Quantile Regression
            if tau in qr_models:
                z_qr = predict_quantile_regression(z_train, qr_models[tau])
                if z_qr is not None:
                    quantile_forecasts['M3_QuantReg'][tau][i] = sigma_fcast * z_qr

            # M4: Historical Simulation (empirical quantile of z_train)
            z_hs = float(np.percentile(z_train, tau * 100))
            quantile_forecasts['M4_HistSim'][tau][i] = sigma_fcast * z_hs

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{n_oos} days completed")

    print(f"  Forecasting complete. Elapsed: {time.time() - t0:.1f}s")

    # ----------------------------------------------------------
    # 3. Evaluate: Coverage, Pinball Loss, VaR backtest, Winkler
    # ----------------------------------------------------------
    print("\n[3/5] Evaluating quantile forecasts...")

    oos_returns = r_values[oos_idx]
    valid = np.isfinite(sigma_forecasts)

    results = {
        'experiment_id': 'K824',
        'title': 'K824: Probabilistic RV Quantile Forecasting',
        'asset': 'SPY',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'n_oos': int(n_oos),
        'n_valid': int(valid.sum()),
        'refit_every': REFIT_EVERY,
        'quantile_levels': TAUS,
        'models': model_names,
        'data_source': 'yfinance (SPY, 2006-01-01 to 2025-12-31)',
        'method': 'GJR-GARCH(1,1) expanding window + 4 quantile methods',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # 3a. Coverage table
    print("\n  --- Quantile Coverage (actual vs nominal) ---")
    coverage_table = {}
    for model in model_names:
        coverage_table[model] = {}
        for tau in TAUS:
            q = quantile_forecasts[model][tau]
            mask = valid & np.isfinite(q)
            if mask.sum() < 10:
                coverage_table[model][str(tau)] = None
                continue
            actual_below = np.mean(oos_returns[mask] < q[mask])
            coverage_table[model][str(tau)] = round(float(actual_below), 6)

    results['coverage_table'] = coverage_table

    # Print coverage summary
    header = f"{'Model':<15}" + "".join(f"{'τ=' + str(t):<10}" for t in TAUS)
    print(f"  {header}")
    print(f"  {'Nominal':<15}" + "".join(f"{t:<10.4f}" for t in TAUS))
    for model in model_names:
        row = f"  {model:<15}"
        for tau in TAUS:
            val = coverage_table[model].get(str(tau))
            if val is not None:
                row += f"{val:<10.4f}"
            else:
                row += f"{'N/A':<10}"
        print(row)

    # 3b. Pinball Loss table
    print("\n  --- Pinball (Tick) Loss (lower is better) ---")
    pinball_table = {}
    pinball_pw = {}  # pointwise, for DM test
    for model in model_names:
        pinball_table[model] = {}
        pinball_pw[model] = {}
        for tau in TAUS:
            q = quantile_forecasts[model][tau]
            mask = valid & np.isfinite(q)
            if mask.sum() < 10:
                pinball_table[model][str(tau)] = None
                continue
            pl = pinball_loss(oos_returns[mask], q[mask], tau)
            pinball_table[model][str(tau)] = round(pl, 8)
            pinball_pw[model][str(tau)] = pointwise_pinball(
                oos_returns[mask], q[mask], tau)

    results['pinball_loss_table'] = pinball_table

    header = f"{'Model':<15}" + "".join(f"{'τ=' + str(t):<12}" for t in TAUS)
    print(f"  {header}")
    for model in model_names:
        row = f"  {model:<15}"
        for tau in TAUS:
            val = pinball_table[model].get(str(tau))
            if val is not None:
                row += f"{val:<12.6f}"
            else:
                row += f"{'N/A':<12}"
        print(row)

    # 3c. Average pinball loss across all quantiles (summary metric)
    print("\n  --- Average Pinball Loss (across all τ) ---")
    avg_pinball = {}
    for model in model_names:
        vals = [pinball_table[model].get(str(t)) for t in TAUS
                if pinball_table[model].get(str(t)) is not None]
        avg_pinball[model] = round(float(np.mean(vals)), 8) if vals else None
        print(f"  {model:<15} {avg_pinball[model]}")
    results['avg_pinball_loss'] = avg_pinball

    # 3d. VaR 1% backtest
    print("\n  --- VaR 1% Backtest (Kupiec + Christoffersen + Basel) ---")
    var_results = {}
    for model in model_names:
        q01 = quantile_forecasts[model][0.01]
        mask = valid & np.isfinite(q01)
        if mask.sum() < 50:
            var_results[model] = None
            continue
        vbt = var_backtest(oos_returns[mask], q01[mask], alpha_var=0.01)
        var_results[model] = vbt
        status = "PASS" if vbt['trinity_pass'] else "FAIL"
        print(f"  {model:<15} violations={vbt['n_violations']}/{vbt['n_total']} "
              f"({vbt['violation_rate']:.4f}) "
              f"Kupiec p={vbt['kupiec']['p_value']:.4f} "
              f"Christ. p={vbt['christoffersen']['p_value']:.4f} "
              f"Basel={vbt['basel_traffic_light']} "
              f"→ {status}")

    results['var_1pct_backtest'] = var_results

    # 3e. VaR 5% backtest
    print("\n  --- VaR 5% Backtest ---")
    var5_results = {}
    for model in model_names:
        q05 = quantile_forecasts[model][0.05]
        mask = valid & np.isfinite(q05)
        if mask.sum() < 50:
            var5_results[model] = None
            continue
        vbt5 = var_backtest(oos_returns[mask], q05[mask], alpha_var=0.05)
        var5_results[model] = vbt5
        status = "PASS" if vbt5['trinity_pass'] else "FAIL"
        print(f"  {model:<15} violations={vbt5['n_violations']}/{vbt5['n_total']} "
              f"({vbt5['violation_rate']:.4f}) "
              f"Kupiec p={vbt5['kupiec']['p_value']:.4f} "
              f"→ {status}")

    results['var_5pct_backtest'] = var5_results

    # 3f. Winkler Score for prediction intervals
    print("\n  --- Winkler Score (prediction interval quality, lower is better) ---")
    intervals = [(0.01, 0.99, 0.02), (0.05, 0.95, 0.10), (0.10, 0.90, 0.20)]
    winkler_results = {}
    for model in model_names:
        winkler_results[model] = {}
        for lo_tau, hi_tau, alpha in intervals:
            q_lo = quantile_forecasts[model][lo_tau]
            q_hi = quantile_forecasts[model][hi_tau]
            mask = valid & np.isfinite(q_lo) & np.isfinite(q_hi)
            if mask.sum() < 50:
                winkler_results[model][f'{lo_tau}-{hi_tau}'] = None
                continue
            ws = winkler_score(oos_returns[mask], q_lo[mask], q_hi[mask], alpha)
            winkler_results[model][f'{lo_tau}-{hi_tau}'] = round(ws, 8)

    results['winkler_scores'] = winkler_results

    header = f"{'Model':<15}" + "".join(f"{'[' + str(lo) + ',' + str(hi) + ']':<15}"
                                        for lo, hi, _ in intervals)
    print(f"  {header}")
    for model in model_names:
        row = f"  {model:<15}"
        for lo_tau, hi_tau, alpha in intervals:
            val = winkler_results[model].get(f'{lo_tau}-{hi_tau}')
            if val is not None:
                row += f"{val:<15.6f}"
            else:
                row += f"{'N/A':<15}"
        print(row)

    # ----------------------------------------------------------
    # 4. DM tests on pinball loss (M3 vs each baseline, per tau)
    # ----------------------------------------------------------
    print("\n[4/5] DM tests (pinball loss, M3_QuantReg vs baselines)...")

    dm_results = {}
    for baseline in ['M1_Normal', 'M2_StudentT', 'M4_HistSim']:
        dm_results[f'M3_vs_{baseline}'] = {}
        for tau in TAUS:
            pw3 = pinball_pw.get('M3_QuantReg', {}).get(str(tau))
            pwb = pinball_pw.get(baseline, {}).get(str(tau))
            if pw3 is None or pwb is None:
                dm_results[f'M3_vs_{baseline}'][str(tau)] = None
                continue
            # Align lengths
            min_n = min(len(pw3), len(pwb))
            t_stat, p_val = dm_test(pw3[:min_n], pwb[:min_n])
            dm_results[f'M3_vs_{baseline}'][str(tau)] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'significant_harvey': bool(abs(t_stat) > 3.0),
                'winner': 'M3_QuantReg' if t_stat < 0 else baseline
            }
            sig_mark = "***" if abs(t_stat) > 3.0 else ("**" if p_val < 0.05 else "")
            print(f"  M3 vs {baseline:<15} τ={tau}: "
                  f"DM t={t_stat:+.3f} p={p_val:.4f} "
                  f"{'→ M3 wins' if t_stat < 0 else '→ ' + baseline + ' wins'} "
                  f"{sig_mark}")

    results['dm_tests'] = dm_results

    # Also DM: M2_StudentT vs M1_Normal (expected: M2 wins at tails)
    dm_m2_vs_m1 = {}
    for tau in TAUS:
        pw2 = pinball_pw.get('M2_StudentT', {}).get(str(tau))
        pw1 = pinball_pw.get('M1_Normal', {}).get(str(tau))
        if pw2 is None or pw1 is None:
            dm_m2_vs_m1[str(tau)] = None
            continue
        min_n = min(len(pw2), len(pw1))
        t_stat, p_val = dm_test(pw2[:min_n], pw1[:min_n])
        dm_m2_vs_m1[str(tau)] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant_harvey': bool(abs(t_stat) > 3.0),
            'winner': 'M2_StudentT' if t_stat < 0 else 'M1_Normal'
        }
    results['dm_tests']['M2_vs_M1'] = dm_m2_vs_m1
    print("\n  M2_StudentT vs M1_Normal:")
    for tau in TAUS:
        d = dm_m2_vs_m1.get(str(tau))
        if d:
            print(f"    τ={tau}: DM t={d['t_stat']:+.3f} p={d['p_value']:.4f} → {d['winner']}")

    # ----------------------------------------------------------
    # 5. Summary & Ranking
    # ----------------------------------------------------------
    print("\n[5/5] Summary ranking...")

    # Coverage deviation: sum of |actual - nominal| across all τ
    coverage_deviation = {}
    for model in model_names:
        devs = []
        for tau in TAUS:
            val = coverage_table[model].get(str(tau))
            if val is not None:
                devs.append(abs(val - tau))
        coverage_deviation[model] = round(float(np.mean(devs)), 6) if devs else None

    results['coverage_deviation'] = coverage_deviation

    print("\n  === FINAL RANKING ===")
    print(f"  {'Model':<15} {'Avg Pinball':<14} {'Cov. Dev.':<12} {'VaR 1%':<10} {'VaR 5%':<10}")
    for model in model_names:
        ap = avg_pinball.get(model, None)
        cd = coverage_deviation.get(model, None)
        v1 = 'PASS' if (var_results.get(model) and var_results[model].get('trinity_pass')) else 'FAIL'
        v5 = 'PASS' if (var5_results.get(model) and var5_results[model].get('trinity_pass')) else 'FAIL'
        ap_str = f"{ap:.6f}" if ap is not None else "N/A"
        cd_str = f"{cd:.6f}" if cd is not None else "N/A"
        print(f"  {model:<15} {ap_str:<14} {cd_str:<12} {v1:<10} {v5:<10}")

    # Best model per criterion
    best_pinball = min(
        [(m, avg_pinball[m]) for m in model_names if avg_pinball.get(m) is not None],
        key=lambda x: x[1]
    )
    best_coverage = min(
        [(m, coverage_deviation[m]) for m in model_names if coverage_deviation.get(m) is not None],
        key=lambda x: x[1]
    )
    var_pass_models = [m for m in model_names
                       if var_results.get(m) and var_results[m].get('trinity_pass')]

    results['summary'] = {
        'best_pinball_loss': {'model': best_pinball[0], 'value': best_pinball[1]},
        'best_coverage': {'model': best_coverage[0], 'value': best_coverage[1]},
        'var_1pct_pass_models': var_pass_models,
        'var_5pct_pass_models': [m for m in model_names
                                 if var5_results.get(m) and var5_results[m].get('trinity_pass')],
    }

    # Key finding
    print(f"\n  Best pinball loss: {best_pinball[0]} ({best_pinball[1]:.6f})")
    print(f"  Best coverage calibration: {best_coverage[0]} ({best_coverage[1]:.6f})")
    print(f"  VaR 1% PASS: {var_pass_models if var_pass_models else 'NONE'}")

    # GJR params summary
    if gjr_params:
        results['final_gjr_params'] = {k: round(v, 6) for k, v in gjr_params.items()}
        results['student_t_df'] = round(t_df, 2)

    results['elapsed_seconds'] = round(time.time() - t0, 1)

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    print(f"  Total elapsed: {results['elapsed_seconds']}s")
    print("=" * 70)

    return results


if __name__ == '__main__':
    main()
