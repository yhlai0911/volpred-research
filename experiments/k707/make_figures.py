"""K707 Investor FAQ — figure generation.

Three figures:
  (a) k707_category_distribution.png — 5 question categories × question count
  (b) k707_confidence_ranking.png    — top-10 high-confidence answers + key metric
  (c) k707_answers_heatmap.png       — 4 personas × 5 categories action map
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k707_results.json"

plt.rcParams["font.sans-serif"] = [
    "PingFang TC", "Heiti TC", "Hiragino Sans GB", "Microsoft YaHei",
    "Noto Sans CJK TC", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    faq = data["faq"]
    categories = data["category_breakdown"]
    conf_dist = data["confidence_distribution"]

    # ============================================================
    # Fig A: 5 category × question count + confidence stacked
    # ============================================================
    cat_labels = {
        "market_prediction": "市場預測",
        "asset_allocation": "資產配置",
        "vt_strategy": "VT 策略",
        "trading_execution": "交易執行",
        "drawdown_risk": "風險控制",
        "methodology": "方法論",
        "summary": "總結",
    }
    cat_order = [
        "asset_allocation", "vt_strategy", "trading_execution",
        "market_prediction", "methodology", "drawdown_risk", "summary",
    ]

    # build counts of high vs medium per category
    qmap = {q["id"]: q for q in faq}
    high_counts, med_counts = [], []
    for cat in cat_order:
        ids = categories[cat]
        h = sum(1 for i in ids if qmap[i]["confidence"] == "high")
        m = sum(1 for i in ids if qmap[i]["confidence"] == "medium")
        high_counts.append(h)
        med_counts.append(m)

    fig, ax = plt.subplots(figsize=(10, 5.6))
    xs = np.arange(len(cat_order))
    bars1 = ax.bar(xs, high_counts, color="#2E7D32", label=f"High confidence ({conf_dist['high']})")
    bars2 = ax.bar(xs, med_counts, bottom=high_counts, color="#F9A825",
                   label=f"Medium confidence ({conf_dist['medium']})")
    ax.set_xticks(xs)
    ax.set_xticklabels([cat_labels[c] for c in cat_order], fontsize=11)
    ax.set_ylabel("問題數", fontsize=12)
    ax.set_title("K707：20 問題 × 5+ 主題類別 × 信心度分佈\n"
                 "（86 實驗，25 直接引用；高信心 14 / 中信心 6 / 低信心 0）",
                 fontsize=13, pad=10)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    # annotate totals on top
    for i, (h, m) in enumerate(zip(high_counts, med_counts)):
        total = h + m
        ax.text(i, total + 0.1, f"{total}", ha="center", fontsize=11, fontweight="bold")

    plt.tight_layout()
    out_a = ROOT / "k707_category_distribution.png"
    plt.savefig(out_a, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"saved {out_a}")

    # ============================================================
    # Fig B: top-10 high-confidence answers, ranked by SEO/share value
    # ============================================================
    # pick a curated set of 10 SEO-friendly questions with a numeric headline
    selected = [
        (1,  "VIX 預測方向？",         "r=0.04（不能）"),
        (2,  "最佳配置？",              "50/50 SPY/GLD, Sharpe 0.548"),
        (3,  "VT vs BH Sharpe？",       "0.525 vs 0.545"),
        (3,  "VT vs BH MDD？",          "-17% vs -32%"),
        (10, "BTC 能避險？",            "尾部相依 4.25 倍（不能）"),
        (11, "黃金為何有效？",          "vol 降 27%, 危機+12.2%"),
        (14, "1 年 MDD>20% 機率？",     "50/50+VT = 0%"),
        (7,  "VIX 回歸半衰期？",        "10.2 天"),
        (8,  "Lookahead 修正後 Sharpe？", "1.68 → 0.355"),
        (17, "簡單打敗複雜？",           "50/50 0.548 > Markowitz 0.405"),
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    ys = np.arange(len(selected))
    labels = [f"Q{qid}: {short}" for qid, short, _ in selected]
    metrics = [m for _, _, m in selected]

    # color bars by category
    color_map = {1: "#1E88E5", 2: "#43A047", 3: "#43A047", 7: "#FB8C00",
                 8: "#1E88E5", 10: "#43A047", 11: "#43A047", 14: "#E53935",
                 17: "#8E24AA"}
    colors = [color_map.get(qid, "#666") for qid, _, _ in selected]

    ax.barh(ys, [1] * len(selected), color=colors, alpha=0.85)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)

    # annotate metric value on each bar
    for y, m in zip(ys, metrics):
        ax.text(0.02, y, m, ha="left", va="center", fontsize=11,
                fontweight="bold", color="white")

    ax.set_title("K707：10 個最有 SEO 價值的問答（一句話答案 + 關鍵數字）",
                 fontsize=13, pad=10)

    # legend (category colors)
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#1E88E5", label="市場預測"),
        Patch(facecolor="#43A047", label="資產配置"),
        Patch(facecolor="#FB8C00", label="交易執行"),
        Patch(facecolor="#E53935", label="風險控制"),
        Patch(facecolor="#8E24AA", label="方法論"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9, ncol=2)

    plt.tight_layout()
    out_b = ROOT / "k707_top10_answers.png"
    plt.savefig(out_b, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"saved {out_b}")

    # ============================================================
    # Fig C: 4 personas × 5 category answer heatmap
    # ============================================================
    personas = ["新手散戶\n(US$5k)", "上班族\n(月定投)", "風險厭惡型\n(γ≥5)", "退休族\n(提領期)"]
    cats = ["配置", "VT", "Rebalance", "DCA", "風控"]

    # value scale: 0=不適用 1=可選 2=建議 3=必須
    matrix = np.array([
        # 新手散戶
        [3, 1, 2, 2, 1],
        # 上班族
        [3, 1, 2, 3, 1],
        # 風險厭惡
        [2, 3, 2, 2, 3],
        # 退休族
        [2, 3, 2, 1, 3],
    ])

    fig, ax = plt.subplots(figsize=(9, 4.5))
    im = ax.imshow(matrix, cmap="YlGnBu", aspect="auto", vmin=0, vmax=3)

    annotations = {0: "—", 1: "可選", 2: "建議", 3: "必須"}
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            v = matrix[i, j]
            ax.text(j, i, annotations[v], ha="center", va="center",
                    fontsize=11, fontweight="bold",
                    color="white" if v >= 2 else "#333")

    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(cats, fontsize=11)
    ax.set_yticks(range(len(personas)))
    ax.set_yticklabels(personas, fontsize=10)
    ax.set_title("K707：4 種散戶 × 5 大主題的行動建議地圖\n"
                 "（K633/K668/K688/K632/K664 綜合，依任務 1+2+5）",
                 fontsize=12, pad=10)

    cbar = fig.colorbar(im, ax=ax, ticks=[0, 1, 2, 3])
    cbar.ax.set_yticklabels(["不適用", "可選", "建議", "必須"])

    plt.tight_layout()
    out_c = ROOT / "k707_persona_action_map.png"
    plt.savefig(out_c, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"saved {out_c}")


if __name__ == "__main__":
    main()
