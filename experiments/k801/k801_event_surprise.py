"""
K801: Event-Surprise Volatility Strategy — VIX Shock Guard

Hypothesis (Codex #5 suggestion):
  Calendar-based event dummies are NULL (K498). But VIX CHANGE on event day
  captures the SURPRISE component. After a large VIX shock (|ΔVIX| > 2σ),
  equity should be reduced for 5 days to avoid follow-through volatility.

Design:
  1. Identify VIX shock days: |ΔVIX| > 2σ (rolling 252d std)
  2. Strategy variants vs baseline (12/VIX):
     A. VIX_Shock_Guard:   if shock yesterday → reduce to 50% weight for 5d
     B. VIX_Shock_Binary:  if shock yesterday → go to cash for 5d
     C. VIX_Spike_Only:    only reduce on VIX SPIKES (ΔVIX > +2σ), not drops
     D. VIX_Drop_Boost:    only INCREASE on VIX DROPS (ΔVIX < -2σ)

Rules:
  - signal.shift(1): use YESTERDAY's VIX shock, never same-day
  - TX cost: 10bps per weight change
  - OOS: 2023-2025
  - Harvey t > 3.0 threshold

Data: SPY, GLD, VIX from yfinance (2010-2025)
Reference: Codex #5 suggestion; K498 (calendar dummies NULL)
"""

import json
import sys
import warnings
from datetime import datetime, date

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

EXPERIMENT_ID = "K801"
START_DATE = "2010-01-01"
END_DATE = "2025-12-31"
OOS_START = "2023-01-01"
TX_COST = 0.001  # 10bps per side
SHOCK_WINDOW = 252  # rolling window for σ of ΔVIX
SHOCK_THRESHOLD = 2.0  # σ multiplier
GUARD_DAYS = 5  # days to hold reduced weight after shock


def download_data():
    """Download SPY, GLD, VIX from yfinance."""
    print("Downloading data...")
    tickers = ["SPY", "GLD", "^VIX"]
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)

    # Extract adjusted close prices
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"][["SPY", "GLD"]]
        vix = raw["Close"]["^VIX"]
    else:
        prices = raw["Close"]
        vix = raw["Close"]

    # Daily returns
    spy_ret = prices["SPY"].pct_change()
    gld_ret = prices["GLD"].pct_change()
    vix_chg = vix.diff()  # Absolute VIX change (not %)

    df = pd.DataFrame({
        "spy_ret": spy_ret,
        "gld_ret": gld_ret,
        "vix": vix,
        "vix_chg": vix_chg,
    }).dropna()

    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    return df


def compute_vix_shocks(df):
    """
    Identify VIX shock days: |ΔVIX| > 2σ (rolling 252d).
    Returns:
      - shock_any: |ΔVIX| > threshold (positive or negative)
      - spike: ΔVIX > +threshold (fear spike)
      - drop: ΔVIX < -threshold (fear drop)
    """
    rolling_std = df["vix_chg"].rolling(SHOCK_WINDOW, min_periods=63).std()
    threshold = SHOCK_THRESHOLD * rolling_std

    df["vix_shock_any"] = (df["vix_chg"].abs() > threshold).astype(int)
    df["vix_spike"] = (df["vix_chg"] > threshold).astype(int)
    df["vix_drop"] = (df["vix_chg"] < -threshold).astype(int)
    df["rolling_std"] = rolling_std

    n_shocks = df["vix_shock_any"].sum()
    n_spikes = df["vix_spike"].sum()
    n_drops = df["vix_drop"].sum()
    print(f"  VIX shocks: {n_shocks} total ({n_spikes} spikes, {n_drops} drops) "
          f"over {len(df)} days ({100*n_shocks/len(df):.1f}%)")
    return df


def build_guard_mask(shock_series, guard_days=GUARD_DAYS):
    """
    After a shock on day t, set mask=1 for t+1 through t+guard_days.
    This is the SIGNAL (lagged): triggered by yesterday's shock.
    """
    mask = np.zeros(len(shock_series), dtype=int)
    shock_arr = shock_series.values
    for i in range(1, len(shock_arr)):
        if shock_arr[i - 1] == 1:  # shock on previous day → trigger today
            for j in range(i, min(i + guard_days, len(shock_arr))):
                mask[j] = 1
    return pd.Series(mask, index=shock_series.index)


def compute_baseline_12vix(df):
    """Baseline: 12/VIX strategy (no shock adjustment)."""
    weight = (12.0 / df["vix"]).clip(0, 1)
    # No lag needed for 12/VIX itself (uses t-1 VIX for t return is standard)
    # But to be safe, shift(1) — use previous day's VIX weight
    weight = weight.shift(1).fillna(method="bfill")
    return weight


def backtest(spy_ret, weight, name="strategy"):
    """
    Run backtest with TX cost.
    Returns dict of performance metrics.
    """
    weight = weight.copy()
    weight_prev = weight.shift(1).fillna(0)
    tx = TX_COST * (weight - weight_prev).abs()

    port_ret = weight * spy_ret - tx

    cum = (1 + port_ret).cumprod()
    total_days = len(port_ret)
    years = total_days / 252

    cagr = cum.iloc[-1] ** (1 / years) - 1
    sharpe = port_ret.mean() / port_ret.std() * np.sqrt(252) if port_ret.std() > 0 else 0

    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min()

    hit_rate = (port_ret > 0).mean()
    ann_vol = port_ret.std() * np.sqrt(252)

    # DM test vs this baseline uses returns
    return {
        "name": name,
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "ann_vol": float(ann_vol),
        "hit_rate": float(hit_rate),
        "total_days": int(total_days),
        "years": float(years),
        "returns": port_ret,
    }


def dm_test(ret1, ret2, loss="se"):
    """
    Diebold-Mariano test (HAC). Returns t-stat and p-value.
    H0: equal predictive accuracy.
    loss='se': squared error-based (default for returns context: d = r1² - r2²)
    Actually for strategy returns, we use d = ret1 - ret2 and test if mean>0.
    """
    d = ret1 - ret2
    n = len(d)
    # HAC variance (Newey-West, 5 lags)
    d_mean = d.mean()
    gamma0 = np.var(d, ddof=1)
    lags = 5
    gamma_sum = gamma0
    for lag in range(1, lags + 1):
        cov = np.cov(d[lag:], d[:-lag])[0, 1]
        gamma_sum += 2 * (1 - lag / (lags + 1)) * cov
    se = np.sqrt(max(gamma_sum, 1e-12) / n)
    t_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def run_experiment():
    # ── 1. Data ──────────────────────────────────────────────────────────────
    df = download_data()
    df = compute_vix_shocks(df)
    df = df.dropna()

    # ── 2. Build shock guard masks (lagged: yesterday's shock → today's flag) ─
    # NOTE: build_guard_mask already applies the lag internally (shock[i-1] → mask[i])
    guard_any = build_guard_mask(df["vix_shock_any"])
    guard_spike = build_guard_mask(df["vix_spike"])
    guard_drop = build_guard_mask(df["vix_drop"])

    print(f"\n  Guard active days (any shock): {guard_any.sum()} ({100*guard_any.mean():.1f}%)")
    print(f"  Guard active days (spike only): {guard_spike.sum()} ({100*guard_spike.mean():.1f}%)")

    # ── 3. Baseline weight: 12/VIX (shifted 1 day) ──────────────────────────
    # Use t-1 VIX → t weight. This is the standard lag.
    vix_lag1 = df["vix"].shift(1)
    base_weight = (12.0 / vix_lag1).clip(0, 1)

    # ── 4. Strategy weights ──────────────────────────────────────────────────
    # A. VIX Shock Guard: reduce to 50% during guard
    weight_guard = base_weight.copy()
    weight_guard[guard_any == 1] = base_weight[guard_any == 1] * 0.5

    # B. VIX Shock Binary: go to cash during guard
    weight_binary = base_weight.copy()
    weight_binary[guard_any == 1] = 0.0

    # C. VIX Spike Only: only reduce on spikes (fear rises)
    weight_spike = base_weight.copy()
    weight_spike[guard_spike == 1] = base_weight[guard_spike == 1] * 0.5

    # D. VIX Drop Boost: boost to 100% when fear drops (contrarian)
    weight_drop = base_weight.copy()
    weight_drop[guard_drop == 1] = 1.0

    spy_ret = df["spy_ret"]

    # ── 5. Backtest all strategies ───────────────────────────────────────────
    print("\nBacktesting strategies...")

    results_full = {}
    results_oos = {}

    strategies = {
        "Baseline_12VIX": base_weight,
        "VIX_Shock_Guard_50pct": weight_guard,
        "VIX_Shock_Binary_Cash": weight_binary,
        "VIX_Spike_Only_50pct": weight_spike,
        "VIX_Drop_Boost_100pct": weight_drop,
        "BuyAndHold_SPY": pd.Series(1.0, index=df.index),
    }

    oos_mask = df.index >= OOS_START

    for name, w in strategies.items():
        res_full = backtest(spy_ret, w, name=name)
        res_oos = backtest(
            spy_ret[oos_mask],
            w[oos_mask],
            name=name + "_OOS"
        )
        results_full[name] = res_full
        results_oos[name] = res_oos

        print(f"  {name:35s} Full: Sharpe={res_full['sharpe']:.3f}, MDD={res_full['mdd']:.1%}, "
              f"CAGR={res_full['cagr']:.1%} | "
              f"OOS: Sharpe={res_oos['sharpe']:.3f}, MDD={res_oos['mdd']:.1%}")

    # ── 6. DM tests vs baseline (full period) ───────────────────────────────
    print("\nDM tests vs Baseline_12VIX (full period):")
    base_ret = results_full["Baseline_12VIX"]["returns"]
    dm_results = {}

    for name in ["VIX_Shock_Guard_50pct", "VIX_Shock_Binary_Cash",
                 "VIX_Spike_Only_50pct", "VIX_Drop_Boost_100pct"]:
        strat_ret = results_full[name]["returns"]
        t_stat, p_val = dm_test(strat_ret, base_ret)
        dm_results[name] = {"t_stat": t_stat, "p_val": p_val,
                             "harvey_pass": abs(t_stat) > 3.0}
        print(f"  {name:35s} t={t_stat:+.3f}, p={p_val:.3f}, Harvey(t>3.0): {'PASS' if abs(t_stat)>3.0 else 'FAIL'}")

    # DM tests OOS
    print("\nDM tests vs Baseline_12VIX (OOS 2023-):")
    base_ret_oos = results_oos["Baseline_12VIX"]["returns"]
    dm_oos = {}

    for name in ["VIX_Shock_Guard_50pct", "VIX_Shock_Binary_Cash",
                 "VIX_Spike_Only_50pct", "VIX_Drop_Boost_100pct"]:
        strat_ret_oos = results_oos[name]["returns"]
        t_stat, p_val = dm_test(strat_ret_oos, base_ret_oos)
        dm_oos[name] = {"t_stat": t_stat, "p_val": p_val,
                        "harvey_pass": abs(t_stat) > 3.0}
        print(f"  {name:35s} t={t_stat:+.3f}, p={p_val:.3f}, Harvey(t>3.0): {'PASS' if abs(t_stat)>3.0 else 'FAIL'}")

    # ── 7. Shock event analysis ──────────────────────────────────────────────
    print("\nShock event forward return analysis:")
    shock_days = df[df["vix_shock_any"] == 1].index
    spike_days = df[df["vix_spike"] == 1].index
    drop_days = df[df["vix_drop"] == 1].index

    # Forward 5-day SPY returns after shock
    fwd_5d_shock = []
    fwd_5d_spike = []
    fwd_5d_drop = []

    for d in shock_days:
        loc = df.index.get_loc(d)
        if loc + 5 < len(df):
            fwd = (1 + spy_ret.iloc[loc+1:loc+6]).prod() - 1
            fwd_5d_shock.append(fwd)

    for d in spike_days:
        loc = df.index.get_loc(d)
        if loc + 5 < len(df):
            fwd = (1 + spy_ret.iloc[loc+1:loc+6]).prod() - 1
            fwd_5d_spike.append(fwd)

    for d in drop_days:
        loc = df.index.get_loc(d)
        if loc + 5 < len(df):
            fwd = (1 + spy_ret.iloc[loc+1:loc+6]).prod() - 1
            fwd_5d_drop.append(fwd)

    # Normal days (no shock yesterday)
    no_shock = df[df["vix_shock_any"] == 0].index
    fwd_5d_normal = []
    for d in no_shock:
        loc = df.index.get_loc(d)
        if loc + 5 < len(df):
            fwd = (1 + spy_ret.iloc[loc+1:loc+6]).prod() - 1
            fwd_5d_normal.append(fwd)

    def fmt(lst):
        if not lst:
            return "N/A"
        a = np.array(lst)
        t, p = stats.ttest_1samp(a, 0)
        return f"mean={np.mean(a):.3%}, std={np.std(a):.3%}, N={len(a)}, t={t:.2f}, p={p:.3f}"

    fwd_analysis = {
        "any_shock": {
            "mean": float(np.mean(fwd_5d_shock)) if fwd_5d_shock else None,
            "std": float(np.std(fwd_5d_shock)) if fwd_5d_shock else None,
            "n": len(fwd_5d_shock),
            "t_stat": float(stats.ttest_1samp(fwd_5d_shock, 0)[0]) if fwd_5d_shock else None,
            "p_val": float(stats.ttest_1samp(fwd_5d_shock, 0)[1]) if fwd_5d_shock else None,
        },
        "spike": {
            "mean": float(np.mean(fwd_5d_spike)) if fwd_5d_spike else None,
            "std": float(np.std(fwd_5d_spike)) if fwd_5d_spike else None,
            "n": len(fwd_5d_spike),
            "t_stat": float(stats.ttest_1samp(fwd_5d_spike, 0)[0]) if fwd_5d_spike else None,
            "p_val": float(stats.ttest_1samp(fwd_5d_spike, 0)[1]) if fwd_5d_spike else None,
        },
        "drop": {
            "mean": float(np.mean(fwd_5d_drop)) if fwd_5d_drop else None,
            "std": float(np.std(fwd_5d_drop)) if fwd_5d_drop else None,
            "n": len(fwd_5d_drop),
            "t_stat": float(stats.ttest_1samp(fwd_5d_drop, 0)[0]) if fwd_5d_drop else None,
            "p_val": float(stats.ttest_1samp(fwd_5d_drop, 0)[1]) if fwd_5d_drop else None,
        },
        "normal": {
            "mean": float(np.mean(fwd_5d_normal)) if fwd_5d_normal else None,
            "std": float(np.std(fwd_5d_normal)) if fwd_5d_normal else None,
            "n": len(fwd_5d_normal),
        },
    }

    print(f"  After any shock: {fmt(fwd_5d_shock)}")
    print(f"  After spike:     {fmt(fwd_5d_spike)}")
    print(f"  After drop:      {fmt(fwd_5d_drop)}")
    print(f"  Normal days:     {fmt(fwd_5d_normal)}")

    # ── 8. Compile results JSON ──────────────────────────────────────────────
    def strip_returns(d):
        """Remove pandas Series from dict for JSON serialization."""
        return {k: v for k, v in d.items() if k != "returns"}

    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Event-Surprise Volatility Strategy: VIX Shock Guard",
        "hypothesis": "VIX daily change > 2σ captures surprise events. Reducing equity after large VIX shocks should improve risk-adjusted returns.",
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{START_DATE} to {END_DATE}",
        "oos_period": f"{OOS_START} to {END_DATE}",
        "n_total": len(df),
        "n_oos": int(oos_mask.sum()),
        "shock_stats": {
            "total_shocks": int(df["vix_shock_any"].sum()),
            "spikes": int(df["vix_spike"].sum()),
            "drops": int(df["vix_drop"].sum()),
            "shock_pct": float(df["vix_shock_any"].mean() * 100),
            "threshold_sigma": SHOCK_THRESHOLD,
            "guard_days": GUARD_DAYS,
        },
        "guard_stats": {
            "any_shock_guard_days": int(guard_any.sum()),
            "spike_guard_days": int(guard_spike.sum()),
            "drop_guard_days": int(guard_drop.sum()),
        },
        "full_period_metrics": {
            name: strip_returns(res)
            for name, res in results_full.items()
        },
        "oos_metrics": {
            name: strip_returns(res)
            for name, res in results_oos.items()
        },
        "dm_tests_full": dm_results,
        "dm_tests_oos": dm_oos,
        "forward_return_analysis": fwd_analysis,
        "parameters": {
            "shock_window": SHOCK_WINDOW,
            "shock_threshold_sigma": SHOCK_THRESHOLD,
            "guard_days": GUARD_DAYS,
            "tx_cost_bps": TX_COST * 10000,
            "lag": "signal.shift(1) — yesterday's shock, today's action",
        },
        "conclusion": "",  # filled after analysis
        "references": [
            "K498 (calendar dummies NULL — motivates surprise-based approach)",
            "Codex #5 suggestion: use surprise component not calendar dummy",
            "Moreira & Muir (2017): volatility timing strategies",
        ],
        "run_date": datetime.now().isoformat(),
    }

    # ── 9. Determine conclusion ──────────────────────────────────────────────
    # Check if any strategy beats baseline with Harvey t > 3.0
    winners = [k for k, v in dm_results.items() if v["harvey_pass"] and v["t_stat"] > 0]
    losers_dm = [k for k, v in dm_results.items() if v["t_stat"] < -1]

    guard_sharpe = results_full["VIX_Shock_Guard_50pct"]["sharpe"]
    base_sharpe = results_full["Baseline_12VIX"]["sharpe"]

    if winners:
        conclusion = (
            f"POSITIVE: {len(winners)} strategy variants pass Harvey t>3.0 vs 12/VIX baseline. "
            f"VIX surprise captures real information beyond calendar effects."
        )
    elif guard_sharpe > base_sharpe + 0.1:
        conclusion = (
            f"PARTIAL: Guard strategy improves Sharpe ({guard_sharpe:.3f} vs {base_sharpe:.3f}) "
            f"but DM t-stat below Harvey threshold. Effect real but not statistically decisive."
        )
    else:
        conclusion = (
            f"NULL: VIX shock guard does not consistently improve on 12/VIX baseline "
            f"(Guard Sharpe={guard_sharpe:.3f} vs Base={base_sharpe:.3f}). "
            f"VIX already encodes surprise via its level; daily change adds no independent signal."
        )

    output["conclusion"] = conclusion
    print(f"\nConclusion: {conclusion}")

    return output


if __name__ == "__main__":
    results = run_experiment()

    out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k801_event_surprise_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nResults saved to: {out_path}")
    print("K801 complete.")
