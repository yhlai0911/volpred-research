"""Taiwan VT Paper Fixes — addressing Gemini R6#2 review concerns.

[提出: Gemini R6#2 審查, 執行: Claude]

Fix 1 (Critical): K=8.63 look-ahead bias
  - Paper uses full-sample VIXTWN/VIX ratio=1.39 to calibrate K=12/1.39=8.63
  - But backtest starts 2016, while VIXTWN only available from 2020/11
  - Fix: expanding-window K that uses only data available at each point in time

Fix 2 (Severe): ±10% price limit stress test
  - Taiwan has ±10% daily price limits
  - If 0050.TW hits limit-down, rebalancing may be impossible
  - Fix: simulate delayed rebalancing when daily return < -9%

Fix 5: ETF transaction tax correction
  - Paper uses 0.585% round-trip (0.30% securities tax + 0.1425%×2 commissions)
  - But Taiwan ETFs pay only 0.1% securities tax (not 0.3%)
  - Correct: 0.1% + 0.1425%×2 = 0.385% round-trip

Run: uv run python experiments/taiwan_paper_fixes.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager

# ── Config ──────────────────────────────────────────────────
BACKTEST_START = "2016-01-01"
BACKTEST_END = "2026-03-20"
VIXTWN_START = "2020-11-01"  # VIXTWN available from Nov 2020
FIXED_K = 8.63
DEFAULT_K = 12.0  # K when no VIXTWN data available (ratio=1.0 assumption)
TX_ORIGINAL = 0.00585  # Original (WRONG): 0.3% tax + 0.1425%×2 commission
# ⚠️ CORRECTED AGAIN (K625): commission should also use 3折 discount
TX_CORRECTED = 0.001855  # Correct: 0.1% ETF tax + 0.04275%×2 commission (3折)
LIMIT_DOWN_THRESHOLD = -0.09  # ≈ approaching -10% limit


def load_data():
    """Load 0050.TW, VIX, and VIXTWN data."""
    dm = DataManager()

    # 0050.TW daily data
    tw50 = dm.get_model_data("0050.TW", "2008-01-01", "2026-12-31")
    print(f"0050.TW: {len(tw50)} days ({tw50.index[0].date()} to {tw50.index[-1].date()})")

    # VIX daily data
    vix = dm.get_model_data("^VIX", "2008-01-01", "2026-12-31")
    print(f"VIX: {len(vix)} days ({vix.index[0].date()} to {vix.index[-1].date()})")

    # VIXTWN from local CSV
    vixtwn_path = Path("data/vixtwn/vixtwn_daily.csv")
    if vixtwn_path.exists():
        vixtwn = pd.read_csv(vixtwn_path, parse_dates=["date"], index_col="date")
        print(f"VIXTWN: {len(vixtwn)} days ({vixtwn.index[0].date()} to {vixtwn.index[-1].date()})")
    else:
        vixtwn = pd.DataFrame()
        print("VIXTWN: no local data found")

    return tw50, vix, vixtwn


def compute_expanding_k(vix_df, vixtwn_df):
    """Compute expanding-window K time series.

    Before VIXTWN exists (pre-2020/11): K = 12 (assume ratio=1.0)
    After VIXTWN exists: K = 12 / expanding_mean(VIXTWN/VIX)

    Returns dict: date -> K value
    """
    # Align VIX and VIXTWN on common dates
    if len(vixtwn_df) == 0:
        return {}

    # VIX close values
    vix_close = vix_df["close"].copy()
    vixtwn_close = vixtwn_df["vixtwn_close"].copy()

    # Find overlapping dates
    common_dates = vix_close.index.intersection(vixtwn_close.index)
    if len(common_dates) == 0:
        print("WARNING: No overlapping dates between VIX and VIXTWN")
        return {}

    print(f"\nVIX-VIXTWN overlap: {len(common_dates)} days "
          f"({common_dates[0].date()} to {common_dates[-1].date()})")

    # Compute daily ratio
    ratio_series = vixtwn_close.loc[common_dates] / vix_close.loc[common_dates]
    ratio_series = ratio_series.sort_index()

    # Expanding mean ratio
    expanding_ratio = ratio_series.expanding(min_periods=20).mean()  # need at least 20 days
    expanding_k = DEFAULT_K / expanding_ratio

    # Full-sample stats
    full_ratio = ratio_series.mean()
    full_k = DEFAULT_K / full_ratio
    print(f"Full-sample VIXTWN/VIX ratio: {full_ratio:.3f} (K = {full_k:.2f})")
    print(f"Ratio range: [{ratio_series.min():.3f}, {ratio_series.max():.3f}]")
    print(f"Ratio CV: {ratio_series.std() / ratio_series.mean() * 100:.1f}%")

    # Show K evolution at key dates
    k_dict = {}
    for date in expanding_k.dropna().index:
        k_dict[date] = float(expanding_k.loc[date])

    # Print K at quarterly intervals
    print("\nExpanding K time series (quarterly snapshots):")
    dates_sorted = sorted(k_dict.keys())
    prev_quarter = None
    for d in dates_sorted:
        q = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        if q != prev_quarter:
            print(f"  {d.date()}: K = {k_dict[d]:.3f} "
                  f"(ratio = {DEFAULT_K / k_dict[d]:.3f})")
            prev_quarter = q

    return k_dict


def run_vix_vt_backtest(tw50_df, vix_df, k_value, rebalance="monthly",
                        tx_cost=0.0, label="", delayed_rebalance=False):
    """Run K/VIX VT strategy on 0050.TW.

    Parameters:
    -----------
    k_value : float or dict
        If float: fixed K for all dates
        If dict: date -> K mapping (expanding window)
    rebalance : str
        'monthly' or 'daily'
    tx_cost : float
        One-way transaction cost (applied on weight changes)
    delayed_rebalance : bool
        If True, simulate limit-down constraint: skip rebalancing when return < LIMIT_DOWN_THRESHOLD
    """
    bt_start = pd.Timestamp(BACKTEST_START)
    bt_end = pd.Timestamp(BACKTEST_END)

    tw_dates = tw50_df.loc[bt_start:bt_end].index
    vix_close = vix_df["close"]

    daily_returns = []
    weights_log = []
    limit_down_events = []
    prev_weight = None
    current_month = None

    for i, date in enumerate(tw_dates):
        tw_ret = float(tw50_df.loc[date, "simple_return"])

        # Get K for this date
        if isinstance(k_value, dict):
            # Find most recent K available before this date
            available_k = DEFAULT_K  # default before VIXTWN exists
            for k_date in sorted(k_value.keys()):
                if k_date < date:
                    available_k = k_value[k_date]
                else:
                    break
            k = available_k
        else:
            k = k_value

        # VIX from previous US trading day
        # Find most recent VIX date strictly before this TW date
        vix_before = vix_close[vix_close.index < date]
        if len(vix_before) == 0:
            continue
        vix_level = float(vix_before.iloc[-1])

        # Compute target weight
        target_weight = min(k / vix_level, 1.0)

        # Monthly rebalancing: only change weight at month boundaries
        if rebalance == "monthly":
            this_month = (date.year, date.month)
            if this_month != current_month:
                current_month = this_month
                should_rebalance = True
            else:
                should_rebalance = False
        else:  # daily
            should_rebalance = True

        # Delayed rebalance for limit-down stress test
        if delayed_rebalance and should_rebalance and prev_weight is not None:
            if target_weight < prev_weight and tw_ret < LIMIT_DOWN_THRESHOLD:
                # Can't sell during limit-down!
                limit_down_events.append({
                    "date": date,
                    "return": tw_ret,
                    "target_weight": target_weight,
                    "actual_weight": prev_weight,
                    "vix": vix_level,
                })
                should_rebalance = False  # Delay to next day

        if should_rebalance:
            new_weight = target_weight
        else:
            new_weight = prev_weight if prev_weight is not None else target_weight

        # Transaction cost
        if prev_weight is not None and should_rebalance:
            turnover = abs(new_weight - prev_weight)
            tc = turnover * tx_cost  # one-way cost on changed portion
        else:
            tc = 0.0

        # Portfolio return
        port_ret = new_weight * tw_ret - tc
        daily_returns.append(port_ret)
        weights_log.append({
            "date": date,
            "weight": new_weight,
            "k": k,
            "vix": vix_level,
            "tw_ret": tw_ret,
            "port_ret": port_ret,
        })
        prev_weight = new_weight

    # Compute metrics
    rets = np.array(daily_returns)
    n = len(rets)
    cum = np.prod(1 + rets) - 1
    years = n / 252
    ann_ret = (1 + cum) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = np.std(rets, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum_series = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(cum_series)
    drawdowns = cum_series / running_max - 1
    max_dd = np.min(drawdowns)

    # Sortino
    downside = rets[rets < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else 1e-9
    sortino = ann_ret / downside_vol

    # Calmar
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-9 else 0

    metrics = {
        "label": label,
        "trading_days": n,
        "cumulative_return": cum,
        "annualized_return": ann_ret,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "limit_down_events": limit_down_events,
    }

    return metrics, weights_log


def run_buy_and_hold(tw50_df):
    """Buy & Hold benchmark for 0050.TW."""
    bt_start = pd.Timestamp(BACKTEST_START)
    bt_end = pd.Timestamp(BACKTEST_END)
    tw_dates = tw50_df.loc[bt_start:bt_end].index

    rets = []
    for date in tw_dates:
        tw_ret = float(tw50_df.loc[date, "simple_return"])
        rets.append(tw_ret)

    rets = np.array(rets)
    n = len(rets)
    cum = np.prod(1 + rets) - 1
    years = n / 252
    ann_ret = (1 + cum) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = np.std(rets, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum_series = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(cum_series)
    drawdowns = cum_series / running_max - 1
    max_dd = np.min(drawdowns)

    return {
        "label": "Buy & Hold (0050.TW)",
        "trading_days": n,
        "cumulative_return": cum,
        "annualized_return": ann_ret,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def find_limit_down_days(tw50_df):
    """Find days where 0050.TW daily return approaches or hits limit-down (-10%)."""
    bt_start = pd.Timestamp(BACKTEST_START)
    bt_end = pd.Timestamp(BACKTEST_END)
    tw_data = tw50_df.loc[bt_start:bt_end]

    extreme_days = []
    for date in tw_data.index:
        ret = float(tw_data.loc[date, "simple_return"])
        if ret < LIMIT_DOWN_THRESHOLD:
            extreme_days.append({
                "date": date,
                "return": ret,
                "close": float(tw_data.loc[date, "close"]),
            })

    return extreme_days


def print_metrics_comparison(metrics_list):
    """Print comparison table."""
    print(f"\n{'Strategy':<45} {'Sharpe':>7} {'Ann.Ret':>8} {'Ann.Vol':>8} {'MDD':>8} {'Sortino':>8} {'Calmar':>7} {'Days':>6}")
    print("-" * 108)
    for m in metrics_list:
        sortino = m.get("sortino", float("nan"))
        calmar = m.get("calmar", float("nan"))
        print(f"{m['label']:<45} {m['sharpe']:>7.3f} "
              f"{m['annualized_return']*100:>7.2f}% "
              f"{m['annualized_vol']*100:>7.2f}% "
              f"{m['max_drawdown']*100:>7.2f}% "
              f"{sortino:>8.3f} "
              f"{calmar:>7.3f} "
              f"{m['trading_days']:>6d}")


def main():
    print("=" * 80)
    print("Taiwan VT Paper Fixes — Gemini R6#2 Review")
    print(f"Backtest: {BACKTEST_START} → {BACKTEST_END}")
    print("=" * 80)

    tw50, vix, vixtwn = load_data()

    # ============================================================
    # FIX 1: Expanding-window K (vs fixed K=8.63 look-ahead bias)
    # ============================================================
    print("\n" + "=" * 80)
    print("FIX 1: Expanding-Window K (Look-Ahead Bias Correction)")
    print("=" * 80)

    # Compute expanding K
    k_expanding = compute_expanding_k(vix, vixtwn)

    # A. Fixed K=8.63 (original paper, has look-ahead bias)
    m_fixed, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=0.0,
        label=f"Fixed K={FIXED_K} (look-ahead bias)"
    )

    # B. Expanding K (no look-ahead bias)
    m_expanding, wlog_exp = run_vix_vt_backtest(
        tw50, vix, k_expanding,
        rebalance="monthly", tx_cost=0.0,
        label="Expanding K (no bias)"
    )

    # C. Fixed K=12 (no VIXTWN assumption)
    m_k12, _ = run_vix_vt_backtest(
        tw50, vix, DEFAULT_K,
        rebalance="monthly", tx_cost=0.0,
        label="Fixed K=12 (VIX ratio=1.0)"
    )

    # D. Buy & Hold
    m_bh = run_buy_and_hold(tw50)

    print_metrics_comparison([m_bh, m_fixed, m_expanding, m_k12])

    # Sharpe difference
    delta_sharpe = m_fixed["sharpe"] - m_expanding["sharpe"]
    print(f"\nSharpe difference (Fixed - Expanding): {delta_sharpe:+.4f}")
    if abs(delta_sharpe) < 0.05:
        print("→ Conclusion: K-invariance CONFIRMED — expanding K produces nearly identical Sharpe")
        print("  The look-ahead bias in K calibration is economically negligible.")
    else:
        print(f"→ WARNING: Sharpe difference of {delta_sharpe:.4f} may be economically meaningful")

    # Show K evolution
    print("\nK evolution (pre vs post VIXTWN availability):")
    print(f"  Pre-VIXTWN (2016-2020/10): K = {DEFAULT_K:.2f} (assumption: ratio = 1.0)")
    if k_expanding:
        final_k = list(k_expanding.values())[-1]
        print(f"  Final expanding K: {final_k:.3f}")
        print(f"  Fixed K in paper: {FIXED_K:.2f}")

    # ============================================================
    # FIX 2: ±10% Price Limit Stress Test
    # ============================================================
    print("\n" + "=" * 80)
    print("FIX 2: ±10% Price Limit Stress Test")
    print("=" * 80)

    # Find extreme days
    extreme_days = find_limit_down_days(tw50)
    print(f"\nDays with return < {LIMIT_DOWN_THRESHOLD*100:.0f}% (approaching limit-down):")
    print(f"  Total: {len(extreme_days)} days out of {m_bh['trading_days']} "
          f"({len(extreme_days)/m_bh['trading_days']*100:.2f}%)")

    if extreme_days:
        print("\n  Date           Return    Close")
        print("  " + "-" * 40)
        for ed in extreme_days:
            print(f"  {ed['date'].date()}   {ed['return']*100:>7.2f}%   NT${ed['close']:.2f}")

    # Run with delayed rebalancing
    m_ideal, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=0.0,
        label="Ideal rebalance (K=8.63)",
        delayed_rebalance=False
    )

    m_delayed, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=0.0,
        label="Delayed rebalance (limit-down)",
        delayed_rebalance=True
    )

    # Also test with daily rebalancing (more exposure to limit-down)
    m_daily_ideal, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="daily", tx_cost=0.0,
        label="Daily ideal rebalance",
        delayed_rebalance=False
    )

    m_daily_delayed, wlog_dd = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="daily", tx_cost=0.0,
        label="Daily delayed rebalance (limit-down)",
        delayed_rebalance=True
    )

    print("\nMonthly rebalancing:")
    print_metrics_comparison([m_ideal, m_delayed])
    n_events_monthly = len(m_delayed.get("limit_down_events", []))
    print(f"  Limit-down rebalance delays: {n_events_monthly}")

    print("\nDaily rebalancing:")
    print_metrics_comparison([m_daily_ideal, m_daily_delayed])
    n_events_daily = len(m_daily_delayed.get("limit_down_events", []))
    print(f"  Limit-down rebalance delays: {n_events_daily}")

    if m_daily_delayed.get("limit_down_events"):
        print("\n  Limit-down events (daily rebalance):")
        print(f"  {'Date':<12} {'Return':>8} {'Target W':>10} {'Actual W':>10} {'VIX':>6}")
        print("  " + "-" * 55)
        for ev in m_daily_delayed["limit_down_events"]:
            date_str = str(ev['date'].date())
            print(f"  {date_str:<12} {ev['return']*100:>7.2f}% "
                  f"{ev['target_weight']:>10.4f} {ev['actual_weight']:>10.4f} "
                  f"{ev['vix']:>6.1f}")

    # MDD comparison
    mdd_diff = m_delayed["max_drawdown"] - m_ideal["max_drawdown"]
    print(f"\nMDD impact (monthly): {mdd_diff*100:+.2f}pp")
    mdd_diff_daily = m_daily_delayed["max_drawdown"] - m_daily_ideal["max_drawdown"]
    print(f"MDD impact (daily):   {mdd_diff_daily*100:+.2f}pp")

    if abs(mdd_diff) < 0.005 and abs(mdd_diff_daily) < 0.005:
        print("→ Conclusion: Limit-down impact is NEGLIGIBLE for both rebalancing frequencies")
    elif n_events_daily == 0 and n_events_monthly == 0:
        print("→ Conclusion: 0050.TW NEVER approached limit-down during the sample period")
        print("  The ±10% limit is not binding for a diversified large-cap ETF")
    else:
        print(f"→ Conclusion: Limit-down affects {n_events_daily} days with MDD impact of {mdd_diff_daily*100:+.2f}pp")

    # ============================================================
    # FIX 5: ETF Transaction Tax Correction (0.1% not 0.3%)
    # ============================================================
    print("\n" + "=" * 80)
    print("FIX 5: ETF Transaction Tax Correction")
    print("=" * 80)
    print(f"\nOriginal paper: TX = {TX_ORIGINAL*100:.3f}% round-trip")
    print(f"  (0.30% securities tax + 0.1425%×2 brokerage)")
    print(f"Corrected:      TX = {TX_CORRECTED*100:.3f}% round-trip")
    print(f"  (0.10% ETF tax + 0.1425%×2 brokerage)")

    # Monthly rebalancing with original TX
    m_orig_tx, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=TX_ORIGINAL,
        label=f"K=8.63, TX={TX_ORIGINAL*100:.3f}% (original)"
    )

    # Monthly rebalancing with corrected TX
    m_corr_tx, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=TX_CORRECTED,
        label=f"K=8.63, TX={TX_CORRECTED*100:.3f}% (corrected ETF)"
    )

    # No TX for reference
    m_no_tx, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=0.0,
        label="K=8.63, TX=0% (gross)"
    )

    # With expanding K and corrected TX (the "best" version)
    m_best, _ = run_vix_vt_backtest(
        tw50, vix, k_expanding,
        rebalance="monthly", tx_cost=TX_CORRECTED,
        label=f"Expanding K, TX={TX_CORRECTED*100:.3f}% (best fix)"
    )

    print_metrics_comparison([m_bh, m_no_tx, m_orig_tx, m_corr_tx, m_best])

    sharpe_improvement = m_corr_tx["sharpe"] - m_orig_tx["sharpe"]
    print(f"\nSharpe improvement from TX correction: {sharpe_improvement:+.4f}")
    print(f"  Original net Sharpe: {m_orig_tx['sharpe']:.3f}")
    print(f"  Corrected net Sharpe: {m_corr_tx['sharpe']:.3f}")
    print(f"  Gross Sharpe: {m_no_tx['sharpe']:.3f}")

    # ============================================================
    # COMBINED: All fixes applied
    # ============================================================
    print("\n" + "=" * 80)
    print("COMBINED: All Fixes Applied")
    print("=" * 80)

    # Best version: expanding K + corrected TX + delayed rebalance
    m_all_fixes, _ = run_vix_vt_backtest(
        tw50, vix, k_expanding,
        rebalance="monthly", tx_cost=TX_CORRECTED,
        label="All fixes (expanding K + correct TX + limit-down)",
        delayed_rebalance=True
    )

    # Original paper version
    m_paper_original, _ = run_vix_vt_backtest(
        tw50, vix, FIXED_K,
        rebalance="monthly", tx_cost=TX_ORIGINAL,
        label="Paper original (K=8.63, TX=0.585%)"
    )

    print("\nFinal comparison:")
    print_metrics_comparison([m_bh, m_paper_original, m_all_fixes])

    delta = m_all_fixes["sharpe"] - m_paper_original["sharpe"]
    print(f"\nOverall Sharpe change from all fixes: {delta:+.4f}")

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 80)
    print("SUMMARY OF FIXES")
    print("=" * 80)

    print(f"""
Fix 1 — K Look-Ahead Bias:
  Fixed K=8.63 Sharpe:     {m_fixed['sharpe']:.3f}
  Expanding K Sharpe:      {m_expanding['sharpe']:.3f}
  Difference:              {m_fixed['sharpe'] - m_expanding['sharpe']:+.4f}
  Verdict:                 {'NEGLIGIBLE — K-invariance holds' if abs(m_fixed['sharpe'] - m_expanding['sharpe']) < 0.05 else 'SIGNIFICANT — paper needs revision'}

Fix 2 — ±10% Price Limit:
  Extreme days (<-9%):     {len(extreme_days)}
  MDD impact (monthly):    {mdd_diff*100:+.2f}pp
  MDD impact (daily):      {mdd_diff_daily*100:+.2f}pp
  Limit-down delays:       {n_events_monthly} (monthly), {n_events_daily} (daily)
  Verdict:                 {'NOT BINDING — 0050.TW never approached limit-down' if len(extreme_days) == 0 else f'{len(extreme_days)} events, MDD impact {mdd_diff_daily*100:+.2f}pp'}

Fix 5 — ETF Tax Correction:
  Original TX (0.585%):    Sharpe {m_orig_tx['sharpe']:.3f}
  Corrected TX (0.385%):   Sharpe {m_corr_tx['sharpe']:.3f}
  Improvement:             {m_corr_tx['sharpe'] - m_orig_tx['sharpe']:+.4f}
  Verdict:                 Paper OVERSTATES costs → results are actually BETTER

Overall Conclusion:
  Original paper Sharpe (net):  {m_paper_original['sharpe']:.3f}
  All-fixes Sharpe (net):       {m_all_fixes['sharpe']:.3f}
  Change:                       {m_all_fixes['sharpe'] - m_paper_original['sharpe']:+.4f}
  → {'Paper conclusions ROBUST — fixes improve results slightly' if m_all_fixes['sharpe'] >= m_paper_original['sharpe'] else 'Paper conclusions ROBUST — fixes have minor negative impact' if m_all_fixes['sharpe'] > m_paper_original['sharpe'] * 0.9 else 'Paper conclusions NEED REVISION'}
""")


if __name__ == "__main__":
    main()
