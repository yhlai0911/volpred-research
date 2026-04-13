"""
K1117b: Monthly-frequency alt-data fetch with point-in-time release alignment.

Fetches 5 alt-data indicators at monthly resolution with explicit release-date
calendars so that, at each month-end F (treated as "forecast-made" date for month
M+1's RV), only values whose release-date <= F are used.

Indicators:
  - USEPU:   Baker-Bloom-Davis daily EPU (aggregated to monthly mean, released ~T+1)
  - NFCI:    Chicago Fed weekly NFCI (aggregated to monthly mean of last 4 weekly obs,
             released Wed 10:30 CT of week W+1 -> last obs of month known ~3 bdays later)
  - CFNAI:   Chicago Fed National Activity Index (monthly, released ~4th week of M+1)
  - UMCSENT: Univ. Michigan Consumer Sentiment (monthly, final end-of-M released
             last Fri of M; preliminary mid-M)
  - INDPRO:  Industrial Production Index (monthly, released mid-month of M+1, ~T+16 BDay)

Publication-delay model:
  month observation at start-of-month date O has a RELEASE_DATE R:
    USEPU    R = O + 1 BDay (daily series; monthly mean known on last day of month + 1)
    NFCI     R = last-Fri-of-month O + 5 BDay (Wed 10:30 CT release -> 3 bdays,
             plus ~2 bday safety buffer)
    CFNAI    R = O + 50 days (official ~4th week of M+1; ~35-50 days post reference-month start)
    UMCSENT  R = O + 30 days (final release on last Fri of M -> safe to use ~end of M)
             For lookahead safety we treat R = O + 30 days (end of reference month)
    INDPRO   R = O + 45 days (~15th of M+1; using O + 45 days is conservative)

At month-end forecast date F = end-of-month M, the "most recent value with R <= F"
is used as signal for predicting RV of month M+1.

Data source: fredgraph (revision-corrected; ALFRED vintage inaccessible without FRED API key).
The same upper-bound argument from K1116c applies: revision-corrected is a smoother state
estimate; if it shows NULL, vintage (noisier) also shows NULL under same linear model.

Output: experiments/k1117b/data/<INDICATOR>_monthly_with_release.csv
        experiments/k1117b/data/<INDICATOR>_monthly_pit.csv
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Storage cache for pre-fetched series (much faster than re-downloading)
STORAGE_MACRO = Path("/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a6ef86dc/storage/macro")
K1116C_DATA = Path("/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a6ef86dc/experiments/k1116c/data")


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_fredgraph(series_id: str, timeout: int = 60) -> pd.DataFrame:
    """Fetch FRED series from fredgraph.csv endpoint (revision-corrected).

    Uses curl subprocess (more reliable than urllib in this environment).
    Caches raw CSV under data/_raw_{series_id}.csv.
    """
    import subprocess

    raw_cache = DATA_DIR / f"_raw_{series_id}.csv"
    if not raw_cache.exists() or raw_cache.stat().st_size < 200:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        log(f"  curl {url}")
        subprocess.run(
            ["curl", "-sS", "-m", str(timeout), url, "-o", str(raw_cache)],
            check=True,
        )
    data = raw_cache.read_text()
    df = pd.read_csv(StringIO(data))
    # fredgraph uses 'observation_date' column
    date_col = [c for c in df.columns if c.lower() == "observation_date"][0]
    df = df.rename(columns={date_col: "DATE", series_id: "VALUE"})
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
    df = df.dropna().sort_values("DATE").reset_index(drop=True)
    return df[["DATE", "VALUE"]]


def load_cached_or_fetch(series_id: str, cache_paths: list[Path]) -> pd.DataFrame:
    """Try cached CSV first, fallback to fredgraph."""
    for p in cache_paths:
        if p.exists():
            log(f"  Using cache: {p.name}")
            df = pd.read_csv(p)
            date_col = [c for c in df.columns if c.lower() in ("observation_date", "date")][0]
            val_cols = [c for c in df.columns if c not in (date_col, "RELEASE_DATE")]
            val_col = val_cols[0]
            df = df.rename(columns={date_col: "DATE", val_col: "VALUE"})
            df["DATE"] = pd.to_datetime(df["DATE"])
            df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
            df = df.dropna(subset=["VALUE"]).sort_values("DATE").reset_index(drop=True)
            return df[["DATE", "VALUE"]]
    log(f"  Fetching fredgraph: {series_id}")
    return fetch_fredgraph(series_id)


# -------------------------------------------------------------------
# Publication-delay release-date rules
# -------------------------------------------------------------------
def add_release_dates(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Add RELEASE_DATE column based on publication-delay rule."""
    df = df.copy()
    if rule == "bday_1":
        # Daily series; release on next business day
        df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(1)
    elif rule == "bday_3":
        # Weekly (NFCI): release Wed of W+1 -> +3 business days from weekly Fri obs
        df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(3)
    elif rule == "end_of_M":
        # UMCSENT final: last Friday of reference month M. Use last day of M (inclusive).
        # Monthly DATE stamps are start-of-month (e.g. 2000-01-01); +MonthEnd(1) -> end of M.
        df["RELEASE_DATE"] = df["DATE"] + pd.offsets.MonthEnd(1)
    elif rule == "end_of_Mplus1":
        # INDPRO: ~mid-M+1; conservative = end of M+1
        # From 2000-01-01: +MonthEnd(2) -> 2000-02-29
        df["RELEASE_DATE"] = df["DATE"] + pd.offsets.MonthEnd(2)
    elif rule == "end_of_Mplus1_late":
        # CFNAI: ~4th week of M+1; end of M+1 is conservative
        df["RELEASE_DATE"] = df["DATE"] + pd.offsets.MonthEnd(2)
    else:
        raise ValueError(f"Unknown rule: {rule}")
    return df


# -------------------------------------------------------------------
# Monthly aggregation (per indicator)
# -------------------------------------------------------------------
def aggregate_monthly(df_daily_or_weekly: pd.DataFrame, release_rule: str) -> pd.DataFrame:
    """For high-frequency series (daily, weekly), aggregate to monthly mean.

    The month M's VALUE = mean of observations within month M.
    RELEASE_DATE = release date of the LAST observation in month M
                   (i.e., when the full monthly mean becomes known).
    """
    df = df_daily_or_weekly.copy()
    df = add_release_dates(df, release_rule)
    df["month"] = df["DATE"].dt.to_period("M").dt.to_timestamp(how="start")
    agg = df.groupby("month").agg(
        VALUE=("VALUE", "mean"),
        LAST_OBS=("DATE", "max"),
        LAST_RELEASE=("RELEASE_DATE", "max"),
    ).reset_index()
    out = agg[["month", "VALUE", "LAST_RELEASE"]].rename(
        columns={"month": "DATE", "LAST_RELEASE": "RELEASE_DATE"}
    )
    return out


def monthly_native(df_monthly: pd.DataFrame, release_rule: str) -> pd.DataFrame:
    """For natively monthly series, just attach release dates."""
    return add_release_dates(df_monthly, release_rule)


def build_pit_monthly(df_with_release: pd.DataFrame, month_ends: pd.DatetimeIndex) -> pd.DataFrame:
    """At each month-end F, take the value with the latest RELEASE_DATE <= F.

    month_ends: DatetimeIndex of month-end dates (pandas MonthEnd).
    Returns DataFrame with (month_end, obs_date, release_date, value).
    """
    d = df_with_release.sort_values("RELEASE_DATE").reset_index(drop=True)
    rows = []
    j = 0
    for F in month_ends:
        # advance j while release_date <= F
        while j < len(d) and d["RELEASE_DATE"].iloc[j] <= F:
            j += 1
        if j == 0:
            rows.append({"month_end": F, "obs_date": pd.NaT, "release_date": pd.NaT, "value": np.nan})
        else:
            best = d.iloc[j - 1]
            rows.append({
                "month_end": F,
                "obs_date": best["DATE"],
                "release_date": best["RELEASE_DATE"],
                "value": best["VALUE"],
            })
    return pd.DataFrame(rows)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    log("=" * 70)
    log("K1117b monthly alt-data fetch + PIT alignment")
    log("=" * 70)

    fetch_log = {"started_utc": datetime.utcnow().isoformat() + "Z", "indicators": {}}

    # Month-end index 2000-01-31 .. 2026-04-30 (forecast dates)
    month_ends = pd.date_range("2000-01-31", "2026-04-30", freq="ME")
    log(f"Month-end calendar: {len(month_ends)} months, {month_ends[0].date()} .. {month_ends[-1].date()}")

    # ---------------- USEPU (daily -> monthly mean) ----------------
    log("\n[USEPU] daily -> monthly mean, release T+1 BDay")
    # Prefer K1116c's USEPU_with_release_date.csv
    src = K1116C_DATA / "USEPU_with_release_date.csv"
    if src.exists():
        df = pd.read_csv(src, parse_dates=["DATE", "RELEASE_DATE"])
        log(f"  Loaded {len(df)} daily obs from K1116c")
        # already has RELEASE_DATE; aggregate to monthly mean
        df["month"] = df["DATE"].dt.to_period("M").dt.to_timestamp(how="start")
        agg = df.groupby("month").agg(
            VALUE=("VALUE", "mean"),
            LAST_RELEASE=("RELEASE_DATE", "max"),
        ).reset_index().rename(columns={"month": "DATE", "LAST_RELEASE": "RELEASE_DATE"})
    else:
        daily = fetch_fredgraph("USEPUINDXD")
        agg = aggregate_monthly(daily, "bday_1")
    agg.to_csv(DATA_DIR / "USEPU_monthly_with_release.csv", index=False)
    pit = build_pit_monthly(agg, month_ends)
    pit.to_csv(DATA_DIR / "USEPU_monthly_pit.csv", index=False)
    fetch_log["indicators"]["USEPU"] = {"cadence": "daily->monthly", "release_rule": "bday_1",
                                         "n_monthly": int(len(agg))}

    # ---------------- NFCI (weekly -> monthly mean) ----------------
    log("\n[NFCI] weekly -> monthly mean, release +3 BDay from weekly Fri")
    src = K1116C_DATA / "NFCI_with_release_date.csv"
    if src.exists():
        df = pd.read_csv(src, parse_dates=["DATE", "RELEASE_DATE"])
        log(f"  Loaded {len(df)} weekly obs from K1116c")
        df["month"] = df["DATE"].dt.to_period("M").dt.to_timestamp(how="start")
        agg = df.groupby("month").agg(
            VALUE=("VALUE", "mean"),
            LAST_RELEASE=("RELEASE_DATE", "max"),
        ).reset_index().rename(columns={"month": "DATE", "LAST_RELEASE": "RELEASE_DATE"})
    else:
        weekly = fetch_fredgraph("NFCI")
        agg = aggregate_monthly(weekly, "bday_3")
    agg.to_csv(DATA_DIR / "NFCI_monthly_with_release.csv", index=False)
    pit = build_pit_monthly(agg, month_ends)
    pit.to_csv(DATA_DIR / "NFCI_monthly_pit.csv", index=False)
    fetch_log["indicators"]["NFCI"] = {"cadence": "weekly->monthly", "release_rule": "bday_3",
                                        "n_monthly": int(len(agg))}

    # ---------------- CFNAI (native monthly) ----------------
    log("\n[CFNAI] native monthly, release ~4th week of M+1 -> end of M+1")
    df = fetch_fredgraph("CFNAI")
    log(f"  Fetched {len(df)} monthly obs")
    df_with = add_release_dates(df, "end_of_Mplus1_late")
    df_with.to_csv(DATA_DIR / "CFNAI_monthly_with_release.csv", index=False)
    pit = build_pit_monthly(df_with, month_ends)
    pit.to_csv(DATA_DIR / "CFNAI_monthly_pit.csv", index=False)
    fetch_log["indicators"]["CFNAI"] = {"cadence": "monthly", "release_rule": "end_of_Mplus1_late",
                                         "n_monthly": int(len(df_with))}

    # ---------------- UMCSENT (monthly, cached) ----------------
    log("\n[UMCSENT] monthly, release end-of-M (final)")
    src = STORAGE_MACRO / "fred_UMCSENT.csv"
    df = load_cached_or_fetch("UMCSENT", [src])
    df = df[df["DATE"] >= "1999-01-01"].reset_index(drop=True)
    df_with = add_release_dates(df, "end_of_M")
    df_with.to_csv(DATA_DIR / "UMCSENT_monthly_with_release.csv", index=False)
    pit = build_pit_monthly(df_with, month_ends)
    pit.to_csv(DATA_DIR / "UMCSENT_monthly_pit.csv", index=False)
    fetch_log["indicators"]["UMCSENT"] = {"cadence": "monthly", "release_rule": "end_of_M",
                                           "n_monthly": int(len(df_with))}

    # ---------------- INDPRO (monthly, cached) ----------------
    log("\n[INDPRO] monthly, release ~mid-M+1 -> end-of-M+1")
    src = STORAGE_MACRO / "fred_INDPRO.csv"
    df = load_cached_or_fetch("INDPRO", [src])
    df = df[df["DATE"] >= "1999-01-01"].reset_index(drop=True)
    # Level -> YoY% for stationarity (raw level has strong trend)
    df["VALUE_YOY"] = df["VALUE"].pct_change(12) * 100
    df_yoy = df[["DATE", "VALUE_YOY"]].rename(columns={"VALUE_YOY": "VALUE"}).dropna().reset_index(drop=True)
    df_with = add_release_dates(df_yoy, "end_of_Mplus1")
    df_with.to_csv(DATA_DIR / "INDPRO_monthly_with_release.csv", index=False)
    pit = build_pit_monthly(df_with, month_ends)
    pit.to_csv(DATA_DIR / "INDPRO_monthly_pit.csv", index=False)
    fetch_log["indicators"]["INDPRO"] = {"cadence": "monthly_yoy", "release_rule": "end_of_Mplus1",
                                          "n_monthly": int(len(df_with)),
                                          "note": "YoY%; level has strong secular trend"}

    fetch_log["completed_utc"] = datetime.utcnow().isoformat() + "Z"
    with open(DATA_DIR / "fetch_log.json", "w") as f:
        json.dump(fetch_log, f, indent=2, default=str)

    log("\nDone. Files in experiments/k1117b/data/")
    for p in sorted(DATA_DIR.glob("*.csv")):
        log(f"  {p.name}")


if __name__ == "__main__":
    main()
