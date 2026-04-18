#!/usr/bin/env python3
"""
K593: Window Size Cross-OOS Validation — Is W=504 really better than W=2000?
=============================================================================
[提出: 用戶, 執行: Claude]

Critical context:
  K591 found W=504 beats W=2000 by 6.6% (DM=3.68) in OOS 2023-2024.
  This contradicts our W=2000 choice AND Feng & Zhang (2025).
  BUT it was only 1 OOS period — classic data snooping risk.
  This experiment validates with 5 non-overlapping OOS periods.

Design:
  1. Data: SPY from yfinance (2005-2026)
  2. Model: GJR-GARCH(1,1)-t at W=252, 504, 1000, 2000
  3. 5 non-overlapping OOS periods:
     - OOS1: 2012-2013 (post-GFC recovery, low vol)
     - OOS2: 2014-2015 (taper tantrum, oil crash)
     - OOS3: 2016-2017 (extremely low vol, Trump rally)
     - OOS4: 2020-2021 (COVID crash + recovery, extreme vol)
     - OOS5: 2023-2024 (rate hikes, AI rally, moderate vol)
  4. For each OOS period, compute QLIKE for each window
  5. Cross-OOS analysis:
     - Which window wins most periods?
     - Mean QLIKE rank across periods
     - Paired t-test: W=504 vs W=2000 across all OOS days
     - DM test per period and pooled
  6. VIX regime analysis: does the winner depend on market regime?

Decision rule:
  - If W=504 wins ≥4/5 periods AND pooled DM significant → revise W=2000 conclusion
  - If W=504 wins ≤2/5 periods → K591 was period-specific, keep W=2000
  - If mixed (3/5) → report as "regime-dependent, no universal winner"

Data source: yfinance (SPY daily close, 2005-01-03 to 2026-03-27)
References:
  Feng & Zhang (2025) "Forecasting Volatility" J.Forecasting — U-shape, W=1000-2000 optimal
  Hillebrand (2005) "Neglecting parameter changes in GARCH models" — persistence bias
  Hansen & Lunde (2005) J.Applied Econometrics — QLIKE
  Patton (2011) JoE — imperfect proxies
  K591: Window Size Sensitivity Sweep (single OOS 2023-24, W=504 best)
  K406/K408: w=2000 upgrade based on persistence bias
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
EXPERIMENT_ID = "K593"
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

# Window sizes to test (focused set for cross-OOS)
WINDOWS = [252, 504, 1000, 2000]

# 5 non-overlapping OOS periods
OOS_PERIODS = {
    'OOS1_2012-2013': ('2012-01-01', '2013-12-31'),
    'OOS2_2014-2015': ('2014-01-01', '2015-12-31'),
    'OOS3_2016-2017': ('2016-01-01', '2017-12-31'),
    'OOS4_2020-2021': ('2020-01-01', '2021-12-31'),
    'OOS5_2023-2024': ('2023-01-01', '2024-12-31'),
}

# Refit frequency
REFIT_EVERY = 21

print("=" * 70)
print(f"{EXPERIMENT_ID}: Window Size Cross-OOS Validation")
print("  Is W=504 really better than W=2000?")
print(f"  Windows: {WINDOWS}")
print(f"  OOS periods: {len(OOS_PERIODS)}")
print("=" * 70)
print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
t0_total = time.time()


# ============================================================
# Data download
# ============================================================
print("\n[1] Downloading SPY data...")
df = yf.download('SPY', start='2003-01-01', end='2026-03-28',
                 progress=False, auto_adjust=True)
if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
    df.columns = df.columns.get_level_values(0)

close = df['Close'].dropna()
ret = np.log(close / close.shift(1)).dropna() * 100  # log returns in %
print(f"  SPY: {len(ret)} daily returns ({ret.index[0].date()} to {ret.index[-1].date()})")
print(f"  Mean={ret.mean():.4f}%, Std={ret.std():.4f}%")
print(f"  Skew={ret.skew():.3f}, Kurt={ret.kurtosis():.3f}")

# Download VIX for regime analysis
print("  Downloading VIX for regime analysis...")
vix_df = yf.download('^VIX', start='2003-01-01', end='2026-03-28',
                     progress=False, auto_adjust=True)
if hasattr(vix_df.columns, 'nlevels') and vix_df.columns.nlevels > 1:
    vix_df.columns = vix_df.columns.get_level_values(0)
vix = vix_df['Close'].dropna()
print(f"  VIX: {len(vix)} days")


# ============================================================
# Loss functions
# ============================================================
def qlike_loss(realized, forecast):
    """QLIKE loss: E[rv/fv - log(rv/fv) - 1]. Lower is better."""
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return float(np.mean(rv / fv - np.log(rv / fv) - 1))


def qlike_per_day(realized, forecast):
    """Per-day QLIKE losses for DM test."""
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return rv / fv - np.log(rv / fv) - 1


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC.
    Returns (DM stat, p-value). Negative DM = model1 better."""
    d = np.asarray(loss1) - np.asarray(loss2)
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)

    # Newey-West HAC variance with bandwidth = h-1
    gamma0 = np.var(d, ddof=0)
    nw_var = gamma0
    for k in range(1, max(h, 2)):
        if len(d) > k:
            gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            nw_var += 2 * (1 - k / max(h, 2)) * gamma_k

    se = np.sqrt(max(nw_var, 1e-15) / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return float(dm_stat), float(p_value)


# ============================================================
# GJR-GARCH rolling forecast
# ============================================================
def gjr_garch_rolling(returns, oos_start, oos_end, window, refit_every=21):
    """Rolling GJR-GARCH(1,1)-t forecast for a given OOS period and window."""
    oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
    oos_dates = returns.index[oos_mask]

    if len(oos_dates) == 0:
        return None

    forecasts = {}
    realized = {}
    persistence_list = []
    convergence_count = 0
    total_fits = 0

    all_idx = returns.index.tolist()
    oos_idx_set = set(oos_dates.tolist())

    last_model = None
    days_since_fit = refit_every  # force fit on first day

    for dt in all_idx:
        if dt not in oos_idx_set:
            continue

        pos = all_idx.index(dt)
        if pos < window:
            continue

        train = returns.iloc[pos - window:pos]

        days_since_fit += 1
        need_refit = (days_since_fit >= refit_every) or (last_model is None)

        if need_refit:
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                                dist='t', mean='Zero', rescale=False)
                res = am.fit(disp='off', show_warning=False)

                total_fits += 1
                if res.convergence_flag == 0:
                    convergence_count += 1

                last_model = res
                params = res.params
                alpha = params.get('alpha[1]', 0)
                beta = params.get('beta[1]', 0)
                gamma = params.get('gamma[1]', 0)
                pers = alpha + beta + gamma / 2
                persistence_list.append(pers)

                days_since_fit = 0
            except Exception:
                pass

        if last_model is not None:
            try:
                fcast = last_model.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                if h > 0 and np.isfinite(h):
                    forecasts[dt] = h
                    realized[dt] = returns.loc[dt] ** 2
            except Exception:
                pass

    common_dates = sorted(set(forecasts.keys()) & set(realized.keys()))
    if len(common_dates) == 0:
        return None

    fv = np.array([forecasts[d] for d in common_dates])
    rv = np.array([realized[d] for d in common_dates])

    conv_rate = convergence_count / total_fits if total_fits > 0 else 0
    avg_pers = float(np.mean(persistence_list)) if persistence_list else float('nan')

    return {
        'dates': common_dates,
        'forecasts': fv,
        'realized': rv,
        'n_forecasts': len(common_dates),
        'convergence_rate': float(conv_rate),
        'total_fits': total_fits,
        'avg_persistence': avg_pers,
    }


# ============================================================
# Run cross-OOS validation
# ============================================================
print("\n[2] Running Cross-OOS Validation")
print("=" * 70)

# Store results: {period_name: {window: {qlike, losses, ...}}}
all_results = {}
# Store per-day losses for pooled DM test: {window: [all losses across periods]}
pooled_losses = {w: [] for w in WINDOWS}

for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    print(f"\n--- {period_name} ({oos_start} to {oos_end}) ---")
    period_results = {}

    for w in WINDOWS:
        t0 = time.time()
        res = gjr_garch_rolling(ret, oos_start, oos_end, window=w,
                                refit_every=REFIT_EVERY)

        if res is not None and res['n_forecasts'] > 0:
            ql = qlike_loss(res['realized'], res['forecasts'])
            per_day = qlike_per_day(res['realized'], res['forecasts'])

            period_results[w] = {
                'qlike': ql,
                'n_forecasts': res['n_forecasts'],
                'convergence_rate': res['convergence_rate'],
                'avg_persistence': res['avg_persistence'],
                'per_day_losses': per_day,
                'dates': res['dates'],
                'forecasts': res['forecasts'],
                'realized': res['realized'],
            }
            pooled_losses[w].extend(per_day.tolist())

            elapsed = time.time() - t0
            print(f"  W={w:>5d}: QLIKE={ql:.6f}  n={res['n_forecasts']}  "
                  f"pers={res['avg_persistence']:.4f}  ({elapsed:.1f}s)")
        else:
            print(f"  W={w:>5d}: FAILED (insufficient data)")

    all_results[period_name] = period_results


# ============================================================
# Analysis 1: Per-period ranking
# ============================================================
print("\n" + "=" * 70)
print("[3] Per-Period Ranking Analysis")
print("=" * 70)

# Build ranking table
ranking_table = {}  # {period: {window: rank}}
win_count = {w: 0 for w in WINDOWS}
qlike_table = {}

for period_name in OOS_PERIODS:
    pr = all_results[period_name]
    if not pr:
        continue

    # Sort windows by QLIKE (lower = better)
    sorted_windows = sorted(pr.keys(), key=lambda w: pr[w]['qlike'])
    qlike_table[period_name] = {w: pr[w]['qlike'] for w in WINDOWS if w in pr}

    ranking_table[period_name] = {}
    for rank, w in enumerate(sorted_windows, 1):
        ranking_table[period_name][w] = rank
        if rank == 1:
            win_count[w] += 1

# Print ranking table
print(f"\n{'Period':<20s}", end="")
for w in WINDOWS:
    print(f"{'W='+str(w):>12s}", end="")
print(f"{'Winner':>10s}")
print("-" * (20 + 12 * len(WINDOWS) + 10))

for period_name in OOS_PERIODS:
    if period_name not in ranking_table:
        continue
    print(f"{period_name:<20s}", end="")
    winner_w = None
    best_ql = float('inf')
    for w in WINDOWS:
        if w in qlike_table.get(period_name, {}):
            ql = qlike_table[period_name][w]
            rank = ranking_table[period_name].get(w, '-')
            print(f"{ql:>10.6f}({rank})", end="")
            if ql < best_ql:
                best_ql = ql
                winner_w = w
        else:
            print(f"{'N/A':>12s}", end="")
    print(f"{'W='+str(winner_w):>10s}" if winner_w else "")

# Mean rank
print(f"\n{'Mean rank':<20s}", end="")
for w in WINDOWS:
    ranks = [ranking_table[p].get(w, len(WINDOWS)) for p in ranking_table]
    mean_rank = np.mean(ranks) if ranks else float('nan')
    print(f"{mean_rank:>12.2f}", end="")
print()

print(f"{'Win count':<20s}", end="")
for w in WINDOWS:
    print(f"{win_count[w]:>12d}", end="")
print()


# ============================================================
# Analysis 2: DM tests per period (W=504 vs W=2000)
# ============================================================
print("\n" + "=" * 70)
print("[4] DM Tests: W=504 vs W=2000 per Period")
print("=" * 70)

dm_per_period = {}
for period_name in OOS_PERIODS:
    pr = all_results[period_name]
    if 504 not in pr or 2000 not in pr:
        continue

    loss_504 = pr[504]['per_day_losses']
    loss_2000 = pr[2000]['per_day_losses']
    min_len = min(len(loss_504), len(loss_2000))

    dm_stat, p_val = dm_test(loss_504[:min_len], loss_2000[:min_len])
    better = "W=504" if dm_stat < 0 else "W=2000"
    sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else "n.s."))

    dm_per_period[period_name] = {
        'dm_stat': dm_stat,
        'p_value': p_val,
        'better': better,
        'significant': sig,
        'n_days': min_len,
    }

    # Calculate QLIKE advantage
    ql_504 = pr[504]['qlike']
    ql_2000 = pr[2000]['qlike']
    advantage_pct = (ql_2000 - ql_504) / ql_2000 * 100

    print(f"  {period_name}: DM={dm_stat:+.4f} p={p_val:.4f} {sig:>5s}  "
          f"→ {better} better  (504 advantage: {advantage_pct:+.2f}%)")


# ============================================================
# Analysis 3: Pooled DM test across all periods
# ============================================================
print("\n" + "=" * 70)
print("[5] Pooled DM Test (all 5 OOS periods combined)")
print("=" * 70)

pooled_dm_results = {}
if pooled_losses[504] and pooled_losses[2000]:
    p504 = np.array(pooled_losses[504])
    p2000 = np.array(pooled_losses[2000])
    min_len = min(len(p504), len(p2000))

    dm_stat, p_val = dm_test(p504[:min_len], p2000[:min_len])
    better = "W=504" if dm_stat < 0 else "W=2000"
    sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else "n.s."))

    pooled_dm_results = {
        'dm_stat': dm_stat,
        'p_value': p_val,
        'better': better,
        'significant': sig,
        'n_total_days': min_len,
    }

    print(f"  Pooled W=504 vs W=2000: DM={dm_stat:+.4f} p={p_val:.4f} {sig}")
    print(f"  → {better} better across {min_len} total OOS days")
    print(f"  Mean QLIKE: W=504={np.mean(p504):.6f}, W=2000={np.mean(p2000):.6f}")
    print(f"  Advantage: {(np.mean(p2000) - np.mean(p504)) / np.mean(p2000) * 100:+.2f}%")

# Also test all pairs
print("\n  All pairwise pooled DM tests:")
all_pooled_dm = {}
for w1 in WINDOWS:
    for w2 in WINDOWS:
        if w1 >= w2:
            continue
        if pooled_losses[w1] and pooled_losses[w2]:
            p1 = np.array(pooled_losses[w1])
            p2 = np.array(pooled_losses[w2])
            min_len = min(len(p1), len(p2))
            dm_stat, p_val = dm_test(p1[:min_len], p2[:min_len])
            better = f"W={w1}" if dm_stat < 0 else f"W={w2}"
            sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else ""))
            all_pooled_dm[f"{w1}_vs_{w2}"] = {
                'dm_stat': dm_stat,
                'p_value': p_val,
                'better': better,
                'significant': sig,
            }
            print(f"    W={w1} vs W={w2}: DM={dm_stat:+.4f} p={p_val:.4f} {sig:>4s} → {better}")


# ============================================================
# Analysis 4: VIX regime analysis
# ============================================================
print("\n" + "=" * 70)
print("[6] VIX Regime Analysis")
print("=" * 70)

# Classify each OOS period by average VIX
regime_analysis = {}
for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    vix_period = vix[(vix.index >= oos_start) & (vix.index <= oos_end)]
    if len(vix_period) == 0:
        continue

    avg_vix = float(vix_period.mean())
    max_vix = float(vix_period.max())
    std_ret = float(ret[(ret.index >= oos_start) & (ret.index <= oos_end)].std())

    regime = "crisis" if avg_vix > 25 else ("elevated" if avg_vix > 20 else "calm")

    # Best window for this period
    pr = all_results.get(period_name, {})
    if pr:
        best_w = min(pr.keys(), key=lambda w: pr[w]['qlike'])
    else:
        best_w = None

    regime_analysis[period_name] = {
        'avg_vix': avg_vix,
        'max_vix': max_vix,
        'std_ret': std_ret,
        'regime': regime,
        'best_window': best_w,
    }

    print(f"  {period_name}: VIX_avg={avg_vix:.1f} VIX_max={max_vix:.1f} "
          f"σ_ret={std_ret:.2f}% regime={regime:>8s} → best W={best_w}")

# Within-period regime split for OOS4 (COVID) and OOS5
print("\n  Within-period VIX regime split (calm VIX<20 vs elevated VIX≥20):")
for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    pr = all_results.get(period_name, {})
    if not pr or 504 not in pr or 2000 not in pr:
        continue

    # Get VIX for each forecast day
    dates_504 = pr[504]['dates']
    dates_2000 = pr[2000]['dates']
    common_dates = sorted(set(dates_504) & set(dates_2000))

    if len(common_dates) < 20:
        continue

    # Split by VIX regime
    calm_idx = []
    elevated_idx = []
    for i, d in enumerate(common_dates):
        if d in vix.index:
            v = vix.loc[d]
            if hasattr(v, 'item'):
                v = v.item()
            if v < 20:
                calm_idx.append(i)
            else:
                elevated_idx.append(i)

    # Get per-day losses aligned to common_dates
    loss_504_dict = dict(zip(pr[504]['dates'],
                              qlike_per_day(pr[504]['realized'], pr[504]['forecasts'])))
    loss_2000_dict = dict(zip(pr[2000]['dates'],
                               qlike_per_day(pr[2000]['realized'], pr[2000]['forecasts'])))

    calm_504 = [loss_504_dict[common_dates[i]] for i in calm_idx if common_dates[i] in loss_504_dict]
    calm_2000 = [loss_2000_dict[common_dates[i]] for i in calm_idx if common_dates[i] in loss_2000_dict]
    elev_504 = [loss_504_dict[common_dates[i]] for i in elevated_idx if common_dates[i] in loss_504_dict]
    elev_2000 = [loss_2000_dict[common_dates[i]] for i in elevated_idx if common_dates[i] in loss_2000_dict]

    if len(calm_504) > 10 and len(calm_2000) > 10:
        min_len = min(len(calm_504), len(calm_2000))
        dm_calm, p_calm = dm_test(np.array(calm_504[:min_len]), np.array(calm_2000[:min_len]))
        better_calm = "W=504" if dm_calm < 0 else "W=2000"
        sig_calm = "***" if p_calm < 0.01 else ("**" if p_calm < 0.05 else ("*" if p_calm < 0.10 else ""))
    else:
        dm_calm, p_calm, better_calm, sig_calm = 0, 1, "N/A", ""

    if len(elev_504) > 10 and len(elev_2000) > 10:
        min_len = min(len(elev_504), len(elev_2000))
        dm_elev, p_elev = dm_test(np.array(elev_504[:min_len]), np.array(elev_2000[:min_len]))
        better_elev = "W=504" if dm_elev < 0 else "W=2000"
        sig_elev = "***" if p_elev < 0.01 else ("**" if p_elev < 0.05 else ("*" if p_elev < 0.10 else ""))
    else:
        dm_elev, p_elev, better_elev, sig_elev = 0, 1, "N/A", ""

    print(f"  {period_name}:")
    print(f"    Calm  (VIX<20, n={len(calm_idx)}): DM={dm_calm:+.3f} p={p_calm:.3f} {sig_calm} → {better_calm}")
    print(f"    Elev  (VIX≥20, n={len(elevated_idx)}): DM={dm_elev:+.3f} p={p_elev:.3f} {sig_elev} → {better_elev}")


# ============================================================
# Analysis 5: Persistence bias by period
# ============================================================
print("\n" + "=" * 70)
print("[7] Persistence Bias Across Periods")
print("=" * 70)

for period_name in OOS_PERIODS:
    pr = all_results.get(period_name, {})
    if not pr:
        continue
    print(f"  {period_name}:", end="")
    for w in WINDOWS:
        if w in pr:
            print(f"  W={w}:{pr[w]['avg_persistence']:.4f}", end="")
    print()


# ============================================================
# Final verdict
# ============================================================
print("\n" + "=" * 70)
print("[8] FINAL VERDICT")
print("=" * 70)

# Count wins
print(f"\n  Win counts: ", end="")
for w in WINDOWS:
    print(f"W={w}={win_count[w]}  ", end="")
print()

# Mean ranks
mean_ranks = {}
for w in WINDOWS:
    ranks = [ranking_table[p].get(w, len(WINDOWS)) for p in ranking_table]
    mean_ranks[w] = np.mean(ranks) if ranks else float('nan')

print(f"  Mean ranks: ", end="")
for w in WINDOWS:
    print(f"W={w}={mean_ranks[w]:.2f}  ", end="")
print()

# Best by mean rank
best_by_rank = min(mean_ranks, key=lambda w: mean_ranks[w])
print(f"\n  Best window by mean rank: W={best_by_rank}")

# DM test summary
n_504_wins = sum(1 for p in dm_per_period.values() if p['better'] == 'W=504')
n_504_sig_wins = sum(1 for p in dm_per_period.values()
                     if p['better'] == 'W=504' and p['p_value'] < 0.05)
n_2000_wins = sum(1 for p in dm_per_period.values() if p['better'] == 'W=2000')
n_2000_sig_wins = sum(1 for p in dm_per_period.values()
                      if p['better'] == 'W=2000' and p['p_value'] < 0.05)

print(f"\n  DM test results (W=504 vs W=2000):")
print(f"    W=504 wins: {n_504_wins}/5 periods ({n_504_sig_wins} significant at 5%)")
print(f"    W=2000 wins: {n_2000_wins}/5 periods ({n_2000_sig_wins} significant at 5%)")

if pooled_dm_results:
    print(f"    Pooled: DM={pooled_dm_results['dm_stat']:+.4f} p={pooled_dm_results['p_value']:.4f} "
          f"→ {pooled_dm_results['better']}")

# Decision
print(f"\n  DECISION LOGIC:")
if n_504_wins >= 4:
    if pooled_dm_results and pooled_dm_results['p_value'] < 0.05 and pooled_dm_results['better'] == 'W=504':
        verdict = "REVISE: W=504 robustly better across periods. Change paper to W=504."
    else:
        verdict = "TENTATIVE: W=504 wins most periods but pooled test not significant. Report both."
elif n_504_wins <= 2:
    verdict = "KEEP W=2000: K591 was period-specific. W=2000 remains our choice."
else:  # 3/5
    verdict = "MIXED: Regime-dependent, no universal winner. Report as asset/period-specific."

print(f"  >>> {verdict}")


# ============================================================
# Save results
# ============================================================
elapsed_total = time.time() - t0_total
print(f"\n{'='*70}")
print(f"Total elapsed: {elapsed_total:.1f}s")

# Prepare serializable results
serializable_qlike = {}
for period_name in OOS_PERIODS:
    serializable_qlike[period_name] = {}
    pr = all_results.get(period_name, {})
    for w in WINDOWS:
        if w in pr:
            serializable_qlike[period_name][str(w)] = {
                'qlike': pr[w]['qlike'],
                'n_forecasts': pr[w]['n_forecasts'],
                'convergence_rate': pr[w]['convergence_rate'],
                'avg_persistence': pr[w]['avg_persistence'],
            }

serializable_rankings = {}
for period_name in ranking_table:
    serializable_rankings[period_name] = {str(w): r for w, r in ranking_table[period_name].items()}

results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Window Size Cross-OOS Validation — Is W=504 really better than W=2000?",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "data_source": "yfinance",
    "asset": "SPY",
    "model": "GJR-GARCH(1,1)-t",
    "windows_tested": WINDOWS,
    "refit_every": REFIT_EVERY,
    "oos_periods": {k: {"start": v[0], "end": v[1]} for k, v in OOS_PERIODS.items()},
    "qlike_by_period_and_window": serializable_qlike,
    "rankings_by_period": serializable_rankings,
    "win_counts": {str(w): win_count[w] for w in WINDOWS},
    "mean_ranks": {str(w): float(mean_ranks[w]) for w in WINDOWS},
    "dm_tests_504_vs_2000_per_period": {
        k: {kk: vv for kk, vv in v.items() if kk != 'n_days' or True}
        for k, v in dm_per_period.items()
    },
    "pooled_dm_test_504_vs_2000": pooled_dm_results,
    "all_pairwise_pooled_dm": all_pooled_dm,
    "regime_analysis": {k: {kk: vv for kk, vv in v.items()}
                        for k, v in regime_analysis.items()},
    "verdict": verdict,
    "decision_rule": {
        "revise_threshold": "W=504 wins >=4/5 AND pooled DM significant",
        "keep_threshold": "W=504 wins <=2/5",
        "mixed_threshold": "W=504 wins 3/5",
    },
    "references": [
        "K591: Window Size Sensitivity Sweep (single OOS 2023-24, W=504 best, DM=3.68)",
        "Feng & Zhang (2025) J.Forecasting — U-shape, W=1000-2000 optimal",
        "Hillebrand (2005) — persistence bias in short windows",
        "Hansen & Lunde (2005) J.Applied Econometrics — QLIKE",
        "Patton (2011) JoE — imperfect proxies",
        "K406/K408: w=2000 upgrade based on persistence bias",
        "K474/K476: Cross-OOS caught 53% false positive rate",
    ],
}

out_path = f"{MAIN_REPO}/experiments/k593_window_cross_oos_results.json"
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
