"""K703 article figures: ten-numbers dashboard + persona action map."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k703_results.json").read_text())

plt.rcParams.update({
    "font.family": ["Heiti TC", "PingFang TC", "Songti TC", "Arial Unicode MS", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 130,
})


def fig_ten_numbers_dashboard():
    """Rank chart: 10 numbers with display + label."""
    nums = RESULTS["ten_numbers"]
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(nums) + 1)
    ax.invert_yaxis()
    ax.axis("off")

    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    ax.text(0.1, 0.3, "#", fontsize=12, fontweight="bold", color="#444")
    ax.text(0.7, 0.3, "數字", fontsize=12, fontweight="bold", color="#444")
    ax.text(3.2, 0.3, "意義", fontsize=12, fontweight="bold", color="#444")
    ax.text(8.6, 0.3, "來源 K", fontsize=12, fontweight="bold", color="#444")
    ax.plot([0.1, 9.9], [0.6, 0.6], color="#888", lw=0.8)

    for i, n in enumerate(nums):
        y = i + 1
        c = palette[i]
        # rank circle
        ax.add_patch(plt.Circle((0.35, y), 0.32, color=c, alpha=0.85))
        ax.text(0.35, y, str(n["rank"]), ha="center", va="center",
                fontsize=11, fontweight="bold", color="white")
        # number display
        ax.text(0.9, y, n["display"], fontsize=15, fontweight="bold",
                color=c, va="center")
        # label
        label_zh = {
            "VIX-direction correlation": "VIX 預測漲跌方向相關係數",
            "BH 50/50 SPY/GLD Sharpe ratio (lag-corrected)": "BH 50/50 SPY/GLD Sharpe（修正 lag 後）",
            "MDD reduction from volatility timing (EWMA VT)": "EWMA VT 最大回撤縮減幅度",
            "CRRA gamma threshold where VT becomes worthwhile": "VT 對風險趨避者開始划算的 γ 門檻",
            "Monthly loss probability with Piecewise Conservative": "Piecewise Conservative 月虧損機率",
            "Fear DCA terminal wealth improvement per dollar invested": "恐慌 DCA 每元終值改善幅度",
            "VIX half-life (mean-reversion speed)": "VIX 均值回歸半衰期",
            "EWMA weight autocorrelation (lag-robustness indicator)": "EWMA 權重自相關（lag 穩健性）",
            "False positive rate without Codex (adversarial) review": "無對抗式審查時的偽發現率",
            "Experiments this research session, 8 overturned (10%)": "本期實驗總數（10% 自我推翻率）",
        }.get(n["label"], n["label"])
        ax.text(3.2, y, label_zh, fontsize=10, va="center", color="#222")
        # source
        src = n["source_experiment"].split("(")[0].strip()
        ax.text(8.6, y, src, fontsize=9, va="center", color="#555", family="monospace")

    ax.text(5, len(nums) + 0.7,
            "K703：把 19 年研究濃縮成 10 個數字（資料源 yfinance/FRED 2006–2026, n≈5089）",
            fontsize=9, ha="center", style="italic", color="#666")
    plt.suptitle("一頁 cheatsheet：散戶該記住的 10 個數字", fontsize=14, fontweight="bold", y=0.97)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out = ROOT / "k703_ten_numbers_dashboard.png"
    plt.savefig(out, dpi=140, bbox_inches="tight")
    plt.close()
    return out


def fig_persona_action_map():
    """4 personas × action items grid."""
    summary = RESULTS["narrative_summary"]
    personas = [
        ("被動投資人", "for_passive_investor", "#1f77b4",
         ["BH 50/50 SPY/GLD（年再平衡）", "Sharpe = 0.545（19 年最高）",
          "不必加 VIX 擇時（修 lag 後沒用）"]),
        ("風險趨避者 γ≥5", "for_risk_averse_investor", "#d62728",
         ["EWMA VT（λ=0.94）", "MDD 從 -32.5% → -17.0%",
          "代價：年化報酬約少 1.8% Sharpe", "保險而非 alpha"]),
        ("DCA 定期定額者", "for_dca_investor", "#2ca02c",
         ["VIX > 20 加倍投入", "VIX > 30 三倍投入",
          "16 年 +4% 終值改善", "不必猜底，反應已知數字"]),
        ("研究者 / 同行", "for_researchers", "#9467bd",
         ["37.5% 偽發現率（對抗式審查抓出）", "VIX |corr| 對 magnitude 0.57",
          "VIX corr 對方向 0.04", "半衰期 10.2 天"]),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    axes = axes.flatten()
    for ax, (name, key, color, actions) in zip(axes, personas):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.add_patch(mpatches.FancyBboxPatch(
            (0.2, 0.2), 9.6, 9.6,
            boxstyle="round,pad=0.1", linewidth=2,
            edgecolor=color, facecolor="white"))
        ax.text(5, 9, name, ha="center", va="center",
                fontsize=14, fontweight="bold", color=color)
        ax.plot([1, 9], [8.3, 8.3], color=color, lw=1)
        for i, action in enumerate(actions):
            ax.text(0.7, 7.5 - i * 1.0, "•", fontsize=14, color=color, va="center")
            ax.text(1.2, 7.5 - i * 1.0, action, fontsize=10, color="#222", va="center")
    plt.suptitle("K703 四種讀者，四種行動建議",
                 fontsize=14, fontweight="bold", y=0.99)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out = ROOT / "k703_persona_action_map.png"
    plt.savefig(out, dpi=140, bbox_inches="tight")
    plt.close()
    return out


def fig_source_K_network():
    """Source K experiments network — show K703 aggregates from underlying K's."""
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # Center node
    ax.add_patch(plt.Circle((5, 4), 0.7, color="#d62728", zorder=5))
    ax.text(5, 4, "K703", ha="center", va="center", fontsize=13,
            fontweight="bold", color="white", zorder=6)
    ax.text(5, 3.05, "10 個數字", ha="center", fontsize=9,
            color="#555", style="italic")

    # Source K nodes
    sources = [
        ("K626", "VIX 方向\nrho=0.04", 1.5, 6.5, "#1f77b4"),
        ("K632", "Fear DCA\n+4%", 1.5, 4, "#2ca02c"),
        ("K648", "Piecewise\n7.7% 月虧", 1.5, 1.5, "#ff7f0e"),
        ("K658", "VIX 半衰期\n10.2 天", 5, 6.8, "#9467bd"),
        ("K687", "BH 50/50\nSharpe=0.545", 5, 1.2, "#8c564b"),
        ("K688", "γ=5 門檻", 8.5, 6.5, "#e377c2"),
        ("K690", "EWMA 自相關\n0.99", 8.5, 4, "#7f7f7f"),
        ("K696", "MDD -50%", 8.5, 1.5, "#bcbd22"),
        ("K697", "VIX magnitude\n0.57", 3.2, 5.8, "#17becf"),
        ("K700", "37.5% 偽發現", 3.2, 2.2, "#1f77b4"),
        ("K702", "50/50 確認", 6.8, 5.8, "#2ca02c"),
    ]

    for k, label, x, y, color in sources:
        # edge
        ax.plot([5, x], [4, y], color="#aaa", lw=0.8, alpha=0.6, zorder=1)
        ax.add_patch(plt.Circle((x, y), 0.45, color=color, alpha=0.85, zorder=4))
        ax.text(x, y, k, ha="center", va="center", fontsize=8.5,
                fontweight="bold", color="white", zorder=5)
        # label below
        ax.text(x, y - 0.75, label, ha="center", va="top", fontsize=8,
                color="#333", zorder=5)

    ax.text(5, 7.5, "K703 = 11 個底層實驗的 cross-K aggregation",
            ha="center", fontsize=12, fontweight="bold", color="#222")
    ax.text(5, 0.3, "資料源 yfinance / FRED  •  期間 2006-01 到 2026-03  •  總實驗數 82",
            ha="center", fontsize=9, color="#666", style="italic")
    plt.tight_layout()
    out = ROOT / "k703_source_K_network.png"
    plt.savefig(out, dpi=140, bbox_inches="tight")
    plt.close()
    return out


if __name__ == "__main__":
    p1 = fig_ten_numbers_dashboard()
    p2 = fig_persona_action_map()
    p3 = fig_source_K_network()
    print(f"Saved: {p1}")
    print(f"Saved: {p2}")
    print(f"Saved: {p3}")
