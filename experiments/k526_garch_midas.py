#!/usr/bin/env python3
"""
K526: GARCH-MIDAS for SPY Volatility Prediction
=================================================
[提出: 用戶, 執行: Claude]

Background:
  GARCH-MIDAS (Engle, Ghysels & Sohn, 2013) decomposes volatility into:
  - Short-run component g_t (daily GARCH dynamics)
  - Long-run component τ_t (driven by low-frequency macro/RV variables)

  This is fundamentally different from standard GARCH which mixes both
  frequencies into a single process. First GARCH-MIDAS experiment in
  our knowledge base.

Models:
  1. GARCH-MIDAS-RV: τ driven by log(monthly realized variance)
  2. GARCH-MIDAS-VIX: τ driven by log(monthly avg VIX)
  3. GJR-GARCH(1,1): benchmark (arch package)
  4. GARCH(1,1): simple benchmark (arch package)

Implementation (Engle, Ghysels & Sohn 2013):
  σ²_t = τ_t · g_t
  g_t = (1-α-β) + α·r²_{t-1}/τ_{t-1} + β·g_{t-1}
  log(τ_t) = m + θ · Σ φ_k(ω)·X_{t-k}
  φ_k(ω) = (1 - k/(K+1))^{ω-1} / Σ_j (1 - j/(K+1))^{ω-1}
  Estimated by MLE with vectorized computations.

Data: yfinance (SPY, ^VIX) — real market data

References:
  Engle, Ghysels & Sohn (2013) RFS 26(11):2471-2509
  Conrad & Loch (2015) JFQA 50(5):1141-1164
  Ghysels, Santa-Clara & Valkanov (2006) JoE
  K490: GJR-X(VIX9D) champion — current best for SPY
"""

import json
import warnings
import time
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize, stats
from numpy.linalg import lstsq
from numba import njit

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K526"
WINDOW = 2000
OOS_MIN = 252
MIDAS_K = 12        # 12 monthly lags (1 year of history)
MIDAS_DAYS = 22     # trading days per month
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

print("=" * 70)
print(f"{EXPERIMENT_ID}: GARCH-MIDAS for SPY Volatility Prediction")
print("  Engle, Ghysels & Sohn (2013) — Mixed Data Sampling")
print("=" * 70)

# ============================================================
# SECTION 1: DATA
# ============================================================
print("\n[1] Loading data...")

import yfinance as yf

spy = yf.download("SPY", start="2010-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2010-01-01", end="2025-01-01", progress=False)

if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['log_ret'])

vix_close = vix[['Close']].rename(columns={'Close': 'VIX'})
data = spy[['Close', 'log_ret']].join(vix_close, how='left')
data['VIX'] = data['VIX'].ffill()
data = data.dropna()

print(f"  SPY: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
print(f"  n={len(data)}")

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")

ret = data['log_ret'].values

desc = {
    'mean': float(np.mean(ret)),
    'std': float(np.std(ret)),
    'skewness': float(stats.skew(ret)),
    'kurtosis': float(stats.kurtosis(ret)),
    'n': int(len(ret))
}
print(f"  Mean={desc['mean']:.6f} Std={desc['std']:.6f} "
      f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.3f}")

jb_stat, jb_p = stats.jarque_bera(ret)
print(f"  JB={jb_stat:.0f} (p={jb_p:.2e})")

# ARCH LM
ret2 = ret ** 2
n_lm = len(ret2) - 10
X_lm = np.column_stack([np.ones(n_lm)] + [ret2[i:i+n_lm] for i in range(10)])
y_lm = ret2[10:]
b_lm = lstsq(X_lm, y_lm, rcond=None)[0]
r2_lm = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
print(f"  ARCH LM(10)={n_lm*r2_lm:.1f} → strong ARCH effects")

# ============================================================
# SECTION 3: MIDAS REGRESSORS
# ============================================================
print("\n[3] MIDAS regressors...")

data['rv_22d'] = data['log_ret'].rolling(MIDAS_DAYS).apply(
    lambda x: np.sum(x**2), raw=True)
data['vix_22d'] = data['VIX'].rolling(MIDAS_DAYS).mean()

# Log-transform for numerical stability
data['log_rv'] = np.log(data['rv_22d'])
data['log_vix'] = np.log(data['vix_22d'])

log_rv_arr = data['log_rv'].values.copy()
log_vix_arr = data['log_vix'].values.copy()

print(f"  log(RV_22d): mean={np.nanmean(log_rv_arr):.3f} std={np.nanstd(log_rv_arr):.3f}")
print(f"  log(VIX_22d): mean={np.nanmean(log_vix_arr):.3f} std={np.nanstd(log_vix_arr):.3f}")

# ============================================================
# SECTION 4: VECTORIZED GARCH-MIDAS (Numba-accelerated)
# ============================================================
print("\n[4] GARCH-MIDAS (Numba-accelerated)...")


@njit(cache=True)
def beta_weights_nb(K, omega):
    """One-parameter Beta polynomial weights (ω₁=1)."""
    w = np.empty(K)
    total = 0.0
    for k in range(K):
        val = max(1.0 - (k + 1.0) / (K + 1.0), 1e-10) ** (omega - 1.0)
        w[k] = val
        total += val
    if total > 0:
        for k in range(K):
            w[k] /= total
    else:
        for k in range(K):
            w[k] = 1.0 / K
    return w


@njit(cache=True)
def garch_midas_ll(params, returns, midas_reg, K, n_days):
    """
    Negative log-likelihood for GARCH-MIDAS.
    params = [m, theta, omega, alpha, beta]
    """
    m = params[0]
    theta = params[1]
    omega = params[2]
    alpha = params[3]
    beta = params[4]

    if alpha <= 0 or beta <= 0 or alpha + beta >= 0.9999:
        return 1e10
    if omega <= 0.5 or omega > 30.0:
        return 1e10

    T = len(returns)
    weights = beta_weights_nb(K, omega)
    start_idx = K * n_days
    omega_g = 1.0 - alpha - beta

    ll = 0.0
    n_valid = 0
    g = 1.0
    prev_tau = -1.0

    for t in range(start_idx, T):
        # Compute log(tau_t) = m + theta * sum(w_k * X_{t-k*n_days})
        midas_sum = 0.0
        ok = True
        for k in range(K):
            idx = t - (k + 1) * n_days
            if idx < 0:
                ok = False
                break
            x_val = midas_reg[idx]
            if x_val != x_val:  # isnan check for numba
                ok = False
                break
            midas_sum += weights[k] * x_val

        if not ok:
            continue

        log_tau = m + theta * midas_sum
        if log_tau > 5 or log_tau < -25:
            return 1e10
        tau = np.exp(log_tau)

        # Update g
        if prev_tau > 0 and t > start_idx:
            eps2_scaled = returns[t-1]**2 / prev_tau
            g = omega_g + alpha * eps2_scaled + beta * g
            if g <= 0 or g > 200:
                g = max(g, 0.001)
                g = min(g, 200)

        sigma2 = tau * g
        if sigma2 <= 0:
            return 1e10

        ll += -0.5 * (1.8378770664093453 + np.log(sigma2)
                      + returns[t]**2 / sigma2)
        n_valid += 1
        prev_tau = tau

    if n_valid < 100:
        return 1e10

    return -ll


@njit(cache=True)
def garch_midas_forecast(returns, midas_reg, m, theta, omega, alpha, beta,
                          K, n_days, start_idx, end_idx):
    """
    Compute 1-step-ahead conditional variance forecasts for [start_idx, end_idx).
    Returns: sigma2_forecast array.
    """
    T = end_idx
    weights = beta_weights_nb(K, omega)
    omega_g = 1.0 - alpha - beta
    min_idx = K * n_days

    sigma2_out = np.full(T, np.nan)
    g = 1.0
    prev_tau = -1.0

    # Warm up from min_idx to start_idx
    for t in range(min_idx, T):
        midas_sum = 0.0
        ok = True
        for k in range(K):
            idx = t - (k + 1) * n_days
            if idx < 0:
                ok = False
                break
            x_val = midas_reg[idx]
            if x_val != x_val:
                ok = False
                break
            midas_sum += weights[k] * x_val

        if not ok:
            continue

        tau = np.exp(m + theta * midas_sum)

        if prev_tau > 0 and t > min_idx:
            eps2_scaled = returns[t-1]**2 / prev_tau
            g = omega_g + alpha * eps2_scaled + beta * g
            g = max(min(g, 200), 0.001)

        sigma2 = tau * g
        if t >= start_idx:
            sigma2_out[t] = sigma2
        prev_tau = tau

    return sigma2_out


# JIT warm-up
print("  JIT compiling...")
_dummy_ret = np.random.randn(300) * 0.01
_dummy_reg = np.random.randn(300) * 0.5 - 7.0
_ = garch_midas_ll(np.array([-9.0, 0.1, 2.0, 0.05, 0.90]),
                    _dummy_ret, _dummy_reg, 12, 22)
_ = garch_midas_forecast(_dummy_ret, _dummy_reg, -9.0, 0.1, 2.0, 0.05, 0.90,
                          12, 22, 265, 300)
print("  JIT ready.")


def fit_garch_midas(returns, midas_reg, K=12, n_days=22, label=""):
    """Fit GARCH-MIDAS by MLE with multiple starts."""
    unc_var = np.nanvar(returns)
    m0 = np.log(max(unc_var, 1e-10))

    bounds = [
        (-20.0, -5.0),
        (-5.0, 5.0),
        (1.01, 20.0),
        (0.001, 0.25),
        (0.6, 0.998),
    ]

    starts = [
        [m0, 0.1, 2.0, 0.05, 0.90],
        [m0, 0.5, 3.0, 0.08, 0.88],
        [m0, -0.3, 5.0, 0.06, 0.90],
        [m0, 1.0, 1.5, 0.04, 0.93],
        [m0, -1.0, 2.0, 0.07, 0.89],
        [m0, 0.2, 8.0, 0.05, 0.91],
        [m0, -0.1, 2.0, 0.10, 0.85],
    ]

    best_result = None
    best_nll = 1e15

    for start in starts:
        try:
            result = optimize.minimize(
                lambda p: garch_midas_ll(p, returns, midas_reg, K, n_days),
                start, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 2000, 'ftol': 1e-12}
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None or best_nll >= 1e9:
        return None

    m, theta, omega, alpha, beta_p = best_result.x
    return {
        'params': {
            'm': float(m), 'theta': float(theta), 'omega': float(omega),
            'alpha': float(alpha), 'beta': float(beta_p),
            'persistence': float(alpha + beta_p),
        },
        'converged': best_result.success,
        'log_likelihood': float(-best_nll),
        'label': label,
    }


# ============================================================
# SECTION 5: GJR-GARCH BENCHMARK
# ============================================================
print("\n[5] GJR-GARCH benchmark (arch)...")
from arch import arch_model

# ============================================================
# SECTION 6: ROLLING OOS EVALUATION
# ============================================================
print("\n[6] Rolling OOS evaluation...")

returns = data['log_ret'].values
ret_pct = returns * 100
n_total = len(returns)
oos_start = WINDOW
n_oos = n_total - oos_start

print(f"  n_total={n_total}, OOS start={oos_start}, n_oos={n_oos}")
print(f"  OOS: {data.index[oos_start].strftime('%Y-%m-%d')} to "
      f"{data.index[-1].strftime('%Y-%m-%d')}")

proxy = returns ** 2
PROXY_FLOOR = 1e-12

forecasts = {
    'GARCH-MIDAS-RV': np.full(n_total, np.nan),
    'GARCH-MIDAS-VIX': np.full(n_total, np.nan),
    'GJR-GARCH': np.full(n_total, np.nan),
    'GARCH(1,1)': np.full(n_total, np.nan),
}

REFIT_FREQ = 63
param_history = {'GARCH-MIDAS-RV': [], 'GARCH-MIDAS-VIX': []}

# Cache for GARCH recursive forecasting
gjr_cache = {'omega': 0, 'alpha': 0, 'gamma': 0, 'beta': 0, 'h_prev': 0}
garch_cache = {'omega': 0, 'alpha': 0, 'beta': 0, 'h_prev': 0}
midas_rv_params = None
midas_vix_params = None

n_refits = 0

for t in range(oos_start, n_total):
    need_refit = (t == oos_start) or ((t - oos_start) % REFIT_FREQ == 0)

    if need_refit:
        n_refits += 1
        ws = t - WINDOW
        w_ret = returns[ws:t]
        w_log_rv = log_rv_arr[ws:t]
        w_log_vix = log_vix_arr[ws:t]
        w_ret_pct = w_ret * 100

        elapsed = time.time() - START_TIME
        pct = (t - oos_start) / n_oos * 100
        print(f"  [{elapsed:.0f}s] Refit #{n_refits} at "
              f"{data.index[t].strftime('%Y-%m-%d')} ({pct:.0f}%)")

        # GARCH-MIDAS-RV
        try:
            res = fit_garch_midas(w_ret, w_log_rv, K=MIDAS_K, n_days=MIDAS_DAYS,
                                  label="MIDAS-RV")
            if res:
                midas_rv_params = res['params']
                param_history['GARCH-MIDAS-RV'].append({
                    'date': data.index[t].strftime('%Y-%m-%d'),
                    **res['params']
                })
                # Compute full forecast sequence for this window
                p = res['params']
                fc = garch_midas_forecast(
                    returns, log_rv_arr,
                    p['m'], p['theta'], p['omega'], p['alpha'], p['beta'],
                    MIDAS_K, MIDAS_DAYS, t,
                    min(t + REFIT_FREQ, n_total))
                # Fill forecasts
                end_fill = min(t + REFIT_FREQ, n_total)
                for tt in range(t, end_fill):
                    if not np.isnan(fc[tt]) and fc[tt] > 0:
                        forecasts['GARCH-MIDAS-RV'][tt] = fc[tt]
        except Exception:
            pass

        # GARCH-MIDAS-VIX
        try:
            res = fit_garch_midas(w_ret, w_log_vix, K=MIDAS_K, n_days=MIDAS_DAYS,
                                  label="MIDAS-VIX")
            if res:
                midas_vix_params = res['params']
                param_history['GARCH-MIDAS-VIX'].append({
                    'date': data.index[t].strftime('%Y-%m-%d'),
                    **res['params']
                })
                p = res['params']
                fc = garch_midas_forecast(
                    returns, log_vix_arr,
                    p['m'], p['theta'], p['omega'], p['alpha'], p['beta'],
                    MIDAS_K, MIDAS_DAYS, t,
                    min(t + REFIT_FREQ, n_total))
                end_fill = min(t + REFIT_FREQ, n_total)
                for tt in range(t, end_fill):
                    if not np.isnan(fc[tt]) and fc[tt] > 0:
                        forecasts['GARCH-MIDAS-VIX'][tt] = fc[tt]
        except Exception:
            pass

        # GJR-GARCH
        try:
            mod = arch_model(pd.Series(w_ret_pct), vol='GARCH', p=1, o=1, q=1,
                             mean='Zero', dist='normal', rescale=False)
            fit = mod.fit(disp='off', show_warning=False)
            gjr_cache['omega'] = float(fit.params.get('omega', 0))
            gjr_cache['alpha'] = float(fit.params.get('alpha[1]', 0))
            gjr_cache['gamma'] = float(fit.params.get('gamma[1]', 0))
            gjr_cache['beta'] = float(fit.params.get('beta[1]', 0))
            gjr_cache['h_prev'] = float(fit.conditional_volatility.iloc[-1]**2)
        except Exception:
            pass

        # GARCH(1,1)
        try:
            mod = arch_model(pd.Series(w_ret_pct), vol='GARCH', p=1, q=1,
                             mean='Zero', dist='normal', rescale=False)
            fit = mod.fit(disp='off', show_warning=False)
            garch_cache['omega'] = float(fit.params.get('omega', 0))
            garch_cache['alpha'] = float(fit.params.get('alpha[1]', 0))
            garch_cache['beta'] = float(fit.params.get('beta[1]', 0))
            garch_cache['h_prev'] = float(fit.conditional_volatility.iloc[-1]**2)
        except Exception:
            pass

    # GJR-GARCH recursive forecast
    if gjr_cache['omega'] > 0 and t > 0:
        eps = ret_pct[t-1]
        ind = 1.0 if eps < 0 else 0.0
        h_t = (gjr_cache['omega'] + gjr_cache['alpha'] * eps**2 +
               gjr_cache['gamma'] * ind * eps**2 +
               gjr_cache['beta'] * gjr_cache['h_prev'])
        h_t = max(h_t, 1e-6)
        gjr_cache['h_prev'] = h_t
        forecasts['GJR-GARCH'][t] = h_t / 10000

    # GARCH(1,1) recursive forecast
    if garch_cache['omega'] > 0 and t > 0:
        eps = ret_pct[t-1]
        h_t = (garch_cache['omega'] + garch_cache['alpha'] * eps**2 +
               garch_cache['beta'] * garch_cache['h_prev'])
        h_t = max(h_t, 1e-6)
        garch_cache['h_prev'] = h_t
        forecasts['GARCH(1,1)'][t] = h_t / 10000

elapsed = time.time() - START_TIME
print(f"\n  Done: {elapsed:.1f}s, {n_refits} refits")

# ============================================================
# SECTION 7: LOSS EVALUATION
# ============================================================
print("\n[7] Loss Evaluation...")

results_table = {}

for name, fcast in forecasts.items():
    f_oos = fcast[oos_start:]
    p_oos = proxy[oos_start:]

    valid = np.isfinite(f_oos) & (f_oos > 0) & np.isfinite(p_oos)
    n_valid = int(valid.sum())

    if n_valid < 50:
        print(f"  {name:25s}: only {n_valid} valid — skip")
        continue

    f_v = f_oos[valid]
    p_v = np.maximum(p_oos[valid], PROXY_FLOOR)

    ratio = np.clip(p_v / f_v, 1e-6, 1e6)
    qlike = float(np.mean(ratio - np.log(ratio) - 1))
    mse = float(np.mean((p_v - f_v)**2))
    mae = float(np.mean(np.abs(p_v - f_v)))

    X_mz = np.column_stack([np.ones(len(f_v)), f_v])
    b_mz = lstsq(X_mz, p_v, rcond=None)[0]
    r2 = float(1 - np.var(p_v - X_mz @ b_mz) / np.var(p_v))

    bias = float(np.mean(f_v) / np.mean(p_v) - 1)

    qlike_losses = ratio - np.log(ratio) - 1
    mse_losses = (p_v - f_v)**2

    results_table[name] = {
        'n_valid': n_valid, 'qlike': qlike, 'mse': mse, 'mae': mae,
        'r2_mz': r2, 'mean_forecast': float(np.mean(f_v)),
        'mean_proxy': float(np.mean(p_v)),
        'forecast_bias': bias,
        '_qlike_losses': qlike_losses, '_mse_losses': mse_losses,
    }

    print(f"  {name:25s}: QLIKE={qlike:.6f}  MSE={mse:.2e}  "
          f"R²={r2:.4f}  bias={bias*100:+.1f}%  n={n_valid}")

# ============================================================
# SECTION 8: DM TESTS
# ============================================================
print("\n[8] DM Tests...")


def dm_test(loss1, loss2, h=1):
    n = min(len(loss1), len(loss2))
    d = loss1[:n] - loss2[:n]
    d_bar = np.mean(d)
    bw = max(int(np.floor(4 * (n/100)**(2/9))), h)
    gamma_0 = np.mean((d - d_bar)**2)
    hac = gamma_0
    for j in range(1, bw+1):
        gj = np.mean((d[j:] - d_bar) * (d[:-j] - d_bar))
        hac += 2 * (1 - j/(bw+1)) * gj
    if hac <= 0:
        return np.nan, np.nan
    dm = d_bar / np.sqrt(hac / n)
    p = 2 * (1 - stats.norm.cdf(abs(dm)))
    return float(dm), float(p)


BM = 'GJR-GARCH'
dm_results = {}

if BM in results_table:
    bl = results_table[BM]['_qlike_losses']

    for name in results_table:
        if name == BM:
            continue

        ml = results_table[name]['_qlike_losses']
        n_com = min(len(ml), len(bl))
        if n_com < 50:
            continue

        dm_stat, dm_p = dm_test(ml[:n_com], bl[:n_com])
        better = name if dm_stat < 0 else BM
        sig = "***" if abs(dm_stat) > 3.0 else "**" if abs(dm_stat) > 2.0 else "*" if abs(dm_stat) > 1.65 else "ns"

        dm_results[f"{name}_vs_{BM}"] = {
            'dm_stat': dm_stat, 'p_value': dm_p,
            'better': better, 'harvey_significant': abs(dm_stat) > 3.0
        }
        print(f"  {name:25s} vs GJR: DM={dm_stat:+.3f} p={dm_p:.4f} ({sig})")

# MIDAS-RV vs MIDAS-VIX
if 'GARCH-MIDAS-RV' in results_table and 'GARCH-MIDAS-VIX' in results_table:
    l1 = results_table['GARCH-MIDAS-RV']['_qlike_losses']
    l2 = results_table['GARCH-MIDAS-VIX']['_qlike_losses']
    n_com = min(len(l1), len(l2))
    if n_com >= 50:
        dm_stat, dm_p = dm_test(l1[:n_com], l2[:n_com])
        better = "MIDAS-RV" if dm_stat < 0 else "MIDAS-VIX"
        dm_results['MIDAS_RV_vs_VIX'] = {
            'dm_stat': float(dm_stat), 'p_value': float(dm_p), 'better': better
        }
        print(f"  MIDAS-RV vs MIDAS-VIX: DM={dm_stat:+.3f} p={dm_p:.4f} → {better}")

# ============================================================
# SECTION 9: IMPROVEMENTS
# ============================================================
print("\n[9] QLIKE Improvement vs GJR...")

improvements = {}
if BM in results_table:
    bq = results_table[BM]['qlike']
    for name, r in results_table.items():
        if name == BM:
            continue
        imp = (bq - r['qlike']) / bq * 100
        improvements[name] = float(imp)
        print(f"  {name:25s}: {imp:+.2f}%")

# ============================================================
# SECTION 10: PARAMETER EVOLUTION
# ============================================================
print("\n[10] Parameters...")

for mn in ['GARCH-MIDAS-RV', 'GARCH-MIDAS-VIX']:
    ph = param_history.get(mn, [])
    if not ph:
        continue

    print(f"\n  --- {mn} ({len(ph)} refits) ---")
    for i in [0, len(ph)//2, -1]:
        p = ph[i]
        print(f"    {p['date']}: m={p['m']:.3f} θ={p['theta']:+.3f} "
              f"ω={p['omega']:.2f} α={p['alpha']:.4f} β={p['beta']:.4f}")

    keys = ['m', 'theta', 'omega', 'alpha', 'beta', 'persistence']
    avgs = {k: float(np.mean([p[k] for p in ph])) for k in keys}
    print(f"    AVG: m={avgs['m']:.3f} θ={avgs['theta']:+.3f} "
          f"ω={avgs['omega']:.2f} α={avgs['alpha']:.4f} β={avgs['beta']:.4f} "
          f"pers={avgs['persistence']:.4f}")

    thetas = [p['theta'] for p in ph]
    pct_pos = sum(1 for t in thetas if t > 0) / len(thetas) * 100
    print(f"    θ: [{min(thetas):+.3f}, {max(thetas):+.3f}], "
          f"positive {pct_pos:.0f}%")

# ============================================================
# SECTION 11: WEIGHT PROFILES
# ============================================================
print("\n[11] MIDAS Weight Profiles...")

for mn in ['GARCH-MIDAS-RV', 'GARCH-MIDAS-VIX']:
    ph = param_history.get(mn, [])
    if not ph:
        continue

    avg_omega = np.mean([p['omega'] for p in ph])
    w = beta_weights_nb(MIDAS_K, avg_omega)

    print(f"\n  {mn} (ω={avg_omega:.2f}):")
    cum = 0
    for k in range(min(MIDAS_K, 6)):
        cum += w[k]
        bar = '#' * int(w[k] * 80)
        print(f"    Lag {k+1:2d}: {w[k]:.4f} (cum={cum:.3f}) {bar}")
    if MIDAS_K > 6:
        print(f"    Remaining: {1-cum:.4f}")

    hl = int(np.searchsorted(np.cumsum(w), 0.5)) + 1
    print(f"    Half-life: {hl} months")

# ============================================================
# SECTION 12: SUB-PERIOD ANALYSIS
# ============================================================
print("\n[12] Sub-period Analysis...")

for year in range(2018, 2025):
    year_mask = np.array([data.index[i].year == year
                          for i in range(oos_start, n_total)])
    n_yr = year_mask.sum()
    if n_yr < 20:
        continue

    print(f"\n  {year} (n={n_yr}):")
    for name, fcast in forecasts.items():
        f_yr = fcast[oos_start:][year_mask]
        p_yr = proxy[oos_start:][year_mask]
        valid = np.isfinite(f_yr) & (f_yr > 0) & np.isfinite(p_yr)
        if valid.sum() < 10:
            continue
        f_v = f_yr[valid]
        p_v = np.maximum(p_yr[valid], PROXY_FLOOR)
        ratio = np.clip(p_v / f_v, 1e-6, 1e6)
        qlike = np.mean(ratio - np.log(ratio) - 1)
        print(f"    {name:25s}: QLIKE={qlike:.6f}")

# ============================================================
# SECTION 13: COMPONENT DECOMPOSITION
# ============================================================
print("\n[13] Component Decomposition (MIDAS-RV)...")

ph_rv = param_history.get('GARCH-MIDAS-RV', [])
if ph_rv:
    avg_p = {k: np.mean([p[k] for p in ph_rv])
             for k in ['m', 'theta', 'omega']}
    weights = beta_weights_nb(MIDAS_K, avg_p['omega'])

    tau_list = []
    g_list = []

    for t in range(oos_start, n_total):
        fv = forecasts['GARCH-MIDAS-RV'][t]
        if np.isnan(fv) or fv <= 0:
            continue

        midas_sum = 0.0
        ok = True
        for k in range(MIDAS_K):
            idx = t - (k+1) * MIDAS_DAYS
            if idx < 0 or np.isnan(log_rv_arr[idx]):
                ok = False
                break
            midas_sum += weights[k] * log_rv_arr[idx]

        if ok:
            tau = np.exp(avg_p['m'] + avg_p['theta'] * midas_sum)
            g = fv / tau if tau > 0 else 1.0
            tau_list.append(tau)
            g_list.append(g)

    if tau_list:
        tau_arr = np.array(tau_list)
        g_arr = np.array(g_list)

        lt = np.log(tau_arr)
        lg = np.log(np.maximum(g_arr, 1e-10))
        ls = lt + lg

        vt = np.var(lt)
        vg = np.var(lg)
        vs = np.var(ls)
        cov_tg = np.cov(lt, lg)[0, 1]

        if vs > 0:
            print(f"  Var decomposition of log(σ²):")
            print(f"    Long-run (τ): {vt/vs*100:.1f}%")
            print(f"    Short-run (g): {vg/vs*100:.1f}%")
            print(f"    2·Cov: {2*cov_tg/vs*100:.1f}%")

        print(f"\n  τ: mean={np.mean(tau_arr):.6f} std={np.std(tau_arr):.6f} "
              f"cv={np.std(tau_arr)/np.mean(tau_arr):.3f}")
        print(f"  g: mean={np.mean(g_arr):.3f} std={np.std(g_arr):.3f}")

# ============================================================
# SECTION 14: CONVERGENCE CHECKS
# ============================================================
print("\n[14] Convergence...")

for mn in ['GARCH-MIDAS-RV', 'GARCH-MIDAS-VIX']:
    ph = param_history.get(mn, [])
    if not ph:
        continue
    pers = [p['persistence'] for p in ph]
    omegas = [p['omega'] for p in ph]
    at_bound = sum(1 for o in omegas if o > 19.5 or o < 1.02)
    print(f"  {mn}: pers=[{min(pers):.4f},{max(pers):.4f}] "
          f"ω_at_bound={at_bound}/{len(omegas)}")

# ============================================================
# SECTION 15: SAVE
# ============================================================
print("\n[15] Saving...")

elapsed_total = time.time() - START_TIME

clean_results = {}
for name, r in results_table.items():
    clean_results[name] = {k: v for k, v in r.items() if not k.startswith('_')}

if clean_results:
    best_model = min(clean_results, key=lambda x: clean_results[x]['qlike'])
    best_qlike = clean_results[best_model]['qlike']
else:
    best_model = "none"
    best_qlike = None

summary = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'GARCH-MIDAS for SPY Volatility Prediction',
    'proposer': '用戶',
    'executor': 'Claude',
    'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    'asset': 'SPY',
    'data_source': 'yfinance (SPY daily, ^VIX daily)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'total_observations': int(n_total),
    'oos_period': f"{data.index[oos_start].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'oos_observations': int(n_oos),
    'estimation_window': WINDOW,
    'refit_frequency_days': REFIT_FREQ,
    'midas_lags_K': MIDAS_K,
    'midas_days_per_period': MIDAS_DAYS,
    'proxy': 'squared returns (clipped at 1e-12)',
    'models': {
        'GARCH-MIDAS-RV': 'GARCH-MIDAS with log(22d RV) regressor',
        'GARCH-MIDAS-VIX': 'GARCH-MIDAS with log(22d avg VIX) regressor',
        'GJR-GARCH': 'GJR-GARCH(1,1) benchmark',
        'GARCH(1,1)': 'GARCH(1,1) benchmark',
    },
    'results': clean_results,
    'qlike_improvements_vs_gjr_pct': improvements,
    'dm_tests': dm_results,
    'best_model': best_model,
    'best_qlike': float(best_qlike) if best_qlike is not None else None,
    'parameter_history': {k: v for k, v in param_history.items()},
    'descriptive_stats': desc,
    'runtime_seconds': float(elapsed_total),
    'references': [
        'Engle, Ghysels & Sohn (2013) RFS 26(11):2471-2509',
        'Conrad & Loch (2015) JFQA 50(5):1141-1164',
        'Ghysels et al. (2006) JoE',
    ],
    'methodology': {
        'total_variance': 'σ²_t = τ_t · g_t',
        'short_run': 'g_t = (1-α-β) + α·r²_{t-1}/τ_{t-1} + β·g_{t-1}',
        'long_run': 'log(τ_t) = m + θ·Σ φ_k(ω)·X_{t-k}',
        'midas_weights': 'φ_k(ω) = (1-k/(K+1))^{ω-1} / Σ',
        'estimation': 'MLE + L-BFGS-B + 7 multi-start',
        'acceleration': 'Numba JIT for log-likelihood and filtering',
    },
    'limitations': [
        'Squared returns as proxy (noisy vs intraday RV)',
        'RV from daily data only',
        'Single asset (SPY)',
        'Fixed K=12, n_days=22',
        'ω₁=1 restriction',
        'Quarterly refit',
    ],
}

print(f"\n{'='*70}")
print(f"FINAL — {EXPERIMENT_ID}: GARCH-MIDAS")
print(f"{'='*70}")
print(f"  Best: {best_model} (QLIKE={best_qlike:.6f})" if best_qlike else "  No valid results")
print(f"  OOS: {summary['oos_period']} (n={n_oos})")

if clean_results:
    print(f"\n  Rankings:")
    ranked = sorted(clean_results.items(), key=lambda x: x[1]['qlike'])
    for i, (name, r) in enumerate(ranked, 1):
        star = " ***" if name == best_model else ""
        print(f"    {i}. {name:25s}: QLIKE={r['qlike']:.6f} R²={r['r2_mz']:.4f}{star}")

print(f"\n  Improvements vs GJR:")
for k, v in improvements.items():
    print(f"    {k}: {v:+.2f}%")

print(f"\n  DM Tests:")
for k, v in dm_results.items():
    sig = "***" if abs(v['dm_stat']) > 3.0 else "ns"
    print(f"    {k}: DM={v['dm_stat']:+.3f} ({sig})")

print(f"\n  Runtime: {elapsed_total:.1f}s")

out = os.path.join(MAIN_REPO, 'experiments', f'{EXPERIMENT_ID.lower()}_garch_midas_results.json')
with open(out, 'w') as f:
    json.dump(summary, f, indent=2, default=str)

local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     f'{EXPERIMENT_ID.lower()}_garch_midas_results.json')
with open(local, 'w') as f:
    json.dump(summary, f, indent=2, default=str)

print(f"\n  Saved: {out}")
print(f"  Saved: {local}")
