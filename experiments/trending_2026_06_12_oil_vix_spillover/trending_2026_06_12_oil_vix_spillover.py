#!/usr/bin/env python3
"""Evidence package for the 2026-06-12 oil/OVX/VIX spillover follow-up."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf


OUT = Path(__file__).resolve().parent
START_DATE = "2007-01-01"
END_DATE = "2026-06-12"
TICKERS = ["^OVX", "^VIX", "CL=F", "BZ=F", "USO", "XLE", "SPY", "^TNX", "DX-Y.NYB"]
CHECKPOINT = pd.Timestamp("2026-05-20")


def _pct_change(series: pd.Series, days: int) -> float:
    return float(series.iloc[-1] / series.iloc[-1 - days] - 1)


def _change_between(df: pd.DataFrame, col: str, start: pd.Timestamp) -> float:
    return float(df[col].iloc[-1] / df.loc[start, col] - 1)


def _rank_pct(series: pd.Series) -> float:
    return float(series.rank(pct=True).iloc[-1])


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def main() -> None:
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    close = raw["Close"].dropna(how="all")
    close.to_csv(OUT / "close_prices.csv", index_label="date")

    combo = close[["^OVX", "^VIX", "CL=F", "BZ=F", "USO", "XLE", "SPY"]].dropna()
    combo.columns = ["OVX", "VIX", "WTI", "Brent", "USO", "XLE", "SPY"]
    combo["OVX_VIX_RATIO"] = combo["OVX"] / combo["VIX"]

    latest_date = combo.index[-1]
    latest = combo.iloc[-1]
    ytd = combo.loc["2026-01-01":]

    rows = []
    for col in ["OVX", "VIX", "OVX_VIX_RATIO", "WTI", "Brent", "USO", "XLE", "SPY"]:
        series = combo[col]
        rows.append(
            {
                "metric": col,
                "latest": float(series.iloc[-1]),
                "change_1d": _pct_change(series, 1),
                "change_5d": _pct_change(series, 5),
                "change_20d": _pct_change(series, 20),
                "change_since_2026_05_20": _change_between(combo, col, CHECKPOINT),
                "full_sample_percentile": _rank_pct(series),
                "one_year_percentile": _rank_pct(series.tail(252)),
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "summary_table.csv", index=False)

    rets = combo[["OVX", "VIX", "WTI", "Brent", "USO", "XLE", "SPY"]].pct_change().dropna()
    same_day = {}
    next_day = {}
    for window in (20, 60, 120, 252):
        rr = rets.tail(window)
        same_day[str(window)] = {
            "OVX_VIX": float(rr["OVX"].corr(rr["VIX"])),
            "WTI_VIX": float(rr["WTI"].corr(rr["VIX"])),
            "OVX_SPY": float(rr["OVX"].corr(rr["SPY"])),
            "WTI_SPY": float(rr["WTI"].corr(rr["SPY"])),
        }

        rr_lag = rets.tail(window + 1)
        x = rr_lag[["OVX", "WTI", "Brent"]].iloc[:-1].reset_index(drop=True)
        y = rr_lag[["VIX", "SPY", "XLE"]].iloc[1:].reset_index(drop=True)
        next_day[str(window)] = {
            "OVX_to_next_VIX": float(x["OVX"].corr(y["VIX"])),
            "WTI_to_next_VIX": float(x["WTI"].corr(y["VIX"])),
            "WTI_to_next_SPY": float(x["WTI"].corr(y["SPY"])),
            "WTI_to_next_XLE": float(x["WTI"].corr(y["XLE"])),
        }

    # Figure 1: 2026 path of oil prices and volatility indicators.
    plt.style.use("seaborn-v0_8-whitegrid")
    plot_cols = ["OVX", "VIX", "WTI", "Brent"]
    norm = ytd[plot_cols].div(ytd[plot_cols].iloc[0]).mul(100)
    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=160)
    palette = {
        "OVX": "#c1121f",
        "VIX": "#2f4858",
        "WTI": "#d95f02",
        "Brent": "#577590",
    }
    for col in plot_cols:
        ax.plot(norm.index, norm[col], label=col, lw=2.0, color=palette[col])
    ax.axhline(100, color="#777777", lw=1, ls="--", alpha=0.7)
    ax.axvline(CHECKPOINT, color="#333333", lw=1.2, ls=":", alpha=0.8)
    ax.text(CHECKPOINT, ax.get_ylim()[1] * 0.94, "May 20 article", ha="left", va="top", fontsize=9)
    ax.set_title("Oil volatility, equity volatility, and crude prices in 2026")
    ax.set_ylabel("Index level, 2026 first observation = 100")
    ax.legend(frameon=True, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "fig_1_oil_vix_2026_path.png", bbox_inches="tight")
    plt.close(fig)

    # Figure 2: spillover diagnostics by correlation window.
    windows = ["20", "60", "120", "252"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), dpi=160, sharey=True)
    same = pd.DataFrame(same_day).T
    same[["OVX_VIX", "WTI_VIX", "OVX_SPY", "WTI_SPY"]].plot(kind="bar", ax=axes[0])
    axes[0].axhline(0, color="#333333", lw=1)
    axes[0].set_title("Same-day return correlations")
    axes[0].set_xlabel("Trailing trading days")
    axes[0].set_ylabel("Correlation")
    axes[0].legend(frameon=True, fontsize=8)

    nxt = pd.DataFrame(next_day).T
    nxt[["OVX_to_next_VIX", "WTI_to_next_VIX", "WTI_to_next_SPY", "WTI_to_next_XLE"]].plot(kind="bar", ax=axes[1])
    axes[1].axhline(0, color="#333333", lw=1)
    axes[1].set_title("Next-day lead-lag correlations")
    axes[1].set_xlabel("Trailing trading days")
    axes[1].legend(frameon=True, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_2_spillover_correlations.png", bbox_inches="tight")
    plt.close(fig)

    peaks = {}
    for col in ["OVX", "VIX", "OVX_VIX_RATIO", "WTI", "Brent"]:
        idx = ytd[col].idxmax()
        peaks[col] = {"date": idx.date().isoformat(), "value": float(ytd.loc[idx, col])}

    checkpoint_values = {
        d: {col: float(combo.loc[pd.Timestamp(d), col]) for col in ["OVX", "VIX", "OVX_VIX_RATIO", "WTI", "Brent", "SPY"]}
        for d in ["2026-05-20", "2026-06-04", "2026-06-05", "2026-06-10", "2026-06-11"]
        if pd.Timestamp(d) in combo.index
    }

    result = {
        "experiment_id": "trending_2026_06_12_oil_vix_spillover",
        "task_id": "trending_repost_2026_06_12_地緣波動",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "data_source": {
            "price_source": "Yahoo Finance via yfinance",
            "tickers": TICKERS,
            "start_date": START_DATE,
            "end_date_exclusive": END_DATE,
            "latest_common_date": latest_date.date().isoformat(),
            "public_refs": [
                "https://fred.stlouisfed.org/series/OVXCLS",
                "https://www.cboe.com/us/indices/dashboard/ovx/",
                "https://www.cmegroup.com/videos/2026/06/10/wti-crude-oil-futures-climbed-past-91-amid-middle-east-conflict.html",
            ],
        },
        "sample": {
            "common_days": int(len(combo)),
            "first_common_date": combo.index[0].date().isoformat(),
            "last_common_date": latest_date.date().isoformat(),
        },
        "latest": {
            "date": latest_date.date().isoformat(),
            "OVX": float(latest["OVX"]),
            "VIX": float(latest["VIX"]),
            "OVX_VIX_RATIO": float(latest["OVX_VIX_RATIO"]),
            "WTI": float(latest["WTI"]),
            "Brent": float(latest["Brent"]),
            "USO": float(latest["USO"]),
            "XLE": float(latest["XLE"]),
            "SPY": float(latest["SPY"]),
        },
        "summary_table": rows,
        "same_day_correlations": same_day,
        "next_day_correlations": next_day,
        "ytd_peaks": peaks,
        "checkpoint_values": checkpoint_values,
        "charts": [
            "fig_1_oil_vix_2026_path.png",
            "fig_2_spillover_correlations.png",
        ],
        "article_ready_numbers": {
            "latest_date": latest_date.date().isoformat(),
            "ovx_latest": f"{latest['OVX']:.2f}",
            "vix_latest": f"{latest['VIX']:.2f}",
            "wti_latest": f"{latest['WTI']:.2f}",
            "brent_latest": f"{latest['Brent']:.2f}",
            "ratio_latest": f"{latest['OVX_VIX_RATIO']:.2f}",
            "ovx_full_percentile": f"P{_rank_pct(combo['OVX']) * 100:.0f}",
            "vix_full_percentile": f"P{_rank_pct(combo['VIX']) * 100:.0f}",
            "ratio_full_percentile": f"P{_rank_pct(combo['OVX_VIX_RATIO']) * 100:.0f}",
            "ovx_5d_change": _fmt_pct(_pct_change(combo["OVX"], 5)),
            "vix_5d_change": _fmt_pct(_pct_change(combo["VIX"], 5)),
            "wti_5d_change": _fmt_pct(_pct_change(combo["WTI"], 5)),
            "brent_5d_change": _fmt_pct(_pct_change(combo["Brent"], 5)),
            "ovx_since_may20": _fmt_pct(_change_between(combo, "OVX", CHECKPOINT)),
            "vix_since_may20": _fmt_pct(_change_between(combo, "VIX", CHECKPOINT)),
            "ratio_since_may20": _fmt_pct(_change_between(combo, "OVX_VIX_RATIO", CHECKPOINT)),
            "wti_since_may20": _fmt_pct(_change_between(combo, "WTI", CHECKPOINT)),
            "brent_since_may20": _fmt_pct(_change_between(combo, "Brent", CHECKPOINT)),
            "spy_since_may20": _fmt_pct(_change_between(combo, "SPY", CHECKPOINT)),
            "ytd_ovx_peak": f"{peaks['OVX']['value']:.2f} on {peaks['OVX']['date']}",
            "ytd_vix_peak": f"{peaks['VIX']['value']:.2f} on {peaks['VIX']['date']}",
            "same_day_20d_ovx_vix_corr": f"{same_day['20']['OVX_VIX']:.2f}",
            "same_day_60d_ovx_vix_corr": f"{same_day['60']['OVX_VIX']:.2f}",
            "next_day_60d_ovx_to_vix_corr": f"{next_day['60']['OVX_to_next_VIX']:.2f}",
            "next_day_60d_wti_to_spy_corr": f"{next_day['60']['WTI_to_next_SPY']:.2f}",
        },
    }
    (OUT / "trending_2026_06_12_oil_vix_spillover_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["article_ready_numbers"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
