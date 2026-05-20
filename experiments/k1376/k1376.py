#!/usr/bin/env python3
"""
K1376: Paper 3 review_v2 B.3 Fix — MDD Retention Bootstrap CI for All 22 Assets

Objective: Extend K1192 block-bootstrap MDD retention analysis from the 5 original
US equity assets (SPY, 50/50 SPY/GLD, DIA, QQQ, IWM) to all 22 primary sample
assets from Paper 3 (vt-trend-following), addressing review_v2 HIGH issue B.3.

Paper 3 primary sample (22 assets):
  Equity (15): SPY, QQQ, IWM, XLF, XLE, DIA, EEM, EFA, FXI, EWZ, EWJ, EWG, EWU, EWA, INDA
  Commodity (3): GLD, SLV, USO
  Bond (3): TLT, LQD, HYG
  Real Estate (1): VNQ
  Composite (1): 50/50 SPY/GLD (from K1192 canonical)

Methodology (identical to K1192):
  - VT: monthly rebalancing, w_t = min(12/VIX_month_end, 1), lag 1 month
  - TSMOM hedge: rolling 252-day regression, beta constrained [0, 0.5]
  - Bootstrap: B=10000, block=252 days, seed=42
  - CI: 90% (5th/95th percentile)
  - MDD retention (def_a): (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100

Hypothesis: Commodities and bonds may show weaker MDD retention due to near-zero
leverage effect gamma (identified in Paper 3 cross-sectional analysis).

Data period: Jan 2005 to Mar 2026 (for assets with sufficient history)
Note: INDA launched 2012; SLV launched 2006 — shorter windows used.

References:
  - K1192: 5-asset canonical bootstrap (10 seconds runtime, verified 2026-04-17)
  - Paper 3 body_v3.tex Table 5 / Section 3.2 (tab:mdd_bootstrap)
  - review_v2.tex item B.3
  - Politis & Romano (1992) block bootstrap
"""

import json
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')

OUT_DIR = Path(__file__).parent

# ====================================================
# Configuration
# ====================================================
START_DATE = '2003-01-01'     # Extra lead for VIX weights + TSMOM lookback
END_DATE = '2026-04-01'
ANALYSIS_START = '2005-01-03'
VT_NUMERATOR = 12.0
TSMOM_LOOKBACK = 252
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_BLOCK = 252
ANNUALIZE = 252
SEED = 42
CI_PCT = 90

# Asset universe
ASSET_CLASSES = {
    'SPY':  'equity',
    'QQQ':  'equity',
    'IWM':  'equity',
    'XLF':  'equity',
    'XLE':  'equity',
    'DIA':  'equity',
    'EEM':  'equity',
    'EFA':  'equity',
    'FXI':  'equity',
    'EWZ':  'equity',
    'EWJ':  'equity',
    'EWG':  'equity',
    'EWU':  'equity',
    'EWA':  'equity',
    'INDA': 'equity',
    'GLD':  'commodity',
    'SLV':  'commodity',
    'USO':  'commodity',
    'TLT':  'bond',
    'LQD':  'bond',
    'HYG':  'bond',
    'VNQ':  'real_estate',
}

# 22 tickers + VIX + SHY
ALL_TICKERS = list(ASSET_CLASSES.keys()) + ['^VIX', 'SHY']

# K1192 canonical point estimates (5 equity assets) — for cross-reference
K1192_CANONICAL = {
    'SPY':   {'point': 103.7},
    '50/50': {'point': 95.6},
    'DIA':   {'point': 106.2},
    'QQQ':   {'point': 109.0},
    'IWM':   {'point': 102.2},
}

# ====================================================
# Logging
# ====================================================
log_path = OUT_DIR / 'k1376_run.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_path), mode='w'),
    ]
)
log = logging.getLogger(__name__)


# ====================================================
# Data Download
# ====================================================
def download_data():
    log.info(f"Downloading {len(ALL_TICKERS)} tickers from {START_DATE} to {END_DATE}")
    raw = yf.download(ALL_TICKERS, start=START_DATE, end=END_DATE, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw['Close']
    else:
        close = raw
    close = close.rename(columns={'^VIX': 'VIX'})
    close = close.ffill()
    log.info(f"Downloaded: {close.shape[1]} columns, {len(close)} rows "
             f"({close.index[0].date()} to {close.index[-1].date()})")
    return close


def compute_daily_returns(close):
    return close.pct_change().dropna(how='all')


# ====================================================
# Monthly VT Weights (Paper Spec — identical to K1192)
# ====================================================
def get_monthly_vt_weights(close_df, vix_series):
    """VIX at end-of-month t → weight for all days in month t+1 (lag 1 month)."""
    vix_monthly = vix_series.resample('ME').last()
    vix_monthly_weight = (VT_NUMERATOR / vix_monthly).clip(upper=1.0)
    vix_monthly_weight = vix_monthly_weight.shift(1)
    w_daily = vix_monthly_weight.reindex(close_df.index, method='ffill')
    return w_daily


# ====================================================
# Strategy Construction (identical to K1192)
# ====================================================
def build_vt_monthly(asset_ret, vix_weights, shy_ret):
    common = (asset_ret.dropna().index
              .intersection(shy_ret.dropna().index)
              .intersection(vix_weights.dropna().index))
    common = common[common >= ANALYSIS_START]
    r = asset_ret.loc[common]
    r_shy = shy_ret.loc[common]
    w = vix_weights.loc[common]
    return w * r + (1 - w) * r_shy


def compute_tsmom_factor(returns, lookback=TSMOM_LOOKBACK):
    """TSMOM signal: sign of past-lookback log return, lagged 1 day."""
    log_ret = np.log1p(returns)
    cum_log_ret = log_ret.rolling(lookback).sum().shift(1)
    signal = np.sign(cum_log_ret)
    return (signal * returns).dropna()


def compute_hedged_vt(vt_returns, asset_returns, lookback=TSMOM_LOOKBACK):
    """Remove TSMOM exposure via rolling OLS, beta clipped to [0, 0.5]."""
    tsmom = compute_tsmom_factor(asset_returns, lookback)
    common = vt_returns.dropna().index.intersection(tsmom.dropna().index)
    vt = vt_returns.loc[common]
    tsm = tsmom.loc[common]
    rolling_cov = vt.rolling(lookback).cov(tsm)
    rolling_var = tsm.rolling(lookback).var()
    b = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
    b = b.shift(1).fillna(0).clip(0, 0.5)
    return (vt - b * tsm).dropna()


def compute_mdd(rets):
    r = np.asarray(rets)
    w = np.cumprod(1 + r)
    pk = np.maximum.accumulate(w)
    return float(np.min(w / pk - 1))


def compute_sharpe(returns):
    r = np.asarray(returns)
    if r.std() == 0 or len(r) < 10:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ANNUALIZE))


# ====================================================
# Block Bootstrap (identical to K1192)
# ====================================================
def block_bootstrap(bh_rets, vt_rets, hedged_rets,
                    n_reps=BOOTSTRAP_REPS, block_size=BOOTSTRAP_BLOCK,
                    seed=SEED, ci_pct=CI_PCT):
    """Bootstrap def_a (MDD retention fraction) + def_b/c/d as supplementary."""
    rng = np.random.RandomState(seed)

    common = (bh_rets.dropna().index
              .intersection(vt_rets.dropna().index)
              .intersection(hedged_rets.dropna().index))
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

    denom_pt = bh_mdd_pt - vt_mdd_pt
    pt_retention = (bh_mdd_pt - hedged_mdd_pt) / denom_pt * 100 if abs(denom_pt) > 1e-8 else np.nan
    pt_vt_red = (vt_mdd_pt - bh_mdd_pt) / abs(bh_mdd_pt) * 100 if bh_mdd_pt != 0 else np.nan
    pt_hedged_abs = hedged_mdd_pt * 100
    pt_hedged_vs_bh = (bh_mdd_pt - hedged_mdd_pt) / abs(bh_mdd_pt) * 100 if bh_mdd_pt != 0 else np.nan

    n_blocks = max(1, n // block_size)
    a_vals, b_vals, c_vals, d_vals = [], [], [], []

    log.info(f"  Bootstrap: n={n}, reps={n_reps}, block={block_size}")
    log.info(f"  Point: retention={pt_retention:.1f}%, vt_red={pt_vt_red:.1f}%, "
             f"hedged_abs={pt_hedged_abs:.1f}%, hedged_vs_bh={pt_hedged_vs_bh:.1f}%")

    for _ in range(n_reps):
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        bh_b, vt_b, h_b = bh[idx], vt[idx], hedged[idx]
        bh_m, vt_m, h_m = _mdd(bh_b), _mdd(vt_b), _mdd(h_b)
        denom = bh_m - vt_m
        if abs(denom) > 1e-8:
            a_vals.append((bh_m - h_m) / denom * 100)
        if bh_m != 0:
            b_vals.append((vt_m - bh_m) / abs(bh_m) * 100)
            d_vals.append((bh_m - h_m) / abs(bh_m) * 100)
        c_vals.append(h_m * 100)

    def ci_stats(arr, lo_p, hi_p):
        arr_clean = np.array(arr)[np.isfinite(arr)]
        if len(arr_clean) < 100:
            return {'lo': None, 'hi': None, 'mean': None, 'median': None, 'n': len(arr_clean)}
        return {
            'lo': round(float(np.percentile(arr_clean, lo_p)), 1),
            'hi': round(float(np.percentile(arr_clean, hi_p)), 1),
            'mean': round(float(np.mean(arr_clean)), 1),
            'median': round(float(np.median(arr_clean)), 1),
            'n': len(arr_clean),
        }

    return {
        'n_obs': n,
        'n_reps': n_reps,
        'block_size': block_size,
        'ci_pct': ci_pct,
        'point_estimates': {
            'bh_mdd_pct': round(bh_mdd_pt * 100, 2),
            'vt_mdd_pct': round(vt_mdd_pt * 100, 2),
            'hedged_mdd_pct': round(hedged_mdd_pt * 100, 2),
            'a_retention': round(pt_retention, 1) if np.isfinite(pt_retention) else None,
            'b_vt_reduction': round(pt_vt_red, 1) if np.isfinite(pt_vt_red) else None,
            'c_hedged_abs_mdd': round(pt_hedged_abs, 1),
            'd_hedged_vs_bh': round(pt_hedged_vs_bh, 1) if np.isfinite(pt_hedged_vs_bh) else None,
        },
        'def_a_retention_fraction': ci_stats(a_vals, lo_pct, hi_pct),
        'def_b_vt_mdd_reduction': ci_stats(b_vals, lo_pct, hi_pct),
        'def_c_hedged_abs_mdd': ci_stats(c_vals, lo_pct, hi_pct),
        'def_d_hedged_vs_bh': ci_stats(d_vals, lo_pct, hi_pct),
    }


# ====================================================
# Per-Asset Analysis
# ====================================================
def analyze_asset(asset_name, asset_ret, shy_ret, vix_weights, bh_ret=None):
    log.info(f"\n{'='*60}")
    log.info(f"Analyzing: {asset_name} (class={ASSET_CLASSES.get(asset_name, 'composite')})")

    if bh_ret is None:
        bh_ret = asset_ret.copy()

    vt_ret = build_vt_monthly(asset_ret, vix_weights, shy_ret)
    hedged_ret = compute_hedged_vt(vt_ret, bh_ret, TSMOM_LOOKBACK)

    common = (bh_ret.dropna().index
              .intersection(vt_ret.dropna().index)
              .intersection(hedged_ret.dropna().index))
    common = common[common >= ANALYSIS_START]
    if len(common) < 252:
        log.warning(f"  {asset_name}: only {len(common)} obs after {ANALYSIS_START}, skipping")
        return None

    bh = bh_ret.loc[common]
    vt = vt_ret.loc[common]
    hedged = hedged_ret.loc[common]

    log.info(f"  Period: {common[0].date()} to {common[-1].date()}, n={len(common)}")
    log.info(f"  BH MDD={compute_mdd(bh)*100:.1f}%  VT MDD={compute_mdd(vt)*100:.1f}%  "
             f"Hedged MDD={compute_mdd(hedged)*100:.1f}%")
    log.info(f"  BH Sharpe={compute_sharpe(bh):.3f}  VT Sharpe={compute_sharpe(vt):.3f}  "
             f"Hedged Sharpe={compute_sharpe(hedged):.3f}")

    boot = block_bootstrap(bh, vt, hedged)
    ci_a = boot['def_a_retention_fraction']
    log.info(f"  → MDD retention 90% CI: [{ci_a['lo']}, {ci_a['hi']}]  "
             f"(point={boot['point_estimates']['a_retention']}%)")

    return {
        'asset': asset_name,
        'asset_class': ASSET_CLASSES.get(asset_name, 'composite'),
        'period_start': str(common[0].date()),
        'period_end': str(common[-1].date()),
        'n_obs': len(common),
        'bootstrap': boot,
    }


# ====================================================
# Main
# ====================================================
def main():
    log.info("=" * 70)
    log.info("K1376: Paper 3 review_v2 B.3 — MDD Retention Bootstrap CI (22 assets)")
    log.info("=" * 70)
    log.info(f"Bootstrap: B={BOOTSTRAP_REPS}, block={BOOTSTRAP_BLOCK}, CI={CI_PCT}%")
    log.info(f"Extending K1192 from 5 equity assets to all 22 primary assets")

    close = download_data()
    ret_df = compute_daily_returns(close)
    vix = close['VIX']
    shy_ret = ret_df['SHY']
    vix_weights = get_monthly_vt_weights(close, vix)

    all_results = {}

    # 22 individual assets
    for ticker in ASSET_CLASSES:
        if ticker not in ret_df.columns:
            log.warning(f"Ticker {ticker} not found in downloaded data, skipping")
            continue
        result = analyze_asset(ticker, ret_df[ticker], shy_ret, vix_weights)
        if result is not None:
            all_results[ticker] = result

    # 50/50 SPY/GLD composite (K1192 canonical)
    if 'SPY' in ret_df.columns and 'GLD' in ret_df.columns:
        blend = 0.5 * ret_df['SPY'] + 0.5 * ret_df['GLD']
        result = analyze_asset('50/50', blend, shy_ret, vix_weights, bh_ret=blend)
        if result is not None:
            all_results['50/50'] = result

    # ====================================================
    # Summary by Asset Class
    # ====================================================
    log.info("\n" + "=" * 80)
    log.info("SUMMARY: MDD Retention 90% CI by Asset (def_a)")
    log.info("=" * 80)

    rows = []
    for asset, r in all_results.items():
        boot = r['bootstrap']
        ci = boot['def_a_retention_fraction']
        pt = boot['point_estimates']
        rows.append({
            'asset': asset,
            'asset_class': r['asset_class'],
            'n_obs': r['n_obs'],
            'period': f"{r['period_start']} — {r['period_end']}",
            'bh_mdd_pct': pt['bh_mdd_pct'],
            'vt_mdd_pct': pt['vt_mdd_pct'],
            'hedged_mdd_pct': pt['hedged_mdd_pct'],
            'retention_point': pt['a_retention'],
            'retention_ci_lo': ci['lo'],
            'retention_ci_hi': ci['hi'],
        })

    # Print by asset class
    for cls in ['equity', 'commodity', 'bond', 'real_estate', 'composite']:
        cls_rows = [r for r in rows if r['asset_class'] == cls]
        if not cls_rows:
            continue
        log.info(f"\n--- {cls.upper()} ---")
        log.info(f"  {'Asset':>8}  {'n':>5}  {'BH MDD':>8}  {'VT MDD':>8}  "
                 f"{'Retention':>10}  {'CI_lo':>7}  {'CI_hi':>7}")
        for r in cls_rows:
            log.info(f"  {r['asset']:>8}  {r['n_obs']:>5}  {r['bh_mdd_pct']:>8.1f}  "
                     f"{r['vt_mdd_pct']:>8.1f}  "
                     f"{str(r['retention_point']):>10}  "
                     f"{str(r['retention_ci_lo']):>7}  {str(r['retention_ci_hi']):>7}")

    # Cross-sectional check: all assets with positive retention
    valid = [r for r in rows if r['retention_ci_lo'] is not None and r['retention_ci_lo'] > 0]
    log.info(f"\nAssets with CI lower bound > 0%: {len(valid)}/{len(rows)}")
    # Check if all CI lower bounds are positive (main hypothesis)
    all_positive = all(r['retention_ci_lo'] is not None and r['retention_ci_lo'] > 0 for r in rows)
    log.info(f"All 22+ assets retain MDD protection: {all_positive}")

    # ====================================================
    # Save Results
    # ====================================================
    output = {
        'experiment_id': 'K1376',
        'title': 'Paper 3 review_v2 B.3 Fix — MDD Retention Bootstrap CI (All 22 Assets)',
        'paper': 'paper/vt-trend-following',
        'review_item': 'review_v2 HIGH issue B.3',
        'methodology': {
            'vt_rule': 'w = min(12/VIX_month_end, 1), monthly rebalancing, lag 1 month',
            'tsmom_hedge': 'rolling 252-day OLS, beta clipped [0, 0.5]',
            'bootstrap': f'B={BOOTSTRAP_REPS}, block={BOOTSTRAP_BLOCK} days, seed={SEED}',
            'ci': f'{CI_PCT}% (percentile bootstrap)',
            'primary_metric': 'def_a: (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100',
            'extends': 'K1192 (5-asset canonical)',
        },
        'assets_analyzed': len(all_results),
        'k1192_comparison': K1192_CANONICAL,
        'results': all_results,
        'summary': {
            'rows': rows,
            'n_positive_ci_lo': len(valid),
            'n_total': len(rows),
            'all_positive_ci_lo': all_positive,
        },
        'verdict': None,  # to be filled after Codex review
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }

    # Determine verdict from results
    if len(rows) >= 20 and len(valid) >= 15:
        output['verdict'] = 'PASS'
        output['verdict_note'] = (
            f"MDD retention CI lo > 0 for {len(valid)}/{len(rows)} assets. "
            "Universal MDD protection hypothesis supported."
        )
    elif len(rows) >= 10 and len(valid) >= 8:
        output['verdict'] = 'CONDITIONAL_PASS'
        output['verdict_note'] = (
            f"MDD retention CI lo > 0 for {len(valid)}/{len(rows)} assets. "
            "Mostly supported but some assets show weak protection."
        )
    else:
        output['verdict'] = 'NULL'
        output['verdict_note'] = f"Only {len(valid)}/{len(rows)} assets show positive CI lo."

    log.info(f"\nVerdict: {output['verdict']} — {output['verdict_note']}")

    out_path = OUT_DIR / 'k1376_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"\nResults saved to {out_path}")

    return output


if __name__ == '__main__':
    results = main()
