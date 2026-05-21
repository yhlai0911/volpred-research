#!/usr/bin/env python3
"""
K471 figures for general-audience article.

All numbers source: experiments/k471/k471_higher_moments_results.json
Lookahead-clean: figures plot in-sample diagnostics + OOS metrics already
computed in the source script (which uses fwd window correctly per script L114).
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k471_higher_moments_results.json").read_text())
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

# Traditional Chinese font on macOS
mpl.rcParams["font.sans-serif"] = ["Heiti TC", "STHeiti", "Arial Unicode MS", "sans-serif"]
mpl.rcParams["axes.unicode_minus"] = False
DPI = 160

ASSETS = ["SPY", "QQQ", "BTC-USD"]
ASSET_COLORS = {"SPY": "#1f77b4", "QQQ": "#2ca02c", "BTC-USD": "#d62728"}


# ---------------------------------------------------------------
# Figure 1: Correlation of higher moments with forward 21-day RV
# ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5.8))
features = ["skew5", "skew21", "skew63", "kurt5", "kurt21", "kurt63"]
feat_labels = ["偏態5日", "偏態21日", "偏態63日", "峰度5日", "峰度21日", "峰度63日"]
x = np.arange(len(features))
width = 0.26
for i, asset in enumerate(ASSETS):
    corrs = [RESULTS["diagnostics"][asset]["corr_with_fwd_rv21"][f]["r"] for f in features]
    ax.bar(x + (i - 1) * width, corrs, width, label=asset, color=ASSET_COLORS[asset])
ax.axhline(0, color="black", lw=0.8)
ax.set_xticks(x)
ax.set_xticklabels(feat_labels, rotation=15)
ax.set_ylabel("與未來 21 日已實現波動的相關係數")
ax.set_title("圖 1｜高階動差與未來波動的相關性：方向有，幅度小（K471）")
ax.legend(loc="lower left")
ax.grid(axis="y", alpha=0.3)
ax.text(0.02, 0.97,
        "資料來源：yfinance 2010-01-01–2025-12-31\n樣本數：SPY/QQQ 4,002 日；BTC 4,102 日",
        transform=ax.transAxes, fontsize=8, va="top", color="#555")
fig.tight_layout()
fig.savefig(FIG_DIR / "k471_corr_with_fwd_rv.png", dpi=DPI, bbox_inches="tight")
plt.close(fig)
print("saved:", FIG_DIR / "k471_corr_with_fwd_rv.png")


# ---------------------------------------------------------------
# Figure 2: OOS Δ R² (incremental R² over baseline) per model per asset
# + DM significance flags
# ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10.5, 5.8))
inc = RESULTS["incremental_r2"]
model_keys = ["M2_rv_skew_OLS", "M3_rv_kurt_OLS", "M4_rv_skew_kurt_OLS",
              "M5_full_OLS", "M6_kitchen_sink_OLS"]
model_labels = ["+偏態21", "+峰度21", "+偏態+峰度",
                "全 6 動差", "全動差+下行+負比"]
x = np.arange(len(model_keys))
width = 0.26
for i, asset in enumerate(ASSETS):
    deltas = [inc[asset]["increments"][m]["delta_r2"] for m in model_keys]
    bars = ax.bar(x + (i - 1) * width, deltas, width, label=asset, color=ASSET_COLORS[asset])
    # Mark statistically distinguishable improvements (DM p<0.05 with positive delta)
    for j, m in enumerate(model_keys):
        dm = inc[asset]["increments"][m].get("dm_pvalue")
        d = deltas[j]
        if dm is not None and dm < 0.05 and d > 0:
            ax.text(x[j] + (i - 1) * width, d + 0.005, "★", ha="center",
                    fontsize=11, color="#b8860b")
ax.axhline(0, color="black", lw=0.8)
ax.set_xticks(x)
ax.set_xticklabels(model_labels, rotation=10)
ax.set_ylabel("增量 R²（相對「只用過去波動」基準）")
ax.set_title("圖 2｜加上偏態/峰度後 OOS R² 的變化（★＝兩模型比較顯著, K471）")
ax.legend(loc="upper right")
ax.grid(axis="y", alpha=0.3)
ax.text(0.02, 0.03,
        "OOS 期間：2023-01-01–2025-12-31\n基準：以過去 21 日波動預測未來 21 日波動",
        transform=ax.transAxes, fontsize=8, va="bottom", color="#555")
fig.tight_layout()
fig.savefig(FIG_DIR / "k471_delta_r2.png", dpi=DPI, bbox_inches="tight")
plt.close(fig)
print("saved:", FIG_DIR / "k471_delta_r2.png")


# ---------------------------------------------------------------
# Figure 3: Regime split — high-vol vs low-vol correlations
# ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5.5))
regimes = RESULTS["regime_analysis"]
xs = np.arange(len(ASSETS))
width = 0.2
hi_skew = [regimes[a]["regime_correlations"]["high_vol"]["skew21"]["r"] for a in ASSETS]
lo_skew = [regimes[a]["regime_correlations"]["low_vol"]["skew21"]["r"] for a in ASSETS]
hi_kurt = [regimes[a]["regime_correlations"]["high_vol"]["kurt21"]["r"] for a in ASSETS]
lo_kurt = [regimes[a]["regime_correlations"]["low_vol"]["kurt21"]["r"] for a in ASSETS]

ax.bar(xs - 1.5 * width, hi_skew, width, label="高波動期｜偏態21", color="#1f77b4")
ax.bar(xs - 0.5 * width, lo_skew, width, label="低波動期｜偏態21", color="#9ec5e8")
ax.bar(xs + 0.5 * width, hi_kurt, width, label="高波動期｜峰度21", color="#d62728")
ax.bar(xs + 1.5 * width, lo_kurt, width, label="低波動期｜峰度21", color="#f4a8a8")

ax.axhline(0, color="black", lw=0.8)
ax.set_xticks(xs)
ax.set_xticklabels(ASSETS)
ax.set_ylabel("與未來波動的相關係數")
ax.set_title("圖 3｜高低波動分期下，相關性更不穩定（K471）")
ax.legend(loc="lower right", ncol=2, fontsize=9)
ax.grid(axis="y", alpha=0.3)
ax.text(0.02, 0.03,
        "區分依據：滾動 21 日 RV 與該資產樣本中位數比較\n"
        "SPY 中位數 0.125、QQQ 0.160、BTC 0.451（年化）",
        transform=ax.transAxes, fontsize=8, va="bottom", color="#555")
fig.tight_layout()
fig.savefig(FIG_DIR / "k471_regime_corr.png", dpi=DPI, bbox_inches="tight")
plt.close(fig)
print("saved:", FIG_DIR / "k471_regime_corr.png")


# ---------------------------------------------------------------
# Figure 4: Distribution of rolling 21-day skewness across assets
# ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9.5, 5.2))
diag = RESULTS["diagnostics"]
labels = ASSETS
means = [diag[a]["skew21_mean"] for a in ASSETS]
stds = [diag[a]["skew21_std"] for a in ASSETS]
mins = [diag[a]["skew21_min"] for a in ASSETS]
maxs = [diag[a]["skew21_max"] for a in ASSETS]

xs = np.arange(len(labels))
# Range bar (min-max)
for i, a in enumerate(ASSETS):
    ax.vlines(xs[i], mins[i], maxs[i], color="#999", lw=2, alpha=0.6)
    # ±1 sd band
    ax.vlines(xs[i], means[i] - stds[i], means[i] + stds[i],
              color=ASSET_COLORS[a], lw=10, alpha=0.7)
    ax.scatter(xs[i], means[i], color="black", s=40, zorder=5)
    ax.text(xs[i] + 0.08, means[i], f"平均 {means[i]:.2f}", va="center", fontsize=9)
    ax.text(xs[i] + 0.08, mins[i], f"最低 {mins[i]:.2f}", va="center", fontsize=8, color="#666")
    ax.text(xs[i] + 0.08, maxs[i], f"最高 {maxs[i]:.2f}", va="center", fontsize=8, color="#666")

ax.axhline(0, color="black", lw=0.8, ls="--")
ax.set_xticks(xs)
ax.set_xticklabels(labels)
ax.set_ylabel("滾動 21 日偏態值")
ax.set_title("圖 4｜偏態本身波動劇烈：估計噪音為何稀釋預測力（K471）")
ax.grid(axis="y", alpha=0.3)
ax.text(0.02, 0.03,
        "粗色條為 ±1 標準差區間，灰線為樣本最小/最大值\n"
        "SPY/QQQ 平均偏態為負（左尾風險高），BTC 接近 0",
        transform=ax.transAxes, fontsize=8, va="bottom", color="#555")
fig.tight_layout()
fig.savefig(FIG_DIR / "k471_skew_distribution.png", dpi=DPI, bbox_inches="tight")
plt.close(fig)
print("saved:", FIG_DIR / "k471_skew_distribution.png")

print("ALL DONE")
