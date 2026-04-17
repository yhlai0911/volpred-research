"""K688: CRRA Utility with Properly Lagged Signals
===================================================
Does VT Win on Utility Even Without Sharpe Alpha?

Motivation:
  K687 showed NO VT strategy beats BH 50/50 on Sharpe after proper lag correction.
  K668 showed VT wins on CRRA utility at all gamma — but was that before lag
  correction? Need to re-test with proper lag.

  Higher risk aversion (gamma) means investors care MORE about avoiding losses
  than capturing gains. Even if VT lowers Sharpe, it may increase utility for
  risk-averse investors by reducing extreme losses.

Method:
  - Data: SPY, GLD, VIX daily via yfinance (2006-01-01 to 2026-03-27)
  - ALL signals properly lagged: signal from t-1, return at t
  - Strategies:
    a. 12/VIX on 50/50 SPY/GLD (lagged)
    b. P3-AGG Lookup on 50/50 (lagged)
    c. EWMA VT on 50/50 (lagged)
    d. BH 50/50 SPY/GLD (benchmark, no signal needed)
  - CRRA utility: U = E[W^(1-gamma)] / (1-gamma) for gamma in {1,2,3,5,7,10,15,20}
  - Certainty equivalent return: CE = (E[W^(1-gamma)])^(1/(1-gamma)) - 1
  - Key question: At what gamma does VT start beating BH 50/50 on utility?

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27
Type: Empirical analysis (real data)

References:
  - K687: Post-correction definitive ranking (no VT beats BH 50/50 on Sharpe)
  - K668: Retirement VT (showed CRRA utility advantage — needs lag re-check)
  - Arrow (1965), Aspects of the Theory of Risk-Bearing
  - Pratt (1964), Risk Aversion in the Small and in the Large
  - RiskMetrics (1996), Technical Document (EWMA lambda=0.94)
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), ...and the Cross-Section of Expected Returns (t>3.0)

Author: VolPred Research System
Date: 2026-03-28
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
EVAL_START = "2007-01-03"       # 1y warmup for EWMA / rolling stats
EWMA_LAMBDA = 0.94             # RiskMetrics EWMA decay factor
TARGET_VOL = 0.10              # 10% annualized target volatility
VIX_12_CAP = 1.5               # Cap for 12/VIX weight
TC_BPS = 5                     # Transaction cost in basis points
RF_ANNUAL = 0.04               # Risk-free rate
RF_DAILY = RF_ANNUAL / 252

# CRRA gamma values (risk aversion coefficients)
# gamma=1: log utility (moderate)
# gamma=5: moderately risk-averse
# gamma=10+: highly risk-averse (retirees)
GAMMAS = [1, 2, 3, 5, 7, 10, 15, 20]


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K688: CRRA UTILITY WITH PROPERLY LAGGED SIGNALS")
    print("=" * 70)
    print("\nDownloading data from yfinance...")

    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    raw = {}

    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw[name] = df
        print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

    spy_ret = raw["SPY"]["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = raw["GLD"]["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = raw["VIX"]["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()
    print(f"\n  Merged data: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")

    # Descriptive stats
    print(f"\n  Descriptive statistics:")
    print(f"    SPY daily return: mean={data['spy_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['spy_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    GLD daily return: mean={data['gld_ret'].mean()*252*100:.2f}% ann, "
          f"std={data['gld_ret'].std()*np.sqrt(252)*100:.2f}% ann")
    print(f"    VIX: mean={data['vix'].mean():.2f}, median={data['vix'].median():.2f}, "
          f"std={data['vix'].std():.2f}")

    return data


# ============================================================================
# Signal Computation (ALL LAGGED)
# ============================================================================
def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    """EWMA volatility (RiskMetrics), returns annualized vol series."""
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2 if len(returns) > 0 else 0.0001

    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2

    vol_daily = np.sqrt(var)
    vol_ann = vol_daily * np.sqrt(252)

    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


def compute_all_signals(data):
    """Compute ALL strategy signals, then LAG by 1 day.

    CRITICAL: Every signal is computed on day t, then shifted to apply on day t+1.
    This eliminates ALL lookahead bias.
    """
    print("\n" + "=" * 70)
    print("COMPUTING SIGNALS (ALL LAGGED BY 1 DAY)")
    print("=" * 70)

    vix = data["vix"]
    data = data.copy()

    # --- 50/50 portfolio returns (used as base for VT strategies) ---
    data["port_ret"] = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

    # ================================================================
    # (a) 12/VIX: w = min(12 / VIX, cap)
    # ================================================================
    raw_12vix = np.minimum(12.0 / vix, VIX_12_CAP)
    data["w_12vix"] = raw_12vix.shift(1)  # LAG
    print(f"  12/VIX: raw mean weight = {raw_12vix.mean():.3f}, cap = {VIX_12_CAP}")

    # ================================================================
    # (b) P3-AGG Lookup: VIX<15 → 80%, 15-25 → 45%, >25 → 10%
    # ================================================================
    def p3agg_weight(v):
        if v < 15:
            return 0.80
        elif v <= 25:
            return 0.45
        else:
            return 0.10

    raw_p3agg = vix.apply(p3agg_weight)
    data["w_p3agg"] = raw_p3agg.shift(1)  # LAG
    print(f"  P3-AGG: raw mean weight = {raw_p3agg.mean():.3f}")

    # ================================================================
    # (c) EWMA VT: target vol / realized vol
    # ================================================================
    port_ret_series = data["port_ret"]
    ewma_vol = compute_ewma_vol(port_ret_series, lam=EWMA_LAMBDA)
    raw_ewma_w = np.minimum(TARGET_VOL / ewma_vol.clip(lower=0.01), 2.0)
    data["w_ewma"] = raw_ewma_w.shift(1)  # LAG
    print(f"  EWMA VT: raw mean weight = {raw_ewma_w.mean():.3f}, target vol = {TARGET_VOL}")

    # Trim to evaluation period
    data = data.loc[EVAL_START:]
    data = data.dropna()
    print(f"\n  Evaluation period: {len(data)} days, {data.index[0].date()} to {data.index[-1].date()}")

    return data


# ============================================================================
# Strategy Returns (Net of TX Costs)
# ============================================================================
def compute_strategy_returns(data):
    """Compute daily net returns for each strategy."""
    print("\n" + "=" * 70)
    print("COMPUTING STRATEGY RETURNS (NET OF TX COSTS)")
    print("=" * 70)

    strategies = {}

    # (a) 12/VIX on 50/50
    w_12vix = data["w_12vix"]
    raw_ret_12vix = w_12vix * data["port_ret"]
    # TX cost: proportional to daily weight change
    dw_12vix = w_12vix.diff().abs()
    tc_12vix = dw_12vix * (TC_BPS / 10000)
    strategies["12/VIX"] = raw_ret_12vix - tc_12vix

    # (b) P3-AGG on 50/50
    w_p3agg = data["w_p3agg"]
    raw_ret_p3agg = w_p3agg * data["port_ret"]
    dw_p3agg = w_p3agg.diff().abs()
    tc_p3agg = dw_p3agg * (TC_BPS / 10000)
    strategies["P3-AGG"] = raw_ret_p3agg - tc_p3agg

    # (c) EWMA VT on 50/50
    w_ewma = data["w_ewma"]
    raw_ret_ewma = w_ewma * data["port_ret"]
    dw_ewma = w_ewma.diff().abs()
    tc_ewma = dw_ewma * (TC_BPS / 10000)
    strategies["EWMA VT"] = raw_ret_ewma - tc_ewma

    # (d) BH 50/50 (no TX cost)
    strategies["BH 50/50"] = data["port_ret"]

    # Summary stats
    for name, rets in strategies.items():
        ann_ret = rets.mean() * 252 * 100
        ann_vol = rets.std() * np.sqrt(252) * 100
        sharpe = (rets.mean() - RF_DAILY) / rets.std() * np.sqrt(252)
        cumret = (1 + rets).prod() - 1
        print(f"  {name:12s}: CAGR={ann_ret:6.2f}%, Vol={ann_vol:5.2f}%, "
              f"Sharpe={sharpe:.3f}, CumRet={cumret*100:.1f}%")

    return strategies


# ============================================================================
# CRRA Utility & Certainty Equivalent
# ============================================================================
def crra_utility(daily_returns, gamma):
    """Compute CRRA utility and certainty equivalent return.

    CRRA utility function: u(W) = W^(1-gamma) / (1-gamma)  for gamma != 1
                           u(W) = ln(W)                     for gamma = 1

    For a sequence of daily returns r_1, ..., r_T, the terminal wealth is:
        W = prod(1 + r_t)

    The expected utility approach:
        We compute the utility of each daily gross return (1+r_t),
        then compute the certainty equivalent.

    Actually, for CRRA we use the standard approach:
        CE_daily = (E[(1+r)^(1-gamma)])^(1/(1-gamma)) - 1   for gamma != 1
        CE_daily = exp(E[ln(1+r)]) - 1                       for gamma = 1

    Annualized CE = (1 + CE_daily)^252 - 1
    """
    gross_returns = 1 + daily_returns.values

    # Sanity: remove any non-positive gross returns (would break power utility)
    # In practice these are extremely rare (market circuit breakers at -20%)
    gross_returns = gross_returns[gross_returns > 0]

    if gamma == 1:
        # Log utility
        mean_log = np.mean(np.log(gross_returns))
        ce_daily = np.exp(mean_log) - 1
        utility = mean_log
    else:
        # Power utility
        powered = gross_returns ** (1 - gamma)
        mean_powered = np.mean(powered)

        if mean_powered <= 0:
            # Edge case: should not happen for positive gross returns
            return {"gamma": gamma, "ce_daily": np.nan, "ce_annual_pct": np.nan,
                    "utility": np.nan, "n_obs": len(gross_returns)}

        utility = mean_powered / (1 - gamma)
        ce_daily = mean_powered ** (1 / (1 - gamma)) - 1

    ce_annual = (1 + ce_daily) ** 252 - 1

    return {
        "gamma": gamma,
        "ce_daily": float(ce_daily),
        "ce_annual_pct": float(ce_annual * 100),
        "utility": float(utility),
        "n_obs": int(len(gross_returns))
    }


def compute_crra_all(strategies, gammas=GAMMAS):
    """Compute CRRA utility for all strategies x all gammas."""
    print("\n" + "=" * 70)
    print("CRRA UTILITY ANALYSIS")
    print("=" * 70)

    results = {}

    for gamma in gammas:
        print(f"\n  gamma = {gamma}:")
        gamma_results = {}

        for name, rets in strategies.items():
            res = crra_utility(rets, gamma)
            gamma_results[name] = res
            print(f"    {name:12s}: CE = {res['ce_annual_pct']:+7.3f}% ann "
                  f"(daily CE = {res['ce_daily']*10000:+.4f} bps)")

        results[gamma] = gamma_results

    return results


# ============================================================================
# Utility Advantage Analysis
# ============================================================================
def analyze_utility_advantage(crra_results, strategies):
    """Analyze where VT strategies beat BH 50/50 on utility."""
    print("\n" + "=" * 70)
    print("UTILITY ADVANTAGE: VT vs BH 50/50")
    print("=" * 70)

    vt_strategies = ["12/VIX", "P3-AGG", "EWMA VT"]
    benchmark = "BH 50/50"

    advantage_table = {}

    for vt_name in vt_strategies:
        adv = []
        crossover_gamma = None

        for gamma in GAMMAS:
            ce_vt = crra_results[gamma][vt_name]["ce_annual_pct"]
            ce_bh = crra_results[gamma][benchmark]["ce_annual_pct"]
            diff = ce_vt - ce_bh

            wins = diff > 0
            adv.append({
                "gamma": gamma,
                "ce_vt_pct": ce_vt,
                "ce_bh_pct": ce_bh,
                "diff_pct": diff,
                "vt_wins": bool(wins)
            })

            if crossover_gamma is None and wins:
                crossover_gamma = gamma

        advantage_table[vt_name] = {
            "crossover_gamma": crossover_gamma,
            "details": adv
        }

        print(f"\n  {vt_name} vs BH 50/50:")
        print(f"    {'gamma':>6s}  {'CE(VT)':>10s}  {'CE(BH)':>10s}  {'Diff':>10s}  Winner")
        print(f"    {'─'*6}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}")
        for row in adv:
            winner = f"← {vt_name}" if row["vt_wins"] else "← BH 50/50"
            print(f"    {row['gamma']:6d}  {row['ce_vt_pct']:+10.3f}%  "
                  f"{row['ce_bh_pct']:+10.3f}%  {row['diff_pct']:+10.3f}%  {winner}")

        if crossover_gamma:
            print(f"    ★ VT wins from gamma ≥ {crossover_gamma}")
        else:
            print(f"    ✗ VT never wins on utility")

    return advantage_table


# ============================================================================
# Risk Metrics Comparison
# ============================================================================
def compute_risk_metrics(strategies):
    """Compute additional risk metrics to explain utility differences."""
    print("\n" + "=" * 70)
    print("RISK METRICS (EXPLAINING UTILITY DIFFERENCES)")
    print("=" * 70)

    metrics = {}
    for name, rets in strategies.items():
        r = rets.dropna().values.astype(float)
        cum = np.cumprod(1 + r)
        drawdowns = cum / np.maximum.accumulate(cum) - 1

        # Moments
        mean_daily = np.mean(r)
        std_daily = np.std(r, ddof=1)
        skewness = float(pd.Series(r).skew())
        kurtosis = float(pd.Series(r).kurtosis())  # excess kurtosis

        # Tail risk
        var_1 = np.percentile(r, 1) * 100     # 1% VaR (daily, in %)
        var_5 = np.percentile(r, 5) * 100     # 5% VaR
        cvar_1 = np.mean(r[r <= np.percentile(r, 1)]) * 100  # CVaR 1%
        cvar_5 = np.mean(r[r <= np.percentile(r, 5)]) * 100  # CVaR 5%

        # Drawdown
        mdd = float(drawdowns.min() * 100)
        avg_dd = float(drawdowns[drawdowns < 0].mean() * 100) if (drawdowns < 0).any() else 0

        # Worst days
        worst_1d = float(np.min(r) * 100)
        worst_5d = float(np.sort(r)[:5].mean() * 100)

        m = {
            "ann_return_pct": float(mean_daily * 252 * 100),
            "ann_vol_pct": float(std_daily * np.sqrt(252) * 100),
            "skewness": skewness,
            "excess_kurtosis": kurtosis,
            "var_1pct_daily": float(var_1),
            "var_5pct_daily": float(var_5),
            "cvar_1pct_daily": float(cvar_1),
            "cvar_5pct_daily": float(cvar_5),
            "mdd_pct": mdd,
            "avg_drawdown_pct": avg_dd,
            "worst_1d_pct": worst_1d,
            "worst_5d_avg_pct": worst_5d
        }
        metrics[name] = m

        print(f"\n  {name}:")
        print(f"    Return: {m['ann_return_pct']:+.2f}% ann, Vol: {m['ann_vol_pct']:.2f}%")
        print(f"    Skewness: {skewness:.3f}, Excess Kurtosis: {kurtosis:.2f}")
        print(f"    VaR 1%: {var_1:.3f}%, CVaR 1%: {cvar_1:.3f}%")
        print(f"    VaR 5%: {var_5:.3f}%, CVaR 5%: {cvar_5:.3f}%")
        print(f"    MDD: {mdd:.2f}%, Worst day: {worst_1d:.3f}%")

    return metrics


# ============================================================================
# Bootstrap Confidence Intervals for CE Differences
# ============================================================================
def bootstrap_ce_diff(strat_returns, bh_returns, gamma, n_boot=5000):
    """Bootstrap the CE difference between a VT strategy and BH 50/50.

    Returns the mean, std, and 95% CI of the CE difference.
    """
    n = len(strat_returns)
    diffs = np.zeros(n_boot)

    strat_vals = strat_returns.values
    bh_vals = bh_returns.values

    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        s_boot = strat_vals[idx]
        bh_boot = bh_vals[idx]

        # Compute CE for bootstrap sample
        gross_s = 1 + s_boot
        gross_bh = 1 + bh_boot

        # Remove any non-positive
        gross_s = gross_s[gross_s > 0]
        gross_bh = gross_bh[gross_bh > 0]

        if gamma == 1:
            ce_s = np.exp(np.mean(np.log(gross_s))) - 1
            ce_bh = np.exp(np.mean(np.log(gross_bh))) - 1
        else:
            mean_s = np.mean(gross_s ** (1 - gamma))
            mean_bh = np.mean(gross_bh ** (1 - gamma))

            if mean_s <= 0 or mean_bh <= 0:
                diffs[b] = np.nan
                continue

            ce_s = mean_s ** (1 / (1 - gamma)) - 1
            ce_bh = mean_bh ** (1 / (1 - gamma)) - 1

        # Annualize
        ce_s_ann = (1 + ce_s) ** 252 - 1
        ce_bh_ann = (1 + ce_bh) ** 252 - 1
        diffs[b] = (ce_s_ann - ce_bh_ann) * 100  # In percentage points

    diffs = diffs[~np.isnan(diffs)]

    return {
        "mean_diff_pct": float(np.mean(diffs)),
        "std_diff_pct": float(np.std(diffs)),
        "ci_lower_pct": float(np.percentile(diffs, 2.5)),
        "ci_upper_pct": float(np.percentile(diffs, 97.5)),
        "pct_positive": float(np.mean(diffs > 0) * 100),
        "n_valid_boot": int(len(diffs))
    }


def run_bootstrap_analysis(strategies, gammas_to_test=None):
    """Run bootstrap CI analysis for selected gammas."""
    if gammas_to_test is None:
        gammas_to_test = [1, 3, 5, 10, 20]

    print("\n" + "=" * 70)
    print("BOOTSTRAP CONFIDENCE INTERVALS (5000 reps)")
    print("=" * 70)

    vt_names = ["12/VIX", "P3-AGG", "EWMA VT"]
    bh_rets = strategies["BH 50/50"]

    bootstrap_results = {}

    for gamma in gammas_to_test:
        print(f"\n  gamma = {gamma}:")
        gamma_boot = {}

        for vt_name in vt_names:
            res = bootstrap_ce_diff(strategies[vt_name], bh_rets, gamma)
            gamma_boot[vt_name] = res

            sig = "***" if res["ci_lower_pct"] > 0 or res["ci_upper_pct"] < 0 else ""
            print(f"    {vt_name:12s}: CE diff = {res['mean_diff_pct']:+.3f}% "
                  f"[{res['ci_lower_pct']:+.3f}, {res['ci_upper_pct']:+.3f}] "
                  f"P(VT>BH) = {res['pct_positive']:.1f}% {sig}")

        bootstrap_results[gamma] = gamma_boot

    return bootstrap_results


# ============================================================================
# Sub-period Analysis (Robustness)
# ============================================================================
def subperiod_analysis(strategies):
    """Analyze CRRA utility in different market regimes / sub-periods."""
    print("\n" + "=" * 70)
    print("SUB-PERIOD ANALYSIS")
    print("=" * 70)

    # Define sub-periods
    periods = {
        "Pre-GFC (2007-2008)": ("2007-01-03", "2008-08-31"),
        "GFC (2008.09-2009.03)": ("2008-09-01", "2009-03-31"),
        "Post-GFC Bull (2009.04-2014)": ("2009-04-01", "2014-12-31"),
        "2015-2019 Bull": ("2015-01-01", "2019-12-31"),
        "COVID Crash (2020.02-2020.04)": ("2020-02-01", "2020-04-30"),
        "Post-COVID Bull (2020.05-2021)": ("2020-05-01", "2021-12-31"),
        "2022 Bear": ("2022-01-01", "2022-12-31"),
        "2023-2026 Recovery": ("2023-01-01", "2026-03-27"),
    }

    subperiod_results = {}

    for period_name, (start, end) in periods.items():
        print(f"\n  {period_name}:")

        period_strats = {}
        valid = True
        for name, rets in strategies.items():
            mask = (rets.index >= start) & (rets.index <= end)
            sub_rets = rets[mask]
            if len(sub_rets) < 20:
                valid = False
                break
            period_strats[name] = sub_rets

        if not valid:
            print(f"    (insufficient data, skipping)")
            continue

        # Compute CE at gamma=5 and gamma=10 for each strategy
        period_result = {}
        for gamma in [5, 10]:
            gamma_res = {}
            for name, sub_rets in period_strats.items():
                res = crra_utility(sub_rets, gamma)
                gamma_res[name] = res["ce_annual_pct"]
            period_result[f"gamma_{gamma}"] = gamma_res

        subperiod_results[period_name] = period_result

        # Print results
        for gamma in [5, 10]:
            bh_ce = period_result[f"gamma_{gamma}"]["BH 50/50"]
            print(f"    gamma={gamma:2d}: ", end="")
            for name in ["12/VIX", "P3-AGG", "EWMA VT", "BH 50/50"]:
                ce = period_result[f"gamma_{gamma}"][name]
                diff = ce - bh_ce
                marker = "★" if diff > 0 and name != "BH 50/50" else ""
                print(f"{name}={ce:+.2f}% ", end="")
            print()

    return subperiod_results


# ============================================================================
# Main Execution
# ============================================================================
def main():
    np.random.seed(42)

    # 1. Download data
    data = download_data()

    # 2. Compute lagged signals
    data = compute_all_signals(data)

    # 3. Compute strategy returns (net of TX)
    strategies = compute_strategy_returns(data)

    # 4. CRRA utility analysis
    crra_results = compute_crra_all(strategies)

    # 5. Utility advantage analysis
    advantage_table = analyze_utility_advantage(crra_results, strategies)

    # 6. Risk metrics (explains why utility may differ from Sharpe)
    risk_metrics = compute_risk_metrics(strategies)

    # 7. Bootstrap confidence intervals
    bootstrap_results = run_bootstrap_analysis(strategies)

    # 8. Sub-period analysis
    subperiod_results = subperiod_analysis(strategies)

    # ================================================================
    # Synthesize Key Finding
    # ================================================================
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)

    for vt_name in ["12/VIX", "P3-AGG", "EWMA VT"]:
        info = advantage_table[vt_name]
        cg = info["crossover_gamma"]
        if cg is not None:
            print(f"\n  {vt_name}: VT wins on utility from gamma >= {cg}")
            if cg <= 3:
                print(f"    → Broadly useful (most investors have gamma 2-5)")
            elif cg <= 7:
                print(f"    → Useful for moderately risk-averse investors")
            elif cg <= 10:
                print(f"    → Only useful for highly risk-averse (retirees)")
            else:
                print(f"    → Only useful for extremely risk-averse (gamma {cg}+)")
        else:
            # Check if BH always wins
            all_diffs = [d["diff_pct"] for d in info["details"]]
            best_gamma = info["details"][np.argmax(all_diffs)]["gamma"]
            best_diff = max(all_diffs)
            print(f"\n  {vt_name}: VT never wins on utility")
            print(f"    Best gamma: {best_gamma} (diff = {best_diff:+.3f}%)")
            print(f"    → VT's return sacrifice exceeds its risk reduction benefit")

    # ================================================================
    # Compile Results
    # ================================================================
    results = {
        "experiment_id": "K688",
        "title": "CRRA Utility with Properly Lagged Signals",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "description": (
            "Tests whether VT strategies win on CRRA utility even though they "
            "lose on Sharpe (K687). All signals properly lagged by 1 day. "
            "CRRA utility penalizes extreme losses more heavily for high-gamma "
            "(risk-averse) investors, potentially favoring VT's downside protection."
        ),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "type": "empirical_analysis",
        "configuration": {
            "gammas": GAMMAS,
            "signal_lag": "1 day (ALL strategies)",
            "tx_cost_bps": TC_BPS,
            "rf_annual": RF_ANNUAL,
            "ewma_lambda": EWMA_LAMBDA,
            "target_vol": TARGET_VOL,
            "vix_12_cap": VIX_12_CAP,
            "bootstrap_reps": 5000
        },
        "crra_utility_results": {},
        "advantage_analysis": {},
        "risk_metrics": risk_metrics,
        "bootstrap_ci": {},
        "subperiod_analysis": subperiod_results,
        "references": [
            "K687: Post-correction definitive ranking (no VT beats BH 50/50 on Sharpe after lag)",
            "K668: Retirement VT (showed CRRA utility advantage — needs lag re-check)",
            "Arrow (1965), Aspects of the Theory of Risk-Bearing",
            "Pratt (1964), Risk Aversion in the Small and in the Large",
            "RiskMetrics (1996), Technical Document (EWMA lambda=0.94)",
            "Copeland & Copeland (1999), Market Timing with VIX",
            "Harvey et al. (2016), ...and the Cross-Section of Expected Returns"
        ]
    }

    # Pack CRRA results
    for gamma in GAMMAS:
        gkey = str(gamma)
        results["crra_utility_results"][gkey] = {}
        for name in strategies:
            r = crra_results[gamma][name]
            results["crra_utility_results"][gkey][name] = {
                "ce_annual_pct": round(r["ce_annual_pct"], 4),
                "ce_daily_bps": round(r["ce_daily"] * 10000, 4),
                "utility": round(r["utility"], 8)
            }

    # Pack advantage analysis
    for vt_name in ["12/VIX", "P3-AGG", "EWMA VT"]:
        info = advantage_table[vt_name]
        results["advantage_analysis"][vt_name] = {
            "crossover_gamma": info["crossover_gamma"],
            "details": [
                {
                    "gamma": d["gamma"],
                    "ce_vt_pct": round(d["ce_vt_pct"], 4),
                    "ce_bh_pct": round(d["ce_bh_pct"], 4),
                    "diff_pct": round(d["diff_pct"], 4),
                    "vt_wins": d["vt_wins"]
                }
                for d in info["details"]
            ]
        }

    # Pack bootstrap results
    for gamma, gamma_boot in bootstrap_results.items():
        gkey = str(gamma)
        results["bootstrap_ci"][gkey] = {}
        for vt_name, boot_res in gamma_boot.items():
            results["bootstrap_ci"][gkey][vt_name] = {
                "mean_diff_pct": round(boot_res["mean_diff_pct"], 4),
                "ci_95_lower_pct": round(boot_res["ci_lower_pct"], 4),
                "ci_95_upper_pct": round(boot_res["ci_upper_pct"], 4),
                "pct_positive": round(boot_res["pct_positive"], 1)
            }

    # Key conclusion
    conclusions = []
    for vt_name in ["12/VIX", "P3-AGG", "EWMA VT"]:
        cg = advantage_table[vt_name]["crossover_gamma"]
        if cg:
            conclusions.append(f"{vt_name}: wins on utility from gamma >= {cg}")
        else:
            conclusions.append(f"{vt_name}: never wins on utility")

    results["key_conclusions"] = conclusions

    # Determine overall verdict
    any_crossover = any(
        advantage_table[v]["crossover_gamma"] is not None
        for v in ["12/VIX", "P3-AGG", "EWMA VT"]
    )

    if any_crossover:
        min_crossover = min(
            advantage_table[v]["crossover_gamma"]
            for v in ["12/VIX", "P3-AGG", "EWMA VT"]
            if advantage_table[v]["crossover_gamma"] is not None
        )
        if min_crossover <= 3:
            verdict = (
                f"VT wins on utility for broadly risk-averse investors (gamma >= {min_crossover}). "
                "Even without Sharpe alpha, VT adds value through downside protection."
            )
        elif min_crossover <= 7:
            verdict = (
                f"VT wins on utility only for moderately risk-averse (gamma >= {min_crossover}). "
                "Limited but real value for investors who strongly dislike losses."
            )
        else:
            verdict = (
                f"VT wins on utility only for extremely risk-averse (gamma >= {min_crossover}). "
                "Narrow utility advantage, most investors better off with BH 50/50."
            )
    else:
        verdict = (
            "VT NEVER wins on utility at any gamma level after proper lag correction. "
            "The return sacrifice is too large to be compensated by risk reduction. "
            "K668's utility advantage was likely an artifact of improper lagging."
        )

    results["verdict"] = verdict
    print(f"\n  VERDICT: {verdict}")

    # Save
    out_path = Path(__file__).parent / "k688_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    results = main()
