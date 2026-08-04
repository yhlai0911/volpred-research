"""Charts for the K1717 general-audience article.

Both figures read every number from experiments/k1717/k1717_results.json.
Nothing is hard-coded except labels and layout.

  1. k1717_general_qlike.png -- forecast-error scores for the two model
     families, each with three settings (own history only / + India VIX /
     + US VIX). A dashed reference line marks the own-history-only score in
     each panel, so the US-VIX bar visibly pokes above it: adding the US
     index makes the forecast worse than adding nothing at all.
  2. k1717_general_threshold.png -- the head-to-head test statistic for the
     first model family across every smoothing setting stored in the results
     file, with the pre-registered pass line at -3 and the pre-registered
     setting called out on the failing side of it.

Palette validated with the dataviz skill's validate_palette.js
("#15803D,#1D4ED8,#B45309", light surface: all checks pass). The one CVD
pair in the 6-8 band is backed by direct value labels on every mark.
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
RESULTS = ROOT / "experiments" / "k1717" / "k1717_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_BASE = "#15803D"
C_LOCAL = "#1D4ED8"
C_US = "#B45309"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

PANELS = [
    ("第一套模型：看報酬序列估波動", "garch_base", "garch_x_india", "garch_x_us"),
    ("第二套模型：看已實現波動往後推", "har_base", "har_x_india", "har_x_us"),
]
SERIES = [
    ("只用自己的歷史", C_BASE),
    ("＋印度 VIX", C_LOCAL),
    ("＋美國 VIX", C_US),
]


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_qlike(data: dict) -> Path:
    metrics = data["oos"]["metrics"]
    n_obs = data["oos"]["n_obs"]

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 5.9), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)

    for ax, (panel_title, k_base, k_local, k_us) in zip(axes, PANELS):
        ax.set_facecolor(C_SURFACE)
        values = [metrics[k]["qlike"] for k in (k_base, k_local, k_us)]
        base_value = values[0]
        colors = [c for _, c in SERIES]

        xpos = [0, 1, 2]
        ax.bar(xpos, values, width=0.50, color=colors, zorder=3,
               edgecolor=C_SURFACE, linewidth=2.0)

        top = max(values)
        ax.set_ylim(0, top * 1.30)

        ax.axhline(base_value, color=C_BASE, lw=1.5, ls=(0, (5, 4)), zorder=4)
        ax.text(
            0.5,
            base_value - top * 0.020,
            "不加指數的水準",
            fontsize=9.5,
            color=C_BASE,
            ha="center",
            va="top",
            zorder=6,
        )

        for x, v in zip(xpos, values):
            label_y = max(v, base_value) + top * 0.038
            ax.text(x, label_y, f"{v:.4f}", ha="center", va="bottom",
                    fontsize=12, weight="bold", color=C_TEXT, zorder=5)

        ax.annotate(
            "比不加還糟",
            xy=(2, values[2]),
            xytext=(2.0, top * 1.19),
            fontsize=10.5,
            weight="bold",
            color=C_US,
            ha="center",
            arrowprops=dict(arrowstyle="-|>", color=C_US, lw=1.4,
                            shrinkA=2, shrinkB=8),
        )

        ax.set_xticks(xpos)
        ax.set_xticklabels([lab for lab, _ in SERIES], fontsize=10.5)
        ax.set_title(panel_title, fontsize=12, pad=10, color=C_TEXT)
        ax.grid(axis="y", color=C_GRID, lw=0.7, zorder=0)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", labelsize=9, colors=C_MUTED)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(C_GRID)

    axes[0].set_ylabel("預測誤差分數（越低越準）", fontsize=10.5, color=C_TEXT)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in SERIES]
    fig.legend(
        handles,
        [lab for lab, _ in SERIES],
        loc="lower center",
        ncol=3,
        frameon=False,
        fontsize=10.5,
        bbox_to_anchor=(0.5, -0.005),
    )

    fig.suptitle(
        "加印度 VIX 兩套模型都變準，加美國 VIX 兩套都變差",
        fontsize=15,
        weight="bold",
        color=C_TEXT,
        y=0.985,
    )
    fig.text(
        0.5,
        0.915,
        f"NIFTY 樣本外 {data['oos']['start'][:10]} ~ {data['oos']['end'][:10]}，"
        f"{n_obs} 個交易日。兩張圖各有自己的刻度，只比同一張圖內的高低。",
        fontsize=9.5,
        color=C_MUTED,
        ha="center",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))

    out = ASSETS / "k1717_general_qlike.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def fig_threshold(data: dict) -> Path:
    cmp_ = data["oos"]["dm_comparisons"]["primary_local_vs_us_garch"]
    sens = cmp_["hac_lag_sensitivity_dm_t"]
    canonical_lag = cmp_["canonical_hac_lag"]

    rows = sorted(
        ((int(k.split("_")[1]), v["t_stat"], v["is_canonical_bandwidth"])
         for k, v in sens.items()),
        key=lambda r: r[0],
    )
    lags = [r[0] for r in rows]
    tvals = [r[1] for r in rows]
    xpos = list(range(len(rows)))
    threshold = -3.0

    fig, ax = plt.subplots(figsize=(10.4, 6.0), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)
    ax.set_facecolor(C_SURFACE)

    lo = min(tvals) - 0.30
    hi = max(tvals) + 0.55

    ax.axhspan(lo, threshold, color="#DCFCE7", zorder=0)
    ax.axhline(threshold, color=C_TEXT, lw=1.6, ls=(0, (5, 4)), zorder=4)
    ax.text(
        len(rows) - 0.55,
        threshold - 0.045,
        "事先立的門檻：統計強度要低於 −3 才算贏",
        fontsize=10,
        color=C_TEXT,
        ha="right",
        va="top",
        weight="bold",
    )
    ax.text(
        len(rows) - 0.55,
        lo + (hi - lo) * 0.03,
        "綠色區＝會過",
        fontsize=11,
        color=C_BASE,
        weight="bold",
        ha="right",
        va="bottom",
    )
    ax.text(
        -0.62,
        hi - (hi - lo) * 0.03,
        "白色區＝沒過",
        fontsize=11,
        color=C_US,
        weight="bold",
        ha="left",
        va="top",
    )

    ax.plot(xpos, tvals, color=C_MUTED, lw=2.0, zorder=3)
    for x, (lag, t, is_canon) in zip(xpos, rows):
        color = C_BASE if t < threshold else C_US
        ax.plot(
            [x], [t],
            marker="o",
            ms=17 if is_canon else 9.5,
            color=color,
            mec=C_SURFACE if not is_canon else C_TEXT,
            mew=1.6 if not is_canon else 2.2,
            zorder=5,
        )
        ax.text(
            x + (0.20 if is_canon else 0.0),
            t + (0.055 if is_canon else 0.10),
            f"{t:.4f}",
            ha="left" if is_canon else "center",
            va="bottom",
            fontsize=11.5 if is_canon else 10.5,
            weight="bold" if is_canon else "normal",
            color=C_US if is_canon else C_TEXT,
        )

    canon_x = lags.index(canonical_lag)
    canon_t = tvals[canon_x]
    ax.annotate(
        f"事先指定的正式設定（{canonical_lag}）\n落在門檻的另一邊，所以判定沒過",
        xy=(canon_x, canon_t),
        xytext=(canon_x - 0.55, canon_t + 0.60),
        fontsize=11,
        weight="bold",
        color=C_US,
        ha="center",
        arrowprops=dict(arrowstyle="-|>", color=C_US, lw=1.6,
                        shrinkA=4, shrinkB=12),
    )

    ax.set_xticks(xpos)
    ax.set_xticklabels([str(l) for l in lags], fontsize=11)
    ax.set_xlim(-0.75, len(rows) - 0.35)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("統計平滑參數（唯一被動到的旋鈕）", fontsize=11, color=C_TEXT)
    ax.set_ylabel("統計強度（越負代表印度 VIX 贏得越確定）", fontsize=11, color=C_TEXT)
    ax.set_title(
        "同一場對決，轉一下平滑旋鈕就能從「沒過」變成「過」",
        fontsize=15,
        weight="bold",
        color=C_TEXT,
        pad=26,
    )
    ax.text(
        -0.75,
        hi + (hi - lo) * 0.035,
        "第一套模型：印度 VIX vs 美國 VIX，"
        f"樣本外 {cmp_['n_obs']} 個交易日",
        fontsize=9.5,
        color=C_MUTED,
        ha="left",
    )
    ax.grid(axis="y", color=C_GRID, lw=0.7, zorder=1)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", labelsize=9, colors=C_MUTED)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(C_GRID)

    fig.tight_layout()
    out = ASSETS / "k1717_general_threshold.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_qlike(data), fig_threshold(data)):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
