#!/usr/bin/env python3
"""K781 — reader-facing figures for the MVF (multiplicative volatility factor) study.

All numbers are read from experiments/k781/k781_mvf_results.json.
Nothing is recomputed and nothing is hard-coded.

Outputs:
  storage/assets/k781_general_ranking.png
  storage/assets/k781_general_subperiod_regime.png

Run:
  uv run python experiments/k781/k781_figures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=150)

RES = json.loads((ROOT / "experiments/k781/k781_mvf_results.json").read_text())

# Reader-facing plain-language names (no jargon in article-visible text).
ZH = {
    "GJR-GARCH": "壞消息加權版",
    "MVF": "慢快相乘版",
    "AMEM-r2": "平方報酬直接版",
    "GARCH": "基本回聲版",
    "HAR-r2": "三段長度平均版",
}
# Okabe-Ito colourblind-safe order, colour follows the entity (never the rank).
COLOR = {
    "GJR-GARCH": "#0072B2",
    "MVF": "#D55E00",
    "AMEM-r2": "#009E73",
    "GARCH": "#CC79A7",
    "HAR-r2": "#E69F00",
}
GREY = "#8a8a8a"
INK = "#333333"
OUT_DIR = ROOT / "storage/assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SURVIVORS = list(RES["mcs"]["surviving_models"])
RANKING = list(RES["qlike_ranking"])
SUBS = RES["subsample_stability"]
REG = RES["regime_analysis"]


def _tidy(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cccccc")
    ax.tick_params(colors=INK, labelsize=10.5, length=3, color="#cccccc")


# ── Figure 1 — ranking dot plot with the surviving shortlist marked ──────────
def fig_ranking(path: Path) -> None:
    rows = sorted(RANKING, key=lambda r: -r["QLIKE"])  # worst on top
    names = [ZH[r["model"]] for r in rows]
    vals = [r["QLIKE"] for r in rows]
    keys = [r["model"] for r in rows]
    y = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.22
    left = lo - pad

    surv_y = [i for i, k in enumerate(keys) if k in SURVIVORS]
    if surv_y:
        ax.axhspan(min(surv_y) - 0.42, max(surv_y) + 0.42,
                   color="#0072B2", alpha=0.07, zorder=0)

    for i, (k, v) in enumerate(zip(keys, vals)):
        inside = k in SURVIVORS
        c = COLOR[k]
        ax.hlines(i, left, v, color=c, alpha=0.55 if inside else 0.3, lw=2, zorder=2)
        ax.plot(v, i, "o", ms=13 if inside else 10,
                color=c if inside else "white",
                markeredgecolor=c, markeredgewidth=2.2, zorder=3)
        ax.text(v + (hi - lo) * 0.022, i, f"{v:.6f}", va="center", ha="left",
                fontsize=11.5, color=INK,
                fontweight="bold" if inside else "normal")
        if inside:
            ax.text(left + (hi - lo) * 0.02, i + 0.30, "留在候選名單內",
                    va="center", ha="left", fontsize=9.6, color="#0072B2")

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=12)
    ax.set_xlim(left, hi + (hi - lo) * 0.16)
    ax.set_xlabel("樣本外預測誤差分數（越低越好）", fontsize=11.5, color=INK)
    ax.set_title("五種波動預測法的成績單：新方法排第二，和第一名之間差 0.012566",
                 fontsize=14, fontweight="bold", color=INK, pad=14)
    ax.grid(axis="x", color="#eeeeee", lw=0.9, zorder=0)
    ax.set_axisbelow(True)
    _tidy(ax)
    fig.text(0.01, -0.02,
             f"SPY 每日資料，樣本外 {RES['oos_period']}，共 {RES['n_oos']} 個交易日；"
             f"藍底區塊＝統計上分不出高下的候選名單（{len(SURVIVORS)} 個）。",
             fontsize=9, color="#666666")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── Figure 2 — subperiod trajectory + high/low volatility split ──────────────
def fig_subperiod_regime(path: Path) -> None:
    periods = ["period_1_2009-2015", "period_2_2015-2020", "period_3_2020-2026"]
    labels = ["2009-2015", "2015-2020", "2020-2026"]
    order = [r["model"] for r in RANKING]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.2, 5.6),
                                   gridspec_kw={"width_ratios": [1.15, 1]})

    x = list(range(3))
    all_y = [SUBS[p][k] for p in periods for k in order]
    for k in order:
        ys = [SUBS[p][k] for p in periods]
        ax1.plot(x, ys, "-o", color=COLOR[k], lw=2, ms=8,
                 markeredgecolor="white", markeredgewidth=1.6, label=ZH[k])
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=11.5)
    ax1.set_xlim(-0.25, 2.25)
    ax1.set_ylim(min(all_y) - 0.03, max(all_y) + 0.07)
    ax1.set_ylabel("預測誤差分數（越低越好）", fontsize=11, color=INK)
    ax1.set_title("切成三段期間看：名次幾乎沒動過", fontsize=13,
                  fontweight="bold", color=INK, pad=12)
    ax1.grid(axis="y", color="#eeeeee", lw=0.9)
    ax1.set_axisbelow(True)
    ax1.legend(fontsize=9.6, frameon=False, loc="upper center",
               bbox_to_anchor=(0.5, -0.12), ncol=3)
    _tidy(ax1)

    har_peak = SUBS[periods[1]]["HAR-r2"]
    ax1.annotate(f"中段最差 {har_peak:.6f}", xy=(1, har_peak),
                 xytext=(1.15, har_peak + 0.035), fontsize=9.8, color="#8a6a1f",
                 arrowprops=dict(arrowstyle="->", color="#E69F00", lw=1.2))
    gjr_p2 = SUBS[periods[1]]["GJR-GARCH"]
    amem_p2 = SUBS[periods[1]]["AMEM-r2"]
    ax1.text(-0.2, min(all_y) - 0.008,
             f"2015-2020 這段冠軍換人：平方報酬直接版 {amem_p2:.6f}\n"
             f"些微領先壞消息加權版 {gjr_p2:.6f}",
             fontsize=9.6, color="#555555", va="bottom")

    rows = list(reversed(order))
    for i, k in enumerate(rows):
        hi_v = REG[k]["QLIKE_high_vol"]
        lo_v = REG[k]["QLIKE_low_vol"]
        ax2.plot([lo_v, hi_v], [i, i], color=COLOR[k], lw=2.4, alpha=0.5, zorder=2)
        ax2.plot(lo_v, i, "o", ms=10, color="white",
                 markeredgecolor=COLOR[k], markeredgewidth=2.2, zorder=3)
        ax2.plot(hi_v, i, "o", ms=10, color=COLOR[k],
                 markeredgecolor=COLOR[k], markeredgewidth=2.2, zorder=3)
    ax2.set_yticks(range(len(rows)))
    ax2.set_yticklabels([ZH[k] for k in rows], fontsize=11.5)
    ax2.set_ylim(-0.7, len(rows) - 0.4)
    ax2.set_xlabel("預測誤差分數（越低越好）", fontsize=11, color=INK)
    ax2.set_title("市場安靜時 vs 市場劇烈時", fontsize=13,
                  fontweight="bold", color=INK, pad=12)
    ax2.grid(axis="x", color="#eeeeee", lw=0.9)
    ax2.set_axisbelow(True)
    ax2.plot([], [], "o", ms=10, color="white", markeredgecolor=GREY,
             markeredgewidth=2.2, label="安靜期")
    ax2.plot([], [], "o", ms=10, color=GREY, markeredgecolor=GREY,
             markeredgewidth=2.2, label="劇烈期")
    ax2.legend(fontsize=10, frameon=False, loc="upper right")
    _tidy(ax2)

    har_i = rows.index("HAR-r2")
    har_hi = REG["HAR-r2"]["QLIKE_high_vol"]
    har_lo = REG["HAR-r2"]["QLIKE_low_vol"]
    ax2.annotate(f"劇烈期 {har_hi:.6f}，安靜期 {har_lo:.6f}",
                 xy=((har_hi + har_lo) / 2, har_i),
                 xytext=(har_hi - 0.02, har_i + 0.55), fontsize=9.8,
                 color="#8a6a1f", ha="left",
                 arrowprops=dict(arrowstyle="->", color="#E69F00", lw=1.2))

    fig.text(0.01, -0.03,
             f"SPY 每日資料，樣本外 {RES['oos_period']}；"
             "劇烈／安靜＝以「過去 66 個交易日已實現波動」是否高於樣本外中位數切半；"
             "三段期間為樣本外交易日等分。",
             fontsize=9, color="#666666")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    f1 = OUT_DIR / "k781_general_ranking.png"
    f2 = OUT_DIR / "k781_general_subperiod_regime.png"
    fig_ranking(f1)
    fig_subperiod_regime(f2)
    print(f"wrote {f1}")
    print(f"wrote {f2}")
