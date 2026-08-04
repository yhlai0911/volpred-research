"""Charts for the K1623 general-audience article.

Two figures, both driven straight off experiments/k1623/k1623_rev2_results.json
so the numbers in the prose and the numbers on the plot cannot drift apart:

  1. k1623_general_ruler_flip.png  -- ARFIMA/HAR loss ratio per asset under the
     two scoring rules. The 1.0 line is the "tie" line; which side of it a bar
     lands on IS the winner, so the ranking flip is readable without a legend
     lookup.
  2. k1623_general_survivor_funnel.png -- how 40 comparisons shrink as the
     multiple-comparison correction is applied.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1623" / "k1623_rev2_results.json"
ASSETS = ROOT / "storage" / "assets"

# Muted, colour-blind-safe pair: warm ochre vs cool teal. Neither reads as
# "good/bad", which matters because the whole point is that neither ruler is
# the right one.
C_QLIKE = "#B45309"
C_MSE = "#0F766E"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"

LABEL = {
    "VIX": "VIX 恐慌指數",
    "SPY": "SPY 標普 500",
    "TW0050": "0050 台灣 50",
    "QQQ": "QQQ 那斯達克",
    "N225": "N225 日經",
}


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_ruler_flip(data: dict) -> Path:
    rows = data["loss_function_sign_reversal"]
    names = [LABEL[r["asset"]] for r in rows]
    qlike = [r["qlike_ratio_arfima_over_har"] for r in rows]
    mse = [r["mse_ratio_arfima_over_har"] for r in rows]
    flipped = [r["sign_reversal"] for r in rows]

    y = range(len(rows))
    h = 0.36
    fig, ax = plt.subplots(figsize=(9.5, 5.6), dpi=160)

    ax.barh([i + h / 2 for i in y], qlike, height=h, color=C_QLIKE,
            label="比例式評分（在意小數字算錯幾成）")
    ax.barh([i - h / 2 for i in y], mse, height=h, color=C_MSE,
            label="平方式評分（在意大數字差多少）")

    ax.axvline(1.0, color=C_TEXT, lw=1.4, zorder=3)
    ax.text(1.0, len(rows) - 0.35, "  1.0 = 兩個模型打平",
            color=C_TEXT, fontsize=9, va="center")

    for i, (q, m) in enumerate(zip(qlike, mse)):
        ax.text(q + 0.008, i + h / 2, f"{q:.3f}", va="center",
                fontsize=8.5, color=C_QLIKE)
        ax.text(m + 0.008, i - h / 2, f"{m:.3f}", va="center",
                fontsize=8.5, color=C_MSE)

    ax.set_yticks(list(y))
    ax.set_yticklabels(
        [n + ("（換尺換冠軍）" if f else "") for n, f in zip(names, flipped)],
        fontsize=10)
    ax.set_xlim(0.78, 1.14)
    ax.set_xlabel("長記憶模型的誤差 ÷ 樸素模型的誤差（<1 代表長記憶模型較準）",
                  fontsize=10)
    ax.set_title("同一批預測，換一把尺量，五個市場有三個換了冠軍",
                 fontsize=13.5, pad=14, weight="bold")
    # Bars fill the left of the panel, so the only clear space is top-right.
    ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1623_general_ruler_flip.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_survivor_funnel(data: dict) -> Path:
    s = data["summary"]
    total = s["n_dm_comparisons_total"]
    stages = ["全部比較", "單看一次就算數", "扣掉多次比較的運氣"]
    qlike = [total // 2, s["nominal_sig_05"]["QLIKE"],
             s["bh_sig_05_within_loss"]["QLIKE"]]
    mse = [total // 2, s["nominal_sig_05"]["MSE"],
           s["bh_sig_05_within_loss"]["MSE"]]

    x = range(len(stages))
    w = 0.36
    fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=160)
    ax.bar([i - w / 2 for i in x], qlike, width=w, color=C_QLIKE,
           label="比例式評分")
    ax.bar([i + w / 2 for i in x], mse, width=w, color=C_MSE,
           label="平方式評分")

    for i, (q, m) in enumerate(zip(qlike, mse)):
        ax.text(i - w / 2, q + 0.4, str(q), ha="center", fontsize=11,
                color=C_QLIKE, weight="bold")
        ax.text(i + w / 2, m + 0.4, str(m), ha="center", fontsize=11,
                color=C_MSE, weight="bold")

    ax.set_xticks(list(x))
    ax.set_xticklabels(stages, fontsize=10.5)
    ax.set_ylabel("有幾組比較「看起來分得出勝負」", fontsize=10)
    ax.set_ylim(0, total // 2 + 4)
    ax.set_title("四十組比較，真正撐過檢驗的沒幾組",
                 fontsize=13.5, pad=14, weight="bold")
    ax.legend(frameon=False, fontsize=9.5)
    ax.grid(axis="y", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1623_general_survivor_funnel.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_ruler_flip(data), fig_survivor_funnel(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
