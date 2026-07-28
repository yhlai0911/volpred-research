#!/usr/bin/env python3
"""Charts for the K1589 general-audience draft.

Every number is read from experiments/k1589/k1589_results.json at run time.
Nothing is hard-coded — if the experiment is re-run, re-running this script
regenerates the figures from the new values.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]

# Durable CJK font chain — see scripts/plot_style.py (2026-06-11 tofu incident).
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()
RESULTS = ROOT / "experiments" / "k1589" / "k1589_results.json"
OUT = Path(__file__).resolve().parent

INK = "#1F2933"
MUTED = "#7B8794"
ACCENT = "#2F6F8F"
BASELINE = "#C2703D"
GRID = "#E4E7EB"

# Reader-facing names; the tickers stay visible because they are the primary key.
LABELS = {
    "RNR": "RNR\nRenaissanceRe",
    "EG": "EG\nEverest",
    "ACGL": "ACGL\nArch Capital",
    "AXS": "AXS\nAxis Capital",
    "KIE": "KIE\n保險業 ETF（對照組）",
}


def _style(ax):
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig_dose_response(d: dict) -> Path:
    """Per-stock slope with 95% bands, reinsurers vs the insurance-ETF control."""
    reg = d["regression"]
    order = ["RNR", "EG", "ACGL", "AXS", "KIE"]
    betas = [reg[t]["beta_category"] for t in order]
    errs = [1.96 * reg[t]["se_beta"] for t in order]
    colors = [BASELINE if t == "KIE" else ACCENT for t in order]

    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=170)
    _style(ax)
    xs = range(len(order))
    ax.bar(xs, betas, yerr=errs, capsize=5, color=colors, width=0.6,
           error_kw={"ecolor": MUTED, "elinewidth": 1.2})
    ax.axhline(0, color=INK, linewidth=1.0)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([LABELS[t] for t in order], fontsize=9)
    ax.set_ylabel("颶風每升一級，事件後波動率的變化幅度", color=INK, fontsize=10)
    ax.set_title(
        "四檔再保險股 vs 一檔保險業 ETF：斜率高低差不多\n"
        f"（{d['n_events_used']} 次大西洋颶風登陸，直線為 95% 區間）",
        color=INK, fontsize=12, loc="left", pad=14,
    )
    for x, b, e in zip(xs, betas, errs):
        ax.annotate(f"{b:+.4f}", (x, b + e), ha="center", va="bottom",
                    fontsize=9, color=INK)
    fig.tight_layout()
    p = OUT / "k1589_general_dose_response.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


def fig_before_after(d: dict) -> Path:
    """Average volatility before vs after landfall — how small the move actually is."""
    rv = d["rv_diagnostics"]
    order = ["RNR", "EG", "ACGL", "AXS", "KIE", "SPY"]
    names = {**{k: k for k in order}, "KIE": "KIE（對照）", "SPY": "SPY（大盤）"}
    pre = [rv[t]["pre_rv_mean"] for t in order]
    post = [rv[t]["post_rv_mean"] for t in order]

    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=170)
    _style(ax)
    xs = range(len(order))
    w = 0.36
    ax.bar([x - w / 2 for x in xs], pre, width=w, color=MUTED, label="登陸前")
    ax.bar([x + w / 2 for x in xs], post, width=w, color=ACCENT, label="登陸後五個交易日")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([names[t] for t in order], fontsize=9)
    ax.set_ylabel("年化波動率", color=INK, fontsize=10)
    ax.set_title(
        "颶風登陸前後的平均波動率：肉眼幾乎看不出差別\n"
        f"（{d['n_events_used']} 次登陸事件平均，資料 NOAA HURDAT2 × yfinance）",
        color=INK, fontsize=12, loc="left", pad=14,
    )
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    for x, a, b in zip(xs, pre, post):
        ax.annotate(f"{b - a:+.4f}", (x, max(a, b)), ha="center", va="bottom",
                    fontsize=8.5, color=INK)
    fig.tight_layout()
    p = OUT / "k1589_general_before_after.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


def main() -> None:
    d = json.loads(RESULTS.read_text(encoding="utf-8"))
    for p in (fig_dose_response(d), fig_before_after(d)):
        print(f"wrote {p.relative_to(ROOT)}")

    # Echo the figures quoted in the prose so they can be eyeballed against the draft.
    reg = d["regression"]
    it = d["kie_interaction_test"]
    print("\n--- numbers used in the draft ---")
    for t in ("RNR", "EG", "ACGL", "AXS", "KIE"):
        r = reg[t]
        holm = r.get("p_beta_holm_reinsurer_scope")
        print(f"{t:5s} beta={r['beta_category']:+.6f} t={r['t_beta']:.4f} "
              f"raw_p={r['p_beta']:.6f} holm={holm if holm is None else f'{holm:.6f}'}")
    print(f"reinsurer_mean_beta={d['identification_check']['reinsurer_mean_beta']:.6f}")
    print(f"diff_vs_KIE={it['beta_reinsurer_minus_kie_category']:+.6f} "
          f"t={it['t_reinsurer_minus_kie_category']:.4f} p={it['p_reinsurer_minus_kie_category']:.4f}")
    print(f"n_events={d['n_events_used']} verdict={d['verdict_internal']}")


if __name__ == "__main__":
    main()
