"""K860: Prospect Theory Evaluation of VT — Loss Aversion Makes VT More Valuable

Research Question:
  Under Prospect Theory (Tversky & Kahneman 1992), how much more valuable is VT
  compared to traditional mean-variance (Sharpe/CRRA)?

  1. Does loss aversion (lambda=2.25) make VT's drawdown reduction worth more?
  2. At what lambda does VT become strictly preferred over BH 50/50?
  3. How do VT variants rank under PT vs Sharpe vs CRRA?

Background:
  - K687: No VT beats BH 50/50 on Sharpe (0.545) with correct lag
  - K688: VT wins on CRRA utility for gamma>=5
  - K859: Robust VT (Floor+Cap+EWMA) Sharpe 0.579, MDD -31.5%
  - VT is drawdown insurance — but HOW MUCH is that worth psychologically?

Prospect Theory (TK92):
  v(x) = x^alpha          if x >= 0  (gains)
  v(x) = -lambda*(-x)^beta if x < 0  (losses)
  Standard params: alpha=beta=0.88, lambda=2.25

  Key: losses feel 2.25x worse than equivalent gains.
  VT reduces big losses => huge PT benefit.

Strategies (all with shift(1)):
  - BH SPY (100% equity reference)
  - BH 50/50 SPY/GLD (monthly rebalance)
  - 12/VIX monthly (baseline VT)
  - Floor(0.3)+Cap(0.9)+EWMA(10)+monthly (K859 best)
  - Risk Parity SPY/GLD (inverse vol weighting, monthly)

Analysis:
  a. CPT value for each strategy at daily and monthly frequency
  b. Sensitivity: lambda from 1.0 to 4.0
  c. Break-even lambda where VT > BH 50/50
  d. CPT ranking vs Sharpe ranking vs CRRA ranking
  e. Certainty Equivalent under PT
  f. Loss frequency analysis

Error log rules applied:
  - Lookahead: signal.shift(1) mandatory
  - Sanity check: compute actual values, never hard-code
  - DM test: from volpred.stats.model_evaluation if needed
  - Sharpe > 2x baseline = almost certainly a bug

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2005-01-01 to 2026-04-04
Evaluation: 2006-01-03 onwards (1yr warmup)

References:
  - Kahneman & Tversky (1979). Prospect theory. Econometrica 47(2), 263-291.
  - Tversky & Kahneman (1992). Advances in prospect theory. J Risk & Uncertainty 5(4), 297-323.
  - Barberis (2013). Thirty years of prospect theory in economics. JEP 27(1), 173-196.
  - K687/K688/K859 (VolPred prior experiments)

Author: VolPred Research System
Date: 2026-04-05
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats
from scipy.optimize import brentq

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2005-01-01"
END_DATE = "2026-04-04"
EVAL_START = "2006-01-03"
TC_BPS = 5                     # Transaction cost in basis points (one-way)
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

# PT parameters (TK92 standard)
ALPHA_PT = 0.88                # Gain curvature
BETA_PT = 0.88                 # Loss curvature
LAMBDA_STANDARD = 2.25         # Standard loss aversion

# Lambda sensitivity range
LAMBDA_RANGE = np.arange(1.0, 4.05, 0.25)

# CRRA gammas for comparison
CRRA_GAMMAS = [1, 2, 3, 5, 8, 10]

# VT parameters
VIX_12_CAP = 1.5
FLOOR = 0.3
CAP = 0.9
EWMA_SPAN = 10


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K860: PROSPECT THEORY EVALUATION OF VT")
    print("=" * 70)
    print("\n[1] DOWNLOADING DATA")

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

    print(f"\n  Merged: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")
    print(f"  SPY ann ret: {data['spy_ret'].mean()*252*100:.1f}%, vol: {data['spy_ret'].std()*np.sqrt(252)*100:.1f}%")
    print(f"  GLD ann ret: {data['gld_ret'].mean()*252*100:.1f}%, vol: {data['gld_ret'].std()*np.sqrt(252)*100:.1f}%")
    print(f"  VIX mean: {data['vix'].mean():.1f}, SPY-GLD corr: {data['spy_ret'].corr(data['gld_ret']):.3f}")

    return data, raw


# ============================================================================
# Strategy Signal Computation
# ============================================================================
def apply_rebalance_monthly(raw_weight):
    """Convert daily signal to monthly-rebalance by holding weight constant."""
    rebal_dates = raw_weight.groupby(
        raw_weight.index.to_period("M")
    ).apply(lambda g: g.index[0])
    held = raw_weight.copy() * np.nan
    for d in rebal_dates:
        if d in held.index:
            held.loc[d] = raw_weight.loc[d]
    held = held.ffill()
    return held


def compute_strategy_returns(data):
    """Compute daily returns for all strategies. ALL lagged by shift(1)."""
    print("\n[2] COMPUTING STRATEGY RETURNS (all lagged by shift(1))")

    vix = data["vix"]
    spy_ret = data["spy_ret"]
    gld_ret = data["gld_ret"]

    strategies = {}

    # --- 0. BH SPY (100% equity) ---
    strategies["BH_SPY"] = spy_ret.copy()
    print(f"  [0] BH SPY 100%")

    # --- 1. BH 50/50 SPY/GLD (monthly rebalance) ---
    w_5050 = pd.Series(0.5, index=data.index)
    w_5050_monthly = apply_rebalance_monthly(w_5050).shift(1)  # LAG
    ret_5050 = w_5050_monthly * spy_ret + (1 - w_5050_monthly) * gld_ret
    # TX cost for 50/50 monthly rebalance (small, ~rebalance drift)
    dw_5050 = w_5050_monthly.diff().abs().fillna(0)
    tc_5050 = dw_5050 * TC_BPS / 10000
    strategies["BH_5050"] = ret_5050 - tc_5050
    print(f"  [1] BH 50/50 SPY/GLD monthly")

    # --- 2. 12/VIX monthly ---
    raw_12vix = np.minimum(12.0 / vix, VIX_12_CAP)
    w_12vix = apply_rebalance_monthly(raw_12vix).shift(1)  # LAG
    ret_12vix = w_12vix * spy_ret + (1 - w_12vix) * gld_ret
    dw_12vix = w_12vix.diff().abs().fillna(0)
    tc_12vix = dw_12vix * TC_BPS / 10000
    strategies["VT_12VIX"] = ret_12vix - tc_12vix
    print(f"  [2] 12/VIX monthly: mean w = {w_12vix.mean():.3f}")

    # --- 3. Floor+Cap+EWMA(10) monthly (K859 best) ---
    vix_ewma = vix.ewm(span=EWMA_SPAN).mean()
    raw_robust = np.maximum(FLOOR, np.minimum(CAP, 12.0 / vix_ewma))
    w_robust = apply_rebalance_monthly(raw_robust).shift(1)  # LAG
    ret_robust = w_robust * spy_ret + (1 - w_robust) * gld_ret
    dw_robust = w_robust.diff().abs().fillna(0)
    tc_robust = dw_robust * TC_BPS / 10000
    strategies["VT_Robust"] = ret_robust - tc_robust
    print(f"  [3] Floor+Cap+EWMA(10): mean w = {w_robust.mean():.3f}")

    # --- 4. Risk Parity SPY/GLD (monthly) ---
    spy_vol_20 = spy_ret.rolling(20).std()
    gld_vol_20 = gld_ret.rolling(20).std()
    raw_rp = gld_vol_20 / (spy_vol_20 + gld_vol_20)  # inverse vol weight for SPY
    raw_rp = raw_rp.clip(0.1, 0.9)
    w_rp = apply_rebalance_monthly(raw_rp).shift(1)  # LAG
    ret_rp = w_rp * spy_ret + (1 - w_rp) * gld_ret
    dw_rp = w_rp.diff().abs().fillna(0)
    tc_rp = dw_rp * TC_BPS / 10000
    strategies["Risk_Parity"] = ret_rp - tc_rp
    print(f"  [4] Risk Parity: mean w = {w_rp.mean():.3f}")

    # Filter to eval period and drop NaN
    eval_start = pd.Timestamp(EVAL_START)
    strat_returns = {}
    for name, ret in strategies.items():
        r = ret.loc[ret.index >= eval_start].dropna()
        strat_returns[name] = r
        print(f"  {name}: {len(r)} days, {r.index[0].date()} to {r.index[-1].date()}")

    return strat_returns


# ============================================================================
# Standard Performance Metrics
# ============================================================================
def compute_performance(returns_dict):
    """Compute Sharpe, CAGR, MDD, Sortino for each strategy."""
    print("\n[3] STANDARD PERFORMANCE METRICS")

    metrics = {}
    for name, ret in returns_dict.items():
        n_days = len(ret)
        n_years = n_days / 252

        cum = (1 + ret).cumprod()
        cagr = cum.iloc[-1] ** (1 / n_years) - 1
        ann_vol = ret.std() * np.sqrt(252)
        sharpe = (ret.mean() - RF_DAILY) / ret.std() * np.sqrt(252) if ret.std() > 0 else 0

        # MDD
        peak = cum.cummax()
        dd = (cum - peak) / peak
        mdd = dd.min()

        # Sortino
        downside = ret[ret < 0].std() * np.sqrt(252)
        sortino = (ret.mean() * 252 - RF_ANNUAL) / downside if downside > 0 else 0

        # Calmar
        calmar = cagr / abs(mdd) if mdd != 0 else 0

        # Loss stats
        loss_freq_daily = (ret < 0).mean()
        loss_mean = ret[ret < 0].mean() if (ret < 0).any() else 0
        gain_mean = ret[ret >= 0].mean() if (ret >= 0).any() else 0

        metrics[name] = {
            "sharpe": float(sharpe),
            "cagr": float(cagr),
            "ann_vol": float(ann_vol),
            "mdd": float(mdd),
            "sortino": float(sortino),
            "calmar": float(calmar),
            "loss_freq_daily": float(loss_freq_daily),
            "loss_mean_daily": float(loss_mean),
            "gain_mean_daily": float(gain_mean),
            "n_days": n_days,
        }

        print(f"  {name:15s}: Sharpe={sharpe:.3f}, CAGR={cagr*100:.1f}%, MDD={mdd*100:.1f}%, "
              f"Sortino={sortino:.3f}, LossFreq={loss_freq_daily*100:.1f}%")

    return metrics


# ============================================================================
# Prospect Theory Value Functions
# ============================================================================
def pt_value(x, alpha=ALPHA_PT, beta=BETA_PT, lam=LAMBDA_STANDARD):
    """Prospect Theory value function (TK92).
    v(x) = x^alpha       if x >= 0
    v(x) = -lambda*(-x)^beta  if x < 0
    """
    result = np.where(
        x >= 0,
        np.power(np.maximum(x, 1e-20), alpha),        # gains
        -lam * np.power(np.maximum(-x, 1e-20), beta)   # losses
    )
    return result


def compute_cpt_value(returns, alpha=ALPHA_PT, beta=BETA_PT, lam=LAMBDA_STANDARD):
    """Compute Cumulative Prospect Theory value as mean v(r_t).
    We use the simple version: average PT value per period.
    This captures the key insight: loss aversion penalizes frequent/large losses.
    """
    r = returns.values
    v = pt_value(r, alpha, beta, lam)
    return float(np.mean(v))


def compute_cpt_certainty_equivalent(returns, alpha=ALPHA_PT, beta=BETA_PT, lam=LAMBDA_STANDARD):
    """Certainty Equivalent under PT: the certain return CE such that v(CE) = E[v(r)].
    Solve: CE^alpha = mean_v  if mean_v >= 0
           -lambda*(-CE)^beta = mean_v  if mean_v < 0
    """
    mean_v = compute_cpt_value(returns, alpha, beta, lam)

    if mean_v >= 0:
        # v(CE) = CE^alpha = mean_v => CE = mean_v^(1/alpha)
        ce = mean_v ** (1.0 / alpha)
    else:
        # v(CE) = -lambda*(-CE)^beta = mean_v
        # lambda*(-CE)^beta = -mean_v
        # (-CE)^beta = -mean_v / lambda
        # -CE = (-mean_v / lambda)^(1/beta)
        # CE = -((-mean_v / lambda)^(1/beta))
        ce = -((-mean_v / lam) ** (1.0 / beta))

    return float(ce)


def compute_crra_utility(returns, gamma):
    """CRRA utility: E[u(1+r)] where u(w) = w^(1-gamma)/(1-gamma) for gamma != 1,
    or u(w) = ln(w) for gamma = 1.
    """
    w = 1.0 + returns.values  # wealth ratio
    w = np.maximum(w, 1e-10)  # prevent negative/zero

    if gamma == 1:
        u = np.log(w)
    else:
        u = w ** (1 - gamma) / (1 - gamma)

    return float(np.mean(u))


# ============================================================================
# Monthly Aggregation
# ============================================================================
def aggregate_monthly(returns_dict):
    """Aggregate daily returns to monthly returns."""
    monthly = {}
    for name, ret in returns_dict.items():
        # Group by month and compound
        m = (1 + ret).groupby(ret.index.to_period("M")).prod() - 1
        monthly[name] = m
    return monthly


# ============================================================================
# Main Analysis
# ============================================================================
def main():
    # --- Download data ---
    data, raw = download_data()

    # --- Compute strategy returns ---
    strat_returns = compute_strategy_returns(data)

    # --- Standard performance ---
    perf = compute_performance(strat_returns)

    # --- Monthly aggregation ---
    monthly_returns = aggregate_monthly(strat_returns)

    # ====================================================================
    # [4] PROSPECT THEORY ANALYSIS
    # ====================================================================
    print("\n" + "=" * 70)
    print("[4] PROSPECT THEORY ANALYSIS (TK92)")
    print("=" * 70)

    # --- 4a. CPT values at standard lambda=2.25 ---
    print("\n[4a] CPT VALUES (alpha=0.88, beta=0.88, lambda=2.25)")
    print("     Reference point = 0 (zero return)")

    cpt_daily = {}
    cpt_monthly = {}
    ce_daily = {}
    ce_monthly = {}

    for name in strat_returns:
        cpt_daily[name] = compute_cpt_value(strat_returns[name])
        cpt_monthly[name] = compute_cpt_value(monthly_returns[name])
        ce_daily[name] = compute_cpt_certainty_equivalent(strat_returns[name])
        ce_monthly[name] = compute_cpt_certainty_equivalent(monthly_returns[name])

    print(f"\n  {'Strategy':18s} | {'CPT(daily)':>12s} | {'CPT(monthly)':>14s} | {'CE daily(bps)':>14s} | {'CE monthly(%)':>14s}")
    print(f"  {'-'*18}-+-{'-'*12}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}")
    for name in strat_returns:
        print(f"  {name:18s} | {cpt_daily[name]:12.6f} | {cpt_monthly[name]:14.6f} | "
              f"{ce_daily[name]*10000:14.2f} | {ce_monthly[name]*100:14.4f}")

    # --- 4b. PT Premium: CPT(VT) - CPT(BH_5050) ---
    print("\n[4b] PT PREMIUM vs BH 50/50")
    ref_cpt_d = cpt_daily["BH_5050"]
    ref_cpt_m = cpt_monthly["BH_5050"]

    for name in strat_returns:
        if name == "BH_5050":
            continue
        prem_d = cpt_daily[name] - ref_cpt_d
        prem_m = cpt_monthly[name] - ref_cpt_m
        prem_d_pct = prem_d / abs(ref_cpt_d) * 100 if ref_cpt_d != 0 else 0
        prem_m_pct = prem_m / abs(ref_cpt_m) * 100 if ref_cpt_m != 0 else 0
        print(f"  {name:18s}: daily premium = {prem_d:+.6f} ({prem_d_pct:+.1f}%), "
              f"monthly = {prem_m:+.6f} ({prem_m_pct:+.1f}%)")

    # ====================================================================
    # [5] LAMBDA SENSITIVITY: When does VT become preferred?
    # ====================================================================
    print("\n" + "=" * 70)
    print("[5] LAMBDA SENSITIVITY ANALYSIS")
    print("=" * 70)

    lambda_results = {name: [] for name in strat_returns}
    lambda_ce_results = {name: [] for name in strat_returns}

    for lam in LAMBDA_RANGE:
        for name in strat_returns:
            v = compute_cpt_value(strat_returns[name], lam=lam)
            lambda_results[name].append(v)
            ce = compute_cpt_certainty_equivalent(strat_returns[name], lam=lam)
            lambda_ce_results[name].append(ce)

    # Print table: CPT values at different lambdas
    print(f"\n  CPT Values (daily) at different lambda levels:")
    print(f"  {'lambda':>7s}", end="")
    for name in strat_returns:
        print(f" | {name:>14s}", end="")
    print()
    print(f"  {'-'*7}", end="")
    for _ in strat_returns:
        print(f"-+-{'-'*14}", end="")
    print()

    for i, lam in enumerate(LAMBDA_RANGE):
        print(f"  {lam:7.2f}", end="")
        for name in strat_returns:
            print(f" | {lambda_results[name][i]:14.6f}", end="")
        print()

    # --- Find break-even lambda ---
    print("\n[5b] BREAK-EVEN LAMBDA (where VT > BH 50/50)")

    vt_names = ["VT_12VIX", "VT_Robust", "Risk_Parity"]
    breakeven_lambdas = {}

    for vt_name in vt_names:
        # Compute difference in CPT values across lambda range
        diffs = []
        for i, lam in enumerate(LAMBDA_RANGE):
            d = lambda_results[vt_name][i] - lambda_results["BH_5050"][i]
            diffs.append(d)

        # Check if there's a sign change
        diffs_arr = np.array(diffs)

        # Check at endpoints
        if diffs_arr[0] > 0:
            print(f"  {vt_name}: Already preferred at lambda=1.0 (no loss aversion needed)")
            breakeven_lambdas[vt_name] = {"value": 1.0, "note": "preferred_at_lambda_1"}
        elif diffs_arr[-1] < 0:
            print(f"  {vt_name}: Never preferred even at lambda={LAMBDA_RANGE[-1]:.1f}")
            breakeven_lambdas[vt_name] = {"value": None, "note": "never_preferred"}
        else:
            # Find crossover via interpolation
            sign_changes = np.where(np.diff(np.sign(diffs_arr)))[0]
            if len(sign_changes) > 0:
                idx = sign_changes[0]
                # Linear interpolation
                lam1, lam2 = LAMBDA_RANGE[idx], LAMBDA_RANGE[idx + 1]
                d1, d2 = diffs_arr[idx], diffs_arr[idx + 1]
                breakeven = lam1 + (0 - d1) * (lam2 - lam1) / (d2 - d1)
                print(f"  {vt_name}: break-even lambda = {breakeven:.2f}")
                breakeven_lambdas[vt_name] = {"value": float(breakeven), "note": "interpolated"}
            else:
                # Try finer grid
                fine_lambdas = np.linspace(1.0, 4.0, 1000)
                fine_diffs = []
                for fl in fine_lambdas:
                    v_vt = compute_cpt_value(strat_returns[vt_name], lam=fl)
                    v_bh = compute_cpt_value(strat_returns["BH_5050"], lam=fl)
                    fine_diffs.append(v_vt - v_bh)
                fine_diffs = np.array(fine_diffs)
                sign_ch = np.where(np.diff(np.sign(fine_diffs)))[0]
                if len(sign_ch) > 0:
                    idx = sign_ch[0]
                    breakeven = fine_lambdas[idx]
                    print(f"  {vt_name}: break-even lambda = {breakeven:.3f} (fine grid)")
                    breakeven_lambdas[vt_name] = {"value": float(breakeven), "note": "fine_grid"}
                else:
                    print(f"  {vt_name}: No crossover found in [1.0, 4.0]")
                    breakeven_lambdas[vt_name] = {"value": None, "note": "no_crossover"}

    # ====================================================================
    # [6] CRRA COMPARISON (from K688)
    # ====================================================================
    print("\n" + "=" * 70)
    print("[6] CRRA UTILITY COMPARISON")
    print("=" * 70)

    crra_results = {}
    for gamma in CRRA_GAMMAS:
        crra_results[gamma] = {}
        for name in strat_returns:
            crra_results[gamma][name] = compute_crra_utility(strat_returns[name], gamma)

    print(f"\n  {'gamma':>7s}", end="")
    for name in strat_returns:
        print(f" | {name:>14s}", end="")
    print()
    print(f"  {'-'*7}", end="")
    for _ in strat_returns:
        print(f"-+-{'-'*14}", end="")
    print()

    for gamma in CRRA_GAMMAS:
        print(f"  {gamma:7d}", end="")
        for name in strat_returns:
            print(f" | {crra_results[gamma][name]:14.6f}", end="")
        print()

    # ====================================================================
    # [7] RANKING COMPARISON: Sharpe vs PT vs CRRA
    # ====================================================================
    print("\n" + "=" * 70)
    print("[7] RANKING COMPARISON")
    print("=" * 70)

    # Sharpe ranking
    sharpe_order = sorted(strat_returns.keys(), key=lambda n: perf[n]["sharpe"], reverse=True)
    # PT ranking (daily, standard lambda)
    pt_order = sorted(strat_returns.keys(), key=lambda n: cpt_daily[n], reverse=True)
    # CRRA ranking (gamma=5)
    crra5_order = sorted(strat_returns.keys(), key=lambda n: crra_results[5][n], reverse=True)
    # CRRA ranking (gamma=10)
    crra10_order = sorted(strat_returns.keys(), key=lambda n: crra_results[10][n], reverse=True)
    # PT ranking at lambda=3.0 (high loss aversion)
    pt_lam3_vals = {}
    for name in strat_returns:
        pt_lam3_vals[name] = compute_cpt_value(strat_returns[name], lam=3.0)
    pt_lam3_order = sorted(strat_returns.keys(), key=lambda n: pt_lam3_vals[n], reverse=True)

    print(f"\n  {'Rank':>4s} | {'Sharpe':>14s} | {'PT (λ=2.25)':>14s} | {'PT (λ=3.0)':>14s} | {'CRRA (γ=5)':>14s} | {'CRRA (γ=10)':>14s}")
    print(f"  {'-'*4}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}")
    for rank in range(len(strat_returns)):
        print(f"  {rank+1:4d} | {sharpe_order[rank]:>14s} | {pt_order[rank]:>14s} | "
              f"{pt_lam3_order[rank]:>14s} | {crra5_order[rank]:>14s} | {crra10_order[rank]:>14s}")

    # ====================================================================
    # [8] LOSS FREQUENCY & TAIL ANALYSIS
    # ====================================================================
    print("\n" + "=" * 70)
    print("[8] LOSS FREQUENCY & TAIL ANALYSIS")
    print("=" * 70)

    for name in strat_returns:
        r = strat_returns[name]
        # Daily
        loss_pct_d = (r < 0).mean() * 100
        big_loss_d = (r < -0.02).mean() * 100  # > 2% daily loss
        tail_loss_d = (r < -0.03).mean() * 100  # > 3% daily loss

        # Monthly
        mr = monthly_returns[name]
        loss_pct_m = (mr < 0).mean() * 100
        big_loss_m = (mr < -0.05).mean() * 100  # > 5% monthly loss
        tail_loss_m = (mr < -0.10).mean() * 100  # > 10% monthly loss

        # Worst returns
        worst_d = r.nsmallest(5).values
        worst_m = mr.nsmallest(5).values

        print(f"\n  {name}:")
        print(f"    Daily:  loss freq {loss_pct_d:.1f}%, >2% loss: {big_loss_d:.1f}%, >3%: {tail_loss_d:.1f}%")
        print(f"    Monthly: loss freq {loss_pct_m:.1f}%, >5% loss: {big_loss_m:.1f}%, >10%: {tail_loss_m:.1f}%")
        print(f"    Worst 5 daily:  {[f'{w*100:.2f}%' for w in worst_d]}")
        print(f"    Worst 5 monthly: {[f'{w*100:.2f}%' for w in worst_m]}")

    # ====================================================================
    # [9] PT PREMIUM DECOMPOSITION: Gain vs Loss component
    # ====================================================================
    print("\n" + "=" * 70)
    print("[9] PT VALUE DECOMPOSITION: Gains vs Losses")
    print("=" * 70)

    decomp = {}
    for name in strat_returns:
        r = strat_returns[name].values
        gains = r[r >= 0]
        losses = r[r < 0]

        # Gain component: mean(x^alpha)
        gain_component = np.mean(np.power(np.maximum(gains, 1e-20), ALPHA_PT))
        # Loss component: mean(-lambda*(-x)^beta) for losses only
        loss_component = np.mean(-LAMBDA_STANDARD * np.power(np.maximum(-losses, 1e-20), BETA_PT))

        # Weighted by frequency
        p_gain = len(gains) / len(r)
        p_loss = len(losses) / len(r)
        total_pt = p_gain * gain_component + p_loss * loss_component

        decomp[name] = {
            "gain_component": float(gain_component),
            "loss_component": float(loss_component),
            "p_gain": float(p_gain),
            "p_loss": float(p_loss),
            "weighted_gain": float(p_gain * gain_component),
            "weighted_loss": float(p_loss * loss_component),
            "total_pt": float(total_pt),
        }

        print(f"  {name:18s}: gain={p_gain*gain_component:+.6f} (p={p_gain:.3f}), "
              f"loss={p_loss*loss_component:+.6f} (p={p_loss:.3f}), "
              f"total={total_pt:+.6f}")

    # ====================================================================
    # [10] CERTAINTY EQUIVALENT COMPARISON
    # ====================================================================
    print("\n" + "=" * 70)
    print("[10] CERTAINTY EQUIVALENT COMPARISON")
    print("=" * 70)

    print(f"\n  {'Strategy':18s} | {'CE daily(bps)':>14s} | {'CE monthly(%)':>14s} | {'CE ann.(%)':>12s} | {'Sharpe':>8s}")
    print(f"  {'-'*18}-+-{'-'*14}-+-{'-'*14}-+-{'-'*12}-+-{'-'*8}")
    for name in strat_returns:
        ce_d_bps = ce_daily[name] * 10000
        ce_m_pct = ce_monthly[name] * 100
        ce_ann = ((1 + ce_monthly[name]) ** 12 - 1) * 100
        print(f"  {name:18s} | {ce_d_bps:14.2f} | {ce_m_pct:14.4f} | {ce_ann:12.2f} | {perf[name]['sharpe']:8.3f}")

    # ====================================================================
    # [11] KEY FINDING: "Insurance Value" of VT
    # ====================================================================
    print("\n" + "=" * 70)
    print("[11] KEY FINDINGS")
    print("=" * 70)

    # How much does VT's CE improve under PT vs simple mean?
    for name in ["VT_12VIX", "VT_Robust", "Risk_Parity"]:
        mean_d = strat_returns[name].mean()
        mean_d_bh = strat_returns["BH_5050"].mean()
        ce_d = ce_daily[name]
        ce_d_bh = ce_daily["BH_5050"]

        # Mean return advantage
        mean_adv = (mean_d - mean_d_bh) * 252 * 10000  # annualized bps
        # CE advantage (PT-adjusted)
        ce_adv = (ce_d - ce_d_bh) * 252 * 10000  # annualized bps

        # "PT amplification": how much does PT amplify (or dampen) the advantage?
        if abs(mean_adv) > 0.01:
            amplification = ce_adv / mean_adv
        else:
            amplification = float('inf') if ce_adv > 0 else float('-inf')

        print(f"\n  {name} vs BH 50/50:")
        print(f"    Mean return advantage:     {mean_adv:+.1f} bps/yr")
        print(f"    PT Certainty-Equiv adv:    {ce_adv:+.1f} bps/yr")
        if abs(mean_adv) > 0.01:
            print(f"    PT amplification factor:   {amplification:.2f}x")
        print(f"    Interpretation: PT values VT's loss reduction "
              f"{'MORE' if ce_adv > mean_adv else 'LESS'} than raw return difference")

    # ====================================================================
    # [12] MONTHLY PT SENSITIVITY TABLE (for publication)
    # ====================================================================
    print("\n" + "=" * 70)
    print("[12] MONTHLY CPT CERTAINTY EQUIVALENT AT VARIOUS LAMBDA")
    print("=" * 70)

    print(f"\n  {'lambda':>7s}", end="")
    for name in strat_returns:
        print(f" | {name:>14s}", end="")
    print(" | {'Best':>10s}")
    print(f"  {'-'*7}", end="")
    for _ in strat_returns:
        print(f"-+-{'-'*14}", end="")
    print(f"-+-{'-'*10}")

    lambda_ce_monthly = {}
    for lam in LAMBDA_RANGE:
        lambda_ce_monthly[lam] = {}
        best_name = None
        best_ce = -1e10
        print(f"  {lam:7.2f}", end="")
        for name in strat_returns:
            ce = compute_cpt_certainty_equivalent(monthly_returns[name], lam=lam)
            lambda_ce_monthly[lam][name] = ce
            ce_ann = ((1 + ce) ** 12 - 1) * 100
            print(f" | {ce_ann:14.2f}", end="")
            if ce > best_ce:
                best_ce = ce
                best_name = name
        print(f" | {best_name:>10s}")

    # ====================================================================
    # Save Results
    # ====================================================================
    print("\n" + "=" * 70)
    print("[13] SAVING RESULTS")
    print("=" * 70)

    results = {
        "experiment_id": "K860",
        "title": "Prospect Theory Evaluation of VT — Loss Aversion Makes VT More Valuable",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "n_days_eval": {name: len(strat_returns[name]) for name in strat_returns},
        "pt_parameters": {
            "alpha": ALPHA_PT,
            "beta": BETA_PT,
            "lambda_standard": LAMBDA_STANDARD,
            "reference_point": "zero return",
        },
        "standard_performance": perf,
        "cpt_values_daily": cpt_daily,
        "cpt_values_monthly": {name: float(v) for name, v in cpt_monthly.items()},
        "certainty_equivalent_daily_bps": {name: float(v * 10000) for name, v in ce_daily.items()},
        "certainty_equivalent_monthly_pct": {name: float(v * 100) for name, v in ce_monthly.items()},
        "pt_decomposition": decomp,
        "breakeven_lambdas": breakeven_lambdas,
        "lambda_sensitivity": {
            "lambdas": [float(l) for l in LAMBDA_RANGE],
            "cpt_daily": {name: [float(v) for v in vals] for name, vals in lambda_results.items()},
            "ce_daily_bps": {name: [float(v * 10000) for v in vals] for name, vals in lambda_ce_results.items()},
        },
        "crra_utility": {str(g): {name: float(v) for name, v in crra_results[g].items()} for g in CRRA_GAMMAS},
        "rankings": {
            "sharpe": sharpe_order,
            "pt_lambda225": pt_order,
            "pt_lambda300": pt_lam3_order,
            "crra_gamma5": crra5_order,
            "crra_gamma10": crra10_order,
        },
        "key_findings": [],
        "references": [
            "Kahneman & Tversky (1979). Prospect theory. Econometrica 47(2), 263-291.",
            "Tversky & Kahneman (1992). Advances in prospect theory. J Risk & Uncertainty 5(4), 297-323.",
            "Barberis (2013). Thirty years of prospect theory in economics. JEP 27(1), 173-196.",
            "K687: Definitive VT ranking (no VT beats BH 50/50 on Sharpe)",
            "K688: CRRA utility (VT wins at gamma>=5)",
            "K859: Robust VT design (Floor+Cap+EWMA best)",
        ],
    }

    # --- Compute key findings ---
    findings = []

    # Finding 1: Does PT favor VT over BH?
    vt_12vix_premium_d = cpt_daily["VT_12VIX"] - cpt_daily["BH_5050"]
    robust_premium_d = cpt_daily["VT_Robust"] - cpt_daily["BH_5050"]
    if vt_12vix_premium_d > 0 or robust_premium_d > 0:
        findings.append(
            f"PT favors VT over BH 50/50: 12/VIX premium = {vt_12vix_premium_d:+.6f}, "
            f"Robust VT premium = {robust_premium_d:+.6f} (daily CPT, lambda=2.25)"
        )
    else:
        findings.append(
            f"PT does NOT favor VT over BH 50/50 at standard lambda=2.25: "
            f"12/VIX diff = {vt_12vix_premium_d:+.6f}, Robust diff = {robust_premium_d:+.6f}"
        )

    # Finding 2: Break-even lambdas
    for vt_name, be in breakeven_lambdas.items():
        if be["value"] is not None:
            findings.append(
                f"{vt_name} becomes preferred at lambda={be['value']:.2f} "
                f"({be['note']})"
            )
        else:
            findings.append(f"{vt_name}: {be['note']}")

    # Finding 3: Ranking stability
    sharpe_top = sharpe_order[0]
    pt_top = pt_order[0]
    crra5_top = crra5_order[0]
    findings.append(
        f"Top strategy: Sharpe={sharpe_top}, PT(lambda=2.25)={pt_top}, CRRA(gamma=5)={crra5_top}"
    )

    # Finding 4: CE comparison
    ce_bh_ann = ((1 + ce_monthly["BH_5050"]) ** 12 - 1) * 100
    for vt_name in ["VT_12VIX", "VT_Robust"]:
        ce_vt_ann = ((1 + ce_monthly[vt_name]) ** 12 - 1) * 100
        ce_diff = ce_vt_ann - ce_bh_ann
        findings.append(
            f"{vt_name} CE(monthly,ann): {ce_vt_ann:.2f}% vs BH 50/50: {ce_bh_ann:.2f}% "
            f"(diff={ce_diff:+.2f}pp)"
        )

    # Finding 5: Loss frequency reduction
    bh_loss_freq = perf["BH_5050"]["loss_freq_daily"]
    for vt_name in ["VT_12VIX", "VT_Robust"]:
        vt_loss_freq = perf[vt_name]["loss_freq_daily"]
        reduction = (bh_loss_freq - vt_loss_freq) / bh_loss_freq * 100
        findings.append(
            f"{vt_name} loss freq reduction: {vt_loss_freq*100:.1f}% vs BH {bh_loss_freq*100:.1f}% "
            f"(reduction: {reduction:+.1f}%)"
        )

    results["key_findings"] = findings

    for f in findings:
        print(f"  * {f}")

    # Save
    results_path = Path("experiments/k860_results.json")
    with open(results_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2, ensure_ascii=False, default=str)

    print(f"\n  Saved to {results_path}")
    print("\n" + "=" * 70)
    print("K860 COMPLETE")
    print("=" * 70)

    return results


if __name__ == "__main__":
    results = main()
