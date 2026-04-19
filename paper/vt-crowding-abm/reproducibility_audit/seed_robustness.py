#!/usr/bin/env python3
"""Seed robustness check for K827v3 ABM tipping point.

Purpose: verify the 50-70% tipping point (Sharpe collapse, Kurt spike)
is not a single-seed artifact.

Approach: rerun the same core simulation logic with 3 seed offsets
(42 [paper default], 13, 7). Smaller Monte Carlo count (N_SIMS=120)
per cell to keep runtime manageable (~3x original runtime).

Stability criteria:
- Sharpe at each adoption level: range across seeds <30% of mean
- Critical threshold (first Sharpe degradation >30%) identical region
- Kurtosis spike at 70% and 100% directionally preserved

Author: Paper 5 pre-submission audit (Claude, 2026-04-18)
"""
import os, sys, json, time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'experiments'))

import numpy as np
from scipy import stats as sp_stats
from multiprocessing import Pool, cpu_count

# Import simulation core from k827v3 script
from k827v3_abm_fixed_liquidity import (
    run_single_simulation, aggregate_metrics,
    N_BH_VT_POOL, N_NOISE_FIXED, BASELINE_PARAMS,
)

VT_FRACTIONS = [0.10, 0.30, 0.50, 0.70, 1.00]
N_SIMS = 120  # smaller than 500, still gives stable means
SEED_OFFSETS = [42, 13, 7]  # 42 = paper default

N_WORKERS = min(cpu_count(), 8)


def run_for_seed_offset(offset: int):
    results = {}
    for vt_frac in VT_FRACTIONS:
        label = f"{int(vt_frac*100)}%"
        args_list = [
            (vt_frac, int(vt_frac * 100000) + sim_idx + offset, {})
            for sim_idx in range(N_SIMS)
        ]
        with Pool(N_WORKERS) as pool:
            sim_results = pool.map(run_single_simulation, args_list)
        agg = aggregate_metrics(sim_results)
        results[label] = agg
    return results


def extract_scalar(d, key):
    v = d.get(key)
    return v['mean'] if v else None


def main():
    t0 = time.time()
    all_runs = {}
    for offset in SEED_OFFSETS:
        print(f"\n=== Seed offset {offset} (N_SIMS={N_SIMS}) ===")
        t_s = time.time()
        r = run_for_seed_offset(offset)
        all_runs[str(offset)] = r
        for lvl in VT_FRACTIONS:
            label = f"{int(lvl*100)}%"
            s = extract_scalar(r[label], 'vt_sharpe')
            v = extract_scalar(r[label], 'ann_vol')
            k = extract_scalar(r[label], 'kurtosis')
            print(f"  {label:>5s}: Sharpe={s:.4f}, Vol={v:.4f}, Kurt={k:.3f}")
        print(f"  elapsed {time.time()-t_s:.1f}s")

    # Cross-seed stability
    print("\n=== Seed stability summary ===")
    summary = {}
    tipping_regions = []
    for lvl in VT_FRACTIONS:
        label = f"{int(lvl*100)}%"
        sharpes = [extract_scalar(all_runs[str(o)][label], 'vt_sharpe') for o in SEED_OFFSETS]
        vols = [extract_scalar(all_runs[str(o)][label], 'ann_vol') for o in SEED_OFFSETS]
        kurts = [extract_scalar(all_runs[str(o)][label], 'kurtosis') for o in SEED_OFFSETS]
        s_mean = float(np.mean(sharpes))
        s_range = float(max(sharpes) - min(sharpes))
        s_rel = s_range / abs(s_mean) if abs(s_mean) > 1e-6 else float('inf')
        summary[label] = {
            'sharpe_by_seed': {str(o): s for o, s in zip(SEED_OFFSETS, sharpes)},
            'sharpe_mean': s_mean,
            'sharpe_range': s_range,
            'sharpe_rel_range': s_rel,
            'vol_by_seed': {str(o): v for o, v in zip(SEED_OFFSETS, vols)},
            'kurt_by_seed': {str(o): k for o, k in zip(SEED_OFFSETS, kurts)},
        }
        print(f"  {label:>5s}: Sharpe {sharpes} -> mean={s_mean:.4f}, range={s_range:.4f} ({s_rel*100:.1f}% rel)")

    # Critical threshold per seed
    print("\n=== Critical threshold per seed ===")
    for o in SEED_OFFSETS:
        r = all_runs[str(o)]
        s10 = extract_scalar(r['10%'], 'vt_sharpe')
        tip = None
        for lvl in [0.30, 0.50, 0.70, 1.00]:
            label = f"{int(lvl*100)}%"
            s = extract_scalar(r[label], 'vt_sharpe')
            if s is None:
                continue
            deg = (1 - s / s10) * 100
            if deg > 30 and tip is None:
                tip = label
        tipping_regions.append(tip)
        print(f"  seed={o}: critical threshold = {tip}")

    unique_tips = set(tipping_regions)
    stable = (len(unique_tips) == 1) and ('50%' in unique_tips or '70%' in unique_tips)
    print(f"\n  Critical thresholds: {tipping_regions}")
    print(f"  Stable across seeds? {stable}")

    total = time.time() - t0
    out = {
        'audit': 'Paper 5 seed robustness',
        'timestamp': datetime.now().isoformat(),
        'n_sims_per_cell': N_SIMS,
        'seed_offsets': SEED_OFFSETS,
        'vt_fractions': VT_FRACTIONS,
        'runtime_seconds': total,
        'summary_by_level': summary,
        'critical_thresholds_by_seed': {str(o): t for o, t in zip(SEED_OFFSETS, tipping_regions)},
        'tipping_stable': stable,
    }
    out_path = os.path.join(os.path.dirname(__file__), 'seed_robustness_results.json')
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {out_path}")
    print(f"Total runtime: {total:.1f}s")


if __name__ == '__main__':
    main()
