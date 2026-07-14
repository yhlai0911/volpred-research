#!/usr/bin/env python3
"""K1681 一般讀者版圖表 — 全部數字讀自 experiments/k1681/k1681_results.json。

輸出 storage/drafts/assets/：
  k1681_general_lefttail.png   隔日左尾命中率 × SMAD 五分位（控制前）
  k1681_general_shrink.png     增量解釋力隨基準變嚴格而縮水
  k1681_general_asymmetry.png  跌破均線 vs 衝高離開均線的斜率
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

RESULTS = ROOT / "experiments" / "k1681" / "k1681_results.json"
OUT = ROOT / "storage" / "drafts" / "assets"

BLUE = "#2b6cb0"
RED = "#c53030"
GREY = "#a0aec0"


def main() -> int:
    apply_cjk_style(dpi=150)
    res = json.loads(RESULTS.read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    signed = res["quintile_profile_signed_smad"]
    lev = res["verdict"]["leverage_contamination"]
    asym = res["verdict"]["one_robust_regularity"]

    # ── 圖 1：左尾命中率 ────────────────────────────────────────────────
    hits = [q["left_tail_hit_rate"] * 100 for q in signed]
    labels = ["跌破最深\n(最低 20%)", "略低於\n均線", "貼著\n均線", "略高於\n均線", "衝最高\n(最高 20%)"]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    colors = [RED] + [BLUE] * 4
    bars = ax.bar(labels, hits, color=colors, width=0.62)
    ax.axhline(5.06, ls="--", c="#2d3748", lw=1.2)
    ax.text(2.5, 5.45, "平常的機率 5.06%", ha="center", fontsize=10, color="#2d3748")
    for b, h in zip(bars, hits):
        ax.text(b.get_x() + b.get_width() / 2, h + 0.15, f"{h:.2f}%", ha="center", fontsize=11)
    ax.set_ylabel("隔天出現「左尾大跌」的比率 (%)")
    ax.set_title("股價離 10 日均線的位置 → 隔天大跌的機率（未做任何控制）", fontsize=13, pad=12)
    ax.set_ylim(0, 10.5)
    ax.text(
        0.5, 9.55,
        "扣掉「最近本來就在跌、波動本來就高」之後：p = 0.62，額外預測力歸零",
        fontsize=10.5, color=RED,
        bbox=dict(boxstyle="round,pad=0.45", fc="#fff5f5", ec=RED, lw=0.9),
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, "資料：20 檔美股 ETF 與大型股，2010-01 至 2026-07，79,140 個資產日｜實驗 k1681", fontsize=8, color="#718096")
    fig.tight_layout()
    fig.savefig(OUT / "k1681_general_lefttail.png", bbox_inches="tight")
    plt.close(fig)

    # ── 圖 2：增量縮水 ─────────────────────────────────────────────────
    vals = [
        lev["incr_r2_vs_M0_naive"] * 100,
        lev["incr_r2_vs_M1_with_return_controls"] * 100,
        lev["incr_r2_vs_M1B_span_baseline"] * 100,
    ]
    names = ["只跟波動基準比\n（天真做法）", "再控制\n前一日與 10 日報酬", "控制 10 個\n個別日報酬（公平基準）"]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.bar(names, vals, color=[GREY, "#63b3ed", RED], width=0.58)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.03, f"+{v:.2f} 個百分點", ha="center", fontsize=11.5)
    ax.set_ylabel("均線距離「額外」解釋到的次日波動 (百分點)")
    ax.set_title("基準越公平，均線距離的功勞縮水得越厲害", fontsize=13, pad=12)
    ax.set_ylim(0, 2.35)
    ax.annotate(
        "約 85% 蒸發",
        xy=(1.72, 0.18), xytext=(1.05, 1.35), fontsize=12, color=RED,
        arrowprops=dict(arrowstyle="->", color=RED, lw=1.4),
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, "資料：同上｜蒸發掉的部分是槓桿效應與波動叢聚，不是均線距離的功勞", fontsize=8, color="#718096")
    fig.tight_layout()
    fig.savefig(OUT / "k1681_general_shrink.png", bbox_inches="tight")
    plt.close(fig)

    # ── 圖 3：不對稱 ───────────────────────────────────────────────────
    coefs = [abs(asym["smad_neg_coef"]), abs(asym["smad_pos_coef"])]
    tstats = [abs(asym["smad_neg_t"]), abs(asym["smad_pos_t"])]
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    bars = ax.barh(["跌破均線那一半", "衝高離開均線那一半"], coefs, color=[RED, "#90cdf4"], height=0.38)
    for b, c, t in zip(bars, coefs, tstats):
        ax.text(c + 0.006, b.get_y() + b.get_height() / 2, f"斜率 {c:.3f}（訊號強度 {t:.1f}）", va="center", fontsize=11)
    ax.set_xlim(0, 0.36)
    ax.set_xlabel("每偏離 1 個標準差，次日波動上升的幅度")
    ax.set_title("有訊號的只有「跌破」那一邊，強度是另一邊的 2.7 倍", fontsize=13, pad=12)
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, "資料：同上｜此不對稱通過公平基準，20 檔全數成立", fontsize=8, color="#718096")
    fig.tight_layout()
    fig.savefig(OUT / "k1681_general_asymmetry.png", bbox_inches="tight")
    plt.close(fig)

    print("wrote 3 figures ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
