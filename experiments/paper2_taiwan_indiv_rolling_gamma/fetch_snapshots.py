"""
fetch_snapshots.py -- refresh the offline price snapshots for the Taiwan-VT
Table 2 rolling-gamma block.

WHY THIS EXISTS
---------------
The 2026-07-07 run truncated all 10 securities to a common terminal date of
2025-01-22 and declared the Codex calendar-alignment caveat "RESOLVED". That
common end was NOT a market fact -- it was an artifact of two stale offline
snapshots (experiments/k1302/data/{2383,2886}_tw.csv both stop on 2025-01-22).
Eight of the ten securities had data running into 2026 and were discarded to
match two expired files. The paper claims a sample through 2026 while the table
rows ended in 2025-01.

Fix: re-fetch every series ONCE from yfinance into this experiment's own data/
directory, so the estimation script stays fully offline and reproducible while
the common end date reflects the actual market calendar.

CONVENTION (uniform across all 12 series)
-----------------------------------------
auto_adjust=False + the `Adj Close` column. This matches the paper's canonical
replication convention (body_v3.tex L33) and the k1302 / paper-CSV snapshots.
Empirically verified 2026-07-13: the k1302b snapshots (whose column is named
`Close`) were downloaded with auto_adjust=True, so their `Close` IS the
dividend-adjusted series -- their log returns match fresh Adj-Close log returns
to ~1e-6. There is therefore NO mixed adjusted/raw convention anywhere in the
data package, contrary to the old results JSON `data_source_note`.

We do NOT overwrite experiments/k1302/data or experiments/k1302b/data: those are
other experiments' canonical snapshots.
"""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.ops.diagnostics import warn

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

FETCH_START = "2007-01-01"  # buffer before the 2008-01-01 sample start

# yfinance ticker -> local snapshot basename
SERIES = {
    "2317.TW": "2317_tw",   # Hon Hai
    "2454.TW": "2454_tw",   # MediaTek
    "2383.TW": "2383_tw",   # Elite Material
    "2886.TW": "2886_tw",   # Mega Financial
    "2412.TW": "2412_tw",   # Chunghwa Telecom
    "2881.TW": "2881_tw",   # Fubon
    "2882.TW": "2882_tw",   # Cathay Financial
    "2885.TW": "2885_tw",   # Yuanta
    "2891.TW": "2891_tw",   # CTBC
    "0056.TW": "0056_tw",   # Yuanta High Dividend ETF
    "0050.TW": "0050_tw",   # Yuanta Taiwan 50 ETF (index row)
    "^TWII": "twii",        # TAIEX (index row)
}

# Existing canonical snapshots, used as a REGRESSION CHECK on the fresh pull:
# fresh Adj-Close log returns must reproduce the old snapshots' log returns over
# the overlapping sample (adjusted-price returns are vintage-invariant).
PAPER_CSV = os.path.join(
    REPO,
    "paper/taiwan-vt/data/"
    "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv",
)
LEGACY_REF = {
    # ticker: (kind, path_or_col)
    "2317.TW": ("paper_csv", "2317_tw_adj_close"),
    "2454.TW": ("paper_csv", "2454_tw_adj_close"),
    "0056.TW": ("paper_csv", "0056_tw_adj_close"),
    "0050.TW": ("paper_csv", "0050_tw_adj_close"),
    "^TWII": ("paper_csv", "twii_adj_close"),
    "2383.TW": ("k1302", "adj_close"),
    "2886.TW": ("k1302", "adj_close"),
    "2412.TW": ("k1302b", "Close"),
    "2881.TW": ("k1302b", "Close"),
    "2882.TW": ("k1302b", "Close"),
    "2885.TW": ("k1302b", "Close"),
    "2891.TW": ("k1302b", "Close"),
}


_LEGACY_DUPES: dict[str, int] = {}
_LEGACY_MISSING: dict[str, str] = {}


def _legacy_returns(ticker: str) -> pd.Series | None:
    kind, col = LEGACY_REF[ticker]
    try:
        if kind == "paper_csv":
            s = pd.read_csv(PAPER_CSV, parse_dates=["date"]).set_index("date")[col]
        elif kind == "k1302":
            p = os.path.join(REPO, "experiments/k1302/data", f"{ticker[:4]}_tw.csv")
            s = pd.read_csv(p, parse_dates=["date"]).set_index("date")[col]
        elif kind == "k1302b":
            p = os.path.join(REPO, "experiments/k1302b/data", f"{ticker[:4]}_tw.csv")
            s = pd.read_csv(p, parse_dates=["Date"]).set_index("Date")[col]
        else:
            return None
    except (FileNotFoundError, KeyError) as exc:
        # Loud, not silent: a missing legacy reference means the regression check
        # for this ticker DID NOT RUN. Swallowing that would let a refreshed series
        # reach the paper with nothing having verified it against the old snapshot.
        warn(
            "rolling-gamma-fetch",
            f"legacy reference unavailable for {ticker} -- regression check SKIPPED "
            f"for this series ({type(exc).__name__}: {exc})",
        )
        _LEGACY_MISSING[ticker] = f"{type(exc).__name__}: {exc}"
        return None
    s = s.dropna().astype(float)
    # The paper CSV contains 10 exactly-duplicated date rows (2026-05-04..05-15;
    # an append that ran twice). De-duplicate before differencing, otherwise the
    # repeated block injects spurious jump returns. Recorded in the manifest as a
    # finding against the paper's canonical CSV -- we do NOT edit that file here.
    dupes = int(s.index.duplicated().sum())
    if dupes:
        s = s[~s.index.duplicated(keep="first")].sort_index()
    _LEGACY_DUPES[ticker] = dupes
    return np.log(s / s.shift(1)).dropna()


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    fetch_date = datetime.now(timezone.utc)
    manifest: dict = {
        "fetched_at_utc": fetch_date.isoformat(),
        "source": "yfinance",
        "yfinance_version": yf.__version__,
        "convention": "auto_adjust=False; price column = 'Adj Close' (dividend+split adjusted)",
        "fetch_start": FETCH_START,
        "series": {},
    }

    for ticker, base in SERIES.items():
        px = yf.Ticker(ticker).history(start=FETCH_START, auto_adjust=False)
        if px.empty:
            raise RuntimeError(f"empty fetch for {ticker}")
        px.index = px.index.tz_localize(None)
        s = px["Adj Close"].dropna().astype(float)
        s.index.name = "date"
        if s.index.duplicated().any():
            raise RuntimeError(f"fresh fetch for {ticker} has duplicate dates")
        out = os.path.join(DATA, f"{base}.csv")
        s.rename("adj_close").to_frame().to_csv(out, float_format="%.10g")

        r_new = np.log(s / s.shift(1)).dropna()
        entry = {
            "ticker": ticker,
            "file": f"data/{base}.csv",
            "n_obs": int(len(s)),
            "first": str(s.index[0].date()),
            "last": str(s.index[-1].date()),
        }

        # Regression check vs the previous canonical snapshot.
        r_old = _legacy_returns(ticker)
        if r_old is not None:
            j = pd.DataFrame({"old": r_old, "new": r_new}).dropna()
            if len(j):
                md = float((j["old"] - j["new"]).abs().max())
                entry["regression_vs_old_snapshot"] = {
                    "reference": f"{LEGACY_REF[ticker][0]}:{LEGACY_REF[ticker][1]}",
                    "overlap_obs": int(len(j)),
                    "max_abs_logret_diff": md,
                    "reproduces_old": bool(md < 1e-4),
                    "duplicate_date_rows_in_old_source": _LEGACY_DUPES.get(ticker, 0),
                }

        # Data-quality: Taiwan cash equities have a +/-10% daily price limit, so a
        # |log return| beyond ~0.11 in a stock/ETF series is a corporate-action or
        # adjustment artifact, not a market move. (^TWII is an index -- not limited
        # per se, but a >11% index move would still be extraordinary.)
        extreme = r_new[r_new.abs() > 0.11]
        entry["extreme_returns_gt_11pct"] = {
            str(d.date()): round(float(v), 4) for d, v in extreme.items()
        }
        manifest["series"][ticker] = entry

        reg = entry.get("regression_vs_old_snapshot", {})
        flag = (
            f"reproduces_old={reg.get('reproduces_old')} (max|dr|={reg.get('max_abs_logret_diff', float('nan')):.2e})"
            if reg else "no legacy reference"
        )
        print(
            f"{ticker:8s} n={entry['n_obs']:5d}  {entry['first']} -> {entry['last']}  "
            f"| {flag} | extreme={len(extreme)}"
        )

    checked = [t for t, e in manifest["series"].items() if "regression_vs_old_snapshot" in e]
    manifest["regression_check_coverage"] = {
        "series_checked": len(checked),
        "series_total": len(SERIES),
        "all_reproduce_old": all(
            manifest["series"][t]["regression_vs_old_snapshot"]["reproduces_old"] for t in checked
        ),
        "series_with_no_legacy_reference": _LEGACY_MISSING,
    }
    if _LEGACY_MISSING:
        warn(
            "rolling-gamma-fetch",
            f"{len(_LEGACY_MISSING)} series were NOT regression-checked against a legacy "
            f"snapshot: {sorted(_LEGACY_MISSING)}",
        )

    manifest["paper_csv_duplicate_date_rows"] = {
        "finding": (
            "The paper's canonical CSV (paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv) "
            "contains 10 exactly-duplicated date rows (2026-05-04..2026-05-15) -- an append "
            "that ran twice. Any experiment that reads its twii/spy/vix columns and differences "
            "them WITHOUT de-duplicating will inject spurious jump returns at that block. "
            "This experiment is unaffected (it estimates from the fresh yfinance snapshots in "
            "data/, which are duplicate-free), but the CSV itself should be repaired by the "
            "main thread; it is not edited here."
        ),
        "duplicate_rows_seen_per_series": {
            t: n for t, n in _LEGACY_DUPES.items() if n
        },
    }

    lasts = {t: pd.Timestamp(e["last"]) for t, e in manifest["series"].items()}
    common_end = min(lasts.values())
    manifest["common_end_all_series"] = str(common_end.date())
    manifest["binding_series_for_common_end"] = [
        t for t, d in lasts.items() if d == common_end
    ]

    with open(os.path.join(DATA, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\ncommon_end (min last-obs across all {len(SERIES)} series) = {common_end.date()}")
    print(f"bound by: {manifest['binding_series_for_common_end']}")
    print(f"written: {DATA}/MANIFEST.json")


if __name__ == "__main__":
    main()
