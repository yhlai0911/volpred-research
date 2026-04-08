#!/usr/bin/env python3
"""
K869: VIX-Based Sector Rotation — Can VIX Timing Add Alpha to Sector Allocation?

Research Questions:
1. Does VIX-based sector rotation beat equal-weight sector portfolio?
2. Does it beat SPY (the cap-weighted benchmark)?
3. Is the alpha from sector selection or from VIX timing?

Error log rules applied:
- signal = signal.shift(1) — MANDATORY lag
- DM test: use volpred.stats.model_evaluation.strategy_dm_test
- Sharpe > 2x baseline = almost certainly bug, STOP and check

Prior work:
- K58: Sector VT Map — gamma doesn't predict sector VT effect, all sectors benefit from VT
- K243: Sector Rotation (basic)
- K560: Sector Rotation with VT — Momentum sector selection improves VT
- K562: Sector Momentum Validation — Daily PASS but Monthly FAIL
- K415: CSVD null result — VIX sufficient #29

Data: yfinance (sector ETFs, ^VIX, SPY), 2005-01 to 2026-04
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Config ──────────────────────────────────────────────────────────────────
GROWTH_SECTORS = ["XLK", "XLY", "XLF", "XLI", "XLB"]  # XLRE excluded (only since 2015)
DEFENSIVE_SECTORS = ["XLV", "XLU", "XLP", "XLE"]
ALL_SECTORS = GROWTH_SECTORS + DEFENSIVE_SECTORS
TICKERS = ALL_SECTORS + ["^VIX", "SPY"]

START = "2005-01-01"
END = "2026-04-05"

IS_END = "2018-12-31"  # In-sample: 2005-2018
# OOS: 2019-2026

REBALANCE_FREQ = "ME"  # Monthly rebalance (pandas >=2.2 uses 'ME')

OUTPUT_DIR = Path(__file__).parent
RESULTS_FILE = OUTPUT_DIR / "k869_results.json"


def download_data():
    """Download sector ETF, VIX, and SPY data."""
    print("Downloading data...")
    data = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    # Drop any ticker with all NaN
    close = close.dropna(how="all", axis=1)

    # Forward fill then drop remaining NaN rows
    close = close.ffill().dropna()

    print(f"Data: {close.index[0].date()} to {close.index[-1].date()}, {len(close)} days")
    print(f"Tickers available: {list(close.columns)}")

    return close


def compute_returns(close):
    """Compute daily returns for all tickers."""
    returns = close.pct_change().dropna()
    return returns


def get_vix_signal(close):
    """Get VIX signal with proper lag (shift(1) = use yesterday's VIX for today's allocation)."""
    vix = close["^VIX"].copy()
    # MANDATORY LAG: use previous day's VIX for today's allocation
    vix_signal = vix.shift(1)
    return vix_signal


def strategy_equal_weight(returns, sectors):
    """Equal-weight across all sectors, rebalanced monthly."""
    sector_rets = returns[sectors].copy()
    # Equal weight = 1/N
    weights = pd.DataFrame(1.0 / len(sectors), index=sector_rets.index, columns=sectors)
    port_ret = (sector_rets * weights).sum(axis=1)
    return port_ret


def strategy_static_growth(returns):
    """Static allocation: 100% growth sectors, equal-weight within."""
    return strategy_equal_weight(returns, GROWTH_SECTORS)


def strategy_static_defensive(returns):
    """Static allocation: 100% defensive sectors, equal-weight within."""
    return strategy_equal_weight(returns, DEFENSIVE_SECTORS)


def strategy_vix_binary(returns, vix_signal):
    """Binary VIX rotation: VIX < 20 → 100% growth; VIX >= 20 → 100% defensive."""
    growth_rets = returns[GROWTH_SECTORS].mean(axis=1)
    def_rets = returns[DEFENSIVE_SECTORS].mean(axis=1)

    # Monthly rebalance signal
    vix_monthly = vix_signal.resample(REBALANCE_FREQ).last().ffill()
    vix_daily = vix_monthly.reindex(returns.index, method="ffill")

    # Binary allocation (already lagged via vix_signal)
    growth_weight = (vix_daily < 20).astype(float)
    def_weight = 1.0 - growth_weight

    port_ret = growth_weight * growth_rets + def_weight * def_rets
    return port_ret


def strategy_vix_smooth(returns, vix_signal):
    """Smooth VIX rotation: weight_growth = clip((25 - VIX) / 10, 0, 1)."""
    growth_rets = returns[GROWTH_SECTORS].mean(axis=1)
    def_rets = returns[DEFENSIVE_SECTORS].mean(axis=1)

    vix_monthly = vix_signal.resample(REBALANCE_FREQ).last().ffill()
    vix_daily = vix_monthly.reindex(returns.index, method="ffill")

    growth_weight = np.clip((25.0 - vix_daily) / 10.0, 0.0, 1.0)
    def_weight = 1.0 - growth_weight

    port_ret = growth_weight * growth_rets + def_weight * def_rets
    return port_ret


def strategy_vix_3tier(returns, vix_signal):
    """3-tier VIX rotation: VIX<15 → 80/20 G/D; 15-25 → 50/50; >25 → 20/80."""
    growth_rets = returns[GROWTH_SECTORS].mean(axis=1)
    def_rets = returns[DEFENSIVE_SECTORS].mean(axis=1)

    vix_monthly = vix_signal.resample(REBALANCE_FREQ).last().ffill()
    vix_daily = vix_monthly.reindex(returns.index, method="ffill")

    growth_weight = pd.Series(0.5, index=returns.index)
    growth_weight[vix_daily < 15] = 0.80
    growth_weight[(vix_daily >= 15) & (vix_daily < 25)] = 0.50
    growth_weight[vix_daily >= 25] = 0.20
    def_weight = 1.0 - growth_weight

    port_ret = growth_weight * growth_rets + def_weight * def_rets
    return port_ret


def compute_metrics(returns_series, name, annual_factor=252):
    """Compute standard performance metrics."""
    r = returns_series.dropna()
    n = len(r)

    total_ret = (1 + r).prod() - 1
    years = n / annual_factor
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0

    ann_mean = r.mean() * annual_factor
    ann_std = r.std() * np.sqrt(annual_factor)
    sharpe = ann_mean / ann_std if ann_std > 0 else 0

    # Max Drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino (downside deviation)
    downside = r[r < 0]
    downside_std = downside.std() * np.sqrt(annual_factor) if len(downside) > 0 else ann_std
    sortino = ann_mean / downside_std if downside_std > 0 else 0

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    return {
        "name": name,
        "n_days": n,
        "cagr": round(cagr, 4),
        "ann_vol": round(ann_std, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 4),
        "total_return": round(total_ret, 4),
    }


def dm_test_wrapper(r1, r2, name1, name2):
    """Run DM test using standard module. Negative t → r1 better (higher returns)."""
    try:
        from volpred.stats.model_evaluation import strategy_dm_test
        t_stat, p_val = strategy_dm_test(
            np.asarray(r1, dtype=np.float64),
            np.asarray(r2, dtype=np.float64),
            h=1,
            loss_fn="negative_return",
        )
        harvey_pass = abs(t_stat) > 3.0
        return {
            "comparison": f"{name1} vs {name2}",
            "dm_t": round(t_stat, 4),
            "dm_p": round(p_val, 4),
            "harvey_pass": harvey_pass,
            "interpretation": f"{'Negative' if t_stat < 0 else 'Positive'} t → {name1 if t_stat < 0 else name2} worse loss (better return)" if abs(t_stat) > 1.96 else "Not significant",
        }
    except Exception as e:
        print(f"DM test error: {e}")
        # Fallback: simple DM
        d = np.asarray(r2, dtype=np.float64) - np.asarray(r1, dtype=np.float64)
        d_mean = np.mean(d)
        d_std = np.std(d, ddof=1)
        t_stat = d_mean / (d_std / np.sqrt(len(d))) if d_std > 0 else 0
        from scipy import stats
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(d)-1))
        return {
            "comparison": f"{name1} vs {name2}",
            "dm_t": round(t_stat, 4),
            "dm_p": round(p_val, 4),
            "harvey_pass": abs(t_stat) > 3.0,
            "interpretation": "fallback DM",
        }


def alpha_decomposition(strategies_dict, returns):
    """
    Decompose total alpha into sector selection alpha + VIX timing alpha.

    Timing alpha = VIX rotation Sharpe - best static allocation Sharpe
    Selection alpha = static allocation Sharpe - equal weight Sharpe
    """
    ew_sharpe = strategies_dict["Equal Weight"]["sharpe"]
    static_growth_sharpe = strategies_dict["Static Growth"]["sharpe"]
    static_def_sharpe = strategies_dict["Static Defensive"]["sharpe"]
    best_static = max(static_growth_sharpe, static_def_sharpe)
    best_static_name = "Static Growth" if static_growth_sharpe >= static_def_sharpe else "Static Defensive"

    decomposition = {}
    for name in ["VIX Binary", "VIX Smooth", "VIX 3-Tier"]:
        if name in strategies_dict:
            total_sharpe = strategies_dict[name]["sharpe"]
            selection_alpha = best_static - ew_sharpe
            timing_alpha = total_sharpe - best_static
            total_alpha_vs_ew = total_sharpe - ew_sharpe

            decomposition[name] = {
                "total_sharpe": total_sharpe,
                "ew_sharpe": ew_sharpe,
                "best_static": best_static,
                "best_static_name": best_static_name,
                "selection_alpha_sharpe": round(selection_alpha, 4),
                "timing_alpha_sharpe": round(timing_alpha, 4),
                "total_alpha_vs_ew": round(total_alpha_vs_ew, 4),
                "pct_from_selection": round(selection_alpha / total_alpha_vs_ew * 100, 1) if total_alpha_vs_ew != 0 else 0,
                "pct_from_timing": round(timing_alpha / total_alpha_vs_ew * 100, 1) if total_alpha_vs_ew != 0 else 0,
            }

    return decomposition


def rolling_analysis(returns_dict, window=252 * 3):
    """Rolling 3-year Sharpe ratio for key strategies."""
    results = {}
    for name, rets in returns_dict.items():
        rolling_sharpe = rets.rolling(window).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0,
            raw=True,
        )
        results[name] = {
            "mean_rolling_sharpe": round(rolling_sharpe.dropna().mean(), 4),
            "std_rolling_sharpe": round(rolling_sharpe.dropna().std(), 4),
            "min_rolling_sharpe": round(rolling_sharpe.dropna().min(), 4),
            "max_rolling_sharpe": round(rolling_sharpe.dropna().max(), 4),
            "pct_positive": round((rolling_sharpe.dropna() > 0).mean() * 100, 1),
        }
    return results


def regime_analysis(returns_dict, vix_signal):
    """Analyze performance in different VIX regimes."""
    regimes = {
        "Low VIX (<15)": vix_signal < 15,
        "Normal VIX (15-20)": (vix_signal >= 15) & (vix_signal < 20),
        "Elevated VIX (20-25)": (vix_signal >= 20) & (vix_signal < 25),
        "High VIX (25-35)": (vix_signal >= 25) & (vix_signal < 35),
        "Crisis VIX (>35)": vix_signal >= 35,
    }

    results = {}
    for regime_name, mask in regimes.items():
        mask_aligned = mask.reindex(list(returns_dict.values())[0].index, method="ffill").fillna(False)
        n_days = mask_aligned.sum()

        regime_data = {}
        for strat_name, rets in returns_dict.items():
            r = rets[mask_aligned].dropna()
            if len(r) > 10:
                ann_ret = r.mean() * 252
                ann_vol = r.std() * np.sqrt(252)
                sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
                regime_data[strat_name] = {
                    "ann_return": round(ann_ret, 4),
                    "ann_vol": round(ann_vol, 4),
                    "sharpe": round(sharpe, 4),
                    "n_days": int(len(r)),
                }

        results[regime_name] = {
            "n_days": int(n_days),
            "strategies": regime_data,
        }

    return results


def cross_oos_validation(close, returns, vix_signal):
    """5 non-overlapping 2-year OOS periods. Check win rate vs SPY and Equal Weight."""
    periods = [
        ("2007-01", "2008-12"),  # GFC
        ("2011-01", "2012-12"),  # Post-GFC recovery
        ("2015-01", "2016-12"),  # Low vol + China scare
        ("2019-01", "2020-12"),  # COVID
        ("2021-01", "2022-12"),  # Post-COVID + rate hikes
    ]

    # Align vix_signal to returns index
    vix_aligned = vix_signal.reindex(returns.index)

    results = []
    for start, end in periods:
        mask = (returns.index >= start) & (returns.index <= end)
        sub_ret = returns[mask]
        sub_vix = vix_aligned[mask]

        if len(sub_ret) < 100:
            continue

        spy_ret = sub_ret["SPY"]
        ew_ret = strategy_equal_weight(sub_ret, ALL_SECTORS)
        smooth_ret = strategy_vix_smooth(sub_ret, sub_vix)
        binary_ret = strategy_vix_binary(sub_ret, sub_vix)
        tier3_ret = strategy_vix_3tier(sub_ret, sub_vix)

        spy_sharpe = spy_ret.mean() / spy_ret.std() * np.sqrt(252) if spy_ret.std() > 0 else 0
        ew_sharpe = ew_ret.mean() / ew_ret.std() * np.sqrt(252) if ew_ret.std() > 0 else 0
        smooth_sharpe = smooth_ret.mean() / smooth_ret.std() * np.sqrt(252) if smooth_ret.std() > 0 else 0
        binary_sharpe = binary_ret.mean() / binary_ret.std() * np.sqrt(252) if binary_ret.std() > 0 else 0
        tier3_sharpe = tier3_ret.mean() / tier3_ret.std() * np.sqrt(252) if tier3_ret.std() > 0 else 0

        period_result = {
            "period": f"{start} to {end}",
            "n_days": int(len(sub_ret)),
            "spy_sharpe": round(spy_sharpe, 4),
            "ew_sharpe": round(ew_sharpe, 4),
            "smooth_sharpe": round(smooth_sharpe, 4),
            "binary_sharpe": round(binary_sharpe, 4),
            "tier3_sharpe": round(tier3_sharpe, 4),
            "smooth_beats_spy": smooth_sharpe > spy_sharpe,
            "smooth_beats_ew": smooth_sharpe > ew_sharpe,
        }
        results.append(period_result)

    wins_vs_spy = sum(1 for r in results if r["smooth_beats_spy"])
    wins_vs_ew = sum(1 for r in results if r["smooth_beats_ew"])

    return {
        "periods": results,
        "smooth_wins_vs_spy": f"{wins_vs_spy}/{len(results)}",
        "smooth_wins_vs_ew": f"{wins_vs_ew}/{len(results)}",
    }


def main():
    global GROWTH_SECTORS, DEFENSIVE_SECTORS, ALL_SECTORS

    print("=" * 70)
    print("K869: VIX-Based Sector Rotation")
    print("=" * 70)

    # ── 1. Download & prepare data ──────────────────────────────────────
    close = download_data()
    returns = compute_returns(close)
    vix_signal = get_vix_signal(close)

    # Verify VIX column exists
    if "^VIX" not in close.columns:
        # Try alternative name
        for col in close.columns:
            if "VIX" in col.upper():
                close["^VIX"] = close[col]
                returns["^VIX"] = returns[col]
                break

    # Check available sectors
    available_sectors = [s for s in ALL_SECTORS if s in returns.columns]
    missing = [s for s in ALL_SECTORS if s not in returns.columns]
    if missing:
        print(f"WARNING: Missing sectors: {missing}")

    print(f"\nAvailable sectors: {available_sectors}")
    print(f"Growth: {[s for s in GROWTH_SECTORS if s in available_sectors]}")
    print(f"Defensive: {[s for s in DEFENSIVE_SECTORS if s in available_sectors]}")

    # Update sector lists to available only
    growth_avail = [s for s in GROWTH_SECTORS if s in available_sectors]
    def_avail = [s for s in DEFENSIVE_SECTORS if s in available_sectors]
    all_avail = growth_avail + def_avail

    # Override globals for strategies
    GROWTH_SECTORS = growth_avail
    DEFENSIVE_SECTORS = def_avail
    ALL_SECTORS = all_avail

    # ── 2. Compute strategy returns ─────────────────────────────────────
    print("\nComputing strategies...")

    strategies = {}
    returns_dict = {}

    # SPY benchmark
    spy_ret = returns["SPY"]
    returns_dict["SPY"] = spy_ret

    # Equal Weight
    ew_ret = strategy_equal_weight(returns, ALL_SECTORS)
    returns_dict["Equal Weight"] = ew_ret

    # Static allocations
    static_growth_ret = strategy_static_growth(returns)
    returns_dict["Static Growth"] = static_growth_ret

    static_def_ret = strategy_static_defensive(returns)
    returns_dict["Static Defensive"] = static_def_ret

    # VIX rotation strategies
    binary_ret = strategy_vix_binary(returns, vix_signal)
    returns_dict["VIX Binary"] = binary_ret

    smooth_ret = strategy_vix_smooth(returns, vix_signal)
    returns_dict["VIX Smooth"] = smooth_ret

    tier3_ret = strategy_vix_3tier(returns, vix_signal)
    returns_dict["VIX 3-Tier"] = tier3_ret

    # ── 3. Full-period metrics ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("FULL PERIOD METRICS")
    print("=" * 70)

    for name, rets in returns_dict.items():
        m = compute_metrics(rets, name)
        strategies[name] = m
        print(f"  {name:20s} | Sharpe {m['sharpe']:6.3f} | CAGR {m['cagr']:7.4f} | MDD {m['mdd']:7.4f} | Sortino {m['sortino']:6.3f}")

    # ── 4. Sanity check: Sharpe > 2x SPY baseline? ─────────────────────
    spy_sharpe = strategies["SPY"]["sharpe"]
    for name, m in strategies.items():
        if name != "SPY" and m["sharpe"] > 2 * spy_sharpe:
            print(f"\n⚠️ WARNING: {name} Sharpe {m['sharpe']:.3f} > 2x SPY {spy_sharpe:.3f} — possible bug!")

    # ── 5. In-Sample / Out-of-Sample split ──────────────────────────────
    print("\n" + "=" * 70)
    print("IN-SAMPLE (2005-2018) vs OUT-OF-SAMPLE (2019-2026)")
    print("=" * 70)

    is_oos_results = {}
    for period_name, mask in [
        ("IS", returns.index <= IS_END),
        ("OOS", returns.index > IS_END),
    ]:
        print(f"\n--- {period_name} ---")
        is_oos_results[period_name] = {}
        for name, rets in returns_dict.items():
            sub = rets[mask]
            m = compute_metrics(sub, f"{name} ({period_name})")
            is_oos_results[period_name][name] = m
            print(f"  {name:20s} | Sharpe {m['sharpe']:6.3f} | CAGR {m['cagr']:7.4f} | MDD {m['mdd']:7.4f}")

    # ── 6. DM Tests ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("DM TESTS (Harvey threshold |t| > 3.0)")
    print("=" * 70)

    # Align all return series
    common_idx = spy_ret.dropna().index
    for name, rets in returns_dict.items():
        common_idx = common_idx.intersection(rets.dropna().index)

    dm_results = []

    # Test each VIX strategy vs SPY and vs Equal Weight
    for vix_strat in ["VIX Binary", "VIX Smooth", "VIX 3-Tier"]:
        for benchmark in ["SPY", "Equal Weight"]:
            r1 = returns_dict[vix_strat].reindex(common_idx).dropna()
            r2 = returns_dict[benchmark].reindex(common_idx).dropna()
            # Ensure same length
            common = r1.index.intersection(r2.index)
            dm = dm_test_wrapper(r1[common].values, r2[common].values, vix_strat, benchmark)
            dm_results.append(dm)
            passed = "✓ PASS" if dm["harvey_pass"] else "✗ FAIL"
            print(f"  {vix_strat:15s} vs {benchmark:15s} | t={dm['dm_t']:6.3f} | p={dm['dm_p']:.4f} | Harvey: {passed}")

    # Also test static allocations vs SPY
    for static in ["Static Growth", "Static Defensive", "Equal Weight"]:
        r1 = returns_dict[static].reindex(common_idx).dropna()
        r2 = returns_dict["SPY"].reindex(common_idx).dropna()
        common = r1.index.intersection(r2.index)
        dm = dm_test_wrapper(r1[common].values, r2[common].values, static, "SPY")
        dm_results.append(dm)
        passed = "✓ PASS" if dm["harvey_pass"] else "✗ FAIL"
        print(f"  {static:15s} vs {'SPY':15s} | t={dm['dm_t']:6.3f} | p={dm['dm_p']:.4f} | Harvey: {passed}")

    # ── 7. Alpha Decomposition ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("ALPHA DECOMPOSITION (Sector Selection vs VIX Timing)")
    print("=" * 70)

    decomp = alpha_decomposition(strategies, returns)
    for name, d in decomp.items():
        print(f"\n  {name}:")
        print(f"    Total Sharpe:    {d['total_sharpe']:.4f}")
        print(f"    EW Baseline:     {d['ew_sharpe']:.4f}")
        print(f"    Best Static:     {d['best_static']:.4f} ({d['best_static_name']})")
        print(f"    Selection alpha: {d['selection_alpha_sharpe']:+.4f} ({d['pct_from_selection']:.1f}%)")
        print(f"    Timing alpha:    {d['timing_alpha_sharpe']:+.4f} ({d['pct_from_timing']:.1f}%)")

    # ── 8. Cross-OOS Validation ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("CROSS-OOS VALIDATION (5 x 2-year periods)")
    print("=" * 70)

    cross_oos = cross_oos_validation(close, returns, vix_signal)
    for p in cross_oos["periods"]:
        print(f"  {p['period']} ({p['n_days']}d): SPY {p['spy_sharpe']:.3f} | EW {p['ew_sharpe']:.3f} | Smooth {p['smooth_sharpe']:.3f} | Beat SPY: {p['smooth_beats_spy']} | Beat EW: {p['smooth_beats_ew']}")
    print(f"\n  Smooth wins vs SPY: {cross_oos['smooth_wins_vs_spy']}")
    print(f"  Smooth wins vs EW:  {cross_oos['smooth_wins_vs_ew']}")

    # ── 9. Regime Analysis ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("VIX REGIME ANALYSIS")
    print("=" * 70)

    key_strats = {k: v for k, v in returns_dict.items() if k in ["SPY", "Equal Weight", "VIX Smooth", "VIX 3-Tier", "Static Defensive"]}
    regime_results = regime_analysis(key_strats, vix_signal)

    for regime_name, regime_data in regime_results.items():
        print(f"\n  {regime_name} ({regime_data['n_days']} days):")
        for strat_name, stats in regime_data.get("strategies", {}).items():
            print(f"    {strat_name:20s} | Return {stats['ann_return']:+7.4f} | Vol {stats['ann_vol']:.4f} | Sharpe {stats['sharpe']:+6.3f}")

    # ── 10. Rolling Analysis ────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("ROLLING 3-YEAR SHARPE")
    print("=" * 70)

    rolling = rolling_analysis(key_strats)
    for name, stats in rolling.items():
        print(f"  {name:20s} | Mean {stats['mean_rolling_sharpe']:6.3f} | Std {stats['std_rolling_sharpe']:.3f} | Min {stats['min_rolling_sharpe']:+6.3f} | Max {stats['max_rolling_sharpe']:+6.3f} | %Pos {stats['pct_positive']:.1f}%")

    # ── 11. Summary & Conclusions ───────────────────────────────────────
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    # Determine if VIX timing adds alpha
    best_vix_strat = max(
        [(n, strategies[n]["sharpe"]) for n in ["VIX Binary", "VIX Smooth", "VIX 3-Tier"]],
        key=lambda x: x[1],
    )
    best_static_alloc = max(
        [(n, strategies[n]["sharpe"]) for n in ["Static Growth", "Static Defensive"]],
        key=lambda x: x[1],
    )

    timing_alpha = best_vix_strat[1] - best_static_alloc[1]
    selection_alpha = best_static_alloc[1] - strategies["Equal Weight"]["sharpe"]

    conclusions = {
        "q1_beats_equal_weight": best_vix_strat[1] > strategies["Equal Weight"]["sharpe"],
        "q1_detail": f"Best VIX strategy ({best_vix_strat[0]}) Sharpe {best_vix_strat[1]:.4f} vs EW {strategies['Equal Weight']['sharpe']:.4f}",
        "q2_beats_spy": best_vix_strat[1] > strategies["SPY"]["sharpe"],
        "q2_detail": f"Best VIX strategy ({best_vix_strat[0]}) Sharpe {best_vix_strat[1]:.4f} vs SPY {strategies['SPY']['sharpe']:.4f}",
        "q3_timing_alpha": round(timing_alpha, 4),
        "q3_selection_alpha": round(selection_alpha, 4),
        "q3_detail": f"Timing alpha (Sharpe): {timing_alpha:+.4f}, Selection alpha: {selection_alpha:+.4f}",
        "q3_interpretation": "Timing adds alpha" if timing_alpha > 0.05 else "Timing alpha negligible or negative",
        "dm_any_pass_harvey": any(d["harvey_pass"] for d in dm_results[:6]),  # First 6 = VIX strats vs benchmarks
        "cross_oos_smooth_vs_spy": cross_oos["smooth_wins_vs_spy"],
        "cross_oos_smooth_vs_ew": cross_oos["smooth_wins_vs_ew"],
    }

    for k, v in conclusions.items():
        print(f"  {k}: {v}")

    # ── 12. Save results ────────────────────────────────────────────────
    results = {
        "experiment_id": "K869",
        "title": "VIX-Based Sector Rotation — Can VIX Timing Add Alpha to Sector Allocation?",
        "date": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "period": f"{returns.index[0].date()} to {returns.index[-1].date()}",
        "n_days": len(returns),
        "sectors": {
            "growth": GROWTH_SECTORS,
            "defensive": DEFENSIVE_SECTORS,
        },
        "lag": "signal.shift(1) applied to VIX (mandatory)",
        "rebalance": "Monthly",
        "full_period_metrics": strategies,
        "is_oos_metrics": is_oos_results,
        "dm_tests": dm_results,
        "alpha_decomposition": decomp,
        "cross_oos_validation": cross_oos,
        "regime_analysis": regime_results,
        "rolling_analysis": rolling,
        "conclusions": conclusions,
        "references": [
            "K58: Sector VT Map — gamma doesn't predict sector VT effect",
            "K560: Sector Rotation with VT — Momentum selection improves VT",
            "K562: Sector Momentum Validation — Daily PASS but Monthly FAIL",
            "K415: CSVD null result — VIX sufficient #29",
            "Harvey (2016): t>3.0 threshold for multiple testing",
        ],
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to {RESULTS_FILE}")
    print("=" * 70)

    return results


if __name__ == "__main__":
    results = main()
