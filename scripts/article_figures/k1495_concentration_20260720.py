"""K1495 article figures — all numbers bound to experiments/k1495/k1495_results.json.

Fig 1: high vs non-high regime forward 21d RV, SPY and RSP side by side
       (shows the effect shows up in BOTH, not only cap-weight).
Fig 2: stationary-bootstrap 95% CI dot-whisker for the three headline
       contrasts (SPY vol / RSP vol / SPY-RSP gap).

Run: uv run python scripts/article_figures/k1495_concentration_20260720.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=160)

RESULTS = json.loads((ROOT / "experiments" / "k1495" / "k1495_results.json").read_text())
OUT = ROOT / "storage" / "article_assets" / "k1495-concentration-20260720"
OUT.mkdir(parents=True, exist_ok=True)

gm = RESULTS["group_means"]
tests = RESULTS["tests"]

NAVY = "#1f3b73"
RUST = "#c1553b"
GREY = "#8a8f98"


def fig1() -> Path:
    hi = gm["high_regime"]
    lo = gm["non_high_regime"]
    labels = ["SPY\n（市值加權）", "RSP\n（等權重）"]
    lo_vals = [lo["fwd_rv21_spy"] * 100, lo["fwd_rv21_rsp"] * 100]
    hi_vals = [hi["fwd_rv21_spy"] * 100, hi["fwd_rv21_rsp"] * 100]

    x = range(len(labels))
    w = 0.34
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    b1 = ax.bar([i - w / 2 for i in x], lo_vals, w, label="非高集中期", color=GREY)
    b2 = ax.bar([i + w / 2 for i in x], hi_vals, w, label="高集中期（前 20%）", color=RUST)
    for bars in (b1, b2):
        for bar in bars:
            ax.annotate(
                f"{bar.get_height():.2f}%",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                ha="center",
                va="bottom",
                fontsize=10,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("未來 21 個交易日年化實現波動率 (%)")
    ax.set_title("高集中期之後，兩種指數的波動都一起升高", fontsize=13, pad=12)
    ax.set_ylim(0, max(hi_vals) * 1.22)
    ax.legend(frameon=False, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.text(
        0.01,
        0.005,
        f"資料：yfinance 日調整收盤 | 樣本 {RESULTS['data']['period']['start']} ~ "
        f"{RESULTS['data']['period']['end']}, n={RESULTS['data']['n_obs']:,} | K1495",
        fontsize=8,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    p = OUT / "fig1_high_vs_nonhigh_forward_rv.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def fig2() -> Path:
    rows = [
        ("SPY 未來波動差", tests["fwd_rv21_spy"]),
        ("RSP 未來波動差", tests["fwd_rv21_rsp"]),
        ("SPY − RSP 波動缺口差", tests["fwd_rv_gap"]),
    ]
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    for i, (name, t) in enumerate(rows):
        lo_ci, hi_ci = (v * 100 for v in t["bootstrap_ci_95"])
        pt = t["diff_high_minus_non_high"] * 100
        crosses_zero = lo_ci <= 0 <= hi_ci
        color = GREY if crosses_zero else NAVY
        ax.plot([lo_ci, hi_ci], [i, i], color=color, lw=3, solid_capstyle="round")
        ax.plot([pt], [i], "o", color=color, ms=9)
        ax.annotate(
            f"{pt:+.2f}pp　[{lo_ci:+.2f}, {hi_ci:+.2f}]",
            (hi_ci, i),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color="#333",
        )
    ax.axvline(0, color="#c0392b", lw=1, ls="--")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel("高集中期 減 非高集中期（百分點），stationary bootstrap 95% 區間")
    ax.set_title("兩檔指數的波動都顯著升高，兩者的差距卻沒拉開", fontsize=13, pad=12)
    ax.set_xlim(-3.5, 12.5)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25)
    fig.text(
        0.01,
        0.01,
        "灰色 = 95% 區間跨過 0（無法排除沒有差別）| 來源：K1495 k1495_results.json",
        fontsize=8,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    p = OUT / "fig2_bootstrap_ci.png"
    fig.savefig(p)
    plt.close(fig)
    return p


if __name__ == "__main__":
    for path in (fig1(), fig2()):
        print(f"wrote {path}")
