#!/usr/bin/env python3
"""K1451 讀者文章圖表。

暫住 storage/drafts/（內容部轄區）——platform_eng 的 owned_paths 目前不含 scripts/，
2026-08-05 由該部門建議內容部先自建、待權限下來再收編為 scripts/gen_k1451_article_charts.py。

所有數值一律從 experiments/k1451/k1451_results.json 程式化讀取，不得寫死。
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
RESULTS = ROOT / "experiments" / "k1451" / "k1451_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_MAIN = "#1D4ED8"
C_BAND = "#93C5FD"
C_ALT = "#B45309"
C_TEXT = "#1F2937"
C_MUTED = "#6B7280"


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_leadlag(res: dict) -> Path:
    ll = res["lead_lag_cross_corr"]
    lags = np.array(ll["lags"], dtype=float)
    corr = np.array(ll["corr"], dtype=float)
    lo = np.array(ll["ci_lo"], dtype=float)
    hi = np.array(ll["ci_hi"], dtype=float)

    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=170)
    ax.fill_between(lags, lo, hi, color=C_BAND, alpha=0.35, label="95% 區間")
    ax.plot(lags, corr, color=C_MAIN, marker="o", markersize=4.5, linewidth=2, label="相關係數")
    ax.axhline(0, color=C_MUTED, linewidth=1, linestyle="--")

    ax.set_title("訊號與未來波動的相關係數：沒有出現領先尖峰", fontsize=13, color=C_TEXT, pad=12)
    ax.set_xlabel("落後期（負值＝訊號更早，正值＝訊號更晚）", fontsize=10, color=C_MUTED)
    ax.set_ylabel("相關係數", fontsize=10, color=C_MUTED)
    ax.set_xticks(lags)
    ax.legend(frameon=False, fontsize=9.5, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)

    ax.annotate(
        f"整段落在 {corr.max():.2f} 到 {corr.min():.2f} 之間，平緩移動",
        xy=(0.5, 0.06),
        xycoords="axes fraction",
        ha="center",
        fontsize=9,
        color=C_MUTED,
    )

    out = ASSETS / "k1451_general_leadlag.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return out


def fig_coef_collapse(res: dict) -> Path:
    uni = res["models"]["univariate"]["hyg_lqd_chg22_lag1"]
    ctl = res["models"]["vix_control_level"]["hyg_lqd_chg22_lag1"]

    labels = ["單獨看信用價差", "把恐慌指數也放進來"]
    coefs = [uni["coef"], ctl["coef"]]
    errs = [1.96 * uni["se_hac"], 1.96 * ctl["se_hac"]]
    pvals = [uni["p_hac"], ctl["p_hac"]]

    fig, ax = plt.subplots(figsize=(8.2, 4.2), dpi=170)
    ypos = [1, 0]
    ax.errorbar(
        coefs,
        ypos,
        xerr=errs,
        fmt="o",
        color=C_MAIN,
        ecolor=C_BAND,
        elinewidth=4,
        capsize=0,
        markersize=9,
    )
    ax.axvline(0, color=C_MUTED, linewidth=1, linestyle="--")

    for x, y, p in zip(coefs, ypos, pvals):
        ax.annotate(
            f"斜率 {x:.4f}　機率值 {p:.3f}",
            xy=(x, y),
            xytext=(0, 14),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            color=C_TEXT,
        )

    ratio = abs(ctl["coef"] / uni["coef"]) * 100
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=11, color=C_TEXT)
    ax.set_xlabel("信用價差對未來波動的斜率（含 95% 區間）", fontsize=10, color=C_MUTED)
    ax.set_title(f"控制恐慌指數之後，斜率只剩原本的 {ratio:.1f}%", fontsize=13, color=C_TEXT, pad=12)
    ax.set_ylim(-0.6, 1.6)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    out = ASSETS / "k1451_general_coef_collapse.png"
    fig.tight_layout()
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load()
    for path in (fig_leadlag(res), fig_coef_collapse(res)):
        print(f"[K1451_charts] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
