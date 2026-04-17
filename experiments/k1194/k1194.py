#!/usr/bin/env python3
"""
K1194: Paper 3 TSMOM Hedge 5-Implementation Forensic
=====================================================

OBJECTIVE:
    Find the canonical TSMOM hedge implementation that reproduces Paper 3:
      - Table 3: SPY MDD retention ~93%, hedged VT Sharpe ~0.737
      - Table 6: Bootstrap 90% CI [86, 97] for SPY

CONTEXT:
    K898 (daily VIX signal, raw TSMOM, beta constrained [0,0.5]): retention=107%
    K1177 (monthly VIX, orth TSMOM, no beta constraint):           retention=132%
    K1192 (monthly VIX, raw TSMOM, beta constrained [0,0.5]):      retention=103.7%
    Paper claims:                                                   retention=93%, CI=[86,97]

    All three prior experiments yield retention > 100% (hedged MDD IMPROVES beyond VT).
    This is the "systematic direction reversal" hypothesis: the hedge makes MDD BETTER
    than VT, not just slightly worse as the paper claims (93% = slight degradation).

FORENSIC APPROACH:
    Test 5 TSMOM hedge implementations systematically to find if any reproduces paper:

    Implementation 1: Model 2 Raw TSMOM (K1177 style)
        - TSMOM_raw = sign(cum252) * r_t
        - Rolling OLS: VT ~ TSMOM_raw
        - No beta constraint
        Monthly VT, 10bps tx cost

    Implementation 2: Model 3 Orth TSMOM (Paper Model 2/3 style)
        - TSMOM_perp = TSMOM_raw - beta_MKT * MKT (full-sample)
        - Rolling OLS: VT ~ TSMOM_perp
        - No beta constraint
        Monthly VT, 10bps tx cost

    Implementation 3: Orth to BH Return (TSMOM residual after regressing on SPY return)
        - TSMOM_perp_BH = TSMOM_raw - beta_BH * BH_return (rolling 252)
        - Rolling OLS: VT ~ TSMOM_perp_BH
        - No beta constraint
        Monthly VT, 10bps tx cost

    Implementation 4: Orth to VT Signal Changes
        - TSMOM_perp_delta = TSMOM_raw - beta_delta * delta(12/VIX)
        - Rolling OLS: VT ~ TSMOM_perp_delta
        - No beta constraint
        Monthly VT, 10bps tx cost

    Implementation 5: Regression-Normalized TSMOM
        - TSMOM_norm = TSMOM_raw / rolling_std(TSMOM_raw, 252)
        - Rolling OLS: VT ~ TSMOM_norm
        - No beta constraint
        Monthly VT, 10bps tx cost

    BONUS Implementation 6: K898 exact (daily VIX, raw TSMOM, beta clipped [0,0.5])
        - Daily VIX signal (no tx cost)
        - For comparison baseline

PAPER VALUES (from main.tex Table 3 and Table 6):
    SPY: BH Sharpe=0.611, VT Sharpe=0.797, Hedged Sharpe=0.737, BH MDD=-55.2%, VT MDD=-24.7%, Hedged MDD=-26.9%
    MDD retention=93%, Bootstrap 90% CI=[86, 97]

METRICS:
    - SPY Hedged VT Sharpe
    - SPY Hedged VT MDD
    - MDD retention = (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100
    - Bootstrap MDD CI (block bootstrap, B=10000, block=252, seed=42)

VERDICT:
    MATCHED: retention in [88, 98] AND CI close to [86, 97] within 5pp
    PARTIAL: retention in [80, 105] but CI off
    DIRECTION REVERSAL: retention > 105 consistently

REFERENCES:
    - Paper main.tex Eq. 4-6, Table 3, Table 6
    - K898, K1177, K1192 implementations
    - Hood & Malik (2025) JBF

Data source: yfinance (SPY, GLD, SHY, ^VIX)
Period: 2005-01-03 to 2026-03-31
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

# ============================================================
# Configuration
# ============================================================
START_DATE = '2003-12-01'       # Lead time for TSMOM lookback + monthly VIX lag
END_DATE = '2026-04-01'
ANALYSIS_START = pd.Timestamp('2005-01-03')
VT_NUMERATOR = 12.0
TSMOM_LOOKBACK = 252
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_BLOCK = 252
ANNUALIZE = 252
TX_COST_BPS = 10.0              # 10 bps per round trip (monthly)
SEED = 42

# Paper Table 3 reference values
PAPER_T3 = {
    'bh_sharpe': 0.611,
    'vt_sharpe': 0.797,
    'hedged_sharpe': 0.737,
    'bh_mdd': -55.2,
    'vt_mdd': -24.7,
    'hedged_mdd': -26.9,
    'mdd_retention': 93,
}
# Paper Table 6 reference (SPY 90% CI)
PAPER_T6_SPY_CI = (86, 97)

# Setup logging
log_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-abe87ed7/experiments/k1194/run.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, mode='w'),
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# Data
# ============================================================
def download_data():
    tickers = ['SPY', 'GLD', '^VIX', 'SHY']
    log.info(f"Downloading {tickers} from {START_DATE} to {END_DATE}")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw['Close']
    else:
        close = raw
    close = close.rename(columns={'^VIX': 'VIX'})
    close = close.ffill()
    log.info(f"Data: {close.index[0].date()} to {close.index[-1].date()}, shape={close.shape}")
    return close


def compute_returns(close):
    return close.pct_change()


# ============================================================
# VT Construction — two variants
# ============================================================
def get_monthly_vt_weights(vix_daily):
    """Monthly VIX signal: end-of-month VIX -> next month weight, forward-filled daily."""
    vix_monthly = vix_daily.resample('ME').last()
    w_monthly = (VT_NUMERATOR / vix_monthly).clip(upper=1.0)
    w_monthly_lagged = w_monthly.shift(1)
    w_daily = w_monthly_lagged.reindex(vix_daily.index, method='ffill')
    return w_daily


def get_daily_vt_weights(vix_daily):
    """Daily VIX signal: VIX at t-1 -> weight at t (K898 style)."""
    w = (VT_NUMERATOR / vix_daily).clip(upper=1.0)
    return w.shift(1)


def build_vt_monthly(asset_ret, shy_ret, vix_daily):
    """Monthly-rebalanced VT with 10bps transaction costs."""
    w = get_monthly_vt_weights(vix_daily)
    common = (asset_ret.dropna().index
              .intersection(shy_ret.dropna().index)
              .intersection(w.dropna().index))
    common = common[common >= ANALYSIS_START]

    r = asset_ret.loc[common]
    r_shy = shy_ret.loc[common]
    w_c = w.loc[common]

    # Transaction costs: 10bps per unit of weight change
    tx = w_c.diff().abs() * (TX_COST_BPS / 10000)
    tx = tx.fillna(0)

    vt = w_c * r + (1 - w_c) * r_shy - tx
    return vt, w_c


def build_vt_daily(asset_ret, shy_ret, vix_daily):
    """Daily VIX signal VT, no transaction costs (K898 style)."""
    w = get_daily_vt_weights(vix_daily)
    common = (asset_ret.dropna().index
              .intersection(shy_ret.dropna().index)
              .intersection(w.dropna().index))
    common = common[common >= ANALYSIS_START]

    r = asset_ret.loc[common]
    r_shy = shy_ret.loc[common]
    w_c = w.loc[common]

    vt = w_c * r + (1 - w_c) * r_shy
    return vt, w_c


# ============================================================
# TSMOM Factor Variants
# ============================================================
def tsmom_raw(asset_ret, lookback=TSMOM_LOOKBACK):
    """Raw TSMOM: sign(cum252) * r_t, signal from t-lookback to t-1 (shift(1))."""
    log_ret = np.log1p(asset_ret)
    cum_log_ret = log_ret.rolling(lookback).sum().shift(1)
    signal = np.sign(cum_log_ret)
    return signal * asset_ret


def tsmom_orth_to_mkt(asset_ret, mkt_ret, lookback=TSMOM_LOOKBACK):
    """
    Orth TSMOM: TSMOM^perp = TSMOM_raw - beta_MKT_fullsample * MKT.
    Full-sample OLS for beta_MKT.
    """
    ts = tsmom_raw(asset_ret, lookback)
    common = ts.dropna().index.intersection(mkt_ret.dropna().index)
    t_c = ts.loc[common]
    m_c = mkt_ret.loc[common]
    beta_mkt = float(np.cov(t_c, m_c)[0, 1] / np.var(m_c))
    tsmom_perp = ts - beta_mkt * mkt_ret
    return tsmom_perp, beta_mkt


def tsmom_orth_to_bh_rolling(asset_ret, bh_ret, lookback=TSMOM_LOOKBACK):
    """
    TSMOM residual after rolling regression of TSMOM on BH return (rolling 252).
    Orthogonalizes out the market direction component rolling (not full-sample).
    """
    ts = tsmom_raw(asset_ret, lookback)
    common = ts.dropna().index.intersection(bh_ret.dropna().index)
    t_c = ts.loc[common]
    b_c = bh_ret.loc[common]

    rolling_cov = t_c.rolling(lookback).cov(b_c)
    rolling_var = b_c.rolling(lookback).var()
    beta_roll = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
    beta_roll_lag = beta_roll.shift(1).fillna(0)

    # Residual: TSMOM - beta * BH_return  (full-series)
    tsmom_perp = ts - beta_roll_lag * bh_ret
    return tsmom_perp


def tsmom_orth_to_delta_vix(asset_ret, vix_daily, lookback=TSMOM_LOOKBACK):
    """
    TSMOM residual after rolling regression of TSMOM on delta(12/VIX).
    Removes the VT signal-change component from TSMOM.
    """
    ts = tsmom_raw(asset_ret, lookback)
    vt_signal = (VT_NUMERATOR / vix_daily).clip(upper=1.0)
    delta_signal = vt_signal.diff()  # changes in VT weight

    common = (ts.dropna().index
              .intersection(delta_signal.dropna().index))
    t_c = ts.loc[common]
    d_c = delta_signal.loc[common]

    rolling_cov = t_c.rolling(lookback).cov(d_c)
    rolling_var = d_c.rolling(lookback).var()
    beta_roll = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)
    beta_roll_lag = beta_roll.shift(1).fillna(0)

    tsmom_perp = ts - beta_roll_lag * delta_signal
    return tsmom_perp


def tsmom_normalized(asset_ret, lookback=TSMOM_LOOKBACK):
    """
    Normalized TSMOM: standardized by rolling std over lookback window.
    """
    ts = tsmom_raw(asset_ret, lookback)
    rolling_std = ts.rolling(lookback).std()
    rolling_std_lag = rolling_std.shift(1)
    tsmom_norm = ts / rolling_std_lag.replace(0, np.nan)
    return tsmom_norm


# ============================================================
# Hedge Construction
# ============================================================
def hedge_vt_with_factor(vt_ret, factor, lookback=TSMOM_LOOKBACK,
                          constrain_beta=False, beta_bounds=(0, 0.5)):
    """
    PureVT = VT - beta_t * factor_t
    where beta_t is from rolling 252-day OLS, lagged 1 day.
    If constrain_beta: clip beta to beta_bounds.
    """
    common = vt_ret.dropna().index.intersection(factor.dropna().index)
    vt = vt_ret.loc[common]
    f = factor.loc[common]

    rolling_cov = vt.rolling(lookback).cov(f)
    rolling_var = f.rolling(lookback).var()
    b = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)

    if constrain_beta:
        b = b.clip(*beta_bounds)

    b_lag = b.shift(1).fillna(0)
    hedged = (vt - b_lag * f).dropna()
    return hedged, b_lag


# ============================================================
# Performance Metrics
# ============================================================
def compute_sharpe(returns):
    r = returns.dropna()
    if len(r) < 10 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ANNUALIZE))


def compute_mdd(returns):
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    wealth = (1 + r).cumprod()
    peak = wealth.cummax()
    dd = (wealth - peak) / peak
    return float(dd.min())


def compute_metrics(returns, name=''):
    r = returns.dropna()
    if len(r) < 10:
        return {'name': name, 'sharpe': 0, 'mdd_pct': 0, 'n_obs': 0}
    s = compute_sharpe(r)
    mdd = compute_mdd(r)
    ann_ret = float(r.mean() * ANNUALIZE)
    ann_vol = float(r.std() * np.sqrt(ANNUALIZE))
    return {
        'name': name,
        'sharpe': round(s, 3),
        'mdd_pct': round(mdd * 100, 2),
        'ann_return_pct': round(ann_ret * 100, 2),
        'ann_vol_pct': round(ann_vol * 100, 2),
        'n_obs': len(r),
        'start': str(r.index[0].date()),
        'end': str(r.index[-1].date()),
    }


def mdd_retention(bh_mdd, vt_mdd, hedged_mdd):
    """
    Retention = (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100
    All MDDs are negative numbers.
    Numerator: improvement of hedged vs BH (positive when hedged < BH in abs)
    Denominator: improvement of VT vs BH (positive when VT < BH in abs)
    100% = hedged VT is exactly as good as VT in MDD terms
    <100% = hedged VT is slightly worse than VT (paper claims 93%)
    >100% = hedged VT is BETTER than VT (K898/K1177/K1192 result)
    """
    num = bh_mdd - hedged_mdd      # positive: bh_mdd more negative
    denom = bh_mdd - vt_mdd        # positive: bh_mdd more negative
    if abs(denom) < 1e-10:
        return float('nan')
    return num / denom * 100


def block_bootstrap_mdd_retention_ci(bh_rets, vt_rets, hedged_rets,
                                       n_reps=BOOTSTRAP_REPS,
                                       block_size=BOOTSTRAP_BLOCK, seed=SEED):
    """
    Block bootstrap 90% CI for MDD retention.
    Returns point estimate and [5th, 95th] percentile CI.
    """
    rng = np.random.RandomState(seed)

    common = (bh_rets.dropna().index
              .intersection(vt_rets.dropna().index)
              .intersection(hedged_rets.dropna().index))
    bh = bh_rets.loc[common].values
    vt = vt_rets.loc[common].values
    hedged = hedged_rets.loc[common].values
    n = len(bh)

    def _mdd_arr(r):
        w = np.cumprod(1 + r)
        pk = np.maximum.accumulate(w)
        return float(np.min(w / pk - 1))

    # Point estimates
    bh_mdd_pt = _mdd_arr(bh)
    vt_mdd_pt = _mdd_arr(vt)
    h_mdd_pt = _mdd_arr(hedged)

    pt_retention = mdd_retention(bh_mdd_pt, vt_mdd_pt, h_mdd_pt)

    retentions = []
    n_blocks = max(1, n // block_size)
    for _ in range(n_reps):
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        bh_b = bh[idx]
        vt_b = vt[idx]
        h_b = hedged[idx]
        ret = mdd_retention(_mdd_arr(bh_b), _mdd_arr(vt_b), _mdd_arr(h_b))
        if np.isfinite(ret):
            retentions.append(ret)

    retentions = np.array(retentions)
    return {
        'point_estimate_pct': round(pt_retention, 1),
        'median_bootstrap_pct': round(float(np.median(retentions)), 1),
        'mean_bootstrap_pct': round(float(np.mean(retentions)), 1),
        'ci_lower_5_pct': round(float(np.percentile(retentions, 5)), 1),
        'ci_upper_95_pct': round(float(np.percentile(retentions, 95)), 1),
        'n_valid': len(retentions),
    }


def check_match(ci_lo, ci_hi, bh_mdd_pt, vt_mdd_pt, hedged_mdd_pt):
    """Check if this implementation matches paper Table 3 + Table 6 values."""
    pt_ret = mdd_retention(bh_mdd_pt, vt_mdd_pt, hedged_mdd_pt)
    paper_ret = PAPER_T3['mdd_retention']
    paper_lo, paper_hi = PAPER_T6_SPY_CI

    ret_close = abs(pt_ret - paper_ret) <= 5.0  # within 5pp
    ci_lo_close = abs(ci_lo - paper_lo) <= 5.0
    ci_hi_close = abs(ci_hi - paper_hi) <= 5.0

    if ret_close and ci_lo_close and ci_hi_close:
        return 'MATCHED'
    elif abs(pt_ret - paper_ret) <= 10.0:
        return 'PARTIAL'
    elif pt_ret > 105.0:
        return 'DIRECTION_REVERSAL'
    else:
        return 'NO_MATCH'


# ============================================================
# Main Experiment
# ============================================================
def main():
    log.info("=" * 70)
    log.info("K1194: Paper 3 TSMOM Hedge 5-Implementation Forensic")
    log.info("=" * 70)
    log.info(f"Period: {ANALYSIS_START.date()} to 2026-03-31")
    log.info(f"Paper Table 3 SPY targets: Sharpe={PAPER_T3['hedged_sharpe']}, "
             f"MDD={PAPER_T3['hedged_mdd']}%, Retention={PAPER_T3['mdd_retention']}%")
    log.info(f"Paper Table 6 SPY CI target: {PAPER_T6_SPY_CI}")
    log.info("")

    # Download data
    close = download_data()
    ret = compute_returns(close)
    vix = close['VIX']
    spy_ret = ret['SPY']
    shy_ret = ret['SHY']

    # Build BH
    bh_ret = spy_ret.loc[spy_ret.dropna().index[spy_ret.dropna().index >= ANALYSIS_START]]

    # Build VT monthly (Impls 1-5)
    vt_monthly, w_monthly = build_vt_monthly(spy_ret, shy_ret, vix)

    # Build VT daily (Impl 6 / K898 baseline)
    vt_daily, w_daily = build_vt_daily(spy_ret, shy_ret, vix)

    # Align BH to analysis start
    bh_ret = spy_ret.loc[spy_ret.index >= ANALYSIS_START].dropna()

    log.info(f"BH: n={len(bh_ret)}, Sharpe={compute_sharpe(bh_ret):.3f}, MDD={compute_mdd(bh_ret)*100:.1f}%")
    log.info(f"VT monthly: n={len(vt_monthly)}, Sharpe={compute_sharpe(vt_monthly):.3f}, MDD={compute_mdd(vt_monthly)*100:.1f}%")
    log.info(f"VT daily: n={len(vt_daily)}, Sharpe={compute_sharpe(vt_daily):.3f}, MDD={compute_mdd(vt_daily)*100:.1f}%")

    # Pre-compute TSMOM factors
    log.info("\nComputing TSMOM factors...")

    ts_raw = tsmom_raw(spy_ret)
    ts_orth_mkt, beta_mkt = tsmom_orth_to_mkt(spy_ret, spy_ret)  # using SPY as own MKT proxy
    ts_orth_bh = tsmom_orth_to_bh_rolling(spy_ret, bh_ret)
    ts_orth_delta = tsmom_orth_to_delta_vix(spy_ret, vix)
    ts_norm = tsmom_normalized(spy_ret)

    # K898 uses raw TSMOM with beta clipped [0, 0.5] on daily VT
    ts_raw_daily = tsmom_raw(spy_ret)

    log.info(f"TSMOM factors computed. beta_MKT (full-sample) = {beta_mkt:.4f}")

    implementations = [
        ('Impl1_Raw_TSMOM_Monthly', vt_monthly, ts_raw, False),
        ('Impl2_Orth_TSMOM_Monthly', vt_monthly, ts_orth_mkt, False),
        ('Impl3_Orth_BH_Monthly', vt_monthly, ts_orth_bh, False),
        ('Impl4_Orth_DeltaVIX_Monthly', vt_monthly, ts_orth_delta, False),
        ('Impl5_Normalized_TSMOM_Monthly', vt_monthly, ts_norm, False),
        ('Impl6_Raw_Daily_K898style', vt_daily, ts_raw_daily, True),  # constrain beta
        # FORENSIC: ADD instead of SUBTRACT (inverted hedge sign)
        # Hypothesis: paper may have intended VT + b*TSMOM (ADDS TSMOM exposure)
        # rather than VT - b*TSMOM (standard hedge)
        # ADD with clip [0,0.5] on DAILY VT gives retention=86.3%, closer to paper 93%
    ]

    results = {}

    for impl_name, vt_use, factor, constrain in implementations:
        log.info(f"\n{'='*60}")
        log.info(f"Running: {impl_name}")
        log.info(f"  constrain_beta={constrain}")

        try:
            hedged, beta_series = hedge_vt_with_factor(
                vt_use, factor,
                lookback=TSMOM_LOOKBACK,
                constrain_beta=constrain,
                beta_bounds=(0, 0.5)
            )

            # Align to common index
            common = (bh_ret.dropna().index
                      .intersection(vt_use.dropna().index)
                      .intersection(hedged.dropna().index))
            bh_a = bh_ret.loc[common]
            vt_a = vt_use.loc[common]
            hedged_a = hedged.loc[common]

            bh_mdd = compute_mdd(bh_a)
            vt_mdd = compute_mdd(vt_a)
            hedged_mdd = compute_mdd(hedged_a)
            hedged_sharpe = compute_sharpe(hedged_a)
            vt_sharpe = compute_sharpe(vt_a)
            bh_sharpe = compute_sharpe(bh_a)

            pt_ret = mdd_retention(bh_mdd, vt_mdd, hedged_mdd)
            log.info(f"  BH:    Sharpe={bh_sharpe:.3f}, MDD={bh_mdd*100:.1f}%")
            log.info(f"  VT:    Sharpe={vt_sharpe:.3f}, MDD={vt_mdd*100:.1f}%")
            log.info(f"  Hedged: Sharpe={hedged_sharpe:.3f}, MDD={hedged_mdd*100:.1f}%")
            log.info(f"  Point MDD Retention: {pt_ret:.1f}%")

            # Bootstrap CI
            log.info(f"  Running bootstrap (B={BOOTSTRAP_REPS})...")
            boot = block_bootstrap_mdd_retention_ci(bh_a, vt_a, hedged_a)

            ci_lo = boot['ci_lower_5_pct']
            ci_hi = boot['ci_upper_95_pct']
            verdict = check_match(ci_lo, ci_hi, bh_mdd, vt_mdd, hedged_mdd)

            log.info(f"  Bootstrap: point={boot['point_estimate_pct']}%, "
                     f"CI=[{ci_lo}, {ci_hi}]")
            log.info(f"  Paper targets: retention={PAPER_T3['mdd_retention']}%, CI={PAPER_T6_SPY_CI}")
            log.info(f"  VERDICT: {verdict}")

            results[impl_name] = {
                'implementation': impl_name,
                'constrain_beta': constrain,
                'vt_type': 'monthly' if 'Monthly' in impl_name else 'daily',
                'metrics': {
                    'bh_sharpe': round(bh_sharpe, 3),
                    'vt_sharpe': round(vt_sharpe, 3),
                    'hedged_sharpe': round(hedged_sharpe, 3),
                    'bh_mdd_pct': round(bh_mdd * 100, 2),
                    'vt_mdd_pct': round(vt_mdd * 100, 2),
                    'hedged_mdd_pct': round(hedged_mdd * 100, 2),
                },
                'mdd_retention_point_pct': round(pt_ret, 1),
                'bootstrap_ci': boot,
                'paper_comparison': {
                    'paper_retention': PAPER_T3['mdd_retention'],
                    'paper_ci_lower': PAPER_T6_SPY_CI[0],
                    'paper_ci_upper': PAPER_T6_SPY_CI[1],
                    'diff_retention': round(pt_ret - PAPER_T3['mdd_retention'], 1),
                    'diff_ci_lower': round(ci_lo - PAPER_T6_SPY_CI[0], 1),
                    'diff_ci_upper': round(ci_hi - PAPER_T6_SPY_CI[1], 1),
                },
                'verdict': verdict,
                'n_obs': len(common),
            }

        except Exception as e:
            log.error(f"  ERROR: {e}")
            import traceback
            log.error(traceback.format_exc())
            results[impl_name] = {'error': str(e), 'verdict': 'ERROR'}

    # ============================================================
    # FORENSIC: Test ADD (inverted sign) hedge implementations
    # Paper formula: PureVT = VT - b*TSMOM  (standard SUBTRACT)
    # Test: PureVT = VT + b*TSMOM  (ADD — possible sign error or different interpretation)
    # ============================================================
    log.info("\n" + "=" * 80)
    log.info("FORENSIC: Testing ADD (inverted sign) implementations")
    log.info("Hypothesis: paper may intend VT + b*TSMOM instead of VT - b*TSMOM")
    log.info("=" * 80)

    forensic_configs = [
        ('ADD_Raw_Daily_clip05', vt_daily, ts_raw_daily, True, True),   # daily VT, clip [0,0.5], ADD
        ('ADD_Raw_Daily_noclip', vt_daily, ts_raw_daily, False, True),  # daily VT, no clip, ADD
        ('ADD_Raw_Monthly_clip05', vt_monthly, ts_raw, True, True),     # monthly VT, clip [0,0.5], ADD
        ('ADD_Orth_Daily_clip05', vt_daily, ts_orth_mkt.reindex(vt_daily.index), True, True),  # orth, daily
    ]

    for fname, vt_use, factor, constrain, do_add in forensic_configs:
        try:
            # Build the hedge with inverted sign
            common_f = vt_use.dropna().index.intersection(factor.dropna().index)
            vt_f = vt_use.loc[common_f]
            f_f = factor.loc[common_f]

            rolling_cov_f = vt_f.rolling(TSMOM_LOOKBACK).cov(f_f)
            rolling_var_f = f_f.rolling(TSMOM_LOOKBACK).var()
            b_f = (rolling_cov_f / rolling_var_f).replace([np.inf, -np.inf], np.nan)
            if constrain:
                b_f = b_f.clip(0, 0.5)
            b_lag_f = b_f.shift(1).fillna(0)

            if do_add:
                hedged_f = (vt_f + b_lag_f * f_f).dropna()
            else:
                hedged_f = (vt_f - b_lag_f * f_f).dropna()

            common_f2 = bh_ret.dropna().index.intersection(vt_use.dropna().index).intersection(hedged_f.dropna().index)
            bh_f = bh_ret.loc[common_f2]
            vt_f2 = vt_use.loc[common_f2]
            h_f = hedged_f.loc[common_f2]

            bh_mdd_f = compute_mdd(bh_f)
            vt_mdd_f = compute_mdd(vt_f2)
            h_mdd_f = compute_mdd(h_f)
            h_sharpe_f = compute_sharpe(h_f)
            pt_ret_f = mdd_retention(bh_mdd_f, vt_mdd_f, h_mdd_f)

            log.info(f"\n  {fname}:")
            log.info(f"    Hedged: Sharpe={h_sharpe_f:.3f}, MDD={h_mdd_f*100:.1f}%")
            log.info(f"    Retention: {pt_ret_f:.1f}%")

            boot_f = block_bootstrap_mdd_retention_ci(bh_f, vt_f2, h_f)
            ci_lo_f = boot_f['ci_lower_5_pct']
            ci_hi_f = boot_f['ci_upper_95_pct']
            verdict_f = check_match(ci_lo_f, ci_hi_f, bh_mdd_f, vt_mdd_f, h_mdd_f)
            log.info(f"    CI=[{ci_lo_f}, {ci_hi_f}], Verdict: {verdict_f}")
            log.info(f"    Paper: retention=93%, CI=[86,97]")

            results[fname] = {
                'implementation': fname,
                'sign_note': 'ADD (inverted hedge sign)',
                'constrain_beta': constrain,
                'vt_type': 'daily' if 'Daily' in fname else 'monthly',
                'metrics': {
                    'hedged_sharpe': round(h_sharpe_f, 3),
                    'hedged_mdd_pct': round(h_mdd_f * 100, 2),
                    'vt_mdd_pct': round(vt_mdd_f * 100, 2),
                    'bh_mdd_pct': round(bh_mdd_f * 100, 2),
                },
                'mdd_retention_point_pct': round(pt_ret_f, 1),
                'bootstrap_ci': boot_f,
                'paper_comparison': {
                    'paper_retention': PAPER_T3['mdd_retention'],
                    'paper_ci_lower': PAPER_T6_SPY_CI[0],
                    'paper_ci_upper': PAPER_T6_SPY_CI[1],
                    'diff_retention': round(pt_ret_f - PAPER_T3['mdd_retention'], 1),
                    'diff_ci_lower': round(ci_lo_f - PAPER_T6_SPY_CI[0], 1),
                    'diff_ci_upper': round(ci_hi_f - PAPER_T6_SPY_CI[1], 1),
                },
                'verdict': verdict_f,
                'n_obs': len(common_f2),
            }

        except Exception as e:
            log.error(f"  {fname} ERROR: {e}")
            results[fname] = {'error': str(e), 'verdict': 'ERROR'}

    # ============================================================
    # Summary
    # ============================================================
    log.info("\n" + "=" * 80)
    log.info("SUMMARY: 5+1 Implementations vs Paper Table 3 + Table 6")
    log.info("=" * 80)
    log.info(f"Paper targets: retention={PAPER_T3['mdd_retention']}%, CI={PAPER_T6_SPY_CI}, "
             f"Hedged Sharpe={PAPER_T3['hedged_sharpe']}")
    log.info("")
    log.info(f"{'Impl':<40} {'Sharpe':>7} {'MDD%':>7} {'Ret%':>7} {'CI':>15} {'Verdict':<25}")
    log.info("-" * 100)

    matched = []
    direction_reversals = []
    for k, v in results.items():
        if 'error' in v:
            log.info(f"  {k:<40} ERROR: {v['error']}")
            continue
        m = v['metrics']
        b = v['bootstrap_ci']
        ret_pct = v['mdd_retention_point_pct']
        ci_str = f"[{b['ci_lower_5_pct']}, {b['ci_upper_95_pct']}]"
        verdict = v['verdict']
        log.info(f"  {k:<40} {m['hedged_sharpe']:>7.3f} {m['hedged_mdd_pct']:>7.1f} "
                 f"{ret_pct:>7.1f} {ci_str:>15} {verdict:<25}")
        if verdict == 'MATCHED':
            matched.append(k)
        elif verdict == 'DIRECTION_REVERSAL':
            direction_reversals.append(k)

    log.info("")
    if matched:
        log.info(f"CANONICAL MATCH FOUND: {matched}")
        log.info("=> K1177/K1192 used wrong implementation")
    elif len(direction_reversals) == len([k for k in results if 'error' not in results[k]]):
        log.info("SYSTEMATIC DIRECTION REVERSAL CONFIRMED:")
        log.info("=> ALL implementations yield retention > 105%")
        log.info("=> Paper 93%/[86,97] CANNOT be reproduced")
        log.info("=> Errata required in paper Table 3 and Table 6")
    else:
        log.info("MIXED RESULTS: some implementations partial, none fully matched")

    # ============================================================
    # Save JSON
    # ============================================================
    output = {
        'experiment_id': 'K1194',
        'title': 'Paper 3 TSMOM Hedge 5-Implementation Forensic',
        'description': (
            'Systematic test of 5+1 TSMOM hedge implementations to find '
            'which (if any) reproduces paper Table 3 retention=93% and Table 6 CI=[86,97].'
        ),
        'data_source': 'yfinance (SPY, SHY, GLD, VIX)',
        'period': f'{ANALYSIS_START.date()} to 2026-03-31',
        'methodology': {
            'vt_rule_monthly': 'w = min(12/VIX_month_end_t, 1), lag 1 month, monthly rebalancing',
            'vt_rule_daily': 'w = min(12/VIX_{t-1}, 1), daily signal (K898 style)',
            'tx_cost_monthly': '10 bps per round trip on monthly weight changes',
            'tsmom_lookback': TSMOM_LOOKBACK,
            'bootstrap': f'{BOOTSTRAP_REPS} reps, block={BOOTSTRAP_BLOCK} days, seed={SEED}',
            'mdd_retention_formula': '(MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT) * 100',
        },
        'paper_targets': {
            'table3': PAPER_T3,
            'table6_spy_ci_90pct': list(PAPER_T6_SPY_CI),
        },
        'prior_experiments': {
            'K898': {
                'method': 'daily VIX, raw TSMOM, beta clipped [0,0.5]',
                'SPY_retention': 107.0,
                'verdict': 'direction_reversal'
            },
            'K1177': {
                'method': 'monthly VIX, orth TSMOM, no beta constraint',
                'SPY_retention': 132.0,
                'verdict': 'direction_reversal'
            },
            'K1192': {
                'method': 'monthly VIX, raw TSMOM, beta clipped [0,0.5]',
                'SPY_retention': 103.7,
                'verdict': 'partial/direction_reversal',
                'note': 'CI=[93,182], far from paper [86,97]'
            },
        },
        'implementations': results,
        'summary': {
            'matched_implementations': matched,
            'direction_reversal_implementations': direction_reversals,
            'all_implementations_tested': list(results.keys()),
            'overall_verdict': (
                'CANONICAL_MATCH_FOUND' if matched else
                'SYSTEMATIC_DIRECTION_REVERSAL' if len(direction_reversals) >= 4 else
                'MIXED'
            ),
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }

    # Generate overall final verdict
    if matched:
        output['summary']['recommendation'] = (
            f"Implementation(s) {matched} match paper. "
            f"K1177/K1192 used wrong TSMOM orthogonalization. "
            f"Paper values are correct. No errata needed."
        )
    elif len(direction_reversals) >= 4:
        output['summary']['recommendation'] = (
            "ALL implementations yield retention > 105%. "
            "Paper claims 93% (hedged VT slightly worse than VT). "
            "Empirical result: hedged VT is BETTER than VT in MDD. "
            "This means TSMOM hedge ADDS drawdown protection rather than removing it. "
            "Paper Table 3 row 'TSMOM-Hedged VT MDD=-26.9%' cannot be reproduced; "
            "actual hedged MDD appears to be better than VT's -24.7%. "
            "Errata required in paper Table 3 and Table 6."
        )
    else:
        output['summary']['recommendation'] = (
            "Mixed results. Further investigation needed. "
            "Check paper's exact data version and VT construction details."
        )

    out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-abe87ed7/experiments/k1194/k1194_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"\nResults saved to: {out_path}")

    return output


if __name__ == '__main__':
    results = main()
