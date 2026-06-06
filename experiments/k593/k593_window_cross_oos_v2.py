#!/usr/bin/env python3
"""
K593-v2: Window Size Cross-OOS Validation — corrigendum fix (Codex review 2026-06-07)
======================================================================================
[Original: K593 / mile_faaddb06; Fix author: Claude (hourly-06 2026-06-07)]

Codex review 2026-06-07 標 mile_faaddb06 為 FAIL，三 SEVERE 點：
  1. Forecast engine bug: refit-every-21-day pattern 下 `last_model.forecast(horizon=1)`
     反覆呼叫同一 frozen-params forecast，沒做 sequential state update.
  2. DM test 沒按日期對齊（`[:min_len]` 截斷）.
  3. Pre-reg 站不住（decision rule 與 results 同檔產出）.

V2 修法：
  1. **Forecast engine**：fit 時記下 frozen GJR params + initial sigma2_state，
     refit 間每日用 fitted params + 真實 returns 做 GJR recursion
     `σ²_{t+1} = ω + (α + γ·I(ε_t<0))·ε²_t + β·σ²_t`
     （zero-mean spec → ε_t = r_t / 100，但 returns 已是 log×100，
      arch fit 也直接吃 log×100，所以這層 scale 內部一致，σ² 也是 same scale.）
  2. **DM date alignment**：per-day losses 改 pd.Series indexed by date；
     DM 比較前先 date intersection；pooled 同理。
  3. **Pre-reg**：本檔 docstring 不再宣稱「事先就把判讀規則寫死」，
     decision rule 標為 ex-post documentation。文章端 corrigendum 另寫。

Reproduce expected：
  - 5 OOS periods × 4 windows = 20 個 GJR-GARCH refit loops
  - 每 loop 內：fit at refit-every-21d；intervening days 用 frozen-params recursion
  - QLIKE / DM 數字會與 v1 不同（v1 forecast engine bug 影響全部）

Output: experiments/k593/k593_window_cross_oos_v2_results.json
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

EXPERIMENT_ID = "K593-v2"
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

WINDOWS = [252, 504, 1000, 2000]

OOS_PERIODS = {
    'OOS1_2012-2013': ('2012-01-01', '2013-12-31'),
    'OOS2_2014-2015': ('2014-01-01', '2015-12-31'),
    'OOS3_2016-2017': ('2016-01-01', '2017-12-31'),
    'OOS4_2020-2021': ('2020-01-01', '2021-12-31'),
    'OOS5_2023-2024': ('2023-01-01', '2024-12-31'),
}

REFIT_EVERY = 21

print("=" * 70)
print(f"{EXPERIMENT_ID}: Window Size Cross-OOS Validation (CORRIGENDUM FIX)")
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
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return float(np.mean(rv / fv - np.log(rv / fv) - 1))


def qlike_per_day_arr(realized, forecast):
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return rv / fv - np.log(rv / fv) - 1


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano w/ Newey-West HAC. Negative DM = model1 better."""
    d = np.asarray(loss1) - np.asarray(loss2)
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)

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


def dm_test_aligned(s1, s2, h=1):
    """DM test on two pd.Series indexed by date; aligns on intersection.
    Returns (dm_stat, p_value, n_aligned)."""
    common = s1.index.intersection(s2.index)
    if len(common) < 10:
        return 0.0, 1.0, len(common)
    a = s1.loc[common].values
    b = s2.loc[common].values
    stat, p = dm_test(a, b, h=h)
    return stat, p, len(common)


# ============================================================
# GJR-GARCH rolling forecast — FIXED: sequential state update between refits
# ============================================================
def gjr_garch_rolling(returns, oos_start, oos_end, window, refit_every=21):
    """Rolling GJR-GARCH(1,1)-t forecast with sequential state update.

    Fix vs v1: between refits, instead of returning the same frozen
    `last_model.forecast()`, we manually iterate the GJR recursion using
    fitted params + true realized returns. This is one-step-ahead with
    frozen params and updated conditional variance state.
    """
    oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
    oos_dates = returns.index[oos_mask]
    if len(oos_dates) == 0:
        return None

    forecasts = {}
    realized = {}
    persistence_list = []
    convergence_count = 0
    total_fits = 0
    refit_failures = 0
    state_breakdowns = 0

    all_idx = returns.index.tolist()
    oos_idx_set = set(oos_dates.tolist())
    pos_of = {d: i for i, d in enumerate(all_idx)}  # O(1) lookup

    # Frozen-params state (reset on each refit):
    omega = alpha = gamma_p = beta = None
    sigma2_state = None   # σ²_t  for forecasting r_t (current iter target)
    has_fit = False
    days_since_fit = refit_every  # force fit on first day

    for dt in all_idx:
        if dt not in oos_idx_set:
            continue
        pos = pos_of[dt]
        if pos < window:
            continue

        train = returns.iloc[pos - window:pos]
        days_since_fit += 1
        need_refit = (days_since_fit >= refit_every) or (not has_fit)

        if need_refit:
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                                dist='t', mean='Zero', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                total_fits += 1
                if res.convergence_flag == 0:
                    convergence_count += 1

                params = res.params
                omega = float(params.get('omega', 0.0))
                alpha = float(params.get('alpha[1]', 0.0))
                gamma_p = float(params.get('gamma[1]', 0.0))
                beta = float(params.get('beta[1]', 0.0))
                pers = alpha + beta + gamma_p / 2
                persistence_list.append(pers)

                # Reset sigma2_state via res.forecast() — this is σ²_pos (i.e. for `dt`)
                # arch's forecast() at horizon=1 from last fit = σ²_{T+1} where T=pos-1
                fcast = res.forecast(horizon=1, reindex=False)
                sigma2_state = float(fcast.variance.values[-1, 0])
                has_fit = True
                days_since_fit = 0
            except Exception:
                # Refit failed — keep using old frozen params if available.
                # Counted for audit (Codex review v2 recommendation).
                refit_failures += 1

        if has_fit and sigma2_state is not None and np.isfinite(sigma2_state) and sigma2_state > 0:
            # Record forecast for today's OOS date:
            forecasts[dt] = sigma2_state
            realized[dt] = returns.iloc[pos] ** 2

            # Update state for next iteration using observed return at pos:
            eps = float(returns.iloc[pos])
            indicator = 1.0 if eps < 0 else 0.0
            sigma2_next = omega + (alpha + gamma_p * indicator) * (eps ** 2) + beta * sigma2_state
            if np.isfinite(sigma2_next) and sigma2_next > 0:
                sigma2_state = sigma2_next
            else:
                # Numerical breakdown — drop state, force refit next iter
                state_breakdowns += 1
                has_fit = False
                sigma2_state = None
                days_since_fit = refit_every

    common_dates = sorted(set(forecasts.keys()) & set(realized.keys()))
    if len(common_dates) == 0:
        return None

    fv = np.array([forecasts[d] for d in common_dates])
    rv = np.array([realized[d] for d in common_dates])

    conv_rate = convergence_count / total_fits if total_fits > 0 else 0
    avg_pers = float(np.mean(persistence_list)) if persistence_list else float('nan')

    # Date-indexed per-day loss series for downstream alignment:
    per_day = qlike_per_day_arr(rv, fv)
    # qlike_per_day_arr filters non-positive; preserve original order on valid mask:
    valid_mask = (rv > 0) & (fv > 0)
    valid_dates = [common_dates[i] for i in range(len(common_dates)) if valid_mask[i]]
    per_day_series = pd.Series(per_day, index=pd.DatetimeIndex(valid_dates))

    return {
        'dates': common_dates,
        'forecasts': fv,
        'realized': rv,
        'n_forecasts': len(common_dates),
        'convergence_rate': float(conv_rate),
        'total_fits': total_fits,
        'avg_persistence': avg_pers,
        'per_day_series': per_day_series,
        'refit_failures': int(refit_failures),
        'state_breakdowns': int(state_breakdowns),
    }


# ============================================================
# Run cross-OOS validation
# ============================================================
print("\n[2] Running Cross-OOS Validation (v2 — sequential state update)")
print("=" * 70)

all_results = {}
# Pooled per-day losses keyed by window, stored as pd.Series concat
pooled_series = {w: [] for w in WINDOWS}

for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    print(f"\n--- {period_name} ({oos_start} to {oos_end}) ---")
    period_results = {}

    for w in WINDOWS:
        t0 = time.time()
        res = gjr_garch_rolling(ret, oos_start, oos_end, window=w,
                                refit_every=REFIT_EVERY)

        if res is not None and res['n_forecasts'] > 0:
            ql = qlike_loss(res['realized'], res['forecasts'])

            period_results[w] = {
                'qlike': ql,
                'n_forecasts': res['n_forecasts'],
                'convergence_rate': res['convergence_rate'],
                'avg_persistence': res['avg_persistence'],
                'per_day_series': res['per_day_series'],
                'dates': res['dates'],
                'forecasts': res['forecasts'],
                'realized': res['realized'],
                'refit_failures': res['refit_failures'],
                'state_breakdowns': res['state_breakdowns'],
            }
            pooled_series[w].append(res['per_day_series'])

            elapsed = time.time() - t0
            print(f"  W={w:>5d}: QLIKE={ql:.6f}  n={res['n_forecasts']}  "
                  f"pers={res['avg_persistence']:.4f}  ({elapsed:.1f}s)")
        else:
            print(f"  W={w:>5d}: FAILED (insufficient data)")

    all_results[period_name] = period_results

# Concat pooled series per window:
pooled_series = {w: (pd.concat(pooled_series[w]).sort_index() if pooled_series[w] else pd.Series(dtype=float))
                 for w in WINDOWS}


# ============================================================
# Analysis 1: Per-period ranking
# ============================================================
print("\n" + "=" * 70)
print("[3] Per-Period Ranking Analysis")
print("=" * 70)

ranking_table = {}
win_count = {w: 0 for w in WINDOWS}
qlike_table = {}

for period_name in OOS_PERIODS:
    pr = all_results[period_name]
    if not pr:
        continue
    sorted_windows = sorted(pr.keys(), key=lambda w: pr[w]['qlike'])
    qlike_table[period_name] = {w: pr[w]['qlike'] for w in WINDOWS if w in pr}
    ranking_table[period_name] = {}
    for rank, w in enumerate(sorted_windows, 1):
        ranking_table[period_name][w] = rank
        if rank == 1:
            win_count[w] += 1

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
# Analysis 2: DM tests per period (W=504 vs W=2000) — date-aligned
# ============================================================
print("\n" + "=" * 70)
print("[4] DM Tests: W=504 vs W=2000 per Period (date-aligned)")
print("=" * 70)

dm_per_period = {}
for period_name in OOS_PERIODS:
    pr = all_results[period_name]
    if 504 not in pr or 2000 not in pr:
        continue

    s504 = pr[504]['per_day_series']
    s2000 = pr[2000]['per_day_series']
    dm_stat, p_val, n_aligned = dm_test_aligned(s504, s2000)
    better = "W=504" if dm_stat < 0 else "W=2000"
    sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else "n.s."))

    dm_per_period[period_name] = {
        'dm_stat': dm_stat,
        'p_value': p_val,
        'better': better,
        'significant': sig,
        'n_days': n_aligned,
    }

    ql_504 = pr[504]['qlike']
    ql_2000 = pr[2000]['qlike']
    advantage_pct = (ql_2000 - ql_504) / ql_2000 * 100

    print(f"  {period_name}: DM={dm_stat:+.4f} p={p_val:.4f} {sig:>5s}  "
          f"→ {better} better  (n_aligned={n_aligned}, 504 adv: {advantage_pct:+.2f}%)")


# ============================================================
# Analysis 3: Pooled DM (date-aligned via intersection of valid dates across windows)
# ============================================================
print("\n" + "=" * 70)
print("[5] Pooled DM Test (all 5 OOS periods, date-aligned)")
print("=" * 70)

pooled_dm_results = {}
if len(pooled_series[504]) > 0 and len(pooled_series[2000]) > 0:
    dm_stat, p_val, n_aligned = dm_test_aligned(pooled_series[504], pooled_series[2000])
    better = "W=504" if dm_stat < 0 else "W=2000"
    sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else "n.s."))

    pooled_dm_results = {
        'dm_stat': dm_stat,
        'p_value': p_val,
        'better': better,
        'significant': sig,
        'n_aligned_days': n_aligned,
    }

    p504 = pooled_series[504].loc[pooled_series[504].index.intersection(pooled_series[2000].index)]
    p2000 = pooled_series[2000].loc[pooled_series[504].index.intersection(pooled_series[2000].index)]
    print(f"  Pooled W=504 vs W=2000: DM={dm_stat:+.4f} p={p_val:.4f} {sig}")
    print(f"  → {better} better across {n_aligned} aligned days")
    print(f"  Mean QLIKE (aligned): W=504={float(p504.mean()):.6f}, W=2000={float(p2000.mean()):.6f}")

# Pairwise pooled DM
print("\n  All pairwise pooled DM tests (date-aligned):")
all_pooled_dm = {}
for w1 in WINDOWS:
    for w2 in WINDOWS:
        if w1 >= w2:
            continue
        if len(pooled_series[w1]) > 0 and len(pooled_series[w2]) > 0:
            dm_stat, p_val, n_aligned = dm_test_aligned(pooled_series[w1], pooled_series[w2])
            better = f"W={w1}" if dm_stat < 0 else f"W={w2}"
            sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else ""))
            all_pooled_dm[f"{w1}_vs_{w2}"] = {
                'dm_stat': dm_stat,
                'p_value': p_val,
                'better': better,
                'significant': sig,
                'n_aligned_days': n_aligned,
            }
            print(f"    W={w1} vs W={w2}: DM={dm_stat:+.4f} p={p_val:.4f} {sig:>4s} → {better} (n={n_aligned})")

# Bonferroni-adjusted significance for pairwise pooled (6 tests × 5 periods = 30 family)
# Plus per-period 5 tests for 504_vs_2000. Codex review NIT2: report adjusted.
N_FAMILY = 30  # 6 pairwise pooled × 5 periods... actually pairwise is 1 pooled per pair = 6 pooled.
# More accurately, we have: 5 (per-period 504_vs_2000) + 6 (pairwise pooled) = 11. Use 11.
N_FAMILY = 11
alpha_bonf = 0.05 / N_FAMILY
print(f"\n  Bonferroni-adjusted threshold (N={N_FAMILY}): p < {alpha_bonf:.6f}")


# ============================================================
# Analysis 4: VIX regime analysis
# ============================================================
print("\n" + "=" * 70)
print("[6] VIX Regime Analysis")
print("=" * 70)

regime_analysis = {}
for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
    vix_period = vix[(vix.index >= oos_start) & (vix.index <= oos_end)]
    if len(vix_period) == 0:
        continue

    avg_vix = float(vix_period.mean())
    max_vix = float(vix_period.max())
    std_ret = float(ret[(ret.index >= oos_start) & (ret.index <= oos_end)].std())

    regime = "crisis" if avg_vix > 25 else ("elevated" if avg_vix > 20 else "calm")
    pr = all_results.get(period_name, {})
    best_w = min(pr.keys(), key=lambda w: pr[w]['qlike']) if pr else None

    regime_analysis[period_name] = {
        'avg_vix': avg_vix,
        'max_vix': max_vix,
        'std_ret': std_ret,
        'regime': regime,
        'best_window': best_w,
    }
    print(f"  {period_name}: VIX_avg={avg_vix:.1f} VIX_max={max_vix:.1f} "
          f"σ_ret={std_ret:.2f}% regime={regime:>8s} → best W={best_w}")


# ============================================================
# Analysis 5: Persistence by period
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
print("[8] FINAL VERDICT (v2)")
print("=" * 70)

print(f"\n  Win counts: ", end="")
for w in WINDOWS:
    print(f"W={w}={win_count[w]}  ", end="")
print()

mean_ranks = {}
for w in WINDOWS:
    ranks = [ranking_table[p].get(w, len(WINDOWS)) for p in ranking_table]
    mean_ranks[w] = np.mean(ranks) if ranks else float('nan')
print(f"  Mean ranks: ", end="")
for w in WINDOWS:
    print(f"W={w}={mean_ranks[w]:.2f}  ", end="")
print()

best_by_rank = min(mean_ranks, key=lambda w: mean_ranks[w])
print(f"\n  Best window by mean rank: W={best_by_rank}")

n_504_wins = sum(1 for p in dm_per_period.values() if p['better'] == 'W=504')
n_504_sig_wins = sum(1 for p in dm_per_period.values()
                     if p['better'] == 'W=504' and p['p_value'] < 0.05)
n_504_bonf_wins = sum(1 for p in dm_per_period.values()
                      if p['better'] == 'W=504' and p['p_value'] < alpha_bonf)
n_2000_wins = sum(1 for p in dm_per_period.values() if p['better'] == 'W=2000')
n_2000_sig_wins = sum(1 for p in dm_per_period.values()
                      if p['better'] == 'W=2000' and p['p_value'] < 0.05)
n_2000_bonf_wins = sum(1 for p in dm_per_period.values()
                       if p['better'] == 'W=2000' and p['p_value'] < alpha_bonf)

print(f"\n  DM test results (W=504 vs W=2000):")
print(f"    W=504  wins: {n_504_wins}/5 periods  (raw 5% sig: {n_504_sig_wins}; Bonferroni: {n_504_bonf_wins})")
print(f"    W=2000 wins: {n_2000_wins}/5 periods (raw 5% sig: {n_2000_sig_wins}; Bonferroni: {n_2000_bonf_wins})")

if pooled_dm_results:
    print(f"    Pooled: DM={pooled_dm_results['dm_stat']:+.4f} p={pooled_dm_results['p_value']:.4f} "
          f"→ {pooled_dm_results['better']}")

# Decision (note: this is ex-post documentation, not pre-registered)
print(f"\n  DECISION LOGIC (ex-post documentation, NOT pre-registered):")
if n_504_wins >= 4:
    if pooled_dm_results and pooled_dm_results['p_value'] < 0.05 and pooled_dm_results['better'] == 'W=504':
        verdict = "REVISE: W=504 robustly better across periods. Change paper to W=504."
    else:
        verdict = "TENTATIVE: W=504 wins most periods but pooled test not significant. Report both."
elif n_504_wins <= 2:
    verdict = "KEEP W=2000: K591 was period-specific. W=2000 remains our choice."
else:
    verdict = "MIXED: Regime-dependent, no universal winner. Report as asset/period-specific."

print(f"  >>> {verdict}")


# ============================================================
# Save results
# ============================================================
elapsed_total = time.time() - t0_total
print(f"\n{'='*70}")
print(f"Total elapsed: {elapsed_total:.1f}s")

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
                'refit_failures': pr[w]['refit_failures'],
                'state_breakdowns': pr[w]['state_breakdowns'],
            }

serializable_rankings = {}
for period_name in ranking_table:
    serializable_rankings[period_name] = {str(w): r for w, r in ranking_table[period_name].items()}

results = {
    "experiment_id": EXPERIMENT_ID,
    "parent_experiment_id": "K593",
    "parent_article": "mile_faaddb06",
    "fix_source": "Codex review 2026-06-07 (storage/reports/review_history/mile_faaddb06/codex_review_2026-06-07.md)",
    "fix_summary": [
        "(1) Forecast engine: refit 間每日用 fitted params + GJR recursion update sigma2 state (取代 frozen last_model.forecast 反覆呼叫)",
        "(2) DM tests: per-period + pooled 全 date-aligned via per_day_series (pd.Series indexed by date) intersection",
        "(3) Decision rule 標 ex-post documentation; pre-reg claim 移除",
        "(4) Output 改存 experiments/k593/k593_window_cross_oos_v2_results.json (原 v1 在 repo 根 experiments/ 下)",
        "(5) Bonferroni-adjusted threshold 計入 N=11 family (5 per-period 504_vs_2000 + 6 pairwise pooled)"
    ],
    "title": "Window Size Cross-OOS Validation V2 — corrigendum fix",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "data_source": "yfinance",
    "asset": "SPY",
    "model": "GJR-GARCH(1,1)-t (zero-mean)",
    "windows_tested": WINDOWS,
    "refit_every": REFIT_EVERY,
    "oos_periods": {k: {"start": v[0], "end": v[1]} for k, v in OOS_PERIODS.items()},
    "qlike_by_period_and_window": serializable_qlike,
    "rankings_by_period": serializable_rankings,
    "win_counts": {str(w): win_count[w] for w in WINDOWS},
    "mean_ranks": {str(w): float(mean_ranks[w]) for w in WINDOWS},
    "dm_tests_504_vs_2000_per_period": dm_per_period,
    "pooled_dm_test_504_vs_2000": pooled_dm_results,
    "all_pairwise_pooled_dm": all_pooled_dm,
    "regime_analysis": regime_analysis,
    "multiple_testing_correction": {
        "family_size_N": N_FAMILY,
        "alpha_bonferroni": alpha_bonf,
        "n_504_wins_bonferroni": n_504_bonf_wins,
        "n_2000_wins_bonferroni": n_2000_bonf_wins,
    },
    "verdict": verdict,
    "pre_registration_status": "EX-POST documentation only — decision rule was written alongside results, not independently timestamped pre-OOS. Article corrigendum required.",
    "decision_rule_ex_post": {
        "revise_threshold": "W=504 wins >=4/5 AND pooled DM significant",
        "keep_threshold": "W=504 wins <=2/5",
        "mixed_threshold": "W=504 wins 3/5",
    },
    "references": [
        "K591: Window Size Sensitivity Sweep (single OOS 2023-24, W=504 best, DM=3.68)",
        "Hillebrand (2005) — persistence bias in short windows",
        "Hansen & Lunde (2005) J.Applied Econometrics — QLIKE",
        "Patton (2011) JoE — imperfect proxies",
        "K406/K408: w=2000 upgrade based on persistence bias",
        "K474/K476: Cross-OOS caught 53% false positive rate",
        "(Feng & Zhang 2025 J.Forecasting — citation needs verification, removed in v2)"
    ],
}

out_path = f"{MAIN_REPO}/experiments/k593/k593_window_cross_oos_v2_results.json"
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
