#!/usr/bin/env python3
"""K1696 讀者文章圖表。暫住 storage/drafts/，待 platform_eng 取得 scripts/ 權限後收編。

數值一律從 experiments/K1696/K1696_results.json 讀取。
results.json 未保存利差波動的逐日序列，故第二張圖改為樣本外損失對照（原時間序列圖見實驗端）。
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
RESULTS = ROOT / "experiments" / "K1696" / "K1696_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

ASSETS_LABEL = {"SPY": "標普 500", "HYG": "高收益債", "IWM": "小型股"}
HORIZONS = [1, 21, 63]
H_LABEL = {1: "明天", 21: "未來 21 天", 63: "未來 63 天"}

C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_heatmap(res: dict) -> Path:
    oos = res["oos"]
    grid = np.zeros((3, 3))
    for i, a in enumerate(ASSETS_LABEL):
        for j, h in enumerate(HORIZONS):
            grid[i, j] = oos[f"{a}_h{h}"]["dm_hln_qlike"]["M3_vs_M2"]["t_stat"]

    vmax = float(np.abs(grid).max())
    fig, ax = plt.subplots(figsize=(7.6, 4.4), dpi=170)
    im = ax.imshow(grid, cmap="RdBu_r", vmin=-vmax, vmax=vmax)

    for i in range(3):
        for j in range(3):
            val = grid[i, j]
            ax.text(
                j,
                i,
                f"{val:+.2f}",
                ha="center",
                va="center",
                fontsize=12,
                color="white" if abs(val) > vmax * 0.55 else C_TEXT,
            )

    ax.set_xticks(range(3), [H_LABEL[h] for h in HORIZONS], fontsize=10.5, color=C_TEXT)
    ax.set_yticks(range(3), list(ASSETS_LABEL.values()), fontsize=10.5, color=C_TEXT)
    ax.set_title("加了利差波動之後，預測變好還是變差", fontsize=13, color=C_TEXT, pad=12)
    cbar = fig.colorbar(im, ax=ax, shrink=0.82)
    cbar.set_label("正值＝加了之後更差", fontsize=9.5, color=C_MUTED)
    ax.annotate(
        "九格裡七格為正；小型股・明天那格達到高度顯著",
        xy=(0.5, -0.2),
        xycoords="axes fraction",
        ha="center",
        fontsize=9.5,
        color=C_MUTED,
    )

    out = ASSETS / "k1696_general_dm_heatmap.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_loss_delta(res: dict) -> Path:
    oos = res["oos"]
    cells, m2, m3 = [], [], []
    for a in ASSETS_LABEL:
        for h in HORIZONS:
            blk = oos[f"{a}_h{h}"]["model_losses"]
            cells.append(f"{ASSETS_LABEL[a]}・{H_LABEL[h]}")
            m2.append(blk["M2"]["qlike_mean"])
            m3.append(blk["M3"]["qlike_mean"])

    pct = [(b - a) / a * 100 for a, b in zip(m2, m3)]
    order = np.argsort(pct)[::-1]
    cells = [cells[i] for i in order]
    pct = [pct[i] for i in order]

    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=170)
    colors = ["#B45309" if p > 0 else "#15803D" for p in pct]
    ax.barh(range(len(cells)), pct, color=colors, height=0.62)
    ax.axvline(0, color=C_MUTED, linewidth=1)
    ax.set_yticks(range(len(cells)), cells, fontsize=10, color=C_TEXT)
    ax.invert_yaxis()
    ax.set_xlabel("加了利差波動之後，損失分數變化（%）", fontsize=10, color=C_MUTED)
    ax.set_title("在已經有 MOVE 的模型上再加利差波動，九格裡七格變差", fontsize=13, color=C_TEXT, pad=12)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    for i, p in enumerate(pct):
        ax.annotate(
            f"{p:+.1f}%",
            xy=(p, i),
            xytext=(6 if p >= 0 else -6, 0),
            textcoords="offset points",
            va="center",
            ha="left" if p >= 0 else "right",
            fontsize=9,
            color=C_TEXT,
        )
    ax.margins(x=0.16)

    out = ASSETS / "k1696_general_loss_delta.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_heatmap(res), fig_loss_delta(res)):
        print(f"[K1696_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
