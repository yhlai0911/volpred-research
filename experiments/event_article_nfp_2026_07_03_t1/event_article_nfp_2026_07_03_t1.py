"""
event_article_nfp_2026_07_03_t1 — evidence package for NFP T-1 event article.

Pulls (as of most recent close available, target 2026-07-01):
  - VIX, VIX9D level + VIX9D/VIX ratio (term-structure inversion signal)
  - SPY 5d / 20d realized vol (annualized, close-to-close)
  - Historical NFP-day (first-Friday-of-month release) SPY return + next-day
    VIX change, for the trailing ~12 NFP dates prior to 2026-07-03.

All data pulled from yfinance. No lookahead: all "current" stats are as of
close 2026-07-01 (the last trading day before NFP release 2026-07-03).
Event-window stats use realized (already-occurred) history only.

Seed: N/A (no stochastic procedure in this script; pure descriptive stats).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

AS_OF = "2026-07-01"  # last close before 2026-07-03 NFP release


def first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    offset = (4 - d.weekday()) % 7  # Friday = weekday 4
    return d + timedelta(days=offset)


def build_nfp_dates(n: int = 13) -> list[date]:
    """Trailing N first-Fridays-of-month strictly before 2026-07-03.

    Note: US NFP release date is normally first Friday of month, but a small
    number of months are shifted (e.g. holiday adjustment). We use the
    first-Friday rule as a standard proxy consistent with BLS historical
    schedule for the vast majority of months; this is disclosed in the
    article as the identification rule.
    """
    dates = []
    y, m = 2026, 6
    while len(dates) < n:
        ff = first_friday(y, m)
        if ff < date(2026, 7, 3):
            dates.append(ff)
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(dates))


def pct(x):
    return float(x) * 100.0


def main():
    nfp_dates = build_nfp_dates(13)
    print("NFP proxy dates used:", nfp_dates)

    # ---- Pull SPY + VIX long history to cover event windows + current RV ----
    start = (nfp_dates[0] - timedelta(days=10)).isoformat()
    end = "2026-07-03"

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
    for nfp in nfp_dates:
        nfp_ts = pd.Timestamp(nfp)
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
                "nfp_date_proxy": str(nfp),
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
        "nfp_release_date": "2026-07-03",
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
            "NFP release dates approximated via first-Friday-of-month rule "
            "(standard BLS schedule pattern); a small number of months may "
            "shift by BLS holiday adjustment, not individually re-verified "
            "against BLS calendar for each of the 13 dates. spy_ret_day0 = "
            "close-to-close return on the trading day matching/following the "
            "release date. vix_chg_day0 = VIX close on release day minus VIX "
            "close on prior trading day. No lookahead: all stats use only "
            "data at/after each historical date; current_snapshot uses only "
            "data through as_of_date (2026-07-01), strictly before the "
            "2026-07-03 release. KNOWN DATA GAP: yfinance ^VIX9D series stops "
            "printing 2026-06-26 (verified via yf.Ticker.history), i.e. it "
            "lags the ^VIX series by several trading sessions as of the "
            "as_of_date. To avoid mixing two different calendar dates into "
            "one ratio, vix9d_over_vix_ratio_same_date is computed on the "
            "last date BOTH series have a print (2026-06-26), not on the "
            "as_of_date. This is disclosed verbatim in the article; no "
            "value was invented to fill the gap."
        ),
    }

    with open(OUT_DIR / "event_article_nfp_2026_07_03_t1_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    hist_df.to_csv(OUT_DIR / "nfp_historical_event_window.csv", index=False)

    # ---- Figures ----
    import matplotlib
    matplotlib.use("Agg")
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
