"""K1412 — TW0050-N225 Harvey-sig OOS sensitivity (rule out type-I).

Paper3_E2 Open Question (research_program.md):
TW0050-N225 是 cross-market copula 10 pairs 中原始 raw-DM 規則下唯一
Harvey-sig pair (Student-t DM_t=3.92, oos_start=2015-06-01). 三因子
candidate:
  (a) λ_L_clayton=0.444  (b) full_sample_corr=0.586
  (c) Asian trading-hour overlap

本實驗：固定 pair=TW0050-N225 + 固定 window/refit_every，
跑 5 OOS starts (2014/2015/2016/2017/2018)，
若 ≥4/5 variant Harvey-sig PASS → 結論 robust 非 type-I error；
否則 type-I 嫌疑放大。

複用 paper3_E2.py 的 model fitting + DM + Harvey-HLN，
single pair 跑 ~50s/run × 5 = ~250s 預估。
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

# Reuse paper3_E2 module
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
P3E2_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), 'paper3_E2_cross_market_copula')
sys.path.insert(0, P3E2_DIR)
import paper3_E2 as p3e2  # noqa: E402

EXPERIMENT_ID = "K1412"
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1412_results.json')

# Fixed pair (TW0050-N225)
PAIR_NAME = 'TW0050-N225'
A1, A2 = 'TW0050', 'N225'
REG1, REG2 = 'vix2', 'vix2'

# 5 OOS starts
OOS_STARTS = ['2014-01-02', '2015-06-01', '2016-01-04', '2017-01-03', '2018-01-02']

# Fixed window/refit (matches paper3_E2 canonical)
WINDOW = 1250
REFIT_EVERY = 63


def main():
    t0 = time.time()
    print(f"=== K1412: TW0050-N225 OOS sensitivity ===")
    print(f"5 OOS starts × window={WINDOW} × refit_every={REFIT_EVERY}")

    # Patch paper3_E2 globals (single-pair, fixed config)
    p3e2.WINDOW = WINDOW
    p3e2.REFIT_EVERY = REFIT_EVERY
    p3e2.MC_PATHS = 5000
    p3e2.MODELS_FILTER = ['DCC-A4f-ASYM', 'Copula-t-A4f-ASYM',
                          'Copula-Clayton-A4f-ASYM']

    df = p3e2.load_data()

    per_oos = {}
    for oos in OOS_STARTS:
        elapsed = time.time() - t0
        print(f"\n>>> [{elapsed:.0f}s] OOS_START={oos} ...")
        p3e2.OOS_START = oos
        try:
            pr = p3e2.evaluate_pair(PAIR_NAME, A1, A2, REG1, REG2, df)
        except Exception as e:
            print(f"  FAIL ({type(e).__name__}: {e})")
            per_oos[oos] = {'error': f"{type(e).__name__}: {e}"}
            continue

        dm_t = pr['dm_qlike'].get('DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM',
                                  {'t_stat': np.nan,
                                   'significant_harvey': False,
                                   'p_value': np.nan})
        dm_c = pr['dm_qlike'].get('DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM',
                                  {'t_stat': np.nan,
                                   'significant_harvey': False,
                                   'p_value': np.nan})
        best_cop = 'Student-t' if dm_t['t_stat'] > dm_c['t_stat'] else 'Clayton'
        best_dm = dm_t if best_cop == 'Student-t' else dm_c

        per_oos[oos] = {
            'lambda_L_t_mean': pr['copula_stats']['student_t']['lambda_L_mean'],
            'lambda_L_clayton_mean': pr['copula_stats']['clayton']['lambda_L_mean'],
            'full_sample_corr': pr['full_sample_corr'],
            'mean_qlike_dcc': pr['mean_qlike'].get('DCC-A4f-ASYM', np.nan),
            'mean_qlike_copula_t': pr['mean_qlike'].get('Copula-t-A4f-ASYM',
                                                        np.nan),
            'mean_qlike_clayton': pr['mean_qlike'].get(
                'Copula-Clayton-A4f-ASYM', np.nan),
            'dm_dcc_vs_t': dm_t['t_stat'],
            'dm_dcc_vs_clayton': dm_c['t_stat'],
            'harvey_pass_t': bool(dm_t['significant_harvey']),
            'harvey_pass_clayton': bool(dm_c['significant_harvey']),
            'best_copula': best_cop,
            'best_dm_t': best_dm['t_stat'],
            'best_harvey_pass': bool(best_dm['significant_harvey']),
            'n_oos_obs': pr.get('n_oos_obs'),
        }

        # Checkpoint
        with open(RESULTS_PATH, 'w') as f:
            json.dump({
                'experiment_id': EXPERIMENT_ID,
                'pair': PAIR_NAME,
                'config': {'window': WINDOW, 'refit_every': REFIT_EVERY,
                           'mc_paths': 5000, 'seed': 42},
                'oos_starts': OOS_STARTS,
                'per_oos': p3e2.to_json_safe(per_oos),
                'timestamp_partial': datetime.now(timezone.utc).isoformat(),
                'parent_experiments': ['Paper3_E2'],
            }, f, indent=2)

    # Summary
    completed = [o for o in OOS_STARTS if 'error' not in per_oos.get(o, {})]
    n_complete = len(completed)
    n_harvey_pass = sum(1 for o in completed
                        if per_oos[o].get('best_harvey_pass'))
    robust_ratio = n_harvey_pass / n_complete if n_complete else 0.0
    verdict = ('ROBUST (≥4/5 Harvey-sig)' if robust_ratio >= 0.8
               else ('PARTIAL (3/5)' if robust_ratio >= 0.6
                     else 'TYPE-I_SUSPECT (<3/5 Harvey-sig)'))

    summary = {
        'n_oos_completed': n_complete,
        'n_harvey_sig': n_harvey_pass,
        'robust_ratio': robust_ratio,
        'verdict': verdict,
        'per_oos_harvey_clayton': {o: per_oos[o].get('harvey_pass_clayton')
                                   for o in completed},
        'per_oos_dm_clayton': {o: per_oos[o].get('dm_dcc_vs_clayton')
                               for o in completed},
        'lambda_L_clayton_range': [
            float(min(per_oos[o]['lambda_L_clayton_mean'] for o in completed)),
            float(max(per_oos[o]['lambda_L_clayton_mean'] for o in completed)),
        ] if completed else None,
        'full_sample_corr_range': [
            float(min(per_oos[o]['full_sample_corr'] for o in completed)),
            float(max(per_oos[o]['full_sample_corr'] for o in completed)),
        ] if completed else None,
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump({
            'experiment_id': EXPERIMENT_ID,
            'pair': PAIR_NAME,
            'config': {'window': WINDOW, 'refit_every': REFIT_EVERY,
                       'mc_paths': 5000, 'seed': 42},
            'oos_starts': OOS_STARTS,
            'per_oos': p3e2.to_json_safe(per_oos),
            'summary': p3e2.to_json_safe(summary),
            'runtime_seconds': time.time() - t0,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'parent_experiments': ['Paper3_E2'],
            'references': [
                'Paper3_E2 (paper3_E2_cross_market_copula, 2026-05-29)',
                'research_program.md Open Question (TW0050-N225 唯一 Harvey-sig)',
                'Harvey/Liu/Newman (1997) HLN small-sample DM correction',
                'Patton (2006) IER 47(2) tail dependence copula',
            ],
        }, f, indent=2)

    print(f"\n=== K1412 DONE in {time.time()-t0:.0f}s ===")
    print(f"verdict: {verdict}")
    print(f"per-OOS Harvey-clayton: {summary['per_oos_harvey_clayton']}")


if __name__ == '__main__':
    main()
