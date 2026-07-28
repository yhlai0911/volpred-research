#!/usr/bin/env python3
"""Chart for the K1658 general-audience draft.

Reads experiments/k1658/K1658_results.json at run time — no hard-coded numbers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()

RESULTS = ROOT / "experiments" / "k1658" / "K1658_results.json"
OUT = Path(__file__).resolve().parent

INK = "#1F2933"
MUTED = "#7B8794"
RAW = "#2F6F8F"
ADJ = "#C2703D"
GRID = "#E4E7EB"

ASSET_LABEL = {"TLT": "TLT 長天期公債", "IEF": "中天期公債 IEF", "ZN=F": "ZN 公債期貨"}
PROXY_LABEL = {"parkinson": "高低價口徑", "sqret": "收盤報酬口徑"}


def fig_raw_vs_holm(d: dict) -> Path:
    """Six tests: nominal evidence vs evidence after correcting for six looks."""
    res = d["part3_aggregate_fomc_effect"]["results"]
    labels = [f"{ASSET_LABEL.get(r['asset'], r['asset'])}\n{PROXY_LABEL.get(r['proxy'], r['proxy'])}"
              for r in res]
    raw = [r["p_value_raw"] for r in res]
    holm = [r["p_value_holm"] for r in res]

    fig, ax = plt.subplots(figsize=(9.6, 5.2), dpi=170)
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)

    ys = range(len(res))
    for y, a, b in zip(ys, raw, holm):
        ax.plot([a, b], [y, y], color=MUTED, linewidth=1.4, zorder=1)
    ax.scatter(raw, list(ys), s=70, color=RAW, zorder=3, label="單看這一組時")
    ax.scatter(holm, list(ys), s=70, color=ADJ, zorder=3, label="扣掉「測了六組」之後")
    ax.axvline(0.05, color=INK, linestyle="--", linewidth=1.1)
    ax.annotate("常用的 0.05 門檻", (0.05, len(res) - 0.4), xytext=(6, 0),
                textcoords="offset points", fontsize=9, color=INK)

    ax.set_yticks(list(ys))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("「純屬運氣」的機率（愈左邊愈不像運氣）", color=INK, fontsize=10)
    ax.set_xlim(-0.03, 1.06)
    ax.set_title(
        "六組檢定，沒有一組撐過多重比較\n"
        f"（聯準會開會隔天的利率資產波動，樣本 {res[0]['n_obs']:,} 個交易日、"
        f"{res[0]['n_fomc_lag_days']} 個開會日）",
        color=INK, fontsize=12, loc="left", pad=14,
    )
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    p = OUT / "k1658_general_raw_vs_holm.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


def main() -> None:
    d = json.loads(RESULTS.read_text(encoding="utf-8"))
    print(f"wrote {fig_raw_vs_holm(d).relative_to(ROOT)}")

    print("\n--- numbers used in the draft ---")
    p1 = d["part1_feasibility_diagnosis"]["per_asset"]
    for a, v in p1.items():
        print(f"{a:5s} intraday {v['intraday_coverage_start']}..{v['intraday_coverage_end']} "
              f"n_days={v['n_trading_days']} usable_fomc={v['n_usable_events']} {v['usable_fomc_events']}")
    p3 = d["part3_aggregate_fomc_effect"]
    print(f"holm family={p3['multiple_testing']['family_size']} "
          f"n_signif={p3['multiple_testing']['n_significant_after_holm']}")
    for r in p3["results"]:
        print(f"{r['asset']:5s} {r['proxy']:10s} pct_var={r['beta_pct_effect_on_variance']:+.3f} "
              f"t={r['t_stat']:+.4f} raw_p={r['p_value_raw']:.6f} holm={r['p_value_holm']:.4f}")


if __name__ == "__main__":
    main()
