#!/usr/bin/env python3
"""K1700 讀者文章圖表。暫住 storage/drafts/，待 platform_eng 取得 scripts/ 權限後收編。

數值一律從 experiments/K1700/k1700_results.json 讀取。
注意：results.json 只保存分位數摘要，未保存 17,199 個視窗的逐筆序列，
故第一張圖畫的是分位數區間而非直方圖（實驗端另有 fig1_rolling_30y_cagr.png）。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["PingFang TC", "PingFang HK", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiments" / "K1700" / "k1700_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_TR = "#1D4ED8"
C_PR = "#6B7280"
C_TARGET = "#B91C1C"
C_DD = "#B45309"
C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_cagr_distribution(res: dict) -> Path:
    rows = [
        ("含息（股息再投入）", res["spx_total_return_30y"], C_TR),
        ("只看指數不含息", res["spx_price_only_30y"], C_PR),
    ]
    target = res["target_cagr"] * 100

    fig, ax = plt.subplots(figsize=(9.0, 4.3), dpi=170)
    for i, (label, blk, color) in enumerate(rows):
        p5, p95 = blk["cagr_p5"] * 100, blk["cagr_p95"] * 100
        med = blk["cagr_median"] * 100
        lo, hi = blk["cagr_min"] * 100, blk["cagr_max"] * 100
        y = len(rows) - 1 - i

        ax.plot([lo, hi], [y, y], color=color, linewidth=1.6, alpha=0.5, zorder=1)
        ax.plot([p5, p95], [y, y], color=color, linewidth=9, alpha=0.35, solid_capstyle="butt", zorder=2)
        ax.plot([med], [y], marker="o", color=color, markersize=11, zorder=3)
        ax.plot([hi], [y], marker="|", color=color, markersize=16, markeredgewidth=2.2, zorder=3)

        ax.annotate(f"中位數 {med:.2f}%", xy=(med, y), xytext=(0, 15), textcoords="offset points",
                    ha="center", fontsize=9.5, color=C_TEXT)
        ax.annotate(f"史上最佳 {hi:.2f}%", xy=(hi, y), xytext=(6, -16), textcoords="offset points",
                    ha="left", fontsize=9, color=color)
        ax.annotate(f"最差 {lo:.2f}%", xy=(lo, y), xytext=(-6, -16), textcoords="offset points",
                    ha="right", fontsize=9, color=color)

    ax.axvline(target, color=C_TARGET, linewidth=1.8, linestyle="--")
    ax.annotate(f"目標 {target:.0f}%", xy=(target, len(rows) - 0.45), xytext=(6, 0),
                textcoords="offset points", fontsize=10, color=C_TARGET)

    n = res["spx_total_return_30y"]["n_windows"]
    ax.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)], fontsize=11, color=C_TEXT)
    ax.set_xlabel("三十年年化報酬（%）　粗段為第 5 到第 95 百分位，細線為全距", fontsize=10, color=C_MUTED)
    ax.set_title(f"{n:,} 個三十年區間，沒有一個碰到目標線", fontsize=13.5, color=C_TEXT, pad=14)
    ax.set_ylim(-0.7, len(rows) - 0.15)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    out = ASSETS / "k1700_general_cagr_distribution.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_leverage_tradeoff(res: dict) -> Path:
    wanted = ["1x 免費借貸（理論上界）", "1.5x 實際短率+1pp", "2x 實際短率+1pp"]
    pretty = ["不借錢", "借到 1.5 倍", "借到 2 倍"]
    rows = {r["label"]: r for r in res["leverage_30y"]}
    picked = [rows[w] for w in wanted]

    share = [r["share_ge_target"] * 100 for r in picked]
    mdd = [abs(r["mdd_median"]) * 100 for r in picked]

    x = np.arange(len(pretty))
    fig, ax = plt.subplots(figsize=(8.8, 4.5), dpi=170)
    width = 0.36
    b1 = ax.bar(x - width / 2, share, width, color=C_TR, label="達標比例")
    b2 = ax.bar(x + width / 2, mdd, width, color=C_DD, label="最大回撤中位數（取絕對值）")

    for bars, vals in ((b1, share), (b2, mdd)):
        for bar, v in zip(bars, vals):
            ax.annotate(f"{v:.2f}%", xy=(bar.get_x() + bar.get_width() / 2, v),
                        xytext=(0, 4), textcoords="offset points", ha="center",
                        fontsize=9.5, color=C_TEXT)

    ax.set_xticks(x, pretty, fontsize=11, color=C_TEXT)
    ax.set_ylabel("百分比", fontsize=10, color=C_MUTED)
    ax.set_title("借得越多達標率越高，代價是回撤同步變深", fontsize=13.5, color=C_TEXT, pad=12)
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.margins(y=0.2)
    ax.annotate(
        "借貸成本採當時三個月國庫券利率加一個百分點；未計交易成本與內扣費用，故對槓桿有利",
        xy=(0.5, -0.19), xycoords="axes fraction", ha="center", fontsize=9, color=C_MUTED,
    )

    out = ASSETS / "k1700_general_leverage_tradeoff.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_cagr_distribution(res), fig_leverage_tradeoff(res)):
        print(f"[K1700_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
