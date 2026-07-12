"""K1701 data layer — point-in-time index membership + price cache.

Builds *point-in-time* (PIT) constituent baskets for the S&P 500 and the Taiwan 50
by walking Wikipedia's index-change tables backwards from the current membership.
This avoids the naive "apply today's constituent list to history" approach, which
carries both survivorship bias (blown-up names silently dropped) and look-ahead
membership bias (recent additions injected into their pre-index high-vol years).

Outputs (all under experiments/k1701/data/):
  raw_sp500_current.csv / raw_sp500_changes.csv   Wikipedia snapshots (with fetch date)
  raw_tw50_current.csv  / raw_tw50_changes.csv
  membership_SPX.csv / membership_TW50.csv        PIT membership, one row per (date, ticker)
  prices_us.parquet / prices_tw.parquet           adjusted close, wide
  data_manifest.json                              provenance + coverage diagnostics

Run: uv run python experiments/k1701/k1701_data.py
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
TW50_URL = "https://zh.wikipedia.org/wiki/%E8%87%BA%E7%81%A350%E6%8C%87%E6%95%B8"

# Download buffer: 22d/66d rolling windows need history before the sample starts.
DOWNLOAD_START = "2009-01-01"
SAMPLE_START = "2010-01-01"

INDEX_PROXIES = {"SPX": "SPY", "TW50": "0050.TW"}
EXTRA_US = ["SPY", "^VIX", "^GSPC", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
EXTRA_TW = ["0050.TW", "^TWII"]


def _fetch_tables(url: str) -> list[pd.DataFrame]:
    resp = requests.get(url, headers=UA, timeout=45)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def _flat_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        "_".join(str(p) for p in c) if isinstance(c, tuple) else str(c) for c in df.columns
    ]
    return df


def _yf_us(ticker: str) -> str:
    """Wikipedia writes share classes as BRK.B; yfinance wants BRK-B."""
    return str(ticker).strip().upper().replace(".", "-")


# ── S&P 500 ────────────────────────────────────────────────────────────────────

def build_sp500_membership(fetch_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = _fetch_tables(SP500_URL)
    current = tables[0]
    changes = _flat_cols(tables[1])

    cur_tickers = sorted({_yf_us(t) for t in current["Symbol"].dropna()})

    changes = changes.rename(
        columns={
            "Effective Date_Effective Date": "date",
            "Added_Ticker": "added",
            "Removed_Ticker": "removed",
            "Reason_Reason": "reason",
        }
    )[["date", "added", "removed", "reason"]]
    changes["date"] = pd.to_datetime(changes["date"], format="mixed", errors="coerce")
    changes = changes.dropna(subset=["date"]).sort_values("date")

    events = []
    for _, row in changes.iterrows():
        events.append(
            {
                "date": row["date"],
                "added": _yf_us(row["added"]) if pd.notna(row["added"]) else None,
                "removed": _yf_us(row["removed"]) if pd.notna(row["removed"]) else None,
            }
        )

    snapshots = _walk_back(cur_tickers, events, fetch_date)
    return current, changes, snapshots


# ── Taiwan 50 ─────────────────────────────────────────────────────────────────

_TW_CODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _tw_codes(cell: object) -> list[str]:
    if pd.isna(cell):
        return []
    return [f"{c}.TW" for c in _TW_CODE.findall(str(cell))]


def _tw_month_end(cell: object) -> pd.Timestamp | None:
    """'2025年9月' -> 2025-09-30.

    TWSE reviews the Taiwan 50 quarterly; the new basket becomes effective on the
    trading day after the third Friday of the review month, and the change is
    announced roughly two weeks earlier.  Wikipedia only records the month, so we
    stamp the change at month-END.  That is deliberately *late* rather than early:
    a late stamp keeps the stale basket for a few extra weeks (realistic for a
    real-time user) whereas an early stamp would inject membership look-ahead.
    """
    m = re.search(r"(\d{4})\D+(\d{1,2})", str(cell))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def build_tw50_membership(fetch_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = _fetch_tables(TW50_URL)
    current_raw = tables[0]
    changes_raw = tables[1]

    cur_tickers = sorted(
        {t for col in current_raw.columns if "股票代號" in str(col) for t in _tw_codes(" ".join(map(str, current_raw[col].dropna())))}
    )
    if len(cur_tickers) < 45:  # the table is a 2-column layout; make sure we got ~50
        raise RuntimeError(f"TW50 current membership parse looks wrong: {len(cur_tickers)} tickers")

    rows = []
    for _, row in changes_raw.iterrows():
        eff = _tw_month_end(row["日期"])
        if eff is None:
            continue
        rows.append(
            {
                "date": eff,
                "added": _tw_codes(row.get("納入指數")),
                "removed": _tw_codes(row.get("剔除指數")),
            }
        )
    changes = pd.DataFrame(rows).sort_values("date")

    events = []
    for _, row in changes.iterrows():
        n = max(len(row["added"]), len(row["removed"]), 1)
        for i in range(n):
            events.append(
                {
                    "date": row["date"],
                    "added": row["added"][i] if i < len(row["added"]) else None,
                    "removed": row["removed"][i] if i < len(row["removed"]) else None,
                }
            )

    snapshots = _walk_back(cur_tickers, events, fetch_date)
    return current_raw, changes, snapshots


# ── PIT reconstruction ────────────────────────────────────────────────────────

def _walk_back(
    current: list[str], events: list[dict], fetch_date: pd.Timestamp
) -> pd.DataFrame:
    """Reconstruct membership backwards in time from the current basket.

    Membership just BEFORE a change at date d is  (membership after d) - {added} + {removed}.
    Processing events in descending date order therefore yields the basket that was
    live over every historical interval.
    """
    members = set(current)
    # (effective_from, effective_to, members) — most recent interval first
    intervals: list[tuple[pd.Timestamp, pd.Timestamp, set[str]]] = []

    events_desc = sorted(events, key=lambda e: e["date"], reverse=True)
    interval_end = fetch_date
    i = 0
    while i < len(events_desc):
        d = events_desc[i]["date"]
        # apply every event stamped with the same effective date at once
        same_day = []
        while i < len(events_desc) and events_desc[i]["date"] == d:
            same_day.append(events_desc[i])
            i += 1

        if d <= interval_end:
            intervals.append((d, interval_end, set(members)))
            interval_end = d - pd.Timedelta(days=1)

        for ev in same_day:
            if ev["added"]:
                members.discard(ev["added"])
            if ev["removed"]:
                members.add(ev["removed"])

    intervals.append((pd.Timestamp("1990-01-01"), interval_end, set(members)))

    rows = []
    for start, end, mem in intervals:
        for t in sorted(mem):
            rows.append({"start": start, "end": end, "ticker": t})
    return pd.DataFrame(rows).sort_values(["start", "ticker"])


def membership_on(snapshots: pd.DataFrame, day: pd.Timestamp) -> list[str]:
    hit = snapshots[(snapshots["start"] <= day) & (snapshots["end"] >= day)]
    return sorted(hit["ticker"].tolist())


# ── prices ────────────────────────────────────────────────────────────────────

def download_prices(tickers: list[str], label: str, chunk: int = 60) -> pd.DataFrame:
    frames = []
    uniq = sorted(set(tickers))
    for k in range(0, len(uniq), chunk):
        batch = uniq[k : k + chunk]
        print(f"  [{label}] {k + 1}-{k + len(batch)} / {len(uniq)}", flush=True)
        for attempt in range(3):
            try:
                raw = yf.download(
                    batch,
                    start=DOWNLOAD_START,
                    auto_adjust=True,          # Close is split/dividend adjusted
                    progress=False,
                    threads=True,
                    group_by="column",
                    timeout=60,
                )
                break
            except Exception as exc:  # transient yfinance/network failure
                print(f"    retry {attempt + 1}: {type(exc).__name__} {exc}", flush=True)
                time.sleep(5 * (attempt + 1))
        else:
            print(f"    !! batch failed permanently: {batch[:5]}...", flush=True)
            continue

        if raw is None or len(raw) == 0:
            continue
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if isinstance(close, pd.Series):
            close = close.to_frame(batch[0])
        frames.append(close)
        time.sleep(1.0)

    if not frames:
        raise RuntimeError(f"no price data downloaded for {label}")
    px = pd.concat(frames, axis=1)
    px = px.loc[:, ~px.columns.duplicated()]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px.sort_index()


def main() -> None:
    fetch_ts = datetime.now(timezone.utc)
    fetch_date = pd.Timestamp(fetch_ts.date())
    print(f"K1701 data build — Wikipedia fetch date {fetch_date.date()}")

    print("[1/4] S&P 500 membership")
    sp_cur, sp_ch, sp_snap = build_sp500_membership(fetch_date)
    sp_cur.to_csv(DATA / "raw_sp500_current.csv", index=False)
    sp_ch.to_csv(DATA / "raw_sp500_changes.csv", index=False)
    sp_snap.to_csv(DATA / "membership_SPX.csv", index=False)

    print("[2/4] Taiwan 50 membership")
    tw_cur, tw_ch, tw_snap = build_tw50_membership(fetch_date)
    tw_cur.to_csv(DATA / "raw_tw50_current.csv", index=False)
    tw_ch.to_csv(DATA / "raw_tw50_changes.csv", index=False)
    tw_snap.to_csv(DATA / "membership_TW50.csv", index=False)

    us_tickers = sorted(set(sp_snap["ticker"]) | set(EXTRA_US))
    tw_tickers = sorted(set(tw_snap["ticker"]) | set(EXTRA_TW))
    print(f"  SPX  universe (ever a member 1990+): {len(us_tickers)} tickers")
    print(f"  TW50 universe: {len(tw_tickers)} tickers")

    print("[3/4] downloading US prices")
    px_us = download_prices(us_tickers, "US")
    px_us.to_parquet(DATA / "prices_us.parquet")

    print("[4/4] downloading TW prices")
    px_tw = download_prices(tw_tickers, "TW")
    px_tw.to_parquet(DATA / "prices_tw.parquet")

    # coverage diagnostic: on each year-end, what share of PIT members has prices?
    coverage = {}
    for name, snap, px in (("SPX", sp_snap, px_us), ("TW50", tw_snap, px_tw)):
        per_year = {}
        for year in range(2010, fetch_date.year + 1):
            day = min(pd.Timestamp(f"{year}-06-30"), fetch_date)
            mem = membership_on(snap, day)
            if not mem:
                continue
            window = px.loc[str(day - pd.Timedelta(days=40)) : str(day)]
            have = [t for t in mem if t in px.columns and window[t].notna().sum() >= 15]
            per_year[year] = {
                "members": len(mem),
                "with_prices": len(have),
                "coverage": round(len(have) / len(mem), 4),
            }
        coverage[name] = per_year

    manifest = {
        "k_id": "K1701",
        "fetched_at_utc": fetch_ts.isoformat(),
        "sources": {
            "sp500_wikipedia": SP500_URL,
            "tw50_wikipedia": TW50_URL,
            "prices": "yfinance (auto_adjust=True, adjusted close)",
        },
        "download_start": DOWNLOAD_START,
        "sample_start": SAMPLE_START,
        "index_proxies": INDEX_PROXIES,
        "universe_size": {"SPX": len(us_tickers), "TW50": len(tw_tickers)},
        "price_panel_shape": {"US": list(px_us.shape), "TW": list(px_tw.shape)},
        "pit_membership_coverage_by_year": coverage,
        "tw50_effective_date_convention": (
            "Wikipedia records the review MONTH only; changes are stamped at month-END "
            "(deliberately late, never early, to avoid membership look-ahead)."
        ),
    }
    (DATA / "data_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print("\nCoverage of PIT members with usable prices:")
    for name, per_year in coverage.items():
        line = " ".join(f"{y}:{v['coverage']:.2f}" for y, v in sorted(per_year.items()))
        print(f"  {name}: {line}")
    print(f"\nwrote {DATA}/data_manifest.json")


if __name__ == "__main__":
    sys.exit(main())
