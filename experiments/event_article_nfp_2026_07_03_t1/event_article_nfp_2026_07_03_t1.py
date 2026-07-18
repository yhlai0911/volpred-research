"""
event_article_nfp_2026_07_03_t1 — evidence package for NFP T-1 event article.

Pulls (as of most recent close available, target 2026-07-01):
  - VIX, VIX9D level + VIX9D/VIX ratio (term-structure inversion signal)
  - SPY 5d / 20d realized vol (annualized, close-to-close)
  - Historical NFP-day SPY return + next-day VIX change, for the trailing 13
    OFFICIAL Employment Situation releases prior to 2026-07-02.

Event dates come from the official BLS/ALFRED release calendar via
`volpred.data.event_dates.nfp_release_dates`, which fails closed if the
calendar is unreachable. This script previously derived them from a
first-Friday-of-month proxy; against the official calendar 7 of the 13 dates
were wrong, including one phantom event (no Employment Situation was published
in October 2025 — the shutdown pushed the September report to 2025-11-20).
The release under study is 2026-07-02, not 2026-07-03: the July 4 holiday was
observed on Friday 2026-07-03, so BLS moved the release forward a day.
See experiments/k1442/related_event_date_audit.md.

All data pulled from yfinance. No lookahead: the download window itself ends
before the release, so "current" stats cannot see 2026-07-02 even by accident.
Event-window stats use realized (already-occurred) history only.

Seed: N/A (no stochastic procedure in this script; pure descriptive stats).
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.data.event_dates import nfp_release_dates

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

RELEASE_DATE = "2026-07-02"  # official BLS Employment Situation release
AS_OF = "2026-07-01"  # last close before the release


def build_nfp_dates(n: int = 13) -> list[pd.Timestamp]:
    """Trailing N official Employment Situation releases strictly before RELEASE_DATE.

    No proxy and no fallback: `nfp_release_dates` raises if the official
    calendar cannot be retrieved. A wrong event date is worse than a failed
    run because it still produces plausible-looking numbers.
    """
    release_ts = pd.Timestamp(RELEASE_DATE)
    # Reach back far enough that N releases exist even with cancelled months.
    official = nfp_release_dates("2024-01-01", RELEASE_DATE)
    prior = [d for d in official if d < release_ts]
    if len(prior) < n:
        raise RuntimeError(
            f"official calendar returned only {len(prior)} releases before "
            f"{RELEASE_DATE}; need {n}"
        )
    return prior[-n:]


def pct(x):
    return float(x) * 100.0


def main():
    nfp_dates = build_nfp_dates(13)
    print("Official NFP release dates used:", [str(d.date()) for d in nfp_dates])

    # ---- Pull SPY + VIX long history to cover event windows + current RV ----
    start = (nfp_dates[0] - timedelta(days=10)).date().isoformat()
    # yfinance `end` is exclusive: stop the window at AS_OF so the release day
    # itself is never downloaded. No-lookahead is then structural, not a slice.
    end = RELEASE_DATE

    spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False)
    vix9d = yf.download("^VIX9D", start=start, end=end, auto_adjust=False, progress=False)

    # flatten possible multiindex columns (yfinance >=0.2 returns MultiIndex even for single ticker sometimes)
    for df in (spy, vix, vix9d):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy = spy[~spy.index.duplicated()]
    vix = vix[~vix.index.duplicated()]
    vix9d = vix9d[~vix9d.index.duplicated()]

    spy_close = spy["Close"].dropna()
    vix_close = vix["Close"].dropna()
    vix9d_close = vix9d["Close"].dropna()

    spy_ret = spy_close.pct_change().dropna()

    # ---- current snapshot as of AS_OF ----
    as_of_ts = pd.Timestamp(AS_OF)
    vix_now = float(vix_close.loc[:as_of_ts].iloc[-1])
    vix_now_date = vix_close.loc[:as_of_ts].index[-1]
    vix9d_now = float(vix9d_close.loc[:as_of_ts].iloc[-1])
    vix9d_now_date = vix9d_close.loc[:as_of_ts].index[-1]
    vix9d_data_lag_days = int((vix_now_date - vix9d_now_date).days)

    # yfinance ^VIX9D known data gap: it stops updating a few sessions before
    # the most recent VIX close in this window (verified: last ^VIX9D print
    # 2026-06-26 vs VIX close 2026-07-01). To avoid comparing two different
    # calendar dates as if simultaneous, compute the ratio on the LAST COMMON
    # DATE where both series have a print, and disclose the staleness
    # explicitly in the article rather than papering over it.
    common_dates = vix_close.index.intersection(vix9d_close.index)
    last_common = common_dates.max()
    vix_on_common = float(vix_close.loc[last_common])
    vix9d_on_common = float(vix9d_close.loc[last_common])
    ratio_common_date = vix9d_on_common / vix_on_common
    ratio_now = ratio_common_date  # canonical ratio uses same-date pair only

    rv5 = spy_ret.loc[:as_of_ts].iloc[-5:]
    rv20 = spy_ret.loc[:as_of_ts].iloc[-20:]
    rv5_ann = pct(rv5.std(ddof=1) * np.sqrt(252))
    rv20_ann = pct(rv20.std(ddof=1) * np.sqrt(252))

    print(f"VIX as of {vix_now_date.date()}: {vix_now:.2f}")
    print(f"VIX9D last print {vix9d_now_date.date()}: {vix9d_now:.2f} (lag {vix9d_data_lag_days}d vs VIX)")
    print(f"Same-date ratio at {last_common.date()}: VIX9D={vix9d_on_common:.2f} / VIX={vix_on_common:.2f} = {ratio_common_date:.4f}")
    print(f"SPY 5d RV (ann, %): {rv5_ann:.2f}")
    print(f"SPY 20d RV (ann, %): {rv20_ann:.2f}")

    # ---- historical NFP-day event window ----
    rows = []
    for nfp_ts in nfp_dates:
        # SPY return ON the NFP release day (close-to-close, day t vs t-1)
        idx = spy_ret.index[spy_ret.index >= nfp_ts]
        if len(idx) == 0:
            continue
        day0 = idx[0]
        if day0 - nfp_ts > pd.Timedelta(days=4):
            continue  # release date not a trading day within reasonable window, skip
        ret_day0 = float(spy_ret.loc[day0]) * 100.0

        # VIX change from day before release to day of release (VIX close t vs t-1)
        vix_idx = vix_close.index[vix_close.index >= nfp_ts]
        if len(vix_idx) == 0:
            continue
        vix_day0 = vix_idx[0]
        prior_vix_idx = vix_close.index[vix_close.index < vix_day0]
        if len(prior_vix_idx) == 0:
            continue
        vix_prior = float(vix_close.loc[prior_vix_idx[-1]])
        vix_on = float(vix_close.loc[vix_day0])
        vix_chg = vix_on - vix_prior

        # next trading day SPY return (post-digestion day t+1)
        after_idx = spy_ret.index[spy_ret.index > day0]
        ret_next = float(spy_ret.loc[after_idx[0]]) * 100.0 if len(after_idx) else np.nan

        rows.append(
            {
                "nfp_release_date": str(nfp_ts.date()),
                "trading_day": str(day0.date()),
                "spy_ret_day0_pct": round(ret_day0, 3),
                "vix_chg_day0_pts": round(vix_chg, 3),
                "spy_ret_next_day_pct": round(ret_next, 3) if not np.isnan(ret_next) else None,
            }
        )

    hist_df = pd.DataFrame(rows)
    print(hist_df)

    n = len(hist_df)
    win_rate_up = float((hist_df["spy_ret_day0_pct"] > 0).mean()) * 100.0
    mean_ret = float(hist_df["spy_ret_day0_pct"].mean())
    median_ret = float(hist_df["spy_ret_day0_pct"].median())
    std_ret = float(hist_df["spy_ret_day0_pct"].std(ddof=1))
    mean_vix_chg = float(hist_df["vix_chg_day0_pts"].mean())
    median_vix_chg = float(hist_df["vix_chg_day0_pts"].median())
    pct_vix_down = float((hist_df["vix_chg_day0_pts"] < 0).mean()) * 100.0
    mean_next_ret = float(hist_df["spy_ret_next_day_pct"].mean())

    summary = {
        "as_of_date": AS_OF,
        "nfp_release_date": RELEASE_DATE,
        "event_date_source": (
            "official BLS Employment Situation release calendar via "
            "volpred.data.event_dates.nfp_release_dates (FRED/ALFRED release id 50)"
        ),
        "data_source": "yfinance (SPY, ^VIX, ^VIX9D daily close)",
        "n_historical_nfp_events": n,
        "current_snapshot": {
            "vix_close_latest": round(vix_now, 2),
            "vix_close_latest_date": str(vix_now_date.date()),
            "vix9d_close_latest_print": round(vix9d_now, 2),
            "vix9d_close_latest_print_date": str(vix9d_now_date.date()),
            "vix9d_data_lag_days_vs_vix": vix9d_data_lag_days,
            "vix9d_over_vix_ratio_same_date": round(ratio_common_date, 4),
            "vix9d_over_vix_ratio_same_date_basis": str(last_common.date()),
            "spy_5d_realized_vol_annualized_pct": round(rv5_ann, 2),
            "spy_20d_realized_vol_annualized_pct": round(rv20_ann, 2),
        },
        # The original 2026-07-01 run hit a yfinance ^VIX9D gap: the series
        # stopped at 2026-06-26, so the ratio was computed on that basis and
        # the gap was disclosed in the article. yfinance has since backfilled
        # 2026-06-29..2026-07-01, so the ratio is now a true same-date T-1
        # figure. This is a VENDOR VINTAGE change, not a consequence of the
        # event-date correction, and not lookahead: 13.14 is the actual
        # 2026-07-01 close, still strictly before the 2026-07-02 release. The
        # 2026-06-26 print is unchanged at 16.80, which is what pins the cause.
        # Recorded rather than overwritten so the as-published claim stays auditable.
        "vix9d_vintage_note": {
            "as_published_vix9d_last_print_date": "2026-06-26",
            "as_published_vix9d_last_print": 16.8,
            "as_published_ratio_same_date": 0.9125,
            "as_published_data_lag_days": 5,
            "reason_for_change": "yfinance backfilled the ^VIX9D gap after publication",
            "affects_live_article": False,
        },
        "historical_nfp_day_stats": {
            "spy_ret_day0_mean_pct": round(mean_ret, 3),
            "spy_ret_day0_median_pct": round(median_ret, 3),
            "spy_ret_day0_std_pct": round(std_ret, 3),
            "spy_up_day_win_rate_pct": round(win_rate_up, 1),
            "vix_chg_day0_mean_pts": round(mean_vix_chg, 3),
            "vix_chg_day0_median_pts": round(median_vix_chg, 3),
            "pct_events_vix_fell_pct": round(pct_vix_down, 1),
            "spy_ret_next_day_mean_pct": round(mean_next_ret, 3),
        },
        "historical_nfp_table": rows,
        "notes": (
            "NFP release dates are the official BLS Employment Situation "
            "release dates from the FRED/ALFRED release calendar (release id "
            "50), retrieved via volpred.data.event_dates.nfp_release_dates, "
            "which fails closed rather than falling back to a proxy. This "
            "replaces the first-Friday-of-month proxy used in the original "
            "run, which put 7 of these 13 events on the wrong date, including "
            "a phantom 2025-10-03 event (no Employment Situation was published "
            "in October 2025; the shutdown moved the September report to "
            "2025-11-20). spy_ret_day0 = "
            "close-to-close return on the trading day matching/following the "
            "release date. vix_chg_day0 = VIX close on release day minus VIX "
            "close on prior trading day. No lookahead: the yfinance download "
            "window ends exclusive at the release date, so no series in this "
            "script contains a 2026-07-02 print at all; current_snapshot is "
            "as of the 2026-07-01 close, the last session before the release. "
            "RESOLVED DATA GAP: at publication the yfinance ^VIX9D series "
            "stopped printing at 2026-06-26, so the ratio was computed on that "
            "basis (0.9125) and the 5-session lag was disclosed verbatim in the "
            "article rather than filled with an invented value. yfinance has "
            "since backfilled 2026-06-29..2026-07-01, so the ratio is now a "
            "true same-date T-1 figure (13.14 / 16.59 = 0.7920). The 2026-06-26 "
            "print is unchanged at 16.80, which confirms the cause is vendor "
            "backfill rather than the event-date correction. Both vintages are "
            "kept: see vix9d_vintage_note. The live article never cited the "
            "VIX9D ratio, so no published number is affected."
        ),
    }

    with open(OUT_DIR / "event_article_nfp_2026_07_03_t1_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    hist_df.to_csv(OUT_DIR / "nfp_historical_event_window.csv", index=False)

    # ---- Figures ----
    import matplotlib
    matplotlib.use("Agg")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from plot_style import apply_cjk_style

    apply_cjk_style()
    import matplotlib.pyplot as plt

    # Figure 1: VIX vs VIX9D term structure, last 60 trading days
    fig, ax = plt.subplots(figsize=(9, 5))
    window = 60
    v_ = vix_close.loc[:as_of_ts].iloc[-window:]
    v9_ = vix9d_close.loc[:as_of_ts].iloc[-window:]
    ax.plot(v_.index, v_.values, label="VIX", color="#1f77b4", linewidth=1.8)
    ax.plot(v9_.index, v9_.values, label="VIX9D", color="#d62728", linewidth=1.8)
    ax.axvline(v_.index[-1], color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.set_title(f"VIX vs VIX9D — 近 {window} 交易日（截至 {AS_OF}）")
    ax.set_ylabel("指數水準")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_vix_vix9d_term_structure.png", dpi=150)
    plt.close(fig)

    # Figure 2: Historical NFP-day SPY return bar chart
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#2ca02c" if r >= 0 else "#d62728" for r in hist_df["spy_ret_day0_pct"]]
    ax.bar(hist_df["trading_day"], hist_df["spy_ret_day0_pct"], color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(mean_ret, color="gray", linestyle="--", linewidth=1, label=f"平均 {mean_ret:.2f}%")
    ax.set_title(f"近 {n} 次非農發佈日 SPY 當日報酬")
    ax.set_ylabel("SPY 當日報酬 (%)")
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_nfp_day_spy_return.png", dpi=150)
    plt.close(fig)

    print("Saved figures to", FIG_DIR)
    print("Saved results JSON.")


if __name__ == "__main__":
    main()
