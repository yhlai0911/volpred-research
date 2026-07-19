#!/usr/bin/env python3
"""Repoint a pinned snapshot CSV's price columns to the repaired price_cache DB.

Background
----------
`scripts/detect_price_split_breaks.py --csv-scan` found that repairing the
0050.TW split artefact in `data/cache/price_cache.db` does NOT reach the pinned
snapshot CSVs under `paper/<id>/data/` and `experiments/<k>/data/` — those files
are frozen copies taken before the repair, so they still carry the ×4 level
break at 2014-01-02 (see task paper_0050_snapshot_repoint_20260719).

What this does (and deliberately does NOT do)
---------------------------------------------
The DB is used as the *reference* for the break factor, not as a wholesale
replacement for the snapshot. Overwriting every cell from today's DB would also
import ~10 years of vendor re-adjustment drift (adj_close moves every time a
dividend is paid), which is exactly what pinning exists to prevent. So the
repair is minimal and surgical: the pre-break segment of the ticker's price
columns is divided by the break factor implied by the DB (volume multiplied),
and every other cell — every other ticker, every post-break row — is left
untouched.

Safety
------
* Read-only against the DB.
* Refuses to run if the DB itself still shows a break at the cut date, or if the
  per-field factors disagree, or if the factor is not close to a plausible split
  ratio.
* Reports the factor and the affected row span before writing.
* Dry-run by default; `--apply` writes.

Usage
-----
  uv run python scripts/repoint_snapshot_from_db.py \
    --csv paper/garch-x-vix/data/0050_tw_vix_2007-2022.csv \
    --ticker 0050.TW --prefix 0050_tw --cut-date 2014-01-02
  ... then re-run with --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "cache" / "price_cache.db"

FIELDS = ["open", "high", "low", "close", "adj_close", "volume"]


def load_db(db_path: Path, ticker: str) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql(
            "SELECT date, open, high, low, close, adj_close, volume "
            "FROM price_data WHERE ticker = ? ORDER BY date",
            conn,
            params=(ticker,),
        )
    if df.empty:
        raise SystemExit(f"[repoint] DB has no rows for ticker {ticker}")
    return df.set_index("date")


def resolve_columns(csv_cols: list[str], prefix: str) -> dict[str, str]:
    """Map DB field -> CSV column, tolerating both `<prefix>_<field>` and bare `<field>`."""
    mapping: dict[str, str] = {}
    for field in FIELDS:
        for candidate in (f"{prefix}_{field}", field):
            if candidate in csv_cols:
                mapping[field] = candidate
                break
    if not mapping:
        raise SystemExit(
            f"[repoint] no price columns found for prefix '{prefix}' in {csv_cols[:12]}…"
        )
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="Snapshot CSV path (repo-relative or absolute)")
    ap.add_argument("--ticker", required=True, help="DB ticker, e.g. 0050.TW")
    ap.add_argument("--prefix", required=True, help="CSV column prefix, e.g. 0050_tw")
    ap.add_argument("--cut-date", required=True, help="First post-break date, e.g. 2014-01-02")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--apply", action="store_true", help="Write the file (default: dry-run)")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = REPO_ROOT / csv_path
    if not csv_path.exists():
        raise SystemExit(f"[repoint] missing CSV: {csv_path}")

    csv = pd.read_csv(csv_path)
    if "date" not in csv.columns:
        raise SystemExit("[repoint] CSV has no 'date' column")
    db = load_db(Path(args.db), args.ticker)
    cols = resolve_columns(list(csv.columns), args.prefix)

    cut = args.cut_date
    pre_mask = csv["date"] < cut
    if not pre_mask.any():
        raise SystemExit(f"[repoint] no rows before cut date {cut}")

    lead = cols.get("adj_close") or cols.get("close") or next(iter(cols.values()))
    have_data = csv[lead].notna()
    missing = sorted(set(csv.loc[have_data, "date"]) - set(db.index))
    if missing:
        raise SystemExit(
            f"[repoint] {len(missing)} dates carry {args.prefix} data but are absent from the DB "
            f"(first: {missing[:3]}) — cannot derive the break factor from the DB"
        )

    # The DB is the reference: it must itself be clean across the cut.
    db_before = db.loc[db.index < cut, "close"].iloc[-1]
    db_after = db.loc[db.index >= cut, "close"].iloc[0]
    if not 0.5 < db_after / db_before < 2.0:
        raise SystemExit(
            f"[repoint] DB still shows a break at {cut} "
            f"(close {db_before:.4f} -> {db_after:.4f}) — repair the DB first"
        )

    print(f"[repoint] {csv_path.relative_to(REPO_ROOT)}  ticker={args.ticker} prefix={args.prefix}")

    # Derive one factor per field from the pre-break overlap, then require agreement.
    factors: dict[str, float] = {}
    for field, col in cols.items():
        pre = csv.loc[pre_mask & csv[col].notna(), ["date", col]]
        if pre.empty:
            continue
        ref = pre["date"].map(db[field]).astype(float)
        ratio = (pre[col].astype(float) / ref.replace(0.0, float("nan"))).dropna()
        if ratio.empty:
            continue
        factors[field] = float(ratio.median())
        spread = float((ratio / factors[field] - 1.0).abs().max())
        if spread > 1e-6:
            raise SystemExit(
                f"[repoint] {col}: pre-break ratio to DB is not a constant "
                f"(median {factors[field]:.6f}, max deviation {spread:.2e}) — "
                "this is not a pure level break; inspect manually"
            )

    price_factors = {f: v for f, v in factors.items() if f != "volume"}
    if not price_factors:
        raise SystemExit("[repoint] no price columns to repair")
    factor = float(pd.Series(list(price_factors.values())).median())
    if max(abs(v / factor - 1.0) for v in price_factors.values()) > 1e-6:
        raise SystemExit(f"[repoint] price fields disagree on the break factor: {price_factors}")
    if abs(factor - 1.0) < 1e-6:
        print("[repoint] snapshot already continuous at the cut date — nothing to do")
        return 0
    if min(abs(factor - c) for c in (2, 3, 4, 5, 10, 0.5, 0.25, 0.2, 0.1)) > 0.02:
        raise SystemExit(f"[repoint] break factor {factor:.4f} is not a plausible split ratio")

    n_pre = int((pre_mask & csv[lead].notna()).sum())
    print(
        f"    break factor = {factor:.6f} (prices divided, volume multiplied) — "
        f"{n_pre} rows before {cut} "
        f"({csv.loc[pre_mask & csv[lead].notna(), 'date'].iloc[0]}.."
        f"{csv.loc[pre_mask & csv[lead].notna(), 'date'].iloc[-1]})"
    )
    for field, col in cols.items():
        if field not in factors:
            continue
        scale = factor if field != "volume" else 1.0 / factor
        csv.loc[pre_mask, col] = csv.loc[pre_mask, col] / scale
        print(f"    {col:24s} pre-break {'/' if field != 'volume' else '*'} {factor:.4f}")

    # Post-condition: the repaired snapshot must be continuous across the cut.
    close_col = cols.get("close") or cols.get("adj_close")
    if close_col:
        left = csv.loc[pre_mask & csv[close_col].notna(), close_col].iloc[-1]
        right = csv.loc[~pre_mask & csv[close_col].notna(), close_col].iloc[0]
        if not 0.5 < right / left < 2.0:
            raise SystemExit(f"[repoint] post-repair still discontinuous: {left:.4f} -> {right:.4f}")
        print(f"    continuity check OK: {close_col} {left:.4f} -> {right:.4f}")
    if not args.apply:
        print("[repoint] dry-run — re-run with --apply to write")
        return 0

    # Rewrite in place at text level: only the repaired cells change, every other
    # field keeps its original literal. A pandas round-trip would reformat the
    # last digit of thousands of untouched cells and bury the real diff.
    lines = csv_path.read_text().splitlines()
    header = lines[0].split(",")
    idx = {col: header.index(col) for col in cols.values()}
    date_i = header.index("date")
    scales = {
        idx[col]: (factor if field != "volume" else 1.0 / factor)
        for field, col in cols.items()
        if field in factors
    }
    out = [lines[0]]
    n_written = 0
    for line in lines[1:]:
        parts = line.split(",")
        if parts[date_i] < cut:
            touched = False
            for i, scale in scales.items():
                if parts[i]:
                    parts[i] = repr(float(parts[i]) / scale)
                    touched = True
            if touched:
                n_written += 1
            line = ",".join(parts)
        out.append(line)
    csv_path.write_text("\n".join(out) + "\n")
    print(f"[repoint] WROTE {csv_path.relative_to(REPO_ROOT)} ({n_written} rows repaired)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
