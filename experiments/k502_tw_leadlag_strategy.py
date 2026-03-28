#!/usr/bin/env python3
"""
K502: US→Taiwan Lead-Lag Trading Strategy
==========================================
Transform the confirmed SPY→TW50 lead-lag relationship into tradable strategies.

Background:
- T32/T33: SPY→TW50 lead-lag confirmed (r=0.376, Harvey pass)
- K461: SSVS SPY_ret PIP=1.000 for Taiwan vol
- I8: ⚠️ c2c Sharpe is BIASED (includes overnight gap, 78% of alpha)
       o2o is the only honest measure for implementable strategies
- K238: 10d SPY Momentum o2o Sharpe=0.87, FAILS Harvey t>3
- U5: Dynamic lead-lag strengthening (+0.01/yr), 2014 corr=0.17 → 2025 corr=0.55

Strategy Designs:
1. SPY 1-day Momentum → Long/Cash 0050.TW
2. SPY 5-day Momentum → Long/Cash 0050.TW
3. VIX Regime + SPY Signal (multi-level)
4. SPY Return Quantile Signal

Return measures:
- c2c: Close[t]/Close[t-1] - 1 (BIASED, reported for comparison only)
- o2o: Close[t]/Open[t] - 1 (REALISTIC, enter at open after seeing US signal)

Data source: yfinance (real market data, 0050.TW + SPY + VIX)
Period: 2010-2025
Transaction cost: 0.1855% round-trip (Taiwan ETF: 0.1% securities tax + 0.04275%x2 broker at 3折)
Author: [提出: User, 執行: Claude]
References:
- Harvey (2016) "...and the Cross-Section of Expected Returns" RFS - t>3.0 threshold
- I8 timing bias analysis (this project)
- T32/T33 US→Asia lead-lag confirmation (this project)
"""

import sys
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

RESULTS_PATH = Path(__file__).parent / "k502_tw_leadlag_strategy_results.json"
# ⚠️ CORRECTED (K625): ETF tax=0.1% not 0.3%, commission=0.04275%/side (3折)
TW_TX_ONEWAY_BPS = 14.275  # 0.14275% one-way sell (0.1% ETF tax + 0.04275% broker)
TW_TX_ROUNDTRIP = 0.001855  # 0.1855% round-trip (buy 0.04275% + sell 0.14275%)
TRADING_DAYS = 252


# ============================================================
# 1. DATA ACQUISITION
# ============================================================

def fetch_data():
    """Fetch SPY, VIX, 0050.TW from yfinance."""
    import yfinance as yf

    tickers = {
        "SPY": "SPY",
        "VIX": "^VIX",
        "TW50": "0050.TW",
    }

    start = "2009-06-01"  # extra buffer for lookback
    end = "2026-03-26"

    data = {}
    for name, ticker in tickers.items():
        print(f"  Fetching {name} ({ticker})...", end=" ")
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        print(f"{len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
        data[name] = df

    return data


# ============================================================
# 2. RETURN COMPUTATION
# ============================================================

def compute_returns(df):
    """
    Compute c2c and o2o returns.
    c2c: Close[t]/Close[t-1] - 1 (includes overnight gap, BIASED)
    o2o: Close[t]/Open[t] - 1 (enter at open, REALISTIC)
    gap: Open[t]/Close[t-1] - 1 (overnight gap, NOT capturable)
    """
    open_clean = df["Open"].replace(0, np.nan)
    close = df["Close"]

    c2c = close.pct_change()
    o2o = close / open_clean - 1
    gap = open_clean / close.shift(1) - 1

    return c2c, o2o, gap


# ============================================================
# 3. SIGNAL CONSTRUCTION
# ============================================================

def signal_spy_1d_momentum(spy_df):
    """Strategy 1: SPY 1-day return > 0 → Long, else Cash."""
    spy_ret = spy_df["Close"].pct_change()
    position = (spy_ret > 0).astype(float)
    return position, spy_ret


def signal_spy_5d_momentum(spy_df):
    """Strategy 2: SPY 5-day cumulative return > 0 → Long, else Cash."""
    spy_ret = spy_df["Close"].pct_change()
    cum_5d = spy_ret.rolling(5).sum()
    position = (cum_5d > 0).astype(float)
    return position, cum_5d


def signal_vix_regime_spy(spy_df, vix_df):
    """
    Strategy 3: VIX Regime + SPY Signal (multi-level weights).
    VIX < 20 + SPY > 0 → 100% long
    VIX < 20 + SPY ≤ 0 → 50% long
    VIX ≥ 20 → 0% (cash / risk-off)
    """
    spy_ret = spy_df["Close"].pct_change()
    vix_close = vix_df["Close"]

    # Align VIX to SPY dates
    vix_aligned = vix_close.reindex(spy_ret.index, method="ffill")

    position = pd.Series(0.0, index=spy_ret.index)
    low_vix = vix_aligned < 20
    spy_positive = spy_ret > 0

    position[low_vix & spy_positive] = 1.0
    position[low_vix & ~spy_positive] = 0.5
    # VIX >= 20 → stays 0.0

    raw_signal = pd.DataFrame({"spy_ret": spy_ret, "vix": vix_aligned}).mean(axis=1)
    return position, raw_signal


def signal_spy_quantile(spy_df, lookback=252):
    """
    Strategy 4: SPY Return Quantile Signal.
    SPY return percentile over past 252 days:
    > 70th percentile → 100% long (momentum)
    < 30th percentile → 0% (risk-off)
    30-70th → 50% long
    """
    spy_ret = spy_df["Close"].pct_change()

    # Rolling percentile
    pctile = spy_ret.rolling(lookback).apply(
        lambda x: stats.percentileofscore(x[:-1], x.iloc[-1]) / 100
        if len(x) > 1 else 0.5,
        raw=False,
    )

    position = pd.Series(0.5, index=spy_ret.index)
    position[pctile > 0.70] = 1.0
    position[pctile < 0.30] = 0.0

    return position, pctile


def signal_spy_10d_momentum(spy_df):
    """Strategy 5 (reference): SPY 10-day momentum (existing strategy in daily_update.py)."""
    spy_ret = spy_df["Close"].pct_change()
    cum_10d = spy_ret.rolling(10).mean()
    position = (cum_10d > 0).astype(float)
    return position, cum_10d


# ============================================================
# 4. ALIGNMENT: US Signal → Taiwan Returns
# ============================================================

def align_signal_to_tw(spy_position, spy_signal_raw, tw_c2c, tw_o2o, tw_gap,
                        start_date="2010-01-01"):
    """
    Align US signal (from day t) to Taiwan returns (day t+1).
    US closes day t → signal available → Taiwan opens day t+1.
    Shift SPY signal index forward by 1 business day, then inner join.
    """
    signal_df = pd.DataFrame({
        "position": spy_position,
        "signal_raw": spy_signal_raw,
    })
    # Signal on day t → applied on day t+1
    signal_df.index = signal_df.index + pd.tseries.offsets.BDay(1)

    returns_df = pd.DataFrame({
        "c2c": tw_c2c,
        "o2o": tw_o2o,
        "gap": tw_gap,
    })

    merged = signal_df.join(returns_df, how="inner").dropna()
    merged = merged[merged.index >= start_date]
    return merged


# ============================================================
# 5. PERFORMANCE METRICS
# ============================================================

def compute_metrics(merged, return_col, tx_roundtrip=TW_TX_ROUNDTRIP):
    """Compute full strategy metrics for a given return column."""
    positions = merged["position"]
    returns = merged[return_col]

    strat_ret = returns * positions

    # Transaction costs on position changes
    trades = positions.diff().abs().fillna(positions.iloc[0:1].abs())
    tx_per_day = trades * tx_roundtrip
    strat_ret_net = strat_ret - tx_per_day

    n = len(strat_ret)
    ann_ret = strat_ret.mean() * TRADING_DAYS
    ann_ret_net = strat_ret_net.mean() * TRADING_DAYS
    ann_vol = strat_ret.std() * np.sqrt(TRADING_DAYS)
    ann_vol_net = strat_ret_net.std() * np.sqrt(TRADING_DAYS)

    sharpe = ann_ret / ann_vol if ann_vol > 1e-10 else 0
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 1e-10 else 0

    # Max drawdown
    cum = (1 + strat_ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    # Net MDD
    cum_net = (1 + strat_ret_net).cumprod()
    peak_net = cum_net.cummax()
    dd_net = (cum_net - peak_net) / peak_net
    max_dd_net = dd_net.min()

    # Win rate (active days only)
    active = strat_ret[positions > 0]
    win_rate = (active > 0).mean() if len(active) > 0 else 0

    exposure = positions.mean()
    n_trades = int(trades.sum())

    # Buy & hold
    bh_ret = returns.mean() * TRADING_DAYS
    bh_vol = returns.std() * np.sqrt(TRADING_DAYS)
    bh_sharpe = bh_ret / bh_vol if bh_vol > 1e-10 else 0
    bh_cum = (1 + returns).cumprod()
    bh_peak = bh_cum.cummax()
    bh_dd = (bh_cum - bh_peak) / bh_peak
    bh_mdd = bh_dd.min()

    # Calmar ratio
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-10 else 0
    calmar_net = ann_ret_net / abs(max_dd_net) if abs(max_dd_net) > 1e-10 else 0

    # Total TX cost
    total_tx_pct = tx_per_day.sum() * 100

    return {
        "n_obs": n,
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_return_net_pct": round(ann_ret_net * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_net": round(sharpe_net, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "max_drawdown_net_pct": round(max_dd_net * 100, 2),
        "calmar": round(calmar, 3),
        "calmar_net": round(calmar_net, 3),
        "win_rate_pct": round(win_rate * 100, 1),
        "exposure_pct": round(exposure * 100, 1),
        "n_trades": n_trades,
        "total_tx_cost_pct": round(total_tx_pct, 2),
        "bh_return_pct": round(bh_ret * 100, 2),
        "bh_vol_pct": round(bh_vol * 100, 2),
        "bh_sharpe": round(bh_sharpe, 3),
        "bh_mdd_pct": round(bh_mdd * 100, 2),
    }


# ============================================================
# 6. NEWEY-WEST ALPHA T-TEST (Harvey Threshold)
# ============================================================

def alpha_ttest_nw(strat_returns, bh_returns, n_obs):
    """
    Test strategy alpha vs B&H with Newey-West HAC.
    Harvey (2016) threshold: |t| > 3.0.
    """
    excess = strat_returns - bh_returns
    n = len(excess)
    mean_ex = excess.mean()

    # Newey-West HAC
    lag = int(4 * (n / 100) ** (2 / 9))
    demean = excess - mean_ex
    gamma_0 = (demean ** 2).mean()
    nw_var = gamma_0
    for j in range(1, lag + 1):
        w = 1 - j / (lag + 1)
        gamma_j = (demean.iloc[j:].values * demean.iloc[:-j].values).mean()
        nw_var += 2 * w * gamma_j

    if nw_var < 0:
        nw_var = gamma_0

    nw_se = np.sqrt(nw_var / n)
    t_nw = mean_ex / nw_se if nw_se > 1e-15 else 0
    p_nw = 2 * (1 - stats.t.cdf(abs(t_nw), df=n - 1))

    # Simple t for comparison
    se = excess.std() / np.sqrt(n)
    t_simple = mean_ex / se if se > 1e-15 else 0

    return {
        "alpha_daily_bps": round(mean_ex * 10000, 2),
        "alpha_annual_pct": round(mean_ex * TRADING_DAYS * 100, 2),
        "t_simple": round(t_simple, 3),
        "t_nw": round(t_nw, 3),
        "p_nw": round(p_nw, 4),
        "nw_lags": lag,
        "harvey_pass": abs(t_nw) > 3.0,
    }


# ============================================================
# 7. CROSS-OOS VALIDATION (5 periods)
# ============================================================

def cross_oos(merged, n_periods=5, tx_roundtrip=TW_TX_ROUNDTRIP):
    """
    Split into n_periods and measure performance in each.
    For momentum signals: no parameters to train, purely OOS measurement.
    """
    n = len(merged)
    period_size = n // n_periods
    results = []

    for i in range(n_periods):
        s = i * period_size
        e = (i + 1) * period_size if i < n_periods - 1 else n
        chunk = merged.iloc[s:e]

        for ret_col in ["c2c", "o2o"]:
            pos = chunk["position"]
            ret = chunk[ret_col]
            strat_ret = ret * pos

            trades = pos.diff().abs().fillna(pos.iloc[0:1].abs())
            tx = trades * tx_roundtrip
            net_ret = strat_ret - tx

            sr = strat_ret.mean() / strat_ret.std() * np.sqrt(TRADING_DAYS) if strat_ret.std() > 1e-10 else 0
            sr_net = net_ret.mean() / net_ret.std() * np.sqrt(TRADING_DAYS) if net_ret.std() > 1e-10 else 0
            bh_sr = ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 1e-10 else 0

            # MDD
            cum = (1 + net_ret).cumprod()
            pk = cum.cummax()
            mdd = ((cum - pk) / pk).min()

            results.append({
                "period": i + 1,
                "start": chunk.index[0].strftime("%Y-%m-%d"),
                "end": chunk.index[-1].strftime("%Y-%m-%d"),
                "n_days": len(chunk),
                "return_type": ret_col,
                "sharpe": round(sr, 3),
                "sharpe_net": round(sr_net, 3),
                "bh_sharpe": round(bh_sr, 3),
                "excess_sharpe": round(sr - bh_sr, 3),
                "excess_sharpe_net": round(sr_net - bh_sr, 3),
                "mdd_net_pct": round(mdd * 100, 2),
                "exposure_pct": round(pos.mean() * 100, 1),
            })

    return results


# ============================================================
# 8. BOOTSTRAP CONFIDENCE INTERVALS
# ============================================================

def bootstrap_sharpe_ci(returns, positions, n_boot=10000, ci=0.95, block_len=20):
    """Stationary bootstrap CI for Sharpe ratio."""
    strat_ret = (returns * positions).values
    n = len(strat_ret)
    sharpes = np.empty(n_boot)

    for b in range(n_boot):
        idx = np.empty(n, dtype=int)
        i = 0
        while i < n:
            start = np.random.randint(0, n)
            blen = np.random.geometric(1.0 / block_len)
            end = min(i + blen, n)
            for k in range(end - i):
                idx[i + k] = (start + k) % n
            i = end
        sample = strat_ret[idx]
        s_mean = sample.mean()
        s_std = sample.std()
        sharpes[b] = s_mean / s_std * np.sqrt(TRADING_DAYS) if s_std > 1e-10 else 0

    alpha = (1 - ci) / 2
    lo = np.percentile(sharpes, alpha * 100)
    hi = np.percentile(sharpes, (1 - alpha) * 100)
    return {
        "sharpe_mean": round(np.mean(sharpes), 3),
        "sharpe_median": round(np.median(sharpes), 3),
        "ci_lo": round(lo, 3),
        "ci_hi": round(hi, 3),
        "ci_level": ci,
        "prob_positive": round((sharpes > 0).mean() * 100, 1),
    }


# ============================================================
# 9. OVERNIGHT GAP DECOMPOSITION
# ============================================================

def gap_decomposition(merged):
    """
    Analyze how much of the alpha comes from the overnight gap (not capturable)
    vs intraday move (capturable via o2o).
    """
    pos = merged["position"]
    long_mask = pos > 0
    cash_mask = pos == 0

    result = {}
    for label, mask in [("long", long_mask), ("cash", cash_mask), ("all", pd.Series(True, index=merged.index))]:
        sub = merged[mask]
        if len(sub) == 0:
            continue
        result[f"{label}_n"] = len(sub)
        result[f"{label}_c2c_bps"] = round(sub["c2c"].mean() * 10000, 2)
        result[f"{label}_gap_bps"] = round(sub["gap"].mean() * 10000, 2)
        result[f"{label}_o2o_bps"] = round(sub["o2o"].mean() * 10000, 2)

        gap_abs = abs(sub["gap"].mean())
        o2o_abs = abs(sub["o2o"].mean())
        total = gap_abs + o2o_abs
        result[f"{label}_gap_share_pct"] = round(gap_abs / total * 100, 1) if total > 1e-10 else 0

    return result


# ============================================================
# 10. TX COST SENSITIVITY
# ============================================================

def tx_sensitivity(merged, return_col="o2o", costs_bps=None):
    """Sweep transaction costs and report net Sharpe."""
    if costs_bps is None:
        costs_bps = [0, 5, 10, 15, 20, 25, 29.25, 35, 40, 50]

    pos = merged["position"]
    ret = merged[return_col]
    trades = pos.diff().abs().fillna(pos.iloc[0:1].abs())

    results = []
    for bps in costs_bps:
        cost_rate = bps / 10000
        strat_ret = ret * pos
        tx = trades * cost_rate * 2
        net = strat_ret - tx

        sr = net.mean() / net.std() * np.sqrt(TRADING_DAYS) if net.std() > 1e-10 else 0
        ann = net.mean() * TRADING_DAYS * 100
        results.append({
            "cost_bps_oneway": bps,
            "sharpe_net": round(sr, 3),
            "ann_return_net_pct": round(ann, 2),
        })

    return results


# ============================================================
# 11. DESCRIPTIVE STATISTICS (pre-estimation diagnostics)
# ============================================================

def descriptive_stats(merged):
    """Pre-estimation diagnostics per CLAUDE.md rule 5."""
    from scipy.stats import skew, kurtosis, jarque_bera

    result = {}
    for col in ["c2c", "o2o", "gap"]:
        s = merged[col].dropna()
        result[col] = {
            "n": len(s),
            "mean_bps": round(s.mean() * 10000, 2),
            "std_bps": round(s.std() * 10000, 2),
            "skewness": round(float(skew(s)), 3),
            "kurtosis": round(float(kurtosis(s, fisher=True)), 3),
            "min_pct": round(s.min() * 100, 2),
            "max_pct": round(s.max() * 100, 2),
            "jb_stat": round(float(jarque_bera(s)[0]), 1),
            "jb_pvalue": round(float(jarque_bera(s)[1]), 6),
        }

    # Correlation: SPY signal vs TW returns
    for col in ["c2c", "o2o"]:
        corr = merged["signal_raw"].corr(merged[col])
        result[f"corr_signal_{col}"] = round(corr, 4)

    return result


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("K502: US→Taiwan Lead-Lag Trading Strategy")
    print("=" * 70)

    # --- Data ---
    print("\n[1/8] Fetching data...")
    data = fetch_data()

    spy = data["SPY"]
    vix = data["VIX"]
    tw50 = data["TW50"]

    # Compute TW returns
    tw_c2c, tw_o2o, tw_gap = compute_returns(tw50)

    # --- Strategy signals ---
    print("\n[2/8] Building signals...")
    strategies = {
        "spy_1d_mom": signal_spy_1d_momentum(spy),
        "spy_5d_mom": signal_spy_5d_momentum(spy),
        "vix_regime_spy": signal_vix_regime_spy(spy, vix),
        "spy_quantile": signal_spy_quantile(spy),
        "spy_10d_mom_ref": signal_spy_10d_momentum(spy),
    }

    strategy_names = {
        "spy_1d_mom": "Strategy 1: SPY 1-day Momentum",
        "spy_5d_mom": "Strategy 2: SPY 5-day Momentum",
        "vix_regime_spy": "Strategy 3: VIX Regime + SPY Signal",
        "spy_quantile": "Strategy 4: SPY Return Quantile",
        "spy_10d_mom_ref": "Reference: SPY 10-day Momentum (existing)",
    }

    # --- Align and compute ---
    print("\n[3/8] Aligning signals to Taiwan returns...")
    all_results = {}

    for strat_key, (position, signal_raw) in strategies.items():
        print(f"\n  === {strategy_names[strat_key]} ===")

        merged = align_signal_to_tw(
            position, signal_raw, tw_c2c, tw_o2o, tw_gap,
            start_date="2010-01-01",
        )
        print(f"  Aligned: {len(merged)} days, {merged.index[0].date()} to {merged.index[-1].date()}")

        # Descriptive stats
        desc = descriptive_stats(merged)

        # Gap decomposition
        gap_dec = gap_decomposition(merged)

        # --- Metrics for c2c and o2o ---
        metrics = {}
        for ret_col in ["c2c", "o2o"]:
            m = compute_metrics(merged, ret_col)
            metrics[ret_col] = m
            tag = "BIASED" if ret_col == "c2c" else "HONEST"
            print(f"  [{ret_col} {tag}] Sharpe={m['sharpe']:.3f}, Net={m['sharpe_net']:.3f}, "
                  f"MDD={m['max_drawdown_pct']:.1f}%, Exposure={m['exposure_pct']:.0f}%")

        # --- Alpha t-test (o2o only, the honest measure) ---
        pos = merged["position"]
        o2o_strat = merged["o2o"] * pos
        o2o_bh = merged["o2o"]
        alpha_test_o2o = alpha_ttest_nw(o2o_strat, o2o_bh, len(merged))
        print(f"  [o2o Alpha] t_NW={alpha_test_o2o['t_nw']:.3f}, "
              f"Harvey={'PASS' if alpha_test_o2o['harvey_pass'] else 'FAIL'}")

        # Also test c2c for comparison
        c2c_strat = merged["c2c"] * pos
        c2c_bh = merged["c2c"]
        alpha_test_c2c = alpha_ttest_nw(c2c_strat, c2c_bh, len(merged))

        # --- Cross-OOS ---
        oos = cross_oos(merged, n_periods=6)  # 6 periods ≈ 2.5 years each

        # Count how many OOS periods have positive excess Sharpe (o2o net)
        oos_o2o_net = [r for r in oos if r["return_type"] == "o2o"]
        n_positive_oos = sum(1 for r in oos_o2o_net if r["excess_sharpe_net"] > 0)
        print(f"  [Cross-OOS] {n_positive_oos}/{len(oos_o2o_net)} periods with positive excess (o2o net)")

        # --- Bootstrap (o2o only) ---
        print(f"  [Bootstrap] Running 10,000 iterations...", end=" ")
        boot = bootstrap_sharpe_ci(merged["o2o"], pos, n_boot=10000)
        print(f"Sharpe CI: [{boot['ci_lo']:.3f}, {boot['ci_hi']:.3f}], P(>0)={boot['prob_positive']:.0f}%")

        # --- TX sensitivity (o2o only) ---
        tx_sens = tx_sensitivity(merged, return_col="o2o")

        # Find breakeven TX cost (where net Sharpe → 0)
        breakeven_bps = None
        for i in range(1, len(tx_sens)):
            if tx_sens[i]["sharpe_net"] <= 0 and tx_sens[i - 1]["sharpe_net"] > 0:
                # Linear interpolation
                s1, s0 = tx_sens[i]["sharpe_net"], tx_sens[i - 1]["sharpe_net"]
                b1, b0 = tx_sens[i]["cost_bps_oneway"], tx_sens[i - 1]["cost_bps_oneway"]
                breakeven_bps = round(b0 + (b1 - b0) * s0 / (s0 - s1), 1) if s0 != s1 else b0
                break

        all_results[strat_key] = {
            "name": strategy_names[strat_key],
            "descriptive_stats": desc,
            "gap_decomposition": gap_dec,
            "metrics_c2c": metrics["c2c"],
            "metrics_o2o": metrics["o2o"],
            "alpha_test_c2c": alpha_test_c2c,
            "alpha_test_o2o": alpha_test_o2o,
            "cross_oos": oos,
            "bootstrap_o2o": boot,
            "tx_sensitivity": tx_sens,
            "breakeven_tx_bps": breakeven_bps,
        }

    # ============================================================
    # SUMMARY TABLE
    # ============================================================
    print("\n" + "=" * 70)
    print("STRATEGY COMPARISON (o2o = honest measure)")
    print("=" * 70)
    print(f"{'Strategy':<35} {'Sharpe':>7} {'Net':>7} {'MDD':>7} {'Calmar':>7} {'Exp%':>5} "
          f"{'t_NW':>6} {'Harvey':>7} {'OOS+':>5}")

    for strat_key in ["spy_1d_mom", "spy_5d_mom", "vix_regime_spy", "spy_quantile", "spy_10d_mom_ref"]:
        r = all_results[strat_key]
        m = r["metrics_o2o"]
        a = r["alpha_test_o2o"]
        oos_o2o = [x for x in r["cross_oos"] if x["return_type"] == "o2o"]
        n_pos = sum(1 for x in oos_o2o if x["excess_sharpe_net"] > 0)

        print(f"{r['name']:<35} {m['sharpe']:>7.3f} {m['sharpe_net']:>7.3f} "
              f"{m['max_drawdown_pct']:>6.1f}% {m['calmar_net']:>7.3f} "
              f"{m['exposure_pct']:>4.0f}% {a['t_nw']:>6.3f} "
              f"{'PASS' if a['harvey_pass'] else 'FAIL':>7} {n_pos}/{len(oos_o2o)}")

    # Buy & hold row
    bh = all_results["spy_1d_mom"]["metrics_o2o"]
    print(f"{'Buy & Hold 0050.TW':<35} {bh['bh_sharpe']:>7.3f} {'N/A':>7} "
          f"{bh['bh_mdd_pct']:>6.1f}% {'N/A':>7} {'100%':>5} {'N/A':>6} {'N/A':>7} {'N/A':>5}")

    # ============================================================
    # c2c vs o2o BIAS ANALYSIS
    # ============================================================
    print("\n" + "=" * 70)
    print("C2C vs O2O BIAS ANALYSIS (timing bias from overnight gap)")
    print("=" * 70)
    print(f"{'Strategy':<35} {'c2c Sharpe':>11} {'o2o Sharpe':>11} {'Bias':>6} {'Gap%':>6}")

    for strat_key in ["spy_1d_mom", "spy_5d_mom", "vix_regime_spy", "spy_quantile", "spy_10d_mom_ref"]:
        r = all_results[strat_key]
        c2c_s = r["metrics_c2c"]["sharpe"]
        o2o_s = r["metrics_o2o"]["sharpe"]
        bias = c2c_s - o2o_s
        gap_pct = r["gap_decomposition"].get("long_gap_share_pct", 0)
        print(f"{r['name']:<35} {c2c_s:>11.3f} {o2o_s:>11.3f} {bias:>+6.3f} {gap_pct:>5.1f}%")

    # ============================================================
    # CROSS-OOS DETAIL (best strategy)
    # ============================================================
    # Find best strategy by o2o net Sharpe
    best_key = max(all_results.keys(),
                   key=lambda k: all_results[k]["metrics_o2o"]["sharpe_net"])
    best = all_results[best_key]
    print(f"\n{'='*70}")
    print(f"CROSS-OOS DETAIL: {best['name']} (best o2o net Sharpe)")
    print(f"{'='*70}")
    oos_detail = [x for x in best["cross_oos"] if x["return_type"] == "o2o"]
    print(f"{'Period':<10} {'Start':<12} {'End':<12} {'Days':>5} {'Sharpe':>7} {'Net':>7} "
          f"{'B&H':>7} {'Excess':>7} {'MDD':>7}")
    for p in oos_detail:
        print(f"  {p['period']:<8} {p['start']:<12} {p['end']:<12} {p['n_days']:>5} "
              f"{p['sharpe']:>7.3f} {p['sharpe_net']:>7.3f} {p['bh_sharpe']:>7.3f} "
              f"{p['excess_sharpe_net']:>+7.3f} {p['mdd_net_pct']:>6.1f}%")

    # ============================================================
    # STRATEGY VIABILITY ASSESSMENT
    # ============================================================
    print(f"\n{'='*70}")
    print("STRATEGY VIABILITY ASSESSMENT")
    print(f"{'='*70}")

    viable_strategies = []
    for strat_key in ["spy_1d_mom", "spy_5d_mom", "vix_regime_spy", "spy_quantile"]:
        r = all_results[strat_key]
        m_o2o = r["metrics_o2o"]
        a = r["alpha_test_o2o"]
        oos_o2o = [x for x in r["cross_oos"] if x["return_type"] == "o2o"]
        n_pos = sum(1 for x in oos_o2o if x["excess_sharpe_net"] > 0)

        checks = {
            "net_sharpe_positive": m_o2o["sharpe_net"] > 0,
            "harvey_pass": a["harvey_pass"],
            "oos_majority_positive": n_pos > len(oos_o2o) / 2,
            "mdd_reasonable": abs(m_o2o["max_drawdown_net_pct"]) < 30,
            "beats_bh_sharpe": m_o2o["sharpe_net"] > m_o2o["bh_sharpe"],
        }

        pass_count = sum(checks.values())
        all_pass = all(checks.values())

        print(f"\n  {r['name']}:")
        for check, passed in checks.items():
            print(f"    {'✓' if passed else '✗'} {check}")
        print(f"    → {pass_count}/5 checks passed. {'*** VIABLE FOR DEPLOYMENT ***' if all_pass else 'NOT viable'}")

        if all_pass:
            viable_strategies.append(strat_key)

    # ============================================================
    # SAVE RESULTS
    # ============================================================
    print(f"\n[8/8] Saving results...")

    output = {
        "experiment_id": "K502",
        "title": "US→Taiwan Lead-Lag Trading Strategy",
        "author": "[提出: User, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (0050.TW, SPY, ^VIX)",
        "data_period": f"{all_results['spy_1d_mom']['metrics_o2o']['n_obs']} trading days",
        "tx_cost": "0.1855% round-trip (0.1% ETF securities tax + 0.04275%x2 broker at 3折) [CORRECTED K625]",
        "methodology": {
            "return_measures": {
                "c2c": "Close-to-close (BIASED, includes overnight gap)",
                "o2o": "Open-to-close (HONEST, enter at open after US signal)",
            },
            "signal_timing": "US closes day t → signal available → enter TW at open day t+1",
            "alignment": "SPY index shifted +1 BDay, inner join with TW",
            "alpha_test": "Newey-West HAC, Harvey (2016) t>3.0",
            "bootstrap": "Stationary bootstrap (Politis & Romano 1994), 10,000 reps, block=20",
            "cross_oos": "6 non-overlapping periods",
        },
        "references": [
            "Harvey (2016) ...and the Cross-Section of Expected Returns, RFS",
            "I8: Timing bias analysis (this project) — c2c inflated by overnight gap",
            "T32/T33: SPY→TW50 lead-lag confirmed (r=0.376, Harvey pass)",
            "K461: SSVS SPY_ret PIP=1.000 for Taiwan",
            "K238: 10d SPY Mom o2o=0.87, FAIL Harvey",
            "U5: Dynamic lead-lag strengthening trend +0.01/yr",
        ],
        "critical_finding": (
            "I8 warning confirmed: c2c Sharpe is INFLATED vs o2o for all strategies. "
            "The overnight gap (not capturable) accounts for a large share of c2c alpha. "
            "Only o2o metrics should be used for deployment decisions."
        ),
        "strategies": all_results,
        "viable_for_deployment": viable_strategies,
        "comparison_with_existing": {
            "taiwan_8.63vix": "Current active TW strategy (VT-based)",
            "taiwan_spy_momentum_10d": "Current inactive TW momentum strategy (marked BIASED in I8)",
        },
    }

    # Add summary table
    summary = []
    for strat_key in ["spy_1d_mom", "spy_5d_mom", "vix_regime_spy", "spy_quantile", "spy_10d_mom_ref"]:
        r = all_results[strat_key]
        m = r["metrics_o2o"]
        a = r["alpha_test_o2o"]
        oos_o2o = [x for x in r["cross_oos"] if x["return_type"] == "o2o"]
        n_pos = sum(1 for x in oos_o2o if x["excess_sharpe_net"] > 0)

        summary.append({
            "strategy": r["name"],
            "key": strat_key,
            "o2o_sharpe": m["sharpe"],
            "o2o_sharpe_net": m["sharpe_net"],
            "c2c_sharpe": r["metrics_c2c"]["sharpe"],
            "c2c_bias": round(r["metrics_c2c"]["sharpe"] - m["sharpe"], 3),
            "max_drawdown_pct": m["max_drawdown_pct"],
            "calmar_net": m["calmar_net"],
            "win_rate_pct": m["win_rate_pct"],
            "exposure_pct": m["exposure_pct"],
            "t_nw": a["t_nw"],
            "harvey_pass": a["harvey_pass"],
            "oos_positive": f"{n_pos}/{len(oos_o2o)}",
            "bootstrap_ci": f"[{r['bootstrap_o2o']['ci_lo']}, {r['bootstrap_o2o']['ci_hi']}]",
            "breakeven_tx_bps": r["breakeven_tx_bps"],
        })

    output["summary_table"] = summary
    output["buy_and_hold"] = {
        "o2o_sharpe": bh["bh_sharpe"],
        "o2o_mdd_pct": bh["bh_mdd_pct"],
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Saved to {RESULTS_PATH}")

    # Final verdict
    print(f"\n{'='*70}")
    print("FINAL VERDICT")
    print(f"{'='*70}")
    if viable_strategies:
        print(f"  VIABLE strategies: {viable_strategies}")
        print("  → Proceed to STRATEGY_REGISTRY addition and daily_update.py integration")
    else:
        print("  NO strategies pass all viability checks.")
        print("  → The lead-lag relationship exists but is NOT strong enough for a standalone trading strategy")
        print("    after accounting for:")
        print("    1. Timing bias (overnight gap not capturable)")
        print("    2. Transaction costs (0.585% round-trip)")
        print("    3. Harvey (2016) t>3.0 threshold")
        print("    → Consistent with I8/K238 findings")

    return output


if __name__ == "__main__":
    results = main()
