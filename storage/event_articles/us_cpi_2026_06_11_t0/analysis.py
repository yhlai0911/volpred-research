"""
US CPI 2026-06 T+0 event article evidence pack.
ERRATA RERUN 2026-07-19 — K1442 `related_event_date_audit` follow-up.

This is a rerun of the original evidence pack, not a new study. The original was
never published, so there is no live article to correct; what was wrong was the
internal evidence and prose.

What was wrong
--------------
The event-day window (2026-06-09 → 2026-06-11) was correct. The HISTORICAL
COMPARISON was not: the CPI release calendar was hard-coded from a "CPI comes out
around the 13th" proxy. Against the official FRED/ALFRED calendar (release id 10),
7 of the 14 hard-coded entries are not CPI release dates:

    2025-10-15 → 2025-10-24   release delayed by the shutdown
    2025-11-13 → (none)       PHANTOM: BLS published no CPI in November 2025
    2025-12-10 → 2025-12-18
    2026-01-14 → 2026-01-13
    2026-02-12 → 2026-02-13
    2026-03-12 → 2026-03-11
    2026-05-13 → 2026-05-12

The phantom matters most. 2025-11-13 was scored as a CPI reaction day and carried
a +14.22% VIX move; no CPI was released that month at all, because the October-2025
reference month was cancelled during the shutdown. A monthly heuristic cannot
represent a cancelled release, which is why the calendar has to be data, not a rule.

The proxy never raised and never produced a NaN. It produced a complete, plausible,
wrong table — and the wrongness ran in one direction: the three moves the original
reported as larger than 2026-06-10 were ALL on non-event days
(2026-02-12 +17.96%, 2025-11-13 +14.22% (phantom), 2026-03-12 +12.63%). Remove the
non-events and 2026-06-10's +11.827% is the LARGEST of the 13 official releases in
the sample, not the fourth. The original's central comparative claim inverted.

Sample falls from 14 to 13: the fabricated November release is gone, and the other
six entries move to their official dates rather than being dropped.

Method deltas (disclosed, not waved off as "nothing else changed")
-----------------------------------------------------------------
 1. Release dates come from `volpred.data.event_dates.cpi_release_dates`
    (FRED/ALFRED release id 10), fail-closed. No proxy, no fallback.
 2. Non-session rows are dropped against the XNYS calendar, and a missing,
    duplicated or out-of-order session raises. yfinance returns a ^VIX quote for
    Memorial Day 2026-05-25, when the exchange was shut. Every reaction here is
    row arithmetic (`iloc[pos-1]` → `iloc[pos]`), which assumes the index IS the
    session list. Verified inert on this data — 2026-05-25 neighbours no official
    release date — but it is a behavioural change, so it is listed as one.
 3. The event window is derived from the official release date's position in the
    session index (t-1, t, t+1) instead of three hard-coded dates. On this data
    the derived window is identical to the original's.
 4. Output path is `Path(__file__).resolve().parent`. The original hard-coded
    `/Users/yhlai0911/Desktop/volpred-research/...`, a root the repo moved out of.
    Correction to the task framing: that is an unportable ABSOLUTE path, not a
    cwd-relative one — combined with `mkdir(parents=True)` it would silently
    resurrect a stale Desktop tree and write there, wherever it was run from.
    Different failure mode, same fix.

Date convention (stated explicitly)
-----------------------------------
  - Event date t = official BLS news-release date (08:30 ET).
  - Reaction = t-1 close → t close. The 08:30 release precedes the 09:30 open, so
    measuring the same session is not lookahead.
  - The event window is TRADING days (t-1, t, t+1), not calendar days.
  - "T+0" in the article slot name means the piece was written on the release day.
    The directory is named `us_cpi_2026_06_11_t0`, but the official June-2026
    release date was 2026-06-10. The slot label is off by one day; the analysis
    and the article body both use 2026-06-10. The directory name is left alone
    because it is referenced by details.json and the task registry.

The data window is deliberately left at the original run's (2025-05-01 →
2026-06-13) so this rerun isolates the date fix rather than confounding it with
fresher data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import exchange_calendars as xcals  # noqa: E402
import yfinance as yf  # noqa: E402

from volpred.data.event_dates import cpi_release_dates  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

START = "2025-05-01"
END = "2026-06-13"  # yfinance end is exclusive; last session = 2026-06-12
TARGET_MONTH = (2026, 6)  # the release this article covers, resolved via the calendar

# The hard-coded calendar this rerun exists to remove. Kept only so the errata
# table is recomputed from the real thing rather than restated from prose.
LEGACY_HARDCODED_DATES = [
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    "2025-10-15", "2025-11-13", "2025-12-10", "2026-01-14", "2026-02-12",
    "2026-03-12", "2026-04-10", "2026-05-13", "2026-06-10",
]

BLS_SOURCE = {
    "release": "BLS Consumer Price Index Summary, 2026-06-10 (USDL-26-0824)",
    "headline_mom_pct": 0.5,
    "headline_yoy_pct": 4.2,
    "core_mom_pct": 0.2,
    "core_yoy_pct": 2.9,
    "energy_mom_pct": 3.9,
    "energy_yoy_pct": 23.5,
    "gasoline_mom_pct": 7.0,
    "gasoline_yoy_pct": 40.5,
}

CONSENSUS = {
    "headline_yoy_pct": 4.2,
    "core_yoy_pct": 2.9,
    "core_mom_pct": 0.3,
    "source": "WSJ live coverage / MarketWatch snippets retrieved 2026-06-12",
}


def load_sessions(ticker: str, start: str, end: str) -> pd.Series:
    """Download `ticker` and assert the result IS the XNYS session list for [start, end).

    Every reaction below is row arithmetic, which silently assumes the index is the
    trading calendar. The two ways that breaks are not symmetric:

      - An EXTRA non-session row is an upstream quirk (yfinance quotes ^VIX for
        Memorial Day 2026-05-25). Dropped, loudly.
      - A MISSING, duplicated or out-of-order session silently corrupts every
        offset: "the row before" stops meaning "the previous session". That raises.

    Expected sessions come from the REQUESTED window, not from the data's own first
    and last row, so a missing leading or trailing session cannot define itself away.
    """
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    s = raw["Close"].squeeze()
    s.name = ticker

    expected = xcals.get_calendar("XNYS").sessions_in_range(
        pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1)
    )
    expected = pd.DatetimeIndex([d.tz_localize(None) if d.tz else d for d in expected])
    idx = pd.DatetimeIndex(s.index)

    dupes = idx[idx.duplicated()]
    if len(dupes):
        raise RuntimeError(f"{ticker}: duplicated rows {[str(d.date()) for d in dupes]}")

    junk = idx.difference(expected)
    if len(junk):
        print(f"  WARNING: {ticker} carried {len(junk)} non-session row(s), dropped: "
              f"{[str(d.date()) for d in junk]}")
        s = s[~idx.isin(junk)]

    got = pd.DatetimeIndex(s.index)
    missing = expected.difference(got)
    if len(missing):
        raise RuntimeError(
            f"{ticker}: {len(missing)} XNYS session(s) absent from the quote series "
            f"({[str(d.date()) for d in missing[:5]]}). Every offset here is row "
            f"arithmetic; it would walk straight past the hole. Refusing to run."
        )
    if not got.equals(expected):
        raise RuntimeError(f"{ticker}: index is not the XNYS session list in order")
    return s.astype(float)


def official_cpi_dates(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Official CPI release dates inside the sample, fail-closed.

    A release that is not a trading session would make "the row before" ambiguous.
    Rather than snap it somewhere plausible, refuse: this whole errata exists
    because a plausible guess is indistinguishable from a correct answer.
    """
    dates = cpi_release_dates(START, END)
    dates = dates[(dates >= sessions[0]) & (dates <= sessions[-1])]
    if len(dates) == 0:
        raise RuntimeError("official CPI calendar returned no dates inside the sample")
    off_session = [d for d in dates if d not in sessions]
    if off_session:
        raise RuntimeError(
            f"official release(s) {[str(d.date()) for d in off_session]} are not XNYS "
            f"sessions; refusing to guess which day absorbed the release"
        )
    return dates


def resolve_target_release(dates: pd.DatetimeIndex) -> pd.Timestamp:
    """The release this article covers, taken from the calendar rather than typed in.

    If the target month carries no official release, this raises instead of falling
    back to a nearby date — that is exactly the phantom-event failure (2025-11-13)
    this rerun exists to remove.
    """
    year, month = TARGET_MONTH
    hits = [d for d in dates if (d.year, d.month) == (year, month)]
    if len(hits) != 1:
        raise RuntimeError(
            f"expected exactly 1 official CPI release in {year}-{month:02d}, got "
            f"{len(hits)}: {[str(d.date()) for d in hits]}"
        )
    return hits[0]


def _pct(a: float, b: float) -> float:
    return float((b - a) / a * 100.0)


def reaction_pct(series: pd.Series, day: pd.Timestamp) -> tuple[float, float, float]:
    """(prev close, close, % change) for the session `day` — t-1 → t.

    `load_sessions` guarantees the INDEX is the session list, which is what makes
    `iloc[pos-1]` mean "the previous session". It says nothing about the VALUES,
    so the two ways a structurally-valid row still poisons a ranking are checked
    here: a NaN/inf quote, and a zero prior close that would divide to infinity.
    """
    pos = series.index.get_loc(day)
    if pos == 0:
        raise RuntimeError(f"{day.date()} is the first session; no t-1 close exists")
    prev, curr = float(series.iloc[pos - 1]), float(series.iloc[pos])
    if not (np.isfinite(prev) and np.isfinite(curr)):
        raise RuntimeError(
            f"{day.date()}: non-finite close (t-1={prev}, t={curr}); a NaN would "
            f"sort silently into the ranking rather than raising"
        )
    if prev == 0:
        raise RuntimeError(f"{day.date()}: prior close is zero; percentage change undefined")
    return prev, curr, _pct(prev, curr)


def build_errata(official: pd.DatetimeIndex) -> list[dict]:
    """Recompute the legacy-vs-official diff instead of restating the audit's prose."""
    official_set = {d.date() for d in official}
    by_month = {(d.year, d.month): d for d in official}
    rows = []
    for raw in LEGACY_HARDCODED_DATES:
        old = pd.Timestamp(raw)
        if old.date() in official_set:
            continue
        match = by_month.get((old.year, old.month))
        rows.append({
            "old": raw,
            "new": None if match is None else str(match.date()),
            "kind": "phantom" if match is None else "misdated",
            "note": (
                f"BLS published no CPI in {old.year}-{old.month:02d}; the "
                f"{old.year}-{old.month - 1:02d} reference month was cancelled during "
                f"the shutdown, so this release never happened"
                if match is None else
                f"hard-coded date is not a release date; official release that month "
                f"was {match.date()}"
            ),
        })
    return rows


def main() -> None:
    vix = load_sessions("^VIX", START, END)
    vix9d = load_sessions("^VIX9D", START, END)
    spy = load_sessions("SPY", START, END)

    sessions = pd.DatetimeIndex(vix.index)
    official = official_cpi_dates(sessions)
    release = resolve_target_release(official)

    print(f"\nOfficial CPI releases in sample: {len(official)}")
    for d in official:
        print(f"  {d.date()}")
    print(f"Target release ({TARGET_MONTH[0]}-{TARGET_MONTH[1]:02d}): {release.date()}")

    # ── Event window: t-1, t, t+1 in TRADING days, taken from the session index ──
    pos = sessions.get_loc(release)
    if pos == 0 or pos + 1 >= len(sessions):
        raise RuntimeError(f"release {release.date()} has no full t-1..t+1 window in sample")
    window = sessions[pos - 1: pos + 2]

    event_window = pd.DataFrame(
        {"VIX": vix.loc[window], "VIX9D": vix9d.loc[window], "SPY": spy.loc[window]}
    )

    reaction_rows = [
        {
            "date": curr.strftime("%Y-%m-%d"),
            "VIX_pct": _pct(event_window.loc[prev, "VIX"], event_window.loc[curr, "VIX"]),
            "VIX9D_pct": _pct(event_window.loc[prev, "VIX9D"], event_window.loc[curr, "VIX9D"]),
            "SPY_pct": _pct(event_window.loc[prev, "SPY"], event_window.loc[curr, "SPY"]),
        }
        for prev, curr in zip(window[:-1], window[1:])
    ]

    # ── Historical comparison, official calendar only ──
    cpi_vix_changes = []
    for day in official:
        prev, curr, pct = reaction_pct(vix, day)
        cpi_vix_changes.append({
            "date": day.strftime("%Y-%m-%d"),
            "vix_prev": prev,
            "vix_close": curr,
            "vix_pct": pct,
        })

    ranked = sorted(cpi_vix_changes, key=lambda x: x["vix_pct"], reverse=True)
    rank_map = {row["date"]: i + 1 for i, row in enumerate(ranked)}
    release_key = release.strftime("%Y-%m-%d")
    current = next(r for r in cpi_vix_changes if r["date"] == release_key)
    recent5 = cpi_vix_changes[-5:]
    pcts = np.array([r["vix_pct"] for r in cpi_vix_changes], dtype=float)

    errata = build_errata(official)

    evidence = {
        "event": f"US CPI {release_key}",
        "article_slot": "T+0",
        "errata": {
            "rerun_date": "2026-07-19",
            "reason": "K1442 related_event_date_audit: hard-coded CPI calendar",
            "published": False,
            "dates_fixed": errata,
            "legacy_sample_n": len(LEGACY_HARDCODED_DATES),
            "official_sample_n": len(cpi_vix_changes),
            "legacy_rank_claim": 4,
            "official_rank": rank_map[release_key],
        },
        "sources": {
            "bls": BLS_SOURCE,
            "consensus": CONSENSUS,
            "market_data": f"yfinance (^VIX, ^VIX9D, SPY), {START} to {END} (exclusive)",
            "release_calendar": "FRED/ALFRED release id 10 via volpred.data.event_dates.cpi_release_dates",
        },
        "official_cpi_release_dates": [d.strftime("%Y-%m-%d") for d in official],
        "event_window_closes": {
            idx.strftime("%Y-%m-%d"): {
                "VIX": round(float(row["VIX"]), 2),
                "VIX9D": round(float(row["VIX9D"]), 2),
                "SPY": round(float(row["SPY"]), 2),
            }
            for idx, row in event_window.iterrows()
        },
        "day_over_day_reaction_pct": reaction_rows,
        "headline_vs_consensus": {
            "headline_yoy_surprise_pctpt": round(BLS_SOURCE["headline_yoy_pct"] - CONSENSUS["headline_yoy_pct"], 3),
            "core_yoy_surprise_pctpt": round(BLS_SOURCE["core_yoy_pct"] - CONSENSUS["core_yoy_pct"], 3),
            "core_mom_surprise_pctpt": round(BLS_SOURCE["core_mom_pct"] - CONSENSUS["core_mom_pct"], 3),
        },
        "release_day_vix_rank": {
            "date": release_key,
            "vix_pct": round(current["vix_pct"], 3),
            "rank_among_official_cpi_days": rank_map[release_key],
            "sample_n": len(cpi_vix_changes),
        },
        "official_cpi_vix_moves_ranked": [
            {"rank": i + 1, "date": r["date"], "vix_pct": round(r["vix_pct"], 3)}
            for i, r in enumerate(ranked)
        ],
        "official_cpi_vix_summary": {
            "mean_pct": round(float(pcts.mean()), 3),
            "median_pct": round(float(np.median(pcts)), 3),
            "n_positive": int((pcts > 0).sum()),
            "n": int(pcts.size),
        },
        "recent5_cpi_vix_moves": recent5,
    }

    (OUT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    labels = [f"{window[1].month}/{window[1].day} CPI 發布日", f"{window[2].month}/{window[2].day} 隔日"]

    # Figure 1: day-over-day reaction bars (event window only)
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    x = np.arange(2)
    width = 0.22
    ax.bar(x - width, [reaction_rows[0]["VIX_pct"], reaction_rows[1]["VIX_pct"]], width, label="VIX", color="#263238")
    ax.bar(x, [reaction_rows[0]["VIX9D_pct"], reaction_rows[1]["VIX9D_pct"]], width, label="VIX9D", color="#c62828")
    ax.bar(x + width, [reaction_rows[0]["SPY_pct"], reaction_rows[1]["SPY_pct"]], width, label="SPY", color="#1565c0")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("日變動（%）", fontsize=11)
    ax.set_title("CPI 發布日先拉高波動，隔日大半吐回", fontsize=13, fontweight="bold")
    ax.legend()
    ax.yaxis.grid(True, alpha=0.25)
    fig.text(0.99, 0.01, "資料來源：BLS、yfinance；VolPred 自製分析", ha="right", va="bottom", fontsize=8, color="gray")
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig1_cpi_t0_reaction.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # Figure 2: indexed event window path (event window only)
    indexed = event_window / event_window.iloc[0] * 100.0
    fig2, ax2 = plt.subplots(figsize=(8.8, 5.2))
    ax2.plot(indexed.index, indexed["VIX"], marker="o", linewidth=2.0, color="#263238", label="VIX")
    ax2.plot(indexed.index, indexed["VIX9D"], marker="o", linewidth=2.0, color="#c62828", label="VIX9D")
    ax2.plot(indexed.index, indexed["SPY"], marker="o", linewidth=2.0, color="#1565c0", label="SPY")
    ax2.axhline(100, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.set_ylabel(f"{window[0].month}/{window[0].day} = 100", fontsize=11)
    ax2.set_title(f"{window[1].month}/{window[1].day} 的 CPI shock 沒有延續成第二天的 vol regime",
                  fontsize=13, fontweight="bold")
    ax2.legend()
    ax2.yaxis.grid(True, alpha=0.25)
    fig2.autofmt_xdate()
    fig2.text(0.99, 0.01, "資料來源：yfinance (^VIX, ^VIX9D, SPY)；VolPred 自製分析",
              ha="right", va="bottom", fontsize=8, color="gray")
    plt.tight_layout()
    fig2.savefig(OUT_DIR / "fig2_cpi_t0_event_window.png", dpi=160, bbox_inches="tight")
    plt.close(fig2)

    print(f"\n{release_key} VIX {current['vix_pct']:.3f}% — rank "
          f"{rank_map[release_key]} of {len(cpi_vix_changes)} official releases")
    print(f"errata rows: {len(errata)} "
          f"({sum(1 for e in errata if e['kind'] == 'phantom')} phantom)")


if __name__ == "__main__":
    main()
