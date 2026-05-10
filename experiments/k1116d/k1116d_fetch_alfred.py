"""K1116d: True ALFRED first-release vintage fetch via FRED API output_type=4.

Goal: Fetch first-release (vintage) values for EPU, NFCI, ANFCI, STLFSI* using the
FRED API (key now available in .env.local). Produces, per indicator, the value that was
ACTUALLY visible to a market participant on each release date — no post-hoc revisions.

This unblocks K1116c's primary limitation. K1116c could only access fredgraph
revision-corrected values; we argued those are an UPPER BOUND on vintage signal quality
(noisier vintage cannot reveal hidden signal). K1116d tests that argument empirically.

API mechanics
-------------
- `output_type=4` returns first-release observations: one row per (date, first
  realtime_start) pair, where realtime_start is the earliest release.
- For NFCI / ANFCI (weekly), 8-yr window fits comfortably within the 100k vintage cap.
- For USEPU / WLEMU (daily revised), the 8-yr window has 2056+ vintages → exceeds the
  cap. We chunk realtime windows (yearly) and stitch.
- For STLFSI, the live series has rotated through 4 IDs (STLFSI → STLFSI2 → STLFSI3 →
  STLFSI4) as predecessors were discontinued. We chain them by realtime_start so each
  release date carries the value that was actually published as STLFSI-of-the-day.

Data window: 2017-12-01 → 2026-04-13 (matches K1116c).

Author: Yi-Hao Lai + VolPred Research System
Date: 2026-05-09
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

np.random.seed(42)


def load_fred_key() -> str:
    """Load FRED_API_KEY from environment, fallback to .env.local manual parse."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env.local"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("FRED_API_KEY not found in env or .env.local")


FRED_KEY = load_fred_key()
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# (series_id, alias, cadence, release_dow, predecessor_chain)
INDICATOR_PLAN = [
    # Weekly chained STLFSI: STLFSI(<=2020-03), STLFSI2(2020-04..2022-01),
    # STLFSI3(2022-01..2022-11), STLFSI4(2022-11..present)
    {"alias": "STLFSI", "cadence": "weekly_fri", "release_dow": "thursday",
     "chain": [
         ("STLFSI",  "2017-12-01", "2020-04-30"),  # pre-discontinue + a tiny overlap
         ("STLFSI2", "2020-04-01", "2022-01-31"),
         ("STLFSI3", "2022-01-15", "2022-11-30"),
         ("STLFSI4", "2022-11-01", "2026-04-13"),
     ]},
    {"alias": "NFCI", "cadence": "weekly_fri", "release_dow": "wednesday",
     "chain": [("NFCI", "2017-12-01", "2026-04-13")]},
    {"alias": "ANFCI", "cadence": "weekly_fri", "release_dow": "wednesday",
     "chain": [("ANFCI", "2017-12-01", "2026-04-13")]},
    # Daily revised: chunk the realtime window per year so each chunk's vintage cap
    # (1000 vintages) is not exceeded.
    {"alias": "USEPU", "cadence": "daily", "release_dow": "next_day",
     "chain": [("USEPUINDXD", "2017-12-01", "2026-04-13")], "chunk_years": True},
    {"alias": "WLEMU", "cadence": "daily", "release_dow": "next_day",
     "chain": [("WLEMUINDXD", "2017-12-01", "2026-04-13")], "chunk_years": True},
]


def fred_first_release(series_id: str, obs_start: str, obs_end: str,
                       rt_start: str | None = None, rt_end: str | None = None,
                       max_retry: int = 3) -> list[dict]:
    """One API call. Returns list of observation dicts."""
    rt_start = rt_start or obs_start
    rt_end = rt_end or obs_end
    params = dict(
        series_id=series_id,
        api_key=FRED_KEY,
        file_type="json",
        output_type=4,
        observation_start=obs_start,
        observation_end=obs_end,
        realtime_start=rt_start,
        realtime_end=rt_end,
        limit=100000,
    )
    last_err = None
    for attempt in range(max_retry):
        try:
            r = requests.get(BASE_URL, params=params, timeout=30)
            if r.status_code == 200:
                obs = r.json().get("observations", [])
                # Codex 2026-05-11 MINOR (b): explicit cap防呆 — if response size approaches
                # FRED's 100000 cap, warn loudly. Daily 6-month chunk should be ~130-140 obs;
                # anything >50000 means the chunk strategy needs revisiting before silent
                # truncation eats data.
                if len(obs) >= 50_000:
                    print(
                        f"    WARNING {series_id} {obs_start}..{obs_end} returned "
                        f"{len(obs)} obs — approaching FRED limit=100000. Reduce chunk size."
                    )
                return obs
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"FRED API failed for {series_id} {obs_start}..{obs_end}: {last_err}")


def fetch_chained_first_release(plan: dict) -> pd.DataFrame:
    """Fetch first-release vintage for one alias, possibly chaining predecessor series.

    Chunk-boundary fix (K1116d-v2, 2026-05-11)
    -----------------------------------------
    The original implementation used **yearly** obs/realtime chunks
    (`obs_start..obs_end == realtime_start..realtime_end`). For daily series with
    publication delay (USEPUINDXD/WLEMUINDXD release on D+1), an obs date X near
    the chunk boundary has `realtime_start = X+1` which falls **outside** the
    chunk's realtime window when `obs_end == X`. The next chunk starts at
    `X+1` (obs_start) so X is also missing there. Net result: 8 obs dates
    across 7 years dropped at chunk boundaries (Codex 2026-05-11 audit MAJOR).

    Fix: switch to **6-month obs chunks** AND extend `realtime_end` by a
    **14-day overlap** beyond the chunk's obs_end. obs windows themselves are
    non-overlapping (`cur = nxt + 1 day`), so cross-chunk same-DATE duplicates
    are not the main concern — the 14d overlap reaches into the post-window
    realtime span where late first-releases live. The `seen_release_dates`
    set primarily de-dups chain-transition overlaps (STLFSI/STLFSI2/...) and
    catches any stray repeated (release_date, obs_date) pairs. 6-month is
    short enough to keep each call's vintage count well under FRED's 100k
    cap (~ 130 vintages/chunk for daily; assert-style warning in
    `fred_first_release` triggers if response approaches 50000).
    """
    rows: list[dict] = []
    seen_release_dates: set = set()  # de-dup across chain overlap zones

    chunk_yearly = plan.get("chunk_years", False)
    for series_id, obs_start, obs_end in plan["chain"]:
        if chunk_yearly:
            # 6-month obs chunks, with 14-day realtime_end overlap into the next obs
            # window so observations at the boundary (whose first release is D+1+)
            # are still captured.
            ranges = []
            cur = pd.to_datetime(obs_start)
            end = pd.to_datetime(obs_end)
            while cur < end:
                nxt = min(cur + pd.DateOffset(months=6), end)
                # observation window: cur..nxt (inclusive on both ends per FRED API)
                # realtime window: cur..nxt+14d so D+1..D+14 first releases of obs
                # near nxt are reachable. Overlap is de-duped via seen_release_dates.
                rt_end = min(nxt + pd.DateOffset(days=14), end + pd.DateOffset(days=14))
                ranges.append((
                    cur.strftime("%Y-%m-%d"),
                    nxt.strftime("%Y-%m-%d"),
                    cur.strftime("%Y-%m-%d"),
                    rt_end.strftime("%Y-%m-%d"),
                ))
                # advance: next chunk starts day after nxt to avoid duplicate obs
                # boundary; seen_release_dates handles any residual overlap.
                cur = nxt + pd.DateOffset(days=1)
        else:
            ranges = [(obs_start, obs_end, obs_start, obs_end)]

        for s, e, rs, re_ in ranges:
            print(f"    {series_id}  obs {s}..{e}  rt {rs}..{re_}", flush=True)
            obs = fred_first_release(series_id, s, e, rt_start=rs, rt_end=re_)
            for o in obs:
                # de-dup on (release_date, observation_date) — chain overlaps possible
                key = (o["realtime_start"], o["date"])
                if key in seen_release_dates:
                    continue
                seen_release_dates.add(key)
                if o["value"] in ("", "."):
                    continue
                try:
                    val = float(o["value"])
                except ValueError:
                    continue
                rows.append({
                    "DATE": pd.to_datetime(o["date"]),
                    "VALUE": val,
                    "RELEASE_DATE": pd.to_datetime(o["realtime_start"]),
                    "SOURCE_SERIES": series_id,
                })
            time.sleep(0.3)

    df = pd.DataFrame(rows).sort_values(["RELEASE_DATE", "DATE"]).reset_index(drop=True)
    # if same DATE appears with multiple RELEASE_DATEs (chain transition or
    # 14-day chunk overlap zone), keep earliest release — that is the true
    # first publication.
    df = df.drop_duplicates(subset=["DATE"], keep="first").reset_index(drop=True)
    return df


def resample_point_in_time(df: pd.DataFrame, freq: str = "W-FRI") -> pd.DataFrame:
    """At each W-FRI Friday F, take the most recent observation whose RELEASE_DATE <= F."""
    if df.empty:
        return pd.DataFrame(columns=["week_end", "obs_date", "release_date", "value"])
    fridays = pd.date_range(df["DATE"].min(), df["DATE"].max() + pd.Timedelta(days=14), freq=freq)
    out = []
    df_sorted = df.sort_values("RELEASE_DATE").reset_index(drop=True)
    for f in fridays:
        avail = df_sorted[df_sorted["RELEASE_DATE"] <= f]
        if len(avail) == 0:
            continue
        row = avail.iloc[-1]
        out.append({
            "week_end": f,
            "obs_date": row["DATE"],
            "release_date": row["RELEASE_DATE"],
            "value": row["VALUE"],
        })
    return pd.DataFrame(out)


def main():
    print("=" * 70)
    print("K1116d: TRUE ALFRED first-release vintage fetch (FRED API output_type=4)")
    print("=" * 70)

    log = {
        "attempt_timestamp": pd.Timestamp.now().isoformat(),
        "fred_api_key_present": True,
        "method": "FRED API output_type=4 (first release per observation date)",
        "indicators": {},
    }

    for plan in INDICATOR_PLAN:
        alias = plan["alias"]
        print(f"\n[{alias}] cadence={plan['cadence']}  chain={[c[0] for c in plan['chain']]}")
        # idempotent skip if both vintage + PIT files exist and non-empty
        vintage_csv = DATA_DIR / f"{alias}_vintage_with_release_date.csv"
        pit_csv = DATA_DIR / f"{alias}_weekly_pit.csv"
        if vintage_csv.exists() and pit_csv.exists():
            try:
                v_df = pd.read_csv(vintage_csv)
                p_df = pd.read_csv(pit_csv)
                if len(v_df) > 100 and len(p_df) > 100:
                    print(f"  SKIP (cached): vintage={len(v_df)} pit={len(p_df)}")
                    log["indicators"][alias] = {
                        "rows_vintage": int(len(v_df)),
                        "rows_pit_weekly": int(len(p_df)),
                        "cached": True,
                    }
                    continue
            except Exception:
                pass
        try:
            df = fetch_chained_first_release(plan)
            print(f"  fetched {len(df)} first-release rows  "
                  f"DATE {df['DATE'].min().date()}..{df['DATE'].max().date()}  "
                  f"REL  {df['RELEASE_DATE'].min().date()}..{df['RELEASE_DATE'].max().date()}")

            # save raw with release dates
            df.to_csv(DATA_DIR / f"{alias}_vintage_with_release_date.csv", index=False)

            # PIT weekly W-FRI panel
            pit = resample_point_in_time(df)
            pit.to_csv(DATA_DIR / f"{alias}_weekly_pit.csv", index=False)
            print(f"  weekly PIT: {len(pit)} rows")

            log["indicators"][alias] = {
                "rows_vintage": int(len(df)),
                "rows_pit_weekly": int(len(pit)),
                "obs_range": [str(df["DATE"].min().date()), str(df["DATE"].max().date())],
                "release_range": [str(df["RELEASE_DATE"].min().date()),
                                  str(df["RELEASE_DATE"].max().date())],
                "chain": [c[0] for c in plan["chain"]],
                "source_breakdown": df.groupby("SOURCE_SERIES").size().to_dict(),
            }
        except Exception as exc:
            print(f"  FAILED: {exc}")
            log["indicators"][alias] = {"error": str(exc)}

    with open(DATA_DIR / "fetch_log.json", "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"\nFetch log saved: {DATA_DIR / 'fetch_log.json'}")

    # also dump a "fredgraph revision-corrected" comparison snapshot for diagnostic
    # so K1116d can compare vintage vs revised in §4.x of README.
    print("\nFetching revision-corrected (fredgraph) for comparison snapshots...")
    for plan in INDICATOR_PLAN:
        alias = plan["alias"]
        rev_path = DATA_DIR / f"{alias}_revised_snapshot.csv"
        if rev_path.exists():
            try:
                rev_df = pd.read_csv(rev_path)
                if len(rev_df) > 50:
                    print(f"  {alias} revised snapshot: cached {len(rev_df)} rows")
                    continue
            except Exception:
                pass
        # use the LAST series in the chain as 'current' identity
        last_sid = plan["chain"][-1][0]
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={last_sid}"
            r = requests.get(url, timeout=20)
            if r.status_code == 200 and r.text:
                from io import StringIO
                rev = pd.read_csv(StringIO(r.text))
                rev.columns = [c.strip() for c in rev.columns]
                rev = rev.rename(columns={rev.columns[0]: "DATE", rev.columns[1]: "VALUE"})
                rev["DATE"] = pd.to_datetime(rev["DATE"])
                rev["VALUE"] = pd.to_numeric(rev["VALUE"], errors="coerce")
                rev = rev.dropna(subset=["VALUE"])
                rev = rev[(rev["DATE"] >= "2017-12-01") & (rev["DATE"] <= "2026-04-13")]
                rev.to_csv(DATA_DIR / f"{alias}_revised_snapshot.csv", index=False)
                print(f"  {alias} revised snapshot: {len(rev)} rows")
        except Exception as exc:
            print(f"  {alias} revised snapshot fetch failed: {exc}")
    print("=" * 70)


if __name__ == "__main__":
    main()
