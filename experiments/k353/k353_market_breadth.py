"""
K353: Market Breadth as Volatility Signal
==========================================
Does Internal Market Health Predict Vol?
(跳躍式探索 — ZERO prior mentions of breadth/advance-decline in 1193 knowledge entries)

Core hypothesis: Market breadth deterioration (narrow rally = few stocks
driving index) creates fragile conditions → future vol spikes BEFORE VIX
reacts. If SPY (cap-weighted) massively outperforms RSP (equal-weight),
it means only mega-caps are holding the index up.

Breadth proxies (all from yfinance, real data only):
1. SPY/RSP ratio (cap-weighted vs equal-weight divergence)
2. SPY-IWM return spread (large vs small cap)
3. SPY/RSP 22d rolling return difference

Tests:
- Correlation: breadth_t vs RV_{t+1:t+22}
- Partial correlation: breadth|VIX vs future RV
- Breadth regime analysis: broad vs narrow rally → vol outcomes
- Breadth-based vol timing strategy: reduce equity when breadth narrows
- 5-period cross-OOS validation

Data: yfinance — SPY, RSP, IWM, ^VIX
Period: 2003-2026 (RSP inception April 2003)

Related prior work:
- K164-K165: Dispersion absorbed by VIX
- K335: ESG vol spread was artifact
- K348: Credit spread partial r=0.10 (tiny)

Author: VolPred Research System (K353)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2003-04-01"  # RSP inception
RV_HORIZON = 22            # 22-day forward realized vol
ROLLING_WINDOW = 22        # rolling window for breadth measures
N_BOOTSTRAP = 5000
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
TARGET_VOL = 0.12
HARVEY_THRESHOLD = 3.0

# Cross-OOS periods (5 periods)
OOS_PERIODS = [
    ("2008-01-01", "2009-12-31"),  # GFC
    ("2011-01-01", "2013-12-31"),  # Recovery + Euro crisis
    ("2015-01-01", "2017-12-31"),  # Low vol era
    ("2018-01-01", "2020-12-31"),  # Volmageddon + COVID
    ("2021-01-01", "2025-12-31"),  # Post-COVID + rate hikes
]

np.random.seed(42)

print("=" * 75)
print("K353: MARKET BREADTH AS VOLATILITY SIGNAL")
print("=" * 75)
print(f"  Data start: {DATA_START} (RSP inception)")
print(f"  RV horizon: {RV_HORIZON}d")
print(f"  Rolling window: {ROLLING_WINDOW}d")
print(f"  Cross-OOS periods: {len(OOS_PERIODS)}")
print(f"  Bootstrap: {N_BOOTSTRAP}")
print()


# ==================================================================
# DATA DOWNLOAD
# ==================================================================
print("=" * 75)
print("SECTION 1: DATA DOWNLOAD")
print("=" * 75)

tickers = {
    "SPY": "SPY",
    "RSP": "RSP",
    "IWM": "IWM",
    "VIX": "^VIX",
}

prices = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2026-03-25",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prices[name] = df["Close"].copy()
    print(f"  {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align all on common dates
price_df = pd.DataFrame(prices)
price_df = price_df.dropna()
print(f"\n  Aligned: {len(price_df)} common trading days")
print(f"  Period: {price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}")


# ==================================================================
# SECTION 2: CONSTRUCT BREADTH PROXIES
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 2: BREADTH PROXY CONSTRUCTION")
print("=" * 75)

# Returns
ret_df = price_df.pct_change().dropna()

# Proxy 1: SPY/RSP price ratio (log)
# Rising ratio = SPY outperforming RSP = narrow rally
price_df["SPY_RSP_ratio"] = np.log(price_df["SPY"] / price_df["RSP"])

# Proxy 2: SPY-IWM return spread (rolling 22d)
ret_df["SPY_IWM_spread"] = ret_df["SPY"].rolling(ROLLING_WINDOW).mean() - ret_df["IWM"].rolling(ROLLING_WINDOW).mean()

# Proxy 3: SPY-RSP rolling return difference (22d)
ret_df["SPY_RSP_ret_diff"] = ret_df["SPY"].rolling(ROLLING_WINDOW).mean() - ret_df["RSP"].rolling(ROLLING_WINDOW).mean()

# Proxy 4: Change in SPY/RSP ratio (momentum of concentration)
price_df["SPY_RSP_ratio_chg"] = price_df["SPY_RSP_ratio"].diff(ROLLING_WINDOW)

# Proxy 5: Relative strength = SPY 22d return / RSP 22d return
ret_df["SPY_RSP_rel_strength"] = (ret_df["SPY"].rolling(ROLLING_WINDOW).sum()) / (ret_df["RSP"].rolling(ROLLING_WINDOW).sum().replace(0, np.nan))

# Future 22d realized vol (annualized)
ret_df["RV_22d_fwd"] = ret_df["SPY"].rolling(RV_HORIZON).std().shift(-RV_HORIZON) * np.sqrt(252)

# Current VIX (for partial correlation)
ret_df["VIX"] = price_df["VIX"].reindex(ret_df.index) / 100  # Convert to decimal

# Merge ratio-based proxies
ret_df["SPY_RSP_ratio"] = price_df["SPY_RSP_ratio"].reindex(ret_df.index)
ret_df["SPY_RSP_ratio_chg"] = price_df["SPY_RSP_ratio_chg"].reindex(ret_df.index)

# Drop NaN
analysis_df = ret_df.dropna(subset=["RV_22d_fwd", "SPY_IWM_spread", "SPY_RSP_ret_diff",
                                      "SPY_RSP_ratio", "SPY_RSP_ratio_chg", "VIX"])
print(f"\n  Analysis sample: {len(analysis_df)} obs")
print(f"  Period: {analysis_df.index[0].strftime('%Y-%m-%d')} to {analysis_df.index[-1].strftime('%Y-%m-%d')}")

# Summary stats for proxies
proxy_cols = ["SPY_RSP_ratio", "SPY_RSP_ratio_chg", "SPY_IWM_spread",
              "SPY_RSP_ret_diff", "SPY_RSP_rel_strength"]
print("\n  Breadth Proxy Summary Statistics:")
print(f"  {'Proxy':<25} {'Mean':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
print("  " + "-" * 65)
for col in proxy_cols:
    if col in analysis_df.columns:
        s = analysis_df[col].dropna()
        print(f"  {col:<25} {s.mean():>10.6f} {s.std():>10.6f} {s.min():>10.6f} {s.max():>10.6f}")


# ==================================================================
# SECTION 3: RAW CORRELATIONS
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 3: RAW CORRELATIONS — Breadth vs Future 22d RV")
print("=" * 75)

print(f"\n  {'Proxy':<25} {'Corr':>8} {'p-value':>10} {'t-stat':>8} {'N':>6}")
print("  " + "-" * 60)

raw_corr_results = {}
for col in proxy_cols:
    if col not in analysis_df.columns:
        continue
    valid = analysis_df[[col, "RV_22d_fwd"]].dropna()
    r, p = stats.pearsonr(valid[col], valid["RV_22d_fwd"])
    n = len(valid)
    t = r * np.sqrt(n - 2) / np.sqrt(1 - r**2)
    raw_corr_results[col] = {"r": r, "p": p, "t": t, "n": n}
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"  {col:<25} {r:>8.4f} {p:>10.4e} {t:>8.2f} {n:>6d} {sig}")

print("\n  Interpretation:")
print("  - Positive corr for SPY_RSP_ratio: narrow rally → higher future vol ✓")
print("  - Negative corr for SPY_RSP_ratio: broad rally → higher future vol (unexpected)")


# ==================================================================
# SECTION 4: PARTIAL CORRELATIONS (controlling for VIX)
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 4: PARTIAL CORRELATIONS — Breadth|VIX vs Future RV")
print("=" * 75)
print("  (This is the KEY test: does breadth add info BEYOND VIX?)")

def partial_correlation(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Residualize x on z
    valid = pd.DataFrame({"x": x, "y": y, "z": z}).dropna()
    n = len(valid)
    if n < 10:
        return np.nan, np.nan, n

    slope_xz = np.polyfit(valid["z"], valid["x"], 1)
    resid_x = valid["x"] - np.polyval(slope_xz, valid["z"])

    slope_yz = np.polyfit(valid["z"], valid["y"], 1)
    resid_y = valid["y"] - np.polyval(slope_yz, valid["z"])

    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p, n

print(f"\n  {'Proxy':<25} {'Raw r':>8} {'Partial r':>10} {'p-value':>10} {'VIX absorbed':>14}")
print("  " + "-" * 70)

partial_results = {}
for col in proxy_cols:
    if col not in analysis_df.columns:
        continue
    valid = analysis_df[[col, "RV_22d_fwd", "VIX"]].dropna()
    raw_r = raw_corr_results.get(col, {}).get("r", np.nan)
    pr, pp, pn = partial_correlation(valid[col], valid["RV_22d_fwd"], valid["VIX"])
    partial_results[col] = {"raw_r": raw_r, "partial_r": pr, "p": pp, "n": pn}
    absorbed = (1 - abs(pr) / max(abs(raw_r), 1e-10)) * 100 if abs(raw_r) > 1e-10 else 0
    sig = "***" if pp < 0.001 else "**" if pp < 0.01 else "*" if pp < 0.05 else ""
    print(f"  {col:<25} {raw_r:>8.4f} {pr:>10.4f} {pp:>10.4e} {absorbed:>12.1f}% {sig}")

print("\n  Key question: Is partial r > 0.05 for any proxy?")
max_partial = max(partial_results.values(), key=lambda x: abs(x["partial_r"]))
best_proxy = [k for k, v in partial_results.items() if v == max_partial][0]
print(f"  Best proxy: {best_proxy} (partial r = {max_partial['partial_r']:.4f})")


# ==================================================================
# SECTION 5: BREADTH REGIME ANALYSIS
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 5: BREADTH REGIME ANALYSIS")
print("=" * 75)

# Define regimes based on SPY_RSP_ret_diff
# Broad rally: RSP outperforms SPY (equal-weight beats cap-weight)
# Narrow rally: SPY outperforms RSP (cap-weight beats equal-weight)
valid_regime = analysis_df[["SPY_RSP_ret_diff", "RV_22d_fwd", "SPY", "VIX"]].dropna()

# Tercile split
q33 = valid_regime["SPY_RSP_ret_diff"].quantile(0.33)
q67 = valid_regime["SPY_RSP_ret_diff"].quantile(0.67)

regime_broad = valid_regime[valid_regime["SPY_RSP_ret_diff"] < q33]  # RSP winning = broad
regime_mid = valid_regime[(valid_regime["SPY_RSP_ret_diff"] >= q33) & (valid_regime["SPY_RSP_ret_diff"] <= q67)]
regime_narrow = valid_regime[valid_regime["SPY_RSP_ret_diff"] > q67]  # SPY winning = narrow

print(f"\n  Tercile split on SPY-RSP 22d return diff:")
print(f"  Broad  (RSP winning): N={len(regime_broad)}, threshold < {q33:.6f}")
print(f"  Mid:                  N={len(regime_mid)}")
print(f"  Narrow (SPY winning): N={len(regime_narrow)}, threshold > {q67:.6f}")

print(f"\n  {'Regime':<12} {'Mean RV':>10} {'Median RV':>10} {'Std RV':>10} {'Mean VIX':>10}")
print("  " + "-" * 55)
for name, df in [("Broad", regime_broad), ("Mid", regime_mid), ("Narrow", regime_narrow)]:
    print(f"  {name:<12} {df['RV_22d_fwd'].mean():>10.4f} {df['RV_22d_fwd'].median():>10.4f} "
          f"{df['RV_22d_fwd'].std():>10.4f} {df['VIX'].mean():>10.4f}")

# t-test: narrow vs broad
t_nb, p_nb = stats.ttest_ind(regime_narrow["RV_22d_fwd"], regime_broad["RV_22d_fwd"])
print(f"\n  Narrow vs Broad RV difference:")
print(f"    t-stat = {t_nb:.3f}, p = {p_nb:.4e}")
print(f"    Mean diff = {regime_narrow['RV_22d_fwd'].mean() - regime_broad['RV_22d_fwd'].mean():.4f}")

# But is this just because VIX is already higher in narrow regimes?
t_vix, p_vix = stats.ttest_ind(regime_narrow["VIX"], regime_broad["VIX"])
print(f"\n  Narrow vs Broad VIX difference:")
print(f"    t-stat = {t_vix:.3f}, p = {p_vix:.4e}")
print(f"    Mean diff = {regime_narrow['VIX'].mean() - regime_broad['VIX'].mean():.4f}")


# ==================================================================
# SECTION 6: GRANGER-STYLE PREDICTIVE REGRESSION
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 6: PREDICTIVE REGRESSION — Breadth → Future RV")
print("=" * 75)
print("  RV_{t+1:t+22} = a + b1*VIX_t + b2*Breadth_t + e")

from numpy.linalg import lstsq

valid_reg = analysis_df[["RV_22d_fwd", "VIX", "SPY_RSP_ret_diff",
                          "SPY_IWM_spread", "SPY_RSP_ratio_chg"]].dropna()

y = valid_reg["RV_22d_fwd"].values

# Model 1: VIX only
X1 = np.column_stack([np.ones(len(y)), valid_reg["VIX"].values])
beta1, res1, _, _ = lstsq(X1, y, rcond=None)
ss_res1 = np.sum((y - X1 @ beta1) ** 2)
ss_tot = np.sum((y - y.mean()) ** 2)
r2_vix = 1 - ss_res1 / ss_tot

print(f"\n  Model 1 (VIX only): R² = {r2_vix:.4f}")
print(f"    β_VIX = {beta1[1]:.4f}")

# Model 2: VIX + each breadth proxy
for proxy_name in ["SPY_RSP_ret_diff", "SPY_IWM_spread", "SPY_RSP_ratio_chg"]:
    X2 = np.column_stack([np.ones(len(y)), valid_reg["VIX"].values, valid_reg[proxy_name].values])
    beta2, res2, _, _ = lstsq(X2, y, rcond=None)
    ss_res2 = np.sum((y - X2 @ beta2) ** 2)
    r2_both = 1 - ss_res2 / ss_tot

    # Incremental R²
    delta_r2 = r2_both - r2_vix

    # F-test for incremental explanatory power
    n = len(y)
    k1, k2 = 2, 3  # parameters in restricted vs unrestricted
    f_stat = ((ss_res1 - ss_res2) / (k2 - k1)) / (ss_res2 / (n - k2))
    f_p = 1 - stats.f.cdf(f_stat, k2 - k1, n - k2)

    # HAC standard errors for β_breadth (Newey-West approximation)
    resid = y - X2 @ beta2
    # Simple Newey-West with 22 lags
    nw_lags = 22
    X2_demean = X2 - X2.mean(axis=0)
    meat = np.zeros((3, 3))
    for lag in range(nw_lags + 1):
        weight = 1 - lag / (nw_lags + 1) if lag > 0 else 1
        for t in range(lag, n):
            outer = np.outer(X2[t] * resid[t], X2[t - lag] * resid[t - lag])
            meat += weight * (outer + outer.T) if lag > 0 else weight * outer
    bread = np.linalg.inv(X2.T @ X2)
    vcov = n * bread @ meat @ bread
    se_breadth = np.sqrt(vcov[2, 2])
    t_breadth = beta2[2] / se_breadth

    sig = "***" if abs(t_breadth) > 3.0 else "**" if abs(t_breadth) > 2.58 else "*" if abs(t_breadth) > 1.96 else ""
    print(f"\n  Model 2 (VIX + {proxy_name}):")
    print(f"    R² = {r2_both:.4f} (ΔR² = {delta_r2:.6f})")
    print(f"    β_breadth = {beta2[2]:.6f} (HAC t = {t_breadth:.3f}) {sig}")
    print(f"    F-test for breadth: F = {f_stat:.3f}, p = {f_p:.4e}")


# ==================================================================
# SECTION 7: BREADTH VOL-TIMING STRATEGY
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 7: BREADTH VOL-TIMING STRATEGY")
print("=" * 75)
print("  Strategy: Reduce equity when breadth narrows (SPY > RSP)")

# Full sample strategy test first
strat_df = ret_df[["SPY", "SPY_RSP_ret_diff", "VIX"]].dropna().copy()

# Breadth signal: z-score of SPY_RSP_ret_diff (expanding)
strat_df["breadth_zscore"] = (
    (strat_df["SPY_RSP_ret_diff"] - strat_df["SPY_RSP_ret_diff"].expanding(min_periods=252).mean()) /
    strat_df["SPY_RSP_ret_diff"].expanding(min_periods=252).std()
)

# Strategy weights (lagged by 1 day to avoid look-ahead)
# Narrow (z > 1): reduce to 50% equity
# Normal (-1 < z < 1): 100% equity
# Broad (z < -1): 100% equity
strat_df["breadth_weight"] = 1.0
strat_df.loc[strat_df["breadth_zscore"] > 1.0, "breadth_weight"] = 0.5
strat_df.loc[strat_df["breadth_zscore"] > 2.0, "breadth_weight"] = 0.25
strat_df["breadth_weight"] = strat_df["breadth_weight"].shift(1)  # LAG!

# 12/VIX benchmark (lagged)
strat_df["vix_weight"] = (TARGET_VOL / (strat_df["VIX"])).clip(0, 1.5)
strat_df["vix_weight"] = strat_df["vix_weight"].shift(1)

# Combined: breadth overlay on 12/VIX
strat_df["combined_weight"] = strat_df["vix_weight"] * strat_df["breadth_weight"]

# Returns
strat_df["ret_buyhold"] = strat_df["SPY"]
strat_df["ret_vix_vt"] = strat_df["SPY"] * strat_df["vix_weight"]
strat_df["ret_breadth_only"] = strat_df["SPY"] * strat_df["breadth_weight"]
strat_df["ret_combined"] = strat_df["SPY"] * strat_df["combined_weight"]

strat_df = strat_df.dropna()

print(f"\n  Strategy sample: {len(strat_df)} days")
print(f"  Period: {strat_df.index[0].strftime('%Y-%m-%d')} to {strat_df.index[-1].strftime('%Y-%m-%d')}")


def calc_metrics(returns, name):
    """Calculate strategy metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    mdd = dd.min()

    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Turnover (for strategies with weights)
    weight_col = name.replace("ret_", "") + "_weight" if name != "ret_buyhold" else None

    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
    }


print(f"\n  {'Strategy':<20} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8}")
print("  " + "-" * 62)

strategies = ["ret_buyhold", "ret_vix_vt", "ret_breadth_only", "ret_combined"]
strat_metrics = {}
for s in strategies:
    m = calc_metrics(strat_df[s], s)
    strat_metrics[s] = m
    print(f"  {s:<20} {m['ann_ret']:>8.4f} {m['ann_vol']:>8.4f} {m['sharpe']:>8.4f} "
          f"{m['mdd']:>8.4f} {m['calmar']:>8.4f}")

# DM test: combined vs VIX-only
e_vix = strat_df["ret_vix_vt"]
e_comb = strat_df["ret_combined"]
# Use squared returns as loss (lower vol = better)
d = e_vix ** 2 - e_comb ** 2  # Positive if combined has lower squared returns (but this isn't quite right)
# Better: compare Sharpe directly
sharpe_vix = strat_metrics["ret_vix_vt"]["sharpe"]
sharpe_combined = strat_metrics["ret_combined"]["sharpe"]
sharpe_diff = sharpe_combined - sharpe_vix
n_years = len(strat_df) / 252
se_sharpe_diff = np.sqrt(2 / n_years)  # Approximate SE of Sharpe difference
t_sharpe = sharpe_diff / se_sharpe_diff
print(f"\n  Sharpe difference (Combined vs VIX-only): {sharpe_diff:.4f}")
print(f"  t-stat: {t_sharpe:.3f} (SE ≈ {se_sharpe_diff:.4f})")
print(f"  {'SIGNIFICANT' if abs(t_sharpe) > 1.96 else 'NOT significant'} at 5%")


# ==================================================================
# SECTION 8: 5-PERIOD CROSS-OOS VALIDATION
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 8: 5-PERIOD CROSS-OOS VALIDATION")
print("=" * 75)

oos_results = []
print(f"\n  {'Period':<22} {'VIX Sharpe':>10} {'Combined':>10} {'Breadth+':>10} {'N':>5}")
print("  " + "-" * 60)

for oos_start, oos_end in OOS_PERIODS:
    oos_mask = (strat_df.index >= oos_start) & (strat_df.index <= oos_end)
    oos_data = strat_df[oos_mask]

    if len(oos_data) < 50:
        continue

    m_vix = calc_metrics(oos_data["ret_vix_vt"], "vix")
    m_comb = calc_metrics(oos_data["ret_combined"], "combined")
    m_bonly = calc_metrics(oos_data["ret_breadth_only"], "breadth")

    breadth_wins = "✓" if m_comb["sharpe"] > m_vix["sharpe"] else "✗"

    oos_results.append({
        "period": f"{oos_start}–{oos_end}",
        "vix_sharpe": m_vix["sharpe"],
        "combined_sharpe": m_comb["sharpe"],
        "breadth_wins": m_comb["sharpe"] > m_vix["sharpe"],
        "n": len(oos_data),
    })

    print(f"  {oos_start}–{oos_end}  {m_vix['sharpe']:>10.4f} {m_comb['sharpe']:>10.4f} "
          f"{breadth_wins:>10} {len(oos_data):>5}")

n_wins = sum(r["breadth_wins"] for r in oos_results)
print(f"\n  Breadth overlay wins: {n_wins}/{len(oos_results)} OOS periods")
print(f"  {'PASSES' if n_wins >= 4 else 'FAILS'} 4/5 consistency threshold")


# ==================================================================
# SECTION 9: BOOTSTRAP SIGNIFICANCE TEST
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 9: BOOTSTRAP — Is breadth overlay Sharpe improvement significant?")
print("=" * 75)

observed_diff = strat_metrics["ret_combined"]["sharpe"] - strat_metrics["ret_vix_vt"]["sharpe"]

boot_diffs = []
combined_rets = strat_df["ret_combined"].values
vix_rets = strat_df["ret_vix_vt"].values
n_obs = len(combined_rets)

for _ in range(N_BOOTSTRAP):
    idx = np.random.choice(n_obs, n_obs, replace=True)
    boot_comb = combined_rets[idx]
    boot_vix = vix_rets[idx]

    s_comb = (boot_comb.mean() * 252 - RF_ANNUAL) / (boot_comb.std() * np.sqrt(252))
    s_vix = (boot_vix.mean() * 252 - RF_ANNUAL) / (boot_vix.std() * np.sqrt(252))
    boot_diffs.append(s_comb - s_vix)

boot_diffs = np.array(boot_diffs)
p_boot = np.mean(boot_diffs < 0)  # If combined is supposed to be better
ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])

print(f"\n  Observed Sharpe diff (Combined - VIX): {observed_diff:.4f}")
print(f"  Bootstrap mean diff: {boot_diffs.mean():.4f}")
print(f"  Bootstrap 95% CI: [{ci_lo:.4f}, {ci_hi:.4f}]")
print(f"  p-value (diff < 0): {p_boot:.4f}")
print(f"  CI includes zero: {'YES' if ci_lo < 0 < ci_hi else 'NO'}")


# ==================================================================
# SECTION 10: CRISIS-SPECIFIC ANALYSIS
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 10: CRISIS-SPECIFIC — Did breadth narrow BEFORE crises?")
print("=" * 75)

crises = {
    "GFC": ("2007-07-01", "2008-09-15"),       # Before Lehman
    "Flash Crash": ("2010-04-01", "2010-05-06"),
    "COVID": ("2019-12-01", "2020-02-19"),
    "2022 Bear": ("2021-11-01", "2022-01-03"),
    "2024 Unwind": ("2024-06-01", "2024-07-31"),
}

print(f"\n  {'Crisis':<15} {'Pre-crisis breadth':>18} {'Breadth z':>10} {'Signal?':>8}")
print("  " + "-" * 55)

for crisis_name, (pre_start, pre_end) in crises.items():
    mask = (strat_df.index >= pre_start) & (strat_df.index <= pre_end)
    pre_data = strat_df[mask]

    if len(pre_data) < 5:
        print(f"  {crisis_name:<15} {'(insufficient data)':>18}")
        continue

    avg_breadth = pre_data["SPY_RSP_ret_diff"].mean()
    avg_z = pre_data["breadth_zscore"].mean()
    narrowing = "NARROW" if avg_z > 0.5 else "BROAD" if avg_z < -0.5 else "NEUTRAL"

    print(f"  {crisis_name:<15} {avg_breadth:>18.6f} {avg_z:>10.3f} {narrowing:>8}")


# ==================================================================
# SECTION 11: LEAD-LAG — Does breadth LEAD VIX?
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 11: LEAD-LAG — Does breadth change LEAD VIX change?")
print("=" * 75)

# Cross-correlation at different lags
lags = list(range(-10, 11))
valid_ll = analysis_df[["SPY_RSP_ret_diff", "VIX"]].dropna()
vix_chg = valid_ll["VIX"].diff()
breadth_val = valid_ll["SPY_RSP_ret_diff"]

print(f"\n  {'Lag (days)':>10} {'Corr(breadth_t, ΔVIXt+lag)':>28} {'p-value':>10}")
print("  " + "-" * 50)

max_corr = 0
max_lag = 0
for lag in lags:
    if lag >= 0:
        x = breadth_val.iloc[:len(breadth_val) - lag if lag > 0 else len(breadth_val)]
        y_shifted = vix_chg.shift(-lag).iloc[:len(breadth_val) - lag if lag > 0 else len(breadth_val)]
    else:
        x = breadth_val.iloc[-lag:]
        y_shifted = vix_chg.iloc[-lag:].shift(-lag)
        # Simpler approach
        x = breadth_val.iloc[abs(lag):]
        y_shifted = vix_chg.iloc[:len(vix_chg) - abs(lag)]

    valid_mask = ~(x.isna() | y_shifted.isna())
    if valid_mask.sum() < 50:
        continue

    r, p = stats.pearsonr(x[valid_mask].values, y_shifted[valid_mask].values)
    if lag in [-5, -2, -1, 0, 1, 2, 5]:
        print(f"  {lag:>10} {r:>28.4f} {p:>10.4e}")
    if abs(r) > abs(max_corr):
        max_corr = r
        max_lag = lag

print(f"\n  Max |corr| = {max_corr:.4f} at lag {max_lag}")
print(f"  {'Breadth LEADS VIX' if max_lag > 0 else 'VIX LEADS breadth' if max_lag < 0 else 'Contemporaneous'}")


# ==================================================================
# SECTION 12: ROBUSTNESS — Different windows
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 12: ROBUSTNESS — Different rolling windows")
print("=" * 75)

windows = [5, 10, 22, 44, 66]
print(f"\n  {'Window':>8} {'Raw r':>8} {'Partial r':>10} {'p (partial)':>12}")
print("  " + "-" * 42)

for w in windows:
    breadth_w = ret_df["SPY"].rolling(w).mean() - ret_df["RSP"].rolling(w).mean()
    rv_fwd = ret_df["SPY"].rolling(RV_HORIZON).std().shift(-RV_HORIZON) * np.sqrt(252)
    vix_vals = price_df["VIX"].reindex(ret_df.index) / 100

    valid_w = pd.DataFrame({"breadth": breadth_w, "rv": rv_fwd, "vix": vix_vals}).dropna()
    if len(valid_w) < 100:
        continue

    r_raw, p_raw = stats.pearsonr(valid_w["breadth"], valid_w["rv"])
    pr, pp, pn = partial_correlation(valid_w["breadth"], valid_w["rv"], valid_w["vix"])

    print(f"  {w:>8} {r_raw:>8.4f} {pr:>10.4f} {pp:>12.4e}")


# ==================================================================
# SECTION 13: COMPREHENSIVE RESULTS SUMMARY
# ==================================================================
print("\n" + "=" * 75)
print("SECTION 13: COMPREHENSIVE RESULTS SUMMARY")
print("=" * 75)

# Collect key findings
best_proxy_name = best_proxy
best_partial_r = max_partial["partial_r"]
best_partial_p = max_partial["p"]

print(f"""
K353 RESULTS — Market Breadth as Volatility Signal
===================================================

1. RAW CORRELATIONS:
   Best proxy: {best_proxy_name}
   Raw r with future 22d RV: {raw_corr_results[best_proxy_name]['r']:.4f}
   t-stat: {raw_corr_results[best_proxy_name]['t']:.2f}

2. PARTIAL CORRELATIONS (controlling for VIX):
   Best partial r: {best_partial_r:.4f} (p = {best_partial_p:.4e})
   Verdict: {'INFORMATIVE beyond VIX' if abs(best_partial_r) > 0.05 and best_partial_p < 0.05 else 'ABSORBED by VIX'}

3. REGIME ANALYSIS:
   Narrow vs Broad RV diff: t = {t_nb:.3f}, p = {p_nb:.4e}
   VIX also differs: t = {t_vix:.3f}, p = {p_vix:.4e}

4. VOL-TIMING STRATEGY:
   Buy & Hold Sharpe: {strat_metrics['ret_buyhold']['sharpe']:.4f}
   12/VIX Sharpe: {strat_metrics['ret_vix_vt']['sharpe']:.4f}
   Combined Sharpe: {strat_metrics['ret_combined']['sharpe']:.4f}
   Difference: {observed_diff:.4f}
   Bootstrap p: {p_boot:.4f}
   CI: [{ci_lo:.4f}, {ci_hi:.4f}]

5. CROSS-OOS:
   Breadth overlay wins: {n_wins}/{len(oos_results)} periods
   {'CONSISTENT' if n_wins >= 4 else 'INCONSISTENT'}

6. LEAD-LAG:
   Max corr at lag {max_lag} → {'Breadth leads VIX' if max_lag > 0 else 'No lead'}

OVERALL VERDICT:
""")

# Final assessment
if abs(best_partial_r) < 0.05 or best_partial_p > 0.05:
    print("  ★ ABSORBED BY VIX — Breadth does NOT add predictive info beyond VIX")
    print("    This is consistent with K164-K165 (dispersion) and the VIX sufficient")
    print("    statistic finding (confirmed 21 times across K, J, G, T series).")
    verdict = "null"
elif abs(best_partial_r) < 0.10:
    print("  ★ TINY INCREMENTAL INFO — partial r < 0.10, economically negligible")
    print("    Similar to K348 credit spread (partial r = 0.10)")
    verdict = "tiny"
else:
    print("  ★ POTENTIAL SIGNAL — partial r > 0.10, warrants further investigation")
    verdict = "signal"

if abs(observed_diff) < 0.05 or p_boot > 0.05:
    print("  ★ NO ECONOMIC VALUE — Breadth overlay does not improve VT Sharpe")
    econ_verdict = "null"
else:
    print("  ★ POSSIBLE ECONOMIC VALUE — but check cross-OOS consistency")
    econ_verdict = "possible"


# ==================================================================
# SAVE RESULTS
# ==================================================================
results = {
    "experiment": "K353",
    "title": "Market Breadth as Volatility Signal",
    "data_source": "yfinance (SPY, RSP, IWM, ^VIX)",
    "period": f"{analysis_df.index[0].strftime('%Y-%m-%d')} to {analysis_df.index[-1].strftime('%Y-%m-%d')}",
    "n_obs": len(analysis_df),
    "raw_correlations": {k: {"r": float(v["r"]), "p": float(v["p"]), "t": float(v["t"])}
                         for k, v in raw_corr_results.items()},
    "partial_correlations": {k: {"raw_r": float(v["raw_r"]), "partial_r": float(v["partial_r"]),
                                  "p": float(v["p"])} for k, v in partial_results.items()},
    "best_proxy": best_proxy_name,
    "best_partial_r": float(best_partial_r),
    "regime_analysis": {
        "narrow_vs_broad_t": float(t_nb),
        "narrow_vs_broad_p": float(p_nb),
        "vix_diff_t": float(t_vix),
        "vix_diff_p": float(p_vix),
    },
    "strategy_metrics": {k: {kk: float(vv) for kk, vv in v.items() if kk != "name"}
                          for k, v in strat_metrics.items()},
    "sharpe_diff": float(observed_diff),
    "bootstrap_p": float(p_boot),
    "bootstrap_ci": [float(ci_lo), float(ci_hi)],
    "cross_oos": oos_results,
    "cross_oos_wins": n_wins,
    "lead_lag_max_corr": float(max_corr),
    "lead_lag_max_lag": int(max_lag),
    "verdict_statistical": verdict,
    "verdict_economic": econ_verdict,
}

results_path = "experiments/k353_market_breadth_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")

print("\n" + "=" * 75)
print("K353 COMPLETE")
print("=" * 75)
