"""
K528: NFP (Non-Farm Payrolls) Event Study on SPY Volatility
=============================================================
Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.

K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
  - Larger sample with more granular windows
  - VIX predictive regression
  - Vol crush pattern analysis
  - Seasonal decomposition (which months matter?)
  - NFP surprise impact (FRED PAYEMS data)

Data sources:
  - SPY daily OHLCV: yfinance (2005-01 to 2026-03)
  - VIX daily close: yfinance (^VIX)
  - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)

CORRECTION 2026-07-19
---------------------
The original run dated every NFP to the first Friday of the month. That proxy is
wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
moves the release to the second Friday whenever the reference week falls late
(28 dates land exactly 7 days early), and pulls it forward around holidays (12
dates land 3-4 days late). It also invents a release in 2025-10 that never
happened, and it forces every event onto a Friday when 16 of the 254 official
releases are not on a Friday at all.

Wrong event dates do not fail loudly. They count quiet days as event days and
dump real event days into the control group, and the figures still render. So
the dates now come from the official release calendar and the run FAILS CLOSED
if that calendar is unreachable -- `get_first_friday` is gone, not deprecated.

This script also emits a before/after comparison against the archived proxy-era
results so the correction's effect on every published number is auditable
(k528_nfp_official_dates_results.json).

References:
  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
    JFE, core finding: scheduled macro announcements earn risk premium
  - Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JFE
  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
  - K1442: event-date audit that found this bug

Author: VolPred Research System
Date: 2026-03-27 (corrected 2026-07-19)
"""

import json
import os
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates

warnings.filterwarnings("ignore")

SAMPLE_START = "2005-01-01"
SAMPLE_END = "2026-03-27"

# Months for which BLS published no Employment Situation report at all. Each
# entry needs a documented reason, and check_calendar_is_complete VERIFIES the
# claim against the raw feed before honouring it -- an allowlist that is taken
# on faith is just a way to make a failing check pass, which is the failure mode
# this whole experiment exists to document.
KNOWN_MISSING_MONTHS: dict[str, str] = {
    "2025-10": (
        "Federal government shutdown. ALFRED shows no release id 50 entry between "
        "2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed "
        "September report landed on 11-20. Same shutdown that cancelled the Oct-2025 "
        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
        "INVENTED an event here -- that phantom is one of the reasons for this rerun."
    ),
}

# Two same-month entries closer together than this cannot be told apart as
# "regular report" vs "off-cycle revision" by date order alone, so the run
# refuses to guess.
#
# A correction I got wrong once and am recording so it is not repeated: I removed
# this gate claiming the real feed "straddles" it, because three genuine cases
# (2006-05, 2013-05, 2020-05) are exactly 3 days apart. That was a misreading of
# my own condition -- the test is `gap < 3`, and a 3-day gap passes it. The real
# data never falsified this gate; I falsified it by first changing `<` to `<=`
# and then deleting it. It is restored, at `< 3`, where every real case passes.
AMBIGUOUS_SAME_MONTH_GAP_DAYS = 3

# The months where ALFRED returns two release-id-50 entries, pinned as the FULL
# raw date set plus which entry is the actual Employment Situation report. Each
# verified individually against the BLS news-release archive
# (bls.gov/news.release/archives/empsit_<MMDDYYYY>.htm).
#
# Why an explicit reviewed list rather than a rule: "earliest entry in the month"
# is right for every case we have checked, but it is a HEURISTIC, and it fails
# silently if an off-cycle item is ever filed BEFORE the report. There is no way
# to tell those apart from dates alone.
#
# Why the full date set and not just the month key: authorising a MONTH means a
# reviewed month whose feed later gains a third entry still sails through on a
# review that never saw it. The approval has to be of the shape someone actually
# looked at, so a change to that shape sends it back for review.
REVIEWED_MULTI_ENTRY_MONTHS: dict[str, dict] = {
    "2006-05": {"raw": ["2006-05-05", "2006-05-08"], "report": "2006-05-05"},
    "2012-12": {"raw": ["2012-12-07", "2012-12-12"], "report": "2012-12-07"},
    "2013-05": {"raw": ["2013-05-03", "2013-05-06"], "report": "2013-05-03"},
    "2020-05": {"raw": ["2020-05-08", "2020-05-11"], "report": "2020-05-08"},
    "2024-01": {"raw": ["2024-01-05", "2024-01-10"], "report": "2024-01-05"},
    "2024-08": {"raw": ["2024-08-02", "2024-08-21"], "report": "2024-08-02"},
}

# How far the observed calendar may fall short of the requested window before the
# run treats it as truncated. One monthly cycle plus slack; a feed that stops
# early otherwise shrinks the "observed span" it is checked against and passes.
MAX_WINDOW_SHORTFALL_DAYS = 70


def write_json_atomic(path: Path, payload) -> None:
    """Write `payload` to `path` atomically.

    A truncate-then-write leaves a half-written results file on the disk if the
    run dies mid-dump, and a half-written results file is worse than none: it
    still parses far enough to look like data to the next reader. Write to a
    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
        raise


# ============================================================
# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
# ============================================================
def check_calendar_is_complete(selected, raw, start, end):
    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.

    "Did the call succeed?" is the wrong question. A monthly release calendar
    that silently lost 2019 still returns a non-empty list, still produces
    event windows, still renders.

    This validates the RAW feed as well as the accessor's per-month selection.
    Validating only the selection cannot work: the accessor collapses each month
    to one date before this function ever sees it, so a same-month ambiguity is
    already resolved -- silently, and possibly wrongly -- by the time a check on
    the output could look for it. That is precisely how the k528 v2 BLOCKER got
    through (Codex v3 finding 3).

    Four ways the input can be wrong without being empty, all of which raise:
      1. a month has two entries too close together to tell report from revision
      2. the selection is not the earliest entry of its month
      3. a month is missing from the observed span
      4. a month is claimed as a known hole but the raw feed actually has data
    """
    sel = [pd.Timestamp(d) for d in selected]
    sel_months = [d.strftime("%Y-%m") for d in sel]

    raw_by_month: dict[str, list[pd.Timestamp]] = {}
    for d in raw:
        ts = pd.Timestamp(d)
        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
    for v in raw_by_month.values():
        v.sort()

    # 0: the selection itself must be well-formed before anything is inferred
    # from it. Building a month->date dict first would silently keep only the
    # last of a duplicated month and hide exactly what we are looking for.
    sel_month_counts: dict[str, int] = {}
    for m in sel_months:
        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
    if sel_dupes:
        raise RuntimeError(
            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
        )
    invented = sorted(set(sel_months) - set(raw_by_month))
    if invented:
        raise RuntimeError(
            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
            "The selection must be a subset of what the source actually published."
        )
    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
    if off_feed:
        raise RuntimeError(
            f"selected dates that do not appear in the raw feed at all: {off_feed}."
        )

    # 1: the accessor's per-month choice must be the earliest entry, and any
    # same-month pair must be far enough apart to tell report from revision.
    ambiguous, mis_selected = [], []
    sel_by_month = dict(zip(sel_months, sel))
    for month, entries in raw_by_month.items():
        if len(entries) > 1:
            gap = (entries[1] - entries[0]).days
            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
                ambiguous.append(
                    f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)"
                )
        if month in sel_by_month and sel_by_month[month] != entries[0]:
            mis_selected.append(
                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
            )
    if ambiguous:
        raise RuntimeError(
            f"{len(ambiguous)} month(s) carry two release entries too close together to "
            f"identify the Employment Situation report by date order: {ambiguous}. "
            "Refusing to guess which one is the monthly report."
        )
    if mis_selected:
        raise RuntimeError(
            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
            "monthly report -- selecting it is the k528 v2 BLOCKER."
        )

    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
    # BEFORE the report. Every multi-entry month therefore has to be one a human
    # checked against the BLS archive, and the checked answer has to match.
    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
    if unreviewed:
        raise RuntimeError(
            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
            f"checked against the BLS archive: "
            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
            "Situation report at bls.gov/news.release/archives/ and add it to "
            "REVIEWED_MULTI_ENTRY_MONTHS."
        )
    # Approve the SHAPE, not the month. A reviewed month whose feed later gains
    # or loses an entry is a shape nobody reviewed, so it goes back for review.
    reshaped = {
        m: {"now": [str(d.date()) for d in multi[m]], "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]}
        for m in multi
        if [str(d.date()) for d in multi[m]] != REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]
    }
    if reshaped:
        raise RuntimeError(
            f"the raw feed for reviewed month(s) no longer matches what was reviewed: {reshaped}. "
            "The approval covers the entry set someone actually checked, not the month name. "
            "Re-verify against bls.gov/news.release/archives/ before proceeding."
        )
    contradicted = {
        m: {"selected": str(sel_by_month[m].date()),
            "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]}
        for m in multi
        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]
    }
    if contradicted:
        raise RuntimeError(
            f"selection contradicts the human-verified release date in {contradicted}. "
            "Either the feed changed or the accessor regressed; do not proceed on the guess."
        )

    # Every month the source published must survive into the selection. Without
    # this, a month can vanish between raw and selected (stale accessor cache vs
    # a live raw fetch is exactly that shape) and neither the gap check nor the
    # window-coverage check sees it -- the observed span just ends one month
    # earlier and still looks continuous.
    dropped = sorted(set(raw_by_month) - set(sel_months) - set(KNOWN_MISSING_MONTHS))
    if dropped:
        raise RuntimeError(
            f"the raw feed has {len(dropped)} month(s) that the selected calendar does not: "
            f"{dropped}. A month present at the source and absent from the analysis is a "
            "silently shortened sample."
        )

    # 3a: the observed span must actually cover what was asked for. Checking only
    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
    # stops early, the span shrinks with it and nothing looks missing. Found by
    # self-audit while Codex v3 round-2 was running.
    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
    head_short = (min(sel) - want_start).days
    tail_short = (want_end - max(sel)).days
    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
        raise RuntimeError(
            f"official NFP calendar does not cover the requested window "
            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
            f"last release {max(sel).date()} ({tail_short}d short of the end). "
            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
            "shortens the sample while every printed count still agrees with itself."
        )

    # 3b: no month may vanish from inside the observed span.
    span = {
        p.strftime("%Y-%m")
        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
    }
    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
    if missing:
        raise RuntimeError(
            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
            f"span: {missing}. A partial calendar dumps real event days into the control "
            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
            "reason (e.g. a cancelled release), never to make this check pass."
        )

    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
    # allowlist is a bypass: any month could be declared 'known missing' and the
    # check would stop looking at it.
    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
    if bogus:
        raise RuntimeError(
            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
            "The allowlist is for real cancellations, not for silencing a selection bug."
        )

    return {
        "n_months_in_span": len(span),
        "n_raw_entries": len(raw),
        "months_with_multiple_raw_entries": sorted(multi),
        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
        "window_coverage": {
            "requested": f"{start}..{end}",
            "observed": f"{min(sel).date()}..{max(sel).date()}",
            "head_shortfall_days": int(head_short),
            "tail_shortfall_days": int(tail_short),
            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
        },
        "residual_limitation": (
            "Same-month selection uses 'earliest wins', which is a heuristic. It cannot "
            "distinguish an off-cycle item filed BEFORE the report from the report itself, "
            "so every multi-entry month must additionally appear in "
            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
            "new multi-entry month fails the run rather than being assumed."
        ),
    }


def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
    """Official NFP (Employment Situation) release dates.

    Deliberately has no except branch. If the release calendar cannot be
    reached, this run must die -- a proxy calendar produces plausible numbers
    from non-events, which is worse than no numbers at all. See the CORRECTION
    note in the module docstring.
    """
    dates = nfp_release_dates(start, end)
    if len(dates) == 0:
        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
    # Pull the unselected feed as well: the accessor collapses each month to one
    # date, so the only place a same-month ambiguity is still visible is here.
    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
    completeness = check_calendar_is_complete(dates, raw, start, end)
    return list(dates), completeness


# ============================================================
# 2. Download data
# ============================================================
print("=" * 60)
print("K528: NFP Event Study on SPY Volatility")
print("=" * 60)

print("\n[1/6] Downloading SPY and VIX data...")
spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Calculate returns
spy["Return"] = spy["Close"].pct_change()
spy["AbsReturn"] = spy["Return"].abs()
spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
spy.dropna(subset=["Return"], inplace=True)

# Merge VIX
vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
spy = spy.join(vix_close, how="left")
spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays

print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")

# ============================================================
# 3. Map NFP dates to trading days
# ============================================================
print("\n[2/6] Mapping NFP dates to trading days...")

nfp_calendar, calendar_completeness = load_nfp_dates()
trading_dates = spy.index

# The proxy forced every event onto a Friday. The official calendar does not,
# and that is load-bearing for the Friday-baseline test below.
n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
print(f"  Official releases: {len(nfp_calendar)} "
      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")

# Map each NFP date to the session that trades the news. The report drops at
# 08:30 ET, before the open, so a release on a closed day is traded at the next
# open -- hence "next trading day", not "nearest". Every release must land on
# exactly one session and no two releases may share one: both failures shrink
# the event set without shrinking any count that gets printed.
release_to_session = {}
unmapped = []
for nfp_date in nfp_calendar:
    nfp_ts = pd.Timestamp(nfp_date)
    if nfp_ts in trading_dates:
        release_to_session[nfp_ts] = nfp_ts
        continue
    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
    candidates = trading_dates[mask]
    if len(candidates) > 0:
        release_to_session[nfp_ts] = candidates[0]
    else:
        unmapped.append(nfp_ts.date().isoformat())

# In-sample releases must map. Releases outside the price series (the calendar
# window can overhang the SPY history on either end) are excluded by design,
# not by failure, so they are separated before the assertion.
in_sample_unmapped = [
    d for d in unmapped
    if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
]
if in_sample_unmapped:
    raise RuntimeError(
        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
        f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
        "drop real event days into the control group."
    )

collisions = {}
for rel, sess in release_to_session.items():
    collisions.setdefault(sess, []).append(rel.date().isoformat())
colliding = {str(s.date()): sorted(v) for s, v in collisions.items() if len(v) > 1}
if colliding:
    raise RuntimeError(
        f"two or more NFP releases mapped to the same trading session: {colliding}. "
        "The de-duplication that used to hide this also silently reduced the event count."
    )

nfp_trading_dates = sorted(release_to_session.values())
n_shifted = sum(1 for r, s in release_to_session.items() if r != s)

# Window buffer: an event needs 5 sessions before and 5 after to have a window
# at all. Excluding the edges is correct; doing it without saying so is not.
window_excluded = [d for d in nfp_trading_dates
                   if d < trading_dates[10] or d > trading_dates[-6]]
valid_nfp = [d for d in nfp_trading_dates
             if d >= trading_dates[10] and d <= trading_dates[-6]]

if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
    raise RuntimeError("event-window partition lost events; refusing to continue")

mapping_audit = {
    "n_official_releases": len(nfp_calendar),
    "n_mapped_to_sessions": len(nfp_trading_dates),
    "n_shifted_to_next_session": n_shifted,
    "n_outside_price_sample": len(unmapped),
    "outside_price_sample_dates": sorted(unmapped),
    "n_excluded_for_window_buffer": len(window_excluded),
    "window_excluded_dates": [str(d.date()) for d in window_excluded],
    "n_valid_events": len(valid_nfp),
}

print(f"  Total official releases: {len(nfp_calendar)}")
print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
print(f"  Outside price sample: {len(unmapped)}")
print(f"  Excluded for window buffer: {len(window_excluded)}")
print(f"  Valid (with pre/post window): {len(valid_nfp)}")

# ============================================================
# 4. Calculate event windows
# ============================================================
print("\n[3/6] Calculating event window statistics...")

results = []
idx_list = list(trading_dates)

for nfp_date in valid_nfp:
    pos = idx_list.index(nfp_date)

    # Pre-event: T-5 to T-1
    pre_window = spy.iloc[pos-5:pos]
    # Event day: T
    event_day = spy.iloc[pos]
    # Post-event: T+1 to T+5
    post_window = spy.iloc[pos+1:pos+6]

    # Unreachable given the window-buffer partition above. Kept as an assertion
    # rather than a `continue`: if the partition ever stops holding, the run
    # must stop, not quietly analyse a smaller sample than it reports.
    if len(pre_window) < 5 or len(post_window) < 5:
        raise RuntimeError(
            f"event {nfp_date.date()} has an incomplete window "
            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
            "window-buffer filter -- the partition and the window logic disagree"
        )

    row = {
        "date": nfp_date.strftime("%Y-%m-%d"),
        "year": nfp_date.year,
        "month": nfp_date.month,
        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
        "event_return": float(event_day["Return"]),
        "event_abs_return": float(event_day["AbsReturn"]),
        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
        "vix_change_event": None,
        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
    }

    if row["pre_vix"] is not None and row["event_vix"] is not None:
        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]

    results.append(row)

df = pd.DataFrame(results)
print(f"  Events with complete data: {len(df)}")
print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")

# ============================================================
# 5. Non-NFP baseline calculation
# ============================================================
print("\n[4/6] Computing non-NFP baseline...")

# Exclude EVERY NFP session from the control group, not just the ones that
# survived the event-window filter. An event dropped for lacking a pre-window
# is still an NFP day; leaving it in the control group is the exact failure this
# experiment exists to fix ("dump real event days into the control group"), just
# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
nfp_set = set(nfp_trading_dates)
non_nfp_mask = ~spy.index.isin(nfp_set)
non_nfp = spy[non_nfp_mask]
n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
if n_leaked:
    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")

baseline_abs_return = float(non_nfp["AbsReturn"].mean())
baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
baseline_abs_return_median = float(non_nfp["AbsReturn"].median())

# Friday-only baseline. The event group is a weekday MIXTURE while the control
# group is pure Friday, so any Friday-vs-other-weekday volatility difference
# loads straight onto the estimate. The test below holds weekday fixed on BOTH
# sides.
#
# Note against the obvious story: this defect is NOT introduced by the date
# correction. The proxy calendar was all-Friday by construction, but mapping
# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
# always there and is essentially unchanged; the old spec was already comparing
# a mixed group against a pure-Friday control. Correcting the dates is what made
# it visible, not what caused it.
friday_mask = non_nfp.index.weekday == 4
friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())

print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")

# ============================================================
# 6. Statistical tests
# ============================================================
print("\n[5/6] Running statistical tests...")

nfp_abs_returns = df["event_abs_return"].values
non_nfp_abs_returns = non_nfp["AbsReturn"].values
friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values

# --- Test A: NFP vs all non-NFP days ---
t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())

# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
#
# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
#   (i)  restrict the event group to Friday releases, or
#   (ii) keep all events and use weekday-matched controls.
# This run takes (i). The non-Friday events are a handful of thin weekday cells
# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
# single-digit strata, with standard errors driven by the smallest of them.
# That is a noisier estimator of a harder-to-state quantity. (i) answers one
# clean question: on a Friday, does an NFP release raise volatility? It costs
# the non-Friday events, which are reported below as a separate descriptive
# line rather than dropped in silence.
#
# The exclusion is not neutral and should not be sold as such: the excluded
# events are quieter than the Friday ones, so restricting RAISES the ratio
# relative to the mixed spec. That is a property of the estimand, not evidence
# of a stronger effect. Both numbers are reported.
nfp_friday_mask = (df["weekday"] == 4).values
nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]

t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())

# Diagnostic ONLY -- the pre-correction specification, kept so the correction
# audit can show what the contaminated estimand was worth. Not a headline
# number and not eligible to be quoted: its p-value mixes in weekday
# composition, which is exactly the defect being repaired.
t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())

# --- Test C: Wilcoxon rank-sum (non-parametric) ---
u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')

# --- Test D: Vol crush pattern (post vs pre) ---
vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)

# --- Test E: VIX predictive regression ---
vix_valid = df.dropna(subset=["pre_vix"])
if len(vix_valid) > 10:
    from numpy.polynomial.polynomial import polyfit
    X_vix = vix_valid["pre_vix"].values
    Y_abs = vix_valid["event_abs_return"].values
    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
    # correlation and p-value
    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
    # also spearman
    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
else:
    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6

# --- Test F: Pre-event VIX change (buildup) ---
# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
vix_buildup = []
for nfp_date in valid_nfp:
    pos = idx_list.index(nfp_date)
    pre5 = spy.iloc[pos-5]
    pre1 = spy.iloc[pos-1]
    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))

t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)

# --- Test G: Seasonal analysis (by month) ---
monthly_stats = {}
for month in range(1, 13):
    month_data = df[df["month"] == month]["event_abs_return"]
    if len(month_data) >= 5:
        monthly_stats[str(month)] = {
            "n": int(len(month_data)),
            "mean_abs_return": float(month_data.mean()),
            "vol_ratio": float(month_data.mean() / baseline_abs_return),
            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
        }

# --- Test H: Regime analysis (high VIX vs low VIX) ---
vix_median = df["pre_vix"].median()
high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)

# --- Test I: Time trend (has NFP impact changed over time?) ---
# Split into halves
midpoint = len(df) // 2
first_half = df.iloc[:midpoint]["event_abs_return"]
second_half = df.iloc[midpoint:]["event_abs_return"]
t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)

# --- Test J: Event-day return direction ---
pos_returns = (df["event_return"] > 0).sum()
neg_returns = (df["event_return"] < 0).sum()
# Binomial test: is there a directional bias?
binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)

print(f"\n--- A. NFP vs All Non-NFP Days ---")
print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
print(f"  t-stat:               {t_stat_all:.3f}")
print(f"  p-value:              {p_val_all:.4f}")
print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")

print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
print(f"  t-stat:               {t_stat_fri:.3f}")
print(f"  p-value:              {p_val_fri:.4f}")
print(f"  Significant (5%):     {'YES' if p_val_fri < 0.05 else 'NO'}")
print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
      f"mean |ret|={nfp_nonfriday_abs.mean():.6f}" if len(nfp_nonfriday_abs) else "  [excluded] none")
print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
      f"{vol_ratio_fri_mixed:.4f}x, p={p_val_fri_mixed:.5f}")
print(f"      ^ pre-correction estimand; p mixes in weekday composition")

print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
print(f"  U-stat:               {u_stat:.1f}")
print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")

print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
print(f"  Difference:           {vol_crush.mean():.6f}")
print(f"  t-stat:               {t_crush:.3f}")
print(f"  p-value:              {p_crush:.4f}")
print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")

print(f"\n--- E. VIX Predictive Regression ---")
if r_vix is not None:
    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
    print(f"  Slope:                {slope:.8f}")
    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")

print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
if t_buildup is not None:
    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
    print(f"  t-stat:               {t_buildup:.3f}")
    print(f"  p-value:              {p_buildup:.4f}")
    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")

print(f"\n--- G. Seasonal Pattern (by month) ---")
print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
for m in range(1, 13):
    if str(m) in monthly_stats:
        ms = monthly_stats[str(m)]
        sig = "*" if ms["p_val"] < 0.05 else ""
        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")

print(f"\n--- H. VIX Regime Analysis ---")
print(f"  VIX median split:     {vix_median:.1f}")
print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
print(f"  t-stat:               {t_regime:.3f}")
print(f"  p-value:              {p_regime:.4f}")

print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
print(f"  t-stat:               {t_trend:.3f}")
print(f"  p-value:              {p_trend:.4f}")

print(f"\n--- J. Directional Bias ---")
print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
print(f"  Binomial p-value:     {binom_p:.4f}")

# ============================================================
# 7. High-low range analysis (intraday vol proxy)
# ============================================================
print(f"\n--- K. Intraday Range (High-Low / Close) ---")
nfp_range = df["high_low_range"].mean()
non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
range_ratio = nfp_range / non_nfp_range
print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
print(f"  Range ratio:          {range_ratio:.3f}x")

# Volume analysis
print(f"\n--- L. Volume Analysis ---")
vol_ratio_data = df["volume_ratio"].dropna()
print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")

# ============================================================
# 8. April NFP specific (for upcoming 04/03 article)
# ============================================================
print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
april_nfp = df[df["month"] == 4]
print(f"  April NFP events:     {len(april_nfp)}")
print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
if "4" in monthly_stats:
    ms4 = monthly_stats["4"]
    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")

# ============================================================
# 9. Summary conclusion
# ============================================================
print(f"\n{'=' * 60}")
print("SUMMARY CONCLUSION")
print("=" * 60)

sig_level = 0.05
conclusions = []

# Each conclusion names the test it came from. The previous run collapsed
# several tests into "insignificant across all tests" while the one-sided
# Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
# contradicted its own numbers. A Welch test on |return| is a test of MEANS;
# it not rejecting is not a finding that the distributions match, and it is
# never evidence that the effect is zero.
conclusions.append(
    f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
    f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
)
conclusions.append(
    f"Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, "
    f"weekday held fixed): {vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
    f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to Friday "
    f"releases; the {len(nfp_nonfriday_abs)} non-Friday events are quieter, so this "
    f"is not a statement about NFP releases in general."
)
conclusions.append(
    f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
    f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
)
if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
    conclusions.append(
        "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
        "so a rank test can detect a location shift the Welch mean test cannot. "
        "Report both; do not summarise them as a single verdict."
    )

if vol_crush.mean() < 0 and p_crush < sig_level:
    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
else:
    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")

if r_vix is not None and p_vix < sig_level:
    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
else:
    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")

for c in conclusions:
    print(f"  • {c}")

print(f"\n  Practical implication:")
print(f"    → Entry VIX regime is the larger and more reliably measured effect "
      f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
      f"so it is not established either way")
print(f"    → Non-significance of a mean test is not evidence of no effect")

# ============================================================
# 9b. Correction audit: every published number, before vs after
# ============================================================
# A mean can sit still while the median and the win rate move underneath it,
# so no claim is judged on its mean alone. Each item carries mean / median /
# win rate / n / significance, and the flip test looks at all of them.
print(f"\n{'=' * 60}")
print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
print("=" * 60)

PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
if not PROXY_PATH.exists():
    raise FileNotFoundError(
        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
        "only record of what the published article claimed. Do not regenerate it."
    )
proxy = json.loads(PROXY_PATH.read_text())


def win_rate(sample, reference):
    """Share of `sample` above the median of `reference` (0.5 under the null)."""
    ref_med = float(np.median(reference))
    return float(np.mean(np.asarray(sample) > ref_med))


# The proxy run only ever reported means, and a mean can hold still while the
# median and the win rate move underneath it. Rather than leave the before-side
# of those two columns null -- which would make the comparison unable to detect
# exactly the failure it is looking for -- rebuild the proxy-era distributions
# from the ARCHIVED per-event data. The dates come out of the archive, so this
# reconstructs history without reintroducing a proxy calendar generator.
proxy_events = proxy["event_data"]
proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])

# The archive holds the proxy run's ANALYSED events, which is not the same as
# its NFP sessions: the proxy also had a January-2005 event that its own
# window-buffer dropped, and leaving that day in the proxy control group is the
# identical leak just repaired on the official side (Codex v3 round-2 BLOCKER 1).
# Reconstructing it needs the first-Friday rule for exactly the months the
# archive does not cover. That is legitimate here and only here: the audit's job
# IS to reconstruct what the superseded run did. It is not reintroduced as a
# data source -- every analysed date still comes from the archive.
_archive_months = {d.strftime("%Y-%m") for d in proxy_event_dates}
_sample_months = [
    p.strftime("%Y-%m")
    for p in pd.period_range(start=pd.Timestamp(SAMPLE_START), end=pd.Timestamp(SAMPLE_END), freq="M")
]
_proxy_extra_sessions = []
for _m in _sample_months:
    if _m in _archive_months:
        continue
    _y, _mm = int(_m[:4]), int(_m[5:])
    _first = pd.Timestamp(year=_y, month=_mm, day=1)
    _ff = _first + pd.Timedelta(days=(4 - _first.weekday()) % 7)   # first Friday
    _cand = trading_dates[(trading_dates >= _ff) & (trading_dates <= _ff + pd.Timedelta(days=3))]
    if len(_cand):
        _proxy_extra_sessions.append(_cand[0])

proxy_all_sessions = set(proxy_event_dates) | set(_proxy_extra_sessions)
# The reconstruction must only ADD window-dropped months, never move an analysed
# one; and the months it adds must be exactly those the archive is missing.
if not set(proxy_event_dates) <= proxy_all_sessions:
    raise AssertionError("proxy session reconstruction dropped an archived event")
if len(proxy_all_sessions) != len(proxy_event_dates) + len(_proxy_extra_sessions):
    raise AssertionError("proxy session reconstruction collided with an archived event")
proxy_non_nfp = spy[~spy.index.isin(proxy_all_sessions)]
proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values

# Two proxy control groups, deliberately, because they answer different questions:
#   _archive  -- excludes only the archive's ANALYSED events. Reproduces the
#                published proxy-era means, which is how we verify the
#                reconstruction is reading the archive correctly.
#   (above)   -- also excludes the proxy's window-dropped session. Leak-free, so
#                it is what the before/after comparison uses.
# Keeping only the first would carry the leak into the audit; keeping only the
# second would silently discard the faithfulness check.
proxy_non_nfp_archive = spy[~spy.index.isin(set(proxy_event_dates))]
proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
_leak_sessions = sorted(str(d.date()) for d in _proxy_extra_sessions)
if len(proxy_non_nfp_archive) - len(proxy_non_nfp) != len(_proxy_extra_sessions):
    raise AssertionError("proxy control groups differ by something other than the reconstructed sessions")

# The proxy calendar was all-Friday by construction, but 15 of its 254 events
# mapped to a Monday because the first Friday was a market holiday. So the
# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
# rebuild the proxy side under the SAME estimand the corrected run uses
# (Friday events only) rather than comparing a mixed `before` against a
# restricted `after` and calling the difference a correction effect.
_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())

# All-days comparison on the leak-free proxy control, so the `before` column of
# that audit item is one estimand throughout rather than a mixture.
_p_t_all, _p_p_all = stats.ttest_ind(proxy_nfp_abs, proxy_non_nfp_abs, equal_var=False)
proxy_ratio_all_clean = float(proxy_nfp_abs.mean() / proxy_non_nfp_abs.mean())

_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
                       for e in proxy_events])
_p_thr = proxy["regime_analysis"]["vix_median_split"]
proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]

# Sanity: the rebuilt means must reproduce the archived means, otherwise the
# reconstruction is wrong and its medians cannot be trusted either. The baseline
# is checked against the ARCHIVE'S control definition -- the leak-free one is a
# deliberate departure from what was published, so holding it to the published
# value would just re-import the leak.
for _label, _rebuilt, _archived in (
    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
):
    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
        raise AssertionError(
            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
            f"vs archived {_archived:.8f}. Refusing to report medians derived "
            "from a reconstruction that cannot reproduce the archived means."
        )
print("  proxy-era distributions reconstructed from archive (means reproduce)")
print(f"  proxy control group additionally excludes {len(_proxy_extra_sessions)} "
      f"window-dropped NFP session(s): {_leak_sessions}")

audit_items = {}


def record(key, label, before, after, note=""):
    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}


# --- 1.10x : NFP vs all non-NFP days ---
record(
    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
    {
        # EVERY field on this side uses the leak-free control group. Mixing an
        # archive-derived mean/p with a leak-free median/win-rate would make a
        # single `before` object that is not any one estimand (Codex v3 round-3
        # finding 3); the as-published values are nested instead.
        "mean_ratio": proxy_ratio_all_clean,
        "nfp_mean": float(proxy_nfp_abs.mean()),
        "baseline_mean": float(proxy_non_nfp_abs.mean()),
        "p_value": float(_p_p_all),
        "significant_5pct": bool(_p_p_all < 0.05),
        "n": int(len(proxy_nfp_abs)),
        "n_control": int(len(proxy_non_nfp_abs)),
        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
        "as_published": {
            "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
            "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
            "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
            "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
            "n_control": int(len(proxy_non_nfp_abs_archive)),
            "note": (
                "what the proxy run published. Its control group still contained the "
                "proxy's own window-dropped NFP session, so it is kept for the record "
                "but is not the like-for-like comparison."
            ),
        },
    },
    {
        "mean_ratio": vol_ratio_all,
        "nfp_mean": float(nfp_abs_returns.mean()),
        "baseline_mean": baseline_abs_return,
        "p_value": float(p_val_all),
        "significant_5pct": bool(p_val_all < 0.05),
        "n": int(len(df)),
        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
    },
    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
         "per-event data, not from the proxy run's own output (it only reported means).",
)

# --- 1.17x : NFP vs Friday-only baseline ---
record(
    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
    {
        # Same estimand as the `after` column: Friday events only.
        "mean_ratio": proxy_ratio_fri_restricted,
        "p_value": float(_p_p_fri),
        "significant_5pct": bool(_p_p_fri < 0.05),
        "n": int(len(proxy_nfp_friday_abs)),
        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
        "n_control_friday": int(len(proxy_fri_abs)),
        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
        "as_published_mixed_weekday": {
            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
            "n": proxy["sample"]["total_nfp_events"],
            "note": (
                "what the proxy run actually published: all 254 events (239 Friday, "
                "15 Monday) against non-NFP Fridays. This is the number the article "
                "quoted, so it is kept, but it is NOT the like-for-like comparison "
                "against the corrected column."
            ),
        },
    },
    {
        "mean_ratio": vol_ratio_fri,
        "p_value": float(p_val_fri),
        "significant_5pct": bool(p_val_fri < 0.05),
        "n": int(len(nfp_friday_abs)),
        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
        "diagnostic_mixed_weekday": {
            "mean_ratio": vol_ratio_fri_mixed,
            "p_value": float(p_val_fri_mixed),
            "significant_5pct": bool(p_val_fri_mixed < 0.05),
            "n": int(len(df)),
            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
        },
    },
    note="Two things changed here and they are separated rather than conflated. "
         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
         "event group is a weekday mixture while the control group is pure "
         "Friday, so the test now restricts the event group to Friday releases. "
         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
         "simply never noticed. Both columns above therefore use the SAME "
         "restricted estimand so the delta is attributable to the dates alone; "
         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
         "(after) hold the old estimand on each side for reference.",
)

# --- 2.17x : high-VIX vs low-VIX regime ---
proxy_reg = proxy["regime_analysis"]
record(
    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
    {
        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
        "n_high": proxy_reg["n_high"],
        "n_low": proxy_reg["n_low"],
        "p_value": proxy_reg["p_value"],
        "significant_5pct": proxy_reg["p_value"] < 0.05,
        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
    },
    {
        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
        "high_mean": float(high_vix.mean()),
        "low_mean": float(low_vix.mean()),
        "n_high": int(len(high_vix)),
        "n_low": int(len(low_vix)),
        "p_value": float(p_regime),
        "significant_5pct": bool(p_regime < 0.05),
        "median_ratio": float(high_vix.median() / low_vix.median()),
        "win_rate": win_rate(high_vix.values, low_vix.values),
    },
)

# --- 0.45 : pre-event VIX correlation ---
proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
record(
    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
    {
        "pearson_r": proxy_e["pearson_r"],
        "pearson_p": proxy_e["pearson_p"],
        "spearman_rho": proxy_e["spearman_rho"],
        "spearman_p": proxy_e["spearman_p"],
        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
        "n": proxy["sample"]["total_nfp_events"],
        "significant_5pct": proxy_e["pearson_p"] < 0.05,
    },
    {
        "pearson_r": float(r_vix),
        "pearson_p": float(p_vix),
        "spearman_rho": float(rho_vix),
        "spearman_p": float(p_rho_vix),
        "slope_pct_per_vix_pt": float(slope) * 100,
        "n": int(len(vix_valid)),
        "significant_5pct": bool(p_vix < 0.05),
    },
)

# --- 16.71 : the VIX median that splits the regimes ---
# The article uses this threshold to place a specific date (2026-07-01 VIX
# 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
# worked example inverts, so it is audited as a claim in its own right.
proxy_thr = proxy_reg["vix_median_split"]
record(
    "vix_median_threshold", "VIX median split (article: 16.71)",
    {
        "threshold": proxy_thr,
        "n": proxy["sample"]["total_nfp_events"],
        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
    },
    {
        "threshold": float(vix_median),
        "n": int(df["pre_vix"].notna().sum()),
        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
    },
)

# --- 254 : the sample itself ---
proxy_dates = {r["date"] for r in proxy["event_data"]}
new_dates = {r["date"] for r in results}
record(
    "sample", "NFP event sample (article: 254 events)",
    {
        "n": proxy["sample"]["total_nfp_events"],
        "date_range": proxy["sample"]["date_range"],
        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
    },
    {
        "n": int(len(df)),
        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
        "non_nfp_trading_days": int(non_nfp_mask.sum()),
        "dates_in_common": len(proxy_dates & new_dates),
        "proxy_only_dates": sorted(proxy_dates - new_dates),
        "official_only_dates": sorted(new_dates - proxy_dates),
    },
    note="Equal counts do not mean equal samples -- check dates_in_common.",
)


def verdict_for(key):
    """Flip test: significance change, sign change, or a >10% move in the headline."""
    b, a = audit_items[key]["before"], audit_items[key]["after"]
    reasons = []
    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
            reasons.append(
                "significance flipped "
                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
                f"{'sig' if a['significant_5pct'] else 'NS'})"
            )
    # The mean is not trusted on its own: the median and the win rate are
    # checked independently, because the failure mode this audit exists to
    # catch is a stable mean sitting on top of a moved distribution.
    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
        if field in b and field in a and b[field] and a[field]:
            rel = abs(a[field] - b[field]) / abs(b[field])
            if rel > 0.10:
                reasons.append(f"{field} moved {rel * 100:.1f}%")
    if b.get("win_rate") and a.get("win_rate"):
        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
            reasons.append(
                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
            )
    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
        reasons.append("the article's worked example changes regime")
    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons


print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
for key, item in audit_items.items():
    v, reasons = verdict_for(key)
    item["verdict"], item["verdict_reasons"] = v, reasons
    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
                     if f in item["before"]), None)
    bf = item["before"].get(headline)
    af = item["after"].get(headline)
    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
    for r in reasons:
        print(f"      - {r}")

n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")

# ============================================================
# 10. Save results
# ============================================================
print("\n[6/6] Saving results...")

output = {
    "experiment_id": "K528",
    "title": "NFP Event Study on SPY Volatility",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
    "event_date_source": {
        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
        "accessor": "volpred.data.event_dates.nfp_release_dates",
        "fallback": "none - the run raises if the calendar is unreachable",
        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
    },
    "sample": {
        "total_nfp_events": len(df),
        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
        "non_nfp_trading_days": int(non_nfp_mask.sum()),
        "friday_baseline_days": int(friday_mask.sum()),
        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
        "event_mapping_audit": mapping_audit,
        "calendar_completeness": calendar_completeness,
        # Recorded independently so the control-group invariant
        # (controls == total - mapped NFP sessions) is checkable rather than an
        # algebraic identity between two numbers derived from each other.
        "total_trading_days": int(len(spy)),
        "control_group_excludes_all_nfp_sessions": bool(
            len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask])) == 0
        ),
    },
    "main_results": {
        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
        "non_nfp_avg_abs_return": baseline_abs_return,
        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
        "friday_baseline_abs_return": friday_baseline,
        "vol_ratio_vs_all": vol_ratio_all,
        "vol_ratio_vs_friday": vol_ratio_fri,
    },
    "statistical_tests": {
        "A_nfp_vs_all": {
            "test": "Welch t-test",
            "t_stat": float(t_stat_all),
            "p_value": float(p_val_all),
            "significant_5pct": bool(p_val_all < 0.05),
        },
        "B_nfp_vs_friday": {
            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
            "estimand": (
                "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event "
                "group is restricted to NFP releases that trade on a Friday, and the "
                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
                "than compared against a pure-Friday control group."
            ),
            "claim_scope": (
                "This identifies the effect of an NFP release ON A FRIDAY. It does not "
                "license a statement about NFP releases in general -- the excluded "
                "non-Friday events are quieter, so the restriction raises the ratio "
                "relative to the mixed-weekday spec. Any prose quoting this number must "
                "say 'Friday NFP', not 'NFP'."
            ),
            "restriction_is_not_neutral": {
                "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
                "friday_mean_abs_return": float(nfp_friday_abs.mean()),
                "excluded_are_quieter_by_pct": (
                    float((nfp_friday_abs.mean() - nfp_nonfriday_abs.mean()) / nfp_friday_abs.mean() * 100)
                    if len(nfp_nonfriday_abs) else None
                ),
            },
            "n_event": int(len(nfp_friday_abs)),
            "n_control": int(len(friday_non_nfp_abs)),
            "vol_ratio": vol_ratio_fri,
            "t_stat": float(t_stat_fri),
            "p_value": float(p_val_fri),
            "significant_5pct": bool(p_val_fri < 0.05),
            "excluded_non_friday_events": {
                "n": int(len(nfp_nonfriday_abs)),
                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
            },
        },
        "B_diagnostic_mixed_weekday": {
            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
            "status": "DIAGNOSTIC ONLY - do not quote",
            "why_not_a_headline": (
                "this is the pre-correction specification: a weekday-mixed event "
                "group against a pure-Friday control group, so the p-value absorbs "
                "any Friday-vs-other-weekday volatility difference. Retained solely "
                "so the correction audit can show what the contaminated estimand was "
                "worth (k528 Codex v2 finding 5)."
            ),
            "vol_ratio": vol_ratio_fri_mixed,
            "t_stat": float(t_stat_fri_mixed),
            "p_value": float(p_val_fri_mixed),
            "significant_5pct": bool(p_val_fri_mixed < 0.05),
        },
        "C_wilcoxon": {
            "test": "Mann-Whitney U (one-sided)",
            "u_stat": float(u_stat),
            "p_value": float(p_val_wilcox),
            "significant_5pct": bool(p_val_wilcox < 0.05),
        },
        "D_vol_crush": {
            "test": "One-sample t-test (post-pre diff)",
            "pre_avg": float(df["pre_avg_abs_return"].mean()),
            "post_avg": float(df["post_avg_abs_return"].mean()),
            "diff": float(vol_crush.mean()),
            "t_stat": float(t_crush),
            "p_value": float(p_crush),
            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
        },
        "E_vix_predictive": {
            "test": "Pearson + Spearman correlation",
            "pearson_r": float(r_vix) if r_vix else None,
            "pearson_p": float(p_vix) if p_vix else None,
            "spearman_rho": float(rho_vix) if rho_vix else None,
            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
            "slope": float(slope) if slope else None,
            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
        },
        "F_vix_buildup": {
            "test": "One-sample t-test (T-5 to T-1 VIX change)",
            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
            "t_stat": float(t_buildup) if t_buildup else None,
            "p_value": float(p_buildup) if p_buildup else None,
            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
        },
    },
    "seasonal_analysis": monthly_stats,
    "regime_analysis": {
        "vix_median_split": float(vix_median),
        "high_vix_nfp_abs_return": float(high_vix.mean()),
        "low_vix_nfp_abs_return": float(low_vix.mean()),
        "n_high": int(len(high_vix)),
        "n_low": int(len(low_vix)),
        "t_stat": float(t_regime),
        "p_value": float(p_regime),
    },
    "time_trend": {
        "first_half_abs_return": float(first_half.mean()),
        "second_half_abs_return": float(second_half.mean()),
        "t_stat": float(t_trend),
        "p_value": float(p_trend),
    },
    "directional_bias": {
        "positive_count": int(pos_returns),
        "negative_count": int(neg_returns),
        "total": int(pos_returns + neg_returns),
        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
        "binomial_p": binom_p,
    },
    "intraday_range": {
        "nfp_avg_range": float(nfp_range),
        "non_nfp_avg_range": float(non_nfp_range),
        "range_ratio": float(range_ratio),
    },
    "volume": {
        "avg_volume_ratio": float(vol_ratio_data.mean()),
        "pct_above_avg": float((vol_ratio_data > 1).mean()),
    },
    "april_nfp": {
        "n": int(len(april_nfp)),
        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
        "avg_signed_return": float(april_nfp["event_return"].mean()),
        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
    },
    "conclusions": conclusions,
    "practical_implication": (
        f"The VIX-regime gap is the LARGEST NUMBER in this study, which is not the "
        f"same as being the dominant effect and is not a causal statement: "
        f"{high_vix.mean()/low_vix.mean():.2f}x between high- and low-VIX NFP days "
        f"(p={p_regime:.4g}). The NFP-day effect itself is smaller and the tests do not "
        f"agree on it -- the Welch mean-difference test against all non-NFP days gives "
        f"{vol_ratio_all:.2f}x (p={p_val_all:.4f}) while the one-sided Mann-Whitney gives "
        f"p={p_val_wilcox:.5f}. Report both. A mean test that does not reject is not "
        "evidence that the effect is zero, and it does not license the claim that the "
        "event 'is not NFP itself'. The two magnitudes are NOT formally compared: "
        "different samples, different control groups, no test of whether the regime gap "
        "exceeds the NFP gap, and the VIX split is an in-sample median. Read them side "
        "by side, not as a ranking."
    ),
    "claim_scope_note": (
        "Every significance statement in this artifact is scoped to its own test. "
        "The superseded run summarised these as 'insignificant across all tests', "
        "which contradicted the one-sided Mann-Whitney result in the same file "
        "(k528 Codex v2 finding 6)."
    ),
    "references": [
        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
    ],
    "event_data": results,  # full per-event data
}

out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
write_json_atomic(out_path, output)

print(f"  Saved to: {out_path}")

# The correction audit is written separately: it is the artifact the article
# correction is justified against, and it must stay readable without wading
# through 254 events of per-day data.
audit_out = {
    "experiment_id": "K528",
    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "before_source": PROXY_PATH.name,
    "after_source": out_path.name,
    "event_date_source": output["event_date_source"],
    "calendar_diff": {
        "proxy_only_dates": sorted(proxy_dates - new_dates),
        "official_only_dates": sorted(new_dates - proxy_dates),
        "dates_in_common": len(proxy_dates & new_dates),
        "n_proxy": len(proxy_dates),
        "n_official": len(new_dates),
        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
    },
    "win_rate_definition": (
        "share of the sample exceeding the MEDIAN of its comparison group; "
        "0.5 under the null"
    ),
    "items": audit_items,
    "n_claims_flipped": n_flipped,
    "n_claims_audited": len(audit_items),
    "article_correction": {
        "article_id": "mile_35eef830",
        "status": "pending - filled in by the correction step",
        "replacements": None,
    },
}
audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
write_json_atomic(audit_path, audit_out)
print(f"  Saved to: {audit_path}")
print("\nDone!")
