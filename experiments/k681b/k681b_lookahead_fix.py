#!/usr/bin/env python3
"""K681b: Lookahead Fix — US/EFA VIX Percentile Strategy

Motivation:
  K681 review (2026-05-18) found 1-day lookahead in US/EFA strategies:
  - w_pct_us[i] = 1 - percentile(VIX[i], past252) uses VIX[i] (same day)
  - backtest multiplies weight[i] * return[i] → cannot trade at close(i) using VIX close(i)
  - Article claimed "前一日 VIX" but code used same-day VIX for US/EFA
  - Taiwan correctly used vix_lag1; US/EFA did not

Fix:
  Apply .shift(1) to BOTH pct and 12/VIX US signals:
  - w_pct_us_fixed[i] = 1 - percentile[i-1]  (use yesterday's percentile rank)
  - w_12vix_us_fixed[i] = min(12/VIX[i-1], 1)  (use yesterday's VIX)

Scope:
  Only US (50/50 SPY/GLD) and EFA. Taiwan is already correct (uses vix_lag1).

Expected outcome:
  - If EFA Sharpe drops from 1.843 to <0.8 → major article correction needed
  - If EFA Sharpe stays >1.2 → original claim holds with errata note
  - If US Sharpe DM t drops below 1.96 → cross-market claim weakened

References:
  - K681: original experiment
  - K681 review: experiments/k681/k681_review_lookahead_2026_05_18.md
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# Configuration
START_DATE = "2009-01-01"
END_DATE = "2026-03-27"
EVAL_START = "2010-01-04"
ROLLING_WINDOW = 252
TC_BPS_US = 5
RF_DAILY = 0.04 / 252
SEED = 42
np.random.seed(SEED)

OUTPUT_DIR = Path("experiments/k681b")


def download_data():
    tickers = {"SPY": "SPY", "GLD": "GLD", "EFA": "EFA", "VIX": "^VIX"}
    prices = {}
    for name, ticker in tickers.items():
        print(f"  Downloading {ticker}...")
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[name] = df["Close"].copy()
        prices[name].name = name
    all_prices = pd.concat(prices.values(), axis=1)
    all_prices.columns = list(prices.keys())
    all_prices = all_prices.ffill()
    returns = all_prices.pct_change()
    returns.columns = [f"{c}_ret" for c in all_prices.columns]
    data = pd.concat([all_prices, returns], axis=1)
    data = data.dropna(subset=["VIX"])
    print(f"  Data: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} rows")
    return data


def compute_signals(data):
    """Compute VIX percentile and derive BOTH original (lookahead) and fixed (no lookahead) weights."""
    vix = data["VIX"].values
    n = len(vix)

    # Same-day percentile (original K681 — lookahead)
    pct_original = np.full(n, np.nan)
    for i in range(ROLLING_WINDOW, n):
        window_vals = vix[i - ROLLING_WINDOW:i]
        pct_original[i] = sp_stats.percentileofscore(window_vals, vix[i]) / 100.0

    data = data.copy()
    data["pct_orig"] = pct_original
    data["vix_lag1"] = data["VIX"].shift(1)

    # Fixed: shift pct by 1 (use yesterday's percentile for today's trade)
    data["pct_fixed"] = data["pct_orig"].shift(1)

    # US/EFA weights — original (lookahead)
    data["w_pct_us_orig"] = 1.0 - data["pct_orig"]
    data["w_12vix_us_orig"] = np.minimum(12.0 / data["VIX"], 1.0)

    # US/EFA weights — fixed (no lookahead)
    data["w_pct_us_fixed"] = 1.0 - data["pct_fixed"]
    data["w_12vix_us_fixed"] = np.minimum(12.0 / data["vix_lag1"], 1.0)

    return data


def backtest_portfolio(data, ret_cols, alloc_weights, weight_col, name, tc_bps):
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    portfolio_ret = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    df["_port_ret"] = portfolio_ret
    valid = df["_port_ret"].notna() & df[weight_col].notna()
    df = df[valid]
    if len(df) < 100:
        return None

    wa = df[weight_col].values
    ret = df["_port_ret"].values
    tc_rate = tc_bps / 10000.0
    sr = np.zeros(len(df))
    prev_w = 0.0
    for i in range(len(df)):
        w = wa[i]
        if np.isnan(w):
            w = prev_w
        tc = abs(w - prev_w) * tc_rate
        sr[i] = w * ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    ann_ret = np.mean(sr) * 252
    ann_vol = np.std(sr, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0
    cum = np.cumprod(1 + sr)
    n_years = len(df) / 252.0
    cagr = (cum[-1]) ** (1 / n_years) - 1
    mdd = np.min((cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum))

    return {
        "strategy": name,
        "sharpe": round(sharpe, 3),
        "cagr_pct": round(cagr * 100, 2),
        "mdd_pct": round(mdd * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
    }


def backtest_single(data, ret_col, weight_col, name, tc_bps):
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    valid = df[ret_col].notna() & df[weight_col].notna()
    df = df[valid]
    if len(df) < 100:
        return None

    wa = df[weight_col].values
    ret = df[ret_col].values
    tc_rate = tc_bps / 10000.0
    sr = np.zeros(len(df))
    prev_w = 0.0
    for i in range(len(df)):
        w = wa[i]
        if np.isnan(w):
            w = prev_w
        tc = abs(w - prev_w) * tc_rate
        sr[i] = w * ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    ann_ret = np.mean(sr) * 252
    ann_vol = np.std(sr, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0
    cum = np.cumprod(1 + sr)
    n_years = len(df) / 252.0
    cagr = (cum[-1]) ** (1 / n_years) - 1
    mdd = np.min((cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum))

    return {
        "strategy": name,
        "sharpe": round(sharpe, 3),
        "cagr_pct": round(cagr * 100, 2),
        "mdd_pct": round(mdd * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "n_days": len(df),
    }


def dm_ttest_portfolio(data, ret_cols, alloc_weights, wc_a, wc_b):
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    port_ret = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    df["_port"] = port_ret
    valid = df["_port"].notna() & df[wc_a].notna() & df[wc_b].notna()
    df = df[valid]
    ret = df["_port"].values
    ra = df[wc_a].values * ret + (1 - df[wc_a].values) * RF_DAILY
    rb = df[wc_b].values * ret + (1 - df[wc_b].values) * RF_DAILY
    diff = ra - rb
    diff = diff[~np.isnan(diff)]
    t = float(np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(len(diff))))
    p = float(2 * sp_stats.t.sf(abs(t), df=len(diff) - 1))
    return {"t_stat": round(t, 3), "p_value": round(p, 4), "harvey_pass": abs(t) > 3.0, "n_obs": len(diff)}


def dm_ttest_single(data, ret_col, wc_a, wc_b):
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    valid = df[ret_col].notna() & df[wc_a].notna() & df[wc_b].notna()
    df = df[valid]
    ret = df[ret_col].values
    ra = df[wc_a].values * ret + (1 - df[wc_a].values) * RF_DAILY
    rb = df[wc_b].values * ret + (1 - df[wc_b].values) * RF_DAILY
    diff = ra - rb
    diff = diff[~np.isnan(diff)]
    t = float(np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(len(diff))))
    p = float(2 * sp_stats.t.sf(abs(t), df=len(diff) - 1))
    return {"t_stat": round(t, 3), "p_value": round(p, 4), "harvey_pass": abs(t) > 3.0, "n_obs": len(diff)}


def main():
    print("K681b: Lookahead Fix — US/EFA VIX Percentile Strategy")
    print("=" * 60)

    print("\n[1] Downloading data...")
    data = download_data()

    print("\n[2] Computing signals (original + fixed)...")
    data = compute_signals(data)

    results = {"experiment_id": "k681b", "date": datetime.now(timezone.utc).isoformat(),
               "fix_applied": "shift(1) on pct and 12/VIX for US/EFA", "eval_period": EVAL_START + " to " + END_DATE}

    print("\n[3] US (50/50 SPY/GLD) Backtest...")
    us = {}
    # Original (lookahead)
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_pct_us_orig", "Percentile-ORIG", TC_BPS_US)
    if r: us["pct_original"] = r; print(f"  Pct ORIGINAL: Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%")
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_12vix_us_orig", "12VIX-ORIG", TC_BPS_US)
    if r: us["vix12_original"] = r; print(f"  12VIX ORIGINAL: Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%")
    # Fixed (no lookahead)
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_pct_us_fixed", "Percentile-FIXED", TC_BPS_US)
    if r: us["pct_fixed"] = r; print(f"  Pct FIXED:    Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%")
    r = backtest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_12vix_us_fixed", "12VIX-FIXED", TC_BPS_US)
    if r: us["vix12_fixed"] = r; print(f"  12VIX FIXED:  Sharpe={r['sharpe']:.3f}, CAGR={r['cagr_pct']:.2f}%")
    # DM tests
    dm_orig = dm_ttest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_pct_us_orig", "w_12vix_us_orig")
    dm_fixed = dm_ttest_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5], "w_pct_us_fixed", "w_12vix_us_fixed")
    us["dm_original"] = dm_orig; us["dm_fixed"] = dm_fixed
    print(f"  DM ORIGINAL: t={dm_orig['t_stat']:.3f}, Harvey={dm_orig['harvey_pass']}")
    print(f"  DM FIXED:    t={dm_fixed['t_stat']:.3f}, Harvey={dm_fixed['harvey_pass']}")
    results["us"] = us

    print("\n[4] EFA (International Developed) Backtest...")
    efa = {}
    r = backtest_single(data, "EFA_ret", "w_pct_us_orig", "Percentile-ORIG", TC_BPS_US)
    if r: efa["pct_original"] = r; print(f"  Pct ORIGINAL: Sharpe={r['sharpe']:.3f}")
    r = backtest_single(data, "EFA_ret", "w_12vix_us_orig", "12VIX-ORIG", TC_BPS_US)
    if r: efa["vix12_original"] = r; print(f"  12VIX ORIGINAL: Sharpe={r['sharpe']:.3f}")
    r = backtest_single(data, "EFA_ret", "w_pct_us_fixed", "Percentile-FIXED", TC_BPS_US)
    if r: efa["pct_fixed"] = r; print(f"  Pct FIXED:    Sharpe={r['sharpe']:.3f}")
    r = backtest_single(data, "EFA_ret", "w_12vix_us_fixed", "12VIX-FIXED", TC_BPS_US)
    if r: efa["vix12_fixed"] = r; print(f"  12VIX FIXED:  Sharpe={r['sharpe']:.3f}")
    dm_orig = dm_ttest_single(data, "EFA_ret", "w_pct_us_orig", "w_12vix_us_orig")
    dm_fixed = dm_ttest_single(data, "EFA_ret", "w_pct_us_fixed", "w_12vix_us_fixed")
    efa["dm_original"] = dm_orig; efa["dm_fixed"] = dm_fixed
    print(f"  DM ORIGINAL: t={dm_orig['t_stat']:.3f}, Harvey={dm_orig['harvey_pass']}")
    print(f"  DM FIXED:    t={dm_fixed['t_stat']:.3f}, Harvey={dm_fixed['harvey_pass']}")
    results["efa"] = efa

    # Summary
    print("\n[5] Summary Comparison:")
    print(f"{'Market':<25} {'Orig Sharpe':>12} {'Fixed Sharpe':>12} {'Delta':>8} {'Orig DM-t':>10} {'Fixed DM-t':>10}")
    print("-" * 80)
    us_orig = us.get("pct_original", {}).get("sharpe", "N/A")
    us_fixed = us.get("pct_fixed", {}).get("sharpe", "N/A")
    efa_orig = efa.get("pct_original", {}).get("sharpe", "N/A")
    efa_fixed = efa.get("pct_fixed", {}).get("sharpe", "N/A")
    us_delta = round(us_fixed - us_orig, 3) if isinstance(us_orig, float) else "N/A"
    efa_delta = round(efa_fixed - efa_orig, 3) if isinstance(efa_orig, float) else "N/A"
    print(f"{'US (50/50 SPY/GLD)':<25} {us_orig:>12} {us_fixed:>12} {us_delta:>8} {us['dm_original']['t_stat']:>10} {us['dm_fixed']['t_stat']:>10}")
    print(f"{'EFA':<25} {efa_orig:>12} {efa_fixed:>12} {efa_delta:>8} {efa['dm_original']['t_stat']:>10} {efa['dm_fixed']['t_stat']:>10}")

    # Interpretation
    interpretation = []
    if isinstance(efa_fixed, float):
        if efa_fixed >= 1.2:
            interpretation.append("EFA result robust after lookahead fix — original claim holds with errata")
        elif efa_fixed >= 0.8:
            interpretation.append("EFA result significantly reduced — article needs downward revision")
        else:
            interpretation.append("EFA result collapsed — major article correction or retraction needed")

    results["summary_comparison"] = {
        "us_pct_sharpe_original": us_orig, "us_pct_sharpe_fixed": us_fixed, "us_sharpe_delta": us_delta,
        "efa_pct_sharpe_original": efa_orig, "efa_pct_sharpe_fixed": efa_fixed, "efa_sharpe_delta": efa_delta,
        "us_dm_t_original": us["dm_original"]["t_stat"], "us_dm_t_fixed": us["dm_fixed"]["t_stat"],
        "efa_dm_t_original": efa["dm_original"]["t_stat"], "efa_dm_t_fixed": efa["dm_fixed"]["t_stat"],
    }
    results["interpretation"] = interpretation
    results["parent_experiment"] = "k681"
    results["lookahead_fix"] = "w_pct_us = (1-pct).shift(1); w_12vix_us = min(12/VIX, 1).shift(1)"

    out_path = OUTPUT_DIR / "k681b_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out_path}")

    for interp in interpretation:
        print(f"  → {interp}")


if __name__ == "__main__":
    main()
