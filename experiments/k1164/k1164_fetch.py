"""K1164 — Fetch analyst coverage + market-cap proxies for each stock.

Per-stock fetch:
  - analyst_count (yfinance Ticker.info['numberOfAnalystOpinions'] or get_recommendations_summary)
  - market_cap (yfinance Ticker.info['marketCap'])
  - avg_daily_turnover (computed from cached parquet: mean(Close * Volume))

Fallback: if yfinance API fails, leave NaN and fall back to market_cap proxy only.

Output: experiments/k1164/data/analyst_media_proxies.json

Run:
  uv run python experiments/k1164/k1164_fetch.py

Random seed: 42 (no stochastic ops, but declared for reproducibility convention).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

np.random.seed(42)

MAIN_REPO = Path("/Users/yhlai0911/Desktop/volpred-research")
WORKTREE_ROOT = Path(__file__).resolve().parents[2]
THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# Reuse the exact ticker lists from K1145/K1147/K1150/K1153 result JSONs
MARKETS: dict[str, dict] = {
    "TW": {
        "k_experiment": "k1145",
        "source_json": MAIN_REPO / "experiments" / "k1145" / "k1145_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1145" / "data",
    },
    "US": {
        "k_experiment": "k1147",
        "source_json": MAIN_REPO / "experiments" / "k1147" / "k1147_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1147" / "data",
    },
    "JP": {
        "k_experiment": "k1150",
        "source_json": MAIN_REPO / "experiments" / "k1150" / "k1150_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1150" / "data",
    },
    "EU": {
        "k_experiment": "k1153",
        "source_json": MAIN_REPO / "experiments" / "k1153" / "k1153_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1153" / "data",
    },
}


def load_tickers(market: str) -> list[str]:
    """Read tickers used in the corresponding K experiment main fit."""
    with open(MARKETS[market]["source_json"], "r") as f:
        r = json.load(f)
    return list(r["main_fit_eav_window_1"].get("per_stock_tickers", r.get("tickers", [])))


def fetch_one(ticker: str) -> dict:
    """Fetch analyst + market cap info via yfinance with fallbacks."""
    out: dict = {
        "ticker": ticker,
        "analyst_count": None,
        "market_cap": None,
        "currency": None,
        "fetch_error": None,
    }
    try:
        t = yf.Ticker(ticker)
        info = None
        try:
            info = t.info  # primary source
        except Exception as e_info:
            out["fetch_error"] = f"info_err: {type(e_info).__name__}: {e_info}"
        if info:
            for key in ("numberOfAnalystOpinions", "recommendationMean"):
                val = info.get(key)
                if val is not None and key == "numberOfAnalystOpinions":
                    try:
                        out["analyst_count"] = float(val)
                    except Exception:
                        pass
            mc = info.get("marketCap")
            if mc is not None:
                try:
                    out["market_cap"] = float(mc)
                except Exception:
                    pass
            out["currency"] = info.get("currency")
        # Secondary fallback: recommendations summary table counts
        if out["analyst_count"] is None:
            try:
                rec = t.get_recommendations_summary() if hasattr(t, "get_recommendations_summary") else None
                if rec is not None and not rec.empty:
                    # Use the most recent row's sum of buy/hold/sell counts
                    latest = rec.iloc[0]
                    total = sum(
                        latest.get(c, 0) or 0
                        for c in ("strongBuy", "buy", "hold", "sell", "strongSell")
                    )
                    if total > 0:
                        out["analyst_count"] = float(total)
            except Exception as e_rec:
                out["fetch_error"] = (out["fetch_error"] or "") + f" | rec_err: {e_rec}"
    except Exception as e_top:
        out["fetch_error"] = f"top_err: {type(e_top).__name__}: {e_top}"
    return out


def compute_avg_turnover(data_dir: Path, ticker: str) -> float | None:
    """Average daily dollar turnover = mean(Close * Volume) over available history."""
    # yfinance stores parquet with dots replaced? check both patterns
    candidates = [
        data_dir / f"{ticker}.parquet",
        data_dir / f"{ticker.replace('.', '_')}.parquet",
        data_dir / f"{ticker.replace('-', '_')}.parquet",
    ]
    for p in candidates:
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if "Close" in df.columns and "Volume" in df.columns:
                    dollar_vol = (df["Close"] * df["Volume"]).dropna()
                    if len(dollar_vol) > 0:
                        return float(dollar_vol.median())
            except Exception:
                continue
    return None


def main() -> None:
    all_rows: dict[str, list[dict]] = {}
    for market in ("TW", "US", "JP", "EU"):
        tickers = load_tickers(market)
        data_dir = MARKETS[market]["data_dir"]
        print(f"[{market}] fetching {len(tickers)} tickers…")
        rows = []
        for i, tk in enumerate(tickers):
            row = fetch_one(tk)
            row["market"] = market
            row["median_daily_turnover"] = compute_avg_turnover(data_dir, tk)
            rows.append(row)
            print(
                f"  [{market} {i+1}/{len(tickers)}] {tk:>10}  "
                f"analyst={row['analyst_count']}, "
                f"mcap={row['market_cap']}, "
                f"turnover={row['median_daily_turnover']}, "
                f"err={row['fetch_error']}"
            )
            time.sleep(0.25)  # gentle throttle
        all_rows[market] = rows

    out_path = DATA_DIR / "analyst_media_proxies.json"
    with open(out_path, "w") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print(f"[done] wrote {out_path}")


if __name__ == "__main__":
    main()
