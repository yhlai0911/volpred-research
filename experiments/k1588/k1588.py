#!/usr/bin/env python3
"""K1588: Social connectedness and earnings-announcement volatility reactions.

Public-data proxy for the SCI-based hypothesis:
 - SCI county centrality comes from the public HDX Social Connectedness Index.
 - Headquarters county is inferred from the public S&P 500 constituents snapshot
   and geocoded via OpenStreetMap Nominatim.
 - Earnings announcements and daily prices come from yfinance.

The experiment is intentionally conservative:
 - earnings timestamps are aligned to the first trading day *after* the
   announcement date to avoid same-day lookahead;
 - the volatility reaction is measured with close-to-close |log return| and
   squared log return, because free public intraday data is unavailable here;
 - SCI is a contemporaneous county connectivity snapshot, not a historical
   panel, so results are associational rather than causal.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


SEED = 42
rng = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "2018-01-01"
END_DATE = "2026-06-30"
EVENT_LOOKBACK = 22
EVENT_PRE_BASELINE = slice(-22, -2)  # exclude t-1 and event day
POST_HORIZON = 5
MAX_TICKERS = 120
EARNS_LIMIT = 24
N_BOOT = 300
PANIC_VIX_THRESHOLD = 20.0

SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
FIPS_URL = "https://raw.githubusercontent.com/kjhealy/us-county/master/data/census/fips-by-state.csv"
SCI_US_COUNTIES_URL = (
    "https://data.humdata.org/dataset/e9988552-74e4-4ff4-943f-c782ac8bca87/"
    "resource/97dc352f-c9c5-47d6-a6ef-88709e14006c/download/us_counties.csv"
)

STATE_NAME_TO_ABBR = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}

ABBR_TO_STATE_NAME = {v: k for k, v in STATE_NAME_TO_ABBR.items()}


def json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if not math.isfinite(v) else v
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, (pd.Timedelta,)):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return [json_safe(v) for v in obj]
    return obj


def norm_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_county_name(name: str) -> str:
    text = norm_text(name)
    text = re.sub(
        r"\b(county|parish|borough|census area|city and borough|municipality|city)\b",
        "",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def normalize_state_name(name: str) -> str:
    return norm_text(name)


def ticker_to_yf(symbol: str) -> str:
    return symbol.replace(".", "-")


def load_csv_cached(url: str, path: Path, *, encoding: str = "utf-8") -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode(encoding, errors="replace")
    path.write_text(text, encoding="utf-8")
    return pd.read_csv(path)


def load_constituents() -> pd.DataFrame:
    path = DATA_DIR / "sp500_constituents.csv"
    if path.exists():
        return pd.read_csv(path)
    df = load_csv_cached(SP500_URL, path)
    return df


def load_state_crosswalk() -> pd.DataFrame:
    path = DATA_DIR / "fips_by_state.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"fips": str, "state": str})
    resp = requests.get(FIPS_URL, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode("latin1", errors="replace")
    path.write_text(text, encoding="utf-8")
    return pd.read_csv(path, dtype={"fips": str, "state": str})


def geocode_hq_location(location: str, session: requests.Session) -> dict[str, Any]:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{location}, United States",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 3,
        "countrycodes": "us",
    }
    headers = {"User-Agent": "volpred-research/1.0"}
    resp = session.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        return {"county": None, "state": None, "display_name": None}
    best = payload[0]
    addr = best.get("address", {}) or {}
    county = addr.get("county") or addr.get("state_district") or addr.get("city")
    state = addr.get("state")
    return {
        "county": county,
        "state": state,
        "display_name": best.get("display_name"),
        "lat": best.get("lat"),
        "lon": best.get("lon"),
    }


def load_or_build_hq_geocodes(constituents: pd.DataFrame) -> pd.DataFrame:
    path = DATA_DIR / "hq_county_geocodes.csv"
    if path.exists():
        return pd.read_csv(path)

    us = constituents.copy()
    us = us[us["Headquarters Location"].astype(str).str.contains(",")]
    us = us[us["Headquarters Location"].str.split(",").str[-1].str.strip().isin(STATE_NAME_TO_ABBR)]
    us = us[["Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "Headquarters Location"]].copy()
    us = us.sort_values("Symbol").head(MAX_TICKERS).reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    session = requests.Session()
    for i, row in us.iterrows():
        location = row["Headquarters Location"]
        try:
            geocode = geocode_hq_location(location, session)
            geocode_status = "ok" if geocode.get("county") else "missing_county"
        except Exception as exc:  # noqa: BLE001
            geocode = {"county": None, "state": None, "display_name": None}
            geocode_status = f"error:{type(exc).__name__}"
        rows.append(
            {
                "Symbol": row["Symbol"],
                "Security": row["Security"],
                "GICS Sector": row["GICS Sector"],
                "GICS Sub-Industry": row["GICS Sub-Industry"],
                "Headquarters Location": location,
                "county": geocode.get("county"),
                "state_name": geocode.get("state"),
                "display_name": geocode.get("display_name"),
                "lat": geocode.get("lat"),
                "lon": geocode.get("lon"),
                "geocode_status": geocode_status,
            }
        )
        time.sleep(0.35)
        if (i + 1) % 25 == 0:
            print(f"Geocoded {i + 1}/{len(us)} HQ locations")
    out = pd.DataFrame(rows)
    out.to_csv(path, index=False)
    return out


def county_fips_crosswalk(state_crosswalk: pd.DataFrame) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for _, row in state_crosswalk.iterrows():
        county_key = normalize_county_name(row["name"])
        state_key = normalize_state_name(ABBR_TO_STATE_NAME.get(str(row["state"]).strip().upper(), str(row["state"]).strip()))
        out[(county_key, state_key)] = str(row["fips"]).zfill(5)
    return out


def resolve_county_fips(
    county_name: str | None,
    state_name: str | None,
    mapping: dict[tuple[str, str], str],
) -> str | None:
    if not county_name or not state_name:
        return None
    state_name_str = str(state_name).strip()
    state_abbr = STATE_NAME_TO_ABBR.get(state_name_str, state_name_str.upper())
    state_candidates = {
        normalize_state_name(state_name_str),
        normalize_state_name(state_abbr),
        normalize_state_name(ABBR_TO_STATE_NAME.get(state_abbr.upper(), state_abbr)),
    }
    county_key = normalize_county_name(county_name)
    for state_key in state_candidates:
        key = (county_key, state_key)
        if key in mapping:
            return mapping[key]
    # fallback: sometimes OSM returns "county" in the city field, or vice versa
    simplified = re.sub(r"\bcounty\b", "", county_key).strip()
    for (ckey, skey), fips in mapping.items():
        if skey in state_candidates and ckey == simplified:
            return fips
    return None


def build_sci_county_centrality() -> pd.DataFrame:
    path = DATA_DIR / "sci_us_county_centrality.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"fips": str})

    sums: dict[str, float] = defaultdict(float)
    chunk_iter = pd.read_csv(
        SCI_US_COUNTIES_URL,
        usecols=["user_country", "friend_country", "user_region", "friend_region", "scaled_sci"],
        dtype={
            "user_country": str,
            "friend_country": str,
            "user_region": str,
            "friend_region": str,
            "scaled_sci": float,
        },
        chunksize=1_000_000,
    )
    n_rows = 0
    for chunk in chunk_iter:
        n_rows += len(chunk)
        us = chunk[(chunk["user_country"] == "US") & (chunk["friend_country"] == "US")].copy()
        if us.empty:
            continue
        grouped = us.groupby("user_region", dropna=True)["scaled_sci"].sum()
        for fips, value in grouped.items():
            sums[str(fips).zfill(5)] += float(value)
        if n_rows % 2_000_000 < 1_000_000:
            print(f"SCI rows processed: {n_rows:,}")

    df = pd.DataFrame({"fips": list(sums.keys()), "sci_sum": list(sums.values())})
    df["log_sci_sum"] = np.log1p(df["sci_sum"])
    df["sci_z"] = (df["log_sci_sum"] - df["log_sci_sum"].mean()) / df["log_sci_sum"].std(ddof=0)
    df["sci_rank_pct"] = df["sci_sum"].rank(pct=True)
    df = df.sort_values("sci_sum", ascending=False).reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def download_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    path = DATA_DIR / "prices_long.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["date"])

    records: list[pd.DataFrame] = []
    chunk_size = 50
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        raw = yf.download(
            chunk,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            group_by="column",
            threads=True,
        )
        if raw.empty:
            continue
        if not isinstance(raw.columns, pd.MultiIndex):
            raw = pd.concat({chunk[0]: raw}, axis=1)
        for sym in chunk:
            if sym not in raw.columns.get_level_values(-1):
                continue
            try:
                sub = raw.xs(sym, axis=1, level=-1)
            except Exception:
                continue
            need = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in sub.columns]
            if len(need) < 4:
                continue
            sub = sub[need].dropna(subset=[c for c in ["Open", "High", "Low", "Close"] if c in sub.columns])
            if sub.empty:
                continue
            rename = {c: c.lower() for c in sub.columns}
            sub = sub.rename(columns=rename)
            sub["yf_symbol"] = sym
            sub["date"] = sub.index
            records.append(sub.reset_index(drop=True))
    if not records:
        raise RuntimeError("No price data downloaded")
    out = pd.concat(records, ignore_index=True)
    out = out[["yf_symbol", "date", "open", "high", "low", "close", "volume"]]
    out.to_csv(path, index=False)
    return out


def fetch_earnings_dates(symbol: str) -> pd.DataFrame:
    tk = yf.Ticker(symbol)
    try:
        df = tk.get_earnings_dates(limit=EARNS_LIMIT)
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(
            {
                "yf_symbol": [symbol],
                "error": [f"{type(exc).__name__}: {exc}"],
            }
        )
    if df is None or df.empty:
        return pd.DataFrame({"yf_symbol": [symbol], "error": ["empty"]})
    out = df.copy().reset_index()
    out = out.rename(columns={out.columns[0]: "earnings_datetime"})
    out["yf_symbol"] = symbol
    out["earnings_datetime"] = pd.to_datetime(out["earnings_datetime"], errors="coerce")
    if getattr(out["earnings_datetime"].dt, "tz", None) is not None:
        out["earnings_datetime"] = out["earnings_datetime"].dt.tz_convert(None)
    out["earnings_date"] = pd.to_datetime(out["earnings_datetime"], errors="coerce")
    if "Surprise(%)" in out.columns:
        out = out.rename(columns={"Surprise(%)": "surprise_pct"})
    elif "Surprise (%)" in out.columns:
        out = out.rename(columns={"Surprise (%)": "surprise_pct"})
    else:
        out["surprise_pct"] = np.nan
    return out


def load_earnings_panel(symbols: list[str]) -> pd.DataFrame:
    path = DATA_DIR / "earnings_dates.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["earnings_date", "earnings_datetime"])

    rows: list[pd.DataFrame] = []
    for i, sym in enumerate(symbols, start=1):
        out = fetch_earnings_dates(sym)
        rows.append(out)
        if i % 20 == 0:
            print(f"Fetched earnings dates for {i}/{len(symbols)} tickers")
        time.sleep(0.15)
    df = pd.concat(rows, ignore_index=True)
    df.to_csv(path, index=False)
    return df


def make_event_panel(
    prices: pd.DataFrame,
    earnings: pd.DataFrame,
    hq: pd.DataFrame,
    centrality: pd.DataFrame,
    county_map: dict[tuple[str, str], str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_wide = prices.pivot(index="date", columns="yf_symbol", values="close").sort_index()
    logret_wide = np.log(price_wide).diff()
    absret_wide = logret_wide.abs()
    rv_wide = logret_wide.pow(2)
    vix = price_wide.get("^VIX")
    if vix is None:
        raise RuntimeError("^VIX missing from price panel")

    hq = hq.copy()
    hq["yf_symbol"] = hq["Symbol"].map(ticker_to_yf)
    hq["state_abbr"] = hq["state_name"].map(STATE_NAME_TO_ABBR)
    hq["county_fips"] = [
        resolve_county_fips(row["county"], row["state_name"], county_map) for _, row in hq.iterrows()
    ]
    hq = hq[hq["county_fips"].notna()].copy()

    centrality = centrality.copy()
    centrality["fips"] = centrality["fips"].astype(str).str.zfill(5)
    county_stats = (
        hq.merge(centrality[["fips", "sci_sum", "log_sci_sum", "sci_z", "sci_rank_pct"]], left_on="county_fips", right_on="fips", how="left")
        .rename(columns={"sci_z": "county_sci_z"})
    )

    event_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    earnings = earnings.copy()
    earnings["yf_symbol"] = earnings["yf_symbol"].astype(str)
    earnings["earnings_date"] = pd.to_datetime(earnings["earnings_date"], errors="coerce")
    earnings = earnings[(earnings["earnings_date"] >= pd.Timestamp(START_DATE)) & (earnings["earnings_date"] <= pd.Timestamp(END_DATE))]

    meta_cols = [
        "Symbol",
        "Security",
        "GICS Sector",
        "GICS Sub-Industry",
        "Headquarters Location",
        "county",
        "state_name",
        "county_fips",
        "sci_sum",
        "log_sci_sum",
        "county_sci_z",
        "sci_rank_pct",
    ]
    county_stats = county_stats[meta_cols].drop_duplicates("Symbol").copy()

    tickers = [c for c in price_wide.columns if c != "^VIX"]
    for _, meta in county_stats.iterrows():
        sym = meta["Symbol"]
        yf_sym = ticker_to_yf(sym)
        if yf_sym not in price_wide.columns:
            continue
        p = price_wide[yf_sym].dropna()
        if p.empty:
            continue
        lr = np.log(p).diff()
        absret = lr.abs()
        rv = lr.pow(2)
        earn_rows = earnings[earnings["yf_symbol"] == yf_sym].copy()
        if earn_rows.empty:
            continue
        for _, erow in earn_rows.iterrows():
            e_date = pd.Timestamp(erow["earnings_date"]).tz_localize(None) if pd.Timestamp(erow["earnings_date"]).tzinfo else pd.Timestamp(erow["earnings_date"])
            pos = p.index.searchsorted(e_date, side="right")
            if pos < EVENT_LOOKBACK or pos + POST_HORIZON >= len(p.index):
                continue
            pre_start = pos + EVENT_PRE_BASELINE.start
            pre_end = pos + EVENT_PRE_BASELINE.stop
            pre_abs = absret.iloc[pre_start:pre_end]
            pre_rv = rv.iloc[pre_start:pre_end]
            if pre_abs.isna().any() or pre_rv.isna().any():
                continue
            event_abs = float(absret.iloc[pos])
            event_rv = float(rv.iloc[pos])
            post_abs = absret.iloc[pos + 1 : pos + 1 + POST_HORIZON]
            post_rv = rv.iloc[pos + 1 : pos + 1 + POST_HORIZON]
            if post_abs.isna().any() or post_rv.isna().any():
                continue
            pre_abs_mean = float(pre_abs.mean())
            pre_rv_mean = float(pre_rv.mean())
            post_abs_mean = float(post_abs.mean())
            post_rv_mean = float(post_rv.mean())
            event_day = pd.Timestamp(p.index[pos])
            vix_level = float(vix.reindex([event_day]).iloc[0]) if event_day in vix.index else float(vix.loc[:event_day].iloc[-1])
            surprise = float(erow.get("surprise_pct", np.nan)) if pd.notna(erow.get("surprise_pct", np.nan)) else np.nan
            base = {
                "Symbol": sym,
                "yf_symbol": yf_sym,
                "Security": meta["Security"],
                "sector": meta["GICS Sector"],
                "sub_industry": meta["GICS Sub-Industry"],
                "hq_location": meta["Headquarters Location"],
                "county": meta["county"],
                "state_name": meta["state_name"],
                "county_fips": meta["county_fips"],
                "county_sci_sum": float(meta["sci_sum"]),
                "county_log_sci_sum": float(meta["log_sci_sum"]),
                "county_sci_z": float(meta["county_sci_z"]),
                "county_sci_rank_pct": float(meta["sci_rank_pct"]),
                "earnings_date": pd.Timestamp(erow["earnings_date"]).isoformat(),
                "event_day": event_day.isoformat(),
                "surprise_pct": surprise,
                "vix_level": vix_level,
                "high_vix": int(vix_level >= PANIC_VIX_THRESHOLD),
                "pre_abs_mean": pre_abs_mean,
                "pre_rv_mean": pre_rv_mean,
                "event_abs": event_abs,
                "event_rv": event_rv,
                "post_abs_mean": post_abs_mean,
                "post_rv_mean": post_rv_mean,
                "jump_log_abs": math.log((event_abs + 1e-8) / (pre_abs_mean + 1e-8)),
                "jump_log_rv": math.log((event_rv + 1e-10) / (pre_rv_mean + 1e-10)),
                "decay_speed_log_abs": math.log((event_abs + 1e-8) / (post_abs_mean + 1e-8)),
                "decay_speed_log_rv": math.log((event_rv + 1e-10) / (post_rv_mean + 1e-10)),
                "abs_event_abn": event_abs - pre_abs_mean,
                "rv_event_abn": event_rv - pre_rv_mean,
                "abs_decay_abn": event_abs - post_abs_mean,
                "rv_decay_abn": event_rv - post_rv_mean,
                "sample_year": event_day.year,
                "sample_quarter": int((event_day.month - 1) / 3) + 1,
            }
            event_rows.append(base)
            for h in range(0, POST_HORIZON + 1):
                abs_h = float(absret.iloc[pos + h])
                rv_h = float(rv.iloc[pos + h])
                profile_rows.append(
                    {
                        **base,
                        "h": h,
                        "absret_h": abs_h,
                        "rv_h": rv_h,
                        "log_abs_ratio_h": math.log((abs_h + 1e-8) / (pre_abs_mean + 1e-8)),
                        "log_rv_ratio_h": math.log((rv_h + 1e-10) / (pre_rv_mean + 1e-10)),
                    }
                )
    event_df = pd.DataFrame(event_rows)
    profile_df = pd.DataFrame(profile_rows)
    return event_df, profile_df


def winsorize(s: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    qlo, qhi = s.quantile(lo), s.quantile(hi)
    return s.clip(qlo, qhi)


def build_design(df: pd.DataFrame, outcome: str, *, interaction: bool = True) -> tuple[pd.Series, pd.DataFrame]:
    work = df.copy()
    work = work.dropna(subset=[outcome, "county_sci_z", "surprise_pct", "pre_abs_mean", "sector", "sample_year"])
    work["surprise_pct"] = winsorize(work["surprise_pct"].fillna(0.0))
    work["surprise_z"] = (work["surprise_pct"] - work["surprise_pct"].mean()) / work["surprise_pct"].std(ddof=0)
    work["pre_log_abs"] = np.log(work["pre_abs_mean"] + 1e-8)
    work["high_vix"] = work["high_vix"].astype(int)
    work["county_sci_z"] = (work["county_sci_z"] - work["county_sci_z"].mean()) / work["county_sci_z"].std(ddof=0)
    cols = ["county_sci_z", "surprise_z", "pre_log_abs", "high_vix"]
    if interaction:
        work["sci_x_high_vix"] = work["county_sci_z"] * work["high_vix"]
        cols.append("sci_x_high_vix")
    dummies = pd.get_dummies(work[["sector", "sample_year"]].astype({"sample_year": str}), drop_first=True)
    X = pd.concat([work[cols], dummies], axis=1)
    X = sm.add_constant(X, has_constant="add")
    X = X.astype(float)
    y = work[outcome].astype(float)
    return y, X


def fit_cluster_ols(df: pd.DataFrame, outcome: str, *, interaction: bool = True) -> dict[str, Any]:
    y, X = build_design(df, outcome, interaction=interaction)
    model = sm.OLS(y, X, missing="drop")
    res = model.fit(cov_type="cluster", cov_kwds={"groups": df.loc[y.index, "yf_symbol"]})
    return {
        "nobs": int(res.nobs),
        "params": {k: float(v) for k, v in res.params.items()},
        "bse": {k: float(v) for k, v in res.bse.items()},
        "tvalues": {k: float(v) for k, v in res.tvalues.items()},
        "pvalues": {k: float(v) for k, v in res.pvalues.items()},
        "rsquared": float(res.rsquared),
        "adj_rsquared": float(res.rsquared_adj),
        "model": res,
        "X": X,
        "y": y,
    }


def cluster_bootstrap(df: pd.DataFrame, outcome: str, *, interaction: bool = True, n_boot: int = N_BOOT) -> dict[str, Any]:
    groups = df["yf_symbol"].dropna().unique().tolist()
    if len(groups) < 2:
        return {"n_boot": 0, "ci": {}, "boot_sd": {}}
    draws: dict[str, list[float]] = defaultdict(list)
    for b in range(n_boot):
        sampled_groups = rng.choice(groups, size=len(groups), replace=True)
        boot = pd.concat([df[df["yf_symbol"] == g] for g in sampled_groups], ignore_index=True)
        try:
            fit = fit_cluster_ols(boot, outcome, interaction=interaction)
        except Exception:
            continue
        for key in ["county_sci_z", "sci_x_high_vix"]:
            if key in fit["params"]:
                draws[key].append(float(fit["params"][key]))
    ci: dict[str, dict[str, float]] = {}
    boot_sd: dict[str, float] = {}
    for key, vals in draws.items():
        if not vals:
            continue
        arr = np.asarray(vals, dtype=float)
        ci[key] = {
            "lo": float(np.quantile(arr, 0.025)),
            "hi": float(np.quantile(arr, 0.975)),
        }
        boot_sd[key] = float(arr.std(ddof=1))
    return {"n_boot": n_boot, "ci": ci, "boot_sd": boot_sd, "draws_n": {k: len(v) for k, v in draws.items()}}


def horizon_coefficients(profile_df: pd.DataFrame, outcome_col: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for h in sorted(profile_df["h"].unique()):
        sub = profile_df[profile_df["h"] == h].copy()
        sub = sub.dropna(subset=[outcome_col, "county_sci_z", "surprise_pct", "sector", "sample_year"])
        sub["surprise_pct"] = winsorize(sub["surprise_pct"].fillna(0.0))
        sub["surprise_z"] = (sub["surprise_pct"] - sub["surprise_pct"].mean()) / sub["surprise_pct"].std(ddof=0)
        sub["county_sci_z"] = (sub["county_sci_z"] - sub["county_sci_z"].mean()) / sub["county_sci_z"].std(ddof=0)
        sub["pre_log_abs"] = np.log(sub["pre_abs_mean"] + 1e-8)
        sub["sci_x_high_vix"] = sub["county_sci_z"] * sub["high_vix"]
        dummies = pd.get_dummies(sub[["sector", "sample_year"]].astype({"sample_year": str}), drop_first=True)
        X = pd.concat([sub[["county_sci_z", "surprise_z", "pre_log_abs", "high_vix", "sci_x_high_vix"]], dummies], axis=1)
        X = sm.add_constant(X, has_constant="add")
        X = X.astype(float)
        y = sub[outcome_col].astype(float)
        res = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": sub["yf_symbol"]})
        rows.append(
            {
                "h": int(h),
                "nobs": int(res.nobs),
                "coef_sci": float(res.params.get("county_sci_z", np.nan)),
                "t_sci": float(res.tvalues.get("county_sci_z", np.nan)),
                "p_sci": float(res.pvalues.get("county_sci_z", np.nan)),
                "coef_high_vix": float(res.params.get("high_vix", np.nan)),
                "coef_interaction": float(res.params.get("sci_x_high_vix", np.nan)) if "sci_x_high_vix" in res.params else np.nan,
                "rsquared": float(res.rsquared),
            }
        )
    return pd.DataFrame(rows)


def tercile_summary(df: pd.DataFrame, outcome: str) -> pd.DataFrame:
    work = df.dropna(subset=[outcome, "county_sci_z"]).copy()
    work["tercile"] = pd.qcut(work["county_sci_z"], q=3, labels=["Low SCI", "Mid SCI", "High SCI"])
    out = (
        work.groupby("tercile", observed=False)[outcome]
        .agg(["count", "mean", "median", "std"])
        .reset_index()
        .rename(columns={"count": "n"})
    )
    return out


def welch_test(high: pd.Series, low: pd.Series) -> dict[str, float]:
    t, p = stats.ttest_ind(high, low, equal_var=False, nan_policy="omit")
    return {"t": float(t), "p": float(p), "mean_diff": float(high.mean() - low.mean())}


def bootstrap_group_diff(df: pd.DataFrame, outcome: str, group_col: str = "tercile", n_boot: int = 1000) -> dict[str, Any]:
    work = df.dropna(subset=[outcome, "county_sci_z"]).copy()
    work[group_col] = pd.qcut(work["county_sci_z"], q=3, labels=["Low SCI", "Mid SCI", "High SCI"])
    groups = work["yf_symbol"].unique().tolist()
    if len(groups) < 2:
        return {"n_boot": 0, "ci": {}, "boot_sd": {}}
    diffs: list[float] = []
    for _ in range(n_boot):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        boot = pd.concat([work[work["yf_symbol"] == g] for g in sampled], ignore_index=True)
        if boot.empty:
            continue
        terc = boot.groupby(group_col, observed=False)[outcome].mean()
        if {"High SCI", "Low SCI"} <= set(terc.index):
            diffs.append(float(terc["High SCI"] - terc["Low SCI"]))
    arr = np.asarray(diffs, dtype=float)
    return {
        "n_boot": n_boot,
        "draws_n": len(diffs),
        "ci": {
            "lo": float(np.quantile(arr, 0.025)) if len(arr) else np.nan,
            "hi": float(np.quantile(arr, 0.975)) if len(arr) else np.nan,
        },
        "boot_sd": float(arr.std(ddof=1)) if len(arr) > 1 else np.nan,
    }


def plot_profiles(profile_df: pd.DataFrame, horizon_abs: pd.DataFrame, horizon_rv: pd.DataFrame) -> list[str]:
    paths: list[str] = []
    work = profile_df.dropna(subset=["county_sci_z", "log_abs_ratio_h", "log_rv_ratio_h"]).copy()
    work["sci_tercile"] = pd.qcut(work["county_sci_z"], q=3, labels=["Low SCI", "Mid SCI", "High SCI"])
    agg = (
        work.groupby(["h", "sci_tercile"], observed=False)[["log_abs_ratio_h", "log_rv_ratio_h"]]
        .mean()
        .reset_index()
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharex=True)
    for terc, g in agg.groupby("sci_tercile", observed=False):
        axes[0].plot(g["h"].to_numpy(), g["log_abs_ratio_h"].to_numpy(), marker="o", label=str(terc))
        axes[1].plot(g["h"].to_numpy(), g["log_rv_ratio_h"].to_numpy(), marker="o", label=str(terc))
    for ax, title, ylabel in [
        (axes[0], "Abnormal |log return| ratio around earnings", "log(abs_t / pre_mean)"),
        (axes[1], "Abnormal squared-return ratio around earnings", "log(rv_t / pre_mean)"),
    ]:
        ax.axhline(0, color="black", lw=1, alpha=0.6)
        ax.axvline(0, color="#666666", lw=1, ls="--", alpha=0.6)
        ax.set_title(title)
        ax.set_xlabel("Event day horizon h")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.2)
    axes[0].legend(frameon=False, fontsize=9, loc="best")
    fig.tight_layout()
    path1 = FIG_DIR / "k1588_event_profile_by_sci_tercile.png"
    fig.savefig(path1, dpi=180, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path1))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharex=True)
    for coefs, ax, title in [
        (horizon_abs, axes[0], "SCI slope by horizon for abnormal |log return|"),
        (horizon_rv, axes[1], "SCI slope by horizon for abnormal squared return"),
    ]:
        ax.plot(coefs["h"].to_numpy(), coefs["coef_sci"].to_numpy(), marker="o", color="#2563eb", label="SCI slope")
        ax.axhline(0, color="black", lw=1, alpha=0.6)
        ax.axvline(0, color="#666666", lw=1, ls="--", alpha=0.6)
        ax.set_xlabel("Event day horizon h")
        ax.set_ylabel("SCI coefficient")
        ax.grid(True, alpha=0.2)
        ax.set_title(title)
    fig.tight_layout()
    path2 = FIG_DIR / "k1588_sci_horizon_coefficients.png"
    fig.savefig(path2, dpi=180, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path2))
    return paths


def verdict_from_results(full_jump: dict[str, Any], full_decay: dict[str, Any], oos_jump: dict[str, Any], oos_decay: dict[str, Any]) -> str:
    jump_coef = full_jump["params"].get("county_sci_z", np.nan)
    decay_coef = full_decay["params"].get("county_sci_z", np.nan)
    jump_ci = full_jump.get("bootstrap", {}).get("ci", {}).get("county_sci_z", {})
    decay_ci = full_decay.get("bootstrap", {}).get("ci", {}).get("county_sci_z", {})
    jump_sig = jump_ci and jump_ci.get("lo", -1) > 0 or jump_ci and jump_ci.get("hi", 1) < 0
    decay_sig = decay_ci and decay_ci.get("lo", -1) > 0 or decay_ci and decay_ci.get("hi", 1) < 0
    oos_jump_sign = np.sign(oos_jump["params"].get("county_sci_z", 0.0))
    oos_decay_sign = np.sign(oos_decay["params"].get("county_sci_z", 0.0))
    hypothesized = (jump_coef > 0) and (decay_coef > 0) and (oos_jump_sign >= 0) and (oos_decay_sign >= 0)
    conditional = ((jump_coef > 0) or (decay_coef > 0)) and (oos_jump_sign >= 0 or oos_decay_sign >= 0)
    if hypothesized and jump_sig and decay_sig:
        return "PASS"
    if conditional and (jump_sig or decay_sig):
        return "CONDITIONAL_PASS"
    if (jump_coef < 0 and decay_coef < 0) or (oos_jump_sign < 0 and oos_decay_sign < 0):
        return "FAIL"
    return "NULL"


def main() -> None:
    constituents = load_constituents()
    state_crosswalk = load_state_crosswalk()

    global hq_crosswalk
    hq_geocodes = load_or_build_hq_geocodes(constituents)
    hq_crosswalk = hq_geocodes.copy()

    geocode_diag = {
        "n_constituents": int(len(constituents)),
        "n_us_selected": int(len(hq_geocodes)),
        "n_geocoded_ok": int((hq_geocodes["geocode_status"] == "ok").sum()),
        "n_missing_county": int((hq_geocodes["geocode_status"] == "missing_county").sum()),
        "n_errors": int(hq_geocodes["geocode_status"].str.startswith("error").sum()),
    }

    county_map = county_fips_crosswalk(state_crosswalk)
    hq_geocodes["county_fips"] = [
        resolve_county_fips(row["county"], row["state_name"], county_map) for _, row in hq_geocodes.iterrows()
    ]
    hq_geocodes.to_csv(DATA_DIR / "hq_county_geocodes.csv", index=False)
    geocode_diag["n_county_fips_matched"] = int(hq_geocodes["county_fips"].notna().sum())

    centrality = build_sci_county_centrality()
    hq_geocodes["county_fips"] = hq_geocodes["county_fips"].astype("string")
    hq_geo_central = hq_geocodes.merge(centrality, left_on="county_fips", right_on="fips", how="left")
    hq_geo_central.to_csv(DATA_DIR / "hq_with_sci.csv", index=False)

    symbols = hq_geocodes["Symbol"].tolist()
    yf_symbols = [ticker_to_yf(s) for s in symbols] + ["^VIX"]
    prices = download_prices(yf_symbols, START_DATE, END_DATE)
    prices.to_csv(DATA_DIR / "prices_long.csv", index=False)

    earnings = load_earnings_panel([ticker_to_yf(s) for s in symbols])
    earnings.to_csv(DATA_DIR / "earnings_dates.csv", index=False)

    event_df, profile_df = make_event_panel(prices, earnings, hq_geocodes, centrality, county_map)
    event_df.to_csv(DATA_DIR / "event_panel.csv", index=False)
    profile_df.to_csv(DATA_DIR / "event_profile_panel.csv", index=False)

    if event_df.empty:
        raise RuntimeError("No matched event observations were created")

    train = event_df[event_df["event_day"] < "2024-01-01"].copy()
    oos = event_df[event_df["event_day"] >= "2024-01-01"].copy()

    results: dict[str, Any] = {
        "experiment_id": "K1588",
        "title": "Social connectedness and earnings-announcement volatility reactions",
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "data": {
            "data_source": [
                "HDX Social Connectedness Index us_counties.csv (public county pair SCI snapshot)",
                "datasets/s-and-p-500-companies constituents.csv (public S&P 500 HQ snapshot)",
                "OpenStreetMap Nominatim geocoder (public HQ county lookup)",
                "yfinance daily OHLCV and earnings dates",
            ],
            "period": {"start": START_DATE, "end": END_DATE},
            "selection": {
                "max_tickers": MAX_TICKERS,
                "earnings_limit_per_ticker": EARNS_LIMIT,
                "lookback_days": EVENT_LOOKBACK,
                "post_horizon_days": POST_HORIZON,
                "panic_vix_threshold": PANIC_VIX_THRESHOLD,
            },
            "diagnostics": geocode_diag,
            "sample_size": {
                "tickers": int(event_df["yf_symbol"].nunique()),
                "events": int(len(event_df)),
                "profile_rows": int(len(profile_df)),
                "train_events": int(len(train)),
                "oos_events": int(len(oos)),
            },
            "coverage": {
                "median_vix": float(event_df["vix_level"].median()),
                "share_high_vix": float(event_df["high_vix"].mean()),
                "county_sci_matched_share": float(event_df["county_sci_z"].notna().mean()),
                "earnings_surprise_available_share": float(event_df["surprise_pct"].notna().mean()),
            },
        },
        "methods": {
            "target": "daily close-to-close abnormal absolute return and squared return around earnings announcements",
            "lookahead_guard": "reaction day = first trading day after the earnings timestamp date; pre-baseline excludes t-1 and event day",
            "main_outcomes": [
                "jump_log_abs = log(event_abs / pre_mean_abs)",
                "jump_log_rv = log(event_rv / pre_mean_rv)",
                "decay_speed_log_abs = log(event_abs / post_1_5_mean_abs)",
                "decay_speed_log_rv = log(event_rv / post_1_5_mean_rv)",
            ],
            "covariates": [
                "county_sci_z",
                "earnings surprise pct (winsorized z-score)",
                "pre-event log absolute return baseline",
                "sector fixed effects",
                "sample-year fixed effects",
                "VIX regime and SCI×VIX interaction",
            ],
            "tests": [
                "cluster-robust OLS by ticker",
                f"cluster bootstrap over tickers (seed=42, {N_BOOT} reps)",
                "tercile high-vs-low bootstrap over tickers (seed=42, 1000 reps)",
                "Welch t-test and tercile split for high SCI vs low SCI",
                "horizon profile regressions for h=0..5",
            ],
        },
    }

    full_jump = fit_cluster_ols(event_df, "jump_log_abs", interaction=True)
    full_jump["bootstrap"] = cluster_bootstrap(event_df, "jump_log_abs", interaction=True)
    full_decay = fit_cluster_ols(event_df, "decay_speed_log_abs", interaction=True)
    full_decay["bootstrap"] = cluster_bootstrap(event_df, "decay_speed_log_abs", interaction=True)

    full_jump_rv = fit_cluster_ols(event_df, "jump_log_rv", interaction=True)
    full_decay_rv = fit_cluster_ols(event_df, "decay_speed_log_rv", interaction=True)

    train_jump = fit_cluster_ols(train, "jump_log_abs", interaction=True) if len(train) else None
    train_decay = fit_cluster_ols(train, "decay_speed_log_abs", interaction=True) if len(train) else None
    oos_jump = fit_cluster_ols(oos, "jump_log_abs", interaction=True) if len(oos) else {"params": {}, "pvalues": {}, "nobs": 0}
    oos_decay = fit_cluster_ols(oos, "decay_speed_log_abs", interaction=True) if len(oos) else {"params": {}, "pvalues": {}, "nobs": 0}

    jump_terc = tercile_summary(event_df, "jump_log_abs")
    decay_terc = tercile_summary(event_df, "decay_speed_log_abs")
    jump_welch = welch_test(
        event_df.loc[event_df["county_sci_z"] >= event_df["county_sci_z"].quantile(2 / 3), "jump_log_abs"],
        event_df.loc[event_df["county_sci_z"] <= event_df["county_sci_z"].quantile(1 / 3), "jump_log_abs"],
    )
    decay_welch = welch_test(
        event_df.loc[event_df["county_sci_z"] >= event_df["county_sci_z"].quantile(2 / 3), "decay_speed_log_abs"],
        event_df.loc[event_df["county_sci_z"] <= event_df["county_sci_z"].quantile(1 / 3), "decay_speed_log_abs"],
    )
    jump_boot = bootstrap_group_diff(event_df, "jump_log_abs", n_boot=1000)
    decay_boot = bootstrap_group_diff(event_df, "decay_speed_log_abs", n_boot=1000)

    event_df = event_df.dropna(subset=["county_sci_z"]).copy()
    event_df["sci_tercile"] = pd.qcut(event_df["county_sci_z"], q=3, labels=["Low SCI", "Mid SCI", "High SCI"])
    event_df["abs_event_rank"] = event_df.groupby("sci_tercile", observed=False)["event_abs"].rank(pct=True)

    horizon_abs = horizon_coefficients(profile_df, "log_abs_ratio_h")
    horizon_rv = horizon_coefficients(profile_df, "log_rv_ratio_h")
    plot_paths = plot_profiles(profile_df, horizon_abs, horizon_rv)

    verdict = verdict_from_results(full_jump, full_decay, oos_jump, oos_decay)

    results.update(
        {
            "model": {
                "full_sample": {
                    "jump_log_abs": {
                        "params": {k: float(v) for k, v in full_jump["params"].items()},
                        "pvalues": {k: float(v) for k, v in full_jump["pvalues"].items()},
                        "cluster_bootstrap": full_jump["bootstrap"],
                        "nobs": full_jump["nobs"],
                        "rsquared": full_jump["rsquared"],
                    },
                    "decay_speed_log_abs": {
                        "params": {k: float(v) for k, v in full_decay["params"].items()},
                        "pvalues": {k: float(v) for k, v in full_decay["pvalues"].items()},
                        "cluster_bootstrap": full_decay["bootstrap"],
                        "nobs": full_decay["nobs"],
                        "rsquared": full_decay["rsquared"],
                    },
                    "jump_log_rv": {
                        "params": {k: float(v) for k, v in full_jump_rv["params"].items()},
                        "pvalues": {k: float(v) for k, v in full_jump_rv["pvalues"].items()},
                        "nobs": full_jump_rv["nobs"],
                        "rsquared": full_jump_rv["rsquared"],
                    },
                    "decay_speed_log_rv": {
                        "params": {k: float(v) for k, v in full_decay_rv["params"].items()},
                        "pvalues": {k: float(v) for k, v in full_decay_rv["pvalues"].items()},
                        "nobs": full_decay_rv["nobs"],
                        "rsquared": full_decay_rv["rsquared"],
                    },
                },
                "train_split": {
                    "train_end": "2023-12-31",
                    "jump_log_abs": None
                    if train_jump is None
                    else {
                        "params": {k: float(v) for k, v in train_jump["params"].items()},
                        "pvalues": {k: float(v) for k, v in train_jump["pvalues"].items()},
                        "nobs": train_jump["nobs"],
                        "rsquared": train_jump["rsquared"],
                    },
                    "decay_speed_log_abs": None
                    if train_decay is None
                    else {
                        "params": {k: float(v) for k, v in train_decay["params"].items()},
                        "pvalues": {k: float(v) for k, v in train_decay["pvalues"].items()},
                        "nobs": train_decay["nobs"],
                        "rsquared": train_decay["rsquared"],
                    },
                    "oos_jump_log_abs": {
                        "params": {k: float(v) for k, v in oos_jump["params"].items()},
                        "pvalues": {k: float(v) for k, v in oos_jump["pvalues"].items()},
                        "nobs": oos_jump["nobs"],
                    },
                    "oos_decay_speed_log_abs": {
                        "params": {k: float(v) for k, v in oos_decay["params"].items()},
                        "pvalues": {k: float(v) for k, v in oos_decay["pvalues"].items()},
                        "nobs": oos_decay["nobs"],
                    },
                },
                "horizon_profile": {
                    "abs": json_safe(horizon_abs.to_dict(orient="records")),
                    "rv": json_safe(horizon_rv.to_dict(orient="records")),
                },
            },
            "results": {
                "jump_tercile_summary": json_safe(jump_terc.to_dict(orient="records")),
                "decay_tercile_summary": json_safe(decay_terc.to_dict(orient="records")),
                "welch_tests": {
                    "jump_log_abs_high_vs_low": jump_welch,
                    "decay_speed_log_abs_high_vs_low": decay_welch,
                },
                "bootstrap_group_diff": {
                    "jump_log_abs": jump_boot,
                    "decay_speed_log_abs": decay_boot,
                },
                "interpretive_cut": {
                    "jump_sign_expected": "positive",
                    "decay_sign_expected": "positive",
                },
            },
            "verdict": verdict,
            "limitations": [
                "SCI is a contemporaneous county-pair snapshot, not a time-varying panel; this is an associational proxy, not causal identification.",
                "HQ county is inferred from current public headquarters locations and geocoded via Nominatim; historical relocations are not tracked.",
                "Earnings timestamps from yfinance are used as the announcement date; the market reaction is aligned to the first trading day after the timestamp date to avoid lookahead, but exact pre/post-open timing is unavailable.",
                "Daily close-to-close |log return| and squared return are proxies for realized volatility; intraday RV would be cleaner but is not publicly available here at scale.",
                "The selected universe is a public S&P 500 snapshot trimmed to US-headquartered tickers with available earnings history; coverage is broad but not exhaustive.",
            ],
            "literature": [
                {
                    "authors": "Bailey, Kuchler, Stroebel, and Wong",
                    "year": 2018,
                    "title": "Social Connectedness: Measurement, Determinants, and Effects",
                    "venue": "Journal of Economic Perspectives",
                    "url": "https://www.aeaweb.org/articles?id=10.1257/jep.32.3.259",
                    "relevance": "Foundational SCI paper and the public county-pair network used here as the connectivity proxy.",
                },
                {
                    "authors": "Hirshleifer, Peng, and Wang",
                    "year": 2025,
                    "title": "Social Networks and Market Reactions to Earnings News",
                    "venue": "Review of Financial Studies",
                    "url": "https://academic.oup.com/rfs",
                    "relevance": "Closest finance target: social-network connectedness and earnings-announcement market reactions.",
                },
                {
                    "authors": "Sui and Wang",
                    "year": 2025,
                    "title": "Social transmission bias: evidence from an online investor platform",
                    "venue": "Review of Finance",
                    "url": "https://academic.oup.com/rof",
                    "relevance": "Related social-transmission mechanism for post-news trading and volatility spillovers.",
                },
            ],
            "artifacts": {
                "hq_geocodes": str(DATA_DIR / "hq_county_geocodes.csv"),
                "hq_with_sci": str(DATA_DIR / "hq_with_sci.csv"),
                "county_centrality": str(DATA_DIR / "sci_us_county_centrality.csv"),
                "prices": str(DATA_DIR / "prices_long.csv"),
                "earnings_dates": str(DATA_DIR / "earnings_dates.csv"),
                "event_panel": str(DATA_DIR / "event_panel.csv"),
                "event_profile_panel": str(DATA_DIR / "event_profile_panel.csv"),
                "figures": plot_paths,
            },
        }
    )

    results["verdict_reason"] = {
        "jump_log_abs_sci_coef": full_jump["params"].get("county_sci_z"),
        "jump_log_abs_sci_pvalue": full_jump["pvalues"].get("county_sci_z"),
        "decay_speed_log_abs_sci_coef": full_decay["params"].get("county_sci_z"),
        "decay_speed_log_abs_sci_pvalue": full_decay["pvalues"].get("county_sci_z"),
        "oos_jump_log_abs_sci_coef": oos_jump["params"].get("county_sci_z"),
        "oos_decay_speed_log_abs_sci_coef": oos_decay["params"].get("county_sci_z"),
    }

    out_path = ROOT / "k1588_results.json"
    out_path.write_text(json.dumps(json_safe(results), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Verdict: {verdict}")


if __name__ == "__main__":
    main()
