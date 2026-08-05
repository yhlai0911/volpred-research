#!/usr/bin/env python3
"""K1704 讀者文章圖表。暫住 storage/drafts/，待 platform_eng 取得 scripts/ 權限後收編。

數值一律從 experiments/k1704/K1704_results.json 讀取。
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
RESULTS = ROOT / "experiments" / "k1704" / "K1704_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

TARGETS = {
    "rv_1min": "一分鐘",
    "rv_5min": "五分鐘",
    "rv_10min": "十分鐘",
    "parkinson": "高低價振幅",
    "r2_day": "當日漲跌幅平方",
    "consensus_weighted": "加權共識",
}
MODELS = {"HAR_RV5": "多尺度模型", "EWMA_R2": "指數加權", "GJR_GARCH": "不對稱模型"}
COLORS = {"HAR_RV5": "#1D4ED8", "EWMA_R2": "#B45309", "GJR_GARCH": "#6B7280"}

C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_qlike_by_proxy(res: dict) -> Path:
    fig, ax = plt.subplots(figsize=(9.4, 4.8), dpi=170)
    x = np.arange(len(TARGETS))
    width = 0.26

    for i, (mk, ml) in enumerate(MODELS.items()):
        vals = [res["targets"][t]["metrics"][mk]["qlike"] for t in TARGETS]
        ax.bar(x + (i - 1) * width, vals, width, color=COLORS[mk], label=ml)

    ax.set_yscale("log")
    ax.set_xticks(x, list(TARGETS.values()), fontsize=10, color=C_TEXT)
    ax.set_ylabel("損失分數（對數軸，越小越好）", fontsize=10, color=C_MUTED)
    ax.set_title("六把尺量同一件事，每一把的第一名都是多尺度模型", fontsize=13, color=C_TEXT, pad=12)
    ax.legend(frameon=False, fontsize=9.5, ncol=3, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6, which="both")
    ax.annotate(
        "改用對數軸，否則「當日漲跌幅平方」那組會把其他五組壓平",
        xy=(0.5, -0.18),
        xycoords="axes fraction",
        ha="center",
        fontsize=9,
        color=C_MUTED,
    )

    out = ASSETS / "k1704_general_qlike_by_proxy.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_split_oos(res: dict) -> Path:
    split = res["split_oos_robustness"]
    segs = [
        ("early_oos", "前段"),
        ("late_oos", "後段"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(9.8, 4.3), dpi=170, sharey=True)
    for ax, (key, label) in zip(axes, segs):
        blk = split[key]["consensus_target"]
        vals = [blk["metrics"][m]["qlike"] for m in MODELS]
        bars = ax.bar(list(MODELS.values()), vals, color=[COLORS[m] for m in MODELS], width=0.6)
        for bar, v in zip(bars, vals):
            ax.annotate(
                f"{v:.4f}",
                xy=(bar.get_x() + bar.get_width() / 2, v),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                fontsize=9.5,
                color=C_TEXT,
            )
        ax.set_title(
            f"{label}（{blk['n_oos']} 天，{split[key]['date_start']} 起）",
            fontsize=11.5,
            color=C_TEXT,
        )
        ax.tick_params(labelsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25, linewidth=0.6)
        ax.margins(y=0.2)

    axes[0].set_ylabel("加權共識下的損失分數", fontsize=10, color=C_MUTED)
    fig.suptitle("驗收期切一半，排名還是一樣", fontsize=13, color=C_TEXT, y=1.03)

    out = ASSETS / "k1704_general_split_oos.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_qlike_by_proxy(res), fig_split_oos(res)):
        print(f"[K1704_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
