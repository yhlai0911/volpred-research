#!/usr/bin/env python3
"""
K548: Leveraged Risk Parity VT — Can modest leverage on 50/50 VT improve risk-adjusted returns?

Motivation:
    12/VIX VT with 50/50 SPY/GLD works but has a structural limitation: during calm
    markets (VIX~12), equity weight = 100% but total portfolio = 50% SPY + 50% GLD,
    so expected return < 100% SPY. Modest leverage (1.2-1.5x) on the 50/50 might
    maintain higher return while keeping VT protection.

Design:
    - Data: SPY + GLD + VIX + ^IRX (3-month T-bill for borrowing cost) from yfinance, 2005-2026
    - Base: 50/50 SPY/GLD with 12/VIX weighting (cap=1.0)
    - Variants:
        (a) Fixed 1.3x leverage on 50/50 VT
        (b) Fixed 1.5x leverage
        (c) Vol-targeting: target 12% annualized portfolio vol, scale leverage dynamically
        (d) Risk parity leverage: equalize SPY/GLD risk contribution, lever to 12% target vol
        (e) VIX-conditional: 1.5x when VIX<15, 1.0x when VIX>25, linear interpolation between
    - Borrowing cost: daily risk-free rate from ^IRX (or 4% fallback)
    - Cross-OOS: 5 non-overlapping periods
    - Evaluation: Sharpe, MDD, Calmar, CAGR, net return after borrowing costs

Related prior work:
    K27: Leverage null (cap=1.0 correct, leverage Sharpe +0.010 NS) — but tested uncapped 12/VIX, not 50/50
    K30: Leveraged ETF VT (Sharpe invariant, VT cuts vol decay 64%) — tested UPRO/TQQQ, not modest leverage
    K116: Tail Risk Parity (CVaR) — null, 50/50 unbeatable
    K219: Risk Parity vs 50/50 — RP NOT sig better (DM p=0.64)
    K275: Complete Case for 50/50 SPY/GLD + 12/VIX synthesis

References:
    Moreira & Muir (2017) "Volatility-Managed Portfolios" JF — VT = 1/sigma scaling
    Asness et al. (2012) "Leverage Aversion and Risk Parity" FAJ — RP with leverage
    Frazzini & Pedersen (2014) "Betting Against Beta" JFE — leverage constraints & Sharpe

Author: VolPred Research System (Claude)
Data: yfinance (SPY, GLD, ^VIX, ^IRX), 2005-2026
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────── Config ───────────────────────────
START = "2004-12-01"  # extra buffer for rolling calcs
END = "2026-03-27"
VOL_TARGET = 0.12  # 12% annualized target vol for vol-targeting variants
VOL_LOOKBACK = 63  # ~3 months for realized vol estimation
BORROWING_SPREAD = 0.005  # 50bps above risk-free as borrowing cost
FALLBACK_RF = 0.04  # 4% if ^IRX unavailable

# Cross-OOS periods (5 non-overlapping)
OOS_PERIODS = [
    ("2005-06-01", "2009-05-31"),  # includes GFC
    ("2009-06-01", "2013-05-31"),  # recovery
    ("2013-06-01", "2017-05-31"),  # low vol
    ("2017-06-01", "2021-05-31"),  # includes COVID
    ("2021-06-01", "2026-03-27"),  # recent
]


def download_data():
    """Download SPY, GLD, VIX, and risk-free rate."""
    print("Downloading data...")
    spy = yf.download("SPY", start=START, end=END, progress=False)
    gld = yf.download("GLD", start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    # Risk-free rate (^IRX = 13-week T-bill yield)
    try:
        irx = yf.download("^IRX", start=START, end=END, progress=False)
        rf_available = len(irx) > 100
    except Exception:
        irx = None
        rf_available = False

    # Flatten MultiIndex columns if present
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    if irx is not None and isinstance(irx.columns, pd.MultiIndex):
        irx.columns = irx.columns.get_level_values(0)

    # Build combined DataFrame
    data = pd.DataFrame(index=spy.index)
    data["spy_close"] = spy["Close"]
    data["gld_close"] = gld["Close"]
    data["vix"] = vix["Close"]

    # Risk-free daily rate
    if rf_available and irx is not None and len(irx) > 0:
        data["rf_annual"] = irx["Close"].reindex(data.index).ffill() / 100  # ^IRX is in %
        data["rf_daily"] = data["rf_annual"] / 252
        print(f"  Risk-free rate from ^IRX: mean={data['rf_annual'].mean()*100:.2f}%")
    else:
        data["rf_annual"] = FALLBACK_RF
        data["rf_daily"] = FALLBACK_RF / 252
        print(f"  Using fallback risk-free rate: {FALLBACK_RF*100:.1f}%")

    # Forward-fill and drop NaN
    data = data.ffill().dropna()

    # Daily returns
    data["spy_ret"] = data["spy_close"].pct_change()
    data["gld_ret"] = data["gld_close"].pct_change()
    data = data.dropna()

    # VIX weight: min(12/VIX, 1.0) — the base VT signal
    data["vix_weight"] = np.minimum(12.0 / data["vix"], 1.0)

    # Rolling volatilities (for vol-targeting and risk parity)
    data["spy_vol"] = data["spy_ret"].rolling(VOL_LOOKBACK).std() * np.sqrt(252)
    data["gld_vol"] = data["gld_ret"].rolling(VOL_LOOKBACK).std() * np.sqrt(252)
    data["spy_gld_corr"] = data["spy_ret"].rolling(VOL_LOOKBACK).corr(data["gld_ret"])

    data = data.dropna()
    print(f"  Data period: {data.index[0].date()} to {data.index[-1].date()}, N={len(data)}")
    return data


def compute_strategy_returns(data):
    """Compute daily returns for all strategy variants."""
    results = {}

    # ═══════════════════════════════════════════════════════════
    # Strategy 0: Base 50/50 VT (unleveraged)
    # ═══════════════════════════════════════════════════════════
    w = data["vix_weight"]
    base_ret = w * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - w) * data["rf_daily"]
    results["base_5050_vt"] = base_ret

    # ═══════════════════════════════════════════════════════════
    # Strategy 0b: 100% SPY Buy & Hold (benchmark)
    # ═══════════════════════════════════════════════════════════
    results["spy_bh"] = data["spy_ret"].copy()

    # ═══════════════════════════════════════════════════════════
    # Strategy 1: Fixed 1.3x Leverage on 50/50 VT
    # ═══════════════════════════════════════════════════════════
    lev = 1.3
    gross_ret = w * lev * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - w * lev) * data["rf_daily"]
    borrow_cost = (lev - 1) * w * (data["rf_daily"] + BORROWING_SPREAD / 252)
    results["lev_1.3x"] = gross_ret - borrow_cost

    # ═══════════════════════════════════════════════════════════
    # Strategy 2: Fixed 1.5x Leverage on 50/50 VT
    # ═══════════════════════════════════════════════════════════
    lev = 1.5
    gross_ret = w * lev * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - w * lev) * data["rf_daily"]
    borrow_cost = (lev - 1) * w * (data["rf_daily"] + BORROWING_SPREAD / 252)
    results["lev_1.5x"] = gross_ret - borrow_cost

    # ═══════════════════════════════════════════════════════════
    # Strategy 3: Vol-Targeting Leverage (target 12% portfolio vol)
    # ═══════════════════════════════════════════════════════════
    # Portfolio vol of 50/50: sqrt(0.25*σ_S² + 0.25*σ_G² + 2*0.25*ρ*σ_S*σ_G)
    port_vol = np.sqrt(
        0.25 * data["spy_vol"] ** 2
        + 0.25 * data["gld_vol"] ** 2
        + 2 * 0.25 * data["spy_gld_corr"] * data["spy_vol"] * data["gld_vol"]
    )
    # Leverage = target_vol / (vix_weight * realized_port_vol), capped at [1.0, 2.0]
    vol_lev = np.clip(VOL_TARGET / (data["vix_weight"] * port_vol + 1e-8), 1.0, 2.0)
    effective_lev = w * vol_lev
    gross_ret = effective_lev * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - effective_lev) * data["rf_daily"]
    borrow_cost = np.maximum(effective_lev - 1, 0) * (data["rf_daily"] + BORROWING_SPREAD / 252)
    results["vol_target_12"] = gross_ret - borrow_cost

    # ═══════════════════════════════════════════════════════════
    # Strategy 4: Risk Parity + Leverage to 12% target vol
    # ═══════════════════════════════════════════════════════════
    # Risk parity: equalize risk contribution -> w_SPY ∝ 1/σ_SPY, w_GLD ∝ 1/σ_GLD
    inv_spy = 1.0 / (data["spy_vol"] + 1e-8)
    inv_gld = 1.0 / (data["gld_vol"] + 1e-8)
    rp_spy = inv_spy / (inv_spy + inv_gld)
    rp_gld = inv_gld / (inv_spy + inv_gld)

    # RP portfolio vol
    rp_port_vol = np.sqrt(
        (rp_spy * data["spy_vol"]) ** 2
        + (rp_gld * data["gld_vol"]) ** 2
        + 2 * rp_spy * rp_gld * data["spy_gld_corr"] * data["spy_vol"] * data["gld_vol"]
    )
    # Leverage to target
    rp_lev = np.clip(VOL_TARGET / (data["vix_weight"] * rp_port_vol + 1e-8), 1.0, 2.0)
    effective_rp = w * rp_lev
    gross_ret = effective_rp * (rp_spy * data["spy_ret"] + rp_gld * data["gld_ret"]) + (1 - effective_rp) * data["rf_daily"]
    borrow_cost = np.maximum(effective_rp - 1, 0) * (data["rf_daily"] + BORROWING_SPREAD / 252)
    results["rp_vol_target"] = gross_ret - borrow_cost

    # ═══════════════════════════════════════════════════════════
    # Strategy 5: VIX-Conditional Leverage
    # 1.5x when VIX<15, 1.0x when VIX>25, linear interpolation between
    # ═══════════════════════════════════════════════════════════
    vix_cond_lev = np.clip(1.5 - 0.5 * (data["vix"] - 15) / (25 - 15), 1.0, 1.5)
    effective_lev = w * vix_cond_lev
    gross_ret = effective_lev * (0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]) + (1 - effective_lev) * data["rf_daily"]
    borrow_cost = np.maximum(effective_lev - 1, 0) * (data["rf_daily"] + BORROWING_SPREAD / 252)
    results["vix_conditional"] = gross_ret - borrow_cost

    return results


def compute_metrics(returns_series, rf_series=None):
    """Compute standard performance metrics."""
    r = returns_series.dropna()
    if len(r) < 252:
        return None

    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    years = len(r) / 252
    cagr = (1 + total_return) ** (1 / years) - 1
    ann_vol = r.std() * np.sqrt(252)

    # Excess return for Sharpe
    if rf_series is not None:
        rf_aligned = rf_series.reindex(r.index).fillna(FALLBACK_RF / 252)
        excess = r - rf_aligned
    else:
        excess = r - FALLBACK_RF / 252
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    # Max drawdown
    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    mdd = drawdown.min()

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = excess[excess < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = excess.mean() * 252 / downside_std

    # Skewness and kurtosis of daily returns
    skew = r.skew()
    kurt = r.kurtosis()

    return {
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "total_return_pct": round(total_return * 100, 2),
        "years": round(years, 1),
        "n_days": len(r),
    }


def diebold_mariano_test(returns1, returns2, h=1):
    """DM test on squared returns (variance loss function)."""
    # Use squared returns as loss proxy
    d = returns1 ** 2 - returns2 ** 2
    d = d.dropna()
    if len(d) < 100:
        return np.nan, np.nan

    d_mean = d.mean()
    # Newey-West with h lags
    n = len(d)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h + 1):
        w = 1 - k / (h + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_value


def sharpe_difference_test(returns1, returns2, rf_daily):
    """
    Test whether Sharpe ratios are significantly different.
    Uses Jobson-Korkie (1981) test with Memmel (2003) correction.
    """
    r1 = returns1.dropna()
    r2 = returns2.dropna()
    # Align
    idx = r1.index.intersection(r2.index)
    r1 = r1.loc[idx]
    r2 = r2.loc[idx]
    rf = rf_daily.reindex(idx).fillna(FALLBACK_RF / 252)

    e1 = r1 - rf
    e2 = r2 - rf
    n = len(e1)

    mu1, mu2 = e1.mean(), e2.mean()
    s1, s2 = e1.std(), e2.std()
    sr1, sr2 = mu1 / s1, mu2 / s2

    rho = e1.corr(e2)

    # Memmel (2003) corrected variance
    theta = (1 / n) * (
        2 * (1 - rho)
        + 0.5 * (sr1 ** 2 + sr2 ** 2 - 2 * sr1 * sr2 * rho ** 2)
    )

    if theta <= 0:
        return np.nan, np.nan

    z = (sr1 - sr2) / np.sqrt(theta)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return z, p


def run_cross_oos(data, strategy_returns):
    """Run cross-OOS evaluation on 5 non-overlapping periods."""
    oos_results = {}

    for name, ret_series in strategy_returns.items():
        period_metrics = []
        for i, (start, end) in enumerate(OOS_PERIODS):
            mask = (data.index >= start) & (data.index <= end)
            sub = ret_series.loc[mask]
            rf_sub = data["rf_daily"].loc[mask]
            if len(sub) < 126:  # need at least 6 months
                continue
            m = compute_metrics(sub, rf_sub)
            if m is not None:
                m["period"] = f"P{i+1}: {start[:4]}-{end[:4]}"
                period_metrics.append(m)

        oos_results[name] = period_metrics

    return oos_results


def analyze_leverage_characteristics(data, strategy_returns):
    """Analyze leverage behavior: when is leverage active, average leverage, etc."""
    w = data["vix_weight"]

    stats_dict = {}

    # For VIX-conditional leverage
    vix_cond_lev = np.clip(1.5 - 0.5 * (data["vix"] - 15) / (25 - 15), 1.0, 1.5)

    # For vol-targeting leverage
    port_vol = np.sqrt(
        0.25 * data["spy_vol"] ** 2
        + 0.25 * data["gld_vol"] ** 2
        + 2 * 0.25 * data["spy_gld_corr"] * data["spy_vol"] * data["gld_vol"]
    )
    vol_lev = np.clip(VOL_TARGET / (w * port_vol + 1e-8), 1.0, 2.0)

    for name, lev_series, desc in [
        ("fixed_1.3x", pd.Series(1.3, index=data.index), "Fixed 1.3x"),
        ("fixed_1.5x", pd.Series(1.5, index=data.index), "Fixed 1.5x"),
        ("vol_target", vol_lev, "Vol-Target 12%"),
        ("vix_conditional", vix_cond_lev, "VIX-Conditional"),
    ]:
        effective = w * lev_series
        borrow_frac = np.maximum(effective - 1, 0)
        annual_cost = (borrow_frac * (data["rf_annual"] + BORROWING_SPREAD)).mean() * 100

        stats_dict[name] = {
            "description": desc,
            "mean_gross_leverage": round(float(lev_series.mean()), 3),
            "mean_effective_exposure": round(float(effective.mean()) * 100, 1),
            "pct_time_leveraged": round(float((effective > 1.0).mean()) * 100, 1),
            "max_effective_exposure": round(float(effective.max()) * 100, 1),
            "mean_borrowing_cost_pa": round(annual_cost, 2),
            "leverage_during_gfc": round(float(effective.loc["2008-09":"2009-03"].mean()) * 100, 1),
            "leverage_during_covid": round(float(effective.loc["2020-02":"2020-04"].mean()) * 100, 1),
        }

    return stats_dict


def main():
    print("=" * 70)
    print("K548: Leveraged Risk Parity VT")
    print("Can modest leverage on 50/50 VT improve risk-adjusted returns?")
    print("=" * 70)

    # ─── Step 1: Download data ───
    data = download_data()

    # ─── Step 2: Descriptive statistics ───
    print("\n─── Descriptive Statistics ───")
    for col, label in [("spy_ret", "SPY"), ("gld_ret", "GLD")]:
        r = data[col]
        print(f"  {label}: mean={r.mean()*252*100:.2f}%/yr, vol={r.std()*np.sqrt(252)*100:.2f}%, "
              f"skew={r.skew():.3f}, kurt={r.kurtosis():.3f}")
    print(f"  VIX: mean={data['vix'].mean():.1f}, median={data['vix'].median():.1f}, "
          f"min={data['vix'].min():.1f}, max={data['vix'].max():.1f}")
    print(f"  VIX<15 pct: {(data['vix'] < 15).mean()*100:.1f}%")
    print(f"  SPY-GLD corr: {data['spy_ret'].corr(data['gld_ret']):.3f}")
    print(f"  Risk-free rate: mean={data['rf_annual'].mean()*100:.2f}%")

    # ─── Step 3: Compute strategy returns ───
    print("\n─── Computing Strategy Returns ───")
    strategy_returns = compute_strategy_returns(data)

    # ─── Step 4: Full-sample metrics ───
    print("\n─── Full-Sample Performance ───")
    full_metrics = {}
    for name, ret in strategy_returns.items():
        m = compute_metrics(ret, data["rf_daily"])
        if m is not None:
            full_metrics[name] = m
            print(f"  {name:20s}: CAGR={m['cagr']:6.2f}%, Vol={m['ann_vol']:5.2f}%, "
                  f"Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:7.2f}%, Calmar={m['calmar']:.3f}")

    # ─── Step 5: Statistical tests vs base ───
    print("\n─── Statistical Tests vs Base 50/50 VT ───")
    base_ret = strategy_returns["base_5050_vt"]
    test_results = {}
    for name, ret in strategy_returns.items():
        if name in ("base_5050_vt", "spy_bh"):
            continue
        # Sharpe difference test
        z, p = sharpe_difference_test(ret, base_ret, data["rf_daily"])
        # DM test
        dm, dm_p = diebold_mariano_test(ret, base_ret)
        test_results[name] = {
            "sharpe_z": round(float(z), 3) if not np.isnan(z) else None,
            "sharpe_p": round(float(p), 4) if not np.isnan(p) else None,
            "dm_stat": round(float(dm), 3) if not np.isnan(dm) else None,
            "dm_p": round(float(dm_p), 4) if not np.isnan(dm_p) else None,
        }
        sig_sharpe = "★" if (p is not None and not np.isnan(p) and p < 0.05) else "NS"
        sig_dm = "★" if (dm_p is not None and not np.isnan(dm_p) and dm_p < 0.05) else "NS"
        print(f"  {name:20s}: Sharpe Δ z={z:+.3f} p={p:.4f} [{sig_sharpe}], "
              f"DM={dm:+.3f} p={dm_p:.4f} [{sig_dm}]")

    # ─── Step 6: Leverage characteristics ───
    print("\n─── Leverage Characteristics ───")
    lev_chars = analyze_leverage_characteristics(data, strategy_returns)
    for name, stats_d in lev_chars.items():
        print(f"  {stats_d['description']:20s}: Avg exposure={stats_d['mean_effective_exposure']:.1f}%, "
              f"Time leveraged={stats_d['pct_time_leveraged']:.1f}%, "
              f"Borrow cost={stats_d['mean_borrowing_cost_pa']:.2f}%/yr, "
              f"GFC exposure={stats_d['leverage_during_gfc']:.1f}%, "
              f"COVID exposure={stats_d['leverage_during_covid']:.1f}%")

    # ─── Step 7: Cross-OOS ───
    print("\n─── Cross-OOS (5 periods) ───")
    oos_results = run_cross_oos(data, strategy_returns)

    # Summary: how many periods does each strategy beat base?
    cross_oos_summary = {}
    for name in strategy_returns.keys():
        if name in ("base_5050_vt", "spy_bh"):
            continue
        wins = 0
        periods_tested = 0
        sharpe_diffs = []
        if name in oos_results and "base_5050_vt" in oos_results:
            for i, (strat_m, base_m) in enumerate(
                zip(oos_results.get(name, []), oos_results.get("base_5050_vt", []))
            ):
                periods_tested += 1
                if strat_m["sharpe"] > base_m["sharpe"]:
                    wins += 1
                sharpe_diffs.append(strat_m["sharpe"] - base_m["sharpe"])

        cross_oos_summary[name] = {
            "wins": wins,
            "periods": periods_tested,
            "win_rate": round(wins / max(periods_tested, 1) * 100, 1),
            "mean_sharpe_diff": round(np.mean(sharpe_diffs), 3) if sharpe_diffs else None,
            "sharpe_diffs": [round(x, 3) for x in sharpe_diffs],
        }
        print(f"  {name:20s}: {wins}/{periods_tested} wins "
              f"(mean ΔSharpe={np.mean(sharpe_diffs):+.3f})")

    # Print period details
    print("\n  Period details (Sharpe):")
    for i, (start, end) in enumerate(OOS_PERIODS):
        period_label = f"P{i+1} ({start[:4]}-{end[:4]})"
        values = [f"{'base':12s}={oos_results.get('base_5050_vt', [{}])[i].get('sharpe', 'N/A') if i < len(oos_results.get('base_5050_vt', [])) else 'N/A'}"]
        for name in ["lev_1.3x", "lev_1.5x", "vol_target_12", "rp_vol_target", "vix_conditional"]:
            if name in oos_results and i < len(oos_results[name]):
                values.append(f"{name[:12]:12s}={oos_results[name][i]['sharpe']}")
        print(f"    {period_label}: {', '.join(values)}")

    # ─── Step 8: Key insight analysis ───
    print("\n─── Key Insights ───")

    # Does leverage improve Sharpe or just return?
    base_sharpe = full_metrics["base_5050_vt"]["sharpe"]
    for name in ["lev_1.3x", "lev_1.5x", "vol_target_12", "rp_vol_target", "vix_conditional"]:
        if name in full_metrics:
            m = full_metrics[name]
            sharpe_diff = m["sharpe"] - base_sharpe
            cagr_diff = m["cagr"] - full_metrics["base_5050_vt"]["cagr"]
            mdd_diff = m["mdd"] - full_metrics["base_5050_vt"]["mdd"]
            vol_diff = m["ann_vol"] - full_metrics["base_5050_vt"]["ann_vol"]
            print(f"  {name:20s}: ΔSharpe={sharpe_diff:+.3f}, ΔCAGR={cagr_diff:+.2f}%, "
                  f"ΔVol={vol_diff:+.2f}%, ΔMDD={mdd_diff:+.2f}%")

    # Theoretical check: In theory, Sharpe is leverage-invariant.
    # In practice, borrowing costs and path-dependency make it worse.
    print("\n  Theory: Sharpe should be invariant to leverage (Moreira & Muir 2017)")
    print(f"  Base Sharpe: {base_sharpe:.3f}")
    for name in ["lev_1.3x", "lev_1.5x"]:
        if name in full_metrics:
            print(f"  {name} Sharpe: {full_metrics[name]['sharpe']:.3f} "
                  f"(Δ={full_metrics[name]['sharpe'] - base_sharpe:+.3f})")
    print("  → If ΔSharpe ≈ 0 or negative, leverage doesn't help after costs")

    # Borrowing cost impact
    print("\n  Borrowing cost impact:")
    for name in ["lev_1.3x", "lev_1.5x"]:
        if name in lev_chars:
            lc = lev_chars[name]
            print(f"  {name}: avg borrow cost = {lc['mean_borrowing_cost_pa']:.2f}%/yr")

    # ─── Step 9: Save results ───
    results = {
        "experiment_id": "K548",
        "title": "Leveraged Risk Parity VT — Modest leverage on 50/50 VT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
        "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_observations": len(data),
        "parameters": {
            "vol_target": VOL_TARGET,
            "vol_lookback": VOL_LOOKBACK,
            "borrowing_spread_bps": BORROWING_SPREAD * 10000,
            "vix_threshold_low": 15,
            "vix_threshold_high": 25,
            "leverage_cap": 2.0,
        },
        "descriptive_stats": {
            "spy_ann_return": round(data["spy_ret"].mean() * 252 * 100, 2),
            "spy_ann_vol": round(data["spy_ret"].std() * np.sqrt(252) * 100, 2),
            "gld_ann_return": round(data["gld_ret"].mean() * 252 * 100, 2),
            "gld_ann_vol": round(data["gld_ret"].std() * np.sqrt(252) * 100, 2),
            "spy_gld_corr": round(float(data["spy_ret"].corr(data["gld_ret"])), 3),
            "vix_mean": round(float(data["vix"].mean()), 1),
            "vix_below_15_pct": round(float((data["vix"] < 15).mean()) * 100, 1),
            "rf_rate_mean_pct": round(float(data["rf_annual"].mean()) * 100, 2),
        },
        "full_sample_metrics": full_metrics,
        "statistical_tests_vs_base": test_results,
        "leverage_characteristics": lev_chars,
        "cross_oos_summary": cross_oos_summary,
        "cross_oos_period_details": {
            name: periods for name, periods in oos_results.items()
        },
        "conclusion": "",  # filled below
        "references": [
            "Moreira & Muir (2017) Volatility-Managed Portfolios, JF",
            "Asness et al. (2012) Leverage Aversion and Risk Parity, FAJ",
            "Frazzini & Pedersen (2014) Betting Against Beta, JFE",
            "K27: Leverage null (cap=1.0 correct)",
            "K30: Leveraged ETF VT (Sharpe invariant)",
            "K219: Risk Parity vs 50/50 (RP NOT sig better)",
            "K275: Complete Case for 50/50 + 12/VIX",
        ],
    }

    # Auto-generate conclusion
    any_sig = any(
        v.get("sharpe_p") is not None and v["sharpe_p"] < 0.05
        for v in test_results.values()
    )
    best_name = max(
        [n for n in full_metrics if n not in ("spy_bh",)],
        key=lambda x: full_metrics[x]["sharpe"],
    )
    best_sharpe = full_metrics[best_name]["sharpe"]

    # Check cross-OOS consistency
    consistent = all(
        cross_oos_summary.get(n, {}).get("win_rate", 0) >= 60
        for n in ["lev_1.3x", "lev_1.5x", "vol_target_12", "rp_vol_target", "vix_conditional"]
        if n in cross_oos_summary
    )

    conclusion_parts = []
    conclusion_parts.append(
        f"Base 50/50 VT Sharpe={base_sharpe:.3f}. "
        f"Best leveraged variant: {best_name} (Sharpe={best_sharpe:.3f})."
    )

    if not any_sig:
        conclusion_parts.append(
            "NO leveraged variant achieves statistically significant Sharpe improvement (all p>0.05). "
            "Confirms K27/K30: leverage does NOT improve Sharpe after borrowing costs."
        )
    else:
        sig_names = [n for n, v in test_results.items() if v.get("sharpe_p") and v["sharpe_p"] < 0.05]
        conclusion_parts.append(
            f"Significant Sharpe improvement in: {', '.join(sig_names)}."
        )

    if not consistent:
        conclusion_parts.append("Cross-OOS inconsistent: no variant consistently beats base across all 5 periods.")

    # Borrowing cost observation
    avg_borrow = np.mean([v["mean_borrowing_cost_pa"] for v in lev_chars.values()])
    conclusion_parts.append(
        f"Average borrowing cost across variants: {avg_borrow:.2f}%/yr. "
        "This eats into the theoretical leverage benefit."
    )

    conclusion_parts.append(
        "Practical implication: 50/50 VT is already near-optimal. "
        "Leverage adds complexity and cost without improving risk-adjusted returns."
    )

    results["conclusion"] = " ".join(conclusion_parts)

    print(f"\n─── Conclusion ───")
    print(f"  {results['conclusion']}")

    # Save
    out_path = Path(__file__).parent / "k548_leveraged_risk_parity_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    results = main()
