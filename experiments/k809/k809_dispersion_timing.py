#!/usr/bin/env python3
"""
K809: Dispersion Timing — Dispersion Ratio Strategies
======================================================
[提出: Codex GPT-5.4 #8 suggestion, 執行: Claude]

Hypothesis: When sector dispersion is high (correlation breakdown),
equal-weight sectors outperform cap-weighted SPY. The dispersion RATIO
(cross-sectional std / SPY vol) captures this relative divergence better
than raw dispersion.

Differentiation from K771:
  - K771 used raw dispersion with 25th/75th expanding percentile thresholds
  - K809 uses dispersion RATIO (cross-sectional std / SPY 20d vol)
  - K809 adds a smooth continuous strategy (S3)
  - K809 uses proper DM test from volpred.stats.model_evaluation
  - K809 focuses on 2023-2025 OOS

Strategies:
  S0: BH SPY (baseline)
  S1: BH Equal-Weight Sectors (always equal-weight 9-11 sectors)
  S2: Dispersion Switch — disp_ratio > expanding_median → EW sectors, else → SPY
  S3: Smooth — weight_EW = clip(disp_ratio / (2 * expanding_median), 0, 1)

Constraints:
  - signal.shift(1) — no lookahead
  - TX cost 5 bps per unit weight change
  - Expanding window for median (no in-sample)
  - Monthly rebalancing for S2/S3

Evaluation:
  - Sharpe, CAGR, MDD, Calmar, Sortino
  - DM test (from volpred.stats.model_evaluation) with Harvey t>3.0
  - Cross-OOS: 5 non-overlapping 2-year periods

Data: SPY + 11 SPDR sector ETFs from yfinance (2010-2026)
OOS: 2023-01-01 ~ 2024-12-31

References:
  - Solnik & Roulet (2000) "Dispersion as cross-sectional volatility"
  - Stivers (2003) "Firm-level return dispersion and future volatility"
  - Connolly & Stivers (2006) "Information content of sector dispersion"
  - Harvey, Liu, Zhu (2016) "... and the Cross-Section of Expected Returns" RFS
  - K771: prior dispersion timing (NULL result with raw dispersion)
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ── Import DM test from volpred ──────────────────────────────────────
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from volpred.stats.model_evaluation import dm_test
    DM_SOURCE = "volpred.stats.model_evaluation"
    print("✓ dm_test imported from volpred.stats.model_evaluation")
except ImportError:
    # Fallback: Newey-West HAC t-test
    def dm_test(loss1, loss2, h=1):
        d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
        valid = np.isfinite(d)
        d = d[valid]
        n = len(d)
        if n < 10:
            return (0.0, 1.0)
        d_mean = np.mean(d)
        max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
        gamma0 = np.mean((d - d_mean) ** 2)
        var_d = gamma0
        for lag in range(1, max_lag + 1):
            weight = 1 - lag / (max_lag + 1)
            gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
            var_d += 2 * weight * gamma_l
        if var_d <= 0:
            return (0.0, 1.0)
        se = np.sqrt(var_d / n)
        if se < 1e-15:
            return (0.0, 1.0)
        t_stat = d_mean / se
        p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
        return (float(t_stat), float(p_val))
    DM_SOURCE = "scipy fallback (Newey-West HAC)"
    print("⚠ dm_test fallback to scipy (Newey-West HAC)")


# ── Configuration ────────────────────────────────────────────────────
SECTOR_ETFS = ['XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU', 'XLB', 'XLRE', 'XLC']
TICKERS = ['SPY'] + SECTOR_ETFS
START = '2010-01-01'
END = '2026-04-01'
DISP_WINDOW = 20       # rolling window for dispersion & SPY vol
TX_COST = 0.0005       # 5 bps per unit weight change
WARMUP_DAYS = 252      # expanding window minimum for median
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

print("=" * 70)
print("K809: Dispersion Timing — Dispersion Ratio Strategies")
print("=" * 70)

# ══════════════════════════════════════════════════════════════════════
# PART A: Data Download & Descriptive Statistics
# ══════════════════════════════════════════════════════════════════════
print("\n[1/6] Downloading data...")
data = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)
prices = data['Close'].copy()

# Handle MultiIndex columns if needed
if isinstance(prices.columns, pd.MultiIndex):
    prices.columns = prices.columns.get_level_values(-1)

prices = prices.dropna(how='all')

# Check available sectors — drop XLRE/XLC if they restrict data to < 2012
# (XLRE starts 2015, XLC starts 2018 — keeping them loses all pre-2018 data)
avail_sectors_all = [s for s in SECTOR_ETFS if s in prices.columns and prices[s].notna().sum() > 500]

# Forward fill small gaps
prices = prices.ffill(limit=5)

# Check if short-history sectors restrict the start date too much
core_sectors = [s for s in avail_sectors_all if s not in ['XLRE', 'XLC']]
all_valid = prices[['SPY'] + avail_sectors_all].notna().all(axis=1)
core_valid = prices[['SPY'] + core_sectors].notna().all(axis=1)

all_start = prices.index[all_valid][0] if all_valid.any() else None
core_start = prices.index[core_valid][0] if core_valid.any() else None

if all_start is not None and core_start is not None:
    print(f"  All 11 sectors start: {all_start.strftime('%Y-%m-%d')}")
    print(f"  Core 9 sectors start: {core_start.strftime('%Y-%m-%d')}")

# Use 9 sectors if 11 sectors lose > 4 years of data
if all_start is not None and core_start is not None and (all_start - core_start).days > 1460:
    avail_sectors = core_sectors
    print(f"  → Using 9 core sectors (dropping XLRE, XLC) to preserve 2010-2018 data")
else:
    avail_sectors = avail_sectors_all
    print(f"  → Using all {len(avail_sectors)} sectors")

missing_sectors = [s for s in SECTOR_ETFS if s not in avail_sectors]
if missing_sectors:
    print(f"  Dropped sectors: {missing_sectors}")
print(f"  Available sectors: {len(avail_sectors)} — {avail_sectors}")

# Determine common date range (all chosen sectors + SPY must have data)
valid_mask = prices[['SPY'] + avail_sectors].notna().all(axis=1)
prices = prices.loc[valid_mask]

print(f"  Data range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(prices)}")

# ── Compute Returns ──────────────────────────────────────────────────
sector_returns = prices[avail_sectors].pct_change().iloc[1:]
spy_ret = prices['SPY'].pct_change().iloc[1:]

# Equal-weight sector basket return
ew_sector_ret = sector_returns.mean(axis=1)

# ── Dispersion Measures ──────────────────────────────────────────────
print("\n[2/6] Computing Dispersion Measures...")

# Cross-sectional volatility: std of sector returns each day
daily_cs_vol = sector_returns.std(axis=1)

# SPY rolling volatility (20d)
spy_rolling_vol = spy_ret.rolling(DISP_WINDOW).std()

# Dispersion ratio: cross-sectional std / SPY vol
dispersion_ratio = daily_cs_vol.rolling(DISP_WINDOW).mean() / spy_rolling_vol
dispersion_ratio = dispersion_ratio.replace([np.inf, -np.inf], np.nan)

# Expanding median (no lookahead — computed on all data up to that point)
expanding_median = dispersion_ratio.expanding(min_periods=WARMUP_DAYS).median()

# Descriptive stats
dr_clean = dispersion_ratio.dropna()
print(f"  Dispersion ratio mean: {dr_clean.mean():.4f}")
print(f"  Dispersion ratio std:  {dr_clean.std():.4f}")
print(f"  Dispersion ratio median: {dr_clean.median():.4f}")
print(f"  Dispersion ratio 25th pct: {dr_clean.quantile(0.25):.4f}")
print(f"  Dispersion ratio 75th pct: {dr_clean.quantile(0.75):.4f}")
print(f"  EW sectors vs SPY corr: {ew_sector_ret.corr(spy_ret):.4f}")

# ══════════════════════════════════════════════════════════════════════
# PART B: Strategy Construction
# ══════════════════════════════════════════════════════════════════════
print("\n[3/6] Constructing strategies...")

# Align all series to common index where dispersion ratio is available
common_idx = dispersion_ratio.dropna().index
common_idx = common_idx.intersection(spy_ret.index)
common_idx = common_idx.intersection(ew_sector_ret.index)
common_idx = common_idx.intersection(expanding_median.dropna().index)

# Re-align
dr = dispersion_ratio.reindex(common_idx)
exp_med = expanding_median.reindex(common_idx)
spy = spy_ret.reindex(common_idx)
ew_sec = ew_sector_ret.reindex(common_idx)

# ── Monthly rebalancing helper ───────────────────────────────────────
def apply_monthly_rebal(signal_raw, idx):
    """Hold weights constant within each month, update at month-end."""
    month_end = pd.Series(False, index=idx)
    for i in range(len(idx) - 1):
        if idx[i].month != idx[i + 1].month:
            month_end.iloc[i] = True
    month_end.iloc[-1] = True

    rebal_signal = signal_raw.copy()
    current_w = rebal_signal.iloc[0]
    for i in range(len(rebal_signal)):
        if month_end.iloc[i]:
            current_w = rebal_signal.iloc[i]
        else:
            rebal_signal.iloc[i] = current_w
    return rebal_signal


def compute_strategy_return(weight_ew, spy_series, ew_series, name, tx_cost=TX_COST):
    """Compute strategy return given EW weight (rest goes to SPY)."""
    ret = weight_ew * ew_series + (1 - weight_ew) * spy_series
    # TX cost
    weight_change = weight_ew.diff().abs()
    weight_change.iloc[0] = 0
    tx = weight_change * tx_cost
    ret_net = ret - tx
    return ret_net


# ── S0: BH SPY ──────────────────────────────────────────────────────
s0_ret = spy.copy()
print(f"  S0: BH SPY — {len(s0_ret)} days")

# ── S1: BH Equal-Weight Sectors ─────────────────────────────────────
s1_ret = ew_sec.copy()
print(f"  S1: BH EW Sectors — {len(s1_ret)} days")

# ── S2: Dispersion Switch ───────────────────────────────────────────
# When disp_ratio > expanding_median → EW sectors (weight=1)
# Otherwise → SPY (weight=0)
raw_signal_s2 = (dr > exp_med).astype(float)
# CRITICAL: shift(1) for no-lookahead
raw_signal_s2 = raw_signal_s2.shift(1)
raw_signal_s2 = raw_signal_s2.dropna()

# Restrict to shifted signal availability
idx_s2 = raw_signal_s2.index
signal_s2 = apply_monthly_rebal(raw_signal_s2, idx_s2)
s2_ret = compute_strategy_return(
    signal_s2, spy.reindex(idx_s2), ew_sec.reindex(idx_s2), 'S2'
)
print(f"  S2: Dispersion Switch — {len(s2_ret)} days")

# ── S3: Smooth ──────────────────────────────────────────────────────
# weight_EW = clip(disp_ratio / (2 * expanding_median), 0, 1)
# This gives a continuous weight: when disp_ratio = 2*median → weight=1
raw_signal_s3 = (dr / (2 * exp_med)).clip(0, 1)
# CRITICAL: shift(1)
raw_signal_s3 = raw_signal_s3.shift(1)
raw_signal_s3 = raw_signal_s3.dropna()

idx_s3 = raw_signal_s3.index
signal_s3 = apply_monthly_rebal(raw_signal_s3, idx_s3)
s3_ret = compute_strategy_return(
    signal_s3, spy.reindex(idx_s3), ew_sec.reindex(idx_s3), 'S3'
)
print(f"  S3: Smooth — {len(s3_ret)} days")

# ── Common evaluation index ──────────────────────────────────────────
eval_idx = s0_ret.index.intersection(s1_ret.index)
eval_idx = eval_idx.intersection(s2_ret.index)
eval_idx = eval_idx.intersection(s3_ret.index)

s0 = s0_ret.reindex(eval_idx)
s1 = s1_ret.reindex(eval_idx)
s2 = s2_ret.reindex(eval_idx)
s3 = s3_ret.reindex(eval_idx)

# ══════════════════════════════════════════════════════════════════════
# PART C: Performance Evaluation
# ══════════════════════════════════════════════════════════════════════
print("\n[4/6] Performance Evaluation...")

def calc_metrics(returns, name):
    """Standard performance metrics."""
    r = returns.dropna()
    n = len(r)
    if n < 10:
        return {'name': name, 'n_days': n, 'ann_return': np.nan, 'ann_vol': np.nan,
                'sharpe': np.nan, 'mdd': np.nan, 'calmar': np.nan, 'sortino': np.nan}
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0
    # CAGR
    years = n / 252
    total_ret = cum.iloc[-1]
    cagr = total_ret ** (1 / years) - 1 if years > 0 and total_ret > 0 else 0
    return {
        'name': name,
        'n_days': int(n),
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'cagr': round(float(cagr), 4),
    }


strategies = {
    'S0: BH SPY': s0,
    'S1: BH EW Sectors': s1,
    'S2: Dispersion Switch': s2,
    'S3: Smooth': s3,
}

# ── Full-period results ──────────────────────────────────────────────
print(f"\n  Full Period: {eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}")
print(f"  {'Strategy':<30} {'CAGR':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

full_results = {}
for name, ret in strategies.items():
    m = calc_metrics(ret, name)
    full_results[name] = m
    print(f"  {name:<30} {m['cagr']:>8.4f} {m['ann_vol']:>8.4f} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} {m['calmar']:>8.4f} {m['sortino']:>8.4f}")

# ── OOS results (2023-2025) ──────────────────────────────────────────
print(f"\n  OOS Period: {OOS_START} to {OOS_END}")
oos_mask = (eval_idx >= OOS_START) & (eval_idx <= OOS_END)
if oos_mask.sum() > 50:
    print(f"  {'Strategy':<30} {'CAGR':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MDD':>8}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    oos_results = {}
    for name, ret in strategies.items():
        m = calc_metrics(ret[oos_mask], name)
        oos_results[name] = m
        print(f"  {name:<30} {m['cagr']:>8.4f} {m['ann_vol']:>8.4f} {m['sharpe']:>8.4f} {m['mdd']:>8.4f}")
else:
    oos_results = {}
    print("  ⚠ Insufficient OOS data")

# ── Regime distribution ──────────────────────────────────────────────
print(f"\n  S2 Signal Distribution:")
s2_aligned = signal_s2.reindex(eval_idx)
spy_pct = (s2_aligned == 0.0).mean() * 100
ew_pct = (s2_aligned == 1.0).mean() * 100
print(f"    SPY (disp_ratio <= median): {spy_pct:.1f}%")
print(f"    EW Sectors (disp_ratio > median): {ew_pct:.1f}%")

print(f"\n  S3 Smooth Weight Stats:")
s3_aligned = signal_s3.reindex(eval_idx)
print(f"    Mean EW weight: {s3_aligned.mean():.4f}")
print(f"    Std EW weight:  {s3_aligned.std():.4f}")
print(f"    Min EW weight:  {s3_aligned.min():.4f}")
print(f"    Max EW weight:  {s3_aligned.max():.4f}")

# ── Per-regime returns analysis ──────────────────────────────────────
print(f"\n  Per-Regime Returns (based on S2 signal):")
for regime_val, label in [(0.0, 'Low Disp (SPY)'), (1.0, 'High Disp (EW Sectors)')]:
    mask = s2_aligned == regime_val
    if mask.sum() > 20:
        spy_regime_ann = s0[mask].mean() * 252
        ew_regime_ann = s1[mask].mean() * 252
        diff = ew_regime_ann - spy_regime_ann
        print(f"    {label:>25}: SPY={spy_regime_ann:+.4f}  EW={ew_regime_ann:+.4f}  EW-SPY={diff:+.4f}")

# ══════════════════════════════════════════════════════════════════════
# PART D: Statistical Tests (DM Test)
# ══════════════════════════════════════════════════════════════════════
print(f"\n[5/6] Diebold-Mariano Tests (source: {DM_SOURCE})...")

# Use squared return differences as loss (forecast evaluation)
# Loss = squared daily return (proxy for volatility forecast error)
# But for strategy comparison, we compare negative returns as "loss"
# i.e., we want to test if strategy X produces statistically different returns
# Standard approach: loss = -return (lower return = higher loss)
# DM test on -returns: negative t means model 1 has lower loss (higher return)

dm_results = {}
for name, ret in [('S1: BH EW Sectors', s1), ('S2: Dispersion Switch', s2), ('S3: Smooth', s3)]:
    # Loss = -return: strategy with higher return has lower loss
    loss_strat = -ret.values
    loss_spy = -s0.values
    t_stat, p_val = dm_test(loss_strat, loss_spy, h=1)
    harvey_sig = abs(t_stat) > 3.0
    dm_results[name] = {
        't_stat': round(float(t_stat), 4),
        'p_value': round(float(p_val), 4),
        'harvey_significant': harvey_sig,
    }
    sig_label = "***" if harvey_sig else ("*" if p_val < 0.05 else "")
    direction = "strat better" if t_stat < 0 else "SPY better"
    print(f"  {name} vs S0: t={t_stat:+.4f}, p={p_val:.4f} ({direction}) {sig_label}")

# ── DM test on OOS only ─────────────────────────────────────────────
print(f"\n  DM Tests (OOS only: {OOS_START} to {OOS_END}):")
dm_oos_results = {}
if oos_mask.sum() > 50:
    for name, ret in [('S1: BH EW Sectors', s1), ('S2: Dispersion Switch', s2), ('S3: Smooth', s3)]:
        loss_strat = -ret[oos_mask].values
        loss_spy = -s0[oos_mask].values
        t_stat, p_val = dm_test(loss_strat, loss_spy, h=1)
        dm_oos_results[name] = {
            't_stat': round(float(t_stat), 4),
            'p_value': round(float(p_val), 4),
        }
        direction = "strat better" if t_stat < 0 else "SPY better"
        print(f"  {name} vs S0 (OOS): t={t_stat:+.4f}, p={p_val:.4f} ({direction})")

# ══════════════════════════════════════════════════════════════════════
# PART E: Cross-OOS Validation
# ══════════════════════════════════════════════════════════════════════
print(f"\n[6/6] Cross-OOS Validation (5 x 2-year periods)...")

oos_periods = [
    ('2011-01-01', '2012-12-31'),
    ('2013-01-01', '2014-12-31'),
    ('2015-01-01', '2016-12-31'),
    ('2017-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
]

cross_oos_results = []
wins_s2 = 0
wins_s3 = 0
n_valid_periods = 0

print(f"\n  {'Period':<25} {'S0 SPY':>10} {'S1 EW':>10} {'S2 Switch':>10} {'S3 Smooth':>10} {'S2>S0':>6} {'S3>S0':>6}")
print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*6} {'-'*6}")

for start_d, end_d in oos_periods:
    mask = (eval_idx >= start_d) & (eval_idx <= end_d)
    if mask.sum() < 100:
        continue

    m0 = calc_metrics(s0[mask], '')['sharpe']
    m1 = calc_metrics(s1[mask], '')['sharpe']
    m2 = calc_metrics(s2[mask], '')['sharpe']
    m3 = calc_metrics(s3[mask], '')['sharpe']

    beat_s2 = m2 > m0
    beat_s3 = m3 > m0
    if beat_s2:
        wins_s2 += 1
    if beat_s3:
        wins_s3 += 1
    n_valid_periods += 1

    cross_oos_results.append({
        'period': f"{start_d} to {end_d}",
        's0_sharpe': round(m0, 4),
        's1_sharpe': round(m1, 4),
        's2_sharpe': round(m2, 4),
        's3_sharpe': round(m3, 4),
        's2_beats_s0': beat_s2,
        's3_beats_s0': beat_s3,
    })

    check_s2 = "Y" if beat_s2 else "N"
    check_s3 = "Y" if beat_s3 else "N"
    print(f"  {start_d} to {end_d:<10} {m0:>10.4f} {m1:>10.4f} {m2:>10.4f} {m3:>10.4f} {check_s2:>6} {check_s3:>6}")

print(f"\n  Cross-OOS Summary:")
print(f"    S2 (Switch) beats S0 (SPY): {wins_s2}/{n_valid_periods}")
print(f"    S3 (Smooth) beats S0 (SPY): {wins_s3}/{n_valid_periods}")

# ── Sensitivity Analysis ────────────────────────────────────────────
print(f"\n  Sensitivity Analysis (dispersion window +-20%):")
sensitivity = {}
for w in [16, 20, 24]:
    cs_vol_w = sector_returns.std(axis=1).rolling(w).mean()
    spy_vol_w = spy_ret.rolling(w).std()
    dr_w = cs_vol_w / spy_vol_w
    dr_w = dr_w.replace([np.inf, -np.inf], np.nan)
    exp_med_w = dr_w.expanding(min_periods=WARMUP_DAYS).median()

    ci = dr_w.dropna().index.intersection(eval_idx)
    ci = ci.intersection(exp_med_w.dropna().index)

    dr_a = dr_w.reindex(ci)
    med_a = exp_med_w.reindex(ci)
    spy_a = spy_ret.reindex(ci)
    ew_a = ew_sector_ret.reindex(ci)

    # S3 smooth with this window
    raw_s = (dr_a / (2 * med_a)).clip(0, 1)
    raw_s = raw_s.shift(1).dropna()
    si = raw_s.index
    ms = apply_monthly_rebal(raw_s, si)
    ret_w = compute_strategy_return(ms, spy_ret.reindex(si), ew_sector_ret.reindex(si), f'w={w}')
    m = calc_metrics(ret_w, f'window={w}')
    sensitivity[w] = m['sharpe']
    print(f"    Window={w}d: Sharpe={m['sharpe']:.4f}")

base_sharpe = sensitivity.get(20, 0)
max_pct_drop = 0
for w, s in sensitivity.items():
    if w != 20 and base_sharpe != 0:
        pct_change = (s - base_sharpe) / abs(base_sharpe) * 100
        max_pct_drop = max(max_pct_drop, abs(pct_change))
        print(f"    Delta from base (w={w}): {pct_change:+.1f}%")

sensitivity_pass = max_pct_drop <= 30

# ══════════════════════════════════════════════════════════════════════
# SUMMARY & VERDICT
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")

s0_sharpe = full_results['S0: BH SPY']['sharpe']
s1_sharpe = full_results['S1: BH EW Sectors']['sharpe']
s2_sharpe = full_results['S2: Dispersion Switch']['sharpe']
s3_sharpe = full_results['S3: Smooth']['sharpe']

# Verdict logic
if s2_sharpe > 2 * s0_sharpe or s3_sharpe > 2 * s0_sharpe:
    verdict = "SUSPICIOUS: Sharpe > 2x baseline — likely bug"
    codex_severity = "HIGH"
elif (s2_sharpe > s0_sharpe and wins_s2 >= 3) or (s3_sharpe > s0_sharpe and wins_s3 >= 3):
    verdict = "PROMISING: dispersion ratio adds value — needs Codex audit"
    codex_severity = "MEDIUM"
elif s1_sharpe > s0_sharpe:
    verdict = "MARGINAL: EW sectors > SPY, but timing adds no value"
    codex_severity = "LOW"
else:
    verdict = "NULL: dispersion timing with ratio signal adds no value over SPY"
    codex_severity = "LOW"

# Check K771 comparison
print(f"\n  K771 (raw dispersion) verdict: NULL — Sharpe 0.81 vs SPY 0.82")
print(f"  K809 (dispersion ratio) results:")
print(f"    S0 (SPY):      Sharpe {s0_sharpe:.4f}")
print(f"    S1 (EW B&H):   Sharpe {s1_sharpe:.4f}")
print(f"    S2 (Switch):   Sharpe {s2_sharpe:.4f}")
print(f"    S3 (Smooth):   Sharpe {s3_sharpe:.4f}")
print(f"\n  Cross-OOS: S2 beats S0 {wins_s2}/{n_valid_periods}, S3 beats S0 {wins_s3}/{n_valid_periods}")
print(f"  Sensitivity pass (<=30% drop): {sensitivity_pass}")
print(f"\n  Verdict: {verdict}")
print(f"  Codex severity: {codex_severity}")

# ══════════════════════════════════════════════════════════════════════
# SAVE RESULTS
# ══════════════════════════════════════════════════════════════════════
output = {
    'experiment_id': 'K809',
    'title': 'Dispersion Timing — Dispersion Ratio Strategies',
    'proposer': 'Codex GPT-5.4 #8 suggestion',
    'executor': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_period': f"{eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(eval_idx)),
    'sectors_used': avail_sectors,
    'n_sectors': len(avail_sectors),
    'methodology': {
        'dispersion_measure': 'dispersion_ratio = rolling_20d_cs_std / rolling_20d_SPY_vol',
        'S0': 'Buy & Hold SPY',
        'S1': 'Buy & Hold Equal-Weight Sectors',
        'S2': 'Dispersion Switch: disp_ratio > expanding_median → EW sectors, else SPY',
        'S3': 'Smooth: weight_EW = clip(disp_ratio / (2*expanding_median), 0, 1)',
        'signal_lag': 'shift(1)',
        'rebalancing': 'monthly',
        'tx_cost_per_unit_change': TX_COST,
        'expanding_median_warmup': WARMUP_DAYS,
    },
    'dispersion_ratio_stats': {
        'mean': round(float(dr_clean.mean()), 4),
        'std': round(float(dr_clean.std()), 4),
        'median': round(float(dr_clean.median()), 4),
        'q25': round(float(dr_clean.quantile(0.25)), 4),
        'q75': round(float(dr_clean.quantile(0.75)), 4),
    },
    'signal_distribution': {
        'S2_spy_pct': round(float(spy_pct), 1),
        'S2_ew_pct': round(float(ew_pct), 1),
        'S3_mean_ew_weight': round(float(s3_aligned.mean()), 4),
        'S3_std_ew_weight': round(float(s3_aligned.std()), 4),
    },
    'full_period_results': full_results,
    'oos_results': oos_results if oos_results else None,
    'dm_tests_full': dm_results,
    'dm_tests_oos': dm_oos_results if dm_oos_results else None,
    'dm_test_source': DM_SOURCE,
    'cross_oos': {
        'periods': cross_oos_results,
        'S2_beats_S0': f"{wins_s2}/{n_valid_periods}",
        'S3_beats_S0': f"{wins_s3}/{n_valid_periods}",
    },
    'sensitivity': {str(k): round(v, 4) for k, v in sensitivity.items()},
    'sensitivity_pass': sensitivity_pass,
    'verdict': verdict,
    'codex_severity': codex_severity,
    'comparison_with_K771': 'K771 used raw dispersion → NULL. K809 uses dispersion ratio.',
    'references': [
        'Solnik & Roulet (2000) Dispersion as cross-sectional volatility',
        'Stivers (2003) Firm-level return dispersion and future volatility',
        'Connolly & Stivers (2006) Information content of sector dispersion',
        'Harvey, Liu, Zhu (2016) ... and the Cross-Section of Expected Returns, RFS',
        'K771: prior dispersion timing experiment (NULL result)',
    ],
}

out_path = Path(__file__).resolve().parent / 'k809_dispersion_timing_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {out_path}")
print(f"\n{'='*70}")
print("K809 COMPLETE")
print(f"{'='*70}")
