#!/usr/bin/env python3
"""
K591: Window Size Sensitivity Sweep — Validating W=2000
========================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K590 literature search found Feng & Zhang (J.Forecasting 2025) confirming
  W=1000-2000 is optimal (U-shape). Our W=2000 was chosen based on M1/M4
  persistence bias analysis. This experiment formally validates with a
  comprehensive sweep.

Prior experiments:
  K041/K042: Initial SPY QLIKE sensitivity (w=126/252/504, <0.5% variation)
  K153: Window size sensitivity low for SPY (w=126/252/504)
  K406/K408: w=2000 upgrade (persistence bias correction)
  K419: Cross-asset window specificity (SPY/GLD→w=2000, TLT→w=504)
  User insight (2026-03-16): U-shape QLIKE, w=5000 best on 2023-24

Design:
  1. Data: SPY from yfinance (2005-2026)
  2. Model: GJR-GARCH(1,1) with Student-t
  3. Window sizes: 252, 504, 756, 1000, 1260, 1500, 1750, 2000, 2500, 3000
  4. OOS: 2023-2024 (fixed for all windows)
  5. Metrics: QLIKE, MSE, persistence (α+β+γ/2), convergence rate
  6. Also test HAR-ABS with same window sweep (w=100 to 1000 for HAR)
  7. Plot the U-shape curve
  8. DM test: W=2000 vs each alternative

Expected: U-shape with minimum around 1000-2000, confirming literature + our choice.

Data source: yfinance (SPY daily close, 2005-01-03 to 2026-03-26)
OOS period: 2023-01-03 to 2024-12-31

References:
  Feng & Zhang (2025) "Forecasting Volatility" J.Forecasting — U-shape, W=1000-2000 optimal
  Hillebrand (2005) "Neglecting parameter changes in GARCH models" — persistence bias
  Hansen & Lunde (2005) "A Forecast Comparison" J.Applied Econometrics — QLIKE
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies" JoE
  K041, K042, K153, K406, K408, K419
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
EXPERIMENT_ID = "K591"
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

# GARCH window sizes to test
GARCH_WINDOWS = [252, 504, 756, 1000, 1260, 1500, 1750, 2000, 2500, 3000]

# HAR window sizes to test (smaller, regression-based)
HAR_WINDOWS = [100, 200, 300, 500, 756, 1000]

# OOS period
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

# Refit frequency (every N days)
REFIT_EVERY = 21

print("=" * 70)
print(f"{EXPERIMENT_ID}: Window Size Sensitivity Sweep — Validating W=2000")
print("  GJR-GARCH(1,1)-t: W = {252..3000}")
print("  HAR-ABS: W = {100..1000}")
print(f"  OOS: {OOS_START} to {OOS_END}, Refit every {REFIT_EVERY} days")
print("=" * 70)
print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
t0_total = time.time()


# ============================================================
# Data download
# ============================================================
print("\n[1] Downloading SPY data...")
df = yf.download('SPY', start='2003-01-01', end='2026-03-27',
                 progress=False, auto_adjust=True)
# Flatten multi-level columns if present
if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
    df.columns = df.columns.get_level_values(0)

close = df['Close'].dropna()
ret = np.log(close / close.shift(1)).dropna() * 100  # log returns in %
print(f"  SPY: {len(ret)} daily returns ({ret.index[0].date()} to {ret.index[-1].date()})")

# Descriptive stats
print(f"  Mean={ret.mean():.4f}%, Std={ret.std():.4f}%")
print(f"  Skew={ret.skew():.3f}, Kurt={ret.kurtosis():.3f}")

# Define OOS mask
oos_mask = (ret.index >= OOS_START) & (ret.index <= OOS_END)
oos_dates = ret.index[oos_mask]
n_oos = len(oos_dates)
print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")


# ============================================================
# QLIKE and MSE loss functions
# ============================================================
def qlike(realized, forecast):
    """QLIKE loss: E[rv/fv - log(rv/fv) - 1]. Lower is better."""
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return np.mean(rv / fv - np.log(rv / fv) - 1)

def mse_loss(realized, forecast):
    """MSE loss on variance scale."""
    valid = (realized > 0) & (forecast > 0)
    return np.mean((realized[valid] - forecast[valid]) ** 2)


# ============================================================
# DM test (Diebold-Mariano with Newey-West HAC)
# ============================================================
def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns (DM stat, p-value). Negative DM = model1 better."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC variance with bandwidth = h-1
    gamma0 = np.var(d, ddof=0)
    nw_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1] if len(d) > k else 0
        nw_var += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(nw_var / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value


# ============================================================
# GJR-GARCH rolling forecast for a given window size
# ============================================================
def gjr_garch_rolling(returns, oos_dates, window, refit_every=21):
    """Rolling GJR-GARCH(1,1)-t forecast with given window size."""
    forecasts = {}
    realized = {}
    persistence_list = []
    convergence_count = 0
    total_fits = 0

    all_idx = returns.index.tolist()
    oos_idx_set = set(oos_dates.tolist())

    last_model = None
    last_params = None
    days_since_fit = refit_every  # force fit on first day

    for i, dt in enumerate(all_idx):
        if dt not in oos_idx_set:
            continue

        pos = all_idx.index(dt)
        if pos < window:
            continue  # not enough history

        train = returns.iloc[pos - window:pos]

        # Decide whether to refit
        days_since_fit += 1
        need_refit = (days_since_fit >= refit_every) or (last_model is None)

        if need_refit:
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                                dist='t', mean='Zero', rescale=False)
                res = am.fit(disp='off', show_warning=False)

                total_fits += 1
                if res.convergence_flag == 0:
                    convergence_count += 1

                last_model = res
                # Extract persistence
                params = res.params
                alpha = params.get('alpha[1]', 0)
                beta = params.get('beta[1]', 0)
                gamma = params.get('gamma[1]', 0)
                pers = alpha + beta + gamma / 2
                persistence_list.append(pers)

                days_since_fit = 0
            except Exception:
                pass  # use last model

        if last_model is not None:
            # 1-step forecast
            try:
                fcast = last_model.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                if h > 0 and np.isfinite(h):
                    forecasts[dt] = h
                    realized[dt] = returns.loc[dt] ** 2  # squared return proxy
            except Exception:
                pass

    # Align
    common_dates = sorted(set(forecasts.keys()) & set(realized.keys()))
    fv = np.array([forecasts[d] for d in common_dates])
    rv = np.array([realized[d] for d in common_dates])

    conv_rate = convergence_count / total_fits if total_fits > 0 else 0
    avg_pers = np.mean(persistence_list) if persistence_list else np.nan
    std_pers = np.std(persistence_list) if persistence_list else np.nan

    return {
        'dates': common_dates,
        'forecasts': fv,
        'realized': rv,
        'n_forecasts': len(common_dates),
        'convergence_rate': conv_rate,
        'total_fits': total_fits,
        'avg_persistence': avg_pers,
        'std_persistence': std_pers,
        'n_persistence': len(persistence_list),
    }


# ============================================================
# HAR-ABS rolling forecast for a given window size
# ============================================================
def har_abs_rolling(returns, oos_dates, window, refit_every=21):
    """Rolling HAR-ABS model: |r_t| = c + b1*|r_{t-1}| + b5*avg|r_{t-5:t-1}| + b22*avg|r_{t-22:t-1}| + e_t
    Forecast: h_{t+1} = (predicted |r_{t+1}|)^2 for variance scale.
    """
    abs_ret = returns.abs()
    forecasts = {}
    realized = {}

    all_idx = returns.index.tolist()
    oos_idx_set = set(oos_dates.tolist())

    last_beta = None
    days_since_fit = refit_every

    for i, dt in enumerate(all_idx):
        if dt not in oos_idx_set:
            continue

        pos = all_idx.index(dt)
        if pos < max(window, 22):
            continue

        # Build HAR features for training
        need_refit = (days_since_fit >= refit_every) or (last_beta is None)

        if need_refit:
            train_abs = abs_ret.iloc[pos - window:pos].values
            n_train = len(train_abs)

            if n_train < 50:
                continue

            # Build design matrix
            Y = train_abs[22:]
            X = np.ones((len(Y), 4))
            for j in range(len(Y)):
                idx = 22 + j
                X[j, 1] = train_abs[idx - 1]  # daily
                X[j, 2] = np.mean(train_abs[idx - 5:idx])  # weekly
                X[j, 3] = np.mean(train_abs[idx - 22:idx])  # monthly

            try:
                beta, _, _, _ = np.linalg.lstsq(X, Y, rcond=None)
                last_beta = beta
                days_since_fit = 0
            except Exception:
                pass

        days_since_fit += 1

        if last_beta is not None:
            # Features for prediction at date dt
            recent = abs_ret.iloc[pos - 22:pos].values
            if len(recent) >= 22:
                x_pred = np.array([
                    1.0,
                    recent[-1],            # daily
                    np.mean(recent[-5:]),   # weekly
                    np.mean(recent[-22:]),  # monthly
                ])
                pred_abs = x_pred @ last_beta
                if pred_abs > 0:
                    forecasts[dt] = pred_abs ** 2  # variance scale
                    realized[dt] = returns.loc[dt] ** 2

    common_dates = sorted(set(forecasts.keys()) & set(realized.keys()))
    fv = np.array([forecasts[d] for d in common_dates])
    rv = np.array([realized[d] for d in common_dates])

    return {
        'dates': common_dates,
        'forecasts': fv,
        'realized': rv,
        'n_forecasts': len(common_dates),
    }


# ============================================================
# Run GJR-GARCH sweep
# ============================================================
print("\n[2] GJR-GARCH(1,1)-t Window Size Sweep")
print("-" * 60)

garch_results = {}
garch_losses = {}  # store per-day QLIKE losses for DM test

for w in GARCH_WINDOWS:
    t0 = time.time()
    print(f"  W={w:>5d}...", end=" ", flush=True)

    res = gjr_garch_rolling(ret, oos_dates, window=w, refit_every=REFIT_EVERY)

    if res['n_forecasts'] > 0:
        ql = qlike(res['realized'], res['forecasts'])
        mse = mse_loss(res['realized'], res['forecasts'])

        # Per-day QLIKE losses for DM test
        rv_arr = res['realized']
        fv_arr = res['forecasts']
        valid = (rv_arr > 0) & (fv_arr > 0)
        per_day_loss = rv_arr[valid] / fv_arr[valid] - np.log(rv_arr[valid] / fv_arr[valid]) - 1

        garch_results[w] = {
            'window': w,
            'n_forecasts': res['n_forecasts'],
            'QLIKE': float(ql),
            'MSE': float(mse),
            'convergence_rate': float(res['convergence_rate']),
            'total_fits': res['total_fits'],
            'avg_persistence': float(res['avg_persistence']),
            'std_persistence': float(res['std_persistence']),
        }
        garch_losses[w] = per_day_loss

        elapsed = time.time() - t0
        print(f"QLIKE={ql:.6f}  MSE={mse:.6f}  pers={res['avg_persistence']:.4f}±{res['std_persistence']:.4f}  "
              f"conv={res['convergence_rate']:.1%}  fits={res['total_fits']}  ({elapsed:.1f}s)")
    else:
        print("  FAILED (no forecasts)")

# Find best GARCH window
if garch_results:
    best_w = min(garch_results, key=lambda w: garch_results[w]['QLIKE'])
    print(f"\n  >>> Best GARCH window: W={best_w} (QLIKE={garch_results[best_w]['QLIKE']:.6f})")


# ============================================================
# DM tests: W=2000 vs each alternative
# ============================================================
print("\n[3] DM Tests: W=2000 vs alternatives")
print("-" * 60)

dm_results = {}
if 2000 in garch_losses:
    ref_loss = garch_losses[2000]
    for w in GARCH_WINDOWS:
        if w == 2000:
            continue
        if w in garch_losses:
            # Align lengths (should be same, but be safe)
            min_len = min(len(ref_loss), len(garch_losses[w]))
            dm_stat, p_val = dm_test(ref_loss[:min_len], garch_losses[w][:min_len])

            better = "W=2000" if dm_stat < 0 else f"W={w}"
            sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else ""))

            dm_results[w] = {
                'dm_stat': float(dm_stat),
                'p_value': float(p_val),
                'better': better,
                'significant': sig,
            }
            print(f"  W=2000 vs W={w:>5d}: DM={dm_stat:+.4f}  p={p_val:.4f}  {sig}  → {better} better")
else:
    print("  W=2000 not available, skipping DM tests")


# ============================================================
# Run HAR-ABS sweep
# ============================================================
print("\n[4] HAR-ABS Window Size Sweep")
print("-" * 60)

har_results = {}
har_losses = {}

for w in HAR_WINDOWS:
    t0 = time.time()
    print(f"  W={w:>5d}...", end=" ", flush=True)

    res = har_abs_rolling(ret, oos_dates, window=w, refit_every=REFIT_EVERY)

    if res['n_forecasts'] > 0:
        ql = qlike(res['realized'], res['forecasts'])
        mse = mse_loss(res['realized'], res['forecasts'])

        rv_arr = res['realized']
        fv_arr = res['forecasts']
        valid = (rv_arr > 0) & (fv_arr > 0)
        per_day_loss = rv_arr[valid] / fv_arr[valid] - np.log(rv_arr[valid] / fv_arr[valid]) - 1

        har_results[w] = {
            'window': w,
            'n_forecasts': res['n_forecasts'],
            'QLIKE': float(ql),
            'MSE': float(mse),
        }
        har_losses[w] = per_day_loss

        elapsed = time.time() - t0
        print(f"QLIKE={ql:.6f}  MSE={mse:.6f}  n={res['n_forecasts']}  ({elapsed:.1f}s)")
    else:
        print("  FAILED")

if har_results:
    best_har_w = min(har_results, key=lambda w: har_results[w]['QLIKE'])
    print(f"\n  >>> Best HAR-ABS window: W={best_har_w} (QLIKE={har_results[best_har_w]['QLIKE']:.6f})")


# ============================================================
# Summary table
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY TABLE: GJR-GARCH(1,1)-t — QLIKE by Window Size")
print("=" * 70)
print(f"{'Window':>8s}  {'QLIKE':>10s}  {'MSE':>10s}  {'Persist':>8s}  {'±Std':>8s}  {'Conv%':>6s}  {'Fits':>5s}  {'vs W=2000':>12s}")
print("-" * 80)

best_ql = min(r['QLIKE'] for r in garch_results.values()) if garch_results else 0
for w in GARCH_WINDOWS:
    if w in garch_results:
        r = garch_results[w]
        dm_info = ""
        if w in dm_results:
            d = dm_results[w]
            dm_info = f"DM={d['dm_stat']:+.3f}{d['significant']}"
        elif w == 2000:
            dm_info = "(reference)"

        marker = " <<<" if r['QLIKE'] == best_ql else ""
        print(f"  {w:>6d}  {r['QLIKE']:>10.6f}  {r['MSE']:>10.6f}  {r['avg_persistence']:>8.4f}  "
              f"{r['std_persistence']:>8.4f}  {r['convergence_rate']:>5.1%}  {r['total_fits']:>5d}  {dm_info}{marker}")

if har_results:
    print("\n" + "=" * 70)
    print("SUMMARY TABLE: HAR-ABS — QLIKE by Window Size")
    print("=" * 70)
    print(f"{'Window':>8s}  {'QLIKE':>10s}  {'MSE':>10s}  {'N':>5s}")
    print("-" * 40)
    best_har_ql = min(r['QLIKE'] for r in har_results.values())
    for w in HAR_WINDOWS:
        if w in har_results:
            r = har_results[w]
            marker = " <<<" if r['QLIKE'] == best_har_ql else ""
            print(f"  {w:>6d}  {r['QLIKE']:>10.6f}  {r['MSE']:>10.6f}  {r['n_forecasts']:>5d}{marker}")


# ============================================================
# Persistence analysis
# ============================================================
print("\n" + "=" * 70)
print("PERSISTENCE ANALYSIS")
print("=" * 70)
print("Hillebrand (2005): Small windows inflate persistence toward 1.0")
print("Our prior (K406/K408): w=504 has -3.0% persistence bias vs w=2000+")
print()

if garch_results:
    ws = sorted(garch_results.keys())
    for w in ws:
        r = garch_results[w]
        print(f"  W={w:>5d}: persistence = {r['avg_persistence']:.4f} ± {r['std_persistence']:.4f}")

    # Regression: persistence vs 1/sqrt(window)
    x_inv = np.array([1.0 / np.sqrt(w) for w in ws])
    y_pers = np.array([garch_results[w]['avg_persistence'] for w in ws])
    if len(ws) > 2:
        slope, intercept, r_value, p_value, se = stats.linregress(x_inv, y_pers)
        print(f"\n  Regression: persistence = {intercept:.4f} + {slope:.4f} / sqrt(W)")
        print(f"  R² = {r_value**2:.4f}, slope p-value = {p_value:.4f}")
        print(f"  Interpretation: {'Smaller windows inflate persistence' if slope > 0 else 'Smaller windows reduce persistence'}")


# ============================================================
# QLIKE U-shape analysis
# ============================================================
print("\n" + "=" * 70)
print("U-SHAPE ANALYSIS (Feng & Zhang 2025)")
print("=" * 70)

if len(garch_results) >= 3:
    ws = sorted(garch_results.keys())
    qs = [garch_results[w]['QLIKE'] for w in ws]

    # Fit quadratic: QLIKE = a*W² + b*W + c
    coeffs = np.polyfit(ws, qs, 2)
    a, b, c = coeffs

    # Minimum of quadratic
    if a > 0:
        w_min = -b / (2 * a)
        q_min = a * w_min**2 + b * w_min + c
        print(f"  Quadratic fit: QLIKE = {a:.2e}*W² + {b:.2e}*W + {c:.4f}")
        print(f"  Minimum at W* = {w_min:.0f} (QLIKE* = {q_min:.6f})")
        print(f"  This {'confirms' if 1000 <= w_min <= 2500 else 'does NOT confirm'} Feng & Zhang (2025) U-shape at W=1000-2000")
    else:
        print(f"  Quadratic fit: a={a:.2e} (negative → no U-shape, monotonically decreasing)")
        # Check if monotonically decreasing
        if all(qs[i] >= qs[i+1] for i in range(len(qs)-1)):
            print("  QLIKE monotonically decreasing with window size → larger windows better")
        else:
            print("  Non-monotonic but not classic U-shape")

    # Also report: relative QLIKE vs W=2000
    if 2000 in garch_results:
        q_2000 = garch_results[2000]['QLIKE']
        print(f"\n  Relative to W=2000 (QLIKE={q_2000:.6f}):")
        for w in ws:
            rel = (garch_results[w]['QLIKE'] - q_2000) / q_2000 * 100
            print(f"    W={w:>5d}: {rel:+.3f}%")


# ============================================================
# Save results
# ============================================================
elapsed_total = time.time() - t0_total
print(f"\n{'='*70}")
print(f"Total elapsed: {elapsed_total:.1f}s")

results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Window Size Sensitivity Sweep — Validating W=2000",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "data_source": "yfinance",
    "asset": "SPY",
    "oos_period": f"{OOS_START} to {OOS_END}",
    "n_oos_days": n_oos,
    "refit_every": REFIT_EVERY,
    "model": "GJR-GARCH(1,1)-t + HAR-ABS",
    "garch_windows_tested": GARCH_WINDOWS,
    "har_windows_tested": HAR_WINDOWS,
    "garch_results": {str(k): v for k, v in garch_results.items()},
    "har_results": {str(k): v for k, v in har_results.items()},
    "dm_tests_vs_2000": dm_results,
    "best_garch_window": int(best_w) if garch_results else None,
    "best_har_window": int(best_har_w) if har_results else None,
    "persistence_analysis": {
        str(w): {
            "avg": float(garch_results[w]['avg_persistence']),
            "std": float(garch_results[w]['std_persistence']),
        } for w in sorted(garch_results.keys())
    } if garch_results else {},
    "references": [
        "Feng & Zhang (2025) J.Forecasting — U-shape W=1000-2000 optimal",
        "Hillebrand (2005) — persistence bias in short windows",
        "Hansen & Lunde (2005) J.Applied Econometrics — QLIKE",
        "Patton (2011) JoE — imperfect proxy",
        "K041/K042/K153/K406/K408/K419 — prior window experiments",
    ],
}

# Save results
out_path = f"{MAIN_REPO}/experiments/k591_window_size_sweep_results.json"
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
