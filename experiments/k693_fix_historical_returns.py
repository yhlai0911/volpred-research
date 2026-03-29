"""
K693: Fix Historical Paper Trading Returns (Lookahead Bias Correction)

Background:
K692 identified that 801+ historical paper_trading entries (2022-01 to 2026-03-16)
have same-day lookahead in portfolio_return. In the old format:
  - trade_date == data_date
  - portfolio_return_T = weight_T × (close_T / close_{T-1} - 1)

This is wrong because at date T, the model computes weight_T using data up to T,
but the return close_T/close_{T-1} is KNOWN at date T — it's not a forecast.
The weight should earn the NEXT day's return.

Correct formula:
  - portfolio_return_T = weight_T × (close_{T+1} / close_T - 1)

Fix approach:
  For each old-format entry at index i (where trade_date == data_date):
    1. Get weight_i from entry[i]
    2. Get data_date_i and data_date_{i+1} from consecutive entries
    3. Download actual close prices for both dates from yfinance
    4. Recompute: portfolio_return_i = sum(weight_asset × (close_{i+1} / close_i - 1))
    5. The LAST old-format entry (boundary) cannot be fixed → set to None

Data source: yfinance (historical close prices)
Assets: SPY, GLD, 0050.TW, ^N225
Period: 2022-01-01 to 2026-03-28
"""

import json
import shutil
import os
import sys
from datetime import datetime, timezone
import numpy as np

# ── Paths ──
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PT_PATH = os.path.join(BASE, "storage", "paper_trading.json")
BACKUP_PATH = os.path.join(BASE, "storage", "paper_trading_backup_pre_k693.json")
RESULTS_PATH = os.path.join(BASE, "experiments", "k693_results.json")


def compute_sharpe(returns, annual_factor=252):
    """Compute annualized Sharpe ratio from daily returns."""
    returns = [r for r in returns if r is not None]
    if len(returns) < 10:
        return None
    arr = np.array(returns)
    mu = np.mean(arr)
    sigma = np.std(arr, ddof=1)
    if sigma < 1e-10:
        return None
    return float(mu / sigma * np.sqrt(annual_factor))


def compute_cumulative_return(returns):
    """Compute cumulative return from daily returns."""
    returns = [r for r in returns if r is not None]
    if not returns:
        return 0.0
    cum = 1.0
    for r in returns:
        cum *= (1 + r)
    return float(cum - 1)


def compute_max_drawdown(returns):
    """Compute max drawdown from daily returns."""
    returns = [r for r in returns if r is not None]
    if not returns:
        return 0.0
    cum = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        cum *= (1 + r)
        if cum > peak:
            peak = cum
        dd = (peak - cum) / peak
        if dd > mdd:
            mdd = dd
    return float(mdd)


def main():
    print("=" * 70)
    print("K693: Fix Historical Paper Trading Returns (Lookahead Bias Correction)")
    print("=" * 70)

    # ── Step 0: Backup ──
    print("\n[Step 0] Backing up paper_trading.json...")
    if os.path.exists(BACKUP_PATH):
        print(f"  Backup already exists at {BACKUP_PATH}")
        print(f"  (Size: {os.path.getsize(BACKUP_PATH):,} bytes)")
    else:
        shutil.copy2(PT_PATH, BACKUP_PATH)
        print(f"  Backed up to {BACKUP_PATH}")
        print(f"  (Size: {os.path.getsize(BACKUP_PATH):,} bytes)")

    # ── Step 1: Load data ──
    print("\n[Step 1] Loading paper_trading.json...")
    with open(PT_PATH) as f:
        pt = json.load(f)

    # Identify strategies with old-format entries
    strategies_to_fix = {}
    for key in pt:
        if not isinstance(pt[key], dict) or "entries" not in pt[key]:
            continue
        entries = pt[key]["entries"]
        old_indices = [
            i for i, e in enumerate(entries)
            if e.get("trade_date") == e.get("data_date")
            and e.get("portfolio_return") is not None
        ]
        if old_indices:
            all_assets = set()
            for i in old_indices:
                all_assets.update(entries[i].get("weights", {}).keys())
            strategies_to_fix[key] = {
                "old_indices": old_indices,
                "assets": sorted(all_assets),
            }

    print(f"  Strategies to fix: {len(strategies_to_fix)}")
    for k, v in strategies_to_fix.items():
        print(f"    {k}: {len(v['old_indices'])} entries, assets={v['assets']}")

    # ── Step 2: Download price data ──
    print("\n[Step 2] Downloading historical price data from yfinance...")
    import yfinance as yf

    all_assets_needed = set()
    for v in strategies_to_fix.values():
        all_assets_needed.update(v["assets"])
    all_assets_needed = sorted(all_assets_needed)
    print(f"  Assets needed: {all_assets_needed}")

    # Download all at once with buffer dates
    price_data = {}  # {asset: {date_str: close_price}}
    for asset in all_assets_needed:
        print(f"  Downloading {asset}...")
        ticker = yf.Ticker(asset)
        # Need data from 2021-12-01 to 2026-03-28 to cover all entries
        hist = ticker.history(start="2021-12-01", end="2026-03-29", auto_adjust=False)
        if len(hist) == 0:
            print(f"    WARNING: No data for {asset}!")
            continue

        # Build date -> close price map
        closes = {}
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            closes[date_str] = float(row["Close"])
        price_data[asset] = closes
        print(f"    Got {len(closes)} trading days ({min(closes.keys())} to {max(closes.keys())})")

    # ── Step 3: Compute before-fix metrics ──
    print("\n[Step 3] Computing BEFORE-fix metrics...")
    before_metrics = {}
    for strat_key, fix_info in strategies_to_fix.items():
        entries = pt[strat_key]["entries"]
        old_returns = [
            entries[i]["portfolio_return"]
            for i in fix_info["old_indices"]
            if entries[i]["portfolio_return"] is not None
        ]
        before_metrics[strat_key] = {
            "sharpe": compute_sharpe(old_returns),
            "cumulative_return": compute_cumulative_return(old_returns),
            "max_drawdown": compute_max_drawdown(old_returns),
            "n_entries": len(old_returns),
            "mean_daily_return": float(np.mean(old_returns)) if old_returns else None,
            "std_daily_return": float(np.std(old_returns, ddof=1)) if len(old_returns) > 1 else None,
        }
        print(f"  {strat_key}: Sharpe={before_metrics[strat_key]['sharpe']:.4f}, "
              f"CumRet={before_metrics[strat_key]['cumulative_return']:.4%}")

    # ── Step 4: Apply the fix ──
    print("\n[Step 4] Applying the lookahead fix...")
    fix_stats = {}

    for strat_key, fix_info in strategies_to_fix.items():
        entries = pt[strat_key]["entries"]
        old_indices = fix_info["old_indices"]
        assets = fix_info["assets"]

        fixed_count = 0
        skipped_no_price = 0
        nulled_last = 0

        for idx_pos, i in enumerate(old_indices):
            entry = entries[i]
            weights = entry.get("weights", {})
            data_date_i = entry["data_date"]

            # Find the next entry's data_date
            # For old-format entries, the next entry is at i+1
            if i + 1 < len(entries):
                next_entry = entries[i + 1]
                data_date_next = next_entry["data_date"]
            else:
                # Last entry in the list — cannot fix, set to None
                entry["portfolio_return"] = None
                nulled_last += 1
                continue

            # Check if next entry is also old-format or new-format
            # For new-format, data_date and trade_date differ
            # We need close prices for data_date_i and data_date_next

            # Compute the correct return: weight_i × (close_{next} / close_i - 1)
            new_portfolio_return = 0.0
            can_fix = True
            actual_returns = {}

            for asset in weights:
                w = weights[asset]
                if w == 0:
                    continue

                if asset not in price_data:
                    can_fix = False
                    break

                close_i = price_data[asset].get(data_date_i)
                close_next = price_data[asset].get(data_date_next)

                if close_i is None or close_next is None:
                    can_fix = False
                    break

                asset_ret = (close_next / close_i) - 1.0
                actual_returns[asset] = round(asset_ret, 6)
                new_portfolio_return += w * asset_ret

            if can_fix:
                entry["portfolio_return"] = round(new_portfolio_return, 6)
                entry["actual_returns"] = actual_returns
                # Update trade_date to reflect the correct execution date
                entry["trade_date"] = data_date_next
                fixed_count += 1
            else:
                skipped_no_price += 1

        fix_stats[strat_key] = {
            "total_old": len(old_indices),
            "fixed": fixed_count,
            "skipped_no_price": skipped_no_price,
            "nulled_last": nulled_last,
        }
        print(f"  {strat_key}: fixed={fixed_count}, skipped={skipped_no_price}, nulled_last={nulled_last}")

    # ── Step 5: Compute after-fix metrics ──
    print("\n[Step 5] Computing AFTER-fix metrics...")
    after_metrics = {}
    for strat_key, fix_info in strategies_to_fix.items():
        entries = pt[strat_key]["entries"]
        old_returns = [
            entries[i]["portfolio_return"]
            for i in fix_info["old_indices"]
            if entries[i]["portfolio_return"] is not None
        ]
        after_metrics[strat_key] = {
            "sharpe": compute_sharpe(old_returns),
            "cumulative_return": compute_cumulative_return(old_returns),
            "max_drawdown": compute_max_drawdown(old_returns),
            "n_entries": len(old_returns),
            "mean_daily_return": float(np.mean(old_returns)) if old_returns else None,
            "std_daily_return": float(np.std(old_returns, ddof=1)) if len(old_returns) > 1 else None,
        }
        print(f"  {strat_key}: Sharpe={after_metrics[strat_key]['sharpe']:.4f}, "
              f"CumRet={after_metrics[strat_key]['cumulative_return']:.4%}")

    # ── Step 6: Comparison ──
    print("\n" + "=" * 70)
    print("BEFORE vs AFTER Comparison")
    print("=" * 70)
    print(f"{'Strategy':<25} {'Before Sharpe':>14} {'After Sharpe':>13} {'Delta':>10} {'Before CumRet':>14} {'After CumRet':>13}")
    print("-" * 90)

    comparison = {}
    for strat_key in strategies_to_fix:
        b = before_metrics[strat_key]
        a = after_metrics[strat_key]
        b_sharpe = b["sharpe"] if b["sharpe"] is not None else 0
        a_sharpe = a["sharpe"] if a["sharpe"] is not None else 0
        delta = a_sharpe - b_sharpe

        print(f"{strat_key:<25} {b_sharpe:>14.4f} {a_sharpe:>13.4f} {delta:>+10.4f} "
              f"{b['cumulative_return']:>13.4%} {a['cumulative_return']:>13.4%}")

        comparison[strat_key] = {
            "before": {
                "sharpe": b["sharpe"],
                "cumulative_return": b["cumulative_return"],
                "max_drawdown": b["max_drawdown"],
                "mean_daily_return": b["mean_daily_return"],
                "std_daily_return": b["std_daily_return"],
                "n_entries": b["n_entries"],
            },
            "after": {
                "sharpe": a["sharpe"],
                "cumulative_return": a["cumulative_return"],
                "max_drawdown": a["max_drawdown"],
                "mean_daily_return": a["mean_daily_return"],
                "std_daily_return": a["std_daily_return"],
                "n_entries": a["n_entries"],
            },
            "delta_sharpe": round(delta, 6),
            "fix_stats": fix_stats[strat_key],
        }

    # ── Step 7: Save corrected paper_trading.json ──
    print(f"\n[Step 7] Saving corrected paper_trading.json...")
    with open(PT_PATH, "w") as f:
        json.dump(pt, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {PT_PATH}")
    print(f"  New size: {os.path.getsize(PT_PATH):,} bytes")
    print(f"  Backup at: {BACKUP_PATH} ({os.path.getsize(BACKUP_PATH):,} bytes)")

    # ── Step 8: Save results ──
    print(f"\n[Step 8] Saving results to k693_results.json...")
    total_fixed = sum(v["fixed"] for v in fix_stats.values())
    total_old = sum(v["total_old"] for v in fix_stats.values())

    # Compute average Sharpe inflation
    sharpe_deltas = [c["delta_sharpe"] for c in comparison.values() if c["delta_sharpe"] is not None]
    avg_sharpe_delta = np.mean(sharpe_deltas) if sharpe_deltas else 0

    results = {
        "experiment_id": "K693",
        "title": "Fix Historical Paper Trading Returns (Lookahead Bias Correction)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (historical close prices for SPY, GLD, 0050.TW, ^N225)",
        "period": "2022-01-01 to 2026-03-27",
        "methodology": (
            "Shifted returns by 1 day: weight_T now earns return_{T→T+1} instead of "
            "return_{T-1→T}. For each old-format entry (trade_date == data_date), "
            "recomputed portfolio_return using next day's actual close prices from yfinance. "
            "Also set trade_date = data_date_{i+1} and added actual_returns field."
        ),
        "summary": {
            "total_strategies_fixed": len(strategies_to_fix),
            "total_entries_fixed": total_fixed,
            "total_old_entries": total_old,
            "entries_nulled_last": sum(v["nulled_last"] for v in fix_stats.values()),
            "entries_skipped_no_price": sum(v["skipped_no_price"] for v in fix_stats.values()),
            "avg_sharpe_delta": round(float(avg_sharpe_delta), 6),
            "backup_path": BACKUP_PATH,
        },
        "per_strategy_comparison": comparison,
        "conclusion": (
            "The lookahead fix shifts each entry's return forward by one trading day. "
            "A negative Sharpe delta indicates the old returns were inflated by lookahead bias "
            "(the model could 'see' the same-day return when setting the weight). "
            "A positive delta suggests the corrected returns happen to be higher for that period, "
            "which is possible since we're just shifting the time alignment. "
            "The key point is correctness, not direction of change."
        ),
        "references": [
            "K692: Identified 801 entries with same-day lookahead bias",
            "daily_update.py: Fixed going forward on 2026-03-17 (trade_date ≠ data_date)",
        ],
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {RESULTS_PATH}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total strategies fixed: {len(strategies_to_fix)}")
    print(f"  Total entries fixed: {total_fixed} / {total_old}")
    print(f"  Average Sharpe delta: {avg_sharpe_delta:+.4f}")
    print(f"  Backup saved at: {BACKUP_PATH}")
    print(f"  Results saved at: {RESULTS_PATH}")
    print("\nDone!")


if __name__ == "__main__":
    main()
