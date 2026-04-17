#!/usr/bin/env python3
"""
K1197: Paper 1 GJR vs EWMA Crisis Period Robustness
=====================================================
Worktree: agent-a73db749
Task: K1197 — Compare GJR-GARCH(1,1,1) vs EWMA volatility-targeting strategies
      during 3 designated crisis periods to validate Paper 1 crisis robustness claims.

PURPOSE:
  Reproduce / validate KB J6 claim:
    "EWMA(0.97) Sharpe 0.828 >= GJR 0.782 (5/5 assets), MDD 12.3% ≈ 12.5%"
  And assess per-crisis GJR vs EWMA advantage on MDD, Sharpe, VaR violations.

CRISIS PERIODS (Paper 1 designated):
  1. GFC 2008        : 2008-09-15 → 2009-03-09
  2. COVID 2020      : 2020-02-20 → 2020-03-23
  3. Rate Hike 2022  : 2022-01-03 → 2022-10-12

ASSETS:
  Primary: SPY
  Cross-check: GLD, TLT, BTC-USD, EEM

METHODOLOGY:
  - GJR-GARCH(1,1,1) with Student-t distribution (arch library)
  - EWMA(lambda=0.94) and EWMA(lambda=0.97)
  - Volatility Targeting (VT): w_t = sigma_target / sigma_t-1 (lagged, no lookahead)
  - sigma_target = 10% annualized
  - Max leverage cap = 1.5
  - Metrics: Sharpe (RF=4% annual), MDD, VaR 1% violations
  - Window: 500 trading days for GJR rolling estimation
  - seed=42

REFERENCES:
  - Engle & Ng (1993) — leverage effect in volatility
  - Glosten, Jagannathan & Runkle (1993) — GJR-GARCH
  - RiskMetrics (1994/1996) — EWMA lambda
  - J6 KB: EWMA vs GJR full-period comparison (Sharpe 0.828 vs 0.782)
  - gjr_vs_ewma_crisis stub (experiments/gjr_vs_ewma_crisis/gjr_vs_ewma_crisis.py)
  - K1185: Paper 1 Table 4 VaR (basis for OOS period alignment)

NO LOOKAHEAD: signal from sigma(t-1), position at t
SEED: 42
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy.stats import norm

warnings.filterwarnings("ignore")

# =====================================================================
# CONFIG
# =====================================================================
np.random.seed(42)

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "k1197_results.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "run.log")

WINDOW = 500          # rolling GJR estimation window (days)
LAMBDA_94 = 0.94
LAMBDA_97 = 0.97
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

DATA_START = "2005-01-01"   # enough lookback for 500-day window before GFC 2008

# Crisis periods (Paper 1 designated + extension)
CRISES = [
    ("GFC 2008",       "2008-09-15", "2009-03-09"),
    ("COVID 2020",     "2020-02-20", "2020-03-23"),
    ("Rate Hike 2022", "2022-01-03", "2022-10-12"),
]

# Full OOS period (aligned with Paper 1)
OOS_START = "2017-01-01"
OOS_END   = "2025-12-31"

# Assets
PRIMARY_ASSET = "SPY"
CROSS_CHECK_ASSETS = ["GLD", "TLT", "BTC-USD", "EEM"]
ALL_ASSETS = [PRIMARY_ASSET] + CROSS_CHECK_ASSETS

# KB J6 reference values for comparison
KB_J6 = {
    "ewma_sharpe": 0.828,
    "gjr_sharpe":  0.782,
    "ewma_mdd":   -0.123,
    "gjr_mdd":    -0.125,
    "win_count":   5,    # EWMA wins on Sharpe in 5/5 assets
}


def log(msg, fh=None):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


# =====================================================================
# GARCH estimation helper
# =====================================================================

def rolling_gjr_forecast(returns_arr_pct, window):
    """
    Returns array of one-step-ahead GJR-GARCH sigma forecasts (decimal scale).
    Uses rolling window estimation.
    gjr_sigma[i] = forecast for day i using data[i-window:i]
    """
    n = len(returns_arr_pct)
    gjr_sigma = np.full(n, np.nan)
    gjr_gamma = np.full(n, np.nan)

    for i in range(window, n):
        w = returns_arr_pct[i - window:i]
        try:
            m = arch_model(w, vol="GARCH", p=1, o=1, q=1,
                           dist="studentst", mean="constant",
                           rescale=False)
            res = m.fit(disp="off", show_warning=False,
                        options={"maxiter": 200, "ftol": 1e-6})
            fc = res.forecast(horizon=1, reindex=False)
            var_fc = fc.variance.values[-1, 0]
            gjr_sigma[i] = np.sqrt(var_fc) / 100.0   # pct → decimal
            g = res.params.get("gamma[1]", np.nan)
            gjr_gamma[i] = float(g)
        except Exception:
            # carry forward
            if i > window and not np.isnan(gjr_sigma[i - 1]):
                gjr_sigma[i] = gjr_sigma[i - 1]
                gjr_gamma[i] = gjr_gamma[i - 1]
    return gjr_sigma, gjr_gamma


def ewma_forecast(returns_dec, window, lam):
    """
    Returns array of EWMA sigma forecasts (decimal scale).
    Initialized with sample variance of first `window` obs.
    """
    n = len(returns_dec)
    ewma_var = np.full(n, np.nan)
    init_var = np.var(returns_dec[:window])
    ewma_var[window - 1] = init_var
    for i in range(window, n):
        ewma_var[i] = lam * ewma_var[i - 1] + (1 - lam) * returns_dec[i - 1] ** 2
    return np.sqrt(ewma_var)


def compute_vt_weights(sigma, target_vol_daily, max_lev):
    """
    Compute lagged VT weights: w[i] = target / sigma[i-1], capped at max_lev.
    Returns weight array (length same as sigma; positions 0..window nan, position i+1 uses sigma[i]).
    """
    n = len(sigma)
    weights = np.full(n, np.nan)
    for i in range(n - 1):
        if not np.isnan(sigma[i]) and sigma[i] > 0:
            weights[i + 1] = min(target_vol_daily / sigma[i], max_lev)
    return weights


def sharpe(ret_arr, rf_daily, ann=252):
    r = ret_arr[~np.isnan(ret_arr)]
    if len(r) < 2:
        return np.nan
    excess = r - rf_daily
    mu = np.mean(excess) * ann
    sd = np.std(r, ddof=1) * np.sqrt(ann)
    return mu / sd if sd > 0 else np.nan


def max_drawdown(ret_arr):
    r = ret_arr[~np.isnan(ret_arr)]
    if len(r) == 0:
        return np.nan
    cum = np.exp(np.nancumsum(r))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(np.min(dd))


def var_violations(ret_arr, sigma_arr, alpha=0.01):
    """Count VaR 1% violations (actual loss > predicted VaR)."""
    violations = 0
    total = 0
    for i in range(len(ret_arr)):
        if np.isnan(ret_arr[i]) or np.isnan(sigma_arr[i]):
            continue
        var = -sigma_arr[i] * norm.ppf(alpha)  # 1-day VaR (positive threshold)
        if ret_arr[i] < -var:
            violations += 1
        total += 1
    if total == 0:
        return np.nan, np.nan
    return violations, violations / total * 100


# =====================================================================
# PER-ASSET ANALYSIS
# =====================================================================

def analyze_asset(ticker, fh):
    log(f"\n{'='*60}", fh)
    log(f"ASSET: {ticker}", fh)
    log(f"{'='*60}", fh)

    # --- Download ---
    raw = yf.download(ticker, start=DATA_START, end="2025-12-31",
                      progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw["Close"].dropna()
    returns = np.log(prices / prices.shift(1)).dropna()
    n = len(returns)
    log(f"  Data: {returns.index[0].date()} to {returns.index[-1].date()}, n={n}", fh)

    if n < WINDOW + 100:
        log(f"  SKIP: insufficient data", fh)
        return None

    ret_arr = returns.values
    ret_pct = ret_arr * 100.0

    # --- Estimates ---
    log(f"  Running rolling GJR-GARCH(1,1,1) w={WINDOW}...", fh)
    t0 = time.time()
    gjr_sigma, gjr_gamma = rolling_gjr_forecast(ret_pct, WINDOW)
    log(f"  GJR done in {time.time()-t0:.0f}s", fh)

    ewma_sigma_94 = ewma_forecast(ret_arr, WINDOW, LAMBDA_94)
    ewma_sigma_97 = ewma_forecast(ret_arr, WINDOW, LAMBDA_97)
    log(f"  EWMA done", fh)

    # --- VT Weights (lagged) ---
    gjr_w    = compute_vt_weights(gjr_sigma,     TARGET_VOL_DAILY, MAX_LEVERAGE)
    ewma94_w = compute_vt_weights(ewma_sigma_94, TARGET_VOL_DAILY, MAX_LEVERAGE)
    ewma97_w = compute_vt_weights(ewma_sigma_97, TARGET_VOL_DAILY, MAX_LEVERAGE)

    # --- Strategy Returns ---
    gjr_ret    = ret_arr * gjr_w
    ewma94_ret = ret_arr * ewma94_w
    ewma97_ret = ret_arr * ewma97_w
    bh_ret     = ret_arr.copy()

    # Create DataFrame
    df = pd.DataFrame({
        "ret":       ret_arr,
        "gjr_ret":   gjr_ret,
        "e94_ret":   ewma94_ret,
        "e97_ret":   ewma97_ret,
        "bh_ret":    bh_ret,
        "gjr_sigma": gjr_sigma,
        "e94_sigma": ewma_sigma_94,
        "e97_sigma": ewma_sigma_97,
        "gjr_gamma": gjr_gamma,
        "gjr_w":     gjr_w,
        "e94_w":     ewma94_w,
        "e97_w":     ewma97_w,
    }, index=returns.index)

    # --- Full OOS Metrics (for KB J6 comparison) ---
    oos_mask = (df.index >= pd.Timestamp(OOS_START)) & (df.index <= pd.Timestamp(OOS_END))
    oos_df = df.loc[oos_mask].dropna(subset=["gjr_ret", "e97_ret"])

    full_oos = {
        "n_oos": len(oos_df),
        "gjr_sharpe":   round(sharpe(oos_df["gjr_ret"].values, RF_DAILY), 3),
        "ewma97_sharpe":round(sharpe(oos_df["e97_ret"].values, RF_DAILY), 3),
        "ewma94_sharpe":round(sharpe(oos_df["e94_ret"].values, RF_DAILY), 3),
        "gjr_mdd":      round(max_drawdown(oos_df["gjr_ret"].values), 4),
        "ewma97_mdd":   round(max_drawdown(oos_df["e97_ret"].values), 4),
        "ewma94_mdd":   round(max_drawdown(oos_df["e94_ret"].values), 4),
    }
    log(f"  OOS Sharpe — GJR: {full_oos['gjr_sharpe']:.3f}, EWMA(0.97): {full_oos['ewma97_sharpe']:.3f}", fh)
    log(f"  OOS MDD   — GJR: {full_oos['gjr_mdd']:.1%}, EWMA(0.97): {full_oos['ewma97_mdd']:.1%}", fh)

    # --- Per-Crisis Analysis ---
    crisis_results = []
    for crisis_name, c_start, c_end in CRISES:
        c_start_ts = pd.Timestamp(c_start)
        c_end_ts   = pd.Timestamp(c_end)

        cmask = (df.index >= c_start_ts) & (df.index <= c_end_ts)
        cdf = df.loc[cmask].dropna(subset=["gjr_ret", "e97_ret"])

        if len(cdf) < 5:
            log(f"  Crisis {crisis_name}: skip (n={len(cdf)})", fh)
            crisis_results.append({"crisis": crisis_name, "skip": True})
            continue

        gjr_s  = sharpe(cdf["gjr_ret"].values, RF_DAILY)
        e97_s  = sharpe(cdf["e97_ret"].values, RF_DAILY)
        e94_s  = sharpe(cdf["e94_ret"].values, RF_DAILY)
        bh_s   = sharpe(cdf["bh_ret"].values, RF_DAILY)

        gjr_mdd  = max_drawdown(cdf["gjr_ret"].values)
        e97_mdd  = max_drawdown(cdf["e97_ret"].values)
        e94_mdd  = max_drawdown(cdf["e94_ret"].values)
        bh_mdd   = max_drawdown(cdf["bh_ret"].values)

        gjr_viol, gjr_viol_rate = var_violations(cdf["ret"].values, cdf["gjr_sigma"].values)
        e97_viol, e97_viol_rate = var_violations(cdf["ret"].values, cdf["e97_sigma"].values)

        gjr_better_mdd = gjr_mdd > e97_mdd  # less negative = better
        avg_gamma = float(np.nanmean(cdf["gjr_gamma"].values))

        cr = {
            "crisis": crisis_name,
            "start": str(cdf.index[0].date()),
            "end":   str(cdf.index[-1].date()),
            "n_days": len(cdf),
            "gjr_sharpe":  round(gjr_s, 3)  if not np.isnan(gjr_s)  else None,
            "ewma97_sharpe":round(e97_s,3)  if not np.isnan(e97_s)  else None,
            "ewma94_sharpe":round(e94_s,3)  if not np.isnan(e94_s)  else None,
            "bh_sharpe":   round(bh_s, 3)  if not np.isnan(bh_s)   else None,
            "gjr_mdd":     round(gjr_mdd*100, 2),
            "ewma97_mdd":  round(e97_mdd*100, 2),
            "ewma94_mdd":  round(e94_mdd*100, 2),
            "bh_mdd":      round(bh_mdd*100, 2),
            "gjr_var_violations": gjr_viol,
            "gjr_var_rate_pct":   round(gjr_viol_rate, 2) if gjr_viol_rate else None,
            "ewma97_var_violations": e97_viol,
            "ewma97_var_rate_pct":   round(e97_viol_rate, 2) if e97_viol_rate else None,
            "gjr_better_mdd": bool(gjr_better_mdd),
            "avg_gamma": round(avg_gamma, 4),
            "mdd_premium_pct": round((e97_mdd - gjr_mdd)*100, 2),  # positive = GJR better
        }
        crisis_results.append(cr)

        log(f"  [{crisis_name}] n={cr['n_days']}, "
            f"GJR MDD: {cr['gjr_mdd']:.1f}%,  EWMA(0.97) MDD: {cr['ewma97_mdd']:.1f}%,  "
            f"GJR better: {cr['gjr_better_mdd']}", fh)

    return {
        "ticker": ticker,
        "full_oos": full_oos,
        "crisis_results": crisis_results,
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    with open(LOG_PATH, "w") as fh:
        log("K1197: Paper 1 GJR vs EWMA Crisis Period Robustness", fh)
        log(f"Run started: {datetime.now(timezone.utc).isoformat()}", fh)
        log(f"Config: window={WINDOW}, lambda=[{LAMBDA_94},{LAMBDA_97}], "
            f"target_vol={TARGET_VOL_ANNUAL:.0%}, max_lev={MAX_LEVERAGE}", fh)
        log(f"Crises: {[c[0] for c in CRISES]}", fh)
        log(f"Assets: {ALL_ASSETS}", fh)

        asset_results = []
        for ticker in ALL_ASSETS:
            try:
                result = analyze_asset(ticker, fh)
                if result:
                    asset_results.append(result)
            except Exception as e:
                log(f"  ERROR on {ticker}: {e}", fh)

        # ---- Summary ----
        log("\n" + "="*70, fh)
        log("SUMMARY", fh)
        log("="*70, fh)

        # Full OOS: compare vs KB J6
        log("\n[Full OOS Sharpe vs KB J6]", fh)
        log(f"  KB J6 — EWMA(0.97) Sharpe: {KB_J6['ewma_sharpe']}, GJR Sharpe: {KB_J6['gjr_sharpe']}", fh)
        ewma_sharpe_count = sum(1 for a in asset_results
                                 if a["full_oos"]["ewma97_sharpe"] is not None and
                                    a["full_oos"]["gjr_sharpe"] is not None and
                                    a["full_oos"]["ewma97_sharpe"] >= a["full_oos"]["gjr_sharpe"])
        log(f"  EWMA(0.97) wins Sharpe in {ewma_sharpe_count}/{len(asset_results)} assets", fh)

        # Per-crisis GJR win rate
        log("\n[Per-Crisis GJR Better MDD]", fh)
        crisis_win_table = {}
        for crisis_name, _, _ in CRISES:
            gjr_wins = 0
            total = 0
            for a in asset_results:
                for cr in a["crisis_results"]:
                    if cr["crisis"] == crisis_name and not cr.get("skip"):
                        total += 1
                        if cr["gjr_better_mdd"]:
                            gjr_wins += 1
            crisis_win_table[crisis_name] = {"gjr_wins": gjr_wins, "total": total}
            log(f"  {crisis_name}: GJR wins MDD {gjr_wins}/{total} assets", fh)

        # SPY detail
        spy_res = next((a for a in asset_results if a["ticker"] == "SPY"), None)
        if spy_res:
            log("\n[SPY Detail]", fh)
            for cr in spy_res["crisis_results"]:
                if cr.get("skip"):
                    continue
                log(f"  {cr['crisis']}: GJR MDD={cr['gjr_mdd']:.1f}%, "
                    f"EWMA(0.97) MDD={cr['ewma97_mdd']:.1f}%, "
                    f"MDD premium={cr['mdd_premium_pct']:+.2f}%, "
                    f"avg gamma={cr['avg_gamma']:.4f}", fh)

        # ---- KB J6 Comparison ----
        spy_oos = spy_res["full_oos"] if spy_res else {}
        kb_match_sharpe = (
            spy_oos.get("ewma97_sharpe") is not None and
            spy_oos.get("gjr_sharpe") is not None and
            abs(spy_oos.get("ewma97_sharpe", 0) - KB_J6["ewma_sharpe"]) / abs(KB_J6["ewma_sharpe"]) < 0.20 and
            abs(spy_oos.get("gjr_sharpe", 0) - KB_J6["gjr_sharpe"]) / abs(KB_J6["gjr_sharpe"]) < 0.20
        )
        kb_ewma_wins = ewma_sharpe_count >= 4  # at least 4/5

        if kb_match_sharpe and kb_ewma_wins:
            kb_verdict = "MATCHED"
        elif kb_ewma_wins:
            kb_verdict = "(a) EWMA wins confirmed but Sharpe magnitudes differ"
        elif not kb_ewma_wins:
            kb_verdict = "(b) EWMA win rate < 4/5 — partial match"
        else:
            kb_verdict = "(c) Cannot confirm KB J6 claim"

        log(f"\nKB J6 Verdict: {kb_verdict}", fh)

        # ---- Save Results ----
        output = {
            "experiment": "K1197",
            "title": "Paper 1 GJR vs EWMA Crisis Period Robustness",
            "methodology": "empirical",
            "data_source": "yfinance (SPY, GLD, TLT, BTC-USD, EEM)",
            "data_period": f"{DATA_START} to 2025-12-31",
            "oos_period": f"{OOS_START} to {OOS_END}",
            "config": {
                "window": WINDOW,
                "lambda_94": LAMBDA_94,
                "lambda_97": LAMBDA_97,
                "target_vol_annual": TARGET_VOL_ANNUAL,
                "max_leverage": MAX_LEVERAGE,
                "rf_annual": RF_ANNUAL,
                "seed": 42,
            },
            "kb_j6_reference": KB_J6,
            "crises_analyzed": [c[0] for c in CRISES],
            "asset_results": asset_results,
            "crisis_win_table": crisis_win_table,
            "summary": {
                "ewma97_wins_sharpe_count": ewma_sharpe_count,
                "total_assets": len(asset_results),
                "kb_j6_verdict": kb_verdict,
            },
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with open(RESULTS_PATH, "w") as f:
            json.dump(output, f, indent=2, default=str)

        log(f"\nResults saved to {RESULTS_PATH}", fh)
        log("K1197 COMPLETE", fh)

    return output


if __name__ == "__main__":
    result = main()
    print("\n[K1197 DONE]")
    print(f"KB J6 verdict: {result['summary']['kb_j6_verdict']}")
    print(f"EWMA wins Sharpe: {result['summary']['ewma97_wins_sharpe_count']}/{result['summary']['total_assets']}")
