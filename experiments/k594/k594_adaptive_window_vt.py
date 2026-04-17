#!/usr/bin/env python3
"""
K594: Adaptive Window VT Strategy — Regime-Dependent Estimation Window
======================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K593 showed optimal GARCH window is regime-dependent:
    - Elevated VIX (OOS4 COVID): W=504 wins (DM=-3.29***)
    - Calm markets (OOS2): W=2000 wins (DM=+2.09**)
    - Very calm (OOS1, OOS3): W=252 wins

  Can we BUILD A TRADING STRATEGY from this? Use short window (responsive)
  when VIX high, long window (stable) when VIX low.

Design:
  1. Data: SPY + VIX from yfinance (2005-2026)
  2. Adaptive window GJR-GARCH:
     - VIX < 15: W=2000 (stable, calm market — precision matters)
     - VIX 15-25: W=1000 (moderate — balance)
     - VIX > 25: W=504 (responsive, crisis — regime relevance matters)
  3. Strategy: VT weight = min(target_vol / σ_adaptive, 1.0)
     target_vol = 12% annualized (≈ 0.756% daily)
  4. Benchmarks:
     a. Fixed W=2000 VT (our standard)
     b. Fixed W=504 VT
     c. 12/VIX (no GARCH at all)
     d. Buy-and-hold SPY
  5. Cross-OOS: 5 non-overlapping periods (same as K593)
  6. Harvey t>3.0 threshold for significance
  7. Transaction cost: 5bp per turnover

Key question:
  Does regime-switching the ESTIMATION WINDOW improve VT,
  even though regime-switching the SIGNAL (VIX overlays) always fails?

Data source: yfinance (SPY daily close, VIX close, 2005-2026)
References:
  K593: Window Cross-OOS — regime-dependent, no universal winner
  K591: Window Size Sensitivity Sweep (W=504 best in 2023-24)
  K406/K408: W=2000 upgrade based on persistence bias
  Feng & Zhang (2025) J.Forecasting — U-shape window
  Moreira & Muir (2017) JF — Volatility-managed portfolios
  Fleming, Kirby & Ostdiek (2001) JFE — Economic value of vol timing
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
EXPERIMENT_ID = "K594"
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

# VIX regime thresholds and corresponding windows
REGIME_CONFIG = {
    'calm':     {'vix_upper': 15,  'window': 2000, 'label': 'VIX<15 → W=2000'},
    'moderate': {'vix_upper': 25,  'window': 1000, 'label': 'VIX 15-25 → W=1000'},
    'crisis':   {'vix_upper': 999, 'window': 504,  'label': 'VIX>25 → W=504'},
}

# Fixed window benchmarks
FIXED_WINDOWS = [504, 2000]

# Strategy parameters
TARGET_VOL_ANNUAL = 0.12          # 12% annualized target
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)  # ~0.756% daily
REFIT_EVERY = 21                  # refit every 21 trading days
TX_COST_BPS = 5                   # 5bp per turnover
RF_DAILY = 0.04 / 252             # risk-free rate (~4% annualized)

# 5 OOS periods (same as K593 for comparability)
OOS_PERIODS = {
    'OOS1_2012-2013': ('2012-01-01', '2013-12-31'),
    'OOS2_2014-2015': ('2014-01-01', '2015-12-31'),
    'OOS3_2016-2017': ('2016-01-01', '2017-12-31'),
    'OOS4_2020-2021': ('2020-01-01', '2021-12-31'),
    'OOS5_2023-2024': ('2023-01-01', '2024-12-31'),
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: Adaptive Window VT Strategy")
print("  Regime-dependent estimation window for Volatility Targeting")
print(f"  Target vol: {TARGET_VOL_ANNUAL*100:.0f}% annualized")
print(f"  TX cost: {TX_COST_BPS} bps per turnover")
print("  Regime windows:")
for regime, cfg in REGIME_CONFIG.items():
    print(f"    {cfg['label']}")
print(f"  Benchmarks: Fixed W={FIXED_WINDOWS}, 12/VIX, Buy-and-Hold")
print(f"  OOS periods: {len(OOS_PERIODS)}")
print("=" * 70)
print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
t0_total = time.time()


# ============================================================
# Data download
# ============================================================
print("\n[1] Downloading data...")
spy_df = yf.download('SPY', start='2003-01-01', end='2026-03-28',
                     progress=False, auto_adjust=True)
if hasattr(spy_df.columns, 'nlevels') and spy_df.columns.nlevels > 1:
    spy_df.columns = spy_df.columns.get_level_values(0)

vix_df = yf.download('^VIX', start='2003-01-01', end='2026-03-28',
                     progress=False, auto_adjust=True)
if hasattr(vix_df.columns, 'nlevels') and vix_df.columns.nlevels > 1:
    vix_df.columns = vix_df.columns.get_level_values(0)

# Align
spy_close = spy_df['Close'].dropna()
vix_close = vix_df['Close'].dropna()
common_idx = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

# Log returns in %
ret_pct = (np.log(spy_close / spy_close.shift(1)).dropna()) * 100
# Simple returns for strategy
ret_simple = (spy_close / spy_close.shift(1) - 1).dropna()

# Align all series
common_idx2 = ret_pct.index.intersection(ret_simple.index).intersection(vix_close.index)
ret_pct = ret_pct.loc[common_idx2]
ret_simple = ret_simple.loc[common_idx2]
vix_close = vix_close.loc[common_idx2]

print(f"  SPY: {len(ret_pct)} daily returns ({ret_pct.index[0].date()} to {ret_pct.index[-1].date()})")
print(f"  Mean={ret_pct.mean():.4f}%, Std={ret_pct.std():.4f}%")
print(f"  VIX: mean={vix_close.mean():.1f}, median={vix_close.median():.1f}")


# ============================================================
# Helper: get VIX regime
# ============================================================
def get_regime(vix_val):
    """Return regime name based on VIX level."""
    v = float(vix_val) if hasattr(vix_val, 'item') else vix_val
    if v < 15:
        return 'calm'
    elif v <= 25:
        return 'moderate'
    else:
        return 'crisis'


def get_window_for_regime(vix_val):
    """Return estimation window based on VIX regime."""
    regime = get_regime(vix_val)
    return REGIME_CONFIG[regime]['window']


# ============================================================
# GJR-GARCH rolling vol forecast (single window, returns daily σ)
# ============================================================
def gjr_garch_vol_series(returns_pct, oos_start, oos_end, window, refit_every=21):
    """
    Rolling GJR-GARCH(1,1)-t vol forecast for VT strategy.
    Returns daily annualized vol forecasts (σ in decimal, not %).
    """
    oos_mask = (returns_pct.index >= oos_start) & (returns_pct.index <= oos_end)
    oos_dates = returns_pct.index[oos_mask]
    if len(oos_dates) == 0:
        return pd.Series(dtype=float)

    all_idx = returns_pct.index.tolist()
    oos_set = set(oos_dates.tolist())

    last_model = None
    days_since_fit = refit_every  # force fit on first day
    vol_forecasts = {}

    for dt in all_idx:
        if dt not in oos_set:
            continue
        pos = all_idx.index(dt)
        if pos < window:
            continue

        train = returns_pct.iloc[pos - window:pos]
        days_since_fit += 1
        need_refit = (days_since_fit >= refit_every) or (last_model is None)

        if need_refit:
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                                dist='t', mean='Zero', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                if res.convergence_flag == 0:
                    last_model = res
                    days_since_fit = 0
            except Exception:
                pass

        if last_model is not None:
            try:
                fcast = last_model.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                if h > 0 and np.isfinite(h):
                    # Convert from daily variance (in %^2) to annualized σ (decimal)
                    daily_sigma = np.sqrt(h) / 100.0
                    annual_sigma = daily_sigma * np.sqrt(252)
                    vol_forecasts[dt] = annual_sigma
            except Exception:
                pass

    return pd.Series(vol_forecasts)


# ============================================================
# Adaptive window vol forecast
# ============================================================
def adaptive_window_vol_series(returns_pct, vix_series, oos_start, oos_end,
                               refit_every=21):
    """
    Adaptive window GJR-GARCH: switch estimation window based on VIX regime.
    For each OOS day:
      1. Check yesterday's VIX → determine regime → select window
      2. Fit GJR-GARCH with that window
      3. Forecast 1-day ahead vol
    """
    oos_mask = (returns_pct.index >= oos_start) & (returns_pct.index <= oos_end)
    oos_dates = returns_pct.index[oos_mask]
    if len(oos_dates) == 0:
        return pd.Series(dtype=float), {}

    all_idx = returns_pct.index.tolist()
    oos_set = set(oos_dates.tolist())

    # Cache fitted models by (window, last_fit_date) to avoid re-fitting
    # when regime doesn't change
    cached_models = {}  # {window: (model, fit_date, days_since)}
    vol_forecasts = {}
    regime_log = {}  # {date: regime_name}

    for dt in all_idx:
        if dt not in oos_set:
            continue

        pos = all_idx.index(dt)

        # Use PREVIOUS day's VIX (no look-ahead)
        if pos < 1:
            continue
        prev_dt = all_idx[pos - 1]
        if prev_dt not in vix_series.index:
            continue
        prev_vix = vix_series.loc[prev_dt]
        if hasattr(prev_vix, 'item'):
            prev_vix = prev_vix.item()

        regime = get_regime(prev_vix)
        window = REGIME_CONFIG[regime]['window']
        regime_log[dt] = regime

        if pos < window:
            continue

        # Check if we need to refit for this window
        need_refit = True
        if window in cached_models:
            _, _, days_since = cached_models[window]
            if days_since < refit_every:
                need_refit = False

        if need_refit:
            train = returns_pct.iloc[pos - window:pos]
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                                dist='t', mean='Zero', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                if res.convergence_flag == 0:
                    cached_models[window] = (res, dt, 0)
            except Exception:
                pass

        # Increment days_since for all cached models
        for w in list(cached_models.keys()):
            m, fd, ds = cached_models[w]
            cached_models[w] = (m, fd, ds + 1)

        # Forecast
        if window in cached_models:
            model, _, _ = cached_models[window]
            try:
                fcast = model.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                if h > 0 and np.isfinite(h):
                    daily_sigma = np.sqrt(h) / 100.0
                    annual_sigma = daily_sigma * np.sqrt(252)
                    vol_forecasts[dt] = annual_sigma
            except Exception:
                pass

    return pd.Series(vol_forecasts), regime_log


# ============================================================
# VT strategy backtest
# ============================================================
def vt_backtest(vol_forecast_series, returns_simple, target_vol_annual,
                tx_cost_bps=5, strategy_name="VT"):
    """
    Backtest a VT strategy.
    Weight_t = min(target_vol / σ_forecast_t, 1.0)
    Return_t = weight_t * r_SPY_t + (1 - weight_t) * rf
    After transaction costs.
    """
    common = vol_forecast_series.index.intersection(returns_simple.index)
    common = sorted(common)
    if len(common) < 20:
        return None

    weights = []
    strat_returns = []
    turnover = []

    prev_weight = 0.0
    for i, dt in enumerate(common):
        sigma = vol_forecast_series.loc[dt]
        if sigma <= 0 or not np.isfinite(sigma):
            sigma = target_vol_annual  # fallback: weight=1

        w = min(target_vol_annual / sigma, 1.0)
        w = max(w, 0.0)  # no shorting

        # Transaction cost
        turn = abs(w - prev_weight)
        tc = turn * tx_cost_bps / 10000.0

        # Strategy return
        r_spy = float(returns_simple.loc[dt])
        r_strat = w * r_spy + (1 - w) * RF_DAILY - tc

        weights.append(w)
        strat_returns.append(r_strat)
        turnover.append(turn)
        prev_weight = w

    ret_series = pd.Series(strat_returns, index=common)
    weight_series = pd.Series(weights, index=common)

    # Performance metrics
    n = len(ret_series)
    ann_ret = float((1 + ret_series).prod() ** (252 / n) - 1) if n > 0 else 0
    ann_vol = float(ret_series.std() * np.sqrt(252))
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0  # excess over 4% rf

    # Max drawdown
    cum = (1 + ret_series).cumprod()
    peak = cum.expanding().max()
    dd = (cum / peak - 1)
    mdd = float(dd.min())

    # Sortino
    downside = ret_series[ret_series < 0]
    downside_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Calmar
    calmar = (ann_ret - 0.04) / abs(mdd) if mdd != 0 else 0

    # Average weight and turnover
    avg_weight = float(np.mean(weights))
    avg_turnover = float(np.mean(turnover))
    total_turnover = float(np.sum(turnover))

    # Net Sharpe (after TX)
    total_tx = total_turnover * tx_cost_bps / 10000.0
    net_ann_ret = ann_ret - total_tx * 252 / n if n > 0 else ann_ret

    return {
        'strategy': strategy_name,
        'n_days': n,
        'ann_return': round(ann_ret * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 4),
        'sortino': round(sortino, 4),
        'calmar': round(calmar, 4),
        'max_drawdown': round(mdd * 100, 2),
        'avg_weight': round(avg_weight, 4),
        'avg_daily_turnover': round(avg_turnover, 4),
        'total_turnover': round(total_turnover, 2),
        'cum_return': round(float((1 + ret_series).prod() - 1) * 100, 2),
        'returns': ret_series,
        'weights': weight_series,
    }


# ============================================================
# 12/VIX benchmark
# ============================================================
def twelve_over_vix_vol(vix_series, oos_start, oos_end):
    """
    12/VIX heuristic: σ_forecast = VIX/100 (annualized).
    Use previous day's VIX.
    """
    oos_mask = (vix_series.index >= oos_start) & (vix_series.index <= oos_end)
    oos_dates = vix_series.index[oos_mask]
    if len(oos_dates) == 0:
        return pd.Series(dtype=float)

    all_idx = vix_series.index.tolist()
    vol_forecasts = {}
    for dt in oos_dates:
        pos = all_idx.index(dt)
        if pos < 1:
            continue
        prev_vix = float(vix_series.iloc[pos - 1])
        vol_forecasts[dt] = prev_vix / 100.0  # VIX is already annualized %

    return pd.Series(vol_forecasts)


# ============================================================
# DM test for Sharpe comparison (bootstrap-based)
# ============================================================
def bootstrap_sharpe_diff(ret1, ret2, n_bootstrap=10000, seed=42):
    """Bootstrap test for difference in Sharpe ratios."""
    rng = np.random.RandomState(seed)
    r1 = np.asarray(ret1)
    r2 = np.asarray(ret2)
    n = min(len(r1), len(r2))
    r1 = r1[:n]
    r2 = r2[:n]

    def sharpe(r):
        m = r.mean() * 252 - 0.04
        s = r.std() * np.sqrt(252)
        return m / s if s > 0 else 0

    obs_diff = sharpe(r1) - sharpe(r2)

    boot_diffs = []
    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        boot_diffs.append(sharpe(r1[idx]) - sharpe(r2[idx]))

    boot_diffs = np.array(boot_diffs)
    se = np.std(boot_diffs)
    if se > 0:
        t_stat = obs_diff / se
        p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    else:
        t_stat = 0
        p_value = 1.0

    return {
        'sharpe_diff': round(obs_diff, 4),
        't_stat': round(t_stat, 4),
        'p_value': round(p_value, 4),
        'se': round(se, 4),
    }


# ============================================================
# Run all strategies across all OOS periods
# ============================================================
print("\n[2] Running strategies across 5 OOS periods")
print("=" * 70)

all_period_results = {}
pooled_returns = {
    'adaptive': [], 'fixed_2000': [], 'fixed_504': [],
    '12_vix': [], 'buy_hold': []
}

for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    print(f"\n{'='*60}")
    print(f"  {period_name} ({oos_start} to {oos_end})")
    print(f"{'='*60}")

    # VIX regime distribution in this period
    vix_period = vix_close[(vix_close.index >= oos_start) & (vix_close.index <= oos_end)]
    n_calm = int((vix_period < 15).sum())
    n_moderate = int(((vix_period >= 15) & (vix_period <= 25)).sum())
    n_crisis = int((vix_period > 25).sum())
    print(f"  VIX regime: calm={n_calm}, moderate={n_moderate}, crisis={n_crisis}")
    print(f"  VIX mean={vix_period.mean():.1f}, median={vix_period.median():.1f}")

    period_results = {}

    # --- Strategy 1: Adaptive Window VT ---
    t0 = time.time()
    adapt_vol, regime_log = adaptive_window_vol_series(
        ret_pct, vix_close, oos_start, oos_end, refit_every=REFIT_EVERY)
    if len(adapt_vol) > 0:
        bt = vt_backtest(adapt_vol, ret_simple, TARGET_VOL_ANNUAL,
                        tx_cost_bps=TX_COST_BPS, strategy_name="Adaptive Window VT")
        if bt:
            period_results['adaptive'] = bt
            pooled_returns['adaptive'].extend(bt['returns'].values.tolist())
            # Regime distribution in actual trading days
            regime_counts = pd.Series(list(regime_log.values())).value_counts().to_dict()
            period_results['adaptive']['regime_counts'] = {
                k: int(v) for k, v in regime_counts.items()
            }
            elapsed = time.time() - t0
            print(f"  Adaptive VT:  Sharpe={bt['sharpe']:.4f}  "
                  f"Ann.Ret={bt['ann_return']:.2f}%  MDD={bt['max_drawdown']:.2f}%  "
                  f"AvgW={bt['avg_weight']:.3f}  ({elapsed:.1f}s)")

    # --- Strategy 2 & 3: Fixed Window VT ---
    for fw in FIXED_WINDOWS:
        t0 = time.time()
        fixed_vol = gjr_garch_vol_series(
            ret_pct, oos_start, oos_end, window=fw, refit_every=REFIT_EVERY)
        if len(fixed_vol) > 0:
            bt = vt_backtest(fixed_vol, ret_simple, TARGET_VOL_ANNUAL,
                            tx_cost_bps=TX_COST_BPS,
                            strategy_name=f"Fixed W={fw} VT")
            if bt:
                key = f'fixed_{fw}'
                period_results[key] = bt
                pooled_returns[key].extend(bt['returns'].values.tolist())
                elapsed = time.time() - t0
                print(f"  Fixed W={fw}: Sharpe={bt['sharpe']:.4f}  "
                      f"Ann.Ret={bt['ann_return']:.2f}%  MDD={bt['max_drawdown']:.2f}%  "
                      f"AvgW={bt['avg_weight']:.3f}  ({elapsed:.1f}s)")

    # --- Strategy 4: 12/VIX ---
    t0 = time.time()
    vix_vol = twelve_over_vix_vol(vix_close, oos_start, oos_end)
    if len(vix_vol) > 0:
        bt = vt_backtest(vix_vol, ret_simple, TARGET_VOL_ANNUAL,
                        tx_cost_bps=TX_COST_BPS, strategy_name="12/VIX VT")
        if bt:
            period_results['12_vix'] = bt
            pooled_returns['12_vix'].extend(bt['returns'].values.tolist())
            elapsed = time.time() - t0
            print(f"  12/VIX:       Sharpe={bt['sharpe']:.4f}  "
                  f"Ann.Ret={bt['ann_return']:.2f}%  MDD={bt['max_drawdown']:.2f}%  "
                  f"AvgW={bt['avg_weight']:.3f}  ({elapsed:.1f}s)")

    # --- Strategy 5: Buy-and-Hold ---
    oos_mask = (ret_simple.index >= oos_start) & (ret_simple.index <= oos_end)
    bh_ret = ret_simple[oos_mask]
    if len(bh_ret) > 20:
        n = len(bh_ret)
        ann_ret = float((1 + bh_ret).prod() ** (252 / n) - 1)
        ann_vol = float(bh_ret.std() * np.sqrt(252))
        sharpe_bh = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0
        cum_bh = (1 + bh_ret).cumprod()
        mdd_bh = float((cum_bh / cum_bh.expanding().max() - 1).min())

        period_results['buy_hold'] = {
            'strategy': 'Buy-and-Hold SPY',
            'n_days': n,
            'ann_return': round(ann_ret * 100, 2),
            'ann_vol': round(ann_vol * 100, 2),
            'sharpe': round(sharpe_bh, 4),
            'max_drawdown': round(mdd_bh * 100, 2),
            'avg_weight': 1.0,
            'returns': bh_ret,
        }
        pooled_returns['buy_hold'].extend(bh_ret.values.tolist())
        print(f"  Buy&Hold:     Sharpe={sharpe_bh:.4f}  "
              f"Ann.Ret={ann_ret*100:.2f}%  MDD={mdd_bh*100:.2f}%")

    all_period_results[period_name] = period_results


# ============================================================
# [3] Cross-OOS Summary
# ============================================================
print("\n" + "=" * 70)
print("[3] Cross-OOS Summary: Sharpe Ratios")
print("=" * 70)

strategies = ['adaptive', 'fixed_2000', 'fixed_504', '12_vix', 'buy_hold']
strat_labels = {
    'adaptive': 'Adaptive VT',
    'fixed_2000': 'Fixed W=2000',
    'fixed_504': 'Fixed W=504',
    '12_vix': '12/VIX',
    'buy_hold': 'Buy&Hold',
}

# Print Sharpe table
header = f"{'Period':<20s}"
for s in strategies:
    header += f"{strat_labels[s]:>14s}"
print(header)
print("-" * (20 + 14 * len(strategies)))

sharpe_by_strat = {s: [] for s in strategies}
win_count = {s: 0 for s in strategies}

for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    line = f"{period_name:<20s}"
    best_sharpe = -999
    best_strat = None
    for s in strategies:
        if s in pr and 'sharpe' in pr[s]:
            sh = pr[s]['sharpe']
            sharpe_by_strat[s].append(sh)
            line += f"{sh:>14.4f}"
            if sh > best_sharpe:
                best_sharpe = sh
                best_strat = s
        else:
            line += f"{'N/A':>14s}"
    if best_strat:
        win_count[best_strat] += 1
        line += f"  ← {strat_labels.get(best_strat, best_strat)}"
    print(line)

# Mean Sharpe
print("-" * (20 + 14 * len(strategies)))
line = f"{'Mean':<20s}"
for s in strategies:
    vals = sharpe_by_strat[s]
    if vals:
        line += f"{np.mean(vals):>14.4f}"
    else:
        line += f"{'N/A':>14s}"
print(line)

line = f"{'Std':<20s}"
for s in strategies:
    vals = sharpe_by_strat[s]
    if len(vals) > 1:
        line += f"{np.std(vals, ddof=1):>14.4f}"
    else:
        line += f"{'N/A':>14s}"
print(line)

line = f"{'Win Count':<20s}"
for s in strategies:
    line += f"{win_count[s]:>14d}"
print(line)


# ============================================================
# [4] Return & MDD table
# ============================================================
print("\n" + "=" * 70)
print("[4] Cumulative Returns & Max Drawdown")
print("=" * 70)

header = f"{'Period':<20s}"
for s in strategies:
    header += f"{strat_labels[s]:>14s}"
print(header)
print("-" * (20 + 14 * len(strategies)))

for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    line = f"{period_name:<20s}"
    for s in strategies:
        if s in pr:
            cr = pr[s].get('cum_return', pr[s].get('ann_return', 0))
            mdd = pr[s].get('max_drawdown', 0)
            line += f"  {cr:>5.1f}/{mdd:>5.1f}"
        else:
            line += f"{'N/A':>14s}"
    print(line)
print("(Format: Cum.Return% / MDD%)")


# ============================================================
# [5] Statistical Tests: Adaptive vs each benchmark
# ============================================================
print("\n" + "=" * 70)
print("[5] Bootstrap Sharpe Difference Tests (Adaptive vs Benchmarks)")
print("=" * 70)

stat_tests = {}
for benchmark in ['fixed_2000', 'fixed_504', '12_vix', 'buy_hold']:
    # Pooled test across all OOS
    r_adapt = np.array(pooled_returns['adaptive'])
    r_bench = np.array(pooled_returns[benchmark])
    min_len = min(len(r_adapt), len(r_bench))

    if min_len > 100:
        result = bootstrap_sharpe_diff(r_adapt[:min_len], r_bench[:min_len])
        sig = "***" if result['p_value'] < 0.01 else \
              ("**" if result['p_value'] < 0.05 else \
               ("*" if result['p_value'] < 0.10 else "n.s."))
        stat_tests[f'adaptive_vs_{benchmark}'] = result
        better = "Adaptive" if result['sharpe_diff'] > 0 else strat_labels[benchmark]
        print(f"  Adaptive vs {strat_labels[benchmark]:>14s}: "
              f"ΔSharpe={result['sharpe_diff']:+.4f}  "
              f"t={result['t_stat']:+.4f}  p={result['p_value']:.4f} {sig}  "
              f"→ {better}")

        # Harvey (2016) threshold
        harvey = abs(result['t_stat']) > 3.0
        print(f"    Harvey t>3.0: {'PASS' if harvey else 'FAIL'} (|t|={abs(result['t_stat']):.2f})")


# ============================================================
# [6] Per-period pairwise tests
# ============================================================
print("\n" + "=" * 70)
print("[6] Per-Period Tests: Adaptive vs Fixed W=2000")
print("=" * 70)

period_tests = {}
for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    if 'adaptive' in pr and 'fixed_2000' in pr:
        r1 = pr['adaptive']['returns'].values
        r2 = pr['fixed_2000']['returns'].values
        min_len = min(len(r1), len(r2))
        if min_len > 50:
            result = bootstrap_sharpe_diff(r1[:min_len], r2[:min_len], n_bootstrap=5000)
            better = "Adaptive" if result['sharpe_diff'] > 0 else "W=2000"
            sig = "***" if result['p_value'] < 0.01 else \
                  ("**" if result['p_value'] < 0.05 else \
                   ("*" if result['p_value'] < 0.10 else "n.s."))
            period_tests[period_name] = result
            print(f"  {period_name}: ΔSharpe={result['sharpe_diff']:+.4f}  "
                  f"t={result['t_stat']:+.4f}  p={result['p_value']:.4f} {sig}  → {better}")


# ============================================================
# [7] Regime analysis: when does adaptive actually differ?
# ============================================================
print("\n" + "=" * 70)
print("[7] Regime Analysis: When Does Adaptive Differ from Fixed?")
print("=" * 70)

for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    if 'adaptive' not in pr:
        continue
    rc = pr['adaptive'].get('regime_counts', {})
    total = sum(rc.values()) if rc else 0
    print(f"\n  {period_name}:")
    for regime in ['calm', 'moderate', 'crisis']:
        cnt = rc.get(regime, 0)
        pct = cnt / total * 100 if total > 0 else 0
        w = REGIME_CONFIG[regime]['window']
        print(f"    {regime:>10s}: {cnt:>4d} days ({pct:>5.1f}%) → W={w}")

    # Compute weight difference between adaptive and fixed W=2000
    if 'fixed_2000' in pr:
        w_adapt = pr['adaptive'].get('weights', pd.Series())
        w_fixed = pr['fixed_2000'].get('weights', pd.Series())
        if len(w_adapt) > 0 and len(w_fixed) > 0:
            common = w_adapt.index.intersection(w_fixed.index)
            diff = w_adapt.loc[common] - w_fixed.loc[common]
            print(f"    Weight diff (adaptive - fixed_2000):")
            print(f"      Mean={diff.mean():+.4f}  Std={diff.std():.4f}  "
                  f"Max={diff.max():+.4f}  Min={diff.min():+.4f}")
            print(f"      Correlation: {w_adapt.loc[common].corr(w_fixed.loc[common]):.4f}")


# ============================================================
# [8] Turnover comparison
# ============================================================
print("\n" + "=" * 70)
print("[8] Turnover Comparison (total turnover per period)")
print("=" * 70)

header = f"{'Period':<20s}"
for s in ['adaptive', 'fixed_2000', 'fixed_504', '12_vix']:
    header += f"{strat_labels[s]:>14s}"
print(header)
print("-" * (20 + 14 * 4))

for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    line = f"{period_name:<20s}"
    for s in ['adaptive', 'fixed_2000', 'fixed_504', '12_vix']:
        if s in pr:
            to = pr[s].get('total_turnover', 0)
            line += f"{to:>14.2f}"
        else:
            line += f"{'N/A':>14s}"
    print(line)


# ============================================================
# [9] Final Verdict
# ============================================================
print("\n" + "=" * 70)
print("[9] FINAL VERDICT")
print("=" * 70)

# Count periods where adaptive beats fixed_2000
n_adaptive_wins = 0
n_periods_tested = 0
for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    if 'adaptive' in pr and 'fixed_2000' in pr:
        n_periods_tested += 1
        if pr['adaptive']['sharpe'] > pr['fixed_2000']['sharpe']:
            n_adaptive_wins += 1

print(f"\n  Adaptive wins {n_adaptive_wins}/{n_periods_tested} periods vs Fixed W=2000")

# Pooled Sharpe
if pooled_returns['adaptive'] and pooled_returns['fixed_2000']:
    r_a = np.array(pooled_returns['adaptive'])
    r_f = np.array(pooled_returns['fixed_2000'])
    sh_a = (r_a.mean() * 252 - 0.04) / (r_a.std() * np.sqrt(252)) if r_a.std() > 0 else 0
    sh_f = (r_f.mean() * 252 - 0.04) / (r_f.std() * np.sqrt(252)) if r_f.std() > 0 else 0
    print(f"  Pooled Sharpe: Adaptive={sh_a:.4f}, Fixed_2000={sh_f:.4f}")
    print(f"  Sharpe difference: {sh_a - sh_f:+.4f}")

# Key insight
pooled_test = stat_tests.get('adaptive_vs_fixed_2000', {})
if pooled_test:
    if abs(pooled_test.get('t_stat', 0)) > 3.0:
        if pooled_test.get('sharpe_diff', 0) > 0:
            verdict = "SIGNIFICANT: Adaptive window VT beats Fixed W=2000 (Harvey t>3.0)."
        else:
            verdict = "SIGNIFICANT: Fixed W=2000 beats Adaptive window VT (Harvey t>3.0)."
    elif pooled_test.get('p_value', 1) < 0.05:
        better = "Adaptive" if pooled_test.get('sharpe_diff', 0) > 0 else "Fixed W=2000"
        verdict = f"MARGINAL: {better} better at p<0.05, but fails Harvey t>3.0 threshold."
    else:
        verdict = ("NULL RESULT: No significant difference between Adaptive and Fixed W=2000. "
                   "Regime-switching the estimation window does NOT improve VT performance.")
else:
    verdict = "INSUFFICIENT DATA for verdict."

print(f"\n  >>> {verdict}")

# Answer the key question
print(f"\n  KEY QUESTION ANSWER:")
print(f"  'Does regime-switching the ESTIMATION WINDOW improve VT?'")
if 'adaptive_vs_fixed_2000' in stat_tests:
    t = stat_tests['adaptive_vs_fixed_2000'].get('t_stat', 0)
    p = stat_tests['adaptive_vs_fixed_2000'].get('p_value', 1)
    d = stat_tests['adaptive_vs_fixed_2000'].get('sharpe_diff', 0)
    if abs(t) > 3.0 and d > 0:
        print(f"  → YES, regime-adaptive window significantly improves VT (t={t:.2f}, p={p:.4f})")
    elif p < 0.05 and d > 0:
        print(f"  → WEAK YES, marginally significant (t={t:.2f}, p={p:.4f}) but fails Harvey")
    elif d > 0:
        print(f"  → NO, small positive but insignificant (t={t:.2f}, p={p:.4f})")
    else:
        print(f"  → NO, adaptive is not better (t={t:.2f}, p={p:.4f})")


# ============================================================
# Save results
# ============================================================
elapsed_total = time.time() - t0_total
print(f"\n{'='*70}")
print(f"Total elapsed: {elapsed_total:.1f}s")

# Prepare serializable results
serializable = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Adaptive Window VT Strategy — Regime-Dependent Estimation Window",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "data_source": "yfinance",
    "asset": "SPY",
    "model": "GJR-GARCH(1,1)-t",
    "regime_config": {k: {"vix_upper": v['vix_upper'], "window": v['window']}
                      for k, v in REGIME_CONFIG.items()},
    "target_vol_annual": TARGET_VOL_ANNUAL,
    "tx_cost_bps": TX_COST_BPS,
    "refit_every": REFIT_EVERY,
    "oos_periods": {k: {"start": v[0], "end": v[1]} for k, v in OOS_PERIODS.items()},
    "per_period_results": {},
    "sharpe_summary": {
        "mean_sharpe": {strat_labels.get(s, s): round(np.mean(sharpe_by_strat[s]), 4)
                        if sharpe_by_strat[s] else None
                        for s in strategies},
        "win_counts": {strat_labels.get(s, s): win_count[s] for s in strategies},
    },
    "statistical_tests_pooled": stat_tests,
    "per_period_tests_vs_fixed2000": {
        k: v for k, v in period_tests.items()
    },
    "verdict": verdict,
    "key_question": "Does regime-switching the ESTIMATION WINDOW improve VT?",
    "references": [
        "K593: Window Cross-OOS — regime-dependent, no universal winner",
        "K591: Window Size Sensitivity Sweep (W=504 best in 2023-24)",
        "K406/K408: W=2000 upgrade based on persistence bias",
        "Feng & Zhang (2025) J.Forecasting — U-shape window",
        "Moreira & Muir (2017) JF — Volatility-managed portfolios",
        "Fleming, Kirby & Ostdiek (2001) JFE — Economic value of vol timing",
    ],
}

# Add per-period details (without non-serializable return series)
for period_name in OOS_PERIODS:
    pr = all_period_results.get(period_name, {})
    period_data = {}
    for s in strategies:
        if s in pr:
            pd_copy = {k: v for k, v in pr[s].items()
                       if k not in ['returns', 'weights']}
            period_data[strat_labels.get(s, s)] = pd_copy
    serializable['per_period_results'][period_name] = period_data

out_path = f"{MAIN_REPO}/experiments/k594_adaptive_window_vt_results.json"
with open(out_path, 'w') as f:
    json.dump(serializable, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

# Also save script
import shutil
script_src = __file__
script_dst = f"{MAIN_REPO}/experiments/k594_adaptive_window_vt.py"
if script_src != script_dst:
    try:
        shutil.copy2(script_src, script_dst)
        print(f"Script copied to {script_dst}")
    except Exception:
        pass

print(f"\n{'='*70}")
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
