#!/usr/bin/env python3
"""
K783b: Cross-Asset Window Size Sensitivity Validation
======================================================
[提出: 用戶, 執行: Claude]

Context:
  K783 found that expanding window significantly beats w=2000 for GJR-GARCH
  on SPY (DM=-3.23, Harvey PASS). Pattern: middle windows (1000-2000) are
  WORST, short (252-504) and very long (ALL) are BEST.
  This MUST be validated on other assets before changing the default.

Design:
  1. Assets: QQQ, GLD, 0050.TW, BTC-USD
  2. Window sizes: 252, 504, 1000, 2000, 3000, 5040, ALL (expanding)
  3. Model: GJR-GARCH(1,1) with Student-t
  4. OOS: 2023-01-01 ~ 2024-12-31
  5. Metric: QLIKE on r² (Patton 2011 proxy-robust)
  6. DM test vs w=2000 for each window, Harvey (2016) t>3.0
  7. Refit every 21 days for efficiency

Key Question: Is "expanding > w=2000" universal or SPY-specific?

Data source: yfinance (daily close)
OOS period: 2023-01-01 to 2024-12-31

References:
  Feng & Zhang (2025) J.Forecasting — U-shape, W=1000-2000 optimal
  Hillebrand (2005) — persistence bias in short windows
  Hansen & Lunde (2005) J.Applied Econometrics — QLIKE
  Patton (2011) JoE — imperfect proxy, r² unbiased for σ²
  Harvey (2016) — t>3.0 threshold for significance
  K591: Window Size Sweep (SPY, W=504 best in 2023-24)
  K593: Cross-OOS Validation (SPY, 5 periods)
  K783: SPY expanding > w=2000 (DM=-3.23)

IMPORTANT for 0050.TW:
  Must use clean_tw50_data() to fix Yahoo Finance split artifact.
"""

import json
import warnings
import time
import sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

# Add project root for imports
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
EXPERIMENT_ID = "K783b"
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

# Assets to test
ASSETS = {
    'QQQ':     {'start': '2003-01-01', 'label': 'QQQ (tech-heavy)'},
    'GLD':     {'start': '2005-01-01', 'label': 'GLD (gold)'},
    '0050.TW': {'start': '2005-01-01', 'label': '0050.TW (Taiwan ETF)'},
    'BTC-USD': {'start': '2015-01-01', 'label': 'BTC-USD (crypto)'},
}

# Window sizes: 252, 504, 1000, 2000, 3000, 5040, 'ALL' (expanding)
WINDOW_SIZES = [252, 504, 1000, 2000, 3000, 5040, 'ALL']

# OOS period
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

# Refit frequency
REFIT_EVERY = 21

print("=" * 70)
print(f"{EXPERIMENT_ID}: Cross-Asset Window Size Sensitivity Validation")
print("  Assets: QQQ, GLD, 0050.TW, BTC-USD")
print(f"  Windows: {WINDOW_SIZES}")
print(f"  OOS: {OOS_START} to {OOS_END}, Refit every {REFIT_EVERY} days")
print(f"  Harvey (2016) threshold: |t| > 3.0")
print("=" * 70)
print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
t0_total = time.time()


# ============================================================
# Loss functions
# ============================================================
def qlike(realized, forecast):
    """QLIKE loss: E[rv/fv - log(rv/fv) - 1]. Lower is better."""
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return np.mean(rv / fv - np.log(rv / fv) - 1)


def qlike_per_day(realized, forecast):
    """Per-day QLIKE losses for DM test."""
    valid = (realized > 0) & (forecast > 0)
    rv = realized[valid]
    fv = forecast[valid]
    return rv / fv - np.log(rv / fv) - 1


# ============================================================
# DM test (Diebold-Mariano with Newey-West HAC)
# ============================================================
def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns (DM stat, p-value). Negative DM = model1 better."""
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)

    # Newey-West HAC variance with bandwidth = h-1
    gamma0 = np.var(d, ddof=0)
    nw_var = gamma0
    for k in range(1, max(h, 2)):
        if len(d) > k:
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            nw_var += 2 * (1 - k / max(h, 2)) * gamma_k

    se = np.sqrt(max(nw_var, 1e-20) / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value


# ============================================================
# GJR-GARCH rolling/expanding forecast
# ============================================================
def gjr_garch_forecast(returns, oos_dates, window, refit_every=21):
    """Rolling or expanding GJR-GARCH(1,1)-t forecast.

    window: int for rolling, 'ALL' for expanding.
    """
    expanding = (window == 'ALL')
    forecasts = {}
    realized = {}
    persistence_list = []
    convergence_count = 0
    total_fits = 0

    all_idx = returns.index.tolist()
    oos_idx_set = set(oos_dates.tolist())

    # Pre-compute positions for speed
    idx_to_pos = {dt: i for i, dt in enumerate(all_idx)}

    last_model = None
    days_since_fit = refit_every  # force fit on first day

    for dt in oos_dates:
        if dt not in idx_to_pos:
            continue
        pos = idx_to_pos[dt]

        if expanding:
            # Use all data from start to pos
            min_window = 252  # at least 1 year for expanding
            if pos < min_window:
                continue
            train = returns.iloc[:pos]
        else:
            if pos < window:
                continue
            train = returns.iloc[pos - window:pos]

        # Decide whether to refit
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
                pass  # use last model

        if last_model is not None:
            try:
                fcast = last_model.forecast(horizon=1, reindex=False)
                h = fcast.variance.values[-1, 0]
                if h > 0 and np.isfinite(h):
                    forecasts[dt] = h
                    realized[dt] = returns.loc[dt] ** 2  # squared return proxy
            except Exception:
                pass

    # Align
    common_dates = sorted(set(forecasts.keys()) & set(realized.keys()))
    fv = np.array([forecasts[d] for d in common_dates])
    rv = np.array([realized[d] for d in common_dates])

    conv_rate = convergence_count / total_fits if total_fits > 0 else 0
    avg_pers = np.mean(persistence_list) if persistence_list else np.nan
    std_pers = np.std(persistence_list) if persistence_list else np.nan

    return {
        'dates': common_dates,
        'forecasts': fv,
        'realized': rv,
        'n_forecasts': len(common_dates),
        'convergence_rate': conv_rate,
        'total_fits': total_fits,
        'avg_persistence': avg_pers,
        'std_persistence': std_pers,
    }


# ============================================================
# Download and prepare data for all assets
# ============================================================
print("\n[1] Downloading data for all assets...")
asset_data = {}

for ticker, cfg in ASSETS.items():
    print(f"  {ticker}...", end=" ", flush=True)
    try:
        df = yf.download(ticker, start=cfg['start'], end='2026-03-31',
                         progress=False, auto_adjust=True)
        if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)

        close = df['Close'].dropna()

        # Special handling for 0050.TW
        if ticker == '0050.TW':
            close, _ = clean_tw50_data(close)

        ret = np.log(close / close.shift(1)).dropna() * 100  # log returns in %

        # Define OOS
        oos_mask = (ret.index >= OOS_START) & (ret.index <= OOS_END)
        oos_dates = ret.index[oos_mask]

        if len(oos_dates) < 50:
            print(f"SKIP (only {len(oos_dates)} OOS days)")
            continue

        asset_data[ticker] = {
            'returns': ret,
            'oos_dates': oos_dates,
            'n_total': len(ret),
            'n_oos': len(oos_dates),
            'start': str(ret.index[0].date()),
            'end': str(ret.index[-1].date()),
            'mean': float(ret.mean()),
            'std': float(ret.std()),
            'skew': float(ret.skew()),
            'kurt': float(ret.kurtosis()),
        }
        print(f"OK: {len(ret)} days ({ret.index[0].date()} to {ret.index[-1].date()}), "
              f"OOS={len(oos_dates)} days, "
              f"mean={ret.mean():.3f}%, std={ret.std():.3f}%")
    except Exception as e:
        print(f"FAILED: {e}")


# ============================================================
# Run GJR-GARCH for each asset × window
# ============================================================
print("\n[2] Running GJR-GARCH(1,1)-t for each asset × window")
print("=" * 70)

all_results = {}   # {asset: {window: result_dict}}
all_losses = {}    # {asset: {window: per_day_loss_array}}

for ticker in asset_data:
    cfg = ASSETS[ticker]
    ret = asset_data[ticker]['returns']
    oos_dates = asset_data[ticker]['oos_dates']

    print(f"\n--- {cfg['label']} ({asset_data[ticker]['n_oos']} OOS days) ---")
    all_results[ticker] = {}
    all_losses[ticker] = {}

    for w in WINDOW_SIZES:
        w_label = str(w)
        t0 = time.time()
        print(f"  W={w_label:>5s}...", end=" ", flush=True)

        # Check if enough data for this window
        if w != 'ALL':
            first_oos_pos = ret.index.get_loc(oos_dates[0])
            if first_oos_pos < w:
                print(f"SKIP (need {w} days, only {first_oos_pos} available)")
                continue

        res = gjr_garch_forecast(ret, oos_dates, window=w, refit_every=REFIT_EVERY)

        if res['n_forecasts'] > 50:
            ql = qlike(res['realized'], res['forecasts'])
            per_day = qlike_per_day(res['realized'], res['forecasts'])

            all_results[ticker][w_label] = {
                'window': w_label,
                'n_forecasts': res['n_forecasts'],
                'QLIKE': float(ql),
                'convergence_rate': float(res['convergence_rate']),
                'total_fits': res['total_fits'],
                'avg_persistence': float(res['avg_persistence']),
                'std_persistence': float(res['std_persistence']),
            }
            all_losses[ticker][w_label] = per_day

            elapsed = time.time() - t0
            print(f"QLIKE={ql:.6f}  pers={res['avg_persistence']:.4f}  "
                  f"conv={res['convergence_rate']:.1%}  n={res['n_forecasts']}  ({elapsed:.1f}s)")
        else:
            elapsed = time.time() - t0
            print(f"SKIP (only {res['n_forecasts']} forecasts, ({elapsed:.1f}s))")


# ============================================================
# DM tests: each window vs w=2000, per asset
# ============================================================
print("\n[3] DM Tests: W=2000 vs alternatives (per asset)")
print("=" * 70)

dm_results = {}  # {asset: {window: {dm_stat, p_value, harvey_pass, better}}}

for ticker in all_losses:
    dm_results[ticker] = {}
    ref_key = '2000'
    if ref_key not in all_losses[ticker]:
        print(f"  {ticker}: W=2000 not available, skipping DM tests")
        continue

    ref_loss = all_losses[ticker][ref_key]
    print(f"\n  {ticker}:")

    for w in WINDOW_SIZES:
        w_label = str(w)
        if w_label == ref_key or w_label not in all_losses[ticker]:
            continue

        alt_loss = all_losses[ticker][w_label]
        min_len = min(len(ref_loss), len(alt_loss))
        if min_len < 50:
            continue

        dm_stat, p_val = dm_test(ref_loss[:min_len], alt_loss[:min_len])
        harvey_pass = abs(dm_stat) > 3.0

        # Negative DM = W=2000 better; Positive DM = alt better
        # But we compare loss_2000 - loss_alt, so:
        # Negative = 2000 has lower loss = 2000 better
        # Wait - dm_test(loss1, loss2): negative = loss1 lower = model1 better
        # So dm_test(ref_loss[2000], alt_loss[w]): negative = 2000 better
        better = "W=2000" if dm_stat < 0 else f"W={w_label}"

        dm_results[ticker][w_label] = {
            'dm_stat': float(dm_stat),
            'p_value': float(p_val),
            'harvey_pass': bool(harvey_pass),
            'better': better,
        }

        sig = "HARVEY PASS" if harvey_pass else ("*" if p_val < 0.10 else "")
        print(f"    vs W={w_label:>5s}: DM={dm_stat:+.3f}  p={p_val:.4f}  "
              f"{'|t|>3.0 ' + sig if harvey_pass else sig:>15s}  -> {better}")


# ============================================================
# Summary: QLIKE matrix (asset × window)
# ============================================================
print("\n" + "=" * 70)
print("QLIKE MATRIX (asset × window) — Lower is better")
print("=" * 70)

# Header
windows_present = [str(w) for w in WINDOW_SIZES]
header = f"{'Asset':>12s}" + "".join(f"  W={w:>5s}" for w in windows_present) + "  BEST"
print(header)
print("-" * len(header))

best_per_asset = {}
for ticker in all_results:
    row = f"{ticker:>12s}"
    best_w = None
    best_ql = float('inf')
    for w in windows_present:
        if w in all_results[ticker]:
            ql = all_results[ticker][w]['QLIKE']
            row += f"  {ql:>8.4f}"
            if ql < best_ql:
                best_ql = ql
                best_w = w
        else:
            row += f"  {'---':>8s}"
    row += f"  W={best_w}" if best_w else "  ---"
    best_per_asset[ticker] = best_w
    print(row)


# ============================================================
# Summary: Relative QLIKE vs w=2000 (%)
# ============================================================
print("\n" + "=" * 70)
print("RELATIVE QLIKE vs W=2000 (%) — Negative = better than W=2000")
print("=" * 70)

header = f"{'Asset':>12s}" + "".join(f"  W={w:>5s}" for w in windows_present) + "  Pattern"
print(header)
print("-" * len(header))

patterns = {}
for ticker in all_results:
    row = f"{ticker:>12s}"
    ref_ql = all_results[ticker].get('2000', {}).get('QLIKE', None)
    if ref_ql is None:
        print(f"{ticker:>12s}  (no W=2000 reference)")
        continue

    ql_by_w = {}
    for w in windows_present:
        if w in all_results[ticker]:
            ql = all_results[ticker][w]['QLIKE']
            rel = (ql - ref_ql) / abs(ref_ql) * 100
            row += f"  {rel:+7.2f}%"
            ql_by_w[w] = ql
        else:
            row += f"  {'---':>8s}"

    # Detect pattern
    if 'ALL' in ql_by_w and '252' in ql_by_w:
        all_ql = ql_by_w.get('ALL', float('inf'))
        short_ql = min(ql_by_w.get('252', float('inf')), ql_by_w.get('504', float('inf')))
        mid_ql = min(ql_by_w.get('1000', float('inf')), ql_by_w.get('2000', float('inf')))

        if all_ql < mid_ql and short_ql < mid_ql:
            pattern = "U-shape (short+ALL > mid)"
        elif all_ql < ref_ql:
            pattern = "ALL beats 2000"
        elif all_ql > ref_ql and short_ql > ref_ql:
            pattern = "2000 is optimal"
        else:
            # Check monotonic
            sorted_ws = sorted([(int(w) if w != 'ALL' else 99999, ql_by_w[w]) for w in ql_by_w])
            diffs = [sorted_ws[i+1][1] - sorted_ws[i][1] for i in range(len(sorted_ws)-1)]
            if all(d <= 0 for d in diffs):
                pattern = "Monotonic decrease (bigger=better)"
            elif all(d >= 0 for d in diffs):
                pattern = "Monotonic increase (smaller=better)"
            else:
                pattern = "Mixed"
    else:
        pattern = "Incomplete"

    patterns[ticker] = pattern
    row += f"  {pattern}"
    print(row)


# ============================================================
# Harvey (2016) significance summary
# ============================================================
print("\n" + "=" * 70)
print("HARVEY (2016) SIGNIFICANCE: |t| > 3.0 tests")
print("=" * 70)

expanding_beats_2000_count = 0
expanding_total = 0

for ticker in dm_results:
    print(f"\n  {ticker}:")
    for w_label, d in dm_results[ticker].items():
        status = "PASS" if d['harvey_pass'] else "FAIL"
        print(f"    W={w_label:>5s}: DM={d['dm_stat']:+.3f}  Harvey {status}  -> {d['better']}")
        if w_label == 'ALL':
            expanding_total += 1
            if d['dm_stat'] > 0 and d['harvey_pass']:
                # Positive DM = alt (ALL) better
                expanding_beats_2000_count += 1
            elif d['dm_stat'] < 0 and d['harvey_pass']:
                # Negative DM = 2000 better, but with Harvey pass
                pass  # 2000 significantly better


# ============================================================
# Key question answer
# ============================================================
print("\n" + "=" * 70)
print("KEY QUESTION: Is 'expanding > w=2000' universal?")
print("=" * 70)

# Count how many assets have expanding (ALL) beating w=2000
all_beats = 0
all_total = 0
for ticker in all_results:
    if 'ALL' in all_results[ticker] and '2000' in all_results[ticker]:
        all_total += 1
        if all_results[ticker]['ALL']['QLIKE'] < all_results[ticker]['2000']['QLIKE']:
            all_beats += 1
            print(f"  {ticker}: ALL ({all_results[ticker]['ALL']['QLIKE']:.6f}) < "
                  f"W=2000 ({all_results[ticker]['2000']['QLIKE']:.6f}) -> ALL wins")
        else:
            print(f"  {ticker}: ALL ({all_results[ticker]['ALL']['QLIKE']:.6f}) >= "
                  f"W=2000 ({all_results[ticker]['2000']['QLIKE']:.6f}) -> W=2000 wins")

print(f"\n  Score: Expanding beats W=2000 in {all_beats}/{all_total} assets")

if all_beats == all_total and all_total > 0:
    conclusion = "UNIVERSAL: Expanding beats W=2000 across ALL tested assets"
elif all_beats >= all_total * 0.75:
    conclusion = "MOSTLY UNIVERSAL: Expanding beats W=2000 in most assets"
elif all_beats >= all_total * 0.5:
    conclusion = "MIXED: Expanding beats W=2000 in some assets, not universal"
elif all_beats > 0:
    conclusion = "MOSTLY ASSET-SPECIFIC: Expanding beats W=2000 only in few assets"
else:
    conclusion = "SPY-SPECIFIC: Expanding does NOT beat W=2000 in any other asset"

print(f"  Conclusion: {conclusion}")


# ============================================================
# Save results
# ============================================================
elapsed_total = time.time() - t0_total
print(f"\n{'='*70}")
print(f"Total elapsed: {elapsed_total:.1f}s")

results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Cross-Asset Window Size Sensitivity Validation",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "data_source": "yfinance",
    "assets_tested": list(all_results.keys()),
    "oos_period": f"{OOS_START} to {OOS_END}",
    "refit_every": REFIT_EVERY,
    "model": "GJR-GARCH(1,1)-t",
    "windows_tested": [str(w) for w in WINDOW_SIZES],
    "harvey_threshold": 3.0,
    "asset_descriptive_stats": {
        ticker: {
            'n_total': asset_data[ticker]['n_total'],
            'n_oos': asset_data[ticker]['n_oos'],
            'period': f"{asset_data[ticker]['start']} to {asset_data[ticker]['end']}",
            'mean_pct': asset_data[ticker]['mean'],
            'std_pct': asset_data[ticker]['std'],
            'skew': asset_data[ticker]['skew'],
            'kurt': asset_data[ticker]['kurt'],
        } for ticker in asset_data
    },
    "qlike_matrix": {
        ticker: {w: all_results[ticker][w]['QLIKE'] for w in all_results[ticker]}
        for ticker in all_results
    },
    "full_results": {
        ticker: all_results[ticker] for ticker in all_results
    },
    "dm_tests_vs_2000": dm_results,
    "best_window_per_asset": best_per_asset,
    "patterns": patterns,
    "expanding_vs_2000_score": f"{all_beats}/{all_total}",
    "conclusion": conclusion,
    "references": [
        "Feng & Zhang (2025) J.Forecasting — U-shape, W=1000-2000 optimal",
        "Hillebrand (2005) — persistence bias in short windows",
        "Hansen & Lunde (2005) J.Applied Econometrics — QLIKE",
        "Patton (2011) JoE — imperfect proxy, r² unbiased for σ²",
        "Harvey (2016) — t>3.0 threshold",
        "K783: SPY expanding > w=2000 (DM=-3.23, Harvey PASS)",
        "K591: Window Size Sweep (SPY)",
        "K593: Cross-OOS Validation (SPY)",
    ],
}

import os
script_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(script_dir, "k783b_cross_asset_window_results.json")
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
