"""Backfill 3-year paper trading history for adaptive_tier strategy.

K595: VIX regime switching on 50/50 SPY/GLD:
  VIX < 15  → VIX-Conditional Leverage mode (1.5x on 12/VIX/2 base)
  15 ≤ VIX ≤ 20 → Standard 12/VIX/2 mode
  VIX > 20  → Piecewise exit (fully cash, w=0)
Monthly rebalance.

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2023-01-04 to present

Usage:
    uv run python scripts/backfill_adaptive_tier.py
    uv run python scripts/backfill_adaptive_tier.py --dry-run
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
    start = "2022-06-01"  # extra history before COMMON_START
    end = datetime.now().strftime("%Y-%m-%d")

    spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    gld = yf.download("GLD", start=start, end=end, auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)

    # Flatten multi-level columns if present
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    print(f"  SPY: {len(spy)} rows ({spy.index[0].date()} to {spy.index[-1].date()})")
    print(f"  GLD: {len(gld)} rows ({gld.index[0].date()} to {gld.index[-1].date()})")
    print(f"  VIX: {len(vix)} rows ({vix.index[0].date()} to {vix.index[-1].date()})")

    return spy, gld, vix


def compute_adaptive_tier(spy, gld, vix):
    """Generate daily entries for adaptive_tier strategy.

    Formula (matching daily_update.py):
        if VIX < 15:
            base = 12/VIX/2
            w = min(base * 1.5, 1.0)   # leverage mode
        elif VIX <= 20:
            w = 12/VIX/2               # standard mode
        else:
            w = 0.0                     # piecewise exit
        spy_w = w, gld_w = w
        portfolio_return = spy_w * r_spy + gld_w * r_gld
    """
    print("\nComputing adaptive_tier entries...")

    # Build aligned DataFrame
    spy_close = spy["Close"].rename("spy_close")
    gld_close = gld["Close"].rename("gld_close")
    vix_close = vix["Close"].rename("vix_close")

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

    # Compute weights based on VIX regime
    def calc_weight(vix_val):
        if vix_val < 15:
            base = 12.0 / vix_val / 2
            return min(base * 1.5, 1.0)
        elif vix_val <= 20:
            return 12.0 / vix_val / 2
        else:
            return 0.0

    df["w"] = df["vix_close"].apply(calc_weight).round(2)
    df["spy_w"] = df["w"]
    df["gld_w"] = df["w"]
    df["cash_w"] = np.maximum(0, 1 - df["spy_w"] - df["gld_w"]).round(2)

    # Portfolio return
    df["portfolio_return"] = (df["spy_w"] * df["spy_ret"] + df["gld_w"] * df["gld_ret"]).round(6)

    # Determine regime for logging
    def regime_label(vix_val):
        if vix_val < 15:
            return "leverage"
        elif vix_val <= 20:
            return "standard"
        else:
            return "exit"
    df["regime"] = df["vix_close"].apply(regime_label)

    # Filter to common start date and exclude today (today's entry added by daily_update)
    yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = df.loc[COMMON_START_DATE:yesterday]
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

    # Regime breakdown
    regime_counts = df["regime"].value_counts()
    for regime, count in regime_counts.items():
        print(f"    {regime}: {count} days ({count/len(df)*100:.1f}%)")

    # Quick stats
    rets = [e["portfolio_return"] for e in entries if e["portfolio_return"] is not None]
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        cum *= (1 + r)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak
        if dd < max_dd:
            max_dd = dd
    years = len(rets) / 252
    ann_ret = (cum ** (1 / years) - 1) * 100 if years > 0 else 0
    daily_vol = np.std(rets, ddof=1)
    sharpe = np.mean(rets) / daily_vol * np.sqrt(252) if daily_vol > 0 else 0
    print(f"  Cumulative: {(cum - 1) * 100:.1f}%, Ann. Return: {ann_ret:.1f}%, Sharpe: {sharpe:.2f}")
    print(f"  Max Drawdown: {max_dd * 100:.1f}%")

    return entries


def main():
    dry_run = "--dry-run" in sys.argv

    spy, gld, vix = fetch_data()

    # Generate backfill entries
    at_entries = compute_adaptive_tier(spy, gld, vix)

    if dry_run:
        print("\n=== DRY RUN -- not writing to paper_trading.json ===")
        print(f"  adaptive_tier: {len(at_entries)} entries ready")
        return

    # Load existing paper_trading.json
    pt_path = PROJECT / "storage" / "paper_trading.json"
    pt = json.loads(pt_path.read_text())

    strat_id = "adaptive_tier"
    if strat_id not in pt:
        pt[strat_id] = {"entries": [], "initial_capital": 1000000}

    existing_dates = {e.get("data_date") for e in pt[strat_id]["entries"]}
    backfill = [e for e in at_entries if e["data_date"] not in existing_dates]

    # Prepend backfill entries before existing entries
    pt[strat_id]["entries"] = backfill + pt[strat_id]["entries"]
    print(f"\n  {strat_id}: added {len(backfill)} backfill entries, total = {len(pt[strat_id]['entries'])}")

    # Write back
    pt_path.write_text(json.dumps(pt, indent=2, ensure_ascii=False))
    print(f"\n  paper_trading.json updated")

    # Recalculate metrics
    print("\nRecalculating strategy metrics...")
    sys.path.insert(0, str(PROJECT / "scripts"))
    from recalc_metrics import recalc_all
    recalc_all()
    print("\n  strategy_metrics.json updated")


if __name__ == "__main__":
    main()
