"""Generate K458 meta-analysis figures from results JSON.

Outputs (≥150 dpi):
  - forest_plot.png      effect sizes (QLIKE %diff vs GJR) with experiment labels
  - fdr_pvalues.png      DM test p-values w/ Harvey + BH thresholds
  - category_results.png stacked bars by category (null/positive/partial/informative)
  - complexity_scatter.png  n_params vs success
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

# Try Traditional Chinese fonts on macOS
for f in ["Heiti TC", "PingFang TC", "Songti TC", "Arial Unicode MS"]:
    if any(f.lower() in fn.name.lower() for fn in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [f]
        break
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments/k458/k458_meta_analysis_results.json"
OUT = ROOT / "experiments/k458/figures"
OUT.mkdir(parents=True, exist_ok=True)

with RESULTS.open() as f:
    R = json.load(f)


# ---------- Figure 1: Forest plot of QLIKE %diff vs GJR ----------
def fig_forest():
    qlike = R["qlike_vs_gjr"]["details"]
    # exclude k426 (1230% outlier swallows axis)
    rows = [(d["experiment"].upper(), d["alt_model"], d["diff_pct"], d["result"])
            for d in qlike if abs(d["diff_pct"]) < 50]
    rows.sort(key=lambda r: r[2])

    labels = [f"{e}: {m}" for e, m, _, _ in rows]
    diffs = [r[2] for r in rows]
    colors = []
    for _, _, d, res in rows:
        if d < 0 and res == "positive":
            colors.append("#2e7d32")          # green: real win
        elif d < 0:
            colors.append("#90caf9")          # light blue: numerical only
        else:
            colors.append("#c62828")          # red: worse than GJR

    fig, ax = plt.subplots(figsize=(9, 6))
    y = np.arange(len(labels))
    ax.barh(y, diffs, color=colors, edgecolor="black", linewidth=0.5)
    ax.axvline(0, color="black", linewidth=1.0)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("樣本外 QLIKE 相對 GJR-GARCH 變化 (%) — 負值代表打敗 GJR")
    ax.set_title("K458 Meta-Analysis：35 個實驗效果量森林圖（已排除 K426 +1230% 離群值）", fontsize=11)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(OUT / "forest_plot.png", dpi=160)
    plt.close()


# ---------- Figure 2: p-value funnel-style with thresholds ----------
def fig_pvalues():
    fdr = R["dm_test_audit"]["fdr_bh_q005"]["details"]
    pvals = np.array([d["p_value"] for d in fdr])
    survives = np.array([d["survives"] for d in fdr])
    labels = [d["comparison"] for d in fdr]

    # Harvey 2016 t>3.0 → two-sided p≈0.0027
    HARVEY_P = 0.0027

    fig, ax = plt.subplots(figsize=(9, 6.5))
    rank = np.arange(1, len(pvals) + 1)
    ax.plot(rank, pvals, marker="o", linestyle="-", linewidth=1, markersize=6,
            color="#37474f", label="DM test 顯著性 (升冪排序)")
    # plot BH thresholds
    bh = np.array([d["bh_threshold"] for d in fdr])
    ax.plot(rank, bh, color="#ef6c00", linestyle="--", label="Benjamini–Hochberg 門檻 q=0.05")
    ax.axhline(HARVEY_P, color="#c62828", linestyle=":", label="Harvey (2016) 嚴格門檻 (≈0.0027)")
    ax.axhline(0.05, color="#90a4ae", linestyle=":", alpha=0.6, label="傳統 0.05")
    # mark survivors
    for i, (p, s, lb) in enumerate(zip(pvals, survives, labels)):
        if s:
            ax.scatter([i + 1], [p], s=80, facecolors="none", edgecolors="#2e7d32", linewidths=1.5)
    ax.set_yscale("log")
    ax.set_xlabel("DM 檢定排序（共 22 個對比）")
    ax.set_ylabel("DM 檢定顯著性數值（對數刻度）")
    ax.set_title("K458 Meta-Analysis：22 個 DM 比較與多重檢定校正（綠圈 = 通過 BH q=0.05）", fontsize=11)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(OUT / "fdr_pvalues.png", dpi=160)
    plt.close()


# ---------- Figure 3: Category outcome breakdown ----------
def fig_category():
    cat = R["category_summary"]
    names = list(cat.keys())
    nulls = [cat[k]["null"] for k in names]
    pos = [cat[k]["positive"] for k in names]
    par = [cat[k]["partial"] for k in names]
    inf = [cat[k]["informative"] for k in names]

    order = np.argsort([cat[k]["total"] for k in names])[::-1]
    names = [names[i] for i in order]
    nulls = [nulls[i] for i in order]
    pos = [pos[i] for i in order]
    par = [par[i] for i in order]
    inf = [inf[i] for i in order]

    pretty = {
        "GARCH_extension": "GARCH 延伸",
        "ML": "機器學習",
        "anomaly": "曆日效應",
        "bayesian": "貝氏估計",
        "cross_market": "跨市場",
        "decomposition": "波動分解",
        "event_study": "事件研究",
        "external_variable": "外生變數",
        "hedging": "避險",
        "multivariate": "多變量",
        "risk_management": "風險管理",
        "strategy": "策略回測",
    }
    labels = [pretty.get(n, n) for n in names]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(labels))
    p1 = ax.bar(x, nulls, color="#90a4ae", label="無顯著結果")
    p2 = ax.bar(x, pos, bottom=nulls, color="#2e7d32", label="有正向發現")
    p3 = ax.bar(x, par, bottom=np.array(nulls) + np.array(pos), color="#fbc02d", label="部分支持")
    p4 = ax.bar(x, inf, bottom=np.array(nulls) + np.array(pos) + np.array(par),
                color="#1565c0", label="提供資訊（非預測）")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
    ax.set_ylabel("實驗數")
    ax.set_title("K458 Meta-Analysis：12 類研究主題的結果分佈（n=35）", fontsize=11)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(OUT / "category_results.png", dpi=160)
    plt.close()


# ---------- Figure 4: Complexity vs outcome ----------
def fig_complexity():
    catalog = R["experiment_catalog"]
    pts = []
    for kid, info in catalog.items():
        if info["n_params"] is None:
            continue
        pts.append((info["n_params"], info["result"], kid))

    successful_results = {"positive", "partial", "informative", "positive_is"}
    xs = [p[0] for p in pts]
    ys = [1 if p[1] in successful_results else 0 for p in pts]
    labels = [p[2].upper() for p in pts]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    rng = np.random.default_rng(458)
    jitter = rng.uniform(-0.06, 0.06, size=len(xs))
    colors = ["#2e7d32" if y else "#c62828" for y in ys]
    ax.scatter(xs, np.array(ys) + jitter, c=colors, s=80, edgecolors="black", linewidth=0.4, alpha=0.85)
    for x, y, lb in zip(xs, ys, labels):
        ax.annotate(lb, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8, alpha=0.75)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["無顯著結果", "有正向發現"])
    ax.set_xlabel("模型參數數量 (n_params)")
    corr = R["complexity_analysis"]["correlation_params_success"]
    ax.set_title(f"K458 Meta-Analysis：模型複雜度與成功率（皮爾森相關係數 = {corr:+.3f}）", fontsize=11)
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlim(left=0)
    plt.tight_layout()
    plt.savefig(OUT / "complexity_scatter.png", dpi=160)
    plt.close()


if __name__ == "__main__":
    fig_forest()
    fig_pvalues()
    fig_category()
    fig_complexity()
    print("Wrote 4 figures to", OUT)
