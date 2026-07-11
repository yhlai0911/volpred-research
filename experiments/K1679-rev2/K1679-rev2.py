#!/usr/bin/env python3
"""
K1679-rev2 — Knowledge-grade revision #3 of the regional-bank deposit-flight test.

Lineage
-------
* K1679       (merged, Codex FAIL): current-vintage signal, DM/HLN only, no CW on
              the real hit, floor artefact.
* K1679-rev   (merged, Codex FAIL): added ALFRED first-release signal + Clark-West +
              un-floored MSE, BUT (a) ran CW only on the two OLD 4w cells and
              extrapolated `any_reject=False` onto the BH-surviving PIT hit
              (dep_flight_13w·rv·H5) that never got a CW test; (b) the verdict logic
              ignored sign + Bonferroni and mislabelled a Bonferroni-significant
              POSITIVE-t cell (signal HURTS) as an unremarkable "FDR-only" null;
              (c) called `output_type=4` (Initial Release Only) a point-in-time
              vintage, which it is not.

This revision (K1679-rev2) fixes exactly those three, keeping every PASS item.

Three fixes
-----------
1. CLARK-WEST ON THE REAL HIT — AND THE WHOLE GRID.
   `run_cw` is now True for EVERY primary cell (2 predictors × 2 targets × 2 H = 8),
   so the actual BH/Bonferroni-surviving cell `dep_flight_13w·rv·H5` finally gets a
   real Clark-West (2007) nested test (HAC lag = that cell's own H, HLN-corrected,
   one-sided upper-tail = augmented/larger model better). The verdict no longer
   extrapolates from other cells.

   NOTE ON WHAT CW CAN AND CANNOT SHOW: CW is one-sided for the augmented model being
   BETTER. A signal that HURTS the forecast (positive DM-t under our convention) will
   NOT reject CW — and that is the correct, expected outcome, not a rescue of the null.
   The evidence that the signal *hurts* comes from the two-sided DM/HLN with a POSITIVE
   t that survives Bonferroni; CW's job here is only to rule out the opposite (that the
   signal secretly helps once the nested-model estimation-noise bias is removed).

2. VERDICT LOGIC NOW USES SIGN + BONFERRONI.
   Convention: d = loss_aug - loss_base, so DM-t > 0  <=>  augmented (deposit) worse
   <=>  the deposit signal HURTS the forecast. A primary cell with DM-t > 0 whose
   Bonferroni-adjusted p < 0.05 is a *documented negative* (signal significantly hurts),
   NOT a benign null and NOT an "FDR-only artefact". Symmetrically, a cell with DM-t < 0
   whose CW test survives Bonferroni over the same m=8 family would be a
   *documented positive* (signal helps). Everything else is graded weak_fdr_only /
   safe_null.

3. GENUINE POINT-IN-TIME VINTAGE (not just first-release).
   We pull the FULL, PAGINATED ALFRED real-time revision history (output_type=1
   with a wide realtime window: every (date, realtime_start, realtime_end, value)
   tuple), and
   reconstruct the signal AS IT WAS ACTUALLY KNOWN at each weekly first-print release
   date R_w: at R_w the newest week enters at its first print while every prior week
   enters at whatever revision was public on R_w. The rolling growth/z transform is
   recomputed on that true vintage snapshot; the newest value is the signal for week w;
   the embargo uses R_w + 1 day. The old first-release-only signal (output_type=4) is
   RETAINED as an explicit *sensitivity* (honestly labelled), so the README can show
   current-vintage  ->  first-release-only  ->  true point-in-time.

Hard constraints preserved (all were PASS in K1679-rev)
-------------------------------------------------------
* seed = 42 everywhere.
* Forward-label embargo: at origin i, training rows j satisfy j + H < i.
* Per-horizon inference: every DM/HLN/CW uses its own H as the HAC truncation lag.
* Canonical QLIKE from volpred.stats.model_evaluation.qlike_pointwise (never
  hand-written); direction actual/pred - log(actual/pred) - 1.
* Pre-registered primary grid identical to K1679 (2 predictors × 2 targets × 2 H).
* Bonferroni + BH over the primary family m = 8; un-floored MSE sensitivity.

Reproduce:  uv run --extra dev python experiments/K1679-rev2/K1679-rev2.py
Requires:   FRED_API_KEY in .env.local, live yfinance access.
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# volpred canonical QLIKE (never hand-write the loss)
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402

# ────────────────────────── configuration ──────────────────────────

SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

OUT_DIR = Path(__file__).resolve().parent

FRED_SMALL = "DPSSCBW027SBOG"  # Deposits, Small Domestically Chartered Commercial Banks
FRED_LARGE = "DPSLCBW027SBOG"  # Deposits, Large Domestically Chartered Commercial Banks

# Current-vintage embargo (K1679-style heuristic, kept for the before/after run):
# H.8 publishes the prior-Wednesday balance sheet on the following Friday
# (as_of + ~8 calendar days). +10d gives a 2-day buffer.
PUBLICATION_LAG_DAYS = 10
# Point-in-time embargo: we KNOW the true ALFRED first-print release date, so a 1-day
# buffer is enough so the signal is used on a session that OPENS after the release.
PIT_BUFFER_DAYS = 1

FRED_START = "2004-01-01"  # lead-in for 13w diff + 52w trailing z-score
PRICE_START = "2006-06-01"  # KRE inception 2006-06-23; lead-in for HAR(22)
ANALYSIS_START = "2007-01-02"

# True-PIT reconstruction needs enough archived weeks BEFORE the target week to
# compute a 52-week rolling z on a 13-week diff (>=65 weekly points). 800 calendar
# days (~114 weeks) is a comfortable margin.
PIT_VINTAGE_LOOKBACK_DAYS = 800
FRED_PAGE_LIMIT = 100_000
# H.8 observations are normally released about 8--10 calendar days after the
# observation Wednesday.  ALFRED backfilled pre-archive observations on
# 2012-08-17; those rows must not be mistaken for genuine first releases.
MAX_PIT_RELEASE_LAG_DAYS = 30
MIN_PIT_SIGNAL_OBS = 100
MIN_PIT_SIGNAL_UNIQUE = 20
MIN_PIT_SIGNAL_STD = 1e-6
MAX_PIT_SIGNAL_AGE_DAYS = 45

TRAIN_FRAC = 0.60
BOOT_REPS = 2000

# Pre-registered PRIMARY family (identical to K1679): 2 predictors × 2 targets × 2 H.
PRIMARY_GRID = [
    {"asset": "KRE", "predictor": p, "target": t, "H": h}
    for p in ("dep_flight_13w", "dep_flight_4w")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

# Declared SECONDARY family (falsification / placebo), NOT in the FDR family.
SECONDARY_GRID = [
    {"asset": a, "predictor": "dep_flight_13w", "target": t, "H": h}
    for a in ("XLF", "SPY")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

PRIMARY_LOSS = {"rv": "qlike", "dsv": "mse"}
PARK_C = 1.0 / (4.0 * np.log(2.0))


# ────────────────────────── data plumbing ──────────────────────────


def get_fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    for cand in (_REPO / ".env.local", Path.home() / "volpred-research" / ".env.local"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                if line.strip().startswith("FRED_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("FRED_API_KEY not found (env or .env.local)")


def fetch_fred_current(series_id: str, api_key: str) -> pd.Series:
    """Current (latest-revision) vintage — the K1679 behaviour, kept for before/after."""
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": FRED_START,
        },
        timeout=60,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    idx = pd.to_datetime([o["date"] for o in obs])
    val = pd.to_numeric([o["value"] for o in obs], errors="coerce")
    return pd.Series(val, index=idx, name=series_id).dropna()


def fetch_fred_first_release(series_id: str, api_key: str) -> pd.DataFrame:
    """
    ALFRED INITIAL-RELEASE-ONLY series (output_type=4): each observation date's value
    AS FIRST PUBLISHED, plus the true release date (realtime_start). Retained here as a
    SENSITIVITY only. It is *not* a true vintage: it never uses the (revised) values of
    older weeks that were actually visible at the trading date, so it carries extra
    measurement error and, if anything, biases toward the null. Returns
    DataFrame[date, release_date, value].
    """
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": FRED_START,
            "output_type": 4,  # initial release only
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        },
        timeout=120,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    rows = []
    for o in obs:
        v = pd.to_numeric(o["value"], errors="coerce")
        if pd.isna(v):
            continue
        rows.append(
            {
                "date": pd.Timestamp(o["date"]),
                "release_date": pd.Timestamp(o["realtime_start"]),
                "value": float(v),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fetch_fred_vintage_history(
    series_id: str, api_key: str
) -> tuple[pd.DataFrame, dict]:
    """
    FULL ALFRED real-time revision history (output_type=1 with a wide realtime window).
    Returns one row per (observation date, revision) with the window during which that
    value was the CURRENT public value:

        DataFrame[date, realtime_start, realtime_end, value]

    This is the raw material for a genuine point-in-time vintage snapshot: to know the
    value of observation `date` as seen on any calendar day R, take the row whose
    [realtime_start, realtime_end] window contains R.  The wide response is paginated
    because the history is much larger than the endpoint's per-request row cap.
    """
    # A wide output_type=1 request contains hundreds of thousands of
    # observation-vintage rows.  The endpoint caps each response at 100,000;
    # silently reading only page 1 was the orphan-run bug that produced a
    # constant pseudo-PIT signal.  Paginate to the API-reported count and fail
    # closed if any page is missing.
    url = "https://api.stlouisfed.org/fred/series/observations"
    base_params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": FRED_START,
        "output_type": 1,  # observations by real-time period (all vintages)
        "realtime_start": "1776-07-04",
        "realtime_end": "9999-12-31",
        "limit": FRED_PAGE_LIMIT,
        "sort_order": "asc",
    }
    obs: list[dict] = []
    expected_count: int | None = None
    offset = 0
    n_pages = 0
    while expected_count is None or offset < expected_count:
        r = requests.get(
            url,
            params={**base_params, "offset": offset},
            timeout=180,
        )
        r.raise_for_status()
        payload = r.json()
        page = payload.get("observations", [])
        if expected_count is None:
            expected_count = int(payload["count"])
        if not page:
            raise RuntimeError(
                f"ALFRED pagination stopped early for {series_id}: "
                f"received={offset}, expected={expected_count}"
            )
        obs.extend(page)
        offset += len(page)
        n_pages += 1

    assert expected_count is not None
    if len(obs) != expected_count:
        raise RuntimeError(
            f"ALFRED row-count mismatch for {series_id}: "
            f"received={len(obs)}, expected={expected_count}"
        )

    rows = []
    n_open_ended = 0
    for o in obs:
        v = pd.to_numeric(o["value"], errors="coerce")
        if pd.isna(v):
            continue
        is_open_ended = o["realtime_end"] == "9999-12-31"
        n_open_ended += int(is_open_ended)
        rows.append(
            {
                "date": pd.Timestamp(o["date"]),
                "realtime_start": pd.Timestamp(o["realtime_start"]),
                # 9999-12-31 is the ALFRED open-ended sentinel and is outside
                # datetime64[ns].  NaT below means "still current".
                "realtime_end": (
                    pd.NaT
                    if is_open_ended
                    else pd.Timestamp(o["realtime_end"])
                ),
                "value": float(v),
            }
        )
    out = (
        pd.DataFrame(rows)
        .sort_values(["date", "realtime_start"])
        .reset_index(drop=True)
    )
    if int(out["realtime_end"].isna().sum()) != n_open_ended:
        raise RuntimeError(
            f"ALFRED open-ended sentinel parse failed for {series_id}: "
            f"expected_NaT={n_open_ended}, got={int(out['realtime_end'].isna().sum())}"
        )
    audit = {
        "series_id": series_id,
        "api_output_type": 1,
        "api_reported_count": expected_count,
        "raw_rows_received": len(obs),
        "numeric_rows_retained": len(out),
        "page_limit": FRED_PAGE_LIMIT,
        "pages_fetched": n_pages,
        "pagination_complete": len(obs) == expected_count,
        "observation_date_min": str(out["date"].min().date()),
        "observation_date_max": str(out["date"].max().date()),
        "n_observation_dates": int(out["date"].nunique()),
        "n_realtime_starts": int(out["realtime_start"].nunique()),
        "n_open_ended_realtime_windows": n_open_ended,
    }
    return out, audit


def fetch_prices(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker, start=PRICE_START, auto_adjust=True, progress=False, threads=False
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def parkinson_variance(df: pd.DataFrame) -> pd.Series:
    hl = np.log(df["High"].astype(float) / df["Low"].astype(float))
    return (PARK_C * hl**2).rename("pk")


# ────────────────────────── signal construction ──────────────────────────


def _transform_signal(small: pd.Series, large: pd.Series) -> pd.DataFrame:
    """
    dep_flight_Nw = -z( log-growth(small, N) - log-growth(large, N) ), trailing 52w z.
    HIGH = deposits fleeing small banks toward large banks = stress. Returns a DataFrame
    indexed by observation date with dep_flight_4w / dep_flight_13w.
    """
    df = pd.concat([small.rename("small"), large.rename("large")], axis=1).dropna()
    out = {"small": df["small"], "large": df["large"]}
    for n in (4, 13):
        g_s = np.log(df["small"]).diff(n)
        g_l = np.log(df["large"]).diff(n)
        diff = g_s - g_l
        mu = diff.rolling(52, min_periods=52).mean()
        sd = diff.rolling(52, min_periods=52).std(ddof=1)
        out[f"dep_flight_{n}w"] = -((diff - mu) / sd)
    return pd.DataFrame(out)


def build_current_vintage_signal(small: pd.Series, large: pd.Series) -> pd.DataFrame:
    """K1679 behaviour: transform on the final-revision series; available_date =
    as_of + PUBLICATION_LAG_DAYS (heuristic)."""
    res = _transform_signal(small, large)
    res.index.name = "as_of"
    res["available_date"] = res.index + timedelta(days=PUBLICATION_LAG_DAYS)
    return res[["dep_flight_4w", "dep_flight_13w", "available_date"]]


def build_first_release_signal(small_fr: pd.DataFrame, large_fr: pd.DataFrame) -> pd.DataFrame:
    """
    SENSITIVITY signal: transform on first-print (initial-release-only) values. Every
    observation enters at its first print; the embargo uses the true release date.
    available_date = max(small_release, large_release) + PIT_BUFFER_DAYS.
    """
    small = small_fr.set_index("date")["value"].sort_index()
    large = large_fr.set_index("date")["value"].sort_index()
    small_rel = small_fr.set_index("date")["release_date"]
    large_rel = large_fr.set_index("date")["release_date"]

    tf = _transform_signal(small, large)  # indexed by observation date
    rel = pd.concat(
        [small_rel.rename("s"), large_rel.rename("l")], axis=1
    ).max(axis=1)  # both series must be public
    res = tf[["dep_flight_4w", "dep_flight_13w"]].copy()
    res["release_date"] = rel.reindex(res.index)
    res["available_date"] = res["release_date"] + timedelta(days=PIT_BUFFER_DAYS)
    res.index.name = "as_of"
    res = res.dropna(subset=["release_date"])
    return res[["dep_flight_4w", "dep_flight_13w", "release_date", "available_date"]]


def _revision_index(vh: pd.DataFrame) -> dict:
    """From a vintage-history frame build {obs_date: (rt_start_array_sorted, value_array)}
    plus a first-print map."""
    idx = {}
    first = {}
    for date, grp in vh.groupby("date"):
        g = grp.sort_values("realtime_start")
        rs = g["realtime_start"].to_numpy(dtype="datetime64[ns]")
        re = g["realtime_end"].to_numpy(dtype="datetime64[ns]")
        vv = g["value"].to_numpy(dtype=np.float64)
        idx[pd.Timestamp(date)] = (rs, re, vv)
        first[pd.Timestamp(date)] = pd.Timestamp(rs[0])
    return idx, first


def _value_as_of(idx: dict, date: pd.Timestamp, R: pd.Timestamp) -> float:
    """Value of observation `date` as it was public on calendar day R (last revision
    whose realtime_start <= R). NaN if `date` had not been published by R."""
    entry = idx.get(date)
    if entry is None:
        return float("nan")
    rs, re, vv = entry
    pos = int(np.searchsorted(rs, np.datetime64(R), side="right")) - 1
    if pos < 0:
        return float("nan")
    # realtime_end is inclusive.  NaT is our representation of ALFRED's
    # 9999-12-31 open-ended sentinel.
    if not np.isnat(re[pos]) and np.datetime64(R) > re[pos]:
        return float("nan")
    return float(vv[pos])


def build_true_pit_signal(
    small_vh: pd.DataFrame,
    large_vh: pd.DataFrame,
    small_fr: pd.DataFrame,
    large_fr: pd.DataFrame,
) -> pd.DataFrame:
    """
    GENUINE point-in-time signal.  output_type=4 supplies the official initial-release
    origin weeks and dates; output_type=1 supplies every revision needed for the
    snapshot. For each observation week w with first-print date
    R_w = max(small_release[w], large_release[w]) (both series public), reconstruct the
    deposit series AS IT WAS KNOWN ON R_w over a trailing window: the newest week enters
    at its first print, every prior week enters at whatever revision was current on R_w.
    Recompute the rolling growth/z transform on that true vintage snapshot and take the
    value at week w as the signal. available_date = R_w + PIT_BUFFER_DAYS.
    """
    small_idx, _ = _revision_index(small_vh)
    large_idx, _ = _revision_index(large_vh)
    common_history = sorted(set(small_idx) & set(large_idx))
    small_release = small_fr.set_index("date")["release_date"].to_dict()
    large_release = large_fr.set_index("date")["release_date"].to_dict()
    origin_weeks = sorted(
        set(common_history) & set(small_release) & set(large_release)
    )

    rows = []
    candidate_release_lags = []
    n_invalid_release_origins_excluded = 0
    for w in origin_weeks:
        R = max(pd.Timestamp(small_release[w]), pd.Timestamp(large_release[w]))
        release_lag = int((R - w).days)
        if release_lag < 0 or release_lag > MAX_PIT_RELEASE_LAG_DAYS:
            # Fail closed on any anomalous output_type=4 record rather than
            # silently treating an archive backfill as a live release origin.
            n_invalid_release_origins_excluded += 1
            continue
        candidate_release_lags.append(release_lag)
        lo = w - pd.Timedelta(days=PIT_VINTAGE_LOOKBACK_DAYS)
        window = [e for e in common_history if lo <= e <= w]
        if len(window) < 66:  # need >=65 weekly points for 52w z on 13w diff
            continue
        s_snap = pd.Series(
            {e: _value_as_of(small_idx, e, R) for e in window}
        ).dropna().sort_index()
        l_snap = pd.Series(
            {e: _value_as_of(large_idx, e, R) for e in window}
        ).dropna().sort_index()
        if len(s_snap) < 66 or len(l_snap) < 66:
            continue
        tf = _transform_signal(s_snap, l_snap)
        if w not in tf.index:
            continue
        r4 = tf.loc[w, "dep_flight_4w"]
        r13 = tf.loc[w, "dep_flight_13w"]
        if pd.isna(r4) and pd.isna(r13):
            continue
        rows.append(
            {
                "as_of": w,
                "dep_flight_4w": float(r4) if pd.notna(r4) else float("nan"),
                "dep_flight_13w": float(r13) if pd.notna(r13) else float("nan"),
                "release_date": R,
                "available_date": R + timedelta(days=PIT_BUFFER_DAYS),
            }
        )
    if not rows:
        raise RuntimeError("true-PIT reconstruction produced no release-valid weeks")
    res = pd.DataFrame(rows).set_index("as_of").sort_index()
    res.index.name = "as_of"
    res = res.dropna(subset=["dep_flight_4w", "dep_flight_13w"], how="all")
    signal_gate = {}
    for col in ("dep_flight_4w", "dep_flight_13w"):
        s = res[col].dropna()
        stats_gate = {
            "n": int(len(s)),
            "n_unique": int(s.nunique()),
            "std": float(s.std(ddof=1)),
        }
        stats_gate["passes"] = bool(
            stats_gate["n"] >= MIN_PIT_SIGNAL_OBS
            and stats_gate["n_unique"] >= MIN_PIT_SIGNAL_UNIQUE
            and stats_gate["std"] > MIN_PIT_SIGNAL_STD
        )
        signal_gate[col] = stats_gate
        if not stats_gate["passes"]:
            raise RuntimeError(f"degenerate true-PIT signal {col}: {stats_gate}")

    res.attrs["pit_build_audit"] = {
        "release_valid_weeks": len(candidate_release_lags),
        "history_only_weeks_not_in_output_type4": int(
            len(set(common_history) - set(origin_weeks))
        ),
        "invalid_output_type4_origins_excluded": n_invalid_release_origins_excluded,
        "release_lag_days_min": min(candidate_release_lags),
        "release_lag_days_max": max(candidate_release_lags),
        "max_allowed_release_lag_days": MAX_PIT_RELEASE_LAG_DAYS,
        "signal_non_degeneracy_gate": signal_gate,
        "signal_as_of_min": str(res.index.min().date()),
        "signal_as_of_max": str(res.index.max().date()),
    }
    out = res[["dep_flight_4w", "dep_flight_13w", "release_date", "available_date"]].copy()
    out.attrs = dict(res.attrs)
    return out


def merge_signal_to_trading_days(
    trading_index: pd.DatetimeIndex, sig: pd.DataFrame
) -> pd.DataFrame:
    """As-of backward merge: trading day t only ever sees a deposit observation whose
    available_date is <= t."""
    left = pd.DataFrame(
        {"date": pd.DatetimeIndex(trading_index).as_unit("ns")}
    ).sort_values("date")
    cols = ["available_date", "as_of_date", "dep_flight_13w", "dep_flight_4w"]
    right = sig.reset_index().rename(columns={"as_of": "as_of_date"})
    right = right[[c for c in cols if c in right.columns]].copy()
    right = right.dropna(subset=["dep_flight_13w", "dep_flight_4w"], how="all").copy()
    right["available_date"] = pd.to_datetime(right["available_date"]).astype("datetime64[ns]")
    right["as_of_date"] = pd.to_datetime(right["as_of_date"]).astype("datetime64[ns]")
    right = right.sort_values("available_date")
    m = pd.merge_asof(
        left, right, left_on="date", right_on="available_date", direction="backward"
    )
    return m.set_index("date")


# ────────────────────────── inference machinery ──────────────────────────


def nw_variance(d: np.ndarray, lag: int) -> float:
    """Newey-West (Bartlett) long-run variance of a mean-zero-centred series."""
    n = len(d)
    dm = d - d.mean()
    g0 = float(np.mean(dm**2))
    v = g0
    for k in range(1, lag + 1):
        gk = float(np.mean(dm[k:] * dm[:-k]))
        v += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    return v


def _hln_corr(n: int, h: int) -> float:
    return float(np.sqrt((n + 1.0 - 2.0 * h + h * (h - 1.0) / n) / n))


def dm_hln(d: np.ndarray, h: int) -> tuple[float, float, float, int]:
    """
    Diebold-Mariano, NW HAC (lag = h) + Harvey-Leybourne-Newbold (1997) correction,
    two-sided against t(n-1). d = loss_aug - loss_base. Negative t => augmented better.
    """
    d = np.asarray(d, dtype=np.float64)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return (np.nan, np.nan, np.nan, n)
    v = nw_variance(d, lag=h)
    if v <= 0:
        return (np.nan, np.nan, np.nan, n)
    se = np.sqrt(v / n)
    t_raw = float(d.mean() / se)
    t_hln = float(t_raw * _hln_corr(n, h))
    p = float(2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1)))
    return (t_raw, t_hln, p, n)


def clark_west(y: np.ndarray, pred_base: np.ndarray, pred_aug: np.ndarray, h: int) -> dict:
    """
    Clark-West (2007) nested-forecast adjusted MSPE test.

        f_t = (y - pred_base)^2 - [ (y - pred_aug)^2 - (pred_base - pred_aug)^2 ]

    Reject H0 (equal MSPE) in favour of the LARGER (augmented) model when mean(f_t) is
    significantly POSITIVE. One-sided upper-tail, HAC truncation lag = h + HLN small-
    sample correction, against t(n-1). Correct test for nested HAR vs HAR+signal; the
    standard DM/HLN is biased toward NOT rejecting for nested models. NB: CW only detects
    the augmented model being BETTER; a signal that hurts (negative CW-t) simply does not
    reject, which is the expected outcome and NOT evidence the signal is neutral.
    """
    y = np.asarray(y, np.float64)
    pb = np.asarray(pred_base, np.float64)
    pa = np.asarray(pred_aug, np.float64)
    f = (y - pb) ** 2 - ((y - pa) ** 2 - (pb - pa) ** 2)
    f = f[np.isfinite(f)]
    n = len(f)
    if n < 30:
        return {"status": "too_short", "n": n}
    v = nw_variance(f, lag=h)
    if v <= 0:
        return {"status": "nonpositive_lrv", "n": n, "fbar": float(f.mean())}
    se = np.sqrt(v / n)
    cw_raw = float(f.mean() / se)
    cw_hln = float(cw_raw * _hln_corr(n, h))
    p_one_raw = float(1.0 - stats.t.cdf(cw_raw, df=n - 1))
    p_one_hln = float(1.0 - stats.t.cdf(cw_hln, df=n - 1))
    return {
        "test": "Clark-West (2007) nested MSPE, one-sided upper-tail",
        "hac_lag": int(h),
        "n": int(n),
        "mean_adjusted_diff_fbar": float(f.mean()),
        "CW_t_raw": cw_raw,
        "CW_t_hln": cw_hln,
        "CW_p_one_sided_raw": p_one_raw,
        "CW_p_one_sided_hln": p_one_hln,
        "reject_equal_mspe_at_05_hln": bool(p_one_hln < 0.05),
        "reject_equal_mspe_at_10_hln": bool(p_one_hln < 0.10),
        "direction": "positive_CW_t_means_augmented(deposit)_better",
    }


def moving_block_bootstrap(d: np.ndarray, block: int, reps: int) -> dict:
    d = np.asarray(d, dtype=np.float64)
    n = len(d)
    if n < block * 3:
        return {"status": "skipped_too_short"}
    n_blocks = int(np.ceil(n / block))
    starts = RNG.integers(0, n - block + 1, size=(reps, n_blocks))
    offs = np.arange(block)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(reps, -1)[:, :n]
    means = d[idx].mean(axis=1)
    obs = float(d.mean())
    centered = means - means.mean()
    p = float(np.mean(np.abs(centered) >= abs(obs)))
    return {
        "block_len": int(block),
        "n_reps": int(reps),
        "mean_loss_diff": obs,
        "boot_se": float(means.std(ddof=1)),
        "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
        "p_two_sided_centered": p,
    }


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=np.float64)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(ranked, 1.0)
    return [float(x) for x in out]


# ────────────────────────── OOS engine ──────────────────────────


def har_terms(q: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "q_d": q,
            "q_w": q.rolling(5, min_periods=5).mean(),
            "q_m": q.rolling(22, min_periods=22).mean(),
        }
    )


def forward_mean(q: pd.Series, H: int) -> pd.Series:
    return q.rolling(H, min_periods=H).mean().shift(-H)


def run_oos(X: np.ndarray, y: np.ndarray, H: int, n_init: int) -> dict:
    """
    Expanding-window OOS with forward-label embargo j + H < i. Returns both the FLOORED
    forecasts (training-min positivity floor, K1679 behaviour) and the RAW (un-floored)
    forecasts, so an MSE-based sensitivity can compare them.
    """
    n, k = X.shape
    Xb = X[:, :-1]

    first_train_end = n_init - H - 1
    if first_train_end < max(k * 5, 60):
        raise RuntimeError("initial training window too small after embargo")

    pb_f, pa_f, pb_r, pa_r, ys = [], [], [], [], []
    n_floor_b = n_floor_a = 0
    embargo_check = {
        "first_origin": int(n_init),
        "first_train_last_row": int(first_train_end),
        "requirement": "j + H < i  =>  last train row j = i - H - 1",
        "holds_for_all_origins": True,
    }

    for i in range(n_init, n):
        j_end = i - H - 1
        if j_end + H >= i:
            embargo_check["holds_for_all_origins"] = False
        sl = slice(0, j_end + 1)
        ytr = y[sl]
        pos = ytr[ytr > 0]
        floor = float(pos.min()) if pos.size else 1e-10
        bb = np.linalg.lstsq(Xb[sl], y[sl], rcond=None)[0]
        ba = np.linalg.lstsq(X[sl], y[sl], rcond=None)[0]
        rb = float(Xb[i] @ bb)
        ra = float(X[i] @ ba)
        pb_r.append(rb)
        pa_r.append(ra)
        fb, fa = rb, ra
        if fb < floor:
            fb = floor
            n_floor_b += 1
        if fa < floor:
            fa = floor
            n_floor_a += 1
        pb_f.append(fb)
        pa_f.append(fa)
        ys.append(float(y[i]))

    if not embargo_check["holds_for_all_origins"]:
        raise AssertionError("forward-label embargo violated")

    return {
        "y": np.asarray(ys),
        "pred_base": np.asarray(pb_f),
        "pred_aug": np.asarray(pa_f),
        "pred_base_raw": np.asarray(pb_r),
        "pred_aug_raw": np.asarray(pa_r),
        "n_floored_base": n_floor_b,
        "n_floored_aug": n_floor_a,
        "embargo_check": embargo_check,
    }


# ────────────────────────── one grid cell ──────────────────────────


def evaluate_cell(
    panel: pd.DataFrame, asset: str, predictor: str, target: str, H: int,
    run_cw: bool = False,
) -> dict:
    q = panel[f"{'pk' if target == 'rv' else 'dsv'}_{asset}"]
    feats = har_terms(q)
    y = forward_mean(q, H)

    ctrl_cols = []
    if asset != "SPY":
        ctrl_cols.append("spy_rv21")
    if "vix" in panel.columns:
        ctrl_cols.append("vix")

    frame = pd.concat([feats, panel[ctrl_cols + [predictor]], y.rename("y")], axis=1)
    frame = frame.loc[frame.index >= pd.Timestamp(ANALYSIS_START)].dropna()

    # ---- mechanical lookahead assertions ----
    probe = frame.index[len(frame) // 2]
    pos = q.index.get_loc(probe)
    expect = float(q.iloc[pos + 1 : pos + 1 + H].mean())
    assert abs(float(frame.loc[probe, "y"]) - expect) < 1e-14, "target window is not (t, t+H]"
    asof = pd.to_datetime(panel.loc[frame.index, "as_of_date"].to_numpy())
    signal_ages = pd.DatetimeIndex(frame.index) - pd.DatetimeIndex(asof)
    min_gap = signal_ages.min()
    max_gap = signal_ages.max()

    scale = {"q_d": 1e4, "q_w": 1e4, "q_m": 1e4, "spy_rv21": 1e4, "vix": 1e-2}
    cols = ["q_d", "q_w", "q_m"] + ctrl_cols + [predictor]
    Xdf = frame[cols].copy()
    for c, s in scale.items():
        if c in Xdf.columns:
            Xdf[c] = Xdf[c] * s
    X = np.column_stack([np.ones(len(Xdf)), Xdf.to_numpy(dtype=np.float64)])
    yv = frame["y"].to_numpy(dtype=np.float64)

    n_init = int(TRAIN_FRAC * len(frame))
    oos = run_oos(X, yv, H=H, n_init=n_init)

    yt = oos["y"]
    pb, pa = oos["pred_base"], oos["pred_aug"]
    pb_r, pa_r = oos["pred_base_raw"], oos["pred_aug_raw"]
    n_floor_b = int(oos["n_floored_base"])
    n_floor_a = int(oos["n_floored_aug"])
    n_zero_actual = int((yt <= 0).sum())

    l_q_b, l_q_a = qlike_pointwise(yt, pb), qlike_pointwise(yt, pa)
    l_m_b, l_m_a = (yt - pb) ** 2, (yt - pa) ** 2
    l_m_b_raw, l_m_a_raw = (yt - pb_r) ** 2, (yt - pa_r) ** 2

    losses = {"qlike": (l_q_b, l_q_a), "mse": (l_m_b, l_m_a)}
    prim = PRIMARY_LOSS[target]

    res = {
        "asset": asset,
        "predictor": predictor,
        "target": target,
        "H": H,
        "hac_lag": H,
        "primary_loss": prim,
        "n_obs_modelling_rows": int(len(frame)),
        "n_oos": int(len(yt)),
        "sample_start": str(frame.index[0].date()),
        "sample_end": str(frame.index[-1].date()),
        "oos_start": str(frame.index[n_init].date()),
        "n_zero_actual": n_zero_actual,
        "n_floored_pred_base": n_floor_b,
        "n_floored_pred_aug": n_floor_a,
        "embargo_check": oos["embargo_check"],
        "min_days_between_deposit_asof_and_use": int(min_gap.days),
        "max_days_between_deposit_asof_and_use": int(max_gap.days),
        "loss_results": {},
    }

    for name, (lb, la) in losses.items():
        d = la - lb
        t_raw, t_hln, p, n = dm_hln(d, h=H)
        entry = {
            "loss_base": float(np.mean(lb)),
            "loss_aug": float(np.mean(la)),
            "improvement_pct": float(100.0 * (np.mean(lb) - np.mean(la)) / np.mean(lb)),
            "mean_loss_diff": float(np.mean(d)),
            "DM_t_raw": t_raw,
            "DM_t_hln": t_hln,
            "DM_p_value": p,
            "DM_n": n,
            "hac_lag": H,
            "direction": "negative_t_means_deposit_augmented_better",
        }
        if name == prim:
            entry["block_bootstrap"] = moving_block_bootstrap(
                d, block=max(10, H), reps=BOOT_REPS
            )
        res["loss_results"][name] = entry

    # ---- FIX 3(kept): un-floored MSE sensitivity ----
    d_raw = l_m_a_raw - l_m_b_raw
    t_raw_u, t_hln_u, p_u, n_u = dm_hln(d_raw, h=H)
    res["mse_unfloored_sensitivity"] = {
        "note": (
            "MSE recomputed on RAW (un-floored) OLS forecasts. MSE needs no positivity "
            "floor; this isolates whether the training-min floor (which clipped ~%d/%d "
            "base and %d/%d aug forecasts) was doing the work."
            % (n_floor_b, len(yt), n_floor_a, len(yt))
        ),
        "loss_base_unfloored": float(np.mean(l_m_b_raw)),
        "loss_aug_unfloored": float(np.mean(l_m_a_raw)),
        "improvement_pct_unfloored": float(
            100.0 * (np.mean(l_m_b_raw) - np.mean(l_m_a_raw)) / np.mean(l_m_b_raw)
        ),
        "mean_loss_diff_unfloored": float(np.mean(d_raw)),
        "DM_t_hln_unfloored": t_hln_u,
        "DM_p_value_unfloored": p_u,
        "DM_n": n_u,
        "vs_floored_mse_DM_t_hln": res["loss_results"]["mse"]["DM_t_hln"],
    }

    # ---- FIX 1: Clark-West nested test on EVERY primary cell (run_cw controls it) ----
    if run_cw:
        # CW is an MSPE (squared-error) test; run it on the RAW forecasts so no floor
        # distorts the adjustment term.
        res["clark_west"] = clark_west(yt, pb_r, pa_r, h=H)

    if target == "dsv" and n_zero_actual > 0:
        res["loss_results"]["qlike"]["caveat"] = (
            f"{n_zero_actual} OOS windows have exactly zero downside semivariance; "
            "QLIKE's log term is undefined there. MSE is the pre-declared primary loss for dsv."
        )

    p_primary = res["loss_results"][prim]["DM_p_value"]
    res["p_value"] = p_primary
    res["DM_t_hln"] = res["loss_results"][prim]["DM_t_hln"]
    return res


# ────────────────────────── grid runner ──────────────────────────


def run_grid(panel: pd.DataFrame, signal_label: str) -> list[dict]:
    cells = []
    for fam, grid in (("primary", PRIMARY_GRID), ("secondary", SECONDARY_GRID)):
        for g in grid:
            # FIX 1: Clark-West on EVERY primary cell (not just the two old 4w cells).
            run_cw = fam == "primary"
            c = evaluate_cell(panel, **g, run_cw=run_cw)
            c["family"] = fam
            c["signal_vintage"] = signal_label
            cells.append(c)
            cwtxt = ""
            if "clark_west" in c and "CW_t_hln" in c["clark_west"]:
                cwtxt = f"  CW_t={c['clark_west']['CW_t_hln']:+.2f}(p={c['clark_west']['CW_p_one_sided_hln']:.3f})"
            print(
                f"    [{signal_label:12s}][{fam:9s}] {c['asset']:3s} {c['predictor']:15s} "
                f"{c['target']:3s} H={c['H']:2d}  n={c['n_oos']:4d}  "
                f"DM_t(HLN)={c['DM_t_hln']:+.3f}  p={c['p_value']:.4f}{cwtxt}"
            )
    prim = [c for c in cells if c["family"] == "primary"]
    praw = [c["p_value"] for c in prim]
    m = len(praw)
    bh = benjamini_hochberg(praw)
    for c, q in zip(prim, bh):
        bonf = float(min(1.0, c["p_value"] * m))
        c["p_value_adjusted"] = {
            "family_size_m": m,
            "bonferroni": bonf,
            "benjamini_hochberg_q": q,
            "bh_reject_at_q10": bool(q < 0.10),
            "bonferroni_reject_at_05": bool(bonf < 0.05),
        }
    # CW is also evaluated over the same eight pre-registered nested-model
    # cells.  Because CW participates in the verdict, its one-sided p-values
    # need the same family-wise/FDR accounting rather than eight unadjusted
    # chances to trigger a "documented_positive" label.
    cw_raw_p = []
    for c in prim:
        p_cw = c.get("clark_west", {}).get("CW_p_one_sided_hln")
        cw_raw_p.append(float(p_cw) if p_cw is not None and np.isfinite(p_cw) else 1.0)
    cw_bh = benjamini_hochberg(cw_raw_p)
    for c, p_cw, q_cw in zip(prim, cw_raw_p, cw_bh):
        bonf_cw = float(min(1.0, p_cw * m))
        if "clark_west" in c:
            c["clark_west"]["p_value_adjusted"] = {
                "family_size_m": m,
                "bonferroni": bonf_cw,
                "benjamini_hochberg_q": q_cw,
                "bh_reject_at_q10": bool(q_cw < 0.10),
                "bonferroni_reject_at_05": bool(bonf_cw < 0.05),
            }
    for c in cells:
        if c["family"] == "secondary":
            c["p_value_adjusted"] = {"note": "declared secondary/falsification family"}
    return cells


def summarise(cells: list[dict]) -> dict:
    """
    FIX 2: verdict logic that uses SIGN + Bonferroni + CW.

    Convention d = loss_aug - loss_base:
        DM_t_hln > 0  <=>  deposit-augmented model WORSE  <=>  signal HURTS.
        DM_t_hln < 0  <=>  deposit-augmented model BETTER  <=>  signal HELPS.

    * A primary cell with DM_t_hln > 0 AND Bonferroni p < 0.05 is a DOCUMENTED NEGATIVE
      (signal significantly hurts), not an "FDR-only artefact".
    * A primary cell with DM_t_hln < 0 AND its Clark-West test survives Bonferroni
      at 0.05 over m=8 is a DOCUMENTED POSITIVE (signal helps once nested-bias is
      corrected).
    * Otherwise weak_fdr_only (some BH survivor but no sign/Bonferroni/CW support) or
      safe_null.
    """
    prim = [c for c in cells if c["family"] == "primary"]
    best = min(prim, key=lambda c: c["p_value"])  # smallest DM p (most extreme cell)

    def bonf(c):
        return c["p_value_adjusted"]["bonferroni"]

    def cw_reject_raw(c):
        cw = c.get("clark_west", {})
        return bool(cw.get("reject_equal_mspe_at_05_hln", False))

    def cw_reject_bonf(c):
        cw = c.get("clark_west", {})
        return bool(
            cw.get("p_value_adjusted", {}).get(
                "bonferroni_reject_at_05", False
            )
        )

    hurts_bonf = [c for c in prim if c["DM_t_hln"] > 0 and bonf(c) < 0.05]
    helps_cw = [c for c in prim if c["DM_t_hln"] < 0 and cw_reject_bonf(c)]

    any_raw = any(c["p_value"] < 0.05 for c in prim)
    any_bh = any(c["p_value_adjusted"]["bh_reject_at_q10"] for c in prim)
    any_harvey = any(abs(c["DM_t_hln"]) > 3.0 for c in prim)
    any_cw_reject_raw = any(cw_reject_raw(c) for c in prim)
    any_cw_reject_bonf = any(cw_reject_bonf(c) for c in prim)

    if helps_cw and hurts_bonf:
        verdict = "mixed_documented"
    elif helps_cw:
        verdict = "documented_positive"  # signal helps (CW rejects, aug better)
    elif hurts_bonf:
        verdict = "documented_negative"  # signal significantly HURTS (Bonferroni)
    elif any_bh:
        verdict = "weak_fdr_only"
    elif any_raw:
        verdict = "weak_raw_only"
    else:
        verdict = "safe_null"

    def cell_tag(c):
        return {
            "asset": c["asset"], "predictor": c["predictor"],
            "target": c["target"], "H": c["H"],
            "DM_t_hln": c["DM_t_hln"], "p_value": c["p_value"],
            "sign": "hurts" if c["DM_t_hln"] > 0 else "helps",
            "bonferroni": bonf(c),
            "bh_q": c["p_value_adjusted"]["benjamini_hochberg_q"],
            "clark_west_t_hln": c.get("clark_west", {}).get("CW_t_hln"),
            "clark_west_p_one_sided_hln": c.get("clark_west", {}).get("CW_p_one_sided_hln"),
            "clark_west_bonferroni": c.get("clark_west", {}).get(
                "p_value_adjusted", {}
            ).get("bonferroni"),
            "clark_west_reject_05_raw": cw_reject_raw(c),
            "clark_west_reject_05_bonferroni": cw_reject_bonf(c),
        }

    return {
        "verdict": verdict,
        "any_raw_p_below_05": any_raw,
        "any_bh_reject_at_q10": any_bh,
        "any_harvey_abs_t_above_3": any_harvey,
        "clark_west_any_raw_reject_at_05_hln": any_cw_reject_raw,
        "clark_west_any_bonferroni_reject_at_05_hln": any_cw_reject_bonf,
        "documented_negative_cells": [cell_tag(c) for c in hurts_bonf],
        "documented_positive_cells": [cell_tag(c) for c in helps_cw],
        "strongest_primary_cell": cell_tag(best),
        "all_primary_cells": [cell_tag(c) for c in prim],
    }


# ────────────────────────── figures ──────────────────────────


def make_figures(panels: dict, summaries: dict) -> None:
    panel_cur = panels["current"]
    panel_fr = panels["first_release"]
    panel_pit = panels["true_pit"]

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), height_ratios=[1.2, 1])
    ax = axes[0]
    sc = panel_cur["dep_flight_13w"].dropna()
    sf = panel_fr["dep_flight_13w"].dropna()
    sp = panel_pit["dep_flight_13w"].dropna()
    ax.plot(sc.index, sc.values, lw=0.8, color="#9e9e9e",
            label="current-vintage 13w (K1679, hindsight-revised)")
    ax.plot(sf.index, sf.values, lw=0.9, color="#f2a900", alpha=0.85,
            label="first-release-only 13w (output_type=4, sensitivity)")
    ax.plot(sp.index, sp.values, lw=1.1, color="#b3282d",
            label="true point-in-time 13w (ALFRED vintage snapshot)")
    ax.axhline(0, color="k", lw=0.6, alpha=0.5)
    ax.axhline(2, color="grey", ls=":", lw=0.9)
    for lo, hi in [("2008-09-01", "2009-06-30"), ("2023-03-01", "2023-06-30")]:
        ax.axvspan(pd.Timestamp(lo), pd.Timestamp(hi), color="#ffcc66", alpha=0.30)
    ax.set_ylabel("deposit-flight z (high = flight from small banks)")
    ax.set_title(
        "K1679-rev2 — current vs first-release vs TRUE point-in-time deposit-flight signal\n"
        "true PIT reconstructs the ALFRED vintage as known at each release; all spike at SVB",
        fontsize=11)
    ax.legend(loc="upper left", fontsize=8.0)
    ax2 = ax.twinx()
    fwd = forward_mean(panel_cur["pk_KRE"], 21)
    fwd = fwd.loc[fwd.index >= pd.Timestamp(ANALYSIS_START)]
    ax2.plot(fwd.index, np.sqrt(fwd.values * 252) * 100, lw=0.7, color="#1f4e79", alpha=0.5,
             label="KRE forward 21d RV (ann. %)")
    ax2.set_ylabel("KRE forward 21d realized vol (ann. %)", color="#1f4e79")
    ax2.legend(loc="upper right", fontsize=8.0)

    # bottom: primary-grid DM t across the three vintages
    ax = axes[1]
    order = PRIMARY_GRID
    labels = [f"{g['predictor'].replace('dep_flight_','')}·{g['target']}·H{g['H']}" for g in order]

    def dm_for(cells):
        d = {}
        for c in cells:
            if c["family"] == "primary":
                d[(c["predictor"], c["target"], c["H"])] = c["DM_t_hln"]
        return [d[(g["predictor"], g["target"], g["H"])] for g in order]

    x = np.arange(len(order))
    ax.bar(x - 0.27, dm_for(summaries["cells_current"]), width=0.27, color="#9e9e9e", label="current")
    ax.bar(x + 0.00, dm_for(summaries["cells_first_release"]), width=0.27, color="#f2a900", label="first-release")
    ax.bar(x + 0.27, dm_for(summaries["cells_true_pit"]), width=0.27, color="#b3282d", label="true PIT")
    for lv, ls in [(1.96, ":"), (3.0, "--")]:
        ax.axhline(lv, color="k", ls=ls, lw=0.8)
        ax.axhline(-lv, color="k", ls=ls, lw=0.8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8.0)
    ax.set_ylabel("DM t (Harvey-corrected)\n>0 = deposit signal HURTS")
    ax.set_title(
        "Primary-grid DM t by vintage — positive = signal hurts; dashed = |t|=1.96/3.0",
        fontsize=10)
    ax.legend(fontsize=8.0)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "K1679-rev2_fig_pit_vs_current.png", dpi=130)
    plt.close(fig)


# ────────────────────────── panel assembly ──────────────────────────


def assemble_panel(sig: pd.DataFrame, px: dict, vix, vix_ok: bool) -> pd.DataFrame:
    cols = {}
    for a in ("KRE", "XLF", "SPY"):
        pk = parkinson_variance(px[a])
        r = np.log(px[a]["Close"].astype(float)).diff()
        cols[f"pk_{a}"] = pk
        cols[f"dsv_{a}"] = np.minimum(r, 0.0) ** 2
    panel = pd.DataFrame(cols).dropna(how="all")
    panel["spy_rv21"] = panel["pk_SPY"].rolling(21, min_periods=21).mean()
    if vix_ok:
        panel["vix"] = vix.reindex(panel.index)
    merged = merge_signal_to_trading_days(panel.index, sig)
    for c in ["dep_flight_13w", "dep_flight_4w", "as_of_date"]:
        panel[c] = merged[c]
    return panel


def _construct(panel):
    svb = panel.loc["2023-03-01":"2023-06-30", "dep_flight_13w"].dropna()
    gfc = panel.loc["2008-09-01":"2009-06-30", "dep_flight_13w"].dropna()
    full = panel["dep_flight_13w"].dropna()
    age_frame = panel.loc[full.index, ["as_of_date"]].dropna()
    ages = (
        pd.DatetimeIndex(age_frame.index)
        - pd.DatetimeIndex(pd.to_datetime(age_frame["as_of_date"].to_numpy()))
    ).days
    return {
        "svb_2023_max_signal": float(svb.max()) if len(svb) else None,
        "svb_2023_argmax_date": str(svb.idxmax().date()) if len(svb) else None,
        "gfc_max_signal": float(gfc.max()) if len(gfc) else None,
        "full_sample_mean": float(full.mean()),
        "full_sample_std": float(full.std()),
        "full_sample_n": int(len(full)),
        "full_sample_n_unique": int(full.nunique()),
        "signal_age_days_min": int(ages.min()) if len(ages) else None,
        "signal_age_days_median": float(np.median(ages)) if len(ages) else None,
        "signal_age_days_max": int(ages.max()) if len(ages) else None,
        "signal_first_date": str(panel["dep_flight_13w"].dropna().index.min().date())
        if panel["dep_flight_13w"].notna().any() else None,
    }


# ────────────────────────── main ──────────────────────────


def main() -> None:
    t0 = time.time()
    key = get_fred_api_key()

    print("[1/7] FRED H.8 current-vintage deposits …")
    small_cur = fetch_fred_current(FRED_SMALL, key)
    large_cur = fetch_fred_current(FRED_LARGE, key)
    sig_cur = build_current_vintage_signal(small_cur, large_cur)

    print("[2/7] ALFRED first-release (output_type=4) deposits …")
    small_fr = fetch_fred_first_release(FRED_SMALL, key)
    large_fr = fetch_fred_first_release(FRED_LARGE, key)
    sig_fr = build_first_release_signal(small_fr, large_fr)
    print(f"    first-release weeks={len(sig_fr)}  "
          f"first available={sig_fr['available_date'].min().date()}")

    print("[3/7] ALFRED full vintage history (output_type=1) — true PIT …")
    small_vh, small_vh_audit = fetch_fred_vintage_history(FRED_SMALL, key)
    large_vh, large_vh_audit = fetch_fred_vintage_history(FRED_LARGE, key)
    print(f"    vintage rows: small={len(small_vh)} (obs={small_vh['date'].nunique()})  "
          f"large={len(large_vh)} (obs={large_vh['date'].nunique()})")
    sig_pit = build_true_pit_signal(small_vh, large_vh, small_fr, large_fr)
    pit_build_audit = dict(sig_pit.attrs["pit_build_audit"])
    print(f"    true-PIT weeks={len(sig_pit)}  "
          f"first available={sig_pit['available_date'].min().date()}  "
          f"last={sig_pit['available_date'].max().date()}")

    print("[4/7] yfinance prices …")
    assets = ["KRE", "XLF", "SPY"]
    px = {a: fetch_prices(a) for a in assets}
    vix_ok = True
    try:
        vix = fetch_prices("^VIX")["Close"].astype(float)
    except Exception as e:  # noqa: BLE001
        vix_ok = False
        vix = None
        print(f"    ! ^VIX unavailable ({e})")

    print("[5/7] panel assembly (current + first-release + true PIT) …")
    panel_cur = assemble_panel(sig_cur, px, vix, vix_ok)
    panel_fr = assemble_panel(sig_fr, px, vix, vix_ok)
    panel_pit = assemble_panel(sig_pit, px, vix, vix_ok)

    construct = {
        "current": _construct(panel_cur),
        "first_release": _construct(panel_fr),
        "true_pit": _construct(panel_pit),
    }
    if (
        construct["true_pit"]["full_sample_std"] <= MIN_PIT_SIGNAL_STD
        or construct["true_pit"]["full_sample_n_unique"] < MIN_PIT_SIGNAL_UNIQUE
        or construct["true_pit"]["signal_age_days_min"] < 0
        or construct["true_pit"]["signal_age_days_max"] > MAX_PIT_SIGNAL_AGE_DAYS
    ):
        raise RuntimeError(
            "true-PIT trading-day panel failed non-degeneracy gate: "
            f"{construct['true_pit']}"
        )
    print(f"    construct SVB max: current={construct['current']['svb_2023_max_signal']:.2f}  "
          f"first_release={construct['first_release']['svb_2023_max_signal']:.2f}  "
          f"true_pit={construct['true_pit']['svb_2023_max_signal']:.2f}")

    def _corr(a, b):
        both = pd.concat([a["dep_flight_13w"].rename("a"),
                          b["dep_flight_13w"].rename("b")], axis=1).dropna()
        return float(both["a"].corr(both["b"])) if len(both) > 10 else None

    sig_corr = {
        "current_vs_first_release": _corr(panel_cur, panel_fr),
        "current_vs_true_pit": _corr(panel_cur, panel_pit),
        "first_release_vs_true_pit": _corr(panel_fr, panel_pit),
    }

    print("[6/7] OOS grids …")
    cells_cur = run_grid(panel_cur, "current")
    cells_fr = run_grid(panel_fr, "first_release")
    cells_pit = run_grid(panel_pit, "true_pit")

    summ_cur = summarise(cells_cur)
    summ_fr = summarise(cells_fr)
    summ_pit = summarise(cells_pit)

    print("[7/7] figure …")
    make_figures(
        {"current": panel_cur, "first_release": panel_fr, "true_pit": panel_pit},
        {"cells_current": cells_cur, "cells_first_release": cells_fr, "cells_true_pit": cells_pit},
    )

    results = {
        "experiment_id": "K1679-rev2",
        "title": (
            "Regional-bank deposit-flight, revision #3: Clark-West on the real hit + "
            "sign/Bonferroni verdict logic + genuine ALFRED point-in-time vintage"
        ),
        "revises": "K1679-rev (Codex FAIL) and K1679 (Codex FAIL)",
        "run_utc": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "primary_signal_for_verdict": "true_pit",
        "verdict": summ_pit["verdict"],
        "three_fixes": {
            "fix1_clark_west_on_real_hit": {
                "problem": (
                    "K1679-rev ran Clark-West only on the two old 4w cells and "
                    "extrapolated any_reject=False onto the BH/Bonferroni-surviving PIT "
                    "hit dep_flight_13w·rv·H5, which never got a CW test."
                ),
                "fix": (
                    "run_cw=True for EVERY primary cell (all 8); the real hit and the "
                    "whole grid now carry an actual Clark-West result. NB: CW is one-sided "
                    "for the augmented model being BETTER, so a hurting signal correctly "
                    "does not reject — that is not a rescue of the null."
                ),
                "clark_west_by_vintage": {
                    v: {
                        f"{c['predictor']}·{c['target']}·H{c['H']}": c.get("clark_west")
                        for c in cells if c["family"] == "primary" and "clark_west" in c
                    }
                    for v, cells in (("current", cells_cur),
                                     ("first_release", cells_fr),
                                     ("true_pit", cells_pit))
                },
            },
            "fix2_sign_bonferroni_verdict": {
                "problem": (
                    "K1679-rev verdict ignored sign and Bonferroni; it labelled a "
                    "Bonferroni-significant POSITIVE-t cell (signal hurts) as an "
                    "'FDR-only artefact'."
                ),
                "fix": (
                    "verdict uses sign (DM_t>0 => hurts) + Bonferroni (<0.05 => "
                    "significant) + CW: hurts+Bonferroni => documented_negative; "
                    "helps+CW Bonferroni-reject over m=8 => documented_positive; "
                    "else weak_fdr_only/safe_null."
                ),
                "convention": "d = loss_aug - loss_base; DM_t_hln>0 => deposit signal HURTS.",
            },
            "fix3_genuine_point_in_time": {
                "problem": (
                    "K1679-rev's 'PIT' used output_type=4 = Initial Release ONLY (first "
                    "print), which is not a vintage snapshot — it omits the revisions of "
                    "older weeks that were actually visible at the trading date."
                ),
                "fix": (
                    "Pull the full PAGINATED ALFRED real-time revision history "
                    "(output_type=1, wide realtime window) and reconstruct the signal as "
                    "known at each weekly "
                    "first-print release date: newest week at first print, prior weeks at "
                    "their revision current on that date. First-release-only retained as an "
                    "explicit, honestly-labelled sensitivity."
                ),
                "signal_correlations": sig_corr,
                "construct_validity": construct,
                "vintage_fetch_audit": {
                    "small": small_vh_audit,
                    "large": large_vh_audit,
                },
                "pit_build_audit": pit_build_audit,
                "note_true_pit_sample": (
                    "ALFRED real-time archiving for these H.8 series starts ~2012-08. "
                    "output_type=4 defines genuine release-origin weeks; older "
                    "output_type=1-only observations remain valid trailing history at "
                    "each 2012+ snapshot but never become forecast origins. Any anomalous "
                    "output_type=4 origin with a release lag over 30 days is excluded."
                ),
            },
        },
        "summary_current_vintage": summ_cur,
        "summary_first_release": summ_fr,
        "summary_true_pit": summ_pit,
        "data_sources": {
            "deposits_small": f"FRED/ALFRED {FRED_SMALL}",
            "deposits_large": f"FRED/ALFRED {FRED_LARGE}",
            "prices": "yfinance auto_adjust=True (KRE, XLF, SPY, ^VIX)",
            "vix_control_available": vix_ok,
        },
        "method": {
            "baseline": "OLS 1 + HAR(d,w,m) + SPY 21d RV + VIX level",
            "augmented": "baseline + deposit-flight signal (only difference)",
            "oos": f"expanding refit, initial train {TRAIN_FRAC:.0%}, embargo j+H<i",
            "dm": "NW HAC lag=H + HLN correction, two-sided t(n-1)",
            "clark_west": "CW(2007) one-sided nested MSPE, HAC lag=H + HLN, ALL 8 primary cells",
            "bootstrap": f"moving-block block=max(10,H) reps={BOOT_REPS} seed={SEED}",
            "multiple_testing": (
                "Bonferroni + BH over primary family m=8, separately for two-sided "
                "DM and one-sided Clark-West p-values"
            ),
            "verdict_rule": "sign + Bonferroni + Clark-West (see three_fixes.fix2)",
        },
        "cells_current_vintage": cells_cur,
        "cells_first_release": cells_fr,
        "cells_true_pit": cells_pit,
        "runtime_seconds": None,
    }
    results["runtime_seconds"] = round(time.time() - t0, 1)

    out = OUT_DIR / "K1679-rev2_results.json"
    tmp = OUT_DIR / "K1679-rev2_results.json.tmp"
    tmp.write_text(json.dumps(results, indent=2, default=str))
    json.loads(tmp.read_text())
    os.replace(tmp, out)

    print(f"\nVERDICT (primary = true_pit): {summ_pit['verdict']}")
    print(f"  true-PIT strongest cell: {summ_pit['strongest_primary_cell']}")
    print(f"  documented_negative cells (true_pit): {summ_pit['documented_negative_cells']}")
    print(f"  first-release verdict: {summ_fr['verdict']}  current verdict: {summ_cur['verdict']}")
    print(f"  signal corr: {sig_corr}")
    print(f"  wrote {out}  ({results['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
