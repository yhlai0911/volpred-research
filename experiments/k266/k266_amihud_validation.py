"""
K266: Amihud Illiquidity GARCH-X — Deep Validation of K265's Harvey Pass
========================================================================
[提出: 用戶, 執行: Claude]

Background:
  K265 found Amihud illiquidity passes Harvey for QQQ (DM t=-3.66) and TLT (t=-5.10).
  This needs rigorous validation before claiming genuine improvement over GJR-GARCH.

Critical issue with K265:
  K265 used full-sample GARCH (mild look-ahead). This test uses PURE rolling estimation.

Method:
  - GARCH-X with Amihud in variance equation (direct MLE, not two-stage):
    h_t = ω + α*ε² + γ*ε²*I(ε<0) + β*h_{t-1} + δ*Amihud_{t-1}
  - Amihud ILLIQ = |return| / dollar_volume, log-transformed, smoothed (5d, 22d, 66d)
  - Rolling window w=2000, refit every 22 days (PURE rolling, no look-ahead)
  - 5-period cross-validation (2005-2024, ~4-year periods)

Validation criteria (ALL must pass for the claim to stand):
  1. QLIKE improvement in 3+/5 OOS periods
  2. DM test with Newey-West HAC (not simple variance)
  3. Harvey threshold (|t| > 3.0 for the pooled result)
  4. Consistent sign of δ across all periods
  5. Robustness across Amihud windows (5d, 22d, 66d)

Assets: SPY, QQQ, GLD, TLT
Data: yfinance, 2005-01-01 to 2024-12-31
"""

import sys
import os
import warnings
import time
import json
import traceback
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.optimize import minimize
from numba import njit

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
REFIT_EVERY = 22
DATA_START = "2003-01-01"  # Extra buffer for Amihud smoothing + window
DATA_END = "2024-12-31"
ASSETS = ["SPY", "QQQ", "GLD", "TLT"]
AMIHUD_WINDOWS = [5, 22, 66]  # Smoothing windows to test

# 5-period cross-validation: ~4 years each
OOS_PERIODS = [
    ("2005-01-01", "2008-12-31", "P1_2005-2008"),
    ("2009-01-01", "2012-12-31", "P2_2009-2012"),
    ("2013-01-01", "2016-12-31", "P3_2013-2016"),
    ("2017-01-01", "2020-12-31", "P4_2017-2020"),
    ("2021-01-01", "2024-12-31", "P5_2021-2024"),
]

print("=" * 80)
print("K266: AMIHUD ILLIQUIDITY GARCH-X — DEEP VALIDATION")
print("    Validating K265's Harvey Pass with Pure Rolling Estimation")
print("    [提出: 用戶, 執行: Claude]")
print("=" * 80)
print(f"  Window: {WINDOW}, Refit every: {REFIT_EVERY}d")
print(f"  Assets: {ASSETS}")
print(f"  OOS Periods: {len(OOS_PERIODS)}")
print(f"  Amihud windows: {AMIHUD_WINDOWS}")
print()


# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def qlike_loss_series(actual_var, predicted_var):
    """Element-wise QLIKE loss for DM test. Lower is better."""
    predicted_var = np.maximum(predicted_var, 1e-12)
    return actual_var / predicted_var + np.log(predicted_var)


def qlike(actual_var, predicted_var):
    """Mean QLIKE loss."""
    return float(np.mean(qlike_loss_series(actual_var, predicted_var)))


def dm_test_hac(loss1, loss2, max_lag=None):
    """
    Diebold-Mariano test with Newey-West HAC standard errors.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative statistic → model 1 better.
    """
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)

    if max_lag is None:
        max_lag = max(1, int(np.floor(T ** (1/3))))

    # Newey-West HAC variance estimator
    gamma_0 = np.mean((d - d_bar) ** 2)
    V = gamma_0
    for k in range(1, max_lag + 1):
        w_k = 1.0 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        V += 2 * w_k * gamma_k

    V = max(V, 1e-20)
    dm_stat = d_bar / np.sqrt(V / T)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return {
        'statistic': float(dm_stat),
        'p_value': float(p_value),
        'mean_diff': float(d_bar),
        'hac_se': float(np.sqrt(V / T)),
        'max_lag': max_lag,
        'better_model': 'GARCH-X' if d_bar < 0 else 'GJR-GARCH',
        'harvey_pass': abs(dm_stat) > 3.0,
    }


# ==================================================================
# GARCH-X via Numba (direct MLE, Amihud in variance equation)
# ==================================================================

@njit
def _gjr_garch_x_variance(returns, exog, omega, alpha, gamma, beta, delta):
    """Compute GJR-GARCH-X variance series with Amihud in variance eq."""
    T = len(returns)
    var = np.empty(T)
    s2 = 0.0
    for i in range(T):
        s2 += returns[i] ** 2
    s2 /= T
    var[0] = s2

    for t in range(1, T):
        shock = returns[t-1] ** 2
        asym = shock if returns[t-1] < 0 else 0.0
        v = omega + alpha * shock + gamma * asym + beta * var[t-1] + delta * exog[t-1]
        if v < 1e-8:
            v = 1e-8
        var[t] = v
    return var


@njit
def _gjr_garch_x_nll(returns, exog, omega, alpha, gamma, beta, delta):
    """Negative log-likelihood for GJR-GARCH-X (Gaussian)."""
    var = _gjr_garch_x_variance(returns, exog, omega, alpha, gamma, beta, delta)
    T = len(returns)
    nll = 0.0
    for t in range(T):
        nll += np.log(var[t]) + returns[t] ** 2 / var[t]
    nll = 0.5 * (T * np.log(2 * np.pi) + nll)
    return nll


def garch_x_nll_wrapper(params, returns, exog):
    """Wrapper for scipy.optimize. Always GJR form."""
    omega, alpha, gamma, beta, delta = params
    val = _gjr_garch_x_nll(returns, exog, omega, alpha, gamma, beta, delta)
    if not np.isfinite(val):
        return 1e10
    return val


def fit_gjr_garch_x(returns_pct, exog, warm_start=None):
    """
    Fit GJR-GARCH-X model via MLE.
    h_t = ω + α*ε² + γ*ε²*I(ε<0) + β*h_{t-1} + δ*Amihud_{t-1}
    Returns: (params, success, nll)
    """
    sample_var = np.var(returns_pct)
    if sample_var < 1e-10:
        return None, False, np.inf

    if warm_start is not None:
        x0 = warm_start.copy()
    else:
        x0 = np.array([0.05 * sample_var, 0.03, 0.05, 0.88, 0.0])

    bounds = [
        (1e-6, sample_var * 10),   # omega
        (1e-6, 0.5),               # alpha
        (-0.3, 0.5),               # gamma
        (0.01, 0.999),             # beta
        (-1.0, 1.0),               # delta (Amihud coeff — wider range)
    ]

    best_result = None
    best_nll = np.inf

    # Multiple starting points for robustness
    starts = [x0]
    for delta_init in [-0.05, 0.0, 0.05, 0.1, -0.1]:
        alt = x0.copy()
        alt[4] = delta_init
        starts.append(alt)

    for start in starts:
        try:
            result = minimize(
                garch_x_nll_wrapper,
                start,
                args=(returns_pct, exog),
                method='L-BFGS-B',
                bounds=bounds,
                options={'maxiter': 300, 'ftol': 1e-8}
            )
            if (result.success or result.fun < 1e9) and result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is not None:
        return best_result.x, True, best_nll
    return None, False, np.inf


def forecast_gjr_garch_x(params, returns_pct, exog):
    """One-step-ahead forecast from fitted GJR-GARCH-X."""
    omega, alpha, gamma, beta, delta = params
    var = _gjr_garch_x_variance(returns_pct, exog, omega, alpha, gamma, beta, delta)

    shock = returns_pct[-1] ** 2
    asym = shock if returns_pct[-1] < 0 else 0.0
    h_next = omega + alpha * shock + gamma * asym + beta * var[-1] + delta * exog[-1]

    if h_next < 1e-8 or not np.isfinite(h_next):
        h_next = np.var(returns_pct)
    return h_next, params[4]  # Return delta for sign tracking


# ==================================================================
# BASELINE: GJR-GARCH via arch package (no Amihud)
# ==================================================================

def fit_baseline_gjr(returns_pct):
    """Fit standard GJR-GARCH(1,1) and return one-step-ahead forecast."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='normal')
        res = am.fit(disp='off', options={'maxiter': 200})
        fcast = res.forecast(horizon=1)
        h = fcast.variance.values[-1, 0]
        if h < 1e-8 or not np.isfinite(h):
            h = np.var(returns_pct)
        return h
    except Exception:
        return np.var(returns_pct)


# ==================================================================
# DATA LOADING
# ==================================================================

def load_data(asset):
    """Load price data from yfinance with volume."""
    print(f"  Loading {asset} from yfinance...")
    df = yf.download(asset, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Close', 'Volume']].dropna()
    df['Return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['Return_pct'] = df['Return'] * 100
    df['RV'] = df['Return'] ** 2  # Realized variance proxy
    df['Dollar_Volume'] = df['Close'] * df['Volume']
    df = df.dropna()
    print(f"    {asset}: {len(df)} observations, {df.index[0].date()} to {df.index[-1].date()}")
    return df


def compute_amihud(df, window):
    """
    Compute Amihud Illiquidity Ratio.
    ILLIQ_t = |return_t| / dollar_volume_t
    Then smooth with rolling window, log-transform.
    """
    illiq = df['Return'].abs() / df['Dollar_Volume']
    illiq = illiq.replace([np.inf, -np.inf], np.nan)
    # Rolling mean smoothing
    illiq_smooth = illiq.rolling(window=window, min_periods=max(1, window // 2)).mean()
    # Log transform (add small constant to avoid log(0))
    log_illiq = np.log(illiq_smooth + 1e-20)
    # Z-score normalize within the series for numerical stability
    mean_val = log_illiq.expanding(min_periods=252).mean()
    std_val = log_illiq.expanding(min_periods=252).std()
    z_illiq = (log_illiq - mean_val) / std_val.clip(lower=1e-8)
    return z_illiq.fillna(0.0)


# ==================================================================
# ROLLING ESTIMATION ENGINE
# ==================================================================

def rolling_forecast(df, amihud_series, oos_start, oos_end):
    """
    Pure rolling GARCH vs GJR-GARCH-X forecast comparison.
    No look-ahead: each forecast uses only data up to that point.

    Returns dict with arrays of forecasts, actuals, deltas.
    """
    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
    oos_idx = df.index[oos_mask]

    if len(oos_idx) < 50:
        return None

    returns_pct = df['Return_pct'].values
    rv = df['RV'].values
    amihud = amihud_series.values
    all_dates = df.index

    # Find integer positions
    oos_positions = [i for i, d in enumerate(all_dates) if d >= pd.Timestamp(oos_start) and d <= pd.Timestamp(oos_end)]
    if not oos_positions or oos_positions[0] < WINDOW:
        return None

    n_oos = len(oos_positions)
    baseline_fcasts = np.full(n_oos, np.nan)
    garchx_fcasts = np.full(n_oos, np.nan)
    actuals = np.full(n_oos, np.nan)
    deltas = np.full(n_oos, np.nan)
    dates_out = []

    warm_params = None
    last_fit = -REFIT_EVERY  # Force fit on first day

    n_fit = 0
    n_fail_baseline = 0
    n_fail_garchx = 0

    for idx_in_oos, pos in enumerate(oos_positions):
        if pos < WINDOW:
            continue

        train_start = pos - WINDOW
        train_end = pos  # Exclusive: train on [train_start, pos-1], forecast pos

        train_ret = returns_pct[train_start:train_end]
        train_amihud = amihud[train_start:train_end]
        actual_rv = rv[pos]
        actuals[idx_in_oos] = actual_rv
        dates_out.append(all_dates[pos])

        # Refit or reuse
        need_refit = (pos - last_fit >= REFIT_EVERY) or warm_params is None

        if need_refit:
            n_fit += 1
            last_fit = pos

            # Baseline: GJR-GARCH
            h_baseline = fit_baseline_gjr(pd.Series(train_ret))
            baseline_fcasts[idx_in_oos] = h_baseline

            # GARCH-X with Amihud
            params, success, nll = fit_gjr_garch_x(train_ret, train_amihud, warm_start=warm_params)
            if success and params is not None:
                h_garchx, delta_val = forecast_gjr_garch_x(params, train_ret, train_amihud)
                garchx_fcasts[idx_in_oos] = h_garchx
                deltas[idx_in_oos] = delta_val
                warm_params = params
            else:
                n_fail_garchx += 1
                garchx_fcasts[idx_in_oos] = h_baseline  # Fallback
                deltas[idx_in_oos] = 0.0
        else:
            # Reuse parameters, just compute new forecast
            h_baseline = fit_baseline_gjr(pd.Series(train_ret))
            baseline_fcasts[idx_in_oos] = h_baseline

            if warm_params is not None:
                h_garchx, delta_val = forecast_gjr_garch_x(warm_params, train_ret, train_amihud)
                garchx_fcasts[idx_in_oos] = h_garchx
                deltas[idx_in_oos] = delta_val
            else:
                garchx_fcasts[idx_in_oos] = h_baseline
                deltas[idx_in_oos] = 0.0

    # Clean up NaNs
    valid = ~(np.isnan(actuals) | np.isnan(baseline_fcasts) | np.isnan(garchx_fcasts))
    if np.sum(valid) < 50:
        return None

    return {
        'actuals': actuals[valid],
        'baseline': baseline_fcasts[valid],
        'garchx': garchx_fcasts[valid],
        'deltas': deltas[valid],
        'dates': [d for d, v in zip(dates_out, valid[~np.isnan(actuals)]) if v] if dates_out else [],
        'n_obs': int(np.sum(valid)),
        'n_fits': n_fit,
        'n_fail_baseline': n_fail_baseline,
        'n_fail_garchx': n_fail_garchx,
    }


# ==================================================================
# REGIME ANALYSIS
# ==================================================================

def regime_analysis(actuals, baseline, garchx, dates):
    """Analyze if improvement is concentrated in specific VIX regimes."""
    # Use realized vol as proxy for regime
    rv_median = np.median(actuals)

    high_vol = actuals > rv_median
    low_vol = ~high_vol

    results = {}
    for name, mask in [('high_vol', high_vol), ('low_vol', low_vol)]:
        if np.sum(mask) < 30:
            results[name] = {'n': int(np.sum(mask)), 'too_few': True}
            continue

        q_base = qlike(actuals[mask], baseline[mask])
        q_garchx = qlike(actuals[mask], garchx[mask])
        improvement_pct = (q_base - q_garchx) / abs(q_base) * 100

        loss_base = qlike_loss_series(actuals[mask], baseline[mask])
        loss_garchx = qlike_loss_series(actuals[mask], garchx[mask])
        dm = dm_test_hac(loss_base, loss_garchx)

        results[name] = {
            'n': int(np.sum(mask)),
            'qlike_baseline': q_base,
            'qlike_garchx': q_garchx,
            'improvement_pct': improvement_pct,
            'dm_stat': dm['statistic'],
            'dm_pval': dm['p_value'],
        }

    return results


# ==================================================================
# MAIN EXECUTION
# ==================================================================

t0 = time.time()

# Load data
print("=" * 60)
print("LOADING DATA")
print("=" * 60)
all_data = {}
for asset in ASSETS:
    all_data[asset] = load_data(asset)
print()

# Pre-compile numba
print("Pre-compiling Numba functions...")
_dummy_ret = np.random.randn(100)
_dummy_exog = np.random.randn(100)
_ = _gjr_garch_x_variance(_dummy_ret, _dummy_exog, 0.01, 0.05, 0.05, 0.9, 0.0)
_ = _gjr_garch_x_nll(_dummy_ret, _dummy_exog, 0.01, 0.05, 0.05, 0.9, 0.0)
print("  Done.")
print()

# ==================================================================
# RUN EXPERIMENTS
# ==================================================================

all_results = {}

for asset in ASSETS:
    print("=" * 70)
    print(f"ASSET: {asset}")
    print("=" * 70)

    df = all_data[asset]
    asset_results = {}

    for aw in AMIHUD_WINDOWS:
        print(f"\n  Amihud window = {aw}d")
        print(f"  {'─' * 50}")

        # Compute Amihud
        amihud = compute_amihud(df, window=aw)

        period_results = []
        all_deltas_by_period = []

        for oos_start, oos_end, period_name in OOS_PERIODS:
            print(f"    Period {period_name}: ", end="", flush=True)

            result = rolling_forecast(df, amihud, oos_start, oos_end)

            if result is None:
                print("SKIP (insufficient data)")
                period_results.append({
                    'period': period_name,
                    'status': 'skip',
                })
                continue

            # QLIKE
            q_base = qlike(result['actuals'], result['baseline'])
            q_garchx = qlike(result['actuals'], result['garchx'])
            improvement = (q_base - q_garchx) / abs(q_base) * 100

            # DM test with HAC
            loss_base = qlike_loss_series(result['actuals'], result['baseline'])
            loss_garchx = qlike_loss_series(result['actuals'], result['garchx'])
            dm = dm_test_hac(loss_base, loss_garchx)

            # Delta sign analysis
            mean_delta = float(np.mean(result['deltas']))
            std_delta = float(np.std(result['deltas']))
            pct_positive = float(np.mean(result['deltas'] > 0) * 100)
            all_deltas_by_period.append(mean_delta)

            # Regime analysis
            regimes = regime_analysis(
                result['actuals'], result['baseline'], result['garchx'],
                result.get('dates', [])
            )

            status = "✓" if dm['harvey_pass'] and improvement > 0 else "✗"
            print(f"n={result['n_obs']:4d}  QLIKE: {q_base:.4f}→{q_garchx:.4f} "
                  f"({improvement:+.2f}%)  DM={dm['statistic']:+.3f} "
                  f"(p={dm['p_value']:.4f})  δ={mean_delta:+.4f}  {status}")

            period_results.append({
                'period': period_name,
                'status': 'ok',
                'n_obs': result['n_obs'],
                'n_fits': result['n_fits'],
                'n_fail_garchx': result['n_fail_garchx'],
                'qlike_baseline': q_base,
                'qlike_garchx': q_garchx,
                'improvement_pct': improvement,
                'dm_stat': dm['statistic'],
                'dm_pval': dm['p_value'],
                'dm_hac_se': dm['hac_se'],
                'harvey_pass': dm['harvey_pass'],
                'better_model': dm['better_model'],
                'mean_delta': mean_delta,
                'std_delta': std_delta,
                'pct_delta_positive': pct_positive,
                'regime_analysis': regimes,
            })

        # Cross-period summary for this Amihud window
        valid_periods = [p for p in period_results if p['status'] == 'ok']

        if valid_periods:
            n_garchx_wins = sum(1 for p in valid_periods if p['improvement_pct'] > 0)
            n_harvey_pass = sum(1 for p in valid_periods if p.get('harvey_pass', False))
            n_valid = len(valid_periods)

            # Sign consistency: all deltas same sign?
            signs = [np.sign(p['mean_delta']) for p in valid_periods]
            sign_consistent = len(set(signs)) == 1 and signs[0] != 0

            # Pooled DM stat (simple average of per-period stats, weighted by sqrt(n))
            pooled_stat = np.mean([p['dm_stat'] for p in valid_periods])
            pooled_weighted = np.average(
                [p['dm_stat'] for p in valid_periods],
                weights=[np.sqrt(p['n_obs']) for p in valid_periods]
            )

            summary = {
                'amihud_window': aw,
                'n_valid_periods': n_valid,
                'n_garchx_wins': n_garchx_wins,
                'n_harvey_pass': n_harvey_pass,
                'win_rate': f"{n_garchx_wins}/{n_valid}",
                'sign_consistent': sign_consistent,
                'dominant_sign': 'positive' if np.mean(all_deltas_by_period) > 0 else 'negative',
                'mean_delta_across_periods': float(np.mean(all_deltas_by_period)),
                'pooled_dm_stat': float(pooled_stat),
                'pooled_dm_weighted': float(pooled_weighted),
                'pooled_harvey_pass': abs(pooled_weighted) > 3.0,
                'periods': period_results,
            }

            print(f"\n  Summary (Amihud {aw}d):")
            print(f"    GARCH-X wins: {summary['win_rate']}")
            print(f"    Harvey pass periods: {n_harvey_pass}/{n_valid}")
            print(f"    Sign consistent: {sign_consistent} ({summary['dominant_sign']})")
            print(f"    Pooled DM (weighted): {pooled_weighted:+.3f} "
                  f"{'PASS HARVEY' if summary['pooled_harvey_pass'] else 'FAIL HARVEY'}")

        else:
            summary = {
                'amihud_window': aw,
                'n_valid_periods': 0,
                'error': 'no valid periods',
                'periods': period_results,
            }

        asset_results[f'amihud_{aw}d'] = summary

    all_results[asset] = asset_results
    print()

elapsed = time.time() - t0

# ==================================================================
# FINAL VERDICT
# ==================================================================
print("\n" + "=" * 80)
print("FINAL VERDICT: K266 Amihud GARCH-X Deep Validation")
print("=" * 80)

# Best Amihud window per asset
for asset in ASSETS:
    print(f"\n{'─' * 60}")
    print(f"  {asset}")
    print(f"{'─' * 60}")

    best_window = None
    best_wins = -1
    best_pooled = 0

    for aw in AMIHUD_WINDOWS:
        key = f'amihud_{aw}d'
        res = all_results[asset].get(key, {})
        wins = res.get('n_garchx_wins', 0)
        pooled = res.get('pooled_dm_weighted', 0)

        print(f"  Amihud {aw:2d}d: wins={res.get('win_rate', '?')}, "
              f"pooled DM={pooled:+.3f}, "
              f"sign_consistent={res.get('sign_consistent', '?')}, "
              f"Harvey={'PASS' if res.get('pooled_harvey_pass', False) else 'FAIL'}")

        if wins > best_wins or (wins == best_wins and abs(pooled) > abs(best_pooled)):
            best_window = aw
            best_wins = wins
            best_pooled = pooled

    if best_window:
        print(f"  → Best window: {best_window}d")

# Overall assessment
print(f"\n{'=' * 80}")
print("VALIDATION CRITERIA CHECK")
print("=" * 80)

genuine_findings = []
for asset in ASSETS:
    for aw in AMIHUD_WINDOWS:
        key = f'amihud_{aw}d'
        res = all_results[asset].get(key, {})

        n_valid = res.get('n_valid_periods', 0)
        n_wins = res.get('n_garchx_wins', 0)
        sign_ok = res.get('sign_consistent', False)
        harvey_ok = res.get('pooled_harvey_pass', False)

        passes_3of5 = n_wins >= 3 and n_valid >= 5
        passes_all = passes_3of5 and sign_ok and harvey_ok

        if passes_3of5:
            status = "GENUINE" if passes_all else "PARTIAL"
            genuine_findings.append({
                'asset': asset,
                'amihud_window': aw,
                'status': status,
                'wins': f"{n_wins}/{n_valid}",
                'sign_consistent': sign_ok,
                'harvey_pass': harvey_ok,
                'pooled_dm': res.get('pooled_dm_weighted', 0),
            })
            print(f"  {status}: {asset} Amihud-{aw}d — {n_wins}/{n_valid} periods, "
                  f"sign={sign_ok}, Harvey={harvey_ok}, "
                  f"pooled DM={res.get('pooled_dm_weighted', 0):+.3f}")

if not genuine_findings:
    print("  NO genuine findings. K265 result does not survive pure rolling validation.")
    print("  Amihud illiquidity does NOT reliably improve GJR-GARCH volatility forecasts.")
else:
    n_genuine = sum(1 for f in genuine_findings if f['status'] == 'GENUINE')
    n_partial = sum(1 for f in genuine_findings if f['status'] == 'PARTIAL')
    print(f"\n  Total: {n_genuine} GENUINE + {n_partial} PARTIAL findings")

    if n_genuine == 0:
        print("  ⚠ No finding passes ALL criteria. K265 result is NOT fully validated.")

print(f"\n  Elapsed: {elapsed:.1f}s")

# ==================================================================
# SAVE RESULTS
# ==================================================================

results_path = os.path.join(os.path.dirname(__file__), "k266_amihud_validation_results.json")

save_data = {
    'experiment': 'K266',
    'title': 'Amihud Illiquidity GARCH-X Deep Validation',
    'method': 'GJR-GARCH-X with Amihud in variance equation, pure rolling w=2000, refit=22d',
    'data_source': 'yfinance',
    'data_period': f'{DATA_START} to {DATA_END}',
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'assets': ASSETS,
    'amihud_windows': AMIHUD_WINDOWS,
    'oos_periods': [{'start': s, 'end': e, 'name': n} for s, e, n in OOS_PERIODS],
    'results': {},
    'genuine_findings': genuine_findings,
    'elapsed_seconds': elapsed,
    'validation_criteria': {
        'qlike_improvement_3of5': '3+ out of 5 OOS periods show improvement',
        'dm_test': 'Newey-West HAC corrected',
        'harvey_threshold': '|t| > 3.0 for pooled result',
        'sign_consistency': 'δ same sign across all periods',
        'amihud_robustness': 'Consistent across 5d/22d/66d windows',
    },
}

# Serialize results (convert numpy types)
def np_safe(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def deep_convert(obj):
    if isinstance(obj, dict):
        return {k: deep_convert(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_convert(v) for v in obj]
    return np_safe(obj)


save_data['results'] = deep_convert(all_results)

with open(results_path, 'w') as f:
    json.dump(save_data, f, indent=2, default=str)

print(f"\nResults saved to: {results_path}")
print("\nK266 COMPLETE.")
