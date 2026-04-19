#!/usr/bin/env python3
"""
Create pinned yfinance daily snapshots inside paper/<name>/data/.

Examples:
  uv run python scripts/snapshot_yfinance.py \
    --ticker SPY,VIX \
    --start 2004-01-01 \
    --end 2026-04-19 \
    --paper leverage-direction
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf


PROJECT_ROOT = Path(__file__).resolve().parents[1]

YFINANCE_ALIAS_MAP = {
    "VIX": "^VIX",
    "^VIX": "^VIX",
    "VVIX": "^VVIX",
    "^VVIX": "^VVIX",
    "VIX3M": "^VIX3M",
    "^VIX3M": "^VIX3M",
    "VIX9D": "^VIX9D",
    "^VIX9D": "^VIX9D",
    "GVZ": "^GVZ",
    "^GVZ": "^GVZ",
    "OVX": "^OVX",
    "^OVX": "^OVX",
    "TWII": "^TWII",
    "^TWII": "^TWII",
}

KNOWN_PRICE_FIELDS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pin yfinance daily snapshots to paper/<name>/data/")
    parser.add_argument("--ticker", required=True, help="Comma-separated ticker list, e.g. SPY,VIX")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--paper", required=True, help="Paper folder name under paper/")
    parser.add_argument("--out-suffix", default="", help="Optional suffix appended before .csv")
    return parser.parse_args()


def canonical_ticker(ticker: str) -> str:
    token = ticker.strip()
    if not token:
        raise ValueError("Empty ticker token")
    return YFINANCE_ALIAS_MAP.get(token.upper(), token)


def display_ticker(ticker: str) -> str:
    canonical = canonical_ticker(ticker)
    return canonical[1:] if canonical.startswith("^") else canonical


def slugify_token(token: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", token)).strip("_").lower()


def output_stem(tickers: list[str], start: str, end: str, out_suffix: str) -> str:
    start_year = start[:4]
    end_year = end[:4]
    ticker_part = "_".join(slugify_token(display_ticker(ticker)) for ticker in tickers)
    suffix = f"_{slugify_token(out_suffix)}" if out_suffix else ""
    return f"{ticker_part}_{start_year}-{end_year}{suffix}"


def flatten_columns(frame: pd.DataFrame, requested_tickers: list[str]) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        flattened: list[str] = []
        known_ticker_tokens = {
            canonical_ticker(ticker) for ticker in requested_tickers
        } | {
            display_ticker(ticker) for ticker in requested_tickers
        }
        for column in out.columns.to_flat_index():
            left, right = (str(column[0]), str(column[1]))
            if left in KNOWN_PRICE_FIELDS and right in known_ticker_tokens:
                flattened.append(f"{slugify_token(display_ticker(right))}_{slugify_token(left)}")
            elif right in KNOWN_PRICE_FIELDS and left in known_ticker_tokens:
                flattened.append(f"{slugify_token(display_ticker(left))}_{slugify_token(right)}")
            elif left in KNOWN_PRICE_FIELDS:
                flattened.append(slugify_token(left))
            elif right in KNOWN_PRICE_FIELDS:
                flattened.append(slugify_token(right))
            else:
                flattened.append("_".join(filter(None, (slugify_token(left), slugify_token(right)))))
        out.columns = flattened
    else:
        out.columns = [slugify_token(str(column)) for column in out.columns]
    return out


def normalize_snapshot(frame: pd.DataFrame, requested_tickers: list[str]) -> pd.DataFrame:
    normalized = flatten_columns(frame.reset_index(), requested_tickers)
    if "datetime" in normalized.columns and "date" not in normalized.columns:
        normalized = normalized.rename(columns={"datetime": "date"})
    if "date" not in normalized.columns:
        raise ValueError("yfinance snapshot is missing a date column after reset_index()")
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.strftime("%Y-%m-%d")
    return normalized


def backup_if_needed(path: Path) -> None:
    if not path.exists():
        return
    backup_path = path.with_name(f"{path.stem}_pre_snapshot.csv.bak")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)


def fetch_snapshot(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    data = yf.download(
        tickers=[canonical_ticker(ticker) for ticker in tickers],
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        multi_level_index=False,
    )
    if data is None or data.empty:
        raise ValueError(f"No data returned for {','.join(tickers)}")
    return normalize_snapshot(data, tickers)


def write_snapshot(frame: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    backup_if_needed(out_path)
    frame.to_csv(out_path, index=False)


def run() -> int:
    args = parse_args()
    requested_tickers = [ticker.strip() for ticker in args.ticker.split(",") if ticker.strip()]
    if not requested_tickers:
        raise ValueError("No tickers parsed from --ticker")

    paper_dir = PROJECT_ROOT / "paper" / args.paper
    if not paper_dir.exists():
        raise FileNotFoundError(f"Paper directory not found: {paper_dir}")
    data_dir = paper_dir / "data"

    stem = output_stem(requested_tickers, args.start, args.end, args.out_suffix)
    merged_out = data_dir / f"{stem}.csv"

    try:
        merged = fetch_snapshot(requested_tickers, args.start, args.end)
        write_snapshot(merged, merged_out)
        print(f"[OK] merged snapshot -> {merged_out.relative_to(PROJECT_ROOT)}")
        print(f"[INFO] rows={len(merged)} cols={len(merged.columns)}")
        return 0
    except Exception as exc:
        if len(requested_tickers) == 1:
            print(f"[ERROR] snapshot failed for {requested_tickers[0]}: {exc}", file=sys.stderr)
            return 1

        print(
            f"[WARN] merged fetch failed for {','.join(requested_tickers)}: {exc}. "
            "Falling back to per-ticker snapshots.",
            file=sys.stderr,
        )

    failures: list[str] = []
    for ticker in requested_tickers:
        single_stem = output_stem([ticker], args.start, args.end, args.out_suffix)
        single_out = data_dir / f"{single_stem}.csv"
        try:
            single = fetch_snapshot([ticker], args.start, args.end)
            write_snapshot(single, single_out)
            print(f"[OK] single snapshot -> {single_out.relative_to(PROJECT_ROOT)}")
            print(f"[INFO] ticker={ticker} rows={len(single)} cols={len(single.columns)}")
        except Exception as exc:
            failures.append(f"{ticker}: {exc}")
            print(f"[ERROR] ticker {ticker} failed: {exc}", file=sys.stderr)

    return 1 if len(failures) == len(requested_tickers) else 0


if __name__ == "__main__":
    raise SystemExit(run())
