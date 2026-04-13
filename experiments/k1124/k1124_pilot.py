"""
K1124 pilot — validate tick rule + OFI computation on single day of TAIFEX TX.

Goal: verify pipeline works before full 5-year run.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

TAIFEX_DIR = Path("/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python")

DAY_START = 84500      # 08:45
DAY_END = 134500       # 13:45


def read_tx_file(path: Path) -> pd.DataFrame:
    for enc in ("big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            break
        except Exception:
            df = None
    if df is None:
        return None
    contract = df.iloc[:, 2].astype(str)
    monthly_mask = contract.str.match(r"^\d{6}$")
    df = df.loc[monthly_mask].copy()
    df["contract_month"] = pd.to_numeric(df.iloc[:, 2], errors="coerce").astype("Int64")
    df["time_int"] = pd.to_numeric(df.iloc[:, 3], errors="coerce").astype("Int64")
    df["price"] = pd.to_numeric(df.iloc[:, 4], errors="coerce")
    df["volume"] = pd.to_numeric(df.iloc[:, 5], errors="coerce")
    df = df.dropna(subset=["contract_month", "time_int", "price", "volume"])
    return df[["contract_month", "time_int", "price", "volume"]]


def pick_active(df):
    return int(df.groupby("contract_month")["volume"].sum().idxmax())


def tick_rule_direction(prices: np.ndarray) -> np.ndarray:
    """Lee & Ready tick rule: +1 = buy-initiated, -1 = sell-initiated.
    For ticks with no price change, carry forward previous non-zero direction.
    First tick: default +1 (convention).
    """
    n = len(prices)
    dirs = np.zeros(n, dtype=np.int8)
    prev_dir = 1  # convention for first tick
    prev_price = prices[0]
    dirs[0] = prev_dir
    for i in range(1, n):
        if prices[i] > prev_price:
            prev_dir = 1
        elif prices[i] < prev_price:
            prev_dir = -1
        # else keep prev_dir (zero-tick rule)
        dirs[i] = prev_dir
        prev_price = prices[i]
    return dirs


def compute_5min_ofi_and_rv(day_df: pd.DataFrame) -> pd.DataFrame:
    """Compute OFI and RV per 5-min bar for day session.
    day_df: rows are ticks in 08:45-13:45, one active contract.
    Returns DataFrame with bar, price_open, price_close, volume, ofi, rv."""
    day_df = day_df.sort_values("time_int").reset_index(drop=True)
    t = day_df["time_int"].values
    p = day_df["price"].values.astype(float)
    v = day_df["volume"].values.astype(float)

    # Bar bucket = integer index of 5-min slot from 08:45
    # HHMMSS -> minutes-of-day / 5
    h = t // 10000
    m = (t % 10000) // 100
    minutes_of_day = h * 60 + m
    base_min = 8 * 60 + 45  # 08:45 = 525
    bar = (minutes_of_day - base_min) // 5  # 0..59 for 08:45-13:45

    # Tick directions
    dirs = tick_rule_direction(p)
    signed_vol = dirs.astype(float) * v

    df = pd.DataFrame({
        "bar": bar,
        "price": p,
        "volume": v,
        "signed_vol": signed_vol,
    })

    # 5-min bar aggregation
    bars = []
    for b_id, g in df.groupby("bar"):
        if len(g) < 2:
            continue
        prices_b = g["price"].values
        log_ret_ticks = np.diff(np.log(prices_b))
        rv = float(np.sum(log_ret_ticks ** 2))
        total_vol = float(g["volume"].sum())
        signed_sum = float(g["signed_vol"].sum())
        ofi = signed_sum / total_vol if total_vol > 0 else 0.0
        bars.append({
            "bar": int(b_id),
            "price_open": float(prices_b[0]),
            "price_close": float(prices_b[-1]),
            "log_ret": float(np.log(prices_b[-1] / prices_b[0])),
            "volume": total_vol,
            "signed_vol": signed_sum,
            "ofi": ofi,
            "rv": rv,
            "n_ticks": int(len(g)),
        })
    return pd.DataFrame(bars)


def main():
    test_date = "2020_06_15"
    path = TAIFEX_DIR / f"Daily_{test_date}TX.csv"
    print(f"Loading: {path.name}")
    df = read_tx_file(path)
    if df is None:
        print("FAIL: cannot read")
        sys.exit(1)
    active = pick_active(df)
    print(f"Active contract: {active}, total ticks: {len(df)}")
    df_active = df[df["contract_month"] == active].copy()
    day_mask = (df_active["time_int"] >= DAY_START) & (df_active["time_int"] <= DAY_END)
    day_df = df_active.loc[day_mask]
    print(f"Day session ticks: {len(day_df)}")

    bars = compute_5min_ofi_and_rv(day_df)
    print(f"\n5-min bars: {len(bars)}")
    print(bars.head(10).to_string())
    print("\nSummary stats:")
    print(f"  OFI mean = {bars['ofi'].mean():.4f}, std = {bars['ofi'].std():.4f}")
    print(f"  |OFI| mean = {bars['ofi'].abs().mean():.4f}")
    print(f"  RV mean = {bars['rv'].mean():.2e}")
    print(f"  log_ret mean = {bars['log_ret'].mean():.2e}, std = {bars['log_ret'].std():.2e}")

    # Basic correlation test
    if len(bars) >= 10:
        # OFI(t) vs RV(t+1)
        ofi_t = bars["ofi"].values[:-1]
        abs_ofi_t = np.abs(ofi_t)
        rv_next = bars["rv"].values[1:]
        if np.std(rv_next) > 0:
            corr = np.corrcoef(abs_ofi_t, rv_next)[0, 1]
            print(f"\nSingle-day corr(|OFI_t|, RV_{{t+1}}) = {corr:.4f}")

if __name__ == "__main__":
    main()
