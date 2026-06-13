"""
US CPI 2026-06-11 T+0 event article evidence pack.

Scope:
1. Pull official market closes around the 2026-06-10 CPI release via yfinance
2. Store the official BLS CPI numbers used in the article
3. Compare the release-day VIX move with the recent CPI sample
4. Generate two reader-facing charts for the published article
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


OUT_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/storage/event_articles/us_cpi_2026_06_11_t0")
OUT_DIR.mkdir(parents=True, exist_ok=True)


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


def _download_close(ticker: str) -> pd.Series:
    df = yf.download(
        ticker,
        start="2025-05-01",
        end="2026-06-13",
        auto_adjust=True,
        progress=False,
    )
    close = df["Close"].squeeze()
    close.name = ticker
    return close


def _pct(a: float, b: float) -> float:
    return float((b - a) / a * 100.0)


def main() -> None:
    vix = _download_close("^VIX")
    vix9d = _download_close("^VIX9D")
    spy = _download_close("SPY")

    event_dates = pd.to_datetime(["2026-06-09", "2026-06-10", "2026-06-11"])
    event_window = pd.DataFrame(
        {
            "VIX": vix.loc[event_dates].astype(float),
            "VIX9D": vix9d.loc[event_dates].astype(float),
            "SPY": spy.loc[event_dates].astype(float),
        }
    )

    reaction_rows = []
    for prev_day, curr_day in zip(event_dates[:-1], event_dates[1:]):
        reaction_rows.append(
            {
                "date": curr_day.strftime("%Y-%m-%d"),
                "VIX_pct": _pct(event_window.loc[prev_day, "VIX"], event_window.loc[curr_day, "VIX"]),
                "VIX9D_pct": _pct(event_window.loc[prev_day, "VIX9D"], event_window.loc[curr_day, "VIX9D"]),
                "SPY_pct": _pct(event_window.loc[prev_day, "SPY"], event_window.loc[curr_day, "SPY"]),
            }
        )

    cpi_dates = pd.to_datetime(
        [
            "2025-05-13",
            "2025-06-11",
            "2025-07-15",
            "2025-08-12",
            "2025-09-11",
            "2025-10-15",
            "2025-11-13",
            "2025-12-10",
            "2026-01-14",
            "2026-02-12",
            "2026-03-12",
            "2026-04-10",
            "2026-05-13",
            "2026-06-10",
        ]
    )
    cpi_vix_changes = []
    for day in cpi_dates:
        if day not in vix.index:
            continue
        pos = vix.index.get_loc(day)
        if pos == 0:
            continue
        prev_close = float(vix.iloc[pos - 1])
        curr_close = float(vix.iloc[pos])
        cpi_vix_changes.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "vix_prev": prev_close,
                "vix_close": curr_close,
                "vix_pct": _pct(prev_close, curr_close),
            }
        )
    ranked = sorted(cpi_vix_changes, key=lambda x: x["vix_pct"], reverse=True)
    rank_map = {row["date"]: i + 1 for i, row in enumerate(ranked)}

    current = next(row for row in cpi_vix_changes if row["date"] == "2026-06-10")
    recent5 = [row for row in cpi_vix_changes if row["date"] >= "2026-02-12"]

    evidence = {
        "event": "US CPI 2026-06-11",
        "article_slot": "T+0",
        "sources": {
            "bls": BLS_SOURCE,
            "consensus": CONSENSUS,
            "market_data": "yfinance (^VIX, ^VIX9D, SPY), downloaded 2026-06-12",
        },
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
            "date": "2026-06-10",
            "vix_pct": round(current["vix_pct"], 3),
            "rank_among_14_cpi_days": rank_map["2026-06-10"],
            "sample_n": len(cpi_vix_changes),
        },
        "recent5_cpi_vix_moves": recent5,
    }

    (OUT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Figure 1: day-over-day reaction bars
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    x = np.arange(2)
    width = 0.22
    ax.bar(x - width, [reaction_rows[0]["VIX_pct"], reaction_rows[1]["VIX_pct"]], width, label="VIX", color="#263238")
    ax.bar(x, [reaction_rows[0]["VIX9D_pct"], reaction_rows[1]["VIX9D_pct"]], width, label="VIX9D", color="#c62828")
    ax.bar(x + width, [reaction_rows[0]["SPY_pct"], reaction_rows[1]["SPY_pct"]], width, label="SPY", color="#1565c0")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(["6/10 CPI 發布日", "6/11 隔日"], fontsize=10)
    ax.set_ylabel("日變動（%）", fontsize=11)
    ax.set_title("CPI 發布日先拉高波動，隔日大半吐回", fontsize=13, fontweight="bold")
    ax.legend()
    ax.yaxis.grid(True, alpha=0.25)
    fig.text(0.99, 0.01, "資料來源：BLS、yfinance；VolPred 自製分析", ha="right", va="bottom", fontsize=8, color="gray")
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig1_cpi_t0_reaction.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # Figure 2: indexed event window path
    indexed = event_window / event_window.iloc[0] * 100.0
    fig2, ax2 = plt.subplots(figsize=(8.8, 5.2))
    ax2.plot(indexed.index, indexed["VIX"], marker="o", linewidth=2.0, color="#263238", label="VIX")
    ax2.plot(indexed.index, indexed["VIX9D"], marker="o", linewidth=2.0, color="#c62828", label="VIX9D")
    ax2.plot(indexed.index, indexed["SPY"], marker="o", linewidth=2.0, color="#1565c0", label="SPY")
    ax2.axhline(100, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.set_ylabel("6/9 = 100", fontsize=11)
    ax2.set_title("6/10 的 CPI shock 沒有延續成第二天的 vol regime", fontsize=13, fontweight="bold")
    ax2.legend()
    ax2.yaxis.grid(True, alpha=0.25)
    fig2.autofmt_xdate()
    fig2.text(0.99, 0.01, "資料來源：yfinance (^VIX, ^VIX9D, SPY)；VolPred 自製分析", ha="right", va="bottom", fontsize=8, color="gray")
    plt.tight_layout()
    fig2.savefig(OUT_DIR / "fig2_cpi_t0_event_window.png", dpi=160, bbox_inches="tight")
    plt.close(fig2)


if __name__ == "__main__":
    main()
