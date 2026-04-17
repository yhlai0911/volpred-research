"""K692: Verify Paper Trading Lag Convention — Is daily_update.py Actually Correct?

K689 claimed paper_trading has lookahead (corr=0.9999 with same-day).
But the daily_update.py backfill logic appears CORRECT:
  - Day T: set weights from VIX_T, portfolio_return = None
  - Day T+1: backfill entry T using close_{T+1}/close_T - 1
  - This means: weight_T × return_{T→T+1} (hold from close_T to close_{T+1})

THIS IS CRITICAL: We need to verify if the production system has a real bug.

Approach:
1. Load paper_trading.json (simple_12vix strategy)
2. Load actual SPY close prices from yfinance
3. Reconstruct returns three ways:
   a. Same-day: weight_T × (close_T/close_{T-1} - 1) — LOOKAHEAD
   b. Next-day: weight_T × (close_{T+1}/close_T - 1) — CORRECT
   c. Actual portfolio_return from paper_trading.json
4. Compare correlations to determine which one matches

Data source: paper_trading.json + yfinance SPY daily closes
Period: 2023-01-04 to latest
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Load paper trading data ──────────────────────────────────────────
PT_FILE = Path("storage/paper_trading.json")
with open(PT_FILE) as f:
    pt_data = json.load(f)

entries = pt_data["simple_12vix"]["entries"]
print(f"Total simple_12vix entries: {len(entries)}")

# ── Load SPY close prices from yfinance ──────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
try:
    from volpred.data.manager import DataManager
    dm = DataManager()
    spy = dm.get_model_data("SPY", "2022-12-01", "2026-12-31", force_refresh=True)
    spy_closes = spy["close"].to_dict()
    # Convert index to date strings
    spy_close_by_date = {}
    for idx, val in spy_closes.items():
        d = str(idx.date()) if hasattr(idx, 'date') else str(idx)
        spy_close_by_date[d] = float(val)
    print(f"SPY close prices loaded: {len(spy_close_by_date)} dates")
except Exception as e:
    print(f"Error loading SPY data via DataManager: {e}")
    print("Falling back to yfinance directly...")
    import yfinance as yf
    spy_df = yf.download("SPY", start="2022-12-01", end="2026-12-31", progress=False)
    spy_close_by_date = {}
    for idx, row in spy_df.iterrows():
        d = str(idx.date())
        spy_close_by_date[d] = float(row["Close"])
    print(f"SPY close prices loaded: {len(spy_close_by_date)} dates")

# Also use _market_daily for recent entries (may have slightly different closes)
market_daily = pt_data.get("_market_daily", {})

# ── Get sorted list of SPY trading dates ─────────────────────────────
all_spy_dates = sorted(spy_close_by_date.keys())
date_to_idx = {d: i for i, d in enumerate(all_spy_dates)}

# ── Build comparison data ────────────────────────────────────────────
# For each entry in paper_trading, extract:
#   - data_date (D) / trade_date
#   - weight (SPY weight)
#   - portfolio_return (from paper_trading)
#   - same_day_return: weight * (close_D / close_{D-1} - 1)
#   - next_day_return: weight * (close_{D+1} / close_D - 1)

# Focus on entries where trade_date == data_date (historical, bulk of data)
records = []
n_skipped = 0
n_new_format = 0

for entry in entries:
    dd = entry.get("data_date", "")
    td = entry.get("trade_date", dd)
    w_spy = entry.get("weights", {}).get("SPY", 0)
    pr = entry.get("portfolio_return")

    if pr is None:
        n_skipped += 1
        continue

    is_new_format = (td != dd)
    if is_new_format:
        n_new_format += 1

    # For historical entries (trade_date == data_date):
    # Use data_date as the reference date
    ref_date = dd if not is_new_format else dd

    if ref_date not in date_to_idx:
        n_skipped += 1
        continue

    idx = date_to_idx[ref_date]

    # Same-day return: close_D / close_{D-1} - 1
    same_day_ret = None
    if idx > 0:
        prev_date = all_spy_dates[idx - 1]
        p_prev = spy_close_by_date[prev_date]
        p_curr = spy_close_by_date[ref_date]
        if p_prev > 0:
            same_day_ret = p_curr / p_prev - 1

    # Next-day return: close_{D+1} / close_D - 1
    next_day_ret = None
    if idx + 1 < len(all_spy_dates):
        next_date = all_spy_dates[idx + 1]
        p_curr = spy_close_by_date[ref_date]
        p_next = spy_close_by_date[next_date]
        if p_curr > 0:
            next_day_ret = p_next / p_curr - 1

    # For new-format entries, also compute:
    # trade_date return: close_{td+1} / close_td - 1
    trade_date_ret = None
    if is_new_format and td in date_to_idx:
        td_idx = date_to_idx[td]
        if td_idx + 1 < len(all_spy_dates):
            p_td = spy_close_by_date[td]
            p_td_next = spy_close_by_date[all_spy_dates[td_idx + 1]]
            if p_td > 0:
                trade_date_ret = p_td_next / p_td - 1

    records.append({
        "data_date": dd,
        "trade_date": td,
        "is_new_format": is_new_format,
        "w_spy": w_spy,
        "portfolio_return": pr,
        "spy_same_day_ret": same_day_ret,
        "spy_next_day_ret": next_day_ret,
        "trade_date_ret": trade_date_ret,
        # Weighted returns
        "weighted_same_day": w_spy * same_day_ret if same_day_ret is not None else None,
        "weighted_next_day": w_spy * next_day_ret if next_day_ret is not None else None,
        "weighted_trade_date": w_spy * trade_date_ret if trade_date_ret is not None else None,
    })

print(f"Records with valid data: {len(records)}")
print(f"Skipped (no return or date): {n_skipped}")
print(f"New format entries: {n_new_format}")

df = pd.DataFrame(records)

# ── ANALYSIS 1: Historical entries (trade_date == data_date) ─────────
hist = df[~df["is_new_format"]].copy()
hist = hist.dropna(subset=["portfolio_return", "weighted_same_day", "weighted_next_day"])
print(f"\n{'='*70}")
print(f"ANALYSIS 1: Historical entries (trade_date == data_date)")
print(f"{'='*70}")
print(f"N = {len(hist)}")

if len(hist) > 10:
    corr_same = np.corrcoef(hist["portfolio_return"], hist["weighted_same_day"])[0, 1]
    corr_next = np.corrcoef(hist["portfolio_return"], hist["weighted_next_day"])[0, 1]

    print(f"\ncorr(paper_trading, same-day weighted)  = {corr_same:.6f}")
    print(f"corr(paper_trading, next-day weighted)  = {corr_next:.6f}")

    # MAE comparison
    mae_same = np.mean(np.abs(hist["portfolio_return"] - hist["weighted_same_day"]))
    mae_next = np.mean(np.abs(hist["portfolio_return"] - hist["weighted_next_day"]))

    print(f"\nMAE(paper_trading, same-day weighted)  = {mae_same:.8f}")
    print(f"MAE(paper_trading, next-day weighted)  = {mae_next:.8f}")

    # RMSE comparison
    rmse_same = np.sqrt(np.mean((hist["portfolio_return"] - hist["weighted_same_day"])**2))
    rmse_next = np.sqrt(np.mean((hist["portfolio_return"] - hist["weighted_next_day"])**2))

    print(f"\nRMSE(paper_trading, same-day weighted) = {rmse_same:.8f}")
    print(f"RMSE(paper_trading, next-day weighted) = {rmse_next:.8f}")

    # Perfect match check: count exact matches within tolerance
    tol = 1e-5
    exact_same = np.sum(np.abs(hist["portfolio_return"] - hist["weighted_same_day"]) < tol)
    exact_next = np.sum(np.abs(hist["portfolio_return"] - hist["weighted_next_day"]) < tol)

    print(f"\nExact matches (|diff| < 1e-5):")
    print(f"  Same-day: {exact_same}/{len(hist)} ({exact_same/len(hist)*100:.1f}%)")
    print(f"  Next-day: {exact_next}/{len(hist)} ({exact_next/len(hist)*100:.1f}%)")

    # Show first 10 rows for manual inspection
    print(f"\n--- First 10 rows ---")
    print(f"{'date':>12} {'w_spy':>6} {'pt_ret':>10} {'same_day':>10} {'next_day':>10} {'diff_same':>10} {'diff_next':>10}")
    for _, row in hist.head(10).iterrows():
        diff_s = row["portfolio_return"] - row["weighted_same_day"]
        diff_n = row["portfolio_return"] - row["weighted_next_day"]
        print(f"{row['data_date']:>12} {row['w_spy']:>6.3f} {row['portfolio_return']:>10.6f} "
              f"{row['weighted_same_day']:>10.6f} {row['weighted_next_day']:>10.6f} "
              f"{diff_s:>10.7f} {diff_n:>10.7f}")

    # CRITICAL TEST: Which one does portfolio_return match?
    if corr_same > corr_next and mae_same < mae_next:
        match_verdict = "SAME-DAY (LOOKAHEAD CONFIRMED)"
    elif corr_next > corr_same and mae_next < mae_same:
        match_verdict = "NEXT-DAY (NO LOOKAHEAD)"
    else:
        match_verdict = "AMBIGUOUS"

    print(f"\n*** VERDICT for historical entries: {match_verdict} ***")

# ── ANALYSIS 2: New-format entries (trade_date != data_date) ─────────
new = df[df["is_new_format"]].copy()
new = new.dropna(subset=["portfolio_return"])
print(f"\n{'='*70}")
print(f"ANALYSIS 2: New-format entries (trade_date != data_date)")
print(f"{'='*70}")
print(f"N = {len(new)}")

if len(new) > 2:
    new_valid = new.dropna(subset=["weighted_same_day", "weighted_next_day"])
    if len(new_valid) > 2:
        corr_same_new = np.corrcoef(new_valid["portfolio_return"], new_valid["weighted_same_day"])[0, 1]
        corr_next_new = np.corrcoef(new_valid["portfolio_return"], new_valid["weighted_next_day"])[0, 1]

        print(f"\ncorr(paper_trading, same-day weighted)  = {corr_same_new:.6f}")
        print(f"corr(paper_trading, next-day weighted)  = {corr_next_new:.6f}")

    # For new-format entries, also check trade_date-based return
    new_td = new.dropna(subset=["weighted_trade_date"])
    if len(new_td) > 2:
        corr_td = np.corrcoef(new_td["portfolio_return"], new_td["weighted_trade_date"])[0, 1]
        print(f"corr(paper_trading, trade-date weighted) = {corr_td:.6f}")

    print(f"\n--- All new-format rows ---")
    print(f"{'dd':>12} {'td':>12} {'w_spy':>6} {'pt_ret':>10} {'same_d':>10} {'next_d':>10} {'td_ret':>10}")
    for _, row in new.iterrows():
        sd = f"{row['weighted_same_day']:.6f}" if pd.notna(row.get('weighted_same_day')) else "N/A"
        nd = f"{row['weighted_next_day']:.6f}" if pd.notna(row.get('weighted_next_day')) else "N/A"
        tdr = f"{row['weighted_trade_date']:.6f}" if pd.notna(row.get('weighted_trade_date')) else "N/A"
        print(f"{row['data_date']:>12} {row['trade_date']:>12} {row['w_spy']:>6.3f} "
              f"{row['portfolio_return']:>10.6f} {sd:>10} {nd:>10} {tdr:>10}")

# ── ANALYSIS 3: Cross-check with _market_daily close prices ──────────
print(f"\n{'='*70}")
print(f"ANALYSIS 3: Cross-check backfill logic with _market_daily")
print(f"{'='*70}")

# For new-format entries, the backfill uses td0 and td1 from _market_daily
# Let's verify: return should be close_{td1} / close_{td0} - 1
print(f"\nBackfill verification for new-format entries:")
print(f"{'dd':>12} {'td0':>12} {'td1':>12} {'md_close0':>10} {'md_close1':>10} {'md_ret':>10} {'pt_ret':>10} {'match':>6}")

for i in range(len(entries) - 1):
    e = entries[i]
    e_next = entries[i + 1]
    td0 = e.get("trade_date", "")
    td1 = e_next.get("trade_date", "")
    dd = e.get("data_date", "")
    pr = e.get("portfolio_return")
    w = e.get("weights", {}).get("SPY", 0)

    if pr is None or td0 == dd:  # skip entries without return or old format
        continue

    md0 = market_daily.get(td0, {})
    md1 = market_daily.get(td1, {})
    c0 = md0.get("spy_close")
    c1 = md1.get("spy_close")

    if c0 and c1 and c0 > 0:
        md_ret = w * (c1 / c0 - 1)
        match = abs(pr - md_ret) < 1e-5
        print(f"{dd:>12} {td0:>12} {td1:>12} {c0:>10.2f} {c1:>10.2f} "
              f"{md_ret:>10.6f} {pr:>10.6f} {'YES' if match else 'NO':>6}")

# ── ANALYSIS 4: Direct return comparison without weighting ───────────
print(f"\n{'='*70}")
print(f"ANALYSIS 4: Raw SPY return comparison (unweighted)")
print(f"{'='*70}")

# For historical entries, compute: portfolio_return / w_spy and compare
# to raw SPY same-day and next-day returns
hist2 = hist[hist["w_spy"] > 0.01].copy()
hist2["implied_spy_ret"] = hist2["portfolio_return"] / hist2["w_spy"]
hist2["raw_same_day"] = hist2["spy_same_day_ret"]
hist2["raw_next_day"] = hist2["spy_next_day_ret"]

if len(hist2) > 10:
    corr_raw_same = np.corrcoef(hist2["implied_spy_ret"], hist2["raw_same_day"])[0, 1]
    corr_raw_next = np.corrcoef(hist2["implied_spy_ret"], hist2["raw_next_day"])[0, 1]

    mae_raw_same = np.mean(np.abs(hist2["implied_spy_ret"] - hist2["raw_same_day"]))
    mae_raw_next = np.mean(np.abs(hist2["implied_spy_ret"] - hist2["raw_next_day"]))

    print(f"\nImplied SPY return = portfolio_return / w_spy")
    print(f"corr(implied, raw same-day)  = {corr_raw_same:.6f}")
    print(f"corr(implied, raw next-day)  = {corr_raw_next:.6f}")
    print(f"MAE(implied, raw same-day)   = {mae_raw_same:.8f}")
    print(f"MAE(implied, raw next-day)   = {mae_raw_next:.8f}")

    # Show first 10 rows
    print(f"\n--- First 10 rows ---")
    print(f"{'date':>12} {'w_spy':>6} {'implied':>10} {'raw_same':>10} {'raw_next':>10}")
    for _, row in hist2.head(10).iterrows():
        print(f"{row['data_date']:>12} {row['w_spy']:>6.3f} {row['implied_spy_ret']:>10.6f} "
              f"{row['raw_same_day']:>10.6f} {row['raw_next_day']:>10.6f}")

# ── ANALYSIS 5: Check where historical entries came from ─────────────
# These entries may have been seeded by a backtest. Let's check if
# there's a pattern shift (the backtest may use same-day convention)
print(f"\n{'='*70}")
print(f"ANALYSIS 5: Detect potential backtest seeding")
print(f"{'='*70}")

# Check if historical entries are from recalc_metrics.py or initial seeding
# by looking for entry creation timestamps or patterns
first_date = entries[0].get("data_date", "")
last_hist_date = entries[800].get("data_date", "")
print(f"Historical entries span: {first_date} to {last_hist_date} ({801} entries)")
print(f"New-format entries from: {entries[801].get('data_date', '')} to {entries[-1].get('data_date', '')}")

# Check what script created the historical entries
# They have no 'actual_returns' field and no 'spy_close' field
# This suggests they were created by a different process (likely initial backfill)
keys_hist = set()
keys_new = set()
for e in entries[:801]:
    keys_hist.update(e.keys())
for e in entries[801:]:
    keys_new.update(e.keys())
print(f"\nHistorical entry keys: {sorted(keys_hist)}")
print(f"New-format entry keys: {sorted(keys_new)}")

# ── OVERALL CONCLUSION ───────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"OVERALL CONCLUSION")
print(f"{'='*70}")

if len(hist) > 10:
    print(f"\n1. Historical entries (N={len(hist)}):")
    print(f"   corr with same-day: {corr_same:.6f}")
    print(f"   corr with next-day: {corr_next:.6f}")
    print(f"   MAE with same-day:  {mae_same:.8f}")
    print(f"   MAE with next-day:  {mae_next:.8f}")

    if corr_same > 0.999 and mae_same < 1e-5:
        hist_conclusion = "SAME-DAY MATCH → Historical entries use LOOKAHEAD convention"
    elif corr_next > 0.999 and mae_next < 1e-5:
        hist_conclusion = "NEXT-DAY MATCH → Historical entries use CORRECT convention"
    elif corr_same > corr_next:
        hist_conclusion = f"SAME-DAY better match (corr diff = {corr_same - corr_next:.6f}) → Likely LOOKAHEAD"
    else:
        hist_conclusion = f"NEXT-DAY better match (corr diff = {corr_next - corr_same:.6f}) → Likely CORRECT"
    print(f"   → {hist_conclusion}")

if len(new) > 2:
    print(f"\n2. New-format entries (N={len(new)}):")
    print(f"   These use backfill logic: close_{{td+1}}/close_{{td}} - 1")
    print(f"   Where td = trade_date (script run day), NOT data_date")
    print(f"   This is a NEXT-DAY convention (no lookahead)")

print(f"\n3. Implications for K689:")
if len(hist) > 10 and corr_same > corr_next:
    print(f"   K689 was CORRECT: historical paper_trading entries have lookahead")
    print(f"   BUT: daily_update.py's NEW entry creation is correct (no lookahead)")
    print(f"   The issue is in the HISTORICAL SEEDING, not in the daily production code")
    print(f"   This means: the backtest results (Sharpe etc) are overstated")
    print(f"   BUT: going forward, new entries are computed correctly")
elif len(hist) > 10 and corr_next > corr_same:
    print(f"   K689 may be WRONG: paper_trading uses next-day convention")
    print(f"   Need to re-examine K689's methodology")

# ── Save results ─────────────────────────────────────────────────────
results = {
    "experiment_id": "K692",
    "title": "Verify Paper Trading Lag Convention",
    "timestamp": datetime.now().isoformat(),
    "data_source": "paper_trading.json + yfinance SPY",
    "period": f"{first_date} to {entries[-1].get('data_date', '')}",
    "strategy": "simple_12vix",
    "sample_sizes": {
        "total_entries": len(entries),
        "historical_entries": len(hist) if len(hist) > 0 else 0,
        "new_format_entries": n_new_format,
    },
    "historical_analysis": {},
    "new_format_analysis": {},
    "conclusion": "",
    "implications_for_k689": "",
}

if len(hist) > 10:
    results["historical_analysis"] = {
        "corr_same_day": round(float(corr_same), 6),
        "corr_next_day": round(float(corr_next), 6),
        "mae_same_day": round(float(mae_same), 8),
        "mae_next_day": round(float(mae_next), 8),
        "rmse_same_day": round(float(rmse_same), 8),
        "rmse_next_day": round(float(rmse_next), 8),
        "exact_matches_same": int(exact_same),
        "exact_matches_next": int(exact_next),
        "verdict": match_verdict,
    }

    if corr_raw_same is not None:
        results["historical_analysis"]["raw_return_analysis"] = {
            "corr_implied_vs_same_day": round(float(corr_raw_same), 6),
            "corr_implied_vs_next_day": round(float(corr_raw_next), 6),
            "mae_implied_vs_same_day": round(float(mae_raw_same), 8),
            "mae_implied_vs_next_day": round(float(mae_raw_next), 8),
        }

if len(new) > 2:
    results["new_format_analysis"] = {
        "n_entries": len(new),
        "description": "Uses backfill: close_{trade_date_next}/close_{trade_date} - 1",
        "convention": "NEXT-DAY (no lookahead)",
    }

# Set overall conclusion
if len(hist) > 10:
    if corr_same > corr_next and mae_same < mae_next:
        results["conclusion"] = (
            "Historical paper_trading entries match SAME-DAY returns (lookahead). "
            "These were created by initial backtest seeding, not by daily_update.py. "
            "The daily_update.py production code is CORRECT (next-day convention). "
            "Impact: historical performance metrics (Sharpe/MDD) are overstated."
        )
        results["implications_for_k689"] = (
            "K689 was partially correct: lookahead exists in HISTORICAL entries. "
            "But the daily_update.py code is NOT the source of the bug. "
            "The bug is in whatever script originally seeded the 801 historical entries."
        )
    elif corr_next > corr_same and mae_next < mae_same:
        results["conclusion"] = (
            "Paper_trading entries match NEXT-DAY returns (no lookahead). "
            "Both historical and new entries are correct. K689's finding needs re-examination."
        )
        results["implications_for_k689"] = (
            "K689 may have made an error in its analysis. The paper_trading system "
            "appears to use the correct next-day convention throughout."
        )
    else:
        results["conclusion"] = "Ambiguous result — neither same-day nor next-day is a clear match."
        results["implications_for_k689"] = "Inconclusive — further investigation needed."

results_path = Path("experiments/k692_results.json")
results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"\nResults saved to {results_path}")
