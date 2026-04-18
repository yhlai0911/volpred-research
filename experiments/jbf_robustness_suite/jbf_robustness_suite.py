"""
K149: JBF Robustness Suite — Final Pre-Submission Checks
=========================================================
[提出: Gemini R6#1, 執行: Claude]

Background:
  Paper 1 (Leverage Direction Matters) core claims:
    (1) GJR gamma direction matters for VT effectiveness
    (2) CV(gamma) classifies leverage mechanism (stable vs unstable)
    (3) VIX is an economic sufficient statistic for vol timing

  This suite runs 5 robustness checks that reviewers will likely demand:
    R1: Sub-sample stability (3 sub-periods)
    R2: Alternative vol proxy (Parkinson range)
    R3: Transaction cost sensitivity (0-50bps)
    R4: Alternative VT rules comparison
    R5: Bootstrap confidence intervals (5000 block bootstrap)

Data: yfinance SPY + QQQ + GLD + EEM daily 2007-2024
Method: empirical robustness checks
Output: paper-ready tables for Section 5

Usage:
    uv run python experiments/jbf_robustness_suite/jbf_robustness_suite.py
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
    "SPY": {"ticker": "SPY", "category": "equity", "desc": "S&P 500"},
    "QQQ": {"ticker": "QQQ", "category": "equity", "desc": "Nasdaq 100"},
    "GLD": {"ticker": "GLD", "category": "safe_haven", "desc": "Gold"},
    "EEM": {"ticker": "EEM", "category": "equity", "desc": "Emerging Mkts"},
}

DATA_START = "2005-01-01"  # enough warmup for w=500 before 2007
DATA_END = "2024-12-31"
FULL_PERIOD = ("2007-01-01", "2024-12-31")

# Sub-periods for R1
SUB_PERIODS = [
    ("2007-01-01", "2012-12-31", "2007-2012 (GFC)"),
    ("2013-01-01", "2018-12-31", "2013-2018 (Bull)"),
    ("2019-01-01", "2024-12-31", "2019-2024 (COVID+)"),
]

# VT params
GARCH_WINDOW = 500  # smaller for sub-period stability (3yr ~ 756d)
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

# R3: TX cost levels
TX_COST_LEVELS = [0, 5, 10, 20, 30, 40, 50]

# R5: Bootstrap
N_BOOTSTRAP = 5000
BLOCK_SIZE = 21  # monthly blocks

np.random.seed(42)

print("=" * 80)
print("K149: JBF ROBUSTNESS SUITE — PAPER SECTION 5")
print("=" * 80)
print(f"  [提出: Gemini R6#1, 執行: Claude]")
print(f"  Assets:       {list(ASSETS.keys())}")
print(f"  Full period:  {FULL_PERIOD[0]} to {FULL_PERIOD[1]}")
print(f"  Sub-periods:  {len(SUB_PERIODS)}")
print(f"  GARCH window: {GARCH_WINDOW}")
print(f"  Bootstrap:    {N_BOOTSTRAP} reps, block={BLOCK_SIZE}d")
print()


# ======================================================================
# DATA DOWNLOAD
# ======================================================================
print("[0/5] Downloading data...")
import yfinance as yf

all_data = {}
for asset_id, info in ASSETS.items():
    ticker = info["ticker"]
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = pd.DataFrame()
    df["close"] = raw["Close"]
    df["high"] = raw["High"]
    df["low"] = raw["Low"]
    df["returns"] = np.log(df["close"] / df["close"].shift(1))
    df = df.dropna()
    all_data[asset_id] = df
    print(f"  {asset_id}: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")

# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw["Close"].dropna()
print(f"  VIX: {vix_series.index[0].date()} to {vix_series.index[-1].date()}")


# ======================================================================
# HELPER FUNCTIONS
# ======================================================================
def fit_gjr_garch(returns_pct, window_data=None):
    """Fit GJR-GARCH(1,1,1) with student-t, return params + vol forecast."""
    from arch import arch_model

    try:
        model = arch_model(
            returns_pct, vol="GARCH", p=1, o=1, q=1,
            dist="t", mean="Zero", rescale=False
        )
        result = model.fit(disp="off", show_warning=False)
        params = dict(result.params)
        fcast = result.forecast(horizon=1)
        var_pct = fcast.variance.iloc[-1, 0]
        vol = np.sqrt(var_pct / 10000)  # back to decimal
        gamma = params.get("gamma[1]", params.get("gamma", np.nan))
        return {
            "params": params,
            "gamma": gamma,
            "vol_forecast": vol,
            "loglik": result.loglikelihood,
            "aic": result.aic,
            "converged": result.convergence_flag == 0,
            "cond_vol": result.conditional_volatility / 100,  # decimal
        }
    except Exception as e:
        return None


def fit_standard_garch(returns_pct):
    """Fit standard GARCH(1,1) with student-t."""
    from arch import arch_model

    try:
        model = arch_model(
            returns_pct, vol="GARCH", p=1, o=0, q=1,
            dist="t", mean="Zero", rescale=False
        )
        result = model.fit(disp="off", show_warning=False)
        fcast = result.forecast(horizon=1)
        var_pct = fcast.variance.iloc[-1, 0]
        vol = np.sqrt(var_pct / 10000)
        return {
            "vol_forecast": vol,
            "aic": result.aic,
            "cond_vol": result.conditional_volatility / 100,
        }
    except Exception:
        return None


def compute_cv_gamma(returns, window=GARCH_WINDOW, n_subsamples=4):
    """Compute CV(gamma) from sub-sample GJR estimates."""
    gammas = []
    sub_len = len(returns) // n_subsamples
    for i in range(n_subsamples):
        start = i * sub_len
        end = start + sub_len
        sub = returns[start:end]
        if len(sub) < 200:
            continue
        result = fit_gjr_garch(sub * 100)
        if result and result["converged"]:
            gammas.append(result["gamma"])

    if len(gammas) < 2:
        return np.nan, gammas
    cv = np.std(gammas) / (np.mean(gammas) + 1e-10)
    return cv, gammas


def rolling_gjr_forecast(returns, window=GARCH_WINDOW):
    """Rolling GJR-GARCH forecast, returns vol series and gamma series."""
    n = len(returns)
    vol_forecasts = np.full(n, np.nan)
    gamma_series = np.full(n, np.nan)

    n_iters = n - window
    report_every = max(1, n_iters // 10)

    for i in range(n_iters):
        idx = window + i
        win_ret = returns[idx - window:idx] * 100  # pct
        result = fit_gjr_garch(win_ret)
        if result:
            vol_forecasts[idx] = result["vol_forecast"]
            gamma_series[idx] = result["gamma"]
        else:
            vol_forecasts[idx] = np.std(returns[idx - window:idx])
            gamma_series[idx] = np.nan

        if (i + 1) % report_every == 0:
            print(f"      Progress: {(i+1)/n_iters*100:.0f}%")

    return vol_forecasts, gamma_series


def ewma_vol(returns, lam=0.97):
    """EWMA volatility."""
    n = len(returns)
    var = np.zeros(n)
    var[0] = np.var(returns[:min(30, n)])
    for t in range(1, n):
        var[t] = lam * var[t - 1] + (1 - lam) * returns[t - 1] ** 2
    return np.sqrt(var)


def vt_strategy(returns, vol_est, target_daily=TARGET_VOL_DAILY,
                max_lev=MAX_LEVERAGE, tx_cost_bps=0):
    """Run VT strategy with given vol estimates. Returns portfolio returns."""
    n = len(returns)
    weights = np.clip(target_daily / np.maximum(vol_est, 1e-8), 0, max_lev)

    port_ret = np.zeros(n)
    for t in range(1, n):
        w = weights[t - 1]  # lagged weight
        weight_change = abs(w - (weights[t - 2] if t >= 2 else w))
        tx = weight_change * tx_cost_bps / 10000 if weight_change > 0.001 else 0
        port_ret[t] = w * returns[t] - tx

    return port_ret, weights


def compute_metrics(port_returns, rf_daily=RF_DAILY):
    """Compute Sharpe, MDD, Calmar, Sortino from daily returns."""
    excess = port_returns - rf_daily
    ann_ret = np.mean(port_returns) * 252
    ann_vol = np.std(port_returns) * np.sqrt(252)
    sharpe = np.mean(excess) / (np.std(port_returns) + 1e-10) * np.sqrt(252)

    # MDD
    cum = np.exp(np.cumsum(port_returns))
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    mdd = np.min(dd)

    # Calmar
    calmar = ann_ret / (abs(mdd) + 1e-10)

    # Sortino
    downside = port_returns[port_returns < 0]
    down_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / down_vol

    return {
        "sharpe": sharpe,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
    }


def qlike(realized_var, forecast_var):
    """QLIKE loss: mean(rv/fv - log(rv/fv) - 1)."""
    ratio = realized_var / (forecast_var + 1e-12)
    return np.mean(ratio - np.log(ratio) - 1)


# ======================================================================
# R1: SUB-SAMPLE STABILITY
# ======================================================================
print("\n" + "=" * 80)
print("R1: SUB-SAMPLE STABILITY")
print("=" * 80)
print("  Testing if GJR gamma, CV(gamma), and VT Sharpe are stable across 3 sub-periods\n")

r1_results = {}

for asset_id, info in ASSETS.items():
    df = all_data[asset_id]
    r1_results[asset_id] = {}

    for period_start, period_end, period_label in SUB_PERIODS:
        mask = (df.index >= period_start) & (df.index <= period_end)
        sub_df = df[mask]

        if len(sub_df) < GARCH_WINDOW + 100:
            print(f"  {asset_id} {period_label}: insufficient data ({len(sub_df)} days)")
            r1_results[asset_id][period_label] = {"status": "insufficient_data"}
            continue

        returns = sub_df["returns"].values

        # Full-sample GJR gamma for sub-period
        result = fit_gjr_garch(returns * 100)
        gamma_full = result["gamma"] if result else np.nan
        gamma_converged = result["converged"] if result else False

        # CV(gamma) for sub-period
        cv_gamma, gammas = compute_cv_gamma(returns, window=min(GARCH_WINDOW, len(returns) // 2))

        # VT performance in sub-period
        vol_est, gamma_ts = rolling_gjr_forecast(returns, window=min(GARCH_WINDOW, len(returns) // 3))
        valid = ~np.isnan(vol_est)
        if valid.sum() > 50:
            vt_ret, vt_w = vt_strategy(returns[valid], vol_est[valid])
            metrics = compute_metrics(vt_ret)
            bh_metrics = compute_metrics(returns[valid])
        else:
            metrics = {"sharpe": np.nan, "mdd": np.nan, "calmar": np.nan}
            bh_metrics = {"sharpe": np.nan, "mdd": np.nan}

        r1_results[asset_id][period_label] = {
            "n_days": len(sub_df),
            "gamma_full": float(gamma_full),
            "gamma_converged": gamma_converged,
            "cv_gamma": float(cv_gamma) if not np.isnan(cv_gamma) else None,
            "gamma_subsamples": [float(g) for g in gammas],
            "vt_sharpe": float(metrics["sharpe"]),
            "vt_mdd": float(metrics["mdd"]),
            "vt_calmar": float(metrics.get("calmar", np.nan)),
            "bh_sharpe": float(bh_metrics["sharpe"]),
            "bh_mdd": float(bh_metrics["mdd"]),
            "sharpe_improvement": float(metrics["sharpe"] - bh_metrics["sharpe"]),
        }

        print(f"  {asset_id} {period_label}: gamma={gamma_full:.4f}, CV={cv_gamma:.2f}, "
              f"VT Sharpe={metrics['sharpe']:.3f}, B&H Sharpe={bh_metrics['sharpe']:.3f}")

# R1 Summary Table
print("\n--- R1 SUMMARY TABLE ---")
print(f"{'Asset':<6} {'Period':<20} {'γ':>8} {'CV(γ)':>8} {'VT Sharpe':>10} {'B&H Sharpe':>11} {'Δ Sharpe':>9}")
print("-" * 75)
for asset_id in ASSETS:
    for period_start, period_end, period_label in SUB_PERIODS:
        if period_label in r1_results[asset_id]:
            r = r1_results[asset_id][period_label]
            if "gamma_full" in r:
                print(f"{asset_id:<6} {period_label:<20} {r['gamma_full']:>8.4f} "
                      f"{r.get('cv_gamma', 0) or 0:>8.2f} {r['vt_sharpe']:>10.3f} "
                      f"{r['bh_sharpe']:>11.3f} {r['sharpe_improvement']:>9.3f}")

# R1 stability assessment
print("\n--- R1 STABILITY ASSESSMENT ---")
for asset_id in ASSETS:
    gammas_across = []
    sharpe_diffs = []
    for period_start, period_end, period_label in SUB_PERIODS:
        if period_label in r1_results[asset_id]:
            r = r1_results[asset_id][period_label]
            if "gamma_full" in r and not np.isnan(r["gamma_full"]):
                gammas_across.append(r["gamma_full"])
            if "sharpe_improvement" in r and not np.isnan(r["sharpe_improvement"]):
                sharpe_diffs.append(r["sharpe_improvement"])

    if len(gammas_across) >= 2:
        gamma_sign_stable = all(g > 0 for g in gammas_across) or all(g < 0 for g in gammas_across)
        gamma_cv_across = np.std(gammas_across) / (abs(np.mean(gammas_across)) + 1e-10)
        print(f"  {asset_id}: gamma sign stable={gamma_sign_stable}, "
              f"gamma across-period CV={gamma_cv_across:.2f}, "
              f"VT advantage range=[{min(sharpe_diffs):.3f}, {max(sharpe_diffs):.3f}]")


# ======================================================================
# R2: ALTERNATIVE VOL PROXY (PARKINSON RANGE)
# ======================================================================
print("\n" + "=" * 80)
print("R2: ALTERNATIVE VOL PROXY — PARKINSON RANGE")
print("=" * 80)
print("  Testing QLIKE with range-based vol proxy instead of r²\n")

r2_results = {}

for asset_id, info in ASSETS.items():
    df = all_data[asset_id].copy()
    mask = (df.index >= FULL_PERIOD[0]) & (df.index <= FULL_PERIOD[1])
    df = df[mask]

    if len(df) < GARCH_WINDOW + 200:
        print(f"  {asset_id}: insufficient data, skipping")
        continue

    returns = df["returns"].values
    high = df["high"].values
    low = df["low"].values

    # Parkinson range estimator: σ² = (1/4ln2) * (ln(H/L))²
    parkinson_var = (1 / (4 * np.log(2))) * (np.log(high / (low + 1e-10))) ** 2

    # Squared returns as proxy
    r2_proxy = returns ** 2

    # Rolling GJR forecast
    print(f"  {asset_id}: running rolling GJR-GARCH...")
    n = len(returns)
    gjr_var = np.full(n, np.nan)
    garch_var = np.full(n, np.nan)

    n_iters = n - GARCH_WINDOW
    report_every = max(1, n_iters // 5)

    for i in range(n_iters):
        idx = GARCH_WINDOW + i
        win_ret = returns[idx - GARCH_WINDOW:idx] * 100

        result_gjr = fit_gjr_garch(win_ret)
        if result_gjr:
            gjr_var[idx] = result_gjr["vol_forecast"] ** 2

        result_garch = fit_standard_garch(win_ret)
        if result_garch:
            garch_var[idx] = result_garch["vol_forecast"] ** 2

        if (i + 1) % report_every == 0:
            print(f"      Progress: {(i+1)/n_iters*100:.0f}%")

    # Compute QLIKE with both proxies
    valid = ~np.isnan(gjr_var) & ~np.isnan(garch_var)
    valid_idx = np.where(valid)[0]

    if len(valid_idx) < 100:
        print(f"  {asset_id}: not enough valid forecasts")
        continue

    # r² proxy QLIKE
    qlike_gjr_r2 = qlike(r2_proxy[valid], gjr_var[valid])
    qlike_garch_r2 = qlike(r2_proxy[valid], garch_var[valid])

    # Parkinson proxy QLIKE
    qlike_gjr_park = qlike(parkinson_var[valid], gjr_var[valid])
    qlike_garch_park = qlike(parkinson_var[valid], garch_var[valid])

    # DM test for GJR vs GARCH under both proxies
    # loss difference: d_t = loss_garch - loss_gjr (positive = GJR better)
    loss_gjr_r2 = r2_proxy[valid] / (gjr_var[valid] + 1e-12) - np.log(r2_proxy[valid] / (gjr_var[valid] + 1e-12)) - 1
    loss_garch_r2 = r2_proxy[valid] / (garch_var[valid] + 1e-12) - np.log(r2_proxy[valid] / (garch_var[valid] + 1e-12)) - 1
    d_r2 = loss_garch_r2 - loss_gjr_r2

    loss_gjr_park = parkinson_var[valid] / (gjr_var[valid] + 1e-12) - np.log(parkinson_var[valid] / (gjr_var[valid] + 1e-12)) - 1
    loss_garch_park = parkinson_var[valid] / (garch_var[valid] + 1e-12) - np.log(parkinson_var[valid] / (garch_var[valid] + 1e-12)) - 1
    d_park = loss_garch_park - loss_gjr_park

    # Newey-West adjusted DM test
    def dm_test_nw(d, max_lag=10):
        """DM test with Newey-West HAC SE."""
        n_d = len(d)
        d_bar = np.mean(d)
        # Newey-West variance
        gamma_0 = np.var(d, ddof=0)
        nw_var = gamma_0
        for k in range(1, max_lag + 1):
            gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            nw_var += 2 * (1 - k / (max_lag + 1)) * gamma_k
        se = np.sqrt(nw_var / n_d)
        t_stat = d_bar / (se + 1e-12)
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n_d - 1))
        return t_stat, p_val

    dm_t_r2, dm_p_r2 = dm_test_nw(d_r2)
    dm_t_park, dm_p_park = dm_test_nw(d_park)

    r2_results[asset_id] = {
        "n_forecasts": int(valid.sum()),
        "qlike_gjr_r2": float(qlike_gjr_r2),
        "qlike_garch_r2": float(qlike_garch_r2),
        "qlike_gjr_parkinson": float(qlike_gjr_park),
        "qlike_garch_parkinson": float(qlike_garch_park),
        "dm_t_r2": float(dm_t_r2),
        "dm_p_r2": float(dm_p_r2),
        "dm_t_parkinson": float(dm_t_park),
        "dm_p_parkinson": float(dm_p_park),
        "gjr_wins_r2": qlike_gjr_r2 < qlike_garch_r2,
        "gjr_wins_parkinson": qlike_gjr_park < qlike_garch_park,
    }

    sig_r2 = "*" if dm_p_r2 < 0.05 else ""
    sig_park = "*" if dm_p_park < 0.05 else ""
    print(f"  {asset_id}: QLIKE(GJR vs GARCH) — r²: {qlike_gjr_r2:.4f} vs {qlike_garch_r2:.4f} "
          f"(DM t={dm_t_r2:.2f}{sig_r2}), Parkinson: {qlike_gjr_park:.4f} vs {qlike_garch_park:.4f} "
          f"(DM t={dm_t_park:.2f}{sig_park})")

# R2 Summary
print("\n--- R2 SUMMARY TABLE ---")
print(f"{'Asset':<6} {'QLIKE(GJR,r²)':>14} {'QLIKE(G,r²)':>12} {'DM(r²)':>8} {'QLIKE(GJR,PK)':>14} {'QLIKE(G,PK)':>12} {'DM(PK)':>8}")
print("-" * 80)
for asset_id, r in r2_results.items():
    sig_r2 = "**" if r["dm_p_r2"] < 0.01 else ("*" if r["dm_p_r2"] < 0.05 else "")
    sig_pk = "**" if r["dm_p_parkinson"] < 0.01 else ("*" if r["dm_p_parkinson"] < 0.05 else "")
    print(f"{asset_id:<6} {r['qlike_gjr_r2']:>14.4f} {r['qlike_garch_r2']:>12.4f} "
          f"{r['dm_t_r2']:>6.2f}{sig_r2:<2} {r['qlike_gjr_parkinson']:>14.4f} "
          f"{r['qlike_garch_parkinson']:>12.4f} {r['dm_t_parkinson']:>6.2f}{sig_pk:<2}")


# ======================================================================
# R3: TRANSACTION COST SENSITIVITY
# ======================================================================
print("\n" + "=" * 80)
print("R3: TRANSACTION COST SENSITIVITY")
print("=" * 80)
print("  Testing VT net Sharpe at 0-50bps cost levels\n")

r3_results = {}

for asset_id, info in ASSETS.items():
    df = all_data[asset_id].copy()
    mask = (df.index >= FULL_PERIOD[0]) & (df.index <= FULL_PERIOD[1])
    df = df[mask]
    returns = df["returns"].values

    if len(returns) < GARCH_WINDOW + 200:
        continue

    print(f"  {asset_id}: rolling GJR forecast...")
    vol_est, gamma_ts = rolling_gjr_forecast(returns, window=GARCH_WINDOW)

    valid = ~np.isnan(vol_est)
    ret_valid = returns[valid]
    vol_valid = vol_est[valid]

    # B&H benchmark
    bh_metrics = compute_metrics(ret_valid)

    asset_results = {"bh": bh_metrics, "costs": {}}

    for cost_bps in TX_COST_LEVELS:
        vt_ret, vt_w = vt_strategy(ret_valid, vol_valid, tx_cost_bps=cost_bps)
        m = compute_metrics(vt_ret)

        # Compute turnover
        weight_changes = np.abs(np.diff(vt_w))
        n_trades = np.sum(weight_changes > 0.001)
        ann_turnover = np.sum(weight_changes) / (len(ret_valid) / 252)

        asset_results["costs"][cost_bps] = {
            **m,
            "n_trades": int(n_trades),
            "ann_turnover": float(ann_turnover),
            "sharpe_vs_bh": float(m["sharpe"] - bh_metrics["sharpe"]),
        }

    r3_results[asset_id] = asset_results

# R3 Summary
print("\n--- R3 SUMMARY TABLE ---")
for asset_id, ar in r3_results.items():
    print(f"\n  {asset_id} (B&H Sharpe = {ar['bh']['sharpe']:.3f}):")
    print(f"  {'Cost(bps)':>10} {'VT Sharpe':>10} {'Δ Sharpe':>9} {'MDD':>8} {'Calmar':>8} {'Ann TO':>8}")
    print("  " + "-" * 60)
    for cost_bps in TX_COST_LEVELS:
        c = ar["costs"][cost_bps]
        print(f"  {cost_bps:>10} {c['sharpe']:>10.3f} {c['sharpe_vs_bh']:>9.3f} "
              f"{c['mdd']:>8.1%} {c['calmar']:>8.2f} {c['ann_turnover']:>8.1f}")

    # Find breakeven cost
    bh_s = ar["bh"]["sharpe"]
    for cost_bps in TX_COST_LEVELS:
        if ar["costs"][cost_bps]["sharpe"] < bh_s:
            if cost_bps > 0:
                prev_cost = TX_COST_LEVELS[TX_COST_LEVELS.index(cost_bps) - 1]
                prev_s = ar["costs"][prev_cost]["sharpe"]
                curr_s = ar["costs"][cost_bps]["sharpe"]
                # Linear interpolation
                breakeven = prev_cost + (cost_bps - prev_cost) * (prev_s - bh_s) / (prev_s - curr_s + 1e-10)
                print(f"  → Breakeven cost ≈ {breakeven:.1f} bps")
            else:
                print(f"  → VT underperforms B&H even at 0bps")
            break
    else:
        print(f"  → VT still beats B&H at {TX_COST_LEVELS[-1]}bps")


# ======================================================================
# R4: ALTERNATIVE VT RULES
# ======================================================================
print("\n" + "=" * 80)
print("R4: ALTERNATIVE VT RULES COMPARISON")
print("=" * 80)
print("  Comparing: 12/VIX, EWMA(0.97), GJR-GARCH VT, Constant 60/40\n")

r4_results = {}

for asset_id, info in ASSETS.items():
    df = all_data[asset_id].copy()
    mask = (df.index >= FULL_PERIOD[0]) & (df.index <= FULL_PERIOD[1])
    df = df[mask]
    returns = df["returns"].values

    if len(returns) < GARCH_WINDOW + 200:
        continue

    # Align VIX
    vix_aligned = vix_series.reindex(df.index).ffill().values
    vix_daily_vol = vix_aligned / 100 / np.sqrt(252)

    # GJR vol (already computed or recompute)
    print(f"  {asset_id}: computing 4 VT variants...")
    vol_gjr, _ = rolling_gjr_forecast(returns, window=GARCH_WINDOW)

    # EWMA vol
    vol_ewma = ewma_vol(returns, lam=0.97)

    # Valid indices (where GJR is available)
    valid = ~np.isnan(vol_gjr) & (vix_daily_vol > 0) & ~np.isnan(vix_daily_vol)
    ret_v = returns[valid]
    gjr_v = vol_gjr[valid]
    ewma_v = vol_ewma[valid]
    vix_v = vix_daily_vol[valid]

    bh_metrics = compute_metrics(ret_v)

    # Strategy 1: 12/VIX (Markowitz-style)
    w_vix = np.clip(TARGET_VOL_DAILY / np.maximum(vix_v, 1e-8), 0, MAX_LEVERAGE)
    vt_vix_ret = np.zeros(len(ret_v))
    for t in range(1, len(ret_v)):
        vt_vix_ret[t] = w_vix[t - 1] * ret_v[t]
    m_vix = compute_metrics(vt_vix_ret)

    # Strategy 2: EWMA(0.97) VT
    vt_ewma_ret, _ = vt_strategy(ret_v, ewma_v)
    m_ewma = compute_metrics(vt_ewma_ret)

    # Strategy 3: GJR-GARCH VT
    vt_gjr_ret, _ = vt_strategy(ret_v, gjr_v)
    m_gjr = compute_metrics(vt_gjr_ret)

    # Strategy 4: Constant 60/40 (60% risky, 40% risk-free)
    vt_const_ret = np.zeros(len(ret_v))
    for t in range(len(ret_v)):
        vt_const_ret[t] = 0.6 * ret_v[t]
    m_const = compute_metrics(vt_const_ret)

    r4_results[asset_id] = {
        "bh": bh_metrics,
        "vix_vt": m_vix,
        "ewma_vt": m_ewma,
        "gjr_vt": m_gjr,
        "const_60_40": m_const,
    }

    # Sub-period breakdown
    r4_results[asset_id]["sub_periods"] = {}
    for period_start, period_end, period_label in SUB_PERIODS:
        sub_mask = (df.index >= period_start) & (df.index <= period_end)
        sub_valid = sub_mask[valid] if len(sub_mask) == len(valid) else np.zeros(len(ret_v), dtype=bool)

        # Reindex: find which valid indices fall in this sub-period
        valid_dates = df.index[valid]
        sub_idx = (valid_dates >= period_start) & (valid_dates <= period_end)

        if sub_idx.sum() < 50:
            continue

        sub_ret = ret_v[sub_idx]
        sub_gjr = gjr_v[sub_idx]
        sub_ewma = ewma_v[sub_idx]
        sub_vix = vix_v[sub_idx]

        # Recompute each strategy for sub-period
        sub_bh = compute_metrics(sub_ret)

        sub_w_vix = np.clip(TARGET_VOL_DAILY / np.maximum(sub_vix, 1e-8), 0, MAX_LEVERAGE)
        sub_vt_vix = np.zeros(len(sub_ret))
        for t in range(1, len(sub_ret)):
            sub_vt_vix[t] = sub_w_vix[t - 1] * sub_ret[t]

        sub_vt_ewma, _ = vt_strategy(sub_ret, sub_ewma)
        sub_vt_gjr, _ = vt_strategy(sub_ret, sub_gjr)

        r4_results[asset_id]["sub_periods"][period_label] = {
            "bh": compute_metrics(sub_ret),
            "vix_vt": compute_metrics(sub_vt_vix),
            "ewma_vt": compute_metrics(sub_vt_ewma),
            "gjr_vt": compute_metrics(sub_vt_gjr),
        }

# R4 Summary
print("\n--- R4 FULL-PERIOD SUMMARY ---")
print(f"{'Asset':<6} {'Method':<15} {'Sharpe':>8} {'Ann Ret':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 65)
for asset_id, ar in r4_results.items():
    methods = [
        ("B&H", ar["bh"]),
        ("12/VIX", ar["vix_vt"]),
        ("EWMA(0.97)", ar["ewma_vt"]),
        ("GJR-GARCH", ar["gjr_vt"]),
        ("Const 60/40", ar["const_60_40"]),
    ]
    for method_name, m in methods:
        print(f"{asset_id:<6} {method_name:<15} {m['sharpe']:>8.3f} {m['ann_ret']:>8.1%} "
              f"{m['mdd']:>8.1%} {m['calmar']:>8.2f} {m['sortino']:>8.2f}")
    print()

# R4 ranking stability across sub-periods
print("--- R4 RANKING STABILITY ACROSS SUB-PERIODS ---")
for asset_id, ar in r4_results.items():
    if "sub_periods" not in ar:
        continue
    print(f"\n  {asset_id}:")
    print(f"  {'Period':<20} {'Best':>12} {'2nd':>12} {'3rd':>12} {'4th':>12}")
    print("  " + "-" * 60)
    for period_label, sub_r in ar["sub_periods"].items():
        ranking = sorted(
            [("12/VIX", sub_r["vix_vt"]["sharpe"]),
             ("EWMA", sub_r["ewma_vt"]["sharpe"]),
             ("GJR", sub_r["gjr_vt"]["sharpe"]),
             ("B&H", sub_r["bh"]["sharpe"])],
            key=lambda x: -x[1]
        )
        rank_str = [f"{name}({s:.2f})" for name, s in ranking]
        print(f"  {period_label:<20} {rank_str[0]:>12} {rank_str[1]:>12} {rank_str[2]:>12} {rank_str[3]:>12}")


# ======================================================================
# R5: BOOTSTRAP CONFIDENCE INTERVALS
# ======================================================================
print("\n" + "=" * 80)
print("R5: BOOTSTRAP CONFIDENCE INTERVALS")
print("=" * 80)
print(f"  {N_BOOTSTRAP} block bootstrap (block={BLOCK_SIZE}d), 95% CI\n")

r5_results = {}

for asset_id, info in ASSETS.items():
    df = all_data[asset_id].copy()
    mask = (df.index >= FULL_PERIOD[0]) & (df.index <= FULL_PERIOD[1])
    df = df[mask]
    returns = df["returns"].values

    if len(returns) < GARCH_WINDOW + 200:
        continue

    # Get GJR vol
    vol_gjr, gamma_ts = rolling_gjr_forecast(returns, window=GARCH_WINDOW)

    valid = ~np.isnan(vol_gjr)
    ret_v = returns[valid]
    gjr_v = vol_gjr[valid]
    gamma_v = gamma_ts[valid]
    gamma_valid = gamma_v[~np.isnan(gamma_v)]

    # Full-sample statistics
    vt_ret, _ = vt_strategy(ret_v, gjr_v)
    full_metrics = compute_metrics(vt_ret)
    full_gamma = np.nanmean(gamma_v)

    print(f"  {asset_id}: bootstrapping {N_BOOTSTRAP} times...")
    t_start = time.time()

    # Block bootstrap
    n = len(ret_v)
    n_blocks = n // BLOCK_SIZE + 1

    boot_sharpes = []
    boot_mdds = []
    boot_gammas = []

    for b in range(N_BOOTSTRAP):
        # Sample blocks with replacement
        block_starts = np.random.randint(0, n - BLOCK_SIZE, size=n_blocks)
        boot_idx = []
        for bs in block_starts:
            boot_idx.extend(range(bs, min(bs + BLOCK_SIZE, n)))
        boot_idx = boot_idx[:n]  # trim to original length

        boot_ret = ret_v[boot_idx]
        boot_vol = gjr_v[boot_idx]

        # VT on bootstrapped sample
        boot_vt_ret, _ = vt_strategy(boot_ret, boot_vol)
        boot_m = compute_metrics(boot_vt_ret)
        boot_sharpes.append(boot_m["sharpe"])
        boot_mdds.append(boot_m["mdd"])

        # Bootstrap gamma (from valid gamma estimates)
        if len(gamma_valid) > 0:
            boot_gamma_idx = np.random.choice(len(gamma_valid), size=len(gamma_valid), replace=True)
            boot_gammas.append(np.mean(gamma_valid[boot_gamma_idx]))

    elapsed = time.time() - t_start

    boot_sharpes = np.array(boot_sharpes)
    boot_mdds = np.array(boot_mdds)
    boot_gammas = np.array(boot_gammas) if boot_gammas else np.array([np.nan])

    r5_results[asset_id] = {
        "full_sharpe": float(full_metrics["sharpe"]),
        "full_mdd": float(full_metrics["mdd"]),
        "full_gamma": float(full_gamma),
        "sharpe_ci_95": (float(np.percentile(boot_sharpes, 2.5)),
                         float(np.percentile(boot_sharpes, 97.5))),
        "sharpe_mean_boot": float(np.mean(boot_sharpes)),
        "sharpe_se": float(np.std(boot_sharpes)),
        "mdd_ci_95": (float(np.percentile(boot_mdds, 2.5)),
                      float(np.percentile(boot_mdds, 97.5))),
        "gamma_ci_95": (float(np.percentile(boot_gammas, 2.5)),
                        float(np.percentile(boot_gammas, 97.5))),
        "gamma_mean_boot": float(np.mean(boot_gammas)),
        "sharpe_prob_positive": float(np.mean(boot_sharpes > 0)),
        "gamma_prob_positive": float(np.mean(boot_gammas > 0)),
        "elapsed_sec": float(elapsed),
    }

    sc = r5_results[asset_id]["sharpe_ci_95"]
    mc = r5_results[asset_id]["mdd_ci_95"]
    gc = r5_results[asset_id]["gamma_ci_95"]
    print(f"  {asset_id}: Sharpe={full_metrics['sharpe']:.3f} CI=[{sc[0]:.3f}, {sc[1]:.3f}], "
          f"MDD={full_metrics['mdd']:.1%} CI=[{mc[0]:.1%}, {mc[1]:.1%}], "
          f"γ={full_gamma:.4f} CI=[{gc[0]:.4f}, {gc[1]:.4f}] "
          f"({elapsed:.1f}s)")

# R5 Summary
print("\n--- R5 BOOTSTRAP SUMMARY TABLE ---")
print(f"{'Asset':<6} {'Sharpe':>8} {'95% CI':>18} {'P(>0)':>7} "
      f"{'MDD':>8} {'95% CI':>18} "
      f"{'γ':>8} {'95% CI':>18} {'P(γ>0)':>8}")
print("-" * 120)
for asset_id, r in r5_results.items():
    sc = r["sharpe_ci_95"]
    mc = r["mdd_ci_95"]
    gc = r["gamma_ci_95"]
    print(f"{asset_id:<6} {r['full_sharpe']:>8.3f} [{sc[0]:>7.3f}, {sc[1]:>7.3f}] "
          f"{r['sharpe_prob_positive']:>7.1%} "
          f"{r['full_mdd']:>8.1%} [{mc[0]:>7.1%}, {mc[1]:>7.1%}] "
          f"{r['full_gamma']:>8.4f} [{gc[0]:>7.4f}, {gc[1]:>7.4f}] "
          f"{r['gamma_prob_positive']:>8.1%}")


# ======================================================================
# OVERALL SYNTHESIS
# ======================================================================
print("\n" + "=" * 80)
print("OVERALL SYNTHESIS — K149 JBF ROBUSTNESS SUITE")
print("=" * 80)

# R1 synthesis
print("\nR1 (Sub-sample Stability):")
for asset_id in ASSETS:
    if asset_id in r1_results:
        gammas = []
        sharpe_diffs = []
        for _, _, pl in SUB_PERIODS:
            if pl in r1_results[asset_id] and "gamma_full" in r1_results[asset_id][pl]:
                g = r1_results[asset_id][pl]["gamma_full"]
                sd = r1_results[asset_id][pl]["sharpe_improvement"]
                if not np.isnan(g):
                    gammas.append(g)
                if not np.isnan(sd):
                    sharpe_diffs.append(sd)

        if gammas:
            sign_stable = "YES" if (all(g > 0 for g in gammas) or all(g < 0 for g in gammas)) else "NO"
            vt_helps = sum(1 for s in sharpe_diffs if s > 0)
            print(f"  {asset_id}: gamma sign stable across sub-periods: {sign_stable}, "
                  f"VT beats B&H in {vt_helps}/{len(sharpe_diffs)} sub-periods")

# R2 synthesis
print("\nR2 (Alternative Vol Proxy):")
gjr_wins_r2 = sum(1 for r in r2_results.values() if r["gjr_wins_r2"])
gjr_wins_pk = sum(1 for r in r2_results.values() if r["gjr_wins_parkinson"])
total = len(r2_results)
print(f"  GJR beats GARCH: {gjr_wins_r2}/{total} assets with r² proxy, "
      f"{gjr_wins_pk}/{total} with Parkinson proxy")
sig_r2 = sum(1 for r in r2_results.values() if r["dm_p_r2"] < 0.05 and r["gjr_wins_r2"])
sig_pk = sum(1 for r in r2_results.values() if r["dm_p_parkinson"] < 0.05 and r["gjr_wins_parkinson"])
print(f"  Significantly better (p<0.05): {sig_r2}/{total} (r²), {sig_pk}/{total} (Parkinson)")

# R3 synthesis
print("\nR3 (Transaction Costs):")
for asset_id, ar in r3_results.items():
    max_cost_still_wins = 0
    for cost_bps in TX_COST_LEVELS:
        if ar["costs"][cost_bps]["sharpe"] > ar["bh"]["sharpe"]:
            max_cost_still_wins = cost_bps
    if max_cost_still_wins >= TX_COST_LEVELS[-1]:
        print(f"  {asset_id}: VT still beats B&H even at {TX_COST_LEVELS[-1]}bps")
    elif max_cost_still_wins > 0:
        print(f"  {asset_id}: VT beats B&H up to ~{max_cost_still_wins}bps")
    else:
        print(f"  {asset_id}: VT does not consistently beat B&H on Sharpe")

# R4 synthesis
print("\nR4 (Alternative VT Rules):")
for asset_id, ar in r4_results.items():
    methods = [("12/VIX", ar["vix_vt"]["sharpe"]),
               ("EWMA", ar["ewma_vt"]["sharpe"]),
               ("GJR", ar["gjr_vt"]["sharpe"]),
               ("Const60/40", ar["const_60_40"]["sharpe"]),
               ("B&H", ar["bh"]["sharpe"])]
    ranked = sorted(methods, key=lambda x: -x[1])
    rank_strs = [f"{name}({s:.2f})" for name, s in ranked]
    print(f"  {asset_id}: {' > '.join(rank_strs)}")

# R5 synthesis
print("\nR5 (Bootstrap CIs):")
for asset_id, r in r5_results.items():
    sc = r["sharpe_ci_95"]
    gc = r["gamma_ci_95"]
    sharpe_sig = "YES" if sc[0] > 0 else "NO"
    gamma_sig = "YES" if gc[0] > 0 else "NO"
    print(f"  {asset_id}: Sharpe CI excludes zero: {sharpe_sig} [{sc[0]:.3f}, {sc[1]:.3f}], "
          f"gamma CI excludes zero: {gamma_sig} [{gc[0]:.4f}, {gc[1]:.4f}]")

# Final verdict
print("\n" + "=" * 80)
print("VERDICT FOR PAPER SECTION 5:")
print("=" * 80)

# Count robustness evidence
robust_claims = {
    "gamma_sign_stability": 0,
    "proxy_robustness": 0,
    "tx_cost_tolerance": 0,
    "gjr_ranking": 0,
    "ci_significance": 0,
}

for asset_id in ASSETS:
    # R1
    if asset_id in r1_results:
        gammas = [r1_results[asset_id][pl]["gamma_full"]
                  for _, _, pl in SUB_PERIODS
                  if pl in r1_results[asset_id] and "gamma_full" in r1_results[asset_id][pl]
                  and not np.isnan(r1_results[asset_id][pl]["gamma_full"])]
        if gammas and (all(g > 0 for g in gammas) or all(g < 0 for g in gammas)):
            robust_claims["gamma_sign_stability"] += 1

    # R2
    if asset_id in r2_results and r2_results[asset_id]["gjr_wins_parkinson"]:
        robust_claims["proxy_robustness"] += 1

    # R3
    if asset_id in r3_results:
        if r3_results[asset_id]["costs"][20]["sharpe"] > r3_results[asset_id]["bh"]["sharpe"]:
            robust_claims["tx_cost_tolerance"] += 1

    # R4
    if asset_id in r4_results:
        gjr_sharpe = r4_results[asset_id]["gjr_vt"]["sharpe"]
        others = [r4_results[asset_id]["ewma_vt"]["sharpe"],
                  r4_results[asset_id]["vix_vt"]["sharpe"]]
        if gjr_sharpe >= max(others):
            robust_claims["gjr_ranking"] += 1

    # R5
    if asset_id in r5_results:
        if r5_results[asset_id]["sharpe_ci_95"][0] > 0:
            robust_claims["ci_significance"] += 1

n_assets = len(ASSETS)
print(f"  R1 gamma sign stable:     {robust_claims['gamma_sign_stability']}/{n_assets} assets")
print(f"  R2 GJR wins (Parkinson):  {robust_claims['proxy_robustness']}/{n_assets} assets")
print(f"  R3 VT beats B&H @20bps:   {robust_claims['tx_cost_tolerance']}/{n_assets} assets")
print(f"  R4 GJR top-ranked:        {robust_claims['gjr_ranking']}/{n_assets} assets")
print(f"  R5 Sharpe CI > 0:         {robust_claims['ci_significance']}/{n_assets} assets")

caveats = []
if robust_claims["gamma_sign_stability"] < n_assets:
    unstable = [a for a in ASSETS if a not in r1_results or
                not all(r1_results[a].get(pl, {}).get("gamma_full", 0) > 0
                        for _, _, pl in SUB_PERIODS if pl in r1_results.get(a, {}))]
    if unstable:
        caveats.append(f"Gamma sign unstable for: {', '.join(unstable)}")

if robust_claims["proxy_robustness"] < n_assets:
    non_robust = [a for a in ASSETS if a in r2_results and not r2_results[a]["gjr_wins_parkinson"]]
    if non_robust:
        caveats.append(f"GJR does not beat GARCH with Parkinson proxy for: {', '.join(non_robust)}")

if robust_claims["tx_cost_tolerance"] < n_assets:
    caveats.append("Some assets lose VT advantage at 20bps TX cost")

if caveats:
    print("\nCAVEATS (must address in paper):")
    for c in caveats:
        print(f"  - {c}")
else:
    print("\n  All claims are ROBUST across all checks.")

# ======================================================================
# SAVE RESULTS
# ======================================================================
output = {
    "experiment": "K149_JBF_Robustness_Suite",
    "proposed_by": "Gemini R6#1",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "assets": list(ASSETS.keys()),
        "full_period": FULL_PERIOD,
        "sub_periods": [(s, e, l) for s, e, l in SUB_PERIODS],
        "garch_window": GARCH_WINDOW,
        "n_bootstrap": N_BOOTSTRAP,
        "block_size": BLOCK_SIZE,
        "tx_cost_levels": TX_COST_LEVELS,
    },
    "R1_subsample_stability": r1_results,
    "R2_alternative_proxy": r2_results,
    "R3_transaction_costs": {
        asset_id: {
            "bh_sharpe": ar["bh"]["sharpe"],
            "costs": {str(k): {kk: vv for kk, vv in v.items()}
                      for k, v in ar["costs"].items()}
        }
        for asset_id, ar in r3_results.items()
    },
    "R4_alternative_rules": {
        asset_id: {
            method: {k: float(v) for k, v in metrics.items()}
            for method, metrics in ar.items()
            if method != "sub_periods"
        }
        for asset_id, ar in r4_results.items()
    },
    "R5_bootstrap_ci": r5_results,
    "verdict": robust_claims,
    "caveats": caveats,
}

# Convert numpy types for JSON serialization
def numpy_to_python(obj):
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        converted = [numpy_to_python(i) for i in obj]
        return type(obj)(converted) if isinstance(obj, tuple) else converted
    return obj

output = numpy_to_python(output)

output_path = project_root / "experiments" / "results" / "k149_jbf_robustness_suite.json"
output_path.parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("\n[K149 COMPLETE]")
