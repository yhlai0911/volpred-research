#!/usr/bin/env python3
"""K603: Dynamic Target Volatility — Should the "12" in 12/VIX Change with Market Conditions?
================================================================================================

Motivation:
    K550 showed fixed threshold 10-16 all similar (flat curve).
    K568 showed 12/VIX is return-optimal among function shapes.
    K4 tested dynamic target vol but was early-phase (single asset, no cross-OOS).
    NEITHER tested with: multi-asset portfolio, rate-adjustment, cross-OOS validation.

    Key insight: "12/VIX" means target vol = 12% annualized. But:
    - In low-rate environments (2010-2021), 12% was reasonable
    - In high-rate environments (2022+), risk-free earns 4-5%, so opportunity cost differs
    - In crisis recovery, higher target might capture more upside

Design:
    1. Data: SPY + GLD + VIX + ^IRX (T-bill rate) from yfinance (2005-2026)
    2. Strategies (all applied to 50/50 SPY/GLD):
       a. Fixed target 12% (baseline = 12/VIX)
       b. Rate-adjusted: target = 12% + (rf - 2%) — higher rates -> higher target
       c. VIX-regime adjusted: VIX<15->15%, VIX 15-25->12%, VIX>25->10%
       d. Rolling Sharpe: target = 12% * (rolling_252d_sharpe / mean_sharpe), clipped [6,20]
       e. Inverse VIX percentile: target = 8% + 8% * (1 - VIX_pctile_252d), clipped [6,20]
    3. Cross-OOS: 5 non-overlapping periods
    4. Harvey (2016) t>3.0 threshold via Diebold-Mariano test
    5. Bootstrap inference (5000 reps)

References:
    - K4: Dynamic target vol (early phase, single asset, null result)
    - K550: Adaptive VIX Threshold (10-16 all similar)
    - K568: Optimal Weight Function (12/VIX return-optimal)
    - Moreira & Muir (2017, JoF): Volatility-managed portfolios
    - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
    - Harvey (2016, JoF): t>3 threshold for new factors
    - Hocquard, Ng & Papageorgiou (2013): Constant proportion portfolio insurance with target vol

Data source: yfinance (SPY, GLD, ^VIX, ^IRX)
Period: 2005-2026 (~21 years)
Author: [Proposed: User, Executed: Claude]
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants & Configuration
# ============================================================
RF_ANNUAL = 0.02  # default risk-free for Sharpe
ANNUALIZE = np.sqrt(252)
N_BOOTSTRAP = 5000
MAX_LEVERAGE = 2.0   # cap leverage at 2x
MIN_WEIGHT = 0.0     # no shorting
FALLBACK_RF = 0.04   # fallback if ^IRX unavailable
np.random.seed(42)

# Cross-OOS: 5 non-overlapping ~4-year periods
OOS_PERIODS = [
    ("P1_2005_2009", "2005-06-01", "2009-05-31"),  # includes GFC
    ("P2_2009_2013", "2009-06-01", "2013-05-31"),  # post-GFC recovery
    ("P3_2013_2017", "2013-06-01", "2017-05-31"),  # low-vol bull
    ("P4_2017_2021", "2017-06-01", "2021-05-31"),  # COVID + recovery
    ("P5_2021_2026", "2021-06-01", "2026-03-28"),  # rate hiking + normalization
]

# ============================================================
#  Data Loading
# ============================================================
def load_data():
    """Load SPY, GLD, VIX, IRX from yfinance and build daily returns."""
    print("Loading data from yfinance...")
    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX", "IRX": "^IRX"}

    frames = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start="2004-11-01", end="2026-03-28",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        frames[name] = df["Close"].rename(name)

    data = pd.concat(frames.values(), axis=1).dropna(subset=["SPY", "GLD", "VIX"])

    # Fill IRX forward (it has more missing days)
    if "IRX" in data.columns:
        data["IRX"] = data["IRX"].ffill()
        # IRX is in percentage points (e.g., 4.5 = 4.5%), convert to decimal
        data["rf_daily"] = data["IRX"] / 100 / 252
    else:
        data["rf_daily"] = FALLBACK_RF / 252

    # Daily returns
    data["ret_SPY"] = np.log(data["SPY"] / data["SPY"].shift(1))
    data["ret_GLD"] = np.log(data["GLD"] / data["GLD"].shift(1))

    # Portfolio return (50/50)
    data["ret_port"] = 0.5 * data["ret_SPY"] + 0.5 * data["ret_GLD"]

    # Rolling stats for strategies
    data["rolling_sharpe_252"] = (
        data["ret_port"].rolling(252).mean() / data["ret_port"].rolling(252).std()
    )
    data["mean_sharpe_expanding"] = data["rolling_sharpe_252"].expanding().mean()

    # VIX percentile (rolling 252-day)
    data["vix_pctile_252"] = data["VIX"].rolling(252).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
    )

    # Annualized risk-free rate for rate-adjusted strategy
    if "IRX" in data.columns:
        data["rf_annual"] = data["IRX"] / 100
    else:
        data["rf_annual"] = FALLBACK_RF

    data = data.dropna(subset=["ret_SPY", "ret_GLD"]).copy()
    print(f"  Data loaded: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}, N={len(data)}")

    return data


# ============================================================
#  Strategy Functions — each returns a dynamic target vol series
# ============================================================
def target_fixed(data, target=0.12):
    """Fixed target vol (baseline)."""
    return pd.Series(target, index=data.index, name="Fixed_12")


def target_rate_adjusted(data, base=0.12, ref_rate=0.02):
    """Rate-adjusted: target = base + (rf - ref_rate).
    Higher rates -> higher target (compensate for cash yield).
    Clipped to [6%, 20%].
    """
    rf = data["rf_annual"].fillna(ref_rate)
    target = base + (rf - ref_rate)
    return target.clip(0.06, 0.20).rename("Rate_Adj")


def target_vix_regime(data):
    """VIX-regime adjusted: VIX<15->15%, 15-25->12%, >25->10%."""
    vix = data["VIX"]
    target = pd.Series(0.12, index=data.index)
    target[vix < 15] = 0.15
    target[vix > 25] = 0.10
    return target.rename("VIX_Regime")


def target_rolling_sharpe(data, base=0.12):
    """Rolling Sharpe: target = base * (rolling_sharpe / mean_sharpe), clipped [6,20]%.
    Good recent performance -> higher target; poor -> lower.
    """
    ratio = data["rolling_sharpe_252"] / data["mean_sharpe_expanding"]
    ratio = ratio.fillna(1.0).replace([np.inf, -np.inf], 1.0)
    target = base * ratio
    return target.clip(0.06, 0.20).rename("Roll_Sharpe")


def target_inv_vix_pctile(data):
    """Inverse VIX percentile: target = 8% + 8% * (1 - VIX_pctile).
    High VIX (high percentile) -> low target; low VIX -> high target.
    Range: [8%, 16%].
    """
    pctile = data["vix_pctile_252"].fillna(0.5)
    target = 0.08 + 0.08 * (1 - pctile)
    return target.clip(0.06, 0.20).rename("Inv_VIX_Pct")


# ============================================================
#  VT Weight Calculation
# ============================================================
def compute_vt_weights(data, target_series):
    """Compute VT weights: w = target / (VIX/100).
    VIX is annualized %, so VIX/100 is the annualized vol estimate.
    Clipped to [0, MAX_LEVERAGE].
    """
    vix_vol = data["VIX"] / 100  # Convert VIX to decimal
    weight = target_series / vix_vol
    return weight.clip(MIN_WEIGHT, MAX_LEVERAGE)


# ============================================================
#  Backtest
# ============================================================
def backtest_strategy(data, weights, name, tx_cost=0.001):
    """Run backtest for a VT strategy with transaction costs."""
    # Strategy return: w * port_return + (1-w) * rf
    w = weights.shift(1)  # use previous day's weight (no look-ahead)
    ret_strat = w * data["ret_port"] + (1 - w) * data["rf_daily"]

    # Transaction costs
    turnover = w.diff().abs()
    ret_strat = ret_strat - turnover * tx_cost

    # Drop NaN
    ret_strat = ret_strat.dropna()

    if len(ret_strat) < 252:
        return {"name": name, "error": "insufficient data"}

    # Metrics
    ann_ret = ret_strat.mean() * 252
    ann_vol = ret_strat.std() * ANNUALIZE
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    cum = np.exp(ret_strat.cumsum())
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    downside_vol = ret_strat[ret_strat < 0].std() * ANNUALIZE
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    avg_turnover = turnover.mean() * 252
    avg_weight = w.mean()

    return {
        "name": name,
        "ann_return": round(float(ann_ret), 6),
        "ann_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "max_dd": round(float(max_dd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "avg_turnover": round(float(avg_turnover), 4),
        "avg_weight": round(float(avg_weight), 4),
        "n_days": len(ret_strat),
        "ret_series": ret_strat,
    }


def backtest_bh(data):
    """Buy-and-hold 50/50 SPY/GLD benchmark."""
    ret = data["ret_port"].dropna()
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * ANNUALIZE
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    cum = np.exp(ret.cumsum())
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    downside_vol = ret[ret < 0].std() * ANNUALIZE
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    return {
        "name": "Buy_Hold",
        "ann_return": round(float(ann_ret), 6),
        "ann_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "max_dd": round(float(max_dd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "avg_turnover": 0.0,
        "avg_weight": 1.0,
        "n_days": len(ret),
        "ret_series": ret,
    }


# ============================================================
#  Statistical Tests
# ============================================================
def dm_test(e1, e2, h=1):
    """Diebold-Mariano test comparing return differences.
    Positive t -> e2 has higher returns.
    """
    d = e2 - e1
    d = d.dropna()
    n = len(d)
    if n < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "n": n}

    d_mean = d.mean()
    gamma0 = d.var()
    if gamma0 == 0:
        return {"t_stat": 0.0, "p_value": 1.0, "n": n}

    t_stat = d_mean / np.sqrt(gamma0 / n)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    return {
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 6),
        "n": n,
    }


def jkm_sharpe_test(ret1, ret2):
    """Jobson-Korkie-Memmel test for equality of Sharpe ratios."""
    r1, r2 = ret1.align(ret2, join="inner")
    r1, r2 = r1.dropna(), r2.dropna()
    idx = r1.index.intersection(r2.index)
    r1, r2 = r1.loc[idx], r2.loc[idx]

    n = len(r1)
    if n < 30:
        return {"z_stat": np.nan, "p_value": np.nan}

    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(), r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]

    sr1 = mu1 / s1 if s1 > 0 else 0
    sr2 = mu2 / s2 if s2 > 0 else 0

    # Memmel (2003) correction
    theta = (1/n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2*sr1*sr2*rho))

    if theta <= 0:
        return {"z_stat": 0.0, "p_value": 1.0}

    z = (sr2 - sr1) / np.sqrt(theta)
    p = 2 * (1 - stats.norm.cdf(abs(z)))

    return {"z_stat": round(float(z), 4), "p_value": round(float(p), 6)}


def bootstrap_sharpe(ret, n_boot=N_BOOTSTRAP):
    """Block bootstrap Sharpe ratio CI."""
    block_size = 21  # monthly blocks
    n = len(ret)
    vals = ret.values
    sharpes = []

    for _ in range(n_boot):
        n_blocks = n // block_size + 1
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        boot = np.concatenate([vals[s:s+block_size] for s in starts])[:n]

        mu = boot.mean() * 252
        sigma = boot.std() * ANNUALIZE
        if sigma > 0:
            sharpes.append((mu - RF_ANNUAL) / sigma)

    sharpes = np.array(sharpes)
    return {
        "mean": round(float(sharpes.mean()), 4),
        "ci_lo": round(float(np.percentile(sharpes, 2.5)), 4),
        "ci_hi": round(float(np.percentile(sharpes, 97.5)), 4),
        "std": round(float(sharpes.std()), 4),
    }


def bootstrap_comparison(ret1, ret2, n_boot=N_BOOTSTRAP):
    """Bootstrap P(strategy2 > strategy1) in Sharpe."""
    block_size = 21
    r1, r2 = ret1.align(ret2, join="inner")
    idx = r1.dropna().index.intersection(r2.dropna().index)
    v1, v2 = r1.loc[idx].values, r2.loc[idx].values
    n = len(v1)

    wins = 0
    for _ in range(n_boot):
        n_blocks = n // block_size + 1
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        b1 = np.concatenate([v1[s:s+block_size] for s in starts])[:n]
        b2 = np.concatenate([v2[s:s+block_size] for s in starts])[:n]

        s1 = b1.std() * ANNUALIZE
        s2 = b2.std() * ANNUALIZE
        sr1 = (b1.mean() * 252 - RF_ANNUAL) / s1 if s1 > 0 else 0
        sr2 = (b2.mean() * 252 - RF_ANNUAL) / s2 if s2 > 0 else 0

        if sr2 > sr1:
            wins += 1

    return {"p_win": round(wins / n_boot, 4)}


# ============================================================
#  Cross-OOS Evaluation
# ============================================================
def cross_oos(data, strategies, periods):
    """Run cross-OOS evaluation across multiple periods."""
    results = {}

    for period_name, start, end in periods:
        mask = (data.index >= start) & (data.index <= end)
        sub = data.loc[mask].copy()

        if len(sub) < 126:  # at least 6 months
            print(f"  {period_name}: insufficient data ({len(sub)} days), skipping")
            continue

        period_results = {}

        # Buy-and-hold
        bh = backtest_bh(sub)
        period_results["Buy_Hold"] = {k: v for k, v in bh.items() if k != "ret_series"}

        for name, target_fn in strategies.items():
            target_series = target_fn(sub)
            weights = compute_vt_weights(sub, target_series)
            result = backtest_strategy(sub, weights, name)
            period_results[name] = {k: v for k, v in result.items() if k != "ret_series"}

        results[period_name] = period_results
        print(f"  {period_name}: {len(sub)} days, "
              f"Fixed_12 Sharpe={period_results.get('Fixed_12', {}).get('sharpe', 'N/A')}, "
              f"B&H Sharpe={period_results['Buy_Hold']['sharpe']}")

    return results


# ============================================================
#  Crisis Analysis
# ============================================================
def crisis_analysis(data, strategies):
    """Analyze performance during specific crisis periods."""
    crises = {
        "GFC_2008": ("2008-09-01", "2009-03-31"),
        "COVID_2020": ("2020-02-19", "2020-03-23"),
        "Rate_Hike_2022": ("2022-01-01", "2022-10-31"),
        "Trump_Tariff_2025": ("2025-02-01", "2025-04-30"),
    }

    results = {}
    for crisis_name, (start, end) in crises.items():
        mask = (data.index >= start) & (data.index <= end)
        sub = data.loc[mask]

        if len(sub) < 5:
            continue

        crisis_res = {}

        # B&H
        bh_ret = sub["ret_port"].sum()
        crisis_res["Buy_Hold"] = {"cum_return": round(float(bh_ret), 4)}

        for name, target_fn in strategies.items():
            target_series = target_fn(sub)
            weights = compute_vt_weights(sub, target_series)
            w = weights.shift(1).fillna(weights.iloc[0])
            strat_ret = (w * sub["ret_port"] + (1 - w) * sub["rf_daily"]).sum()
            avg_w = w.mean()
            crisis_res[name] = {
                "cum_return": round(float(strat_ret), 4),
                "avg_weight": round(float(avg_w), 4),
                "avg_target": round(float(target_fn(sub).mean()), 4),
            }

        results[crisis_name] = crisis_res

    return results


# ============================================================
#  Target Vol Dynamics Analysis
# ============================================================
def target_dynamics_analysis(data, strategies):
    """Analyze how each target vol varies over time."""
    results = {}
    for name, target_fn in strategies.items():
        ts = target_fn(data)
        ac = ts.autocorr(1) if ts.std() > 0 else 1.0
        results[name] = {
            "mean": round(float(ts.mean()), 4),
            "std": round(float(ts.std()), 4),
            "min": round(float(ts.min()), 4),
            "max": round(float(ts.max()), 4),
            "pct_below_10": round(float((ts < 0.10).mean()), 4),
            "pct_above_14": round(float((ts > 0.14).mean()), 4),
            "autocorr_1d": round(float(ac), 4),
            "correlation_with_vix": round(float(ts.corr(data["VIX"])), 4),
        }
    return results


# ============================================================
#  Rate Environment Analysis
# ============================================================
def rate_environment_analysis(data, strategies):
    """Compare strategy performance across rate environments."""
    rf = data["rf_annual"].fillna(RF_ANNUAL)

    envs = {
        "low_rate_lt1pct": rf < 0.01,
        "mid_rate_1_3pct": (rf >= 0.01) & (rf < 0.03),
        "high_rate_gt3pct": rf >= 0.03,
    }

    results = {}
    for env_name, mask in envs.items():
        sub = data.loc[mask]
        if len(sub) < 126:
            continue

        env_res = {"n_days": len(sub), "avg_rf": round(float(rf[mask].mean()), 4)}

        for name, target_fn in strategies.items():
            ts = target_fn(sub)
            weights = compute_vt_weights(sub, ts)
            w = weights.shift(1).fillna(weights.iloc[0])
            strat_ret = w * sub["ret_port"] + (1 - w) * sub["rf_daily"]
            strat_ret = strat_ret.dropna()

            ann_r = strat_ret.mean() * 252
            ann_v = strat_ret.std() * ANNUALIZE
            sharpe = (ann_r - RF_ANNUAL) / ann_v if ann_v > 0 else 0

            env_res[name] = {
                "sharpe": round(float(sharpe), 4),
                "ann_return": round(float(ann_r), 6),
                "avg_target": round(float(ts.mean()), 4),
            }

        results[env_name] = env_res

    return results


# ============================================================
#  Main
# ============================================================
def main():
    print("=" * 80)
    print("K603: Dynamic Target Volatility")
    print("Should the '12' in 12/VIX change with market conditions?")
    print("=" * 80)

    # ---- Load Data ----
    data = load_data()

    # ---- Descriptive Statistics ----
    print("\n--- Descriptive Statistics ---")
    print(f"  SPY daily return: mean={data['ret_SPY'].mean()*252:.4f}, std={data['ret_SPY'].std()*ANNUALIZE:.4f}")
    print(f"  GLD daily return: mean={data['ret_GLD'].mean()*252:.4f}, std={data['ret_GLD'].std()*ANNUALIZE:.4f}")
    print(f"  Portfolio return:  mean={data['ret_port'].mean()*252:.4f}, std={data['ret_port'].std()*ANNUALIZE:.4f}")
    print(f"  VIX: mean={data['VIX'].mean():.2f}, std={data['VIX'].std():.2f}, min={data['VIX'].min():.2f}, max={data['VIX'].max():.2f}")

    irx_valid = data["IRX"].dropna()
    if len(irx_valid) > 0:
        print(f"  IRX (T-bill %): mean={irx_valid.mean():.2f}, min={irx_valid.min():.2f}, max={irx_valid.max():.2f}")

    # ---- Define Strategies ----
    strategies = {
        "Fixed_12": target_fixed,
        "Rate_Adj": target_rate_adjusted,
        "VIX_Regime": target_vix_regime,
        "Roll_Sharpe": target_rolling_sharpe,
        "Inv_VIX_Pct": target_inv_vix_pctile,
    }

    # ---- Target Dynamics ----
    print("\n--- Target Volatility Dynamics ---")
    target_dynamics = target_dynamics_analysis(data, strategies)
    for name, stats_d in target_dynamics.items():
        print(f"  {name:15s}: mean={stats_d['mean']:.4f}, std={stats_d['std']:.4f}, "
              f"range=[{stats_d['min']:.4f}, {stats_d['max']:.4f}], "
              f"corr(VIX)={stats_d['correlation_with_vix']:.4f}")

    # ---- Full-Sample Backtest ----
    print("\n--- Full-Sample Backtest ---")
    full_results = {}
    ret_series = {}

    # Buy and hold
    bh = backtest_bh(data)
    full_results["Buy_Hold"] = {k: v for k, v in bh.items() if k != "ret_series"}
    ret_series["Buy_Hold"] = bh["ret_series"]
    print(f"  Buy_Hold: Sharpe={bh['sharpe']:.4f}, Return={bh['ann_return']*100:.2f}%, "
          f"Vol={bh['ann_vol']*100:.2f}%, MDD={bh['max_dd']*100:.2f}%")

    for name, target_fn in strategies.items():
        target_series = target_fn(data)
        weights = compute_vt_weights(data, target_series)
        result = backtest_strategy(data, weights, name)
        full_results[name] = {k: v for k, v in result.items() if k != "ret_series"}
        ret_series[name] = result["ret_series"]
        print(f"  {name:15s}: Sharpe={result['sharpe']:.4f}, Return={result['ann_return']*100:.2f}%, "
              f"Vol={result['ann_vol']*100:.2f}%, MDD={result['max_dd']*100:.2f}%, "
              f"Turnover={result['avg_turnover']:.2f}")

    # ---- Statistical Tests vs Baseline (Fixed_12) ----
    print("\n--- Statistical Tests vs Fixed_12 (Baseline) ---")
    stat_tests = {}
    baseline_ret = ret_series["Fixed_12"]

    for name in ["Rate_Adj", "VIX_Regime", "Roll_Sharpe", "Inv_VIX_Pct"]:
        strat_ret = ret_series[name]

        dm = dm_test(baseline_ret, strat_ret)
        jkm = jkm_sharpe_test(baseline_ret, strat_ret)
        boot = bootstrap_comparison(baseline_ret, strat_ret)

        stat_tests[name] = {
            "dm_t": dm["t_stat"],
            "dm_p": dm["p_value"],
            "jkm_z": jkm["z_stat"],
            "jkm_p": jkm["p_value"],
            "boot_p_win": boot["p_win"],
        }

        harvey_pass = abs(dm["t_stat"]) > 3.0 if not np.isnan(dm["t_stat"]) else False
        print(f"  {name:15s}: DM t={dm['t_stat']:+.4f} (p={dm['p_value']:.4f}) "
              f"{'PASS' if harvey_pass else 'FAIL'} Harvey, "
              f"JKM z={jkm['z_stat']:+.4f}, Boot P(win)={boot['p_win']:.4f}")

    # ---- Tests vs Buy-and-Hold ----
    print("\n--- Statistical Tests vs Buy-and-Hold ---")
    stat_tests_bh = {}
    bh_ret = ret_series["Buy_Hold"]

    for name in strategies.keys():
        strat_ret = ret_series[name]
        dm = dm_test(bh_ret, strat_ret)
        jkm = jkm_sharpe_test(bh_ret, strat_ret)

        stat_tests_bh[name] = {
            "dm_t": dm["t_stat"],
            "dm_p": dm["p_value"],
            "jkm_z": jkm["z_stat"],
            "jkm_p": jkm["p_value"],
        }

        harvey_pass = abs(dm["t_stat"]) > 3.0 if not np.isnan(dm["t_stat"]) else False
        print(f"  {name:15s}: DM t={dm['t_stat']:+.4f} (p={dm['p_value']:.4f}) "
              f"{'PASS' if harvey_pass else 'FAIL'} Harvey, "
              f"JKM z={jkm['z_stat']:+.4f}")

    # ---- Bootstrap Sharpe CIs ----
    print("\n--- Bootstrap Sharpe Ratio CI (95%) ---")
    boot_cis = {}
    for name in ["Buy_Hold", "Fixed_12", "Rate_Adj", "VIX_Regime", "Roll_Sharpe", "Inv_VIX_Pct"]:
        ci = bootstrap_sharpe(ret_series[name])
        boot_cis[name] = ci
        print(f"  {name:15s}: {ci['mean']:.4f} [{ci['ci_lo']:.4f}, {ci['ci_hi']:.4f}]")

    # ---- Cross-OOS ----
    print("\n--- Cross-OOS Evaluation (5 periods) ---")
    oos_results = cross_oos(data, strategies, OOS_PERIODS)

    # Summarize OOS wins
    oos_wins = {name: {"vs_bh": 0, "vs_fixed": 0, "total": 0} for name in strategies}

    for period_name, period_res in oos_results.items():
        bh_sharpe = period_res.get("Buy_Hold", {}).get("sharpe", 0)
        fixed_sharpe = period_res.get("Fixed_12", {}).get("sharpe", 0)

        for name in strategies:
            if name in period_res:
                s = period_res[name].get("sharpe", 0)
                oos_wins[name]["total"] += 1
                if s > bh_sharpe:
                    oos_wins[name]["vs_bh"] += 1
                if s > fixed_sharpe:
                    oos_wins[name]["vs_fixed"] += 1

    print("\n  OOS Win Rate (Sharpe):")
    for name, wins in oos_wins.items():
        total = wins["total"]
        if total > 0:
            print(f"    {name:15s}: vs B&H {wins['vs_bh']}/{total}, "
                  f"vs Fixed_12 {wins['vs_fixed']}/{total}")

    # ---- Crisis Analysis ----
    print("\n--- Crisis Analysis ---")
    crisis_res = crisis_analysis(data, strategies)
    for crisis_name, strats in crisis_res.items():
        bh_r = strats.get("Buy_Hold", {}).get("cum_return", 0)
        print(f"\n  {crisis_name} (B&H: {bh_r*100:.2f}%):")
        for name in strategies:
            if name in strats:
                s = strats[name]
                print(f"    {name:15s}: {s['cum_return']*100:.2f}%, "
                      f"avg_w={s['avg_weight']:.3f}, avg_target={s['avg_target']*100:.1f}%")

    # ---- Rate Environment Analysis ----
    print("\n--- Rate Environment Analysis ---")
    rate_env = rate_environment_analysis(data, strategies)
    for env_name, env_res in rate_env.items():
        print(f"\n  {env_name} (n={env_res['n_days']}, avg_rf={env_res['avg_rf']*100:.2f}%):")
        for name in strategies:
            if name in env_res:
                s = env_res[name]
                print(f"    {name:15s}: Sharpe={s['sharpe']:.4f}, "
                      f"Return={s['ann_return']*100:.2f}%, avg_target={s['avg_target']*100:.1f}%")

    # ---- Transaction Cost Sensitivity ----
    print("\n--- Transaction Cost Sensitivity ---")
    tx_sensitivity = {}
    for tx in [0.0, 0.001, 0.003, 0.005, 0.010]:
        tx_res = {}
        for name, target_fn in strategies.items():
            target_series = target_fn(data)
            weights = compute_vt_weights(data, target_series)
            result = backtest_strategy(data, weights, name, tx_cost=tx)
            tx_res[name] = result["sharpe"]
        tx_sensitivity[f"tx_{int(tx*10000)}bp"] = tx_res

    print(f"  {'TX Cost':>10s}  " + "  ".join(f"{n:>12s}" for n in strategies.keys()))
    for tx_label, sharpes in tx_sensitivity.items():
        vals = "  ".join(f"{sharpes[n]:12.4f}" for n in strategies.keys())
        print(f"  {tx_label:>10s}  {vals}")

    # ---- Correlation Between Dynamic Target Series ----
    print("\n--- Correlation Between Target Vol Series ---")
    target_df = pd.DataFrame({name: fn(data) for name, fn in strategies.items()})
    corr = target_df.corr()
    print(corr.round(3).to_string())

    # ---- Summary & Conclusion ----
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    # Find best dynamic strategy
    dynamic_names = ["Rate_Adj", "VIX_Regime", "Roll_Sharpe", "Inv_VIX_Pct"]
    best_dyn = max(dynamic_names, key=lambda n: full_results[n]["sharpe"])
    worst_dyn = min(dynamic_names, key=lambda n: full_results[n]["sharpe"])

    fixed_sharpe_val = full_results["Fixed_12"]["sharpe"]
    best_sharpe = full_results[best_dyn]["sharpe"]
    worst_sharpe = full_results[worst_dyn]["sharpe"]

    any_harvey_pass = any(
        abs(stat_tests[n]["dm_t"]) > 3.0
        for n in dynamic_names
        if not np.isnan(stat_tests[n]["dm_t"])
    )

    print(f"\n  Fixed_12 (baseline) Sharpe: {fixed_sharpe_val:.4f}")
    print(f"  Best dynamic ({best_dyn}):    {best_sharpe:.4f} (diff: {best_sharpe-fixed_sharpe_val:+.4f})")
    print(f"  Worst dynamic ({worst_dyn}):  {worst_sharpe:.4f} (diff: {worst_sharpe-fixed_sharpe_val:+.4f})")
    print(f"  Any Harvey t>3.0 pass:        {'YES' if any_harvey_pass else 'NO'}")

    # Determine conclusion
    if any_harvey_pass and best_sharpe > fixed_sharpe_val:
        conclusion = "SIGNIFICANT: At least one dynamic target beats fixed 12%"
    elif best_sharpe > fixed_sharpe_val and not any_harvey_pass:
        conclusion = "MARGINAL: Dynamic targets show improvement but fail Harvey threshold"
    elif best_sharpe <= fixed_sharpe_val:
        conclusion = "NULL RESULT: No dynamic target beats fixed 12% — confirming K4"
    else:
        conclusion = "MIXED: See detailed results"

    print(f"\n  CONCLUSION: {conclusion}")

    # K4 comparison
    print(f"\n  K4 Comparison:")
    print(f"    K4 found: all dynamic targets WORSE (VIX double-dipping)")
    print(f"    K603 adds: multi-asset (50/50 SPY/GLD), rate-adjusted, cross-OOS, Harvey test")
    if worst_sharpe < fixed_sharpe_val:
        print(f"    K603 CONFIRMS K4: dynamic targets still worse or equal")
    else:
        print(f"    K603 CHALLENGES K4: some dynamic targets now better (different portfolio)")

    # ============================================================
    #  Save Results
    # ============================================================
    output = {
        "experiment_id": "k603",
        "title": "K603: Dynamic Target Volatility — Should 12 in 12/VIX Change?",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
        "data_period": f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
        "n_days": len(data),
        "portfolio": "50/50 SPY/GLD",
        "methodology": {
            "baseline": "Fixed target 12% (standard 12/VIX)",
            "dynamic_strategies": [
                "Rate_Adj: target = 12% + (rf - 2%), clipped [6%, 20%]",
                "VIX_Regime: VIX<15->15%, 15-25->12%, >25->10%",
                "Roll_Sharpe: target = 12% * (rolling_sharpe/mean_sharpe), clipped [6%, 20%]",
                "Inv_VIX_Pct: target = 8% + 8%*(1-VIX_pctile), clipped [6%, 20%]",
            ],
            "cross_oos": "5 non-overlapping ~4yr periods",
            "statistical_tests": "DM test (Harvey t>3.0), JKM Sharpe test, block bootstrap",
            "tx_cost": "1bp default",
        },
        "references": [
            "K4: Dynamic target vol (early phase null result)",
            "K550: Adaptive VIX Threshold (10-16 all similar)",
            "K568: Optimal Weight Function (12/VIX return-optimal)",
            "Moreira & Muir (2017, JoF)",
            "Harvey (2016, JoF): t>3 threshold",
        ],
        "full_sample_results": {k: v for k, v in full_results.items()},
        "target_dynamics": target_dynamics,
        "statistical_tests_vs_fixed": stat_tests,
        "statistical_tests_vs_bh": stat_tests_bh,
        "bootstrap_ci": boot_cis,
        "cross_oos_results": oos_results,
        "cross_oos_wins": oos_wins,
        "crisis_analysis": crisis_res,
        "rate_environment": rate_env,
        "tx_sensitivity": tx_sensitivity,
        "conclusion": conclusion,
    }

    out_path = Path(__file__).parent / "k603_dynamic_target_vol_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return output


if __name__ == "__main__":
    results = main()
