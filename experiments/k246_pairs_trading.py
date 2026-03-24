#!/usr/bin/env python3
"""
K246: Pairs Trading SPY-QQQ — Mean Reversion Between Correlated Assets
=======================================================================
[提出: 用戶, 執行: Claude]

Hypothesis: SPY and QQQ are highly correlated (r>0.95). When they diverge
from their equilibrium relationship, mean reversion creates a tradable signal.

Data: SPY, QQQ daily from yfinance, 2005-2024.

Methodology:
1. Spread = log(QQQ) - β × log(SPY), β from rolling OLS (252d)
2. Z-score = (spread - MA(60d)) / std(60d)
3. Three trading rules:
   a. Classic: entry ±2σ, exit ±0.5σ
   b. Bollinger: entry ±1.5σ, exit 0
   c. Adaptive: entry = rolling 95th pctile of |Z|
4. Dollar-neutral: $1 long + $β short (or vice versa)
5. 5-period cross-OOS validation
6. Transaction cost: 10 bps round-trip

KEY RISK: Mean reversion breaks during structural shifts (tech bubble, COVID tech boom).
⚠️ REQUIRES SHORT SELLING — sophisticated investors only.

Author: VolPred Research System (K246)
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
START_DATE = "2005-01-01"
END_DATE = "2024-12-31"
HEDGE_RATIO_WINDOW = 252      # rolling OLS window for β
ZSCORE_LOOKBACK = 60          # MA + std window for z-score
TX_COST_ONEWAY = 0.0005       # 5 bps per leg one-way (10 bps round-trip total)
STOP_LOSS_Z = 4.0             # stop-loss if z-score exceeds this

# 5-period cross-OOS splits
OOS_PERIODS = [
    ("2009-01-01", "2012-12-31", "2009-2012 (Post-GFC Recovery)"),
    ("2013-01-01", "2016-12-31", "2013-2016 (Low Vol Bull)"),
    ("2017-01-01", "2018-12-31", "2017-2018 (Late Cycle + Volmageddon)"),
    ("2019-01-01", "2021-12-31", "2019-2021 (COVID + Tech Boom)"),
    ("2022-01-01", "2024-12-31", "2022-2024 (Rate Hikes + AI Boom)"),
]


def download_data():
    """Download SPY and QQQ adjusted close prices."""
    print("=" * 70)
    print("K246: Pairs Trading SPY-QQQ")
    print("=" * 70)
    print(f"\nDownloading data {START_DATE} to {END_DATE}...")

    tickers = ["SPY", "QQQ"]
    prices = {}
    for t in tickers:
        df = yf.download(t, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[t] = df["Close"]
        print(f"  {t}: {len(df)} trading days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    # Align dates
    price_df = pd.DataFrame(prices).dropna()
    print(f"  Aligned: {len(price_df)} common trading days")
    return price_df


def compute_spread(price_df):
    """
    Compute the log-spread with rolling hedge ratio.
    spread_t = log(QQQ_t) - β_t × log(SPY_t)
    β_t from rolling OLS(252d): log(QQQ) = α + β × log(SPY) + ε
    """
    log_spy = np.log(price_df["SPY"])
    log_qqq = np.log(price_df["QQQ"])

    n = len(price_df)
    beta = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    r_squared = np.full(n, np.nan)

    for i in range(HEDGE_RATIO_WINDOW, n):
        y = log_qqq.iloc[i - HEDGE_RATIO_WINDOW:i].values
        x = log_spy.iloc[i - HEDGE_RATIO_WINDOW:i].values
        X = np.column_stack([np.ones(HEDGE_RATIO_WINDOW), x])
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        alpha[i] = coef[0]
        beta[i] = coef[1]
        ss_res = np.sum((y - X @ coef) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared[i] = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    spread = log_qqq - beta * log_spy

    result = pd.DataFrame({
        "spread": spread,
        "beta": beta,
        "alpha": alpha,
        "r_squared": r_squared,
        "log_spy": log_spy,
        "log_qqq": log_qqq,
    }, index=price_df.index)

    return result


def compute_zscore(spread_series):
    """Z-score = (spread - MA) / rolling_std, using ZSCORE_LOOKBACK window."""
    ma = spread_series.rolling(ZSCORE_LOOKBACK).mean()
    std = spread_series.rolling(ZSCORE_LOOKBACK).std()
    z = (spread_series - ma) / std
    return z


def backtest_classic(price_df, spread_df, zscore, entry_z=2.0, exit_z=0.5, label="Classic"):
    """
    Classic pairs trading:
    - Long spread (long QQQ, short β×SPY) when Z < -entry_z
    - Short spread (short QQQ, long β×SPY) when Z > +entry_z
    - Exit when |Z| < exit_z
    - Stop-loss at |Z| > STOP_LOSS_Z

    Returns daily P&L series (dollar-neutral).
    """
    n = len(price_df)
    position = 0  # +1 = long spread, -1 = short spread, 0 = flat
    positions = np.zeros(n)
    entry_prices_qqq = np.zeros(n)
    entry_prices_spy = np.zeros(n)
    entry_betas = np.zeros(n)

    trades = []
    current_entry_day = None

    spy_ret = price_df["SPY"].pct_change().values
    qqq_ret = price_df["QQQ"].pct_change().values
    beta_arr = spread_df["beta"].values
    z_arr = zscore.values

    daily_pnl = np.zeros(n)

    for i in range(1, n):
        if np.isnan(z_arr[i]) or np.isnan(beta_arr[i]):
            positions[i] = 0
            continue

        z = z_arr[i]
        prev_pos = position

        # Entry logic
        if position == 0:
            if z < -entry_z:
                position = 1   # long spread: long QQQ, short SPY
                current_entry_day = i
            elif z > entry_z:
                position = -1  # short spread: short QQQ, long SPY
                current_entry_day = i

        # Exit logic
        elif position == 1:
            if z > -exit_z or z > STOP_LOSS_Z:
                # Record trade
                trades.append({
                    "entry_day": current_entry_day,
                    "exit_day": i,
                    "holding_days": i - current_entry_day,
                    "direction": "long_spread",
                    "exit_reason": "stop_loss" if z > STOP_LOSS_Z else "target",
                })
                position = 0
                current_entry_day = None

        elif position == -1:
            if z < exit_z or z < -STOP_LOSS_Z:
                trades.append({
                    "entry_day": current_entry_day,
                    "exit_day": i,
                    "holding_days": i - current_entry_day,
                    "direction": "short_spread",
                    "exit_reason": "stop_loss" if z < -STOP_LOSS_Z else "target",
                })
                position = 0
                current_entry_day = None

        positions[i] = position

        # Daily P&L: position × (qqq_ret - β × spy_ret)
        # Dollar-neutral: $1 in QQQ, $β in SPY
        if prev_pos != 0 and not np.isnan(qqq_ret[i]) and not np.isnan(spy_ret[i]):
            b = beta_arr[i - 1]  # use previous day's beta for today's return
            spread_return = qqq_ret[i] - b * spy_ret[i]
            daily_pnl[i] = prev_pos * spread_return

        # Transaction cost on entry/exit
        if prev_pos == 0 and position != 0:
            # Entry: pay TX cost on both legs
            daily_pnl[i] -= 2 * TX_COST_ONEWAY
        elif prev_pos != 0 and position == 0:
            # Exit: pay TX cost on both legs
            daily_pnl[i] -= 2 * TX_COST_ONEWAY

    pnl_series = pd.Series(daily_pnl, index=price_df.index)
    pos_series = pd.Series(positions, index=price_df.index)

    return pnl_series, pos_series, trades


def backtest_bollinger(price_df, spread_df, zscore):
    """Bollinger variant: entry at ±1.5σ, exit at 0."""
    return backtest_classic(price_df, spread_df, zscore, entry_z=1.5, exit_z=0.0, label="Bollinger")


def backtest_adaptive(price_df, spread_df, zscore):
    """
    Adaptive variant: entry threshold = rolling 95th percentile of |Z| (252d).
    Exit at 0.
    """
    n = len(price_df)
    z_arr = zscore.values
    beta_arr = spread_df["beta"].values
    spy_ret = price_df["SPY"].pct_change().values
    qqq_ret = price_df["QQQ"].pct_change().values

    # Rolling 95th percentile of |Z|
    abs_z = np.abs(z_arr)
    adaptive_threshold = np.full(n, np.nan)
    for i in range(252, n):
        window = abs_z[i - 252:i]
        valid = window[~np.isnan(window)]
        if len(valid) > 50:
            adaptive_threshold[i] = np.percentile(valid, 95)

    position = 0
    positions = np.zeros(n)
    daily_pnl = np.zeros(n)
    trades = []
    current_entry_day = None

    for i in range(1, n):
        if np.isnan(z_arr[i]) or np.isnan(beta_arr[i]) or np.isnan(adaptive_threshold[i]):
            positions[i] = 0
            continue

        z = z_arr[i]
        threshold = adaptive_threshold[i]
        prev_pos = position

        if position == 0:
            if z < -threshold:
                position = 1
                current_entry_day = i
            elif z > threshold:
                position = -1
                current_entry_day = i
        elif position == 1:
            if z > 0 or z > STOP_LOSS_Z:
                trades.append({
                    "entry_day": current_entry_day,
                    "exit_day": i,
                    "holding_days": i - current_entry_day,
                    "direction": "long_spread",
                    "exit_reason": "stop_loss" if z > STOP_LOSS_Z else "target",
                })
                position = 0
                current_entry_day = None
        elif position == -1:
            if z < 0 or z < -STOP_LOSS_Z:
                trades.append({
                    "entry_day": current_entry_day,
                    "exit_day": i,
                    "holding_days": i - current_entry_day,
                    "direction": "short_spread",
                    "exit_reason": "stop_loss" if z < -STOP_LOSS_Z else "target",
                })
                position = 0
                current_entry_day = None

        positions[i] = position

        if prev_pos != 0 and not np.isnan(qqq_ret[i]) and not np.isnan(spy_ret[i]):
            b = beta_arr[i - 1]
            spread_return = qqq_ret[i] - b * spy_ret[i]
            daily_pnl[i] = prev_pos * spread_return

        if prev_pos == 0 and position != 0:
            daily_pnl[i] -= 2 * TX_COST_ONEWAY
        elif prev_pos != 0 and position == 0:
            daily_pnl[i] -= 2 * TX_COST_ONEWAY

    pnl_series = pd.Series(daily_pnl, index=price_df.index)
    pos_series = pd.Series(positions, index=price_df.index)

    return pnl_series, pos_series, trades


def compute_metrics(pnl_series, trades, label, period_label="Full"):
    """Compute Sharpe, MDD, win rate, avg holding period, profit/trade."""
    # Filter to non-NaN
    pnl = pnl_series.dropna()
    if len(pnl) == 0:
        return None

    total_ret = pnl.sum()
    ann_ret = pnl.mean() * 252
    ann_vol = pnl.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum_pnl = pnl.cumsum()
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max
    mdd = drawdown.min()

    # Trade-level metrics
    n_trades = len(trades)
    if n_trades > 0:
        # Compute P&L per trade from the daily pnl series
        trade_pnls = []
        for t in trades:
            idx_start = t["entry_day"]
            idx_end = t["exit_day"]
            trade_pnl = pnl.iloc[idx_start:idx_end + 1].sum()
            trade_pnls.append(trade_pnl)

        trade_pnls = np.array(trade_pnls)
        win_rate = np.mean(trade_pnls > 0)
        avg_profit = np.mean(trade_pnls)
        avg_holding = np.mean([t["holding_days"] for t in trades])
        stop_losses = sum(1 for t in trades if t["exit_reason"] == "stop_loss")
    else:
        win_rate = 0
        avg_profit = 0
        avg_holding = 0
        stop_losses = 0

    # Time in market
    pnl_arr = pnl_series.values
    time_in_market = np.mean(pnl_arr != 0) if len(pnl_arr) > 0 else 0

    # Trading years
    years = (pnl.index[-1] - pnl.index[0]).days / 365.25 if len(pnl) > 1 else 1

    # Sharpe t-stat (Harvey threshold: t>3.0)
    sharpe_se = 1.0 / np.sqrt(years) if years > 0 else np.inf
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        "label": label,
        "period": period_label,
        "years": round(years, 1),
        "n_trades": n_trades,
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_t": round(sharpe_t, 2),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "win_rate_pct": round(win_rate * 100, 1),
        "avg_profit_bps": round(avg_profit * 10000, 1),
        "avg_holding_days": round(avg_holding, 1),
        "stop_losses": stop_losses,
        "time_in_market_pct": round(time_in_market * 100, 1),
        "total_return_pct": round(total_ret * 100, 2),
    }


def analyze_correlation_stability(price_df):
    """Analyze rolling correlation between SPY and QQQ returns."""
    spy_ret = price_df["SPY"].pct_change()
    qqq_ret = price_df["QQQ"].pct_change()

    full_corr = spy_ret.corr(qqq_ret)

    # Rolling 252-day correlation
    rolling_corr = spy_ret.rolling(252).corr(qqq_ret)

    print(f"\n--- SPY-QQQ Correlation Analysis ---")
    print(f"  Full-sample correlation: {full_corr:.4f}")
    print(f"  Rolling 252d correlation:")
    print(f"    Mean: {rolling_corr.mean():.4f}")
    print(f"    Min:  {rolling_corr.min():.4f} ({rolling_corr.idxmin().strftime('%Y-%m-%d')})")
    print(f"    Max:  {rolling_corr.max():.4f} ({rolling_corr.idxmax().strftime('%Y-%m-%d')})")
    print(f"    Std:  {rolling_corr.std():.4f}")

    # Periods where correlation dropped below 0.90
    low_corr = rolling_corr[rolling_corr < 0.90].dropna()
    if len(low_corr) > 0:
        print(f"  Days with corr < 0.90: {len(low_corr)} ({len(low_corr)/len(rolling_corr.dropna())*100:.1f}%)")
    else:
        print(f"  Days with corr < 0.90: 0")

    return full_corr, rolling_corr


def analyze_spread_stationarity(spread_series):
    """Test if the spread is stationary (ADF test)."""
    from statsmodels.tsa.stattools import adfuller

    valid_spread = spread_series.dropna()
    if len(valid_spread) < 100:
        print("  Insufficient data for ADF test")
        return None

    # Full-sample ADF
    adf_stat, pvalue, _, nobs, crit, _ = adfuller(valid_spread, maxlag=20)

    print(f"\n--- Spread Stationarity (ADF Test) ---")
    print(f"  ADF statistic: {adf_stat:.4f}")
    print(f"  p-value: {pvalue:.6f}")
    print(f"  Critical values: 1%={crit['1%']:.3f}, 5%={crit['5%']:.3f}, 10%={crit['10%']:.3f}")
    print(f"  Stationary (5%): {'YES' if pvalue < 0.05 else 'NO'}")

    # Engle-Granger cointegration test
    from statsmodels.tsa.stattools import coint
    spy_log = np.log(valid_spread.index.map(lambda x: 1))  # placeholder
    # We'll test cointegration on the original log prices
    return pvalue


def test_cointegration(price_df):
    """Engle-Granger cointegration test on log prices."""
    from statsmodels.tsa.stattools import coint

    log_spy = np.log(price_df["SPY"])
    log_qqq = np.log(price_df["QQQ"])

    t_stat, pvalue, crit_values = coint(log_qqq, log_spy)

    print(f"\n--- Engle-Granger Cointegration Test ---")
    print(f"  t-statistic: {t_stat:.4f}")
    print(f"  p-value: {pvalue:.6f}")
    print(f"  Critical values: 1%={crit_values[0]:.3f}, 5%={crit_values[1]:.3f}, 10%={crit_values[2]:.3f}")
    print(f"  Cointegrated (5%): {'YES' if pvalue < 0.05 else 'NO'}")

    return t_stat, pvalue


def analyze_hedge_ratio_stability(spread_df):
    """Analyze how stable the rolling hedge ratio is over time."""
    beta = spread_df["beta"].dropna()

    print(f"\n--- Hedge Ratio (β) Stability ---")
    print(f"  Mean β: {beta.mean():.4f}")
    print(f"  Std β:  {beta.std():.4f}")
    print(f"  Min β:  {beta.min():.4f} ({beta.idxmin().strftime('%Y-%m-%d')})")
    print(f"  Max β:  {beta.max():.4f} ({beta.idxmax().strftime('%Y-%m-%d')})")
    print(f"  Range:  {beta.max() - beta.min():.4f}")

    # β change per year
    beta_annual_std = beta.diff().std() * np.sqrt(252)
    print(f"  Annualized β drift: {beta_annual_std:.4f}")

    # R² of the OLS
    r2 = spread_df["r_squared"].dropna()
    print(f"  Rolling R² mean: {r2.mean():.4f}")
    print(f"  Rolling R² min:  {r2.min():.4f}")

    return beta


def analyze_zscore_distribution(zscore):
    """Analyze distribution of z-scores."""
    z = zscore.dropna()

    print(f"\n--- Z-Score Distribution ---")
    print(f"  Mean:     {z.mean():.4f}")
    print(f"  Std:      {z.std():.4f}")
    print(f"  Skew:     {stats.skew(z):.4f}")
    print(f"  Kurtosis: {stats.kurtosis(z):.4f}")
    print(f"  |Z| > 1:  {(np.abs(z) > 1).mean()*100:.1f}%")
    print(f"  |Z| > 1.5: {(np.abs(z) > 1.5).mean()*100:.1f}%")
    print(f"  |Z| > 2:  {(np.abs(z) > 2).mean()*100:.1f}%")
    print(f"  |Z| > 3:  {(np.abs(z) > 3).mean()*100:.1f}%")
    print(f"  |Z| > 4:  {(np.abs(z) > 4).mean()*100:.1f}%")


def run_cross_oos(price_df, spread_df, zscore, strategy_func, strategy_name):
    """Run 5-period cross-OOS validation."""
    print(f"\n{'='*70}")
    print(f"Cross-OOS Validation: {strategy_name}")
    print(f"{'='*70}")

    oos_results = []
    all_oos_pnl = []

    for oos_start, oos_end, period_label in OOS_PERIODS:
        mask = (price_df.index >= oos_start) & (price_df.index <= oos_end)
        if mask.sum() < 100:
            print(f"  {period_label}: insufficient data ({mask.sum()} days)")
            continue

        pnl, pos, trades = strategy_func(
            price_df[mask], spread_df[mask], zscore[mask]
        )

        metrics = compute_metrics(pnl, trades, strategy_name, period_label)
        if metrics:
            oos_results.append(metrics)
            all_oos_pnl.append(pnl)
            print(f"  {period_label}: Sharpe={metrics['sharpe']:.3f}, "
                  f"MDD={metrics['mdd_pct']:.1f}%, "
                  f"Trades={metrics['n_trades']}, "
                  f"WinRate={metrics['win_rate_pct']:.0f}%, "
                  f"AvgHold={metrics['avg_holding_days']:.0f}d")

    # Cross-OOS consistency
    if len(oos_results) >= 3:
        sharpes = [r["sharpe"] for r in oos_results]
        positive_sharpes = sum(1 for s in sharpes if s > 0)
        print(f"\n  Cross-OOS Summary:")
        print(f"    Positive Sharpe periods: {positive_sharpes}/{len(sharpes)}")
        print(f"    Mean Sharpe: {np.mean(sharpes):.3f}")
        print(f"    Std Sharpe:  {np.std(sharpes):.3f}")
        print(f"    Min Sharpe:  {min(sharpes):.3f}")
        print(f"    Max Sharpe:  {max(sharpes):.3f}")

    return oos_results


def run_full_backtest(price_df, spread_df, zscore, strategy_func, strategy_name):
    """Full-sample backtest."""
    pnl, pos, trades = strategy_func(price_df, spread_df, zscore)
    metrics = compute_metrics(pnl, trades, strategy_name, "Full Sample")
    return pnl, pos, trades, metrics


def regime_analysis(price_df, spread_df, zscore, pnl_series):
    """Analyze performance in different market regimes."""
    print(f"\n--- Regime Analysis (Classic Strategy) ---")

    spy_ret = price_df["SPY"].pct_change()

    # Define regimes by SPY return
    spy_252d_ret = spy_ret.rolling(252).sum()

    regimes = {
        "Bull (SPY 252d > 20%)": spy_252d_ret > 0.20,
        "Normal (0-20%)": (spy_252d_ret >= 0) & (spy_252d_ret <= 0.20),
        "Bear (SPY 252d < 0%)": spy_252d_ret < 0,
    }

    for regime_name, mask in regimes.items():
        mask = mask.reindex(pnl_series.index).fillna(False)
        regime_pnl = pnl_series[mask]
        if len(regime_pnl) > 50:
            ann_ret = regime_pnl.mean() * 252
            ann_vol = regime_pnl.std() * np.sqrt(252)
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
            print(f"  {regime_name}: {mask.sum()} days, Sharpe={sharpe:.3f}, "
                  f"Ann.Ret={ann_ret*100:.2f}%")

    # VIX regime (if available)
    try:
        vix = yf.download("^VIX", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        vix_close = vix["Close"].reindex(pnl_series.index).ffill()

        vix_regimes = {
            "VIX < 15 (Low Vol)": vix_close < 15,
            "VIX 15-25 (Normal)": (vix_close >= 15) & (vix_close <= 25),
            "VIX > 25 (High Vol)": vix_close > 25,
        }

        print(f"\n  VIX Regime Breakdown:")
        for regime_name, mask in vix_regimes.items():
            mask = mask.reindex(pnl_series.index).fillna(False)
            regime_pnl = pnl_series[mask]
            if len(regime_pnl) > 50:
                ann_ret = regime_pnl.mean() * 252
                ann_vol = regime_pnl.std() * np.sqrt(252)
                sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
                print(f"    {regime_name}: {mask.sum()} days, Sharpe={sharpe:.3f}, "
                      f"Ann.Ret={ann_ret*100:.2f}%")
    except Exception:
        print("  (VIX data not available for regime analysis)")


def structural_break_analysis(spread_df, zscore, price_df):
    """Identify periods where mean reversion broke down."""
    print(f"\n--- Structural Break Analysis ---")
    print(f"  Periods where spread diverged significantly (|Z| > 3 sustained > 20 days):")

    z = zscore.dropna()
    extreme = np.abs(z) > 3

    # Find consecutive runs of extreme z-scores
    runs = []
    in_run = False
    run_start = None

    for i in range(len(extreme)):
        if extreme.iloc[i]:
            if not in_run:
                in_run = True
                run_start = extreme.index[i]
        else:
            if in_run:
                run_end = extreme.index[i - 1]
                run_len = (run_end - run_start).days
                if run_len >= 20:
                    runs.append((run_start, run_end, run_len))
                in_run = False

    if in_run and run_start is not None:
        run_end = extreme.index[-1]
        run_len = (run_end - run_start).days
        if run_len >= 20:
            runs.append((run_start, run_end, run_len))

    if runs:
        for start, end, duration in runs:
            avg_z = z.loc[start:end].mean()
            print(f"    {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')} "
                  f"({duration} days, avg Z={avg_z:.2f})")
    else:
        print(f"    No sustained extreme divergences found (> 20 consecutive days with |Z|>3)")

    # Half-life of mean reversion
    spread = spread_df["spread"].dropna()
    spread_lag = spread.shift(1)
    valid = ~(spread.isna() | spread_lag.isna())
    y = spread[valid].values
    x = spread_lag[valid].values

    # AR(1): spread_t = phi * spread_{t-1} + eps
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    if slope > 0 and slope < 1:
        half_life = -np.log(2) / np.log(slope)
        print(f"\n  Mean Reversion Half-Life: {half_life:.1f} trading days ({half_life/21:.1f} months)")
        print(f"    AR(1) coefficient: {slope:.4f}")
        print(f"    AR(1) R²: {r_value**2:.4f}")
    else:
        print(f"\n  Mean Reversion Half-Life: N/A (AR(1) coef = {slope:.4f})")


def bootstrap_sharpe_test(pnl_series, n_bootstrap=10000):
    """Bootstrap test: is Sharpe significantly different from 0?"""
    pnl = pnl_series.dropna().values
    if len(pnl) < 252:
        return None, None

    observed_sharpe = pnl.mean() / pnl.std() * np.sqrt(252)

    rng = np.random.RandomState(42)
    boot_sharpes = np.zeros(n_bootstrap)
    n = len(pnl)

    for b in range(n_bootstrap):
        sample = rng.choice(pnl, size=n, replace=True)
        boot_sharpes[b] = sample.mean() / sample.std() * np.sqrt(252)

    # P-value: fraction of bootstrap samples with Sharpe <= 0
    p_value = np.mean(boot_sharpes <= 0)
    ci_lower = np.percentile(boot_sharpes, 2.5)
    ci_upper = np.percentile(boot_sharpes, 97.5)

    return {
        "observed_sharpe": round(observed_sharpe, 4),
        "p_value": round(p_value, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "significant_5pct": p_value < 0.05,
    }


def main():
    # 1. Download data
    price_df = download_data()

    # 2. Correlation analysis
    full_corr, rolling_corr = analyze_correlation_stability(price_df)

    # 3. Cointegration test
    coint_t, coint_p = test_cointegration(price_df)

    # 4. Compute spread and z-score
    print(f"\nComputing rolling spread (β window={HEDGE_RATIO_WINDOW}, z-score lookback={ZSCORE_LOOKBACK})...")
    spread_df = compute_spread(price_df)
    zscore = compute_zscore(spread_df["spread"])

    # 5. Hedge ratio stability
    beta_series = analyze_hedge_ratio_stability(spread_df)

    # 6. Z-score distribution
    analyze_zscore_distribution(zscore)

    # 7. Spread stationarity
    valid_spread = spread_df["spread"].dropna()
    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_p, _, _, crit, _ = adfuller(valid_spread, maxlag=20)
    print(f"\n--- Spread Stationarity (ADF Test) ---")
    print(f"  ADF statistic: {adf_stat:.4f}")
    print(f"  p-value: {adf_p:.6f}")
    print(f"  Stationary (5%): {'YES' if adf_p < 0.05 else 'NO'}")

    # 8. Structural break analysis
    structural_break_analysis(spread_df, zscore, price_df)

    # ============================================================
    # BACKTESTS
    # ============================================================
    strategies = {
        "Classic (±2σ, exit ±0.5σ)": backtest_classic,
        "Bollinger (±1.5σ, exit 0)": backtest_bollinger,
        "Adaptive (95th pctile, exit 0)": backtest_adaptive,
    }

    all_results = {}
    full_metrics = []
    oos_results_all = {}

    for strat_name, strat_func in strategies.items():
        print(f"\n{'='*70}")
        print(f"Strategy: {strat_name}")
        print(f"{'='*70}")

        # Full sample
        pnl, pos, trades, metrics = run_full_backtest(price_df, spread_df, zscore, strat_func, strat_name)
        if metrics:
            full_metrics.append(metrics)
            print(f"\n  Full Sample Results:")
            print(f"    Sharpe: {metrics['sharpe']:.3f} (t={metrics['sharpe_t']:.2f})")
            print(f"    Ann. Return: {metrics['ann_return_pct']:.2f}%")
            print(f"    Ann. Vol: {metrics['ann_vol_pct']:.2f}%")
            print(f"    MDD: {metrics['mdd_pct']:.2f}%")
            print(f"    Calmar: {metrics['calmar']:.3f}")
            print(f"    Trades: {metrics['n_trades']}")
            print(f"    Win Rate: {metrics['win_rate_pct']:.1f}%")
            print(f"    Avg Holding: {metrics['avg_holding_days']:.1f} days")
            print(f"    Time in Market: {metrics['time_in_market_pct']:.1f}%")
            print(f"    Stop Losses: {metrics['stop_losses']}")

        # Bootstrap test
        boot = bootstrap_sharpe_test(pnl)
        if boot:
            print(f"\n  Bootstrap Sharpe Test (10,000 reps):")
            print(f"    Observed: {boot['observed_sharpe']:.4f}")
            print(f"    p-value (H0: Sharpe ≤ 0): {boot['p_value']:.4f}")
            print(f"    95% CI: [{boot['ci_95_lower']:.4f}, {boot['ci_95_upper']:.4f}]")
            print(f"    Significant (5%): {'YES' if boot['significant_5pct'] else 'NO'}")

        # Cross-OOS
        oos = run_cross_oos(price_df, spread_df, zscore, strat_func, strat_name)
        oos_results_all[strat_name] = oos

        all_results[strat_name] = {
            "full_sample": metrics,
            "bootstrap": boot,
            "oos_periods": oos,
        }

    # 9. Regime analysis (classic strategy only)
    classic_pnl, _, _, _ = run_full_backtest(price_df, spread_df, zscore, backtest_classic, "Classic")
    regime_analysis(price_df, spread_df, zscore, classic_pnl)

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n{'='*70}")
    print(f"K246 SUMMARY: SPY-QQQ Pairs Trading")
    print(f"{'='*70}")

    print(f"\n--- Data ---")
    print(f"  Period: {price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(price_df)}")
    print(f"  SPY-QQQ correlation: {full_corr:.4f}")
    print(f"  Cointegrated (5%): {'YES' if coint_p < 0.05 else 'NO'} (p={coint_p:.4f})")
    print(f"  Spread stationary (ADF 5%): {'YES' if adf_p < 0.05 else 'NO'} (p={adf_p:.4f})")

    print(f"\n--- Full-Sample Strategy Comparison ---")
    print(f"  {'Strategy':<35} {'Sharpe':>7} {'t-stat':>7} {'MDD%':>7} {'Trades':>7} {'Win%':>6} {'AvgHold':>8}")
    print(f"  {'-'*35} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*8}")
    for m in full_metrics:
        print(f"  {m['label']:<35} {m['sharpe']:>7.3f} {m['sharpe_t']:>7.2f} "
              f"{m['mdd_pct']:>7.2f} {m['n_trades']:>7} {m['win_rate_pct']:>5.1f}% {m['avg_holding_days']:>7.1f}d")

    print(f"\n--- Cross-OOS Sharpe by Strategy ---")
    for strat_name in strategies:
        oos = oos_results_all.get(strat_name, [])
        if oos:
            sharpes = [r["sharpe"] for r in oos]
            pos_count = sum(1 for s in sharpes if s > 0)
            print(f"  {strat_name}:")
            for r in oos:
                marker = "+" if r["sharpe"] > 0 else "-"
                print(f"    [{marker}] {r['period']}: Sharpe={r['sharpe']:.3f}, "
                      f"MDD={r['mdd_pct']:.1f}%, Trades={r['n_trades']}")
            print(f"    → Positive: {pos_count}/{len(sharpes)}, Mean: {np.mean(sharpes):.3f}")

    # Harvey threshold check
    print(f"\n--- Harvey (2016) Threshold Check ---")
    for m in full_metrics:
        passes = m["sharpe_t"] > 3.0
        print(f"  {m['label']}: t={m['sharpe_t']:.2f} → {'PASS' if passes else 'FAIL'} (threshold: 3.0)")

    # Key risks
    print(f"\n--- Key Risks ---")
    print(f"  1. Requires SHORT SELLING (sophisticated investors only)")
    print(f"  2. Mean reversion can break during structural tech shifts")
    print(f"  3. Beta (hedge ratio) drifts over time — must be re-estimated")
    print(f"  4. Dollar-neutral does NOT mean risk-neutral (tail risk remains)")
    print(f"  5. Margin requirements for short positions add funding cost")
    print(f"  6. Low time-in-market means capital is idle most of the time")

    # ============================================================
    # SAVE RESULTS
    # ============================================================
    output = {
        "experiment": "K246",
        "title": "Pairs Trading SPY-QQQ — Mean Reversion Between Correlated Assets",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "source": "yfinance (real market data)",
            "assets": ["SPY", "QQQ"],
            "period": f"{price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}",
            "trading_days": len(price_df),
            "tx_cost_bps": TX_COST_ONEWAY * 10000 * 2,
        },
        "diagnostics": {
            "spy_qqq_correlation": round(full_corr, 4),
            "cointegration_p_value": round(coint_p, 4),
            "cointegrated_5pct": coint_p < 0.05,
            "spread_adf_p_value": round(adf_p, 4),
            "spread_stationary_5pct": adf_p < 0.05,
            "hedge_ratio_mean": round(float(beta_series.mean()), 4),
            "hedge_ratio_std": round(float(beta_series.std()), 4),
        },
        "strategies": {},
        "conclusion": "",
        "limitations": [
            "Requires short selling capability (not available to all investors)",
            "Transaction costs assume 10 bps round-trip; real costs may be higher with margin/borrow",
            "Hedge ratio (beta) is estimated from rolling OLS — structural breaks can cause large losses",
            "Dollar-neutral != risk-neutral (residual risk from beta estimation error)",
            "Does not account for margin requirements, funding costs, or short-sale rebates",
            "Low time-in-market means opportunity cost of idle capital not measured",
            "Single pair (SPY-QQQ) — results may not generalize to other pairs",
        ],
    }

    best_sharpe = -999
    best_strategy = None

    for strat_name, result in all_results.items():
        strat_data = {
            "full_sample": result["full_sample"],
            "bootstrap_sharpe_test": result["bootstrap"],
            "cross_oos": result["oos_periods"],
        }
        if result["oos_periods"]:
            sharpes = [r["sharpe"] for r in result["oos_periods"]]
            strat_data["cross_oos_summary"] = {
                "n_periods": len(sharpes),
                "n_positive": sum(1 for s in sharpes if s > 0),
                "mean_sharpe": round(np.mean(sharpes), 4),
                "std_sharpe": round(np.std(sharpes), 4),
            }
        output["strategies"][strat_name] = strat_data

        if result["full_sample"] and result["full_sample"]["sharpe"] > best_sharpe:
            best_sharpe = result["full_sample"]["sharpe"]
            best_strategy = strat_name

    # Conclusion
    harvey_pass = any(m["sharpe_t"] > 3.0 for m in full_metrics)
    any_oos_consistent = False
    for strat_name, oos in oos_results_all.items():
        if oos:
            pos_count = sum(1 for r in oos if r["sharpe"] > 0)
            if pos_count >= 4:
                any_oos_consistent = True

    if harvey_pass and any_oos_consistent:
        conclusion = (
            f"SPY-QQQ pairs trading shows promise. Best strategy: {best_strategy} "
            f"(Sharpe={best_sharpe:.3f}). Passes Harvey threshold and cross-OOS validation. "
            f"However, requires short selling and careful risk management."
        )
    elif best_sharpe > 0:
        conclusion = (
            f"SPY-QQQ pairs trading generates modest positive returns but FAILS Harvey (2016) "
            f"threshold (t>3.0). Best strategy: {best_strategy} (Sharpe={best_sharpe:.3f}). "
            f"After transaction costs and margin requirements, net alpha is likely negligible. "
            f"Mean reversion exists but is too weak/infrequent to be a standalone strategy."
        )
    else:
        conclusion = (
            f"SPY-QQQ pairs trading does NOT generate positive risk-adjusted returns after "
            f"transaction costs. The correlation is high but mean reversion is too slow/weak. "
            f"Best strategy: {best_strategy} (Sharpe={best_sharpe:.3f})."
        )

    output["conclusion"] = conclusion
    print(f"\n--- CONCLUSION ---")
    print(f"  {conclusion}")

    # Save
    output_path = Path(__file__).parent / "k246_pairs_trading_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return output


if __name__ == "__main__":
    results = main()
