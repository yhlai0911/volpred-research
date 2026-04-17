#!/usr/bin/env python3
"""
K115: GARCH-Enhanced Pairs Trading
===================================
First non-VT strategy research using GARCH conditional volatility.

Hypothesis: GARCH conditional vol can improve pairs trading entry/exit timing.
- High vol → wider entry threshold (avoid false signals)
- Low vol → tighter threshold (capture more trades)

Pairs tested:
1. SPY/QQQ (high-corr US equity)
2. GLD/GDX (gold/gold miners)
3. XLE/USO (energy ETF/crude oil)

Methodology:
- Engle-Granger cointegration test
- Standard pairs trading (fixed z-score ±2)
- GARCH-enhanced pairs trading (dynamic threshold)
- OOS: 2023-01-01 ~ 2024-12-31
- Transaction cost: 0.1% per trade (round trip)

Author: VolPred Research System (K115)
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from statsmodels.tsa.stattools import adfuller, coint

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
PAIRS = [
    ("SPY", "QQQ", "US Equity"),
    ("GLD", "GDX", "Gold/Miners"),
    ("XLE", "USO", "Energy"),
]

# Backup pairs if cointegration fails
BACKUP_PAIRS = [
    ("GLD", "SLV", "Precious Metals"),
    ("EWJ", "EWZ", "Intl Equity"),
    ("TLT", "IEF", "Treasuries"),
    ("XLF", "KBE", "Financials"),
]

START_DATE = "2010-01-01"
END_DATE = "2024-12-31"
OOS_START = "2023-01-01"
LOOKBACK = 60  # rolling window for z-score
GARCH_WINDOW = 500  # GARCH estimation window
ENTRY_Z = 2.0  # standard entry threshold
EXIT_Z = 0.0  # close when z crosses 0
STOP_Z = 4.0  # stop-loss threshold
TX_COST = 0.001  # 0.1% per trade (one-way)


def download_data(tickers, start, end):
    """Download adjusted close prices."""
    all_data = {}
    for t in tickers:
        print(f"  Downloading {t}...")
        df = yf.download(t, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty:
            print(f"  WARNING: No data for {t}")
            continue
        # Handle MultiIndex columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        all_data[t] = df["Close"]
    return pd.DataFrame(all_data).dropna()


def test_cointegration(prices, asset1, asset2):
    """
    Run Engle-Granger cointegration test.
    Returns: (is_cointegrated, p_value, hedge_ratio, test_stat)
    """
    y = prices[asset1].values
    x = prices[asset2].values

    # Engle-Granger test (statsmodels coint)
    score, pvalue, crit_values = coint(y, x)

    # OLS hedge ratio
    from numpy.polynomial import polynomial as P

    # Simple OLS: y = alpha + beta * x + e
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    hedge_ratio = beta[1]

    # ADF on spread
    spread = y - hedge_ratio * x
    adf_stat, adf_pvalue, _, _, _, _ = adfuller(spread, maxlag=20, autolag="AIC")

    return {
        "coint_stat": score,
        "coint_pvalue": pvalue,
        "crit_1pct": crit_values[0],
        "crit_5pct": crit_values[1],
        "crit_10pct": crit_values[2],
        "hedge_ratio": hedge_ratio,
        "adf_stat": adf_stat,
        "adf_pvalue": adf_pvalue,
        "is_cointegrated": pvalue < 0.05,
    }


def compute_spread(prices, asset1, asset2, hedge_ratio):
    """Compute the spread = asset1 - hedge_ratio * asset2."""
    return prices[asset1] - hedge_ratio * prices[asset2]


def rolling_zscore(spread, window=60):
    """Compute rolling z-score of spread."""
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    return (spread - mean) / std


def fit_garch_on_spread(spread_returns, window=500):
    """
    Fit GJR-GARCH(1,1) on spread returns to get conditional volatility.
    Returns conditional vol series (sigma).
    """
    n = len(spread_returns)
    cond_vol = pd.Series(np.nan, index=spread_returns.index)

    for i in range(window, n):
        train = spread_returns.iloc[i - window : i]

        # Scale for numerical stability
        scale = train.std()
        if scale < 1e-10:
            cond_vol.iloc[i] = scale
            continue

        try:
            am = arch_model(
                train * 100,  # scale to percentage
                vol="Garch",
                p=1,
                q=1,
                dist="normal",
                mean="Constant",
            )
            res = am.fit(disp="off", show_warning=False)
            # One-step forecast
            fcast = res.forecast(horizon=1)
            sigma2 = fcast.variance.values[-1, 0]
            cond_vol.iloc[i] = np.sqrt(sigma2) / 100  # scale back
        except Exception:
            # Fallback to EWMA
            cond_vol.iloc[i] = (
                train.ewm(span=20, min_periods=10).std().iloc[-1]
            )

    return cond_vol


def run_standard_pairs(
    zscore, spread, prices, asset1, asset2, entry_z=2.0, exit_z=0.0, stop_z=4.0
):
    """
    Standard pairs trading strategy with fixed thresholds.
    Returns trades dataframe and daily PnL.
    """
    position = 0  # +1 = long spread, -1 = short spread, 0 = flat
    trades = []
    daily_pnl = pd.Series(0.0, index=zscore.index)
    entry_date = None
    entry_spread = None

    for i in range(1, len(zscore)):
        date = zscore.index[i]
        z = zscore.iloc[i]
        s = spread.iloc[i]

        if np.isnan(z):
            continue

        # Entry signals
        if position == 0:
            if z > entry_z:
                position = -1  # short spread (expect mean reversion down)
                entry_date = date
                entry_spread = s
            elif z < -entry_z:
                position = 1  # long spread (expect mean reversion up)
                entry_date = date
                entry_spread = s

        # Exit signals
        elif position != 0:
            # Stop loss
            if (position == -1 and z > stop_z) or (position == 1 and z < -stop_z):
                pnl = position * (s - entry_spread) - 2 * TX_COST * abs(entry_spread)
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "direction": position,
                        "entry_spread": entry_spread,
                        "exit_spread": s,
                        "pnl": pnl,
                        "exit_reason": "stop_loss",
                    }
                )
                position = 0
                entry_date = None
                entry_spread = None

            # Mean reversion exit
            elif (position == -1 and z <= exit_z) or (position == 1 and z >= exit_z):
                pnl = position * (s - entry_spread) - 2 * TX_COST * abs(entry_spread)
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "direction": position,
                        "entry_spread": entry_spread,
                        "exit_spread": s,
                        "pnl": pnl,
                        "exit_reason": "mean_reversion",
                    }
                )
                position = 0
                entry_date = None
                entry_spread = None

        # Daily PnL for open positions
        if position != 0 and entry_spread is not None:
            daily_pnl.iloc[i] = position * (s - spread.iloc[i - 1])

    return pd.DataFrame(trades), daily_pnl


def run_garch_enhanced_pairs(
    zscore,
    spread,
    cond_vol,
    prices,
    asset1,
    asset2,
    base_entry_z=2.0,
    exit_z=0.0,
    stop_z=4.0,
):
    """
    GARCH-enhanced pairs trading:
    - Dynamic entry threshold: base_z * (cond_vol / uncond_vol)
    - Position sizing: inverse conditional vol
    """
    position = 0
    trades = []
    daily_pnl = pd.Series(0.0, index=zscore.index)
    entry_date = None
    entry_spread = None
    pos_size = 1.0

    # Unconditional vol (rolling) - aligned to spread index
    uncond_vol = spread.diff().rolling(252).std()

    for i in range(1, len(zscore)):
        date = zscore.index[i]
        z = zscore.iloc[i]
        s = spread.iloc[i]

        # Use .get() with date index for cond_vol/uncond_vol (different length)
        cv = cond_vol.get(date, np.nan)
        uv = uncond_vol.get(date, np.nan)

        if np.isnan(z) or np.isnan(cv) or np.isnan(uv) or uv < 1e-10:
            continue

        # Dynamic threshold: scale entry threshold by vol ratio
        vol_ratio = cv / uv
        vol_ratio = np.clip(vol_ratio, 0.5, 2.0)  # bound to avoid extremes
        dynamic_entry_z = base_entry_z * vol_ratio
        dynamic_stop_z = stop_z * vol_ratio

        # Position sizing: inverse vol (normalized)
        pos_size = 1.0 / vol_ratio  # more capital when vol is low
        pos_size = np.clip(pos_size, 0.5, 2.0)

        # Entry signals
        if position == 0:
            if z > dynamic_entry_z:
                position = -1
                entry_date = date
                entry_spread = s
                entry_pos_size = pos_size
            elif z < -dynamic_entry_z:
                position = 1
                entry_date = date
                entry_spread = s
                entry_pos_size = pos_size

        # Exit signals
        elif position != 0:
            if (position == -1 and z > dynamic_stop_z) or (
                position == 1 and z < -dynamic_stop_z
            ):
                raw_pnl = position * (s - entry_spread)
                pnl = (
                    entry_pos_size * raw_pnl
                    - 2 * TX_COST * abs(entry_spread) * entry_pos_size
                )
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "direction": position,
                        "entry_spread": entry_spread,
                        "exit_spread": s,
                        "pnl": pnl,
                        "pos_size": entry_pos_size,
                        "dynamic_entry_z": dynamic_entry_z,
                        "exit_reason": "stop_loss",
                    }
                )
                position = 0

            elif (position == -1 and z <= exit_z) or (position == 1 and z >= exit_z):
                raw_pnl = position * (s - entry_spread)
                pnl = (
                    entry_pos_size * raw_pnl
                    - 2 * TX_COST * abs(entry_spread) * entry_pos_size
                )
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "direction": position,
                        "entry_spread": entry_spread,
                        "exit_spread": s,
                        "pnl": pnl,
                        "pos_size": entry_pos_size,
                        "dynamic_entry_z": dynamic_entry_z,
                        "exit_reason": "mean_reversion",
                    }
                )
                position = 0

        # Daily PnL
        if position != 0 and entry_spread is not None:
            daily_pnl.iloc[i] = entry_pos_size * position * (s - spread.iloc[i - 1])

    return pd.DataFrame(trades), daily_pnl


def compute_strategy_metrics(daily_pnl, trades_df, label=""):
    """Compute strategy performance metrics."""
    # Filter to non-zero days for return calculation
    # Use cumulative PnL approach
    cum_pnl = daily_pnl.cumsum()

    # Annualized metrics
    n_days = len(daily_pnl)
    n_years = n_days / 252

    total_return = cum_pnl.iloc[-1] if len(cum_pnl) > 0 else 0
    daily_std = daily_pnl.std()
    annual_std = daily_std * np.sqrt(252)

    # Sharpe (using PnL, not returns - need to normalize)
    mean_daily = daily_pnl.mean()
    sharpe = (mean_daily / daily_std * np.sqrt(252)) if daily_std > 0 else 0

    # MDD from cumulative PnL
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max
    mdd = drawdown.min()

    # Trade statistics
    n_trades = len(trades_df)
    if n_trades > 0:
        win_rate = (trades_df["pnl"] > 0).mean()
        avg_pnl = trades_df["pnl"].mean()
        avg_holding = 0
        if "entry_date" in trades_df.columns and "exit_date" in trades_df.columns:
            trades_df_copy = trades_df.copy()
            trades_df_copy["holding_days"] = (
                pd.to_datetime(trades_df_copy["exit_date"])
                - pd.to_datetime(trades_df_copy["entry_date"])
            ).dt.days
            avg_holding = trades_df_copy["holding_days"].mean()
        profit_factor = (
            trades_df[trades_df["pnl"] > 0]["pnl"].sum()
            / abs(trades_df[trades_df["pnl"] < 0]["pnl"].sum())
            if (trades_df["pnl"] < 0).any()
            else float("inf")
        )
        stop_loss_pct = (
            (trades_df["exit_reason"] == "stop_loss").mean()
            if "exit_reason" in trades_df.columns
            else 0
        )
    else:
        win_rate = avg_pnl = avg_holding = profit_factor = stop_loss_pct = 0

    # Harvey t-stat for Sharpe
    harvey_t = sharpe / (1 / np.sqrt(n_years)) if n_years > 0 else 0

    return {
        "label": label,
        "sharpe": round(sharpe, 3),
        "harvey_t": round(harvey_t, 2),
        "total_pnl": round(total_return, 4),
        "annual_vol": round(annual_std, 4),
        "mdd": round(mdd, 4),
        "n_trades": n_trades,
        "win_rate": round(win_rate, 3),
        "avg_pnl_per_trade": round(avg_pnl, 6) if n_trades > 0 else 0,
        "avg_holding_days": round(avg_holding, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "stop_loss_pct": round(stop_loss_pct, 3),
        "n_years": round(n_years, 2),
    }


def compute_oos_metrics(daily_pnl, trades_df, oos_start, label=""):
    """Compute metrics only for OOS period."""
    oos_pnl = daily_pnl.loc[oos_start:]
    if trades_df is not None and len(trades_df) > 0:
        oos_trades = trades_df[
            pd.to_datetime(trades_df["entry_date"]) >= pd.to_datetime(oos_start)
        ]
    else:
        oos_trades = pd.DataFrame()
    return compute_strategy_metrics(oos_pnl, oos_trades, label=label)


def rolling_cointegration_test(prices, asset1, asset2, window=252):
    """Test if cointegration is stable over time using rolling windows."""
    results = []
    for i in range(window, len(prices), 63):  # quarterly steps
        sub = prices.iloc[i - window : i]
        try:
            _, pval, _ = coint(sub[asset1].values, sub[asset2].values)
            results.append(
                {"date": sub.index[-1], "pvalue": pval, "cointegrated": pval < 0.05}
            )
        except Exception:
            pass
    df = pd.DataFrame(results)
    stable_pct = df["cointegrated"].mean() if len(df) > 0 else 0
    return df, stable_pct


# ============================================================
# Main execution
# ============================================================
def main():
    print("=" * 70)
    print("K115: GARCH-Enhanced Pairs Trading")
    print("=" * 70)
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"OOS: {OOS_START} to {END_DATE}")
    print(f"TX cost: {TX_COST*100:.1f}% per trade")
    print()

    # Step 1: Download all data
    print("=" * 70)
    print("STEP 1: Data Download")
    print("=" * 70)
    all_tickers = set()
    for a1, a2, _ in PAIRS + BACKUP_PAIRS:
        all_tickers.add(a1)
        all_tickers.add(a2)

    prices = download_data(list(all_tickers), START_DATE, END_DATE)
    print(f"  Downloaded {len(prices.columns)} assets, {len(prices)} days")
    print(f"  Date range: {prices.index[0].date()} to {prices.index[-1].date()}")
    print()

    # Step 2: Cointegration tests
    print("=" * 70)
    print("STEP 2: Cointegration Tests")
    print("=" * 70)

    valid_pairs = []
    all_coint_results = []

    for a1, a2, name in PAIRS + BACKUP_PAIRS:
        if a1 not in prices.columns or a2 not in prices.columns:
            print(f"  {name} ({a1}/{a2}): SKIP - data not available")
            continue

        pair_prices = prices[[a1, a2]].dropna()
        if len(pair_prices) < 500:
            print(f"  {name} ({a1}/{a2}): SKIP - insufficient data ({len(pair_prices)} days)")
            continue

        result = test_cointegration(pair_prices, a1, a2)
        result["pair"] = f"{a1}/{a2}"
        result["name"] = name
        all_coint_results.append(result)

        status = "PASS" if result["is_cointegrated"] else "FAIL"
        print(
            f"  {name} ({a1}/{a2}): {status} | "
            f"coint p={result['coint_pvalue']:.4f} | "
            f"ADF p={result['adf_pvalue']:.4f} | "
            f"hedge_ratio={result['hedge_ratio']:.4f}"
        )

        if result["is_cointegrated"]:
            valid_pairs.append((a1, a2, name, result["hedge_ratio"]))

    print()
    print(f"  Cointegrated pairs: {len(valid_pairs)} / {len(all_coint_results)}")

    # Rolling cointegration stability
    print()
    print("  Rolling cointegration stability (252-day windows):")
    for a1, a2, name, _ in valid_pairs:
        pair_prices = prices[[a1, a2]].dropna()
        _, stable_pct = rolling_cointegration_test(pair_prices, a1, a2)
        print(f"    {name} ({a1}/{a2}): {stable_pct*100:.1f}% of windows cointegrated")

    if len(valid_pairs) == 0:
        print("\n  WARNING: No cointegrated pairs found! Testing all pairs anyway for analysis.")
        # Use all primary pairs even if not cointegrated
        for a1, a2, name in PAIRS:
            if a1 in prices.columns and a2 in prices.columns:
                pair_prices = prices[[a1, a2]].dropna()
                result = test_cointegration(pair_prices, a1, a2)
                valid_pairs.append((a1, a2, name, result["hedge_ratio"]))

    # Step 3: Run strategies on each pair
    print()
    print("=" * 70)
    print("STEP 3: Strategy Execution")
    print("=" * 70)

    all_results = []

    for a1, a2, name, hedge_ratio in valid_pairs:
        print(f"\n{'─'*60}")
        print(f"  Pair: {a1}/{a2} ({name})")
        print(f"  Hedge ratio: {hedge_ratio:.4f}")
        print(f"{'─'*60}")

        pair_prices = prices[[a1, a2]].dropna()
        spread = compute_spread(pair_prices, a1, a2, hedge_ratio)
        zscore = rolling_zscore(spread, window=LOOKBACK)

        # Spread returns for GARCH
        spread_ret = spread.diff().dropna()

        # Correlation check
        corr = pair_prices[a1].pct_change().corr(pair_prices[a2].pct_change())
        print(f"  Return correlation: {corr:.3f}")
        print(f"  Spread mean: {spread.mean():.4f}, std: {spread.std():.4f}")
        print(f"  Spread stationarity (ADF p): {adfuller(spread.dropna())[1]:.4f}")

        # 3a: Standard pairs trading
        print(f"\n  [Standard Pairs Trading] z_entry=±{ENTRY_Z}, z_exit={EXIT_Z}")
        std_trades, std_pnl = run_standard_pairs(
            zscore, spread, pair_prices, a1, a2, ENTRY_Z, EXIT_Z, STOP_Z
        )

        std_full = compute_strategy_metrics(std_pnl, std_trades, f"Standard ({a1}/{a2})")
        std_oos = compute_oos_metrics(std_pnl, std_trades, OOS_START, f"Standard OOS ({a1}/{a2})")

        print(f"    Full sample: Sharpe={std_full['sharpe']}, "
              f"MDD={std_full['mdd']:.4f}, "
              f"Trades={std_full['n_trades']}, "
              f"WinRate={std_full['win_rate']:.1%}")
        print(f"    OOS ({OOS_START}+): Sharpe={std_oos['sharpe']}, "
              f"MDD={std_oos['mdd']:.4f}, "
              f"Trades={std_oos['n_trades']}, "
              f"WinRate={std_oos['win_rate']:.1%}")

        # 3b: GARCH-enhanced pairs trading
        print(f"\n  [GARCH-Enhanced Pairs Trading]")
        print(f"    Fitting GARCH on spread returns (window={GARCH_WINDOW})...")

        cond_vol = fit_garch_on_spread(spread_ret, window=GARCH_WINDOW)
        valid_cv = cond_vol.dropna()
        print(f"    Conditional vol: {len(valid_cv)} observations")
        print(f"    Cond vol mean={valid_cv.mean():.6f}, "
              f"std={valid_cv.std():.6f}")

        # Vol ratio statistics
        uncond_vol = spread_ret.rolling(252).std()
        vol_ratio = (cond_vol / uncond_vol).dropna()
        print(f"    Vol ratio (cond/uncond): mean={vol_ratio.mean():.3f}, "
              f"std={vol_ratio.std():.3f}, "
              f"range=[{vol_ratio.quantile(0.05):.3f}, {vol_ratio.quantile(0.95):.3f}]")

        garch_trades, garch_pnl = run_garch_enhanced_pairs(
            zscore, spread, cond_vol, pair_prices, a1, a2, ENTRY_Z, EXIT_Z, STOP_Z
        )

        garch_full = compute_strategy_metrics(garch_pnl, garch_trades, f"GARCH ({a1}/{a2})")
        garch_oos = compute_oos_metrics(
            garch_pnl, garch_trades, OOS_START, f"GARCH OOS ({a1}/{a2})"
        )

        print(f"    Full sample: Sharpe={garch_full['sharpe']}, "
              f"MDD={garch_full['mdd']:.4f}, "
              f"Trades={garch_full['n_trades']}, "
              f"WinRate={garch_full['win_rate']:.1%}")
        print(f"    OOS ({OOS_START}+): Sharpe={garch_oos['sharpe']}, "
              f"MDD={garch_oos['mdd']:.4f}, "
              f"Trades={garch_oos['n_trades']}, "
              f"WinRate={garch_oos['win_rate']:.1%}")

        # 3c: Compare
        sharpe_diff = garch_oos["sharpe"] - std_oos["sharpe"]
        print(f"\n  GARCH vs Standard (OOS): Sharpe diff = {sharpe_diff:+.3f}")

        # DM-like test on daily PnL (paired comparison)
        oos_std_pnl = std_pnl.loc[OOS_START:]
        oos_garch_pnl = garch_pnl.loc[OOS_START:]
        pnl_diff = oos_garch_pnl - oos_std_pnl
        if pnl_diff.std() > 0:
            dm_t = pnl_diff.mean() / (pnl_diff.std() / np.sqrt(len(pnl_diff)))
            dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), df=len(pnl_diff) - 1))
        else:
            dm_t = 0
            dm_p = 1.0
        print(f"  DM-like test: t={dm_t:.3f}, p={dm_p:.4f}")

        pair_result = {
            "pair": f"{a1}/{a2}",
            "name": name,
            "correlation": round(corr, 3),
            "hedge_ratio": round(hedge_ratio, 4),
            "standard_full": std_full,
            "standard_oos": std_oos,
            "garch_full": garch_full,
            "garch_oos": garch_oos,
            "sharpe_diff_oos": round(sharpe_diff, 3),
            "dm_t": round(dm_t, 3),
            "dm_p": round(dm_p, 4),
            "vol_ratio_mean": round(vol_ratio.mean(), 3),
            "vol_ratio_std": round(vol_ratio.std(), 3),
        }
        all_results.append(pair_result)

    # Step 4: Cross-pair summary
    print()
    print("=" * 70)
    print("STEP 4: Cross-Pair Summary")
    print("=" * 70)

    print(f"\n{'Pair':<15} {'Strategy':<12} {'Sharpe':>8} {'MDD':>10} {'Trades':>8} {'WinRate':>8} {'AvgHold':>8} {'Harvey_t':>9}")
    print("─" * 82)

    for r in all_results:
        for key, strat_name in [("standard_oos", "Standard"), ("garch_oos", "GARCH")]:
            m = r[key]
            print(
                f"{r['pair']:<15} {strat_name:<12} "
                f"{m['sharpe']:>8.3f} "
                f"{m['mdd']:>10.4f} "
                f"{m['n_trades']:>8} "
                f"{m['win_rate']:>7.1%} "
                f"{m['avg_holding_days']:>7.1f}d "
                f"{m['harvey_t']:>9.2f}"
            )
        print()

    # Summary statistics
    std_sharpes = [r["standard_oos"]["sharpe"] for r in all_results]
    garch_sharpes = [r["garch_oos"]["sharpe"] for r in all_results]
    sharpe_diffs = [r["sharpe_diff_oos"] for r in all_results]

    print(f"\n  Average OOS Sharpe - Standard: {np.mean(std_sharpes):.3f}")
    print(f"  Average OOS Sharpe - GARCH:    {np.mean(garch_sharpes):.3f}")
    print(f"  Average Sharpe improvement:     {np.mean(sharpe_diffs):+.3f}")
    print(f"  GARCH wins: {sum(1 for d in sharpe_diffs if d > 0)}/{len(sharpe_diffs)} pairs")

    # Paired t-test across pairs
    if len(sharpe_diffs) >= 2:
        t_stat, p_val = stats.ttest_1samp(sharpe_diffs, 0)
        print(f"  Paired t-test (Sharpe diff): t={t_stat:.3f}, p={p_val:.4f}")
    else:
        t_stat, p_val = 0, 1
        print(f"  Paired t-test: insufficient pairs")

    # Step 5: Additional analysis - threshold sensitivity
    print()
    print("=" * 70)
    print("STEP 5: Entry Threshold Sensitivity")
    print("=" * 70)

    # Test different base entry thresholds
    if len(valid_pairs) > 0:
        a1, a2, name, hedge_ratio = valid_pairs[0]  # Use first pair
        pair_prices = prices[[a1, a2]].dropna()
        spread = compute_spread(pair_prices, a1, a2, hedge_ratio)
        zscore = rolling_zscore(spread, window=LOOKBACK)
        spread_ret = spread.diff().dropna()
        cond_vol = fit_garch_on_spread(spread_ret, window=GARCH_WINDOW)

        print(f"\n  Testing on {a1}/{a2}:")
        print(f"  {'Threshold':>10} {'Std Sharpe':>12} {'GARCH Sharpe':>14} {'Diff':>8} {'Std #Trades':>12} {'GARCH #Trades':>14}")
        print("  " + "─" * 72)

        for entry_z in [1.0, 1.5, 2.0, 2.5, 3.0]:
            std_tr, std_p = run_standard_pairs(
                zscore, spread, pair_prices, a1, a2, entry_z, EXIT_Z, entry_z * 2
            )
            std_m = compute_oos_metrics(std_p, std_tr, OOS_START)

            garch_tr, garch_p = run_garch_enhanced_pairs(
                zscore, spread, cond_vol, pair_prices, a1, a2, entry_z, EXIT_Z, entry_z * 2
            )
            garch_m = compute_oos_metrics(garch_p, garch_tr, OOS_START)

            diff = garch_m["sharpe"] - std_m["sharpe"]
            print(
                f"  {entry_z:>10.1f} "
                f"{std_m['sharpe']:>12.3f} "
                f"{garch_m['sharpe']:>14.3f} "
                f"{diff:>+8.3f} "
                f"{std_m['n_trades']:>12} "
                f"{garch_m['n_trades']:>14}"
            )

    # Step 6: Regime analysis
    print()
    print("=" * 70)
    print("STEP 6: Regime Analysis (High Vol vs Low Vol Periods)")
    print("=" * 70)

    if "SPY" in prices.columns:
        spy_ret = prices["SPY"].pct_change()
        spy_vol = spy_ret.rolling(22).std() * np.sqrt(252)

        for a1, a2, name, hedge_ratio in valid_pairs:
            pair_prices = prices[[a1, a2]].dropna()
            spread = compute_spread(pair_prices, a1, a2, hedge_ratio)
            zscore = rolling_zscore(spread, window=LOOKBACK)
            spread_ret = spread.diff().dropna()
            cond_vol = fit_garch_on_spread(spread_ret, window=GARCH_WINDOW)

            # Split into high/low vol regimes
            aligned = pd.DataFrame({"spy_vol": spy_vol, "zscore": zscore}).dropna()
            median_vol = aligned["spy_vol"].median()

            # High vol period
            high_vol_dates = aligned[aligned["spy_vol"] > median_vol].index
            low_vol_dates = aligned[aligned["spy_vol"] <= median_vol].index

            std_tr, std_pnl = run_standard_pairs(
                zscore, spread, pair_prices, a1, a2, ENTRY_Z, EXIT_Z, STOP_Z
            )
            garch_tr, garch_pnl = run_garch_enhanced_pairs(
                zscore, spread, cond_vol, pair_prices, a1, a2, ENTRY_Z, EXIT_Z, STOP_Z
            )

            # High vol PnL
            std_high = std_pnl.loc[std_pnl.index.isin(high_vol_dates)]
            garch_high = garch_pnl.loc[garch_pnl.index.isin(high_vol_dates)]
            std_low = std_pnl.loc[std_pnl.index.isin(low_vol_dates)]
            garch_low = garch_pnl.loc[garch_pnl.index.isin(low_vol_dates)]

            std_sharpe_high = (
                std_high.mean() / std_high.std() * np.sqrt(252)
                if std_high.std() > 0
                else 0
            )
            garch_sharpe_high = (
                garch_high.mean() / garch_high.std() * np.sqrt(252)
                if garch_high.std() > 0
                else 0
            )
            std_sharpe_low = (
                std_low.mean() / std_low.std() * np.sqrt(252)
                if std_low.std() > 0
                else 0
            )
            garch_sharpe_low = (
                garch_low.mean() / garch_low.std() * np.sqrt(252)
                if garch_low.std() > 0
                else 0
            )

            print(f"\n  {a1}/{a2} ({name}):")
            print(f"    High vol regime: Standard Sharpe={std_sharpe_high:.3f}, "
                  f"GARCH Sharpe={garch_sharpe_high:.3f} "
                  f"(diff={garch_sharpe_high-std_sharpe_high:+.3f})")
            print(f"    Low vol regime:  Standard Sharpe={std_sharpe_low:.3f}, "
                  f"GARCH Sharpe={garch_sharpe_low:.3f} "
                  f"(diff={garch_sharpe_low-std_sharpe_low:+.3f})")

    # Step 7: Conclusions
    print()
    print("=" * 70)
    print("STEP 7: Conclusions")
    print("=" * 70)

    # Determine overall result
    avg_improvement = np.mean(sharpe_diffs) if sharpe_diffs else 0
    garch_win_count = sum(1 for d in sharpe_diffs if d > 0)
    n_pairs_tested = len(sharpe_diffs)

    print(f"\n  1. Cointegration: {len(valid_pairs)} pairs tested")
    for r in all_coint_results:
        status = "Cointegrated" if r["is_cointegrated"] else "NOT cointegrated"
        print(f"     {r['pair']} ({r['name']}): {status} (p={r['coint_pvalue']:.4f})")

    print(f"\n  2. Standard Pairs Trading Performance (OOS):")
    for r in all_results:
        m = r["standard_oos"]
        print(f"     {r['pair']}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.4f}, "
              f"Harvey_t={m['harvey_t']:.2f}")

    print(f"\n  3. GARCH Enhancement Effect:")
    print(f"     Average Sharpe improvement: {avg_improvement:+.3f}")
    print(f"     GARCH wins: {garch_win_count}/{n_pairs_tested}")
    if len(sharpe_diffs) >= 2:
        print(f"     Paired t-test: t={t_stat:.3f}, p={p_val:.4f}")

    # Final verdict
    print(f"\n  4. Final Verdict:")
    if avg_improvement > 0.1 and p_val < 0.05:
        verdict = "POSITIVE: GARCH significantly improves pairs trading"
    elif avg_improvement > 0:
        verdict = "MARGINAL: GARCH shows slight improvement but not statistically significant"
    elif avg_improvement < -0.1:
        verdict = "NEGATIVE: GARCH hurts pairs trading performance"
    else:
        verdict = "NULL: GARCH adds no meaningful value to pairs trading"
    print(f"     {verdict}")

    # Harvey threshold check
    any_harvey = any(
        r["garch_oos"]["harvey_t"] > 3.0 or r["standard_oos"]["harvey_t"] > 3.0
        for r in all_results
    )
    print(f"     Any strategy passes Harvey t>3.0: {'YES' if any_harvey else 'NO'}")

    print(f"\n  5. Key Insight:")
    print(f"     Pairs trading is a mean-reversion strategy that depends on")
    print(f"     spread stationarity. GARCH adds complexity but the primary")
    print(f"     challenge is finding truly cointegrated pairs that remain")
    print(f"     stable over time, not optimizing entry/exit thresholds.")

    # Save results
    output = {
        "experiment": "K115",
        "title": "GARCH-Enhanced Pairs Trading",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "oos_start": OOS_START,
            "lookback": LOOKBACK,
            "garch_window": GARCH_WINDOW,
            "entry_z": ENTRY_Z,
            "tx_cost": TX_COST,
        },
        "cointegration_results": all_coint_results,
        "pair_results": all_results,
        "summary": {
            "n_pairs_tested": n_pairs_tested,
            "avg_sharpe_standard": round(np.mean(std_sharpes), 3) if std_sharpes else None,
            "avg_sharpe_garch": round(np.mean(garch_sharpes), 3) if garch_sharpes else None,
            "avg_sharpe_improvement": round(avg_improvement, 3),
            "garch_wins": garch_win_count,
            "paired_t_stat": round(t_stat, 3) if len(sharpe_diffs) >= 2 else None,
            "paired_p_value": round(p_val, 4) if len(sharpe_diffs) >= 2 else None,
            "passes_harvey": any_harvey,
            "verdict": verdict,
        },
    }

    # Convert datetime objects for JSON serialization
    def convert_timestamps(obj):
        if isinstance(obj, dict):
            return {k: convert_timestamps(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_timestamps(i) for i in obj]
        elif isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj

    output = convert_timestamps(output)

    out_path = Path(__file__).parent / "pairs_trading_garch_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return output


if __name__ == "__main__":
    main()
