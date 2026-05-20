"""K619 figures: bug-fix before/after + 4-model QLIKE comparison.

Inputs: experiments/k619/k619_kan_corrected_results.json
Outputs:
  - fig1_bug_fix_before_after.png
  - fig2_model_qlike_comparison.png
  - fig3_complexity_vs_qlike.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Heiti TC", "PingFang TC", "Noto Sans CJK TC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[3]
RES = json.loads((ROOT / "experiments/k619/k619_kan_corrected_results.json").read_text())
OUT = ROOT / "experiments/k619/figures"
OUT.mkdir(parents=True, exist_ok=True)


def fig1_bug_fix() -> None:
    """K618 (有 bug) vs K619 (修正後) 各模型 QLIKE 對比。"""
    cmp = RES["k618_comparison"]
    models = ["GJR-GARCH", "HAR-ABS", "KAN", "MLP"]
    k618_vals = [cmp[m]["K618_QLIKE"] for m in models]
    k619_vals = [cmp[m]["K619_QLIKE"] for m in models]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=180)
    x = list(range(len(models)))
    w = 0.36
    ax.bar([i - w / 2 for i in x], k618_vals, width=w,
           color="#d96c6c", label="K618（含兩個 bug）")
    ax.bar([i + w / 2 for i in x], k619_vals, width=w,
           color="#5a9bd4", label="K619（修正後）")

    for i, (a, b) in enumerate(zip(k618_vals, k619_vals)):
        ax.text(i - w / 2, a + max(k618_vals) * 0.01, f"{a:.3f}",
                ha="center", va="bottom", fontsize=8.5)
        ax.text(i + w / 2, b + max(k618_vals) * 0.01, f"{b:.3f}",
                ha="center", va="bottom", fontsize=8.5)

    ax.set_xticks(x)
    ax.set_xticklabels(models)
    ax.set_ylabel("QLIKE 損失（越低越好）")
    ax.set_title("K618 兩個 bug 修正前後 QLIKE 變化（OOS 2023–2024，n=501）")
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_bug_fix_before_after.png", dpi=180)
    plt.close(fig)


def fig2_model_compare() -> None:
    """4 模型 QLIKE 並列（K619 修正後）。"""
    res = RES["results"]
    order = ["GJR-GARCH", "KAN", "MLP", "HAR-ABS"]  # 依 QLIKE 由低到高大致排
    qlike = [res[m]["QLIKE"] for m in order]
    corr = [res[m]["Correlation"] for m in order]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.8), dpi=180)

    colors = ["#3a7d44", "#5a9bd4", "#d4a44d", "#a26da3"]
    ax1.bar(order, qlike, color=colors)
    for i, v in enumerate(qlike):
        ax1.text(i, v + 0.003, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
    ax1.set_ylabel("QLIKE（越低越好）")
    ax1.set_title("修正後 4 模型 QLIKE 對比")
    ax1.set_ylim(0.45, max(qlike) * 1.04)
    ax1.grid(axis="y", alpha=0.3)

    ax2.bar(order, corr, color=colors)
    for i, v in enumerate(corr):
        ax2.text(i, v + 0.005, f"{v:.3f}", ha="center", va="bottom", fontsize=9)
    ax2.set_ylabel("與真實 |r_t| 的相關係數")
    ax2.set_title("修正後 4 模型預測相關係數")
    ax2.grid(axis="y", alpha=0.3)

    fig.suptitle("K619：KAN 與三個基準模型的 OOS 表現（SPY，2023–2024）",
                 fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_model_qlike_comparison.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def fig3_complexity() -> None:
    """模型參數量 vs QLIKE 散點，視覺呈現 ML 模型多花參數但沒有實際優勢。"""
    res = RES["results"]
    cmplx = RES["model_complexity"]
    name_map = {
        "GJR-GARCH": "GJR_params",
        "HAR-ABS": "HAR_params",
        "KAN": "KAN_params",
        "MLP": "MLP_params",
    }
    pts = [(name, cmplx[name_map[name]], res[name]["QLIKE"])
           for name in ["GJR-GARCH", "HAR-ABS", "KAN", "MLP"]]

    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=180)
    colors = {"GJR-GARCH": "#3a7d44", "HAR-ABS": "#a26da3",
              "KAN": "#5a9bd4", "MLP": "#d4a44d"}
    for name, p, q in pts:
        ax.scatter(p, q, s=200, color=colors[name], edgecolor="black",
                   linewidth=0.8, zorder=3, label=f"{name}（{p} 參數）")
        offset_y = 0.0035 if name != "MLP" else -0.005
        ax.annotate(f"{q:.4f}", xy=(p, q),
                    xytext=(p * 1.15 + 5, q + offset_y), fontsize=9)

    ax.set_xscale("log")
    ax.set_xlabel("模型參數量（log scale）")
    ax.set_ylabel("QLIKE（越低越好）")
    ax.set_title("參數複雜度 vs OOS QLIKE：複雜模型沒有換來更好的預測")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "fig3_complexity_vs_qlike.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    fig1_bug_fix()
    fig2_model_compare()
    fig3_complexity()
    for f in sorted(OUT.glob("*.png")):
        print(f"wrote {f.relative_to(ROOT)} ({f.stat().st_size // 1024} KB)")
