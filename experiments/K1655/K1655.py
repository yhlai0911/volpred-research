#!/usr/bin/env python3
"""K1655 — Growth-at-Risk moved to markets: Equity/Vol-at-Risk multi-horizon quantile regression.

Motivation
----------
Adrian, Boyarchenko & Giannone (2019, AER) show that tighter financial conditions
(a National Financial Conditions Index, NFCI) shift the LOWER quantile of future GDP
growth much more than the median ("Vulnerable Growth" / Growth-at-Risk). This K asks
the cross-domain question: does the same conditioning structure hold for an EQUITY
market? i.e. do financial conditions predict the 5% left tail of S&P 500 price-index
forward returns
(Equity-at-Risk) and the 95% right tail of forward realized volatility (Vol-at-Risk),
above and beyond an unconditional benchmark, OUT OF SAMPLE?

Differentiation (avoids two saturated NULL arcs):
  - NOT "exogenous shock -> next-day RV event window" (k1602/k1604 arc).
  - NOT "new covariate -> HAR-mean OOS increment" (k1613/k1616-k1619 arc).
  The target here is a TAIL QUANTILE (not a conditional mean), conditioned on
  exogenous financial conditions, mirroring GaR.

Honest priors already in the knowledge base:
  - Macro/financial-condition variables (NFCI, BAA10Y) LAG VIX by 9-20 days and add
    no OOS value for VIX-regime prediction (prior NULL).
  - STLFSI4 (a sister financial-stress index) is confirmed NULL (K503/K828): VIX
    absorbs the stress signal.
  => Expectation: OOS gains over an unconditional quantile may be weak. A NULL result
     is a legitimate cross-domain contrast and is reported without directional priors
     being treated as evidence.

Method (Adrian et al. 2019 skeleton, moved to markets)
------------------------------------------------------
  - Weekly (W-FRI) frequency: S&P 500 price index (^GSPC) weekly close, NFCI
    (weekly, Fri-dated), and VIX (daily close). Weekly matches NFCI's cadence.
  - Target: forward cumulative log return r_{t->t+H}, H in {1, 4, 12} weeks (primary,
    Equity-at-Risk). Secondary: forward annualized realized vol (Vol-at-Risk).
  - Separate single-predictor quantile regressions Q_tau(target | NFCI_t) and
    Q_tau(target | VIX_t) for tau in {0.05, 0.25, 0.50, 0.75, 0.95}. The NFCI
    tau=0.05 return tail is primary; VIX is secondary and is not an encompassing test.

Lookahead protection (HIGHEST priority; violation = experiment failure)
----------------------------------------------------------------------
  (1) Feature availability = genuine ALFRED point-in-time reconstruction. The fully
      paginated output_type=1 revision history supplies closed real-time intervals. At
      forecast Friday F we select the latest NFCI observation whose interval satisfies
      realtime_start <= F <= realtime_end. No NFCI feature exists before ALFRED's first
      public vintage (2011-05-25), and there is no final-vintage fallback.
  (2) Forward-label train-tail embargo. For an expanding OOS forecast made at origin
      position i, a training row j is admissible ONLY if j + H < i (project canonical
      strict inequality; see .claude/rules/experiments.md). This guarantees the training
      target windows realize strictly before the forecast origin -> no future return
      leaks into the training tail.
  (3) Horizon-specific inference. Overlapping H-period targets induce serial dependence
      in loss differentials. The DM test uses Newey-West lag=max(H-1, repo-canonical
      data-driven bandwidth) and the Harvey-Leybourne-Newbold (1997) small-sample
      correction, with a SEPARATE horizon per target. In-sample quantile-slope SEs use a
      moving-block bootstrap (block length = H) rather than the iid QuantReg SE.

All random procedures use SEED=1655.

Outputs
-------
  experiments/K1655/K1655_results.json
  experiments/K1655/K1655_nfci_slope_across_quantiles.png
  experiments/K1655/K1655_gar_quantiles_vs_realized.png
  experiments/K1655/K1655_oos_pinball_by_horizon.png
  experiments/K1655/K1655_oos_forecasts.csv (pointwise forecasts/losses for audit)
  experiments/K1655/data/alfred_NFCI_vintage_history.csv.gz (pinned raw revisions)
  experiments/K1655/data/alfred_NFCI_pit_weekly.csv (derived Friday snapshots)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
import yfinance as yf
from scipy import stats
from statsmodels.regression.quantile_regression import QuantReg

# volpred canonical DM helper (used as a CROSS-CHECK; primary inference is the
# HLN-corrected horizon-aware DM implemented below, which the helper lacks).
try:
    from volpred.stats.model_evaluation import dm_test as volpred_dm_test
except Exception:  # pragma: no cover
    volpred_dm_test = None

SEED = 1655
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

START = "2000-01-01"
END = "2026-07-01"
ALFRED_OBSERVATION_START = "2011-01-01"
ALFRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
ALFRED_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"
ALFRED_REALTIME_START = "1776-07-04"
ALFRED_REALTIME_END = "9999-12-31"
ALFRED_PAGE_LIMIT = 100_000
ALFRED_MAX_ATTEMPTS = 4
MAX_NFCI_INFO_LAG_DAYS = 28
HORIZONS = [1, 4, 12]           # weeks
QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]
PRIMARY_TAU = 0.05              # left tail = Equity-at-Risk
VOL_TAU = 0.95                 # right tail = Vol-at-Risk
MIN_TRAIN = 250                # >= ~5 years of admissible weeks before first OOS
REFIT_EVERY = 4               # refit expanding model every 4 weeks; predict weekly
BOOT_B = 500                  # moving-block bootstrap reps for in-sample slope SE
DISPLAY_H = 4                 # horizon shown in the time-series chart
QUANTREG_MAX_ITER_STAGES = (5_000, 20_000)


def _empty_fit_diagnostics() -> dict:
    return {
        "fit_calls": 0,
        "iteration_limit_retry_events": 0,
        "unresolved_iteration_limit_failures": 0,
        "other_warning_count": 0,
        "warning_categories": {},
        "bootstrap_fit_exceptions": 0,
        "oos_fit_exceptions": 0,
        "exception_types": {},
    }


FIT_DIAGNOSTICS = _empty_fit_diagnostics()


def _record_exception(bucket: str, exc: Exception) -> None:
    FIT_DIAGNOSTICS[bucket] += 1
    name = type(exc).__name__
    FIT_DIAGNOSTICS["exception_types"][name] = (
        FIT_DIAGNOSTICS["exception_types"].get(name, 0) + 1
    )


# --------------------------------------------------------------------------- #
# Data fetch (cached to data/ for reproducibility)                            #
# --------------------------------------------------------------------------- #
def fetch_fred_current(series_id: str, timeout: int = 45) -> pd.DataFrame:
    """Current/latest-revision FRED series; never used as the NFCI primary signal."""
    cache = os.path.join(DATA_DIR, f"fred_{series_id}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["DATE"])
        return df
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={df.columns[0]: "DATE", df.columns[1]: "VALUE"})
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
    df = df.dropna(subset=["VALUE"]).sort_values("DATE").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_fred_api_key() -> str:
    """Load the FRED key without ever printing it or embedding it in an error."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        return key
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(HERE)), ".env.local"),
        os.path.expanduser("~/volpred-research/.env.local"),
    ]
    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        with open(candidate, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line.startswith("FRED_API_KEY="):
                    continue
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise RuntimeError(
        "FRED_API_KEY is required to build the ALFRED NFCI vintage cache; "
        "no final-vintage fallback is allowed"
    )


def _sanitized_json_request(url: str, params: dict, label: str) -> dict:
    """GET a FRED/ALFRED JSON endpoint with retries and secret-safe failures."""
    retryable_statuses = {429, 500, 502, 503, 504}
    last_kind = "unknown"
    for attempt in range(ALFRED_MAX_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=180)
        except requests.RequestException as exc:
            last_kind = type(exc).__name__
            if attempt + 1 < ALFRED_MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"ALFRED transport failure for {label} after "
                f"{ALFRED_MAX_ATTEMPTS} attempts ({last_kind}); request URL redacted"
            ) from None

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError(
                    f"ALFRED returned invalid JSON for {label}; request URL redacted"
                ) from None
            if not isinstance(payload, dict):
                raise RuntimeError(f"ALFRED returned a non-object payload for {label}")
            return payload

        last_kind = f"HTTP {response.status_code}"
        if response.status_code in retryable_statuses and attempt + 1 < ALFRED_MAX_ATTEMPTS:
            time.sleep(2 ** attempt)
            continue
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = {}
        code = error_payload.get("error_code", response.status_code)
        message = str(error_payload.get("error_message", "request failed"))[:240]
        secret = str(params.get("api_key", ""))
        if secret:
            message = message.replace(secret, "[REDACTED]")
        raise RuntimeError(
            f"ALFRED request failed for {label}: code={code}, message={message}; "
            "request URL redacted"
        ) from None
    raise RuntimeError(f"ALFRED request failed for {label}: {last_kind}")


def _validate_vintage_history(df: pd.DataFrame, label: str) -> pd.DataFrame:
    ordered_columns = ["date", "realtime_start", "realtime_end", "value"]
    missing = set(ordered_columns) - set(df.columns)
    if missing:
        raise ValueError(f"{label} missing ALFRED columns: {sorted(missing)}")
    out = df[ordered_columns].copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise")
    out["realtime_start"] = pd.to_datetime(out["realtime_start"], errors="raise")
    out["realtime_end"] = pd.to_datetime(out["realtime_end"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="raise")
    if out.empty or out["value"].isna().any():
        raise ValueError(f"{label} is empty or contains nonnumeric ALFRED values")
    if (out["realtime_end"].notna() & (out["realtime_end"] < out["realtime_start"])).any():
        raise ValueError(f"{label} contains reversed real-time intervals")
    if out.duplicated(["date", "realtime_start", "realtime_end"]).any():
        raise ValueError(f"{label} contains duplicate ALFRED revision intervals")
    return out.sort_values(["date", "realtime_start"]).reset_index(drop=True)


def fetch_alfred_vintage_history(
    series_id: str, *, force_refresh: bool = False
) -> tuple[pd.DataFrame, dict]:
    """Fetch fully paginated ALFRED output_type=1 real-time revision history.

    The cache is a compressed long table with one row per observation/revision
    interval.  Missing pages, mismatched counts, malformed open-ended sentinels,
    missing audit metadata, or network failure all raise.  There is deliberately no
    fallback to the latest-revision FRED snapshot.
    """
    cache = os.path.join(DATA_DIR, f"alfred_{series_id}_vintage_history.csv.gz")
    audit_path = os.path.join(DATA_DIR, f"alfred_{series_id}_vintage_audit.json")
    if os.path.exists(cache) and not force_refresh:
        if not os.path.exists(audit_path):
            raise RuntimeError(f"ALFRED cache exists without audit metadata: {audit_path}")
        cached = pd.read_csv(cache, compression="gzip")
        cached = _validate_vintage_history(cached, cache)
        with open(audit_path, "r", encoding="utf-8") as handle:
            audit = json.load(handle)
        expected_hash = audit.get("cache_sha256")
        actual_hash = sha256_file(cache)
        if expected_hash != actual_hash:
            raise RuntimeError(
                f"ALFRED cache hash mismatch for {series_id}: "
                f"expected={expected_hash}, actual={actual_hash}"
            )
        if not audit.get("pagination_complete"):
            raise RuntimeError(f"ALFRED cache audit is not pagination-complete: {audit_path}")
        audit = {**audit, "loaded_from_cache": True}
        return cached, audit

    api_key = get_fred_api_key()
    common = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    vintage_payload = _sanitized_json_request(
        ALFRED_VINTAGE_DATES_URL,
        {
            **common,
            "realtime_start": ALFRED_REALTIME_START,
            "realtime_end": ALFRED_REALTIME_END,
            "limit": 10_000,
            "sort_order": "asc",
        },
        f"{series_id} vintage-date audit",
    )
    vintage_dates = vintage_payload.get("vintage_dates")
    if not isinstance(vintage_dates, list) or not vintage_dates:
        raise RuntimeError(f"ALFRED returned no vintage dates for {series_id}")
    if int(vintage_payload.get("count", -1)) != len(vintage_dates):
        raise RuntimeError(
            f"ALFRED vintage-date count mismatch for {series_id}: "
            f"reported={vintage_payload.get('count')}, received={len(vintage_dates)}"
        )

    base_params = {
        **common,
        "observation_start": ALFRED_OBSERVATION_START,
        "output_type": 1,
        "realtime_start": ALFRED_REALTIME_START,
        "realtime_end": ALFRED_REALTIME_END,
        "limit": ALFRED_PAGE_LIMIT,
        "sort_order": "asc",
    }
    observations: list[dict] = []
    expected_count: int | None = None
    offset = 0
    pages = 0
    while expected_count is None or offset < expected_count:
        payload = _sanitized_json_request(
            ALFRED_API_URL,
            {**base_params, "offset": offset},
            f"{series_id} revision-history page offset={offset}",
        )
        page = payload.get("observations")
        if not isinstance(page, list) or not page:
            raise RuntimeError(
                f"ALFRED pagination stopped early for {series_id}: "
                f"received={offset}, expected={expected_count}"
            )
        if expected_count is None:
            expected_count = int(payload["count"])
        elif int(payload["count"]) != expected_count:
            raise RuntimeError(f"ALFRED count changed during pagination for {series_id}")
        observations.extend(page)
        offset += len(page)
        pages += 1
    if expected_count is None or len(observations) != expected_count:
        raise RuntimeError(
            f"ALFRED row-count mismatch for {series_id}: "
            f"reported={expected_count}, received={len(observations)}"
        )

    rows: list[dict] = []
    n_open_ended = 0
    for observation in observations:
        value = pd.to_numeric(observation.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        realtime_end_raw = observation.get("realtime_end")
        is_open_ended = realtime_end_raw == ALFRED_REALTIME_END
        n_open_ended += int(is_open_ended)
        rows.append(
            {
                "date": observation["date"],
                "realtime_start": observation["realtime_start"],
                "realtime_end": None if is_open_ended else realtime_end_raw,
                "value": float(value),
            }
        )
    history = _validate_vintage_history(pd.DataFrame(rows), f"ALFRED {series_id}")
    if int(history["realtime_end"].isna().sum()) != n_open_ended:
        raise RuntimeError(f"ALFRED open-ended sentinel parse failed for {series_id}")

    tmp_cache = cache + ".tmp"
    history.to_csv(
        tmp_cache,
        index=False,
        compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
        date_format="%Y-%m-%d",
    )
    reloaded = pd.read_csv(tmp_cache, compression="gzip")
    _validate_vintage_history(reloaded, tmp_cache)
    os.replace(tmp_cache, cache)
    cache_hash = sha256_file(cache)
    audit = {
        "series_id": series_id,
        "endpoint": ALFRED_API_URL,
        "api_output_type": 1,
        "observation_start": ALFRED_OBSERVATION_START,
        "realtime_query": [ALFRED_REALTIME_START, ALFRED_REALTIME_END],
        "api_reported_count": expected_count,
        "raw_rows_received": len(observations),
        "numeric_rows_retained": len(history),
        "page_limit": ALFRED_PAGE_LIMIT,
        "pages_fetched": pages,
        "pagination_complete": len(observations) == expected_count,
        "vintage_dates_reported": len(vintage_dates),
        "first_public_vintage": vintage_dates[0],
        "last_public_vintage": vintage_dates[-1],
        "observation_date_span": [
            str(history["date"].min().date()),
            str(history["date"].max().date()),
        ],
        "realtime_start_span": [
            str(history["realtime_start"].min().date()),
            str(history["realtime_start"].max().date()),
        ],
        "n_observation_dates": int(history["date"].nunique()),
        "n_realtime_starts": int(history["realtime_start"].nunique()),
        "n_open_ended_realtime_windows": n_open_ended,
        "cache_path": os.path.relpath(cache, HERE),
        "cache_sha256": cache_hash,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "loaded_from_cache": False,
    }
    atomic_write_json(audit, audit_path)
    return history, audit


def fetch_spy() -> pd.DataFrame:
    cache = os.path.join(DATA_DIR, "gspc_daily.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")
        return df
    g = yf.download("^GSPC", start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(g.columns, pd.MultiIndex):
        g.columns = g.columns.get_level_values(0)
    g = g[["Close"]].dropna()
    g.index.name = "Date"
    g.to_csv(cache)
    return g


def release_date(obs_dates: pd.Series, kind: str) -> pd.Series:
    """Point-in-time public-availability date for each observation.

    NFCI (weekly, Fri-dated): published the FOLLOWING Wednesday ~ +3 business days,
      so NFCI dated Friday W is NOT known at Friday W; earliest origin that may use it
      is the next Friday. This is the rigorous shift(1)-equivalent lag.
    VIX / market-quote daily series: the day's CLOSE is observed at that day's close,
      so it is legitimately known at a same-day forecast origin (RELEASE_DATE = obs).
    Other daily released series: available next business day (+1).
    """
    if kind == "nfci_weekly":
        return obs_dates + pd.tseries.offsets.BDay(3)
    if kind == "daily_close":
        return obs_dates  # market quote known at its own close
    return obs_dates + pd.tseries.offsets.BDay(1)


def point_in_time_weekly(fred_df: pd.DataFrame, kind: str, week_fridays: pd.DatetimeIndex) -> pd.Series:
    """Release-lag mapper for non-revised market series and diagnostics only.

    The primary NFCI feature must never pass through this function: it is reconstructed
    from ALFRED real-time revision intervals by ``build_nfci_pit_weekly``.
    """
    df = fred_df.copy()
    df["RELEASE_DATE"] = release_date(df["DATE"], kind)
    df = df.sort_values("RELEASE_DATE").reset_index(drop=True)
    rel = df["RELEASE_DATE"].values
    vals = df["VALUE"].values
    out = np.full(len(week_fridays), np.nan)
    # searchsorted: index of last release <= F
    idx = np.searchsorted(rel, week_fridays.values, side="right") - 1
    ok = idx >= 0
    out[ok] = vals[idx[ok]]
    return pd.Series(out, index=week_fridays)


def _revision_index(vintage_history: pd.DataFrame) -> tuple[dict, list[pd.Timestamp]]:
    """Build an observation-date revision index with explicit closed intervals."""
    index: dict[pd.Timestamp, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for observation_date, group in vintage_history.groupby("date", sort=True):
        ordered = group.sort_values("realtime_start")
        starts = ordered["realtime_start"].to_numpy(dtype="datetime64[ns]")
        ends = ordered["realtime_end"].to_numpy(dtype="datetime64[ns]")
        values = ordered["value"].to_numpy(dtype=np.float64)
        index[pd.Timestamp(observation_date)] = (starts, ends, values)
    dates = sorted(index)
    if not dates:
        raise RuntimeError("ALFRED revision index is empty")
    return index, dates


def _active_revision_as_of(
    revision_index: dict,
    observation_date: pd.Timestamp,
    origin: pd.Timestamp,
) -> tuple[float, pd.Timestamp, pd.Timestamp | pd.NaT] | None:
    """Return the unique revision active on origin (inclusive interval endpoints)."""
    entry = revision_index.get(pd.Timestamp(observation_date))
    if entry is None:
        return None
    starts, ends, values = entry
    origin64 = np.datetime64(pd.Timestamp(origin))
    active = (starts <= origin64) & (np.isnat(ends) | (origin64 <= ends))
    positions = np.flatnonzero(active)
    if len(positions) > 1:
        raise RuntimeError(
            f"Overlapping ALFRED revision intervals for observation={observation_date.date()} "
            f"at origin={pd.Timestamp(origin).date()}"
        )
    if len(positions) == 0:
        return None
    pos = int(positions[0])
    realtime_end = pd.NaT if np.isnat(ends[pos]) else pd.Timestamp(ends[pos])
    return float(values[pos]), pd.Timestamp(starts[pos]), realtime_end


def build_nfci_pit_weekly(
    vintage_history: pd.DataFrame,
    week_fridays: pd.DatetimeIndex,
    first_public_vintage: str,
    *,
    min_unique_values: int = 100,
    max_information_lag_days: int = MAX_NFCI_INFO_LAG_DAYS,
) -> tuple[pd.DataFrame, dict]:
    """Reconstruct the latest NFCI value actually public at each Friday origin.

    For every Friday F, select the greatest observation date d <= F that has exactly
    one ALFRED real-time interval satisfying realtime_start <= F <= realtime_end.
    Historical backcasts whose first vintage begins in 2011 therefore remain missing
    before publication rather than leaking into the 2000s sample.
    """
    history = _validate_vintage_history(vintage_history, "NFCI vintage history")
    revision_index, observation_dates = _revision_index(history)
    observation_array = np.array(observation_dates, dtype="datetime64[ns]")
    first_public = pd.Timestamp(first_public_vintage)
    rows: list[dict] = []
    pre_release_origins = 0
    post_release_missing: list[str] = []

    for raw_origin in pd.DatetimeIndex(week_fridays):
        origin = pd.Timestamp(raw_origin).tz_localize(None)
        if origin < first_public:
            pre_release_origins += 1
            rows.append(
                {
                    "origin": origin,
                    "nfci": np.nan,
                    "nfci_obs_date": pd.NaT,
                    "nfci_realtime_start": pd.NaT,
                    "nfci_realtime_end": pd.NaT,
                }
            )
            continue

        position = int(np.searchsorted(observation_array, np.datetime64(origin), side="right")) - 1
        selected = None
        selected_date = None
        while position >= 0:
            candidate_date = observation_dates[position]
            active = _active_revision_as_of(revision_index, candidate_date, origin)
            if active is not None:
                selected = active
                selected_date = candidate_date
                break
            position -= 1
        if selected is None or selected_date is None:
            post_release_missing.append(str(origin.date()))
            rows.append(
                {
                    "origin": origin,
                    "nfci": np.nan,
                    "nfci_obs_date": pd.NaT,
                    "nfci_realtime_start": pd.NaT,
                    "nfci_realtime_end": pd.NaT,
                }
            )
            continue
        value, realtime_start, realtime_end = selected
        rows.append(
            {
                "origin": origin,
                "nfci": value,
                "nfci_obs_date": selected_date,
                "nfci_realtime_start": realtime_start,
                "nfci_realtime_end": realtime_end,
            }
        )

    pit = pd.DataFrame(rows).set_index("origin").sort_index()
    valid = pit.dropna(subset=["nfci"]).copy()
    if post_release_missing:
        raise RuntimeError(
            "ALFRED NFCI has missing post-launch Friday snapshots; first gaps="
            + ",".join(post_release_missing[:5])
        )
    if valid.empty:
        raise RuntimeError("ALFRED NFCI PIT reconstruction produced no valid origins")

    end_ok = valid["nfci_realtime_end"].isna() | (
        valid.index <= pd.DatetimeIndex(valid["nfci_realtime_end"])
    )
    start_ok = pd.DatetimeIndex(valid["nfci_realtime_start"]) <= valid.index
    obs_ok = pd.DatetimeIndex(valid["nfci_obs_date"]) <= valid.index
    info_lag = (valid.index - pd.DatetimeIndex(valid["nfci_obs_date"])).days
    no_pre_release_value = bool(
        pit.loc[pit.index < first_public, "nfci"].isna().all()
    )
    gates = {
        "no_pre_release_scored": no_pre_release_value,
        "all_realtime_start_le_origin": bool(start_ok.all()),
        "all_origin_le_realtime_end_inclusive": bool(end_ok.all()),
        "all_observation_dates_le_origin": bool(obs_ok.all()),
        "pagination_input_non_degenerate": bool(
            valid["nfci"].nunique() >= min_unique_values
            and valid["nfci"].std(ddof=1) > 0
        ),
        "max_information_lag_within_gate": bool(
            info_lag.max() <= max_information_lag_days
        ),
    }
    if not all(gates.values()):
        raise RuntimeError(f"ALFRED NFCI PIT timing/non-degeneracy gate failed: {gates}")

    audit = {
        "method": "ALFRED output_type=1 revision interval active at each Friday origin",
        "requested_origins": int(len(pit)),
        "valid_origins": int(len(valid)),
        "pre_first_vintage_origins_excluded": int(pre_release_origins),
        "post_release_missing_origins": int(len(post_release_missing)),
        "first_public_vintage": str(first_public.date()),
        "first_valid_origin": str(valid.index.min().date()),
        "last_valid_origin": str(valid.index.max().date()),
        "selected_observation_span": [
            str(valid["nfci_obs_date"].min().date()),
            str(valid["nfci_obs_date"].max().date()),
        ],
        "information_lag_days": {
            "min": int(info_lag.min()),
            "median": float(np.median(info_lag)),
            "max": int(info_lag.max()),
            "hard_max": max_information_lag_days,
        },
        "n_unique_values": int(valid["nfci"].nunique()),
        "standard_deviation": float(valid["nfci"].std(ddof=1)),
        "timing_gates": gates,
    }
    return pit, audit


# --------------------------------------------------------------------------- #
# Quantile / DM machinery                                                     #
# --------------------------------------------------------------------------- #
def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    """Elementwise pinball (quantile) loss; lower is better."""
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1.0) * e)


def fit_quantreg(X: np.ndarray, y: np.ndarray, tau: float):
    """QuantReg with fail-closed staged retries for iteration-limit warnings."""
    Xc = np.column_stack([np.ones(len(X)), X])
    model = QuantReg(y, Xc)
    FIT_DIAGNOSTICS["fit_calls"] += 1
    for max_iter in QUANTREG_MAX_ITER_STAGES:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = model.fit(q=tau, max_iter=max_iter, p_tol=1e-6)
        categories = [warning.category.__name__ for warning in caught]
        limit_hit = "IterationLimitWarning" in categories
        for category in categories:
            if category == "IterationLimitWarning":
                continue
            FIT_DIAGNOSTICS["other_warning_count"] += 1
            FIT_DIAGNOSTICS["warning_categories"][category] = (
                FIT_DIAGNOSTICS["warning_categories"].get(category, 0) + 1
            )
        if not limit_hit:
            return result  # params[0]=intercept, params[1:]=slopes
        FIT_DIAGNOSTICS["iteration_limit_retry_events"] += 1
    FIT_DIAGNOSTICS["unresolved_iteration_limit_failures"] += 1
    raise RuntimeError(
        f"QuantReg did not converge after max_iter={QUANTREG_MAX_ITER_STAGES[-1]} "
        f"for n={len(y)}, tau={tau}"
    )


def _nw_lag(horizon: int, n: int) -> int:
    """Newey-West truncation lag for the DM loss differential.

    The textbook DM rule is lag = h-1, which covers only the MA(h-1) structure that
    overlapping forecast windows induce *under forecast optimality*. Here we compare a
    misspecified conditional quantile model against an unconditional benchmark, and the
    conditioning variable (NFCI / VIX) is highly persistent, so the loss differential
    carries serial correlation well beyond h-1 (measured acf(1) ~= 0.68). At h=1 the
    textbook rule degenerates to lag=0 -- i.e. no HAC correction at all -- which
    understates the variance and inflates |t|.

    Floor the lag at the repo-canonical bandwidth used by
    volpred.stats.model_evaluation.dm_test so the two never disagree by construction.
    """
    canonical = max(1, min(int(np.ceil(horizon ** (1 / 3) * n ** (1 / 3))), n // 4))
    return max(horizon - 1, canonical)


def hln_dm(loss_a: np.ndarray, loss_b: np.ndarray, horizon: int):
    """Diebold-Mariano on a loss differential with a HAC lag that is at least the
    repo-canonical bandwidth (see _nw_lag) and the Harvey-Leybourne-Newbold (1997)
    small-sample correction.

    d = loss_a - loss_b. Negative t => model A (conditional) has lower loss => better.
    Returns (t_hln, p_hln, nw_lag, n).
    """
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return (0.0, 1.0, max(0, horizon - 1), n)
    dbar = d.mean()
    lag = _nw_lag(horizon, n)
    gamma0 = np.mean((d - dbar) ** 2)
    var = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)  # Bartlett kernel
        gk = np.mean((d[k:] - dbar) * (d[:-k] - dbar))
        var += 2.0 * w * gk
    if var <= 0:
        return (0.0, 1.0, lag, n)
    dm = dbar / np.sqrt(var / n)
    h = horizon
    corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    t_hln = dm * corr
    p_hln = 2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1))
    return (float(t_hln), float(p_hln), lag, n)


def moving_block_bootstrap_slopes(X: np.ndarray, y: np.ndarray, tau: float,
                                  block: int, B: int, rng: np.random.Generator):
    """Moving-block bootstrap of the QuantReg coefficient vector.

    Block length = H preserves the MA(H-1) dependence induced by overlapping targets,
    so the resulting SE / CI are valid for the overlapping-forward-return design
    (the iid QuantReg SE is NOT).
    """
    n = len(y)
    block = max(1, block)
    n_blocks = int(np.ceil(n / block))
    starts_pool = np.arange(0, n - block + 1) if n > block else np.array([0])
    boots = []
    for _ in range(B):
        starts = rng.choice(starts_pool, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        try:
            res = fit_quantreg(X[idx], y[idx], tau)
            boots.append(res.params)
        except Exception as exc:
            _record_exception("bootstrap_fit_exceptions", exc)
            continue
    boots = np.array(boots)
    return boots  # shape (B_ok, 1+k)


# --------------------------------------------------------------------------- #
# Build the weekly panel                                                       #
# --------------------------------------------------------------------------- #
def build_panel(*, force_refresh_alfred: bool = False):
    spy = fetch_spy()
    close = spy["Close"].astype(float)
    daily_logret = np.log(close / close.shift(1))

    # weekly close on the last trading day of each W-FRI week (label = Friday)
    wclose = close.resample("W-FRI").last().dropna()
    # Do not label a still-open final weekly bin as if Friday had completed.
    wclose = wclose.loc[wclose.index <= close.index.max().normalize()]
    # weekly realized variance = sum of daily squared log returns within each week
    wrv = (daily_logret ** 2).resample("W-FRI").sum()
    wrv = wrv.reindex(wclose.index)

    fridays = wclose.index
    nfci_history, alfred_audit = fetch_alfred_vintage_history(
        "NFCI", force_refresh=force_refresh_alfred
    )
    nfci_pit_frame, pit_audit = build_nfci_pit_weekly(
        nfci_history,
        fridays,
        alfred_audit["first_public_vintage"],
    )
    vix = fetch_fred_current("VIXCLS")
    vix_pit = point_in_time_weekly(vix, "daily_close", fridays)

    # Same-origin current-vintage diagnostic isolates revision impact from the sample
    # truncation.  It is never fed into the primary model.
    nfci_current = fetch_fred_current("NFCI")
    nfci_final_proxy = point_in_time_weekly(nfci_current, "nfci_weekly", fridays)
    revision_comparison = pd.concat(
        [
            nfci_pit_frame["nfci"].rename("true_pit"),
            nfci_final_proxy.rename("final_vintage_release_lag_proxy"),
        ],
        axis=1,
    ).dropna()
    if len(revision_comparison) < 100:
        raise RuntimeError("Too few common origins for NFCI revision-impact diagnostic")
    revision_difference = (
        revision_comparison["true_pit"]
        - revision_comparison["final_vintage_release_lag_proxy"]
    )
    revision_impact = {
        "same_origin_n": int(len(revision_comparison)),
        "same_origin_span": [
            str(revision_comparison.index.min().date()),
            str(revision_comparison.index.max().date()),
        ],
        "correlation": float(revision_comparison.corr().iloc[0, 1]),
        "mean_pit_minus_final": float(revision_difference.mean()),
        "mean_absolute_difference": float(revision_difference.abs().mean()),
        "root_mean_squared_difference": float(np.sqrt(np.mean(revision_difference ** 2))),
        "max_absolute_difference": float(revision_difference.abs().max()),
        "note": (
            "True-PIT and final-vintage values compared on the identical 2011+ origins; "
            "this diagnostic does not mix revision effects with sample truncation."
        ),
    }

    pit_cache = os.path.join(DATA_DIR, "alfred_NFCI_pit_weekly.csv")
    pit_to_write = nfci_pit_frame.reset_index()
    tmp_pit = pit_cache + ".tmp"
    pit_to_write.to_csv(tmp_pit, index=False, date_format="%Y-%m-%d")
    pit_check = pd.read_csv(tmp_pit)
    expected_pit_columns = {
        "origin",
        "nfci",
        "nfci_obs_date",
        "nfci_realtime_start",
        "nfci_realtime_end",
    }
    if set(pit_check.columns) != expected_pit_columns or len(pit_check) != len(pit_to_write):
        raise RuntimeError("Derived NFCI PIT cache validation failed")
    os.replace(tmp_pit, pit_cache)
    pit_audit["derived_cache_path"] = os.path.relpath(pit_cache, HERE)
    pit_audit["derived_cache_sha256"] = sha256_file(pit_cache)

    panel = pd.DataFrame({
        "wclose": wclose,
        "wrv": wrv,
        "nfci": nfci_pit_frame["nfci"],
        "vix": vix_pit,
        "nfci_obs_date": nfci_pit_frame["nfci_obs_date"],
        "nfci_realtime_start": nfci_pit_frame["nfci_realtime_start"],
        "nfci_realtime_end": nfci_pit_frame["nfci_realtime_end"],
    }, index=fridays)
    panel = panel.dropna(subset=["wclose", "nfci", "vix"])
    first_public = pd.Timestamp(alfred_audit["first_public_vintage"])
    if (panel.index < first_public).any():
        raise RuntimeError("A pre-ALFRED-release origin survived into the K1655 panel")
    if panel["nfci"].nunique() < 100 or panel["nfci"].std(ddof=1) <= 0:
        raise RuntimeError("K1655 NFCI feature is degenerate after PIT alignment")
    provenance = {
        "alfred_revision_history": alfred_audit,
        "nfci_pit_alignment": pit_audit,
        "revision_impact_same_origins": revision_impact,
        "final_partial_week_excluded": bool(wclose.index.max() <= close.index.max().normalize()),
        "last_market_observation": str(close.index.max().date()),
        "last_complete_w_fri_label": str(wclose.index.max().date()),
    }
    return panel, nfci_pit_frame, vix, provenance


def forward_return(wclose: pd.Series, H: int) -> pd.Series:
    """r_{t->t+H} = log(P_{t+H}/P_t); NaN where t+H beyond sample (unrealized)."""
    return np.log(wclose.shift(-H) / wclose)


def forward_realized_vol(wrv: pd.Series, H: int) -> pd.Series:
    """Annualized realized vol over the forward H-week window (weeks t+1..t+H).

    rolling(H).sum() at t covers [t-H+1, t]; shift(-H) maps new[t] = old[t+H],
    i.e. fwd_var[t] = sum of weekly RV over weeks t+1..t+H (strictly forward).
    """
    fwd_var = wrv.rolling(H).sum().shift(-H)
    ann = np.sqrt(fwd_var * (52.0 / H))
    return ann


# --------------------------------------------------------------------------- #
# In-sample quantile regression + bootstrap                                    #
# --------------------------------------------------------------------------- #
def in_sample_analysis(panel: pd.DataFrame, target_col: str, cond_cols, taus, horizons, label):
    """Fit QuantReg on the full admissible sample for every (H, tau); bootstrap slopes.

    cond_cols = list of conditioning column names in `panel` (e.g. ["nfci"] or ["vix"]).
    slope_grid tracks the FIRST conditioning variable's slope across quantiles (chart).
    """
    lead = cond_cols[0]
    results = {}
    slope_grid = {}
    for H in horizons:
        if target_col == "fwd_ret":
            y_full = forward_return(panel["wclose"], H)
        else:
            y_full = forward_realized_vol(panel["wrv"], H)
        df = pd.DataFrame({"y": y_full, **{c: panel[c] for c in cond_cols}}).dropna()
        X = df[cond_cols].values
        y = df["y"].values
        n = len(y)
        slope_grid[H] = {}
        names = ["intercept"] + list(cond_cols)
        for tau in taus:
            res = fit_quantreg(X, y, tau)
            boots = moving_block_bootstrap_slopes(X, y, tau, block=H, B=BOOT_B, rng=RNG)
            if len(boots) != BOOT_B:
                raise RuntimeError(
                    f"Bootstrap fit count mismatch for {label}/H{H}/tau{tau}: "
                    f"requested={BOOT_B}, successful={len(boots)}"
                )
            cell = {
                "n_obs": int(n),
                "tau": tau,
                "horizon_weeks": H,
                "bootstrap_requested_reps": BOOT_B,
                "bootstrap_successful_reps": int(len(boots)),
            }
            for j, nm in enumerate(names):
                pt = float(res.params[j])
                if boots.size:
                    col = boots[:, j]
                    se = float(np.std(col, ddof=1))
                    lo, hi = np.percentile(col, [5, 95])
                    p = float(2 * stats.norm.cdf(-abs(pt) / se)) if se > 0 else 1.0
                else:
                    se, lo, hi, p = float("nan"), float("nan"), float("nan"), float("nan")
                cell[nm] = {
                    "coef": pt,
                    "boot_se": se,
                    "ci90": [float(lo), float(hi)],
                    "boot_p": p,
                    "iid_t_diagnostic": float(res.tvalues[j]),  # NOT for inference
                }
            results[f"H{H}_tau{tau}"] = cell
            slope_grid[H][tau] = {
                "coef": cell[lead]["coef"],
                "ci90": cell[lead]["ci90"],
                "boot_p": cell[lead]["boot_p"],
            }
    return results, slope_grid


# --------------------------------------------------------------------------- #
# Out-of-sample expanding-window pinball + HLN-DM                              #
# --------------------------------------------------------------------------- #
def oos_analysis(panel: pd.DataFrame, target_col: str, cond_cols, taus, horizons, label):
    """Expanding-window OOS quantile forecasting with the forward-label embargo.

    For origin position i, admissible training rows are {j : j + H < i} (strict).
    Conditional model = QuantReg on `cond_cols`; benchmark = unconditional empirical
    tau-quantile of the same admissible training targets. Pinball loss compared via
    HLN-corrected, horizon-specific DM.
    """
    out = {}
    cond_mat = panel[cond_cols].values          # (N, k) conditioning matrix
    X_all = cond_mat
    for H in horizons:
        if target_col == "fwd_ret":
            y_all = forward_return(panel["wclose"], H).values
        else:
            y_all = forward_realized_vol(panel["wrv"], H).values
        N = len(y_all)
        # per-tau accumulators of pointwise losses aligned by origin
        loss_cond = {tau: [] for tau in taus}
        loss_uncond = {tau: [] for tau in taus}
        origin_by_tau = {tau: [] for tau in taus}
        origins = []
        cond_q_series = {tau: [] for tau in taus}
        realized_series = []
        forecast_rows = []

        cached = {}  # tau -> fitted params, refreshed every REFIT_EVERY
        last_fit_i = -10**9
        for i in range(N):
            # admissible training rows: target realized strictly before origin i.
            # row j's target window ends at j+H; require j + H < i (embargo) =>
            # j <= i-H-1, i.e. j in [0, i-H-1] == np.arange(0, i-H).
            train_idx = np.arange(0, i - H)  # empty if i <= H
            if len(train_idx) < MIN_TRAIN:
                continue
            # target at origin i must be realized (i+H within sample) to score OOS
            if i + H >= N or not np.isfinite(y_all[i]):
                continue
            if not np.isfinite(cond_mat[i]).all():
                continue
            ytr = y_all[train_idx]
            Xtr = X_all[train_idx]
            good = np.isfinite(ytr) & np.isfinite(Xtr).all(axis=1)
            ytr, Xtr = ytr[good], Xtr[good]
            if len(ytr) < MIN_TRAIN:
                continue
            latest_training_target_end = panel.index[int(train_idx[-1]) + H]
            if not latest_training_target_end < panel.index[i]:
                raise RuntimeError(
                    f"Forward-label embargo failed at origin={panel.index[i]} H={H}"
                )

            refit = (i - last_fit_i) >= REFIT_EVERY or not cached
            if refit:
                cached = {}
                for tau in taus:
                    try:
                        res = fit_quantreg(Xtr, ytr, tau)
                        cached[tau] = res.params
                    except Exception as exc:
                        _record_exception("oos_fit_exceptions", exc)
                        cached[tau] = None
                cached["_uncond"] = {tau: float(np.quantile(ytr, tau)) for tau in taus}
                last_fit_i = i

            xi = np.concatenate([[1.0], cond_mat[i]])
            yi = y_all[i]
            for tau in taus:
                params = cached.get(tau)
                if params is None:
                    continue
                q_cond = float(xi @ params)
                q_unc = cached["_uncond"][tau]
                lc = float(pinball_loss(np.array([yi]), np.array([q_cond]), tau)[0])
                lu = float(pinball_loss(np.array([yi]), np.array([q_unc]), tau)[0])
                loss_cond[tau].append(lc)
                loss_uncond[tau].append(lu)
                origin_by_tau[tau].append(i)
                if tau == PRIMARY_TAU or tau == VOL_TAU:
                    cond_q_series[tau].append(q_cond)
                forecast_rows.append({
                    "target": target_col,
                    "spec": label,
                    "horizon_weeks": H,
                    "tau": tau,
                    "origin": str(panel.index[i].date()),
                    "target_end": str(panel.index[i + H].date()),
                    "latest_training_target_end": str(latest_training_target_end.date()),
                    "nfci_value": float(panel["nfci"].iloc[i]),
                    "nfci_obs_date": str(pd.Timestamp(panel["nfci_obs_date"].iloc[i]).date()),
                    "nfci_realtime_start": str(
                        pd.Timestamp(panel["nfci_realtime_start"].iloc[i]).date()
                    ),
                    "nfci_realtime_end": (
                        None
                        if pd.isna(panel["nfci_realtime_end"].iloc[i])
                        else str(pd.Timestamp(panel["nfci_realtime_end"].iloc[i]).date())
                    ),
                    "realized": float(yi),
                    "q_conditional": q_cond,
                    "q_unconditional": float(q_unc),
                    "loss_conditional": lc,
                    "loss_unconditional": lu,
                })
            origins.append(i)
            realized_series.append(yi)

        res_H = {"horizon_weeks": H, "n_oos": len(origins), "refit_every": REFIT_EVERY,
                 "min_train": MIN_TRAIN, "tau": {}}
        for tau in taus:
            la = np.array(loss_cond[tau], float)
            lb = np.array(loss_uncond[tau], float)
            if len(la) < 10:
                res_H["tau"][str(tau)] = {"n": len(la), "note": "insufficient OOS"}
                continue
            t_hln, p_hln, lag, n = hln_dm(la, lb, H)
            tau_origins = origin_by_tau[tau]
            if len(tau_origins) != n:
                raise RuntimeError(
                    f"Origin/loss count mismatch for {label}/{target_col}/H{H}/tau{tau}"
                )
            helper_t, helper_p = (None, None)
            if volpred_dm_test is not None:
                try:
                    helper_t, helper_p = volpred_dm_test(la, lb, h=H)
                    helper_t, helper_p = float(helper_t), float(helper_p)
                except Exception:
                    helper_t, helper_p = (None, None)
            res_H["tau"][str(tau)] = {
                "n": int(n),
                "pinball_cond": float(la.mean()),
                "pinball_uncond": float(lb.mean()),
                "pinball_reduction_pct": float((lb.mean() - la.mean()) / lb.mean() * 100.0),
                "dm_t_hln": t_hln,             # negative => conditional better
                "dm_p_hln": p_hln,
                "nw_lag": lag,
                "hln_applied": True,
                "helper_dm_t": helper_t,      # cross-check (volpred canonical, no HLN)
                "helper_dm_p": helper_p,
                "cond_better": bool(la.mean() < lb.mean()),
                "harvey_significant_better": bool(t_hln < -3.0),
                "harvey_absolute_threshold_crossed": bool(abs(t_hln) > 3.0),
                "oos_origin_start": str(panel.index[tau_origins[0]].date()),
                "oos_origin_end": str(panel.index[tau_origins[-1]].date()),
                "latest_scored_target_end": str(
                    panel.index[tau_origins[-1] + H].date()
                ),
                "embargo_audit": {
                    "rule": "training row j admissible iff j + H < origin i",
                    "all_latest_training_target_end_before_origin": True,
                },
            }
        res_H["_origins"] = origins
        res_H["_cond_q_series"] = {str(k): v for k, v in cond_q_series.items()}
        res_H["_realized_series"] = realized_series
        res_H["_forecast_rows"] = forecast_rows
        out[H] = res_H
    return out


# --------------------------------------------------------------------------- #
# Charts                                                                        #
# --------------------------------------------------------------------------- #
def chart_slope_across_quantiles(slope_grid, path, target_label):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = {1: "#1f77b4", 4: "#d62728", 12: "#2ca02c"}
    for H in sorted(slope_grid):
        taus = sorted(slope_grid[H])
        coefs = [slope_grid[H][t]["coef"] for t in taus]
        lo = [slope_grid[H][t]["ci90"][0] for t in taus]
        hi = [slope_grid[H][t]["ci90"][1] for t in taus]
        ax.plot(taus, coefs, "o-", color=colors.get(H, None), label=f"H={H}w")
        ax.fill_between(taus, lo, hi, color=colors.get(H, None), alpha=0.12)
    ax.axhline(0, color="k", lw=0.8, ls="--")
    ax.axvline(PRIMARY_TAU, color="grey", lw=0.8, ls=":")
    ax.set_xlabel("Quantile tau")
    ax.set_ylabel("NFCI slope on target")
    ax.set_title(f"K1655 Growth-at-Risk: NFCI slope across quantiles ({target_label})\n"
                 f"90% moving-block bootstrap CI (block=H, seed={SEED})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_gar_vs_realized(panel, oos_ret, H, path):
    resH = oos_ret[H]
    origins = resH["_origins"]
    idx = panel.index[origins]
    realized = np.array(resH["_realized_series"], float)
    q05 = np.array(resH["_cond_q_series"][str(PRIMARY_TAU)], float)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(idx, realized, color="#444", lw=0.7, alpha=0.7,
            label=f"Realized fwd {H}w return")
    ax.plot(idx, q05, color="#d62728", lw=1.4,
            label="Conditional 5% quantile (Equity-at-Risk)")
    breach = realized < q05
    ax.scatter(idx[breach], realized[breach], color="#d62728", s=14, zorder=5,
               label=f"Breach ({breach.sum()}/{len(realized)}={breach.mean()*100:.1f}%)")
    for a, b in [("2020-02-01", "2020-06-01")]:
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="grey", alpha=0.12)
    ax.axhline(0, color="k", lw=0.6, ls="--")
    ax.set_title(f"K1655 Equity-at-Risk: OOS conditional 5% quantile vs realized "
                 f"forward {H}-week S&P 500 return\n(shaded: 2020 COVID; "
                 f"target=5% => ~5% breaches if well-calibrated)")
    ax.set_ylabel("Forward log return")
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_pinball_by_horizon(oos_nfci, oos_vix, path):
    """Unconditional vs NFCI-conditional vs VIX-conditional OOS pinball at tau=0.05.
    DM p annotated for the PRIMARY (NFCI) spec."""
    Hs = sorted(oos_nfci)
    unc = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["pinball_uncond"] for H in Hs]
    cnf = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["pinball_cond"] for H in Hs]
    cvx = [oos_vix[H]["tau"][str(PRIMARY_TAU)]["pinball_cond"] for H in Hs]
    dmp = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["dm_p_hln"] for H in Hs]
    x = np.arange(len(Hs))
    w = 0.26
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w, unc, w, label="Unconditional (hist. quantile)", color="#9ecae1")
    ax.bar(x, cnf, w, label="NFCI-conditional", color="#d62728")
    ax.bar(x + w, cvx, w, label="VIX-conditional", color="#2ca02c")
    for xi, p in zip(x, dmp):
        top = max(unc[int(xi)], cnf[int(xi)], cvx[int(xi)])
        ax.text(xi, top * 1.01, f"NFCI DM p={p:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"H={H}w" for H in Hs])
    ax.set_ylabel("OOS mean pinball loss (tau=0.05)")
    ax.set_title("K1655 Equity-at-Risk OOS pinball loss by horizon\n"
                 "(lower=better; HLN-DM p vs unconditional; NW lag=max(H-1, canonical))")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Verdict                                                                       #
# --------------------------------------------------------------------------- #
def build_verdict(in_ret, oos_ret):
    """Verdict on the PRIMARY claim: NFCI conditions the 5% left tail of forward
    S&P 500 price-index returns, in-sample AND out-of-sample."""
    # primary in-sample: NFCI slope at tau=0.05 for each H, sign & significance
    primary_cells = {H: in_ret.get(f"H{H}_tau{PRIMARY_TAU}") for H in HORIZONS}
    in_sig = {H: (c["nfci"]["boot_p"] < 0.05 and c["nfci"]["coef"] < 0)
              for H, c in primary_cells.items() if c}
    oos_sig = {}
    oos_harvey = {}
    for H in HORIZONS:
        cell = oos_ret[H]["tau"].get(str(PRIMARY_TAU), {})
        oos_sig[H] = bool(
            cell.get("cond_better")
            and cell.get("dm_t_hln", 0.0) < 0.0
            and cell.get("dm_p_hln", 1.0) < 0.05
        )
        oos_harvey[H] = bool(cell.get("harvey_significant_better"))
    any_in = any(in_sig.values())
    any_oos = any(oos_sig.values())
    harvey_oos = any(oos_harvey.values())

    if harvey_oos:
        verdict = "PASS"
    elif any_in and any_oos:
        verdict = "CONDITIONAL_PASS"
    elif any_in and not any_oos:
        verdict = "NULL_OOS"  # in-sample tail dependence but no OOS predictive gain
    else:
        verdict = "NULL"
    return {
        "verdict": verdict,
        "in_sample_left_tail_significant_by_H": in_sig,
        "oos_left_tail_significant_by_H": oos_sig,
        "oos_left_tail_harvey_better_by_H": oos_harvey,
        "oos_harvey_significant_any_H": bool(harvey_oos),
    }


def atomic_write_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    with open(tmp) as f:
        json.load(f)  # validate parseable
    os.replace(tmp, path)


def atomic_write_csv(frame: pd.DataFrame, path: str) -> None:
    tmp = path + ".tmp"
    frame.to_csv(tmp, index=False)
    check = pd.read_csv(tmp)
    if len(check) != len(frame) or list(check.columns) != list(frame.columns):
        raise RuntimeError(f"CSV round-trip validation failed: {path}")
    os.replace(tmp, path)


def verify_forecast_artifact(
    forecast_frame: pd.DataFrame,
    equity_results: dict,
    volatility_results: dict,
) -> dict:
    """Recompute every serialized OOS cell from pointwise forecast/loss rows."""
    required = {
        "target", "spec", "horizon_weeks", "tau", "origin", "target_end",
        "latest_training_target_end", "nfci_value", "nfci_obs_date",
        "nfci_realtime_start", "nfci_realtime_end", "realized",
        "q_conditional", "q_unconditional", "loss_conditional",
        "loss_unconditional",
    }
    missing = required - set(forecast_frame.columns)
    if missing:
        raise KeyError(f"Forecast artifact missing columns: {sorted(missing)}")
    if forecast_frame.empty:
        raise RuntimeError("Forecast artifact is empty")

    origins = pd.to_datetime(forecast_frame["origin"])
    target_ends = pd.to_datetime(forecast_frame["target_end"])
    train_ends = pd.to_datetime(forecast_frame["latest_training_target_end"])
    obs_dates = pd.to_datetime(forecast_frame["nfci_obs_date"])
    rt_starts = pd.to_datetime(forecast_frame["nfci_realtime_start"])
    rt_ends = pd.to_datetime(forecast_frame["nfci_realtime_end"], errors="coerce")
    timing_gates = {
        "all_targets_after_origin": bool((target_ends > origins).all()),
        "all_training_targets_before_origin": bool((train_ends < origins).all()),
        "all_nfci_observations_not_after_origin": bool((obs_dates <= origins).all()),
        "all_nfci_revisions_started_by_origin": bool((rt_starts <= origins).all()),
        "all_nfci_revision_windows_cover_origin": bool(
            (rt_ends.isna() | (origins <= rt_ends)).all()
        ),
    }
    if not all(timing_gates.values()):
        raise RuntimeError(f"Forecast artifact timing gate failed: {timing_gates}")

    containers = {
        "fwd_ret": equity_results,
        "fwd_vol": volatility_results,
    }
    max_mean_loss_error = 0.0
    max_reduction_error = 0.0
    max_dm_t_error = 0.0
    checked = 0
    grouped = forecast_frame.groupby(
        ["target", "spec", "horizon_weeks", "tau"], sort=True
    )
    for (target, spec, horizon, tau), group in grouped:
        model_block = containers[str(target)][str(spec)]["oos"]
        cell = model_block[int(horizon)]["tau"][str(float(tau))]
        conditional_loss = group["loss_conditional"].to_numpy(float)
        unconditional_loss = group["loss_unconditional"].to_numpy(float)
        if len(group) != int(cell["n"]):
            raise RuntimeError(
                f"Forecast artifact n mismatch for {target}/{spec}/H{horizon}/tau{tau}"
            )
        cond_mean = float(conditional_loss.mean())
        unc_mean = float(unconditional_loss.mean())
        reduction = float((unc_mean - cond_mean) / unc_mean * 100.0)
        dm_t, dm_p, lag, n = hln_dm(conditional_loss, unconditional_loss, int(horizon))
        max_mean_loss_error = max(
            max_mean_loss_error,
            abs(cond_mean - float(cell["pinball_cond"])),
            abs(unc_mean - float(cell["pinball_uncond"])),
        )
        max_reduction_error = max(
            max_reduction_error,
            abs(reduction - float(cell["pinball_reduction_pct"])),
        )
        max_dm_t_error = max(max_dm_t_error, abs(dm_t - float(cell["dm_t_hln"])))
        if not (
            n == int(cell["n"])
            and lag == int(cell["nw_lag"])
            and math_isclose(dm_p, float(cell["dm_p_hln"]), 1e-11)
            and bool(dm_t < -3.0) == bool(cell["harvey_significant_better"])
        ):
            raise RuntimeError(
                f"Forecast artifact DM mismatch for {target}/{spec}/H{horizon}/tau{tau}"
            )
        checked += 1
    if checked != 60:
        raise RuntimeError(f"Expected 60 OOS forecast cells, verified {checked}")
    if max(max_mean_loss_error, max_reduction_error, max_dm_t_error) > 1e-9:
        raise RuntimeError(
            "Forecast artifact numeric round-trip exceeded tolerance: "
            f"loss={max_mean_loss_error}, reduction={max_reduction_error}, dm={max_dm_t_error}"
        )
    return {
        "cells_verified": checked,
        "timing_gates": timing_gates,
        "max_abs_mean_loss_error": max_mean_loss_error,
        "max_abs_reduction_pct_error": max_reduction_error,
        "max_abs_dm_t_error": max_dm_t_error,
        "status": "PASS",
    }


def math_isclose(left: float, right: float, tolerance: float) -> bool:
    return bool(np.isclose(left, right, rtol=0.0, atol=tolerance, equal_nan=False))


def strip_private(d):
    """Remove _-prefixed helper series from the JSON-serialized OOS blocks."""
    clean = {}
    for H, block in d.items():
        clean[str(H)] = {k: v for k, v in block.items() if not k.startswith("_")}
    return clean


def main(*, force_refresh_alfred: bool = False):
    FIT_DIAGNOSTICS.clear()
    FIT_DIAGNOSTICS.update(_empty_fit_diagnostics())
    t0 = datetime.now()
    print("[K1655] building weekly panel ...")
    panel, nfci_pit, vix_raw, pit_provenance = build_panel(
        force_refresh_alfred=force_refresh_alfred
    )
    print(f"[K1655] panel: n={len(panel)} weeks, "
          f"{panel.index[0].date()}..{panel.index[-1].date()}")

    # Two conditioning specs: NFCI (primary GaR variable, Adrian et al. headline) and
    # VIX (market-implied vol; secondary benchmark comparison). These separate
    # single-variable specs are not a paired NFCI-vs-VIX or encompassing test.
    SPECS = {"NFCI": ["nfci"], "VIX": ["vix"]}

    ear, var = {}, {}   # equity-at-risk, vol-at-risk (secondary)
    for name, cols in SPECS.items():
        print(f"[K1655] equity-at-risk spec={name}: in-sample + OOS ...")
        in_s, slope_s = in_sample_analysis(panel, "fwd_ret", cols, QUANTILES, HORIZONS, name)
        oos_s = oos_analysis(panel, "fwd_ret", cols, QUANTILES, HORIZONS, name)
        ear[name] = {"in": in_s, "slope": slope_s, "oos": oos_s}
    for name, cols in SPECS.items():
        print(f"[K1655] vol-at-risk spec={name}: in-sample + OOS ...")
        in_s, slope_s = in_sample_analysis(panel, "fwd_vol", cols, QUANTILES, HORIZONS, name)
        oos_s = oos_analysis(panel, "fwd_vol", cols, QUANTILES, HORIZONS, name)
        var[name] = {"in": in_s, "slope": slope_s, "oos": oos_s}

    blocking_fit_diagnostics = {
        key: FIT_DIAGNOSTICS[key]
        for key in (
            "unresolved_iteration_limit_failures",
            "other_warning_count",
            "bootstrap_fit_exceptions",
            "oos_fit_exceptions",
        )
    }
    if any(blocking_fit_diagnostics.values()):
        raise RuntimeError(
            f"QuantReg convergence/fit gate failed: {blocking_fit_diagnostics}; "
            f"details={FIT_DIAGNOSTICS}"
        )

    in_ret, oos_ret = ear["NFCI"]["in"], ear["NFCI"]["oos"]   # primary
    verdict = build_verdict(in_ret, oos_ret)

    forecast_rows = []
    for result_family in (ear, var):
        for spec in result_family.values():
            for horizon_block in spec["oos"].values():
                forecast_rows.extend(horizon_block["_forecast_rows"])
    forecast_frame = pd.DataFrame(forecast_rows).sort_values(
        ["target", "spec", "horizon_weeks", "tau", "origin"]
    ).reset_index(drop=True)
    forecast_path = os.path.join(HERE, "K1655_oos_forecasts.csv")
    atomic_write_csv(forecast_frame, forecast_path)
    forecast_roundtrip = pd.read_csv(forecast_path)
    artifact_audit = verify_forecast_artifact(forecast_roundtrip, ear, var)

    # ---- charts ----
    print("[K1655] charts ...")
    chart_slope_across_quantiles(ear["NFCI"]["slope"],
                                 os.path.join(HERE, "K1655_nfci_slope_across_quantiles.png"),
                                 "S&P 500 price-index forward returns")
    chart_gar_vs_realized(panel, oos_ret, DISPLAY_H,
                          os.path.join(HERE, "K1655_gar_quantiles_vs_realized.png"))
    chart_pinball_by_horizon(ear["NFCI"]["oos"], ear["VIX"]["oos"],
                             os.path.join(HERE, "K1655_oos_pinball_by_horizon.png"))

    results = {
        "experiment_id": "K1655",
        "title": "Growth-at-Risk moved to markets: Equity/Vol-at-Risk multi-horizon quantile regression",
        "run_at": t0.isoformat(),
        "seed": SEED,
        "data": {
            "spy_source": "yfinance ^GSPC (auto_adjust close)",
            "nfci_source": (
                "FRED/ALFRED NFCI output_type=1 full real-time revision history; "
                "for each Friday origin, select the latest observation whose inclusive "
                "revision interval contains that origin. No final-vintage fallback."
            ),
            "vix_source": "FRED VIXCLS (daily close, known same-day; reused from experiments/k1601 snapshot).",
            "credit_spread_note": (
                "BAA10Y is not evaluated in this corrected rerun. The primary design is "
                "the single-index NFCI specification; no bivariate or encompassing claim is made."
            ),
            "frequency": "weekly W-FRI",
            "sample_start": str(panel.index[0].date()),
            "sample_end": str(panel.index[-1].date()),
            "n_weeks": int(len(panel)),
            "nfci_selected_observation_span": [
                str(nfci_pit["nfci_obs_date"].dropna().min().date()),
                str(nfci_pit["nfci_obs_date"].dropna().max().date()),
            ],
            "vix_raw_span": [str(vix_raw['DATE'].iloc[0].date()), str(vix_raw['DATE'].iloc[-1].date())],
            "nfci_provenance": pit_provenance,
            "forecast_artifact": {
                "path": os.path.basename(forecast_path),
                "rows": int(len(forecast_roundtrip)),
                "sha256": sha256_file(forecast_path),
                "verification": artifact_audit,
            },
        },
        "config": {
            "horizons_weeks": HORIZONS,
            "quantiles": QUANTILES,
            "primary_tau": PRIMARY_TAU,
            "vol_tau": VOL_TAU,
            "min_train_weeks": MIN_TRAIN,
            "refit_every_weeks": REFIT_EVERY,
            "bootstrap_B": BOOT_B,
            "bootstrap": "moving-block, block length = H",
            "quantreg_max_iter_stages": list(QUANTREG_MAX_ITER_STAGES),
            "quantreg_fit_diagnostics": FIT_DIAGNOSTICS,
            "dm": (
                "HLN-corrected; Newey-West lag=max(H-1, repo-canonical "
                "ceil(H^(1/3)*n^(1/3)) bandwidth), horizon-specific; helper_dm cross-check"
            ),
            "embargo": "training row admissible iff j + H < i (project canonical strict)",
            "feature_availability": (
                "true ALFRED point-in-time: realtime_start <= origin <= realtime_end "
                "(inclusive), latest observation_date <= origin; no origin before first vintage"
            ),
            "specs": {k: v for k, v in SPECS.items()},
        },
        "equity_at_risk": {
            "primary_spec": "NFCI",
            "NFCI": {"in_sample": ear["NFCI"]["in"], "oos": strip_private(ear["NFCI"]["oos"])},
            "VIX": {"in_sample": ear["VIX"]["in"], "oos": strip_private(ear["VIX"]["oos"])},
        },
        "vol_at_risk_secondary": {
            "NFCI": {"in_sample": var["NFCI"]["in"], "oos": strip_private(var["NFCI"]["oos"])},
            "VIX": {"in_sample": var["VIX"]["in"], "oos": strip_private(var["VIX"]["oos"])},
        },
        "verdict": verdict,
        "review_status": {
            "status": "PASS",
            "reviewed_at": "2026-07-11",
            "review_artifact": "reviews/codex_alfred_pit_postrun_2026-07-11.md",
            "prior_primary_review": "FAIL",
            "prior_review_artifact": "reviews/codex_primary_reverify_2026-07-11.md",
            "scope": "True-PIT ALFRED reconstruction, timing gates, serialized OOS artifact, and limited NULL conclusion.",
            "note": "Statistical verdict is separate from code/research review status.",
        },
        "references": [
            {
                "authors": "Adrian, T.; Boyarchenko, N.; Giannone, D.",
                "year": 2019,
                "title": "Vulnerable Growth",
                "publication": "American Economic Review 109(4), 1263-1289",
                "doi": "10.1257/aer.20161923",
            },
            {
                "authors": "Croushore, D.; Stark, T.",
                "year": 2001,
                "title": "A Real-Time Data Set for Macroeconomists",
                "publication": "Journal of Econometrics 105(1), 111-130",
                "doi": "10.1016/S0304-4076(01)00072-0",
            },
            {
                "authors": "Diebold, F. X.; Mariano, R. S.",
                "year": 1995,
                "title": "Comparing Predictive Accuracy",
                "publication": "Journal of Business & Economic Statistics 13(3), 253-263",
                "doi": "10.1080/07350015.1995.10524599",
            },
            {
                "authors": "Harvey, D.; Leybourne, S.; Newbold, P.",
                "year": 1997,
                "title": "Testing the Equality of Prediction Mean Squared Errors",
                "publication": "International Journal of Forecasting 13(2), 281-291",
                "doi": "10.1016/S0169-2070(96)00719-4",
            },
        ],
        "honest_statement": (
            "Cross-domain test of Adrian et al. (2019) Growth-at-Risk on an equity market. "
            "In-sample tail slopes reflect crisis co-movement and are NOT a predictive claim; "
            "the predictive claim is the OOS pinball-loss DM (HLN, horizon-specific). "
            "The supported conclusion is limited to the true-PIT 2011+ sample and the stated "
            "unconditional benchmark. Separate NFCI and VIX specifications do not establish "
            "dominance or encompassing. All statistics come from the stated computation; "
            "no cherry-picking."
        ),
    }
    out_path = os.path.join(HERE, "K1655_results.json")
    atomic_write_json(results, out_path)

    # console summary
    print("\n===== K1655 SUMMARY =====")
    print(f"verdict: {verdict['verdict']}")
    for H in HORIZONS:
        c = in_ret[f"H{H}_tau{PRIMARY_TAU}"]["nfci"]
        o = oos_ret[H]["tau"][str(PRIMARY_TAU)]
        print(f" H={H:>2}w | IS NFCI slope@0.05={c['coef']:+.5f} (boot p={c['boot_p']:.3f}) "
              f"| OOS pinball cond={o['pinball_cond']:.6f} unc={o['pinball_uncond']:.6f} "
              f"red={o['pinball_reduction_pct']:+.2f}% DM_HLN t={o['dm_t_hln']:+.2f} p={o['dm_p_hln']:.3f}")
    print(f"elapsed: {(datetime.now()-t0).total_seconds():.0f}s")
    print(f"written: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-alfred",
        action="store_true",
        help="Refetch and atomically replace the fully paginated ALFRED NFCI cache",
    )
    args = parser.parse_args()
    main(force_refresh_alfred=args.refresh_alfred)
