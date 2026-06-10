#!/usr/bin/env python3
"""
K1458: Paper 6 v5 review H1 — Trough-window daily-return decomposition.

Gemini v4 review (paper/vt-trend-following/review_history/v5/README.md) H1:

    Decompose daily PureVT returns around MDD troughs (2009-03, 2020-03).
    Show whether the MDD improvement in PureVT comes from actual VIX timing
    or simply from profiting off the short-TSMOM hedge during market rebounds.

Body v3 only adds verbal caveat citing Daniel & Moskowitz (2016) — no
quantitative decomposition. This experiment closes that gap by computing,
for each of the 5 canonical assets (SPY / 50-50 / DIA / QQQ / IWM):

  1. Identify Buy-and-Hold drawdown trough date inside 2008-2010 and
     2019-2021 calendar windows.
  2. Build ±63 trading-day window around each trough.
  3. Within window, decompose PureVT_t = VT_t + (-beta_t * TSMOM_t):
       - VIX-timing contribution: VT_t - BH_t
       - TSMOM-hedge contribution: -beta_t * TSMOM_t
  4. Partition trading days inside window by sign(TSMOM_t):
       - "TSMOM<0" days: market rebounding while past-12m trend negative,
         short-TSMOM mechanically positive.
       - "TSMOM>=0" days: other.
  5. Sum cumulative contribution of each component on each sign-partition.

Output JSON tabulates per (asset × trough × component × sign-partition) the
cumulative log-return contribution and the day count. This lets the paper
quantify whether PureVT MDD retention in trough windows is driven by VIX
timing (VT - BH) or by mechanical short-TSMOM in rebound days.

Strategy construction reuses K1192 helpers verbatim — only the post-hoc
decomposition is new.
"""

import json
import logging
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

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

LOG_PATH = os.path.join(REPO_ROOT, 'experiments',
                       'k1458_h1_trough_decomposition', 'run.log')
RESULTS_PATH = os.path.join(REPO_ROOT, 'experiments',
                            'k1458_h1_trough_decomposition',
                            'k1458_results.json')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, mode='w'),
    ],
)
log = logging.getLogger('k1458')
base.log.setLevel(logging.WARNING)

# Trough-search calendar windows (per Gemini v4 H1 spec)
TROUGH_WINDOWS = [
    ('2009-03', '2008-06-01', '2010-06-30'),
    ('2020-03', '2019-06-01', '2021-06-30'),
]
TROUGH_HALF_WINDOW_DAYS = 63   # ±63 trading days


def _decompose_around_trough(asset_key, bh_ret, vt_ret, pure_vt_ret,
                             tsmom_factor, beta_series, trough_label,
                             search_start, search_end):
    """Build ±63d decomposition table around BH MDD trough inside window."""
    # 1. Align series on intersection
    idx = (bh_ret.dropna().index
           .intersection(vt_ret.dropna().index)
           .intersection(pure_vt_ret.dropna().index)
           .intersection(tsmom_factor.dropna().index)
           .intersection(beta_series.dropna().index))
    idx = pd.DatetimeIndex(idx).sort_values()
    bh = bh_ret.reindex(idx)
    vt = vt_ret.reindex(idx)
    pure = pure_vt_ret.reindex(idx)
    tsm = tsmom_factor.reindex(idx)
    beta = beta_series.reindex(idx)

    sub = idx[(idx >= search_start) & (idx <= search_end)]
    if len(sub) == 0:
        return None

    # 2. BH cumulative drawdown inside search window → identify trough date
    bh_cum = (1.0 + bh.loc[sub]).cumprod()
    bh_peak = bh_cum.cummax()
    drawdown = (bh_cum / bh_peak) - 1.0
    trough_date = drawdown.idxmin()
    trough_dd = float(drawdown.loc[trough_date])

    # 3. ±63 trading-day window centred on trough
    pos = idx.get_loc(trough_date)
    lo = max(0, pos - TROUGH_HALF_WINDOW_DAYS)
    hi = min(len(idx) - 1, pos + TROUGH_HALF_WINDOW_DAYS)
    win_idx = idx[lo:hi + 1]

    bh_w = bh.loc[win_idx]
    vt_w = vt.loc[win_idx]
    pure_w = pure.loc[win_idx]
    tsm_w = tsm.loc[win_idx]
    beta_w = beta.loc[win_idx]
    # Daily decomposition contributions (additive in arithmetic return space)
    vix_timing_w = vt_w - bh_w            # VIX-timing vs BH
    tsmom_hedge_w = -beta_w * tsm_w       # TSMOM-hedge contribution to PureVT

    # 4. Partition by sign(TSMOM_t)
    mask_neg = tsm_w < 0
    mask_pos = ~mask_neg

    def _agg(daily, mask):
        sel = daily.loc[mask]
        return {
            'days': int(mask.sum()),
            'sum_arith_return': float(sel.sum()),
            'mean_arith_return': float(sel.mean()) if mask.sum() > 0 else None,
            'cumulative_log_return': float(np.log1p(sel.dropna()).sum())
            if mask.sum() > 0 else 0.0,
        }

    decomposition = {
        'asset': asset_key,
        'trough_label': trough_label,
        'trough_date': str(trough_date.date()),
        'trough_dd_in_window': trough_dd,
        'window_start': str(win_idx[0].date()),
        'window_end': str(win_idx[-1].date()),
        'window_trading_days': int(len(win_idx)),
        'days_tsmom_negative': int(mask_neg.sum()),
        'days_tsmom_nonneg': int(mask_pos.sum()),
        # Cumulative full-window log returns for each series
        'full_window_cumret': {
            'bh':       float(np.log1p(bh_w.dropna()).sum()),
            'vt':       float(np.log1p(vt_w.dropna()).sum()),
            'pure_vt':  float(np.log1p(pure_w.dropna()).sum()),
            'vix_timing_arith_sum': float(vix_timing_w.sum()),
            'tsmom_hedge_arith_sum': float(tsmom_hedge_w.sum()),
        },
        # Split by sign(TSMOM_t)
        'tsmom_neg_partition': {
            'vix_timing': _agg(vix_timing_w, mask_neg),
            'tsmom_hedge': _agg(tsmom_hedge_w, mask_neg),
            'vt_excess_bh': _agg(vt_w - bh_w, mask_neg),
            'pure_vt_excess_bh': _agg(pure_w - bh_w, mask_neg),
        },
        'tsmom_nonneg_partition': {
            'vix_timing': _agg(vix_timing_w, mask_pos),
            'tsmom_hedge': _agg(tsmom_hedge_w, mask_pos),
            'vt_excess_bh': _agg(vt_w - bh_w, mask_pos),
            'pure_vt_excess_bh': _agg(pure_w - bh_w, mask_pos),
        },
    }

    # 5. Headline raw contributions (no unbounded ratio).
    #    Codex 2026-06-10 FAIL: previously reported share = num/den, but den
    #    (pure_vt_excess) can be near-zero or opposite-signed against num,
    #    producing unbounded/反號 ratios (SPY 2020 share=9.18; 50/50=-6.93).
    #    Fix: report raw arithmetic contributions only; compute share ONLY
    #    when num and den both positive (same sign) — else None.
    pure_excess_total = float((pure_w - bh_w).sum())
    tsmom_neg_hedge = decomposition['tsmom_neg_partition']['tsmom_hedge']['sum_arith_return']
    vix_timing_full = float((vt_w - bh_w).sum())
    tsmom_hedge_full = float((-beta_w * tsm_w).sum())
    same_sign_positive = (pure_excess_total > 0) and (tsmom_neg_hedge > 0)
    decomposition['headline'] = {
        'pure_vt_excess_bh_total_arith': pure_excess_total,
        'vix_timing_total_arith': vix_timing_full,
        'tsmom_hedge_total_arith': tsmom_hedge_full,
        'tsmom_hedge_in_tsmom_neg_days_arith': tsmom_neg_hedge,
        'share_attributable_to_mechanical_rebound_hedge_same_sign_only':
            (tsmom_neg_hedge / pure_excess_total) if same_sign_positive else None,
        'share_valid': same_sign_positive,
    }
    return decomposition


def _build_strategies(close, ret_df, vix_weights, asset_name,
                      bh_series, shy_ret):
    """Mirror k1192 strategy construction for a single asset (no bootstrap)."""
    vt = base.build_vt_monthly(bh_series, vix_weights, shy_ret)
    # k1192 compute_hedged_vt returns PureVT_t = VT_t - beta_t * TSMOM_t
    pure_vt = base.compute_hedged_vt(vt, bh_series)
    # Recover (beta, tsmom) separately so we can decompose contributions
    tsmom = base.compute_tsmom_factor(bh_series)
    common = vt.dropna().index.intersection(tsmom.dropna().index)
    vt_c = vt.loc[common]
    tsm_c = tsmom.loc[common]
    rolling_cov = vt_c.rolling(base.TSMOM_LOOKBACK).cov(tsm_c)
    rolling_var = tsm_c.rolling(base.TSMOM_LOOKBACK).var()
    beta = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
    beta = beta.shift(1).fillna(0).clip(0, 0.5)
    return {
        'bh': bh_series,
        'vt': vt,
        'pure_vt': pure_vt,
        'tsmom': tsmom,
        'beta': beta,
    }


def main():
    log.info("=" * 70)
    log.info("K1458: Paper 6 v5 H1 — Trough-window decomposition")
    log.info("=" * 70)
    log.info(f"5 canonical assets: SPY / 50-50 (SPY+GLD) / DIA / QQQ / IWM")
    log.info(f"Trough windows: {[w[0] for w in TROUGH_WINDOWS]}")
    log.info(f"Half-window: ±{TROUGH_HALF_WINDOW_DAYS} trading days")

    close = base.download_data()
    ret_df = base.compute_daily_returns(close)
    vix = close['VIX']
    shy_ret = ret_df['SHY']
    vix_weights = base.get_monthly_vt_weights(close, vix)

    # 5 canonical assets
    asset_to_bh = {
        'SPY':    ret_df['SPY'],
        '50/50':  0.5 * ret_df['SPY'] + 0.5 * ret_df['GLD'],
        'DIA':    ret_df['DIA'],
        'QQQ':    ret_df['QQQ'],
        'IWM':    ret_df['IWM'],
    }

    results = {
        'experiment_id': 'k1458_h1_trough_decomposition',
        'task': 'paper_body_vtt_v6_fixes_round4_2026_06_10',
        'data_window': {
            'start': base.START_DATE,
            'end': base.END_DATE,
        },
        'tsmom_lookback': base.TSMOM_LOOKBACK,
        'vt_numerator': base.VT_NUMERATOR,
        'trough_half_window_days': TROUGH_HALF_WINDOW_DAYS,
        'trough_search_windows': TROUGH_WINDOWS,
        'per_asset': {},
        'generated_at_utc': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }

    for asset_key, bh_ret in asset_to_bh.items():
        log.info(f"\n--- {asset_key} ---")
        strat = _build_strategies(close, ret_df, vix_weights, asset_key,
                                  bh_ret, shy_ret)
        per_trough = []
        for label, start, end in TROUGH_WINDOWS:
            decomp = _decompose_around_trough(
                asset_key,
                strat['bh'], strat['vt'], strat['pure_vt'],
                strat['tsmom'], strat['beta'],
                label, pd.Timestamp(start), pd.Timestamp(end),
            )
            if decomp is None:
                log.warning(f"{asset_key} {label}: no data in window")
                continue
            log.info(f"  {label} trough={decomp['trough_date']} "
                     f"dd={decomp['trough_dd_in_window']:.3f} "
                     f"tsmom<0 days={decomp['days_tsmom_negative']}")
            log.info(f"    PureVT-BH(arith)={decomp['headline']['pure_vt_excess_bh_total_arith']:+.4f}"
                     f"  VIX-timing={decomp['headline']['vix_timing_total_arith']:+.4f}"
                     f"  TSMOM-hedge(full)={decomp['headline']['tsmom_hedge_total_arith']:+.4f}"
                     f"  TSMOM-hedge(neg-only)={decomp['headline']['tsmom_hedge_in_tsmom_neg_days_arith']:+.4f}"
                     f"  share_valid={decomp['headline']['share_valid']}")
            per_trough.append(decomp)
        results['per_asset'][asset_key] = per_trough

    # Cross-asset raw summary (Codex-fix: no unbounded ratio).
    # For each trough, aggregate per-asset RAW contributions; share is reported
    # only on the subset of assets where (pure_excess > 0 AND num > 0).
    summary_per_trough = {}
    for label, _, _ in TROUGH_WINDOWS:
        rows = []
        for asset_key, decs in results['per_asset'].items():
            for d in decs:
                if d['trough_label'] == label:
                    rows.append((asset_key, d['headline']))
        if not rows:
            continue
        pure_excess = [h['pure_vt_excess_bh_total_arith'] for _, h in rows]
        vix_timing = [h['vix_timing_total_arith'] for _, h in rows]
        tsmom_hedge_full = [h['tsmom_hedge_total_arith'] for _, h in rows]
        tsmom_neg_hedge = [h['tsmom_hedge_in_tsmom_neg_days_arith']
                           for _, h in rows]
        valid_shares = [h['share_attributable_to_mechanical_rebound_hedge_same_sign_only']
                        for _, h in rows
                        if h['share_valid']]
        summary_per_trough[label] = {
            'n_assets': len(rows),
            'pure_vt_excess_arith': {
                'median': float(np.median(pure_excess)),
                'min':    float(np.min(pure_excess)),
                'max':    float(np.max(pure_excess)),
            },
            'vix_timing_arith': {
                'median': float(np.median(vix_timing)),
                'min':    float(np.min(vix_timing)),
                'max':    float(np.max(vix_timing)),
            },
            'tsmom_hedge_full_arith': {
                'median': float(np.median(tsmom_hedge_full)),
                'min':    float(np.min(tsmom_hedge_full)),
                'max':    float(np.max(tsmom_hedge_full)),
            },
            'tsmom_hedge_on_tsmom_neg_days_arith': {
                'median': float(np.median(tsmom_neg_hedge)),
                'min':    float(np.min(tsmom_neg_hedge)),
                'max':    float(np.max(tsmom_neg_hedge)),
            },
            'valid_share_count': len(valid_shares),
            'valid_share_median': (float(np.median(valid_shares))
                                   if valid_shares else None),
            'valid_share_min':    (float(np.min(valid_shares))
                                   if valid_shares else None),
            'valid_share_max':    (float(np.max(valid_shares))
                                   if valid_shares else None),
            'note': ('share = TSMOM-hedge-contrib-on-tsmom<0-days / '
                     'PureVT_excess_vs_BH; reported only when both numerator '
                     'and denominator are positive (same sign). Negative or '
                     'sign-flipped denominators make the ratio unbounded — '
                     'use raw arithmetic contributions instead.'),
        }
    results['cross_asset_summary'] = summary_per_trough

    log.info("\n" + "=" * 70)
    log.info("CROSS-ASSET SUMMARY (raw arithmetic contributions, median across assets):")
    for label, s in summary_per_trough.items():
        log.info(f"  {label}: PureVT-BH={s['pure_vt_excess_arith']['median']:+.4f}  "
                 f"VIX-timing={s['vix_timing_arith']['median']:+.4f}  "
                 f"TSMOM-hedge(full)={s['tsmom_hedge_full_arith']['median']:+.4f}  "
                 f"TSMOM-hedge(neg-only)={s['tsmom_hedge_on_tsmom_neg_days_arith']['median']:+.4f}")
        if s['valid_share_count']:
            log.info(f"    valid_share (n={s['valid_share_count']}/{s['n_assets']}): "
                     f"median={s['valid_share_median']:.3f}  "
                     f"min={s['valid_share_min']:.3f}  "
                     f"max={s['valid_share_max']:.3f}")

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    log.info(f"\nResults written to: {RESULTS_PATH}")


if __name__ == '__main__':
    main()
