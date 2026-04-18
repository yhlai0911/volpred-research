"""
K145: Predictive Model Selection via CV(gamma) — From Post-hoc to Ex-ante Guidance
===================================================================================
[提出: Gemini R5a, 執行: Claude]

Background:
  K143 validated CV(gamma) as a mechanism classifier (stable vs unstable gamma).
  This experiment tests: can PREVIOUS-period CV(gamma) PREDICT which model to use
  in the NEXT period?

Design:
  1. Rolling 504d GJR-GARCH estimation with 252d sub-windows for CV(gamma)
  2. Stability threshold: CV < 1.0 → stable (use GJR), CV ≥ 1.0 → unstable (use GARCH/EWMA)
  3. Adaptive Model Selection Rule:
     - if CV(gamma)_{t-1} < threshold → next period use GJR-GARCH
     - if CV(gamma)_{t-1} ≥ threshold → next period use GARCH(1,1)
  4. Compare Adaptive vs Fixed-GJR vs Fixed-GARCH (QLIKE + DM test)
  5. OOS: last 2 years (2023-2024)
  6. Cross-asset: 15+ assets (equity + commodity + safe haven + crypto)

Outputs:
  1. Rolling CV(gamma) time series (representative assets)
  2. Adaptive vs Fixed QLIKE comparison table
  3. CV threshold sensitivity (0.5, 1.0, 1.5, 2.0)
  4. How many assets does Adaptive significantly beat Fixed?
  5. Conclusion: can CV(gamma) guide real-time model selection?

Data: yfinance daily, 2010-2024
Methodology: empirical (rolling window OOS)

Usage:
    uv run python experiments/predictive_model_selection/predictive_model_selection.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ======================================================================
# CONFIG
# ======================================================================
ASSETS = {
    # --- Equity (8) ---
    "SPY":  {"ticker": "SPY",    "category": "equity",    "desc": "S&P 500"},
    "QQQ":  {"ticker": "QQQ",    "category": "equity",    "desc": "Nasdaq 100"},
    "IWM":  {"ticker": "IWM",    "category": "equity",    "desc": "Russell 2000"},
    "EEM":  {"ticker": "EEM",    "category": "equity",    "desc": "Emerging Markets"},
    "EFA":  {"ticker": "EFA",    "category": "equity",    "desc": "EAFE Developed"},
    "XLF":  {"ticker": "XLF",    "category": "equity",    "desc": "US Financials"},
    "XLE":  {"ticker": "XLE",    "category": "equity",    "desc": "US Energy"},
    "XLK":  {"ticker": "XLK",    "category": "equity",    "desc": "US Technology"},
    # --- Safe haven / Fixed income (4) ---
    "GLD":  {"ticker": "GLD",    "category": "safe_haven", "desc": "Gold"},
    "TLT":  {"ticker": "TLT",    "category": "safe_haven", "desc": "20+ Year Treasury"},
    "IEF":  {"ticker": "IEF",    "category": "safe_haven", "desc": "7-10 Year Treasury"},
    "SLV":  {"ticker": "SLV",    "category": "safe_haven", "desc": "Silver"},
    # --- Commodity (3) ---
    "USO":  {"ticker": "USO",    "category": "commodity",  "desc": "Crude Oil"},
    "DBA":  {"ticker": "DBA",    "category": "commodity",  "desc": "Agriculture"},
    "UNG":  {"ticker": "UNG",    "category": "commodity",  "desc": "Natural Gas"},
    # --- Crypto (2) ---
    "BTC":  {"ticker": "BTC-USD", "category": "crypto",    "desc": "Bitcoin"},
    "ETH":  {"ticker": "ETH-USD", "category": "crypto",    "desc": "Ethereum"},
}

DATA_START     = "2010-01-01"
DATA_END       = "2024-12-31"
OOS_START      = "2023-01-01"     # last 2 years
GARCH_WINDOW   = 504             # rolling estimation window
SUB_WINDOW     = 252             # sub-window for CV(gamma) calculation
CV_THRESHOLDS  = [0.5, 1.0, 1.5, 2.0]  # sensitivity analysis
MIN_OBS        = 2000            # minimum days required
FORECAST_HORIZON = 1             # 1-day ahead

np.random.seed(42)

print("=" * 80)
print("K145: PREDICTIVE MODEL SELECTION VIA CV(gamma)")
print("     From Post-hoc Validation to Ex-ante Guidance")
print("=" * 80)
print(f"  [提出: Gemini R5a, 執行: Claude]")
print(f"  Assets:          {len(ASSETS)} targets across 4 categories")
print(f"  Full period:     {DATA_START} to {DATA_END}")
print(f"  OOS period:      {OOS_START} to {DATA_END}")
print(f"  GARCH window:    {GARCH_WINDOW}d")
print(f"  Sub-window:      {SUB_WINDOW}d (for CV calculation)")
print(f"  CV thresholds:   {CV_THRESHOLDS}")
print(f"  Min obs:         {MIN_OBS} days")
print()


# ======================================================================
# 1. DATA LOADING
# ======================================================================
print("[1] Loading data via yfinance...")
t0 = time.time()

import yfinance as yf

returns_all = {}
asset_info = {}

for name, info in ASSETS.items():
    try:
        df = yf.download(info["ticker"], start=DATA_START, end=DATA_END, progress=False)
        if df is None or len(df) < MIN_OBS:
            print(f"    {name}: SKIPPED (only {len(df) if df is not None else 0} days, need {MIN_OBS})")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        close = df["Close"].dropna()
        ret = np.log(close / close.shift(1)).dropna() * 100  # pct log returns
        returns_all[name] = ret
        asset_info[name] = info
        print(f"    {name} ({info['desc']}): {len(ret)} days "
              f"({ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')}) "
              f"[{info['category']}]")
    except Exception as e:
        print(f"    {name}: FAILED ({e})")

VALID_ASSETS = list(asset_info.keys())
N_ASSETS = len(VALID_ASSETS)
print(f"\n    Successfully loaded {N_ASSETS} assets in {time.time()-t0:.1f}s")
print()


# ======================================================================
# 2. HELPER FUNCTIONS
# ======================================================================

def fit_gjr_garch(returns: pd.Series) -> dict | None:
    """Fit GJR-GARCH(1,1) with Student-t distribution."""
    from arch import arch_model
    try:
        am = arch_model(returns, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
        res = am.fit(disp="off", show_warning=False)
        gamma = res.params.get("gamma[1]", res.params.get("o[1]", 0))
        return {
            "model": "GJR",
            "gamma": gamma,
            "alpha": res.params.get("alpha[1]", 0),
            "beta": res.params.get("beta[1]", 0),
            "omega": res.params.get("omega", 0),
            "cond_vol": res.conditional_volatility,
            "forecast_var": res.forecast(horizon=1).variance.iloc[-1, 0],
            "aic": res.aic,
            "result": res,
        }
    except Exception:
        return None


def fit_garch(returns: pd.Series) -> dict | None:
    """Fit standard GARCH(1,1) with Student-t distribution."""
    from arch import arch_model
    try:
        am = arch_model(returns, vol="Garch", p=1, q=1, dist="t", mean="Constant")
        res = am.fit(disp="off", show_warning=False)
        return {
            "model": "GARCH",
            "gamma": 0.0,
            "alpha": res.params.get("alpha[1]", 0),
            "beta": res.params.get("beta[1]", 0),
            "omega": res.params.get("omega", 0),
            "cond_vol": res.conditional_volatility,
            "forecast_var": res.forecast(horizon=1).variance.iloc[-1, 0],
            "aic": res.aic,
            "result": res,
        }
    except Exception:
        return None


def compute_ewma_var(returns: pd.Series, lam: float = 0.97) -> float:
    """Compute EWMA(lambda) 1-step ahead variance forecast."""
    r = returns.values
    var_t = r[0] ** 2
    for i in range(1, len(r)):
        var_t = lam * var_t + (1 - lam) * r[i] ** 2
    return var_t


def ewma_variance_series(returns: pd.Series, lam: float = 0.97) -> np.ndarray:
    """Full EWMA variance path."""
    r = returns.values
    n = len(r)
    var = np.zeros(n)
    var[0] = r[0] ** 2
    for i in range(1, n):
        var[i] = lam * var[i - 1] + (1 - lam) * r[i] ** 2
    return var


def compute_cv_gamma(returns: pd.Series, window: int = 504, sub_window: int = 252) -> float:
    """
    Compute CV(gamma) = std(gamma_sub) / |mean(gamma_sub)|
    using non-overlapping sub-windows within the main window.
    """
    from arch import arch_model
    n = len(returns)
    if n < window:
        return np.nan

    data = returns.iloc[-window:]
    n_subs = window // sub_window
    if n_subs < 2:
        return np.nan

    gammas = []
    for i in range(n_subs):
        start_idx = i * sub_window
        end_idx = start_idx + sub_window
        sub_data = data.iloc[start_idx:end_idx]
        try:
            am = arch_model(sub_data, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
            res = am.fit(disp="off", show_warning=False)
            g = res.params.get("gamma[1]", res.params.get("o[1]", 0))
            gammas.append(g)
        except Exception:
            continue

    if len(gammas) < 2:
        return np.nan

    mean_g = np.mean(gammas)
    std_g = np.std(gammas, ddof=1)

    if abs(mean_g) < 1e-8:
        return np.inf  # unstable

    return std_g / abs(mean_g)


def qlike_loss(realized_var: np.ndarray, forecast_var: np.ndarray) -> float:
    """QLIKE loss function: mean(log(h) + r^2/h)."""
    mask = (forecast_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    rv = realized_var[mask]
    fv = forecast_var[mask]
    if len(rv) == 0:
        return np.inf
    return np.mean(np.log(fv) + rv / fv)


def dm_test(loss1: np.ndarray, loss2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test. Returns (t-stat, p-value).
    Negative t-stat means model 1 is better (lower loss)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    if len(d) < 10:
        return 0.0, 1.0
    mean_d = np.mean(d)
    # Newey-West HAC variance with lag = int(len^(1/3))
    n = len(d)
    lag = max(1, int(n ** (1 / 3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = mean_d / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value


# ======================================================================
# 3. ROLLING OOS EVALUATION
# ======================================================================
print("[2] Rolling OOS evaluation...")
print(f"    OOS start: {OOS_START}")
print(f"    GARCH window: {GARCH_WINDOW}d, CV sub-window: {SUB_WINDOW}d")
print()

t0 = time.time()

# For each asset, do rolling 1-day-ahead forecasts
# Track: GJR forecast, GARCH forecast, EWMA forecast, CV(gamma)
# Then compute adaptive forecasts based on CV(gamma) from previous window

results = {}

for asset_idx, name in enumerate(VALID_ASSETS):
    print(f"  [{asset_idx+1}/{N_ASSETS}] {name} ({asset_info[name]['desc']})...", flush=True)
    t_asset = time.time()

    ret = returns_all[name]

    # Find OOS start index
    oos_mask = ret.index >= OOS_START
    if oos_mask.sum() < 100:
        print(f"    SKIPPED: only {oos_mask.sum()} OOS days")
        continue

    oos_indices = ret.index[oos_mask]
    # We need at least GARCH_WINDOW days before first OOS day
    first_oos_loc = ret.index.get_loc(oos_indices[0])
    if first_oos_loc < GARCH_WINDOW:
        print(f"    SKIPPED: not enough in-sample data ({first_oos_loc} < {GARCH_WINDOW})")
        continue

    n_oos = len(oos_indices)

    # Storage for rolling forecasts
    gjr_forecasts = np.full(n_oos, np.nan)
    garch_forecasts = np.full(n_oos, np.nan)
    ewma_forecasts = np.full(n_oos, np.nan)
    cv_gammas = np.full(n_oos, np.nan)
    realized_vars = np.full(n_oos, np.nan)
    gjr_gammas = np.full(n_oos, np.nan)

    # We re-estimate every 21 days (monthly) for speed
    REESTIMATE_FREQ = 21
    last_gjr_result = None
    last_garch_result = None
    last_cv = np.nan

    for i in range(n_oos):
        day_loc = first_oos_loc + i
        day = ret.index[day_loc]

        # Realized variance = r^2 of that day (proxy)
        realized_vars[i] = ret.iloc[day_loc] ** 2

        # Training window
        train_data = ret.iloc[day_loc - GARCH_WINDOW: day_loc]

        # Re-estimate models periodically
        if i % REESTIMATE_FREQ == 0 or last_gjr_result is None:
            gjr_res = fit_gjr_garch(train_data)
            garch_res = fit_garch(train_data)

            if gjr_res is not None:
                last_gjr_result = gjr_res
            if garch_res is not None:
                last_garch_result = garch_res

            # Compute CV(gamma) from train window
            last_cv = compute_cv_gamma(train_data, window=GARCH_WINDOW, sub_window=SUB_WINDOW)

        # GJR forecast
        if last_gjr_result is not None:
            gjr_forecasts[i] = last_gjr_result["forecast_var"]
            gjr_gammas[i] = last_gjr_result["gamma"]

        # GARCH forecast
        if last_garch_result is not None:
            garch_forecasts[i] = last_garch_result["forecast_var"]

        # EWMA forecast
        ewma_forecasts[i] = compute_ewma_var(train_data, lam=0.97)

        # Store CV
        cv_gammas[i] = last_cv

        # Re-estimate models: update forecast with latest data
        # For non-reestimation days, use recursion to update 1-step forecast
        if i % REESTIMATE_FREQ != 0:
            r_prev = ret.iloc[day_loc - 1]  # previous return
            if last_gjr_result is not None:
                alpha = last_gjr_result["alpha"]
                beta = last_gjr_result["beta"]
                gamma = last_gjr_result["gamma"]
                omega = last_gjr_result["omega"]
                prev_var = gjr_forecasts[i - 1] if i > 0 and np.isfinite(gjr_forecasts[i - 1]) else last_gjr_result["forecast_var"]
                indicator = 1.0 if r_prev < 0 else 0.0
                gjr_forecasts[i] = omega + (alpha + gamma * indicator) * r_prev ** 2 + beta * prev_var

            if last_garch_result is not None:
                alpha_g = last_garch_result["alpha"]
                beta_g = last_garch_result["beta"]
                omega_g = last_garch_result["omega"]
                prev_var_g = garch_forecasts[i - 1] if i > 0 and np.isfinite(garch_forecasts[i - 1]) else last_garch_result["forecast_var"]
                garch_forecasts[i] = omega_g + alpha_g * r_prev ** 2 + beta_g * prev_var_g

    # Store results
    results[name] = {
        "category": asset_info[name]["category"],
        "desc": asset_info[name]["desc"],
        "n_oos": n_oos,
        "gjr_forecasts": gjr_forecasts,
        "garch_forecasts": garch_forecasts,
        "ewma_forecasts": ewma_forecasts,
        "cv_gammas": cv_gammas,
        "realized_vars": realized_vars,
        "gjr_gammas": gjr_gammas,
        "oos_dates": oos_indices,
    }

    elapsed = time.time() - t_asset
    mean_cv = np.nanmean(cv_gammas)
    print(f"    {n_oos} OOS days, mean CV(gamma)={mean_cv:.2f}, {elapsed:.1f}s")

print(f"\n    Total rolling evaluation: {time.time()-t0:.1f}s")
print()


# ======================================================================
# 4. ADAPTIVE MODEL SELECTION & COMPARISON
# ======================================================================
print("[3] Adaptive Model Selection: CV(gamma) → model choice")
print()

# Individual QLIKE losses for DM test
def qlike_individual(rv: np.ndarray, fv: np.ndarray) -> np.ndarray:
    """Individual QLIKE loss per observation."""
    mask = (fv > 0) & np.isfinite(rv) & np.isfinite(fv)
    out = np.full(len(rv), np.nan)
    out[mask] = np.log(fv[mask]) + rv[mask] / fv[mask]
    return out


# Table: for each threshold, for each asset, compare Adaptive vs Fixed-GJR vs Fixed-GARCH
print("-" * 110)
print(f"{'Threshold':>10} | {'Asset':>5} | {'Cat':>10} | {'QLIKE_GJR':>10} | {'QLIKE_GARCH':>11} | "
      f"{'QLIKE_EWMA':>10} | {'QLIKE_Adapt':>11} | {'Best':>8} | {'DM(A<GJR)':>10} | {'DM(A<GAR)':>10}")
print("-" * 110)

# Collect summary across thresholds
threshold_summary = {}

for thr in CV_THRESHOLDS:
    wins_vs_gjr = 0
    wins_vs_garch = 0
    sig_wins_vs_gjr = 0
    sig_wins_vs_garch = 0
    total = 0

    asset_rows = []

    for name in sorted(results.keys()):
        res = results[name]
        rv = res["realized_vars"]
        gjr_f = res["gjr_forecasts"]
        garch_f = res["garch_forecasts"]
        ewma_f = res["ewma_forecasts"]
        cv = res["cv_gammas"]

        # Build adaptive forecast: use CV from previous re-estimation
        adaptive_f = np.full(len(rv), np.nan)
        for i in range(len(rv)):
            cv_val = cv[i]  # this is the CV at time of last re-estimation
            if np.isnan(cv_val) or np.isinf(cv_val):
                # Default to GARCH when CV is unknown/infinite (unstable)
                adaptive_f[i] = garch_f[i] if np.isfinite(garch_f[i]) else ewma_f[i]
            elif cv_val < thr:
                # Stable gamma → use GJR
                adaptive_f[i] = gjr_f[i]
            else:
                # Unstable gamma → use GARCH
                adaptive_f[i] = garch_f[i] if np.isfinite(garch_f[i]) else ewma_f[i]

        # Compute QLIKE
        q_gjr = qlike_loss(rv, gjr_f)
        q_garch = qlike_loss(rv, garch_f)
        q_ewma = qlike_loss(rv, ewma_f)
        q_adapt = qlike_loss(rv, adaptive_f)

        # DM tests (adaptive vs each fixed)
        loss_adapt = qlike_individual(rv, adaptive_f)
        loss_gjr = qlike_individual(rv, gjr_f)
        loss_garch = qlike_individual(rv, garch_f)

        dm_vs_gjr_t, dm_vs_gjr_p = dm_test(loss_adapt, loss_gjr)
        dm_vs_garch_t, dm_vs_garch_p = dm_test(loss_adapt, loss_garch)

        best = "Adaptive" if q_adapt <= min(q_gjr, q_garch, q_ewma) else \
               "GJR" if q_gjr <= min(q_garch, q_ewma) else \
               "GARCH" if q_garch <= q_ewma else "EWMA"

        total += 1
        if q_adapt < q_gjr:
            wins_vs_gjr += 1
        if q_adapt < q_garch:
            wins_vs_garch += 1
        if dm_vs_gjr_t < 0 and dm_vs_gjr_p < 0.10:
            sig_wins_vs_gjr += 1
        if dm_vs_garch_t < 0 and dm_vs_garch_p < 0.10:
            sig_wins_vs_garch += 1

        # Fraction of OOS days using GJR vs GARCH
        n_gjr_days = np.sum((cv < thr) & np.isfinite(cv))
        n_garch_days = np.sum((cv >= thr) | ~np.isfinite(cv))
        pct_gjr = n_gjr_days / len(cv) * 100

        dm_gjr_str = f"{dm_vs_gjr_t:+.2f}{'*' if dm_vs_gjr_p < 0.10 else ''}"
        dm_garch_str = f"{dm_vs_garch_t:+.2f}{'*' if dm_vs_garch_p < 0.10 else ''}"

        print(f"{thr:>10.1f} | {name:>5} | {res['category']:>10} | {q_gjr:>10.4f} | {q_garch:>11.4f} | "
              f"{q_ewma:>10.4f} | {q_adapt:>11.4f} | {best:>8} | {dm_gjr_str:>10} | {dm_garch_str:>10}")

        asset_rows.append({
            "asset": name,
            "category": res["category"],
            "qlike_gjr": q_gjr,
            "qlike_garch": q_garch,
            "qlike_ewma": q_ewma,
            "qlike_adaptive": q_adapt,
            "best_model": best,
            "dm_vs_gjr_t": dm_vs_gjr_t,
            "dm_vs_gjr_p": dm_vs_gjr_p,
            "dm_vs_garch_t": dm_vs_garch_t,
            "dm_vs_garch_p": dm_vs_garch_p,
            "pct_gjr_days": pct_gjr,
            "mean_cv": float(np.nanmean(cv)),
        })

    threshold_summary[thr] = {
        "total": total,
        "wins_vs_gjr": wins_vs_gjr,
        "wins_vs_garch": wins_vs_garch,
        "sig_wins_vs_gjr": sig_wins_vs_gjr,
        "sig_wins_vs_garch": sig_wins_vs_garch,
        "asset_rows": asset_rows,
    }

    print(f"{'':>10}   Adaptive wins (QLIKE<): vs GJR {wins_vs_gjr}/{total}, vs GARCH {wins_vs_garch}/{total}")
    print(f"{'':>10}   Significant wins (DM p<0.10): vs GJR {sig_wins_vs_gjr}/{total}, vs GARCH {sig_wins_vs_garch}/{total}")
    print("-" * 110)

print()


# ======================================================================
# 5. CV(gamma) TIME SERIES FOR REPRESENTATIVE ASSETS
# ======================================================================
print("[4] CV(gamma) time series for representative assets")
print()

representative = ["SPY", "GLD", "TLT", "BTC"]
for name in representative:
    if name not in results:
        continue
    res = results[name]
    cv = res["cv_gammas"]
    dates = res["oos_dates"]
    valid = np.isfinite(cv)

    if valid.sum() == 0:
        print(f"  {name}: no valid CV values")
        continue

    mean_cv = np.nanmean(cv)
    std_cv = np.nanstd(cv)
    min_cv = np.nanmin(cv)
    max_cv = np.nanmax(cv)
    pct_stable = np.sum(cv[valid] < 1.0) / valid.sum() * 100

    print(f"  {name} ({res['desc']}):")
    print(f"    CV(gamma): mean={mean_cv:.3f}, std={std_cv:.3f}, range=[{min_cv:.3f}, {max_cv:.3f}]")
    print(f"    Stable fraction (CV<1.0): {pct_stable:.1f}%")
    print(f"    Mean GJR gamma: {np.nanmean(res['gjr_gammas']):.4f}")
    print()


# ======================================================================
# 6. THRESHOLD SENSITIVITY ANALYSIS
# ======================================================================
print("[5] Threshold Sensitivity Summary")
print()
print(f"{'Threshold':>10} | {'Adapt < GJR':>12} | {'Adapt < GARCH':>14} | {'Sig(GJR)':>9} | {'Sig(GARCH)':>11} | {'Avg QLIKE':>10}")
print("-" * 70)

for thr in CV_THRESHOLDS:
    s = threshold_summary[thr]
    # Average adaptive QLIKE across assets
    avg_q = np.mean([r["qlike_adaptive"] for r in s["asset_rows"]])
    print(f"{thr:>10.1f} | {s['wins_vs_gjr']:>5}/{s['total']:<6} | {s['wins_vs_garch']:>6}/{s['total']:<7} | "
          f"{s['sig_wins_vs_gjr']:>4}/{s['total']:<4} | {s['sig_wins_vs_garch']:>5}/{s['total']:<5} | {avg_q:>10.4f}")

print()


# ======================================================================
# 7. CATEGORY-LEVEL ANALYSIS
# ======================================================================
print("[6] Category-level analysis (threshold = 1.0)")
print()

best_thr = 1.0
s = threshold_summary[best_thr]

categories = {}
for row in s["asset_rows"]:
    cat = row["category"]
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(row)

print(f"{'Category':>12} | {'N':>3} | {'Adapt<GJR':>10} | {'Adapt<GARCH':>12} | {'Avg CV':>7} | {'Avg %GJR days':>14} | {'Adapt Best':>11}")
print("-" * 80)

for cat in ["equity", "safe_haven", "commodity", "crypto"]:
    if cat not in categories:
        continue
    rows = categories[cat]
    n = len(rows)
    adapt_lt_gjr = sum(1 for r in rows if r["qlike_adaptive"] < r["qlike_gjr"])
    adapt_lt_garch = sum(1 for r in rows if r["qlike_adaptive"] < r["qlike_garch"])
    avg_cv = np.mean([r["mean_cv"] for r in rows])
    avg_pct_gjr = np.mean([r["pct_gjr_days"] for r in rows])
    adapt_best = sum(1 for r in rows if r["best_model"] == "Adaptive")
    print(f"{cat:>12} | {n:>3} | {adapt_lt_gjr:>4}/{n:<5} | {adapt_lt_garch:>5}/{n:<6} | {avg_cv:>7.2f} | {avg_pct_gjr:>13.1f}% | {adapt_best:>5}/{n:<5}")

print()


# ======================================================================
# 8. ORACLE COMPARISON (UPPER BOUND)
# ======================================================================
print("[7] Oracle comparison: ex-post best model per period")
print()

print(f"{'Asset':>5} | {'QLIKE_GJR':>10} | {'QLIKE_GARCH':>11} | {'QLIKE_Oracle':>12} | {'QLIKE_Adapt':>11} | "
      f"{'Gap(A-O)/O':>11} | {'Oracle=GJR%':>11}")
print("-" * 80)

for name in sorted(results.keys()):
    res = results[name]
    rv = res["realized_vars"]
    gjr_f = res["gjr_forecasts"]
    garch_f = res["garch_forecasts"]

    # Oracle: pick whichever is better for each observation
    oracle_f = np.where(
        qlike_individual(rv, gjr_f) <= qlike_individual(rv, garch_f),
        gjr_f,
        garch_f
    )
    # Handle NaN
    oracle_f = np.where(np.isfinite(oracle_f), oracle_f, gjr_f)

    q_oracle = qlike_loss(rv, oracle_f)
    q_gjr = qlike_loss(rv, gjr_f)
    q_garch = qlike_loss(rv, garch_f)

    # Adaptive at threshold=1.0
    cv = res["cv_gammas"]
    adaptive_f = np.full(len(rv), np.nan)
    for i in range(len(rv)):
        cv_val = cv[i]
        if np.isnan(cv_val) or np.isinf(cv_val):
            adaptive_f[i] = garch_f[i] if np.isfinite(garch_f[i]) else 0.0
        elif cv_val < 1.0:
            adaptive_f[i] = gjr_f[i]
        else:
            adaptive_f[i] = garch_f[i] if np.isfinite(garch_f[i]) else 0.0
    q_adapt = qlike_loss(rv, adaptive_f)

    gap_pct = (q_adapt - q_oracle) / abs(q_oracle) * 100 if abs(q_oracle) > 1e-10 else 0.0
    oracle_gjr_pct = np.sum(qlike_individual(rv, gjr_f) <= qlike_individual(rv, garch_f)) / len(rv) * 100

    print(f"{name:>5} | {q_gjr:>10.4f} | {q_garch:>11.4f} | {q_oracle:>12.4f} | {q_adapt:>11.4f} | "
          f"{gap_pct:>10.1f}% | {oracle_gjr_pct:>10.1f}%")

print()


# ======================================================================
# 9. STATISTICAL SUMMARY
# ======================================================================
print("[8] Final Statistical Summary")
print("=" * 80)

# Use threshold = 1.0 as primary
s = threshold_summary[1.0]
total = s["total"]

# Count categories
adapt_best_count = sum(1 for r in s["asset_rows"] if r["best_model"] == "Adaptive")
gjr_best_count = sum(1 for r in s["asset_rows"] if r["best_model"] == "GJR")
garch_best_count = sum(1 for r in s["asset_rows"] if r["best_model"] == "GARCH")
ewma_best_count = sum(1 for r in s["asset_rows"] if r["best_model"] == "EWMA")

print(f"  Assets evaluated:     {total}")
print(f"  OOS period:           {OOS_START} to {DATA_END}")
print(f"  Primary threshold:    CV(gamma) = 1.0")
print()
print(f"  Best model count:")
print(f"    Adaptive:  {adapt_best_count}/{total} ({adapt_best_count/total*100:.0f}%)")
print(f"    GJR:       {gjr_best_count}/{total} ({gjr_best_count/total*100:.0f}%)")
print(f"    GARCH:     {garch_best_count}/{total} ({garch_best_count/total*100:.0f}%)")
print(f"    EWMA:      {ewma_best_count}/{total} ({ewma_best_count/total*100:.0f}%)")
print()
print(f"  Adaptive wins (QLIKE lower):")
print(f"    vs GJR:    {s['wins_vs_gjr']}/{total}")
print(f"    vs GARCH:  {s['wins_vs_garch']}/{total}")
print()
print(f"  Significant wins (DM test p<0.10):")
print(f"    vs GJR:    {s['sig_wins_vs_gjr']}/{total}")
print(f"    vs GARCH:  {s['sig_wins_vs_garch']}/{total}")
print()

# Cross-sectional: does mean CV predict which fixed model is better?
# Filter out inf values for statistical tests
cvs_raw = [r["mean_cv"] for r in s["asset_rows"]]
gjr_better = [1 if r["qlike_gjr"] < r["qlike_garch"] else 0 for r in s["asset_rows"]]
# Cap inf at a large value for rank-based tests; filter for parametric tests
cvs_capped = [min(cv, 100.0) if np.isfinite(cv) else 100.0 for cv in cvs_raw]
finite_mask = [np.isfinite(cv) for cv in cvs_raw]
cvs_finite = [cv for cv, m in zip(cvs_raw, finite_mask) if m]
gjr_finite = [g for g, m in zip(gjr_better, finite_mask) if m]

if len(cvs_capped) >= 5:
    rho, p = stats.spearmanr(cvs_capped, gjr_better)
    print(f"  Cross-sectional: Spearman(CV_capped, GJR_better) = {rho:.3f} (p={p:.3f})")
    print(f"    (inf CV capped at 100 for rank test; {sum(1 for m in finite_mask if not m)} assets had inf)")
    # Point-biserial correlation (finite only)
    if len(cvs_finite) >= 5:
        cvs_arr = np.array(cvs_finite)
        gjr_arr = np.array(gjr_finite)
        cv_gjr_wins = cvs_arr[gjr_arr == 1]
        cv_garch_wins = cvs_arr[gjr_arr == 0]
        if len(cv_gjr_wins) > 1 and len(cv_garch_wins) > 1:
            t_pb, p_pb = stats.ttest_ind(cv_gjr_wins, cv_garch_wins)
            print(f"  CV when GJR wins: mean={np.mean(cv_gjr_wins):.3f} (n={len(cv_gjr_wins)})")
            print(f"  CV when GARCH wins: mean={np.mean(cv_garch_wins):.3f} (n={len(cv_garch_wins)})")
            print(f"  t-test: t={t_pb:.2f}, p={p_pb:.3f}")
print()

# Binomial test: is Adaptive significantly better than chance?
from scipy.stats import binomtest
p_binom_gjr = binomtest(s['wins_vs_gjr'], total, 0.5, alternative='greater').pvalue
p_binom_garch = binomtest(s['wins_vs_garch'], total, 0.5, alternative='greater').pvalue
print(f"  Binomial test (Adaptive wins > 50%):")
print(f"    vs GJR:    p = {p_binom_gjr:.4f}")
print(f"    vs GARCH:  p = {p_binom_garch:.4f}")
print()


# ======================================================================
# 10. CONCLUSIONS
# ======================================================================
print("[9] CONCLUSIONS")
print("=" * 80)

# Determine conclusion based on evidence
if s['sig_wins_vs_gjr'] >= total * 0.3 or s['sig_wins_vs_garch'] >= total * 0.3:
    conclusion = "POSITIVE"
    conclusion_text = (
        "CV(gamma)-based adaptive model selection provides STATISTICALLY SIGNIFICANT\n"
        "    improvement over fixed model choice for a meaningful fraction of assets.\n"
        "    This validates CV(gamma) as an ex-ante model selection criterion."
    )
elif s['wins_vs_gjr'] > total * 0.5 and s['wins_vs_garch'] > total * 0.5:
    conclusion = "WEAK POSITIVE"
    conclusion_text = (
        "CV(gamma)-based adaptive selection wins more often than not, but improvements\n"
        "    are not statistically significant by DM test. CV(gamma) provides directional\n"
        "    guidance but the economic magnitude is small — consistent with the QLIKE\n"
        "    ceiling (K126: 87% irreducible noise)."
    )
elif adapt_best_count >= gjr_best_count and adapt_best_count >= garch_best_count:
    conclusion = "MARGINAL"
    conclusion_text = (
        "Adaptive selection is the best single approach but improvements are marginal.\n"
        "    The QLIKE differences are within noise for most assets. CV(gamma) classifies\n"
        "    correctly but the classification doesn't translate to forecast improvement."
    )
else:
    conclusion = "NULL"
    conclusion_text = (
        "CV(gamma)-based adaptive selection does NOT improve over fixed model choice.\n"
        "    Despite CV(gamma) being a valid mechanism classifier (K143), it lacks\n"
        "    predictive power for model selection — consistent with VIX sufficiency\n"
        "    (the improvement ceiling is too low for model switching to matter)."
    )

print(f"  Verdict: {conclusion}")
print(f"    {conclusion_text}")
print()

# JBF paper implications
print("  JBF Paper Implications:")
if conclusion in ("POSITIVE", "WEAK POSITIVE"):
    print("    - CV(gamma) serves dual purpose: mechanism classifier + model selector")
    print("    - Table for paper: 'Adaptive Model Selection via CV(gamma)'")
    print("    - Practical rule: estimate gamma stability before choosing model")
else:
    print("    - CV(gamma) is a diagnostic tool, not a selection tool")
    print("    - Distinction: understanding WHY a model works != knowing WHICH model to use")
    print("    - The QLIKE ceiling limits the value of any model switching strategy")
    print("    - Consistent with K129 Economic Sufficiency: VIX dominates model choice")
print()


# ======================================================================
# 11. SAVE RESULTS
# ======================================================================
output = {
    "experiment": "K145",
    "title": "Predictive Model Selection via CV(gamma)",
    "attribution": "[提出: Gemini R5a, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "data_start": DATA_START,
        "data_end": DATA_END,
        "oos_start": OOS_START,
        "garch_window": GARCH_WINDOW,
        "sub_window": SUB_WINDOW,
        "cv_thresholds": CV_THRESHOLDS,
        "reestimate_freq": REESTIMATE_FREQ,
        "n_assets": N_ASSETS,
    },
    "conclusion": conclusion,
    "conclusion_text": conclusion_text.strip(),
    "threshold_summary": {
        str(thr): {
            "total": s["total"],
            "wins_vs_gjr": s["wins_vs_gjr"],
            "wins_vs_garch": s["wins_vs_garch"],
            "sig_wins_vs_gjr": s["sig_wins_vs_gjr"],
            "sig_wins_vs_garch": s["sig_wins_vs_garch"],
            "asset_results": [
                {k: v for k, v in r.items()}
                for r in s["asset_rows"]
            ],
        }
        for thr, s in threshold_summary.items()
    },
    "representative_cv_stats": {},
}

for name in representative:
    if name in results:
        cv = results[name]["cv_gammas"]
        valid = np.isfinite(cv)
        output["representative_cv_stats"][name] = {
            "mean_cv": float(np.nanmean(cv)) if valid.sum() > 0 else None,
            "std_cv": float(np.nanstd(cv)) if valid.sum() > 0 else None,
            "pct_stable": float(np.sum(cv[valid] < 1.0) / valid.sum() * 100) if valid.sum() > 0 else None,
            "mean_gamma": float(np.nanmean(results[name]["gjr_gammas"])),
        }

report_path = project_root / "storage" / "reports" / "k145_predictive_model_selection.json"
with open(report_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Report saved to: {report_path}")

print()
print("K145 complete.")
