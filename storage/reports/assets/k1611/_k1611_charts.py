#!/usr/bin/env python3
"""Charts for the K1611 general-audience draft (jargon-free labels).

Reads experiments/k1611/K1611_results.json (single source of truth) and renders
two PNGs used by storage/drafts/K1611_general_draft.md. All on-chart text is
plain Chinese — no model acronyms, no metric acronyms (audience=general gate).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[4]
RES = json.loads((ROOT / "experiments/k1611/K1611_results.json").read_text())["assets"]
OUT = Path(__file__).resolve().parent

plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

AVG_C = "#8aa8c8"   # 平均派
ASY_C = "#1f4e79"   # 不對稱派

# ── Fig 1: 預測誤差分數 by 市況（primary proxy = 報酬平方）────────────────
assets = [("SPY", "美股 SPY（4,156 個交易日）"), ("0050.TW", "台股 0050（1,212 個交易日）")]
fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6))
for ax, (key, title) in zip(axes, assets):
    p = RES[key]["proxies"]["r2"]
    hi, lo = p["regime_subsample_high"], p["regime_subsample_low"]
    avg = [hi["qlike_har"], lo["qlike_har"]]
    asy = [hi["qlike_gjr"], lo["qlike_gjr"]]
    x = [0, 1]
    w = 0.34
    ax.bar([i - w / 2 for i in x], avg, w, label="平均派", color=AVG_C)
    ax.bar([i + w / 2 for i in x], asy, w, label="不對稱派", color=ASY_C)
    for i, (a, b) in enumerate(zip(avg, asy)):
        ax.text(i - w / 2, a + 0.02, f"{a:.3f}", ha="center", fontsize=9, color="#333")
        ax.text(i + w / 2, b + 0.02, f"{b:.3f}", ha="center", fontsize=9, color="#333")
    ax.set_xticks(x)
    ax.set_xticklabels([f"高恐慌日\n({hi['n']} 天)", f"低恐慌日\n({lo['n']} 天)"], fontsize=10)
    ax.set_title(title, fontsize=11)
    ax.set_ylim(0, max(avg + asy) * 1.22)
    ax.set_ylabel("預測誤差分數（越低越準）", fontsize=9.5)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, framealpha=0.9)
fig.suptitle("兩種市況下的預測誤差：深藍（不對稱派）在四根組合裡都比較低", fontsize=12.5)
fig.text(0.5, 0.005, "資料：實驗 k1611。真實波動以當日報酬平方衡量；恐慌高低以前一日 VIX 對過去中位數切分。",
         ha="center", fontsize=8.2, color="#666")
fig.tight_layout(rect=(0, 0.035, 1, 0.94))
fig.savefig(OUT / "k1611_qlike_by_regime.png", dpi=150)
plt.close(fig)

# ── Fig 2: 市況對「誤差差距」的影響量 + 95% 區間，全部蓋住 0 ─────────────
CELLS = [
    ("SPY", "r2", "美股 · 報酬平方"),
    ("SPY", "rsov", "美股 · 區間加跳空"),
    ("0050.TW", "r2", "台股 · 報酬平方"),
    ("0050.TW", "rsov", "台股 · 區間加跳空"),
]
fig, ax = plt.subplots(figsize=(9.5, 4.2))
for y, (asset, proxy, lab) in enumerate(CELLS):
    s = RES[asset]["proxies"][proxy]["regime_slope_test_expanding_median"]
    b, se, pv = s["slope_b"], s["se_b"], s["p_value_b"]
    lo, hi = b - 1.96 * se, b + 1.96 * se
    ax.plot([lo, hi], [y, y], color=ASY_C, lw=2.6, solid_capstyle="round")
    ax.plot(b, y, "o", color=ASY_C, ms=7)
    ax.text(hi + 0.02, y, f"落在運氣範圍內（{pv:.2f}）", va="center", fontsize=9, color="#444")
ax.axvline(0, color="#c00", lw=1.4, ls="--")
ax.text(0.008, len(CELLS) - 0.42, "0 = 兩種市況下差距一樣", fontsize=9, color="#c00")
ax.set_yticks(range(len(CELLS)))
ax.set_yticklabels([c[2] for c in CELLS], fontsize=10)
ax.set_ylim(-0.7, len(CELLS) - 0.15)
ax.set_xlim(-0.35, 0.95)
ax.invert_yaxis()
ax.set_xlabel("高恐慌相對低恐慌：兩派誤差差距的變化量（含 95% 區間）", fontsize=10)
ax.set_title("市況會不會改變勝負？四組檢定的區間全部蓋住 0", fontsize=12.5)
ax.grid(axis="x", alpha=0.25)
ax.set_axisbelow(True)
fig.text(0.5, 0.012, "資料：實驗 k1611。括號內為該組結果純屬運氣時仍會出現的機率。",
         ha="center", fontsize=8.2, color="#666")
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(OUT / "k1611_regime_slope_ci.png", dpi=150)
plt.close(fig)

print("wrote", OUT / "k1611_qlike_by_regime.png", OUT / "k1611_regime_slope_ci.png")
