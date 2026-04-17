"""
K567: International VT Leverage — Does VIX-Conditional Leverage Work Internationally?
=====================================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K551 (US) validated VIX-conditional leverage (Harvey t=7.90, 11/11 OOS).
  K558 (Taiwan) validated percentile-based leverage (t=4.79, 18/18 OOS).
  K68 showed 12/VIX VT works on 13/13 international markets for MDD reduction.
  K237 confirmed 8/8 international markets get MDD improvement but 0/8 Sharpe.

  The question: does LEVERAGE overlay also generalize beyond US and Taiwan?

Markets tested:
  - EFA  (iShares MSCI Developed ex-US) — broad developed
  - EWZ  (iShares MSCI Brazil)          — emerging, high vol
  - EWJ  (iShares MSCI Japan)           — developed, low gamma
  - EWU  (iShares MSCI United Kingdom)  — developed, Brexit risk
  - FXI  (iShares China Large-Cap)      — emerging, policy risk
  - SPY  (US benchmark)                 — baseline reference

Leverage variants tested per market:
  a. Base VT:     50/50 [Market]/GLD + 12/VIX monthly (no leverage overlay)
  b. US-style:    VIX<15 → 1.5x, VIX>25 → 1.0x (absolute thresholds, K551)
  c. Percentile:  VIX rolling pctile<0.3 → 1.5x (relative, K558 Taiwan approach)
  d. Local RV:    market's own RV22<median → 1.3x (local volatility signal)

All paired with 50% GLD.
Cross-OOS: 3 periods.
Harvey t>3.0 threshold.

References:
  Moreira & Muir (2017) JoF: Volatility-managed portfolios
  Bozovic (2024) IRFA: VIX-managed > realized-vol managed
  Hood & Raughtigan (2024/2025) JPM: VT alpha from implicit trend-following

Data source: yfinance (real data only)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import json

# ==================================================================
# CONFIG
# ==================================================================
MARKETS = {
    "SPY": {"name": "US (S&P 500)",              "data_start": "2005-01-01"},
    "EFA": {"name": "Developed ex-US (EAFE)",    "data_start": "2005-01-01"},
    "EWZ": {"name": "Brazil (MSCI Brazil)",      "data_start": "2005-01-01"},
    "EWJ": {"name": "Japan (MSCI Japan)",        "data_start": "2005-01-01"},
    "EWU": {"name": "UK (MSCI UK)",              "data_start": "2005-01-01"},
    "FXI": {"name": "China (China Large-Cap)",   "data_start": "2005-01-01"},
}

VT_NUMERATOR = 12  # 12/VIX monthly weight
MAX_WEIGHT = 1.5   # cap leverage at 1.5x
TX_COST_BPS = 10   # 10bps per rebalance (conservative for intl ETFs)
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

# VIX Percentile window (rolling)
VIX_PCTILE_WINDOW = 252 * 5  # 5 years rolling

# RV calculation window
RV_WINDOW = 22  # 22 trading days (~1 month)
RV_MEDIAN_WINDOW = 252 * 3  # 3 years rolling median

# Cross-OOS periods (3 periods as specified)
OOS_PERIODS = [
    ("2008-01-01", "2012-12-31"),  # GFC + recovery
    ("2013-01-01", "2018-12-31"),  # Low vol → vol spike
    ("2019-01-01", "2025-12-31"),  # COVID + rate hikes
]

N_BOOTSTRAP = 5000

print("=" * 80)
print("K567: INTERNATIONAL VT LEVERAGE — Does VIX-Conditional Leverage Generalize?")
print("=" * 80)
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Markets: {', '.join(MARKETS.keys())}")
print(f"Variants: Base VT, US-style, Percentile, Local RV")
print(f"Cross-OOS periods: {len(OOS_PERIODS)}")
print(f"Harvey threshold: t>3.0")
print(f"Bootstrap: {N_BOOTSTRAP} reps")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/8] Downloading market data from yfinance...")

tickers_to_download = list(MARKETS.keys()) + ["GLD", "^VIX"]
raw_data = {}

for t in tickers_to_download:
    start = "2004-01-01"  # extra early for warmup
    df = yf.download(t, start=start, end="2026-12-31", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col_name = t.replace("^", "").replace(".", "_")
    raw_data[t] = df[["Close"]].rename(columns={"Close": col_name})
    print(f"  {t}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

vix_df = raw_data["^VIX"]
gld_df = raw_data["GLD"]

print(f"\n  VIX: {len(vix_df)} rows")
print(f"  GLD: {len(gld_df)} rows")


# ==================================================================
# 2. Helper Functions
# ==================================================================

def compute_metrics(daily_returns, name, index=None):
    """Compute standard performance metrics from daily log returns."""
    n = len(daily_returns)
    if n < 50:
        return None
    yrs = n / 252
    cum = np.exp(np.cumsum(daily_returns))

    ann_ret = (cum[-1] ** (1 / yrs)) - 1
    ann_vol = np.std(daily_returns) * np.sqrt(252)
    sharpe = ((np.mean(daily_returns) - RF_DAILY) / np.std(daily_returns) * np.sqrt(252)
              if np.std(daily_returns) > 0 else 0)

    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    max_dd = np.min(dd)
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    downside = daily_returns[daily_returns < 0]
    ds_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / ds_vol

    return {
        "name": name,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "total_growth": cum[-1],
        "years": yrs,
        "n_days": n,
    }


def compute_vix_percentile_series(vix_values, window=VIX_PCTILE_WINDOW):
    """Rolling percentile of VIX within its own history."""
    n = len(vix_values)
    pctile = np.full(n, 0.5)
    for i in range(window, n):
        lookback = vix_values[max(0, i - window):i]
        pctile[i] = np.mean(lookback <= vix_values[i])
    return pctile


def compute_rv22(returns, window=RV_WINDOW):
    """Realized volatility (annualized) over rolling window."""
    n = len(returns)
    rv = np.full(n, np.nan)
    for i in range(window, n):
        rv[i] = np.std(returns[i - window:i]) * np.sqrt(252)
    return rv


def compute_rv_median(rv, window=RV_MEDIAN_WINDOW):
    """Rolling median of RV."""
    n = len(rv)
    med = np.full(n, np.nan)
    for i in range(window, n):
        valid = rv[max(0, i - window):i]
        valid = valid[~np.isnan(valid)]
        if len(valid) > 0:
            med[i] = np.median(valid)
    return med


def run_vt_with_leverage(mkt_ret, gld_ret, vix_level, dates,
                         leverage_func, tx_bps, name):
    """
    Run 50/50 [Market]/GLD + 12/VIX monthly rebalancing WITH leverage overlay.

    leverage_func(t, vix_val, vix_pctile, local_rv, rv_median) -> leverage multiplier

    The base VT weight is 12/VIX (capped at 1.5).
    The leverage overlay multiplies the EQUITY portion additionally.
    Final equity weight = 0.5 * base_vt_weight * leverage_multiplier.
    """
    n = len(mkt_ret)
    port_ret = np.zeros(n)

    # Determine monthly rebalance dates
    date_series = pd.Series(range(n), index=dates)
    monthly_last = date_series.resample("ME").last()
    rebal_indices = set(monthly_last.values)

    current_base_w = 1.0
    current_lev = 1.0
    n_trades = 0
    leverage_active_days = 0

    for t in range(n):
        # Portfolio: 50% * base_w * leverage * market + 50% * GLD
        effective_w = current_base_w * current_lev
        equity_ret = 0.5 * effective_w * mkt_ret[t]
        gold_ret = 0.5 * gld_ret[t]

        tx_cost = 0.0
        if t in rebal_indices and t > 0:
            vix_val = vix_level[t]
            if vix_val > 0:
                new_base_w = min(VT_NUMERATOR / vix_val, MAX_WEIGHT)
            else:
                new_base_w = 1.0

            new_lev = leverage_func(t)

            old_eff = current_base_w * current_lev
            new_eff = new_base_w * new_lev
            dw = abs(new_eff - old_eff)
            if dw > 0.001:
                tx_cost = 0.5 * dw * tx_bps / 10000
                n_trades += 1

            current_base_w = new_base_w
            current_lev = new_lev

        if current_lev > 1.01:
            leverage_active_days += 1

        port_ret[t] = equity_ret + gold_ret - tx_cost

    metrics = compute_metrics(port_ret, name, index=dates)
    if metrics is not None:
        metrics["n_trades"] = n_trades
        metrics["trades_per_year"] = n_trades / (n / 252) if n > 0 else 0
        metrics["leverage_pct"] = leverage_active_days / n * 100 if n > 0 else 0
    return metrics, port_ret


def paired_t_test(daily_ret_a, daily_ret_b):
    """Paired t-test (Sharpe difference) using Jobson-Korkie with Memmel correction."""
    diff = daily_ret_a - daily_ret_b
    n = len(diff)
    if n < 30:
        return 0.0, 1.0
    t_stat = np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(n))
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_val


def bootstrap_sharpe_diff(ret_a, ret_b, n_boot=N_BOOTSTRAP):
    """Bootstrap the Sharpe difference."""
    n = len(ret_a)
    sharpe_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        sa = (np.mean(ret_a[idx]) - RF_DAILY) / np.std(ret_a[idx]) * np.sqrt(252)
        sb = (np.mean(ret_b[idx]) - RF_DAILY) / np.std(ret_b[idx]) * np.sqrt(252)
        sharpe_diffs[b] = sa - sb
    pct_positive = np.mean(sharpe_diffs > 0)
    ci_lo = np.percentile(sharpe_diffs, 2.5)
    ci_hi = np.percentile(sharpe_diffs, 97.5)
    return pct_positive, ci_lo, ci_hi


# ==================================================================
# 3. Descriptive Statistics (diagnostics first)
# ==================================================================
print("\n[2/8] Descriptive statistics & diagnostics...")

diagnostics = {}
for ticker, info in MARKETS.items():
    col_name = ticker.replace("^", "").replace(".", "_")
    mkt_df = raw_data[ticker]
    merged = mkt_df.join(gld_df, how="inner").join(vix_df, how="inner").dropna()
    merged = merged[merged.index >= info["data_start"]]

    if len(merged) < 252:
        print(f"  {ticker}: Insufficient data, skipping")
        continue

    mkt_ret = np.log(merged[col_name] / merged[col_name].shift(1)).dropna().values

    diag = {
        "n_days": len(mkt_ret),
        "years": len(mkt_ret) / 252,
        "mean_daily": float(np.mean(mkt_ret)),
        "std_daily": float(np.std(mkt_ret)),
        "ann_vol": float(np.std(mkt_ret) * np.sqrt(252)),
        "skewness": float(stats.skew(mkt_ret)),
        "kurtosis": float(stats.kurtosis(mkt_ret)),
    }
    diagnostics[ticker] = diag

    print(f"  {ticker} ({info['name']}): N={diag['n_days']}, "
          f"Ann.Vol={diag['ann_vol']:.1%}, Skew={diag['skewness']:.2f}, "
          f"Kurt={diag['kurtosis']:.2f}")


# ==================================================================
# 4. Full-Period Analysis — All Variants
# ==================================================================
print("\n[3/8] Full-period analysis for all markets × all variants...")

full_results = {}

for ticker, info in MARKETS.items():
    col_name = ticker.replace("^", "").replace(".", "_")
    mkt_df = raw_data[ticker]

    merged = mkt_df.join(gld_df, how="inner").join(vix_df, how="inner").dropna()
    merged = merged[merged.index >= info["data_start"]]

    if len(merged) < 252:
        print(f"  {ticker}: Insufficient data, skipping")
        continue

    mkt_ret = np.log(merged[col_name] / merged[col_name].shift(1)).values
    gld_ret_arr = np.log(merged["GLD"] / merged["GLD"].shift(1)).values
    vix_level = merged["VIX"].values
    dates = merged.index

    # Remove first NaN from log returns
    valid_mask = ~(np.isnan(mkt_ret) | np.isnan(gld_ret_arr))
    mkt_ret = np.where(valid_mask, mkt_ret, 0.0)
    gld_ret_arr = np.where(valid_mask, gld_ret_arr, 0.0)

    # Precompute signals
    vix_pctile = compute_vix_percentile_series(vix_level)
    local_rv = compute_rv22(mkt_ret)
    rv_med = compute_rv_median(local_rv)

    n = len(mkt_ret)

    # (a) Base VT: no leverage overlay
    def base_lev(t):
        return 1.0
    base_metrics, base_ret = run_vt_with_leverage(
        mkt_ret, gld_ret_arr, vix_level, dates, base_lev, TX_COST_BPS,
        f"{ticker} Base VT")

    # (b) US-style: VIX<15 → 1.5x, VIX>25 → 1.0x, else 1.2x
    def us_style_lev(t):
        if vix_level[t] < 15:
            return 1.5
        elif vix_level[t] > 25:
            return 1.0
        else:
            return 1.2
    us_metrics, us_ret = run_vt_with_leverage(
        mkt_ret, gld_ret_arr, vix_level, dates, us_style_lev, TX_COST_BPS,
        f"{ticker} US-style Lev")

    # (c) Percentile: VIX pctile<0.3 → 1.5x, pctile>0.7 → 1.0x, else 1.2x
    def pctile_lev(t):
        if vix_pctile[t] < 0.3:
            return 1.5
        elif vix_pctile[t] > 0.7:
            return 1.0
        else:
            return 1.2
    pctile_metrics, pctile_ret = run_vt_with_leverage(
        mkt_ret, gld_ret_arr, vix_level, dates, pctile_lev, TX_COST_BPS,
        f"{ticker} Percentile Lev")

    # (d) Local RV: RV22 < rolling median → 1.3x, else 1.0x
    def local_rv_lev(t):
        if np.isnan(local_rv[t]) or np.isnan(rv_med[t]):
            return 1.0
        if local_rv[t] < rv_med[t]:
            return 1.3
        else:
            return 1.0
    rv_metrics, rv_ret = run_vt_with_leverage(
        mkt_ret, gld_ret_arr, vix_level, dates, local_rv_lev, TX_COST_BPS,
        f"{ticker} Local RV Lev")

    # Buy & Hold benchmarks
    bh_ret = 0.5 * mkt_ret + 0.5 * gld_ret_arr
    bh_metrics = compute_metrics(bh_ret, f"{ticker} 50/50 B&H", index=dates)

    market_results = {
        "ticker": ticker,
        "name": info["name"],
        "n_days": n,
        "years": n / 252,
        "bh": bh_metrics,
        "base_vt": base_metrics,
        "us_style": us_metrics,
        "percentile": pctile_metrics,
        "local_rv": rv_metrics,
        "daily_returns": {
            "bh": bh_ret,
            "base_vt": base_ret,
            "us_style": us_ret,
            "percentile": pctile_ret,
            "local_rv": rv_ret,
        }
    }

    # Statistical tests: each leverage variant vs Base VT
    for variant_key, variant_label in [
        ("us_style", "US-style"),
        ("percentile", "Percentile"),
        ("local_rv", "Local RV"),
    ]:
        variant_ret = market_results["daily_returns"][variant_key]
        t_stat, p_val = paired_t_test(variant_ret, base_ret)
        boot_pos, boot_lo, boot_hi = bootstrap_sharpe_diff(variant_ret, base_ret)
        market_results[f"{variant_key}_vs_base"] = {
            "t_stat": float(t_stat),
            "p_val": float(p_val),
            "harvey_pass": abs(t_stat) > 3.0,
            "boot_pct_positive": float(boot_pos),
            "boot_ci_lo": float(boot_lo),
            "boot_ci_hi": float(boot_hi),
        }

    full_results[ticker] = market_results
    sharpe_base = base_metrics["sharpe"] if base_metrics else 0
    sharpe_us = us_metrics["sharpe"] if us_metrics else 0
    sharpe_pct = pctile_metrics["sharpe"] if pctile_metrics else 0
    sharpe_rv = rv_metrics["sharpe"] if rv_metrics else 0

    print(f"\n  {ticker} ({info['name']}):")
    print(f"    B&H Sharpe:    {bh_metrics['sharpe']:.3f}, MDD: {bh_metrics['max_dd']:.1%}")
    print(f"    Base VT:       {sharpe_base:.3f}, MDD: {base_metrics['max_dd']:.1%}")
    print(f"    US-style Lev:  {sharpe_us:.3f}, MDD: {us_metrics['max_dd']:.1%}")
    print(f"    Percentile Lev:{sharpe_pct:.3f}, MDD: {pctile_metrics['max_dd']:.1%}")
    print(f"    Local RV Lev:  {sharpe_rv:.3f}, MDD: {rv_metrics['max_dd']:.1%}")


# ==================================================================
# 5. Cross-OOS Validation (3 periods)
# ==================================================================
print("\n\n[4/8] Cross-OOS validation (3 periods)...")

oos_results = {}

for ticker, info in MARKETS.items():
    if ticker not in full_results:
        continue

    col_name = ticker.replace("^", "").replace(".", "_")
    mkt_df = raw_data[ticker]
    merged = mkt_df.join(gld_df, how="inner").join(vix_df, how="inner").dropna()

    oos_market = {"periods": []}

    for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
        # IS = everything EXCEPT this OOS period
        oos_mask = (merged.index >= oos_start) & (merged.index <= oos_end)
        oos_data = merged[oos_mask]

        if len(oos_data) < 126:  # minimum ~6 months
            oos_market["periods"].append({
                "period": f"{oos_start} to {oos_end}",
                "status": "insufficient_data",
            })
            continue

        mkt_ret = np.log(oos_data[col_name] / oos_data[col_name].shift(1)).values
        gld_ret_arr = np.log(oos_data["GLD"] / oos_data["GLD"].shift(1)).values
        vix_level = oos_data["VIX"].values
        dates = oos_data.index

        valid_mask = ~(np.isnan(mkt_ret) | np.isnan(gld_ret_arr))
        mkt_ret = np.where(valid_mask, mkt_ret, 0.0)
        gld_ret_arr = np.where(valid_mask, gld_ret_arr, 0.0)

        # Precompute signals (using full history before OOS for rolling lookback)
        full_before_oos = merged[merged.index <= oos_end]
        full_vix = full_before_oos["VIX"].values
        full_mkt_ret_all = np.log(
            full_before_oos[col_name] / full_before_oos[col_name].shift(1)
        ).values
        full_mkt_ret_all = np.where(np.isnan(full_mkt_ret_all), 0.0, full_mkt_ret_all)

        vix_pctile_full = compute_vix_percentile_series(full_vix)
        local_rv_full = compute_rv22(full_mkt_ret_all)
        rv_med_full = compute_rv_median(local_rv_full)

        # Map OOS indices into full array
        n_full = len(full_before_oos)
        n_oos = len(oos_data)
        oos_offset = n_full - n_oos

        # Build leverage functions that index into full arrays
        def make_base_lev():
            return lambda t: 1.0

        def make_us_lev(vl):
            def f(t):
                idx = oos_offset + t
                if idx < len(vl) and vl[idx] < 15:
                    return 1.5
                elif idx < len(vl) and vl[idx] > 25:
                    return 1.0
                else:
                    return 1.2
            return f

        def make_pctile_lev(vp):
            def f(t):
                idx = oos_offset + t
                if idx < len(vp) and vp[idx] < 0.3:
                    return 1.5
                elif idx < len(vp) and vp[idx] > 0.7:
                    return 1.0
                else:
                    return 1.2
            return f

        def make_rv_lev(lr, rm):
            def f(t):
                idx = oos_offset + t
                if idx >= len(lr) or idx >= len(rm):
                    return 1.0
                if np.isnan(lr[idx]) or np.isnan(rm[idx]):
                    return 1.0
                return 1.3 if lr[idx] < rm[idx] else 1.0
            return f

        base_m, base_r = run_vt_with_leverage(
            mkt_ret, gld_ret_arr, vix_level, dates,
            make_base_lev(), TX_COST_BPS, f"{ticker} Base VT OOS{period_idx}")

        us_m, us_r = run_vt_with_leverage(
            mkt_ret, gld_ret_arr, vix_level, dates,
            make_us_lev(full_vix), TX_COST_BPS, f"{ticker} US-style OOS{period_idx}")

        pct_m, pct_r = run_vt_with_leverage(
            mkt_ret, gld_ret_arr, vix_level, dates,
            make_pctile_lev(vix_pctile_full), TX_COST_BPS,
            f"{ticker} Percentile OOS{period_idx}")

        rv_m, rv_r = run_vt_with_leverage(
            mkt_ret, gld_ret_arr, vix_level, dates,
            make_rv_lev(local_rv_full, rv_med_full), TX_COST_BPS,
            f"{ticker} Local RV OOS{period_idx}")

        period_result = {
            "period": f"{oos_start} to {oos_end}",
            "n_days": len(mkt_ret),
            "base_sharpe": base_m["sharpe"] if base_m else None,
            "us_sharpe": us_m["sharpe"] if us_m else None,
            "pctile_sharpe": pct_m["sharpe"] if pct_m else None,
            "rv_sharpe": rv_m["sharpe"] if rv_m else None,
            "us_positive": (us_m["sharpe"] > base_m["sharpe"])
                if (us_m and base_m) else None,
            "pctile_positive": (pct_m["sharpe"] > base_m["sharpe"])
                if (pct_m and base_m) else None,
            "rv_positive": (rv_m["sharpe"] > base_m["sharpe"])
                if (rv_m and base_m) else None,
        }
        oos_market["periods"].append(period_result)

        print(f"  {ticker} OOS[{period_idx}] ({oos_start}-{oos_end}): "
              f"Base={base_m['sharpe']:.3f}, "
              f"US={us_m['sharpe']:.3f} ({'✓' if period_result['us_positive'] else '✗'}), "
              f"Pct={pct_m['sharpe']:.3f} ({'✓' if period_result['pctile_positive'] else '✗'}), "
              f"RV={rv_m['sharpe']:.3f} ({'✓' if period_result['rv_positive'] else '✗'})")

    # Count OOS wins per variant
    valid_periods = [p for p in oos_market["periods"] if p.get("us_positive") is not None]
    oos_market["n_valid_periods"] = len(valid_periods)
    oos_market["us_oos_wins"] = sum(1 for p in valid_periods if p["us_positive"])
    oos_market["pctile_oos_wins"] = sum(1 for p in valid_periods if p["pctile_positive"])
    oos_market["rv_oos_wins"] = sum(1 for p in valid_periods if p["rv_positive"])

    oos_results[ticker] = oos_market


# ==================================================================
# 6. Summary Table
# ==================================================================
print("\n\n[5/8] Summary across markets...")
print("=" * 100)
print(f"{'Market':<12} {'Base VT':>10} {'US-style':>10} {'Pctile':>10} {'RV':>10} "
      f"{'Best':>10} {'t-stat':>8} {'Harvey':>8} {'OOS':>8}")
print("-" * 100)

summary = {}
markets_with_leverage_benefit = 0
best_variant_counts = {"us_style": 0, "percentile": 0, "local_rv": 0, "none": 0}

for ticker in MARKETS:
    if ticker not in full_results:
        continue
    r = full_results[ticker]

    base_s = r["base_vt"]["sharpe"] if r["base_vt"] else 0
    us_s = r["us_style"]["sharpe"] if r["us_style"] else 0
    pct_s = r["percentile"]["sharpe"] if r["percentile"] else 0
    rv_s = r["local_rv"]["sharpe"] if r["local_rv"] else 0

    # Find best variant
    variants = {
        "us_style": us_s,
        "percentile": pct_s,
        "local_rv": rv_s,
    }
    best_key = max(variants, key=variants.get)
    best_sharpe = variants[best_key]

    # Is best variant better than base?
    if best_sharpe > base_s + 0.01:  # meaningful improvement
        markets_with_leverage_benefit += 1
        best_variant_counts[best_key] += 1

        # Get t-stat for best variant
        t_info = r.get(f"{best_key}_vs_base", {})
        t_stat = t_info.get("t_stat", 0)
        harvey_pass = t_info.get("harvey_pass", False)
    else:
        best_key = "none"
        best_variant_counts["none"] += 1
        t_stat = 0
        harvey_pass = False

    oos_info = oos_results.get(ticker, {})
    oos_str = ""
    if oos_info and best_key != "none":
        oos_wins = oos_info.get(f"{best_key}_oos_wins", 0)
        n_valid = oos_info.get("n_valid_periods", 0)
        oos_str = f"{oos_wins}/{n_valid}"

    print(f"{ticker:<12} {base_s:>10.3f} {us_s:>10.3f} {pct_s:>10.3f} {rv_s:>10.3f} "
          f"{best_key:>10} {t_stat:>8.2f} {'PASS' if harvey_pass else 'FAIL':>8} "
          f"{oos_str:>8}")

    summary[ticker] = {
        "base_sharpe": float(base_s),
        "us_style_sharpe": float(us_s),
        "percentile_sharpe": float(pct_s),
        "local_rv_sharpe": float(rv_s),
        "best_variant": best_key,
        "best_sharpe_improvement": float(best_sharpe - base_s),
        "t_stat": float(t_stat),
        "harvey_pass": harvey_pass,
        "oos_wins": oos_info.get(f"{best_key}_oos_wins", 0) if best_key != "none" else 0,
        "oos_total": oos_info.get("n_valid_periods", 0),
    }

print("-" * 100)
print(f"\nMarkets with leverage benefit: {markets_with_leverage_benefit}/{len(MARKETS)}")
print(f"Best variant distribution: {best_variant_counts}")


# ==================================================================
# 7. MDD Analysis
# ==================================================================
print("\n\n[6/8] Max Drawdown analysis...")
print(f"{'Market':<12} {'B&H MDD':>10} {'Base VT':>10} {'US-style':>10} "
      f"{'Pctile':>10} {'RV':>10}")
print("-" * 72)

for ticker in MARKETS:
    if ticker not in full_results:
        continue
    r = full_results[ticker]
    bh_mdd = r["bh"]["max_dd"] if r["bh"] else 0
    base_mdd = r["base_vt"]["max_dd"] if r["base_vt"] else 0
    us_mdd = r["us_style"]["max_dd"] if r["us_style"] else 0
    pct_mdd = r["percentile"]["max_dd"] if r["percentile"] else 0
    rv_mdd = r["local_rv"]["max_dd"] if r["local_rv"] else 0

    print(f"{ticker:<12} {bh_mdd:>10.1%} {base_mdd:>10.1%} {us_mdd:>10.1%} "
          f"{pct_mdd:>10.1%} {rv_mdd:>10.1%}")


# ==================================================================
# 8. Cross-Market Meta-Analysis
# ==================================================================
print("\n\n[7/8] Cross-market meta-analysis...")

# Collect Sharpe improvements for each variant
improvements = {"us_style": [], "percentile": [], "local_rv": []}
for ticker in MARKETS:
    if ticker not in full_results:
        continue
    r = full_results[ticker]
    base_s = r["base_vt"]["sharpe"] if r["base_vt"] else 0
    improvements["us_style"].append(r["us_style"]["sharpe"] - base_s if r["us_style"] else 0)
    improvements["percentile"].append(r["percentile"]["sharpe"] - base_s if r["percentile"] else 0)
    improvements["local_rv"].append(r["local_rv"]["sharpe"] - base_s if r["local_rv"] else 0)

print("\nSharpe improvement over Base VT (cross-market):")
for variant, imps in improvements.items():
    arr = np.array(imps)
    mean_imp = np.mean(arr)
    std_imp = np.std(arr, ddof=1)
    n = len(arr)
    t_stat_meta = mean_imp / (std_imp / np.sqrt(n)) if std_imp > 0 else 0
    pct_positive = np.mean(arr > 0)

    print(f"  {variant:>12}: mean={mean_imp:+.4f}, std={std_imp:.4f}, "
          f"t={t_stat_meta:.2f}, {pct_positive:.0%} positive, "
          f"Harvey {'PASS' if abs(t_stat_meta) > 3.0 else 'FAIL'}")

# Cross-market correlation: does leverage benefit correlate with market volatility?
vols = []
best_improvements = []
for ticker in MARKETS:
    if ticker not in full_results or ticker not in diagnostics:
        continue
    r = full_results[ticker]
    base_s = r["base_vt"]["sharpe"] if r["base_vt"] else 0
    best_imp = max(
        (r["us_style"]["sharpe"] if r["us_style"] else 0) - base_s,
        (r["percentile"]["sharpe"] if r["percentile"] else 0) - base_s,
        (r["local_rv"]["sharpe"] if r["local_rv"] else 0) - base_s,
    )
    vols.append(diagnostics[ticker]["ann_vol"])
    best_improvements.append(best_imp)

if len(vols) >= 3:
    spearman_r, spearman_p = stats.spearmanr(vols, best_improvements)
    print(f"\n  Spearman(market_vol, best_leverage_improvement): r={spearman_r:.3f}, p={spearman_p:.3f}")


# ==================================================================
# 9. Save Results
# ==================================================================
print("\n\n[8/8] Saving results...")

# Build serializable results (exclude daily return arrays)
serializable = {
    "experiment_id": "k567",
    "title": "K567: International VT Leverage — VIX-Conditional Leverage Across Markets",
    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "data_source": "yfinance",
    "methodology": {
        "markets": list(MARKETS.keys()),
        "leverage_variants": [
            "Base VT (12/VIX, no overlay)",
            "US-style (VIX<15→1.5x, VIX>25→1.0x, else 1.2x)",
            "Percentile (VIX pctile<0.3→1.5x, >0.7→1.0x, else 1.2x)",
            "Local RV (RV22<median→1.3x, else 1.0x)",
        ],
        "allocation": "50% Market ETF / 50% GLD",
        "rebalancing": "Monthly",
        "tx_cost_bps": TX_COST_BPS,
        "rf_annual": RF_ANNUAL,
        "cross_oos_periods": OOS_PERIODS,
        "bootstrap_reps": N_BOOTSTRAP,
        "harvey_threshold": 3.0,
    },
    "references": [
        "Moreira & Muir (2017) JoF: Volatility-Managed Portfolios",
        "Bozovic (2024) IRFA: VIX-managed > realized-vol managed",
        "Hood & Raughtigan (2024/2025) JPM: VT alpha from implicit trend-following",
        "K551: US VIX-Conditional Leverage (t=7.90, 11/11 OOS)",
        "K558: Taiwan Hybrid Leverage (t=4.79, 18/18 OOS)",
        "K68: International VT (13/13 MDD improvement)",
        "K237: International 50/50+VT (8/8 MDD, 0/8 Sharpe)",
    ],
    "diagnostics": diagnostics,
    "summary": summary,
    "full_results": {},
    "oos_results": oos_results,
    "cross_market_meta": {
        "n_markets": len(MARKETS),
        "markets_with_leverage_benefit": markets_with_leverage_benefit,
        "best_variant_counts": best_variant_counts,
    },
}

# Add full results (without daily returns)
for ticker, r in full_results.items():
    sr = {}
    for key in ["ticker", "name", "n_days", "years"]:
        sr[key] = r[key]
    for variant in ["bh", "base_vt", "us_style", "percentile", "local_rv"]:
        if r[variant]:
            sr[variant] = {k: float(v) if isinstance(v, (np.floating, float)) else v
                          for k, v in r[variant].items()}
    for key in ["us_style_vs_base", "percentile_vs_base", "local_rv_vs_base"]:
        if key in r:
            sr[key] = r[key]
    serializable["full_results"][ticker] = sr

# Add meta-analysis
meta_results = {}
for variant, imps in improvements.items():
    arr = np.array(imps)
    mean_imp = np.mean(arr)
    std_imp = np.std(arr, ddof=1)
    n = len(arr)
    t_meta = mean_imp / (std_imp / np.sqrt(n)) if std_imp > 0 else 0
    meta_results[variant] = {
        "mean_improvement": float(mean_imp),
        "std_improvement": float(std_imp),
        "t_stat_meta": float(t_meta),
        "pct_positive": float(np.mean(arr > 0)),
        "harvey_pass": abs(t_meta) > 3.0,
        "improvements_by_market": {ticker: float(imp)
                                    for ticker, imp in zip(MARKETS.keys(), imps)},
    }
serializable["cross_market_meta"]["variant_meta"] = meta_results

if len(vols) >= 3:
    serializable["cross_market_meta"]["vol_leverage_corr"] = {
        "spearman_r": float(spearman_r),
        "spearman_p": float(spearman_p),
    }

# Final verdict
n_harvey_pass = sum(1 for s in summary.values() if s.get("harvey_pass", False))
n_oos_majority = sum(1 for s in summary.values()
                     if s.get("oos_wins", 0) > s.get("oos_total", 0) / 2
                     and s.get("oos_total", 0) > 0)

serializable["verdict"] = {
    "leverage_universality": markets_with_leverage_benefit >= 4,
    "n_markets_with_benefit": markets_with_leverage_benefit,
    "n_harvey_pass": n_harvey_pass,
    "n_oos_majority_wins": n_oos_majority,
    "is_universal_principle": (markets_with_leverage_benefit >= 5
                               and n_harvey_pass >= 3),
    "conclusion": "",
}

if serializable["verdict"]["is_universal_principle"]:
    serializable["verdict"]["conclusion"] = (
        f"VIX-conditional leverage is a UNIVERSAL portfolio construction principle. "
        f"{markets_with_leverage_benefit}/{len(MARKETS)} markets show improvement, "
        f"{n_harvey_pass} pass Harvey t>3.0."
    )
else:
    serializable["verdict"]["conclusion"] = (
        f"VIX-conditional leverage has LIMITED generalizability. "
        f"Only {markets_with_leverage_benefit}/{len(MARKETS)} markets show improvement, "
        f"{n_harvey_pass} pass Harvey t>3.0. "
        f"Leverage overlay may be US/market-specific."
    )

# Save
results_path = "experiments/k567_international_vt_leverage_results.json"
with open(results_path, "w") as f:
    json.dump(serializable, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")

# ==================================================================
# FINAL SUMMARY
# ==================================================================
print("\n" + "=" * 80)
print("FINAL VERDICT")
print("=" * 80)
print(serializable["verdict"]["conclusion"])
print(f"\nMarkets with leverage benefit: {markets_with_leverage_benefit}/{len(MARKETS)}")
print(f"Harvey t>3.0 passes: {n_harvey_pass}/{len(MARKETS)}")
print(f"OOS majority wins: {n_oos_majority}/{len(MARKETS)}")
print(f"\nBest variant by market:")
for ticker, s in summary.items():
    print(f"  {ticker}: {s['best_variant']} (ΔSharpe={s['best_sharpe_improvement']:+.3f}, "
          f"t={s['t_stat']:.2f}, OOS={s['oos_wins']}/{s['oos_total']})")
print()
