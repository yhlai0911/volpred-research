"""Official macro-event release dates.

Event studies treat the event date as a constant. It is not — it is data, and it
needs a primary source like any other input. A calendar proxy ("CPI comes out
around the 13th") silently does two things at once: it counts non-event days as
event days, and it dumps real event days into the control group. Nothing throws,
nothing is NaN, the figures still render.

That is not hypothetical. Until 2026-07-12 our CPI event studies hard-coded the
release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
dates were wrong, one of them a day on which BLS published no CPI at all (the
Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
reaction on the real dates flipped the mean from +2.18% to -0.85%.

So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
publishes the actual news-release dates per statistical release, which is exactly
the ground truth an event study needs.

Usage:
    from volpred.data.event_dates import cpi_release_dates
    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex

See docs/error_log.md 2026-07-12 for the incident this module exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# FRED release ids for the macro releases we run event studies on.
# https://fred.stlouisfed.org/releases
RELEASE_IDS = {
    "CPI_US": 10,      # Consumer Price Index
    "NFP_US": 50,      # Employment Situation
    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
}

_CACHE_DIR = Path(__file__).resolve().parents[3] / "storage" / "data" / "event_dates_cache"
_CACHE_TTL = timedelta(days=7)


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    root = Path(__file__).resolve().parents[3]
    for cand in (".env.local", ".env"):
        p = root / cand
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if line.startswith("FRED_API_KEY"):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(
        "FRED_API_KEY not found. Event dates must come from the official release "
        "calendar — do not fall back to a hard-coded list or a calendar proxy."
    )


def _fetch(release_id: int, start: str, end: str) -> list[str]:
    r = requests.get(
        "https://api.stlouisfed.org/fred/release/dates",
        params={
            "release_id": release_id,
            "api_key": _api_key(),
            "file_type": "json",
            "realtime_start": start,
            "realtime_end": end,
            # Without this, ALFRED only returns releases that already carry data, so
            # scheduled-but-not-yet-published dates (the ones an upcoming-event
            # populator actually needs) are missing. Verified 2026-07-12 that it does
            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
            # shutdown, stays absent either way.
            "include_release_dates_with_no_data": "true",
            "limit": 1000,
            "sort_order": "asc",
        },
        timeout=30,
    )
    r.raise_for_status()
    return [d["date"] for d in r.json()["release_dates"]]


def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
    """Official news-release dates for `event` within [start, end].

    Monthly releases can carry off-cycle entries (annual seasonal-factor and
    benchmark revisions are filed against the same release id, LATER in the
    month than the regular report). We therefore keep the EARLIEST entry in
    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
    picked 6 off-cycle dates as NFP events and flipped a significance result.

    Fail-closed on ambiguity: the selected sequence must look like a monthly
    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
    e.g. 2025-09-05 -> 2025-11-20 = 76d). Any gap outside that band
    raises instead of returning a plausible-but-wrong calendar —
    silently-wrong event dates are worse than a failed run.
    """
    if event not in RELEASE_IDS:
        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")

    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
    if use_cache and cache.exists():
        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
        if age < _CACHE_TTL:
            raw = json.loads(cache.read_text())
        else:
            raw = None
    else:
        raw = None

    if raw is None:
        raw = _fetch(RELEASE_IDS[event], start, end)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw) + "\n")

    dates = pd.to_datetime(raw)
    if len(dates) == 0:
        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
    s = pd.Series(dates, index=dates)
    monthly = s.groupby([dates.year, dates.month]).min()
    selected = pd.DatetimeIndex(sorted(monthly.values))
    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
    gaps = pd.Series(selected).diff().dropna().dt.days
    bad = gaps[(gaps < 13) | (gaps > 110)]
    if len(bad) > 0:
        offenders = [
            f"{selected[i - 1].date()} -> {selected[i].date()} ({int(g)}d)"
            for i, g in zip(bad.index, bad.values)
        ]
        raise RuntimeError(
            f"{event} release calendar failed monthly-cadence validation "
            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
            f"missing months need manual disambiguation — refusing to return "
            f"a plausible-but-wrong calendar."
        )
    return selected


def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
    return release_dates("CPI_US", start, end, **kw)


def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
    return release_dates("NFP_US", start, end, **kw)
