#!/usr/bin/env python3
"""
K1109 Pre-registration builder.

Produces `prereg_sample.json` with the ticker list that will be used for
K1109 confirmatory analysis. The sample is fixed BEFORE any estimation
is run (pre-registration, to avoid cherry-pick bias identified in E052).

Selection rule (as specified in the task brief):
  - Build per-sector pools (sizes 3-6 each) chosen before seeing results.
  - From each pool, randomly draw `target_n` firms using numpy RNG with
    seed=42. If pool < target_n, take the whole pool (flag as exhausted).
  - Target N across all sectors: ~30-40 firms.

Author: VolPred Research System
Date: 2026-04-13
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SEED = 42
OUT_PATH = Path(__file__).parent / 'prereg_sample.json'

# Sector pools (all decided BEFORE estimation, per task brief).
# Some Task-brief typos resolved by strict reading:
#   - Consumer pool: drop duplicates (2330 is foundry, 2881 is financial).
#   - tech_other: task listed 2888/2892 which are *actually* financials
#     (Shin Kong Financial, First Financial). We keep the task-specified
#     labels to preserve pre-registration discipline; robustness analysis
#     in Stage 3 will also run without tech_other.
SECTOR_POOLS = {
    'foundry':      ['2330', '2303', '6239'],
    'fabless':      ['2454', '2379', '3034', '3035', '3443', '2388'],
    'financials':   ['2881', '2882', '2883', '2886', '2887'],
    'shipping':     ['2603', '2615', '2609'],
    'trad_mfg':     ['1301', '1303', '1326', '2002', '2027'],
    'ems':          ['2317', '3045', '2382'],
    'consumer':     ['2912', '1216', '2637', '1215', '2347', '1210'],
    'tech_other':   ['2888', '2892'],
}

TARGET_N = {
    'foundry':     3,
    'fabless':     6,
    'financials':  5,
    'shipping':    3,
    'trad_mfg':    5,
    'ems':         3,
    'consumer':    5,
    'tech_other':  3,  # pool only has 2; will be exhausted
}

FIRM_NAMES = {
    '2330': 'TSMC',            '2303': 'UMC',          '6239': 'Powertech',
    '2454': 'MediaTek',        '2379': 'Realtek',      '3034': 'Novatek',
    '3035': 'FarEastone Info', '3443': 'GlobalWafer',  '2388': 'VIA Tech',
    '2881': 'Fubon FH',        '2882': 'Cathay FH',    '2883': 'China Dev FH',
    '2886': 'Mega FH',         '2887': 'Taishin FH',
    '2603': 'Evergreen',       '2615': 'Wan Hai',      '2609': 'Yang Ming',
    '1301': 'Formosa',         '1303': 'Nan Ya',       '1326': 'FCFC',
    '2002': 'China Steel',     '2027': 'ChiaTai Steel',
    '2317': 'Hon Hai',         '3045': 'TWM',          '2382': 'Quanta',
    '2912': 'Pres. Chain',     '1216': 'Uni-President','2637': 'Yungshin',
    '1215': 'Charoen Pokphand','2347': 'Synnex',       '1210': 'Dachan Food',
    '2888': 'Shin Kong FH',    '2892': 'First FH',
}


def main():
    rng = np.random.default_rng(SEED)
    sample = []
    log = {}
    for sector, pool in SECTOR_POOLS.items():
        target = TARGET_N[sector]
        n_pool = len(pool)
        if n_pool == 0:
            log[sector] = {'n_drawn': 0, 'n_pool': 0, 'exhausted': False, 'drawn': []}
            continue
        if n_pool <= target:
            drawn = list(pool)
            exhausted = True
        else:
            idx = rng.choice(n_pool, size=target, replace=False)
            drawn = [pool[i] for i in sorted(idx)]
            exhausted = False
        for code in drawn:
            sample.append({
                'code': code,
                'ticker': f'{code}.TW',
                'name': FIRM_NAMES.get(code, f'Unknown-{code}'),
                'sector': sector,
            })
        log[sector] = {
            'n_pool': n_pool,
            'n_drawn': len(drawn),
            'target': target,
            'exhausted': exhausted,
            'drawn': drawn,
        }

    out = {
        'experiment_id': 'K1109',
        'title': 'Pre-registered random sector sample (confirmatory)',
        'pre_registration_timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': SEED,
        'sector_pools': SECTOR_POOLS,
        'target_n_per_sector': TARGET_N,
        'selection_rule': (
            "For each sector, draw `target` firms at random from the pool "
            "using numpy.random.default_rng(seed=42). If pool <= target, "
            "take all pool members and flag exhausted=True. Sample is "
            "locked BEFORE any Stage 1 estimation. Modifying the sample "
            "after looking at results would re-introduce the cherry-pick "
            "bias identified in E052 (K1106b)."
        ),
        'n_total_firms': len(sample),
        'sample_breakdown': log,
        'sample': sample,
        'notes': [
            'tech_other pool contains 2888 and 2892 which industry '
            'classification typically lists as financials. We preserve '
            'the task-supplied labels to respect pre-registration; '
            'robustness analysis in Stage 3 will drop tech_other.',
            'Consumer-pool typos removed: task listed 2330 (actually '
            'foundry) and 2881 (actually financials) — we drop the '
            'duplicates before sampling.',
        ],
    }

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'Pre-reg sample written to {OUT_PATH}')
    print(f'Total firms: {len(sample)}')
    for sector, info in log.items():
        flag = '[EXHAUSTED]' if info.get('exhausted') else ''
        print(f'  {sector:12s} {info["n_drawn"]}/{info["target"]:d} from pool of {info["n_pool"]:d} {flag}')

    return sample


if __name__ == '__main__':
    main()
