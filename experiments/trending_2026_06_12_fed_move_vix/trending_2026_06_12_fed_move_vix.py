#!/usr/bin/env python3
"""Evidence package for the 2026-06-12 Fed/MOVE/VIX trending article.

The publication date is in Asia/Taipei. U.S. market data available at that
point is the 2026-06-11 close, so the yfinance end date is 2026-06-12.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf


OUT = Path(__file__).resolve().parent
START_DATE = "2003-01-01"
END_DATE = "2026-06-12"
TICKERS = ["^VIX", "^MOVE", "SPY", "TLT", "^TNX", "^IRX", "ZQ=F", "ZN=F"]


def _pct_change(series: pd.Series, days: int) -> float:
    return float(series.iloc[-1] / series.iloc[-1 - days] - 1)


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

    combo = pd.concat(
        {"VIX": close["^VIX"], "MOVE": close["^MOVE"]},
        axis=1,
    ).dropna()
    combo["MOVE_VIX_RATIO"] = combo["MOVE"] / combo["VIX"]

    latest_date = combo.index[-1]
    latest = combo.iloc[-1]

    metrics = {
        "VIX": combo["VIX"],
        "MOVE": combo["MOVE"],
        "MOVE/VIX": combo["MOVE_VIX_RATIO"],
    }
    table_rows = []
    for name, series in metrics.items():
        table_rows.append(
            {
                "metric": name,
                "latest": float(series.iloc[-1]),
                "change_1d": _pct_change(series, 1),
                "change_5d": _pct_change(series, 5),
                "change_20d": _pct_change(series, 20),
                "full_sample_percentile": _rank_pct(series),
                "one_year_percentile": _rank_pct(series.tail(252)),
            }
        )

    zq = close["ZQ=F"].dropna()
    rates = {
        "^IRX_13w_tbill_yield_pct": float(close["^IRX"].dropna().iloc[-1]),
        "^TNX_10y_yield_pct": float(close["^TNX"].dropna().iloc[-1]),
        "ZQ_front_implied_rate_pct": float(100 - zq.iloc[-1]),
        "ZQ_front_implied_rate_pct_5d_ago": float(100 - zq.iloc[-6]),
        "ZQ_front_implied_rate_pct_20d_ago": float(100 - zq.iloc[-21]),
        "ZN_front_10y_futures_price": float(close["ZN=F"].dropna().iloc[-1]),
    }
    assets = {
        "SPY_close": float(close["SPY"].dropna().iloc[-1]),
        "SPY_5d_return": _pct_change(close["SPY"].dropna(), 5),
        "TLT_close": float(close["TLT"].dropna().iloc[-1]),
        "TLT_5d_return": _pct_change(close["TLT"].dropna(), 5),
    }

    corr = {}
    returns = combo[["VIX", "MOVE"]].pct_change().dropna()
    for window in (20, 60, 120, 252):
        corr[f"{window}d"] = float(
            returns["VIX"].tail(window).corr(returns["MOVE"].tail(window))
        )
    corr["full_sample"] = float(returns["VIX"].corr(returns["MOVE"]))

    pd.DataFrame(table_rows).to_csv(OUT / "summary_table.csv", index=False)

    # Figure 1: one-year normalized MOVE and VIX.
    recent = combo.tail(252)
    normalized = recent[["VIX", "MOVE"]].div(recent[["VIX", "MOVE"]].iloc[0]).mul(100)
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=160)
    ax.plot(normalized.index, normalized["VIX"], label="VIX, normalized", lw=2.2)
    ax.plot(normalized.index, normalized["MOVE"], label="MOVE, normalized", lw=2.2)
    ax.axhline(100, color="#777777", lw=1, ls="--", alpha=0.7)
    ax.set_title("MOVE vs VIX, normalized to 100 one year earlier")
    ax.set_ylabel("Index level, first observation = 100")
    ax.legend(frameon=True)
    fig.tight_layout()
    fig.savefig(OUT / "fig_1_move_vix_normalized_1y.png", bbox_inches="tight")
    plt.close(fig)

    # Figure 2: full-sample MOVE/VIX ratio and current historical location.
    ratio = combo["MOVE_VIX_RATIO"]
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), dpi=160, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(ratio.index, ratio, color="#2f4858", lw=1.1)
    axes[0].axhline(ratio.median(), color="#d95f02", lw=1.4, ls="--", label=f"Median {ratio.median():.2f}")
    axes[0].scatter([latest_date], [latest["MOVE_VIX_RATIO"]], color="#c1121f", s=45, zorder=5, label=f"Latest {latest['MOVE_VIX_RATIO']:.2f}")
    axes[0].set_title("MOVE/VIX ratio since 2003")
    axes[0].set_ylabel("MOVE / VIX")
    axes[0].legend(frameon=True)
    axes[1].hist(ratio, bins=60, color="#7aa6c2", edgecolor="white")
    axes[1].axvline(latest["MOVE_VIX_RATIO"], color="#c1121f", lw=2.0, label=f"Latest P{_rank_pct(ratio) * 100:.0f}")
    axes[1].axvline(ratio.median(), color="#d95f02", lw=1.5, ls="--", label="Median")
    axes[1].set_xlabel("MOVE / VIX")
    axes[1].set_ylabel("Trading days")
    axes[1].legend(frameon=True)
    fig.tight_layout()
    fig.savefig(OUT / "fig_2_move_vix_ratio_history.png", bbox_inches="tight")
    plt.close(fig)

    result = {
        "experiment_id": "trending_2026_06_12_fed_move_vix",
        "task_id": "trending_repost_2026_06_12_fed降息",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "data_source": {
            "price_source": "Yahoo Finance via yfinance",
            "tickers": TICKERS,
            "start_date": START_DATE,
            "end_date_exclusive": END_DATE,
            "latest_common_move_vix_date": latest_date.date().isoformat(),
            "public_methodology_refs": [
                "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
                "https://cdn.cboe.com/resources/indices/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf",
                "https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-move-index",
            ],
        },
        "sample": {
            "move_vix_common_days": int(len(combo)),
            "first_common_date": combo.index[0].date().isoformat(),
            "last_common_date": latest_date.date().isoformat(),
        },
        "latest": {
            "date": latest_date.date().isoformat(),
            "VIX": float(latest["VIX"]),
            "MOVE": float(latest["MOVE"]),
            "MOVE_VIX_RATIO": float(latest["MOVE_VIX_RATIO"]),
            **rates,
            **assets,
        },
        "summary_table": table_rows,
        "correlations": corr,
        "recent_checkpoint_dates": {
            d: {
                "VIX": float(combo.loc[pd.Timestamp(d), "VIX"]),
                "MOVE": float(combo.loc[pd.Timestamp(d), "MOVE"]),
                "MOVE_VIX_RATIO": float(combo.loc[pd.Timestamp(d), "MOVE_VIX_RATIO"]),
                "ZQ_front_implied_rate_pct": float(100 - close.loc[pd.Timestamp(d), "ZQ=F"]),
            }
            for d in ("2026-06-04", "2026-06-05", "2026-06-09", "2026-06-10", "2026-06-11")
            if pd.Timestamp(d) in combo.index and pd.Timestamp(d) in close.index
        },
        "charts": [
            "fig_1_move_vix_normalized_1y.png",
            "fig_2_move_vix_ratio_history.png",
        ],
        "article_ready_numbers": {
            "latest_date": latest_date.date().isoformat(),
            "vix_latest": f"{latest['VIX']:.2f}",
            "move_latest": f"{latest['MOVE']:.2f}",
            "ratio_latest": f"{latest['MOVE_VIX_RATIO']:.2f}",
            "ratio_full_percentile": f"P{_rank_pct(ratio) * 100:.0f}",
            "ratio_one_year_percentile": f"P{_rank_pct(ratio.tail(252)) * 100:.0f}",
            "move_full_percentile": f"P{_rank_pct(combo['MOVE']) * 100:.0f}",
            "vix_full_percentile": f"P{_rank_pct(combo['VIX']) * 100:.0f}",
            "move_5d_change": _fmt_pct(_pct_change(combo["MOVE"], 5)),
            "vix_5d_change": _fmt_pct(_pct_change(combo["VIX"], 5)),
            "ratio_5d_change": _fmt_pct(_pct_change(ratio, 5)),
            "zq_implied_rate_latest": f"{rates['ZQ_front_implied_rate_pct']:.2f}%",
            "zq_implied_rate_5d_ago": f"{rates['ZQ_front_implied_rate_pct_5d_ago']:.2f}%",
            "spy_5d_return": _fmt_pct(assets["SPY_5d_return"]),
            "tlt_5d_return": _fmt_pct(assets["TLT_5d_return"]),
            "corr_20d": f"{corr['20d']:.2f}",
            "corr_60d": f"{corr['60d']:.2f}",
        },
    }
    (OUT / "trending_2026_06_12_fed_move_vix_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result["article_ready_numbers"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
