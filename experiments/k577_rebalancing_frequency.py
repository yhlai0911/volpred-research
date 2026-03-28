#!/usr/bin/env python3
"""
K577: Optimal Rebalancing Frequency for VIX-Conditional Leverage
================================================================
Motivation:
    K548/K551 validated VIX-Conditional Leverage with DAILY rebalancing
    (Sharpe 1.474, Harvey t=7.90, 11/11 OOS). But daily trading is impractical
    for most retail investors. K562 showed sector momentum dies at monthly
    frequency. Does VIX-Conditional Leverage ALSO require daily frequency,
    or can it work weekly/monthly?

    This is critical for strategy listing — if monthly works, many more investors
    can use it.

Design:
    1. Data: SPY + GLD + VIX + ^IRX from yfinance (2005-2026)
    2. Strategy: 50/50 SPY/GLD + 12/VIX + VIX-Conditional Leverage
       (VIX<15 -> 1.5x, VIX>25 -> 1.0x, linear interpolation)
    3. Rebalancing frequencies:
       a. Daily (K548 baseline)
       b. Weekly (every Friday)
       c. Bi-weekly (every other Friday)
       d. Monthly (1st trading day)
       e. Quarterly (1st trading day of quarter)
    4. For each frequency, compute BOTH leveraged and unleveraged at SAME freq
       - Sharpe, MDD, CAGR, turnover, TX cost drag
       - DM test vs daily baseline
       - Cross-OOS: 5 periods (leveraged vs unleveraged at same freq)
    5. Also test: does the VIX THRESHOLD check frequency matter separately
       from rebalancing? (hybrid: check VIX daily but only rebalance weekly)
    6. Harvey t>3.0 for monthly leveraged vs monthly unleveraged (FAIR comparison)

Related experiments:
    K548: VIX-Conditional Leverage -- Sharpe +0.112, CAGR +5.4%, 5/5 Cross-OOS
    K551: K548 Deep Validation -- Harvey t=7.90, 11/11 OOS, 100% bootstrap
    K499: Rebalancing frequency for base VT (monthly best for cost efficiency)
    K562: Sector Momentum -- daily PASS but monthly FAIL

References:
    Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
    Fleming, Kirby, Ostdiek (2003) "Economic Value of Volatility Timing" JFE
    Harvey & Liu (2016) "... and the Cross-Section of Expected Returns" RFS

Author: VolPred Research System (Claude)
Data: yfinance (SPY, GLD, ^VIX, ^IRX), 2005-2026
"""

import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────── Config ───────────────────────────
START = "2004-12-01"
END = "2026-03-27"
BORROWING_SPREAD = 0.005  # 50bps above risk-free
FALLBACK_RF = 0.04

# VIX-Conditional Leverage parameters (from K548)
VIX_LOW = 15.0   # below this -> max leverage (1.5x)
VIX_HIGH = 25.0  # above this -> no leverage (1.0x)
LEV_MAX = 1.5
LEV_MIN = 1.0

# Transaction cost scenarios (round-trip)
TX_COSTS = {
    "zero": 0.0,
    "low_5bps": 0.0005,
    "medium_10bps": 0.001,
    "high_20bps": 0.002,
}

# Cross-OOS periods (5 non-overlapping)
OOS_PERIODS = [
    ("2005-06-01", "2009-05-31"),  # includes GFC
    ("2009-06-01", "2013-05-31"),  # recovery
    ("2013-06-01", "2017-05-31"),  # low vol
    ("2017-06-01", "2021-05-31"),  # includes COVID
    ("2021-06-01", "2026-03-27"),  # recent
]

t0 = time.time()

print("=" * 80)
print("K577: Optimal Rebalancing Frequency for VIX-Conditional Leverage")
print("=" * 80)


# ─────────────────────── Data Download ────────────────────────
def download_data():
    """Download SPY, GLD, VIX, and risk-free rate."""
    print("\n[1/8] Downloading data...")
    spy = yf.download("SPY", start=START, end=END, progress=False)
    gld = yf.download("GLD", start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    try:
        irx = yf.download("^IRX", start=START, end=END, progress=False)
        rf_available = len(irx) > 100
    except Exception:
        irx = None
        rf_available = False

    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    if irx is not None and isinstance(irx.columns, pd.MultiIndex):
        irx.columns = irx.columns.get_level_values(0)

    data = pd.DataFrame(index=spy.index)
    data["spy_close"] = spy["Close"]
    data["gld_close"] = gld["Close"]
    data["vix"] = vix["Close"]

    if rf_available and irx is not None and len(irx) > 0:
        data["rf_annual"] = irx["Close"].reindex(data.index).ffill() / 100
        data["rf_daily"] = data["rf_annual"] / 252
        print(f"  Risk-free rate from ^IRX: mean={data['rf_annual'].mean()*100:.2f}%")
    else:
        data["rf_annual"] = FALLBACK_RF
        data["rf_daily"] = FALLBACK_RF / 252
        print(f"  Using fallback risk-free rate: {FALLBACK_RF*100:.1f}%")

    data = data.ffill().dropna()
    data["spy_ret"] = data["spy_close"].pct_change()
    data["gld_ret"] = data["gld_close"].pct_change()
    data = data.dropna()

    print(f"  Data period: {data.index[0].date()} to {data.index[-1].date()}, N={len(data)}")
    return data


# ─────────────────────── Strategy Logic ───────────────────────
def compute_vix_weight(vix_val):
    """12/VIX capped at 1.0."""
    return min(12.0 / vix_val, 1.0)


def compute_leverage(vix_val):
    """VIX-Conditional Leverage: 1.5x when VIX<15, 1.0x when VIX>25, linear interp."""
    return float(np.clip(LEV_MAX - (LEV_MAX - LEV_MIN) * (vix_val - VIX_LOW) / (VIX_HIGH - VIX_LOW),
                   LEV_MIN, LEV_MAX))


def get_rebalance_dates(data_index, frequency):
    """Return set of indices where rebalancing happens for the given frequency."""
    dates = data_index
    if frequency == "daily":
        return set(range(len(dates)))
    elif frequency == "weekly":
        rebal = set()
        for i in range(len(dates)):
            if dates[i].weekday() == 4:  # Friday
                rebal.add(i)
            elif i == len(dates) - 1:
                rebal.add(i)
            elif i < len(dates) - 1 and dates[i].weekday() < 4 and dates[i + 1].weekday() < dates[i].weekday():
                rebal.add(i)
        rebal.add(0)  # always rebalance on first day
        return rebal
    elif frequency == "biweekly":
        weekly = sorted(get_rebalance_dates(data_index, "weekly"))
        return set(weekly[::2])
    elif frequency == "monthly":
        rebal = {0}
        for i in range(1, len(dates)):
            if dates[i].month != dates[i - 1].month:
                rebal.add(i)
        return rebal
    elif frequency == "quarterly":
        rebal = {0}
        for i in range(1, len(dates)):
            curr_q = (dates[i].month - 1) // 3
            prev_q = (dates[i - 1].month - 1) // 3
            if curr_q != prev_q or dates[i].year != dates[i - 1].year:
                rebal.add(i)
        return rebal
    else:
        raise ValueError(f"Unknown frequency: {frequency}")


def simulate_strategy(data, frequency, leveraged=True, check_vix_daily=False, tx_cost=0.0):
    """
    Simulate strategy with given rebalancing frequency.

    Parameters:
    -----------
    data : DataFrame with spy_ret, gld_ret, vix, rf_daily
    frequency : str - "daily", "weekly", "biweekly", "monthly", "quarterly"
    leveraged : bool - if True, apply VIX-conditional leverage; if False, base VT only
    check_vix_daily : bool - if True, update leverage from VIX daily even when
                      not rebalancing (hybrid approach)
    tx_cost : float - round-trip transaction cost as fraction

    Returns:
    --------
    (Series of daily portfolio returns, annual_turnover)
    """
    n = len(data)
    dates = data.index
    spy_ret = data["spy_ret"].values
    gld_ret = data["gld_ret"].values
    vix_vals = data["vix"].values
    rf_daily = data["rf_daily"].values

    rebal_dates = get_rebalance_dates(dates, frequency)

    # Initialize
    port_returns = np.zeros(n)
    current_w = compute_vix_weight(vix_vals[0])
    current_lev = compute_leverage(vix_vals[0]) if leveraged else 1.0
    turnover_total = 0.0

    for i in range(n):
        is_rebal_day = i in rebal_dates

        if is_rebal_day:
            new_w = compute_vix_weight(vix_vals[i])
            new_lev = compute_leverage(vix_vals[i]) if leveraged else 1.0
        elif check_vix_daily and leveraged:
            # Check VIX daily for leverage but keep weight from last rebalance
            new_w = current_w
            new_lev = compute_leverage(vix_vals[i])
        else:
            new_w = current_w
            new_lev = current_lev

        # Compute turnover (change in effective exposure)
        old_exposure = current_w * current_lev
        new_exposure = new_w * new_lev
        turn = abs(new_exposure - old_exposure)
        turnover_total += turn

        # Apply transaction cost on turnover
        tx = turn * tx_cost

        # Update
        current_w = new_w
        current_lev = new_lev

        # Portfolio return
        effective_lev = current_w * current_lev
        risky_ret = 0.5 * spy_ret[i] + 0.5 * gld_ret[i]
        gross_ret = effective_lev * risky_ret + (1 - effective_lev) * rf_daily[i]

        # Borrowing cost (when leverage > 1, only for leveraged strategy)
        if leveraged:
            borrow_cost = max(effective_lev - 1, 0) * (rf_daily[i] + BORROWING_SPREAD / 252)
        else:
            borrow_cost = 0.0

        port_returns[i] = gross_ret - borrow_cost - tx

    annual_turnover = turnover_total / (n / 252)
    return pd.Series(port_returns, index=dates), annual_turnover


# ─────────────────────── Metrics ──────────────────────────────
def compute_metrics(returns_series, rf_series=None):
    """Compute standard performance metrics."""
    r = returns_series.dropna()
    if len(r) < 100:
        return None

    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    years = len(r) / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0.5 else 0
    ann_vol = r.std() * np.sqrt(252)

    if rf_series is not None:
        rf_aligned = rf_series.reindex(r.index).fillna(FALLBACK_RF / 252)
        excess = r - rf_aligned
    else:
        excess = r - FALLBACK_RF / 252
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    mdd = drawdown.min()

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    downside = excess[excess < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = excess.mean() * 252 / downside_std

    return {
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "total_return_pct": round(total_return * 100, 2),
        "years": round(years, 1),
        "n_days": len(r),
    }


def sharpe_diff_test(returns1, returns2, rf_daily):
    """
    Test Sharpe ratio difference: Jobson-Korkie (1981) + Memmel (2003) correction.
    Positive t means returns1 has higher Sharpe.
    Returns (t_stat, p_value).
    """
    idx = returns1.index.intersection(returns2.index)
    r1 = returns1.loc[idx].dropna()
    r2 = returns2.loc[idx].dropna()
    idx2 = r1.index.intersection(r2.index)
    r1 = r1.loc[idx2]
    r2 = r2.loc[idx2]
    rf = rf_daily.reindex(idx2).fillna(FALLBACK_RF / 252)

    e1 = r1 - rf
    e2 = r2 - rf
    n = len(e1)
    if n < 100:
        return np.nan, np.nan

    mu1, mu2 = e1.mean(), e2.mean()
    s1, s2 = e1.std(), e2.std()
    if s1 == 0 or s2 == 0:
        return np.nan, np.nan
    sr1, sr2 = mu1 / s1, mu2 / s2
    rho = e1.corr(e2)

    theta = (1 / n) * (
        2 * (1 - rho)
        + 0.5 * (sr1**2 + sr2**2 - 2 * sr1 * sr2 * rho**2)
    )
    if theta <= 0:
        return np.nan, np.nan

    # Annualize: multiply by sqrt(252) because we want annualized Sharpe diff t-stat
    z = (sr1 - sr2) / np.sqrt(theta)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return round(z, 3), round(p, 6)


def bootstrap_sharpe_test(returns1, returns2, rf_daily, n_boot=5000, seed=42):
    """
    Bootstrap test for Sharpe ratio difference (returns1 - returns2).
    Returns (mean_diff, ci_lo, ci_hi, p_win).
    """
    idx = returns1.index.intersection(returns2.index)
    r1 = returns1.loc[idx].values
    r2 = returns2.loc[idx].values
    rf = rf_daily.reindex(idx).fillna(FALLBACK_RF / 252).values
    n = len(r1)

    rng = np.random.default_rng(seed)
    diffs = np.zeros(n_boot)

    for b in range(n_boot):
        ix = rng.choice(n, size=n, replace=True)
        e1 = r1[ix] - rf[ix]
        e2 = r2[ix] - rf[ix]
        sr1 = e1.mean() / e1.std() * np.sqrt(252) if e1.std() > 0 else 0
        sr2 = e2.mean() / e2.std() * np.sqrt(252) if e2.std() > 0 else 0
        diffs[b] = sr1 - sr2

    mean_diff = np.mean(diffs)
    ci_lo = np.percentile(diffs, 2.5)
    ci_hi = np.percentile(diffs, 97.5)
    p_win = np.mean(diffs > 0) * 100

    return round(mean_diff, 4), round(ci_lo, 4), round(ci_hi, 4), round(p_win, 1)


# ─────────────────────── Main Analysis ────────────────────────
data = download_data()

# ════════════════════════════════════════════════════════════════
# Part 1: Full-sample — both leveraged AND unleveraged at each frequency
# ════════════════════════════════════════════════════════════════
print("\n[2/8] Full-sample frequency comparison (leveraged AND unleveraged)...")

frequencies = ["daily", "weekly", "biweekly", "monthly", "quarterly"]

# Store returns for all strategies
lev_returns = {}   # leveraged at freq
base_returns = {}  # unleveraged at same freq
lev_metrics = {}
base_metrics = {}
lev_turnovers = {}

for freq in frequencies:
    # Leveraged strategy
    ret_l, turn_l = simulate_strategy(data, freq, leveraged=True)
    lev_returns[freq] = ret_l
    lev_metrics[freq] = compute_metrics(ret_l, data["rf_daily"])
    lev_metrics[freq]["annual_turnover"] = round(turn_l, 2)
    lev_turnovers[freq] = turn_l

    # Unleveraged base at SAME frequency
    ret_b, turn_b = simulate_strategy(data, freq, leveraged=False)
    base_returns[freq] = ret_b
    base_metrics[freq] = compute_metrics(ret_b, data["rf_daily"])
    base_metrics[freq]["annual_turnover"] = round(turn_b, 2)

    sharpe_diff = round(lev_metrics[freq]["sharpe"] - base_metrics[freq]["sharpe"], 3)
    cagr_diff = round(lev_metrics[freq]["cagr"] - base_metrics[freq]["cagr"], 2)

    print(f"  {freq:12s}: Lev Sharpe={lev_metrics[freq]['sharpe']:.3f}, "
          f"Base Sharpe={base_metrics[freq]['sharpe']:.3f}, "
          f"Diff={sharpe_diff:+.3f}, "
          f"Lev CAGR={lev_metrics[freq]['cagr']:.1f}%, "
          f"Turn={turn_l:.1f}x/yr")

# ════════════════════════════════════════════════════════════════
# Part 2: TX cost impact
# ════════════════════════════════════════════════════════════════
print("\n[3/8] Transaction cost impact...")

tx_impact = {}
for freq in frequencies:
    tx_impact[freq] = {}
    for tx_name, tx_rate in TX_COSTS.items():
        ret_tx, _ = simulate_strategy(data, freq, leveraged=True, tx_cost=tx_rate)
        m_tx = compute_metrics(ret_tx, data["rf_daily"])
        tx_impact[freq][tx_name] = {
            "sharpe": m_tx["sharpe"],
            "cagr": m_tx["cagr"],
            "sharpe_drag": round(lev_metrics[freq]["sharpe"] - m_tx["sharpe"], 4),
        }
    net_10bps = tx_impact[freq]["medium_10bps"]["sharpe"]
    print(f"  {freq:12s}: Gross Sharpe={lev_metrics[freq]['sharpe']:.3f}, "
          f"Net(10bps)={net_10bps:.3f}, Drag={tx_impact[freq]['medium_10bps']['sharpe_drag']:.4f}")

# ════════════════════════════════════════════════════════════════
# Part 3: FAIR Harvey test — leveraged vs unleveraged at SAME frequency
# ════════════════════════════════════════════════════════════════
print("\n[4/8] FAIR Harvey test: leveraged vs unleveraged at SAME frequency...")

harvey_fair = {}
for freq in frequencies:
    jk_t, jk_p = sharpe_diff_test(lev_returns[freq], base_returns[freq], data["rf_daily"])
    boot_mean, boot_lo, boot_hi, boot_pwin = bootstrap_sharpe_test(
        lev_returns[freq], base_returns[freq], data["rf_daily"], n_boot=5000
    )

    passes_harvey = jk_t > 3.0 if not np.isnan(jk_t) else False
    harvey_fair[freq] = {
        "jk_t": jk_t,
        "jk_p": jk_p,
        "passes_harvey_3": passes_harvey,
        "bootstrap_sharpe_diff_mean": boot_mean,
        "bootstrap_ci_95": [boot_lo, boot_hi],
        "bootstrap_p_win": boot_pwin,
        "lev_sharpe": lev_metrics[freq]["sharpe"],
        "base_sharpe": base_metrics[freq]["sharpe"],
    }
    status = "PASS" if passes_harvey else "FAIL"
    print(f"  {freq:12s}: Lev={lev_metrics[freq]['sharpe']:.3f} vs Base={base_metrics[freq]['sharpe']:.3f}, "
          f"JK_t={jk_t:.2f} ({status}), Boot P(win)={boot_pwin}%")

# ════════════════════════════════════════════════════════════════
# Part 4: Also test leveraged vs daily-unleveraged (original K548 comparison)
# ════════════════════════════════════════════════════════════════
print("\n[5/8] Harvey test: each freq leveraged vs DAILY unleveraged base...")

daily_base_ret = base_returns["daily"]
harvey_vs_daily_base = {}
for freq in frequencies:
    jk_t, jk_p = sharpe_diff_test(lev_returns[freq], daily_base_ret, data["rf_daily"])
    boot_mean, boot_lo, boot_hi, boot_pwin = bootstrap_sharpe_test(
        lev_returns[freq], daily_base_ret, data["rf_daily"], n_boot=5000
    )

    positive = jk_t > 0 if not np.isnan(jk_t) else False
    passes_harvey = jk_t > 3.0 if not np.isnan(jk_t) else False

    harvey_vs_daily_base[freq] = {
        "jk_t": jk_t,
        "jk_p": jk_p,
        "positive": positive,
        "passes_harvey_3": passes_harvey,
        "bootstrap_sharpe_diff_mean": boot_mean,
        "bootstrap_ci_95": [boot_lo, boot_hi],
        "bootstrap_p_win": boot_pwin,
    }
    direction = "+" if positive else "-"
    harv_status = "PASS" if passes_harvey else "FAIL"
    print(f"  {freq:12s} lev vs daily base: JK_t={jk_t:.2f} ({direction}) ({harv_status}), "
          f"Boot P(win)={boot_pwin}%")

# ════════════════════════════════════════════════════════════════
# Part 5: Degradation analysis — leveraged at freq vs leveraged daily
# ════════════════════════════════════════════════════════════════
print("\n[6/8] Degradation: leveraged at freq vs leveraged daily...")

daily_lev_sharpe = lev_metrics["daily"]["sharpe"]
daily_lev_cagr = lev_metrics["daily"]["cagr"]

degradation = {}
stat_vs_daily = {}

for freq in frequencies:
    m = lev_metrics[freq]
    sharpe_loss = round(daily_lev_sharpe - m["sharpe"], 4)
    cagr_loss = round(daily_lev_cagr - m["cagr"], 2)
    pct_retained = round(m["sharpe"] / daily_lev_sharpe * 100, 1) if daily_lev_sharpe > 0 else 0

    degradation[freq] = {
        "sharpe_loss_vs_daily_lev": sharpe_loss,
        "cagr_loss_vs_daily_lev": cagr_loss,
        "pct_sharpe_retained_vs_daily_lev": pct_retained,
    }

    if freq != "daily":
        jk_t, jk_p = sharpe_diff_test(lev_returns[freq], lev_returns["daily"], data["rf_daily"])
        boot_mean, boot_lo, boot_hi, boot_pwin = bootstrap_sharpe_test(
            lev_returns[freq], lev_returns["daily"], data["rf_daily"], n_boot=5000
        )
        stat_vs_daily[freq] = {
            "jk_t": jk_t,
            "jk_p": jk_p,
            "sig_p05": jk_p < 0.05 if not np.isnan(jk_p) else False,
            "bootstrap_sharpe_diff_mean": boot_mean,
            "bootstrap_ci_95": [boot_lo, boot_hi],
        }
        print(f"  {freq:12s}: Sharpe loss={sharpe_loss:.3f} ({pct_retained:.0f}% retained), "
              f"CAGR loss={cagr_loss:.1f}%, JK_t={jk_t:.2f} (sig={jk_p < 0.05 if not np.isnan(jk_p) else 'NA'})")
    else:
        stat_vs_daily[freq] = {"baseline": True}
        print(f"  {freq:12s}: BASELINE")

# ════════════════════════════════════════════════════════════════
# Part 6: Cross-OOS — leveraged vs unleveraged at SAME frequency
# ════════════════════════════════════════════════════════════════
print("\n[7/8] Cross-OOS (5 periods): leveraged vs unleveraged at SAME freq...")

oos_results = {}
for freq in frequencies:
    wins = 0
    period_details = []
    for j, (start, end) in enumerate(OOS_PERIODS):
        mask = (data.index >= start) & (data.index <= end)
        sub = data.loc[mask]
        if len(sub) < 100:
            continue

        ret_l, _ = simulate_strategy(sub, freq, leveraged=True)
        ret_b, _ = simulate_strategy(sub, freq, leveraged=False)

        m_l = compute_metrics(ret_l, sub["rf_daily"])
        m_b = compute_metrics(ret_b, sub["rf_daily"])

        if m_l is None or m_b is None:
            continue

        win = m_l["sharpe"] > m_b["sharpe"]
        if win:
            wins += 1

        period_details.append({
            "period": f"{start} to {end}",
            "lev_sharpe": m_l["sharpe"],
            "base_sharpe": m_b["sharpe"],
            "sharpe_diff": round(m_l["sharpe"] - m_b["sharpe"], 3),
            "lev_cagr": m_l["cagr"],
            "lev_mdd": m_l["mdd"],
            "base_cagr": m_b["cagr"],
            "base_mdd": m_b["mdd"],
            "win": win,
        })

    n_periods = len(period_details)
    oos_results[freq] = {
        "wins": wins,
        "total": n_periods,
        "win_rate": round(wins / n_periods * 100, 1) if n_periods > 0 else 0,
        "periods": period_details,
    }
    print(f"  {freq:12s}: {wins}/{n_periods} OOS wins (lev vs base at same freq)")

# ════════════════════════════════════════════════════════════════
# Part 7: Hybrid VIX check — daily VIX check + weekly/monthly rebalance
# ════════════════════════════════════════════════════════════════
print("\n[8/8] Hybrid: daily VIX check + periodic rebalance...")

hybrid_results = {}
for freq in ["weekly", "biweekly", "monthly", "quarterly"]:
    # Standard leveraged (check VIX only on rebal day)
    m_std = lev_metrics[freq]

    # Hybrid leveraged (check VIX daily for leverage, rebalance weight periodically)
    ret_hyb, turn_hyb = simulate_strategy(data, freq, leveraged=True, check_vix_daily=True)
    m_hyb = compute_metrics(ret_hyb, data["rf_daily"])

    sharpe_gain = round(m_hyb["sharpe"] - m_std["sharpe"], 4)

    # Also test hybrid vs same-freq base
    jk_t_hyb, jk_p_hyb = sharpe_diff_test(ret_hyb, base_returns[freq], data["rf_daily"])
    boot_hyb = bootstrap_sharpe_test(ret_hyb, base_returns[freq], data["rf_daily"], n_boot=5000)

    hybrid_results[freq] = {
        "standard_lev": {
            "sharpe": m_std["sharpe"],
            "cagr": m_std["cagr"],
            "mdd": m_std["mdd"],
        },
        "hybrid_daily_vix_lev": {
            "sharpe": m_hyb["sharpe"],
            "cagr": m_hyb["cagr"],
            "mdd": m_hyb["mdd"],
            "turnover": round(turn_hyb, 2),
        },
        "base_at_freq": {
            "sharpe": base_metrics[freq]["sharpe"],
        },
        "sharpe_gain_from_daily_vix_check": sharpe_gain,
        "hybrid_vs_base_jk_t": jk_t_hyb,
        "hybrid_vs_base_passes_harvey": jk_t_hyb > 3.0 if not np.isnan(jk_t_hyb) else False,
        "hybrid_vs_base_bootstrap_pwin": boot_hyb[3],
    }
    print(f"  {freq:12s}: standard={m_std['sharpe']:.3f}, "
          f"hybrid={m_hyb['sharpe']:.3f} (gain={sharpe_gain:+.4f}), "
          f"vs base JK_t={jk_t_hyb:.2f}")

# ════════════════════════════════════════════════════════════════
# Part 8: Cross-OOS for HYBRID (the deployable candidate)
# ════════════════════════════════════════════════════════════════
print("\n[BONUS] Cross-OOS for hybrid (daily VIX + periodic rebalance)...")

hybrid_oos = {}
for freq in ["weekly", "monthly"]:
    wins = 0
    period_details = []
    for j, (start, end) in enumerate(OOS_PERIODS):
        mask = (data.index >= start) & (data.index <= end)
        sub = data.loc[mask]
        if len(sub) < 100:
            continue

        ret_hyb, _ = simulate_strategy(sub, freq, leveraged=True, check_vix_daily=True)
        ret_base, _ = simulate_strategy(sub, freq, leveraged=False)

        m_hyb = compute_metrics(ret_hyb, sub["rf_daily"])
        m_base = compute_metrics(ret_base, sub["rf_daily"])

        if m_hyb is None or m_base is None:
            continue

        win = m_hyb["sharpe"] > m_base["sharpe"]
        if win:
            wins += 1

        period_details.append({
            "period": f"{start} to {end}",
            "hybrid_sharpe": m_hyb["sharpe"],
            "base_sharpe": m_base["sharpe"],
            "diff": round(m_hyb["sharpe"] - m_base["sharpe"], 3),
            "win": win,
        })

    n_periods = len(period_details)
    hybrid_oos[freq] = {
        "wins": wins,
        "total": n_periods,
        "win_rate": round(wins / n_periods * 100, 1) if n_periods > 0 else 0,
        "periods": period_details,
    }
    print(f"  {freq:12s} hybrid: {wins}/{n_periods} OOS wins vs base at same freq")

# ════════════════════════════════════════════════════════════════
# Summary & Conclusion
# ════════════════════════════════════════════════════════════════
elapsed = time.time() - t0

# Determine deployability
monthly_fair_harvey = harvey_fair.get("monthly", {}).get("passes_harvey_3", False)
weekly_fair_harvey = harvey_fair.get("weekly", {}).get("passes_harvey_3", False)
monthly_oos_wins = oos_results.get("monthly", {}).get("wins", 0)
weekly_oos_wins = oos_results.get("weekly", {}).get("wins", 0)
monthly_oos_total = oos_results.get("monthly", {}).get("total", 5)
weekly_oos_total = oos_results.get("weekly", {}).get("total", 5)

# Check hybrid
monthly_hybrid_harvey = hybrid_results.get("monthly", {}).get("hybrid_vs_base_passes_harvey", False)
weekly_hybrid_harvey = hybrid_results.get("weekly", {}).get("hybrid_vs_base_passes_harvey", False)
monthly_hybrid_oos = hybrid_oos.get("monthly", {}).get("wins", 0)
weekly_hybrid_oos = hybrid_oos.get("weekly", {}).get("wins", 0)

recommendation = ""
if monthly_fair_harvey and monthly_oos_wins >= 3:
    recommendation = ("MONTHLY VIX-Conditional Leverage is DEPLOYABLE for retail -- "
                      "passes Harvey t>3.0 at same rebalancing frequency with good OOS consistency.")
elif weekly_fair_harvey and weekly_oos_wins >= 3:
    recommendation = ("WEEKLY is the minimum viable frequency for VIX-Conditional Leverage -- "
                      "monthly loses too much signal but weekly passes Harvey at same freq.")
elif monthly_hybrid_harvey and monthly_hybrid_oos >= 3:
    recommendation = ("MONTHLY rebalancing with DAILY VIX leverage check (hybrid) is DEPLOYABLE -- "
                      "passes Harvey t>3.0, good OOS consistency. Requires daily VIX monitoring "
                      "but only monthly portfolio rebalancing.")
elif weekly_hybrid_harvey and weekly_hybrid_oos >= 3:
    recommendation = ("WEEKLY rebalancing with daily VIX leverage check (hybrid) is DEPLOYABLE -- "
                      "passes Harvey t>3.0, good OOS consistency. Requires daily VIX monitoring "
                      "but only weekly portfolio adjustment.")
elif monthly_hybrid_harvey:
    recommendation = ("MONTHLY hybrid (daily VIX check + monthly rebalance) passes Harvey "
                      f"but OOS weak ({monthly_hybrid_oos}/5). Use with caution.")
elif weekly_hybrid_harvey:
    recommendation = ("WEEKLY hybrid (daily VIX check + weekly rebalance) passes Harvey "
                      f"but OOS weak ({weekly_hybrid_oos}/5). Use with caution.")
else:
    recommendation = ("VIX-Conditional Leverage REQUIRES DAILY frequency -- "
                      "lower frequencies lose too much signal even with hybrid VIX check. "
                      "Not suitable for casual retail investors.")

summary = {
    "daily_lev_sharpe": lev_metrics["daily"]["sharpe"],
    "weekly_lev_sharpe": lev_metrics["weekly"]["sharpe"],
    "monthly_lev_sharpe": lev_metrics["monthly"]["sharpe"],
    "daily_base_sharpe": base_metrics["daily"]["sharpe"],
    "weekly_base_sharpe": base_metrics["weekly"]["sharpe"],
    "monthly_base_sharpe": base_metrics["monthly"]["sharpe"],
    "fair_comparison": {
        "weekly_lev_vs_weekly_base_harvey": harvey_fair["weekly"]["passes_harvey_3"],
        "monthly_lev_vs_monthly_base_harvey": harvey_fair["monthly"]["passes_harvey_3"],
    },
    "vs_daily_base": {
        "weekly_lev_better_than_daily_base": harvey_vs_daily_base["weekly"]["positive"],
        "monthly_lev_better_than_daily_base": harvey_vs_daily_base["monthly"]["positive"],
    },
    "oos_wins": {
        "daily": f"{oos_results['daily']['wins']}/{oos_results['daily']['total']}",
        "weekly": f"{oos_results['weekly']['wins']}/{oos_results['weekly']['total']}",
        "monthly": f"{oos_results['monthly']['wins']}/{oos_results['monthly']['total']}",
    },
    "hybrid_results": {
        "weekly_hybrid_sharpe": hybrid_results.get("weekly", {}).get("hybrid_daily_vix_lev", {}).get("sharpe"),
        "monthly_hybrid_sharpe": hybrid_results.get("monthly", {}).get("hybrid_daily_vix_lev", {}).get("sharpe"),
        "weekly_hybrid_passes_harvey": weekly_hybrid_harvey,
        "monthly_hybrid_passes_harvey": monthly_hybrid_harvey,
        "weekly_hybrid_oos_wins": f"{weekly_hybrid_oos}/{hybrid_oos.get('weekly', {}).get('total', 5)}",
        "monthly_hybrid_oos_wins": f"{monthly_hybrid_oos}/{hybrid_oos.get('monthly', {}).get('total', 5)}",
    },
    "recommendation": recommendation,
}

# Print summary tables
print("\n" + "=" * 80)
print("SUMMARY TABLE A: Leveraged Strategy at Each Frequency")
print("=" * 80)
print(f"{'Freq':12s} | {'Lev SR':>7s} | {'Base SR':>7s} | {'Diff':>6s} | {'Lev CAGR':>8s} | "
      f"{'Lev MDD':>8s} | {'Turn':>6s} | {'Harvey':>8s} | {'OOS':>5s}")
print("-" * 90)
for freq in frequencies:
    lm = lev_metrics[freq]
    bm = base_metrics[freq]
    hf = harvey_fair[freq]
    o = oos_results[freq]
    diff = round(lm["sharpe"] - bm["sharpe"], 3)
    harv_str = "PASS" if hf["passes_harvey_3"] else f"t={hf['jk_t']:.1f}"
    oos_str = f"{o['wins']}/{o['total']}"
    print(f"{freq:12s} | {lm['sharpe']:7.3f} | {bm['sharpe']:7.3f} | {diff:+6.3f} | "
          f"{lm['cagr']:7.1f}% | {lm['mdd']:7.1f}% | {lm['annual_turnover']:5.1f}x | "
          f"{harv_str:>8s} | {oos_str:>5s}")

print(f"\n  Note: 'Harvey' = FAIR test (lev vs base at SAME freq), OOS = lev vs base at same freq")

print("\n" + "=" * 80)
print("SUMMARY TABLE B: Degradation from Daily Leveraged")
print("=" * 80)
print(f"{'Freq':12s} | {'Sharpe':>7s} | {'Loss':>7s} | {'Retain':>7s} | {'Sig?':>5s}")
print("-" * 50)
for freq in frequencies:
    lm = lev_metrics[freq]
    d = degradation[freq]
    sig = stat_vs_daily.get(freq, {})
    sig_str = "Y" if sig.get("sig_p05", False) else ("base" if freq == "daily" else "N")
    print(f"{freq:12s} | {lm['sharpe']:7.3f} | {d['sharpe_loss_vs_daily_lev']:+7.3f} | "
          f"{d['pct_sharpe_retained_vs_daily_lev']:6.0f}% | {sig_str:>5s}")

print(f"\n  HYBRID approach (daily VIX check + periodic rebalance):")
for freq in ["weekly", "monthly"]:
    h = hybrid_results.get(freq, {})
    ho = hybrid_oos.get(freq, {})
    if h:
        hyb_sr = h['hybrid_daily_vix_lev']['sharpe']
        base_sr = h['base_at_freq']['sharpe']
        harv = "PASS" if h['hybrid_vs_base_passes_harvey'] else "FAIL"
        oos_str = f"{ho.get('wins', '?')}/{ho.get('total', '?')}"
        print(f"    {freq}: hybrid Sharpe={hyb_sr:.3f} (base={base_sr:.3f}), "
              f"Harvey: {harv}, OOS: {oos_str}")

print(f"\n  RECOMMENDATION: {recommendation}")
print(f"\n  Elapsed: {elapsed:.1f}s")

# ════════════════════════════════════════════════════════════════
# Save results
# ════════════════════════════════════════════════════════════════
results = {
    "experiment_id": "K577",
    "title": "Optimal Rebalancing Frequency for VIX-Conditional Leverage",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
    "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": len(data),
    "strategy_rule": "VIX<15 -> 1.5x, VIX>25 -> 1.0x, linear interp; 50/50 SPY/GLD + 12/VIX cap=1.0",
    "related_experiments": ["K548", "K551", "K499", "K562"],
    "references": [
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Fleming, Kirby, Ostdiek (2003) 'Economic Value of Volatility Timing' JFE",
        "Harvey & Liu (2016) '...and the Cross-Section of Expected Returns' RFS",
    ],
    "leveraged_metrics_by_freq": lev_metrics,
    "unleveraged_base_metrics_by_freq": base_metrics,
    "tx_cost_impact": tx_impact,
    "fair_harvey_test_lev_vs_base_same_freq": harvey_fair,
    "harvey_test_vs_daily_base": harvey_vs_daily_base,
    "degradation_vs_daily_lev": degradation,
    "stat_tests_freq_lev_vs_daily_lev": stat_vs_daily,
    "cross_oos_results": oos_results,
    "hybrid_vix_check": hybrid_results,
    "hybrid_oos_results": hybrid_oos,
    "summary": summary,
    "elapsed_seconds": round(elapsed, 1),
}

out_path = Path(__file__).parent / "k577_rebalancing_frequency_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {out_path}")
print("DONE.")
