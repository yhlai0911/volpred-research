"""
K1268: Parse 15-min GDELT export.CSV files into 5-min event/sentiment bars.

GDELT 2.0 export.CSV is tab-separated, no header. Columns we need:
  0  GLOBALEVENTID (int)
  1  SQLDATE (YYYYMMDD)
  ...
  26 GoldsteinScale (float, -10..+10)
  29 NumMentions
  31 AvgTone (float, -100..+100, typically -10..+10)
  ...

We aggregate counts + tone by 15-min slot (the file's nominal timestamp), then
upsample-by-forward-fill to 5-min bars (each 15-min slot replicates 3 times) so
GDELT bars align with SPY 5-min bars.

Reference: GDELT 2.0 events column header
http://data.gdeltproject.org/documentation/CSV.header.dailyupdates.txt
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("k1268_agg")

DATA_DIR = Path(__file__).parent / "data"
OUT_PATH = Path(__file__).parent / "gdelt_5min_bars.parquet"

# 0-indexed column positions in GDELT 2.0 events (61 cols)
COL_GOLDSTEIN = 30  # GoldsteinScale (1-indexed 31 in docs; 0-indexed 30)
COL_AVGTONE = 34  # AvgTone (1-indexed 35; 0-indexed 34)


def parse_one(path: Path) -> dict | None:
    """Parse one GDELT export.csv -> aggregate stats for the 15-min slot."""
    if path.stat().st_size == 0:
        return None
    n = 0
    g_sum = 0.0
    g_n = 0
    t_sum = 0.0
    t_n = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 35:
                    continue
                n += 1
                try:
                    g = float(row[COL_GOLDSTEIN])
                    g_sum += g
                    g_n += 1
                except (ValueError, IndexError):
                    pass
                try:
                    t = float(row[COL_AVGTONE])
                    t_sum += t
                    t_n += 1
                except (ValueError, IndexError):
                    pass
    except Exception as e:  # noqa: BLE001
        log.warning("parse fail %s: %s", path.name, e)
        return None
    return {
        "count": n,
        "goldstein_mean": (g_sum / g_n) if g_n else np.nan,
        "avgtone_mean": (t_sum / t_n) if t_n else np.nan,
    }


def aggregate_day(date_str: str) -> pd.DataFrame:
    day_dir = DATA_DIR / date_str
    if not day_dir.exists():
        log.warning("missing dir %s", day_dir)
        return pd.DataFrame()
    rows = []
    files = sorted(day_dir.glob("*.export.csv"))
    for fp in files:
        slot = fp.stem.split(".")[0]  # YYYYMMDDHHMMSS
        ts = datetime.strptime(slot, "%Y%m%d%H%M%S")
        rec = parse_one(fp)
        if rec is None:
            continue
        rec["ts"] = ts
        rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    log.info("%s: %d 15-min bars parsed", date_str, len(df))
    return df


def upsample_to_5min(df_15min: pd.DataFrame) -> pd.DataFrame:
    """15-min slots -> 5-min bars by forward-fill (each slot replicates 3 times)."""
    if df_15min.empty:
        return df_15min
    # Build full 5-min index spanning the day
    start = df_15min.index.min()
    end = df_15min.index.max() + pd.Timedelta(minutes=14)
    idx5 = pd.date_range(start=start, end=end, freq="5min")
    df5 = df_15min.reindex(idx5).ffill(limit=2)  # ffill 2 = 10 min after each :00/:15/:30/:45
    return df5


def main():
    from k1268_fetch_gdelt import EVENT_DAYS
    all_frames = {}
    summary = {}
    for d in EVENT_DAYS:
        df15 = aggregate_day(d)
        df5 = upsample_to_5min(df15)
        if df5.empty:
            summary[d] = {"bars_5min": 0, "skip": "no_data"}
            continue
        all_frames[d] = df5
        summary[d] = {
            "bars_5min": int(len(df5)),
            "count_mean": float(df5["count"].mean()),
            "count_max": int(df5["count"].max()),
            "goldstein_mean": float(df5["goldstein_mean"].mean()),
            "avgtone_mean": float(df5["avgtone_mean"].mean()),
        }

    if not all_frames:
        log.error("No data aggregated for any event day; abort.")
        return 1

    combined = pd.concat([df.assign(day=d) for d, df in all_frames.items()])
    combined.to_parquet(OUT_PATH)
    (Path(__file__).parent / "aggregate_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Wrote %s (%d total 5-min bars)", OUT_PATH, len(combined))
    log.info("Summary: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
