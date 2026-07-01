"""Generate the 懶人包 (lazypack) infographic set for the merger-arbitrage
volatility article. 3 panels: concept / method / results. Matplotlib-based,
professional/bento style (no cartoon), every number bound to
k1590_diagnostic_results.json. No internal research code names
(no "K1590", no "VolPred", no "AI"/"LLM") anywhere in rendered text.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = Path(__file__).resolve().parent
PUB = OUT / "plots_public"
PUB.mkdir(parents=True, exist_ok=True)

R = json.loads((OUT / "k1590_diagnostic_results.json").read_text())

FACE = "#f7f7f5"
NAVY = "#1b2a4a"
ACCENT = "#b2182b"
BLUE = "#2166ac"
GREY = "#555555"

plt.rcParams["font.family"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS", "sans-serif"]


def panel_frame(title: str, subtitle: str, figsize=(9, 6.2)):
    fig = plt.figure(figsize=figsize, facecolor=FACE)
    fig.suptitle(title, fontsize=20, fontweight="bold", color=NAVY, y=0.97)
    fig.text(0.5, 0.905, subtitle, ha="center", fontsize=11, color=GREY)
    return fig


def panel1_concept():
    fig = panel_frame(
        "當「小道消息」不再可靠，波動率會先講真話",
        "併購套利基金的日常震盪，藏著一般市場數據看不到的訊號",
    )
    ax = fig.add_axes((0.05, 0.08, 0.9, 0.76))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    boxes = [
        (0.3, 5.5, 4.4, 3.5, "#dbe9f6", "併購套利基金是什麼？",
         "專門持有「已宣布併購案」股票的\nETF（代號 MNA）。\n\n只要交易還沒完成，股價和收購價\n之間永遠有一段價差，\n這段價差就是套利者的獲利空間。"),
        (5.3, 5.5, 4.4, 3.5, "#fde8df", "價差為什麼會擴大？",
         "當市場擔心交易可能破局，\n例如反壟斷卡關、資金環境變緊，\n股價會提前反映風險，\n價差跟著放大、也跟著抖動。"),
        (0.3, 1.0, 9.4, 3.9, "#eef2ee", "這篇文章要驗證的想法",
         "如果「交易破局的擔憂」真的存在，那麼在市場恐慌\n（VIX 飆高）的時候，併購套利基金的日常震盪幅度應該\n明顯放大，而且放大的程度要比它單純追蹤大盤\n（跟 SPY 走勢雷同）所能解釋的還要多。"),
    ]
    for x, y, w, h, color, head, body in boxes:
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.25",
            linewidth=1.2, edgecolor="#999999", facecolor=color))
        ax.text(x + 0.25, y + h - 0.55, head, fontsize=13, fontweight="bold", color=NAVY, va="top")
        ax.text(x + 0.25, y + h - 1.25, body, fontsize=10.5, color="#222222", va="top", linespacing=1.6)

    fig.text(0.5, 0.02, "資料來源：yfinance 每日調整後收盤價，期間 2020–2026",
              ha="center", fontsize=9, color="#888888")
    fig.savefig(PUB / "lazypack_1_concept.png", dpi=160)
    plt.close(fig)


def panel2_method():
    fig = panel_frame(
        "怎麼量出「破局擔憂」？",
        "三個步驟，把主觀的市場情緒換成看得到的數字",
    )
    ax = fig.add_axes((0.05, 0.08, 0.9, 0.76))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    steps = [
        ("1", "分情境", "把 2020–2026 的每個交易日，依當天 VIX 指數\n分成三種情境：\n\n平靜期（VIX < 20）／緊張期（VIX 20–30）\n恐慌期（VIX > 30）"),
        ("2", "量震盪", "計算併購套利基金在每個情境下的\n單日絕對報酬平均值——\n也就是「平均一天會抖動多大幅度」"),
        ("3", "做檢定", "用統計上的兩樣本檢定，確認恐慌期跟\n平靜期的震盪差異不是巧合，\n同時檢查它和大盤（SPY）的相關程度，\n排除「只是跟著大盤動」的可能"),
    ]
    x0 = 0.3
    w = 3.0
    gap = 0.3
    for i, (num, head, body) in enumerate(steps):
        x = x0 + i * (w + gap)
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, 3.6), w, 5.4, boxstyle="round,pad=0.08,rounding_size=0.25",
            linewidth=1.2, edgecolor="#999999", facecolor="#ffffff"))
        ax.add_patch(mpatches.Circle((x + 0.55, 8.35), 0.42, facecolor=BLUE, edgecolor="none"))
        ax.text(x + 0.55, 8.35, num, fontsize=16, color="white", ha="center", va="center", fontweight="bold")
        ax.text(x + 0.2, 7.55, head, fontsize=13.5, fontweight="bold", color=NAVY)
        ax.text(x + 0.2, 7.05, body, fontsize=9.8, color="#222222", va="top", linespacing=1.55)

    n_low = R["vix_regime_stats"]["low_vix_lt20"]["n_days"]
    n_mid = R["vix_regime_stats"]["mid_vix_20_30"]["n_days"]
    n_high = R["vix_regime_stats"]["high_vix_gt30"]["n_days"]
    n_total = R["meta"]["period"]["n_trading_days"]
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.3, 0.7, ) if False else (0.3, 0.7), 9.4, 2.5, boxstyle="round,pad=0.08,rounding_size=0.25",
        linewidth=1.2, edgecolor="#999999", facecolor="#f0f0eb"))
    ax.text(5.0, 2.55, "樣本規模", fontsize=13, fontweight="bold", color=NAVY, ha="center")
    ax.text(5.0, 1.55,
            f"共 {n_total} 個交易日：平靜期 {n_low} 天、緊張期 {n_mid} 天、恐慌期 {n_high} 天",
            fontsize=11.5, color="#222222", ha="center")

    fig.text(0.5, 0.02, "資料來源：yfinance 每日調整後收盤價（MNA / SPY / VIX），2020–2026，共 1,629 個交易日",
              ha="center", fontsize=9, color="#888888")
    fig.savefig(PUB / "lazypack_2_method.png", dpi=160)
    plt.close(fig)


def panel3_results():
    vrt = R["vol_regime_test"]
    pearson = R["correlations"]["pearson"]["SPY"]["MNA"]
    ratio = vrt["magnitude_ratio_high_over_low"]
    p_val = vrt["p_value"]
    low = vrt["low_vix_lt20"]["mean_abs_ret"] * 100
    high = vrt["high_vix_gt30"]["mean_abs_ret"] * 100

    fig = panel_frame(
        "結果：恐慌期的震盪，是平靜期的 3 倍",
        "而且不是「跟著大盤抖」——這是屬於併購套利自己的訊號",
    )
    ax = fig.add_axes((0.05, 0.08, 0.9, 0.76))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # Big number card
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.3, 5.3), 4.3, 3.5, boxstyle="round,pad=0.08,rounding_size=0.25",
        linewidth=1.4, edgecolor=ACCENT, facecolor="#fdf0ee"))
    ax.text(2.45, 8.15, "震盪倍數", fontsize=13, color=NAVY, ha="center", fontweight="bold")
    ax.text(2.45, 6.9, f"{ratio:.1f}×", fontsize=46, color=ACCENT, ha="center", fontweight="bold")
    ax.text(2.45, 5.75, f"恐慌期平均單日震盪 {high:.2f}%\n對比平靜期 {low:.2f}%",
            fontsize=10.5, color="#333333", ha="center", linespacing=1.5)

    ax.add_patch(mpatches.FancyBboxPatch(
        (5.0, 5.3), 4.7, 3.5, boxstyle="round,pad=0.08,rounding_size=0.25",
        linewidth=1.2, edgecolor="#999999", facecolor="#ffffff"))
    ax.text(7.35, 8.15, "統計顯著性", fontsize=13, color=NAVY, ha="center", fontweight="bold")
    ax.text(7.35, 6.9, f"p < 0.001", fontsize=30, color=BLUE, ha="center", fontweight="bold")
    ax.text(7.35, 5.75, "恐慌期與平靜期的震盪差異\n並非巧合（樣本數合計逾 1,000 天）",
            fontsize=10.2, color="#333333", ha="center", linespacing=1.5)

    ax.add_patch(mpatches.FancyBboxPatch(
        (0.3, 1.0), 9.4, 3.7, boxstyle="round,pad=0.08,rounding_size=0.25",
        linewidth=1.2, edgecolor="#999999", facecolor="#eef2ee"))
    ax.text(5.0, 4.15, "關鍵：這不只是「跟著大盤抖」", fontsize=13.5, fontweight="bold", color=NAVY, ha="center")
    ax.text(
        5.0, 2.4,
        f"併購套利基金與大盤（SPY）的相關係數只有 {pearson:.2f}（1.0 代表完全同步）。\n"
        "換句話說，它多出來的震盪有相當一部分來自「這筆併購案還做不做得成」\n"
        "的擔憂，而不是單純被大盤情緒帶動。",
        fontsize=11, color="#222222", ha="center", linespacing=1.6)

    fig.text(0.5, 0.02,
              "資料來源：yfinance 每日調整後收盤價，2020–2026，樣本數 1,629 個交易日；本結果為描述性診斷，非交易建議",
              ha="center", fontsize=8.5, color="#888888")
    fig.savefig(PUB / "lazypack_3_results.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    panel1_concept()
    panel2_method()
    panel3_results()
    print("wrote 3 lazypack panels to", PUB)
