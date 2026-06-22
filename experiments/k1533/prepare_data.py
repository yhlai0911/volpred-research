"""K1533 data preparation for RECH-X replication.

Builds two return + realized-measure datasets:

US (SPY, QQQ):
  - Daily OHLC from yfinance (auto_adjust=False, raw OHLC for range estimators).
  - Realized-measure PROXY = Garman-Klass daily variance estimator from OHLC.
    This is a daily range-based proxy, NOT the 5-min intraday RV from the
    Oxford-Man Institute used in the original RECH-X paper. Documented
    fidelity gap (see README). VIX (close) is also saved as an alternative
    exogenous covariate.

TAIWAN (TAIFEX TX futures):
  - Daily returns + TRUE 5-min intraday realized variance reconstructed from
    the 5-min bar parquet built in k1100h (2017-2021 day session). This is a
    genuine high-frequency RV, matching the spirit of the paper's covariate.

All outputs land in experiments/k1533/data/. No shared state is modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)

SEED = 1533
np.random.seed(SEED)


def garman_klass_var(o, h, l, c):
    """Garman-Klass daily variance estimator (in return^2 units).

    GK = 0.5*(ln(H/L))^2 - (2*ln2 - 1)*(ln(C/O))^2
    Returns daily variance; sqrt gives daily realized volatility proxy.
    """
    hl = np.log(h / l)
    co = np.log(c / o)
    return 0.5 * hl**2 - (2 * np.log(2) - 1) * co**2


def build_us():
    import yfinance as yf

    start, end = "2007-01-01", "2024-12-31"
    out = {}
    for tic in ["SPY", "QQQ"]:
        df = yf.download(tic, start=start, end=end, progress=False, auto_adjust=False)
        df.columns = [c[0] for c in df.columns]  # flatten MultiIndex
        df = df[["Open", "High", "Low", "Close", "Adj Close"]].dropna()
        # Returns from adjusted close (handles splits/divs); demean later in model.
        ret = 100.0 * np.log(df["Adj Close"]).diff()  # percent log returns
        gk_var = garman_klass_var(df["Open"], df["High"], df["Low"], df["Close"])
        # Express RV in same (percent) scale as returns: var of 100*logret.
        gk_var_pct = gk_var * (100.0**2)
        d = pd.DataFrame(
            {
                "ret": ret,
                "rv": gk_var_pct,  # daily realized variance proxy (percent^2)
                "close": df["Close"],
            }
        ).dropna()
        d.index.name = "date"
        d.to_csv(DATA / f"us_{tic}.csv")
        out[tic] = d
        print(f"US {tic}: {len(d)} rows, {d.index.min().date()}..{d.index.max().date()}")

    # VIX as alt covariate (close), align to SPY index later in model.
    vix = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)
    vix.columns = [c[0] for c in vix.columns]
    vixc = vix["Close"].rename("vix")
    vixc.index.name = "date"
    vixc.to_csv(DATA / "us_VIX.csv")
    print(f"US VIX: {len(vixc)} rows")
    return out


def build_taiwan():
    """Reconstruct daily returns + true 5-min RV for TAIFEX TX from 5-min bars."""
    pq = ROOT / "experiments/k1100h/data/_taifex_5min_2017-2021.parquet"
    if not pq.exists():
        print(f"WARN: TAIFEX 5min parquet missing at {pq}; skipping Taiwan", file=sys.stderr)
        return None
    bars = pd.read_parquet(pq)
    # Use day session only (continuous regular-trading bars).
    day = bars[bars["session"] == "day"].copy()
    day["session_date"] = pd.to_datetime(day["session_date"])
    day = day.sort_values(["session_date", "bar_start"])

    rows = []
    for d, g in day.groupby("session_date"):
        closes = g["close"].to_numpy(dtype=float)
        if len(closes) < 5:
            continue
        # 5-min log returns within the day (percent scale).
        logc = np.log(closes)
        intraday_ret = np.diff(logc) * 100.0
        rv = float(np.sum(intraday_ret**2))  # realized variance (percent^2)
        day_open = float(g["open"].iloc[0])
        day_close = float(g["close"].iloc[-1])
        rows.append(
            {
                "date": d,
                "open": day_open,
                "close": day_close,
                "rv": rv,
                "n_bars": len(closes),
            }
        )
    tx = pd.DataFrame(rows).set_index("date").sort_index()
    # Daily close-to-close return (percent log return).
    tx["ret"] = 100.0 * np.log(tx["close"]).diff()
    tx = tx.dropna(subset=["ret", "rv"])
    tx = tx[["ret", "rv", "close", "n_bars"]]
    tx.to_csv(DATA / "tw_TX.csv")
    print(f"TW TX: {len(tx)} rows, {tx.index.min().date()}..{tx.index.max().date()}")
    print(f"  median n 5-min bars/day: {tx['n_bars'].median():.0f}")
    return tx


if __name__ == "__main__":
    print("=== Building US data (yfinance OHLC -> Garman-Klass RV proxy) ===")
    build_us()
    print("\n=== Building Taiwan data (TAIFEX 5-min -> true intraday RV) ===")
    build_taiwan()
    print("\nDone.")
