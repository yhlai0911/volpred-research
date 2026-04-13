#!/usr/bin/env python3
"""
K1162 placebo — within-stock permutation of continuous surp_z for each
subset (HIGH / LOW).

For each of {LOW, HIGH} subsets:
  - Load stocks and standardize within subset (same as k1162.py main).
  - For each of N_PLACEBO reps, shuffle surp_z within each stock.
  - Refit pooled panel on shuffled data.
  - Compare the observed θ_SURP to the permutation null.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(SCRIPT_DIR))
from k1162 import (  # noqa: E402
    load_one_stock, standardize_continuous, fit_pooled_panel,
    hessian_se_theta_x, COVERAGE_PATH, RESULTS_PATH, GLOBAL_SEED,
)

N_PLACEBO = 60


def shuffle_surp_z_within_stock(stock, rng):
    new = stock['surp_z'].copy()
    rng.shuffle(new)
    return {**stock, 'surp_z': new}


def run_placebo_for_subset(label, tickers_subset, observed_theta, rng):
    print(f'\n=== Placebo for subset {label} ({len(tickers_subset)} tickers) ===')
    stocks = []
    for tk in tickers_subset:
        s = load_one_stock(tk, window=1)
        if s is not None:
            stocks.append(s)
    stocks, _ = standardize_continuous(stocks)
    print(f'  Loaded {len(stocks)} stocks for subset {label}')

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
            if (b + 1) % 10 == 0 or b == 0:
                print(f'  [{label}] placebo {b+1}/{N_PLACEBO}: θ={fit["theta_x"]:+.3e}, '
                      f't={t:+.2f}, elapsed={elapsed:.0f}s')
        except Exception as e:
            print(f'  [{label}] placebo {b+1}: FAIL {e}')

    placebo_thetas = np.array(placebo_thetas)
    if len(placebo_thetas) == 0:
        return {'label': label, 'status': 'all_fail'}
    rejection_rate = float(np.mean(placebo_thetas >= observed_theta))
    mean = float(np.mean(placebo_thetas))
    se = float(np.std(placebo_thetas, ddof=1))
    ci = [float(np.percentile(placebo_thetas, 2.5)),
          float(np.percentile(placebo_thetas, 97.5))]
    z = (observed_theta - mean) / se if se > 0 else np.nan

    print(f'\n  [{label}] Placebo summary:')
    print(f'    N = {len(placebo_thetas)}')
    print(f'    mean = {mean:+.3e}, SE = {se:.3e}')
    print(f'    95% CI = [{ci[0]:+.3e}, {ci[1]:+.3e}]')
    print(f'    observed = {observed_theta:+.3e}, z = {z:+.2f}')
    print(f'    P(placebo >= observed) = {rejection_rate:.4f}')

    return {
        'label': label,
        'n_placebo': int(len(placebo_thetas)),
        'observed_theta_surp': observed_theta,
        'placebo_mean': mean,
        'placebo_se': se,
        'placebo_ci_95': ci,
        'rejection_rate_one_sided': rejection_rate,
        'z_observed_relative_to_placebo': float(z) if np.isfinite(z) else None,
        'placebo_thetas': placebo_thetas.tolist(),
        'placebo_ts': placebo_ts,
    }


def main():
    with open(RESULTS_PATH) as f:
        main_results = json.load(f)
    obs_H = main_results['subset_HIGH']['continuous']['theta_surp']
    obs_L = main_results['subset_LOW']['continuous']['theta_surp']
    tickers_H = main_results['tickers_high']
    tickers_L = main_results['tickers_low']

    rng = np.random.default_rng(GLOBAL_SEED)
    t0 = time.time()

    res_low = run_placebo_for_subset('LOW', tickers_L, obs_L, rng)
    res_high = run_placebo_for_subset('HIGH', tickers_H, obs_H, rng)

    out = {
        'experiment_id': 'K1162_placebo',
        'description': 'Within-stock permutation of continuous surp_z (surp-z shuffled within each stock); refit pooled MLE on each subset',
        'n_placebo_each': N_PLACEBO,
        'random_seed': GLOBAL_SEED,
        'subset_LOW': res_low,
        'subset_HIGH': res_high,
        'elapsed_seconds': float(time.time() - t0),
    }
    out_path = SCRIPT_DIR / 'k1162_placebo_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'\nResults -> {out_path}')


if __name__ == '__main__':
    main()
