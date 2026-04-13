#!/usr/bin/env python3
"""K1167 institutional ownership fetch.

For each of the 110 stocks in K1166's per-stock panel, fetch:
- yfinance Ticker.major_holders -> institutionsPercentHeld (primary)
- yfinance Ticker.institutional_holders -> sum pctHeld (secondary, for cross-check)

Writes `experiments/k1167/data/institutional_ownership.json` with a per-ticker
snapshot. Snapshot timestamp is recorded for reproducibility.

Random seed: 42 (no stochastic ops, but set by convention).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

np.random.seed(42)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

# Source of tickers: K1166 per-stock panel CSV (canonical list of 110 stocks with market labels).
# Primary path uses the sibling k1166 experiment dir; worktree fallback uses a local copy under data/.
_PRIMARY = ROOT.parent / "k1166" / "k1166_per_stock_table.csv"
_FALLBACK = DATA / "k1166_per_stock_table.csv"
K1166_CSV = _PRIMARY if _PRIMARY.exists() else _FALLBACK


def extract_from_major_holders(df: pd.DataFrame | None) -> dict | None:
    """Extract institutions/insiders percentages from major_holders DataFrame.

    yfinance 0.2+ returns a DataFrame where the row index is named
    'Breakdown' (with entries like 'institutionsPercentHeld') and the sole
    data column is 'Value'. Older formats used a column 'Breakdown'.
    """
    if df is None or df.empty:
        return None
    out: dict = {}
    keyed: dict = {}
    # Case 1: 'Breakdown' is the row index name (newer yfinance layout)
    if getattr(df.index, "name", None) == "Breakdown" and "Value" in df.columns:
        for idx in df.index:
            keyed[str(idx)] = df.loc[idx, "Value"]
    # Case 2: 'Breakdown' is a column
    elif "Breakdown" in df.columns and "Value" in df.columns:
        keyed = dict(zip(df["Breakdown"].astype(str), df["Value"]))
    else:
        # fallback: use first two columns or index->col0
        try:
            if df.shape[1] >= 2:
                keyed = dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1]))
            elif df.shape[1] == 1:
                keyed = {str(idx): df.iloc[i, 0] for i, idx in enumerate(df.index)}
            else:
                return None
        except Exception:
            return None
    for k in ("insidersPercentHeld", "institutionsPercentHeld", "institutionsFloatPercentHeld", "institutionsCount"):
        v = keyed.get(k)
        if v is None:
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


def extract_institutional_sum(df: pd.DataFrame | None) -> dict | None:
    """Extract sum of top-N institutional holders (cross-check proxy)."""
    if df is None or df.empty:
        return None
    if "pctHeld" not in df.columns:
        return None
    try:
        pct_sum = float(df["pctHeld"].sum())
        n_rows = int(df.shape[0])
        return {"topN_sum_pctHeld": pct_sum, "topN_rows": n_rows}
    except Exception:
        return None


def fetch_one(ticker: str) -> dict:
    rec: dict = {"ticker": ticker, "major_holders": None, "institutional_holders": None, "error": None}
    try:
        t = yf.Ticker(ticker)
        try:
            mh = t.major_holders
            rec["major_holders"] = extract_from_major_holders(mh)
        except Exception as e:
            rec["major_holders_error"] = str(e)
        try:
            ih = t.institutional_holders
            rec["institutional_holders"] = extract_institutional_sum(ih)
        except Exception as e:
            rec["institutional_holders_error"] = str(e)
    except Exception as e:
        rec["error"] = str(e)
    return rec


def main() -> None:
    panel = pd.read_csv(K1166_CSV)
    tickers = list(panel["ticker"].astype(str))
    markets = dict(zip(panel["ticker"].astype(str), panel["market"].astype(str)))
    print(f"[K1167-fetch] tickers n={len(tickers)}")

    results = []
    for i, tkr in enumerate(tickers, 1):
        rec = fetch_one(tkr)
        rec["market"] = markets.get(tkr, None)
        results.append(rec)
        pct_ih = None
        if rec.get("major_holders"):
            pct_ih = rec["major_holders"].get("institutionsPercentHeld")
        print(f"  [{i:03d}/{len(tickers)}] {tkr} ({rec['market']}): instPctHeld={pct_ih}")
        # polite rate limiting (yfinance public API)
        time.sleep(0.35)

    out = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance Ticker.major_holders (primary) + Ticker.institutional_holders (secondary)",
        "n_tickers": len(tickers),
        "records": results,
    }
    (DATA / "institutional_ownership.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[K1167-fetch] wrote {DATA/'institutional_ownership.json'}")


if __name__ == "__main__":
    main()
