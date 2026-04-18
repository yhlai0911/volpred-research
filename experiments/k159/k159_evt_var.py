#!/usr/bin/env python3
"""
K159: EVT-VaR — Extreme Value Theory with Peaks-over-Threshold for Tail Risk
=============================================================================
[提出: research_program.md, 執行: Claude]

Research Question:
  Does Extreme Value Theory (Peaks-over-Threshold + GPD) improve VaR/ES
  estimation vs GARCH-Normal and GARCH-Student-t, especially in the deep
  tails (1% and 2.5%)?

Method:
  1. Fit GJR-GARCH(1,1) to each rolling window to get conditional sigma
     and standardised residuals z_t = r_t / sigma_t.
  2. Three VaR/ES models on the standardised residuals:
     A) Normal   — VaR = mu + sigma * Phi^{-1}(alpha)
     B) Student-t — MLE fit df; VaR from t-distribution quantile
     C) EVT-GPD  — Peaks-over-Threshold at 90th percentile of losses,
                    fit Generalized Pareto Distribution to exceedances,
                    invert survival function for VaR/ES
  3. Rolling OOS: window=2000, OOS 2023-01-01 to 2024-12-31
  4. Assets: SPY, QQQ, GLD, EEM, TLT, 0050.TW
  5. Evaluation: Kupiec, Christoffersen, DQ test, violation rate, ES backtest

Statistical constraints (research_program.md):
  - GARCH window >= 500 (using 2000)
  - OOS >= 252 days
  - Harvey threshold t > 3.0 for significance claims
  - Re-estimate each window (no lookahead)

Author: VolPred Research System
Date: 2026-03-23
"""

import json
import os
import sys
import time
import traceback
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.stats import genpareto

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
ASSETS = ["SPY", "QQQ", "GLD", "EEM", "TLT", "0050.TW"]
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2010-01-01"      # enough history for w=2000 before OOS
ALPHA_LEVELS = [0.01, 0.025]   # 1% and 2.5% VaR
POT_THRESHOLD_QUANTILE = 0.90  # 90th percentile of losses for POT
SEED = 42
RE_ESTIMATE_EVERY = 21         # re-estimate GARCH every 21 days (monthly)

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "k159_evt_var_results.json"

np.random.seed(SEED)

print("=" * 80)
print("K159: EVT-VaR — Extreme Value Theory for Tail Risk Estimation")
print("    POT + Generalized Pareto Distribution vs GARCH-Normal / GARCH-t")
print("=" * 80)
print(f"  Assets:  {ASSETS}")
print(f"  Window:  {WINDOW}")
print(f"  OOS:     {OOS_START} to {OOS_END}")
print(f"  Alphas:  {ALPHA_LEVELS}")
print(f"  POT threshold: {POT_THRESHOLD_QUANTILE*100:.0f}th percentile of losses")
print()


# ============================================================================
# Data Loading
# ============================================================================
def load_data(ticker, start=DATA_START, end="2025-06-01"):
    """Download daily data via yfinance."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.sort_index()
    return df


# ============================================================================
# EVT-GPD Functions
# ============================================================================
def fit_gpd_pot(losses, threshold_quantile=0.90):
    """
    Fit Generalized Pareto Distribution to exceedances over threshold.

    Parameters
    ----------
    losses : array-like
        Positive loss values (= -returns for the left tail).
    threshold_quantile : float
        Quantile of losses to use as threshold.

    Returns
    -------
    dict with keys: xi (shape), sigma (scale), threshold, n_exceed, n_total
    """
    losses = np.asarray(losses)
    threshold = np.quantile(losses, threshold_quantile)

    exceedances = losses[losses > threshold] - threshold
    n_exceed = len(exceedances)
    n_total = len(losses)

    if n_exceed < 20:
        # Not enough exceedances — fallback
        return None

    # Fit GPD using scipy.stats.genpareto (MLE)
    # genpareto parameterisation: F(x) = 1 - (1 + xi*x/sigma)^{-1/xi}
    try:
        xi, loc, sigma = genpareto.fit(exceedances, floc=0)  # fix location=0
    except Exception:
        return None

    return {
        'xi': xi,       # shape parameter
        'sigma': sigma,  # scale parameter
        'threshold': threshold,
        'n_exceed': n_exceed,
        'n_total': n_total,
    }


def evt_var_es(gpd_params, alpha):
    """
    Compute VaR and ES from GPD tail model.

    For standardised residuals z, losses = -z.
    VaR_alpha = u + (sigma/xi) * ((n/Nu * alpha)^{-xi} - 1)
    ES_alpha  = VaR_alpha / (1 - xi) + (sigma - xi*u) / (1 - xi)

    Parameters
    ----------
    gpd_params : dict from fit_gpd_pot
    alpha : float (e.g. 0.01)

    Returns
    -------
    (VaR_loss, ES_loss) — both are positive numbers representing loss magnitudes
    """
    xi = gpd_params['xi']
    sigma = gpd_params['sigma']
    u = gpd_params['threshold']
    Nu = gpd_params['n_exceed']
    n = gpd_params['n_total']

    # Exceedance probability
    Fu = Nu / n  # fraction above threshold

    # VaR (loss scale, positive)
    var_loss = u + (sigma / xi) * ((Fu / alpha) ** xi - 1)

    # ES (loss scale, positive)
    if xi < 1.0:
        es_loss = var_loss / (1 - xi) + (sigma - xi * u) / (1 - xi)
    else:
        es_loss = var_loss * 1.5  # fallback if xi >= 1 (infinite mean)

    return float(var_loss), float(es_loss)


# ============================================================================
# Student-t MLE for standardised residuals
# ============================================================================
def fit_student_t(residuals):
    """
    Fit Student-t distribution to standardised residuals via MLE.
    Returns (df, loc, scale).
    """
    try:
        df_fit, loc_fit, scale_fit = stats.t.fit(residuals)
        # Ensure df is reasonable
        if df_fit < 2.1:
            df_fit = 2.1
        if df_fit > 100:
            df_fit = 100
        return df_fit, loc_fit, scale_fit
    except Exception:
        return 5.0, 0.0, 1.0  # fallback


# ============================================================================
# VaR / ES Computation for each model
# ============================================================================
def compute_var_es_normal(sigma_t, alpha):
    """Normal VaR/ES. Returns (VaR, ES) as negative numbers (losses)."""
    z_alpha = stats.norm.ppf(alpha)
    var = sigma_t * z_alpha
    # ES for normal
    es = sigma_t * (-stats.norm.pdf(z_alpha) / alpha)
    return var, -es  # both negative (loss side)


def compute_var_es_t(sigma_t, df, loc, scale, alpha):
    """Student-t VaR/ES. Returns (VaR, ES) as negative numbers."""
    z_alpha = stats.t.ppf(alpha, df, loc=loc, scale=scale)
    var = sigma_t * z_alpha
    # ES for Student-t
    t_pdf = stats.t.pdf(z_alpha, df, loc=loc, scale=scale)
    es_z = -scale * (df + z_alpha**2) / (df - 1) * t_pdf / alpha + loc
    es = sigma_t * es_z
    return var, es


def compute_var_es_evt(sigma_t, gpd_params, alpha):
    """EVT-GPD VaR/ES. Returns (VaR, ES) as negative numbers."""
    if gpd_params is None:
        # Fallback to Normal
        return compute_var_es_normal(sigma_t, alpha)

    var_loss, es_loss = evt_var_es(gpd_params, alpha)
    # Convert from loss scale (positive) to return scale (negative)
    var = -sigma_t * var_loss
    es = -sigma_t * es_loss
    return var, es


# ============================================================================
# Backtesting Functions
# ============================================================================
def kupiec_test(violations, n_obs, alpha):
    """
    Kupiec (1995) unconditional coverage test.
    H0: violation rate = alpha
    Returns: (LR_uc, p_value)
    """
    v = np.sum(violations)
    T = n_obs
    pi_hat = v / T if T > 0 else 0

    if v == 0 or v == T:
        return 0.0, 1.0

    # LR statistic
    lr = 2 * (v * np.log(pi_hat / alpha) + (T - v) * np.log((1 - pi_hat) / (1 - alpha)))
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(p_value)


def christoffersen_test(violations):
    """
    Christoffersen (1998) conditional coverage test (independence + coverage).
    H0: violations are iid Bernoulli(alpha)
    Returns: (LR_cc, p_value)
    """
    violations = np.asarray(violations, dtype=int)
    T = len(violations)

    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for i in range(1, T):
        if violations[i-1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i-1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i-1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1

    # Independence test
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0

    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    pi_hat = (n01 + n11) / T

    if pi01 <= 0 or pi01 >= 1:
        return 0.0, 1.0
    if pi11 <= 0 or pi11 >= 1:
        # Only one transition type
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi_hat) + (n01 + n11) * np.log(pi_hat)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )

    p_value = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(p_value)


def dq_test(violations, returns, var_forecasts, n_lags=4):
    """
    Dynamic Quantile (DQ) test — Engle & Manganelli (2004).
    Regress hit_t - alpha on lagged hits and VaR.
    H0: no predictability in violations.
    Returns: (DQ_stat, p_value)
    """
    import statsmodels.api as sm

    violations = np.asarray(violations, dtype=float)
    T = len(violations)
    alpha_val = np.mean(violations)

    hit = violations - alpha_val  # centered hits

    # Build regressors: lagged hits + VaR
    X = []
    y = []
    for t in range(n_lags, T):
        row = [hit[t - j] for j in range(1, n_lags + 1)]
        row.append(var_forecasts[t])
        X.append(row)
        y.append(hit[t])

    X = np.array(X)
    y = np.array(y)
    X = sm.add_constant(X)

    try:
        model = sm.OLS(y, X).fit()
        dq_stat = float(model.fvalue)
        dq_pval = float(model.f_pvalue)
    except Exception:
        dq_stat = 0.0
        dq_pval = 1.0

    return dq_stat, dq_pval


def es_backtest_z2(returns, var_forecasts, es_forecasts, alpha):
    """
    Acerbi-Szekely Z2 test for Expected Shortfall.
    Z2 = (1/(T*alpha)) * sum_t (r_t * I(r_t < VaR_t) / ES_t) + 1
    Under H0 (correct ES): E[Z2] = 0
    Negative Z2 => ES underestimated (too optimistic).
    Bootstrap p-value.
    """
    returns = np.asarray(returns)
    var_forecasts = np.asarray(var_forecasts)
    es_forecasts = np.asarray(es_forecasts)
    T = len(returns)

    violations = returns < var_forecasts
    n_viol = np.sum(violations)

    if n_viol == 0:
        return {'z2': np.nan, 'p_value': np.nan, 'n_violations': 0}

    # Compute Z2
    z2 = (1 / (T * alpha)) * np.sum(returns[violations] / es_forecasts[violations]) + 1

    # Bootstrap p-value
    n_boot = 2000
    z2_boot = np.zeros(n_boot)
    rng = np.random.RandomState(SEED)
    for b in range(n_boot):
        idx = rng.choice(T, size=T, replace=True)
        r_b = returns[idx]
        var_b = var_forecasts[idx]
        es_b = es_forecasts[idx]
        viol_b = r_b < var_b
        if np.sum(viol_b) == 0:
            z2_boot[b] = 0
        else:
            z2_boot[b] = (1 / (T * alpha)) * np.sum(r_b[viol_b] / es_b[viol_b]) + 1

    p_value = float(np.mean(z2_boot <= z2))

    return {
        'z2': float(z2),
        'p_value': p_value,
        'n_violations': int(n_viol),
    }


# ============================================================================
# Main Rolling Evaluation
# ============================================================================
def run_asset(ticker):
    """Run the full rolling EVT-VaR evaluation for one asset."""
    print(f"\n{'='*70}")
    print(f"  Processing: {ticker}")
    print(f"{'='*70}")

    # Load data
    df = load_data(ticker)
    if df is None or len(df) < WINDOW + 252:
        print(f"  [SKIP] Not enough data for {ticker}")
        return None

    # Compute log returns (percentage)
    df['returns'] = np.log(df['Close'] / df['Close'].shift(1)) * 100
    df = df.dropna(subset=['returns'])

    # Find OOS range
    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_dates = df.index[oos_mask]
    if len(oos_dates) < 100:
        print(f"  [SKIP] OOS too short for {ticker}: {len(oos_dates)} days")
        return None

    print(f"  Total data points: {len(df)}")
    print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')} ({len(oos_dates)} days)")

    returns_all = df['returns'].values
    dates_all = df.index

    # Locate OOS indices
    oos_start_idx = np.where(dates_all >= pd.Timestamp(OOS_START))[0][0]
    oos_end_idx = np.where(dates_all <= pd.Timestamp(OOS_END))[0][-1]

    n_oos = oos_end_idx - oos_start_idx + 1
    print(f"  OOS index range: {oos_start_idx} to {oos_end_idx} ({n_oos} days)")

    # Storage for forecasts
    results_by_alpha = {}

    for alpha in ALPHA_LEVELS:
        var_normal = np.full(n_oos, np.nan)
        var_t = np.full(n_oos, np.nan)
        var_evt = np.full(n_oos, np.nan)
        es_normal = np.full(n_oos, np.nan)
        es_t = np.full(n_oos, np.nan)
        es_evt = np.full(n_oos, np.nan)
        oos_returns = np.full(n_oos, np.nan)

        # Track GARCH estimation
        last_garch_result = None
        last_t_params = None
        last_gpd_params = None
        last_estimate_idx = -999

        t0 = time.time()

        for i in range(n_oos):
            t_idx = oos_start_idx + i
            window_start = t_idx - WINDOW
            if window_start < 0:
                continue

            oos_returns[i] = returns_all[t_idx]
            window_returns = returns_all[window_start:t_idx]

            # Re-estimate GARCH periodically
            if (i - last_estimate_idx) >= RE_ESTIMATE_EVERY or last_garch_result is None:
                try:
                    am = arch_model(
                        window_returns, vol='GARCH', p=1, o=1, q=1,
                        mean='Constant', dist='normal'
                    )
                    res = am.fit(disp='off', show_warning=False)
                    last_garch_result = res
                    last_estimate_idx = i

                    # Get standardised residuals
                    std_resid = res.resid / res.conditional_volatility
                    std_resid = std_resid[~np.isnan(std_resid)]

                    # Fit Student-t to standardised residuals
                    last_t_params = fit_student_t(std_resid)

                    # Fit GPD to losses (= -std_resid for left tail)
                    losses = -std_resid  # positive = large losses
                    last_gpd_params = fit_gpd_pot(losses, POT_THRESHOLD_QUANTILE)

                except Exception:
                    if last_garch_result is None:
                        continue

            # Forecast 1-step ahead volatility
            try:
                forecast = last_garch_result.forecast(horizon=1)
                sigma_t = np.sqrt(forecast.variance.iloc[-1, 0])
            except Exception:
                # Fallback: use last conditional vol
                sigma_t = last_garch_result.conditional_volatility.iloc[-1]

            if np.isnan(sigma_t) or sigma_t <= 0:
                sigma_t = np.std(window_returns)

            # Model A: Normal VaR/ES
            v_n, e_n = compute_var_es_normal(sigma_t, alpha)
            var_normal[i] = v_n
            es_normal[i] = e_n

            # Model B: Student-t VaR/ES
            if last_t_params is not None:
                df_t, loc_t, scale_t = last_t_params
                v_t, e_t = compute_var_es_t(sigma_t, df_t, loc_t, scale_t, alpha)
                var_t[i] = v_t
                es_t[i] = e_t
            else:
                var_t[i] = v_n
                es_t[i] = e_n

            # Model C: EVT-GPD VaR/ES
            v_e, e_e = compute_var_es_evt(sigma_t, last_gpd_params, alpha)
            var_evt[i] = v_e
            es_evt[i] = e_e

        elapsed = time.time() - t0
        print(f"  Alpha={alpha:.3f}: {elapsed:.1f}s")

        # Remove NaN entries
        valid = ~np.isnan(oos_returns) & ~np.isnan(var_normal) & ~np.isnan(var_t) & ~np.isnan(var_evt)
        oos_ret = oos_returns[valid]
        v_norm = var_normal[valid]
        v_stud = var_t[valid]
        v_evt_ = var_evt[valid]
        e_norm = es_normal[valid]
        e_stud = es_t[valid]
        e_evt_ = es_evt[valid]

        n_valid = len(oos_ret)
        print(f"    Valid OOS observations: {n_valid}")

        if n_valid < 100:
            print(f"    [SKIP alpha={alpha}] Too few valid observations")
            continue

        # Compute violations
        viol_normal = (oos_ret < v_norm).astype(int)
        viol_t = (oos_ret < v_stud).astype(int)
        viol_evt = (oos_ret < v_evt_).astype(int)

        vr_normal = np.mean(viol_normal)
        vr_t = np.mean(viol_t)
        vr_evt = np.mean(viol_evt)

        print(f"    Violation rates: Normal={vr_normal:.4f}, Student-t={vr_t:.4f}, EVT={vr_evt:.4f} (expected={alpha:.4f})")

        # Kupiec tests
        ku_norm = kupiec_test(viol_normal, n_valid, alpha)
        ku_t = kupiec_test(viol_t, n_valid, alpha)
        ku_evt = kupiec_test(viol_evt, n_valid, alpha)

        # Christoffersen tests
        cc_norm = christoffersen_test(viol_normal)
        cc_t = christoffersen_test(viol_t)
        cc_evt = christoffersen_test(viol_evt)

        # DQ tests
        dq_norm = dq_test(viol_normal, oos_ret, v_norm)
        dq_t = dq_test(viol_t, oos_ret, v_stud)
        dq_evt = dq_test(viol_evt, oos_ret, v_evt_)

        # ES backtests (Z2)
        es_bt_norm = es_backtest_z2(oos_ret, v_norm, e_norm, alpha)
        es_bt_t = es_backtest_z2(oos_ret, v_stud, e_stud, alpha)
        es_bt_evt = es_backtest_z2(oos_ret, v_evt_, e_evt_, alpha)

        # Summary for this alpha
        alpha_results = {
            'n_oos': n_valid,
            'expected_alpha': alpha,
            'models': {
                'Normal': {
                    'violation_rate': float(vr_normal),
                    'n_violations': int(np.sum(viol_normal)),
                    'kupiec': {'LR': ku_norm[0], 'p_value': ku_norm[1], 'pass': ku_norm[1] > 0.05},
                    'christoffersen': {'LR': cc_norm[0], 'p_value': cc_norm[1], 'pass': cc_norm[1] > 0.05},
                    'dq_test': {'F_stat': dq_norm[0], 'p_value': dq_norm[1], 'pass': dq_norm[1] > 0.05},
                    'es_backtest': es_bt_norm,
                },
                'Student-t': {
                    'violation_rate': float(vr_t),
                    'n_violations': int(np.sum(viol_t)),
                    'kupiec': {'LR': ku_t[0], 'p_value': ku_t[1], 'pass': ku_t[1] > 0.05},
                    'christoffersen': {'LR': cc_t[0], 'p_value': cc_t[1], 'pass': cc_t[1] > 0.05},
                    'dq_test': {'F_stat': dq_t[0], 'p_value': dq_t[1], 'pass': dq_t[1] > 0.05},
                    'es_backtest': es_bt_t,
                },
                'EVT-GPD': {
                    'violation_rate': float(vr_evt),
                    'n_violations': int(np.sum(viol_evt)),
                    'kupiec': {'LR': ku_evt[0], 'p_value': ku_evt[1], 'pass': ku_evt[1] > 0.05},
                    'christoffersen': {'LR': cc_evt[0], 'p_value': cc_evt[1], 'pass': cc_evt[1] > 0.05},
                    'dq_test': {'F_stat': dq_evt[0], 'p_value': dq_evt[1], 'pass': dq_evt[1] > 0.05},
                    'es_backtest': es_bt_evt,
                },
            }
        }

        # GPD parameters (last window)
        if last_gpd_params is not None:
            alpha_results['gpd_params'] = {
                'xi': float(last_gpd_params['xi']),
                'sigma': float(last_gpd_params['sigma']),
                'threshold': float(last_gpd_params['threshold']),
                'n_exceed': int(last_gpd_params['n_exceed']),
            }

        if last_t_params is not None:
            alpha_results['t_params'] = {
                'df': float(last_t_params[0]),
                'loc': float(last_t_params[1]),
                'scale': float(last_t_params[2]),
            }

        results_by_alpha[str(alpha)] = alpha_results

    return results_by_alpha


# ============================================================================
# Main
# ============================================================================
def main():
    all_results = {}
    start_time = time.time()

    for ticker in ASSETS:
        try:
            res = run_asset(ticker)
            if res is not None:
                all_results[ticker] = res
        except Exception as e:
            print(f"\n  [ERROR] {ticker}: {e}")
            traceback.print_exc()
            continue

    elapsed_total = time.time() - start_time

    # ========================================================================
    # Summary Table
    # ========================================================================
    print("\n\n")
    print("=" * 100)
    print("K159: EVT-VaR RESULTS SUMMARY")
    print("=" * 100)

    # Count passes across assets and alphas
    summary_counts = {}
    for model_name in ['Normal', 'Student-t', 'EVT-GPD']:
        summary_counts[model_name] = {
            'kupiec_pass': 0, 'kupiec_total': 0,
            'cc_pass': 0, 'cc_total': 0,
            'dq_pass': 0, 'dq_total': 0,
            'trinity_pass': 0, 'trinity_total': 0,
            'viol_rates': [],
        }

    for ticker, asset_res in all_results.items():
        for alpha_str, alpha_res in asset_res.items():
            alpha = float(alpha_str)
            n_oos = alpha_res['n_oos']

            print(f"\n--- {ticker} | alpha={alpha:.3f} | OOS={n_oos} days ---")
            header = f"{'Model':<12} {'Viol%':>7} {'#Viol':>6} {'Kupiec':>10} {'CC':>10} {'DQ':>10} {'ES-Z2':>8} {'Trinity':>8}"
            print(header)
            print("-" * len(header))

            for model_name in ['Normal', 'Student-t', 'EVT-GPD']:
                m = alpha_res['models'][model_name]
                vr = m['violation_rate']
                nv = m['n_violations']
                ku_pass = "PASS" if m['kupiec']['pass'] else "FAIL"
                cc_pass = "PASS" if m['christoffersen']['pass'] else "FAIL"
                dq_pass = "PASS" if m['dq_test']['pass'] else "FAIL"

                es_z2 = m['es_backtest']['z2']
                es_str = f"{es_z2:.3f}" if not np.isnan(es_z2) else "N/A"

                trinity = m['kupiec']['pass'] and m['christoffersen']['pass'] and m['dq_test']['pass']
                trinity_str = "3/3" if trinity else f"{'1' if m['kupiec']['pass'] else '0'}+{'1' if m['christoffersen']['pass'] else '0'}+{'1' if m['dq_test']['pass'] else '0'}"

                print(f"{model_name:<12} {vr:>7.4f} {nv:>6d} {ku_pass:>10} {cc_pass:>10} {dq_pass:>10} {es_str:>8} {trinity_str:>8}")

                # Accumulate summary
                sc = summary_counts[model_name]
                sc['kupiec_total'] += 1
                sc['cc_total'] += 1
                sc['dq_total'] += 1
                sc['trinity_total'] += 1
                if m['kupiec']['pass']:
                    sc['kupiec_pass'] += 1
                if m['christoffersen']['pass']:
                    sc['cc_pass'] += 1
                if m['dq_test']['pass']:
                    sc['dq_pass'] += 1
                if trinity:
                    sc['trinity_pass'] += 1
                sc['viol_rates'].append((alpha, vr))

    # ========================================================================
    # Aggregate Summary
    # ========================================================================
    print("\n\n")
    print("=" * 80)
    print("AGGREGATE SUMMARY (across all assets and alpha levels)")
    print("=" * 80)
    print(f"{'Model':<12} {'Kupiec':>12} {'Christoff':>12} {'DQ':>12} {'Trinity':>12}")
    print("-" * 60)

    for model_name in ['Normal', 'Student-t', 'EVT-GPD']:
        sc = summary_counts[model_name]
        kt = sc['kupiec_total']
        kp = sc['kupiec_pass']
        ct = sc['cc_total']
        cp = sc['cc_pass']
        dt = sc['dq_total']
        dp = sc['dq_pass']
        tt = sc['trinity_total']
        tp = sc['trinity_pass']
        print(f"{model_name:<12} {kp}/{kt:>3}      {cp}/{ct:>3}      {dp}/{dt:>3}      {tp}/{tt:>3}")

    # ========================================================================
    # Violation Rate Analysis
    # ========================================================================
    print("\n\nVIOLATION RATE ANALYSIS (closer to expected = better):")
    print(f"{'Model':<12} {'Alpha':>6} {'Mean VR':>9} {'Median VR':>10} {'Abs Err':>9}")
    print("-" * 50)

    for alpha in ALPHA_LEVELS:
        for model_name in ['Normal', 'Student-t', 'EVT-GPD']:
            sc = summary_counts[model_name]
            rates = [vr for (a, vr) in sc['viol_rates'] if a == alpha]
            if rates:
                mean_vr = np.mean(rates)
                median_vr = np.median(rates)
                abs_err = abs(mean_vr - alpha)
                print(f"{model_name:<12} {alpha:>6.3f} {mean_vr:>9.4f} {median_vr:>10.4f} {abs_err:>9.4f}")

    # ========================================================================
    # Star Rating
    # ========================================================================
    evt_kupiec = summary_counts['EVT-GPD']['kupiec_pass']
    evt_trinity = summary_counts['EVT-GPD']['trinity_pass']
    normal_kupiec = summary_counts['Normal']['kupiec_pass']
    t_kupiec = summary_counts['Student-t']['kupiec_pass']
    total_tests = summary_counts['EVT-GPD']['kupiec_total']

    # Rate based on EVT improvement over baselines
    evt_advantage = evt_kupiec - max(normal_kupiec, t_kupiec)

    if evt_advantage >= 2 and evt_trinity >= total_tests * 0.6:
        star_rating = 3
        star_str = "★★★"
        verdict = "EVT-GPD significantly improves tail risk estimation"
    elif evt_kupiec >= normal_kupiec and evt_kupiec >= t_kupiec:
        star_rating = 2
        star_str = "★★"
        verdict = "EVT-GPD competitive/mixed results vs baselines"
    else:
        star_rating = 1
        star_str = "★"
        verdict = "EVT-GPD does not clearly improve over simpler methods"

    # Check if any model dominates
    print(f"\n\n{'='*80}")
    print(f"VERDICT: {star_str} — {verdict}")
    print(f"{'='*80}")
    print(f"  EVT-GPD Kupiec pass: {evt_kupiec}/{total_tests}")
    print(f"  Normal  Kupiec pass: {normal_kupiec}/{total_tests}")
    print(f"  Student-t Kupiec pass: {t_kupiec}/{total_tests}")
    print(f"  EVT-GPD Trinity pass: {evt_trinity}/{total_tests}")

    # Additional insights
    # Check if EVT is better at deeper tails (1% vs 2.5%)
    for alpha in ALPHA_LEVELS:
        evt_rates = [vr for (a, vr) in summary_counts['EVT-GPD']['viol_rates'] if a == alpha]
        norm_rates = [vr for (a, vr) in summary_counts['Normal']['viol_rates'] if a == alpha]
        if evt_rates and norm_rates:
            evt_err = np.mean([abs(vr - alpha) for vr in evt_rates])
            norm_err = np.mean([abs(vr - alpha) for vr in norm_rates])
            print(f"\n  Alpha={alpha:.3f}: Mean absolute VR error — EVT={evt_err:.4f}, Normal={norm_err:.4f}")
            if evt_err < norm_err:
                print(f"    -> EVT better calibrated at {alpha:.1%} level")
            else:
                print(f"    -> Normal better calibrated at {alpha:.1%} level")

    # ========================================================================
    # Findings
    # ========================================================================
    findings = []

    # Finding 1: Overall comparison
    findings.append(
        f"EVT-GPD Kupiec pass rate: {evt_kupiec}/{total_tests} "
        f"vs Normal {normal_kupiec}/{total_tests}, Student-t {t_kupiec}/{total_tests}"
    )

    # Finding 2: Trinity test
    findings.append(
        f"EVT-GPD Trinity (Kupiec+CC+DQ) pass rate: {evt_trinity}/{total_tests}"
    )

    # Finding 3: Per-alpha analysis
    for alpha in ALPHA_LEVELS:
        evt_rates = [vr for (a, vr) in summary_counts['EVT-GPD']['viol_rates'] if a == alpha]
        if evt_rates:
            mean_vr = np.mean(evt_rates)
            findings.append(f"At {alpha:.1%}: EVT mean violation rate = {mean_vr:.4f} (expected {alpha:.4f})")

    # Finding 4: GPD shape parameters
    xi_values = []
    for ticker, asset_res in all_results.items():
        for alpha_str, alpha_res in asset_res.items():
            if 'gpd_params' in alpha_res:
                xi_values.append((ticker, alpha_res['gpd_params']['xi']))
    if xi_values:
        mean_xi = np.mean([x[1] for x in xi_values])
        findings.append(f"Mean GPD shape parameter xi = {mean_xi:.3f} (>0 = heavy tails)")
        for t, xi in xi_values:
            findings.append(f"  {t}: xi = {xi:.3f}")

    print(f"\nTotal elapsed: {elapsed_total:.1f}s")

    # ========================================================================
    # Save Results
    # ========================================================================
    output = {
        "experiment_id": "K159",
        "title": "EVT-VaR: Extreme Value Theory for Tail Risk",
        "timestamp": datetime.now().isoformat(),
        "star_rating": star_str,
        "star_rating_numeric": star_rating,
        "verdict": verdict,
        "config": {
            "assets": ASSETS,
            "window": WINDOW,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "alpha_levels": ALPHA_LEVELS,
            "pot_threshold_quantile": POT_THRESHOLD_QUANTILE,
            "re_estimate_every": RE_ESTIMATE_EVERY,
        },
        "findings": findings,
        "aggregate": {
            model: {
                'kupiec_pass': summary_counts[model]['kupiec_pass'],
                'kupiec_total': summary_counts[model]['kupiec_total'],
                'cc_pass': summary_counts[model]['cc_pass'],
                'cc_total': summary_counts[model]['cc_total'],
                'dq_pass': summary_counts[model]['dq_pass'],
                'dq_total': summary_counts[model]['dq_total'],
                'trinity_pass': summary_counts[model]['trinity_pass'],
                'trinity_total': summary_counts[model]['trinity_total'],
            }
            for model in ['Normal', 'Student-t', 'EVT-GPD']
        },
        "results": {},
    }

    # Convert numpy types for JSON serialization
    def sanitize(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    for ticker, asset_res in all_results.items():
        output["results"][ticker] = sanitize(asset_res)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(sanitize(output), f, indent=2)

    print(f"\nResults saved to: {RESULTS_PATH}")
    print("\nDone.")


if __name__ == "__main__":
    main()
