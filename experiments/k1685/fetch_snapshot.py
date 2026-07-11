#!/usr/bin/env python3
"""
K1685 step 0: fetch and PIN a fresh SPY + VIX snapshot.

Writes experiments/k1685/data/k1685_spy_vix_snapshot.csv (immutable once written)
plus a provenance sidecar with SHA256, fetch time, and data endpoints.

Cross-checks the fresh pull against the paper's existing snapshot
(paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv) over the overlapping
dates: SPY adjusted-close log returns must agree (back-adjustment is a constant
multiplicative rescale, so log returns are invariant), and VIX closes must match.

Run with --refetch to overwrite an existing snapshot (default: refuse, so that
re-running the experiment always reuses the pinned file).

Author: VolPred Research System | Date: 2026-07-12
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "k1685_spy_vix_snapshot.csv")
PROVENANCE_PATH = os.path.join(DATA_DIR, "k1685_snapshot_provenance.json")
PAPER_CSV = os.path.join(PROJECT_ROOT, "paper", "garch-x-vix", "data",
                         "spy_vix_qqq_eem_fez_2000-2026.csv")

FETCH_START = "2000-01-01"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch() -> pd.DataFrame:
    """One ticker at a time — avoids yfinance MultiIndex column ambiguity."""
    spy = yf.download("SPY", start=FETCH_START, progress=False,
                      auto_adjust=False, threads=False)
    vix = yf.download("^VIX", start=FETCH_START, progress=False,
                      auto_adjust=False, threads=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    out = pd.DataFrame({
        "spy_adj_close": spy["Adj Close"],
        "spy_close": spy["Close"],
        "vix_close": vix["Close"],
    }).dropna()
    out.index.name = "date"
    return out.sort_index()


def crosscheck(snap: pd.DataFrame) -> dict:
    """Compare fresh snapshot against the paper's pinned CSV over common dates."""
    if not os.path.exists(PAPER_CSV):
        return {"status": "paper_csv_missing", "path": PAPER_CSV}

    paper = pd.read_csv(PAPER_CSV, parse_dates=["date"], index_col="date").sort_index()
    common = snap.index.intersection(paper.index)
    if len(common) < 100:
        return {"status": "insufficient_overlap", "n_common": int(len(common))}

    # Log returns are computed within each source (over its own full history),
    # then aligned — this is what the experiment actually consumes.
    snap_ret = np.log(snap["spy_adj_close"] / snap["spy_adj_close"].shift(1)).loc[common]
    paper_ret = np.log(paper["spy_adj_close"] / paper["spy_adj_close"].shift(1)).loc[common]
    ret_diff = (snap_ret - paper_ret).dropna()
    vix_diff = (snap.loc[common, "vix_close"] - paper.loc[common, "vix_close"]).dropna()

    return {
        "status": "ok",
        "paper_csv": os.path.relpath(PAPER_CSV, PROJECT_ROOT),
        "paper_csv_sha256": sha256_of(PAPER_CSV),
        "paper_last_date": str(paper.index[-1].date()),
        "n_common_dates": int(len(common)),
        "spy_logret_max_abs_diff": float(np.abs(ret_diff).max()),
        "spy_logret_mean_abs_diff": float(np.abs(ret_diff).mean()),
        "vix_max_abs_diff": float(np.abs(vix_diff).max()),
        "n_dates_only_in_snapshot": int(len(snap.index.difference(paper.index))),
        "n_dates_only_in_paper": int(len(paper.index.difference(snap.index))),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true",
                    help="overwrite an existing pinned snapshot")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SNAPSHOT_PATH) and not args.refetch:
        print(f"Snapshot already pinned: {SNAPSHOT_PATH}")
        print(f"  sha256 = {sha256_of(SNAPSHOT_PATH)}")
        print("  (use --refetch to overwrite)")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()
    print(f"Fetching SPY + ^VIX from yfinance (start={FETCH_START}) ...")
    snap = fetch()
    print(f"  rows={len(snap)}  {snap.index[0].date()} .. {snap.index[-1].date()}")

    check = crosscheck(snap)
    print(f"  cross-check vs paper CSV: {json.dumps(check, indent=2)}")

    snap.to_csv(SNAPSHOT_PATH, float_format="%.10f")
    digest = sha256_of(SNAPSHOT_PATH)

    provenance = {
        "experiment_id": "K1685",
        "snapshot_file": os.path.relpath(SNAPSHOT_PATH, PROJECT_ROOT),
        "snapshot_sha256": digest,
        "source": "yfinance",
        "yfinance_version": yf.__version__,
        "tickers": {"spy": "SPY (Adj Close)", "vix": "^VIX (Close)"},
        "fetch_start": FETCH_START,
        "fetched_at_utc": fetched_at,
        "n_rows": int(len(snap)),
        "first_date": str(snap.index[0].date()),
        "last_date": str(snap.index[-1].date()),
        "crosscheck_vs_paper_snapshot": check,
    }
    with open(PROVENANCE_PATH, "w") as fh:
        json.dump(provenance, fh, indent=2)

    print(f"\nPinned  : {SNAPSHOT_PATH}")
    print(f"sha256  : {digest}")
    print(f"endpoint: {snap.index[-1].date()}")


if __name__ == "__main__":
    main()
