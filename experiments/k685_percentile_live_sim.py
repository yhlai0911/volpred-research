"""K685: VIX Percentile Strategy — Live Period Simulation (2025-2026)

Motivation:
  K684 optimized the percentile strategy with backtest data (2006-2026, full period).
  Now we SIMULATE it on the 2025-01-01 to 2026-03-27 LIVE period — the same window
  that K640 audited for piecewise_conservative (live Sharpe 3.98).

  Key question: Would percentile have beaten Piecewise Conservative during the
  2025 tariff shock (VIX peak 52.33 in April 2025)?

Strategies simulated:
  a. Percentile 50/50 (K679 original): w = 1 - pct(VIX, 252d), 50/50 SPY/GLD
  b. Percentile 70/30 (K684 optimal): same signal, 70/30 SPY/GLD, 2% threshold
  c. P3-AGG lookup: VIX<15 → 80%, 15-25 → 45%, >25 → 10%, 50/50 SPY/GLD

Comparison vs existing live strategies (from paper_trading.json):
  - Piecewise Conservative
  - 50/50 SPY/GLD (recommended_5050)
  - 12/VIX (simple_12vix)
  - Buy-and-Hold SPY

NOTE: This is a SIMULATION, not actual paper trading. The percentile strategies
were NOT run live during this period. We reconstruct what WOULD have happened.

References:
  - K679: VIX Percentile Strategy — original discovery
  - K680: Cross-OOS validation (5/5 wins, DM t=3.157)
  - K682: P3-AGG lookup table
  - K684: Optimal implementation (252d, 2% threshold, 70/30)
  - K640: Piecewise Conservative live audit

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27 (for VIX percentile calculation)
Live simulation: 2025-01-01 to 2026-03-27

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
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-28"  # download to today
LIVE_START = "2025-01-01"
ROLLING_WINDOW = 252
TC_BPS = 5               # Transaction cost in basis points (one-way)
RF_DAILY = 0.04 / 252    # ~4% annual risk-free for cash portion
THRESHOLD_PCT = 0.02     # 2% weight change threshold for K684 variant


def download_data():
    """Download SPY, GLD, VIX data."""
    print("Downloading SPY, GLD, ^VIX data...")
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    gld = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)

    # Handle MultiIndex columns from newer yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy_close = spy["Close"].copy()
    spy_close.name = "spy_close"
    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = gld["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = vix["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close, spy_close], axis=1).dropna()
    print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} days")
    return data


def compute_vix_percentile(data):
    """Compute rolling 252-day VIX percentile rank."""
    vix = data["vix"]

    def rolling_percentile(series, window=ROLLING_WINDOW):
        result = pd.Series(index=series.index, dtype=float)
        vals = series.values
        for i in range(window, len(vals)):
            window_vals = vals[i - window:i]
            result.iloc[i] = sp_stats.percentileofscore(window_vals, vals[i]) / 100.0
        return result

    data = data.copy()
    data["vix_percentile"] = rolling_percentile(vix)
    return data


def simulate_percentile_5050(data, live_mask):
    """Strategy A: K679 original — w = 1 - pct(VIX, 252d), 50/50 SPY/GLD."""
    df = data[live_mask].copy()
    pct = df["vix_percentile"].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret
    strategy_ret = np.zeros(len(df))
    tc_rate = TC_BPS / 10000.0
    prev_w = 0.5  # start at moderate exposure

    weights = []
    for i in range(len(df)):
        w = 1.0 - pct[i] if not np.isnan(pct[i]) else prev_w
        w = np.clip(w, 0.0, 1.0)

        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        weights.append(w)
        prev_w = w

    return np.array(weights), strategy_ret, df.index


def simulate_percentile_7030(data, live_mask):
    """Strategy B: K684 optimal — 252d percentile, 70/30 SPY/GLD, 2% threshold, 5% floor."""
    df = data[live_mask].copy()
    pct = df["vix_percentile"].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    portfolio_ret = 0.7 * spy_ret + 0.3 * gld_ret
    strategy_ret = np.zeros(len(df))
    tc_rate = TC_BPS / 10000.0
    prev_w = 0.5  # start at moderate exposure

    weights = []
    for i in range(len(df)):
        target_w = 1.0 - pct[i] if not np.isnan(pct[i]) else prev_w
        target_w = np.clip(target_w, 0.05, 1.0)  # 5% floor

        # 2% threshold: only change if target differs by > 2%
        if abs(target_w - prev_w) < THRESHOLD_PCT:
            w = prev_w
        else:
            w = target_w

        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        weights.append(w)
        prev_w = w

    return np.array(weights), strategy_ret, df.index


def simulate_p3agg(data, live_mask):
    """Strategy C: P3-AGG lookup — VIX<15→80%, 15-25→45%, >25→10%, 50/50 SPY/GLD."""
    df = data[live_mask].copy()
    vix = df["vix"].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret
    strategy_ret = np.zeros(len(df))
    tc_rate = TC_BPS / 10000.0
    prev_w = 0.45  # start at mid-range

    weights = []
    for i in range(len(df)):
        v = vix[i]
        if v < 15:
            w = 0.80
        elif v < 25:
            w = 0.45
        else:
            w = 0.10

        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        weights.append(w)
        prev_w = w

    return np.array(weights), strategy_ret, df.index


def simulate_bh_spy(data, live_mask):
    """Buy-and-Hold SPY (100% SPY)."""
    df = data[live_mask].copy()
    return np.ones(len(df)), df["spy_ret"].values, df.index


def compute_metrics(strategy_ret, name, n_days):
    """Compute standard performance metrics."""
    cum_ret = np.cumprod(1 + strategy_ret)
    total_ret = cum_ret[-1] - 1
    n_years = n_days / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    ann_ret = np.mean(strategy_ret) * 252
    ann_vol = np.std(strategy_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio
    downside = strategy_ret[strategy_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    return {
        "strategy": name,
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": n_days,
    }


def load_paper_trading_metrics():
    """Load actual paper trading results for comparison."""
    pt_path = Path(__file__).parent.parent / "storage" / "paper_trading.json"
    with open(pt_path) as f:
        pt_data = json.load(f)

    results = {}
    for key in ["piecewise_conservative", "simple_12vix", "recommended_5050"]:
        entries = pt_data.get(key, {}).get("entries", [])
        live = [e for e in entries if e.get("data_date", "") >= "2025-01-01"]
        if live:
            rets = np.array([e.get("portfolio_return", 0) or 0 for e in live])
            n_days = len(rets)
            cum = np.cumprod(1 + rets)
            total_ret = cum[-1] - 1
            ann_ret = np.mean(rets) * 252
            ann_vol = np.std(rets, ddof=1) * np.sqrt(252)
            sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0
            cagr = (cum[-1]) ** (252 / n_days) - 1
            running_max = np.maximum.accumulate(cum)
            mdd = np.min((cum - running_max) / running_max)

            # Sortino
            downside = rets[rets < 0]
            downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
            sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

            display_names = {
                "piecewise_conservative": "Piecewise Conservative (LIVE)",
                "simple_12vix": "12/VIX (LIVE)",
                "recommended_5050": "50/50 SPY/GLD (LIVE)",
            }

            results[key] = {
                "strategy": display_names[key],
                "cagr_pct": round(cagr * 100, 2),
                "sharpe": round(sharpe, 3),
                "sortino": round(sortino, 3),
                "mdd_pct": round(mdd * 100, 2),
                "calmar": round((cagr / abs(mdd)) if mdd != 0 else 0, 3),
                "ann_vol_pct": round(ann_vol * 100, 2),
                "total_return_pct": round(total_ret * 100, 2),
                "n_days": n_days,
                "source": "paper_trading.json (actual live)",
            }

    return results


def tariff_shock_analysis(data, weights_dict, dates):
    """Analyze behavior during April 2025 tariff shock (VIX peak ~52)."""
    # Find the VIX peak in 2025
    live_data = data[data.index >= LIVE_START].copy()
    vix_series = live_data["vix"]

    # Peak VIX date
    peak_idx = vix_series.idxmax()
    peak_vix = float(vix_series.loc[peak_idx])

    # Define shock period: 1 week before and 2 weeks after peak
    shock_start = peak_idx - pd.Timedelta(days=14)
    shock_end = peak_idx + pd.Timedelta(days=30)

    analysis = {
        "vix_peak_date": peak_idx.strftime("%Y-%m-%d"),
        "vix_peak_value": round(peak_vix, 2),
        "shock_window": f"{shock_start.strftime('%Y-%m-%d')} to {shock_end.strftime('%Y-%m-%d')}",
        "strategy_behavior": {},
    }

    # For each strategy, what was the weight at peak? How fast recovery?
    for strat_name, (weights, strat_ret, strat_dates) in weights_dict.items():
        date_series = pd.Series(weights, index=strat_dates)
        ret_series = pd.Series(strat_ret, index=strat_dates)

        # Weight at peak
        if peak_idx in date_series.index:
            weight_at_peak = float(date_series.loc[peak_idx])
        else:
            # Find closest date
            closest = date_series.index[date_series.index.get_indexer([peak_idx], method="nearest")[0]]
            weight_at_peak = float(date_series.loc[closest])

        # Weight 1 week before peak
        pre_peak = peak_idx - pd.Timedelta(days=7)
        pre_dates = date_series.index[date_series.index <= pre_peak]
        weight_pre = float(date_series.loc[pre_dates[-1]]) if len(pre_dates) > 0 else None

        # Weight 2 weeks after peak
        post_peak = peak_idx + pd.Timedelta(days=14)
        post_dates = date_series.index[date_series.index >= post_peak]
        weight_post = float(date_series.loc[post_dates[0]]) if len(post_dates) > 0 else None

        # Weight 1 month after peak
        month_after = peak_idx + pd.Timedelta(days=30)
        month_dates = date_series.index[date_series.index >= month_after]
        weight_month = float(date_series.loc[month_dates[0]]) if len(month_dates) > 0 else None

        # Return during shock window
        shock_mask = (ret_series.index >= shock_start) & (ret_series.index <= shock_end)
        shock_rets = ret_series[shock_mask]
        shock_total = float((1 + shock_rets).prod() - 1) if len(shock_rets) > 0 else 0

        # Days to recover to 50% weight (proxy for re-entry speed)
        post_peak_weights = date_series[date_series.index > peak_idx]
        recovery_days = None
        for j, (d, w) in enumerate(post_peak_weights.items()):
            if w >= 0.50:
                recovery_days = (d - peak_idx).days
                break

        analysis["strategy_behavior"][strat_name] = {
            "weight_at_peak": round(weight_at_peak, 4),
            "weight_1w_before": round(weight_pre, 4) if weight_pre is not None else None,
            "weight_2w_after": round(weight_post, 4) if weight_post is not None else None,
            "weight_1m_after": round(weight_month, 4) if weight_month is not None else None,
            "shock_window_return_pct": round(shock_total * 100, 2),
            "days_to_50pct_weight": recovery_days,
        }

    return analysis


def dm_test_comparison(ret_a, ret_b, name_a, name_b):
    """Diebold-Mariano style comparison of two return series."""
    # Align indices
    common = ret_a.index.intersection(ret_b.index)
    a = ret_a.loc[common].values
    b = ret_b.loc[common].values
    diff = b - a

    if len(diff) < 30:
        return None

    mean_diff = np.mean(diff)
    se_diff = np.std(diff, ddof=1) / np.sqrt(len(diff))
    t_stat = mean_diff / se_diff if se_diff > 0 else 0
    p_val = float(2 * sp_stats.t.sf(abs(t_stat), df=len(diff) - 1))

    return {
        "comparison": f"{name_b} vs {name_a}",
        "mean_diff_bps_daily": round(mean_diff * 10000, 3),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_val, 4),
        "significant_5pct": p_val < 0.05,
        "harvey_pass": abs(t_stat) > 3.0,
        "n_obs": len(diff),
    }


def monthly_returns_comparison(weights_dict, data, live_mask):
    """Compare monthly returns across strategies."""
    live_data = data[live_mask].copy()

    monthly_results = {}
    for strat_name, (weights, strat_ret, strat_dates) in weights_dict.items():
        ret_series = pd.Series(strat_ret, index=strat_dates)
        monthly = (1 + ret_series).resample("ME").prod() - 1
        monthly_results[strat_name] = {
            m.strftime("%Y-%m"): round(float(v) * 100, 2)
            for m, v in monthly.items()
        }

    return monthly_results


def main():
    print("=" * 70)
    print("K685: VIX Percentile Strategy — Live Period Simulation (2025-2026)")
    print("=" * 70)
    print("NOTE: This is a SIMULATION, not actual paper trading.")
    print()

    # Step 1: Download data
    data = download_data()

    # Step 2: VIX descriptive stats for live period
    live_mask = data.index >= LIVE_START
    live_data = data[live_mask]
    vix_live = live_data["vix"]

    print(f"\n--- Live Period VIX Stats ({LIVE_START} to {data.index[-1].date()}) ---")
    print(f"  Mean: {vix_live.mean():.2f}")
    print(f"  Std:  {vix_live.std():.2f}")
    print(f"  Min:  {vix_live.min():.2f}")
    print(f"  Max:  {vix_live.max():.2f}")
    print(f"  Days: {len(vix_live)}")

    vix_live_stats = {
        "mean": round(float(vix_live.mean()), 2),
        "std": round(float(vix_live.std()), 2),
        "min": round(float(vix_live.min()), 2),
        "max": round(float(vix_live.max()), 2),
        "median": round(float(vix_live.median()), 2),
        "n_days_above_25": int((vix_live > 25).sum()),
        "n_days_above_30": int((vix_live > 30).sum()),
        "n_days_below_15": int((vix_live < 15).sum()),
    }

    # Step 3: Compute VIX percentile (needs full history)
    print("\n--- Computing VIX rolling percentile (252d) ---")
    data = compute_vix_percentile(data)
    live_mask = data.index >= LIVE_START  # re-create after copy

    # Check percentile at key dates
    live_pct = data[live_mask]["vix_percentile"]
    print(f"  Live period percentile range: [{live_pct.min():.3f}, {live_pct.max():.3f}]")
    print(f"  Live period percentile mean: {live_pct.mean():.3f}")

    # Step 4: Simulate all three percentile variants
    print("\n--- Simulating Percentile Strategies ---")

    w_p5050, ret_p5050, dates_p5050 = simulate_percentile_5050(data, live_mask)
    print(f"  Percentile 50/50: {len(ret_p5050)} days simulated")

    w_p7030, ret_p7030, dates_p7030 = simulate_percentile_7030(data, live_mask)
    print(f"  Percentile 70/30: {len(ret_p7030)} days simulated")

    w_p3agg, ret_p3agg, dates_p3agg = simulate_p3agg(data, live_mask)
    print(f"  P3-AGG Lookup: {len(ret_p3agg)} days simulated")

    w_bh, ret_bh, dates_bh = simulate_bh_spy(data, live_mask)
    print(f"  B&H SPY: {len(ret_bh)} days simulated")

    # Step 5: Compute metrics for simulated strategies
    print("\n--- Performance Metrics (Live Simulation) ---")
    sim_results = {}

    strategies_sim = [
        ("Percentile 50/50 (SIM)", ret_p5050, w_p5050),
        ("Percentile 70/30 (SIM)", ret_p7030, w_p7030),
        ("P3-AGG Lookup (SIM)", ret_p3agg, w_p3agg),
        ("Buy-Hold SPY (SIM)", ret_bh, w_bh),
    ]

    for name, ret, w in strategies_sim:
        metrics = compute_metrics(ret, name, len(ret))
        metrics["avg_weight"] = round(float(np.mean(w)), 3)
        sim_results[name] = metrics
        print(f"\n  {name}:")
        print(f"    CAGR: {metrics['cagr_pct']:.2f}%")
        print(f"    Sharpe: {metrics['sharpe']:.3f}")
        print(f"    MDD: {metrics['mdd_pct']:.2f}%")
        print(f"    Sortino: {metrics['sortino']:.3f}")
        print(f"    Avg weight: {metrics['avg_weight']:.3f}")

    # Step 6: Load paper trading comparison data
    print("\n--- Paper Trading Comparison (Actual LIVE) ---")
    pt_results = load_paper_trading_metrics()
    for key, metrics in pt_results.items():
        print(f"\n  {metrics['strategy']}:")
        print(f"    CAGR: {metrics['cagr_pct']:.2f}%")
        print(f"    Sharpe: {metrics['sharpe']:.3f}")
        print(f"    MDD: {metrics['mdd_pct']:.2f}%")

    # Step 7: Tariff shock analysis
    print("\n--- Tariff Shock Analysis (VIX Peak ~52) ---")

    weights_dict = {
        "Percentile 50/50": (w_p5050, ret_p5050, dates_p5050),
        "Percentile 70/30": (w_p7030, ret_p7030, dates_p7030),
        "P3-AGG Lookup": (w_p3agg, ret_p3agg, dates_p3agg),
        "Buy-Hold SPY": (w_bh, ret_bh, dates_bh),
    }

    shock_analysis = tariff_shock_analysis(data, weights_dict, dates_p5050)
    print(f"\n  VIX Peak: {shock_analysis['vix_peak_value']} on {shock_analysis['vix_peak_date']}")
    print(f"  Shock window: {shock_analysis['shock_window']}")

    for sname, sinfo in shock_analysis["strategy_behavior"].items():
        print(f"\n  {sname}:")
        print(f"    Weight at peak: {sinfo['weight_at_peak']:.4f}")
        print(f"    Weight 1w before: {sinfo['weight_1w_before']}")
        print(f"    Weight 2w after: {sinfo['weight_2w_after']}")
        print(f"    Weight 1m after: {sinfo['weight_1m_after']}")
        print(f"    Shock window return: {sinfo['shock_window_return_pct']:.2f}%")
        print(f"    Days to 50% weight: {sinfo['days_to_50pct_weight']}")

    # Step 8: DM test comparisons
    print("\n--- Statistical Comparisons (DM Test) ---")

    ret_series = {
        "Percentile 50/50": pd.Series(ret_p5050, index=dates_p5050),
        "Percentile 70/30": pd.Series(ret_p7030, index=dates_p7030),
        "P3-AGG Lookup": pd.Series(ret_p3agg, index=dates_p3agg),
        "Buy-Hold SPY": pd.Series(ret_bh, index=dates_bh),
    }

    dm_results = []

    # Compare each percentile vs B&H SPY
    for name in ["Percentile 50/50", "Percentile 70/30", "P3-AGG Lookup"]:
        dm = dm_test_comparison(
            ret_series["Buy-Hold SPY"], ret_series[name],
            "Buy-Hold SPY", name
        )
        if dm:
            dm_results.append(dm)
            sig = "HARVEY PASS" if dm["harvey_pass"] else ("*" if dm["significant_5pct"] else "ns")
            print(f"  {dm['comparison']}: t={dm['t_stat']:.3f} ({sig})")

    # Compare percentile variants vs each other
    dm = dm_test_comparison(
        ret_series["Percentile 50/50"], ret_series["Percentile 70/30"],
        "Percentile 50/50", "Percentile 70/30"
    )
    if dm:
        dm_results.append(dm)
        sig = "HARVEY PASS" if dm["harvey_pass"] else ("*" if dm["significant_5pct"] else "ns")
        print(f"  {dm['comparison']}: t={dm['t_stat']:.3f} ({sig})")

    # Step 9: Monthly returns
    print("\n--- Monthly Returns Comparison ---")
    monthly = monthly_returns_comparison(weights_dict, data, live_mask)
    months = sorted(set().union(*(m.keys() for m in monthly.values())))

    print(f"\n  {'Month':<10}", end="")
    for sname in weights_dict:
        print(f"  {sname[:12]:>12}", end="")
    print()

    for month in months:
        print(f"  {month:<10}", end="")
        for sname in weights_dict:
            val = monthly.get(sname, {}).get(month, None)
            if val is not None:
                print(f"  {val:>11.2f}%", end="")
            else:
                print(f"  {'N/A':>12}", end="")
        print()

    # Step 10: Key findings summary
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    findings = []

    # Ranking
    all_results = {}
    all_results.update(sim_results)
    for key, val in pt_results.items():
        all_results[val["strategy"]] = val

    ranked = sorted(all_results.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    print("\n  Strategy Ranking by Sharpe (live period):")
    for i, (name, m) in enumerate(ranked, 1):
        label = "(SIM)" if "(SIM)" in name else "(LIVE)"
        print(f"    {i}. {name}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr_pct']:.2f}%, MDD={m['mdd_pct']:.2f}%")
        findings.append(f"#{i} {name}: Sharpe={m['sharpe']:.3f}")

    # Key question: Did percentile beat piecewise?
    pc_sharpe = pt_results.get("piecewise_conservative", {}).get("sharpe", 0)
    p5050_sharpe = sim_results.get("Percentile 50/50 (SIM)", {}).get("sharpe", 0)
    p7030_sharpe = sim_results.get("Percentile 70/30 (SIM)", {}).get("sharpe", 0)

    if p7030_sharpe > pc_sharpe:
        findings.append(f"Percentile 70/30 BEATS Piecewise (Sharpe {p7030_sharpe:.3f} vs {pc_sharpe:.3f})")
    elif p5050_sharpe > pc_sharpe:
        findings.append(f"Percentile 50/50 BEATS Piecewise (Sharpe {p5050_sharpe:.3f} vs {pc_sharpe:.3f})")
    else:
        findings.append(f"Piecewise remains BEST in live period (Sharpe {pc_sharpe:.3f} vs Percentile 70/30 {p7030_sharpe:.3f})")

    # Tariff shock key finding
    peak_vix = shock_analysis["vix_peak_value"]
    p5050_at_peak = shock_analysis["strategy_behavior"].get("Percentile 50/50", {}).get("weight_at_peak", None)
    p7030_at_peak = shock_analysis["strategy_behavior"].get("Percentile 70/30", {}).get("weight_at_peak", None)
    if p5050_at_peak is not None:
        findings.append(f"At VIX peak {peak_vix}: Percentile 50/50 weight={p5050_at_peak:.4f}, 70/30 weight={p7030_at_peak:.4f}")

    p5050_recovery = shock_analysis["strategy_behavior"].get("Percentile 50/50", {}).get("days_to_50pct_weight", None)
    p7030_recovery = shock_analysis["strategy_behavior"].get("Percentile 70/30", {}).get("days_to_50pct_weight", None)
    findings.append(f"Recovery to 50% weight: Percentile 50/50={p5050_recovery}d, 70/30={p7030_recovery}d")

    for finding in findings:
        print(f"\n  - {finding}")

    # ============================================================================
    # Save results
    # ============================================================================
    results = {
        "experiment_id": "K685",
        "title": "VIX Percentile Strategy — Live Period Simulation (2025-2026)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "type": "SIMULATION (not actual paper trading)",
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{START_DATE} to {data.index[-1].date()}",
        "live_simulation_period": f"{LIVE_START} to {data.index[-1].date()}",
        "n_live_days": int(live_mask.sum()),
        "methodology": {
            "strategies_simulated": {
                "Percentile 50/50": "w = 1 - pct(VIX, 252d), 50/50 SPY/GLD (K679 original)",
                "Percentile 70/30": "w = 1 - pct(VIX, 252d), 70/30 SPY/GLD, 2% threshold, 5% floor (K684 optimal)",
                "P3-AGG Lookup": "VIX<15→80%, 15-25→45%, >25→10%, 50/50 SPY/GLD (K682)",
            },
            "comparison_strategies": {
                "Piecewise Conservative": "From paper_trading.json (actual live)",
                "12/VIX": "From paper_trading.json (actual live)",
                "50/50 SPY/GLD": "From paper_trading.json (actual live)",
                "Buy-Hold SPY": "100% SPY (simulated)",
            },
            "transaction_cost": f"{TC_BPS} bps one-way",
            "risk_free_rate": "4% annual",
            "rolling_window": ROLLING_WINDOW,
        },
        "references": [
            "K679: VIX Percentile Strategy (Sharpe 1.68 vs 12/VIX 1.08)",
            "K680: Cross-OOS Validation (5/5 wins, DM t=3.157)",
            "K682: P3-AGG Lookup Table",
            "K684: Optimal Implementation (252d, 2%thresh, 70/30)",
            "K640: Piecewise Conservative live audit (Sharpe 3.98)",
        ],
        "vix_live_stats": vix_live_stats,
        "simulated_strategy_metrics": sim_results,
        "paper_trading_metrics": pt_results,
        "tariff_shock_analysis": shock_analysis,
        "dm_test_results": dm_results,
        "monthly_returns": monthly,
        "key_findings": findings,
    }

    out_path = Path(__file__).parent / "k685_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
