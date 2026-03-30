"""Evaluate a new strategy candidate against existing paper_trading strategies.

Usage:
  uv run python scripts/evaluate_new_strategy.py --help
  uv run python scripts/evaluate_new_strategy.py --example    # run built-in example

Design principles:
  1. New strategy is simulated on the SAME period as paper_trading (COMMON_START ~ today)
  2. Same lag convention: signal from t-1, return at t (next-day return)
  3. Same TX cost assumption
  4. Compare against ALL existing strategies on identical period
  5. No historical data is modified — forward tracking corrects naturally

This tool answers: "If this strategy had been tracked since COMMON_START,
how would it compare to what we're already tracking?"
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
COMMON_START = "2023-01-04"
TX_COST_BPS = 5  # 5 basis points per rebalance (US ETFs)


def load_existing_metrics() -> dict:
    """Load existing strategy metrics from paper_trading.json."""
    pt_path = PROJECT / "storage" / "paper_trading.json"
    pt = json.loads(pt_path.read_text())

    results = {}
    for sid, strat in pt.items():
        if sid.startswith("_"):
            continue
        entries = strat.get("entries", [])
        returns = []
        for e in entries:
            td = e.get("data_date") or e.get("trade_date", "")
            ret = e.get("portfolio_return")
            if td >= COMMON_START and ret is not None:
                returns.append(ret)
        if len(returns) < 10:
            continue
        results[sid] = _calc_metrics(returns)
    return results


def _calc_metrics(returns: list) -> dict:
    """Calculate Sharpe, MDD, CAGR, Calmar from daily returns."""
    r = np.array(returns)
    n = len(r)
    if n < 10:
        return {}

    mean_r = np.mean(r)
    std_r = np.std(r, ddof=1)
    sharpe = mean_r / std_r * np.sqrt(252) if std_r > 0 else 0

    cum = np.cumsum(r)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    mdd = float(np.min(dd)) * 100

    cagr = ((1 + np.sum(r)) ** (252 / n) - 1) * 100
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Win rate (monthly)
    monthly_r = []
    for i in range(0, n, 21):
        chunk = r[i:i+21]
        if len(chunk) > 10:
            monthly_r.append(np.sum(chunk))
    win_rate = sum(1 for x in monthly_r if x > 0) / len(monthly_r) * 100 if monthly_r else 0

    return {
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 1),
        "cagr": round(cagr, 1),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "n_days": n,
    }


def simulate_strategy(
    weights_func,
    asset_tickers: list[str] = ("SPY", "GLD"),
    start: str = COMMON_START,
    tx_cost_bps: int = TX_COST_BPS,
) -> dict:
    """Simulate a strategy and return metrics on the SAME period as paper_trading.

    Args:
        weights_func: callable(row) -> dict of {asset: weight}.
            `row` is a pandas Series with columns: Date, VIX, SPY_close, GLD_close, etc.
            The function receives data from day t-1 and weights are applied to day t's return.
        asset_tickers: list of yfinance tickers to download
        start: start date (should be COMMON_START for fair comparison)
        tx_cost_bps: transaction cost in basis points per weight change
    """
    import yfinance as yf

    # Download data
    tickers = list(asset_tickers) + ["^VIX"]
    data = {}
    for t in tickers:
        d = yf.download(t, start="2022-01-01", end="2026-12-31", progress=False)
        data[t] = d["Close"].squeeze()

    df = pd.DataFrame(data).dropna()
    df.columns = [c.replace("^", "") for c in df.columns]

    # Compute returns
    for col in df.columns:
        if col != "VIX":
            df[f"r_{col}"] = df[col].pct_change()

    df = df.dropna()

    # Apply strategy with PROPER LAG: signal from t-1, return at t
    weights_list = []
    for i in range(len(df)):
        row = df.iloc[i]
        w = weights_func(row)
        weights_list.append(w)

    df["weights"] = weights_list

    # Shift weights by 1 day (lag)
    df["weights_lag"] = df["weights"].shift(1)
    df = df.iloc[1:]  # drop first row (no lagged weight)

    # Compute portfolio return
    port_returns = []
    prev_w = {}
    for _, row in df.iterrows():
        w = row["weights_lag"]
        if not isinstance(w, dict):
            port_returns.append(0)
            continue

        # Portfolio return
        r = sum(w.get(a, 0) * row.get(f"r_{a}", 0) for a in asset_tickers)

        # TX cost
        tx = sum(abs(w.get(a, 0) - prev_w.get(a, 0)) for a in asset_tickers)
        r -= tx * tx_cost_bps / 10000

        port_returns.append(r)
        prev_w = w

    # Filter to COMMON_START period
    df["port_return"] = port_returns
    mask = df.index >= pd.Timestamp(start)
    filtered = df.loc[mask, "port_return"].tolist()

    return _calc_metrics(filtered)


def compare(new_metrics: dict, existing: dict, new_name: str = "NEW") -> None:
    """Print comparison table with composite ranking (K717 multi-dimensional)."""
    all_strats = {new_name: new_metrics, **existing}

    # Composite score: CAGR + Sharpe + Calmar + win_rate (normalized 0-1, equal weight)
    for key in ["cagr", "sharpe", "calmar", "win_rate"]:
        vals = [m.get(key, 0) for m in all_strats.values() if isinstance(m.get(key), (int, float))]
        if not vals:
            continue
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1
        for m in all_strats.values():
            v = m.get(key)
            if isinstance(v, (int, float)):
                m[f"_{key}_n"] = (v - mn) / rng

    for m in all_strats.values():
        norms = [m.get(f"_{k}_n", 0) for k in ["cagr", "sharpe", "calmar", "win_rate"]]
        m["composite"] = round(sum(norms) / len(norms), 3) if norms else 0

    sorted_strats = sorted(all_strats.items(), key=lambda x: x[1].get("composite", 0), reverse=True)

    print(f"\n{'Strategy':30s} {'Comp':>5} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Calmar':>7} {'Win%':>5}")
    print("-" * 75)
    for name, m in sorted_strats:
        marker = " ◀◀◀" if name == new_name else ""
        print(f"{name:30s} {m.get('composite',0):>5.3f} {m.get('sharpe',0):>7.3f} {m.get('cagr',0):>6.1f}% {m.get('mdd',0):>6.1f}% {m.get('calmar',0):>7.2f} {m.get('win_rate',0):>4.0f}%{marker}")

    rank = next(i for i, (n, _) in enumerate(sorted_strats, 1) if n == new_name)
    total = len(sorted_strats)
    median_rank = total // 2

    print(f"\n{new_name} ranks #{rank}/{total} by composite (CAGR+Sharpe+Calmar+WinRate)")

    if rank <= median_rank:
        print(f"✅ PASSES: Above median (#{median_rank}) — proceed to cross-OOS validation")
    else:
        print(f"❌ FAILS: Below median — not competitive with existing strategies")


def run_example():
    """Example: evaluate 37.5/37.5/25 SPY/GLD/TLT (K713)."""
    print("=== Example: 37.5/37.5/25 SPY/GLD/TLT static allocation ===\n")

    def weights_func(row):
        return {"SPY": 0.375, "GLD": 0.375, "TLT": 0.25}

    existing = load_existing_metrics()
    new_metrics = simulate_strategy(
        weights_func,
        asset_tickers=["SPY", "GLD", "TLT"],
        tx_cost_bps=5,
    )
    compare(new_metrics, existing, "37.5/37.5/25 SPY/GLD/TLT")

    return new_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate new strategy vs existing paper_trading strategies")
    parser.add_argument("--example", action="store_true", help="Run built-in K713 example")
    args = parser.parse_args()

    if args.example:
        run_example()
    else:
        parser.print_help()
        print("\nUse --example to run the built-in test, or import and call simulate_strategy() programmatically.")
