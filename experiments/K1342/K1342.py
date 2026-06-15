"""K1342: MOC-imbalance proxy and late-close drift.

This is a conservative proxy study, not a proprietary NYSE/Nasdaq imbalance-feed
study. Free Yahoo minute bars do not contain true MOC imbalance messages, so the
signal uses only pre-publication signed-volume pressure from 15:30-15:48 ET.

Lookahead policy
----------------
- Signal window ends at 15:48 ET; targets start no earlier than 15:52 ET.
- High-pressure filter uses each ticker's prior 20 trading days only
  (`shift(1).rolling(...).quantile(...)`).
- Next-day targets use the next observed trading day, not calendar-day offsets.
- Bootstrap uses np.random.default_rng(SEED).
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
PERIOD = "60d"
INTERVAL = "2m"
SIGNAL_START_ET = "15:30"
SIGNAL_END_ET = "15:48"
ENTRY_START_ET = "15:52"
ENTRY_END_ET = "15:52"
CLOSE_START_ET = "15:54"
CLOSE_END_ET = "15:58"
ROUND_TRIP_COST_BPS = 3.4  # task assumption: 1.7bp per side liquidity/impact cost
BOOTSTRAP_B = 5000
BOOTSTRAP_BLOCK_DAYS = 5
HIGH_PRESSURE_LOOKBACK = 20
HIGH_PRESSURE_MIN_PERIODS = 10
HIGH_PRESSURE_Q = 0.70

TARGETS = ["late_close", "overnight_open", "next_close"]


def flatten_yfinance_columns(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        if "Price" in df.columns.names:
            df.columns = df.columns.get_level_values("Price")
        else:
            df.columns = df.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in needed if col not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")
    return df[needed].dropna()


def fetch_minute_bars(ticker: str) -> pd.DataFrame:
    raw = yf.download(
        ticker,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise ValueError(f"{ticker}: yfinance returned no data")
    raw = raw[~raw.index.duplicated(keep="last")]
    df = flatten_yfinance_columns(raw, ticker)
    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df.index = idx.tz_convert("America/New_York")
    df = df.between_time("09:30", "15:59").copy()
    df["date"] = df.index.date
    df["time"] = df.index.time
    df["ret_bar"] = np.log(df["Close"] / df["Close"].shift(1))
    # Do not let the overnight jump contaminate the first regular-session minute.
    first_bar = df.groupby("date", sort=True).head(1).index
    df.loc[first_bar, "ret_bar"] = np.nan
    df["signed_volume"] = np.sign(df["ret_bar"].fillna(0.0)) * df["Volume"]
    return df


def minute_slice(day: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return day.between_time(start, end)


def build_daily_signals(ticker: str, bars: pd.DataFrame) -> pd.DataFrame:
    days = [(d, g.sort_index()) for d, g in bars.groupby("date", sort=True)]
    rows: list[dict] = []

    for i, (day, intraday) in enumerate(days[:-1]):
        next_day, next_intraday = days[i + 1]
        signal_window = minute_slice(intraday, SIGNAL_START_ET, SIGNAL_END_ET)
        entry_window = minute_slice(intraday, ENTRY_START_ET, ENTRY_END_ET)
        close_window = minute_slice(intraday, CLOSE_START_ET, CLOSE_END_ET)
        if len(signal_window) < 8 or entry_window.empty or close_window.empty:
            continue

        signal_volume = float(signal_window["Volume"].sum())
        if signal_volume <= 0:
            continue
        pressure = float(signal_window["signed_volume"].sum() / signal_volume)
        side = int(np.sign(pressure))
        if side == 0:
            continue

        entry_price = float(entry_window["Close"].iloc[-1])
        close_price = float(close_window["Close"].iloc[-1])
        next_open_price = float(next_intraday["Open"].iloc[0])
        next_close_price = float(next_intraday["Close"].iloc[-1])

        rows.append(
            {
                "ticker": ticker,
                "date": pd.Timestamp(day).strftime("%Y-%m-%d"),
                "next_trading_date": pd.Timestamp(next_day).strftime("%Y-%m-%d"),
                "signal_pressure": pressure,
                "abs_pressure": abs(pressure),
                "signal_side": side,
                "signal_volume": signal_volume,
                "entry_price_after_publication": entry_price,
                "close_price": close_price,
                "next_open_price": next_open_price,
                "next_close_price": next_close_price,
                "late_close_return": math.log(close_price / entry_price),
                "overnight_open_return": math.log(next_open_price / close_price),
                "next_close_return": math.log(next_close_price / close_price),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["date_ts"] = pd.to_datetime(out["date"])
    out = out.sort_values(["ticker", "date_ts"]).reset_index(drop=True)
    out["high_pressure_threshold"] = (
        out.groupby("ticker")["abs_pressure"]
        .transform(
            lambda s: s.shift(1)
            .rolling(HIGH_PRESSURE_LOOKBACK, min_periods=HIGH_PRESSURE_MIN_PERIODS)
            .quantile(HIGH_PRESSURE_Q)
        )
    )
    out["is_high_pressure"] = out["abs_pressure"] >= out["high_pressure_threshold"]
    out.loc[out["high_pressure_threshold"].isna(), "is_high_pressure"] = False
    return out


def newey_west_tstat(x: np.ndarray, lag: int = 5) -> float:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < lag + 3:
        return float("nan")
    demeaned = x - x.mean()
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    var = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        gamma = float(np.dot(demeaned[k:], demeaned[:-k]) / n)
        var += 2.0 * (1.0 - k / (lag + 1.0)) * gamma
    se = math.sqrt(max(var, 0.0) / n)
    return float(x.mean() / se) if se > 0 else float("nan")


def block_bootstrap_pvalue(x: np.ndarray, block: int = BOOTSTRAP_BLOCK_DAYS) -> float:
    """One-sided p-value for H0 mean(x) <= 0, using centred block bootstrap."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 8:
        return float("nan")
    block = min(block, max(2, n // 2))
    observed = float(x.mean())
    centred = x - observed
    rng = np.random.default_rng(SEED)
    n_blocks = math.ceil(n / block)
    boot_means = np.empty(BOOTSTRAP_B)
    for b in range(BOOTSTRAP_B):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([centred[s : s + block] for s in starts])[:n]
        boot_means[b] = sample.mean()
    return float(np.mean(boot_means >= observed))


def summarise_group(df: pd.DataFrame, label: str) -> dict:
    out: dict[str, dict] = {}
    daily = df.copy()
    daily["date_ts"] = pd.to_datetime(daily["date"])
    for target in TARGETS:
        gross_col = f"{target}_strategy_gross"
        net_col = f"{target}_strategy_net"
        daily[gross_col] = daily["signal_side"] * daily[f"{target}_return"]
        daily[net_col] = daily[gross_col] - ROUND_TRIP_COST_BPS / 10000.0

        by_date = (
            daily.groupby("date_ts")[[gross_col, net_col]]
            .mean()
            .sort_index()
        )
        gross = by_date[gross_col].to_numpy(dtype=float)
        net = by_date[net_col].to_numpy(dtype=float)
        p_gross = block_bootstrap_pvalue(gross)
        p_net = block_bootstrap_pvalue(net)
        out[target] = {
            "label": label,
            "n_observations": int(len(daily)),
            "n_dates": int(len(by_date)),
            "gross_mean_bps": float(np.nanmean(gross) * 10000.0),
            "net_mean_bps": float(np.nanmean(net) * 10000.0),
            "gross_hit_rate": float(np.nanmean(gross > 0.0)),
            "net_hit_rate": float(np.nanmean(net > 0.0)),
            "gross_newey_west_t": newey_west_tstat(gross),
            "net_newey_west_t": newey_west_tstat(net),
            "gross_block_bootstrap_p_one_sided": p_gross,
            "net_block_bootstrap_p_one_sided": p_net,
            "gross_block_bootstrap_p_bonferroni_6": (
                float(min(1.0, p_gross * 6.0)) if not math.isnan(p_gross) else float("nan")
            ),
            "net_block_bootstrap_p_bonferroni_6": (
                float(min(1.0, p_net * 6.0)) if not math.isnan(p_net) else float("nan")
            ),
        }
    return out


def summarise_by_ticker(df: pd.DataFrame) -> dict:
    out: dict[str, dict] = {}
    for ticker, g in df.groupby("ticker", sort=True):
        out[ticker] = {}
        for target in TARGETS:
            signed = g["signal_side"] * g[f"{target}_return"]
            out[ticker][target] = {
                "n": int(len(g)),
                "gross_mean_bps": float(signed.mean() * 10000.0),
                "net_mean_bps": float((signed.mean() - ROUND_TRIP_COST_BPS / 10000.0) * 10000.0),
                "hit_rate": float((signed > 0.0).mean()),
                "mean_abs_pressure": float(g["abs_pressure"].mean()),
                "high_pressure_n": int(g["is_high_pressure"].sum()),
            }
    return out


def make_figures(records: pd.DataFrame, summary: dict) -> None:
    labels = {"late_close": "15:51-close", "overnight_open": "close-next open", "next_close": "close-next close"}
    all_metrics = summary["pooled_daily_equal_weight"]["all_days"]
    hp_metrics = summary["pooled_daily_equal_weight"]["high_pressure_days"]

    x = np.arange(len(TARGETS))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(
        x - width / 2,
        [all_metrics[t]["gross_mean_bps"] for t in TARGETS],
        width,
        label="All days gross",
        color="#345995",
    )
    ax.bar(
        x + width / 2,
        [hp_metrics[t]["gross_mean_bps"] for t in TARGETS],
        width,
        label="Causal high-pressure gross",
        color="#E26D5A",
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x, [labels[t] for t in TARGETS])
    ax.set_ylabel("Mean strategy return, bps")
    ax.set_title("K1342 MOC proxy direction: gross drift by target")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1342_mean_drift_bps.png", dpi=140)
    plt.close(fig)

    daily = records.copy()
    daily["date_ts"] = pd.to_datetime(daily["date"])
    daily["late_close_net"] = (
        daily["signal_side"] * daily["late_close_return"] - ROUND_TRIP_COST_BPS / 10000.0
    )
    ew = daily.groupby("date_ts")["late_close_net"].mean().sort_index()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot((1.0 + ew).cumprod() - 1.0, color="#2A9D8F", linewidth=1.6)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("K1342 equal-weight 15:51-close proxy strategy, net of 3.4bp")
    ax.set_ylabel("Cumulative return")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1342_late_close_net_cumulative.png", dpi=140)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    all_records: list[pd.DataFrame] = []
    data_audit: dict[str, dict] = {}

    for ticker in TICKERS:
        print(f"Downloading {ticker} {PERIOD} {INTERVAL}...")
        try:
            bars = fetch_minute_bars(ticker)
            records = build_daily_signals(ticker, bars)
        except Exception as exc:
            data_audit[ticker] = {"ok": False, "error": repr(exc)}
            print(f"  {ticker}: failed: {exc}")
            continue
        data_audit[ticker] = {
            "ok": True,
            "minute_rows": int(len(bars)),
            "regular_session_dates": int(bars["date"].nunique()),
            "usable_signal_days": int(len(records)),
            "first_date": str(bars["date"].min()),
            "last_date": str(bars["date"].max()),
        }
        print(
            f"  {ticker}: rows={len(bars)} dates={bars['date'].nunique()} "
            f"usable={len(records)}"
        )
        if not records.empty:
            all_records.append(records)

    if not all_records:
        raise RuntimeError("No usable minute records")

    records = pd.concat(all_records, ignore_index=True)
    all_days = records.copy()
    high_pressure = records[records["is_high_pressure"]].copy()

    summary = {
        "k_id": "K1342",
        "run_date": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d"),
        "seed": SEED,
        "status": "completed_proxy_study",
        "data_source": "yfinance 1-minute OHLCV; no proprietary MOC imbalance feed",
        "period": PERIOD,
        "interval": INTERVAL,
        "tickers": TICKERS,
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "bootstrap": {"B": BOOTSTRAP_B, "block_days": BOOTSTRAP_BLOCK_DAYS},
        "signal_definition": {
            "proxy": "sum(sign(bar return) * volume) / sum(volume)",
            "signal_window_et": f"{SIGNAL_START_ET}-{SIGNAL_END_ET}",
            "entry_for_late_close_target_et": f"{ENTRY_START_ET} close",
            "close_exit_proxy_et": f"last available {CLOSE_START_ET}-{CLOSE_END_ET} close",
            "high_pressure_filter": (
                "abs(proxy) >= prior 20-trading-day rolling 70th percentile "
                "with shift(1), min_periods=10"
            ),
        },
        "lookahead_policy": (
            "Signal excludes 15:50 and later bars; targets begin at 15:51 or at the "
            "next session. High-pressure thresholds use shifted prior data only."
        ),
        "data_audit": data_audit,
        "sample": {
            "n_observations_all": int(len(all_days)),
            "n_observations_high_pressure": int(len(high_pressure)),
            "n_dates_all": int(all_days["date"].nunique()),
            "n_dates_high_pressure": int(high_pressure["date"].nunique()),
            "first_signal_date": str(all_days["date"].min()),
            "last_signal_date": str(all_days["date"].max()),
        },
        "pooled_daily_equal_weight": {
            "all_days": summarise_group(all_days, "all_days"),
            "high_pressure_days": summarise_group(high_pressure, "high_pressure_days")
            if not high_pressure.empty
            else {},
        },
        "by_ticker": summarise_by_ticker(records),
        "interpretation": (
            "This tests whether a free pre-close signed-volume proxy predicts drift. "
            "It cannot validate true exchange-published MOC imbalance alpha without "
            "the proprietary imbalance feed."
        ),
    }

    records_out = records.drop(columns=["date_ts"], errors="ignore").copy()
    records_out.to_csv(OUT_DIR / "K1342_daily_signals.csv", index=False)
    make_figures(records, summary)

    with (OUT_DIR / "K1342_results.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Wrote {OUT_DIR / 'K1342_results.json'}")
    print(f"Wrote {OUT_DIR / 'K1342_daily_signals.csv'}")
    print("\n=== Key pooled results (bps, p_boot net) ===")
    for group_name, group in summary["pooled_daily_equal_weight"].items():
        if not group:
            continue
        print(group_name)
        for target in TARGETS:
            m = group[target]
            print(
                f"  {target:>14}: n_dates={m['n_dates']:>2} "
                f"gross={m['gross_mean_bps']:+.3f} net={m['net_mean_bps']:+.3f} "
                f"t_net={m['net_newey_west_t']:+.2f} p_net={m['net_block_bootstrap_p_one_sided']:.3f}"
            )


if __name__ == "__main__":
    main()
