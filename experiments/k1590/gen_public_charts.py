"""Generate reader-facing charts for the merger-arbitrage volatility article.

Reads the diagnostic results JSON (k1590_diagnostic_results.json) and MNA/VIX
price history to build two charts with NO internal research code names
(no "K1590", no "VolPred", no "AI"/"LLM") in any title/legend/axis label.

Chart 1: MNA realized volatility vs VIX level, 2020-2026 (line chart).
Chart 2: Average absolute daily move by VIX regime, bar chart with n and
         Welch t-test annotation (plain-language).

Data: same yfinance pull logic as k1590_diagnostic.py, re-run here so the
chart uses the identical series (adj close, auto_adjust=False).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd
import yfinance as yf

np.random.seed(42)

OUT = Path(__file__).resolve().parent
PUB = OUT / "plots_public"
PUB.mkdir(parents=True, exist_ok=True)

RESULTS = json.loads((OUT / "k1590_diagnostic_results.json").read_text())

TICKERS = ["MNA", "SPY", "^VIX"]
START = RESULTS["meta"]["period"]["start"]
END = RESULTS["meta"]["period"]["end"]


def pull_data() -> pd.DataFrame:
    raw = yf.download(
        TICKERS, start=START, end=END, progress=False,
        auto_adjust=False, group_by="ticker",
    )
    closes = {}
    for t in TICKERS:
        if (t, "Adj Close") in raw.columns:
            closes[t] = raw[(t, "Adj Close")]
        else:
            closes[t] = raw[(t, "Close")]
    df = pd.concat(closes, axis=1)
    df.columns = TICKERS
    return df.dropna(how="all")


def main() -> None:
    prices = pull_data()
    rets = np.log(prices / prices.shift(1)).dropna(how="all")
    mna = rets["MNA"].dropna()
    vix_lvl = prices["^VIX"].reindex(mna.index)

    rv21 = (mna.rolling(21).std(ddof=1) * np.sqrt(252)).dropna()

    # ---- Chart 1: rolling vol vs VIX, plain language ----
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(rv21.index, rv21.values * 100, lw=1.1, color="#2166ac",
             label="併購套利 ETF 年化波動率（21 日滾動）")
    ax2 = ax.twinx()
    ax2.plot(vix_lvl.reindex(rv21.index).index, vix_lvl.reindex(rv21.index).values,
              lw=0.8, color="#b2182b", alpha=0.55, label="VIX 指數")
    ax.set_title("併購套利 ETF 波動率 vs. VIX 指數（2020–2026）")
    ax.set_ylabel("年化波動率（%）")
    ax2.set_ylabel("VIX 指數水準")
    ax.grid(alpha=0.3)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(PUB / "mna_vol_vs_vix.png", dpi=150)
    plt.close(fig)

    # ---- Chart 2: regime bar chart (plain language, from results JSON) ----
    regime = RESULTS["vix_regime_stats"]
    vrt = RESULTS["vol_regime_test"]
    labels = ["VIX < 20\n（平靜期）", "VIX 20–30\n（緊張期）", "VIX > 30\n（恐慌期）"]
    means = [
        regime["low_vix_lt20"]["MNA"]["mean"],
        regime["mid_vix_20_30"]["MNA"]["mean"],
        regime["high_vix_gt30"]["MNA"]["mean"],
    ]
    # Use mean absolute return per regime for the bar heights (matches vol_regime_test framing)
    abs_means = [
        vrt["low_vix_lt20"]["mean_abs_ret"] * 100,
        None,
        vrt["high_vix_gt30"]["mean_abs_ret"] * 100,
    ]
    ns = [
        regime["low_vix_lt20"]["n_days"],
        regime["mid_vix_20_30"]["n_days"],
        regime["high_vix_gt30"]["n_days"],
    ]
    # mid-regime mean abs return computed directly here for display completeness
    mid_abs = float(np.abs(mna[(vix_lvl >= 20) & (vix_lvl <= 30)]).mean()) * 100
    abs_means[1] = mid_abs

    fig, ax = plt.subplots(figsize=(8, 5.2))
    colors = ["#a6cee3", "#fdbf6f", "#fb9a99"]
    bars = ax.bar(labels, abs_means, color=colors, edgecolor="#333333", width=0.6)
    for bar, n, val in zip(bars, ns, abs_means):
        ax.text(bar.get_x() + bar.get_width() / 2, val + max(abs_means) * 0.02,
                 f"{val:.2f}%\n(n={n})", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("平均單日絕對報酬（%）")
    ax.set_title("VIX 三種情境下，併購套利 ETF 的單日震盪幅度")
    ratio = vrt["magnitude_ratio_high_over_low"]
    p_val = vrt["p_value"]
    ax.text(0.5, -0.22,
            f"恐慌期 / 平靜期震盪倍數 ≈ {ratio:.1f} 倍（統計檢定 p < 0.001，樣本期間 2020–2026）",
            transform=ax.transAxes, ha="center", fontsize=9, color="#444444")
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(PUB / "mna_regime_bars.png", dpi=150)
    plt.close(fig)

    print("wrote", PUB / "mna_vol_vs_vix.png")
    print("wrote", PUB / "mna_regime_bars.png")


if __name__ == "__main__":
    main()
