"""
K435: Structural Break Detection + Adaptive GARCH
==================================================

Research Questions:
1. Does SPY volatility have structural breaks? Where?
2. Does per-regime GARCH reduce persistence (Hillebrand 2005 effect)?
3. Does adaptive GARCH (re-estimate after break) improve OOS forecasting?

Literature:
- Hasanov (2024) "Structural breaks and GARCH models of exchange rate volatility" JAE
  - Models incorporating structural breaks universally outperform those ignoring breaks
- Hillebrand (2005) "Neglecting parameter changes in GARCH models" J. Econometrics
  - Ignoring structural breaks inflates GARCH persistence (spurious IGARCH effect)
- Inclán & Tiao (1994) "Use of cumulative sums of squares for retrospective detection
  of changes of variance" JASA
  - ICSS algorithm for detecting variance change points

Prior Knowledge:
- SPY GARCH persistence typically 0.94-0.98 (multiple K-entries)
- TLT persistence dropped 0.96→0.67 in 2023 (structural break from Fed policy)
- SPY persistence remarkably stable (std 0.007-0.012) vs TLT (std 0.039-0.214)
- K427: SPY-TLT correlation had structural break in 2020 (Chow F=74.4)

Data: SPY 2005-01-01 to 2026-03-25 (yfinance)
OOS: 2023-01-01 to 2024-12-31

Author: [提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import json
import warnings
from datetime import datetime, timezone
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# STEP 0: Data Download
# ============================================================
print("=" * 70)
print("K435: Structural Break Detection + Adaptive GARCH")
print("=" * 70)

import yfinance as yf

ticker = "SPY"
data = yf.download(ticker, start="2005-01-01", end="2026-03-26", progress=False)
if isinstance(data.columns, pd.MultiIndex):
    data.columns = data.columns.get_level_values(0)

# Handle both old and new yfinance column names
if 'Adj Close' in data.columns:
    prices = data['Adj Close'].dropna()
elif 'Close' in data.columns:
    prices = data['Close'].dropna()
else:
    raise KeyError(f"No price column found. Available: {list(data.columns)}")
returns = np.log(prices / prices.shift(1)).dropna() * 100  # percentage log returns

print(f"\nData: {ticker}")
print(f"Period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
print(f"Observations: {len(returns)}")

# ============================================================
# STEP 0.5: Descriptive Statistics + Diagnostic Tests
# ============================================================
print("\n" + "=" * 70)
print("STEP 0.5: Data Diagnostics (per CLAUDE.md rule #4)")
print("=" * 70)

from scipy.stats import jarque_bera, kurtosis, skew
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

desc_stats = {
    'mean': float(returns.mean()),
    'std': float(returns.std()),
    'skewness': float(skew(returns)),
    'kurtosis': float(kurtosis(returns, fisher=True)),  # excess kurtosis
    'min': float(returns.min()),
    'max': float(returns.max()),
    'n': len(returns)
}
print(f"\nDescriptive Statistics:")
for k, v in desc_stats.items():
    print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

# ADF test
adf_stat, adf_pval, _, _, _, _ = adfuller(returns, maxlag=20)
print(f"\nADF test: stat={adf_stat:.4f}, p-value={adf_pval:.6f}")
print(f"  → Returns are {'stationary' if adf_pval < 0.05 else 'NON-STATIONARY (WARNING)'}")

# ARCH LM test
arch_lm = het_arch(returns, nlags=10)
print(f"\nARCH LM test (10 lags): stat={arch_lm[0]:.4f}, p-value={arch_lm[1]:.6f}")
print(f"  → ARCH effects {'present' if arch_lm[1] < 0.05 else 'NOT present (WARNING)'}")

# Ljung-Box test
lb_result = acorr_ljungbox(returns, lags=[10], return_df=True)
lb_stat = lb_result['lb_stat'].values[0]
lb_pval = lb_result['lb_pvalue'].values[0]
print(f"\nLjung-Box test (10 lags): stat={lb_stat:.4f}, p-value={lb_pval:.6f}")

# Ljung-Box on squared returns
lb_sq = acorr_ljungbox(returns**2, lags=[10], return_df=True)
lb_sq_stat = lb_sq['lb_stat'].values[0]
lb_sq_pval = lb_sq['lb_pvalue'].values[0]
print(f"Ljung-Box on r² (10 lags): stat={lb_sq_stat:.4f}, p-value={lb_sq_pval:.6f}")
print(f"  → Volatility clustering {'confirmed' if lb_sq_pval < 0.05 else 'NOT confirmed (WARNING)'}")

# Jarque-Bera
jb_stat, jb_pval = jarque_bera(returns)
print(f"\nJarque-Bera: stat={jb_stat:.4f}, p-value={jb_pval:.6f}")
print(f"  → {'Non-normal' if jb_pval < 0.05 else 'Normal'} distribution")

diagnostics = {
    'descriptive': desc_stats,
    'adf_stat': float(adf_stat),
    'adf_pval': float(adf_pval),
    'arch_lm_stat': float(arch_lm[0]),
    'arch_lm_pval': float(arch_lm[1]),
    'ljungbox_stat': float(lb_stat),
    'ljungbox_pval': float(lb_pval),
    'ljungbox_sq_stat': float(lb_sq_stat),
    'ljungbox_sq_pval': float(lb_sq_pval),
    'jarque_bera_stat': float(jb_stat),
    'jarque_bera_pval': float(jb_pval)
}

# ============================================================
# STEP 1: ICSS Structural Break Detection
# ============================================================
print("\n" + "=" * 70)
print("STEP 1: ICSS Algorithm (Inclán & Tiao 1994)")
print("=" * 70)


def icss_detect(returns_array, alpha=0.05, min_segment=126):
    """
    Inclán & Tiao (1994) ICSS algorithm for detecting variance change points.

    The test statistic D_k = (C_k / C_T) - k/T where C_k = sum(r_i^2, i=1..k)
    Under H0 (no break), max|D_k| * sqrt(T/2) ~ Kolmogorov-Smirnov distribution.
    Critical value at 5%: 1.358 (from I&T 1994, Table 1).

    Parameters:
        returns_array: array of returns
        alpha: significance level (0.05 → critical value 1.358)
        min_segment: minimum segment length between breaks

    Returns:
        list of breakpoint indices
    """
    # Critical values from Inclán & Tiao (1994) Table 1
    critical_values = {0.10: 1.224, 0.05: 1.358, 0.01: 1.628}
    cv = critical_values.get(alpha, 1.358)

    r = np.asarray(returns_array, dtype=np.float64)
    n = len(r)
    r2 = r ** 2

    def find_break(r2_seg, offset=0):
        """Find single most significant break in a segment."""
        T = len(r2_seg)
        if T < 2 * min_segment:
            return None, 0.0

        C = np.cumsum(r2_seg)
        C_T = C[-1]
        if C_T == 0:
            return None, 0.0

        k = np.arange(1, T + 1)
        D = C / C_T - k / T

        # Restrict to valid range (min_segment from each end)
        valid_start = min_segment
        valid_end = T - min_segment
        if valid_start >= valid_end:
            return None, 0.0

        D_valid = D[valid_start:valid_end]
        abs_D = np.abs(D_valid)

        max_idx = np.argmax(abs_D)
        max_D = abs_D[max_idx]
        test_stat = max_D * np.sqrt(T / 2)

        if test_stat > cv:
            bp = valid_start + max_idx + offset
            return bp, test_stat
        return None, 0.0

    # Iterative procedure to find all breaks
    breakpoints = []
    segments = [(0, n)]

    max_iter = 20  # safety limit
    for iteration in range(max_iter):
        new_segments = []
        found_new = False

        for seg_start, seg_end in segments:
            seg_r2 = r2[seg_start:seg_end]
            bp, stat = find_break(seg_r2, offset=seg_start)

            if bp is not None:
                breakpoints.append((bp, stat))
                found_new = True
                # Split segment at breakpoint
                new_segments.append((seg_start, bp))
                new_segments.append((bp, seg_end))
            else:
                new_segments.append((seg_start, seg_end))

        segments = new_segments
        if not found_new:
            break

    # Sort and deduplicate
    breakpoints = sorted(set(breakpoints), key=lambda x: x[0])

    # Remove breakpoints too close together
    if len(breakpoints) > 1:
        filtered = [breakpoints[0]]
        for bp, stat in breakpoints[1:]:
            if bp - filtered[-1][0] >= min_segment:
                filtered.append((bp, stat))
            elif stat > filtered[-1][1]:
                filtered[-1] = (bp, stat)
        breakpoints = filtered

    return breakpoints


# Run ICSS
returns_array = returns.values
breakpoints = icss_detect(returns_array, alpha=0.05, min_segment=126)

print(f"\nICSS detected {len(breakpoints)} structural break(s) at 5% level:")
print(f"(min_segment = 126 trading days = ~6 months)")

break_info = []
for bp_idx, stat in breakpoints:
    bp_date = returns.index[bp_idx]
    # Compute variance before and after
    var_before = np.var(returns_array[max(0, bp_idx-252):bp_idx])
    var_after = np.var(returns_array[bp_idx:min(len(returns_array), bp_idx+252)])
    vol_before = np.sqrt(var_before) * np.sqrt(252)
    vol_after = np.sqrt(var_after) * np.sqrt(252)

    info = {
        'index': int(bp_idx),
        'date': bp_date.strftime('%Y-%m-%d'),
        'test_statistic': float(stat),
        'critical_value': 1.358,
        'vol_before_ann': float(vol_before),
        'vol_after_ann': float(vol_after),
        'vol_ratio': float(vol_after / vol_before) if vol_before > 0 else None
    }
    break_info.append(info)
    print(f"\n  Break #{len(break_info)}:")
    print(f"    Date: {info['date']}")
    print(f"    Test stat: {info['test_statistic']:.3f} (critical: 1.358)")
    print(f"    Vol before (ann): {info['vol_before_ann']:.1f}%")
    print(f"    Vol after (ann):  {info['vol_after_ann']:.1f}%")
    print(f"    Vol ratio: {info['vol_ratio']:.2f}x")

# Also run with more liberal threshold to see borderline breaks
breakpoints_10 = icss_detect(returns_array, alpha=0.10, min_segment=126)
if len(breakpoints_10) > len(breakpoints):
    print(f"\n  (At 10% level: {len(breakpoints_10)} breaks detected)")
    for bp_idx, stat in breakpoints_10:
        if (bp_idx, stat) not in breakpoints:
            bp_date = returns.index[bp_idx]
            print(f"    Additional at 10%: {bp_date.strftime('%Y-%m-%d')} (stat={stat:.3f})")

# ============================================================
# STEP 1b: CUSUM-of-squares test for variance stability
# ============================================================
print("\n\n--- CUSUM-of-squares supplementary test ---")

r2_array = returns_array ** 2
n = len(r2_array)
C = np.cumsum(r2_array)
C_T = C[-1]
W = C / C_T  # normalized CUSUM of squares
k = np.arange(1, n + 1)
expected = k / n
deviations = W - expected

max_dev = np.max(np.abs(deviations))
# Under H0, max|W_k - k/T| has known critical values
# Approximate: critical value ≈ 0.12238 / sqrt(T) + 1.143 (Brown, Durbin, Evans 1975)
# Actually for large T, use Kolmogorov-Smirnov: 1.36/sqrt(T) at 5%
ks_cv_05 = 1.36 / np.sqrt(n)
print(f"Max |CUSUM-sq deviation|: {max_dev:.6f}")
print(f"KS critical (5%): {ks_cv_05:.6f}")
print(f"→ {'REJECT H0: variance is NOT stable' if max_dev > ks_cv_05 else 'Cannot reject H0: variance appears stable'}")

# ============================================================
# STEP 2: Per-regime GARCH estimation
# ============================================================
print("\n" + "=" * 70)
print("STEP 2: Per-regime GJR-GARCH(1,1) Estimation")
print("=" * 70)

# Define regimes based on detected breaks
regime_bounds = [0] + [bp[0] for bp in breakpoints] + [len(returns_array)]
regime_names = []
for i in range(len(regime_bounds) - 1):
    start_date = returns.index[regime_bounds[i]].strftime('%Y-%m-%d')
    end_date = returns.index[min(regime_bounds[i+1]-1, len(returns)-1)].strftime('%Y-%m-%d')
    regime_names.append(f"Regime {i+1}: {start_date} to {end_date}")

print(f"\n{len(regime_names)} regimes identified:")
for name in regime_names:
    print(f"  {name}")


def fit_gjr_garch(ret_series, name=""):
    """Fit GJR-GARCH(1,1) with Normal innovations."""
    try:
        am = arch_model(ret_series, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False)

        params = {
            'omega': float(res.params.get('omega', np.nan)),
            'alpha': float(res.params.get('alpha[1]', np.nan)),
            'gamma': float(res.params.get('gamma[1]', np.nan)),
            'beta': float(res.params.get('beta[1]', np.nan)),
        }
        params['persistence'] = params['alpha'] + params['gamma'] / 2 + params['beta']
        params['converged'] = bool(res.convergence_flag == 0)
        params['loglik'] = float(res.loglikelihood)
        params['n_obs'] = int(res.nobs)
        params['unconditional_vol_ann'] = float(np.sqrt(res.conditional_volatility.mean()**2) * np.sqrt(252))

        # Residual diagnostics
        std_resid = res.resid / res.conditional_volatility
        arch_lm_resid = het_arch(std_resid.dropna(), nlags=5)
        params['resid_arch_lm_pval'] = float(arch_lm_resid[1])
        params['resid_arch_remaining'] = bool(arch_lm_resid[1] < 0.05)

        return params, res
    except Exception as e:
        print(f"  WARNING: Failed to fit {name}: {e}")
        return None, None


# Fit full-sample GARCH
print("\n--- Full-sample GJR-GARCH(1,1) ---")
full_params, full_res = fit_gjr_garch(returns, "Full Sample")
if full_params:
    print(f"  omega={full_params['omega']:.6f}, alpha={full_params['alpha']:.4f}, "
          f"gamma={full_params['gamma']:.4f}, beta={full_params['beta']:.4f}")
    print(f"  persistence={full_params['persistence']:.4f}")
    print(f"  converged={full_params['converged']}, loglik={full_params['loglik']:.2f}")
    print(f"  unconditional vol (ann): {full_params['unconditional_vol_ann']:.1f}%")
    print(f"  residual ARCH LM p-val: {full_params['resid_arch_lm_pval']:.4f} "
          f"({'remaining ARCH!' if full_params['resid_arch_remaining'] else 'clean'})")

# Fit per-regime GARCH
regime_params = {}
print("\n--- Per-regime GJR-GARCH(1,1) ---")
for i in range(len(regime_bounds) - 1):
    start_idx = regime_bounds[i]
    end_idx = regime_bounds[i + 1]
    regime_ret = returns.iloc[start_idx:end_idx]

    name = regime_names[i]
    n_obs = len(regime_ret)
    print(f"\n  {name} (n={n_obs}):")

    if n_obs < 252:
        print(f"    SKIP: too few observations ({n_obs} < 252)")
        regime_params[name] = {'skipped': True, 'n_obs': n_obs, 'reason': 'too few observations'}
        continue

    params, res = fit_gjr_garch(regime_ret, name)
    if params:
        regime_params[name] = params
        print(f"    omega={params['omega']:.6f}, alpha={params['alpha']:.4f}, "
              f"gamma={params['gamma']:.4f}, beta={params['beta']:.4f}")
        print(f"    persistence={params['persistence']:.4f}")
        print(f"    converged={params['converged']}")
        print(f"    unconditional vol (ann): {params['unconditional_vol_ann']:.1f}%")
        print(f"    residual ARCH LM p-val: {params['resid_arch_lm_pval']:.4f}")
    else:
        regime_params[name] = {'failed': True}

# Hillebrand (2005) test: compare persistence
print("\n\n--- Hillebrand (2005) Persistence Comparison ---")
print(f"Full-sample persistence: {full_params['persistence']:.4f}")
regime_persistences = []
for name, params in regime_params.items():
    if isinstance(params, dict) and 'persistence' in params:
        regime_persistences.append(params['persistence'])
        print(f"  {name}: persistence={params['persistence']:.4f}")

if regime_persistences:
    avg_regime_pers = np.mean(regime_persistences)
    print(f"\nAverage regime persistence: {avg_regime_pers:.4f}")
    print(f"Full-sample persistence:   {full_params['persistence']:.4f}")
    pers_diff = full_params['persistence'] - avg_regime_pers
    print(f"Difference (full - avg regime): {pers_diff:.4f}")
    if pers_diff > 0.01:
        print(f"→ CONFIRMED: Full-sample persistence inflated by {pers_diff:.4f}")
        print(f"  (Hillebrand 2005 spurious IGARCH effect)")
    else:
        print(f"→ Persistence inflation is minimal ({pers_diff:.4f})")
        print(f"  (Hillebrand effect not pronounced for SPY)")

hillebrand_result = {
    'full_sample_persistence': float(full_params['persistence']),
    'avg_regime_persistence': float(avg_regime_pers) if regime_persistences else None,
    'persistence_difference': float(pers_diff) if regime_persistences else None,
    'hillebrand_effect_confirmed': bool(pers_diff > 0.01) if regime_persistences else None
}

# ============================================================
# STEP 3: Adaptive GARCH OOS Forecasting
# ============================================================
print("\n" + "=" * 70)
print("STEP 3: Adaptive GARCH OOS Forecasting")
print("=" * 70)

oos_start = '2023-01-01'
oos_end = '2024-12-31'

# Find OOS indices
oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
oos_indices = np.where(oos_mask)[0]
oos_dates = returns.index[oos_mask]

print(f"\nOOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {len(oos_indices)}")

# Realized variance (proxy: squared returns)
realized_var = returns_array ** 2

# Strategy 1: Standard (fixed window=2000, ignore breaks)
# Strategy 2: Post-break (use only data after most recent break)
# Strategy 3: Adaptive (detect break in expanding window, reset if break found)

print("\n--- Running 3 forecasting strategies ---")

BASE_WINDOW = 2000
MIN_WINDOW = 504  # minimum window after break reset

forecasts_standard = []
forecasts_postbreak = []
forecasts_adaptive = []

# Pre-compute break dates within the estimation window
break_indices_set = set(bp[0] for bp in breakpoints)

n_oos = len(oos_indices)
progress_marks = set([int(n_oos * p) for p in [0.25, 0.5, 0.75, 1.0]])

for count, t in enumerate(oos_indices):
    if count in progress_marks:
        print(f"  Progress: {count}/{n_oos} ({100*count/n_oos:.0f}%)")

    # --- Strategy 1: Standard (fixed window) ---
    start_std = max(0, t - BASE_WINDOW)
    ret_std = returns.iloc[start_std:t]
    try:
        am = arch_model(ret_std, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False, options={'maxiter': 200})
        fc = res.forecast(horizon=1)
        forecasts_standard.append(float(fc.variance.values[-1, 0]))
    except:
        forecasts_standard.append(float(ret_std.var()))

    # --- Strategy 2: Post-break (use data after most recent break) ---
    # Find the most recent break before time t
    recent_break = None
    for bp_idx, _ in breakpoints:
        if bp_idx < t:
            recent_break = bp_idx

    if recent_break is not None and (t - recent_break) >= MIN_WINDOW:
        start_pb = recent_break
    else:
        start_pb = max(0, t - BASE_WINDOW)

    ret_pb = returns.iloc[start_pb:t]
    try:
        am = arch_model(ret_pb, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False, options={'maxiter': 200})
        fc = res.forecast(horizon=1)
        forecasts_postbreak.append(float(fc.variance.values[-1, 0]))
    except:
        forecasts_postbreak.append(float(ret_pb.var()))

    # --- Strategy 3: Adaptive (online break detection + reset) ---
    # Use expanding window, but run ICSS periodically to check for breaks
    # For efficiency, we run ICSS every 63 days (quarterly) on the estimation window

    if count == 0:
        adaptive_start = max(0, t - BASE_WINDOW)
        last_icss_check = 0

    if count - last_icss_check >= 63 or count == 0:
        # Run ICSS on current estimation window
        est_data = returns_array[adaptive_start:t]
        if len(est_data) > 504:
            new_breaks = icss_detect(est_data, alpha=0.05, min_segment=126)
            if new_breaks:
                # Use data from the last detected break onward
                last_bp = new_breaks[-1][0]
                candidate_start = adaptive_start + last_bp
                if t - candidate_start >= MIN_WINDOW:
                    adaptive_start = candidate_start
        last_icss_check = count

    ret_adp = returns.iloc[adaptive_start:t]
    try:
        am = arch_model(ret_adp, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False, options={'maxiter': 200})
        fc = res.forecast(horizon=1)
        forecasts_adaptive.append(float(fc.variance.values[-1, 0]))
    except:
        forecasts_adaptive.append(float(ret_adp.var()))

print(f"  Done: {n_oos}/{n_oos} (100%)")

# Convert to arrays
f_std = np.array(forecasts_standard)
f_pb = np.array(forecasts_postbreak)
f_adp = np.array(forecasts_adaptive)
rv_oos = realized_var[oos_indices]

# ============================================================
# STEP 4: OOS Evaluation
# ============================================================
print("\n" + "=" * 70)
print("STEP 4: OOS Evaluation")
print("=" * 70)


def qlike(realized, forecast):
    """QLIKE loss: mean(rv/fv - log(rv/fv) - 1)"""
    ratio = realized / forecast
    valid = (ratio > 0) & np.isfinite(ratio)
    return float(np.mean(ratio[valid] - np.log(ratio[valid]) - 1))


def mse(realized, forecast):
    """Mean Squared Error"""
    return float(np.mean((realized - forecast)**2))


def mae(realized, forecast):
    """Mean Absolute Error"""
    return float(np.mean(np.abs(realized - forecast)))


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative t-stat → loss1 < loss2 → model 1 better
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West variance (with h-1 lags for h-step forecasts)
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for j in range(1, h):
        gamma_j = np.cov(d[j:], d[:-j])[0, 1]
        nw_var += 2 * (1 - j/h) * gamma_j

    se = np.sqrt(nw_var / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return float(t_stat), float(p_val)


# QLIKE losses per observation (for DM test)
def qlike_loss_series(realized, forecast):
    ratio = realized / forecast
    valid = np.isfinite(ratio) & (ratio > 0)
    losses = np.where(valid, ratio - np.log(ratio) - 1, np.nan)
    return losses


# Compute metrics
strategies = {
    'Standard (w=2000)': f_std,
    'Post-break': f_pb,
    'Adaptive': f_adp
}

oos_metrics = {}
print(f"\n{'Strategy':<25} {'QLIKE':<12} {'MSE':<14} {'MAE':<12}")
print("-" * 65)

for name, fc in strategies.items():
    q = qlike(rv_oos, fc)
    m = mse(rv_oos, fc)
    a = mae(rv_oos, fc)
    oos_metrics[name] = {'QLIKE': q, 'MSE': m, 'MAE': a}
    print(f"{name:<25} {q:<12.6f} {m:<14.8f} {a:<12.6f}")

# DM tests: adaptive vs standard, post-break vs standard
print("\n--- Diebold-Mariano Tests ---")

loss_std = qlike_loss_series(rv_oos, f_std)
loss_pb = qlike_loss_series(rv_oos, f_pb)
loss_adp = qlike_loss_series(rv_oos, f_adp)

# Clean NaNs for DM test
valid = np.isfinite(loss_std) & np.isfinite(loss_pb) & np.isfinite(loss_adp)

dm_adp_vs_std_t, dm_adp_vs_std_p = dm_test(loss_adp[valid], loss_std[valid])
dm_pb_vs_std_t, dm_pb_vs_std_p = dm_test(loss_pb[valid], loss_std[valid])
dm_adp_vs_pb_t, dm_adp_vs_pb_p = dm_test(loss_adp[valid], loss_pb[valid])

print(f"\n  Adaptive vs Standard:   DM t={dm_adp_vs_std_t:.4f}, p={dm_adp_vs_std_p:.4f}")
if dm_adp_vs_std_t < 0:
    print(f"    → Adaptive {'SIGNIFICANTLY' if dm_adp_vs_std_p < 0.05 else 'marginally'} better")
else:
    print(f"    → Standard {'SIGNIFICANTLY' if dm_adp_vs_std_p < 0.05 else 'marginally'} better")

print(f"\n  Post-break vs Standard: DM t={dm_pb_vs_std_t:.4f}, p={dm_pb_vs_std_p:.4f}")
if dm_pb_vs_std_t < 0:
    print(f"    → Post-break {'SIGNIFICANTLY' if dm_pb_vs_std_p < 0.05 else 'marginally'} better")
else:
    print(f"    → Standard {'SIGNIFICANTLY' if dm_pb_vs_std_p < 0.05 else 'marginally'} better")

print(f"\n  Adaptive vs Post-break: DM t={dm_adp_vs_pb_t:.4f}, p={dm_adp_vs_pb_p:.4f}")

dm_tests = {
    'adaptive_vs_standard': {'t_stat': dm_adp_vs_std_t, 'p_value': dm_adp_vs_std_p},
    'postbreak_vs_standard': {'t_stat': dm_pb_vs_std_t, 'p_value': dm_pb_vs_std_p},
    'adaptive_vs_postbreak': {'t_stat': dm_adp_vs_pb_t, 'p_value': dm_adp_vs_pb_p}
}

# Harvey threshold check
print(f"\n--- Harvey (2016) t>3.0 threshold ---")
for test_name, test_vals in dm_tests.items():
    passes = abs(test_vals['t_stat']) > 3.0
    print(f"  {test_name}: |t|={abs(test_vals['t_stat']):.4f} {'PASSES' if passes else 'FAILS'} Harvey threshold")

# ============================================================
# STEP 4b: Sub-period analysis (by regime)
# ============================================================
print("\n\n--- Sub-period OOS QLIKE (2023 vs 2024) ---")

oos_dates_arr = returns.index[oos_indices]
mask_2023 = oos_dates_arr.year == 2023
mask_2024 = oos_dates_arr.year == 2024

subperiod_metrics = {}
for year, mask in [('2023', mask_2023), ('2024', mask_2024)]:
    if mask.sum() > 0:
        sub_metrics = {}
        for name, fc in strategies.items():
            q = qlike(rv_oos[mask], fc[mask])
            sub_metrics[name] = q
        subperiod_metrics[year] = sub_metrics
        print(f"\n  {year}:")
        for name, q in sub_metrics.items():
            print(f"    {name:<25}: QLIKE={q:.6f}")

# ============================================================
# STEP 5: Rolling persistence analysis
# ============================================================
print("\n" + "=" * 70)
print("STEP 5: Rolling Persistence Analysis")
print("=" * 70)

# Estimate GJR-GARCH with rolling windows, track persistence over time
rolling_window = 504
step = 63  # quarterly
persistence_series = []

print(f"\nRolling GJR-GARCH (w={rolling_window}, step={step})...")

for start in range(0, len(returns) - rolling_window, step):
    end = start + rolling_window
    ret_win = returns.iloc[start:end]
    mid_date = returns.index[start + rolling_window // 2]

    try:
        am = arch_model(ret_win, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False, options={'maxiter': 200})

        alpha = float(res.params.get('alpha[1]', 0))
        gamma = float(res.params.get('gamma[1]', 0))
        beta = float(res.params.get('beta[1]', 0))
        pers = alpha + gamma / 2 + beta

        persistence_series.append({
            'date': mid_date.strftime('%Y-%m-%d'),
            'persistence': float(pers),
            'alpha': float(alpha),
            'gamma': float(gamma),
            'beta': float(beta)
        })
    except:
        pass

if persistence_series:
    pers_values = [p['persistence'] for p in persistence_series]
    print(f"\nPersistence statistics (n={len(pers_values)}):")
    print(f"  Mean: {np.mean(pers_values):.4f}")
    print(f"  Std:  {np.std(pers_values):.4f}")
    print(f"  Min:  {np.min(pers_values):.4f} (date: {persistence_series[np.argmin(pers_values)]['date']})")
    print(f"  Max:  {np.max(pers_values):.4f} (date: {persistence_series[np.argmax(pers_values)]['date']})")

    # Identify periods of unusually low persistence (potential breaks)
    mean_p = np.mean(pers_values)
    std_p = np.std(pers_values)
    outlier_low = [p for p in persistence_series if p['persistence'] < mean_p - 2 * std_p]
    outlier_high = [p for p in persistence_series if p['persistence'] > mean_p + 2 * std_p]

    if outlier_low:
        print(f"\n  Low persistence outliers (< mean - 2σ):")
        for p in outlier_low:
            print(f"    {p['date']}: persistence={p['persistence']:.4f}")
    if outlier_high:
        print(f"\n  High persistence outliers (> mean + 2σ):")
        for p in outlier_high:
            print(f"    {p['date']}: persistence={p['persistence']:.4f}")

# ============================================================
# STEP 6: Chow test for parameter stability across regimes
# ============================================================
print("\n" + "=" * 70)
print("STEP 6: Chow-type Test for GARCH Parameter Stability")
print("=" * 70)

# Compare log-likelihoods: unrestricted (sum of per-regime) vs restricted (full-sample)
if full_params and len([p for p in regime_params.values() if isinstance(p, dict) and 'loglik' in p]) >= 2:
    restricted_ll = full_params['loglik']
    unrestricted_ll = sum(p['loglik'] for p in regime_params.values() if isinstance(p, dict) and 'loglik' in p)

    # Number of parameters per regime: omega, alpha, gamma, beta, mu = 5
    n_params = 5
    n_regimes = len([p for p in regime_params.values() if isinstance(p, dict) and 'loglik' in p])
    df = (n_regimes - 1) * n_params  # degrees of freedom for LR test

    lr_stat = 2 * (unrestricted_ll - restricted_ll)
    lr_pval = 1 - stats.chi2.cdf(lr_stat, df)

    print(f"\nLikelihood Ratio Test for Parameter Stability:")
    print(f"  Restricted (full-sample) LL:  {restricted_ll:.2f}")
    print(f"  Unrestricted (per-regime) LL: {unrestricted_ll:.2f}")
    print(f"  LR statistic: {lr_stat:.2f}")
    print(f"  Degrees of freedom: {df}")
    print(f"  p-value: {lr_pval:.6f}")
    print(f"  → {'REJECT H0: Parameters differ across regimes' if lr_pval < 0.05 else 'Cannot reject H0: Parameters stable'}")

    chow_test = {
        'restricted_ll': float(restricted_ll),
        'unrestricted_ll': float(unrestricted_ll),
        'lr_statistic': float(lr_stat),
        'degrees_of_freedom': int(df),
        'p_value': float(lr_pval),
        'reject_stability': bool(lr_pval < 0.05)
    }
else:
    print("\n  Cannot perform test (insufficient regime estimates)")
    chow_test = {'note': 'insufficient regime estimates'}

# ============================================================
# CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Determine best strategy
best_strategy = min(oos_metrics, key=lambda x: oos_metrics[x]['QLIKE'])
worst_strategy = max(oos_metrics, key=lambda x: oos_metrics[x]['QLIKE'])

print(f"\n1. STRUCTURAL BREAKS:")
print(f"   ICSS detected {len(breakpoints)} break(s) in SPY 2005-2026")
if breakpoints:
    for info in break_info:
        print(f"   - {info['date']}: vol ratio = {info['vol_ratio']:.2f}x")
print(f"   CUSUM-sq test: variance is {'NOT stable' if max_dev > ks_cv_05 else 'stable'}")

print(f"\n2. HILLEBRAND (2005) PERSISTENCE EFFECT:")
if regime_persistences:
    print(f"   Full-sample persistence: {full_params['persistence']:.4f}")
    print(f"   Avg regime persistence:  {avg_regime_pers:.4f}")
    print(f"   Inflation: {pers_diff:.4f} ({'confirmed' if pers_diff > 0.01 else 'minimal'})")

print(f"\n3. OOS FORECASTING (2023-2024):")
print(f"   Best strategy: {best_strategy} (QLIKE={oos_metrics[best_strategy]['QLIKE']:.6f})")
print(f"   Worst strategy: {worst_strategy} (QLIKE={oos_metrics[worst_strategy]['QLIKE']:.6f})")
for test_name, test_vals in dm_tests.items():
    sig = "***" if test_vals['p_value'] < 0.01 else "**" if test_vals['p_value'] < 0.05 else "*" if test_vals['p_value'] < 0.10 else ""
    print(f"   DM {test_name}: t={test_vals['t_stat']:.4f}, p={test_vals['p_value']:.4f} {sig}")

# Overall assessment
sig_improvement = any(abs(v['t_stat']) > 3.0 for v in dm_tests.values())
practical_improvement = abs(oos_metrics['Standard (w=2000)']['QLIKE'] - oos_metrics['Adaptive']['QLIKE']) / abs(oos_metrics['Standard (w=2000)']['QLIKE'])

print(f"\n4. PRACTICAL SIGNIFICANCE:")
print(f"   QLIKE improvement (Adaptive vs Standard): {practical_improvement*100:.2f}%")
print(f"   Harvey (2016) threshold: {'PASSES' if sig_improvement else 'FAILS'}")

print(f"\n5. LIMITATIONS:")
print(f"   - Squared returns as RV proxy (noisy)")
print(f"   - Single asset (SPY)")
print(f"   - ICSS assumes IID within segments")
print(f"   - Adaptive ICSS check frequency (quarterly) is ad hoc")
print(f"   - Post-break window size cutoff ({MIN_WINDOW}) is ad hoc")

# ============================================================
# Save Results
# ============================================================
results = {
    'experiment_id': 'K435',
    'title': 'Structural Break Detection + Adaptive GARCH',
    'asset': 'SPY',
    'data_source': 'yfinance',
    'data_period': f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(returns),
    'oos_period': f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
    'oos_n': int(len(oos_indices)),
    'timestamp': datetime.now(timezone.utc).isoformat(),

    'diagnostics': diagnostics,

    'structural_breaks': {
        'method': 'ICSS (Inclán & Tiao 1994)',
        'significance_level': 0.05,
        'critical_value': 1.358,
        'min_segment': 126,
        'n_breaks': len(breakpoints),
        'breaks': break_info,
        'cusum_sq_max_deviation': float(max_dev),
        'cusum_sq_critical_value': float(ks_cv_05),
        'cusum_sq_reject_stability': bool(max_dev > ks_cv_05)
    },

    'garch_parameters': {
        'full_sample': full_params,
        'per_regime': {name: params for name, params in regime_params.items()},
        'hillebrand_effect': hillebrand_result
    },

    'oos_forecasting': {
        'strategies': oos_metrics,
        'best_strategy': best_strategy,
        'dm_tests': dm_tests,
        'harvey_threshold_passed': sig_improvement,
        'qlike_improvement_pct': float(practical_improvement * 100),
        'subperiod_qlike': subperiod_metrics
    },

    'rolling_persistence': {
        'window': rolling_window,
        'step': step,
        'n_estimates': len(persistence_series),
        'mean': float(np.mean(pers_values)) if persistence_series else None,
        'std': float(np.std(pers_values)) if persistence_series else None,
        'min': float(np.min(pers_values)) if persistence_series else None,
        'max': float(np.max(pers_values)) if persistence_series else None,
        'series': persistence_series[:10] + ['... truncated ...'] + persistence_series[-10:] if len(persistence_series) > 20 else persistence_series
    },

    'parameter_stability_test': chow_test,

    'references': [
        'Hasanov (2024) "Structural breaks and GARCH models of exchange rate volatility" JAE. DOI: 10.1002/jae.3091',
        'Hillebrand (2005) "Neglecting parameter changes in GARCH models" J. Econometrics',
        'Inclán & Tiao (1994) "Use of cumulative sums of squares for retrospective detection of changes of variance" JASA'
    ],

    'prior_knowledge': [
        'K427: SPY-TLT correlation structural break in 2020 (Chow F=74.4)',
        'SPY persistence typically 0.94-0.98 (std 0.007-0.012)',
        'TLT persistence dropped 0.96→0.67 in 2023 (Fed policy structural break)'
    ],

    'conclusion': '',
    'limitations': [
        'Squared returns as RV proxy (noisy)',
        'Single asset (SPY only)',
        'ICSS assumes IID within segments (violated by ARCH effects)',
        'Adaptive ICSS check frequency (quarterly) is ad hoc',
        f'Post-break minimum window ({MIN_WINDOW}) is ad hoc',
        'No bootstrap confidence intervals for QLIKE differences'
    ]
}

# Write conclusion based on results
if len(breakpoints) > 0:
    break_dates_str = ', '.join([b['date'] for b in break_info])
    results['conclusion'] = (
        f"ICSS detected {len(breakpoints)} structural break(s) in SPY volatility at: {break_dates_str}. "
        f"Hillebrand effect: full-sample persistence ({full_params['persistence']:.4f}) vs "
        f"avg regime persistence ({avg_regime_pers:.4f}), "
        f"difference = {pers_diff:.4f} ({'confirms' if pers_diff > 0.01 else 'does not confirm'} spurious IGARCH). "
        f"OOS forecasting: best = {best_strategy} (QLIKE={oos_metrics[best_strategy]['QLIKE']:.6f}), "
        f"QLIKE improvement = {practical_improvement*100:.2f}%. "
        f"DM test adaptive vs standard: t={dm_adp_vs_std_t:.4f}, p={dm_adp_vs_std_p:.4f}. "
        f"Harvey (2016) threshold: {'PASSES' if sig_improvement else 'FAILS'}."
    )
else:
    results['conclusion'] = (
        f"ICSS detected NO structural breaks in SPY volatility (2005-2026). "
        f"This is consistent with SPY's high persistence stability (std<0.02). "
        f"Adaptive GARCH offers no improvement over standard approach for SPY."
    )

# Save
import os
output_path = os.path.join(os.path.dirname(__file__), 'k435_structural_break_garch_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n\nResults saved to: {output_path}")
print("=" * 70)
print("K435 COMPLETE")
print("=" * 70)
