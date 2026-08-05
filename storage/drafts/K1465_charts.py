#!/usr/bin/env python3
"""K1465 讀者文章圖表。

暫住 storage/drafts/（內容部轄區），待 platform_eng 取得 scripts/ 權限後收編。
數值一律從 experiments/k1465/k1465_results.json 讀取。

注意：results.json 的 dow_descriptive_full.*.n 有 ×1e4 標度瑕疵（顯示 7720000 等），
本腳本一律以 dow_descriptive_full.vrp.n 為樣本數來源，已於 2026-08-05 送 request 請研究部確認。
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
RESULTS = ROOT / "experiments" / "k1465" / "k1465_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

DOW = ["週一", "週二", "週三", "週四", "週五"]
KEYS = ["0", "1", "2", "3", "4"]

C_MEAN = "#1D4ED8"
C_MED = "#B45309"
C_FULL = "#1D4ED8"
C_OOS = "#15803D"
C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _vals(block: dict, stat: str) -> list[float]:
    return [float(block[stat][k]) for k in KEYS]


def fig_mean_vs_median(res: dict) -> Path:
    full = res["dow_descriptive_full"]
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4), dpi=170, sharey=True)
    x = np.arange(len(DOW))
    width = 0.38

    for ax, key, title in (
        (axes[0], "r_on_sq_x1e4", "隔夜"),
        (axes[1], "r_id_sq_x1e4", "盤中"),
    ):
        blk = full[key]
        ax.bar(x - width / 2, _vals(blk, "mean"), width, color=C_MEAN, label="平均值")
        ax.bar(x + width / 2, _vals(blk, "median"), width, color=C_MED, label="中位數")
        ax.set_xticks(x)
        ax.set_xticklabels(DOW, fontsize=10, color=C_TEXT)
        ax.set_title(title, fontsize=12, color=C_TEXT)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25, linewidth=0.6)

    axes[0].set_ylabel("平方報酬（萬分之一）", fontsize=10, color=C_MUTED)
    axes[0].legend(frameon=False, fontsize=9.5)

    on = full["r_on_sq_x1e4"]
    fig.suptitle(
        f"隔夜週一的平均值最高（{on['mean']['0']:.4f}），中位數卻低於週五（{on['median']['0']:.4f} vs {on['median']['4']:.4f}）",
        fontsize=12.5,
        color=C_TEXT,
        y=1.02,
    )

    out = ASSETS / "k1465_general_dow_mean_vs_median.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_vrp_flat(res: dict) -> Path:
    full = res["dow_descriptive_full"]["vrp"]
    oos = res["dow_descriptive_oos"]["vrp"]
    kw = res["kruskal_wallis"]

    fig, ax = plt.subplots(figsize=(8.4, 4.5), dpi=170)
    x = np.arange(len(DOW))
    ax.plot(x, _vals(full, "mean"), color=C_FULL, marker="o", linewidth=2, label="全期")
    ax.plot(x, _vals(oos, "mean"), color=C_OOS, marker="s", linewidth=2, label="樣本外")

    ax.set_xticks(x)
    ax.set_xticklabels(DOW, fontsize=10, color=C_TEXT)
    ax.set_ylabel("恐慌溢酬平均值", fontsize=10, color=C_MUTED)
    ax.set_title("五個星期別的恐慌溢酬，兩條線都是平的", fontsize=13, color=C_TEXT, pad=12)
    ax.legend(frameon=False, fontsize=9.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)

    ax.annotate(
        f"分布一致性檢定：全期機率值 {kw['vrp_full']['p']:.3f}，樣本外 {kw['vrp_oos']['p']:.3f}（都不拒絕）",
        xy=(0.5, -0.22),
        xycoords="axes fraction",
        ha="center",
        fontsize=9.5,
        color=C_MUTED,
    )

    out = ASSETS / "k1465_general_vrp_flat.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def fig_oos_scoreboard(res: dict) -> Path:
    """results.json 未保存逐日淨值序列，故改用樣本外績效對照長條（見 draft 內註記）。"""
    bt = res["backtest_oos"]
    strat, bh = bt["strat_ret"], bt["bh_ret"]

    metrics = [
        ("年化報酬", strat["mean_ann"] * 100, bh["mean_ann"] * 100, "%"),
        ("夏普值", strat["sharpe"], bh["sharpe"], ""),
        ("最大回撤", strat["max_dd"] * 100, bh["max_dd"] * 100, "%"),
        ("期末淨值", strat["final_equity"], bh["final_equity"], ""),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(11.2, 3.9), dpi=170)
    for ax, (name, s, b, unit) in zip(axes, metrics):
        bars = ax.bar(["只做週一", "一直持有"], [s, b], color=[C_MED, C_FULL], width=0.6)
        ax.axhline(0, color=C_MUTED, linewidth=1)
        ax.set_title(name, fontsize=11.5, color=C_TEXT)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=9.5)
        for bar, val in zip(bars, (s, b)):
            va = "bottom" if val >= 0 else "top"
            ax.annotate(
                f"{val:.2f}{unit}",
                xy=(bar.get_x() + bar.get_width() / 2, val),
                xytext=(0, 5 if val >= 0 else -5),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=9.5,
                color=C_TEXT,
            )
        ax.margins(y=0.28)

    fig.suptitle(
        f"樣本外 {bt['strat_ret']['n']} 個交易日：照星期做，四項全輸",
        fontsize=13,
        color=C_TEXT,
        y=1.04,
    )

    out = ASSETS / "k1465_general_oos_equity.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_mean_vs_median(res), fig_vrp_flat(res), fig_oos_scoreboard(res)):
        print(f"[K1465_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
