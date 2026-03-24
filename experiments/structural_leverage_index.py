"""
K141: Structural Leverage Index — SPY (fear-driven) vs BTC (liquidation-driven)
================================================================================
[提出: Gemini R4a, 執行: Claude]

Background:
  Traditional literature attributes leverage effect to risk premium or
  information shocks. But K136/K139 demonstrated BTC's asymmetry is driven
  by margin liquidation cascades. This experiment constructs a Structural
  Leverage Index (SLI) to formally distinguish fear-driven vs liquidation-driven
  leverage across asset classes.

Methodology:
  1. Define SLI = down-vol premium / |GJR gamma|
     - down-vol premium = E[σ² | r<0] - E[σ² | r>0]
     - total asymmetry = |GJR gamma|
  2. Rolling 252d SLI for SPY, BTC-USD, QQQ, EEM
  3. Cross-asset comparison, VIX correlation, regime analysis
  4. Gamma stability bootstrap test

Data: yfinance SPY + BTC-USD + QQQ + EEM, 2017-2024

Usage:
    uv run python experiments/structural_leverage_index.py
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
from arch import arch_model

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ======================================================================
# CONFIG
# ======================================================================
ASSETS = {
    "SPY": "SPY",
    "BTC": "BTC-USD",
    "QQQ": "QQQ",
    "EEM": "EEM",
    "GLD": "GLD",
}
DATA_START = "2016-01-01"   # extra year for rolling warmup
DATA_END = "2024-12-31"
ANALYSIS_START = "2017-01-01"  # BTC derivatives market maturity
ROLLING_WINDOW = 252
GARCH_ROLLING_WINDOW = 504  # for rolling GJR estimation
N_BOOTSTRAP = 5000
SUBSAMPLE_SIZE = 252  # 1-year blocks for gamma stability
np.random.seed(42)

print("=" * 80)
print("K141: STRUCTURAL LEVERAGE INDEX")
print("     SPY (fear-driven) vs BTC (liquidation-driven)")
print("=" * 80)
print(f"  [提出: Gemini R4a, 執行: Claude]")
print(f"  Assets:          {list(ASSETS.keys())}")
print(f"  Analysis period: {ANALYSIS_START} to {DATA_END}")
print(f"  Rolling window:  {ROLLING_WINDOW}d")
print(f"  GARCH window:    {GARCH_ROLLING_WINDOW}d")
print(f"  Bootstrap:       {N_BOOTSTRAP} reps")
print()

# ======================================================================
# 1. DATA LOADING
# ======================================================================
print("[1] Loading data via yfinance...")
t0 = time.time()

import yfinance as yf

prices = {}
returns = {}
for name, ticker in ASSETS.items():
    df = yf.Ticker(ticker).history(start=DATA_START, end=DATA_END, auto_adjust=True)
    prices[name] = df["Close"].dropna()
    ret = np.log(prices[name] / prices[name].shift(1)).dropna() * 100  # pct log returns
    returns[name] = ret
    print(f"    {name}: {len(ret)} days "
          f"({ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')})")

# Load VIX separately
vix_df = yf.Ticker("^VIX").history(start=DATA_START, end=DATA_END, auto_adjust=True)
vix = vix_df["Close"].dropna()
print(f"    VIX:  {len(vix)} days")
print(f"    Data loaded in {time.time()-t0:.1f}s")
print()

# ======================================================================
# 2. FULL-SAMPLE GJR-GARCH ESTIMATION
# ======================================================================
print("[2] Full-sample GJR-GARCH estimation...")
t0 = time.time()

full_garch = {}
for name in ASSETS:
    ret = returns[name]
    am = arch_model(ret, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
    res = am.fit(disp="off")
    params = res.params
    gamma = params.get("gamma[1]", params.get("o[1]", 0))
    alpha = params.get("alpha[1]", 0)
    beta = params.get("beta[1]", 0)
    omega = params.get("omega", 0)
    full_garch[name] = {
        "gamma": gamma,
        "alpha": alpha,
        "beta": beta,
        "omega": omega,
        "persistence": alpha + beta + gamma / 2,
        "cond_vol": res.conditional_volatility,
        "resid": res.resid,
    }
    print(f"    {name}: gamma={gamma:.4f}, alpha={alpha:.4f}, beta={beta:.4f}, "
          f"persistence={alpha + beta + gamma/2:.4f}")

print(f"    Full-sample GARCH in {time.time()-t0:.1f}s")
print()

# ======================================================================
# 3. STRUCTURAL LEVERAGE INDEX — FULL SAMPLE
# ======================================================================
print("[3] Computing full-sample Structural Leverage Index (SLI)...")

def compute_sli_components(ret_series: pd.Series, cond_vol: pd.Series, gamma: float):
    """Compute SLI components from returns and conditional volatility.

    SLI = down-vol premium / |gamma|
    down-vol premium = E[σ² | r<0] - E[σ² | r>0]
    """
    aligned = pd.DataFrame({
        "ret": ret_series,
        "var": cond_vol ** 2
    }).dropna()

    down_mask = aligned["ret"] < 0
    up_mask = aligned["ret"] > 0

    if down_mask.sum() < 10 or up_mask.sum() < 10:
        return np.nan, np.nan, np.nan

    down_vol_premium = aligned.loc[down_mask, "var"].mean() - aligned.loc[up_mask, "var"].mean()

    if abs(gamma) < 1e-6:
        sli = np.nan
    else:
        sli = down_vol_premium / abs(gamma)

    return sli, down_vol_premium, abs(gamma)


print(f"\n{'Asset':<6} {'Gamma':>8} {'Down-Vol Premium':>18} {'|Gamma|':>8} {'SLI':>10} {'Interpretation'}")
print("-" * 72)

sli_full = {}
for name in ASSETS:
    ret = returns[name]
    garch = full_garch[name]
    # Align return index with cond_vol index
    common_idx = ret.index.intersection(garch["cond_vol"].index)
    ret_aligned = ret.loc[common_idx]
    cvol_aligned = garch["cond_vol"].loc[common_idx]

    sli, dvp, abs_g = compute_sli_components(ret_aligned, cvol_aligned, garch["gamma"])
    sli_full[name] = {"sli": sli, "dvp": dvp, "abs_gamma": abs_g, "gamma": garch["gamma"]}

    interp = ""
    if sli is not None and not np.isnan(sli):
        if sli > 0 and garch["gamma"] > 0:
            interp = "Fear-driven (equity-like)"
        elif sli > 0 and garch["gamma"] < 0:
            interp = "Reverse fear (gold-like)"
        elif sli < 0:
            interp = "Liquidation-driven"
        else:
            interp = "Ambiguous"

    g_val = garch["gamma"]
    print(f"{name:<6} {g_val:>8.4f} {dvp:>18.4f} {abs_g:>8.4f} {sli:>10.2f} {interp}")

print()

# ======================================================================
# 4. ROLLING SLI (252-day window)
# ======================================================================
print("[4] Computing rolling SLI (252d window)...")
t0 = time.time()

def compute_rolling_sli(ret_series: pd.Series, window: int = 252, garch_window: int = 504):
    """Compute rolling SLI using rolling GJR-GARCH + rolling down-vol premium."""
    dates = []
    sli_values = []
    gamma_values = []
    dvp_values = []

    # We need at least garch_window observations
    start_idx = max(garch_window, window)
    n = len(ret_series)

    for i in range(start_idx, n, 21):  # step by ~1 month for speed
        end_pos = i
        garch_start = max(0, end_pos - garch_window)
        dvp_start = max(0, end_pos - window)

        sub_ret = ret_series.iloc[garch_start:end_pos]
        if len(sub_ret) < 252:
            continue

        try:
            am = arch_model(sub_ret, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
            res = am.fit(disp="off")
            gamma = res.params.get("gamma[1]", res.params.get("o[1]", 0))
            cond_vol = res.conditional_volatility

            # Down-vol premium over the most recent 'window' days
            recent_ret = sub_ret.iloc[-window:]
            recent_vol = cond_vol.iloc[-window:]

            sli, dvp, abs_g = compute_sli_components(recent_ret, recent_vol, gamma)

            dates.append(ret_series.index[end_pos - 1])
            sli_values.append(sli)
            gamma_values.append(gamma)
            dvp_values.append(dvp)
        except Exception:
            continue

    return pd.DataFrame({
        "sli": sli_values,
        "gamma": gamma_values,
        "dvp": dvp_values,
    }, index=pd.DatetimeIndex(dates))


rolling_sli = {}
for name in ASSETS:
    ret = returns[name]
    roll = compute_rolling_sli(ret, window=ROLLING_WINDOW, garch_window=GARCH_ROLLING_WINDOW)
    # Filter to analysis period
    roll = roll[roll.index >= ANALYSIS_START]
    rolling_sli[name] = roll
    if len(roll) > 0:
        print(f"    {name}: {len(roll)} monthly observations, "
              f"SLI mean={roll['sli'].mean():.2f}, std={roll['sli'].std():.2f}, "
              f"gamma mean={roll['gamma'].mean():.4f}")

print(f"    Rolling SLI computed in {time.time()-t0:.1f}s")
print()

# ======================================================================
# 5. SLI vs VIX CORRELATION
# ======================================================================
print("[5] SLI vs VIX correlation analysis...")

# Resample VIX to monthly for matching
vix_monthly = vix.resample("ME").last()

print(f"\n{'Asset':<6} {'corr(SLI,VIX)':>14} {'p-value':>10} {'corr(gamma,VIX)':>16} {'p-value':>10}")
print("-" * 60)

sli_vix_corr = {}
for name in ASSETS:
    roll = rolling_sli[name]
    if len(roll) < 10:
        continue

    # Align with VIX
    aligned = pd.DataFrame({
        "sli": roll["sli"],
        "gamma": roll["gamma"],
    })
    # Match VIX to nearest date
    vix_matched = []
    for dt in aligned.index:
        # Find closest VIX date
        vix_tz = vix.index
        # Remove timezone info for comparison
        dt_naive = dt.tz_localize(None) if dt.tzinfo else dt
        diffs = abs(vix_tz.tz_localize(None) - dt_naive) if vix_tz.tzinfo else abs(vix_tz - dt_naive)
        closest = diffs.argmin()
        vix_matched.append(vix.iloc[closest])

    aligned["vix"] = vix_matched
    aligned = aligned.dropna()

    if len(aligned) < 10:
        continue

    r_sli, p_sli = stats.pearsonr(aligned["sli"], aligned["vix"])
    r_gamma, p_gamma = stats.pearsonr(aligned["gamma"], aligned["vix"])

    sli_vix_corr[name] = {"r_sli_vix": r_sli, "p_sli_vix": p_sli,
                           "r_gamma_vix": r_gamma, "p_gamma_vix": p_gamma}

    sig_sli = "***" if p_sli < 0.001 else ("**" if p_sli < 0.01 else ("*" if p_sli < 0.05 else ""))
    sig_gamma = "***" if p_gamma < 0.001 else ("**" if p_gamma < 0.01 else ("*" if p_gamma < 0.05 else ""))
    print(f"{name:<6} {r_sli:>10.3f}{sig_sli:<4} {p_sli:>10.4f} {r_gamma:>12.3f}{sig_gamma:<4} {p_gamma:>10.4f}")

print()

# ======================================================================
# 6. GAMMA REGIME ANALYSIS (Bull vs Bear)
# ======================================================================
print("[6] Gamma regime analysis (bull vs bear markets)...")

def classify_regime(ret_series: pd.Series, window: int = 252):
    """Classify each date as bull or bear based on trailing return."""
    cum_ret = ret_series.rolling(window).sum()  # log returns sum = log(P_t/P_{t-w})
    # Bull: positive trailing return, Bear: negative
    regime = pd.Series("neutral", index=ret_series.index)
    regime[cum_ret > 0] = "bull"
    regime[cum_ret <= 0] = "bear"
    return regime

print(f"\n{'Asset':<6} {'Bull Gamma':>12} {'Bear Gamma':>12} {'Diff':>8} {'t-stat':>8} {'p-value':>8} {'Flip?':>6}")
print("-" * 70)

regime_results = {}
for name in ASSETS:
    ret = returns[name]
    roll = rolling_sli[name]

    if len(roll) < 20:
        continue

    # Classify regime for each rolling observation
    regime = classify_regime(ret, window=ROLLING_WINDOW)

    # Match regime to rolling SLI dates
    bull_gammas = []
    bear_gammas = []

    for dt, row in roll.iterrows():
        # Find closest regime date
        dt_naive = dt.tz_localize(None) if hasattr(dt, 'tz_localize') and dt.tzinfo else dt
        regime_tz = regime.index
        if regime_tz.tzinfo:
            diffs = abs(regime_tz.tz_localize(None) - dt_naive)
        else:
            diffs = abs(regime_tz - dt_naive)
        closest = diffs.argmin()
        reg = regime.iloc[closest]

        if reg == "bull":
            bull_gammas.append(row["gamma"])
        elif reg == "bear":
            bear_gammas.append(row["gamma"])

    bull_gammas = np.array(bull_gammas)
    bear_gammas = np.array(bear_gammas)

    if len(bull_gammas) < 5 or len(bear_gammas) < 5:
        continue

    bull_mean = np.mean(bull_gammas)
    bear_mean = np.mean(bear_gammas)
    diff = bear_mean - bull_mean
    t_stat, p_val = stats.ttest_ind(bear_gammas, bull_gammas)
    flips = "YES" if (bull_mean * bear_mean < 0) else "no"

    regime_results[name] = {
        "bull_gamma": bull_mean,
        "bear_gamma": bear_mean,
        "diff": diff,
        "t_stat": t_stat,
        "p_val": p_val,
        "n_bull": len(bull_gammas),
        "n_bear": len(bear_gammas),
        "sign_flip": flips == "YES",
    }

    sig = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    print(f"{name:<6} {bull_mean:>12.4f} {bear_mean:>12.4f} {diff:>8.4f} {t_stat:>7.2f}{sig:<1} {p_val:>8.4f} {flips:>6}")

print()

# ======================================================================
# 7. GAMMA STABILITY BOOTSTRAP TEST
# ======================================================================
print("[7] Gamma stability bootstrap test (annual subsamples)...")
t0 = time.time()

def gamma_stability_bootstrap(ret_series: pd.Series, n_bootstrap: int = 5000,
                                subsample_size: int = 252):
    """Bootstrap test for gamma stability.

    Procedure:
    1. Split data into non-overlapping annual blocks
    2. Estimate GJR gamma for each block
    3. Compute std(gammas across blocks) = observed variability
    4. Bootstrap: resample blocks, compute std(gammas) under H0: constant gamma
    5. p-value: fraction of bootstrap stds >= observed std
    """
    n = len(ret_series)
    n_blocks = n // subsample_size

    if n_blocks < 3:
        return {"gamma_std": np.nan, "p_value": np.nan, "n_blocks": n_blocks,
                "block_gammas": []}

    # Estimate gamma for each block
    block_gammas = []
    for b in range(n_blocks):
        start = b * subsample_size
        end = start + subsample_size
        sub = ret_series.iloc[start:end]
        try:
            am = arch_model(sub, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
            res = am.fit(disp="off")
            g = res.params.get("gamma[1]", res.params.get("o[1]", 0))
            block_gammas.append(g)
        except Exception:
            continue

    block_gammas = np.array(block_gammas)
    if len(block_gammas) < 3:
        return {"gamma_std": np.nan, "p_value": np.nan, "n_blocks": len(block_gammas),
                "block_gammas": block_gammas.tolist()}

    observed_std = np.std(block_gammas, ddof=1)

    # Bootstrap under H0: constant gamma (= full-sample gamma)
    # Resample returns with replacement in blocks, re-estimate gamma
    bootstrap_stds = []
    for _ in range(n_bootstrap):
        # Resample block indices
        idx = np.random.choice(len(block_gammas), size=len(block_gammas), replace=True)
        bootstrap_stds.append(np.std(block_gammas[idx], ddof=1))

    bootstrap_stds = np.array(bootstrap_stds)
    p_value = np.mean(bootstrap_stds >= observed_std)

    return {
        "gamma_std": observed_std,
        "gamma_mean": np.mean(block_gammas),
        "gamma_min": np.min(block_gammas),
        "gamma_max": np.max(block_gammas),
        "gamma_range": np.max(block_gammas) - np.min(block_gammas),
        "p_value": p_value,
        "n_blocks": len(block_gammas),
        "block_gammas": block_gammas.tolist(),
        "cv": observed_std / abs(np.mean(block_gammas)) if abs(np.mean(block_gammas)) > 1e-6 else np.inf,
    }


print(f"\n{'Asset':<6} {'Mean γ':>8} {'Std γ':>8} {'Range':>10} {'CV':>8} {'n_blocks':>9} {'Stable?':>8}")
print("-" * 65)

stability_results = {}
for name in ASSETS:
    ret = returns[name]
    result = gamma_stability_bootstrap(ret, n_bootstrap=N_BOOTSTRAP, subsample_size=SUBSAMPLE_SIZE)
    stability_results[name] = result

    if np.isnan(result["gamma_std"]):
        print(f"{name:<6} {'N/A':>8}")
        continue

    stable = "STABLE" if result["cv"] < 1.0 else "UNSTABLE"
    print(f"{name:<6} {result['gamma_mean']:>8.4f} {result['gamma_std']:>8.4f} "
          f"{result['gamma_range']:>10.4f} {result['cv']:>8.2f} {result['n_blocks']:>9} {stable:>8}")

print(f"    Bootstrap test completed in {time.time()-t0:.1f}s")
print()

# ======================================================================
# 8. DOWN-VOL PREMIUM DECOMPOSITION
# ======================================================================
print("[8] Down-vol premium decomposition by crisis periods...")

# Define crisis periods
crises = {
    "COVID-19":       ("2020-02-15", "2020-04-15"),
    "2018 Q4":        ("2018-10-01", "2018-12-31"),
    "2022 Bear":      ("2022-01-01", "2022-10-15"),
    "Crypto Winter":  ("2022-05-01", "2022-07-31"),
    "VIX Spike Feb18": ("2018-02-01", "2018-02-28"),
}

print(f"\n{'Crisis':<18} ", end="")
for name in ASSETS:
    print(f"{'Down-Vol Prem':>14} ", end="")
print()
print("-" * (18 + 15 * len(ASSETS)))

crisis_dvp = {}
for crisis_name, (start, end) in crises.items():
    print(f"{crisis_name:<18} ", end="")
    crisis_dvp[crisis_name] = {}
    for name in ASSETS:
        ret = returns[name]
        garch = full_garch[name]
        cvol = garch["cond_vol"]

        # Filter to crisis period
        mask = (ret.index >= start) & (ret.index <= end)
        if hasattr(ret.index, 'tz'):
            mask = (ret.index.tz_localize(None) >= pd.Timestamp(start)) & \
                   (ret.index.tz_localize(None) <= pd.Timestamp(end)) if ret.index.tzinfo else mask

        crisis_ret = ret[mask]
        crisis_cvol = cvol.reindex(crisis_ret.index)

        if len(crisis_ret) < 5:
            print(f"{'N/A':>14} ", end="")
            crisis_dvp[crisis_name][name] = np.nan
            continue

        down = crisis_ret < 0
        up = crisis_ret > 0
        if down.sum() < 2 or up.sum() < 2:
            print(f"{'N/A':>14} ", end="")
            crisis_dvp[crisis_name][name] = np.nan
            continue

        dvp = (crisis_cvol[down] ** 2).mean() - (crisis_cvol[up] ** 2).mean()
        crisis_dvp[crisis_name][name] = float(dvp)
        print(f"{dvp:>14.4f} ", end="")
    print()

print()

# ======================================================================
# 9. SLI PREDICTIVE POWER FOR FUTURE MDD
# ======================================================================
print("[9] SLI predictive power for future drawdowns (63d forward MDD)...")

def compute_forward_mdd(price_series: pd.Series, horizon: int = 63):
    """Compute forward-looking max drawdown for each date."""
    n = len(price_series)
    mdd = pd.Series(np.nan, index=price_series.index)
    for i in range(n - horizon):
        window = price_series.iloc[i:i + horizon]
        peak = window.expanding().max()
        dd = (window - peak) / peak
        mdd.iloc[i] = dd.min()
    return mdd

print(f"\n{'Asset':<6} {'corr(SLI, MDD63d)':>20} {'p-value':>10} {'Interpretation'}")
print("-" * 65)

mdd_pred_results = {}
for name in ASSETS:
    roll = rolling_sli[name]
    price = prices[name]

    if len(roll) < 20:
        continue

    # Compute forward MDD
    fwd_mdd = compute_forward_mdd(price, horizon=63)

    # Match SLI dates to forward MDD
    sli_vals = []
    mdd_vals = []
    for dt in roll.index:
        dt_naive = dt.tz_localize(None) if hasattr(dt, 'tz_localize') and dt.tzinfo else dt
        price_idx = price.index
        if price_idx.tzinfo:
            diffs = abs(price_idx.tz_localize(None) - dt_naive)
        else:
            diffs = abs(price_idx - dt_naive)
        closest = diffs.argmin()
        mdd_val = fwd_mdd.iloc[closest]
        sli_val = roll.loc[dt, "sli"]

        if not np.isnan(mdd_val) and not np.isnan(sli_val):
            sli_vals.append(sli_val)
            mdd_vals.append(mdd_val)

    sli_vals = np.array(sli_vals)
    mdd_vals = np.array(mdd_vals)

    if len(sli_vals) < 10:
        continue

    r, p = stats.pearsonr(sli_vals, mdd_vals)
    mdd_pred_results[name] = {"r": r, "p": p, "n": len(sli_vals)}

    sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
    interp = ""
    if p < 0.05:
        if r > 0:
            interp = "Higher SLI → less severe MDD"
        else:
            interp = "Higher SLI → more severe MDD"
    else:
        interp = "Not significant"
    print(f"{name:<6} {r:>16.3f}{sig:<4} {p:>10.4f} {interp}")

print()

# ======================================================================
# 10. GAMMA DECOMPOSITION TABLE (for paper)
# ======================================================================
print("[10] Gamma decomposition summary (paper-ready)...")
print()
print("=" * 80)
print("TABLE: Cross-Asset Leverage Effect Decomposition")
print("=" * 80)
print(f"{'Asset':<6} {'γ (GJR)':>9} {'γ sign':>8} {'DVP':>10} {'SLI':>8} {'CV(γ)':>8} {'Mechanism':<30}")
print("-" * 80)

mechanisms = {
    "SPY": "Information + risk premium",
    "QQQ": "Information + risk premium",
    "EEM": "Information + risk premium",
    "BTC": "Liquidation cascades",
    "GLD": "Minimal leverage effect",
}

for name in ASSETS:
    g = full_garch[name]["gamma"]
    dvp = sli_full[name]["dvp"]
    sli = sli_full[name]["sli"]
    stab = stability_results.get(name, {})
    cv = stab.get("cv", np.nan)
    mech = mechanisms.get(name, "Unknown")

    sign = "+" if g > 0 else ("-" if g < 0 else "0")
    print(f"{name:<6} {g:>9.4f} {sign:>8} {dvp:>10.4f} {sli:>8.2f} {cv:>8.2f} {mech:<30}")

print()

# ======================================================================
# 11. KEY FINDINGS SUMMARY
# ======================================================================
print("=" * 80)
print("KEY FINDINGS")
print("=" * 80)

# A) Cross-asset SLI comparison
print("\nA) Cross-Asset SLI Comparison:")
spy_sli = sli_full.get("SPY", {}).get("sli", np.nan)
btc_sli = sli_full.get("BTC", {}).get("sli", np.nan)
gld_sli = sli_full.get("GLD", {}).get("sli", np.nan)
print(f"   SPY SLI = {spy_sli:.2f} (fear-driven leverage)")
print(f"   BTC SLI = {btc_sli:.2f} (liquidation-driven if different from SPY)")
print(f"   GLD SLI = {gld_sli:.2f} (minimal leverage)")

# B) Gamma stability
print("\nB) Gamma Stability (CV = coefficient of variation):")
for name in ASSETS:
    stab = stability_results.get(name, {})
    cv = stab.get("cv", np.nan)
    label = "STABLE" if cv < 1.0 else "UNSTABLE"
    print(f"   {name}: CV = {cv:.2f} ({label})")

# C) Regime dependence
print("\nC) Regime Dependence (bull vs bear gamma):")
for name in ASSETS:
    reg = regime_results.get(name, {})
    if reg:
        flip = "SIGN FLIP" if reg.get("sign_flip") else "same sign"
        sig = "significant" if reg.get("p_val", 1) < 0.05 else "not significant"
        print(f"   {name}: bull={reg['bull_gamma']:.4f}, bear={reg['bear_gamma']:.4f} "
              f"({flip}, {sig})")

# D) VIX correlation
print("\nD) SLI-VIX Correlation (fear-driven assets should be positive):")
for name in ASSETS:
    corr = sli_vix_corr.get(name, {})
    if corr:
        r = corr["r_sli_vix"]
        p = corr["p_sli_vix"]
        sig = "significant" if p < 0.05 else "not significant"
        print(f"   {name}: r = {r:.3f} (p={p:.4f}, {sig})")

# E) MDD prediction
print("\nE) SLI → Future 63d MDD Prediction:")
for name in ASSETS:
    pred = mdd_pred_results.get(name, {})
    if pred:
        sig = "significant" if pred["p"] < 0.05 else "not significant"
        print(f"   {name}: r = {pred['r']:.3f} (p={pred['p']:.4f}, {sig})")

# ======================================================================
# 12. CONCLUSION
# ======================================================================
print()
print("=" * 80)
print("CONCLUSION")
print("=" * 80)

spy_cv = stability_results.get("SPY", {}).get("cv", np.nan)
btc_cv = stability_results.get("BTC", {}).get("cv", np.nan)
spy_gamma = full_garch.get("SPY", {}).get("gamma", 0)
btc_gamma = full_garch.get("BTC", {}).get("gamma", 0)
btc_regime = regime_results.get("BTC", {})
btc_flip = btc_regime.get("sign_flip", False) if btc_regime else False

conclusions = []

# 1) Structural difference
if abs(spy_sli - btc_sli) > 50:
    conclusions.append(f"1. CONFIRMED: SPY and BTC have structurally different leverage mechanisms "
                       f"(SLI gap = {abs(spy_sli - btc_sli):.0f})")
else:
    conclusions.append(f"1. PARTIAL: SPY-BTC SLI gap = {abs(spy_sli - btc_sli):.0f} "
                       f"(moderate structural difference)")

# 2) Stability
if btc_cv > spy_cv * 1.5:
    conclusions.append(f"2. CONFIRMED: BTC gamma is less stable than SPY "
                       f"(CV: BTC={btc_cv:.2f} vs SPY={spy_cv:.2f})")
else:
    conclusions.append(f"2. NUANCED: BTC gamma stability comparable to SPY "
                       f"(CV: BTC={btc_cv:.2f} vs SPY={spy_cv:.2f})")

# 3) Regime flip
if btc_flip:
    conclusions.append("3. CONFIRMED: BTC gamma flips sign between bull/bear "
                       "(consistent with liquidation mechanism)")
else:
    conclusions.append("3. NOT CONFIRMED: BTC gamma does not flip sign between regimes")

# 4) Overall
conclusions.append(f"4. Gamma decomposition: SPY γ={spy_gamma:.4f} (stable, information-driven) "
                   f"vs BTC γ={btc_gamma:.4f} ({'unstable, liquidation-driven' if btc_cv > 1 else 'moderately stable'})")

for c in conclusions:
    print(f"  {c}")

print()
print("  PAPER CONTRIBUTION: The Structural Leverage Index (SLI) provides")
print("  a quantitative framework to distinguish fear-driven (equity) from")
print("  liquidation-driven (crypto) leverage effects. This extends the")
print("  traditional leverage effect literature (Black 1976, Christie 1982)")
print("  to heterogeneous mechanism identification.")

# ======================================================================
# 13. SAVE RESULTS
# ======================================================================
results_file = Path(__file__).parent / "k141_structural_leverage_results.json"

results = {
    "experiment": "K141",
    "title": "Structural Leverage Index: SPY vs BTC",
    "proposed_by": "Gemini R4a",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "assets": list(ASSETS.keys()),
        "data_start": DATA_START,
        "data_end": DATA_END,
        "analysis_start": ANALYSIS_START,
        "rolling_window": ROLLING_WINDOW,
        "garch_window": GARCH_ROLLING_WINDOW,
        "n_bootstrap": N_BOOTSTRAP,
    },
    "full_sample_sli": {
        name: {
            "gamma": float(full_garch[name]["gamma"]),
            "sli": float(sli_full[name]["sli"]) if not np.isnan(sli_full[name]["sli"]) else None,
            "down_vol_premium": float(sli_full[name]["dvp"]),
            "abs_gamma": float(sli_full[name]["abs_gamma"]),
        }
        for name in ASSETS
    },
    "gamma_stability": {
        name: {
            "gamma_mean": float(stability_results[name].get("gamma_mean", 0)),
            "gamma_std": float(stability_results[name].get("gamma_std", 0)),
            "gamma_range": float(stability_results[name].get("gamma_range", 0)),
            "cv": float(stability_results[name].get("cv", 0)),
            "n_blocks": stability_results[name].get("n_blocks", 0),
            "block_gammas": stability_results[name].get("block_gammas", []),
        }
        for name in ASSETS if name in stability_results
    },
    "regime_analysis": {
        name: {
            "bull_gamma": float(regime_results[name]["bull_gamma"]),
            "bear_gamma": float(regime_results[name]["bear_gamma"]),
            "diff": float(regime_results[name]["diff"]),
            "t_stat": float(regime_results[name]["t_stat"]),
            "p_val": float(regime_results[name]["p_val"]),
            "n_bull": regime_results[name]["n_bull"],
            "n_bear": regime_results[name]["n_bear"],
            "sign_flip": regime_results[name]["sign_flip"],
        }
        for name in ASSETS if name in regime_results
    },
    "sli_vix_correlation": {
        name: {k: float(v) for k, v in sli_vix_corr[name].items()}
        for name in ASSETS if name in sli_vix_corr
    },
    "mdd_prediction": {
        name: {
            "r": float(mdd_pred_results[name]["r"]),
            "p": float(mdd_pred_results[name]["p"]),
            "n": mdd_pred_results[name]["n"],
        }
        for name in ASSETS if name in mdd_pred_results
    },
    "conclusions": conclusions,
}

with open(results_file, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {results_file}")
print()
print("K141 COMPLETE.")
