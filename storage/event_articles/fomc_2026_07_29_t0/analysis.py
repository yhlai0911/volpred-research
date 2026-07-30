"""
FOMC 2026-07-29 T+0 event article — evidence package.

Angle (evidence-first; the angle came out of the numbers, not the other way round):
  FOMC decision day is normally a volatility RELEASE valve — the event risk that
  was priced into options gets resolved at 14:00 ET and VIX falls (the classic
  "vol crush"). On 2026-07-29 it did the opposite: VIX rose and SPY fell hard.

  This script measures how unusual that is against every scheduled FOMC decision
  day since 2019, and checks whether the day's realized SPY move exceeded what
  the previous close's VIX was implying for a single day.

Date source: Federal Reserve published FOMC meeting calendars (scheduled meetings
only; the 2020 unscheduled inter-meeting actions on 2020-03-03 and 2020-03-15 are
EXCLUDED because this study is about *scheduled* event days — including surprise
emergency cuts would contaminate the "priced-in event" baseline). The 2026 dates
match scripts/populate_upcoming_events.py::gen_fomc.
Price source: yfinance (^VIX, SPY, ^VIX3M), auto_adjust=True.

Outputs: evidence.json, fig1_fomc_day_vix.png, fig2_implied_vs_realized.png
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from plot_style import apply_cjk_style

apply_cjk_style()

SEED = 20260729
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
START = "2018-12-01"
END = "2026-07-31"
EVENT = pd.Timestamp("2026-07-29")

# ── Scheduled FOMC decision days (the second day of each two-day meeting) ──
# Source: Federal Reserve published meeting calendars, 2019-2026.
FOMC_DATES = pd.to_datetime([
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (scheduled only — 03-03 and 03-15 emergency cuts excluded by design)
    "2020-01-29", "2020-03-18", "2020-04-29", "2020-06-10",
    "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29",
])

TRADING_DAYS = 252.0


def fetch() -> pd.DataFrame:
    raw = yf.download(
        ["^VIX", "SPY", "^VIX3M"], start=START, end=END,
        auto_adjust=True, progress=False,
    )
    px = raw["Close"].copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px.rename(columns={"^VIX": "vix", "^VIX3M": "vix3m", "SPY": "spy"})


def build_panel(px: pd.DataFrame) -> pd.DataFrame:
    """One row per FOMC decision day, with the prior close as the reference."""
    rows = []
    idx = px.index
    for d in FOMC_DATES:
        if d not in idx:
            continue  # not a trading day / no data yet
        i = idx.get_loc(d)
        if i == 0:
            continue
        prev = idx[i - 1]
        vix_prev, vix_now = px["vix"].iloc[i - 1], px["vix"].iloc[i]
        spy_prev, spy_now = px["spy"].iloc[i - 1], px["spy"].iloc[i]
        if not np.isfinite([vix_prev, vix_now, spy_prev, spy_now]).all():
            continue
        spy_ret = spy_now / spy_prev - 1.0
        # What the previous close's VIX implied for ONE trading day, in percent.
        implied_1d = vix_prev / np.sqrt(TRADING_DAYS)
        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "prev_date": prev.strftime("%Y-%m-%d"),
            "vix_prev": float(vix_prev),
            "vix": float(vix_now),
            "vix_chg": float(vix_now - vix_prev),
            "vix_pct": float(vix_now / vix_prev - 1.0),
            "spy_ret": float(spy_ret),
            "spy_abs": float(abs(spy_ret) * 100.0),
            "implied_1d": float(implied_1d),
            "realized_over_implied": float(abs(spy_ret) * 100.0 / implied_1d),
        })
    return pd.DataFrame(rows).set_index("date", drop=False)


def main() -> None:
    px = fetch()
    panel = build_panel(px)

    ev_key = EVENT.strftime("%Y-%m-%d")
    if ev_key not in panel.index:
        raise SystemExit(f"event day {ev_key} not in panel — no closing data yet")
    ev = panel.loc[ev_key]
    hist = panel.drop(index=ev_key)  # strictly prior events, no self-inclusion

    # ── 1. Is FOMC day normally a vol-crush day? ──
    crush_share = float((hist["vix_chg"] < 0).mean())
    # Sign test against a fair coin: does VIX fall on FOMC day more often than not?
    n_down = int((hist["vix_chg"] < 0).sum())
    n_tot = int(len(hist))
    sign_p = float(stats.binomtest(n_down, n_tot, 0.5, alternative="greater").pvalue)
    # Paired test on the level change itself.
    t_stat, t_p = stats.ttest_1samp(hist["vix_chg"], 0.0)
    wil_p = float(stats.wilcoxon(hist["vix_chg"]).pvalue)

    # ── 2. Where does 2026-07-29 sit in that distribution? ──
    vix_pct_rank = float((hist["vix_chg"] < ev["vix_chg"]).mean())
    spy_rank = float((hist["spy_ret"] > ev["spy_ret"]).mean())
    z = float((ev["vix_chg"] - hist["vix_chg"].mean()) / hist["vix_chg"].std(ddof=1))

    # ── 3. Did the day break out of what the previous close implied? ──
    ratio_hist = hist["realized_over_implied"]
    breach_share = float((ratio_hist > 1.0).mean())
    ratio_rank = float((ratio_hist < ev["realized_over_implied"]).mean())

    # ── 4. Sub-period check: is the vol-crush pattern stable, or a 2019-2021 relic? ──
    sub = {}
    for label, lo, hi in [("2019-2021", "2019-01-01", "2021-12-31"),
                          ("2022-2023", "2022-01-01", "2023-12-31"),
                          ("2024-2026", "2024-01-01", "2026-12-31")]:
        m = hist[(hist["date"] >= lo) & (hist["date"] <= hi)]
        sub[label] = {
            "n": int(len(m)),
            "mean_vix_chg": float(m["vix_chg"].mean()),
            "share_vix_down": float((m["vix_chg"] < 0).mean()),
            "mean_spy_abs": float(m["spy_abs"].mean()),
        }

    # ── 5. Largest FOMC-day VIX jumps on record, for the table ──
    top = (panel.sort_values("vix_chg", ascending=False)
                .head(6)[["date", "vix_prev", "vix", "vix_chg", "vix_pct", "spy_ret"]]
                .to_dict("records"))

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "event": {
            "event_key": "FOMC_2026_07_29",
            "event_type": "fomc",
            "event_date": "2026-07-29",
            "event_series_slot": "T+0",
        },
        "data": {
            "price_source": "yfinance ^VIX / SPY / ^VIX3M, auto_adjust=True",
            "date_source": "Federal Reserve published FOMC meeting calendars, scheduled meetings only",
            "sample": f"{panel['date'].iloc[0]} .. {panel['date'].iloc[-1]}",
            "n_fomc_days": int(len(panel)),
            "n_prior_events": n_tot,
            "last_close_available": px.index[-1].strftime("%Y-%m-%d"),
        },
        "event_day": {k: (float(ev[k]) if k != "date" and k != "prev_date" else ev[k])
                      for k in panel.columns},
        "baseline": {
            "share_vix_down_on_fomc_day": crush_share,
            "n_down": n_down, "n_total": n_tot,
            "sign_test_p_greater": sign_p,
            "mean_vix_chg": float(hist["vix_chg"].mean()),
            "median_vix_chg": float(hist["vix_chg"].median()),
            "sd_vix_chg": float(hist["vix_chg"].std(ddof=1)),
            "ttest_t": float(t_stat), "ttest_p": float(t_p),
            "wilcoxon_p": wil_p,
            "mean_spy_abs_pct": float(hist["spy_abs"].mean()),
        },
        "event_vs_baseline": {
            "vix_chg_percentile": vix_pct_rank,
            "spy_ret_percentile_worst": spy_rank,
            "vix_chg_zscore": z,
            "realized_over_implied": float(ev["realized_over_implied"]),
            "share_prior_events_breaching_implied": breach_share,
            "realized_over_implied_percentile": ratio_rank,
        },
        "subperiods": sub,
        "top_vix_jumps": top,
    }

    (OUT_DIR / "evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── fig1: FOMC-day VIX change distribution, this event marked ──
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(hist["vix_chg"], bins=24, color="#4C78A8", alpha=0.85,
            edgecolor="white", label=f"2019-2026 前 {n_tot} 次 FOMC 決議日")
    ax.axvline(0, color="#666666", lw=1, ls="--")
    ax.axvline(float(hist["vix_chg"].mean()), color="#54A24B", lw=2,
               label=f"歷史平均 {hist['vix_chg'].mean():+.2f} 點")
    ax.axvline(float(ev["vix_chg"]), color="#E45756", lw=2.5,
               label=f"2026-07-29 {ev['vix_chg']:+.2f} 點")
    ax.set_xlabel("FOMC 決議日 VIX 變動（點，相對前一收盤）")
    ax.set_ylabel("次數")
    ax.set_title("決議日通常是波動率的洩壓閥；這次是反過來的")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig1_fomc_day_vix.png", dpi=150)
    plt.close(fig)

    # ── fig2: implied (prev-close VIX, 1-day) vs realized |SPY| on each FOMC day ──
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(hist["implied_1d"], hist["spy_abs"], s=34, color="#4C78A8",
               alpha=0.75, label="2019-2026 前次 FOMC 決議日")
    ax.scatter([ev["implied_1d"]], [ev["spy_abs"]], s=150, color="#E45756",
               marker="*", zorder=5, label="2026-07-29")
    lim = max(float(hist["implied_1d"].max()), float(hist["spy_abs"].max())) * 1.05
    ax.plot([0, lim], [0, lim], color="#666666", lw=1, ls="--",
            label="實際 = 前一日 VIX 隱含的單日幅度")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("前一收盤 VIX 換算的單日隱含幅度（%）")
    ax.set_ylabel("決議日 SPY 實際絕對漲跌幅（%）")
    ax.set_title("虛線以上 = 當天走得比事前定價還兇")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig2_implied_vs_realized.png", dpi=150)
    plt.close(fig)

    print(json.dumps({
        "event": evidence["event_day"],
        "baseline": evidence["baseline"],
        "vs": evidence["event_vs_baseline"],
        "sub": sub,
        "top": top[:4],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
