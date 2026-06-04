#!/usr/bin/env python3
"""
K1417: Paper 3 H2 — Stationary bootstrap with long mean block sizes.

Gemini v4 review (paper/vt-trend-following/review_history/v4/README.md) H2:

    Block size = 252 days, sample length 21 years (~5,300 obs). Each synthetic
    path = only ~21 independent blocks. Major drawdowns (2008, 2022) have
    peak-to-recovery paths well over 252 days. Scrambling 1-year blocks severs
    the autocorrelation of multi-year secular bear markets. Synthetic Buy-
    and-Hold MDDs are mechanically *shallower* than empirical ones because
    long-memory drawdown paths are broken. MDD_BH (denominator of retention)
    shrinks → retention ratio inflated → 90% CI lower bounds pushed upward.

    Required fix: Use stationary bootstrap with expected block size 3-5 years
    (preserves full peak-to-trough-to-recovery cycles), OR report absolute MDD
    differences rather than the highly sensitive retention ratio.

This experiment re-runs K1192's bootstrap with the Politis & Romano (1994)
stationary bootstrap at two mean block sizes: 756 trading days (~3 years) and
1260 trading days (~5 years). It tabulates how the retention CI shifts vs
K1192's fixed-block 252-day baseline.

Strategy construction (monthly VT, TSMOM hedge) reuses K1192's helpers
verbatim so the only methodological difference is the bootstrap. All other
inputs (data window, monthly VIX signal, SHY cash proxy, TSMOM lookback,
seed) are identical to K1192 to keep the comparison clean.

If H2 is correct, K1417 90% CI lower bounds will fall meaningfully below
K1192's [86, 90, 82, 91, 91] across the 5 asset classes once the stationary
bootstrap preserves multi-year drawdown autocorrelation.
"""

import json
import logging
import os
import sys
import warnings
from datetime import datetime

import numpy as np

# Reuse K1192 strategy + data helpers. K1192 module-level logging hard-codes a
# stale worktree path; stub FileHandler before importing so the import succeeds
# in the canonical repo location.
REPO_ROOT = '/Users/yhlai0911/Desktop/volpred-research'
sys.path.insert(0, os.path.join(REPO_ROOT, 'experiments', 'k1192'))

_orig_file_handler = logging.FileHandler
class _NullFileHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()
logging.FileHandler = _NullFileHandler  # type: ignore[assignment]
try:
    import k1192 as base  # noqa: E402
finally:
    logging.FileHandler = _orig_file_handler  # type: ignore[assignment]

warnings.filterwarnings('ignore')

# ====================================================
# Configuration
# ====================================================
MEAN_BLOCK_LENGTHS = [756, 1260]  # 3y and 5y in trading days
BOOTSTRAP_REPS_DEFAULT = 10_000
SEED = 42
CI_PCT = 90

# ====================================================
# Logging
# ====================================================
LOG_PATH = os.path.join(REPO_ROOT, 'experiments', 'k1417', 'run.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, mode='w'),
    ],
)
log = logging.getLogger('k1417')
# Quiet K1192's logger (it would otherwise duplicate progress lines).
base.log.setLevel(logging.WARNING)


# ====================================================
# Stationary bootstrap (Politis & Romano 1994)
# ====================================================
def _draw_stationary_indices(n, mean_block, rng):
    """
    Draw n indices via stationary bootstrap with geometric block lengths.

    At each step, with probability 1/mean_block start a new block at a
    uniformly random position; otherwise continue the current block by
    incrementing the index (wrapping around modulo n for circularity).
    Expected block length = mean_block.
    """
    p_new = 1.0 / mean_block
    out = np.empty(n, dtype=np.int64)
    out[0] = rng.randint(0, n)
    # Vectorise the new-block decisions; iterate the wrap-around cheaply.
    new_block = rng.random_sample(n) < p_new
    new_starts = rng.randint(0, n, size=n)
    cur = out[0]
    for t in range(1, n):
        if new_block[t]:
            cur = new_starts[t]
        else:
            cur = (cur + 1) % n
        out[t] = cur
    return out


def stationary_bootstrap_4defs(bh_rets, vt_rets, hedged_rets,
                               n_reps=BOOTSTRAP_REPS_DEFAULT,
                               mean_block=756, seed=SEED, ci_pct=CI_PCT):
    """
    Stationary bootstrap for the same 4 MDD CI definitions K1192 reports.

    Definitions (a)-(d) are identical to K1192.block_bootstrap_4defs; only the
    resampling scheme differs (stationary geometric blocks instead of fixed
    overlapping 252-day blocks).
    """
    rng = np.random.RandomState(seed)

    common = bh_rets.dropna().index.intersection(
        vt_rets.dropna().index).intersection(
        hedged_rets.dropna().index)
    bh = bh_rets.loc[common].values
    vt = vt_rets.loc[common].values
    hedged = hedged_rets.loc[common].values
    n = len(bh)

    alpha = 1 - ci_pct / 100
    lo_pct = alpha / 2 * 100
    hi_pct = (1 - alpha / 2) * 100

    def _mdd(r):
        w = np.cumprod(1 + r)
        pk = np.maximum.accumulate(w)
        return float(np.min(w / pk - 1))

    bh_mdd_pt = _mdd(bh)
    vt_mdd_pt = _mdd(vt)
    hedged_mdd_pt = _mdd(hedged)

    pt_retention = ((bh_mdd_pt - hedged_mdd_pt) / (bh_mdd_pt - vt_mdd_pt) * 100
                    if abs(bh_mdd_pt - vt_mdd_pt) > 1e-8 else np.nan)
    pt_vt_reduction = ((vt_mdd_pt - bh_mdd_pt) / abs(bh_mdd_pt) * 100
                       if bh_mdd_pt != 0 else np.nan)
    pt_hedged_abs = hedged_mdd_pt * 100
    pt_hedged_vs_bh = ((bh_mdd_pt - hedged_mdd_pt) / abs(bh_mdd_pt) * 100
                       if bh_mdd_pt != 0 else np.nan)

    log.info(f"  Point estimates: retention={pt_retention:.1f}%, "
             f"vt_red={pt_vt_reduction:.1f}%, hedged_abs={pt_hedged_abs:.1f}%, "
             f"hedged_vs_bh={pt_hedged_vs_bh:.1f}%")
    log.info(f"  Running {n_reps} stationary-bootstrap reps (mean_block={mean_block}, n={n})")

    a_vals, b_vals, c_vals, d_vals = [], [], [], []
    for rep in range(n_reps):
        idx = _draw_stationary_indices(n, mean_block, rng)
        bh_b = bh[idx]
        vt_b = vt[idx]
        h_b = hedged[idx]

        bh_mdd = _mdd(bh_b)
        vt_mdd = _mdd(vt_b)
        h_mdd = _mdd(h_b)

        denom = bh_mdd - vt_mdd
        if abs(denom) > 1e-8:
            a_vals.append((bh_mdd - h_mdd) / denom * 100)
        if bh_mdd != 0:
            b_vals.append((vt_mdd - bh_mdd) / abs(bh_mdd) * 100)
            d_vals.append((bh_mdd - h_mdd) / abs(bh_mdd) * 100)
        c_vals.append(h_mdd * 100)

        if (rep + 1) % 2000 == 0:
            log.info(f"    rep {rep+1}/{n_reps}")

    def ci_stats(arr, lo_p, hi_p):
        arr = np.array(arr)
        arr = arr[np.isfinite(arr)]
        if len(arr) < 100:
            return {'lo': np.nan, 'hi': np.nan, 'mean': np.nan,
                    'median': np.nan, 'n': int(len(arr))}
        return {
            'lo': round(float(np.percentile(arr, lo_p)), 1),
            'hi': round(float(np.percentile(arr, hi_p)), 1),
            'mean': round(float(np.mean(arr)), 1),
            'median': round(float(np.median(arr)), 1),
            'n': int(len(arr)),
        }

    return {
        'n_obs': n,
        'n_reps': n_reps,
        'mean_block': mean_block,
        'ci_pct': ci_pct,
        'lo_pct_used': lo_pct,
        'hi_pct_used': hi_pct,
        'point_estimates': {
            'bh_mdd_pct': round(bh_mdd_pt * 100, 2),
            'vt_mdd_pct': round(vt_mdd_pt * 100, 2),
            'hedged_mdd_pct': round(hedged_mdd_pt * 100, 2),
            'a_retention': round(pt_retention, 1) if np.isfinite(pt_retention) else None,
            'b_vt_reduction': round(pt_vt_reduction, 1) if np.isfinite(pt_vt_reduction) else None,
            'c_hedged_abs_mdd': round(pt_hedged_abs, 1),
            'd_hedged_vs_bh': round(pt_hedged_vs_bh, 1) if np.isfinite(pt_hedged_vs_bh) else None,
        },
        'def_a_retention_fraction': ci_stats(a_vals, lo_pct, hi_pct),
        'def_b_vt_mdd_reduction': ci_stats(b_vals, lo_pct, hi_pct),
        'def_c_hedged_abs_mdd': ci_stats(c_vals, lo_pct, hi_pct),
        'def_d_hedged_vs_bh': ci_stats(d_vals, lo_pct, hi_pct),
    }


# ====================================================
# Asset analysis with stationary bootstrap
# ====================================================
def analyze_asset_stationary(asset_name, asset_ret, shy_ret, vix_weights,
                              mean_blocks, n_reps, bh_ret=None):
    log.info(f"\n{'='*60}")
    log.info(f"Analyzing: {asset_name}")
    log.info(f"{'='*60}")

    if bh_ret is None:
        bh_ret = base.build_bh(asset_ret)
    vt_ret = base.build_vt_monthly(asset_ret, vix_weights, shy_ret)
    hedged_ret = base.compute_hedged_vt(vt_ret, bh_ret, base.TSMOM_LOOKBACK)

    common = bh_ret.dropna().index.intersection(
        vt_ret.dropna().index).intersection(
        hedged_ret.dropna().index)
    common = common[common >= base.ANALYSIS_START]
    bh = bh_ret.loc[common]
    vt = vt_ret.loc[common]
    hedged = hedged_ret.loc[common]

    log.info(f"  Aligned: {common[0].date()} to {common[-1].date()}, n={len(common)}")
    log.info(f"  BH MDD={base.compute_mdd(bh)*100:.1f}%  "
             f"VT MDD={base.compute_mdd(vt)*100:.1f}%  "
             f"Hedged MDD={base.compute_mdd(hedged)*100:.1f}%")

    out = {'asset': asset_name, 'n_obs': len(common), 'by_mean_block': {}}
    for mb in mean_blocks:
        log.info(f"\n  -- stationary bootstrap mean_block={mb} ({mb/252:.1f}y) --")
        out['by_mean_block'][str(mb)] = stationary_bootstrap_4defs(
            bh, vt, hedged, n_reps=n_reps, mean_block=mb)
    return out


# ====================================================
# Main
# ====================================================
def main(n_reps=BOOTSTRAP_REPS_DEFAULT, mean_blocks=None,
         out_path=None):
    if mean_blocks is None:
        mean_blocks = MEAN_BLOCK_LENGTHS

    log.info("=" * 70)
    log.info("K1417: Paper 3 H2 — Stationary bootstrap MDD CI")
    log.info("=" * 70)
    log.info(f"Mean blocks (trading days): {mean_blocks}")
    log.info(f"Reps per spec: {n_reps}, seed={SEED}, CI={CI_PCT}%")

    close = base.download_data()
    ret_df = base.compute_daily_returns(close)
    vix = close['VIX']
    shy_ret = ret_df['SHY']
    vix_weights = base.get_monthly_vt_weights(close, vix)

    results = {}
    results['SPY'] = analyze_asset_stationary(
        'SPY', ret_df['SPY'], shy_ret, vix_weights, mean_blocks, n_reps)
    blend = 0.5 * ret_df['SPY'] + 0.5 * ret_df['GLD']
    results['50/50'] = analyze_asset_stationary(
        '50/50', blend, shy_ret, vix_weights, mean_blocks, n_reps, bh_ret=blend)
    for asset in ['DIA', 'QQQ', 'IWM']:
        results[asset] = analyze_asset_stationary(
            asset, ret_df[asset], shy_ret, vix_weights, mean_blocks, n_reps)

    # ====================================================
    # K1192 vs K1417 retention CI comparison
    # ====================================================
    log.info("\n" + "=" * 80)
    log.info("Retention (def a) 90% CI: K1192 fixed-block 252  vs  K1417 stationary")
    log.info("=" * 80)
    k1192_ref = {
        'SPY':   {'lo': 86, 'hi': 97},
        '50/50': {'lo': 90, 'hi': 99},
        'DIA':   {'lo': 83, 'hi': 96},
        'QQQ':   {'lo': 82, 'hi': 95},
        'IWM':   {'lo': 91, 'hi': 100},
    }
    comparison_rows = []
    for asset in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        row = {
            'asset': asset,
            'k1192_fixed_252': [k1192_ref[asset]['lo'], k1192_ref[asset]['hi']],
        }
        for mb in mean_blocks:
            ci = results[asset]['by_mean_block'][str(mb)]['def_a_retention_fraction']
            row[f'k1417_stationary_{mb}'] = [ci['lo'], ci['hi']]
            row[f'lo_shift_{mb}'] = (round(ci['lo'] - k1192_ref[asset]['lo'], 1)
                                      if np.isfinite(ci['lo']) else None)
        comparison_rows.append(row)
        log.info(f"  {asset}: K1192=[{k1192_ref[asset]['lo']},{k1192_ref[asset]['hi']}]  "
                 + "  ".join(
                     f"sb({mb})=[{results[asset]['by_mean_block'][str(mb)]['def_a_retention_fraction']['lo']},"
                     f"{results[asset]['by_mean_block'][str(mb)]['def_a_retention_fraction']['hi']}]"
                     for mb in mean_blocks))

    # Magnitude check: does CI shift materially? (>=3pp lower bound shift)
    lo_shifts = [row[f'lo_shift_{mean_blocks[-1]}']
                 for row in comparison_rows
                 if row.get(f'lo_shift_{mean_blocks[-1]}') is not None]
    if lo_shifts:
        mean_lo_shift = float(np.mean(lo_shifts))
        median_lo_shift = float(np.median(lo_shifts))
        material_shift = sum(1 for s in lo_shifts if s <= -3)
    else:
        mean_lo_shift = median_lo_shift = float('nan')
        material_shift = 0
    verdict = ('H2 SUPPORTED — long-block stationary bootstrap meaningfully lowers '
               'retention CI lo bound'
               if material_shift >= 3 else
               'H2 NOT SUPPORTED — CI shift below 3pp on majority of assets; '
               'retention robust to bootstrap block length')

    summary = {
        'comparison_rows': comparison_rows,
        f'mean_lo_shift_at_{mean_blocks[-1]}': round(mean_lo_shift, 2),
        f'median_lo_shift_at_{mean_blocks[-1]}': round(median_lo_shift, 2),
        f'n_assets_with_material_shift_at_{mean_blocks[-1]}': material_shift,
        'verdict': verdict,
    }
    log.info("")
    log.info(f"Mean lo-shift at mean_block={mean_blocks[-1]}: {mean_lo_shift:.2f}pp")
    log.info(f"Median lo-shift at mean_block={mean_blocks[-1]}: {median_lo_shift:.2f}pp")
    log.info(f"Assets with material (<= -3pp) shift: {material_shift}/5")
    log.info(f"Verdict: {verdict}")

    output = {
        'experiment_id': 'K1417',
        'title': 'Paper 3 H2 — Stationary bootstrap MDD CI',
        'description': (
            'Stationary bootstrap (Politis & Romano 1994) variant of K1192. '
            'Mean block lengths 756 (3y) and 1260 (5y) trading days. '
            'Tests Gemini v4 H2: fixed 252-day blocks bias retention CI upward '
            'by destroying multi-year drawdown autocorrelation.'
        ),
        'data_source': 'yfinance',
        'period': f'{base.ANALYSIS_START} to {base.END_DATE}',
        'methodology': {
            'vt_rule': 'w = min(12/VIX_month_end, 1), monthly rebalancing, lag 1 month',
            'cash_proxy': 'SHY',
            'tsmom_lookback': base.TSMOM_LOOKBACK,
            'bootstrap': (f'Stationary (Politis & Romano 1994), '
                          f'mean_blocks={mean_blocks} trading days, '
                          f'B={n_reps}, seed={SEED}'),
            'ci': f'{CI_PCT}%',
        },
        'reference_k1192_fixed_block_ci': k1192_ref,
        'assets': results,
        'summary': summary,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'paper_link': 'paper/vt-trend-following/review_history/v4/README.md (H2)',
    }

    if out_path is None:
        out_path = os.path.join(REPO_ROOT, 'experiments', 'k1417', 'k1417_results.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"\nResults saved to {out_path}")
    return output


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--n-reps', type=int, default=BOOTSTRAP_REPS_DEFAULT)
    parser.add_argument('--mean-blocks', type=int, nargs='+',
                        default=MEAN_BLOCK_LENGTHS)
    parser.add_argument('--out', type=str, default=None)
    args = parser.parse_args()
    main(n_reps=args.n_reps, mean_blocks=args.mean_blocks, out_path=args.out)
