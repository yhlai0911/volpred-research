#!/usr/bin/env python3
"""
K1192: Paper 3 Table 6 Bootstrap MDD CI — Formal Reproduce Experiment

Objective: Reproduce Paper 3 body_v2.tex Table 6 (tab:mdd_bootstrap) with the
correct formula and monthly rebalancing, testing 4 CI definitions to identify
which matches paper [86, 97] for SPY.

Paper Table 6 formula (Eq. mdd_retention_boot):
  MDD Retention_b = (MDD_BH,b - MDD_HedgedVT,b) / (MDD_BH,b - MDD_VT,b)

This is the fraction of BH-to-VT drawdown improvement that SURVIVES TSMOM hedging.

Key divergence from K898:
  - K898 uses daily VIX signal (daily rebalancing)
  - Paper uses monthly VIX signal (monthly rebalancing, VIX at month-end -> next month weight)
  - K898 also clips retention to [-1, 3], yielding point estimates >100%
  - Paper gets point estimates 90-97% (consistent with monthly rebalancing)

4 CI Definitions tested:
  (a) retention_fraction CI: (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100
      [Paper Table 6 formula; 90% CI = 5th/95th percentile]
  (b) reduction_pct CI: (MDD_VT - MDD_BH) / MDD_BH * 100 (VT MDD reduction vs BH)
      [Alternative: how much does VT improve MDD?]
  (c) absolute_hedged_mdd CI: MDD_Hedged * 100 (absolute MDD of hedged VT)
  (d) relative_improvement CI: (MDD_BH - MDD_Hedged) / abs(MDD_BH) * 100
      [How much does hedged VT protect vs BH?]

Data: yfinance, SPY GLD DIA QQQ IWM VIX SHY
Period: 2005-01-03 to 2026-03-31 (paper period)
VT: monthly rebalancing, w_t = min(12/VIX_month_end, 1), lag 1 month
    [matches paper: "VIX at end of month t determines allocation for month t+1"]
TSMOM hedge: rolling 252-day regression, beta constrained [0, 0.5]
Bootstrap: block bootstrap B=10000, block=252, seed=42
CI: 90% (5th/95th percentile)

References:
  - Politis & Romano (1992) - Block bootstrap
  - Paper body_v2.tex Section 3.2 / Eq. mdd_retention_boot / Table 6
  - K898: k898_paper3_table3_supplement.py (daily rebalancing version)
"""

import json
import logging
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')

# ====================================================
# Configuration
# ====================================================
START_DATE = '2004-06-01'     # Extra lead for GLD/SHY + TSMOM lookback
END_DATE = '2026-04-01'
ANALYSIS_START = '2005-01-03'
VT_NUMERATOR = 12.0
TSMOM_LOOKBACK = 252
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_BLOCK = 252
ANNUALIZE = 252
SEED = 42

# Paper's reference values (Table 6 body_v2.tex)
PAPER_TABLE6 = {
    'SPY':   {'point': 93, 'ci_lower': 86, 'ci_upper': 97},
    '50/50': {'point': 96, 'ci_lower': 90, 'ci_upper': 99},
    'DIA':   {'point': 91, 'ci_lower': 83, 'ci_upper': 96},
    'QQQ':   {'point': 90, 'ci_lower': 82, 'ci_upper': 95},
    'IWM':   {'point': 97, 'ci_lower': 91, 'ci_upper': 100},
}

# ====================================================
# Logging
# ====================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aff924a6/experiments/k1192/run.log', mode='w'),
    ]
)
log = logging.getLogger(__name__)


# ====================================================
# Data Download
# ====================================================
def download_data():
    tickers = ['SPY', 'GLD', 'DIA', 'QQQ', 'IWM', '^VIX', 'SHY']
    log.info(f"Downloading {tickers} from {START_DATE} to {END_DATE}")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw['Close']
    else:
        close = raw
    close = close.rename(columns={'^VIX': 'VIX'})
    close = close.ffill()
    log.info(f"Data range: {close.index[0].date()} to {close.index[-1].date()}, shape={close.shape}")
    return close


def compute_daily_returns(close):
    ret = close.pct_change()
    return ret.dropna(how='all')


# ====================================================
# Monthly Rebalancing VT (Paper Spec)
# ====================================================
def get_monthly_vt_weights(close_df, vix_series):
    """
    Monthly rebalancing: weight for month m+1 = min(12/VIX_month_end_m, 1).
    VIX at end of month t -> weight holds constant during month t+1.
    Returns daily weight series (same weight for all days in a calendar month).
    """
    # Month-end VIX
    vix_monthly = vix_series.resample('ME').last()
    vix_monthly_weight = (VT_NUMERATOR / vix_monthly).clip(upper=1.0)
    # Shift by 1 month to avoid look-ahead
    vix_monthly_weight = vix_monthly_weight.shift(1)

    # Forward-fill to daily (constant within month)
    daily_idx = close_df.index
    # reindex to daily, forward-fill
    w_daily = vix_monthly_weight.reindex(daily_idx, method='ffill')
    return w_daily


# ====================================================
# Strategy Construction
# ====================================================
def build_bh(asset_ret):
    return asset_ret.copy()


def build_vt_monthly(asset_ret, vix_weights, shy_ret):
    """Monthly-rebalanced VT with SHY as cash proxy."""
    common = asset_ret.dropna().index.intersection(
        shy_ret.dropna().index).intersection(
        vix_weights.dropna().index)
    common = common[common >= ANALYSIS_START]
    r = asset_ret.loc[common]
    r_shy = shy_ret.loc[common]
    w = vix_weights.loc[common]
    vt = w * r + (1 - w) * r_shy
    return vt


def compute_tsmom_factor(returns, lookback=TSMOM_LOOKBACK):
    """
    TSMOM factor: sign(cum_ret_{t-252:t-1}) * r_t
    Lagged by construction (shift(1) on cumulative return sign).
    """
    log_ret = np.log1p(returns)
    cum_log_ret = log_ret.rolling(lookback).sum().shift(1)
    signal = np.sign(cum_log_ret)
    return (signal * returns).dropna()


def compute_hedged_vt(vt_returns, asset_returns, lookback=TSMOM_LOOKBACK):
    """
    TSMOM-Hedged VT: remove TSMOM exposure via rolling 252-day regression.
    PureVT_t = VT_t - beta_TSMOM,t * TSMOM_t
    beta constrained to [0, 0.5], lagged 1 day.
    """
    tsmom = compute_tsmom_factor(asset_returns, lookback)
    common = vt_returns.dropna().index.intersection(tsmom.dropna().index)
    vt = vt_returns.loc[common]
    tsm = tsmom.loc[common]

    rolling_cov = vt.rolling(lookback).cov(tsm)
    rolling_var = tsm.rolling(lookback).var()
    b = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
    b = b.shift(1).fillna(0).clip(0, 0.5)
    hedged = (vt - b * tsm).dropna()
    return hedged


def compute_mdd(rets):
    """Max drawdown from return series (returns negative number)."""
    r = np.asarray(rets)
    w = np.cumprod(1 + r)
    peak = np.maximum.accumulate(w)
    dd = w / peak - 1
    return float(np.min(dd))


def compute_sharpe(returns):
    r = np.asarray(returns)
    if r.std() == 0 or len(r) < 10:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ANNUALIZE))


# ====================================================
# 4-Definition Bootstrap
# ====================================================
def block_bootstrap_4defs(bh_rets, vt_rets, hedged_rets, n_reps=BOOTSTRAP_REPS,
                           block_size=BOOTSTRAP_BLOCK, seed=SEED, ci_pct=90):
    """
    Block bootstrap for 4 MDD CI definitions.

    (a) retention_fraction: (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100
        [Paper Table 6 / Eq. mdd_retention_boot]
    (b) vt_mdd_reduction: (MDD_VT - MDD_BH) / abs(MDD_BH) * 100
        [VT MDD improvement vs BH as % of BH MDD, positive = improvement]
    (c) hedged_mdd_absolute: MDD_Hedged * 100
        [Raw MDD of Hedged VT strategy]
    (d) hedged_vs_bh_pct: (MDD_BH - MDD_Hedged) / abs(MDD_BH) * 100
        [How much does hedged VT improve vs BH?]

    CI: percentile bootstrap at (alpha/2)th and (1-alpha/2)th percentiles
    where alpha = 1 - ci_pct/100
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
    lo_pct = alpha / 2 * 100          # e.g., 5.0 for 90% CI
    hi_pct = (1 - alpha / 2) * 100   # e.g., 95.0 for 90% CI

    def _mdd(r):
        w = np.cumprod(1 + r)
        pk = np.maximum.accumulate(w)
        return float(np.min(w / pk - 1))

    def _mdd_vectorized(r_mat):
        """r_mat: (n_reps, T) array -> MDD for each row"""
        w = np.cumprod(1 + r_mat, axis=1)
        pk = np.maximum.accumulate(w, axis=1)
        dd = w / pk - 1
        return dd.min(axis=1)

    # Point estimates
    bh_mdd_pt = _mdd(bh)
    vt_mdd_pt = _mdd(vt)
    hedged_mdd_pt = _mdd(hedged)

    pt_retention = ((bh_mdd_pt - hedged_mdd_pt) / (bh_mdd_pt - vt_mdd_pt) * 100
                    if abs(bh_mdd_pt - vt_mdd_pt) > 1e-8 else np.nan)
    pt_vt_reduction = (vt_mdd_pt - bh_mdd_pt) / abs(bh_mdd_pt) * 100 if bh_mdd_pt != 0 else np.nan
    pt_hedged_abs = hedged_mdd_pt * 100
    pt_hedged_vs_bh = (bh_mdd_pt - hedged_mdd_pt) / abs(bh_mdd_pt) * 100 if bh_mdd_pt != 0 else np.nan

    log.info(f"  Point estimates: retention={pt_retention:.1f}%, vt_red={pt_vt_reduction:.1f}%, "
             f"hedged_abs={pt_hedged_abs:.1f}%, hedged_vs_bh={pt_hedged_vs_bh:.1f}%")

    # Bootstrap
    n_blocks = max(1, n // block_size)

    a_vals, b_vals, c_vals, d_vals = [], [], [], []

    log.info(f"  Running {n_reps} bootstrap replications (block={block_size}, n={n})")
    for _ in range(n_reps):
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]

        bh_b = bh[idx]
        vt_b = vt[idx]
        h_b = hedged[idx]

        bh_mdd = _mdd(bh_b)
        vt_mdd = _mdd(vt_b)
        h_mdd = _mdd(h_b)

        denom = bh_mdd - vt_mdd
        if abs(denom) > 1e-8:
            ret = (bh_mdd - h_mdd) / denom * 100
            a_vals.append(ret)
        if bh_mdd != 0:
            b_vals.append((vt_mdd - bh_mdd) / abs(bh_mdd) * 100)
            d_vals.append((bh_mdd - h_mdd) / abs(bh_mdd) * 100)
        c_vals.append(h_mdd * 100)

    a_arr = np.array(a_vals)
    b_arr = np.array(b_vals)
    c_arr = np.array(c_vals)
    d_arr = np.array(d_vals)

    def ci_stats(arr, lo_p, hi_p):
        arr_clean = arr[np.isfinite(arr)]
        if len(arr_clean) < 100:
            return {'lo': np.nan, 'hi': np.nan, 'mean': np.nan, 'median': np.nan, 'n': len(arr_clean)}
        return {
            'lo': round(float(np.percentile(arr_clean, lo_p)), 1),
            'hi': round(float(np.percentile(arr_clean, hi_p)), 1),
            'mean': round(float(np.mean(arr_clean)), 1),
            'median': round(float(np.median(arr_clean)), 1),
            'n': len(arr_clean),
        }

    result = {
        'n_obs': n,
        'n_reps': n_reps,
        'block_size': block_size,
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
        'def_a_retention_fraction': ci_stats(a_arr, lo_pct, hi_pct),
        'def_b_vt_mdd_reduction': ci_stats(b_arr, lo_pct, hi_pct),
        'def_c_hedged_abs_mdd': ci_stats(c_arr, lo_pct, hi_pct),
        'def_d_hedged_vs_bh': ci_stats(d_arr, lo_pct, hi_pct),
    }
    return result


# ====================================================
# Asset Analysis
# ====================================================
def analyze_asset(asset_name, asset_ret, shy_ret, vix_weights, close_df=None,
                  bh_ret=None):
    """Full analysis for a single asset."""
    log.info(f"\n{'='*60}")
    log.info(f"Analyzing: {asset_name}")
    log.info(f"{'='*60}")

    if bh_ret is None:
        bh_ret = build_bh(asset_ret)

    vt_ret = build_vt_monthly(asset_ret, vix_weights, shy_ret)

    hedged_ret = compute_hedged_vt(vt_ret, bh_ret, TSMOM_LOOKBACK)

    # Align
    common = bh_ret.dropna().index.intersection(
        vt_ret.dropna().index).intersection(
        hedged_ret.dropna().index)
    common = common[common >= ANALYSIS_START]

    bh = bh_ret.loc[common]
    vt = vt_ret.loc[common]
    hedged = hedged_ret.loc[common]

    log.info(f"  Aligned period: {common[0].date()} to {common[-1].date()}, n={len(common)}")
    log.info(f"  BH MDD: {compute_mdd(bh)*100:.1f}%")
    log.info(f"  VT MDD: {compute_mdd(vt)*100:.1f}%")
    log.info(f"  Hedged MDD: {compute_mdd(hedged)*100:.1f}%")
    log.info(f"  BH Sharpe: {compute_sharpe(bh):.3f}")
    log.info(f"  VT Sharpe: {compute_sharpe(vt):.3f}")
    log.info(f"  Hedged Sharpe: {compute_sharpe(hedged):.3f}")

    boot = block_bootstrap_4defs(bh, vt, hedged)

    # Match check vs paper
    paper_ref = PAPER_TABLE6.get(asset_name.replace(' SPY/GLD', '').strip())
    match_info = {}
    if paper_ref:
        for def_key, def_label in [
            ('def_a_retention_fraction', 'a_retention'),
            ('def_b_vt_mdd_reduction', 'b_vt_reduction'),
            ('def_c_hedged_abs_mdd', 'c_hedged_abs'),
            ('def_d_hedged_vs_bh', 'd_hedged_vs_bh'),
        ]:
            ci = boot[def_key]
            lo_match = abs(ci['lo'] - paper_ref['ci_lower']) <= 5.0 if np.isfinite(ci['lo']) else False
            hi_match = abs(ci['hi'] - paper_ref['ci_upper']) <= 5.0 if np.isfinite(ci['hi']) else False
            match_info[def_label] = {
                'paper_ci': [paper_ref['ci_lower'], paper_ref['ci_upper']],
                'computed_ci': [ci['lo'], ci['hi']],
                'lo_diff': round(ci['lo'] - paper_ref['ci_lower'], 1) if np.isfinite(ci['lo']) else None,
                'hi_diff': round(ci['hi'] - paper_ref['ci_upper'], 1) if np.isfinite(ci['hi']) else None,
                'lo_match_5pp': lo_match,
                'hi_match_5pp': hi_match,
                'both_match': lo_match and hi_match,
            }

        log.info(f"  Paper reference: point={paper_ref['point']}, CI=[{paper_ref['ci_lower']}, {paper_ref['ci_upper']}]")
        for k, v in match_info.items():
            log.info(f"  Def {k}: computed=[{v['computed_ci'][0]}, {v['computed_ci'][1]}], "
                     f"diff=[{v['lo_diff']}, {v['hi_diff']}], match={v['both_match']}")

    return {
        'asset': asset_name,
        'n_obs': boot['n_obs'],
        'bootstrap_results': boot,
        'paper_match': match_info,
    }


# ====================================================
# Main
# ====================================================
def main():
    log.info("=" * 70)
    log.info("K1192: Paper 3 Table 6 Bootstrap MDD CI — Formal Reproduce")
    log.info("=" * 70)
    log.info(f"Period: {ANALYSIS_START} to {END_DATE}")
    log.info(f"VT: monthly rebalancing, w=min(12/VIX_month_end, 1), lag 1 month")
    log.info(f"Bootstrap: B={BOOTSTRAP_REPS}, block={BOOTSTRAP_BLOCK}, seed={SEED}")
    log.info(f"CI: 90% (5th/95th percentile)")
    log.info("")
    log.info("Paper Table 6 target (body_v2.tex):")
    for asset, v in PAPER_TABLE6.items():
        log.info(f"  {asset}: point={v['point']}, CI=[{v['ci_lower']}, {v['ci_upper']}]")

    # Download
    close = download_data()
    ret_df = compute_daily_returns(close)
    vix = close['VIX']
    shy_ret = ret_df['SHY']

    # Monthly VT weights
    vix_weights = get_monthly_vt_weights(close, vix)
    log.info(f"\nMonthly VT weights: first 5 distinct = "
             f"{vix_weights.dropna().unique()[:5].round(3).tolist()}")

    all_results = {}

    # SPY
    all_results['SPY'] = analyze_asset(
        'SPY', ret_df['SPY'], shy_ret, vix_weights)

    # 50/50 SPY/GLD
    blend = 0.5 * ret_df['SPY'] + 0.5 * ret_df['GLD']
    all_results['50/50'] = analyze_asset(
        '50/50', blend, shy_ret, vix_weights, bh_ret=blend)

    # DIA, QQQ, IWM
    for asset in ['DIA', 'QQQ', 'IWM']:
        all_results[asset] = analyze_asset(
            asset, ret_df[asset], shy_ret, vix_weights)

    # ====================================================
    # Summary
    # ====================================================
    log.info("\n" + "=" * 80)
    log.info("SUMMARY: 4-Definition CI vs Paper Table 6")
    log.info("=" * 80)

    summary_rows = []
    for asset_key in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        r = all_results[asset_key]
        boot = r['bootstrap_results']
        paper = PAPER_TABLE6.get(asset_key, {})
        row = {
            'asset': asset_key,
            'paper_ci': [paper.get('ci_lower'), paper.get('ci_upper')],
            'def_a': [boot['def_a_retention_fraction']['lo'], boot['def_a_retention_fraction']['hi']],
            'def_b': [boot['def_b_vt_mdd_reduction']['lo'], boot['def_b_vt_mdd_reduction']['hi']],
            'def_c': [boot['def_c_hedged_abs_mdd']['lo'], boot['def_c_hedged_abs_mdd']['hi']],
            'def_d': [boot['def_d_hedged_vs_bh']['lo'], boot['def_d_hedged_vs_bh']['hi']],
        }
        summary_rows.append(row)
        log.info(f"\n{asset_key}:")
        log.info(f"  Paper: [{paper.get('ci_lower')}, {paper.get('ci_upper')}]")
        log.info(f"  (a) Retention fraction: [{boot['def_a_retention_fraction']['lo']}, {boot['def_a_retention_fraction']['hi']}]")
        log.info(f"  (b) VT MDD reduction:   [{boot['def_b_vt_mdd_reduction']['lo']}, {boot['def_b_vt_mdd_reduction']['hi']}]")
        log.info(f"  (c) Hedged abs MDD:     [{boot['def_c_hedged_abs_mdd']['lo']}, {boot['def_c_hedged_abs_mdd']['hi']}]")
        log.info(f"  (d) Hedged vs BH:       [{boot['def_d_hedged_vs_bh']['lo']}, {boot['def_d_hedged_vs_bh']['hi']}]")

    # Determine best-match definition
    match_counts = {'a': 0, 'b': 0, 'c': 0, 'd': 0}
    for asset_key in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        matches = all_results[asset_key]['paper_match']
        for k, label in [('a_retention', 'a'), ('b_vt_reduction', 'b'),
                          ('c_hedged_abs', 'c'), ('d_hedged_vs_bh', 'd')]:
            if matches.get(k, {}).get('both_match', False):
                match_counts[label] += 1

    best_def = max(match_counts, key=lambda k: match_counts[k])
    log.info(f"\nMatch counts (both lo+hi within 5pp): {match_counts}")
    log.info(f"Best matching definition: ({best_def}) with {match_counts[best_def]}/5 assets")

    # ====================================================
    # Save Results
    # ====================================================
    output = {
        'experiment_id': 'K1192',
        'title': 'Paper 3 Table 6 Bootstrap MDD CI — Formal Reproduce',
        'description': (
            'Block bootstrap (B=10000, block=252, seed=42) for MDD retention '
            'CI testing 4 definitions against paper Table 6 [86,97] for SPY. '
            'Uses monthly rebalancing (paper spec) vs K898 daily rebalancing.'
        ),
        'data_source': 'yfinance',
        'period': f'{ANALYSIS_START} to {END_DATE}',
        'methodology': {
            'vt_rule': 'w = min(12/VIX_month_end, 1), monthly rebalancing, lag 1 month',
            'cash_proxy': 'SHY (short-term treasury)',
            'tsmom_lookback': TSMOM_LOOKBACK,
            'bootstrap': f'{BOOTSTRAP_REPS} reps, block={BOOTSTRAP_BLOCK} days',
            'ci': '90% (5th/95th percentile)',
            'seed': SEED,
        },
        'paper_table6_reference': PAPER_TABLE6,
        'key_difference_from_k898': (
            'K898 uses daily VIX signal (daily rebalancing). '
            'Paper uses monthly end-of-month VIX (monthly rebalancing). '
            'Monthly rebalancing yields lower VT/Hedged MDD differences '
            'because fewer signals means smoother weight transitions. '
            'K898 point estimates >100% (hedged better than VT); '
            'paper point estimates 90-97% (expected from monthly VT).'
        ),
        'assets': {},
        'summary': {
            'rows': summary_rows,
            'match_counts': match_counts,
            'best_matching_definition': best_def,
            'best_matching_count': match_counts[best_def],
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }

    for asset_key in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        output['assets'][asset_key] = all_results[asset_key]

    out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aff924a6/experiments/k1192/k1192_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"\nResults saved to {out_path}")

    return output


if __name__ == '__main__':
    results = main()
