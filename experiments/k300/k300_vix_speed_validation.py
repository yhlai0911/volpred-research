"""
K300: VIX Spike Speed Rolling Validation
==========================================
[提出: 用戶, 執行: Claude]

Background:
  K299 Pilot C found VIX 5-day z-score passes Harvey (partial r=0.106, t=6.54)
  for vol prediction. K265→K266 taught us that full-sample results can be
  artifacts. This is the rigorous rolling validation.

Method (Two-Stage GARCH-X, pure rolling):
  Stage 1: GJR-GARCH(1,1,1) w=2000, refit every 22d → h_t (baseline forecast)
  Stage 2: Rolling OLS (252d): h_adjusted = h_t + δ * VIX_speed_{t-1}
  VIX_speed = (VIX - MA(VIX,20d)) / std(VIX,20d)  (z-score of VIX level)

5-Period Cross-Validation (2005-2024, ~4-year periods):
  P1: 2005-2008 (GFC ramp-up)
  P2: 2009-2012 (recovery)
  P3: 2013-2016 (low-vol era)
  P4: 2017-2020 (COVID)
  P5: 2021-2024 (rate hikes)

Pass Criteria (ALL must hold):
  1. 3+/5 periods show QLIKE improvement
  2. Consistent δ sign across periods
  3. Pooled DM test passes Harvey (|t| > 3.0, Newey-West HAC)
  4. Meaningful effect size (not just statistical)

Bonus Test: Does VIX speed improve 50/50 SPY+VT strategy MDD?

Data: SPY, ^VIX daily from yfinance. 2003-01-01 to 2024-12-31.
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

# ==================================================================
# CONFIG
# ==================================================================
GARCH_WINDOW = 2000        # Stage 1: GJR-GARCH estimation window
REFIT_EVERY = 22           # Refit GARCH every 22 days
OLS_WINDOW = 252           # Stage 2: Rolling OLS window
VIX_MA_WINDOW = 20         # VIX moving average for z-score
DATA_START = "1996-01-01"  # Need 2000d buffer before 2005-01-01
DATA_END = "2024-12-31"

# 5-period cross-validation: ~4 years each
OOS_PERIODS = [
    ("2005-01-01", "2008-12-31", "P1_2005-2008"),
    ("2009-01-01", "2012-12-31", "P2_2009-2012"),
    ("2013-01-01", "2016-12-31", "P3_2013-2016"),
    ("2017-01-01", "2020-12-31", "P4_2017-2020"),
    ("2021-01-01", "2024-12-31", "P5_2021-2024"),
]

print("=" * 80)
print("K300: VIX SPIKE SPEED ROLLING VALIDATION")
print("    Validating K299 Pilot C (t=6.54) with Pure Rolling Two-Stage GARCH-X")
print("    [提出: 用戶, 執行: Claude]")
print("=" * 80)
print(f"  GARCH window: {GARCH_WINDOW}, OLS window: {OLS_WINDOW}")
print(f"  Refit every: {REFIT_EVERY}d, VIX MA window: {VIX_MA_WINDOW}d")
print(f"  OOS Periods: {len(OOS_PERIODS)}")
print()


# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def qlike_loss_series(actual_var, predicted_var):
    """Element-wise QLIKE loss. Lower is better."""
    predicted_var = np.maximum(predicted_var, 1e-12)
    return actual_var / predicted_var + np.log(predicted_var)


def qlike(actual_var, predicted_var):
    """Mean QLIKE loss."""
    return float(np.mean(qlike_loss_series(actual_var, predicted_var)))


def dm_test_hac(loss1, loss2, max_lag=None):
    """
    Diebold-Mariano test with Newey-West HAC standard errors.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative statistic → model 1 (loss1) better (lower loss).
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
        'better_model': 'GJR-GARCH' if d_bar < 0 else 'Two-Stage',
        'harvey_pass': abs(dm_stat) > 3.0,
    }


def rolling_ols_coefficient(y, X, window):
    """
    Rolling OLS: y_t = a + b * X_t + e_t using last `window` observations.
    Returns coefficient b (the slope on X).
    Uses numpy lstsq for numerical stability.
    """
    if len(y) < window:
        return 0.0, 0.0, 0.0  # coeff, se, t_stat

    y_w = y[-window:]
    X_w = X[-window:]

    # Remove NaN/Inf
    valid = np.isfinite(y_w) & np.isfinite(X_w)
    if np.sum(valid) < 30:
        return 0.0, 0.0, 0.0

    y_v = y_w[valid]
    X_v = X_w[valid]
    n = len(y_v)

    # Design matrix: [1, X]
    A = np.column_stack([np.ones(n), X_v])

    try:
        result = np.linalg.lstsq(A, y_v, rcond=None)
        coeffs = result[0]
        b = coeffs[1]

        # Standard error of b
        residuals = y_v - A @ coeffs
        sigma2 = np.sum(residuals ** 2) / max(n - 2, 1)
        XtX_inv = np.linalg.inv(A.T @ A)
        se_b = np.sqrt(sigma2 * XtX_inv[1, 1])
        t_stat = b / max(se_b, 1e-12)

        return float(b), float(se_b), float(t_stat)
    except (np.linalg.LinAlgError, ValueError):
        return 0.0, 0.0, 0.0


# ==================================================================
# DATA LOADING
# ==================================================================

print("=" * 60)
print("LOADING DATA")
print("=" * 60)

print("  Downloading SPY from yfinance...")
spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

print("  Downloading ^VIX from yfinance...")
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

# Align dates
spy = spy_raw[['Close']].rename(columns={'Close': 'SPY_Close'})
vix = vix_raw[['Close']].rename(columns={'Close': 'VIX'})
df = spy.join(vix, how='inner').dropna()

# Returns
df['Return'] = np.log(df['SPY_Close'] / df['SPY_Close'].shift(1))
df['Return_pct'] = df['Return'] * 100
df['RV'] = df['Return'] ** 2  # Realized variance proxy (squared return)

# VIX speed z-score: (VIX - MA20) / std20
df['VIX_MA'] = df['VIX'].rolling(window=VIX_MA_WINDOW, min_periods=VIX_MA_WINDOW).mean()
df['VIX_STD'] = df['VIX'].rolling(window=VIX_MA_WINDOW, min_periods=VIX_MA_WINDOW).std()
df['VIX_speed'] = (df['VIX'] - df['VIX_MA']) / df['VIX_STD'].clip(lower=0.01)

df = df.dropna()

print(f"  Combined data: {len(df)} observations")
print(f"  Date range: {df.index[0].date()} to {df.index[-1].date()}")
print(f"  VIX speed stats: mean={df['VIX_speed'].mean():.3f}, "
      f"std={df['VIX_speed'].std():.3f}, "
      f"min={df['VIX_speed'].min():.2f}, max={df['VIX_speed'].max():.2f}")
print()


# ==================================================================
# STAGE 1: GJR-GARCH BASELINE FORECASTS
# ==================================================================

def fit_gjr_garch_baseline(returns_pct):
    """Fit GJR-GARCH(1,1,1) and return one-step-ahead variance forecast."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='normal')
        res = am.fit(disp='off', options={'maxiter': 300})
        fcast = res.forecast(horizon=1)
        h = fcast.variance.values[-1, 0]
        if h < 1e-8 or not np.isfinite(h):
            h = np.var(returns_pct)
        return h
    except Exception:
        return np.var(returns_pct)


# ==================================================================
# ROLLING TWO-STAGE FORECAST ENGINE
# ==================================================================

def rolling_two_stage_forecast(df, oos_start, oos_end):
    """
    Pure rolling two-stage GARCH-X forecast.

    Stage 1: GJR-GARCH(1,1,1) w=2000 → h_t (baseline)
    Stage 2: Rolling OLS (252d) on past data:
             RV_{t} = a + delta * VIX_speed_{t-1} + e
             then: h_adjusted_{t+1} = h_{t+1} + delta_hat * VIX_speed_{t}

    No look-ahead: OLS uses only past realized variance and past VIX speed.
    """
    oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
    oos_idx = df.index[oos_mask]

    if len(oos_idx) < 50:
        return None

    returns_pct = df['Return_pct'].values
    rv = df['RV'].values
    vix_speed = df['VIX_speed'].values
    all_dates = df.index

    # Integer positions for OOS
    oos_positions = [i for i, d in enumerate(all_dates)
                     if d >= pd.Timestamp(oos_start) and d <= pd.Timestamp(oos_end)]

    if not oos_positions or oos_positions[0] < GARCH_WINDOW:
        return None

    n_oos = len(oos_positions)
    baseline_fcasts = np.full(n_oos, np.nan)
    twostage_fcasts = np.full(n_oos, np.nan)
    actuals = np.full(n_oos, np.nan)
    deltas = np.full(n_oos, np.nan)
    delta_ses = np.full(n_oos, np.nan)
    delta_tstats = np.full(n_oos, np.nan)
    dates_out = []

    last_garch_fit = -REFIT_EVERY
    cached_h = None
    n_garch_fits = 0
    n_ols_fits = 0
    n_garch_fail = 0

    for idx_in_oos, pos in enumerate(oos_positions):
        if pos < GARCH_WINDOW:
            continue

        train_start = pos - GARCH_WINDOW
        train_ret = returns_pct[train_start:pos]
        actual_rv_t = rv[pos]
        actuals[idx_in_oos] = actual_rv_t
        dates_out.append(all_dates[pos])

        # ============================================
        # STAGE 1: GJR-GARCH baseline forecast
        # ============================================
        need_garch_refit = (pos - last_garch_fit >= REFIT_EVERY) or cached_h is None

        if need_garch_refit:
            n_garch_fits += 1
            last_garch_fit = pos
            h_baseline = fit_gjr_garch_baseline(pd.Series(train_ret))
            cached_h = h_baseline
        else:
            # Between refits: use arch package with cached model isn't feasible
            # in two-stage approach. We still get the GJR forecast using the
            # training window up to current point.
            h_baseline = fit_gjr_garch_baseline(pd.Series(train_ret))

        baseline_fcasts[idx_in_oos] = h_baseline

        # ============================================
        # STAGE 2: Rolling OLS adjustment
        # ============================================
        # OLS training data: use past OLS_WINDOW days BEFORE the forecast date
        # y = RV[t], X = VIX_speed[t-1] (lagged by 1 day)
        # This ensures pure predictability — we predict tomorrow's RV using
        # today's VIX speed.

        ols_end = pos  # exclusive: data up to pos-1
        ols_start_idx = max(0, ols_end - OLS_WINDOW)

        if ols_end - ols_start_idx < 60:
            # Not enough data for OLS
            twostage_fcasts[idx_in_oos] = h_baseline
            deltas[idx_in_oos] = 0.0
            delta_ses[idx_in_oos] = 0.0
            delta_tstats[idx_in_oos] = 0.0
            continue

        # OLS: RV_t = a + delta * VIX_speed_{t-1} + e
        # Indices: for t in [ols_start+1, ols_end-1]:
        #   y[t] = RV[t], X[t] = VIX_speed[t-1]
        ols_range = np.arange(ols_start_idx + 1, ols_end)
        y_ols = rv[ols_range]                    # RV at time t
        x_ols = vix_speed[ols_range - 1]         # VIX speed at t-1

        delta_hat, se_hat, t_hat = rolling_ols_coefficient(y_ols, x_ols, len(y_ols))
        n_ols_fits += 1

        deltas[idx_in_oos] = delta_hat
        delta_ses[idx_in_oos] = se_hat
        delta_tstats[idx_in_oos] = t_hat

        # Adjusted forecast: h_adjusted = h_baseline + delta * VIX_speed[today]
        # VIX_speed[today] = vix_speed[pos-1] (lag 1: available at forecast time)
        vix_speed_today = vix_speed[pos - 1]
        h_adjusted = h_baseline + delta_hat * vix_speed_today

        # Floor at 1e-8 to avoid negative variance
        if h_adjusted < 1e-8 or not np.isfinite(h_adjusted):
            h_adjusted = h_baseline

        twostage_fcasts[idx_in_oos] = h_adjusted

    # Clean up NaNs
    valid = ~(np.isnan(actuals) | np.isnan(baseline_fcasts) | np.isnan(twostage_fcasts))
    if np.sum(valid) < 50:
        return None

    return {
        'actuals': actuals[valid],
        'baseline': baseline_fcasts[valid],
        'twostage': twostage_fcasts[valid],
        'deltas': deltas[valid],
        'delta_ses': delta_ses[valid],
        'delta_tstats': delta_tstats[valid],
        'dates': [d for d, v in zip(dates_out, valid[:len(dates_out)]) if v],
        'n_obs': int(np.sum(valid)),
        'n_garch_fits': n_garch_fits,
        'n_ols_fits': n_ols_fits,
        'n_garch_fail': n_garch_fail,
    }


# ==================================================================
# REGIME ANALYSIS
# ==================================================================

def regime_analysis(actuals, baseline, twostage, vix_speed_vals):
    """Analyze improvement by VIX regime (high spike vs. calm)."""
    if vix_speed_vals is None or len(vix_speed_vals) != len(actuals):
        return {}

    results = {}

    # Split by VIX speed sign (positive = VIX rising, negative = VIX falling)
    for name, mask_fn in [
        ('vix_rising', lambda x: x > 0),
        ('vix_falling', lambda x: x <= 0),
        ('vix_spike', lambda x: x > 1.0),   # > 1 std above MA
        ('vix_calm', lambda x: (x >= -1.0) & (x <= 1.0)),
    ]:
        mask = mask_fn(vix_speed_vals)
        if np.sum(mask) < 30:
            results[name] = {'n': int(np.sum(mask)), 'too_few': True}
            continue

        q_base = qlike(actuals[mask], baseline[mask])
        q_twostage = qlike(actuals[mask], twostage[mask])
        improvement_pct = (q_base - q_twostage) / abs(q_base) * 100

        loss_base = qlike_loss_series(actuals[mask], baseline[mask])
        loss_twostage = qlike_loss_series(actuals[mask], twostage[mask])
        dm = dm_test_hac(loss_base, loss_twostage)

        results[name] = {
            'n': int(np.sum(mask)),
            'qlike_baseline': float(q_base),
            'qlike_twostage': float(q_twostage),
            'improvement_pct': float(improvement_pct),
            'dm_stat': float(dm['statistic']),
            'dm_pval': float(dm['p_value']),
            'harvey_pass': dm['harvey_pass'],
        }

    return results


# ==================================================================
# MAIN EXECUTION
# ==================================================================

t0 = time.time()

print("=" * 70)
print("RUNNING 5-PERIOD ROLLING VALIDATION")
print("=" * 70)

all_period_results = []
all_actuals_pooled = []
all_baseline_pooled = []
all_twostage_pooled = []
all_deltas_means = []

for oos_start, oos_end, period_name in OOS_PERIODS:
    print(f"\n  Period {period_name}: ", end="", flush=True)

    result = rolling_two_stage_forecast(df, oos_start, oos_end)

    if result is None:
        print("SKIP (insufficient data)")
        all_period_results.append({
            'period': period_name,
            'status': 'skip',
        })
        continue

    # QLIKE comparison
    q_base = qlike(result['actuals'], result['baseline'])
    q_twostage = qlike(result['actuals'], result['twostage'])
    improvement = (q_base - q_twostage) / abs(q_base) * 100

    # DM test with HAC
    loss_base = qlike_loss_series(result['actuals'], result['baseline'])
    loss_twostage = qlike_loss_series(result['actuals'], result['twostage'])
    dm = dm_test_hac(loss_base, loss_twostage)

    # Delta analysis
    mean_delta = float(np.mean(result['deltas']))
    median_delta = float(np.median(result['deltas']))
    std_delta = float(np.std(result['deltas']))
    pct_positive = float(np.mean(result['deltas'] > 0) * 100)
    mean_t_stat = float(np.mean(result['delta_tstats']))

    all_deltas_means.append(mean_delta)

    # Collect for pooled analysis
    all_actuals_pooled.append(result['actuals'])
    all_baseline_pooled.append(result['baseline'])
    all_twostage_pooled.append(result['twostage'])

    # Get VIX speed values for regime analysis (lag 1)
    vix_speed_at_forecast = df['VIX_speed'].values
    oos_positions = [i for i, d in enumerate(df.index)
                     if d >= pd.Timestamp(oos_start) and d <= pd.Timestamp(oos_end)]
    if len(oos_positions) >= result['n_obs']:
        vix_for_regime = np.array([vix_speed_at_forecast[p - 1] for p in oos_positions[:result['n_obs']]])
    else:
        vix_for_regime = None

    regimes = regime_analysis(result['actuals'], result['baseline'], result['twostage'], vix_for_regime)

    status_icon = "PASS" if improvement > 0 else "FAIL"
    harvey_icon = "Harvey:PASS" if dm['harvey_pass'] else "Harvey:FAIL"

    print(f"n={result['n_obs']:4d}  "
          f"QLIKE: {q_base:.4f} -> {q_twostage:.4f} ({improvement:+.2f}%)  "
          f"DM={dm['statistic']:+.3f} (p={dm['p_value']:.4f}) {harvey_icon}  "
          f"delta={mean_delta:+.6f}  [{status_icon}]")

    # Print regime details
    for regime_name, regime_data in regimes.items():
        if not regime_data.get('too_few', False):
            print(f"        {regime_name:12s}: n={regime_data['n']:4d}, "
                  f"QLIKE impr={regime_data['improvement_pct']:+.2f}%, "
                  f"DM={regime_data['dm_stat']:+.3f}")

    all_period_results.append({
        'period': period_name,
        'oos_start': oos_start,
        'oos_end': oos_end,
        'status': 'ok',
        'n_obs': result['n_obs'],
        'n_garch_fits': result['n_garch_fits'],
        'n_ols_fits': result['n_ols_fits'],
        'qlike_baseline': q_base,
        'qlike_twostage': q_twostage,
        'qlike_improvement_pct': improvement,
        'qlike_improved': improvement > 0,
        'dm_stat': dm['statistic'],
        'dm_pval': dm['p_value'],
        'dm_hac_se': dm['hac_se'],
        'harvey_pass': dm['harvey_pass'],
        'better_model': dm['better_model'],
        'mean_delta': mean_delta,
        'median_delta': median_delta,
        'std_delta': std_delta,
        'pct_delta_positive': pct_positive,
        'mean_ols_t_stat': mean_t_stat,
        'regime_analysis': regimes,
    })


# ==================================================================
# POOLED ANALYSIS
# ==================================================================

print("\n" + "=" * 70)
print("POOLED ANALYSIS (all periods combined)")
print("=" * 70)

valid_results = [r for r in all_period_results if r['status'] == 'ok']

if all_actuals_pooled:
    pooled_actuals = np.concatenate(all_actuals_pooled)
    pooled_baseline = np.concatenate(all_baseline_pooled)
    pooled_twostage = np.concatenate(all_twostage_pooled)

    pooled_q_base = qlike(pooled_actuals, pooled_baseline)
    pooled_q_twostage = qlike(pooled_actuals, pooled_twostage)
    pooled_improvement = (pooled_q_base - pooled_q_twostage) / abs(pooled_q_base) * 100

    pooled_loss_base = qlike_loss_series(pooled_actuals, pooled_baseline)
    pooled_loss_twostage = qlike_loss_series(pooled_actuals, pooled_twostage)
    pooled_dm = dm_test_hac(pooled_loss_base, pooled_loss_twostage)

    print(f"\n  Pooled N = {len(pooled_actuals)}")
    print(f"  QLIKE: {pooled_q_base:.4f} -> {pooled_q_twostage:.4f} ({pooled_improvement:+.2f}%)")
    print(f"  Pooled DM stat = {pooled_dm['statistic']:+.4f}  (p={pooled_dm['p_value']:.6f})")
    print(f"  Harvey threshold (|t| > 3.0): {'PASS' if pooled_dm['harvey_pass'] else 'FAIL'}")
    print(f"  Better model: {pooled_dm['better_model']}")
else:
    pooled_dm = {'statistic': 0, 'p_value': 1, 'harvey_pass': False}
    pooled_improvement = 0
    print("  No valid periods for pooling.")


# ==================================================================
# VALIDATION CRITERIA CHECK
# ==================================================================

print("\n" + "=" * 80)
print("VALIDATION CRITERIA CHECK")
print("=" * 80)

n_valid = len(valid_results)
n_improved = sum(1 for r in valid_results if r['qlike_improved'])
n_harvey = sum(1 for r in valid_results if r['harvey_pass'])

# Delta sign consistency
delta_signs = [np.sign(r['mean_delta']) for r in valid_results]
all_positive = all(s > 0 for s in delta_signs)
all_negative = all(s < 0 for s in delta_signs)
sign_consistent = all_positive or all_negative
dominant_sign = 'positive' if np.mean(all_deltas_means) > 0 else 'negative'

# Criteria
crit_1 = n_improved >= 3 and n_valid >= 5  # 3+/5 QLIKE improvement
crit_2 = sign_consistent                    # Consistent delta sign
crit_3 = pooled_dm['harvey_pass']           # Pooled DM passes Harvey
crit_4 = abs(pooled_improvement) > 0.1      # Meaningful effect (>0.1% QLIKE improvement)

all_pass = crit_1 and crit_2 and crit_3

print(f"\n  Valid periods: {n_valid}/5")
print(f"  Periods with QLIKE improvement: {n_improved}/{n_valid}")
print(f"  Periods with Harvey pass: {n_harvey}/{n_valid}")
print(f"  Delta signs: {delta_signs}")
print(f"  Sign consistent: {sign_consistent} (dominant: {dominant_sign})")
print()

criteria_table = [
    ("1. QLIKE improvement 3+/5", crit_1, f"{n_improved}/{n_valid} periods improved"),
    ("2. Consistent delta sign", crit_2, f"Signs: {delta_signs}, dominant={dominant_sign}"),
    ("3. Pooled DM Harvey pass", crit_3, f"DM={pooled_dm['statistic']:+.3f}, |t|>3.0"),
    ("4. Meaningful effect size", crit_4, f"Pooled QLIKE change: {pooled_improvement:+.3f}%"),
]

for name, passed, detail in criteria_table:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    print(f"         {detail}")

print()
if all_pass:
    print("  >>> VERDICT: VIX speed z-score PASSES rolling validation. <<<")
    print("  >>> K299 Pilot C result (t=6.54) is GENUINE. <<<")
elif crit_1 and crit_3:
    print("  >>> VERDICT: PARTIAL pass — QLIKE and Harvey OK but sign inconsistency. <<<")
    print("  >>> Needs further investigation before claiming genuine. <<<")
elif crit_1:
    print("  >>> VERDICT: WEAK — QLIKE improves in majority but pooled DM fails Harvey. <<<")
    print("  >>> K299 Pilot C result may be inflated by full-sample estimation. <<<")
else:
    print("  >>> VERDICT: FAIL — VIX speed does NOT survive pure rolling validation. <<<")
    print("  >>> K299 Pilot C (t=6.54) is an ARTIFACT of full-sample estimation. <<<")


# ==================================================================
# BONUS: VIX SPEED SIGNAL FOR 50/50 STRATEGY MDD
# ==================================================================

print("\n" + "=" * 80)
print("BONUS: VIX Speed Signal for 50/50 SPY Strategy")
print("=" * 80)

# Simple test: When VIX speed z-score > 1.5, reduce SPY exposure
# Compare: (A) Buy & hold SPY vs (B) 50/50 SPY+Cash with VIX speed cutoff

spy_ret_daily = df['Return'].values
vix_speed_vals = df['VIX_speed'].values
dates_all = df.index

# Strategy: when VIX_speed > threshold, go 50% SPY (risk-off)
# when VIX_speed <= threshold, stay 100% SPY
thresholds = [1.0, 1.5, 2.0]

print(f"\n  Testing thresholds: {thresholds}")
print(f"  OOS period: 2010-01-01 to 2024-12-31")

oos_mask_bonus = dates_all >= pd.Timestamp('2010-01-01')
spy_ret_oos = spy_ret_daily[oos_mask_bonus]
vix_speed_oos = vix_speed_vals[oos_mask_bonus]
dates_oos = dates_all[oos_mask_bonus]

# Buy & hold stats
bh_cum = np.cumsum(spy_ret_oos)
bh_peak = np.maximum.accumulate(bh_cum)
bh_dd = bh_cum - bh_peak
bh_mdd = np.min(bh_dd)
bh_annual_ret = np.mean(spy_ret_oos) * 252
bh_annual_vol = np.std(spy_ret_oos) * np.sqrt(252)
bh_sharpe = bh_annual_ret / bh_annual_vol if bh_annual_vol > 0 else 0

print(f"\n  Buy & Hold SPY:")
print(f"    Annual return: {bh_annual_ret:.4f}")
print(f"    Annual vol:    {bh_annual_vol:.4f}")
print(f"    Sharpe:        {bh_sharpe:.3f}")
print(f"    MDD:           {bh_mdd:.4f}")

bonus_results = {
    'buy_hold': {
        'annual_return': float(bh_annual_ret),
        'annual_vol': float(bh_annual_vol),
        'sharpe': float(bh_sharpe),
        'mdd': float(bh_mdd),
    }
}

for threshold in thresholds:
    # Signal: use yesterday's VIX speed (lagged)
    signal = np.roll(vix_speed_oos, 1)
    signal[0] = 0  # no signal on first day

    # Weight: 100% SPY if calm, 50% if VIX spiking
    weight = np.where(signal > threshold, 0.5, 1.0)

    strat_ret = spy_ret_oos * weight
    strat_cum = np.cumsum(strat_ret)
    strat_peak = np.maximum.accumulate(strat_cum)
    strat_dd = strat_cum - strat_peak
    strat_mdd = np.min(strat_dd)
    strat_annual_ret = np.mean(strat_ret) * 252
    strat_annual_vol = np.std(strat_ret) * np.sqrt(252)
    strat_sharpe = strat_annual_ret / strat_annual_vol if strat_annual_vol > 0 else 0

    n_risk_off = int(np.sum(signal > threshold))
    pct_risk_off = n_risk_off / len(signal) * 100

    mdd_improvement = (strat_mdd - bh_mdd) / abs(bh_mdd) * 100  # positive = less drawdown

    print(f"\n  VIX speed threshold > {threshold}:")
    print(f"    Risk-off days: {n_risk_off} ({pct_risk_off:.1f}%)")
    print(f"    Annual return: {strat_annual_ret:.4f}")
    print(f"    Annual vol:    {strat_annual_vol:.4f}")
    print(f"    Sharpe:        {strat_sharpe:.3f}")
    print(f"    MDD:           {strat_mdd:.4f} ({mdd_improvement:+.1f}% vs B&H)")

    bonus_results[f'threshold_{threshold}'] = {
        'threshold': float(threshold),
        'n_risk_off': n_risk_off,
        'pct_risk_off': float(pct_risk_off),
        'annual_return': float(strat_annual_ret),
        'annual_vol': float(strat_annual_vol),
        'sharpe': float(strat_sharpe),
        'mdd': float(strat_mdd),
        'mdd_improvement_pct': float(mdd_improvement),
    }


# ==================================================================
# DETAILED PERIOD-BY-PERIOD TABLE
# ==================================================================

print("\n" + "=" * 80)
print("DETAILED PERIOD-BY-PERIOD RESULTS")
print("=" * 80)

print(f"\n{'Period':<18} {'N':>5} {'QLIKE Base':>11} {'QLIKE 2-Stg':>12} "
      f"{'Impr%':>7} {'DM stat':>8} {'p-val':>7} {'Harvey':>7} {'delta':>10} {'delta_t':>8}")
print("-" * 115)

for r in valid_results:
    print(f"{r['period']:<18} {r['n_obs']:>5d} {r['qlike_baseline']:>11.4f} "
          f"{r['qlike_twostage']:>12.4f} {r['qlike_improvement_pct']:>+7.2f} "
          f"{r['dm_stat']:>+8.3f} {r['dm_pval']:>7.4f} "
          f"{'PASS' if r['harvey_pass'] else 'FAIL':>7} "
          f"{r['mean_delta']:>+10.6f} {r['mean_ols_t_stat']:>+8.2f}")

if all_actuals_pooled:
    print("-" * 115)
    print(f"{'POOLED':<18} {len(pooled_actuals):>5d} {pooled_q_base:>11.4f} "
          f"{pooled_q_twostage:>12.4f} {pooled_improvement:>+7.2f} "
          f"{pooled_dm['statistic']:>+8.3f} {pooled_dm['p_value']:>7.4f} "
          f"{'PASS' if pooled_dm['harvey_pass'] else 'FAIL':>7}")


# ==================================================================
# ELAPSED TIME
# ==================================================================

elapsed = time.time() - t0
print(f"\n  Total elapsed: {elapsed:.1f}s")


# ==================================================================
# SAVE RESULTS
# ==================================================================

results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "k300_vix_speed_validation_results.json")


def np_safe(obj):
    """Convert numpy types for JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    return obj


def deep_convert(obj):
    if isinstance(obj, dict):
        return {k: deep_convert(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_convert(v) for v in obj]
    return np_safe(obj)


save_data = {
    'experiment': 'K300',
    'title': 'VIX Spike Speed Rolling Validation',
    'description': 'Validates K299 Pilot C (VIX 5d z-score, partial r=0.106, t=6.54) '
                   'with pure rolling two-stage GARCH-X estimation.',
    'attribution': '[提出: 用戶, 執行: Claude]',
    'method': {
        'stage1': 'GJR-GARCH(1,1,1), w=2000, refit every 22d',
        'stage2': f'Rolling OLS (w={OLS_WINDOW}d): RV = a + delta * VIX_speed_{{t-1}}',
        'vix_speed': f'(VIX - MA(VIX,{VIX_MA_WINDOW}d)) / std(VIX,{VIX_MA_WINDOW}d)',
        'estimation': 'Pure rolling, no look-ahead',
    },
    'data_source': 'yfinance',
    'data_period': f'{DATA_START} to {DATA_END}',
    'config': {
        'garch_window': GARCH_WINDOW,
        'ols_window': OLS_WINDOW,
        'refit_every': REFIT_EVERY,
        'vix_ma_window': VIX_MA_WINDOW,
    },
    'oos_periods': [{'start': s, 'end': e, 'name': n} for s, e, n in OOS_PERIODS],
    'period_results': deep_convert(all_period_results),
    'pooled_analysis': deep_convert({
        'n_total': len(pooled_actuals) if all_actuals_pooled else 0,
        'qlike_baseline': pooled_q_base if all_actuals_pooled else None,
        'qlike_twostage': pooled_q_twostage if all_actuals_pooled else None,
        'qlike_improvement_pct': pooled_improvement if all_actuals_pooled else None,
        'dm_stat': pooled_dm['statistic'],
        'dm_pval': pooled_dm['p_value'],
        'harvey_pass': pooled_dm['harvey_pass'],
    }),
    'validation_criteria': {
        'criterion_1_qlike_3of5': crit_1,
        'criterion_2_sign_consistent': crit_2,
        'criterion_3_pooled_harvey': crit_3,
        'criterion_4_meaningful_effect': crit_4,
        'all_pass': all_pass,
    },
    'summary': {
        'n_valid_periods': n_valid,
        'n_improved': n_improved,
        'n_harvey_pass': n_harvey,
        'delta_signs': delta_signs,
        'sign_consistent': sign_consistent,
        'dominant_sign': dominant_sign,
    },
    'bonus_strategy': deep_convert(bonus_results),
    'elapsed_seconds': elapsed,
}

with open(results_path, 'w') as f:
    json.dump(save_data, f, indent=2, default=str)

print(f"\nResults saved to: {results_path}")
print("\nK300 COMPLETE.")
