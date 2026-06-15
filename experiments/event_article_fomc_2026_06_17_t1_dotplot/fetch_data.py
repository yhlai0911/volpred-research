"""
fetch_data.py — event_article_fomc_2026_06_17_t1_dotplot
Fetches: ^MOVE, ^VIX, ^VIX9D, TLT, SHV, ^IRX, SPY
for the FOMC T-1 tail-hedging article (2026-06-16).

yfinance multi-ticker download sorts columns ALPHABETICALLY.
We use the original ticker names as column keys, not positional rename.
"""
import json
import warnings
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── parameters ───────────────────────────────────────────────────────────────
START = "2003-01-01"
END   = "2026-06-17"  # up to today's data (T-1 = 2026-06-16, latest available = 2026-06-15)
FOMC_DATES_PAST = [
    # Past 6 FOMC announcement dates (Eastern time)
    "2025-09-17",   # Sep 2025 — cut 25bp
    "2025-10-29",   # Oct 2025 — cut 25bp
    "2025-12-10",   # Dec 2025 — cut 25bp
    "2026-01-29",   # Jan 2026 — hold
    "2026-03-19",   # Mar 2026 — hold
    "2026-04-30",   # Apr 2026 — hold
]
TARGET_FOMC = "2026-06-17"

TICKER_LIST = ["^MOVE", "^VIX", "^VIX9D", "TLT", "SHV", "^IRX", "SPY"]

print("Fetching data from yfinance...")
raw = yf.download(
    TICKER_LIST,
    start=START,
    end=END,
    auto_adjust=True,
    progress=False,
)
# yfinance sorts columns alphabetically — keep ticker names as-is
close = raw["Close"].copy()
close.index = close.index.tz_localize(None)

# Verify we have the right columns
print(f"  Columns: {close.columns.tolist()}")
print(f"  Rows: {len(close)}, Latest: {close.index[-1].date()}")
print(close[["^MOVE","^VIX","^VIX9D","TLT","SHV","SPY"]].tail(3))

# ─── today's snapshot (latest available row) ─────────────────────────────────
today_row = close.iloc[-1]
today_date = str(close.index[-1].date())

cutoff_3m  = pd.Timestamp(today_date) - pd.DateOffset(days=90)
cutoff_35d = pd.Timestamp(today_date) - pd.DateOffset(days=35)

# MOVE
move_series = close["^MOVE"].dropna()
move_today  = float(today_row["^MOVE"])
move_3m     = move_series[move_series.index >= cutoff_3m]
move_3m_mean = float(move_3m.mean())
move_pct_rank = float((move_series < move_today).mean() * 100)

# VIX
vix_series  = close["^VIX"].dropna()
vix_today   = float(today_row["^VIX"])
vix_3m      = vix_series[vix_series.index >= cutoff_3m]
vix_3m_mean = float(vix_3m.mean())
vix_pct_rank = float((vix_series < vix_today).mean() * 100)

# VIX9D
vix9d_series  = close["^VIX9D"].dropna()
vix9d_today   = float(today_row["^VIX9D"])
vix9d_3m      = vix9d_series[vix9d_series.index >= cutoff_3m]
vix9d_3m_mean = float(vix9d_3m.mean())
vix9d_vix_ratio = vix9d_today / vix_today

# TLT
tlt_series  = close["TLT"].dropna()
tlt_today   = float(today_row["TLT"])
tlt_30d     = tlt_series[tlt_series.index >= cutoff_35d]
tlt_rv      = float(tlt_30d.pct_change().dropna().std() * np.sqrt(252) * 100)

# SHV / IRX
shv_today = float(today_row["SHV"])
irx_val   = today_row["^IRX"]
irx_today = float(irx_val) if not pd.isna(irx_val) else None

# SPY
spy_today = float(today_row["SPY"])

print(f"\nToday ({today_date}):")
print(f"  ^MOVE: {move_today:.2f}  3m mean: {move_3m_mean:.2f}  pct_rank: {move_pct_rank:.1f}%")
print(f"  ^VIX:  {vix_today:.2f}   3m mean: {vix_3m_mean:.2f}   pct_rank: {vix_pct_rank:.1f}%")
print(f"  ^VIX9D:{vix9d_today:.2f}  3m mean: {vix9d_3m_mean:.2f}   VIX9D/VIX: {vix9d_vix_ratio:.4f}")
print(f"  TLT:   {tlt_today:.2f}  30d RV: {tlt_rv:.2f}%")
print(f"  SHV:   {shv_today:.4f}  IRX: {irx_today}")
print(f"  SPY:   {spy_today:.2f}")

# ─── FOMC T-1 cross-section (past 6 meetings) ─────────────────────────────────
def nearest_at_or_before(df, target_dt):
    """Return last index entry at or before target_dt."""
    mask = df.index <= pd.Timestamp(target_dt)
    if mask.any():
        return df[mask].index[-1]
    return None

def nth_trading_day_after(df, start_dt, n=5):
    """Return the nth row AFTER start_dt (0-indexed)."""
    after = df[df.index > pd.Timestamp(start_dt)]
    if len(after) >= n:
        return after.index[n - 1]
    elif len(after) > 0:
        return after.index[-1]
    return None

print("\nFOMC T-1 cross-section:")
fomc_data = []
for fd in FOMC_DATES_PAST:
    dt = datetime.strptime(fd, "%Y-%m-%d")
    dt_t1 = dt - timedelta(days=1)

    t1_idx = nearest_at_or_before(close, dt_t1)
    t0_idx = nearest_at_or_before(close, dt)
    t5_idx = nth_trading_day_after(close, dt, n=5)

    row = {"fomc_date": fd}

    def safe(series, idx):
        try:
            v = float(series.loc[idx])
            return v if not np.isnan(v) else None
        except Exception:
            return None

    if t1_idx is not None:
        row["t1_date"]  = str(t1_idx.date())
        row["t1_MOVE"]  = safe(close["^MOVE"], t1_idx)
        row["t1_VIX"]   = safe(close["^VIX"],  t1_idx)
        row["t1_VIX9D"] = safe(close["^VIX9D"], t1_idx)
        row["t1_SPY"]   = safe(close["SPY"],    t1_idx)

    if t0_idx is not None:
        row["t0_date"] = str(t0_idx.date())
        row["t0_SPY"]  = safe(close["SPY"], t0_idx)
        row["t0_VIX"]  = safe(close["^VIX"], t0_idx)
        row["t0_MOVE"] = safe(close["^MOVE"], t0_idx)

    if t5_idx is not None:
        row["t5_date"] = str(t5_idx.date())
        row["t5_SPY"]  = safe(close["SPY"], t5_idx)

    # T-1 to T0 and T0 to T+5 SPY returns
    if row.get("t1_SPY") and row.get("t0_SPY"):
        row["spy_t1_to_t0_pct"] = (row["t0_SPY"] - row["t1_SPY"]) / row["t1_SPY"] * 100
    if row.get("t0_SPY") and row.get("t5_SPY"):
        row["spy_t0_to_t5_pct"] = (row["t5_SPY"] - row["t0_SPY"]) / row["t0_SPY"] * 100

    fomc_data.append(row)
    print(f"  {fd}: T-1 MOVE={row.get('t1_MOVE'):.2f}, VIX={row.get('t1_VIX'):.2f}, VIX9D={row.get('t1_VIX9D')}, SPY 5d={row.get('spy_t0_to_t5_pct')}")

# ─── Cross-section stats ───────────────────────────────────────────────────────
t1_move_vals = [r["t1_MOVE"] for r in fomc_data if r.get("t1_MOVE") is not None]
t1_vix_vals  = [r["t1_VIX"]  for r in fomc_data if r.get("t1_VIX")  is not None]
spy_5d_vals  = [r["spy_t0_to_t5_pct"] for r in fomc_data if r.get("spy_t0_to_t5_pct") is not None]

# ─── Save raw close for figure script ─────────────────────────────────────────
out_csv = "/Users/yhlai0911/Desktop/volpred-research/experiments/event_article_fomc_2026_06_17_t1_dotplot/raw_close.csv"
close.to_csv(out_csv)
print(f"\nSaved raw data to {out_csv}")

# ─── Build results.json ───────────────────────────────────────────────────────
results = {
    "data_as_of": today_date,
    "today": {
        "MOVE": move_today,
        "MOVE_3m_mean": move_3m_mean,
        "MOVE_pct_rank_full_history": move_pct_rank,
        "VIX": vix_today,
        "VIX_3m_mean": vix_3m_mean,
        "VIX_pct_rank_full_history": vix_pct_rank,
        "VIX9D": vix9d_today,
        "VIX9D_3m_mean": vix9d_3m_mean,
        "VIX9D_VIX_ratio": vix9d_vix_ratio,
        "TLT": tlt_today,
        "TLT_30d_rv_annualized_pct": tlt_rv,
        "SHV": shv_today,
        "IRX_pct": irx_today,
        "SPY": spy_today,
    },
    "fomc_t1_cross_section": fomc_data,
    "fomc_t1_MOVE_stats": {
        "n": len(t1_move_vals),
        "mean": float(np.mean(t1_move_vals)) if t1_move_vals else None,
        "median": float(np.median(t1_move_vals)) if t1_move_vals else None,
        "min": float(np.min(t1_move_vals)) if t1_move_vals else None,
        "max": float(np.max(t1_move_vals)) if t1_move_vals else None,
        "today_vs_mean_diff": move_today - float(np.mean(t1_move_vals)) if t1_move_vals else None,
    },
    "fomc_t1_VIX_stats": {
        "n": len(t1_vix_vals),
        "mean": float(np.mean(t1_vix_vals)) if t1_vix_vals else None,
        "median": float(np.median(t1_vix_vals)) if t1_vix_vals else None,
    },
    "fomc_spy_t0_to_t5_stats": {
        "n": len(spy_5d_vals),
        "mean_pct": float(np.mean(spy_5d_vals)) if spy_5d_vals else None,
        "positive_freq": float(np.mean([v > 0 for v in spy_5d_vals])) if spy_5d_vals else None,
    },
    "target_fomc": TARGET_FOMC,
    "note": "data_as_of is last trading day available in yfinance (may be T-2 or T-1 depending on time of fetch)",
}

out_json = "/Users/yhlai0911/Desktop/volpred-research/experiments/event_article_fomc_2026_06_17_t1_dotplot/results.json"
with open(out_json, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"Saved results to {out_json}")
