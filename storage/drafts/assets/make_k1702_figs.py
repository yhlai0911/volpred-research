"""K1702 一般讀者文章配圖 — 全部數字直接讀 experiments/k1702/k1702_results.json。"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[3]
RES = json.loads((ROOT / "experiments/k1702/k1702_results.json").read_text())
OUT = ROOT / "storage/drafts/assets"

for cand in ["Heiti TC", "PingFang TC", "Songti TC", "Arial Unicode MS"]:
    if any(f.name == cand for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

FACTORS = ["SMB", "HML", "RMW", "CMA", "MOM", "QMJ"]
LABEL = {
    "SMB": "SMB 小型股",
    "HML": "HML 價值",
    "RMW": "RMW 高獲利",
    "CMA": "CMA 保守投資",
    "MOM": "MOM 動能",
    "QMJ": "QMJ 品質",
}
BLUE, RED, GREY = "#2E6F9E", "#C0392B", "#9AA5AD"

dd = RES["drawdown_analysis"]["per_factor"]
rand = RES["drawdown_analysis"]["primary_randomization_test"]["per_factor"]
cost25 = RES["cost_survival"]["25"]["per_factor_sharpe_difference"]

# ── 圖 1：raw 回撤「改善」vs 曝險匹配後的真實差距 ────────────────────────────
raw_gap = [(-dd[f]["unmanaged_max_drawdown"] + dd[f]["managed_max_drawdown"]) * -100 for f in FACTORS]
# raw_gap = managed_mdd - unmanaged_mdd (百分點, 正 = 回撤變淺)
raw_gap = [(dd[f]["managed_max_drawdown"] - dd[f]["unmanaged_max_drawdown"]) * 100 for f in FACTORS]
matched_gap = [dd[f]["production_exposure_matched_gap_pp"] for f in FACTORS]

x = np.arange(len(FACTORS))
w = 0.38
fig, ax = plt.subplots(figsize=(10, 5.6))
b1 = ax.bar(x - w / 2, raw_gap, w, label="原始比較（沒調曝險）", color=BLUE)
b2 = ax.bar(x + w / 2, matched_gap, w, label="曝險匹配後（同樣風險再比）", color=RED)
ax.axhline(0, color="#333", lw=1)
ax.set_xticks(x)
ax.set_xticklabels([LABEL[f] for f in FACTORS], fontsize=10)
ax.set_ylabel("最大回撤改善（百分點，正值 = 回撤變淺）", fontsize=11)
ax.set_title("波動率調控讓回撤變淺？換成同樣曝險再比，六個因子只剩一個還是正的\n"
             "K1702｜2000-01～2026-04 樣本外，25bp 成本", fontsize=13, pad=14)
for bars in (b1, b2):
    for b in bars:
        v = b.get_height()
        ax.annotate(f"{v:+.0f}", (b.get_x() + b.get_width() / 2, v),
                    ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=9, xytext=(0, 3 if v >= 0 else -3), textcoords="offset points")
ax.legend(fontsize=10, frameon=False)
ax.set_ylim(min(matched_gap) - 8, max(raw_gap) + 12)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(0.5, -0.02, "資料：Fama-French / AQR 官方因子月報酬；計算：experiments/k1702",
         ha="center", fontsize=8.5, color="#666")
fig.tight_layout()
fig.savefig(OUT / "k1702_mdd_raw_vs_matched.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ── 圖 2：樣本外 Sharpe 變化（25bp） ────────────────────────────────────────
deltas = [cost25[f] for f in FACTORS]
order = np.argsort(deltas)
fs = [FACTORS[i] for i in order]
ds = [deltas[i] for i in order]
fig, ax = plt.subplots(figsize=(9, 5))
colors = [RED if d < 0 else BLUE for d in ds]
bars = ax.barh([LABEL[f] for f in fs], ds, color=colors, height=0.6)
ax.axvline(0, color="#333", lw=1)
for b, d in zip(bars, ds):
    ax.annotate(f"{d:+.2f}", (d, b.get_y() + b.get_height() / 2),
                va="center", ha="left" if d >= 0 else "right",
                xytext=(4 if d >= 0 else -4, 0), textcoords="offset points", fontsize=10)
ax.set_xlabel("樣本外 Sharpe 變化（波動率調控後 − 原始因子）", fontsize=11)
ax.set_title("六個因子套上波動率調控，樣本外只有動能變好\n"
             "K1702｜2000-01～2026-04，316 個月，25bp 成本，槓桿上限 3 倍", fontsize=13, pad=14)
ax.set_xlim(min(ds) - 0.12, max(ds) + 0.12)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(0.5, -0.02, "資料：Fama-French / AQR 官方因子；計算：experiments/k1702",
         ha="center", fontsize=8.5, color="#666")
fig.tight_layout()
fig.savefig(OUT / "k1702_oos_sharpe_delta.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ── 圖 3：MOM 的相位隨機化 null 分布 ────────────────────────────────────────
mom = rand["MOM"]
null_gaps = np.array(mom["null_exposure_matched_gaps"]) * 100
obs = dd["MOM"]["production_exposure_matched_gap_pp"]
p = mom["one_sided_p"]
fig, ax = plt.subplots(figsize=(9.5, 5.2))
ax.hist(null_gaps, bins=30, color=GREY, edgecolor="white")
ax.axvline(obs, color=RED, lw=2.4)
ax.set_ylim(0, ax.get_ylim()[1] * 1.35)
ax.annotate(f"真實訊號 {obs:+.1f} 個百分點\n316 條假訊號裡有 {mom['null_exceedance_count']} 條打得更好\n單尾 p = {p:.3f}（不顯著）",
            (obs, ax.get_ylim()[1] * 0.97), xytext=(-14, 0), textcoords="offset points",
            ha="right", va="top", fontsize=10.5, color=RED)
ax.set_xlabel("曝險匹配後的回撤改善（百分點）", fontsize=11)
ax.set_ylabel("假訊號出現次數", fontsize=11)
ax.set_title("把動能的加減碼時點整段挪開，回撤照樣變淺\n"
             "MOM：真實權重路徑 vs 316 種被打亂時點的同一條路徑", fontsize=13, pad=14)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(0.5, -0.02, "資料：experiments/k1702 相位隨機化檢定（circular shift，Holm 校正）",
         ha="center", fontsize=8.5, color="#666")
fig.tight_layout()
fig.savefig(OUT / "k1702_mom_phase_null.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print("raw_gap", dict(zip(FACTORS, [round(v, 1) for v in raw_gap])))
print("matched_gap", dict(zip(FACTORS, [round(v, 1) for v in matched_gap])))
print("MOM p", p, "exceed", mom["null_exceedance_count"], "holm", mom["holm_adjusted_p"])
print("saved 3 figs to", OUT)
