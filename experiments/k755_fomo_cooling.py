"""K755: FOMO Cooling Mechanism — Can a 48-Hour Lock Prevent the Costliest Behavioral Mistake?
==========================================================================================
K743 found FOMO costs 5x more than panic (-58% vs -14% Sharpe). This experiment
designs and tests a systematic COOLING MECHANISM that locks VT weights after
large single-day rallies, preventing the most costly behavioral mistake.

Part A: FOMO Frequency & Aftermath
  - How often does SPY gain >2% in a single day? (2006-2026)
  - Next-2-day and next-5-day return distribution after +2% days
  - Is there mean reversion or momentum after large rallies?

Part B: Cooling Mechanism Variants (vs standard 12/VIX)
  1. Lock-48h: After SPY >+2%, freeze current weight for 2 trading days
  2. Lock-5d: Freeze for 5 trading days
  3. Cap-increase: After SPY >+2%, cap weight increase at 50% of 12/VIX change
  4. Gradual-return: After SPY >+2%, linearly return to 12/VIX target over 5 days

Part C: Combined FOMO Cooling + Panic Protection
  - FOMO cooling (Lock-48h) + panic floor (min 30% equity when VIX>30)
  - Test as combined "Robust VT" with fixed implementation

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-30 (~20 years)
Evaluation: 2007-01-03 to present (1y warmup)
Type: Empirical analysis (real market data)

References:
  - K743: FOMO costs -58% Sharpe, most costly behavioral mistake
  - K743-review: Codex found 2 HIGH bugs (delayed rebalance lookahead, loss aversion lag)
         FOMO finding rated safe — core FOMO result reliable
  - K687: No VT beats BH 50/50 on Sharpe after proper lag
  - K697: VIX predicts vol magnitude (r=0.57) not direction (r=0.04)
  - Moreira & Muir (2017), Volatility-Managed Portfolios, JF
  - Daniel & Moskowitz (2016), Momentum Crashes, JFE — crash-prone momentum reversal
  - Barberis & Shleifer (2003), Style Investing, JFE — extrapolation bias
  - Odean (1998), Are Investors Reluctant to Realize Their Losses?, JF

[提出: Claude (from K743 + research_program), 執行: Claude]
Author: VolPred Research System
Date: 2026-03-30
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-30"
EVAL_START = "2007-01-03"
TC_BPS = 5                     # Transaction cost: 5 bps per leg
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
VIX_12_CAP = 1.5               # Max weight for 12/VIX

# FOMO trigger thresholds to test
FOMO_THRESHOLD = 0.02           # 2% daily return triggers FOMO event

# Cooling mechanism parameters
LOCK_48H_DAYS = 2              # Freeze weight for 2 trading days
LOCK_5D_DAYS = 5               # Freeze weight for 5 trading days
CAP_INCREASE_RATIO = 0.50      # Cap weight increase at 50% of signal change
GRADUAL_RETURN_DAYS = 5        # Linear return to target over 5 days

# Panic floor parameters (for Part C combined)
PANIC_VIX_THRESHOLD = 30
FLOOR_EQUITY = 0.30

# Bootstrap
N_BOOTSTRAP = 5000


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("Downloading data from yfinance...")
    tickers = ["SPY", "GLD", "^VIX"]
    data = {}
    for t in tickers:
        df = yf.download(t, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t.replace("^", "")] = df["Close"].dropna()

    combined = pd.DataFrame(data).dropna()

    spy_ret = combined["SPY"].pct_change()
    gld_ret = combined["GLD"].pct_change()
    vix = combined["VIX"]

    return combined, spy_ret, gld_ret, vix


# ============================================================================
# Helper: Performance Metrics
# ============================================================================
def compute_metrics(returns, name=""):
    """Compute standard performance metrics for a return series."""
    r = returns.dropna()
    n = len(r)
    if n < 30:
        return {"name": name, "n_obs": n, "error": "Insufficient data"}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # CAGR
    total_days = (r.index[-1] - r.index[0]).days
    total_return = cum.iloc[-1] / cum.iloc[0] if cum.iloc[0] > 0 else 1
    years = total_days / 365.25
    cagr = total_return ** (1 / years) - 1 if years > 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (ann_ret - RF_ANNUAL) / downside if downside > 0 else 0

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    return {
        "name": name,
        "n_obs": n,
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "cagr": round(cagr, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
    }


def bootstrap_sharpe_diff(ret_a, ret_b, n_boot=N_BOOTSTRAP):
    """Bootstrap test for Sharpe difference (a - b)."""
    diff_series = ret_a - ret_b
    diff_arr = diff_series.dropna().values
    n = len(diff_arr)

    sharpe_a = (ret_a.mean() * 252 - RF_ANNUAL) / (ret_a.std() * np.sqrt(252))
    sharpe_b = (ret_b.mean() * 252 - RF_ANNUAL) / (ret_b.std() * np.sqrt(252))
    observed_diff = sharpe_a - sharpe_b

    rng = np.random.RandomState(42)
    boot_diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        a_boot = ret_a.values[idx]
        b_boot = ret_b.values[idx]
        s_a = (a_boot.mean() * 252 - RF_ANNUAL) / (a_boot.std() * np.sqrt(252))
        s_b = (b_boot.mean() * 252 - RF_ANNUAL) / (b_boot.std() * np.sqrt(252))
        boot_diffs[i] = s_a - s_b

    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)
    p_value = np.mean(boot_diffs < 0) if observed_diff > 0 else np.mean(boot_diffs > 0)

    return {
        "observed_diff": round(observed_diff, 4),
        "ci_95_lo": round(ci_lo, 4),
        "ci_95_hi": round(ci_hi, 4),
        "p_value": round(p_value, 4),
    }


# ============================================================================
# Part A: FOMO Frequency & Aftermath Analysis
# ============================================================================
def analyze_fomo_events(spy_ret, eval_mask):
    """Analyze what happens after large positive SPY days."""
    print("\n" + "=" * 70)
    print("PART A: FOMO EVENT ANALYSIS")
    print("=" * 70)

    r = spy_ret[eval_mask].dropna()
    n_total = len(r)

    # Find FOMO trigger days (SPY >+2%)
    fomo_days = r[r > FOMO_THRESHOLD]
    n_fomo = len(fomo_days)
    fomo_pct = n_fomo / n_total * 100

    print(f"\nTotal trading days: {n_total}")
    print(f"Days with SPY >+2%: {n_fomo} ({fomo_pct:.1f}%)")
    print(f"Average FOMO day return: {fomo_days.mean()*100:.2f}%")
    print(f"Median FOMO day return: {fomo_days.median()*100:.2f}%")
    print(f"Max FOMO day return: {fomo_days.max()*100:.2f}%")

    # Threshold analysis
    thresholds = [0.01, 0.015, 0.02, 0.025, 0.03]
    threshold_counts = {}
    for th in thresholds:
        cnt = (r > th).sum()
        threshold_counts[f">{th*100:.1f}%"] = {
            "count": int(cnt),
            "pct_of_days": round(cnt / n_total * 100, 2),
            "avg_per_year": round(cnt / (n_total / 252), 1),
        }
        print(f"  SPY >{th*100:.0f}%: {cnt} days ({cnt/n_total*100:.1f}%), "
              f"~{cnt/(n_total/252):.1f}/year")

    # Next-N-day returns after FOMO events
    aftermath = {}
    for horizon in [1, 2, 3, 5, 10, 20]:
        future_rets = []
        for date in fomo_days.index:
            loc = r.index.get_loc(date)
            if loc + horizon < len(r):
                future_ret = r.iloc[loc + 1: loc + 1 + horizon].sum()
                future_rets.append(future_ret)
        future_rets = np.array(future_rets)
        n_obs = len(future_rets)
        if n_obs > 5:
            mean_ret = future_rets.mean()
            std_ret = future_rets.std()
            t_stat = mean_ret / (std_ret / np.sqrt(n_obs))
            p_val = 2 * sp_stats.t.sf(abs(t_stat), n_obs - 1)
            pct_positive = (future_rets > 0).mean()

            aftermath[f"next_{horizon}d"] = {
                "n_events": int(n_obs),
                "mean_return": round(mean_ret * 100, 3),
                "median_return": round(np.median(future_rets) * 100, 3),
                "std_return": round(std_ret * 100, 3),
                "t_stat": round(t_stat, 3),
                "p_value": round(p_val, 4),
                "pct_positive": round(pct_positive * 100, 1),
            }
            direction = "mean reversion" if mean_ret < 0 else "momentum"
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
            print(f"\n  Next {horizon}d after +2% day: "
                  f"mean={mean_ret*100:+.3f}%, median={np.median(future_rets)*100:+.3f}%, "
                  f"t={t_stat:.2f}{sig}, %pos={pct_positive*100:.1f}% ({direction})")

    # Compare with unconditional returns for same horizons
    unconditional = {}
    for horizon in [1, 2, 5]:
        all_future = r.rolling(horizon).sum().shift(-horizon).dropna()
        uncon_mean = all_future.mean()
        unconditional[f"unconditional_{horizon}d"] = round(uncon_mean * 100, 3)

    print("\n  Unconditional comparison:")
    for k, v in unconditional.items():
        print(f"    {k}: {v:+.3f}%")

    # By VIX regime during FOMO events
    vix_at_fomo = []
    for date in fomo_days.index:
        # (We'll compute this with vix passed separately)
        pass

    return {
        "n_total_days": int(n_total),
        "n_fomo_days": int(n_fomo),
        "fomo_pct": round(fomo_pct, 2),
        "avg_fomo_return": round(fomo_days.mean() * 100, 3),
        "threshold_analysis": threshold_counts,
        "aftermath_returns": aftermath,
        "unconditional_returns": unconditional,
    }


def analyze_fomo_by_vix_regime(spy_ret, vix, eval_mask):
    """Break down FOMO events by VIX regime."""
    r = spy_ret[eval_mask].dropna()
    v = vix[eval_mask].reindex(r.index)

    fomo_mask = r > FOMO_THRESHOLD
    fomo_dates = r[fomo_mask].index

    regimes = {
        "low_vix_<15": v < 15,
        "mid_vix_15-25": (v >= 15) & (v < 25),
        "high_vix_25-35": (v >= 25) & (v < 35),
        "extreme_vix_>35": v >= 35,
    }

    results = {}
    print("\nFOMO events by VIX regime:")
    for regime_name, regime_mask in regimes.items():
        regime_fomo = fomo_mask & regime_mask
        n_fomo_in_regime = regime_fomo.sum()
        n_regime_days = regime_mask.sum()

        # Next-2d returns in this regime
        next_2d = []
        for date in r[regime_fomo].index:
            loc = r.index.get_loc(date)
            if loc + 2 < len(r):
                next_2d.append(r.iloc[loc + 1: loc + 3].sum())

        next_2d = np.array(next_2d) if next_2d else np.array([0])
        results[regime_name] = {
            "n_fomo_events": int(n_fomo_in_regime),
            "n_regime_days": int(n_regime_days),
            "fomo_rate": round(n_fomo_in_regime / max(n_regime_days, 1) * 100, 2),
            "next_2d_mean": round(next_2d.mean() * 100, 3) if len(next_2d) > 0 else None,
        }
        print(f"  {regime_name}: {n_fomo_in_regime} events "
              f"({n_fomo_in_regime/max(n_regime_days,1)*100:.1f}% of regime days), "
              f"next-2d mean={next_2d.mean()*100:+.3f}%")

    return results


# ============================================================================
# Part B: Cooling Mechanism Strategies
# ============================================================================
def compute_perfect_12vix(spy_ret, gld_ret, vix, eval_mask):
    """Perfect 12/VIX execution: daily rebalance, proper lag."""
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)  # signal.shift(1) !!
    w_equity = w_equity.fillna(0.5)

    port_ret = w_equity * spy_ret + (1 - w_equity) * gld_ret
    delta_w = w_equity.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_equity[eval_mask]


def compute_bh_5050(spy_ret, gld_ret, eval_mask):
    """Buy & Hold 50/50 SPY/GLD — monthly rebalance."""
    w = 0.5
    port_ret = w * spy_ret + (1 - w) * gld_ret

    idx = port_ret.index
    is_rebal = pd.Series(False, index=idx)
    for i in range(0, len(idx), 21):
        is_rebal.iloc[i] = True
    tc = is_rebal.astype(float) * 0.01 * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask]


def compute_lock_strategy(spy_ret, gld_ret, vix, eval_mask, lock_days=2, name="Lock"):
    """After SPY >+2%, freeze weight for N trading days."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)  # signal.shift(1) !!
    w_target = w_target.fillna(0.5)
    spy_ret_lagged = spy_ret.shift(1)  # Yesterday's return known today

    w_actual = w_target.copy()
    lock_counter = pd.Series(0, index=w_target.index, dtype=int)

    # Need to iterate since lock state depends on previous days
    values = w_target.values.copy()
    ret_vals = spy_ret_lagged.values
    lock_remaining = 0

    for i in range(1, len(values)):
        if lock_remaining > 0:
            # Still locked: keep previous weight
            values[i] = values[i - 1]
            lock_remaining -= 1
        # Check if yesterday's return triggered FOMO (using lagged return)
        if not np.isnan(ret_vals[i]) and ret_vals[i] > FOMO_THRESHOLD:
            lock_remaining = lock_days
            # Weight stays at what we already have (current value stays from target or locked)
            # But we freeze starting from current — don't change from what we have
            if i > 0 and lock_remaining == lock_days:
                values[i] = values[i - 1]  # Freeze at yesterday's weight

    w_actual = pd.Series(values, index=w_target.index)
    port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
    delta_w = w_actual.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    # Count lock events
    n_lock_events = 0
    lock_rem = 0
    for i in range(1, len(ret_vals)):
        if lock_rem > 0:
            lock_rem -= 1
        if not np.isnan(ret_vals[i]) and ret_vals[i] > FOMO_THRESHOLD:
            n_lock_events += 1
            lock_rem = lock_days

    return port_ret_net[eval_mask], w_actual[eval_mask], n_lock_events


def compute_cap_increase(spy_ret, gld_ret, vix, eval_mask, cap_ratio=0.5):
    """After SPY >+2%, cap weight INCREASE at cap_ratio of signal change for 2 days."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)  # signal.shift(1) !!
    w_target = w_target.fillna(0.5)
    spy_ret_lagged = spy_ret.shift(1)

    values = w_target.values.copy()
    ret_vals = spy_ret_lagged.values
    cap_remaining = 0

    for i in range(1, len(values)):
        target_change = values[i] - values[i - 1] if not np.isnan(values[i - 1]) else 0

        if cap_remaining > 0:
            # Cap increases only — decreases pass through
            if target_change > 0:
                capped_change = target_change * cap_ratio
                values[i] = values[i - 1] + capped_change
            # else: decrease passes through normally
            cap_remaining -= 1

        # Check if yesterday triggered FOMO
        if not np.isnan(ret_vals[i]) and ret_vals[i] > FOMO_THRESHOLD:
            cap_remaining = 2  # Cap for 2 days

    w_actual = pd.Series(values, index=w_target.index)
    port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
    delta_w = w_actual.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_actual[eval_mask]


def compute_gradual_return(spy_ret, gld_ret, vix, eval_mask, return_days=5):
    """After SPY >+2%, linearly return to target over N days."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)  # signal.shift(1) !!
    w_target = w_target.fillna(0.5)
    spy_ret_lagged = spy_ret.shift(1)

    values = w_target.values.copy()
    ret_vals = spy_ret_lagged.values
    gradual_remaining = 0
    anchor_weight = 0.5  # Weight at the moment of FOMO trigger

    for i in range(1, len(values)):
        if gradual_remaining > 0:
            # Linear interpolation from anchor to current target
            progress = 1.0 - (gradual_remaining / return_days)  # 0 → 1
            values[i] = anchor_weight + progress * (values[i] - anchor_weight)
            gradual_remaining -= 1

        if not np.isnan(ret_vals[i]) and ret_vals[i] > FOMO_THRESHOLD:
            anchor_weight = values[i - 1] if i > 0 else 0.5
            gradual_remaining = return_days
            values[i] = anchor_weight  # Start from current weight

    w_actual = pd.Series(values, index=w_target.index)
    port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
    delta_w = w_actual.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_actual[eval_mask]


# ============================================================================
# Part C: Combined FOMO Cooling + Panic Protection
# ============================================================================
def compute_combined_robust(spy_ret, gld_ret, vix, eval_mask, lock_days=2):
    """Combined: FOMO lock + panic floor (min 30% equity when VIX > 30)."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)  # signal.shift(1) !!
    w_target = w_target.fillna(0.5)
    spy_ret_lagged = spy_ret.shift(1)
    vix_lagged = vix.shift(1)

    values = w_target.values.copy()
    ret_vals = spy_ret_lagged.values
    vix_vals = vix_lagged.values
    lock_remaining = 0

    for i in range(1, len(values)):
        # FOMO lock: freeze weight after large rallies
        if lock_remaining > 0:
            values[i] = values[i - 1]
            lock_remaining -= 1

        if not np.isnan(ret_vals[i]) and ret_vals[i] > FOMO_THRESHOLD:
            lock_remaining = lock_days
            values[i] = values[i - 1]

        # Panic floor: ensure min 30% equity even when VIX is high
        # (Counter-intuitive: prevents panic selling by FORCING equity exposure)
        if not np.isnan(vix_vals[i]) and vix_vals[i] > PANIC_VIX_THRESHOLD:
            values[i] = max(values[i], FLOOR_EQUITY)

    w_actual = pd.Series(values, index=w_target.index)
    port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
    delta_w = w_actual.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_actual[eval_mask]


# ============================================================================
# Sub-period Analysis
# ============================================================================
def sub_period_analysis(strategies_returns, periods):
    """Compute Sharpe for each strategy across sub-periods."""
    results = {}
    for period_name, (start, end) in periods.items():
        results[period_name] = {}
        for strat_name, ret_series in strategies_returns.items():
            sub = ret_series.loc[start:end].dropna()
            if len(sub) > 30:
                ann_ret = sub.mean() * 252
                ann_vol = sub.std() * np.sqrt(252)
                sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
                results[period_name][strat_name] = round(sharpe, 4)
            else:
                results[period_name][strat_name] = None
    return results


# ============================================================================
# Sensitivity Analysis
# ============================================================================
def sensitivity_analysis(spy_ret, gld_ret, vix, eval_mask):
    """Test cooling mechanism with different thresholds and lock durations."""
    print("\n" + "=" * 70)
    print("SENSITIVITY ANALYSIS")
    print("=" * 70)

    results = {}

    # Vary FOMO threshold
    for threshold in [0.01, 0.015, 0.02, 0.025, 0.03]:
        original_th = FOMO_THRESHOLD
        # Temporarily modify — we pass threshold via function param instead
        w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
        w_target = w_target.fillna(0.5)
        spy_ret_lagged = spy_ret.shift(1)

        values = w_target.values.copy()
        ret_vals = spy_ret_lagged.values
        lock_remaining = 0

        for i in range(1, len(values)):
            if lock_remaining > 0:
                values[i] = values[i - 1]
                lock_remaining -= 1
            if not np.isnan(ret_vals[i]) and ret_vals[i] > threshold:
                lock_remaining = 2
                values[i] = values[i - 1]

        w_actual = pd.Series(values, index=w_target.index)
        port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
        delta_w = w_actual.diff().abs().fillna(0)
        tc = delta_w * TC_BPS / 10000 * 2
        port_ret_net = (port_ret - tc)[eval_mask]
        m = compute_metrics(port_ret_net, f"Lock-48h th={threshold*100:.1f}%")
        results[f"threshold_{threshold*100:.1f}pct"] = m
        print(f"  Threshold={threshold*100:.1f}%: Sharpe={m['sharpe']:.4f}, MDD={m['mdd']:.4f}")

    # Vary lock duration (at 2% threshold)
    for lock_d in [1, 2, 3, 5, 10]:
        ret_net, _, _ = compute_lock_strategy(spy_ret, gld_ret, vix, eval_mask,
                                               lock_days=lock_d, name=f"Lock-{lock_d}d")
        m = compute_metrics(ret_net, f"Lock-{lock_d}d")
        results[f"lock_{lock_d}d"] = m
        print(f"  Lock={lock_d}d: Sharpe={m['sharpe']:.4f}, MDD={m['mdd']:.4f}")

    return results


# ============================================================================
# Main Execution
# ============================================================================
def main():
    print("K755: FOMO Cooling Mechanism Experiment")
    print("=" * 70)

    # Download data
    combined, spy_ret, gld_ret, vix = download_data()
    print(f"Data range: {combined.index[0].strftime('%Y-%m-%d')} to "
          f"{combined.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total observations: {len(combined)}")

    # Evaluation mask
    eval_mask = spy_ret.index >= EVAL_START

    # ========================================================================
    # PART A: FOMO Frequency & Aftermath
    # ========================================================================
    fomo_analysis = analyze_fomo_events(spy_ret, eval_mask)
    vix_regime_analysis = analyze_fomo_by_vix_regime(spy_ret, vix, eval_mask)

    # ========================================================================
    # PART B: Cooling Mechanism Variants
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART B: COOLING MECHANISM STRATEGIES")
    print("=" * 70)

    # Baselines
    ret_12vix, w_12vix = compute_perfect_12vix(spy_ret, gld_ret, vix, eval_mask)
    ret_bh = compute_bh_5050(spy_ret, gld_ret, eval_mask)

    # Cooling variants
    ret_lock48h, w_lock48h, n_lock48h = compute_lock_strategy(
        spy_ret, gld_ret, vix, eval_mask, lock_days=LOCK_48H_DAYS, name="Lock-48h")
    ret_lock5d, w_lock5d, n_lock5d = compute_lock_strategy(
        spy_ret, gld_ret, vix, eval_mask, lock_days=LOCK_5D_DAYS, name="Lock-5d")
    ret_cap, w_cap = compute_cap_increase(
        spy_ret, gld_ret, vix, eval_mask, cap_ratio=CAP_INCREASE_RATIO)
    ret_gradual, w_gradual = compute_gradual_return(
        spy_ret, gld_ret, vix, eval_mask, return_days=GRADUAL_RETURN_DAYS)

    # Part C: Combined
    ret_combined, w_combined = compute_combined_robust(spy_ret, gld_ret, vix, eval_mask)

    # Compute all metrics
    strategies = {
        "BH_50/50": ret_bh,
        "Perfect_12/VIX": ret_12vix,
        "Lock-48h": ret_lock48h,
        "Lock-5d": ret_lock5d,
        "Cap-increase": ret_cap,
        "Gradual-return": ret_gradual,
        "Combined_Robust": ret_combined,
    }

    metrics = {}
    for name, ret in strategies.items():
        m = compute_metrics(ret, name)
        metrics[name] = m
        print(f"\n{name}: Sharpe={m['sharpe']:.4f}, MDD={m['mdd']:.4f}, "
              f"CAGR={m['cagr']:.4f}, Sortino={m['sortino']:.4f}")

    # Print comparison table
    print("\n" + "-" * 70)
    print(f"{'Strategy':<20} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8} {'Sortino':>8} {'Calmar':>8}")
    print("-" * 70)
    for name, m in metrics.items():
        print(f"{m['name']:<20} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} "
              f"{m['cagr']:>8.4f} {m['sortino']:>8.4f} {m['calmar']:>8.4f}")
    print("-" * 70)

    # ========================================================================
    # Statistical Tests: Bootstrap Sharpe differences
    # ========================================================================
    print("\n" + "=" * 70)
    print("STATISTICAL TESTS (Bootstrap Sharpe Differences)")
    print("=" * 70)

    stat_tests = {}
    for name, ret in strategies.items():
        if name in ["BH_50/50", "Perfect_12/VIX"]:
            continue
        # vs Perfect 12/VIX
        test_vs_12vix = bootstrap_sharpe_diff(ret, ret_12vix)
        # vs BH 50/50
        test_vs_bh = bootstrap_sharpe_diff(ret, ret_bh)

        stat_tests[name] = {
            "vs_12vix": test_vs_12vix,
            "vs_bh": test_vs_bh,
        }
        print(f"\n{name} vs 12/VIX: ΔSharpe={test_vs_12vix['observed_diff']:+.4f} "
              f"[{test_vs_12vix['ci_95_lo']:.4f}, {test_vs_12vix['ci_95_hi']:.4f}] "
              f"p={test_vs_12vix['p_value']:.4f}")
        print(f"{name} vs BH: ΔSharpe={test_vs_bh['observed_diff']:+.4f} "
              f"[{test_vs_bh['ci_95_lo']:.4f}, {test_vs_bh['ci_95_hi']:.4f}] "
              f"p={test_vs_bh['p_value']:.4f}")

    # Also test 12/VIX vs BH
    test_12vix_vs_bh = bootstrap_sharpe_diff(ret_12vix, ret_bh)
    stat_tests["12vix_vs_bh"] = test_12vix_vs_bh
    print(f"\n12/VIX vs BH: ΔSharpe={test_12vix_vs_bh['observed_diff']:+.4f} "
          f"[{test_12vix_vs_bh['ci_95_lo']:.4f}, {test_12vix_vs_bh['ci_95_hi']:.4f}]")

    # ========================================================================
    # Weight Analysis: How much do cooling mechanisms change weights?
    # ========================================================================
    print("\n" + "=" * 70)
    print("WEIGHT CHANGE ANALYSIS")
    print("=" * 70)

    weight_analysis = {}
    weight_series = {
        "Perfect_12/VIX": w_12vix,
        "Lock-48h": w_lock48h,
        "Lock-5d": w_lock5d,
        "Cap-increase": w_cap,
        "Gradual-return": w_gradual,
        "Combined_Robust": w_combined,
    }

    for name, w in weight_series.items():
        avg_w = w.mean()
        std_w = w.std()
        avg_turnover = w.diff().abs().mean()
        corr_with_12vix = w.corr(w_12vix)
        weight_analysis[name] = {
            "avg_weight": round(avg_w, 4),
            "std_weight": round(std_w, 4),
            "avg_daily_turnover": round(avg_turnover, 6),
            "corr_with_12vix": round(corr_with_12vix, 4),
        }
        print(f"  {name}: avg_w={avg_w:.4f}, std={std_w:.4f}, "
              f"turnover={avg_turnover:.6f}, corr_w_12vix={corr_with_12vix:.4f}")

    # ========================================================================
    # Sub-period Analysis
    # ========================================================================
    print("\n" + "=" * 70)
    print("SUB-PERIOD ANALYSIS")
    print("=" * 70)

    sub_periods = {
        "GFC_2008-2009": ("2008-01-01", "2009-12-31"),
        "Recovery_2010-2013": ("2010-01-01", "2013-12-31"),
        "Bull_2014-2019": ("2014-01-01", "2019-12-31"),
        "COVID_2020": ("2020-01-01", "2020-12-31"),
        "PostCOVID_2021-2023": ("2021-01-01", "2023-12-31"),
        "Recent_2024-2026": ("2024-01-01", "2026-03-30"),
    }
    sub_results = sub_period_analysis(strategies, sub_periods)
    for period, strats in sub_results.items():
        print(f"\n  {period}:")
        for s, v in strats.items():
            if v is not None:
                print(f"    {s}: Sharpe={v:.4f}")

    # ========================================================================
    # Sensitivity Analysis
    # ========================================================================
    sensitivity_results = sensitivity_analysis(spy_ret, gld_ret, vix, eval_mask)

    # ========================================================================
    # Part A Deep Dive: FOMO events during crashes vs normal
    # ========================================================================
    print("\n" + "=" * 70)
    print("FOMO EVENT DEEP DIVE: CONTEXT MATTERS")
    print("=" * 70)

    # Large +2% days are often RECOVERY bounces in high-VIX environments
    r = spy_ret[eval_mask].dropna()
    v = vix[eval_mask].reindex(r.index)
    fomo_mask = r > FOMO_THRESHOLD

    # High VIX FOMO = recovery bounce; Low VIX FOMO = genuine rally
    high_vix_fomo = fomo_mask & (v > 25)
    low_vix_fomo = fomo_mask & (v <= 25)

    context_analysis = {}
    for label, mask in [("high_vix_recovery", high_vix_fomo),
                         ("low_vix_rally", low_vix_fomo)]:
        events = r[mask]
        next_5d = []
        for date in events.index:
            loc = r.index.get_loc(date)
            if loc + 5 < len(r):
                next_5d.append(r.iloc[loc + 1: loc + 6].sum())
        next_5d = np.array(next_5d) if next_5d else np.array([0.0])
        context_analysis[label] = {
            "n_events": int(mask.sum()),
            "avg_trigger_return": round(events.mean() * 100, 3) if len(events) > 0 else 0,
            "next_5d_mean": round(next_5d.mean() * 100, 3),
            "next_5d_pct_positive": round((next_5d > 0).mean() * 100, 1),
        }
        print(f"  {label}: {mask.sum()} events, trigger avg={events.mean()*100:.2f}%, "
              f"next-5d mean={next_5d.mean()*100:+.3f}%, "
              f"%pos={((next_5d > 0).mean()*100):.1f}%")

    # ========================================================================
    # COMPILE RESULTS
    # ========================================================================
    results = {
        "experiment_id": "K755",
        "title": "K755: FOMO Cooling Mechanism — Can a 48-Hour Lock Prevent the Costliest Behavioral Mistake?",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{combined.index[0].strftime('%Y-%m-%d')} to {combined.index[-1].strftime('%Y-%m-%d')}",
        "eval_period": f"{EVAL_START} to {combined.index[-1].strftime('%Y-%m-%d')}",
        "n_observations": int(len(combined)),
        "parameters": {
            "fomo_threshold": FOMO_THRESHOLD,
            "lock_48h_days": LOCK_48H_DAYS,
            "lock_5d_days": LOCK_5D_DAYS,
            "cap_increase_ratio": CAP_INCREASE_RATIO,
            "gradual_return_days": GRADUAL_RETURN_DAYS,
            "tc_bps": TC_BPS,
            "rf_annual": RF_ANNUAL,
            "vix_12_cap": VIX_12_CAP,
            "panic_vix_threshold": PANIC_VIX_THRESHOLD,
            "floor_equity": FLOOR_EQUITY,
        },
        "part_a_fomo_analysis": fomo_analysis,
        "part_a_vix_regime": vix_regime_analysis,
        "part_a_context": context_analysis,
        "part_b_metrics": metrics,
        "part_b_lock_events": {
            "lock_48h_events": n_lock48h,
            "lock_5d_events": n_lock5d,
        },
        "statistical_tests": stat_tests,
        "weight_analysis": weight_analysis,
        "sub_period_analysis": sub_results,
        "sensitivity_analysis": sensitivity_results,
        "conclusions": {},  # Filled below
    }

    # ========================================================================
    # CONCLUSIONS
    # ========================================================================
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    # Determine best cooling strategy
    cooling_names = ["Lock-48h", "Lock-5d", "Cap-increase", "Gradual-return", "Combined_Robust"]
    best_cooling = max(cooling_names, key=lambda x: metrics[x]["sharpe"])
    worst_cooling = min(cooling_names, key=lambda x: metrics[x]["sharpe"])

    sharpe_12vix = metrics["Perfect_12/VIX"]["sharpe"]
    sharpe_bh = metrics["BH_50/50"]["sharpe"]
    sharpe_best = metrics[best_cooling]["sharpe"]
    sharpe_worst = metrics[worst_cooling]["sharpe"]

    # Does cooling help or hurt vs perfect 12/VIX?
    cooling_helps = sharpe_best > sharpe_12vix
    cooling_vs_12vix = "improves" if cooling_helps else "slightly reduces"

    conclusions = {
        "best_cooling_strategy": best_cooling,
        "best_sharpe": sharpe_best,
        "worst_cooling_strategy": worst_cooling,
        "worst_sharpe": sharpe_worst,
        "perfect_12vix_sharpe": sharpe_12vix,
        "bh_5050_sharpe": sharpe_bh,
        "cooling_vs_12vix": cooling_vs_12vix,
        "fomo_events_per_year": fomo_analysis["threshold_analysis"][">2.0%"]["avg_per_year"],
        "mean_reversion_after_fomo": (
            "yes" if fomo_analysis["aftermath_returns"].get("next_2d", {}).get("mean_return", 0) < 0
            else "no/weak"
        ),
        "summary": (
            f"FOMO events (SPY >+2%) occur ~{fomo_analysis['threshold_analysis']['>2.0%']['avg_per_year']:.0f}x/year. "
            f"Post-FOMO returns show {'mean reversion' if fomo_analysis['aftermath_returns'].get('next_2d', {}).get('mean_return', 0) < 0 else 'continuation/neutral'}. "
            f"Best cooling ({best_cooling}) {cooling_vs_12vix} Sharpe to {sharpe_best:.4f} from 12/VIX {sharpe_12vix:.4f}. "
            f"BH 50/50 Sharpe: {sharpe_bh:.4f}. "
            f"Cooling is {'a viable overlay' if cooling_helps else 'neutral-to-slightly-costly as a systematic rule'}."
        ),
    }

    results["conclusions"] = conclusions

    for k, v in conclusions.items():
        if k != "summary":
            print(f"  {k}: {v}")
    print(f"\n  SUMMARY: {conclusions['summary']}")

    # ========================================================================
    # SAVE RESULTS
    # ========================================================================
    results_path = Path("experiments/k755_fomo_cooling_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    return results


if __name__ == "__main__":
    results = main()
