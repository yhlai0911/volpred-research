"""Backfill 3-year paper trading history for vix_cond_leverage and taiwan_hybrid_leverage.

These two strategies were added on 2026-03-27 with only 1 entry.
This script generates daily entries from 2023-01-04 to 2026-03-26 using
the EXACT same formulas as daily_update.py.

Data source: yfinance (SPY, GLD, 0050.TW, ^VIX)
Period: 2023-01-01 to 2026-03-27

Usage:
    uv run python scripts/backfill_new_strategies.py
    uv run python scripts/backfill_new_strategies.py --dry-run   # preview only
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

PROJECT = Path(__file__).resolve().parent.parent
COMMON_START_DATE = "2023-01-04"


def fetch_data():
    """Fetch all required price data from yfinance."""
    print("Fetching data from yfinance...")
    start = "2022-01-01"  # extra history for VIX percentile (252d lookback)
    end = "2026-03-28"

    spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    gld = yf.download("GLD", start=start, end=end, auto_adjust=True, progress=False)
    tw50 = yf.download("0050.TW", start=start, end=end, auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)

    # Flatten multi-level columns if present
    for df in [spy, gld, tw50, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    print(f"  SPY: {len(spy)} rows ({spy.index[0].date()} to {spy.index[-1].date()})")
    print(f"  GLD: {len(gld)} rows ({gld.index[0].date()} to {gld.index[-1].date()})")
    print(f"  0050.TW: {len(tw50)} rows ({tw50.index[0].date()} to {tw50.index[-1].date()})")
    print(f"  VIX: {len(vix)} rows ({vix.index[0].date()} to {vix.index[-1].date()})")

    return spy, gld, tw50, vix


def compute_vix_cond_leverage(spy, gld, vix):
    """Generate daily entries for vix_cond_leverage strategy.

    Formula (from daily_update.py lines 340-358):
        base_weight = 12/VIX / 2    (50% equity allocation)
        leverage = 1.5 if VIX < 15 else 1.0
        spy_w = min(base_weight * leverage, 1.0)
        gld_w = min(base_weight * leverage, 1.0)
        portfolio_return = spy_w * r_spy + gld_w * r_gld
    """
    print("\nComputing vix_cond_leverage entries...")

    # Align dates: use SPY trading dates
    spy_close = spy["Close"].rename("spy_close")
    gld_close = gld["Close"].rename("gld_close")
    vix_close = vix["Close"].rename("vix_close")

    # Merge on date
    df = pd.DataFrame(index=spy_close.index)
    df["spy_close"] = spy_close
    df["gld_close"] = gld_close
    df["vix_close"] = vix_close

    # Forward fill VIX for any missing US trading days
    df["vix_close"] = df["vix_close"].ffill()
    df = df.dropna(subset=["spy_close", "gld_close", "vix_close"])

    # Compute daily returns
    df["spy_ret"] = df["spy_close"].pct_change()
    df["gld_ret"] = df["gld_close"].pct_change()

    # Open prices for metadata
    spy_open = spy["Open"].rename("spy_open")
    gld_open = gld["Open"].rename("gld_open")
    df["spy_open"] = spy_open
    df["gld_open"] = gld_open

    # Compute weights
    df["base_weight"] = 12.0 / df["vix_close"] / 2
    df["leverage"] = np.where(df["vix_close"] < 15, 1.5, 1.0)
    df["spy_w"] = np.minimum(df["base_weight"] * df["leverage"], 1.0).round(2)
    df["gld_w"] = np.minimum(df["base_weight"] * df["leverage"], 1.0).round(2)
    df["cash_w"] = np.maximum(0, 1 - df["spy_w"] - df["gld_w"]).round(2)

    # Portfolio return: weight * return (cash earns 0, matching daily_update.py)
    df["portfolio_return"] = (df["spy_w"] * df["spy_ret"] + df["gld_w"] * df["gld_ret"]).round(6)

    # Filter to common start date and up to 2026-03-26 (before existing entry)
    df = df.loc[COMMON_START_DATE:"2026-03-26"]
    # Drop first row if return is NaN (first day has no prior close)
    df = df.dropna(subset=["portfolio_return"])

    entries = []
    for date_idx, row in df.iterrows():
        date_str = str(date_idx.date())
        entry = {
            "data_date": date_str,
            "trade_date": date_str,
            "weights": {
                "SPY": float(row["spy_w"]),
                "GLD": float(row["gld_w"]),
            },
            "portfolio_return": float(row["portfolio_return"]),
            "cash_weight": float(row["cash_w"]),
            "spy_close": round(float(row["spy_close"]), 2),
            "gld_close": round(float(row["gld_close"]), 2),
            "spy_open": round(float(row["spy_open"]), 2) if pd.notna(row["spy_open"]) else None,
            "gld_open": round(float(row["gld_open"]), 2) if pd.notna(row["gld_open"]) else None,
        }
        entries.append(entry)

    print(f"  Generated {len(entries)} entries ({entries[0]['data_date']} to {entries[-1]['data_date']})")

    # Quick stats
    rets = [e["portfolio_return"] for e in entries if e["portfolio_return"] is not None]
    cum = 1.0
    for r in rets:
        cum *= (1 + r)
    years = len(rets) / 252
    ann_ret = (cum ** (1 / years) - 1) * 100 if years > 0 else 0
    daily_vol = np.std(rets, ddof=1)
    sharpe = np.mean(rets) / daily_vol * np.sqrt(252) if daily_vol > 0 else 0
    print(f"  Cumulative: {(cum - 1) * 100:.1f}%, Ann. Return: {ann_ret:.1f}%, Sharpe: {sharpe:.2f}")

    return entries


def compute_taiwan_hybrid_leverage(tw50, vix):
    """Generate daily entries for taiwan_hybrid_leverage strategy.

    Formula (from daily_update.py lines 361-393):
        base_weight = 8.63 / VIX(T-1)        # Taiwan uses previous day VIX
        rv22_tw = std(returns_tw, 22d) * sqrt(252)
        vix_percentile = percentile_rank(VIX, 252d rolling)
        leverage = 1.5 if rv22_tw < 0.20 and vix_percentile < 0.30 else 1.0
        weight = min(base_weight * leverage, 1.0)
        portfolio_return = weight * r_tw
    """
    print("\nComputing taiwan_hybrid_leverage entries...")

    tw50_close = tw50["Close"].rename("tw50_close")
    vix_close = vix["Close"].rename("vix_close")
    tw50_open = tw50["Open"].rename("tw50_open")

    # Build DataFrame on 0050.TW trading dates
    df = pd.DataFrame(index=tw50_close.index)
    df["tw50_close"] = tw50_close
    df["tw50_open"] = tw50_open

    # Taiwan uses PREVIOUS day VIX (cross-market lag)
    # Align VIX to TW dates by forward-filling
    vix_df = pd.DataFrame({"vix_close": vix_close})
    # Reindex VIX to all calendar days, forward fill, then select TW dates
    all_dates = pd.date_range(vix_df.index.min(), vix_df.index.max(), freq="D")
    vix_daily = vix_df.reindex(all_dates).ffill()

    # For each TW trading date, use the PREVIOUS calendar day's VIX
    # (i.e., the most recent VIX value before this TW trading day)
    prev_day_vix = []
    for d in df.index:
        # Find the VIX value from the day before (or most recent available)
        prev_dates = vix_daily.loc[:d - pd.Timedelta(days=1)]
        if len(prev_dates) > 0:
            prev_day_vix.append(float(prev_dates["vix_close"].iloc[-1]))
        else:
            prev_day_vix.append(np.nan)
    df["vix_prev"] = prev_day_vix

    df = df.dropna(subset=["tw50_close", "vix_prev"])

    # Compute daily returns
    df["tw50_ret"] = df["tw50_close"].pct_change()

    # 22-day rolling realized volatility (annualized)
    df["rv22_tw"] = df["tw50_ret"].rolling(22).std() * np.sqrt(252)

    # VIX 252-day rolling percentile
    # For each day, compute what percentile the current VIX is in the past 252 days
    # We need VIX history, not the lagged VIX for TW
    # Actually the daily_update.py uses vix_level (current VIX) for percentile
    # But for TW strategy it uses vix_prev for base weight
    # Let me re-read the code...
    # Line 372-376: vix_hist = vix_data["close"], vix_percentile = (vix_252 < vix_level).sum() / len(vix_252)
    # vix_level is the CURRENT VIX level (not lagged)
    # But for Taiwan, the "current" VIX available is the previous day's VIX
    # So we use vix_prev for percentile too (same VIX value used throughout)

    # Build rolling VIX percentile using the VIX values available to TW
    vix_percentiles = []
    for i in range(len(df)):
        if i < 252:
            vix_percentiles.append(0.5)  # conservative fallback matching daily_update.py
        else:
            vix_window = df["vix_prev"].iloc[i - 252:i + 1].values
            current_vix = df["vix_prev"].iloc[i]
            pctl = float((vix_window[:-1] > current_vix).sum()) / 252
            # daily_update.py: (vix_252 < vix_level).sum() / len(vix_252)
            # This gives the fraction of past values BELOW current
            pctl = float((vix_window[:-1] < current_vix).sum()) / 252
            vix_percentiles.append(pctl)
    df["vix_percentile"] = vix_percentiles

    # Base weight: 8.63 / VIX(T-1)
    df["base_weight"] = 8.63 / df["vix_prev"]

    # Conditional leverage
    df["leverage"] = np.where(
        (df["rv22_tw"] < 0.20) & (df["vix_percentile"] < 0.30),
        1.5,
        1.0
    )

    # Final weight
    df["tw_w"] = np.minimum(df["base_weight"] * df["leverage"], 1.0).round(2)
    df["cash_w"] = np.maximum(0, 1 - df["tw_w"]).round(2)

    # Portfolio return
    df["portfolio_return"] = (df["tw_w"] * df["tw50_ret"]).round(6)

    # Filter to common start date and up to 2026-03-26
    # Taiwan starts later - find the first date >= COMMON_START_DATE with valid data
    df = df.loc[COMMON_START_DATE:"2026-03-26"]
    df = df.dropna(subset=["portfolio_return", "rv22_tw"])

    entries = []
    for date_idx, row in df.iterrows():
        date_str = str(date_idx.date())
        entry = {
            "data_date": date_str,
            "trade_date": date_str,
            "weights": {
                "0050.TW": float(row["tw_w"]),
            },
            "portfolio_return": float(row["portfolio_return"]),
            "cash_weight": float(row["cash_w"]),
            "tw50_close": round(float(row["tw50_close"]), 2),
            "tw50_open": round(float(row["tw50_open"]), 2) if pd.notna(row["tw50_open"]) else None,
        }
        entries.append(entry)

    print(f"  Generated {len(entries)} entries ({entries[0]['data_date']} to {entries[-1]['data_date']})")

    # Quick stats
    rets = [e["portfolio_return"] for e in entries if e["portfolio_return"] is not None]
    cum = 1.0
    for r in rets:
        cum *= (1 + r)
    years = len(rets) / 252
    ann_ret = (cum ** (1 / years) - 1) * 100 if years > 0 else 0
    daily_vol = np.std(rets, ddof=1)
    sharpe = np.mean(rets) / daily_vol * np.sqrt(252) if daily_vol > 0 else 0
    print(f"  Cumulative: {(cum - 1) * 100:.1f}%, Ann. Return: {ann_ret:.1f}%, Sharpe: {sharpe:.2f}")

    return entries


def main():
    dry_run = "--dry-run" in sys.argv

    spy, gld, tw50, vix = fetch_data()

    # Generate backfill entries
    vcl_entries = compute_vix_cond_leverage(spy, gld, vix)
    thl_entries = compute_taiwan_hybrid_leverage(tw50, vix)

    if dry_run:
        print("\n=== DRY RUN — not writing to paper_trading.json ===")
        print(f"  vix_cond_leverage: {len(vcl_entries)} entries ready")
        print(f"  taiwan_hybrid_leverage: {len(thl_entries)} entries ready")
        return

    # Load existing paper_trading.json
    pt_path = PROJECT / "storage" / "paper_trading.json"
    pt = json.loads(pt_path.read_text())

    # Merge backfill entries with existing entries
    for strat_id, new_entries in [
        ("vix_cond_leverage", vcl_entries),
        ("taiwan_hybrid_leverage", thl_entries),
    ]:
        if strat_id not in pt:
            pt[strat_id] = {"entries": [], "initial_capital": 1000000}

        existing_dates = {e.get("data_date") for e in pt[strat_id]["entries"]}
        # Only add entries for dates not already present
        added = 0
        for entry in new_entries:
            if entry["data_date"] not in existing_dates:
                added += 1

        # Prepend backfill entries before existing entries
        backfill = [e for e in new_entries if e["data_date"] not in existing_dates]
        pt[strat_id]["entries"] = backfill + pt[strat_id]["entries"]
        print(f"\n  {strat_id}: added {added} backfill entries, total = {len(pt[strat_id]['entries'])}")

    # Write back
    pt_path.write_text(json.dumps(pt, indent=2, ensure_ascii=False))
    print(f"\n✓ paper_trading.json updated")

    # Recalculate metrics
    print("\nRecalculating strategy metrics...")
    sys.path.insert(0, str(PROJECT / "scripts"))
    from recalc_metrics import recalc_all
    recalc_all()
    print("\n✓ strategy_metrics.json updated")


if __name__ == "__main__":
    main()
