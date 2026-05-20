"""K560 sector rotation rewrite figures (post-lookahead-patch honest answer).

Inputs:  experiments/k560/k560_sector_rotation_vt_results.json (post-patch, 2026-05-07)
Outputs: experiments/k560/figures/k560_pre_post_sharpe.png
         experiments/k560/figures/k560_post_patch_oos_sharpe.png
         experiments/k560/figures/k560_lookahead_illustration.png

Pre-patch numbers come from the article errata flag (mile_4ec7b75e):
  - momentum_top1 Sharpe ~2.16
  - relative_strength Sharpe ~1.876
  Sibling K562 also collapsed 2.16 -> 0.72 after the same K547-family patch.
We approximate other strategies' pre-patch values from typical lookahead inflation
factor (1.4-2.9x, per errata) anchored on the two known data points.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments" / "k560" / "k560_sector_rotation_vt_results.json"
OUT = ROOT / "experiments" / "k560" / "figures"
OUT.mkdir(parents=True, exist_ok=True)


def setup_chinese_font() -> None:
    candidates = [
        "PingFang TC", "PingFang SC", "Heiti TC", "Songti TC",
        "Hiragino Sans GB", "Microsoft JhengHei", "Microsoft YaHei",
        "Noto Sans CJK TC", "Noto Sans CJK SC", "Noto Sans TC",
        "Arial Unicode MS",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((c for c in candidates if c in available), None)
    if chosen:
        plt.rcParams["font.family"] = chosen
    plt.rcParams["axes.unicode_minus"] = False


def main() -> None:
    setup_chinese_font()
    data = json.loads(RESULTS.read_text())
    full = data["full_sample_results"]
    oos = data["cross_oos_results"]

    # ---- Strategy display labels (zh-Hant) ----
    label_map = {
        "momentum_top1": "Momentum Top1\n(動能最強單一類股)",
        "lowvol_top1": "Low-Vol Top1\n(波動最低單一類股)",
        "mean_reversion_top1": "Mean-Rev Top1\n(60 日最弱反轉)",
        "relative_strength": "Relative Strength\n(相對 SPY 強勢平均)",
        "momentum_top3": "Momentum Top3\n(動能前三名)",
        "mom_lowvol_combo": "Mom+LowVol Combo\n(動能前三再選低波)",
        "equal_weight_all_sectors": "Equal Weight 9 Sectors\n(九類股等權重)",
    }
    rotation_keys = list(label_map.keys())

    # ---- Figure 1: Pre vs post-patch Sharpe (the collapse) ----
    # Post-patch: read from results
    post = [full[k]["sharpe"] for k in rotation_keys]
    # Pre-patch: errata documents momentum_top1=2.16, relative_strength=1.876.
    # Other rotation strategies: errata says inflation factor 1.4-2.9x. We use
    # mid-range 2.0x as best-available approximation (clearly labelled "估算" in caption).
    pre_known = {"momentum_top1": 2.16, "relative_strength": 1.876}
    pre = []
    for k in rotation_keys:
        if k in pre_known:
            pre.append(pre_known[k])
        else:
            # Approximate pre-patch with 2.0x inflation factor (mid of 1.4-2.9x)
            pre.append(round(full[k]["sharpe"] * 2.0, 3))

    bench_post = full["benchmark_spy_vt_gld"]["sharpe"]

    fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=180)
    x = np.arange(len(rotation_keys))
    w = 0.38
    b1 = ax.bar(x - w/2, pre, w, color="#d9534f", alpha=0.9, label="Patch 前（含 lookahead 偏差）")
    b2 = ax.bar(x + w/2, post, w, color="#2c7be5", alpha=0.95, label="Patch 後（誠實答案）")

    ax.axhline(bench_post, ls="--", color="#5a6268", lw=1.4, alpha=0.85,
               label=f"基準 SPY-VT + GLD（Sharpe = {bench_post:.3f}）")
    ax.axhline(0, color="black", lw=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels([label_map[k] for k in rotation_keys], fontsize=8.5)
    ax.set_ylabel("Sharpe Ratio (年化)", fontsize=11)
    ax.set_title("K560：lookahead 修補前後，VIX 類股輪動策略 Sharpe 全面崩潰\n"
                 "（樣本期 2005-03-30 → 2026-05-06，n = 5,310）", fontsize=12.5, pad=12)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(-0.05, max(pre) * 1.18)

    for rect, v in zip(b1, pre):
        ax.text(rect.get_x() + rect.get_width()/2, v + 0.04, f"{v:.2f}",
                ha="center", fontsize=8, color="#8b1f1f")
    for rect, v in zip(b2, post):
        ax.text(rect.get_x() + rect.get_width()/2, v + 0.04, f"{v:.2f}",
                ha="center", fontsize=8, color="#1a4380")

    fig.text(0.5, 0.005,
             "Patch 前數字：momentum_top1 = 2.16、relative_strength = 1.876 來自 mile_4ec7b75e errata；"
             "其餘策略依 errata 記載 1.4-2.9× 膨脹係數取中位 2.0× 估算。\n"
             "Patch 後數字 100% 來自 K560 重跑 results.json（2026-05-07）。",
             ha="center", fontsize=7.5, color="#555")
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(OUT / "k560_pre_post_sharpe.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 2: Post-patch OOS Sharpe across 3 windows ----
    fig, ax = plt.subplots(figsize=(11.5, 6.0), dpi=180)
    periods = [
        f"OOS-1 ({oos[0]['oos_start'][:7]} ~ {oos[0]['oos_end'][:7]})",
        f"OOS-2 ({oos[1]['oos_start'][:7]} ~ {oos[1]['oos_end'][:7]})",
        f"OOS-3 ({oos[2]['oos_start'][:7]} ~ {oos[2]['oos_end'][:7]})",
    ]
    keys_oos = rotation_keys + ["benchmark_spy_vt_gld"]
    matrix = np.array([[oos[i][k]["sharpe"] for i in range(3)] for k in keys_oos])

    x = np.arange(len(periods))
    w = 0.10
    palette = plt.get_cmap("tab10").colors
    short_labels = {
        "momentum_top1": "Mom Top1",
        "lowvol_top1": "LowVol Top1",
        "mean_reversion_top1": "MeanRev Top1",
        "relative_strength": "RelStrength",
        "momentum_top3": "Mom Top3",
        "mom_lowvol_combo": "Mom+LowVol",
        "equal_weight_all_sectors": "EqualWeight 9",
        "benchmark_spy_vt_gld": "SPY-VT+GLD（基準）",
    }
    for j, k in enumerate(keys_oos):
        offset = (j - len(keys_oos)/2) * w + w/2
        color = "#000" if k == "benchmark_spy_vt_gld" else palette[j % len(palette)]
        edgecolor = "black" if k == "benchmark_spy_vt_gld" else None
        ax.bar(x + offset, matrix[j], w, label=short_labels[k], color=color,
               edgecolor=edgecolor, linewidth=1.0 if edgecolor else 0)

    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9.5)
    ax.set_ylabel("OOS Sharpe Ratio", fontsize=11)
    ax.set_title("K560 patch 後 — 3 個 OOS 窗口的 Sharpe 全面比較\n"
                 "沒有任何輪動策略在 3 個窗口都贏基準（不滿足 OOS-consistent）",
                 fontsize=12.5, pad=12)
    ax.legend(loc="upper left", fontsize=8.5, ncol=2)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "k560_post_patch_oos_sharpe.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 3: Lookahead bug illustration ----
    fig, ax = plt.subplots(figsize=(11, 5.8), dpi=180)
    ax.axis("off")

    # Timeline
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)

    # Day labels
    for i, lab in enumerate(["t-1", "t", "t+1"]):
        ax.axvline(2 + i*3, color="#bbb", lw=1, ls="--")
        ax.text(2 + i*3, 5.6, f"Day {lab}", ha="center", fontsize=11, color="#333")

    # BUG row (red)
    ax.text(0.4, 4.4, "Patch 前（bug）", fontsize=11, color="#c0392b", weight="bold")
    ax.annotate("", xy=(5, 4.0), xytext=(5, 3.6),
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.6))
    ax.text(5, 4.1, "用 day-t 收盤後\n才知道的訊號", ha="center", fontsize=9, color="#c0392b")
    ax.text(5, 3.4, "決定 day-t 全天的權重", ha="center", fontsize=9, color="#c0392b")
    ax.text(5, 3.0, "× day-t 報酬 → 偷看未來",
            ha="center", fontsize=9.5, color="#c0392b", weight="bold")

    # FIX row (blue)
    ax.text(0.4, 1.9, "Patch 後（正確）", fontsize=11, color="#1f5fa8", weight="bold")
    ax.annotate("", xy=(5, 1.5), xytext=(2, 1.5),
                arrowprops=dict(arrowstyle="->", color="#1f5fa8", lw=1.6))
    ax.text(2, 1.1, "day t-1 收盤訊號", ha="center", fontsize=9, color="#1f5fa8")
    ax.text(5, 1.1, "套用為 day-t 權重", ha="center", fontsize=9, color="#1f5fa8")
    ax.text(8, 1.1, "結算 day-t 報酬", ha="center", fontsize=9, color="#1f5fa8")

    ax.text(5, 5.2, "K560 lookahead patch（K547-family）：sig_idx = i-1，不是 i",
            ha="center", fontsize=13, weight="bold", color="black")
    ax.text(5, 0.3,
            "Code patch: vt_w = vt_weights[sig_idx]；sec_moms / sec_vols / sec_rs 全改用 sig_idx\n"
            "（experiments/k560/k560_sector_rotation_vt.py L249-L262）",
            ha="center", fontsize=8.5, color="#555")
    fig.savefig(OUT / "k560_lookahead_illustration.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    print("Wrote:")
    for p in sorted(OUT.glob("k560_*.png")):
        print(f"  {p}  ({p.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
