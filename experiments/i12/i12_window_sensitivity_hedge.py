"""
I12: Rolling Window Sensitivity for Hedge Ratio Estimation
Tests multiple window sizes in parallel using multiprocessing.

Windows: 30, 60, 120, 250, 500, 1000 days
Methods: Rolling OLS + EWMA with different decay parameters
Pairs: SPY-ES, GLD-GC, TLT-ZN (representative)

Uses multiprocessing for parallel window evaluation.
Evaluation: Ederington HE, DM test vs Naive.

Data: yfinance, OOS 2020-2025
Output: experiments/i12/i12_window_sensitivity_results.json
"""
from pathlib import Path

import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from multiprocessing import Pool
import json, warnings, time
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_FILE = EXPERIMENT_DIR / 'i12_window_sensitivity_results.json'

def evaluate_config(args):
    """Evaluate one (pair, window, method) configuration."""
    spot_t, fut_t, pair_name, window, method = args

    try:
        spot = yf.download(spot_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()
        fut = yf.download(fut_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()
    except:
        return None

    common = spot.index.intersection(fut.index)
    spot, fut = spot.loc[common], fut.loc[common]
    s_ret = spot.pct_change().dropna()
    f_ret = fut.pct_change().dropna().reindex(s_ret.index).fillna(0)

    oos_start = '2020-01-01'
    oos_mask = s_ret.index >= oos_start
    s_oos = s_ret[oos_mask]
    f_oos = f_ret[oos_mask]
    n_oos = len(s_oos)

    if n_oos < 100:
        return None

    all_s = s_ret.values
    all_f = f_ret.values
    all_idx = s_ret.index
    oos_start_loc = int(np.where(all_idx >= oos_start)[0][0])

    unhedged_var = float(s_oos.var())
    hedged_naive = s_oos - 1.0 * f_oos

    if method == 'rolling_ols':
        h_vals = []
        for t in range(oos_start_loc, len(all_s)):
            start = max(0, t - window)
            s_w = all_s[start:t]
            f_w = all_f[start:t]
            if len(s_w) < 30:
                h_vals.append(1.0)
                continue
            var_f = np.var(f_w, ddof=1)
            h_vals.append(np.cov(s_w, f_w)[0, 1] / var_f if var_f > 0 else 1.0)
        h = pd.Series(h_vals, index=s_oos.index)

    elif method.startswith('ewma_'):
        lam = float(method.split('_')[1])
        init_start = max(0, oos_start_loc - window)
        ewma_cov = float(np.cov(all_s[init_start:oos_start_loc], all_f[init_start:oos_start_loc])[0, 1])
        ewma_var = float(np.var(all_f[init_start:oos_start_loc], ddof=1))
        h_vals = []
        for t in range(oos_start_loc, len(all_s)):
            h_vals.append(ewma_cov / ewma_var if ewma_var > 0 else 1.0)
            ewma_cov = lam * ewma_cov + (1 - lam) * all_s[t] * all_f[t]
            ewma_var = lam * ewma_var + (1 - lam) * all_f[t]**2
        h = pd.Series(h_vals, index=s_oos.index)

    hedged = s_oos - h * f_oos
    he = float(1 - hedged.var() / unhedged_var)

    # DM vs Naive
    sq_naive = hedged_naive**2
    sq_comp = hedged**2
    d = sq_naive - sq_comp
    d = d.dropna()
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if len(d) > 0 and d.std() > 0 else 0

    avg_h = float(h.mean())
    h_std = float(h.std())
    turnover = float(h.diff().abs().mean()) * 252

    return {
        'pair': pair_name, 'window': window, 'method': method,
        'HE': round(he, 4), 'avg_h': round(avg_h, 4), 'h_std': round(h_std, 4),
        'turnover': round(turnover, 2), 'dm_t': round(dm_t, 2),
    }


if __name__ == '__main__':
    pairs = [
        ('SPY', 'ES=F', 'SPY-ES'),
        ('GLD', 'GC=F', 'GLD-GC'),
        ('TLT', 'ZN=F', 'TLT-ZN'),
    ]

    windows = [30, 60, 120, 250, 500, 1000]
    ewma_lambdas = [0.90, 0.94, 0.97, 0.99]

    # Build all configurations
    configs = []
    for spot_t, fut_t, name in pairs:
        for w in windows:
            configs.append((spot_t, fut_t, name, w, 'rolling_ols'))
        for lam in ewma_lambdas:
            configs.append((spot_t, fut_t, name, 0, f'ewma_{lam}'))

    print(f"I12: Window Sensitivity ({len(configs)} configs, 3 pairs)")
    print("=" * 90)

    start = time.time()
    with Pool(8) as pool:
        results_list = pool.map(evaluate_config, configs)
    elapsed = time.time() - start

    results_list = [r for r in results_list if r is not None]
    print(f"Completed {len(results_list)} configs in {elapsed:.0f}s")

    # Print results by pair
    for pair_name in ['SPY-ES', 'GLD-GC', 'TLT-ZN']:
        pair_res = [r for r in results_list if r['pair'] == pair_name]
        print(f"\n{'='*75}")
        print(f"{pair_name}")
        print(f"{'Method':<18} {'Window':>7} {'HE':>7} {'Avg h':>7} {'h Std':>7} {'Turn':>7} {'DM t':>7}")
        print("-" * 60)

        # Naive baseline
        print(f"{'Naive':<18} {'—':>7} {'—':>7} {'1.000':>7} {'0.000':>7} {'0.00':>7} {'—':>7}")

        for r in sorted(pair_res, key=lambda x: (x['method'], x['window'])):
            w_str = str(r['window']) if r['window'] > 0 else "—"
            sig = "★" if r['dm_t'] > 3 else ""
            print(f"{r['method']:<18} {w_str:>7} {r['HE']:>6.1%} {r['avg_h']:>7.3f} {r['h_std']:>7.3f} {r['turnover']:>7.1f} {r['dm_t']:>6.1f}{sig}")

    # Save
    output = {
        'experiment': 'I12',
        'title': 'Window Sensitivity for Hedge Ratio (multiprocessing)',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'computation': {'configs': len(configs), 'elapsed_sec': round(elapsed)},
        'results': results_list,
    }

    with open(RESULTS_FILE, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nResults saved to {RESULTS_FILE}")
