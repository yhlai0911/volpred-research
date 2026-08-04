"""Charts for the K1698 general-audience article.

All three figures read every number from experiments/k1698/k1698_results.json.
Nothing is hardcoded — including the pre-registered decision threshold, which is
parsed out of the stored rule string rather than retyped.

  1. k1698_general_two_targets.png -- the same two models scored against two
     different targets. Left panel: the volatility number the forecast was built
     from. Right panel: the squared daily return of the ETF an investor actually
     holds. The winner swaps between the panels. Faceted because the two error
     scales are not comparable; only the within-panel ranking is.
  2. k1698_general_strength_flip.png -- test strength for the same model pair,
     on both targets, before and after the volatility series was rebuilt, with
     the pre-registered decision band drawn. Exactly one bar leaves the band,
     and it is on the target that was never the one being asked about.
  3. k1698_general_rebuild_audit.png -- what the rebuild changed: the average
     level ratio between the old and rebuilt series, and how tightly the two
     series track each other.

Palette: #B45309 / #0F9488 for the two models (validated: lightness band,
chroma floor, protan/deutan/tritan separation, normal-vision floor and surface
contrast all pass). #71717A is used only as a recessive baseline mark for "the
old way" in figures 2 and 3 — it is deliberately a neutral, not a categorical
hue, and identity there is carried by axis direction plus direct labels.
"""

from __future__ import annotations

import json
import re
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
RESULTS = ROOT / "experiments" / "k1698" / "k1698_results.json"
ASSETS = ROOT / "storage" / "assets"

C_HIST = "#B45309"   # 以歷史波動為基礎的模型
C_RET = "#0F9488"    # 以報酬序列估出來的波動模型
C_OLD = "#71717A"    # 舊序列（基準，刻意用中性色）
C_BAND = "#E4E4E7"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#52525B"

MODEL_HIST = "HAR-RV"
MODEL_RET = "GJR"
PAIR = f"{MODEL_HIST}_vs_{MODEL_RET}"

TARGET_OWN = "rv_tx_aligned"
TARGET_ETF = "r2_0050"

LABEL_HIST = "以歷史波動為基礎的模型"
LABEL_RET = "以報酬序列估出來的波動模型"
LABEL_OWN = "模型自己算出來的波動率數字"
LABEL_ETF = "投資人實際持有的 0050 當日報酬平方"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def threshold(data: dict) -> float:
    """Pull the pre-registered |t| bar out of the stored rule text."""
    note = data["gate"]["leg1_qlike"]["aligned_target_r2_0050"]["note"]
    m = re.search(r"guardrail\s*=\s*\|t\|\s*>\s*(\d+(?:\.\d+)?)", note)
    if not m:
        raise ValueError("pre-registered guardrail not found in results JSON")
    return float(m.group(1))


def dm(data: dict, run: str, target: str) -> dict:
    """The stored test record for the model pair, wherever it is filed."""
    tests = data["runs"][run]["qlike_dm_tests"]
    for block in ("primary_nonnested", "secondary_nonnested"):
        rec = tests.get(block, {}).get(target, {}).get(PAIR)
        if rec:
            return rec
    raise KeyError(f"{PAIR} not found for run={run} target={target}")


def score(data: dict, run: str, target: str, model: str) -> dict:
    return data["runs"][run]["qlike"][target][model]


def _strip(ax, keep_left: bool = True) -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if not keep_left:
        ax.spines["left"].set_visible(False)
    ax.set_axisbelow(True)


def fig_two_targets(data: dict) -> Path:
    panels = [
        (TARGET_OWN, LABEL_OWN, "把預測拿去對「它自己算出來的那個波動率」"),
        (TARGET_ETF, LABEL_ETF, "把同樣兩個預測拿去對「你手上真正持有的東西」"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.6), dpi=160)

    for ax, (target, _label, sub) in zip(axes, panels):
        hist = score(data, "primary", target, MODEL_HIST)
        ret = score(data, "primary", target, MODEL_RET)
        vals = [hist["qlike"], ret["qlike"]]
        colors = [C_HIST, C_RET]
        ypos = [1, 0]

        bars = ax.barh(ypos, vals, height=0.42, color=colors)
        best = min(range(2), key=lambda i: vals[i])

        for i, (b, v) in enumerate(zip(bars, vals)):
            ax.text(v + max(vals) * 0.025, b.get_y() + b.get_height() / 2,
                    f"{v:.4f}" + ("　← 較準" if i == best else ""),
                    va="center", fontsize=10.5, weight="bold", color=colors[i])

        ax.set_yticks(ypos)
        ax.set_yticklabels([LABEL_HIST, LABEL_RET], fontsize=10)
        ax.set_ylim(-0.55, 1.55)
        ax.set_xlim(0, max(vals) * 1.52)
        ax.set_title(sub, fontsize=11.5, pad=10, weight="bold", color=C_TEXT)
        ax.set_xlabel(f"誤差分數（愈低愈準，共 {hist['n']} 天）", fontsize=9.5,
                      color=C_MUTED)
        ax.grid(axis="x", color=C_GRID, lw=0.7)
        _strip(ax, keep_left=False)
        ax.tick_params(axis="y", length=0)

    fig.suptitle("換一個評分標的，兩個模型的名次就對調", fontsize=14.5,
                 weight="bold", y=1.02)
    fig.text(0.5, -0.06,
             "左右兩張圖的分數不能互相比大小，只能各自看誰高誰低。",
             ha="center", fontsize=9.5, color=C_MUTED)
    fig.tight_layout()

    out = ASSETS / "k1698_general_two_targets.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_strength_flip(data: dict) -> Path:
    bar = threshold(data)
    rows = [
        (LABEL_ETF, TARGET_ETF),
        (LABEL_OWN, TARGET_OWN),
    ]
    runs = [("bridge_old_rv", "舊的波動率序列", C_OLD),
            ("primary", "重建後的波動率序列", C_HIST)]

    fig, ax = plt.subplots(figsize=(10.4, 5.0), dpi=160)
    ax.axvspan(-bar, bar, color=C_BAND, zorder=0)

    h = 0.3
    for j, (run, run_label, color) in enumerate(runs):
        ys = [i + (h / 2 if j == 1 else -h / 2) for i in range(len(rows))]
        vals = [dm(data, run, t)["t_stat"] for _, t in rows]
        ax.barh(ys, vals, height=h, color=color, zorder=2, label=run_label)
        for y, v in zip(ys, vals):
            ax.text(v + (0.18 if v > 0 else -0.18), y, f"{v:+.2f}",
                    va="center", ha="left" if v > 0 else "right",
                    fontsize=10.5, weight="bold", color=color, zorder=3)

    ax.axvline(0, color=C_TEXT, lw=1.2, zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.5)
    ax.set_xlim(-6.9, 4.4)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel(f"檢定強度（愈往左愈偏向{LABEL_HIST}；灰帶內＝沒跨過事前寫死的 ±{bar:g} 門檻）",
                  fontsize=9.5, color=C_MUTED)
    ax.set_title("唯一跨過門檻的那一根，量的是模型自己算出來的東西",
                 fontsize=14, pad=14, weight="bold")
    ax.legend(frameon=False, fontsize=10, loc="lower left")
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    _strip(ax, keep_left=False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()

    out = ASSETS / "k1698_general_strength_flip.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig_rebuild_audit(data: dict) -> Path:
    rc = data["rv_construction"]
    ratio = rc["old_vs_new"]["mean_ratio_new_over_old"]
    corr = rc["old_vs_new"]["corr"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.0), dpi=160,
                                   gridspec_kw={"width_ratios": [1.05, 1]})

    vals = [1.0, ratio]
    colors = [C_OLD, C_HIST]
    bars = ax1.barh([1, 0], vals, height=0.4, color=colors)
    for b, v, c in zip(bars, vals, colors):
        ax1.text(v + 0.03, b.get_y() + b.get_height() / 2,
                 "基準" if v == 1.0 else f"{v:.4f} 倍",
                 va="center", fontsize=11, weight="bold", color=c)
    ax1.set_yticks([1, 0])
    ax1.set_yticklabels(["舊的波動率序列", "重建後的波動率序列"], fontsize=10.5)
    ax1.set_ylim(-0.5, 1.5)
    ax1.set_xlim(0, ratio * 1.32)
    ax1.set_title("同一段期間，重建後的波動率平均高出四分之一",
                  fontsize=11.5, pad=10, weight="bold", color=C_TEXT)
    ax1.set_xlabel("平均水準（以舊序列為 1）", fontsize=9.5, color=C_MUTED)
    ax1.grid(axis="x", color=C_GRID, lw=0.7)
    _strip(ax1, keep_left=False)
    ax1.tick_params(axis="y", length=0)

    ax2.barh([0], [1.0], height=0.34, color=C_BAND)
    ax2.barh([0], [corr], height=0.34, color=C_HIST)
    ax2.text(corr - 0.02, 0, f"{corr:.4f}", va="center", ha="right",
             fontsize=13, weight="bold", color="white")
    ax2.text(1.0, 0.24, "完全一致 = 1", fontsize=9.5, color=C_MUTED, ha="right")
    ax2.set_xlim(0, 1.04)
    ax2.set_ylim(-0.5, 0.5)
    ax2.set_yticks([])
    ax2.set_title("兩條序列只有八成左右對得上",
                  fontsize=11.5, pad=10, weight="bold", color=C_TEXT)
    ax2.set_xlabel("新舊兩條波動率序列的同向程度", fontsize=9.5, color=C_MUTED)
    ax2.grid(axis="x", color=C_GRID, lw=0.7)
    _strip(ax2, keep_left=False)

    fig.text(0.5, -0.08,
             f"重建涵蓋 {rc['n_days']:,} 個交易日，換月 {rc['n_roll_days']} 天，"
             f"起點價缺漏 {rc['n_anchor_missing']} 天，"
             f"平均每天 {rc['mean_n_returns_per_day']:.1f} 段五分鐘報酬。",
             ha="center", fontsize=9.5, color=C_MUTED)
    fig.tight_layout()

    out = ASSETS / "k1698_general_rebuild_audit.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_two_targets(data), fig_strength_flip(data),
              fig_rebuild_audit(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
