"""
US CPI 2026-07-14 T-2 event article — evidence package.

Angle (a correction piece, per 研究誠實原則 §6):
  Our earlier CPI event studies hard-coded release dates from a "13th of month"
  calendar proxy (scripts/populate_upcoming_events.py::gen_us_cpi, fixed
  2026-07-12). Against the official BLS/ALFRED release calendar, 7 of the 13
  dates were wrong — including two days on which no CPI was published at all
  (Oct-2025 CPI was cancelled; Nov-2025 CPI slipped from Dec 10 to Dec 18).

  This script recomputes the CPI-day reaction of VIX and SPY under BOTH date
  sets and reports whether the conclusion survives.

Date source: ALFRED release dates, release_id=10 (CPI news release), fetched
live so the package is reproducible. https://alfred.stlouisfed.org/release/downloaddates?rid=10
Price source: yfinance (^VIX, SPY), auto_adjust=True.

Outputs: evidence.json, fig1_date_error.png, fig2_cpi_day_reaction.png
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from plot_style import apply_cjk_style

apply_cjk_style()

SEED = 20260712
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
START = "2024-06-01"
END = "2026-07-11"  # exclusive-ish; last fully closed trading day = 2026-07-10

# ── The date list actually used by our previously published CPI event studies ──
# Source: storage/event_articles/us_cpi_2026_06_11_t2/analysis.py:44-57 (hard-coded,
# no provenance). Reproduced verbatim so the comparison is auditable.
LEGACY_DATES = pd.to_datetime(
    [
        "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
        "2025-10-15", "2025-11-13", "2025-12-10", "2026-01-14", "2026-02-12",
        "2026-03-12", "2026-04-10", "2026-05-13",
    ]
)


def fetch_official_cpi_dates(start: str, end: str) -> pd.DatetimeIndex:
    """Official CPI news-release dates from ALFRED (release_id=10)."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        for cand in (".env.local", ".env"):
            p = Path(__file__).resolve().parents[3] / cand  # repo root
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.startswith("FRED_API_KEY"):
                        key = line.split("=", 1)[1].strip().strip("\"'")
                        break
            if key:
                break
    if not key:
        raise RuntimeError("FRED_API_KEY not found — cannot fetch official CPI release dates")

    r = requests.get(
        "https://api.stlouisfed.org/fred/release/dates",
        params={
            "release_id": 10,
            "api_key": key,
            "file_type": "json",
            "realtime_start": start,
            "realtime_end": end,
            "limit": 200,
            "sort_order": "asc",
        },
        timeout=30,
    )
    r.raise_for_status()
    dates = pd.to_datetime([d["date"] for d in r.json()["release_dates"]])
    # release_id=10 occasionally carries off-cycle entries (e.g. annual seasonal-factor
    # revisions). The monthly news release is one per calendar month; keep the last
    # entry per month, which is the CPI news release itself.
    s = pd.Series(dates, index=dates)
    monthly = s.groupby([dates.year, dates.month]).max()
    return pd.DatetimeIndex(sorted(monthly.values))


print("Fetching official CPI release dates from ALFRED...")
OFFICIAL_ALL = fetch_official_cpi_dates("2024-01-01", "2026-12-31")
# Restrict to the same window the legacy study covered (its first date onward)
OFFICIAL_DATES = OFFICIAL_ALL[
    (OFFICIAL_ALL >= LEGACY_DATES.min()) & (OFFICIAL_ALL <= pd.Timestamp("2026-07-10"))
]
print(f"  official (window of legacy study): {[str(d.date()) for d in OFFICIAL_DATES]}")

print("Downloading ^VIX, SPY...")
vix = yf.download("^VIX", start=START, end=END, auto_adjust=True, progress=False)["Close"].squeeze()
spy = yf.download("SPY", start=START, end=END, auto_adjust=True, progress=False)["Close"].squeeze()
vix.index = pd.to_datetime(vix.index).tz_localize(None)
spy.index = pd.to_datetime(spy.index).tz_localize(None)
# ^VIX and SPY calendars differ by a session or two (index holidays); intersect so
# every statistic below is computed on the same set of days.
common = vix.index.intersection(spy.index)
vix, spy = vix.loc[common], spy.loc[common]
print(f"  common calendar: {len(vix)} days {vix.index[0].date()}→{vix.index[-1].date()}")

vix_chg = vix.pct_change() * 100.0          # VIX % change, day t vs t-1
spy_ret = spy.pct_change() * 100.0          # SPY % return
spy_abs = spy_ret.abs()

trading_days = vix.index


def to_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Map each release date onto the trading day it lands on (exact match only).

    An exact-match requirement is the point of this exercise: a release date that
    is not a trading day, or that never happened, must NOT be silently snapped to
    a neighbouring session — that is precisely how the legacy list smuggled two
    non-events into the sample.
    """
    return pd.DatetimeIndex([d for d in dates if d in trading_days])


legacy_td = to_trading_days(LEGACY_DATES)
official_td = to_trading_days(OFFICIAL_DATES)

wrong = [str(d.date()) for d in LEGACY_DATES if d not in set(OFFICIAL_DATES)]
missed = [str(d.date()) for d in OFFICIAL_DATES if d not in set(LEGACY_DATES)]

# Days on which the legacy list claimed a CPI release but BLS published none at all
# (as opposed to "off by a day"). Determined by: no official release in that
# calendar month within ±10 days.
phantom = []
for d in LEGACY_DATES:
    near = [o for o in OFFICIAL_DATES if abs((o - d).days) <= 10]
    if not near:
        phantom.append(str(d.date()))

print(f"\nlegacy n={len(LEGACY_DATES)}  official n={len(OFFICIAL_DATES)}")
print(f"wrong dates in legacy list: {len(wrong)} → {wrong}")
print(f"phantom (no CPI within ±10d): {phantom}")


def reaction_stats(td: pd.DatetimeIndex, label: str) -> dict:
    """CPI-day reaction vs all other trading days."""
    mask = trading_days.isin(td)
    ev_vix = vix_chg[mask].dropna()
    ev_abs = spy_abs[mask].dropna()
    non_vix = vix_chg[~mask].dropna()
    non_abs = spy_abs[~mask].dropna()

    # Welch t-test (unequal variance) — event days vs non-event days
    t_vix, p_vix = stats.ttest_ind(ev_vix, non_vix, equal_var=False)
    t_abs, p_abs = stats.ttest_ind(ev_abs, non_abs, equal_var=False)

    out = {
        "label": label,
        "n_event_days": int(len(ev_vix)),
        "n_nonevent_days": int(len(non_vix)),
        "vix_pct_change_on_cpi_day": {
            "mean": round(float(ev_vix.mean()), 3),
            "median": round(float(ev_vix.median()), 3),
            "std": round(float(ev_vix.std(ddof=1)), 3),
            "min": round(float(ev_vix.min()), 3),
            "max": round(float(ev_vix.max()), 3),
        },
        "vix_pct_change_other_days_mean": round(float(non_vix.mean()), 3),
        "vix_welch_t": round(float(t_vix), 3),
        "vix_welch_p": round(float(p_vix), 4),
        "spy_abs_return_on_cpi_day_mean": round(float(ev_abs.mean()), 3),
        "spy_abs_return_other_days_mean": round(float(non_abs.mean()), 3),
        "spy_abs_welch_t": round(float(t_abs), 3),
        "spy_abs_welch_p": round(float(p_abs), 4),
        "per_day": [
            {
                "date": str(d.date()),
                "vix_pct": round(float(vix_chg.loc[d]), 2),
                "spy_pct": round(float(spy_ret.loc[d]), 2),
            }
            for d in td
        ],
    }
    return out


legacy_stats = reaction_stats(legacy_td, "legacy (13th-of-month proxy)")
official_stats = reaction_stats(official_td, "official (BLS/ALFRED)")

print("\n--- legacy ---")
print(f"  VIX mean {legacy_stats['vix_pct_change_on_cpi_day']['mean']}%  "
      f"Welch t={legacy_stats['vix_welch_t']} p={legacy_stats['vix_welch_p']}")
print(f"  |SPY| mean {legacy_stats['spy_abs_return_on_cpi_day_mean']}%  "
      f"Welch t={legacy_stats['spy_abs_welch_t']} p={legacy_stats['spy_abs_welch_p']}")
print("--- official ---")
print(f"  VIX mean {official_stats['vix_pct_change_on_cpi_day']['mean']}%  "
      f"Welch t={official_stats['vix_welch_t']} p={official_stats['vix_welch_p']}")
print(f"  |SPY| mean {official_stats['spy_abs_return_on_cpi_day_mean']}%  "
      f"Welch t={official_stats['spy_abs_welch_t']} p={official_stats['spy_abs_welch_p']}")

# ── The headline the legacy T-2 article actually ran: "recent 4 CPI reactions" ──
legacy_recent4 = to_trading_days(LEGACY_DATES[-4:])
official_recent4 = to_trading_days(OFFICIAL_DATES[-4:])
r4_legacy = [round(float(vix_chg.loc[d]), 2) for d in legacy_recent4]
r4_official = [round(float(vix_chg.loc[d]), 2) for d in official_recent4]
print(f"\nrecent-4 VIX move, legacy dates:   {r4_legacy}  mean={np.mean(r4_legacy):.2f}%")
print(f"recent-4 VIX move, official dates: {r4_official}  mean={np.mean(r4_official):.2f}%")

# ── Current positioning going into 2026-07-14 ─────────────────────────────────
latest = vix.index[-1]
vix_now = float(vix.iloc[-1])
vix_20d = float(vix.iloc[-20:].mean())
spy_rv20 = float(spy_ret.iloc[-20:].std(ddof=1) * np.sqrt(252))

# ── Figures ───────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 5.2))
alld = sorted(set(LEGACY_DATES) | set(OFFICIAL_DATES))
for i, d in enumerate(alld):
    in_l, in_o = d in set(LEGACY_DATES), d in set(OFFICIAL_DATES)
    if in_l and in_o:
        c, m, lbl = "#3d7a5a", "o", "both agree"
    elif in_o:
        c, m, lbl = "#1f5fa8", "^", "official only (we missed it)"
    else:
        c, m, lbl = "#c0392b", "x", "legacy only (no CPI that day)"
    ax.scatter(d, 1 if in_o else 0, color=c, marker=m, s=90, zorder=3,
               label=lbl if lbl not in ax.get_legend_handles_labels()[1] else None)
ax.set_yticks([0, 1])
ax.set_yticklabels(["我們用過的日期\n(官方沒有)", "官方發布日"])
ax.set_title("CPI 發布日：舊分析的硬編日期 vs BLS/ALFRED 官方日曆\n"
             f"13 個日期中 {len(wrong)} 個對不上；{len(phantom)} 天根本沒有 CPI",
             fontsize=12)
ax.grid(alpha=0.25, axis="x")
ax.legend(loc="center left", fontsize=9, framealpha=0.9)
plt.tight_layout()
plt.savefig(OUT_DIR / "fig1_date_error.png", dpi=150)
plt.close()

fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
for ax, key, ttl, unit in [
    (a1, "vix", "CPI 當天 VIX 變動", "%"),
    (a2, "spy", "CPI 當天 SPY 絕對報酬", "%"),
]:
    if key == "vix":
        L = [vix_chg.loc[d] for d in legacy_td]
        O = [vix_chg.loc[d] for d in official_td]
        base = float(vix_chg.mean())
    else:
        L = [spy_abs.loc[d] for d in legacy_td]
        O = [spy_abs.loc[d] for d in official_td]
        base = float(spy_abs.mean())
    ax.boxplot([L, O], labels=["舊（proxy 日期）", "新（官方日期）"], widths=0.5)
    ax.axhline(base, color="#c0392b", ls="--", lw=1.2,
               label=f"一般交易日均值 {base:.2f}{unit}")
    ax.scatter([1] * len(L), L, alpha=0.6, color="#888", zorder=3)
    ax.scatter([2] * len(O), O, alpha=0.7, color="#1f5fa8", zorder=3)
    ax.set_title(ttl, fontsize=12)
    ax.set_ylabel(unit)
    ax.grid(alpha=0.25, axis="y")
    ax.legend(fontsize=9)
plt.suptitle("換上官方發布日之後，CPI 日的波動反應（2025-05 ~ 2026-06）", fontsize=13)
plt.tight_layout()
plt.savefig(OUT_DIR / "fig2_cpi_day_reaction.png", dpi=150)
plt.close()

evidence = {
    "event": "US CPI 2026-07-14 (June 2026 reference month, 08:30 ET)",
    "event_date_source": "BLS schedule + ALFRED release_id=10",
    "article_slot": "T-2",
    "generated_for_trading_day": str(latest.date()),
    "seed": SEED,
    "price_source": "yfinance ^VIX / SPY, auto_adjust=True",
    "sample_window": f"{START} → {str(latest.date())}",
    "date_error_audit": {
        "legacy_dates": [str(d.date()) for d in LEGACY_DATES],
        "legacy_source": "storage/event_articles/us_cpi_2026_06_11_t2/analysis.py:44 (hard-coded, no provenance)",
        "official_dates": [str(d.date()) for d in OFFICIAL_DATES],
        "n_legacy": len(LEGACY_DATES),
        "n_official": len(OFFICIAL_DATES),
        "n_wrong": len(wrong),
        "wrong_dates": wrong,
        "phantom_dates_no_cpi_published": phantom,
        "official_dates_legacy_missed": missed,
        "root_cause": "scripts/populate_upcoming_events.py::gen_us_cpi used '13th of month' as a proxy for the BLS release date (fixed 2026-07-12: now reads the BLS-published table).",
    },
    "reaction_legacy_dates": legacy_stats,
    "reaction_official_dates": official_stats,
    "recent4_headline": {
        "legacy_dates": [str(d.date()) for d in legacy_recent4],
        "legacy_vix_pct": r4_legacy,
        "legacy_mean": round(float(np.mean(r4_legacy)), 2),
        "official_dates": [str(d.date()) for d in official_recent4],
        "official_vix_pct": r4_official,
        "official_mean": round(float(np.mean(r4_official)), 2),
    },
    "current_positioning": {
        "as_of": str(latest.date()),
        "vix_close": round(vix_now, 2),
        "vix_20d_mean": round(vix_20d, 2),
        "spy_realized_vol_20d_annualized_pct": round(spy_rv20, 2),
        "vix_minus_realized": round(vix_now - spy_rv20, 2),
    },
    "figures": ["fig1_date_error.png", "fig2_cpi_day_reaction.png"],
}
(OUT_DIR / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
print(f"\n✅ evidence.json + 2 figures → {OUT_DIR}")
print(f"VIX now {vix_now:.2f} | 20d realized {spy_rv20:.2f}% | spread {vix_now - spy_rv20:+.2f}")
