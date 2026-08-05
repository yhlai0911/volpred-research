#!/usr/bin/env python3
"""K1677-rev 讀者文章圖表。暫住 storage/drafts/，待 platform_eng 取得 scripts/ 權限後收編。

數值一律從 experiments/K1677-rev/K1677-rev_results.json 讀取。
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
RESULTS = ROOT / "experiments" / "K1677-rev" / "K1677-rev_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

OUTCOMES = {
    "rv_mktadj": "波動（市場調整）",
    "rv_placebo_z": "波動（安慰劑對照）",
    "rv_raw_logratio": "波動（原始比值）",
    "semivar_mktadj": "下跌波動（市場調整）",
    "semivar_placebo_z": "下跌波動（安慰劑對照）",
    "worstday_placebo_z": "最糟單日（安慰劑對照）",
    "amihud_mktadj": "價量衝擊（市場調整）",
    "spread_cs_mktadj": "買賣價差（市場調整）",
}

C_PASS = "#B45309"
C_FAIL = "#9CA3AF"
C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_directional(res: dict) -> Path:
    agg = res["aggregates_primary_complete_case"]
    names, tvals = [], []
    for key, label in OUTCOMES.items():
        names.append(label)
        tvals.append(agg[key]["t_cluster_directional"])

    order = np.argsort(tvals)
    names = [names[i] for i in order]
    tvals = [tvals[i] for i in order]

    fig, ax = plt.subplots(figsize=(8.8, 4.9), dpi=170)
    colors = [C_PASS if t >= 3 else C_FAIL for t in tvals]
    ax.barh(range(len(names)), tvals, color=colors, height=0.62)
    ax.axvline(0, color=C_MUTED, linewidth=1)
    ax.axvline(3, color=C_PASS, linewidth=1.4, linestyle="--")
    ax.annotate(
        "門檻 3.0",
        xy=(3, len(names) - 0.4),
        xytext=(5, 0),
        textcoords="offset points",
        fontsize=9.5,
        color=C_PASS,
    )

    ax.set_yticks(range(len(names)), names, fontsize=10, color=C_TEXT)
    ax.set_xlabel("群集層級統計量（正值＝方向支持傳染）", fontsize=10, color=C_MUTED)
    ax.set_title("八個事先宣告的指標，只有買賣價差走到門檻", fontsize=13, color=C_TEXT, pad=12)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    for i, t in enumerate(tvals):
        ax.annotate(
            f"{t:+.2f}",
            xy=(t, i),
            xytext=(6 if t >= 0 else -6, 0),
            textcoords="offset points",
            va="center",
            ha="left" if t >= 0 else "right",
            fontsize=9,
            color=C_TEXT,
        )
    ax.margins(x=0.18)

    out = ASSETS / "k1677_general_directional.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_primary_vs_sensitivity(res: dict) -> Path:
    pri = res["aggregates_primary_complete_case"]["spread_cs_mktadj"]
    sen = res["aggregates_available_peer_sensitivity"]["spread_cs_mktadj"]

    labels = [
        f"嚴格版\n（{pri['n']} 件事件，{pri['n_time_clusters']} 群）",
        f"放寬版\n（{sen['n']} 件事件，{sen['n_time_clusters']} 群）",
    ]

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.3), dpi=170)

    tvals = [pri["t_cluster_directional"], sen["t_cluster_directional"]]
    bars = axes[0].bar(labels, tvals, color=[C_FAIL, C_PASS], width=0.58)
    axes[0].axhline(3, color=C_PASS, linewidth=1.3, linestyle="--")
    axes[0].set_title("群集層級統計量", fontsize=11.5, color=C_TEXT)
    for bar, v in zip(bars, tvals):
        axes[0].annotate(
            f"{v:.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, v),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=C_TEXT,
        )

    pvals = [
        pri["p_bh_cluster_signflip_directional"],
        sen["p_bh_cluster_signflip_directional"],
    ]
    bars = axes[1].bar(labels, pvals, color=[C_FAIL, C_PASS], width=0.58)
    axes[1].axhline(0.05, color="#B91C1C", linewidth=1.3, linestyle="--")
    axes[1].annotate("門檻 0.05", xy=(1.35, 0.052), fontsize=9, color="#B91C1C", ha="right")
    axes[1].set_title("最嚴格校正後的機率值", fontsize=11.5, color=C_TEXT)
    for bar, v in zip(bars, pvals):
        axes[1].annotate(
            f"{v:.4f}",
            xy=(bar.get_x() + bar.get_width() / 2, v),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=C_TEXT,
        )

    for ax in axes:
        ax.tick_params(labelsize=9.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25, linewidth=0.6)
        ax.margins(y=0.24)

    fig.suptitle(
        "放寬版全部通過，但它的同業名單排除了後來下市與被併購的公司，因此不採用",
        fontsize=12.5,
        color=C_TEXT,
        y=1.04,
    )

    out = ASSETS / "k1677_general_primary_vs_sensitivity.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_directional(res), fig_primary_vs_sensitivity(res)):
        print(f"[K1677_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
