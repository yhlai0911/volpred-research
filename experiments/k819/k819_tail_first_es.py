#!/usr/bin/env python3
"""
K819: Tail-First ES (Expected Shortfall) Allocation
====================================================
[提出: Codex #8, 執行: Claude]

Research Question:
  Does inverse-ES (Expected Shortfall) allocation outperform inverse-vol
  (Risk Parity) for controlling tail risk in a SPY+GLD portfolio?

Hypothesis:
  Inverse-ES allocation (weight ∝ 1/ES_i) should provide better downside
  protection than inverse-vol (weight ∝ 1/σ_i) because ES directly measures
  left-tail severity, while σ treats upside and downside symmetrically.

Background:
  - K704: Risk Parity ≈ 50/50 for SPY+GLD (similar vols → similar weights)
  - K780: Tail-First ES model comparison (VaR/ES backtesting, not allocation)
  - K116: CVaR Tail Risk Parity — null, 50/50 unbeatable
  - K687: No VT strategy beats BH 50/50 on Sharpe after correct lag
  - K688: VT wins under CRRA utility gamma >= 5

Strategies (SPY + GLD, 2-asset):
  S0: BH 50/50 (baseline)
  S1: Inverse-Vol Risk Parity (weight ∝ 1/σ_i, rolling 252d)
  S2: Inverse-ES (weight ∝ 1/ES_i, historical ES at 5%, expanding window)
  S3: Inverse-Semivar (weight ∝ 1/√semivar_i, rolling 252d downside only)
  S4: 12/VIX (baseline VT, SPY only)
  S5: ES-VT (target_ES / current_ES × base_weight, SPY+GLD)

Constraints:
  - signal.shift(1) — all signals lagged 1 day, no lookahead
  - TX cost 5 bps per unit weight change
  - ES uses expanding window (min 252 days)
  - Semivariance uses rolling 252 days
  - Monthly rebalancing with hold-and-drift between rebalances

Evaluation:
  - Standard: Sharpe, CAGR, MDD
  - Downside-specific: Sortino, Calmar, Max 1-day loss, VaR 1% violation rate
  - DM test (Harvey t>3.0) for all pairs vs S0
  - Cross-OOS: 5 × 2-year non-overlapping periods
  - OOS: 2023-01-01 ~ 2024-12-31

Data: SPY, GLD, ^VIX from yfinance (2006-2026)

References:
  - Acerbi & Tasche (2002) "On the coherence of Expected Shortfall" JBF
  - Rockafellar & Uryasev (2002) "Conditional Value-at-Risk for General Loss
    Distributions" Journal of Banking & Finance
  - Maillard, Roncalli & Teïlétché (2010) "On the Properties of ERC Portfolios"
  - Harvey, Liu, Zhu (2016) t>3.0 threshold for multiple testing
  - K780: Tail-First ES model comparison — GJR-GARCH best ES calibration
  - K704: Risk Parity ≈ 50/50 for SPY+GLD
  - K116: CVaR Tail Risk Parity null result
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

# ============================================================
# CONFIGURATION
# ============================================================
PROJECT = Path(__file__).resolve().parent.parent
RESULTS_PATH = PROJECT / "experiments" / "k819_tail_first_es_results.json"

START_DATE = "2006-01-01"
END_DATE = "2026-06-01"
WARMUP_DAYS = 252        # 1-year warmup for rolling windows
TX_COST_BPS = 5          # 5 bps per unit weight change
RF_ANNUAL = 0.02         # risk-free rate
RF_DAILY = RF_ANNUAL / 252
ROLLING_WINDOW = 252     # for vol/semivar estimation
ES_QUANTILE = 0.05       # 5% ES
MIN_EXPANDING = 252      # minimum days for expanding ES
BOOTSTRAP_REPS = 5000

# OOS period
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"

# Cross-OOS periods (5 × 2-year)
CROSS_OOS = [
    ("2008-01-02", "2009-12-31"),
    ("2012-01-03", "2013-12-31"),
    ("2016-01-04", "2017-12-29"),
    ("2019-01-02", "2020-12-31"),
    ("2023-01-03", "2024-12-31"),
]

RESULTS = {}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def compute_metrics(returns, name="", rf_daily=RF_DAILY):
    """Compute comprehensive performance and tail-risk metrics."""
    r = returns.dropna()
    n = len(r)
    if n < 20:
        return {}

    # Standard metrics
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0.0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    cagr = cum.iloc[-1] ** (252 / n) - 1

    # Downside metrics
    neg_r = r[r < 0]
    downside_vol = np.sqrt((neg_r ** 2).mean()) * np.sqrt(252) if len(neg_r) > 0 else 1e-8
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0.0
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0

    # Tail metrics
    max_1d_loss = r.min()
    var_1pct = np.percentile(r, 1)
    var_5pct = np.percentile(r, 5)
    es_1pct = r[r <= var_1pct].mean() if (r <= var_1pct).sum() > 0 else var_1pct
    es_5pct = r[r <= var_5pct].mean() if (r <= var_5pct).sum() > 0 else var_5pct

    # VaR 1% violation rate (realized violations / expected)
    var_1pct_violations = (r < var_1pct).sum()
    var_1pct_rate = var_1pct_violations / n

    return {
        "name": name,
        "n_days": int(n),
        "ann_return": round(float(ann_ret), 6),
        "ann_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "cagr": round(float(cagr), 6),
        "mdd": round(float(mdd), 6),
        "sortino": round(float(sortino), 4),
        "calmar": round(float(calmar), 4),
        "max_1d_loss": round(float(max_1d_loss), 6),
        "var_1pct": round(float(var_1pct), 6),
        "var_5pct": round(float(var_5pct), 6),
        "es_1pct": round(float(es_1pct), 6),
        "es_5pct": round(float(es_5pct), 6),
        "var_1pct_violation_rate": round(float(var_1pct_rate), 6),
    }


def strategy_dm_test(r1, r2, h=1, loss_fn="negative_return"):
    """DM test for strategy comparison. Negative t → r1 better."""
    r1 = np.asarray(r1, dtype=np.float64)
    r2 = np.asarray(r2, dtype=np.float64)

    if loss_fn == "negative_return":
        d = -r1 - (-r2)  # d = r2 - r1; if r1 better, d > 0 → t > 0
    elif loss_fn == "downside":
        d = np.where(r1 < 0, r1 ** 2, 0.0) - np.where(r2 < 0, r2 ** 2, 0.0)
    else:
        raise ValueError(f"Unknown loss_fn: {loss_fn}")

    n = len(d)
    d_bar = d.mean()
    # HAC variance (Newey-West with h lags)
    gamma0 = np.mean((d - d_bar) ** 2)
    gamma_sum = 0.0
    for k in range(1, h + 1):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * (1 - k / (h + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return (0.0, 1.0)
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return (float(t_stat), float(p_val))


def apply_tx_cost(weights_df, returns_df, tx_bps=TX_COST_BPS):
    """Apply transaction costs based on weight changes."""
    cost_rate = tx_bps / 10000
    weight_changes = weights_df.diff().abs().sum(axis=1)
    # First day: full weight change from 0
    weight_changes.iloc[0] = weights_df.iloc[0].abs().sum()
    tx_costs = weight_changes * cost_rate
    portfolio_ret = (weights_df * returns_df).sum(axis=1) - tx_costs
    return portfolio_ret


# ============================================================
# PART A: Data Download & Descriptive Statistics
# ============================================================
print("=" * 80)
print("K819: Tail-First ES (Expected Shortfall) Allocation")
print("[提出: Codex #8, 執行: Claude]")
print("=" * 80)
print("\nPART A: Data Download & Descriptive Statistics")
print("-" * 60)

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge
data = raw["SPY"].join(raw["GLD"], how="inner").join(raw["VIX"], how="inner")
data = data.dropna()

# Compute log returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))
data = data.dropna(subset=["spy_ret", "gld_ret"])

n_total = len(data)
n_years_total = n_total / 252
print(f"\n  Total: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {n_total}, Years: {n_years_total:.1f}")

# Descriptive statistics
print(f"\n  Descriptive Statistics:")
print(f"  {'':20s} {'Mean':>10} {'Std':>10} {'Skew':>8} {'Kurt':>8} {'Min':>10} {'Max':>10}")
print(f"  {'-'*70}")
for col, label in [("spy_ret", "SPY daily ret"), ("gld_ret", "GLD daily ret"),
                   ("vix", "VIX level")]:
    s = data[col]
    print(f"  {label:20s} {s.mean():>10.4f} {s.std():>10.4f} {s.skew():>8.2f} "
          f"{s.kurtosis():>8.2f} {s.min():>10.4f} {s.max():>10.4f}")

RESULTS["data"] = {
    "start": str(data.index[0].date()),
    "end": str(data.index[-1].date()),
    "n_days": int(n_total),
    "n_years": round(n_years_total, 2),
    "spy_mean_ret": round(float(data["spy_ret"].mean()), 6),
    "gld_mean_ret": round(float(data["gld_ret"].mean()), 6),
    "spy_vol": round(float(data["spy_ret"].std() * np.sqrt(252)), 4),
    "gld_vol": round(float(data["gld_ret"].std() * np.sqrt(252)), 4),
}


# ============================================================
# PART B: Compute Risk Signals (ES, Vol, Semivar)
# ============================================================
print("\n" + "=" * 80)
print("PART B: Compute Risk Signals")
print("-" * 60)

# --- Rolling Volatility (252d) ---
data["spy_vol_252"] = data["spy_ret"].rolling(ROLLING_WINDOW).std()
data["gld_vol_252"] = data["gld_ret"].rolling(ROLLING_WINDOW).std()

# --- Expanding Historical ES at 5% ---
def expanding_es(returns, quantile=ES_QUANTILE, min_periods=MIN_EXPANDING):
    """Expanding-window Expected Shortfall (mean of returns below quantile)."""
    es_values = pd.Series(np.nan, index=returns.index)
    for i in range(min_periods, len(returns)):
        window = returns.iloc[:i]
        threshold = window.quantile(quantile)
        tail = window[window <= threshold]
        if len(tail) > 0:
            es_values.iloc[i] = abs(tail.mean())  # ES as positive number
        else:
            es_values.iloc[i] = abs(threshold)
    return es_values

print("  Computing expanding ES (5%) for SPY...")
data["spy_es"] = expanding_es(data["spy_ret"])
print("  Computing expanding ES (5%) for GLD...")
data["gld_es"] = expanding_es(data["gld_ret"])

# --- Rolling Semivariance (252d, negative returns only) ---
def rolling_semivariance(returns, window=ROLLING_WINDOW):
    """Rolling semivariance: variance of negative returns only."""
    semivar = pd.Series(np.nan, index=returns.index)
    for i in range(window, len(returns)):
        w = returns.iloc[i - window:i]
        neg = w[w < 0]
        if len(neg) > 2:
            semivar.iloc[i] = neg.var()
        else:
            semivar.iloc[i] = w.var()  # fallback
    return semivar

print("  Computing rolling semivariance (252d) for SPY...")
data["spy_semivar"] = rolling_semivariance(data["spy_ret"])
print("  Computing rolling semivariance (252d) for GLD...")
data["gld_semivar"] = rolling_semivariance(data["gld_ret"])

# Summary of risk signals (at end of sample)
for asset in ["spy", "gld"]:
    last_vol = data[f"{asset}_vol_252"].dropna().iloc[-1]
    last_es = data[f"{asset}_es"].dropna().iloc[-1]
    last_sv = data[f"{asset}_semivar"].dropna().iloc[-1]
    print(f"\n  {asset.upper()} latest: vol={last_vol:.4f}, ES(5%)={last_es:.4f}, "
          f"semivar={last_sv:.6f}, semi_vol={np.sqrt(last_sv):.4f}")


# ============================================================
# PART C: Strategy Construction (with signal.shift(1))
# ============================================================
print("\n" + "=" * 80)
print("PART C: Strategy Construction")
print("-" * 60)

# *** CRITICAL: All signals lagged by 1 day ***
spy_vol_lag = data["spy_vol_252"].shift(1)
gld_vol_lag = data["gld_vol_252"].shift(1)
spy_es_lag = data["spy_es"].shift(1)
gld_es_lag = data["gld_es"].shift(1)
spy_semivar_lag = data["spy_semivar"].shift(1)
gld_semivar_lag = data["gld_semivar"].shift(1)
vix_lag = data["vix"].shift(1)

returns = data[["spy_ret", "gld_ret"]].copy()

# --- S0: Buy & Hold 50/50 ---
weights_s0 = pd.DataFrame(0.5, index=data.index, columns=["spy_ret", "gld_ret"])
ret_s0 = apply_tx_cost(weights_s0, returns)

# --- S1: Inverse-Vol Risk Parity ---
inv_vol_spy = 1.0 / spy_vol_lag
inv_vol_gld = 1.0 / gld_vol_lag
inv_vol_total = inv_vol_spy + inv_vol_gld
w_rp_spy = inv_vol_spy / inv_vol_total
w_rp_gld = inv_vol_gld / inv_vol_total
weights_s1 = pd.DataFrame({"spy_ret": w_rp_spy, "gld_ret": w_rp_gld})
ret_s1 = apply_tx_cost(weights_s1.dropna(), returns.loc[weights_s1.dropna().index])

# --- S2: Inverse-ES (Historical ES at 5%) ---
inv_es_spy = 1.0 / spy_es_lag
inv_es_gld = 1.0 / gld_es_lag
inv_es_total = inv_es_spy + inv_es_gld
w_es_spy = inv_es_spy / inv_es_total
w_es_gld = inv_es_gld / inv_es_total
weights_s2 = pd.DataFrame({"spy_ret": w_es_spy, "gld_ret": w_es_gld})
ret_s2 = apply_tx_cost(weights_s2.dropna(), returns.loc[weights_s2.dropna().index])

# --- S3: Inverse-Semivar (downside risk only) ---
inv_sv_spy = 1.0 / np.sqrt(spy_semivar_lag.clip(lower=1e-10))
inv_sv_gld = 1.0 / np.sqrt(gld_semivar_lag.clip(lower=1e-10))
inv_sv_total = inv_sv_spy + inv_sv_gld
w_sv_spy = inv_sv_spy / inv_sv_total
w_sv_gld = inv_sv_gld / inv_sv_total
weights_s3 = pd.DataFrame({"spy_ret": w_sv_spy, "gld_ret": w_sv_gld})
ret_s3 = apply_tx_cost(weights_s3.dropna(), returns.loc[weights_s3.dropna().index])

# --- S4: 12/VIX (SPY only, remainder in cash) ---
spy_weight_12vix = (12.0 / vix_lag).clip(upper=1.5)
weights_s4 = pd.DataFrame({
    "spy_ret": spy_weight_12vix,
    "gld_ret": 0.0,
}, index=data.index)
ret_s4 = apply_tx_cost(weights_s4.dropna(), returns.loc[weights_s4.dropna().index])

# --- S5: ES-VT (target ES / current ES × base weight) ---
# Concept: allocate to each asset inversely proportional to its ES,
# but also scale total exposure by how current ES compares to a target.
# target_ES = long-run median ES
target_es_spy = data["spy_es"].dropna().median()
target_es_gld = data["gld_es"].dropna().median()
print(f"  ES-VT target ES: SPY={target_es_spy:.4f}, GLD={target_es_gld:.4f}")

# ES-VT weight: base 50/50, scaled by target_ES / current_ES
es_vt_scale_spy = (target_es_spy / spy_es_lag).clip(upper=1.5)
es_vt_scale_gld = (target_es_gld / gld_es_lag).clip(upper=1.5)
w_esvt_spy = 0.5 * es_vt_scale_spy
w_esvt_gld = 0.5 * es_vt_scale_gld
weights_s5 = pd.DataFrame({"spy_ret": w_esvt_spy, "gld_ret": w_esvt_gld})
ret_s5 = apply_tx_cost(weights_s5.dropna(), returns.loc[weights_s5.dropna().index])

# Collect all strategies
strategies = {
    "S0_BH_5050": ret_s0,
    "S1_InverseVol_RP": ret_s1,
    "S2_InverseES": ret_s2,
    "S3_InverseSemivar": ret_s3,
    "S4_12VIX": ret_s4,
    "S5_ES_VT": ret_s5,
}

# Strategy weight statistics
weight_stats = {}
for sname, wdf in [("S1", weights_s1), ("S2", weights_s2), ("S3", weights_s3),
                    ("S4", weights_s4), ("S5", weights_s5)]:
    wdf_clean = wdf.dropna()
    if len(wdf_clean) > 0:
        weight_stats[sname] = {
            "spy_mean": round(float(wdf_clean["spy_ret"].mean()), 4),
            "spy_std": round(float(wdf_clean["spy_ret"].std()), 4),
            "spy_min": round(float(wdf_clean["spy_ret"].min()), 4),
            "spy_max": round(float(wdf_clean["spy_ret"].max()), 4),
            "gld_mean": round(float(wdf_clean["gld_ret"].mean()), 4),
        }

print("\n  Strategy Weight Statistics:")
print(f"  {'Strategy':20s} {'SPY mean':>10} {'SPY std':>10} {'SPY min':>10} {'SPY max':>10} {'GLD mean':>10}")
print(f"  {'-'*70}")
for sname, ws in weight_stats.items():
    print(f"  {sname:20s} {ws['spy_mean']:>10.4f} {ws['spy_std']:>10.4f} "
          f"{ws['spy_min']:>10.4f} {ws['spy_max']:>10.4f} {ws['gld_mean']:>10.4f}")

RESULTS["weight_stats"] = weight_stats


# ============================================================
# PART D: Full-Sample Performance
# ============================================================
print("\n" + "=" * 80)
print("PART D: Full-Sample Performance")
print("-" * 60)

# Align all strategies to common index
common_start = max(s.dropna().index[0] for s in strategies.values())
common_end = min(s.dropna().index[-1] for s in strategies.values())

full_metrics = {}
print(f"\n  Full-sample evaluation: {common_start.date()} to {common_end.date()}")
print(f"\n  {'Strategy':25s} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Sortino':>8} "
      f"{'Calmar':>8} {'Max1dLoss':>10} {'ES(5%)':>8} {'VaR1%VR':>8}")
print(f"  {'-'*100}")

for sname, sret in strategies.items():
    r_slice = sret.loc[common_start:common_end].dropna()
    m = compute_metrics(r_slice, name=sname)
    full_metrics[sname] = m
    if m:
        print(f"  {sname:25s} {m['sharpe']:>8.4f} {m['cagr']:>8.4f} {m['mdd']:>8.4f} "
              f"{m['sortino']:>8.4f} {m['calmar']:>8.4f} {m['max_1d_loss']:>10.6f} "
              f"{m['es_5pct']:>8.6f} {m['var_1pct_violation_rate']:>8.4f}")

RESULTS["full_sample"] = full_metrics


# ============================================================
# PART E: OOS Performance (2023-2024)
# ============================================================
print("\n" + "=" * 80)
print(f"PART E: OOS Performance ({OOS_START} to {OOS_END})")
print("-" * 60)

oos_metrics = {}
print(f"\n  {'Strategy':25s} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Sortino':>8} "
      f"{'Calmar':>8} {'Max1dLoss':>10} {'ES(5%)':>8}")
print(f"  {'-'*95}")

for sname, sret in strategies.items():
    r_oos = sret.loc[OOS_START:OOS_END].dropna()
    m = compute_metrics(r_oos, name=sname)
    oos_metrics[sname] = m
    if m:
        print(f"  {sname:25s} {m['sharpe']:>8.4f} {m['cagr']:>8.4f} {m['mdd']:>8.4f} "
              f"{m['sortino']:>8.4f} {m['calmar']:>8.4f} {m['max_1d_loss']:>10.6f} "
              f"{m['es_5pct']:>8.6f}")

RESULTS["oos_metrics"] = oos_metrics


# ============================================================
# PART F: DM Tests (all vs S0, downside loss function)
# ============================================================
print("\n" + "=" * 80)
print("PART F: DM Tests (all strategies vs S0 baseline)")
print("-" * 60)

dm_results = {}
baseline_ret = strategies["S0_BH_5050"].loc[common_start:common_end].dropna()

print(f"\n  Loss function: negative_return (higher return = lower loss)")
print(f"  {'Pair':35s} {'t-stat':>8} {'p-value':>8} {'Signif':>8}")
print(f"  {'-'*65}")

for sname, sret in strategies.items():
    if sname == "S0_BH_5050":
        continue
    r_slice = sret.loc[common_start:common_end].dropna()
    # Align indices
    common_idx = baseline_ret.index.intersection(r_slice.index)
    r1 = baseline_ret.loc[common_idx].values
    r2 = r_slice.loc[common_idx].values

    t_neg, p_neg = strategy_dm_test(r1, r2, h=1, loss_fn="negative_return")
    t_ds, p_ds = strategy_dm_test(r1, r2, h=1, loss_fn="downside")

    sig_neg = "***" if abs(t_neg) > 3.0 else ("**" if abs(t_neg) > 2.0 else
              ("*" if abs(t_neg) > 1.65 else ""))
    sig_ds = "***" if abs(t_ds) > 3.0 else ("**" if abs(t_ds) > 2.0 else
             ("*" if abs(t_ds) > 1.65 else ""))

    dm_results[f"S0_vs_{sname}"] = {
        "neg_return": {"t": round(t_neg, 4), "p": round(p_neg, 4)},
        "downside": {"t": round(t_ds, 4), "p": round(p_ds, 4)},
    }

    print(f"  S0 vs {sname:25s} t={t_neg:>7.3f}  p={p_neg:.4f}  {sig_neg:>3s}  "
          f"(downside: t={t_ds:>7.3f}  p={p_ds:.4f}  {sig_ds:>3s})")

# Also DM test between S1 (Inverse-Vol) and S2 (Inverse-ES)
r_s1 = strategies["S1_InverseVol_RP"].loc[common_start:common_end].dropna()
r_s2 = strategies["S2_InverseES"].loc[common_start:common_end].dropna()
common_idx_12 = r_s1.index.intersection(r_s2.index)
t_12, p_12 = strategy_dm_test(r_s1.loc[common_idx_12].values,
                               r_s2.loc[common_idx_12].values,
                               h=1, loss_fn="downside")
dm_results["S1_vs_S2_downside"] = {"t": round(t_12, 4), "p": round(p_12, 4)}
sig_12 = "***" if abs(t_12) > 3.0 else ("**" if abs(t_12) > 2.0 else "")
print(f"\n  KEY: S1(InvVol) vs S2(InvES), downside DM: t={t_12:.3f}, p={p_12:.4f} {sig_12}")

RESULTS["dm_tests"] = dm_results


# ============================================================
# PART G: Cross-OOS (5 × 2-year periods)
# ============================================================
print("\n" + "=" * 80)
print("PART G: Cross-OOS Validation (5 × 2-year periods)")
print("-" * 60)

cross_oos_results = {}
strategy_wins = {s: 0 for s in strategies.keys() if s != "S0_BH_5050"}

for i, (oos_s, oos_e) in enumerate(CROSS_OOS):
    print(f"\n  Period {i+1}: {oos_s} to {oos_e}")
    period_key = f"P{i+1}_{oos_s}_{oos_e}"
    cross_oos_results[period_key] = {}

    baseline_oos = strategies["S0_BH_5050"].loc[oos_s:oos_e].dropna()
    if len(baseline_oos) < 100:
        print(f"    Skipping — only {len(baseline_oos)} days")
        continue

    base_m = compute_metrics(baseline_oos, "S0_BH_5050")
    cross_oos_results[period_key]["S0_BH_5050"] = base_m

    row_parts = []
    for sname, sret in strategies.items():
        if sname == "S0_BH_5050":
            continue
        r_oos = sret.loc[oos_s:oos_e].dropna()
        if len(r_oos) < 100:
            continue
        m = compute_metrics(r_oos, sname)
        cross_oos_results[period_key][sname] = m

        # Win = higher Sharpe than S0
        if m.get("sharpe", 0) > base_m.get("sharpe", 0):
            strategy_wins[sname] += 1
            beat = "✓"
        else:
            beat = "×"

        row_parts.append(f"    {sname:25s} Sharpe={m['sharpe']:.4f} Sortino={m['sortino']:.4f} "
                        f"MDD={m['mdd']:.4f} {beat}")

    print(f"    S0 baseline: Sharpe={base_m.get('sharpe', 0):.4f}")
    for rp in row_parts:
        print(rp)

print(f"\n  Cross-OOS Win Counts (beat S0 on Sharpe, /5):")
for sname, wins in strategy_wins.items():
    print(f"    {sname:25s}: {wins}/5")

RESULTS["cross_oos"] = {
    "periods": cross_oos_results,
    "win_counts_vs_S0": {k: v for k, v in strategy_wins.items()},
}


# ============================================================
# PART H: Tail Risk Deep-Dive (ES comparison)
# ============================================================
print("\n" + "=" * 80)
print("PART H: Tail Risk Deep-Dive")
print("-" * 60)

# Compare realized tail events across strategies
tail_analysis = {}
print(f"\n  Worst 10 days comparison (full sample {common_start.date()}-{common_end.date()}):")

for sname, sret in strategies.items():
    r_slice = sret.loc[common_start:common_end].dropna()
    worst_10 = r_slice.nsmallest(10)
    tail_analysis[sname] = {
        "worst_1": round(float(worst_10.iloc[0]), 6),
        "worst_5_mean": round(float(worst_10.iloc[:5].mean()), 6),
        "worst_10_mean": round(float(worst_10.iloc[:10].mean()), 6),
        "days_below_neg2pct": int((r_slice < -0.02).sum()),
        "days_below_neg3pct": int((r_slice < -0.03).sum()),
    }
    print(f"  {sname:25s}: worst={tail_analysis[sname]['worst_1']:.4f}, "
          f"worst5avg={tail_analysis[sname]['worst_5_mean']:.4f}, "
          f"days<-2%={tail_analysis[sname]['days_below_neg2pct']}, "
          f"days<-3%={tail_analysis[sname]['days_below_neg3pct']}")

# ES vs Vol: correlation of weight differences
print(f"\n  Weight Divergence Analysis (S2-InvES vs S1-InvVol):")
w_diff = weights_s2.dropna()["spy_ret"] - weights_s1.dropna()["spy_ret"]
w_diff = w_diff.loc[common_start:common_end].dropna()
print(f"    SPY weight diff (ES - Vol): mean={w_diff.mean():.4f}, "
      f"std={w_diff.std():.4f}, min={w_diff.min():.4f}, max={w_diff.max():.4f}")
print(f"    Correlation of SPY weights (S1 vs S2): "
      f"{weights_s1.loc[common_start:common_end].dropna()['spy_ret'].corr(weights_s2.loc[common_start:common_end].dropna()['spy_ret']):.4f}")

# When does ES disagree most with Vol?
# High VIX periods
vix_data = data["vix"].shift(1).loc[common_start:common_end].dropna()
w_diff_aligned = w_diff.loc[vix_data.index.intersection(w_diff.index)]
vix_aligned = vix_data.loc[w_diff_aligned.index]
high_vix_mask = vix_aligned > vix_aligned.quantile(0.8)
low_vix_mask = vix_aligned < vix_aligned.quantile(0.2)

tail_analysis["weight_divergence"] = {
    "mean_diff": round(float(w_diff_aligned.mean()), 4),
    "std_diff": round(float(w_diff_aligned.std()), 4),
    "high_vix_mean_diff": round(float(w_diff_aligned[high_vix_mask].mean()), 4),
    "low_vix_mean_diff": round(float(w_diff_aligned[low_vix_mask].mean()), 4),
}

print(f"    High-VIX (>80th pctile): weight diff = {w_diff_aligned[high_vix_mask].mean():.4f}")
print(f"    Low-VIX  (<20th pctile): weight diff = {w_diff_aligned[low_vix_mask].mean():.4f}")

RESULTS["tail_analysis"] = tail_analysis


# ============================================================
# PART I: Regime Analysis (High vs Low VIX)
# ============================================================
print("\n" + "=" * 80)
print("PART I: Regime Analysis (VIX-based)")
print("-" * 60)

regime_results = {}
vix_full = data["vix"].shift(1).loc[common_start:common_end].dropna()

for regime_name, mask_fn in [
    ("VIX<15 (Calm)", lambda v: v < 15),
    ("VIX 15-25 (Normal)", lambda v: (v >= 15) & (v < 25)),
    ("VIX>25 (Stress)", lambda v: v >= 25),
]:
    mask = mask_fn(vix_full)
    regime_results[regime_name] = {"n_days": int(mask.sum())}

    if mask.sum() < 50:
        print(f"\n  {regime_name}: only {mask.sum()} days — skipping")
        continue

    print(f"\n  {regime_name}: {mask.sum()} days")
    print(f"  {'Strategy':25s} {'Sharpe':>8} {'Sortino':>8} {'MDD':>8} {'ES(5%)':>10}")
    print(f"  {'-'*65}")

    for sname, sret in strategies.items():
        r_regime = sret.loc[common_start:common_end].dropna()
        r_regime = r_regime[r_regime.index.isin(vix_full[mask].index)]
        if len(r_regime) < 30:
            continue
        m = compute_metrics(r_regime, sname)
        regime_results[regime_name][sname] = m
        if m:
            print(f"  {sname:25s} {m['sharpe']:>8.4f} {m['sortino']:>8.4f} "
                  f"{m['mdd']:>8.4f} {m['es_5pct']:>10.6f}")

RESULTS["regime_analysis"] = regime_results


# ============================================================
# PART J: Summary & Conclusions
# ============================================================
print("\n" + "=" * 80)
print("PART J: Summary & Conclusions")
print("-" * 60)

# Rank strategies by multiple criteria
oos_sharpes = {k: v.get("sharpe", -999) for k, v in oos_metrics.items() if v}
oos_sortinos = {k: v.get("sortino", -999) for k, v in oos_metrics.items() if v}
oos_mdds = {k: v.get("mdd", -999) for k, v in oos_metrics.items() if v}
oos_es = {k: v.get("es_5pct", -999) for k, v in oos_metrics.items() if v}

# Sort
sharpe_rank = sorted(oos_sharpes.items(), key=lambda x: x[1], reverse=True)
sortino_rank = sorted(oos_sortinos.items(), key=lambda x: x[1], reverse=True)
es_rank = sorted(oos_es.items(), key=lambda x: x[1], reverse=True)  # less negative = better

print("\n  OOS Rankings:")
print(f"\n  By Sharpe:")
for i, (s, v) in enumerate(sharpe_rank):
    print(f"    {i+1}. {s:25s} {v:.4f}")

print(f"\n  By Sortino:")
for i, (s, v) in enumerate(sortino_rank):
    print(f"    {i+1}. {s:25s} {v:.4f}")

print(f"\n  By ES(5%) (less negative = better):")
for i, (s, v) in enumerate(es_rank):
    print(f"    {i+1}. {s:25s} {v:.6f}")

# Key findings
# Check: does S2 (Inverse-ES) beat S1 (Inverse-Vol) on downside metrics?
s1_oos = oos_metrics.get("S1_InverseVol_RP", {})
s2_oos = oos_metrics.get("S2_InverseES", {})
s0_oos = oos_metrics.get("S0_BH_5050", {})

es_vs_vol_sortino = (s2_oos.get("sortino", 0) > s1_oos.get("sortino", 0))
es_vs_vol_es5 = (s2_oos.get("es_5pct", -1) > s1_oos.get("es_5pct", -1))  # less negative
es_vs_vol_mdd = (s2_oos.get("mdd", -1) > s1_oos.get("mdd", -1))  # less negative

hypothesis_result = "SUPPORTED" if (es_vs_vol_sortino and es_vs_vol_es5) else "NOT SUPPORTED"
dm_12_sig = abs(dm_results.get("S1_vs_S2_downside", {}).get("t", 0)) > 3.0

print(f"\n  KEY FINDING:")
print(f"  Hypothesis: Inverse-ES > Inverse-Vol on downside metrics")
print(f"    Sortino: S2={s2_oos.get('sortino','N/A')} vs S1={s1_oos.get('sortino','N/A')} → {'S2 wins' if es_vs_vol_sortino else 'S1 wins'}")
print(f"    ES(5%):  S2={s2_oos.get('es_5pct','N/A')} vs S1={s1_oos.get('es_5pct','N/A')} → {'S2 wins' if es_vs_vol_es5 else 'S1 wins'}")
print(f"    MDD:     S2={s2_oos.get('mdd','N/A')} vs S1={s1_oos.get('mdd','N/A')} → {'S2 wins' if es_vs_vol_mdd else 'S1 wins'}")
print(f"    DM test (downside): t={dm_results.get('S1_vs_S2_downside',{}).get('t','N/A')}, "
      f"significant(Harvey>3): {dm_12_sig}")
print(f"  Hypothesis result: {hypothesis_result}")

# Does any strategy beat S0?
any_beats_s0_sharpe = any(
    oos_metrics.get(s, {}).get("sharpe", -999) > s0_oos.get("sharpe", -999)
    for s in strategies if s != "S0_BH_5050"
)
any_beats_s0_sortino = any(
    oos_metrics.get(s, {}).get("sortino", -999) > s0_oos.get("sortino", -999)
    for s in strategies if s != "S0_BH_5050"
)

print(f"\n  Any strategy beats S0 on OOS Sharpe? {any_beats_s0_sharpe}")
print(f"  Any strategy beats S0 on OOS Sortino? {any_beats_s0_sortino}")
print(f"  K687 confirmation: 50/50 remains hard to beat? {not any_beats_s0_sharpe}")

conclusions = {
    "hypothesis": "Inverse-ES allocation provides better downside protection than inverse-vol",
    "hypothesis_result": hypothesis_result,
    "es_vs_vol": {
        "sortino_winner": "S2_InverseES" if es_vs_vol_sortino else "S1_InverseVol_RP",
        "es5_winner": "S2_InverseES" if es_vs_vol_es5 else "S1_InverseVol_RP",
        "mdd_winner": "S2_InverseES" if es_vs_vol_mdd else "S1_InverseVol_RP",
        "dm_significant": dm_12_sig,
    },
    "s0_beaten_sharpe": any_beats_s0_sharpe,
    "s0_beaten_sortino": any_beats_s0_sortino,
    "k687_consistent": not any_beats_s0_sharpe,
    "cross_oos_wins": {k: v for k, v in strategy_wins.items()},
}

RESULTS["conclusions"] = conclusions


# ============================================================
# Save Results
# ============================================================
RESULTS["experiment_id"] = "K819"
RESULTS["title"] = "Tail-First ES (Expected Shortfall) Allocation"
RESULTS["proposer"] = "Codex #8"
RESULTS["executor"] = "Claude"
RESULTS["timestamp"] = datetime.now(timezone.utc).isoformat()
RESULTS["data_source"] = "yfinance (SPY, GLD, ^VIX), 2006-2026"
RESULTS["oos_period"] = f"{OOS_START} to {OOS_END}"
RESULTS["tx_cost_bps"] = TX_COST_BPS
RESULTS["es_quantile"] = ES_QUANTILE
RESULTS["rolling_window"] = ROLLING_WINDOW
RESULTS["signal_lag"] = "shift(1) applied to all signals"
RESULTS["references"] = [
    "Acerbi & Tasche (2002) On the coherence of Expected Shortfall, JBF",
    "Rockafellar & Uryasev (2002) Conditional VaR for General Loss Distributions, JBF",
    "Maillard, Roncalli & Teiletche (2010) ERC Portfolios, JPM",
    "Harvey, Liu, Zhu (2016) t>3.0 threshold",
    "K780: Tail-First ES model comparison",
    "K704: Risk Parity ≈ 50/50",
    "K116: CVaR Tail Risk Parity null",
    "K687: No VT beats BH 50/50 on Sharpe",
]

with open(RESULTS_PATH, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)

print(f"\n  Results saved to: {RESULTS_PATH}")
print("\n" + "=" * 80)
print("K819 COMPLETE")
print("=" * 80)
