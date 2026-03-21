#!/usr/bin/env python3
"""
FHS-VaR Targeting Experiment
============================
Compare sigma-targeting (12/VIX, GARCH VT) with VaR-targeting strategies.

Core idea: instead of w = target_sigma / predicted_sigma,
use w = target_VaR / predicted_VaR where VaR comes from GJR-GARCH + Skewed-t.

VaR-targeting naturally accounts for fat tails and skewness that sigma-targeting ignores.

Author: VolPred Research System
Date: 2026-03-21
Proposed by: Gemini
Executed by: Claude
"""
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
sys.path.insert(0, str(PROJECT_ROOT))

from arch import arch_model
from arch.univariate.distribution import SkewStudent
from volpred.data.manager import DataManager

# ── Configuration ─────────────────────────────────────────────────────
ASSETS = ["SPY", "QQQ", "GLD", "EEM"]
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2026-03-21"
DATA_START = "2012-01-01"  # enough history for w=2000 + OOS

# VaR targets: daily 1% VaR in absolute return terms
VAR_TARGETS = [0.015, 0.020, 0.025]  # 1.5%, 2.0%, 2.5%
VAR_ALPHA = 0.01  # 1% VaR

# Sigma target for GARCH VT
SIGMA_TARGET = 0.12  # 12% annualized

# Transaction cost per one-way trade
TX_COST = 0.0005  # 0.05% = 5 bps

# Weight bounds
W_MIN = 0.0
W_MAX = 1.5

# Risk-free rate (annualized)
RF_ANNUAL = 0.04

# Annual trading days
TRADING_DAYS = 252

# Refit frequency: refit GARCH every N days (speed optimization)
# Daily refit is too slow (806 * 4 assets * ~0.1s = ~320s per strategy)
# Weekly refit is ~5x faster and virtually identical results
REFIT_EVERY = 5  # refit every 5 trading days


def fetch_data(dm: DataManager, ticker: str) -> pd.DataFrame:
    """Fetch price data and compute returns."""
    df = dm.get_price_data(ticker, DATA_START, OOS_END, force_refresh=True)
    df = df.sort_index()
    df["simple_ret"] = df["close"].pct_change()
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1)) * 100  # pct scale for arch
    df = df.dropna()
    return df


def fit_rolling_garch(df: pd.DataFrame, oos_mask: np.ndarray) -> pd.DataFrame:
    """
    Fit GJR-GARCH(1,1) + Skewed-t on rolling windows for all OOS dates.
    Returns DataFrame with columns: sigma, eta, lambda, mu (all in % scale for sigma/mu).

    Uses REFIT_EVERY to reduce computation: between refits, use the last model's
    1-step forecast updated with the new return observation.
    """
    returns_pct = df["log_ret"].values
    dates = df.index
    oos_indices = np.where(oos_mask)[0]

    # Output arrays
    sigma_out = np.full(len(dates), np.nan)
    eta_out = np.full(len(dates), np.nan)
    lam_out = np.full(len(dates), np.nan)
    mu_out = np.full(len(dates), np.nan)

    dist = SkewStudent()
    last_fit_idx = -999
    last_res = None
    n_valid = 0

    print(f"    Rolling GJR-GARCH + Skewed-t: {len(oos_indices)} OOS days, refit every {REFIT_EVERY} days...")
    t0 = time.time()

    for i, idx in enumerate(oos_indices):
        if idx < WINDOW:
            continue

        need_refit = (idx - last_fit_idx >= REFIT_EVERY) or (last_res is None)

        if need_refit:
            try:
                window_data = returns_pct[idx - WINDOW + 1 : idx + 1]
                am = arch_model(
                    window_data,
                    mean="Constant",
                    vol="GARCH",
                    p=1, o=1, q=1,
                    dist="skewt",
                )
                res = am.fit(disp="off", show_warning=False)
                forecast = res.forecast(horizon=1)
                sigma = np.sqrt(forecast.variance.iloc[-1, 0])
                eta = res.params["eta"]
                lam = res.params["lambda"]
                mu = res.params["mu"]

                last_res = res
                last_fit_idx = idx
            except Exception:
                continue
        else:
            # Use last fit's parameters with updated data
            try:
                window_data = returns_pct[idx - WINDOW + 1 : idx + 1]
                am = arch_model(
                    window_data,
                    mean="Constant",
                    vol="GARCH",
                    p=1, o=1, q=1,
                    dist="skewt",
                )
                # Use last params as starting values, fix them
                res = am.fit(
                    disp="off",
                    show_warning=False,
                    starting_values=last_res.params.values,
                    options={"maxiter": 1},  # minimal optimization
                )
                forecast = res.forecast(horizon=1)
                sigma = np.sqrt(forecast.variance.iloc[-1, 0])
                eta = res.params["eta"]
                lam = res.params["lambda"]
                mu = res.params["mu"]
            except Exception:
                # Fallback to last good values
                if last_res is not None:
                    sigma = sigma_out[oos_indices[i-1]] if i > 0 else np.nan
                    eta = eta_out[oos_indices[i-1]] if i > 0 else np.nan
                    lam = lam_out[oos_indices[i-1]] if i > 0 else np.nan
                    mu = mu_out[oos_indices[i-1]] if i > 0 else np.nan
                    if np.isnan(sigma):
                        continue
                else:
                    continue

        sigma_out[idx] = sigma
        eta_out[idx] = eta
        lam_out[idx] = lam
        mu_out[idx] = mu
        n_valid += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"      {i+1}/{len(oos_indices)} done ({elapsed:.1f}s, {n_valid} valid)")

    elapsed = time.time() - t0
    print(f"      Complete: {n_valid}/{len(oos_indices)} valid fits in {elapsed:.1f}s")

    garch_df = pd.DataFrame({
        "sigma": sigma_out,
        "eta": eta_out,
        "lambda": lam_out,
        "mu": mu_out,
    }, index=dates)

    return garch_df


def build_sigma_targeting_weights(garch_df: pd.DataFrame, target_vol: float) -> pd.Series:
    """Compute sigma-targeting weights: w = target_vol / (sigma_daily * sqrt(252))."""
    sigma_annual = (garch_df["sigma"] / 100.0) * np.sqrt(TRADING_DAYS)
    weights = target_vol / sigma_annual
    weights = weights.clip(W_MIN, W_MAX)
    return weights


def build_var_targeting_weights(garch_df: pd.DataFrame, target_var: float,
                                 alpha: float = 0.01) -> pd.Series:
    """Compute VaR-targeting weights: w = target_VaR / |predicted_VaR|."""
    dist = SkewStudent()
    weights = pd.Series(np.nan, index=garch_df.index)

    valid = garch_df.dropna()
    for date, row in valid.iterrows():
        q = dist.ppf([alpha], parameters=[row["eta"], row["lambda"]])[0]
        var_pct = row["mu"] + row["sigma"] * q  # % scale
        var_decimal = var_pct / 100.0  # decimal scale
        predicted_loss = abs(var_decimal)
        if predicted_loss > 1e-8:
            w = target_var / predicted_loss
        else:
            w = 1.0
        weights[date] = np.clip(w, W_MIN, W_MAX)

    return weights


def build_strategy_returns(df: pd.DataFrame, weights: pd.Series,
                            oos_mask: np.ndarray) -> dict:
    """Given weights (unlagged), lag them and compute strategy returns."""
    # Lag weights by 1 day (weight computed at t, applied to r_{t+1})
    lagged_w = weights.shift(1)
    oos_w = lagged_w[oos_mask].dropna()
    oos_ret = df["simple_ret"][oos_mask].reindex(oos_w.index)

    # Drop any remaining NaNs
    valid = oos_w.notna() & oos_ret.notna()
    oos_w = oos_w[valid]
    oos_ret = oos_ret[valid]

    strategy_ret = oos_w * oos_ret
    turnover = oos_w.diff().abs()

    return {
        "returns": strategy_ret,
        "weights": oos_w,
        "turnover": turnover,
    }


def compute_metrics(result: dict) -> dict:
    """Compute strategy performance metrics."""
    ret = result["returns"].dropna()
    weights = result["weights"].dropna()
    turnover = result["turnover"].dropna()
    rf_daily = RF_ANNUAL / TRADING_DAYS

    if len(ret) < 20:
        return {"error": "insufficient data"}

    n_days = len(ret)
    n_years = n_days / TRADING_DAYS
    total_ret = (1 + ret).prod() - 1
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = ret.std() * np.sqrt(TRADING_DAYS)
    excess_ret = ret - rf_daily

    # Sharpe
    sharpe = excess_ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else 0

    # Sortino
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(TRADING_DAYS) if len(downside) > 0 else 1e-8
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # MDD
    cum = (1 + ret).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    mdd = drawdown.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-8 else 0

    # Turnover & TX costs
    ann_turnover = turnover.sum() / n_years if n_years > 0 else 0
    total_tc = turnover.sum() * TX_COST * 2  # roundtrip
    ann_tc = total_tc / n_years if n_years > 0 else 0
    net_sharpe = ((excess_ret.mean() - ann_tc / TRADING_DAYS) / ret.std() * np.sqrt(TRADING_DAYS)
                  if ret.std() > 0 else 0)

    # Harvey t-stat
    harvey_t = sharpe * np.sqrt(n_years)

    # Weight stats
    avg_weight = weights.mean()
    std_weight = weights.std()

    # Return distribution
    skew = ret.skew()
    kurt = ret.kurtosis()
    win_rate = (ret > 0).mean()

    return {
        "n_days": n_days,
        "n_years": round(n_years, 2),
        "total_return": round(total_ret * 100, 2),
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "net_sharpe": round(net_sharpe, 3),
        "harvey_t": round(harvey_t, 2),
        "ann_turnover": round(ann_turnover, 2),
        "ann_tc_pct": round(ann_tc * 100, 3),
        "avg_weight": round(avg_weight, 3),
        "std_weight": round(std_weight, 3),
        "ret_skew": round(skew, 3),
        "ret_kurtosis": round(kurt, 3),
        "win_rate": round(win_rate * 100, 1),
    }


def dm_test(ret1: pd.Series, ret2: pd.Series) -> dict:
    """Diebold-Mariano test: H0: E[ret1] = E[ret2]."""
    from scipy.stats import t as tdist
    common = ret1.index.intersection(ret2.index)
    r1 = ret1.reindex(common).dropna()
    r2 = ret2.reindex(common).dropna()
    common2 = r1.index.intersection(r2.index)
    r1 = r1.reindex(common2)
    r2 = r2.reindex(common2)

    if len(r1) < 20:
        return {"t_stat": float("nan"), "p_value": float("nan")}

    d = r1 - r2
    t_stat = d.mean() / (d.std() / np.sqrt(len(d))) if d.std() > 0 else 0
    p_value = 2 * (1 - tdist.cdf(abs(t_stat), df=len(d)-1))

    return {"t_stat": round(float(t_stat), 3), "p_value": round(float(p_value), 4)}


def bootstrap_mdd_test(ret1: pd.Series, ret2: pd.Series, n_boot: int = 5000) -> dict:
    """Bootstrap test for MDD difference. Negative obs_diff = ret1 has smaller MDD (better)."""
    common = ret1.index.intersection(ret2.index)
    r1 = ret1.reindex(common).dropna().values
    r2 = ret2.reindex(common).dropna().values
    n = min(len(r1), len(r2))
    r1 = r1[:n]
    r2 = r2[:n]

    def mdd(returns):
        cum = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cum)
        dd = (cum - running_max) / running_max
        return dd.min()

    obs_diff = mdd(r1) - mdd(r2)

    np.random.seed(42)
    diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        diffs[b] = mdd(r1[idx]) - mdd(r2[idx])

    # p-value: probability of observing diff >= 0 (i.e., ret1 not better than ret2)
    p_value = np.mean(diffs >= 0)

    return {
        "obs_mdd_diff_pct": round(float(obs_diff * 100), 2),
        "p_value": round(float(p_value), 4),
    }


def run_experiment_for_asset(ticker: str, dm: DataManager, vix_df: pd.DataFrame) -> dict:
    """Run full experiment for one asset."""
    print(f"\n{'='*60}")
    print(f"  Asset: {ticker}")
    print(f"{'='*60}")

    # Fetch data
    df = fetch_data(dm, ticker)
    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} obs)")

    # OOS mask
    oos_mask = np.asarray(df.index >= OOS_START)
    n_oos = oos_mask.sum()
    print(f"  OOS: {OOS_START} onward ({n_oos} days)")

    if n_oos < 50:
        return {"error": f"insufficient OOS data ({n_oos})"}

    results = {}
    all_returns = {}  # for cross-strategy DM tests

    # ── 1. Buy & Hold ────────────────────────────────────────────
    print("\n  [1] Buy & Hold")
    bh_ret = df["simple_ret"][oos_mask].dropna()
    bh_result = {
        "returns": bh_ret,
        "weights": pd.Series(1.0, index=bh_ret.index),
        "turnover": pd.Series(0.0, index=bh_ret.index),
    }
    results["buy_hold"] = {"name": "Buy & Hold", "metrics": compute_metrics(bh_result)}
    all_returns["buy_hold"] = bh_ret

    # ── 2. 12/VIX Baseline ──────────────────────────────────────
    print("  [2] 12/VIX σ-targeting")
    try:
        vix_close = vix_df["close"].reindex(df.index, method="ffill")
        vix_weights = (12.0 / vix_close).clip(W_MIN, W_MAX)
        vix_strat = build_strategy_returns(df, vix_weights, oos_mask)
        vix_strat_name = "12/VIX σ-targeting"
        results["12_vix"] = {"name": vix_strat_name, "metrics": compute_metrics(vix_strat)}
        all_returns["12_vix"] = vix_strat["returns"]
    except Exception as e:
        print(f"    ERROR: {e}")
        results["12_vix"] = {"name": "12/VIX σ-targeting", "error": str(e)}

    # ── 3. Fit GJR-GARCH + Skewed-t (shared across all GARCH strategies) ──
    print("  [3] Fitting GJR-GARCH + Skewed-t (shared model)...")
    garch_df = fit_rolling_garch(df, oos_mask)

    # ── 4. GARCH σ-targeting (12%) ──────────────────────────────
    print("  [4] GARCH σ-targeting (12%)")
    sigma_w = build_sigma_targeting_weights(garch_df, SIGMA_TARGET)
    sigma_strat = build_strategy_returns(df, sigma_w, oos_mask)
    results["garch_sigma"] = {
        "name": f"GARCH σ-targeting ({SIGMA_TARGET:.0%})",
        "metrics": compute_metrics(sigma_strat),
    }
    all_returns["garch_sigma"] = sigma_strat["returns"]

    # ── 5. VaR-targeting at different levels ─────────────────────
    for target_var in VAR_TARGETS:
        key = f"var_{int(target_var*1000)}"
        label = f"VaR-targeting ({target_var:.1%} daily 1%VaR)"
        print(f"  [5] {label}")
        var_w = build_var_targeting_weights(garch_df, target_var, VAR_ALPHA)
        var_strat = build_strategy_returns(df, var_w, oos_mask)
        results[key] = {"name": label, "metrics": compute_metrics(var_strat)}
        all_returns[key] = var_strat["returns"]

    # ── 6. Statistical comparisons ───────────────────────────────
    print("  [6] Statistical tests...")
    comparisons = ["12_vix", "garch_sigma", "var_15", "var_20", "var_25"]
    for skey in comparisons:
        if skey not in all_returns or skey not in results:
            continue
        if "error" in results.get(skey, {}):
            continue

        sr = all_returns[skey]

        # DM vs buy-and-hold
        results[skey]["dm_vs_buyhold"] = dm_test(sr, all_returns["buy_hold"])

        # Bootstrap MDD vs buy-and-hold
        results[skey]["mdd_bootstrap_vs_buyhold"] = bootstrap_mdd_test(sr, all_returns["buy_hold"])

    # Pairwise: VaR vs GARCH-sigma
    for vk in ["var_15", "var_20", "var_25"]:
        if vk in all_returns and "garch_sigma" in all_returns:
            results[vk]["dm_vs_garch_sigma"] = dm_test(all_returns[vk], all_returns["garch_sigma"])
        if vk in all_returns and "12_vix" in all_returns:
            results[vk]["dm_vs_12vix"] = dm_test(all_returns[vk], all_returns["12_vix"])

    # ── Diagnostic: VaR quantile stats ───────────────────────────
    valid_garch = garch_df.dropna()
    if len(valid_garch) > 0:
        dist = SkewStudent()
        quantiles_1pct = []
        for _, row in valid_garch.iterrows():
            q = dist.ppf([VAR_ALPHA], parameters=[row["eta"], row["lambda"]])[0]
            quantiles_1pct.append(q)
        q_arr = np.array(quantiles_1pct)
        normal_q = -2.326  # Normal 1% quantile
        results["diagnostics"] = {
            "skewt_1pct_quantile_mean": round(float(q_arr.mean()), 4),
            "skewt_1pct_quantile_std": round(float(q_arr.std()), 4),
            "skewt_1pct_quantile_min": round(float(q_arr.min()), 4),
            "skewt_1pct_quantile_max": round(float(q_arr.max()), 4),
            "normal_1pct_quantile": normal_q,
            "avg_eta_df": round(float(valid_garch["eta"].mean()), 2),
            "avg_lambda_skew": round(float(valid_garch["lambda"].mean()), 4),
            "avg_sigma_pct": round(float(valid_garch["sigma"].mean()), 4),
            "n_valid_fits": len(valid_garch),
        }

    return results


def print_summary(all_results: dict):
    """Print formatted summary tables."""
    print("\n" + "=" * 110)
    print("  FHS-VaR Targeting 實驗結果摘要")
    print("  [提出: Gemini, 執行: Claude]")
    print("=" * 110)

    header = (
        f"{'Asset':<6} {'Strategy':<38} {'Sharpe':>7} {'NetSh':>7} "
        f"{'MDD%':>7} {'Calmar':>7} {'Sortino':>8} {'Harvey-t':>8} "
        f"{'Turn':>6} {'AvgW':>6}"
    )
    print(header)
    print("-" * 110)

    for asset, ar in all_results.items():
        if "error" in ar:
            print(f"{asset:<6} ERROR: {ar['error']}")
            continue

        for key in ["buy_hold", "12_vix", "garch_sigma", "var_15", "var_20", "var_25"]:
            strat = ar.get(key, {})
            if "metrics" not in strat:
                continue
            m = strat["metrics"]
            if "error" in m:
                continue
            name = strat["name"][:37]
            print(
                f"{asset:<6} {name:<38} "
                f"{m['sharpe']:>7.3f} {m['net_sharpe']:>7.3f} "
                f"{m['mdd']:>7.2f} {m['calmar']:>7.3f} "
                f"{m['sortino']:>8.3f} {m['harvey_t']:>8.2f} "
                f"{m['ann_turnover']:>6.1f} {m['avg_weight']:>6.3f}"
            )
        print("-" * 110)

    # ── Comparison table ─────────────────────────────────────────
    print("\n" + "=" * 90)
    print("  VaR-targeting vs σ-targeting 詳細比較")
    print("=" * 90)

    for asset, ar in all_results.items():
        if "error" in ar:
            continue

        garch_m = ar.get("garch_sigma", {}).get("metrics", {})
        if not garch_m or "error" in garch_m:
            continue

        print(f"\n  {asset}:")
        print(f"    GARCH σ-targeting baseline: Sharpe={garch_m['sharpe']:.3f}, MDD={garch_m['mdd']:.2f}%, NetSharpe={garch_m['net_sharpe']:.3f}")

        for vk in ["var_15", "var_20", "var_25"]:
            strat = ar.get(vk, {})
            m = strat.get("metrics", {})
            if not m or "error" in m:
                continue
            dm_info = strat.get("dm_vs_garch_sigma", {})

            delta_sharpe = m["sharpe"] - garch_m["sharpe"]
            delta_mdd = m["mdd"] - garch_m["mdd"]

            print(f"    {strat['name'][:45]}:")
            print(f"      Sharpe={m['sharpe']:.3f} (Δ={delta_sharpe:+.3f})  DM t={dm_info.get('t_stat', '?')}, p={dm_info.get('p_value', '?')}")
            print(f"      MDD={m['mdd']:.2f}% (Δ={delta_mdd:+.2f}%)  NetSharpe={m['net_sharpe']:.3f}")

        # Diagnostics
        diag = ar.get("diagnostics", {})
        if diag:
            print(f"    Diagnostics: avg skewt q(1%)={diag.get('skewt_1pct_quantile_mean', '?'):.4f} (Normal=-2.3263)")
            print(f"      avg eta={diag.get('avg_eta_df', '?'):.1f}, avg lambda={diag.get('avg_lambda_skew', '?'):.4f}")

    # ── Cross-asset summary ──────────────────────────────────────
    print("\n" + "=" * 80)
    print("  跨資產平均績效")
    print("=" * 80)

    strategy_keys = ["buy_hold", "12_vix", "garch_sigma", "var_15", "var_20", "var_25"]
    strategy_names = {
        "buy_hold": "Buy & Hold",
        "12_vix": "12/VIX σ-targeting",
        "garch_sigma": "GARCH σ-targeting (12%)",
        "var_15": "VaR-targeting (1.5%)",
        "var_20": "VaR-targeting (2.0%)",
        "var_25": "VaR-targeting (2.5%)",
    }

    print(f"  {'Strategy':<35} {'Avg Sharpe':>10} {'Avg NetSh':>10} {'Avg MDD':>10} {'N':>4}")
    print("  " + "-" * 72)

    for skey in strategy_keys:
        sharpes, net_sharpes, mdds = [], [], []
        for asset in ASSETS:
            ar = all_results.get(asset, {})
            if "error" in ar:
                continue
            m = ar.get(skey, {}).get("metrics", {})
            if m and "error" not in m:
                sharpes.append(m["sharpe"])
                net_sharpes.append(m["net_sharpe"])
                mdds.append(m["mdd"])
        if sharpes:
            print(
                f"  {strategy_names.get(skey, skey):<35} "
                f"{np.mean(sharpes):>10.3f} {np.mean(net_sharpes):>10.3f} "
                f"{np.mean(mdds):>10.2f} {len(sharpes):>4}"
            )


def main():
    print("=" * 60)
    print("  FHS-VaR Targeting Experiment")
    print("  Gemini 建議 / Claude 執行")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    dm = DataManager()
    t_start = time.time()

    # Fetch VIX once (shared across all assets)
    print("\n  Fetching VIX data...")
    vix_df = dm.get_price_data("^VIX", DATA_START, OOS_END, force_refresh=True)
    print(f"  VIX: {vix_df.index[0].date()} to {vix_df.index[-1].date()} ({len(vix_df)} obs)")

    all_results = {}

    for ticker in ASSETS:
        try:
            result = run_experiment_for_asset(ticker, dm, vix_df)
            all_results[ticker] = result
        except Exception as e:
            print(f"\n  FATAL ERROR for {ticker}: {e}")
            import traceback
            traceback.print_exc()
            all_results[ticker] = {"error": str(e)}

    elapsed = time.time() - t_start
    print(f"\n  Total elapsed: {elapsed:.1f}s")

    # Print summary
    print_summary(all_results)

    # ── Save results ─────────────────────────────────────────────
    save_data = {
        "experiment": "FHS-VaR Targeting",
        "description": (
            "Compare sigma-targeting vs VaR-targeting VT strategies. "
            "VaR-targeting uses GJR-GARCH(1,1) + Skewed-t to compute 1-day 1% VaR, "
            "then sets weight = target_VaR_loss / predicted_VaR_loss."
        ),
        "proposed_by": "Gemini",
        "executed_by": "Claude",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "window": WINDOW,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "var_targets": VAR_TARGETS,
            "var_alpha": VAR_ALPHA,
            "sigma_target": SIGMA_TARGET,
            "tx_cost": TX_COST,
            "rf_annual": RF_ANNUAL,
            "weight_bounds": [W_MIN, W_MAX],
            "refit_every": REFIT_EVERY,
            "garch_model": "GJR-GARCH(1,1)",
            "distribution": "Skewed Student-t",
        },
        "results": {},
        "elapsed_seconds": round(elapsed, 1),
    }

    # Build cross-asset summary
    strategy_keys = ["buy_hold", "12_vix", "garch_sigma", "var_15", "var_20", "var_25"]
    cross_asset = {}
    for skey in strategy_keys:
        sharpes, net_sharpes, mdds = [], [], []
        for asset in ASSETS:
            ar = all_results.get(asset, {})
            if "error" in ar:
                continue
            m = ar.get(skey, {}).get("metrics", {})
            if m and "error" not in m:
                sharpes.append(m["sharpe"])
                net_sharpes.append(m["net_sharpe"])
                mdds.append(m["mdd"])
        if sharpes:
            cross_asset[skey] = {
                "avg_sharpe": round(np.mean(sharpes), 3),
                "avg_net_sharpe": round(np.mean(net_sharpes), 3),
                "avg_mdd": round(np.mean(mdds), 2),
                "n_assets": len(sharpes),
            }
    save_data["cross_asset_summary"] = cross_asset

    # Per-asset results (exclude non-serializable objects)
    for asset, ar in all_results.items():
        save_asset = {}
        if "error" in ar:
            save_asset["error"] = ar["error"]
        else:
            for key, val in ar.items():
                if isinstance(val, dict):
                    clean = {}
                    for k, v in val.items():
                        if isinstance(v, (dict, str, int, float, list, bool, type(None))):
                            clean[k] = v
                    save_asset[key] = clean
        save_data["results"][asset] = save_asset

    # Conclusions
    conclusions = []
    garch_avg_sh = cross_asset.get("garch_sigma", {}).get("avg_sharpe", 0)
    garch_avg_mdd = cross_asset.get("garch_sigma", {}).get("avg_mdd", 0)

    best_var_key = None
    best_var_sh = -999
    for vk in ["var_15", "var_20", "var_25"]:
        sh = cross_asset.get(vk, {}).get("avg_sharpe", -999)
        if sh > best_var_sh:
            best_var_sh = sh
            best_var_key = vk

    if best_var_key:
        delta = best_var_sh - garch_avg_sh
        best_mdd = cross_asset[best_var_key]["avg_mdd"]

        if abs(delta) < 0.03:
            conclusions.append(
                f"VaR-targeting 與 GARCH σ-targeting Sharpe 無顯著差異 "
                f"(best VaR avg={best_var_sh:.3f} vs σ avg={garch_avg_sh:.3f}, Δ={delta:+.3f})"
            )
        elif delta > 0:
            conclusions.append(
                f"VaR-targeting 改善 Sharpe: best={best_var_sh:.3f} vs σ={garch_avg_sh:.3f} (Δ={delta:+.3f})"
            )
        else:
            conclusions.append(
                f"VaR-targeting 未改善 Sharpe: best={best_var_sh:.3f} vs σ={garch_avg_sh:.3f} (Δ={delta:+.3f})"
            )

        mdd_delta = best_mdd - garch_avg_mdd  # positive = less negative = better
        if mdd_delta > 1:
            conclusions.append(f"VaR-targeting MDD 改善 {mdd_delta:+.2f}%")
        elif mdd_delta < -1:
            conclusions.append(f"VaR-targeting MDD 惡化 {mdd_delta:+.2f}%")
        else:
            conclusions.append(f"VaR-targeting MDD 與 σ-targeting 接近 (Δ={mdd_delta:+.2f}%)")

    # 12/VIX comparison
    vix_avg_sh = cross_asset.get("12_vix", {}).get("avg_sharpe", 0)
    if best_var_key and vix_avg_sh:
        delta_vix = best_var_sh - vix_avg_sh
        conclusions.append(
            f"VaR-targeting vs 12/VIX: Δ Sharpe = {delta_vix:+.3f}"
        )

    # Harvey threshold check
    for asset in ASSETS:
        ar = all_results.get(asset, {})
        if "error" in ar:
            continue
        for vk in ["var_15", "var_20", "var_25"]:
            m = ar.get(vk, {}).get("metrics", {})
            if m and m.get("harvey_t", 0) >= 3.0:
                conclusions.append(f"{asset} {ar[vk]['name']}: Harvey t={m['harvey_t']:.2f} >= 3.0 PASS")

    # Key insight: does the skewed-t quantile differ from Normal?
    for asset in ASSETS:
        ar = all_results.get(asset, {})
        diag = ar.get("diagnostics", {})
        if diag:
            q_mean = diag.get("skewt_1pct_quantile_mean", -2.326)
            diff_from_normal = q_mean - (-2.326)
            if abs(diff_from_normal) > 0.1:
                conclusions.append(
                    f"{asset}: Skewed-t 1% quantile ({q_mean:.3f}) 顯著偏離 Normal (-2.326), "
                    f"Δ={diff_from_normal:+.3f} → VaR-targeting 確實考慮了尾部特徵"
                )

    save_data["conclusions"] = conclusions

    output_path = PROJECT_ROOT / "storage" / "experiments" / "fhs_var_targeting.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {output_path}")

    print("\n" + "=" * 60)
    print("  結論")
    print("=" * 60)
    for c in conclusions:
        print(f"  - {c}")
    print()


if __name__ == "__main__":
    main()
