#!/usr/bin/env python3
"""
K1114: Rolling θ_EAV time-varying heterogeneity for A4f-EAV
============================================================
[提出: Claude 承接 K1113 STRONG NULL, 執行: Claude]

Motivation / Big question:
  Paper 2 cross-sectional firm-attribute route is exhausted
  (K1109 sector FAIL, K1113 all 5 covariates FAIL, max BH-adj p=0.854).
  The K1067b/c findings (UMC θ₂>0 strongly PASS; MediaTek REVERSE)
  suggest θ_EAV heterogeneity is *real* — but not explainable by
  observable firm attributes at the firm level.

  This experiment changes dimension: rather than asking
  "which firms have positive θ_EAV?", it asks
  "does θ_EAV vary *over time* within a single firm?".

  Two temporal variation hypotheses:
    - Structural:  θ grows/shrinks with earnings-call information content
                   (covered by analyst ecosystem, pre-announcement price-in)
    - Cyclical:    θ depends on macro regime — larger when market is calm
                   and earnings surprise dominates; smaller when VIX is
                   high and macro news drowns out firm-specific signal

Hypotheses:
  H1 (Structural trend): θ_EAV(t) has a statistically significant linear
      trend vs time (OLS slope t-stat, Harvey |t|>3.0).
  H2 (Cyclical / VIX regime): θ_EAV(t) is correlated (Spearman) with
      contemporaneous VIX (ex-ante percentile rank).
  H3 (Regime-split): θ_EAV(t) distributions differ between
      high-VIX and low-VIX windows (two-sample KS test).

Multiple testing correction:
  3 stocks × 3 tests = 9 p-values; Benjamini-Hochberg FDR adjusted.
  A test is "PASS" only if BH-adj p < 0.05 AND |t|>3.0 where applicable
  (Harvey 2016 threshold).

Model specification (same as K1067b/c):
  τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε)
  u_t = r_t / √τ_t
  g_t = ω_g + α·u_{t-1}² + γ·u_{t-1}²·I(u<0) + β·g_{t-1}
  σ²_t = τ_t · g_t

Rolling design:
  - Window: 500 observations (~2 trading years) — satisfies GARCH
    window requirement (Hwang & Valls Pereira 2006, n≥500)
  - Step:   21 observations (~1 month) → ~115 overlapping windows
  - Period: 2014-01-01 ~ 2025-12-31 (covers 2015 China crash,
    2020 COVID, 2022 bear market)
  - Per stock (TSMC/UMC/MediaTek): ~115 θ₂ estimates

Lookahead discipline:
  - EAV_{t} uses same-day post-close announcement flag (already observed)
  - τ is built from VIX_{t-1}, EAV_{t-1} (lagged)
  - Rolling VIX percentile for regime split uses ex-ante trailing
    (only data up to t-1) — avoids E064 IS-regime degeneracy
  - Seed 42 for all stochastic draws (bootstrap not used but recorded)

Data:
  - 2330.TW (TSMC), 2303.TW (UMC), 2454.TW (MediaTek) — yfinance
  - ^VIX daily (yfinance), forward-filled to TW trading days
  - 財報公告日.txt (Big5) — earnings announcement dates

References:
  - K1067:  TSMC A4f-EAV NULL (θ₂~0)
  - K1067b: UMC A4f-EAV — H2 PASS (θ₂>0, t=15.43, fraction=1.0)
  - K1067c: MediaTek A4f-EAV REVERSE (θ₂ fraction=0.185)
  - K1109:  Pre-registered N=31 sector ANOVA FAIL
  - K1113:  Firm covariate 5 hypotheses STRONG NULL
  - Engle, Ghysels, Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison.
  - Harvey et al. (2016). DM t > 3.0 threshold.

Random seed: 42
Author: VolPred Research System
Date: 2026-04-13
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats, optimize

import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)
RNG = np.random.default_rng(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1114"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1114_results.json'

# Configuration
TICKERS = [
    {'ticker': '2330.TW', 'code': '2330', 'name': 'TSMC'},
    {'ticker': '2303.TW', 'code': '2303', 'name': 'UMC'},
    {'ticker': '2454.TW', 'code': '2454', 'name': 'MediaTek'},
]
DATA_START = '2012-01-01'  # extra history for first-window warmup
DATA_END = '2025-12-31'
ROLL_START = '2014-01-01'  # first rolling window ends here roughly
WINDOW = 500            # ~2 trading years
STEP = 21               # ~1 month
VIX_LOW_Q = 0.33        # regime split thresholds (ex-ante percentile)
VIX_HIGH_Q = 0.67

print("=" * 72)
print(f"{EXPERIMENT_ID}: Rolling θ_EAV time-varying heterogeneity for A4f-EAV")
print("=" * 72)


# ==========================================================================
# SECTION 1: LOAD EARNINGS ANNOUNCEMENTS FOR ALL THREE TICKERS
# ==========================================================================
print("\n[1] Loading earnings announcements (Big5)...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')
lines = raw_text.strip().split('\n')

ea_by_code = {t['code']: [] for t in TICKERS}
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code = parts[0].strip()
        if code not in ea_by_code:
            continue
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                ea_by_code[code].append(dt)
            except Exception:
                pass

for tinfo in TICKERS:
    ea_by_code[tinfo['code']] = sorted(set(ea_by_code[tinfo['code']]))
    print(f"  {tinfo['name']} ({tinfo['code']}): {len(ea_by_code[tinfo['code']])} announcements")


# ==========================================================================
# SECTION 2: LOAD VIX (shared across tickers)
# ==========================================================================
print("\n[2] Loading ^VIX...")
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].dropna()
print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()}, n={len(vix_close)}")


# ==========================================================================
# SECTION 3: MODEL FITTING FUNCTION (A4f-EAV, 7 params)
# ==========================================================================

def fit_a4f_eav(returns, vix_vals, eav_vals):
    """A4f + EAV: τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε). 7 params.

    Returns (params, loglik, converged_flag). If optimizer degenerate,
    converged_flag=False, caller should discard.
    """
    n = len(returns)
    if n < 100:
        return None, None, False

    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    eav_lag = np.empty(n)
    eav_lag[0] = eav_vals[0]
    eav_lag[1:] = eav_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau_raw = theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag
        tau = np.maximum(tau_raw, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns) + 1e-10
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8
    eav_mean = np.mean(eav_lag) + 1e-8
    theta2_init_scale = var0 * 0.05 / max(eav_mean, 1e-4)

    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init_scale, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, theta2_init_scale * 0.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init_scale * 0.5, 0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-8, 1e-3),
        (-1e-2, 1e-2),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 400})
            if res.fun < best_ll and res.success:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    if best_params is None:
        return None, None, False

    # Convergence sanity: theta2 not at bound, persistence < 1
    t2 = best_params[2]
    at_bound = abs(t2) > 9.5e-3  # within 5% of ±1e-2 bound
    persist = best_params[4] + best_params[5] / 2.0 + best_params[6]
    converged = (not at_bound) and (persist < 0.999)
    return best_params, best_ll, converged


# ==========================================================================
# SECTION 4: ROLLING FIT + TESTS PER TICKER
# ==========================================================================

def run_rolling(tinfo):
    ticker = tinfo['ticker']
    code = tinfo['code']
    name = tinfo['name']
    print(f"\n[3.{name}] Rolling A4f-EAV for {name} ({ticker})...")

    # Load prices
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if 'Close' not in raw.columns:
        print(f"  SKIP {name}: no Close column")
        return None
    prices = raw['Close'].dropna()
    if len(prices) < WINDOW + 50:
        print(f"  SKIP {name}: only {len(prices)} obs")
        return None
    log_ret = np.log(prices / prices.shift(1))
    vix_ffill = vix_close.reindex(prices.index, method='ffill')

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_ffill}).dropna()
    # Drop extreme returns (splits or data errors)
    before = len(df)
    df = df[df['log_ret'].abs() <= 0.30]
    if len(df) < before:
        print(f"  Dropped {before - len(df)} extreme returns")

    # Build EAV
    trading_days = df.index
    eav_binary = np.zeros(len(trading_days), dtype=float)
    ea_dates = ea_by_code[code]
    pos_arr = trading_days.searchsorted(np.array([pd.Timestamp(d) for d in ea_dates]))
    for i, pos in enumerate(pos_arr):
        p = int(pos)
        if p >= len(trading_days):
            continue
        eav_binary[p] = 1.0
    df['eav'] = eav_binary
    n_events = int(df['eav'].sum())
    print(f"  {name}: n={len(df)}, events={n_events}, event%={n_events/len(df)*100:.2f}")

    ret_arr = df['log_ret'].values
    vix_arr = df['VIX'].values
    eav_arr = df['eav'].values

    # Rolling windows
    theta2_series = []
    window_info = []

    start_idx = WINDOW  # first window ends here
    for end_idx in range(start_idx, len(df), STEP):
        win_ret = ret_arr[end_idx - WINDOW:end_idx]
        win_vix = vix_arr[end_idx - WINDOW:end_idx]
        win_eav = eav_arr[end_idx - WINDOW:end_idx]
        n_win_ev = int(win_eav.sum())
        if n_win_ev < 3:
            # skip — too few events to identify θ₂
            continue
        params, ll, conv = fit_a4f_eav(win_ret, win_vix, win_eav)
        if params is None or not conv:
            continue
        theta2_val = float(params[2])

        window_end_date = df.index[end_idx - 1]
        window_end_time = window_end_date.value / 1e9  # unix seconds as time axis
        # VIX at window end (ex-ante: known at end of window)
        vix_end = float(vix_arr[end_idx - 1])

        theta2_series.append(theta2_val)
        window_info.append({
            'end_date': str(window_end_date.date()),
            'end_idx': int(end_idx),
            'time_days': int((window_end_date - df.index[0]).days),
            'vix_end': vix_end,
            'n_events_in_window': n_win_ev,
            'theta2': theta2_val,
            'theta1': float(params[1]),
            'theta0': float(params[0]),
            'persistence': float(params[4] + params[5] / 2.0 + params[6]),
            'loglik': float(-ll),
        })

    n_valid = len(theta2_series)
    print(f"  {name}: {n_valid} valid rolling-window fits (out of ~{(len(df)-WINDOW)//STEP})")
    if n_valid < 20:
        print(f"  WARNING: too few valid fits for reliable tests on {name}")

    # --- TEST 1: Structural trend (OLS θ₂ ~ time) ---
    if n_valid >= 10:
        time_vec = np.array([w['time_days'] for w in window_info], dtype=float)
        theta2_vec = np.array(theta2_series, dtype=float)
        slope_res = stats.linregress(time_vec, theta2_vec)
        # Newey-West-like HAC: compute simple t via linregress (ignoring autocorr)
        t_trend = float(slope_res.slope / slope_res.stderr) if slope_res.stderr > 0 else np.nan
        p_trend = float(slope_res.pvalue)
        slope_val = float(slope_res.slope)
    else:
        t_trend = p_trend = slope_val = np.nan

    # --- TEST 2: Cyclical (Spearman θ₂ vs ex-ante VIX percentile) ---
    if n_valid >= 10:
        vix_ends = np.array([w['vix_end'] for w in window_info], dtype=float)
        # Ex-ante percentile using expanding window of prior VIX values only
        # (trailing percentile rank of vix_end among vix values known before window end)
        # Simpler and still ex-ante: use VIX percentile *within* the set of window-ends,
        # computed cumulatively (k-th element's rank among first k)
        ex_ante_pct = np.full(len(vix_ends), np.nan)
        for k in range(len(vix_ends)):
            past = vix_ends[:k + 1]
            ex_ante_pct[k] = float((past < vix_ends[k]).mean())
        # Drop first few where percentile undefined / degenerate
        valid_mask = np.arange(len(vix_ends)) >= 5
        if valid_mask.sum() >= 10:
            sp_rho, sp_p = stats.spearmanr(ex_ante_pct[valid_mask], theta2_vec[valid_mask])
            sp_rho = float(sp_rho); sp_p = float(sp_p)
            # t-equivalent for Spearman: t = r*sqrt((n-2)/(1-r²))
            n_sp = int(valid_mask.sum())
            sp_t = float(sp_rho * np.sqrt((n_sp - 2) / max(1 - sp_rho ** 2, 1e-10))) if abs(sp_rho) < 1 else np.nan
        else:
            sp_rho = sp_p = sp_t = np.nan
    else:
        sp_rho = sp_p = sp_t = np.nan

    # --- TEST 3: Regime split (KS test high-VIX vs low-VIX ex-ante) ---
    if n_valid >= 15:
        vix_ends = np.array([w['vix_end'] for w in window_info], dtype=float)
        theta2_vec = np.array(theta2_series, dtype=float)
        # Use ex-ante trailing percentile (first 10 excluded as warmup)
        ex_ante_pct = np.full(len(vix_ends), np.nan)
        for k in range(10, len(vix_ends)):
            past = vix_ends[:k]  # strictly prior
            if len(past) >= 5:
                ex_ante_pct[k] = float((past < vix_ends[k]).mean())
        valid_mask = ~np.isnan(ex_ante_pct)
        low_mask = valid_mask & (ex_ante_pct <= VIX_LOW_Q)
        high_mask = valid_mask & (ex_ante_pct >= VIX_HIGH_Q)
        if low_mask.sum() >= 5 and high_mask.sum() >= 5:
            ks_stat, ks_p = stats.ks_2samp(theta2_vec[low_mask], theta2_vec[high_mask])
            ks_stat = float(ks_stat); ks_p = float(ks_p)
            mean_low = float(np.mean(theta2_vec[low_mask]))
            mean_high = float(np.mean(theta2_vec[high_mask]))
            n_low = int(low_mask.sum()); n_high = int(high_mask.sum())
        else:
            ks_stat = ks_p = mean_low = mean_high = np.nan
            n_low = int(low_mask.sum()); n_high = int(high_mask.sum())
    else:
        ks_stat = ks_p = mean_low = mean_high = np.nan
        n_low = n_high = 0

    return {
        'ticker': ticker,
        'name': name,
        'n_obs': int(len(df)),
        'n_events': int(n_events),
        'n_valid_fits': int(n_valid),
        'theta2_series': [float(x) for x in theta2_series],
        'window_info': window_info,
        'theta2_mean': float(np.mean(theta2_series)) if n_valid > 0 else np.nan,
        'theta2_std': float(np.std(theta2_series, ddof=1)) if n_valid > 1 else np.nan,
        'theta2_pos_fraction': float(np.mean(np.array(theta2_series) > 0)) if n_valid > 0 else np.nan,
        'test1_trend': {
            'slope_per_day': slope_val,
            't_stat': t_trend,
            'p_value': p_trend,
        },
        'test2_spearman_vix': {
            'rho': sp_rho,
            't_stat': sp_t,
            'p_value': sp_p,
        },
        'test3_regime_ks': {
            'ks_stat': ks_stat,
            'p_value': ks_p,
            'mean_theta2_low_vix': mean_low,
            'mean_theta2_high_vix': mean_high,
            'n_low_vix_windows': n_low,
            'n_high_vix_windows': n_high,
        },
    }


results_by_stock = {}
for tinfo in TICKERS:
    res = run_rolling(tinfo)
    if res is not None:
        results_by_stock[tinfo['name']] = res


# ==========================================================================
# SECTION 5: BH-FDR ACROSS 9 TESTS (3 stocks × 3 tests)
# ==========================================================================
print("\n[4] Benjamini-Hochberg FDR across 9 tests...")

pvals = []
labels = []
tstats = []
for name, r in results_by_stock.items():
    pvals.append(r['test1_trend']['p_value'])
    tstats.append(r['test1_trend']['t_stat'])
    labels.append(f"{name}_test1_trend")
    pvals.append(r['test2_spearman_vix']['p_value'])
    tstats.append(r['test2_spearman_vix']['t_stat'])
    labels.append(f"{name}_test2_spearman_vix")
    pvals.append(r['test3_regime_ks']['p_value'])
    tstats.append(np.nan)  # KS has no standard t-stat
    labels.append(f"{name}_test3_regime_ks")

pvals_arr = np.array(pvals, dtype=float)
valid_p = ~np.isnan(pvals_arr)
bh_adj = np.full(len(pvals_arr), np.nan)
if valid_p.sum() > 0:
    p_sub = pvals_arr[valid_p]
    order = np.argsort(p_sub)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(p_sub))
    m = len(p_sub)
    adj_sub = np.minimum.accumulate(
        (p_sub[order] * m / (np.arange(m) + 1))[::-1]
    )[::-1]
    # Reassemble
    adj_in_order = np.empty(m)
    for rank_i, orig_i in enumerate(order):
        adj_in_order[orig_i] = min(adj_sub[rank_i], 1.0)
    bh_adj[valid_p] = adj_in_order

verdict_table = []
for i, lab in enumerate(labels):
    raw_p = pvals_arr[i]
    adj_p = bh_adj[i]
    t = tstats[i]
    # Verdict rules:
    #   PASS: adj_p<0.05 AND (|t|>3.0 OR test3 KS ignores t)
    #   NS:   adj_p>=0.05
    passes_harvey = (not np.isnan(t)) and (abs(t) > 3.0)
    is_test3 = 'test3' in lab
    if np.isnan(adj_p):
        verdict = 'SKIP'
    elif adj_p < 0.05 and (passes_harvey or is_test3):
        verdict = 'PASS'
    elif adj_p < 0.05 and not passes_harvey and not is_test3:
        verdict = 'MARGINAL'  # BH ok but Harvey threshold not met
    else:
        verdict = 'NS'
    verdict_table.append({
        'label': lab,
        'raw_p': float(raw_p) if not np.isnan(raw_p) else None,
        'bh_adj_p': float(adj_p) if not np.isnan(adj_p) else None,
        't_stat': float(t) if not np.isnan(t) else None,
        'verdict': verdict,
    })

for row in verdict_table:
    print(f"  {row['label']:40s} raw_p={row['raw_p']}, bh_p={row['bh_adj_p']}, "
          f"t={row['t_stat']}, verdict={row['verdict']}")


# ==========================================================================
# SECTION 6: SAVE RESULTS JSON
# ==========================================================================
print("\n[5] Writing results JSON...")

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Rolling θ_EAV time-varying heterogeneity for A4f-EAV',
    'author': 'VolPred Research System (Claude)',
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'config': {
        'tickers': [t['ticker'] for t in TICKERS],
        'data_start': DATA_START,
        'data_end': DATA_END,
        'window_obs': WINDOW,
        'step_obs': STEP,
        'random_seed': 42,
        'vix_low_quantile': VIX_LOW_Q,
        'vix_high_quantile': VIX_HIGH_Q,
    },
    'per_stock_results': results_by_stock,
    'bh_fdr_table': verdict_table,
    'elapsed_seconds': float(time.time() - START_TIME),
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str, ensure_ascii=False)
print(f"  Saved {RESULTS_PATH}")


# ==========================================================================
# SECTION 7: PLOTS
# ==========================================================================
print("\n[6] Plots...")
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # --- Plot 1: rolling θ₂ time series per stock ---
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=False)
    for ax, (name, r) in zip(axes, results_by_stock.items()):
        dates = [pd.Timestamp(w['end_date']) for w in r['window_info']]
        theta2 = r['theta2_series']
        ax.plot(dates, theta2, color='steelblue', lw=1.3, label=f"{name} rolling θ₂")
        ax.axhline(0, color='gray', lw=0.6, linestyle='--')
        ax.set_title(
            f"{name} rolling θ_EAV (window=500, step=21)  "
            f"mean={r['theta2_mean']:.2e}, pos%={r['theta2_pos_fraction']*100:.0f}%  "
            f"n_fit={r['n_valid_fits']}"
        )
        ax.set_ylabel("θ₂ (EAV loading)")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].set_xlabel("Window end date")
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'k1114_rolling_theta.png', dpi=110)
    plt.close()
    print("  Saved k1114_rolling_theta.png")

    # --- Plot 2: θ₂ vs VIX scatter ---
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=False)
    for ax, (name, r) in zip(axes, results_by_stock.items()):
        vix_e = [w['vix_end'] for w in r['window_info']]
        theta2 = r['theta2_series']
        ax.scatter(vix_e, theta2, s=14, alpha=0.6, color='darkorange')
        ax.axhline(0, color='gray', lw=0.6, linestyle='--')
        rho = r['test2_spearman_vix']['rho']
        pv = r['test2_spearman_vix']['p_value']
        rho_str = f"{rho:.3f}" if rho is not None and not (isinstance(rho, float) and np.isnan(rho)) else "NA"
        pv_str = f"{pv:.3f}" if pv is not None and not (isinstance(pv, float) and np.isnan(pv)) else "NA"
        ax.set_title(f"{name}  Spearman ρ={rho_str}  p={pv_str}")
        ax.set_xlabel("VIX at window end")
        ax.set_ylabel("θ₂")
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'k1114_vix_scatter.png', dpi=110)
    plt.close()
    print("  Saved k1114_vix_scatter.png")

    # --- Plot 3: regime boxplot (low vs high VIX) ---
    fig, ax = plt.subplots(figsize=(9, 5))
    box_data = []
    box_labels = []
    for name, r in results_by_stock.items():
        # Reconstruct low/high masks using ex-ante
        ve = np.array([w['vix_end'] for w in r['window_info']], dtype=float)
        t2 = np.array(r['theta2_series'], dtype=float)
        ex_ante_pct = np.full(len(ve), np.nan)
        for k in range(10, len(ve)):
            past = ve[:k]
            if len(past) >= 5:
                ex_ante_pct[k] = float((past < ve[k]).mean())
        valid = ~np.isnan(ex_ante_pct)
        low = valid & (ex_ante_pct <= VIX_LOW_Q)
        high = valid & (ex_ante_pct >= VIX_HIGH_Q)
        if low.sum() > 1:
            box_data.append(t2[low]); box_labels.append(f"{name}\nLow VIX (n={int(low.sum())})")
        if high.sum() > 1:
            box_data.append(t2[high]); box_labels.append(f"{name}\nHigh VIX (n={int(high.sum())})")
    if box_data:
        bp = ax.boxplot(box_data, labels=box_labels, showmeans=True, patch_artist=True)
        for i, patch in enumerate(bp['boxes']):
            patch.set_facecolor('lightsteelblue' if i % 2 == 0 else 'lightsalmon')
        ax.axhline(0, color='gray', lw=0.6, linestyle='--')
        ax.set_ylabel("θ₂ (EAV loading)")
        ax.set_title("K1114 regime-split θ_EAV distributions (ex-ante VIX percentile)")
        ax.grid(alpha=0.3, axis='y')
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.savefig(SCRIPT_DIR / 'k1114_regime_boxplot.png', dpi=110)
        plt.close()
        print("  Saved k1114_regime_boxplot.png")
    else:
        print("  (regime boxplot skipped: no valid regime data)")

except Exception as e:
    print(f"  Plot generation failed: {e}")


elapsed = time.time() - START_TIME
print(f"\n{EXPERIMENT_ID} done in {elapsed:.0f}s")
