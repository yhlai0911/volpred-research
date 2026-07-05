#!/usr/bin/env python3
"""
K506: EWT-0050 Vol Spread Strategy — Cross-OOS Validation
==========================================================
Background:
  K505: VT+VolSpread combo Sharpe=0.698, MDD=-25% (best Taiwan strategy candidate).
  But fails Harvey (t=2.49) and needs cross-OOS validation before deployment.

Strategy:
  Base: weight = min(8.63 / VIX, 1.0)  [Taiwan VT, Q1 finding]
  Vol Spread Adjustment:
    ratio = EWT_realized_vol / TW50_realized_vol (21-day rolling)
    if ratio > 1.2 → weight *= 0.5  (reduce: EWT more volatile = international stress)
    if ratio < 0.8 → weight *= 1.2  (increase: TW50 stable relative to EWT)
    else: no adjustment
  Monthly rebalancing (K499: monthly optimal for high TX cost)
  TX: side-aware K625 schedule (buy 4.275bp, sell 14.275bp; round-trip 18.55bp)
  Cash earns 1.5% annual (Taiwan short-term deposit proxy)

Comparison:
  1. Buy & Hold 0050.TW
  2. 8.63/VIX VT (existing strategy)
  3. VT + VolSpread (K505 candidate)

5 Cross-OOS Periods:
  1. 2012-2013 (post-GFC recovery)
  2. 2014-2015 (China fears, TW slow growth)
  3. 2016-2017 (Trump election, tech rally)
  4. 2018-2019 (trade war, yield inversion)
  5. 2020-2021 (COVID crash + recovery)
  (K505's 2022-2025 is the 6th, already known good)

Evaluation:
  - Net Sharpe (after TX), MDD, Calmar, Annual Return
  - DM test: VT+VS vs VT alone (per-period and pooled)
  - ≥4/5 OOS periods VT+VS beats VT → consider deployment
  - ≤2/5 → do NOT deploy

Data: repo-local cache / yfinance fallback (EWT, 0050.TW, ^VIX) — real market data
References:
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  - Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS
  - Bozovic (2024) "VIX-managed portfolios" IRFA
  - K499 (monthly rebalancing optimal), K505 (VT+VolSpread initial results)
  - Q1 (8.63/VIX for Taiwan = 12/(VIX×1.39))

Author: [提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

RESULTS_PATH = Path(__file__).parent / "k506_ewt_volspread_cross_oos_results.json"
EXPERIMENT_DIR = Path(__file__).parent
DATA_DIR = EXPERIMENT_DIR / "data"
LOCAL_PRICE_CACHE_DB = Path(__file__).resolve().parents[2] / "data" / "cache" / "price_cache.db"
K506_EWT_SNAPSHOT_CSV = DATA_DIR / "EWT_2010_2021_yfinance.csv"
K1090_EWT_FALLBACK_CSV = Path(__file__).resolve().parents[1] / "k1090" / "data" / "EWT.csv"

# ============================================================
# Configuration
# ============================================================
# Corrected K625 cost schedule:
#   buy  = commission only = 0.04275%
#   sell = commission + securities transaction tax = 0.04275% + 0.10%
# The old K506 rerun applied the full round-trip cost to every abs(delta weight).
# This hardening uses side-aware per-dollar-traded costs as the primary tradable
# specification, while still reporting the round-trip total for provenance.
TX_BUY_ONEWAY = 0.0004275
TX_SELL_ONEWAY = 0.0014275
TX_ROUNDTRIP = TX_BUY_ONEWAY + TX_SELL_ONEWAY
CASH_RATE_ANNUAL = 0.015     # 1.5% Taiwan short-term deposit
VT_SCALAR = 8.63             # 12/(1.39) adjusted for VIXTWN
MAX_WEIGHT = 1.0             # cap at 100% equity
VOL_WINDOW = 21              # 21-day rolling vol for spread
RATIO_HIGH = 1.2             # reduce when ratio > 1.2
RATIO_LOW = 0.8              # increase when ratio < 0.8
ADJUST_DOWN = 0.5            # multiplier when high spread
ADJUST_UP = 1.2              # multiplier when low spread
TRADING_DAYS = 252

OOS_PERIODS = [
    ("2012-01-01", "2013-12-31", "2012-2013"),
    ("2014-01-01", "2015-12-31", "2014-2015"),
    ("2016-01-01", "2017-12-31", "2016-2017"),
    ("2018-01-01", "2019-12-31", "2018-2019"),
    ("2020-01-01", "2021-12-31", "2020-2021"),
]

# Need IS data before OOS for vol computation
DATA_START = "2010-01-01"   # 2yr buffer before first OOS
DATA_END = "2022-01-01"     # covers through 2021


print("=" * 80)
print("K506: EWT-0050 Vol Spread Strategy — Cross-OOS Validation")
print("=" * 80)
t0 = time.time()

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1/5] Loading data...")

tickers = {
    "EWT": "EWT",           # iShares MSCI Taiwan ETF (USD)
    "TW50": "0050.TW",      # Yuanta 0050 ETF (TWD)
    "VIX": "^VIX",          # CBOE VIX
}

def load_from_sqlite_cache(ticker):
    """Load OHLC from the shared local price cache."""
    if not LOCAL_PRICE_CACHE_DB.exists():
        return None

    query = (
        "SELECT date, open, high, low, close, volume, adj_close "
        "FROM price_data WHERE ticker = ? AND date >= ? AND date < ? ORDER BY date"
    )
    with sqlite3.connect(LOCAL_PRICE_CACHE_DB) as conn:
        df = pd.read_sql_query(query, conn, params=(ticker, DATA_START, DATA_END))
    if df.empty:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.index.name = None
    return df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "adj_close": "Adj Close",
        }
    )


def load_ewt_csv(path):
    """Load a repo-local EWT CSV snapshot if it covers the required range."""
    if not path.exists():
        return None

    df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    df.index.name = None
    start_required = pd.Timestamp(DATA_START) + pd.Timedelta(days=7)
    end_required = pd.Timestamp(DATA_END) - pd.Timedelta(days=1)
    if df.index.min() > start_required or df.index.max() < end_required:
        return None
    return df.sort_index()


def load_market_data(name, ticker):
    """Prefer deterministic local caches; fall back to yfinance only when needed."""
    if ticker in {"0050.TW", "^VIX"}:
        cached = load_from_sqlite_cache(ticker)
        if cached is not None and not cached.empty:
            return cached, f"sqlite:{LOCAL_PRICE_CACHE_DB.name}"

    if ticker == "EWT":
        cached = load_ewt_csv(K506_EWT_SNAPSHOT_CSV)
        if cached is not None and not cached.empty:
            return cached, f"csv:{K506_EWT_SNAPSHOT_CSV.relative_to(Path(__file__).resolve().parents[2])}"

        cached = load_ewt_csv(K1090_EWT_FALLBACK_CSV)
        if cached is not None and not cached.empty:
            return cached, f"csv:{K1090_EWT_FALLBACK_CSV.relative_to(Path(__file__).resolve().parents[2])}"

    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        return None, "download_failed"
    if ticker == "EWT":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(K506_EWT_SNAPSHOT_CSV, index_label="Date")
        return df, f"yfinance_saved:{K506_EWT_SNAPSHOT_CSV.relative_to(Path(__file__).resolve().parents[2])}"
    return df, "yfinance"


raw = {}
data_sources = {}
for name, ticker in tickers.items():
    df, source = load_market_data(name, ticker)
    if df is None or df.empty:
        raise RuntimeError(
            f"Missing local data for {ticker}. "
            f"EWT cannot be re-downloaded in the current restricted-network environment."
        )
    raw[name] = df
    data_sources[name] = source
    print(f"  {name} ({ticker}) [{source}]: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 2. DATA PREPARATION (vectorized)
# ============================================================
print("\n[2/5] Preparing data...")

# Adjusted price helpers. 0050.TW has a 2014 split in this sample; strategy P&L
# and realized-vol inputs must use adjusted close/open rather than raw close.
def adjusted_close(df: pd.DataFrame) -> pd.Series:
    if "Adj Close" in df and df["Adj Close"].notna().any():
        return df["Adj Close"].squeeze()
    return df["Close"].squeeze()


def adjusted_open(df: pd.DataFrame) -> pd.Series:
    if {"Open", "Close", "Adj Close"}.issubset(df.columns) and df["Adj Close"].notna().any():
        factor = df["Adj Close"] / df["Close"]
        return (df["Open"] * factor).squeeze()
    return df["Open"].squeeze()


def repair_discrete_price_splits(open_series: pd.Series, close_series: pd.Series):
    """Repair split-like jumps that remain in the cache's adjusted prices."""
    repaired_open = open_series.astype(float).copy()
    repaired_close = close_series.astype(float).copy()
    raw_ratios = (close_series / close_series.shift(1)).dropna()
    split_events = []

    for date, ratio in raw_ratios.items():
        ratio = float(ratio)
        if ratio <= 0:
            continue

        prior_scale = None
        split_label = None
        if ratio < 0.5:
            divisor = int(round(1 / ratio))
            implied_ratio = 1 / divisor if divisor else np.nan
            if divisor >= 2 and abs(ratio / implied_ratio - 1) <= 0.08:
                prior_scale = implied_ratio
                split_label = f"{divisor}-for-1"
        elif ratio > 2:
            multiplier = int(round(ratio))
            if multiplier >= 2 and abs(ratio / multiplier - 1) <= 0.08:
                prior_scale = float(multiplier)
                split_label = f"1-for-{multiplier} reverse"

        if prior_scale is None:
            continue

        mask = repaired_close.index < date
        repaired_close.loc[mask] *= prior_scale
        repaired_open.loc[mask] *= prior_scale
        split_events.append({
            "date": pd.Timestamp(date).date().isoformat(),
            "raw_close_ratio": round(ratio, 6),
            "prior_price_scale": prior_scale,
            "detected_split": split_label,
        })

    return repaired_open, repaired_close, split_events


def asof_to_tw_calendar(signal: pd.Series, tw_dates: pd.DatetimeIndex, name: str) -> pd.Series:
    """Latest signal strictly before each Taiwan trading date.

    A US close labelled date D is known before Taiwan opens on D+1, not before
    Taiwan opens on D. `allow_exact_matches=False` prevents same-calendar-day
    US closes from leaking into that Taiwan day, while still allowing US-only
    holiday observations between two Taiwan sessions to update the next TW open.
    """
    left = pd.DataFrame({"tw_date": pd.DatetimeIndex(tw_dates).sort_values()})
    right = signal.dropna().sort_index().rename(name).reset_index()
    right.columns = ["signal_date", name]
    left["tw_date"] = pd.to_datetime(left["tw_date"]).astype("datetime64[ns]")
    right["signal_date"] = pd.to_datetime(right["signal_date"]).astype("datetime64[ns]")
    merged = pd.merge_asof(
        left,
        right,
        left_on="tw_date",
        right_on="signal_date",
        direction="backward",
        allow_exact_matches=False,
    ).set_index("tw_date")
    out = merged[name]
    out.index.name = None
    return out


ewt_close = adjusted_close(raw["EWT"])
tw50_close_base = adjusted_close(raw["TW50"])
tw50_open_base = adjusted_open(raw["TW50"])
tw50_open, tw50_close, tw50_split_adjustments = repair_discrete_price_splits(tw50_open_base, tw50_close_base)
if tw50_split_adjustments:
    print(f"  Split-like 0050.TW adjustments: {tw50_split_adjustments}")
vix_close = raw["VIX"]["Close"].squeeze()

# Native-calendar returns and volatility inputs.
ewt_logret = np.log(ewt_close / ewt_close.shift(1))
ewt_vol = ewt_logret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
tw50_logret = np.log(tw50_close / tw50_close.shift(1))
tw50_vol_signal_native = tw50_logret.rolling(VOL_WINDOW).std().shift(1) * np.sqrt(TRADING_DAYS)

# Use TW50 trading calendar as base (strategy trades 0050.TW).
tw_dates = tw50_close.dropna().index
ewt_vol_on_tw = asof_to_tw_calendar(ewt_vol, tw_dates, "ewt_vol")
vix_on_tw = asof_to_tw_calendar(vix_close, tw_dates, "vix_signal")

data = pd.DataFrame({
    "tw50_close": tw50_close.reindex(tw_dates),
    "tw50_open": tw50_open.reindex(tw_dates),
    "tw50_vol_signal": tw50_vol_signal_native.reindex(tw_dates),
    "ewt_vol_signal": ewt_vol_on_tw,
    "vix_signal": vix_on_tw,
})

# Tradable return decomposition. On a rebalance day, the old weight earns
# close(t-1)->open(t); the newly chosen weight earns open(t)->close(t).
data["tw50_ret"] = data["tw50_close"] / data["tw50_close"].shift(1) - 1
data["tw50_overnight_ret"] = data["tw50_open"] / data["tw50_close"].shift(1) - 1
data["tw50_open_to_close_ret"] = data["tw50_close"] / data["tw50_open"] - 1
data["vol_ratio_signal"] = data["ewt_vol_signal"] / data["tw50_vol_signal"]

# Drop NaN from rolling windows, strict as-of signals, and return construction.
data = data.dropna()

print(f"  Final aligned dataset: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  Vol ratio signal stats: mean={data['vol_ratio_signal'].mean():.3f}, "
      f"std={data['vol_ratio_signal'].std():.3f}, "
      f"min={data['vol_ratio_signal'].min():.3f}, max={data['vol_ratio_signal'].max():.3f}")
print(f"  Ratio > {RATIO_HIGH}: {(data['vol_ratio_signal'] > RATIO_HIGH).mean()*100:.1f}% of days")
print(f"  Ratio < {RATIO_LOW}: {(data['vol_ratio_signal'] < RATIO_LOW).mean()*100:.1f}% of days")

# ============================================================
# 3. STRATEGY FUNCTIONS (vectorized)
# ============================================================

def get_month_starts(dates):
    """Return numpy boolean array for first trading day of each month."""
    months = pd.Series(dates.to_period('M'), index=dates)
    result = (months != months.shift(1)).values.copy()
    result[0] = True  # First day is always a rebalance day
    return result


def backtest_buyhold(ret_series):
    """Buy & Hold: 100% equity, no rebalancing."""
    cum = (1 + ret_series).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(ret_series) / TRADING_DAYS
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = ret_series.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(ann_ret / abs(mdd)) if mdd != 0 else 0,
        "total_ret": float(total_ret),
        "n_days": len(ret_series),
        "n_rebalances": 0,
        "tx_total_pct": 0.0,
        "daily_returns": ret_series,
    }


def backtest_vt(data_slice, use_volspread=False):
    """
    VT strategy with monthly rebalancing.
    If use_volspread: apply vol spread adjustment.
    """
    dates = data_slice.index
    tw50_ret = data_slice["tw50_ret"].values
    tw50_overnight_ret = data_slice["tw50_overnight_ret"].values
    tw50_open_to_close_ret = data_slice["tw50_open_to_close_ret"].values
    vix_signal = data_slice["vix_signal"].values
    vol_ratio_signal = data_slice["vol_ratio_signal"].values

    # Identify month starts for rebalancing
    month_starts = get_month_starts(dates)  # numpy boolean array

    n = len(dates)
    portfolio_ret = np.empty(n)
    daily_cash_ret = CASH_RATE_ANNUAL / TRADING_DAYS
    half_cash_ret = daily_cash_ret / 2

    # Track state
    current_weight = 0.0
    n_rebalances = 0
    tx_total = 0.0

    def transaction_cost(old_weight, new_weight):
        delta = new_weight - old_weight
        if delta > 0:
            return delta * TX_BUY_ONEWAY
        if delta < 0:
            return -delta * TX_SELL_ONEWAY
        return 0.0

    for i in range(n):
        # Check if rebalance day (first day or month start)
        if i == 0 or month_starts[i]:
            old_weight = current_weight

            # Old close-to-close position earns the overnight gap before the
            # opening trade can be executed.
            overnight_leg = (
                old_weight * tw50_overnight_ret[i]
                + (1 - old_weight) * half_cash_ret
            )
            if 1 + overnight_leg > 0:
                pretrade_weight = old_weight * (1 + tw50_overnight_ret[i]) / (1 + overnight_leg)
            else:
                pretrade_weight = old_weight

            # Compute target weight using only signals known before the Taiwan open.
            target_w = min(VT_SCALAR / vix_signal[i], MAX_WEIGHT) if vix_signal[i] > 0 else 0

            if use_volspread:
                r = vol_ratio_signal[i]
                if r > RATIO_HIGH:
                    target_w *= ADJUST_DOWN
                elif r < RATIO_LOW:
                    target_w *= ADJUST_UP
                target_w = min(target_w, MAX_WEIGHT)

            # Side-aware per-dollar-traded cost at the rebalance open.
            tx_cost = transaction_cost(pretrade_weight, target_w)
            tx_total += tx_cost

            n_rebalances += 1

            # New target earns only open-to-close on the rebalance day. Between
            # monthly rebalances, portfolio weights drift with asset returns.
            intraday_leg = (
                target_w * tw50_open_to_close_ret[i]
                + (1 - target_w) * half_cash_ret
            )
            day_ret = (1 + overnight_leg) * (1 - tx_cost) * (1 + intraday_leg) - 1
            if 1 + intraday_leg > 0:
                current_weight = target_w * (1 + tw50_open_to_close_ret[i]) / (1 + intraday_leg)
            else:
                current_weight = target_w
        else:
            # Normal day: no trade; close-to-close position drifts naturally.
            day_ret = current_weight * tw50_ret[i] + (1 - current_weight) * daily_cash_ret
            if 1 + day_ret > 0:
                current_weight = current_weight * (1 + tw50_ret[i]) / (1 + day_ret)

        portfolio_ret[i] = day_ret

    # Convert to series
    port_ret = pd.Series(portfolio_ret, index=dates)
    cum = (1 + port_ret).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = n / TRADING_DAYS
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(ann_ret / abs(mdd)) if mdd != 0 else 0,
        "total_ret": float(total_ret),
        "n_days": n,
        "n_rebalances": n_rebalances,
        "tx_total_pct": float(tx_total * 100),
        "daily_returns": port_ret,
    }


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    loss1, loss2: loss series (e.g., -daily_returns for comparing strategies).
    H0: equal predictive ability. Reject if |t| > threshold.
    Returns: (t_stat, p_value)
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # Newey-West type variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


def bonferroni_adjust(p_values):
    """Family-wise error rate control."""
    m = len(p_values)
    return [min(float(p) * m, 1.0) for p in p_values]


def bh_adjust(p_values):
    """Benjamini-Hochberg FDR control."""
    p_values = np.asarray(p_values, dtype=float)
    m = len(p_values)
    order = np.argsort(p_values)
    ranked = p_values[order]
    adjusted = np.empty(m)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        value = min(prev, ranked[i] * m / rank)
        adjusted[i] = value
        prev = value
    out = np.empty(m)
    out[order] = adjusted
    return [min(float(p), 1.0) for p in out]


# ============================================================
# 4. CROSS-OOS BACKTEST
# ============================================================
print("\n[3/5] Running cross-OOS backtests...")

all_results = {}
vt_wins = 0
vs_wins = 0
all_vt_returns = []
all_vs_returns = []
dm_tests = []

for oos_start, oos_end, label in OOS_PERIODS:
    print(f"\n  --- OOS Period: {label} ({oos_start} to {oos_end}) ---")

    # Slice data for this OOS period
    mask = (data.index >= oos_start) & (data.index <= oos_end)
    oos_data = data.loc[mask].copy()

    if len(oos_data) < 100:
        print(f"    ⚠️ Only {len(oos_data)} days — skipping (need >= 100)")
        continue

    print(f"    Trading days: {len(oos_data)}")
    print(f"    Vol ratio signal: mean={oos_data['vol_ratio_signal'].mean():.3f}, "
          f"std={oos_data['vol_ratio_signal'].std():.3f}")
    print(f"    VIX signal: mean={oos_data['vix_signal'].mean():.1f}, "
          f"min={oos_data['vix_signal'].min():.1f}, max={oos_data['vix_signal'].max():.1f}")

    # 1. Buy & Hold
    bh = backtest_buyhold(oos_data["tw50_ret"])

    # 2. VT only (8.63/VIX)
    vt = backtest_vt(oos_data, use_volspread=False)

    # 3. VT + VolSpread
    vs = backtest_vt(oos_data, use_volspread=True)

    # DM test: VT+VS vs VT (using negative returns as loss)
    # Positive t-stat means VT+VS has lower loss (= better)
    vt_loss = -vt["daily_returns"].values
    vs_loss = -vs["daily_returns"].values
    dm_t, dm_p = dm_test(vt_loss, vs_loss)

    # Collect for pooled test
    all_vt_returns.append(vt["daily_returns"])
    all_vs_returns.append(vs["daily_returns"])

    # Determine winner
    if vs["sharpe"] > vt["sharpe"]:
        vs_wins += 1
        winner = "VT+VS"
    else:
        vt_wins += 1
        winner = "VT"

    period_result = {
        "period": label,
        "n_days": len(oos_data),
        "vix_mean": round(oos_data["vix_signal"].mean(), 1),
        "vol_ratio_mean": round(oos_data["vol_ratio_signal"].mean(), 3),
        "vol_ratio_std": round(oos_data["vol_ratio_signal"].std(), 3),
        "pct_high_ratio": round((oos_data["vol_ratio_signal"] > RATIO_HIGH).mean() * 100, 1),
        "pct_low_ratio": round((oos_data["vol_ratio_signal"] < RATIO_LOW).mean() * 100, 1),
        "buy_hold": {
            "sharpe": round(bh["sharpe"], 4),
            "ann_ret_pct": round(bh["ann_ret"] * 100, 2),
            "mdd_pct": round(bh["mdd"] * 100, 2),
        },
        "vt_only": {
            "sharpe": round(vt["sharpe"], 4),
            "ann_ret_pct": round(vt["ann_ret"] * 100, 2),
            "ann_vol_pct": round(vt["ann_vol"] * 100, 2),
            "mdd_pct": round(vt["mdd"] * 100, 2),
            "calmar": round(vt["calmar"], 3),
            "n_rebalances": vt["n_rebalances"],
            "tx_total_pct": round(vt["tx_total_pct"], 3),
        },
        "vt_volspread": {
            "sharpe": round(vs["sharpe"], 4),
            "ann_ret_pct": round(vs["ann_ret"] * 100, 2),
            "ann_vol_pct": round(vs["ann_vol"] * 100, 2),
            "mdd_pct": round(vs["mdd"] * 100, 2),
            "calmar": round(vs["calmar"], 3),
            "n_rebalances": vs["n_rebalances"],
            "tx_total_pct": round(vs["tx_total_pct"], 3),
        },
        "dm_test_vs_minus_vt": {
            "test_name": label,
            "t_stat": round(dm_t, 4),
            "p_value": round(dm_p, 4),
            "significant_5pct": dm_p < 0.05,
            "direction": "VT+VS better" if dm_t > 0 else "VT better",
        },
        "sharpe_diff": round(vs["sharpe"] - vt["sharpe"], 4),
        "winner": winner,
    }

    all_results[label] = period_result
    dm_tests.append({"name": label, "t_stat": dm_t, "p_value": dm_p})

    print(f"    Buy&Hold:  Sharpe={bh['sharpe']:.4f}, Ret={bh['ann_ret']*100:.1f}%, MDD={bh['mdd']*100:.1f}%")
    print(f"    VT only:   Sharpe={vt['sharpe']:.4f}, Ret={vt['ann_ret']*100:.1f}%, MDD={vt['mdd']*100:.1f}%")
    print(f"    VT+VS:     Sharpe={vs['sharpe']:.4f}, Ret={vs['ann_ret']*100:.1f}%, MDD={vs['mdd']*100:.1f}%")
    print(f"    DM test:   t={dm_t:.4f}, p={dm_p:.4f} ({'significant' if dm_p < 0.05 else 'NS'})")
    print(f"    Winner:    {winner} (Sharpe diff = {vs['sharpe'] - vt['sharpe']:+.4f})")

# ============================================================
# 5. POOLED ANALYSIS
# ============================================================
print("\n[4/5] Pooled analysis across all OOS periods...")

# Concatenate all daily returns
pooled_vt = pd.concat(all_vt_returns)
pooled_vs = pd.concat(all_vs_returns)

# Pooled DM test
pooled_vt_loss = -pooled_vt.values
pooled_vs_loss = -pooled_vs.values
pooled_dm_t, pooled_dm_p = dm_test(pooled_vt_loss, pooled_vs_loss)
dm_tests.append({"name": "pooled", "t_stat": pooled_dm_t, "p_value": pooled_dm_p})

# Pooled Sharpe
n_years_pooled = len(pooled_vt) / TRADING_DAYS
pooled_vt_sharpe = (pooled_vt.mean() * TRADING_DAYS) / (pooled_vt.std() * np.sqrt(TRADING_DAYS))
pooled_vs_sharpe = (pooled_vs.mean() * TRADING_DAYS) / (pooled_vs.std() * np.sqrt(TRADING_DAYS))

# Harvey t-test for each strategy vs 0
# t = Sharpe * sqrt(T/252) approximately
n_total = len(pooled_vt)
harvey_vt_t = pooled_vt_sharpe * np.sqrt(n_total / TRADING_DAYS)
harvey_vs_t = pooled_vs_sharpe * np.sqrt(n_total / TRADING_DAYS)

print(f"\n  Pooled Statistics ({n_total} total days, {n_years_pooled:.1f} years):")
print(f"    VT only   — Pooled Sharpe: {pooled_vt_sharpe:.4f}, Harvey t: {harvey_vt_t:.3f}")
print(f"    VT+VS     — Pooled Sharpe: {pooled_vs_sharpe:.4f}, Harvey t: {harvey_vs_t:.3f}")
print(f"    Pooled DM — t={pooled_dm_t:.4f}, p={pooled_dm_p:.4f}")
print(f"    Harvey threshold: t > 3.0")

raw_p_values = [test["p_value"] for test in dm_tests]
bonferroni_p = bonferroni_adjust(raw_p_values)
bh_p = bh_adjust(raw_p_values)
for test, bonf_p, bh_p_value in zip(dm_tests, bonferroni_p, bh_p):
    test["bonferroni_p_value"] = bonf_p
    test["bh_p_value"] = bh_p_value
    test["significant_5pct_bonferroni"] = bonf_p < 0.05
    test["significant_5pct_bh"] = bh_p_value < 0.05

for test in dm_tests:
    if test["name"] == "pooled":
        continue
    all_results[test["name"]]["dm_test_vs_minus_vt"].update({
        "bonferroni_p_value": round(test["bonferroni_p_value"], 4),
        "bh_p_value": round(test["bh_p_value"], 4),
        "significant_5pct_bonferroni": test["significant_5pct_bonferroni"],
        "significant_5pct_bh": test["significant_5pct_bh"],
    })

print(f"\n  Score: VT+VS wins {vs_wins}/5, VT wins {vt_wins}/5")
if vs_wins >= 4:
    verdict = "PASS — VT+VolSpread consistently outperforms. Consider deployment."
elif vs_wins >= 3:
    verdict = "MARGINAL — Slight edge but not consistent enough. More testing needed."
elif vs_wins <= 2:
    verdict = "FAIL — VT+VolSpread does NOT consistently outperform. Do NOT deploy."
else:
    verdict = "INCONCLUSIVE"

print(f"  Verdict: {verdict}")

# ============================================================
# 6. SAVE RESULTS
# ============================================================
print("\n[5/5] Saving results...")

# Summary table for display
summary_rows = []
for label in [p[2] for p in OOS_PERIODS]:
    if label in all_results:
        r = all_results[label]
        summary_rows.append({
            "Period": label,
            "VIX_mean": r["vix_mean"],
            "VolRatio_mean": r["vol_ratio_mean"],
            "BH_Sharpe": r["buy_hold"]["sharpe"],
            "VT_Sharpe": r["vt_only"]["sharpe"],
            "VS_Sharpe": r["vt_volspread"]["sharpe"],
            "Diff": r["sharpe_diff"],
            "DM_t": r["dm_test_vs_minus_vt"]["t_stat"],
            "DM_p": r["dm_test_vs_minus_vt"]["p_value"],
            "Winner": r["winner"],
        })

summary_df = pd.DataFrame(summary_rows)
print("\n" + "=" * 100)
print("CROSS-OOS SUMMARY TABLE")
print("=" * 100)
print(summary_df.to_string(index=False))
print("=" * 100)

elapsed = time.time() - t0

output = {
    "experiment": "K506",
    "title": "EWT-0050 Vol Spread Strategy — Cross-OOS Validation",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "repo-local cache preferred, yfinance fallback; adjusted OHLC used for 0050.TW split safety",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_total_days": len(data),
    "strategy": {
        "base": "weight = min(8.63/VIX, 1.0)",
        "vol_spread_adjustment": {
            "vol_window": VOL_WINDOW,
            "ratio_high_threshold": RATIO_HIGH,
            "ratio_low_threshold": RATIO_LOW,
            "adjust_down_multiplier": ADJUST_DOWN,
            "adjust_up_multiplier": ADJUST_UP,
        },
        "rebalancing": "monthly (1st trading day)",
        "return_channel": "tradable rebalance-open channel: old weight earns close-to-open gap; new target earns open-to-close; weights drift between monthly rebalances",
        "tx_costs": {
            "buy_oneway": TX_BUY_ONEWAY,
            "sell_oneway": TX_SELL_ONEWAY,
            "roundtrip_reference": TX_ROUNDTRIP,
            "application": "side-aware per dollar traded at rebalance open",
        },
        "cash_rate_annual": CASH_RATE_ANNUAL,
        "signal_timing": "strict as-of: latest US EWT/VIX close strictly before Taiwan trading date; 0050 realized vol through prior TW close",
    },
    "data_inputs": data_sources,
    "methodology_hardening_2026_07_05": {
        "rebalance_timing": "fixed close-to-close mismatch by decomposing rebalance-day 0050 return into close-to-open and open-to-close legs",
        "calendar_asof": "fixed row-shift stale signal risk with merge_asof(allow_exact_matches=False) from US calendars to Taiwan trading dates",
        "price_adjustment": "uses adjusted close/open and repairs split-like jumps that remain in the local cache",
        "detected_tw50_split_adjustments": tw50_split_adjustments,
        "transaction_cost": "fixed full-round-trip-on-every-delta overcharge; now uses K625 buy/sell one-way schedule",
        "knowledge_write": "deferred to the formal knowledge writer/gate; this Codex task only refreshes the experiment artifact",
    },
    "oos_periods": {label: all_results.get(label, "skipped") for _, _, label in OOS_PERIODS},
    "pooled_analysis": {
        "n_total_days": n_total,
        "n_years": round(n_years_pooled, 2),
        "vt_only_pooled_sharpe": round(float(pooled_vt_sharpe), 4),
        "vt_volspread_pooled_sharpe": round(float(pooled_vs_sharpe), 4),
        "harvey_t_vt": round(float(harvey_vt_t), 3),
        "harvey_t_vs": round(float(harvey_vs_t), 3),
        "harvey_threshold": 3.0,
        "pooled_dm_test": {
            "test_name": "pooled",
            "t_stat": round(pooled_dm_t, 4),
            "p_value": round(pooled_dm_p, 4),
            "significant_5pct": pooled_dm_p < 0.05,
            "direction": "VT+VS better" if pooled_dm_t > 0 else "VT better",
            "bonferroni_p_value": round(dm_tests[-1]["bonferroni_p_value"], 4),
            "bh_p_value": round(dm_tests[-1]["bh_p_value"], 4),
            "significant_5pct_bonferroni": dm_tests[-1]["significant_5pct_bonferroni"],
            "significant_5pct_bh": dm_tests[-1]["significant_5pct_bh"],
        },
        "multiple_testing_family_size": len(dm_tests),
        "multiple_testing_method_note": "Reported both Bonferroni (FWER) and Benjamini-Hochberg (FDR) for 5 segment tests + pooled test.",
    },
    "cross_oos_score": {
        "vs_wins": vs_wins,
        "vt_wins": vt_wins,
        "total_periods": len([l for l in [p[2] for p in OOS_PERIODS] if l in all_results]),
        "pass_threshold": ">=4/5",
        "verdict": verdict,
    },
    "vol_ratio_diagnostics": {
        "full_sample_mean": round(data["vol_ratio_signal"].mean(), 3),
        "full_sample_std": round(data["vol_ratio_signal"].std(), 3),
        "full_sample_min": round(data["vol_ratio_signal"].min(), 3),
        "full_sample_max": round(data["vol_ratio_signal"].max(), 3),
        "pct_above_1.2": round((data["vol_ratio_signal"] > RATIO_HIGH).mean() * 100, 1),
        "pct_below_0.8": round((data["vol_ratio_signal"] < RATIO_LOW).mean() * 100, 1),
    },
    "runtime_seconds": round(elapsed, 2),
    "references": [
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Harvey, Liu, Zhu (2016) '...and the Cross-Section of Expected Returns' RFS",
        "Bozovic (2024) 'VIX-managed portfolios' IRFA",
        "K499: Monthly rebalancing optimal for Taiwan TX cost",
        "K505: VT+VolSpread initial results (Sharpe=0.698, MDD=-25%)",
        "Q1: 8.63/VIX for Taiwan = 12/(VIX*1.39)",
    ],
}

results_payload = json.dumps(output, indent=2, default=str)
tmp_results_path = RESULTS_PATH.with_suffix(".tmp")
tmp_results_path.write_text(results_payload)
json.loads(tmp_results_path.read_text())
os.replace(tmp_results_path, RESULTS_PATH)
print(f"\nResults saved to {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print(f"\nFINAL VERDICT: {verdict}")
