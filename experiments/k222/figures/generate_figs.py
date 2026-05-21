"""
Generate qualitative figures for K222 corrigendum (mile_5302df53 / mile_e8aefbf1).

Source data: K87 cross-validation refutation of K85's "VT doubles SWR" claim
(see knowledge.json line 9515).

Two PNGs:
  fig_swr_refutation.png   — old claim vs K87 stress-test bootstrap on 8% WR
  fig_vt_role_reframe.png  — VT 真正角色：variance narrowing under 4% WR
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent

plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.family"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS", "sans-serif"]

# ---- Figure 1: 8% WR survival — old claim vs K87 cross-validation ----
labels = ["原宣稱 (K85)", "Bootstrap A", "Bootstrap B", "Bootstrap C", "Bootstrap D", "Bootstrap E"]
survival = [95.5, 28.0, 27.1, 26.4, 25.6, 25.2]
colors = ["#999999"] + ["#c0392b"] * 5

fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.bar(labels, survival, color=colors, edgecolor="black", linewidth=0.5)
ax.axhline(95.0, color="#888", ls="--", lw=0.8, label="95% 存活門檻")
ax.set_ylim(0, 105)
ax.set_ylabel("8% 提領率下 30 年存活率 (%)")
ax.set_title("K87 交叉驗證：8% 提領率「翻倍」宣稱被推翻\n(5 種 block size bootstrap 全部 < 30%)")
for b, v in zip(bars, survival):
    ax.text(b.get_x() + b.get_width()/2, v + 1.5, f"{v:.1f}%", ha="center", fontsize=9)
ax.legend(loc="upper right", fontsize=9)
plt.tight_layout()
plt.savefig(OUT / "fig_swr_refutation.png", dpi=150)
plt.close()

# ---- Figure 2: VT 真正角色 — 4% WR 下變異變窄 (qualitative density) ----
rng = np.random.default_rng(42)
# Synthetic terminal wealth densities under 4% WR — 兩者中位數接近、VT 尾部窄
bh = rng.lognormal(mean=np.log(2.5e6), sigma=0.95, size=20000) * 1.0
vt = rng.lognormal(mean=np.log(2.6e6), sigma=0.55, size=20000) * 1.0  # narrower

fig, ax = plt.subplots(figsize=(9, 4.5))
bins = np.linspace(0, 1.5e7, 60)
ax.hist(bh / 1e6, bins=bins/1e6, alpha=0.55, color="#3498db", label="B&H SPY (4% WR)", density=True)
ax.hist(vt / 1e6, bins=bins/1e6, alpha=0.55, color="#e67e22", label="VT 12/VIX (4% WR)", density=True)
ax.axvline(np.median(bh)/1e6, color="#3498db", ls="--", lw=1)
ax.axvline(np.median(vt)/1e6, color="#e67e22", ls="--", lw=1)
ax.set_xlabel("30 年後資產終值 ($M, 起始 $1M)")
ax.set_ylabel("密度（示意）")
ax.set_title("K222 修正後 VT 的真正角色：4% WR 下變異變窄、不是提領率翻倍\n(示意圖；2026-05-06 K222 lookahead patch 後待 rerun 取代)")
ax.legend(loc="upper right")
ax.text(0.02, 0.95, "* 此為定性示意，非 post-patch 數值結果。\n  K222 待重跑後以實際數據替換。",
        transform=ax.transAxes, fontsize=8, va="top",
        bbox=dict(boxstyle="round,pad=0.3", fc="#fef9e7", ec="#888"))
plt.tight_layout()
plt.savefig(OUT / "fig_vt_role_reframe.png", dpi=150)
plt.close()

print("OK", list(OUT.glob("*.png")))
