#!/usr/bin/env python3
"""
K1151 placebo — within-stock permutation of continuous surprise signal.

Mirrors K1147 placebo but for the continuous spec:
  - For each stock, shuffle the surp_z vector in place (preserve marginal
    distribution within stock, break time alignment).
  - Refit pooled panel.
  - Under the null (no real time-aligned surprise → vol signal), the
    refit θ_SURP should center at ~0.

60 reps.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(SCRIPT_DIR))
from k1151 import (  # noqa: E402
    load_one_stock, standardize_continuous, fit_pooled_panel,
    hessian_se_theta_x, TICKERS, GLOBAL_SEED, RESULTS_PATH,
)

N_PLACEBO = 60


def shuffle_surp_z_within_stock(stock, rng):
    new = stock['surp_z'].copy()
    rng.shuffle(new)
    return {**stock, 'surp_z': new}


def main():
    with open(RESULTS_PATH) as f:
        main_results = json.load(f)
    observed = main_results['continuous_surprise']['theta_surp']

    print('=== K1151 placebo: within-stock permutation of continuous surp_z ===')
    print(f'Observed (main) θ_SURP = {observed:+.4e}')
    rng = np.random.default_rng(GLOBAL_SEED)

    print('Loading stocks ...')
    stocks = []
    for tk in TICKERS:
        s = load_one_stock(tk, window=1)
        if s is not None:
            stocks.append(s)
    stocks, _ = standardize_continuous(stocks)
    print(f'  Loaded {len(stocks)} stocks')

    placebo_thetas = []
    placebo_ts = []
    t0 = time.time()
    for b in range(N_PLACEBO):
        permuted = [shuffle_surp_z_within_stock(s, rng) for s in stocks]
        try:
            fit = fit_pooled_panel(
                permuted, 'surp_z', max_outer=3, verbose=False,
                init_vix=9e-8, init_x=0.0,
                time_budget=120,
                bounds_x=(-1e-2, 1e-2),
            )
            se = hessian_se_theta_x(
                permuted, 'surp_z',
                [np.array(p) for p in fit['per_stock_params']],
                fit['theta_vix'], fit['theta_x'],
            )
            t = (fit['theta_x'] / se) if (se and se > 0) else np.nan
            placebo_thetas.append(fit['theta_x'])
            placebo_ts.append(float(t) if np.isfinite(t) else None)
            elapsed = time.time() - t0
            print(f'  placebo {b+1}/{N_PLACEBO}: theta={fit["theta_x"]:+.3e}, '
                  f't={t:+.2f}, elapsed={elapsed:.0f}s')
        except Exception as e:
            print(f'  placebo {b+1}: FAIL {e}')

    placebo_thetas = np.array(placebo_thetas)
    if len(placebo_thetas) == 0:
        print('  All placebo failed')
        return
    rejection_rate = float(np.mean(placebo_thetas >= observed))
    mean = float(np.mean(placebo_thetas))
    se = float(np.std(placebo_thetas, ddof=1))
    ci = [float(np.percentile(placebo_thetas, 2.5)),
          float(np.percentile(placebo_thetas, 97.5))]
    z = (observed - mean) / se if se > 0 else np.nan

    print('\n=== Placebo summary ===')
    print(f'N = {len(placebo_thetas)}')
    print(f'mean = {mean:+.3e}, SE = {se:.3e}')
    print(f'95% CI = [{ci[0]:+.3e}, {ci[1]:+.3e}]')
    print(f'observed = {observed:+.3e}')
    print(f'observed z = {z:+.2f}')
    print(f'P(placebo >= observed) = {rejection_rate:.4f}')

    out = {
        'experiment_id': 'K1151_placebo',
        'description': 'Within-stock permutation of continuous surp_z; refit pooled MLE',
        'n_placebo': int(len(placebo_thetas)),
        'observed_theta_surp': observed,
        'placebo_mean': mean,
        'placebo_se': se,
        'placebo_ci_95': ci,
        'rejection_rate_one_sided': rejection_rate,
        'z_observed_relative_to_placebo': float(z) if np.isfinite(z) else None,
        'placebo_thetas': placebo_thetas.tolist(),
        'placebo_ts': placebo_ts,
        'random_seed': GLOBAL_SEED,
        'elapsed_seconds': float(time.time() - t0),
    }
    out_path = SCRIPT_DIR / 'k1151_placebo_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'\nResults -> {out_path}')


if __name__ == '__main__':
    main()
