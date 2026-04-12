#!/usr/bin/env python3
"""
K1073 postprocessing: recompute tau/sigma² using per-refit parameters (not
just last-refit params), and generate a clean final comparison summary.

Also examines the MSE blowup in SLOPE/COMBO to characterize numerical
instability. QLIKE remains the primary (Patton 2011 proxy-robust) metric.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1073_results.json')

with open(RESULTS_PATH) as f:
    R = json.load(f)

# --- Reload VIX family (same period as k1073.py) ---
spy_raw = yf.download('SPY', start='2011-01-01', end='2026-04-13',
                      progress=False, auto_adjust=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

vixes = {}
for name, sym in [('VIX', '^VIX'), ('VIX9D', '^VIX9D'),
                  ('VIX3M', '^VIX3M'), ('VVIX', '^VVIX')]:
    d = yf.download(sym, start='2011-01-01', end='2026-04-13',
                    progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    vixes[name] = d['Close']

df = pd.DataFrame({
    'close': spy_raw['Close'],
    'VIX': vixes['VIX'],
    'VIX9D': vixes['VIX9D'],
    'VIX3M': vixes['VIX3M'],
    'VVIX': vixes['VVIX'],
}).dropna()

oos_mask = np.array(df.index >= '2013-01-02')
oos_dates = df.index[oos_mask]
print(f"OOS dates: {oos_dates[0].date()} to {oos_dates[-1].date()}, n={len(oos_dates)}")

# --- Compute tau per OOS day using the correct per-refit parameters ---
# refit_dates are stored in results
refit_dates = pd.to_datetime(R['refit_dates'])

# For each OOS day, find which refit window it belongs to
# Refit k covers days from refit_dates[k] until refit_dates[k+1]-1
# (last refit covers until the end)
def assign_refit(oos_dts, refit_dts):
    idx = np.zeros(len(oos_dts), dtype=int)
    for i, d in enumerate(oos_dts):
        # Find the latest refit date <= d
        valid = refit_dts <= d
        if valid.any():
            idx[i] = np.where(valid)[0][-1]
        else:
            idx[i] = 0
    return idx


refit_idx = assign_refit(oos_dates, refit_dates)
print(f"Refit assignments: min={refit_idx.min()}, max={refit_idx.max()}, "
      f"unique={len(np.unique(refit_idx))}")

# Build lagged X² for OOS days (predetermined, X at t-1)
oos_vix2 = df['VIX'].shift(1).loc[oos_dates].values ** 2
oos_vix9d2 = df['VIX9D'].shift(1).loc[oos_dates].values ** 2
oos_vix3m2 = df['VIX3M'].shift(1).loc[oos_dates].values ** 2
oos_vvix2 = df['VVIX'].shift(1).loc[oos_dates].values ** 2

x2_by_spec = {
    'A4f_VIX': oos_vix2,
    'A4f_VIX9D': oos_vix9d2,
    'A4f_VIX3M': oos_vix3m2,
    'A4f_VVIX': oos_vvix2,
}

# For each single-exog spec, reconstruct tau at each OOS day using that
# day's refit-index params
tau_correct = {}
for spec in x2_by_spec:
    for tgt in ['close', 'oc']:
        mname = f'{spec}_{tgt}'
        hist = R['param_history'].get(mname, [])
        if not hist:
            continue
        theta0_per_refit = np.array([h['theta0'] for h in hist])
        theta1_per_refit = np.array([h['theta1'] for h in hist])
        # Fill missing refits with last seen (shouldn't happen here but guard)
        # refit_idx may exceed len(hist)-1 slightly, clip
        idx_clip = np.clip(refit_idx, 0, len(hist) - 1)
        tau_per_day = np.maximum(
            theta0_per_refit[idx_clip]
            + theta1_per_refit[idx_clip] * x2_by_spec[spec],
            1e-16)
        tau_correct[mname] = tau_per_day

# Now inspect tau relative to forecast (we have forecasts only via results
# r2_close, but not raw forecasts). Use published QLIKE instead to reason.

# Compute summary of tau_per_day
print("\nTau summary per model (using per-refit params):")
print(f"  {'Model':<20} {'tau mean':>12} {'tau std':>12} "
      f"{'tau p95':>12} {'tau p99':>12}")
print("  " + "-" * 72)
tau_summary = {}
for mname, tau in tau_correct.items():
    tau_summary[mname] = {
        'mean': float(np.mean(tau)),
        'std': float(np.std(tau)),
        'p50': float(np.median(tau)),
        'p95': float(np.percentile(tau, 95)),
        'p99': float(np.percentile(tau, 99)),
        'max': float(np.max(tau)),
        'min': float(np.min(tau)),
    }
    print(f"  {mname:<20} {np.mean(tau):>12.3e} {np.std(tau):>12.3e} "
          f"{np.percentile(tau, 95):>12.3e} {np.percentile(tau, 99):>12.3e}")

# Compare against published r²_close and r²_oc mean
r2_close_mean = 1.131e-04
r2_oc_mean = 6.494e-05
print(f"\n  For reference:")
print(f"    r²_close OOS mean = {r2_close_mean:.3e}")
print(f"    r²_oc    OOS mean = {r2_oc_mean:.3e}")

# Update results JSON with corrected tau
R['tau_per_refit_summary'] = tau_summary

# Identify unstable refits: tau > 10x expected variance
print("\n  Refits with tau >>> expected variance:")
unstable_count = {}
for mname, tau in tau_correct.items():
    r2_ref = r2_close_mean if 'close' in mname else r2_oc_mean
    bad_days = int(np.sum(tau > 10 * r2_ref))
    total = len(tau)
    unstable_count[mname] = {
        'bad_day_fraction': float(bad_days / total),
        'bad_days': bad_days,
        'total_days': total,
    }
    if bad_days > 0:
        print(f"    {mname:<20} {bad_days}/{total} days ({100*bad_days/total:.1f}%) "
              f"have tau > 10x expected r² ({r2_ref:.1e})")
R['unstable_days'] = unstable_count

# Write back
with open(RESULTS_PATH, 'w') as f:
    json.dump(R, f, indent=2, default=str)
print(f"\nResults JSON updated with per-refit tau summary.")
