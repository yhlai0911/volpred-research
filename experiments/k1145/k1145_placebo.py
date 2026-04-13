#!/usr/bin/env python3
"""
K1145 placebo test (Codex-suggested supplement)
================================================
Within-stock permutation of EAV dates, refit pooled BCD, check if
theta_EAV pooled signal disappears under null.

If true placebo: pooled theta_EAV under permutation should center around
0 with SE comparable to bootstrap SE. If pooled signal is real, observed
+6.36e-5 should be far in the right tail of the placebo distribution.

Outputs k1145_placebo_results.json + adds rejection rate to verdict.
"""

import os
import sys
import json
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(SCRIPT_DIR))
from k1145 import (
    load_one_stock, fit_pooled_panel, hessian_se_theta_eav, TICKERS,
    GLOBAL_SEED,
)

OBSERVED_THETA_EAV = 6.3622e-5  # from main run
N_PLACEBO = 60  # smaller than bootstrap; permutation is its own null


def shuffle_eav_within_stock(stock, rng):
    """Permute the eav binary array within a stock; preserves total
    number of events but breaks the time-alignment with returns."""
    new = stock['eav'].copy()
    rng.shuffle(new)
    return {**stock, 'eav': new}


def main():
    print('=== K1145 placebo: within-stock permutation of EAV ===')
    rng = np.random.default_rng(GLOBAL_SEED)
    print('Loading stocks...')
    stocks = []
    for tk in TICKERS:
        s = load_one_stock(tk, eav_window=1)
        if s is not None:
            stocks.append(s)
    print(f'Loaded {len(stocks)} stocks')

    placebo_thetas = []
    placebo_ts = []
    t0 = time.time()
    for b in range(N_PLACEBO):
        permuted = [shuffle_eav_within_stock(s, rng) for s in stocks]
        try:
            fit = fit_pooled_panel(
                permuted, max_outer=3, verbose=False,
                init_vix=9e-8, init_eav=0.0,
                time_budget=120,
            )
            se = hessian_se_theta_eav(
                permuted, [np.array(p) for p in fit['per_stock_params']],
                fit['theta_vix'], fit['theta_eav'],
            )
            t = (fit['theta_eav'] / se) if (se and se > 0) else np.nan
            placebo_thetas.append(fit['theta_eav'])
            placebo_ts.append(float(t) if np.isfinite(t) else None)
            elapsed = time.time() - t0
            print(f'  placebo {b+1}/{N_PLACEBO}: theta_EAV={fit["theta_eav"]:+.3e}, t={t:+.2f}, elapsed={elapsed:.0f}s')
        except Exception as e:
            print(f'  placebo {b+1}: FAIL {e}')

    placebo_thetas = np.array(placebo_thetas)
    rejection_rate = float(np.mean(placebo_thetas >= OBSERVED_THETA_EAV))
    placebo_mean = float(np.mean(placebo_thetas))
    placebo_se = float(np.std(placebo_thetas, ddof=1))
    placebo_ci = [
        float(np.percentile(placebo_thetas, 2.5)),
        float(np.percentile(placebo_thetas, 97.5)),
    ]
    print('\n=== Placebo summary ===')
    print(f'N placebo = {len(placebo_thetas)}')
    print(f'placebo mean θ_EAV = {placebo_mean:+.3e}')
    print(f'placebo SE = {placebo_se:.3e}')
    print(f'placebo 95% CI = [{placebo_ci[0]:+.3e}, {placebo_ci[1]:+.3e}]')
    print(f'observed θ_EAV = {OBSERVED_THETA_EAV:+.3e}')
    print(f'P(placebo >= observed) = {rejection_rate:.3f}')
    print(f'  (small p = real signal; placebo distribution centered at 0 with much smaller variance = strong evidence)')

    out = {
        'experiment_id': 'K1145_placebo',
        'description': 'Within-stock EAV permutation placebo, refit pooled MLE',
        'n_placebo': int(len(placebo_thetas)),
        'observed_theta_eav': OBSERVED_THETA_EAV,
        'placebo_mean': placebo_mean,
        'placebo_se': placebo_se,
        'placebo_ci_95': placebo_ci,
        'rejection_rate_one_sided': rejection_rate,
        'placebo_thetas': placebo_thetas.tolist(),
        'placebo_ts': placebo_ts,
        'random_seed': GLOBAL_SEED,
        'elapsed_seconds': float(time.time() - t0),
    }
    out_path = SCRIPT_DIR / 'k1145_placebo_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'\nResults -> {out_path}')


if __name__ == '__main__':
    main()
