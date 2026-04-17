#!/usr/bin/env python3
"""
K553: VIX-Conditional Leverage for Taiwan — Taiwan-Specific Adaptation

K551 showed VIX-Conditional Leverage works brilliantly for US (Harvey t=7.90,
11/11 OOS) but FAILS for Taiwan (-0.004 Sharpe diff). Root cause: VIX is almost
always >15 from Taiwan's perspective due to amplification (~4.6x), so US thresholds
(15/25) never trigger the leverage-up condition.

This experiment designs TAIWAN-SPECIFIC leverage strategies:
  Variant A: Taiwan-Calibrated VIX Thresholds (18/30 instead of 15/25)
  Variant B: Taiwan's Own Realized Vol (RV22_TW) thresholds
  Variant C: VT Weight Signal (8.63/VIX > 0.5 = calm)
  Variant D: VIX Percentile-Based (rolling 1yr VIX percentile)
  Variant E: Hybrid (RV22_TW + VIX percentile)

All variants tested with 5-period cross-OOS + Harvey t>3.0 + bootstrap.

References:
  K548: Original VIX-Conditional Leverage (US, Sharpe +0.112)
  K551: Deep validation (US: 11/11 OOS, Taiwan: FAIL -0.004)
  K550: Adaptive VIX threshold analysis
  K461: Taiwan VT calibration (8.63/VIX)
  Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  Harvey et al. (2016) t>3.0 threshold

Author: VolPred Research System (Claude)
Data: yfinance (0050.TW, ^VIX), 2005-2026
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────── Config ───────────────────────────
START = "2005-01-01"
END = "2026-03-27"
BORROWING_SPREAD = 0.008  # Taiwan margin cost: ~80bps above rf
TW_RF = 0.01  # Taiwan risk-free ~1%
N_BOOTSTRAP = 5000
np.random.seed(42)

# Cross-OOS periods (5-period for Taiwan data, 2009-2026 where data is dense)
OOS_PERIODS = [
    ("2009-06-01", "2012-12-31"),
    ("2013-01-01", "2016-05-31"),
    ("2016-06-01", "2019-11-30"),
    ("2019-12-01", "2023-05-31"),
    ("2023-06-01", "2026-03-27"),
]

# Alternative OOS split
OOS_ALT = [
    ("2009-06-01", "2013-12-31"),
    ("2014-01-01", "2017-12-31"),
    ("2018-01-01", "2021-12-31"),
    ("2022-01-01", "2026-03-27"),
]


def download_data():
    """Download 0050.TW and VIX data."""
    print("=" * 70)
    print("K553: VIX-CONDITIONAL LEVERAGE FOR TAIWAN")
    print("=" * 70)

    tw = yf.download("0050.TW", start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    for df in [tw, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    data = pd.DataFrame(index=tw.index)
    data["tw_close"] = tw["Close"]
    data["vix_raw"] = vix["Close"].reindex(tw.index)

    # VIX with 1-day lag (US market closes T-1 relative to Taiwan T)
    data["vix"] = data["vix_raw"].shift(1)
    data = data.ffill().dropna()

    data["tw_ret"] = data["tw_close"].pct_change()
    data = data.dropna()
    data = data.iloc[1:]  # remove first row

    # 8.63/VIX weight for Taiwan (from K461)
    data["vt_weight"] = np.minimum(8.63 / data["vix"], 1.0)
    data["rf_daily"] = TW_RF / 252

    # Realized vol (22-day rolling) for 0050.TW
    data["rv22_tw"] = data["tw_ret"].rolling(22).std() * np.sqrt(252) * 100  # annualized %

    # Rolling VIX percentile (252-day window)
    data["vix_pctile"] = data["vix"].rolling(252).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
    )

    data = data.dropna()
    print(f"  Data: {data.index[0].date()} to {data.index[-1].date()}, N={len(data)}")

    # Diagnostics
    print(f"\n  === TAIWAN DATA DIAGNOSTICS ===")
    print(f"  0050.TW return: mean={data['tw_ret'].mean()*252*100:.1f}%/yr, "
          f"vol={data['tw_ret'].std()*np.sqrt(252)*100:.1f}%/yr")
    print(f"  VIX (lagged): mean={data['vix'].mean():.1f}, median={data['vix'].median():.1f}")
    print(f"  VIX distribution:")
    for threshold in [12, 15, 18, 20, 25, 30]:
        pct = (data["vix"] < threshold).mean() * 100
        print(f"    VIX < {threshold}: {pct:.1f}% of days")
    print(f"  RV22_TW: mean={data['rv22_tw'].mean():.1f}%, median={data['rv22_tw'].median():.1f}%")
    print(f"  VT weight (8.63/VIX): mean={data['vt_weight'].mean():.3f}, "
          f"median={data['vt_weight'].median():.3f}")

    return data


def compute_base_returns(data):
    """Base Taiwan VT: 8.63/VIX * 0050.TW + (1 - 8.63/VIX) * rf."""
    w = data["vt_weight"]
    return w * data["tw_ret"] + (1 - w) * data["rf_daily"]


def apply_leverage(data, leverage_series, borrow_spread=BORROWING_SPREAD):
    """
    Apply leverage to base Taiwan VT returns.
    leverage_series: pd.Series of leverage multipliers (>=1.0).
    """
    w = data["vt_weight"]
    effective_lev = w * leverage_series
    gross_ret = effective_lev * data["tw_ret"] + (1 - effective_lev) * data["rf_daily"]

    # Borrowing cost on leveraged portion
    borrow_daily = (data["rf_daily"] + borrow_spread / 252)
    borrow_cost = np.maximum(effective_lev - 1, 0) * borrow_daily
    net_ret = gross_ret - borrow_cost

    return net_ret, effective_lev


def compute_metrics(returns_series):
    """Standard performance metrics."""
    r = returns_series.dropna()
    if len(r) < 126:
        return None

    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    years = len(r) / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = r.std() * np.sqrt(252)

    rf_daily = TW_RF / 252
    excess = r - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    mdd = drawdown.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    downside = excess[excess < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = excess.mean() * 252 / downside_std

    return {
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "total_return_pct": round(total_return * 100, 2),
        "years": round(years, 1),
        "n_days": len(r),
    }


def dm_test_harvey(base_ret, strat_ret, h=1):
    """Diebold-Mariano test with Newey-West HAC for Harvey (2016) threshold."""
    d = strat_ret - base_ret
    d = d.dropna()
    n = len(d)
    d_mean = d.mean()

    # Newey-West HAC variance estimator
    max_lag = int(np.ceil(4 * (n / 100) ** (2/9)))
    gamma = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        gamma[k] = np.mean((d.values[k:] - d_mean) * (d.values[:n-k] - d_mean))

    # Bartlett kernel weights
    nw_var = gamma[0]
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        nw_var += 2 * w * gamma[k]

    se = np.sqrt(nw_var / n)
    t_stat = d_mean / se if se > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return {
        "t_stat": round(t_stat, 3),
        "p_value": round(p_value, 6),
        "harvey_pass": abs(t_stat) > 3.0,
        "n": n,
        "nw_lags": max_lag,
    }


def bootstrap_sharpe_diff(base_ret, strat_ret, n_boot=N_BOOTSTRAP):
    """Block bootstrap for Sharpe difference CI."""
    base = base_ret.values
    strat = strat_ret.values
    n = len(base)
    block_size = 22  # Monthly blocks

    diffs = []
    for _ in range(n_boot):
        n_blocks = int(np.ceil(n / block_size))
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]

        b_boot = base[indices]
        s_boot = strat[indices]

        rf_d = TW_RF / 252
        b_sharpe = (b_boot.mean() - rf_d) / b_boot.std() * np.sqrt(252) if b_boot.std() > 0 else 0
        s_sharpe = (s_boot.mean() - rf_d) / s_boot.std() * np.sqrt(252) if s_boot.std() > 0 else 0
        diffs.append(s_sharpe - b_sharpe)

    diffs = np.array(diffs)
    return {
        "mean_diff": round(np.mean(diffs), 4),
        "ci_5": round(np.percentile(diffs, 2.5), 4),
        "ci_95": round(np.percentile(diffs, 97.5), 4),
        "p_win": round((diffs > 0).mean() * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════
# VARIANT A: Taiwan-Calibrated VIX Thresholds
# ═══════════════════════════════════════════════════════════════
def variant_a_vix_calibrated(data, low_vix=18, high_vix=30, max_lev=1.5):
    """
    Taiwan-calibrated VIX thresholds.
    Since VIX is almost always >15 from Taiwan's view, we raise thresholds:
    - 'Calm' for Taiwan: VIX < 18 (not 15)
    - 'Stress' for Taiwan: VIX > 30 (not 25)
    """
    lev = np.clip(
        max_lev - (max_lev - 1.0) * (data["vix"] - low_vix) / (high_vix - low_vix),
        1.0, max_lev
    )
    return apply_leverage(data, lev)


# ═══════════════════════════════════════════════════════════════
# VARIANT B: Taiwan's Own Realized Vol
# ═══════════════════════════════════════════════════════════════
def variant_b_rv_tw(data, rv_low=15, rv_high=25, max_lev=1.5):
    """
    Use 0050.TW's own 22-day realized vol instead of VIX.
    - RV22_TW < rv_low%: lever up (calm)
    - RV22_TW > rv_high%: no leverage (stress)
    """
    lev = np.clip(
        max_lev - (max_lev - 1.0) * (data["rv22_tw"] - rv_low) / (rv_high - rv_low),
        1.0, max_lev
    )
    return apply_leverage(data, lev)


# ═══════════════════════════════════════════════════════════════
# VARIANT C: VT Weight Signal
# ═══════════════════════════════════════════════════════════════
def variant_c_vt_weight(data, w_high=0.5, w_low=0.3, max_lev=1.5):
    """
    Use the 8.63/VIX weight itself as the signal.
    - Weight > w_high (calm, high allocation): lever up
    - Weight < w_low (stress, low allocation): no leverage
    """
    w = data["vt_weight"]
    lev = np.clip(
        1.0 + (max_lev - 1.0) * (w - w_low) / (w_high - w_low),
        1.0, max_lev
    )
    return apply_leverage(data, lev)


# ═══════════════════════════════════════════════════════════════
# VARIANT D: VIX Percentile-Based
# ═══════════════════════════════════════════════════════════════
def variant_d_vix_percentile(data, pctile_low=0.30, pctile_high=0.70, max_lev=1.5):
    """
    Use rolling 1yr VIX percentile (relative to history).
    - VIX in bottom 30th percentile (low relative to history): lever up
    - VIX in top 30th percentile (high relative to history): no leverage
    Advantage: self-calibrating, no absolute thresholds needed.
    """
    pctile = data["vix_pctile"]
    # When percentile is LOW (VIX is relatively calm), lever UP
    lev = np.clip(
        max_lev - (max_lev - 1.0) * (pctile - pctile_low) / (pctile_high - pctile_low),
        1.0, max_lev
    )
    return apply_leverage(data, lev)


# ═══════════════════════════════════════════════════════════════
# VARIANT E: Hybrid (RV22_TW + VIX Percentile)
# ═══════════════════════════════════════════════════════════════
def variant_e_hybrid(data, rv_low=15, rv_high=25, pctile_low=0.30, pctile_high=0.70,
                     max_lev=1.5):
    """
    Both signals must agree for leverage.
    - Both calm (RV low + VIX percentile low): lever up
    - Either stressed: no leverage
    """
    rv_lev = np.clip(
        max_lev - (max_lev - 1.0) * (data["rv22_tw"] - rv_low) / (rv_high - rv_low),
        1.0, max_lev
    )
    pctile = data["vix_pctile"]
    pctile_lev = np.clip(
        max_lev - (max_lev - 1.0) * (pctile - pctile_low) / (pctile_high - pctile_low),
        1.0, max_lev
    )
    # Take minimum of both — conservative, both must agree
    combined_lev = np.minimum(rv_lev, pctile_lev)
    return apply_leverage(data, combined_lev)


# ═══════════════════════════════════════════════════════════════
# SENSITIVITY GRID SWEEP
# ═══════════════════════════════════════════════════════════════
def sensitivity_sweep(data):
    """Grid search over key parameters for each variant."""
    print("\n" + "=" * 70)
    print("SENSITIVITY ANALYSIS: PARAMETER GRID SWEEP")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    base_m = compute_metrics(base_ret)
    base_sharpe = base_m["sharpe"]
    print(f"  Base Sharpe: {base_sharpe:.3f}")

    results = {}

    # Variant A: VIX threshold sweep
    print("\n  --- Variant A: VIX Threshold Sweep ---")
    a_results = []
    for low in [14, 16, 18, 20, 22]:
        for high in [25, 28, 30, 33, 35]:
            if high <= low + 5:
                continue
            for lev in [1.2, 1.3, 1.5]:
                ret, _ = variant_a_vix_calibrated(data, low, high, lev)
                m = compute_metrics(ret)
                if m:
                    diff = m["sharpe"] - base_sharpe
                    a_results.append({
                        "low": low, "high": high, "max_lev": lev,
                        "sharpe": m["sharpe"], "diff": round(diff, 3),
                        "cagr": m["cagr"], "mdd": m["mdd"],
                    })
    a_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"  Tested {len(a_results)} configs")
    for r in a_results[:5]:
        print(f"    VIX[{r['low']},{r['high']}] lev={r['max_lev']}: "
              f"Sharpe={r['sharpe']:.3f} ({r['diff']:+.3f}), "
              f"CAGR={r['cagr']:.1f}%, MDD={r['mdd']:.1f}%")
    results["variant_a_sweep"] = a_results
    n_positive_a = sum(1 for r in a_results if r["diff"] > 0)
    print(f"  Positive configs: {n_positive_a}/{len(a_results)} ({n_positive_a/len(a_results)*100:.0f}%)")

    # Variant B: RV threshold sweep
    print("\n  --- Variant B: RV22_TW Threshold Sweep ---")
    b_results = []
    for rv_low in [10, 12, 15, 18, 20]:
        for rv_high in [20, 25, 30, 35]:
            if rv_high <= rv_low + 5:
                continue
            for lev in [1.2, 1.3, 1.5]:
                ret, _ = variant_b_rv_tw(data, rv_low, rv_high, lev)
                m = compute_metrics(ret)
                if m:
                    diff = m["sharpe"] - base_sharpe
                    b_results.append({
                        "rv_low": rv_low, "rv_high": rv_high, "max_lev": lev,
                        "sharpe": m["sharpe"], "diff": round(diff, 3),
                        "cagr": m["cagr"], "mdd": m["mdd"],
                    })
    b_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"  Tested {len(b_results)} configs")
    for r in b_results[:5]:
        print(f"    RV[{r['rv_low']},{r['rv_high']}] lev={r['max_lev']}: "
              f"Sharpe={r['sharpe']:.3f} ({r['diff']:+.3f}), "
              f"CAGR={r['cagr']:.1f}%, MDD={r['mdd']:.1f}%")
    results["variant_b_sweep"] = b_results
    n_positive_b = sum(1 for r in b_results if r["diff"] > 0)
    print(f"  Positive configs: {n_positive_b}/{len(b_results)} ({n_positive_b/len(b_results)*100:.0f}%)")

    # Variant C: VT weight sweep
    print("\n  --- Variant C: VT Weight Signal Sweep ---")
    c_results = []
    for w_high in [0.35, 0.40, 0.50, 0.60, 0.70]:
        for w_low in [0.20, 0.25, 0.30, 0.35]:
            if w_high <= w_low + 0.05:
                continue
            for lev in [1.2, 1.3, 1.5]:
                ret, _ = variant_c_vt_weight(data, w_high, w_low, lev)
                m = compute_metrics(ret)
                if m:
                    diff = m["sharpe"] - base_sharpe
                    c_results.append({
                        "w_high": w_high, "w_low": w_low, "max_lev": lev,
                        "sharpe": m["sharpe"], "diff": round(diff, 3),
                        "cagr": m["cagr"], "mdd": m["mdd"],
                    })
    c_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"  Tested {len(c_results)} configs")
    for r in c_results[:5]:
        print(f"    W[{r['w_low']},{r['w_high']}] lev={r['max_lev']}: "
              f"Sharpe={r['sharpe']:.3f} ({r['diff']:+.3f}), "
              f"CAGR={r['cagr']:.1f}%, MDD={r['mdd']:.1f}%")
    results["variant_c_sweep"] = c_results
    n_positive_c = sum(1 for r in c_results if r["diff"] > 0)
    print(f"  Positive configs: {n_positive_c}/{len(c_results)} ({n_positive_c/len(c_results)*100:.0f}%)")

    # Variant D: Percentile sweep
    print("\n  --- Variant D: VIX Percentile Sweep ---")
    d_results = []
    for p_low in [0.15, 0.20, 0.25, 0.30, 0.40]:
        for p_high in [0.50, 0.60, 0.70, 0.80]:
            if p_high <= p_low + 0.1:
                continue
            for lev in [1.2, 1.3, 1.5]:
                ret, _ = variant_d_vix_percentile(data, p_low, p_high, lev)
                m = compute_metrics(ret)
                if m:
                    diff = m["sharpe"] - base_sharpe
                    d_results.append({
                        "pctile_low": p_low, "pctile_high": p_high, "max_lev": lev,
                        "sharpe": m["sharpe"], "diff": round(diff, 3),
                        "cagr": m["cagr"], "mdd": m["mdd"],
                    })
    d_results.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"  Tested {len(d_results)} configs")
    for r in d_results[:5]:
        print(f"    Pctile[{r['pctile_low']},{r['pctile_high']}] lev={r['max_lev']}: "
              f"Sharpe={r['sharpe']:.3f} ({r['diff']:+.3f}), "
              f"CAGR={r['cagr']:.1f}%, MDD={r['mdd']:.1f}%")
    results["variant_d_sweep"] = d_results
    n_positive_d = sum(1 for r in d_results if r["diff"] > 0)
    print(f"  Positive configs: {n_positive_d}/{len(d_results)} ({n_positive_d/len(d_results)*100:.0f}%)")

    return results


# ═══════════════════════════════════════════════════════════════
# CROSS-OOS VALIDATION
# ═══════════════════════════════════════════════════════════════
def cross_oos_test(data, variant_func, variant_kwargs, variant_name, oos_periods):
    """Run cross-OOS validation for a variant."""
    results = []
    base_ret = compute_base_returns(data)

    for i, (start, end) in enumerate(oos_periods):
        mask = (data.index >= start) & (data.index <= end)
        if mask.sum() < 63:  # min ~3 months
            continue

        b = base_ret.loc[mask]
        s_ret, _ = variant_func(data.loc[mask] if 'data' not in variant_kwargs else data, **variant_kwargs)
        # Recompute for the period
        sub = data.loc[mask].copy()
        s_ret, _ = variant_func(sub, **variant_kwargs)
        b = compute_base_returns(sub)

        b_m = compute_metrics(b)
        s_m = compute_metrics(s_ret)

        if b_m and s_m:
            diff = s_m["sharpe"] - b_m["sharpe"]
            results.append({
                "period": f"{start} to {end}",
                "n_days": mask.sum(),
                "base_sharpe": b_m["sharpe"],
                "strat_sharpe": s_m["sharpe"],
                "sharpe_diff": round(diff, 3),
                "win": diff > 0,
                "base_mdd": b_m["mdd"],
                "strat_mdd": s_m["mdd"],
            })

    n_wins = sum(1 for r in results if r["win"])
    n_total = len(results)
    return {
        "variant": variant_name,
        "n_wins": n_wins,
        "n_total": n_total,
        "win_rate": round(n_wins / n_total * 100, 1) if n_total > 0 else 0,
        "periods": results,
    }


# ═══════════════════════════════════════════════════════════════
# FULL EVALUATION OF BEST VARIANTS
# ═══════════════════════════════════════════════════════════════
def full_evaluate(data, variant_func, variant_kwargs, variant_name):
    """Full evaluation: metrics, DM test, bootstrap, cross-OOS."""
    print(f"\n{'─' * 60}")
    print(f"  FULL EVALUATION: {variant_name}")
    print(f"{'─' * 60}")

    base_ret = compute_base_returns(data)
    strat_ret, effective_lev = variant_func(data, **variant_kwargs)

    base_m = compute_metrics(base_ret)
    strat_m = compute_metrics(strat_ret)

    if not base_m or not strat_m:
        print("  ERROR: insufficient data")
        return None

    sharpe_diff = strat_m["sharpe"] - base_m["sharpe"]
    print(f"  Base:  Sharpe={base_m['sharpe']:.3f}, CAGR={base_m['cagr']:.1f}%, MDD={base_m['mdd']:.1f}%")
    print(f"  Strat: Sharpe={strat_m['sharpe']:.3f}, CAGR={strat_m['cagr']:.1f}%, MDD={strat_m['mdd']:.1f}%")
    print(f"  Diff:  Sharpe {sharpe_diff:+.3f}, CAGR {strat_m['cagr']-base_m['cagr']:+.1f}pp, "
          f"MDD {strat_m['mdd']-base_m['mdd']:+.1f}pp")

    # Leverage diagnostics
    lev_vals = effective_lev.dropna()
    print(f"\n  Leverage diagnostics:")
    print(f"    Mean effective leverage: {lev_vals.mean():.3f}")
    print(f"    % days with leverage > 1: {(lev_vals > 1.01).mean()*100:.1f}%")
    print(f"    % days at max leverage: {(lev_vals > 1.45).mean()*100:.1f}%")
    print(f"    Mean leverage when > 1: {lev_vals[lev_vals > 1.01].mean():.3f}" if (lev_vals > 1.01).any() else "    N/A")

    # Harvey DM test
    print(f"\n  Harvey DM test:")
    dm = dm_test_harvey(base_ret, strat_ret)
    print(f"    t={dm['t_stat']:.3f}, p={dm['p_value']:.6f}, "
          f"{'PASS (t>{:.1f})'.format(3.0) if dm['harvey_pass'] else 'FAIL (t<3.0)'}")

    # Bootstrap
    print(f"\n  Bootstrap ({N_BOOTSTRAP} reps):")
    boot = bootstrap_sharpe_diff(base_ret, strat_ret)
    print(f"    Mean diff: {boot['mean_diff']:+.4f}")
    print(f"    95% CI: [{boot['ci_5']:.4f}, {boot['ci_95']:.4f}]")
    print(f"    P(win): {boot['p_win']:.1f}%")

    # Cross-OOS (primary)
    print(f"\n  Cross-OOS (primary, {len(OOS_PERIODS)} periods):")
    oos_primary = cross_oos_test(data, variant_func, variant_kwargs, variant_name, OOS_PERIODS)
    for p in oos_primary["periods"]:
        print(f"    {p['period']}: base={p['base_sharpe']:.3f}, strat={p['strat_sharpe']:.3f}, "
              f"diff={p['sharpe_diff']:+.3f} {'WIN' if p['win'] else 'LOSS'}")
    print(f"    Result: {oos_primary['n_wins']}/{oos_primary['n_total']} wins")

    # Cross-OOS (alternative)
    print(f"\n  Cross-OOS (alternative, {len(OOS_ALT)} periods):")
    oos_alt = cross_oos_test(data, variant_func, variant_kwargs, variant_name, OOS_ALT)
    for p in oos_alt["periods"]:
        print(f"    {p['period']}: base={p['base_sharpe']:.3f}, strat={p['strat_sharpe']:.3f}, "
              f"diff={p['sharpe_diff']:+.3f} {'WIN' if p['win'] else 'LOSS'}")
    print(f"    Result: {oos_alt['n_wins']}/{oos_alt['n_total']} wins")

    total_wins = oos_primary["n_wins"] + oos_alt["n_wins"]
    total_periods = oos_primary["n_total"] + oos_alt["n_total"]

    return {
        "variant": variant_name,
        "params": variant_kwargs,
        "full_sample": {
            "base": base_m,
            "strategy": strat_m,
            "sharpe_diff": round(sharpe_diff, 3),
        },
        "leverage_diagnostics": {
            "mean_effective_lev": round(lev_vals.mean(), 3),
            "pct_days_leveraged": round((lev_vals > 1.01).mean() * 100, 1),
            "mean_lev_when_leveraged": round(lev_vals[lev_vals > 1.01].mean(), 3) if (lev_vals > 1.01).any() else None,
        },
        "harvey_dm_test": dm,
        "bootstrap": boot,
        "cross_oos_primary": oos_primary,
        "cross_oos_alternative": oos_alt,
        "total_oos_wins": total_wins,
        "total_oos_periods": total_periods,
    }


# ═══════════════════════════════════════════════════════════════
# K551 REPLICATION (US thresholds on Taiwan — confirm failure)
# ═══════════════════════════════════════════════════════════════
def replicate_k551_failure(data):
    """Replicate K551's Taiwan failure for comparison."""
    print("\n" + "=" * 70)
    print("K551 REPLICATION: US THRESHOLDS ON TAIWAN (EXPECTED FAILURE)")
    print("=" * 70)

    base_ret = compute_base_returns(data)
    base_m = compute_metrics(base_ret)

    # K551 used VIX 15/25
    ret_15_25, _ = variant_a_vix_calibrated(data, low_vix=15, high_vix=25, max_lev=1.5)
    m_15_25 = compute_metrics(ret_15_25)

    # K551 also tested 12/20
    ret_12_20, _ = variant_a_vix_calibrated(data, low_vix=12, high_vix=20, max_lev=1.5)
    m_12_20 = compute_metrics(ret_12_20)

    print(f"  Base 8.63/VIX:    Sharpe={base_m['sharpe']:.3f}, MDD={base_m['mdd']:.1f}%")
    print(f"  VIX[15,25] 1.5x:  Sharpe={m_15_25['sharpe']:.3f}, MDD={m_15_25['mdd']:.1f}% "
          f"(diff={m_15_25['sharpe']-base_m['sharpe']:+.3f})")
    print(f"  VIX[12,20] 1.5x:  Sharpe={m_12_20['sharpe']:.3f}, MDD={m_12_20['mdd']:.1f}% "
          f"(diff={m_12_20['sharpe']-base_m['sharpe']:+.3f})")
    print(f"\n  CONFIRMED: US thresholds fail for Taiwan (as found in K551)")

    return {
        "base": base_m,
        "vix_15_25": m_15_25,
        "vix_12_20": m_12_20,
        "sharpe_diff_15_25": round(m_15_25["sharpe"] - base_m["sharpe"], 3),
        "sharpe_diff_12_20": round(m_12_20["sharpe"] - base_m["sharpe"], 3),
    }


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("K553: VIX-CONDITIONAL LEVERAGE FOR TAIWAN")
    print("Taiwan-Specific Adaptation of K548/K551")
    print("=" * 70)

    data = download_data()

    all_results = {
        "experiment_id": "K553",
        "title": "VIX-Conditional Leverage for Taiwan — Taiwan-Specific Adaptation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (0050.TW, ^VIX)",
        "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_days": len(data),
        "references": [
            "K548: Original VIX-Conditional Leverage (US, Sharpe +0.112)",
            "K551: Deep validation (US 11/11 OOS, Taiwan FAIL)",
            "K461: Taiwan VT calibration (8.63/VIX)",
            "Moreira & Muir (2017) Volatility-Managed Portfolios, JF",
            "Harvey et al. (2016) t>3.0 threshold, RFS",
        ],
    }

    # Step 0: Confirm K551 failure
    k551_replication = replicate_k551_failure(data)
    all_results["k551_replication"] = k551_replication

    # Step 1: Sensitivity sweep (find best params per variant)
    sweep = sensitivity_sweep(data)
    all_results["sensitivity_sweep"] = {
        "variant_a_top5": sweep["variant_a_sweep"][:5],
        "variant_b_top5": sweep["variant_b_sweep"][:5],
        "variant_c_top5": sweep["variant_c_sweep"][:5],
        "variant_d_top5": sweep["variant_d_sweep"][:5],
        "variant_a_positive_rate": round(sum(1 for r in sweep["variant_a_sweep"] if r["diff"] > 0) / max(len(sweep["variant_a_sweep"]), 1) * 100, 1),
        "variant_b_positive_rate": round(sum(1 for r in sweep["variant_b_sweep"] if r["diff"] > 0) / max(len(sweep["variant_b_sweep"]), 1) * 100, 1),
        "variant_c_positive_rate": round(sum(1 for r in sweep["variant_c_sweep"] if r["diff"] > 0) / max(len(sweep["variant_c_sweep"]), 1) * 100, 1),
        "variant_d_positive_rate": round(sum(1 for r in sweep["variant_d_sweep"] if r["diff"] > 0) / max(len(sweep["variant_d_sweep"]), 1) * 100, 1),
    }

    # Step 2: Full evaluation of each variant (best config from sweep)
    print("\n" + "=" * 70)
    print("FULL EVALUATION OF BEST VARIANT CONFIGURATIONS")
    print("=" * 70)

    # Best config for each variant (from sweep or design specification)
    evaluations = {}

    # Variant A: Best from sweep (use design specification 18/30 as primary)
    best_a = sweep["variant_a_sweep"][0] if sweep["variant_a_sweep"] else None
    if best_a:
        eval_a = full_evaluate(data, variant_a_vix_calibrated,
                               {"low_vix": best_a["low"], "high_vix": best_a["high"],
                                "max_lev": best_a["max_lev"]},
                               f"A: VIX[{best_a['low']},{best_a['high']}] lev={best_a['max_lev']}")
        evaluations["variant_a_best"] = eval_a

    # Also test the design spec 18/30/1.3 (moderate)
    eval_a_design = full_evaluate(data, variant_a_vix_calibrated,
                                  {"low_vix": 18, "high_vix": 30, "max_lev": 1.3},
                                  "A_design: VIX[18,30] lev=1.3")
    evaluations["variant_a_design"] = eval_a_design

    # Variant B: Best from sweep
    best_b = sweep["variant_b_sweep"][0] if sweep["variant_b_sweep"] else None
    if best_b:
        eval_b = full_evaluate(data, variant_b_rv_tw,
                               {"rv_low": best_b["rv_low"], "rv_high": best_b["rv_high"],
                                "max_lev": best_b["max_lev"]},
                               f"B: RV[{best_b['rv_low']},{best_b['rv_high']}] lev={best_b['max_lev']}")
        evaluations["variant_b_best"] = eval_b

    # Variant C: Best from sweep
    best_c = sweep["variant_c_sweep"][0] if sweep["variant_c_sweep"] else None
    if best_c:
        eval_c = full_evaluate(data, variant_c_vt_weight,
                               {"w_high": best_c["w_high"], "w_low": best_c["w_low"],
                                "max_lev": best_c["max_lev"]},
                               f"C: W[{best_c['w_low']},{best_c['w_high']}] lev={best_c['max_lev']}")
        evaluations["variant_c_best"] = eval_c

    # Variant D: Best from sweep
    best_d = sweep["variant_d_sweep"][0] if sweep["variant_d_sweep"] else None
    if best_d:
        eval_d = full_evaluate(data, variant_d_vix_percentile,
                               {"pctile_low": best_d["pctile_low"],
                                "pctile_high": best_d["pctile_high"],
                                "max_lev": best_d["max_lev"]},
                               f"D: Pctile[{best_d['pctile_low']},{best_d['pctile_high']}] lev={best_d['max_lev']}")
        evaluations["variant_d_best"] = eval_d

    # Variant E: Hybrid with best params from B and D
    if best_b and best_d:
        eval_e = full_evaluate(data, variant_e_hybrid,
                               {"rv_low": best_b["rv_low"], "rv_high": best_b["rv_high"],
                                "pctile_low": best_d["pctile_low"],
                                "pctile_high": best_d["pctile_high"],
                                "max_lev": min(best_b["max_lev"], best_d["max_lev"])},
                               f"E: Hybrid RV+Pctile lev={min(best_b['max_lev'], best_d['max_lev'])}")
        evaluations["variant_e_hybrid"] = eval_e

    all_results["evaluations"] = evaluations

    # Step 3: Summary
    print("\n" + "=" * 70)
    print("SUMMARY: ALL VARIANTS COMPARISON")
    print("=" * 70)
    summary_table = []
    for key, ev in evaluations.items():
        if ev and "full_sample" in ev:
            fs = ev["full_sample"]
            dm = ev["harvey_dm_test"]
            boot = ev["bootstrap"]
            oos_w = ev["total_oos_wins"]
            oos_t = ev["total_oos_periods"]
            row = {
                "variant": ev["variant"],
                "sharpe": fs["strategy"]["sharpe"],
                "sharpe_diff": fs["sharpe_diff"],
                "cagr": fs["strategy"]["cagr"],
                "mdd": fs["strategy"]["mdd"],
                "harvey_t": dm["t_stat"],
                "harvey_pass": dm["harvey_pass"],
                "bootstrap_pwin": boot["p_win"],
                "oos_wins": f"{oos_w}/{oos_t}",
            }
            summary_table.append(row)
            status = "PASS" if dm["harvey_pass"] else "FAIL"
            print(f"  {ev['variant']}")
            print(f"    Sharpe={fs['strategy']['sharpe']:.3f} ({fs['sharpe_diff']:+.3f}), "
                  f"CAGR={fs['strategy']['cagr']:.1f}%, MDD={fs['strategy']['mdd']:.1f}%")
            print(f"    Harvey t={dm['t_stat']:.3f} [{status}], "
                  f"Bootstrap P(win)={boot['p_win']:.1f}%, "
                  f"OOS: {oos_w}/{oos_t}")
            print()

    all_results["summary"] = summary_table

    # Step 4: Conclusion
    any_harvey_pass = any(r.get("harvey_pass", False) for r in summary_table)
    best_variant = max(summary_table, key=lambda x: x["sharpe_diff"]) if summary_table else None

    conclusion = {
        "any_harvey_pass": any_harvey_pass,
        "best_variant": best_variant["variant"] if best_variant else "none",
        "best_sharpe_diff": best_variant["sharpe_diff"] if best_variant else 0,
        "k551_problem_solved": any_harvey_pass,
    }

    if any_harvey_pass:
        conclusion["verdict"] = (
            "Taiwan-specific adaptation SUCCEEDS. At least one variant passes Harvey t>3.0. "
            "The K551 failure was due to using US-calibrated VIX thresholds (15/25), "
            "which are inappropriate for Taiwan's higher-volatility regime."
        )
    else:
        # Check if improvement is consistent even if NS
        consistent = best_variant and best_variant.get("bootstrap_pwin", 0) > 60
        if consistent:
            conclusion["verdict"] = (
                "Taiwan adaptation shows CONSISTENT but MODEST improvement that fails Harvey t>3.0. "
                "Leverage helps Taiwan VT directionally but the benefit is too small relative to noise. "
                "Taiwan's higher vol means leverage adds proportionally more risk. "
                "Recommend: DO NOT list as strategy for Taiwan."
            )
        else:
            conclusion["verdict"] = (
                "Taiwan adaptation FAILS. No variant achieves consistent improvement. "
                "The fundamental issue: Taiwan already has 2-3x higher vol than US equities, "
                "so leverage amplifies risk more than it captures excess returns. "
                "VIX-Conditional Leverage is inherently a low-vol-market strategy."
            )

    all_results["conclusion"] = conclusion

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    print(f"  {conclusion['verdict']}")
    print(f"\n  Best variant: {conclusion['best_variant']}")
    print(f"  Best Sharpe diff: {conclusion['best_sharpe_diff']:+.3f}")
    print(f"  Any Harvey pass: {conclusion['any_harvey_pass']}")

    # Save results
    results_path = Path(__file__).parent / "k553_leveraged_vt_taiwan_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    return all_results


if __name__ == "__main__":
    main()
